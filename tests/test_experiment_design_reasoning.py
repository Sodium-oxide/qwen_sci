from __future__ import annotations

from copy import deepcopy
from io import StringIO
import json

import pytest

from src.agents.experiment_design_agent import (
    CounterexampleAnalyzer,
    ExperimentDesignOrchestrator,
    FormalReasoningPlanContractError,
    FormalReasoningPlanner,
    RequiredJsonLLMError,
    build_default_json_llm_call,
    load_idea_artifact_bundle,
    validate_formal_reasoning_plan,
    validate_counterexample_analysis,
    validate_reasoning_artifacts,
)
from src.agents.experiment_design_agent.evidence_planner import _baseline_queries
from src.agents.experiment_design_agent.contracts import (
    RESEARCH_BRIEF_SCHEMA_VERSION,
    validate_experiment_design,
)
from src.agents.experiment_design_agent.formal_reasoning_planner import (
    validate_formal_reasoning_contract_repair,
)
from src.agents.experiment_design_agent.run_logging import ExperimentDesignRunLogger


def _brief(discipline_id: str = "26") -> dict:
    return {
        "schema_version": RESEARCH_BRIEF_SCHEMA_VERSION,
        "brief_id": "reasoning-brief",
        "topic": "A declared formal research relation.",
        "discipline_ids": [discipline_id],
        "selected_direction": {
            "id": "selected",
            "title": "A declared formal research relation.",
            "central_hypothesis": "Under A1, the relation x > 0 follows.",
            "mechanism_or_relation": "A symbolic relation over x.",
        },
        "research_object": {"description": "A formal object."},
        "intervention_or_transformation": "A declared transformation.",
        "discriminating_observations": ["A symbolic verification check."],
        "boundary_conditions": ["The declared formal scope."],
        "alternative_explanations": ["A different symbolic relation."],
        "known_unknowns": ["The proof obligation remains unverified."],
        "evidence_status": "PROPOSED",
        "source": {"idea_result_schema": "idea_result_v5", "direction_id": "selected"},
        "reasoning_context": {
            "schema_version": "reasoning_context_v1",
            "selected_direction_id": "selected",
            "assumptions": ["x is positive."],
            "claim_scope": "The declared formal research relation.",
            "falsifiers": [],
            "boundary_conditions": ["The declared formal scope."],
            "alternative_explanations": ["A different symbolic relation."],
            "formal_symbols": ["x"],
            "gap_records": [],
            "evidence_roles": [],
            "source_anchors": [],
            "upstream_source_paths": [],
            "source_priority": ["selected_direction"],
        },
    }


def _formal_plan() -> dict:
    return {
        "schema_version": "formal_reasoning_plan_v1",
        "applicability": "formal_theory",
        "assumptions": [
            {
                "assumption_id": "A1",
                "statement": "x is positive.",
                "predicate": "x > 0",
                "scope": "declared domain",
                "satisfaction_test": "Check x > 0.",
                "symbol_references": ["x"],
                "variable_references": [],
                "source_path": "reasoning_context.assumptions[0]",
                "status": "candidate_formalization",
            }
        ],
        "definitions": [
            {
                "definition_id": "D1",
                "symbol": "x",
                "statement": "x is the declared scalar.",
                "domain": "real numbers",
                "codomain": "real numbers",
                "variable_references": [],
                "source_path": "variable_claim_model.variables.V1",
                "status": "candidate_formalization",
            }
        ],
        "propositions": [
            {
                "proposition_id": "P1",
                "statement": "The target relation holds.",
                "premises": ["A1", "D1"],
                "conclusion": "x > 0",
                "scope": "declared domain",
                "symbol_references": ["x"],
                "variable_references": [],
                "status": "candidate_formalization",
            }
        ],
        "proof_obligations": [
            {
                "obligation_id": "PO1",
                "target": "Show x > 0.",
                "dependencies": ["A1", "D1"],
                "symbol_references": ["x"],
                "variable_references": [],
                "status": "unresolved",
            }
        ],
        "forward_derivation": {
            "steps": [
                {
                    "step_id": "S1",
                    "premises": ["A1", "D1"],
                    "symbol_references": ["x"],
                    "variable_references": [],
                    "rule_or_lemma": "Use A1.",
                    "derived_statement": "x > 0",
                    "status": "proposed",
                }
            ],
            "target_proposition_id": "P1",
            "final_conclusion_step": "S1",
            "final_conclusion": "x > 0",
            "status": "unverified",
        },
        "unknown_items": [],
        "status": "unverified",
    }


