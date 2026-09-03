"""Bounded, access-context-aware coordination for lawful full-text requests.

This module coordinates requests; it never manufactures an access path.  It
prevents duplicate anonymous requests to the same OA URL and temporarily
remembers classified failures.  The access-context generation is deliberately
part of every cache key: a future, legitimately configured TDM client must not
be blocked by an old anonymous 403.
"""

from __future__ import annotations

from concurrent.futures import Future
from copy import deepcopy
from hashlib import sha256
import os
import shutil
import threading
import time
from typing import Any, Callable, Mapping
from urllib.parse import urlsplit, urlunsplit

import diskcache as dc


# v2 changes both failure lifetimes and circuit-host attribution.  Isolating
# keys prevents old anonymous DOI-wide circuits from governing the new policy.
FULLTEXT_DOWNLOAD_CACHE_SCHEMA_VERSION = "fulltext_download_cache_v2"

# DOI and Handle services are redirectors, not content hosts.  A publisher's
# response after a DOI redirect must never disable every later DOI lookup.
_RESOLVER_HOSTS = frozenset({"doi.org", "dx.doi.org", "hdl.handle.net"})


def normalize_download_url(value: Any) -> str:
    """Normalize only the URL portions safe for identity comparison.

    Query strings remain intact because signed repository URLs can legitimately
    differ only by query.  Fragment identifiers are never sent in HTTP
    requests and would only defeat de-duplication.
    """

    raw = str(value or "").strip()
    if not raw:
        return ""
    parsed = urlsplit(raw)
    scheme = parsed.scheme.lower()
    host = parsed.netloc.lower()
    if scheme not in {"http", "https"} or not host:
        return ""
    return urlunsplit((scheme, host, parsed.path, parsed.query, ""))


def sanitize_url_for_storage(value: Any) -> str:
    """Keep URL provenance useful without persisting signed query parameters."""

    normalized = normalize_download_url(value)
    if not normalized:
        return ""
    parsed = urlsplit(normalized)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


def _has_url_query(value: Any) -> bool:
    normalized = normalize_download_url(value)
    return bool(normalized and urlsplit(normalized).query)


def _is_resolver_host(host: str) -> bool:
    normalized = str(host or "").strip().casefold().rstrip(".")
    return normalized in _RESOLVER_HOSTS


