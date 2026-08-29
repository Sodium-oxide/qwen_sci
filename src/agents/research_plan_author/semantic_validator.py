"""Cross-section semantic validation for a proposal-only Research Plan document."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any

from .contracts import AUTHORING_LANGUAGE, validate_research_plan_document
from .latex_safety import contains_non_english_script, contains_observed_result_language
from .section_router import required_route_ids


_FORMAL_CLAIMS = {
    "formal_definition",
    "formal_proposition",
    "proof_obligation",
    "forward_derivation",
    "counterexample_plan",
}
_CRITICAL_METHOD_FIELDS = {"sample_size", "sampling", "calibration", "eligibility", "endpoint", "statistics"}
_EVIDENCE_REQUIRED_CLAIMS = {"background", "survey_evidence", "research_gap"}


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _text(value: object) -> str:
    return str(value or "").strip()


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def validate_composed_research_plan(
    document: object,
    *,
    preparation: Mapping[str, Any],
    routing: Mapping[str, Any],
    source_registry: Mapping[str, Any],
) -> list[str]:
    """Reject silent source loss, observed results, and semantic evidence upgrades."""

    errors = validate_research_plan_document(document)
    if not isinstance(document, Mapping):
        return errors
    payload = dict(document)
    if payload.get("document_status") != "PROPOSAL_NO_OBSERVED_RESULTS":
        errors.append("composed document must remain PROPOSAL_NO_OBSERVED_RESULTS")
    if payload.get("language") != AUTHORING_LANGUAGE:
        errors.append("composed document language must be English")
    metadata = _mapping(payload.get("document_metadata"))
    for text_field in (metadata.get("title"), payload.get("abstract", {}).get("text") if isinstance(payload.get("abstract"), Mapping) else ""):
        if contains_non_english_script(text_field):
            errors.append("composed document contains non-English-script visible prose")
        if contains_observed_result_language(text_field):
            errors.append("composed document presents an observed result in visible prose")
    all_sections = [
        section
        for section in [*(payload.get("sections") or []), *(payload.get("appendices") or [])]
        if isinstance(section, Mapping)
    ]
    section_ids = {_text(section.get("section_id")) for section in all_sections}
    required_ids = set(required_route_ids(routing))
    if "abstract" in required_ids:
        abstract = _mapping(payload.get("abstract"))
        if not _text(abstract.get("text")):
            errors.append("composed document omits required abstract content")
        elif not {_text(claim_id) for claim_id in abstract.get("claim_ids") or [] if _text(claim_id)}:
            errors.append("composed document abstract must reference at least one claim ID")
        required_ids.remove("abstract")
    missing = required_ids - section_ids
    if missing:
        errors.append(f"composed document omits required routed sections: {sorted(missing)}")
    claims = [claim for claim in payload.get("claim_provenance") or [] if isinstance(claim, Mapping)]
    claim_ids = [_text(claim.get("claim_id")) for claim in claims]
    if len(claim_ids) != len(set(claim_ids)):
        errors.append("document contains duplicate claim_id values")
    claim_id_set = set(claim_ids)
    for section in all_sections:
        if contains_non_english_script(section.get("title")):
            errors.append(f"section {section.get('section_id')} title contains non-English-script visible prose")
        for block in section.get("blocks") or []:
            if not isinstance(block, Mapping):
                continue
            block_id = _text(block.get("block_id")) or "unnamed"
            block_text = _text(block.get("text"))
            if contains_non_english_script(block_text):
                errors.append(f"section block {block_id} contains non-English-script visible prose")
            if contains_observed_result_language(block_text):
                errors.append(f"section block {block_id} presents an observed result")
            block_claim_ids = {_text(claim_id) for claim_id in block.get("claim_ids") or [] if _text(claim_id)}
            if block_text and not block_claim_ids:
                errors.append(f"section block {block_id} must reference at least one claim ID")
            unknown_claims = block_claim_ids - claim_id_set
            if unknown_claims:
                errors.append(f"section block {block.get('block_id')} references unknown claims")
    allowed_sources = set(source_registry.get("allowed_source_ids") or [])
    allowed_anchors = set(source_registry.get("allowed_survey_anchor_ids") or [])
    cards = _mapping(source_registry.get("evidence_cards_by_id"))
    allowed_card_ids = set(cards)
    citation_keys = {
        _text(record.get("citation_key"))
        for record in payload.get("citation_registry") or []
        if isinstance(record, Mapping)
    }
    formal_ids: set[str] = set()
    frozen = _mapping(_mapping(preparation.get("source_bundle")).get("author_context"))
    plan = _mapping(frozen.get("formal_reasoning"))
    for collection, field in (("definitions", "definition_id"), ("assumptions", "assumption_id"), ("propositions", "proposition_id"), ("proof_obligations", "obligation_id")):
        formal_ids.update(_text(item.get(field)) for item in plan.get(collection) or [] if isinstance(item, Mapping))
    formal_ids.update(_text(item.get("step_id")) for item in _mapping(plan.get("forward_derivation")).get("steps") or [] if isinstance(item, Mapping))
    branch_ids = {
        _text(branch.get("branch_id"))
        for branch in frozen.get("outcome_branches") or []
        if isinstance(branch, Mapping)
    }
    for claim in claims:
        claim_id = _text(claim.get("claim_id"))
        claim_kind = _text(claim.get("claim_kind"))
        qualification = _text(claim.get("qualification"))
        statement = _text(claim.get("statement"))
        if claim_kind == "observed_result" or contains_observed_result_language(statement):
            errors.append(f"claim {claim_id} presents an observed result")
        if claim_kind in _EVIDENCE_REQUIRED_CLAIMS and not (
            claim.get("source_ids") or claim.get("evidence_card_ids") or claim.get("survey_anchor_ids")
        ):
            errors.append(f"claim {claim_id} lacks traceable evidence provenance")
        if contains_non_english_script(statement):
            errors.append(f"claim {claim_id} contains non-English-script visible prose")
        if set(claim.get("source_ids") or []) - allowed_sources:
            errors.append(f"claim {claim_id} has an unregistered source")
        if set(claim.get("survey_anchor_ids") or []) - allowed_anchors:
            errors.append(f"claim {claim_id} has an unregistered survey anchor")
        if set(claim.get("evidence_card_ids") or []) - allowed_card_ids:
            errors.append(f"claim {claim_id} has an unregistered evidence card")
        if set(claim.get("formal_reference_ids") or []) - formal_ids:
            errors.append(f"claim {claim_id} has an unregistered formal reference")
        if set(claim.get("citation_keys") or []) - citation_keys:
            errors.append(f"claim {claim_id} has an invented citation key")
        if claim_kind == "expected_outcome":
            if qualification != "expected_not_observed" or not set(claim.get("outcome_branch_ids") or []):
                errors.append(f"expected outcome claim {claim_id} is not a conditional branch")
            if set(claim.get("outcome_branch_ids") or []) - branch_ids:
                errors.append(f"expected outcome claim {claim_id} references an unknown outcome branch")
        if claim_kind in _FORMAL_CLAIMS:
            if qualification not in {"proposed", "unverified", "not_applicable"}:
                errors.append(f"formal claim {claim_id} is upgraded beyond the upstream verification state")
            if claim.get("evidence_card_ids"):
                errors.append(f"formal claim {claim_id} mixes formal reasoning with empirical evidence")
            if re.search(r"\b(?:verified|proved|proven|proof completed|valid counterexample)\b", statement, re.IGNORECASE):
                errors.append(f"formal claim {claim_id} asserts verification that the proposal has not established")
        elif claim.get("formal_reference_ids"):
            errors.append(f"empirical claim {claim_id} mixes formal reasoning with empirical evidence")
        if qualification == "evidence_backed":
            method_field = _text(claim.get("method_field")).casefold()
            evidence_cards = [cards.get(card_id, {}) for card_id in claim.get("evidence_card_ids") or []]
            if method_field in _CRITICAL_METHOD_FIELDS and any(card.get("evidence_level") != "fulltext" for card in evidence_cards):
                errors.append(f"critical method claim {claim_id} is not backed by full text")
    final_unknowns = payload.get("open_items") if isinstance(payload.get("open_items"), list) else []
    final_reviews = payload.get("review_items") if isinstance(payload.get("review_items"), list) else []
    expected_unknown_ids = {str(item.get("source_item_id") or "") for item in source_registry.get("unknown_items") or [] if isinstance(item, Mapping)}
    expected_review_ids = {str(item.get("source_item_id") or "") for item in source_registry.get("review_items") or [] if isinstance(item, Mapping)}
    final_unknown_id_list = [str(item.get("source_item_id") or "") for item in final_unknowns if isinstance(item, Mapping)]
    final_review_id_list = [str(item.get("source_item_id") or "") for item in final_reviews if isinstance(item, Mapping)]
    final_unknown_ids = set(final_unknown_id_list)
    final_review_ids = set(final_review_id_list)
    if final_unknown_ids != expected_unknown_ids:
        errors.append("composed document dropped or invented an upstream unknown item")
    if final_review_ids != expected_review_ids:
        errors.append("composed document dropped or invented an upstream human-review item")
    if len(final_unknown_id_list) != len(final_unknown_ids) or len(final_review_id_list) != len(final_review_ids):
        errors.append("composed document repeats an upstream unknown or human-review item")
    for item in [*final_unknowns, *final_reviews]:
        if isinstance(item, Mapping) and contains_non_english_script(item.get("text")):
            errors.append("composed document contains a non-English-script unknown or review rendering")
    for item in final_unknowns:
        if isinstance(item, Mapping) and item.get("status") != "needs_human_input":
            errors.append("composed document open_items must use status=needs_human_input")
    for item in final_reviews:
        if isinstance(item, Mapping) and item.get("status") != "review_required":
            errors.append("composed document review_items must use status=review_required")
    if routing.get("template_family") == "mathematics_theory":
        if _mapping(payload.get("source_manifest")).get("theory_sampling_power_status") != "not_applicable":
            errors.append("mathematics/theory sampling and power must be recorded as not_applicable")
        methods_text = " ".join(
            _text(block.get("text"))
            for section in all_sections
            if _text(section.get("section_id")) == "study_design_and_methods"
            for block in section.get("blocks") or []
            if isinstance(block, Mapping)
        ).casefold()
        if ("sample size" in methods_text or "statistical power" in methods_text) and "not applicable" not in methods_text:
            errors.append("mathematics/theory sampling and power must remain not_applicable")
    return sorted(set(errors))


__all__ = ["validate_composed_research_plan"]
