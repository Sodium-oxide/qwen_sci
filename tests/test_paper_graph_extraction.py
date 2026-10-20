"""Offline queue execution through the real extractor, importer and vector store."""
from __future__ import annotations

import json
from pathlib import Path
import re
from threading import Barrier, Event, Lock
from types import SimpleNamespace

import numpy as np
import pytest
from filelock import FileLock
from omegaconf import OmegaConf

from src.paper_graph import extraction
from src.paper_graph.extraction import PaperGraphExtractionExecutor
from src.paper_graph.ingest import ingest_paper
from src.paper_graph.provenance import validate_graph
from src.paper_graph.repository import PaperGraphRepository, core_snapshot, readonly_connection
from src.paper_graph.settings import PaperGraphSettings
from src.paper_graph.validation import build_and_check, check_retrieval


FULLTEXT = ("# Example paper\n\n## Method\nA conserves B under constant input.\n"
            "This relation assumes stationary noise.\nIt holds only at equilibrium.\n"
            "## Results\nA component measures the conserved quantity.\n")


def raw_response():
    return {
        "metadata": {"title": "Example paper", "domain": "physics"},
        "core_contributions": [{
            "id": "relation", "name": "Conservation relation", "summary": "A conservation relation",
            "quote": "A conserves B under constant input.", "source_section": "Method",
            "structure": "A conserves B", "assumptions": ["stationary noise"],
            "boundary_conditions": ["equilibrium"],
        }],
        "components": [{
            "id": "measurement", "name": "Measurement", "summary": "Measures a conserved quantity",
            "source_quote": "A component measures the conserved quantity.", "source_section": "Results",
            "related_to_core": "Conservation relation",
        }],
    }


class Encoder:
    def __init__(self):
        self.calls = []

    def encode(self, texts, **kwargs):
        self.calls.extend(texts)
        return np.array([[1, .25, .1] for _ in texts], dtype=np.float32)


@pytest.fixture
def queue_env(tmp_path):
    source = tmp_path / "paper.md"
    source.write_text(FULLTEXT, encoding="utf-8")
    model = tmp_path / "model"
    model.mkdir()
    (model / "config.json").write_text("{}")
    (model / "modules.json").write_text("[]")
    (model / "pytorch_model.bin").write_bytes(b"offline-test-model")
    settings = PaperGraphSettings(tmp_path / "graph.db", tmp_path / "index", model)
    config = OmegaConf.create({"survey": {"APIInfo": {"llm_model_name": "offline-model"}},
                               "paper_graph": {k: str(v) if isinstance(v, Path) else v
                                               for k, v in vars(settings).items()}})
    payload = {"paper_id": "https://openalex.org/W123", "metadata": {"title": "Example paper"},
               "source_documents": [{"source_id": "local-paper", "path": str(source)}]}
    ingest_paper(settings.db_path, payload)
    return SimpleNamespace(settings=settings, config=config, source=source, payload=payload,
                           repository=PaperGraphRepository(settings.db_path), encoder=Encoder())


def offline_agent(batches, *, context=100_000, logger=None, noise=False):
    # Keep the real retry/metadata/extractor path, replacing only model transport.
    from src.agents.survey_agent.utils.api_call import ChatAgent
    agent = object.__new__(ChatAgent)
    agent.batch_workers = 2
    agent.model_name = "offline-model"
    agent.exponential_backoff = False
    agent.config = SimpleNamespace(BasicInfo=SimpleNamespace(debug=False),
        APIInfo=SimpleNamespace(batch_chat_timeout=1, llm_max_context_length=context))
    agent.logger = logger or SimpleNamespace(info=lambda *a: None, warning=lambda *a: None, error=lambda *a: None)
    agent.estimate_tokens = lambda prompt: len(prompt) // 4
    agent.submissions = []
    responses = iter(batches)

    def transport(prompts, **kwargs):
        agent.submissions.append((prompts.copy(), kwargs))
        if noise:
            print("offline model transport")
            agent.logger.info("offline extractor logger")
        batch = next(responses)
        if callable(batch):
            batch = batch()
        return [json.dumps(r) if isinstance(r, dict) else r for r in batch]

    agent.batch_remote_chat = transport
    return agent


def executor(env, agent=None, factory=None):
    return PaperGraphExtractionExecutor(env.settings.db_path, config=env.config,
                                        chat_agent_factory=factory or (lambda: agent))


def forbidden_agent():
    raise AssertionError("this operation must not initialize a model client")


def attempts(env):
    conn = readonly_connection(env.settings.db_path)
    try:
        return [dict(row) for row in conn.execute("SELECT * FROM extraction_attempts ORDER BY attempt_id")]
    finally:
        conn.close()


def test_queue_extracts_fulltext_verifies_and_commits_success_atomically(queue_env):
    env = queue_env
    agent = offline_agent([[raw_response()]])
    result = executor(env, agent).run()
    assert result["ok"] and result["succeeded"] == 1 and result["remaining"] == 0
    assert result["papers"][0]["result"]["components"] == 1
    assert len(agent.submissions) == 1  # No unnecessary baseline/dataset pass.
    prompts, options = agent.submissions[0]
    assert FULLTEXT in prompts[0]
    assert options["strict_input_budget"] is True
    nodes, graph = core_snapshot(env.settings.db_path)
    assert validate_graph(env.settings.db_path, nodes)
    assert nodes[0]["paper_id"] == "W123" and nodes[0]["paper_domain"] == "physics_astronomy"
    evidence = nodes[0]["evidence_records"][0]
    loc = evidence["locator"]
    assert FULLTEXT[loc["start"]:loc["end"]] == evidence["quote"]
    row, = attempts(env)
    assert row["status"] == "succeeded" and row["stage"] == "complete" and row["output_json"]
    assert executor(env, factory=forbidden_agent).run()["processed"] == 0
    assert core_snapshot(env.settings.db_path)[1] == graph


@pytest.mark.parametrize("change,reason,status", [
    (lambda response: response["core_contributions"][0].update(quote="Invented causal relation."), "unverified_evidence", "failed"),
    (lambda response: response["core_contributions"][0].update(page=9), "unverified_evidence", "failed"),
    (lambda response: response["core_contributions"][0].update(page="None", source_section=""), "unverified_evidence", "failed"),
    (lambda response: response["core_contributions"][0].update(source_id="unknown-source"), "unverified_evidence", "failed"),
    (lambda response: response["core_contributions"][0].update(source_sha256="incorrect-checksum"), "unverified_evidence", "failed"),
    (lambda response: response["core_contributions"][0].update(locator={"path": "/invented/paper.md"}), "unverified_evidence", "failed"),
    (lambda response: response["components"][0].update(related_to_core="Nonexistent core"), "unlinked_components", "partial"),
    (lambda response: response["components"][0].update(source_quote="Fabricated measurement."), "unverified_evidence", "partial"),
    (lambda response: response["metadata"].update(domain="Others"), "unresolved_discipline", "failed"),
    (lambda response: response.update(components=[None]), "invalid_component", "partial"),
    (lambda response: response["core_contributions"][0].update(evidence_records=[{"quote": "Fabricated extra quote."}]), "unverified_evidence", "failed"),
    (lambda response: response["components"][0].update(quote="Fabricated alias alongside a valid source_quote."), "unverified_evidence", "partial"),
    (lambda response: response["core_contributions"][0].update(evidence=42), "invalid_evidence", "failed"),
])
def test_invalid_output_keeps_reasons_and_imports_only_eligible_entities(queue_env, change, reason, status):
    env = queue_env
    response = raw_response()
    change(response)
    before = core_snapshot(env.settings.db_path)
    result = executor(env, offline_agent([[response]])).run(max_evidence_repairs=0)
    assert not result["ok"] and result[status] == 1
    paper = result["papers"][0]
    assert paper["status"] == status
    assert reason in paper["error"]["message"]
    if status == "failed":
        assert paper["stage"] == "evidence_verification" and core_snapshot(env.settings.db_path) == before
    else:
        nodes, _ = core_snapshot(env.settings.db_path)
        assert len(nodes) == 1 and not nodes[0]["components"]
        assert validate_graph(env.settings.db_path, nodes)
    pending, = env.repository.pending()
    assert pending["execution"]["status"] == status and pending["execution"]["has_output"]
    assert reason in pending["execution"]["error"]["message"]


def test_nested_json_entity_cannot_hide_fabricated_additional_quote(queue_env):
    from src.agents.survey_agent.utils.step2v2_extractor import aggregate_results
    env = queue_env
    response = raw_response()
    core = response["core_contributions"][0]
    component = response.pop("components")[0]
    component["evidence_records"] = [{"quote": "A fabricated second quote."}]
    core["components"] = [json.dumps(component)]
    output, = aggregate_results([{"node_id": "W123", "result": response}], [], {}, preserve_components=True)
    plan = executor(env, factory=forbidden_agent).run(dry_run=True)
    attempt = env.repository.start_attempt("W123", plan["papers"][0]["input_hash"])
    env.repository.checkpoint_attempt(attempt, stage="evidence_verification", output=output)
    result = executor(env, factory=forbidden_agent).run(max_evidence_repairs=0)
    assert result["partial"] == 1 and "unverified_evidence" in result["papers"][0]["error"]["message"]
    assert not core_snapshot(env.settings.db_path)[0][0]["components"]


def test_bad_paper_does_not_block_later_papers_and_limit_counts_runnable_work(queue_env):
    env = queue_env
    ingest_paper(env.settings.db_path, {**env.payload, "paper_id": "W124"})
    bad = raw_response()
    bad["metadata"]["domain"] = "Others"
    first = executor(env, offline_agent([[bad]])).run(limit=1)
    assert first["failed"] == 1 and first["remaining"] == 2
    second = executor(env, offline_agent([[raw_response()]])).run(limit=1)
    assert second["skipped_failed"] == 1 and second["succeeded"] == 1
    assert second["papers"][-1]["paper_id"] == "W124" and second["remaining"] == 1


def test_dry_run_is_read_only_and_selected_ids_are_normalized(queue_env):
    env = queue_env
    before = env.settings.db_path.read_bytes()
    result = executor(env, factory=forbidden_agent).run(
        paper_ids=["https://openalex.org/W123", "W999"], dry_run=True)
    assert result["ok"] and result["papers"][0]["status"] == "planned"
    assert result["papers"][0]["fulltext_chars"] == len(FULLTEXT)
    assert result["not_pending"] == ["W999"]
    assert not attempts(env) and env.settings.db_path.read_bytes() == before


def test_queue_factory_uses_explicit_provider_registry_without_global_reload(queue_env, monkeypatch):
    from src.agents.survey_agent.utils import api_call
    config = OmegaConf.create({
        "llm": {"default_provider": "offline", "providers": {"offline": {
            "api_key_env": "OFFLINE_TEST_KEY", "api_key": "offline-test-key",
            "base_url": "https://offline.invalid/v1", "api_style": "chat_completions",
            "tokenizer_fallback": "utf8_bytes", "token_limit_parameter": "max_tokens",
            "default_models": {"survey": "offline-model"},
        }}, "models": {"offline-model": {"provider": "offline", "api_style": "chat_completions",
                                             "capabilities": {"chat_completions": True}}}},
        "survey": {"APIInfo": {"llm_provider": "offline", "llm_api_key": "", "llm_api_base_url": "",
                                "llm_model_name": "offline-model", "batch_chat_agent_worker": 1,
                                "use_stream_mode": False}},
    })
    monkeypatch.setattr(api_call, "load_config", forbidden_agent)
    instance = PaperGraphExtractionExecutor(queue_env.settings.db_path, config=config)
    agent = instance._make_chat_agent()
    assert agent.provider_name == "offline" and agent.model_name == "offline-model"
    assert agent.remote_url == "https://offline.invalid/v1/chat/completions"
    assert agent._project_config is config
    agent.config.APIInfo.batch_chat_agent_worker = 2
    assert config.survey.APIInfo.batch_chat_agent_worker == 1


