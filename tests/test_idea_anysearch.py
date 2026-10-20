import json
import logging
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from omegaconf import OmegaConf

from src.agents.idea_agent.agent.artifacts import artifact_append, artifact_get, artifact_init, artifact_set
from src.agents.idea_agent.utils.papers import paper_repository as repository_module
from src.agents.idea_agent.utils.papers.external_search import IdeaExternalSearch, build_external_queries, flatten_references
from src.agents.idea_agent.utils.papers.paper_repository import PaperRepository
from src.agents.idea_agent.utils.prompting.prompt_views import format_paper_capsules_prompt_view, format_paper_context_prompt_view
from src.agents.idea_agent.utils.workflow import ligagent_flow, ligagent_handlers as handlers
from src.agents.idea_agent.utils.workflow.idea_helpers import build_direction_result_document
from src.agents.idea_agent.utils.workflow.ligagent_utils import LigRuntime, LigSession, collect_paper_context_entries
from src.agents.idea_agent.utils.workflow.result_persistence import compact_result_payload
from src.agents.idea_agent.utils.workflow.stage_contract import StageContext
from src.pipeline.anysearch import SearchResult, normalize_anysearch_paper


def _paper(index=1, **kwargs):
    return normalize_anysearch_paper({"title": f"Receptor mechanism study {index}", "doi": f"10.1000/{index}", "abstract": "Actual abstract of ligand exposure and receptor modulation. " * 8, **kwargs})


def _reference(paper):
    return {"paper_id": paper["paperId"], "node_id": paper["paperId"], "title": paper["title"], "keynote": paper["abstract"],
            "doi": paper["doi"], "source": "anysearch", "reading_status": "completed", "reading_mode": "abstract",
            "source_path": "/reading/source.md", "discovery_provenance": paper["discovery_provenance"]}


def _agent(tmp_path, **settings):
    artifact = artifact_init()
    artifact_set(artifact, "topic", ["receptor"])
    artifact_set(artifact, "task_contract", {"original_request": "Identify the receptor mechanism"})
    repository = SimpleNamespace(read_discovered_paper=Mock(side_effect=lambda paper, **_kwargs: _reference(paper)),
                                 retrieve_keynotes_by_paper_ids=Mock(return_value=[]))
    config = OmegaConf.create({"run": {"input": "Identify the receptor mechanism"}, "agent": {
        "paper_keynote_keep_top_k": 1, "keynote_json_repair_attempts": 0,
        "anysearch": {"enabled": True, "initial_queries": 1, "candidate_queries": 1, "initial_read_limit": 2,
                      "candidate_read_limit": 2, "max_total_papers": 3, "checkpoint_attempts": 2,
                      "max_rounds": 1, **settings}}})
    agent = SimpleNamespace(artifact=artifact, run_dir=tmp_path, paper_repository=repository, config=config,
                            logger=logging.getLogger(__name__), model="qwen3.8-flash", project_config={"llm": {"provider": "qwen"}})
    agent.session = LigSession(artifact)
    agent.runtime = LigRuntime(agent)
    return agent


def _context(agent):
    return StageContext(agent=agent, artifact=agent.artifact, workflow_name="ligagent.knowledge_acquisition",
                        runtime=agent.runtime, session=agent.session, logger=agent.logger,
                        state={"topic": "receptor", "rag_query": "receptor", "mode": "standard", "citation_references": []})


def _apply(agent, result):
    for name, value in result.artifact_patch.replace.items():
        artifact_set(agent.artifact, name, value)
    for name, values in result.artifact_patch.append.items():
        artifact_append(agent.artifact, name, values)


def test_queries_use_scientific_allowlist_and_never_serialize_rubric():
    task = {"original_request": "Study receptor ligand modulation", "rubric": "PRIVATE_RUBRIC", "evaluation": {"instructions": "PRIVATE_EVAL"}}
    candidates = [{"title": "Membrane pathway", "hypothesis": "lipid displacement", "mechanism_or_relation": "bilayer perturbation",
                   "evidence_gaps": ["residue contact measurements"], "open_questions": ["channel kinetics"],
                   "rubric": "PRIVATE_RUBRIC", "evaluation": "PRIVATE_EVAL", "score": "PRIVATE_SCORE"},
                  {"title": "Rejected path", "maturity_status": "rejected"},
                  {"title": "Duplicate path", "independence_status": "collapsed_duplicate"}]
    initial = build_external_queries(task, topic="receptor", phase="initial")
    candidate = build_external_queries(task, topic="receptor", phase="candidate", candidates=candidates)
    assert len(initial) == 2 and len(candidate) == 1
    assert all(term in candidate[0] for term in ["lipid displacement", "bilayer perturbation", "residue contact", "channel kinetics"])
    assert "PRIVATE" not in str(initial + candidate)
    assert "Rejected" not in str(candidate) and "Duplicate" not in str(candidate)


