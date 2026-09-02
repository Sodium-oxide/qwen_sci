"""Type-specific Socrates review for qualified ``research_package_v2`` items.

Socrates may examine the evidence and planned design for a qualified package,
but this review is deliberately not a promotion gate.  In particular it cannot
turn a discovery lead, partial candidate, or old gap state into a primary
research candidate.
"""

from __future__ import annotations

from enum import Enum
from typing import Any
import time

try:
    from ._gap_types import ResearchPackageKind
    from ._research_packages import research_package_gate
except ImportError:
    from _gap_types import ResearchPackageKind
    from _research_packages import research_package_gate


class SocratesReviewMode(str, Enum):
    CAUSAL_EVIDENCE_REPAIR = "SocratesCausalEvidenceRepair"
    BOUNDARY_EVIDENCE_REVIEW = "SocratesBoundaryEvidenceReview"
    MEASUREMENT_VALIDATION_REVIEW = "SocratesMeasurementValidationReview"
    CONTRADICTION_RESOLUTION_REVIEW = "SocratesContradictionResolutionReview"
    THEORY_EVIDENCE_REVIEW = "SocratesTheoryEvidenceReview"
    GENERALIZATION_REVIEW = "SocratesGeneralizationReview"
    METHOD_DESIGN_REVIEW = "SocratesMethodDesignReview"
    EMPIRICAL_COVERAGE_REVIEW = "SocratesEmpiricalCoverageReview"
    MECHANISM_DISCRIMINATION_REVIEW = "SocratesMechanismDiscriminationReview"
    DATA_COVERAGE_REVIEW = "SocratesDataCoverageReview"
    SCALE_INTEGRATION_REVIEW = "SocratesScaleIntegrationReview"
    BENCHMARK_REVIEW = "SocratesBenchmarkComparisonReview"
    TRANSLATION_REVIEW = "SocratesTranslationImplementationReview"
    FOLLOWUP_LIMITATION_REVIEW = "SocratesFollowupLimitationReview"


_REVIEW_MODE_BY_PACKAGE_KIND: dict[ResearchPackageKind, SocratesReviewMode] = {
    ResearchPackageKind.MECHANISM_HYPOTHESIS: SocratesReviewMode.CAUSAL_EVIDENCE_REPAIR,
    ResearchPackageKind.MECHANISM_DISCRIMINATION: SocratesReviewMode.MECHANISM_DISCRIMINATION_REVIEW,
    ResearchPackageKind.EMPIRICAL_TEST: SocratesReviewMode.EMPIRICAL_COVERAGE_REVIEW,
    ResearchPackageKind.FOLLOWUP_RESOLUTION: SocratesReviewMode.FOLLOWUP_LIMITATION_REVIEW,
    ResearchPackageKind.BOUNDARY_CONDITION: SocratesReviewMode.BOUNDARY_EVIDENCE_REVIEW,
    ResearchPackageKind.REPLICATION_RESOLUTION: SocratesReviewMode.CONTRADICTION_RESOLUTION_REVIEW,
    ResearchPackageKind.MEASUREMENT_VALIDATION: SocratesReviewMode.MEASUREMENT_VALIDATION_REVIEW,
    ResearchPackageKind.THEORY_VALIDATION: SocratesReviewMode.THEORY_EVIDENCE_REVIEW,
    ResearchPackageKind.GENERALIZATION_VALIDATION: SocratesReviewMode.GENERALIZATION_REVIEW,
    ResearchPackageKind.METHOD_EVALUATION: SocratesReviewMode.METHOD_DESIGN_REVIEW,
    ResearchPackageKind.DATA_ACQUISITION: SocratesReviewMode.DATA_COVERAGE_REVIEW,
    ResearchPackageKind.SCALE_INTEGRATION: SocratesReviewMode.SCALE_INTEGRATION_REVIEW,
    ResearchPackageKind.BENCHMARK_DESIGN: SocratesReviewMode.BENCHMARK_REVIEW,
    ResearchPackageKind.TRANSLATION_FEASIBILITY: SocratesReviewMode.TRANSLATION_REVIEW,
}