def test_partial_evidence_resumes_and_history_is_preserved(queue_env):
    env = queue_env
    bad = raw_response()
    bad["components"][0]["source_quote"] = "Unverifiable quotation."
    assert executor(env, offline_agent([[bad]])).run(max_evidence_repairs=0)["partial"] == 1
    assert executor(env, factory=forbidden_agent).run(dry_run=True)["papers"][0]["action"] == "repair_evidence"
    patch = evidence_patch("/ideation_resource/components/0/source_quote")
    agent = offline_agent([[patch]])
    retried = executor(env, agent).run(retry_failed=True)
    assert retried["ok"] and retried["papers"][0]["reused_output"]
    assert len(agent.submissions) == 1 and "repair_failed_evidence_only" in agent.submissions[0][0][0]
    assert [attempt["status"] for attempt in attempts(env)] == ["partial", "succeeded"]


def evidence_patch(target, *, records=None):
    return {"repairs": [{"target_id": target, "evidence_records": records or [{
        "quote": "A component measures the conserved quantity.", "source_id": "local-paper", "source_section": "Results",
    }]}], "unresolved": []}


def repair_events(env):
    conn = readonly_connection(env.settings.db_path)
    try:
        return [dict(row) for row in conn.execute("SELECT * FROM extraction_evidence_repairs ORDER BY repair_id")]
    finally:
        conn.close()


def request_events(env):
    conn = readonly_connection(env.settings.db_path)
    try:
        return [dict(row) for row in conn.execute("SELECT * FROM extraction_requests ORDER BY request_id")]
    finally:
        conn.close()


def component_patch(target="/ideation_resource/core_contributions/0"):
    return {"target_id": target, "components": [{"id": "measurement", "name": "Measurement",
        "summary": "Measures the conserved quantity", "evidence_records": [{
            "quote": "A component measures the conserved quantity.",
            "source_id": "local-paper", "source_section": "Results"}]}], "unresolved": None}


def save_missing_components(env, response=None):
    response = response or raw_response()
    response["components"] = []
    result = executor(env, offline_agent([[response]])).run(max_component_repairs=0)
    assert result["partial"] == 1 and "missing_grounded_components" in result["papers"][0]["error"]["message"]
    return json.loads(attempts(env)[-1]["output_json"])


def test_missing_components_resume_from_saved_core_and_dry_run_is_read_only(queue_env):
    env = queue_env
    original = save_missing_components(env)
    assert executor(env, factory=forbidden_agent).run(dry_run=True)["papers"][0]["action"] == "repair_components"
    before = env.settings.db_path.read_bytes()
    plan = executor(env, factory=forbidden_agent).run(retry_failed=True, dry_run=True)
    assert plan["papers"][0]["action"] == "repair_components" and env.settings.db_path.read_bytes() == before
    agent = offline_agent([[component_patch()]])
    result = executor(env, agent).run(retry_failed=True)
    assert result["ok"] and result["papers"][0]["reused_output"]
    assert result["papers"][0]["component_repairs"] == 1 and len(agent.submissions) == 1
    assert "repair_missing_components_only" in agent.submissions[0][0][0]
    saved = json.loads(attempts(env)[-1]["output_json"])
    core = saved["ideation_resource"]["core_contributions"][0]
    assert {key: value for key, value in core.items() if key != "components"} == original["ideation_resource"]["core_contributions"][0]
    assert saved["metadata"] == original["metadata"]
    assert validate_graph(env.settings.db_path, core_snapshot(env.settings.db_path)[0])
    event = request_events(env)[-1]
    assert event["stage"] == "component_repair" and event["status"] == "applied"


def test_new_extraction_repairs_missing_components_before_import(queue_env):
    env = queue_env
    response = raw_response()
    response["components"] = []
    agent = offline_agent([[response], [component_patch()]])
    result = executor(env, agent).run()
    assert result["ok"] and result["papers"][0]["component_repairs"] == 1
    assert result["papers"][0]["result"]["components"] == 1 and len(agent.submissions) == 2
    assert result["papers"][0]["evidence_repairs"] == 0


@pytest.mark.parametrize("change,reason", [
    (lambda patch: patch.update(metadata={}), "unexpected_component_repair_fields"),
    (lambda patch: patch.update(target_id="/ideation_resource/core_contributions/9"), "unknown_component_repair_target"),
    (lambda patch: patch["components"][0].update(name="Conservation relation"), "duplicate_component_or_core_identity"),
    (lambda patch: patch["components"][0].update(summary=""), "component_name_and_summary_required"),
    (lambda patch: patch["components"][0].update(related_to_core="Other core"), "unexpected_component_fields"),
    (lambda patch: patch["components"][0]["evidence_records"][0].update(quote="Invented evidence."), "unverified_component_evidence"),
    (lambda patch: patch["components"][0]["evidence_records"][0].update(source_sha256="changed"), "source_checksum_mismatch"),
    (lambda patch: patch["components"][0]["evidence_records"][0].update(source_id="unknown"), "unknown_source_id"),
    (lambda patch: patch["components"].append(patch["components"][0].copy()), "duplicate_component_or_core_identity"),
])
def test_component_repair_rejects_changes_or_unverified_additions(queue_env, change, reason):
    env = queue_env
    original = save_missing_components(env)
    patch = component_patch()
    change(patch)
    result = executor(env, offline_agent([[patch]])).run(retry_failed=True, max_component_repairs=1)
    assert result["partial"] == 1 and not core_snapshot(env.settings.db_path)[0][0]["components"]
    assert reason in " ".join(result["papers"][0]["error"]["component_repair_errors"])
    assert json.loads(attempts(env)[-1]["output_json"]) == original
    assert json.loads(request_events(env)[-1]["response_json"]) == json.dumps(patch)


def test_component_repair_retains_completed_core_when_another_core_is_unresolved(queue_env):
    env = queue_env
    response = raw_response()
    response["core_contributions"].append({**response["core_contributions"][0], "id": "second", "name": "Second relation"})
    save_missing_components(env, response)
    target = "/ideation_resource/core_contributions/1"
    unresolved = {"target_id": target, "components": [], "unresolved": "Need another retained source passage."}
    first = executor(env, offline_agent([[component_patch()], [unresolved]])).run(retry_failed=True, max_component_repairs=1)
    assert first["partial"] == 1 and sum(len(core["components"]) for core in core_snapshot(env.settings.db_path)[0]) == 1
    partial = json.loads(attempts(env)[-1]["output_json"])
    preserved = partial["ideation_resource"]["core_contributions"][0]
    assert preserved["components"] and "another retained" in first["papers"][0]["error"]["component_repair_errors"][0]
    agent = offline_agent([[component_patch(target)]])
    completed = executor(env, agent).run(retry_failed=True)
    assert completed["ok"] and len(agent.submissions) == 1
    assert '"target_id": "/ideation_resource/core_contributions/1"' in agent.submissions[0][0][0]
    assert json.loads(attempts(env)[-1]["output_json"])["ideation_resource"]["core_contributions"][0] == preserved


def test_malformed_component_reply_is_saved_and_repaired_with_error_feedback(queue_env):
    env = queue_env
    save_missing_components(env)
    agent = offline_agent([["{broken"], [component_patch()]])
    result = executor(env, agent).run(retry_failed=True)
    assert result["ok"] and result["papers"][0]["component_repairs"] == 2
    events = [event for event in request_events(env) if event["stage"] == "component_repair"]
    assert json.loads(events[0]["response_json"]) == "{broken"
    assert json.loads(events[1]["request_json"])["previous_repair_errors"]


def test_main_json_repairs_only_missing_metadata_and_preserves_contributions(queue_env):
    env = queue_env
    response = raw_response()
    metadata = response.pop("metadata")
    agent = offline_agent([[response], [{"metadata": metadata}]])
    result = executor(env, agent).run()
    assert result["ok"] and len(agent.submissions) == 2
    prompt = agent.submissions[1][0][0]
    assert '"task": "repair_main_extraction_json"' in prompt
    assert '"fields_to_repair": ["metadata"]' in prompt and FULLTEXT in prompt
    saved = json.loads(attempts(env)[-1]["output_json"])
    assert saved["ideation_resource"]["core_contributions"] == response["core_contributions"]
    assert saved["ideation_resource"]["components"] == response["components"]
    first, second = request_events(env)
    assert first["status"] == "failed" and second["stage"] == "extraction_json_repair"
    assert json.loads(first["response_json"]) == json.dumps(response)


def test_main_json_repair_rejects_changes_to_valid_fields(queue_env):
    env = queue_env
    response = raw_response()
    metadata = response.pop("metadata")
    changed = {**response, "metadata": metadata, "components": []}
    agent = offline_agent([[response], [changed], [{"metadata": metadata}]])
    result = executor(env, agent).run()
    assert result["ok"] and len(agent.submissions) == 3
    assert "protected_main_fields_changed" in json.loads(request_events(env)[1]["outcome_json"])["error"]
    assert json.loads(attempts(env)[-1]["output_json"])["ideation_resource"]["components"] == response["components"]


def test_truncated_outer_json_retains_complete_fields_in_targeted_repair(queue_env):
    env = queue_env
    response = raw_response()
    prefix = json.dumps({key: value for key, value in response.items() if key != "components"})[:-1]
    truncated = prefix + ', "components": ['
    agent = offline_agent([[truncated], [{"components": response["components"]}]])
    result = executor(env, agent).run()
    assert result["ok"]
    failure = json.loads(request_events(env)[0]["outcome_json"])
    assert "Invalid outer JSON" in failure["error"] and "Missing required key: metadata" not in failure["error"]
    assert failure["repair_state"]["candidate"]["metadata"] == response["metadata"]
    saved = json.loads(attempts(env)[-1]["output_json"])
    assert saved["ideation_resource"]["core_contributions"] == response["core_contributions"]


def test_failed_main_json_resumes_saved_fields_and_raw_response(queue_env):
    env = queue_env
    response = raw_response()
    metadata = response.pop("metadata")
    failed = executor(env, offline_agent([[response], [{}], [{}]])).run()
    assert failed["failed"] == 1 and not attempts(env)[0]["output_json"]
    assert executor(env, factory=forbidden_agent).run()["skipped_failed"] == 1
    plan = executor(env, factory=forbidden_agent).run(retry_failed=True, dry_run=True)
    assert plan["papers"][0]["action"] == "repair_main_json"
    agent = offline_agent([[{"metadata": metadata}]])
    completed = executor(env, agent).run(retry_failed=True)
    assert completed["ok"] and len(agent.submissions) == 1
    assert "repair_main_extraction_json" in agent.submissions[0][0][0]
    assert json.loads(attempts(env)[-1]["output_json"])["ideation_resource"]["core_contributions"] == response["core_contributions"]


def test_interruption_before_new_request_keeps_earlier_main_repair_state(queue_env):
    env = queue_env
    response = raw_response()
    metadata = response.pop("metadata")
    failed = executor(env, offline_agent([[response], [{}], [{}]])).run()
    env.repository.start_attempt("W123", failed["papers"][0]["input_hash"])
    agent = offline_agent([[{"metadata": metadata}]])
    result = executor(env, agent).run()
    assert result["ok"] and len(agent.submissions) == 1
    assert "repair_main_extraction_json" in agent.submissions[0][0][0]
    assert json.loads(attempts(env)[-1]["output_json"])["ideation_resource"]["components"] == response["components"]


