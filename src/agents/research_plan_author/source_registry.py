"""Build a global, source-bounded knowledge base for Research Plan Authoring."""

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
    """Expose every already-known source; an LLM cannot mint bibliography data."""

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
        "schema_version": "research_plan_author_source_registry_v3",
        "allowed_source_ids": allowed_source_ids,
        "allowed_survey_anchor_ids": survey_anchor_ids,
        "evidence_cards_by_id": evidence_cards_by_id,
        "citation_registry": deepcopy(citations),
        "unknown_items": unknown_items,
        "review_items": review_items,
    }


_RECOMMENDED_SLOTS_BY_SECTION = {
    "introduction": {"research_object_measurability", "mechanism", "boundary_conditions"},
    "survey_and_research_gap": {"research_object_measurability", "mechanism", "boundary_conditions"},
    "study_design_and_methods": {
        "study_design",
        "measurement_calibration",
        "comparison_controls",
        "statistics_bias",
    },
    "computational_evaluation_protocol": {
        "study_design",
        "measurement_calibration",
        "comparison_controls",
        "statistics_bias",
    },
    "expected_outcomes": {"mechanism", "comparison_controls", "statistics_bias"},
    "risk_limitations_and_review": {"risk_ethics_reproducibility", "boundary_conditions"},
    "appendix_evidence_and_review": None,
}


def build_authoring_knowledge_base(
    preparation: Mapping[str, Any],
    source_registry: Mapping[str, Any],
) -> dict[str, Any]:
    """Assemble every frozen upstream artifact into one writer-visible knowledge base.

    The knowledge base is deliberately broader than a route recommendation.  It
    preserves provenance by exposing canonical IDs and metadata, but it never
    turns an evidence slot into a permission boundary for scholarly synthesis.
    """

    bundle = _mapping(preparation.get("source_bundle"))
    author_context = _mapping(bundle.get("author_context"))
    return {
        "schema_version": "research_plan_authoring_knowledge_base_v1",
        "theory_spine": deepcopy(_mapping(preparation.get("theory_spine"))),
        "source_catalog": {
            "allowed_source_ids": list(source_registry.get("allowed_source_ids") or []),
            "citation_registry": deepcopy(list(source_registry.get("citation_registry") or [])),
            "evidence_cards_by_id": deepcopy(_mapping(source_registry.get("evidence_cards_by_id"))),
            "survey_anchor_ids": list(source_registry.get("allowed_survey_anchor_ids") or []),
        },
        "upstream_artifacts": {
            "selected_direction": deepcopy(author_context.get("selected_direction")),
            "research_design": deepcopy(author_context.get("research_design")),
            "hypothesis_mapping": deepcopy(author_context.get("hypothesis_mapping")),
            "formal_reasoning": deepcopy(author_context.get("formal_reasoning")),
            "counterexample_analysis": deepcopy(author_context.get("counterexample_analysis")),
            "outcome_branches": deepcopy(author_context.get("outcome_branches")),
            "reasoning_context": deepcopy(author_context.get("reasoning_context")),
            "variables_and_operationalization": deepcopy(author_context.get("variables_and_operationalization")),
            "idea_evolution": deepcopy(_mapping(bundle.get("idea_evolution"))),
            "survey_binding": deepcopy(_mapping(bundle.get("survey_binding"))),
        },
        "unknown_items": deepcopy(list(source_registry.get("unknown_items") or [])),
        "review_items": deepcopy(list(source_registry.get("review_items") or [])),
    }


def source_registry_for_route(source_registry: Mapping[str, Any], route: Mapping[str, Any]) -> dict[str, Any]:
    """Return the global catalog plus non-binding relevance recommendations.

    Earlier versions used ``claim_slot`` to hide sources from most sections.
    That made source traceability a writing prohibition and caused shallow,
    repetitive prose.  The writer may now use any canonical source; slots only
    help it start from a sensible evidence cluster.
    """

    section_id = _text(route.get("section_id")).casefold()
    recommended_slots = _RECOMMENDED_SLOTS_BY_SECTION.get(section_id, set())
    cards = _mapping(source_registry.get("evidence_cards_by_id"))
    if recommended_slots is None:
        recommended_source_ids = list(source_registry.get("allowed_source_ids") or [])
    else:
        recommended_source_ids = sorted(
            {
                _text(_mapping(card).get("source_id"))
                for card in cards.values()
                if _text(_mapping(card).get("source_id"))
                and _text(_mapping(card).get("claim_slot")).casefold() in recommended_slots
            }
        )
    return {
        "schema_version": _text(source_registry.get("schema_version")),
        "allowed_source_ids": list(source_registry.get("allowed_source_ids") or []),
        "allowed_survey_anchor_ids": list(source_registry.get("allowed_survey_anchor_ids") or []),
        "evidence_cards_by_id": deepcopy(cards),
        "citation_registry": deepcopy(list(source_registry.get("citation_registry") or [])),
        "unknown_items": deepcopy(list(source_registry.get("unknown_items") or [])),
        "review_items": deepcopy(list(source_registry.get("review_items") or [])),
        "recommended_source_ids": recommended_source_ids,
        "recommended_claim_slots": sorted(recommended_slots or set()),
        "authoring_knowledge_base": deepcopy(_mapping(source_registry.get("authoring_knowledge_base"))),
    }


def source_registry_for_blueprint_section(
    source_registry: Mapping[str, Any],
    route: Mapping[str, Any],
    blueprint_section: Mapping[str, Any],
) -> dict[str, Any]:
    """Preserve global source access after Blueprint planning.

    ``allowed_source_ids`` in historic Blueprint artifacts is retained only for
    cache compatibility and observability.  It must never narrow the sources
    available to the section writer.
    """

    return source_registry_for_route(source_registry, route)


__all__ = [
    "build_frozen_source_registry",
    "build_authoring_knowledge_base",
    "source_registry_for_blueprint_section",
    "source_registry_for_route",
]
