"""Fail-open, post-synthesis scientific debate for Idea Agent directions."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
from itertools import combinations
import json
from typing import Any, Dict, Iterable, List, Mapping, Optional

from src.agents.idea_agent.agent.prompts.scientific_debate import SCIENTIFIC_DEBATE_PROMPT
from src.agents.idea_agent.utils.core.json_utils import pretty_json
from src.agents.idea_agent.utils.mcts.scientific_intervention_ontology import (
    detect_profile_drift,
    format_scientific_intervention_profile_for_prompt,
    get_scientific_intervention_profile,
)
from src.agents.idea_agent.utils.workflow.idea_contract import normalize_idea_contract
from src.agents.idea_agent.utils.workflow.idea_diversity import compare_mature_ideas


DEBATE_ROUNDS = (1, 2)
DEBATE_PROMPT_CHAR_LIMIT = 120_000
INTERNAL_DEBATE_PROMPT_LIMIT = 80_000
CROSS_SEED_DEBATE_PROMPT_LIMIT = 60_000
IMMUTABLE_IDENTITY_FIELDS = (
    "idea_id",
    "seed_id",
    "target_gap_ids",
    "route_id",
    "route_signature",
    "lineage",
)
_DEBATE_CANDIDATE_FIELDS = (
    "direction_mode",
    "idea_taste_mode",
    "direction_summary",
    "title",
    "abstract",
    "core_contribution",
    "central_hypothesis",
    "mechanism_or_relation",
    "expected_mechanism",
    "discriminating_observation",
    "boundary_or_failure_condition",
    "claim_scope",
    "assumptions",
    "alternative_explanations",
    "gap_alignment",
    "evidence_requirement",
    "evidence_basis",
    "falsifier",
    "risks",
    "target_gap_ids",
    "scientific_object",
    "intervention_or_transformation",
    "independence_status",
    "refinement_scope",
    "scientific_intervention",
)
_DEBATE_INTERVENTION_FIELDS = (
    "profile_id",
    "profile_label",
    "contribution_mode",
    "scientific_object_schema",
    "object_roles",
    "allowed_operations",
    "evidence_obligations",
    "boundary_obligations",
    "measurement_or_observation_roles",
    "route_contract_incomplete_fields",
    "route_contract_noop_fields",
    "route_contract_parent_values",
)
ALLOWED_REVISION_FIELDS = (
    "abstract",
    "core_contribution",
    "central_hypothesis",
    "scientific_object",
    "intervention_or_transformation",
    "mechanism_or_relation",
    "expected_mechanism",
    "discriminating_observation",
    "boundary_or_failure_condition",
    "claim_scope",
    "assumptions",
    "alternative_explanations",
    "gap_alignment",
    "evidence_requirement",
    "evidence_basis",
    "risks",
    "falsifier",
)
DEBATE_STATUSES = {
    "SCIENTIFICALLY_QUALIFIED",
    "SCIENTIFICALLY_QUALIFIED_WITH_UNCERTAINTY",
    "NEEDS_SCOPE_REDUCTION",
    "PROFILE_DRIFT",
    "REQUIRES_REVIEW",
    "LOWER_CONFIDENCE",
}
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
_ROUTE_CONTRACT_FIELDS = {
    "premise_inversion": ("central_hypothesis",),
    "object_substitution": ("scientific_object",),
    "mechanism_replacement": ("mechanism_or_relation", "expected_mechanism"),
    "representation_shift": ("intervention_or_transformation",),
    "verification_reversal": ("discriminating_observation",),
}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _list(value: Any) -> List[str]:
    if value is None:
        return []
    values = value if isinstance(value, (list, tuple)) else [value]
    return [item for item in (_text(item) for item in values) if item]


def _profile_id(direction: Mapping[str, Any], profile_id: str = "") -> str:
    if profile_id:
        return _text(profile_id).lower()
    intervention = direction.get("scientific_intervention")
    if isinstance(intervention, Mapping):
        return _text(intervention.get("profile_id") or "generic_scientific").lower()
    return "generic_scientific"


def _gap_ids(direction: Mapping[str, Any]) -> List[str]:
    raw = direction.get("target_gap_ids")
    return _list(raw)


def _status(value: Any, default: str) -> str:
    normalized = _text(value).upper()
    return normalized if normalized in DEBATE_STATUSES else default


def _severity(value: Any) -> str:
    normalized = _text(value).lower()
    return normalized if normalized in {"none", "minor", "moderate", "major"} else "none"


def _sanitize_candidate(candidate: Mapping[str, Any]) -> Dict[str, Any]:
    sanitized = deepcopy(dict(candidate))
    for field_name in EXPERIMENT_FIELDS:
        sanitized.pop(field_name, None)
    return sanitized


def _compact_prompt_value(value: Any, *, max_text: int = 4_000, max_items: int = 8) -> Any:
    """Bound values embedded in Debate prompts without changing the candidate."""

    if isinstance(value, str):
        text = value.strip()
        return text if len(text) <= max_text else text[: max_text - 3].rstrip() + "..."
    if isinstance(value, Mapping):
        return {
            str(key): _compact_prompt_value(item, max_text=max_text, max_items=max_items)
            for key, item in list(value.items())[:max_items]
        }
    if isinstance(value, (list, tuple)):
        return [
            _compact_prompt_value(item, max_text=max_text, max_items=max_items)
            for item in list(value)[:max_items]
        ]
    return value


def _is_populated(value: Any) -> bool:
    return value not in (None, "", [], {})


def _contract_value_signature(value: Any) -> str:
    if isinstance(value, (Mapping, list, tuple, set, frozenset)):
        try:
            return json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            pass
    return " ".join(_text(value).casefold().split())


def _has_route_material_change(
    route_id: str,
    candidate: Mapping[str, Any],
    parent_values: Mapping[str, Any],
) -> bool:
    route_fields = _ROUTE_CONTRACT_FIELDS.get(route_id, ())
    return any(
        _is_populated(candidate.get(field_name))
        and (
            not _is_populated(parent_values.get(field_name))
            or _contract_value_signature(candidate.get(field_name))
            != _contract_value_signature(parent_values.get(field_name))
        )
        for field_name in route_fields
    )


def effective_scientific_contract(direction: Mapping[str, Any]) -> Dict[str, Any]:
    """Resolve the scientific fields Debate should evaluate without losing lineage.

    MCTS payloads may expose a field at the top level, within the state-level
    hypothesis contract, or only on the mature seed.  Debate should read the
    same effective view across those representations, while revisions continue
    to obey the immutable identity constraints below.
    """

    effective: Dict[str, Any] = {}
    intervention = direction.get("scientific_intervention")
    intervention = intervention if isinstance(intervention, Mapping) else {}
    seed_records: List[Mapping[str, Any]] = []
    for field_name in ("mature_idea_record", "mature_idea", "seed", "root_idea"):
        source = direction.get(field_name)
        if isinstance(source, Mapping):
            seed_records.append(source)
    embedded_seed = intervention.get("mature_idea_record")
    if isinstance(embedded_seed, Mapping):
        seed_records.append(embedded_seed)

    seed_aliases = {
        "central_hypothesis": "hypothesis",
        "mechanism_or_relation": "mechanism",
        "claim_scope": "refinement_scope",
    }
    for seed in seed_records:
        for field_name in _DEBATE_CANDIDATE_FIELDS:
            value = seed.get(field_name)
            if not _is_populated(value):
                alias = seed_aliases.get(field_name)
                value = seed.get(alias) if alias else None
            if _is_populated(value):
                effective.setdefault(field_name, deepcopy(value))

    nested_contract = intervention.get("hypothesis_contract")
    if isinstance(nested_contract, Mapping):
        for field_name, value in nested_contract.items():
            if _is_populated(value):
                effective[field_name] = deepcopy(value)

    for field_name in _DEBATE_CANDIDATE_FIELDS:
        value = direction.get(field_name)
        if _is_populated(value):
            effective[field_name] = deepcopy(value)
    effective["scientific_intervention"] = dict(intervention)
    return effective


def _debate_candidate_view(direction: Mapping[str, Any]) -> Dict[str, Any]:
    effective = effective_scientific_contract(direction)
    view: Dict[str, Any] = {}
    for field_name in _DEBATE_CANDIDATE_FIELDS:
        if field_name not in effective:
            continue
        value = effective.get(field_name)
        if field_name == "scientific_intervention" and isinstance(value, Mapping):
            value = {
                key: value.get(key)
                for key in _DEBATE_INTERVENTION_FIELDS
                if key in value
            }
        view[field_name] = _compact_prompt_value(value)
    return view


def _immutable_identity_snapshot(candidate: Mapping[str, Any]) -> Dict[str, Any]:
    return {field: deepcopy(candidate.get(field)) for field in IMMUTABLE_IDENTITY_FIELDS if field in candidate}


def _identity_violations(
    original: Mapping[str, Any],
    attempted: Any,
    revised: Mapping[str, Any],
) -> List[Dict[str, Any]]:
    if not isinstance(attempted, Mapping):
        return []
    violations: List[Dict[str, Any]] = []
    for field in IMMUTABLE_IDENTITY_FIELDS:
        if field not in attempted:
            continue
        before = deepcopy(original.get(field))
        proposed = deepcopy(attempted.get(field))
        if proposed == before:
            continue
        violations.append(
            {
                "violation_type": "gap_mapping_violation" if field == "target_gap_ids" else "identity_violation",
                "field": field,
                "attempted_value": proposed,
                "restored_value": deepcopy(revised.get(field, before)),
            }
        )
    return violations


def _debate_handoff_view(
    survey_handoff: Any,
    target_gap_ids: Iterable[str],
) -> Dict[str, Any]:
    if not isinstance(survey_handoff, Mapping):
        return {}
    target_ids = set(_list(target_gap_ids))
    view: Dict[str, Any] = {}
    for field_name in ("survey_run_id", "project_id", "topic", "profile_resolution", "scope", "constraints"):
        if field_name in survey_handoff:
            view[field_name] = _compact_prompt_value(survey_handoff.get(field_name))
    gaps = []
    for gap in survey_handoff.get("gaps", []):
        if not isinstance(gap, Mapping):
            continue
        gap_id = _text(gap.get("gap_id"))
        if target_ids and gap_id not in target_ids:
            continue
        gaps.append(
            _compact_prompt_value(
                {
                    key: gap.get(key)
                    for key in (
                        "gap_id",
                        "subhypothesis_id",
                        "gap_kind",
                        "target_slot",
                        "statement",
                        "status",
                        "priority",
                        "support_level",
                        "gap_audit",
                    )
                    if key in gap
                }
            )
        )
        if len(gaps) >= 8:
            break
    if gaps:
        view["gaps"] = gaps
    triage = survey_handoff.get("gap_triage")
    if isinstance(triage, Mapping):
        rows = [
            row for row in triage.get("gaps", [])
            if isinstance(row, Mapping)
            and (not target_ids or _text(row.get("gap_id")) in target_ids)
        ]
        if rows:
            view["gap_triage"] = _compact_prompt_value({"gaps": rows[:8]})
    return view


def _baseline_concerns(
    direction: Mapping[str, Any],
    *,
    profile_drift: Mapping[str, Any],
    round_number: int,
) -> Dict[str, Any]:
    candidate = effective_scientific_contract(direction)
    gap_ids = _gap_ids(candidate)
    concerns: List[str] = []
    alternatives: List[str] = []
    changed_field: List[str] = []
    actual_missing_fields: List[str] = []
    profile_drift_fields: List[str] = []
    severity = "none"
    required_revision = ""
    if round_number == 1:
        question_type = "scientific_consistency"
        if not gap_ids:
            concerns.append("The candidate has no explicit target_gap_ids.")
            changed_field.append("target_gap_ids")
            actual_missing_fields.append("target_gap_ids")
            severity = "major"
            required_revision = "Keep the candidate but mark its scope as needing Gap alignment review."
        if not _text(candidate.get("central_hypothesis")):
            concerns.append("The central hypothesis cannot be read as a standalone claim.")
            changed_field.append("central_hypothesis")
            actual_missing_fields.append("central_hypothesis")
            severity = "major"
            required_revision = "State one direction-specific, uncertainty-calibrated hypothesis."
        if not _text(candidate.get("mechanism_or_relation") or candidate.get("expected_mechanism")):
            concerns.append("The mechanism or relation is underspecified.")
            changed_field.append("mechanism_or_relation")
            actual_missing_fields.append("mechanism_or_relation")
            severity = "major"
            required_revision = "Name the profile-native mechanism or relation that links intervention and observation."
        if not _list(candidate.get("assumptions")):
            concerns.append("The candidate does not expose its operating assumptions.")
            changed_field.append("assumptions")
            actual_missing_fields.append("assumptions")
            severity = max(severity, "moderate", key=("none", "minor", "moderate", "major").index)
            required_revision = "State the minimum assumptions needed for the mechanism."
        if not _text(candidate.get("refinement_scope") or candidate.get("claim_scope")):
            concerns.append("The refinement scope is not explicit.")
            changed_field.append("claim_scope")
            actual_missing_fields.append("claim_scope")
            severity = max(severity, "moderate", key=("none", "minor", "moderate", "major").index)
            required_revision = "Bound the claim to the smallest defensible refinement scope."
        if _text(candidate.get("independence_status")).casefold() in {"collapsed_duplicate", "duplicate", "rejected"}:
            concerns.append("The candidate was marked non-independent by mature-idea adjudication.")
            changed_field.append("independence_status")
            severity = "major"
            required_revision = "Preserve the candidate identity and explain its substantive route difference."
        if profile_drift.get("drift_severity") == "material":
            concerns.append("A CS/ML concept appears to be the primary contribution for a non-computational profile.")
            changed_field.append("mechanism_or_relation")
            profile_drift_fields.append("mechanism_or_relation")
            severity = "major"
            required_revision = "Rewrite the primary contribution using the selected profile's native mechanism or process."
        elif profile_drift.get("drift_severity") == "soft":
            concerns.append("CS/ML terms appear as secondary analysis tools.")
            severity = "moderate"
            required_revision = "Keep the tool secondary and state the domain-native scientific claim first."
        intervention = candidate.get("scientific_intervention")
        incomplete_route_fields = (
            _list(intervention.get("route_contract_incomplete_fields"))
            if isinstance(intervention, Mapping)
            else []
        )
        if incomplete_route_fields:
            concerns.append(
                "The route-defining fields were inherited from the parent instead of being generated by this route: "
                + ", ".join(incomplete_route_fields)
                + "."
            )
            changed_field.extend(incomplete_route_fields)
            severity = "major"
            required_revision = "Supply a route-specific scientific field rather than relying on the parent contract."
        noop_route_fields = (
            _list(intervention.get("route_contract_noop_fields"))
            if isinstance(intervention, Mapping)
            else []
        )
        if noop_route_fields:
            concerns.append(
                "The route-defining fields only restate the parent contract instead of making a substantive change: "
                + ", ".join(noop_route_fields)
                + "."
            )
            changed_field.extend(noop_route_fields)
            severity = "major"
            required_revision = "Replace the inherited route field with a substantively different profile-native value."
    else:
        question_type = "scope_and_alternatives"
        claim_scope = _text(candidate.get("claim_scope"))
        if not claim_scope:
            concerns.append("The candidate does not state a boundary for its claim.")
            changed_field.append("claim_scope")
            severity = "moderate"
            required_revision = "Add a bounded validity or transfer scope."
        if not _text(candidate.get("boundary_or_failure_condition")):
            concerns.append("No explicit boundary or failure condition is stated.")
            changed_field.append("boundary_or_failure_condition")
            severity = max(severity, "moderate", key=("none", "minor", "moderate", "major").index)
            required_revision = "Add the smallest meaningful failure or validity boundary."
        alternatives = _list(candidate.get("alternative_explanations"))
        if not alternatives:
            alternatives = ["A competing mechanism or confounder could explain the same observation."]
    return {
        "question_type": question_type,
        "scientific_concern": " ".join(concerns),
        "opponent_concern": alternatives[0] if alternatives else "",
        "severity": severity,
        "required_revision": required_revision,
        "changed_field": list(dict.fromkeys(changed_field)),
        "actual_missing_fields": list(dict.fromkeys(actual_missing_fields)),
        "profile_drift_fields": list(dict.fromkeys(profile_drift_fields)),
        "alternative_explanations": alternatives,
    }


def _apply_revision(
    original: Mapping[str, Any],
    raw_revision: Any,
    *,
    direction_mode: str,
    original_gap_ids: List[str],
) -> tuple[Dict[str, Any], List[str], bool, bool]:
    revised = _sanitize_candidate(original)
    if isinstance(raw_revision, Mapping):
        for field_name in ALLOWED_REVISION_FIELDS:
            if field_name in raw_revision and raw_revision[field_name] not in (None, ""):
                value = deepcopy(raw_revision[field_name])
                if field_name == "scientific_object" and not isinstance(value, Mapping):
                    description = _text(value)
                    if not description:
                        continue
                    value = {"description": description}
                revised[field_name] = value
    changed_fields = [
        field_name
        for field_name in ALLOWED_REVISION_FIELDS
        if revised.get(field_name) != original.get(field_name)
    ]
    gap_violation = False
    revised["direction_mode"] = direction_mode
    revised["target_gap_ids"] = list(original_gap_ids)
    if isinstance(raw_revision, Mapping) and "target_gap_ids" in raw_revision:
        proposed_gap_ids = _list(raw_revision.get("target_gap_ids"))
        if proposed_gap_ids != original_gap_ids:
            gap_violation = True
            changed_fields.append("target_gap_ids")
    intervention = revised.get("scientific_intervention")
    if isinstance(intervention, Mapping):
        intervention = dict(intervention)
        incomplete_route_fields = _list(intervention.get("route_contract_incomplete_fields"))
        noop_route_fields = _list(intervention.get("route_contract_noop_fields"))
        parent_values = intervention.get("route_contract_parent_values")
        parent_values = parent_values if isinstance(parent_values, Mapping) else {}
        route_id = _text(original.get("route_id") or intervention.get("route_id"))
        if _has_route_material_change(route_id, revised, parent_values):
            incomplete_route_fields = []
            noop_route_fields = []
        if incomplete_route_fields:
            intervention["route_contract_incomplete_fields"] = incomplete_route_fields
        else:
            intervention.pop("route_contract_incomplete_fields", None)
        if noop_route_fields:
            intervention["route_contract_noop_fields"] = noop_route_fields
        else:
            intervention.pop("route_contract_noop_fields", None)
        if incomplete_route_fields or noop_route_fields:
            intervention["route_contract_parent_values"] = dict(parent_values)
        else:
            intervention.pop("route_contract_parent_values", None)
        revised["scientific_intervention"] = intervention
    try:
        normalized = normalize_idea_contract(revised, keep_extra=True)
    except (TypeError, ValueError):
        normalized = revised
    normalized["direction_mode"] = direction_mode
    normalized["target_gap_ids"] = list(original_gap_ids)
    for field_name in EXPERIMENT_FIELDS:
        normalized.pop(field_name, None)
    return normalized, list(dict.fromkeys(changed_fields)), bool(changed_fields), gap_violation


def _status_from_baseline(baseline: Mapping[str, Any]) -> str:
    if baseline.get("severity") == "major":
        if baseline.get("profile_drift_fields") and not baseline.get("actual_missing_fields"):
            return "PROFILE_DRIFT"
        return "NEEDS_SCOPE_REDUCTION"
    if baseline.get("severity") in {"minor", "moderate"}:
        return "SCIENTIFICALLY_QUALIFIED_WITH_UNCERTAINTY"
    return "SCIENTIFICALLY_QUALIFIED"


def _event_payload(
    payload: Mapping[str, Any],
    *,
    round_number: int,
    direction_mode: str,
    candidate: Mapping[str, Any],
    baseline: Mapping[str, Any],
    final_scope: str,
    final_status: str,
    revision_applied: bool,
    changed_fields: List[str],
) -> Dict[str, Any]:
    return {
        "round": round_number,
        "direction_mode": direction_mode,
        "question_type": _text(payload.get("question_type") or baseline.get("question_type")),
        "target_claim": _text(payload.get("target_claim") or candidate.get("central_hypothesis")),
        "scientific_concern": _text(payload.get("scientific_concern") or baseline.get("scientific_concern")),
        "opponent_concern": _text(payload.get("opponent_concern") or baseline.get("opponent_concern")),
        "severity": _severity(payload.get("severity") or baseline.get("severity")),
        "required_revision": _text(payload.get("required_revision") or baseline.get("required_revision")),
        "revision_applied": bool(revision_applied or payload.get("revision_applied", False)),
        "changed_field": _list(payload.get("changed_field") or changed_fields),
        "actual_missing_fields": _list(baseline.get("actual_missing_fields")),
        "profile_drift_fields": _list(baseline.get("profile_drift_fields")),
        "alternative_explanations": _list(
            payload.get("alternative_explanations") or baseline.get("alternative_explanations")
        ),
        "final_scope": _text(payload.get("final_scope") or final_scope),
        "final_status": final_status,
    }


def _fallback_event(
    *,
    round_number: int,
    direction_mode: str,
    candidate: Mapping[str, Any],
    baseline: Mapping[str, Any],
) -> Dict[str, Any]:
    default_status = _status_from_baseline(baseline)
    return _event_payload(
        baseline,
        round_number=round_number,
        direction_mode=direction_mode,
        candidate=candidate,
        baseline=baseline,
        final_scope=_text(candidate.get("claim_scope")),
        final_status=default_status,
        revision_applied=False,
        changed_fields=[],
    )


def _debate_prompt(
    *,
    topic: str,
    round_number: int,
    direction: Mapping[str, Any],
    profile_id: str,
    profile_context: str,
    survey_handoff: Any,
    profile_drift: Mapping[str, Any],
    baseline: Mapping[str, Any],
    prompt_limit: int = DEBATE_PROMPT_CHAR_LIMIT,
) -> str:
    prompt = SCIENTIFIC_DEBATE_PROMPT.format(
        topic=topic or "unspecified topic",
        round=round_number,
        question_type=baseline.get("question_type") or "scientific_consistency",
        direction_mode=_text(direction.get("direction_mode") or direction.get("idea_taste_mode")),
        direction_summary=_text(direction.get("direction_summary")),
        profile_id=profile_id,
        profile_context=profile_context or "Use the profile-native object schema already attached to the candidate.",
        survey_handoff=pretty_json(_debate_handoff_view(survey_handoff, _gap_ids(direction))),
        profile_drift=pretty_json(profile_drift),
        candidate=pretty_json(_debate_candidate_view(direction)),
        round_checks=pretty_json(dict(baseline)),
    )
    limit = max(2_000, int(prompt_limit or DEBATE_PROMPT_CHAR_LIMIT))
    if len(prompt) > limit:
        prompt = prompt[: limit - 80].rstrip() + "\n[Debate context truncated to the configured input budget.]"
    return prompt


def _cross_seed_prompt(
    *,
    topic: str,
    left: Mapping[str, Any],
    right: Mapping[str, Any],
    current_disputes: Any = None,
    prompt_limit: int,
) -> str:
    left_view = _debate_candidate_view(left)
    right_view = _debate_candidate_view(right)
    prompt = (
        "You are an adversarial scientific referee comparing two mature-idea candidates.\n"
        f"Topic: {topic or 'unspecified topic'}\n\n"
        "Compare only the bounded candidate views below. Do not merge their identity, "
        "seed, route, lineage, or target Gap mapping. Explain whether they are genuinely "
        "different mechanisms, objects, assumptions, or validation paths, which evidence "
        "would discriminate them, and whether both should be retained. Return JSON only.\n"
        "Candidate A:\n" + pretty_json(left_view) + "\nCandidate B:\n" + pretty_json(right_view) + "\n"
        "Current internal disputes:\n" + pretty_json(current_disputes or []) + "\n"
        "Schema: {\"same_mechanism\": false, \"conflicting_assumptions\": [], "
        "\"problem_redefinition\": \"\", \"local_repair_assessment\": \"\", "
        "\"discriminating_evidence\": [], \"retain_both\": true, \"rationale\": \"\"}"
    )
    limit = max(2_000, int(prompt_limit or CROSS_SEED_DEBATE_PROMPT_LIMIT))
    return prompt if len(prompt) <= limit else prompt[: limit - 80].rstrip() + "\n[Cross-seed context truncated.]"


def cross_seed_debate(
    directions: Iterable[Mapping[str, Any]],
    *,
    topic: str = "",
    runtime: Any = None,
    session: Any = None,
    workflow_name: str = "",
    model: str = "",
    logger: Any = None,
    max_rounds: int = 1,
    max_parallel_cross_seed: int = 1,
    prompt_limit: int = CROSS_SEED_DEBATE_PROMPT_LIMIT,
) -> Dict[str, Any]:
    """Run bounded pairwise comparisons across distinct mature-idea seeds."""

    candidates = [dict(item) for item in directions or [] if isinstance(item, Mapping)]
    representatives: Dict[str, Dict[str, Any]] = {}
    for item in candidates:
        seed_id = _text(item.get("seed_id") or item.get("idea_id") or "legacy-primary")
        current_score = float(item.get("search_score") or 0.0)
        previous = representatives.get(seed_id)
        if previous is None or current_score > float(previous.get("search_score") or 0.0):
            representatives[seed_id] = item
    pair_specs = list(combinations(representatives.values(), 2))

    def _log_pair_progress(
        event: str,
        pair_number: int,
        comparison: Mapping[str, Any],
        *,
        failure_reason: str = "",
    ) -> None:
        if logger is None:
            return
        try:
            if failure_reason:
                logger.warning(
                    "⚠️ Cross-seed debate pair %d/%d %s (left_seed_id=%s, right_seed_id=%s): %s",
                    pair_number,
                    len(pair_specs),
                    event,
                    comparison.get("left_seed_id"),
                    comparison.get("right_seed_id"),
                    failure_reason,
                )
            else:
                logger.info(
                    "⚖️ Cross-seed debate pair %d/%d %s (left_seed_id=%s, right_seed_id=%s).",
                    pair_number,
                    len(pair_specs),
                    event,
                    comparison.get("left_seed_id"),
                    comparison.get("right_seed_id"),
                )
        except Exception:
            pass

    def _compare_pair(
        pair_number: int,
        left: Mapping[str, Any],
        right: Mapping[str, Any],
    ) -> tuple[Dict[str, Any], Optional[Dict[str, Any]]]:
        comparison = {
            "left_idea_id": _text(left.get("idea_id")),
            "left_seed_id": _text(left.get("seed_id")),
            "right_idea_id": _text(right.get("idea_id")),
            "right_seed_id": _text(right.get("seed_id")),
            "same_mechanism": False,
            "conflicting_assumptions": [],
            "problem_redefinition": "",
            "local_repair_assessment": "",
            "discriminating_evidence": [],
            "retain_both": True,
            "rationale": "Pair retained for cross-seed comparison.",
        }
        _log_pair_progress("started", pair_number, comparison)
        structural = compare_mature_ideas(left, right)
        mechanism_similarity = max(
            structural.get("field_similarity", {}).get(field, 0.0)
            for field in ("mechanism", "mechanism_or_relation", "intervention_or_transformation")
        ) if structural.get("field_similarity") else 0.0
        comparison["same_mechanism"] = mechanism_similarity >= 0.72
        comparison["structural_comparison"] = structural
        disputes = {
            "left": list(left.get("debate_trace") or [])[-2:],
            "right": list(right.get("debate_trace") or [])[-2:],
        }
        comparison["current_internal_disputes"] = disputes
        if runtime is not None and callable(getattr(runtime, "llm_json", None)):
            try:
                payload = runtime.llm_json(
                    session=session,
                    stage="cross_seed_debate",
                    workflow_name=workflow_name or None,
                    op_name="cross_seed_debate_pair",
                    prompt=_cross_seed_prompt(topic=topic, left=left, right=right, current_disputes=disputes, prompt_limit=prompt_limit),
                    model=model or None,
                    temperature=0.1,
                    max_output_tokens=2048,
                )
                if isinstance(payload, list):
                    payload = payload[0] if payload else {}
                if isinstance(payload, Mapping):
                    for key in comparison:
                        if key in payload and key not in {"left_idea_id", "left_seed_id", "right_idea_id", "right_seed_id"}:
                            comparison[key] = deepcopy(payload[key])
            except Exception as exc:
                failure = {"pair": [comparison["left_seed_id"], comparison["right_seed_id"]], "reason": str(exc)}
                comparison["rationale"] = "Cross-seed debate failed; retain both candidates for review."
                _log_pair_progress("failed", pair_number, comparison, failure_reason=str(exc))
                return comparison, failure
        _log_pair_progress("completed", pair_number, comparison)
        return comparison, None

    worker_count = min(max(1, int(max_parallel_cross_seed or 1)), len(pair_specs)) if pair_specs else 1
    pair_results: List[tuple[Dict[str, Any], Optional[Dict[str, Any]]] | None] = [None] * len(pair_specs)
    if worker_count == 1:
        for index, (left, right) in enumerate(pair_specs):
            pair_results[index] = _compare_pair(index + 1, left, right)
    else:
        if logger is not None:
            try:
                logger.info(
                    "⚖️ Cross-seed debate scheduling %d pair(s) with up to %d parallel worker(s).",
                    len(pair_specs),
                    worker_count,
                )
            except Exception:
                pass
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            futures = {
                executor.submit(_compare_pair, index + 1, left, right): index
                for index, (left, right) in enumerate(pair_specs)
            }
            for future in as_completed(futures):
                pair_results[futures[future]] = future.result()

    pairs: List[Dict[str, Any]] = []
    failures: List[Dict[str, Any]] = []
    for result in pair_results:
        if result is None:
            continue
        comparison, failure = result
        pairs.append(comparison)
        if failure is not None:
            failures.append(failure)
    return {
        "mode": "cross_seed_pairwise",
        "round_count": max(0, int(max_rounds)) if pairs else 0,
        "representative_count": len(representatives),
        "representatives": [_debate_candidate_view(item) for item in representatives.values()],
        "pairs": pairs,
        "failures": failures,
    }


def debate_seed_portfolio(*args: Any, **kwargs: Any) -> Dict[str, Any]:
    """Compatibility alias for callers naming the cross-seed adjudication."""

    return cross_seed_debate(*args, **kwargs)


def _debate_single_direction(
    direction: Mapping[str, Any],
    *,
    topic: str,
    survey_handoff: Any,
    profile_id: str,
    profile_context: str,
    runtime: Any,
    session: Any,
    workflow_name: str,
    model: str,
    logger: Any,
    round_numbers: List[int],
    internal_prompt_limit: int,
) -> tuple[Dict[str, Any], List[Dict[str, Any]], List[Dict[str, str]]]:
    """Run sequential debate rounds for one isolated candidate."""

    current = _sanitize_candidate(direction)
    effective_initial = effective_scientific_contract(current)
    for field_name, value in effective_initial.items():
        if not _is_populated(current.get(field_name)) and _is_populated(value):
            current[field_name] = deepcopy(value)
    direction_mode = _text(current.get("direction_mode") or current.get("idea_taste_mode") or "default")
    current["direction_mode"] = direction_mode
    original_gap_ids = _gap_ids(current)
    resolved_profile_id = _profile_id(current, profile_id)
    direction_events: List[Dict[str, Any]] = []
    failures: List[Dict[str, str]] = []
    failure_reason = ""
    identity_snapshot = _immutable_identity_snapshot(current)
    for round_number in round_numbers:
        preflight_drift = detect_profile_drift(
            resolved_profile_id,
            candidate=effective_scientific_contract(current),
            survey_handoff=survey_handoff if isinstance(survey_handoff, Mapping) else None,
            research_object=current.get("scientific_object"),
        )
        preflight = _baseline_concerns(
            current,
            profile_drift=preflight_drift,
            round_number=round_number,
        )
        payload: Dict[str, Any] = {}
        if runtime is not None and callable(getattr(runtime, "llm_json", None)):
            try:
                debate_prompt = _debate_prompt(
                    topic=topic,
                    round_number=round_number,
                    direction=current,
                    profile_id=resolved_profile_id,
                    profile_context=profile_context,
                    survey_handoff=survey_handoff,
                    profile_drift=preflight_drift,
                    baseline=preflight,
                    prompt_limit=internal_prompt_limit,
                )
                if logger is not None:
                    try:
                        logger.info(
                            "Scientific debate prompt bounded: direction=%s round=%s chars=%d",
                            direction_mode,
                            round_number,
                            len(debate_prompt),
                        )
                    except Exception:
                        pass
                payload = runtime.llm_json(
                    session=session,
                    stage="scientific_debate",
                    workflow_name=workflow_name or None,
                    op_name=f"scientific_debate_round_{round_number}",
                    prompt=debate_prompt,
                    model=model or None,
                    temperature=0.1,
                    max_output_tokens=4096,
                )
                if isinstance(payload, list):
                    payload = payload[0] if payload else {}
                if not isinstance(payload, Mapping):
                    payload = {}
            except Exception as exc:
                failure_reason = str(exc)
                failures.append({"direction_mode": direction_mode, "round": str(round_number), "reason": failure_reason})
                direction_events.append(
                    {
                        **_fallback_event(
                            round_number=round_number,
                            direction_mode=direction_mode,
                            candidate=current,
                            baseline=preflight,
                        ),
                        "final_status": "REQUIRES_REVIEW",
                        "required_revision": "Debate call failed; retain the candidate and review its scientific scope.",
                        "preflight_missing": list(preflight.get("actual_missing_fields") or []),
                        "postflight_missing": list(preflight.get("actual_missing_fields") or []),
                        "preflight_changed_fields": list(preflight.get("changed_field") or []),
                        "postflight_changed_fields": list(preflight.get("changed_field") or []),
                        "preflight_profile_drift_fields": list(preflight.get("profile_drift_fields") or []),
                        "postflight_profile_drift_fields": list(preflight.get("profile_drift_fields") or []),
                        "preflight_severity": preflight.get("severity"),
                        "postflight_severity": preflight.get("severity"),
                        "termination_reason": "runtime_failure",
                    }
                )
                break

        revision_payload = payload.get("revised_candidate") if isinstance(payload, Mapping) else None
        if not isinstance(revision_payload, Mapping) and isinstance(payload, Mapping):
            revision_payload = payload.get("candidate")
        if not isinstance(revision_payload, Mapping) and isinstance(payload, Mapping):
            revision_payload = payload
        revised, changed_fields, revision_applied, gap_violation = _apply_revision(
            current,
            revision_payload,
            direction_mode=direction_mode,
            original_gap_ids=original_gap_ids,
        )
        identity_violations = _identity_violations(current, revision_payload, revised)
        immutable_violation = bool(identity_violations)
        if identity_violations:
            gap_violation = gap_violation or any(item.get("field") == "target_gap_ids" for item in identity_violations)
            changed_fields.extend(item.get("field") for item in identity_violations if item.get("field"))
            revised.update(deepcopy(identity_snapshot))
            revised["target_gap_ids"] = list(original_gap_ids)
        current = revised
        postflight_drift = detect_profile_drift(
            resolved_profile_id,
            candidate=effective_scientific_contract(current),
            survey_handoff=survey_handoff if isinstance(survey_handoff, Mapping) else None,
            research_object=current.get("scientific_object"),
        )
        postflight = _baseline_concerns(
            current,
            profile_drift=postflight_drift,
            round_number=round_number,
        )
        termination_reason = ""
        if immutable_violation:
            violated_fields = ", ".join(item.get("field", "") for item in identity_violations)
            postflight["scientific_concern"] = (
                _text(postflight.get("scientific_concern"))
                + f" Debate attempted to change immutable identity fields: {violated_fields}."
            ).strip()
            postflight["severity"] = "major"
            postflight["required_revision"] = "Preserve the original idea, seed, route, lineage, and Gap mapping."
            termination_reason = "immutable_gap_mapping_violation" if gap_violation else "immutable_identity_violation"
        elif postflight.get("severity") == "major":
            termination_reason = "post_revision_major_contract_violation"

        default_status = _status_from_baseline(postflight)
        proposed_status = _status(
            payload.get("final_status") if isinstance(payload, Mapping) else None,
            default_status,
        )
        event_status = default_status
        if proposed_status == "LOWER_CONFIDENCE" and default_status not in {"NEEDS_SCOPE_REDUCTION", "PROFILE_DRIFT"}:
            event_status = "LOWER_CONFIDENCE"
        if immutable_violation:
            event_status = "NEEDS_SCOPE_REDUCTION"
        if current.get("scientificity_status") == "LOWER_CONFIDENCE" and event_status == "SCIENTIFICALLY_QUALIFIED":
            event_status = "LOWER_CONFIDENCE"
        event = _event_payload(
            payload if isinstance(payload, Mapping) else {},
            round_number=round_number,
            direction_mode=direction_mode,
            candidate=current,
            baseline=postflight,
            final_scope=_text(current.get("claim_scope")),
            final_status=event_status,
            revision_applied=revision_applied,
            changed_fields=changed_fields,
        )
        if identity_violations:
            event["identity_violations"] = identity_violations
            event["gap_mapping_violation"] = any(
                item.get("violation_type") == "gap_mapping_violation" for item in identity_violations
            )
        event["preflight_missing"] = list(preflight.get("actual_missing_fields") or [])
        event["postflight_missing"] = list(postflight.get("actual_missing_fields") or [])
        event["preflight_changed_fields"] = list(preflight.get("changed_field") or [])
        event["postflight_changed_fields"] = list(postflight.get("changed_field") or [])
        event["preflight_profile_drift_fields"] = list(preflight.get("profile_drift_fields") or [])
        event["postflight_profile_drift_fields"] = list(postflight.get("profile_drift_fields") or [])
        event["preflight_severity"] = preflight.get("severity")
        event["postflight_severity"] = postflight.get("severity")
        event["termination_reason"] = termination_reason
        event["next_round"] = bool(
            not termination_reason and round_number < max(round_numbers)
        )
        direction_events.append(event)
        if termination_reason:
            break

    if logger is not None and direction_events:
        final_event = direction_events[-1]
        try:
            logger.info(
                "⚖️ Scientific debate completed: seed_id=%s route_id=%s rounds=%d "
                "preflight_missing=%s preflight_profile_drift=%s revision_applied=%s "
                "postflight_missing=%s postflight_profile_drift=%s status=%s "
                "next_round=%s termination_reason=%s.",
                _text(current.get("seed_id") or current.get("idea_id") or "legacy-primary"),
                _text(current.get("route_id") or direction_mode),
                len(direction_events),
                final_event.get("preflight_missing", []),
                final_event.get("preflight_profile_drift_fields", []),
                final_event.get("revision_applied", False),
                final_event.get("postflight_missing", []),
                final_event.get("postflight_profile_drift_fields", []),
                final_event.get("final_status"),
                final_event.get("next_round", False),
                final_event.get("termination_reason", ""),
            )
        except Exception:
            pass

    if not direction_events:
        direction_events.append(
            _fallback_event(
                round_number=1,
                direction_mode=direction_mode,
                candidate=current,
                baseline={
                    "question_type": "scientific_consistency",
                    "severity": "none",
                    "alternative_explanations": [],
                },
            )
        )
    final_status = direction_events[-1]["final_status"]
    if failure_reason:
        final_status = "REQUIRES_REVIEW"
    current["direction_mode"] = direction_mode
    current["target_gap_ids"] = original_gap_ids
    current["debate_trace"] = direction_events
    current["debate_status"] = final_status
    current["scientificity_status"] = final_status
    if failure_reason:
        current["debate_failure_reason"] = failure_reason
    return current, direction_events, failures


def debate_direction_set(
    directions: Iterable[Mapping[str, Any]],
    *,
    topic: str = "",
    survey_handoff: Any = None,
    profile_id: str = "",
    profile_context: str = "",
    runtime: Any = None,
    session: Any = None,
    workflow_name: str = "",
    model: str = "",
    logger: Any = None,
    max_rounds: int = 2,
    max_parallel_internal: int = 1,
    max_parallel_cross_seed: int = 1,
    internal_prompt_limit: int = INTERNAL_DEBATE_PROMPT_LIMIT,
    cross_seed_prompt_limit: int = CROSS_SEED_DEBATE_PROMPT_LIMIT,
    cross_seed_max_rounds: int = 1,
    run_cross_seed: bool = True,
) -> Dict[str, Any]:
    """Debate each direction independently and preserve candidates on failure."""

    round_numbers = [round_number for round_number in DEBATE_ROUNDS if round_number <= max(1, min(2, int(max_rounds)))]
    source_directions = [direction for direction in directions or [] if isinstance(direction, Mapping)]
    worker_count = min(max(1, int(max_parallel_internal or 1)), len(source_directions)) if source_directions else 1

    def _run_direction(direction: Mapping[str, Any]) -> tuple[Dict[str, Any], List[Dict[str, Any]], List[Dict[str, str]]]:
        return _debate_single_direction(
            direction,
            topic=topic,
            survey_handoff=survey_handoff,
            profile_id=profile_id,
            profile_context=profile_context,
            runtime=runtime,
            session=session,
            workflow_name=workflow_name,
            model=model,
            logger=logger,
            round_numbers=round_numbers,
            internal_prompt_limit=internal_prompt_limit,
        )

    direction_results: List[tuple[Dict[str, Any], List[Dict[str, Any]], List[Dict[str, str]]] | None] = [None] * len(source_directions)
    if worker_count == 1:
        for index, direction in enumerate(source_directions):
            direction_results[index] = _run_direction(direction)
    else:
        if logger is not None:
            try:
                logger.info(
                    "⚖️ Scientific debate scheduling %d directions with up to %d parallel worker(s).",
                    len(source_directions),
                    worker_count,
                )
            except Exception:
                pass
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            futures = {
                executor.submit(_run_direction, direction): index
                for index, direction in enumerate(source_directions)
            }
            for future in as_completed(futures):
                direction_results[futures[future]] = future.result()

    revised_directions: List[Dict[str, Any]] = []
    debate_trace: List[Dict[str, Any]] = []
    failures: List[Dict[str, str]] = []
    for result in direction_results:
        if result is None:
            continue
        current, direction_events, direction_failures = result
        revised_directions.append(current)
        debate_trace.extend(direction_events)
        failures.extend(direction_failures)

    cross_seed_result = cross_seed_debate(
        revised_directions,
        topic=topic,
        runtime=runtime,
        session=session,
        workflow_name=workflow_name,
        model=model,
        logger=logger,
        max_rounds=cross_seed_max_rounds,
        max_parallel_cross_seed=max_parallel_cross_seed,
        prompt_limit=cross_seed_prompt_limit,
    ) if run_cross_seed else {"mode": "disabled", "pairs": [], "failures": []}
    internal_events = [
        event
        for direction in revised_directions
        for event in direction.get("debate_trace", [])
        if isinstance(event, Mapping)
    ]
    first_round_events = [event for event in internal_events if event.get("round") == 1]
    second_round_events = [event for event in internal_events if event.get("round") == 2]
    debate_statistics = {
        "preflight_major_count": sum(
            event.get("preflight_severity") == "major" for event in first_round_events
        ),
        "repaired_after_round_1_count": sum(
            event.get("preflight_severity") == "major"
            and event.get("postflight_severity") != "major"
            and not event.get("termination_reason")
            for event in first_round_events
        ),
        "postflight_major_count": sum(
            event.get("postflight_severity") == "major" for event in internal_events
        ),
        "immutable_violation_count": sum(
            bool(event.get("termination_reason", "").startswith("immutable_"))
            for event in internal_events
        ),
        "qualified_after_round_2_count": sum(
            event.get("final_status")
            in {"SCIENTIFICALLY_QUALIFIED", "SCIENTIFICALLY_QUALIFIED_WITH_UNCERTAINTY", "LOWER_CONFIDENCE"}
            for event in second_round_events
        ),
    }
    result = {
        "debate_mode": "two_round_fail_open",
        "debate_layers": "internal_plus_cross_seed",
        "internal_debate": [
            {
                "idea_id": item.get("idea_id"),
                "seed_id": item.get("seed_id"),
                "status": item.get("debate_status"),
                "trace": item.get("debate_trace", []),
            }
            for item in revised_directions
        ],
        "cross_seed_debate": cross_seed_result,
        "directions": revised_directions,
        "debate_trace": debate_trace,
        "failures": failures,
        "statistics": debate_statistics,
        "round_count": len(round_numbers),
        "direction_count": len(revised_directions),
    }
    if logger is not None:
        try:
            logger.info(
                "⚖️ Scientific debate processed %d directions in %d configured round(s); failures=%d; "
                "cross-seed pairs=%d; preflight_major=%d; repaired_after_round_1=%d; "
                "postflight_major=%d; immutable_violations=%d; qualified_after_round_2=%d.",
                len(revised_directions),
                len(round_numbers),
                len(failures),
                len(cross_seed_result.get("pairs", [])),
                debate_statistics["preflight_major_count"],
                debate_statistics["repaired_after_round_1_count"],
                debate_statistics["postflight_major_count"],
                debate_statistics["immutable_violation_count"],
                debate_statistics["qualified_after_round_2_count"],
            )
        except Exception:
            pass
    return result


__all__ = [
    "debate_direction_set",
    "cross_seed_debate",
    "debate_seed_portfolio",
    "DEBATE_ROUNDS",
    "DEBATE_STATUSES",
]
