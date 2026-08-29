"""Portfolio-level adjudication for mature-idea route candidates.

The portfolio is deliberately fail-open: it projects candidates into bounded
records, removes structural duplicates, and keeps distinctive high-risk ideas
available for later review.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from copy import deepcopy
from typing import Any, Dict, Iterable, List, Mapping, Sequence

from src.agents.idea_agent.utils.workflow.idea_diversity import (
    build_mature_idea_route_signature,
    compare_mature_ideas,
)
from src.agents.idea_agent.utils.workflow.idea_contract import normalize_mature_ideas


def _text(value: Any) -> str:
    return str(value or "").strip()


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _tokens(value: Any) -> set[str]:
    if isinstance(value, Mapping):
        value = " ".join(f"{key}:{item}" for key, item in value.items())
    elif isinstance(value, (list, tuple, set)):
        value = " ".join(map(str, value))
    return set(re.findall(r"[a-z0-9_\u0080-\uffff]+", _text(value).casefold()))


def _route_key(candidate: Mapping[str, Any]) -> str:
    signature = candidate.get("route_signature")
    if isinstance(signature, Mapping) and signature:
        route_id = _text(signature.get("route_id") or candidate.get("route_id"))
        structural = {
            key: signature[key]
            for key in sorted(signature)
            if key not in {"mature_idea", "seed_id"}
        }
        if route_id:
            structural["route_id"] = route_id
        return json.dumps(structural, ensure_ascii=False, sort_keys=True, default=str)
    route_id = _text(candidate.get("route_id"))
    if route_id:
        return route_id
    structural = build_mature_idea_route_signature(candidate)
    return json.dumps(structural, ensure_ascii=False, sort_keys=True, default=str)


def _candidate_key(candidate: Mapping[str, Any]) -> str:
    return ":".join(
        (
            _text(candidate.get("idea_id") or candidate.get("candidate_id") or candidate.get("title")),
            _text(candidate.get("seed_id")),
            _text(candidate.get("route_id")),
        )
    )


def _candidate_score(candidate: Mapping[str, Any], *, route_frequency: Mapping[str, int]) -> Dict[str, float]:
    evaluation = candidate.get("evaluation") if isinstance(candidate.get("evaluation"), Mapping) else {}
    scientific_validity = _number(
        evaluation.get("explanatory_power", evaluation.get("clarity", candidate.get("scientific_validity", 0.0)))
    )
    if scientific_validity > 1.0:
        scientific_validity /= 10.0
    maturity = candidate.get("maturity") if isinstance(candidate.get("maturity"), Mapping) else {}
    maturity_score = _number(maturity.get("composite", maturity.get("score", candidate.get("maturity_score", 0.0))))
    if maturity_score > 1.0:
        maturity_score /= 10.0
    if not maturity_score:
        maturity_score = {"mature": 1.0, "provisional": 0.72, "exploratory": 0.48, "needs_grounding": 0.3, "rejected": 0.0}.get(
            _text(candidate.get("maturity_status")).casefold(), 0.5
        )
    validation = _number(
        candidate.get("validation_feasibility", evaluation.get("feasibility", evaluation.get("identifiability", 0.0)))
    )
    if validation > 1.0:
        validation /= 10.0
    frequency = max(1, route_frequency.get(_route_key(candidate), 1))
    route_uniqueness = 1.0 / frequency
    risk = _number(candidate.get("risk", evaluation.get("risk", 0.0)))
    if risk > 1.0:
        risk /= 10.0
    portfolio_value = 0.55 * route_uniqueness + 0.45 * (scientific_validity + maturity_score + validation) / 3.0
    composite = scientific_validity + maturity_score + route_uniqueness + validation + portfolio_value
    return {
        "scientific_validity": round(scientific_validity, 6),
        "maturity": round(maturity_score, 6),
        "route_uniqueness": round(route_uniqueness, 6),
        "validation_feasibility": round(validation, 6),
        "portfolio_value": round(portfolio_value, 6),
        "risk": round(risk, 6),
        "composite": round(composite, 6),
    }


def group_candidates_by_seed(candidates: Iterable[Mapping[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    grouped: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for candidate in candidates or []:
        if not isinstance(candidate, Mapping):
            continue
        item = deepcopy(dict(candidate))
        seed_id = _text(item.get("seed_id") or item.get("idea_id") or "legacy-primary")
        item.setdefault("seed_id", seed_id)
        grouped[seed_id].append(item)
    return dict(grouped)


def enforce_candidate_invariants(
    candidates: Iterable[Mapping[str, Any]],
    *,
    has_survey_handoff: bool = False,
) -> List[Dict[str, Any]]:
    """Normalize identity fields and annotate, rather than silently hide, violations."""
    result: List[Dict[str, Any]] = []
    for item in candidates or []:
        if not isinstance(item, Mapping):
            continue
        candidate = deepcopy(dict(item))
        violations: List[str] = []
        candidate["idea_id"] = _text(candidate.get("idea_id") or candidate.get("candidate_id") or candidate.get("title") or "candidate")
        candidate["seed_id"] = _text(candidate.get("seed_id") or candidate["idea_id"])
        candidate["route_id"] = _text(candidate.get("route_id") or candidate.get("direction_mode") or "legacy_route")
        if not candidate.get("route_signature"):
            candidate["route_signature"] = build_mature_idea_route_signature(candidate) or {"route_id": candidate["route_id"]}
        if has_survey_handoff and not candidate.get("target_gap_ids"):
            violations.append("missing_target_gap_ids")
        if candidate.get("reframed_problem_id") and not candidate.get("rejected_gap_ids"):
            violations.append("missing_rejected_gap_ids")
        if candidate.get("rejected_gap_ids") and not candidate.get("reframed_problem_id"):
            violations.append("missing_reframed_problem_id")
        if violations:
            candidate["invariant_status"] = "violated"
            candidate["invariant_violations"] = violations
        else:
            candidate["invariant_status"] = "valid"
        result.append(candidate)
    return result


def cluster_candidates_by_route_signature(candidates: Iterable[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    clusters: Dict[str, Dict[str, Any]] = {}
    for candidate in candidates or []:
        if not isinstance(candidate, Mapping):
            continue
        seed_id = _text(candidate.get("seed_id") or candidate.get("idea_id") or "legacy-primary")
        route_key = _route_key(candidate)
        key = route_key
        for existing_key, existing_cluster in clusters.items():
            representative = existing_cluster.get("_representative_raw")
            if isinstance(representative, Mapping) and compare_mature_ideas(candidate, representative).get("duplicate"):
                key = existing_key
                break
        cluster = clusters.setdefault(
            key,
            {
                "cluster_id": f"route:{len(clusters) + 1}",
                "seed_id": seed_id,
                "seed_ids": [],
                "route_signature": deepcopy(candidate.get("route_signature") or build_mature_idea_route_signature(candidate)),
                "route_id": _text(candidate.get("route_id")),
                "candidate_ids": [],
                "candidates": [],
            },
        )
        cluster.setdefault("route_ids", [])
        if _text(candidate.get("route_id")) and _text(candidate.get("route_id")) not in cluster["route_ids"]:
            cluster["route_ids"].append(_text(candidate.get("route_id")))
        cluster.setdefault("_representative_raw", deepcopy(dict(candidate)))
        if seed_id not in cluster["seed_ids"]:
            cluster["seed_ids"].append(seed_id)
        candidate_id = _candidate_key(candidate)
        if candidate_id:
            cluster["candidate_ids"].append(candidate_id)
        cluster["candidates"].append(deepcopy(dict(candidate)))
    result = list(clusters.values())
    for cluster in result:
        cluster["candidate_count"] = len(cluster["candidates"])
        cluster["representative"] = max(
            cluster["candidates"],
            key=lambda item: _number(item.get("search_score"), _number((item.get("evaluation") or {}).get("composite") if isinstance(item.get("evaluation"), Mapping) else 0.0)),
        )
        cluster.pop("candidates", None)
        cluster.pop("_representative_raw", None)
    return result


def select_seed_representatives(
    candidates: Iterable[Mapping[str, Any]],
    *,
    max_candidates_per_seed: int = 5,
) -> Dict[str, List[Dict[str, Any]]]:
    grouped = group_candidates_by_seed(candidates)
    representatives: Dict[str, List[Dict[str, Any]]] = {}
    route_frequency = defaultdict(int)
    for items in grouped.values():
        for item in items:
            route_frequency[_route_key(item)] += 1
    for seed_id, items in grouped.items():
        ranked = []
        for item in items:
            score = _candidate_score(item, route_frequency=route_frequency)
            enriched = deepcopy(item)
            enriched["portfolio_score"] = score
            ranked.append(enriched)
        ranked.sort(key=lambda item: item["portfolio_score"]["composite"], reverse=True)
        seen_routes = set()
        selected: List[Dict[str, Any]] = []
        for item in ranked:
            key = _route_key(item)
            if key in seen_routes:
                continue
            seen_routes.add(key)
            selected.append(item)
            if len(selected) >= max(1, int(max_candidates_per_seed)):
                break
        for item in ranked:
            key = _route_key(item)
            score = item["portfolio_score"]
            is_high_risk = score["risk"] >= 0.65 or _text(item.get("maturity_status")).casefold() in {"exploratory", "needs_grounding"}
            if is_high_risk and key not in seen_routes:
                seen_routes.add(key)
                selected.append(item)
        representatives[seed_id] = selected
    return representatives


def build_diversity_report(
    candidates: Sequence[Mapping[str, Any]],
    route_clusters: Sequence[Mapping[str, Any]],
    *,
    max_same_route_ratio: float = 0.60,
    min_route_distance: float = 0.35,
    enabled: bool = True,
) -> Dict[str, Any]:
    route_ids = [_route_key(item) for item in candidates if isinstance(item, Mapping)]
    counts = defaultdict(int)
    for route_id in route_ids:
        counts[route_id] += 1
    total = len(route_ids)
    dominant_ratio = max(counts.values(), default=0) / total if total else 0.0
    diversity_failure = bool(enabled) and (len(route_clusters) <= 1 or dominant_ratio > float(max_same_route_ratio))
    return {
        "candidate_count": total,
        "route_cluster_count": len(route_clusters),
        "unique_route_count": len(counts),
        "dominant_route_ratio": round(dominant_ratio, 6),
        "max_same_route_ratio": float(max_same_route_ratio),
        "min_route_distance": float(min_route_distance),
        "enabled": bool(enabled),
        "diversity_failure": bool(diversity_failure),
        "route_counts": dict(counts),
    }


def select_primary_and_competitors(
    candidates: Sequence[Mapping[str, Any]],
    *,
    max_competitors: int = 4,
) -> Dict[str, Any]:
    route_frequency = defaultdict(int)
    for candidate in candidates:
        route_frequency[_route_key(candidate)] += 1
    ranked: List[Dict[str, Any]] = []
    for candidate in candidates:
        item = deepcopy(dict(candidate))
        item["portfolio_score"] = _candidate_score(item, route_frequency=route_frequency)
        ranked.append(item)
    ranked.sort(key=lambda item: item["portfolio_score"]["composite"], reverse=True)
    valid_ranked = [item for item in ranked if item.get("invariant_status") != "violated"]
    primary = valid_ranked[0] if valid_ranked else {}
    primary_id = _candidate_key(primary)
    competitors = [item for item in ranked if _candidate_key(item) != primary_id][: max(0, int(max_competitors))]
    high_risk = [
        item for item in ranked
        if item["portfolio_score"]["risk"] >= 0.65
        or _text(item.get("maturity_status")).casefold() in {"exploratory", "needs_grounding"}
    ]
    return {"primary": primary, "competitors": competitors, "high_risk": high_risk, "ranked": ranked}


def build_idea_portfolio(
    candidates: Iterable[Mapping[str, Any]],
    mature_ideas: Any = None,
    *,
    topic: str = "",
    max_candidates_per_seed: int = 5,
    max_same_route_ratio: float = 0.60,
    debate_result: Mapping[str, Any] | None = None,
    has_survey_handoff: bool = False,
    min_independent_ideas: int = 2,
    primary_selection_policy: str = "scientific_maturity_diversity_validation",
    diversity_enabled: bool = True,
    min_route_distance: float = 0.35,
    regenerate_collapsed_routes: bool = False,
    preserve_high_risk_unique_candidates: bool = True,
) -> Dict[str, Any]:
    candidate_list = enforce_candidate_invariants(candidates, has_survey_handoff=has_survey_handoff)
    representatives_by_seed = select_seed_representatives(
        candidate_list,
        max_candidates_per_seed=max_candidates_per_seed,
    )
    representatives = [item for items in representatives_by_seed.values() for item in items]
    structurally_unique: List[Dict[str, Any]] = []
    collapsed_representatives: List[Dict[str, Any]] = []
    for item in representatives:
        duplicate = next(
            (prior for prior in structurally_unique if compare_mature_ideas(item, prior).get("duplicate")),
            None,
        )
        if duplicate is not None:
            collapsed = deepcopy(item)
            collapsed["rejection_reason"] = "structural_duplicate_of_route"
            collapsed["duplicate_of"] = _candidate_key(duplicate)
            collapsed_representatives.append(collapsed)
            continue
        structurally_unique.append(item)
    representatives = structurally_unique
    route_clusters = cluster_candidates_by_route_signature(representatives)
    selection = select_primary_and_competitors(
        representatives,
        max_competitors=max(0, len(representatives) - 1),
    )
    primary = selection["primary"]
    selected_ids = {
        _candidate_key(selection["primary"]),
        *(_candidate_key(item) for item in selection["competitors"]),
    }
    rejected = []
    rejected.extend(collapsed_representatives)
    for item in candidate_list:
        item_id = _candidate_key(item)
        if item_id and item_id not in selected_ids and item not in selection["high_risk"]:
            rejected_item = deepcopy(item)
            rejected_item["rejection_reason"] = "homogeneous_variant_or_not_selected_representative"
            rejected.append(rejected_item)
    normalized_mature = normalize_mature_ideas(mature_ideas or [])
    diversity_report = build_diversity_report(
        representatives,
        route_clusters,
        max_same_route_ratio=max_same_route_ratio,
        min_route_distance=min_route_distance,
        enabled=diversity_enabled,
    )
    diversity_report["min_independent_ideas"] = max(1, int(min_independent_ideas))
    diversity_report["independent_idea_shortfall"] = max(0, int(min_independent_ideas) - len(normalized_mature))
    diversity_report["regeneration_requested"] = bool(regenerate_collapsed_routes and diversity_report["diversity_failure"])
    diversity_report["invariant_violation_count"] = sum(
        1 for item in candidate_list if item.get("invariant_status") == "violated"
    )
    diversity_report["primary_selection_blocked"] = not bool(primary)
    return {
        "schema_version": "idea_portfolio_v1",
        "topic": _text(topic),
        "mature_ideas": normalized_mature,
        "selected_primary_idea": primary,
        "competitive_ideas": selection["competitors"],
        "high_risk_ideas": selection["high_risk"] if preserve_high_risk_unique_candidates else [],
        "rejected_ideas": rejected,
        "route_clusters": route_clusters,
        "diversity_report": diversity_report,
        "debate_summary": deepcopy(dict(debate_result)) if isinstance(debate_result, Mapping) else {},
        "selection_rationale": (
            f"Primary selection policy '{primary_selection_policy}' maximizes scientific validity, maturity, route uniqueness, "
            "validation feasibility, and portfolio value; taste mode is not a selection rule."
            if primary else "No candidate was materialized."
        ),
        "representatives_by_seed": representatives_by_seed,
    }


__all__ = [
    "build_idea_portfolio",
    "build_diversity_report",
    "cluster_candidates_by_route_signature",
    "group_candidates_by_seed",
    "select_primary_and_competitors",
    "select_seed_representatives",
    "enforce_candidate_invariants",
]
