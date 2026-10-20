import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import requests

from src.pipeline.adaptive_search import AdaptiveSearch, acquisition_scope, load_history
from src.pipeline.anysearch import AnySearchClient, SearchResult, identity_keys, merge_papers, normalize_anysearch_paper
from src.pipeline.search_capabilities import validate_route
from src.pipeline.search_planner import ScientificSearchPlanner, scientific_input
from src.pipeline.source_reader import SourceReader
from src.pipeline.source_retry import SOURCE_READER_REVISION, source_route_fingerprint


def catalog():
    return {"status": "success", "channels": {
        "academic.search": {"description": "Cross-discipline papers", "params": {"year_from": {}, "year_to": {}, "open_access": {"type": "boolean"}}},
        "academic.biomedical": {"description": "Biomedical evidence", "params": {"source": {}, "field": {"enum": ["title", "tiab"]}}},
        "academic.dataset": {"description": "Data and code repositories", "params": {"resource_type": {"enum": ["Dataset", "Software"]}}},
        "academic.citation": {"description": "Citation graph", "params": {"id": {"required": True}, "id_type": {}, "op": {}}},
    }}


class Response:
    def __init__(self, payload=None, *, body="", status=200, headers=None):
        self.payload, self.body, self.status_code = payload, body, status
        self.headers = headers or {"Content-Type": "text/html"}
        self.encoding = "utf-8"
        self.closed = False

    def json(self):
        return self.payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code))

    def iter_content(self, size):
        yield self.body.encode()

    def close(self):
        self.closed = True


def paper(i, **fields):
    return normalize_anysearch_paper({"title": f"Perovskite stability mechanism {i}", "doi": f"10.1000/p{i}",
                                      "abstract": "Actual measured perovskite stability and degradation mechanism.", **fields})


def reference(p):
    return {"paper_id": p["paperId"], "title": p["title"], "doi": p["doi"],
            "reading_status": "completed", "reading_mode": "abstract", "keynote": p["abstract"]}


def need(*, read_limit=8, routes=None):
    return {"id": "N1", "kind": "mechanism", "purpose": "Find degradation evidence", "target_subproblem": "Which degradation mechanisms are measured?",
            "disciplines": ["materials", "machine learning"], "object_terms": ["perovskite"],
            "coverage_terms": ["stability"], "expected_source_types": ["paper"],
            "queries": ["perovskite stability", "perovskite degradation mechanisms"],
            "routes": routes or [{"provider": "anysearch", "tag": "academic.search", "params": {}, "query": "perovskite stability"}],
            "budget": {"requests": 4, "successful_reads": read_limit}}


def runner(tmp_path, client, reader, *, state=None, settings=None, inherited=()):
    path = tmp_path / "search.json"
    if state:
        path.write_text(json.dumps(state))
    return AdaptiveSearch(path=path, client=client, reader=reader, inherited=inherited,
                          settings={"max_rounds": 1, "read_limit": 8, "result_limit": 10, **(settings or {})})


def state(plan_need=None):
    return {"phase": "survey", "capabilities": catalog(), "plan": {"needs": [plan_need or need()]}}


@pytest.mark.parametrize("tag,params", [
    ("fictional.physics", {}), ("academic.search", {"invented": "x"}),
    ("academic.citation", {"op": "citations"}), ("academic.search", {"year_from": "yesterday"}),
    ("academic.search", {"year_from": 2026, "year_to": 2020}),
    ("academic.biomedical", {"field": "unknown"}), ("academic.search", {"open_access": 7}),
])
def test_invalid_catalog_routes_rejected(tag, params):
    with pytest.raises(ValueError):
        validate_route(catalog(), tag, params)


