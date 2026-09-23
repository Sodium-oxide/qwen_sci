from copy import deepcopy

from src.agents.experiment_design_agent.formal_dependency import build_counterexample_target
from src.agents.experiment_design_agent.artifacts import _formal_reasoning_summary
from src.agents.experiment_design_agent.reasoning_validation import validate_counterexample_analysis


def plan():
    return {
        "assumptions": [
            {"assumption_id": "A1", "predicate": "x > 0"},
            {"assumption_id": "A2", "predicate": "spectral uniqueness"},
        ],
        "definitions": [{"definition_id": "D1", "domain": "R", "codomain": "R", "symbol": "x", "source_path": "source"}],
        "propositions": [{"proposition_id": "P1", "premises": ["A1", "D1"], "conclusion": "x > 1", "scope": "R"}],
        "proof_obligations": [{"obligation_id": "PO1", "target": "prove P1", "dependencies": ["P1"]}],
        "forward_derivation": {"final_conclusion_step": "S1", "steps": []},
    }


def test_counterexample_is_conjunction_and_uses_target_assumptions():
    target = build_counterexample_target(plan(), "P1")
    assert target["required_assumption_ids"] == ["A1"]
    assert target["counterexample_condition"]["operator"] == "and"
    assert target["counterexample_condition"]["operands"][-1] == {"operator": "not", "operand": {"conclusion_ref": "P1"}}


def test_global_and_transitive_assumptions_are_required():
    formal = plan()
    formal["definitions"][0]["depends_on"] = ["A2"]
    assert build_counterexample_target(formal, "P1")["required_assumption_ids"] == ["A1", "A2"]
    formal["definitions"][0].pop("depends_on")
    formal["global_assumption_ids"] = ["A2"]
    assert build_counterexample_target(formal, "P1")["required_assumption_ids"] == ["A1", "A2"]


def test_author_handoff_retains_mathematical_content():
    formal = plan()
    handoff = _formal_reasoning_summary(formal)
    for collection in ("assumptions", "definitions", "propositions", "proof_obligations"):
        assert handoff[collection] == formal[collection]
    assert handoff["forward_derivation"]["final_conclusion_step"] == "S1"
    handoff["definitions"][0]["domain"] = "changed"
    assert formal["definitions"][0]["domain"] == "R"


def test_missing_relevant_assumption_is_rejected_but_a2_is_optional():
    analysis = {
        "schema_version": "counterexample_analysis_v1", "applicability": "formal_theory",
        "target_claim_id": "P1", "negated_conclusion": "not x > 1", "search_domain": "R",
        "candidate_counterexamples": [{
            "counterexample_id": "CE2", "witness": "x = 1/2",
            "assumption_checks": [{"assumption_id": "A1", "check": "x > 0", "result": "true", "evidence": "1/2 > 0"}],
            "conclusion_check": {"negated_conclusion": "x <= 1", "result": "true", "evidence": "1/2 <= 1"},
            "validity": "unverified", "search_method": "llm_proposal_only", "limitations": [],
        }],
        "exhaustiveness": {"is_exhaustive": False}, "status": "candidate_found_unverified", "limitations": [], "unknown_items": [],
    }
    assert validate_counterexample_analysis(analysis, formal_reasoning_plan=plan()) == []
    missing = deepcopy(analysis)
    missing["candidate_counterexamples"][0]["assumption_checks"] = []
    assert any("missing_target_assumptions" in error for error in validate_counterexample_analysis(missing, formal_reasoning_plan=plan()))
    analysis["target_claim_id"] = "P9"
    assert "unknown_formal_target:P9" in validate_counterexample_analysis(analysis, formal_reasoning_plan=plan())
