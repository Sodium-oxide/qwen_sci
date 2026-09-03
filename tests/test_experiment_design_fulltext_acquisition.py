"""Regression tests for safe ExperimentDesign full-text acquisition."""

from __future__ import annotations

import json
from io import StringIO
from pathlib import Path

from src.agents.experiment_design_agent.fulltext_acquisition import (
    SurveyCompatibleFulltextAcquirer,
)
from src.agents.experiment_design_agent.run_logging import ExperimentDesignRunLogger
from src.agents.experiment_design_agent.survey_evidence import SurveyEvidenceCollector


class _Response:
    def __init__(
        self,
        *,
        status_code: int = 200,
        content: bytes = b"",
        content_type: str = "application/pdf",
        url: str = "https://repository.example/paper.pdf",
        headers: dict[str, str] | None = None,
    ) -> None:
        self.status_code = status_code
        self.content = content
        self.url = url
        self.headers = {"Content-Type": content_type, **(headers or {})}
        self.closed = False

    def iter_content(self, *, chunk_size: int) -> list[bytes]:
        del chunk_size
        return [self.content]

    def close(self) -> None:
        self.closed = True


class _Session:
    def __init__(self, responses: dict[str, _Response]) -> None:
        self.responses = responses
        self.calls: list[dict[str, object]] = []

    def get(self, url: str, **kwargs: object) -> _Response:
        self.calls.append({"url": url, **kwargs})
        return self.responses[url]


def _paper(*candidates: dict[str, object]) -> dict[str, object]:
    return {
        "canonical_paper_id": "W123",
        "title": "Safe parsing of open literature",
        "abstract": "An abstract remains available when full text cannot be parsed.",
        "fulltext_candidates": list(candidates),
    }


def _config(tmp_path: Path, **overrides: object) -> dict[str, object]:
    return {
        "cache_dir": str(tmp_path),
        "max_candidates_per_paper": 12,
        "max_pdf_bytes": 50_000,
        "timeout_seconds": 5,
        "per_host_concurrency": 1,
        "parser_backend": "survey_mineru",
        "parser_batch_size": 1,
        "enable_landing_page_recovery": True,
        "max_landing_page_bytes": 20_000,
        "max_declared_pdf_links_per_landing_page": 8,
        **overrides,
    }


def _valid_pdf_validator(path: str) -> bool:
    return Path(path).read_bytes().startswith(b"%PDF-")


def _write_markdown(paths: list[Path], output_dir: Path) -> None:
    pdf_path = paths[0]
    target = output_dir / pdf_path.stem / "auto" / f"{pdf_path.stem}.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("# Parsed paper\n\nValidated full-text evidence.", encoding="utf-8")


def test_html_mislabeled_as_pdf_is_rejected_without_calling_mineru(tmp_path: Path) -> None:
    url = "https://publisher.example/download.pdf"
    parser_calls = 0

    def parser(paths: list[Path], output_dir: Path) -> None:
        nonlocal parser_calls
        del paths, output_dir
        parser_calls += 1

    acquirer = SurveyCompatibleFulltextAcquirer(
        _config(tmp_path),
        session=_Session({url: _Response(content=b"<!DOCTYPE html><head>login</head>", content_type="text/html", url=url)}),
        pdf_validator=_valid_pdf_validator,
        pdf_parser=parser,
    )

    result = acquirer.acquire(_paper({"kind": "pdf", "url": url, "source": "openalex.best_oa_location"}))

    audit = result["fulltext_acquisition"]
    assert "fulltext" not in result
    assert audit["status"] == "non_pdf"
    assert audit["attempts"][0]["content_type"] == "text/html"
    assert parser_calls == 0