def test_capability_discovery_cache_and_stale_fallback_are_secret_safe(tmp_path):
    domains = Response({"code": 0, "data": {"domains": [{"domain": "academic"}]}})
    details = Response({"code": 0, "data": {"domains": [{"domain": "academic", "sub_domains": [
        {"sub_domain": tag, **item} for tag, item in catalog()["channels"].items()
    ]}]}})
    session = SimpleNamespace(get=Mock(side_effect=[domains, details]))
    client = AnySearchClient("https://search.example", session=session, api_key="", cache_dir=tmp_path)
    assert "academic.citation" in client.capabilities()["channels"]
    assert client.capabilities()["status"] == "success"
    assert session.get.call_count == 2
    cached = AnySearchClient("https://search.example", session=SimpleNamespace(get=Mock()), cache_dir=tmp_path)
    assert "academic.dataset" in cached.capabilities()["channels"]
    cached.session.get.assert_not_called()
    cached.session.get = Mock(return_value=Response({"code": -1, "message": "DO_NOT_PERSIST_THIS_SECRET"}))
    assert cached.capabilities(refresh=True)["status"] == "stale"
    assert "DO_NOT_PERSIST_THIS_SECRET" not in str(cached.capabilities())
    assert "DO_NOT_PERSIST_THIS_SECRET" not in "".join(p.read_text() for p in tmp_path.glob("*.json"))


def test_per_request_tags_params_cache_and_invalid_request_no_http(tmp_path):
    session = SimpleNamespace(post=Mock(return_value=Response({"results": []})))
    client = AnySearchClient("https://search.example", session=session, cache_dir=tmp_path)
    client._capability_catalog = catalog()
    assert client.search("perovskite", tag="academic.search", params={"year_from": 2020}).successful
    assert client.search("perovskite", tag="academic.search", params={"year_from": 2021}).successful
    assert client.search("perovskite", tag="academic.dataset", params={"resource_type": "Dataset"}).successful
    assert client.search("perovskite", tag="academic.search", params={"year_from": 2020}).cached
    assert client.search("perovskite", tag="academic.citation", params={}).status == "invalid_request"
    assert session.post.call_count == 3
    payloads = [call.kwargs["json"] for call in session.post.call_args_list]
    assert payloads[-1]["tag"] == "academic.dataset"
    assert payloads[-1]["params"] == {"resource_type": "Dataset"}


def test_multidisciplinary_plan_only_receives_science_and_real_capabilities():
    inputs = scientific_input({"original_request": "Predict perovskite solar cell stability with machine learning",
        "rubric": "PRIVATE_RUBRIC", "evidence_gaps": [{"description": "degradation pathways", "score": "PRIVATE_SCORE"}]},
        topic="perovskite solar cell stability", project_context={"research_identity": {"core_entities": ["perovskite solar cell"]}},
        candidates=[{"title": "Transfer survival analysis", "hypothesis": "censored lifetime observations predict failure", "evaluation": "PRIVATE_EVALUATION"}])
    needs = [need(read_limit=2), {**need(read_limit=1), "id": "N2", "kind": "data_code", "expected_source_types": ["dataset"],
        "target_subproblem": "Find stability measurements and benchmark data", "routes": [
            {"provider": "anysearch", "tag": "academic.dataset", "params": {"resource_type": "Dataset"},
             "query": "perovskite stability dataset"}]}]
    llm = Mock(return_value=json.dumps({"needs": needs}))
    result = ScientificSearchPlanner(catalog(), llm=llm).plan(inputs)
    assert result["source"] == "model" and len(result["needs"]) == 2
    prompt = llm.call_args.args[0]
    assert "PRIVATE_" not in prompt
    assert "academic.dataset" in prompt and "degradation pathways" in prompt
    assert inputs["context"]["core_entities"] == ["perovskite solar cell"]
    assert all(len(q.split()) < 20 for n in result["needs"] for q in n["queries"])


def test_plan_parse_failure_preserves_raw_and_falls_back_with_bounded_repair():
    raw = []
    llm = Mock(return_value="invalid JSON model reply")
    inputs = scientific_input({"original_request": "Investigate perovskite solar cell stability dataset"}, topic="perovskite solar cell stability")
    result = ScientificSearchPlanner(catalog(), llm=llm, repair_attempts=1,
                                     save_raw=lambda label, reply: raw.append(reply)).plan(inputs)
    assert llm.call_count == 2 and raw == ["invalid JSON model reply"] * 2
    assert result["source"] == "deterministic_fallback" and result["needs"]
    assert any(n["kind"] == "data_code" for n in result["needs"])


