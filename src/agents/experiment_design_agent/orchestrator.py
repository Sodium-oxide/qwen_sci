"""Core design-state orchestration without retrieval or experiment execution."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
from pathlib import Path
import inspect
from typing import Any

from .cache import ExperimentDesignCache
from .completeness import CompletenessValidator
from .contracts import validate_experiment_design, validate_research_brief
from .evidence_planner import EvidenceRetrievalPlanner
from .idea_adapter import IdeaResultAdapter
from .counterexample_analyzer import (
    CounterexampleAnalyzer,
    not_applicable_counterexample_analysis,
    unavailable_counterexample_analysis,
)
from .formal_reasoning_planner import (
    FormalReasoningPlanner,
    not_applicable_formal_reasoning_plan,
    unavailable_formal_reasoning_plan,
)
from .llm_json import build_default_json_llm_call, validation_summary
from .reasoning_context import build_reasoning_context_from_brief
from .reasoning_validation import validate_reasoning_artifacts
from .scope_gate import ScopeAndSafetyGate
from .study_type_composer import StudyTypeTemplateComposer
from .survey_evidence import SurveyEvidenceAdapter
from .template_router import TemplateRouter
from .variable_claim_extractor import VariableClaimExtractor
from .run_logging import ExperimentDesignRunLogger


DESIGN_PREPARATION_SCHEMA_VERSION = "experiment_design_preparation_v1"
DESIGN_RUN_SCHEMA_VERSION = "experiment_design_run_v1"


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _setting(value: object, key: str, default: object = None) -> object:
    if isinstance(value, Mapping):
        return value.get(key, default)
    return getattr(value, key, default)


def _experiment_design_cache_config(config: object | None) -> object:
    if config is None:
        return {"enabled": False}
    experiment_design = _setting(config, "experiment_design", config)
    retrieval = _setting(experiment_design, "retrieval", {})
    return _setting(retrieval, "cache", {"enabled": False})


def _llm_cache_context(config: object | None, model: str | None) -> dict[str, str]:
    experiment_design = _setting(config, "experiment_design", config)
    return {
        "provider": str(_setting(experiment_design, "provider", "") or ""),
        "model": str(model or _setting(experiment_design, "model", "") or ""),
    }


def _sequence_count(value: object) -> int:
    return len(value) if isinstance(value, Sequence) and not isinstance(value, (str, bytes)) else 0


def _design_validation_profile(design: Mapping[str, Any]) -> dict[str, object]:
    """Provide final-validation diagnostics without serializing the design itself."""

    evidence = _mapping(design.get("evidence_bundle"))
    coverage = _mapping(evidence.get("coverage"))
    template = _mapping(design.get("template_composition"))
    policy = _mapping(design.get("execution_policy"))
    review = _mapping(design.get("risk_and_human_review"))
    statuses = _mapping(design.get("field_statuses"))
    reasoning_context = _mapping(_mapping(design.get("research_brief")).get("reasoning_context"))
    variable_claim_model = _mapping(design.get("variable_claim_model"))
    formal_reasoning_plan = _mapping(design.get("formal_reasoning_plan"))
    counterexample_analysis = _mapping(design.get("counterexample_analysis"))
    return {
        "schema_version": str(design.get("schema_version") or ""),
        "design_id": str(design.get("design_id") or ""),
        "template_id": str(template.get("template_id") or ""),
        "template_submode": str(template.get("submode") or ""),
        "execution_mode": str(policy.get("mode") or ""),
        "observed_results_count": _sequence_count(design.get("observed_results")),
        "outcome_branch_count": _sequence_count(design.get("outcome_branches")),
        "open_design_question_count": _sequence_count(design.get("open_design_questions")),
        "field_status_count": len(statuses),
        "needs_human_input_field_count": sum(value == "needs_human_input" for value in statuses.values()),
        "evidence_card_count": _sequence_count(evidence.get("evidence_cards")),
        "evidence_covered_slot_count": _sequence_count(coverage.get("covered_slots")),
        "reasoning_context_unknown_item_count": _sequence_count(reasoning_context.get("gap_records")),
        "variable_claim_unknown_item_count": _sequence_count(variable_claim_model.get("unknown_items")),
        "formal_reasoning_unknown_item_count": _sequence_count(formal_reasoning_plan.get("unknown_items")),
        "counterexample_unknown_item_count": _sequence_count(counterexample_analysis.get("unknown_items")),
        "risk_review_required": bool(review.get("human_review_required")),
    }


def _blocked_evidence_plan(brief_id: object) -> dict[str, Any]:
    return {
        "schema_version": "experiment_design_evidence_retrieval_plan_v2",
        "planning_mode": "QUERY_PLANNING_ONLY",
        "planning_status": "NOT_PLANNED_BLOCKED_SCOPE",
        "research_brief_id": str(brief_id or ""),
        "template_id": "",
        "queries": [],
        "retrieved_evidence": [],
        "observed_results": [],
        "llm_used": False,
        "warnings": ["Scope must be in range before evidence queries are planned."],
    }


def _degradation_reason(stage: str) -> str:
    return (
        f"The {stage} LLM batch was discarded after an unavailable or invalid response. "
        "No generated claim, formalization, counterexample, or protocol detail from that batch is retained; "
        "qualified human review is required."
    )


def _degraded_variable_claim_model(*, reason: str) -> dict[str, Any]:
    return {
        "schema_version": "variable_claim_model_v1",
        "status": "complete_or_requires_input",
        "claims": [],
        "variables": [],
        "unknown_items": [
            {
                "field_path": "variable_claim_model",
                "reason": reason,
                "status": "needs_human_input",
            }
        ],
    }


def _append_unique_text(values: object, value: str) -> list[str]:
    existing = [
        str(item).strip()
        for item in values
        if str(item).strip()
    ] if isinstance(values, Sequence) and not isinstance(values, (str, bytes)) else []
    if value not in existing:
        existing.append(value)
    return existing


def _record_degradation(
    logger: ExperimentDesignRunLogger | None,
    *,
    stage: str,
    brief_id: str,
    error: BaseException | None = None,
    disposition: str = "discarded_invalid_llm_batch",
) -> dict[str, str]:
    record = {
        "stage": stage,
        "disposition": disposition,
        "error_code": type(error).__name__ if error is not None else "UPSTREAM_DEGRADED",
    }
    if logger is not None:
        logger.event(
            stage,
            "degraded",
            level="WARNING",
            status="DEGRADED",
            brief_id=brief_id,
            requires_human_review=True,
            disposition=disposition,
            error_code=record["error_code"],
        )
    return record


def _mark_design_degraded(
    design: Mapping[str, Any],
    degradations: Sequence[Mapping[str, str]],
) -> dict[str, Any]:
    """Expose discarded batches through existing ExperimentDesign review fields."""

    marked = deepcopy(dict(design))
    if not degradations:
        return marked
    review = _mapping(marked.get("risk_and_human_review"))
    review["human_review_required"] = True
    review["execution_prohibited"] = True
    review["review_triggers"] = _append_unique_text(
        review.get("review_triggers"),
        "LLM_OR_WORKFLOW_DEGRADATION_REVIEW",
    )
    review["approval_dependencies"] = _append_unique_text(
        review.get("approval_dependencies"),
        "Qualified human review must replace every discarded LLM or workflow batch before execution.",
    )
    marked["risk_and_human_review"] = review

    field_statuses = _mapping(marked.get("field_statuses"))
    questions = marked.get("open_design_questions")
    open_questions = list(questions) if isinstance(questions, list) else []
    warnings = _mapping(marked.get("validation_report")).get("warnings")
    validation_warnings = list(warnings) if isinstance(warnings, list) else []
    for degradation in degradations:
        stage = str(degradation.get("stage") or "unknown_stage")
        field_statuses[f"degraded_stages.{stage}"] = "needs_human_input"
        message = (
            f"Replace the discarded {stage} batch with qualified human review before treating this design as complete."
        )
        if message not in open_questions:
            open_questions.append(message)
        warning = (
            f"{stage} was degraded after its LLM or contract-validation batch was discarded; no discarded output is retained."
        )
        if warning not in validation_warnings:
            validation_warnings.append(warning)
    marked["field_statuses"] = field_statuses
    marked["open_design_questions"] = open_questions
    marked["validation_report"] = {
        "status": "BLOCKED_BY_RISK_REVIEW",
        "errors": [],
        "warnings": validation_warnings,
    }
    return marked


class ExperimentDesignOrchestrator:
    """Prepare a scientific design package while retaining all unknowns and review gates."""

    def __init__(
        self,
        *,
        allow_digital_execution: bool | None = None,
        llm_call: Callable[..., object] | None = None,
        composer_llm_call: Callable[..., object] | None = None,
        config: Any = None,
        llm_model: str | None = None,
    ) -> None:
        self.config = config
        if allow_digital_execution is None:
            try:
                from src.config import get_experiment_design_config

                allow_digital_execution = bool(
                    get_experiment_design_config().execution.allow_digital_execution
                )
            except Exception:
                allow_digital_execution = False
        self.allow_digital_execution = bool(allow_digital_execution)
        self.llm_call = llm_call
        self.llm_model = llm_model
        self._default_llm_call: Callable[..., object] | None = None
        self.cache = ExperimentDesignCache(_experiment_design_cache_config(config))
        self.idea_adapter = IdeaResultAdapter()
        self.scope_gate = ScopeAndSafetyGate()
        self.template_router = TemplateRouter()
        self.evidence_planner = EvidenceRetrievalPlanner(cache=self.cache)
        self.completeness_validator = CompletenessValidator()
        self.variable_claim_extractor = VariableClaimExtractor()
        self.formal_reasoning_planner = FormalReasoningPlanner()
        self.counterexample_analyzer = CounterexampleAnalyzer()
        self.study_type_composer = StudyTypeTemplateComposer(
            template_router=self.template_router,
            scope_gate=self.scope_gate,
        )
        self.composer_llm_call = composer_llm_call

    def _required_reasoning_llm(self, override: Callable[..., object] | None = None) -> Callable[..., object]:
        callback = override or self.llm_call
        if callback is not None:
            return callback
        if self._default_llm_call is None:
            self._default_llm_call = build_default_json_llm_call(
                config=self.config,
                model=self.llm_model,
            )
        return self._default_llm_call

    def _required_composer_llm(self, override: Callable[..., object] | None = None) -> Callable[..., object]:
        return override or self.composer_llm_call or self.llm_call or self._required_reasoning_llm()

    def prepare(
        self,
        research_brief: Mapping[str, Any],
        *,
        user_constraints: Mapping[str, Any] | None = None,
        candidate_design: Mapping[str, Any] | None = None,
        evidence_bundle: Mapping[str, Any] | None = None,
        logger: ExperimentDesignRunLogger | None = None,
    ) -> dict[str, Any]:
        brief = _mapping(research_brief)
        brief_errors = validate_research_brief(brief)
        scope_gate = self.scope_gate.evaluate(
            brief,
            user_constraints=user_constraints,
            allow_digital_execution=self.allow_digital_execution,
        )
        template_routing = self.template_router.route(brief, user_constraints=user_constraints)
        cache_run_id = self.cache.begin_run(brief.get("brief_id"))
        planning_degraded = False
        if scope_gate["status"] == "IN_SCOPE" and not brief_errors:
            try:
                planner_kwargs: dict[str, Any] = {"llm_call": self._required_reasoning_llm()}
                planner_parameters = inspect.signature(self.evidence_planner.plan).parameters
                if "logger" in planner_parameters:
                    planner_kwargs["logger"] = logger
                if "cache_run_id" in planner_parameters:
                    planner_kwargs["cache_run_id"] = cache_run_id
                if "cache_context" in planner_parameters:
                    planner_kwargs["cache_context"] = _llm_cache_context(self.config, self.llm_model)
                evidence_plan = self.evidence_planner.plan(brief, template_routing, **planner_kwargs)
            except Exception as exc:
                planning_degraded = True
                _record_degradation(
                    logger,
                    stage="evidence_retrieval_planner",
                    brief_id=str(brief.get("brief_id") or ""),
                    error=exc,
                )
                evidence_plan = self.evidence_planner.degraded_plan(
                    brief,
                    template_routing,
                    reason=_degradation_reason("evidence_retrieval_planner"),
                )
        else:
            evidence_plan = _blocked_evidence_plan(brief.get("brief_id"))
        planning_degraded = planning_degraded or (
            scope_gate["status"] == "IN_SCOPE"
            and not brief_errors
            and not bool(evidence_plan.get("llm_used"))
        )
        completeness = self.completeness_validator.assess(
            brief,
            template_routing,
            candidate_design=candidate_design,
            evidence_bundle=evidence_bundle,
        )
        unknown_items = list(completeness["unknown_items"])
        if planning_degraded:
            unknown_items.append(
                {
                    "field_path": "evidence_retrieval_plan.queries",
                    "status": "needs_human_input",
                    "reason": _degradation_reason("evidence_retrieval_planner"),
                    "blocks_final_design": True,
                }
            )
        human_review = scope_gate["risk_and_human_review"]
        if human_review["human_review_required"]:
            unknown_items.append(
                {
                    "field_path": "risk_and_human_review.approval_dependencies",
                    "status": "needs_human_input",
                    "reason": "Required review and approval dependencies must be confirmed by qualified humans.",
                    "blocks_final_design": True,
                }
            )
        if scope_gate["status"] != "IN_SCOPE" or brief_errors:
            validation_status = "BLOCKED_BY_SCOPE"
        elif human_review["human_review_required"]:
            validation_status = "BLOCKED_BY_RISK_REVIEW"
        else:
            validation_status = completeness["status"]
        return {
            "schema_version": DESIGN_PREPARATION_SCHEMA_VERSION,
            "stage": "DESIGN_PREPARATION",
            "research_brief": brief,
            "scope_gate": scope_gate,
            "template_routing": template_routing,
            "evidence_retrieval_plan": evidence_plan,
            "cache_run_id": cache_run_id,
            "cache_manifest": self.cache.run_manifest(cache_run_id),
            "completeness": completeness,
            "unknown_items": unknown_items,
            "risk_and_human_review": human_review,
            "observed_results": [],
            "validation_report": {
                "status": validation_status,
                "errors": brief_errors + list(completeness["errors"]),
                "warnings": list(evidence_plan["warnings"]),
            },
        }

    def prepare_from_idea_result(
        self,
        idea_result: Mapping[str, Any],
        *,
        discipline_ids: object,
        brief_id: str,
        selected_direction: str = "",
        user_constraints: Mapping[str, Any] | None = None,
        audit_sources: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        brief = self.idea_adapter.adapt(
            idea_result,
            discipline_ids=discipline_ids,
            brief_id=brief_id,
            selected_direction=selected_direction,
            audit_sources=audit_sources,
        )
        return self.prepare(brief, user_constraints=user_constraints)

    def prepare_from_idea_path(
        self,
        idea_result_path: str,
        *,
        discipline_ids: object,
        brief_id: str | None = None,
        selected_direction: str = "",
        user_constraints: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Prepare from one run directory while retaining audit provenance."""

        brief = self.idea_adapter.adapt_path(
            idea_result_path,
            discipline_ids=discipline_ids,
            brief_id=brief_id,
            selected_direction=selected_direction,
        )
        return self.prepare(brief, user_constraints=user_constraints)

    def compose_design(
        self,
        research_brief: Mapping[str, Any],
        *,
        user_constraints: Mapping[str, Any] | None = None,
        evidence_bundle: Mapping[str, Any] | None = None,
        composer_llm_call: Callable[..., object] | None = None,
        reasoning_llm_call: Callable[..., object] | None = None,
        logger: ExperimentDesignRunLogger | None = None,
    ) -> dict[str, Any]:
        """Create the final design-state artifact without invoking any executor."""

        brief = _mapping(research_brief)
        scope_gate = self.scope_gate.evaluate(
            brief,
            user_constraints=user_constraints,
            allow_digital_execution=self.allow_digital_execution,
        )
        if scope_gate["status"] != "IN_SCOPE" or validate_research_brief(brief):
            raise ValueError("ExperimentDesign composition is unavailable until the ResearchBrief is valid and in scope.")
        routing = self.template_router.route(brief, user_constraints=user_constraints)
        reasoning_context = build_reasoning_context_from_brief(brief)
        brief_id = str(brief.get("brief_id") or "")
        degradations: list[dict[str, str]] = []
        if logger is not None:
            logger.event(
                "reasoning_context",
                "completed",
                status="COMPLETED",
                brief_id=brief_id,
                assumption_count=_sequence_count(reasoning_context.get("assumptions")),
                falsifier_count=_sequence_count(reasoning_context.get("falsifiers")),
                boundary_condition_count=_sequence_count(reasoning_context.get("boundary_conditions")),
                alternative_explanation_count=_sequence_count(reasoning_context.get("alternative_explanations")),
            )

        if logger is not None:
            logger.event(
                "variable_claim_extraction",
                "started",
                status="RUNNING",
                brief_id=brief_id,
            )
        try:
            variable_claim_model = self.variable_claim_extractor.extract(
                brief,
                reasoning_context=reasoning_context,
                llm_call=self._required_reasoning_llm(reasoning_llm_call),
            )
        except Exception as exc:
            degradations.append(
                _record_degradation(
                    logger,
                    stage="variable_claim_extraction",
                    brief_id=brief_id,
                    error=exc,
                )
            )
            variable_claim_model = _degraded_variable_claim_model(
                reason=_degradation_reason("variable_claim_extraction"),
            )
        if logger is not None:
            logger.event(
                "variable_claim_extraction",
                "completed",
                status="DEGRADED" if degradations else "COMPLETED",
                brief_id=brief_id,
                variable_count=_sequence_count(variable_claim_model.get("variables")),
                claim_count=_sequence_count(variable_claim_model.get("claims")),
                unknown_item_count=_sequence_count(variable_claim_model.get("unknown_items")),
            )

        formal_applicable = (
            routing.get("primary_template") == "mathematics_theory"
            and routing.get("submode") != "physical_validation"
        )
        variable_claim_degraded = any(
            record["stage"] == "variable_claim_extraction" for record in degradations
        )
        formal_degraded = False
        if formal_applicable:
            if logger is not None:
                logger.event(
                    "formal_reasoning_planner",
                    "started",
                    status="RUNNING",
                    brief_id=brief_id,
                )
            if variable_claim_degraded:
                formal_degraded = True
                degradations.append(
                    _record_degradation(
                        logger,
                        stage="formal_reasoning_planner",
                        brief_id=brief_id,
                        disposition="skipped_after_upstream_degradation",
                    )
                )
                formal_reasoning_plan = unavailable_formal_reasoning_plan(
                    reason=(
                        "Formal reasoning was not run because the variable and claim extraction batch was discarded; "
                        "a qualified human must supply the formalization."
                    ),
                )
            else:
                try:
                    formal_reasoning_plan = self.formal_reasoning_planner.plan(
                        brief,
                        reasoning_context,
                        variable_claim_model,
                        llm_call=self._required_reasoning_llm(reasoning_llm_call),
                        logger=logger,
                        brief_id=brief_id,
                    )
                except Exception as exc:
                    formal_degraded = True
                    degradations.append(
                        _record_degradation(
                            logger,
                            stage="formal_reasoning_planner",
                            brief_id=brief_id,
                            error=exc,
                        )
                    )
                    formal_reasoning_plan = unavailable_formal_reasoning_plan(
                        reason=_degradation_reason("formal_reasoning_planner"),
                    )
            if logger is not None:
                logger.event(
                "formal_reasoning_planner",
                "completed",
                status="DEGRADED" if formal_degraded else "COMPLETED",
                    brief_id=brief_id,
                    assumption_count=_sequence_count(formal_reasoning_plan.get("assumptions")),
                    definition_count=_sequence_count(formal_reasoning_plan.get("definitions")),
                    proposition_count=_sequence_count(formal_reasoning_plan.get("propositions")),
                    proof_obligation_count=_sequence_count(formal_reasoning_plan.get("proof_obligations")),
                    forward_step_count=_sequence_count(
                        _mapping(formal_reasoning_plan.get("forward_derivation")).get("steps")
                    ),
                )

            if logger is not None:
                logger.event(
                    "counterexample_analyzer",
                    "started",
                    status="RUNNING",
                    brief_id=brief_id,
                )
            counterexample_degraded = False
            if formal_degraded:
                counterexample_degraded = True
                degradations.append(
                    _record_degradation(
                        logger,
                        stage="counterexample_analyzer",
                        brief_id=brief_id,
                        disposition="skipped_after_upstream_degradation",
                    )
                )
                counterexample_analysis = unavailable_counterexample_analysis(
                    reason=(
                        "Counterexample analysis was not run because its formal reasoning input was discarded; "
                        "a qualified human must define the target claim and search domain."
                    ),
                )
            else:
                try:
                    counterexample_analysis = self.counterexample_analyzer.analyze(
                        brief,
                        reasoning_context,
                        variable_claim_model,
                        formal_reasoning_plan,
                        llm_call=self._required_reasoning_llm(reasoning_llm_call),
                        logger=logger,
                        brief_id=brief_id,
                    )
                except Exception as exc:
                    counterexample_degraded = True
                    degradations.append(
                        _record_degradation(
                            logger,
                            stage="counterexample_analyzer",
                            brief_id=brief_id,
                            error=exc,
                        )
                    )
                    counterexample_analysis = unavailable_counterexample_analysis(
                        reason=_degradation_reason("counterexample_analyzer"),
                    )
            if logger is not None:
                logger.event(
                "counterexample_analyzer",
                "completed",
                status="DEGRADED" if counterexample_degraded else "COMPLETED",
                    brief_id=brief_id,
                    candidate_count=_sequence_count(counterexample_analysis.get("candidate_counterexamples")),
                    unknown_item_count=_sequence_count(counterexample_analysis.get("unknown_items")),
                    exhaustiveness_is_exhaustive=bool(
                        _mapping(counterexample_analysis.get("exhaustiveness")).get("is_exhaustive")
                    ),
                )
        else:
            formal_reasoning_plan = not_applicable_formal_reasoning_plan()
            counterexample_analysis = not_applicable_counterexample_analysis()
            if logger is not None:
                logger.event(
                    "formal_reasoning_planner",
                    "completed",
                    status="NOT_APPLICABLE",
                    brief_id=brief_id,
                    template_id=str(routing.get("primary_template") or ""),
                )
                logger.event(
                    "counterexample_analyzer",
                    "completed",
                    status="NOT_APPLICABLE",
                    brief_id=brief_id,
                    template_id=str(routing.get("primary_template") or ""),
                )

        if logger is not None:
            logger.event(
                "reasoning_validation",
                "started",
                status="RUNNING",
                brief_id=brief_id,
            )

        def discarded_reasoning_artifacts(reason: str) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
            degraded_variable_claim_model = _degraded_variable_claim_model(reason=reason)
            if formal_applicable:
                degraded_formal_reasoning_plan = unavailable_formal_reasoning_plan(reason=reason)
                degraded_counterexample_analysis = unavailable_counterexample_analysis(reason=reason)
            else:
                degraded_formal_reasoning_plan = not_applicable_formal_reasoning_plan()
                degraded_counterexample_analysis = not_applicable_counterexample_analysis()
            return (
                degraded_variable_claim_model,
                degraded_formal_reasoning_plan,
                degraded_counterexample_analysis,
            )

        try:
            reasoning_errors = validate_reasoning_artifacts(
                variable_claim_model=variable_claim_model,
                formal_reasoning_plan=formal_reasoning_plan,
                counterexample_analysis=counterexample_analysis,
                template_composition=routing,
            )
        except Exception as exc:
            degradations.append(
                _record_degradation(
                    logger,
                    stage="reasoning_validation",
                    brief_id=brief_id,
                    error=exc,
                )
            )
            variable_claim_model, formal_reasoning_plan, counterexample_analysis = discarded_reasoning_artifacts(
                _degradation_reason("reasoning_validation"),
            )
            reasoning_errors = validate_reasoning_artifacts(
                variable_claim_model=variable_claim_model,
                formal_reasoning_plan=formal_reasoning_plan,
                counterexample_analysis=counterexample_analysis,
                template_composition=routing,
            )
        if reasoning_errors:
            if logger is not None:
                logger.event(
                    "reasoning_validation",
                    "discarded_invalid_batch",
                    level="WARNING",
                    status="DEGRADED",
                    brief_id=brief_id,
                    error_count=len(reasoning_errors),
                    errors=reasoning_errors,
                )
            degradations.append(
                _record_degradation(
                    logger,
                    stage="reasoning_validation",
                    brief_id=brief_id,
                )
            )
            variable_claim_model, formal_reasoning_plan, counterexample_analysis = discarded_reasoning_artifacts(
                _degradation_reason("reasoning_validation"),
            )
            reasoning_errors = validate_reasoning_artifacts(
                variable_claim_model=variable_claim_model,
                formal_reasoning_plan=formal_reasoning_plan,
                counterexample_analysis=counterexample_analysis,
                template_composition=routing,
            )
            if reasoning_errors:
                raise RuntimeError(
                    "experiment_design: deterministic reasoning degradation failed validation: "
                    + "; ".join(reasoning_errors)
                )
        if logger is not None:
            logger.event(
                "reasoning_validation",
                "completed",
                status="DEGRADED" if degradations else "COMPLETED",
                brief_id=brief_id,
                error_count=0,
            )

        if logger is not None:
            logger.event(
                "template_composer",
                "started",
                status="RUNNING",
                brief_id=brief_id,
                template_id=str(routing.get("primary_template") or ""),
            )
        try:
            design = self.study_type_composer.compose(
                brief,
                template_routing=routing,
                evidence_bundle=evidence_bundle,
                user_constraints=user_constraints,
                llm_call=self._required_composer_llm(composer_llm_call),
                reasoning_context=reasoning_context,
                variable_claim_model=variable_claim_model,
                formal_reasoning_plan=formal_reasoning_plan,
                counterexample_analysis=counterexample_analysis,
                logger=logger,
                brief_id=brief_id,
            )
        except Exception as exc:
            degradations.append(
                _record_degradation(
                    logger,
                    stage="template_composer",
                    brief_id=brief_id,
                    error=exc,
                )
            )
            design = self.study_type_composer.compose_deterministically(
                brief,
                template_routing=routing,
                evidence_bundle=evidence_bundle,
                user_constraints=user_constraints,
                reasoning_context=reasoning_context,
                variable_claim_model=variable_claim_model,
                formal_reasoning_plan=formal_reasoning_plan,
                counterexample_analysis=counterexample_analysis,
            )
        if logger is not None:
            logger.event(
                "template_composer",
                "completed",
                status=(
                    "DEGRADED"
                    if any(record["stage"] == "template_composer" for record in degradations)
                    else "COMPLETED"
                ),
                brief_id=brief_id,
                template_id=str(routing.get("primary_template") or ""),
                design_id=str(design.get("design_id") or ""),
                llm_used=bool(_mapping(design.get("template_composition")).get("llm_used")),
            )
        design = _mark_design_degraded(design, degradations)
        if logger is not None:
            logger.event(
                "compose_final_validation",
                "started",
                status="RUNNING",
                brief_id=brief_id,
                design_id=str(design.get("design_id") or ""),
            )
            logger.event(
                "compose_final_validation",
                "input_profiled",
                status="PROFILED",
                brief_id=brief_id,
                **_design_validation_profile(design),
            )
        try:
            final_errors = validate_experiment_design(design)
        except Exception as exc:
            degradations.append(
                _record_degradation(
                    logger,
                    stage="compose_final_validation",
                    brief_id=brief_id,
                    error=exc,
                    disposition="discarded_after_validator_failure",
                )
            )
            final_errors = ["final_contract_validator_unavailable"]
        if final_errors:
            if logger is not None:
                logger.event(
                    "compose_final_validation",
                    "contract_validated",
                    level="WARNING",
                    status="DEGRADED",
                    brief_id=brief_id,
                    **_design_validation_profile(design),
                    **validation_summary(final_errors),
                )
                logger.event(
                    "compose_final_validation",
                    "discarded_invalid_candidate",
                    level="WARNING",
                    status="DEGRADED",
                    brief_id=brief_id,
                    design_id=str(design.get("design_id") or ""),
                    **validation_summary(final_errors),
                )
            if not any(record["stage"] == "compose_final_validation" for record in degradations):
                degradations.append(
                    _record_degradation(
                        logger,
                        stage="compose_final_validation",
                        brief_id=brief_id,
                    )
                )
            design = self.study_type_composer.compose_deterministically(
                brief,
                template_routing=routing,
                evidence_bundle=evidence_bundle,
                user_constraints=user_constraints,
                reasoning_context=reasoning_context,
                variable_claim_model=variable_claim_model,
                formal_reasoning_plan=formal_reasoning_plan,
                counterexample_analysis=counterexample_analysis,
            )
            design = _mark_design_degraded(design, degradations)
        if logger is not None:
            logger.event(
                "compose_final_validation",
                "contract_validated",
                status="VALID",
                brief_id=brief_id,
                **_design_validation_profile(design),
                **validation_summary([]),
            )
            logger.event(
                "compose_final_validation",
                "completed",
                status="DEGRADED" if degradations else "COMPLETED",
                brief_id=brief_id,
                design_id=str(design.get("design_id") or ""),
                error_count=0,
            )
        design["reasoning_validation_report"] = {
            "status": "STRUCTURALLY_VALID_UNVERIFIED_REASONING",
            "errors": [],
            "warnings": [
                "Forward derivation and counterexample candidates are proposals unless an independent verifier or qualified human confirms them.",
                "No experiment, simulation, symbolic execution, or exhaustive counterexample search was run.",
                *(
                    [
                        "One or more LLM or workflow batches were discarded and require qualified human replacement."
                    ]
                    if degradations
                    else []
                ),
            ],
        }
        return design

    def compose_design_from_idea_path(
        self,
        idea_result_path: str,
        *,
        discipline_ids: object,
        brief_id: str | None = None,
        selected_direction: str = "",
        user_constraints: Mapping[str, Any] | None = None,
        evidence_bundle: Mapping[str, Any] | None = None,
        composer_llm_call: Callable[..., object] | None = None,
        reasoning_llm_call: Callable[..., object] | None = None,
    ) -> dict[str, Any]:
        """Compose a final design from the canonical Idea run artifact."""

        brief = self.idea_adapter.adapt_path(
            idea_result_path,
            discipline_ids=discipline_ids,
            brief_id=brief_id,
            selected_direction=selected_direction,
        )
        return self.compose_design(
            brief,
            user_constraints=user_constraints,
            evidence_bundle=evidence_bundle,
            composer_llm_call=composer_llm_call,
            reasoning_llm_call=reasoning_llm_call,
        )

    def collect_survey_evidence(
        self,
        research_brief: Mapping[str, Any],
        *,
        survey_evidence_adapter: SurveyEvidenceAdapter | None = None,
        survey_artifacts: Mapping[str, Any] | Sequence[Mapping[str, Any]] | None = None,
        card_llm_call: Callable[[str], object] | None = None,
        max_results_per_query: int = 10,
        max_fulltext_papers: int = 15,
    ) -> dict[str, Any]:
        """Collect and extract traceable design evidence after scope and plan validation."""

        preparation = self.prepare(research_brief)
        plan = preparation["evidence_retrieval_plan"]
        if plan["planning_status"] != "READY_FOR_RETRIEVAL":
            preparation["survey_evidence"] = {
                "schema_version": "experiment_design_survey_evidence_adaptation_v1",
                "collection": {},
                "evidence_bundle": {},
                "warnings": ["Evidence collection was not started because the design scope is blocked."],
            }
            return preparation
        adapter = survey_evidence_adapter or SurveyEvidenceAdapter.from_config(
            card_llm_call=card_llm_call or self._required_reasoning_llm(),
        )
        evidence = adapter.collect_and_extract(
            brief_id=str(research_brief.get("brief_id") or ""),
            evidence_plan=plan,
            survey_artifacts=survey_artifacts,
            max_results_per_query=max_results_per_query,
            max_fulltext_papers=max_fulltext_papers,
            cache_run_id=str(preparation.get("cache_run_id") or ""),
        )
        preparation["survey_evidence"] = evidence
        preparation["evidence_bundle"] = evidence["evidence_bundle"]
        return preparation

    def run_from_preparation(
        self,
        preparation: Mapping[str, Any],
        *,
        user_constraints: Mapping[str, Any] | None = None,
        survey_evidence_adapter: SurveyEvidenceAdapter | None = None,
        survey_artifacts: Mapping[str, Any] | Sequence[Mapping[str, Any]] | None = None,
        card_llm_call: Callable[[str], object] | None = None,
        composer_llm_call: Callable[..., object] | None = None,
        reasoning_llm_call: Callable[..., object] | None = None,
        max_results_per_query: int = 10,
        max_fulltext_papers: int = 15,
        logger: ExperimentDesignRunLogger | None = None,
        _emit_run_events: bool = True,
    ) -> dict[str, Any]:
        """Complete a prepared design workflow without re-running preparation.

        ``preparation`` owns the already generated Evidence Retrieval Planner
        output.  This method passes that exact plan to the survey adapter and
        never calls ``prepare`` or ``collect_survey_evidence``.  The method is
        design-only: it never invokes an experiment, simulation, benchmark, or
        other execution path.
        """

        prepared = _mapping(preparation)
        brief = _mapping(prepared.get("research_brief"))
        scope_gate = _mapping(prepared.get("scope_gate"))
        evidence_plan_value = prepared.get("evidence_retrieval_plan")
        evidence_plan = evidence_plan_value if isinstance(evidence_plan_value, Mapping) else {}
        cache_run_id = str(prepared.get("cache_run_id") or "")
        brief_id = str(brief.get("brief_id") or "")
        if logger is not None and _emit_run_events:
            logger.event(
                "run",
                "started",
                status="RUNNING",
                brief_id=brief_id,
                execution_mode="DESIGN_ONLY",
            )

        try:
            if not brief:
                raise ValueError("ExperimentDesign run requires preparation.research_brief.")
            if scope_gate.get("status") != "IN_SCOPE":
                raise ValueError(
                    "ExperimentDesign run requires an in-scope preparation: "
                    f"{scope_gate.get('status', 'UNKNOWN')}"
                )
            if evidence_plan.get("planning_status") != "READY_FOR_RETRIEVAL":
                raise ValueError(
                    "ExperimentDesign run requires an evidence plan with "
                    "planning_status=READY_FOR_RETRIEVAL."
                )
            if survey_evidence_adapter is None:
                survey_evidence_adapter = SurveyEvidenceAdapter.from_config(
                    card_llm_call=card_llm_call or self._required_reasoning_llm(),
                    config=self.config,
                )
            if logger is None:
                evidence = survey_evidence_adapter.collect_and_extract(
                    brief_id=brief_id,
                    evidence_plan=evidence_plan,
                    survey_artifacts=survey_artifacts,
                    max_results_per_query=max(1, int(max_results_per_query)),
                    max_fulltext_papers=max(0, int(max_fulltext_papers)),
                    cache_run_id=cache_run_id,
                )
            else:
                with logger.stage(
                    "evidence",
                    brief_id=brief_id,
                    query_count=len(evidence_plan.get("queries") or []),
                ):
                    evidence = survey_evidence_adapter.collect_and_extract(
                        brief_id=brief_id,
                        evidence_plan=evidence_plan,
                        survey_artifacts=survey_artifacts,
                        max_results_per_query=max(1, int(max_results_per_query)),
                        max_fulltext_papers=max(0, int(max_fulltext_papers)),
                        logger=logger,
                        cache_run_id=cache_run_id,
                    )
            if not isinstance(evidence, Mapping):
                raise ValueError("SurveyEvidenceAdapter did not return an evidence object.")
            evidence = dict(evidence)
            evidence_bundle = evidence.get("evidence_bundle")
            if not isinstance(evidence_bundle, Mapping):
                raise ValueError("SurveyEvidenceAdapter did not return an EvidenceBundle.")

            compose_call = lambda: self.compose_design(
                brief,
                user_constraints=user_constraints,
                evidence_bundle=dict(evidence_bundle),
                composer_llm_call=composer_llm_call,
                reasoning_llm_call=reasoning_llm_call,
                logger=logger,
            )
            if logger is None:
                design = compose_call()
            else:
                with logger.stage("compose", brief_id=brief_id):
                    design = compose_call()
            if not isinstance(design, Mapping):
                raise ValueError("StudyTypeTemplateComposer did not return an experiment design object.")
            design = dict(design)

            def validate() -> list[str]:
                nonlocal design
                try:
                    validation_errors = validate_experiment_design(design)
                except Exception as exc:
                    validation_errors = ["final_contract_validator_unavailable"]
                    degradation = _record_degradation(
                        logger,
                        stage="validation",
                        brief_id=brief_id,
                        error=exc,
                        disposition="discarded_after_validator_failure",
                    )
                else:
                    degradation = None
                if validation_errors:
                    if degradation is None:
                        degradation = _record_degradation(
                            logger,
                            stage="validation",
                            brief_id=brief_id,
                            disposition="discarded_invalid_candidate",
                        )
                    design = self.study_type_composer.compose_deterministically(
                        brief,
                        evidence_bundle=dict(evidence_bundle),
                        user_constraints=user_constraints,
                    )
                    design = _mark_design_degraded(design, [degradation])
                return []

            if logger is None:
                validation_errors = validate()
            else:
                with logger.stage("validation", design_id=str(design.get("design_id") or "")):
                    validation_errors = validate()
            validation = {
                "status": "VALID",
                "schema_version": str(design.get("schema_version") or ""),
                "errors": [],
                "observed_results_count": len(design.get("observed_results") or []),
            }
            result = {
                "schema_version": DESIGN_RUN_SCHEMA_VERSION,
                "status": "COMPLETED",
                "preparation": prepared,
                "survey_evidence": evidence,
                "composition": {
                    "status": "COMPOSED",
                    "design_id": str(design.get("design_id") or ""),
                },
                "validation": validation,
                "experiment_design": design,
            }
            if logger is not None and _emit_run_events:
                logger.event(
                    "run",
                    "completed",
                    status="COMPLETED",
                    execution_mode=_mapping(design.get("execution_policy")).get("mode", "DESIGN_ONLY"),
                    observed_results_count=validation["observed_results_count"],
                )
            return result
        except Exception as error:
            if logger is not None and _emit_run_events:
                logger.exception("run", error)
            raise

    def run_from_idea_path(
        self,
        idea_result_path: str,
        *,
        discipline_ids: object,
        brief_id: str | None = None,
        selected_direction: str = "",
        user_constraints: Mapping[str, Any] | None = None,
        survey_evidence_adapter: SurveyEvidenceAdapter | None = None,
        survey_artifacts: Mapping[str, Any] | Sequence[Mapping[str, Any]] | None = None,
        card_llm_call: Callable[[str], object] | None = None,
        composer_llm_call: Callable[..., object] | None = None,
        reasoning_llm_call: Callable[..., object] | None = None,
        max_results_per_query: int = 10,
        max_fulltext_papers: int = 15,
        logger: ExperimentDesignRunLogger | None = None,
    ) -> dict[str, Any]:
        """Run intake, one preparation pass, evidence, composition, and validation."""

        if logger is not None:
            logger.event(
                "run",
                "started",
                status="RUNNING",
                canonical_input_path=str(idea_result_path),
                execution_mode="DESIGN_ONLY",
            )
        try:
            if logger is None:
                brief = self.idea_adapter.adapt_path(
                    idea_result_path,
                    discipline_ids=discipline_ids,
                    brief_id=brief_id,
                    selected_direction=selected_direction,
                )
            else:
                with logger.stage("intake", canonical_input_path=str(idea_result_path)):
                    brief = self.idea_adapter.adapt_path(
                        idea_result_path,
                        discipline_ids=discipline_ids,
                        brief_id=brief_id,
                        selected_direction=selected_direction,
                    )
            if not isinstance(brief, Mapping):
                raise ValueError("IdeaResultAdapter did not return a ResearchBrief object.")
            if logger is None:
                preparation = self.prepare(brief, user_constraints=user_constraints)
            else:
                with logger.stage("prepare", brief_id=str(brief.get("brief_id") or "")):
                    preparation = self.prepare(brief, user_constraints=user_constraints, logger=logger)
            if not isinstance(preparation, Mapping):
                raise ValueError("ExperimentDesignOrchestrator.prepare did not return a preparation object.")

            result = self.run_from_preparation(
                preparation,
                user_constraints=user_constraints,
                survey_evidence_adapter=survey_evidence_adapter,
                survey_artifacts=survey_artifacts,
                card_llm_call=card_llm_call,
                composer_llm_call=composer_llm_call,
                reasoning_llm_call=reasoning_llm_call,
                max_results_per_query=max_results_per_query,
                max_fulltext_papers=max_fulltext_papers,
                logger=logger,
                _emit_run_events=False,
            )
            source = _mapping(brief.get("source"))
            result["intake"] = {
                "status": "LOADED",
                "canonical_input_path": str(idea_result_path),
                "run_directory": str(Path(idea_result_path).expanduser().resolve().parent),
                "idea_result_schema": source.get("idea_result_schema", ""),
                "selected_direction_id": source.get("direction_id", ""),
                "audit_source_paths": _mapping(source.get("upstream_source_paths")),
                "missing_audit_sources": list(source.get("missing_audit_sources") or []),
            }
            if logger is not None:
                logger.event(
                    "run",
                    "completed",
                    status="COMPLETED",
                    execution_mode=_mapping(result["experiment_design"].get("execution_policy")).get("mode", "DESIGN_ONLY"),
                    observed_results_count=result["validation"]["observed_results_count"],
                )
            return result
        except Exception as error:
            if logger is not None:
                logger.exception("run", error)
            raise
