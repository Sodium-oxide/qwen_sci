import json
from copy import deepcopy
from io import StringIO
from threading import Barrier, Lock
from time import sleep

import pytest

from test_formal_contracts_v2 import formal_plan
from src.agents.experiment_design_agent.definition_evidence import DefinitionEvidenceIndex, variable_groups, bounded_prompt_evidence
from src.agents.experiment_design_agent.formal_definition_resolver import (
    FormalDefinitionResolver,
    normalize_definition_conditions,
    normalize_model_relations,
    namespace_group_records,
)
import src.agents.experiment_design_agent.formal_definition_resolver as formal_definition_resolver_module
from src.agents.experiment_design_agent.run_logging import ExperimentDesignRunLogger


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


def test_uncatalogued_card_reference_does_not_discard_definition():
    result = resolution()
    result["definitions"][0].update(origin="source_grounded", source_refs=[{"card_id": "EC2", "locator": "Eq 1", "quote": "spectral opacity"}])
    resolved = FormalDefinitionResolver().resolve(
        {}, {}, {"variables": [{"variable_id": "V1", "name": "density"}]},
        {"evidence_cards": [card(1), card(2, "spectral opacity")]},
        llm_call=lambda *args, **kwargs: result,
        settings={"initial_cards": 1},
    )
    assert resolved["definitions"][0]["source_refs"][0]["card_id"] == "EC2"


@pytest.mark.parametrize("reference", [
    {"card_id": "EC1", "locator": "Eq 1", "quote": "The paper defines a density measure."},
    {"card_id": "EC1", "locator": "Eq 1"},
])
def test_source_reference_accepts_paraphrase_or_no_quote(reference):
    result = resolution()
    result["definitions"][0].update(origin="source_grounded", source_refs=[reference])

    resolved = FormalDefinitionResolver().resolve(
        {}, {}, {"variables": [{"variable_id": "V1", "name": "density"}]},
        {"evidence_cards": [card(1)]}, llm_call=lambda *_args, **_kwargs: result,
        settings={"max_supplement_rounds": 0},
    )

    assert resolved["definitions"][0]["source_refs"] == [reference]


def test_source_reference_still_requires_card_locator():
    result = resolution()
    result["definitions"][0].update(
        origin="source_grounded",
        source_refs=[{"card_id": "EC1", "locator": "Eq 2", "quote": "Paraphrased"}],
    )

    resolved = FormalDefinitionResolver().resolve(
        {}, {}, {"variables": [{"variable_id": "V1", "name": "density"}]},
        {"evidence_cards": [card(1)]}, llm_call=lambda *_args, **_kwargs: result,
        settings={"max_supplement_rounds": 0},
    )
    assert any("definition_source_locator_not_grounded" in item["reason"] for item in resolved["unknown_items"])


def test_cross_group_definition_is_retained_as_warning():
    payload = resolution()
    payload["definitions"][0]["definition_id"] = "G3_S_E"
    payload["definitions"][0]["variable_references"] = ["V1", "V3"]
    logger = ExperimentDesignRunLogger("cross-group-warning", console_stream=StringIO())

    resolved = FormalDefinitionResolver().resolve(
        {}, {}, {"variables": [
            {"variable_id": "V1", "name": "first"},
            {"variable_id": "V2", "name": "second"},
            {"variable_id": "V3", "name": "third"},
        ]},
        {}, llm_call=lambda *_args, **_kwargs: payload,
        settings={"variables_per_group": 2, "max_supplement_rounds": 0}, logger=logger,
    )

    assert resolved["schema_version"] == "formal_definition_resolution_v1"
    assert any("references_variables_outside_group" in item["reason"] for item in resolved["unknown_items"])
    assert all(record["status"] != "DEGRADED" for record in logger.records if record["stage"] == "formal_definition_resolver")


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


