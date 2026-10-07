from copy import deepcopy
from types import SimpleNamespace
import hashlib
import json

import pytest

from src.agents.experiment_design_agent.survey_paper_pool import (
    load_survey_papers, select_survey_papers, resolve_survey_source,
)
from src.agents.experiment_design_agent.survey_evidence import SurveyEvidenceAdapter, SurveyEvidenceCollector
from src.agents.experiment_design_agent.definition_evidence import bounded_formal_evidence, bounded_prompt_evidence
from src.agents.experiment_design_agent.variable_claim_extractor import build_variable_claim_extractor_prompt
from src.pipeline.survey_retrieval_export import publish_survey_retrieval


def paper(identifier, score, **fields):
    return {"paper_id": identifier, "title": f"Original paper {identifier}",
            "abstract": "A physical definition of computational operation speed.",
            "relevance_score": score, **fields}


def test_pool_uses_scores_and_caps_primary_plus_graph_at_32():
    seeds = [paper(f"W{100 + index}", 100 - index) for index in range(40)]
    expansions = [paper(f"W{200 + index}", 90 - index, source_kind="citation_graph_expansion",
                        parent_paper_ids=["W100"]) for index in range(20)]
    inputs = {"papers": seeds + expansions + [paper("W999", 999, source_kind="citation_graph_expansion",
                                                   parent_paper_ids=["W404"])]}
    original = deepcopy(inputs)
    pool = select_survey_papers(inputs, max_papers=100)
    assert pool["paper_count"] == 32
    assert pool["primary_paper_count"] == 20
    assert pool["expansion_paper_count"] == 12
    assert pool["papers"][0]["canonical_paper_id"] == "W100"
    assert "W999" not in {item["canonical_paper_id"] for item in pool["papers"]}
    assert inputs == original


def test_collector_never_calls_independent_search_or_rescreening():
    class Forbidden:
        def search(self, *_args, **_kwargs):
            pytest.fail("Independent retrieval is cancelled")
        def screen(self, *_args, **_kwargs):
            pytest.fail("Survey scores are accepted directly")
    collector = SurveyEvidenceCollector(openalex_client=Forbidden(), semantic_scholar_client=Forbidden(),
                                        paper_screener=Forbidden())
    collected = collector.collect({"queries": [{"query": "unrelated biology"}]},
                                  survey_artifacts={"papers": [paper("W1", 5)]})
    assert collected["provider_runs"] == []
    assert len(collected["papers"]) == 1
    assert collected["collection_policy"] == "survey_original_papers_only"


def test_manifest_reads_original_papers_and_never_review(tmp_path):
    source = tmp_path / "survey_retrieval_manifest.json"
    source.write_text(json.dumps({"papers": [paper("W1", 5)]}), encoding="utf-8")
    manifest = tmp_path / "survey_manifest.json"
    manifest.write_text(json.dumps({"artifacts": {"retrieval_papers": {"path": source.name}}}), encoding="utf-8")
    (tmp_path / "survey.md").write_text("UNRELATED GENERATED TEXT", encoding="utf-8")
    assert load_survey_papers(manifest)["papers"][0]["paper_id"] == "W1"
    with pytest.raises(ValueError, match="not the generated review"):
        load_survey_papers(tmp_path / "survey.md")


def test_empty_pool_does_not_trigger_search():
    collected = SurveyEvidenceCollector().collect({}, survey_artifacts={"papers": []})
    assert collected["papers"] == []
    assert collected["provider_runs"] == []


def test_graph_selection_requires_relevant_one_hop_papers():
    pool = select_survey_papers({"papers": [paper("W1", 5),
        paper("W2", 2, source_kind="citation_graph_expansion", parent_paper_ids=["W1"]),
        paper("W3", 5, source_kind="citation_graph_expansion", parent_paper_ids=["W1"], lineage_depth=2),
        paper("W4", 4, source_kind="citation_graph_expansion", parent_paper_ids=["W1"], lineage_depth=1)]})
    assert [item["canonical_paper_id"] for item in pool["papers"]] == ["W1", "W4"]


