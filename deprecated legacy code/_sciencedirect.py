"""ScienceDirect metadata discovery with project-safe provider controls.

The connector intentionally exposes only bibliographic metadata and publisher
landing URLs.  Those URLs still pass through the normal OA resolver, PDF
acquisition, full-text alignment, genre review, and evidence gates before a
paper can count as scientific evidence.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import json
import os
import random
import re
import shutil
import time
from pathlib import Path
from threading import Lock
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

try:
    from .config import (
        SCIENCEDIRECT_API_KEY,
        SCIENCE_PROVIDER_RATE_DIR,
        SCIENCE_SCIENCEDIRECT_API_URL,
        SCIENCE_SCIENCEDIRECT_CACHE_DIR,
        SCIENCE_SCIENCEDIRECT_CACHE_TTL_SECONDS,
        SCIENCE_SCIENCEDIRECT_ENABLED,
        SCIENCE_SCIENCEDIRECT_MAX_QPS,
        SCIENCE_SCIENCEDIRECT_RETRY_LIMIT,
        SCIENCE_SCIENCEDIRECT_RUN_REQUEST_LIMIT,
        SCIENCE_SCIENCEDIRECT_TIMEOUT_SECONDS,
    )
    from .log import log_event
except ImportError:
    from config import (
        SCIENCEDIRECT_API_KEY,
        SCIENCE_PROVIDER_RATE_DIR,
        SCIENCE_SCIENCEDIRECT_API_URL,
        SCIENCE_SCIENCEDIRECT_CACHE_DIR,
        SCIENCE_SCIENCEDIRECT_CACHE_TTL_SECONDS,
        SCIENCE_SCIENCEDIRECT_ENABLED,
        SCIENCE_SCIENCEDIRECT_MAX_QPS,
        SCIENCE_SCIENCEDIRECT_RETRY_LIMIT,
        SCIENCE_SCIENCEDIRECT_RUN_REQUEST_LIMIT,
        SCIENCE_SCIENCEDIRECT_TIMEOUT_SECONDS,
    )
    from log import log_event


SCIENCEDIRECT_RATE_SCOPE = hashlib.sha256(
    (SCIENCEDIRECT_API_KEY or "not_configured").encode("utf-8")
).hexdigest()[:16]
SCIENCEDIRECT_RATE_STATE_FILE = (
    SCIENCE_PROVIDER_RATE_DIR / f"sciencedirect_{SCIENCEDIRECT_RATE_SCOPE}.json"
)
SCIENCEDIRECT_PROCESS_LOCK_DIR = (
    SCIENCE_PROVIDER_RATE_DIR / f".sciencedirect_{SCIENCEDIRECT_RATE_SCOPE}.lock"
)
SCIENCEDIRECT_RATE_LOCK = Lock()
SCIENCEDIRECT_RUN_BUDGET_LOCK = Lock()
_YEAR_PATTERN = re.compile(r"\b(19|20)\d{2}\b")


@dataclass
class ScienceDirectRunBudget:
    run_id: str
    total_limit: int
    total_used: int = 0

    def snapshot(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "total_limit": self.total_limit,
            "total_used": self.total_used,
            "remaining": max(0, self.total_limit - self.total_used),
        }


SCIENCEDIRECT_RUN_BUDGET: ScienceDirectRunBudget | None = None


def sciencedirect_max_qps() -> float:
    """Return the configured rate, bounded to the connector's safe ceiling."""
    return min(2.0, max(0.1, float(SCIENCE_SCIENCEDIRECT_MAX_QPS)))


def sciencedirect_min_interval_seconds() -> float:
    return 1.0 / sciencedirect_max_qps()


def start_sciencedirect_run_budget(run_id: str = "") -> dict[str, Any]:
    global SCIENCEDIRECT_RUN_BUDGET
    with SCIENCEDIRECT_RUN_BUDGET_LOCK:
        SCIENCEDIRECT_RUN_BUDGET = ScienceDirectRunBudget(
            run_id=str(run_id or f"science_run_{int(time.time())}"),
            total_limit=max(1, int(SCIENCE_SCIENCEDIRECT_RUN_REQUEST_LIMIT)),
        )
        snapshot = SCIENCEDIRECT_RUN_BUDGET.snapshot()
    log_event("SCIENCE", "sciencedirect_run_budget_started", **snapshot)
    return snapshot


def sciencedirect_run_budget_status() -> dict[str, Any]:
    with SCIENCEDIRECT_RUN_BUDGET_LOCK:
        budget = SCIENCEDIRECT_RUN_BUDGET
        return budget.snapshot() if budget is not None else {"active": False}


