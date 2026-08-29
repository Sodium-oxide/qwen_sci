"""Direction-preserving synthesis for the five Idea Agent taste modes.

This module deliberately does not fuse multiple candidates into one idea.  It
normalizes each direction independently, records cross-direction overlap, and
keeps a recoverable candidate for every expected direction.
"""

from __future__ import annotations

from copy import deepcopy
import re
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from src.agents.idea_agent.utils.mcts.idea_taste_presets import IDEA_TASTE_PRESETS
from src.agents.idea_agent.utils.workflow.idea_contract import normalize_idea_contract


DEFAULT_DIRECTION_MODES: Tuple[str, ...] = (
    "moonshot_inventor",
    "bridge_builder",
    "steady_engineer",
    "ambitious_realist",
    "evidence_first",
)

EXPERIMENT_FIELDS = (
    "experiments",
    "experiment_design",
    "predicted_results",
    "sample_size",
    "statistical_test",
    "instrument_configuration",
    "ablation_plan",
    "failure_repair_plan",
)

HYPOTHESIS_FIELDS = (
    "central_hypothesis",
    "scientific_object",
    "mechanism_or_relation",
    "intervention_or_transformation",
    "expected_mechanism",
    "discriminating_observation",
    "boundary_or_failure_condition",
    "claim_scope",
    "assumptions",
    "target_gap_ids",
    "gap_alignment",
    "evidence_requirement",
    "evidence_basis",
)


def _text(value: Any) -> str:
    return str(value or "").strip()


def _unique(values: Iterable[Any]) -> List[str]:
    result: List[str] = []
    seen = set()
    for value in values:
        item = _text(value)
        if not item:
            continue
        key = item.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def _canonical_text(value: Any) -> str:
    text = _text(value).lower()
    text = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", " ", text)
    return " ".join(text.split())


def _mode_of(entry: Mapping[str, Any], fallback: str = "") -> str:
    return _text(entry.get("direction_mode") or entry.get("idea_taste_mode") or entry.get("mode") or fallback)


def _source_id(entry: Mapping[str, Any], mode: str, ordinal: int = 0) -> str:
    for key in ("candidate_id", "source_candidate_id", "node_id", "id", "signature"):
        value = _text(entry.get(key))
        if value:
            return value
    path = entry.get("search_path")
    if isinstance(path, (list, tuple)) and path:
        value = _text(path[-1])
        if value:
            return f"{mode}:{value}"
    return f"{mode}:candidate:{ordinal or 1}"


