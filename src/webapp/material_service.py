"""Controlled storage and publication of browser-uploaded research materials."""

from __future__ import annotations

import json
import os
import re
import uuid
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from fastapi import UploadFile

from src.pipeline.multimodal_evidence.contract import SUPPORTED_MODALITIES
from src.pipeline.science_run import (
    ScienceRunInputError,
    ScienceRunPaths,
    atomic_write_json,
    file_sha256,
    load_science_run,
    locked_science_run,
    append_science_event,
)

from .schemas import MaterialMetadata


_CHUNK_BYTES = 1_048_576
_MAX_FILE_BYTES = 52_428_800
_MAX_TOTAL_BYTES = 268_435_456
_SAFE_SUFFIXES = frozenset(
    {
        ".avi", ".bmp", ".c", ".cpp", ".csv", ".docx", ".gif", ".h", ".ipynb",
        ".jpeg", ".jpg", ".json", ".jl", ".latex", ".m", ".markdown", ".md", ".mkv",
        ".mol", ".mol2", ".mov", ".mp3", ".mp4", ".npy", ".npz", ".pdf", ".ply", ".png",
        ".pts", ".py", ".r", ".sdf", ".smi", ".smiles", ".tex", ".tif", ".tiff", ".tsv",
        ".txt", ".wav", ".webm", ".webp", ".xls", ".xlsx", ".xml", ".xyz", ".yaml", ".yml", ".zip",
    }
)
_IMAGE_SUFFIXES = frozenset({".bmp", ".gif", ".jpeg", ".jpg", ".png", ".tif", ".tiff", ".webp"})
_TABLE_SUFFIXES = frozenset({".csv", ".tsv", ".xls", ".xlsx"})
_STAGE_MUTABLE_STATUSES = frozenset({"PENDING", "FAILED"})
_MATERIAL_ID_PATTERN = re.compile(r"mat-[a-f0-9]{32}")


class MaterialUploadError(ValueError):
    """Raised when a browser material cannot be stored safely."""


def _safe_filename(value: str | None) -> tuple[str, str]:
    name = Path(value or "upload").name
    name = re.sub(r"[^A-Za-z0-9._ -]", "_", name).strip(". ") or "upload"
    suffix = Path(name).suffix.lower()
    if suffix not in _SAFE_SUFFIXES:
        raise MaterialUploadError(f"Unsupported upload type: {suffix or 'no extension'}")
    return name[:180], suffix


def _inferred_modality(suffix: str) -> str | None:
    if suffix in _IMAGE_SUFFIXES:
        return "image"
    if suffix in _TABLE_SUFFIXES:
        return "table"
    return None


def _safe_metadata(metadata: MaterialMetadata, *, stored_name: str, original_name: str, size: int) -> dict[str, Any]:
    modality = metadata.modality or _inferred_modality(Path(stored_name).suffix.lower())
    return {
        "material_id": f"mat-{uuid.uuid4().hex}",
        "original_name": original_name,
        "stored_name": stored_name,
        "file_size_bytes": size,
        "sha256": "",
        "scope": metadata.scope,
        "modality": modality,
        "contains_sensitive_data": metadata.contains_sensitive_data,
        "metadata": {
            key: value
            for key, value in {
                "label": metadata.label.strip(),
                "group": metadata.group.strip(),
                "condition": metadata.condition.strip(),
                "timepoint": metadata.timepoint.strip(),
            }.items()
            if value
        },
    }


def _assert_materials_mutable(state: Mapping[str, Any]) -> None:
    stages = state.get("stages")
    if not isinstance(stages, Mapping):
        raise MaterialUploadError("Science run has no stage state.")
    if any(
        isinstance(stage, Mapping) and str(stage.get("status") or "PENDING") not in _STAGE_MUTABLE_STATUSES
        for stage in stages.values()
    ):
        raise MaterialUploadError("Materials are immutable after research execution begins.")


