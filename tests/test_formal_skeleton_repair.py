from copy import deepcopy
from io import StringIO
import json

import pytest

from test_formal_contracts_v2 import formal_plan
from src.agents.experiment_design_agent.formal_contracts import TARGET_FIELDS, validate_formal_plan_v2
from src.agents.experiment_design_agent.formal_dependency import log_symbol_diagnostics, symbol_reference_diagnostics
from src.agents.experiment_design_agent.formal_plan_recovery import recover_formal_plan
from src.agents.experiment_design_agent.formal_reasoning_planner import FormalReasoningPlanner
from src.agents.experiment_design_agent.formal_skeleton_repair import (
    normalize_skeleton_target_fields, repair_skeleton_records, skeleton_repair_targets, skeleton_output_contract,
)
from src.agents.experiment_design_agent.formal_expression import expression_diagnostics, normalize_expression, valid_expression
from src.agents.experiment_design_agent.formal_verification import (
    build_verification_task, run_verification_task, scoped_diagnostics, verify_formal_plan,
)
from src.agents.experiment_design_agent.run_logging import ExperimentDesignRunLogger


def test_accepted_field_repair_clears_local_encoding_issue_and_allows_execution():
    plan = formal_plan()
    target = plan["propositions"][0]
    target.pop("domain_expression")
    target["machine_encoding_issues"] = ["domain_expression"]
    plan["unknown_items"] = [{"record_id": "P1", "field": "domain_expression", "category": "record_encoding",
                              "status": "encoding_pending", "reason": "Unparseable domain encoding."}]

    def callback(*_args, **_kwargs):
        return {"schema_version": "skeleton_record_patch_v1", "patches": [
            {"collection": "propositions", "record_id": "P1", "fields": {"domain_expression": {"bool": True}}},
        ]}

    repair_skeleton_records(plan, {}, settings={}, repair_prompt="INPUT_JSON:\n", llm_call=callback)
    assert not target.get("machine_encoding_issues")
    assert not plan["unknown_items"]
    assert build_verification_task(plan, "P1", "z3")["blockers"] == []
    assert run_verification_task(build_verification_task(plan, "P1", "z3"))["result"] == "passed"


VARIABLES = {"variables": [{"variable_id": "V1"}]}
MISSING_FIELDS = ("scope", "conclusion", "premises", "quantifiers", "domain_expression", "conclusion_expression")


def inputs(plan):
    return {"definitions": deepcopy(plan["definitions"]), "model_relations": [], "unknown_items": []}


def payload(prompt):
    return json.loads(prompt.split("INPUT_JSON:\n", 1)[1])


def proof_result(target_id):
    attempt = deepcopy(formal_plan()["proof_attempts"][0])
    attempt.update(attempt_id=f"PA_{target_id}", target_id=target_id)
    return {"target_id": target_id, "proof_attempts": [attempt]}


def test_eleven_incomplete_targets_are_repaired_then_receive_proof_drafts():
    complete = formal_plan()
    complete["propositions"] = []
    for number in range(1, 12):
        target = deepcopy(formal_plan()["propositions"][0])
        target["proposition_id"] = f"P{number}"
        complete["propositions"].append(target)
    skeleton = deepcopy(complete)
    skeleton["proof_attempts"] = []
    for target in skeleton["propositions"]:
        for field in MISSING_FIELDS:
            target.pop(field)
    repair_batches = []
    proof_targets = []

    def callback(prompt, **_kwargs):
        request = payload(prompt)
        if "skeleton stage" in prompt:
            assert request["output_contract"]["required_target_fields"] == list(TARGET_FIELDS)
            return deepcopy(skeleton)
        if "skeleton record repair stage" in prompt:
            repair_batches.append(request["repair_targets"])
            patches = []
            for item in request["repair_targets"]:
                original = next(target for target in complete["propositions"] if target["proposition_id"] == item["record_id"])
                assert set(item["fields"]) == set(MISSING_FIELDS)
                patches.append({**item, "fields": {field: deepcopy(original[field]) for field in item["fields"]}})
            return {"schema_version": "skeleton_record_patch_v1", "patches": patches}
        identifiers = [target["proposition_id"] for target in request["skeleton"]["targets"]]
        proof_targets.extend(identifiers)
        return {"target_results": [proof_result(identifier) for identifier in identifiers]}

    result = FormalReasoningPlanner().plan({}, {}, VARIABLES, formal_inputs=inputs(complete), llm_call=callback)
    assert [len(batch) for batch in repair_batches] == [4, 4, 3]
    assert set(proof_targets) == {f"P{number}" for number in range(1, 12)}
    for actual, expected in zip(result["propositions"], complete["propositions"]):
        assert {key: value for key, value in actual.items()
                if key not in {"candidate_completion_pending", "candidate_completion_fields"}} == expected
    assert len(result["proof_attempts"]) == 11
    assert len(result["candidate_completions"]) == 11 * len(MISSING_FIELDS)
    assert all(item["status"] == "unverified" for item in result["candidate_completions"])
    assert validate_formal_plan_v2(result, VARIABLES) == []


