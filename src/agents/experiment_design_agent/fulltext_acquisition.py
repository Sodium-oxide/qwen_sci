"""Survey-compatible, design-only acquisition of traceable open full text.

This module deliberately consumes only OA candidates already attached to a
paper discovered by ExperimentDesign.  It does not discover papers, expand a
topic, rank papers, or execute any research activity.  A document becomes
``fulltext`` only after strict PDF validation and successful MinerU Markdown
output; all other outcomes retain the paper's existing abstract/metadata.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from urllib.parse import urlsplit
import os
import re
import time

import requests

from src.agents.survey_agent.modules.fulltext_download_cache import (
    FulltextDownloadCoordinator,
    sanitize_url_for_storage,
)
from src.agents.survey_agent.modules.fulltext_resolution import (
    resolve_declared_pdf_links,
    resolve_fulltext_candidates,
)
from src.agents.survey_agent.utils.utils import is_valid_pdf

from .cache import ExperimentDesignCache


FULLTEXT_ACQUISITION_SCHEMA_VERSION = "experiment_design_fulltext_acquisition_v1"


def _setting(value: object, key: str, default: object = "") -> object:
    if isinstance(value, Mapping):
        return value.get(key, default)
    return getattr(value, key, default)


def _text(value: object, *, limit: int = 1200) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def _as_bool(value: object, default: bool) -> bool:
    if value is None:
        return default
    return str(value).strip().casefold() not in {"0", "false", "no", "off", ""}


def _as_int(value: object, default: int, *, minimum: int = 0) -> int:
    try:
        return max(minimum, int(value))
    except (TypeError, ValueError):
        return max(minimum, default)


def _as_float(value: object, default: float, *, minimum: float = 0.1) -> float:
    try:
        return max(minimum, float(value))
    except (TypeError, ValueError):
        return max(minimum, default)


def _safe_host(url: object) -> str:
    return str(urlsplit(str(url or "")).netloc or "").casefold()


def _safe_candidate(candidate: Mapping[str, Any]) -> dict[str, Any]:
    safe = {
        key: candidate[key]
        for key in (
            "kind",
            "source",
            "sources",
            "priority",
            "version",
            "license",
            "host_type",
            "evidence",
            "oa_evidence",
            "metadata_field",
            "status",
        )
        if candidate.get(key) not in (None, "", [], {})
    }
    safe["url"] = sanitize_url_for_storage(candidate.get("url"))
    return safe


def _download_status_for_http_status(status_code: object) -> str:
    if status_code == 404:
        return "not_found"
    if status_code == 401:
        return "authentication_required"
    if status_code == 403:
        return "access_denied"
    if status_code == 429:
        return "rate_limited"
    if isinstance(status_code, int) and status_code >= 500:
        return "transient_failure"
    return "http_error"


class SurveyCompatibleFulltextAcquirer:
    """Acquire validated OA PDFs and parse them to Markdown with Survey tools.

    ``unpaywall_api`` is dependency-injected and never constructed here.  The
    default configuration disables it, so it cannot become a hidden discovery
    source.  Likewise, candidate resolution receives only ExperimentDesign's
    already-declared locations; DOI, generic metadata, PMC, and arXiv
    expansion are disabled in this adapter.
    """

    def __init__(
        self,
        config: object | None = None,
        *,
        session: Any | None = None,
        coordinator: FulltextDownloadCoordinator | None = None,
        pdf_validator: Callable[[str], bool] | None = None,
        pdf_parser: Callable[[list[Path], Path], object] | None = None,
        candidate_resolver: Callable[..., Mapping[str, Any]] = resolve_fulltext_candidates,
        landing_resolver: Callable[..., Mapping[str, Any]] = resolve_declared_pdf_links,
        unpaywall_api: Any | None = None,
        cache: ExperimentDesignCache | None = None,
    ) -> None:
        self.config = config or {}
        self.cache = cache or ExperimentDesignCache({"enabled": False})
        self.enabled = _as_bool(_setting(self.config, "enabled", True), True)
        self.cache_dir = Path(
            _text(
                _setting(
                    self.config,
                    "cache_dir",
                    "workspace/experiment_design/fulltext_cache",
                ),
                limit=4000,
            )
            or "workspace/experiment_design/fulltext_cache"
        )
        self.max_candidates_per_paper = _as_int(
            _setting(self.config, "max_candidates_per_paper", 12), 12, minimum=1
        )
        self.max_papers = _as_int(
            _setting(self.config, "max_papers", 20), 20, minimum=0
        )
        self.max_pdf_bytes = _as_int(
            _setting(self.config, "max_pdf_bytes", 50_000_000),
            50_000_000,
            minimum=2048,
        )
        self.timeout_seconds = _as_float(
            _setting(self.config, "timeout_seconds", 30), 30.0
        )
        self.enable_landing_page_recovery = _as_bool(
            _setting(self.config, "enable_landing_page_recovery", True), True
        )
        self.enable_unpaywall_resolution = _as_bool(
            _setting(self.config, "enable_unpaywall_resolution", False), False
        )
        self.max_landing_page_bytes = _as_int(
            _setting(self.config, "max_landing_page_bytes", 1_500_000),
            1_500_000,
            minimum=1024,
        )
        self.max_declared_pdf_links = _as_int(
            _setting(self.config, "max_declared_pdf_links_per_landing_page", 8),
            8,
            minimum=1,
        )
        self.max_redirects = _as_int(
            _setting(self.config, "max_redirects", 5), 5, minimum=0
        )
        self.parser_backend = _text(
            _setting(self.config, "parser_backend", "survey_mineru"), limit=80
        ) or "survey_mineru"
        self.parser_batch_size = _as_int(
            _setting(self.config, "parser_batch_size", 1), 1, minimum=1
        )
        self.session = session or requests.Session()
        self.pdf_validator = pdf_validator or is_valid_pdf
        self.pdf_parser = pdf_parser
        self.candidate_resolver = candidate_resolver
        self.landing_resolver = landing_resolver
        self.unpaywall_api = unpaywall_api if self.enable_unpaywall_resolution else None
        self._coordinator_settings = self._build_coordinator_settings()
        self.coordinator = coordinator or FulltextDownloadCoordinator(
            str(self.cache_dir), self._coordinator_settings
        )

    def _build_coordinator_settings(self) -> SimpleNamespace:
        """Translate the small ExperimentDesign config surface for Survey's guard."""

        return SimpleNamespace(
            fulltext_access_context_generation="experiment-design-anonymous-v1",
            fulltext_per_host_concurrency=_as_int(
                _setting(self.config, "per_host_concurrency", 2), 2, minimum=1
            ),
            fulltext_pdf_max_bytes=self.max_pdf_bytes,
            fulltext_failure_non_pdf_ttl_seconds=_as_int(
                _setting(self.config, "failure_non_pdf_ttl_seconds", 21_600),
                21_600,
                minimum=1,
            ),
            fulltext_failure_access_denied_ttl_seconds=_as_int(
                _setting(self.config, "failure_access_denied_ttl_seconds", 1_800),
                1_800,
                minimum=1,
            ),
            fulltext_failure_rate_limited_ttl_seconds=_as_int(
                _setting(self.config, "failure_rate_limited_ttl_seconds", 900),
                900,
                minimum=1,
            ),
            fulltext_failure_transient_first_ttl_seconds=60,
            fulltext_failure_transient_ttl_seconds=180,
            fulltext_pdf_success_cache_ttl_seconds=2_592_000,
            fulltext_oa_resolution_cache_ttl_seconds=604_800,
            fulltext_host_denial_window_seconds=600,
            fulltext_host_denial_threshold=2,
            fulltext_host_circuit_ttl_seconds=3_600,
            invalidate_fulltext_failure_cache=False,
        )

    @staticmethod
    def _paper_id(paper: Mapping[str, Any]) -> str:
        canonical = _text(paper.get("canonical_paper_id"), limit=300)
        if canonical:
            return canonical
        doi = _text(paper.get("doi"), limit=300)
        if doi:
            return f"doi:{doi}"
        title = _text(paper.get("title"), limit=300)
        return f"paper:{sha256(title.encode('utf-8')).hexdigest()[:16]}" if title else "paper:unknown"

    def _paths_for_paper(self, paper_id: str) -> tuple[Path, Path]:
        slug = re.sub(r"[^A-Za-z0-9._-]+", "_", paper_id).strip("._") or "paper"
        digest = sha256(paper_id.encode("utf-8")).hexdigest()[:12]
        file_id = f"{slug[:96]}-{digest}"
        return (
            self.cache_dir / "pdf" / f"{file_id}.pdf",
            self.cache_dir / "markdown",
        )

    @staticmethod
    def _remove_partial_pdf(pdf_path: Path) -> None:
        for path in (pdf_path, Path(f"{pdf_path}.part")):
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass

    @staticmethod
    def _emit(logger: Any | None, event: str, *, level: str = "INFO", status: str, **fields: object) -> None:
        if logger is not None:
            logger.event("evidence_fulltext", event, level=level, status=status, **fields)

    def _resolution_input(self, paper: Mapping[str, Any]) -> dict[str, Any]:
        """Map only existing ExperimentDesign OA candidates to Survey's format."""

        locations: list[dict[str, Any]] = []
        for position, raw_candidate in enumerate(paper.get("fulltext_candidates") or [], start=1):
            if not isinstance(raw_candidate, Mapping):
                continue
            url = _text(raw_candidate.get("url"), limit=4000)
            if not url:
                continue
            raw_kind = _text(raw_candidate.get("kind"), limit=40).casefold()
            kind = "landing_page" if raw_kind in {"landing", "landing_page"} else "pdf"
            source = _text(raw_candidate.get("source"), limit=160) or "declared_open_access"
            priority = _as_int(raw_candidate.get("priority"), position * 10, minimum=0)
            location: dict[str, Any] = {
                "source": source,
                "priority": priority,
                "version": _text(raw_candidate.get("version"), limit=100),
                "license": _text(raw_candidate.get("license"), limit=120),
                "host_type": _text(raw_candidate.get("host_type"), limit=120),
                "evidence": _text(raw_candidate.get("evidence"), limit=160) or "experiment_design_declared_oa",
            }
            if kind == "landing_page":
                location["landing_page_url"] = url
            else:
                location["pdf_url"] = url
            locations.append(location)
        return {"openalex_oa_locations": locations}

    def _resolve_candidates(self, paper: Mapping[str, Any]) -> dict[str, Any]:
        resolution = self.candidate_resolver(
            self._resolution_input(paper),
            unpaywall_api=self.unpaywall_api,
            include_all_unpaywall_locations=self.enable_unpaywall_resolution,
            include_generic_metadata_urls=False,
            include_doi_landing_fallback=False,
        )
        return dict(resolution) if isinstance(resolution, Mapping) else {}

    def _download_pdf(self, url: str, pdf_path: Path) -> dict[str, Any]:
        """Stream one candidate with bounded bytes, Range handling, and no parser."""

        started_at = time.monotonic()
        attempt: dict[str, Any] = {
            "downloaded": False,
            "status": "fetch_failed",
            "requested_url": url,
            "final_url": url,
            "http_status": None,
            "content_type": "",
            "bytes_written": 0,
            "requested_host": _safe_host(url),
            "final_host": _safe_host(url),
        }

        def finish(downloaded: bool) -> dict[str, Any]:
            attempt["downloaded"] = bool(downloaded)
            attempt["elapsed_seconds"] = round(time.monotonic() - started_at, 3)
            return attempt

        partial_path = Path(f"{pdf_path}.part")
        existing_size = partial_path.stat().st_size if partial_path.exists() else 0
        headers = {
            "Accept": "application/pdf,application/octet-stream;q=0.9,*/*;q=0.1",
            "Range": f"bytes={existing_size}-",
            "User-Agent": "Xcientist/0.8 (ExperimentDesign OA full-text acquisition)",
        }
        response: Any | None = None
        try:
            response = self.session.get(
                url,
                headers=headers,
                stream=True,
                timeout=self.timeout_seconds,
                allow_redirects=True,
            )
            status_code = int(getattr(response, "status_code", 0) or 0)
            attempt["http_status"] = status_code
            attempt["final_url"] = str(getattr(response, "url", "") or url)
            attempt["final_host"] = _safe_host(attempt["final_url"])
            content_type = str(getattr(response, "headers", {}).get("Content-Type") or "").casefold()
            attempt["content_type"] = content_type
            if status_code not in {200, 206, 416}:
                attempt["status"] = _download_status_for_http_status(status_code)
                return finish(False)
            if "text/html" in content_type or "application/xhtml" in content_type or "application/json" in content_type:
                attempt["status"] = "non_pdf"
                return finish(False)
            if status_code == 416:
                if not partial_path.exists():
                    attempt["status"] = "range_not_satisfiable"
                    return finish(False)
                pdf_path.parent.mkdir(parents=True, exist_ok=True)
                os.replace(partial_path, pdf_path)
            else:
                if status_code == 206:
                    content_range = str(getattr(response, "headers", {}).get("Content-Range") or "")
                    try:
                        range_start = int(content_range.split(" ", 1)[1].split("-", 1)[0])
                    except (IndexError, ValueError):
                        attempt["status"] = "invalid_range_response"
                        return finish(False)
                    if range_start != existing_size:
                        attempt["status"] = "invalid_range_response"
                        return finish(False)
                elif existing_size:
                    existing_size = 0

                content_length = str(getattr(response, "headers", {}).get("Content-Length") or "")
                try:
                    declared_size = int(content_length) + existing_size if content_length else None
                except ValueError:
                    declared_size = None
                if declared_size is not None and declared_size > self.max_pdf_bytes:
                    attempt["status"] = "too_large"
                    return finish(False)

                pdf_path.parent.mkdir(parents=True, exist_ok=True)
                write_mode = "ab" if status_code == 206 and existing_size else "wb"
                downloaded = existing_size
                with partial_path.open(write_mode) as handle:
                    for chunk in response.iter_content(chunk_size=64 * 1024):
                        if not chunk:
                            continue
                        if downloaded + len(chunk) > self.max_pdf_bytes:
                            attempt["status"] = "too_large"
                            return finish(False)
                        handle.write(chunk)
                        downloaded += len(chunk)
                        attempt["bytes_written"] += len(chunk)
                os.replace(partial_path, pdf_path)

            if not self.pdf_validator(str(pdf_path)):
                attempt["status"] = "non_pdf"
                return finish(False)
            attempt["status"] = "downloaded_response"
            return finish(True)
        except requests.Timeout:
            attempt["status"] = "timeout"
            return finish(False)
        except requests.RequestException:
            attempt["status"] = "network_error"
            return finish(False)
        except (OSError, ValueError, TypeError) as exc:
            attempt["status"] = "fetch_failed"
            attempt["error"] = type(exc).__name__
            return finish(False)
        finally:
            if response is not None:
                close = getattr(response, "close", None)
                if callable(close):
                    close()
            if not attempt.get("downloaded"):
                self._remove_partial_pdf(pdf_path)

    def _resolve_landing(self, candidate: Mapping[str, Any]) -> dict[str, Any]:
        def operation() -> Mapping[str, Any]:
            return self.landing_resolver(
                candidate,
                http_client=self.session,
                timeout_seconds=self.timeout_seconds,
                max_html_bytes=self.max_landing_page_bytes,
                max_pdf_links=self.max_declared_pdf_links,
                max_redirects=self.max_redirects,
            )

        return self.coordinator.execute(
            url=_text(candidate.get("url"), limit=4000),
            kind="landing_page",
            operation=operation,
            is_success=lambda result: _text(result.get("status"), limit=80)
            in {"resolved_to_pdf", "pdf_links_found"},
        )

    def _parse_pdf(self, paper_id: str, pdf_path: Path, markdown_root: Path) -> tuple[str, dict[str, Any]]:
        parser_audit: dict[str, Any] = {
            "backend": self.parser_backend,
            "status": "not_started",
            "batch_size": self.parser_batch_size,
        }
        if self.parser_backend != "survey_mineru":
            parser_audit["status"] = "parser_unavailable"
            return "", parser_audit
        try:
            parser = self.pdf_parser
            if parser is None:
                from src.agents.survey_agent.utils.mineru_utils import parse_doc

                parser = lambda paths, output_dir: parse_doc(paths, output_dir=output_dir, lang="en")
        except ImportError:
            parser_audit["status"] = "parser_unavailable"
            return "", parser_audit

        markdown_root.mkdir(parents=True, exist_ok=True)
        markdown_path = markdown_root / pdf_path.stem / "auto" / f"{pdf_path.stem}.md"
        try:
            parser([pdf_path], markdown_root)
        except ImportError:
            parser_audit["status"] = "parser_unavailable"
            return "", parser_audit
        except Exception as exc:
            parser_audit["status"] = "parse_failed"
            parser_audit["failure_reason"] = type(exc).__name__
            return "", parser_audit

        if not markdown_path.is_file() or not _text(markdown_path.read_text(encoding="utf-8", errors="replace"), limit=100):
            parser_audit["retry"] = "single_paper"
            try:
                parser([pdf_path], markdown_root)
            except ImportError:
                parser_audit["status"] = "parser_unavailable"
                return "", parser_audit
            except Exception as exc:
                parser_audit["status"] = "parse_failed"
                parser_audit["failure_reason"] = type(exc).__name__
                return "", parser_audit
        if not markdown_path.is_file():
            parser_audit["status"] = "parse_failed"
            parser_audit["failure_reason"] = "markdown_not_created"
            return "", parser_audit
        try:
            markdown = markdown_path.read_text(encoding="utf-8", errors="replace").strip()
        except OSError as exc:
            parser_audit["status"] = "parse_failed"
            parser_audit["failure_reason"] = type(exc).__name__
            return "", parser_audit
        if not markdown:
            parser_audit["status"] = "parse_failed"
            parser_audit["failure_reason"] = "markdown_empty"
            return "", parser_audit
        parser_audit.update(
            {
                "status": "parsed",
                "source_location": f"fulltext:survey_pdf:{paper_id}:markdown",
                "markdown_path": str(markdown_path),
            }
        )
        return markdown, parser_audit

    @staticmethod
    def _final_status(attempts: list[dict[str, Any]]) -> str:
        statuses = {str(item.get("status") or "") for item in attempts}
        if "access_denied" in statuses or "authentication_required" in statuses:
            return "access_denied"
        if "rate_limited" in statuses:
            return "rate_limited"
        if "non_pdf" in statuses:
            return "non_pdf"
        if "too_large" in statuses:
            return "too_large"
        if "timeout" in statuses:
            return "download_timeout"
        return "download_failed"

    def _acquisition_cache_identity(self, paper: Mapping[str, Any], paper_id: str) -> dict[str, Any]:
        candidates = [
            _safe_candidate(dict(candidate))
            for candidate in paper.get("fulltext_candidates") or []
            if isinstance(candidate, Mapping)
        ]
        return {
            "canonical_paper_id": paper_id,
            "candidates": candidates,
            "parser_backend": self.parser_backend,
            "parser_batch_size": self.parser_batch_size,
            "fulltext_schema_version": FULLTEXT_ACQUISITION_SCHEMA_VERSION,
        }

    @staticmethod
    def _pdf_sha256(pdf_path: Path) -> str:
        digest = sha256()
        with pdf_path.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                digest.update(chunk)
        return digest.hexdigest()

    def _cache_acquisition_result(
        self,
        identity: Mapping[str, Any],
        result: Mapping[str, Any],
        *,
        cache_run_id: str,
    ) -> dict[str, Any]:
        resolved = dict(result)
        if _text(resolved.get("fulltext"), limit=100):
            self.cache.write(
                "fulltext_acquisitions",
                identity,
                resolved,
                metadata={"status": "parsed"},
                run_id=cache_run_id,
            )
        return resolved

    def acquire(
        self,
        paper: Mapping[str, Any],
        *,
        logger: Any | None = None,
        cache_run_id: str = "",
    ) -> dict[str, Any]:
        """Acquire one paper's existing OA candidates without upgrading failures."""

        record = dict(paper) if isinstance(paper, Mapping) else {}
        paper_id = self._paper_id(record)
        acquisition_cache_identity = self._acquisition_cache_identity(record, paper_id)
        if not self.enabled:
            audit = {
                "schema_version": FULLTEXT_ACQUISITION_SCHEMA_VERSION,
                "status": "disabled",
                "selected_candidate": {},
                "attempts": [],
                "parser": {"backend": self.parser_backend, "status": "not_started"},
            }
            return {"fulltext_acquisition": audit}

        cached_acquisition = self.cache.read(
            "fulltext_acquisitions",
            acquisition_cache_identity,
            run_id=cache_run_id,
        )
        if cached_acquisition is not None:
            self._emit(
                logger,
                "fulltext_cache_hit",
                status="CACHED",
                canonical_paper_id=paper_id,
                evidence_level="fulltext",
            )
            return cached_acquisition
        if self.cache.offline:
            audit = {
                "schema_version": FULLTEXT_ACQUISITION_SCHEMA_VERSION,
                "status": "cache_miss_read_only",
                "selected_candidate": {},
                "attempts": [],
                "parser": {"backend": self.parser_backend, "status": "not_started"},
            }
            self._emit(
                logger,
                "fulltext_cache_miss",
                level="WARNING",
                status="OFFLINE_DEGRADED",
                canonical_paper_id=paper_id,
                evidence_level="abstract_or_metadata",
            )
            return {"fulltext_acquisition": audit}

        resolution = self._resolve_candidates(record)
        candidates = [
            dict(candidate)
            for candidate in resolution.get("candidates") or []
            if isinstance(candidate, Mapping)
        ][: self.max_candidates_per_paper]
        candidate_summary = [_safe_candidate(candidate) for candidate in candidates]
        self._emit(
            logger,
            "fulltext_candidate_resolution",
            status="RESOLVED" if candidates else "EMPTY",
            canonical_paper_id=paper_id,
            candidate_count=len(candidates),
            candidates=candidate_summary,
            unpaywall_status=_text(_setting(resolution.get("unpaywall", {}), "status", "not_requested"), limit=80),
        )
        audit: dict[str, Any] = {
            "schema_version": FULLTEXT_ACQUISITION_SCHEMA_VERSION,
            "status": "no_open_access_candidate" if not candidates else "pending",
            "selected_candidate": {},
            "attempts": [],
            "parser": {"backend": self.parser_backend, "status": "not_started"},
            "candidate_resolution": {
                "candidate_count": len(candidates),
                "candidates": candidate_summary,
                "unpaywall": dict(resolution.get("unpaywall") or {"status": "not_requested"}),
                "disabled_candidates": [
                    _safe_candidate(item)
                    for item in resolution.get("disabled_candidates") or []
                    if isinstance(item, Mapping)
                ],
            },
        }
        if not candidates:
            self._emit(
                logger,
                "fulltext_acquisition_completed",
                status="NO_OPEN_ACCESS_CANDIDATE",
                canonical_paper_id=paper_id,
                attempt_count=0,
                evidence_level="abstract_or_metadata",
            )
            return {"fulltext_acquisition": audit}

        pdf_path, markdown_root = self._paths_for_paper(paper_id)
        queue = list(candidates)
        cursor = 0
        while cursor < len(queue) and cursor < self.max_candidates_per_paper:
            candidate = queue[cursor]
            cursor += 1
            kind = _text(candidate.get("kind"), limit=40)
            if kind == "landing_page":
                if not self.enable_landing_page_recovery:
                    landing = {"status": "landing_recovery_disabled", "pdf_candidates": []}
                else:
                    landing = self._resolve_landing(candidate)
                landing_record = {
                    **_safe_candidate(candidate),
                    "status": _text(landing.get("status"), limit=80) or "fetch_failed",
                    "http_status": landing.get("http_status"),
                    "content_type": _text(landing.get("content_type"), limit=200),
                    "final_host": _safe_host(landing.get("final_url")),
                    "elapsed_seconds": landing.get("elapsed_seconds"),
                    "declared_pdf_count": len(landing.get("pdf_candidates") or []),
                }
                audit["attempts"].append(landing_record)
                self._emit(
                    logger,
                    "fulltext_download_attempt",
                    status=landing_record["status"].upper(),
                    canonical_paper_id=paper_id,
                    candidate=landing_record,
                )
                if landing_record["status"] not in {"resolved_to_pdf", "pdf_links_found"}:
                    self._emit(
                        logger,
                        "fulltext_download_rejected",
                        level="WARNING",
                        status=landing_record["status"].upper(),
                        canonical_paper_id=paper_id,
                        candidate=landing_record,
                    )
                declared = [
                    dict(item)
                    for item in landing.get("pdf_candidates") or []
                    if isinstance(item, Mapping)
                ][: self.max_declared_pdf_links]
                queue[cursor:cursor] = declared
                continue

            url = _text(candidate.get("url"), limit=4000)
            if not url:
                continue
            result = self.coordinator.execute(
                url=url,
                kind="pdf",
                destination_path=str(pdf_path),
                validator=self.pdf_validator,
                operation=lambda candidate_url=url: self._download_pdf(candidate_url, pdf_path),
            )
            attempt = {
                **_safe_candidate(candidate),
                **{
                    key: value
                    for key, value in result.items()
                    if key not in {"requested_url", "final_url", "error"}
                },
                "final_host": _safe_host(result.get("final_url")),
            }
            audit["attempts"].append(attempt)
            self._emit(
                logger,
                "fulltext_download_attempt",
                status=_text(attempt.get("status"), limit=80).upper() or "UNKNOWN",
                canonical_paper_id=paper_id,
                candidate=attempt,
            )
            if not result.get("downloaded"):
                self._emit(
                    logger,
                    "fulltext_download_rejected",
                    level="WARNING",
                    status=_text(attempt.get("status"), limit=80).upper() or "REJECTED",
                    canonical_paper_id=paper_id,
                    candidate=attempt,
                )
                self._remove_partial_pdf(pdf_path)
                continue

            try:
                pdf_sha256 = self._pdf_sha256(pdf_path)
            except OSError as exc:
                parser_audit = {
                    "backend": self.parser_backend,
                    "status": "parse_failed",
                    "failure_reason": type(exc).__name__,
                }
                markdown = ""
            else:
                parse_cache_identity = {
                    "pdf_sha256": pdf_sha256,
                    "parser_backend": self.parser_backend,
                    "parser_batch_size": self.parser_batch_size,
                }
                cached_parse = self.cache.read(
                    "pdf_markdown",
                    parse_cache_identity,
                    run_id=cache_run_id,
                )
                if cached_parse is not None:
                    markdown = _text(cached_parse.get("markdown"), limit=2_000_000)
                    parser_audit = dict(cached_parse.get("parser") or {})
                    parser_audit.update(
                        {
                            "backend": self.parser_backend,
                            "status": "cache_hit",
                            "pdf_sha256": pdf_sha256,
                            "source_location": f"fulltext:cache_pdf:{paper_id}:markdown",
                        }
                    )
                    self._emit(
                        logger,
                        "fulltext_parse_cache_hit",
                        status="CACHED",
                        canonical_paper_id=paper_id,
                        pdf_sha256=pdf_sha256,
                    )
                elif self.cache.offline:
                    markdown = ""
                    parser_audit = {
                        "backend": self.parser_backend,
                        "status": "cache_miss_read_only",
                        "pdf_sha256": pdf_sha256,
                    }
                else:
                    markdown, parser_audit = self._parse_pdf(paper_id, pdf_path, markdown_root)
                    parser_audit["pdf_sha256"] = pdf_sha256
                    if markdown:
                        self.cache.write(
                            "pdf_markdown",
                            parse_cache_identity,
                            {"markdown": markdown, "parser": parser_audit},
                            metadata={"pdf_sha256": pdf_sha256},
                            run_id=cache_run_id,
                        )
            audit["parser"] = parser_audit
            if not markdown:
                self._emit(
                    logger,
                    "fulltext_parse_failed",
                    level="WARNING",
                    status=_text(parser_audit.get("status"), limit=80).upper() or "PARSE_FAILED",
                    canonical_paper_id=paper_id,
                    parser=parser_audit,
                )
                audit["status"] = _text(parser_audit.get("status"), limit=80) or "parse_failed"
                self._emit(
                    logger,
                    "fulltext_acquisition_completed",
                    status=audit["status"].upper(),
                    canonical_paper_id=paper_id,
                    attempt_count=len(audit["attempts"]),
                    evidence_level="abstract_or_metadata",
                )
                return {"fulltext_acquisition": audit}

            source_location = _text(parser_audit.get("source_location"), limit=300)
            audit["status"] = "parsed"
            audit["selected_candidate"] = _safe_candidate(candidate)
            self._emit(
                logger,
                "fulltext_parse_completed",
                status="PARSED",
                canonical_paper_id=paper_id,
                parser=parser_audit,
            )
            self._emit(
                logger,
                "fulltext_acquisition_completed",
                status="PARSED",
                canonical_paper_id=paper_id,
                selected_source=_text(candidate.get("source"), limit=160),
                attempt_count=len(audit["attempts"]),
                evidence_level="fulltext",
            )
            return self._cache_acquisition_result(
                acquisition_cache_identity,
                {
                "fulltext": markdown,
                "fulltext_source_location": source_location,
                "content_availability": "fulltext",
                "fulltext_acquisition": audit,
                },
                cache_run_id=cache_run_id,
            )

        audit["status"] = self._final_status(audit["attempts"])
        self._emit(
            logger,
            "fulltext_acquisition_completed",
            status=audit["status"].upper(),
            canonical_paper_id=paper_id,
            attempt_count=len(audit["attempts"]),
            evidence_level="abstract_or_metadata",
        )
        return {"fulltext_acquisition": audit}


__all__ = [
    "FULLTEXT_ACQUISITION_SCHEMA_VERSION",
    "SurveyCompatibleFulltextAcquirer",
]