def test_failed_downloads_backfill_until_eight_successful_reads_and_resume(tmp_path):
    papers = [paper(i) for i in range(12)]
    client = SimpleNamespace(search=Mock(return_value=SearchResult(papers, "success", 1)))
    calls = []

    def read(p):
        saved = load_history(tmp_path / "search.json")
        assert saved["reads"][p["paperId"]]["status"] == "in_progress"
        calls.append(p["paperId"])
        if p["paperId"] in {v["paperId"] for v in papers[:4]}:
            return {"reading_status": "unavailable"}
        return reference(p)

    result = runner(tmp_path, client, read, state=state(), settings={"max_acquisition_attempts": 20}).run(phase="survey", task={}, topic="perovskite")
    assert len(result["references"]) == 8 and len(calls) == 12
    saved = load_history(tmp_path / "search.json")
    assert saved["budget"]["acquisitions"] == 12
    resumed = runner(tmp_path, client, read).run(phase="survey", task={}, topic="perovskite")
    assert len(resumed["references"]) == 8 and len(calls) == 12 and client.search.call_count == 1


def test_acquisition_budget_is_durable_and_does_not_consume_read_success_slots(tmp_path):
    client = SimpleNamespace(search=Mock(return_value=SearchResult([paper(i) for i in range(10)], "success")))
    read = Mock(return_value={"reading_status": "unavailable"})
    result = runner(tmp_path, client, read, state=state(), settings={"max_acquisition_attempts": 3}).run(phase="survey", task={})
    assert result["references"] == [] and read.call_count == 3
    saved = load_history(tmp_path / "search.json")
    assert saved["status"] == "budget_exhausted" and saved["budget"]["acquisitions"] == 3
    runner(tmp_path, client, read, settings={"max_acquisition_attempts": 3}).run(phase="survey", task={})
    assert read.call_count == 3


def test_reading_success_rate_includes_failed_attempt_before_success(tmp_path):
    candidate = paper(1)
    client = SimpleNamespace(search=Mock(return_value=SearchResult([candidate], "success")))
    read = Mock(side_effect=[{"reading_status": "unavailable"}, reference(candidate)])
    result = runner(tmp_path, client, read, state=state(need(read_limit=1)),
                    settings={"max_rounds": 2}).run(phase="survey", task={})
    assert len(result["references"]) == 1 and read.call_count == 2
    metrics = load_history(tmp_path / "search.json")["summary"]["N1"]
    assert metrics["read_attempts"] == 2
    assert metrics["read_successes"] == 1
    assert metrics["reading_success_rate"] == 0.5


def test_all_needs_are_probed_before_read_budget_is_allocated_to_extra_reads(tmp_path):
    first, second = need(read_limit=2), need(read_limit=2)
    second.update(id="N2", purpose="Find transferable prediction methods", queries=["perovskite prediction methods"],
                  routes=[{"provider": "anysearch", "tag": "academic.search", "params": {}, "query": "perovskite prediction methods"}])
    saved = state(first)
    saved["plan"]["needs"].append(second)

    def search(query, **options):
        return SearchResult([paper(1), paper(2)] if query == "perovskite stability" else [paper(3), paper(4)], "success")

    client = SimpleNamespace(search=Mock(side_effect=search))

    def read(p):
        assert client.search.call_count >= 2
        return reference(p)

    result = runner(tmp_path, client, read, state=saved, settings={"max_rounds": 2, "read_limit": 2}).run(phase="survey", task={})
    assert [r["paper_id"] for r in result["references"]] == [paper(1)["paperId"], paper(3)["paperId"]]


def test_duplicates_trigger_real_id_citation_trace_and_actual_content_coverage(tmp_path):
    old, new = paper(1), paper(2)
    def search(query, **kwargs):
        return SearchResult([new] if kwargs.get("tag") == "academic.citation" else [old, old], "success")
    client = SimpleNamespace(search=Mock(side_effect=search))
    result = runner(tmp_path, client, reference, state=state(need(read_limit=1)), settings={"max_rounds": 2}).run(
        phase="survey", task={}, known_references=[reference(old)])
    assert [r["paper_id"] for r in result["references"]] == [new["paperId"]]
    call = client.search.call_args_list[-1]
    assert call.kwargs["tag"] == "academic.citation" and call.kwargs["params"]["id"] == old["doi"]
    saved = load_history(tmp_path / "search.json")
    assert saved["adjustments"][0]["metrics"]["duplicates"] >= 1
    assert saved["summary"]["N1"]["covered_terms"] == ["stability"]
    assert saved["summary"]["N1"]["coverage_basis"] == "actual_read_content"