_REVIEW_REQUIREMENTS: dict[SocratesReviewMode, dict[str, list[str]]] = {
    SocratesReviewMode.EMPIRICAL_COVERAGE_REVIEW: {
        "required_evidence_roles": ["declared phenomenon", "target object and condition", "scoped coverage search"],
        "disqualifying_evidence": ["scope-aligned direct evidence already covers the stated dimension"],
    },
    SocratesReviewMode.FOLLOWUP_LIMITATION_REVIEW: {
        "required_evidence_roles": ["verbatim author limitation", "affected claim", "post-limitation resolution search"],
        "disqualifying_evidence": ["generic future-work wording only", "direct follow-up already resolves the limitation"],
    },
    SocratesReviewMode.CAUSAL_EVIDENCE_REPAIR: {
        "required_evidence_roles": ["independent edge spans", "alternative explanation", "identification design"],
        "disqualifying_evidence": ["parallel effect", "temporal precedence only", "context mismatch"],
    },
    SocratesReviewMode.MECHANISM_DISCRIMINATION_REVIEW: {
        "required_evidence_roles": ["mechanism A evidence", "mechanism B evidence", "common endpoint", "discriminating prediction"],
        "disqualifying_evidence": ["unrelated mechanisms", "no observable distinction between paths"],
    },
    SocratesReviewMode.BOUNDARY_EVIDENCE_REVIEW: {
        "required_evidence_roles": ["comparable condition A", "comparable condition B", "named boundary variable"],
        "disqualifying_evidence": ["measurement non-comparability", "known boundary fully resolves difference"],
    },
    SocratesReviewMode.MEASUREMENT_VALIDATION_REVIEW: {
        "required_evidence_roles": ["construct", "proxy", "target or gold standard"],
        "disqualifying_evidence": ["existing direct calibration resolves mapping"],
    },
    SocratesReviewMode.CONTRADICTION_RESOLUTION_REVIEW: {
        "required_evidence_roles": ["independent result set A", "independent result set B", "comparability analysis"],
        "disqualifying_evidence": ["results differ only because of a known boundary variable"],
    },
    SocratesReviewMode.THEORY_EVIDENCE_REVIEW: {
        "required_evidence_roles": ["formal claim", "assumptions", "proof/counterexample path"],
        "disqualifying_evidence": ["already resolved theorem or counterexample"],
    },
    SocratesReviewMode.GENERALIZATION_REVIEW: {
        "required_evidence_roles": ["source-domain result", "target domain", "shift definition"],
        "disqualifying_evidence": ["scope-aligned external validation already resolves transport"],
    },
    SocratesReviewMode.METHOD_DESIGN_REVIEW: {
        "required_evidence_roles": ["current failure mode", "bias/identification problem", "alternative evaluation"],
        "disqualifying_evidence": ["alternative is not evaluably distinct"],
    },
    SocratesReviewMode.DATA_COVERAGE_REVIEW: {
        "required_evidence_roles": ["measured coverage deficiency", "impact on the claim", "feasible acquisition path"],
        "disqualifying_evidence": ["the asserted coverage is already available within scope"],
    },
    SocratesReviewMode.SCALE_INTEGRATION_REVIEW: {
        "required_evidence_roles": ["source scale", "target scale", "bridge variable", "coupling test"],
        "disqualifying_evidence": ["a validated bridge already spans the declared scales"],
    },
    SocratesReviewMode.BENCHMARK_REVIEW: {
        "required_evidence_roles": ["candidate systems", "common task", "shared metric", "comparison protocol"],
        "disqualifying_evidence": ["an accepted fair benchmark already resolves the comparison"],
    },
    SocratesReviewMode.TRANSLATION_REVIEW: {
        "required_evidence_roles": ["validated source claim", "deployment context", "implementation barrier", "feasibility criterion"],
        "disqualifying_evidence": ["scope-aligned real-world validation already resolves feasibility"],
    },
}


def review_mode_for_package(package: dict[str, Any]) -> SocratesReviewMode:
    try:
        kind = ResearchPackageKind(str(package.get("package_kind") or ""))
    except ValueError as exc:
        raise ValueError("Type-specific Socrates review requires a known research_package_v2 kind") from exc
    return _REVIEW_MODE_BY_PACKAGE_KIND[kind]


def _requirements_for(mode: SocratesReviewMode) -> dict[str, list[str]]:
    return _REVIEW_REQUIREMENTS.get(
        mode,
        {
            "required_evidence_roles": ["type payload", "source lineage", "type-specific execution requirement"],
            "disqualifying_evidence": ["direct resolution within declared scope"],
        },
    )


def build_socrates_type_review_request(project: dict[str, Any], package: dict[str, Any]) -> dict[str, Any]:
    """Build a bounded, package-kind-specific review task."""
    gate = research_package_gate(package)
    mode = review_mode_for_package(package)
    requirements = _requirements_for(mode)
    return {
        "schema_version": "socrates_type_review_request_v2",
        "project_id": str(project.get("project_id") or ""),
        "gap_id": str(package.get("gap_id") or ""),
        "research_package_id": str(package.get("research_package_id") or ""),
        "package_version": int(package.get("package_version") or 0),
        "review_mode": mode.value,
        "package_kind": str(package.get("package_kind") or ""),
        "required_evidence_roles": requirements["required_evidence_roles"],
        "disqualifying_evidence": requirements["disqualifying_evidence"],
        "type_payload": dict(package.get("type_payload") or {}),
        "source_lineage": list(package.get("source_lineage") or []),
        "retrieval_assessment": dict(package.get("retrieval_assessment") or {}),
        "execution_requirements": dict(package.get("execution_requirements") or {}),
        "package_gate": gate,
        "review_rule": (
            "Review only this package's bound source lineage and type contract. "
            "Do not infer missing facts, change the gap type, or promote an unqualified candidate."
        ),
    }


