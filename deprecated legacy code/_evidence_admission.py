"""Deny-dominant evidence admission decisions."""

from __future__ import annotations

from typing import Any, Mapping


EVIDENCE_ADMISSION_SCHEMA_VERSION = "evidence_admission_v4"
GAP_SOURCE_ADMISSION_SCHEMA_VERSION = "gap_source_admission_v4"

ADMISSION_LEVELS = (
    "HARD_REJECT",
    "PROJECT_CONTEXT_ONLY",
    "AUXILIARY",
    "CORE_CANDIDATE",
    "DIRECT_EVIDENCE",
)
ALLOWED_DIRECT_EVIDENCE_GENRES = frozenset({
    "primary_empirical",
    "primary_measurement",
    "primary_validation",
})
DIRECT_ALIGNMENT_VERDICTS = frozenset({"SUPPORTS"})


def _text(value: Any) -> str:
    return str(value or "").strip()


def _task_alignment_assessment(
    record: Mapping[str, Any],
    contract_id: str,
    research_question_task_id: str,
) -> Mapping[str, Any]:
    """Read the only task-scoped classification authority for admission."""
    for binding in record.get("subhypothesis_bindings", []):
        if not isinstance(binding, Mapping):
            continue
        if (
            _text(binding.get("research_question_contract_id")) == contract_id
            and _text(binding.get("research_question_task_id"))
            == research_question_task_id
        ):
            assessment = binding.get("alignment_assessment")
            return assessment if isinstance(assessment, Mapping) else {}
    return {}


def _paper_classification(record: Mapping[str, Any]) -> Mapping[str, Any]:
    value = record.get("paper_classification")
    if isinstance(value, Mapping):
        return value
    value = record.get("paper_classification_v1")
    return value if isinstance(value, Mapping) else {}


def _document_quality_allows_evidence(record: Mapping[str, Any]) -> bool:
    if record.get("document_quality_allows_evidence") is True:
        return True
    enrichment = record.get("full_text_enrichment")
    enrichment = enrichment if isinstance(enrichment, Mapping) else {}
    conversion = enrichment.get("document_conversion_run")
    conversion = conversion if isinstance(conversion, Mapping) else {}
    text_quality = enrichment.get("text_quality") or conversion.get("quality")
    structure_quality = enrichment.get("structure_quality") or conversion.get("structure_quality")
    locator_quality = enrichment.get("source_locator_quality") or conversion.get("source_locator_quality")
    text_quality = text_quality if isinstance(text_quality, Mapping) else {}
    structure_quality = structure_quality if isinstance(structure_quality, Mapping) else {}
    locator_quality = locator_quality if isinstance(locator_quality, Mapping) else {}
    ingestion_status = _text(
        enrichment.get("ingestion_status") or conversion.get("ingestion_status")
    ).upper()
    return all((
        ingestion_status == "TEXT_READY",
        _text(text_quality.get("status")).upper() == "PASS",
        _text(structure_quality.get("status")).upper() == "PASS",
        _text(locator_quality.get("status")).upper() == "PASS",
    ))


def _document_quality_allows_local_evidence(record: Mapping[str, Any]) -> bool:
    """Require identity, text and source-location integrity for a local claim.

    Whole-document structure is relevant to absence and synthesis claims, but
    cannot invalidate a source-bound result whose own quote and span are valid.
    """
    if record.get("document_integrity_failure") is True:
        return False
    enrichment = record.get("full_text_enrichment")
    enrichment = enrichment if isinstance(enrichment, Mapping) else {}
    conversion = enrichment.get("document_conversion_run")
    conversion = conversion if isinstance(conversion, Mapping) else {}
    text_quality = enrichment.get("text_quality") or conversion.get("quality")
    locator_quality = enrichment.get("source_locator_quality") or conversion.get("source_locator_quality")
    text_quality = text_quality if isinstance(text_quality, Mapping) else {}
    locator_quality = locator_quality if isinstance(locator_quality, Mapping) else {}
    ingestion_status = _text(
        enrichment.get("ingestion_status") or conversion.get("ingestion_status")
    ).upper()
    if record.get("document_quality_allows_evidence") is True:
        return True
    return all((
        ingestion_status == "TEXT_READY",
        _text(text_quality.get("status")).upper() == "PASS",
        _text(locator_quality.get("status")).upper() == "PASS",
    ))


