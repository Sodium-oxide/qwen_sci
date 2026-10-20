"""Real SQLite/FAISS contracts with deterministic offline embeddings."""
from __future__ import annotations

import copy
import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from omegaconf import OmegaConf

from src.paper_graph.artifacts import file_hash, index_generation, model_identity, read_artifacts
from src.paper_graph.health import check_paper_graph
from src.paper_graph.indexing import GraphCoreComponentIndexer
from src.paper_graph.ingest import import_survey_cache, ingest_paper, normalize_extraction, source_documents
from src.paper_graph.provenance import validate_graph
from src.paper_graph.repository import PaperGraphRepository, core_snapshot, readonly_connection
from src.paper_graph.settings import PaperGraphSettings
from src.paper_graph.survey import ingest_survey_paper


class Encoder:
    def __init__(self):
        self.calls = []

    def encode(self, texts, **kwargs):
        self.calls.extend(texts)
        return np.array([[1, 0 if "dominant" in t else .25, .1] for t in texts], dtype=np.float32)


@pytest.fixture
def corpus(tmp_path):
    model = tmp_path / "model"
    model.mkdir()
    (model / "config.json").write_text("{}")
    (model / "modules.json").write_text("[]")
    (model / "pytorch_model.bin").write_bytes(b"offline-test-model")
    source = tmp_path / "paper.md"
    source.write_text("# Example paper\n\n## Method\nA conserves B under constant input.\n"
                      "This relation assumes stationary noise.\nIt holds only at equilibrium.\n"
                      "## Results\nA component measures the conserved quantity.\n", encoding="utf-8")
    payload = {"paper_id": "https://openalex.org/W123", "metadata": {"title": "Example paper", "domain": "physics"},
        "source_documents": [{"source_id": "local-paper", "path": str(source)}],
        "ideation_resource": {"core_contributions": [{"id": "relation", "name": "Conservation relation",
            "summary": "A conservation relation", "quote": "A conserves B under constant input.", "source_section": "Method",
            "structure": "A conserves B", "assumptions": ["stationary noise"], "boundary_conditions": ["equilibrium"],
            "components": [{"id": "measurement", "name": "Measurement", "summary": "Measures a conserved quantity",
                "source_quote": "A component measures the conserved quantity.", "source_section": "Results"}]}]}}
    settings = PaperGraphSettings(tmp_path / "graph.db", tmp_path / "index", model)
    return SimpleNamespace(settings=settings, payload=payload, source=source, encoder=Encoder())


def build(corpus, **kwargs):
    return GraphCoreComponentIndexer(corpus.settings.db_path, corpus.settings.index_dir,
                                     corpus.settings.model_path, model=corpus.encoder).build(**kwargs)


def load_store(corpus, **kwargs):
    from src.agents.idea_agent.utils.papers.paper_graph_vector_store import PaperGraphComponentVectorStore
    return PaperGraphComponentVectorStore(config={"paper_graph": vars(corpus.settings)},
                                          model=corpus.encoder, **kwargs).load()


def test_nested_ingestion_stable_ids_idempotency_and_queue(corpus):
    first = ingest_paper(corpus.settings.db_path, corpus.payload)
    assert first == {"paper_id": "W123", "changed": True, "cores": 1, "components": 1, "pending_reasons": []}
    nodes, version = core_snapshot(corpus.settings.db_path)
    assert validate_graph(corpus.settings.db_path, nodes)
    assert not ingest_paper(corpus.settings.db_path, corpus.payload)["changed"]
    updated = copy.deepcopy(corpus.payload)
    updated["ideation_resource"]["core_contributions"][0]["summary"] = "Edited contribution summary"
    assert ingest_paper(corpus.settings.db_path, updated)["changed"]
    after, current = core_snapshot(corpus.settings.db_path)
    assert after[0]["node_id"] == nodes[0]["node_id"]
    assert after[0]["components"][0]["node_id"] == nodes[0]["components"][0]["node_id"]
    assert current["revision"] == version["revision"] + 1
    assert not PaperGraphRepository(corpus.settings.db_path).pending()


def test_section_duplicates_merge_evidence_and_reorder_is_idempotent(corpus):
    cores = corpus.payload["ideation_resource"]["core_contributions"]
    extra = copy.deepcopy(cores[0])
    extra["quote"] = "This relation assumes stationary noise."
    cores.append(extra)
    imported = ingest_paper(corpus.settings.db_path, corpus.payload)
    assert imported["cores"] == imported["components"] == 1
    nodes, _ = core_snapshot(corpus.settings.db_path)
    assert len(nodes[0]["evidence_records"]) == 2
    cores.reverse()
    assert not ingest_paper(corpus.settings.db_path, corpus.payload)["changed"]


