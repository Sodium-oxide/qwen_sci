import json
import time
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock

from omegaconf import OmegaConf
import pytest
import requests

from src.pipeline.anysearch import (
    AnySearchClient,
    DEFAULT_ANYSEARCH_BASE_URL,
    anysearch_from_survey_config,
    identity_keys,
    merge_papers,
    normalize_anysearch_paper,
    parse_anysearch_response,
    with_anysearch_lanes,
)


class Response:
    def __init__(self, payload=None, status=200):
        self.payload, self.status_code = payload, status

    def json(self):
        return self.payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code))


class Session:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        result = self.responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


@pytest.mark.parametrize("envelope", [None, "results", "papers", "data"])
def test_response_normalizes_actual_abstract_and_stable_identity(envelope):
    rows = [{"title": "A receptor study", "doi": "https://doi.org/10.1000/TEST", "abstract": "Actual abstract.",
             "snippet": "Discovery text.", "pdf_url": "https://repo.example/paper.pdf",
             "authors": ["One Author", {"display_name": "Two Author"}, None, {}]}]
    papers = parse_anysearch_response({envelope: rows} if envelope else rows)
    paper = papers[0]
    assert paper["abstract"] == "Actual abstract."
    assert paper["discovery_snippet"] == "Discovery text."
    assert paper["doi"] == "10.1000/test"
    assert paper["authors"] == [{"name": "One Author"}, {"name": "Two Author"}]
    assert paper["paperId"].startswith("AS")
    assert normalize_anysearch_paper({"title": "Different title", "doi": "10.1000/test"})["paperId"] == paper["paperId"]
    assert paper["openalex_oa_locations"][0]["pdf_url"].endswith(".pdf")


def test_snippet_is_never_promoted_to_abstract_and_openalex_ids_survive():
    paper = normalize_anysearch_paper({"paperId": "https://openalex.org/W123", "title": "Study", "snippet": "Only a snippet"})
    assert paper["paperId"] == "W123"
    assert paper["abstract"] == ""
    assert paper["discovery_snippet"] == "Only a snippet"
    assert normalize_anysearch_paper({"title": "Study", "authors": "One Author"})["authors"] == []


def test_public_rest_envelope_preserves_discovery_content_and_doi_url():
    papers = parse_anysearch_response({"code": 0, "message": "success", "request_id": "example-request", "data": {
        "results": [{"title": "Receptor study", "url": "https://doi.org/10.1000/TEST?source=search",
                     "snippet": "Author (2026)", "content": "Cleaned source content."}],
        "metadata": {"total_results": 1, "search_time_ms": 100},
    }})
    assert len(papers) == 1
    assert papers[0]["doi"] == "10.1000/test"
    assert papers[0]["abstract"] == ""
    assert papers[0]["discovery_content"] == "Cleaned source content."
    assert papers[0]["discovery_snippet"] == "Author (2026)"
    assert parse_anysearch_response({"code": 0, "data": {"results": []}}) == []


@pytest.mark.parametrize("payload", [
    {"code": -1, "message": "sensitive-upstream-message", "data": {"results": []}},
    {"error": {"message": "sensitive-upstream-message"}, "results": []},
])
def test_business_errors_are_failures_without_exposing_upstream_messages(payload):
    with pytest.raises(ValueError) as exc:
        parse_anysearch_response(payload)
    assert "sensitive-upstream-message" not in str(exc.value)


@pytest.mark.parametrize("base", ["https://anysearch.example", "https://anysearch.example/v1/", "https://anysearch.example/v1/search"])
def test_rest_endpoint_variants_and_server_result_limit(base):
    session = Session(Response({"code": 0, "data": {"results": []}}))
    client = AnySearchClient(base, api_key="", session=session)
    assert client.search(" receptor ", limit=100).successful
    url, kwargs = session.calls[0]
    assert url == "https://anysearch.example/v1/search"
    assert kwargs["json"] == {"query": "receptor", "max_results": 10, "tag": "academic.search", "format": "json"}
    assert kwargs["headers"] == {}
    assert "params" not in kwargs


@pytest.mark.parametrize("base", ["https://anysearch.example/mcp/", "https://anysearch.example/sse", "https://anysearch.example?key=unused"])
def test_mcp_or_query_urls_never_receive_rest_requests(base):
    session = Session()
    result = AnySearchClient(base, session=session).search("receptor")
    assert result.status == "provider_failure" and result.attempts == 0
    assert not session.calls


