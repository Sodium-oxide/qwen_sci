"""Structured stage services for the resumable science workflow."""

from __future__ import annotations

import contextlib
import json
import os
import re
import subprocess
import sys
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from omegaconf import OmegaConf

from src.pipeline.science_run import atomic_write_json, atomic_write_text, file_sha256, text_sha256
from src.pipeline.science_manifests import (
    ScienceManifestError,
    write_author_manifest,
    write_experiment_design_manifest,
    write_idea_manifest,
)
from src.pipeline.survey_idea_loader import SurveyIdeaLoadError, load_survey_idea_context


REPO_ROOT = Path(__file__).resolve().parents[2]
_WINDOWS_DRIVE_PATH = re.compile(r"^[A-Za-z]:[\\/]")


class ScienceStageError(RuntimeError):
    """A stage failure with a stable top-level science exit code."""

    def __init__(self, stage: str, exit_code: int, message: str) -> None:
        super().__init__(message)
        self.stage = stage
        self.exit_code = exit_code


@dataclass(frozen=True)
class ScienceStageResult:
    """One successfully published stage result and its exact handoff path."""

    stage: str
    result_path: Path
    outputs: Mapping[str, str]
    identity: Mapping[str, str]
    metadata: Mapping[str, Any]


@dataclass(frozen=True)
class SurveyStageRequest:
    config_path: Path
    topic: str
    attempt_dir: Path
    survey_run_id: str
    quiet: bool = False
    on_service_process_started: Callable[[int], None] | None = None


@dataclass(frozen=True)
class IdeaStageRequest:
    config_path: Path
    topic: str
    survey_manifest_path: Path
    survey_identity: Mapping[str, str]
    attempt_dir: Path
    quiet: bool = False


@dataclass(frozen=True)
class ExperimentDesignStageRequest:
    config_path: Path
    topic: str
    idea_result_path: Path
    idea_manifest_path: Path
    idea_identity: Mapping[str, str]
    attempt_dir: Path
    science_run_id: str
    discipline_ids: tuple[str, ...]
    selected_direction: str
    model: str | None


@dataclass(frozen=True)
class AuthorStageRequest:
    config_path: Path
    topic: str
    author_input_path: Path
    survey_manifest_path: Path
    idea_result_path: Path
    idea_manifest_path: Path
    experiment_design_manifest_path: Path
    survey_identity: Mapping[str, str]
    attempt_dir: Path
    model: str | None
    rendering: Mapping[str, Any]
    render_required: bool = False
    survey_appendix: str = "source-link"


@dataclass(frozen=True)
class ScienceStageServices:
    """Callable service bundle that makes workflow orchestration testable."""

    survey: Callable[[SurveyStageRequest], ScienceStageResult]
    idea: Callable[[IdeaStageRequest], ScienceStageResult]
    exp_design: Callable[[ExperimentDesignStageRequest], ScienceStageResult]
    author: Callable[[AuthorStageRequest], ScienceStageResult]


def default_science_stage_services() -> ScienceStageServices:
    return ScienceStageServices(
        survey=run_survey_stage,
        idea=run_idea_stage,
        exp_design=run_experiment_design_stage,
        author=run_author_stage,
    )


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _text(value: object) -> str:
    return str(value or "").strip()


def _resolve_author_runtime_path(value: object, *, force_path: bool = False) -> str | Path | None:
    """Resolve YAML and CLI rendering paths consistently on Windows and WSL."""

    raw_value = _text(value)
    if not raw_value:
        return None
    looks_like_path = force_path or "/" in raw_value.replace("\\", "/") or bool(
        _WINDOWS_DRIVE_PATH.match(raw_value)
    )
    if not looks_like_path:
        return raw_value
    from src.agents.research_plan_author.run import _resolve_optional_path

    return _resolve_optional_path(raw_value)


