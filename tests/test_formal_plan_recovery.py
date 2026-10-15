from copy import deepcopy
import json

import pytest

from test_formal_contracts_v2 import formal_plan
from src.agents.experiment_design_agent.formal_contracts import validate_formal_plan_v2
from src.agents.experiment_design_agent.formal_plan_recovery import (
    normalize_variable_dependencies, recover_counterexample_analysis, recover_formal_plan,
)
from src.agents.experiment_design_agent.formal_reasoning_planner import FormalReasoningPlanner
from src.agents.experiment_design_agent.formal_verification import build_verification_task, verify_formal_plan
from src.agents.experiment_design_agent.reasoning_validation import validate_counterexample_analysis
from src.agents.experiment_design_agent.run_logging import ExperimentDesignRunLogger


VARIABLES = {"variables": [{"variable_id": "V1"}]}


def encoded_relation(**fields):
    relation = {"relation_id": "R1", "statement": "The scalar is positive", "expression_latex": "x > 0",
                "formal_expression": {"op": "gt", "args": [{"symbol": "x"}, {"number": "0"}]},
                "scope": "real scalars", "origin": "modeling_convention", "source_refs": [],
                "conditions": [], "condition_expressions": [], "selection_reason": "Study a positive scalar",
                "depends_on": ["D1"], "symbol_references": ["x"], "variable_references": ["V1"],
                "status": "candidate_formalization"}
    relation.update(fields)
    return relation


def test_relation_metadata_normalization_preserves_math_and_executes_backend():
    plan = formal_plan()
    original = encoded_relation(origin="source_grounded", source_refs="EC1",
                                depends_on={"definition_id": "D1"},
                                symbol_references={"symbol": "x"}, variable_references="V1")
    plan["model_relations"] = [original]
    plan["propositions"][0]["premises"] = ["R1"]

    generated = recover_formal_plan(plan, VARIABLES)
    relation = generated["model_relations"][0]
    assert relation["formal_expression"] == original["formal_expression"]
    assert relation["expression_latex"] == original["expression_latex"]
    assert relation["depends_on"] == ["D1"]
    assert relation["source_refs"] == [{"card_id": "EC1"}]
    assert json.loads(relation["format_originals"]["source_refs"]) == "EC1"
    assert relation["origin"] == "unresolved"
    assert relation["status"] == "candidate_formalization"
    assert generated["status"] == "unverified"
    assert not any(record.get("dependency_health") for record in [relation, generated["propositions"][0]])
    assert build_verification_task(generated, "P1", "z3")["blockers"] == []
    report = verify_formal_plan(generated, {"enabled": True, "backends": ["z3"], "timeout_seconds": 10})
    summary = report["target_summaries"][0]
    assert summary["status"] == "verified_in_declared_scope"
    assert summary["computation_results"][0]["executed"]
    assert summary["computation_results"][0]["result"] == "passed"
    assert summary["semantic_status"] == "not_reviewed"
    assert summary["encoding_diagnostic_count"] > 0
    assert recover_formal_plan(generated, VARIABLES) == generated


def test_unparseable_relation_reference_retains_draft_and_only_skips_affected_execution():
    plan = formal_plan()
    original = encoded_relation(depends_on={"unexpected": "D1"})
    plan["model_relations"] = [original]
    affected = deepcopy(plan["propositions"][0])
    affected.update(proposition_id="P2", premises=["R1"])
    plan["propositions"].append(affected)

    generated = recover_formal_plan(plan, VARIABLES)
    relation = generated["model_relations"][0]
    assert relation["statement"] == original["statement"]
    assert relation["formal_expression"] == original["formal_expression"]
    assert json.loads(relation["format_originals"]["depends_on"]) == original["depends_on"]
    assert relation["machine_encoding_issues"] == ["depends_on"]
    assert generated["status"] == "unverified"
    assert not generated["propositions"][1].get("dependency_health")
    assert build_verification_task(generated, "P1", "z3")["blockers"] == []
    assert "encoding_issue:R1:depends_on" in build_verification_task(generated, "P2", "z3")["blockers"]
    assert validate_formal_plan_v2(generated, VARIABLES) == []
    assert recover_formal_plan(generated, VARIABLES) == generated

    relation["depends_on"] = ["D1"]
    repaired = recover_formal_plan(generated, VARIABLES)
    assert not repaired["model_relations"][0].get("machine_encoding_issues")
    assert build_verification_task(repaired, "P2", "z3")["blockers"] == []


