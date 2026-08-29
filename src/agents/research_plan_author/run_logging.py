"""Structured, redacted console and JSONL logging for Research Plan Author."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys
from threading import RLock
from time import perf_counter
from collections.abc import Iterator, Mapping
from typing import Any, TextIO


AUTHOR_LOGGING_SCHEMA_VERSION = "research_plan_author_run_log_v1"
_LEVELS = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40, "CRITICAL": 50}
_CORE_FIELDS = {"timestamp", "level", "run_id", "stage", "event", "status", "elapsed_ms"}
_SENSITIVE_KEYS = {
    "prompt",
    "raw",
    "raw_response",
    "response",
    "source_text",
    "fulltext",
    "full_text",
    "abstract",
    "content",
    "api_key",
    "apikey",
    "access_token",
    "token",
    "secret",
    "password",
    "clinical_data",
    "patient_data",
    "personal_data",
    "dangerous_parameters",
    "restricted_protocol",
}
_SECRET_PATTERN = re.compile(
    r"(?i)(api[_ -]?key|access[_ -]?token|token|password|secret)\s*[:=]\s*[^\s,;]+"
)


class AuthorRunLoggingError(RuntimeError):
    """Raised when the Author logger cannot write its configured sink."""


def _safe_text(value: object, *, limit: int = 2000) -> str:
    text = _SECRET_PATTERN.sub(lambda match: f"{match.group(1)}=[REDACTED]", str(value or ""))
    return text[:limit]


def _sanitize(value: object, *, key: object = "") -> object:
    normalized_key = re.sub(r"[^a-z0-9]+", "_", str(key).casefold()).strip("_")
    if normalized_key in _SENSITIVE_KEYS or normalized_key.endswith("_prompt") or normalized_key.endswith("_raw_response"):
        return "[REDACTED]"
    if isinstance(value, Mapping):
        return {str(item_key): _sanitize(item_value, key=item_key) for item_key, item_value in list(value.items())[:100]}
    if isinstance(value, (list, tuple, set)):
        return [_sanitize(item) for item in list(value)[:100]]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return _safe_text(value)


class AuthorRunLogger:
    """Emit structured Author events while redacting prompts, sources, and secrets."""

    def __init__(
        self,
        run_id: str,
        *,
        jsonl_path: str | Path | None = None,
        console_stream: TextIO | None = None,
        console_level: str = "INFO",
        console_enabled: bool = True,
    ) -> None:
        self.run_id = _safe_text(run_id, limit=300).strip()
        if not self.run_id:
            raise ValueError("run_id must be non-empty")
        self.console_level = str(console_level or "INFO").upper()
        if self.console_level not in _LEVELS:
            raise ValueError(f"Unsupported log level: {console_level}")
        self.console_stream = console_stream if console_stream is not None else sys.stderr
        self.console_enabled = bool(console_enabled)
        self.jsonl_path = Path(jsonl_path).expanduser().resolve() if jsonl_path is not None else None
        self._file: TextIO | None = None
        self._lock = RLock()
        if self.jsonl_path is not None:
            try:
                self.jsonl_path.parent.mkdir(parents=True, exist_ok=True)
                self._file = self.jsonl_path.open("a", encoding="utf-8", buffering=1)
            except OSError as error:
                raise AuthorRunLoggingError(f"Cannot open log file '{self.jsonl_path}': {error}") from error

    def emit(
        self,
        stage: str,
        event: str,
        *,
        level: str = "INFO",
        status: str = "INFO",
        elapsed_ms: float | None = None,
        **fields: object,
    ) -> dict[str, Any]:
        normalized_level = str(level or "INFO").upper()
        if normalized_level not in _LEVELS:
            raise ValueError(f"Unsupported log level: {level}")
        normalized_stage = _safe_text(stage, limit=160).strip()
        normalized_event = _safe_text(event, limit=160).strip()
        if not normalized_stage or not normalized_event:
            raise ValueError("stage and event must be non-empty")
        record: dict[str, Any] = {
            "schema_version": AUTHOR_LOGGING_SCHEMA_VERSION,
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "level": normalized_level,
            "run_id": self.run_id,
            "stage": normalized_stage,
            "event": normalized_event,
            "status": _safe_text(status, limit=100).strip() or "INFO",
            "elapsed_ms": round(float(elapsed_ms), 3) if elapsed_ms is not None else None,
        }
        for key, value in _sanitize(fields).items():
            if key not in _CORE_FIELDS and key != "schema_version":
                record[key] = value
        line = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        with self._lock:
            try:
                if self._file is not None:
                    self._file.write(line + "\n")
                    self._file.flush()
                if self.console_enabled and _LEVELS[normalized_level] >= _LEVELS[self.console_level]:
                    rendered_fields = [
                        f"{key}={json.dumps(record[key], ensure_ascii=False, separators=(',', ':')) if isinstance(record[key], (Mapping, list, tuple)) else record[key]}"
                        for key in sorted(record)
                        if key not in _CORE_FIELDS and key != "schema_version"
                    ]
                    self.console_stream.write(
                        " ".join(
                            [
                                record["timestamp"],
                                normalized_level,
                                f"run={self.run_id}",
                                f"stage={normalized_stage}",
                                f"event={normalized_event}",
                                f"status={record['status']}",
                                f"elapsed_ms={record['elapsed_ms']}",
                                *rendered_fields,
                            ]
                        )
                        + "\n"
                    )
                    self.console_stream.flush()
            except (OSError, TypeError, ValueError) as error:
                raise AuthorRunLoggingError(f"Cannot write log event '{normalized_stage}/{normalized_event}': {error}") from error
        return record

    @contextmanager
    def stage(self, stage: str, **fields: object) -> Iterator[None]:
        started_at = perf_counter()
        self.emit(stage, "started", status="RUNNING", **fields)
        try:
            yield
        except Exception as error:
            self.emit(
                stage,
                "failed",
                level="ERROR",
                status="FAILED",
                elapsed_ms=(perf_counter() - started_at) * 1000,
                error_code=type(error).__name__,
                exception_type=type(error).__name__,
                error=_safe_text(str(error)),
                **fields,
            )
            raise
        else:
            self.emit(
                stage,
                "completed",
                status="COMPLETED",
                elapsed_ms=(perf_counter() - started_at) * 1000,
                **fields,
            )

    def close(self) -> None:
        with self._lock:
            if self._file is None:
                return
            try:
                self._file.flush()
                self._file.close()
            except OSError as error:
                raise AuthorRunLoggingError(f"Cannot close log file '{self.jsonl_path}': {error}") from error
            finally:
                self._file = None


__all__ = ["AUTHOR_LOGGING_SCHEMA_VERSION", "AuthorRunLogger", "AuthorRunLoggingError"]
