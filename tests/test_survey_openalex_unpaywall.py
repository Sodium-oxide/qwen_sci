import os
import sys
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import networkx as nx
import requests


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SURVEY_AGENT_ROOT = os.path.join(PROJECT_ROOT, "src", "agents", "survey_agent")
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, SURVEY_AGENT_ROOT)

from modules.data_manager import DataManager
from modules.work_collector import WorkCollector
from modules.work_analyzer import WorkAnalyzer
from utils import api_call
from utils.api_call import ArxivAPI, OpenAlexAPI, UnpaywallAPI


class _Logger:
    def info(self, *_args, **_kwargs):
        pass

    def warning(self, *_args, **_kwargs):
        pass

    def error(self, *_args, **_kwargs):
        pass


def test_metadata_only_sh_root_is_passed_to_graph_expansion_but_not_reading_pipeline():
    """A full-text failure must not erase a semantically admitted graph root."""

    collector = object.__new__(WorkCollector)
    collector.context_seed_paper_ids = set()
    collector.metadata_only_graph_seed_ids = {"W-metadata-only"}
    collector.expand_in_local_paper_graph = False
    collector.logger = _Logger()
    observed = {}

    def update_reference_graph(seed_ids):
        observed["seed_ids"] = list(seed_ids)
        # End here: this test only verifies graph-root admission, not remote
        # graph retrieval or downstream full-text reading.
        return []

    collector.update_reference_graph = update_reference_graph

    result = WorkCollector.expand_seed_papers_by_reference_and_citation(
        collector,
        ["W-readable-seed"],
    )

    assert result == []
    assert observed["seed_ids"] == ["W-readable-seed", "W-metadata-only"]


class _Response:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


def _api_config(**overrides):
    defaults = {
        "openalex_base_url": "https://api.openalex.org",
        "openalex_api_key": "openalex-test-key",
        "openalex_email": "researcher@example.org",
        "openalex_requests_per_second": 8,
        "openalex_connect_timeout_seconds": 10,
        "openalex_read_timeout_seconds": 30,
        "openalex_api_max_retry": 0,
        "openalex_retry_base_delay_seconds": 1,
        "openalex_retry_max_delay_seconds": 60,
        "openalex_search_per_page": 10,
        "openalex_graph_candidate_per_page": 100,
        "openalex_graph_recent_quota": 1,
        "openalex_graph_high_impact_quota": 1,
        "openalex_graph_cache_schema_version": 2,
        "unpaywall_base_url": "https://api.unpaywall.org/v2",
        "unpaywall_email": "researcher@example.org",
        "unpaywall_timeout": 30,
    }
    defaults.update(overrides)
    return SimpleNamespace(APIInfo=SimpleNamespace(**defaults))


def _raw_work(work_id, title, **overrides):
    work = {
        "id": f"https://api.openalex.org/{work_id}",
        "title": title,
        "publication_year": 2025,
        "publication_date": "2025-01-01",
        "abstract_inverted_index": {"paper": [1], "OpenAlex": [0]},
        "authorships": [{"author": {"display_name": "Ada Lovelace"}}],
        "primary_location": {"source": {"display_name": "Journal of Tests"}},
        "cited_by_count": 0,
    }
    work.update(overrides)
    return work


class _FakeWorks:
    records = {}
    search_results = []
    citation_results = {}
    calls = []

    @classmethod
    def reset(cls):
        cls.records = {}
        cls.search_results = []
        cls.citation_results = {}
        cls.calls = []

    def __init__(self):
        self.search_query = None
        self.filter_values = None
        self.sort_values = None

    def __getitem__(self, record_id):
        if isinstance(record_id, list):
            self.calls.append(("batch", tuple(record_id)))
            return [self.records[work_id] for work_id in record_id if work_id in self.records]
        self.calls.append(("single", record_id))
        return self.records.get(record_id)

    def search(self, query):
        self.search_query = query
        return self

    def filter(self, **kwargs):
        self.filter_values = kwargs
        return self

    def sort(self, **kwargs):
        self.sort_values = kwargs
        return self

    def get(self, per_page=None):
        if self.filter_values and "cites" in self.filter_values:
            key = (
                self.filter_values.get("cites"),
                next(iter(self.sort_values or {}), ""),
            )
            self.calls.append(("citations", key, per_page))
            return self.citation_results.get(key, [])
        if self.filter_values:
            self.calls.append(
                ("filtered_search", self.search_query, self.filter_values, self.sort_values, per_page)
            )
            return self.search_results
        self.calls.append(("search", self.search_query, per_page))
        return self.search_results


