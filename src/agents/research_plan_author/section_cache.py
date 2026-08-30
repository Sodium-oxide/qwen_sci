"""Versioned content-addressed reuse for validated Author sections."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from threading import RLock
from typing import Any
from uuid import uuid4


SECTION_COMPOSITION_CACHE_SCHEMA_VERSION = "research_plan_author_section_cache_v1"
SECTION_COMPOSITION_CACHE_REVISION = "4"
_CACHE_MODES = {"disabled", "read_write", "read_only", "refresh"}


def _setting(value: object, key: str, default: object = "") -> object:
    if isinstance(value, Mapping):
        return value.get(key, default)
    return getattr(value, key, default)


def _as_bool(value: object, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).strip().casefold() in {"1", "true", "yes", "on"}


def _canonical(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _canonical(item) for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_canonical(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    return str(value)


def canonical_json(value: object) -> str:
    return json.dumps(_canonical(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def content_digest(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def section_cache_identity(
    *,
    preparation: Mapping[str, Any],
    blueprint: Mapping[str, Any],
    route: Mapping[str, Any],
    blueprint_section: Mapping[str, Any],
    source_registry: Mapping[str, Any],
) -> dict[str, Any]:
    """Capture every source-bounded input that can change a section result."""

    source_bundle = preparation.get("source_bundle")
    return {
        "cache_schema_version": SECTION_COMPOSITION_CACHE_SCHEMA_VERSION,
        "composer_revision": SECTION_COMPOSITION_CACHE_REVISION,
        "source_bundle": deepcopy(dict(source_bundle)) if isinstance(source_bundle, Mapping) else {},
        "blueprint_global_constraints": deepcopy(dict(blueprint.get("global_constraints") or {})),
        "blueprint_argument_ledger": deepcopy(dict(blueprint.get("argument_ledger") or {})),
        "route": deepcopy(dict(route)),
        "blueprint_section": deepcopy(dict(blueprint_section)),
        "source_registry": deepcopy(dict(source_registry)),
    }


class SectionCompositionCache:
    """Store only complete, validated section payloads; cache failures are misses."""

    def __init__(self, config: object | None = None) -> None:
        self.enabled = _as_bool(_setting(config, "enabled", True), True)
        requested_mode = str(_setting(config, "mode", "read_write") or "read_write").strip().casefold()
        self.mode = requested_mode if requested_mode in _CACHE_MODES else "read_write"
        if not self.enabled:
            self.mode = "disabled"
        root = str(_setting(config, "root", ".science/cache/research_plan_author/v1") or ".science/cache/research_plan_author/v1")
        self.root = Path(root).expanduser().resolve()
        self._lock = RLock()
        self._stats = {"hits": 0, "misses": 0, "writes": 0, "corrupt": 0}

    @property
    def can_read(self) -> bool:
        return self.mode not in {"disabled", "refresh"}

    @property
    def can_write(self) -> bool:
        return self.mode in {"read_write", "refresh"}

    def read(self, identity: Mapping[str, Any]) -> dict[str, Any] | None:
        if not self.can_read:
            return None
        identity_digest = content_digest(identity)
        try:
            with self._lock:
                with self._path_for(identity_digest).open("r", encoding="utf-8") as handle:
                    envelope = json.load(handle)
                if not isinstance(envelope, Mapping):
                    self._stats["corrupt"] += 1
                    return None
                section = envelope.get("section")
                if (
                    envelope.get("schema_version") != SECTION_COMPOSITION_CACHE_SCHEMA_VERSION
                    or envelope.get("identity_digest") != identity_digest
                    or not isinstance(section, Mapping)
                    or envelope.get("section_digest") != content_digest(section)
                ):
                    self._stats["corrupt"] += 1
                    return None
                self._stats["hits"] += 1
                return deepcopy(dict(section))
        except (OSError, ValueError, json.JSONDecodeError):
            with self._lock:
                self._stats["misses"] += 1
            return None

    def write(self, identity: Mapping[str, Any], section: Mapping[str, Any]) -> bool:
        if not self.can_write:
            return False
        identity_digest = content_digest(identity)
        safe_section = deepcopy(dict(section))
        envelope = {
            "schema_version": SECTION_COMPOSITION_CACHE_SCHEMA_VERSION,
            "identity_digest": identity_digest,
            "section_digest": content_digest(safe_section),
            "created_at": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "section": safe_section,
        }
        try:
            with self._lock:
                self._atomic_write_json(self._path_for(identity_digest), envelope)
                self._stats["writes"] += 1
            return True
        except OSError:
            return False

    def summary(self) -> dict[str, Any]:
        with self._lock:
            return {
                "schema_version": SECTION_COMPOSITION_CACHE_SCHEMA_VERSION,
                "mode": self.mode,
                "root": str(self.root),
                **self._stats,
            }

    def _path_for(self, identity_digest: str) -> Path:
        return self.root / "sections" / f"{identity_digest}.json"

    @staticmethod
    def _atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
        try:
            with temporary_path.open("x", encoding="utf-8", newline="\n") as handle:
                handle.write(canonical_json(payload))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_path, path)
        finally:
            if temporary_path.exists():
                try:
                    temporary_path.unlink()
                except OSError:
                    pass


__all__ = [
    "SECTION_COMPOSITION_CACHE_REVISION",
    "SECTION_COMPOSITION_CACHE_SCHEMA_VERSION",
    "SectionCompositionCache",
    "content_digest",
    "section_cache_identity",
]
