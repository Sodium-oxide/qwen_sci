"""Independent, auditable Q1/Q2 mathematical-modeling workflow.

This workflow is deliberately outside the four-stage science state machine.
It consumes only a verified Idea sidecar and never changes ``idea_result_v5``
or the ExperimentDesign input.
"""

from __future__ import annotations

import json
import logging
import shutil
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from src.agents.quantitative_modeling.execution_policy import build_execution_authorization
from src.agents.quantitative_modeling.execution_ir_compiler import compile_execution_ir_from_model_spec
from src.agents.quantitative_modeling.hypothesis_refinement import (
    accept_hypothesis_refinement_proposal,
    build_hypothesis_refinement_proposal,
)
from src.agents.quantitative_modeling.mathir_compiler import compile_mathir_from_model_spec
from src.agents.quantitative_modeling.mathir_validator import (
    audit_quantitative_model,
    require_executable_model_audit,
)
from src.agents.quantitative_modeling.model_synthesis import synthesize_quantitative_model
from src.agents.quantitative_modeling.model_blueprint import synthesize_quantitative_model_blueprint
from src.agents.quantitative_modeling.parameter_contracts import (
    ParameterContractError,
    approve_parameter_resolution_proposal,
    build_parameter_query_plan,
    build_parameter_resolution_proposal,
    model_blueprint_identity,
    normalize_approved_parameter_set,
    normalize_model_blueprint,
    normalize_parameter_evidence_collection,
)
from src.agents.quantitative_modeling.parameter_evidence.discovery import (
    discover_parameter_literature,
)
from src.agents.quantitative_modeling.parameter_evidence.extraction import (
    extract_parameter_evidence_candidates,
)
from src.agents.quantitative_modeling.parameter_evidence.fulltext import (
    PARAMETER_FULLTEXT_MANIFEST_SCHEMA_VERSION,
    fetch_open_access_fulltexts,
)
from src.agents.quantitative_modeling.parameter_evidence.providers import (
    AcademicMetadataProviders,
    ParameterEvidenceSettings,
)
from src.agents.quantitative_modeling.publisher.json_markdown_consistency import (
    validate_json_markdown_consistency,
)
from src.agents.quantitative_modeling.pde.convergence import build_refinement_plans
from src.agents.quantitative_modeling.result_ledger import append_result_ledger_entry
from src.agents.quantitative_modeling.result_qualification import qualify_simulation_result
from src.agents.quantitative_modeling.run_plan import build_simulation_run_plan, validate_simulation_run_plan
from src.agents.quantitative_modeling.sandbox_runner import execute_simulation_run_plan
from src.pipeline.quantitative_manifests import (
    QuantitativeManifestError,
    verify_quantitative_ideas_manifest,
)
from src.pipeline.science_manifests import (
    ScienceManifestError,
    verify_experiment_design_manifest,
    verify_idea_manifest,
    verify_survey_manifest,
)
from src.pipeline.science_run import (
    atomic_write_json,
    atomic_write_text,
    file_sha256,
    load_science_run,
    locked_science_run,
    science_run_paths,
)


QUANTITATIVE_WORKFLOW_MANIFEST_SCHEMA_VERSION = "quantitative_workflow_manifest_v1"
_LOGGER = logging.getLogger(__name__)


class QuantitativeWorkflowError(RuntimeError):
    """Raised when an isolated quantitative artifact cannot be safely published."""


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _compiled_execution_artifacts(specification: Mapping[str, object]) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Return legacy MathIR or the new execution IR envelope for one model."""

    compiled = compile_execution_ir_from_model_spec(specification)
    if compiled["kind"] == "MATHIR":
        return compiled["document"], None
    return None, compiled


def _text(value: object) -> str:
    return str(value or "").strip()


def _read_json(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise QuantitativeWorkflowError(f"Cannot read {label}: {exc}") from exc
    if not isinstance(value, Mapping):
        raise QuantitativeWorkflowError(f"{label} must be a JSON object")
    return dict(value)


def _write_json_once(path: Path, payload: Mapping[str, object]) -> Path:
    if path.exists():
        raise QuantitativeWorkflowError(f"Immutable quantitative artifact already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(path, dict(payload))
    return path


def _write_text_once(path: Path, value: str) -> Path:
    if path.exists():
        raise QuantitativeWorkflowError(f"Immutable quantitative artifact already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, value.rstrip() + "\n")
    return path


def _archive_pde_field_series(
    execution_dir: Path, scenario_results: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Move large PDE arrays out of JSON while retaining an immutable index."""

    artifacts: list[dict[str, Any]] = []
    for index, scenario in enumerate(scenario_results, start=1):
        result = _mapping(scenario.get("result"))
        raw_series = result.get("field_series")
        if not isinstance(raw_series, Mapping):
            continue
        try:
            import numpy as np
        except ImportError as exc:
            raise QuantitativeWorkflowError("PDE field archiving requires numpy") from exc
        arrays = {str(field_id): np.asarray(values, dtype=float) for field_id, values in raw_series.items()}
        if not arrays or any(array.ndim < 2 for array in arrays.values()):
            raise QuantitativeWorkflowError("PDE field_series must contain snapshot arrays")
        archive_path = execution_dir / f"field_series_{index:02d}.npz"
        staging_path = execution_dir / f".field_series_{index:02d}.npz.staging"
        payload: dict[str, Any] = {f"field_{field_id}": array for field_id, array in arrays.items()}
        for coordinate in ("x", "y", "time"):
            if coordinate in result:
                payload[coordinate] = np.asarray(result[coordinate], dtype=float)
        try:
            with staging_path.open("wb") as handle:
                np.savez_compressed(handle, **payload)
            staging_path.replace(archive_path)
        except OSError as exc:
            staging_path.unlink(missing_ok=True)
            raise QuantitativeWorkflowError(f"cannot archive PDE field series: {exc}") from exc
        result.pop("field_series", None)
        result["field_series_artifact"] = {
            "path": str(archive_path.resolve()),
            "format": "NPZ",
            "fields": sorted(arrays),
            "shape": {field_id: list(array.shape) for field_id, array in arrays.items()},
            "sha256": file_sha256(archive_path),
        }
        scenario["result"] = result
        artifacts.append(dict(result["field_series_artifact"]))
    return artifacts


def _require_under(path: Path, root: Path, *, label: str) -> Path:
    resolved = path.expanduser().resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise QuantitativeWorkflowError(f"{label} must remain under the science run directory") from exc
    return resolved


def _load_run_raw(run_dir: str | Path) -> tuple[Path, dict[str, Any], dict[str, Any]]:
    paths = science_run_paths(run_dir)
    try:
        metadata, state = load_science_run(paths)
    except Exception as exc:
        raise QuantitativeWorkflowError(f"Cannot load science run: {exc}") from exc
    return paths.run_dir, metadata, state


