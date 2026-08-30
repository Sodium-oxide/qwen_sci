"""Stage manifests and verified handoffs for the design-only science workflow."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.pipeline.science_run import atomic_write_json, file_sha256
from src.pipeline.survey_idea_loader import SurveyIdeaLoadError, load_survey_idea_context


IDEA_MANIFEST_SCHEMA_VERSION = "science_idea_manifest_v1"
EXPERIMENT_DESIGN_MANIFEST_SCHEMA_VERSION = "science_experiment_design_manifest_v1"
AUTHOR_MANIFEST_SCHEMA_VERSION = "science_author_manifest_v1"
_IDENTITY_FIELDS = (
    "survey_run_id",
    "project_id",
    "project_context_fingerprint",
)
_STAGE_SCHEMAS = {
    "idea": IDEA_MANIFEST_SCHEMA_VERSION,
    "exp_design": EXPERIMENT_DESIGN_MANIFEST_SCHEMA_VERSION,
    "author": AUTHOR_MANIFEST_SCHEMA_VERSION,
}


class ScienceManifestError(ValueError):
    """Raised when a stage manifest or its declared artifact is untrusted."""


@dataclass(frozen=True)
class VerifiedStageManifest:
    """A verified stage manifest and its only permitted downstream artifact."""

    stage: str
    manifest_path: Path
    canonical_path: Path
    identity: Mapping[str, str]
    metadata: Mapping[str, Any]
    artifacts: Mapping[str, Path]


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _text(value: object) -> str:
    return str(value or "").strip()


def _read_json(path: Path, *, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ScienceManifestError(f"Cannot read {label}: {path}: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise ScienceManifestError(f"{label} must contain a JSON object: {path}")
    return dict(payload)


def _record(path: str | Path) -> dict[str, str]:
    resolved = Path(path).expanduser().resolve()
    if not resolved.is_file():
        raise ScienceManifestError(f"Manifest artifact does not exist: {resolved}")
    return {"path": str(resolved), "sha256": file_sha256(resolved)}


def _records(paths: Mapping[str, str | Path]) -> dict[str, dict[str, str]]:
    return {str(name): _record(path) for name, path in paths.items()}


def _identity(value: Mapping[str, object]) -> dict[str, str]:
    return {str(key): _text(item) for key, item in value.items() if _text(item)}


def _identity_error(actual: Mapping[str, object], expected: Mapping[str, object], *, label: str) -> None:
    for field in _IDENTITY_FIELDS:
        expected_value = _text(expected.get(field))
        actual_value = _text(actual.get(field))
        if not actual_value:
            raise ScienceManifestError(f"{label} is missing {field}")
        if expected_value and actual_value != expected_value:
            raise ScienceManifestError(f"{label} differs for {field}")
    expected_manifest = _text(expected.get("survey_manifest_path"))
    actual_manifest = _text(actual.get("survey_manifest_path") or actual.get("manifest_path"))
    if not actual_manifest:
        raise ScienceManifestError(f"{label} is missing survey_manifest_path")
    if expected_manifest:
        if Path(actual_manifest).expanduser().resolve() != Path(expected_manifest).expanduser().resolve():
            raise ScienceManifestError(f"{label} differs for survey_manifest_path")
    expected_handoff = _text(expected.get("handoff_fingerprint"))
    actual_handoff = _text(actual.get("handoff_fingerprint"))
    if not actual_handoff:
        raise ScienceManifestError(f"{label} is missing handoff_fingerprint")
    if expected_handoff and actual_handoff != expected_handoff:
        raise ScienceManifestError(f"{label} differs for handoff_fingerprint")


def _verify_record(
    record: object,
    *,
    manifest_path: Path,
    label: str,
    require_local: bool,
) -> Path:
    payload = _mapping(record)
    raw_path = _text(payload.get("path"))
    expected_hash = _text(payload.get("sha256"))
    if not raw_path or not expected_hash:
        raise ScienceManifestError(f"{label} has no path or SHA-256")
    path = Path(raw_path).expanduser()
    if not path.is_absolute():
        raise ScienceManifestError(f"{label} path is not absolute: {raw_path}")
    path = path.resolve()
    if require_local:
        try:
            path.relative_to(manifest_path.parent)
        except ValueError as exc:
            raise ScienceManifestError(f"{label} escapes its stage attempt directory") from exc
    if not path.is_file():
        raise ScienceManifestError(f"{label} is missing: {path}")
    if file_sha256(path) != expected_hash:
        raise ScienceManifestError(f"{label} SHA-256 does not match its manifest")
    return path


def _build_manifest(
    *,
    stage: str,
    topic: str,
    identity: Mapping[str, object],
    inputs: Mapping[str, str | Path],
    artifacts: Mapping[str, str | Path],
    canonical_artifact: str,
    metadata: Mapping[str, Any],
) -> dict[str, Any]:
    if stage not in _STAGE_SCHEMAS:
        raise ScienceManifestError(f"Unsupported science manifest stage: {stage}")
    if canonical_artifact not in artifacts:
        raise ScienceManifestError(f"{stage} canonical artifact is not declared")
    if not _text(topic):
        raise ScienceManifestError(f"{stage} manifest topic is required")
    normalized_identity = _identity(identity)
    _identity_error(
        normalized_identity,
        normalized_identity,
        label=f"{stage} manifest identity",
    )
    return {
        "schema_version": _STAGE_SCHEMAS[stage],
        "stage": stage,
        "status": "COMPLETED",
        "topic": _text(topic),
        "identity": normalized_identity,
        "inputs": _records(inputs),
        "artifacts": _records(artifacts),
        "canonical_artifact": canonical_artifact,
        "metadata": dict(metadata),
    }


def _write_manifest(path: str | Path, payload: Mapping[str, Any]) -> Path:
    manifest_path = Path(path).expanduser().resolve()
    atomic_write_json(manifest_path, dict(payload))
    return manifest_path


def write_idea_manifest(
    *,
    attempt_dir: str | Path,
    topic: str,
    idea_result_path: str | Path,
    survey_manifest_path: str | Path,
    identity: Mapping[str, object],
    selected_direction_id: str,
) -> Path:
    attempt = Path(attempt_dir).expanduser().resolve()
    return _write_manifest(
        attempt / "idea_manifest.json",
        _build_manifest(
            stage="idea",
            topic=topic,
            identity=identity,
            inputs={"survey_manifest": survey_manifest_path},
            artifacts={"idea_result": idea_result_path},
            canonical_artifact="idea_result",
            metadata={
                "idea_result_schema_version": "idea_result_v5",
                "selected_direction_id": _text(selected_direction_id),
            },
        ),
    )


def write_experiment_design_manifest(
    *,
    attempt_dir: str | Path,
    topic: str,
    idea_manifest_path: str | Path,
    idea_result_path: str | Path,
    artifact_paths: Mapping[str, str | Path],
    identity: Mapping[str, object],
    design_id: str,
    selected_direction_id: str,
    discipline_ids: list[str],
    log_path: str | Path | None = None,
) -> Path:
    artifacts = {
        "experiment_design_json": artifact_paths["experiment_design_json"],
        "experiment_design_markdown": artifact_paths["experiment_design_markdown"],
        "author_json": artifact_paths["author_json"],
    }
    if log_path is not None and Path(log_path).is_file():
        artifacts["log"] = log_path
    attempt = Path(attempt_dir).expanduser().resolve()
    return _write_manifest(
        attempt / "experiment_design_manifest.json",
        _build_manifest(
            stage="exp_design",
            topic=topic,
            identity=identity,
            inputs={
                "idea_manifest": idea_manifest_path,
                "idea_result": idea_result_path,
            },
            artifacts=artifacts,
            canonical_artifact="author_json",
            metadata={
                "design_id": _text(design_id),
                "selected_direction_id": _text(selected_direction_id),
                "discipline_ids": [str(value).strip() for value in discipline_ids if str(value).strip()],
                "execution_mode": "DESIGN_ONLY",
            },
        ),
    )


def write_author_manifest(
    *,
    attempt_dir: str | Path,
    topic: str,
    survey_manifest_path: str | Path,
    idea_manifest_path: str | Path,
    experiment_design_manifest_path: str | Path,
    author_input_path: str | Path,
    artifact_paths: Mapping[str, str | Path],
    identity: Mapping[str, object],
    source_design_id: str,
    selected_direction_id: str,
    rendering: Mapping[str, Any],
) -> Path:
    required = ("preparation_json", "author_context_json", "document_json", "idea_evolution_json")
    artifacts = {name: artifact_paths[name] for name in required}
    for name in ("survey_source_binding", "survey_full_text_appendix", "render_status"):
        if name in artifact_paths:
            artifacts[name] = artifact_paths[name]
    artifacts.update(
        {
            name: path
            for name, path in artifact_paths.items()
            if name.startswith("render_") and name != "render_status"
        }
    )
    attempt = Path(attempt_dir).expanduser().resolve()
    rendering_payload = dict(rendering)
    rendering_status = _text(rendering_payload.get("status"))
    rendering_required = rendering_payload.get("required")
    if rendering_status not in {"COMPLETED", "SKIPPED", "FAILED_OPTIONAL"} or not isinstance(
        rendering_required, bool
    ):
        raise ScienceManifestError("Author manifest has an invalid rendering status")
    if "render_status" not in artifacts:
        raise ScienceManifestError("Author manifest rendering status has no artifact")
    if rendering_status == "COMPLETED" and "render_pdf" not in artifacts:
        raise ScienceManifestError("Completed Author rendering has no render_pdf artifact")
    return _write_manifest(
        attempt / "author_manifest.json",
        _build_manifest(
            stage="author",
            topic=topic,
            identity=identity,
            inputs={
                "survey_manifest": survey_manifest_path,
                "idea_manifest": idea_manifest_path,
                "experiment_design_manifest": experiment_design_manifest_path,
                "author_input": author_input_path,
            },
            artifacts=artifacts,
            canonical_artifact="document_json",
            metadata={
                "source_design_id": _text(source_design_id),
                "selected_direction_id": _text(selected_direction_id),
                "rendering": rendering_payload,
            },
        ),
    )


def verify_survey_manifest(
    manifest_path: str | Path,
    *,
    expected_identity: Mapping[str, object] | None = None,
    expected_topic: str | None = None,
) -> VerifiedStageManifest:
    try:
        context = load_survey_idea_context(manifest_path)
    except SurveyIdeaLoadError as exc:
        raise ScienceManifestError(f"Survey manifest is invalid: {exc}") from exc
    identity = {
        "survey_run_id": _text(context.survey_run_id),
        "project_id": _text(context.project_id),
        "project_context_fingerprint": _text(context.project_context_fingerprint),
        "survey_manifest_path": str(context.manifest_path),
        "manifest_fingerprint": file_sha256(context.manifest_path),
        "handoff_fingerprint": _text(context.handoff.get("handoff_fingerprint")),
    }
    _identity_error(identity, expected_identity or identity, label="Survey manifest identity")
    if expected_topic and context.topic.casefold() != _text(expected_topic).casefold():
        raise ScienceManifestError("Survey manifest topic differs from the science run topic")
    return VerifiedStageManifest(
        stage="survey",
        manifest_path=context.manifest_path,
        canonical_path=context.manifest_path,
        identity=identity,
        metadata={"topic": context.topic},
        artifacts={"survey_manifest": context.manifest_path},
    )


def _verify_common_manifest(stage: str, manifest_path: str | Path) -> tuple[Path, dict[str, Any], dict[str, Path]]:
    path = Path(manifest_path).expanduser().resolve()
    payload = _read_json(path, label=f"{stage} manifest")
    if payload.get("schema_version") != _STAGE_SCHEMAS[stage]:
        raise ScienceManifestError(f"Unsupported {stage} manifest schema")
    if payload.get("stage") != stage or payload.get("status") != "COMPLETED":
        raise ScienceManifestError(f"{stage} manifest is not a completed {stage} result")
    identity = _identity(_mapping(payload.get("identity")))
    _identity_error(identity, identity, label=f"{stage} manifest identity")
    artifacts_payload = _mapping(payload.get("artifacts"))
    artifacts = {
        name: _verify_record(record, manifest_path=path, label=f"{stage} artifact {name}", require_local=True)
        for name, record in artifacts_payload.items()
    }
    canonical_name = _text(payload.get("canonical_artifact"))
    if canonical_name not in artifacts:
        raise ScienceManifestError(f"{stage} manifest canonical artifact is missing")
    return path, payload, artifacts


def _verify_input(payload: Mapping[str, Any], name: str, *, manifest_path: Path) -> Path:
    inputs = _mapping(payload.get("inputs"))
    if name not in inputs:
        raise ScienceManifestError(f"Manifest input is missing: {name}")
    return _verify_record(
        inputs[name],
        manifest_path=manifest_path,
        label=f"Manifest input {name}",
        require_local=False,
    )


def verify_idea_manifest(
    manifest_path: str | Path,
    *,
    expected_survey_identity: Mapping[str, object] | None = None,
    expected_topic: str | None = None,
) -> VerifiedStageManifest:
    path, payload, artifacts = _verify_common_manifest("idea", manifest_path)
    identity = _identity(_mapping(payload.get("identity")))
    _identity_error(identity, expected_survey_identity or identity, label="Idea manifest identity")
    topic = _text(payload.get("topic"))
    if expected_topic and topic.casefold() != _text(expected_topic).casefold():
        raise ScienceManifestError("Idea manifest topic differs from the science run topic")
    survey_manifest = _verify_input(payload, "survey_manifest", manifest_path=path)
    survey = verify_survey_manifest(
        survey_manifest,
        expected_identity=identity,
        expected_topic=topic,
    )
    idea_result = artifacts.get("idea_result")
    if idea_result is None:
        raise ScienceManifestError("Idea manifest has no idea_result artifact")
    result_payload = _read_json(idea_result, label="Idea result")
    if _text(result_payload.get("schema_version")) != "idea_result_v5":
        raise ScienceManifestError("Idea result schema is not idea_result_v5")
    if _text(result_payload.get("topic")).casefold() != topic.casefold():
        raise ScienceManifestError("Idea result topic differs from its manifest")
    _identity_error(
        _mapping(result_payload.get("survey_binding")),
        survey.identity,
        label="Idea result Survey binding",
    )
    selected_direction = _text(_mapping(payload.get("metadata")).get("selected_direction_id"))
    if not selected_direction or selected_direction != _text(result_payload.get("primary_direction")):
        raise ScienceManifestError("Idea manifest selected direction differs from idea_result.json")
    verified_identity = {**identity, "selected_direction_id": selected_direction}
    return VerifiedStageManifest(
        stage="idea",
        manifest_path=path,
        canonical_path=idea_result,
        identity=verified_identity,
        metadata={**_mapping(payload.get("metadata")), "topic": topic},
        artifacts=artifacts,
    )


def verify_experiment_design_manifest(
    manifest_path: str | Path,
    *,
    expected_survey_identity: Mapping[str, object] | None = None,
    expected_topic: str | None = None,
) -> VerifiedStageManifest:
    path, payload, artifacts = _verify_common_manifest("exp_design", manifest_path)
    identity = _identity(_mapping(payload.get("identity")))
    _identity_error(identity, expected_survey_identity or identity, label="ExperimentDesign manifest identity")
    topic = _text(payload.get("topic"))
    if expected_topic and topic.casefold() != _text(expected_topic).casefold():
        raise ScienceManifestError("ExperimentDesign manifest topic differs from the science run topic")
    idea_manifest = _verify_input(payload, "idea_manifest", manifest_path=path)
    idea = verify_idea_manifest(
        idea_manifest,
        expected_survey_identity=identity,
        expected_topic=topic,
    )
    idea_result = _verify_input(payload, "idea_result", manifest_path=path)
    if idea_result != idea.canonical_path:
        raise ScienceManifestError("ExperimentDesign manifest idea_result is not the Idea manifest canonical artifact")
    metadata = _mapping(payload.get("metadata"))
    disciplines = metadata.get("discipline_ids")
    if not isinstance(disciplines, list) or not [_text(value) for value in disciplines if _text(value)]:
        raise ScienceManifestError("ExperimentDesign manifest has no verified discipline_ids")
    selected_direction = _text(metadata.get("selected_direction_id"))
    if not selected_direction or selected_direction != _text(idea.identity.get("selected_direction_id")):
        raise ScienceManifestError("ExperimentDesign manifest selected direction differs from Idea manifest")
    if _text(metadata.get("execution_mode")) != "DESIGN_ONLY":
        raise ScienceManifestError("ExperimentDesign manifest is not DESIGN_ONLY")
    design_json = artifacts.get("experiment_design_json")
    author_json = artifacts.get("author_json")
    if design_json is None or author_json is None:
        raise ScienceManifestError("ExperimentDesign manifest is missing design or Author handoff artifact")
    design = _read_json(design_json, label="ExperimentDesign JSON")
    if _text(_mapping(design.get("execution_policy")).get("mode")) != "DESIGN_ONLY":
        raise ScienceManifestError("ExperimentDesign JSON is not DESIGN_ONLY")
    design_disciplines = _mapping(design.get("research_brief")).get("discipline_ids")
    if not isinstance(design_disciplines, list) or not design_disciplines:
        raise ScienceManifestError("ExperimentDesign JSON has no discipline_ids")
    normalized_manifest_disciplines = [_text(value) for value in disciplines if _text(value)]
    normalized_design_disciplines = [_text(value) for value in design_disciplines if _text(value)]
    if normalized_design_disciplines != normalized_manifest_disciplines:
        raise ScienceManifestError("ExperimentDesign JSON discipline_ids differ from its manifest")
    handoff = _read_json(author_json, label="ExperimentDesign Author handoff")
    if _text(handoff.get("schema_version")) != "research_plan_author_input_v3":
        raise ScienceManifestError("ExperimentDesign Author handoff has an unsupported schema")
    provenance = _mapping(handoff.get("provenance"))
    _identity_error(
        _mapping(provenance.get("survey_binding")),
        idea.identity,
        label="ExperimentDesign Author handoff Survey binding",
    )
    if _text(provenance.get("selected_direction_id")) != selected_direction:
        raise ScienceManifestError("ExperimentDesign Author handoff selected direction differs from manifest")
    if Path(_text(provenance.get("idea_result_path"))).expanduser().resolve() != idea.canonical_path:
        raise ScienceManifestError("ExperimentDesign Author handoff does not reference the canonical Idea result")
    return VerifiedStageManifest(
        stage="exp_design",
        manifest_path=path,
        canonical_path=author_json,
        identity={**identity, "selected_direction_id": selected_direction},
        metadata={**metadata, "topic": topic},
        artifacts=artifacts,
    )


def verify_author_manifest(
    manifest_path: str | Path,
    *,
    expected_survey_identity: Mapping[str, object] | None = None,
    expected_topic: str | None = None,
    expected_render_required: bool | None = None,
) -> VerifiedStageManifest:
    path, payload, artifacts = _verify_common_manifest("author", manifest_path)
    identity = _identity(_mapping(payload.get("identity")))
    _identity_error(identity, expected_survey_identity or identity, label="Author manifest identity")
    topic = _text(payload.get("topic"))
    if expected_topic and topic.casefold() != _text(expected_topic).casefold():
        raise ScienceManifestError("Author manifest topic differs from the science run topic")
    survey_manifest = _verify_input(payload, "survey_manifest", manifest_path=path)
    verify_survey_manifest(survey_manifest, expected_identity=identity, expected_topic=topic)
    idea_manifest = _verify_input(payload, "idea_manifest", manifest_path=path)
    idea = verify_idea_manifest(idea_manifest, expected_survey_identity=identity, expected_topic=topic)
    design_manifest = _verify_input(payload, "experiment_design_manifest", manifest_path=path)
    design = verify_experiment_design_manifest(
        design_manifest,
        expected_survey_identity=idea.identity,
        expected_topic=topic,
    )
    author_input = _verify_input(payload, "author_input", manifest_path=path)
    if author_input != design.canonical_path:
        raise ScienceManifestError("Author manifest input is not the ExperimentDesign manifest canonical handoff")
    document = artifacts.get("document_json")
    if document is None:
        raise ScienceManifestError("Author manifest has no document_json artifact")
    document_payload = _read_json(document, label="Author document")
    source_manifest = _mapping(document_payload.get("source_manifest"))
    _identity_error(
        _mapping(source_manifest.get("survey_binding")),
        design.identity,
        label="Author document Survey binding",
    )
    metadata = _mapping(payload.get("metadata"))
    if _text(metadata.get("source_design_id")) != _text(design.metadata.get("design_id")):
        raise ScienceManifestError("Author manifest source_design_id differs from ExperimentDesign manifest")
    if _text(document_payload.get("source_design_id")) != _text(design.metadata.get("design_id")):
        raise ScienceManifestError("Author document source_design_id differs from ExperimentDesign manifest")
    selected_direction = _text(metadata.get("selected_direction_id"))
    if selected_direction != _text(design.identity.get("selected_direction_id")):
        raise ScienceManifestError("Author manifest selected direction differs from ExperimentDesign manifest")
    if _text(source_manifest.get("selected_direction_id")) != selected_direction:
        raise ScienceManifestError("Author document selected direction differs from Author manifest")
    if not isinstance(metadata.get("rendering"), Mapping):
        raise ScienceManifestError("Author manifest has no rendering status")
    rendering = _mapping(metadata.get("rendering"))
    status = _text(rendering.get("status"))
    required = rendering.get("required")
    if status not in {"COMPLETED", "SKIPPED", "FAILED_OPTIONAL"} or not isinstance(required, bool):
        raise ScienceManifestError("Author manifest has an invalid rendering status")
    status_path = artifacts.get("render_status")
    if status_path is None:
        raise ScienceManifestError("Author manifest rendering status has no artifact")
    status_payload = _read_json(status_path, label="Author rendering status")
    if _text(status_payload.get("status")) != status or status_payload.get("required") is not required:
        raise ScienceManifestError("Author rendering status artifact differs from its manifest")
    if required and status != "COMPLETED":
        raise ScienceManifestError("Required Author rendering was not completed")
    if status == "COMPLETED" and "render_pdf" not in artifacts:
        raise ScienceManifestError("Completed Author rendering has no render_pdf artifact")
    if expected_render_required is not None and required != expected_render_required:
        raise ScienceManifestError("Author manifest rendering requirement differs from the science run")
    return VerifiedStageManifest(
        stage="author",
        manifest_path=path,
        canonical_path=document,
        identity={**identity, "selected_direction_id": selected_direction},
        metadata={**metadata, "topic": topic},
        artifacts=artifacts,
    )


def verify_stage_manifest(
    stage: str,
    manifest_path: str | Path,
    *,
    expected_survey_identity: Mapping[str, object] | None = None,
    expected_topic: str | None = None,
    expected_render_required: bool | None = None,
) -> VerifiedStageManifest:
    if stage == "survey":
        return verify_survey_manifest(
            manifest_path,
            expected_identity=expected_survey_identity,
            expected_topic=expected_topic,
        )
    if stage == "idea":
        return verify_idea_manifest(
            manifest_path,
            expected_survey_identity=expected_survey_identity,
            expected_topic=expected_topic,
        )
    if stage == "exp_design":
        return verify_experiment_design_manifest(
            manifest_path,
            expected_survey_identity=expected_survey_identity,
            expected_topic=expected_topic,
        )
    if stage == "author":
        return verify_author_manifest(
            manifest_path,
            expected_survey_identity=expected_survey_identity,
            expected_topic=expected_topic,
            expected_render_required=expected_render_required,
        )
    raise ScienceManifestError(f"Unknown science manifest stage: {stage}")


__all__ = [
    "AUTHOR_MANIFEST_SCHEMA_VERSION",
    "EXPERIMENT_DESIGN_MANIFEST_SCHEMA_VERSION",
    "IDEA_MANIFEST_SCHEMA_VERSION",
    "ScienceManifestError",
    "VerifiedStageManifest",
    "verify_author_manifest",
    "verify_experiment_design_manifest",
    "verify_idea_manifest",
    "verify_stage_manifest",
    "verify_survey_manifest",
    "write_author_manifest",
    "write_experiment_design_manifest",
    "write_idea_manifest",
]
