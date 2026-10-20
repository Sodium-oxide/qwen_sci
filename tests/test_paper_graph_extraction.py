"""Offline queue execution through the real extractor, importer and vector store."""
from __future__ import annotations

import json
from pathlib import Path
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


@pytest.mark.parametrize("change,reason", [
    (lambda r: r["core_contributions"][0].update(quote="Invented causal relation."), "unverified_evidence"),
    (lambda r: r["core_contributions"][0].update(source_section="Results"), "unverified_evidence"),
    (lambda r: r["core_contributions"][0].update(page=9), "unverified_evidence"),
    (lambda r: r["core_contributions"][0].update(source_id="unknown-source"), "unverified_evidence"),
    (lambda r: r["core_contributions"][0].update(locator={"start": 0, "end": 5}), "unverified_evidence"),
    (lambda r: r["core_contributions"][0].update(locator={"start": True, "end": 90}), "unverified_evidence"),
    (lambda r: r["core_contributions"][0].update(locator={"path": "/invented/paper.md"}), "unverified_evidence"),
    (lambda r: r["components"][0].update(related_to_core="Nonexistent core"), "unlinked_components"),
    (lambda r: r["components"][0].update(source_quote="Fabricated measurement."), "unverified_evidence"),
    (lambda r: r["metadata"].update(domain="Others"), "unresolved_discipline"),
    (lambda r: r.update(components=[None]), "invalid_component"),
    (lambda r: r["core_contributions"][0].update(evidence_records=[{"quote": "Fabricated extra quote."}]), "unverified_evidence"),
    (lambda r: r["components"][0].update(quote="Fabricated alias alongside a valid source_quote."), "unverified_evidence"),
    (lambda r: r["core_contributions"][0].update(evidence=42), "invalid_evidence"),
])
def test_invalid_output_retains_specific_error_without_graph_changes(queue_env, change, reason):
    env = queue_env
    response = raw_response()
    change(response)
    before = core_snapshot(env.settings.db_path)
    result = executor(env, offline_agent([[response]])).run()
    assert not result["ok"] and result["failed"] == 1
    paper = result["papers"][0]
    assert paper["stage"] == "evidence_verification"
    assert reason in paper["error"]["message"]
    assert core_snapshot(env.settings.db_path) == before
    pending, = env.repository.pending()
    assert pending["execution"]["status"] == "failed" and pending["execution"]["has_output"]
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
    result = executor(env, factory=forbidden_agent).run()
    assert result["failed"] == 1 and "unverified_evidence" in result["papers"][0]["error"]["message"]
    assert not core_snapshot(env.settings.db_path)[0]


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


def test_failed_evidence_requires_explicit_retry_and_history_is_preserved(queue_env):
    env = queue_env
    bad = raw_response()
    bad["components"][0]["source_quote"] = "Unverifiable quotation."
    assert executor(env, offline_agent([[bad]])).run()["failed"] == 1
    assert executor(env, factory=forbidden_agent).run()["skipped_failed"] == 1
    retried = executor(env, offline_agent([[raw_response()]])).run(retry_failed=True)
    assert retried["ok"] and not retried["papers"][0]["reused_output"]
    assert [a["status"] for a in attempts(env)] == ["failed", "succeeded"]


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
