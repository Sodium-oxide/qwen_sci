"""Persistent, content-addressed caches for legal full-text acquisition."""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from threading import Lock
from typing import Any
from urllib.parse import urlsplit
import json
import os
import time

try:
    from .config import (
        FULLTEXT_CACHE_DIR,
        FULLTEXT_CACHE_ENABLED,
        FULLTEXT_CONTENT_DIR,
        FULLTEXT_EXTERNALIZE_PROJECT_TEXT,
        FULLTEXT_FAILURE_404_TTL_SECONDS,
        FULLTEXT_FAILURE_AUTH_TTL_SECONDS,
        FULLTEXT_FAILURE_NON_PDF_TTL_SECONDS,
        FULLTEXT_FAILURE_TRANSIENT_FIRST_TTL_SECONDS,
        FULLTEXT_FAILURE_TRANSIENT_TTL_SECONDS,
        FULLTEXT_LANDING_CACHE_TTL_SECONDS,
        FULLTEXT_OA_CACHE_TTL_SECONDS,
        FULLTEXT_PDF_CACHE_TTL_SECONDS,
        SCIENCE_ACADEMIC_MCP_OA_CACHE_TTL_SECONDS,
    )
except ImportError:
    from config import (
        FULLTEXT_CACHE_DIR,
        FULLTEXT_CACHE_ENABLED,
        FULLTEXT_CONTENT_DIR,
        FULLTEXT_EXTERNALIZE_PROJECT_TEXT,
        FULLTEXT_FAILURE_404_TTL_SECONDS,
        FULLTEXT_FAILURE_AUTH_TTL_SECONDS,
        FULLTEXT_FAILURE_NON_PDF_TTL_SECONDS,
        FULLTEXT_FAILURE_TRANSIENT_FIRST_TTL_SECONDS,
        FULLTEXT_FAILURE_TRANSIENT_TTL_SECONDS,
        FULLTEXT_LANDING_CACHE_TTL_SECONDS,
        FULLTEXT_OA_CACHE_TTL_SECONDS,
        FULLTEXT_PDF_CACHE_TTL_SECONDS,
        SCIENCE_ACADEMIC_MCP_OA_CACHE_TTL_SECONDS,
    )


FULLTEXT_CACHE_SCHEMA_VERSION = "fulltext_cache_v1"
FULLTEXT_REFERENCE_SCHEMA_VERSION = "content_addressed_fulltext_ref_v1"
_CACHE_LOCK = Lock()
_FAILURE_BACKOFF_LOCK = Lock()
_KEY_LOCKS_LOCK = Lock()
_KEY_LOCKS: dict[str, Lock] = {}
_TRANSIENT_FAILURE_CLASSES = {
    "TRANSIENT_PROVIDER_FAILURE",
    "TRANSIENT_FETCH_FAILURE",
}


class CachedFullTextFailure(RuntimeError):
    """A still-live negative cache entry represented as the original failure."""

    def __init__(self, entry: dict[str, Any]):
        super().__init__(str(entry.get("error") or entry.get("failure_class") or "cached full-text failure"))
        self.cache_hit = True
        self.failure_class = str(entry.get("failure_class") or "TRANSIENT")
        self.http_status = int(entry.get("http_status") or 0)
        self.retry_after_seconds = max(
            0,
            int(float(entry.get("expires_at") or 0) - time.time()),
        )


@contextmanager
def fulltext_cache_singleflight(namespace: str, key: str):
    """Serialize one cache-producing operation without blocking other keys."""

    lock_key = f"{namespace}:{key}"
    with _KEY_LOCKS_LOCK:
        lock = _KEY_LOCKS.get(lock_key)
        if lock is None:
            lock = Lock()
            _KEY_LOCKS[lock_key] = lock
    lock.acquire()
    try:
        yield
    finally:
        lock.release()


def _digest(value: str) -> str:
    return sha256(str(value or "").encode("utf-8")).hexdigest()


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def _entry_path(namespace: str, key: str) -> Path:
    return Path(FULLTEXT_CACHE_DIR) / namespace / f"{_digest(key)}.json"


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(
        f".{path.name}.{os.getpid()}.{time.time_ns()}.tmp"
    )
    with _CACHE_LOCK:
        try:
            temporary.write_bytes(data)
            os.replace(temporary, path)
        finally:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    _atomic_write_bytes(
        path,
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8"),
    )