def test_main_repair_budget_failure_keeps_original_source_and_saved_response(queue_env):
    from src.agents.survey_agent.utils.step2v2_extractor import build_main_extraction_prompt, extract_regex_candidates
    env = queue_env
    system, user = build_main_extraction_prompt(FULLTEXT, "Example paper", extract_regex_candidates(FULLTEXT))
    context = len(system + "\n\n" + user) // 4 + 16001
    response = raw_response()
    response.pop("metadata")
    agent = offline_agent([[response]], context=context)
    result = executor(env, agent).run()
    assert result["failed"] == 1 and len(agent.submissions) == 1
    assert "main_json_repair_input_budget_exceeded" in result["papers"][0]["error"]["message"]
    assert FULLTEXT in agent.submissions[0][0][0]
    assert json.loads(request_events(env)[0]["response_json"]) == json.dumps(response)


def test_component_repair_source_change_cannot_commit_a_stale_result(queue_env):
    env = queue_env
    save_missing_components(env)
    before = core_snapshot(env.settings.db_path)
    def changed_source():
        env.source.write_text(FULLTEXT + "Changed while component repair was in flight.\n")
        return [component_patch()]
    result = executor(env, offline_agent([changed_source])).run(retry_failed=True)
    assert result["failed"] == 1 and "checksum mismatch" in result["papers"][0]["error"]["message"]
    assert core_snapshot(env.settings.db_path) == before


@pytest.mark.parametrize("after_validation", [False, True])
def test_main_response_saved_before_interruption_resumes_without_another_request(queue_env, monkeypatch, after_validation):
    env = queue_env
    operation = "finish_extraction_request" if after_validation else "save_extraction_response"
    original = getattr(PaperGraphRepository, operation)
    def interrupted(repository, *args, **kwargs):
        original(repository, *args, **kwargs)
        raise KeyboardInterrupt("stop after durable main response")
    monkeypatch.setattr(PaperGraphRepository, operation, interrupted)
    with pytest.raises(KeyboardInterrupt):
        executor(env, offline_agent([[raw_response()]])).run()
    monkeypatch.setattr(PaperGraphRepository, operation, original)
    agent = offline_agent([])
    completed = executor(env, agent).run()
    assert completed["ok"] and not agent.submissions
    assert [attempt["status"] for attempt in attempts(env)] == ["interrupted", "succeeded"]


def saved_failure(env, response=None):
    response = response or raw_response()
    if response == raw_response():
        response["components"][0]["source_quote"] = "Unverifiable quotation."
    result = executor(env, offline_agent([[response]])).run(max_evidence_repairs=0)
    assert result["partial"] == 1
    return result


def test_caption_interrupted_sentence_repairs_to_independent_literal_fragments(queue_env):
    env = queue_env
    body = FULLTEXT.replace("A component measures the conserved quantity.",
        "A component measures\n\n![](figure.png)\n\nFigure 1: " + "A caption interrupts reading order. " * 130
        + "\n\nthe conserved quantity.")
    env.source.write_text(body, encoding="utf-8")
    ingest_paper(env.settings.db_path, env.payload)
    records = [{"quote": quote, "source_id": "local-paper", "source_section": "Results"}
               for quote in ["A component measures", "the conserved quantity."]]
    patch = evidence_patch("/ideation_resource/components/0/source_quote", records=records)
    agent = offline_agent([[raw_response()], [patch]])
    result = executor(env, agent).run()
    assert result["ok"] and result["papers"][0]["evidence_repairs"] == 1
    assert len(agent.submissions) == 2
    prompt, = agent.submissions[1][0]
    from src.paper_graph.evidence_repair import REPAIR_INSTRUCTIONS
    request = json.loads(prompt.removeprefix(REPAIR_INSTRUCTIONS + "\n\n"))
    failure, = request["failures"]
    assert failure["failed_evidence"]["quote"] == "A component measures the conserved quantity."
    assert failure["reasons"] == ["quote_not_contiguous_in_retained_fulltext"]
    context = "\n".join(part["text"] for part in request["source_excerpts"])
    assert "A component measures" in context and "the conserved quantity." in context and "![](figure.png)" in context
    for excerpt in request["source_excerpts"]:
        assert body[excerpt["start"]:excerpt["end"]] == excerpt["text"]
    nodes, _ = core_snapshot(env.settings.db_path)
    assert validate_graph(env.settings.db_path, nodes)
    component, = nodes[0]["components"]
    assert {e["quote"] for e in component["evidence_records"]} == {r["quote"] for r in records}
    for record in component["evidence_records"]:
        loc = record["locator"]
        assert body[loc["start"]:loc["end"]] == record["quote"]
        assert record["source_id"] == "local-paper" and record["source_sha256"]
    assert env.source.read_text() == body
    event, = repair_events(env)
    assert event["status"] == "applied" and json.loads(event["response_json"]) == json.dumps(patch)
    outcome = json.loads(event["outcome_json"])
    assert not outcome["remaining_issues"] and not outcome["errors"]
    validated = build_and_check(env.settings, queries=["conserved quantity"], model=env.encoder)
    assert validated["ok"] and validated["retrieval"]["results"][0]["hits"]


def test_partial_slot_repairs_keep_verified_work_and_resume_only_remaining_targets(queue_env):
    env = queue_env
    bad = raw_response()
    valid = {"quote": "A component measures the conserved quantity.", "source_section": "Results"}
    bad["components"][0]["evidence_records"] = [{"quote": "Broken first quote."}, {"quote": "Broken second quote."}, valid]
    saved_failure(env, bad)
    before = json.loads(attempts(env)[0]["output_json"])
    first_target = "/ideation_resource/components/0/evidence_records/0"
    fragments = [{"quote": q, "source_section": "Results"} for q in ["A component measures", "the conserved quantity."]]
    first_patch = evidence_patch(first_target, records=fragments)
    first_patch["unresolved"] = [{"target_id": "/ideation_resource/components/0/evidence_records/1", "reason": "Need a different passage."}]
    result = executor(env, offline_agent([[first_patch]])).run(retry_failed=True, max_evidence_repairs=1)
    assert result["partial"] == 1 and not core_snapshot(env.settings.db_path)[0][0]["components"]
    partial = json.loads(attempts(env)[-1]["output_json"])
    old_component = before["ideation_resource"]["components"][0]
    component = partial["ideation_resource"]["components"][0]
    assert component["evidence_records"][3] == valid
    assert component["source_quote"] == old_component["source_quote"]
    assert partial["ideation_resource"]["core_contributions"] == before["ideation_resource"]["core_contributions"]
    assert {k: v for k, v in component.items() if k != "evidence_records"} == {k: v for k, v in old_component.items() if k != "evidence_records"}
    issue, = result["papers"][0]["error"]["evidence_issues"]
    assert issue["target_id"] == "/ideation_resource/components/0/evidence_records/2"
    agent = offline_agent([[evidence_patch(issue["target_id"])]])
    completed = executor(env, agent).run(retry_failed=True)
    assert completed["ok"] and completed["papers"][0]["reused_output"]
    assert first_target not in agent.submissions[0][0][0]
    final = json.loads(attempts(env)[-1]["output_json"])["ideation_resource"]["components"][0]
    assert final["evidence_records"][:2] == component["evidence_records"][:2]
    assert final["evidence_records"][3] == valid
    assert [e["status"] for e in repair_events(env)] == ["partial", "applied"]
    assert [attempt["status"] for attempt in attempts(env)] == ["partial", "partial", "succeeded"]


def test_interrupted_repair_reuses_successful_entity_checkpoint(queue_env):
    from copy import deepcopy
    env = queue_env
    bad = raw_response()
    second = deepcopy(bad["components"][0])
    second.update(id="measurement2", name="Second measurement", source_quote="Second invalid quote.")
    bad["components"][0]["source_quote"] = "First invalid quote."
    bad["components"].append(second)
    def interrupt():
        raise KeyboardInterrupt("stop during second repair request")
    first = offline_agent([[bad], [evidence_patch("/ideation_resource/components/0/source_quote")], interrupt])
    with pytest.raises(KeyboardInterrupt):
        executor(env, first).run()
    interrupted, = attempts(env)
    assert interrupted["status"] == "running" and interrupted["stage"] == "evidence_repair"
    partial = json.loads(interrupted["output_json"])
    assert "source_quote" not in partial["ideation_resource"]["components"][0]
    assert partial["ideation_resource"]["components"][1]["source_quote"] == "Second invalid quote."
    agent = offline_agent([[evidence_patch("/ideation_resource/components/1/source_quote")]])
    result = executor(env, agent).run()
    assert result["ok"] and result["papers"][0]["reused_output"]
    assert len(agent.submissions) == 1 and '"First invalid quote."' not in agent.submissions[0][0][0]
    assert [a["status"] for a in attempts(env)] == ["interrupted", "succeeded"]


@pytest.mark.parametrize("change,reason", [
    (lambda p: p["repairs"][0].update(summary="Changed scientific claim"), "unexpected_patch_fields"),
    (lambda p: p.update(components=[]), "repair_response_must_contain_only"),
    (lambda p: p["repairs"][0].update(target_id="/ideation_resource/components/9/quote"), "unknown_repair_target"),
    (lambda p: p["repairs"][0].update(evidence_records=[]), "replacement_evidence_must_be_nonempty"),
    (lambda p: p["repairs"][0]["evidence_records"][0].update(quote="Invented quote."), "quote_not_contiguous"),
    (lambda p: p["repairs"][0]["evidence_records"][0].update(source_id="wrong-source"), "unknown_source_id"),
    (lambda p: p["repairs"][0]["evidence_records"][0].update(source_sha256="wrong-sha"), "source_checksum_mismatch"),
    (lambda p: p["repairs"][0]["evidence_records"][0].update(page=9), "page_not_retained"),
    (lambda p: p["repairs"][0]["evidence_records"][0].update(page="None", source_section=""), "page_not_retained"),
    (lambda p: p["repairs"][0]["evidence_records"][0].update(locator={"path": "/not/the/source.md"}), "locator_path_mismatch"),
    (lambda p: p["repairs"].append(p["repairs"][0].copy()), "duplicate_repair_target"),
])
def test_unsafe_or_unverifiable_repairs_preserve_output_and_failure(queue_env, change, reason):
    env = queue_env
    saved_failure(env)
    original = json.loads(attempts(env)[0]["output_json"])
    patch = evidence_patch("/ideation_resource/components/0/source_quote")
    change(patch)
    result = executor(env, offline_agent([[patch]])).run(retry_failed=True, max_evidence_repairs=1)
    assert result["partial"] == 1 and result["remaining"] == 1
    assert reason in " ".join(result["papers"][0]["error"]["repair_errors"])
    assert json.loads(attempts(env)[-1]["output_json"]) == original
    assert not core_snapshot(env.settings.db_path)[0][0]["components"]
    event, = repair_events(env)
    assert event["status"] == "failed" and json.loads(event["response_json"]) == json.dumps(patch)


def test_malformed_reply_is_saved_and_next_round_gets_error_feedback(queue_env):
    env = queue_env
    saved_failure(env)
    patch = evidence_patch("/ideation_resource/components/0/source_quote")
    agent = offline_agent([["{broken JSON"], [patch]])
    result = executor(env, agent).run(retry_failed=True)
    assert result["ok"] and result["papers"][0]["evidence_repairs"] == 2
    first, second = repair_events(env)
    assert json.loads(first["response_json"]) == "{broken JSON"
    assert json.loads(second["request_json"])["previous_repair_errors"] == ["ValueError: No JSON found"]


def test_unresolved_evidence_retains_specific_reason_and_original_extraction(queue_env):
    env = queue_env
    saved_failure(env)
    unresolved = {"repairs": [], "unresolved": [{"target_id": "/ideation_resource/components/0/source_quote",
                                               "reason": "The supplied section does not support this claim."}]}
    result = executor(env, offline_agent([[unresolved]])).run(retry_failed=True, max_evidence_repairs=1)
    assert result["partial"] == 1
    assert "does not support" in result["papers"][0]["error"]["repair_errors"][0]
    assert len(result["papers"][0]["error"]["evidence_issues"]) == 1
    assert attempts(env)[0]["output_json"] == attempts(env)[1]["output_json"]