def test_invalid_relation_record_remains_in_live_list_with_full_original():
    from src.agents.experiment_design_agent.formal_definition_resolver import FormalDefinitionResolver

    original = encoded_relation(scope=None, source_refs=9)
    payload = {"schema_version": "formal_definition_resolution_v1", "definitions": [],
               "model_relations": [original], "unknown_items": []}
    retained, discarded = FormalDefinitionResolver._quarantine_invalid_records(payload, {})
    assert discarded == []
    relation = retained["model_relations"][0]
    assert relation["statement"] == original["statement"]
    assert relation["formal_expression"] == original["formal_expression"]
    assert relation["status"] == "unresolved"
    assert relation["original_record"]
    assert json.loads(relation["format_originals"]["source_refs"]) == 9


def test_uninterpretable_relation_shape_keeps_full_content_in_live_draft():
    from src.agents.experiment_design_agent.formal_definition_resolver import normalize_model_relations

    original = [{"statement": "First mathematical candidate"}, {"statement": "Second mathematical candidate"}]
    normalized, _repairs, discarded = normalize_model_relations(
        {"model_relations": [original], "unknown_items": []}, id_prefix="G1_",
    )
    assert discarded == []
    assert len(normalized["model_relations"]) == 1
    assert json.loads(normalized["model_relations"][0]["original_record"]) == original


def test_semantic_issue_and_backend_result_are_recorded_separately():
    plan = formal_plan()
    plan["semantic_diagnostics"] = [{"target_id": "P1", "reason": "Physical applicability remains to be reviewed."}]
    report = verify_formal_plan(plan, {"enabled": True, "backends": ["z3"], "timeout_seconds": 10})
    summary = report["target_summaries"][0]
    assert summary["semantic_status"] == "requires_review"
    assert summary["computation_results"][0]["executed"]
    assert summary["computation_results"][0]["result"] == "passed"
    assert summary["status"] == "unresolved"


def test_single_reference_object_and_quantifier_object_normalize_without_dependency_blocking():
    plan = formal_plan()
    target = plan["propositions"][0]
    target["premises"] = {"assumption_id": "A1"}
    target["quantifiers"] = target["quantifiers"][0]
    generated = recover_formal_plan(plan, VARIABLES)
    assert generated["propositions"][0]["premises"] == ["A1"]
    assert generated["propositions"][0]["quantifiers"] == formal_plan()["propositions"][0]["quantifiers"]
    assert build_verification_task(generated, "P1", "z3")["blockers"] == []
    assert generated["status"] == "unverified"


def test_unresolved_relation_semantics_do_not_hide_computational_result():
    plan = formal_plan()
    plan["model_relations"] = [encoded_relation(status="unresolved")]
    plan["propositions"][0]["premises"] = ["R1"]
    generated = recover_formal_plan(plan, VARIABLES)
    report = verify_formal_plan(generated, {"enabled": True, "backends": ["z3"], "timeout_seconds": 10})
    summary = report["target_summaries"][0]
    assert summary["computation_results"][0]["executed"]
    assert summary["computation_results"][0]["result"] == "passed"
    assert summary["status"] != "verified_in_declared_scope"
    assert summary["semantic_status"] == "requires_review"


def dependency_plan():
    plan = formal_plan()
    helper = deepcopy(plan["definitions"][0])
    helper.update(definition_id="D2", symbol="y", variable_references=[], depends_on=["D4"])
    cyclic = deepcopy(helper)
    cyclic.update(definition_id="D4", symbol="w")
    plan["definitions"][0]["depends_on"] = ["D4", "D2"]
    plan["definitions"].extend([helper, cyclic])
    return plan


def dependency_diagnostics(plan):
    return {item["record_id"]: item for item in plan["unknown_items"]
            if item.get("error_code") in {"unresolved_prerequisite", "cyclic_dependency"}}


def test_dependency_warnings_use_final_closure_and_do_not_repeat_or_grow_archive():
    logger = ExperimentDesignRunLogger("dependency-deltas", console_enabled=False)
    generated = recover_formal_plan(dependency_plan(), VARIABLES, logger=logger)
    diagnostics = dependency_diagnostics(generated)
    assert diagnostics["D1"]["dependency_ids"] == ["D2", "D4"]
    event_count = len(logger.records)
    snapshot = deepcopy(generated)
    generated["definitions"][0]["depends_on"].reverse()
    repeated = recover_formal_plan(generated, VARIABLES, logger=logger)

    assert len(logger.records) == event_count
    assert repeated["unknown_items"] == snapshot["unknown_items"]
    assert repeated["construction_archive"] == snapshot["construction_archive"]
    assert validate_formal_plan_v2(repeated, VARIABLES) == []