def test_official_default_and_environment_override(monkeypatch):
    monkeypatch.delenv("ANYSEARCH_BASE_URL", raising=False)
    assert AnySearchClient(api_key="").base_url == DEFAULT_ANYSEARCH_BASE_URL
    config = OmegaConf.load("src/config/default.yaml")
    assert config.survey.ModuleInfo.WorkCollector.enable_anysearch_discovery is False
    assert config.survey.ModuleInfo.WorkCollector.shared_search_enabled is False
    assert config.idea.agent.anysearch.enabled is True
    for key in ["survey.APIInfo.anysearch_base_url", "idea.agent.anysearch.base_url", "quantitative_modeling.parameter_evidence.anysearch_base_url"]:
        assert OmegaConf.select(config, key) == DEFAULT_ANYSEARCH_BASE_URL
    monkeypatch.setenv("ANYSEARCH_BASE_URL", "https://anysearch.example")
    assert AnySearchClient(api_key="").base_url == "https://anysearch.example"
    assert config.survey.APIInfo.anysearch_base_url == "https://anysearch.example"
    assert config.idea.agent.anysearch.base_url == "https://anysearch.example"


def test_cross_provider_dedup_retains_metadata_and_every_origin():
    oa = {"paperId": "W123", "title": "A study", "externalIds": {"DOI": "10.1000/test"},
          "retrieval_provenance": [{"provider": "openalex"}]}
    external = normalize_anysearch_paper({"title": "An alternate title", "doi": "10.1000/test", "abstract": "Actual abstract"})
    external["retrieval_provenance"] = [{"provider": "anysearch", "query": "receptor"}]
    merged = merge_papers([oa, external])
    assert len(merged) == 1
    assert merged[0]["paperId"] == "W123"
    assert merged[0]["abstract"] == "Actual abstract"
    assert {item["provider"] for item in merged[0]["retrieval_provenance"]} == {"openalex", "anysearch"}
    assert merged[0]["discovery_provenance"][0]["provider"] == "anysearch"
    assert identity_keys({"node_id": "https://api.openalex.org/W123"}) & identity_keys(oa)


@pytest.mark.parametrize("status", ["disabled", "unconfigured"])
def test_unconfigured_or_disabled_does_not_make_requests(tmp_path, status):
    session = Session()
    client = AnySearchClient("" if status == "unconfigured" else "https://anysearch.example", enabled=status != "disabled", session=session, cache_dir=tmp_path)
    result = client.search("receptor")
    assert result.status == status
    assert not result.successful
    assert not session.calls
    assert not list(tmp_path.glob("*.json"))


def test_bounded_transient_retry_and_success_cache(tmp_path):
    session = Session(Response(status=429), Response({"results": [{"title": "Study"}]}))
    client = AnySearchClient("https://anysearch.example/", api_key="test-credential", session=session, cache_dir=tmp_path, max_retries=1)
    result = client.search("receptor", limit=5)
    assert result.successful and result.attempts == 2
    url, kwargs = session.calls[0]
    assert url == "https://anysearch.example/v1/search"
    assert kwargs["json"] == {"query": "receptor", "max_results": 5, "tag": "academic.search", "format": "json"}
    assert kwargs["headers"] == {"Authorization": "Bearer test-credential"}
    assert kwargs["timeout"] == (5.0, 30.0)
    assert client.search("receptor", limit=5).cached
    assert len(session.calls) == 2


@pytest.mark.parametrize("failure", [requests.Timeout(), requests.ConnectionError(), Response(status=503), Response(status=429)])
def test_provider_failure_is_bounded_and_never_cached_as_empty(tmp_path, failure):
    session = Session(failure, failure, Response([]))
    client = AnySearchClient("https://anysearch.example", session=session, cache_dir=tmp_path, max_retries=1)
    result = client.search("receptor")
    assert not result.successful and result.attempts == 2
    assert not list(tmp_path.glob("*.json"))
    assert client.search("receptor").status == "valid_empty"
    assert len(session.calls) == 3


@pytest.mark.parametrize("response", [Response(status=403), Response({"unexpected": []}), Response({"results": [{"error": "no valid metadata"}]}),
                                      Response({"code": -1, "message": "private-message", "data": {"results": []}})])