def test_valid_pdf_becomes_fulltext_only_after_markdown_is_written(tmp_path: Path) -> None:
    url = "https://repository.example/paper.pdf"
    response = _Response(content=b"%PDF-1.7\n" + b"x" * 4096, url=url)
    acquirer = SurveyCompatibleFulltextAcquirer(
        _config(tmp_path),
        session=_Session({url: response}),
        pdf_validator=_valid_pdf_validator,
        pdf_parser=_write_markdown,
    )

    result = acquirer.acquire(_paper({"kind": "pdf", "url": url, "source": "openalex.best_oa_location"}))

    assert result["content_availability"] == "fulltext"
    assert result["fulltext"] == "# Parsed paper\n\nValidated full-text evidence."
    assert result["fulltext_source_location"] == "fulltext:survey_pdf:W123:markdown"
    assert result["fulltext_acquisition"]["status"] == "parsed"
    assert response.closed is True


def test_non_pdf_candidate_continues_to_next_candidate(tmp_path: Path) -> None:
    first = "https://publisher.example/looks-like.pdf"
    second = "https://repository.example/open.pdf"
    acquirer = SurveyCompatibleFulltextAcquirer(
        _config(tmp_path),
        session=_Session(
            {
                first: _Response(content=b"<html>not a PDF</html>", content_type="text/html", url=first),
                second: _Response(content=b"%PDF-1.7\n" + b"x" * 4096, url=second),
            }
        ),
        pdf_validator=_valid_pdf_validator,
        pdf_parser=_write_markdown,
    )

    result = acquirer.acquire(
        _paper(
            {"kind": "pdf", "url": first, "source": "openalex.best_oa_location"},
            {"kind": "pdf", "url": second, "source": "openalex.oa_location"},
        )
    )

    audit = result["fulltext_acquisition"]
    assert result["content_availability"] == "fulltext"
    assert [attempt["status"] for attempt in audit["attempts"]] == ["non_pdf", "downloaded_response"]
    assert audit["selected_candidate"]["url"] == second


def test_landing_page_declared_pdf_is_bounded_and_traceable(tmp_path: Path) -> None:
    landing_url = "https://repository.example/article"
    pdf_url = "https://repository.example/article/download.pdf"

    def landing_resolver(candidate: dict[str, object], **_: object) -> dict[str, object]:
        assert candidate["url"] == landing_url
        return {
            "status": "pdf_links_found",
            "http_status": 200,
            "content_type": "text/html",
            "final_url": landing_url,
            "pdf_candidates": [
                {
                    "kind": "pdf",
                    "url": pdf_url,
                    "source": "openalex.best_oa_location.declared_pdf",
                    "priority": 10,
                }
            ],
        }

    acquirer = SurveyCompatibleFulltextAcquirer(
        _config(tmp_path),
        session=_Session({pdf_url: _Response(content=b"%PDF-1.7\n" + b"x" * 4096, url=pdf_url)}),
        pdf_validator=_valid_pdf_validator,
        pdf_parser=_write_markdown,
        landing_resolver=landing_resolver,
    )

    result = acquirer.acquire(_paper({"kind": "landing", "url": landing_url, "source": "openalex.best_oa_location"}))

    audit = result["fulltext_acquisition"]
    assert result["content_availability"] == "fulltext"
    assert audit["attempts"][0]["status"] == "pdf_links_found"
    assert audit["selected_candidate"]["source"] == "openalex.best_oa_location.declared_pdf"


def test_mineru_failure_retries_once_then_keeps_abstract_level(tmp_path: Path) -> None:
    url = "https://repository.example/paper.pdf"
    parser_calls = 0

    def parser(paths: list[Path], output_dir: Path) -> None:
        nonlocal parser_calls
        del paths, output_dir
        parser_calls += 1

    acquirer = SurveyCompatibleFulltextAcquirer(
        _config(tmp_path),
        session=_Session({url: _Response(content=b"%PDF-1.7\n" + b"x" * 4096, url=url)}),
        pdf_validator=_valid_pdf_validator,
        pdf_parser=parser,
    )

    result = acquirer.acquire(_paper({"kind": "pdf", "url": url, "source": "openalex.best_oa_location"}))

    assert "fulltext" not in result
    assert result["fulltext_acquisition"]["status"] == "parse_failed"
    assert result["fulltext_acquisition"]["parser"]["retry"] == "single_paper"
    assert parser_calls == 2


