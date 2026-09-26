from copy import deepcopy
import json

import pytest

from test_formal_contracts_v2 import formal_plan
from src.agents.experiment_design_agent.formal_contracts import validate_formal_plan_v2
from src.agents.experiment_design_agent.formal_plan_recovery import recover_counterexample_analysis, recover_formal_plan
from src.agents.experiment_design_agent.formal_reasoning_planner import FormalReasoningPlanner
from src.agents.experiment_design_agent.formal_verification import build_verification_task, verify_formal_plan
from src.agents.experiment_design_agent.reasoning_validation import validate_counterexample_analysis


VARIABLES = {"variables": [{"variable_id": "V1"}]}


def resolution(plan):
    return {"definitions": deepcopy(plan["definitions"]), "model_relations": [], "unknown_items": []}


def test_wrapped_skeleton_and_variable_dependencies_preserve_results():
    plan = formal_plan()
    derived = deepcopy(plan["definitions"][0])
    derived.update(definition_id="D12", symbol="y", depends_on=["V1"], variable_references=[])
    plan["definitions"].append(derived)
    relation = {
        "relation_id": "R1", "statement": "A model constraint", "formal_expression": None,
        "scope": "real scalars", "origin": "modeling_convention", "source_refs": [],
        "conditions": [], "condition_expressions": [], "selection_reason": "Model constraint",
        "depends_on": ["V1"], "symbol_references": ["x"], "variable_references": [], "status": "unresolved",
    }
    plan["model_relations"] = [relation]
    resolved = resolution(plan)
    resolved["model_relations"] = [relation]

    def callback(prompt, **_kwargs):
        if "skeleton stage" in prompt:
            return {"formal_plan": deepcopy(plan)}
        return {"target_results": [{"target_id": "P1", "proof_attempts": deepcopy(plan["proof_attempts"])}]}

    generated = FormalReasoningPlanner().plan({}, {}, VARIABLES, formal_inputs=resolved, llm_call=callback)
    assert len(generated["definitions"]) == 2
    assert generated["definitions"][1]["depends_on"] == ["D1"]
    assert generated["model_relations"][0]["depends_on"] == ["D1"]
    assert generated["assumptions"] == plan["assumptions"]
    assert generated["propositions"] == plan["propositions"]
    assert generated["proof_attempts"] == plan["proof_attempts"]
    assert validate_formal_plan_v2(generated, VARIABLES) == []
    assert len(generated["dependency_repairs"]) == 2


def test_ambiguous_variable_dependency_blocks_only_affected_target():
    plan = formal_plan()
    plan["definitions"][0]["definition_id"] = "DA"
    alternative = deepcopy(plan["definitions"][0])
    alternative.update(definition_id="DB", symbol="y")
    plan["definitions"].append(alternative)
    affected = deepcopy(plan["propositions"][0])
    affected.update(proposition_id="P2", depends_on=["V1"])
    plan["propositions"].append(affected)
    generated = recover_formal_plan(plan, VARIABLES)
    assert generated["propositions"][0] == plan["propositions"][0]
    assert generated["propositions"][1]["construction_status"] == "blocked"
    assert generated["proof_attempts"] == plan["proof_attempts"]
    archived = [json.loads(entry["raw_json"]) for entry in generated["construction_archive"]]
    assert any(record.get("depends_on") == ["V1"] for record in archived)
    assert validate_formal_plan_v2(generated, VARIABLES) == []
    assert build_verification_task(generated, "P2", "z3")["blockers"]


@pytest.mark.parametrize("damage", ["bad_quantifier", "bad_lemma_application", "unknown_dependency", "bad_status"])
def test_invalid_record_does_not_erase_independent_proof(damage):
    plan = formal_plan()
    second = deepcopy(plan["propositions"][0])
    second["proposition_id"] = "P2"
    if damage == "bad_quantifier":
        second["quantifiers"] = [{"symbol": "x", "sort": {}, "quantifier": "forall"}]
    elif damage == "bad_lemma_application":
        second["lemma_instantiations"] = [{"lemma_id": "missing", "instantiation": {}}]
    elif damage == "unknown_dependency":
        second["depends_on"] = ["missing"]
    else:
        second["status"] = {"bad": "shape"}
    plan["propositions"].append(second)
    generated = recover_formal_plan(plan, VARIABLES)
    assert generated["propositions"][0] == plan["propositions"][0]
    assert generated["definitions"] == plan["definitions"]
    assert generated["proof_attempts"] == plan["proof_attempts"]
    assert validate_formal_plan_v2(generated, VARIABLES) == []


