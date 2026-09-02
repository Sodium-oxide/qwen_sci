"""State-driven orchestration for the independent quantitative branch."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from src.agents.quantitative_modeling.author_handoff import build_quantitative_author_handoff
from src.agents.quantitative_modeling.publisher.run import publish_quantitative_models_pdf
from src.agents.quantitative_modeling.result_ledger import qualified_ledger_entries
from src.pipeline.quantitative_manifests import (
    QuantitativeManifestError,
    verify_quantitative_ideas_manifest,
)
from src.pipeline.quantitative_state import (
    new_quantitative_state,
    save_quantitative_state,
)
from src.pipeline.quantitative_workflow import (
    QuantitativeWorkflowError,
    materialize_quantitative_model_version,
    prepare_quantitative_model_blueprint,
    require_experiment_design_completed,
)
from src.pipeline.science_manifests import (
    ScienceManifestError,
    verify_idea_manifest,
    verify_survey_manifest,
    write_idea_manifest,
)
from src.pipeline.science_run import (
    append_science_event,
    atomic_write_json,
    file_sha256,
    load_science_run,
    locked_science_run,
    recover_stage_completed,
    save_science_state,
    science_run_paths,
)


class QuantitativeOrchestratorError(RuntimeError):
    """Raised when the quantitative branch cannot determine a safe next step."""


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _text(value: object) -> str:
    return str(value or "").strip()


def _read_json(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise QuantitativeOrchestratorError(f"cannot read {label}: {exc}") from exc
    if not isinstance(value, Mapping):
        raise QuantitativeOrchestratorError(f"{label} must be a JSON object")
    return dict(value)


def _record(path: Path) -> dict[str, str]:
    return {"path": str(path.resolve()), "sha256": file_sha256(path)}


def _raw_science_context(run_dir: str | Path) -> tuple[Path, dict[str, Any], dict[str, Any]]:
    paths = science_run_paths(run_dir)
    try:
        metadata, state = load_science_run(paths)
    except Exception as exc:
        raise QuantitativeOrchestratorError(f"cannot load science run: {exc}") from exc
    return paths.run_dir, metadata, state


def _idea_context(
    root: Path, metadata: Mapping[str, object], state: Mapping[str, object]
) -> tuple[Path | None, dict[str, Any] | None]:
    idea_manifest_path, idea_manifest = _verified_idea_manifest(root, metadata, state)
    if idea_manifest_path is None or idea_manifest is None:
        return None, None
    stages = _mapping(state.get("stages"))
    idea_stage = _mapping(stages.get("idea"))
    topic = _text(_mapping(metadata.get("immutable_inputs")).get("topic"))
    candidates: list[Path] = []
    output_path = _mapping(idea_stage.get("outputs")).get("quantitative_ideas_manifest")
    if _text(output_path):
        candidates.append(Path(_text(output_path)).expanduser().resolve())
    candidates.extend(sorted(idea_manifest_path.parent.glob("quantitative_ideas_manifest.json")))
    seen: set[Path] = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        try:
            candidate.relative_to(idea_manifest_path.parent.resolve())
        except ValueError as exc:
            raise QuantitativeOrchestratorError(
                "quantitative Idea manifest must remain beside the current Idea manifest"
            ) from exc
        try:
            verified = verify_quantitative_ideas_manifest(
                candidate,
                expected_identity=idea_manifest.identity,
                expected_topic=topic,
            )
        except QuantitativeManifestError as exc:
            raise QuantitativeOrchestratorError(f"Quantitative Idea manifest validation failed: {exc}") from exc
        return verified.manifest_path, dict(verified.payload)
    return None, None


def _verified_idea_manifest(
    root: Path, metadata: Mapping[str, object], state: Mapping[str, object]
) -> tuple[Path | None, Any | None]:
    """Load the immutable Idea manifest without requiring a Q sidecar."""

    stages = _mapping(state.get("stages"))
    idea_stage = _mapping(stages.get("idea"))
    if idea_stage.get("status") != "COMPLETED":
        return None, None
    raw_idea_manifest_path = _text(idea_stage.get("result_manifest_path"))
    if not raw_idea_manifest_path:
        raise QuantitativeOrchestratorError("completed Idea has no result manifest path")
    idea_manifest_path = Path(raw_idea_manifest_path).expanduser()
    if not idea_manifest_path.is_absolute():
        raise QuantitativeOrchestratorError("completed Idea result manifest path must be absolute")
    idea_manifest_path = idea_manifest_path.resolve()
    try:
        idea_manifest_path.relative_to((root / "idea").resolve())
    except ValueError as exc:
        raise QuantitativeOrchestratorError(
            "completed Idea manifest escapes the science run Idea directory"
        ) from exc
    if not idea_manifest_path.is_file():
        raise QuantitativeOrchestratorError(
            f"completed Idea result manifest is missing: {idea_manifest_path}"
        )
    expected_idea_sha256 = _text(_mapping(idea_stage.get("result_identity")).get("result_sha256"))
    if not expected_idea_sha256 or file_sha256(idea_manifest_path) != expected_idea_sha256:
        raise QuantitativeOrchestratorError(
            "completed Idea manifest fingerprint no longer matches its persisted state"
        )
    survey_stage = _mapping(stages.get("survey"))
    if survey_stage.get("status") != "COMPLETED":
        raise QuantitativeOrchestratorError(
            "completed Idea requires a completed Survey stage before quantitative modeling"
        )
    raw_survey_manifest_path = _text(survey_stage.get("result_manifest_path"))
    if not raw_survey_manifest_path:
        raise QuantitativeOrchestratorError("completed Survey has no result manifest path")
    survey_manifest_path = Path(raw_survey_manifest_path).expanduser()
    if not survey_manifest_path.is_absolute():
        raise QuantitativeOrchestratorError("completed Survey result manifest path must be absolute")
    survey_manifest_path = survey_manifest_path.resolve()
    try:
        survey_manifest_path.relative_to((root / "survey").resolve())
    except ValueError as exc:
        raise QuantitativeOrchestratorError(
            "completed Survey manifest escapes the science run Survey directory"
        ) from exc
    if not survey_manifest_path.is_file():
        raise QuantitativeOrchestratorError(
            f"completed Survey result manifest is missing: {survey_manifest_path}"
        )
    expected_survey_sha256 = _text(_mapping(survey_stage.get("result_identity")).get("result_sha256"))
    if not expected_survey_sha256 or file_sha256(survey_manifest_path) != expected_survey_sha256:
        raise QuantitativeOrchestratorError(
            "completed Survey manifest fingerprint no longer matches its persisted state"
        )
    topic = _text(_mapping(metadata.get("immutable_inputs")).get("topic"))
    try:
        survey_manifest = verify_survey_manifest(survey_manifest_path, expected_topic=topic)
        idea_manifest = verify_idea_manifest(
            idea_manifest_path,
            expected_survey_identity=survey_manifest.identity,
            expected_topic=topic,
        )
    except ScienceManifestError as exc:
        raise QuantitativeOrchestratorError(
            f"Survey/Idea manifest validation failed: {exc}"
        ) from exc
    return idea_manifest.manifest_path, idea_manifest


def _recover_failed_idea_artifact(
    root: Path,
    metadata: Mapping[str, object],
    state: Mapping[str, object],
) -> None:
    """Recover a verified Idea artifact already written before stage publication failed."""

    stages = _mapping(state.get("stages"))
    idea_stage = _mapping(stages.get("idea"))
    if idea_stage.get("status") != "FAILED":
        return
    attempt = idea_stage.get("attempt")
    if not isinstance(attempt, int) or attempt < 1:
        raise QuantitativeOrchestratorError("failed Idea has no valid allocated attempt")
    attempt_dir = (root / "idea" / f"attempt-{attempt:03d}").resolve()
    result_path = attempt_dir / "idea_result.json"
    manifest_path = attempt_dir / "idea_manifest.json"
    topic = _text(_mapping(metadata.get("immutable_inputs")).get("topic"))
    survey_stage = _mapping(stages.get("survey"))
    if survey_stage.get("status") != "COMPLETED":
        raise QuantitativeOrchestratorError("failed Idea recovery requires a completed Survey stage")
    survey_manifest_raw = _text(survey_stage.get("result_manifest_path"))
    if not survey_manifest_raw:
        raise QuantitativeOrchestratorError("completed Survey has no result manifest path")
    survey_manifest_path = Path(survey_manifest_raw).expanduser().resolve()
    if not survey_manifest_path.is_file():
        raise QuantitativeOrchestratorError(
            f"completed Survey manifest is missing during Idea recovery: {survey_manifest_path}"
        )
    expected_survey_sha256 = _text(_mapping(survey_stage.get("result_identity")).get("result_sha256"))
    if not expected_survey_sha256 or file_sha256(survey_manifest_path) != expected_survey_sha256:
        raise QuantitativeOrchestratorError("Survey manifest fingerprint no longer matches persisted state")
    try:
        survey = verify_survey_manifest(survey_manifest_path, expected_topic=topic)
    except ScienceManifestError as exc:
        raise QuantitativeOrchestratorError(f"Survey manifest validation failed during Idea recovery: {exc}") from exc

    if manifest_path.is_file():
        try:
            verified = verify_idea_manifest(
                manifest_path,
                expected_survey_identity=survey.identity,
                expected_topic=topic,
            )
        except ScienceManifestError as exc:
            raise QuantitativeOrchestratorError(f"existing Idea manifest cannot be recovered: {exc}") from exc
    else:
        if not result_path.is_file():
            return
        idea_payload = _read_json(result_path, label="failed Idea result")
        if _text(idea_payload.get("schema_version")) != "idea_result_v5":
            raise QuantitativeOrchestratorError("failed Idea result schema is not idea_result_v5")
        if _text(idea_payload.get("topic")).casefold() != topic.casefold():
            raise QuantitativeOrchestratorError("failed Idea result topic differs from the science run topic")
        if not _text(idea_payload.get("primary_direction")):
            raise QuantitativeOrchestratorError("failed Idea result has no primary_direction")
        from src.agents.idea_agent.utils.workflow.idea_contract import normalize_idea_contract

        legacy_entry = idea_payload.get("legacy_best_entry")
        contract_candidate = legacy_entry if isinstance(legacy_entry, Mapping) else idea_payload
        try:
            normalize_idea_contract(contract_candidate, allow_legacy=False, keep_extra=True)
        except (TypeError, ValueError) as exc:
            raise QuantitativeOrchestratorError(
                f"failed Idea result does not contain a valid canonical Idea contract: {exc}"
            ) from exc
        identity = {
            **dict(survey.identity),
            "selected_direction_id": _text(idea_payload.get("primary_direction")),
        }
        try:
            write_idea_manifest(
                attempt_dir=attempt_dir,
                topic=topic,
                idea_result_path=result_path,
                survey_manifest_path=survey_manifest_path,
                identity=identity,
                selected_direction_id=_text(idea_payload.get("primary_direction")),
            )
            verified = verify_idea_manifest(
                manifest_path,
                expected_survey_identity=survey.identity,
                expected_topic=topic,
            )
        except ScienceManifestError as exc:
            raise QuantitativeOrchestratorError(f"recovered Idea manifest validation failed: {exc}") from exc

    outputs = {
        "idea_manifest": str(verified.manifest_path),
        "idea_result": str(verified.canonical_path),
        "idea_run_dir": str(attempt_dir),
    }
    if "quantitative_ideas" in verified.artifacts:
        outputs["quantitative_ideas"] = str(verified.artifacts["quantitative_ideas"])
    paths = science_run_paths(root)
    with locked_science_run(paths):
        persisted_metadata, persisted_state = load_science_run(paths)
        persisted_stages = _mapping(persisted_state.get("stages"))
        persisted_idea = _mapping(persisted_stages.get("idea"))
        if (
            _text(persisted_metadata.get("science_run_id")) != _text(metadata.get("science_run_id"))
            or persisted_idea.get("status") != "FAILED"
            or persisted_idea.get("attempt") != attempt
        ):
            return
        result_identity = {
            **dict(verified.identity),
            "result_sha256": file_sha256(verified.manifest_path),
        }
        recover_stage_completed(
            persisted_state,
            "idea",
            attempt=attempt,
            result_manifest_path=str(verified.manifest_path),
            outputs=outputs,
            result_identity=result_identity,
        )
        save_science_state(paths, persisted_state)
        append_science_event(
            paths,
            event_type="IDEA_ARTIFACT_RECOVERED",
            attempt=attempt,
            result_path=str(verified.manifest_path),
            result_identity=result_identity,
        )


def _design_record(root: Path, metadata: Mapping[str, object], state: Mapping[str, object]) -> dict[str, Any]:
    stage = _mapping(_mapping(state.get("stages")).get("exp_design"))
    if stage.get("status") != "COMPLETED":
        return {"status": "WAITING_FOR_EXPERIMENT_DESIGN"}
    try:
        path = require_experiment_design_completed(root)
    except QuantitativeWorkflowError as exc:
        raise QuantitativeOrchestratorError(str(exc)) from exc
    design_payload = _read_json(path, label="ExperimentDesign manifest")
    design_metadata = _mapping(design_payload.get("metadata"))
    return {
        "status": "COMPLETED",
        "manifest": _record(path),
        "design_id": _text(design_metadata.get("design_id")),
    }


def _version_status(root: Path, idea_id: str, version: int) -> dict[str, Any]:
    version_dir = root / "quantitative" / idea_id / f"v{version}"
    evidence_dir = root / "quantitative" / idea_id / "parameter_evidence" / f"v{version}"
    state: dict[str, Any] = {
        "version": version,
        "parent_version": None if version == 0 else version - 1,
        "status": "WAITING_FOR_BLUEPRINT",
        "artifacts": {},
        "execution_ids": [],
        "qualification_status": "PENDING",
    }
    if not version_dir.is_dir():
        return state
    tracked_files = {
        "revision_acceptance": version_dir / "revision_acceptance.json",
        "model_spec": version_dir / "quantitative_model_spec.json",
        "model": version_dir / "mathematical_model.md",
        "plan": version_dir / "simulation_run_plan.json",
        "ledger": version_dir / "result_ledger.json",
    }
    tracked_files.update(
        {
            "blueprint": evidence_dir / "model_blueprint.json",
            "query_plan": evidence_dir / "parameter_query_plan.json",
            "approved_parameters": evidence_dir / "approved_parameter_set.json",
            "parameter_proposal": evidence_dir / "parameter_resolution_proposal.json",
        }
    )
    blueprint_path = evidence_dir / "model_blueprint.json"
    model_spec = version_dir / "quantitative_model_spec.json"
    plan = version_dir / "simulation_run_plan.json"
    state["artifacts"] = {
        name: _record(path)
        for name, path in tracked_files.items()
        if path.is_file()
    }
    if not blueprint_path.is_file():
        if not (model_spec.is_file() and plan.is_file()):
            return state
        state["parameterization_mode"] = "LEGACY_INLINE_ASSUMPTIONS"
    else:
        approved = evidence_dir / "approved_parameter_set.json"
        if not approved.is_file():
            if (evidence_dir / "parameter_resolution_proposal.json").is_file():
                state["status"] = "WAITING_FOR_PARAMETER_APPROVAL"
            elif list((evidence_dir / "extractions").glob("extract-*.json")) or (evidence_dir / "user_documents").is_dir():
                state["status"] = "WAITING_FOR_PARAMETER_REVIEW"
            else:
                state["status"] = "WAITING_FOR_PARAMETER_EVIDENCE"
            return state
        approved_payload = _read_json(approved, label="approved parameter set")
        state["parameter_set_identity"] = _text(approved_payload.get("parameter_set_identity"))
    if not model_spec.is_file() or not plan.is_file():
        state["status"] = "PARAMETERS_APPROVED"
        return state
    model_payload = _read_json(model_spec, label="quantitative model specification")
    plan_payload = _read_json(plan, label="simulation run plan")
    state["model_spec_identity"] = _text(
        _mapping(model_payload.get("lineage")).get("model_spec_identity")
    )
    state["plan_identity"] = _text(plan_payload.get("plan_identity"))
    state["status"] = "MODEL_MATERIALIZED"
    execution_root = version_dir / "executions"
    executions = sorted(
        path for path in execution_root.iterdir() if path.is_dir()
    ) if execution_root.is_dir() else []
    execution_ids: list[str] = []
    unqualified: list[str] = []
    for execution_dir in executions:
        record_path = execution_dir / "execution_record.json"
        if not record_path.is_file():
            continue
        execution_id = _text(_read_json(record_path, label="execution record").get("execution_id")) or execution_dir.name
        execution_ids.append(execution_id)
        if not (execution_dir / "result_qualification.json").is_file():
            unqualified.append(execution_id)
    state["execution_ids"] = execution_ids
    if not execution_ids:
        state["status"] = "WAITING_FOR_EXECUTION_AUTHORIZATION"
        return state
    if unqualified:
        state["status"] = "WAITING_FOR_QUALIFICATION"
        state["unqualified_execution_ids"] = unqualified
        return state
    ledger_path = version_dir / "result_ledger.json"
    if ledger_path.is_file():
        ledger = _read_json(ledger_path, label="result ledger")
        try:
            qualified = qualified_ledger_entries(ledger)
        except Exception as exc:
            raise QuantitativeOrchestratorError(f"result ledger validation failed: {exc}") from exc
        if qualified:
            state["qualification_status"] = "QUALIFIED"
            state["status"] = "QUALIFIED_WAITING_FOR_REVISION_DECISION"
    return state


def _next_actions(state: Mapping[str, Any], *, manifest_path: Path | None) -> list[dict[str, Any]]:
    status = _text(state.get("status"))
    idea_id = _text(state.get("quantitative_idea_id"))
    version = state.get("current_version")
    prefix = f"--run-dir <RUN> --idea-id {idea_id} --version {version}"
    manifest = str(manifest_path) if manifest_path else "<QUANTITATIVE_IDEAS_MANIFEST>"
    if status == "WAITING_FOR_BLUEPRINT":
        return [{"action": "blueprint", "command": f"quantitative blueprint --run-dir <RUN> --quantitative-ideas-manifest {manifest} --idea-id {idea_id} --version {version}"}]
    if status == "WAITING_FOR_PARAMETER_EVIDENCE":
        return [{"action": "discover", "command": f"quantitative parameters discover {prefix} --fetch"}]
    if status == "WAITING_FOR_PARAMETER_REVIEW":
        return [{"action": "propose", "command": f"quantitative parameters propose {prefix} --selections-json '<SELECTIONS_JSON>'"}]
    if status == "WAITING_FOR_PARAMETER_APPROVAL":
        return [{"action": "approve", "command": f"quantitative parameters approve {prefix} --approve"}]
    if status == "PARAMETERS_APPROVED":
        return [{"action": "materialize", "command": f"quantitative materialize --run-dir <RUN> --quantitative-ideas-manifest {manifest} --idea-id {idea_id} --version {version}"}]
    if status == "WAITING_FOR_EXECUTION_AUTHORIZATION":
        return [{"action": "simulate", "command": f"quantitative simulate {prefix} --execute --plan-identity {state.get('plan_identity', '')}"}]
    if status == "WAITING_FOR_QUALIFICATION":
        return [{"action": "qualify", "command": f"quantitative qualify {prefix} --execution-id <EXECUTION_ID> --hypothesis-relation <RELATION> --result-summary '<SUMMARY>'"}]
    if status == "QUALIFIED_WAITING_FOR_REVISION_DECISION":
        actions = [{"action": "finalize", "command": f"quantitative finalize {prefix}"}]
        if isinstance(version, int) and version < 2:
            actions.append({"action": "propose-refinement", "command": f"quantitative propose-refinement {prefix} --revision-reason '<REASON>' ..."})
        return actions
    if status == "WAITING_FOR_REVISION_APPROVAL":
        return [
            {
                "action": "finalize-current-version",
                "command": f"quantitative finalize --run-dir <RUN> --idea-id {idea_id} --version {version}",
            },
            {
                "action": "accept-revision",
                "command": f"quantitative accept-revision --run-dir <RUN> --idea-id {idea_id} --parent-version {version} --accept",
            },
        ]
    if status == "READY_TO_PUBLISH":
        return [{"action": "publish", "command": "quantitative publish --run-dir <RUN>"}]
    if status == "PUBLISHED":
        return [{"action": "author-handoff", "command": "quantitative author-handoff --run-dir <RUN>"}]
    if status == "HANDED_OFF":
        return [{"action": "resume-author", "command": "science --resume <RUN> --until author"}]
    if status == "WAITING_FOR_EXPERIMENT_DESIGN":
        return [{"action": "science", "command": "science --resume <RUN> --until exp_design"}]
    if status == "NO_QUANTITATIVE_IDEAS":
        if manifest_path is None:
            return [
                {
                    "action": "resume-from-idea",
                    "command": "quantitative resume-from-idea --run-dir <RUN> --config <CONFIG>",
                }
            ]
        return [{"action": "resume-author", "command": "science --resume <RUN> --until author"}]
    return []


def ensure_quantitative_ideas_from_existing_idea(
    *,
    run_dir: str | Path,
    llm_call: Callable[..., object],
) -> dict[str, str]:
    """Generate the independent Q sidecar for a completed legacy Idea run.

    The canonical ``idea_result_v5`` and its Idea manifest are read-only.  This
    helper publishes only the two quantitative sidecar artifacts in the same
    Idea attempt, then records their paths in the mutable science state.
    """

    root, metadata, science_state = _raw_science_context(run_dir)
    design = _design_record(root, metadata, science_state)
    if design.get("status") != "COMPLETED":
        raise QuantitativeOrchestratorError(
            "ExperimentDesign must be completed before generating the quantitative Idea sidecar"
        )
    idea_manifest_path, idea_manifest = _verified_idea_manifest(root, metadata, science_state)
    if idea_manifest_path is None or idea_manifest is None:
        raise QuantitativeOrchestratorError(
            "an existing completed Idea manifest is required to start quantitative modeling"
        )

    existing_manifest, existing_payload = _idea_context(root, metadata, science_state)
    if existing_manifest is not None and existing_payload is not None:
        ideas_path = _mapping(
            _read_json(existing_manifest, label="quantitative ideas manifest").get("artifacts")
        ).get("quantitative_ideas")
        return {
            "quantitative_ideas": str(Path(_text(ideas_path)).expanduser().resolve()),
            "quantitative_ideas_manifest": str(existing_manifest),
            "created": "false",
        }

    from src.agents.quantitative_modeling.idea_generation import generate_quantitative_idea_set
    from src.pipeline.quantitative_manifests import write_quantitative_ideas_manifest

    topic = _text(_mapping(metadata.get("immutable_inputs")).get("topic"))
    idea_result_path = idea_manifest.canonical_path
    sidecar_path = idea_manifest_path.parent / "quantitative_ideas.json"
    sidecar_manifest_path = idea_manifest_path.parent / "quantitative_ideas_manifest.json"
    if sidecar_path.exists() or sidecar_manifest_path.exists():
        raise QuantitativeOrchestratorError(
            "an unverified quantitative sidecar already exists; inspect it instead of overwriting immutable artifacts"
        )
    source_identity = {
        **dict(idea_manifest.identity),
        "science_run_id": _text(metadata.get("science_run_id")),
        "idea_result_path": str(idea_result_path),
    }
    idea_payload = _read_json(idea_result_path, label="canonical Idea result")
    quantitative_payload = generate_quantitative_idea_set(
        topic=topic,
        idea_result=idea_payload,
        source_identity=source_identity,
        llm_call=llm_call,
    )

    paths = science_run_paths(root)
    with locked_science_run(paths):
        persisted_metadata, persisted_state = load_science_run(paths)
        if _text(persisted_metadata.get("science_run_id")) != _text(metadata.get("science_run_id")):
            raise QuantitativeOrchestratorError("science run metadata changed while publishing the quantitative sidecar")
        current_idea_path, current_idea = _verified_idea_manifest(root, persisted_metadata, persisted_state)
        if current_idea_path != idea_manifest_path or current_idea is None:
            raise QuantitativeOrchestratorError("the completed Idea changed while publishing the quantitative sidecar")
        if sidecar_path.exists() or sidecar_manifest_path.exists():
            raise QuantitativeOrchestratorError(
                "a quantitative sidecar appeared while it was being generated; no artifact was overwritten"
            )
        atomic_write_json(sidecar_path, quantitative_payload)
        published_manifest = write_quantitative_ideas_manifest(
            attempt_dir=idea_manifest_path.parent,
            topic=topic,
            idea_manifest_path=idea_manifest_path,
            ideas_path=sidecar_path,
            identity=current_idea.identity,
        )
        stages = persisted_state.get("stages")
        if not isinstance(stages, dict) or not isinstance(stages.get("idea"), dict):
            raise QuantitativeOrchestratorError("science state has no mutable Idea stage record")
        stage = stages["idea"]
        outputs = _mapping(stage.get("outputs"))
        outputs.update(
            {
                "quantitative_ideas": str(sidecar_path),
                "quantitative_ideas_manifest": str(published_manifest),
            }
        )
        stage["outputs"] = outputs
        save_science_state(paths, persisted_state)
        append_science_event(
            paths,
            event_type="QUANTITATIVE_IDEA_SIDECAR_PUBLISHED",
            idea_manifest_path=str(idea_manifest_path),
            quantitative_ideas_path=str(sidecar_path),
            quantitative_ideas_manifest_path=str(published_manifest),
        )
    return {
        "quantitative_ideas": str(sidecar_path),
        "quantitative_ideas_manifest": str(published_manifest),
        "created": "true",
    }


def resume_quantitative_from_existing_idea(
    *,
    run_dir: str | Path,
    llm_call: Callable[..., object],
) -> dict[str, Any]:
    """Resume the quantitative branch from an already completed Idea stage.

    A pending or failed ExperimentDesign is resumed through its existing
    science workflow.  Completed Survey and Idea stages are never rerun.  The
    function stops at the normal quantitative state machine boundary; it never
    authorizes or executes a numerical simulation.
    """

    root, metadata, science_state = _raw_science_context(run_dir)
    _recover_failed_idea_artifact(root, metadata, science_state)
    root, metadata, science_state = _raw_science_context(root)
    _verified_idea_manifest(root, metadata, science_state)
    design = _design_record(root, metadata, science_state)
    if design.get("status") != "COMPLETED":
        from src.pipeline.science_workflow import run_science_workflow

        run_science_workflow(
            paths=science_run_paths(root),
            metadata=metadata,
            until="exp_design",
            quiet=True,
        )
    ensure_quantitative_ideas_from_existing_idea(run_dir=root, llm_call=llm_call)
    return refresh_quantitative_state(root)


def refresh_quantitative_state(run_dir: str | Path) -> dict[str, Any]:
    """Reconcile persisted quantitative state with immutable branch artifacts."""

    root, metadata, science_state = _raw_science_context(run_dir)
    state = new_quantitative_state(science_run_id=_text(metadata.get("science_run_id")))
    design = _design_record(root, metadata, science_state)
    state["experiment_design"] = design
    if design.get("status") != "COMPLETED":
        state["status"] = "WAITING_FOR_EXPERIMENT_DESIGN"
        state["next_actions"] = [{"action": "science", "command": "science --resume <RUN> --until exp_design"}]
        save_quantitative_state(root, state)
        return state
    manifest_path, payload = _idea_context(root, metadata, science_state)
    if manifest_path is not None:
        state["quantitative_ideas_manifest"] = _record(manifest_path)
    if payload is None or _text(payload.get("generation_status")) != "READY":
        state["status"] = "NO_QUANTITATIVE_IDEAS"
        state["next_actions"] = _next_actions(state, manifest_path=manifest_path)
        save_quantitative_state(root, state)
        return state
    for raw_idea in payload.get("ideas") or []:
        idea = _mapping(raw_idea)
        idea_id = _text(idea.get("quantitative_idea_id"))
        if idea_id not in {"Q1", "Q2"}:
            continue
        versions: dict[str, Any] = {}
        finalization = root / "quantitative" / idea_id / "finalization.json"
        highest_existing = -1
        for version in range(3):
            if (root / "quantitative" / idea_id / f"v{version}").is_dir():
                highest_existing = version
            version_state = _version_status(root, idea_id, version)
            if version_state["status"] == "WAITING_FOR_BLUEPRINT" and version > 0:
                acceptance = root / "quantitative" / idea_id / f"v{version}" / "revision_acceptance.json"
                if acceptance.is_file() and not (root / "quantitative" / idea_id / f"v{version - 1}" / "hypothesis_refinement_proposal.json").is_file():
                    version_state["status"] = "WAITING_FOR_REVISION_APPROVAL"
            versions[f"v{version}"] = version_state
        current_version = max(0, highest_existing)
        if finalization.is_file():
            final_payload = _read_json(finalization, label="quantitative finalization")
            current_version = int(final_payload.get("final_version", current_version))
            current_status = "FINALIZED"
        else:
            current_status = versions[f"v{current_version}"]["status"]
            proposal = root / "quantitative" / idea_id / f"v{current_version}" / "hypothesis_refinement_proposal.json"
            if proposal.is_file() and current_version < 2 and not (root / "quantitative" / idea_id / f"v{current_version + 1}").is_dir():
                current_status = "WAITING_FOR_REVISION_APPROVAL"
        idea_state = {
            "quantitative_idea_id": idea_id,
            "title": _text(idea.get("title")),
            "status": current_status,
            "current_version": current_version,
            "versions": versions,
        }
        state["ideas"][idea_id] = idea_state
    if not state["ideas"]:
        state["status"] = "NO_QUANTITATIVE_IDEAS"
    elif all(_text(idea.get("status")) == "FINALIZED" for idea in state["ideas"].values()):
        pdf_path = root / "quantitative" / "publication" / "quantitative_mathematical_models.pdf"
        handoff = root / "quantitative" / "author" / "quantitative_author_handoff_manifest.json"
        state["status"] = "HANDED_OFF" if handoff.is_file() else "PUBLISHED" if pdf_path.is_file() else "READY_TO_PUBLISH"
    else:
        unresolved = next(
            idea
            for idea in state["ideas"].values()
            if _text(idea.get("status")) != "FINALIZED"
        )
        state["status"] = _text(unresolved.get("status"))
    state["next_actions"] = _next_actions(
        next((idea for idea in state["ideas"].values() if _text(idea.get("status")) != "FINALIZED"), state),
        manifest_path=manifest_path,
    )
    save_quantitative_state(root, state)
    return state


def continue_quantitative_workflow(
    *,
    run_dir: str | Path,
    llm_call: Callable[[str], object] | None = None,
    latex_engine: str | Path | None = None,
    pdf_renderer: str | Path | None = None,
    timeout_seconds: int = 180,
) -> dict[str, Any]:
    """Perform one non-destructive-or-authorized transition and return state.

    This command never executes a solver.  It may create a blueprint or model
    after a human parameter approval, but simulation always stops at the exact
    plan identity and requires a separate ``simulate --execute`` invocation.
    """

    state = refresh_quantitative_state(run_dir)
    root = Path(run_dir).expanduser().resolve()
    if _text(state.get("status")) in {"WAITING_FOR_EXPERIMENT_DESIGN", "NO_QUANTITATIVE_IDEAS", "WAITING_FOR_PARAMETER_EVIDENCE", "WAITING_FOR_PARAMETER_REVIEW", "WAITING_FOR_PARAMETER_APPROVAL", "WAITING_FOR_EXECUTION_AUTHORIZATION", "WAITING_FOR_QUALIFICATION", "QUALIFIED_WAITING_FOR_REVISION_DECISION", "WAITING_FOR_REVISION_APPROVAL"}:
        return state
    manifest_record = _mapping(state.get("quantitative_ideas_manifest"))
    manifest_path = Path(_text(manifest_record.get("path"))).expanduser().resolve()
    action_state = next(
        (
            idea
            for idea in state.get("ideas", {}).values()
            if _text(idea.get("status")) != "FINALIZED"
        ),
        None,
    )
    if action_state is not None:
        idea_id = _text(action_state.get("quantitative_idea_id"))
        version = int(action_state.get("current_version", 0))
        status = _text(action_state.get("status"))
        if status == "WAITING_FOR_BLUEPRINT":
            if llm_call is None:
                raise QuantitativeOrchestratorError("blueprint continuation requires an LLM callback")
            prepare_quantitative_model_blueprint(
                run_dir=root,
                quantitative_ideas_manifest_path=manifest_path,
                quantitative_idea_id=idea_id,
                version=version,
                llm_call=llm_call,
            )
        elif status == "PARAMETERS_APPROVED":
            if llm_call is None:
                raise QuantitativeOrchestratorError("model materialization continuation requires an LLM callback")
            materialize_quantitative_model_version(
                run_dir=root,
                quantitative_ideas_manifest_path=manifest_path,
                quantitative_idea_id=idea_id,
                version=version,
                llm_call=llm_call,
            )
        else:
            return state
        return refresh_quantitative_state(root)
    if _text(state.get("status")) == "READY_TO_PUBLISH":
        publish_quantitative_models_pdf(
            run_dir=root,
            latex_engine=latex_engine,
            pdf_renderer=pdf_renderer,
            timeout_seconds=timeout_seconds,
        )
        return refresh_quantitative_state(root)
    if _text(state.get("status")) == "PUBLISHED":
        build_quantitative_author_handoff(
            run_dir=root,
            quantitative_models_pdf_path=root / "quantitative" / "publication" / "quantitative_mathematical_models.pdf",
        )
        return refresh_quantitative_state(root)
    return state


def continue_quantitative_until_author_ready(
    *,
    run_dir: str | Path,
    idea_llm_call: Callable[..., object],
    model_llm_call: Callable[[str], object],
    latex_engine: str | Path | None = None,
    pdf_renderer: str | Path | None = None,
    timeout_seconds: int = 180,
    max_transitions: int = 64,
) -> dict[str, Any]:
    """Advance safe quantitative transitions until human input or Author handoff.

    This high-level continuation never executes a solver.  It may recover the
    sidecar, complete ExperimentDesign, generate blueprints, materialize an
    approved model, publish the separate PDF, and create the Author handoff.
    Parameter review, revision decisions, qualification, and every simulation
    remain explicit stopping points.
    """

    if max_transitions < 1:
        raise QuantitativeOrchestratorError("max_transitions must be positive")
    state = resume_quantitative_from_existing_idea(run_dir=run_dir, llm_call=idea_llm_call)
    safe_statuses = {
        "WAITING_FOR_BLUEPRINT",
        "PARAMETERS_APPROVED",
        "READY_TO_PUBLISH",
        "PUBLISHED",
    }
    for _ in range(max_transitions):
        status = _text(state.get("status"))
        if status in {"NO_QUANTITATIVE_IDEAS", "HANDED_OFF"}:
            return state
        if status not in safe_statuses:
            return state
        before = json.dumps(
            {
                "status": status,
                "ideas": state.get("ideas"),
                "experiment_design": state.get("experiment_design"),
            },
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        )
        state = continue_quantitative_workflow(
            run_dir=run_dir,
            llm_call=model_llm_call,
            latex_engine=latex_engine,
            pdf_renderer=pdf_renderer,
            timeout_seconds=timeout_seconds,
        )
        after = json.dumps(
            {
                "status": state.get("status"),
                "ideas": state.get("ideas"),
                "experiment_design": state.get("experiment_design"),
            },
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        )
        if before == after:
            raise QuantitativeOrchestratorError(
                f"quantitative continuation made no progress at status {status}"
            )
    raise QuantitativeOrchestratorError(
        f"quantitative continuation exceeded the transition limit ({max_transitions})"
    )


__all__ = [
    "QuantitativeOrchestratorError",
    "continue_quantitative_workflow",
    "continue_quantitative_until_author_ready",
    "ensure_quantitative_ideas_from_existing_idea",
    "refresh_quantitative_state",
    "resume_quantitative_from_existing_idea",
]
