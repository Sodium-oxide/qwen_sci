from copy import deepcopy
import json
from threading import Barrier, Event, Lock
from time import sleep

import pytest

from src.agents.experiment_design_agent.formal_contracts import adapt_legacy_plan, validate_formal_plan_v2
from src.agents.experiment_design_agent.formal_definition_resolver import FormalDefinitionResolver
from src.agents.experiment_design_agent.formal_reasoning_planner import FormalReasoningPlanner, _repair_skeleton_record_ids


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


def test_unresolved_definition_keeps_symbol_gap_without_invalidating_plan():
    plan = formal_plan()
    plan["definitions"][0].update(
        definition_status="unresolved", verification_readiness="blocked",
        symbol_references=["missing"],
    )
    plan["assumptions"] = []
    plan["propositions"] = []
    plan["proof_attempts"] = []

    assert validate_formal_plan_v2(plan, {"variables": [{"variable_id": "V1"}]}) == []
    plan["definitions"][0].update(definition_status="specified", verification_readiness="encoded")
    assert "D1_undefined_symbol:missing" in validate_formal_plan_v2(plan, {"variables": [{"variable_id": "V1"}]})


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


def test_planner_builds_skeleton_then_target_proof_batches():
    plan = formal_plan()
    unrelated_definition = deepcopy(plan["definitions"][0])
    unrelated_definition.update(definition_id="D2", symbol="y", variable_references=[])
    plan["definitions"].append(unrelated_definition)
    plan["forward_derivation"] = {
        "steps": [{
            "step_id": "S_P1_1", "premises": ["A1"], "symbol_references": ["x"],
            "variable_references": ["V1"], "rule_or_lemma": "Order implication",
            "derived_statement": "x >= 0", "status": "proposed",
        }],
        "target_proposition_id": "P1", "final_conclusion_step": "S_P1_1",
        "final_conclusion": "x >= 0", "status": "unverified",
    }
    resolution = {
        "schema_version": "formal_definition_resolution_v1",
        "definitions": plan["definitions"],
        "model_relations": [],
        "unknown_items": [],
    }
    calls = []

    def callback(prompt, **kwargs):
        if "skeleton stage" in prompt:
            calls.append("v2_skeleton")
            skeleton = deepcopy(plan)
            skeleton["proof_attempts"] = []
            skeleton["forward_derivation"]["steps"] = []
            skeleton["forward_derivation"]["final_conclusion_step"] = ""
            skeleton["forward_derivation"]["status"] = "unresolved"
            return skeleton
        calls.append("v2_target_proof")
        target_input = json.loads(prompt.split("INPUT_JSON:\n", 1)[1])
        assert [item["definition_id"] for item in target_input["skeleton"]["definitions"]] == ["D1"]
        return {
            "target_results": [{
                "target_id": "P1",
                "proof_obligations": [],
                "proof_attempts": deepcopy(plan["proof_attempts"]),
                "derivation_steps": deepcopy(plan["forward_derivation"]["steps"]),
                "status": "unverified",
            }],
            "semantic_diagnostics": [],
            "unknown_items": [],
        }

    generated = FormalReasoningPlanner().plan(
        {}, {}, {"variables": [{"variable_id": "V1"}]},
        formal_inputs=resolution, llm_call=callback,
        planner_settings={"max_targets_per_request": 2, "max_evidence_cards": 4},
    )
    assert calls == ["v2_skeleton", "v2_target_proof"]
    assert generated["proof_attempts"]
    assert generated["forward_derivation"]["steps"]


def test_skeleton_prompt_omits_large_provenance_and_restores_full_records():
    plan = formal_plan()
    definitions = []
    for number in range(1, 41):
        definition = deepcopy(plan["definitions"][0])
        definition.update(
            definition_id=f"D{number}", symbol=f"symbol{number}",
            statement="Blocked modeling description. " * 80,
            conditions=["Unavailable scientific condition. " * 30],
            source_refs=[{"card_id": f"EC{number}", "locator": "Eq 1", "quote": "PROVENANCE_ONLY " * 100}],
            definition_status="unresolved", verification_readiness="blocked",
            symbol_references=["missing"] if number == 1 else [],
        )
        definitions.append(definition)
    resolved = {"definitions": definitions, "model_relations": [], "unknown_items": []}
    prompts = []

    def callback(prompt, **_kwargs):
        prompts.append(prompt)
        return {"definitions": [], "model_relations": [], "propositions": [], "lemmas": []}

    generated = FormalReasoningPlanner().plan(
        {"source": "PROVENANCE_ONLY " * 1000},
        {"source_anchors": ["PROVENANCE_ONLY " * 1000]},
        {"variables": [{"variable_id": "V1"}]},
        formal_inputs=resolved,
        evidence_bundle={"evidence_cards": [{"card_id": "EC1", "source_id": "paper1", "statement": "Normal evidence", "evidence_excerpt": "PROVENANCE_ONLY " * 1000}]},
        llm_call=callback,
    )

    assert len(prompts) == 1
    assert len(prompts[0]) < 70000
    assert "PROVENANCE_ONLY" not in prompts[0]
    assert generated["definitions"] == definitions