def test_inherited_requests_and_readings_reused_without_new_io(tmp_path):
    p = paper(1)
    prior = {**state(need(read_limit=1)), "queries": [{"provider": "anysearch", "tag": "academic.search", "params": {},
            "query": "perovskite stability", "result_limit": 10, "status": "success", "papers": [p]}],
             "reads": {p["paperId"]: {"status": "completed", "reference": reference(p), "need_id": "N1"}}}
    client = SimpleNamespace(search=Mock())
    read = Mock()
    result = runner(tmp_path, client, read, state=state(need(read_limit=1)), inherited=[prior]).run(phase="idea", task={})
    assert len(result["references"]) == 1
    assert result["searches"][0]["status"] == "reused"
    client.search.assert_not_called()
    read.assert_not_called()


def test_http_retry_attempts_cannot_exceed_shared_request_budget(tmp_path):
    session = SimpleNamespace(post=Mock(return_value=Response(status=503)))
    client = AnySearchClient("https://search.example", session=session, max_retries=3)
    client._capability_catalog = catalog()
    result = runner(tmp_path, client, Mock(), state=state(), settings={"max_http_requests": 2}).run(phase="survey", task={})
    assert session.post.call_count == 2 and result["references"] == []
    saved = load_history(tmp_path / "search.json")
    assert saved["budget"]["http"] == 2


def test_url_identifiers_direct_pdf_and_dataset_versions():
    pmc = normalize_anysearch_paper({"title": "Source", "url": "https://pmc.ncbi.nlm.nih.gov/articles/PMC123456/"})
    arxiv = normalize_anysearch_paper({"title": "Source preprint", "url": "https://arxiv.org/pdf/2401.12345v2.pdf"})
    assert pmc["externalIds"]["PMCID"] == "PMC123456"
    assert arxiv["externalIds"]["ArXiv"] == "2401.12345v2"
    assert arxiv["openAccessPdf"]["url"].endswith(".pdf")
    first = normalize_anysearch_paper({"title": "Dataset", "url": "https://zenodo.org/records/123", "source_type": "dataset", "version": "v1"})
    second = normalize_anysearch_paper({"title": "Dataset", "url": "https://zenodo.org/records/123", "source_type": "dataset", "version": "v2"})
    assert not identity_keys(first) & identity_keys(second)
    assert len(merge_papers([first, second])) == 2 and first["paperId"] != second["paperId"]
    article = normalize_anysearch_paper({"title": "Dataset", "source_type": "paper", "url": "https://publisher.example/article"})
    dataset = normalize_anysearch_paper({"title": "Dataset", "source_type": "dataset", "url": "https://zenodo.org/records/123"})
    assert len(merge_papers([article, dataset])) == 2
    assert article["paperId"] != dataset["paperId"]


def test_read_real_pmc_page_preserves_original_and_scope_never_snippet(tmp_path):
    p = normalize_anysearch_paper({"title": "Source", "url": "https://pmc.ncbi.nlm.nih.gov/articles/PMC123456/", "snippet": "UNVERIFIED_SNIPPET"})
    html = '<html><meta name="citation_doi" content="10.1000/a"><article><section id="abstract">Real abstract.</section><h2>Results</h2>' + "Actual measured receptor observations. " * 180 + '</article></html>'
    session = SimpleNamespace(get=Mock(return_value=Response(body=html)))
    manager = SimpleNamespace(register_discovered_papers=Mock(), get_paper_raw_markdown=Mock())
    result = SourceReader(manager, tmp_path, session=session).read(p, max_source_chars=1000)
    assert result["reading_status"] == "completed" and result["reading_mode"] == "fulltext_html_excerpt"
    assert "UNVERIFIED_SNIPPET" not in result["keynote"] and result["doi"] == "10.1000/a"
    assert result["reading_range"]["end"] == 1000
    assert len(Path(result["source_path"]).read_text()) > 5000
    manager.get_paper_raw_markdown.assert_not_called()
    cached = SourceReader(manager, tmp_path, session=session).read(p, max_source_chars=1200)
    assert len(cached["keynote"]) == 1200 and session.get.call_count == 1