def build_evidence_admission(
    record: Mapping[str, Any],
    *,
    contract_id: str,
    contract_revision: str,
    contract_hash: str,
    extraction_status: str,
    alignment_status: str,
    assertions: list[dict[str, Any]],
    research_question_task_id: str = "",
) -> dict[str, Any]:
    alignment = _task_alignment_assessment(
        record, contract_id, research_question_task_id
    )
    classification = _paper_classification(record)
    task_research_role = _text(alignment.get("research_role")).upper()
    research_role = _text(
        task_research_role or classification.get("research_role")
    ).upper()
    evidence_genre = _text(
        record.get("evidence_genre") or classification.get("evidence_genre")
    ).lower()
    document_quality_ready = _document_quality_allows_evidence(record)
    local_document_quality_ready = _document_quality_allows_local_evidence(record)
    allowed_use = _text(alignment.get("allowed_use")).lower()
    exclusion_hits = alignment.get("exclusion_hits") or []
    hard_reject_reasons: list[str] = []
    if task_research_role == "OFF_TOPIC" or alignment.get("off_topic") is True or alignment.get("true_off_topic") is True:
        hard_reject_reasons.append("OFF_TOPIC")
    if allowed_use == "excluded_from_automatic_import":
        hard_reject_reasons.append("EXCLUDED_FROM_AUTOMATIC_IMPORT")
    if exclusion_hits:
        hard_reject_reasons.append("EXPLICIT_EXCLUSION_HIT")
    if record.get("document_integrity_failure") is True:
        hard_reject_reasons.append("DOCUMENT_INTEGRITY_FAILURE")
    verified_assertions = [
        assertion
        for assertion in assertions
        if isinstance(assertion, Mapping)
        and _text(assertion.get("validator_verdict")) == "VERIFIED_SOURCE_BOUND"
    ]
    arm_evidence_assertions = [
        assertion
        for assertion in verified_assertions
        if isinstance(assertion.get("comparison_evidence_v4"), Mapping)
        and _text((assertion.get("comparison_evidence_v4") or {}).get("evidence_type"))
        == "ARM_EVIDENCE"
        and bool((assertion.get("comparison_evidence_v4") or {}).get("arm_matches"))
    ]
    arm_evidence_assertion_ids = sorted({
        _text(assertion.get("assertion_id"))
        for assertion in arm_evidence_assertions
        if _text(assertion.get("assertion_id"))
    })
    arm_coverage_ids = sorted({
        _text(match.get("arm_id"))
        for assertion in arm_evidence_assertions
        for match in (assertion.get("comparison_evidence_v4") or {}).get("arm_matches", [])
        if isinstance(match, Mapping) and _text(match.get("arm_id"))
    })
    verified_supports = [
        support
        for assertion in verified_assertions
        for support in assertion.get("slot_support", [])
        if isinstance(support, Mapping)
        and support.get("research_question_contract_id") == contract_id
        and (
            not research_question_task_id
            or _text(support.get("research_question_task_id"))
            == research_question_task_id
        )
        and support.get("support_status") == "VERIFIED_NONCOUNTING"
        and _text(support.get("alignment_verdict")) in {
            "SUPPORTS", "CONSISTENT_WITH", "BOUNDARY", "ADVERSE"
        }
    ]
    effective_supports: list[dict[str, Any]] = []
    support_admissions: list[dict[str, Any]] = []
    for assertion in verified_assertions:
        assertion_id = _text(assertion.get("assertion_id"))
        partial_eligible = (
            extraction_status == "PROPOSITION_PARTIAL"
            and isinstance(assertion.get("partial_gate_eligibility"), Mapping)
            and assertion["partial_gate_eligibility"].get("status")
            == "ELIGIBLE_FOR_PARTIAL_POSITIVE_ADMISSION"
        )
        local_claim_ready = extraction_status == "PROPOSITION_READY" or partial_eligible
        for raw_support in assertion.get("slot_support", []):
            if not isinstance(raw_support, Mapping):
                continue
            support = dict(raw_support)
            if support.get("research_question_contract_id") != contract_id:
                continue
            if research_question_task_id and (
                _text(support.get("research_question_task_id"))
                != research_question_task_id
            ):
                continue
            terminal_positive = (
                support.get("support_status") == "VERIFIED_NONCOUNTING"
                and _text(support.get("terminal_status")) == "TERMINAL"
                and _text(support.get("alignment_verdict")) in DIRECT_ALIGNMENT_VERDICTS
            )
            direct_admitted = bool(
                not hard_reject_reasons
                and terminal_positive
                and local_claim_ready
                and _text(assertion.get("attribution")).upper() == "CURRENT_AUTHORS"
                and evidence_genre in ALLOWED_DIRECT_EVIDENCE_GENRES
                and local_document_quality_ready
            )
            support_admissions.append({
                "assertion_id": assertion_id,
                "slot_support_id": _text(support.get("slot_support_id")),
                "slot_id": _text(support.get("slot_id")),
                "admission_status": (
                    "DIRECT_SLOT_ADMITTED" if direct_admitted
                    else "PENDING" if _text(support.get("terminal_status")) != "TERMINAL"
                    else "CONTEXT_RETAINED"
                ),
                "counts_toward_slot_gate": direct_admitted,
                "reason_codes": ([] if direct_admitted else [
                    "PENDING_ALIGNMENT_PAIR" if _text(support.get("terminal_status")) != "TERMINAL"
                    else "NONCOUNTING_ASSERTION_SLOT_SUPPORT"
                ]),
            })
            if direct_admitted:
                effective_supports.append(support)
    admitted_supports_by_slot: dict[str, list[dict[str, Any]]] = {}
    for support in effective_supports:
        slot_id = _text(support.get("slot_id"))
        if slot_id:
            admitted_supports_by_slot.setdefault(slot_id, []).append(dict(support))
    if hard_reject_reasons:
        level = "HARD_REJECT"
        reason_codes = hard_reject_reasons
    elif effective_supports:
        level = "DIRECT_EVIDENCE"
        reason_codes = ["ADMITTED_TASK_SLOT_SOURCE_BOUND_SUPPORT"]
    elif arm_evidence_assertions:
        # A single declared arm is usable for comparison coverage but cannot
        # itself establish that one arm outperforms another.
        level = "AUXILIARY"
        reason_codes = ["ARM_EVIDENCE_NONCOUNTING_UNTIL_COMPARABILITY_AUDIT"]
    elif verified_supports:
        level = "CORE_CANDIDATE"
        reason_codes = list(dict.fromkeys([
            "CONTRACT_RELEVANT_WITHOUT_DIRECT_ADMISSION",
            *([] if evidence_genre in ALLOWED_DIRECT_EVIDENCE_GENRES else [
                "EVIDENCE_GENRE_NOT_DIRECT_ADMISSIBLE"
            ]),
            *([] if document_quality_ready else ["DOCUMENT_QUALITY_NOT_EVIDENCE_READY"]),
        ]))
    elif research_role in {"METHOD", "BACKGROUND", "COMPONENT_SUPPORT", "BOUNDARY"}:
        level = "AUXILIARY"
        reason_codes = ["AUXILIARY_RESEARCH_ROLE"]
    else:
        level = "PROJECT_CONTEXT_ONLY"
        reason_codes = ["NO_ADMITTED_SOURCE_BOUND_SLOT_SUPPORT"]
    direct = level == "DIRECT_EVIDENCE"
    retained = level != "HARD_REJECT"
    return {
        "schema_version": GAP_SOURCE_ADMISSION_SCHEMA_VERSION,
        "research_question_contract_id": contract_id,
        "research_question_contract_revision": contract_revision,
        "research_question_contract_hash": contract_hash,
        "research_question_task_id": research_question_task_id,
        "admission_level": level,
        "reason_codes": reason_codes,
        "deny_dominance_applied": bool(hard_reject_reasons),
        "partial_document_admission": direct and extraction_status == "PROPOSITION_PARTIAL",
        "retained_for_project_context": retained,
        "eligible_for_gap_synthesis": direct,
        "eligible_for_direct_slot": direct,
        "counts_toward_gate": direct,
        "counts_toward_corpus_target": direct,
        "direct_evidence_eligible": direct,
        "counts_toward_arm_coverage": bool(arm_evidence_assertion_ids),
        "counts_toward_comparison_conclusion": False,
        "corpus_admitted": level in {"AUXILIARY", "CORE_CANDIDATE", "DIRECT_EVIDENCE"},
        "corpus_admission_reason": reason_codes[0] if reason_codes else "",
        "admitted_assertion_ids": sorted({
            _text(item.get("assertion_id")) for item in effective_supports if _text(item.get("assertion_id"))
        }),
        "admitted_slot_support_ids": sorted({
            _text(item.get("slot_support_id")) for item in effective_supports if _text(item.get("slot_support_id"))
        }),
        "eligible_slot_ids": sorted(admitted_supports_by_slot),
        "admitted_slot_supports": admitted_supports_by_slot,
        "support_admissions": support_admissions,
        "verified_noncounting_assertion_ids": sorted({
            _text(assertion.get("assertion_id"))
            for assertion in verified_assertions
            if _text(assertion.get("assertion_id"))
        }),
        "verified_noncounting_slot_support_ids": sorted({
            _text(support.get("slot_support_id"))
            for support in verified_supports
            if _text(support.get("slot_support_id"))
        }),
        "arm_evidence_assertion_ids": arm_evidence_assertion_ids,
        "arm_coverage_ids": arm_coverage_ids,
        "evidence_genre": evidence_genre,
        "research_role": research_role,
        "document_quality_ready": document_quality_ready,
        "local_document_quality_ready": local_document_quality_ready,
        "extraction_status": extraction_status,
        "slot_alignment_status": alignment_status,
    }


