from copy import deepcopy
import json

import pytest

from test_formal_contracts_v2 import formal_plan
from src.agents.experiment_design_agent.formal_definition_resolver import FormalDefinitionResolver
from src.agents.experiment_design_agent.formal_reconciliation import (
    apply_definition_reconciliation, reconciliation_record_scope, repair_plan_symbol_conflicts,
)
from src.agents.experiment_design_agent.formal_reasoning_planner import FormalReasoningPlanner
from src.agents.experiment_design_agent.formal_contracts import validate_formal_plan_v2
from src.agents.experiment_design_agent.formal_plan_recovery import recover_formal_plan
from src.agents.experiment_design_agent.formal_verification import build_verification_task, verify_formal_plan
from src.agents.experiment_design_agent.proof_checker import verify_proof_attempt


def resolution():
    plan = formal_plan()
    return {"schema_version": "formal_definition_resolution_v1",
            "definitions": deepcopy(plan["definitions"]), "model_relations": [], "unknown_items": []}


def test_reconciliation_preserves_text_diagnostics_while_applying_definition_repair():
    payload = resolution()
    payload["unknown_items"] = [
        "An open research question remains.",
        {"record_id": "D1", "field_path": "definitions.D1.unit",
         "reason": "Unit was missing", "status": "needs_human_input"},
    ]
    repaired = apply_definition_reconciliation(payload, {
        "repairs": [{"record_id": "D1", "fields": {"selection_reason": "A revised mathematical convention"}}],
    })

    assert repaired["unknown_items"][0] == payload["unknown_items"][0]
    assert repaired["unknown_items"][1]["resolved"] is True
    assert "reconciliation_audit" in repaired
    assert "resolved" not in payload["unknown_items"][1]
    assert apply_definition_reconciliation(payload, {"issues": []}) == payload


def test_reconciliation_reports_malformed_record_location_without_attribute_error():
    payload = resolution()
    payload["definitions"].append("Invalid definition object")

    with pytest.raises(ValueError, match=r"record_not_object:definitions\[1\]"):
        apply_definition_reconciliation(payload, {})


def test_reconciliation_scope_keeps_conflicts_and_direct_consumers_only():
    payload = resolution()
    duplicate = deepcopy(payload["definitions"][0])
    duplicate.update(definition_id="D2", symbol="x", variable_references=["V2"])
    unrelated = deepcopy(payload["definitions"][0])
    unrelated.update(definition_id="D3", symbol="z", variable_references=["V3"])
    payload["definitions"].extend([duplicate, unrelated])
    payload["model_relations"] = [
        {"relation_id": "R2", "depends_on": ["D2"], "symbol_references": ["x"]},
        {"relation_id": "R3", "depends_on": ["D3"], "symbol_references": ["z"]},
    ]

    scope = reconciliation_record_scope(payload)

    assert [item["definition_id"] for item in scope["payload"]["definitions"]] == ["D1", "D2"]
    assert [item["relation_id"] for item in scope["payload"]["model_relations"]] == ["R2"]
    assert scope["direct_consumer_ids"] == ["R2"]
    assert scope["omitted_definition_count"] == 1


def test_scoped_symbol_rename_updates_consumers_and_preserves_sources():
    payload = resolution()
    payload["definitions"][0]["source_refs"] = [{"card_id": "EC1", "locator": "Eq 1", "quote": "x source"}]
    duplicate = deepcopy(payload["definitions"][0])
    duplicate.update(definition_id="D2", variable_references=["V2"], source_refs=[])
    payload["definitions"].append(duplicate)
    payload["model_relations"] = [{
        "relation_id": "R2", "statement": "x > 0", "expression_latex": "x > 0",
        "formal_expression": {"op": "gt", "args": [{"symbol": "x"}, {"number": "0"}]},
        "depends_on": ["D2"], "symbol_references": ["x"], "variable_references": ["V2"],
        "status": "candidate_formalization", "origin": "modeling_convention", "source_refs": [],
        "scope": "A second quantity", "conditions": [], "condition_expressions": [],
        "selection_reason": "Second quantity has an independent domain",
    }]
    repaired = apply_definition_reconciliation(payload, {
        "symbol_renames": [{"definition_id": "D2", "symbol": "y", "affected_ids": ["R2"]}],
    })
    assert repaired["definitions"][0] == payload["definitions"][0]
    assert repaired["definitions"][1]["symbol"] == "y"
    assert repaired["model_relations"][0]["formal_expression"]["args"][0] == {"symbol": "y"}
    assert repaired["model_relations"][0]["symbol_references"] == ["y"]
    assert repaired["model_relations"][0]["statement"] == "y > 0"
    assert payload["definitions"][1]["symbol"] == "x"
    assert repaired["reconciliation_audit"][0]["changes"]


