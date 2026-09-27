from copy import deepcopy
from io import StringIO
import json

from test_formal_contracts_v2 import formal_plan
from test_experiment_design_reasoning import _brief, _counterexample_plan, _variable_claim_model
from src.agents.experiment_design_agent.orchestrator import ExperimentDesignOrchestrator
from src.agents.experiment_design_agent.formal_contracts import validate_formal_plan_v2
from src.agents.experiment_design_agent.run_logging import ExperimentDesignRunLogger
from src.agents.experiment_design_agent.artifacts import build_author_handoff, write_experiment_design_artifacts
from src.agents.experiment_design_agent.contracts import validate_experiment_design
from src.agents.experiment_design_agent.formal_verification import validate_verification_report, verify_formal_plan
from src.agents.research_plan_author.contracts import validate_author_input
from src.agents.research_plan_author.theory_spine import build_theory_spine, validate_theory_spine
from src.agents.research_plan_author.section_composer import _formal_reference_ids


def test_orchestrator_to_author_carries_real_verification(tmp_path):
    plan = formal_plan()
    plan["definitions"][0]["variable_references"] = []
    calls = []
    def callback(prompt, **kwargs):
        calls.append(prompt.split("\n", 1)[0])
        if "Variable and Claim Extractor" in prompt:
            return {"schema_version": "variable_claim_model_v1", "status": "complete_or_requires_input", "variables": [], "claims": [], "unknown_items": []}
        if "Formal Definition Resolver" in prompt:
            return {"schema_version": "formal_definition_resolution_v1", "definitions": deepcopy(plan["definitions"]), "model_relations": [], "unknown_items": []}
        if "Formal Reasoning Planner v2" in prompt:
            return deepcopy(plan)
        if "Counterexample Analyzer" in prompt:
            return _counterexample_plan()
        if "Formal Scientific Revision Planner" in prompt:
            return {"schema_version": "formal_revision_patch_v1", "reason": "No additional input", "replacements": [], "additions": [], "proof_attempts": []}
        return {"open_design_questions": ["Review physical model applicability separately."]}
    orchestrator = ExperimentDesignOrchestrator(llm_call=callback, config={"experiment_design": {"formal_reasoning": {"enabled": True, "definition_resolution": True, "max_semantic_revisions": 2, "verification": {"enabled": True, "backends": ["z3"], "timeout_seconds": 10}}}})
    design = orchestrator.compose_design(_brief())
    assert design["formal_reasoning_plan"]["schema_version"] == "formal_reasoning_plan_v2"
    assert validate_experiment_design(design) == []
    report = design["formal_verification_report"]
    assert report["target_summaries"][0]["status"] == "verified_in_declared_scope"
    assert design["observed_results"] == []
    assert design["execution_policy"]["mode"] == "DESIGN_ONLY"
    handoff = build_author_handoff(design)
    assert handoff["formal_verification_report"] == report
    assert validate_author_input(handoff) == []
    paths = write_experiment_design_artifacts(design, tmp_path)
    assert "Mathematical Verification Results" in paths.experiment_design_markdown.read_text(encoding="utf-8")
    preparation = {"source_bundle": {"author_context": handoff}}
    spine = build_theory_spine(preparation, routing={"template_family": "mathematics_theory"})
    assert not validate_theory_spine(spine, preparation=preparation)
    assert "PR1/S1" in _formal_reference_ids(preparation)
    unit = next(unit for unit in spine["lemma_units"] if unit["source_kind"] == "proposition")
    assert unit["display_label"] == "P1"
    assert unit["verification_summary"]["status"] == "verified_in_declared_scope"


def test_verification_report_rejects_stale_or_forged_summary():
    plan = formal_plan()
    report = verify_formal_plan(plan, {"enabled": True, "backends": ["z3"]})
    assert validate_verification_report(plan, report) == []
    forged = deepcopy(report)
    forged["policy"]["enabled"] = False
    assert "verification_success_without_valid_execution" in validate_verification_report(plan, forged)
    plan["propositions"][0]["conclusion_expression"]["args"][1] = {"number": "100"}
    assert any("stale_or_mismatched" in error for error in validate_verification_report(plan, report))


def test_diagnostic_only_revision_does_not_repeat_counterexample_analysis():
    plan = formal_plan()
    plan["definitions"][0]["variable_references"] = []
    counterexample_calls = 0

    def callback(prompt, **_kwargs):
        nonlocal counterexample_calls
        if "Variable and Claim Extractor" in prompt:
            return {"schema_version": "variable_claim_model_v1", "status": "complete_or_requires_input",
                    "variables": [], "claims": [], "unknown_items": []}
        if "Formal Definition Resolver" in prompt:
            return {"schema_version": "formal_definition_resolution_v1",
                    "definitions": deepcopy(plan["definitions"]), "model_relations": [], "unknown_items": []}
        if "Formal Reasoning Planner v2" in prompt:
            return deepcopy(plan)
        if "Counterexample Analyzer" in prompt:
            counterexample_calls += 1
            return _counterexample_plan()
        if "Formal Scientific Revision Planner" in prompt:
            return {"schema_version": "formal_revision_patch_v1", "reason": "Record the remaining scope question",
                    "unknown_items": [{"record_id": "P1", "target_id": "P1", "field_path": "propositions.P1.scope",
                                       "reason": "Clarify the declared scope", "status": "needs_human_input"}]}
        return {"open_design_questions": []}

    orchestrator = ExperimentDesignOrchestrator(
        llm_call=callback,
        config={"experiment_design": {"formal_reasoning": {
            "enabled": True, "definition_resolution": True, "max_semantic_revisions": 1,
            "verification": {"enabled": False},
        }}},
    )

    logger = ExperimentDesignRunLogger("diagnostic-only-revision", console_stream=StringIO())
    design = orchestrator.compose_design(_brief(), logger=logger)

    assert counterexample_calls == 1
    assert design["formal_revision_audit"]["iterations"][0]["status"] == "diagnostics_updated"
    assert design["formal_reasoning_plan"]["unknown_items"][0]["record_id"] == "P1"
    completion = next(item for item in logger.records if item["stage"] == "formal_semantic_revision"
                      and item["event"] == "completed")
    assert completion["change_count"] == 0
    assert completion["result_status"] == "diagnostics_updated"


