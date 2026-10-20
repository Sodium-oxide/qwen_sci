import logging
from types import SimpleNamespace
from unittest.mock import Mock

import diskcache
import pytest

from src.agents.survey_agent.modules.data_manager import DataManager
from src.agents.survey_agent.modules.adaptive_discovery import run_survey_search
from src.agents.survey_agent.modules.work_analyzer import WorkAnalyzer
from src.agents.survey_agent.modules.work_collector import WorkCollector
from src.pipeline.anysearch import normalize_anysearch_paper


def _paper(**kwargs):
    return normalize_anysearch_paper({"title": "A receptor mechanism study", "abstract": "The authors measure receptor modulation under controlled ligand exposure. " * 6, **kwargs})


def _manager(tmp_path):
    manager = object.__new__(DataManager)
    manager.config = SimpleNamespace(BasicInfo=SimpleNamespace(debug=False), ModuleInfo=SimpleNamespace(WorkCollector=SimpleNamespace()))
    manager.logger = logging.getLogger(__name__)
    manager.cache_path = str(tmp_path)
    manager.paper_abstract_cache = {}
    manager.discovery_metadata_cache = {}
    manager.unpaywall_api = SimpleNamespace(enabled=False, get_oa_candidates=lambda _doi: [])
    manager.openalex_api = Mock()
    manager.semantic_scholar_api = Mock()
    manager.arxiv_api = Mock()
    return manager


def test_discovery_metadata_and_abstract_remain_readable_after_cache_reopen(tmp_path):
    paper = _paper(doi="10.1000/receptor", authors=["One Author"])
    manager = _manager(tmp_path)
    with diskcache.Cache(str(tmp_path / "discovery")) as cache:
        manager.discovery_metadata_cache = cache
        manager.register_discovered_papers([paper])
    resumed = _manager(tmp_path)
    with diskcache.Cache(str(tmp_path / "discovery")) as cache:
        resumed.discovery_metadata_cache = cache
        assert resumed.get_paper_title_abstract(paper["paperId"]) == (paper["title"], paper["abstract"])
        assert resumed.get_paper_title(paper["paperId"]) == paper["title"]
        resumed.openalex_api.get_paper_details.assert_not_called()
        resumed.semantic_scholar_api.get_paper_details.assert_not_called()


def test_synthetic_ids_do_not_fall_through_to_other_metadata_apis(tmp_path):
    manager = _manager(tmp_path)
    paper = _paper(abstract="", snippet="Search text about a receptor. " * 10)
    manager.register_discovered_papers([paper])
    with pytest.raises(ValueError, match="valid abstract"):
        manager.get_paper_title_abstract(paper["paperId"])
    manager.openalex_api.get_paper_details.assert_not_called()
    manager.semantic_scholar_api.get_paper_details.assert_not_called()
    manager.arxiv_api.get_paper_details.assert_not_called()


@pytest.mark.parametrize("openalex_id", ["", "W123"])
def test_bare_discovered_id_uses_cached_fulltext_routes(tmp_path, openalex_id):
    manager = _manager(tmp_path)
    paper = _paper(openalex_id=openalex_id, pdf_url="https://repo.example/receptor.pdf", identifiers={"ArXiv": "2501.12345"})
    manager.register_discovered_papers([paper])
    pid = paper["paperId"]
    assert manager._paper_download_id(paper) == pid
    assert manager._has_pdf_download_candidate(pid)
    info = manager._prepare_download_info(pid)
    assert info[0] == pid
    assert any(candidate["url"] == "https://repo.example/receptor.pdf" for candidate in info[1])
    manager.openalex_api.get_paper_details.assert_not_called()


