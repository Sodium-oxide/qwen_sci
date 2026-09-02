"""Single entry point for the immutable original-gap source-role audit.

The evaluator is deliberately separate from evidence-bundle enrichment.  It
may read the current project/sub-hypothesis contract to understand scientific
identity, but causal values are admitted only when they match the candidate's
own paper-qualified source units.  Same-branch papers added later are outside
this boundary.
"""
from __future__ import annotations

from typing import Any, TypedDict


class OriginalSourceRoleAssessment(TypedDict, total=False):
    version: str
    state: str
    prior_state: str
    source_clue_role: str
    allowed_transition: str
    gap_candidate_pool: str
    socrates_targeted_retrieval_allowed: bool
    source_alignment_verdict: str
    gap_epistemic_verdict: str
    causal_readiness_verdict: str
    original_source_role_audit_hash: str
    routed_candidate: dict[str, Any]


def _normalize_candidate_provenance(seed: dict[str, Any]) -> dict[str, Any]:
    """Index every original paper-qualified unit without inventing a source.

    Single-fragment and composite candidates share this representation.  The
    top-level compatibility fields are retained for existing reports, while
    ``sources`` is authoritative for contradiction/mediation/mismatch/TABI
    candidates that necessarily have more than one source unit.
    """
    item = dict(seed)
    branch = str(item.get("sub_hypothesis_id") or "").strip()
    units = [
        unit for unit in (item.get("source_evidence_units") or [])
        if isinstance(unit, dict)
    ]
    existing = (
        item.get("source_candidate_provenance")
        if isinstance(item.get("source_candidate_provenance"), dict)
        else {}
    )
    sources: list[dict[str, Any]] = []
    for unit in units:
        location = (
            dict(unit.get("source_location") or {})
            if isinstance(unit.get("source_location"), dict) else {}
        )
        if not location:
            location = {
                key: unit.get(key)
                for key in ("source_field", "section", "sentence_start", "sentence_end", "source_locator")
                if unit.get(key) not in (None, "")
            }
        sources.append({
            "paper_id": str(unit.get("paper_id") or ""),
            "source_unit_id": str(unit.get("source_unit_id") or ""),
            "source_location": location,
            "source_field": str(unit.get("source_field") or ""),
            "excerpt_hash": str(unit.get("excerpt_hash") or ""),
            "binding_status": str(unit.get("binding_status") or ""),
            "sub_hypothesis_id": branch,
        })
    if not sources and existing:
        existing_sources = existing.get("sources") if isinstance(existing.get("sources"), list) else []
        sources = [dict(source) for source in existing_sources if isinstance(source, dict)]
        if not sources and any(existing.get(key) for key in ("paper_id", "source_unit_id", "excerpt_hash")):
            sources = [{
                "paper_id": str(existing.get("paper_id") or ""),
                "source_unit_id": str(existing.get("source_unit_id") or ""),
                "source_location": dict(existing.get("source_location") or {})
                if isinstance(existing.get("source_location"), dict) else {},
                "source_field": str(existing.get("source_field") or ""),
                "excerpt_hash": str(existing.get("excerpt_hash") or ""),
                "binding_status": str(existing.get("binding_status") or ""),
                "sub_hypothesis_id": str(existing.get("sub_hypothesis_id") or branch),
            }]
    first = sources[0] if sources else {}
    item["source_candidate_provenance"] = {
        "version": "source_candidate_provenance_v1",
        "paper_id": str(first.get("paper_id") or ""),
        "source_unit_id": str(first.get("source_unit_id") or ""),
        "source_location": dict(first.get("source_location") or {}),
        "source_field": str(first.get("source_field") or ""),
        "excerpt_hash": str(first.get("excerpt_hash") or ""),
        "sub_hypothesis_id": branch,
        "sources": sources,
        "source_count": len(sources),
        "complete": bool(sources) and all(
            source.get("paper_id")
            and source.get("source_unit_id")
            and source.get("source_location")
            and source.get("excerpt_hash")
            and source.get("sub_hypothesis_id")
            for source in sources
        ),
    }
    return item


