"""OpenAlex broad-discovery provider.

This module deliberately owns OpenAlex transport concerns instead of placing
another cursor/cache/rate-limit implementation in ``_literature_search``.
Results are normalized into the existing literature-result contract so that
ranking, stratification, alignment gates, and import remain shared with every
other provider.
"""
from __future__ import annotations

import hashlib
import json
import os
import random
import shutil
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

try:
    from .config import (
        OPENALEX_API_KEY,
        SCIENCE_OPENALEX_API_URL,
        SCIENCE_OPENALEX_CACHE_DIR,
        SCIENCE_OPENALEX_CACHE_TTL_SECONDS,
        SCIENCE_OPENALEX_ENABLED,
        SCIENCE_OPENALEX_MAILTO,
        SCIENCE_OPENALEX_MAX_PAGES_PER_BRANCH,
        SCIENCE_OPENALEX_MAX_QPS,
        SCIENCE_OPENALEX_PER_PAGE,
        SCIENCE_OPENALEX_RETRY_LIMIT,
        SCIENCE_OPENALEX_RUN_REQUEST_LIMIT,
        SCIENCE_PROVIDER_RATE_DIR,
    )
    from .log import log_event
except ImportError:
    from config import (
        OPENALEX_API_KEY,
        SCIENCE_OPENALEX_API_URL,
        SCIENCE_OPENALEX_CACHE_DIR,
        SCIENCE_OPENALEX_CACHE_TTL_SECONDS,
        SCIENCE_OPENALEX_ENABLED,
        SCIENCE_OPENALEX_MAILTO,
        SCIENCE_OPENALEX_MAX_PAGES_PER_BRANCH,
        SCIENCE_OPENALEX_MAX_QPS,
        SCIENCE_OPENALEX_PER_PAGE,
        SCIENCE_OPENALEX_RETRY_LIMIT,
        SCIENCE_OPENALEX_RUN_REQUEST_LIMIT,
        SCIENCE_PROVIDER_RATE_DIR,
    )
    from log import log_event


OPENALEX_RATE_SCOPE = hashlib.sha256((OPENALEX_API_KEY or "anonymous").encode("utf-8")).hexdigest()[:16]
OPENALEX_RATE_STATE_FILE = SCIENCE_PROVIDER_RATE_DIR / f"openalex_{OPENALEX_RATE_SCOPE}.json"
OPENALEX_PROCESS_LOCK_DIR = SCIENCE_PROVIDER_RATE_DIR / f".openalex_{OPENALEX_RATE_SCOPE}.lock"
OPENALEX_RATE_LOCK = Lock()
OPENALEX_RUN_BUDGET_LOCK = Lock()


@dataclass
class OpenAlexRunBudget:
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


OPENALEX_RUN_BUDGET: OpenAlexRunBudget | None = None


def openalex_max_qps() -> float:
    """The configuration may lower but can never raise the six-QPS ceiling."""
    return min(6.0, max(0.1, float(SCIENCE_OPENALEX_MAX_QPS)))


def openalex_min_interval_seconds() -> float:
    return 1.0 / openalex_max_qps()


def openalex_retry_limit() -> int:
    """Bound OpenAlex attempts so 429/503 recovery does not burn run budget."""
    try:
        return max(1, min(3, int(SCIENCE_OPENALEX_RETRY_LIMIT)))
    except (TypeError, ValueError):
        return 1


def start_openalex_run_budget(run_id: str = "") -> dict[str, Any]:
    global OPENALEX_RUN_BUDGET
    with OPENALEX_RUN_BUDGET_LOCK:
        OPENALEX_RUN_BUDGET = OpenAlexRunBudget(
            run_id=str(run_id or f"science_run_{int(time.time())}"),
            total_limit=max(1, int(SCIENCE_OPENALEX_RUN_REQUEST_LIMIT)),
        )
        snapshot = OPENALEX_RUN_BUDGET.snapshot()
    log_event("SCIENCE", "openalex_run_budget_started", **snapshot, max_qps=openalex_max_qps())
    return snapshot


def openalex_run_budget_status() -> dict[str, Any]:
    with OPENALEX_RUN_BUDGET_LOCK:
        budget = OPENALEX_RUN_BUDGET
        return budget.snapshot() if budget is not None else {"active": False}