def test_malformed_relations_do_not_discard_valid_definitions():
    payload = resolution()
    payload["model_relations"] = [
        {"relation_id": None, "statement": "rho is positive", "depends_on": []},
        None,
        "rho = mass / volume",
    ]
    logger = ExperimentDesignRunLogger("malformed-relations", console_stream=StringIO())
    result = FormalDefinitionResolver().resolve(
        {}, {}, {"variables": [{"variable_id": "V1", "name": "density"}]},
        {}, llm_call=lambda *_args, **_kwargs: payload,
        settings={"max_supplement_rounds": 0}, logger=logger,
    )
    assert result["definitions"][0]["definition_id"] == "D1"
    assert result["model_relations"][0]["relation_id"] == "G1_R1"
    assert result["model_relations"][0]["statement"] == "rho is positive"
    assert result["model_relations"][1]["relation_id"] == "G1_R3"
    assert result["model_relations"][1]["statement"] == "rho = mass / volume"
    assert result["model_relations"][1]["status"] == "unresolved"
    assert result["unknown_items"][0]["field_path"] == "model_relations[1]"
    completed = next(item for item in logger.records if item["event"] == "group_completed")
    assert completed["status"] == "WARNING"
    assert completed["relation_review_count"] == 2


def test_relation_validation_reports_index_and_type():
    payload = resolution()
    payload["model_relations"] = [None, {"relation_id": 2}]
    with pytest.raises(ValueError, match=r"model_relations\[0\]: expected object, got NoneType") as error:
        FormalDefinitionResolver._validate(payload, {})
    assert "model_relations[1].relation_id: expected nonempty string, got int" in str(error.value)
    normalized, repaired, quarantined = normalize_model_relations(payload, id_prefix="G1_")
    assert normalized["model_relations"] == [{"relation_id": "G1_R2"}]
    assert repaired and quarantined


def test_group_namespace_updates_relation_dependencies():
    payload = resolution()
    payload["model_relations"] = [
        {"relation_id": "R1", "depends_on": []},
        {"relation_id": "R2", "depends_on": ["R1", "D1"]},
    ]
    normalized, renamed = namespace_group_records(payload, id_prefix="G2_", primary_ids={"D1"})
    assert renamed == ["R1->G2_R1", "R2->G2_R2"]
    assert normalized["model_relations"][1]["depends_on"] == ["G2_R1", "D1"]
    assert payload["model_relations"][0]["relation_id"] == "R1"


def test_quarantined_nested_relations_retain_bounded_raw_excerpt():
    payload = resolution()
    payload["model_relations"] = [[{"relation_id": "R1"}, {"relation_id": "R2"}]]
    normalized, _repaired, quarantined = normalize_model_relations(payload, id_prefix="G1_")
    assert normalized["model_relations"] == []
    assert quarantined
    assert '"relation_id":"R2"' in normalized["unknown_items"][0]["raw_excerpt"]


def test_supplement_stops_after_unchanged_gaps_and_caps_new_cards():
    calls = []

    def callback(prompt, **_kwargs):
        calls.append(input_payload(prompt))
        result = resolution()
        result["definitions"][0].update(definition_status="unresolved", origin="unresolved")
        result["evidence_requests"] = [{"query": "density", "reason": "Need a definition"}]
        return result

    FormalDefinitionResolver().resolve(
        {}, {}, {"variables": [{"variable_id": "V1", "name": "density"}]},
        {"evidence_cards": [card(number) for number in range(20)]},
        llm_call=callback,
        settings={"initial_cards": 1, "supplement_cards": 10, "max_supplement_rounds": 2},
    )
    assert len(calls) == 2
    assert len(calls[1]["evidence_cards"]) == 10