def aggregate_evidence_admissions(admissions: Mapping[str, Any]) -> dict[str, Any]:
    values = [
        task_admission
        for item in admissions.values()
        if isinstance(item, Mapping)
        for task_admission in (
            item.get("task_admissions", {}).values()
            if isinstance(item.get("task_admissions"), Mapping)
            else [item]
        )
        if isinstance(task_admission, Mapping)
    ]
    priority = {level: index for index, level in enumerate(ADMISSION_LEVELS)}
    if not values:
        level = "PROJECT_CONTEXT_ONLY"
        selected: list[Mapping[str, Any]] = []
    elif any(item.get("admission_level") == "HARD_REJECT" for item in values):
        level = "HARD_REJECT"
        selected = [item for item in values if item.get("admission_level") == level]
    else:
        level = max(
            (_text(item.get("admission_level")) for item in values),
            key=lambda item: priority.get(item, 0),
        )
        selected = [item for item in values if item.get("admission_level") == level]
    direct = level == "DIRECT_EVIDENCE"
    retained = level != "HARD_REJECT"
    arm_evidence_assertion_ids = sorted({
        _text(assertion_id)
        for item in values
        for assertion_id in item.get("arm_evidence_assertion_ids", [])
        if _text(assertion_id)
    })
    arm_coverage_ids = sorted({
        _text(arm_id)
        for item in values
        for arm_id in item.get("arm_coverage_ids", [])
        if _text(arm_id)
    })
    return {
        "schema_version": EVIDENCE_ADMISSION_SCHEMA_VERSION,
        "admission_level": level,
        "reason_codes": sorted({
            _text(reason)
            for item in selected
            for reason in item.get("reason_codes", [])
            if _text(reason)
        }) or ["NO_CONTRACT_ADMISSION"],
        "retained_for_project_context": retained,
        "eligible_for_gap_synthesis": direct,
        "eligible_for_direct_slot": direct,
        "counts_toward_gate": direct,
        "counts_toward_corpus_target": direct,
        "counts_toward_arm_coverage": bool(arm_evidence_assertion_ids),
        "counts_toward_comparison_conclusion": False,
        "arm_evidence_assertion_ids": arm_evidence_assertion_ids,
        "arm_coverage_ids": arm_coverage_ids,
        "corpus_admitted": level in {"AUXILIARY", "CORE_CANDIDATE", "DIRECT_EVIDENCE"},
        "deny_dominance_applied": level == "HARD_REJECT",
        "partial_document_admission": bool(
            direct and any(item.get("partial_document_admission") is True for item in selected)
        ),
    }