def _candidate_payload(raw: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(raw, Mapping):
        return None
    payload = raw.get("idea") if isinstance(raw.get("idea"), Mapping) else raw
    candidate = dict(payload)
    for key in ("evaluation", "score", "path", "search_path", "search_score"):
        if key in raw and key not in candidate:
            candidate[key] = deepcopy(raw[key])
    return candidate


def _normalise_candidate(raw: Any, mode: str, ordinal: int = 0) -> Dict[str, Any]:
    candidate = _candidate_payload(raw) or {}
    intervention = candidate.get("scientific_intervention")
    contract = intervention.get("hypothesis_contract") if isinstance(intervention, Mapping) else None
    if isinstance(contract, Mapping):
        for field_name in HYPOTHESIS_FIELDS:
            if not candidate.get(field_name) and contract.get(field_name) is not None:
                candidate[field_name] = deepcopy(contract[field_name])

    central = _text(candidate.get("central_hypothesis"))
    title = _text(candidate.get("title")) or f"{mode or 'default'} direction hypothesis"
    abstract = _text(candidate.get("abstract")) or central or title
    contribution = _text(candidate.get("core_contribution")) or central or title
    method = _text(candidate.get("method")) or (
        "Specify the profile-native mechanism, its transformation, and the observation "
        "that would distinguish the hypothesis."
    )
    candidate.update(
        {
            "title": title,
            "abstract": abstract,
            "core_contribution": contribution,
            "method": method,
        }
    )
    for key in EXPERIMENT_FIELDS:
        candidate.pop(key, None)
    try:
        normalized = normalize_idea_contract(candidate, keep_extra=True)
    except (TypeError, ValueError):
        normalized = dict(candidate)
    normalized["direction_mode"] = mode or _mode_of(normalized) or "default"
    normalized["idea_taste_mode"] = normalized["direction_mode"]
    normalized.setdefault("source_candidate_ids", [_source_id(normalized, normalized["direction_mode"], ordinal)])
    return normalized


def _entry_map(mode_entries: Any) -> Dict[str, Dict[str, Any]]:
    if isinstance(mode_entries, Mapping):
        iterable = []
        for mode, entry in mode_entries.items():
            if isinstance(entry, Mapping):
                item = dict(entry)
                item.setdefault("direction_mode", _text(mode))
                iterable.append(item)
    else:
        iterable = [dict(entry) for entry in (mode_entries or []) if isinstance(entry, Mapping)]
    result: Dict[str, Dict[str, Any]] = {}
    for entry in iterable:
        mode = _mode_of(entry)
        if mode and mode not in result:
            result[mode] = entry
    return result


def _result_candidates(result: Any, mode: str) -> List[Dict[str, Any]]:
    candidates: List[Dict[str, Any]] = []
    best = getattr(result, "best", None)
    if best is not None:
        payload = best.to_dict() if hasattr(best, "to_dict") else best
        candidate = _candidate_payload(payload)
        if candidate is not None:
            candidate.setdefault("direction_mode", mode)
            candidates.append(candidate)
    pareto = getattr(result, "pareto", None)
    if isinstance(pareto, Mapping):
        for item in pareto.values():
            if item is None:
                continue
            payload = item.to_dict() if hasattr(item, "to_dict") else item
            candidate = _candidate_payload(payload)
            if candidate is not None:
                candidate.setdefault("direction_mode", mode)
                candidates.append(candidate)
    return candidates


def _result_pareto_candidates(result: Any, mode: str) -> List[Dict[str, Any]]:
    pareto = getattr(result, "pareto", None)
    if not isinstance(pareto, Mapping):
        return []
    candidates: List[Dict[str, Any]] = []
    for item in pareto.values():
        if item is None:
            continue
        payload = item.to_dict() if hasattr(item, "to_dict") else item
        candidate = _candidate_payload(payload)
        if candidate is None:
            continue
        candidate.setdefault("direction_mode", mode)
        candidates.append(candidate)
    return candidates


def _pareto_candidate(entry: Mapping[str, Any], mode: str) -> Optional[Dict[str, Any]]:
    pareto = entry.get("pareto_candidates")
    if not isinstance(pareto, Mapping):
        return None
    candidates = [_candidate_payload(item) for item in pareto.values() if item is not None]
    candidates = [item for item in candidates if item is not None]
    if not candidates:
        return None
    candidates.sort(key=lambda item: float(item.get("score") or item.get("search_score") or 0.0), reverse=True)
    candidates[0].setdefault("direction_mode", mode)
    return candidates[0]


def _preset_affinity(entry: Mapping[str, Any], mode: str) -> float:
    preset = IDEA_TASTE_PRESETS.get(mode)
    evaluation = entry.get("evaluation")
    if not isinstance(evaluation, Mapping):
        return float(entry.get("search_score") or 0.0)
    if preset is None:
        return float(evaluation.get("composite") or entry.get("search_score") or 0.0)
    value = 0.0
    for field_name, weight in preset.weights.items():
        metric = field_name[:-7] if field_name.endswith("_weight") else field_name
        try:
            value += float(weight) * float(evaluation.get(metric) or 0.0)
        except (TypeError, ValueError):
            continue
    return value


def _shared_fallback(
    candidates: Sequence[Mapping[str, Any]],
    mode: str,
) -> Optional[Dict[str, Any]]:
    if not candidates:
        return None
    ranked = sorted(
        (dict(candidate) for candidate in candidates),
        key=lambda item: _preset_affinity(item, mode),
        reverse=True,
    )
    ranked[0].setdefault("direction_mode", mode)
    return ranked[0]


def _direction_reframe(candidate: Dict[str, Any], mode: str, source_mode: str, reason: str) -> Dict[str, Any]:
    reframed = deepcopy(candidate)
    reframed["direction_mode"] = mode
    reframed["idea_taste_mode"] = mode
    reframed["idea_source"] = "direction_fallback"
    reframed["scientificity_status"] = "LOWER_CONFIDENCE"
    reframed["fallback_reason"] = reason
    reframed["direction_reframing"] = {
        "requested_direction": mode,
        "source_direction": source_mode or "shared_candidate",
        "instruction": (
            f"Reframe the same hypothesis for {mode}; preserve the core mechanism and gap link, "
            "but express its risk and evidence preference in the requested direction."
        ),
    }
    note = (
        f"Direction {mode} used a fallback from {source_mode or 'shared candidate'}; "
        "the candidate remains provisional and needs direction-specific refinement."
    )
    reframed["synthesis_notes"] = _unique(
        [reframed.get("synthesis_notes"), note]
    )
    return reframed


def _gap_ids(candidate: Mapping[str, Any]) -> List[str]:
    values: List[Any] = list(candidate.get("target_gap_ids") or [])
    alignment = candidate.get("gap_alignment")
    if isinstance(alignment, Mapping):
        values.extend(alignment.get("gap_ids") or alignment.get("target_gap_ids") or [])
    elif isinstance(alignment, (list, tuple)):
        values.extend(alignment)
    return _unique(values)


def _prepare_direction(
    candidate: Dict[str, Any],
    mode: str,
    source_mode: str,
    ordinal: int,
    fallback_reason: str = "",
) -> Dict[str, Any]:
    prepared = _normalise_candidate(candidate, mode, ordinal)
    prepared["direction_mode"] = mode
    prepared["idea_taste_mode"] = mode
    prepared["idea_source"] = "direction_synthesis" if not fallback_reason else "direction_fallback"
    prepared["source_modes"] = _unique(
        [*(prepared.get("source_modes") or []), source_mode or mode]
    )
    prepared["source_candidate_ids"] = _unique(
        [*(prepared.get("source_candidate_ids") or []), _source_id(prepared, source_mode or mode, ordinal)]
    )
    prepared["target_gap_ids"] = _gap_ids(prepared)
    preset = IDEA_TASTE_PRESETS.get(mode)
    prepared["direction_summary"] = _text(
        prepared.get("direction_summary") or (preset.summary if preset is not None else mode)
    )
    prepared.setdefault("scientificity_status", "NORMAL")
    prepared.setdefault("synthesis_notes", [])
    if not isinstance(prepared["synthesis_notes"], list):
        prepared["synthesis_notes"] = [prepared["synthesis_notes"]]
    prepared["synthesis_notes"] = _unique(prepared["synthesis_notes"])
    if fallback_reason:
        prepared = _direction_reframe(prepared, mode, source_mode, fallback_reason)
    return prepared


def synthesize_direction_set(
    mode_entries: Any,
    *,
    expected_modes: Optional[Sequence[str]] = None,
    shared_candidates: Optional[Iterable[Mapping[str, Any]]] = None,
    mode_results: Optional[Mapping[str, Any]] = None,
    topic: str = "",
    logger: Any = None,
) -> Dict[str, Any]:
    """Return one independently preserved synthesized candidate per direction.

    Synthesis is intentionally fail-open.  It never rejects a direction because
    a seed is provisional or because a scientific field is missing.  Missing
    directions are recovered from Pareto candidates first, then from the shared
    candidate pool, and finally represented by a minimal placeholder.
    """

    modes = _unique(expected_modes or DEFAULT_DIRECTION_MODES)
    if not modes:
        modes = list(DEFAULT_DIRECTION_MODES)
    entries_by_mode = _entry_map(mode_entries)
    result_candidates: Dict[str, List[Dict[str, Any]]] = {}
    for mode, result in (mode_results or {}).items():
        result_candidates[_text(mode)] = _result_candidates(result, _text(mode))

    shared: List[Mapping[str, Any]] = []
    if shared_candidates is not None:
        shared.extend(item for item in shared_candidates if isinstance(item, Mapping))
    shared.extend(item for entries_mode, item in entries_by_mode.items() if entries_mode not in modes)
    for candidates in result_candidates.values():
        shared.extend(candidates)
    if not shared:
        shared.extend(entries_by_mode.values())

    directions: List[Dict[str, Any]] = []
    fallback_records: List[Dict[str, Any]] = []
    for ordinal, mode in enumerate(modes, start=1):
        source_mode = mode
        candidate = entries_by_mode.get(mode)
        fallback_reason = ""
        if candidate is None:
            candidate = _pareto_candidate(entries_by_mode.get(mode, {}), mode) if mode in entries_by_mode else None
            if candidate is None and mode_results and mode in mode_results:
                result_pareto = _result_pareto_candidates(mode_results[mode], mode)
                if result_pareto:
                    candidate = sorted(
                        result_pareto,
                        key=lambda item: float(item.get("score") or item.get("search_score") or 0.0),
                        reverse=True,
                    )[0]
            if candidate is None and result_candidates.get(mode):
                candidate = sorted(
                    result_candidates[mode],
                    key=lambda item: float(item.get("score") or item.get("search_score") or 0.0),
                    reverse=True,
                )[0]
            if candidate is None:
                candidate = _shared_fallback(shared, mode)
                source_mode = _mode_of(candidate or {}, "shared_candidate")
            if candidate is None:
                candidate = {
                    "title": f"{mode} direction for {topic or 'the research topic'}",
                    "abstract": "A direction-specific hypothesis seed is awaiting MCTS materialization.",
                    "core_contribution": "Preserve this direction as an exploratory hypothesis seed.",
                    "method": "Materialize the profile-native mechanism and its discriminating observation in the next search pass.",
                    "central_hypothesis": "A direction-specific mechanism may address the prepared research gap.",
                    "claim_scope": "Exploratory and provisional until materialized and debated.",
                }
                source_mode = "placeholder"
            fallback_reason = "direction_candidate_unavailable"
            fallback_records.append(
                {
                    "direction_mode": mode,
                    "source_direction": source_mode,
                    "reason": fallback_reason,
                }
            )
        prepared = _prepare_direction(candidate, mode, source_mode, ordinal, fallback_reason)
        directions.append(prepared)

    mechanism_groups: Dict[str, List[str]] = {}
    hypothesis_groups: Dict[str, List[str]] = {}
    for direction in directions:
        mechanism_key = _canonical_text(
            direction.get("mechanism_or_relation") or direction.get("expected_mechanism")
        )
        if mechanism_key:
            mechanism_groups.setdefault(mechanism_key, []).append(direction["direction_mode"])
        hypothesis_key = _canonical_text(direction.get("central_hypothesis"))
        if hypothesis_key:
            hypothesis_groups.setdefault(hypothesis_key, []).append(direction["direction_mode"])

    cross_direction_notes: List[Dict[str, str]] = []
    for modes_with_same_mechanism in mechanism_groups.values():
        if len(modes_with_same_mechanism) < 2:
            continue
        joined = ", ".join(modes_with_same_mechanism)
        cross_direction_notes.append(
            {
                "conflict": f"The same mechanism appears in {joined}.",
                "resolution": "Retain each direction and preserve its distinct risk, scope, and evidence preference; do not fuse them.",
            }
        )
    for modes_with_same_hypothesis in hypothesis_groups.values():
        if len(modes_with_same_hypothesis) < 2:
            continue
        joined = ", ".join(modes_with_same_hypothesis)
        cross_direction_notes.append(
            {
                "conflict": f"The same central hypothesis wording appears in {joined}.",
                "resolution": "Deduplicate the wording in synthesis notes while keeping separate direction candidates.",
            }
        )
    gap_sets = {tuple(direction.get("target_gap_ids") or []) for direction in directions}
    if len(gap_sets) > 1:
        cross_direction_notes.append(
            {
                "conflict": "Direction candidates reference different subsets of the prepared gap ledger.",
                "resolution": "Keep direction-local gap IDs and use the shared Gap seed context as the common association.",
            }
        )
    for direction in directions:
        if not direction.get("target_gap_ids"):
            direction["synthesis_notes"] = _unique(
                [*(direction.get("synthesis_notes") or []), "No explicit gap ID was present; retain the candidate as an exploratory topic seed."]
            )

    seed_groups: Dict[str, List[str]] = {}
    route_groups: Dict[str, List[str]] = {}
    for direction in directions:
        seed_id = _text(direction.get("seed_id") or direction.get("idea_id") or "legacy-primary")
        route_id = _text(direction.get("route_id") or direction.get("direction_mode") or "legacy_route")
        candidate_id = _text(direction.get("idea_id") or direction.get("title") or route_id)
        seed_groups.setdefault(seed_id, []).append(candidate_id)
        route_groups.setdefault(route_id, []).append(candidate_id)

    result = {
        "synthesis_mode": "direction_preserving",
        "directions": directions,
        "cross_direction_notes": cross_direction_notes,
        "fallbacks": fallback_records,
        "direction_count": len(directions),
        "expected_direction_modes": modes,
        "seed_groups": seed_groups,
        "route_clusters": [
            {"route_id": route_id, "candidate_ids": candidate_ids, "candidate_count": len(candidate_ids)}
            for route_id, candidate_ids in route_groups.items()
        ],
        "diversity_report": {
            "seed_count": len(seed_groups),
            "route_cluster_count": len(route_groups),
            "diversity_failure": len(route_groups) <= 1,
        },
    }
    if logger is not None:
        try:
            logger.info(
                "🧭 Direction synthesis preserved %d directions (%d fallbacks).",
                len(directions),
                len(fallback_records),
            )
        except Exception:
            pass
    return result


__all__ = [
    "DEFAULT_DIRECTION_MODES",
    "synthesize_direction_set",
]
