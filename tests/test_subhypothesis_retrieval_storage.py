from copy import deepcopy
import json

import pytest

from scripts.compact_subhypothesis_retrieval import compact_file
from src.pipeline.subhypothesis_retrieval_storage import (
    STORAGE_SCHEMA_VERSION,
    expand_subhypothesis_retrieval,
    load_subhypothesis_retrieval,
    serialize_subhypothesis_retrieval,
)


def _artifact():
    span = {"source": "abstract", "text": "Measured response in the target system. " * 30}
    limits = ["This observation does not establish causality. " * 20]
    assessment = {"sub_hypothesis_id": "SH1", "semantic_relevance_score": 4,
                  "evidence_spans": [span], "claim_limits": limits}
    paper = {"paperId": "W1", "title": "可追溯证据", "abstract": span["text"],
             "sh_semantic_assessments": [assessment],
             "sh_matches": [{"sub_hypothesis_id": "SH1", "semantic_assessment": assessment,
                 "slot_assessments": [{"slot_name": slot, "llm_evidence_spans": [span],
                     "llm_claim_limits": limits} for slot in ("observation", "mechanism")]}]}
    return {"schema_version": "subhypothesis_feedback_retrieval_execution_v1",
            "candidate_papers": [paper], "scientific_candidate_papers": [deepcopy(paper)],
            "seed_selection": {"selected_papers": [paper], "evidence_seed_papers": [paper],
                "exploration_seed_papers": [], "context_seed_papers": [],
                "holdout_candidates": [], "rejected_papers": [],
                "minimum_seed_unmet_by_sh": {"SH1": 1}},
            "assessment_alignment_audit": [{"parsed_response": {"papers": [deepcopy(paper)]}}],
            "candidate_discovery": {"records": [], "ledger_fingerprint": "unchanged"}}


def test_storage_deduplicates_papers_semantics_and_evidence_without_changing_audits():
    artifact = _artifact()
    before = deepcopy(artifact)
    stored = serialize_subhypothesis_retrieval(artifact)
    assert artifact == before
    assert stored["storage_schema_version"] == STORAGE_SCHEMA_VERSION
    assert list(stored["paper_records"]) == ["W1"]
    assert len(stored["semantic_assessment_records"]) == 1
    assert len(stored["evidence_records"]) == 2
    assert stored["candidate_paper_ids"] == stored["scientific_candidate_paper_ids"] == ["W1"]
    assert stored["seed_selection"]["selected_paper_ids"] == ["W1"]
    assert "candidate_papers" not in stored
    assert stored["assessment_alignment_audit"] == artifact["assessment_alignment_audit"]
    assert stored["candidate_discovery"] == artifact["candidate_discovery"]
    encoded = json.dumps(stored, ensure_ascii=False, indent=2)
    assert len(encoded.encode()) < len(json.dumps(artifact, ensure_ascii=False, indent=2).encode()) * .7
    restored = expand_subhypothesis_retrieval(json.loads(encoded))
    assert restored == artifact
    paper = restored["candidate_papers"][0]
    assert restored["seed_selection"]["selected_papers"][0] is paper
    semantic = paper["sh_semantic_assessments"][0]
    assert semantic is paper["sh_matches"][0]["semantic_assessment"]
    assert semantic["evidence_spans"][0] is paper["sh_matches"][0]["slot_assessments"][0]["llm_evidence_spans"][0]
    assert serialize_subhypothesis_retrieval(stored) == stored
    assert serialize_subhypothesis_retrieval(restored) == stored


def test_storage_preserves_order_duplicates_missing_ids_and_different_paper_snapshots():
    artifact = _artifact()
    raw_snapshot = {"paperId": "W1", "abstract": "Earlier discovery snapshot"}
    anonymous = {"title": "Source without a provider identifier"}
    artifact["scientific_candidate_papers"] = [raw_snapshot, anonymous, raw_snapshot]
    artifact["seed_selection"]["holdout_candidates"] = [{"paperId": "W2", "title": "Holdout only"}]
    stored = serialize_subhypothesis_retrieval(artifact)
    assert len(stored["paper_records"]) == 4
    refs = stored["scientific_candidate_paper_ids"]
    assert refs[0] == refs[2] != stored["candidate_paper_ids"][0]
    assert stored["seed_selection"]["holdout_candidate_ids"] == ["W2"]
    assert expand_subhypothesis_retrieval(json.loads(json.dumps(stored))) == artifact


@pytest.mark.parametrize("artifact", [{}, {"coverage_final": {"complete": True}},
    {"candidate_papers": [], "seed_selection": {"selected_papers": [], "rejected_papers": None}}])
def test_storage_accepts_legacy_minimal_and_empty_artifacts(artifact):
    assert expand_subhypothesis_retrieval(artifact) == artifact
    assert expand_subhypothesis_retrieval(serialize_subhypothesis_retrieval(artifact)) == artifact


@pytest.mark.parametrize("table", ["paper_records", "semantic_assessment_records", "evidence_records"])
def test_reader_rejects_missing_references_instead_of_dropping_data(table):
    stored = serialize_subhypothesis_retrieval(_artifact())
    stored[table].clear()
    with pytest.raises(ValueError, match="Missing retrieval storage reference"):
        expand_subhypothesis_retrieval(stored)


def test_reader_rejects_unknown_versions_and_reference_cycles():
    stored = serialize_subhypothesis_retrieval(_artifact())
    stored["storage_schema_version"] = "future_version"
    with pytest.raises(ValueError, match="Unsupported retrieval storage schema"):
        expand_subhypothesis_retrieval(stored)
    stored["storage_schema_version"] = STORAGE_SCHEMA_VERSION
    identifier = next(iter(stored["semantic_assessment_records"]))
    stored["semantic_assessment_records"][identifier]["semantic_assessment_id"] = identifier
    with pytest.raises(ValueError, match="Cyclic retrieval storage reference"):
        expand_subhypothesis_retrieval(stored)


def test_migration_preserves_all_values_and_indentation_and_is_idempotent(tmp_path):
    path = tmp_path / "subhypothesis_retrieval.json"
    artifact = _artifact()
    path.write_text(json.dumps(artifact, ensure_ascii=False, indent=2), encoding="utf-8")
    result = compact_file(path)
    assert result["changed"] is result["roundtrip_verified"] is True
    assert result["after_bytes"] < result["before_bytes"]
    text = path.read_text(encoding="utf-8")
    assert text == json.dumps(json.loads(text), ensure_ascii=False, indent=2)
    assert "可追溯证据" in text
    assert load_subhypothesis_retrieval(path) == artifact
    migrated_stat = path.stat()
    assert compact_file(path)["changed"] is False
    assert path.stat().st_mtime_ns == migrated_stat.st_mtime_ns
    assert list(tmp_path.iterdir()) == [path]


def test_failed_migration_keeps_original_file(tmp_path, monkeypatch):
    import scripts.compact_subhypothesis_retrieval as migration

    path = tmp_path / "subhypothesis_retrieval.json"
    original = json.dumps(_artifact(), ensure_ascii=False, indent=2)
    path.write_text(original, encoding="utf-8")
    monkeypatch.setattr(migration.os, "replace", lambda *_args: (_ for _ in ()).throw(OSError("replace failed")))
    with pytest.raises(OSError, match="replace failed"):
        compact_file(path)
    assert path.read_text(encoding="utf-8") == original
    assert list(tmp_path.iterdir()) == [path]
