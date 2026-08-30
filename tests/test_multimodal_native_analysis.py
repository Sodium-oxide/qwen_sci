from __future__ import annotations

import json
from pathlib import Path
import wave

import numpy as np
import pytest

from src.pipeline.multimodal_evidence.contract import (
    MultimodalInputError,
    MultimodalInputSpec,
    MultimodalSettings,
    ValidatedMultimodalRecord,
)
from src.pipeline.multimodal_evidence.service import build_local_multimodal_input_context


def _record(path: Path, modality: str, index: int) -> ValidatedMultimodalRecord:
    return ValidatedMultimodalRecord(
        record_id=f"record-{index}",
        modality=modality,
        source_path=path.resolve(),
        source_name=path.name,
        file_size_bytes=path.stat().st_size,
        metadata={"group": "g1"},
        input_index=index,
    )


def test_none_input_does_not_invoke_native_analysis(monkeypatch) -> None:
    from src.pipeline.multimodal_evidence import service

    def unexpected(*_args, **_kwargs):
        raise AssertionError("native analysis must remain disabled without explicit input")

    monkeypatch.setattr(service, "analyze_record", unexpected)
    assert build_local_multimodal_input_context(None) is None


def test_local_context_contains_json_safe_image_table_and_signal_statistics(tmp_path) -> None:
    Image = pytest.importorskip("PIL.Image")
    pd = pytest.importorskip("pandas")
    image_path = tmp_path / "sample.png"
    Image.new("RGB", (3, 2), (10, 20, 30)).save(image_path)
    table_path = tmp_path / "metrics.csv"
    pd.DataFrame({"measurement": [1.0, 2.0, None], "group": ["a", "b", "b"]}).to_csv(
        table_path,
        index=False,
    )
    signal_path = tmp_path / "signal.npy"
    np.save(signal_path, np.array([1.0, 2.0, 3.0, 4.0]))
    spec = MultimodalInputSpec(
        dataset_id="demo",
        input_mode="manifest",
        records=(
            _record(image_path, "image", 0),
            _record(table_path, "table", 1),
            _record(signal_path, "signal", 2),
        ),
    )

    context = build_local_multimodal_input_context(spec, settings=MultimodalSettings())

    assert context is not None
    assert context["mode"] == "local_only"
    assert context["selected_record_ids"] == ["record-0", "record-1", "record-2"]
    assert {item["modality"] for item in context["native_findings"]} == {
        "image",
        "table",
        "signal",
    }
    assert str(tmp_path.resolve()) not in json.dumps(context, ensure_ascii=False)
    json.dumps(context, allow_nan=False)


def test_partial_local_failure_is_recorded_without_losing_successful_findings(tmp_path) -> None:
    text_path = tmp_path / "notes.txt"
    text_path.write_text("one\ntwo\n", encoding="utf-8")
    molecule_path = tmp_path / "compound.sdf"
    molecule_path.write_text("molecule", encoding="utf-8")
    spec = MultimodalInputSpec(
        dataset_id="partial",
        input_mode="manifest",
        records=(
            _record(text_path, "text", 0),
            _record(molecule_path, "molecule", 1),
        ),
    )

    context = build_local_multimodal_input_context(spec)

    assert context is not None
    assert context["native_findings"][0]["record_id"] == "record-0"
    assert context["rejected_records"] == [
        {
            "record_id": "record-1",
            "modality": "molecule",
            "source_name": "compound.sdf",
            "code": "unsupported_modality",
            "message": "Molecule records are not supported in Batch A because RDKit is not a declared dependency.",
        }
    ]


def test_local_analysis_supports_bounded_audio_point_cloud_and_trajectory_metadata(tmp_path) -> None:
    audio_path = tmp_path / "signal.wav"
    with wave.open(str(audio_path), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(8_000)
        audio.writeframes(b"\x00\x00" * 16)
    point_cloud_path = tmp_path / "shape.xyz"
    point_cloud_path.write_text("0 0 0\n1 0 0\n0 1 0\n", encoding="utf-8")
    trajectory_path = tmp_path / "path.json"
    trajectory_path.write_text("[[0, 0], [3, 4], [3, 8]]", encoding="utf-8")
    spec = MultimodalInputSpec(
        dataset_id="geometry",
        input_mode="manifest",
        records=(
            _record(audio_path, "audio", 0),
            _record(point_cloud_path, "threeD", 1),
            _record(trajectory_path, "trajectory", 2),
        ),
    )

    context = build_local_multimodal_input_context(spec)

    findings = {finding["modality"]: finding["metrics"] for finding in context["native_findings"]}
    assert findings["audio"]["sample_rate_hz"] == 8_000
    assert findings["threeD"]["point_count"] == 3
    assert findings["trajectory"]["path_length"] == 9.0


def test_all_local_failures_are_not_silently_downgraded_to_text_only(tmp_path) -> None:
    molecule_path = tmp_path / "compound.sdf"
    molecule_path.write_text("molecule", encoding="utf-8")
    spec = MultimodalInputSpec(
        dataset_id="all-fail",
        input_mode="manifest",
        records=(_record(molecule_path, "molecule", 0),),
    )

    with pytest.raises(MultimodalInputError, match="No selected multimodal records"):
        build_local_multimodal_input_context(spec)