def test_repaired_evidence_does_not_bypass_full_structure_validation(queue_env):
    env = queue_env
    bad = raw_response()
    bad["components"][0].update(source_quote="Invalid quote.", related_to_core="Unknown parent")
    agent = offline_agent([[bad], [evidence_patch("/ideation_resource/components/0/source_quote")]])
    result = executor(env, agent).run()
    assert result["partial"] == 1 and result["papers"][0]["status"] == "partial"
    error = result["papers"][0]["error"]
    assert "unlinked_components" in error["reasons"] and not error["evidence_issues"]
    assert not core_snapshot(env.settings.db_path)[0][0]["components"]


def test_saved_evidence_dry_run_is_read_only_and_preserves_old_fingerprint(queue_env):
    env = queue_env
    old = saved_failure(env)
    before = env.settings.db_path.read_bytes()
    plan = executor(env, factory=forbidden_agent).run(retry_failed=True, dry_run=True, max_evidence_repairs=3)
    paper, = plan["papers"]
    assert paper["action"] == "repair_evidence" and paper["reused_output"]
    assert paper["input_hash"] == old["papers"][0]["input_hash"]
    assert paper["evidence_issues"][0]["field"] == "source_quote"
    assert env.settings.db_path.read_bytes() == before and not repair_events(env)


def test_repair_budget_failure_makes_no_transport_call(queue_env):
    env = queue_env
    saved_failure(env)
    agent = offline_agent([], context=16_050)
    result = executor(env, agent).run(retry_failed=True, max_evidence_repairs=1)
    assert result["partial"] == 1 and not agent.submissions
    assert "repair_input_budget_exceeded" in result["papers"][0]["error"]["repair_errors"][0]
    assert not core_snapshot(env.settings.db_path)[0][0]["components"]


def test_nonretryable_provider_error_stops_repair_requests_and_keeps_saved_output(queue_env):
    from src.agents.survey_agent.utils.api_call import NonRetryableRequestError
    env = queue_env
    saved_failure(env)
    def fail():
        raise NonRetryableRequestError("offline provider rejected request parameters")
    agent = offline_agent([fail])
    result = executor(env, agent).run(retry_failed=True)
    assert result["partial"] == 1 and len(agent.submissions) == 1
    assert "NonRetryableRequestError" in result["papers"][0]["error"]["repair_errors"][0]
    assert attempts(env)[0]["output_json"] == attempts(env)[1]["output_json"]


def test_source_change_during_repair_rejects_graph_import(queue_env):
    env = queue_env
    saved_failure(env)
    before = core_snapshot(env.settings.db_path)
    def changed_source():
        env.source.write_text(FULLTEXT + "Changed while repair was in flight.\n")
        return [evidence_patch("/ideation_resource/components/0/source_quote")]
    result = executor(env, offline_agent([changed_source])).run(retry_failed=True)
    assert result["failed"] == 1 and "checksum mismatch" in result["papers"][0]["error"]["message"]
    assert core_snapshot(env.settings.db_path) == before


def test_queue_change_during_repair_retains_new_queue_input(queue_env):
    env = queue_env
    saved_failure(env)
    before = core_snapshot(env.settings.db_path)
    def reimport():
        ingest_paper(env.settings.db_path, {**env.payload, "metadata": {"title": "New input during repair"}})
        return [evidence_patch("/ideation_resource/components/0/source_quote")]
    result = executor(env, offline_agent([reimport])).run(retry_failed=True)
    assert result["failed"] == 1 and result["papers"][0]["error"]["type"] == "QueueChangedError"
    assert env.repository.pending()[0]["input"]["metadata"]["title"] == "New input during repair"
    assert core_snapshot(env.settings.db_path) == before


def test_nested_json_entity_repair_preserves_other_fields(queue_env):
    from src.agents.survey_agent.utils.step2v2_extractor import aggregate_results
    env = queue_env
    response = raw_response()
    component = response.pop("components")[0]
    component["quote"] = "Fabricated extra quote."
    response["core_contributions"][0]["components"] = [json.dumps(component)]
    output, = aggregate_results([{"node_id": "W123", "result": response}], [], {}, preserve_components=True)
    plan = executor(env, factory=forbidden_agent).run(dry_run=True)
    attempt = env.repository.start_attempt("W123", plan["papers"][0]["input_hash"])
    env.repository.checkpoint_attempt(attempt, stage="evidence_verification", output=output)
    target = "/ideation_resource/core_contributions/0/components/0/quote"
    result = executor(env, offline_agent([[evidence_patch(target)]])).run()
    assert result["ok"] and result["papers"][0]["reused_output"]
    repaired = json.loads(attempts(env)[-1]["output_json"])
    nested = json.loads(repaired["ideation_resource"]["core_contributions"][0]["components"][0])
    assert {k: v for k, v in nested.items() if k != "evidence_records"} == {k: v for k, v in component.items() if k != "quote"}


def test_valid_legacy_evidence_is_kept_when_a_repaired_quote_adds_new_records(queue_env):
    env = queue_env
    extra = "A repeated measurement confirms the conserved quantity."
    body = FULLTEXT + extra + "\n"
    env.source.write_text(body)
    ingest_paper(env.settings.db_path, env.payload)
    response = raw_response()
    response["components"][0].update(source_quote="Broken quote.", evidence=[{"quote": extra, "source_section": "Results"}])
    agent = offline_agent([[response], [evidence_patch("/ideation_resource/components/0/source_quote")]])
    result = executor(env, agent).run()
    assert result["ok"]
    saved = json.loads(attempts(env)[0]["output_json"])["ideation_resource"]["components"][0]
    assert saved["evidence"] == response["components"][0]["evidence"]
    nodes, _ = core_snapshot(env.settings.db_path)
    quotes = {record["quote"] for record in nodes[0]["components"][0]["evidence_records"]}
    assert quotes == {extra, "A component measures the conserved quantity."}


def test_main_extractor_can_return_split_evidence_without_repair_calls(queue_env):
    env = queue_env
    response = raw_response()
    response["components"][0]["source_quote"] = ""
    response["components"][0]["evidence_records"] = [
        {"quote": "A component measures", "source_section": "Results"},
        {"quote": "the conserved quantity.", "source_section": "Results"},
    ]
    agent = offline_agent([[response]])
    result = executor(env, agent).run()
    assert result["ok"] and not result["papers"][0]["evidence_repairs"]
    assert len(agent.submissions) == 1 and not repair_events(env)
    assert "never stitch the separated text into one quote" in agent.submissions[0][0][0]
    nodes, _ = core_snapshot(env.settings.db_path)
    assert len(nodes[0]["components"][0]["evidence_records"]) == 2


def test_repaired_fragments_keep_their_individual_page_source_and_location(queue_env):
    env = queue_env
    payload = {**env.payload, "source_documents": [*env.payload["source_documents"],
        {"source_id": "page-one", "text": "A component measures", "page": 1},
        {"source_id": "page-two", "text": "the conserved quantity.", "page": 2}]}
    ingest_paper(env.settings.db_path, payload)
    response = raw_response()
    response["components"][0].update(source_id="page-one", page=1)
    patch = evidence_patch("/ideation_resource/components/0/source_quote", records=[
        {"quote": "A component measures", "source_id": "page-one", "page": 1},
        {"quote": "the conserved quantity.", "source_id": "page-two", "page": 2},
    ])
    result = executor(env, offline_agent([[response], [patch]])).run()
    assert result["ok"]
    nodes, _ = core_snapshot(env.settings.db_path)
    assert validate_graph(env.settings.db_path, nodes)
    records = nodes[0]["components"][0]["evidence_records"]
    assert {(r["source_id"], r["locator"]["page"]) for r in records} == {("page-one", 1), ("page-two", 2)}
    assert all(r["locator"]["start"] == 0 and not r["locator"]["section"] for r in records)


def test_bad_patch_does_not_undo_an_independent_good_patch_on_the_same_entity(queue_env):
    env = queue_env
    response = raw_response()
    response["components"][0].update(quote="Broken alias one.", source_quote="Broken alias two.")
    saved_failure(env, response)
    patch = evidence_patch("/ideation_resource/components/0/quote")
    bad_patch = evidence_patch("/ideation_resource/components/0/source_quote")["repairs"][0]
    bad_patch["evidence_records"][0]["quote"] = "Still unverifiable."
    patch["repairs"].append(bad_patch)
    result = executor(env, offline_agent([[patch]])).run(retry_failed=True, max_evidence_repairs=1)
    assert result["partial"] == 1
    saved = json.loads(attempts(env)[-1]["output_json"])["ideation_resource"]["components"][0]
    assert "quote" not in saved and saved["source_quote"] == "Broken alias two."
    assert len(saved["evidence_records"]) == 1
    assert result["papers"][0]["error"]["evidence_issues"][0]["field"] == "source_quote"
    assert repair_events(env)[0]["status"] == "partial"


def test_wrong_paper_identity_is_persisted_as_failure_without_masking_the_error(queue_env):
    from src.agents.survey_agent.utils.step2v2_extractor import aggregate_results
    env = queue_env
    output, = aggregate_results([{"node_id": "W999", "result": raw_response()}], [], {}, preserve_components=True)
    plan = executor(env, factory=forbidden_agent).run(dry_run=True)
    attempt = env.repository.start_attempt("W123", plan["papers"][0]["input_hash"])
    env.repository.checkpoint_attempt(attempt, stage="evidence_verification", output=output)
    result = executor(env, factory=forbidden_agent).run()
    assert result["failed"] == 1 and "extracted_paper_id_mismatch" in result["papers"][0]["error"]["message"]
    assert attempts(env)[-1]["status"] == "failed" and not core_snapshot(env.settings.db_path)[0]


def test_source_failure_is_persisted_and_changed_fulltext_invalidates_failed_fingerprint(queue_env):
    env = queue_env
    original = env.source.read_text()
    env.source.write_text(" \n", encoding="utf-8")
    failed = executor(env, factory=forbidden_agent).run()
    assert failed["failed"] == 1 and failed["papers"][0]["stage"] == "source_validation"
    assert "missing_fulltext" in failed["papers"][0]["error"]["reasons"]
    # Restore the same authoritative text; its changed fingerprint is runnable.
    env.source.write_text(original, encoding="utf-8")
    assert executor(env, offline_agent([[raw_response()]])).run()["succeeded"] == 1


def test_changed_file_cannot_be_replaced_by_queued_inline_text(queue_env):
    env = queue_env
    env.source.write_text(FULLTEXT + "Changed after queue import.\n")
    result = executor(env, factory=forbidden_agent).run()
    assert "source_checksum_mismatch" in result["papers"][0]["error"]["message"]
    env.source.unlink()
    result = executor(env, factory=forbidden_agent).run()
    assert "missing_fulltext" in result["papers"][0]["error"]["message"]
    assert not core_snapshot(env.settings.db_path)[0]


@pytest.mark.parametrize("failure", [KeyboardInterrupt, OSError])
def test_interrupted_or_failed_ingestion_reuses_saved_output_without_model(queue_env, monkeypatch, failure):
    env = queue_env
    real_import = extraction.ingest_paper
    def fail(*a, **kw):
        raise failure("simulated interruption before commit")
    monkeypatch.setattr(extraction, "ingest_paper", fail)
    if failure is KeyboardInterrupt:
        with pytest.raises(KeyboardInterrupt):
            executor(env, offline_agent([[raw_response()]])).run()
    else:
        assert executor(env, offline_agent([[raw_response()]])).run()["failed"] == 1
    before_revision = core_snapshot(env.settings.db_path)[1]["revision"]
    monkeypatch.setattr(extraction, "ingest_paper", real_import)
    result = executor(env, factory=forbidden_agent).run()
    assert result["ok"] and result["papers"][0]["reused_output"]
    assert attempts(env)[0]["status"] == ("interrupted" if failure is KeyboardInterrupt else "failed")
    assert attempts(env)[1]["status"] == "succeeded"
    assert core_snapshot(env.settings.db_path)[1]["revision"] == before_revision + 1


