"""Redact local paths and credentials before returning operational data."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any


PATH_KEYS = frozenset({"attempt_dir", "result_path", "outputs", "input_identity", "run_dir", "path"})
_SENSITIVE_KEY_PARTS = frozenset(
    {
        "api_key",
        "apikey",
        "access_token",
        "refresh_token",
        "id_token",
        "authorization",
        "password",
        "passwd",
        "secret",
        "client_secret",
        "cookie",
        "set_cookie",
        "private_key",
    }
)
_WINDOWS_PATH = re.compile(r"(?i)(?:[A-Z]:[\\/]|\\\\)[^\r\n'\"]+")
_POSIX_PATH = re.compile(r"(?<![A-Za-z0-9_.-])/(?:[^\s'\"]+/)+[^\s'\"]*")
_SENSITIVE_ASSIGNMENT = re.compile(
    r"(?im)(?P<prefix>\b(?:api[-_]?key|access[-_]?token|refresh[-_]?token|id[-_]?token|"
    r"authorization|password|passwd|client[-_]?secret|secret|cookie|set[-_]?cookie|private[-_]?key)\b"
    r"\s*(?:=|:)\s*)(?P<value>\"[^\"]*\"|'[^']*'|[^\s,;]+)"
)
_SENSITIVE_HEADER = re.compile(r"(?im)^(?P<prefix>\s*(?:authorization|cookie|set-cookie)\s*:\s*)[^\r\n]*")
_BEARER_TOKEN = re.compile(r"(?i)(\bbearer\s+)[A-Za-z0-9._~+/=-]+")


def _normalized_key(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value).casefold()).strip("_")


def is_sensitive_key(value: object) -> bool:
    normalized = _normalized_key(value)
    return normalized in _SENSITIVE_KEY_PARTS or normalized.endswith("_secret") or normalized.endswith("_token")


def safe_text(value: str) -> str:
    """Return readable log text without machine-local paths or credentials."""

    redacted = _SENSITIVE_HEADER.sub(lambda match: f"{match.group('prefix')}[redacted]", value)
    redacted = _SENSITIVE_ASSIGNMENT.sub(lambda match: f"{match.group('prefix')}[redacted]", redacted)
    redacted = _BEARER_TOKEN.sub(r"\1[redacted]", redacted)
    redacted = _WINDOWS_PATH.sub("[local path]", redacted)
    return _POSIX_PATH.sub("[local path]", redacted)


def safe_payload(value: Any, *, omitted_keys: frozenset[str] = PATH_KEYS) -> Any:
    """Recursively remove path fields and redact sensitive values from JSON-like data."""

    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for raw_key, child in value.items():
            key = str(raw_key)
            if key in omitted_keys:
                continue
            result[key] = "[redacted]" if is_sensitive_key(key) else safe_payload(child, omitted_keys=omitted_keys)
        return result
    if isinstance(value, list):
        return [safe_payload(child, omitted_keys=omitted_keys) for child in value]
    if isinstance(value, str):
        return safe_text(value)
    return value