def test_field_patch_preserves_valid_targets_fields_and_proofs():
    plan = formal_plan()
    target = deepcopy(plan["propositions"][0])
    target.update(proposition_id="P2")
    target.pop("scope")
    target.pop("conclusion_expression")
    plan["propositions"].append(target)
    original = deepcopy(plan)

    def callback(prompt, **_kwargs):
        request = payload(prompt)
        assert len(request["repair_targets"]) == 1
        assert request["repair_targets"][0]["record_id"] == "P2"
        return {"schema_version": "skeleton_record_patch_v1", "patches": [
            {"collection": "propositions", "record_id": "P1", "fields": {"statement": "Changed"}},
            {"collection": "propositions", "record_id": "P2", "fields": {
                "scope": "real scalars", "conclusion_expression": {"wrong": "AST"}, "statement": "Changed"}},
            {"collection": "propositions", "record_id": "P2", "fields": {"scope": "Overwritten"}},
        ]}

    repair_skeleton_records(plan, {}, settings={}, repair_prompt="INPUT_JSON:\n", llm_call=callback)
    assert plan["propositions"][0] == original["propositions"][0]
    assert plan["propositions"][1]["statement"] == original["propositions"][1]["statement"]
    assert plan["propositions"][1]["scope"] == "real scalars"
    assert "conclusion_expression" not in plan["propositions"][1]
    assert plan["proof_attempts"] == original["proof_attempts"]
    assert plan["construction_archive"]


@pytest.mark.parametrize("failure", ["exception", "empty", "malformed"])
def test_failed_skeleton_repair_still_drafts_all_targets(failure):
    plan = formal_plan()
    second = deepcopy(plan["propositions"][0])
    second.update(proposition_id="P2", required_obligation_ids=["PO_other"])
    for field in MISSING_FIELDS:
        second.pop(field)
    plan["propositions"].append(second)
    proof_targets = []
    logger = ExperimentDesignRunLogger("repair-retention", console_stream=StringIO())

    def callback(prompt, **_kwargs):
        if "skeleton stage" in prompt:
            return deepcopy(plan)
        if "skeleton record repair stage" in prompt:
            if failure == "exception":
                raise RuntimeError("Repair request failed")
            if failure == "malformed":
                return {"schema_version": "bad", "patches": "bad"}
            return {"schema_version": "skeleton_record_patch_v1", "patches": []}
        identifiers = [target["proposition_id"] for target in payload(prompt)["skeleton"]["targets"]]
        proof_targets.extend(identifiers)
        return {"target_results": [proof_result(identifier) for identifier in identifiers]}

    result = FormalReasoningPlanner().plan({}, {}, VARIABLES, formal_inputs=inputs(plan), llm_call=callback, logger=logger)
    assert set(proof_targets) == {"P1", "P2"}
    assert result["propositions"][0] == plan["propositions"][0]
    assert result["proof_attempts"][0] == plan["proof_attempts"][0]
    assert any(attempt["target_id"] == "P2" for attempt in result["proof_attempts"])
    assert result["propositions"][1]["construction_status"] == "needs_review"
    assert build_verification_task(result, "P2", "z3")["blockers"]
    notices = [record for record in logger.records if record["event"] == "record_warning" and record.get("field") == "target_fields"]
    assert len(notices) == 1
    assert all(field in notices[0]["error_detail"] for field in MISSING_FIELDS)
    assert not any(record["status"] == "DEGRADED" for record in logger.records)
    assert validate_formal_plan_v2(result, VARIABLES) == []