def test_large_skeleton_prompt_reaches_llm():
    plan = formal_plan()
    prompts = []

    def callback(prompt, **_kwargs):
        prompts.append(prompt)
        return {"definitions": [], "model_relations": [], "propositions": [], "lemmas": []}

    generated = FormalReasoningPlanner().plan(
        {"topic": "x" * 130000}, {}, {"variables": [{"variable_id": "V1"}]},
        formal_inputs={"definitions": plan["definitions"], "model_relations": [], "unknown_items": []},
        llm_call=callback,
    )

    assert len(prompts) == 1
    assert len(prompts[0]) > 120000
    assert generated["definitions"] == plan["definitions"]


def test_skeleton_normalizes_unambiguous_ids_and_safe_statuses():
    source = formal_plan()
    skeleton = deepcopy(source)
    skeleton["proof_attempts"] = []
    skeleton["assumptions"][0]["id"] = skeleton["assumptions"][0].pop("assumption_id")
    del skeleton["assumptions"][0]["status"]
    skeleton["propositions"][0]["required_obligation_ids"] = ["PO1"]
    skeleton["proof_obligations"] = [{
        "proof_obligation_id": "PO1", "target_id": "P1", "target": "Check the order implication",
        "premises": ["A1"], "conclusion_expression": None, "symbol_references": ["x"],
    }]
    calls = []

    def callback(prompt, **_kwargs):
        calls.append(prompt)
        if "skeleton stage" in prompt:
            return deepcopy(skeleton)
        return {"target_results": [{"target_id": "P1"}]}

    generated = FormalReasoningPlanner().plan(
        {}, {}, {"variables": [{"variable_id": "V1"}]},
        formal_inputs={"definitions": source["definitions"], "model_relations": [], "unknown_items": []},
        llm_call=callback,
    )

    assert len(calls) == 2
    assert generated["assumptions"][0]["assumption_id"] == "A1"
    assert generated["assumptions"][0]["status"] == "candidate_formalization"
    assert generated["proof_obligations"][0]["obligation_id"] == "PO1"
    assert generated["proof_obligations"][0]["status"] == "unresolved"


def test_skeleton_repairs_missing_ids_with_one_small_request():
    source = formal_plan()
    skeleton = deepcopy(source)
    skeleton["proof_attempts"] = []
    del skeleton["assumptions"][0]["assumption_id"]
    skeleton["propositions"][0]["required_obligation_ids"] = ["PO1"]
    skeleton["proof_obligations"] = [{
        "target_id": "P1", "target": "Check the order implication",
        "premises": ["A1"], "conclusion_expression": None,
        "symbol_references": ["x"], "status": "unresolved",
    }]
    calls = []

    def callback(prompt, **_kwargs):
        calls.append(prompt)
        if "skeleton stage" in prompt:
            return deepcopy(skeleton)
        if "Repair only record identifiers" in prompt:
            payload = json.loads(prompt.split("INPUT_JSON:\n", 1)[1])
            assert len(payload["records"]) == 2
            assert [item["required_obligation_ids"] for item in payload["references"]] == [["PO1"]]
            return {"repairs": [
                {"collection": "assumptions", "index": 0, "identifier": "A1"},
                {"collection": "proof_obligations", "index": 0, "identifier": "PO1"},
            ]}
        return {"target_results": [{"target_id": "P1"}]}

    generated = FormalReasoningPlanner().plan(
        {}, {}, {"variables": [{"variable_id": "V1"}]},
        formal_inputs={"definitions": source["definitions"], "model_relations": [], "unknown_items": []},
        llm_call=callback,
    )

    assert len(calls) == 3
    assert len(calls[1]) < len(calls[0])
    assert generated["assumptions"][0]["assumption_id"] == "A1"
    assert generated["proof_obligations"][0]["obligation_id"] == "PO1"


def test_skeleton_id_repair_rejects_wrong_target_reference():
    skeleton = formal_plan()
    del skeleton["assumptions"][0]["assumption_id"]
    skeleton["propositions"][0]["required_obligation_ids"] = ["PO1"]
    skeleton["proof_obligations"] = [{"target_id": "P1", "target": "Check the order implication"}]

    def callback(_prompt, **_kwargs):
        return {"repairs": [
            {"collection": "assumptions", "index": 0, "identifier": "A1"},
            {"collection": "proof_obligations", "index": 0, "identifier": "PO2"},
        ]}

    with pytest.raises(ValueError, match="formal_v2_skeleton_id_repair_target_mismatch"):
        _repair_skeleton_record_ids(
            skeleton, [("assumptions", 0), ("proof_obligations", 0)],
            llm_call=callback, logger=None, brief_id="",
        )
    assert "assumption_id" not in skeleton["assumptions"][0]
    assert "obligation_id" not in skeleton["proof_obligations"][0]