def _p2_status_and_s4_final_step_error_plan() -> dict:
    plan = _formal_plan()
    proposition = deepcopy(plan["propositions"][0])
    proposition["proposition_id"] = "P2"
    proposition["statement"] = "A secondary declared relation."
    proposition["status"] = "invalid_status"
    plan["propositions"].append(proposition)
    base_step = plan["forward_derivation"]["steps"][0]
    for step_id in ("S2", "S3", "S4"):
        step = deepcopy(base_step)
        step["step_id"] = step_id
        plan["forward_derivation"]["steps"].append(step)
    plan["forward_derivation"]["final_conclusion_step"] = "S4"
    plan["forward_derivation"]["steps"][3]["derived_statement"] = "A mismatched final conclusion."
    return plan


def _counterexample_plan() -> dict:
    return {
        "schema_version": "counterexample_analysis_v1",
        "applicability": "formal_theory",
        "target_claim_id": "P1",
        "negated_conclusion": "not (x > 0)",
        "search_domain": "declared scalar domain",
        "candidate_counterexamples": [],
        "exhaustiveness": {"scope": "bounded symbolic candidates", "is_exhaustive": False, "reason": "No exhaustive proof was run."},
        "status": "no_candidate_found_in_declared_scope",
        "limitations": ["A finite search cannot establish theorem validity."],
        "unknown_items": [],
    }


def _llm_callback(calls: list[dict]) -> object:
    def callback(prompt: str, **kwargs: object) -> dict:
        calls.append({"prompt": prompt, **kwargs})
        if "Evidence Retrieval Planner" in prompt:
            return {"queries": [{key: value for key, value in task.items() if key != "task_id"} for task in _baseline_queries(_brief())]}
        if "Variable and Claim Extractor" in prompt:
            return {
                "schema_version": "variable_claim_model_v1",
                "status": "complete_or_requires_input",
                "claims": [],
                "variables": [],
                "unknown_items": [],
            }
        if "Formal Reasoning Planner" in prompt:
            return _formal_plan()
        if "Counterexample Analyzer" in prompt:
            return _counterexample_plan()
        return {"open_design_questions": ["Confirm unresolved design requirements."]}

    return callback


def test_every_required_stage_receives_json_object_mode() -> None:
    calls: list[dict] = []
    orchestrator = ExperimentDesignOrchestrator(llm_call=_llm_callback(calls))

    prepared = orchestrator.prepare(_brief())
    assert prepared["evidence_retrieval_plan"]["llm_used"] is True
    assert calls[0]["response_format"] == {"type": "json_object"}

    calls.clear()
    design = orchestrator.compose_design(_brief())
    assert len(calls) == 4
    assert all(call["response_format"] == {"type": "json_object"} for call in calls)
    assert design["observed_results"] == []
    assert design["formal_reasoning_plan"]["forward_derivation"]["status"] == "unverified"


def test_orchestrator_degrades_an_invalid_query_plan_without_fabricating_evidence() -> None:
    prepared = ExperimentDesignOrchestrator(
        llm_call=lambda _prompt, **_kwargs: "not-json"
    ).prepare(_brief())

    plan = prepared["evidence_retrieval_plan"]
    assert plan["planning_status"] == "READY_FOR_RETRIEVAL"
    assert plan["llm_used"] is False
    assert plan["retrieved_evidence"] == []
    assert plan["warnings"]
    assert any(item["field_path"] == "evidence_retrieval_plan.queries" for item in prepared["unknown_items"])