def test_idea_client_uses_official_default_and_configured_tag(monkeypatch, tmp_path):
    monkeypatch.delenv("ANYSEARCH_BASE_URL", raising=False)
    search = IdeaExternalSearch(_agent(tmp_path, tag="academic.biomedical"))
    assert search.client.base_url == "https://api.anysearch.com"
    assert search.client.tag == "academic.biomedical"


def test_reading_budget_dedup_and_completed_checkpoints_are_reused(tmp_path):
    agent = _agent(tmp_path)
    first = _paper(1)
    duplicate = _paper(99, title="A different title for the same DOI", doi=first["doi"])
    client = SimpleNamespace(search=Mock(return_value=SearchResult([first, duplicate, _paper(2), _paper(3)], "success", 1)))
    search = IdeaExternalSearch(agent, client=client)
    arguments = {"phase": "initial", "task": {"original_request": "receptor"}, "topic": "receptor"}
    result = search.run(**arguments)
    assert len(result["references"]) == 2
    resumed = IdeaExternalSearch(agent, client=client).run(**arguments)
    assert resumed["references"] == result["references"]
    assert client.search.call_count == 1 and agent.paper_repository.read_discovered_paper.call_count == 2
    assert result["references"][0]["retrieval_provenance"][0]["phase"] == "initial"
    saved = json.loads((tmp_path / "external_search" / "initial.json").read_text())
    assert all(read["status"] == "completed" for read in saved["reads"].values())
    candidate = search.run(phase="candidate", task={}, topic="receptor", candidates=[{"title": "Lipid pathway"}])
    assert len(candidate["references"]) == 1
    assert agent.paper_repository.read_discovered_paper.call_count == 3
    assert client.search.call_count == 2


def test_known_survey_papers_are_not_read_again(tmp_path):
    agent = _agent(tmp_path)
    paper = _paper()
    client = SimpleNamespace(search=Mock(return_value=SearchResult([paper], "success")))
    result = IdeaExternalSearch(agent, client=client).run(phase="initial", task={}, topic="receptor",
        known_references=[{"paper_id": "W123", "title": "Different title", "doi": paper["doi"]}])
    assert result["references"] == []
    agent.paper_repository.read_discovered_paper.assert_not_called()


def test_only_failed_paper_is_retried_and_each_attempt_is_checkpointed(tmp_path):
    agent = _agent(tmp_path)
    good, bad = _paper(1), _paper(2)
    read_calls = []

    def read(paper, **_kwargs):
        checkpoint = json.loads((tmp_path / "external_search" / "initial.json").read_text())
        assert checkpoint["reads"][paper["paperId"]]["status"] == "in_progress"
        read_calls.append(paper["paperId"])
        if paper["paperId"] == bad["paperId"]:
            raise ValueError("Temporary paper reading failure")
        return _reference(paper)

    agent.paper_repository.read_discovered_paper = read
    client = SimpleNamespace(search=Mock(return_value=SearchResult([good, bad], "success")))
    for _ in range(4):
        result = IdeaExternalSearch(agent, client=client).run(phase="initial", task={}, topic="receptor")
        assert [ref["paper_id"] for ref in result["references"]] == [good["paperId"]]
    assert read_calls.count(good["paperId"]) == 1 and read_calls.count(bad["paperId"]) == 2
    assert client.search.call_count == 1
    state = json.loads((tmp_path / "external_search" / "initial.json").read_text())
    assert state["reads"][bad["paperId"]]["error_type"] == "ValueError"
    assert state["reads"][bad["paperId"]]["attempts"] == 2


def test_provider_failure_is_retried_locally_with_fixed_query_set_and_cap(tmp_path):
    agent = _agent(tmp_path)
    client = SimpleNamespace(search=Mock(return_value=SearchResult(status="provider_failure", attempts=2)))
    for topic in ["receptor", "changed context", "another context", "last context"]:
        result = IdeaExternalSearch(agent, client=client).run(phase="initial", task={}, topic=topic)
    assert client.search.call_count == 2
    assert {call.args[0] for call in client.search.call_args_list} == {"receptor"}
    assert result["searches"][0]["attempts"] == 2
    assert result["searches"][0]["status"] == "provider_failure"
    agent.paper_repository.read_discovered_paper.assert_not_called()


