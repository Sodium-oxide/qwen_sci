"""Canonical JSON and safe identifiers used by all persisted role-A data."""

from __future__ import annotations

from hashlib import sha256
from pathlib import PurePosixPath
from typing import Any
import json
import re

from .errors import UnsafeArtifactPathError


_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


def canonical_json_bytes(value: Any, *, pretty: bool = False) -> bytes:
    """Serialize deterministically; schemas prohibit NaN and non-JSON objects."""

    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        indent=2 if pretty else None,
        separators=None if pretty else (",", ":"),
    ).encode("utf-8")


def sha256_digest(value: Any) -> str:
    return "sha256:" + sha256(canonical_json_bytes(value)).hexdigest()


def sha256_bytes(value: bytes) -> str:
    return "sha256:" + sha256(value).hexdigest()


def require_safe_identifier(value: str, *, field: str) -> str:
    normalized = str(value or "").strip()
    if not _SAFE_IDENTIFIER.fullmatch(normalized):
        raise UnsafeArtifactPathError(
            f"{field} must match {_SAFE_IDENTIFIER.pattern}",
            field_path=field,
            context={"value": normalized},
        )
    return normalized


def safe_relative_path(value: str) -> str:
    raw = str(value or "").replace("\\", "/")
    path = PurePosixPath(raw)
    if not raw or raw.startswith("/") or path.is_absolute():
        raise UnsafeArtifactPathError("Artifact path must be relative", context={"path": raw})
    if any(part in {"", ".", ".."} for part in path.parts):
        raise UnsafeArtifactPathError("Artifact path contains traversal", context={"path": raw})
    return path.as_posix()

