"""Coverage-first scheduling of scientific gaps and compatible search routes."""

from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from src.agents.idea_agent.utils.mcts.idea_routes import IdeaRoutePolicy


_ACTIVE_ROUTES = {"core_hypothesis", "provisional_hypothesis", "exploratory_frontier"}
_ROUTE_MATCHES = (
    (("target_object", "scientific_object", "object_selection"), ("object_substitution", "premise_inversion")),
    (("measurement_construct", "construct", "identifiability", "nonidentifiable"), ("verification_reversal", "representation_shift")),
    (("comparable_endpoint", "representation", "measurement", "readout"), ("representation_shift", "verification_reversal")),
    (("external_validation", "evidence_role", "direct_observation", "validation_gap", "counterexample"), ("verification_reversal", "object_substitution")),
    (("boundary", "assumption", "generalization", "premise"), ("premise_inversion", "mechanism_replacement")),
    (("mechanism", "causal", "proof", "current_method", "method_or_design"), ("mechanism_replacement", "verification_reversal")),
)


def _texts(value: Any) -> list[str]:
    values = value if isinstance(value, (list, tuple)) else [value]
    return list(dict.fromkeys(str(item).strip() for item in values if item is not None and str(item).strip()))


def _gap_records(handoff: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    triage = handoff.get("gap_triage") or {}
    rows = triage.get("gaps", []) if isinstance(triage, Mapping) else []
    audits = {str(row.get("gap_id")): row for row in rows if isinstance(row, Mapping)}
    records = {}
    for row in handoff.get("gaps", []) or []:
        if not isinstance(row, Mapping) or not row.get("gap_id"):
            continue
        gap_id = str(row["gap_id"])
        audit = audits.get(gap_id) or row.get("gap_audit") or {}
        records[gap_id] = {**dict(row), **dict(audit)}
    return records


def _eligible(gap: Mapping[str, Any]) -> bool:
    route = str(gap.get("eligibility_route") or "")
    return (
        (not route or route in _ACTIVE_ROUTES)
        and str(gap.get("status") or "") not in {"rejected", "out_of_scope", "closed", "resolved"}
    )


def _gap_priority(gap: Mapping[str, Any]) -> tuple[int, int]:
    return (
        {"core_hypothesis": 0, "provisional_hypothesis": 1, "exploratory_frontier": 2}.get(str(gap.get("eligibility_route") or ""), 1),
        {"high": 0, "medium": 1, "low": 2}.get(str(gap.get("priority") or ""), 1),
    )


def rank_gap_routes(gap: Mapping[str, Any], routes: Sequence[IdeaRoutePolicy]) -> list[IdeaRoutePolicy]:
    """Match ontology fields, without using topic names or discipline-specific rules."""
    features = " ".join(
        _texts(gap.get("gap_kind")) + _texts(gap.get("target_slot"))
        + _texts(gap.get("candidate_defect_tags"))
    ).lower()
    preferred = next(
        (route_ids for tokens, route_ids in _ROUTE_MATCHES if any(token in features for token in tokens)),
        ("mechanism_replacement", "verification_reversal"),
    )
    order = {route_id: index for index, route_id in enumerate(preferred)}
    return sorted(routes, key=lambda route: (order.get(route.route_id, len(order)), route.route_id))


@dataclass(frozen=True)
class GapSearchTask:
    seed: dict[str, Any]
    route: IdeaRoutePolicy
    primary_gap: dict[str, Any]
    iterations: int
    coverage_before: str = "unsearched"
    context_constraints: tuple[dict[str, Any], ...] = ()

    @property
    def primary_gap_id(self) -> str:
        return str(self.primary_gap.get("gap_id") or "")

    @property
    def key(self) -> tuple[str, str, str]:
        return str(self.seed.get("idea_id") or "legacy-primary"), self.primary_gap_id, self.route.route_id

    def focus(self) -> dict[str, Any]:
        return {
            "primary_gap_id": self.primary_gap_id,
            "primary_gap": deepcopy(self.primary_gap),
            "context_gap_ids": [gap["gap_id"] for gap in self.context_constraints],
            "context_constraints": deepcopy(list(self.context_constraints)),
            "route_id": self.route.route_id,
            "route_selection_reason": "Route matched to gap kind, target slot, and scientific defects.",
            "iteration_budget": self.iterations,
            "coverage_before": self.coverage_before,
        }

    def to_payload(self) -> dict[str, Any]:
        return {"seed_id": self.key[0], **self.focus()}

    def focused_seed(self) -> dict[str, Any]:
        seed = deepcopy(self.seed)
        seed["gap_search_focus"] = self.focus()
        if self.primary_gap_id:
            seed["target_gap_ids"] = [self.primary_gap_id]
        return seed


def build_gap_screening_tasks(
    seeds: Sequence[Mapping[str, Any]],
    routes: Sequence[IdeaRoutePolicy],
    handoff: Mapping[str, Any],
    *,
    iterations: int,
    search_budget: int = 0,
) -> list[GapSearchTask]:
    """Give each eligible target gap one search before revisiting any gap."""
    if not routes or iterations <= 0:
        return []
    records = _gap_records(handoff)
    choices: dict[str, list[tuple[Mapping[str, Any], dict[str, Any]]]] = defaultdict(list)
    for seed in seeds:
        gap_ids = _texts(seed.get("target_gap_ids"))
        if not gap_ids:
            choices["seed:" + str(seed.get("idea_id") or "legacy-primary")].append((seed, {
                "gap_kind": " ".join(_texts(seed.get("target_defects"))),
            }))
        for gap_id in gap_ids:
            if handoff and gap_id not in records:
                continue
            gap = records.get(gap_id, {"gap_id": gap_id, "gap_kind": gap_id})
            if _eligible(gap):
                choices[gap_id].append((seed, gap))
    tasks = []
    for candidates in choices.values():
        seed, gap = min(candidates, key=lambda item: (
            {"verified": 0, "mature": 0, "provisional": 1}.get(str(item[0].get("maturity_status") or ""), 1),
            len(_texts(item[0].get("target_gap_ids"))),
            str(item[0].get("idea_id") or ""),
        ))
        constraints = tuple(
            deepcopy(records[gap_id])
            for gap_id in _texts(seed.get("target_gap_ids"))
            if gap_id != gap.get("gap_id") and gap_id in records
        )
        tasks.append(GapSearchTask(
            deepcopy(dict(seed)), rank_gap_routes(gap, routes)[0], deepcopy(gap), iterations,
            context_constraints=constraints,
        ))
    tasks.sort(key=lambda task: (not bool(task.primary_gap_id), *_gap_priority(task.primary_gap), task.primary_gap_id, task.key[0]))
    # Distinct frozen scientific alternatives must survive shared-gap scheduling.
    # Reserve one search per primary/challenger, not the former five-route cross product.
    reserved = []
    for seed in seeds:
        if seed.get("scientific_candidate_root_role") not in {"primary", "challenger"}:
            continue
        gaps = [records[gid] for gid in _texts(seed.get("target_gap_ids")) if gid in records and _eligible(records[gid])]
        gap = min(gaps, key=_gap_priority) if gaps else {"gap_kind": "object_selection"}
        task = next((task for task in tasks if task.key[0] == seed.get("idea_id")), None)
        if task is None:
            task = GapSearchTask(deepcopy(dict(seed)), rank_gap_routes(gap, routes)[0], deepcopy(gap), iterations)
            tasks.append(task)
        reserved.append(task)
    if search_budget > 0:
        others = [task for task in tasks if task not in reserved]
        return reserved + others[:max(0, search_budget - len(reserved))]
    return tasks


def _has_candidate(result: Any) -> bool:
    return result is not None and getattr(result, "best", None) is not None


def build_gap_refinement_tasks(
    screening_tasks: Sequence[GapSearchTask],
    results: Mapping[tuple[str, str, str], Any],
    routes: Sequence[IdeaRoutePolicy],
    *,
    iterations: int,
    search_budget: int,
) -> list[GapSearchTask]:
    """Retry gaps without candidates first, then explore a different compatible route."""
    if not routes or iterations <= 0 or search_budget <= 0:
        return []
    candidates = []
    for task in screening_tasks:
        result = results.get(task.key)
        successful = _has_candidate(result)
        attempted = task.key in results
        alternatives = [route for route in rank_gap_routes(task.primary_gap, routes) if route.route_id != task.route.route_id]
        route = alternatives[0] if attempted and alternatives else task.route
        score = float(result.best.evaluation.composite) if successful else 0.0
        next_task = GapSearchTask(
            task.seed, route, task.primary_gap, iterations,
            "candidate_available" if successful else ("no_candidate" if attempted else "unsearched"),
            task.context_constraints,
        )
        candidates.append((not bool(task.primary_gap_id), successful, attempted, _gap_priority(task.primary_gap), -score, task.key, next_task))
    candidates.sort(key=lambda item: item[:-1])
    return [item[-1] for item in candidates[:search_budget]]


def gap_coverage_report(
    tasks: Sequence[GapSearchTask], results: Mapping[tuple[str, str, str], Any],
) -> dict[str, Any]:
    """Coverage means a returned candidate, not proof that a scientific gap is solved."""
    targeted = sorted({task.primary_gap_id for task in tasks if task.primary_gap_id})
    covered = sorted({task.primary_gap_id for task in tasks if task.primary_gap_id and _has_candidate(results.get(task.key))})
    return {
        "targeted_gap_ids": targeted,
        "candidate_gap_ids": covered,
        "gaps_without_candidates": sorted(set(targeted) - set(covered)),
        "search_count": len(tasks),
        "iteration_budget": sum(task.iterations for task in tasks),
        "coverage_definition": "At least one evaluated candidate; scientific resolution remains unverified.",
    }
