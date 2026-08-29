"""Durable, split preparation artifacts for resumable evidence extraction."""

from __future__ import annotations

import json
import hashlib
import os
from pathlib import Path
import re
from threading import RLock
from typing import Any, Mapping
from uuid import uuid4

try:
    from .config import SCIENCE_DIR
    from ._evidence_proposition_extraction import PROPOSITION_EXTRACTION_SCHEMA_VERSION
    from ._evidence_slot_alignment import (
        ALIGNMENT_BATCH_ARTIFACT_SCHEMA_VERSION,
        CONTRACT_TASK_ALIGNMENT_INDEX_SCHEMA_VERSION,
    )
except ImportError:
    from config import SCIENCE_DIR
    from _evidence_proposition_extraction import PROPOSITION_EXTRACTION_SCHEMA_VERSION
    from _evidence_slot_alignment import (
        ALIGNMENT_BATCH_ARTIFACT_SCHEMA_VERSION,
        CONTRACT_TASK_ALIGNMENT_INDEX_SCHEMA_VERSION,
    )


PREPARATION_STORE_SCHEMA_VERSION = "evidence_preparation_store_v2"
PREPARED_ARTIFACT_SAFE_PATH_LIMIT = 240
_PREPARATION_STORE_LOCK = RLock()


def _safe_component(value: Any, fallback: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9._-]+", "_", str(value or "").strip())
    return normalized.strip("._-")[:160] or fallback


