from __future__ import annotations

from pathlib import Path

import pytest

from src.pipeline.multimodal_evidence import capabilities
from src.pipeline.multimodal_evidence.contract import (
    MultimodalInputError,
    MultimodalInputSpec,
    ValidatedMultimodalRecord,
)
from src.pipeline.multimodal_evidence.rendering import supports_remote_preview


def _spec(*, modality: str, suffix: str) -> MultimodalInputSpec:
    record = ValidatedMultimodalRecord(
        record_id="record-1",
        modality=modality,
        source_path=Path(f"sample{suffix}"),
        source_name=f"sample{suffix}",
        file_size_bytes=1,
        metadata={},
        input_index=0,
    )
    return MultimodalInputSpec(dataset_id="demo", records=(record,), input_mode="files")


def test_no_input_skips_capability_discovery(monkeypatch) -> None:
    def unexpected(_module_name: str) -> bool:
        raise AssertionError("capability discovery must remain disabled without explicit input")

    monkeypatch.setattr(capabilities, "_module_available", unexpected)

    assert capabilities.preflight_multimodal_capabilities(None) is None


def test_missing_explicit_input_capability_has_install_command(monkeypatch) -> None:
    monkeypatch.setattr(capabilities, "_module_available", lambda _module_name: False)

    with pytest.raises(MultimodalInputError) as exc_info:
        capabilities.preflight_multimodal_capabilities(_spec(modality="image", suffix=".png"))

    message = str(exc_info.value)
    assert "image analysis" in message
    assert "Pillow" in message
    assert "uv sync --group multimodal" in message


def test_remote_preview_preflight_requires_pillow_for_signal(monkeypatch) -> None:
    requested_modules: list[str] = []

    def missing_pillow(module_name: str) -> bool:
        requested_modules.append(module_name)
        return module_name != "PIL"

    monkeypatch.setattr(capabilities, "_module_available", missing_pillow)

    with pytest.raises(MultimodalInputError, match="Pillow"):
        capabilities.preflight_multimodal_capabilities(
            _spec(modality="signal", suffix=".npy"),
            remote_perception_authorized=True,
        )

    assert requested_modules == ["PIL"]


def test_video_preflight_checks_imageio_and_ffmpeg(monkeypatch) -> None:
    monkeypatch.setattr(capabilities, "_module_available", lambda _module_name: False)

    with pytest.raises(MultimodalInputError) as exc_info:
        capabilities.preflight_multimodal_capabilities(_spec(modality="video", suffix=".mp4"))

    assert "imageio, imageio-ffmpeg" in str(exc_info.value)


@pytest.mark.parametrize(
    ("suffix", "required_reader"),
    [
        (".xlsx", "openpyxl"),
        (".xls", "xlrd"),
        (".parquet", "pyarrow"),
    ],
)
def test_table_preflight_checks_format_specific_reader(
    monkeypatch,
    suffix: str,
    required_reader: str,
) -> None:
    monkeypatch.setattr(capabilities, "_module_available", lambda _module_name: False)

    with pytest.raises(MultimodalInputError) as exc_info:
        capabilities.preflight_multimodal_capabilities(_spec(modality="table", suffix=suffix))

    assert required_reader in str(exc_info.value)


def test_video_and_table_records_are_not_eligible_for_remote_previews() -> None:
    assert supports_remote_preview(_spec(modality="video", suffix=".mp4").records[0]) is False
    assert supports_remote_preview(_spec(modality="table", suffix=".csv").records[0]) is False


def test_molecule_input_requires_a_future_chemistry_group(monkeypatch) -> None:
    def unexpected(_module_name: str) -> bool:
        raise AssertionError("molecule input must be rejected before capability discovery")

    monkeypatch.setattr(capabilities, "_module_available", unexpected)

    with pytest.raises(MultimodalInputError) as exc_info:
        capabilities.preflight_multimodal_capabilities(_spec(modality="molecule", suffix=".sdf"))

    message = str(exc_info.value)
    assert "RDKit" in message
    assert "chemistry dependency group" in message
    assert "not processed as text" in message