def test_malformed_derivation_and_attempt_leave_valid_drafts():
    plan = formal_plan()
    plan["forward_derivation"] = "invalid wrapper"
    plan["proof_attempts"].append({"attempt_id": {}, "target_id": {"wrong": "shape"}, "steps": []})
    generated = recover_formal_plan(plan, VARIABLES)
    assert generated["proof_attempts"] == [plan["proof_attempts"][0]]
    assert generated["propositions"] == plan["propositions"]
    assert len(generated["construction_archive"]) == 2
    assert validate_formal_plan_v2(generated, VARIABLES) == []


def test_failed_target_is_repaired_without_changing_successful_target():
    plan = formal_plan()
    second = deepcopy(plan["propositions"][0])
    second["proposition_id"] = "P2"
    plan["propositions"].append(second)
    good = deepcopy(plan["proof_attempts"][0])
    repaired = deepcopy(good)
    repaired.update(attempt_id="PR2", target_id="P2")
    repaired["steps"][0]["step_id"] = "S2"
    repaired["final_step_id"] = "S2"
    invalid = deepcopy(repaired)
    invalid["steps"][0]["premises"] = ["missing"]
    calls = []

    def callback(prompt, **_kwargs):
        if "skeleton stage" in prompt:
            skeleton = deepcopy(plan)
            skeleton["proof_attempts"] = []
            return skeleton
        inputs = json.loads(prompt.split("INPUT_JSON:\n", 1)[1])
        ids = [target["proposition_id"] for target in inputs["skeleton"]["targets"]]
        calls.append(ids)
        if len(calls) == 1:
            return {"target_results": [{"target_id": "P1", "proof_attempts": [good]},
                                       {"target_id": "P2", "proof_attempts": [invalid]}]}
        assert ids == ["P2"]
        assert inputs["targeted_repair"]["diagnostics"]
        assert inputs["skeleton"]["construction_archive"]
        replacement = deepcopy(plan["propositions"][0])
        replacement["statement"] = "A different theorem"
        return {"propositions": [replacement], "target_results": [{"target_id": "P2", "proof_attempts": [repaired]}]}

    generated = FormalReasoningPlanner().plan({}, {}, VARIABLES, formal_inputs=resolution(plan), llm_call=callback)
    assert calls == [["P1", "P2"], ["P2"]]
    assert generated["propositions"] == plan["propositions"]
    assert generated["proof_attempts"] == [good, repaired]
    assert generated["construction_archive"]
    assert not any(item.get("field") == "proof_attempts" for item in generated["unknown_items"])
    assert generated["status"] == "unverified"
    assert validate_formal_plan_v2(generated, VARIABLES) == []


def test_proof_context_includes_later_lemma_and_its_premises():
    plan = formal_plan()
    lemma = deepcopy(plan["propositions"][0])
    lemma["lemma_id"] = lemma.pop("proposition_id").replace("P", "L")
    assumption = deepcopy(plan["assumptions"][0])
    assumption["assumption_id"] = "A2"
    lemma["premises"] = ["A2"]
    plan["assumptions"].append(assumption)
    plan["lemmas"] = [lemma]
    plan["propositions"][0]["premises"] = ["L1"]
    plan["proof_attempts"] = []
    calls = []

    def callback(prompt, **_kwargs):
        if "skeleton stage" in prompt:
            return deepcopy(plan)
        inputs = json.loads(prompt.split("INPUT_JSON:\n", 1)[1])
        target_id = inputs["skeleton"]["targets"][0].get("lemma_id", "P1")
        calls.append(target_id)
        if target_id == "P1":
            assert [record["lemma_id"] for record in inputs["skeleton"]["lemmas"]] == ["L1"]
            assert "A2" in {record["assumption_id"] for record in inputs["skeleton"]["assumptions"]}
            assert inputs["skeleton"]["proof_attempts"][0]["target_id"] == "L1"
        attempt = {"attempt_id": f"PR_{target_id}", "target_id": target_id, "steps": [{
            "step_id": f"S_{target_id}", "premises": ["A2"] if target_id == "L1" else ["L1"],
            "derived_statement": "x >= 0", "rule_or_lemma": "Order implication", "status": "proposed",
        }], "final_step_id": f"S_{target_id}"}
        return {"target_results": [{"target_id": target_id, "proof_attempts": [attempt]}]}

    generated = FormalReasoningPlanner().plan({}, {}, VARIABLES, formal_inputs=resolution(plan), llm_call=callback)
    assert calls == ["L1", "P1"]
    assert len(generated["proof_attempts"]) == 2
    assert validate_formal_plan_v2(generated, VARIABLES) == []