def test_dependency_warnings_report_only_new_or_changed_blockers():
    logger = ExperimentDesignRunLogger("changed-dependencies", console_enabled=False)
    generated = recover_formal_plan(dependency_plan(), VARIABLES, logger=logger)
    event_count = len(logger.records)
    additional = deepcopy(generated["definitions"][2])
    additional.update(definition_id="D3", symbol="z", depends_on=["D3"])
    generated["definitions"].append(additional)
    generated["definitions"][0]["depends_on"].append("D3")

    changed = recover_formal_plan(generated, VARIABLES, logger=logger)

    assert {item["record_id"] for item in logger.records[event_count:] if item.get("event") != "graph_profiled"} == {"D1", "D3"}
    assert dependency_diagnostics(changed)["D1"]["dependency_ids"] == ["D2", "D3", "D4"]
    assert len([item for item in changed["unknown_items"] if item.get("record_id") == "D1"]) == 1
    event_count = len(logger.records)
    changed["definitions"][0]["depends_on"].remove("D3")
    reduced = recover_formal_plan(changed, VARIABLES, logger=logger)
    assert [item["record_id"] for item in logger.records[event_count:] if item.get("event") != "graph_profiled"] == ["D1"]
    assert dependency_diagnostics(reduced)["D1"]["dependency_ids"] == ["D2", "D4"]


def test_resolved_dependencies_remove_stale_cycle_and_propagation_diagnostics():
    logger = ExperimentDesignRunLogger("resolved-dependencies", console_enabled=False)
    generated = recover_formal_plan(dependency_plan(), VARIABLES, logger=logger)
    assert dependency_diagnostics(generated)
    event_count = len(logger.records)
    generated["definitions"][2]["depends_on"] = []

    resolved = recover_formal_plan(generated, VARIABLES, logger=logger)

    assert dependency_diagnostics(resolved) == {}
    assert not resolved["unknown_items"]
    assert all(not record.get("dependency_health") for record in resolved["definitions"])
    assert not resolved["propositions"][0].get("dependency_health")
    assert not [item for item in logger.records[event_count:] if item.get("event") != "graph_profiled"]
    assert validate_formal_plan_v2(resolved, VARIABLES) == []


def test_dependency_health_change_is_reported_with_unchanged_reference_ids():
    logger = ExperimentDesignRunLogger("dependency-health-change", console_enabled=False)
    generated = recover_formal_plan(dependency_plan(), VARIABLES, logger=logger)
    event_count = len(logger.records)
    generated["definitions"][2].update(depends_on=[], dependency_health="invalid_or_blocked")

    changed = recover_formal_plan(generated, VARIABLES, logger=logger)

    assert {item["record_id"] for item in logger.records[event_count:] if item.get("event") != "graph_profiled"} == {"D1", "D2"}
    assert dependency_diagnostics(changed)["D1"]["dependency_ids"] == ["D2", "D4"]
    assert dependency_diagnostics(changed)["D1"]["dependency_states"]["D4"] == "invalid_or_blocked"


def test_legacy_dependency_warnings_collapse_without_repeating_unchanged_warnings():
    generated = recover_formal_plan(dependency_plan(), VARIABLES)
    legacy = []
    for diagnostic in generated["unknown_items"]:
        original = {key: value for key, value in diagnostic.items()
                    if key not in {"dependency_ids", "dependency_states", "dependency_health", "error_code"}}
        if diagnostic["record_id"] == "D1":
            original["reason"] = "A prerequisite construction remains unresolved: ['D4', 'D2']."
            legacy.append(dict(original, reason="A prerequisite construction remains unresolved: ['D4']."))
        legacy.append(original)
    generated["unknown_items"] = legacy
    logger = ExperimentDesignRunLogger("legacy-dependencies", console_enabled=False)

    migrated = recover_formal_plan(generated, VARIABLES, logger=logger)

    assert not logger.records
    assert len([item for item in migrated["unknown_items"] if item.get("record_id") == "D1"]) == 1
    assert dependency_diagnostics(migrated)["D1"]["dependency_ids"] == ["D2", "D4"]


