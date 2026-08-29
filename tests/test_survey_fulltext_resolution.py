import json
import os
import sys
import threading
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SURVEY_AGENT_ROOT = os.path.join(PROJECT_ROOT, "src", "agents", "survey_agent")
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, SURVEY_AGENT_ROOT)

from modules import data_manager, fulltext_resolution
from modules.data_manager import DataManager
from modules.fulltext_download_cache import FulltextDownloadCoordinator, normalize_download_url
from utils import api_call
from utils.api_call import UnpaywallAPI


class _Logger:
    def info(self, *_args, **_kwargs):
        pass

    def warning(self, *_args, **_kwargs):
        pass

    def error(self, *_args, **_kwargs):
        pass


class _JsonResponse:
    def __init__(self, payload, status_code=200):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


class _StreamResponse:
    def __init__(self, status_code, body=b"", *, url="", content_type="application/pdf", headers=None):
        self.status_code = status_code
        self._body = body
        self.url = url
        self.headers = {"Content-Type": content_type, "Content-Length": str(len(body))}
        self.headers.update(headers or {})
        self.closed = False

    def iter_content(self, chunk_size=1024):
        del chunk_size
        if self._body:
            yield self._body

    def close(self):
        self.closed = True


def _api_config():
    return SimpleNamespace(
        APIInfo=SimpleNamespace(
            unpaywall_base_url="https://api.unpaywall.org/v2",
            unpaywall_email="researcher@example.org",
            unpaywall_timeout=30,
        )
    )


def _manager(tmp_path, candidates):
    manager = object.__new__(DataManager)
    manager.cache_path = str(tmp_path)
    manager.logger = _Logger()
    manager.config = SimpleNamespace(
        BasicInfo=SimpleNamespace(debug=False, base_dir=str(tmp_path)),
        ModuleInfo=SimpleNamespace(
            WorkCollector=SimpleNamespace(download_safe_mode=False, download_timeout=5),
        ),
    )
    manager.unpaywall_api = SimpleNamespace(
        normalize_doi=UnpaywallAPI.normalize_doi,
        get_oa_candidates=lambda _doi: list(candidates),
    )
    manager.fulltext_download_coordinator = FulltextDownloadCoordinator(
        str(tmp_path), manager.config.ModuleInfo.WorkCollector, logger=manager.logger
    )
    manager._fulltext_artifact_lock = threading.RLock()
    return manager


def _paper():
    return {
        "paperId": "W123",
        "api_platform": "openalex",
        "title": "A full-text acquisition test paper",
        "externalIds": {"DOI": "10.1000/fulltext-test"},
    }


def test_unpaywall_returns_all_locations_as_provenance_rich_candidates(monkeypatch):
    def fake_get(_url, **_kwargs):
        return _JsonResponse(
            {
                "best_oa_location": {
                    "url_for_pdf": "https://repo.example/best.pdf",
                    "url_for_landing_page": "https://repo.example/best-record",
                    "host_type": "repository",
                    "version": "acceptedVersion",
                    "license": "cc-by",
                },
                "oa_locations": [
                    {
                        "url_for_pdf": "https://other.example/author.pdf",
                        "url_for_landing_page": "https://other.example/author-record",
                        "host_type": "repository",
                        "version": "submittedVersion",
                    }
                ],
            }
        )

    monkeypatch.setattr(api_call.requests, "get", fake_get)

    candidates = UnpaywallAPI(_api_config()).get_oa_candidates("10.1000/fulltext-test")

    assert [(item["source"], item["kind"], item["priority"]) for item in candidates] == [
        ("unpaywall.best_oa_location", "pdf", 0),
        ("unpaywall.best_oa_location", "landing_page", 1),
        ("unpaywall.oa_locations", "pdf", 10),
        ("unpaywall.oa_locations", "landing_page", 11),
    ]
    assert candidates[0]["version"] == "acceptedVersion"
    assert candidates[0]["license"] == "cc-by"
    assert "researcher@example.org" not in json.dumps(candidates)