def test_protected_merge_archives_conflicting_accepted_attempt():
    plan = recover_formal_plan(formal_plan(), VARIABLES)
    conflicting = deepcopy(plan["proof_attempts"][0])
    conflicting["steps"][0]["derived_statement"] = "Unapproved change"
    FormalReasoningPlanner._merge_target_response(plan, {"target_results": [{"target_id": "P1", "proof_attempts": [conflicting]}]}, {"P1"})
    assert plan["proof_attempts"] == formal_plan()["proof_attempts"]
    assert json.loads(plan["construction_archive"][0]["raw_json"]) == conflicting


def test_existing_obligation_can_receive_missing_encoding():
    plan = formal_plan()
    obligation = {"obligation_id": "PO1", "target_id": "P1", "target": "Check order implication",
                  "status": "unresolved", "premises": ["A1"], "conclusion_expression": None}
    plan["proof_obligations"] = [obligation]
    plan = recover_formal_plan(plan, VARIABLES)
    completed = {**obligation, "conclusion_expression": deepcopy(plan["propositions"][0]["conclusion_expression"])}
    FormalReasoningPlanner._merge_target_response(plan, {"target_results": [{"target_id": "P1", "proof_obligations": [completed]}]}, {"P1"})
    assert plan["proof_obligations"] == [completed]
    assert not plan["unknown_items"]


def test_target_repair_budget_includes_request_and_record_failures():
    plan = formal_plan()
    invalid = deepcopy(plan["proof_attempts"][0])
    invalid["steps"][0]["premises"] = ["missing"]
    rounds = []

    def callback(prompt, **_kwargs):
        if "skeleton stage" in prompt:
            skeleton = deepcopy(plan)
            skeleton["proof_attempts"] = []
            return skeleton
        inputs = json.loads(prompt.split("INPUT_JSON:\n", 1)[1])
        rounds.append(inputs["targeted_repair"])
        if len(rounds) == 1:
            return {"target_results": [{"target_id": "P1", "proof_attempts": [invalid]}]}
        raise RuntimeError("Repair request failed")

    generated = FormalReasoningPlanner().plan({}, {}, VARIABLES, formal_inputs=resolution(plan), llm_call=callback,
                                            planner_settings={"max_target_repairs": 1})
    assert len(rounds) == 2
    assert generated["propositions"] == plan["propositions"]
    assert generated["construction_archive"]
    assert validate_formal_plan_v2(generated, VARIABLES) == []


def test_failed_id_repair_retains_independent_skeleton():
    plan = formal_plan()
    broken = deepcopy(plan["assumptions"][0])
    del broken["assumption_id"]
    plan["assumptions"].append(broken)
    plan["proof_attempts"] = []

    def callback(prompt, **_kwargs):
        if "skeleton stage" in prompt:
            return deepcopy(plan)
        if "Repair only record identifiers" in prompt:
            raise RuntimeError("ID repair timeout")
        return {"target_results": [{"target_id": "P1"}]}

    generated = FormalReasoningPlanner().plan({}, {}, VARIABLES, formal_inputs=resolution(plan), llm_call=callback)
    assert generated["definitions"] == plan["definitions"]
    assert generated["propositions"] == plan["propositions"]
    assert len(generated["assumptions"]) == 2
    assert validate_formal_plan_v2(generated, VARIABLES) == []


def test_blocked_premise_cannot_pass_rule_or_backend(monkeypatch):
    plan = formal_plan()
    plan["assumptions"][0]["depends_on"] = ["missing"]
    generated = recover_formal_plan(plan, VARIABLES)
    calls = []
    def unexpected_backend(*_args, **_kwargs):
        calls.append(1)
        raise AssertionError("Blocked construction must not launch a backend")

    monkeypatch.setattr("src.agents.experiment_design_agent.formal_verification.subprocess.run", unexpected_backend)
    report = verify_formal_plan(generated, {"enabled": True, "backends": ["z3", "lean"]})
    assert calls == []
    assert report["target_summaries"][0]["status"] == "unresolved"
    assert generated["proof_attempts"] == plan["proof_attempts"]
    assert generated["construction_archive"]


