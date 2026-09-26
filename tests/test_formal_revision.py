from copy import deepcopy
from io import StringIO
import json

import pytest

from test_formal_contracts_v2 import formal_plan
from src.agents.experiment_design_agent.formal_contracts import validate_formal_plan_v2
from src.agents.experiment_design_agent.formal_dependency import COLLECTION_IDS
from src.agents.experiment_design_agent.formal_revision import affected_ids, apply_semantic_revision, run_formal_revision_loop
from src.agents.experiment_design_agent.run_logging import ExperimentDesignRunLogger


def patch(**operations):
    return {"schema_version": "formal_revision_patch_v1", "reason": "Refine the conditional formal draft", **operations}


def replacement(collection, record):
    return {"collection": collection, "record": deepcopy(record)}


def refined_target(plan):
    target = deepcopy(plan["propositions"][0])
    target["scope"] = "real scalars satisfying the explicit assumption A1"
    return target


def with_second_target():
    plan = formal_plan()
    second = deepcopy(plan["propositions"][0])
    second["proposition_id"] = "P2"
    plan["propositions"].append(second)
    return plan


def test_revision_whitelist_matches_supplied_records_and_obligation_dependencies():
    plan = formal_plan()
    assumption = deepcopy(plan["assumptions"][0])
    assumption["assumption_id"] = "A2"
    plan["assumptions"].append(assumption)
    definition = deepcopy(plan["definitions"][0])
    definition.update(definition_id="D2", symbol="y", variable_references=[])
    plan["definitions"].append(definition)
    plan["proof_obligations"] = [{"obligation_id": "PO1", "target_id": "P1", "target": "Establish the conditional bound",
                                  "premises": ["A2", "D2"], "conclusion_expression": None, "status": "unresolved"}]
    plan["propositions"][0]["required_obligation_ids"] = ["PO1"]
    seen = []

    def callback(prompt, **_kwargs):
        request = json.loads(prompt.split("INPUT_JSON:\n", 1)[1])
        identifiers = {record[field] for collection, field in COLLECTION_IDS.items() for record in request["plan"][collection]}
        assert set(request["affected_ids"]) == identifiers
        assert {item["record_id"] for item in request["editable_records"]} == identifiers
        assert {"P1", "PO1", "A2", "D2"} <= identifiers
        assert request["editable_target_ids"] == ["P1"]
        obligation = deepcopy(request["plan"]["proof_obligations"][0])
        obligation["conclusion_expression"] = deepcopy(plan["propositions"][0]["conclusion_expression"])
        seen.append(identifiers)
        return patch(replacements=[replacement("proof_obligations", obligation)])

    current, _report, audit = run_formal_revision_loop(plan, {"verification": {"enabled": False}, "max_semantic_revisions": 1}, llm_call=callback)
    assert len(seen) == 1
    assert current["proof_obligations"][0]["conclusion_expression"] is not None
    assert current["revision"] == 2
    assert audit["iterations"][0]["rejected_operations"] == []
    assert affected_ids(plan, {"target_summaries": [{"target_id": "P1", "status": "unresolved"}]}) == seen[0]
    assert validate_formal_plan_v2(current) == []


@pytest.mark.parametrize("order", ["first", "last"])
def test_outside_replacement_does_not_discard_valid_operations(order):
    plan = with_second_target()
    changed = refined_target(plan)
    unrelated = deepcopy(plan["propositions"][1])
    unrelated["statement"] = "An unauthorized change"
    operations = [replacement("propositions", unrelated), replacement("propositions", changed)]
    if order == "last":
        operations.reverse()
    logger = ExperimentDesignRunLogger("partial-revision", console_stream=StringIO())
    current, audit = apply_semantic_revision(plan, patch(replacements=operations), {"P1", "A1", "D1"}, logger=logger, iteration=1, target_ids=["P1"])
    assert current["propositions"][0] == changed
    assert current["propositions"][1] == plan["propositions"][1]
    assert current["proof_attempts"] == plan["proof_attempts"]
    assert audit["status"] == "revised"
    assert audit["warning_count"] == 1
    rejection = audit["rejected_operations"][0]
    assert rejection["record_id"] == "P2"
    assert json.loads(rejection["raw_json"])["record"] == unrelated
    warning = next(record for record in logger.records if record["event"] == "operation_warning")
    assert warning["record_id"] == "P2"
    assert warning["error_code"] == "semantic_revision_outside_affected_scope"
    assert warning["status"] == warning["level"] == "WARNING"
    assert warning["error_detail"]
    assert "raw_json" not in warning