def test_unpaywall_oa_resolution_is_cached_with_configured_ttl(monkeypatch, tmp_path):
    config = _api_config()
    config.BasicInfo = SimpleNamespace(cache_path=str(tmp_path))
    config.ModuleInfo = SimpleNamespace(
        WorkCollector=SimpleNamespace(fulltext_oa_resolution_cache_ttl_seconds=60)
    )
    calls = 0

    def fake_get(_url, **_kwargs):
        nonlocal calls
        calls += 1
        return _JsonResponse(
            {"best_oa_location": {"url_for_pdf": "https://repo.example/cached.pdf"}}
        )

    monkeypatch.setattr(api_call.requests, "get", fake_get)
    client = UnpaywallAPI(config)

    first = client.get_oa_candidates("10.1000/cached")
    second = client.get_oa_candidates("https://doi.org/10.1000/cached")

    assert calls == 1
    assert first == second


def test_candidate_deduplication_preserves_case_sensitive_paths_and_signed_queries():
    resolution = fulltext_resolution.resolve_fulltext_candidates(
        {
            "paperId": "W-case",
            "doi": "10.1000/case",
        },
        unpaywall_api=SimpleNamespace(
            normalize_doi=UnpaywallAPI.normalize_doi,
            get_oa_candidates=lambda _doi: [
                {
                    "url": "https://REPO.example/File.pdf?Signature=ABC",
                    "kind": "pdf",
                    "source": "unpaywall.best_oa_location",
                    "priority": 0,
                },
                {
                    "url": "https://repo.example/File.pdf?Signature=abc",
                    "kind": "pdf",
                    "source": "unpaywall.oa_locations",
                    "priority": 10,
                },
                {
                    "url": "https://repo.example/file.pdf?Signature=ABC",
                    "kind": "pdf",
                    "source": "metadata.repository",
                    "priority": 120,
                },
            ],
        ),
    )

    assert [candidate["url"] for candidate in resolution["candidates"]] == [
        "https://repo.example/File.pdf?Signature=ABC",
        "https://repo.example/File.pdf?Signature=abc",
        "https://doi.org/10.1000/case",
        "https://repo.example/file.pdf?Signature=ABC",
    ]


def test_metadata_and_pmc_routes_pass_download_preflight(tmp_path):
    manager = _manager(tmp_path, [])
    metadata_paper = {
        "paperId": "W-repository",
        "repository_pdf": "https://repository.example.edu/paper.pdf",
    }
    pmc_paper = {
        "paperId": "W-pmc",
        "externalIds": {"PMCID": "PMC123456"},
    }
    openalex_location_paper = {
        "paperId": "W-openalex-location",
        "openalex_oa_locations": [
            {
                "source": "openalex.oa_locations",
                "landing_page_url": "https://repository.example.edu/record/123",
            }
        ],
    }

    assert manager._has_pdf_download_candidate(metadata_paper) is True
    assert manager._has_pdf_download_candidate(pmc_paper) is True
    assert manager._has_pdf_download_candidate(openalex_location_paper) is True
    metadata_info = manager._prepare_download_info(metadata_paper)
    pmc_info = manager._prepare_download_info(pmc_paper)
    assert metadata_info[1][0]["source"] == "metadata.repository"
    assert pmc_info[1][0]["source"] == "identifier.pmc"
    assert pmc_info[1][0]["url"].endswith("/PMC123456/pdf/")