def test_invalid_counterexample_does_not_erase_other_target_analysis():
    from src.agents.experiment_design_agent.counterexample_analyzer import unavailable_counterexample_analysis

    plan = formal_plan()
    second = deepcopy(plan["propositions"][0])
    second["proposition_id"] = "P2"
    plan["propositions"].append(second)
    good = unavailable_counterexample_analysis(reason="An explicit search is required.")
    good["target_claim_id"] = "P1"
    bad = deepcopy(good)
    bad.update(target_claim_id="P2", candidate_counterexamples="bad")
    generated = recover_counterexample_analysis({**good, "target_analyses": [good, bad]}, plan)
    assert generated["target_analyses"][0] == good
    assert generated["target_analyses"][1]["construction_archive"]
    assert validate_counterexample_analysis(generated, formal_reasoning_plan=plan) == []


def test_skeleton_receives_relevant_scientific_evidence():
    plan = formal_plan()
    inputs = []
    card = {"card_id": "EC1", "source_id": "paper1", "statement": "Order weakening of a real scalar x",
            "evidence_excerpt": "A positive real scalar x satisfies x >= 0.", "locator": "Theorem 1"}

    def callback(prompt, **_kwargs):
        if "skeleton stage" in prompt:
            inputs.append(json.loads(prompt.split("INPUT_JSON:\n", 1)[1]))
            return deepcopy(plan)
        return {"target_results": [{"target_id": "P1"}]}

    FormalReasoningPlanner().plan({}, {}, VARIABLES, formal_inputs=resolution(plan),
                                 evidence_bundle={"evidence_cards": [card]}, llm_call=callback)
    assert inputs[0]["evidence_bundle"]["evidence_cards"] == [card]


@pytest.mark.parametrize("conflict", ["id", "symbol", "cycle"])
def test_ambiguous_or_cyclic_premise_blocks_affected_proof(conflict):
    plan = formal_plan()
    if conflict == "cycle":
        plan["assumptions"][0]["depends_on"] = ["P1"]
    else:
        duplicate = deepcopy(plan["definitions"][0])
        if conflict == "symbol":
            duplicate["definition_id"] = "D2"
        duplicate["statement"] = "An incompatible definition"
        plan["definitions"].append(duplicate)
    generated = recover_formal_plan(plan, VARIABLES)
    assert generated["propositions"][0]["construction_status"] == "blocked"
    assert generated["construction_archive"]
    assert generated["proof_attempts"] == plan["proof_attempts"]
    assert validate_formal_plan_v2(generated, VARIABLES) == []


def test_cross_artifact_validation_preserves_formal_plan(monkeypatch):
    from io import StringIO
    from test_experiment_design_reasoning import _brief, _counterexample_plan, _variable_claim_model
    from src.agents.experiment_design_agent.contracts import validate_experiment_design
    from src.agents.experiment_design_agent.orchestrator import ExperimentDesignOrchestrator
    from src.agents.experiment_design_agent.run_logging import ExperimentDesignRunLogger

    plan = formal_plan()
    plan["definitions"][0]["variable_references"] = []
    invalid = deepcopy(plan["propositions"][0])
    invalid.update(proposition_id="P2", depends_on=["unknown"])
    plan["propositions"].append(invalid)
    model = _variable_claim_model()
    logger = ExperimentDesignRunLogger("partial-recovery", console_stream=StringIO())

    def callback(prompt, **_kwargs):
        if "Variable and Claim Extractor" in prompt:
            return deepcopy(model)
        if "Formal Definition Resolver" in prompt:
            return {"schema_version": "formal_definition_resolution_v1", **resolution(plan)}
        if "Counterexample Analyzer" in prompt:
            return _counterexample_plan()
        return {"open_design_questions": []}

    orchestrator = ExperimentDesignOrchestrator(llm_call=callback, config={"experiment_design": {
        "formal_reasoning": {"enabled": True, "definition_resolution": True,
                             "max_semantic_revisions": 0, "verification": {"enabled": False}},
    }})
    monkeypatch.setattr(orchestrator.formal_reasoning_planner, "plan", lambda *_args, **_kwargs: deepcopy(plan))
    design = orchestrator.compose_design(_brief(), logger=logger)
    generated = design["formal_reasoning_plan"]
    assert design["variable_claim_model"]["variables"] == model["variables"]
    assert generated["definitions"] == plan["definitions"]
    assert generated["propositions"][0] == plan["propositions"][0]
    assert generated["proof_attempts"] == plan["proof_attempts"]
    assert generated["propositions"][1]["construction_status"] == "blocked"
    assert validate_experiment_design(design) == []
    assert any(record["event"] == "records_recovered" for record in logger.records)
    assert not any(record["status"] == "DEGRADED" for record in logger.records)
