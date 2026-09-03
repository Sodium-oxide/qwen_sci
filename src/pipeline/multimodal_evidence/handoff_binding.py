"""Bind bounded multimodal observations into the existing Idea handoff v1."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from src.pipeline.survey_idea_handoff import (
    AnchorRecord,
    EvidenceRoleRecord,
    SourcePointer,
)

from .survey_integration import build_multimodal_survey_projection


MULTIMODAL_EVIDENCE_ARTIFACT = "multimodal_evidence.json"


def build_multimodal_handoff_binding(
    multimodal_evidence: Mapping[str, Any] | None,
    *,
    gap_ids_by_subhypothesis: Mapping[str, Sequence[str]] | None = None,
) -> tuple[list[AnchorRecord], list[EvidenceRoleRecord]]:
    """Create v1 anchors and roles without widening the handoff schema.

    An observation is linked to a Gap only when that data SH has exactly one
    eligible Gap.  Multiple same-SH Gaps require an explicit binding later in
    the handoff, which prevents a local observation from elevating an unrelated
    Gap merely because both happen to share an SH identifier.
    """

    projection = build_multimodal_survey_projection(multimodal_evidence)
    if projection is None:
        return [], []
    gap_ids_by_subhypothesis = gap_ids_by_subhypothesis or {}
    anchors: list[AnchorRecord] = []
    roles: list[EvidenceRoleRecord] = []
    for row in projection.get("data_anchored_subhypotheses", []):
        if not isinstance(row, Mapping):
            continue
        subhypothesis_id = str(row.get("sub_hypothesis_id") or "").strip()
        if not subhypothesis_id:
            continue
        associated_gap_ids = _unique_texts(
            list(gap_ids_by_subhypothesis.get(subhypothesis_id, []))
        )
        direct_gap_ids = associated_gap_ids if len(associated_gap_ids) == 1 else []
        observation_anchors: list[AnchorRecord] = []
        claim_limits: list[str] = []
        observed_record_ids: set[str] = set()
        for observation in row.get("observations", []):
            if not isinstance(observation, Mapping):
                continue
            observation_id = str(observation.get("observation_id") or "").strip()
            if not observation_id:
                continue
            observed_record_ids.update(
                str(record_id).strip()
                for record_id in observation.get("record_ids", [])
                if str(record_id).strip()
            )
            anchor = AnchorRecord.create(
                anchor_type="multimodal_observation",
                label=f"{subhypothesis_id}: provided-data observation {observation_id}",
                subhypothesis_id=subhypothesis_id,
                target_slot="multimodal_observation",
                source_id=observation_id,
                claim_anchor=str(observation.get("finding") or "")[:700],
                text_excerpt=str(observation.get("finding") or "")[:900],
                supports_gap_ids=direct_gap_ids,
                source_pointer=SourcePointer(
                    artifact=MULTIMODAL_EVIDENCE_ARTIFACT,
                    json_pointer=f"/observations/{_source_index(observation)}",
                ),
            )
            anchors.append(anchor)
            observation_anchors.append(anchor)
            limit = str(observation.get("claim_limits") or "").strip()
            if limit:
                claim_limits.append(limit)
        for claim in row.get("claims", []):
            if not isinstance(claim, Mapping):
                continue
            limit = str(claim.get("claim_limits") or "").strip()
            if limit:
                claim_limits.append(limit)
        anchor_ids = [anchor.anchor_id for anchor in observation_anchors]
        if anchor_ids:
            roles.append(
                EvidenceRoleRecord.create(
                    subhypothesis_id=subhypothesis_id,
                    target_slot="multimodal_observation",
                    expected_role="DIRECT_OBSERVATION",
                    allowed_support_kinds=["provided_multimodal_data_only"],
                    claim_limits=_unique_texts(claim_limits),
                    anchor_ids=anchor_ids,
                )
            )
        if observed_record_ids:
            roles.append(
                EvidenceRoleRecord.create(
                    subhypothesis_id=subhypothesis_id,
                    target_slot="multimodal_native_measurement",
                    expected_role="METHOD_OR_MEASUREMENT",
                    allowed_support_kinds=["bounded_local_native_measurement"],
                    claim_limits=_unique_texts(
                        [
                            *claim_limits,
                            "Native metrics describe only the provided records and do not establish a mechanism or generality.",
                        ]
                    ),
                    anchor_ids=anchor_ids,
                )
            )
    return anchors, roles


def _unique_texts(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if text and text not in seen:
            seen.add(text)
            result.append(text[:700])
    return result


def _source_index(observation: Mapping[str, Any]) -> int:
    value = observation.get("source_index")
    return value if isinstance(value, int) and value >= 0 else 0


__all__ = ["MULTIMODAL_EVIDENCE_ARTIFACT", "build_multimodal_handoff_binding"]
