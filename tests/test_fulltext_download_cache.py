import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SURVEY_AGENT_ROOT = os.path.join(PROJECT_ROOT, "src", "agents", "survey_agent")
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, SURVEY_AGENT_ROOT)

from modules.fulltext_download_cache import FulltextDownloadCoordinator


def _settings(**overrides):
    values = {
        "fulltext_per_host_concurrency": 2,
        "fulltext_access_context_generation": "anonymous-v1",
        "fulltext_oa_resolution_cache_ttl_seconds": 60,
        "fulltext_pdf_success_cache_ttl_seconds": 60,
        "fulltext_failure_404_ttl_seconds": 60,
        "fulltext_failure_access_denied_ttl_seconds": 60,
        "fulltext_failure_non_pdf_ttl_seconds": 60,
        "fulltext_failure_transient_first_ttl_seconds": 1,
        "fulltext_failure_transient_ttl_seconds": 2,
        "fulltext_host_denial_threshold": 2,
        "fulltext_host_denial_window_seconds": 60,
        "fulltext_host_circuit_ttl_seconds": 60,
        "invalidate_fulltext_failure_cache": False,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _valid_pdf(path):
    return Path(path).exists() and Path(path).read_bytes().startswith(b"%PDF-")


def test_url_singleflight_downloads_once_and_materializes_for_waiters(tmp_path):
    coordinator = FulltextDownloadCoordinator(str(tmp_path), _settings())
    url = "https://repository.example.edu/record/article.pdf"
    calls = 0
    lock = threading.Lock()

    def download(destination):
        def operation():
            nonlocal calls
            with lock:
                calls += 1
            time.sleep(0.08)
            Path(destination).write_bytes(b"%PDF-singleflight")
            return {
                "downloaded": True,
                "status": "downloaded_response",
                "http_status": 200,
                "content_type": "application/pdf",
                "bytes_written": 17,
            }

        return coordinator.execute(
            url=url,
            kind="pdf",
            destination_path=str(destination),
            validator=_valid_pdf,
            operation=operation,
        )

    first = tmp_path / "first.pdf"
    second = tmp_path / "second.pdf"
    with ThreadPoolExecutor(max_workers=2) as executor:
        first_result, second_result = list(
            executor.map(download, (first, second))
        )

    assert calls == 1
    assert first_result["downloaded"] is True
    assert second_result["downloaded"] is True
    assert first.read_bytes() == second.read_bytes() == b"%PDF-singleflight"
    assert any(
        result.get("singleflight_shared") for result in (first_result, second_result)
    )


def test_per_host_concurrency_is_bounded_while_distinct_urls_run(tmp_path):
    coordinator = FulltextDownloadCoordinator(
        str(tmp_path), _settings(fulltext_per_host_concurrency=2)
    )
    active = 0
    peak = 0
    lock = threading.Lock()

    def resolve(index):
        nonlocal active, peak

        def operation():
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
            time.sleep(0.06)
            with lock:
                active -= 1
            return {
                "status": "pdf_links_found",
                "pdf_candidates": [],
                "http_status": 200,
                "content_type": "text/html",
            }

        return coordinator.execute(
            url=f"https://onlinelibrary.wiley.com/record/{index}",
            kind="landing_page",
            operation=operation,
            is_success=lambda result: result.get("status") == "pdf_links_found",
        )

    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(resolve, range(4)))

    assert peak == 2
    assert all(result["status"] == "pdf_links_found" for result in results)


def test_classified_failure_uses_ttl_cache_without_reissuing_request(tmp_path):
    coordinator = FulltextDownloadCoordinator(str(tmp_path), _settings())
    calls = 0

    def operation():
        nonlocal calls
        calls += 1
        return {
            "downloaded": False,
            "status": "not_found",
            "http_status": 404,
            "content_type": "text/html",
        }

    first = coordinator.execute(
        url="https://repo.example.edu/missing.pdf",
        kind="pdf",
        destination_path=str(tmp_path / "missing.pdf"),
        validator=_valid_pdf,
        operation=operation,
    )
    second = coordinator.execute(
        url="https://repo.example.edu/missing.pdf",
        kind="pdf",
        destination_path=str(tmp_path / "again.pdf"),
        validator=_valid_pdf,
        operation=operation,
    )

    assert calls == 1
    assert first["status"] == second["status"] == "not_found"
    assert second["cache_hit"] is True
    assert second["cache_state"] == "failure"