def test_invalid_reconciliation_keeps_valid_group_relations():
    variables = [{"variable_id": "V1", "name": "density"},
                 {"variable_id": "V2", "name": "spectrum"}]

    def callback(prompt, **_kwargs):
        payload = input_payload(prompt)
        if "candidate_catalog" in payload:
            return {"issues": "invalid"}
        variable = payload["variable_claim_model"]["variables"][0]["variable_id"]
        result = resolution(variable, "rho" if variable == "V1" else "flux",
                            "D1" if variable == "V1" else "D2")
        result["model_relations"] = [{"relation_id": "R1",
                                      "statement": "rho relation" if variable == "V1" else "flux relation",
                                      "depends_on": [], "status": "unresolved", "source_refs": []}]
        return result

    result = FormalDefinitionResolver().resolve(
        {}, {}, {"variables": variables}, {}, llm_call=callback,
        settings={"variables_per_group": 1, "max_supplement_rounds": 0},
    )
    assert {item["definition_id"] for item in result["definitions"]} == {"D1", "D2"}
    assert [item["relation_id"] for item in result["model_relations"]] == ["G1_R1", "G2_R1"]
    assert [item["statement"] for item in result["model_relations"]] == ["rho relation", "flux relation"]
    assert any(item["field_path"] == "definition_reconciliation" for item in result["unknown_items"])


def test_reconciliation_review_preserves_source_references():
    variables = [{"variable_id": "V1", "name": "density"},
                 {"variable_id": "V2", "name": "spectrum"}]
    long_quote = "PROVENANCE_ONLY " * 5000
    reconciliation_prompts = []

    def callback(prompt, **_kwargs):
        payload = input_payload(prompt)
        if "candidate_catalog" in payload:
            reconciliation_prompts.append(prompt)
            return {"issues": []}
        variable = payload["variable_claim_model"]["variables"][0]["variable_id"]
        result = resolution(variable, "rho" if variable == "V1" else "flux",
                            "D1" if variable == "V1" else "D2")
        result["definitions"][0].update(
            origin="source_grounded",
            source_refs=[{"card_id": payload["evidence_cards"][0]["card_id"],
                          "locator": "Eq 1", "quote": long_quote}],
        )
        return result

    result = FormalDefinitionResolver().resolve(
        {}, {}, {"variables": variables},
        {"evidence_cards": [card(1, "density"), card(2, "spectrum")]},
        llm_call=callback,
        settings={"variables_per_group": 1, "max_supplement_rounds": 0},
    )

    assert result["retrieval_audit"][-1]["status"] == "completed"
    assert len(reconciliation_prompts) == 1
    assert "PROVENANCE_ONLY" not in reconciliation_prompts[0]
    assert len(reconciliation_prompts[0]) < 120000
    assert result["definitions"][0]["source_refs"][0]["quote"] == long_quote


def test_reconciliation_review_marks_only_reported_conflicts():
    variables = [{"variable_id": "V1", "name": "density"}, {"variable_id": "V2", "name": "spectrum"}]

    def callback(prompt, **_kwargs):
        payload = input_payload(prompt)
        if "candidate_catalog" in payload:
            assert [item["definition_id"] for item in payload["candidate_catalog"]["definitions"]] == ["D1", "D2"]
            return {"issues": [{"record_ids": ["D1"], "reason": "Its domain conflicts with the selected model."}]}
        variable_id = payload["variable_claim_model"]["variables"][0]["variable_id"]
        number = int(variable_id[1:])
        return resolution(variable_id, f"symbol{number}", f"D{number}")

    result = FormalDefinitionResolver().resolve(
        {}, {}, {"variables": variables}, {}, llm_call=callback,
        settings={"variables_per_group": 1, "max_supplement_rounds": 0},
    )

    assert result["definitions"][0]["verification_readiness"] == "blocked"
    assert result["definitions"][1]["definition_status"] == "specified"
    assert any(item["field_path"] == "definition_reconciliation.D1" for item in result["unknown_items"])


