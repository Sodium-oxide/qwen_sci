import json
from copy import deepcopy

import pytest

from test_formal_contracts_v2 import formal_plan
from src.agents.experiment_design_agent.definition_evidence import DefinitionEvidenceIndex, variable_groups, bounded_prompt_evidence
from src.agents.experiment_design_agent.formal_definition_resolver import (
    FormalDefinitionResolver,
    normalize_definition_conditions,
)


def card(number, statement="expansion density definition"):
    return {"card_id": f"EC{number}", "source_id": f"paper{number % 5}", "statement": statement,
            "evidence_excerpt": statement, "source_location": "Eq 1", "evidence_level": "fulltext"}


def resolution(variable="V1", symbol="rho", identifier="D1"):
    definition = deepcopy(formal_plan()["definitions"][0])
    definition.update(variable_references=[variable], symbol=symbol, definition_id=identifier)
    return {"schema_version": "formal_definition_resolution_v1", "definitions": [definition], "model_relations": [], "unknown_items": []}


def input_payload(prompt):
    return json.loads(prompt.split("INPUT_JSON:\n", 1)[1])


def test_retrieval_bounds_diversity_and_irrelevant_cards():
    cards = [card(number) for number in range(283)] + [card(400, "unrelated spectral flux")]
    index = DefinitionEvidenceIndex(cards)
    selected = index.select("expansion", limit=100)
    assert len(selected) == 40
    assert len({record["source_id"] for record in selected[:5]}) == 5
    assert "EC400" not in {record["card_id"] for record in selected}
    assert index.select("nonmatching") == []
    selected = index.select("expansion", max_chars=500)
    assert sum(len(json.dumps(record, ensure_ascii=False, sort_keys=True)) for record in selected) <= 500


def test_grouping_uses_claim_links_and_dependency():
    variables = [{"variable_id": "V1", "name": "density", "claim_links": ["C1"]},
                 {"variable_id": "V2", "name": "spectrum"},
                 {"variable_id": "V3", "name": "expansion", "depends_on": ["V1"]}]
    assert [record["variable_id"] for record in variable_groups(variables, 2)[0]] == ["V1", "V3"]


def test_supplement_uses_new_cards_and_previous_candidate():
    calls = []

    def callback(prompt, **kwargs):
        payload = input_payload(prompt)
        calls.append(payload)
        result = resolution()
        if len(calls) == 1:
            result["definitions"][0].update(definition_status="unresolved", origin="unresolved")
            result["evidence_requests"] = [{"query": "spectral opacity", "reason": "Need an opacity relation"}]
        return result

    result = FormalDefinitionResolver().resolve({}, {}, {"variables": [{"variable_id": "V1", "name": "density"}]},
        {"evidence_cards": [card(1), card(2, "spectral opacity definition")]}, llm_call=callback,
        settings={"initial_cards": 1})
    assert len(calls) == 2
    assert calls[0]["evidence_cards"][0]["card_id"] == "EC1"
    assert calls[1]["evidence_cards"][0]["card_id"] == "EC2"
    assert calls[1]["previous_candidate"]["evidence_requests"]
    assert result["definitions"][0]["definition_status"] == "specified"


def test_rejects_reference_to_unseen_card():
    result = resolution()
    result["definitions"][0].update(origin="source_grounded", source_refs=[{"card_id": "EC2", "locator": "Eq 1", "quote": "spectral opacity"}])
    with pytest.raises(ValueError, match="not_grounded"):
        FormalDefinitionResolver().resolve({}, {}, {"variables": [{"variable_id": "V1", "name": "density"}]},
            {"evidence_cards": [card(1), card(2, "spectral opacity")]}, llm_call=lambda *args, **kwargs: result,
            settings={"initial_cards": 1})


def test_normalizes_unambiguous_condition_shapes_without_dropping_definition():
    payload = resolution()
    definition = payload["definitions"][0]
    definition["conditions"] = {"condition": "x > 0"}
    definition["condition_expressions"] = {"op": "gt", "args": [{"symbol": "x"}, {"number": "0"}]}

    normalized, changes = normalize_definition_conditions(payload)

    assert normalized["definitions"][0]["conditions"] == ["x > 0"]
    assert normalized["definitions"][0]["condition_expressions"] == [{"op": "gt", "args": [{"symbol": "x"}, {"number": "0"}]}]
    assert changes == ["D1.conditions", "D1.condition_expressions"]
    assert normalized["definitions"][0]["definition_status"] == "specified"


def test_normalizes_readable_expression_and_records_encoding_gap():
    payload = resolution()
    payload["definitions"][0]["conditions"] = "x > 0"
    payload["definitions"][0]["condition_expressions"] = "x > 0"

    normalized, _ = normalize_definition_conditions(payload)

    definition = normalized["definitions"][0]
    assert definition["conditions"] == ["x > 0"]
    assert definition["condition_expressions"] == []
    assert definition["verification_readiness"] == "requires_encoding"
    assert normalized["unknown_items"][0]["status"] == "needs_human_input"