def test_new_authorized_access_context_does_not_reuse_anonymous_403(tmp_path):
    url = "https://onlinelibrary.wiley.com/doi/pdf/10.1/example"
    calls = 0

    anonymous = FulltextDownloadCoordinator(
        str(tmp_path), _settings(fulltext_access_context_generation="anonymous-v1")
    )

    def denied():
        nonlocal calls
        calls += 1
        return {
            "downloaded": False,
            "status": "access_denied",
            "http_status": 403,
            "content_type": "text/html",
        }

    first = anonymous.execute(
        url=url,
        kind="landing_page",
        operation=denied,
        is_success=lambda _result: False,
    )
    authorized = FulltextDownloadCoordinator(
        str(tmp_path), _settings(fulltext_access_context_generation="wiley-tdm-v1")
    )

    def authorized_resolution():
        nonlocal calls
        calls += 1
        return {
            "status": "pdf_links_found",
            "pdf_candidates": [{"url": "https://tdm.example/article.pdf"}],
            "http_status": 200,
            "content_type": "text/html",
        }

    second = authorized.execute(
        url=url,
        kind="landing_page",
        operation=authorized_resolution,
        is_success=lambda result: result.get("status") == "pdf_links_found",
    )

    assert calls == 2
    assert first["status"] == "access_denied"
    assert second["status"] == "pdf_links_found"
    assert second["cache_hit"] is False


def test_repeated_distinct_access_denials_open_a_short_host_circuit(tmp_path):
    coordinator = FulltextDownloadCoordinator(
        str(tmp_path), _settings(fulltext_host_denial_threshold=2)
    )
    calls = 0

    def denied():
        nonlocal calls
        calls += 1
        return {
            "downloaded": False,
            "status": "access_denied",
            "http_status": 403,
            "content_type": "text/html",
        }

    for suffix in ("one", "two"):
        result = coordinator.execute(
            url=f"https://publisher.example/doi/{suffix}",
            kind="landing_page",
            operation=denied,
            is_success=lambda _result: False,
        )
        assert result["status"] == "access_denied"

    circuit = coordinator.execute(
        url="https://publisher.example/doi/three",
        kind="landing_page",
        operation=denied,
        is_success=lambda _result: False,
    )

    assert calls == 2
    assert circuit["status"] == "host_circuit_open"
    assert circuit["cache_hit"] is True


def test_redirected_denials_do_not_open_a_global_doi_circuit(tmp_path):
    coordinator = FulltextDownloadCoordinator(
        str(tmp_path), _settings(fulltext_host_denial_threshold=2)
    )
    calls = 0

    def denied_after_doi_redirect():
        nonlocal calls
        calls += 1
        return {
            "downloaded": False,
            "status": "access_denied",
            "final_url": f"https://publisher.example/article/restricted-{calls}",
            "http_status": 403,
            "content_type": "text/html",
        }

    for suffix in ("one", "two"):
        result = coordinator.execute(
            url=f"https://doi.org/10.1000/{suffix}",
            kind="landing_page",
            operation=denied_after_doi_redirect,
            is_success=lambda _result: False,
        )
        assert result["status"] == "access_denied"

    # The publisher circuit may protect direct publisher URLs, but another DOI
    # must still be allowed to resolve to a different legal OA location.
    third = coordinator.execute(
        url="https://doi.org/10.1000/three",
        kind="landing_page",
        operation=lambda: {
            "status": "pdf_links_found",
            "final_url": "https://repository.example/record/three",
            "pdf_candidates": [{"url": "https://repository.example/three.pdf"}],
        },
        is_success=lambda result: result.get("status") == "pdf_links_found",
    )
    publisher_circuit = coordinator.execute(
        url="https://publisher.example/article/another",
        kind="landing_page",
        operation=denied_after_doi_redirect,
        is_success=lambda _result: False,
    )

    assert calls == 2
    assert third["status"] == "pdf_links_found"
    assert publisher_circuit["status"] == "host_circuit_open"


def test_signed_url_failures_use_the_short_signed_url_ttl(tmp_path):
    coordinator = FulltextDownloadCoordinator(
        str(tmp_path),
        _settings(
            fulltext_failure_access_denied_ttl_seconds=3600,
            fulltext_failure_signed_url_ttl_seconds=7,
        ),
    )

    assert coordinator._failure_ttl(
        "access_denied", "https://repository.example/paper.pdf?expires=123"
    ) == 7
