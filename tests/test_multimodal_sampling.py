from __future__ import annotations

from pathlib import Path

from src.pipeline.multimodal_evidence.contract import ValidatedMultimodalRecord
from src.pipeline.multimodal_evidence.sampling import select_stratified_records


def _record(record_id: str, input_index: int, **metadata: str) -> ValidatedMultimodalRecord:
    return ValidatedMultimodalRecord(
        record_id=record_id,
        modality="image",
        source_path=Path(f"/unused/{record_id}.png"),
        source_name=f"{record_id}.png",
        file_size_bytes=1,
        metadata=metadata,
        input_index=input_index,
    )


def test_sampling_preserves_each_stratum_then_round_robins_stably() -> None:
    records = [
        _record("a-1", 0, group="a"),
        _record("a-2", 1, group="a"),
        _record("a-3", 2, group="a"),
        _record("b-1", 3, group="b"),
        _record("b-2", 4, group="b"),
    ]

    result = select_stratified_records(records, max_records_per_modality=4)

    assert result.selected_record_ids == ["a-1", "a-2", "b-1", "b-2"]
    assert result.truncated_strata_by_modality == {}
    assert result.policy.endswith("_v1")


def test_sampling_is_deterministic_when_strata_exceed_the_budget() -> None:
    records = [
        _record("a", 0, label="a"),
        _record("b", 1, label="b"),
        _record("c", 2, label="c"),
    ]

    first = select_stratified_records(records, max_records_per_modality=2)
    second = select_stratified_records(reversed(records), max_records_per_modality=2)

    assert first.selected_record_ids == ["a", "b"]
    assert second.selected_record_ids == first.selected_record_ids
    assert first.truncated_strata_by_modality == {"image": 1}
