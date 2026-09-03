"""Append-only, content-verifiable artifact storage (M15)."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import uuid4
import json
import os

from .canonical import (
    canonical_json_bytes,
    require_safe_identifier,
    safe_relative_path,
    sha256_bytes,
)
from .errors import ArtifactIntegrityError, IdempotencyConflict, ImmutableArtifactConflict
from .schema_registry import SchemaRegistry


class ArtifactStore:
    """Store immutable payload versions and stable descriptors.

    A repeated idempotency key returns the original descriptor. Reusing that
    key for different bytes is rejected instead of silently accepting drift.
    """

    def __init__(self, root: Path | str, registry: SchemaRegistry | None = None) -> None:
        self.root = Path(root).resolve()
        self.registry = registry or SchemaRegistry()

    def _lock(self, artifact_type: str, artifact_id: str):
        try:
            from filelock import FileLock
        except ImportError as exc:
            raise RuntimeError(
                "Role A concurrent storage requires filelock; install requirements-power-core-a.txt"
            ) from exc
        lock_path = self.root / ".locks" / artifact_type / f"{artifact_id}.lock"
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        return FileLock(str(lock_path), timeout=10)

    @staticmethod
    def _write_exclusive(path: Path, body: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            if path.read_bytes() != body:
                raise ImmutableArtifactConflict(
                    "Refusing to overwrite an immutable artifact", context={"path": str(path)}
                )
            return
        temporary = path.parent / f".{path.name}.tmp.{uuid4().hex}"
        try:
            with temporary.open("xb") as stream:
                stream.write(body)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(temporary, path)
            except FileExistsError:
                if path.read_bytes() != body:
                    raise ImmutableArtifactConflict(
                        "Refusing to overwrite an immutable artifact", context={"path": str(path)}
                    )
            except OSError:
                try:
                    with path.open("xb") as destination:
                        destination.write(body)
                        destination.flush()
                        os.fsync(destination.fileno())
                except FileExistsError:
                    if path.read_bytes() != body:
                        raise ImmutableArtifactConflict(
                            "Refusing to overwrite an immutable artifact", context={"path": str(path)}
                        )
        finally:
            temporary.unlink(missing_ok=True)

    def _idempotency_path(self, key: str) -> Path:
        digest = sha256_bytes(str(key).encode("utf-8")).split(":", 1)[1]
        return self.root / "idempotency" / f"{digest}.json"

    def _descriptor_from_path(self, path: Path) -> dict[str, Any]:
        descriptor = json.loads(path.read_text(encoding="utf-8"))
        self.registry.validate("ArtifactDescriptor", descriptor)
        return descriptor

    def put_json(
        self,
        *,
        artifact_id: str,
        artifact_type: str,
        contract_schema: str,
        payload: dict[str, Any],
        producer: str,
        created_at: str,
        lineage_hashes: list[str] | None = None,
        idempotency_key: str,
    ) -> dict[str, Any]:
        artifact_id = require_safe_identifier(artifact_id, field="artifact_id")
        artifact_type = require_safe_identifier(artifact_type, field="artifact_type")
        self.registry.validate(contract_schema, payload)
        body = canonical_json_bytes(payload, pretty=True) + b"\n"
        compact_hash = sha256_bytes(canonical_json_bytes(payload))
        receipt_path = self._idempotency_path(idempotency_key)

        with self._lock(artifact_type, artifact_id):
            if receipt_path.is_file():
                receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
                expected = (artifact_type, artifact_id, compact_hash)
                observed = (receipt.get("artifact_type"), receipt.get("artifact_id"), receipt.get("content_hash"))
                if observed != expected:
                    raise IdempotencyConflict(
                        "An idempotency key was reused for different content",
                        context={"key": idempotency_key, "expected": expected, "observed": observed},
                    )
                return self.verify_descriptor(receipt["descriptor"])

            base = self.root / "artifacts" / artifact_type / artifact_id
            descriptors = sorted(base.glob("v[0-9][0-9][0-9][0-9][0-9][0-9]/descriptor.json"))
            for descriptor_path in descriptors:
                descriptor = self._descriptor_from_path(descriptor_path)
                if descriptor["content_hash"] == compact_hash:
                    self._write_receipt(
                        receipt_path, idempotency_key, artifact_type, artifact_id, compact_hash, descriptor
                    )
                    return self.verify_descriptor(descriptor)

            version = len(descriptors) + 1
            version_dir = base / f"v{version:06d}"
            payload_path = version_dir / "payload.json"
            relative_path = safe_relative_path(payload_path.relative_to(self.root).as_posix())
            descriptor = {
                "schema_version": "artifact_descriptor_v1",
                "artifact_id": artifact_id,
                "artifact_type": artifact_type,
                "artifact_version": version,
                "contract_schema": contract_schema,
                "content_hash": compact_hash,
                "byte_size": len(body),
                "relative_path": relative_path,
                "created_at": created_at,
                "producer": producer,
                "lineage_hashes": sorted(set(lineage_hashes or [])),
            }
            self.registry.validate("ArtifactDescriptor", descriptor)
            self._write_exclusive(payload_path, body)
            self._write_exclusive(
                version_dir / "descriptor.json", canonical_json_bytes(descriptor, pretty=True) + b"\n"
            )
            self._write_receipt(
                receipt_path, idempotency_key, artifact_type, artifact_id, compact_hash, descriptor
            )
            return self.verify_descriptor(descriptor)

    def _write_receipt(
        self,
        path: Path,
        key: str,
        artifact_type: str,
        artifact_id: str,
        content_hash: str,
        descriptor: dict[str, Any],
    ) -> None:
        receipt = {
            "idempotency_key": key,
            "artifact_type": artifact_type,
            "artifact_id": artifact_id,
            "content_hash": content_hash,
            "descriptor": descriptor,
        }
        self._write_exclusive(path, canonical_json_bytes(receipt, pretty=True) + b"\n")

    def verify_descriptor(self, descriptor: dict[str, Any]) -> dict[str, Any]:
        validated = self.registry.validate("ArtifactDescriptor", descriptor)
        relative = safe_relative_path(validated["relative_path"])
        path = (self.root / Path(relative)).resolve()
        try:
            path.relative_to(self.root)
        except ValueError as exc:
            raise ArtifactIntegrityError("Artifact escaped its store root", context={"path": str(path)}) from exc
        if not path.is_file():
            raise ArtifactIntegrityError("Artifact payload is missing", context={"path": str(path)})
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ArtifactIntegrityError("Artifact payload is unreadable", context={"path": str(path)}) from exc
        observed_hash = sha256_bytes(canonical_json_bytes(payload))
        if observed_hash != validated["content_hash"]:
            raise ArtifactIntegrityError(
                "Artifact content hash mismatch",
                context={"path": str(path), "expected": validated["content_hash"], "observed": observed_hash},
            )
        self.registry.validate(validated["contract_schema"], payload)
        return validated

    def read_json(self, descriptor: dict[str, Any]) -> dict[str, Any]:
        validated = self.verify_descriptor(descriptor)
        return json.loads((self.root / validated["relative_path"]).read_text(encoding="utf-8"))

    def latest_descriptor(self, *, artifact_type: str, artifact_id: str) -> dict[str, Any]:
        artifact_type = require_safe_identifier(artifact_type, field="artifact_type")
        artifact_id = require_safe_identifier(artifact_id, field="artifact_id")
        base = self.root / "artifacts" / artifact_type / artifact_id
        descriptors = sorted(base.glob("v[0-9][0-9][0-9][0-9][0-9][0-9]/descriptor.json"))
        if not descriptors:
            raise ArtifactIntegrityError(
                "No artifact descriptor found",
                context={"artifact_type": artifact_type, "artifact_id": artifact_id},
            )
        return self.verify_descriptor(self._descriptor_from_path(descriptors[-1]))

    def list_descriptors(self, *, artifact_type: str) -> list[dict[str, Any]]:
        artifact_type = require_safe_identifier(artifact_type, field="artifact_type")
        base = self.root / "artifacts" / artifact_type
        descriptors = sorted(base.glob("*/v[0-9][0-9][0-9][0-9][0-9][0-9]/descriptor.json"))
        return [self.verify_descriptor(self._descriptor_from_path(path)) for path in descriptors]