def test_planner_keeps_successful_target_when_later_group_fails():
    plan = formal_plan()
    second = deepcopy(plan["propositions"][0])
    second["proposition_id"] = "P2"
    plan["propositions"].append(second)
    resolution = {
        "schema_version": "formal_definition_resolution_v1",
        "definitions": plan["definitions"], "model_relations": [], "unknown_items": [],
    }

    def callback(prompt, **_kwargs):
        if "skeleton stage" in prompt:
            skeleton = deepcopy(plan)
            skeleton["proof_attempts"] = []
            return skeleton
        if json.loads(prompt.split("INPUT_JSON:\n", 1)[1])["target_group_number"] == 1:
            return {"target_results": [{"target_id": "P1", "proof_attempts": deepcopy(plan["proof_attempts"])}]}
        raise RuntimeError("target P2 backend timeout")

    generated = FormalReasoningPlanner().plan(
        {}, {}, {"variables": [{"variable_id": "V1"}]},
        formal_inputs=resolution, llm_call=callback,
        planner_settings={"max_targets_per_request": 1},
    )
    assert [item["proposition_id"] for item in generated["propositions"]] == ["P1", "P2"]
    assert generated["proof_attempts"][0]["target_id"] == "P1"
    assert generated["status"] == "requires_human_review"
    assert any(item["field_path"] == "proof_attempts.P2" and "backend timeout" in item["reason"] for item in generated["unknown_items"])


def test_planner_proof_groups_run_three_at_a_time():
    plan = formal_plan()
    plan["propositions"] = [
        {**deepcopy(plan["propositions"][0]), "proposition_id": f"P{number}"}
        for number in range(1, 5)
    ]
    resolved = {"definitions": plan["definitions"], "model_relations": [], "unknown_items": []}
    barrier = Barrier(3)
    lock = Lock()
    active = 0
    max_active = 0

    def callback(prompt, **_kwargs):
        nonlocal active, max_active
        if "skeleton stage" in prompt:
            return deepcopy(plan)
        target_group = json.loads(prompt.split("INPUT_JSON:\n", 1)[1])["target_group_number"]
        with lock:
            active += 1
            max_active = max(max_active, active)
        try:
            if target_group <= 3:
                barrier.wait(timeout=5)
            sleep(0.02)
            return {"target_results": [{"target_id": f"P{target_group}"}]}
        finally:
            with lock:
                active -= 1

    generated = FormalReasoningPlanner()._plan_v2_two_stage(
        {}, {}, {"variables": [{"variable_id": "V1"}]}, resolved, {},
        llm_call=callback, logger=None, brief_id="",
        planner_settings={"max_targets_per_request": 1, "parallel_workers": 10},
    )

    assert max_active == 3
    assert [item["proposition_id"] for item in generated["propositions"]] == ["P1", "P2", "P3", "P4"]


def test_planner_waits_for_prerequisite_proof_group():
    plan = formal_plan()
    plan["propositions"] = [
        {**deepcopy(plan["propositions"][0]), "proposition_id": f"P{number}"}
        for number in range(1, 4)
    ]
    plan["propositions"][1]["premises"] = ["P1"]
    resolved = {"definitions": plan["definitions"], "model_relations": [], "unknown_items": []}
    first_done = Event()

    def callback(prompt, **_kwargs):
        if "skeleton stage" in prompt:
            return deepcopy(plan)
        target_group = json.loads(prompt.split("INPUT_JSON:\n", 1)[1])["target_group_number"]
        if target_group == 1:
            sleep(0.05)
            first_done.set()
        if target_group == 2:
            assert first_done.is_set()
        return {"target_results": [{"target_id": f"P{target_group}"}]}

    generated = FormalReasoningPlanner()._plan_v2_two_stage(
        {}, {}, {"variables": [{"variable_id": "V1"}]}, resolved, {},
        llm_call=callback, logger=None, brief_id="",
        planner_settings={"max_targets_per_request": 1},
    )

    assert generated["status"] == "unverified"


def test_resolver_preserves_uncatalogued_source_reference():
    plan = formal_plan()
    plan["definitions"][0].update(origin="source_grounded", source_refs=[{"card_id": "missing", "locator": "Eq 1", "quote": "a formula"}])
    resolved = FormalDefinitionResolver().resolve(
        {}, {}, {"variables": []}, {},
        llm_call=lambda *_args, **_kwargs: {"schema_version": "formal_definition_resolution_v1", "definitions": plan["definitions"], "model_relations": [], "unknown_items": []},
    )
    assert resolved["definitions"][0]["source_refs"][0]["card_id"] == "missing"


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


def test_scientific_revision_preserves_uncatalogued_source_reference():
    from src.agents.experiment_design_agent.formal_revision import apply_semantic_revision

    plan = formal_plan()
    definition = deepcopy(plan["definitions"][0])
    definition.update(origin="source_grounded", source_refs=[{"card_id": "uncatalogued", "locator": "Eq. 1", "quote": "Unverified citation"}])
    revised, audit = apply_semantic_revision(
        plan,
        {"schema_version": "formal_revision_patch_v1", "reason": "Add a citation", "replacements": [{"collection": "definitions", "record": definition}]},
        {"D1"},
    )
    assert revised["definitions"][0]["source_refs"][0]["card_id"] == "uncatalogued"
    assert audit["status"] == "revised"