def test_symbol_mismatch_retains_math_without_catalog_warning():
    plan = formal_plan()
    plan["propositions"][0]["symbol_references"].append("unmatched_notation")
    logger = ExperimentDesignRunLogger("symbol-notice", console_stream=StringIO())
    result = recover_formal_plan(plan, VARIABLES, logger=logger)
    log_symbol_diagnostics(result, logger=logger)
    assert result["propositions"] == plan["propositions"]
    assert result["proof_attempts"] == plan["proof_attempts"]
    assert result["unknown_items"] == []
    assert result["status"] == "unverified"
    assert skeleton_repair_targets(result) == []
    assert build_verification_task(result, "P1", "z3")["blockers"] == []
    notices = [record for record in logger.records if record["event"] == "symbol_notice"]
    assert notices == []
    assert result["symbol_diagnostics"] == []


def test_quantified_local_symbols_need_no_global_definition():
    plan = formal_plan()
    plan["definitions"] = []
    plan["assumptions"] = []
    plan["propositions"][0]["premises"] = []
    plan["proof_attempts"][0]["steps"][0]["premises"] = []
    assert symbol_reference_diagnostics(plan) == []
    assert build_verification_task(plan, "P1", "z3")["blockers"] == []


def test_dependency_repair_removes_unknown_reference_and_retains_valid_premise():
    plan = formal_plan()
    plan["propositions"][0]["premises"].append("unknown")

    def callback(*_args, **_kwargs):
        return {"schema_version": "skeleton_record_patch_v1", "patches": [
            {"collection": "propositions", "record_id": "P1", "fields": {"premises": ["A1"]}},
        ]}

    repair_skeleton_records(plan, {}, settings={}, repair_prompt="INPUT_JSON:\n", llm_call=callback)
    assert plan["propositions"][0]["premises"] == ["A1"]
    assert plan["skeleton_repair_audit"][0]["status"] == "REPAIRED"
    assert plan["candidate_completions"][0]["before"] == ["A1", "unknown"]
    assert plan["candidate_completions"][0]["after"] == ["A1"]


def test_unambiguous_aliases_and_variable_ids_are_repaired_before_llm_patch():
    plan = formal_plan()
    plan["assumptions"][0]["depends_on"] = ["V1"]
    plan["propositions"][0]["applicability_scope"] = plan["propositions"][0].pop("scope")
    calls = []

    def callback(prompt, **_kwargs):
        calls.append(prompt)
        if "skeleton stage" in prompt:
            return deepcopy(plan)
        return {"target_results": [proof_result("P1")]}

    result = FormalReasoningPlanner().plan({}, {}, VARIABLES, formal_inputs=inputs(plan), llm_call=callback)
    assert not any("skeleton record repair stage" in prompt for prompt in calls)
    assert result["assumptions"][0]["depends_on"] == ["D1"]
    assert result["propositions"][0]["scope"] == "real scalars"
    assert result["unknown_items"] == []


def test_malformed_symbol_metadata_is_only_advisory():
    plan = formal_plan()
    plan["propositions"][0].update(quantifiers=None, target_id={"bad": "shape"})
    plan["symbol_diagnostics"] = None
    normalize_skeleton_target_fields(plan)
    log_symbol_diagnostics(plan, logger=ExperimentDesignRunLogger("bad-metadata", console_stream=StringIO()))
    assert isinstance(plan["symbol_diagnostics"], list)


