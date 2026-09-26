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
    normalize_skeleton_target_fields, repair_skeleton_records, skeleton_repair_targets,
)
from src.agents.experiment_design_agent.formal_verification import build_verification_task
from src.agents.experiment_design_agent.run_logging import ExperimentDesignRunLogger


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
    assert result["propositions"] == complete["propositions"]
    assert len(result["proof_attempts"]) == 11
    assert result["unknown_items"] == []
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
    second["proposition_id"] = "P2"
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
    assert result["propositions"][1]["construction_status"] == "blocked"
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


def test_dependency_repair_cannot_drop_premises_to_claim_success():
    plan = formal_plan()
    plan["propositions"][0]["premises"].append("unknown")

    def callback(*_args, **_kwargs):
        return {"schema_version": "skeleton_record_patch_v1", "patches": [
            {"collection": "propositions", "record_id": "P1", "fields": {"premises": ["A1"]}},
        ]}

    repair_skeleton_records(plan, {}, settings={}, repair_prompt="INPUT_JSON:\n", llm_call=callback)
    assert plan["propositions"][0]["premises"] == ["A1", "unknown"]
    assert plan["skeleton_repair_audit"][0]["status"] == "NO_PROGRESS"


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