def require_experiment_design_completed(run_dir: str | Path) -> Path:
    """Require the main science branch to finish DESIGN_ONLY ExperimentDesign."""

    root, metadata, state = _load_run_raw(run_dir)
    stages = _mapping(state.get("stages"))
    topic = _text(_mapping(metadata.get("immutable_inputs")).get("topic"))

    def current_stage_manifest_path(stage_name: str, directory_name: str) -> Path:
        stage = _mapping(stages.get(stage_name))
        if stage.get("status") != "COMPLETED":
            raise QuantitativeWorkflowError(
                f"quantitative modeling requires a completed {stage_name} stage"
            )
        raw_path = _text(stage.get("result_manifest_path"))
        if not raw_path:
            raise QuantitativeWorkflowError(f"completed {stage_name} has no result manifest path")
        path = Path(raw_path).expanduser()
        if not path.is_absolute():
            raise QuantitativeWorkflowError(
                f"completed {stage_name} result manifest path must be absolute"
            )
        path = path.resolve()
        try:
            path.relative_to((root / directory_name).resolve())
        except ValueError as exc:
            raise QuantitativeWorkflowError(
                f"completed {stage_name} manifest escapes the science run"
            ) from exc
        if not path.is_file():
            raise QuantitativeWorkflowError(f"completed {stage_name} manifest is missing")
        expected_sha256 = _text(_mapping(stage.get("result_identity")).get("result_sha256"))
        if not expected_sha256 or file_sha256(path) != expected_sha256:
            raise QuantitativeWorkflowError(
                f"completed {stage_name} manifest fingerprint no longer matches science state"
            )
        return path

    idea_stage = _mapping(stages.get("idea"))
    if idea_stage.get("status") != "COMPLETED":
        raise QuantitativeWorkflowError(
            "quantitative modeling requires a completed Idea stage before ExperimentDesign"
        )
    design_stage = _mapping(stages.get("exp_design"))
    if design_stage.get("status") != "COMPLETED":
        raise QuantitativeWorkflowError(
            "WAITING_FOR_EXPERIMENT_DESIGN: quantitative modeling starts only after "
            "ExperimentDesign is COMPLETED"
        )
    survey_manifest_path = current_stage_manifest_path("survey", "survey")
    idea_manifest_path = current_stage_manifest_path("idea", "idea")
    manifest_path = current_stage_manifest_path("exp_design", "experiment_design")
    try:
        survey_manifest = verify_survey_manifest(survey_manifest_path, expected_topic=topic)
        idea_manifest = verify_idea_manifest(
            idea_manifest_path,
            expected_survey_identity=survey_manifest.identity,
            expected_topic=topic,
        )
        verify_experiment_design_manifest(
            manifest_path,
            expected_survey_identity=idea_manifest.identity,
            expected_topic=topic,
        )
    except ScienceManifestError as exc:
        raise QuantitativeWorkflowError(
            f"ExperimentDesign manifest validation failed: {exc}"
        ) from exc
    return manifest_path


def _load_run(run_dir: str | Path) -> tuple[Path, dict[str, Any], dict[str, Any]]:
    root, metadata, state = _load_run_raw(run_dir)
    require_experiment_design_completed(root)
    return root, metadata, state


def _workflow_root(run_dir: Path) -> Path:
    return run_dir / "quantitative"


def _version_directory(run_dir: Path, quantitative_idea_id: str, version: int) -> Path:
    if quantitative_idea_id not in {"Q1", "Q2"} or version < 0 or version > 2:
        raise QuantitativeWorkflowError("quantitative idea version must identify Q1/Q2 at v0, v1, or v2")
    return _workflow_root(run_dir) / quantitative_idea_id / f"v{version}"


def _parameter_evidence_directory(run_dir: Path, quantitative_idea_id: str, version: int) -> Path:
    _version_directory(run_dir, quantitative_idea_id, version)
    return _workflow_root(run_dir) / quantitative_idea_id / "parameter_evidence" / f"v{version}"


def _artifact_record(path: Path) -> dict[str, str]:
    if not path.is_file():
        raise QuantitativeWorkflowError(f"required parameter artifact is missing: {path}")
    return {"path": str(path.resolve()), "sha256": file_sha256(path)}


def _revision_context_for_version(
    *, root: Path, quantitative_idea_id: str, version: int, version_dir: Path
) -> tuple[Path | None, dict[str, Any]]:
    """Verify v1/v2 acceptance and expose only the accepted proposal fields."""

    if version == 0:
        return None, {}
    acceptance_path = version_dir / "revision_acceptance.json"
    if not acceptance_path.is_file():
        raise QuantitativeWorkflowError(
            "Q revisions require an explicitly accepted refinement proposal before parameter planning"
        )
    acceptance = _read_json(acceptance_path, label="revision acceptance")
    if (
        acceptance.get("approval_status") != "ACCEPTED"
        or acceptance.get("quantitative_idea_id") != quantitative_idea_id
        or acceptance.get("version") != version
        or acceptance.get("parent_version") != version - 1
        or acceptance.get("requires_new_execution") is not True
    ):
        raise QuantitativeWorkflowError("revision acceptance does not authorize this Q parameter version")
    proposal_path = Path(_text(acceptance.get("proposal_path"))).expanduser().resolve()
    expected_proposal = _version_directory(root, quantitative_idea_id, version - 1) / "hypothesis_refinement_proposal.json"
    if proposal_path != expected_proposal.resolve() or not proposal_path.is_file():
        raise QuantitativeWorkflowError("revision acceptance proposal path is invalid")
    if file_sha256(proposal_path) != _text(acceptance.get("proposal_sha256")):
        raise QuantitativeWorkflowError("revision acceptance proposal hash no longer matches")
    proposal = _read_json(proposal_path, label="accepted hypothesis refinement proposal")
    if proposal.get("approval_status") != "PROPOSED" or proposal.get("requires_new_execution") is not True:
        raise QuantitativeWorkflowError("accepted hypothesis refinement proposal is invalid")
    return acceptance_path, {
        "hypothesis_delta": _text(proposal.get("hypothesis_delta")),
        "model_delta": list(proposal.get("model_delta") or []),
        "parameter_or_boundary_delta": list(proposal.get("parameter_or_boundary_delta") or []),
        "expected_discriminating_result": _text(proposal.get("expected_discriminating_result")),
        "falsification_condition": _text(proposal.get("falsification_condition")),
        "accepted_proposal_path": str(proposal_path),
        "accepted_proposal_sha256": file_sha256(proposal_path),
    }