def test_all_outside_operations_keep_plan_and_revision_unchanged():
    plan = formal_plan()
    absent = deepcopy(plan["definitions"][0])
    absent["definition_id"] = "D_missing"
    current, audit = apply_semantic_revision(plan, patch(replacements=[replacement("definitions", absent)]), {"P1"})
    assert current == plan
    assert audit["status"] == "no_progress"
    assert audit["rejected_operations"][0]["record_id"] == "D_missing"
    assert "does not exist" in audit["rejected_operations"][0]["reason"]


@pytest.mark.parametrize("damage", ["scalar", "bad_id", "wrong_collection", "malformed_quantifier", "unknown_dependency", "cycle", "verification_claim"])
def test_bad_operation_preserves_independent_legal_change(damage):
    plan = formal_plan()
    definition = deepcopy(plan["definitions"][0])
    definition["selection_reason"] = "Declare the real scalar used by the conditional target"
    target = refined_target(plan)
    operation = replacement("propositions", target)
    if damage == "scalar":
        operation = "not an operation"
    elif damage == "bad_id":
        operation["record"]["proposition_id"] = {"bad": "shape"}
    elif damage == "wrong_collection":
        operation = replacement("lemmas", dict(target, lemma_id="P1"))
    elif damage == "malformed_quantifier":
        operation["record"]["quantifiers"][0]["sort"] = {}
    elif damage == "unknown_dependency":
        operation["record"]["depends_on"] = ["not_defined"]
    elif damage == "cycle":
        operation["record"]["depends_on"] = ["P1"]
    else:
        operation["record"]["status"] = "verified"
    current, audit = apply_semantic_revision(plan, patch(replacements=[operation, replacement("definitions", definition)]), {"P1", "D1"})
    assert current["definitions"][0] == definition
    assert current["propositions"] == plan["propositions"]
    assert current["proof_attempts"] == plan["proof_attempts"]
    assert audit["status"] == "revised"
    assert audit["warning_count"] == 1
    assert validate_formal_plan_v2(current) == []


def test_jointly_dependent_addition_and_replacement_are_accepted():
    plan = formal_plan()
    definition = deepcopy(plan["definitions"][0])
    definition.update(definition_id="D2", symbol="y", variable_references=[])
    target = refined_target(plan)
    target["depends_on"] = ["D2"]
    current, audit = apply_semantic_revision(plan, patch(replacements=[replacement("propositions", target)],
        additions=[replacement("definitions", definition)]), {"P1", "A1", "D1"})
    assert current["propositions"][0] == target
    assert current["definitions"][1] == definition
    assert audit["warning_count"] == 0
    assert validate_formal_plan_v2(current) == []


def test_discarded_addition_does_not_leave_dangling_references():
    plan = formal_plan()
    definition = deepcopy(plan["definitions"][0])
    definition.update(definition_id="D2", symbol="y", variable_references=[])
    definition.pop("domain")
    target = refined_target(plan)
    target["depends_on"] = ["D2"]
    assumption = deepcopy(plan["assumptions"][0])
    assumption["statement"] = "The declared scalar satisfies the positivity hypothesis"
    current, audit = apply_semantic_revision(plan, patch(replacements=[replacement("propositions", target), replacement("assumptions", assumption)],
        additions=[replacement("definitions", definition)]), {"P1", "A1", "D1"})
    assert current["propositions"] == plan["propositions"]
    assert current["definitions"] == plan["definitions"]
    assert current["assumptions"][0] == assumption
    assert {item["record_id"] for item in audit["rejected_operations"]} == {"P1", "D2"}
    assert validate_formal_plan_v2(current) == []


def test_proof_replacement_cannot_erase_or_reassign_an_unrelated_attempt():
    plan = with_second_target()
    unrelated = deepcopy(plan["proof_attempts"][0])
    unrelated.update(attempt_id="PR2", target_id="P2")
    plan["proof_attempts"].append(unrelated)
    reassigned = deepcopy(unrelated)
    reassigned["target_id"] = "P1"
    outside = deepcopy(unrelated)
    outside["attempt_id"] = "PR3"
    valid = deepcopy(plan["proof_attempts"][0])
    valid["steps"][0]["derived_statement"] = "A positive real scalar is nonnegative"
    current, audit = apply_semantic_revision(plan, patch(proof_attempts=[reassigned, outside, valid]), {"P1", "A1", "D1"})
    assert current["proof_attempts"] == [valid, unrelated]
    assert audit["warning_count"] == 2