@pytest.mark.parametrize("mutation,reason", [
    (lambda p: p["ideation_resource"]["core_contributions"][0].update(quote="A ... under constant input."), "contribution_evidence_missing"),
    (lambda p: p["ideation_resource"]["core_contributions"][0].update(source_section="Results"), "contribution_evidence_missing"),
    (lambda p: p["ideation_resource"]["core_contributions"][0].update(page=9), "contribution_evidence_missing"),
    (lambda p: p["metadata"].update(domain="Others"), "unresolved_discipline"),
    (lambda p: p["ideation_resource"].update(components=[{"name": "orphan", "related_to_core": "missing", "summary": "x"}]), "unlinked_components"),
])
def test_incomplete_data_queued_without_invented_evidence(corpus, mutation, reason):
    mutation(corpus.payload)
    result = ingest_paper(corpus.settings.db_path, corpus.payload)
    assert any(r.startswith(reason) for r in result["pending_reasons"])
    assert PaperGraphRepository(corpus.settings.db_path).pending()


def test_legacy_quote_locator_recovery_and_page_specific_text(corpus):
    core = corpus.payload["ideation_resource"]["core_contributions"][0]
    del core["source_section"]
    assert not ingest_paper(corpus.settings.db_path, corpus.payload)["pending_reasons"]
    nodes, _ = core_snapshot(corpus.settings.db_path)
    assert nodes[0]["evidence_records"][0]["locator"]["section"] == "Method"
    corpus.payload["source_documents"][0]["page"] = 3
    core["page"] = 3
    assert not ingest_paper(corpus.settings.db_path, corpus.payload)["pending_reasons"]
    validate_graph(corpus.settings.db_path, core_snapshot(corpus.settings.db_path)[0])


def test_source_checksum_and_missing_file_are_not_replaced_by_inline_text(corpus):
    with pytest.raises(ValueError, match="checksum"):
        source_documents({}, [{"path": str(corpus.source), "sha256": "wrong"}])
    assert not source_documents({}, [{"path": str(corpus.source.with_name("missing.md")), "text": "invented"}])


def test_keynote_update_preserves_valid_structure_and_authoritative_delete_removes_it(corpus):
    ingest_paper(corpus.settings.db_path, corpus.payload)
    before, version = core_snapshot(corpus.settings.db_path)
    for _ in range(3):
        result = ingest_paper(corpus.settings.db_path, {"paper_id": "W123", "keynote": "New reading note"})
        assert result["cores"] == 1 and not result["changed"]
    assert core_snapshot(corpus.settings.db_path) == (before, version)
    PaperGraphRepository(corpus.settings.db_path).delete_paper("W123")
    assert not core_snapshot(corpus.settings.db_path)[0]


def test_malformed_structured_update_does_not_delete_previously_verified_nodes(corpus):
    ingest_paper(corpus.settings.db_path, corpus.payload)
    before = core_snapshot(corpus.settings.db_path)
    malformed = copy.deepcopy(corpus.payload)
    malformed["ideation_resource"]["core_contributions"] = [None, "malformed"]
    result = ingest_paper(corpus.settings.db_path, malformed)
    assert result["pending_reasons"] and not result["changed"]
    assert core_snapshot(corpus.settings.db_path) == before


def test_diskcache_import_actual_id_and_queue_completion(corpus, tmp_path):
    from diskcache import Cache
    cache = tmp_path / "survey"
    parsed = cache / "parsed_papers" / "W123" / "auto"
    parsed.mkdir(parents=True)
    (parsed / "W123.md").write_text(corpus.source.read_text())
    with Cache(str(cache / "paper_keynotes")) as notes:
        notes["id"] = {"paper_id": "W123", "keynote": "Unstructured reading note"}
    (cache / "constructed_nodes").mkdir()
    (cache / "constructed_nodes" / "bad.json").write_text('{"bad":"entry"}')
    result = import_survey_cache(corpus.settings.db_path, cache)
    assert result["papers"] == result["queued"] == 1 and len(result["errors"]) == 1
    assert result["cores"] == result["components"] == 0
    pending = PaperGraphRepository(corpus.settings.db_path).pending()[0]
    assert pending["input"]["paper_title"] == "Example paper"
    completed = {**corpus.payload, "source_documents": pending["input"]["source_documents"]}
    assert not ingest_paper(corpus.settings.db_path, completed)["pending_reasons"]
    assert not PaperGraphRepository(corpus.settings.db_path).pending()