def test_equivalent_definition_merge_redirects_dependencies_without_losing_provenance():
    payload = resolution()
    duplicate = deepcopy(payload["definitions"][0])
    duplicate.update(definition_id="D2", symbol="y", variable_references=["V2"],
                     source_refs=[{"card_id": "EC2", "locator": "Definition 2"}])
    consumer = deepcopy(payload["definitions"][0])
    consumer.update(definition_id="D3", symbol="z", variable_references=["V3"],
                    object_kind="derived", formal_expression={"symbol": "y"},
                    expression_latex="z = y", depends_on=["D2"], symbol_references=["y"])
    payload["definitions"].extend([duplicate, consumer])
    repaired = apply_definition_reconciliation(payload, {
        "merges": [{"retained_id": "D1", "merged_ids": ["D2"]}],
    })
    assert [record["definition_id"] for record in repaired["definitions"]] == ["D1", "D3"]
    assert repaired["definitions"][0]["variable_references"] == ["V1", "V2"]
    assert repaired["definitions"][0]["source_refs"] == duplicate["source_refs"]
    assert repaired["definitions"][1]["depends_on"] == ["D1"]
    assert repaired["definitions"][1]["formal_expression"] == {"symbol": "x"}


def test_resolver_repairs_single_group_symbol_conflict_before_recovery():
    calls = []

    def callback(prompt, **_kwargs):
        inputs = json.loads(prompt.split("INPUT_JSON:\n", 1)[1])
        calls.append(inputs)
        if "candidate_catalog" in inputs:
            return {"issues": [], "symbol_renames": [
                {"definition_id": "D2", "symbol": "y", "affected_ids": []},
            ]}
        result = resolution()
        duplicate = deepcopy(result["definitions"][0])
        duplicate.update(definition_id="D2", variable_references=["V2"])
        result["definitions"].append(duplicate)
        return result

    resolved = FormalDefinitionResolver().resolve(
        {}, {}, {"variables": [{"variable_id": "V1"}, {"variable_id": "V2"}]}, {},
        llm_call=callback, settings={"max_supplement_rounds": 0},
    )
    assert len(calls) == 3
    assert [record["symbol"] for record in resolved["definitions"]] == ["x", "y"]
    assert all(record["definition_status"] == "specified" for record in resolved["definitions"])
    assert not resolved["unknown_items"]


def test_proof_generation_completes_model_without_evidence_and_adds_supporting_records():
    plan = formal_plan()
    incomplete = deepcopy(plan["definitions"][0])
    incomplete.update(definition_status="unresolved", verification_readiness="blocked", origin="unresolved")
    inputs = {"definitions": [incomplete], "model_relations": [], "unknown_items": []}

    def callback(prompt, **_kwargs):
        request = json.loads(prompt.split("INPUT_JSON:\n", 1)[1])
        assert request["proof_policy"]["evidence_role"] == "reference"
        if "skeleton stage" in prompt:
            result = deepcopy(plan)
            result["definitions"] = []
            result["proof_attempts"] = []
            return result
        extra = deepcopy(plan["definitions"][0])
        extra.update(definition_id="D2", symbol="y", variable_references=[])
        assumption = deepcopy(plan["assumptions"][0])
        assumption.update(assumption_id="A2", selection_reason="An explicit modeling assumption")
        attempt = deepcopy(plan["proof_attempts"][0])
        attempt["steps"][0].update(rule_or_lemma="A general mathematical argument", premises=["A1", "D2", "A2"])
        return {"target_results": [{
            "target_id": "P1", "definitions": [deepcopy(plan["definitions"][0]), extra],
            "assumptions": [assumption], "proof_attempts": [attempt],
        }]}

    generated = FormalReasoningPlanner().plan(
        {}, {}, {"variables": [{"variable_id": "V1"}]}, formal_inputs=inputs,
        evidence_bundle={}, llm_call=callback,
    )
    assert generated["definitions"][0]["definition_status"] == "specified"
    assert len(generated["definitions"]) == 2
    assert len(generated["assumptions"]) == 2
    assert generated["proof_attempts"][0]["steps"][0]["premises"] == ["A1", "D2", "A2"]
    assert validate_formal_plan_v2(generated, {"variables": [{"variable_id": "V1"}]}) == []
    assert not any(blocker.startswith("undefined:") for blocker in build_verification_task(generated, "P1", "z3")["blockers"])