def test_dataset_read_records_version_and_checks_actual_download(tmp_path):
    p = normalize_anysearch_paper({"title": "Solar stability dataset", "url": "https://zenodo.org/records/123", "source_type": "dataset", "snippet": "UNVERIFIED"})
    html = '<html><script type="application/ld+json">{"@type":"Dataset","version":"2.1","distribution":[{"contentUrl":"https://zenodo.org/records/123/files/data.csv"}]}</script><main>Dataset description and units.</main></html>'
    responses = [Response(body=html), Response(status=206, headers={"Content-Type": "text/csv", "Content-Length": "1024"})]
    session = SimpleNamespace(get=Mock(side_effect=responses))
    result = SourceReader(None, tmp_path, session=session).read(p)
    assert result["version"] == "2.1" and result["repository_id"] == "zenodo:123"
    assert result["access_status"] == "download_verified"
    assert result["reading_mode"] == "repository_metadata" and "UNVERIFIED" not in result["keynote"]
    assert session.get.call_args.kwargs["headers"]["Range"] == "bytes=0-1023"
    assert all(r.closed for r in responses)


def test_doi_metadata_must_match_identity_before_abstract_fallback(tmp_path):
    p = paper(1, abstract="")
    api = SimpleNamespace(get_paper_details=Mock(return_value={"doi": "10.1000/WRONG", "abstract": "Wrong paper abstract"}))
    manager = SimpleNamespace(openalex_api=api, register_discovered_papers=Mock(),
        get_paper_title_abstract=Mock(side_effect=ValueError("missing")))
    result = SourceReader(manager, tmp_path).read(p, prefer_fulltext=False)
    assert result["reading_status"] == "unavailable" and "keynote" not in result
    api.get_paper_details.return_value = {"doi": p["doi"], "abstract": "Verified actual abstract"}
    result = SourceReader(manager, tmp_path).read(p, prefer_fulltext=False)
    assert result["reading_mode"] == "abstract" and result["keynote"] == "Verified actual abstract"
    assert result["metadata_identity_status"] == "doi_exact_match"


def test_github_source_reads_requested_release_at_verified_commit(tmp_path):
    p = normalize_anysearch_paper({"title": "Solar prediction code", "url": "https://github.com/science/solar", "version": "v2"})
    assert p["source_type"] == "code"
    responses = [Response(body=json.dumps({"default_branch": "main"})),
                 Response(body=json.dumps({"sha": "f" * 40})), Response(body="# Solar\nActual reproducibility instructions.")]
    session = SimpleNamespace(get=Mock(side_effect=responses))
    result = SourceReader(None, tmp_path, session=session).read(p)
    assert result["repository_id"] == "github.com/science/solar"
    assert result["version"] == "f" * 40 and result["reading_mode"] == "repository_readme"
    assert session.get.call_args_list[1].args[0].endswith("/commits/v2")
    assert ("/" + "f" * 40 + "/README.md") in session.get.call_args_list[2].args[0]
    assert all(r.closed for r in responses)


def test_existing_discipline_and_subproblem_science_are_visible_without_assessment_fields():
    supplied = scientific_input({"current_subproblem": [{"question": "Which membrane conditions change receptor modulation?",
        "rubric": "SECRET_SCORING", "score": 5}]}, project_context={"discovery_taxonomy": {
            "primary_discipline": "Biophysics", "assessment": "SECRET_SCORING"}, "secondary_disciplines": ["Pharmacology"]})
    assert "Biophysics" in supplied["disciplines"] and "Pharmacology" in supplied["disciplines"]
    assert supplied["current_subproblem"] == ["Which membrane conditions change receptor modulation?"]
    assert "SECRET_SCORING" not in json.dumps(supplied)


