from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterable, Mapping

from .contract import (
    MULTIMODAL_INPUT_MANIFEST_SCHEMA_VERSION,
    MultimodalInputError,
    MultimodalInputSpec,
    MultimodalSettings,
    ValidatedMultimodalRecord,
    normalize_metadata,
    normalize_modality,
    normalize_record_id,
)


_WINDOWS_DRIVE_PATH = re.compile(r"^[A-Za-z]:")
_MODALITY_SUFFIXES: dict[str, frozenset[str]] = {
    "image": frozenset({".bmp", ".gif", ".jpeg", ".jpg", ".png", ".tif", ".tiff", ".webp"}),
    "table": frozenset({".csv", ".parquet", ".tsv", ".xls", ".xlsx"}),
    "signal": frozenset({".csv", ".npy", ".npz", ".tsv"}),
    "audio": frozenset({".wav"}),
    "video": frozenset({".avi", ".mkv", ".mov", ".mp4", ".webm"}),
    "threeD": frozenset({".npy", ".ply", ".pts", ".xyz"}),
    "trajectory": frozenset({".csv", ".json", ".tsv"}),
    "text": frozenset({".log", ".md", ".rst", ".txt"}),
    "symbolic": frozenset({".latex", ".mathml", ".sympy", ".tex", ".xml"}),
    "molecule": frozenset({".mol", ".mol2", ".sdf", ".smi", ".smiles"}),
}

_DIRECT_FILE_MODALITIES = {
    suffix: modality
    for modality, suffixes in _MODALITY_SUFFIXES.items()
    if modality in {"image", "table", "audio", "video", "text", "symbolic", "molecule"}
    for suffix in suffixes
}


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _safe_name(path: Path) -> str:
    return path.name or "input file"


def _resolve_regular_file(path: Path, *, record_id: str) -> Path:
    try:
        resolved = path.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise MultimodalInputError(f"Record '{record_id}' references a file that does not exist.") from exc
    if not resolved.is_file():
        raise MultimodalInputError(f"Record '{record_id}' must reference a regular file.")
    return resolved


def _validate_file_size(
    path: Path,
    *,
    record_id: str,
    settings: MultimodalSettings,
    total_bytes: int,
) -> int:
    try:
        file_size_bytes = path.stat().st_size
    except OSError as exc:
        raise MultimodalInputError(f"Record '{record_id}' could not be inspected.") from exc
    if file_size_bytes > settings.max_input_file_bytes:
        raise MultimodalInputError(
            f"Record '{record_id}' exceeds the per-file multimodal input limit."
        )
    if total_bytes + file_size_bytes > settings.max_total_input_bytes:
        raise MultimodalInputError("Multimodal inputs exceed the total input size limit.")
    return file_size_bytes


def _validate_suffix(path: Path, *, record_id: str, modality: str) -> None:
    suffix = path.suffix.lower()
    if suffix not in _MODALITY_SUFFIXES[modality]:
        raise MultimodalInputError(
            f"Record '{record_id}' has an extension incompatible with modality '{modality}'."
        )


def _build_record(
    *,
    record_id: str,
    modality: str,
    source_path: Path,
    metadata: Mapping[str, Any],
    input_index: int,
    settings: MultimodalSettings,
    total_bytes: int,
) -> tuple[ValidatedMultimodalRecord, int]:
    resolved = _resolve_regular_file(source_path, record_id=record_id)
    _validate_suffix(resolved, record_id=record_id, modality=modality)
    file_size_bytes = _validate_file_size(
        resolved,
        record_id=record_id,
        settings=settings,
        total_bytes=total_bytes,
    )
    record = ValidatedMultimodalRecord(
        record_id=record_id,
        modality=modality,
        source_path=resolved,
        source_name=_safe_name(resolved),
        file_size_bytes=file_size_bytes,
        metadata=normalize_metadata(metadata),
        input_index=input_index,
    )
    return record, total_bytes + file_size_bytes


def infer_direct_file_modality(path: Path) -> str:
    modality = _DIRECT_FILE_MODALITIES.get(path.suffix.lower())
    if modality:
        return modality
    if path.suffix.lower() in {".npy", ".npz", ".csv", ".tsv", ".json", ".xyz", ".ply", ".pts"}:
        raise MultimodalInputError(
            f"'{_safe_name(path)}' is ambiguous. Use --multimodal-evidence-manifest to declare its modality."
        )
    raise MultimodalInputError(
        f"'{_safe_name(path)}' has no supported multimodal file extension."
    )