def test_generic_metadata_urls_are_provenance_rich_and_non_oa_landings_are_disabled():
    unpaywall = SimpleNamespace(
        normalize_doi=UnpaywallAPI.normalize_doi,
        get_oa_candidates=lambda _doi: [
            {
                "url": "https://repository.example/unpaywall.pdf",
                "kind": "pdf",
                "source": "unpaywall.best_oa_location",
                "priority": 0,
            }
        ],
    )
    resolution = fulltext_resolution.resolve_fulltext_candidates(
        {
            "paperId": "W-generic",
            "doi": "10.1000/generic",
            "open_access": {"is_oa": True},
            "pdf_url": "https://metadata.example/direct.pdf",
            "full_text_url": "https://repository.example/record/123",
        },
        unpaywall_api=unpaywall,
    )

    assert [candidate["source"] for candidate in resolution["candidates"]] == [
        "unpaywall.best_oa_location",
        "doi.landing_fallback",
        "metadata.pdf_url",
        "metadata.full_text_url",
    ]
    generic_pdf = resolution["candidates"][2]
    assert generic_pdf["kind"] == "pdf"
    assert generic_pdf["metadata_field"] == "pdf_url"
    assert generic_pdf["oa_evidence"] == "metadata.open_access.is_oa"
    assert resolution["candidates"][3]["kind"] == "landing_page"

    without_oa = fulltext_resolution.resolve_fulltext_candidates(
        {
            "paperId": "W-no-oa",
            "full_text_url": "https://publisher.example/article/123",
        },
        unpaywall_api=unpaywall,
    )
    assert without_oa["candidates"] == []
    assert without_oa["disabled_candidates"] == [
        {
            "url": "https://publisher.example/article/123",
            "kind": "landing_page",
            "source": "metadata.full_text_url",
            "priority": 131,
            "metadata_field": "full_text_url",
            "status": "landing_recovery_requires_explicit_oa",
        }
    ]


def test_openalex_oa_locations_add_direct_and_landing_candidates():
    resolution = fulltext_resolution.resolve_fulltext_candidates(
        {
            "paperId": "W-openalex-locations",
            "openalex_oa_locations": [
                {
                    "source": "openalex.best_oa_location",
                    "priority": 30,
                    "pdf_url": "https://repository.example/best.pdf",
                    "landing_page_url": "https://repository.example/best",
                    "version": "acceptedVersion",
                    "license": "cc-by",
                    "host_type": "repository",
                },
                {
                    "source": "openalex.oa_locations",
                    "priority": 40,
                    "landing_page_url": "https://repository.example/other",
                    "version": "submittedVersion",
                },
            ],
        },
        unpaywall_api=SimpleNamespace(
            normalize_doi=UnpaywallAPI.normalize_doi,
            get_oa_candidates=lambda _doi: [],
        ),
    )

    assert [(item["source"], item["kind"], item["priority"]) for item in resolution["candidates"]] == [
        ("openalex.best_oa_location", "pdf", 30),
        ("openalex.best_oa_location", "landing_page", 30),
        ("openalex.oa_locations", "landing_page", 40),
    ]
    assert resolution["candidates"][0]["license"] == "cc-by"
    assert resolution["candidates"][1]["oa_evidence"] == "openalex.oa_location"


def test_openalex_oa_landing_page_permits_explicit_download_anchor(monkeypatch):
    html = b"""
        <html><body>
          <a href='/download?id=123&amp;format=pdf' download aria-label='Download accepted manuscript PDF'>PDF</a>
        </body></html>
    """
    monkeypatch.setattr(
        fulltext_resolution.requests,
        "get",
        lambda *_args, **_kwargs: _StreamResponse(
            200,
            html,
            url="https://repository.example.edu/record/123",
            content_type="text/html; charset=utf-8",
        ),
    )

    outcome = fulltext_resolution.resolve_declared_pdf_links(
        {
            "url": "https://repository.example.edu/record/123",
            "kind": "landing_page",
            "source": "openalex.oa_locations",
            "priority": 40,
        }
    )

    assert outcome["status"] == "pdf_links_found"
    assert outcome["pdf_candidates"][0]["url"] == "https://repository.example.edu/download?id=123&format=pdf"


def test_full_pdf_response_restarts_instead_of_appending_to_a_partial_file(monkeypatch, tmp_path):
    manager = _manager(tmp_path, [])
    pdf_path = tmp_path / "paper.pdf"
    partial_path = Path(f"{pdf_path}.part")
    partial_path.write_bytes(b"%PDF-old-partial")
    monkeypatch.setattr(
        data_manager.requests,
        "get",
        lambda *_args, **_kwargs: _StreamResponse(
            200,
            b"%PDF-new-complete",
            url="https://repository.example/paper.pdf",
        ),
    )

    attempt = manager._download_pdf_with_resume(
        "https://repository.example/paper.pdf",
        str(pdf_path),
        "test paper",
        return_attempt=True,
    )

    assert attempt["downloaded"] is True
    assert pdf_path.read_bytes() == b"%PDF-new-complete"
    assert not partial_path.exists()