def test_corrupt_pdf_and_parser_unavailable_never_upgrade_content_level(tmp_path: Path) -> None:
    corrupt_url = "https://repository.example/corrupt.pdf"
    unavailable_url = "https://repository.example/unavailable.pdf"
    corrupt = SurveyCompatibleFulltextAcquirer(
        _config(tmp_path / "corrupt"),
        session=_Session({corrupt_url: _Response(content=b"%PDF-broken", url=corrupt_url)}),
        pdf_validator=lambda _: False,
        pdf_parser=_write_markdown,
    )
    unavailable = SurveyCompatibleFulltextAcquirer(
        _config(tmp_path / "unavailable", parser_backend="not_installed"),
        session=_Session({unavailable_url: _Response(content=b"%PDF-1.7\n" + b"x" * 4096, url=unavailable_url)}),
        pdf_validator=_valid_pdf_validator,
    )

    corrupt_result = corrupt.acquire(
        _paper({"kind": "pdf", "url": corrupt_url, "source": "openalex.best_oa_location"})
    )
    unavailable_result = unavailable.acquire(
        _paper({"kind": "pdf", "url": unavailable_url, "source": "openalex.best_oa_location"})
    )

    assert "fulltext" not in corrupt_result
    assert corrupt_result["fulltext_acquisition"]["status"] == "non_pdf"
    assert "fulltext" not in unavailable_result
    assert unavailable_result["fulltext_acquisition"]["status"] == "parser_unavailable"


def test_http_rejections_and_size_limit_are_audited_without_parser(tmp_path: Path) -> None:
    access_denied_url = "https://publisher.example/denied.pdf"
    rate_limited_url = "https://publisher.example/rate-limited.pdf"
    too_large_url = "https://repository.example/large.pdf"
    parser_calls = 0

    def parser(paths: list[Path], output_dir: Path) -> None:
        nonlocal parser_calls
        del paths, output_dir
        parser_calls += 1

    denied = SurveyCompatibleFulltextAcquirer(
        _config(tmp_path / "denied"),
        session=_Session({access_denied_url: _Response(status_code=403, content=b"denied", url=access_denied_url)}),
        pdf_validator=_valid_pdf_validator,
        pdf_parser=parser,
    )
    limited = SurveyCompatibleFulltextAcquirer(
        _config(tmp_path / "limited"),
        session=_Session({rate_limited_url: _Response(status_code=429, content=b"later", url=rate_limited_url)}),
        pdf_validator=_valid_pdf_validator,
        pdf_parser=parser,
    )
    oversized = SurveyCompatibleFulltextAcquirer(
        _config(tmp_path / "oversized", max_pdf_bytes=2048),
        session=_Session(
            {
                too_large_url: _Response(
                    content=b"%PDF-1.7\n" + b"x" * 4096,
                    url=too_large_url,
                    headers={"Content-Length": "50000"},
                )
            }
        ),
        pdf_validator=_valid_pdf_validator,
        pdf_parser=parser,
    )

    denied_result = denied.acquire(_paper({"kind": "pdf", "url": access_denied_url, "source": "openalex.best_oa_location"}))
    limited_result = limited.acquire(_paper({"kind": "pdf", "url": rate_limited_url, "source": "openalex.best_oa_location"}))
    oversized_result = oversized.acquire(_paper({"kind": "pdf", "url": too_large_url, "source": "openalex.best_oa_location"}))

    assert denied_result["fulltext_acquisition"]["status"] == "access_denied"
    assert limited_result["fulltext_acquisition"]["status"] == "rate_limited"
    assert oversized_result["fulltext_acquisition"]["status"] == "too_large"
    assert parser_calls == 0