def _parameter_version_context(
    *,
    run_dir: str | Path,
    quantitative_ideas_manifest_path: str | Path,
    quantitative_idea_id: str,
    version: int,
) -> tuple[Path, dict[str, Any], dict[str, Any], Path, dict[str, Any], dict[str, Any], Path, Path, dict[str, Any]]:
    """Resolve the immutable Q inputs shared by parameter and model stages."""

    root, metadata, state = _load_run(run_dir)
    _require_unfinalized(root, quantitative_idea_id)
    version_dir = _version_directory(root, quantitative_idea_id, version)
    if version == 0:
        if version_dir.exists():
            raise QuantitativeWorkflowError(f"Quantitative model version already exists: {version_dir}")
        created_from_artifact: Path | None = None
        revision_context: dict[str, Any] = {}
    else:
        if not version_dir.is_dir():
            raise QuantitativeWorkflowError("accepted Q revision directory is missing")
        created_from_artifact, revision_context = _revision_context_for_version(
            root=root,
            quantitative_idea_id=quantitative_idea_id,
            version=version,
            version_dir=version_dir,
        )
        existing_non_acceptance = [child for child in version_dir.iterdir() if child.name != "revision_acceptance.json"]
        if existing_non_acceptance:
            raise QuantitativeWorkflowError("the accepted Q revision has already been materialized")
    idea, sidecar, sidecar_manifest = _verified_idea(
        run_dir=root,
        quantitative_ideas_manifest_path=quantitative_ideas_manifest_path,
        quantitative_idea_id=quantitative_idea_id,
    )
    workflow_manifest = _write_workflow_manifest(
        run_dir=root,
        metadata=metadata,
        sidecar_manifest=sidecar_manifest,
    )
    lineage = _lineage(
        metadata=metadata,
        sidecar=sidecar,
        quantitative_idea_id=quantitative_idea_id,
        version=version,
        created_from_artifact=created_from_artifact or sidecar_manifest,
    )
    return (
        root,
        metadata,
        state,
        workflow_manifest,
        idea,
        lineage,
        version_dir,
        _parameter_evidence_directory(root, quantitative_idea_id, version),
        revision_context,
    )


def _require_unfinalized(run_dir: Path, quantitative_idea_id: str) -> None:
    if (_workflow_root(run_dir) / quantitative_idea_id / "finalization.json").is_file():
        raise QuantitativeWorkflowError(
            "this quantitative idea has already been finalized and cannot be revised or re-executed"
        )


def _verified_idea(
    *, run_dir: Path, quantitative_ideas_manifest_path: str | Path, quantitative_idea_id: str
) -> tuple[dict[str, Any], dict[str, Any], Path]:
    try:
        verified = verify_quantitative_ideas_manifest(quantitative_ideas_manifest_path)
    except QuantitativeManifestError as exc:
        raise QuantitativeWorkflowError(f"Quantitative Idea sidecar is invalid: {exc}") from exc
    _require_under(verified.manifest_path, run_dir, label="quantitative ideas manifest")
    if verified.payload.get("generation_status") != "READY":
        raise QuantitativeWorkflowError("Quantitative Idea sidecar has no executable candidate")
    for candidate in verified.payload["ideas"]:
        idea = _mapping(candidate)
        if idea.get("quantitative_idea_id") == quantitative_idea_id:
            if idea.get("execution_readiness") != "EXECUTABLE_CANDIDATE":
                raise QuantitativeWorkflowError("Quantitative Idea is not executable")
            return idea, dict(verified.payload), verified.manifest_path
    raise QuantitativeWorkflowError(f"Quantitative Idea {quantitative_idea_id} is not in the verified sidecar")


def _lineage(
    *,
    metadata: Mapping[str, object],
    sidecar: Mapping[str, object],
    quantitative_idea_id: str,
    version: int,
    created_from_artifact: Path,
) -> dict[str, Any]:
    source_identity = _mapping(sidecar.get("source_identity"))
    immutable_inputs = _mapping(metadata.get("immutable_inputs"))
    run_id = _text(metadata.get("science_run_id"))
    if not run_id:
        raise QuantitativeWorkflowError("science_run.json has no science_run_id")
    return {
        "science_run_id": run_id,
        "survey_run_id": _text(source_identity.get("survey_run_id")),
        "project_id": _text(source_identity.get("project_id")),
        "project_context_fingerprint": _text(source_identity.get("project_context_fingerprint")),
        "selected_direction_id": _text(source_identity.get("selected_direction_id")),
        "quantitative_idea_id": quantitative_idea_id,
        "version": version,
        "parent_version": None if version == 0 else version - 1,
        "created_from_artifact": str(created_from_artifact),
        "topic": _text(immutable_inputs.get("topic")),
    }


def _write_workflow_manifest(
    *, run_dir: Path, metadata: Mapping[str, object], sidecar_manifest: Path
) -> Path:
    root = _workflow_root(run_dir)
    path = root / "quantitative_workflow_manifest.json"
    payload = {
        "schema_version": QUANTITATIVE_WORKFLOW_MANIFEST_SCHEMA_VERSION,
        "science_run_id": _text(metadata.get("science_run_id")),
        "quantitative_ideas_manifest": {
            "path": str(sidecar_manifest),
            "sha256": file_sha256(sidecar_manifest),
        },
    }
    if path.exists():
        current = _read_json(path, label="quantitative workflow manifest")
        if current != payload:
            raise QuantitativeWorkflowError("quantitative workflow manifest is bound to a different Idea sidecar")
        return path
    return _write_json_once(path, payload)


def _load_parameter_blueprint(
    *, root: Path, quantitative_idea_id: str, version: int
) -> tuple[dict[str, Any], Path]:
    path = _parameter_evidence_directory(root, quantitative_idea_id, version) / "model_blueprint.json"
    try:
        blueprint = normalize_model_blueprint(_read_json(path, label="quantitative model blueprint"))
    except ParameterContractError as error:
        raise QuantitativeWorkflowError(f"quantitative model blueprint is invalid: {error}") from error
    if blueprint["lineage"]["quantitative_idea_id"] != quantitative_idea_id or blueprint["lineage"]["version"] != version:
        raise QuantitativeWorkflowError("quantitative model blueprint identity differs from requested Q version")
    return blueprint, path


def _load_parameter_evidence_collections(evidence_dir: Path) -> list[dict[str, Any]]:
    extraction_dir = evidence_dir / "extractions"
    if not extraction_dir.is_dir():
        return []
    collections: list[dict[str, Any]] = []
    for path in sorted(extraction_dir.glob("extract-*.json")):
        try:
            collections.append(normalize_parameter_evidence_collection(_read_json(path, label="parameter evidence collection")))
        except ParameterContractError as error:
            raise QuantitativeWorkflowError(f"parameter evidence collection is invalid: {error}") from error
    return collections