def test_doi_landing_recovery_is_redirect_bounded_and_discovers_only_declared_pdf(monkeypatch):
    seen_urls = []

    def fake_get(url, **kwargs):
        seen_urls.append((url, kwargs.get("allow_redirects")))
        if url == "https://doi.org/10.1000/doi-fallback":
            return _StreamResponse(
                302,
                url=url,
                headers={"Location": "https://repository.example/record/123"},
            )
        assert url == "https://repository.example/record/123"
        return _StreamResponse(
            200,
            b"<meta name='citation_pdf_url' content='/bitstream/123/paper.pdf'>",
            url=url,
            content_type="text/html",
        )

    monkeypatch.setattr(fulltext_resolution.requests, "get", fake_get)
    outcome = fulltext_resolution.resolve_declared_pdf_links(
        {
            "url": "https://doi.org/10.1000/doi-fallback",
            "kind": "landing_page",
            "source": "doi.landing_fallback",
            "oa_evidence": "unpaywall.oa_location",
            "priority": 20,
        },
        max_redirects=3,
    )

    assert seen_urls == [
        ("https://doi.org/10.1000/doi-fallback", False),
        ("https://repository.example/record/123", False),
    ]
    assert outcome["status"] == "pdf_links_found"
    assert outcome["redirect_count"] == 1
    assert outcome["pdf_candidates"] == [
        {
            "url": "https://repository.example/bitstream/123/paper.pdf",
            "kind": "pdf",
            "source": "doi.landing_fallback.declared_pdf",
            "priority": 20,
            "version": "",
            "license": "",
            "host_type": "",
        }
    ]


def test_doi_landing_fallback_runs_after_unpaywall_and_before_generic_metadata(monkeypatch, tmp_path):
    candidates = [
        {
            "url": "https://repository.example/unpaywall.pdf",
            "kind": "pdf",
            "source": "unpaywall.best_oa_location",
            "priority": 0,
        }
    ]
    manager = _manager(tmp_path, candidates)
    paper = {
        **_paper(),
        "pdf_url": "https://metadata.example/fallback.pdf",
    }
    seen_urls = []

    def fake_get(url, **_kwargs):
        seen_urls.append(url)
        if url == "https://repository.example/unpaywall.pdf":
            return _StreamResponse(404, b"missing", url=url, content_type="text/html")
        if url == "https://doi.org/10.1000/fulltext-test":
            return _StreamResponse(
                302,
                url=url,
                headers={"Location": "https://repository.example/record/doi"},
            )
        if url == "https://repository.example/record/doi":
            return _StreamResponse(
                200,
                b"<meta name='citation_pdf_url' content='/bitstream/doi-paper.pdf'>",
                url=url,
                content_type="text/html",
            )
        if url == "https://repository.example/bitstream/doi-paper.pdf":
            return _StreamResponse(200, b"%PDF-from-doi", url=url)
        pytest.fail(f"Unexpected request: {url}")

    monkeypatch.setattr(data_manager.requests, "get", fake_get)
    monkeypatch.setattr(
        data_manager,
        "is_valid_pdf",
        lambda path: Path(path).read_bytes().startswith(b"%PDF-") if Path(path).exists() else False,
    )

    paper_id, pdf_path = manager._download_single_paper(paper, 1, 1)

    assert paper_id == "W123"
    assert Path(pdf_path).read_bytes() == b"%PDF-from-doi"
    assert seen_urls == [
        "https://repository.example/unpaywall.pdf",
        "https://doi.org/10.1000/fulltext-test",
        "https://repository.example/record/doi",
        "https://repository.example/bitstream/doi-paper.pdf",
    ]
    provenance = json.loads((tmp_path / "fulltext_provenance" / "W123.json").read_text(encoding="utf-8"))
    assert [attempt["source"] for attempt in provenance["attempts"]] == [
        "unpaywall.best_oa_location",
        "doi.landing_fallback",
        "doi.landing_fallback.declared_pdf",
    ]
    assert provenance["outcome"]["selected_source"] == "doi.landing_fallback.declared_pdf"


