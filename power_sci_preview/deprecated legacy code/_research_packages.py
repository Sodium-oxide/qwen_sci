"""Research-package construction for qualified, heterogeneous gap types.

The legacy hypothesis package is intentionally reserved for a qualified causal
identification gap.  This module gives every other scientific gap type an
equally explicit package contract instead of forcing it through a mediator
template.  It consumes only v2 candidate and retrieval-assessment artefacts.
"""

from __future__ import annotations

from hashlib import sha256
from typing import Any

try:
    from ._gap_types import (
        EvidenceMaturity,
        GapRoute,
        ScopeStatus,
        SemanticVerdict,
        assessment_of,
        contract_for,
        is_primary_research_candidate,
        package_kind_for,
        payload_of,
    )
    from ._research_graph import RESEARCH_EVIDENCE_GRAPH_SCHEMA_VERSION
except ImportError:
    from _gap_types import (
        EvidenceMaturity,
        GapRoute,
        ScopeStatus,
        SemanticVerdict,
        assessment_of,
        contract_for,
        is_primary_research_candidate,
        package_kind_for,
        payload_of,
    )
    from _research_graph import RESEARCH_EVIDENCE_GRAPH_SCHEMA_VERSION


def _text(value: Any) -> str:
    return " ".join(str(value or "").split())


