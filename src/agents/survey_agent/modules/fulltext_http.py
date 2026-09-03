"""Bounded HTTP transport for lawful open-access full-text retrieval.

The client intentionally supports only ordinary public GET requests.  It does
not manage browser cookies, credentials, challenge bypasses, or subscription
access; callers remain responsible for validating that a returned body is a
real public PDF.
"""

from __future__ import annotations

import threading
import time
from email.utils import parsedate_to_datetime
from typing import Any, Mapping

import requests


class FulltextHttpClient:
    """Use per-thread sessions with bounded retries for transient GET failures."""

    _RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})

    def __init__(self, settings: Any, *, contact_email: str = "", logger: Any = None) -> None:
        self.settings = settings
        self.logger = logger
        self.contact_email = self._safe_header_value(contact_email)
        self.max_retries = max(0, int(self._setting("fulltext_http_max_retries", 2) or 0))
        self.retry_base_delay_seconds = self._positive_float(
            self._setting("fulltext_http_retry_base_delay_seconds", 1), default=1.0
        )
        self.retry_max_delay_seconds = self._positive_float(
            self._setting("fulltext_http_retry_max_delay_seconds", 10), default=10.0
        )
        self.connect_timeout_seconds = self._positive_float(
            self._setting("fulltext_connect_timeout_seconds", 10), default=10.0
        )
        self.read_timeout_seconds = self._positive_float(
            self._setting("fulltext_read_timeout_seconds", 60), default=60.0
        )
        self._local = threading.local()

    def _setting(self, name: str, default: Any) -> Any:
        return getattr(self.settings, name, default)

    @staticmethod
    def _positive_float(value: Any, *, default: float) -> float:
        try:
            return max(0.1, float(value))
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _safe_header_value(value: Any) -> str:
        return str(value or "").replace("\r", "").replace("\n", "").strip()

    @property
    def default_headers(self) -> dict[str, str]:
        user_agent = "Xcientist/0.8 (academic OA full-text retrieval)"
        if self.contact_email:
            user_agent = f"Xcientist/0.8 (academic OA full-text retrieval; contact: {self.contact_email})"
        return {
            "User-Agent": user_agent,
            "Accept": "application/pdf,application/xhtml+xml,text/html;q=0.9,*/*;q=0.5",
            "Accept-Language": "en-US,en;q=0.8",
        }

    @property
    def timeout(self) -> tuple[float, float]:
        return (self.connect_timeout_seconds, self.read_timeout_seconds)

    def _session(self) -> requests.Session:
        session = getattr(self._local, "session", None)
        if session is None:
            session = requests.Session()
            self._local.session = session
        return session

    def _retry_delay_seconds(self, response: Any, retry_index: int) -> float:
        retry_after = str(getattr(response, "headers", {}).get("Retry-After") or "").strip()
        if retry_after:
            try:
                return min(self.retry_max_delay_seconds, max(0.0, float(retry_after)))
            except ValueError:
                try:
                    retry_at = parsedate_to_datetime(retry_after)
                    if retry_at.tzinfo is not None:
                        return min(
                            self.retry_max_delay_seconds,
                            max(0.0, retry_at.timestamp() - time.time()),
                        )
                except (TypeError, ValueError, OverflowError):
                    pass
        return min(
            self.retry_max_delay_seconds,
            self.retry_base_delay_seconds * (2 ** max(0, retry_index - 1)),
        )

    def get(
        self,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        stream: bool = True,
        timeout: float | tuple[float, float] | None = None,
        allow_redirects: bool = True,
    ) -> requests.Response:
        """GET once or retry only retryable failures; the final response is returned."""

        request_headers = self.default_headers
        request_headers.update({str(key): str(value) for key, value in (headers or {}).items()})
        effective_timeout = self.timeout if timeout is None else timeout
        total_attempts = self.max_retries + 1
        for attempt in range(1, total_attempts + 1):
            try:
                response = self._session().get(
                    url,
                    headers=request_headers,
                    stream=stream,
                    timeout=effective_timeout,
                    allow_redirects=allow_redirects,
                )
            except requests.RequestException:
                if attempt >= total_attempts:
                    raise
                time.sleep(self._retry_delay_seconds(None, attempt))
                continue
            if response.status_code not in self._RETRYABLE_STATUS_CODES or attempt >= total_attempts:
                return response
            delay = self._retry_delay_seconds(response, attempt)
            response.close()
            time.sleep(delay)

        raise RuntimeError("full-text HTTP retry loop exhausted without a response")