def build_input_spec_from_files(
    files: Iterable[str | Path],
    *,
    settings: MultimodalSettings | None = None,
    dataset_id: str = "cli-multimodal-input",
) -> MultimodalInputSpec:
    active_settings = settings or MultimodalSettings()
    records: list[ValidatedMultimodalRecord] = []
    seen_paths: set[Path] = set()
    total_bytes = 0
    for input_index, raw_path in enumerate(files):
        path = Path(raw_path).expanduser()
        record_id = f"file-{input_index + 1:03d}"
        resolved = _resolve_regular_file(path, record_id=record_id)
        if resolved in seen_paths:
            raise MultimodalInputError("The same multimodal file was supplied more than once.")
        seen_paths.add(resolved)
        modality = infer_direct_file_modality(resolved)
        record, total_bytes = _build_record(
            record_id=record_id,
            modality=modality,
            source_path=resolved,
            metadata={},
            input_index=input_index,
            settings=active_settings,
            total_bytes=total_bytes,
        )
        records.append(record)
    if not records:
        raise MultimodalInputError("At least one multimodal file is required.")
    return MultimodalInputSpec(
        dataset_id=str(dataset_id).strip() or "cli-multimodal-input",
        records=tuple(records),
        input_mode="explicit_files",
    )


def _manifest_member_path(raw_path: str, manifest_root: Path, *, record_id: str) -> Path:
    normalized = raw_path.replace("\\", "/").strip()
    member = Path(normalized)
    if (
        not normalized
        or normalized.startswith("/")
        or normalized.startswith("\\")
        or _WINDOWS_DRIVE_PATH.match(normalized)
        or member.is_absolute()
        or ".." in member.parts
    ):
        raise MultimodalInputError(
            f"Record '{record_id}' must use a relative manifest file path within the manifest directory."
        )
    candidate = manifest_root / member
    resolved = _resolve_regular_file(candidate, record_id=record_id)
    if not _is_relative_to(resolved, manifest_root):
        raise MultimodalInputError(
            f"Record '{record_id}' resolves outside the manifest directory."
        )
    return resolved


def load_input_manifest(
    path: str | Path,
    *,
    settings: MultimodalSettings | None = None,
) -> MultimodalInputSpec:
    active_settings = settings or MultimodalSettings()
    manifest_path = Path(path).expanduser()
    try:
        resolved_manifest_path = manifest_path.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise MultimodalInputError("Multimodal evidence manifest does not exist.") from exc
    if not resolved_manifest_path.is_file():
        raise MultimodalInputError("Multimodal evidence manifest must be a regular file.")
    try:
        payload = json.loads(resolved_manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MultimodalInputError("Multimodal evidence manifest must be valid UTF-8 JSON.") from exc
    if not isinstance(payload, dict):
        raise MultimodalInputError("Multimodal evidence manifest must be a JSON object.")
    if payload.get("schema_version") != MULTIMODAL_INPUT_MANIFEST_SCHEMA_VERSION:
        raise MultimodalInputError("Unsupported multimodal evidence manifest schema_version.")
    raw_records = payload.get("records")
    if not isinstance(raw_records, list) or not raw_records:
        raise MultimodalInputError("Multimodal evidence manifest must contain a non-empty records list.")

    manifest_root = resolved_manifest_path.parent.resolve()
    dataset_id = str(payload.get("dataset_id") or resolved_manifest_path.stem).strip()
    if not dataset_id:
        raise MultimodalInputError("Multimodal evidence manifest dataset_id cannot be empty.")

    records: list[ValidatedMultimodalRecord] = []
    seen_ids: set[str] = set()
    total_bytes = 0
    for input_index, raw_record in enumerate(raw_records):
        if not isinstance(raw_record, dict):
            raise MultimodalInputError("Each multimodal manifest record must be a JSON object.")
        record_id = normalize_record_id(raw_record.get("record_id"))
        if record_id in seen_ids:
            raise MultimodalInputError(f"Duplicate multimodal record_id '{record_id}'.")
        seen_ids.add(record_id)
        modality = normalize_modality(raw_record.get("modality"))
        raw_file = raw_record.get("file")
        if not isinstance(raw_file, str):
            raise MultimodalInputError(f"Record '{record_id}' must include a string file path.")
        source_path = _manifest_member_path(raw_file, manifest_root, record_id=record_id)
        record, total_bytes = _build_record(
            record_id=record_id,
            modality=modality,
            source_path=source_path,
            metadata=raw_record,
            input_index=input_index,
            settings=active_settings,
            total_bytes=total_bytes,
        )
        records.append(record)
    return MultimodalInputSpec(
        dataset_id=dataset_id[:256],
        records=tuple(records),
        input_mode="manifest",
    )