@pytest.mark.parametrize("enabled", [True, False, "true", "false"])
def test_survey_dispatch_blocks_anysearch_even_with_legacy_config(enabled):
    collector = object.__new__(WorkCollector)
    collector.config = SimpleNamespace(ModuleInfo=SimpleNamespace(WorkCollector=SimpleNamespace(enable_anysearch_discovery=enabled)))
    collector.logger = logging.getLogger(__name__)
    client = SimpleNamespace(search=Mock())
    register = Mock()
    collector.data_manager = SimpleNamespace(anysearch_api=client, register_discovered_papers=register)
    result = collector._execute_query_lane_with_status({"provider": "anysearch", "query": "receptor", "result_limit": 3})
    assert result == ([], False, "disabled")
    assert not collector._discovery_lane_enabled({"provider": "anysearch"})
    assert collector._discovery_lane_enabled({"provider": "openalex"})
    client.search.assert_not_called()
    register.assert_not_called()


@pytest.mark.parametrize("shared_search_enabled", [True, False])
def test_survey_skips_shared_anysearch_search_with_legacy_config(tmp_path, monkeypatch, shared_search_enabled):
    collector = object.__new__(WorkCollector)
    collector.config = SimpleNamespace(
        BasicInfo=SimpleNamespace(base_dir=str(tmp_path)),
        ModuleInfo=SimpleNamespace(WorkCollector=SimpleNamespace(
            enable_anysearch_discovery=True, shared_search_enabled=shared_search_enabled)),
    )
    search_loop = Mock()
    monkeypatch.setattr("src.agents.survey_agent.modules.adaptive_discovery.AdaptiveSearch", search_loop)
    assert run_survey_search(collector, topic="receptor", research_context={}) == {
        "papers": [], "references": [], "searches": [],
    }
    search_loop.assert_not_called()
    plan = {"query_lanes": [{"provider": "openalex", "query": "receptor"}]}
    assert collector._with_anysearch_lanes(plan) == plan
    assert not list(tmp_path.iterdir())


def _collector(tmp_path, papers, *, local, graph_match=False, fulltext=False, fallback=True):
    collector = object.__new__(WorkCollector)
    collector.config = SimpleNamespace(ModuleInfo=SimpleNamespace(
        WorkCollector=SimpleNamespace(enable_anysearch_discovery=True, max_seed_paper_num=4),
        WorkAnalyzer=SimpleNamespace(abstract_when_full_text_fail=fallback)))
    collector.logger = logging.getLogger(__name__)
    collector.expand_in_local_paper_graph = local
    collector.use_ds_when_graph_fail = False
    collector.graph_paper_ids = set()
    collector.ignore_paper = set()
    collector._openalex_id_aliases = {}
    collector.context_seed_paper_ids = set()
    collector.metadata_only_graph_seed_ids = set()
    collector.get_project_research_context = lambda _topic: {"original_topic": "receptor"}
    collector._build_configured_subhypothesis_plan = lambda *_args: ({}, [])
    collector._discover_seed_candidates = lambda *_args: papers
    collector._filter_project_candidates_if_enabled = lambda _topic, records, _context: records
    manager = _manager(tmp_path)
    manager.openalex_api.resolve_work_id.side_effect = lambda paper: paper.get("openalex_id", "")
    manager.download_and_parse_papers = Mock(side_effect=lambda records, limit: [paper["paperId"] for paper in records] if fulltext else [])
    collector.data_manager = manager
    collector.paper_graph_retriever = SimpleNamespace(search_by_paper_title=Mock(return_value=[{}] if graph_match else []))
    return collector


@pytest.mark.parametrize("local", [True, False])
@pytest.mark.parametrize("openalex_id", ["", "W123"])
def test_external_paper_is_read_even_when_absent_from_local_graph(tmp_path, local, openalex_id):
    paper = _paper(openalex_id=openalex_id)
    collector = _collector(tmp_path, [paper], local=local)
    assert collector.collect_seed_papers("receptor") == [paper["paperId"]]
    assert paper["paperId"] in collector.graph_paper_ids
    assert collector.data_manager.download_and_parse_papers.call_count == 1
    if local or not openalex_id:
        assert paper["paperId"] in collector.context_seed_paper_ids
    if not openalex_id:
        collector.data_manager.openalex_api.resolve_work_id.assert_not_called()
        collector.paper_graph_retriever.search_by_paper_title.assert_not_called()
    else:
        assert paper["paperId"] in collector.graph_seed_expansion_modes


