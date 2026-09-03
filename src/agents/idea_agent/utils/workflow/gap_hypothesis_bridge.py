"""Fail-open conversion from Survey gaps to Idea hypothesis seeds."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import re
from typing import Any

from src.pipeline.survey_idea_handoff import stable_identifier
from src.agents.idea_agent.utils.workflow.multimodal_data_anchoring import (
    DATA_ANCHORED_PRIORITY,
    build_data_anchored_seed_context,
)


GAP_HYPOTHESIS_BRIDGE_SCHEMA_VERSION = "gap_hypothesis_bridge_v1"

_PRIMARY_ROUTES = frozenset(
    {"core_hypothesis", "provisional_hypothesis", "exploratory_frontier"}
)
_EXPLORATORY_ROUTES = frozenset({"future_work_seed"})
_CONSTRAINT_ROUTES = frozenset({"supporting_constraint", "verification_only"})
_EXCLUDED_ROUTES = frozenset({"exclude", "contradicted", "misaligned", "out_of_scope"})
_EXCLUDED_AUDIT_STATUSES = frozenset({"contradicted", "misaligned", "out_of_scope"})
_EXCLUDED_GAP_STATUSES = frozenset(
    {"rejected", "contradicted", "misaligned", "out_of_scope"}
)

_ROUTE_RANK = {
    "core_hypothesis": 0,
    "provisional_hypothesis": 1,
    "exploratory_frontier": 2,
    "future_work_seed": 3,
    "supporting_constraint": 4,
    "verification_only": 5,
}
_PRIORITY_RANK = {"high": 0, "medium": 1, "low": 2}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _texts(value: Any) -> list[str]:
    values = value if isinstance(value, (list, tuple, set, frozenset)) else [value]
    result: list[str] = []
    seen: set[str] = set()
    for item in values:
        item_text = _text(item)
        if item_text and item_text not in seen:
            seen.add(item_text)
            result.append(item_text)
    return result


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _records(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, Mapping):
        return [dict(value)]
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [dict(item) for item in value if isinstance(item, Mapping)]
    return []


def _confidence(gap: Mapping[str, Any], triage: Mapping[str, Any]) -> float:
    raw_value = triage.get(
        "existence_confidence",
        gap.get(
            "existence_confidence",
            gap.get("confidence", _mapping(gap.get("gap_audit")).get("confidence", 0.5)),
        ),
    )
    try:
        value = float(raw_value)
    except (TypeError, ValueError):
        value = 0.5
    return max(0.0, min(1.0, value))


def _route(gap: Mapping[str, Any], triage: Mapping[str, Any]) -> str:
    explicit_route = _text(triage.get("eligibility_route"))
    if explicit_route:
        return explicit_route

    audit_route = _text(_mapping(gap.get("gap_audit")).get("eligibility_route"))
    if audit_route:
        return audit_route

    gap_kind = " ".join(
        _text(gap.get(key)) for key in ("gap_kind", "target_slot", "statement")
    ).casefold()
    if "future work" in gap_kind or "future_work" in gap_kind:
        return "future_work_seed"
    if _text(gap.get("status")).casefold() in _EXCLUDED_GAP_STATUSES:
        return "exclude"
    return "provisional_hypothesis"


def _audit_status(gap: Mapping[str, Any], triage: Mapping[str, Any]) -> str:
    return (
        _text(triage.get("audit_status"))
        or _text(_mapping(gap.get("gap_audit")).get("audit_status"))
        or "unverified"
    )


def _seed_status(
    route: str,
    audit_status: str,
    source_anchors: list[dict[str, Any]],
) -> str:
    if not source_anchors:
        return "unanchored"
    if audit_status == "verified" and route == "core_hypothesis":
        return "verified"
    if route == "provisional_hypothesis":
        return "provisional"
    if route in _EXPLORATORY_ROUTES or route == "exploratory_frontier":
        return "exploratory"
    if route in _CONSTRAINT_ROUTES:
        return "constraint"
    if audit_status in {"plausible", "weakly_supported", "unverified"}:
        return "plausible"
    return "provisional"


def _anchor_index(handoff: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        _text(anchor.get("anchor_id")): dict(anchor)
        for anchor in _records(handoff.get("anchors"))
        if _text(anchor.get("anchor_id"))
    }


def _evidence_role_index(handoff: Mapping[str, Any]) -> dict[tuple[str, str], list[dict[str, Any]]]:
    index: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for role in _records(handoff.get("evidence_roles")):
        key = (_text(role.get("subhypothesis_id")), _text(role.get("target_slot")))
        if not key[0] and not key[1]:
            continue
        index.setdefault(key, []).append(dict(role))
    return index


def _source_anchors(
    gap: Mapping[str, Any],
    anchor_index: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    anchors: list[dict[str, Any]] = []
    for anchor_id in _texts(gap.get("anchor_ids")):
        anchor = anchor_index.get(anchor_id)
        if anchor is not None:
            anchors.append(dict(anchor))
    source_pointer = _mapping(gap.get("source_pointer"))
    if source_pointer and not anchors:
        anchors.append({"source_pointer": source_pointer})
    return anchors


def _known_evidence(
    gap: Mapping[str, Any],
    source_anchors: Sequence[Mapping[str, Any]],
    evidence_roles: Sequence[Mapping[str, Any]],
) -> list[str]:
    evidence: list[str] = []
    for anchor in source_anchors:
        excerpt = _text(anchor.get("text_excerpt") or anchor.get("label"))
        if excerpt:
            evidence.append(excerpt)
        pointer = _mapping(anchor.get("source_pointer"))
        if pointer:
            artifact = _text(pointer.get("artifact"))
            json_pointer = _text(pointer.get("json_pointer"))
            if artifact or json_pointer:
                evidence.append(f"source:{artifact}#{json_pointer}".strip("#"))
    for role in evidence_roles:
        expected_role = _text(role.get("expected_role"))
        if expected_role:
            evidence.append(f"evidence_role:{expected_role}")
    source_pointer = _mapping(gap.get("source_pointer"))
    if source_pointer:
        artifact = _text(source_pointer.get("artifact"))
        json_pointer = _text(source_pointer.get("json_pointer"))
        if artifact or json_pointer:
            evidence.append(f"source:{artifact}#{json_pointer}".strip("#"))
    return _texts(evidence)


def _unknown_or_unverified(
    gap: Mapping[str, Any],
    triage: Mapping[str, Any],
) -> list[str]:
    unknown: list[str] = []
    audit_status = _audit_status(gap, triage)
    verification_status = _text(triage.get("verification_status"))
    if audit_status:
        unknown.append(f"audit_status:{audit_status}")
    if verification_status and verification_status != "verified":
        unknown.append(f"verification_status:{verification_status}")
    eligibility = _mapping(gap.get("evidence_eligibility"))
    unknown.extend(f"claim_limit:{item}" for item in _texts(eligibility.get("claim_limits")))
    if not unknown:
        unknown.append("evidence scope remains to be established")
    return _texts(unknown)


def _profile_id(
    profile_resolution: Mapping[str, Any],
    handoff: Mapping[str, Any],
) -> str:
    handoff_resolution = _mapping(handoff.get("profile_resolution"))
    return (
        _text(profile_resolution.get("profile_id"))
        or _text(profile_resolution.get("profile_id_hint"))
        or _text(handoff_resolution.get("profile_id"))
        or _text(handoff_resolution.get("profile_id_hint"))
        or "generic_scientific"
    ).casefold()


def _is_excluded(gap: Mapping[str, Any], route: str, audit_status: str) -> bool:
    gap_status = _text(gap.get("status")).casefold()
    return (
        route in _EXCLUDED_ROUTES
        or audit_status in _EXCLUDED_AUDIT_STATUSES
        or gap_status in _EXCLUDED_GAP_STATUSES
    )


def _bound_unresolved_data_gap_statement(statement: str) -> str:
    """Remove novelty assertions that an unresolved local observation cannot support."""

    text = _text(statement)
    novelty_claim = re.compile(
        r"\b(?:first\s+(?:discovery|finding|observation|report|evidence)|"
        r"newly\s+discovered|first[- ]ever)\b|首次(?:发现|报道|观察)|首个(?:发现|报道|观察)",
        re.IGNORECASE,
    )
    if not novelty_claim.search(text):
        return text
    return (
        "The supplied dataset contains an observation whose relationship to the "
        "literature remains unresolved; test condition-specific, alternative, and "
        "measurement explanations before making any novelty claim."
    )


def build_gap_hypothesis_seeds(
    survey_idea_handoff: Mapping[str, Any] | None,
    gap_triage: Mapping[str, Any] | None = None,
    *,
    profile_resolution: Mapping[str, Any] | None = None,
    scope: Mapping[str, Any] | None = None,
    topic: str = "",
    multimodal_evidence_projection: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Build hypothesis seeds without imposing a strict evidence admission gate."""

    handoff = _mapping(survey_idea_handoff)
    triage = _mapping(gap_triage) or _mapping(handoff.get("gap_triage"))
    triage_by_id = {
        _text(item.get("gap_id")): item
        for item in _records(triage.get("gaps"))
        if _text(item.get("gap_id"))
    }
    anchors_by_id = _anchor_index(handoff)
    evidence_roles_by_slot = _evidence_role_index(handoff)
    resolved_profile_id = _profile_id(_mapping(profile_resolution), handoff)
    resolved_scope = _mapping(scope) or _mapping(handoff.get("scope"))
    seeds: list[dict[str, Any]] = []

    for gap in _records(handoff.get("gaps")):
        gap_id = _text(gap.get("gap_id"))
        if not gap_id:
            continue
        triage_row = triage_by_id.get(gap_id, {})
        route = _route(gap, triage_row)
        audit_status = _audit_status(gap, triage_row)
        if _is_excluded(gap, route, audit_status):
            continue
        source_anchors = _source_anchors(gap, anchors_by_id)
        key = (_text(gap.get("subhypothesis_id")), _text(gap.get("target_slot")))
        evidence_roles = [dict(role) for role in evidence_roles_by_slot.get(key, [])]
        confidence = _confidence(gap, triage_row)
        candidate_defect_tags = _texts(gap.get("candidate_defect_tags"))
        if not candidate_defect_tags:
            candidate_defect_tags = ["unexplored_gap"]
        data_context = build_data_anchored_seed_context(
            handoff,
            gap,
            multimodal_evidence_projection=multimodal_evidence_projection,
        )
        data_status = _text(data_context.get("literature_reconciliation_status"))
        gap_kind = _text(gap.get("gap_kind")) or "unexplored_gap"
        target_slot = _text(gap.get("target_slot")) or "scientific_constraint"
        gap_statement = _text(gap.get("statement")) or "An unresolved research gap remains."
        unknown_or_unverified = _unknown_or_unverified(gap, triage_row)
        if data_status == "measurement_at_risk":
            gap_kind = "measurement_validity_gap"
            target_slot = "multimodal_native_measurement"
            gap_statement = (
                "The supplied-data pattern requires validation against calibration, "
                "preparation, proxy-validity, or preprocessing explanations before "
                "it can support a mechanism claim."
            )
            candidate_defect_tags = _texts(
                ["measurement_validity", "method_design", *candidate_defect_tags]
            )
        elif data_status == "challenged":
            gap_statement = (
                "The supplied-data observation and comparable literature evidence "
                "are challenged; resolve their conditions, comparability, measurement, "
                "or competing mechanisms without treating either source as decisive."
            )
        elif data_status == "unresolved":
            gap_statement = _bound_unresolved_data_gap_statement(gap_statement)
            unknown_or_unverified = _texts(
                [
                    *unknown_or_unverified,
                    "literature_reconciliation:unresolved; do not characterize the local observation as a first discovery",
                ]
            )
        seed_id = stable_identifier(
            "gap_seed",
            gap_id,
            route,
            resolved_profile_id,
        )
        seeds.append(
            {
                "schema_version": GAP_HYPOTHESIS_BRIDGE_SCHEMA_VERSION,
                "seed_id": seed_id,
                "gap_id": gap_id,
                "subhypothesis_id": _text(gap.get("subhypothesis_id")) or "GLOBAL",
                "gap_statement": gap_statement,
                "gap_kind": gap_kind,
                "target_slot": target_slot,
                "target_object": _text(gap.get("target_object")),
                "priority": _text(gap.get("priority")) or "medium",
                "gap_route": route or "provisional_hypothesis",
                "profile_id": resolved_profile_id,
                "why_it_matters": _text(gap.get("why_it_matters")),
                "known_evidence": _known_evidence(gap, source_anchors, evidence_roles),
                "unknown_or_unverified": unknown_or_unverified,
                "source_anchors": source_anchors,
                "evidence_roles": evidence_roles,
                "scope": dict(resolved_scope),
                "candidate_defect_tags": candidate_defect_tags,
                "candidate_contribution_modes": _texts(gap.get("candidate_contribution_modes")),
                "confidence": round(confidence, 6),
                "seed_status": _seed_status(route, audit_status, source_anchors),
                "audit_status": audit_status,
                "verification_status": _text(triage_row.get("verification_status")) or "not_checked",
                **data_context,
            }
        )

    if not seeds:
        topic_text = _text(topic) or _text(handoff.get("topic")) or "the stated research topic"
        fallback_gap_id = stable_identifier("topic_gap", topic_text)
        seeds.append(
            {
                "schema_version": GAP_HYPOTHESIS_BRIDGE_SCHEMA_VERSION,
                "seed_id": stable_identifier("gap_seed", fallback_gap_id, "topic_seed", resolved_profile_id),
                "gap_id": fallback_gap_id,
                "subhypothesis_id": "GLOBAL",
                "gap_statement": f"The unresolved mechanism or relation in {topic_text} remains to be determined.",
                "gap_kind": "topic_seed",
                "target_slot": "scientific_constraint",
                "target_object": topic_text,
                "priority": "medium",
                "gap_route": "exploratory_frontier",
                "profile_id": resolved_profile_id,
                "why_it_matters": "Provides a fail-open starting point when Survey did not expose a usable gap.",
                "known_evidence": [],
                "unknown_or_unverified": ["Survey gap evidence is unavailable or excluded."],
                "source_anchors": [],
                "evidence_roles": [],
                "scope": dict(resolved_scope),
                "candidate_defect_tags": ["unexplored_gap"],
                "candidate_contribution_modes": [],
                "confidence": 0.0,
                "seed_status": "unanchored",
                "audit_status": "unverified",
                "verification_status": "not_checked",
                "fallback": True,
            }
        )

    seeds.sort(
        key=lambda seed: (
            0 if seed.get("analysis_priority") == DATA_ANCHORED_PRIORITY else 1,
            _ROUTE_RANK.get(_text(seed.get("gap_route")), 9),
            _PRIORITY_RANK.get(_text(seed.get("priority")), 1),
            -float(seed.get("confidence") or 0.0),
            _text(seed.get("gap_id")),
        )
    )
    return seeds


