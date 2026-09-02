"""Retired Academic MCP OA adapter retained for state compatibility.

Production code hard-disables this adapter. Parser helpers remain so older
persisted audits stay readable, but the public resolver performs no cache or
network access and always returns an empty hard-disabled result.
"""
from __future__ import annotations

from typing import Any, Callable
from urllib.parse import quote, urlencode, urlsplit
import re

try:
    from .config import (
        CORE_API_KEY,
        SCIENCE_ACADEMIC_MCP_OA_CORE_API_URL,
        SCIENCE_ACADEMIC_MCP_OA_CORE_ENABLED,
        SCIENCE_ACADEMIC_MCP_OA_ENABLED,
        SCIENCE_ACADEMIC_MCP_OA_HARD_DISABLED,
        SCIENCE_ACADEMIC_MCP_OA_TIMEOUT_SECONDS,
    )
    from ._fulltext_cache import (
        get_oa_source_resolution,
        put_oa_source_failure,
        put_oa_source_resolution,
    )
except ImportError:
    from config import (
        CORE_API_KEY,
        SCIENCE_ACADEMIC_MCP_OA_CORE_API_URL,
        SCIENCE_ACADEMIC_MCP_OA_CORE_ENABLED,
        SCIENCE_ACADEMIC_MCP_OA_ENABLED,
        SCIENCE_ACADEMIC_MCP_OA_HARD_DISABLED,
        SCIENCE_ACADEMIC_MCP_OA_TIMEOUT_SECONDS,
    )
    from _fulltext_cache import (
        get_oa_source_resolution,
        put_oa_source_failure,
        put_oa_source_resolution,
    )


_IACR_EPRINT_PATTERN = re.compile(r"\b((?:19|20)\d{2}/\d{1,6})\b")
_IACR_URL_PATTERN = re.compile(r"eprint\.iacr\.org/((?:19|20)\d{2}/\d{1,6})", re.IGNORECASE)


def _normalized_http_url(value: Any) -> str:
    raw = str(value or "").strip()
    parsed = urlsplit(raw)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        return ""
    return parsed._replace(fragment="").geturl()