def _identity_from_survey_context(context: object) -> dict[str, str]:
    return {
        "survey_run_id": _text(getattr(context, "survey_run_id", "")),
        "project_id": _text(getattr(context, "project_id", "")),
        "project_context_fingerprint": _text(
            getattr(context, "project_context_fingerprint", "")
        ),
        "survey_manifest_path": str(getattr(context, "manifest_path")).strip(),
        "manifest_fingerprint": file_sha256(getattr(context, "manifest_path")),
        "handoff_fingerprint": _text(
            _mapping(getattr(context, "handoff", {})).get("handoff_fingerprint")
        ),
        "topic_fingerprint": text_sha256(_text(getattr(context, "topic", ""))),
    }


def _require_identity(
    actual: Mapping[str, object],
    expected: Mapping[str, str],
    *,
    stage: str,
    exit_code: int,
) -> dict[str, str]:
    required = (
        "survey_run_id",
        "project_id",
        "project_context_fingerprint",
    )
    normalized = {field: _text(actual.get(field)) for field in required}
    missing = [field for field, value in normalized.items() if not value]
    if missing:
        raise ScienceStageError(
            stage,
            exit_code,
            "Survey binding is incomplete; missing " + ", ".join(missing),
        )
    mismatched = [field for field in required if normalized[field] != _text(expected.get(field))]
    if mismatched:
        raise ScienceStageError(
            stage,
            exit_code,
            "Survey binding differs for " + ", ".join(mismatched),
        )
    expected_manifest_path = _text(expected.get("survey_manifest_path"))
    actual_manifest_path = _text(actual.get("survey_manifest_path") or actual.get("manifest_path"))
    if expected_manifest_path:
        if not actual_manifest_path:
            raise ScienceStageError(stage, exit_code, "Survey binding is missing manifest_path")
        if Path(actual_manifest_path).expanduser().resolve() != Path(expected_manifest_path).expanduser().resolve():
            raise ScienceStageError(stage, exit_code, "Survey binding differs for manifest_path")
    expected_handoff_fingerprint = _text(expected.get("handoff_fingerprint"))
    actual_handoff_fingerprint = _text(actual.get("handoff_fingerprint"))
    if expected_handoff_fingerprint and actual_handoff_fingerprint != expected_handoff_fingerprint:
        raise ScienceStageError(stage, exit_code, "Survey binding differs for handoff_fingerprint")
    return {
        **dict(expected),
        **normalized,
        **({"survey_manifest_path": expected_manifest_path} if expected_manifest_path else {}),
        **({"handoff_fingerprint": expected_handoff_fingerprint} if expected_handoff_fingerprint else {}),
    }


def _stage_environment(config_path: Path) -> dict[str, str]:
    for candidate in (REPO_ROOT / ".env", REPO_ROOT / "src" / "config" / ".env"):
        if candidate.exists():
            load_dotenv(candidate, override=False)
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(REPO_ROOT) + (
        os.pathsep + environment["PYTHONPATH"] if environment.get("PYTHONPATH") else ""
    )
    environment["QWENSCI_CONFIG"] = str(config_path)
    environment["QWENSCI_CONFIG_PATH"] = str(config_path)
    return environment


def _survey_override_key(config_path: Path, key: str) -> str:
    config = OmegaConf.to_container(OmegaConf.load(config_path), resolve=False)
    prefix = "survey." if isinstance(config, dict) and "survey" in config else ""
    return f"{prefix}{key}"


def _survey_runtime_config(request: SurveyStageRequest) -> Path:
    try:
        config = OmegaConf.load(request.config_path)
        values = {
            "BasicInfo.topic": request.topic,
            "BasicInfo.survey_run_id": request.survey_run_id,
            "BasicInfo.base_dir": str(request.attempt_dir),
            "BasicInfo.save_path": str(request.attempt_dir / "survey.md"),
            "BasicInfo.save_json_path": str(request.attempt_dir / "survey.json"),
            "BasicInfo.evaluation_save_path": str(request.attempt_dir / "evaluation.txt"),
        }
        for key, value in values.items():
            OmegaConf.update(config, _survey_override_key(request.config_path, key), value, merge=False)
        request.attempt_dir.mkdir(parents=True, exist_ok=True)
        runtime_path = request.attempt_dir / f"science_survey_{uuid.uuid4().hex}.yaml"
        OmegaConf.save(config, runtime_path)
        return runtime_path
    except Exception as exc:
        raise ScienceStageError("survey", 10, f"Cannot create Survey runtime config: {exc}") from exc