def _use_fake_pyalex(monkeypatch):
    _FakeWorks.reset()
    monkeypatch.setattr(api_call, "PyAlexWorks", _FakeWorks)


def test_openalex_normalizes_work_url_and_configures_pyalex(monkeypatch):
    _use_fake_pyalex(monkeypatch)
    _FakeWorks.search_results = [
        _raw_work(
            "W4402952666",
            "OpenAlex-backed paper",
            doi="https://doi.org/10.1000/example",
            best_oa_location={"pdf_url": "https://example.org/open.pdf"},
        )
    ]

    papers = OpenAlexAPI(_api_config()).search_papers("test query")

    assert api_call.pyalex_config.email == "researcher@example.org"
    assert api_call.pyalex_config.api_key == "openalex-test-key"
    assert _FakeWorks.calls == [("search", "test query", 10)]
    assert papers == [
        {
            "paperId": "W4402952666",
            "openalex_id": "https://api.openalex.org/W4402952666",
            "api_platform": "openalex",
            "title": "OpenAlex-backed paper",
            "abstract": "OpenAlex paper",
            "authors": [{"name": "Ada Lovelace"}],
            "year": 2025,
            "venue": "Journal of Tests",
            "externalIds": {"DOI": "10.1000/example"},
            "doi": "10.1000/example",
            "citedByCount": 0,
            "open_access": {"is_oa": True, "oa_status": ""},
            "openAccessPdf": {"url": "https://example.org/open.pdf"},
            "openalex_oa_locations": [
                {
                    "source": "openalex.best_oa_location",
                    "priority": 30,
                    "pdf_url": "https://example.org/open.pdf",
                    "landing_page_url": "",
                    "version": "",
                    "license": "",
                    "host_type": "",
                    "evidence": "openalex.best_oa_location",
                }
            ],
        }
    ]
    assert OpenAlexAPI.normalize_work_id("https://openalex.org/W4402952666") == "W4402952666"
    assert OpenAlexAPI.normalize_work_id("https://api.openalex.org/works/W4402952666") == "W4402952666"


def test_openalex_paces_request_starts_at_or_below_eight_per_second(monkeypatch):
    _use_fake_pyalex(monkeypatch)
    provider = OpenAlexAPI(_api_config(openalex_requests_per_second=10))
    sleeps = []
    monotonic_values = iter((100.0, 100.0, 100.0, 100.0))
    monkeypatch.setattr(api_call, "_OPENALEX_NEXT_REQUEST_NOT_BEFORE", 0.0)
    monkeypatch.setattr(api_call.time, "monotonic", lambda: next(monotonic_values))
    monkeypatch.setattr(api_call.time, "sleep", sleeps.append)

    assert provider.requests_per_second == 8.0
    assert provider._wait_for_request_rate_slot() == 0.0
    assert provider._wait_for_request_rate_slot() == 0.125
    assert sleeps == [0.125]