def review_type_specific_research_package(project: dict[str, Any], package: dict[str, Any]) -> dict[str, Any]:
    """Produce a deterministic review dossier for one already-qualified package."""
    request = build_socrates_type_review_request(project, package)
    gate = request["package_gate"]
    retrieval = request["retrieval_assessment"]
    missing_axes = [str(item) for item in retrieval.get("remaining_missing_axes", []) if str(item)]
    review_ready = bool(gate.get("passes") is True and request["source_lineage"] and not missing_axes)
    return {
        "schema_version": "socrates_type_review_v2",
        "project_id": request["project_id"],
        "gap_id": request["gap_id"],
        "research_package_id": request["research_package_id"],
        "package_version": request["package_version"],
        "review_mode": request["review_mode"],
        "package_kind": request["package_kind"],
        "status": "TYPE_SPECIFIC_REVIEW_READY" if review_ready else "TYPE_SPECIFIC_REVIEW_BLOCKED",
        "review_ready": review_ready,
        "required_evidence_roles": request["required_evidence_roles"],
        "disqualifying_evidence": request["disqualifying_evidence"],
        "remaining_missing_axes": missing_axes,
        "reason": (
            "The qualified package has source lineage and no remaining declared retrieval axes; execute its type-specific design."
            if review_ready
            else "The package is not execution-ready; repair only the declared type-specific evidence/design deficiencies."
        ),
        "request": request,
    }


def run_socrates_type_specific_review(project_id: str, gap_id: str) -> dict[str, Any]:
    """Load and persist one type-specific review without a mechanism fallback."""
    try:
        from ._project import load_project, save_project
    except ImportError:
        from _project import load_project, save_project
    project = load_project(project_id)
    try:
        from ._research_workflow import (
            PROPOSAL_BRIEF_STAGE,
            TYPE_SPECIFIC_SOCRATES_REVIEW_STAGE,
            record_workflow_execution,
            record_workflow_status,
            workflow_tool_gate,
        )
    except ImportError:
        from _research_workflow import (
            PROPOSAL_BRIEF_STAGE,
            TYPE_SPECIFIC_SOCRATES_REVIEW_STAGE,
            record_workflow_execution,
            record_workflow_status,
            workflow_tool_gate,
        )
    gate = workflow_tool_gate(
        project,
        TYPE_SPECIFIC_SOCRATES_REVIEW_STAGE,
        {"gap_id": gap_id},
    )
    if not gate.get("allowed"):
        return dict(gate.get("result") or {})
    package = next(
        (
            item for item in project.get("research_packages", [])
            if isinstance(item, dict) and str(item.get("gap_id") or "") == str(gap_id)
        ),
        None,
    )
    if not isinstance(package, dict):
        raise ValueError("No current research_package_v2 exists for this gap")
    review = review_type_specific_research_package(project, package)
    reviews = project.get("socrates_type_reviews") if isinstance(project.get("socrates_type_reviews"), dict) else {}
    if review["review_ready"]:
        ready_package_ids = sorted(
            str(item.get("research_package_id") or "")
            for item in reviews.values()
            if isinstance(item, dict)
            and item.get("review_ready") is True
            and str(item.get("research_package_id") or "")
        )
        ready_package_ids = sorted(set([*ready_package_ids, str(package.get("research_package_id") or "")]))
        workflow_state = record_workflow_status(
            project,
            stage=TYPE_SPECIFIC_SOCRATES_REVIEW_STAGE,
            status="TYPE_SPECIFIC_REVIEW_COMPLETE_READY_FOR_PROPOSAL",
            terminal=False,
            allowed_next_stages=[PROPOSAL_BRIEF_STAGE],
            blocked_stages=[],
            reason_code="TYPE_SPECIFIC_REVIEW_COMPLETED_READY_FOR_PROPOSAL",
            artifact_ids=ready_package_ids,
            remediation_plan={},
        )
    else:
        workflow_state = record_workflow_status(
            project,
            stage=TYPE_SPECIFIC_SOCRATES_REVIEW_STAGE,
            status="TYPE_SPECIFIC_REVIEW_BLOCKED",
            terminal=False,
            allowed_next_stages=[],
            blocked_stages=[PROPOSAL_BRIEF_STAGE],
            reason_code="TYPE_SPECIFIC_REVIEW_REQUIREMENTS_INCOMPLETE",
            artifact_ids=[str(gap_id)],
            remediation_plan={"kind": "repair_type_specific_package", "remaining_missing_axes": review["remaining_missing_axes"]},
        )
    review.update(workflow_state)
    reviews[str(gap_id)] = review
    project["socrates_type_reviews"] = reviews
    try:
        from ._research_graph import persist_research_task_graph
    except ImportError:
        from _research_graph import persist_research_task_graph
    persist_research_task_graph(project)
    record_workflow_execution(
        project,
        TYPE_SPECIFIC_SOCRATES_REVIEW_STAGE,
        {"gap_id": gap_id},
        review,
        execution_key=str(gate.get("execution_key") or ""),
    )
    project["updatedAt"] = time.time()
    save_project(project)
    return review
