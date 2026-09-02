"""Domain-neutral set-level coverage contracts for objective decomposition.

The LLM proposes scientific direction axes and a deliberately over-complete
candidate pool.  This module does not decide which domain concepts matter; it
only normalizes the declared axes, builds an auditable coverage matrix, and
selects a small set that maximizes coverage, scale diversity, and independence.
"""
from __future__ import annotations

from copy import deepcopy
from itertools import combinations
from typing import Any
import re


DIRECTION_AXIS_TYPES = frozenset({
    "mechanism",
    "material_or_composition",
    "method_or_computation",
    "data_or_measurement",
    "experimental_context",
    "scale",
    "cross_scale_transition",
    "translation_or_deployment",
    "system_integration",
    "boundary_or_failure",
    "outcome",
    "comparator",
    "other",
})
SCALE_CLASSES = frozenset({"micro", "meso", "macro", "cross_scale", "unspecified"})
COVERAGE_STRENGTHS = {"none": 0.0, "partial": 0.5, "full": 1.0}
_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{1,}")
_GENERIC_TOKENS = frozenset({
    "and", "or", "the", "a", "an", "to", "of", "for", "in", "on", "with",
    "without", "under", "between", "from", "by", "as", "at", "into", "across",
    "effect", "effects", "impact", "role", "study", "research", "analysis",
    "mechanism", "mechanisms", "outcome", "outcomes", "system", "systems",
})