@pytest.mark.parametrize(
    ("failed_stage", "expected_degraded_stage"),
    (
        ("variable", "variable_claim_extraction"),
        ("formal", "formal_reasoning_planner"),
        ("counterexample", "counterexample_analyzer"),
        ("template", "template_composer"),
    ),
)
def test_orchestrator_discards_invalid_llm_batches_and_returns_a_valid_design(
    failed_stage: str,
    expected_degraded_stage: str,
) -> None:
    logger = ExperimentDesignRunLogger(f"degraded-{failed_stage}", console_stream=StringIO())

    def llm_call(prompt: str, **_kwargs: object) -> object:
        if "Variable and Claim Extractor" in prompt:
            if failed_stage == "variable":
                return "not-json"
            return {
                "schema_version": "variable_claim_model_v1",
                "status": "complete_or_requires_input",
                "claims": [],
                "variables": [],
                "unknown_items": [],
            }
        if "Formal Reasoning Planner" in prompt:
            return "not-json" if failed_stage == "formal" else _formal_plan()
        if "Counterexample Analyzer" in prompt:
            return "not-json" if failed_stage == "counterexample" else _counterexample_plan()
        if failed_stage == "template":
            return {"unsupported_section": "discard this patch"}
        return {"open_design_questions": ["Confirm unresolved design requirements."]}

    design = ExperimentDesignOrchestrator(llm_call=llm_call).compose_design(
        _brief(),
        logger=logger,
    )

    assert validate_experiment_design(design) == []
    assert design["risk_and_human_review"]["human_review_required"] is True
    assert "LLM_OR_WORKFLOW_DEGRADATION_REVIEW" in design["risk_and_human_review"]["review_triggers"]
    assert design["field_statuses"][f"degraded_stages.{expected_degraded_stage}"] == "needs_human_input"
    assert any(
        record["stage"] == expected_degraded_stage
        and record["event"] == "degraded"
        and record["status"] == "DEGRADED"
        for record in logger.records
    )
    assert all("not-json" not in str(record) for record in logger.records)
    if failed_stage == "variable":
        assert design["variable_claim_model"]["unknown_items"]
        assert design["formal_reasoning_plan"]["status"] == "requires_human_review"
    if failed_stage == "formal":
        assert design["formal_reasoning_plan"]["status"] == "requires_human_review"
        assert design["counterexample_analysis"]["status"] == "requires_human_review"
    if failed_stage == "counterexample":
        assert design["counterexample_analysis"]["status"] == "requires_human_review"
    if failed_stage == "template":
        assert design["template_composition"]["llm_used"] is False


def test_formal_planner_logs_json_contract_failure_without_raw_response() -> None:
    logger = ExperimentDesignRunLogger("formal-json-failure", console_stream=StringIO())

    with pytest.raises(RequiredJsonLLMError):
        FormalReasoningPlanner().plan(
            _brief(),
            {"schema_version": "reasoning_context_v1"},
            _variable_claim_model(),
            llm_call=lambda *_args, **_kwargs: "not a complete JSON object",
            logger=logger,
            brief_id="reasoning-brief",
        )

    events = [
        record
        for record in logger.records
        if record["stage"] == "formal_reasoning_planner"
    ]
    assert [record["event"] for record in events] == [
        "llm_request_started",
        "llm_response_received",
        "llm_json_contract_failed",
    ]
    response_event = events[1]
    assert response_event["response_type"] == "str"
    assert response_event["response_character_count"] == len("not a complete JSON object")
    assert response_event["response_starts_with_json_object"] is False
    assert response_event["response_has_code_fence"] is False
    assert all("not a complete JSON object" not in str(record) for record in events)


def test_counterexample_analyzer_logs_json_contract_failure_without_raw_response() -> None:
    logger = ExperimentDesignRunLogger("counterexample-json-failure", console_stream=StringIO())
    rejected_response = "not a complete JSON object"

    with pytest.raises(RequiredJsonLLMError):
        CounterexampleAnalyzer().analyze(
            _brief(),
            {"schema_version": "reasoning_context_v1"},
            _variable_claim_model(),
            _formal_plan(),
            llm_call=lambda *_args, **_kwargs: rejected_response,
            logger=logger,
            brief_id="reasoning-brief",
        )

    events = [
        record
        for record in logger.records
        if record["stage"] == "counterexample_analyzer"
    ]
    assert [record["event"] for record in events] == [
        "llm_request_started",
        "llm_response_received",
        "llm_json_contract_failed",
    ]
    assert events[1]["response_character_count"] == len(rejected_response)
    assert all(rejected_response not in str(record) for record in events)