def assess_original_gap_source_role(
    project: dict[str, Any],
    subhypothesis_contract: dict[str, Any] | None,
    gap_candidate_seed: dict[str, Any],
) -> OriginalSourceRoleAssessment:
    """Audit and route one source candidate without evidence enrichment."""
    try:
        from ._gap_detection import (
            apply_three_verdict_gap_route,
            pre_rank_gap_source_role_route,
        )
    except ImportError:
        from _gap_detection import (
            apply_three_verdict_gap_route,
            pre_rank_gap_source_role_route,
        )

    seed = _normalize_candidate_provenance(dict(gap_candidate_seed or {}))
    seed["source_state"] = "SOURCE_CANDIDATE"
    local_project = project
    contract = subhypothesis_contract if isinstance(subhypothesis_contract, dict) else {}
    branch = str(seed.get("sub_hypothesis_id") or contract.get("sub_hypothesis_id") or "").strip()
    if contract and branch:
        local_project = dict(project)
        contracts = dict(project.get("subhypothesis_alignment_contracts") or {})
        contracts[branch] = contract
        local_project["subhypothesis_alignment_contracts"] = contracts

    routed = apply_three_verdict_gap_route(
        local_project,
        pre_rank_gap_source_role_route(local_project, seed),
    )
    audit = routed.get("original_source_role_audit") if isinstance(routed.get("original_source_role_audit"), dict) else {}
    scientific = routed.get("scientific_verdicts") if isinstance(routed.get("scientific_verdicts"), dict) else {}
    routed["source_state"] = "ORIGINAL_SOURCE_AUDITED"
    history = [
        str(item) for item in (routed.get("source_state_history") or [])
        if str(item)
    ]
    for state in ("SOURCE_CANDIDATE", "ORIGINAL_SOURCE_AUDITED"):
        if state not in history:
            history.append(state)
    routed["source_state_history"] = history
    assessment: OriginalSourceRoleAssessment = {
        "version": "original_gap_source_role_assessment_v1",
        "prior_state": "SOURCE_CANDIDATE",
        "state": "ORIGINAL_SOURCE_AUDITED",
        "source_clue_role": str(audit.get("source_clue_role") or routed.get("source_clue_role") or "partial"),
        "allowed_transition": str(audit.get("allowed_transition") or "SECONDARY_RESEARCH_OPPORTUNITY"),
        "gap_candidate_pool": str(routed.get("gap_candidate_pool") or ""),
        "socrates_targeted_retrieval_allowed": routed.get("socrates_targeted_retrieval_allowed") is True,
        "source_alignment_verdict": str(scientific.get("source_alignment_verdict") or "UNVERIFIABLE_SOURCE"),
        "gap_epistemic_verdict": str(scientific.get("gap_epistemic_verdict") or "EVIDENCE_EXTRACTION_SHORTAGE"),
        "causal_readiness_verdict": str(scientific.get("causal_readiness_verdict") or "SOURCE_ROLE_CONFLICT"),
        "original_source_role_audit_hash": str(audit.get("audit_hash") or ""),
        "routed_candidate": routed,
    }
    routed["original_source_role_assessment"] = {
        key: value for key, value in assessment.items() if key != "routed_candidate"
    }
    return assessment


def audit_and_route_original_gap_source(
    project: dict[str, Any],
    gap_candidate_seed: dict[str, Any],
) -> dict[str, Any]:
    """Return the routed seed for TanXi's pre-ranking candidate pools."""
    branch = str(gap_candidate_seed.get("sub_hypothesis_id") or "").strip()
    contracts = project.get("subhypothesis_alignment_contracts") if isinstance(project.get("subhypothesis_alignment_contracts"), dict) else {}
    contract = contracts.get(branch) if isinstance(contracts.get(branch), dict) else {}
    assessment = assess_original_gap_source_role(project, contract, gap_candidate_seed)
    routed = dict(assessment.get("routed_candidate") or {})
    try:
        from ._mechanism_seed import build_mechanism_seed
    except ImportError:
        from _mechanism_seed import build_mechanism_seed
    seed = build_mechanism_seed(project, routed, contract)
    routed["mechanism_seed_contract"] = seed
    # This is a new composite candidate, not an in-place promotion of the
    # immutable source fragment.  It may participate in TanXi's composite
    # audit/ranking, but Socrates authority is still decided by the later
    # evidence-bundle gate.
    epistemic = routed.get("gap_epistemic_verdict") if isinstance(routed.get("gap_epistemic_verdict"), dict) else {}
    source = routed.get("source_alignment_verdict") if isinstance(routed.get("source_alignment_verdict"), dict) else {}
    needs_existence_verification = bool(
        seed.get("status") == "COMPLETE_COMPOSITE_MECHANISM_SEED"
        and epistemic.get("passes") is True
        and (
            epistemic.get("requires_gap_existence_verification") is True
            or not bool((epistemic.get("explicit_predicate_assessment") or {}).get("passes"))
        )
    )
    if needs_existence_verification:
        try:
            from ._gap_existence import build_gap_existence_verification_task
        except ImportError:
            from _gap_existence import build_gap_existence_verification_task
        routed["gap_existence_verification_task"] = build_gap_existence_verification_task(project, routed)
        routed["gap_candidate_pool"] = "GAP_EXISTENCE_VERIFICATION_POOL"
        routed["scientific_state"] = "GAP_EXISTENCE_VERIFICATION_PENDING"
        routed["mechanism_seed_transition"] = "GAP_EXISTENCE_VERIFICATION"
        routed["socrates_targeted_retrieval_allowed"] = False
    elif (
        seed.get("status") == "COMPLETE_COMPOSITE_MECHANISM_SEED"
        and epistemic.get("passes") is True
        and source.get("verdict") in {"DIRECTLY_ALIGNED", "PARTIALLY_ALIGNED"}
        and str((routed.get("original_source_role_audit") or {}).get("source_clue_role") or "") == "partial"
    ):
        routed["gap_candidate_pool"] = "COMPOSITE_GAP_AUDIT_POOL"
        routed["scientific_state"] = "COMPOSITE_MECHANISM_SEED_CANDIDATE"
        routed["mechanism_seed_transition"] = "COMPOSITE_MECHANISM_CANDIDATE"
        routed["socrates_targeted_retrieval_allowed"] = False
    return routed