def _load_fulltext_document(evidence_dir: Path, document_id: str) -> dict[str, Any] | None:
    manifest_path = evidence_dir / "fulltext" / "fulltext_manifest.json"
    if manifest_path.is_file():
        manifest = _read_json(manifest_path, label="parameter full-text manifest")
        if manifest.get("schema_version") != PARAMETER_FULLTEXT_MANIFEST_SCHEMA_VERSION:
            raise QuantitativeWorkflowError("parameter full-text manifest schema is unsupported")
        for raw_document in manifest.get("documents") or []:
            document = _mapping(raw_document)
            if _text(document.get("document_id")) == document_id:
                return document
    user_document_path = evidence_dir / "user_documents" / f"{document_id}.json"
    if user_document_path.is_file():
        return _read_json(user_document_path, label="user-provided parameter document")
    return None


def prepare_quantitative_model_blueprint(
    *,
    run_dir: str | Path,
    quantitative_ideas_manifest_path: str | Path,
    quantitative_idea_id: str,
    version: int,
    llm_call: Callable[[str], object],
) -> dict[str, str]:
    """Create the immutable, non-numeric parameter contract for one Q version."""

    (
        _root,
        _metadata,
        _state,
        workflow_manifest,
        idea,
        lineage,
        _version_dir,
        evidence_dir,
        revision_context,
    ) = _parameter_version_context(
        run_dir=run_dir,
        quantitative_ideas_manifest_path=quantitative_ideas_manifest_path,
        quantitative_idea_id=quantitative_idea_id,
        version=version,
    )
    blueprint_path = evidence_dir / "model_blueprint.json"
    if blueprint_path.exists():
        raise QuantitativeWorkflowError(f"quantitative model blueprint already exists: {blueprint_path}")
    try:
        blueprint = synthesize_quantitative_model_blueprint(
            quantitative_idea=idea,
            lineage=lineage,
            revision_context=revision_context,
            llm_call=llm_call,
        )
        query_plan = build_parameter_query_plan(blueprint=blueprint)
    except (ParameterContractError, ValueError) as error:
        raise QuantitativeWorkflowError(f"cannot prepare quantitative model blueprint: {error}") from error
    paths = {
        "workflow_manifest": workflow_manifest,
        "blueprint": _write_json_once(blueprint_path, blueprint),
        "query_plan": _write_json_once(evidence_dir / "parameter_query_plan.json", query_plan),
    }
    return {name: str(path) for name, path in paths.items()}


def discover_quantitative_parameter_evidence(
    *,
    run_dir: str | Path,
    quantitative_idea_id: str,
    version: int,
    fetch: bool,
    runtime_config: object,
) -> Path:
    """Use academic metadata APIs only after explicit network-fetch authorization."""

    if not fetch:
        raise QuantitativeWorkflowError("parameter discovery requires explicit --fetch authorization")
    root, _metadata, _state = _load_run(run_dir)
    _require_unfinalized(root, quantitative_idea_id)
    blueprint, _blueprint_path = _load_parameter_blueprint(
        root=root, quantitative_idea_id=quantitative_idea_id, version=version
    )
    evidence_dir = _parameter_evidence_directory(root, quantitative_idea_id, version)
    discovery_path = evidence_dir / "discovery" / "parameter_discovery.json"
    if discovery_path.exists():
        raise QuantitativeWorkflowError("parameter discovery is immutable and already exists")
    settings = ParameterEvidenceSettings.from_runtime_config(runtime_config)
    discovery = discover_parameter_literature(
        blueprint=blueprint,
        providers=AcademicMetadataProviders(settings),
    )
    return _write_json_once(discovery_path, discovery)


def fetch_quantitative_parameter_fulltext(
    *,
    run_dir: str | Path,
    quantitative_idea_id: str,
    version: int,
    fetch: bool,
    runtime_config: object,
) -> Path:
    """Acquire only provider-declared OA PDFs after explicit network authorization."""

    if not fetch:
        raise QuantitativeWorkflowError("parameter full-text acquisition requires explicit --fetch authorization")
    root, _metadata, _state = _load_run(run_dir)
    _require_unfinalized(root, quantitative_idea_id)
    blueprint, _blueprint_path = _load_parameter_blueprint(
        root=root, quantitative_idea_id=quantitative_idea_id, version=version
    )
    evidence_dir = _parameter_evidence_directory(root, quantitative_idea_id, version)
    discovery_path = evidence_dir / "discovery" / "parameter_discovery.json"
    discovery = _read_json(discovery_path, label="parameter discovery")
    manifest_path = evidence_dir / "fulltext" / "fulltext_manifest.json"
    if manifest_path.exists():
        raise QuantitativeWorkflowError("parameter full-text manifest is immutable and already exists")
    fulltext = fetch_open_access_fulltexts(
        blueprint=blueprint,
        discovery=discovery,
        output_directory=manifest_path.parent / "documents",
        settings=ParameterEvidenceSettings.from_runtime_config(runtime_config),
    )
    return _write_json_once(manifest_path, fulltext)


def register_quantitative_parameter_document(
    *,
    run_dir: str | Path,
    quantitative_idea_id: str,
    version: int,
    document_path: str | Path,
    document_id: str,
    title: str,
    doi: str = "",
    year: int | None = None,
) -> Path:
    """Copy one user-provided local document into the controlled evidence tree."""

    root, _metadata, _state = _load_run(run_dir)
    _require_unfinalized(root, quantitative_idea_id)
    _blueprint, _blueprint_path = _load_parameter_blueprint(
        root=root, quantitative_idea_id=quantitative_idea_id, version=version
    )
    source = Path(document_path).expanduser().resolve()
    if not source.is_file() or source.suffix.casefold() not in {".pdf", ".txt", ".md", ".csv"}:
        raise QuantitativeWorkflowError("user-provided parameter document must be an existing PDF, TXT, MD, or CSV file")
    normalized_document_id = _text(document_id)
    if not normalized_document_id or any(character not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-" for character in normalized_document_id):
        raise QuantitativeWorkflowError("user-provided parameter document_id must use only letters, numbers, underscores, or hyphens")
    normalized_title = _text(title)
    if not normalized_title:
        raise QuantitativeWorkflowError("user-provided parameter document title is required")
    if year is not None and (isinstance(year, bool) or int(year) < 1):
        raise QuantitativeWorkflowError("user-provided parameter document year must be a positive integer when supplied")
    evidence_dir = _parameter_evidence_directory(root, quantitative_idea_id, version)
    target_dir = evidence_dir / "user_documents"
    record_path = target_dir / f"{normalized_document_id}.json"
    target_path = target_dir / f"{normalized_document_id}{source.suffix.casefold()}"
    if record_path.exists() or target_path.exists():
        raise QuantitativeWorkflowError("user-provided parameter document ID is already registered")
    target_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target_path)
    record = {
        "document_id": normalized_document_id,
        "path": str(target_path.resolve()),
        "sha256": file_sha256(target_path),
        "title": normalized_title,
        "doi": _text(doi),
        "year": int(year) if year is not None else None,
        "discovery_sources": ["user_provided"],
        "cross_validated": False,
        "parameter_request_ids": [],
        "evidence_status": "USER_PROVIDED",
        "retrieval_source": "USER_PROVIDED",
    }
    return _write_json_once(record_path, record)


