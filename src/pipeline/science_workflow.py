"""Service orchestration for the resumable design-only science workflow."""

from __future__ import annotations

import copy
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.pipeline.science_run import (
    SCIENCE_STAGE_NAMES,
    ScienceRunPaths,
    ScienceRunStateError,
    append_science_event,
    file_sha256,
    is_stage_execution_active,
    load_science_run,
    locked_science_run,
    mark_stage_completed,
    mark_stage_failed,
    mark_stage_running,
    record_stage_service_process,
    save_science_state,
    utc_now,
)
from src.pipeline.science_manifests import (
    ScienceManifestError,
    VerifiedStageManifest,
    verify_stage_manifest,
)
from src.pipeline.science_stages import (
    AuthorStageRequest,
    ExperimentDesignStageRequest,
    IdeaStageRequest,
    ScienceStageError,
    ScienceStageResult,
    ScienceStageServices,
    SurveyStageRequest,
    default_science_stage_services,
)


_STAGE_DIRECTORIES = {
    "survey": "survey",
    "idea": "idea",
    "exp_design": "experiment_design",
    "author": "author",
}
_STAGE_EXIT_CODES = {
    "survey": 10,
    "idea": 20,
    "exp_design": 30,
    "author": 40,
}
_STAGE_MANIFEST_FILENAMES = {
    "survey": "survey_manifest.json",
    "idea": "idea_manifest.json",
    "exp_design": "experiment_design_manifest.json",
    "author": "author_manifest.json",
}
_IDENTITY_FIELDS = (
    "survey_run_id",
    "project_id",
    "project_context_fingerprint",
)