def _read_json(path: Path) -> dict[str, Any] | None:
    if not FULLTEXT_CACHE_ENABLED or not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _read_fresh(path: Path) -> dict[str, Any] | None:
    entry = _read_json(path)
    if not entry:
        return None
    expires_at = float(entry.get("expires_at") or 0)
    if expires_at and expires_at <= time.time():
        return None
    return entry


def _cache_entry(
    *,
    status: str,
    ttl_seconds: float,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    stored_at = time.time()
    ttl = max(0.0, float(ttl_seconds or 0))
    return {
        "schema_version": FULLTEXT_CACHE_SCHEMA_VERSION,
        "status": status,
        "stored_at": stored_at,
        "expires_at": stored_at + ttl if ttl > 0 else 0,
        **deepcopy(payload or {}),
    }


def _write_entry(
    namespace: str,
    key: str,
    *,
    status: str,
    ttl_seconds: float,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    entry = _cache_entry(status=status, ttl_seconds=ttl_seconds, payload=payload)
    if FULLTEXT_CACHE_ENABLED:
        _atomic_write_json(_entry_path(namespace, key), entry)
    return entry


def _write_failure_entry(
    namespace: str,
    key: str,
    failure: dict[str, Any],
) -> dict[str, Any]:
    payload = deepcopy(failure)
    with _FAILURE_BACKOFF_LOCK:
        if str(payload.get("failure_class") or "") in _TRANSIENT_FAILURE_CLASSES:
            previous = _read_json(_entry_path(namespace, key))
            previous_count = 0
            if (
                previous
                and previous.get("status") == "failure"
                and str(previous.get("failure_class") or "")
                in _TRANSIENT_FAILURE_CLASSES
            ):
                try:
                    previous_count = max(
                        0,
                        int(previous.get("transient_failure_count") or 0),
                    )
                except (TypeError, ValueError):
                    previous_count = 0
            transient_failure_count = previous_count + 1
            payload["transient_failure_count"] = transient_failure_count
            payload["ttl_seconds"] = (
                FULLTEXT_FAILURE_TRANSIENT_FIRST_TTL_SECONDS
                if transient_failure_count == 1
                else FULLTEXT_FAILURE_TRANSIENT_TTL_SECONDS
            )
        return _write_entry(
            namespace,
            key,
            status="failure",
            ttl_seconds=float(payload.pop("ttl_seconds")),
            payload=payload,
        )


def get_oa_resolution(doi: str) -> dict[str, Any] | None:
    entry = _read_fresh(_entry_path("oa", str(doi).strip().lower()))
    if entry:
        entry["cache_hit"] = True
    return entry


def put_oa_resolution(doi: str, payload: dict[str, Any]) -> dict[str, Any]:
    return _write_entry(
        "oa",
        str(doi).strip().lower(),
        status="ok",
        ttl_seconds=FULLTEXT_OA_CACHE_TTL_SECONDS,
        payload={"payload": deepcopy(payload)},
    )


def put_oa_failure(doi: str, exc: BaseException) -> dict[str, Any]:
    failure = failure_payload(exc)
    return _write_failure_entry(
        "oa",
        str(doi).strip().lower(),
        failure,
    )


def _oa_source_cache_key(source: str, identity: str) -> str:
    return f"{str(source or '').strip().lower()}:{str(identity or '').strip().lower()}"


def get_oa_source_resolution(source: str, identity: str) -> dict[str, Any] | None:
    """Return a cached source-specific OA discovery response when still fresh."""

    entry = _read_fresh(_entry_path("oa_sources", _oa_source_cache_key(source, identity)))
    if entry:
        entry["cache_hit"] = True
    return entry


def put_oa_source_resolution(
    source: str,
    identity: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Persist a source-specific OA discovery response without caching a PDF itself."""

    return _write_entry(
        "oa_sources",
        _oa_source_cache_key(source, identity),
        status="ok",
        ttl_seconds=SCIENCE_ACADEMIC_MCP_OA_CACHE_TTL_SECONDS,
        payload={"payload": deepcopy(payload)},
    )


def put_oa_source_failure(source: str, identity: str, exc: BaseException) -> dict[str, Any]:
    """Persist a negative source-specific OA discovery result using failure TTL policy."""

    return _write_failure_entry(
        "oa_sources",
        _oa_source_cache_key(source, identity),
        failure_payload(exc),
    )


def get_landing_resolution(url: str) -> dict[str, Any] | None:
    entry = _read_fresh(_entry_path("landing", str(url).strip()))
    if entry:
        entry["cache_hit"] = True
    return entry


def put_landing_resolution(url: str, payload: dict[str, Any]) -> dict[str, Any]:
    return _write_entry(
        "landing",
        str(url).strip(),
        status="ok",
        ttl_seconds=FULLTEXT_LANDING_CACHE_TTL_SECONDS,
        payload={"payload": deepcopy(payload)},
    )


def put_landing_failure(url: str, exc: BaseException) -> dict[str, Any]:
    failure = failure_payload(exc)
    entry = _write_failure_entry(
        "landing",
        str(url).strip(),
        failure,
    )
    _put_host_auth_failure(str(getattr(exc, "final_url", "") or url), entry)
    return entry


def _pdf_url_key(url: str) -> str:
    return str(url or "").strip()


def get_pdf_by_url(url: str) -> dict[str, Any] | None:
    host_failure = get_host_failure(url)
    if host_failure:
        raise CachedFullTextFailure(host_failure)
    entry = _read_fresh(_entry_path("pdf_urls", _pdf_url_key(url)))
    if not entry:
        return None
    if entry.get("status") == "failure":
        raise CachedFullTextFailure(entry)
    content_hash = str(entry.get("content_hash") or "")
    content_path = Path(FULLTEXT_CACHE_DIR) / "pdf" / f"{content_hash}.pdf"
    try:
        data = content_path.read_bytes()
    except OSError:
        return None
    if sha256(data).hexdigest() != content_hash:
        return None
    return {**entry, "cache_hit": True, "data": data}


def put_pdf_by_url(
    url: str,
    data: bytes,
    *,
    final_url: str,
    content_type: str,
    etag: str = "",
    last_modified: str = "",
) -> dict[str, Any]:
    content_hash = sha256(data).hexdigest()
    if FULLTEXT_CACHE_ENABLED:
        content_path = Path(FULLTEXT_CACHE_DIR) / "pdf" / f"{content_hash}.pdf"
        if not content_path.is_file():
            _atomic_write_bytes(content_path, data)
    validator_payload = {
        "url": str(url),
        "final_url": str(final_url),
        "content_type": str(content_type),
        "etag": str(etag),
        "last_modified": str(last_modified),
        "validator_key": _digest(f"{url}\0{etag}\0{last_modified}"),
        "content_hash": content_hash,
        "bytes": len(data),
    }
    entry = _write_entry(
        "pdf_urls",
        _pdf_url_key(url),
        status="ok",
        ttl_seconds=FULLTEXT_PDF_CACHE_TTL_SECONDS,
        payload=validator_payload,
    )
    _write_entry(
        "pdf_validators",
        _canonical_json(
            {
                "url": str(url),
                "etag": str(etag),
                "last_modified": str(last_modified),
            }
        ),
        status="ok",
        ttl_seconds=FULLTEXT_PDF_CACHE_TTL_SECONDS,
        payload=validator_payload,
    )
    return entry


def put_pdf_failure(
    url: str,
    exc: BaseException,
    *,
    non_pdf: bool = False,
) -> dict[str, Any]:
    failure = failure_payload(exc, non_pdf=non_pdf)
    entry = _write_failure_entry(
        "pdf_urls",
        _pdf_url_key(url),
        failure,
    )
    _put_host_auth_failure(url, entry)
    return entry


def _put_host_auth_failure(url: str, entry: dict[str, Any]) -> None:
    if str(entry.get("failure_class") or "") != "AUTH_OR_ACCESS_DENIED":
        return
    host = str(urlsplit(str(url or "")).hostname or "").lower()
    if host:
        _write_entry(
            "host_failures",
            host,
            status="failure",
            ttl_seconds=FULLTEXT_FAILURE_AUTH_TTL_SECONDS,
            payload={
                key: entry.get(key)
                for key in ("failure_class", "http_status", "error")
            },
        )


def get_host_failure(url: str) -> dict[str, Any] | None:
    host = str(urlsplit(str(url or "")).hostname or "").lower()
    if not host:
        return None
    entry = _read_fresh(_entry_path("host_failures", host))
    if entry:
        entry["cache_hit"] = True
    return entry


def failure_payload(
    exc: BaseException,
    *,
    non_pdf: bool = False,
) -> dict[str, Any]:
    status = int(getattr(exc, "http_status", 0) or 0)
    message = str(exc)
    lowered = message.lower()
    if non_pdf:
        failure_class = "NON_PDF_CONTENT"
        ttl = FULLTEXT_FAILURE_NON_PDF_TTL_SECONDS
    elif status == 404:
        failure_class = "NOT_FOUND"
        ttl = FULLTEXT_FAILURE_404_TTL_SECONDS
    elif status in {401, 403}:
        failure_class = "AUTH_OR_ACCESS_DENIED"
        ttl = FULLTEXT_FAILURE_AUTH_TTL_SECONDS
    elif (
        status == 429
        or status >= 500
        or isinstance(exc, TimeoutError)
        or "timed out" in lowered
        or "timeout" in lowered
        or "temporar" in lowered
    ):
        failure_class = "TRANSIENT_PROVIDER_FAILURE"
        ttl = FULLTEXT_FAILURE_TRANSIENT_FIRST_TTL_SECONDS
    else:
        failure_class = "TRANSIENT_FETCH_FAILURE"
        ttl = FULLTEXT_FAILURE_TRANSIENT_FIRST_TTL_SECONDS
    return {
        "failure_class": failure_class,
        "http_status": status or None,
        "error": message[:1000],
        "final_url": str(
            getattr(exc, "final_url", "")
            or getattr(exc, "url", "")
            or ""
        )[:1000],
        "ttl_seconds": float(ttl),
    }


def markdown_cache_key(content_hash: str, converter_version: str) -> str:
    return f"{content_hash}:{converter_version}"


def get_markdown(content_hash: str, converter_version: str) -> dict[str, Any] | None:
    key = markdown_cache_key(content_hash, converter_version)
    metadata = _read_json(_entry_path("markdown", key))
    if not metadata or metadata.get("status") != "ok":
        return None
    markdown_path = Path(FULLTEXT_CACHE_DIR) / "markdown" / f"{_digest(key)}.md"
    try:
        markdown = markdown_path.read_text(encoding="utf-8")
    except OSError:
        return None
    return {**metadata, "cache_hit": True, "markdown": markdown}


def put_markdown(
    content_hash: str,
    converter_version: str,
    markdown: str,
    conversion_report: dict[str, Any] | None,
) -> dict[str, Any]:
    key = markdown_cache_key(content_hash, converter_version)
    if FULLTEXT_CACHE_ENABLED:
        markdown_path = Path(FULLTEXT_CACHE_DIR) / "markdown" / f"{_digest(key)}.md"
        _atomic_write_bytes(markdown_path, str(markdown).encode("utf-8"))
    return _write_entry(
        "markdown",
        key,
        status="ok",
        ttl_seconds=0,
        payload={
            "content_hash": content_hash,
            "converter_version": converter_version,
            "markdown_hash": sha256(str(markdown).encode("utf-8")).hexdigest(),
            "conversion_report": deepcopy(conversion_report or {}),
        },
    )


def excerpt_cache_key(
    *,
    content_hash: str,
    extractor_version: str,
    alignment_contract_hash: str,
    extraction_keywords_hash: str,
    max_output_chars: int,
) -> str:
    return _canonical_json(
        {
            "content_hash": content_hash,
            "extractor_version": extractor_version,
            "alignment_contract_hash": alignment_contract_hash,
            "extraction_keywords_hash": extraction_keywords_hash,
            "max_output_chars": int(max_output_chars),
        }
    )


def get_excerpt(**key_fields: Any) -> dict[str, Any] | None:
    entry = _read_json(_entry_path("excerpts", excerpt_cache_key(**key_fields)))
    if entry and entry.get("status") == "ok":
        entry["cache_hit"] = True
        return entry
    return None


def put_excerpt(result: dict[str, Any], **key_fields: Any) -> dict[str, Any]:
    return _write_entry(
        "excerpts",
        excerpt_cache_key(**key_fields),
        status="ok",
        ttl_seconds=0,
        payload={"result": deepcopy(result)},
    )


def visual_evidence_cache_key(
    *,
    content_hash: str,
    asset_image_sha256: str,
    alignment_contract_hash: str,
    model: str,
    prompt_version: str,
    schema_version: str,
) -> str:
    return _canonical_json(
        {
            "content_hash": str(content_hash or ""),
            "asset_image_sha256": str(asset_image_sha256 or ""),
            "alignment_contract_hash": str(alignment_contract_hash or ""),
            "model": str(model or ""),
            "prompt_version": str(prompt_version or ""),
            "schema_version": str(schema_version or ""),
        }
    )


def get_visual_evidence(**key_fields: Any) -> dict[str, Any] | None:
    entry = _read_json(_entry_path("visual", visual_evidence_cache_key(**key_fields)))
    if entry and entry.get("status") == "ok":
        entry["cache_hit"] = True
        return entry
    return None


def put_visual_evidence(result: dict[str, Any], **key_fields: Any) -> dict[str, Any]:
    return _write_entry(
        "visual",
        visual_evidence_cache_key(**key_fields),
        status="ok",
        ttl_seconds=0,
        payload={"result": deepcopy(result)},
    )


def store_fulltext_text(text: str) -> dict[str, Any]:
    encoded = str(text or "").encode("utf-8")
    content_hash = sha256(encoded).hexdigest()
    path = Path(FULLTEXT_CONTENT_DIR) / f"{content_hash}.md"
    if FULLTEXT_EXTERNALIZE_PROJECT_TEXT and not path.is_file():
        _atomic_write_bytes(path, encoded)
    return {
        "schema_version": FULLTEXT_REFERENCE_SCHEMA_VERSION,
        "fulltext_content_hash": f"sha256:{content_hash}",
        "fulltext_hash": content_hash,
        "fulltext_ref": f"fulltext/{content_hash}.md",
        "chars": len(str(text or "")),
    }


def load_fulltext_text(record: dict[str, Any]) -> str:
    content_hash = str(
        record.get("fulltext_hash")
        or str(record.get("fulltext_content_hash") or "").removeprefix("sha256:")
    )
    if not content_hash:
        return ""
    path = Path(FULLTEXT_CONTENT_DIR) / f"{content_hash}.md"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return ""
    if sha256(text.encode("utf-8")).hexdigest() != content_hash:
        return ""
    return text


def externalize_project_fulltexts(project: dict[str, Any]) -> dict[str, Any]:
    if not FULLTEXT_EXTERNALIZE_PROJECT_TEXT:
        return project
    for record in project.get("papergraph", []) if isinstance(project.get("papergraph"), list) else []:
        if not isinstance(record, dict):
            continue
        text = str(record.get("full_text_excerpt") or "")
        if not text:
            continue
        reference = store_fulltext_text(text)
        record.update(reference)
        record.pop("full_text_excerpt", None)
    return project


def hydrate_project_fulltexts(project: dict[str, Any]) -> dict[str, Any]:
    for record in project.get("papergraph", []) if isinstance(project.get("papergraph"), list) else []:
        if not isinstance(record, dict) or str(record.get("full_text_excerpt") or ""):
            continue
        text = load_fulltext_text(record)
        if text:
            record["full_text_excerpt"] = text
    return project


def externalize_paper_fulltext(paper: dict[str, Any]) -> dict[str, Any]:
    wrapper = {"papergraph": [paper]}
    externalize_project_fulltexts(wrapper)
    return paper


def hydrate_paper_fulltext(paper: dict[str, Any]) -> dict[str, Any]:
    wrapper = {"papergraph": [paper]}
    hydrate_project_fulltexts(wrapper)
    return paper