def _text(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def _slug(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "_", _text(value).lower()).strip("_")


def normalize_direction_axes(
    raw_axes: Any,
    *,
    reframing_axes: Any = None,
    limit: int = 16,
) -> list[dict[str, Any]]:
    """Normalize model-extracted source directions without domain vocabulary."""

    source_items: list[Any] = list(raw_axes) if isinstance(raw_axes, list) else []
    if not source_items and isinstance(reframing_axes, list):
        source_items.extend(
            {
                "label": _text(item),
                "description": _text(item),
                "axis_type": "other",
                "importance": 3,
                "independence_required": False,
                "source": "academic_reframing",
            }
            for item in reframing_axes
            if _text(item)
        )
    axes: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in source_items:
        item = raw if isinstance(raw, dict) else {"label": raw}
        label = _text(item.get("label") or item.get("name") or item.get("direction"))
        description = _text(
            item.get("description")
            or item.get("scientific_direction")
            or item.get("scope")
            or label
        )
        if not label:
            continue
        key = _slug(label)
        if not key or key in seen:
            continue
        seen.add(key)
        axis_type = _slug(item.get("axis_type") or item.get("type") or "other")
        if axis_type not in DIRECTION_AXIS_TYPES:
            axis_type = "other"
        scale = _slug(item.get("scale") or "unspecified")
        if scale not in SCALE_CLASSES:
            scale = "unspecified"
        try:
            importance = max(1, min(5, int(item.get("importance") or 3)))
        except (TypeError, ValueError):
            importance = 3
        axes.append({
            "id": f"AX{len(axes) + 1}",
            "source_id": _text(item.get("id") or item.get("axis_id")),
            "label": label,
            "description": description,
            "axis_type": axis_type,
            "scale": scale,
            "importance": importance,
            "independence_required": bool(item.get("independence_required")),
            "source_excerpt": _text(
                item.get("source_excerpt")
                or item.get("source_text")
                or item.get("evidence")
            ),
            "source": _text(item.get("source") or "objective_direction_extractor"),
        })
        if len(axes) >= max(1, int(limit or 16)):
            break
    return axes


def normalize_direction_coverage_claims(value: Any) -> list[dict[str, Any]]:
    """Normalize candidate-declared axis coverage for later deterministic use."""

    claims: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in value if isinstance(value, list) else []:
        item = raw if isinstance(raw, dict) else {}
        axis_id = _text(item.get("axis_id") or item.get("id")).upper()
        if not axis_id or axis_id in seen:
            continue
        strength = _slug(item.get("coverage_strength") or item.get("strength") or "none")
        if strength not in COVERAGE_STRENGTHS:
            strength = "none"
        seen.add(axis_id)
        claims.append({
            "axis_id": axis_id,
            "coverage_strength": strength,
            "rationale": _text(item.get("rationale") or item.get("reason")),
        })
    return claims


def _candidate_text(candidate: dict[str, Any]) -> str:
    values: list[str] = []
    for key in (
        "focus",
        "scientific_object",
        "independent_variable",
        "comparison",
        "baseline_or_comparator",
        "retrieval_query",
    ):
        values.append(_text(candidate.get(key)))
    for key in ("causal_chain", "dependent_variables", "moderators"):
        raw = candidate.get(key)
        if isinstance(raw, list):
            values.extend(_text(item) for item in raw)
    return " ".join(value for value in values if value)


def _tokens(value: Any) -> set[str]:
    return {
        token.lower()
        for token in _TOKEN_PATTERN.findall(_text(value))
        if token.lower() not in _GENERIC_TOKENS
    }


def _lexical_axis_support(candidate: dict[str, Any], axis: dict[str, Any]) -> float:
    axis_tokens = _tokens(
        " ".join([
            _text(axis.get("label")),
            _text(axis.get("description")),
            _text(axis.get("source_excerpt")),
        ])
    )
    if not axis_tokens:
        return 0.0
    overlap = len(axis_tokens & _tokens(_candidate_text(candidate))) / len(axis_tokens)
    if overlap >= 0.60:
        return 1.0
    if overlap >= 0.25:
        return 0.5
    return 0.0


def build_candidate_direction_coverage_matrix(
    candidates: list[dict[str, Any]],
    axes: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build the auditable candidate × source-direction coverage matrix."""

    rows: list[dict[str, Any]] = []
    values: dict[str, dict[str, float]] = {}
    for index, candidate in enumerate(candidates):
        candidate_id = _text(candidate.get("candidate_id")) or f"C{index + 1}"
        claims = {
            _text(item.get("axis_id")).upper(): item
            for item in normalize_direction_coverage_claims(
                candidate.get("direction_coverage")
            )
        }
        cells: list[dict[str, Any]] = []
        values[candidate_id] = {}
        for axis in axes:
            axis_id = _text(axis.get("id")).upper()
            source_id = _text(axis.get("source_id")).upper()
            claim = claims.get(axis_id) or (claims.get(source_id) if source_id else None)
            declared = (
                COVERAGE_STRENGTHS.get(_slug(claim.get("coverage_strength")), 0.0)
                if isinstance(claim, dict)
                else 0.0
            )
            lexical = _lexical_axis_support(candidate, axis)
            # Explicit source-axis mapping is authoritative; lexical matching
            # can only recover an omitted mapping as partial, never manufacture
            # full coverage.
            strength = declared if claim else min(0.5, lexical)
            values[candidate_id][axis_id] = strength
            cells.append({
                "axis_id": axis_id,
                "coverage_strength": (
                    "full" if strength >= 1.0 else "partial" if strength > 0.0 else "none"
                ),
                "score": strength,
                "source": "candidate_declared" if claim else "lexical_fallback",
                "rationale": _text(claim.get("rationale")) if claim else "",
            })
        preflight = (
            candidate.get("scientific_operationality_preflight")
            if isinstance(candidate.get("scientific_operationality_preflight"), dict)
            else {}
        )
        rows.append({
            "candidate_id": candidate_id,
            "focus": _text(candidate.get("focus")),
            "scale": _slug(candidate.get("scale") or "unspecified"),
            "operationality": _text(preflight.get("status") or "unknown"),
            "cells": cells,
        })
    return {
        "schema_version": "decomposition_direction_coverage_matrix_v1",
        "axis_ids": [_text(axis.get("id")).upper() for axis in axes],
        "candidate_ids": [row["candidate_id"] for row in rows],
        "rows": rows,
        "values": values,
    }


def _pair_similarity(left: dict[str, Any], right: dict[str, Any]) -> float:
    left_tokens = _tokens(_candidate_text(left))
    right_tokens = _tokens(_candidate_text(right))
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


def _combination_score(
    combo: tuple[dict[str, Any], ...],
    *,
    axes: list[dict[str, Any]],
    matrix_values: dict[str, dict[str, float]],
) -> tuple[float, dict[str, Any]]:
    axis_maxima: dict[str, float] = {}
    weighted_coverage = 0.0
    required_full = 0
    for axis in axes:
        axis_id = _text(axis.get("id")).upper()
        maximum = max(
            (
                matrix_values.get(_text(candidate.get("candidate_id")), {}).get(axis_id, 0.0)
                for candidate in combo
            ),
            default=0.0,
        )
        axis_maxima[axis_id] = maximum
        importance = int(axis.get("importance") or 3)
        weighted_coverage += importance * maximum
        if axis.get("independence_required") and maximum >= 1.0:
            required_full += 1

    scales = {
        _slug(candidate.get("scale") or "unspecified")
        for candidate in combo
        if _slug(candidate.get("scale") or "unspecified") != "unspecified"
    }
    scale_score = len(scales) * 0.75 + (0.75 if "cross_scale" in scales else 0.0)
    similarities = [
        _pair_similarity(left, right)
        for left, right in combinations(combo, 2)
    ]
    independence_penalty = sum(max(0.0, value - 0.22) * 2.5 for value in similarities)
    full_axes = sum(value >= 1.0 for value in axis_maxima.values())
    partial_axes = sum(0.0 < value < 1.0 for value in axis_maxima.values())
    score = (
        weighted_coverage * 10.0
        + full_axes * 4.0
        + partial_axes
        + required_full * 6.0
        + scale_score
        - independence_penalty
    )
    return score, {
        "weighted_direction_coverage": weighted_coverage,
        "full_axis_count": full_axes,
        "partial_axis_count": partial_axes,
        "covered_scales": sorted(scales),
        "independence_penalty": round(independence_penalty, 6),
        "axis_maxima": axis_maxima,
    }


def select_candidate_set(
    candidates: list[dict[str, Any]],
    axes: list[dict[str, Any]],
    matrix: dict[str, Any],
    *,
    final_limit: int = 6,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Select the globally best bounded set; 12 choose 6 is only 924 sets."""

    limit = max(1, int(final_limit or 6))
    ready = [
        candidate
        for candidate in candidates
        if (
            isinstance(candidate.get("scientific_operationality_preflight"), dict)
            and candidate["scientific_operationality_preflight"].get("status") == "ready"
        )
    ]
    eligible = ready or list(candidates)
    choose = min(limit, len(eligible))
    if not choose:
        return [], {
            "schema_version": "decomposition_set_selection_v1",
            "status": "no_eligible_candidates",
            "selected_candidate_ids": [],
        }
    if not axes:
        selected = [deepcopy(item) for item in eligible[:choose]]
        selected_ids = {_text(item.get("candidate_id")) for item in selected}
        return selected, {
            "schema_version": "decomposition_set_selection_v1",
            "status": "selected_without_direction_axes",
            "algorithm": "decomposition_order_fallback_no_axes",
            "candidate_count": len(candidates),
            "operational_candidate_count": len(ready),
            "eligible_candidate_count": len(eligible),
            "combination_count_evaluated": 0,
            "final_limit": limit,
            "selected_candidate_ids": [
                _text(item.get("candidate_id")) for item in selected
            ],
            "rejected_candidate_ids": [
                _text(item.get("candidate_id"))
                for item in candidates
                if _text(item.get("candidate_id")) not in selected_ids
            ],
            "objective_score": 0.0,
            "covered_scales": sorted({
                _slug(item.get("scale") or "unspecified")
                for item in selected
                if _slug(item.get("scale") or "unspecified") != "unspecified"
            }),
        }
    values = matrix.get("values") if isinstance(matrix.get("values"), dict) else {}
    best_combo: tuple[dict[str, Any], ...] = ()
    best_score = float("-inf")
    best_details: dict[str, Any] = {}
    evaluated = 0
    for combo in combinations(eligible, choose):
        evaluated += 1
        score, details = _combination_score(combo, axes=axes, matrix_values=values)
        tie_key = tuple(_text(item.get("candidate_id")) for item in combo)
        best_tie_key = tuple(_text(item.get("candidate_id")) for item in best_combo)
        if score > best_score or (score == best_score and (not best_combo or tie_key < best_tie_key)):
            best_combo = combo
            best_score = score
            best_details = details
    selected = [deepcopy(item) for item in best_combo]
    selected_ids = {_text(item.get("candidate_id")) for item in selected}
    return selected, {
        "schema_version": "decomposition_set_selection_v1",
        "status": "selected",
        "algorithm": "exhaustive_weighted_set_cover",
        "candidate_count": len(candidates),
        "operational_candidate_count": len(ready),
        "eligible_candidate_count": len(eligible),
        "combination_count_evaluated": evaluated,
        "final_limit": limit,
        "selected_candidate_ids": [
            _text(item.get("candidate_id")) for item in selected
        ],
        "rejected_candidate_ids": [
            _text(item.get("candidate_id"))
            for item in candidates
            if _text(item.get("candidate_id")) not in selected_ids
        ],
        "objective_score": round(best_score, 6),
        **best_details,
    }


def audit_selected_direction_coverage(
    selected: list[dict[str, Any]],
    axes: list[dict[str, Any]],
    matrix: dict[str, Any],
    *,
    expected_count: int | None = None,
) -> dict[str, Any]:
    """Classify partial coverage as a repair need, not as acceptance."""

    values = matrix.get("values") if isinstance(matrix.get("values"), dict) else {}
    selected_ids = [_text(item.get("candidate_id")) for item in selected]
    axis_results: list[dict[str, Any]] = []
    missing: list[str] = []
    partial: list[str] = []
    for axis in axes:
        axis_id = _text(axis.get("id")).upper()
        maximum = max(
            (values.get(candidate_id, {}).get(axis_id, 0.0) for candidate_id in selected_ids),
            default=0.0,
        )
        status = "full" if maximum >= 1.0 else "partial" if maximum > 0.0 else "uncovered"
        if status == "partial":
            partial.append(axis_id)
        elif status == "uncovered":
            missing.append(axis_id)
        axis_results.append({
            "axis_id": axis_id,
            "label": _text(axis.get("label")),
            "axis_type": _text(axis.get("axis_type")),
            "scale": _text(axis.get("scale")),
            "importance": int(axis.get("importance") or 3),
            "status": status,
            "maximum_score": maximum,
            "covered_by_candidate_ids": [
                candidate_id
                for candidate_id in selected_ids
                if values.get(candidate_id, {}).get(axis_id, 0.0) > 0.0
            ],
        })
    repair_axes = [*missing, *partial]
    blocked_candidate_ids = [
        _text(item.get("candidate_id"))
        for item in selected
        if (
            not isinstance(item.get("scientific_operationality_preflight"), dict)
            or item["scientific_operationality_preflight"].get("status") != "ready"
        )
    ]
    independence_violations = [
        {
            "left_candidate_id": _text(left.get("candidate_id")),
            "right_candidate_id": _text(right.get("candidate_id")),
            "similarity": round(_pair_similarity(left, right), 6),
        }
        for left, right in combinations(selected, 2)
        if (
            _pair_similarity(left, right) > 0.92
            and _slug(left.get("scientific_object"))
            == _slug(right.get("scientific_object"))
        )
    ]
    count_shortfall = (
        max(0, int(expected_count) - len(selected))
        if expected_count is not None
        else 0
    )
    if not axes:
        status = "not_assessed_no_direction_axes"
    elif repair_axes:
        status = "needs_missing_direction_generation"
    elif count_shortfall or blocked_candidate_ids or independence_violations:
        status = "needs_final_set_revision"
    else:
        status = "accepted"
    return {
        "schema_version": "decomposition_set_acceptance_v1",
        "status": status,
        "selected_candidate_ids": selected_ids,
        "expected_count": int(expected_count) if expected_count is not None else None,
        "selected_count": len(selected),
        "count_shortfall": count_shortfall,
        "blocked_candidate_ids": blocked_candidate_ids,
        "independence_similarity_threshold": 0.92,
        "independence_violations": independence_violations,
        "axis_results": axis_results,
        "fully_covered_axis_count": sum(item["status"] == "full" for item in axis_results),
        "partial_axis_ids": partial,
        "uncovered_axis_ids": missing,
        "repair_axis_ids": repair_axes,
    }
