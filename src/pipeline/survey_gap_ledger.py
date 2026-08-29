"""Deterministic extraction of survey evidence gaps.

The gap ledger is intentionally compiled from structured Survey artifacts only.
It does not call an LLM, infer a discipline from topic words, or treat a paper
role as stronger than the evidence plan permits.  This keeps the Survey to Idea
boundary reproducible while leaving semantic gap synthesis for a later stage.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from .survey_idea_handoff import (
    EVIDENCE_ROLES,
    EvidenceEligibility,
    GapLedger,
    GapRecord,
    ProfileResolution,
    SourcePointer,
    build_gap_ledger_payload,
)


_ROLE_ALIASES = {
    "COMPARATIVE_OR_MEASUREMENT_EVIDENCE": "COMPARATIVE_EVIDENCE",
    "COMPARATIVE_MEASUREMENT_EVIDENCE": "COMPARATIVE_EVIDENCE",
    "LIMITING_OR_CHALLENGING_EVIDENCE": "COUNTEREVIDENCE",
    "LIMITING_CHALLENGING_EVIDENCE": "COUNTEREVIDENCE",
}

_SLOT_GAP_KINDS = {
    "formal_claim": "missing_assumption",
    "assumption": "missing_assumption",
    "validity_domain": "missing_boundary_condition",
    "target_condition": "missing_boundary_condition",
    "boundary_condition": "missing_boundary_condition",
    "comparator": "missing_comparator",
    "comparison_condition": "missing_comparator",
    "mapping_or_calibration": "measurement_construct_mismatch",
    "construct": "measurement_construct_mismatch",
    "direct_observation": "evidence_role_deficit",
    "candidate_mechanism": "mechanism_explanation_gap",
    "mechanism": "mechanism_explanation_gap",
    "discriminating_observation": "identifiability_gap",
    "identifiability": "identifiability_gap",
    "falsification_or_counterexample": "counterevidence_gap",
}

_GAP_TAGS = {
    "missing_assumption": ("missing_assumption", "proof_gap"),
    "missing_boundary_condition": ("missing_boundary_condition", "invalid_generalization"),
    "missing_comparator": ("missing_comparator",),
    "measurement_construct_mismatch": ("measurement_construct_mismatch",),
    "evidence_role_deficit": ("evidence_role_deficit",),
    "mechanism_explanation_gap": ("mechanism_explanation_gap",),
    "identifiability_gap": ("identifiability_gap",),
    "counterevidence_gap": ("counterevidence_gap",),
    "unsupported_causal_link": ("unsupported_causal_link",),
    "confounding_or_selection_bias": ("confounding_or_selection_bias",),
    "invalid_generalization": ("invalid_generalization", "missing_boundary_condition"),
    "insufficient_reproducibility": ("insufficient_reproducibility",),
    "proof_gap": ("proof_gap", "missing_assumption"),
}

_CONTRIBUTION_MODES = {
    "missing_assumption": ("formal_assumption", "theorem_refinement", "counterexample"),
    "missing_boundary_condition": ("boundary_condition", "domain_calibration", "counterexample"),
    "missing_comparator": ("comparator_design", "comparative_test"),
    "measurement_construct_mismatch": ("measurement_construct", "calibration"),
    "evidence_role_deficit": ("targeted_evidence_acquisition", "discriminating_observation"),
    "mechanism_explanation_gap": ("mechanistic_model", "causal_intervention"),
    "identifiability_gap": ("discriminating_observation", "measurement_design"),
    "counterevidence_gap": ("counterexample", "boundary_test"),
    "unsupported_causal_link": ("causal_design", "mechanistic_intervention"),
    "confounding_or_selection_bias": ("confounding_control", "sensitivity_analysis"),
    "invalid_generalization": ("boundary_condition", "transport_test"),
    "insufficient_reproducibility": ("replication_design", "protocol_specification"),
    "proof_gap": ("formal_assumption", "proof_obligation", "counterexample"),
}

_WHY_IT_MATTERS = {
    "missing_assumption": "Without the stated assumptions, the claim cannot be evaluated for validity.",
    "missing_boundary_condition": "Without a validity boundary, the claim may be generalized beyond the supported regime.",
    "missing_comparator": "Without a defined comparator, the direction and size of the claimed difference cannot be assessed.",
    "measurement_construct_mismatch": "A mismatch between the construct and its measurement weakens interpretation of the claim.",
    "evidence_role_deficit": "The available paper roles do not support the evidence strength required by this slot.",
    "mechanism_explanation_gap": "The observed relation lacks an identified mechanism that could distinguish competing explanations.",
    "identifiability_gap": "The available observations do not identify which explanation or parameter generated the result.",
    "counterevidence_gap": "The claim has not been tested against a stated limiting case or counterexample.",
    "unsupported_causal_link": "The causal interpretation is not supported by the stated design or evidence.",
    "confounding_or_selection_bias": "Confounding or selection can account for the observed association unless addressed.",
    "invalid_generalization": "The claim may not transport to the conditions, population, or scale being asserted.",
    "insufficient_reproducibility": "The result cannot be independently checked with the currently specified reproducibility evidence.",
    "proof_gap": "A missing proof obligation prevents the formal claim from being established within its stated assumptions.",
}


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


def _blockers(value: Any) -> list[tuple[str, str]]:
    values = value if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)) else [value]
    result: list[tuple[str, str]] = []
    for item in values:
        if isinstance(item, Mapping):
            kind = _text(item.get("kind") or item.get("type") or item.get("code"))
            statement = _text(item.get("statement") or item.get("reason") or item.get("text") or kind)
        else:
            kind = ""
            statement = _text(item)
        if statement:
            result.append((kind, statement))
    return result


def _load_json_mapping(source: Mapping[str, Any] | str | Path, label: str) -> dict[str, Any]:
    if isinstance(source, Mapping):
        return dict(source)
    path = Path(source)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(f"Unable to read {label}: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"{label} is not valid JSON: {path}") from exc
    if not isinstance(payload, Mapping):
        raise ValueError(f"{label} must contain a JSON object: {path}")
    return dict(payload)


def load_evidence_plan(source: Mapping[str, Any] | str | Path) -> dict[str, Any]:
    """Read an evidence plan from a mapping or JSON file."""

    payload = _load_json_mapping(source, "evidence plan")
    nested = payload.get("survey_evidence_plan")
    return dict(nested) if isinstance(nested, Mapping) else payload


def read_evidence_plan(source: Mapping[str, Any] | str | Path) -> dict[str, Any]:
    """Compatibility alias for callers that use ``read_*`` naming."""

    return load_evidence_plan(source)


def _json_pointer(*parts: Any) -> str:
    escaped = [str(part).replace("~", "~0").replace("/", "~1") for part in parts]
    return "/" + "/".join(escaped)


def _source(artifact: str, *parts: Any) -> SourcePointer:
    return SourcePointer(artifact=artifact, json_pointer=_json_pointer(*parts))


def _normalize_slot(slot: Any) -> str:
    return re.sub(r"\s+", "_", _text(slot).casefold().replace("-", "_"))


def _normalize_role(role: Any) -> str:
    raw = re.sub(r"\s+", "_", _text(role).upper())
    normalized = _ROLE_ALIASES.get(raw, raw)
    return normalized if normalized in EVIDENCE_ROLES else ""


def _slug(value: Any) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", _text(value).casefold()).strip("_")
    return slug or "unspecified"


def _slot_classification(slot: Any) -> tuple[str, str, list[str], list[str]]:
    raw = _text(slot)
    normalized = _normalize_slot(raw)
    kind = _SLOT_GAP_KINDS.get(normalized, f"unmapped_gap:{_slug(raw)}")
    tags = list(_GAP_TAGS.get(kind, (kind,)))
    modes = list(_CONTRIBUTION_MODES.get(kind, ("targeted_evidence_acquisition",)))
    return kind, raw, tags, modes


def _blocker_classification(blocker_kind: str, blocker_text: str) -> tuple[str, str, list[str], list[str]]:
    combined = f"{blocker_kind} {blocker_text}".casefold()
    if "missing_required_slot:" in combined or "background_only_slot:" in combined:
        slot = combined.split(":", 1)[1].strip().split()[0]
        return _slot_classification(slot)
    patterns = (
        (("causal", "confound", "selection bias"), "unsupported_causal_link", "causal_link"),
        (("measurement", "calibration", "construct", "proxy"), "measurement_construct_mismatch", "mapping_or_calibration"),
        (("comparator", "comparab", "comparison"), "missing_comparator", "comparator"),
        (("generaliz", "transport", "population", "scope", "validity domain", "boundary", "regime"), "missing_boundary_condition", "validity_domain"),
        (("assumption", "formal", "theorem", "proof", "validity"), "missing_assumption", "formal_claim"),
        (("reproduc", "replicat"), "insufficient_reproducibility", "reproducibility"),
        (("mechanism", "pathway", "explanation"), "mechanism_explanation_gap", "candidate_mechanism"),
        (("identif", "discriminat"), "identifiability_gap", "discriminating_observation"),
    )
    for needles, kind, target_slot in patterns:
        if any(needle in combined for needle in needles):
            tags = list(_GAP_TAGS.get(kind, (kind,)))
            modes = list(_CONTRIBUTION_MODES.get(kind, ("targeted_evidence_acquisition",)))
            return kind, target_slot, tags, modes
    label = blocker_text or blocker_kind
    kind = f"unmapped_gap:{_slug(label)}"
    target_slot = "claim_blocker" if blocker_kind in {
        "conclusion_admissibility",
        "limitations",
        "comparability",
        "measurement",
        "scope",
    } else (blocker_kind or "claim_blocker")
    return kind, target_slot, [kind], ["targeted_evidence_acquisition"]


def _profile_resolution(project_context: Mapping[str, Any] | None) -> ProfileResolution:
    context = _mapping(project_context)
    nested = _mapping(context.get("research_context"))
    raw = _mapping(context.get("discovery_taxonomy"))
    if not raw:
        raw = _mapping(nested.get("discovery_taxonomy"))
    if not raw:
        raw = _mapping(context.get("taxonomy_resolution"))
    if not raw:
        raw = _mapping(context.get("profile_resolution"))
    primary = _text(raw.get("primary_discipline")) or _text(context.get("primary_discipline"))
    status = _text(raw.get("status")) or ("resolved" if primary else "unresolved")
    filters = _mapping(raw.get("provider_filters"))
    openalex = _mapping(filters.get("openalex"))
    openalex_ids = _texts(
        raw.get("openalex_field_ids")
        or raw.get("resolved_openalex_field_ids")
        or openalex.get("resolved_field_ids")
        or context.get("openalex_field_ids")
    )
    discipline_ids = _texts(raw.get("discipline_ids") or context.get("discipline_ids"))
    paperseek_ids = _texts(raw.get("paperseek_field_ids") or context.get("paperseek_field_ids"))
    source = _text(
        raw.get("source")
        or context.get("domain_resolution_source")
        or nested.get("domain_resolution_source")
    )
    profile_hint = _text(raw.get("profile_id_hint") or context.get("profile_id_hint"))
    confidence = raw.get("confidence", context.get("domain_confidence"))
    try:
        confidence = float(confidence) if confidence is not None else None
        if confidence is not None and not 0.0 <= confidence <= 1.0:
            confidence = max(0.0, min(1.0, confidence))
    except (TypeError, ValueError):
        confidence = None
    confirmation = raw.get(
        "requires_human_confirmation",
        context.get("requires_human_confirmation", False),
    )
    if isinstance(confirmation, str):
        confirmation = confirmation.casefold() in {"1", "true", "yes", "y"}
    return ProfileResolution(
        status=status,
        source=source,
        primary_discipline=primary,
        discipline_ids=discipline_ids,
        openalex_field_ids=openalex_ids,
        paperseek_field_ids=paperseek_ids,
        profile_id_hint=profile_hint,
        confidence=confidence,
        requires_human_confirmation=bool(confirmation),
        unresolved_reason=_text(raw.get("reason") or raw.get("unresolved_reason")),
    )


def _project_value(
    key: str,
    explicit: Any,
    plan: Mapping[str, Any],
    claim_traceability: Mapping[str, Any],
    project_context: Mapping[str, Any],
    survey_json: Mapping[str, Any],
) -> str:
    if _text(explicit):
        return _text(explicit)
    nested = _mapping(project_context.get("research_context"))
    for source in (plan, claim_traceability, survey_json, project_context, nested):
        value = source.get(key)
        if _text(value):
            return _text(value)
    return ""


def _eligibility(
    subhypothesis: Mapping[str, Any],
    support: Mapping[str, Any],
    expected_role: str,
) -> EvidenceEligibility:
    constraints = _mapping(support.get("qualified_paper_constraints"))
    claim_limits: list[str] = []
    for _, raw_constraints in constraints.items():
        for constraint in _records(raw_constraints):
            claim_limits.extend(_texts(constraint.get("semantic_claim_limits")))
    return EvidenceEligibility(
        required_roles=[expected_role] if expected_role else [],
        allowed_claim_modes=_texts(subhypothesis.get("allowed_claim_modes")),
        forbidden_paper_ids=_texts(subhypothesis.get("forbidden_paper_ids")),
        direct_writing_blocked_paper_ids=_texts(
            subhypothesis.get("direct_writing_blocked_paper_ids")
        ),
        claim_limits=_texts(claim_limits),
    )


def _make_gap(
    *,
    subhypothesis_id: str,
    gap_kind: str,
    target_slot: str,
    statement: str,
    priority: str,
    source_pointer: SourcePointer,
    eligibility: EvidenceEligibility | None = None,
    tags: Sequence[str] = (),
    contribution_modes: Sequence[str] = (),
    source_kind: str,
    target_object: str = "",
) -> GapRecord:
    effective_tags = list(tags) or list(_GAP_TAGS.get(gap_kind, (gap_kind,)))
    effective_modes = list(contribution_modes) or list(
        _CONTRIBUTION_MODES.get(gap_kind, ("targeted_evidence_acquisition",))
    )
    return GapRecord.create(
        subhypothesis_id=subhypothesis_id,
        gap_kind=gap_kind,
        target_slot=target_slot,
        statement=statement,
        target_object=target_object,
        priority=priority,
        support_level="authoritative",
        why_it_matters=_WHY_IT_MATTERS.get(gap_kind, "The structured Survey artifacts identify an unresolved research constraint."),
        candidate_defect_tags=effective_tags,
        candidate_contribution_modes=effective_modes,
        evidence_eligibility=eligibility or EvidenceEligibility(),
        source_pointer=source_pointer,
        source_kind=source_kind,
    )


def _extract_gap_records(
    *,
    evidence_plan: Mapping[str, Any],
    claim_traceability: Mapping[str, Any] | None,
) -> list[GapRecord]:
    plan = load_evidence_plan(evidence_plan)
    gaps: list[GapRecord] = []
    seen: set[tuple[str, str, str]] = set()
    subhypotheses = _records(plan.get("subhypotheses"))

    def add(gap: GapRecord) -> None:
        key = (gap.subhypothesis_id, gap.gap_kind, gap.target_slot)
        if key in seen or any(
            existing[0] == gap.subhypothesis_id and existing[2] == gap.target_slot
            for existing in seen
        ):
            return
        seen.add(key)
        gaps.append(gap)

    for sh_index, raw_sh in enumerate(subhypotheses):
        sh = _mapping(raw_sh)
        sh_id = _text(sh.get("sub_hypothesis_id")) or f"SH{sh_index + 1}"
        summary = _text(sh.get("summary") or sh.get("question"))
        for slot_index, raw_slot in enumerate(_texts(sh.get("missing_slots"))):
            kind, target_slot, tags, modes = _slot_classification(raw_slot)
            statement = (
                f"Required evidence slot '{target_slot}' is missing from the Survey evidence plan"
                + (f" for sub-hypothesis {sh_id}: {summary}" if summary else f" for sub-hypothesis {sh_id}.")
            )
            support = _mapping(_mapping(sh.get("slot_support")).get(target_slot))
            role = _normalize_role(support.get("expected_evidence_role"))
            add(
                _make_gap(
                    subhypothesis_id=sh_id,
                    gap_kind=kind,
                    target_slot=target_slot,
                    statement=statement,
                    priority="high",
                    source_pointer=_source("survey_evidence_plan.json", "subhypotheses", sh_index, "missing_slots", slot_index),
                    eligibility=_eligibility(sh, support, role),
                    tags=tags,
                    contribution_modes=modes,
                    source_kind="missing_slot",
                    target_object=target_slot,
                )
            )

        for cluster_index, raw_cluster in enumerate(_records(sh.get("relevant_clusters"))):
            cluster = _mapping(raw_cluster)
            for uncovered_index, raw_slot in enumerate(_texts(cluster.get("uncovered_required_slots"))):
                kind, target_slot, tags, modes = _slot_classification(raw_slot)
                support = _mapping(_mapping(sh.get("slot_support")).get(target_slot))
                role = _normalize_role(support.get("expected_evidence_role"))
                add(
                    _make_gap(
                        subhypothesis_id=sh_id,
                        gap_kind=kind,
                        target_slot=target_slot,
                        statement=f"Required slot '{target_slot}' remains uncovered in relevant evidence cluster '{_text(cluster.get('cluster_name')) or f'cluster_{cluster_index}'}'.",
                        priority="high",
                        source_pointer=_source(
                            "survey_evidence_plan.json",
                            "subhypotheses",
                            sh_index,
                            "relevant_clusters",
                            cluster_index,
                            "uncovered_required_slots",
                            uncovered_index,
                        ),
                        eligibility=_eligibility(sh, support, role),
                        tags=tags,
                        contribution_modes=modes,
                        source_kind="uncovered_required_slot",
                        target_object=target_slot,
                    )
                )

        slot_supports = _mapping(sh.get("slot_support"))
        for slot_name, raw_support in slot_supports.items():
            support = _mapping(raw_support)
            role = _normalize_role(support.get("expected_evidence_role"))
            if not role:
                continue
            direct_ids = _texts(support.get("evidence_paper_ids"))
            qualified_ids = _texts(support.get("qualified_paper_ids"))
            background_ids = _texts(support.get("background_paper_ids"))
            constraints = _mapping(support.get("qualified_paper_constraints"))
            forbidden = {
                _text(paper_id)
                for paper_id, raw_constraints in constraints.items()
                if any(bool(item.get("forbidden_as_direct_evidence")) for item in _records(raw_constraints))
            }
            blocked = set(_texts(sh.get("direct_writing_blocked_paper_ids")))
            admissible_direct = [paper_id for paper_id in direct_ids if paper_id not in forbidden and paper_id not in blocked]
            context_satisfies = role == "BACKGROUND_CONTEXT" and bool(background_ids)
            if admissible_direct or context_satisfies:
                continue
            if qualified_ids:
                priority = "medium"
                statement = "Existing papers are only qualified or indirect contributions and do not satisfy the required evidence role directly."
            elif background_ids:
                priority = "high"
                statement = "Existing evidence is background-only and does not satisfy the required evidence role."
            else:
                priority = "high"
                statement = "No admissible paper currently satisfies the required evidence role for this slot."
            add(
                _make_gap(
                    subhypothesis_id=sh_id,
                    gap_kind="evidence_role_deficit",
                    target_slot=_text(slot_name),
                    statement=statement,
                    priority=priority,
                    source_pointer=_source(
                        "survey_evidence_plan.json",
                        "subhypotheses",
                        sh_index,
                        "slot_support",
                        slot_name,
                        "expected_evidence_role",
                    ),
                    eligibility=_eligibility(sh, support, role),
                    source_kind="evidence_role_deficit",
                    target_object=_text(slot_name),
                )
            )

        blocker_containers = (
            "conclusion_admissibility",
            "limitations",
            "comparability",
            "measurement",
            "scope",
        )
        for container_name in blocker_containers:
            container = _mapping(sh.get(container_name))
            blockers = _blockers(container.get("blockers"))
            for blocker_index, (blocker_kind, blocker) in enumerate(blockers):
                kind, target_slot, tags, modes = _blocker_classification(blocker_kind or container_name, blocker)
                target_slot = target_slot if not target_slot.startswith("claim_blocker") else "claim_blocker"
                add(
                    _make_gap(
                        subhypothesis_id=sh_id,
                        gap_kind=kind,
                        target_slot=target_slot,
                        statement=f"Structured claim blocker: {blocker}",
                        priority="high",
                        source_pointer=_source(
                            "survey_evidence_plan.json",
                            "subhypotheses",
                            sh_index,
                            container_name,
                            "blockers",
                            blocker_index,
                        ),
                        eligibility=EvidenceEligibility(
                            allowed_claim_modes=_texts(sh.get("allowed_claim_modes")),
                            forbidden_paper_ids=_texts(sh.get("forbidden_paper_ids")),
                            direct_writing_blocked_paper_ids=_texts(sh.get("direct_writing_blocked_paper_ids")),
                        ),
                        tags=tags,
                        contribution_modes=modes,
                        source_kind="claim_blocker",
                        target_object=target_slot,
                    )
                )

    traceability = _mapping(claim_traceability)
    for claim_index, raw_claim in enumerate(_records(traceability.get("claims"))):
        claim = _mapping(raw_claim)
        sh_id = _text(claim.get("subhypothesis_id") or claim.get("sub_hypothesis_id")) or "GLOBAL"
        blocker_sources: list[tuple[str, Any]] = [("blockers", claim.get("blockers"))]
        for container_name in (
            "conclusion_admissibility",
            "limitations",
            "comparability",
            "measurement",
            "scope",
        ):
            container = _mapping(claim.get(container_name))
            if container.get("blockers"):
                blocker_sources.append((f"{container_name}/blockers", container.get("blockers")))
        for source_name, raw_blockers in blocker_sources:
            for blocker_index, (blocker_kind, blocker_text) in enumerate(_blockers(raw_blockers)):
                kind, target_slot, tags, modes = _blocker_classification(blocker_kind, blocker_text)
                if target_slot.startswith("claim_blocker"):
                    target_slot = _text(claim.get("target_slot") or claim.get("claim_id")) or "claim_blocker"
                source_parts = [*source_name.split("/"), blocker_index]
                add(
                    _make_gap(
                        subhypothesis_id=sh_id,
                        gap_kind=kind,
                        target_slot=target_slot,
                        statement=f"Structured claim blocker: {blocker_text}",
                        priority="high",
                        source_pointer=_source("survey_claim_traceability.json", "claims", claim_index, *source_parts),
                        tags=tags,
                        contribution_modes=modes,
                        source_kind="claim_blocker",
                        target_object=target_slot,
                    )
                )
    return gaps


def extract_deterministic_gaps(
    *,
    evidence_plan: Mapping[str, Any] | str | Path,
    claim_traceability: Mapping[str, Any] | str | Path | None = None,
) -> list[GapRecord]:
    """Extract authoritative GapRecord objects without invoking an LLM."""

    plan = load_evidence_plan(evidence_plan)
    traceability = None
    if claim_traceability is not None:
        traceability = _load_json_mapping(claim_traceability, "claim traceability")
        nested = traceability.get("survey_claim_traceability")
        if isinstance(nested, Mapping):
            traceability = dict(nested)
    return _extract_gap_records(evidence_plan=plan, claim_traceability=traceability)


def build_deterministic_gap_ledger(
    *,
    evidence_plan: Mapping[str, Any] | str | Path,
    claim_traceability: Mapping[str, Any] | str | Path | None = None,
    project_context: Mapping[str, Any] | str | Path | None = None,
    survey_json: Mapping[str, Any] | str | Path | None = None,
    source_artifacts: Mapping[str, Any] | None = None,
    project_id: str = "",
    survey_run_id: str = "",
    project_context_fingerprint: str = "",
    created_at: str = "",
) -> dict[str, Any]:
    """Build the initial ``survey_gap_ledger_v1`` payload deterministically."""

    plan = load_evidence_plan(evidence_plan)
    traceability = {}
    if claim_traceability is not None:
        traceability = _load_json_mapping(claim_traceability, "claim traceability")
        nested_traceability = traceability.get("survey_claim_traceability")
        if isinstance(nested_traceability, Mapping):
            traceability = dict(nested_traceability)
    context = {}
    if project_context is not None:
        context = _load_json_mapping(project_context, "project context")
    survey = {}
    if survey_json is not None:
        survey = _load_json_mapping(survey_json, "survey JSON")
    if not plan.get("subhypotheses") and isinstance(survey.get("survey_evidence_plan"), Mapping):
        plan = dict(survey["survey_evidence_plan"])
    if not traceability and isinstance(survey.get("claim_traceability"), Mapping):
        traceability = dict(survey["claim_traceability"])
    resolved_project_id = _project_value("project_id", project_id, plan, traceability, context, survey)
    resolved_run_id = _project_value("survey_run_id", survey_run_id, plan, traceability, context, survey)
    if not resolved_run_id:
        resolved_run_id = _project_value("research_run_id", "", plan, traceability, context, survey)
    if not resolved_run_id:
        resolved_run_id = resolved_project_id
    resolved_fingerprint = _project_value(
        "project_context_fingerprint",
        project_context_fingerprint,
        plan,
        traceability,
        context,
        survey,
    )
    if not resolved_fingerprint:
        resolved_fingerprint = _text(context.get("input_fingerprint")) or _text(
            _mapping(context.get("research_context")).get("input_fingerprint")
        )
    if not resolved_project_id or not resolved_run_id or not resolved_fingerprint:
        raise ValueError("evidence plan and Survey context must provide project_id, survey_run_id, and project_context_fingerprint")
    artifacts = {
        "evidence_plan": "survey_evidence_plan.json",
    }
    if claim_traceability is not None or traceability:
        artifacts["claim_traceability"] = "survey_claim_traceability.json"
    if project_context is not None or context:
        artifacts["project_context"] = "project_context.json"
    if survey_json is not None or survey:
        artifacts["survey_json"] = "survey.json"
    artifacts.update(dict(source_artifacts or {}))
    ledger = GapLedger(
        project_id=resolved_project_id,
        survey_run_id=resolved_run_id,
        project_context_fingerprint=resolved_fingerprint,
        gaps=_extract_gap_records(evidence_plan=plan, claim_traceability=traceability),
        profile_resolution=_profile_resolution(context),
        source_artifacts=artifacts,
        created_at=_text(created_at),
    )
    return build_gap_ledger_payload(ledger)


def build_initial_gap_ledger(**kwargs: Any) -> dict[str, Any]:
    """Alias emphasizing that this is the pre-LLM deterministic ledger."""

    return build_deterministic_gap_ledger(**kwargs)


def build_survey_gap_ledger(**kwargs: Any) -> dict[str, Any]:
    """Alias for pipeline callers using the Survey artifact naming."""

    return build_deterministic_gap_ledger(**kwargs)


__all__ = [
    "build_deterministic_gap_ledger",
    "build_initial_gap_ledger",
    "build_survey_gap_ledger",
    "extract_deterministic_gaps",
    "load_evidence_plan",
    "read_evidence_plan",
]