def test_final_validation_logs_profile_and_safe_invalid_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    logger = ExperimentDesignRunLogger("final-validation-invalid", console_stream=StringIO())
    rejected_value = "do-not-log-this-validation-value"
    monkeypatch.setattr(
        "src.agents.experiment_design_agent.orchestrator.validate_experiment_design",
        lambda _design: [f"design_schema: {rejected_value}"],
    )

    design = ExperimentDesignOrchestrator(llm_call=_llm_callback([])).compose_design(
        _brief(),
        logger=logger,
    )

    events = [
        record
        for record in logger.records
        if record["stage"] == "compose_final_validation"
    ]
    assert [record["event"] for record in events] == [
        "started",
        "input_profiled",
        "contract_validated",
        "discarded_invalid_candidate",
        "degraded",
        "contract_validated",
        "completed",
    ]
    contract_event = events[2]
    assert contract_event["status"] == "DEGRADED"
    assert contract_event["validation_errors"] == ["design_schema"]
    assert contract_event["outcome_branch_count"] == 4
    assert all(rejected_value not in str(record) for record in events)
    assert design["template_composition"]["llm_used"] is False
    assert "LLM_OR_WORKFLOW_DEGRADATION_REVIEW" in design["risk_and_human_review"]["review_triggers"]


def test_default_callback_uses_the_project_agent_and_json_mode(monkeypatch) -> None:
    calls: list[dict] = []

    class Provider:
        default_models = {
            "experiment_design": "test-experiment-design-model",
            "experiment": "test-experiment-model",
        }

    class FakeAgent:
        provider = Provider()

        def __init__(self, *, config=None, provider_name=None) -> None:
            self.config = config
            self.provider_name = provider_name

        def chat(self, prompt: str, *, model: str, **kwargs: object) -> str:
            calls.append({"prompt": prompt, "model": model, **kwargs})
            return "{\"ok\": true}"

    import src.agents.idea_agent.agent.base as base

    monkeypatch.setattr(base, "AgentBase", FakeAgent)
    callback = build_default_json_llm_call(config={"llm": {}})
    assert callback("return JSON", response_format={"type": "json_object"}) == '{"ok": true}'
    assert calls[0]["model"] == "test-experiment-design-model"
    assert calls[0]["response_format"] == {"type": "json_object"}


def test_default_callback_uses_experiment_design_qwen_model_and_provider(monkeypatch) -> None:
    calls: list[dict] = []

    class Provider:
        default_models = {}

    class FakeAgent:
        provider = Provider()

        def __init__(self, *, config=None, provider_name=None) -> None:
            calls.append({"config": config, "provider_name": provider_name})

        def chat(self, prompt: str, *, model: str, **kwargs: object) -> str:
            calls.append({"prompt": prompt, "model": model, **kwargs})
            return '{"ok": true}'

    import src.agents.idea_agent.agent.base as base

    monkeypatch.setattr(base, "AgentBase", FakeAgent)
    callback = build_default_json_llm_call(
        config={
            "llm": {"default_provider": "openai"},
            "experiment_design": {"provider": "qwen", "model": "qwen3.8-flash"},
        }
    )

    assert callback("return JSON", response_format={"type": "json_object"}) == '{"ok": true}'
    assert calls[0]["provider_name"] == "qwen"
    assert calls[1]["model"] == "qwen3.8-flash"


def test_semantic_validation_rejects_undefined_symbols_but_allows_independent_final_text() -> None:
    plan = _formal_plan()
    plan["propositions"][0]["symbol_references"] = ["undefined"]
    assert any("undefined_symbol" in error for error in validate_formal_reasoning_plan(plan))

    plan = _formal_plan()
    plan["forward_derivation"]["final_conclusion"] = "x < 0"
    plan["forward_derivation"]["steps"][0]["derived_statement"] = "A different derivation statement."
    assert validate_formal_reasoning_plan(plan) == []


def _variable_claim_model() -> dict:
    return {
        "schema_version": "variable_claim_model_v1",
        "status": "complete_or_requires_input",
        "claims": [],
        "variables": [
            {
                "variable_id": "V1",
                "name": "declared scalar",
                "role": "formal_parameter",
                "formal_or_empirical": "formal",
                "construct": "A scalar in the supplied formal relation.",
                "observable": "not_applicable",
                "operational_definition": {"value": "", "status": "needs_formal_definition"},
                "unit_or_domain": {"value": "", "status": "needs_formal_definition"},
                "hypothesis_links": ["H1"],
                "claim_links": [],
                "source_path": "research_brief.reasoning_context",
                "status": "candidate_extracted",
            }
        ],
        "unknown_items": [],
    }