def test_checkpoint_reuses_successful_group_after_failure(tmp_path):
    calls = []
    failed_v2 = False
    lock = Lock()
    variables = [{"variable_id": "V1", "name": "density"}, {"variable_id": "V2", "name": "spectrum"}]
    settings = {"checkpoint": {"root": str(tmp_path), "enabled": True}, "variables_per_group": 1}

    def callback(prompt, **kwargs):
        nonlocal failed_v2
        payload = input_payload(prompt)
        with lock:
            calls.append(payload)
        if "candidate_catalog" in payload:
            return {"issues": []}
        variable = payload["variable_claim_model"]["variables"][0]["variable_id"]
        if variable == "V2":
            with lock:
                if not failed_v2:
                    failed_v2 = True
                    raise RuntimeError("interrupted")
        return resolution(variable, "rho" if variable == "V1" else "flux", "D1" if variable == "V1" else "D2")

    resolver = FormalDefinitionResolver()
    with pytest.raises(Exception, match="interrupted"):
        resolver.resolve({}, {}, {"variables": variables}, {}, llm_call=callback, settings=settings)
    result = resolver.resolve({}, {}, {"variables": variables}, {}, llm_call=callback, settings=settings)
    assert len(calls) == 4
    assert len(result["definitions"]) == 2
    assert result["retrieval_audit"][0]["cache_hit"]


def test_degraded_definition_groups_are_not_written_or_reused(monkeypatch):
    degraded = resolution()
    degraded["definitions"][0].update(definition_status="unresolved", verification_readiness="blocked", origin="unresolved")
    degraded["unknown_items"] = [{"field_path": "definitions.D1", "reason": "requires review", "status": "needs_human_input"}]

    class RecordingCache:
        def __init__(self, cached=None):
            self.cached = deepcopy(cached)
            self.read_count = 0
            self.writes = []
            self.offline = False

        def read(self, *_args, **_kwargs):
            self.read_count += 1
            return deepcopy(self.cached)

        def write(self, _namespace, _identity, payload, **_kwargs):
            self.writes.append(deepcopy(payload))
            return "snapshot"

    cache = RecordingCache()
    monkeypatch.setattr(formal_definition_resolver_module, "ExperimentDesignCache", lambda _settings: cache)
    result = FormalDefinitionResolver().resolve(
        {}, {}, {"variables": [{"variable_id": "V1", "name": "density"}]}, {},
        llm_call=lambda *_args, **_kwargs: degraded,
        settings={"checkpoint": {"enabled": True}, "max_supplement_rounds": 0},
    )
    assert result["unknown_items"]
    assert cache.writes == []

    cache.cached = degraded
    recovered = resolution()
    result = FormalDefinitionResolver().resolve(
        {}, {}, {"variables": [{"variable_id": "V1", "name": "density"}]}, {},
        llm_call=lambda *_args, **_kwargs: recovered,
        settings={"checkpoint": {"enabled": True}, "max_supplement_rounds": 0},
    )
    assert result["definitions"][0]["definition_status"] == "specified"
    assert cache.read_count >= 2
    assert cache.writes[-1]["definitions"][0]["definition_status"] == "specified"


def test_definition_groups_run_three_at_a_time_and_merge_in_order():
    barrier = Barrier(3)
    lock = Lock()
    active = 0
    max_active = 0

    def callback(prompt, **_kwargs):
        nonlocal active, max_active
        payload = input_payload(prompt)
        if "candidate_catalog" in payload:
            return {"issues": []}
        group_number = int(payload["id_prefix"].strip("G_"))
        with lock:
            active += 1
            max_active = max(max_active, active)
        try:
            if group_number <= 3:
                barrier.wait(timeout=5)
            sleep(0.02)
            return resolution(f"V{group_number}", f"symbol{group_number}", f"D{group_number}")
        finally:
            with lock:
                active -= 1

    result = FormalDefinitionResolver().resolve(
        {}, {}, {"variables": [{"variable_id": f"V{number}", "name": f"quantity{number}"} for number in range(1, 5)]},
        {}, llm_call=callback,
        settings={"variables_per_group": 1, "max_supplement_rounds": 0, "parallel_workers": 10},
    )

    assert max_active == 3
    assert [item["definition_id"] for item in result["definitions"]] == ["D1", "D2", "D3", "D4"]
    assert [item["group"] for item in result["retrieval_audit"][:4]] == [1, 2, 3, 4]