def test_interruption_after_import_commit_already_has_success_checkpoint(queue_env, monkeypatch):
    env = queue_env
    real_import = extraction.ingest_paper
    def interrupt_after_commit(*a, **kw):
        real_import(*a, **kw)
        raise KeyboardInterrupt("simulated process death after commit")
    monkeypatch.setattr(extraction, "ingest_paper", interrupt_after_commit)
    with pytest.raises(KeyboardInterrupt):
        executor(env, offline_agent([[raw_response()]])).run()
    assert attempts(env)[0]["status"] == "succeeded"
    assert not env.repository.pending() and len(core_snapshot(env.settings.db_path)[0]) == 1


def test_concurrent_reimport_is_not_overwritten_by_stale_extraction(queue_env):
    env = queue_env
    def reimport_while_model_runs():
        ingest_paper(env.settings.db_path, {**env.payload, "metadata": {"title": "Updated queue input"}})
        return [raw_response()]
    result = executor(env, offline_agent([reimport_while_model_runs])).run()
    assert result["failed"] == 1 and result["papers"][0]["error"]["type"] == "QueueChangedError"
    assert env.repository.pending()[0]["input"]["metadata"]["title"] == "Updated queue input"
    assert not core_snapshot(env.settings.db_path)[0]


def test_ingestion_rolls_back_if_success_checkpoint_cannot_be_committed(queue_env):
    from src.agents.survey_agent.utils.step2v2_extractor import aggregate_results
    env = queue_env
    pending, = env.repository.pending()
    docs, errors = extraction._source_snapshot(pending["input"])
    assert not errors
    output, = aggregate_results([{"node_id": "W123", "result": raw_response()}], [], {}, preserve_components=True)
    payload = extraction._merge_output("W123", pending["input"], output, docs)
    before = core_snapshot(env.settings.db_path)
    from src.paper_graph.repository import digest
    with pytest.raises(ValueError, match="No running ingestion attempt"):
        ingest_paper(env.settings.db_path, payload, expected_queue_hash=digest(pending["input"]),
                     extraction_attempt_id=999999)
    assert core_snapshot(env.settings.db_path) == before
    assert env.repository.pending()[0]["input"] == pending["input"]


def test_only_one_queue_executor_can_claim_work(queue_env):
    env = queue_env
    with FileLock(str(env.settings.db_path) + ".extract.lock"):
        with pytest.raises(RuntimeError, match="Another.*executor"):
            executor(env, factory=forbidden_agent).run()
    assert not attempts(env)


def test_oversize_fulltext_fails_before_transport_and_records_budget_reason(queue_env):
    env = queue_env
    agent = offline_agent([], context=16_100)
    result = executor(env, agent).run(max_output_tokens=16_000)
    assert result["papers"][0]["stage"] == "extraction"
    assert "input_budget_exceeded:W123" in result["papers"][0]["error"]["message"]
    assert not agent.submissions and not attempts(env)[0]["output_json"]


def test_existing_extractor_selective_retry_keeps_paper_and_baseline_identity():
    from src.agents.survey_agent.utils.step2v2_extractor import extract_paper_info_batch
    first, second = raw_response(), raw_response()
    first["metadata"]["title"], second["metadata"]["title"] = "First paper", "Second paper"
    b1 = {"baselines": [{"name": "Comparison One", "related_to_core": "Conservation relation"}]}
    b2 = {"datasets": [{"name": "Dataset Two", "related_to_core": "Conservation relation"}]}
    agent = offline_agent([[None, second], [first], [b1, None], [b2]])
    result = extract_paper_info_batch({"W1": FULLTEXT, "W2": FULLTEXT}, agent, max_retry=2)
    assert [(p["node_id"], p["metadata"]["title"]) for p in result] == [("W1", "First paper"), ("W2", "Second paper")]
    assert result[0]["graph_data"]["baselines"][0]["name"] == "Comparison One"
    assert result[1]["graph_data"]["datasets"][0]["name"] == "Dataset Two"
    assert [len(p) for p, _ in agent.submissions] == [2, 1, 2, 1]


def test_index_is_gated_until_components_exist_then_checks_real_queries(queue_env):
    env = queue_env
    empty = build_and_check(env.settings, queries=["conservation measurement"], model=env.encoder)
    assert not empty["ok"] and empty["index"]["reason"] == "no_indexable_components"
    assert not env.encoder.calls and not env.settings.index_dir.exists()
    assert executor(env, offline_agent([[raw_response()]])).run()["ok"]
    built = build_and_check(env.settings, queries=["conservation measurement"], model=env.encoder)
    assert built["ok"] and built["index"]["vector_store_size"] == 1
    assert built["health"]["domain_counts"] == {"physics_astronomy": 1}
    assert built["health"]["cross_domain_corpus"] is False
    result, = built["retrieval"]["results"]
    assert result["query_source"] == "user" and result["hits"][0]["paper_id"] == "W123"
    assert result["hits"][0]["matched_components"] and result["hits"][0]["evidence_records"]
    smoke = check_retrieval(env.settings, model=env.encoder)
    assert smoke["ok"] and smoke["results"][0]["query_source"] == "component_summary_smoke"


def test_index_build_covers_complete_active_graph_after_limited_extraction(queue_env):
    env = queue_env
    ingest_paper(env.settings.db_path, {**env.payload, "paper_id": "W124"})
    second = raw_response()
    second["metadata"]["domain"] = "biology"
    assert executor(env, offline_agent([[raw_response()]])).run(limit=1)["succeeded"] == 1
    assert executor(env, offline_agent([[second]])).run(limit=1)["succeeded"] == 1
    result = build_and_check(env.settings, model=env.encoder)
    assert result["ok"] and result["index"]["vector_store_size"] == 2
    assert result["health"]["cross_domain_corpus"] is True
    assert set(result["health"]["domain_counts"]) == {"physics_astronomy", "agricultural_biological_sciences"}


def test_cli_extract_keeps_json_stdout_custom_config_and_reports_query_results(queue_env, tmp_path, monkeypatch, capsys):
    from src import config as config_module
    from src.cli import main
    from src.agents.survey_agent.utils.rich_logger import get_logger
    from src.agents.idea_agent.utils.papers import paper_graph_vector_store
    import sentence_transformers
    env = queue_env
    config_path = tmp_path / "custom.yaml"
    config_path.write_text(OmegaConf.to_yaml(env.config))
    monkeypatch.setattr(config_module, "_config", config_module._config)
    logger = get_logger("offline-queue-cli-test")
    agent = offline_agent([[raw_response()]], logger=logger, noise=True)
    seen = []
    def make_agent(self):
        seen.append(self.config.survey.APIInfo.llm_model_name)
        return agent
    monkeypatch.setattr(PaperGraphExtractionExecutor, "_make_chat_agent", make_agent)
    monkeypatch.setattr(sentence_transformers, "SentenceTransformer", lambda *a, **kw: env.encoder)
    monkeypatch.setattr(paper_graph_vector_store, "SentenceTransformer", lambda *a, **kw: env.encoder)
    capsys.readouterr()
    code = main(["paper-graph", "extract", "--config", str(config_path), "--limit", "1",
                 "--build-index", "--query", "conserved quantity"])
    captured = capsys.readouterr()
    result = json.loads(captured.out)
    assert code == 0 and result["succeeded"] == 1 and result["validation"]["retrieval"]["ok"]
    assert seen == ["offline-model"]
    assert "offline model transport" in captured.err and "offline extractor logger" in captured.err
    code = main(["paper-graph", "check", "--config", str(config_path), "--query", "measurement"])
    assert code == 0 and json.loads(capsys.readouterr().out)["retrieval"]["ok"]


