"""Structured console and JSONL logging for the ExperimentDesign workflow."""

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


LOGGING_SCHEMA_VERSION = "experiment_design_run_log_v1"
_LEVELS = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40, "CRITICAL": 50}
_CORE_FIELDS = {
    "timestamp",
    "level",
    "run_id",
    "stage",
    "event",
    "status",
    "elapsed_ms",
}
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


class RunLoggingError(RuntimeError):
    """Raised when a configured log sink cannot be written."""


def _normalize_level(level: str) -> str:
    normalized = str(level or "INFO").strip().upper()
    if normalized not in _LEVELS:
        raise ValueError(f"Unsupported log level: {level}")
    return normalized


def _safe_text(value: object, *, limit: int = 2000) -> str:
    text = str(value or "")
    text = _SECRET_PATTERN.sub(lambda match: f"{match.group(1)}=[REDACTED]", text)
    return text[:limit]


def _key_is_sensitive(key: object) -> bool:
    normalized = re.sub(r"[^a-z0-9]+", "_", str(key).strip().casefold()).strip("_")
    return normalized in _SENSITIVE_KEYS or normalized.endswith("_prompt") or normalized.endswith("_raw_response")


def _sanitize(value: object, *, key: object = "") -> object:
    if _key_is_sensitive(key):
        return "[REDACTED]"
    if isinstance(value, Mapping):
        return {
            str(item_key): _sanitize(item_value, key=item_key)
            for item_key, item_value in list(value.items())[:100]
        }
    if isinstance(value, (list, tuple, set)):
        return [_sanitize(item) for item in list(value)[:100]]
    if isinstance(value, str):
        return _safe_text(value)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return _safe_text(value)


def _format_console_value(value: object) -> str:
    if isinstance(value, (Mapping, list, tuple)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return str(value)


class ExperimentDesignRunLogger:
    """Emit human-readable console events and structured JSONL records."""

    def __init__(
        self,
        run_id: str,
        *,
        jsonl_path: str | Path | None = None,
        log_file: str | Path | None = None,
        console_stream: TextIO | None = None,
        console_level: str = "INFO",
        console_enabled: bool = True,
    ) -> None:
        normalized_run_id = _safe_text(run_id, limit=300).strip()
        if not normalized_run_id:
            raise ValueError("run_id must be non-empty")
        if jsonl_path is not None and log_file is not None:
            raise ValueError("Pass only one of jsonl_path or log_file")
        self.run_id = normalized_run_id
        self.console_level = _normalize_level(console_level)
        self.console_stream = console_stream if console_stream is not None else sys.stderr
        self.console_enabled = bool(console_enabled)
        self.jsonl_path: Path | None = None
        self._file: TextIO | None = None
        self._records: list[dict[str, Any]] = []
        self._lock = RLock()
        target = jsonl_path if jsonl_path is not None else log_file
        if target is not None:
            self.jsonl_path = Path(target).expanduser().resolve()
            try:
                self.jsonl_path.parent.mkdir(parents=True, exist_ok=True)
                self._file = self.jsonl_path.open("a", encoding="utf-8", buffering=1)
            except OSError as exc:
                raise RunLoggingError(f"Cannot open log file '{self.jsonl_path}': {exc}") from exc

    @property
    def records(self) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(record) for record in self._records]

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
        normalized_level = _normalize_level(level)
        normalized_stage = _safe_text(stage, limit=160).strip()
        normalized_event = _safe_text(event, limit=160).strip()
        normalized_status = _safe_text(status, limit=100).strip() or "INFO"
        if not normalized_stage or not normalized_event:
            raise ValueError("stage and event must be non-empty")
        record: dict[str, Any] = {
            "schema_version": LOGGING_SCHEMA_VERSION,
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "level": normalized_level,
            "run_id": self.run_id,
            "stage": normalized_stage,
            "event": normalized_event,
            "status": normalized_status,
            "elapsed_ms": round(float(elapsed_ms), 3) if elapsed_ms is not None else None,
        }
        sanitized_fields = _sanitize(fields)
        if isinstance(sanitized_fields, Mapping):
            for key, value in sanitized_fields.items():
                if key not in _CORE_FIELDS and key != "schema_version":
                    record[key] = value
        line = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        with self._lock:
            self._records.append(dict(record))
            try:
                if self._file is not None:
                    self._file.write(line + "\n")
                    self._file.flush()
                if self.console_enabled and _LEVELS[normalized_level] >= _LEVELS[self.console_level]:
                    console_fields = [
                        f"{key}={_format_console_value(record[key])}"
                        for key in sorted(record)
                        if key not in _CORE_FIELDS and key != "schema_version"
                    ]
                    message = " ".join(
                        [
                            record["timestamp"],
                            normalized_level,
                            f"run={self.run_id}",
                            f"stage={normalized_stage}",
                            f"event={normalized_event}",
                            f"status={normalized_status}",
                            f"elapsed_ms={record['elapsed_ms']}",
                            *console_fields,
                        ]
                    )
                    self.console_stream.write(message + "\n")
                    self.console_stream.flush()
            except (OSError, TypeError, ValueError) as exc:
                raise RunLoggingError(f"Cannot write log event '{normalized_stage}/{normalized_event}': {exc}") from exc
        return record

    def event(
        self,
        stage: str,
        event: str,
        *,
        level: str = "INFO",
        status: str = "INFO",
        elapsed_ms: float | None = None,
        **fields: object,
    ) -> dict[str, Any]:
        return self.emit(
            stage,
            event,
            level=level,
            status=status,
            elapsed_ms=elapsed_ms,
            **fields,
        )

    def exception(
        self,
        stage: str,
        error: BaseException,
        *,
        event: str = "failed",
        status: str = "FAILED",
        level: str = "ERROR",
        elapsed_ms: float | None = None,
        error_code: str | None = None,
        **fields: object,
    ) -> dict[str, Any]:
        return self.emit(
            stage,
            event,
            level=level,
            status=status,
            elapsed_ms=elapsed_ms,
            error_code=error_code or type(error).__name__,
            exception_type=type(error).__name__,
            error=_safe_text(str(error), limit=2000),
            **fields,
        )

    @contextmanager
    def stage(self, stage: str, **fields: object) -> Iterator[None]:
        started_at = perf_counter()
        self.emit(stage, "started", status="RUNNING", **fields)
        try:
            yield
        except Exception as error:
            self.exception(stage, error, elapsed_ms=(perf_counter() - started_at) * 1000, **fields)
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
            except OSError as exc:
                raise RunLoggingError(f"Cannot close log file '{self.jsonl_path}': {exc}") from exc
            finally:
                self._file = None

    def __enter__(self) -> "ExperimentDesignRunLogger":
        return self

    def __exit__(self, _exc_type: object, _exc_value: object, _traceback: object) -> None:
        self.close()


RunLogger = ExperimentDesignRunLogger
ExperimentDesignLogger = ExperimentDesignRunLogger


__all__ = [
    "LOGGING_SCHEMA_VERSION",
    "RunLoggingError",
    "ExperimentDesignRunLogger",
    "ExperimentDesignLogger",
    "RunLogger",
]