def test_repair_rounds_only_request_remaining_fields_and_clear_resolved_diagnostics():
    plan = formal_plan()
    target = plan["propositions"][0]
    target.pop("scope")
    target.pop("conclusion_expression")
    rounds = []

    def callback(prompt, **_kwargs):
        request = payload(prompt)
        rounds.append(request["repair_targets"][0]["fields"])
        if len(rounds) == 1:
            return {"schema_version": "skeleton_record_patch_v1", "patches": [
                {"collection": "propositions", "record_id": "P1", "fields": {"scope": "real scalars"}},
            ], "unknown_items": [{"record_id": "P1", "field": "conclusion_expression", "reason": "Encoding absent"}]}
        return {"schema_version": "skeleton_record_patch_v1", "patches": [
            {"collection": "propositions", "record_id": "P1", "fields": {
                "conclusion_expression": deepcopy(formal_plan()["propositions"][0]["conclusion_expression"])}},
        ]}

    repair_skeleton_records(plan, {}, settings={"max_skeleton_repairs": 2}, repair_prompt="INPUT_JSON:\n", llm_call=callback)
    assert set(rounds[0]) == {"scope", "conclusion_expression"}
    assert set(rounds[1]) == {"conclusion_expression"}
    assert plan["unknown_items"] == []
    assert plan["skeleton_repair_audit"][0]["diagnostics"][0]["reason"] == "Encoding absent"
    assert skeleton_repair_targets(plan) == []


def test_malformed_neighbor_record_does_not_prevent_valid_field_patch():
    plan = formal_plan()
    plan["propositions"][0].pop("scope")
    plan["propositions"].insert(0, "Malformed neighbor")

    def callback(*_args, **_kwargs):
        return {"schema_version": "skeleton_record_patch_v1", "patches": [
            {"collection": "propositions", "record_id": "P1", "fields": {"scope": "real scalars"}},
        ]}

    repair_skeleton_records(plan, {}, settings={}, repair_prompt="INPUT_JSON:\n", llm_call=callback)
    assert plan["propositions"][1]["scope"] == "real scalars"
    assert plan["skeleton_repair_audit"][0]["status"] == "REPAIRED"


def test_candidate_completion_is_adopted_and_enters_actual_verification():
    plan = formal_plan()
    plan["propositions"][0].pop("domain_expression")

    def callback(*_args, **_kwargs):
        return {"schema_version": "skeleton_record_patch_v1", "patches": [
            {"collection": "propositions", "record_id": "P1", "fields": {
                "domain_expression": {"bool": True},
            }},
        ]}

    repair_skeleton_records(plan, {}, settings={}, repair_prompt="INPUT_JSON:\n", llm_call=callback)
    completion = plan["candidate_completions"][0]
    assert plan["propositions"][0]["domain_expression"] == {"bool": True}
    assert completion["original_present"] is False
    assert completion["original"] is None
    assert completion["candidate"] == {"bool": True}
    assert completion["before"] is None
    assert completion["after"] == {"bool": True}
    assert completion["status"] == "unverified"
    assert plan["propositions"][0]["candidate_completion_pending"] is False
    assert plan["status"] == "unverified"
    assert any("Original draft before targeted field repair." == item["reason"] for item in plan["construction_archive"])
    task = build_verification_task(plan, "P1", "z3")
    assert task["blockers"] == []
    verification = run_verification_task(task)
    assert verification["result"] == "passed"
    assert verification["executed"] is True


def test_repair_cannot_remove_valid_premise_while_correcting_invalid_reference():
    plan = formal_plan()
    plan["propositions"][0]["premises"].append("unknown")

    def callback(*_args, **_kwargs):
        return {"schema_version": "skeleton_record_patch_v1", "patches": [
            {"collection": "propositions", "record_id": "P1", "fields": {"premises": []}},
        ]}

    repair_skeleton_records(plan, {}, settings={}, repair_prompt="INPUT_JSON:\n", llm_call=callback)
    assert plan["propositions"][0]["premises"] == ["A1", "unknown"]
    assert plan["skeleton_repair_audit"][0]["rejected_fields"][0]["field_diagnostics"][0]["error_code"] == "valid_reference_removed"


