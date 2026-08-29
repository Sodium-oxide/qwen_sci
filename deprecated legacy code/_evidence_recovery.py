"""Failure-specific recovery routing for the V4 evidence pipeline."""

from __future__ import annotations

from typing import Any, Iterable, Mapping


EVIDENCE_RECOVERY_SCHEMA_VERSION = "evidence_recovery_classification_v1"

RECOVERY_ACTIONS = {
    "CONTRACT_SCOPE_INCOHERENT": "re_decompose_or_narrow_research_question_contract",
    "CONTRACT_COHERENCE_PENDING": "resume_contract_coherence_audit",
    "CORPUS_OFF_TOPIC_DOMINANT": "repair_query_and_admission_before_more_retrieval",
    "FULLTEXT_STRUCTURE_INVALID": "rerun_document_section_and_span_structuring",
    "LLM_EXTRACTION_PENDING": "resume_llm_proposition_extraction",
    "ASSERTION_VALIDATION_FAILURE": "inspect_fulltext_parser_and_proposition_prompt",
    "SLOT_ALIGNMENT_FAILURE": "repair_contract_semantics_or_slot_mapping",
    "GENUINE_SLOT_SHORTAGE": "run_slot_directed_retrieval_for_declared_missing_slots",
    "LINEAGE_MISSING": "rebuild_assertion_to_source_lineage",
    "NO_RECOVERY_REQUIRED": "continue_gap_analysis",
}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _records_for_contract(project: Mapping[str, Any], contract_id: str) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    seen: set[str] = set()
    for collection_name in ("papergraph", "evidence"):
        collection = project.get(collection_name)
        for record in collection if isinstance(collection, list) else []:
            if not isinstance(record, Mapping):
                continue
            admissions = record.get("gap_source_admissions_v4")
            alignments = record.get("contract_alignment_summaries")
            bound = bool(
                isinstance(admissions, Mapping) and contract_id in admissions
                or isinstance(alignments, Mapping) and contract_id in alignments
                or any(
                    isinstance(binding, Mapping)
                    and _text(binding.get("research_question_contract_id")) == contract_id
                    for binding in record.get("subhypothesis_bindings", [])
                )
            )
            if not bound:
                continue
            identity = _text(record.get("paper_id") or record.get("id")) or f"{collection_name}:{id(record)}"
            if identity in seen:
                continue
            seen.add(identity)
            output.append(dict(record))
    return output


def _diagnostic_lineage_missing(
    diagnostics: Iterable[Mapping[str, Any]],
    *,
    contract_id: str,
    sub_hypothesis_id: str,
) -> bool:
    for diagnostic in diagnostics:
        if not isinstance(diagnostic, Mapping):
            continue
        diagnostic_contract = _text(diagnostic.get("research_question_contract_id"))
        diagnostic_sub = _text(diagnostic.get("sub_hypothesis_id"))
        if diagnostic_contract and diagnostic_contract != contract_id:
            continue
        if diagnostic_sub and diagnostic_sub != sub_hypothesis_id:
            continue
        reason = " ".join((
            _text(diagnostic.get("reason")),
            _text(diagnostic.get("reason_code")),
            _text(diagnostic.get("detail")),
        )).upper()
        if any(token in reason for token in (
            "LINEAGE_MISSING",
            "SOURCE_SPAN_ARTIFACT_MISSING",
            "ASSERTION_PROVENANCE_INCOMPLETE",
            "ASSERTION_DOCUMENT_ARTIFACT_MISSING",
            "ASSERTION_SPAN_DOCUMENT_MISMATCH",
        )):
            return True
    return False


