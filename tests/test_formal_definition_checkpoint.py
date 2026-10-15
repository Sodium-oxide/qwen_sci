from copy import deepcopy
import json

import pytest

from test_definition_evidence_retrieval import input_payload, resolution
from src.agents.experiment_design_agent.formal_definition_resolver import FormalDefinitionResolver
from src.agents.experiment_design_agent.cache import ExperimentDesignCache
from src.agents.experiment_design_agent.run_logging import ExperimentDesignRunLogger
import src.agents.experiment_design_agent.formal_definition_resolver as resolver_module


def checkpoint_settings(root, **overrides):
    return {"checkpoint": {"enabled": True, "root": str(root)},
            "max_supplement_rounds": 0, **overrides}


def unexpected_request(*_args, **_kwargs):
    pytest.fail("The completed checkpoint should avoid another LLM request")


def test_partial_group_resumes_only_missing_definition_then_reuses_completion(tmp_path):
    variables = [{"variable_id": "V1", "claim_links": ["C1"]},
                 {"variable_id": "V2", "claim_links": ["C1"]}]
    resolver = FormalDefinitionResolver()
    settings = checkpoint_settings(tmp_path)
    first = resolver.resolve({}, {}, {"variables": variables}, {},
                             llm_call=lambda *_args, **_kwargs: resolution(), settings=settings)
    assert [record["definition_id"] for record in first["definitions"]] == ["D1"]
    calls = []

    def repair(prompt, **_kwargs):
        request = input_payload(prompt)
        calls.append(request)
        assert request["request_mode"] == "targeted_patch"
        assert request["repair_targets"]["definition_ids"] == ["D2"]
        assert request["previous_candidate"]["definitions"][0]["definition_id"] == "D1"
        return resolution("V2", "temperature", "D2")

    second = resolver.resolve({}, {}, {"variables": variables}, {}, llm_call=repair,
                              settings={**settings, "max_supplement_rounds": 1})
    assert len(calls) == 1
    assert second["definitions"][0] == first["definitions"][0]
    assert {record["definition_id"] for record in second["definitions"]} == {"D1", "D2"}
    third = resolver.resolve({}, {}, {"variables": variables}, {},
                             llm_call=unexpected_request, settings=settings)
    assert third["definitions"] == second["definitions"]
    assert third["retrieval_audit"][0]["resumed"]


def test_supplement_failure_does_not_lose_saved_initial_group(tmp_path):
    variables = [{"variable_id": "V1", "claim_links": ["C1"]},
                 {"variable_id": "V2", "claim_links": ["C1"]}]
    resolver = FormalDefinitionResolver()
    settings = checkpoint_settings(tmp_path, max_supplement_rounds=1)

    def interrupted(prompt, **_kwargs):
        if input_payload(prompt).get("request_mode") == "targeted_patch":
            raise RuntimeError("Interrupted supplement")
        return resolution()

    first = resolver.resolve({}, {}, {"variables": variables}, {}, llm_call=interrupted, settings=settings)
    assert any("Interrupted supplement" in item["reason"] for item in first["unknown_items"])
    calls = []

    def repair(prompt, **_kwargs):
        request = input_payload(prompt)
        calls.append(request)
        assert request["request_mode"] == "targeted_patch"
        return resolution("V2", "temperature", "D2")

    second = resolver.resolve({}, {}, {"variables": variables}, {}, llm_call=repair, settings=settings)
    assert len(calls) == 1
    assert {record["definition_id"] for record in second["definitions"]} == {"D1", "D2"}


def test_unencoded_group_and_reference_requests_are_cached_with_diagnostics(tmp_path):
    payload = resolution()
    payload["definitions"][0]["verification_readiness"] = "requires_encoding"
    payload["unknown_items"] = [{"reason": "An open research question", "status": "needs_human_input"}]
    payload["evidence_requests"] = [{"query": "optional reference", "record_ids": ["D1"]}]
    resolver = FormalDefinitionResolver()
    settings = checkpoint_settings(tmp_path)
    variables = {"variables": [{"variable_id": "V1"}]}
    first = resolver.resolve({}, {}, variables, {}, llm_call=lambda *_args, **_kwargs: payload, settings=settings)
    second = resolver.resolve({}, {}, variables, {}, llm_call=unexpected_request, settings=settings)
    assert second["definitions"] == first["definitions"]
    assert second["definitions"][0]["verification_readiness"] == "requires_encoding"
    assert second["unknown_items"] == first["unknown_items"]
    assert list(tmp_path.glob("objects/definition_group_responses/*.json"))


def test_cached_cycles_remain_drafts(tmp_path):
    payload = resolution()
    payload["definitions"][0]["depends_on"] = ["D1"]
    variables = {"variables": [{"variable_id": "V1"}]}
    resolver = FormalDefinitionResolver()
    settings = checkpoint_settings(tmp_path)
    resolver.resolve({}, {}, variables, {}, llm_call=lambda *_args, **_kwargs: payload, settings=settings)
    restored = resolver.resolve({}, {}, variables, {}, llm_call=unexpected_request, settings=settings)
    assert restored["definitions"][0]["dependency_health"] == "cyclic"
    assert restored["definitions"][0]["depends_on"] == ["D1"]