def test_orchestrator_retains_valid_revision_when_another_record_invents_variable():
    plan = formal_plan()
    plan["definitions"][0]["variable_references"] = []

    def callback(prompt, **_kwargs):
        if "Variable and Claim Extractor" in prompt:
            return {"schema_version": "variable_claim_model_v1", "status": "complete_or_requires_input",
                    "variables": [], "claims": [], "unknown_items": []}
        if "Formal Definition Resolver" in prompt:
            return {"schema_version": "formal_definition_resolution_v1",
                    "definitions": deepcopy(plan["definitions"]), "model_relations": [], "unknown_items": []}
        if "Formal Reasoning Planner v2" in prompt:
            return deepcopy(plan)
        if "Counterexample Analyzer" in prompt:
            return _counterexample_plan()
        if "Formal Scientific Revision Planner" in prompt:
            request = json.loads(prompt.split("INPUT_JSON:\n", 1)[1])
            assumption = deepcopy(request["plan"]["assumptions"][0])
            assumption["variable_references"] = ["V16"]
            definition = deepcopy(request["plan"]["definitions"][0])
            definition["selection_reason"] = "Clarify the registered definition"
            return {"schema_version": "formal_revision_patch_v1", "reason": "Clarify the definition",
                    "replacements": [{"collection": "assumptions", "record": assumption},
                                     {"collection": "definitions", "record": definition}]}
        return {"open_design_questions": []}

    logger = ExperimentDesignRunLogger("unknown-variable-orchestration", console_stream=StringIO())
    design = ExperimentDesignOrchestrator(
        llm_call=callback,
        config={"experiment_design": {"formal_reasoning": {
            "enabled": True, "definition_resolution": True, "max_semantic_revisions": 1,
            "verification": {"enabled": False},
        }}},
    ).compose_design(_brief(), logger=logger)

    assert design["formal_reasoning_plan"]["definitions"][0]["selection_reason"] == "Clarify the registered definition"
    assert design["formal_reasoning_plan"]["assumptions"][0] == plan["assumptions"][0]
    assert validate_formal_plan_v2(design["formal_reasoning_plan"], design["variable_claim_model"]) == []
    assert validate_experiment_design(design) == []
    warning = next(record for record in logger.records if record.get("error_code") == "unknown_variable_reference")
    assert warning["record_id"] == "A1"
    assert warning["field_path"] == "assumptions.A1.variable_references"


def test_definition_resolution_warning_does_not_skip_formal_plan():
    calls = []

    def callback(prompt, **kwargs):
        calls.append(prompt)
        if "Variable and Claim Extractor" in prompt:
            return _variable_claim_model()
        if "Formal Definition Resolver" in prompt:
            malformed = deepcopy(formal_plan()["definitions"])
            malformed[0]["variable_references"] = ["V1"]
            malformed[0]["origin"] = "invalid_origin_from_model"
            return {
                "schema_version": "formal_definition_resolution_v1",
                "definitions": malformed,
                "model_relations": [],
                "unknown_items": [],
            }
        if "Formal Reasoning Planner" in prompt or "Formal Reasoning Planner v2" in prompt:
            raise RuntimeError("formal planner unavailable")
        if "Counterexample Analyzer" in prompt:
            raise AssertionError("counterexample LLM must not run after definition resolution failure")
        return {"open_design_questions": []}

    logger = ExperimentDesignRunLogger("definition-failure", console_stream=StringIO())
    config = {"experiment_design": {"formal_reasoning": {"enabled": True, "definition_resolution": True}}}
    design = ExperimentDesignOrchestrator(llm_call=callback, config=config).compose_design(_brief(), logger=logger)

    assert design["formal_reasoning_plan"]["status"] == "requires_human_review"
    assert not any("formal_definition_resolver" in item for item in design["field_statuses"])
    assert any("Formal Reasoning Planner" in prompt for prompt in calls)
    assert any(
        record["stage"] == "formal_definition_resolver"
        and record["event"] == "record_warning"
        and record["status"] == "WARNING"
        and record.get("field") == "origin"
        and record.get("disposition") == "kept_unresolved"
        for record in logger.records
    )
    assert any(
        record["stage"] == "formal_reasoning_planner"
        and record["event"] == "warning"
        and record["status"] == "WARNING"
        for record in logger.records
    )