def test_malformed_dependency_diagnostic_does_not_abort_other_records():
    plan = dependency_plan()
    malformed_id = {"record_id": [], "category": "construction_warning", "reason": "Cyclic construction dependency."}
    malformed_reason = {"record_id": "D1", "category": "construction_warning",
                        "error_code": "unresolved_prerequisite", "reason": {"unexpected": "object"}}
    plan["unknown_items"] = [malformed_id, malformed_reason]

    generated = recover_formal_plan(plan, VARIABLES)

    assert malformed_id in generated["unknown_items"]
    assert dependency_diagnostics(generated)["D1"]["dependency_ids"] == ["D2", "D4"]
    assert validate_formal_plan_v2(generated, VARIABLES) == []


def test_formal_ids_in_variable_references_move_to_dependencies_and_unknown_ids_remain():
    plan = formal_plan()
    helper = deepcopy(plan["definitions"][0])
    helper.update(definition_id="D2", symbol="y", variable_references=["V1", "D1", "missing", "D1"],
                  depends_on=["A1"])
    plan["definitions"].append(helper)

    normalize_variable_dependencies(plan, VARIABLES)

    assert helper["variable_references"] == ["V1", "missing"]
    assert helper["depends_on"] == ["A1", "D1"]
    assert plan["dependency_repairs"][0]["moved_to_depends_on"] == ["D1"]
    snapshot = deepcopy(plan)
    assert normalize_variable_dependencies(plan, VARIABLES) == snapshot


def test_registered_variable_ids_take_precedence_over_colliding_formal_ids():
    plan = formal_plan()
    plan["propositions"][0]["variable_references"] = ["D1"]
    normalize_variable_dependencies(plan, {"variables": [{"variable_id": "D1"}]})
    assert plan["propositions"][0]["variable_references"] == ["D1"]
    assert "dependency_repairs" not in plan


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
    plan["assumptions"][0]["object_bindings"] = {"x": "DA"}
    alternative = deepcopy(plan["definitions"][0])
    alternative.update(definition_id="DB", symbol="y")
    plan["definitions"].append(alternative)
    affected = deepcopy(plan["propositions"][0])
    affected.update(proposition_id="P2", depends_on=["V1"])
    plan["propositions"].append(affected)
    generated = recover_formal_plan(plan, VARIABLES)
    assert generated["propositions"][0] == plan["propositions"][0]
    assert generated["propositions"][1]["construction_status"] == "needs_review"
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
        assert inputs["output_contract"]["required_attempt_fields"] == ["attempt_id", "target_id", "steps", "final_step_id"]
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
            plan["assumptions"][0].pop("object_bindings")
        duplicate["statement"] = "An incompatible definition"
        plan["definitions"].append(duplicate)
    generated = recover_formal_plan(plan, VARIABLES)
    if conflict == "id":
        assert generated["propositions"][0].get("construction_status") != "needs_review"
    else:
        assert generated["propositions"][0]["construction_status"] == "needs_review"
    assert generated["construction_archive"]
    if conflict == "symbol":
        step = generated["proof_attempts"][0]["steps"][0]
        assert step["derived_statement"] == plan["proof_attempts"][0]["steps"][0]["derived_statement"]
        assert step["premises"] == plan["proof_attempts"][0]["steps"][0]["premises"]
        assert step.get("construction_status") != "needs_review"
        assert build_verification_task(generated, "P1", "z3")["blockers"]
    else:
        assert generated["proof_attempts"] == plan["proof_attempts"]
    assert validate_formal_plan_v2(generated, VARIABLES) == []


def test_cyclic_definitions_remain_intact_but_are_not_verification_ready():
    plan = formal_plan()
    first = plan["definitions"][0]
    second = deepcopy(first)
    second.update(definition_id="D2", symbol="y", variable_references=[])
    first["depends_on"] = ["D2"]
    second["depends_on"] = ["D1"]
    plan["definitions"].append(second)
    original_expressions = [first["formal_expression"], second["formal_expression"]]

    generated = recover_formal_plan(plan, VARIABLES)

    assert [record["formal_expression"] for record in generated["definitions"]] == original_expressions
    assert all(record.get("dependency_health") == "cyclic" for record in generated["definitions"])
    assert all(record.get("construction_status") == "needs_review" for record in generated["definitions"])
    assert all(record.get("verification_readiness") != "blocked" for record in generated["definitions"])
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
    assert generated["propositions"][1]["construction_status"] == "needs_review"
    assert validate_experiment_design(design) == []
    assert any(record["event"] == "records_recovered" for record in logger.records)
    assert not any(record["status"] == "DEGRADED" for record in logger.records)
