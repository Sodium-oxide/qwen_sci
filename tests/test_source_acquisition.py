import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import requests

from src.agents.survey_agent.modules.fulltext_resolution import public_repository_route, resolve_declared_pdf_links
from src.pipeline.anysearch import identity_keys, merge_papers, normalize_anysearch_paper, source_identifiers
from src.pipeline.scholarly_metadata import parse_repository_jats, resolve_biomedical_metadata
from src.pipeline.source_reader import SourceReader
from src.pipeline.source_retry import source_route_fingerprint


class Response:
    def __init__(self, body="", status=200, content_type="text/html"):
        self.body, self.status_code = body, status
        self.headers = {"Content-Type": content_type}
        self.encoding = "utf-8"
        self.closed = False

    def raise_for_status(self):
        if self.status_code >= 400:
            response = requests.Response()
            response.status_code = self.status_code
            raise requests.HTTPError(str(self.status_code), response=response)

    def iter_content(self, chunk_size=65536):
        yield self.body.encode()

    def close(self):
        self.closed = True


def metadata(**overrides):
    return {"resultList": {"result": [{"source": "MED", "id": "12345", "pmcid": "PMC98765", "doi": "10.1000/verified",
        "title": "Verified receptor mechanism", "pubYear": "2024", "abstractText": "<p>Actual abstract.</p>",
        "authorList": {"author": [{"fullName": "One Author"}]}, "journalInfo": {"journal": {"title": "Journal"}},
        "fullTextUrlList": {"fullTextUrl": [{"availabilityCode": "OA", "documentStyle": "pdf", "url": "https://repository.example/article.pdf"}]},
        **overrides}]}}


def jats(*, pmcid="98765", doi="10.1000/verified"):
    return f'<article article-type="research-article"><front><article-meta><article-id pub-id-type="pmc">{pmcid}</article-id>' \
        f'<article-id pub-id-type="pmid">12345</article-id><article-id pub-id-type="doi">{doi}</article-id>' \
        '<title-group><article-title>Verified receptor mechanism</article-title></title-group>' \
        '<abstract>Actual abstract.</abstract></article-meta></front><body><sec><title>Results</title><p>' \
        + "Actual measured receptor observations. " * 100 + '</p></sec></body></article>'


@pytest.mark.parametrize("url", ["https://pubmed.ncbi.nlm.nih.gov/12345/", "https://www.ncbi.nlm.nih.gov/pubmed/12345",
                                 "https://europepmc.org/article/MED/12345"])
def test_pubmed_identifiers_survive_normalization_and_merge(url):
    paper = normalize_anysearch_paper({"title": "Truncated title ...", "url": url})
    assert paper["externalIds"]["PubMed"] == "12345"
    canonical = {"paperId": "W123", "title": "Canonical title", "externalIds": {"PubMed": "12345", "DOI": "10.1000/verified"}}
    assert len(merge_papers([paper, canonical])) == 1
    assert "pmid:12345" in identity_keys(paper)
    assert not source_identifiers({"url": url.replace("https://", "https://untrusted.")})["pmid"]


def test_metadata_requires_exact_identifiers_and_retains_real_abstract_and_oa_routes():
    fetch = Mock(return_value=metadata())
    resolved = resolve_biomedical_metadata({"url": "https://pubmed.ncbi.nlm.nih.gov/12345/"}, fetch)
    assert "EXT_ID%3A12345" in fetch.call_args.args[0]
    assert resolved["doi"] == "10.1000/verified" and resolved["pmcid"] == "PMC98765"
    assert resolved["abstract"] == "Actual abstract."
    assert resolved["openalex_oa_locations"][0]["oa_evidence"] == "europepmc.OA"
    assert resolved["identity_provenance"][0]["identifiers"]["pmid"] == "12345"
    with pytest.raises(ValueError, match="matches"):
        resolve_biomedical_metadata({"pmid": "54321"}, fetch)
    with pytest.raises(ValueError, match="matches"):
        resolve_biomedical_metadata({"pmid": "12345", "doi": "10.1000/other"}, fetch)