@pytest.mark.parametrize("change", ["model", "provider", "topic", "variable", "evidence", "prompt"])
def test_checkpoint_identity_changes_require_fresh_generation(tmp_path, monkeypatch, change):
    resolver = FormalDefinitionResolver()
    settings = checkpoint_settings(tmp_path)
    brief = {"title": "Original topic"}
    variables = {"variables": [{"variable_id": "V1", "name": "density"}]}
    resolver.resolve(brief, {}, variables, {}, llm_call=lambda *_args, **_kwargs: resolution(),
                     settings=settings, cache_identity={"model": "first", "provider": "first"})
    if change == "prompt":
        monkeypatch.setattr(resolver_module, "DEFINITION_PROMPT", "Additional instruction.\n" + resolver_module.DEFINITION_PROMPT)
    changed_brief = {**brief, "title": "New topic"} if change == "topic" else brief
    changed_variables = deepcopy(variables)
    if change == "variable":
        changed_variables["variables"][0]["name"] = "temperature"
    evidence = {"evidence_cards": [{"card_id": "EC1", "statement": "density",
                                   "evidence_excerpt": "density", "source_id": "paper1"}]} if change == "evidence" else {}
    calls = []

    def generate(prompt, **_kwargs):
        calls.append(input_payload(prompt))
        return resolution()

    resolver.resolve(changed_brief, {}, changed_variables, evidence, llm_call=generate,
                     settings=settings, cache_identity={"model": "second" if change == "model" else "first",
                                                        "provider": "second" if change == "provider" else "first"})
    assert len(calls) == 1


def test_reconciliation_replays_initial_and_repair_patches_without_llm(tmp_path):
    variables = {"variables": [{"variable_id": "V1", "claim_links": ["C1"]},
                               {"variable_id": "V2", "claim_links": ["C1"]}]}
    settings = checkpoint_settings(tmp_path)
    calls = []

    def generate(prompt, **_kwargs):
        request = input_payload(prompt)
        calls.append(request)
        if request.get("request_mode") == "resolve_remaining_conflicts":
            return {"issues": [], "symbol_renames": [{"definition_id": "D2", "symbol": "y", "affected_ids": []}]}
        if "candidate_catalog" in request:
            return {"issues": [{"record_ids": ["D2"], "reason": "Duplicate symbol"}],
                    "repairs": [{"record_id": "D1", "fields": {"selection_reason": "Clarified convention"}}]}
        payload = resolution(symbol="x")
        payload["definitions"].extend(resolution("V2", "x", "D2")["definitions"])
        return payload

    resolver = FormalDefinitionResolver()
    first = resolver.resolve({}, {}, variables, {}, llm_call=generate, settings=settings)
    assert len(calls) == 3
    second = resolver.resolve({}, {}, variables, {}, llm_call=unexpected_request, settings=settings)
    assert second["definitions"] == first["definitions"]
    assert [record["symbol"] for record in second["definitions"]] == ["x", "y"]
    assert second["definitions"][0]["selection_reason"] == "Clarified convention"
    assert second["reconciliation_audit"] == first["reconciliation_audit"]
    snapshots = [json.loads(path.read_text(encoding="utf-8")) for path in
                 tmp_path.glob("objects/definition_reconciliation/*.json")]
    assert any(len(snapshot["payload"].get("patches", [])) == 2 for snapshot in snapshots)


def test_reconciliation_interruption_resumes_after_initial_patch(tmp_path):
    settings = checkpoint_settings(tmp_path)
    variables = {"variables": [{"variable_id": "V1", "claim_links": ["C1"]},
                               {"variable_id": "V2", "claim_links": ["C1"]}]}

    def interrupted(prompt, **_kwargs):
        request = input_payload(prompt)
        if request.get("request_mode") == "resolve_remaining_conflicts":
            raise RuntimeError("Interrupted coordination")
        if "candidate_catalog" in request:
            return {"issues": [{"record_ids": ["D2"], "reason": "Duplicate symbol"}]}
        payload = resolution(symbol="x")
        payload["definitions"].extend(resolution("V2", "x", "D2")["definitions"])
        return payload

    resolver = FormalDefinitionResolver()
    first = resolver.resolve({}, {}, variables, {}, llm_call=interrupted, settings=settings)
    assert any("Interrupted coordination" in item["reason"] for item in first["unknown_items"])
    calls = []

    def repair(prompt, **_kwargs):
        request = input_payload(prompt)
        calls.append(request)
        assert request["request_mode"] == "resolve_remaining_conflicts"
        return {"issues": [], "symbol_renames": [{"definition_id": "D2", "symbol": "y", "affected_ids": []}]}

    second = resolver.resolve({}, {}, variables, {}, llm_call=repair, settings=settings)
    assert len(calls) == 1
    assert [record["symbol"] for record in second["definitions"]] == ["x", "y"]