def test_no_candidates_does_not_freeze_empty_phase_and_disabled_does_nothing(tmp_path):
    agent = _agent(tmp_path)
    client = SimpleNamespace(search=Mock(return_value=SearchResult(status="valid_empty")))
    search = IdeaExternalSearch(agent, client=client)
    assert search.run(phase="candidate", task={}, topic="receptor")["references"] == []
    assert not (tmp_path / "external_search" / "candidate.json").exists()
    search.run(phase="candidate", task={}, topic="receptor", candidates=[{"title": "Lipid pathway"}])
    assert client.search.call_count == 1
    agent.config.agent.anysearch.enabled = "false"
    assert search.run(phase="initial", task={}, topic="receptor") == {"references": [], "searches": []}
    assert not (tmp_path / "external_search" / "initial.json").exists()


def _repository(tmp_path):
    repository = object.__new__(PaperRepository)
    repository.config = OmegaConf.create({"BasicInfo": {"base_dir": str(tmp_path / "frozen_survey"),
        "cache_path": str(tmp_path / "shared_cache"), "sh_graph_provenance_artifact_path": str(tmp_path / "frozen_survey" / "graph.json")}})
    return repository


@pytest.mark.parametrize("fulltext", [True, False])
def test_paper_reader_uses_real_source_and_isolates_reports_from_frozen_survey(monkeypatch, tmp_path, fulltext):
    repository = _repository(tmp_path)
    original = OmegaConf.to_container(repository.config, resolve=False)
    created = []
    paper = _paper()
    text = ("Full text findings. " * 150).strip() if fulltext else paper["abstract"]

    def manager(config):
        created.append(config)
        return SimpleNamespace(register_discovered_papers=Mock(), _resolve_paper_reference_id=lambda paper: paper["paperId"],
            get_paper_raw_markdown=Mock(return_value=text) if fulltext else Mock(side_effect=ValueError("No full text")),
            get_paper_title_abstract=Mock(return_value=(paper["title"], text)))

    monkeypatch.setattr(repository_module, "DataManager", manager)
    work_dir = tmp_path / "idea" / "reading"
    reference = repository.read_discovered_paper(paper, work_dir=work_dir, max_source_chars=1000)
    assert reference["reading_status"] == "completed"
    assert reference["reading_mode"] == ("fulltext_excerpt" if fulltext else "abstract")
    assert Path(reference["source_path"]).read_text() == text
    assert reference["used_chars"] <= 1000 and reference["source_chars"] == len(text)
    assert created[0].BasicInfo.base_dir == str(work_dir.resolve())
    assert created[0].BasicInfo.sh_graph_provenance_artifact_path == str(work_dir.resolve() / "sh_graph_provenance.json")
    assert created[0].BasicInfo.cache_path == original["BasicInfo"]["cache_path"]
    assert OmegaConf.to_container(repository.config, resolve=False) == original
    if not fulltext:
        assert reference["reading_issues"] == [{"step": "fulltext", "error_type": "ValueError"}]


def test_unavailable_snippet_is_not_a_keynote_and_disallowed_abstract_is_not_read(monkeypatch, tmp_path):
    repository = _repository(tmp_path)
    paper = _paper(abstract="", snippet="Discovery snippet. " * 30)
    manager = SimpleNamespace(register_discovered_papers=Mock(), _resolve_paper_reference_id=lambda paper: paper["paperId"],
                              get_paper_raw_markdown=Mock(side_effect=ValueError("No full text")),
                              get_paper_title_abstract=Mock(side_effect=ValueError("No actual abstract")))
    monkeypatch.setattr(repository_module, "DataManager", lambda _config: manager)
    result = repository.read_discovered_paper(paper, work_dir=tmp_path / "reading")
    assert result["reading_status"] == "unavailable" and "keynote" not in result
    assert not list((tmp_path / "reading").glob("*.md"))
    manager.get_paper_title_abstract.reset_mock()
    result = repository.read_discovered_paper(paper, work_dir=tmp_path / "reading", allow_abstract_fallback=False)
    assert result["reading_status"] == "unavailable"
    manager.get_paper_title_abstract.assert_not_called()


