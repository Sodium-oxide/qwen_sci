"""Schemas and deterministic helpers for the normalized science state store.

The module is intentionally free of filesystem writes.  Physical access,
locking, transactions, and reference resolution remain the exclusive
responsibility of :class:`ScienceStateManager`.
"""
from __future__ import annotations

from hashlib import sha256
from pathlib import PurePosixPath
from typing import Any, Iterable
import copy
import json
import re


SCIENCE_PROJECT_MANIFEST_SCHEMA_VERSION = "science_project_manifest_v1"
SCIENCE_ARTIFACT_REF_SCHEMA_VERSION = "science_artifact_ref_v1"
SCIENCE_FRAGMENT_INDEX_SCHEMA_VERSION = "science_fragment_index_v1"
SCIENCE_FRAGMENT_REGISTRY_SCHEMA_VERSION = "science_fragment_registry_v1"
SCIENCE_TRANSACTION_AUDIT_SCHEMA_VERSION = "science_transaction_audit_v1"
NORMALIZED_ARTIFACT_STORAGE_FORMAT = "normalized_artifact_store_v1"
MAX_PROJECT_MANIFEST_BYTES = 256 * 1024

_SAFE_PATH_PART = re.compile(r"^[A-Za-z0-9_.-]+$")
_MANIFEST_REF_FIELDS = {
    "paper_refs",
    "gap_refs",
    "bundle_refs",
    "contract_refs",
    "report_refs",
    "run_summary_refs",
    "project_field_refs",
    "research_evidence_graph_refs",
    "tanxi_detector_result_refs",
    "subhypothesis_contract_refs",
    "retrieval_execution_refs",
    "tanxi_input_manifest_refs",
}


class ScienceManifestValidationError(ValueError):
    pass


def canonical_json_bytes(value: Any, *, pretty: bool = False) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        indent=2 if pretty else None,
        separators=None if pretty else (",", ":"),
        default=str,
    ).encode("utf-8")


def content_hash(value: Any, *, omit_content_hash: bool = False) -> str:
    payload = copy.deepcopy(value)
    if omit_content_hash and isinstance(payload, dict):
        payload.pop("content_hash", None)
    return "sha256:" + sha256(canonical_json_bytes(payload)).hexdigest()


def with_content_hash(value: dict[str, Any]) -> dict[str, Any]:
    payload = copy.deepcopy(value)
    payload["content_hash"] = content_hash(payload, omit_content_hash=True)
    return payload


def safe_relative_artifact_path(path: str) -> str:
    """Return one normalized POSIX path and reject traversal/absolute paths."""
    normalized = str(PurePosixPath(str(path or "").replace("\\", "/")))
    parts = PurePosixPath(normalized).parts
    if not normalized or normalized == "." or normalized.startswith("/"):
        raise ScienceManifestValidationError(f"Artifact path must be relative: {path!r}")
    if any(part in {"", ".", ".."} or not _SAFE_PATH_PART.fullmatch(part) for part in parts):
        raise ScienceManifestValidationError(f"Unsafe artifact path: {path!r}")
    return normalized


def science_artifact_ref(
    *,
    state_store_id: str,
    project_id: str,
    artifact_type: str,
    artifact_id: str,
    artifact_version: int,
    path: str,
    artifact_hash: str,
) -> dict[str, Any]:
    ref = {
        "ref_schema": SCIENCE_ARTIFACT_REF_SCHEMA_VERSION,
        "state_store_id": str(state_store_id or "").strip(),
        "project_id": str(project_id or "").strip(),
        "artifact_type": str(artifact_type or "").strip(),
        "artifact_id": str(artifact_id or "").strip(),
        "artifact_version": max(0, int(artifact_version or 0)),
        "path": safe_relative_artifact_path(path),
        "content_hash": str(artifact_hash or "").strip(),
    }
    validate_science_artifact_ref(ref)
    return ref


def validate_science_artifact_ref(
    ref: Any,
    *,
    state_store_id: str = "",
    project_id: str = "",
) -> dict[str, Any]:
    if not isinstance(ref, dict):
        raise ScienceManifestValidationError("Science artifact reference must be an object")
    required = {
        "ref_schema", "state_store_id", "project_id", "artifact_type",
        "artifact_id", "artifact_version", "path", "content_hash",
    }
    missing = sorted(key for key in required if ref.get(key) in {None, ""})
    if missing:
        raise ScienceManifestValidationError(
            f"Science artifact reference is missing: {', '.join(missing)}"
        )
    if ref.get("ref_schema") != SCIENCE_ARTIFACT_REF_SCHEMA_VERSION:
        raise ScienceManifestValidationError("Unknown science artifact reference schema")
    if state_store_id and str(ref.get("state_store_id")) != str(state_store_id):
        raise ScienceManifestValidationError("Science artifact reference store mismatch")
    if project_id and str(ref.get("project_id")) != str(project_id):
        raise ScienceManifestValidationError("Science artifact reference project mismatch")
    safe_relative_artifact_path(str(ref.get("path") or ""))
    if int(ref.get("artifact_version") or 0) < 0:
        raise ScienceManifestValidationError("Artifact version cannot be negative")
    if not str(ref.get("content_hash") or "").startswith("sha256:"):
        raise ScienceManifestValidationError("Science artifact reference requires sha256 content_hash")
    return copy.deepcopy(ref)