def test_permanent_http_or_schema_failure_does_not_retry(tmp_path, response):
    session = Session(response)
    result = AnySearchClient("https://anysearch.example", session=session, cache_dir=tmp_path, max_retries=3).search("receptor")
    assert result.status == "provider_failure" and result.attempts == 1
    assert not list(tmp_path.glob("*.json"))


def test_empty_cache_expires_and_corrupt_cache_is_ignored(tmp_path):
    session = Session(Response([]), Response([{ "title": "New study"}]), Response([]))
    client = AnySearchClient("https://anysearch.example", session=session, cache_dir=tmp_path)
    assert client.search("receptor").status == "valid_empty"
    assert client.search("receptor").cached
    path = next(tmp_path.glob("*.json"))
    cached = json.loads(path.read_text())
    cached["saved_at"] = time.time() - 21601
    path.write_text(json.dumps(cached))
    assert client.search("receptor").papers[0]["title"] == "New study"
    path.write_text("[]")
    assert client.search("receptor").status == "valid_empty"
    assert len(session.calls) == 3


def test_plan_upgrade_covers_nested_cached_sh_slots_without_losing_scope():
    lane = {"provider": "openalex", "lane": "broad_anchor", "query": "receptor", "subhypothesis_id": "SH1", "slot_name": "mechanism",
            "provider_filter": {"type": "review"}, "hard_filter_applied": True}
    plan = {"identity": "unchanged", "query_lanes": [lane], "subhypotheses": [{"slot_recovery_tasks": [{"retrieval_plan": {"query_lanes": [lane]}}]}]}
    original = deepcopy(plan)
    upgraded = with_anysearch_lanes(plan, enabled=True, result_limit=7)
    for lanes in [upgraded["query_lanes"], upgraded["subhypotheses"][0]["slot_recovery_tasks"][0]["retrieval_plan"]["query_lanes"]]:
        assert [item["provider"] for item in lanes] == ["openalex", "anysearch"]
        assert lanes[1]["subhypothesis_id"] == "SH1" and lanes[1]["slot_name"] == "mechanism"
        assert "provider_filter" not in lanes[1]
        assert lanes[1]["result_limit"] == 7
    assert upgraded["identity"] == "unchanged" and plan == original
    assert with_anysearch_lanes(upgraded, enabled=True) == upgraded
    assert with_anysearch_lanes(plan, enabled=False) == plan


@pytest.mark.parametrize("enabled", [True, False, "true", "false"])
def test_survey_client_denies_access_with_legacy_config_and_environment(monkeypatch, tmp_path, enabled):
    monkeypatch.setenv("ANYSEARCH_BASE_URL", "https://anysearch.example")
    monkeypatch.setenv("ANYSEARCH_API_KEY", "test-credential")
    config = SimpleNamespace(BasicInfo=SimpleNamespace(cache_path=str(tmp_path)), APIInfo=SimpleNamespace(),
                             ModuleInfo=SimpleNamespace(WorkCollector=SimpleNamespace(enable_anysearch_discovery=enabled)))
    client = anysearch_from_survey_config(config)
    client.session = Mock()
    assert not client.enabled and client.base_url == "https://anysearch.example"
    assert client.search("receptor").status == "disabled"
    assert client.capabilities(refresh=True)["status"] == "disabled"
    client.session.post.assert_not_called()
    client.session.get.assert_not_called()


def test_survey_client_defaults_to_official_service_and_accepts_tag(monkeypatch, tmp_path):
    monkeypatch.delenv("ANYSEARCH_BASE_URL", raising=False)
    config = {"BasicInfo": {"cache_path": str(tmp_path)}, "APIInfo": {"anysearch_tag": "academic.biomedical"},
              "ModuleInfo": {"WorkCollector": {"enable_anysearch_discovery": True}}}
    client = anysearch_from_survey_config(config)
    assert not client.enabled
    assert client.base_url == DEFAULT_ANYSEARCH_BASE_URL
    assert client.tag == "academic.biomedical"


def test_cache_separates_academic_search_tags(tmp_path):
    session = Session(Response({"code": 0, "data": {"results": []}}), Response({"code": 0, "data": {"results": []}}))
    for tag in ["academic.search", "academic.biomedical", "academic.search"]:
        result = AnySearchClient("https://anysearch.example", api_key="", session=session, cache_dir=tmp_path, tag=tag).search("receptor")
        assert result.successful
    assert result.cached
    assert len(session.calls) == 2
