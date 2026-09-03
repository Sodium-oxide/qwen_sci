"""Content-addressed local snapshots for reproducible ExperimentDesign runs."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
from threading import RLock
from typing import Any
from uuid import uuid4


EXPERIMENT_DESIGN_CACHE_SCHEMA_VERSION = "experiment_design_cache_v1"
EXPERIMENT_DESIGN_RUN_MANIFEST_SCHEMA_VERSION = "experiment_design_cache_run_manifest_v1"
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


def text_digest(value: object) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _safe_segment(value: object, *, fallback: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9_.-]+", "-", str(value or "").strip()).strip(".-")
    return normalized[:120] or fallback


class ExperimentDesignCache:
    """Store immutable JSON snapshots and a mutable latest-snapshot index.

    Cache failures are deliberately non-fatal: callers receive a cache miss and
    can apply their existing per-batch degradation policy.  ``read_only`` is
    the exception to external work: callers can check ``offline`` and avoid a
    network or LLM call when no matching snapshot is available.
    """

    def __init__(self, config: object | None = None) -> None:
        self.enabled = _as_bool(_setting(config, "enabled", True), True)
        requested_mode = str(_setting(config, "mode", "read_write") or "read_write").strip().casefold()
        self.mode = requested_mode if requested_mode in _CACHE_MODES else "read_write"
        if not self.enabled:
            self.mode = "disabled"
        root = str(_setting(config, "root", ".science/cache/experiment_design/v1") or ".science/cache/experiment_design/v1")
        self.root = Path(root).expanduser()
        self._lock = RLock()

    @property
    def can_read(self) -> bool:
        return self.mode != "disabled"

    @property
    def can_write(self) -> bool:
        return self.mode in {"read_write", "refresh"}

    @property
    def offline(self) -> bool:
        return self.mode == "read_only"

    def logical_key(self, namespace: str, identity: Mapping[str, Any]) -> str:
        return content_digest(
            {
                "cache_schema_version": EXPERIMENT_DESIGN_CACHE_SCHEMA_VERSION,
                "namespace": namespace,
                "identity": identity,
            }
        )

    def begin_run(self, brief_id: object, *, run_id: str | None = None) -> str:
        if not self.can_read:
            return ""
        resolved_run_id = run_id or (
            f"{_safe_segment(brief_id, fallback='brief')}-"
            f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}-{uuid4().hex[:10]}"
        )
        manifest_path = self._manifest_path(resolved_run_id)
        with self._lock:
            if manifest_path.is_file():
                return resolved_run_id
            if not self.can_write:
                return resolved_run_id
            manifest = {
                "schema_version": EXPERIMENT_DESIGN_RUN_MANIFEST_SCHEMA_VERSION,
                "run_id": resolved_run_id,
                "brief_id": str(brief_id or ""),
                "created_at": _utc_now(),
                "cache_root": str(self.root),
                "records": [],
            }
            try:
                self._atomic_write_json(manifest_path, manifest)
            except OSError:
                return ""
        return resolved_run_id

    def run_manifest(self, run_id: object) -> dict[str, Any]:
        normalized_run_id = str(run_id or "").strip()
        if not normalized_run_id:
            return {}
        try:
            return self._read_json(self._manifest_path(normalized_run_id))
        except (OSError, ValueError, json.JSONDecodeError):
            return {}

    def run_manifest_path(self, run_id: object) -> str:
        normalized_run_id = str(run_id or "").strip()
        return str(self._manifest_path(normalized_run_id)) if normalized_run_id else ""

    def read(
        self,
        namespace: str,
        identity: Mapping[str, Any],
        *,
        run_id: str = "",
        snapshot_key: str = "",
    ) -> dict[str, Any] | None:
        if not self.can_read or self.mode == "refresh":
            return None
        logical_key = self.logical_key(namespace, identity)
        try:
            with self._lock:
                resolved_snapshot_key = snapshot_key or str(
                    self._read_json(self._index_path(namespace, logical_key)).get("snapshot_key") or ""
                )
                if not resolved_snapshot_key:
                    self._record(run_id, namespace, logical_key, "", "miss")
                    return None
                envelope = self._read_json(self._object_path(namespace, resolved_snapshot_key))
                expected_snapshot_key = content_digest(
                    {
                        "namespace": namespace,
                        "logical_key": logical_key,
                        "metadata": envelope.get("metadata", {}),
                        "payload": envelope.get("payload", {}),
                    }
                )
                if envelope.get("snapshot_key") != resolved_snapshot_key or expected_snapshot_key != resolved_snapshot_key:
                    self._record(run_id, namespace, logical_key, resolved_snapshot_key, "corrupt")
                    return None
                payload = envelope.get("payload")
                if not isinstance(payload, Mapping):
                    self._record(run_id, namespace, logical_key, resolved_snapshot_key, "corrupt")
                    return None
                self._record(run_id, namespace, logical_key, resolved_snapshot_key, "hit")
                return deepcopy(dict(payload))
        except (OSError, ValueError, json.JSONDecodeError):
            return None

    def write(
        self,
        namespace: str,
        identity: Mapping[str, Any],
        payload: Mapping[str, Any],
        *,
        metadata: Mapping[str, Any] | None = None,
        run_id: str = "",
    ) -> str:
        if not self.can_write:
            return ""
        logical_key = self.logical_key(namespace, identity)
        safe_metadata = dict(metadata or {})
        safe_payload = deepcopy(dict(payload))
        snapshot_key = content_digest(
            {
                "namespace": namespace,
                "logical_key": logical_key,
                "metadata": safe_metadata,
                "payload": safe_payload,
            }
        )
        envelope = {
            "schema_version": EXPERIMENT_DESIGN_CACHE_SCHEMA_VERSION,
            "namespace": namespace,
            "logical_key": logical_key,
            "snapshot_key": snapshot_key,
            "created_at": _utc_now(),
            "metadata": safe_metadata,
            "payload": safe_payload,
        }
        try:
            with self._lock:
                object_path = self._object_path(namespace, snapshot_key)
                if not object_path.is_file():
                    self._atomic_write_json(object_path, envelope)
                self._atomic_write_json(
                    self._index_path(namespace, logical_key),
                    {
                        "schema_version": EXPERIMENT_DESIGN_CACHE_SCHEMA_VERSION,
                        "namespace": namespace,
                        "logical_key": logical_key,
                        "snapshot_key": snapshot_key,
                        "updated_at": _utc_now(),
                    },
                )
                self._record(run_id, namespace, logical_key, snapshot_key, "written")
        except OSError:
            return ""
        return snapshot_key

    def _object_path(self, namespace: str, snapshot_key: str) -> Path:
        return self.root / "objects" / _safe_segment(namespace, fallback="unknown") / f"{snapshot_key}.json"

    def _index_path(self, namespace: str, logical_key: str) -> Path:
        return self.root / "indexes" / _safe_segment(namespace, fallback="unknown") / f"{logical_key}.json"

    def _manifest_path(self, run_id: str) -> Path:
        return self.root / "runs" / _safe_segment(run_id, fallback="run") / "manifest.json"

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any]:
        with path.open("r", encoding="utf-8") as handle:
            loaded = json.load(handle)
        return dict(loaded) if isinstance(loaded, Mapping) else {}

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

    def _record(
        self,
        run_id: str,
        namespace: str,
        logical_key: str,
        snapshot_key: str,
        action: str,
    ) -> None:
        if not run_id or not self.can_write:
            return
        manifest_path = self._manifest_path(run_id)
        manifest = self._read_json(manifest_path) if manifest_path.is_file() else {
            "schema_version": EXPERIMENT_DESIGN_RUN_MANIFEST_SCHEMA_VERSION,
            "run_id": run_id,
            "brief_id": "",
            "created_at": _utc_now(),
            "cache_root": str(self.root),
            "records": [],
        }
        records = manifest.get("records")
        if not isinstance(records, list):
            records = []
        record = {
            "namespace": namespace,
            "logical_key": logical_key,
            "snapshot_key": snapshot_key,
            "action": action,
            "recorded_at": _utc_now(),
        }
        if not any(
            isinstance(existing, Mapping)
            and all(existing.get(field) == record[field] for field in ("namespace", "logical_key", "snapshot_key", "action"))
            for existing in records
        ):
            records.append(record)
            manifest["records"] = records
            self._atomic_write_json(manifest_path, manifest)


__all__ = [
    "EXPERIMENT_DESIGN_CACHE_SCHEMA_VERSION",
    "EXPERIMENT_DESIGN_RUN_MANIFEST_SCHEMA_VERSION",
    "ExperimentDesignCache",
    "canonical_json",
    "content_digest",
    "text_digest",
]
