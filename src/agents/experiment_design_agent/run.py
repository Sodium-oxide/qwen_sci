"""Complete design-state workflow for one Idea Agent artifact."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
from pathlib import Path
from typing import Any

from .contracts import validate_experiment_design
from .formal_reasoning_planner import FormalReasoningPlanContractError
from .llm_json import RequiredJsonLLMError
from .orchestrator import ExperimentDesignOrchestrator
from .survey_evidence import SurveyEvidenceAdapter
from .run_logging import ExperimentDesignRunLogger


RUN_SCHEMA_VERSION = "experiment_design_run_v1"
RUN_SUCCESS = 0
RUN_INPUT_ERROR = 2
RUN_CONFIG_ERROR = 3
RUN_IDEA_ERROR = 4
RUN_SCOPE_ERROR = 5
RUN_LLM_ERROR = 6
RUN_VALIDATION_ERROR = 7
RUN_RUNTIME_ERROR = 10
_MISSING = object()


class ExperimentDesignRunError(RuntimeError):
    """A stage-specific failure from the complete design workflow."""

    def __init__(
        self,
        stage: str,
        message: str,
        *,
        exit_code: int = RUN_RUNTIME_ERROR,
        audit_record: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(f"{stage}: {message}")
        self.stage = stage
        self.exit_code = exit_code
        self.audit_record = deepcopy(dict(audit_record)) if audit_record is not None else None


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _setting(value: object, key: str, default: object = None) -> object:
    if isinstance(value, Mapping):
        return value.get(key, default)
    return getattr(value, key, default)


def _nested_setting(value: object, keys: Sequence[str], default: object = None) -> object:
    current = value
    for key in keys:
        current = _setting(current, key, _MISSING)
        if current is _MISSING:
            return default
    return current


def _config_int(config: object | None, keys: Sequence[str], default: int) -> int:
    value = _nested_setting(config, keys, default)
    try:
        return max(1, int(value))
    except (TypeError, ValueError):
        return default


def _config_bool(config: object | None, keys: Sequence[str], default: bool = False) -> bool:
    value = _nested_setting(config, keys, default)
    if isinstance(value, str):
        return value.strip().casefold() not in {"", "0", "false", "no", "off", "none"}
    return bool(value)


def _load_config(config: object | None, config_path: str | Path | None) -> object | None:
    if config is not None:
        return config
    try:
        from src.config import load_config

        return load_config(
            str(Path(config_path).expanduser().resolve()) if config_path is not None else None
        )
    except Exception as exc:
        raise ExperimentDesignRunError("config", str(exc), exit_code=RUN_CONFIG_ERROR) from exc


def _resolve_idea_path(value: str | Path) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    path = path.resolve()
    if path.is_dir() or path.suffix == "":
        path = path / "idea_result.json"
    return path.resolve()


def _stage_exit_code(stage: str, exc: Exception) -> int:
    if isinstance(exc, RequiredJsonLLMError):
        return RUN_LLM_ERROR
    if isinstance(exc, FormalReasoningPlanContractError):
        return RUN_LLM_ERROR
    if stage == "intake":
        return RUN_INPUT_ERROR if isinstance(exc, FileNotFoundError) else RUN_IDEA_ERROR
    if stage == "prepare" and ("scope" in str(exc).casefold() or "discipline" in str(exc).casefold()):
        return RUN_SCOPE_ERROR
    if stage == "validation":
        return RUN_VALIDATION_ERROR
    if isinstance(exc, ValueError):
        return RUN_IDEA_ERROR
    return RUN_RUNTIME_ERROR


def _formal_reasoning_repair_audit_log_summary(audit_record: Mapping[str, Any]) -> dict[str, object]:
    """Keep repair diagnostics visible without writing generated reasoning to logs."""

    initial_errors = audit_record.get("initial_validation_errors")
    repair_errors = audit_record.get("repair_validation_errors")
    constraints = audit_record.get("constraints")
    return {
        "repair_attempted": bool(audit_record.get("repair_attempted")),
        "repair_stage": str(audit_record.get("repair_stage") or ""),
        "repair_status": str(audit_record.get("repair_status") or "FAILED"),
        "initial_validation_error_count": len(initial_errors) if isinstance(initial_errors, list) else 0,
        "repair_validation_error_count": len(repair_errors) if isinstance(repair_errors, list) else 0,
        "repair_constraint_count": len(constraints) if isinstance(constraints, list) else 0,
        "repaired_candidate_returned": isinstance(audit_record.get("repaired_candidate"), Mapping),
    }


def _run_stage(
    stage: str,
    callback: Callable[[], Any],
    *,
    logger: ExperimentDesignRunLogger | None = None,
    log_fields: Mapping[str, object] | None = None,
) -> Any:
    try:
        if logger is None:
            return callback()
        with logger.stage(stage, **dict(log_fields or {})):
            return callback()
    except ExperimentDesignRunError:
        raise
    except Exception as exc:
        audit_record = exc.audit_record if isinstance(exc, FormalReasoningPlanContractError) else None
        if logger is not None and audit_record is not None:
            logger.event(
                stage,
                "formal_reasoning_contract_repair_audit",
                level="ERROR",
                status=str(audit_record.get("repair_status") or "FAILED"),
                **_formal_reasoning_repair_audit_log_summary(audit_record),
            )
        raise ExperimentDesignRunError(
            stage,
            f"{type(exc).__name__}: {exc}",
            exit_code=_stage_exit_code(stage, exc),
            audit_record=audit_record,
        ) from exc


def _build_intake_record(idea_path: Path, research_brief: Mapping[str, Any]) -> dict[str, Any]:
    source = _mapping(research_brief.get("source"))
    selected_direction = _mapping(research_brief.get("selected_direction"))
    return {
        "status": "LOADED",
        "canonical_input_path": str(idea_path),
        "run_directory": str(idea_path.parent),
        "idea_result_schema": source.get("idea_result_schema", ""),
        "selected_direction_id": source.get("direction_id") or selected_direction.get("id", ""),
        "audit_source_paths": _mapping(source.get("upstream_source_paths")),
        "missing_audit_sources": list(source.get("missing_audit_sources") or []),
    }


def run_experiment_design(
    idea_result_path: str | Path,
    *,
    discipline_ids: object,
    brief_id: str | None = None,
    selected_direction: str = "",
    user_constraints: Mapping[str, Any] | None = None,
    config: object | None = None,
    config_path: str | Path | None = None,
    llm_model: str | None = None,
    llm_call: Callable[..., object] | None = None,
    composer_llm_call: Callable[..., object] | None = None,
    card_llm_call: Callable[[str], object] | None = None,
    survey_evidence_adapter: SurveyEvidenceAdapter | None = None,
    survey_artifacts: Mapping[str, Any] | Sequence[Mapping[str, Any]] | None = None,
    orchestrator: ExperimentDesignOrchestrator | None = None,
    logger: ExperimentDesignRunLogger | None = None,
    max_results_per_query: int | None = None,
    max_fulltext_papers: int | None = None,
) -> dict[str, Any]:
    """Run intake, preparation, evidence adaptation, composition, and validation once.

    The preparation plan is passed directly to the evidence adapter.  This is
    deliberate: ``ExperimentDesignOrchestrator.collect_survey_evidence`` is a
    convenience method that calls ``prepare`` internally and is therefore not
    used here.
    """

    runtime_config = _load_config(config, config_path)
    try:
        idea_path = _resolve_idea_path(idea_result_path)
    except (OSError, RuntimeError, ValueError) as exc:
        raise ExperimentDesignRunError(
            "intake",
            f"cannot resolve Idea artifact path: {exc}",
            exit_code=RUN_INPUT_ERROR,
        ) from exc
    if not idea_path.exists() or not idea_path.is_file():
        raise ExperimentDesignRunError(
            "intake",
            f"canonical Idea artifact not found: {idea_path}",
            exit_code=RUN_INPUT_ERROR,
        )
    if logger is not None:
        logger.event(
            "run",
            "started",
            status="RUNNING",
            canonical_input_path=str(idea_path),
            execution_mode="DESIGN_ONLY",
        )

    if orchestrator is None:
        orchestrator_kwargs: dict[str, Any] = {
            "config": runtime_config,
            "llm_model": llm_model,
            "llm_call": llm_call,
            "composer_llm_call": composer_llm_call,
        }
        if runtime_config is not None:
            orchestrator_kwargs["allow_digital_execution"] = _config_bool(
                runtime_config,
                ("experiment_design", "execution", "allow_digital_execution"),
                False,
            )
        orchestrator = ExperimentDesignOrchestrator(**orchestrator_kwargs)

    def load_research_brief() -> Mapping[str, Any]:
        result = orchestrator.idea_adapter.adapt_path(
            str(idea_path),
            discipline_ids=discipline_ids,
            brief_id=brief_id,
            selected_direction=selected_direction,
        )
        if not isinstance(result, Mapping):
            raise ExperimentDesignRunError(
                "intake",
                "IdeaResultAdapter did not return a ResearchBrief object",
                exit_code=RUN_IDEA_ERROR,
            )
        return result

    research_brief = _run_stage(
        "intake",
        load_research_brief,
        logger=logger,
        log_fields={"canonical_input_path": str(idea_path)},
    )
    research_brief = dict(research_brief)
    intake = _build_intake_record(idea_path, research_brief)

    def prepare_design() -> Mapping[str, Any]:
        result = orchestrator.prepare(
            research_brief,
            user_constraints=user_constraints,
            logger=logger,
        )
        if not isinstance(result, Mapping):
            raise ExperimentDesignRunError(
                "prepare",
                "ExperimentDesignOrchestrator.prepare did not return a preparation object",
            )
        result = dict(result)
        scoped = _mapping(result.get("scope_gate"))
        if scoped.get("status") != "IN_SCOPE":
            raise ValueError(
                f"design scope is not available: {scoped.get('status', 'UNKNOWN')}"
            )
        planned = _mapping(result.get("evidence_retrieval_plan"))
        if planned.get("planning_status") != "READY_FOR_RETRIEVAL":
            raise ExperimentDesignRunError(
                "prepare",
                "evidence retrieval planning did not reach READY_FOR_RETRIEVAL",
                exit_code=RUN_LLM_ERROR,
            )
        return result

    preparation = _run_stage(
        "prepare",
        prepare_design,
        logger=logger,
        log_fields={"brief_id": research_brief.get("brief_id", "")},
    )
    preparation = dict(preparation)
    evidence_plan = _mapping(preparation.get("evidence_retrieval_plan"))

    if survey_evidence_adapter is None:
        resolved_card_llm = card_llm_call or orchestrator._required_reasoning_llm()
        survey_evidence_adapter = SurveyEvidenceAdapter.from_config(
            card_llm_call=resolved_card_llm,
            config=runtime_config,
        )
    def collect_evidence() -> Mapping[str, Any]:
        result = survey_evidence_adapter.collect_and_extract(
            brief_id=str(research_brief.get("brief_id") or ""),
            evidence_plan=evidence_plan,
            survey_artifacts=survey_artifacts,
            max_results_per_query=max_results_per_query
            if max_results_per_query is not None
            else _config_int(runtime_config, ("experiment_design", "retrieval", "max_results_per_query"), 10),
            max_fulltext_papers=max_fulltext_papers
            if max_fulltext_papers is not None
            else _config_int(runtime_config, ("experiment_design", "retrieval", "max_fulltext_papers"), 15),
            logger=logger,
            cache_run_id=str(preparation.get("cache_run_id") or ""),
        )
        if not isinstance(result, Mapping):
            raise ExperimentDesignRunError(
                "evidence",
                "survey evidence adapter did not return an object",
            )
        result = dict(result)
        if not isinstance(result.get("evidence_bundle"), Mapping):
            raise ExperimentDesignRunError(
                "evidence",
                "survey evidence adapter did not return an EvidenceBundle",
                exit_code=RUN_VALIDATION_ERROR,
            )
        return result

    evidence = _run_stage(
        "evidence",
        collect_evidence,
        logger=logger,
        log_fields={
            "brief_id": research_brief.get("brief_id", ""),
            "query_count": len(evidence_plan.get("queries") or []),
        },
    )
    evidence = dict(evidence)
    evidence_bundle = evidence.get("evidence_bundle")

    def compose_design() -> Mapping[str, Any]:
        result = orchestrator.compose_design(
            research_brief,
            user_constraints=user_constraints,
            evidence_bundle=dict(evidence_bundle),
            composer_llm_call=composer_llm_call,
            reasoning_llm_call=llm_call,
            logger=logger,
        )
        if not isinstance(result, Mapping):
            raise ExperimentDesignRunError(
                "compose",
                "StudyTypeTemplateComposer did not return an object",
            )
        return result

    design = _run_stage(
        "compose",
        compose_design,
        logger=logger,
        log_fields={"brief_id": research_brief.get("brief_id", "")},
    )
    design = dict(design)

    def validate_design() -> list[str]:
        errors = validate_experiment_design(design)
        if errors:
            raise ExperimentDesignRunError(
                "validation",
                "; ".join(str(error) for error in errors),
                exit_code=RUN_VALIDATION_ERROR,
            )
        return errors

    _run_stage(
        "validation",
        validate_design,
        logger=logger,
        log_fields={"design_id": design.get("design_id", "")},
    )
    validation = {
        "status": "VALID",
        "schema_version": design.get("schema_version", ""),
        "errors": [],
        "observed_results_count": len(design.get("observed_results") or []),
    }
    cache_manifest = _mapping(evidence.get("cache_manifest")) or _mapping(
        preparation.get("cache_manifest")
    )
    cache_manifest_path = ""
    cache = getattr(survey_evidence_adapter, "cache", None)
    manifest_path = getattr(cache, "run_manifest_path", None)
    if callable(manifest_path):
        cache_manifest_path = str(
            manifest_path(str(preparation.get("cache_run_id") or "")) or ""
        )

    result = {
        "schema_version": RUN_SCHEMA_VERSION,
        "status": "COMPLETED",
        "intake": intake,
        "preparation": preparation,
        "survey_evidence": evidence,
        "composition": {
            "status": "COMPOSED",
            "design_id": design.get("design_id", ""),
        },
        "cache_manifest": cache_manifest,
        "cache_manifest_path": cache_manifest_path,
        "validation": validation,
        "experiment_design": design,
    }
    if logger is not None:
        logger.event(
            "run",
            "completed",
            status="COMPLETED",
            execution_mode=_mapping(design.get("execution_policy")).get("mode", "DESIGN_ONLY"),
            observed_results_count=validation["observed_results_count"],
        )
    return result


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the complete design-only ExperimentDesign workflow; never execute experiments."
    )
    parser.add_argument("--config", help="Path to config YAML")
    parser.add_argument("--idea-json", required=True, help="idea_result.json or an Idea Agent run directory")
    parser.add_argument(
        "--discipline-id",
        action="append",
        required=True,
        metavar="ID",
        help="Scientific discipline ID; repeat for multiple fields",
    )
    parser.add_argument("--selected-direction", default="", help="Direction ID, mode, or title")
    parser.add_argument("--brief-id", help="ResearchBrief ID")
    parser.add_argument("--model", help="Override the configured ExperimentDesign model")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the module-level entry point and print the validated run envelope."""

    args = _build_parser().parse_args(argv)
    try:
        result = run_experiment_design(
            args.idea_json,
            discipline_ids=args.discipline_id,
            brief_id=args.brief_id,
            selected_direction=args.selected_direction,
            config_path=args.config,
            llm_model=args.model,
        )
    except ExperimentDesignRunError as exc:
        print(f"experiment_design failed at {exc.stage}: {exc}", file=sys.stderr)
        return exc.exit_code
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    return RUN_SUCCESS


if __name__ == "__main__":
    raise SystemExit(main())