class ScienceWorkflowError(RuntimeError):
    """A stable workflow error associated with one science stage."""

    def __init__(
        self,
        stage: str,
        exit_code: int,
        message: str,
        *,
        observed_state: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.stage = stage
        self.exit_code = exit_code
        self.observed_state = (
            copy.deepcopy(dict(observed_state)) if isinstance(observed_state, Mapping) else None
        )
        self.observed_state_revision = (
            self.observed_state.get("revision", 0) if self.observed_state is not None else None
        )


@dataclass(frozen=True)
class ScienceWorkflowOutcome:
    """Final persisted metadata and state after one workflow invocation."""

    metadata: Mapping[str, Any]
    state: Mapping[str, Any]


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _text(value: object) -> str:
    return str(value or "").strip()


def _stage_attempt_dir(paths: ScienceRunPaths, stage_name: str, attempt: int) -> Path:
    if attempt < 1:
        raise ScienceRunStateError(f"Science stage {stage_name} has no allocated attempt")
    return (paths.run_dir / _STAGE_DIRECTORIES[stage_name] / f"attempt-{attempt:03d}").resolve()


def _metadata_inputs(metadata: Mapping[str, Any]) -> tuple[str, dict[str, Any], dict[str, Any]]:
    immutable_inputs = _mapping(metadata.get("immutable_inputs"))
    options = _mapping(immutable_inputs.get("options"))
    topic = _text(immutable_inputs.get("topic"))
    if not topic:
        raise ScienceRunStateError("science_run.json has no immutable topic")
    science_run_id = _text(metadata.get("science_run_id"))
    if not science_run_id:
        raise ScienceRunStateError("science_run.json has no science_run_id")
    return topic, options, immutable_inputs


def _expected_render_required(options: Mapping[str, Any]) -> bool:
    return bool(_mapping(options.get("author_rendering")).get("required", False))


def _completed_stage(
    paths: ScienceRunPaths,
    state: Mapping[str, Any],
    stage_name: str,
    *,
    consumer_stage: str,
    expected_topic: str | None = None,
    expected_render_required: bool | None = None,
) -> VerifiedStageManifest:
    stages = _mapping(state.get("stages"))
    stage = _mapping(stages.get(stage_name))
    if stage.get("status") != "COMPLETED":
        raise ScienceWorkflowError(
            consumer_stage,
            _STAGE_EXIT_CODES[consumer_stage],
            f"{consumer_stage} requires completed {stage_name}",
        )
    result_path = _text(stage.get("result_manifest_path"))
    if not result_path:
        raise ScienceWorkflowError(
            consumer_stage,
            _STAGE_EXIT_CODES[consumer_stage],
            f"Completed {stage_name} has no exact result path",
        )
    path = Path(result_path).expanduser()
    if not path.is_absolute():
        raise ScienceWorkflowError(
            consumer_stage,
            _STAGE_EXIT_CODES[consumer_stage],
            f"Completed {stage_name} result path is not absolute",
        )
    if not path.is_file():
        raise ScienceWorkflowError(
            consumer_stage,
            _STAGE_EXIT_CODES[consumer_stage],
            f"Completed {stage_name} result path no longer exists: {path}",
        )
    try:
        path.resolve().relative_to((paths.run_dir / _STAGE_DIRECTORIES[stage_name]).resolve())
    except ValueError as exc:
        raise ScienceWorkflowError(
            consumer_stage,
            _STAGE_EXIT_CODES[consumer_stage],
            f"Completed {stage_name} result path escapes its science run stage directory",
        ) from exc
    raw_identity = _mapping(stage.get("result_identity"))
    identity = {str(key): _text(value) for key, value in raw_identity.items() if _text(value)}
    if not identity:
        raise ScienceWorkflowError(
            consumer_stage,
            _STAGE_EXIT_CODES[consumer_stage],
            f"Completed {stage_name} has no persisted result identity",
        )
    expected_sha256 = _text(identity.get("result_sha256"))
    if not expected_sha256:
        raise ScienceWorkflowError(
            consumer_stage,
            _STAGE_EXIT_CODES[consumer_stage],
            f"Completed {stage_name} has no persisted result fingerprint",
        )
    actual_sha256 = file_sha256(path)
    if actual_sha256 != expected_sha256:
        raise ScienceWorkflowError(
            consumer_stage,
            _STAGE_EXIT_CODES[consumer_stage],
            f"Completed {stage_name} result fingerprint no longer matches its persisted state",
        )
    try:
        verified = verify_stage_manifest(
            stage_name,
            path,
            expected_topic=expected_topic,
            expected_render_required=expected_render_required,
        )
    except ScienceManifestError as exc:
        raise ScienceWorkflowError(
            consumer_stage,
            _STAGE_EXIT_CODES[consumer_stage],
            f"Completed {stage_name} manifest validation failed: {exc}",
        ) from exc
    for field in (*_IDENTITY_FIELDS, "selected_direction_id"):
        persisted_value = _text(identity.get(field))
        verified_value = _text(verified.identity.get(field))
        if persisted_value and persisted_value != verified_value:
            raise ScienceWorkflowError(
                consumer_stage,
                _STAGE_EXIT_CODES[consumer_stage],
                f"Completed {stage_name} manifest identity differs from its persisted state for {field}",
            )
    return verified


def _input_identity(
    paths: ScienceRunPaths,
    state: Mapping[str, Any],
    metadata: Mapping[str, Any],
    stage_name: str,
    quantitative_handoff_manifest_path: Path | None = None,
) -> dict[str, Any]:
    topic, _options, immutable_inputs = _metadata_inputs(metadata)
    science_run_id = _text(metadata.get("science_run_id"))
    if stage_name == "survey":
        return {
            "science_run_id": science_run_id,
            "topic_fingerprint": _text(immutable_inputs.get("topic_fingerprint")),
        }
    survey = _completed_stage(
        paths,
        state,
        "survey",
        consumer_stage=stage_name,
        expected_topic=topic,
    )
    if stage_name == "idea":
        return {
            "survey_manifest_path": str(survey.canonical_path),
            "survey_identity": dict(survey.identity),
            "topic": topic,
        }
    idea = _completed_stage(
        paths,
        state,
        "idea",
        consumer_stage=stage_name,
        expected_topic=topic,
    )
    if stage_name == "exp_design":
        return {
            "survey_manifest_path": str(survey.canonical_path),
            "survey_identity": dict(survey.identity),
            "idea_manifest_path": str(idea.manifest_path),
            "idea_result_path": str(idea.canonical_path),
            "idea_identity": dict(idea.identity),
        }
    design = _completed_stage(
        paths,
        state,
        "exp_design",
        consumer_stage=stage_name,
        expected_topic=topic,
    )
    identity = {
        "survey_manifest_path": str(survey.canonical_path),
        "survey_identity": dict(survey.identity),
        "idea_manifest_path": str(idea.manifest_path),
        "idea_result_path": str(idea.canonical_path),
        "idea_identity": dict(idea.identity),
        "experiment_design_manifest_path": str(design.manifest_path),
        "author_input_path": str(design.canonical_path),
        "design_identity": dict(design.identity),
    }
    if quantitative_handoff_manifest_path is not None:
        identity["quantitative_handoff_manifest_path"] = str(quantitative_handoff_manifest_path)
        identity["quantitative_handoff_manifest_sha256"] = file_sha256(quantitative_handoff_manifest_path)
    return identity


def _stage_request(
    *,
    paths: ScienceRunPaths,
    metadata: Mapping[str, Any],
    state: Mapping[str, Any],
    stage_name: str,
    attempt: int,
    quiet: bool,
    quantitative_handoff_manifest_path: Path | None = None,
) -> SurveyStageRequest | IdeaStageRequest | ExperimentDesignStageRequest | AuthorStageRequest:
    topic, options, _immutable_inputs = _metadata_inputs(metadata)
    attempt_dir = _stage_attempt_dir(paths, stage_name, attempt)
    science_run_id = _text(metadata.get("science_run_id"))
    if stage_name == "survey":
        def record_service_process(process_id: int) -> None:
            with locked_science_run(paths):
                persisted_metadata, persisted_state = load_science_run(paths)
                if persisted_metadata.get("science_run_id") != metadata.get("science_run_id"):
                    raise ScienceRunStateError(
                        "Science run metadata changed while recording the Survey service process"
                    )
                record_stage_service_process(
                    persisted_state,
                    "survey",
                    attempt=attempt,
                    process_id=process_id,
                )
                save_science_state(paths, persisted_state)

        return SurveyStageRequest(
            config_path=paths.config_snapshot,
            topic=topic,
            attempt_dir=attempt_dir,
            survey_run_id=f"{science_run_id}-survey-{attempt:03d}",
            quiet=quiet,
            on_service_process_started=record_service_process,
        )

    survey = _completed_stage(
        paths,
        state,
        "survey",
        consumer_stage=stage_name,
        expected_topic=topic,
    )
    if stage_name == "idea":
        quantitative_options = _mapping(options.get("quantitative"))
        return IdeaStageRequest(
            config_path=paths.config_snapshot,
            topic=topic,
            survey_manifest_path=survey.canonical_path,
            survey_identity=survey.identity,
            attempt_dir=attempt_dir,
            quiet=quiet,
            science_run_id=science_run_id,
            quantitative_mode=(
                _text(quantitative_options.get("mode"))
                or _text(options.get("quantitative_mode"))
                or "off"
            ),
            model=_text(_mapping(options.get("models")).get("quantitative")) or None,
        )

    idea = _completed_stage(
        paths,
        state,
        "idea",
        consumer_stage=stage_name,
        expected_topic=topic,
    )
    if stage_name == "exp_design":
        selected_direction = _text(options.get("selected_direction")) or _text(
            idea.identity.get("selected_direction_id")
        )
        return ExperimentDesignStageRequest(
            config_path=paths.config_snapshot,
            topic=topic,
            idea_result_path=idea.canonical_path,
            idea_manifest_path=idea.manifest_path,
            idea_identity=idea.identity,
            attempt_dir=attempt_dir,
            science_run_id=science_run_id,
            discipline_ids=tuple(str(value) for value in options.get("discipline_ids") or []),
            selected_direction=selected_direction,
            model=_text(_mapping(options.get("models")).get("experiment_design")) or None,
        )

    design = _completed_stage(
        paths,
        state,
        "exp_design",
        consumer_stage=stage_name,
        expected_topic=topic,
    )
    return AuthorStageRequest(
        config_path=paths.config_snapshot,
        topic=topic,
        author_input_path=design.canonical_path,
        survey_manifest_path=survey.canonical_path,
        idea_result_path=idea.canonical_path,
        idea_manifest_path=idea.manifest_path,
        experiment_design_manifest_path=design.manifest_path,
        survey_identity=survey.identity,
        attempt_dir=attempt_dir,
        model=_text(_mapping(options.get("models")).get("author")) or None,
        rendering=_mapping(options.get("author_rendering")),
        render_required=bool(_mapping(options.get("author_rendering")).get("required", False)),
        survey_appendix=_text(options.get("survey_appendix")) or "source-link",
        quantitative_handoff_manifest_path=quantitative_handoff_manifest_path,
    )


def _service_for(services: ScienceStageServices, stage_name: str):
    return {
        "survey": services.survey,
        "idea": services.idea,
        "exp_design": services.exp_design,
        "author": services.author,
    }[stage_name]


def _normalize_result(
    result: ScienceStageResult,
    *,
    stage_name: str,
    attempt_dir: Path,
) -> ScienceStageResult:
    if not isinstance(result, ScienceStageResult):
        raise ScienceWorkflowError(
            stage_name,
            _STAGE_EXIT_CODES[stage_name],
            f"{stage_name} service returned an invalid result object",
        )
    if result.stage != stage_name:
        raise ScienceWorkflowError(
            stage_name,
            _STAGE_EXIT_CODES[stage_name],
            f"{stage_name} service reported the wrong stage: {result.stage!r}",
        )
    result_path = Path(result.result_path).expanduser().resolve()
    try:
        result_path.relative_to(attempt_dir)
    except ValueError as exc:
        raise ScienceWorkflowError(
            stage_name,
            _STAGE_EXIT_CODES[stage_name],
            f"{stage_name} result is outside its allocated attempt directory: {result_path}",
        ) from exc
    if not result_path.is_file():
        raise ScienceWorkflowError(
            stage_name,
            _STAGE_EXIT_CODES[stage_name],
            f"{stage_name} service did not publish its result path: {result_path}",
        )
    outputs: dict[str, str] = {}
    for key, value in result.outputs.items():
        output_path = Path(_text(value)).expanduser().resolve()
        try:
            output_path.relative_to(attempt_dir)
        except ValueError as exc:
            raise ScienceWorkflowError(
                stage_name,
                _STAGE_EXIT_CODES[stage_name],
                f"{stage_name} output {key!r} is outside its allocated attempt directory: {output_path}",
            ) from exc
        if not output_path.exists():
            raise ScienceWorkflowError(
                stage_name,
                _STAGE_EXIT_CODES[stage_name],
                f"{stage_name} service did not publish output {key!r}: {output_path}",
            )
        outputs[str(key)] = str(output_path)
    identity = {str(key): _text(value) for key, value in result.identity.items() if _text(value)}
    if not identity:
        raise ScienceWorkflowError(
            stage_name,
            _STAGE_EXIT_CODES[stage_name],
            f"{stage_name} service returned no result identity",
        )
    result_sha256 = file_sha256(result_path)
    supplied_sha256 = _text(identity.get("result_sha256"))
    if supplied_sha256 and supplied_sha256 != result_sha256:
        raise ScienceWorkflowError(
            stage_name,
            _STAGE_EXIT_CODES[stage_name],
            f"{stage_name} service supplied a result fingerprint that does not match its published result",
        )
    identity["result_sha256"] = result_sha256
    return ScienceStageResult(
        stage=stage_name,
        result_path=result_path,
        outputs=outputs,
        identity=identity,
        metadata=dict(result.metadata),
    )


def _verify_published_stage_result(
    result: ScienceStageResult,
    *,
    stage_name: str,
    expected_topic: str,
    expected_render_required: bool | None = None,
) -> None:
    try:
        verified = verify_stage_manifest(
            stage_name,
            result.result_path,
            expected_topic=expected_topic,
            expected_render_required=expected_render_required,
        )
    except ScienceManifestError as exc:
        raise ScienceWorkflowError(
            stage_name,
            _STAGE_EXIT_CODES[stage_name],
            f"{stage_name} published manifest validation failed: {exc}",
        ) from exc
    for field in (*_IDENTITY_FIELDS, "selected_direction_id"):
        published_value = _text(result.identity.get(field))
        verified_value = _text(verified.identity.get(field))
        if published_value and published_value != verified_value:
            raise ScienceWorkflowError(
                stage_name,
                _STAGE_EXIT_CODES[stage_name],
                f"{stage_name} published manifest identity differs from its service result for {field}",
            )


def _recover_interrupted_stages(
    paths: ScienceRunPaths,
    metadata: Mapping[str, Any],
) -> None:
    """Recover completed manifests from stale attempts or preserve them as failed."""

    topic, options, _immutable_inputs = _metadata_inputs(metadata)
    expected_render_required = _expected_render_required(options)
    with locked_science_run(paths):
        persisted_metadata, state = load_science_run(paths)
        if persisted_metadata.get("science_run_id") != metadata.get("science_run_id"):
            raise ScienceRunStateError("Science run metadata changed while recovering interrupted stages")
        changed = False
        for stage_name in SCIENCE_STAGE_NAMES:
            stage = _mapping(_mapping(state.get("stages")).get(stage_name))
            if stage.get("status") != "RUNNING":
                continue
            if is_stage_execution_active(stage):
                owner = _mapping(stage.get("execution_owner"))
                raise ScienceWorkflowError(
                    stage_name,
                    _STAGE_EXIT_CODES[stage_name],
                    f"{stage_name} is still running under process {owner.get('pid')}",
                    observed_state=state,
                )
            attempt = int(stage.get("attempt") or 0)
            manifest_path = _stage_attempt_dir(paths, stage_name, attempt) / _STAGE_MANIFEST_FILENAMES[stage_name]
            if manifest_path.is_file():
                try:
                    verified = verify_stage_manifest(
                        stage_name,
                        manifest_path,
                        expected_topic=topic,
                        expected_render_required=expected_render_required,
                    )
                except ScienceManifestError as exc:
                    recovery_message = (
                        f"Interrupted attempt {attempt} did not publish a verifiable manifest: {exc}"
                    )
                else:
                    identity = dict(verified.identity)
                    identity["result_sha256"] = file_sha256(manifest_path)
                    outputs = {
                        f"{stage_name}_manifest": str(manifest_path),
                        **{name: str(path) for name, path in verified.artifacts.items()},
                    }
                    mark_stage_completed(
                        state,
                        stage_name,
                        result_manifest_path=str(manifest_path),
                        outputs=outputs,
                        result_identity=identity,
                    )
                    append_science_event(
                        paths,
                        event_type="STAGE_RECOVERED",
                        stage=stage_name,
                        attempt=attempt,
                        result_path=str(manifest_path),
                    )
                    changed = True
                    continue
            else:
                recovery_message = f"Interrupted attempt {attempt} has no published manifest"
            mark_stage_failed(
                state,
                stage_name,
                exit_code=_STAGE_EXIT_CODES[stage_name],
                message=recovery_message,
                error_type="InterruptedScienceStage",
            )
            append_science_event(
                paths,
                event_type="STAGE_RECOVERY_RETRY",
                stage=stage_name,
                attempt=attempt,
                message=recovery_message,
            )
            changed = True
        if changed:
            save_science_state(paths, state)


def _coerce_stage_error(stage_name: str, error: Exception) -> ScienceWorkflowError:
    if isinstance(error, ScienceWorkflowError):
        return error
    if isinstance(error, ScienceStageError) and error.stage == stage_name:
        return ScienceWorkflowError(stage_name, error.exit_code, str(error))
    return ScienceWorkflowError(
        stage_name,
        _STAGE_EXIT_CODES[stage_name],
        f"{stage_name} service failed: {type(error).__name__}: {error}",
    )


def _record_failure(
    paths: ScienceRunPaths,
    *,
    stage_name: str,
    attempt: int,
    error: ScienceWorkflowError,
) -> None:
    with locked_science_run(paths):
        _metadata, state = load_science_run(paths)
        stage = _mapping(_mapping(state.get("stages")).get(stage_name))
        if stage.get("status") != "RUNNING" or stage.get("attempt") != attempt:
            raise ScienceRunStateError(
                f"Cannot record {stage_name} failure because its attempt is no longer running"
            )
        mark_stage_failed(
            state,
            stage_name,
            exit_code=error.exit_code,
            message=str(error),
            error_type=type(error).__name__,
        )
        save_science_state(paths, state)
        append_science_event(
            paths,
            event_type="STAGE_FAILED",
            stage=stage_name,
            attempt=attempt,
            exit_code=error.exit_code,
            message=str(error),
        )


def _run_stage(
    *,
    paths: ScienceRunPaths,
    metadata: Mapping[str, Any],
    stage_name: str,
    services: ScienceStageServices,
    quiet: bool,
    quantitative_handoff_manifest_path: Path | None = None,
) -> None:
    with locked_science_run(paths):
        persisted_metadata, state = load_science_run(paths)
        if persisted_metadata.get("science_run_id") != metadata.get("science_run_id"):
            raise ScienceRunStateError("Science run metadata changed while preparing a stage")
        stage = _mapping(_mapping(state.get("stages")).get(stage_name))
        if stage.get("status") == "COMPLETED":
            topic, options, _immutable_inputs = _metadata_inputs(persisted_metadata)
            if stage_name == "author" and quantitative_handoff_manifest_path is not None:
                recorded_handoff = _text(
                    _mapping(stage.get("input_identity")).get(
                        "quantitative_handoff_manifest_path"
                    )
                )
                if recorded_handoff != str(quantitative_handoff_manifest_path):
                    raise ScienceWorkflowError(
                        "author",
                        _STAGE_EXIT_CODES["author"],
                        "Author is already completed without this quantitative handoff; "
                        "use --restart-from author --force",
                    )
            _completed_stage(
                paths,
                state,
                stage_name,
                consumer_stage=stage_name,
                expected_topic=topic,
                expected_render_required=(
                    _expected_render_required(options) if stage_name == "author" else None
                ),
            )
            return
        if stage.get("status") == "RUNNING":
            raise ScienceWorkflowError(
                stage_name,
                _STAGE_EXIT_CODES[stage_name],
                f"{stage_name} already has a running attempt; use --restart-from after inspecting it",
            )
        input_identity: dict[str, Any]
        try:
            input_identity = _input_identity(
                paths,
                state,
                persisted_metadata,
                stage_name,
                quantitative_handoff_manifest_path,
            )
            mark_stage_running(state, stage_name, input_identity=input_identity)
            attempt = int(_mapping(_mapping(state.get("stages")).get(stage_name)).get("attempt") or 0)
            request = _stage_request(
                paths=paths,
                metadata=persisted_metadata,
                state=state,
                stage_name=stage_name,
                attempt=attempt,
                quiet=quiet,
                quantitative_handoff_manifest_path=quantitative_handoff_manifest_path,
            )
        except Exception as exc:
            error = _coerce_stage_error(stage_name, exc)
            current_stage = _mapping(_mapping(state.get("stages")).get(stage_name))
            if current_stage.get("status") != "RUNNING":
                mark_stage_running(state, stage_name, input_identity={})
                attempt = int(_mapping(_mapping(state.get("stages")).get(stage_name)).get("attempt") or 0)
            else:
                attempt = int(current_stage.get("attempt") or 0)
            mark_stage_failed(
                state,
                stage_name,
                exit_code=error.exit_code,
                message=str(error),
                error_type=type(error).__name__,
            )
            save_science_state(paths, state)
            append_science_event(
                paths,
                event_type="STAGE_FAILED",
                stage=stage_name,
                attempt=attempt,
                exit_code=error.exit_code,
                message=str(error),
            )
            raise error from exc
        save_science_state(paths, state)
        append_science_event(
            paths,
            event_type="STAGE_STARTED",
            stage=stage_name,
            attempt=attempt,
            attempt_dir=str(_stage_attempt_dir(paths, stage_name, attempt)),
            input_identity=input_identity,
        )

    attempt_dir = _stage_attempt_dir(paths, stage_name, attempt)
    try:
        result = _normalize_result(
            _service_for(services, stage_name)(request),
            stage_name=stage_name,
            attempt_dir=attempt_dir,
        )
        topic, options, _immutable_inputs = _metadata_inputs(metadata)
        _verify_published_stage_result(
            result,
            stage_name=stage_name,
            expected_topic=topic,
            expected_render_required=(
                _expected_render_required(options) if stage_name == "author" else None
            ),
        )
    except Exception as exc:
        error = _coerce_stage_error(stage_name, exc)
        _record_failure(paths, stage_name=stage_name, attempt=attempt, error=error)
        raise error from exc

    with locked_science_run(paths):
        _persisted_metadata, state = load_science_run(paths)
        stage = _mapping(_mapping(state.get("stages")).get(stage_name))
        if stage.get("status") != "RUNNING" or stage.get("attempt") != attempt:
            raise ScienceRunStateError(
                f"Cannot record {stage_name} completion because its attempt is no longer running"
            )
        mark_stage_completed(
            state,
            stage_name,
            result_manifest_path=str(result.result_path),
            outputs=result.outputs,
            result_identity=result.identity,
        )
        save_science_state(paths, state)
        append_science_event(
            paths,
            event_type="STAGE_COMPLETED",
            stage=stage_name,
            attempt=attempt,
            result_path=str(result.result_path),
            outputs=dict(result.outputs),
            result_identity=dict(result.identity),
        )


def _finish_workflow(paths: ScienceRunPaths, *, until: str) -> ScienceWorkflowOutcome:
    with locked_science_run(paths):
        metadata, state = load_science_run(paths)
        stages = _mapping(state.get("stages"))
        all_completed = all(
            _mapping(stages.get(stage_name)).get("status") == "COMPLETED"
            for stage_name in SCIENCE_STAGE_NAMES
        )
        next_status = "COMPLETED" if all_completed else "PARTIAL"
        if state.get("status") != next_status:
            state["status"] = next_status
            state["last_updated_at"] = utc_now()
            save_science_state(paths, state)
            append_science_event(
                paths,
                event_type="RUN_COMPLETED" if all_completed else "RUN_PARTIAL",
                until=until,
            )
        return ScienceWorkflowOutcome(metadata=metadata, state=state)


def run_science_workflow(
    *,
    paths: ScienceRunPaths,
    metadata: Mapping[str, Any],
    until: str = "author",
    services: ScienceStageServices | None = None,
    quiet: bool = False,
    quantitative_handoff_manifest_path: str | Path | None = None,
) -> ScienceWorkflowOutcome:
    """Run pending stages serially with exact persisted handoff paths.

    State transitions are locked and atomically written, while each potentially
    long-running service is intentionally invoked after releasing the run lock.
    """

    if until not in SCIENCE_STAGE_NAMES:
        raise ScienceWorkflowError("survey", 2, f"Unknown science stage: {until}")
    active_services = services or default_science_stage_services()
    handoff_path: Path | None = None
    if quantitative_handoff_manifest_path is not None:
        handoff_path = Path(quantitative_handoff_manifest_path).expanduser().resolve()
        try:
            handoff_path.relative_to((paths.run_dir / "quantitative").resolve())
        except ValueError as exc:
            raise ScienceWorkflowError(
                "author",
                _STAGE_EXIT_CODES["author"],
                "quantitative Author handoff must remain under the science run quantitative directory",
            ) from exc
        if not handoff_path.is_file():
            raise ScienceWorkflowError(
                "author",
                _STAGE_EXIT_CODES["author"],
                f"quantitative Author handoff does not exist: {handoff_path}",
            )
    _recover_interrupted_stages(paths, metadata)
    for stage_name in SCIENCE_STAGE_NAMES[: SCIENCE_STAGE_NAMES.index(until) + 1]:
        _run_stage(
            paths=paths,
            metadata=metadata,
            stage_name=stage_name,
            services=active_services,
            quiet=quiet,
            quantitative_handoff_manifest_path=handoff_path,
        )
    return _finish_workflow(paths, until=until)


__all__ = [
    "ScienceWorkflowError",
    "ScienceWorkflowOutcome",
    "run_science_workflow",
]
