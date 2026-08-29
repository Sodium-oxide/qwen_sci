"""Build deterministic citation and source identifiers from frozen Author inputs."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from typing import Any, Mapping


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _text(value: object) -> str:
    return str(value or "").strip()


def _append_unique(records: list[dict[str, Any]], record: dict[str, Any], *, key: str) -> None:
    value = _text(record.get(key))
    if value and not any(_text(existing.get(key)) == value for existing in records):
        records.append(record)


def _citation_key(source_id: str) -> str:
    """Keep BibTeX keys stable and syntax-safe without exposing a raw URL/DOI."""

    digest = hashlib.sha256(source_id.encode("utf-8")).hexdigest()[:16]
    return f"cite_{digest}"


def _source_items(items: object, *, prefix: str) -> list[dict[str, Any]]:
    values = items if isinstance(items, list) else []
    records: list[dict[str, Any]] = []
    for index, item in enumerate(values, start=1):
        canonical = json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
        records.append(
            {
                "source_item_id": f"{prefix}-{index}",
                "source_item_sha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
                "original_item": deepcopy(item),
            }
        )
    return records


def build_frozen_source_registry(preparation: Mapping[str, Any]) -> dict[str, Any]:
    """Expose only already-known identifiers; an LLM cannot mint bibliography data."""

    bundle = _mapping(preparation.get("source_bundle"))
    handoff = _mapping(bundle.get("author_context"))
    compact = _mapping(handoff.get("source_registry"))
    evidence_cards_by_id = {
        str(card_id): deepcopy(dict(card))
        for card_id, card in (_mapping(compact.get("evidence_cards_by_id"))).items()
        if isinstance(card, Mapping)
    }
    allowed_source_ids = [
        _text(source_id)
        for source_id in compact.get("allowed_source_ids") or []
        if _text(source_id)
    ]
    citations = [
        deepcopy(dict(citation))
        for citation in compact.get("citation_registry") or []
        if isinstance(citation, Mapping)
    ]
    survey_sources = _mapping(bundle.get("survey_sources"))
    survey_artifacts = _mapping(survey_sources.get("artifacts"))
    survey_anchor_ids = [f"survey:{name}" for name in sorted(survey_artifacts)]
    survey_markdown = _mapping(survey_artifacts.get("survey_markdown"))
    for excerpt in survey_markdown.get("excerpts") or []:
        if not isinstance(excerpt, Mapping):
            continue
        anchor_id = _text(excerpt.get("anchor_id"))
        if anchor_id.startswith("survey:survey_markdown#") and anchor_id not in survey_anchor_ids:
            survey_anchor_ids.append(anchor_id)
    unknown_items = _source_items(handoff.get("unknown_items"), prefix="unknown")
    review_items = _source_items(handoff.get("review_items"), prefix="review")
    return {
        "schema_version": "research_plan_author_source_registry_v2",
        "allowed_source_ids": allowed_source_ids,
        "allowed_survey_anchor_ids": survey_anchor_ids,
        "evidence_cards_by_id": evidence_cards_by_id,
        "citation_registry": deepcopy(citations),
        "unknown_items": unknown_items,
        "review_items": review_items,
    }


def source_registry_for_route(source_registry: Mapping[str, Any], route: Mapping[str, Any]) -> dict[str, Any]:
    """Return only evidence metadata relevant to one routed section."""

    section_id = _text(route.get("section_id")).casefold()
    evidence_slots_by_section = {
        "references": None,
        "appendix_evidence_and_review": None,
        "survey_and_research_gap": None,
        "introduction": {"background", "research_gap", "mechanism", "research_object_measurability"},
        "abstract": set(),
        "research_questions_and_contributions": set(),
        "idea_origin_and_selection": set(),
        "formal_problem_and_hypotheses": set(),
        "expected_outcomes": set(),
        "risk_limitations_and_review": {"risk_ethics_reproducibility", "boundary_conditions"},
        "appendix_idea_evolution": set(),
        "appendix_variables_and_definitions": {"research_object_measurability", "study_design"},
        "computational_evaluation_protocol": {"study_design", "comparison_controls", "boundary_conditions", "statistics_bias"},
        "materials_and_characterization": {"study_design", "measurement_calibration", "comparison_controls", "boundary_conditions"},
        "system_boundary_and_validation": {"study_design", "measurement_calibration", "comparison_controls", "boundary_conditions", "risk_ethics_reproducibility"},
        "spatiotemporal_design": {"study_design", "measurement_calibration", "boundary_conditions"},
        "model_controls_and_repeats": {"study_design", "measurement_calibration", "comparison_controls", "risk_ethics_reproducibility"},
        "pico_endpoints_and_governance": {"study_design", "measurement_calibration", "risk_ethics_reproducibility", "statistics_bias"},
        "definitions_and_propositions": set(),
        "forward_derivation_and_counterexamples": set(),
    }
    slot_filter = evidence_slots_by_section.get(section_id, set())
    all_cards = _mapping(source_registry.get("evidence_cards_by_id"))
    selected = (
        dict(all_cards)
        if slot_filter is None
        else {
            card_id: card
            for card_id, card in all_cards.items()
            if _text(_mapping(card).get("claim_slot")).casefold() in slot_filter
        }
    )
    selected_sources = {_text(_mapping(card).get("source_id")) for card in selected.values()}
    survey_route = section_id == "survey_and_research_gap"
    citations = [
        deepcopy(dict(citation))
        for citation in source_registry.get("citation_registry") or []
        if _text(_mapping(citation).get("source_id")) in selected_sources
    ]
    return {
        "schema_version": _text(source_registry.get("schema_version")),
        "allowed_source_ids": [
            source_id for source_id in source_registry.get("allowed_source_ids") or []
            if source_id in selected_sources
        ],
        "allowed_survey_anchor_ids": list(source_registry.get("allowed_survey_anchor_ids") or []) if survey_route else [],
        "evidence_cards_by_id": selected,
        "citation_registry": citations,
        "unknown_items": deepcopy(list(source_registry.get("unknown_items") or [])),
        "review_items": deepcopy(list(source_registry.get("review_items") or [])),
    }


def source_registry_for_blueprint_section(
    source_registry: Mapping[str, Any],
    route: Mapping[str, Any],
    blueprint_section: Mapping[str, Any],
) -> dict[str, Any]:
    """Apply a route-scoped Blueprint source selection before prose composition."""

    routed = source_registry_for_route(source_registry, route)
    selected_source_ids = {
        _text(source_id)
        for source_id in blueprint_section.get("allowed_source_ids") or []
        if _text(source_id)
    }
    cards = {
        card_id: card
        for card_id, card in _mapping(routed.get("evidence_cards_by_id")).items()
        if _text(_mapping(card).get("source_id")) in selected_source_ids
    }
    citations = [
        deepcopy(dict(citation))
        for citation in routed.get("citation_registry") or []
        if isinstance(citation, Mapping) and _text(citation.get("source_id")) in selected_source_ids
    ]
    return {
        **routed,
        "allowed_source_ids": [
            source_id for source_id in routed.get("allowed_source_ids") or [] if source_id in selected_source_ids
        ],
        "evidence_cards_by_id": cards,
        "citation_registry": citations,
    }


__all__ = [
    "build_frozen_source_registry",
    "source_registry_for_blueprint_section",
    "source_registry_for_route",
]