def build_gap_seed_status(seeds: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Return a compact, non-gating summary for logging and root state metadata."""

    records = [dict(seed) for seed in seeds if isinstance(seed, Mapping)]
    route_counts: dict[str, int] = {}
    status_counts: dict[str, int] = {}
    for seed in records:
        route = _text(seed.get("gap_route")) or "unknown"
        status = _text(seed.get("seed_status")) or "unknown"
        route_counts[route] = route_counts.get(route, 0) + 1
        status_counts[status] = status_counts.get(status, 0) + 1
    return {
        "schema_version": GAP_HYPOTHESIS_BRIDGE_SCHEMA_VERSION,
        "seed_count": len(records),
        "seed_ids": [_text(seed.get("seed_id")) for seed in records if _text(seed.get("seed_id"))],
        "gap_ids": [_text(seed.get("gap_id")) for seed in records if _text(seed.get("gap_id"))],
        "route_counts": route_counts,
        "status_counts": status_counts,
        "fallback_used": any(bool(seed.get("fallback")) for seed in records),
        "admission_mode": "fail_open_except_explicit_exclusion",
    }


def build_gap_seed_context(seeds: Sequence[Mapping[str, Any]]) -> str:
    """Render deterministic seed context for later MCTS prompts."""

    lines = ["== Gap-to-Hypothesis Seeds =="]
    for index, seed in enumerate(seeds, start=1):
        lines.extend(
            [
                f"{index}. seed_id={_text(seed.get('seed_id'))} route={_text(seed.get('gap_route'))} status={_text(seed.get('seed_status'))}",
                f"   gap_id={_text(seed.get('gap_id'))} target_slot={_text(seed.get('target_slot'))} target_object={_text(seed.get('target_object'))}",
                f"   statement={_text(seed.get('gap_statement'))}",
                f"   candidate_defect_tags={', '.join(_texts(seed.get('candidate_defect_tags'))) or 'unexplored_gap'}",
                f"   known_evidence={'; '.join(_texts(seed.get('known_evidence'))) or 'none supplied'}",
                f"   unknown_or_unverified={'; '.join(_texts(seed.get('unknown_or_unverified'))) or 'not specified'}",
            ]
        )
        if seed.get("analysis_priority") == DATA_ANCHORED_PRIORITY:
            lines.extend(
                [
                    f"   data_anchor_refs={', '.join(_texts(seed.get('data_anchor_refs'))) or 'none'}",
                    f"   literature_reconciliation_status={_text(seed.get('literature_reconciliation_status')) or 'unresolved'}",
                    f"   competing_explanations={'; '.join(_texts(seed.get('competing_explanations'))) or 'must remain open'}",
                    f"   measurement_needs={'; '.join(_texts(seed.get('measurement_needs'))) or 'a discriminating measurement is required'}",
                    "   data_coverage_branches=candidate_mechanism | alternative_explanation | measurement_artifact",
                ]
            )
    return "\n".join(lines)


__all__ = [
    "GAP_HYPOTHESIS_BRIDGE_SCHEMA_VERSION",
    "build_gap_hypothesis_seeds",
    "build_gap_seed_context",
    "build_gap_seed_status",
]