@pytest.mark.parametrize("wrong_reference", ["missing", "D1", "PO_other"])
def test_obligation_repair_removes_invalid_ids_and_preserves_valid_obligations(wrong_reference):
    plan = formal_plan()
    plan["proof_obligations"] = [
        {"obligation_id": "PO_good", "target_id": "P1", "status": "unresolved"},
        {"obligation_id": "PO_other", "target_id": "P2", "status": "unresolved"},
    ]
    second = deepcopy(plan["propositions"][0])
    second["proposition_id"] = "P2"
    plan["propositions"].append(second)
    plan["propositions"][0]["required_obligation_ids"] = ["PO_good", wrong_reference]

    def callback(prompt, **_kwargs):
        request = payload(prompt)
        target = next(item for item in request["repair_targets"] if item["record_id"] == "P1")
        assert target["valid_obligation_ids"] == ["PO_good"]
        assert target["invalid_references"][0]["reference"] == wrong_reference
        expected_codes = {"missing": "missing_reference", "D1": "wrong_reference_type", "PO_other": "obligation_target_mismatch"}
        assert target["invalid_references"][0]["error_code"] == expected_codes[wrong_reference]
        assert next(item for item in request["record_catalog"] if item["record_id"] == "PO_good")["target_id"] == "P1"
        return {"schema_version": "skeleton_record_patch_v1", "patches": [
            {"collection": "propositions", "record_id": "P1", "fields": {"required_obligation_ids": ["PO_good"]}},
        ]}

    repair_skeleton_records(plan, {}, settings={}, repair_prompt="INPUT_JSON:\n", llm_call=callback)
    assert plan["propositions"][0]["required_obligation_ids"] == ["PO_good"]
    assert plan["skeleton_repair_audit"][0]["status"] == "REPAIRED"


def test_obligation_repair_rejects_deleting_a_valid_obligation():
    plan = formal_plan()
    plan["proof_obligations"] = [{"obligation_id": "PO_good", "target_id": "P1", "status": "unresolved"}]
    plan["propositions"][0]["required_obligation_ids"] = ["PO_good", "missing"]

    def callback(*_args, **_kwargs):
        return {"schema_version": "skeleton_record_patch_v1", "patches": [
            {"collection": "propositions", "record_id": "P1", "fields": {"required_obligation_ids": []}},
        ]}

    repair_skeleton_records(plan, {}, settings={}, repair_prompt="INPUT_JSON:\n", llm_call=callback)
    assert plan["propositions"][0]["required_obligation_ids"] == ["PO_good", "missing"]
    assert plan["skeleton_repair_audit"][0]["status"] == "NO_PROGRESS"


@pytest.mark.parametrize("reverse_order", [False, True])
def test_related_target_and_obligation_patches_are_validated_together(reverse_order):
    plan = formal_plan()
    second = deepcopy(plan["propositions"][0])
    second.update(proposition_id="P2", required_obligation_ids=["PO_good", "missing"])
    plan["propositions"].append(second)
    plan["proof_obligations"] = [{"obligation_id": "PO_good", "target_id": "P1", "status": "unresolved"}]
    calls = []

    def callback(prompt, **_kwargs):
        request = payload(prompt)
        calls.append(request)
        assert {item["record_id"] for item in request["repair_targets"]} == {"P1", "P2", "PO_good"}
        patches = [
            {"collection": "propositions", "record_id": "P2", "fields": {"required_obligation_ids": ["PO_good"]}},
            {"collection": "proof_obligations", "record_id": "PO_good", "fields": {"target_id": "P2"}},
        ]
        return {"schema_version": "skeleton_record_patch_v1", "patches": list(reversed(patches)) if reverse_order else patches}

    repair_skeleton_records(plan, {}, settings={"max_records_per_skeleton_repair": 1}, repair_prompt="INPUT_JSON:\n", llm_call=callback)
    assert len(calls) == 1
    assert plan["proof_obligations"][0]["target_id"] == "P2"
    assert plan["propositions"][1]["required_obligation_ids"] == ["PO_good"]
    assert skeleton_repair_targets(plan) == []