def aggregate_task_evidence_admissions(
    admissions: Mapping[str, Any],
) -> dict[str, Any]:
    """Aggregate independent object-task decisions without cross-task poisoning."""
    task_values = {
        str(key): item
        for key, item in admissions.items()
        if isinstance(item, Mapping)
    }
    non_rejected = {
        key: item
        for key, item in task_values.items()
        if item.get("admission_level") != "HARD_REJECT"
    }
    aggregate = aggregate_evidence_admissions(non_rejected or task_values)
    aggregate["task_scoped"] = True
    aggregate["task_count"] = len(task_values)
    aggregate["hard_rejected_task_count"] = sum(
        1
        for item in task_values.values()
        if item.get("admission_level") == "HARD_REJECT"
    )
    return aggregate


def apply_evidence_admission(
    record: dict[str, Any],
    admissions: Mapping[str, Any],
    *,
    evidence_record: dict[str, Any] | None = None,
) -> dict[str, Any]:
    aggregate = aggregate_evidence_admissions(admissions)
    record["evidence_admission_v4"] = aggregate
    for key in (
        "retained_for_project_context", "eligible_for_gap_synthesis",
        "eligible_for_direct_slot", "counts_toward_gate",
        "counts_toward_corpus_target", "counts_toward_arm_coverage",
        "counts_toward_comparison_conclusion", "corpus_admitted",
    ):
        record[key] = aggregate[key]
    record["direct_evidence_eligible"] = aggregate["eligible_for_direct_slot"]
    record["corpus_admission_reason"] = aggregate["reason_codes"][0]
    if isinstance(evidence_record, dict):
        evidence_record["evidence_admission_v4"] = dict(aggregate)
        for key in (
            "eligible_for_gap_synthesis", "eligible_for_direct_slot",
            "counts_toward_gate", "counts_toward_corpus_target",
            "counts_toward_arm_coverage", "counts_toward_comparison_conclusion",
            "corpus_admitted",
        ):
            evidence_record[key] = aggregate[key]
    return aggregate