def _reserve_sciencedirect_run_request() -> dict[str, Any]:
    with SCIENCEDIRECT_RUN_BUDGET_LOCK:
        budget = SCIENCEDIRECT_RUN_BUDGET
        if budget is None:
            return {"active": False}
        if budget.total_used >= budget.total_limit:
            raise RuntimeError(
                "sciencedirect_run_budget_exhausted: "
                f"total={budget.total_used}/{budget.total_limit}"
            )
        budget.total_used += 1
        return budget.snapshot()


def _normalized_doi(value: Any) -> str:
    doi = str(value or "").strip().lower()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        if doi.startswith(prefix):
            doi = doi[len(prefix):]
    return doi.rstrip(".,;)")


def _find_landing_url(entry: dict[str, Any], doi: str) -> str:
    for field in ("prism:url", "link"):
        value = entry.get(field)
        if isinstance(value, str) and value.strip().startswith(("http://", "https://")):
            return value.strip()
        if isinstance(value, list):
            preferred: list[tuple[int, str]] = []
            for item in value:
                if not isinstance(item, dict):
                    continue
                href = str(item.get("@href") or item.get("href") or "").strip()
                ref = str(item.get("@ref") or item.get("ref") or "").lower()
                if not href.startswith(("http://", "https://")):
                    continue
                priority = {"scidir": 0, "doi": 1, "self": 2}.get(ref)
                if priority is not None:
                    preferred.append((priority, href))
            if preferred:
                return min(preferred, key=lambda item: item[0])[1]
    return f"https://doi.org/{doi}" if doi else ""


def _authors(entry: dict[str, Any]) -> list[str]:
    raw = entry.get("dc:creator") or entry.get("authors") or ""
    if isinstance(raw, list):
        values = raw
    else:
        values = re.split(r"\s*;\s*", str(raw))
    return [str(value).strip() for value in values if str(value).strip()]


def sciencedirect_entry_to_result(entry: dict[str, Any]) -> dict[str, Any]:
    """Normalize one Elsevier ScienceDirect search entry into the project schema."""
    try:
        from ._literature_import import build_citation
        from ._utils import normalize_space
    except ImportError:
        from _literature_import import build_citation
        from _utils import normalize_space

    title = normalize_space(str(entry.get("dc:title") or entry.get("title") or ""))
    abstract = normalize_space(str(entry.get("dc:description") or entry.get("description") or ""))
    doi = _normalized_doi(entry.get("prism:doi") or entry.get("doi"))
    cover_date = str(entry.get("prism:coverDate") or entry.get("coverDate") or "").strip()
    year_match = _YEAR_PATTERN.search(cover_date)
    year = year_match.group(0) if year_match else ""
    venue = normalize_space(str(entry.get("prism:publicationName") or entry.get("publicationName") or ""))
    eid = str(entry.get("eid") or entry.get("dc:identifier") or "").strip()
    authors = _authors(entry)
    citation_count = int(entry.get("citedby-count") or entry.get("citationCount") or 0)
    publication_type = normalize_space(
        str(entry.get("prism:aggregationType") or entry.get("subtypeDescription") or "journal article")
    )
    landing_url = _find_landing_url(entry, doi)
    citation = build_citation(title=title, authors=authors, year=year, doi=doi, arxiv_id="")
    citation_metrics = {
        "sciencedirect": {
            "cited_by_count": citation_count,
            "cover_date": cover_date,
            "eid": eid,
        }
    }
    external_ids = {
        "doi": doi,
        "sciencedirect_eid": eid,
    }
    provider_provenance = {
        "discovery_provider": "sciencedirect",
        "sciencedirect_eid": eid,
        "metadata_only_discovery": True,
    }
    papergraph_input = {
        "title": title,
        "citation": citation,
        "authors": authors,
        "year": year,
        "venue": venue,
        "provider": "sciencedirect",
        "source_type": "api",
        "doi": doi,
        "url": landing_url,
        "abstract": abstract,
        # The ScienceDirect search endpoint does not establish OA status or
        # furnish a PDF.  Leave this empty for the shared resolver chain.
        "open_access_pdf": "",
        "publication_types": [publication_type] if publication_type else [],
        "provider_provenance": provider_provenance,
        "external_ids": external_ids,
        "citation_metrics": citation_metrics,
        "venue_metadata": {"provider": "sciencedirect", "source_type": "journal"},
    }
    return {
        **papergraph_input,
        "sciencedirect_eid": eid,
        "is_open_access": False,
        "citation_count": citation_count,
        "reference_count": 0,
        "papergraph_input": papergraph_input,
    }


