"""Build finalization records and a minimal Author-facing quantitative sidecar."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from src.agents.quantitative_modeling.model_format import model_spec_identity, normalize_quantitative_model_spec
from src.agents.quantitative_modeling.parameter_contracts import (
    ParameterContractError,
    normalize_approved_parameter_set,
)
from src.agents.quantitative_modeling.publisher.json_markdown_consistency import (
    validate_json_markdown_consistency,
)
from src.agents.quantitative_modeling.result_ledger import qualified_ledger_entries, validate_result_ledger
from src.agents.research_plan_author.quantitative_evidence_adapter import (
    QUANTITATIVE_AUTHOR_HANDOFF_MANIFEST_SCHEMA_VERSION,
)
from src.agents.research_plan_author.quantitative_evidence_contracts import (
    QUANTITATIVE_AUTHOR_HANDOFF_SCHEMA_VERSION,
    validate_quantitative_author_handoff,
)
from src.pipeline.quantitative_manifests import QuantitativeManifestError, verify_quantitative_ideas_manifest
from src.pipeline.quantitative_workflow import QuantitativeWorkflowError, require_experiment_design_completed
from src.pipeline.science_run import (
    atomic_write_json,
    file_sha256,
    load_science_run,
    science_run_paths,
    utc_now,
)


QUANTITATIVE_FINALIZATION_SCHEMA_VERSION = "quantitative_finalization_v1"


class QuantitativeAuthorHandoffError(RuntimeError):
    """Raised when a final Q result cannot enter Author as controlled evidence."""


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _text(value: object) -> str:
    return str(value or "").strip()


def _read_json(path: Path, *, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise QuantitativeAuthorHandoffError(f"Cannot read {label}: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise QuantitativeAuthorHandoffError(f"{label} must be a JSON object")
    return dict(payload)


def _record(path: Path) -> dict[str, str]:
    if not path.is_file():
        raise QuantitativeAuthorHandoffError(f"Required quantitative artifact is missing: {path}")
    return {"path": str(path.resolve()), "sha256": file_sha256(path)}


def _verify_record(path: Path, record: object, *, label: str) -> None:
    """Ensure a finalization still references the exact immutable artifact."""

    expected = _mapping(record)
    recorded_path = Path(_text(expected.get("path"))).expanduser().resolve()
    if recorded_path != path.resolve():
        raise QuantitativeAuthorHandoffError(f"finalization {label} path no longer matches")
    if not path.is_file():
        raise QuantitativeAuthorHandoffError(f"finalization {label} is missing")
    if file_sha256(path) != _text(expected.get("sha256")):
        raise QuantitativeAuthorHandoffError(f"finalization {label} hash no longer matches")


def _version_directory(run_dir: Path, quantitative_idea_id: str, version: int) -> Path:
    if quantitative_idea_id not in {"Q1", "Q2"} or version not in {0, 1, 2}:
        raise QuantitativeAuthorHandoffError("quantitative finalization must identify Q1/Q2 at v0, v1, or v2")
    return run_dir / "quantitative" / quantitative_idea_id / f"v{version}"


def expected_quantitative_idea_ids(*, root: Path) -> tuple[str, ...]:
    """Return every Q in the verified sidecar bound to this quantitative run."""

    workflow_manifest_path = root / "quantitative" / "quantitative_workflow_manifest.json"
    workflow_manifest = _read_json(workflow_manifest_path, label="quantitative workflow manifest")
    if workflow_manifest.get("schema_version") != "quantitative_workflow_manifest_v1":
        raise QuantitativeAuthorHandoffError("unsupported quantitative workflow manifest schema")
    try:
        metadata, _state = load_science_run(science_run_paths(root))
    except Exception as exc:
        raise QuantitativeAuthorHandoffError(f"science run is invalid: {exc}") from exc
    if _text(workflow_manifest.get("science_run_id")) != _text(metadata.get("science_run_id")):
        raise QuantitativeAuthorHandoffError(
            "quantitative workflow manifest science_run_id differs from the current science run"
        )
    sidecar_record = _mapping(workflow_manifest.get("quantitative_ideas_manifest"))
    sidecar_path = Path(_text(sidecar_record.get("path"))).expanduser().resolve()
    try:
        sidecar_path.relative_to((root / "idea").resolve())
    except ValueError as exc:
        raise QuantitativeAuthorHandoffError(
            "quantitative workflow sidecar must remain under the science run Idea directory"
        ) from exc
    _verify_record(sidecar_path, sidecar_record, label="quantitative ideas manifest")
    try:
        verified = verify_quantitative_ideas_manifest(sidecar_path)
    except QuantitativeManifestError as exc:
        raise QuantitativeAuthorHandoffError(f"quantitative ideas sidecar is invalid: {exc}") from exc
    if verified.payload.get("generation_status") != "READY":
        return ()
    identifiers = {
        _text(_mapping(idea).get("quantitative_idea_id"))
        for idea in verified.payload.get("ideas") or []
    }
    if not identifiers or not identifiers.issubset({"Q1", "Q2"}):
        raise QuantitativeAuthorHandoffError("quantitative ideas sidecar has invalid Q identifiers")
    return tuple(sorted(identifiers))


def finalize_quantitative_idea(
    *, run_dir: str | Path, quantitative_idea_id: str, version: int
) -> Path:
    """Freeze a version only when it has qualified numerical evidence."""

    root = Path(run_dir).expanduser().resolve()
    try:
        require_experiment_design_completed(root)
    except QuantitativeWorkflowError as exc:
        raise QuantitativeAuthorHandoffError(str(exc)) from exc
    version_dir = _version_directory(root, quantitative_idea_id, version)
    spec_path = version_dir / "quantitative_model_spec.json"
    markdown_path = version_dir / "mathematical_model.md"
    ledger_path = version_dir / "result_ledger.json"
    specification = normalize_quantitative_model_spec(_read_json(spec_path, label="model specification"))
    try:
        markdown = markdown_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise QuantitativeAuthorHandoffError(f"Cannot read mathematical model Markdown: {exc}") from exc
    validate_json_markdown_consistency(specification, markdown)
    ledger = validate_result_ledger(_read_json(ledger_path, label="result ledger"))
    qualified = qualified_ledger_entries(ledger)
    if not qualified:
        raise QuantitativeAuthorHandoffError("a final Q version needs at least one QUALIFIED simulation result")
    if specification["lineage"]["quantitative_idea_id"] != quantitative_idea_id or specification["lineage"]["version"] != version:
        raise QuantitativeAuthorHandoffError("model specification identity differs from the requested final Q version")
    parameter_artifacts: dict[str, dict[str, str]] = {}
    parameter_provenance = _mapping(specification.get("parameter_provenance"))
    if parameter_provenance.get("mode") == "APPROVED_PARAMETER_SET":
        evidence_dir = root / "quantitative" / quantitative_idea_id / "parameter_evidence" / f"v{version}"
        parameter_set_path = evidence_dir / "approved_parameter_set.json"
        parameter_manifest_path = evidence_dir / "approved_parameter_set_manifest.json"
        try:
            parameter_set = normalize_approved_parameter_set(
                _read_json(parameter_set_path, label="approved parameter set")
            )
        except ParameterContractError as exc:
            raise QuantitativeAuthorHandoffError(f"approved parameter set is invalid: {exc}") from exc
        if parameter_set["parameter_set_identity"] != _text(parameter_provenance.get("parameter_set_identity")):
            raise QuantitativeAuthorHandoffError("model parameter provenance identity no longer matches approved set")
        parameter_artifacts = {
            "approved_parameter_set": _record(parameter_set_path),
            "approved_parameter_set_manifest": _record(parameter_manifest_path),
        }
    finalization_path = root / "quantitative" / quantitative_idea_id / "finalization.json"
    if finalization_path.exists():
        raise QuantitativeAuthorHandoffError("quantitative idea already has a finalization record")
    lineage_ledgers: dict[str, dict[str, str]] = {}
    for historical_version in range(version + 1):
        historical_path = _version_directory(root, quantitative_idea_id, historical_version) / "result_ledger.json"
        validate_result_ledger(_read_json(historical_path, label="historical result ledger"))
        lineage_ledgers[f"v{historical_version}"] = _record(historical_path)
    payload = {
        "schema_version": QUANTITATIVE_FINALIZATION_SCHEMA_VERSION,
        "finalized_at": utc_now(),
        "quantitative_idea_id": quantitative_idea_id,
        "final_version": version,
        "model_identity": specification["lineage"],
        "model_spec_identity": model_spec_identity(specification),
        "qualified_execution_ids": [entry["execution_id"] for entry in qualified],
        "artifacts": {
            "model_spec": _record(spec_path),
            "mathematical_model_markdown": _record(markdown_path),
            "result_ledger": _record(ledger_path),
            **parameter_artifacts,
        },
        "lineage_ledgers": lineage_ledgers,
    }
    atomic_write_json(finalization_path, payload)
    return finalization_path


def _validated_lineage_summary(
    root: Path,
    quantitative_idea_id: str,
    final_version: int,
    lineage_records: object,
) -> list[dict[str, Any]]:
    records = _mapping(lineage_records)
    expected_keys = {f"v{version}" for version in range(final_version + 1)}
    if set(records) != expected_keys:
        raise QuantitativeAuthorHandoffError("finalization lineage ledger records are incomplete")
    summary: list[dict[str, Any]] = []
    for version in range(final_version + 1):
        ledger_path = _version_directory(root, quantitative_idea_id, version) / "result_ledger.json"
        _verify_record(ledger_path, records[f"v{version}"], label=f"lineage ledger v{version}")
        ledger = validate_result_ledger(_read_json(ledger_path, label=f"lineage ledger v{version}"))
        for entry in ledger["entries"]:
            summary.append(
                {
                    "version": version,
                    "relation": entry["hypothesis_relation"],
                    "reason": entry["reason"] or entry["result_summary"],
                }
            )
    return summary


def _qualification_numerical_quality(entry: Mapping[str, object]) -> dict[str, Any]:
    qualification_path = Path(_text(entry.get("qualification_path"))).expanduser().resolve()
    if not qualification_path.is_file():
        raise QuantitativeAuthorHandoffError("qualified result is missing its qualification artifact")
    qualification = _read_json(qualification_path, label="result qualification")
    quality = _mapping(qualification.get("numerical_quality"))
    status = _text(quality.get("status")) or "NOT_REPORTED"
    if status not in {"NUMERICALLY_VERIFIED", "NUMERICALLY_UNVERIFIED", "NOT_REPORTED"}:
        raise QuantitativeAuthorHandoffError("qualified result has an unsupported numerical quality status")
    scenario_statuses = quality.get("scenario_statuses") or []
    if not isinstance(scenario_statuses, list):
        raise QuantitativeAuthorHandoffError("qualified result numerical quality scenario statuses are invalid")
    return {
        "status": status,
        "scenario_statuses": [_text(item) for item in scenario_statuses],
    }


def load_finalized_quantitative_record(
    *, root: Path, finalization_path: Path
) -> dict[str, Any]:
    """Load a final Q version only if its frozen artifacts remain exact."""

    finalization = _read_json(finalization_path, label="quantitative finalization")
    if finalization.get("schema_version") != QUANTITATIVE_FINALIZATION_SCHEMA_VERSION:
        raise QuantitativeAuthorHandoffError("unsupported quantitative finalization schema")
    quantitative_idea_id = _text(finalization.get("quantitative_idea_id"))
    final_version = finalization.get("final_version")
    if quantitative_idea_id not in {"Q1", "Q2"} or not isinstance(final_version, int):
        raise QuantitativeAuthorHandoffError("quantitative finalization identity is invalid")
    expected_finalization_path = root / "quantitative" / quantitative_idea_id / "finalization.json"
    if finalization_path.resolve() != expected_finalization_path.resolve():
        raise QuantitativeAuthorHandoffError("quantitative finalization path differs from its Q identity")
    version_dir = _version_directory(root, quantitative_idea_id, final_version)
    spec_path = version_dir / "quantitative_model_spec.json"
    markdown_path = version_dir / "mathematical_model.md"
    ledger_path = version_dir / "result_ledger.json"
    artifacts = _mapping(finalization.get("artifacts"))
    _verify_record(spec_path, artifacts.get("model_spec"), label="model specification")
    _verify_record(markdown_path, artifacts.get("mathematical_model_markdown"), label="mathematical model Markdown")
    _verify_record(ledger_path, artifacts.get("result_ledger"), label="result ledger")
    spec = normalize_quantitative_model_spec(_read_json(spec_path, label="final model specification"))
    try:
        markdown = markdown_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise QuantitativeAuthorHandoffError(f"Cannot read final mathematical model Markdown: {exc}") from exc
    validate_json_markdown_consistency(spec, markdown)
    ledger = validate_result_ledger(_read_json(ledger_path, label="final result ledger"))
    if _mapping(finalization.get("model_identity")) != spec["lineage"]:
        raise QuantitativeAuthorHandoffError("finalization model lineage no longer matches")
    if model_spec_identity(spec) != _text(finalization.get("model_spec_identity")):
        raise QuantitativeAuthorHandoffError("finalization model specification identity no longer matches")
    parameter_provenance = _mapping(spec.get("parameter_provenance"))
    if parameter_provenance.get("mode") == "APPROVED_PARAMETER_SET":
        evidence_dir = root / "quantitative" / quantitative_idea_id / "parameter_evidence" / f"v{final_version}"
        parameter_set_path = evidence_dir / "approved_parameter_set.json"
        parameter_manifest_path = evidence_dir / "approved_parameter_set_manifest.json"
        _verify_record(parameter_set_path, artifacts.get("approved_parameter_set"), label="approved parameter set")
        _verify_record(
            parameter_manifest_path,
            artifacts.get("approved_parameter_set_manifest"),
            label="approved parameter set manifest",
        )
        try:
            parameter_set = normalize_approved_parameter_set(
                _read_json(parameter_set_path, label="approved parameter set")
            )
        except ParameterContractError as exc:
            raise QuantitativeAuthorHandoffError(f"approved parameter set is invalid: {exc}") from exc
        if parameter_set["parameter_set_identity"] != _text(parameter_provenance.get("parameter_set_identity")):
            raise QuantitativeAuthorHandoffError("final model parameter provenance no longer matches approved set")
    qualified = qualified_ledger_entries(ledger)
    if not qualified:
        raise QuantitativeAuthorHandoffError("finalized Q has no qualified entries")
    qualified_execution_ids = [entry["execution_id"] for entry in qualified]
    if finalization.get("qualified_execution_ids") != qualified_execution_ids:
        raise QuantitativeAuthorHandoffError("finalization qualified execution list no longer matches")
    lineage = _validated_lineage_summary(
        root,
        quantitative_idea_id,
        final_version,
        finalization.get("lineage_ledgers"),
    )
    return {
        "finalization": finalization,
        "model_spec": spec,
        "qualified_entries": qualified,
        "lineage_summary": lineage,
    }


def _finalized_evidence(root: Path, finalization_path: Path) -> tuple[dict[str, str], list[dict[str, Any]], dict[str, Any]]:
    record = load_finalized_quantitative_record(root=root, finalization_path=finalization_path)
    finalization = record["finalization"]
    spec = record["model_spec"]
    qualified = record["qualified_entries"]
    lineage = record["lineage_summary"]
    quantitative_idea_id = _text(finalization.get("quantitative_idea_id"))
    final_version = finalization["final_version"]
    source_identity = {
        field: _text(spec["lineage"].get(field))
        for field in (
            "science_run_id",
            "survey_run_id",
            "project_id",
            "project_context_fingerprint",
            "selected_direction_id",
        )
    }
    evidence = [
        {
            "quantitative_idea_id": quantitative_idea_id,
            "final_version": final_version,
            "question": spec["scientific_question"],
            "model_family": spec["numerical_plan"]["solver_family"],
            "execution_mode": "NUMERICAL_SIMULATION",
            "result_kind": "SIMULATED",
            "empirical_claim_status": "NOT_EMPIRICAL",
            "result_quality": "QUALIFIED",
            "hypothesis_relation": entry["hypothesis_relation"],
            "result_summary": entry["result_summary"],
            "applicability_conditions": spec["assumptions"] and [
                assumption["statement"] for assumption in spec["assumptions"]
            ],
            "limitations": spec["limitations"],
            "lineage_summary": lineage,
            "numerical_quality": _qualification_numerical_quality(entry),
            "supplement_pdf_reference": f"quantitative_mathematical_models.pdf#{quantitative_idea_id}",
            "parameter_provenance": spec["parameter_provenance"],
        }
        for entry in qualified
    ]
    return source_identity, evidence, finalization


def build_quantitative_author_handoff(
    *, run_dir: str | Path, quantitative_models_pdf_path: str | Path
) -> tuple[Path, Path]:
    """Create a small, verified capsule only after the supplementary PDF exists."""

    root = Path(run_dir).expanduser().resolve()
    try:
        require_experiment_design_completed(root)
    except QuantitativeWorkflowError as exc:
        raise QuantitativeAuthorHandoffError(str(exc)) from exc
    pdf_path = Path(quantitative_models_pdf_path).expanduser().resolve()
    expected_pdf_path = root / "quantitative" / "publication" / "quantitative_mathematical_models.pdf"
    if pdf_path != expected_pdf_path:
        raise QuantitativeAuthorHandoffError("Author must use this run's formal quantitative supplementary PDF")
    if not pdf_path.is_file():
        raise QuantitativeAuthorHandoffError("quantitative supplementary PDF does not exist")
    identities: list[dict[str, str]] = []
    evidence: list[dict[str, Any]] = []
    finalization_records: dict[str, dict[str, str]] = {}
    expected_ids = expected_quantitative_idea_ids(root=root)
    missing_finalizations = [
        quantitative_idea_id
        for quantitative_idea_id in expected_ids
        if not (root / "quantitative" / quantitative_idea_id / "finalization.json").is_file()
    ]
    if missing_finalizations:
        raise QuantitativeAuthorHandoffError(
            "all quantitative ideas must be finalized before Author handoff; missing: "
            + ", ".join(missing_finalizations)
        )
    for quantitative_idea_id in expected_ids:
        finalization_path = root / "quantitative" / quantitative_idea_id / "finalization.json"
        if not finalization_path.is_file():
            continue
        identity, records, _finalization = _finalized_evidence(root, finalization_path)
        identities.append(identity)
        evidence.extend(records)
        finalization_records[quantitative_idea_id] = _record(finalization_path)
    if not evidence:
        raise QuantitativeAuthorHandoffError("no finalized qualified Q evidence is available for Author")
    source_identity = identities[0]
    if any(identity != source_identity for identity in identities[1:]):
        raise QuantitativeAuthorHandoffError("finalized quantitative ideas have incompatible source identities")
    handoff = validate_quantitative_author_handoff(
        {
            "schema_version": QUANTITATIVE_AUTHOR_HANDOFF_SCHEMA_VERSION,
            "source_identity": source_identity,
            "evidence": evidence,
        }
    )
    author_dir = root / "quantitative" / "author"
    handoff_path = author_dir / "quantitative_author_handoff.json"
    manifest_path = author_dir / "quantitative_author_handoff_manifest.json"
    if handoff_path.exists() or manifest_path.exists():
        raise QuantitativeAuthorHandoffError("quantitative Author handoff already exists")
    author_dir.mkdir(parents=True, exist_ok=False)
    atomic_write_json(handoff_path, handoff)
    manifest = {
        "schema_version": QUANTITATIVE_AUTHOR_HANDOFF_MANIFEST_SCHEMA_VERSION,
        "status": "COMPLETED",
        "source_identity": source_identity,
        "inputs": {"finalizations": finalization_records},
        "artifacts": {"handoff": _record(handoff_path), "quantitative_models_pdf": _record(pdf_path)},
    }
    atomic_write_json(manifest_path, manifest)
    return handoff_path, manifest_path


__all__ = [
    "QUANTITATIVE_FINALIZATION_SCHEMA_VERSION",
    "QuantitativeAuthorHandoffError",
    "build_quantitative_author_handoff",
    "expected_quantitative_idea_ids",
    "finalize_quantitative_idea",
    "load_finalized_quantitative_record",
]