def reserve_openalex_run_request() -> dict[str, Any]:
    with OPENALEX_RUN_BUDGET_LOCK:
        budget = OPENALEX_RUN_BUDGET
        if budget is None:
            return {"active": False}
        if budget.total_used >= budget.total_limit:
            raise RuntimeError(
                f"openalex_run_budget_exhausted: total={budget.total_used}/{budget.total_limit}"
            )
        budget.total_used += 1
        return budget.snapshot()


def openalex_abstract_to_text(inverted_index: Any) -> str:
    """Reconstruct the OpenAlex inverted abstract without assuming contiguity."""
    if not isinstance(inverted_index, dict):
        return ""
    positioned: list[tuple[int, str]] = []
    for token, positions in inverted_index.items():
        if not isinstance(token, str) or not isinstance(positions, list):
            continue
        for position in positions:
            try:
                positioned.append((int(position), token))
            except (TypeError, ValueError):
                continue
    return " ".join(token for _position, token in sorted(positioned, key=lambda item: item[0])).strip()


def normalize_openalex_doi(value: Any) -> str:
    raw = str(value or "").strip()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        if raw.lower().startswith(prefix):
            raw = raw[len(prefix):]
    return raw.strip().lower()


def normalized_openalex_id(work: dict[str, Any]) -> str:
    ids = work.get("ids") if isinstance(work.get("ids"), dict) else {}
    return str(work.get("id") or ids.get("openalex") or "").strip()


def openalex_work_to_result(work: dict[str, Any]) -> dict[str, Any]:
    """Map one Works response into the provider-neutral papergraph contract."""
    try:
        from ._literature_import import build_citation
        from ._utils import normalize_space
    except ImportError:
        from _literature_import import build_citation
        from _utils import normalize_space

    title = normalize_space(str(work.get("display_name") or work.get("title") or ""))
    authorships = work.get("authorships") if isinstance(work.get("authorships"), list) else []
    authors = [
        normalize_space(str((item.get("author") or {}).get("display_name") or ""))
        for item in authorships
        if isinstance(item, dict)
    ]
    authors = [author for author in authors if author]
    doi = normalize_openalex_doi(work.get("doi"))
    year = str(work.get("publication_year") or "")
    primary_location = work.get("primary_location") if isinstance(work.get("primary_location"), dict) else {}
    best_oa_location = work.get("best_oa_location") if isinstance(work.get("best_oa_location"), dict) else {}
    source = primary_location.get("source") if isinstance(primary_location.get("source"), dict) else {}
    best_source = best_oa_location.get("source") if isinstance(best_oa_location.get("source"), dict) else {}
    venue = normalize_space(str(source.get("display_name") or best_source.get("display_name") or ""))
    venue_source = source or best_source
    venue_metadata = {
        "provider": "openalex",
        "source_id": str(venue_source.get("id") or "").strip(),
        "source_type": str(venue_source.get("type") or "").strip().lower(),
        "issn_l": str(venue_source.get("issn_l") or "").strip(),
        "is_core": bool(venue_source.get("is_core")),
        "is_in_doaj": bool(venue_source.get("is_in_doaj")),
        "is_oa": bool(venue_source.get("is_oa")),
    }
    landing_url = str(
        best_oa_location.get("landing_page_url")
        or primary_location.get("landing_page_url")
        or (f"https://doi.org/{doi}" if doi else "")
    ).strip()
    open_access = work.get("open_access") if isinstance(work.get("open_access"), dict) else {}
    open_access_pdf = str(
        best_oa_location.get("pdf_url")
        or primary_location.get("pdf_url")
        or open_access.get("oa_url")
        or ""
    ).strip()
    publication_types = [
        str(value)
        for value in (work.get("type"), work.get("type_crossref"), work.get("type_repository"))
        if str(value or "").strip()
    ]
    topics = [
        str(item.get("display_name") or "")
        for item in (work.get("topics") or [])
        if isinstance(item, dict) and str(item.get("display_name") or "").strip()
    ]
    concepts = [
        str(item.get("display_name") or "")
        for item in (work.get("concepts") or [])
        if isinstance(item, dict) and str(item.get("display_name") or "").strip()
    ]
    openalex_id = normalized_openalex_id(work)
    cited_by_count = int(work.get("cited_by_count") or 0)
    referenced_works_count = int(work.get("referenced_works_count") or 0)
    abstract = openalex_abstract_to_text(work.get("abstract_inverted_index"))
    citation = build_citation(title=title, authors=authors, year=year, doi=doi, arxiv_id="")
    citation_metrics = {
        "openalex": {
            "cited_by_count": cited_by_count,
            "referenced_works_count": referenced_works_count,
            "counts_by_year": work.get("counts_by_year") if isinstance(work.get("counts_by_year"), list) else [],
            "fwci": work.get("fwci"),
            "citation_normalized_percentile": (
                work.get("citation_normalized_percentile")
                if isinstance(work.get("citation_normalized_percentile"), dict)
                else {}
            ),
            "cited_by_percentile_year": (
                work.get("cited_by_percentile_year")
                if isinstance(work.get("cited_by_percentile_year"), dict)
                else {}
            ),
        }
    }
    work_ids = work.get("ids") if isinstance(work.get("ids"), dict) else {}
    external_ids = {
        "openalex": openalex_id,
        "doi": doi,
        "pmid": str((work_ids.get("pmid") or "")).strip(),
        "pmcid": str((work_ids.get("pmcid") or work_ids.get("pmc") or "")).strip(),
        "mag": str((work_ids.get("mag") or "")).strip(),
    }
    input_payload = {
        "title": title,
        "citation": citation,
        "authors": authors,
        "year": year,
        "venue": venue,
        "provider": "openalex",
        "source_type": "api",
        "doi": doi,
        "openalex_id": openalex_id,
        "url": landing_url,
        "abstract": abstract,
        "open_access_pdf": open_access_pdf,
        "publication_types": publication_types,
        "provider_provenance": {"discovery_provider": "openalex", "openalex_id": openalex_id},
        "external_ids": external_ids,
        "citation_metrics": citation_metrics,
        "venue_metadata": venue_metadata,
        "topics": topics,
        "concepts": concepts,
    }
    return {
        "title": title,
        "citation": citation,
        "authors": authors,
        "year": year,
        "venue": venue,
        "provider": "openalex",
        "source_type": "api",
        "doi": doi,
        "openalex_id": openalex_id,
        "url": landing_url,
        "open_access_pdf": open_access_pdf,
        "is_open_access": bool(open_access.get("is_oa")),
        "citation_count": cited_by_count,
        "reference_count": referenced_works_count,
        "citation_metrics": citation_metrics,
        "venue_metadata": venue_metadata,
        "external_ids": external_ids,
        "provider_provenance": input_payload["provider_provenance"],
        "topics": topics,
        "concepts": concepts,
        "publication_types": publication_types,
        "abstract": abstract,
        "papergraph_input": input_payload,
    }