def test_invalid_association_patch_cannot_make_a_dependent_reference_patch_accepted():
    plan = formal_plan()
    plan["propositions"][0]["required_obligation_ids"] = ["PO1", "missing"]
    plan["proof_obligations"] = [{"obligation_id": "PO1", "target_id": "missing", "status": "unresolved"}]

    def callback(*_args, **_kwargs):
        return {"schema_version": "skeleton_record_patch_v1", "patches": [
            {"collection": "propositions", "record_id": "P1", "fields": {"required_obligation_ids": ["PO1"]}},
            {"collection": "proof_obligations", "record_id": "PO1", "fields": {"target_id": "not_a_target"}},
        ]}

    repair_skeleton_records(plan, {}, settings={}, repair_prompt="INPUT_JSON:\n", llm_call=callback)
    assert plan["propositions"][0]["required_obligation_ids"] == ["PO1", "missing"]
    assert plan["proof_obligations"][0]["target_id"] == "missing"


def test_expression_diagnostics_and_numeric_normalization_share_the_validation_contract():
    expression = {"op": "ge", "args": [{"symbol": "x"}, {"number": 0}]}
    assert expression_diagnostics(expression)[0] == {
        "node_path": "$.args[1].number", "error_code": "number_requires_string",
        "actual_type": "int", "expected": 'A numeric string such as "0" or "1/3".',
    }
    assert valid_expression(expression) is False
    assert valid_expression(normalize_expression(expression)) is True
    assert normalize_expression({"number": True}) == {"number": True}
    assert valid_expression(normalize_expression({"number": float("inf")})) is False
    assert valid_expression({"call": "arbitrary_mathematical_function", "args": [{"symbol": "x"}]}) is True


def test_expression_patch_failure_path_reaches_log_audit_and_next_request():
    plan = formal_plan()
    plan["propositions"][0]["conclusion_expression"]["args"][1] = "zero"
    plan["propositions"][0].pop("scope")
    logger = ExperimentDesignRunLogger("expression-diagnostics", console_stream=StringIO())
    requests = []

    def callback(prompt, **_kwargs):
        request = payload(prompt)
        requests.append(request)
        diagnostics = request["repair_targets"][0]["field_diagnostics"]
        assert next(item for item in diagnostics if item["field"] == "conclusion_expression")["node_path"] == "$.args[1]"
        return {"schema_version": "skeleton_record_patch_v1", "patches": [
            {"collection": "propositions", "record_id": "P1", "fields": {
                "scope": "real scalars", "conclusion_expression": deepcopy(plan["propositions"][0]["conclusion_expression"])}},
        ]} if len(requests) == 1 else {"schema_version": "skeleton_record_patch_v1", "patches": [
            {"collection": "propositions", "record_id": "P1", "fields": {
                "conclusion_expression": deepcopy(formal_plan()["propositions"][0]["conclusion_expression"])}},
        ]}

    repair_skeleton_records(plan, {}, settings={"max_skeleton_repairs": 2}, repair_prompt="INPUT_JSON:\n", llm_call=callback, logger=logger)
    notice = next(item for item in logger.records if item["event"] == "skeleton_patch_warning")
    assert notice["field_diagnostics"][0]["node_path"] == "$.args[1]"
    assert notice["field_diagnostics"][0]["error_code"] == "expression_requires_object"
    assert plan["skeleton_repair_audit"][0]["rejected_fields"][0]["field_diagnostics"] == notice["field_diagnostics"]
    assert len(requests) == 2
    assert skeleton_repair_targets(plan) == []


def test_numeric_leaf_shape_is_repaired_locally_without_an_llm_request():
    plan = formal_plan()
    plan["assumptions"][0]["predicate_expression"]["args"][1] = {"number": 0}

    def callback(*_args, **_kwargs):
        pytest.fail("Numeric leaf normalization must not require an LLM call")

    repair_skeleton_records(plan, {}, settings={}, repair_prompt="INPUT_JSON:\n", llm_call=callback)
    assert plan["assumptions"][0]["predicate_expression"]["args"][1] == {"number": "0"}
    assert plan["construction_archive"]