def _cache_key(*, query: str, count: int, start: int) -> str:
    material = json.dumps(
        {
            "scope": SCIENCEDIRECT_RATE_SCOPE,
            "query": str(query or "").strip().lower(),
            "count": int(count),
            "start": int(start),
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _cache_path(cache_key: str) -> Path:
    return SCIENCE_SCIENCEDIRECT_CACHE_DIR / f"{cache_key}.json"


def _read_cached_response(cache_key: str) -> dict[str, Any] | None:
    try:
        payload = json.loads(_cache_path(cache_key).read_text(encoding="utf-8"))
        if time.time() - float(payload.get("cached_at") or 0.0) > SCIENCE_SCIENCEDIRECT_CACHE_TTL_SECONDS:
            return None
        response = payload.get("response")
        return response if isinstance(response, dict) else None
    except (OSError, ValueError, TypeError):
        return None


def _write_cached_response(cache_key: str, response: dict[str, Any]) -> None:
    path = _cache_path(cache_key)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps({"cached_at": time.time(), "response": response}, ensure_ascii=False),
            encoding="utf-8",
        )
        os.replace(temporary, path)
    except OSError as exc:
        log_event("SCIENCE", "sciencedirect_cache_write_failed", error=str(exc)[:200])


def _read_rate_state() -> dict[str, Any]:
    try:
        payload = json.loads(SCIENCEDIRECT_RATE_STATE_FILE.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def _write_rate_state(state: dict[str, Any]) -> None:
    try:
        SCIENCEDIRECT_RATE_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        temporary = SCIENCEDIRECT_RATE_STATE_FILE.with_suffix(".tmp")
        temporary.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
        os.replace(temporary, SCIENCEDIRECT_RATE_STATE_FILE)
    except OSError as exc:
        log_event("SCIENCE", "sciencedirect_rate_state_write_failed", error=str(exc)[:200])


@contextmanager
def _sciencedirect_process_lock():
    SCIENCEDIRECT_PROCESS_LOCK_DIR.parent.mkdir(parents=True, exist_ok=True)
    while True:
        try:
            SCIENCEDIRECT_PROCESS_LOCK_DIR.mkdir()
            break
        except FileExistsError:
            try:
                if time.time() - SCIENCEDIRECT_PROCESS_LOCK_DIR.stat().st_mtime > 30.0:
                    shutil.rmtree(SCIENCEDIRECT_PROCESS_LOCK_DIR, ignore_errors=True)
                    continue
            except OSError:
                pass
            time.sleep(0.02)
    try:
        yield
    finally:
        shutil.rmtree(SCIENCEDIRECT_PROCESS_LOCK_DIR, ignore_errors=True)


def _reserve_global_sciencedirect_slot() -> float:
    with SCIENCEDIRECT_RATE_LOCK:
        with _sciencedirect_process_lock():
            state = _read_rate_state()
            last = float(state.get("last_request_wall_time") or 0.0)
            delay = max(0.0, last + sciencedirect_min_interval_seconds() - time.time())
            if delay:
                time.sleep(delay)
            timestamp = time.time()
            _write_rate_state(
                {
                    "last_request_wall_time": timestamp,
                    "max_qps": sciencedirect_max_qps(),
                    "min_interval_seconds": sciencedirect_min_interval_seconds(),
                }
            )
    return delay


def _http_get_json(url: str, *, timeout: float) -> tuple[dict[str, Any], dict[str, str]]:
    request = Request(
        url,
        headers={
            "Accept": "application/json",
            "X-ELS-APIKey": SCIENCEDIRECT_API_KEY,
            "User-Agent": "qwen-ai-scientist/1.0 (ScienceDirect metadata discovery)",
        },
    )
    with urlopen(request, timeout=timeout) as response:  # nosec B310 -- configured scholarly API endpoint
        payload = json.loads(response.read().decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("ScienceDirect response was not a JSON object")
        return payload, {str(key).lower(): str(value) for key, value in response.headers.items()}


def _retry_after_seconds(value: Any) -> float:
    try:
        return max(0.0, min(120.0, float(value)))
    except (TypeError, ValueError):
        return 0.0


def _is_retryable_http_status(status: int) -> bool:
    return status == 429 or 500 <= status <= 599


def _retry_wait_seconds(attempt: int, retry_after: float) -> float:
    if retry_after:
        return retry_after
    return min(30.0, (2.0 ** attempt) + random.uniform(0.0, 0.4))


def search_sciencedirect(
    query: str,
    *,
    max_results: int = 25,
    start: int = 0,
) -> dict[str, Any]:
    """Search the ScienceDirect API without treating results as full text."""
    selected_count = max(1, min(100, int(max_results)))
    selected_start = max(0, int(start))
    if not SCIENCE_SCIENCEDIRECT_ENABLED:
        return {"provider": "sciencedirect", "query": query, "status": "disabled", "results": []}
    if not SCIENCEDIRECT_API_KEY:
        return {
            "provider": "sciencedirect",
            "query": query,
            "status": "not_configured",
            "results": [],
            "error": "SCIENCEDIRECT_API_KEY is required for ScienceDirect API requests.",
        }
    cache_key = _cache_key(query=query, count=selected_count, start=selected_start)
    cached = _read_cached_response(cache_key)
    if cached is not None:
        entries = ((cached.get("search-results") or {}).get("entry") or [])
        results = [sciencedirect_entry_to_result(item) for item in entries if isinstance(item, dict)]
        log_event("SCIENCE", "sciencedirect_cache_hit", query=query[:180], result_count=len(results))
        return {
            "provider": "sciencedirect",
            "query": query,
            "status": "ok",
            "results": results[:selected_count],
            "cache_hit": True,
            "api": "api.elsevier.com/content/search/sciencedirect",
        }

    params = {"query": str(query), "count": str(selected_count), "start": str(selected_start), "sort": "relevance"}
    url = f"{SCIENCE_SCIENCEDIRECT_API_URL}?{urlencode(params)}"
    last_error = ""
    for attempt in range(SCIENCE_SCIENCEDIRECT_RETRY_LIMIT + 1):
        try:
            budget = _reserve_sciencedirect_run_request()
        except RuntimeError as exc:
            return {
                "provider": "sciencedirect",
                "query": query,
                "status": "run_budget_exhausted",
                "error": str(exc),
                "results": [],
            }
        delay = _reserve_global_sciencedirect_slot()
        if delay:
            log_event(
                "SCIENCE",
                "sciencedirect_rate_limit_wait",
                wait_ms=round(delay * 1000.0, 1),
                max_qps=sciencedirect_max_qps(),
            )
        try:
            payload, _headers = _http_get_json(url, timeout=SCIENCE_SCIENCEDIRECT_TIMEOUT_SECONDS)
            _write_cached_response(cache_key, payload)
            entries = ((payload.get("search-results") or {}).get("entry") or [])
            results = [sciencedirect_entry_to_result(item) for item in entries if isinstance(item, dict)]
            log_event(
                "SCIENCE",
                "sciencedirect_request_complete",
                query=query[:180],
                result_count=len(results),
                attempt=attempt + 1,
                **budget,
            )
            return {
                "provider": "sciencedirect",
                "query": query,
                "status": "ok",
                "results": results[:selected_count],
                "cache_hit": False,
                "api": "api.elsevier.com/content/search/sciencedirect",
            }
        except HTTPError as exc:
            last_error = f"HTTP {exc.code}: {str(exc.reason or '')}".strip()
            if not _is_retryable_http_status(int(exc.code)) or attempt >= SCIENCE_SCIENCEDIRECT_RETRY_LIMIT:
                break
            wait = _retry_wait_seconds(
                attempt,
                _retry_after_seconds(exc.headers.get("Retry-After") if exc.headers else None),
            )
            log_event(
                "SCIENCE",
                "sciencedirect_retry_scheduled",
                http_status=exc.code,
                attempt=attempt + 1,
                wait_seconds=round(wait, 2),
            )
            time.sleep(wait)
        except (URLError, TimeoutError, OSError) as exc:
            last_error = str(exc)
            if attempt >= SCIENCE_SCIENCEDIRECT_RETRY_LIMIT:
                break
            wait = _retry_wait_seconds(attempt, 0.0)
            log_event(
                "SCIENCE",
                "sciencedirect_retry_scheduled",
                error_class=type(exc).__name__,
                attempt=attempt + 1,
                wait_seconds=round(wait, 2),
            )
            time.sleep(wait)
        except (ValueError, TypeError) as exc:
            last_error = str(exc)
            break
    log_event("SCIENCE", "sciencedirect_request_failed", query=query[:180], error=last_error[:240])
    return {
        "provider": "sciencedirect",
        "query": query,
        "status": "error",
        "error": last_error,
        "results": [],
    }