def classify_evidence_recovery(
    project: Mapping[str, Any],
    branch_state: Mapping[str, Any],
    *,
    diagnostics: Iterable[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    contract_id = _text(branch_state.get("research_question_contract_id"))
    sub_hypothesis_id = _text(branch_state.get("sub_hypothesis_id"))
    missing_slots = sorted({
        _text(item) for item in branch_state.get("missing_direct_slot_ids", [])
        if _text(item)
    })
    audits = project.get("research_contract_coherence_audits_v3")
    audit = audits.get(sub_hypothesis_id) if isinstance(audits, Mapping) else {}
    audit = audit if isinstance(audit, Mapping) else {}
    records = _records_for_contract(project, contract_id)
    admissions = [
        record["gap_source_admissions_v4"][contract_id]
        for record in records
        if isinstance(record.get("gap_source_admissions_v4"), Mapping)
        and isinstance(record["gap_source_admissions_v4"].get(contract_id), Mapping)
    ]
    extraction_rows = [
        record["document_proposition_summary"]
        for record in records
        if isinstance(record.get("document_proposition_summary"), Mapping)
        and record["document_proposition_summary"].get("schema_version")
        == "document_proposition_summary_v2"
    ]
    alignment_rows = [
        record["contract_alignment_summaries"][contract_id]
        for record in records
        if isinstance(record.get("contract_alignment_summaries"), Mapping)
        and isinstance(record["contract_alignment_summaries"].get(contract_id), Mapping)
        and record["contract_alignment_summaries"][contract_id].get("schema_version")
        == "contract_alignment_summary_v2"
    ]
    off_topic_rejections = sum(
        admission.get("admission_level") == "HARD_REJECT"
        and "OFF_TOPIC" in set(admission.get("reason_codes") or [])
        for admission in admissions
    )
    direct_admissions = sum(
        admission.get("admission_level") == "DIRECT_EVIDENCE"
        for admission in admissions
    )
    structuring_invalid = any(
        any(
            "STRUCTUR" in _text(code).upper()
            or "SECTION" in _text(code).upper()
            for code in extraction.get("reason_codes", [])
        )
        for extraction in extraction_rows
    )
    extraction_pending = any(
        _text(extraction.get("status")) in {
            "PROPOSITION_PARTIAL", "COMPOSITION_PENDING", "LLM_DISABLED",
            "LLM_EXTRACTION_PENDING", "LLM_BATCH_TIMEOUT",
            "LLM_PROTOCOL_INVALID", "SOURCE_CORRUPTED",
        }
        for extraction in extraction_rows
    )
    rejected_candidate_count = sum(
        int(extraction.get("rejected_candidate_count") or 0) or len([
            item for item in extraction.get("rejected_candidates", [])
            if isinstance(item, Mapping)
            and _text(item.get("validator_verdict")).startswith("REJECTED")
        ])
        for extraction in extraction_rows
    )
    verified_proposition_count = sum(
        int(extraction.get("verified_proposition_count") or 0) or len([
            item for item in extraction.get("propositions", [])
            if isinstance(item, Mapping)
            and item.get("validator_verdict") == "ACCEPTED_SOURCE_BOUND"
        ])
        for extraction in extraction_rows
    )
    alignment_pending = any(
        _text(alignment.get("status")) == "SLOT_ALIGNMENT_PENDING"
        for alignment in alignment_rows
    )
    lineage_missing = _diagnostic_lineage_missing(
        diagnostics,
        contract_id=contract_id,
        sub_hypothesis_id=sub_hypothesis_id,
    )

    if _text(audit.get("status")) == "CONTRACT_SCOPE_INCOHERENT":
        failure_type = "CONTRACT_SCOPE_INCOHERENT"
    elif _text(audit.get("status")) == "COHERENCE_PENDING":
        failure_type = "CONTRACT_COHERENCE_PENDING"
    elif off_topic_rejections and direct_admissions == 0 and off_topic_rejections * 2 >= max(1, len(admissions)):
        failure_type = "CORPUS_OFF_TOPIC_DOMINANT"
    elif structuring_invalid:
        failure_type = "FULLTEXT_STRUCTURE_INVALID"
    elif extraction_pending:
        failure_type = "LLM_EXTRACTION_PENDING"
    elif rejected_candidate_count and verified_proposition_count == 0:
        failure_type = "ASSERTION_VALIDATION_FAILURE"
    elif lineage_missing:
        failure_type = "LINEAGE_MISSING"
    elif alignment_pending:
        failure_type = "SLOT_ALIGNMENT_FAILURE"
    elif missing_slots:
        failure_type = "GENUINE_SLOT_SHORTAGE"
    else:
        failure_type = "NO_RECOVERY_REQUIRED"
    return {
        "schema_version": EVIDENCE_RECOVERY_SCHEMA_VERSION,
        "sub_hypothesis_id": sub_hypothesis_id,
        "research_question_contract_id": contract_id,
        "failure_type": failure_type,
        "next_action": RECOVERY_ACTIONS[failure_type],
        "slot_directed_retrieval_allowed": failure_type == "GENUINE_SLOT_SHORTAGE",
        "scientific_conclusion_allowed": failure_type == "NO_RECOVERY_REQUIRED",
        "missing_direct_slot_ids": missing_slots,
        "diagnostics": {
            "bound_record_count": len(records),
            "admission_count": len(admissions),
            "off_topic_rejection_count": off_topic_rejections,
            "direct_admission_count": direct_admissions,
            "rejected_proposition_candidate_count": rejected_candidate_count,
            "verified_proposition_count": verified_proposition_count,
            "alignment_pending_count": sum(
                _text(item.get("status")) == "SLOT_ALIGNMENT_PENDING"
                for item in alignment_rows
            ),
            "lineage_missing": lineage_missing,
        },
    }