def test_openalex_injects_connect_and_read_timeout_into_pyalex_request(monkeypatch):
    captured = {}

    class _PrivateWorks:
        def __init__(self):
            self.params = {}

        @property
        def url(self):
            return "https://api.openalex.org/works"

        def _add_params(self, key, value):
            self.params[key] = value

        def search(self, query):
            self.params["search"] = query
            return self

        def _get_from_url(self, url, session=None):
            return session.get(url)

    def fake_request(_session, _method, _url, **kwargs):
        captured["timeout"] = kwargs.get("timeout")
        return []

    monkeypatch.setattr(api_call, "PyAlexWorks", _PrivateWorks)
    monkeypatch.setattr(api_call.requests.Session, "request", fake_request)
    provider = OpenAlexAPI(
        _api_config(
            openalex_connect_timeout_seconds=2,
            openalex_read_timeout_seconds=5,
        )
    )

    assert provider.search_papers("bounded OpenAlex request") == []
    assert captured["timeout"] == (2.0, 5.0)
    assert api_call.pyalex_config.max_retries == 0


def test_openalex_sends_api_key_only_in_authorization_header(monkeypatch):
    captured = {}

    class _CapturingLogger:
        def __init__(self):
            self.messages = []

        def info(self, message, *args, **_kwargs):
            self.messages.append(message % args if args else message)

        def warning(self, message, *args, **_kwargs):
            self.messages.append(message % args if args else message)

    def fake_send(_session, request, **_kwargs):
        captured["authorization"] = request.headers.get("Authorization")
        captured["url"] = request.url
        response = requests.Response()
        response.status_code = 200
        response.url = request.url
        response.request = request
        response.headers.update(
            {
                "X-RateLimit-Limit": "1000",
                "X-RateLimit-Remaining": "999",
                "X-RateLimit-Credits-Used": "1",
                "X-RateLimit-Reset": "3600",
            }
        )
        response._content = b'{"meta": {}, "results": []}'
        return response

    monkeypatch.setattr(api_call.requests.Session, "send", fake_send)
    provider = OpenAlexAPI(_api_config(openalex_api_key="openalex-secret-key"))
    provider.logger = _CapturingLogger()

    assert provider.search_papers("authenticated OpenAlex request") == []
    assert captured["authorization"] == "Bearer openalex-secret-key"
    assert "api_key" not in captured["url"]
    assert all("openalex-secret-key" not in message for message in provider.logger.messages)
    assert any("rate_limit_remaining=999" in message for message in provider.logger.messages)


def test_openalex_skips_network_requests_without_an_api_key(monkeypatch):
    _use_fake_pyalex(monkeypatch)
    monkeypatch.delenv("OPENALEX_API_KEY", raising=False)

    class _CapturingLogger:
        def __init__(self):
            self.messages = []

        def warning(self, message, *args, **_kwargs):
            self.messages.append(message % args if args else message)

    provider = OpenAlexAPI(_api_config(openalex_api_key=""))
    provider.logger = _CapturingLogger()

    assert provider.search_papers("must not reach OpenAlex") == []
    assert _FakeWorks.calls == []
    assert provider.logger.messages == [
        "OpenAlex request skipped label=search 'must not reach OpenAlex' "
        "reason=missing_api_key. Configure APIInfo.openalex_api_key or OPENALEX_API_KEY."
    ]


def test_openalex_search_status_distinguishes_completed_empty_from_request_failure(monkeypatch):
    _use_fake_pyalex(monkeypatch)
    provider = OpenAlexAPI(_api_config())

    papers, successful = provider.search_papers_with_status("valid empty query")

    assert papers == []
    assert successful is True

    monkeypatch.delenv("OPENALEX_API_KEY", raising=False)
    unavailable_provider = OpenAlexAPI(_api_config(openalex_api_key=""))
    unavailable_papers, unavailable_successful = unavailable_provider.search_papers_with_status(
        "request that cannot start"
    )

    assert unavailable_papers == []
    assert unavailable_successful is False