def test_doi_landing_fallback_runs_after_a_denied_unpaywall_candidate(monkeypatch, tmp_path):
    manager = _manager(
        tmp_path,
        [
            {
                "url": "https://publisher.example/restricted.pdf",
                "kind": "pdf",
                "source": "unpaywall.best_oa_location",
                "priority": 0,
            }
        ],
    )
    paper = {**_paper(), "pdf_url": "https://repository.example/available.pdf"}
    seen_urls = []

    def fake_get(url, **_kwargs):
        seen_urls.append(url)
        if url == "https://publisher.example/restricted.pdf":
            return _StreamResponse(403, b"denied", url=url, content_type="text/html")
        if url == "https://doi.org/10.1000/fulltext-test":
            return _StreamResponse(
                302,
                url=url,
                headers={"Location": "https://repository.example/record/available"},
            )
        if url == "https://repository.example/record/available":
            return _StreamResponse(
                200,
                b"<meta name='citation_pdf_url' content='/download/available.pdf'>",
                url=url,
                content_type="text/html",
            )
        if url == "https://repository.example/download/available.pdf":
            return _StreamResponse(200, b"%PDF-from-doi", url=url)
        pytest.fail(f"Unexpected request: {url}")

    monkeypatch.setattr(data_manager.requests, "get", fake_get)
    monkeypatch.setattr(
        data_manager,
        "is_valid_pdf",
        lambda path: Path(path).read_bytes().startswith(b"%PDF-") if Path(path).exists() else False,
    )

    paper_id, pdf_path = manager._download_single_paper(paper, 1, 1)

    assert paper_id == "W123"
    assert Path(pdf_path).read_bytes() == b"%PDF-from-doi"
    assert seen_urls == [
        "https://publisher.example/restricted.pdf",
        "https://doi.org/10.1000/fulltext-test",
        "https://repository.example/record/available",
        "https://repository.example/download/available.pdf",
    ]
    provenance = json.loads((tmp_path / "fulltext_provenance" / "W123.json").read_text(encoding="utf-8"))
    assert [attempt["source"] for attempt in provenance["attempts"]] == [
        "unpaywall.best_oa_location",
        "doi.landing_fallback",
        "doi.landing_fallback.declared_pdf",
    ]
    assert provenance["outcome"]["selected_source"] == "doi.landing_fallback.declared_pdf"


def test_empty_unpaywall_resolution_is_preserved_in_fulltext_provenance(tmp_path):
    manager = _manager(tmp_path, [])

    paper_id, pdf_path = manager._download_single_paper(_paper(), 1, 1)

    assert (paper_id, pdf_path) == (None, None)
    provenance = json.loads(
        (tmp_path / "fulltext_provenance" / "W123.json").read_text(encoding="utf-8")
    )
    assert provenance["resolution"]["unpaywall"]["status"] == "no_open_access_location"
    assert provenance["outcome"]["status"] == "no_open_access_candidate"


def test_landing_recovery_rejects_non_oa_publisher_route_without_http(monkeypatch):
    monkeypatch.setattr(
        fulltext_resolution.requests,
        "get",
        lambda *_args, **_kwargs: pytest.fail("publisher landing page must not be fetched"),
    )

    outcome = fulltext_resolution.resolve_declared_pdf_links(
        {
            "url": "https://publisher.example/article",
            "kind": "landing_page",
            "source": "publisher.doi",
        }
    )

    assert outcome == {"status": "landing_recovery_not_permitted", "pdf_candidates": []}


def test_persistent_download_cache_redacts_signed_and_redirect_query_urls(tmp_path):
    coordinator = FulltextDownloadCoordinator(
        str(tmp_path), SimpleNamespace(fulltext_access_context_generation="anonymous-v1")
    )
    raw_url = "https://repository.example.edu/paper.pdf?X-Amz-Signature=SECRET"
    final_url = "https://login.example.edu/callback?state=PRIVATE"

    coordinator.execute(
        url=raw_url,
        kind="pdf",
        destination_path=str(tmp_path / "unused.pdf"),
        validator=lambda _path: False,
        operation=lambda: {
            "downloaded": False,
            "status": "access_denied",
            "requested_url": raw_url,
            "final_url": final_url,
            "http_status": 403,
            "content_type": "text/html",
        },
    )

    cache_entry = coordinator._cache.get(
        coordinator._url_cache_key(normalize_download_url(raw_url))
    )
    persisted = json.dumps(cache_entry, sort_keys=True)
    assert "SECRET" not in persisted
    assert "PRIVATE" not in persisted
    assert "X-Amz-Signature" not in persisted
    assert "state=" not in persisted