def test_user_declared_assumption_status_is_allowed() -> None:
    plan = _formal_plan()
    plan["assumptions"][0]["status"] = "user_declared"

    assert validate_formal_reasoning_plan(plan) == []


def test_formal_reasoning_statuses_match_the_prompt_contract() -> None:
    plan = _formal_plan()
    plan["propositions"][0]["status"] = "unverified"

    assert any("propositions[0]_invalid_status" in error for error in validate_formal_reasoning_plan(plan))


def test_variable_id_used_as_a_symbol_requires_a_linked_definition() -> None:
    plan = _formal_plan()
    plan["definitions"][0]["symbol"] = "V1"
    for record in (
        plan["assumptions"][0],
        plan["propositions"][0],
        plan["proof_obligations"][0],
        plan["forward_derivation"]["steps"][0],
    ):
        record["symbol_references"] = ["V1"]

    errors = validate_formal_reasoning_plan(plan, variable_claim_model=_variable_claim_model())
    assert any("variable_id_symbol_requires_linked_definition:V1" in error for error in errors)

    plan["definitions"][0]["variable_references"] = ["V1"]
    assert validate_formal_reasoning_plan(plan, variable_claim_model=_variable_claim_model()) == []


def test_formal_definition_rejects_extra_reference_array_and_repair_may_only_remove_it() -> None:
    initial = _formal_plan()
    initial["definitions"][0]["symbol_references"] = ["x"]

    initial_errors = validate_formal_reasoning_plan(initial, variable_claim_model=_variable_claim_model())
    assert "formal_reasoning_plan.definitions[0]_unsupported_reference_array:symbol_references" in initial_errors

    repaired = deepcopy(initial)
    del repaired["definitions"][0]["symbol_references"]
    assert validate_formal_reasoning_contract_repair(initial, repaired) == []
    assert validate_formal_reasoning_plan(repaired, variable_claim_model=_variable_claim_model()) == []

    rewritten = deepcopy(initial)
    rewritten["definitions"][0]["symbol_references"] = ["another_symbol"]
    assert (
        "contract_repair_modified_protected_field:definitions.D1.symbol_references"
        in validate_formal_reasoning_contract_repair(initial, rewritten)
    )


def test_formal_planner_repairs_only_contract_references_and_retains_audit() -> None:
    initial = _formal_plan()
    initial["assumptions"][0]["symbol_references"] = ["V1"]
    initial["assumptions"][0]["status"] = "declared"
    initial["propositions"][0]["symbol_references"] = ["V1"]
    initial["proof_obligations"][0]["symbol_references"] = ["V1"]
    initial["forward_derivation"]["steps"][0]["symbol_references"] = ["V1"]
    repair_patch = {
        "schema_version": "formal_reasoning_repair_patch_v1",
        "operations": [
            {"op": "replace", "path": "/assumptions/A1/symbol_references", "value": ["x"]},
            {"op": "replace", "path": "/assumptions/A1/variable_references", "value": ["V1"]},
            {"op": "replace", "path": "/assumptions/A1/status", "value": "user_declared"},
            {"op": "replace", "path": "/propositions/P1/symbol_references", "value": ["x"]},
            {"op": "replace", "path": "/propositions/P1/variable_references", "value": ["V1"]},
            {"op": "replace", "path": "/proof_obligations/PO1/symbol_references", "value": ["x"]},
            {"op": "replace", "path": "/proof_obligations/PO1/variable_references", "value": ["V1"]},
            {"op": "replace", "path": "/forward_derivation/steps/S1/symbol_references", "value": ["x"]},
            {"op": "replace", "path": "/forward_derivation/steps/S1/variable_references", "value": ["V1"]},
        ],
    }
    calls: list[dict[str, object]] = []
    logger = ExperimentDesignRunLogger("formal-repair-logging", console_stream=StringIO())

    def llm_call(prompt: str, **kwargs: object) -> dict:
        calls.append({"prompt": prompt, **kwargs})
        if "Formal Reasoning Contract Repairer" in prompt:
            return deepcopy(repair_patch)
        return deepcopy(initial)

    plan = FormalReasoningPlanner().plan(
        _brief(),
        {"schema_version": "reasoning_context_v1"},
        _variable_claim_model(),
        llm_call=llm_call,
        logger=logger,
        brief_id="reasoning-brief",
    )

    assert len(calls) == 2
    assert all(call["response_format"] == {"type": "json_object"} for call in calls)
    assert plan["assumptions"][0]["variable_references"] == ["V1"]
    assert plan["assumptions"][0]["symbol_references"] == ["x"]
    assert plan["repair_audit"]["repair_status"] == "REPAIRED"
    assert plan["repair_audit"]["initial_candidate"] == initial
    assert plan["repair_audit"]["repair_patch"] == repair_patch
    assert plan["repair_audit"]["initial_validation_errors"]
    assert validate_formal_reasoning_plan(plan, variable_claim_model=_variable_claim_model()) == []
    assert [
        record["event"]
        for record in logger.records
        if record["stage"] == "formal_reasoning_planner"
    ] == [
        "llm_request_started",
        "llm_response_received",
        "llm_json_parsed",
        "initial_contract_validated",
        "contract_repair_started",
        "contract_repair_validated",
    ]
    assert [
        record["event"]
        for record in logger.records
        if record["stage"] == "formal_reasoning_contract_repair"
    ] == ["llm_request_started", "llm_response_received", "llm_json_parsed"]
    repair_event = next(
        record
        for record in logger.records
        if record["stage"] == "formal_reasoning_planner"
        and record["event"] == "contract_repair_validated"
    )
    assert repair_event["status"] == "REPAIRED"
    assert repair_event["validation_error_count"] == 0
    assert all(
        key not in repair_event
        for key in ("prompt", "raw_response", "response", "initial_candidate", "repaired_candidate")
    )


