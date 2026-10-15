import json
from copy import deepcopy

import pytest

from test_formal_contracts_v2 import formal_plan
from src.agents.experiment_design_agent.formal_contracts import DEFINITION_TEXT_CONTRACT
from src.agents.experiment_design_agent.formal_definition_resolver import (
    DEFINITION_PROMPT, RECONCILIATION_REVIEW_PROMPT, FormalDefinitionResolver,
    expand_compact_resolution, normalize_model_relation_formats,
)
from src.agents.experiment_design_agent.formal_dependency import declared_dependencies
from src.agents.experiment_design_agent.formal_object_registry import inspect_dependency_graph
from src.agents.experiment_design_agent.formal_verification import build_verification_task
from test_formal_plan_recovery import encoded_relation
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


@pytest.mark.parametrize("wire_format", [False, True])
def test_relation_prerequisites_survive_existing_dependencies_and_cache_replay(tmp_path, wire_format):
    payload = {"schema_version": "formal_definition_resolution_v1", "definitions": formal_plan()["definitions"],
               "model_relations": [encoded_relation(premises=["D1", "A_missing", "Finite energy budget"],
                                                    conditions=["Existing scope condition"])], "unknown_items": []}
    if wire_format:
        payload["wire_format"] = "formal_definition_wire_v1"
    calls = []
    def callback(prompt, **_kwargs):
        request = json.loads(prompt.split("INPUT_JSON:\n", 1)[1])
        assert "depends_on" in request["relation_fields"]
        assert "premises" not in request["relation_fields"]
        calls.append(prompt)
        return deepcopy(payload)
    settings = {"max_supplement_rounds": 0, "checkpoint": {"enabled": True, "root": str(tmp_path)}}
    resolver = FormalDefinitionResolver()
    arguments = ({}, {}, {"variables": [{"variable_id": "V1"}]}, {})
    first = resolver.resolve(*arguments, llm_call=callback, settings=settings)
    second = resolver.resolve(*arguments, llm_call=callback, settings=settings)
    assert len(calls) == 1
    for result in (first, second):
        relation = result["model_relations"][0]
        assert relation["depends_on"] == ["D1", "A_missing"]
        assert relation["conditions"] == ["Existing scope condition", "Finite energy budget"]
        assert json.loads(relation["format_originals"]["premises"]) == payload["model_relations"][0]["premises"]
        assert "premises" not in relation
        assert result["object_registry_diagnostics"]["missing_definition_reference_count"] == 1
        assert result["object_registry_diagnostics"]["textual_premise_count"] == 1


def test_raw_relation_graph_distinguishes_text_and_explicit_missing_ids():
    payload = {"definitions": formal_plan()["definitions"], "model_relations": [encoded_relation(
        premises=["D1", "A_missing", "Finite power budget", {"object_id": "external definition"}],
    )]}
    diagnostic = inspect_dependency_graph(payload)
    assert declared_dependencies(payload["model_relations"][0]) == {"D1", "A_missing", "external definition"}
    assert diagnostic["missing_premise_reference_count"] == 2
    assert diagnostic["textual_premise_count"] == 1
    assert {item["missing_id"] for item in diagnostic["missing_premise_references"]} == {"A_missing", "external definition"}


def test_relation_structured_prerequisites_keep_expressions_and_are_idempotent():
    expression = {"op": "gt", "args": [{"symbol": "x"}, {"number": "0"}]}
    payload = {"wire_format": "formal_definition_wire_v1", "definitions": [], "unknown_items": [],
               "model_relations": [encoded_relation(premises=[
                   {"definition_id": "D2"}, {"text": "x is positive", "formal_expression": expression},
               ])]}
    expanded = expand_compact_resolution(payload)
    normalized = normalize_model_relation_formats(expanded)
    relation = normalized["model_relations"][0]
    assert relation["depends_on"] == ["D1", "D2"]
    assert relation["conditions"] == ["x is positive"]
    assert relation["condition_expressions"] == [expression]
    assert normalize_model_relation_formats(normalized) == normalized


def test_relation_uninterpretable_prerequisite_is_archived_and_diagnosed():
    original = [{"ref": ["invalid"]}, 17, "Finite energy budget"]
    normalized = normalize_model_relation_formats({"model_relations": [encoded_relation(premises=original)], "unknown_items": []})
    relation = normalized["model_relations"][0]
    assert json.loads(relation["format_originals"]["premises"]) == original
    assert relation["conditions"] == ["Finite energy budget"]
    assert "premises" in relation["machine_encoding_issues"]
    assert any(item["field"] == "premises" for item in normalized["unknown_items"])
    assert inspect_dependency_graph(normalized)["uninterpreted_premise_count"] == 2


def test_relation_same_encoding_with_different_text_keeps_condition_pairs():
    expression = {"op": "gt", "args": [{"symbol": "x"}, {"number": "0"}]}
    payload = {"unknown_items": [], "model_relations": [encoded_relation(
        conditions=["x is positive"], condition_expressions=[expression],
        premises=[{"text": "x > 0", "formal_expression": expression},
                  {"text": "x > 0", "formal_expression": expression}],
    )]}
    relation = normalize_model_relation_formats(payload)["model_relations"][0]
    assert relation["conditions"] == ["x is positive", "x > 0"]
    assert relation["condition_expressions"] == [expression, expression]


def test_relation_new_premise_encoding_survives_legacy_single_expression():
    positive = {"op": "gt", "args": [{"symbol": "x"}, {"number": "0"}]}
    bounded = {"op": "lt", "args": [{"symbol": "x"}, {"number": "10"}]}
    payload = {"unknown_items": [], "model_relations": [encoded_relation(
        conditions=["x is positive"], condition_expressions=positive,
        premises=[{"text": "x is bounded", "formal_expression": bounded}],
    )]}
    relation = normalize_model_relation_formats(payload)["model_relations"][0]
    assert relation["conditions"] == ["x is positive", "x is bounded"]
    assert relation["condition_expressions"] == [positive, bounded]


def test_retained_text_prerequisite_reaches_proof_context_and_requires_encoding():
    from src.agents.experiment_design_agent.formal_reasoning_planner import _compact_formal_inputs, _skeleton_formal_inputs
    from src.agents.experiment_design_agent.formal_plan_recovery import recover_formal_plan
    from src.agents.experiment_design_agent.formal_contracts import author_formal_payload
    plan = formal_plan()
    plan["model_relations"] = [encoded_relation(premises=["Finite energy budget"])]
    plan["propositions"][0]["premises"] = ["R1"]
    recovered = recover_formal_plan(normalize_model_relation_formats(plan))
    inputs = _skeleton_formal_inputs(_compact_formal_inputs(recovered, max_unknown_items=30))
    assert inputs["model_relations"][0]["conditions"] == ["Finite energy budget"]
    assert "missing_condition_encoding:R1" in build_verification_task(recovered, "P1", "z3")["blockers"]
    assert author_formal_payload(recovered)["model_relations"][0]["conditions"] == ["Finite energy budget"]


def test_explicit_known_reference_with_spaces_is_not_reclassified_as_text():
    payload = {"definitions": [{"definition_id": "external definition"}], "unknown_items": [],
               "model_relations": [encoded_relation(premises=["external definition"])]}
    diagnostic = inspect_dependency_graph(payload)
    assert diagnostic["textual_premise_count"] == 0
    assert diagnostic["missing_premise_reference_count"] == 0
    normalized = normalize_model_relation_formats(payload)
    assert normalized["model_relations"][0]["depends_on"] == ["D1", "external definition"]


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