def test_index_updates_reuses_and_removes_exact_active_membership(corpus):
    ingest_paper(corpus.settings.db_path, corpus.payload)
    assert build(corpus)["embedded"] == 1
    assert build(corpus)["reused"] == 1
    core = corpus.payload["ideation_resource"]["core_contributions"][0]
    core["components"][0]["summary"] = "Changed measurement summary"
    ingest_paper(corpus.settings.db_path, corpus.payload)
    assert build(corpus)["embedded"] == 1
    assert len(corpus.encoder.calls) == 2
    PaperGraphRepository(corpus.settings.db_path).delete_paper("W123")
    stats = build(corpus)
    assert stats["removed"] == 1 and stats["vector_store_size"] == 0
    assert read_artifacts(corpus.settings.index_dir)[0].ntotal == 0
    assert not load_store(corpus).search_by_vector([1, 0, 0])


def test_model_revision_rebuilds_even_at_same_dimension(corpus):
    ingest_paper(corpus.settings.db_path, corpus.payload)
    build(corpus)
    old = model_identity(corpus.settings.model_path)
    (corpus.settings.model_path / "pytorch_model.bin").write_bytes(b"changed-model-same-dimension")
    assert model_identity(corpus.settings.model_path)["revision"] != old["revision"]
    with pytest.raises(ValueError, match="embedding model"):
        load_store(corpus)
    assert build(corpus)["embedded"] == 1


@pytest.mark.parametrize("failure", ["zero", "nan", "shape"])
def test_invalid_embeddings_leave_current_generation_untouched(corpus, failure):
    ingest_paper(corpus.settings.db_path, corpus.payload)
    build(corpus)
    previous = (corpus.settings.index_dir / "CURRENT.json").read_bytes()
    def bad(texts, **kwargs):
        return np.array([[0, 0, 0]] if failure == "zero" else [[np.nan, 0, 0]] if failure == "nan" else [1, 2])
    corpus.encoder.encode = bad
    with pytest.raises(ValueError, match="Embedding"):
        build(corpus, rebuild=True)
    assert (corpus.settings.index_dir / "CURRENT.json").read_bytes() == previous


def test_changed_graph_during_embedding_and_publication_failure_are_atomic(corpus, monkeypatch):
    ingest_paper(corpus.settings.db_path, corpus.payload)
    build(corpus)
    pointer = corpus.settings.index_dir / "CURRENT.json"
    previous = pointer.read_bytes()
    original = corpus.encoder.encode
    def change_graph(texts, **kwargs):
        PaperGraphRepository(corpus.settings.db_path).delete_paper("W123")
        return original(texts, **kwargs)
    corpus.encoder.encode = change_graph
    with pytest.raises(RuntimeError, match="changed during"):
        build(corpus, rebuild=True)
    assert pointer.read_bytes() == previous
    ingest_paper(corpus.settings.db_path, corpus.payload)
    corpus.encoder.encode = original
    from src.paper_graph import artifacts
    replace = artifacts.os.replace
    def fail_pointer(source, destination):
        if Path(destination).name == "CURRENT.json":
            raise OSError("simulated publication failure")
        return replace(source, destination)
    monkeypatch.setattr(artifacts.os, "replace", fail_pointer)
    with pytest.raises(OSError, match="publication"):
        build(corpus)
    assert pointer.read_bytes() == previous
    assert read_artifacts(corpus.settings.index_dir)[0].ntotal == 1


@pytest.mark.parametrize("corruption", ["count", "ids", "checksum", "duplicate", "dimension", "manifest"])
def test_corrupt_artifacts_are_rejected(corpus, corruption):
    ingest_paper(corpus.settings.db_path, corpus.payload)
    build(corpus)
    directory = index_generation(corpus.settings.index_dir)
    manifest = json.loads((directory / "manifest.json").read_text())
    meta = json.loads((directory / "meta.json").read_text())
    if corruption == "checksum":
        (directory / "meta.json").write_text("{}")
    elif corruption in {"count", "ids", "duplicate"}:
        if corruption == "count":
            meta["meta"] = {}
        elif corruption == "ids":
            meta["meta"]["9"] = meta["meta"].pop("0")
        else:
            meta["meta"]["0"]["id"] = ""
        (directory / "meta.json").write_text(json.dumps(meta))
        manifest["artifacts"]["meta.json"] = file_hash(directory / "meta.json")
    elif corruption == "dimension":
        manifest["dimension"] += 1
    else:
        del manifest["model"]
    (directory / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError):
        read_artifacts(corpus.settings.index_dir)