def test_preserves_unrecognized_condition_object_with_encoding_diagnostic():
    payload = resolution()
    payload["definitions"][0]["conditions"] = {"lower_bound": 0, "upper_bound": 1}

    normalized, _ = normalize_definition_conditions(payload)

    assert normalized["definitions"][0]["conditions"] == ['{"lower_bound":0,"upper_bound":1}']
    assert normalized["definitions"][0]["verification_readiness"] == "requires_encoding"
    assert normalized["unknown_items"][0]["status"] == "needs_human_input"
    FormalDefinitionResolver._validate(normalized, {})


def test_shape_repair_does_not_trigger_redundant_supplement_round():
    calls = []

    def callback(prompt, **kwargs):
        calls.append(prompt)
        payload = resolution()
        payload["definitions"][0]["conditions"] = {"lower_bound": 0}
        payload["definitions"][0]["condition_expressions"] = {"lower_bound": {"number": "0"}}
        return payload

    FormalDefinitionResolver().resolve(
        {}, {}, {"variables": [{"variable_id": "V1", "name": "density"}]},
        {"evidence_cards": [card(1)]}, llm_call=callback,
        settings={"max_supplement_rounds": 2},
    )
    assert len(calls) == 1


def test_checkpoint_reuses_successful_group_after_failure(tmp_path):
    calls = []
    variables = [{"variable_id": "V1", "name": "density"}, {"variable_id": "V2", "name": "spectrum"}]
    settings = {"checkpoint": {"root": str(tmp_path), "enabled": True}, "variables_per_group": 1}

    def callback(prompt, **kwargs):
        payload = input_payload(prompt)
        calls.append(payload)
        if "candidates" in payload:
            return payload["candidates"]
        variable = payload["variable_claim_model"]["variables"][0]["variable_id"]
        if variable == "V2" and len(calls) == 2:
            raise RuntimeError("interrupted")
        return resolution(variable, "rho" if variable == "V1" else "flux", "D1" if variable == "V1" else "D2")

    resolver = FormalDefinitionResolver()
    with pytest.raises(Exception, match="interrupted"):
        resolver.resolve({}, {}, {"variables": variables}, {}, llm_call=callback, settings=settings)
    result = resolver.resolve({}, {}, {"variables": variables}, {}, llm_call=callback, settings=settings)
    assert len(calls) == 4
    assert len(result["definitions"]) == 2
    assert result["retrieval_audit"][0]["cache_hit"]


def test_missing_symbols_and_cycles_remain_unresolved():
    payload = resolution()
    payload["definitions"][0]["formal_expression"] = {"symbol": "missing"}
    merged = FormalDefinitionResolver._merge(payload)
    assert merged["definitions"][0]["verification_readiness"] == "blocked"
    payload = resolution()
    payload["definitions"][0]["depends_on"] = ["D1"]
    assert FormalDefinitionResolver._merge(payload)["unknown_items"]


def test_oversized_context_stops_before_llm():
    def callback(*args, **kwargs):
        pytest.fail("Oversized request must not reach LLM")

    with pytest.raises(ValueError, match="budget"):
        FormalDefinitionResolver().resolve({"text": "a" * 10000}, {}, {"variables": []}, {},
            llm_call=callback, settings={"max_prompt_chars": 1000})


def test_nested_prompt_removes_duplicate_evidence_but_preserves_registry():
    cards = [card(number) for number in range(283)]
    payload = {"evidence_bundle": {"evidence_cards": cards}, "knowledge": {"evidence_cards_by_id": {record["card_id"]: record for record in cards}}}
    bounded = bounded_prompt_evidence(payload, "density")
    assert len(bounded["retrieved_evidence_cards"]) == 40
    assert len(bounded["knowledge"]["evidence_cards_by_id"]) == 283
    assert all(set(record) == {"card_id"} for record in bounded["evidence_bundle"]["evidence_cards"])
    assert payload["evidence_bundle"]["evidence_cards"][0]["statement"]


def test_conflict_does_not_discard_independent_definitions():
    payload = resolution()
    alternative = resolution("V2", "rho", "D2")["definitions"][0]
    alternative["unit"] = "kg"
    independent = resolution("V3", "flux", "D3")["definitions"][0]
    payload["definitions"].extend([alternative, independent])
    merged = FormalDefinitionResolver._merge(payload)
    assert merged["definitions"][0]["definition_status"] == "unresolved"
    assert merged["definitions"][0]["variable_references"] == ["V1", "V2"]
    assert merged["definitions"][1]["definition_status"] == "specified"
    assert merged["unknown_items"]