def test_bad_proof_attempt_does_not_discard_a_valid_attempt():
    plan = with_second_target()
    bad = deepcopy(plan["proof_attempts"][0])
    bad.update(attempt_id="PR2", target_id="P2", steps="not an array")
    valid = deepcopy(plan["proof_attempts"][0])
    valid["steps"][0]["derived_statement"] = "A positive scalar is nonnegative"
    current, audit = apply_semantic_revision(plan, patch(proof_attempts=[bad, valid]), {"P1", "P2", "A1", "D1"})
    assert current["proof_attempts"] == [valid]
    assert audit["rejected_operations"][0]["record_id"] == "PR2"
    assert validate_formal_plan_v2(current) == []


def test_unrelated_diagnostics_remain_intact():
    plan = with_second_target()
    unrelated = {"record_id": "P2", "field_path": "propositions.P2.scope", "reason": "External input needed", "status": "needs_human_input"}
    plan["unknown_items"] = [unrelated]
    scoped = {"record_id": "P1", "field_path": "propositions.P1.scope", "reason": "Clarify the declared scope", "status": "needs_human_input"}
    outside = dict(unrelated, reason="Unauthorized replacement")
    current, audit = apply_semantic_revision(plan, patch(unknown_items=[outside, scoped]), {"P1", "A1", "D1"})
    assert current["unknown_items"] == [unrelated, scoped]
    assert audit["warning_count"] == 1
    assert audit["rejected_operations"][0]["record_id"] == "P2"


def test_loop_reports_partial_success_as_warning():
    plan = with_second_target()
    logger = ExperimentDesignRunLogger("revision-loop-warning", console_stream=StringIO())

    def callback(prompt, **_kwargs):
        request = json.loads(prompt.split("INPUT_JSON:\n", 1)[1])
        if request["target_ids"] == ["P1"]:
            return patch(replacements=[replacement("propositions", plan["propositions"][1]), replacement("propositions", refined_target(plan))])
        return patch()

    current, _report, audit = run_formal_revision_loop(plan, {"verification": {"enabled": False}, "max_semantic_revisions": 1}, llm_call=callback, logger=logger)
    assert current["propositions"][0] == refined_target(plan)
    assert current["propositions"][1] == plan["propositions"][1]
    assert audit["iterations"][0]["status"] == "revised"
    assert audit["iterations"][0]["warning_count"] == 1
    completion = next(record for record in logger.records if record["stage"] == "formal_semantic_revision"
                      and record["event"] == "completed" and record["target_ids"] == ["P1"])
    assert completion["status"] == completion["level"] == "WARNING"
    assert completion["result_status"] == "revised"
    assert not any(record["status"] == "DEGRADED" or record["level"] == "ERROR" for record in logger.records)


def test_invalid_patch_only_warns_and_other_targets_continue():
    plan = with_second_target()
    logger = ExperimentDesignRunLogger("invalid-revision", console_stream=StringIO())
    seen = []

    def callback(prompt, **_kwargs):
        request = json.loads(prompt.split("INPUT_JSON:\n", 1)[1])
        seen.extend(request["target_ids"])
        return {"bad": "envelope"} if request["target_ids"] == ["P1"] else patch()

    current, _report, audit = run_formal_revision_loop(plan, {"verification": {"enabled": False}, "max_semantic_revisions": 1}, llm_call=callback, logger=logger)
    assert current == plan
    assert seen == ["P1", "P2"]
    assert json.loads(audit["iterations"][0]["raw_patch_json"]) == {"bad": "envelope"}
    warning = next(record for record in logger.records if record["event"] == "warning")
    assert warning["record_id"] == "P1"
    assert warning["level"] == warning["status"] == "WARNING"
    assert warning["disposition"] == "kept_previous_plan"


def test_new_obligation_and_target_registration_are_validated_together():
    plan = formal_plan()
    target = refined_target(plan)
    target["required_obligation_ids"] = ["PO1"]
    obligation = {"obligation_id": "PO1", "target_id": "P1", "target": "Check the conditional bound",
                  "premises": ["A1"], "conclusion_expression": None, "status": "unresolved"}
    current, audit = apply_semantic_revision(plan, patch(replacements=[replacement("propositions", target)],
        additions=[replacement("proof_obligations", obligation)]), {"P1", "A1", "D1"})
    assert current["proof_obligations"] == [obligation]
    assert current["propositions"][0]["required_obligation_ids"] == ["PO1"]
    assert audit["warning_count"] == 0
    assert validate_formal_plan_v2(current) == []