def test_provider_disabled_reload_failed_reload_and_current_sources(corpus):
    from src.agents.idea_agent.utils.papers.paper_graph_vector_store import PaperGraphComponentVectorStore
    store = PaperGraphComponentVectorStore(config={"paper_graph": vars(corpus.settings)}, disabled_error="initially missing")
    with pytest.raises(RuntimeError, match="initially"):
        store.search("query")
    ingest_paper(corpus.settings.db_path, corpus.payload)
    build(corpus)
    store.reload()
    assert store._disabled_error is None
    hit = store.search_by_vector([1, 0, 0])[0]
    assert hit["core_node"]["evidence_records"][0]["locator"]["path"] == str(corpus.source)
    with pytest.raises(ValueError, match="dimension"):
        store.search_by_vector([1, 0])
    with pytest.raises(ValueError, match="non-finite"):
        store.search_by_vector([np.nan, 0, 0])
    previous = store._index
    pointer = corpus.settings.index_dir / "CURRENT.json"
    original = pointer.read_text()
    pointer.write_text('{"generation":"missing"}')
    with pytest.raises(FileNotFoundError):
        store.reload()
    assert store._index is previous and store._disabled_error is None
    pointer.write_text(original)
    corpus.source.write_text(corpus.source.read_text() + "\nChanged full text.\n")
    with pytest.raises(ValueError, match="source changed"):
        store.search_by_vector([1, 0, 0])
    with pytest.raises(ValueError, match="checksum"):
        build(corpus)
    assert not check_paper_graph(corpus.settings)["ok"]


def test_graph_change_invalidates_loaded_provider(corpus):
    ingest_paper(corpus.settings.db_path, corpus.payload)
    build(corpus)
    store = load_store(corpus)
    PaperGraphRepository(corpus.settings.db_path).delete_paper("W123")
    with pytest.raises(ValueError, match="changed after"):
        store.search_by_vector([1, 0, 0])


def test_many_components_from_one_core_do_not_hide_other_cores(corpus):
    core = corpus.payload["ideation_resource"]["core_contributions"][0]
    component = core["components"][0]
    core["components"] = [{**component, "id": f"part-{i}", "name": f"Part {i}", "summary": "dominant component"} for i in range(80)]
    second = copy.deepcopy(core)
    second.update(id="second", name="Second relation", components=[{**component, "summary": "lower score"}])
    corpus.payload["ideation_resource"]["core_contributions"].append(second)
    ingest_paper(corpus.settings.db_path, corpus.payload)
    build(corpus)
    results = load_store(corpus).search_by_vector([1, 0, .1], top_k=2)
    assert len(results) == 2


def test_health_checks_readiness_and_does_not_create_missing_database(corpus):
    assert not check_paper_graph(corpus.settings)["ok"]
    assert not corpus.settings.db_path.exists()
    ingest_paper(corpus.settings.db_path, corpus.payload)
    build(corpus)
    result = check_paper_graph(corpus.settings)
    assert result["ok"], result
    assert result["node_counts"] == {"Paper": 1, "Core": 1, "Component": 1}
    assert not result["cross_domain_corpus"]
    conn = sqlite3.connect(corpus.settings.db_path)
    conn.execute("DELETE FROM edges")
    conn.commit()
    conn.close()
    assert not check_paper_graph(corpus.settings)["ok"]


def test_settings_detached_configs_and_local_survey_hook(corpus):
    config = OmegaConf.create({"paper_graph": {k: str(v) if isinstance(v, Path) else v for k, v in vars(corpus.settings).items()},
                               "BasicInfo": {"cache_path": str(corpus.source.parent)}})
    assert PaperGraphSettings.from_config(config) == corpus.settings
    assert PaperGraphSettings.from_config(SimpleNamespace(paper_graph=corpus.settings)) == corpus.settings
    manager = SimpleNamespace(get_discovered_paper=lambda _: {"title": "Example paper", "verified_reading_mode": "fulltext",
        "verified_source_path": str(corpus.source), "verified_source_sha256": file_hash(corpus.source)})
    payload = copy.deepcopy(corpus.payload)
    del payload["source_documents"]
    assert not ingest_survey_paper(config, manager, "W123", payload)["pending_reasons"]
    assert not ingest_survey_paper({}, manager, "W123", payload)