def _source_unit_refs(candidate: dict[str, Any]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for item in candidate.get("source_evidence_units", []):
        if not isinstance(item, dict):
            continue
        key = (_text(item.get("paper_id")), _text(item.get("source_unit_id")))
        if not key[1] or key in seen:
            continue
        seen.add(key)
        refs.append(
            {
                "paper_id": key[0],
                "document_version_hash": _text(item.get("document_version_hash")),
                "source_unit_id": key[1],
                "excerpt_hash": _text(item.get("excerpt_hash")),
                "source_field": _text(item.get("source_field")),
                "assertion_id": _text(item.get("assertion_id") or item.get("evidence_assertion_id")),
                "source_span_id": _text(item.get("source_span_id") or item.get("source_unit_id")),
                "evidence_link_id": _text(item.get("evidence_link_id")),
                "evidence_role": _text(item.get("evidence_link_role") or item.get("evidence_role")),
                "verified_excerpt": _text(item.get("excerpt") or item.get("quote")),
            }
        )
    return refs


def research_package_gate(package: dict[str, Any]) -> dict[str, Any]:
    """Validate one type-specific package without causal special cases."""
    required = {
        "schema_version",
        "package_version",
        "research_package_id",
        "gap_id",
        "gap_type",
        "package_kind",
        "research_question",
        "type_payload",
        "source_lineage",
        "evidence_bundle",
        "retrieval_assessment",
        "graph_snapshot_ref",
        "package_input_fingerprint",
        "proposal_authoring_contract_ref",
        "socrates_review_requirement",
    }
    missing = sorted(key for key in required if key not in package)
    route = _text((package.get("qualification") or {}).get("route"))
    semantic = _text((package.get("qualification") or {}).get("semantic_verdict"))
    maturity = _text((package.get("qualification") or {}).get("evidence_maturity"))
    scope = _text((package.get("qualification") or {}).get("scope_status"))
    lineage = [item for item in package.get("source_lineage", []) if isinstance(item, dict)]
    graph_ref = package.get("graph_snapshot_ref") if isinstance(package.get("graph_snapshot_ref"), dict) else {}
    graph_ref_complete = bool(
        _text(graph_ref.get("graph_id"))
        and int(graph_ref.get("graph_version") or 0) > 0
        and _text(graph_ref.get("input_fingerprint"))
        and _text(graph_ref.get("schema_version")) == RESEARCH_EVIDENCE_GRAPH_SCHEMA_VERSION
    )
    binding_complete = bool(lineage) and all(
        _text(item.get("assertion_id"))
        and _text(item.get("source_span_id"))
        and _text(item.get("evidence_link_id"))
        and _text(item.get("document_version_hash"))
        for item in lineage
    )
    evidence_bundle = [item for item in package.get("evidence_bundle", []) if isinstance(item, dict)]
    retrieval_assessment = package.get("retrieval_assessment") if isinstance(package.get("retrieval_assessment"), dict) else {}
    evidence_bundle_complete = bool(evidence_bundle) and all(
        _text(item.get("assertion_id"))
        and _text(item.get("source_span_id") or item.get("source_unit_id"))
        and _text(item.get("evidence_link_id"))
        and _text(item.get("document_version_hash"))
        and _text(item.get("allowed_use"))
        and _text(item.get("verified_excerpt"))
        for item in evidence_bundle
    )
    ready = bool(
        not missing
        and route == GapRoute.PRIMARY_CANDIDATE.value
        and semantic == SemanticVerdict.ENTAILED.value
        and maturity == EvidenceMaturity.DESIGN_READY.value
        and scope == ScopeStatus.CORE.value
        and graph_ref_complete
        and binding_complete
        and evidence_bundle_complete
        and retrieval_assessment.get("schema_version") == "gap_retrieval_assessment_v3"
        and _text(retrieval_assessment.get("rebind_fingerprint"))
    )
    return {
        "schema_version": "research_package_gate_v2",
        "passes": ready,
        "status": "READY_FOR_RESEARCH_EXECUTION" if ready else "RESEARCH_PACKAGE_BLOCKED",
        "missing_fields": missing,
        "source_binding_complete": binding_complete,
        "evidence_bundle_complete": evidence_bundle_complete,
        "graph_snapshot_ref_complete": graph_ref_complete,
        "retrieval_rebind_complete": bool(
            retrieval_assessment.get("schema_version") == "gap_retrieval_assessment_v3"
            and _text(retrieval_assessment.get("rebind_fingerprint"))
        ),
        "reason": (
            "The type-specific candidate is semantically entailed, assertion/span/link-traceable, retrieval-qualified, and design-ready."
            if ready
            else "The package lacks a mandatory v2 qualification, V3 graph reference, or complete assertion/span/link source binding."
        ),
    }


def build_research_package(project: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    """Construct one research package for a qualified v2 candidate.

    Raises ``ValueError`` for a non-qualified candidate; callers must not turn
    a partial candidate into a package by supplying additional ad-hoc fields.
    """
    if not is_primary_research_candidate(candidate):
        raise ValueError("Only a v2 PRIMARY_CANDIDATE may build a research package")
    graph_binding = candidate.get("graph_binding_audit") if isinstance(candidate.get("graph_binding_audit"), dict) else {}
    if graph_binding.get("status") != "PASSED":
        raise ValueError("Only a candidate with complete V3 graph assertion/span/link bindings may build a research package")
    assessment = assessment_of(candidate)
    payload = payload_of(candidate)
    contract = contract_for(assessment["gap_type"])
    retrieval = candidate.get("retrieval_assessment")
    rebind = candidate.get("retrieval_rebind")
    semantic_audit = candidate.get("semantic_audit")
    if not isinstance(retrieval, dict) or retrieval.get("schema_version") != "gap_retrieval_assessment_v3":
        raise ValueError("A qualified research package requires gap_retrieval_assessment_v3")
    if not isinstance(rebind, dict) or rebind.get("schema_version") != "gap_retrieval_evidence_rebind_v3":
        raise ValueError("A qualified research package requires V3 retrieval evidence rebind")
    if not isinstance(semantic_audit, dict) or semantic_audit.get("schema_version") != "gap_semantic_audit_result_v3":
        raise ValueError("A qualified research package requires a current V3 semantic audit")
    if _text(retrieval.get("rebind_fingerprint")) != _text(rebind.get("rebind_fingerprint")):
        raise ValueError("Research package retrieval assessment does not match the current evidence rebind")
    question = candidate.get("research_question") if isinstance(candidate.get("research_question"), dict) else {}
    identity = "|".join(
        (
            _text(project.get("project_id")),
            _text(candidate.get("gap_id") or candidate.get("candidate_identity")),
            assessment["gap_type"],
            package_kind_for(candidate).value,
        )
    )
    research_package_id = "rp_" + sha256(identity.encode("utf-8")).hexdigest()[:20]
    prior_versions = [
        int(item.get("package_version") or 0)
        for item in project.get("research_packages", [])
        if isinstance(item, dict)
        and str(item.get("research_package_id") or "") == research_package_id
    ]
    package = {
        "schema_version": "research_package_v2",
        "research_package_id": research_package_id,
        "package_version": max(prior_versions, default=0) + 1,
        "project_id": _text(project.get("project_id")),
        "graph_snapshot_ref": dict(candidate.get("graph_snapshot_ref") or {}),
        "gap_id": _text(candidate.get("gap_id")),
        "candidate_identity": _text(candidate.get("candidate_identity")),
        "gap_type": assessment["gap_type"],
        "gap_subtype": _text(assessment.get("gap_subtype")),
        "package_kind": package_kind_for(candidate).value,
        "research_question": {
            "question_text": _text(question.get("question_text")),
            "question_kind": _text(question.get("question_kind")),
            "target_knowledge_need": _text(question.get("target_knowledge_need")),
            "expected_gap_type_priors": list(question.get("expected_gap_type_priors") or []),
            "declared_scope": dict((candidate.get("research_question_contract") or {}).get("scientific_scope") or {}),
        },
        "research_question_contract": {
            "contract_id": _text((candidate.get("research_question_contract") or {}).get("contract_id")),
            "contract_revision": _text((candidate.get("research_question_contract") or {}).get("contract_revision") or (candidate.get("research_question_contract") or {}).get("declaration_hash")),
        },
        "type_payload": dict(payload),
        "type_contract": {
            "required_payload_fields": list(contract.required_payload_fields),
            "required_semantic_checks": list(contract.required_semantic_checks),
            "required_retrieval_axes": list(contract.required_retrieval_axes),
        },
        "qualification": {
            "route": assessment.get("route"),
            "semantic_verdict": assessment.get("semantic_verdict"),
            "evidence_maturity": assessment.get("evidence_maturity"),
            "scope_status": assessment.get("scope_status"),
            "novelty_verdict": assessment.get("novelty_verdict"),
            "decision_reasons": list(assessment.get("decision_reasons") or []),
        },
        "semantic_audit": dict(candidate.get("semantic_audit") or {}),
        "retrieval_assessment": dict(retrieval),
        "source_lineage": _source_unit_refs(candidate),
        "evidence_bundle": [
            {
                "paper_id": ref["paper_id"],
                "document_version_hash": ref["document_version_hash"],
                "source_unit_id": ref["source_unit_id"],
                "source_span_id": ref["source_span_id"],
                "assertion_id": ref["assertion_id"],
                "evidence_link_id": ref["evidence_link_id"],
                "evidence_role": ref["evidence_role"],
                "excerpt_hash": ref["excerpt_hash"],
                "verified_excerpt": ref["verified_excerpt"],
                "allowed_use": "SOURCE_BOUND_GAP_AND_PROPOSAL_SUPPORT",
            }
            for ref in _source_unit_refs(candidate)
        ],
        "claim_boundary": {
            "allowed_conclusion_strength": "type_specific_scope_bound_research_claim",
            "declared_scope": dict((candidate.get("research_question_contract") or {}).get("scientific_scope") or {}),
            "prohibits": [
                "unscoped_generalization",
                "derived_inference_as_primary_evidence",
                "proposed_action_as_established_result",
            ],
        },
        "proposal_authoring_contract_ref": {
            "schema_version": "proposal_authoring_contract_v2",
            "package_kind": package_kind_for(candidate).value,
        },
        "socrates_review_requirement": {
            "schema_version": "socrates_type_review_v2",
            "required": True,
            "review_scope": "type_specific_package_and_frozen_evidence_bundle",
        },
        "package_input_fingerprint": "pkg_" + sha256(
            "|".join(
                (
                    _text(candidate.get("candidate_identity")),
                    _text((candidate.get("graph_snapshot_ref") or {}).get("input_fingerprint")),
                    _text((candidate.get("research_question_contract") or {}).get("contract_revision")),
                    assessment["gap_type"],
                )
            ).encode("utf-8")
        ).hexdigest()[:24],
        "invalidated_by": [],
        "lifecycle_status": "CURRENT",
        "execution_requirements": {
            "falsification_or_discrimination": candidate.get("falsifiability_plan") or payload.get("falsification_plan") or {},
            "remaining_missing_axes": list(retrieval.get("remaining_missing_axes") or []),
            "claim_strength": "type_specific_scope_bound_research_claim",
        },
    }
    package["gate"] = research_package_gate(package)
    return package


def build_research_packages(project: dict[str, Any], candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Build one package per qualified candidate, preserving type diversity."""
    packages = [
        build_research_package(project, candidate)
        for candidate in candidates
        if isinstance(candidate, dict) and is_primary_research_candidate(candidate)
    ]
    packages.sort(key=lambda item: (str(item.get("gap_type") or ""), str(item.get("research_package_id") or "")))
    return packages


def select_research_package_candidates(
    project: dict[str, Any],
    qualified_gaps: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """Dispatch qualified gaps by package kind without causal coercion.

    The result is the one general selection entrypoint.  A caller needing a
    causal hypothesis uses the ``MECHANISM_HYPOTHESIS_PACKAGE`` bucket; a
    measurement, contradiction, theory, or boundary candidate remains in its
    own research-execution bucket.
    """
    grouped: dict[str, list[dict[str, Any]]] = {}
    secondary: list[dict[str, Any]] = []
    for candidate in qualified_gaps:
        if not isinstance(candidate, dict):
            continue
        try:
            assessment = assessment_of(candidate)
        except ValueError:
            continue
        if not is_primary_research_candidate(candidate):
            secondary.append(candidate)
            continue
        kind = package_kind_for(candidate).value
        grouped.setdefault(kind, []).append(candidate)
    for candidates in grouped.values():
        candidates.sort(key=lambda item: (str(item.get("gap_id") or ""), str(item.get("candidate_identity") or "")))
    grouped["secondary_research"] = secondary
    # Stable convenience names make orchestration intent readable while the
    # canonical package-kind keys remain exhaustive and domain-neutral.
    grouped["mechanism_hypothesis"] = list(grouped.get("MECHANISM_HYPOTHESIS_PACKAGE", []))
    grouped["boundary_condition"] = list(grouped.get("BOUNDARY_CONDITION_PACKAGE", []))
    grouped["measurement_validation"] = list(grouped.get("MEASUREMENT_VALIDATION_PACKAGE", []))
    grouped["theory_validation"] = list(grouped.get("THEORY_VALIDATION_PACKAGE", []))
    grouped["replication_resolution"] = list(grouped.get("REPLICATION_RESOLUTION_PACKAGE", []))
    return grouped


def group_research_packages_by_kind(packages: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for package in packages:
        if not isinstance(package, dict):
            continue
        kind = _text(package.get("package_kind"))
        if kind:
            grouped.setdefault(kind, []).append(package)
    for values in grouped.values():
        values.sort(key=lambda item: (str(item.get("research_package_id") or ""), int(item.get("package_version") or 0)))
    return grouped