def test_successful_completion_is_info_and_null_encoding_is_not_a_scientific_error():
    plan = formal_plan()
    plan["propositions"][0].pop("conclusion_expression")
    logger = ExperimentDesignRunLogger("encoding-gap", console_stream=StringIO())

    def callback(*_args, **_kwargs):
        return {"schema_version": "skeleton_record_patch_v1", "patches": [
            {"collection": "propositions", "record_id": "P1", "fields": {"conclusion_expression": None}},
        ]}

    repair_skeleton_records(plan, {}, settings={}, repair_prompt="INPUT_JSON:\n", llm_call=callback, logger=logger)
    assert all(item["level"] == "INFO" for item in logger.records)
    assert any(item["status"] == "ENCODING_PENDING" for item in logger.records)
    assert plan["unknown_items"][0]["category"] == "encoding_gap"
    assert plan["status"] == "unverified"
    assert plan["propositions"][0]["conclusion"] == "x >= 0"
    assert build_verification_task(plan, "P1", "z3")["blockers"]


def test_legacy_completion_markers_do_not_block_solver_or_rule_verification():
    plan = formal_plan()
    plan["propositions"][0]["candidate_completion_pending"] = True
    plan["assumptions"][0]["candidate_completion_pending"] = True
    plan["unknown_items"] = [{"record_id": "P1", "field": "domain_expression", "category": "model_completion",
                               "diagnostic_origin": "skeleton_record_repair", "status": "needs_human_input",
                               "reason": "Model-generated completion requires human confirmation of scientific meaning."}]
    assert scoped_diagnostics(plan, "P1")["unknown_items"] == []
    assert build_verification_task(plan, "P1", "z3")["blockers"] == []
    assert run_verification_task(build_verification_task(plan, "P1", "z3"))["result"] == "passed"
    plan["proof_attempts"][0]["steps"][0]["rule_id"] = "order_weakening"
    plan["proof_attempts"][0]["steps"][0]["derived_expression"] = deepcopy(plan["propositions"][0]["conclusion_expression"])
    report = verify_formal_plan(plan, {"enabled": True, "backends": [], "timeout_seconds": 5})
    assert any(item["backend"] == "rules" and item["executed"] for item in report["results"])


def test_completion_does_not_make_a_cyclic_dependency_a_proved_premise():
    plan = formal_plan()
    plan["assumptions"][0]["depends_on"] = ["P1"]
    plan["propositions"][0].pop("scope")

    def callback(*_args, **_kwargs):
        return {"schema_version": "skeleton_record_patch_v1", "patches": [
            {"collection": "propositions", "record_id": "P1", "fields": {"scope": "real scalars"}},
        ]}

    repair_skeleton_records(plan, {}, settings={}, repair_prompt="INPUT_JSON:\n", llm_call=callback)
    plan = recover_formal_plan(plan, VARIABLES)
    assert plan["assumptions"][0]["depends_on"] == ["P1"]
    assert build_verification_task(plan, "P1", "z3")["blockers"]
    assert run_verification_task(build_verification_task(plan, "P1", "z3"))["executed"] is False


def test_output_contract_pairs_assumptions_targets_and_obligations():
    contract = skeleton_output_contract()
    examples = contract["target_examples"]
    assert valid_expression(examples["assumption"]["predicate_expression"])
    assert examples["lemma"]["required_obligation_ids"] == [examples["proof_obligation"]["obligation_id"]]
    assert examples["proof_obligation"]["target_id"] == examples["lemma"]["lemma_id"]


def test_successful_patch_can_report_a_specific_semantic_conflict_without_generic_blocking():
    plan = formal_plan()
    plan["propositions"][0].pop("domain_expression")
    logger = ExperimentDesignRunLogger("specific-review", console_stream=StringIO())

    def callback(*_args, **_kwargs):
        return {"schema_version": "skeleton_record_patch_v1", "patches": [
            {"collection": "propositions", "record_id": "P1", "fields": {"domain_expression": {"bool": True}}},
        ], "unknown_items": [{"record_id": "P1", "field": "domain_expression", "category": "semantic_conflict",
                              "reason": "Two stated operating regimes impose incompatible domain conditions."}]}

    repair_skeleton_records(plan, {}, settings={}, repair_prompt="INPUT_JSON:\n", llm_call=callback, logger=logger)
    assert plan["status"] == "requires_human_review"
    assert plan["unknown_items"][0]["category"] == "semantic_conflict"
    warning = next(item for item in logger.records if item["event"] == "skeleton_semantic_warning")
    assert warning["status"] == "REVIEW_REQUIRED"
    assert warning["level"] == "WARNING"
    assert "incompatible" in warning["error_detail"]
    assert plan["propositions"][0]["candidate_completion_pending"] is False