def _normalize_doi(value: Any) -> str:
    doi = str(value or "").strip().lower()
    doi = re.sub(r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", "", doi)
    return doi.rstrip(" .;,)")


def _title_key(value: Any) -> str:
    return re.sub(r"[^\w]+", "", str(value or "").casefold(), flags=re.UNICODE)


def _external_ids(payload: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    identifiers: dict[str, Any] = {}
    for container in (payload, result):
        for key in ("external_ids", "externalIds"):
            nested = container.get(key)
            if isinstance(nested, dict):
                identifiers.update(nested)
    return identifiers


def _iacr_eprint_id(payload: dict[str, Any], result: dict[str, Any]) -> str:
    identifiers = _external_ids(payload, result)
    values: list[Any] = []
    for container in (payload, result, identifiers):
        values.extend(
            container.get(key)
            for key in (
                "iacr_eprint_id",
                "iacr_eprint",
                "IACR",
                "IACR ePrint",
                "eprint",
            )
            if container.get(key)
        )
        values.extend(container.get(key) for key in ("url", "pdf_url", "open_access_pdf") if container.get(key))
    for value in values:
        text = str(value or "")
        match = _IACR_URL_PATTERN.search(text) or _IACR_EPRINT_PATTERN.search(text)
        if match:
            return match.group(1)
    return ""


def _safe_error(exc: BaseException) -> str:
    message = str(exc)
    if CORE_API_KEY:
        message = message.replace(CORE_API_KEY, "[redacted]")
    return message[:500]


def _core_identity(payload: dict[str, Any], result: dict[str, Any]) -> tuple[str, str, str]:
    doi = _normalize_doi(payload.get("doi") or result.get("doi"))
    title = str(payload.get("title") or result.get("title") or "").strip()
    if doi:
        return f"doi:{doi}", doi, title
    normalized_title = _title_key(title)
    return (f"title:{normalized_title}", "", title) if normalized_title else ("", "", "")


def _iter_core_values(value: Any) -> list[Any]:
    if isinstance(value, (list, tuple, set)):
        return list(value)
    if value is None:
        return []
    return [value]


def _core_record_doi_values(record: dict[str, Any]) -> list[str]:
    values: list[Any] = []
    for key in ("doi", "DOI"):
        values.extend(_iter_core_values(record.get(key)))
    for container_key in ("identifiers", "externalIds", "external_ids"):
        nested = record.get(container_key)
        if isinstance(nested, dict):
            for key in ("doi", "DOI"):
                values.extend(_iter_core_values(nested.get(key)))
        elif isinstance(nested, list):
            for item in nested:
                if not isinstance(item, dict):
                    continue
                identifier_type = str(
                    item.get("type")
                    or item.get("identifierType")
                    or item.get("scheme")
                    or ""
                ).lower()
                if identifier_type == "doi":
                    values.extend(_iter_core_values(item.get("identifier") or item.get("value")))
    normalized: list[str] = []
    for value in values:
        doi = _normalize_doi(value)
        if doi and doi not in normalized:
            normalized.append(doi)
    return normalized


def _core_record_matches(record: dict[str, Any], *, doi: str, title: str) -> tuple[bool, str]:
    expected_title = _title_key(title)
    if doi:
        return (doi in _core_record_doi_values(record), "doi")
    record_title = _title_key(record.get("title"))
    return (bool(expected_title and record_title == expected_title), "normalized_title")


def _core_output_id(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return re.sub(r"^https?://api\.core\.ac\.uk/v3/outputs/", "", text, flags=re.IGNORECASE).split("/")[0]


def _core_download_candidates_from_record(record: dict[str, Any], *, matched_by: str) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []

    def add(url: Any, *, source: str, priority: int, output_id: str = "") -> None:
        normalized_url = _normalized_http_url(url)
        if not normalized_url:
            return
        candidate = {
            "url": normalized_url,
            "kind": "pdf",
            "source": source,
            "priority": priority,
            "license": str(record.get("license") or ""),
            "version": str(record.get("version") or ""),
            "core_id": str(record.get("id") or ""),
        }
        if output_id:
            candidate["core_output_id"] = output_id
        candidates.append(candidate)

    for key in ("downloadUrl", "download_url", "fullTextUrl", "full_text_url"):
        source_key = re.sub(r"(?<!^)(?=[A-Z])", "_", key).lower()
        add(record.get(key), source=f"academic_mcp.core.{source_key}", priority=90)
    for output in record.get("outputs") or []:
        if not isinstance(output, dict):
            continue
        output_id = _core_output_id(output.get("id") or output.get("identifier"))
        for key in ("downloadUrl", "download_url", "fullTextUrl", "full_text_url"):
            source_key = re.sub(r"(?<!^)(?=[A-Z])", "_", key).lower()
            add(
                output.get(key),
                source=f"academic_mcp.core.output.{source_key}",
                priority=65,
                output_id=output_id,
            )
        if output_id:
            add(
                f"{SCIENCE_ACADEMIC_MCP_OA_CORE_API_URL}/outputs/{quote(output_id, safe='')}/download",
                source="academic_mcp.core.output_download",
                priority=60,
                output_id=output_id,
            )
    unique: dict[str, dict[str, Any]] = {}
    for candidate in candidates:
        key = str(candidate.get("url") or "").lower()
        if key and key not in unique:
            unique[key] = candidate
    return sorted(unique.values(), key=lambda item: int(item.get("priority") or 0))


def _core_candidates_from_response(
    response: dict[str, Any],
    *,
    doi: str,
    title: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    records = response.get("results") if isinstance(response.get("results"), list) else []
    first_exact_without_download: dict[str, Any] | None = None
    for record in records:
        if not isinstance(record, dict):
            continue
        exact_match, matched_by = _core_record_matches(record, doi=doi, title=title)
        if not exact_match:
            continue
        candidates = _core_download_candidates_from_record(record, matched_by=matched_by)
        if not candidates:
            if first_exact_without_download is None:
                first_exact_without_download = {
                    "status": "exact_record_without_public_download",
                    "matched_by": matched_by,
                    "core_id": str(record.get("id") or ""),
                }
            continue
        return candidates, {
            "status": "resolved",
            "matched_by": matched_by,
            "core_id": str(candidates[0].get("core_id") or ""),
            "candidate_count": len(candidates),
            "candidate_sources": [str(item.get("source") or "") for item in candidates],
        }
    if first_exact_without_download is not None:
        return [], first_exact_without_download
    return [], {"status": "no_exact_public_download"}


def resolve_academic_mcp_oa_fallback(
    payload: dict[str, Any],
    result: dict[str, Any],
    *,
    http_get_json: Callable[..., dict[str, Any]],
    host_slot: Callable[[str], Any],
) -> dict[str, Any]:
    """Return strict legal OA PDF candidates without fetching any PDF bytes.

    It never searches IACR by title and only accepts a CORE result when DOI or
    a normalized full title matches exactly, preventing a broad search result
    from being attached to the wrong paper.
    """

    audit: dict[str, Any] = {
        "enabled": bool(SCIENCE_ACADEMIC_MCP_OA_ENABLED),
        "iacr": {"status": "not_applicable"},
        "core": {"status": "not_requested"},
    }
    candidates: list[dict[str, Any]] = []
    if SCIENCE_ACADEMIC_MCP_OA_HARD_DISABLED:
        audit.update({
            "enabled": False,
            "status": "hard_disabled",
            "reason": (
                "Academic MCP OA fallback has been retired from the "
                "production retrieval path."
            ),
        })
        audit["iacr"]["status"] = "hard_disabled"
        audit["core"]["status"] = "hard_disabled"
        return {"candidates": candidates, "audit": audit}
    if not SCIENCE_ACADEMIC_MCP_OA_ENABLED:
        audit["iacr"]["status"] = "disabled"
        audit["core"]["status"] = "disabled"
        return {"candidates": candidates, "audit": audit}

    iacr_id = _iacr_eprint_id(payload, result)
    if iacr_id:
        candidates.append(
            {
                "url": f"https://eprint.iacr.org/{quote(iacr_id, safe='/')}.pdf",
                "kind": "pdf",
                "source": "academic_mcp.iacr.public_eprint",
                "priority": 80,
                "iacr_eprint_id": iacr_id,
            }
        )
        audit["iacr"] = {"status": "identified", "eprint_id": iacr_id}

    identity, doi, title = _core_identity(payload, result)
    if not SCIENCE_ACADEMIC_MCP_OA_CORE_ENABLED:
        audit["core"] = {
            "status": "disabled_by_policy",
            "reason": "SCIENCE_ACADEMIC_MCP_OA_CORE_ENABLED is off; CORE lookup is not used in default retrieval runs.",
        }
    elif not CORE_API_KEY:
        audit["core"] = {"status": "not_configured"}
    elif not identity:
        audit["core"] = {"status": "no_stable_identity"}
    else:
        cache_source = "academic_mcp.core"
        cached = get_oa_source_resolution(cache_source, identity)
        if cached and cached.get("status") == "ok":
            cached_payload = cached.get("payload") if isinstance(cached.get("payload"), dict) else {}
            cached_candidates = cached_payload.get("candidates") if isinstance(cached_payload.get("candidates"), list) else []
            candidates.extend(item for item in cached_candidates if isinstance(item, dict))
            cached_audit = cached_payload.get("audit") if isinstance(cached_payload.get("audit"), dict) else {}
            audit["core"] = {**cached_audit, "cache_hit": True}
        elif cached and cached.get("status") == "failure":
            audit["core"] = {
                "status": "lookup_failed",
                "cache_hit": True,
                "failure_class": str(cached.get("failure_class") or ""),
                "http_status": cached.get("http_status"),
                "error": str(cached.get("error") or "cached CORE lookup failure")[:500],
            }
        else:
            query = doi or title
            url = f"{SCIENCE_ACADEMIC_MCP_OA_CORE_API_URL}/search/works?{urlencode({'q': query, 'limit': '5'})}"
            try:
                with host_slot(url):
                    response = http_get_json(
                        url,
                        headers={
                            "Accept": "application/json",
                            "Authorization": f"Bearer {CORE_API_KEY}",
                            "User-Agent": "qwen-zhikan-papergraph/0.1 (CORE OA discovery)",
                        },
                        timeout=SCIENCE_ACADEMIC_MCP_OA_TIMEOUT_SECONDS,
                    )
                resolved_candidates, core_audit = _core_candidates_from_response(response, doi=doi, title=title)
                put_oa_source_resolution(
                    cache_source,
                    identity,
                    {"candidates": resolved_candidates, "audit": core_audit},
                )
                candidates.extend(resolved_candidates)
                audit["core"] = core_audit
            except Exception as exc:
                put_oa_source_failure(cache_source, identity, exc)
                audit["core"] = {
                    "status": "lookup_failed",
                    "error": _safe_error(exc),
                    "http_status": getattr(exc, "http_status", None),
                }

    unique: dict[str, dict[str, Any]] = {}
    for candidate in candidates:
        url = _normalized_http_url(candidate.get("url"))
        if url and url.lower() not in unique:
            unique[url.lower()] = {**candidate, "url": url}
    resolved_candidates = sorted(
        unique.values(),
        key=lambda item: int(item.get("priority") or 0),
    )
    return {"candidates": resolved_candidates, "audit": audit}