def _artifact_directory(
    project_id: str,
    paper_id: str,
    document_version_id: str,
) -> Path:
    return (
        Path(SCIENCE_DIR)
        / "prepared_evidence"
        / _safe_component(project_id, "unscoped_project")
        / _safe_component(paper_id, "unknown_paper")
        / _safe_component(document_version_id, "unknown_document_version")
    )


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_name(
        f".{path.stem}.{uuid4().hex[:8]}{path.suffix}.tmp"
    )
    try:
        temporary_path.write_text(
            json.dumps(dict(payload), ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_name(
        f".{path.stem}.{uuid4().hex[:8]}{path.suffix}.tmp"
    )
    try:
        temporary_path.write_text(str(text or ""), encoding="utf-8")
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return dict(value) if isinstance(value, Mapping) else None


def _load_document_proposition_artifact(
    *,
    project_id: str,
    paper_id: str,
    document: Mapping[str, Any],
) -> dict[str, Any] | None:
    document_version_id = str(document.get("document_version_id") or "")
    directory = _artifact_directory(project_id, paper_id, document_version_id)
    manifest = _read_json(directory / "manifest.json")
    if not manifest or any((
        manifest.get("schema_version") != PREPARATION_STORE_SCHEMA_VERSION,
        str(manifest.get("paper_id") or "") != str(paper_id or ""),
        str(manifest.get("document_version_id") or "") != document_version_id,
    )):
        return None
    descriptor = _read_json(directory / "descriptor.json")
    sections_payload = _read_json(directory / "sections.json")
    spans_payload = _read_json(directory / "source_spans.json")
    proposition_artifact = _read_json(directory / "propositions.json")
    alignments_payload = _read_json(directory / "alignments.json")
    if not all((descriptor, sections_payload, spans_payload, proposition_artifact, alignments_payload)):
        return None
    if proposition_artifact.get("schema_version") != PROPOSITION_EXTRACTION_SCHEMA_VERSION:
        return None
    return {
        "schema_version": PREPARATION_STORE_SCHEMA_VERSION,
        "document_descriptor": descriptor,
        "document_sections": list(sections_payload.get("sections") or []),
        "source_spans": list(spans_payload.get("source_spans") or []),
        "document_proposition_artifact": proposition_artifact,
        "contract_alignment_artifacts": {
            str(key): dict(value)
            for key, value in dict(
                alignments_payload.get("contract_alignment_artifacts") or {}
            ).items()
            if isinstance(value, Mapping)
            and value.get("schema_version") == CONTRACT_TASK_ALIGNMENT_INDEX_SCHEMA_VERSION
        },
        "artifact_refs": dict(manifest.get("artifact_refs") or {}),
    }


def _atomic_batch_directory(
    project_id: str,
    paper_id: str,
    document_version_id: str,
) -> Path:
    return _artifact_directory(project_id, paper_id, document_version_id) / "atomic_batches"


def _load_atomic_proposition_batches(
    *,
    project_id: str,
    paper_id: str,
    document: Mapping[str, Any],
) -> list[dict[str, Any]]:
    document_version_id = str(document.get("document_version_id") or "")
    document_version_hash = str(document.get("document_version_hash") or "")
    if not document_version_id or not document_version_hash:
        return []
    directory = _atomic_batch_directory(project_id, paper_id, document_version_id)
    try:
        paths = sorted(directory.glob("*.json"))
    except OSError:
        return []
    batches: list[dict[str, Any]] = []
    for path in paths:
        payload = _read_json(path)
        if not isinstance(payload, Mapping):
            continue
        if any((
            payload.get("schema_version") != "atomic_proposition_batch_v1",
            str(payload.get("document_version_id") or "") != document_version_id,
            str(payload.get("document_version_hash") or "") != document_version_hash,
            not str(payload.get("batch_id") or ""),
        )):
            continue
        batches.append(dict(payload))
    return batches


def _persist_atomic_proposition_batch(
    *,
    project_id: str,
    paper_id: str,
    document_version_id: str,
    batch_artifact: Mapping[str, Any],
) -> str:
    if any((
        batch_artifact.get("schema_version") != "atomic_proposition_batch_v1",
        str(batch_artifact.get("document_version_id") or "") != document_version_id,
        not str(batch_artifact.get("batch_id") or ""),
    )):
        raise ValueError("Invalid atomic proposition batch checkpoint")
    path = _atomic_batch_directory(
        project_id, paper_id, document_version_id
    ) / f"{_safe_component(batch_artifact.get('batch_id'), 'batch')}.json"
    _write_json(path, batch_artifact)
    return str(path)


def _compact_storage_key(value: Any, *, prefix: str) -> str:
    normalized = _safe_component(value, prefix)
    suffix = normalized.rsplit("_", 1)[-1]
    if re.fullmatch(r"[0-9a-fA-F]{12,}", suffix):
        return prefix + suffix[-16:].lower()
    return prefix + hashlib.blake2b(
        normalized.encode("utf-8"), digest_size=8
    ).hexdigest()


def _compact_alignment_batch_name(
    alignment_artifact_id: Any,
    batch_id: Any,
) -> str:
    normalized_batch_id = _safe_component(batch_id, "batch")
    match = re.fullmatch(
        r"alignment_(\d+)(?:_repair_(\d+))?",
        normalized_batch_id,
    )
    if match:
        batch_key = "b" + match.group(1)
        if match.group(2):
            batch_key += "r" + match.group(2)
    else:
        batch_key = _compact_storage_key(normalized_batch_id, prefix="b")
    return f"{_compact_storage_key(alignment_artifact_id, prefix='a')}_{batch_key}.json"


def _alignment_batch_directory(directory: Path) -> Path:
    return directory / "ab"


def _alignment_batch_path(
    directory: Path,
    alignment_artifact_id: Any,
    batch_id: Any,
) -> Path:
    return _alignment_batch_directory(directory) / _compact_alignment_batch_name(
        alignment_artifact_id,
        batch_id,
    )


def _temporary_path_for(path: Path, *, nonce: str = "ffffffff") -> Path:
    return path.with_name(f".{path.stem}.{nonce}{path.suffix}.tmp")


def _load_alignment_batch_artifacts(
    *,
    project_id: str,
    paper_id: str,
    document: Mapping[str, Any],
) -> list[dict[str, Any]]:
    document_version_id = str(document.get("document_version_id") or "")
    if not document_version_id:
        return []
    directory = _alignment_batch_directory(
        _artifact_directory(project_id, paper_id, document_version_id)
    )
    try:
        paths = sorted(directory.glob("*.json"))
    except OSError:
        return []
    batches: list[dict[str, Any]] = []
    for path in paths:
        payload = _read_json(path)
        if not isinstance(payload, Mapping):
            continue
        if any((
            payload.get("schema_version") != ALIGNMENT_BATCH_ARTIFACT_SCHEMA_VERSION,
            not str(payload.get("alignment_artifact_id") or ""),
            not str(payload.get("batch_id") or ""),
        )):
            continue
        batches.append(dict(payload))
    return batches


def _persist_alignment_batch_artifact_at_directory(
    *,
    directory: Path,
    batch_artifact: Mapping[str, Any],
) -> str:
    alignment_artifact_id = str(batch_artifact.get("alignment_artifact_id") or "")
    batch_id = str(batch_artifact.get("batch_id") or "")
    if any((
        batch_artifact.get("schema_version") != ALIGNMENT_BATCH_ARTIFACT_SCHEMA_VERSION,
        not alignment_artifact_id,
        not batch_id,
    )):
        raise ValueError("Invalid contract alignment batch checkpoint")
    path = _alignment_batch_path(directory, alignment_artifact_id, batch_id)
    existing_batch = _read_json(path)
    if existing_batch and any((
        str(existing_batch.get("alignment_artifact_id") or "")
        != alignment_artifact_id,
        str(existing_batch.get("batch_id") or "") != batch_id,
    )):
        raise ValueError("PREPARED_ARTIFACT_STORAGE_KEY_COLLISION")
    _write_json(path, batch_artifact)
    return str(path)


def _persist_alignment_batch_artifact(
    *,
    project_id: str,
    paper_id: str,
    document_version_id: str,
    batch_artifact: Mapping[str, Any],
) -> str:
    return _persist_alignment_batch_artifact_at_directory(
        directory=_artifact_directory(project_id, paper_id, document_version_id),
        batch_artifact=batch_artifact,
    )


def validate_prepared_evidence_path_budget(
    *,
    project_id: str,
    paper_id: str,
    document_version_id: str,
) -> dict[str, Any]:
    directory = _artifact_directory(project_id, paper_id, document_version_id)
    targets = {
        "atomic_batch": _atomic_batch_directory(
            project_id, paper_id, document_version_id
        ) / "batch_9999.json",
        "alignment_batch": _alignment_batch_path(
            directory,
            "alignment_ffffffffffffffffffffffff",
            "alignment_9999_repair_9",
        ),
        "manifest": directory / "manifest.json",
    }
    temporary_targets = {
        name: _temporary_path_for(path)
        for name, path in targets.items()
    }
    path_lengths = {
        **{name: len(str(path)) for name, path in targets.items()},
        **{
            f"{name}_temporary": len(str(path))
            for name, path in temporary_targets.items()
        },
    }
    maximum_path_chars = max(path_lengths.values(), default=0)
    if maximum_path_chars > PREPARED_ARTIFACT_SAFE_PATH_LIMIT:
        raise ValueError(
            "PREPARED_ARTIFACT_PATH_BUDGET_EXCEEDED: "
            f"max_path_chars={maximum_path_chars}, "
            f"safe_limit={PREPARED_ARTIFACT_SAFE_PATH_LIMIT}, "
            f"directory={directory}"
        )
    return {
        "layout": "compact_alignment_batch_v1",
        "directory": str(directory),
        "maximum_path_chars": maximum_path_chars,
        "safe_path_limit": PREPARED_ARTIFACT_SAFE_PATH_LIMIT,
        "path_lengths": path_lengths,
    }


def _materialize_alignment_batch_artifacts(
    directory: Path,
    task_alignment: Mapping[str, Any],
) -> dict[str, Any]:
    materialized = dict(task_alignment)
    raw_batches = list(materialized.pop("batch_artifacts", []) or [])
    batch_refs: list[dict[str, Any]] = []
    alignment_artifact_id = str(materialized.get("artifact_id") or "")
    for raw_batch in raw_batches:
        if not isinstance(raw_batch, Mapping):
            continue
        batch = dict(raw_batch)
        if any((
            batch.get("schema_version") != ALIGNMENT_BATCH_ARTIFACT_SCHEMA_VERSION,
            str(batch.get("alignment_artifact_id") or "") != alignment_artifact_id,
            not str(batch.get("batch_id") or ""),
        )):
            raise ValueError("Invalid contract alignment batch artifact")
        path = Path(_persist_alignment_batch_artifact_at_directory(
            directory=directory,
            batch_artifact=batch,
        ))
        batch_refs.append({
            "batch_id": str(batch.get("batch_id") or ""),
            "status": str(batch.get("status") or ""),
            "path": str(path),
        })
    if batch_refs:
        materialized["batch_artifact_refs"] = batch_refs
    return materialized


def _merge_contract_alignment_artifacts(
    existing: Mapping[str, Any],
    incoming: Mapping[str, Any],
    *,
    directory: Path,
) -> dict[str, Any]:
    merged = {
        str(key): dict(value)
        for key, value in existing.items()
        if isinstance(value, Mapping)
        and value.get("schema_version") == CONTRACT_TASK_ALIGNMENT_INDEX_SCHEMA_VERSION
    }
    for key, value in incoming.items():
        if not isinstance(value, Mapping):
            continue
        if value.get("schema_version") != CONTRACT_TASK_ALIGNMENT_INDEX_SCHEMA_VERSION:
            raise ValueError(
                f"Only {CONTRACT_TASK_ALIGNMENT_INDEX_SCHEMA_VERSION} can be persisted"
            )
        contract_id = str(key)
        alignment = dict(value)
        previous = (
            dict(merged.get(contract_id) or {})
            if isinstance(merged.get(contract_id), Mapping)
            else {}
        )
        task_alignments = {
            str(task_key): dict(task_alignment)
            for task_key, task_alignment in dict(
                previous.get("task_alignments") or {}
            ).items()
            if isinstance(task_alignment, Mapping)
        }
        task_alignments.update({
            str(task_id): _materialize_alignment_batch_artifacts(
                directory,
                task_alignment,
            )
            for task_id, task_alignment in dict(alignment.get("task_alignments") or {}).items()
            if isinstance(task_alignment, Mapping)
        })
        merged[contract_id] = {
            "schema_version": CONTRACT_TASK_ALIGNMENT_INDEX_SCHEMA_VERSION,
            "research_question_contract_id": contract_id,
            "task_alignments": task_alignments,
            "whole_contract_alignment": {"status": "NOT_RUN"},
        }
    return merged


def _persist_document_proposition_artifact(
    *,
    project_id: str,
    paper_id: str,
    artifact: Mapping[str, Any],
    document_descriptor: Mapping[str, Any],
    document_sections: list[dict[str, Any]],
    source_spans: list[dict[str, Any]],
    contract_alignment_artifacts: Mapping[str, Any] | None = None,
    document_ingestion: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    document_version_id = str(
        document_descriptor.get("document_version_id")
        or artifact.get("document_version_id")
        or ""
    )
    if not document_version_id:
        raise ValueError("Prepared proposition artifact requires document_version_id")
    if artifact.get("schema_version") != PROPOSITION_EXTRACTION_SCHEMA_VERSION:
        raise ValueError(
            f"Only {PROPOSITION_EXTRACTION_SCHEMA_VERSION} can be persisted"
        )
    directory = _artifact_directory(project_id, paper_id, document_version_id)
    existing_alignments_payload = _read_json(directory / "alignments.json") or {}
    merged_alignments = _merge_contract_alignment_artifacts(
        dict(existing_alignments_payload.get("contract_alignment_artifacts") or {}),
        dict(contract_alignment_artifacts or {}),
        directory=directory,
    )
    refs = {
        "descriptor_ref": str(directory / "descriptor.json"),
        "sections_ref": str(directory / "sections.json"),
        "source_spans_ref": str(directory / "source_spans.json"),
        "proposition_artifact_ref": str(directory / "propositions.json"),
        "contract_alignment_artifacts_ref": str(directory / "alignments.json"),
    }
    if any(
        isinstance(task_alignment, Mapping)
        and list(task_alignment.get("batch_artifact_refs") or [])
        for index in merged_alignments.values()
        if isinstance(index, Mapping)
        for task_alignment in dict(index.get("task_alignments") or {}).values()
    ):
        refs["alignment_batches_dir"] = str(_alignment_batch_directory(directory))
    ingestion = dict(document_ingestion or {})
    canonical_text = str(ingestion.get("canonical_text") or "")
    if canonical_text:
        refs["canonical_text_ref"] = str(directory / "canonical_text.txt")
        _write_text(directory / "canonical_text.txt", canonical_text)
    layout_payload = {
        "schema_version": "prepared_pdf_layout_v2",
        "document_version_id": document_version_id,
        "pages": list(ingestion.get("raw_layout_pages") or []),
        "fragment_registry": list(ingestion.get("fragment_registry") or []),
        "reading_order_quality": dict(ingestion.get("reading_order_quality") or {}),
    }
    if layout_payload["pages"] or layout_payload["fragment_registry"]:
        refs["layout_ref"] = str(directory / "layout.json")
        _write_json(directory / "layout.json", layout_payload)
    if ingestion.get("paragraphs"):
        refs["paragraphs_ref"] = str(directory / "paragraphs.json")
        _write_json(directory / "paragraphs.json", {
            "schema_version": "prepared_pdf_paragraphs_v2",
            "document_version_id": document_version_id,
            "paragraphs": list(ingestion.get("paragraphs") or []),
        })
    if ingestion.get("llm_chunks"):
        refs["llm_chunks_ref"] = str(directory / "llm_chunks.json")
        _write_json(directory / "llm_chunks.json", {
            "schema_version": "prepared_llm_chunks_v2",
            "document_version_id": document_version_id,
            "llm_chunks": list(ingestion.get("llm_chunks") or []),
        })
    persisted_descriptor = dict(document_descriptor)
    if not persisted_descriptor.get("source_artifact_ref"):
        source_path = str(ingestion.get("source_path") or "")
        source_url = str(
            ingestion.get("source_url")
            or persisted_descriptor.get("source_url")
            or ""
        )
        if source_path:
            persisted_descriptor["source_artifact_ref"] = {
                "artifact_type": "source_document",
                "path": source_path,
            }
        elif source_url:
            persisted_descriptor["source_artifact_ref"] = {
                "artifact_type": "source_document",
                "url": source_url,
            }
    if refs.get("canonical_text_ref") and not persisted_descriptor.get(
        "canonical_text_ref"
    ):
        persisted_descriptor["canonical_text_ref"] = {
            "artifact_type": "canonical_text",
            "path": refs["canonical_text_ref"],
        }
    if not persisted_descriptor.get("source_locator_ref"):
        persisted_descriptor["source_locator_ref"] = {
            "artifact_type": "source_spans",
            "path": refs["source_spans_ref"],
        }
    _write_json(directory / "descriptor.json", persisted_descriptor)
    _write_json(directory / "sections.json", {
        "schema_version": "prepared_document_sections_v2",
        "document_version_id": document_version_id,
        "sections": list(document_sections),
    })
    _write_json(directory / "source_spans.json", {
        "schema_version": "prepared_source_spans_v2",
        "document_version_id": document_version_id,
        "source_spans": list(source_spans),
    })
    _write_json(directory / "propositions.json", artifact)
    _write_json(directory / "alignments.json", {
        "schema_version": "prepared_contract_alignments_v2",
        "document_version_id": document_version_id,
        "contract_alignment_artifacts": merged_alignments,
    })
    manifest = {
        "schema_version": PREPARATION_STORE_SCHEMA_VERSION,
        "project_id": str(project_id or ""),
        "paper_id": str(paper_id or ""),
        "document_version_id": document_version_id,
        "artifact_status": str(artifact.get("status") or ""),
        "document_descriptor": persisted_descriptor,
        "artifact_refs": refs,
        "section_count": len(document_sections),
        "source_span_count": len(source_spans),
        "proposition_count": len(artifact.get("propositions") or []),
        "alignment_count": len(merged_alignments),
    }
    _write_json(directory / "manifest.json", manifest)
    return manifest


def load_document_proposition_artifact(
    *,
    project_id: str,
    paper_id: str,
    document: Mapping[str, Any],
) -> dict[str, Any] | None:
    with _PREPARATION_STORE_LOCK:
        return _load_document_proposition_artifact(
            project_id=project_id,
            paper_id=paper_id,
            document=document,
        )


def load_atomic_proposition_batches(
    *,
    project_id: str,
    paper_id: str,
    document: Mapping[str, Any],
) -> list[dict[str, Any]]:
    with _PREPARATION_STORE_LOCK:
        return _load_atomic_proposition_batches(
            project_id=project_id,
            paper_id=paper_id,
            document=document,
        )


def load_alignment_batch_artifacts(
    *,
    project_id: str,
    paper_id: str,
    document: Mapping[str, Any],
) -> list[dict[str, Any]]:
    with _PREPARATION_STORE_LOCK:
        return _load_alignment_batch_artifacts(
            project_id=project_id,
            paper_id=paper_id,
            document=document,
        )


def persist_atomic_proposition_batch(
    *,
    project_id: str,
    paper_id: str,
    document_version_id: str,
    batch_artifact: Mapping[str, Any],
) -> str:
    with _PREPARATION_STORE_LOCK:
        return _persist_atomic_proposition_batch(
            project_id=project_id,
            paper_id=paper_id,
            document_version_id=document_version_id,
            batch_artifact=batch_artifact,
        )


def persist_alignment_batch_artifact(
    *,
    project_id: str,
    paper_id: str,
    document_version_id: str,
    batch_artifact: Mapping[str, Any],
) -> str:
    with _PREPARATION_STORE_LOCK:
        return _persist_alignment_batch_artifact(
            project_id=project_id,
            paper_id=paper_id,
            document_version_id=document_version_id,
            batch_artifact=batch_artifact,
        )


def persist_document_proposition_artifact(
    *,
    project_id: str,
    paper_id: str,
    artifact: Mapping[str, Any],
    document_descriptor: Mapping[str, Any],
    document_sections: list[dict[str, Any]],
    source_spans: list[dict[str, Any]],
    contract_alignment_artifacts: Mapping[str, Any] | None = None,
    document_ingestion: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    with _PREPARATION_STORE_LOCK:
        return _persist_document_proposition_artifact(
            project_id=project_id,
            paper_id=paper_id,
            artifact=artifact,
            document_descriptor=document_descriptor,
            document_sections=document_sections,
            source_spans=source_spans,
            contract_alignment_artifacts=contract_alignment_artifacts,
            document_ingestion=document_ingestion,
        )


__all__ = [
    "PREPARATION_STORE_SCHEMA_VERSION",
    "PREPARED_ARTIFACT_SAFE_PATH_LIMIT",
    "load_alignment_batch_artifacts",
    "load_atomic_proposition_batches",
    "load_document_proposition_artifact",
    "persist_alignment_batch_artifact",
    "persist_atomic_proposition_batch",
    "persist_document_proposition_artifact",
    "validate_prepared_evidence_path_budget",
]