def test_proof_shape_normalization_preserves_free_form_rule():
    plan = formal_plan()
    plan["proof_attempts"] = []
    plan = recover_formal_plan(plan)
    FormalReasoningPlanner._merge_target_response(plan, {"target_results": [{
        "target_id": "P1", "proof_attempts": {
            "steps": {"first": {"statement": "x >= 0", "rule": "Convex analysis", "premises": ["A1"]}},
        },
    }]}, {"P1"})
    recovered = recover_formal_plan(plan)
    step = recovered["proof_attempts"][0]["steps"][0]
    assert step["derived_statement"] == "x >= 0"
    assert step["rule_or_lemma"] == "Convex analysis"
    assert validate_formal_plan_v2(recovered) == []


def test_missing_literature_relation_can_be_completed_as_a_symbolic_model():
    calls = []

    def callback(prompt, **_kwargs):
        request = json.loads(prompt.split("INPUT_JSON:\n", 1)[1])
        assert request["evidence_cards"] == []
        assert "construct a useful candidate" in prompt
        calls.append(request)
        result = resolution()
        result["model_relations"] = [{
            "relation_id": "G1_R2", "statement": "A proposed symbolic crossover condition",
            "expression_latex": "x > 0", "formal_expression": {"op": "gt", "args": [{"symbol": "x"}, {"number": "0"}]},
            "depends_on": ["D1"], "symbol_references": ["x"], "variable_references": ["V1"],
            "status": "candidate_formalization", "origin": "modeling_convention", "source_refs": [],
            "scope": "The explicitly proposed cost model", "conditions": [], "condition_expressions": [],
            "selection_reason": "Constructed from the model without requiring a literature threshold",
        }]
        if len(calls) == 1:
            result["model_relations"][0].update(status="unresolved", origin="unresolved", formal_expression=None)
        return result

    resolved = FormalDefinitionResolver().resolve(
        {}, {}, {"variables": [{"variable_id": "V1"}]}, {}, llm_call=callback,
        settings={"max_supplement_rounds": 1},
    )
    assert len(calls) == 2
    assert resolved["model_relations"][0]["status"] == "candidate_formalization"
    assert resolved["model_relations"][0]["origin"] == "modeling_convention"
    assert resolved["model_relations"][0]["source_refs"] == []


def test_symbol_repair_updates_existing_proof_steps_and_target_ast():
    plan = recover_formal_plan(formal_plan())
    renamed = apply_definition_reconciliation(plan, {
        "symbol_renames": [{"definition_id": "D1", "symbol": "y", "affected_ids": ["A1", "P1", "S1"]}],
    })
    assert renamed["propositions"][0]["quantifiers"][0]["symbol"] == "y"
    assert renamed["propositions"][0]["conclusion_expression"]["args"][0] == {"symbol": "y"}
    assert renamed["proof_attempts"][0]["steps"][0]["derived_statement"] == "y >= 0"
    assert renamed["assumptions"][0]["predicate_expression"]["args"][0] == {"symbol": "y"}
    assert validate_formal_plan_v2(renamed) == []


def test_repeated_supporting_definition_reuses_canonical_id_and_updates_proof():
    plan = recover_formal_plan(formal_plan())
    plan["proof_attempts"] = []
    repeated = deepcopy(plan["definitions"][0])
    repeated["definition_id"] = "D_copy"
    plan["reconciliation_audit"] = [{"before": {"depends_on": ["D_copy"]}}]
    plan["definitions"][0]["completion_audit"] = {"before": {"depends_on": ["D_copy"]}}
    attempt = deepcopy(formal_plan()["proof_attempts"][0])
    attempt["steps"][0]["premises"].append("D_copy")
    FormalReasoningPlanner._merge_target_response(plan, {"target_results": [{
        "target_id": "P1", "definitions": [repeated], "proof_attempts": [attempt],
    }]}, {"P1"})
    assert len(plan["definitions"]) == 1
    assert plan["proof_attempts"][0]["steps"][0]["premises"] == ["A1", "D1"]
    assert attempt["steps"][0]["premises"] == ["A1", "D_copy"]
    assert plan["reconciliation_audit"][0]["before"]["depends_on"] == ["D_copy"]
    assert plan["definitions"][0]["completion_audit"]["before"]["depends_on"] == ["D_copy"]


def test_scoped_step_rename_does_not_overwrite_another_attempt_with_same_step_id():
    plan = recover_formal_plan(formal_plan())
    first_attempt = plan["proof_attempts"][0]
    second_attempt = deepcopy(first_attempt)
    second_attempt["attempt_id"] = "PR2"
    second_attempt["steps"][0]["derived_statement"] = "x > 0"
    plan["proof_attempts"].append(second_attempt)
    renamed = apply_definition_reconciliation(plan, {"symbol_renames": [{
        "definition_id": "D1", "symbol": "y", "affected_ids": ["PR1/S1"],
    }]})
    assert renamed["proof_attempts"][0]["steps"][0]["derived_statement"] == "y >= 0"
    assert renamed["proof_attempts"][1] == second_attempt