def test_partial_publication_and_ungrounded_legacy_graph_rejected(corpus):
    ingest_paper(corpus.settings.db_path, corpus.payload)
    with pytest.raises(ValueError, match="Partial"):
        build(corpus, limit=1)
    conn = sqlite3.connect(corpus.settings.db_path)
    conn.execute("DELETE FROM nodes WHERE node_type='Paper'")
    conn.commit()
    conn.close()
    with pytest.raises(ValueError):
        build(corpus)


def test_graph_evidence_catalog_keeps_each_verified_span_for_claim_audits(corpus):
    from src.agents.idea_agent.utils.workflow.claim_evidence import evidence_catalog, audit_claims
    ingest_paper(corpus.settings.db_path, corpus.payload)
    nodes, _ = core_snapshot(corpus.settings.db_path)
    catalog = evidence_catalog(nodes)
    records = [*nodes[0]["evidence_records"], *nodes[0]["components"][0]["evidence_records"]]
    assert len(catalog["local-paper"]["verified_quotes"]) == 2
    claim = {"claim_id": "c1", "kind": "literature_fact", "text": records[0]["quote"],
             "support_refs": [records[0]["evidence_id"]]}
    audits, _ = audit_claims([claim], records, catalog)
    assert audits[0]["sources"][0]["quote_matches"] and audits[0]["sources"][0]["readable"]
    forged = {**records[0], "quote": "\n\n".join(catalog["local-paper"]["verified_quotes"])}
    audits, _ = audit_claims([claim], [forged], catalog)
    assert not audits[0]["sources"][0]["quote_matches"]


def test_cli_ingest_queue_roundtrip_build_check_and_delete(corpus, tmp_path, monkeypatch, capsys):
    from src import config as config_module
    from src.cli import main
    import sentence_transformers
    monkeypatch.setattr(config_module, "_config", config_module._config)
    monkeypatch.setattr(sentence_transformers, "SentenceTransformer", lambda *a, **k: corpus.encoder)
    config = tmp_path / "config.yaml"
    config.write_text(OmegaConf.to_yaml(OmegaConf.create({"paper_graph": {
        k: str(v) if isinstance(v, Path) else v for k, v in vars(corpus.settings).items()}})))
    input_path = tmp_path / "papers.json"
    input_path.write_text(json.dumps({"paper_id": "W123"}))
    def run(*arguments):
        result = main(["paper-graph", *arguments, "--config", str(config)])
        output = json.loads(capsys.readouterr().out)
        return result, output
    assert run("ingest", "--input", str(input_path))[0] == 0
    queue = tmp_path / "queue.json"
    assert run("queue", "--output", str(queue))[0] == 0
    envelope = json.loads(queue.read_text())
    envelope["pending"][0]["input"] = corpus.payload
    queue.write_text(json.dumps(envelope))
    assert run("ingest", "--input", str(queue))[0] == 0
    assert not run("queue")[1]["pending"]
    assert run("build")[0] == 0
    assert run("check")[0] == 0
    assert run("delete", "--paper-id", "W123", "--build-index")[0] == 0
    assert run("check")[0] == 1


def test_doctor_uses_canonical_model_graph_and_index_without_embedding_load(corpus, monkeypatch, capsys):
    from src import cli
    from src import config as config_module
    from src.paper_graph import health
    from argparse import Namespace
    import sentence_transformers
    monkeypatch.setattr(config_module, "_config", config_module._config)
    config = config_module.load_config(str(config_module.DEFAULT_CONFIG_PATH))
    config.paper_graph = {k: str(v) if isinstance(v, Path) else v for k, v in vars(corpus.settings).items()}
    monkeypatch.setattr(config_module, "load_config", lambda *a, **k: config)
    observed = []
    original = health.check_paper_graph
    def record(settings):
        observed.append(settings)
        return original(settings)
    monkeypatch.setattr(health, "check_paper_graph", record)
    def forbidden(*a, **k):
        raise AssertionError("doctor initialized an embedding model")
    monkeypatch.setattr(sentence_transformers, "SentenceTransformer", forbidden)
    assert cli._doctor_command(Namespace(config=str(config_module.DEFAULT_CONFIG_PATH))) == 1
    assert observed == [corpus.settings]
    assert "paper_graph.component_index" in capsys.readouterr().out
