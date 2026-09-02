"""V3 contract-slot evidence bundles for a research question.

A V3 bundle composes only what the active research-question contract declares:
source-bound support for its evidence slots.  Causal slots remain available for
causal gap types, but are never invented for another type.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Mapping

try:
    from ._type_directed_evidence import (
        evidence_profile_for_contract,
        type_directed_admission,
    )
except ImportError:
    from _type_directed_evidence import (
        evidence_profile_for_contract,
        type_directed_admission,
    )


TYPE_DIRECTED_EVIDENCE_BUNDLE_VERSION = "type_directed_evidence_bundle_v3"


def _text(value: Any) -> str:
    return " ".join(str(value or "").split())


def _identity(item: Mapping[str, Any], position: int) -> str:
    record = item.get("record") if isinstance(item.get("record"), Mapping) else {}
    for value in (
        item.get("identity"), record.get("paper_id"), record.get("doi"),
        record.get("url"), record.get("title"),
    ):
        normalized = _text(value)
        if normalized:
            return normalized
    return f"record_{position + 1}"


def _sh_local(item: Mapping[str, Any]) -> bool:
    record = item.get("record") if isinstance(item.get("record"), Mapping) else {}
    alignment = item.get("alignment") if isinstance(item.get("alignment"), Mapping) else {}
    scope = _text(
        alignment.get("admission_scope")
        or alignment.get("sh_locality_scope")
        or record.get("admission_scope")
        or record.get("sh_locality_scope")
    ).lower()
    return bool(
        alignment.get("project_background_only") is not True
        and alignment.get("off_topic") is not True
        and scope not in {"project_background_only", "out_of_scope"}
    )


def _source_admission(
    record: Mapping[str, Any], alignment: Mapping[str, Any], contract: Mapping[str, Any],
) -> dict[str, Any]:
    """Use only a current V3 projection or recompute one from source spans."""

    projected = alignment.get("type_directed_evidence")
    if isinstance(projected, Mapping) and _text(projected.get("schema_version")) == "type_directed_admission_v3":
        return dict(projected)
    return type_directed_admission(
        record,
        contract,
        context_admitted=_sh_local({"record": record, "alignment": alignment}),
        excluded=bool(alignment.get("off_topic") is True),
        panel_core_allowed=alignment.get("panel_core_allowed") is not False,
        requested_evidence_kind=_text(alignment.get("requested_evidence_kind")),
    )


def evaluate_type_directed_evidence_bundle(
    project: Mapping[str, Any],
    sub_hypothesis_id: str,
    related_records: list[dict[str, Any]],
    *,
    alignment_contract: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Aggregate V3 source admissions against the declared slot contract."""

    del project
    contract = alignment_contract if isinstance(alignment_contract, Mapping) else {}
    profile = evidence_profile_for_contract(contract)
    required_slots = list(profile.get("required_slots") or [])
    slot_sources: dict[str, list[dict[str, Any]]] = defaultdict(list)
    source_entries: list[dict[str, Any]] = []
    unsupported_sources: list[dict[str, Any]] = []
    for position, item in enumerate(related_records or []):
        if not isinstance(item, Mapping):
            continue
        record = item.get("record") if isinstance(item.get("record"), Mapping) else {}
        alignment = item.get("alignment") if isinstance(item.get("alignment"), Mapping) else {}
        identity = _identity(item, position)
        sh_local = _sh_local(item)
        admission = _source_admission(record, alignment, contract)
        entry = {
            "source_identity": identity,
            "title": _text(record.get("title"))[:240],
            "source_admission_present": bool(admission.get("source_admission_present")),
            "admission_status": _text(admission.get("admission_status")),
            "evidence_lane": _text(admission.get("evidence_lane")),
            "scope_status": _text(admission.get("scope_status")),
            "admitted_slot_ids": list(admission.get("admitted_slot_ids") or []),
            "supporting_source_span_ids": list(admission.get("supporting_source_span_ids") or []),
            "sh_local": sh_local,
        }
        if not sh_local or not admission.get("source_admission_present"):
            unsupported_sources.append(entry)
            continue
        source_entries.append(entry)
        for slot_id in entry["admitted_slot_ids"]:
            if required_slots and slot_id not in required_slots:
                continue
            slot_sources[slot_id].append(entry)
    supported_slots = [slot for slot in required_slots if slot_sources.get(slot)]
    missing_slots = [slot for slot in required_slots if not slot_sources.get(slot)]
    source_bound_slot_support_count = sum(len(slot_sources[slot]) for slot in supported_slots)
    contract_operational = bool(_text(profile.get("research_question_contract_id")) and required_slots)
    if not contract_operational:
        status = "CONTRACT_EVIDENCE_SLOTS_UNDECLARED"
    elif not source_entries:
        status = "NO_SOURCE_BOUND_CONTRACT_EVIDENCE"
    elif not missing_slots:
        status = "CORE_CONTRACT_EVIDENCE_BUNDLE"
    else:
        status = "PARTIAL_CONTRACT_EVIDENCE"
    core_ready = status == "CORE_CONTRACT_EVIDENCE_BUNDLE"
    partial_ready = status in {"CORE_CONTRACT_EVIDENCE_BUNDLE", "PARTIAL_CONTRACT_EVIDENCE"}
    return {
        "schema_version": TYPE_DIRECTED_EVIDENCE_BUNDLE_VERSION,
        "sub_hypothesis_id": _text(sub_hypothesis_id),
        "research_question_contract_id": _text(profile.get("research_question_contract_id")),
        "gap_types": list(profile.get("gap_types") or []),
        "required_slot_ids": required_slots,
        "supported_slot_ids": supported_slots,
        "missing_required_slot_ids": missing_slots,
        "slot_source_lineage": {slot: list(slot_sources.get(slot) or []) for slot in required_slots},
        "source_bound_contract_support_count": len(source_entries),
        "source_bound_slot_support_count": source_bound_slot_support_count,
        "source_entries": source_entries,
        "unsupported_source_entries": unsupported_sources,
        "contract_operational": contract_operational,
        "status": status,
        "core_contract_evidence_ready": core_ready,
        "partial_contract_evidence_ready": partial_ready,
        "research_question_ready": core_ready,
        "reason": (
            "all contract-required evidence slots have V3 source-bound support"
            if core_ready else "one or more declared evidence slots remain unsupported"
            if partial_ready else "the active contract lacks source-bound V3 evidence support"
        ),
    }