def test_initial_hook_feeds_supplement_into_analysis_and_preserves_provenance(monkeypatch, tmp_path):
    agent = _agent(tmp_path)
    references = [_reference(_paper(1)), _reference(_paper(2))]
    search_record = {"provider": "anysearch", "phase": "initial", "query": "receptor", "status": "success"}
    monkeypatch.setattr(handlers, "search_idea_literature", lambda _agent, **_kwargs: {"references": references, "searches": [search_record]})
    calls = []

    def chat(prompt, **_kwargs):
        calls.append(prompt)
        if '"score"' in prompt:
            return '{"score": 80}'
        if "lower-priority" in prompt:
            return '{"summary":"Other receptor mechanism evidence."}'
        return '{"summary":"Observed receptor modulation.","insight":"Ligand exposure matters."}'

    agent.chat = chat
    ctx = _context(agent)
    ranked = handlers.ka_keynote_ranking_stage(agent, ctx)
    _apply(agent, ranked)
    ctx.state.update(ranked.state_patch)
    selected = handlers.ka_reference_selection_stage(agent, ctx)
    _apply(agent, selected)
    curated = selected.state_patch["curated_references"]
    assert len(curated) == 2
    assert curated[0]["reading_mode"] == "abstract"
    assert curated[1]["source_references"][0]["paper_id"] == references[1]["paper_id"]
    assert len(flatten_references([curated])) == 3
    public_refs = artifact_get(agent.artifact, "external_references")
    assert len(public_refs) == 2
    assert public_refs[0]["summary"] == "Observed receptor modulation."
    assert public_refs[0]["source_path"] == "/reading/source.md"
    assert all("keynote" not in ref for ref in public_refs)
    view = format_paper_capsules_prompt_view(curated)
    assert "Observed receptor modulation." in view and "Source scope: abstract" in view
    assert all("Source scope: abstract" in prompt for prompt in calls)
    entries = collect_paper_context_entries(agent.artifact, [curated])
    assert "source_scope=abstract" in format_paper_context_prompt_view(entries)
    assert artifact_get(agent.artifact, "external_searches") == [search_record]


def test_candidate_hook_places_new_reading_in_route_evidence_context(monkeypatch, tmp_path):
    agent = _agent(tmp_path)
    reference = _reference(_paper())
    artifact_set(agent.artifact, "mature_ideas", [{"idea_id": "I1", "title": "Receptor mechanism", "hypothesis": "ligand exposure changes the receptor"}])
    monkeypatch.setattr(handlers, "search_idea_literature", lambda _agent, **_kwargs: {"references": [reference], "searches": []})
    agent.chat = lambda prompt, **_kwargs: ('{"score":80}' if '"score"' in prompt else '{"summary":"Receptor mechanism depends on ligand exposure.","insight":"Measure kinetics."}')
    first = handlers.execute_route_context_preparation_stage(agent, _context(agent))
    assert first.metrics["external_references_added"] == 1
    assert first.artifact_patch.replace["mature_idea_contexts"][0]["evidence_subset"][0]["paper_id"] == reference["paper_id"]
    _apply(agent, first)
    second = handlers.execute_route_context_preparation_stage(agent, _context(agent))
    assert second.metrics["external_references_added"] == 0
    assert not second.artifact_patch.append


def test_scoring_failure_keeps_paper_for_compression_and_source_metadata(monkeypatch, tmp_path):
    agent = _agent(tmp_path)
    agent.chat = Mock(side_effect=ValueError("Invalid score JSON"))
    reference = _reference(_paper())
    scored = handlers._score_keynote_reference(agent, _context(agent), "receptor", "query", reference)
    assert scored["score"] == 0 and scored["scoring_status"] == "fallback"
    assert scored["keynote"] == reference["keynote"]
    agent.chat = lambda *_args, **_kwargs: '{"summary":"Evidence.","insight":"Implication."}'
    compressed = handlers._compress_single_keynote_reference(agent, _context(agent), "receptor", "query", scored)
    assert compressed["scoring_issue"] == "ValueError" and compressed["reading_mode"] == "abstract"


def test_final_and_direction_results_retain_external_sources_after_compaction(monkeypatch, tmp_path):
    agent = _agent(tmp_path)
    references = [{"paper_id": "AS1", "title": "Receptor paper", "source": "anysearch", "reading_mode": "abstract", "source_path": "/reading/source.md"}]
    searches = [{"provider": "anysearch", "phase": "initial", "status": "success"}]
    artifact_set(agent.artifact, "external_references", references)
    artifact_set(agent.artifact, "external_searches", searches)
    candidate = {"title": "Receptor mechanism", "abstract": "Test ligand kinetics.", "method": "Measure kinetics.", "central_hypothesis": "Ligand alters state transitions.", "components": []}
    monkeypatch.setattr(ligagent_flow, "align_public_idea_entry", lambda **kwargs: kwargs["best_entry"])
    monkeypatch.setattr(ligagent_flow, "build_profile_aware_materialization", lambda *_args: {})
    monkeypatch.setattr(ligagent_flow, "generate_idea_introduction", lambda **_kwargs: "Introduction.")
    payload = ligagent_flow.build_idea_result_payload(candidate, [], agent.artifact, lambda *_args: "", agent.model, agent.logger)
    direction = build_direction_result_document("receptor", candidate, agent.artifact, {"status": "verified"})
    for result in [compact_result_payload(payload), compact_result_payload(direction)]:
        assert result["external_references"] == references and result["external_searches"] == searches
