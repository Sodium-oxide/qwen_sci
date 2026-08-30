from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


MULTIMODAL_INPUT_MANIFEST_SCHEMA_VERSION = "multimodal_input_manifest_v1"
MULTIMODAL_LOCAL_INPUT_CONTEXT_SCHEMA_VERSION = "multimodal_local_input_context_v1"
MULTIMODAL_EVIDENCE_SCHEMA_VERSION = "multimodal_evidence_v1"

SUPPORTED_MODALITIES = frozenset(
    {
        "image",
        "table",
        "signal",
        "audio",
        "video",
        "threeD",
        "trajectory",
        "text",
        "symbolic",
        "molecule",
    }
)

_RECORD_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_METADATA_KEYS = ("label", "group", "condition", "timepoint")


class MultimodalInputError(ValueError):
    """Raised when a multimodal input cannot be safely processed locally."""


@dataclass(frozen=True)
class MultimodalSettings:
    max_records_per_modality: int = 24
    max_input_file_bytes: int = 52_428_800
    max_total_input_bytes: int = 268_435_456
    remote_perception_authorized: bool = False

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any] | None) -> "MultimodalSettings":
        data = value or {}
        try:
            max_records_per_modality = int(
                data.get("max_records_per_modality", cls.max_records_per_modality)
            )
            max_input_file_bytes = int(
                data.get("max_input_file_bytes", cls.max_input_file_bytes)
            )
            max_total_input_bytes = int(
                data.get("max_total_input_bytes", cls.max_total_input_bytes)
            )
        except (TypeError, ValueError) as exc:
            raise MultimodalInputError("Multimodal size limits must be integers.") from exc
        if max_records_per_modality < 1:
            raise MultimodalInputError("max_records_per_modality must be at least 1.")
        if max_input_file_bytes < 1 or max_total_input_bytes < 1:
            raise MultimodalInputError("Multimodal input size limits must be positive.")
        if max_input_file_bytes > max_total_input_bytes:
            raise MultimodalInputError(
                "max_input_file_bytes cannot exceed max_total_input_bytes."
            )
        return cls(
            max_records_per_modality=max_records_per_modality,
            max_input_file_bytes=max_input_file_bytes,
            max_total_input_bytes=max_total_input_bytes,
            remote_perception_authorized=bool(
                data.get("remote_perception_authorized", False)
            ),
        )


def normalize_record_id(value: Any) -> str:
    record_id = str(value or "").strip()
    if not _RECORD_ID_PATTERN.fullmatch(record_id):
        raise MultimodalInputError(
            "Each multimodal record_id must be 1-128 characters using letters, numbers, '.', '_', ':', or '-'."
        )
    return record_id


def normalize_modality(value: Any) -> str:
    modality = str(value or "").strip()
    if modality not in SUPPORTED_MODALITIES:
        supported = ", ".join(sorted(SUPPORTED_MODALITIES))
        raise MultimodalInputError(
            f"Unsupported multimodal modality '{modality}'. Supported modalities: {supported}."
        )
    return modality


def normalize_metadata(record: Mapping[str, Any]) -> dict[str, str]:
    metadata: dict[str, str] = {}
    for key in _METADATA_KEYS:
        raw_value = record.get(key)
        if raw_value is None:
            continue
        value = str(raw_value).strip()
        if value:
            metadata[key] = value[:256]
    return metadata