def test_formal_repair_patch_preserves_required_arrays_during_status_fix() -> None:
    initial = _formal_plan()
    initial["propositions"][0]["status"] = "invalid_status"
    initial["forward_derivation"]["steps"][0]["derived_statement"] = "A mismatched conclusion."
    repair_patch = {
        "schema_version": "formal_reasoning_repair_patch_v1",
        "operations": [
            {"op": "replace", "path": "/propositions/P1/status", "value": "unresolved"},
        ],
    }

    plan = FormalReasoningPlanner().plan(
        _brief(),
        {"schema_version": "reasoning_context_v1"},
        _variable_claim_model(),
        llm_call=lambda prompt, **_kwargs: deepcopy(repair_patch)
        if "Formal Reasoning Contract Repairer" in prompt
        else deepcopy(initial),
    )

    assert plan["propositions"][0]["status"] == "unresolved"
    assert plan["forward_derivation"]["steps"][0]["derived_statement"] == "A mismatched conclusion."
    assert plan["assumptions"][0]["symbol_references"] == ["x"]
    assert plan["propositions"][0]["symbol_references"] == ["x"]
    assert plan["proof_obligations"][0]["symbol_references"] == ["x"]
    assert plan["forward_derivation"]["steps"][0]["symbol_references"] == ["x"]
    assert validate_formal_reasoning_plan(plan, variable_claim_model=_variable_claim_model()) == []


def test_formal_repair_patch_only_fixes_observed_p2_status_error() -> None:
    initial = _p2_status_and_s4_final_step_error_plan()
    assert validate_formal_reasoning_plan(initial, variable_claim_model=_variable_claim_model()) == [
        "formal_reasoning_plan.propositions[1]_invalid_status",
    ]
    repair_patch = {
        "schema_version": "formal_reasoning_repair_patch_v1",
        "operations": [
            {"op": "replace", "path": "/propositions/P2/status", "value": "unresolved"},
        ],
    }

    plan = FormalReasoningPlanner().plan(
        _brief(),
        {"schema_version": "reasoning_context_v1"},
        _variable_claim_model(),
        llm_call=lambda prompt, **_kwargs: deepcopy(repair_patch)
        if "Formal Reasoning Contract Repairer" in prompt
        else deepcopy(initial),
    )

    assert plan["propositions"][1]["status"] == "unresolved"
    assert plan["forward_derivation"]["steps"][3]["derived_statement"] == "A mismatched final conclusion."
    assert all(
        isinstance(record["symbol_references"], list)
        for record in (
            *plan["assumptions"],
            *plan["propositions"],
            *plan["proof_obligations"],
            *plan["forward_derivation"]["steps"],
        )
    )
    assert validate_formal_reasoning_plan(plan, variable_claim_model=_variable_claim_model()) == []