def run_survey_stage(request: SurveyStageRequest) -> ScienceStageResult:
    """Run Survey in an isolated attempt directory and verify its manifest."""

    runtime_config = _survey_runtime_config(request)
    environment = _stage_environment(runtime_config)
    for key in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY"):
        environment.pop(key, None)
    environment["no_proxy"] = "58.210.177.113,localhost,127.0.0.1"
    environment.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
    environment.setdefault("MINERU_MODEL_SOURCE", "modelscope")
    command = [
        sys.executable,
        str(REPO_ROOT / "src" / "agents" / "survey_agent" / "scripts" / "run_deep_survey.py"),
        "--config-path",
        str(runtime_config.parent),
        "--config-name",
        runtime_config.stem,
    ]
    run_kwargs: dict[str, object] = {"cwd": str(REPO_ROOT), "env": environment}
    if request.quiet:
        run_kwargs.update({"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL})
    try:
        process = subprocess.Popen(command, **run_kwargs)
    except OSError as exc:
        raise ScienceStageError("survey", 10, f"Survey process could not start: {exc}") from exc
    callback_error: Exception | None = None
    try:
        if request.on_service_process_started is not None:
            try:
                request.on_service_process_started(process.pid)
            except Exception as exc:
                callback_error = exc
        return_code = process.wait()
    finally:
        runtime_config.unlink(missing_ok=True)
    if callback_error is not None:
        raise ScienceStageError(
            "survey", 10, f"Survey process ownership could not be recorded: {callback_error}"
        ) from callback_error
    if return_code:
        raise ScienceStageError("survey", 10, f"Survey process exited with code {return_code}")
    manifest_path = request.attempt_dir / "survey_manifest.json"
    try:
        context = load_survey_idea_context(manifest_path)
    except SurveyIdeaLoadError as exc:
        raise ScienceStageError("survey", 11, f"Survey manifest validation failed: {exc}") from exc
    if context.topic.casefold() != request.topic.casefold():
        raise ScienceStageError("survey", 11, "Survey manifest topic differs from the science run topic")
    identity = _identity_from_survey_context(context)
    return ScienceStageResult(
        stage="survey",
        result_path=context.manifest_path,
        outputs={
            "survey_manifest": str(context.manifest_path),
            "survey_markdown": str(context.base_dir / "survey.md"),
            "survey_json": str(context.base_dir / "survey.json"),
            "survey_handoff": str(context.base_dir / "survey_idea_handoff.json"),
            "survey_gap_ledger": str(context.base_dir / "survey_gap_ledger.json"),
        },
        identity=identity,
        metadata={"topic": context.topic},
    )


def run_idea_stage(request: IdeaStageRequest) -> ScienceStageResult:
    """Run Idea with a fixed output directory and canonical result path."""

    try:
        from src.agents.idea_agent.run import run_idea_workflow

        stream = sys.stderr if request.quiet else sys.stdout
        with contextlib.redirect_stdout(stream):
            result_dir = Path(
                run_idea_workflow(
                    config_path=str(request.config_path),
                    topic=request.topic,
                    output_root=str(request.attempt_dir.parent),
                    run_id=request.attempt_dir.name,
                    survey_manifest=str(request.survey_manifest_path),
                    include_console=not request.quiet,
                )
            ).resolve()
    except SurveyIdeaLoadError as exc:
        raise ScienceStageError("idea", 21, f"Idea Survey binding failed: {exc}") from exc
    except Exception as exc:
        raise ScienceStageError("idea", 20, f"Idea execution failed: {exc}") from exc
    idea_result_path = result_dir / "idea_result.json"
    try:
        payload = json.loads(idea_result_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ScienceStageError("idea", 21, f"Idea result is unavailable: {idea_result_path}: {exc}") from exc
    if _text(payload.get("schema_version")) != "idea_result_v5":
        raise ScienceStageError("idea", 21, "Idea result must use schema_version idea_result_v5")
    if _text(payload.get("topic")).casefold() != request.topic.casefold():
        raise ScienceStageError("idea", 21, "Idea result topic differs from the science run topic")
    binding = _mapping(payload.get("survey_binding"))
    identity = _require_identity(binding, request.survey_identity, stage="idea", exit_code=21)
    selected_direction = _text(payload.get("primary_direction"))
    if not selected_direction:
        raise ScienceStageError("idea", 21, "Idea result has no primary_direction")
    identity["selected_direction_id"] = selected_direction
    try:
        manifest_path = write_idea_manifest(
            attempt_dir=request.attempt_dir,
            topic=request.topic,
            idea_result_path=idea_result_path,
            survey_manifest_path=request.survey_manifest_path,
            identity=identity,
            selected_direction_id=selected_direction,
        )
    except ScienceManifestError as exc:
        raise ScienceStageError("idea", 21, f"Idea manifest publication failed: {exc}") from exc
    return ScienceStageResult(
        stage="idea",
        result_path=manifest_path,
        outputs={
            "idea_manifest": str(manifest_path),
            "idea_result": str(idea_result_path),
            "idea_run_dir": str(result_dir),
        },
        identity=identity,
        metadata={"selected_direction_id": selected_direction},
    )


def run_experiment_design_stage(request: ExperimentDesignStageRequest) -> ScienceStageResult:
    """Run the existing design-only ExperimentDesign API and publish exact paths."""

    logger = None
    try:
        from src.agents.experiment_design_agent.artifacts import (
            generate_timestamp,
            write_experiment_design_artifacts,
        )
        from src.agents.experiment_design_agent.discipline_catalog import resolve_design_scope
        from src.agents.experiment_design_agent.idea_intake import load_idea_artifact_bundle
        from src.agents.experiment_design_agent.run import run_experiment_design
        from src.agents.experiment_design_agent.run_logging import ExperimentDesignRunLogger
        from src.config import load_config

        config = load_config(str(request.config_path))
        idea_bundle = load_idea_artifact_bundle(request.idea_result_path)
        discipline_ids = list(request.discipline_ids)
        if not discipline_ids:
            embedded = _mapping(idea_bundle.get("idea_result")).get("discipline_ids")
            if isinstance(embedded, str):
                discipline_ids = [embedded]
            elif isinstance(embedded, (list, tuple)):
                discipline_ids = [str(value) for value in embedded]
        if not discipline_ids:
            raise ScienceStageError("exp_design", 30, "No discipline_ids were supplied by science input or Idea")
        scope = resolve_design_scope(discipline_ids)
        if scope.get("status") != "IN_SCOPE":
            raise ScienceStageError(
                "exp_design",
                30,
                f"ExperimentDesign scope rejected input: {scope.get('status')}: {scope.get('reason')}",
            )
        request.attempt_dir.mkdir(parents=True, exist_ok=True)
        timestamp = generate_timestamp()
        log_path = request.attempt_dir / f"experiment_design_{timestamp}.jsonl"
        logger = ExperimentDesignRunLogger(f"science-exp-design-{timestamp}", jsonl_path=log_path)
        try:
            result = run_experiment_design(
                str(request.idea_result_path),
                discipline_ids=discipline_ids,
                brief_id=request.science_run_id,
                selected_direction=request.selected_direction,
                config=config,
                llm_model=request.model,
                logger=logger,
            )
            with logger.stage("artifacts", output_dir=str(request.attempt_dir)):
                artifact_paths = write_experiment_design_artifacts(
                    result,
                    request.attempt_dir,
                    timestamp=timestamp,
                    idea_result_path=str(request.idea_result_path),
                )
        finally:
            if logger is not None:
                logger.close()
    except ScienceStageError:
        raise
    except Exception as exc:
        code = 31 if exc.__class__.__name__.startswith("Artifact") else 30
        raise ScienceStageError("exp_design", code, f"ExperimentDesign execution failed: {exc}") from exc
    design = _mapping(result.get("experiment_design"))
    if _text(_mapping(design.get("execution_policy")).get("mode")) != "DESIGN_ONLY":
        raise ScienceStageError("exp_design", 30, "ExperimentDesign returned a non-design-only execution mode")
    artifacts = _mapping(artifact_paths.as_dict())
    author_json = Path(_text(artifacts.get("author_json"))).resolve()
    try:
        handoff = json.loads(author_json.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ScienceStageError("exp_design", 31, f"ExperimentDesign Author handoff is unavailable: {exc}") from exc
    identity = _require_identity(
        _mapping(_mapping(handoff.get("provenance")).get("survey_binding")),
        request.idea_identity,
        stage="exp_design",
        exit_code=31,
    )
    provenance = _mapping(handoff.get("provenance"))
    selected_direction = _text(provenance.get("selected_direction_id"))
    expected_direction = _text(request.selected_direction) or _text(
        request.idea_identity.get("selected_direction_id")
    )
    if not selected_direction:
        raise ScienceStageError("exp_design", 31, "ExperimentDesign Author handoff has no selected direction")
    if expected_direction and selected_direction != expected_direction:
        raise ScienceStageError("exp_design", 31, "ExperimentDesign selected direction differs from the requested Idea direction")
    identity["selected_direction_id"] = selected_direction
    string_artifacts = {
        key: str(artifacts[key])
        for key in (
            "experiment_design_json",
            "experiment_design_markdown",
            "author_json",
        )
    }
    try:
        manifest_path = write_experiment_design_manifest(
            attempt_dir=request.attempt_dir,
            topic=request.topic,
            idea_manifest_path=request.idea_manifest_path,
            idea_result_path=request.idea_result_path,
            artifact_paths=string_artifacts,
            identity=identity,
            design_id=_text(design.get("design_id")),
            selected_direction_id=selected_direction,
            discipline_ids=[str(value) for value in discipline_ids],
            log_path=log_path,
        )
    except (KeyError, ScienceManifestError) as exc:
        raise ScienceStageError("exp_design", 31, f"ExperimentDesign manifest publication failed: {exc}") from exc
    string_artifacts["experiment_design_manifest"] = str(manifest_path)
    return ScienceStageResult(
        stage="exp_design",
        result_path=manifest_path,
        outputs=string_artifacts,
        identity=identity,
        metadata={"design_id": _text(design.get("design_id")), "log_file": str(log_path)},
    )


def _write_verified_survey_artifacts(request: AuthorStageRequest) -> dict[str, str]:
    mode = _text(request.survey_appendix) or "source-link"
    if mode not in {"source-link", "full-text"}:
        raise ScienceStageError("author", 41, f"Unsupported survey appendix mode: {mode}")
    try:
        survey_context = load_survey_idea_context(request.survey_manifest_path)
        survey_markdown_path = survey_context.base_dir / "survey.md"
        source_binding_path = request.attempt_dir / "survey_source_binding.json"
        atomic_write_json(
            source_binding_path,
            {
                "schema_version": "science_survey_source_binding_v1",
                "mode": mode,
                "survey_manifest_path": str(survey_context.manifest_path),
                "survey_manifest_sha256": file_sha256(survey_context.manifest_path),
                "survey_markdown_path": str(survey_markdown_path),
                "survey_markdown_sha256": file_sha256(survey_markdown_path),
                "survey_binding": dict(request.survey_identity),
            },
        )
    except SurveyIdeaLoadError as exc:
        raise ScienceStageError("author", 41, f"Author Survey appendix validation failed: {exc}") from exc
    except OSError as exc:
        raise ScienceStageError("author", 41, f"Author Survey source binding could not be written: {exc}") from exc
    outputs = {"survey_source_binding": str(source_binding_path)}
    if mode == "full-text":
        appendix_path = request.attempt_dir / "verified_survey_appendix.md"
        try:
            atomic_write_text(appendix_path, survey_context.survey_markdown)
        except OSError as exc:
            raise ScienceStageError("author", 41, f"Author Survey appendix could not be written: {exc}") from exc
        outputs["survey_full_text_appendix"] = str(appendix_path)
    return outputs


def _run_author_render(
    render: Callable[[], Mapping[str, str | int]],
    *,
    required: bool,
    logger: Any,
) -> tuple[dict[str, str | int], dict[str, Any]]:
    try:
        artifacts = dict(render())
    except Exception as exc:
        message = f"Author rendering failed: {exc}"
        if required:
            raise ScienceStageError("author", 41, message) from exc
        logger.emit("render", "failed_optional", level="WARNING", status="FAILED_OPTIONAL", error=message)
        return {}, {"status": "FAILED_OPTIONAL", "required": False, "error": message}
    return artifacts, {"status": "COMPLETED", "required": bool(required), "error": ""}


def run_author_stage(request: AuthorStageRequest) -> ScienceStageResult:
    """Run Author with strict Survey binding and return the published document path."""

    logger = None
    try:
        from src.agents.experiment_design_agent.artifacts import generate_timestamp
        from src.agents.research_plan_author.artifacts import write_author_preparation_artifacts
        from src.agents.research_plan_author.llm_json import build_author_json_llm_call
        from src.agents.research_plan_author.render import render_research_plan_document
        from src.agents.research_plan_author.run import run_research_plan_author
        from src.agents.research_plan_author.run_logging import AuthorRunLogger
        from src.config import load_config

        config = load_config(str(request.config_path))
        author_config = _mapping(config.get("research_plan_author", {}))
        if not bool(author_config.get("enabled", True)):
            raise ScienceStageError("author", 40, "research_plan_author.enabled is false")
        request.attempt_dir.mkdir(parents=True, exist_ok=True)
        timestamp = generate_timestamp()
        log_path = request.attempt_dir / f"author_{timestamp}.jsonl"
        logger = AuthorRunLogger(f"science-author-{timestamp}", jsonl_path=log_path)
        idea_config = _mapping(author_config.get("idea_evolution"))
        authoring_config = _mapping(author_config.get("authoring"))
        configured_section_repairs = authoring_config.get(
            "max_contract_repairs_per_section",
            authoring_config.get("max_contract_repairs", 1),
        )
        try:
            result = run_research_plan_author(
                request.author_input_path,
                survey_manifest_path=request.survey_manifest_path,
                idea_result_path=request.idea_result_path,
                include_idea_evolution=str(idea_config.get("default_mode") or "auto"),
                max_idea_iterations=int(idea_config.get("max_iterations") or 3),
                strict_survey_binding=True,
                llm_call=build_author_json_llm_call(config=config, model=request.model),
                max_contract_repairs=int(1 if configured_section_repairs is None else configured_section_repairs),
                composer_concurrency=int(authoring_config.get("composer_concurrency") or 5),
                section_cache_config=_mapping(authoring_config.get("section_cache")),
                logger=logger,
            )
            with logger.stage("artifacts", output_dir=str(request.attempt_dir)):
                artifact_paths = write_author_preparation_artifacts(
                    result,
                    request.attempt_dir,
                    timestamp=timestamp,
            )
            render_artifacts: dict[str, str | int] = {}
            configured_rendering = _mapping(author_config.get("rendering"))
            for executable_key in ("engine", "bibtex", "pdf_renderer"):
                normalized_executable = _resolve_author_runtime_path(
                    configured_rendering.get(executable_key)
                )
                if normalized_executable is not None:
                    configured_rendering[executable_key] = normalized_executable
            rendering = _mapping(request.rendering)
            render_required = bool(request.render_required)
            template_dir_value = _text(rendering.get("template_dir") or configured_rendering.get("template_dir"))
            if template_dir_value:
                template_dir = _resolve_author_runtime_path(template_dir_value, force_path=True)
                template_profile_value = rendering.get("template_profile") or configured_rendering.get("template_profile")
                with logger.stage("render", template_dir=template_dir_value):
                    render_artifacts, render_status = _run_author_render(
                        lambda: render_research_plan_document(
                            result["document"],
                            output_dir=request.attempt_dir,
                            timestamp=timestamp,
                            preparation_collision_index=artifact_paths.collision_index,
                            template_dir=template_dir,
                            template_profile=_resolve_author_runtime_path(template_profile_value),
                            template_main=_text(rendering.get("template_main") or configured_rendering.get("main_tex")),
                            latex_engine=_resolve_author_runtime_path(rendering.get("latex_engine")),
                            bibtex=_resolve_author_runtime_path(rendering.get("bibtex")),
                            pdf_renderer=_resolve_author_runtime_path(rendering.get("pdf_renderer")),
                            compile_timeout_seconds=int(rendering.get("compile_timeout_seconds") or configured_rendering.get("compile_timeout_seconds") or 180),
                            configured_rendering=configured_rendering,
                            author_name=_text(rendering.get("author_name")) or "Anonymous Research Plan Author",
                            logger=logger,
                        ).artifacts.as_dict(),
                        required=render_required,
                        logger=logger,
                    )
            else:
                if render_required:
                    raise ScienceStageError("author", 41, "Author rendering is required but no template_dir is configured")
                logger.emit("render", "not_configured", level="WARNING", status="SKIPPED")
                render_status = {"status": "SKIPPED", "required": False, "error": ""}
            render_status_path = request.attempt_dir / "author_render_status.json"
            atomic_write_json(
                render_status_path,
                {
                    "schema_version": "science_author_render_status_v1",
                    **render_status,
                    "template_dir": template_dir_value,
                },
            )
            with logger.stage("survey_appendix", mode=request.survey_appendix):
                survey_artifacts = _write_verified_survey_artifacts(request)
        finally:
            if logger is not None:
                logger.close()
    except ScienceStageError:
        raise
    except Exception as exc:
        raise ScienceStageError("author", 40, f"Author execution failed: {exc}") from exc
    artifacts = _mapping(artifact_paths.as_dict())
    document_path = Path(_text(artifacts.get("document_json"))).resolve()
    document = _mapping(result.get("document"))
    source_manifest = _mapping(document.get("source_manifest"))
    identity = _require_identity(
        _mapping(source_manifest.get("survey_binding")),
        request.survey_identity,
        stage="author",
        exit_code=40,
    )
    string_artifacts = {
        key: str(artifacts[key])
        for key in (
            "preparation_json",
            "author_context_json",
            "document_json",
            "idea_evolution_json",
        )
    }
    rendered_files = {
        f"render_{key}": str(value)
        for key, value in render_artifacts.items()
        if isinstance(value, str) and Path(value).is_file()
    }
    string_artifacts.update(rendered_files)
    string_artifacts["render_status"] = str(render_status_path)
    string_artifacts.update(survey_artifacts)
    selected_direction = _text(result.get("selected_direction_id"))
    manifest_identity = {**identity, "selected_direction_id": selected_direction}
    try:
        manifest_path = write_author_manifest(
            attempt_dir=request.attempt_dir,
            topic=request.topic,
            survey_manifest_path=request.survey_manifest_path,
            idea_manifest_path=request.idea_manifest_path,
            experiment_design_manifest_path=request.experiment_design_manifest_path,
            author_input_path=request.author_input_path,
            artifact_paths=string_artifacts,
            identity=manifest_identity,
            source_design_id=_text(result.get("source_design_id")),
            selected_direction_id=selected_direction,
            rendering=render_status,
        )
    except (KeyError, ScienceManifestError) as exc:
        raise ScienceStageError("author", 41, f"Author manifest publication failed: {exc}") from exc
    string_artifacts["author_manifest"] = str(manifest_path)
    return ScienceStageResult(
        stage="author",
        result_path=manifest_path,
        outputs=string_artifacts,
        identity=manifest_identity,
        metadata={
            "source_design_id": _text(result.get("source_design_id")),
            "selected_direction_id": _text(result.get("selected_direction_id")),
            "log_file": str(log_path),
            "rendering": render_status,
        },
    )