def test_server_ignoring_range_restarts_download_without_corrupting_pdf(tmp_path: Path) -> None:
    url = "https://repository.example/range.pdf"
    acquirer = SurveyCompatibleFulltextAcquirer(
        _config(tmp_path),
        session=_Session({url: _Response(content=b"%PDF-1.7\n" + b"new" * 2000, url=url)}),
        pdf_validator=_valid_pdf_validator,
        pdf_parser=_write_markdown,
    )
    pdf_path, _ = acquirer._paths_for_paper("W123")
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    Path(f"{pdf_path}.part").write_bytes(b"old partial bytes")

    result = acquirer.acquire(_paper({"kind": "pdf", "url": url, "source": "openalex.best_oa_location"}))

    assert result["content_availability"] == "fulltext"
    assert pdf_path.read_bytes().startswith(b"%PDF-1.7\nnew")
    assert b"old partial bytes" not in pdf_path.read_bytes()


def test_collector_retains_abstract_when_fulltext_acquisition_fails(tmp_path: Path) -> None:
    url = "https://publisher.example/login.pdf"

    class _OpenAlex:
        def search(self, *_: object, **__: object) -> list[dict[str, object]]:
            return [
                {
                    **_paper({"kind": "pdf", "url": url, "source": "openalex.best_oa_location"}),
                    "providers": ["openalex"],
                    "provider_ids": {"openalex": "W123"},
                    "query_task_ids": ["EDQ1"],
                    "abstract_source_location": "abstract:openalex",
                    "content_availability": "abstract",
                }
            ]

    acquirer = SurveyCompatibleFulltextAcquirer(
        _config(tmp_path),
        session=_Session({url: _Response(content=b"<html>login</html>", content_type="text/html", url=url)}),
        pdf_validator=_valid_pdf_validator,
        pdf_parser=_write_markdown,
    )
    collector = SurveyEvidenceCollector(
        openalex_client=_OpenAlex(),
        semantic_scholar_client=object(),
        fulltext_fetcher=acquirer,
    )

    collection = collector.collect(
        {"queries": [{"task_id": "EDQ1", "slot": "measurement_calibration", "query": "calibration"}]},
        max_fulltext_papers=1,
        screener_llm_call=lambda prompt, **kwargs: {
            "slot_assessments": [
                {
                    "slot": "measurement_calibration",
                    "relation": "limited_support",
                    "evidence_anchors": [{"source": "abstract", "text": "full text cannot be parsed"}],
                    "rationale": "The supplied abstract is only a limited design cue.",
                }
            ]
        },
    )

    paper = collection["papers"][0]
    assert paper["content_availability"] == "abstract"
    assert paper["abstract"] == "An abstract remains available when full text cannot be parsed."
    assert "fulltext" not in paper
    assert collection["fulltext_acquisition_by_paper"]["W123"]["status"] == "non_pdf"


def test_fulltext_events_keep_only_query_free_provenance_urls(tmp_path: Path) -> None:
    url = "https://repository.example/paper.pdf?token=very-secret"
    logger = ExperimentDesignRunLogger("fulltext-log-test", console_stream=StringIO())
    acquirer = SurveyCompatibleFulltextAcquirer(
        _config(tmp_path),
        session=_Session({url: _Response(content=b"%PDF-1.7\n" + b"x" * 4096, url=url)}),
        pdf_validator=_valid_pdf_validator,
        pdf_parser=_write_markdown,
    )

    result = acquirer.acquire(
        _paper({"kind": "pdf", "url": url, "source": "openalex.best_oa_location"}),
        logger=logger,
    )

    records = [record for record in logger.records if record["stage"] == "evidence_fulltext"]
    serialized = json.dumps(records, ensure_ascii=False)
    assert result["fulltext_acquisition"]["selected_candidate"]["url"] == "https://repository.example/paper.pdf"
    assert "token=very-secret" not in serialized
    assert any(record["event"] == "fulltext_download_rejected" for record in records) is False
    assert records[-1]["event"] == "fulltext_acquisition_completed"


def test_experiment_design_has_no_legacy_pypdf_parser() -> None:
    source = Path("src/agents/experiment_design_agent/survey_evidence.py").read_text(encoding="utf-8")

    assert "PdfReader" not in source
    assert "pypdf" not in source
    assert "OpenAccessFulltextFetcher" not in source
