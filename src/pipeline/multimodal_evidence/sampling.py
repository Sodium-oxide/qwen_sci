from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from typing import Iterable

from .contract import ValidatedMultimodalRecord


@dataclass(frozen=True)
class SamplingResult:
    records: tuple[ValidatedMultimodalRecord, ...]
    policy: str
    truncated_strata_by_modality: dict[str, int]

    @property
    def selected_record_ids(self) -> list[str]:
        return [record.record_id for record in self.records]


def _stratum_key(record: ValidatedMultimodalRecord) -> tuple[str, str, str, str]:
    metadata = record.metadata
    return tuple(str(metadata.get(key, "")) for key in ("label", "group", "condition", "timepoint"))


def select_stratified_records(
    records: Iterable[ValidatedMultimodalRecord],
    *,
    max_records_per_modality: int,
) -> SamplingResult:
    if max_records_per_modality < 1:
        raise ValueError("max_records_per_modality must be at least 1.")
    by_modality: "OrderedDict[str, list[ValidatedMultimodalRecord]]" = OrderedDict()
    for record in sorted(records, key=lambda item: item.input_index):
        by_modality.setdefault(record.modality, []).append(record)

    selected: list[ValidatedMultimodalRecord] = []
    truncated_strata_by_modality: dict[str, int] = {}
    for modality, modality_records in by_modality.items():
        strata: "OrderedDict[tuple[str, str, str, str], list[ValidatedMultimodalRecord]]" = OrderedDict()
        for record in modality_records:
            strata.setdefault(_stratum_key(record), []).append(record)
        stratum_records = list(strata.values())
        if len(stratum_records) > max_records_per_modality:
            truncated_strata_by_modality[modality] = len(stratum_records) - max_records_per_modality
        modality_selected: list[ValidatedMultimodalRecord] = [
            group[0] for group in stratum_records[:max_records_per_modality]
        ]
        next_indices = [1 for _ in modality_selected]
        while len(modality_selected) < max_records_per_modality:
            added = False
            for group_index, group in enumerate(stratum_records[:max_records_per_modality]):
                next_index = next_indices[group_index]
                if next_index >= len(group):
                    continue
                modality_selected.append(group[next_index])
                next_indices[group_index] += 1
                added = True
                if len(modality_selected) >= max_records_per_modality:
                    break
            if not added:
                break
        selected.extend(modality_selected)

    return SamplingResult(
        records=tuple(sorted(selected, key=lambda item: item.input_index)),
        policy="stratified_by_label_group_condition_timepoint_round_robin_v1",
        truncated_strata_by_modality=truncated_strata_by_modality,
    )