def manifest_content_hash(manifest: dict[str, Any]) -> str:
    return content_hash(manifest, omit_content_hash=True)


def finalize_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    payload = copy.deepcopy(manifest)
    payload["content_hash"] = manifest_content_hash(payload)
    validate_project_manifest(payload)
    return payload


def _iter_manifest_refs(manifest: dict[str, Any]) -> Iterable[dict[str, Any]]:
    for field in _MANIFEST_REF_FIELDS:
        value = manifest.get(field)
        if isinstance(value, dict):
            for ref in value.values():
                if isinstance(ref, dict):
                    yield ref
    for field in (
        "latest_report_ref", "latest_run_summary_ref", "fragment_registry_ref",
        "paper_index_ref", "source_span_registry_ref", "assertion_registry_ref",
        "source_span_registry_root_ref", "assertion_registry_root_ref",
        "active_research_evidence_graph_ref", "active_tanxi_input_manifest_ref",
    ):
        ref = manifest.get(field)
        if isinstance(ref, dict):
            yield ref


def validate_project_manifest(manifest: Any) -> dict[str, Any]:
    if not isinstance(manifest, dict):
        raise ScienceManifestValidationError("Project manifest must be an object")
    if manifest.get("schema_version") != SCIENCE_PROJECT_MANIFEST_SCHEMA_VERSION:
        raise ScienceManifestValidationError("Unknown project manifest schema")
    if manifest.get("storage_format") != NORMALIZED_ARTIFACT_STORAGE_FORMAT:
        raise ScienceManifestValidationError("Unknown normalized storage format")
    required = (
        "project_id", "state_version", "state_store_id", "artifact_versions",
        "project_metadata", "paper_ids", "gap_ids", "knowledge_gap_ids",
        "ranked_gap_ids", "primary_gap_ids", "secondary_gap_ids",
        "paper_refs", "gap_refs", "bundle_refs", "contract_refs",
        "report_refs", "run_summary_refs", "project_field_refs",
        "last_committed_transaction_id",
        "updated_at", "content_hash",
    )
    missing = [key for key in required if key not in manifest]
    if missing:
        raise ScienceManifestValidationError(
            f"Project manifest is missing: {', '.join(missing)}"
        )
    project_id = str(manifest.get("project_id") or "")
    store_id = str(manifest.get("state_store_id") or "")
    if not project_id or not store_id:
        raise ScienceManifestValidationError("Project manifest identity is incomplete")
    for field in (
        "paper_ids", "gap_ids", "knowledge_gap_ids", "ranked_gap_ids",
        "primary_gap_ids", "secondary_gap_ids",
    ):
        values = manifest.get(field)
        if not isinstance(values, list) or any(not isinstance(item, str) for item in values):
            raise ScienceManifestValidationError(f"Project manifest {field} must be a string list")
        if len(values) != len(set(values)):
            raise ScienceManifestValidationError(f"Project manifest {field} contains duplicates")
    for ref in _iter_manifest_refs(manifest):
        validate_science_artifact_ref(ref, state_store_id=store_id, project_id=project_id)
    expected = manifest_content_hash(manifest)
    if manifest.get("content_hash") != expected:
        raise ScienceManifestValidationError("Project manifest content_hash mismatch")
    size = len(canonical_json_bytes(manifest, pretty=True))
    if size > MAX_PROJECT_MANIFEST_BYTES:
        raise ScienceManifestValidationError(
            f"Project manifest exceeds {MAX_PROJECT_MANIFEST_BYTES} bytes: {size}"
        )
    return {
        "valid": True,
        "schema_version": SCIENCE_PROJECT_MANIFEST_SCHEMA_VERSION,
        "content_hash": expected,
        "serialized_bytes": size,
        "reference_count": sum(1 for _ in _iter_manifest_refs(manifest)),
    }


def encode_indexed_jsonl(records: Iterable[dict[str, Any]]) -> tuple[bytes, dict[str, dict[str, int]]]:
    """Encode canonical fragments and return byte-accurate random-access offsets."""
    chunks: list[bytes] = []
    index: dict[str, dict[str, int]] = {}
    offset = 0
    for record in records:
        fragment_id = str(record.get("fragment_id") or "").strip()
        if not fragment_id:
            raise ScienceManifestValidationError("Indexed JSONL fragment lacks fragment_id")
        if fragment_id in index:
            continue
        body = canonical_json_bytes(record)
        chunks.append(body + b"\n")
        index[fragment_id] = {"offset": offset, "length": len(body)}
        offset += len(body) + 1
    return b"".join(chunks), index


def fragment_index_document(
    *,
    alignment_contract_hash: str,
    paper_id: str,
    jsonl_path: str,
    entries: dict[str, dict[str, int]],
) -> dict[str, Any]:
    return with_content_hash({
        "schema_version": SCIENCE_FRAGMENT_INDEX_SCHEMA_VERSION,
        "alignment_contract_hash": str(alignment_contract_hash),
        "paper_id": str(paper_id),
        "jsonl_path": safe_relative_artifact_path(jsonl_path),
        "entries": copy.deepcopy(entries),
    })


def fragment_registry_document(entries: dict[str, dict[str, Any]]) -> dict[str, Any]:
    return with_content_hash({
        "schema_version": SCIENCE_FRAGMENT_REGISTRY_SCHEMA_VERSION,
        "entries": copy.deepcopy(entries),
    })