def test_policy_pdf_is_delegated_to_pdf_parser_without_page_size_limit(tmp_path):
    p = normalize_anysearch_paper({"title": "Official standard", "source_type": "standard", "url": "https://agency.example/standard"})
    response = Response(body="PDF" * 2_000_000, headers={"Content-Type": "application/pdf"})
    session = SimpleNamespace(get=Mock(return_value=response))
    manager = SimpleNamespace(register_discovered_papers=Mock(), get_paper_raw_markdown=Mock(return_value="Actual parsed standard requirements."))
    result = SourceReader(manager, tmp_path, session=session).read(p)
    assert result["reading_status"] == "completed" and result["reading_mode"] == "fulltext"
    parsed = manager.get_paper_raw_markdown.call_args.args[0]
    assert parsed["openAccessPdf"]["url"] == p["url"] and response.closed


def test_blocked_source_is_not_rescheduled_without_new_routes_even_across_resume(tmp_path):
    candidate = paper(20)
    client = SimpleNamespace(search=Mock(return_value=SearchResult([candidate], "success")))

    def read(value):
        return {"reading_status": "unavailable", "retry": {"policy": "when_source_changes",
            "route_fingerprint": source_route_fingerprint(value), "access_context_generation": "anonymous-v1",
            "reader_revision": SOURCE_READER_REVISION}}

    reader = Mock(side_effect=read)
    runner(tmp_path, client, reader, state=state(need(read_limit=1)), settings={"max_rounds": 2}).run(phase="survey", task={})
    saved = load_history(tmp_path / "search.json")
    assert reader.call_count == 1 and saved["budget"]["acquisitions"] == 1
    assert saved["reads"][candidate["paperId"]]["deferred_reason"] == "unchanged_source_routes"
    runner(tmp_path, client, reader, settings={"max_rounds": 2}).run(phase="survey", task={})
    assert reader.call_count == 1


def test_new_download_route_reopens_paper_after_attempt_limit_without_resetting_budget(tmp_path):
    candidate = paper(21)
    client = SimpleNamespace(search=Mock(return_value=SearchResult([candidate], "success")))
    reader = Mock(side_effect=[{"reading_status": "unavailable"}, reference(candidate)])
    runner(tmp_path, client, reader, state=state(need(read_limit=1)), settings={"checkpoint_attempts": 1}).run(phase="survey", task={})
    saved = load_history(tmp_path / "search.json")
    saved["queries"][0]["papers"][0]["openAccessPdf"] = {"url": "https://repository.example/new.pdf"}
    (tmp_path / "search.json").write_text(json.dumps(saved))
    result = runner(tmp_path, client, reader, settings={"checkpoint_attempts": 1}).run(phase="survey", task={})
    saved = load_history(tmp_path / "search.json")
    assert len(result["references"]) == 1 and reader.call_count == 2
    assert saved["budget"]["acquisitions"] == 2
    assert saved["reads"][candidate["paperId"]]["attempts"] == 2


def test_blocked_reading_is_shared_across_phases_but_access_context_change_reopens_it(tmp_path):
    candidate = paper(22)
    retry = {"policy": "when_source_changes", "route_fingerprint": source_route_fingerprint(candidate),
             "access_context_generation": "anonymous-v1", "reader_revision": SOURCE_READER_REVISION}
    inherited = {"reads": {candidate["paperId"]: {"paper": candidate, "status": "unavailable", "attempts": 2,
        "reference": {"reading_status": "unavailable", "retry": retry}, "attempt_fingerprint": retry["route_fingerprint"]}}}
    client = SimpleNamespace(search=Mock(return_value=SearchResult([candidate], "success")))
    reader = Mock(return_value=reference(candidate))
    result = runner(tmp_path, client, reader, state=state(need(read_limit=1)), inherited=[inherited]).run(phase="candidate", task={})
    assert result["references"] == []
    reader.assert_not_called()
    result = runner(tmp_path, client, reader, settings={"access_context_generation": "institutional-v2"}).run(phase="candidate", task={})
    assert len(result["references"]) == 1 and reader.call_count == 1
    assert load_history(tmp_path / "search.json")["budget"]["acquisitions"] == 1