def test_openalex_retries_timeouts_and_429_through_shared_rate_pacer(monkeypatch):
    class _CapturingLogger:
        def __init__(self):
            self.messages = []

        def info(self, message, *args, **_kwargs):
            self.messages.append(message % args if args else message)

        def warning(self, message, *args, **_kwargs):
            self.messages.append(message % args if args else message)

    provider = OpenAlexAPI(_api_config(openalex_api_max_retry=2))
    provider.logger = _CapturingLogger()
    rate_slots = []
    slept = []
    attempts = []
    provider._wait_for_request_rate_slot = lambda: rate_slots.append(True) or 0.125
    monkeypatch.setattr(api_call.time, "sleep", slept.append)

    def operation(_session):
        attempts.append(True)
        if len(attempts) == 1:
            raise requests.ReadTimeout("read timed out")
        if len(attempts) == 2:
            error = requests.HTTPError("rate limited")
            error.response = SimpleNamespace(
                status_code=429,
                headers={
                    "Retry-After": "7",
                    "X-RateLimit-Limit": "1000",
                    "X-RateLimit-Remaining": "123",
                    "X-RateLimit-Credits-Used": "1",
                    "X-RateLimit-Reset": "3600",
                },
            )
            raise error
        return {"ok": True}

    assert provider._call_pyalex("retry test", operation) == {"ok": True}
    assert len(rate_slots) == 3
    assert slept == [1.0, 7.0]
    assert any("attempt=1/3" in message for message in provider.logger.messages)
    assert any("status=429" in message for message in provider.logger.messages)
    assert any("retry_delay_seconds=7.00" in message for message in provider.logger.messages)
    assert any("rate_limit_remaining=123" in message for message in provider.logger.messages)
    assert any("attempt=3/3 status=success" in message for message in provider.logger.messages)


def test_openalex_resolves_doi_and_exact_title_without_semantic_scholar(monkeypatch):
    _use_fake_pyalex(monkeypatch)
    doi_work = _raw_work("W100", "A precise scientific title")
    _FakeWorks.records["https://doi.org/10.1000/example"] = doi_work
    _FakeWorks.search_results = [doi_work, _raw_work("W101", "A different title")]
    provider = OpenAlexAPI(_api_config())

    assert provider.resolve_work_id({"externalIds": {"DOI": "10.1000/example"}}) == "W100"
    assert provider.resolve_work_id({"title": "A precise scientific title", "year": 2025}) == "W100"
    assert provider.resolve_work_id({"title": "A title with no exact match"}) == ""


def test_openalex_applies_only_exact_taxonomy_field_filters(monkeypatch):
    _use_fake_pyalex(monkeypatch)
    _FakeWorks.search_results = [_raw_work("W25", "Materials discovery")]
    provider = OpenAlexAPI(_api_config())
    exact_filter = {
        "applied": True,
        "coverage": "exact",
        "policy": "hard_filter",
        "resolved_field_ids": ["25"],
    }

    provider.search_papers("materials discovery", provider_filter=exact_filter)
    provider.search_papers(
        "electrical engineering",
        provider_filter={
            "applied": False,
            "coverage": "parent_only",
            "policy": "post_filter_only",
            "resolved_field_ids": ["22"],
        },
    )

    assert _FakeWorks.calls[0] == (
        "filtered_search",
        "materials discovery",
        {"primary_topic": {"field": {"id": "25"}}},
        None,
        10,
    )
    assert _FakeWorks.calls[1] == ("search", "electrical engineering", 10)


def test_arxiv_discovery_requires_an_exact_taxonomy_category(monkeypatch):
    calls = []
    atom_response = b"""<?xml version='1.0' encoding='UTF-8'?>
    <feed xmlns='http://www.w3.org/2005/Atom'>
      <entry>
        <id>http://arxiv.org/abs/2501.12345v2</id>
        <title>Materials machine learning</title>
        <summary> A test abstract. </summary>
        <published>2025-01-02T00:00:00Z</published>
        <author><name>Ada Lovelace</name></author>
      </entry>
    </feed>"""

    def fake_get(url, **_kwargs):
        calls.append(url)
        return SimpleNamespace(status_code=200, content=atom_response)

    monkeypatch.setattr(api_call.requests, "get", fake_get)
    provider = ArxivAPI(_api_config())
    exact_filter = {
        "applied": True,
        "coverage": "exact",
        "policy": "hard_filter",
        "category_expression": "(cat:cs.LG OR cat:cs.AI)",
    }

    papers = provider.search_papers("machine learning", provider_filter=exact_filter)
    assert papers[0]["paperId"] == "2501.12345"
    assert papers[0]["externalIds"] == {"ArXiv": "2501.12345"}
    search_query = parse_qs(urlparse(calls[0]).query)["search_query"][0]
    assert "cat:cs.LG" in search_query
    assert "all:machine learning" in search_query

    assert provider.search_papers("machine learning", provider_filter={"applied": False}) == []
    assert len(calls) == 1