def extract_quantitative_parameter_candidates(
    *,
    run_dir: str | Path,
    quantitative_idea_id: str,
    version: int,
    document_id: str,
    llm_call: Callable[[str], object],
    maximum_characters: int = 40_000,
) -> Path:
    """Extract one immutable candidate collection from a controlled document."""

    root, _metadata, _state = _load_run(run_dir)
    with locked_science_run(science_run_paths(root)):
        _require_unfinalized(root, quantitative_idea_id)
        blueprint, _blueprint_path = _load_parameter_blueprint(
            root=root, quantitative_idea_id=quantitative_idea_id, version=version
        )
        evidence_dir = _parameter_evidence_directory(root, quantitative_idea_id, version)
        document = _load_fulltext_document(evidence_dir, _text(document_id))
        if document is None:
            raise QuantitativeWorkflowError("parameter evidence document_id is not registered in this Q version")
        source_path = Path(_text(document.get("path"))).expanduser().resolve()
        if not source_path.is_file() or file_sha256(source_path) != _text(document.get("sha256")):
            raise QuantitativeWorkflowError("parameter evidence document content no longer matches its manifest")
        counters: dict[str, int] = {}
        for collection in _load_parameter_evidence_collections(evidence_dir):
            for candidate in collection["candidates"]:
                parameter_id = candidate["parameter_id"]
                try:
                    counter = int(str(candidate["candidate_id"]).rsplit("-", 1)[1])
                except (IndexError, ValueError):
                    raise QuantitativeWorkflowError("existing parameter evidence candidate ID is malformed")
                counters[parameter_id] = max(counters.get(parameter_id, 0), counter)
        collection = extract_parameter_evidence_candidates(
            blueprint=blueprint,
            source_document=document,
            llm_call=llm_call,
            next_candidate_numbers=counters,
            maximum_characters=maximum_characters,
        )
        extraction_dir = evidence_dir / "extractions"
        index = len(list(extraction_dir.glob("extract-*.json"))) + 1 if extraction_dir.is_dir() else 1
        return _write_json_once(extraction_dir / f"extract-{index:03d}.json", collection)


def propose_quantitative_parameter_resolution(
    *,
    run_dir: str | Path,
    quantitative_idea_id: str,
    version: int,
    selections: object,
) -> Path:
    """Build a reviewable selection proposal; it does not grant numerical use."""

    root, _metadata, _state = _load_run(run_dir)
    _require_unfinalized(root, quantitative_idea_id)
    blueprint, _blueprint_path = _load_parameter_blueprint(
        root=root, quantitative_idea_id=quantitative_idea_id, version=version
    )
    evidence_dir = _parameter_evidence_directory(root, quantitative_idea_id, version)
    proposal_path = evidence_dir / "parameter_resolution_proposal.json"
    if proposal_path.exists():
        raise QuantitativeWorkflowError("parameter resolution proposal is immutable and already exists")
    try:
        proposal = build_parameter_resolution_proposal(
            blueprint=blueprint,
            evidence_collections=_load_parameter_evidence_collections(evidence_dir),
            selections=selections,
        )
    except ParameterContractError as error:
        raise QuantitativeWorkflowError(f"parameter resolution proposal is invalid: {error}") from error
    return _write_json_once(proposal_path, proposal)


def approve_quantitative_parameter_resolution(
    *,
    run_dir: str | Path,
    quantitative_idea_id: str,
    version: int,
    approve: bool,
) -> dict[str, str]:
    """Freeze a complete, explicitly approved parameter set without executing anything."""

    root, _metadata, _state = _load_run(run_dir)
    _require_unfinalized(root, quantitative_idea_id)
    blueprint, _blueprint_path = _load_parameter_blueprint(
        root=root, quantitative_idea_id=quantitative_idea_id, version=version
    )
    evidence_dir = _parameter_evidence_directory(root, quantitative_idea_id, version)
    proposal_path = evidence_dir / "parameter_resolution_proposal.json"
    approved_path = evidence_dir / "approved_parameter_set.json"
    manifest_path = evidence_dir / "approved_parameter_set_manifest.json"
    if approved_path.exists() or manifest_path.exists():
        raise QuantitativeWorkflowError("approved parameter set is immutable and already exists")
    try:
        approved = approve_parameter_resolution_proposal(
            _read_json(proposal_path, label="parameter resolution proposal"),
            approve=approve,
        )
        approved = normalize_approved_parameter_set(approved)
    except ParameterContractError as error:
        raise QuantitativeWorkflowError(f"parameter resolution approval failed: {error}") from error
    if approved["blueprint_identity"] != model_blueprint_identity(blueprint) or approved["lineage"] != blueprint["lineage"]:
        raise QuantitativeWorkflowError("approved parameter set does not bind to this model blueprint")
    requests = {request["parameter_id"]: request for request in blueprint["parameter_requests"]}
    entries = {entry["parameter_id"]: entry for entry in approved["entries"]}
    if set(entries) != set(requests):
        raise QuantitativeWorkflowError("approved parameter set must resolve exactly every blueprint parameter request")
    for parameter_id, request in requests.items():
        entry = entries[parameter_id]
        if (
            entry["mathir_symbol"] != request["mathir_symbol"]
            or entry["unit"] != request["unit"]
            or entry["dimension"] != request["dimension"]
            or entry["role"] != request["role"]
        ):
            raise QuantitativeWorkflowError("approved parameter set entry differs from its blueprint request")
        if (
            entry["provenance_status"] == "APPROVED_MODEL_ASSUMPTION"
            and request["evidence_requirement"]
            not in {"LITERATURE_PREFERRED", "MODEL_ASSUMPTION_ALLOWED"}
        ):
            raise QuantitativeWorkflowError("model assumption approval is not permitted for this parameter request")
    _write_json_once(approved_path, approved)
    manifest = {
        "schema_version": "quantitative_approved_parameter_set_manifest_v1",
        "parameter_set_identity": approved["parameter_set_identity"],
        "blueprint_identity": approved["blueprint_identity"],
        "lineage": approved["lineage"],
        "artifacts": {"approved_parameter_set": _artifact_record(approved_path)},
    }
    _write_json_once(manifest_path, manifest)
    return {"parameter_set": str(approved_path), "manifest": str(manifest_path)}