class FulltextDownloadCoordinator:
    """Coordinate same-URL work and cache safe, classified acquisition state.

    The coordinator is intentionally process-local for single-flight locks and
    per-host semaphores.  Its result cache is persistent, so completed failure
    classifications can protect later runs without sharing credentials.
    """

    _SUCCESS_STATUS = "downloaded_response"
    _LANDING_SUCCESS_STATUSES = frozenset({"resolved_to_pdf", "pdf_links_found"})

    def __init__(self, cache_path: str, settings: Any, logger: Any = None) -> None:
        self.settings = settings
        self.logger = logger
        self.access_context_generation = str(
            self._setting("fulltext_access_context_generation", "anonymous-v1")
            or "anonymous-v1"
        ).strip() or "anonymous-v1"
        self.per_host_concurrency = max(
            1, int(self._setting("fulltext_per_host_concurrency", 2) or 2)
        )
        self._cache = dc.Cache(os.path.join(str(cache_path), "fulltext_download_state"))
        self._lock = threading.RLock()
        self._inflight: dict[str, Future] = {}
        self._host_semaphores: dict[str, threading.BoundedSemaphore] = {}
        self._transient_counts: dict[str, int] = {}

        if self._as_bool("invalidate_fulltext_failure_cache", False):
            self.invalidate_failure_cache()

    def _setting(self, name: str, default: Any) -> Any:
        return getattr(self.settings, name, default)

    def _as_bool(self, name: str, default: bool) -> bool:
        value = self._setting(name, default)
        return str(value).strip().casefold() not in {"0", "false", "no", "off", ""}

    @staticmethod
    def _url_digest(normalized_url: str) -> str:
        return sha256(normalized_url.encode("utf-8")).hexdigest()

    @staticmethod
    def _host(normalized_url: str) -> str:
        return str(urlsplit(normalized_url).netloc or "").casefold()

    def _url_cache_key(self, normalized_url: str) -> str:
        return (
            f"url-result:{FULLTEXT_DOWNLOAD_CACHE_SCHEMA_VERSION}:"
            f"{self.access_context_generation}:{self._url_digest(normalized_url)}"
        )

    def _host_circuit_key(self, host: str) -> str:
        return (
            f"host-circuit:{FULLTEXT_DOWNLOAD_CACHE_SCHEMA_VERSION}:"
            f"{self.access_context_generation}:{host}"
        )

    def _host_denials_key(self, host: str) -> str:
        return (
            f"host-denials:{FULLTEXT_DOWNLOAD_CACHE_SCHEMA_VERSION}:"
            f"{self.access_context_generation}:{host}"
        )

    def _host_semaphore(self, host: str) -> threading.BoundedSemaphore:
        with self._lock:
            semaphore = self._host_semaphores.get(host)
            if semaphore is None:
                semaphore = threading.BoundedSemaphore(self.per_host_concurrency)
                self._host_semaphores[host] = semaphore
            return semaphore

    def _failure_ttl(self, status: str, normalized_url: str) -> int:
        # Signed object-store URLs commonly expire between attempts.  Holding a
        # negative result for days prevents a fresh metadata lookup from ever
        # being useful, so keep those failures intentionally short.
        if _has_url_query(normalized_url) and status != "not_found":
            return max(
                1,
                int(self._setting("fulltext_failure_signed_url_ttl_seconds", 300)),
            )
        if status == "not_found":
            return max(1, int(self._setting("fulltext_failure_404_ttl_seconds", 86400)))
        if status in {"access_denied", "authentication_required"}:
            return max(1, int(self._setting("fulltext_failure_access_denied_ttl_seconds", 1800)))
        if status == "rate_limited":
            return max(1, int(self._setting("fulltext_failure_rate_limited_ttl_seconds", 900)))
        if status in {"non_pdf", "no_declared_pdf", "landing_page_only"}:
            return max(1, int(self._setting("fulltext_failure_non_pdf_ttl_seconds", 21600)))
        if status in {"timeout", "network_error", "transient_failure", "fetch_failed", "http_error"}:
            with self._lock:
                failures = self._transient_counts.get(normalized_url, 0) + 1
                self._transient_counts[normalized_url] = failures
            if failures <= 1:
                return max(1, int(self._setting("fulltext_failure_transient_first_ttl_seconds", 60)))
            return max(1, int(self._setting("fulltext_failure_transient_ttl_seconds", 180)))
        return max(1, int(self._setting("fulltext_failure_transient_first_ttl_seconds", 60)))

    def _success_ttl(self, kind: str) -> int:
        if kind == "landing_page":
            return max(1, int(self._setting("fulltext_oa_resolution_cache_ttl_seconds", 604800)))
        return max(1, int(self._setting("fulltext_pdf_success_cache_ttl_seconds", 2592000)))

    def _cache_entry(self, normalized_url: str) -> dict[str, Any] | None:
        entry = self._cache.get(self._url_cache_key(normalized_url))
        return dict(entry) if isinstance(entry, Mapping) else None

    def _store_entry(
        self,
        normalized_url: str,
        *,
        kind: str,
        result: Mapping[str, Any],
        source_path: str = "",
        successful: bool,
    ) -> None:
        status = str(result.get("status") or "fetch_failed")
        ttl = self._success_ttl(kind) if successful else self._failure_ttl(status, normalized_url)
        safe_result = self._cache_safe_result(result)
        requires_refetch = (
            kind == "landing_page"
            and any(
                _has_url_query(candidate.get("url"))
                for candidate in result.get("pdf_candidates") or []
                if isinstance(candidate, Mapping)
            )
        )
        payload = {
            "schema_version": FULLTEXT_DOWNLOAD_CACHE_SCHEMA_VERSION,
            "kind": kind,
            "status": status,
            "successful": bool(successful),
            "source_path": str(source_path or ""),
            "result": safe_result,
            "requires_refetch": requires_refetch,
            "cached_at": time.time(),
            "access_context_generation": self.access_context_generation,
        }
        self._cache.set(self._url_cache_key(normalized_url), payload, expire=ttl)

    @staticmethod
    def _cache_safe_result(value: Any) -> Any:
        if isinstance(value, Mapping):
            safe: dict[str, Any] = {}
            for key, item in value.items():
                if key in {"requested_url", "final_url", "url"}:
                    safe[key] = sanitize_url_for_storage(item)
                elif key == "error":
                    safe[key] = "redacted"
                else:
                    safe[key] = FulltextDownloadCoordinator._cache_safe_result(item)
            return safe
        if isinstance(value, (list, tuple)):
            return [FulltextDownloadCoordinator._cache_safe_result(item) for item in value]
        return deepcopy(value)

    def _host_circuit_result(self, normalized_url: str) -> dict[str, Any] | None:
        host = self._host(normalized_url)
        # Ignore legacy circuits produced by the pre-v2 DOI attribution logic
        # as well as any future accidental resolver circuit.
        if _is_resolver_host(host):
            return None
        circuit = self._cache.get(self._host_circuit_key(host))
        if not isinstance(circuit, Mapping):
            return None
        retry_after = max(0, int(float(circuit.get("until", 0)) - time.time()))
        return {
            "downloaded": False,
            "status": "host_circuit_open",
            "requested_url": normalized_url,
            "final_url": normalized_url,
            "http_status": None,
            "content_type": "",
            "bytes_written": 0,
            "host": host,
            "retry_after_seconds": retry_after,
            "cache_hit": True,
        }

    def _record_access_denial(self, normalized_url: str) -> None:
        host = self._host(normalized_url)
        if _is_resolver_host(host):
            return
        now = time.time()
        window = max(1, int(self._setting("fulltext_host_denial_window_seconds", 600)))
        threshold = max(1, int(self._setting("fulltext_host_denial_threshold", 2)))
        denial_key = self._host_denials_key(host)
        existing = self._cache.get(denial_key) or []
        records = [
            item
            for item in existing
            if isinstance(item, Mapping)
            and float(item.get("timestamp", 0)) >= now - window
            and str(item.get("url_digest") or "")
        ]
        url_digest = self._url_digest(normalized_url)
        if not any(str(item.get("url_digest")) == url_digest for item in records):
            records.append({"url_digest": url_digest, "timestamp": now})
        self._cache.set(denial_key, records, expire=window)
        if len(records) < threshold:
            return
        ttl = max(1, int(self._setting("fulltext_host_circuit_ttl_seconds", 3600)))
        self._cache.set(
            self._host_circuit_key(host),
            {"until": now + ttl, "denial_count": len(records)},
            expire=ttl,
        )
        if self.logger is not None:
            self.logger.warning(
                "Full-text host circuit opened host=%s access_context=%s denials=%s ttl_seconds=%s.",
                host,
                self.access_context_generation,
                len(records),
                ttl,
            )

    @staticmethod
    def _copy_success(source_path: str, destination_path: str, validator: Callable[[str], bool]) -> bool:
        if not source_path or not destination_path or not os.path.isfile(source_path):
            return False
        try:
            if not validator(source_path):
                return False
            if os.path.abspath(source_path) != os.path.abspath(destination_path):
                os.makedirs(os.path.dirname(destination_path), exist_ok=True)
                shutil.copyfile(source_path, destination_path)
            return bool(validator(destination_path))
        except OSError:
            return False

    def _read_cached_result(
        self,
        normalized_url: str,
        *,
        kind: str,
        destination_path: str | None,
        validator: Callable[[str], bool] | None,
    ) -> dict[str, Any] | None:
        entry = self._cache_entry(normalized_url)
        if entry is None or entry.get("kind") != kind:
            return None
        if entry.get("requires_refetch"):
            return None
        result = deepcopy(dict(entry.get("result") or {}))
        if not entry.get("successful"):
            result["cache_hit"] = True
            result["cache_state"] = "failure"
            return result
        if kind == "pdf":
            if destination_path is None or validator is None:
                return None
            if not self._copy_success(str(entry.get("source_path") or ""), destination_path, validator):
                self._cache.delete(self._url_cache_key(normalized_url))
                return None
        result["cache_hit"] = True
        result["cache_state"] = "success"
        if kind == "pdf":
            result["downloaded"] = True
        return result

    def execute(
        self,
        *,
        url: str,
        kind: str,
        operation: Callable[[], Mapping[str, Any]],
        destination_path: str | None = None,
        validator: Callable[[str], bool] | None = None,
        is_success: Callable[[Mapping[str, Any]], bool] | None = None,
    ) -> dict[str, Any]:
        """Run one request once per URL/context, respecting the host semaphore."""

        normalized_url = normalize_download_url(url)
        if not normalized_url:
            return {
                "downloaded": False,
                "status": "invalid_url",
                "requested_url": str(url or ""),
                "final_url": str(url or ""),
                "http_status": None,
                "content_type": "",
                "bytes_written": 0,
            }

        cached = self._read_cached_result(
            normalized_url,
            kind=kind,
            destination_path=destination_path,
            validator=validator,
        )
        if cached is not None:
            return cached
        circuit = self._host_circuit_result(normalized_url)
        if circuit is not None:
            return circuit

        singleflight_key = f"{kind}:{self.access_context_generation}:{normalized_url}"
        leader = False
        with self._lock:
            future = self._inflight.get(singleflight_key)
            if future is None:
                future = Future()
                self._inflight[singleflight_key] = future
                leader = True

        if leader:
            try:
                host = self._host(normalized_url)
                with self._host_semaphore(host):
                    result = dict(operation() or {})
                result.setdefault("requested_url", normalized_url)
                result.setdefault("final_url", normalized_url)
                result.setdefault("host", host)
                succeeded = bool(is_success(result)) if is_success else bool(result.get("downloaded"))
                source_path = destination_path if succeeded and kind == "pdf" else ""
                self._store_entry(
                    normalized_url,
                    kind=kind,
                    result=result,
                    source_path=source_path,
                    successful=succeeded,
                )
                if str(result.get("status") or "") == "access_denied":
                    # Redirectors are not the host that denied access.  Record
                    # the final content host when it is available, so a 403
                    # from one publisher cannot open a DOI-wide circuit.
                    final_url = normalize_download_url(result.get("final_url"))
                    self._record_access_denial(final_url or normalized_url)
                future.set_result(deepcopy(result))
            except Exception as exc:  # Preserve a classified result for waiters.
                result = {
                    "downloaded": False,
                    "status": "fetch_failed",
                    "requested_url": normalized_url,
                    "final_url": normalized_url,
                    "http_status": None,
                    "content_type": "",
                    "bytes_written": 0,
                    "error": type(exc).__name__,
                }
                self._store_entry(
                    normalized_url,
                    kind=kind,
                    result=result,
                    successful=False,
                )
                future.set_result(deepcopy(result))
            finally:
                with self._lock:
                    self._inflight.pop(singleflight_key, None)
        else:
            result = deepcopy(dict(future.result()))
            result["singleflight_shared"] = True
            if kind == "pdf":
                cached_after_wait = self._read_cached_result(
                    normalized_url,
                    kind=kind,
                    destination_path=destination_path,
                    validator=validator,
                )
                if cached_after_wait is not None:
                    cached_after_wait["singleflight_shared"] = True
                    return cached_after_wait
                result["downloaded"] = False
                result["status"] = "shared_result_unavailable"
            return result

        result = deepcopy(dict(future.result()))
        result.setdefault("cache_hit", False)
        result.setdefault("singleflight_shared", False)
        return result

    def invalidate_url(self, url: str) -> None:
        normalized_url = normalize_download_url(url)
        if normalized_url:
            self._cache.delete(self._url_cache_key(normalized_url))

    def invalidate_failure_cache(self) -> None:
        """Explicitly clear only this context's cached failures and circuits."""

        prefix = f"{FULLTEXT_DOWNLOAD_CACHE_SCHEMA_VERSION}:{self.access_context_generation}:"
        for key in list(self._cache.iterkeys()):
            text = str(key)
            if text.startswith("url-result:") and prefix in text:
                entry = self._cache.get(key)
                if isinstance(entry, Mapping) and not entry.get("successful"):
                    self._cache.delete(key)
            elif text.startswith("host-circuit:") and prefix in text:
                self._cache.delete(key)
            elif text.startswith("host-denials:") and prefix in text:
                self._cache.delete(key)