def test_openalex_graph_retrieval_batches_references_and_mixes_citation_strata(monkeypatch):
    _use_fake_pyalex(monkeypatch)
    seed = _raw_work("W1", "Seed", referenced_works=["W2", "W3"])
    newest = _raw_work("W2", "Newest citing work", publication_date="2025-06-01")
    foundation = _raw_work("W3", "High impact citing work", cited_by_count=300)
    _FakeWorks.records.update({"W1": seed, "W2": newest, "W3": foundation})
    _FakeWorks.citation_results = {
        ("W1", "publication_date"): [newest],
        ("W1", "cited_by_count"): [foundation],
    }
    provider = OpenAlexAPI(_api_config())

    references = provider.get_related_papers("W1", "out", 2)
    citations = provider.get_related_papers("W1", "in", 2)

    assert [paper["paperId"] for paper in references] == ["W2", "W3"]
    assert [paper["paperId"] for paper in citations] == ["W2", "W3"]
    assert ("batch", ("W2", "W3")) in _FakeWorks.calls
    assert ("citations", ("W1", "publication_date"), 100) in _FakeWorks.calls
    assert ("citations", ("W1", "cited_by_count"), 100) in _FakeWorks.calls


def test_unpaywall_selects_best_open_access_pdf(monkeypatch):
    requested = {}

    def fake_get(url, **kwargs):
        requested["url"] = url
        requested["params"] = kwargs["params"]
        return _Response(
            200,
            {"best_oa_location": {"url_for_pdf": "https://repository.example.org/paper.pdf"}},
        )

    monkeypatch.setattr(api_call.requests, "get", fake_get)

    url = UnpaywallAPI(_api_config()).get_oa_pdf_url("https://doi.org/10.1000/example")

    assert requested["url"].endswith("10.1000%2Fexample")
    assert requested["params"] == {"email": "researcher@example.org"}
    assert url == "https://repository.example.org/paper.pdf"


def test_data_manager_prefers_unpaywall_for_openalex_doi(tmp_path):
    manager = object.__new__(DataManager)
    manager.cache_path = str(tmp_path)
    manager.unpaywall_api = SimpleNamespace(
        enabled=True,
        get_oa_pdf_url=lambda doi: "https://repository.example.org/version-of-record.pdf",
    )

    info = manager._prepare_download_info(
        {
            "paperId": "W4402952666",
            "openalex_id": "https://api.openalex.org/W4402952666",
            "api_platform": "openalex",
            "title": "OpenAlex-backed paper",
            "externalIds": {"DOI": "10.1000/example"},
            "openAccessPdf": {"url": "https://openalex.example.org/accepted-manuscript.pdf"},
        }
    )

    assert info[0] == "W4402952666"
    assert info[1] == [
        {
            "url": "https://repository.example.org/version-of-record.pdf",
            "kind": "pdf",
            "source": "unpaywall.legacy_best_pdf",
            "priority": 0,
            "sources": ["unpaywall.legacy_best_pdf"],
        },
        {
            "url": "https://doi.org/10.1000/example",
            "kind": "landing_page",
            "source": "doi.landing_fallback",
            "priority": 20,
            "doi": "10.1000/example",
            "oa_evidence": "unpaywall.oa_location",
            "sources": ["doi.landing_fallback"],
        },
        {
            "url": "https://openalex.example.org/accepted-manuscript.pdf",
            "kind": "pdf",
            "source": "provider.open_access_pdf",
            "priority": 140,
            "sources": ["provider.open_access_pdf"],
        },
    ]
    assert info[2].endswith(os.path.join("W4402952666", "W4402952666.pdf"))