def test_read_only_partial_checkpoint_preserves_state_without_requesting_repairs(tmp_path):
    payload = resolution()
    payload["definitions"][0].update(definition_status="unresolved", verification_readiness="blocked", origin="unresolved")
    variables = {"variables": [{"variable_id": "V1"}]}
    resolver = FormalDefinitionResolver()
    settings = checkpoint_settings(tmp_path)
    resolver.resolve({}, {}, variables, {}, llm_call=lambda *_args, **_kwargs: payload, settings=settings)
    settings["checkpoint"]["mode"] = "read_only"
    restored = resolver.resolve({}, {}, variables, {}, llm_call=unexpected_request,
                                settings={**settings, "max_supplement_rounds": 1})
    assert restored["definitions"][0]["definition_status"] == "unresolved"
    assert restored["definitions"][0]["verification_readiness"] == "blocked"
    assert restored["unknown_items"]


def test_raw_response_survives_normalization_interruption_and_is_reused(tmp_path, monkeypatch):
    original_normalize = resolver_module.normalize_record_completeness
    variables = {"variables": [{"variable_id": "V1"}]}
    resolver = FormalDefinitionResolver()
    settings = checkpoint_settings(tmp_path)

    def interrupted(*_args, **_kwargs):
        raise RuntimeError("Interrupted normalization")

    monkeypatch.setattr(resolver_module, "normalize_record_completeness", interrupted)
    first = resolver.resolve({}, {}, variables, {}, llm_call=lambda *_args, **_kwargs: resolution(), settings=settings)
    assert any("Interrupted normalization" in item["reason"] for item in first["unknown_items"])
    assert list(tmp_path.glob("objects/definition_group_responses/*.json"))
    monkeypatch.setattr(resolver_module, "normalize_record_completeness", original_normalize)
    restored = resolver.resolve({}, {}, variables, {}, llm_call=unexpected_request, settings=settings)
    assert restored["definitions"][0]["definition_status"] == "specified"


def test_written_and_resumed_checkpoints_have_explicit_logs(tmp_path):
    logger = ExperimentDesignRunLogger("checkpoint-test")
    resolver = FormalDefinitionResolver()
    variables = {"variables": [{"variable_id": "V1"}]}
    settings = checkpoint_settings(tmp_path)
    resolver.resolve({}, {}, variables, {}, llm_call=lambda *_args, **_kwargs: resolution(),
                     settings=settings, logger=logger)
    restored = resolver.resolve({}, {}, variables, {}, llm_call=unexpected_request, settings=settings, logger=logger)
    assert any(record["event"] == "checkpoint_written" and record["namespace"] == "definition_group_progress"
               for record in logger.records)
    assert any(record["event"] == "group_resumed" and record["cache_hit"] for record in logger.records)
    assert restored["retrieval_audit"][0]["cache_hit"]


def test_checkpoint_write_failure_does_not_discard_generated_definitions(tmp_path, monkeypatch):
    def fail_write(*_args, **_kwargs):
        raise OSError("Checkpoint storage unavailable")

    monkeypatch.setattr(ExperimentDesignCache, "write", fail_write)
    logger = ExperimentDesignRunLogger("checkpoint-write-failure")
    restored = FormalDefinitionResolver().resolve(
        {}, {}, {"variables": [{"variable_id": "V1"}]}, {},
        llm_call=lambda *_args, **_kwargs: resolution(),
        settings=checkpoint_settings(tmp_path), logger=logger,
    )
    assert restored["definitions"][0]["definition_status"] == "specified"
    assert not restored["unknown_items"]
    assert any(record["event"] == "checkpoint_warning" for record in logger.records)


def test_invalid_review_is_archived_but_does_not_poison_reusable_checkpoint(tmp_path):
    settings = checkpoint_settings(tmp_path)
    variables = {"variables": [{"variable_id": "V1", "claim_links": ["C1"]},
                               {"variable_id": "V2", "claim_links": ["C1"]}]}

    def invalid_review(prompt, **_kwargs):
        request = input_payload(prompt)
        if "candidate_catalog" in request:
            return {"issues": [{"record_ids": ["missing"], "reason": "Unknown owner"}]}
        payload = resolution(symbol="x")
        payload["definitions"].extend(resolution("V2", "x", "D2")["definitions"])
        return payload

    resolver = FormalDefinitionResolver()
    resolver.resolve({}, {}, variables, {}, llm_call=invalid_review, settings=settings)
    assert list(tmp_path.glob("objects/definition_reconciliation_responses/*.json"))
    assert not list(tmp_path.glob("indexes/definition_reconciliation/*.json"))
    calls = []

    def fixed_review(prompt, **_kwargs):
        calls.append(input_payload(prompt))
        return {"issues": [], "symbol_renames": [{"definition_id": "D2", "symbol": "y", "affected_ids": []}]}

    restored = resolver.resolve({}, {}, variables, {}, llm_call=fixed_review, settings=settings)
    assert len(calls) == 1
    assert [record["symbol"] for record in restored["definitions"]] == ["x", "y"]
