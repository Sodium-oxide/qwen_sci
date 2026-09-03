"""Metadata-only precision checks before a retrieval round starts full-text work.

The audit is intentionally advisory.  It examines the first distinct provider
candidates with the same alignment contract used at admission time, records why
the query appears broad, and leaves the complete candidate pool intact.  This
means it can steer the next role-specific query without converting an early
ranking artifact into a recall-reducing rejection rule.
"""
from __future__ import annotations

from collections import Counter
from typing import Any
import re


DEFAULT_PRECISION_AUDIT_SAMPLE_SIZE = 12
MIN_AUDITABLE_CANDIDATES = 6
MIN_OBJECT_PRECISION = 0.50
MIN_DIRECT_CORE_PRECISION = 0.25

_BACKGROUND_ROLES = frozenset({
    "background_or_framework",
    "theoretical_framework",
    "rationale_only",
})
_DIRECT_EVIDENCE_KINDS = frozenset({
    "mechanism_discovery",
    "causal_validation",
    "experimental_evidence",
    "predictive_validation",
    "type_directed_slot_evidence",
})


def _candidate_identity(candidate: dict[str, Any], position: int) -> str:
    payload = (
        candidate.get("papergraph_input")
        if isinstance(candidate.get("papergraph_input"), dict)
        else {}
    )
    for field in ("doi", "pmid", "semantic_scholar_id", "openalex_id", "arxiv_id"):
        value = str(candidate.get(field) or payload.get(field) or "").strip().lower()
        if value and value not in {"unknown", "none", "unspecified"}:
            return f"{field}:{value}"
    title = re.sub(
        r"[^a-z0-9]+",
        " ",
        str(candidate.get("title") or payload.get("title") or "").lower(),
    ).strip()
    if title:
        return f"title:{title}"
    return f"position:{position}"


def _direct_branch_lookup(query_plan: list[dict[str, Any]] | None) -> dict[str, bool]:
    lookup: dict[str, bool] = {}
    for raw in query_plan or []:
        if not isinstance(raw, dict):
            continue
        branch = str(raw.get("branch") or "").strip()
        if not branch:
            continue
        role = str(raw.get("evidence_path_role") or raw.get("role") or "").strip().lower()
        kind = str(raw.get("evidence_kind") or "").strip().lower()
        lookup[branch] = bool(
            kind in _DIRECT_EVIDENCE_KINDS and role not in _BACKGROUND_ROLES
        )
    return lookup


def _candidate_targets_direct_evidence(
    candidate: dict[str, Any],
    branch_lookup: dict[str, bool],
) -> bool:
    branches = [
        candidate.get("primary_query_branch"),
        candidate.get("query_branch"),
        *(candidate.get("matched_query_branches") or []),
    ]
    matched = [
        branch_lookup[str(branch)]
        for branch in branches
        if str(branch or "") in branch_lookup
    ]
    if matched:
        # A multi-branch duplicate can legitimately be admitted through a
        # direct branch even if its first provider branch was a review query.
        return any(matched)
    role = str(candidate.get("evidence_path_role") or "").strip().lower()
    kind = str(candidate.get("evidence_kind") or "").strip().lower()
    return bool(kind in _DIRECT_EVIDENCE_KINDS and role not in _BACKGROUND_ROLES)