def test_formal_repair_patch_rejects_a_valid_but_unrelated_operation() -> None:
    initial = _p2_status_and_s4_final_step_error_plan()
    repair_patch = {
        "schema_version": "formal_reasoning_repair_patch_v1",
        "operations": [
            {"op": "replace", "path": "/propositions/P2/status", "value": "unresolved"},
            {"op": "replace", "path": "/assumptions/A1/status", "value": "unresolved"},
        ],
    }

    with pytest.raises(FormalReasoningPlanContractError) as error:
        FormalReasoningPlanner().plan(
            _brief(),
            {"schema_version": "reasoning_context_v1"},
            _variable_claim_model(),
            llm_call=lambda prompt, **_kwargs: deepcopy(repair_patch)
            if "Formal Reasoning Contract Repairer" in prompt
            else deepcopy(initial),
        )

    assert error.value.audit_record["repair_status"] == "REJECTED"
    assert "formal_repair_patch_operation_not_required:1" in error.value.audit_record[
        "repair_validation_errors"
    ]


def test_formal_repair_patch_removes_only_an_extra_definition_reference_array() -> None:
    initial = _formal_plan()
    initial["definitions"][0]["symbol_references"] = ["x"]
    repair_patch = {
        "schema_version": "formal_reasoning_repair_patch_v1",
        "operations": [
            {"op": "remove", "path": "/definitions/D1/symbol_references"},
        ],
    }

    plan = FormalReasoningPlanner().plan(
        _brief(),
        {"schema_version": "reasoning_context_v1"},
        _variable_claim_model(),
        llm_call=lambda prompt, **_kwargs: deepcopy(repair_patch)
        if "Formal Reasoning Contract Repairer" in prompt
        else deepcopy(initial),
    )

    assert "symbol_references" not in plan["definitions"][0]
    assert plan["assumptions"][0]["symbol_references"] == ["x"]
    assert validate_formal_reasoning_plan(plan, variable_claim_model=_variable_claim_model()) == []


def test_formal_repair_patch_rejects_a_new_definition_even_for_a_reported_symbol() -> None:
    initial = _formal_plan()
    initial["propositions"][0]["symbol_references"] = ["missing_symbol"]
    repair_patch = {
        "schema_version": "formal_reasoning_repair_patch_v1",
        "operations": [
            {"op": "replace", "path": "/propositions/P1/status", "value": "unresolved"},
            {
                "op": "add",
                "path": "/definitions/D5",
                "value": {
                    "definition_id": "D5",
                    "symbol": "missing_symbol",
                    "statement": "An LLM-invented definition.",
                    "domain": "declared domain",
                    "codomain": "declared codomain",
                    "variable_references": [],
                    "source_path": "reasoning_context",
                    "status": "candidate_formalization",
                },
            },
        ],
    }

    with pytest.raises(FormalReasoningPlanContractError) as error:
        FormalReasoningPlanner().plan(
            _brief(),
            {"schema_version": "reasoning_context_v1"},
            _variable_claim_model(),
            llm_call=lambda prompt, **_kwargs: deepcopy(repair_patch)
            if "Formal Reasoning Contract Repairer" in prompt
            else deepcopy(initial),
        )

    assert error.value.audit_record["repair_status"] == "REJECTED"
    assert "formal_repair_patch_operation_not_required:1" in error.value.audit_record[
        "repair_validation_errors"
    ]


def test_formal_planner_never_returns_an_invalid_repair_as_fallback() -> None:
    invalid = _formal_plan()
    invalid["propositions"][0]["symbol_references"] = ["V1"]

    with pytest.raises(FormalReasoningPlanContractError) as error:
        FormalReasoningPlanner().plan(
            _brief(),
            {"schema_version": "reasoning_context_v1"},
            _variable_claim_model(),
            llm_call=lambda *_args, **_kwargs: deepcopy(invalid),
        )

    assert error.value.audit_record["repair_status"] == "REJECTED"
    assert error.value.audit_record["initial_candidate"] == invalid