def test_reference_graph_is_openalex_only_and_rebuilds_with_canonical_ids(tmp_path):
    seed = {
        "paperId": "W1",
        "openalex_id": "https://api.openalex.org/W1",
        "api_platform": "openalex",
        "title": "Seed",
        "abstract": "A sufficiently long seed abstract for graph testing." * 4,
        "authors": [{"name": "Ada"}],
        "year": 2025,
        "venue": "Journal",
    }
    reference = {
        "paperId": "W2",
        "openalex_id": "https://api.openalex.org/W2",
        "api_platform": "openalex",
        "title": "Reference",
        "abstract": "A sufficiently long reference abstract for graph testing." * 4,
        "authors": [{"name": "Grace"}],
        "year": 2024,
        "venue": "Journal",
    }
    citation = {
        "paperId": "W3",
        "openalex_id": "https://api.openalex.org/W3",
        "api_platform": "openalex",
        "title": "Citation",
        "abstract": "A sufficiently long citation abstract for graph testing." * 4,
        "authors": [{"name": "Lin"}],
        "year": 2026,
        "venue": "Journal",
    }

    class _OpenAlexGraph:
        def resolve_work_id(self, paper_id):
            return "W1" if paper_id == "legacy-seed" else paper_id

        def get_paper_details(self, paper_id):
            return {"W1": seed, "W2": reference, "W3": citation}[paper_id]

        def get_related_papers(self, paper_id, direction, _limit):
            assert paper_id == "W1"
            return [reference] if direction == "out" else [citation]

    class _SemanticScholar:
        def __getattr__(self, _name):
            raise AssertionError("Semantic Scholar must not be called by OpenAlex graph expansion")

    collector = object.__new__(WorkCollector)
    collector.config = SimpleNamespace(
        APIInfo=SimpleNamespace(openalex_graph_cache_schema_version=2),
        ModuleInfo=SimpleNamespace(
            WorkCollector=SimpleNamespace(
                related_work_top_k=30,
                reference_graph_depth=1,
                RAG_source_use_embedding_filter=True,
                RAG_source_use_LLM_filter=False,
            )
        ),
    )
    collector.cache_path = str(tmp_path)
    collector.reference_graph_path = os.path.join(str(tmp_path), "reference_graph.pkl")
    collector.reference_graph = None
    collector._openalex_id_aliases = {}
    collector.data_manager = SimpleNamespace(
        openalex_api=_OpenAlexGraph(),
        semantic_scholar_api=_SemanticScholar(),
        _resolve_paper_reference_id=DataManager._resolve_paper_reference_id,
    )
    collector.logger = _Logger()
    collector.graph_paper_ids = set()

    resolved = collector.update_reference_graph(["legacy-seed"])

    assert resolved == ["W1"]
    assert set(collector.reference_graph.nodes) == {"W1", "W2", "W3"}
    assert collector.reference_graph.graph == {
        "provider": "openalex",
        "schema_version": 2,
        "client": "pyalex",
    }
    assert collector.reference_graph.has_edge("W1", "W2")
    assert collector.reference_graph.has_edge("W3", "W1")
    assert all(
        node["provider"] == "openalex"
        for _, node in collector.reference_graph.nodes(data=True)
    )


