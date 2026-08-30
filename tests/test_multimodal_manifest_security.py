from __future__ import annotations

import json

import pytest

from src.pipeline.multimodal_evidence.contract import MultimodalInputError, MultimodalSettings
from src.pipeline.multimodal_evidence.manifest import (
    build_input_spec_from_files,
    load_input_manifest,
)


def _write_manifest(tmp_path, records: list[dict]) -> object:
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": "multimodal_input_manifest_v1",
                "dataset_id": "dataset-a",
                "records": records,
            }
        ),
        encoding="utf-8",
    )
    return manifest


def _record(file_name: str, **extra: object) -> dict:
    return {
        "record_id": "record-001",
        "file": file_name,
        "modality": "image",
        **extra,
    }


def test_manifest_accepts_relative_file_and_filters_unknown_metadata(tmp_path) -> None:
    files = tmp_path / "files"
    files.mkdir()
    (files / "micrograph.png").write_bytes(b"image")
    manifest = _write_manifest(
        tmp_path,
        [
            _record(
                "files/micrograph.png",
                group="batch-A",
                condition="wet",
                secret_note="must not propagate",
            )
        ],
    )

    spec = load_input_manifest(manifest)

    assert spec.dataset_id == "dataset-a"
    assert spec.records[0].metadata == {"group": "batch-A", "condition": "wet"}
    assert spec.records[0].source_path == (files / "micrograph.png").resolve()


@pytest.mark.parametrize("file_name", ["../outside.png", "/tmp/outside.png", "C:\\outside.png"])
def test_manifest_rejects_escaping_member_paths(tmp_path, file_name: str) -> None:
    manifest = _write_manifest(tmp_path, [_record(file_name)])

    with pytest.raises(MultimodalInputError, match="relative manifest file path"):
        load_input_manifest(manifest)


def test_manifest_rejects_symlink_escape(tmp_path) -> None:
    outside = tmp_path.parent / "outside.png"
    outside.write_bytes(b"image")
    link = tmp_path / "escaped.png"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("Current Windows test environment cannot create symlinks.")
    manifest = _write_manifest(tmp_path, [_record("escaped.png")])

    with pytest.raises(MultimodalInputError, match="outside the manifest directory"):
        load_input_manifest(manifest)


def test_manifest_rejects_unknown_and_mismatched_modalities(tmp_path) -> None:
    (tmp_path / "sample.png").write_bytes(b"image")
    unknown = _write_manifest(
        tmp_path,
        [{"record_id": "record-001", "file": "sample.png", "modality": "unknown"}],
    )

    with pytest.raises(MultimodalInputError, match="Unsupported multimodal modality"):
        load_input_manifest(unknown)

    mismatch = _write_manifest(
        tmp_path,
        [{"record_id": "record-001", "file": "sample.png", "modality": "table"}],
    )
    with pytest.raises(MultimodalInputError, match="extension incompatible"):
        load_input_manifest(mismatch)


def test_manifest_rejects_missing_file_and_size_limit(tmp_path) -> None:
    missing = _write_manifest(tmp_path, [_record("missing.png")])
    with pytest.raises(MultimodalInputError, match="does not exist"):
        load_input_manifest(missing)

    (tmp_path / "large.png").write_bytes(b"1234")
    oversized = _write_manifest(tmp_path, [_record("large.png")])
    with pytest.raises(MultimodalInputError, match="per-file"):
        load_input_manifest(
            oversized,
            settings=MultimodalSettings(max_input_file_bytes=3, max_total_input_bytes=10),
        )


def test_explicit_ambiguous_file_requires_a_manifest_modality_declaration(tmp_path) -> None:
    array_path = tmp_path / "measurement.npy"
    array_path.write_bytes(b"not inspected before modality selection")

    with pytest.raises(MultimodalInputError, match="ambiguous"):
        build_input_spec_from_files([array_path])
