"""Project accepted Survey gaps into the compact Idea handoff contract."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from .survey_idea_handoff import (
    EVIDENCE_ROLES,
    AnchorRecord,
    EvidenceEligibility,
    EvidenceRoleRecord,
    GapRecord,
    ProfileResolution,
    ScopeRecord,
    SourcePointer,
    SurveyIdeaHandoff,
    build_handoff_payload,
    validate_gap_ledger_payload,
)
from .survey_gap_triage import build_gap_triage_artifact


_ROLE_ALIASES = {
    "COMPARATIVE_OR_MEASUREMENT_EVIDENCE": "COMPARATIVE_EVIDENCE",
    "COMPARATIVE_MEASUREMENT_EVIDENCE": "COMPARATIVE_EVIDENCE",
    "LIMITING_OR_CHALLENGING_EVIDENCE": "COUNTEREVIDENCE",
    "LIMITING_CHALLENGING_EVIDENCE": "COUNTEREVIDENCE",
}
_ACCEPTED_DECISIONS = frozenset({"accept", "merge"})


def _text(value: Any) -> str:
    return str(value or "").strip()


def _texts(value: Any) -> list[str]:
    values = value if isinstance(value, (list, tuple, set, frozenset)) else [value]
    result: list[str] = []
    seen: set[str] = set()
    for item in values:
        text = _text(item)
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _records(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, Mapping):
        return [dict(value)]
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [dict(item) for item in value if isinstance(item, Mapping)]
    return []


def _load_mapping(source: Mapping[str, Any] | str | Path | None, label: str) -> dict[str, Any]:
    if source is None:
        return {}
    if isinstance(source, Mapping):
        return dict(source)
    path = Path(source)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(f"Unable to read {label}: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"{label} is not valid JSON: {path}") from exc
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must contain a JSON object: {path}")
    return dict(value)


def _source_pointer(value: Any) -> SourcePointer | None:
    payload = _mapping(value)
    if not _text(payload.get("artifact")) or not _text(payload.get("json_pointer")):
        return None
    return SourcePointer(
        artifact=_text(payload.get("artifact")),
        json_pointer=_text(payload.get("json_pointer")),
        paper_id=_text(payload.get("paper_id")),
        section=_text(payload.get("section")),
        page=payload.get("page") if isinstance(payload.get("page"), int) else None,
        paragraph_index=(
            payload.get("paragraph_index")
            if isinstance(payload.get("paragraph_index"), int)
            else None
        ),
    )


def _profile_resolution(value: Any) -> ProfileResolution:
    payload = _mapping(value)
    confidence = payload.get("confidence")
    try:
        confidence = float(confidence) if confidence is not None else None
    except (TypeError, ValueError):
        confidence = None
    return ProfileResolution(
        status=_text(payload.get("status")) or "unresolved",
        source=_text(payload.get("source")),
        primary_discipline=_text(payload.get("primary_discipline")),
        discipline_ids=_texts(payload.get("discipline_ids")),
        openalex_field_ids=_texts(payload.get("openalex_field_ids")),
        paperseek_field_ids=_texts(payload.get("paperseek_field_ids")),
        profile_id_hint=_text(payload.get("profile_id_hint")),
        confidence=confidence,
        requires_human_confirmation=bool(payload.get("requires_human_confirmation")),
        unresolved_reason=_text(payload.get("unresolved_reason") or payload.get("reason")),
    )


def _eligibility(value: Any) -> EvidenceEligibility:
    payload = _mapping(value)
    return EvidenceEligibility(
        required_roles=[role for role in _texts(payload.get("required_roles")) if role in EVIDENCE_ROLES],
        allowed_claim_modes=_texts(payload.get("allowed_claim_modes")),
        forbidden_paper_ids=_texts(payload.get("forbidden_paper_ids")),
        direct_writing_blocked_paper_ids=_texts(payload.get("direct_writing_blocked_paper_ids")),
        claim_limits=_texts(payload.get("claim_limits")),
    )


def _gap_from_ledger(payload: Mapping[str, Any]) -> GapRecord:
    source = _source_pointer(payload.get("source_pointer"))
    return GapRecord(
        gap_id=_text(payload.get("gap_id")),
        subhypothesis_id=_text(payload.get("subhypothesis_id")) or "GLOBAL",
        gap_kind=_text(payload.get("gap_kind")),
        target_slot=_text(payload.get("target_slot")),
        statement=_text(payload.get("statement")),
        status="open",
        priority=_text(payload.get("priority")) or "medium",
        support_level=_text(payload.get("support_level")) or "authoritative",
        target_object=_text(payload.get("target_object")),
        why_it_matters=_text(payload.get("why_it_matters")),
        candidate_defect_tags=_texts(payload.get("candidate_defect_tags")),
        candidate_contribution_modes=_texts(payload.get("candidate_contribution_modes")),
        evidence_eligibility=_eligibility(payload.get("evidence_eligibility")),
        source_pointer=source,
        gap_group_id=_text(payload.get("gap_group_id")),
        source_kind=_text(payload.get("source_kind")) or "deterministic_gap_ledger",
        gap_audit=_mapping(payload.get("gap_audit")),
    )


def _gap_from_candidate(candidate: Mapping[str, Any], group_id: str) -> GapRecord | None:
    source = next(
        (
            pointer
            for pointer in (_source_pointer(value) for value in _records(candidate.get("source_pointers")))
            if pointer is not None
        ),
        None,
    )
    if source is None:
        return None
    role = _text(candidate.get("evidence_role"))
    if role in _ROLE_ALIASES:
        role = _ROLE_ALIASES[role]
    return GapRecord.create(
        subhypothesis_id=_text(candidate.get("subhypothesis_id")) or "GLOBAL",
        gap_kind=_text(candidate.get("gap_kind")) or "unmapped_gap:accepted_candidate",
        target_slot=_text(candidate.get("target_slot")) or "scientific_constraint",
        statement=_text(candidate.get("statement")),
        target_object=_text(candidate.get("claim_scope")),
        priority="medium",
        support_level=_text(candidate.get("support_level")) or "cross_source",
        why_it_matters=_text(candidate.get("rationale")),
        candidate_defect_tags=_texts(candidate.get("candidate_defect_tags")),
        candidate_contribution_modes=_texts(candidate.get("candidate_contribution_modes")),
        evidence_eligibility=EvidenceEligibility(
            required_roles=[role] if role in EVIDENCE_ROLES else [],
            claim_limits=_texts(candidate.get("claim_scope")),
        ),
        source_pointer=source,
        gap_group_id=group_id,
        source_kind="accepted_llm_gap_candidate",
        gap_audit={
            "candidate_id": _text(candidate.get("candidate_id")),
            "existence_confidence": candidate.get("confidence", 0.5),
        },
    )


def _accepted_candidate_gaps(adjudication: Mapping[str, Any]) -> list[GapRecord]:
    synthesis = _mapping(adjudication.get("synthesis"))
    groups = {
        _text(group.get("group_id")): group
        for group in _records(synthesis.get("groups"))
        if _text(group.get("group_id"))
    }
    accepted: list[GapRecord] = []
    for decision in _records(adjudication.get("decisions")):
        if _text(decision.get("decision")) not in _ACCEPTED_DECISIONS:
            continue
        group_id = _text(decision.get("group_id"))
        group = groups.get(group_id)
        if group is None:
            continue
        candidate = _mapping(group.get("representative"))
        gap = _gap_from_candidate(candidate, group_id)
        if gap is not None:
            accepted.append(gap)
    return accepted


def _anchor_for_gap(gap: GapRecord) -> AnchorRecord:
    pointer = gap.source_pointer
    source_id = ""
    if pointer is not None:
        source_id = ":".join(
            [pointer.artifact, pointer.json_pointer, pointer.paper_id, pointer.section]
        )
    return AnchorRecord.create(
        anchor_type="gap_evidence_anchor",
        label=f"{gap.subhypothesis_id}: {gap.target_slot}",
        subhypothesis_id=gap.subhypothesis_id,
        target_slot=gap.target_slot,
        source_id=source_id,
        claim_anchor=gap.statement,
        text_excerpt=gap.statement,
        paper_ids=[pointer.paper_id] if pointer and pointer.paper_id else [],
        supports_gap_ids=[gap.gap_id],
        source_pointer=pointer,
    )


def _normalized_role(value: Any) -> str:
    role = _text(value)
    role = _ROLE_ALIASES.get(role, role)
    return role if role in EVIDENCE_ROLES else ""


def _evidence_roles(
    evidence_plan: Mapping[str, Any],
    anchors_by_slot: Mapping[tuple[str, str], list[str]],
) -> list[EvidenceRoleRecord]:
    records: list[EvidenceRoleRecord] = []
    for subhypothesis in _records(evidence_plan.get("subhypotheses")):
        subhypothesis_id = _text(subhypothesis.get("sub_hypothesis_id")) or "GLOBAL"
        for target_slot, raw_support in _mapping(subhypothesis.get("slot_support")).items():
            support = _mapping(raw_support)
            expected_role = _normalized_role(support.get("expected_evidence_role"))
            if not expected_role:
                continue
            constraints = _mapping(support.get("qualified_paper_constraints"))
            forbidden = [
                _text(paper_id)
                for paper_id, values in constraints.items()
                if any(bool(item.get("forbidden_as_direct_evidence")) for item in _records(values))
            ]
            claim_limits = [
                limit
                for values in constraints.values()
                for item in _records(values)
                for limit in _texts(item.get("semantic_claim_limits"))
            ]
            records.append(
                EvidenceRoleRecord.create(
                    subhypothesis_id=subhypothesis_id,
                    target_slot=_text(target_slot),
                    expected_role=expected_role,
                    paper_ids=_texts(support.get("evidence_paper_ids")),
                    qualified_paper_ids=_texts(support.get("qualified_paper_ids")),
                    background_paper_ids=_texts(support.get("background_paper_ids")),
                    allowed_support_kinds=_texts(
                        [
                            support.get("minimum_evidence"),
                            support.get("admission_rule"),
                        ]
                    ),
                    forbidden_as_direct_evidence=forbidden,
                    claim_limits=claim_limits,
                    anchor_ids=list(anchors_by_slot.get((subhypothesis_id, _text(target_slot)), [])),
                )
            )
    return records


def _scope_from_context(project_context: Mapping[str, Any]) -> ScopeRecord:
    context = _mapping(project_context.get("research_context")) or dict(project_context)
    inventory = _mapping(context.get("research_design_inventory"))
    values: dict[str, list[str]] = {
        "research_object": [],
        "phenomenon": [],
        "target_conditions": [],
        "outcomes_or_readouts": [],
        "intervention_or_perturbation": [],
    }
    kind_map = {
        "research_object": "research_object",
        "target_relation": "phenomenon",
        "condition_or_regime": "target_conditions",
        "measurement": "outcomes_or_readouts",
        "outcome_or_construct": "outcomes_or_readouts",
        "method_or_design": "intervention_or_perturbation",
    }
    for item in _records(inventory.get("design_basis")):
        key = kind_map.get(_text(item.get("kind")))
        if key:
            values[key].extend(_texts(item.get("anchors")) or [_text(item.get("statement"))])
    identity = _mapping(context.get("research_identity"))
    values["research_object"].extend(_texts(identity.get("core_entities")))
    return ScopeRecord(
        research_object=_texts(values["research_object"]),
        phenomenon=_texts(values["phenomenon"]),
        target_conditions=_texts(values["target_conditions"]),
        intervention_or_perturbation=_texts(values["intervention_or_perturbation"]),
        outcomes_or_readouts=_texts(values["outcomes_or_readouts"]),
        in_scope=_texts([context.get("domain"), identity.get("label")]),
        out_of_scope=_texts(identity.get("must_not_be_primary")),
        claim_strength="qualified",
    )


def build_survey_idea_handoff_projection(
    *,
    gap_ledger: Mapping[str, Any] | str | Path,
    adjudication: Mapping[str, Any] | str | Path | None = None,
    evidence_plan: Mapping[str, Any] | str | Path | None = None,
    project_context: Mapping[str, Any] | str | Path | None = None,
    survey_json: Mapping[str, Any] | str | Path | None = None,
    source_artifacts: Mapping[str, Any] | None = None,
    created_at: str = "",
    triage_llm_call: Any = None,
) -> dict[str, Any]:
    """Project authoritative ledger gaps plus adjudicated candidates to Handoff v1."""

    ledger = _load_mapping(gap_ledger, "gap ledger")
    errors = validate_gap_ledger_payload(ledger, verify_fingerprint=bool(ledger.get("ledger_fingerprint")))
    if errors:
        raise ValueError("Invalid gap ledger for handoff projection: " + "; ".join(errors))
    plan = _load_mapping(evidence_plan, "evidence plan")
    if isinstance(plan.get("survey_evidence_plan"), Mapping):
        plan = dict(plan["survey_evidence_plan"])
    context = _load_mapping(project_context, "project context")
    survey = _load_mapping(survey_json, "survey JSON")
    adjudication_payload = _load_mapping(adjudication, "gap adjudication")
    deterministic = [
        _gap_from_ledger(gap)
        for gap in _records(ledger.get("gaps"))
        if _text(gap.get("status")) not in {"out_of_scope", "rejected"}
    ]
    occupied = {(gap.subhypothesis_id, gap.gap_kind, gap.target_slot) for gap in deterministic}
    accepted = [
        gap
        for gap in _accepted_candidate_gaps(adjudication_payload)
        if (gap.subhypothesis_id, gap.gap_kind, gap.target_slot) not in occupied
    ]
    gaps = [*deterministic, *accepted]
    anchors = [_anchor_for_gap(gap) for gap in gaps]
    anchors_by_slot: dict[tuple[str, str], list[str]] = {}
    for gap, anchor in zip(gaps, anchors):
        anchors_by_slot.setdefault((gap.subhypothesis_id, gap.target_slot), []).append(anchor.anchor_id)
    gaps = [
        GapRecord(
            **{
                **gap.__dict__,
                "anchor_ids": anchors_by_slot[(gap.subhypothesis_id, gap.target_slot)],
            }
        )
        for gap in gaps
    ]
    triage_ledger = dict(ledger)
    triage_ledger["gaps"] = [gap.to_payload() for gap in gaps]
    triage_ledger["candidate_gaps"] = []
    gap_triage = build_gap_triage_artifact(
        gap_ledger=triage_ledger,
        profile_resolution=_mapping(ledger.get("profile_resolution")),
        llm_call=triage_llm_call if callable(triage_llm_call) else None,
    )
    triage_by_id = {
        _text(item.get("gap_id")): item
        for item in _records(gap_triage.get("gaps"))
        if _text(item.get("gap_id"))
    }
    gaps = [
        GapRecord(**{**gap.__dict__, "gap_audit": triage_by_id.get(gap.gap_id, {})})
        for gap in gaps
    ]
    project_id = _text(ledger.get("project_id"))
    survey_run_id = _text(ledger.get("survey_run_id"))
    topic = _text(survey.get("topic")) or _text(
        _mapping(context.get("research_context")).get("original_topic")
    )
    if not topic:
        topic = _text(context.get("domain")) or "Survey research project"
    artifacts = {
        "survey_markdown": "survey.md",
        "survey_json": "survey.json",
        "project_context": "project_context.json",
        "evidence_plan": "survey_evidence_plan.json",
        "claim_traceability": "survey_claim_traceability.json",
        "gap_ledger": "survey_gap_ledger.json",
        "gap_triage": "survey_gap_triage.json",
        "idea_handoff": "survey_idea_handoff.json",
    }
    artifacts.update(dict(source_artifacts or {}))
    handoff = SurveyIdeaHandoff(
        project_id=project_id,
        survey_run_id=survey_run_id,
        topic=topic,
        project_context_fingerprint=_text(ledger.get("project_context_fingerprint")),
        gaps=gaps,
        anchors=anchors,
        evidence_roles=_evidence_roles(plan, anchors_by_slot),
        profile_resolution=_profile_resolution(ledger.get("profile_resolution")),
        scope=_scope_from_context(context),
        constraints={
            "may_generate_new_gap": False,
            "accepted_candidate_decisions": sorted(_ACCEPTED_DECISIONS),
            "evidence_bounded_writing": bool(plan.get("evidence_bounded_writing")),
            "requires_human_confirmation": bool(
                _mapping(ledger.get("profile_resolution")).get("requires_human_confirmation")
            ),
        },
        gap_triage=gap_triage,
        source_artifacts=artifacts,
        created_at=_text(created_at),
        status="ready" if gaps else "partial",
    )
    return build_handoff_payload(handoff)


project_accepted_gaps_to_handoff = build_survey_idea_handoff_projection


__all__ = [
    "build_survey_idea_handoff_projection",
    "project_accepted_gaps_to_handoff",
]
