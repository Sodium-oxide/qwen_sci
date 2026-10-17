"""Atomic artifact publishing for durable web Jobs."""

from __future__ import annotations

import hashlib
import json
import mimetypes
import uuid
from pathlib import Path
from typing import Mapping, Sequence

from .jobs.errors import JobInputError, JobStateError
from .jobs.models import JobRecord
from .jobs.store import JobStore
from .jobs.store import canonical_hash, utc_now
from .jobs.runner import JobContext


def write_job_manifest(context: JobContext, payload: Mapping[str, object]) -> Path:
    return prepare_job_manifest(context.job_dir, payload)


def prepare_job_manifest(job_dir: Path, payload: Mapping[str, object]) -> Path:
    path = job_dir / "input.json"
    if path.exists():
        raise JobInputError("A frozen Job manifest cannot be overwritten.")
    _atomic_write_json(path, dict(payload))
    return path


def read_job_manifest(context: JobContext) -> dict[str, object]:
    path = context.job_dir / "input.json"
    try:
        raw = path.read_bytes()
        payload = json.loads(raw)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise JobInputError("Job input manifest is unavailable or invalid.") from exc
    if not isinstance(payload, dict):
        raise JobInputError("Job input manifest must be a JSON object.")
    expected_hash = context.job.input_manifest_sha256
    actual_hash = (
        canonical_hash(payload.get("input")) if payload.get("schema_version") == "web_job_input_v1"
        else hashlib.sha256(raw).hexdigest()
    )
    if actual_hash != expected_hash:
        raise JobInputError("Job input manifest no longer matches its recorded hash.")
    if payload.get("job_id") != context.job.job_id or payload.get("kind") != context.job.kind:
        raise JobInputError("Job input manifest belongs to a different task.")
    prompt = payload.get("prompt", {})
    if not isinstance(prompt, dict) or any(
        prompt.get(key) != getattr(context.job, key)
        for key in ("prompt_id", "prompt_version", "prompt_hash")
    ):
        raise JobInputError("Job prompt metadata does not match the frozen task.")
    return payload


def publish_json_artifact(
    context: JobContext,
    *,
    role: str,
    filename: str,
    payload: Mapping[str, object] | list[object],
    media_type: str = "application/json",
    provenance: Mapping[str, object] | None = None,
    validator_status: str = "NOT_AUDITABLE",
    source_file_ids: Sequence[str] = (),
    max_bytes: int = 52_428_800,
) -> str:
    return publish_bytes_artifact(
        context,
        role=role,
        filename=filename,
        content=json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False).encode("utf-8") + b"\n",
        media_type=media_type,
        provenance=provenance,
        validator_status=validator_status,
        source_file_ids=source_file_ids,
        max_bytes=max_bytes,
    )


def publish_bytes_artifact(
    context: JobContext,
    *,
    role: str,
    filename: str,
    content: bytes,
    media_type: str | None = None,
    provenance: Mapping[str, object] | None = None,
    validator_status: str = "NOT_AUDITABLE",
    source_file_ids: Sequence[str] = (),
    max_bytes: int = 52_428_800,
) -> str:
    context.check_cancelled()
    with context.store.lease_guard(context.job.job_id, lease_owner=context.lease_owner, attempt=context.job.attempt) as leased:
        if leased.status == "CANCEL_REQUESTED":
            from .jobs.runner import JobCancelled

            raise JobCancelled("Job cancellation was requested before publishing.")
        return _write_artifact(
            context.job_dir, leased, role=role, filename=filename, content=content,
            media_type=media_type, provenance=provenance, validator_status=validator_status,
            source_file_ids=source_file_ids, max_bytes=max_bytes,
        )


def publish_export_artifact(
    store: JobStore, record: JobRecord, *, filename: str, content: bytes,
    media_type: str, provenance: Mapping[str, object], source_file_ids: Sequence[str] = (),
    max_bytes: int = 52_428_800,
) -> str:
    current = store.get(record.job_id)
    if current.status != "SUCCEEDED" or current.attempt != record.attempt:
        raise JobStateError("Only the accepted Job attempt can publish a final export.")
    artifact_id = _write_artifact(
        store.job_directory(record.job_id), record, role="reviewed_export", filename=filename,
        content=content, media_type=media_type, provenance=provenance,
        validator_status="PASS", source_file_ids=source_file_ids, max_bytes=max_bytes,
    )
    store.attach_artifact(record.job_id, artifact_id, expected_status="SUCCEEDED", expected_attempt=record.attempt)
    return artifact_id