def audit_subhypothesis_retrieval_precision(
    candidates: list[dict[str, Any]] | None,
    alignment_contract: dict[str, Any],
    *,
    query_plan: list[dict[str, Any]] | None = None,
    sample_size: int = DEFAULT_PRECISION_AUDIT_SAMPLE_SIZE,
    enable_focal_variable_synonym_dictionary: bool = False,
) -> dict[str, Any]:
    """Assess the leading metadata sample before any PDF/OA preparation.

    The return value never controls candidate admission.  ``refinement_recommended``
    is a deterministic signal for the subsequent retrieval loop and is kept in
    the search artifact so a restart can explain why a role query changed.
    """
    try:
        from ._research_alignment import assess_candidate_alignment_across_matched_evidence_lanes
    except ImportError:
        from _research_alignment import assess_candidate_alignment_across_matched_evidence_lanes

    requested_size = max(1, int(sample_size or DEFAULT_PRECISION_AUDIT_SAMPLE_SIZE))
    distinct: list[dict[str, Any]] = []
    seen: set[str] = set()
    for position, raw in enumerate(candidates or []):
        if not isinstance(raw, dict):
            continue
        candidate = dict(raw)
        key = _candidate_identity(candidate, position)
        if key in seen:
            continue
        seen.add(key)
        distinct.append(candidate)
        if len(distinct) >= requested_size:
            break

    branch_lookup = _direct_branch_lookup(query_plan)
    counts: Counter[str] = Counter()
    role_counts: Counter[str] = Counter()
    rejection_reasons: Counter[str] = Counter()
    samples: list[dict[str, Any]] = []
    for candidate in distinct:
        assessment = assess_candidate_alignment_across_matched_evidence_lanes(
            candidate,
            alignment_contract,
            enable_focal_variable_synonym_dictionary=enable_focal_variable_synonym_dictionary,
        )
        type_evidence = (
            assessment.get("type_directed_evidence")
            if isinstance(assessment.get("type_directed_evidence"), dict)
            else {}
        )
        direct_branch = _candidate_targets_direct_evidence(candidate, branch_lookup)
        project_context = (
            assessment.get("project_context")
            if isinstance(assessment.get("project_context"), dict)
            else {}
        )
        object_supported = bool(project_context.get("passes"))
        import_eligible = bool(assessment.get("import_eligible"))
        core_eligible = bool(assessment.get("core_eligible"))
        evidence_role = str(type_evidence.get("evidence_role") or "unclassified")
        reason = str(assessment.get("reason") or "")

        counts["sampled"] += 1
        counts["object_supported"] += int(object_supported)
        counts["import_eligible"] += int(import_eligible)
        counts["core_eligible"] += int(core_eligible)
        counts["direct_branch_candidates"] += int(direct_branch)
        counts["direct_branch_core_eligible"] += int(direct_branch and core_eligible)
        counts["background_branch_candidates"] += int(not direct_branch)
        role_counts[evidence_role] += 1
        if not import_eligible:
            rejection_reasons[reason or "alignment_gate_rejected"] += 1
        if len(samples) < requested_size:
            samples.append({
                "result_index": int(candidate.get("result_index") or 0),
                "title": str(candidate.get("title") or "untitled")[:180],
                "query_branch": str(
                    candidate.get("primary_query_branch")
                    or candidate.get("query_branch")
                    or ""
                ),
                "targets_direct_evidence": direct_branch,
                "specific_object_supported": object_supported,
                "import_eligible": import_eligible,
                "core_eligible": core_eligible,
                "type_directed_evidence_role": evidence_role,
                "reason": reason[:360],
            })

    sampled = int(counts["sampled"])
    direct_candidates = int(counts["direct_branch_candidates"])
    object_precision = (counts["object_supported"] / sampled) if sampled else 0.0
    import_precision = (counts["import_eligible"] / sampled) if sampled else 0.0
    core_precision = (counts["core_eligible"] / sampled) if sampled else 0.0
    direct_core_precision = (
        counts["direct_branch_core_eligible"] / direct_candidates
        if direct_candidates
        else None
    )
    reasons: list[str] = []
    if sampled < MIN_AUDITABLE_CANDIDATES:
        reasons.append("INSUFFICIENT_METADATA_SAMPLE")
    else:
        if object_precision < MIN_OBJECT_PRECISION:
            reasons.append("LOW_OBJECT_PRECISION")
        if not counts["import_eligible"]:
            reasons.append("ZERO_IMPORT_PRECISION")
        if direct_candidates >= 3 and (direct_core_precision or 0.0) < MIN_DIRECT_CORE_PRECISION:
            reasons.append("LOW_DIRECT_CORE_PRECISION")
        if direct_candidates == 0 and branch_lookup and any(branch_lookup.values()):
            reasons.append("NO_DIRECT_ROLE_CANDIDATES_IN_SAMPLE")

    refinement_recommended = bool(
        set(reasons) - {"INSUFFICIENT_METADATA_SAMPLE"}
    )
    return {
        "schema_version": "subhypothesis_pre_import_precision_audit_v1",
        "phase": "metadata_before_fulltext_preparation",
        "advisory_only": True,
        "candidate_pool_preserved": True,
        "sample_size_requested": requested_size,
        "minimum_auditable_candidates": MIN_AUDITABLE_CANDIDATES,
        "thresholds": {
            "object_precision": MIN_OBJECT_PRECISION,
            "direct_core_precision": MIN_DIRECT_CORE_PRECISION,
        },
        "counts": dict(counts),
        "rates": {
            "object_precision": round(object_precision, 4),
            "import_precision": round(import_precision, 4),
            "core_precision": round(core_precision, 4),
            "direct_core_precision": (
                round(direct_core_precision, 4)
                if direct_core_precision is not None
                else None
            ),
        },
        "type_directed_evidence_role_counts": dict(role_counts),
        "rejection_reason_counts": dict(rejection_reasons),
        "refinement_recommended": refinement_recommended,
        "reasons": reasons,
        "recommended_actions": (
            ["reassess_scientific_model", "refine_role_query_branches"]
            if refinement_recommended
            else []
        ),
        "samples": samples,
    }
