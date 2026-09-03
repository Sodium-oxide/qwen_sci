"""Domain-independent mature-idea independence and route-signature helpers."""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Mapping, Sequence, Tuple

from src.agents.idea_agent.utils.workflow.idea_contract import normalize_mature_ideas


_STRUCTURAL_FIELDS: Tuple[str, ...] = (
    "scientific_object",
    "assumptions",
    "mechanism_or_relation",
    "mechanism",
    "intervention_or_transformation",
    "representation",
    "theory_representation",
    "falsifier",
    "target_gap_ids",
)


def _tokens(value: Any) -> set[str]:
    if isinstance(value, Mapping):
        value = " ".join(f"{key} {item}" for key, item in value.items())
    elif isinstance(value, (list, tuple, set)):
        value = " ".join(str(item) for item in value)
    text = str(value or "").casefold()
    return {
        token
        for token in re.findall(r"[a-z0-9_\u0080-\uffff]+", text)
        if token
    }


def _similarity(left: Any, right: Any) -> float:
    left_tokens = _tokens(left)
    right_tokens = _tokens(right)
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / max(1, len(left_tokens | right_tokens))


def build_mature_idea_route_signature(idea: Mapping[str, Any]) -> Dict[str, Any]:
    """Build a structural signature; titles and prose are intentionally excluded."""

    return {
        field: idea.get(field)
        for field in _STRUCTURAL_FIELDS
        if idea.get(field) not in (None, "", [], {}, ())
    }


def compare_mature_ideas(
    left: Mapping[str, Any],
    right: Mapping[str, Any],
) -> Dict[str, Any]:
    """Return field-level structural overlap and a conservative duplicate decision."""

    scores: Dict[str, float] = {}
    for field in _STRUCTURAL_FIELDS:
        left_value = left.get(field)
        right_value = right.get(field)
        if left_value in (None, "", [], {}, ()) or right_value in (None, "", [], {}, ()):
            continue
        scores[field] = _similarity(left_value, right_value)

    textual_scores = {
        "title": _similarity(left.get("title"), right.get("title")),
        "hypothesis": _similarity(left.get("hypothesis") or left.get("central_hypothesis"), right.get("hypothesis") or right.get("central_hypothesis")),
    }

    populated = list(scores.values())
    high_overlap = {field for field, score in scores.items() if score >= 0.72}
    causal_fields = {
        "scientific_object",
        "mechanism_or_relation",
        "mechanism",
        "intervention_or_transformation",
        "representation",
    }
    causal_overlap = sum(1 for field in causal_fields if scores.get(field, 0.0) >= 0.72)
    same_gaps = scores.get("target_gap_ids", 0.0) >= 0.85
    duplicate = bool(
        causal_overlap >= 2 and (same_gaps or causal_overlap >= 3)
        or causal_overlap >= 3 and len(populated) >= 3
        or len(high_overlap) >= 5
        or not populated and max(textual_scores.values(), default=0.0) >= 0.85
    )
    if duplicate:
        rationale = (
            "Collapsed as a rephrasing: the scientific object, causal mechanism, "
            "and intervention/representation overlap without a distinct route."
        )
    elif not scores:
        rationale = "Retained provisionally because no comparable structural fields were supplied."
    else:
        distinct = [field for field in causal_fields if scores.get(field, 0.0) < 0.72]
        rationale = "Retained as structurally distinct in: " + ", ".join(distinct or ["falsifier or target gaps"])
    return {
        "duplicate": duplicate,
        "field_similarity": scores,
        "overlap_fields": sorted(high_overlap),
        "rationale": rationale,
    }


def filter_independent_mature_ideas(
    ideas: Any,
    *,
    return_rejected: bool = False,
) -> Any:
    """Keep mature ideas that differ in at least one substantive structural dimension."""

    normalized = normalize_mature_ideas(ideas)
    accepted: List[Dict[str, Any]] = []
    rejected: List[Dict[str, Any]] = []
    for candidate in normalized:
        candidate = dict(candidate)
        candidate["route_signature"] = build_mature_idea_route_signature(candidate)
        comparisons = [compare_mature_ideas(candidate, prior) for prior in accepted]
        duplicate_index = next(
            (index for index, item in enumerate(comparisons) if item["duplicate"]),
            None,
        )
        duplicate_match = comparisons[duplicate_index] if duplicate_index is not None else None
        if duplicate_match is not None:
            candidate["independence_rationale"] = duplicate_match["rationale"]
            candidate["independence_status"] = "collapsed_duplicate"
            canonical = accepted[duplicate_index]
            related = canonical.setdefault("source_lineage", [])
            if not isinstance(related, list):
                related = [related]
                canonical["source_lineage"] = related
            related.append(
                {
                    "idea_source": candidate.get("idea_source"),
                    "idea_id": candidate.get("idea_id"),
                    "lineage": candidate.get("lineage"),
                }
            )
            rejected.append(candidate)
            continue
        if comparisons:
            candidate["independence_rationale"] = next(
                (item["rationale"] for item in comparisons if not item["duplicate"]),
                "Retained as an independent mature idea.",
            )
        else:
            candidate["independence_rationale"] = "First mature idea in the collection."
        candidate["independence_status"] = "independent"
        accepted.append(candidate)

    if return_rejected:
        return {"accepted": accepted, "rejected": rejected}
    return accepted


def deduplicate_mature_ideas(ideas: Any) -> List[Dict[str, Any]]:
    """Compatibility alias for callers that use deduplication terminology."""

    return filter_independent_mature_ideas(ideas)