def _write_artifact(
    job_dir: Path, record: JobRecord, *, role: str, filename: str, content: bytes,
    media_type: str | None, provenance: Mapping[str, object] | None,
    validator_status: str, source_file_ids: Sequence[str], max_bytes: int,
) -> str:
    safe_name = Path(filename).name
    if safe_name != filename or not safe_name or len(safe_name) > 180 or any(char in safe_name for char in "/\\:\x00") or safe_name in {".", ".."}:
        raise ValueError("Artifact filename is invalid.")
    if validator_status not in {"PASS", "WARN", "FAIL", "NOT_AUDITABLE"}:
        raise ValueError("Artifact validator_status is invalid.")
    if len(content) > max(1, int(max_bytes)):
        raise ValueError("Artifact exceeds the configured output size limit.")
    digest = hashlib.sha256(content).hexdigest()
    provenance = {
        "input_manifest_sha256": record.input_manifest_sha256, "revision": record.revision,
        "prompt_id": record.prompt_id, "prompt_version": record.prompt_version, "prompt_hash": record.prompt_hash,
        "model": record.model_name, "provider": record.provider_name, **dict(provenance or {}),
    }
    input_path = job_dir / "input.json"
    if input_path.is_file():
        raw_input = input_path.read_bytes()
        if hashlib.sha256(raw_input).hexdigest() == record.input_manifest_sha256:
            snapshot = json.loads(raw_input)
            provenance["effective_prompt_hash"] = snapshot.get("prompt", {}).get("effective_prompt_hash")
            provenance["generation"] = snapshot.get("model", {}).get("generation", {})
    identity = canonical_hash({"role": role, "filename": safe_name, "sha256": digest, "provenance": provenance})[:20]
    artifact_id = f"artifact-{record.job_id}-{record.attempt}-{identity}"
    attempt_root = job_dir / "artifacts" / f"attempt-{record.attempt:03d}"
    attempt_root.mkdir(parents=True, exist_ok=True)
    target = attempt_root / f"{digest[:16]}-{safe_name}"
    if not target.exists():
        temporary = attempt_root / f".{safe_name}.{uuid.uuid4().hex}.tmp"
        try:
            temporary.write_bytes(content)
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)
    elif hashlib.sha256(target.read_bytes()).hexdigest() != digest:
        raise ValueError("An immutable Artifact path already has different content.")
    manifest = {
        "artifact_id": artifact_id,
        "job_id": record.job_id,
        "attempt": record.attempt,
        "revision": record.revision,
        "role": role,
        "label": safe_name,
        "media_type": media_type or mimetypes.guess_type(safe_name)[0] or "application/octet-stream",
        "relative_path": target.relative_to(job_dir).as_posix(),
        "size_bytes": len(content),
        "sha256": digest,
        "previewable": bool((media_type or "").startswith(("image/", "text/")) or media_type == "application/pdf"),
        "source_file_ids": [str(file_id) for file_id in source_file_ids],
        "validator_status": validator_status,
        "provenance": dict(provenance or {}),
        "created_at": utc_now(),
    }
    manifest_path = attempt_root / f"{identity}.manifest.json"
    if not manifest_path.exists():
        _atomic_write_json(manifest_path, manifest)
    return artifact_id


def list_job_artifacts(job_dir: Path) -> list[dict[str, object]]:
    artifacts: list[dict[str, object]] = []
    root = job_dir / "artifacts"
    if not root.is_dir():
        return artifacts
    for manifest_path in sorted(root.glob("attempt-*/*.manifest.json")):
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict) or not isinstance(payload.get("artifact_id"), str):
            continue
        try:
            attempt = int(payload.get("attempt", 0))
        except (TypeError, ValueError):
            continue
        if payload.get("job_id") == job_dir.name and manifest_path.parent.name == f"attempt-{attempt:03d}":
            artifacts.append(payload)
    return artifacts


def resolve_job_artifact(job_dir: Path, artifact_id: str) -> tuple[Path, dict[str, object]] | None:
    for record in list_job_artifacts(job_dir):
        if record.get("artifact_id") != artifact_id:
            continue
        relative_path = record.get("relative_path")
        if not isinstance(relative_path, str):
            return None
        path = (job_dir / relative_path).resolve()
        try:
            attempt = int(record.get("attempt", 0))
            path.relative_to((job_dir / "artifacts" / f"attempt-{attempt:03d}").resolve())
        except ValueError:
            return None
        if not path.is_file():
            return None
        try:
            if path.stat().st_size != record.get("size_bytes") or hashlib.sha256(path.read_bytes()).hexdigest() != record.get("sha256"):
                return None
        except OSError:
            return None
        return path, record
    return None


def _atomic_write_json(path: Path, payload: Mapping[str, object]) -> None:
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