def test_landing_page_discovers_only_declared_pdf_links(monkeypatch):
    html = b"""
        <html><head>
          <meta name='citation_pdf_url' content='/bitstream/123/paper.pdf'>
          <link rel='alternate' type='application/pdf' href='/download/alternative.pdf'>
        </head><body><a href='/files/supplement.pdf'>Supplement</a></body></html>
    """
    monkeypatch.setattr(
        fulltext_resolution.requests,
        "get",
        lambda *_args, **_kwargs: _StreamResponse(
            200,
            html,
            url="https://repository.example.edu/record/123",
            content_type="text/html; charset=utf-8",
        ),
    )

    outcome = fulltext_resolution.resolve_declared_pdf_links(
        {
            "url": "https://repository.example.edu/record/123",
            "kind": "landing_page",
            "source": "unpaywall.oa_locations",
            "priority": 10,
            "version": "acceptedVersion",
        }
    )

    assert outcome["status"] == "pdf_links_found"
    assert [item["url"] for item in outcome["pdf_candidates"]] == [
        "https://repository.example.edu/bitstream/123/paper.pdf",
        "https://repository.example.edu/download/alternative.pdf",
    ]
    assert all(item["source"] == "unpaywall.oa_locations.declared_pdf" for item in outcome["pdf_candidates"])


@pytest.mark.parametrize(
    ("status_code", "content_type", "body", "expected_status"),
    [
        (404, "text/html", b"not found", "not_found"),
        (403, "text/html", b"access denied", "access_denied"),
    ],
)
def test_landing_page_classifies_not_found_and_access_denied(
    monkeypatch, status_code, content_type, body, expected_status
):
    monkeypatch.setattr(
        fulltext_resolution.requests,
        "get",
        lambda *_args, **_kwargs: _StreamResponse(
            status_code,
            body,
            url="https://repository.example.edu/record/123",
            content_type=content_type,
        ),
    )

    outcome = fulltext_resolution.resolve_declared_pdf_links(
        {
            "url": "https://repository.example.edu/record/123",
            "kind": "landing_page",
            "source": "unpaywall.oa_locations",
            "priority": 10,
        }
    )

    assert outcome["status"] == expected_status
    assert outcome["http_status"] == status_code
    assert outcome["pdf_candidates"] == []


@pytest.mark.parametrize(
    ("first_response", "expected_status"),
    [
        (_StreamResponse(404, b"not found", url="https://repo.example/missing.pdf", content_type="text/html"), "not_found"),
        (_StreamResponse(403, b"access denied", url="https://publisher.example/blocked.pdf", content_type="text/html"), "access_denied"),
        (_StreamResponse(200, b"<html>sign in</html>", url="https://publisher.example/login", content_type="text/html"), "non_pdf"),
    ],
)
def test_download_attempt_failure_is_provenanced_then_next_oa_candidate_succeeds(
    monkeypatch, tmp_path, first_response, expected_status
):
    candidates = [
        {
            "url": "https://first.example/paper.pdf",
            "kind": "pdf",
            "source": "unpaywall.best_oa_location",
            "priority": 0,
        },
        {
            "url": "https://repository.example/accepted.pdf",
            "kind": "pdf",
            "source": "unpaywall.oa_locations",
            "priority": 10,
        },
    ]
    manager = _manager(tmp_path, candidates)
    responses = [first_response, _StreamResponse(200, b"%PDF-minimal", url="https://repository.example/accepted.pdf")]

    def fake_get(*_args, **_kwargs):
        return responses.pop(0)

    monkeypatch.setattr(data_manager.requests, "get", fake_get)
    monkeypatch.setattr(
        data_manager,
        "is_valid_pdf",
        lambda path: Path(path).read_bytes().startswith(b"%PDF-") if Path(path).exists() else False,
    )

    paper_id, pdf_path = manager._download_single_paper(_paper(), 1, 1)

    assert paper_id == "W123"
    assert Path(pdf_path).read_bytes() == b"%PDF-minimal"
    provenance = json.loads((tmp_path / "fulltext_provenance" / "W123.json").read_text(encoding="utf-8"))
    assert provenance["attempts"][0]["status"] == expected_status
    assert provenance["attempts"][1]["status"] == "downloaded_response"
    assert provenance["outcome"]["status"] == "downloaded"
    assert provenance["outcome"]["selected_source"] == "unpaywall.oa_locations"