def materialize_quantitative_model_version(
    *,
    run_dir: str | Path,
    quantitative_ideas_manifest_path: str | Path,
    quantitative_idea_id: str,
    version: int,
    llm_call: Callable[[str], object],
    scenarios: object = None,
    resource_limits: Mapping[str, object] | None = None,
) -> dict[str, str]:
    """Create an executable model only from one frozen approved parameter set."""

    (
        root,
        _metadata,
        _state,
        workflow_manifest,
        idea,
        lineage,
        version_dir,
        evidence_dir,
        revision_context,
    ) = _parameter_version_context(
        run_dir=run_dir,
        quantitative_ideas_manifest_path=quantitative_ideas_manifest_path,
        quantitative_idea_id=quantitative_idea_id,
        version=version,
    )
    blueprint, _blueprint_path = _load_parameter_blueprint(
        root=root, quantitative_idea_id=quantitative_idea_id, version=version
    )
    if blueprint["lineage"] != {field: lineage.get(field) for field in blueprint["lineage"]}:
        raise QuantitativeWorkflowError("model blueprint lineage differs from the current Q version")
    if blueprint["revision_context"] != revision_context:
        raise QuantitativeWorkflowError("model blueprint did not preserve the accepted refinement context")
    approved_path = evidence_dir / "approved_parameter_set.json"
    parameter_manifest_path = evidence_dir / "approved_parameter_set_manifest.json"
    try:
        approved = normalize_approved_parameter_set(_read_json(approved_path, label="approved parameter set"))
    except ParameterContractError as error:
        raise QuantitativeWorkflowError(f"approved parameter set is invalid: {error}") from error
    if approved["blueprint_identity"] != model_blueprint_identity(blueprint) or approved["lineage"] != blueprint["lineage"]:
        raise QuantitativeWorkflowError("approved parameter set belongs to a different model blueprint")
    parameter_manifest = _read_json(parameter_manifest_path, label="approved parameter set manifest")
    if (
        parameter_manifest.get("parameter_set_identity") != approved["parameter_set_identity"]
        or _mapping(parameter_manifest.get("artifacts")).get("approved_parameter_set") != _artifact_record(approved_path)
    ):
        raise QuantitativeWorkflowError("approved parameter set manifest no longer matches its set")
    synthesized = synthesize_quantitative_model(
        quantitative_idea=idea,
        lineage=lineage,
        llm_call=llm_call,
        model_blueprint=blueprint,
        approved_parameter_set=approved,
        revision_context=revision_context,
        execution_scenarios=scenarios,
    )
    consistent = validate_json_markdown_consistency(
        synthesized["model_spec"],
        synthesized["markdown"],
    )
    audit = audit_quantitative_model(consistent["model_spec"])
    require_executable_model_audit(audit)
    mathir, execution_ir = _compiled_execution_artifacts(consistent["model_spec"])
    model_identity = {
        **consistent["model_spec"]["lineage"],
        "model_spec_identity": synthesized["model_spec_identity"],
        "parameter_set_identity": approved["parameter_set_identity"],
    }
    plan_kwargs: dict[str, Any] = {
        "model_identity": model_identity,
        "scenarios": scenarios,
        "resource_limits": resource_limits,
        "parameter_set": approved,
        "parameter_set_manifest": _artifact_record(parameter_manifest_path),
    }
    if execution_ir is None:
        plan_kwargs["mathir"] = mathir
    else:
        plan_kwargs["execution_ir"] = execution_ir
    plan = build_simulation_run_plan(**plan_kwargs)
    paths = {
        "workflow_manifest": workflow_manifest,
        "model_spec": _write_json_once(version_dir / "quantitative_model_spec.json", consistent["model_spec"]),
        "markdown": _write_text_once(version_dir / "mathematical_model.md", consistent["markdown"]),
        **(
            {"mathir": _write_json_once(version_dir / "mathir.json", mathir)}
            if mathir is not None
            else {"execution_ir": _write_json_once(version_dir / "execution_ir.json", execution_ir)}
        ),
        "audit": _write_json_once(version_dir / "model_audit_report.json", audit),
        "capability": _write_json_once(version_dir / "capability_assessment.json", audit["capability"]),
        "plan": _write_json_once(version_dir / "simulation_run_plan.json", plan),
    }
    _LOGGER.info(
        "quantitative model artifact written idea_id=%s version=%d artifact_count=%d",
        quantitative_idea_id,
        version,
        len(paths),
    )
    return {name: str(path) for name, path in paths.items()}