def test_cli_dry_run_does_not_build_and_bad_query_options_return_error(queue_env, tmp_path, monkeypatch, capsys):
    from src import config as config_module
    from src.cli import main
    env = queue_env
    monkeypatch.setattr(config_module, "_config", config_module._config)
    path = tmp_path / "config.yaml"
    path.write_text(OmegaConf.to_yaml(env.config))
    monkeypatch.setattr(PaperGraphExtractionExecutor, "_make_chat_agent", lambda self: forbidden_agent())
    assert main(["paper-graph", "extract", "--config", str(path), "--dry-run", "--build-index"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["validation"]["status"] == "planned" and not env.settings.index_dir.exists()
    assert not attempts(env)
    assert main(["paper-graph", "extract", "--config", str(path), "--query", "x"]) == 2
    assert "requires --build-index" in json.loads(capsys.readouterr().out)["error"]
    assert main(["paper-graph", "extract", "--config", str(path), "--dry-run", "--max-evidence-repairs", "-1"]) == 2
    assert "nonnegative" in json.loads(capsys.readouterr().out)["error"]


def test_cli_retries_saved_evidence_with_only_a_targeted_model_request(queue_env, tmp_path, monkeypatch, capsys):
    from src import config as config_module
    from src.cli import main
    env = queue_env
    saved_failure(env)
    monkeypatch.setattr(config_module, "_config", config_module._config)
    path = tmp_path / "config.yaml"
    path.write_text(OmegaConf.to_yaml(env.config))
    agent = offline_agent([[evidence_patch("/ideation_resource/components/0/source_quote")]])
    monkeypatch.setattr(PaperGraphExtractionExecutor, "_make_chat_agent", lambda self: agent)
    args = ["paper-graph", "extract", "--config", str(path), "--paper-id", "W123", "--retry-failed", "--max-evidence-repairs", "1"]
    assert main([*args, "--dry-run"]) == 0
    assert json.loads(capsys.readouterr().out)["papers"][0]["action"] == "repair_evidence"
    assert not agent.submissions
    assert main(args) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["succeeded"] == 1 and result["papers"][0]["reused_output"]
    assert len(agent.submissions) == 1


@pytest.mark.parametrize("failure", ["build", "health", "query"])
def test_cli_preserves_extraction_result_when_later_validation_fails(queue_env, tmp_path, monkeypatch, capsys, failure):
    from src import config as config_module
    from src.cli import main
    from src.paper_graph import validation
    import sentence_transformers
    env = queue_env
    monkeypatch.setattr(config_module, "_config", config_module._config)
    path = tmp_path / "config.yaml"
    path.write_text(OmegaConf.to_yaml(env.config))
    agent = offline_agent([[raw_response()]])
    monkeypatch.setattr(PaperGraphExtractionExecutor, "_make_chat_agent", lambda self: agent)
    monkeypatch.setattr(sentence_transformers, "SentenceTransformer", lambda *a, **kw: env.encoder)
    def fail(*args, **kwargs):
        raise RuntimeError("offline validation failure")
    if failure == "build":
        monkeypatch.setattr(validation.GraphCoreComponentIndexer, "build", fail)
    elif failure == "health":
        monkeypatch.setattr(validation, "check_paper_graph", fail)
    else:
        env.encoder.encode = fail
        # Publish once during extraction, fail only the subsequent query.
        original = validation.GraphCoreComponentIndexer.build
        def publish(self, *a, **kw):
            env.encoder.encode = Encoder().encode
            result = original(self, *a, **kw)
            env.encoder.encode = fail
            return result
        monkeypatch.setattr(validation.GraphCoreComponentIndexer, "build", publish)
    code = main(["paper-graph", "extract", "--config", str(path), "--build-index", "--query", "measurement"])
    result = json.loads(capsys.readouterr().out)
    assert code == 1 and result["succeeded"] == 1 and result["papers"][0]["status"] == "succeeded"
    assert not result["validation"]["ok"] and not env.repository.pending()


def enqueue_parallel_papers(env, count):
    responses = {}
    for number in range(123, 123 + count):
        paper_id = f"W{number}"
        title = f"Paper {paper_id}"
        quote = f"A component for {paper_id} measures the conserved quantity."
        source = env.source.parent / f"{paper_id}.md"
        source.write_text(FULLTEXT.replace("Example paper", title).replace("A component measures the conserved quantity.", quote))
        ingest_paper(env.settings.db_path, {"paper_id": paper_id, "metadata": {"title": title},
            "source_documents": [{"source_id": paper_id, "path": str(source)}]})
        response = raw_response()
        response["metadata"]["title"] = title
        response["components"][0]["source_quote"] = quote
        responses[paper_id] = response
    return responses


def prompt_paper_id(prompt):
    return re.search(r"(?m)^# Paper (W\d+)$", prompt).group(1)


def test_ten_workers_really_overlap_keep_identity_and_initialize_client_once(queue_env):
    env = queue_env
    responses = enqueue_parallel_papers(env, 23)
    barrier = Barrier(10, timeout=15)
    lock = Lock()
    active, peak = 0, 0
    calls = []
    factory_calls = []
    agent = offline_agent([])

    def transport(prompts, **kwargs):
        nonlocal active, peak
        assert len(prompts) == 1
        paper_id = prompt_paper_id(prompts[0])
        with lock:
            calls.append(paper_id)
            initial_wave = len(calls) <= 10
            active += 1
            peak = max(peak, active)
        try:
            if initial_wave:
                barrier.wait()
            return [json.dumps(responses[paper_id])]
        finally:
            with lock:
                active -= 1

    def factory():
        factory_calls.append(True)
        return agent

    agent.batch_remote_chat = transport
    result = executor(env, factory=factory).run()
    assert result["ok"] and result["succeeded"] == 23 and result["workers"] == 10
    assert peak == 10 and len(factory_calls) == 1
    assert len(calls) == len(set(calls)) == 23
    assert [paper["paper_id"] for paper in result["papers"]] == sorted(responses)
    nodes, state = core_snapshot(env.settings.db_path)
    assert len(nodes) == 23 and validate_graph(env.settings.db_path, nodes)
    for core in nodes:
        paper_id = core["paper_id"]
        assert core["paper_title"] == f"Paper {paper_id}"
        assert core["components"][0]["evidence_records"][0]["quote"] == responses[paper_id]["components"][0]["source_quote"]
    assert len(attempts(env)) == 23 and not env.repository.pending()


def test_scheduler_backfills_before_slow_paper_finishes_and_writes_are_serial(queue_env, monkeypatch):
    env = queue_env
    responses = enqueue_parallel_papers(env, 4)
    first_pair = Barrier(2, timeout=10)
    replacement_started = Event()
    agent = offline_agent([])
    real_import = extraction.ingest_paper
    import_lock = Lock()
    completed_order = []

    def transport(prompts, **kwargs):
        paper_id = prompt_paper_id(prompts[0])
        if paper_id in {"W123", "W124"}:
            first_pair.wait()
        if paper_id == "W123":
            assert replacement_started.wait(timeout=10), "scheduler waited for the whole first pair"
        if paper_id == "W125":
            replacement_started.set()
        return [json.dumps(responses[paper_id])]

    def guarded_import(*args, **kwargs):
        assert import_lock.acquire(blocking=False), "graph writes must not overlap"
        try:
            result = real_import(*args, **kwargs)
            completed_order.append(result["paper_id"])
            return result
        finally:
            import_lock.release()

    agent.batch_remote_chat = transport
    monkeypatch.setattr(extraction, "ingest_paper", guarded_import)
    result = executor(env, agent).run(workers=2)
    assert result["ok"] and result["succeeded"] == 4
    assert completed_order[0] == "W124"
    assert [paper["paper_id"] for paper in result["papers"]] == sorted(responses)


def test_parallel_limit_skips_failed_papers_without_claiming_extra_work(queue_env):
    env = queue_env
    responses = enqueue_parallel_papers(env, 5)
    bad = responses["W123"]
    bad["metadata"]["domain"] = "Others"
    first = executor(env, offline_agent([[bad]])).run(limit=1, workers=1)
    assert first["failed"] == 1
    barrier = Barrier(2, timeout=10)
    agent = offline_agent([])
    calls = []

    def transport(prompts, **kwargs):
        paper_id = prompt_paper_id(prompts[0])
        calls.append(paper_id)
        barrier.wait()
        return [json.dumps(responses[paper_id])]

    agent.batch_remote_chat = transport
    result = executor(env, agent).run(limit=2, workers=10)
    assert result["processed"] == 2 and result["succeeded"] == 2 and result["skipped_failed"] == 1
    assert sorted(calls) == ["W124", "W125"]
    assert [paper["paper_id"] for paper in result["papers"]] == ["W123", "W124", "W125"]
    assert len(attempts(env)) == 3 and result["remaining"] == 3


def test_parallel_saved_repairs_and_fresh_failures_are_isolated_by_paper(queue_env):
    env = queue_env
    responses = enqueue_parallel_papers(env, 3)
    responses["W123"]["components"][0]["source_quote"] = "Broken saved evidence."
    saved = executor(env, offline_agent([[responses["W123"]]])).run(limit=1, workers=1, max_evidence_repairs=0)
    assert saved["partial"] == 1
    responses["W124"]["metadata"]["domain"] = "Others"
    barrier = Barrier(3, timeout=10)
    agent = offline_agent([])
    repairs, fresh = [], []

    def transport(prompts, **kwargs):
        prompt = prompts[0]
        barrier.wait()
        if "repair_failed_evidence_only" in prompt:
            from src.paper_graph.evidence_repair import REPAIR_INSTRUCTIONS
            request = json.loads(prompt.removeprefix(REPAIR_INSTRUCTIONS + "\n\n"))
            repairs.append(request["paper_id"])
            patch = evidence_patch(request["failures"][0]["target_id"], records=[{
                "quote": "A component for W123 measures the conserved quantity.", "source_id": "W123", "source_section": "Results"}])
            return [json.dumps(patch)]
        paper_id = prompt_paper_id(prompt)
        fresh.append(paper_id)
        return [json.dumps(responses[paper_id])]

    agent.batch_remote_chat = transport
    result = executor(env, agent).run(retry_failed=True, workers=3)
    assert result["processed"] == 3 and result["succeeded"] == 2 and result["failed"] == 1
    assert repairs == ["W123"] and sorted(fresh) == ["W124", "W125"]
    first, second, third = result["papers"]
    assert first["reused_output"] and first["input_hash"] == saved["papers"][0]["input_hash"]
    assert "unresolved_discipline" in second["error"]["reasons"] and third["status"] == "succeeded"
    assert result["remaining"] == 1 and env.repository.pending()[0]["paper_id"] == "W124"
    nodes, _ = core_snapshot(env.settings.db_path)
    assert validate_graph(env.settings.db_path, nodes)


def test_parallel_interruption_preserves_other_paid_output_and_leaves_unscheduled_papers_pending(queue_env):
    env = queue_env
    responses = enqueue_parallel_papers(env, 4)
    barrier = Barrier(2, timeout=10)
    agent = offline_agent([])
    instance = executor(env, agent)
    calls = []

    def transport(prompts, **kwargs):
        paper_id = prompt_paper_id(prompts[0])
        calls.append(paper_id)
        barrier.wait()
        if paper_id == "W123":
            raise KeyboardInterrupt("interrupted first paper")
        assert instance._stop_requested.wait(timeout=10)
        return [json.dumps(responses[paper_id])]

    agent.batch_remote_chat = transport
    with pytest.raises(KeyboardInterrupt):
        instance.run(workers=2)
    assert sorted(calls) == ["W123", "W124"]
    assert len(attempts(env)) == 2 and len(env.repository.pending()) == 4
    saved = next(row for row in attempts(env) if row["paper_id"] == "W124")
    assert saved["status"] == "interrupted" and saved["output_json"]
    with FileLock(str(env.settings.db_path) + ".extract.lock", timeout=0):
        pass
    resumed = executor(env, factory=forbidden_agent).run(paper_ids=["W124"], workers=1)
    assert resumed["ok"] and resumed["papers"][0]["reused_output"]
    assert len(env.repository.pending()) == 3


def test_worker_count_does_not_change_fingerprint_and_parallel_dry_run_is_read_only(queue_env):
    env = queue_env
    enqueue_parallel_papers(env, 12)
    before = env.settings.db_path.read_bytes()
    sequential = executor(env, factory=forbidden_agent).run(dry_run=True, workers=1)
    parallel = executor(env, factory=forbidden_agent).run(dry_run=True, workers=10)
    assert sequential["papers"] == parallel["papers"] and parallel["processed"] == 12
    assert parallel["workers"] == 10 and not attempts(env)
    assert env.settings.db_path.read_bytes() == before


@pytest.mark.parametrize("workers", [0, -1, True, 1.5])
def test_invalid_worker_count_is_rejected_before_writes_or_model_initialization(queue_env, workers):
    with pytest.raises(ValueError, match="workers must be a positive integer"):
        executor(queue_env, factory=forbidden_agent).run(workers=workers)
    assert not attempts(queue_env)


def test_parallel_workers_inherit_request_context(queue_env):
    from contextvars import ContextVar
    env = queue_env
    responses = enqueue_parallel_papers(env, 2)
    request_context = ContextVar("parallel_test_request_context", default="missing")
    agent = offline_agent([])
    seen = []

    def transport(prompts, **kwargs):
        seen.append(request_context.get())
        return [json.dumps(responses[prompt_paper_id(prompts[0])])]

    agent.batch_remote_chat = transport
    token = request_context.set("current-research-policy")
    try:
        result = executor(env, agent).run(workers=2)
    finally:
        request_context.reset(token)
    assert result["ok"] and seen == ["current-research-policy"] * 2


def test_shared_real_chat_scheduler_keeps_concurrent_paper_retries_separate(queue_env, monkeypatch):
    from contextvars import ContextVar
    from src.agents.survey_agent.utils.api_call import ChatAgent
    env = queue_env
    responses = enqueue_parallel_papers(env, 3)
    barrier = Barrier(3, timeout=10)
    lock = Lock()
    calls = {}
    contexts = []
    request_context = ContextVar("nested_scheduler_request_context", default="missing")
    agent = offline_agent([])
    del agent.batch_remote_chat
    agent.config.APIInfo.batch_chat_timeout = 20
    agent.config.APIInfo.low_flow_mode = False

    def request(self, index, content, *args, **kwargs):
        paper_id = prompt_paper_id(content)
        with lock:
            calls[paper_id] = calls.get(paper_id, 0) + 1
            count = calls[paper_id]
            contexts.append(request_context.get())
        if count == 1:
            barrier.wait()
        if paper_id == "W123" and count == 1:
            return index, "{malformed model JSON"
        return index, json.dumps(responses[paper_id])

    monkeypatch.setattr(ChatAgent, "_ChatAgent__remote_chat", request)
    token = request_context.set("shared-research-budget")
    try:
        result = executor(env, agent).run(workers=3)
    finally:
        request_context.reset(token)
    assert result["ok"] and result["succeeded"] == 3
    assert calls == {"W123": 2, "W124": 1, "W125": 1}
    assert contexts == ["shared-research-budget"] * 4
    nodes, _ = core_snapshot(env.settings.db_path)
    assert validate_graph(env.settings.db_path, nodes)
    assert {node["paper_id"]: node["paper_title"] for node in nodes} == {paper_id: f"Paper {paper_id}" for paper_id in responses}


def test_cli_parallel_index_build_waits_for_every_paper(queue_env, tmp_path, monkeypatch, capsys):
    from src import config as config_module
    from src.cli import main
    from src.paper_graph import validation
    env = queue_env
    responses = enqueue_parallel_papers(env, 3)
    barrier = Barrier(3, timeout=10)
    agent = offline_agent([])

    def transport(prompts, **kwargs):
        barrier.wait()
        return [json.dumps(responses[prompt_paper_id(prompts[0])])]

    agent.batch_remote_chat = transport
    monkeypatch.setattr(config_module, "_config", config_module._config)
    monkeypatch.setattr(PaperGraphExtractionExecutor, "_make_chat_agent", lambda self: agent)
    real_build = validation.build_and_check
    builds = []

    def build(settings, **kwargs):
        assert not env.repository.pending()
        assert len(core_snapshot(env.settings.db_path)[0]) == 3
        builds.append(True)
        return real_build(settings, **kwargs, model=env.encoder)

    monkeypatch.setattr(validation, "build_and_check", build)
    path = tmp_path / "config.yaml"
    path.write_text(OmegaConf.to_yaml(env.config))
    assert main(["paper-graph", "extract", "--config", str(path), "--workers", "3", "--build-index"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["workers"] == 3 and result["succeeded"] == 3
    assert result["validation"]["ok"] and result["validation"]["index"]["vector_store_size"] == 3
    assert builds == [True]


@pytest.mark.parametrize("change", [
    lambda core: core.update(source_section="Results"),
    lambda core: core.update(source_section="Unmarked subsection"),
    lambda core: core.update(locator={"start": 0, "end": 5}),
    lambda core: core.update(locator={"start": True, "end": 90}),
])
def test_unique_quote_locator_correction_is_audited_without_model_repair(queue_env, change):
    env = queue_env
    response = raw_response()
    change(response["core_contributions"][0])
    original_core = response["core_contributions"][0].copy()
    agent = offline_agent([[response]])
    result = executor(env, agent).run(max_evidence_repairs=0)
    assert result["ok"] and len(agent.submissions) == 1
    paper, = result["papers"]
    assert paper["evidence_repairs"] == 0 and paper["evidence_locator_corrections"] == 1
    event, = repair_events(env)
    assert event["round"] == 0 and event["status"] == "applied"
    request = json.loads(event["request_json"])
    assert request["method"] == "deterministic_locator"
    assert request["failures"][0]["failed_evidence"]["quote"] == original_core["quote"]
    output = json.loads(attempts(env)[0]["output_json"])
    core = output["ideation_resource"]["core_contributions"][0]
    for key in ("id", "name", "summary", "structure", "assumptions", "boundary_conditions", "source_section"):
        assert core[key] == original_core[key]
    record, = core["evidence_records"]
    assert record["quote"] == original_core["quote"] and record["locator"]["section"] == "Method"
    location = record["locator"]
    assert FULLTEXT[location["start"]:location["end"]] == record["quote"]
    assert env.source.read_text() == FULLTEXT
    assert validate_graph(env.settings.db_path, core_snapshot(env.settings.db_path)[0])


def test_plain_subheading_corrections_reuse_verified_locations_across_entities(queue_env, monkeypatch):
    from copy import deepcopy
    from src.paper_graph.evidence_repair import EvidenceLocatorCache
    env = queue_env
    body = FULLTEXT.replace("## Results\n", "## Results\nMeasurements\n\n")
    env.source.write_text(body)
    ingest_paper(env.settings.db_path, env.payload)
    response = raw_response()
    quote = response["components"][0]["source_quote"]
    response["components"][0]["source_section"] = "Measurements"
    second = deepcopy(response["components"][0])
    second.update(id="second", name="Second measurement", source_section="Another subsection")
    verified = deepcopy(second)
    verified.update(id="verified", name="Verified measurement", source_section="Results")
    response["components"].extend([second, verified])
    response["core_contributions"][0]["evidence_records"] = [{"quote": quote, "source_section": "Measurements"}]
    calls = []
    real_locate = EvidenceLocatorCache._locate

    def locate(cache, doc, candidate_quote):
        calls.append((doc["source_id"], doc["sha256"], candidate_quote))
        return real_locate(cache, doc, candidate_quote)

    monkeypatch.setattr(EvidenceLocatorCache, "_locate", locate)
    agent = offline_agent([[response]])
    result = executor(env, agent).run()
    assert result["ok"] and len(agent.submissions) == 1
    paper, = result["papers"]
    assert paper["evidence_repairs"] == 0
    assert paper["evidence_locator_corrections"] == paper["evidence_locator_cache_hits"] == 3
    assert sum(candidate_quote == quote for _, _, candidate_quote in calls) == 1
    event, = repair_events(env)
    assert len(json.loads(event["outcome_json"])["applied_targets"]) == 3
    assert validate_graph(env.settings.db_path, core_snapshot(env.settings.db_path)[0])


def test_previously_saved_locator_failure_resumes_without_model_initialization(queue_env):
    from src.agents.survey_agent.utils.step2v2_extractor import aggregate_results
    env = queue_env
    response = raw_response()
    response["components"][0]["source_section"] = "Unmarked subsection"
    output, = aggregate_results([{"node_id": "W123", "result": response}], [], {}, preserve_components=True)
    plan = executor(env, factory=forbidden_agent).run(dry_run=True)
    attempt_id = env.repository.start_attempt("W123", plan["papers"][0]["input_hash"])
    env.repository.checkpoint_attempt(attempt_id, status="failed", stage="evidence_verification", output=output,
                                     error={"message": "unknown_section"})
    result = executor(env, factory=forbidden_agent).run(retry_failed=True)
    assert result["ok"] and result["papers"][0]["reused_output"]
    assert result["papers"][0]["evidence_locator_corrections"] == 1
    assert [row["status"] for row in attempts(env)] == ["failed", "succeeded"]
    assert json.loads(attempts(env)[0]["output_json"]) == output


def test_ambiguous_quote_locations_require_a_model_choice(queue_env):
    env = queue_env
    quote = "A component measures the conserved quantity."
    env.source.write_text(FULLTEXT + "\n## Discussion\n" + quote + "\n")
    ingest_paper(env.settings.db_path, env.payload)
    response = raw_response()
    response["components"][0]["source_section"] = "Unknown section"
    def choose_candidate():
        from src.paper_graph.evidence_repair import REPAIR_INSTRUCTIONS
        prompt, = agent.submissions[-1][0]
        request = json.loads(prompt.removeprefix(REPAIR_INSTRUCTIONS + "\n\n"))
        candidates = request["location_candidates"]
        assert len(candidates) == 2
        selected = next(candidate for candidate in candidates
                        if candidate["evidence_record"]["locator"]["section"] == "Discussion")
        return [{"repairs": [{"target_id": selected["target_id"], "candidate_ids": [selected["candidate_id"]]}]}]
    agent = offline_agent([[response], choose_candidate])
    result = executor(env, agent).run()
    assert result["ok"] and len(agent.submissions) == 2
    paper, = result["papers"]
    assert paper["evidence_repairs"] == 1 and paper["evidence_locator_corrections"] == 0
    event, = repair_events(env)
    assert event["round"] == 1 and event["status"] == "applied"
    request = json.loads(event["request_json"])
    selection = json.loads(json.loads(event["response_json"]))["repairs"][0]
    assert set(selection) == {"target_id", "candidate_ids"}
    assert selection["candidate_ids"][0] in {candidate["candidate_id"] for candidate in request["location_candidates"]}
    nodes, _ = core_snapshot(env.settings.db_path)
    assert validate_graph(env.settings.db_path, nodes)
    record, = nodes[0]["components"][0]["evidence_records"]
    assert record["locator"]["section"] == "Discussion"
    assert record["locator"]["start"] == env.source.read_text().rindex(quote)


def test_saved_core_repair_selects_candidate_and_checkpoints_real_heading_without_reextraction(queue_env):
    from src.paper_graph.evidence_repair import REPAIR_INSTRUCTIONS
    env = queue_env
    quote = "A conserves B under constant input."
    body = FULLTEXT.replace("## Method", "## \uf0b7 Method") + "\n## o Method\n" + quote + "\n"
    env.source.write_text(body, encoding="utf-8")
    ingest_paper(env.settings.db_path, env.payload)
    failed = executor(env, offline_agent([[raw_response()]])).run(max_evidence_repairs=0)
    assert failed["failed"] == 1 and not core_snapshot(env.settings.db_path)[0]
    def choose_candidate():
        prompt, = agent.submissions[-1][0]
        request = json.loads(prompt.removeprefix(REPAIR_INSTRUCTIONS + "\n\n"))
        candidates = request["location_candidates"]
        assert len(candidates) == 2
        selected = next(candidate for candidate in candidates
                        if candidate["evidence_record"]["locator"]["section"] == "\uf0b7 Method")
        return [{"repairs": [{"target_id": selected["target_id"], "candidate_ids": [selected["candidate_id"]]}]}]
    agent = offline_agent([choose_candidate])
    result = executor(env, agent).run(retry_failed=True)
    assert result["ok"] and result["papers"][0]["reused_output"] and len(agent.submissions) == 1
    saved = json.loads(attempts(env)[-1]["output_json"])
    record, = saved["ideation_resource"]["core_contributions"][0]["evidence_records"]
    assert record["locator"]["section"] == "\uf0b7 Method" and record["locator"]["start"] == body.index(quote)
    assert record["quote"] == body[record["locator"]["start"]:record["locator"]["end"]]
    event, = repair_events(env)
    assert event["status"] == "applied" and not json.loads(event["outcome_json"])["remaining_issues"]
    nodes, _ = core_snapshot(env.settings.db_path)
    assert validate_graph(env.settings.db_path, nodes)


@pytest.mark.parametrize("change", [
    lambda record: record.update(source_section="Method"),
    lambda record: record.update(source_section="Unmarked subsection"),
    lambda record: record.update(locator={"start": True, "end": 20}),
])
def test_unique_model_repair_quote_gets_locator_corrected_before_another_request(queue_env, change, capsys):
    env = queue_env
    saved_failure(env)
    patch = evidence_patch("/ideation_resource/components/0/source_quote")
    change(patch["repairs"][0]["evidence_records"][0])
    agent = offline_agent([[patch]])
    capsys.readouterr()
    result = executor(env, agent).run(retry_failed=True)
    assert result["ok"] and len(agent.submissions) == 1
    assert result["papers"][0]["evidence_repairs"] == 1
    event, = repair_events(env)
    assert json.loads(event["response_json"]) == json.dumps(patch)
    assert event["status"] == "applied"
    records = [json.loads(line) for line in capsys.readouterr().err.splitlines()]
    started, = [record for record in records if record["event"] == "evidence_repair_started"]
    finished, = [record for record in records if record["event"] == "evidence_repair_finished"]
    assert started["paper_id"] == finished["paper_id"] == "W123"
    assert started["entity"] == finished["entity"] == "component[0]:Measurement"
    assert started["round"] == finished["round"] == finished["model_requests"] == 1
    assert started["repair_id"] == finished["repair_id"] == event["repair_id"]
    assert finished["status"] == "applied" and not finished["remaining"]
    assert "paper=W123" in agent.submissions[0][1]["desc"]


def test_locator_correction_still_requires_full_structural_validation(queue_env):
    env = queue_env
    response = raw_response()
    response["components"][0].update(source_section="Missing section", related_to_core="Unknown parent")
    agent = offline_agent([[response]])
    result = executor(env, agent).run()
    paper, = result["papers"]
    assert result["partial"] == 1 and paper["evidence_locator_corrections"] == 1
    assert "unlinked_components" in paper["error"]["reasons"]
    assert len(agent.submissions) == 1 and not core_snapshot(env.settings.db_path)[0][0]["components"]


def test_locator_cache_requires_unique_source_identity_checksum_and_literal_quote():
    from src.paper_graph.evidence_repair import EvidenceLocatorCache
    from src.paper_graph.ingest import source_documents
    quote = "A unique original statement."
    docs = source_documents({"source_documents": [
        {"source_id": "first", "text": "## Method\n" + quote},
        {"source_id": "second", "text": "## Results\n" + quote},
    ]})
    cache = EvidenceLocatorCache(docs)
    assert cache.resolve({"quote": quote}, {})[0] is None
    location, reused = cache.resolve({"quote": quote, "source_id": "first", "source_sha256": docs[0]["sha256"]}, {})
    assert location["source_id"] == "first" and location["locator"]["section"] == "Method"
    assert reused
    for fields in [{"source_id": "missing"}, {"source_id": "first", "source_sha256": "wrong"},
                   {"source_id": "first", "locator": {"path": "/wrong/source.md"}},
                   {"source_id": "first", "quote": "A paraphrase of the statement."}]:
        assert cache.resolve({"quote": quote, **fields}, {})[0] is None
    changed_docs = source_documents({"source_documents": [{"source_id": "first", "text": "## Changed\n" + quote}]})
    changed = EvidenceLocatorCache(changed_docs)
    assert changed.resolve({"quote": quote, "source_id": "first", "source_sha256": docs[0]["sha256"]}, {})[0] is None
    updated, reused = changed.resolve({"quote": quote, "source_id": "first"}, {})
    assert updated["source_sha256"] != location["source_sha256"] and not reused


@pytest.mark.parametrize("token_capacity", [None, 10000])
def test_batch_logs_identify_request_and_disable_progress_on_redirected_streams(queue_env, monkeypatch, capsys,
                                                                             token_capacity):
    import sys
    from src.agents.survey_agent.utils.api_call import ChatAgent
    logger = SimpleNamespace(info=lambda message, *args: print(message % args, file=sys.stderr),
                             warning=lambda *args: None, error=lambda *args: None)
    agent = offline_agent([], logger=logger)
    del agent.batch_remote_chat
    agent.config.APIInfo.low_flow_mode = False
    monkeypatch.setattr(ChatAgent, "_ChatAgent__remote_chat", lambda self, index, content, *args, **kwargs: (index, "answer"))
    desc = "Evidence repair paper=W123 entity=Measurement round=1/2"
    assert agent.batch_remote_chat(["question"], desc=desc, max_in_flight_tokens=token_capacity) == ["answer"]
    captured = capsys.readouterr()
    assert desc in captured.err and "completed." in captured.err
    assert "\r" not in captured.err and "\x1b" not in captured.err and "| 0/1" not in captured.err


def test_partial_paper_indexes_only_verified_components_and_resumes_saved_candidates(queue_env):
    env = queue_env
    response = raw_response()
    response["components"].append({**response["components"][0], "id": "secondary", "name": "Secondary measurement",
                                   "source_quote": "An unsupported measurement claim."})
    queued_input = env.repository.pending()[0]["input"]
    first = executor(env, offline_agent([[response]])).run(max_evidence_repairs=0)
    assert not first["ok"] and first["partial"] == 1 and first["failed"] == 0 and first["remaining"] == 1
    paper = first["papers"][0]
    assert paper["result"]["cores"] == paper["result"]["components"] == 1
    candidate, = paper["result"]["candidates"]
    assert candidate["verification_status"] == "unverified"
    assert candidate["candidate"]["source_quote"] == "An unsupported measurement claim."
    pending, = env.repository.pending()
    assert pending["status"] == pending["execution"]["status"] == "partial"
    assert pending["input"] == queued_input and pending["execution"]["has_output"]
    built = build_and_check(env.settings, queries=["measurement"], model=env.encoder)
    assert built["ok"] and built["index"]["vector_store_size"] == 1
    nodes, _ = core_snapshot(env.settings.db_path)
    assert nodes[0]["verification_status"] == nodes[0]["components"][0]["verification_status"] == "verified"
    assert [component["name"] for component in nodes[0]["components"]] == ["Measurement"]
    agent = offline_agent([[evidence_patch("/ideation_resource/components/1/source_quote")]])
    resumed = executor(env, agent).run()
    assert resumed["ok"] and resumed["succeeded"] == 1 and resumed["papers"][0]["reused_output"]
    assert resumed["papers"][0]["input_hash"] == paper["input_hash"] and len(agent.submissions) == 1
    assert [attempt["status"] for attempt in attempts(env)] == ["partial", "succeeded"]
    assert len(core_snapshot(env.settings.db_path)[0][0]["components"]) == 2


def test_unverified_parent_blocks_its_components_without_discarding_other_cores(queue_env):
    env = queue_env
    response = raw_response()
    response["core_contributions"].append({**response["core_contributions"][0], "id": "unsupported",
        "name": "Unsupported relation", "quote": "A fabricated relation.", "components": [{
            **response["components"][0], "id": "blocked", "name": "Blocked component"}]})
    result = executor(env, offline_agent([[response]])).run(max_evidence_repairs=0)
    assert result["partial"] == 1
    candidates = result["papers"][0]["result"]["candidates"]
    assert {candidate["verification_status"] for candidate in candidates} == {"unverified", "blocked"}
    blocked, = [candidate for candidate in candidates if candidate["name"] == "Blocked component"]
    assert blocked["evidence_status"] == "verified" and any("parent_contribution_unverified" in reason
                                                            for reason in blocked["reasons"])
    nodes, _ = core_snapshot(env.settings.db_path)
    assert len(nodes) == 1 and nodes[0]["full_name"] == "Conservation relation"
    assert validate_graph(env.settings.db_path, nodes)


def test_format_only_extraction_needs_no_model_repair_and_survives_repeated_headings(queue_env):
    env = queue_env
    body = FULLTEXT.replace("A component measures", "A\u00a0component measures")
    body = body.replace("## Results", "## Results\nAn unrelated result.\n## Results")
    env.source.write_text(body, encoding="utf-8")
    ingest_paper(env.settings.db_path, env.payload)
    agent = offline_agent([[raw_response()]])
    result = executor(env, agent).run()
    assert result["ok"] and len(agent.submissions) == 1 and result["papers"][0]["evidence_repairs"] == 0
    nodes, _ = core_snapshot(env.settings.db_path)
    record, = nodes[0]["components"][0]["evidence_records"]
    assert record["quote"].startswith("A\u00a0component")
    assert validate_graph(env.settings.db_path, nodes)
    assert build_and_check(env.settings, queries=["measurement"], model=env.encoder)["ok"]


def test_partial_updates_merge_verified_fragments_but_never_publish_bad_candidates(queue_env):
    env = queue_env
    response = raw_response()
    response["components"].append({**response["components"][0], "id": "secondary", "name": "Secondary measurement",
                                   "source_quote": "Unsupported secondary quote."})
    assert executor(env, offline_agent([[response]])).run(max_evidence_repairs=0)["partial"] == 1
    payload = json.loads(attempts(env)[0]["output_json"])
    payload["source_documents"] = env.payload["source_documents"]
    payload["ideation_resource"]["components"][0]["source_quote"] = "Unsupported original quote."
    payload["ideation_resource"]["components"][1]["source_quote"] = "A component measures the conserved quantity."
    imported = ingest_paper(env.settings.db_path, payload)
    assert imported["status"] == "partial" and imported["components"] == 2
    assert imported["candidates"][0]["candidate"]["source_quote"] == "Unsupported original quote."
    nodes, _ = core_snapshot(env.settings.db_path)
    assert len(nodes[0]["components"]) == 2 and validate_graph(env.settings.db_path, nodes)
    assert all("Unsupported" not in record["quote"] for component in nodes[0]["components"]
               for record in component["evidence_records"])


def test_partial_import_and_checkpoint_commit_atomically(queue_env, monkeypatch):
    env = queue_env
    response = raw_response()
    response["components"][0]["source_quote"] = "Unsupported quote."
    real_import = extraction.ingest_paper

    def interrupt_after_commit(*args, **kwargs):
        real_import(*args, **kwargs)
        raise KeyboardInterrupt("after partial commit")

    monkeypatch.setattr(extraction, "ingest_paper", interrupt_after_commit)
    with pytest.raises(KeyboardInterrupt):
        executor(env, offline_agent([[response]])).run(workers=1, max_evidence_repairs=0)
    assert attempts(env)[0]["status"] == "partial" and env.repository.pending()[0]["status"] == "partial"
    assert len(core_snapshot(env.settings.db_path)[0]) == 1
    monkeypatch.setattr(extraction, "ingest_paper", real_import)
    agent = offline_agent([[evidence_patch("/ideation_resource/components/0/source_quote")]])
    assert executor(env, agent).run()["succeeded"] == 1 and len(agent.submissions) == 1


def test_partial_import_rolls_back_without_a_matching_execution_checkpoint(queue_env):
    from src.agents.survey_agent.utils.step2v2_extractor import aggregate_results
    from src.paper_graph.repository import digest

    env = queue_env
    pending, = env.repository.pending()
    docs, errors = extraction._source_snapshot(pending["input"])
    assert not errors
    response = raw_response()
    response["components"][0]["source_quote"] = "Unsupported quote."
    output, = aggregate_results([{"node_id": "W123", "result": response}], [], {}, preserve_components=True)
    payload = extraction._merge_output("W123", pending["input"], output, docs)
    before = core_snapshot(env.settings.db_path)
    with pytest.raises(ValueError, match="No running ingestion attempt"):
        ingest_paper(env.settings.db_path, payload, expected_queue_hash=digest(pending["input"]),
                     extraction_attempt_id=999999, queue_input=pending["input"])
    assert core_snapshot(env.settings.db_path) == before
    assert env.repository.pending()[0] == pending


def test_changed_source_partial_import_does_not_retain_previous_source_nodes(queue_env):
    env = queue_env
    response = raw_response()
    response["components"][0]["source_quote"] = "Unsupported quote."
    assert executor(env, offline_agent([[response]])).run(max_evidence_repairs=0)["partial"] == 1
    old_nodes, _ = core_snapshot(env.settings.db_path)
    env.source.write_text(FULLTEXT + "A new retained version.\n", encoding="utf-8")
    response["core_contributions"][0].update(id="new-relation", name="New relation")
    response["components"][0]["related_to_core"] = "New relation"
    imported = ingest_paper(env.settings.db_path, {**env.payload, "metadata": response["metadata"],
                                                  "ideation_resource": response})
    assert imported["status"] == "partial"
    nodes, _ = core_snapshot(env.settings.db_path)
    assert len(nodes) == 1 and nodes[0]["node_id"] != old_nodes[0]["node_id"]
    assert nodes[0]["evidence_records"][0]["source_sha256"] != old_nodes[0]["evidence_records"][0]["source_sha256"]
    assert validate_graph(env.settings.db_path, nodes)


def test_runtime_provenance_rejects_explicitly_unverified_graph_nodes(queue_env):
    env = queue_env
    assert executor(env, offline_agent([[raw_response()]])).run()["ok"]
    nodes, _ = core_snapshot(env.settings.db_path)
    core = {**nodes[0], "verification_status": "unverified"}
    with env.repository.write() as connection:
        connection.execute("UPDATE nodes SET raw_json=? WHERE id=?", (json.dumps(core), core["node_id"]))
    nodes, _ = core_snapshot(env.settings.db_path)
    with pytest.raises(ValueError, match="Unverified graph candidate"):
        validate_graph(env.settings.db_path, nodes)


def test_domain_coverage_excludes_partial_cores_without_indexed_components(queue_env):
    env = queue_env
    response = raw_response()
    response["components"][0]["source_quote"] = "Unsupported quote."
    assert executor(env, offline_agent([[response]])).run(max_evidence_repairs=0)["partial"] == 1
    ingest_paper(env.settings.db_path, {**env.payload, "paper_id": "W124", "ideation_resource": raw_response(),
        "metadata": {"title": "Another paper", "domain": "biology"}})
    built = build_and_check(env.settings, queries=["measurement"], model=env.encoder)
    assert built["ok"] and built["health"]["cross_domain_corpus"] is False
    assert built["health"]["domain_counts"] == {"agricultural_biological_sciences": 1}