def _cache_key(*, query: str, cursor: str, per_page: int, filters: str) -> str:
    material = json.dumps(
        {
            "scope": OPENALEX_RATE_SCOPE,
            "query": str(query or "").strip().lower(),
            "cursor": str(cursor or ""),
            "per_page": int(per_page),
            "filters": str(filters or ""),
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _cache_path(cache_key: str) -> Path:
    return SCIENCE_OPENALEX_CACHE_DIR / f"{cache_key}.json"


def _read_cached_response(cache_key: str) -> dict[str, Any] | None:
    path = _cache_path(cache_key)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        cached_at = float(payload.get("cached_at") or 0.0)
        if time.time() - cached_at > SCIENCE_OPENALEX_CACHE_TTL_SECONDS:
            return None
        response = payload.get("response")
        return response if isinstance(response, dict) else None
    except (OSError, ValueError, TypeError):
        return None


def _write_cached_response(cache_key: str, response: dict[str, Any]) -> None:
    path = _cache_path(cache_key)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = path.with_suffix(".tmp")
        temp_path.write_text(
            json.dumps({"cached_at": time.time(), "response": response}, ensure_ascii=False),
            encoding="utf-8",
        )
        os.replace(temp_path, path)
    except OSError as exc:
        log_event("SCIENCE", "openalex_cache_write_failed", path=str(path), error=str(exc)[:200])


def _read_rate_state() -> dict[str, Any]:
    try:
        payload = json.loads(OPENALEX_RATE_STATE_FILE.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def _write_rate_state(state: dict[str, Any]) -> None:
    try:
        OPENALEX_RATE_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        temporary = OPENALEX_RATE_STATE_FILE.with_suffix(".tmp")
        temporary.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
        os.replace(temporary, OPENALEX_RATE_STATE_FILE)
    except OSError as exc:
        log_event("SCIENCE", "openalex_rate_state_write_failed", error=str(exc)[:200])


@contextmanager
def _openalex_process_lock():
    OPENALEX_PROCESS_LOCK_DIR.parent.mkdir(parents=True, exist_ok=True)
    while True:
        try:
            OPENALEX_PROCESS_LOCK_DIR.mkdir()
            break
        except FileExistsError:
            try:
                if time.time() - OPENALEX_PROCESS_LOCK_DIR.stat().st_mtime > 30.0:
                    shutil.rmtree(OPENALEX_PROCESS_LOCK_DIR, ignore_errors=True)
                    continue
            except OSError:
                pass
            time.sleep(0.02)
    try:
        yield
    finally:
        shutil.rmtree(OPENALEX_PROCESS_LOCK_DIR, ignore_errors=True)


def _reserve_global_openalex_slot() -> float:
    """Serialize every workspace using this credential and enforce <= 6 QPS."""
    with OPENALEX_RATE_LOCK:
        with _openalex_process_lock():
            state = _read_rate_state()
            last = float(state.get("last_request_wall_time") or 0.0)
            delay = max(0.0, last + openalex_min_interval_seconds() - time.time())
            if delay:
                time.sleep(delay)
            timestamp = time.time()
            _write_rate_state(
                {
                    "last_request_wall_time": timestamp,
                    "max_qps": openalex_max_qps(),
                    "min_interval_seconds": openalex_min_interval_seconds(),
                }
            )
    return delay


def _parse_retry_after(value: Any) -> float:
    try:
        return max(0.0, min(60.0, float(value)))
    except (TypeError, ValueError):
        return 0.0


def _openalex_http_get_json(url: str, *, timeout: float = 30.0) -> tuple[dict[str, Any], dict[str, str]]:
    request = Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "qwen-ai-scientist/1.0 (OpenAlex discovery)",
        },
    )
    with urlopen(request, timeout=timeout) as response:  # nosec B310 -- a configured scholarly API endpoint
        body = response.read().decode("utf-8")
        payload = json.loads(body)
        if not isinstance(payload, dict):
            raise ValueError("OpenAlex response was not a JSON object")
        return payload, {str(key).lower(): str(value) for key, value in response.headers.items()}


def search_openalex_works(
    query: str,
    *,
    max_results: int = 100,
    cursor: str = "*",
    per_page: int | None = None,
    filters: str = "",
) -> dict[str, Any]:
    """Search one OpenAlex Works page with persistent cache and bounded retry."""
    selected_per_page = max(1, min(100, int(per_page or min(max_results, SCIENCE_OPENALEX_PER_PAGE))))
    if not SCIENCE_OPENALEX_ENABLED:
        return {"provider": "openalex", "query": query, "status": "disabled", "results": []}
    if not OPENALEX_API_KEY:
        return {
            "provider": "openalex",
            "query": query,
            "status": "not_configured",
            "results": [],
            "error": "OPENALEX_API_KEY is required for OpenAlex API requests.",
        }
    cache_key = _cache_key(query=query, cursor=cursor, per_page=selected_per_page, filters=filters)
    cached = _read_cached_response(cache_key)
    if cached is not None:
        raw_results = cached.get("results") if isinstance(cached.get("results"), list) else []
        results = [openalex_work_to_result(item) for item in raw_results if isinstance(item, dict)]
        log_event("SCIENCE", "openalex_cache_hit", query=query[:180], cursor=cursor, result_count=len(results))
        return {
            "provider": "openalex",
            "query": query,
            "status": "ok",
            "results": results[:max_results],
            "next_cursor": str((cached.get("meta") or {}).get("next_cursor") or ""),
            "cache_hit": True,
            "api": "api.openalex.org/works",
        }

    params: dict[str, str] = {
        "search": query,
        "per-page": str(selected_per_page),
        "cursor": str(cursor or "*"),
        "api_key": OPENALEX_API_KEY,
    }
    if filters:
        params["filter"] = filters
    if SCIENCE_OPENALEX_MAILTO:
        params["mailto"] = SCIENCE_OPENALEX_MAILTO
    url = f"{SCIENCE_OPENALEX_API_URL}?{urlencode(params)}"
    last_error = ""
    retry_limit = openalex_retry_limit()
    for attempt in range(retry_limit):
        try:
            budget = reserve_openalex_run_request()
        except RuntimeError as exc:
            return {
                "provider": "openalex",
                "query": query,
                "status": "run_budget_exhausted",
                "error": str(exc),
                "results": [],
            }
        delay = _reserve_global_openalex_slot()
        if delay:
            log_event("SCIENCE", "openalex_rate_limit_wait", wait_ms=round(delay * 1000.0, 1), max_qps=openalex_max_qps())
        try:
            payload, _headers = _openalex_http_get_json(url)
            _write_cached_response(cache_key, payload)
            raw_results = payload.get("results") if isinstance(payload.get("results"), list) else []
            results = [openalex_work_to_result(item) for item in raw_results if isinstance(item, dict)]
            log_event(
                "SCIENCE",
                "openalex_request_complete",
                query=query[:180],
                cursor=cursor,
                result_count=len(results),
                attempt=attempt + 1,
                retry_limit=retry_limit,
                **budget,
            )
            return {
                "provider": "openalex",
                "query": query,
                "status": "ok",
                "results": results[:max_results],
                "next_cursor": str((payload.get("meta") or {}).get("next_cursor") or ""),
                "cache_hit": False,
                "api": "api.openalex.org/works",
            }
        except HTTPError as exc:
            last_error = f"HTTP {exc.code}: {str(exc.reason or '')}".strip()
            retry_after = _parse_retry_after(exc.headers.get("Retry-After") if exc.headers else None)
            if exc.code not in {429, 503} or attempt >= retry_limit - 1:
                break
            wait = retry_after or min(20.0, (2.0 ** attempt) + random.uniform(0.0, 0.4))
            log_event("SCIENCE", "openalex_retry_scheduled", http_status=exc.code, attempt=attempt + 1, wait_seconds=round(wait, 2))
            time.sleep(wait)
        except (URLError, TimeoutError, ValueError, OSError) as exc:
            last_error = str(exc)
            break
    log_event("SCIENCE", "openalex_request_failed", query=query[:180], error=last_error[:240])
    return {"provider": "openalex", "query": query, "status": "error", "error": last_error, "results": []}


def fetch_openalex_work_by_doi(doi: str) -> dict[str, Any]:
    """Resolve one DOI to provider-native venue and normalized-impact metadata.

    This is deliberately a detail lookup, not another keyword-search branch.
    It is used only for a bounded set of already-selected formal papers whose
    source record lacks the metadata needed to distinguish venue calibre from
    the paper's role in the current sub-hypothesis.
    """
    normalized_doi = normalize_openalex_doi(doi)
    if not normalized_doi:
        return {
            "provider": "openalex",
            "status": "invalid_identifier",
            "doi": "",
            "result": None,
        }
    if not SCIENCE_OPENALEX_ENABLED:
        return {
            "provider": "openalex",
            "status": "disabled",
            "doi": normalized_doi,
            "result": None,
        }
    if not OPENALEX_API_KEY:
        return {
            "provider": "openalex",
            "status": "not_configured",
            "doi": normalized_doi,
            "result": None,
            "error": "OPENALEX_API_KEY is required for OpenAlex API requests.",
        }
    cache_key = _cache_key(
        query=f"doi:{normalized_doi}",
        cursor="doi_detail",
        per_page=1,
        filters="openalex_work_by_doi_v1",
    )
    cached = _read_cached_response(cache_key)
    if cached is not None:
        result = openalex_work_to_result(cached)
        log_event(
            "SCIENCE",
            "openalex_doi_metadata_cache_hit",
            doi=normalized_doi,
            openalex_id=result.get("openalex_id", ""),
        )
        return {
            "provider": "openalex",
            "status": "ok",
            "doi": normalized_doi,
            "result": result,
            "cache_hit": True,
            "api": "api.openalex.org/works/{doi}",
        }

    params = {"api_key": OPENALEX_API_KEY}
    if SCIENCE_OPENALEX_MAILTO:
        params["mailto"] = SCIENCE_OPENALEX_MAILTO
    identifier = quote(f"https://doi.org/{normalized_doi}", safe="")
    url = f"{SCIENCE_OPENALEX_API_URL}/{identifier}?{urlencode(params)}"
    last_error = ""
    retry_limit = openalex_retry_limit()
    for attempt in range(retry_limit):
        try:
            budget = reserve_openalex_run_request()
        except RuntimeError as exc:
            return {
                "provider": "openalex",
                "status": "run_budget_exhausted",
                "doi": normalized_doi,
                "result": None,
                "error": str(exc),
            }
        delay = _reserve_global_openalex_slot()
        if delay:
            log_event(
                "SCIENCE",
                "openalex_rate_limit_wait",
                wait_ms=round(delay * 1000.0, 1),
                max_qps=openalex_max_qps(),
            )
        try:
            work, _headers = _openalex_http_get_json(url)
            _write_cached_response(cache_key, work)
            result = openalex_work_to_result(work)
            log_event(
                "SCIENCE",
                "openalex_doi_metadata_complete",
                doi=normalized_doi,
                openalex_id=result.get("openalex_id", ""),
                attempt=attempt + 1,
                retry_limit=retry_limit,
                **budget,
            )
            return {
                "provider": "openalex",
                "status": "ok",
                "doi": normalized_doi,
                "result": result,
                "cache_hit": False,
                "api": "api.openalex.org/works/{doi}",
            }
        except HTTPError as exc:
            last_error = f"HTTP {exc.code}: {str(exc.reason or '')}".strip()
            retry_after = _parse_retry_after(exc.headers.get("Retry-After") if exc.headers else None)
            if exc.code not in {429, 503} or attempt >= retry_limit - 1:
                break
            wait = retry_after or min(20.0, (2.0 ** attempt) + random.uniform(0.0, 0.4))
            log_event(
                "SCIENCE",
                "openalex_doi_metadata_retry_scheduled",
                doi=normalized_doi,
                http_status=exc.code,
                attempt=attempt + 1,
                wait_seconds=round(wait, 2),
            )
            time.sleep(wait)
        except (URLError, TimeoutError, ValueError, OSError) as exc:
            last_error = str(exc)
            break
    log_event("SCIENCE", "openalex_doi_metadata_failed", doi=normalized_doi, error=last_error[:240])
    return {
        "provider": "openalex",
        "status": "error",
        "doi": normalized_doi,
        "result": None,
        "error": last_error,
    }


def search_openalex_discovery_batch(
    query_plan: list[dict[str, Any]],
    *,
    max_pages_per_branch: int | None = None,
    per_page: int | None = None,
    filters: str = "",
    discipline_filter_audit: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Fetch one broad candidate pool per semantic branch, not once per layer."""
    branch_pages = max(
        1,
        min(50, int(max_pages_per_branch or SCIENCE_OPENALEX_MAX_PAGES_PER_BRANCH)),
    )
    selected_per_page = max(1, min(100, int(per_page or SCIENCE_OPENALEX_PER_PAGE)))
    blocks: list[dict[str, Any]] = []
    for plan in query_plan:
        if not isinstance(plan, dict):
            continue
        branch = str(plan.get("branch") or "primary")
        query = str(plan.get("query") or "").strip()
        if not query:
            continue
        cursor = "*"
        for page_number in range(1, branch_pages + 1):
            block = search_openalex_works(
                query,
                max_results=selected_per_page,
                cursor=cursor,
                per_page=selected_per_page,
                filters=filters,
            )
            block["query_branch"] = branch
            block["retrieval_strategy"] = "openalex_broad_discovery"
            block["discipline_filter_audit"] = dict(discipline_filter_audit or {})
            block["provider_batch_page"] = page_number
            block["provider_batch_max_pages"] = branch_pages
            blocks.append(block)
            cursor = str(block.get("next_cursor") or "")
            if str(block.get("status") or "") != "ok" or not cursor:
                break
    log_event(
        "SCIENCE",
        "openalex_discovery_batch_complete",
        branches=len({str(item.get("query_branch") or "") for item in blocks}),
        blocks=len(blocks),
        result_count=sum(len(block.get("results") or []) for block in blocks),
        max_pages_per_branch=branch_pages,
        per_page=selected_per_page,
        request_ceiling=len(
            [
                item
                for item in query_plan
                if isinstance(item, dict) and str(item.get("query") or "").strip()
            ]
        )
        * branch_pages,
        max_qps=openalex_max_qps(),
    )
    return blocks
