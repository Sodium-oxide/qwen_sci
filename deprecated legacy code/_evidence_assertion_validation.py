"""Minimal provenance validation for source-bound scientific propositions."""

from __future__ import annotations

from typing import Any, Mapping
from uuid import NAMESPACE_URL, uuid5


EVIDENCE_PROPOSITION_SCHEMA_VERSION = "evidence_proposition_v7"
EVIDENCE_ASSERTION_SCHEMA_VERSION = "evidence_assertion_v4"
SOURCE_SPAN_SCHEMA_VERSION = "source_span_v6"


def _text(value: Any) -> str:
    return str(value or "").strip()


def _canonical_claim_role(candidate: Mapping[str, Any]) -> str:
    attribution = _text(candidate.get("attribution")).upper()
    assertion_kind = _text(candidate.get("assertion_kind")).upper()
    if attribution == "CITED_WORK":
        return "CITED_CLAIM"
    if assertion_kind in {"METHOD_DESCRIPTION", "MEASUREMENT_DEFINITION"}:
        return "AUTHOR_METHOD"
    if assertion_kind == "AUTHOR_LIMITATION":
        return "AUTHOR_LIMITATION"
    if attribution == "CURRENT_AUTHORS":
        return "AUTHOR_CLAIM"
    return "UNSPECIFIED_CLAIM"


def _rejected(
    candidate: Mapping[str, Any],
    *,
    verdict: str,
    reason_codes: list[str],
) -> dict[str, Any]:
    return {
        "schema_version": EVIDENCE_PROPOSITION_SCHEMA_VERSION,
        "source_span_id": _text(candidate.get("source_span_id")),
        "canonical_statement": _text(candidate.get("canonical_statement")),
        "validator_verdict": verdict,
        "validator_reason_codes": reason_codes,
        "diagnostic_codes": list(candidate.get("diagnostic_codes") or []),
        "direct_slot_eligible": False,
        "counts_toward_gate": False,
    }