def test_duplicate_symbol_addition_preserves_legal_definition_update():
    plan = formal_plan()
    changed = deepcopy(plan["definitions"][0])
    changed["selection_reason"] = "Declare the scalar in the target model"
    duplicate = deepcopy(plan["definitions"][0])
    duplicate["definition_id"] = "D2"
    current, audit = apply_semantic_revision(plan, patch(replacements=[replacement("definitions", changed)],
        additions=[replacement("definitions", duplicate)]), {"D1"})
    assert current["definitions"] == [changed]
    assert [item["record_id"] for item in audit["rejected_operations"]] == ["D2"]


def test_diagnostic_cannot_mix_an_editable_owner_with_unrelated_owner():
    plan = with_second_target()
    diagnostic = {"record_id": "P1", "target_id": "P2", "reason": "Mixed ownership", "status": "needs_human_input"}
    current, audit = apply_semantic_revision(plan, patch(unknown_items=[diagnostic]), {"P1", "A1", "D1"})
    assert current == plan
    assert audit["rejected_operations"][0]["error_code"] == "semantic_diagnostic_outside_scope"


def test_source_locator_mismatch_accepts_semantic_definition_revision():
    plan = formal_plan()
    definition = deepcopy(plan["definitions"][0])
    reference = {"card_id": "EC1", "locator": "Eq. 2"}
    definition.update(origin="source_grounded", source_refs=[reference])
    current, audit = apply_semantic_revision(
        plan, patch(replacements=[replacement("definitions", definition)]), {"D1"},
        evidence_bundle={"evidence_cards": [{"card_id": "EC1", "source_location": "fulltext:paper:markdown"}]},
    )
    assert current["definitions"] == [definition]
    assert current["revision"] == 2
    assert audit["status"] == "revised"
    assert audit["rejected_operations"] == []
    assert validate_formal_plan_v2(current) == []


def test_bad_source_reference_does_not_discard_valid_target_revision():
    plan = formal_plan()
    definition = deepcopy(plan["definitions"][0])
    definition.update(origin="source_grounded", source_refs=1)
    target = refined_target(plan)
    current, audit = apply_semantic_revision(plan, patch(replacements=[replacement("definitions", definition),
        replacement("propositions", target)]), {"P1", "A1", "D1"})
    assert current["definitions"] == plan["definitions"]
    assert current["propositions"][0] == target
    assert audit["rejected_operations"][0]["record_id"] == "D1"


def test_invalid_obligation_association_preserves_independent_changes():
    plan = with_second_target()
    obligation = {"obligation_id": "PO1", "target_id": "P1", "target": "An essential conditional step",
                  "premises": ["A1"], "conclusion_expression": None, "status": "unresolved"}
    plan["proof_obligations"] = [obligation]
    plan["propositions"][0]["required_obligation_ids"] = ["PO1"]
    changed_obligation = dict(obligation, target_id="P2")
    definition = deepcopy(plan["definitions"][0])
    definition["selection_reason"] = "Declare a scalar in the shared model"
    current, audit = apply_semantic_revision(plan, patch(replacements=[replacement("proof_obligations", changed_obligation),
        replacement("definitions", definition)]), {"P1", "PO1", "D1", "A1"})
    assert current["proof_obligations"] == [obligation]
    assert current["definitions"][0] == definition
    assert audit["warning_count"] == 1
    assert audit["rejected_operations"][0]["record_id"] == "PO1"
    assert validate_formal_plan_v2(current) == []


@pytest.mark.parametrize("failure", ["request", "json"])
def test_request_and_json_failures_only_log_warnings_and_continue(failure):
    plan = with_second_target()
    logger = ExperimentDesignRunLogger("request-warning", console_stream=StringIO())
    seen = []

    def callback(prompt, **_kwargs):
        request = json.loads(prompt.split("INPUT_JSON:\n", 1)[1])
        seen.extend(request["target_ids"])
        if request["target_ids"] == ["P1"]:
            if failure == "request":
                raise TimeoutError("Model request timed out")
            return "invalid JSON response"
        return patch()

    current, _report, audit = run_formal_revision_loop(plan, {"verification": {"enabled": False}, "max_semantic_revisions": 1}, llm_call=callback, logger=logger)
    assert current == plan
    assert seen == ["P1", "P2"]
    assert audit["iterations"][0]["disposition"] == "kept_previous_plan"
    failure_logs = [record for record in logger.records if record["event"] in ("llm_request_failed", "llm_json_contract_failed", "warning")]
    assert failure_logs
    assert all(record["record_id"] == "P1" for record in failure_logs)
    assert all(record["level"] == record["status"] == "WARNING" for record in failure_logs)
    assert not any(record["level"] == "ERROR" or record["status"] == "DEGRADED" for record in logger.records)