def test_obligation_patch_cannot_break_an_existing_valid_owner():
    plan = formal_plan()
    plan["propositions"][0]["required_obligation_ids"] = ["PO1"]
    other = deepcopy(plan["propositions"][0])
    other.update(proposition_id="P2", required_obligation_ids=["PO1", "missing"])
    plan["propositions"].append(other)
    plan["proof_obligations"] = [{"obligation_id": "PO1", "target_id": "P1", "status": "unresolved"}]

    def callback(*_args, **_kwargs):
        return {"schema_version": "skeleton_record_patch_v1", "patches": [
            {"collection": "propositions", "record_id": "P2", "fields": {"required_obligation_ids": ["PO1"]}},
            {"collection": "proof_obligations", "record_id": "PO1", "fields": {"target_id": "P2"}},
        ]}

    repair_skeleton_records(plan, {}, settings={}, repair_prompt="INPUT_JSON:\n", llm_call=callback)
    assert plan["proof_obligations"][0]["target_id"] == "P1"
    assert plan["propositions"][1]["required_obligation_ids"] == ["PO1", "missing"]
    rejected = plan["skeleton_repair_audit"][0]["rejected_fields"]
    assert any(diagnostic["error_code"] == "valid_obligation_association_changed"
               for item in rejected for diagnostic in item["field_diagnostics"])


def test_repair_catalog_excludes_unrelated_targets_but_includes_replacement_obligations():
    plan = formal_plan()
    plan["propositions"][0]["required_obligation_ids"] = ["missing"]
    plan["proof_obligations"] = [{"obligation_id": "PO1", "target_id": "P1", "status": "unresolved"}]
    unrelated = deepcopy(plan["propositions"][0])
    unrelated.update(proposition_id="unrelated", required_obligation_ids=[])
    plan["propositions"].append(unrelated)

    def callback(prompt, **_kwargs):
        request = payload(prompt)
        catalog = {item["record_id"]: item for item in request["record_catalog"]}
        assert "unrelated" not in catalog
        assert catalog["PO1"]["target_id"] == "P1"
        assert catalog["PO1"]["status"] == "unresolved"
        return {"schema_version": "skeleton_record_patch_v1", "patches": [
            {"collection": "propositions", "record_id": "P1", "fields": {"required_obligation_ids": ["PO1"]}},
        ]}

    repair_skeleton_records(plan, {}, settings={}, repair_prompt="INPUT_JSON:\n", llm_call=callback)
    assert plan["propositions"][0]["required_obligation_ids"] == ["PO1"]


@pytest.mark.parametrize("field", ["premises", "depends_on", "assumption_ids"])
def test_unproved_obligation_is_repaired_as_an_invalid_premise_type(field):
    plan = formal_plan()
    plan["proof_obligations"] = [{"obligation_id": "PO1", "target_id": "P1", "status": "unresolved"}]
    target = plan["propositions"][0]
    target["required_obligation_ids"] = ["PO1"]
    target[field] = ["A1", "PO1"]
    assert field in skeleton_repair_targets(plan)[0]["fields"]

    def callback(*_args, **_kwargs):
        return {"schema_version": "skeleton_record_patch_v1", "patches": [
            {"collection": "propositions", "record_id": "P1", "fields": {field: ["A1"]}},
        ]}

    repair_skeleton_records(plan, {}, settings={}, repair_prompt="INPUT_JSON:\n", llm_call=callback)
    assert target[field] == ["A1"]
    assert target["required_obligation_ids"] == ["PO1"]
    assert skeleton_repair_targets(plan) == []