def test_pubmed_403_falls_back_to_verified_metadata_and_repository_xml_with_alias_reuse(tmp_path):
    paper = normalize_anysearch_paper({"title": "Truncated title ...", "url": "https://pubmed.ncbi.nlm.nih.gov/12345/", "snippet": "UNVERIFIED"})

    def get(url, **kwargs):
        if "pubmed.ncbi.nlm.nih.gov" in url:
            return Response(status=403)
        if "/search?" in url:
            return Response(json.dumps(metadata()), content_type="application/json")
        assert url.endswith("/PMC98765/fullTextXML")
        return Response(jats(), content_type="application/xml")

    session = SimpleNamespace(get=Mock(side_effect=get))
    manager = SimpleNamespace(register_discovered_papers=Mock(), get_paper_raw_markdown=Mock())
    result = SourceReader(manager, tmp_path, session=session).read(paper)
    assert result["reading_status"] == "completed" and result["reading_mode"] == "fulltext_xml"
    assert result["title"] == "Verified receptor mechanism" and result["doi"] == "10.1000/verified"
    assert result["externalIds"]["PMCID"] == "PMC98765"
    assert "UNVERIFIED" not in result["keynote"]
    assert hashlib.sha256(Path(result["raw_source_path"]).read_bytes()).hexdigest() == result["raw_source_sha256"]
    assert result["source_article_type"] == "research-article"
    manager.get_paper_raw_markdown.assert_not_called()
    alias = normalize_anysearch_paper({"title": "Different displayed title", "doi": result["doi"]})
    reused = SourceReader(manager, tmp_path, session=session).read(alias)
    assert reused["paper_id"] == alias["paperId"] and reused["reused_from"] == paper["paperId"]
    assert session.get.call_count == 3
    assert len(merge_papers([paper, result, alias])) == 1


@pytest.mark.parametrize("body", [jats(pmcid="11111", doi="10.1000/other"), "<error>Unavailable</error>",
    '<!DOCTYPE article [<!ENTITY bad "unsafe">]><article><body>&bad;</body></article>',
    '<article><front><article-meta><article-id pub-id-type="pmc">98765</article-id></article-meta></front></article>'])
def test_repository_xml_rejects_wrong_identity_error_pages_and_missing_body(body):
    with pytest.raises(ValueError):
        parse_repository_jats(body, {"pmcid": "PMC98765", "doi": "10.1000/verified"})


def test_jats_namespace_and_external_doctype_do_not_require_network():
    body = '<!DOCTYPE article SYSTEM "https://unused.example/jats.dtd">' + jats().replace('<article ', '<article xmlns="urn:jats" ')
    assert "Actual measured" in parse_repository_jats(body, {"pmcid": "PMC98765"})["content"]


@pytest.mark.parametrize("url", ["https://pmc.ncbi.nlm.nih.gov/articles/PMC98765/",
                                 "https://www.biorxiv.org/content/10.1101/2023.04.19.537578v2.full-text"])
def test_anysearch_repository_pages_resolve_declared_pdf_without_source_relabeling(url):
    response = Response('<meta name="citation_pdf_url" content="/declared.pdf">')
    session = SimpleNamespace(get=Mock(return_value=response))
    result = resolve_declared_pdf_links({"kind": "landing_page", "source": "anysearch.oa_location", "url": url}, http_client=session)
    assert result["status"] == "pdf_links_found" and result["pdf_candidates"][0]["url"].endswith("/declared.pdf")
    assert result["pdf_candidates"][0]["source"] == "anysearch.oa_location.declared_pdf"
    assert session.get.call_count == 1


@pytest.mark.parametrize("url", ["https://pmc.ncbi.nlm.nih.gov.evil.example/articles/PMC98765/",
                                 "https://www.biorxiv.org/account", "https://publisher.example/article"])
def test_anysearch_label_alone_does_not_enable_arbitrary_landing_recovery(url):
    session = SimpleNamespace(get=Mock())
    result = resolve_declared_pdf_links({"kind": "landing_page", "source": "anysearch.oa_location", "url": url}, http_client=session)
    assert result["status"] == "landing_recovery_not_permitted"
    session.get.assert_not_called()


def test_biorxiv_html_retains_requested_version(tmp_path):
    url = "https://www.biorxiv.org/content/10.1101/2023.04.19.537578v2.full-text"
    html = '<html><meta name="citation_doi" content="10.1101/2023.04.19.537578"><article>' + "Actual experiment. " * 200 + '</article></html>'
    session = SimpleNamespace(get=Mock(return_value=Response(html)))
    paper = normalize_anysearch_paper({"title": "Preprint", "source_type": "preprint", "url": url})
    result = SourceReader(None, tmp_path, session=session).read(paper)
    assert result["reading_mode"] == "fulltext_html" and result["version"] == "v2"
    assert public_repository_route(url)["version"] == "v2"