def _materials_payload(records: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    return {"schema_version": "web_materials_manifest_v1", "materials": [dict(record) for record in records]}


def _multimodal_payload(*, run_id: str, records: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    for record in records:
        modality = record.get("modality")
        if (
            modality not in SUPPORTED_MODALITIES
            or record.get("scope") != "survey_evidence"
            or bool(record.get("contains_sensitive_data"))
        ):
            continue
        metadata = record.get("metadata") if isinstance(record.get("metadata"), Mapping) else {}
        entries.append(
            {
                "record_id": str(record["material_id"]),
                "modality": str(modality),
                "file": f"files/{record['stored_name']}",
                **{
                    key: str(value)
                    for key, value in metadata.items()
                    if key in {"label", "group", "condition", "timepoint"} and str(value).strip()
                },
            }
        )
    return {
        "schema_version": "multimodal_input_manifest_v1",
        "dataset_id": run_id,
        "records": entries,
    }


def _stored_material_path(paths: ScienceRunPaths, record: Mapping[str, Any]) -> Path:
    stored_name = str(record.get("stored_name") or "")
    if not stored_name or Path(stored_name).name != stored_name:
        raise MaterialUploadError("The stored material record is invalid.")
    files_dir = (paths.inputs / "files").resolve()
    path = (files_dir / stored_name).resolve()
    try:
        path.relative_to(files_dir)
    except ValueError as exc:
        raise MaterialUploadError("The stored material record is outside this research run.") from exc
    if not path.is_file() or file_sha256(path) != str(record.get("sha256") or ""):
        raise MaterialUploadError("The stored material is missing or no longer matches its registered hash.")
    return path


def _load_material_records(paths: ScienceRunPaths) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    run_metadata, state = load_science_run(paths)
    immutable_inputs = run_metadata.get("immutable_inputs")
    if not isinstance(immutable_inputs, dict):
        raise MaterialUploadError("Science run has invalid immutable inputs.")
    materials = immutable_inputs.get("materials")
    if not isinstance(materials, dict):
        raise MaterialUploadError("Science run has invalid material settings.")
    raw_records = materials.get("records")
    if not isinstance(raw_records, list):
        raise MaterialUploadError("Science run has invalid material records.")
    records = [dict(record) for record in raw_records if isinstance(record, Mapping)]
    if len(records) != len(raw_records):
        raise MaterialUploadError("Science run has invalid material records.")
    return run_metadata, state, materials, records


def read_material(paths: ScienceRunPaths, material_id: str) -> tuple[Path, str]:
    """Return only a hash-verified material registered in this exact run."""

    if not _MATERIAL_ID_PATTERN.fullmatch(material_id):
        raise MaterialUploadError("Unknown research material.")
    with locked_science_run(paths):
        _metadata, _state, _materials, records = _load_material_records(paths)
        record = next((item for item in records if item.get("material_id") == material_id), None)
        if record is None:
            raise MaterialUploadError("Unknown research material.")
        path = _stored_material_path(paths, record)
        return path, str(record.get("original_name") or path.name)


def remove_material(paths: ScienceRunPaths, material_id: str) -> None:
    """Remove a pre-execution material without allowing a manifest rewrite later."""

    if not _MATERIAL_ID_PATTERN.fullmatch(material_id):
        raise MaterialUploadError("Unknown research material.")
    with locked_science_run(paths):
        run_metadata, state, materials, records = _load_material_records(paths)
        _assert_materials_mutable(state)
        match_index = next((index for index, item in enumerate(records) if item.get("material_id") == material_id), None)
        if match_index is None:
            raise MaterialUploadError("Unknown research material.")
        removed = records.pop(match_index)
        source = _stored_material_path(paths, removed)
        temporary = source.with_name(f".{source.name}.removing")
        if temporary.exists():
            raise MaterialUploadError("This research material is currently being updated. Retry shortly.")
        os.replace(source, temporary)
        try:
            materials["records"] = records
            materials_manifest = _materials_payload(records)
            multimodal_manifest = _multimodal_payload(run_id=str(run_metadata["science_run_id"]), records=records)
            atomic_write_json(paths.materials_manifest, materials_manifest)
            atomic_write_json(paths.multimodal_input_manifest, multimodal_manifest)
            materials["manifest_sha256"] = file_sha256(paths.materials_manifest)
            materials["multimodal_manifest_sha256"] = file_sha256(paths.multimodal_input_manifest)
            atomic_write_json(paths.run_metadata, run_metadata)
            append_science_event(paths, event_type="MATERIAL_REMOVED", material_id=material_id, material_count=len(records))
        except Exception:
            os.replace(temporary, source)
            raise
        temporary.unlink(missing_ok=True)


async def store_materials(
    *,
    paths: ScienceRunPaths,
    uploads: list[UploadFile],
    metadata: list[MaterialMetadata],
) -> list[dict[str, Any]]:
    """Stream browser uploads into one run's controlled input directory."""

    if not uploads:
        raise MaterialUploadError("At least one file is required.")
    if len(uploads) != len(metadata):
        raise MaterialUploadError("Each upload requires exactly one metadata entry.")

    with locked_science_run(paths):
        run_metadata, state = load_science_run(paths)
        _assert_materials_mutable(state)
        immutable_inputs = run_metadata.get("immutable_inputs")
        if not isinstance(immutable_inputs, Mapping):
            raise MaterialUploadError("Science run has invalid immutable inputs.")
        material_inputs = immutable_inputs.get("materials", {})
        if not isinstance(material_inputs, Mapping):
            raise MaterialUploadError("Science run has invalid material metadata.")
        existing_records = material_inputs.get("records", [])
        if not isinstance(existing_records, list):
            raise MaterialUploadError("Science run has invalid material records.")
        existing_total = sum(
            int(record.get("file_size_bytes") or 0)
            for record in existing_records
            if isinstance(record, Mapping)
        )

    inputs_dir = paths.inputs
    files_dir = inputs_dir / "files"
    files_dir.mkdir(parents=True, exist_ok=True)
    stored_records: list[dict[str, Any]] = []
    uploaded_total = 0
    temporary_paths: list[Path] = []
    final_paths: list[Path] = []
    try:
        for upload, item_metadata in zip(uploads, metadata, strict=True):
            original_name, suffix = _safe_filename(upload.filename)
            stored_name = f"{uuid.uuid4().hex}{suffix}"
            final_path = files_dir / stored_name
            temporary_path = files_dir / f".{stored_name}.uploading"
            temporary_paths.append(temporary_path)
            size = 0
            with temporary_path.open("xb") as handle:
                while chunk := await upload.read(_CHUNK_BYTES):
                    size += len(chunk)
                    uploaded_total += len(chunk)
                    if size > _MAX_FILE_BYTES:
                        raise MaterialUploadError(f"'{original_name}' exceeds the 50 MiB per-file limit.")
                    if existing_total + uploaded_total > _MAX_TOTAL_BYTES:
                        raise MaterialUploadError("Research materials exceed the 250 MiB per-run limit.")
                    handle.write(chunk)
            os.replace(temporary_path, final_path)
            final_paths.append(final_path)
            record = _safe_metadata(
                item_metadata,
                stored_name=stored_name,
                original_name=original_name,
                size=size,
            )
            record["sha256"] = file_sha256(final_path)
            stored_records.append(record)
    except Exception:
        for temporary_path in temporary_paths:
            temporary_path.unlink(missing_ok=True)
        for final_path in final_paths:
            final_path.unlink(missing_ok=True)
        raise
    finally:
        for upload in uploads:
            await upload.close()

    try:
        with locked_science_run(paths):
            run_metadata, state = load_science_run(paths)
            _assert_materials_mutable(state)
            immutable_inputs = run_metadata.get("immutable_inputs")
            if not isinstance(immutable_inputs, dict):
                raise MaterialUploadError("Science run has invalid immutable inputs.")
            materials = immutable_inputs.get("materials")
            if not isinstance(materials, dict):
                raise MaterialUploadError("Science run has invalid material settings.")
            records = materials.setdefault("records", [])
            if not isinstance(records, list):
                raise MaterialUploadError("Science run has invalid material records.")
            records.extend(stored_records)
            materials_manifest = _materials_payload(records)
            multimodal_manifest = _multimodal_payload(
                run_id=str(run_metadata["science_run_id"]),
                records=records,
            )
            atomic_write_json(paths.materials_manifest, materials_manifest)
            atomic_write_json(paths.multimodal_input_manifest, multimodal_manifest)
            materials["manifest_path"] = paths.materials_manifest.relative_to(paths.run_dir).as_posix()
            materials["manifest_sha256"] = file_sha256(paths.materials_manifest)
            materials["multimodal_manifest_path"] = paths.multimodal_input_manifest.relative_to(paths.run_dir).as_posix()
            materials["multimodal_manifest_sha256"] = file_sha256(paths.multimodal_input_manifest)
            atomic_write_json(paths.run_metadata, run_metadata)
            append_science_event(
                paths,
                event_type="MATERIALS_REGISTERED",
                material_ids=[record["material_id"] for record in stored_records],
                material_count=len(records),
            )
    except Exception:
        for final_path in final_paths:
            final_path.unlink(missing_ok=True)
        raise
    return stored_records


def parse_material_metadata(value: str) -> list[MaterialMetadata]:
    try:
        payload = json.loads(value)
    except json.JSONDecodeError as exc:
        raise MaterialUploadError("metadata must be a JSON array.") from exc
    if not isinstance(payload, list):
        raise MaterialUploadError("metadata must be a JSON array.")
    try:
        return [MaterialMetadata.model_validate(item) for item in payload]
    except (TypeError, ValueError) as exc:
        raise MaterialUploadError(f"Invalid material metadata: {exc}") from exc
