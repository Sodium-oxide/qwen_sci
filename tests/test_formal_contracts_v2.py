from copy import deepcopy

from src.agents.experiment_design_agent.formal_contracts import adapt_legacy_plan, validate_formal_plan_v2
from src.agents.experiment_design_agent.formal_definition_resolver import FormalDefinitionResolver
from src.agents.experiment_design_agent.formal_reasoning_planner import FormalReasoningPlanner


def formal_plan():
    return {
        "schema_version": "formal_reasoning_plan_v2", "revision": 1,
        "applicability": "formal_theory", "status": "unverified",
        "definitions": [{
            "definition_id": "D1", "symbol": "x", "statement": "A real scalar", "object_kind": "primitive",
            "expression_latex": "x \\in \\mathbb R", "formal_expression": None,
            "domain": "R", "codomain": "R", "unit": "dimensionless", "conditions": [],
            "condition_expressions": [], "depends_on": [], "symbol_references": [], "variable_references": ["V1"],
            "origin": "modeling_convention", "source_refs": [], "selection_reason": "Study a real scalar",
            "definition_status": "specified", "verification_readiness": "encoded",
        }],
        "model_relations": [],
        "assumptions": [{"assumption_id": "A1", "statement": "Positive scalar", "predicate": "x > 0", "predicate_expression": {"op": "gt", "args": [{"symbol": "x"}, {"number": "0"}]}, "status": "candidate_formalization", "symbol_references": ["x"]}],
        "propositions": [{
            "proposition_id": "P1", "statement": "A positive real is nonnegative", "premises": ["A1"],
            "conclusion": "x >= 0", "scope": "real scalars", "status": "candidate_formalization",
            "quantifiers": [{"symbol": "x", "sort": "real", "quantifier": "forall"}],
            "domain_expression": {"bool": True}, "conclusion_expression": {"op": "ge", "args": [{"symbol": "x"}, {"number": "0"}]},
            "required_obligation_ids": [], "symbol_references": ["x"],
        }],
        "lemmas": [], "proof_obligations": [],
        "proof_attempts": [{"attempt_id": "PR1", "target_id": "P1", "steps": [{"step_id": "S1", "premises": ["A1"], "derived_statement": "x >= 0", "rule_or_lemma": "Strict order implies weak order", "symbol_references": ["x"], "status": "proposed"}], "final_step_id": "S1"}],
        "global_assumption_ids": [], "unknown_items": [], "semantic_diagnostics": [],
    }


def test_v2_accepts_explicit_definitions_and_proof_draft():
    assert validate_formal_plan_v2(formal_plan(), {"variables": [{"variable_id": "V1"}]}) == []


def test_definition_and_dependency_failures():
    plan = formal_plan()
    plan["definitions"][0]["unit"] = ""
    assert any("specified_requires:unit" in error for error in validate_formal_plan_v2(plan))
    plan = formal_plan()
    plan["assumptions"][0]["depends_on"] = ["P1"]
    assert any("cycle" in error for error in validate_formal_plan_v2(plan))
    plan = formal_plan()
    plan["proof_attempts"][0]["steps"][0]["premises"] = ["P1"]
    assert any("circular_proof" in error for error in validate_formal_plan_v2(plan))
    plan = formal_plan()
    plan["propositions"][0]["quantifiers"] = ["bad"]
    assert any("invalid_quantifiers" in error for error in validate_formal_plan_v2(plan))
    plan = formal_plan()
    plan["propositions"][0]["required_obligation_ids"] = "PO1"
    assert any("invalid_required_obligation_ids" in error for error in validate_formal_plan_v2(plan))


def test_target_association_is_not_a_proof_premise():
    plan = formal_plan()
    plan["proof_obligations"] = [{"obligation_id": "PO1", "target_id": "P1", "target": "Prove order implication", "status": "unresolved", "premises": ["A1"]}]
    plan["propositions"][0]["required_obligation_ids"] = ["PO1"]
    assert validate_formal_plan_v2(plan) == []
    plan["proof_attempts"][0]["steps"][0]["premises"] = ["PO1"]
    assert any("cannot_use_unresolved_obligation" in error for error in validate_formal_plan_v2(plan))


def test_legacy_adaptation_does_not_fabricate_definitions_or_proofs():
    legacy = {"schema_version": "formal_reasoning_plan_v1", "definitions": [{"definition_id": "D1", "symbol": "x", "statement": "Some quantity"}], "propositions": [], "status": "unverified"}
    converted = adapt_legacy_plan(legacy)
    assert converted["definitions"][0]["formal_expression"] is None
    assert converted["definitions"][0]["definition_status"] == "unresolved"
    assert converted["proof_attempts"] == []
    assert legacy["schema_version"] == "formal_reasoning_plan_v1"


def test_resolver_and_planner_preserve_resolved_science():
    plan = formal_plan()
    resolution = {"schema_version": "formal_definition_resolution_v1", "definitions": plan["definitions"], "model_relations": [], "unknown_items": []}
    resolved = FormalDefinitionResolver().resolve({}, {}, {"variables": [{"variable_id": "V1"}]}, {}, llm_call=lambda *_args, **_kwargs: deepcopy(resolution))
    changed = deepcopy(plan)
    changed["definitions"][0]["statement"] = "Unapproved replacement"
    generated = FormalReasoningPlanner().plan({}, {}, {"variables": [{"variable_id": "V1"}]}, formal_inputs=resolved, llm_call=lambda *_args, **_kwargs: changed)
    assert generated["definitions"] == resolved["definitions"]


def test_resolver_rejects_fabricated_source():
    import pytest

    plan = formal_plan()
    plan["definitions"][0].update(origin="source_grounded", source_refs=[{"card_id": "missing", "locator": "Eq 1", "quote": "a formula"}])
    with pytest.raises(ValueError, match="not_grounded"):
        FormalDefinitionResolver().resolve({}, {}, {"variables": []}, {}, llm_call=lambda *_args, **_kwargs: {"schema_version": "formal_definition_resolution_v1", "definitions": plan["definitions"], "model_relations": [], "unknown_items": []})


def test_invalid_target_does_not_discard_independent_proof():
    from src.agents.experiment_design_agent.formal_contracts import retain_independent_targets

    plan = formal_plan()
    invalid = deepcopy(plan["propositions"][0])
    invalid.update(proposition_id="P2", quantifiers=["bad"])
    plan["propositions"].append(invalid)
    retained, errors = retain_independent_targets(plan)
    assert errors == []
    assert [target["proposition_id"] for target in retained["propositions"]] == ["P1"]
    assert retained["proof_attempts"] == plan["proof_attempts"]
    assert retained["definitions"] == plan["definitions"]
    assert retained["unknown_items"][-1]["field_path"] == "rejected_targets.P2"


def test_scientific_revision_cannot_forge_a_source():
    import pytest
    from src.agents.experiment_design_agent.formal_revision import apply_semantic_revision

    plan = formal_plan()
    definition = deepcopy(plan["definitions"][0])
    definition.update(origin="source_grounded", source_refs=[{"card_id": "invented", "locator": "Eq. 1", "quote": "fake"}])
    with pytest.raises(ValueError, match="definition_source_not_grounded"):
        apply_semantic_revision(plan, {"schema_version": "formal_revision_patch_v1", "reason": "Claim a source", "replacements": [{"collection": "definitions", "record": definition}]}, {"D1"})