def test_dependent_definition_group_receives_completed_definitions():
    variables = [
        {"variable_id": "V1", "name": "density"},
        {"variable_id": "V2", "name": "expansion", "depends_on": ["V1"]},
        {"variable_id": "V3", "name": "spectrum"},
    ]
    seen = {}

    def callback(prompt, **_kwargs):
        payload = input_payload(prompt)
        if "candidate_catalog" in payload:
            return {"issues": []}
        variable_id = payload["variable_claim_model"]["variables"][0]["variable_id"]
        seen[variable_id] = [item["definition_id"] for item in payload["existing_definitions"]]
        number = int(variable_id[1:])
        return resolution(variable_id, f"symbol{number}", f"D{number}")

    result = FormalDefinitionResolver().resolve(
        {}, {}, {"variables": variables}, {}, llm_call=callback,
        settings={"variables_per_group": 1, "max_supplement_rounds": 0},
    )

    assert "D1" in seen["V2"]
    assert [item["definition_id"] for item in result["definitions"]] == ["D1", "D2", "D3"]


def test_missing_symbols_and_cycles_remain_unresolved():
    payload = resolution()
    payload["definitions"][0]["formal_expression"] = {"symbol": "missing"}
    merged = FormalDefinitionResolver._merge(payload)
    assert merged["definitions"][0]["verification_readiness"] == "blocked"
    payload = resolution()
    payload["definitions"][0]["depends_on"] = ["D1"]
    assert FormalDefinitionResolver._merge(payload)["unknown_items"]


def test_merge_resolves_definition_ids_and_unique_function_names():
    payload = resolution(symbol="t_fo", identifier="G2_primitive_freeze_out_time")
    function = resolution("V2", "A_spec(t)", "D2")["definitions"][0]
    dependent = resolution("V3", "U_act", "D3")["definitions"][0]
    dependent["symbol_references"] = ["G2_primitive_freeze_out_time", "A_spec", "missing"]
    payload["definitions"].extend([function, dependent])

    merged = FormalDefinitionResolver._merge(payload)

    assert dependent["symbol_references"] == ["t_fo", "A_spec(t)", "missing"]
    assert dependent["verification_readiness"] == "blocked"
    assert any("missing" in item["reason"] for item in merged["unknown_items"])


def test_merge_does_not_guess_ambiguous_function_reference():
    payload = resolution(symbol="A_spec(t)")
    payload["definitions"].append(resolution("V2", "A_spec(u)", "D2")["definitions"][0])
    dependent = resolution("V3", "U_act", "D3")["definitions"][0]
    dependent["symbol_references"] = ["A_spec"]
    payload["definitions"].append(dependent)

    FormalDefinitionResolver._merge(payload)

    assert dependent["symbol_references"] == ["A_spec"]
    assert dependent["verification_readiness"] == "blocked"


def test_merge_does_not_guess_id_function_name_collision():
    payload = resolution(symbol="other", identifier="A_spec")
    payload["definitions"].append(resolution("V2", "A_spec(t)", "D2")["definitions"][0])
    dependent = resolution("V3", "U_act", "D3")["definitions"][0]
    dependent["symbol_references"] = ["A_spec"]
    payload["definitions"].append(dependent)

    FormalDefinitionResolver._merge(payload)

    assert dependent["symbol_references"] == ["A_spec"]
    assert dependent["verification_readiness"] == "blocked"


def test_large_definition_context_reaches_llm():
    prompts = []

    def callback(prompt, **_kwargs):
        prompts.append(prompt)
        return resolution()

    result = FormalDefinitionResolver().resolve(
        {"text": "a" * 10000}, {}, {"variables": [{"variable_id": "V1", "name": "density"}]}, {},
        llm_call=callback, settings={"max_supplement_rounds": 0},
    )

    assert len(prompts) == 1
    assert len(prompts[0]) > 10000
    assert result["definitions"][0]["definition_status"] == "specified"


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