def validate_proposition_candidate(
    candidate: Mapping[str, Any],
    spans_by_id: Mapping[str, Mapping[str, Any]],
    *,
    document_version_hash: str,
    model_id: str,
    prompt_revision: str,
    extraction_run_id: str,
) -> dict[str, Any]:
    """Validate only immutable provenance and the minimal proposition protocol."""

    span_id = _text(candidate.get("source_span_id"))
    span = spans_by_id.get(span_id)
    if not isinstance(span, Mapping):
        return _rejected(
            candidate,
            verdict="REJECTED_PROVENANCE",
            reason_codes=["SOURCE_SPAN_NOT_FOUND"],
        )

    provenance_errors: list[str] = []
    if _text(span.get("schema_version")) != SOURCE_SPAN_SCHEMA_VERSION:
        provenance_errors.append("SOURCE_SPAN_SCHEMA_MISMATCH")
    if _text(span.get("document_version_hash")) != document_version_hash:
        provenance_errors.append("DOCUMENT_VERSION_MISMATCH")
    if _text(span.get("section_disposition")) != "INCLUDED":
        provenance_errors.append("SOURCE_SECTION_EXCLUDED")
    if _text(span.get("source_material_status")) != "SOURCE_BOUND_FULLTEXT":
        provenance_errors.append("SOURCE_MATERIAL_NOT_BOUND_FULLTEXT")

    span_quote = str(span.get("quote") or "")
    exact_quote = str(candidate.get("exact_quote") or "")
    quote_start = candidate.get("quote_char_start")
    quote_end = candidate.get("quote_char_end")
    if not exact_quote:
        provenance_errors.append("SOURCE_EVIDENCE_QUOTE_MISSING")
    elif not isinstance(quote_start, int) or not isinstance(quote_end, int):
        provenance_errors.append("SOURCE_EVIDENCE_OFFSETS_MISSING")
    elif not (0 <= quote_start < quote_end <= len(span_quote)):
        provenance_errors.append("SOURCE_EVIDENCE_OFFSETS_OUT_OF_RANGE")
    elif span_quote[quote_start:quote_end] != exact_quote:
        provenance_errors.append("SOURCE_EVIDENCE_OFFSET_TEXT_MISMATCH")
    if provenance_errors:
        return _rejected(
            candidate,
            verdict="REJECTED_PROVENANCE",
            reason_codes=provenance_errors,
        )

    canonical_statement = _text(candidate.get("canonical_statement"))
    if not canonical_statement:
        return _rejected(
            candidate,
            verdict="REJECTED_PROTOCOL",
            reason_codes=["CANONICAL_STATEMENT_MISSING"],
        )

    llm_proposition_type = _text(candidate.get("proposition_type")).upper()
    llm_assertion_kind = _text(candidate.get("assertion_kind")).upper()
    attribution = _text(candidate.get("attribution")).upper() or "UNSPECIFIED"
    claim_role = _canonical_claim_role(candidate)
    relation_kind = _text(
        candidate.get("canonical_relation") or candidate.get("relation")
    ).upper()
    canonical_subject = _text(candidate.get("canonical_subject"))
    canonical_object = _text(candidate.get("canonical_object"))
    proposition_id = "prop_" + uuid5(
        NAMESPACE_URL,
        "|".join((
            document_version_hash,
            span_id,
            str(quote_start),
            str(quote_end),
            canonical_statement,
            canonical_subject,
            relation_kind,
            canonical_object,
            llm_assertion_kind,
        )),
    ).hex[:24]
    empty_anchor = {"text": "", "source_start": None, "source_end": None}
    source_location = {
        key: span.get(key)
        for key in (
            "source_locator",
            "source_field",
            "section_id",
            "section_heading",
            "section_number",
            "section_disposition",
            "char_start",
            "char_end",
            "page_number",
        )
        if span.get(key) not in {None, ""}
    }
    return {
        "schema_version": EVIDENCE_PROPOSITION_SCHEMA_VERSION,
        "proposition_id": proposition_id,
        "paper_id": _text(span.get("paper_id")),
        "document_version_hash": document_version_hash,
        "source_span_id": span_id,
        "source_span_ids": [span_id],
        "source_unit_ids": [_text(span.get("source_unit_id") or span_id)],
        "exact_quote": exact_quote,
        "quote_char_start": quote_start,
        "quote_char_end": quote_end,
        "canonical_statement": canonical_statement,
        "subject": dict(empty_anchor),
        "predicate": dict(empty_anchor),
        "object": dict(empty_anchor),
        "normalization": {
            "subject": canonical_subject,
            "predicate": relation_kind,
            "object": canonical_object,
        },
        "claim_role": claim_role,
        "proposition_type": llm_proposition_type,
        "llm_proposition_type": llm_proposition_type,
        "assertion_kind": llm_assertion_kind,
        "llm_assertion_kind": llm_assertion_kind,
        "assertion_kinds": [llm_assertion_kind] if llm_assertion_kind else [],
        "relation_kind": relation_kind,
        "polarity": _text(candidate.get("polarity")).upper() or "UNSPECIFIED",
        "modality": _text(candidate.get("modality")).upper() or "UNSPECIFIED",
        "attribution": attribution,
        "claim_completeness": _text(candidate.get("claim_completeness")).upper(),
        "claim_scope": _text(candidate.get("claim_scope")).upper(),
        "extraction_profile": _text(candidate.get("extraction_profile")).upper(),
        "specialized_fields": dict(candidate.get("specialized_fields") or {}),
        "structure_anchors": list(candidate.get("structure_anchors") or []),
        "quantities": list(candidate.get("quantities") or []),
        "boundary_conditions": list(candidate.get("boundary_conditions") or []),
        "comparison_arms": list(candidate.get("comparison_arms") or []),
        "limitations": list(candidate.get("limitations") or []),
        "section_heading": _text(span.get("section_heading")),
        "section_disposition": _text(span.get("section_disposition")),
        "source_material_status": _text(span.get("source_material_status")),
        "textual_explicitness": "EXPLICIT",
        "assertion_origin": "SOURCE_EXPLICIT",
        "derivation_status": "NOT_DERIVED",
        "extraction_method": "llm_source_bound_proposition_v1",
        "model_id": model_id,
        "prompt_revision": prompt_revision,
        "extraction_run_id": extraction_run_id,
        "validator_verdict": "ACCEPTED_SOURCE_BOUND",
        "validator_reason_codes": [],
        "diagnostic_codes": list(dict.fromkeys(
            str(item) for item in candidate.get("diagnostic_codes", []) if str(item)
        )),
        "direct_slot_eligible": False,
        "counts_toward_gate": False,
        "source_grounding": dict(candidate.get("source_grounding") or {}),
        "source_locations": [source_location],
    }