def test_work_analyzer_uses_the_current_openalex_graph_for_mla(tmp_path):
    reference_graph = nx.DiGraph()
    reference_graph.graph.update(
        {"provider": "openalex", "schema_version": 2, "client": "pyalex"}
    )
    reference_graph.add_node("W4402952666")
    reference_graph.nodes["W4402952666"].update(
        {
            "title": "OpenAlex-backed paper",
            "authors": [{"name": "Ada Lovelace"}],
            "year": 2025,
            "venue": "Journal of Tests",
        }
    )

    class _UnexpectedProvider:
        def __getattr__(self, _name):
            raise AssertionError("No provider should be called when the OpenAlex graph has metadata")

    analyzer = object.__new__(WorkAnalyzer)
    analyzer.config = SimpleNamespace(
        APIInfo=SimpleNamespace(openalex_graph_cache_schema_version=2)
    )
    analyzer.work_collector = SimpleNamespace(reference_graph=reference_graph)
    analyzer.cache_path = str(tmp_path)
    analyzer.logger = _Logger()
    analyzer.openalex_api = _UnexpectedProvider()
    analyzer.semantic_scholar_api = _UnexpectedProvider()
    analyzer.arxiv_api = _UnexpectedProvider()

    assert analyzer._load_openalex_reference_graph() is reference_graph
    citation = analyzer.generate_mla("W4402952666")

    assert citation == 'Ada Lovelace. "OpenAlex-backed paper." *Journal of Tests*, 2025.'


def test_seed_collection_uses_openalex_before_semantic_scholar():
    paper = {
        "paperId": "W4402952666",
        "openalex_id": "https://api.openalex.org/W4402952666",
        "api_platform": "openalex",
        "title": "OpenAlex-backed paper",
        "externalIds": {"DOI": "10.1000/example"},
    }

    class _OpenAlex:
        def search_papers(self, topic):
            assert topic == "OpenAlex first"
            return [paper]

        def resolve_work_id(self, reference):
            assert reference == paper
            return "W4402952666"

    class _SemanticScholar:
        def search_papers(self, **_kwargs):
            raise AssertionError("Semantic Scholar must not run when OpenAlex found papers")

    class _DataManager:
        openalex_api = _OpenAlex()
        semantic_scholar_api = _SemanticScholar()

        def __init__(self):
            self.download_requests = []

        def _resolve_paper_reference_id(self, paper_info):
            return paper_info["paperId"]

        def download_and_parse_papers(self, papers, limit):
            self.download_requests.append((papers, limit))
            return ["W4402952666"]

    data_manager = _DataManager()
    collector = object.__new__(WorkCollector)
    collector.config = SimpleNamespace(
        ModuleInfo=SimpleNamespace(
            WorkCollector=SimpleNamespace(
                use_seed_filter_LLM=False,
                max_seed_paper_num=5,
            )
        )
    )
    collector.data_manager = data_manager
    collector.logger = _Logger()
    collector.expand_in_local_paper_graph = False
    collector.graph_paper_ids = set()
    collector.ignore_paper = set()
    collector._openalex_id_aliases = {}

    assert collector.collect_seed_papers("OpenAlex first") == ["W4402952666"]
    assert data_manager.download_requests == [([paper], 5)]


def test_research_context_default_cache_paths_are_fingerprint_scoped(tmp_path):
    collector = object.__new__(WorkCollector)
    collector.cache_path = str(tmp_path)
    collector.config = SimpleNamespace(
        BasicInfo=SimpleNamespace(research_context_path="")
    )

    first_path = collector._research_context_cache_path(
        original_topic="Crop disease diagnosis",
        title="",
        declared_domain="",
        objective="visual diagnosis",
        research_brief="",
    )
    second_path = collector._research_context_cache_path(
        original_topic="Crop disease diagnosis",
        title="",
        declared_domain="",
        objective="multimodal early warning",
        research_brief="",
    )

    assert first_path != second_path
    assert os.path.dirname(first_path).endswith("research_context")

    collector.config.BasicInfo.research_context_path = str(tmp_path / "explicit.json")
    assert collector._research_context_cache_path(
        original_topic="Another topic",
        title="",
        declared_domain="",
        objective="",
        research_brief="",
    ) == str(tmp_path / "explicit.json")