def prepare_quantitative_model_version(
    *,
    run_dir: str | Path,
    quantitative_ideas_manifest_path: str | Path,
    quantitative_idea_id: str,
    version: int,
    llm_call: Callable[[str], object],
    scenarios: object = None,
    resource_limits: Mapping[str, object] | None = None,
) -> dict[str, str]:
    """Synthesize, format-check, audit, and plan one immutable Q version.

    This operation does not run a solver.  The returned plan must later be
    confirmed explicitly through ``--execute``.
    """

    root, metadata, _state = _load_run(run_dir)
    _require_unfinalized(root, quantitative_idea_id)
    version_dir = _version_directory(root, quantitative_idea_id, version)
    revision_context: dict[str, Any] = {}
    if _parameter_evidence_directory(root, quantitative_idea_id, version).exists():
        raise QuantitativeWorkflowError(
            "this Q version has started evidence-bound parameter planning; use materialize_quantitative_model_version"
        )
    if version == 0:
        if version_dir.exists():
            raise QuantitativeWorkflowError(f"Quantitative model version already exists: {version_dir}")
        created_from_artifact: Path | None = None
    else:
        acceptance_path, revision_context = _revision_context_for_version(
            root=root,
            quantitative_idea_id=quantitative_idea_id,
            version=version,
            version_dir=version_dir,
        )
        if acceptance_path is None:
            raise QuantitativeWorkflowError("accepted Q revision has no acceptance artifact")
        existing_non_acceptance = [
            child for child in version_dir.iterdir() if child.name != "revision_acceptance.json"
        ]
        if existing_non_acceptance:
            raise QuantitativeWorkflowError("the accepted Q revision has already been materialized")
        created_from_artifact = acceptance_path
    idea, sidecar, sidecar_manifest = _verified_idea(
        run_dir=root,
        quantitative_ideas_manifest_path=quantitative_ideas_manifest_path,
        quantitative_idea_id=quantitative_idea_id,
    )
    workflow_manifest = _write_workflow_manifest(
        run_dir=root,
        metadata=metadata,
        sidecar_manifest=sidecar_manifest,
    )
    lineage = _lineage(
        metadata=metadata,
        sidecar=sidecar,
        quantitative_idea_id=quantitative_idea_id,
        version=version,
        created_from_artifact=created_from_artifact or sidecar_manifest,
    )
    synthesized = synthesize_quantitative_model(
        quantitative_idea=idea,
        lineage=lineage,
        llm_call=llm_call,
        revision_context=revision_context,
    )
    consistent = validate_json_markdown_consistency(
        synthesized["model_spec"],
        synthesized["markdown"],
    )
    audit = audit_quantitative_model(consistent["model_spec"])
    require_executable_model_audit(audit)
    mathir, execution_ir = _compiled_execution_artifacts(consistent["model_spec"])
    model_identity = {
        **consistent["model_spec"]["lineage"],
        "model_spec_identity": synthesized["model_spec_identity"],
    }
    plan_kwargs = {
        "model_identity": model_identity,
        "scenarios": scenarios,
        "resource_limits": resource_limits,
    }
    if execution_ir is None:
        plan_kwargs["mathir"] = mathir
    else:
        plan_kwargs["execution_ir"] = execution_ir
    plan = build_simulation_run_plan(**plan_kwargs)
    paths = {
        "workflow_manifest": workflow_manifest,
        "model_spec": _write_json_once(version_dir / "quantitative_model_spec.json", consistent["model_spec"]),
        "markdown": _write_text_once(version_dir / "mathematical_model.md", consistent["markdown"]),
        **(
            {"mathir": _write_json_once(version_dir / "mathir.json", mathir)}
            if mathir is not None
            else {"execution_ir": _write_json_once(version_dir / "execution_ir.json", execution_ir)}
        ),
        "audit": _write_json_once(version_dir / "model_audit_report.json", audit),
        "capability": _write_json_once(version_dir / "capability_assessment.json", audit["capability"]),
        "plan": _write_json_once(version_dir / "simulation_run_plan.json", plan),
    }
    _LOGGER.info(
        "quantitative model artifact written idea_id=%s version=%d artifact_count=%d",
        quantitative_idea_id,
        version,
        len(paths),
    )
    return {name: str(path) for name, path in paths.items()}


def _load_plan(version_dir: Path) -> dict[str, Any]:
    return validate_simulation_run_plan(
        _read_json(version_dir / "simulation_run_plan.json", label="simulation run plan")
    )


def prepare_pde_convergence_plans(
    *,
    run_dir: str | Path,
    quantitative_idea_id: str,
    version: int,
    grid_multipliers: tuple[int, ...] = (1, 2, 4),
    time_step_divisors: tuple[int, ...] = (1,),
) -> dict[str, str]:
    """Persist identity-bound PDE refinement plans without executing them."""

    root, _metadata, _state = _load_run(run_dir)
    _require_unfinalized(root, quantitative_idea_id)
    version_dir = _version_directory(root, quantitative_idea_id, version)
    parent_plan = _load_plan(version_dir)
    plans = build_refinement_plans(
        parent_plan,
        grid_multipliers=grid_multipliers,
        time_step_divisors=time_step_divisors,
    )
    convergence_dir = version_dir / "convergence"
    if convergence_dir.exists():
        raise QuantitativeWorkflowError("PDE convergence plans already exist for this Q version")
    convergence_dir.mkdir(parents=True, exist_ok=False)
    plan_records: list[dict[str, Any]] = []
    for plan in plans:
        refinement_id = _text(_mapping(plan["model_identity"]).get("refinement_id"))
        plan_path = convergence_dir / f"{refinement_id}.json"
        _write_json_once(plan_path, plan)
        plan_records.append(
            {
                "refinement_id": refinement_id,
                "plan_identity": plan["plan_identity"],
                "path": str(plan_path),
                "requires_explicit_execution": True,
            }
        )
    manifest_path = convergence_dir / "convergence_manifest.json"
    manifest = {
        "schema_version": "pde_convergence_plan_manifest_v1",
        "parent_plan_identity": parent_plan["plan_identity"],
        "quantitative_idea_id": quantitative_idea_id,
        "version": version,
        "requires_explicit_execution": True,
        "plans": plan_records,
    }
    _write_json_once(manifest_path, manifest)
    return {"manifest": str(manifest_path), **{record["refinement_id"]: record["path"] for record in plan_records}}


def execute_quantitative_plan(
    *,
    run_dir: str | Path,
    quantitative_idea_id: str,
    version: int,
    execute: bool,
    confirmed_plan_identity: str,
) -> dict[str, str]:
    """Execute one immutable plan only after exact explicit authorization."""

    root, _metadata, _state = _load_run(run_dir)
    _require_unfinalized(root, quantitative_idea_id)
    version_dir = _version_directory(root, quantitative_idea_id, version)
    plan = _load_plan(version_dir)
    authorization = build_execution_authorization(
        plan=plan,
        confirmed_plan_identity=confirmed_plan_identity,
    )
    execution = execute_simulation_run_plan(
        plan,
        execute=execute,
        confirmed_plan_identity=confirmed_plan_identity,
    )
    execution_dir = version_dir / "executions" / str(execution["execution_id"])
    if execution_dir.exists():
        raise QuantitativeWorkflowError("simulation execution ID collision")
    execution_dir.mkdir(parents=True, exist_ok=False)
    scenario_results = [dict(item) for item in execution["scenario_results"]]
    field_series_artifacts = _archive_pde_field_series(execution_dir, scenario_results)
    result_payload = {
        "schema_version": "simulation_result_v1",
        "execution_id": execution["execution_id"],
        "plan_identity": execution["plan_identity"],
        "model_identity": execution["model_identity"],
        "scenario_results": scenario_results,
    }
    record = {key: value for key, value in execution.items() if key != "scenario_results"}
    paths = {
        "authorization": _write_json_once(execution_dir / "execution_authorization.json", authorization),
        "execution_record": _write_json_once(execution_dir / "execution_record.json", record),
        "simulation_result": _write_json_once(execution_dir / "simulation_result.json", result_payload),
    }
    if field_series_artifacts:
        paths["field_series_manifest"] = str(
            _write_json_once(
                execution_dir / "field_series_manifest.json",
                {
                    "schema_version": "pde_field_series_manifest_v1",
                    "execution_id": execution["execution_id"],
                    "artifacts": field_series_artifacts,
                },
            )
        )
    return {name: str(path) for name, path in paths.items()}


