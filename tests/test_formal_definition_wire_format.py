import json
from copy import deepcopy

import pytest

from test_formal_contracts_v2 import formal_plan
from src.agents.experiment_design_agent.formal_contracts import DEFINITION_TEXT_CONTRACT
from src.agents.experiment_design_agent.formal_definition_resolver import (
    DEFINITION_PROMPT, RECONCILIATION_REVIEW_PROMPT, FormalDefinitionResolver,
)
from src.agents.experiment_design_agent.formal_reasoning_planner import (
    FORMAL_REASONING_V2_PROMPT, FORMAL_REASONING_SKELETON_PROMPT, FORMAL_REASONING_TARGET_PROMPT,
)
from src.agents.experiment_design_agent.formal_revision import REVISION_PROMPT


def test_compact_definition_wire_format_is_enriched_deterministically():
    def callback(prompt, **_kwargs):
        assert "object_kind" in prompt
        assert "exactly `primitive`" in prompt
        assert "relation `status` must be exactly `candidate_formalization`" in prompt
        assert "`unresolved`; `origin`" in prompt
        assert "verification_readiness" in prompt
        request = json.loads(prompt.split("INPUT_JSON:\n", 1)[1])
        assert "condition_expressions" not in request["definition_fields"]
        assert "depends_on" not in request["definition_fields"]
        assert "verification_readiness" not in request["definition_fields"]
        assert "variable_dependency_registry" not in request["definition_fields"]
        return {
            "wire_format": "formal_definition_wire_v1",
            "schema_version": "formal_definition_resolution_v1",
            "definitions": [{
                "definition_id": "D1",
                "symbol": "x",
                "statement": "A real scalar",
                "object_kind": "primitive",
                "domain": "R",
                "codomain": "R",
                "unit": "dimensionless",
                "origin": "modeling_convention",
                "source_refs": [],
                "variable_references": ["V1"],
                "conditions": [{
                    "text": "x is positive",
                    "formal_expression": {
                        "op": "gt",
                        "args": [{"symbol": "x"}, {"number": "0"}],
                    },
                }],
            }],
            "model_relations": [],
            "unknown_items": [],
        }

    result = FormalDefinitionResolver().resolve(
        {}, {}, {"variables": [{"variable_id": "V1"}]}, {},
        llm_call=callback, settings={"max_supplement_rounds": 0},
    )

    definition = result["definitions"][0]
    assert definition["conditions"] == ["x is positive"]
    assert definition["condition_expressions"][0]["op"] == "gt"
    assert definition["definition_status"] == "specified"
    assert definition["verification_readiness"] == "requires_encoding"
    assert definition["symbol_references"] == []
    assert "wire_format" not in result
    assert result["variable_dependency_registry"][0]["record_id"] == "D1"


@pytest.mark.parametrize("prompt", [
    DEFINITION_PROMPT, RECONCILIATION_REVIEW_PROMPT, FORMAL_REASONING_V2_PROMPT,
    FORMAL_REASONING_SKELETON_PROMPT, FORMAL_REASONING_TARGET_PROMPT, REVISION_PROMPT,
])
def test_definition_generating_prompts_explain_structural_fields_and_reference_ids(prompt):
    assert DEFINITION_TEXT_CONTRACT in prompt
    assert "nonempty strings, never null" in prompt
    assert "not_applicable" in prompt
    assert "only registered variable IDs" in prompt


def test_compact_missing_structural_fields_are_targeted_and_repaired():
    calls = []

    def callback(prompt, **_kwargs):
        request = json.loads(prompt.split("INPUT_JSON:\n", 1)[1])
        calls.append(request)
        definition = deepcopy(formal_plan()["definitions"][0])
        for field in ("definition_status", "verification_readiness", "depends_on", "symbol_references"):
            definition.pop(field)
        definition.update(symbol="G", statement="A finite topology graph", expression_latex=None,
                          domain="admissible network topologies", codomain=None, unit=None)
        if len(calls) == 2:
            assert request["repair_targets"]["definition_ids"] == ["D1"]
            fields = {item["field"] for item in request["previous_candidate"]["unknown_items"]}
            assert {"codomain", "unit"} <= fields
            definition.update(codomain="weighted graphs", unit="not_applicable")
        return {"wire_format": "formal_definition_wire_v1",
                "schema_version": "formal_definition_resolution_v1", "definitions": [definition],
                "model_relations": [], "unknown_items": []}

    result = FormalDefinitionResolver().resolve(
        {}, {}, {"variables": [{"variable_id": "V1"}]}, {},
        llm_call=callback, settings={"max_supplement_rounds": 1},
    )

    assert len(calls) == 2
    assert result["definitions"][0]["definition_status"] == "specified"
    assert result["definitions"][0]["verification_readiness"] == "requires_encoding"
    diagnostics = result["retrieval_audit"][0]["record_diagnostics"]
    assert {item["field"] for item in diagnostics} == {"codomain", "unit"}
    assert all(item["error_code"] == "unspecified_content" for item in diagnostics)
    assert not result["unknown_items"]