@pytest.mark.parametrize("change", ["new_url", "access_context"])
def test_access_denial_checkpoint_skips_unchanged_routes_and_reopens_for_changes(tmp_path, change):
    paper = normalize_anysearch_paper({"title": "Source", "url": "https://publisher.example/article"})
    session = SimpleNamespace(get=Mock(return_value=Response(status=403)))
    parser = Mock(side_effect=ValueError("missing"))
    coordinator = SimpleNamespace(access_context_generation="anonymous-v1")
    manager = SimpleNamespace(register_discovered_papers=Mock(), get_paper_raw_markdown=parser,
                              fulltext_download_coordinator=coordinator, get_paper_title_abstract=Mock(side_effect=ValueError("missing")))
    first = SourceReader(manager, tmp_path, session=session).read(paper)
    assert first["retry"]["policy"] == "when_source_changes"
    second = SourceReader(manager, tmp_path, session=session).read(paper)
    assert second["retry_skipped"] and session.get.call_count == parser.call_count == 1
    if change == "new_url":
        paper["openAccessPdf"] = {"url": "https://repository.example/new.pdf"}
        assert source_route_fingerprint(paper) != first["retry"]["route_fingerprint"]
    else:
        coordinator.access_context_generation = "institutional-v2"
    parser.side_effect = None
    parser.return_value = "Actually parsed article text."
    third = SourceReader(manager, tmp_path, session=session).read(paper)
    assert third["reading_status"] == "completed" and parser.call_count == 2


def test_transient_source_failures_remain_retryable(tmp_path):
    paper = normalize_anysearch_paper({"title": "Source", "url": "https://publisher.example/article"})
    session = SimpleNamespace(get=Mock(side_effect=requests.Timeout()))
    first = SourceReader(None, tmp_path, session=session).read(paper)
    assert first["retry"]["policy"] == "retry"
    SourceReader(None, tmp_path, session=session).read(paper)
    assert session.get.call_count == 2


def test_failed_xml_identity_does_not_enter_reading_results(tmp_path):
    paper = normalize_anysearch_paper({"title": "Source", "doi": "10.1000/verified", "externalIds": {"PMCID": "PMC98765"}})
    session = SimpleNamespace(get=Mock(side_effect=[Response(jats(pmcid="11111", doi="10.1000/other"), content_type="application/xml"), Response(status=403)]))
    result = SourceReader(None, tmp_path, session=session).read(paper)
    assert result["reading_status"] == "unavailable" and "keynote" not in result
    assert not list(tmp_path.glob("*.jats.xml"))


def test_requested_preprint_version_invalidates_same_id_reading_cache(tmp_path):
    base = "https://www.biorxiv.org/content/10.1101/2023.04.19.537578"
    first = normalize_anysearch_paper({"title": "Preprint", "url": base + "v1.full-text"})
    second = normalize_anysearch_paper({"title": "Preprint", "url": base + "v2.full-text"})
    assert first["paperId"] == second["paperId"]
    html = '<html><meta name="citation_doi" content="10.1101/2023.04.19.537578"><article>' + "Actual experiment. " * 200 + '</article></html>'
    session = SimpleNamespace(get=Mock(side_effect=[Response(html), Response(html)]))
    assert SourceReader(None, tmp_path, session=session).read(first)["version"] == "v1"
    assert SourceReader(None, tmp_path, session=session).read(second)["version"] == "v2"
    assert session.get.call_count == 2


def test_shared_http_budget_covers_metadata_and_xml_and_does_not_create_permanent_failure(tmp_path):
    from src.pipeline.adaptive_search import acquisition_scope
    paper = normalize_anysearch_paper({"title": "Source", "url": "https://pubmed.ncbi.nlm.nih.gov/12345/"})
    session = SimpleNamespace(get=Mock(side_effect=[Response(status=403), Response(json.dumps(metadata()), content_type="application/json")]))
    requests_reserved = []

    def reserve(kind):
        requests_reserved.append(kind)
        return len(requests_reserved) <= 2

    with acquisition_scope(reserve):
        result = SourceReader(None, tmp_path, session=session).read(paper, allow_abstract_fallback=False)
    assert result["reading_status"] == "unavailable" and result["retry"]["policy"] == "retry"
    assert session.get.call_count == 2 and len(requests_reserved) > 2
    assert "budget_exhausted" in result["retry"]["reasons"]


def test_pdf_failure_report_is_propagated_to_source_retry_state(tmp_path):
    paper = normalize_anysearch_paper({"title": "Source", "doi": "10.1000/verified", "pdf_url": "https://repository.example/source.pdf"})
    manager = SimpleNamespace(register_discovered_papers=Mock(), get_paper_raw_markdown=Mock(side_effect=ValueError("missing")),
        get_fulltext_acquisition_report=Mock(return_value={"attempts": [{"status": "access_denied", "http_status": 403, "url": paper["openAccessPdf"]["url"]}]}))
    result = SourceReader(manager, tmp_path).read(paper)
    assert result["retry"]["policy"] == "when_source_changes"
    assert result["source_attempts"][0]["http_status"] == 403