def test_formal_planner_rejects_a_repair_that_changes_a_proposition() -> None:
    initial = _formal_plan()
    initial["propositions"][0]["symbol_references"] = ["V1"]
    repair_patch = {
        "schema_version": "formal_reasoning_repair_patch_v1",
        "operations": [
            {"op": "replace", "path": "/propositions/P1/conclusion", "value": "x < 0"},
        ],
    }

    with pytest.raises(FormalReasoningPlanContractError) as error:
        FormalReasoningPlanner().plan(
            _brief(),
            {"schema_version": "reasoning_context_v1"},
            _variable_claim_model(),
            llm_call=lambda prompt, **_kwargs: deepcopy(repair_patch)
            if "Formal Reasoning Contract Repairer" in prompt
            else deepcopy(initial),
        )

    assert error.value.audit_record["repair_status"] == "REJECTED"
    assert "formal_repair_patch_operation_not_required:0" in error.value.audit_record[
        "repair_validation_errors"
    ]


def test_counterexample_validation_requires_all_assumptions_and_separates_empirical_claims() -> None:
    counterexample = _counterexample_plan()
    counterexample["applicability"] = "empirical_consistency"
    errors = validate_reasoning_artifacts(
        variable_claim_model={
            "schema_version": "variable_claim_model_v1",
            "status": "complete_or_requires_input",
            "claims": [],
            "variables": [],
            "unknown_items": [],
        },
        formal_reasoning_plan=_formal_plan(),
        counterexample_analysis=counterexample,
        template_composition={"template_id": "mathematics_theory", "submode": "formal_theory"},
    )
    assert "formal_theorem_and_empirical_consistency_must_remain_separate" in errors

    counterexample = _counterexample_plan()
    counterexample["candidate_counterexamples"] = [{
        "counterexample_id": "CE1",
        "witness": "x = -1",
        "assumption_checks": [],
        "conclusion_check": {
            "negated_conclusion": "not (x > 0)",
            "result": "true",
            "evidence": "candidate only",
        },
        "validity": "candidate_counterexample",
        "search_method": "llm_proposal_only",
        "limitations": ["Not verified."],
    }]
    errors = validate_reasoning_artifacts(
        variable_claim_model=None,
        formal_reasoning_plan=_formal_plan(),
        counterexample_analysis=counterexample,
        template_composition={"template_id": "mathematics_theory", "submode": "formal_theory"},
    )
    assert any("must_check_every_declared_assumption" in error for error in errors)
    assert any("does_not_satisfy_all_assumptions" in error for error in errors)


def test_counterexample_validation_allows_candidate_specific_negated_conclusion() -> None:
    counterexample = _counterexample_plan()
    counterexample["candidate_counterexamples"] = [{
        "counterexample_id": "CE1",
        "witness": "x = -1",
        "assumption_checks": [{
            "assumption_id": "A1",
            "check": "The witness is within the declared scalar domain.",
            "result": "true",
            "evidence": "The candidate assigns a real scalar value to x.",
        }],
        "conclusion_check": {
            "negated_conclusion": "For this witness, the target inequality is false.",
            "result": "false",
            "evidence": "This is a candidate-specific formulation only.",
        },
        "validity": "conclusion_not_refuted",
        "search_method": "llm_proposal_only",
        "limitations": ["Not verified."],
    }]

    assert validate_counterexample_analysis(counterexample) == []


def test_idea_run_loader_keeps_one_canonical_direction_and_audit_paths(tmp_path) -> None:
    run_dir = tmp_path / "idea-run"
    run_dir.mkdir()
    main = {
        "schema_version": "idea_result_v5",
        "topic": "A topic",
        "primary_direction": "selected",
        "directions": [{
            "direction_mode": "selected",
            "title": "Selected direction",
            "hypothesis": {"central_hypothesis": "The selected claim.", "mechanism_or_relation": "A relation."},
            "experiment_handoff": {},
        }],
    }
    (run_dir / "idea_result.json").write_text(json.dumps(main), encoding="utf-8")
    (run_dir / "idea_portfolio.json").write_text(json.dumps({"selected_primary_idea": {"central_hypothesis": "Audit claim."}}), encoding="utf-8")
    (run_dir / "idea_directions.json").write_text(json.dumps({"directions": [{"title": "Do not merge me"}]}), encoding="utf-8")

    bundle = load_idea_artifact_bundle(run_dir)
    assert bundle["idea_result"]["directions"][0]["direction_mode"] == "selected"
    assert "idea_directions" in bundle["audit_sources"]
    assert len(bundle["idea_result"]["directions"]) == 1
    assert bundle["source_paths"]["idea_result"].endswith("idea_result.json")