def test_foreign_primary_stubs_are_archived_without_supplement_or_conflict():
    requests = []

    def callback(prompt, **_kwargs):
        request = json.loads(prompt.split("INPUT_JSON:\n", 1)[1])
        requests.append(request)
        if "candidate_catalog" in request:
            return {"issues": []}
        assigned = request["assigned_definition_ids"]
        assert len(assigned) == 1
        assert {item["definition_id"] for item in request["global_variable_registry"]} == {"D1", "D2"}
        variable_id, definition_id = next(iter(assigned.items()))
        definition = deepcopy(formal_plan()["definitions"][0])
        definition.update(definition_id=definition_id, symbol=variable_id,
                          variable_references=[variable_id])
        foreign_id = "D2" if definition_id == "D1" else "D1"
        return {"schema_version": "formal_definition_resolution_v1",
                "definitions": [definition, {"definition_id": foreign_id, "unit": None}],
                "model_relations": [], "unknown_items": [
                    {"record_id": foreign_id, "field_path": f"definitions.{foreign_id}.unit",
                     "reason": "Foreign definition left incomplete", "status": "needs_human_input"},
                ]}

    result = FormalDefinitionResolver().resolve(
        {}, {}, {"variables": [{"variable_id": "V1"}, {"variable_id": "V2"}]}, {},
        llm_call=callback, settings={"variables_per_group": 1, "max_supplement_rounds": 2},
    )

    group_requests = [request for request in requests if "assigned_definition_ids" in request]
    assert len(group_requests) == 2
    assert [item["definition_id"] for item in result["definitions"]] == ["D1", "D2"]
    assert not result["unknown_items"]
    group_audit = [item for item in result["retrieval_audit"] if "group" in item]
    assert len(group_audit) == 2
    assert all(not item["record_diagnostics"] for item in group_audit)
    assert all(len(item["out_of_group_candidates"]) == 1 for item in group_audit)


def test_resolver_moves_known_formal_references_before_global_variable_validation():
    def callback(prompt, **_kwargs):
        definition = deepcopy(formal_plan()["definitions"][0])
        helper = deepcopy(definition)
        helper.update(definition_id="support", symbol="y", variable_references=[])
        definition["variable_references"] = ["V1", "support"]
        return {"schema_version": "formal_definition_resolution_v1",
                "definitions": [definition, helper], "model_relations": [], "unknown_items": []}

    result = FormalDefinitionResolver().resolve(
        {}, {}, {"variables": [{"variable_id": "V1"}]}, {},
        llm_call=callback, settings={"max_supplement_rounds": 0},
    )

    definition = result["definitions"][0]
    assert definition["variable_references"] == ["V1"]
    assert definition["depends_on"] == ["G1_support"]
    assert definition["definition_status"] == "specified"
    assert not result["unknown_items"]
    assert result["retrieval_audit"][0]["dependency_repairs"][0]["moved_to_depends_on"] == ["support"]


def test_cross_group_formal_reference_is_resolved_after_group_merge():
    def callback(prompt, **_kwargs):
        request = json.loads(prompt.split("INPUT_JSON:\n", 1)[1])
        if "candidate_catalog" in request:
            return {"issues": []}
        variable_id, definition_id = next(iter(request["assigned_definition_ids"].items()))
        definition = deepcopy(formal_plan()["definitions"][0])
        definition.update(definition_id=definition_id, symbol=variable_id,
                          variable_references=[variable_id])
        if variable_id == "V1":
            definition["variable_references"].append("D2")
        return {"schema_version": "formal_definition_resolution_v1",
                "definitions": [definition], "model_relations": [], "unknown_items": []}

    result = FormalDefinitionResolver().resolve(
        {}, {}, {"variables": [{"variable_id": "V1"}, {"variable_id": "V2"}]}, {},
        llm_call=callback, settings={"variables_per_group": 1, "max_supplement_rounds": 0},
    )
    assert result["definitions"][0]["variable_references"] == ["V1"]
    assert result["definitions"][0]["depends_on"] == ["D2"]
    assert result["definitions"][0]["definition_status"] == "specified"
    assert not result["unknown_items"]


def test_support_record_namespace_does_not_rename_a_registered_variable_reference():
    def callback(prompt, **_kwargs):
        definition = deepcopy(formal_plan()["definitions"][0])
        helper = deepcopy(definition)
        helper.update(definition_id="V1", symbol="y", variable_references=[])
        return {"schema_version": "formal_definition_resolution_v1",
                "definitions": [definition, helper], "model_relations": [], "unknown_items": []}

    result = FormalDefinitionResolver().resolve(
        {}, {}, {"variables": [{"variable_id": "V1"}]}, {},
        llm_call=callback, settings={"max_supplement_rounds": 0},
    )
    assert [item["definition_id"] for item in result["definitions"]] == ["D1", "G1_V1"]
    assert result["definitions"][0]["variable_references"] == ["V1"]
    assert not result["unknown_items"]