@dataclass(frozen=True)
class ValidatedMultimodalRecord:
    record_id: str
    modality: str
    source_path: Path
    source_name: str
    file_size_bytes: int
    metadata: Mapping[str, str]
    input_index: int

    def to_runtime_dict(self) -> dict[str, Any]:
        return {
            "record_id": self.record_id,
            "modality": self.modality,
            "source_path": str(self.source_path),
            "source_name": self.source_name,
            "file_size_bytes": self.file_size_bytes,
            "metadata": dict(self.metadata),
            "input_index": self.input_index,
        }

    def to_safe_context_dict(self) -> dict[str, Any]:
        return {
            "record_id": self.record_id,
            "modality": self.modality,
            "source_name": self.source_name,
            "file_size_bytes": self.file_size_bytes,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class MultimodalInputSpec:
    dataset_id: str
    records: tuple[ValidatedMultimodalRecord, ...]
    input_mode: str

    def to_runtime_dict(self) -> dict[str, Any]:
        return {
            "schema_version": MULTIMODAL_INPUT_MANIFEST_SCHEMA_VERSION,
            "dataset_id": self.dataset_id,
            "input_mode": self.input_mode,
            "records": [record.to_runtime_dict() for record in self.records],
        }

    def to_safe_runtime_dict(self) -> dict[str, Any]:
        """Return the child-process configuration payload without source paths."""

        return {
            "schema_version": MULTIMODAL_INPUT_MANIFEST_SCHEMA_VERSION,
            "dataset_id": self.dataset_id,
            "input_mode": self.input_mode,
            "records": [record.to_safe_context_dict() for record in self.records],
        }


def validate_local_context(context: Mapping[str, Any]) -> dict[str, Any]:
    if context.get("schema_version") != MULTIMODAL_LOCAL_INPUT_CONTEXT_SCHEMA_VERSION:
        raise MultimodalInputError("Invalid local multimodal context schema version.")
    if context.get("mode") != "local_only":
        raise MultimodalInputError("Batch A multimodal context must remain local_only.")
    if not isinstance(context.get("records"), list):
        raise MultimodalInputError("Local multimodal context must contain records.")
    if not isinstance(context.get("selected_record_ids"), list):
        raise MultimodalInputError("Local multimodal context must contain selected_record_ids.")
    try:
        serialized = json.dumps(context, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise MultimodalInputError(
            "Local multimodal context must be JSON-serializable without NaN values."
        ) from exc
    if _contains_key(context, "source_path"):
        raise MultimodalInputError(
            "Local multimodal context must not contain resolved source paths."
        )
    return dict(context)


def validate_multimodal_evidence(evidence: Mapping[str, Any]) -> dict[str, Any]:
    if evidence.get("schema_version") != MULTIMODAL_EVIDENCE_SCHEMA_VERSION:
        raise MultimodalInputError("Invalid multimodal evidence schema version.")
    perception = evidence.get("perception")
    if not isinstance(perception, Mapping):
        raise MultimodalInputError("Multimodal evidence must describe its perception mode.")
    mode = perception.get("mode")
    if mode not in {"local_only", "remote_perception"}:
        raise MultimodalInputError("Multimodal evidence contains an invalid perception mode.")
    for field in ("native_findings", "observations", "claims", "limitations"):
        if not isinstance(evidence.get(field), list):
            raise MultimodalInputError(f"Multimodal evidence must contain a {field} list.")
    if mode == "local_only" and (evidence["observations"] or evidence["claims"]):
        raise MultimodalInputError(
            "Local-only multimodal evidence cannot contain remote observations or claims."
        )
    if mode == "remote_perception" and (
        perception.get("provider") != "qwen"
        or perception.get("model") != "qwen3-vl-plus"
    ):
        raise MultimodalInputError(
            "Remote multimodal evidence must be produced by qwen/qwen3-vl-plus."
        )
    if _contains_prohibited_key(
        evidence,
        {
            "source_path",
            "image_bytes",
            "preview_path",
            "base64",
            "raw_response",
            "exif",
            "media_bytes",
            "absolute_path",
            "file_path",
            "source_file",
            "raw_media",
        },
    ) or _contains_absolute_path_value(evidence):
        raise MultimodalInputError(
            "Multimodal evidence must not contain source paths, previews, raw media, or provider responses."
        )
    try:
        json.dumps(evidence, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise MultimodalInputError(
            "Multimodal evidence must be JSON-serializable without NaN values."
        ) from exc
    return dict(evidence)


def _contains_key(value: Any, prohibited_key: str) -> bool:
    if isinstance(value, Mapping):
        return any(
            key == prohibited_key or _contains_key(child, prohibited_key)
            for key, child in value.items()
        )
    if isinstance(value, (list, tuple)):
        return any(_contains_key(child, prohibited_key) for child in value)
    return False


def _contains_prohibited_key(value: Any, prohibited_keys: set[str]) -> bool:
    if isinstance(value, Mapping):
        return any(
            _is_prohibited_key(str(key), prohibited_keys)
            or _contains_prohibited_key(child, prohibited_keys)
            for key, child in value.items()
        )
    if isinstance(value, (list, tuple)):
        return any(_contains_prohibited_key(child, prohibited_keys) for child in value)
    return False


def _is_prohibited_key(key: str, prohibited_keys: set[str]) -> bool:
    normalized = key.casefold()
    return (
        normalized in prohibited_keys
        or "base64" in normalized
        or normalized.startswith("raw_response")
        or normalized.endswith("_preview_path")
    )


def _contains_absolute_path_value(value: Any) -> bool:
    if isinstance(value, Mapping):
        return any(_contains_absolute_path_value(child) for child in value.values())
    if isinstance(value, (list, tuple)):
        return any(_contains_absolute_path_value(child) for child in value)
    if not isinstance(value, str):
        return False
    normalized = value.strip().replace("\\", "/")
    return bool(
        normalized.startswith("/")
        or re.match(r"^[A-Za-z]:/", normalized)
        or normalized.startswith("//")
    )


def finite_json_number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None
