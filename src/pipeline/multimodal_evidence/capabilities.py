"""Preflight optional local capabilities for explicit multimodal inputs."""

from __future__ import annotations

import importlib.util
from collections.abc import Iterable

from .contract import MultimodalInputError, MultimodalInputSpec, ValidatedMultimodalRecord


MULTIMODAL_INSTALL_COMMAND = "uv sync --group multimodal"

_CAPABILITY_MODULES = {
    "Pillow": "PIL",
    "pandas": "pandas",
    "imageio": "imageio",
    "imageio-ffmpeg": "imageio_ffmpeg",
    "openpyxl": "openpyxl",
    "pyarrow": "pyarrow",
    "xlrd": "xlrd",
}
_REMOTE_PREVIEW_MODALITIES = frozenset({"image", "signal", "audio", "threeD", "trajectory"})


def preflight_multimodal_capabilities(
    input_spec: MultimodalInputSpec | None,
    *,
    remote_perception_authorized: bool = False,
) -> None:
    """Fail before native media reads when declared optional capabilities are absent.

    The caller must pass an already-validated explicit input spec. A missing
    spec deliberately performs no module discovery so pure-text Survey runs
    preserve their default-closed multimodal behavior.
    """

    if input_spec is None:
        return
    molecule_records = [
        record for record in input_spec.records if record.modality == "molecule"
    ]
    if molecule_records:
        record_ids = ", ".join(record.record_id for record in molecule_records)
        raise MultimodalInputError(
            "Molecule/RDKit input is not supported by the current multimodal capability "
            f"for record(s): {record_ids}. It requires a separate chemistry dependency group "
            "and was not processed as text."
        )

    required = _required_capabilities(
        input_spec.records,
        remote_perception_authorized=remote_perception_authorized,
    )
    missing = [
        capability
        for capability in sorted(required)
        if not _module_available(_CAPABILITY_MODULES[capability])
    ]
    if not missing:
        return
    modalities = ", ".join(sorted({record.modality for record in input_spec.records}))
    raise MultimodalInputError(
        "Multimodal capability unavailable for explicit "
        f"{modalities} analysis: missing {', '.join(missing)}. "
        f"Install it with: {MULTIMODAL_INSTALL_COMMAND}"
    )


def _required_capabilities(
    records: Iterable[ValidatedMultimodalRecord],
    *,
    remote_perception_authorized: bool,
) -> set[str]:
    required: set[str] = set()
    for record in records:
        suffix = record.source_path.suffix.lower()
        if record.modality == "image":
            required.add("Pillow")
        elif record.modality == "table":
            required.update(_table_capabilities(suffix))
        elif record.modality == "signal" and suffix in {".csv", ".tsv"}:
            required.add("pandas")
        elif record.modality == "video":
            required.update({"imageio", "imageio-ffmpeg"})
        elif record.modality == "trajectory" and suffix != ".json":
            required.add("pandas")
        if remote_perception_authorized and record.modality in _REMOTE_PREVIEW_MODALITIES:
            required.add("Pillow")
    return required


def _table_capabilities(suffix: str) -> set[str]:
    required = {"pandas"}
    if suffix == ".xlsx":
        required.add("openpyxl")
    elif suffix == ".xls":
        required.add("xlrd")
    elif suffix == ".parquet":
        required.add("pyarrow")
    return required


def _module_available(module_name: str) -> bool:
    try:
        return importlib.util.find_spec(module_name) is not None
    except (ImportError, ModuleNotFoundError, ValueError):
        return False