def test_real_openalex_external_paper_can_still_expand_from_existing_graph(tmp_path):
    paper = _paper(openalex_id="W123")
    collector = _collector(tmp_path, [paper], local=True, graph_match=True)
    assert collector.collect_seed_papers("receptor") == ["W123"]
    collector.data_manager.download_and_parse_papers.assert_not_called()
    assert collector.context_seed_paper_ids == set()
    assert collector.graph_seed_expansion_modes == {"W123": "evidence_normal"}


def test_snippet_only_external_paper_is_not_a_readable_seed(tmp_path):
    paper = _paper(abstract="", snippet="Discovery metadata only. " * 10)
    collector = _collector(tmp_path, [paper], local=False)
    assert collector.collect_seed_papers("receptor") == []
    assert not collector.metadata_only_graph_seed_ids


def test_survey_bibliography_uses_discovered_metadata(tmp_path):
    manager = _manager(tmp_path)
    paper = _paper(authors=["One Author", {"name": "Two Author"}], venue="Journal", year=2026)
    manager.register_discovered_papers([paper])
    analyzer = object.__new__(WorkAnalyzer)
    analyzer._load_openalex_reference_graph = lambda: None
    analyzer.work_collector = SimpleNamespace(data_manager=manager)
    analyzer.semantic_scholar_api = Mock()
    citation = analyzer.generate_mla(paper["paperId"])
    assert "One Author and Two Author" in citation and "Journal" in citation and "2026" in citation
    analyzer.semantic_scholar_api.get_paper_details.assert_not_called()


@pytest.mark.parametrize("parallel", [True, False])
def test_verified_source_is_reused_in_corpus_without_download_or_mineru(tmp_path, parallel):
    import hashlib
    source = tmp_path / "repository.md"
    content = "Dataset units and measurements from a versioned repository."
    source.write_text(content, encoding="utf-8")
    paper = _paper(abstract="", source_type="dataset")
    paper.update(verified_source_path=str(source), verified_source_sha256=hashlib.sha256(content.encode()).hexdigest(),
                 verified_reading_mode="repository_metadata", version="v2")
    manager = _manager(tmp_path)
    manager.config.ModuleInfo.WorkCollector.download_in_parallel = parallel
    manager._fulltext_download_enabled = lambda: True
    manager._get_reference_graph = lambda: None
    manager._download_single_paper = Mock(side_effect=AssertionError("Should reuse actual source"))
    assert manager.download_and_parse_papers([paper], limit=1) == [paper["paperId"]]
    actual = manager.get_paper_raw_markdown(paper["paperId"])
    assert content in actual and '"version": "v2"' in actual
    manager._download_single_paper.assert_not_called()
    source.write_text("tampered", encoding="utf-8")
    assert manager._verified_source_content(paper["paperId"]) == ""


def test_cached_anysearch_channel_lanes_are_blocked_and_cache_isolated(tmp_path):
    collector = object.__new__(WorkCollector)
    collector.config = SimpleNamespace(ModuleInfo=SimpleNamespace(WorkCollector=SimpleNamespace(enable_anysearch_discovery=True)))
    collector.logger = logging.getLogger(__name__)
    client = SimpleNamespace(search=Mock())
    collector.data_manager = SimpleNamespace(anysearch_api=client, register_discovered_papers=Mock())
    base = {"provider": "anysearch", "query": "receptor modulation", "result_limit": 3,
            "tag": "academic.biomedical", "params": {"field": "tiab"}}
    assert collector._execute_query_lane_with_status(base) == ([], False, "disabled")
    client.search.assert_not_called()
    collector.data_manager.register_discovered_papers.assert_not_called()
    assert collector._sh_retrieval_lane_cache_key(base) != collector._sh_retrieval_lane_cache_key({**base, "tag": "academic.search"})
    assert collector._sh_retrieval_lane_cache_key(base) != collector._sh_retrieval_lane_cache_key({**base, "params": {"field": "all"}})