def test_legacy_bound_attempt_uses_original_cache_not_generated_review(tmp_path):
    import diskcache
    (tmp_path / "src").mkdir()
    run = tmp_path / "workspace" / "science-runs" / "run-1"
    survey = run / "survey" / "attempt-001"
    survey.mkdir(parents=True)
    (survey / "survey_manifest.json").write_text('{}', encoding="utf-8")
    (survey / "survey.md").write_text('GENERATED REVIEW MUST NOT BE READ', encoding="utf-8")
    (survey / "sh_graph_provenance.json").write_text(json.dumps({"paper_annotations": {
        "W1": [{"association_stage": "SEED_SELECTION", "lineage_depth": 0, "semantic_relevance_score": 5}],
        "W2": [{"association_stage": "GRAPH_EXPANSION", "lineage_depth": 1,
                "parent_paper_ids": ["W1"], "semantic_relevance_score": 4}]}}), encoding="utf-8")
    with diskcache.Cache(str(tmp_path / "database" / "paper_abstracts")) as cache:
        cache[hashlib.md5(b"W1").hexdigest()] = {"title": "Original title", "abstract": "ORIGINAL ABSTRACT"}
    source = resolve_survey_source(run / "idea" / "attempt-001" / "idea_result.json",
        {"manifest_path": "/unavailable/old/path/survey/attempt-001/survey_manifest.json"})
    assert source["papers"][0]["abstract"] == "ORIGINAL ABSTRACT"
    assert source["warnings"]
    assert select_survey_papers(source)["paper_count"] == 2


def test_missing_bound_attempt_never_substitutes_another_survey(tmp_path):
    other = tmp_path / "survey" / "attempt-002"
    other.mkdir(parents=True)
    (other / "survey_manifest.json").write_text('{}', encoding="utf-8")
    (other / "survey_retrieval_manifest.json").write_text(json.dumps({"papers": [paper("W1", 5)]}), encoding="utf-8")
    source = resolve_survey_source(tmp_path / "idea" / "idea_result.json",
        {"manifest_path": "/old/path/survey/attempt-001/survey_manifest.json"})
    assert source["papers"] == []
    assert "survey_bound_source_unavailable" in source["warnings"][0]


def test_cards_only_feed_variable_and_definition_reference():
    bundle = {"usage": "variables_and_definitions", "evidence_role": "reference",
              "evidence_cards": [{"card_id": "EC1", "evidence_excerpt": "ORIGINAL PAPER QUOTE"}]}
    variable_prompt = build_variable_claim_extractor_prompt({}, {"schema_version": "reasoning_context_v1"}, bundle)
    assert "ORIGINAL PAPER QUOTE" in variable_prompt
    assert bounded_formal_evidence(bundle, {})["evidence_cards"] == []
    assert bounded_prompt_evidence({"evidence_bundle": bundle}, {})["evidence_bundle"] == {}
    assert bundle["evidence_cards"]


def test_survey_export_preserves_original_text_and_scores_without_discovery(tmp_path):
    cache = {hashlib.md5(b"W2").hexdigest(): {"title": "Graph paper", "abstract": "Original graph abstract"}}
    manager = SimpleNamespace(paper_abstract_cache=cache, _resolve_paper_reference_id=lambda record: record["paper_id"])
    collector = SimpleNamespace(
        data_manager=manager, subhypothesis_retrieval_artifact={"candidate_papers": [paper("W1", 5)]},
        sh_graph_provenance_artifact={"paper_annotations": {"W2": [{"root_seed_paper_ids": ["W1"]}]}},
        fulltext_budget_plan={"selected_for_fulltext": [{"paper_id": "W2", "max_llm_relevance_score": 4}]},
    )
    config = SimpleNamespace(BasicInfo=SimpleNamespace(base_dir=str(tmp_path), cache_path=str(tmp_path), topic="physical computing"))
    path = publish_survey_retrieval(config, collector, ["W1"], ["W2"])
    exported = json.loads(path.read_text(encoding="utf-8"))
    assert exported["papers"][0]["abstract"] == paper("W1", 5)["abstract"]
    expanded = exported["papers"][1]
    assert expanded["abstract"] == "Original graph abstract"
    assert expanded["source_kind"] == "citation_graph_expansion"
    assert expanded["relevance_score"] == 4
    assert select_survey_papers(exported)["paper_count"] == 2


def test_adapter_extracts_cards_from_original_papers_and_marks_reference_usage():
    def extract(prompt, **_kwargs):
        payload = json.loads(prompt.split("INPUT_JSON:\n", 1)[1])
        return {"cards": [{"claim_slot": "research_object_measurability",
                           "statement": "Computational speed is an operation rate.",
                           "design_implication": "Use an operation rate variable.",
                           "source_id": payload["canonical_paper_id"],
                           "source_location": payload["fixed_source_location"],
                           "evidence_level": payload["fixed_evidence_level"],
                           "evidence_excerpt": "A physical definition of computational operation speed.",
                           "limitations": [], "does_not_establish": []}]}
    adapter = SurveyEvidenceAdapter(collector=SurveyEvidenceCollector(), card_llm_call=extract)
    result = adapter.collect_and_extract(brief_id="B1", evidence_plan={},
                                         survey_artifacts={"papers": [paper("W1", 5)]})
    assert result["evidence_bundle"]["usage"] == "variables_and_definitions"
    assert len(result["evidence_bundle"]["evidence_cards"]) == 1
    assert result["evidence_bundle"]["evidence_cards"][0]["evidence_role"] == "reference"