def test_fulltext_failure_is_written_to_sh_and_graph_artifacts_without_mutating_semantics(
    monkeypatch, tmp_path
):
    candidates = [
        {
            "url": "https://publisher.example/blocked.pdf",
            "kind": "pdf",
            "source": "unpaywall.best_oa_location",
            "priority": 0,
        },
        {
            "url": "https://openalex-content.example/blocked.pdf",
            "kind": "pdf",
            "source": "openalex.open_access_pdf",
            "priority": 140,
        },
    ]
    manager = _manager(tmp_path, candidates)
    selected_paper = {
        **_paper(),
        "sh_semantic_assessments": [
            {
                "sub_hypothesis_id": "SH1",
                "overall_relation": "partial",
                "seed_tier": "exploration",
                "graph_expansion_eligible": True,
            }
        ],
        "sh_matches": [
            {
                "sub_hypothesis_id": "SH1",
                "semantic_assessment": {
                    "overall_relation": "partial",
                    "seed_tier": "exploration",
                },
            }
        ],
    }
    semantic_before = deepcopy(
        {
            "sh_semantic_assessments": selected_paper["sh_semantic_assessments"],
            "sh_matches": selected_paper["sh_matches"],
        }
    )
    graph_annotation = {
        "schema_version": "sh_node_annotation_v1",
        "sub_hypothesis_id": "SH1",
        "evidence_use_mode": "QUALIFIED_SH_CONTRIBUTION",
        "graph_expansion_mode": "exploration",
    }
    manager.config.BasicInfo.subhypothesis_retrieval = {
        "candidate_papers": [selected_paper],
        "seed_selection": {"selected_papers": [selected_paper]},
    }
    manager.config.BasicInfo.sh_graph_provenance = {
        "schema_version": "sh_graph_provenance_v1",
        "paper_annotations": {"W123": [deepcopy(graph_annotation)]},
        "graph_expansion_records": [],
    }

    responses = [
        _StreamResponse(403, b"denied", url="https://publisher.example/login", content_type="text/html"),
        _StreamResponse(403, b"denied", url="https://openalex-content.example/login", content_type="text/html"),
    ]
    monkeypatch.setattr(data_manager.requests, "get", lambda *_args, **_kwargs: responses.pop(0))

    paper_id, pdf_path = manager._download_single_paper(selected_paper, 1, 1)

    assert (paper_id, pdf_path) == (None, None)
    summary = manager.config.BasicInfo.subhypothesis_retrieval[
        "fulltext_acquisition_by_paper"
    ]["W123"]
    assert summary["status"] == "open_access_access_denied"
    assert summary["fulltext_available"] is False
    assert summary["writing_direct_evidence_allowed"] is False
    assert selected_paper["sh_semantic_assessments"] == semantic_before["sh_semantic_assessments"]
    assert selected_paper["sh_matches"] == semantic_before["sh_matches"]
    assert selected_paper["sh_semantic_assessments"][0]["seed_tier"] == "exploration"
    assert selected_paper["sh_semantic_assessments"][0]["graph_expansion_eligible"] is True

    graph = manager.config.BasicInfo.sh_graph_provenance
    assert graph["fulltext_acquisition_by_paper"]["W123"] == summary
    assert graph["paper_annotations"]["W123"] == [graph_annotation]
    assert (tmp_path / "sh_graph_provenance.json").exists()