def test_new_auxiliary_lemma_keeps_its_own_proof_attempt():
    plan = recover_formal_plan(formal_plan())
    lemma = deepcopy(plan["propositions"][0])
    lemma["lemma_id"] = "L1"
    del lemma["proposition_id"]
    attempt = deepcopy(plan["proof_attempts"][0])
    attempt.update(attempt_id="PR_L1", target_id="L1")
    attempt["steps"][0].update(
        step_id="S_L1", rule_or_lemma="order_weakening",
        derived_expression=deepcopy(lemma["conclusion_expression"]),
    )
    attempt["final_step_id"] = "S_L1"
    FormalReasoningPlanner._merge_target_response(plan, {"target_results": [{
        "target_id": "P1", "lemmas": [lemma], "proof_attempts": [attempt],
    }]}, {"P1"})
    recovered = recover_formal_plan(plan)
    assert recovered["lemmas"][0]["lemma_id"] == "L1"
    accepted = next(item for item in recovered["proof_attempts"] if item["target_id"] == "L1")
    assert verify_proof_attempt(recovered, accepted)["result"] == "passed"


def test_failed_symbol_repair_keeps_explicit_diagnostic_and_candidates():
    plan = recover_formal_plan(formal_plan())
    duplicate = deepcopy(plan["definitions"][0])
    duplicate["definition_id"] = "D2"
    plan["definitions"].append(duplicate)
    repaired = repair_plan_symbol_conflicts(plan, {}, llm_call=lambda *_args, **_kwargs: {})
    assert len(repaired["definitions"]) == 2
    assert "unresolved conflicts" in repaired["unknown_items"][0]["reason"]


def test_cyclic_definitions_survive_and_still_cannot_prove_target():
    payload = resolution()
    payload["definitions"][0]["depends_on"] = ["D1"]
    resolved = FormalDefinitionResolver._merge(payload)
    assert resolved["definitions"][0]["definition_status"] == "specified"
    assert resolved["definitions"][0]["dependency_health"] == "cyclic"
    plan = formal_plan()
    plan["definitions"] = resolved["definitions"]
    recovered = recover_formal_plan(plan)
    assert recovered["definitions"][0]["definition_id"] == "D1"
    report = verify_formal_plan(recovered, {"enabled": True, "backends": ["sympy"]})
    assert all(result["result"] != "passed" for result in report["results"])
    circular = formal_plan()
    circular["proof_attempts"][0]["steps"][0]["premises"] = ["P1"]
    circular["proof_attempts"][0]["steps"][0]["derived_expression"] = circular["propositions"][0]["conclusion_expression"]
    assert verify_proof_attempt(circular, circular["proof_attempts"][0])["limitations"] == ["circular_proof_premise:P1"]


@pytest.mark.parametrize("health", ["cyclic", "missing", "invalid_or_blocked", "blocked_by_dependency"])
@pytest.mark.parametrize("record_id", ["D1", "P1"])
def test_direct_proof_check_rejects_unready_target_or_definition(health, record_id):
    plan = formal_plan()
    definition = plan["definitions"][0]
    definition["formal_expression"] = {"number": "1"}
    conclusion = {"op": "eq", "args": [{"symbol": "x"}, {"number": "1"}]}
    plan["propositions"][0]["conclusion_expression"] = conclusion
    attempt = plan["proof_attempts"][0]
    attempt["steps"][0].update(
        premises=["D1"], derived_expression=conclusion, rule_or_lemma="definition_unfolding",
    )
    assert verify_proof_attempt(plan, attempt)["result"] == "passed"
    record = definition if record_id == "D1" else plan["propositions"][0]
    record["dependency_health"] = health
    checked = verify_proof_attempt(plan, attempt)
    assert checked["result"] == "unknown"
    assert checked["limitations"] == [f"dependency_not_ready:{record_id}"]


@pytest.mark.parametrize("patch", [
    {"repairs": [{"record_id": "D1", "fields": {"definition_id": "D2"}}]},
    {"symbol_renames": [{"definition_id": "D1", "symbol": "y", "affected_ids": ["missing"]}]},
    {"merges": [{"retained_id": "D1", "merged_ids": ["D1"]}]},
])
def test_invalid_reconciliation_is_transactional(patch):
    payload = resolution()
    original = deepcopy(payload)
    with pytest.raises(ValueError):
        apply_definition_reconciliation(payload, patch)
    assert payload == original