def qualify_quantitative_execution(
    *,
    run_dir: str | Path,
    quantitative_idea_id: str,
    version: int,
    execution_id: str,
    hypothesis_relation: str,
    result_summary: str,
) -> dict[str, str]:
    """Qualify one completed run and append it to the version's permanent ledger."""

    root, _metadata, _state = _load_run(run_dir)
    _require_unfinalized(root, quantitative_idea_id)
    version_dir = _version_directory(root, quantitative_idea_id, version)
    plan = _load_plan(version_dir)
    execution_dir = version_dir / "executions" / _text(execution_id)
    record_path = execution_dir / "execution_record.json"
    result_path = execution_dir / "simulation_result.json"
    record = _read_json(record_path, label="simulation execution record")
    result = _read_json(result_path, label="simulation result")
    execution = {**record, "scenario_results": result.get("scenario_results")}
    if _text(execution.get("plan_identity")) != _text(plan.get("plan_identity")):
        raise QuantitativeWorkflowError("execution record is bound to a different simulation run plan")
    qualification = qualify_simulation_result(
        execution,
        hypothesis_relation=hypothesis_relation,
        required_validation_checks=plan["qualification_requirements"],
    )
    qualification_path = _write_json_once(execution_dir / "result_qualification.json", qualification)
    ledger_path = version_dir / "result_ledger.json"
    ledger = _read_json(ledger_path, label="result ledger") if ledger_path.exists() else None
    updated_ledger = append_result_ledger_entry(
        ledger,
        execution=execution,
        qualification=qualification,
        result_summary=_text(result_summary),
        execution_record_path=str(record_path),
        qualification_path=str(qualification_path),
    )
    atomic_write_json(ledger_path, updated_ledger)
    return {"qualification": str(qualification_path), "ledger": str(ledger_path)}


def propose_quantitative_refinement(
    *,
    run_dir: str | Path,
    quantitative_idea_id: str,
    version: int,
    revision_reason: str,
    hypothesis_delta: str,
    model_delta: list[str],
    parameter_or_boundary_delta: list[str],
    expected_discriminating_result: str,
    falsification_condition: str,
) -> Path:
    """Publish an unaccepted revision proposal anchored to all qualified results."""

    root, _metadata, _state = _load_run(run_dir)
    _require_unfinalized(root, quantitative_idea_id)
    version_dir = _version_directory(root, quantitative_idea_id, version)
    ledger_path = version_dir / "result_ledger.json"
    if not ledger_path.is_file():
        raise QuantitativeWorkflowError("a qualified result ledger is required before proposing a revision")
    proposal = build_hypothesis_refinement_proposal(
        ledger=_read_json(ledger_path, label="result ledger"),
        revision_reason=revision_reason,
        hypothesis_delta=hypothesis_delta,
        model_delta=model_delta,
        parameter_or_boundary_delta=parameter_or_boundary_delta,
        expected_discriminating_result=expected_discriminating_result,
        falsification_condition=falsification_condition,
    )
    return _write_json_once(version_dir / "hypothesis_refinement_proposal.json", proposal)


def accept_quantitative_refinement(
    *,
    run_dir: str | Path,
    quantitative_idea_id: str,
    parent_version: int,
    accept: bool,
) -> Path:
    """Create only the authorization for v1/v2; it never executes a simulation."""

    root, _metadata, _state = _load_run(run_dir)
    _require_unfinalized(root, quantitative_idea_id)
    parent_dir = _version_directory(root, quantitative_idea_id, parent_version)
    proposal_path = parent_dir / "hypothesis_refinement_proposal.json"
    proposal = _read_json(proposal_path, label="hypothesis refinement proposal")
    acceptance = accept_hypothesis_refinement_proposal(proposal, accept=accept)
    target_dir = _version_directory(root, quantitative_idea_id, int(acceptance["version"]))
    if target_dir.exists():
        raise QuantitativeWorkflowError("target Q version already exists")
    target_dir.mkdir(parents=True, exist_ok=False)
    acceptance = {
        **acceptance,
        "proposal_path": str(proposal_path),
        "proposal_sha256": file_sha256(proposal_path),
    }
    return _write_json_once(target_dir / "revision_acceptance.json", acceptance)


def build_main_hypothesis_feedback_packet(*, run_dir: str | Path) -> Path:
    """Create a non-mutating packet for a future human-led Idea reconsideration."""

    root, metadata, _state = _load_run(run_dir)
    feedback: list[dict[str, Any]] = []
    for quantitative_idea_id in ("Q1", "Q2"):
        idea_root = _workflow_root(root) / quantitative_idea_id
        if not idea_root.is_dir():
            continue
        for version in range(3):
            ledger_path = idea_root / f"v{version}" / "result_ledger.json"
            if not ledger_path.is_file():
                continue
            ledger = _read_json(ledger_path, label="result ledger")
            entries = [entry for entry in ledger.get("entries", []) if entry.get("result_quality") == "QUALIFIED"]
            if not entries:
                continue
            feedback.append(
                {
                    "quantitative_idea_id": quantitative_idea_id,
                    "version": version,
                    "execution_mode": "NUMERICAL_SIMULATION",
                    "result_kind": "SIMULATED",
                    "empirical_claim_status": "NOT_EMPIRICAL",
                    "relations": [entry.get("hypothesis_relation") for entry in entries],
                    "result_summaries": [entry.get("result_summary") for entry in entries],
                    "instruction": "Human review may use this as a bounded input to a new Idea revision; it cannot rewrite idea_result_v5.",
                }
            )
    packet = {
        "schema_version": "main_hypothesis_feedback_packet_v1",
        "science_run_id": _text(metadata.get("science_run_id")),
        "mutates_idea_result_v5": False,
        "feedback": feedback,
    }
    return _write_json_once(_workflow_root(root) / "main_hypothesis_feedback_packet.json", packet)


__all__ = [
    "QUANTITATIVE_WORKFLOW_MANIFEST_SCHEMA_VERSION",
    "QuantitativeWorkflowError",
    "approve_quantitative_parameter_resolution",
    "execute_quantitative_plan",
    "accept_quantitative_refinement",
    "build_main_hypothesis_feedback_packet",
    "discover_quantitative_parameter_evidence",
    "extract_quantitative_parameter_candidates",
    "fetch_quantitative_parameter_fulltext",
    "materialize_quantitative_model_version",
    "prepare_pde_convergence_plans",
    "prepare_quantitative_model_blueprint",
    "prepare_quantitative_model_version",
    "propose_quantitative_parameter_resolution",
    "propose_quantitative_refinement",
    "qualify_quantitative_execution",
    "register_quantitative_parameter_document",
    "require_experiment_design_completed",
]
