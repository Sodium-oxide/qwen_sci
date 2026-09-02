"""Type-directed literature retrieval planning and post-retrieval qualification.

The planner generates neutral evidence questions from a V3 gap contract.  It
does not execute search itself and it never treats a missing local mention as
evidence that the scientific gap is open.
"""

from __future__ import annotations

from hashlib import sha256
import json
from typing import Any

try:
    from .log import log_event
except ImportError:
    from log import log_event

try:
    from ._gap_types import (
        CandidateStage,
        EvidenceMaturity,
        GapLifecyclePhase,
        GapRoute,
        ScopeStatus,
        SemanticVerdict,
        assessment_of,
        contract_for,
        missing_payload_fields,
        package_kind_for,
        payload_of,
        synchronize_candidate_surface,
    )
except ImportError:
    from _gap_types import (
        CandidateStage,
        EvidenceMaturity,
        GapLifecyclePhase,
        GapRoute,
        ScopeStatus,
        SemanticVerdict,
        assessment_of,
        contract_for,
        missing_payload_fields,
        package_kind_for,
        payload_of,
        synchronize_candidate_surface,
    )


def _text(value: Any) -> str:
    return " ".join(str(value or "").split())


def _fingerprint(value: dict[str, Any]) -> str:
    """Return a stable identifier for an immutable V3 workflow artefact."""

    return "sha256:" + sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()


def _gap_candidate_retrieval_fingerprint(candidate: dict[str, Any]) -> str:
    """Fingerprint the V3 candidate material a GAP_RESOLUTION item owns."""

    source = candidate if isinstance(candidate, dict) else {}
    return _fingerprint({
        "candidate_identity": _text(source.get("candidate_identity")),
        "gap_type": _text(
            ((source.get("retrieval_plan") or {}).get("gap_type"))
            if isinstance(source.get("retrieval_plan"), dict)
            else ""
        ),
        "source_assertion_ids": list(source.get("source_assertion_ids") or []),
        "type_payload": dict(source.get("type_payload") or {}),
        "evidence_graph_contract": dict(source.get("evidence_graph_contract") or {}),
    })


def _primary_source_span_gate(
    project: dict[str, Any],
    candidate: dict[str, Any],
    semantic_audit: dict[str, Any],
    retrieval_assessment: dict[str, Any],
) -> dict[str, Any]:
    """Verify current-v3 source lineage before any primary research route.

    The source span is not merely an identifier: it must contain a verified,
    quoted excerpt.  Both semantic and retrieval artefacts must cite only
    those spans, and every originating paper must satisfy the current source
    admission contract.  No legacy project field can satisfy this gate.
    """
    units = [item for item in candidate.get("source_evidence_units", []) if isinstance(item, dict)]
    source_ids = {
        _text(item.get("source_unit_id"))
        for item in units
        if _text(item.get("source_unit_id"))
    }
    pipeline_bound = bool(candidate.get("evidence_graph_contract"))
    verified_source_ids = {
        _text(item.get("source_unit_id"))
        for item in units
        if _text(item.get("source_unit_id"))
        and _text(item.get("excerpt_hash"))
        and _text(item.get("excerpt"))
        and (not pipeline_bound or _text(item.get("document_version_hash")))
        and _text(item.get("binding_status")) == "SOURCE_UNIT_VERIFIED"
    }
    semantic_lineage = semantic_audit
    if not isinstance(semantic_lineage.get("supporting_source_unit_ids"), list):
        deterministic = semantic_audit.get("deterministic")
        semantic_lineage = deterministic if isinstance(deterministic, dict) else semantic_audit
    semantic_source_ids = {
        _text(item)
        for item in semantic_lineage.get("supporting_source_unit_ids", [])
        if _text(item)
    }
    retrieval_source_ids = {
        _text(item)
        for item in retrieval_assessment.get("supporting_source_unit_ids", [])
        if _text(item)
    }
    records = [
        item
        for collection in (project.get("papergraph"), project.get("evidence"))
        if isinstance(collection, list)
        for item in collection
        if isinstance(item, dict)
    ]
    question_contract = candidate.get("research_question_contract") if isinstance(candidate.get("research_question_contract"), dict) else {}
    contract_id = _text(question_contract.get("contract_id"))
    graph_contract = candidate.get("evidence_graph_contract") if isinstance(candidate.get("evidence_graph_contract"), dict) else {}
    contract_revision = _text(graph_contract.get("research_question_contract_revision"))
    expected_document_versions = {
        _text(item.get("document_version_hash"))
        for item in units
        if _text(item.get("document_version_hash"))
    }
    admissions_by_paper = {
        _text(record.get("paper_id")): (record.get("gap_source_admissions_v4") or {}).get(contract_id)
        for record in records
        if isinstance(record.get("gap_source_admissions_v4"), dict)
        and isinstance((record.get("gap_source_admissions_v4") or {}).get(contract_id), dict)
        and (record.get("gap_source_admissions_v4") or {}).get(contract_id, {}).get("schema_version") == "gap_source_admission_v4"
        and isinstance(record.get("evidence_projection_v4"), dict)
        and record["evidence_projection_v4"].get("schema_version") == "evidence_projection_v4"
        and record["evidence_projection_v4"].get("status") == "CURRENT"
        and (
            not expected_document_versions
            or _text(record["evidence_projection_v4"].get("document_version_hash")) in expected_document_versions
        )
        and (
            not contract_revision
            or _text(
                (record["evidence_projection_v4"].get("research_question_contract_revisions") or {}).get(contract_id)
            ) == contract_revision
        )
    }
    paper_ids = {_text(item.get("paper_id")) for item in units if _text(item.get("paper_id"))}
    admitted_papers = {
        paper_id
        for paper_id in paper_ids
        if isinstance(admissions_by_paper.get(paper_id), dict)
        and _text(admissions_by_paper[paper_id].get("admission_level")) == "DIRECT_EVIDENCE"
        and admissions_by_paper[paper_id].get("eligible_for_gap_synthesis") is True
        and admissions_by_paper[paper_id].get("direct_evidence_eligible") is True
    }
    failure_codes: list[str] = []
    if not source_ids or source_ids != verified_source_ids:
        failure_codes.append("UNVERIFIED_OR_UNQUOTED_SOURCE_SPAN")
    if not semantic_source_ids or not semantic_source_ids.issubset(source_ids):
        failure_codes.append("SEMANTIC_AUDIT_SOURCE_LINEAGE_INCOMPLETE")
    if not retrieval_source_ids or not retrieval_source_ids.issubset(source_ids):
        failure_codes.append("RETRIEVAL_SOURCE_LINEAGE_INCOMPLETE")
    if paper_ids != admitted_papers:
        failure_codes.append("PRIMARY_SOURCE_ADMISSION_NOT_PASSED")
    return {
        "schema_version": "primary_source_span_gate_v3",
        "status": "PASSED" if not failure_codes else "BLOCKED",
        "source_unit_ids": sorted(source_ids),
        "semantic_audit_source_unit_ids": sorted(semantic_source_ids),
        "retrieval_source_unit_ids": sorted(retrieval_source_ids),
        "admitted_paper_ids": sorted(admitted_papers),
        "research_question_contract_revision": contract_revision,
        "document_version_hashes": sorted(expected_document_versions),
        "failure_codes": failure_codes,
    }


def _query_terms(candidate: dict[str, Any]) -> list[str]:
    payload = payload_of(candidate)
    question = candidate.get("research_question") if isinstance(candidate.get("research_question"), dict) else {}
    values = [
        question.get("object"),
        question.get("known_claim"),
        question.get("unknown_claim"),
        *payload.values(),
    ]
    output: list[str] = []
    for value in values:
        if isinstance(value, (list, tuple, set)):
            value = " ".join(_text(item) for item in value)
        elif isinstance(value, dict):
            value = " ".join(_text(item) for item in value.values())
        text = _text(value)
        if text and text not in output:
            output.append(text[:320])
    return output[:4]


_RETRIEVAL_INTENTS: dict[str, dict[str, tuple[str, ...]]] = {
    "EMPIRICAL_COVERAGE_GAP": {
        "positive": ("direct observation under declared condition", "scope-specific empirical coverage"),
        "negative": ("complete coverage systematic review", "direct study of declared object condition"),
        "review": ("coverage review",),
        "primary": ("direct empirical study",),
    },
    "AUTHOR_STATED_LIMITATION_GAP": {
        "positive": ("follow-up resolving stated limitation",),
        "negative": ("limitation directly resolved", "post-publication follow-up"),
        "review": ("limitation review",),
        "primary": ("follow-up primary study",),
    },
    "CAUSAL_IDENTIFICATION_GAP": {
        "positive": ("intervention quasi-experiment longitudinal identification", "mediation moderation confounding control"),
        "negative": ("causal effect directly identified", "competing explanation tested"),
        "review": ("causal identification systematic review",),
        "primary": ("intervention experiment natural experiment",),
    },
    "MECHANISM_COMPETITION_GAP": {
        "positive": ("mechanism discrimination prediction intervention",),
        "negative": ("competing mechanisms distinguished",),
        "review": ("mechanism comparison review",),
        "primary": ("discriminating experiment joint measurement",),
    },
    "BOUNDARY_HETEROGENEITY_GAP": {
        "positive": ("threshold interaction stratified regime comparison",),
        "negative": ("boundary condition already established",),
        "review": ("heterogeneity boundary review",),
        "primary": ("stratified experiment interaction analysis",),
    },
    "CONTRADICTION_REPLICATION_GAP": {
        "positive": ("replication reanalysis unified protocol",),
        "negative": ("meta-analysis resolves discrepancy",),
        "review": ("replication systematic review meta-analysis",),
        "primary": ("independent replication reanalysis",),
    },
    "MEASUREMENT_OPERATIONALIZATION_GAP": {
        "positive": ("gold standard calibration external validation measurement error",),
        "negative": ("proxy validity directly validated",),
        "review": ("measurement validation review",),
        "primary": ("calibration study cross-instrument comparison",),
    },
    "THEORY_MATHEMATICAL_GAP": {
        "positive": ("proof counterexample identifiability theorem extension",),
        "negative": ("formal result already proved counterexample",),
        "review": ("formal theory review",),
        "primary": ("proof counterexample numerical verification",),
    },
    "GENERALIZATION_TRANSPORTABILITY_GAP": {
        "positive": ("external validation out-of-distribution transportability",),
        "negative": ("target-domain validation domain shift analysis",),
        "review": ("generalization transportability review",),
        "primary": ("external validation transfer experiment",),
    },
    "METHOD_DESIGN_GAP": {
        "positive": ("bias analysis alternative design ablation",),
        "negative": ("method failure resolved comparative evaluation",),
        "review": ("methods comparison review",),
        "primary": ("controlled method comparison",),
    },
    "DATA_COVERAGE_GAP": {
        "positive": ("missing variable population regime long-horizon data acquisition",),
        "negative": ("dataset coverage already available",),
        "review": ("dataset coverage review",),
        "primary": ("data collection dataset release",),
    },
    "SCALE_INTEGRATION_GAP": {
        "positive": ("cross-scale coupling bridge variable multiscale validation",),
        "negative": ("scale bridge already validated",),
        "review": ("multiscale integration review",),
        "primary": ("multiscale experiment coupling analysis",),
    },
    "BENCHMARK_COMPARISON_GAP": {
        "positive": ("shared benchmark common task common metric fair protocol",),
        "negative": ("benchmark protocol already established",),
        "review": ("benchmark comparison review",),
        "primary": ("benchmark study common evaluation",),
    },
    "TRANSLATION_IMPLEMENTATION_GAP": {
        "positive": ("real-world validation implementation barrier deployment feasibility",),
        "negative": ("deployment feasibility already validated",),
        "review": ("implementation translation review",),
        "primary": ("field deployment feasibility study",),
    },
}


def _queries(joined_terms: str, intents: tuple[str, ...]) -> list[str]:
    return [" ".join(part for part in (joined_terms, intent) if part).strip() for intent in intents]


def build_gap_search_plan(project: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    """Build a falsifiable, type-specific plan after semantic audit.

    Search terms are derived only from structured candidate fields.  The plan
    always contains resolution and disqualification queries so a retriever is
    not rewarded merely for finding confirmatory papers.
    """
    assessment = assessment_of(candidate)
    contract = contract_for(assessment["gap_type"])
    terms = _query_terms(candidate)
    joined = " ; ".join(terms)
    axes = list(contract.required_retrieval_axes)
    intents = _RETRIEVAL_INTENTS[assessment["gap_type"]]
    return {
        "schema_version": "gap_search_plan_v3",
        "project_id": _text(project.get("project_id")),
        "gap_id": _text(candidate.get("gap_id")),
        "candidate_identity": _text(candidate.get("candidate_identity")),
        "gap_type": assessment["gap_type"],
        "gap_subtype": _text(assessment.get("gap_subtype")),
        "package_kind": package_kind_for(candidate).value,
        "missing_axes": axes,
        "resolution_question": (
            f"Within the declared object and conditions, has the specified {assessment['gap_type']} "
            "already been directly resolved, and what evidence remains missing if not?"
        ),
        "positive_queries": _queries(joined, intents["positive"]),
        "negative_queries": _queries(joined, intents["negative"]),
        "review_queries": _queries(joined, intents["review"]),
        "primary_source_queries": _queries(joined, intents["primary"]),
        "query_intents": {
            "OPEN_GAP_EVIDENCE": _queries(joined, intents["positive"]),
            "RESOLUTION_OR_DISQUALIFICATION": _queries(
                joined,
                tuple([*intents["negative"], *intents["review"]]),
            ),
        },
        "required_source_roles": ["DIRECT_PRIMARY_EVIDENCE", "INDEPENDENT_REPLICATION_OR_REVIEW"],
        "disqualifying_evidence": [
            "A direct, scope-aligned study resolves the declared unknown.",
            "A review or meta-analysis concludes the issue is resolved within the declared scope.",
            "The candidate's relation or measurement mapping is contradicted by source-bound evidence.",
        ],
        "stop_conditions": [
            "Direct resolution evidence is found.",
            "Two independent scope-aligned sources establish the same answer.",
            "The bounded search budget is exhausted without direct resolution evidence.",
        ],
        "lifecycle_contract": {
            "semantic_phase": GapLifecyclePhase.SEMANTIC_AUDIT.value,
            "primary_phase": GapLifecyclePhase.PRIMARY_QUALIFICATION.value,
            "retrieval_result_schema": "gap_targeted_retrieval_result_v3",
            "rebind_required_before_qualification": True,
            "reaudit_required_after_rebind": True,
        },
        "provider_execution_contract": {
            "schema_version": "gap_provider_execution_contract_v3",
            "required_query_intents": [
                "OPEN_GAP_EVIDENCE",
                "RESOLUTION_OR_DISQUALIFICATION",
            ],
            "generic_topic_search_permitted": False,
            "provider_outcome_schema": "provider_outcome_v3",
            "cache_scope": "candidate_fingerprint_contract_revision_plan_fingerprint_query_fingerprint",
        },
    }


def build_gap_resolution_work_item_v3(
    candidate: dict[str, Any],
    *,
    target_slot_ids: list[str],
    graph_snapshot_id: str,
) -> dict[str, Any]:
    """Construct a current V3 GAP_RESOLUTION item from explicit caller scope.

    A gap plan cannot silently borrow every slot of an SH.  The caller must
    identify the exact evidence slots whose unresolved obligation the paired
    search is meant to inform, and must provide the immutable graph snapshot
    against which returned evidence will later be rebound.
    """

    try:
        from ._research_question_contract import (
            build_retrieval_obligation_v3,
            build_retrieval_work_item_v3,
            validate_research_question_contract,
        )
    except ImportError:
        from _research_question_contract import (
            build_retrieval_obligation_v3,
            build_retrieval_work_item_v3,
            validate_research_question_contract,
        )
    source = candidate if isinstance(candidate, dict) else {}
    plan = source.get("retrieval_plan") if isinstance(source.get("retrieval_plan"), dict) else {}
    if plan.get("schema_version") != "gap_search_plan_v3":
        raise ValueError("GapResolution work item requires the active gap_search_plan_v3")
    contract = validate_research_question_contract(source.get("research_question_contract"))
    candidate_identity = _text(source.get("candidate_identity"))
    gap_type = _text(plan.get("gap_type"))
    slots = sorted({_text(slot) for slot in target_slot_ids if _text(slot)})
    if not candidate_identity or not gap_type or not slots or not _text(graph_snapshot_id):
        raise ValueError("GapResolution work item requires candidate identity, gap type, explicit target slots, and graph snapshot")
    source_roles = [
        _text(role)
        for role in plan.get("required_source_roles", [])
        if _text(role)
    ]
    required_role = source_roles[0] if source_roles else "DIRECT_PRIMARY_EVIDENCE"
    obligations = [
        build_retrieval_obligation_v3(
            contract,
            slot_id=slot,
            evidence_role="GAP_RESOLUTION",
            required_source_role=required_role,
        )
        for slot in slots
    ]
    candidate_fingerprint = _gap_candidate_retrieval_fingerprint(source)
    return build_retrieval_work_item_v3(
        contract,
        work_item_kind="GAP_RESOLUTION",
        target_slot_ids=slots,
        obligations=obligations,
        plan_fingerprint=_fingerprint(plan),
        gap_candidate_id=candidate_identity,
        gap_candidate_fingerprint=candidate_fingerprint,
        gap_type=gap_type,
        graph_snapshot_id=_text(graph_snapshot_id),
    )


def compile_gap_retrieval_queries_v3(
    candidate: dict[str, Any],
    *,
    provider: str,
    retrieval_work_item_v3: dict[str, Any],
    plan_revision: str,
) -> list[dict[str, Any]]:
    """Compile the paired open/resolution queries from a V3 gap plan only."""

    try:
        from ._retrieval_execution_v3 import compile_gap_query_variants_v3
    except ImportError:
        from _retrieval_execution_v3 import compile_gap_query_variants_v3
    source = candidate if isinstance(candidate, dict) else {}
    plan = source.get("retrieval_plan") if isinstance(source.get("retrieval_plan"), dict) else {}
    return compile_gap_query_variants_v3(
        provider,
        plan,
        retrieval_work_item_v3,
        plan_revision=plan_revision,
    )


def plan_targeted_retrieval(project: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    """Attach a search plan; this operation does not grant primary status."""
    assessment = assessment_of(candidate)
    updated = dict(candidate)
    updated_assessment = dict(assessment)
    blockers: list[str] = []
    if assessment.get("semantic_verdict") != SemanticVerdict.ENTAILED.value:
        blockers.append("SEMANTIC_ENTAILMENT_REQUIRED")
    if assessment.get("scope_status") not in {ScopeStatus.CORE.value, ScopeStatus.COMPONENT_BRIDGE.value}:
        blockers.append("CORE_OR_COMPONENT_BRIDGE_SCOPE_REQUIRED")
    discovery_missing = missing_payload_fields(
        candidate,
        lifecycle_phase=GapLifecyclePhase.DISCOVERY,
    )
    if discovery_missing:
        blockers.extend("MISSING_DISCOVERY_PAYLOAD:" + item for item in discovery_missing)
    # V3 deliberately permits semantic-enrichment and primary-package fields
    # to remain absent here.  Targeted retrieval is how those deficits are
    # resolved; asking for them before planning would be a circular gate.
    allowed = not blockers
    updated_assessment.update(
        {
            "candidate_stage": CandidateStage.RETRIEVAL_PLANNED.value if allowed else assessment.get("candidate_stage"),
            "route": GapRoute.TARGETED_RETRIEVAL.value if allowed else GapRoute.DIAGNOSTIC.value,
            "decision_reasons": (
                ["TYPE_DIRECTED_RETRIEVAL_REQUIRED"]
                if allowed
                else ["RETRIEVAL_BLOCKED"] + blockers
            ),
        }
    )
    updated["retrieval_plan"] = build_gap_search_plan(project, candidate) if allowed else {}
    updated["retrieval_transition"] = {
        "schema_version": "gap_lifecycle_transition_v3",
        "from_stage": _text(assessment.get("candidate_stage")),
        "to_stage": CandidateStage.RETRIEVAL_PLANNED.value if allowed else _text(assessment.get("candidate_stage")),
        "route": GapRoute.TARGETED_RETRIEVAL.value if allowed else GapRoute.DIAGNOSTIC.value,
        "blockers": blockers,
        "semantic_payload_deficits": missing_payload_fields(
            candidate,
            lifecycle_phase=GapLifecyclePhase.SEMANTIC_AUDIT,
        ),
        "primary_payload_deficits": missing_payload_fields(
            candidate,
            lifecycle_phase=GapLifecyclePhase.PRIMARY_QUALIFICATION,
        ),
    }
    return synchronize_candidate_surface(updated, updated_assessment)


def build_slot_directed_recovery_plan(
    project: dict[str, Any],
    branch_state: dict[str, Any],
) -> dict[str, Any]:
    """Create a bounded recovery task for exact uncovered research slots.

    This plan is intentionally not a generic topic search.  It can only be
    created for a current V3 branch state with named missing direct slots.
    """

    branch = branch_state if isinstance(branch_state, dict) else {}
    sub_hypothesis_id = _text(branch.get("sub_hypothesis_id"))
    contract_id = _text(branch.get("research_question_contract_id"))
    contract_revision = _text(
        branch.get("research_question_contract_revision")
        or branch.get("contract_revision")
    )
    missing_slot_ids = sorted(
        {_text(item) for item in branch.get("missing_direct_slot_ids", []) if _text(item)}
    )
    if (
        _text(branch.get("recovery_failure_type")) != "GENUINE_SLOT_SHORTAGE"
        or branch.get("slot_directed_retrieval_allowed") is not True
    ):
        raise ValueError(
            "Slot-directed retrieval is reserved for a classified GENUINE_SLOT_SHORTAGE"
        )
    if not sub_hypothesis_id or not contract_id or not contract_revision or not missing_slot_ids:
        raise ValueError("Slot-directed recovery requires a V3 branch with contract id and missing direct slot ids")
    sub_hypotheses = (
        project.get("sub_hypotheses")
        if isinstance(project.get("sub_hypotheses"), list)
        else []
    )
    sub_hypothesis = next(
        (
            item
            for item in sub_hypotheses
            if isinstance(item, dict)
            and _text(item.get("id") or item.get("sub_hypothesis_id"))
            == sub_hypothesis_id
        ),
        {},
    )
    contract = (
        sub_hypothesis.get("research_question_contract")
        if isinstance(sub_hypothesis.get("research_question_contract"), dict)
        else {}
    )
    if (
        _text(contract.get("schema_version")) != "research_question_contract_v3"
        or _text(contract.get("contract_id")) != contract_id
        or _text(contract.get("contract_revision") or contract.get("declaration_hash"))
        != contract_revision
    ):
        raise ValueError("SLOT_RECOVERY_CURRENT_RESEARCH_QUESTION_CONTRACT_V3_REQUIRED")
    try:
        from ._research_question_contract import build_question_retrieval_plan
    except ImportError:
        from _research_question_contract import build_question_retrieval_plan
    current_plan = build_question_retrieval_plan(contract)
    recovery_tasks = [
        dict(task)
        for task in current_plan.get("tasks", [])
        if isinstance(task, dict)
        and set(_text(slot) for slot in task.get("target_slot_ids", []) if _text(slot))
        & set(missing_slot_ids)
    ]
    if not recovery_tasks:
        raise ValueError("SLOT_RECOVERY_CURRENT_V3_TASKS_NOT_FOUND_FOR_MISSING_SLOTS")
    work_items = [
        dict(task.get("retrieval_work_item_v3") or {})
        for task in recovery_tasks
        if isinstance(task.get("retrieval_work_item_v3"), dict)
        and _text((task.get("retrieval_work_item_v3") or {}).get("schema_version"))
        == "retrieval_work_item_v3"
    ]
    if len(work_items) != len(recovery_tasks):
        raise ValueError("SLOT_RECOVERY_CURRENT_V3_WORK_ITEM_REQUIRED")
    result_envelopes = [
        {
            "schema_version": "slot_recovery_result_envelope_v3",
            "status": "PENDING",
            "execution_status": "NOT_EXECUTED",
            "project_id": _text(project.get("project_id")),
            "sub_hypothesis_id": sub_hypothesis_id,
            "research_question_contract_id": contract_id,
            "research_question_contract_revision": contract_revision,
            "plan_revision": _text(current_plan.get("plan_revision")),
            "task_id": _text(task.get("task_id")),
            "target_slot_ids": list(task.get("target_slot_ids") or []),
            "retrieval_work_item_v3": dict(task.get("retrieval_work_item_v3") or {}),
            "evidence_disposition": "NOT_ACQUIRED",
            "admission_status": "PENDING",
            "scientific_conclusion_allowed": False,
        }
        for task in recovery_tasks
    ]
    return {
        "schema_version": "slot_directed_recovery_plan_v3",
        "project_id": _text(project.get("project_id")),
        "sub_hypothesis_id": sub_hypothesis_id,
        "research_question_contract_id": contract_id,
        "contract_revision": contract_revision,
        "recovery_kind": "DIRECT_SLOT_EVIDENCE_RECOVERY",
        "target_slot_ids": missing_slot_ids,
        "retrieval_plan_v3": current_plan,
        "retrieval_work_items_v3": work_items,
        "current_result_envelopes_v3": result_envelopes,
        "query_constraints": {
            "must_preserve_contract_scope": True,
            "must_bind_returned_source_spans": True,
            "must_extract_explicit_assertions": True,
            "generic_topic_search_permitted": False,
        },
        "success_criteria": [
            "A returned document is versioned and source-span bound.",
            "At least one explicit assertion is admitted for a target slot.",
            "The branch slot coverage ledger changes from MISSING after extraction review.",
        ],
        "failure_interpretation": "No result or a provider error is retrieval coverage information, not a scientific gap verdict.",
    }


def build_gap_targeted_retrieval_result_v3(
    candidate: dict[str, Any],
    snapshot: dict[str, Any],
    *,
    target_slot_ids: list[str],
    admitted_source_evidence_units: list[dict[str, Any]],
    retrieval_work_item_v3: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Assemble one gap-targeted V3 result from *current admitted evidence*.

    Discovery metadata, abstracts, candidate-paper rows, and derived
    inferences do not enter this boundary.  The caller may supply a runtime
    excerpt only for an assertion/span pair that already exists in the exact
    current graph snapshot and has an ``evidence_admission_v4`` record for a
    requested slot.  Full text with no qualifying slot support is reported as
    ``INCONCLUSIVE``; it is neither turned into direct evidence nor treated as
    proof that a scientific gap is open.
    """

    try:
        from ._research_graph import graph_snapshot_ref
    except ImportError:
        from _research_graph import graph_snapshot_ref

    source = candidate if isinstance(candidate, dict) else {}
    graph = snapshot if isinstance(snapshot, dict) else {}
    if _text(graph.get("schema_version")) != "research_evidence_graph_v4":
        raise ValueError("gap_targeted_retrieval_result_v3 requires research_evidence_graph_v4")
    graph_ref = graph_snapshot_ref(graph)
    if not _text(graph_ref.get("snapshot_id")):
        raise ValueError("Current V3 graph snapshot requires a snapshot_id")
    plan = source.get("retrieval_plan") if isinstance(source.get("retrieval_plan"), dict) else {}
    if _text(plan.get("schema_version")) != "gap_search_plan_v3":
        raise ValueError("Gap-targeted result requires the active gap_search_plan_v3")
    candidate_identity = _text(source.get("candidate_identity"))
    if not candidate_identity:
        raise ValueError("Gap-targeted result requires candidate_identity")
    requested_slots = sorted({_text(slot) for slot in target_slot_ids if _text(slot)})
    if not requested_slots:
        raise ValueError("Gap-targeted result requires explicit target_slot_ids")
    if retrieval_work_item_v3 is not None:
        work_item = retrieval_work_item_v3 if isinstance(retrieval_work_item_v3, dict) else {}
        if _text(work_item.get("schema_version")) != "retrieval_work_item_v3":
            raise ValueError("Gap-targeted result rejects a non-V3 retrieval work item")
        if _text(work_item.get("gap_candidate_id")) != candidate_identity:
            raise ValueError("Gap-targeted work item belongs to a different candidate")
        if _text(work_item.get("graph_snapshot_id")) != _text(graph_ref.get("snapshot_id")):
            raise ValueError("Gap-targeted work item is not bound to the current graph snapshot")
        work_item_slots = sorted({_text(slot) for slot in work_item.get("target_slot_ids", []) if _text(slot)})
        if work_item_slots != requested_slots:
            raise ValueError("Gap-targeted work item target slots differ from result target slots")

    nodes = [item for item in graph.get("nodes", []) if isinstance(item, dict)]
    assertions = {
        _text(item.get("node_id")): item
        for item in nodes
        if item.get("node_type") == "EVIDENCE_ASSERTION" and _text(item.get("node_id"))
    }
    spans = {
        _text(item.get("node_id")): item
        for item in nodes
        if item.get("node_type") == "SOURCE_SPAN" and _text(item.get("node_id"))
    }
    direct_admissions = {
        (
            _text(item.get("assertion_id")),
            _text(item.get("slot_id")),
        )
        for item in graph.get("evidence_admissions", [])
        if isinstance(item, dict)
        and _text(item.get("schema_version")) == "evidence_admission_v4"
        and _text(item.get("status")) == "ADMITTED_DIRECT_SLOT"
    }
    supplied = [item for item in admitted_source_evidence_units if isinstance(item, dict)]
    selected: list[dict[str, Any]] = []
    covered_slots: set[str] = set()
    fulltext_seen = False
    for raw in supplied:
        assertion_id = _text(raw.get("assertion_id") or raw.get("evidence_assertion_id"))
        span_id = _text(raw.get("source_span_id") or raw.get("source_unit_id"))
        assertion, span = assertions.get(assertion_id), spans.get(span_id)
        if not assertion or not span:
            # The result may never reference a prior snapshot or an unbound
            # extraction artifact.  Treat it as a malformed producer rather
            # than quietly dropping it from a seemingly successful result.
            raise ValueError("Gap-targeted result source unit is absent from the current graph snapshot")
        if _text(span.get("source_type")) == "fulltext":
            fulltext_seen = True
        if (
            _text(assertion.get("schema_version")) != "evidence_assertion_v4"
            or _text(assertion.get("textual_explicitness")) != "EXPLICIT"
            or _text(assertion.get("assertion_origin")) != "SOURCE_EXPLICIT"
            or _text(assertion.get("derivation_status")) not in {"", "NOT_DERIVED"}
        ):
            continue
        eligible_slots = {
            slot for slot in requested_slots
            if (assertion_id, slot) in direct_admissions
        }
        if not eligible_slots:
            continue
        selected_unit = dict(raw)
        selected_unit.update(
            {
                "assertion_id": assertion_id,
                "evidence_assertion_id": assertion_id,
                "source_span_id": span_id,
                "source_unit_id": _text(raw.get("source_unit_id") or span.get("source_unit_id") or span_id),
                "paper_id": _text(raw.get("paper_id") or span.get("paper_id") or assertion.get("paper_id")),
                "document_version_hash": _text(span.get("document_version_hash")),
                "admitted_slot_ids_v4": sorted(eligible_slots),
                "evidence_admission_status": "ADMITTED_DIRECT_SLOT",
                "assertion_origin": "SOURCE_EXPLICIT",
                "derivation_status": "NOT_DERIVED",
            }
        )
        selected.append(selected_unit)
        covered_slots.update(eligible_slots)

    complete = set(requested_slots).issubset(covered_slots)
    question_contract = (
        source.get("research_question_contract")
        if isinstance(source.get("research_question_contract"), dict)
        else {}
    )
    work_item = retrieval_work_item_v3 if isinstance(retrieval_work_item_v3, dict) else {}
    result = {
        "schema_version": "gap_targeted_retrieval_result_v3",
        "candidate_identity": candidate_identity,
        "gap_candidate_id": candidate_identity,
        "gap_candidate_fingerprint": _text(
            work_item.get("gap_candidate_fingerprint")
        ) or _gap_candidate_retrieval_fingerprint(source),
        "retrieval_plan_fingerprint": _fingerprint(plan),
        "gap_search_plan_fingerprint": _fingerprint(plan),
        "research_question_contract_id": _text(question_contract.get("contract_id")),
        "research_question_contract_revision": _text(
            question_contract.get("contract_revision") or question_contract.get("declaration_hash")
        ),
        "graph_snapshot_ref": graph_ref,
        "research_graph_snapshot_id": _text(graph_ref.get("snapshot_id")),
        "target_slot_ids": requested_slots,
        "covered_slot_ids": sorted(covered_slots),
        "satisfied_obligation_slot_ids": sorted(covered_slots),
        "remaining_obligation_slot_ids": sorted(set(requested_slots) - covered_slots),
        "retrieval_work_item_v3": dict(retrieval_work_item_v3 or {}),
        "retrieved_assertion_ids": sorted({_text(item.get("assertion_id")) for item in selected}),
        "retrieved_source_span_ids": sorted({_text(item.get("source_span_id")) for item in selected}),
        "retrieved_document_version_ids": sorted({
            _text(item.get("document_version_hash"))
            for item in selected
            if _text(item.get("document_version_hash"))
        }),
        "retrieved_source_evidence_units": selected,
        "evidence_admission_schema_version": "evidence_admission_v4",
        "result_status": "ADMITTED_EVIDENCE_AVAILABLE" if complete else "INCONCLUSIVE",
        "evidence_disposition": "DIRECT_SUPPORT" if complete else "INCONCLUSIVE",
        "fulltext_and_admission_status": (
            "DIRECT_SLOT_ADMITTED"
            if complete
            else "FULLTEXT_ACQUIRED_SLOT_NOT_ADMITTED"
            if fulltext_seen
            else "NO_ADMITTED_CURRENT_SNAPSHOT_EVIDENCE"
        ),
        "inconclusive_reason_codes": (
            []
            if complete
            else [
                "FULLTEXT_ACQUIRED_SLOT_NOT_ADMITTED"
                if fulltext_seen
                else "NO_ADMITTED_CURRENT_SNAPSHOT_EVIDENCE_FOR_TARGET_SLOT"
            ]
        ),
    }
    if complete:
        # Re-use the strict rebind validator as a construction invariant.  A
        # producer cannot emit a result which this module itself would later
        # reject at the rebind boundary.
        _v3_retrieved_units(source, result, graph)
    return result


def _v3_retrieved_units(
    candidate: dict[str, Any],
    retrieval_result: dict[str, Any],
    snapshot: dict[str, Any],
) -> list[dict[str, Any]]:
    """Validate retrieval text against exact assertion/span objects in V3 graph."""

    try:
        from ._research_graph import graph_snapshot_ref
    except ImportError:
        from _research_graph import graph_snapshot_ref
    if _text(snapshot.get("schema_version")) != "research_evidence_graph_v4":
        raise ValueError("Retrieval evidence rebind requires research_evidence_graph_v4")
    if retrieval_result.get("schema_version") != "gap_targeted_retrieval_result_v3":
        raise ValueError("Unsupported targeted retrieval result schema; legacy fallbacks are disabled")
    if _text(retrieval_result.get("candidate_identity")) != _text(candidate.get("candidate_identity")):
        raise ValueError("Targeted retrieval result is bound to a different candidate")
    plan = candidate.get("retrieval_plan") if isinstance(candidate.get("retrieval_plan"), dict) else {}
    if plan.get("schema_version") != "gap_search_plan_v3":
        raise ValueError("Retrieval rebind requires an active V3 targeted retrieval plan")
    if _text(retrieval_result.get("retrieval_plan_fingerprint")) != _fingerprint(plan):
        raise ValueError("Targeted retrieval result does not match the active retrieval plan")
    current_ref = graph_snapshot_ref(snapshot)
    result_ref = retrieval_result.get("graph_snapshot_ref")
    if not isinstance(result_ref, dict) or result_ref != current_ref:
        raise ValueError("Targeted retrieval result is not bound to the current graph snapshot")
    if _text(retrieval_result.get("research_graph_snapshot_id")) != _text(current_ref.get("snapshot_id")):
        raise ValueError("Targeted retrieval result current graph snapshot id mismatch")
    if _text(retrieval_result.get("result_status")) != "ADMITTED_EVIDENCE_AVAILABLE":
        raise ValueError("Only admitted V3 evidence can be rebound; inconclusive results require more retrieval or extraction")
    target_slots = {
        _text(item) for item in retrieval_result.get("target_slot_ids", []) if _text(item)
    }
    covered_slots = {
        _text(item) for item in retrieval_result.get("covered_slot_ids", []) if _text(item)
    }
    if not target_slots or not target_slots.issubset(covered_slots):
        raise ValueError("Targeted retrieval result does not cover every declared target slot")
    requested_assertion_ids = {
        _text(item) for item in retrieval_result.get("retrieved_assertion_ids", []) if _text(item)
    }
    raw_units = retrieval_result.get("retrieved_source_evidence_units")
    if not requested_assertion_ids or not isinstance(raw_units, list):
        raise ValueError("Targeted retrieval result requires assertion ids and source-bound evidence units")
    nodes = [item for item in snapshot.get("nodes", []) if isinstance(item, dict)]
    assertions = {
        _text(item.get("node_id")): item
        for item in nodes
        if item.get("node_type") == "EVIDENCE_ASSERTION" and _text(item.get("node_id"))
    }
    spans = {
        _text(item.get("node_id")): item
        for item in nodes
        if item.get("node_type") == "SOURCE_SPAN" and _text(item.get("node_id"))
    }
    direct_admissions = {
        (_text(item.get("assertion_id")), _text(item.get("slot_id")))
        for item in snapshot.get("evidence_admissions", [])
        if isinstance(item, dict)
        and _text(item.get("schema_version")) == "evidence_admission_v4"
        and _text(item.get("status")) == "ADMITTED_DIRECT_SLOT"
    }
    contract = candidate.get("research_question_contract") if isinstance(candidate.get("research_question_contract"), dict) else {}
    contract_id = _text(contract.get("contract_id"))
    units: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for raw in raw_units:
        if not isinstance(raw, dict):
            raise ValueError("Targeted retrieval source units must be objects")
        assertion_id = _text(raw.get("assertion_id") or raw.get("evidence_assertion_id"))
        span_id = _text(raw.get("source_span_id") or raw.get("source_unit_id"))
        assertion = assertions.get(assertion_id)
        span = spans.get(span_id)
        if not assertion or not span or assertion_id not in requested_assertion_ids:
            raise ValueError("Retrieved evidence is not bound to a declared V3 assertion/span pair")
        if (
            _text(assertion.get("schema_version")) != "evidence_assertion_v4"
            or _text(assertion.get("textual_explicitness")) != "EXPLICIT"
            or _text(assertion.get("assertion_origin")) != "SOURCE_EXPLICIT"
            or _text(assertion.get("derivation_status")) not in {"", "NOT_DERIVED"}
        ):
            raise ValueError("Retrieved evidence assertion is not source-explicit V3 evidence")
        if (
            _text(span.get("schema_version")) != "source_span_v6"
            or _text(span.get("source_type")) != "fulltext"
            or _text(span.get("span_kind")) in {"title", "abstract"}
            or _text(span.get("section_disposition")) != "INCLUDED"
            or _text(span.get("source_material_status")) != "SOURCE_BOUND_FULLTEXT"
            or _text(span.get("binding_status")) != "SOURCE_UNIT_VERIFIED"
            or not _text(span.get("source_locator"))
        ):
            raise ValueError("Retrieved direct evidence requires a current full-text V3 source span")
        raw_slots = {
            _text(slot) for slot in raw.get("admitted_slot_ids_v4", []) if _text(slot)
        }
        if not raw_slots or not raw_slots.issubset(target_slots):
            raise ValueError("Retrieved evidence unit lacks an explicit target-slot admission")
        if not all((assertion_id, slot) in direct_admissions for slot in raw_slots):
            raise ValueError("Retrieved evidence unit slot admission is absent from the current V3 graph")
        if contract_id and _text(assertion.get("research_question_contract_id")) != contract_id:
            raise ValueError("Retrieved assertion is outside the candidate research-question contract")
        if span_id not in {_text(item) for item in assertion.get("source_span_ids", [])}:
            raise ValueError("Retrieved span is not a provenance source of its assertion")
        version = _text(raw.get("document_version_hash"))
        if not version or version != _text(assertion.get("document_version_hash")) or version != _text(span.get("document_version_hash")):
            raise ValueError("Retrieved source unit document version does not match its V3 assertion/span")
        excerpt = _text(raw.get("excerpt"))
        excerpt_hash = _text(raw.get("excerpt_hash") or raw.get("quote_hash"))
        expected_hash = _text(span.get("excerpt_hash") or span.get("quote_hash"))
        if not excerpt or not excerpt_hash or (expected_hash and expected_hash != excerpt_hash):
            raise ValueError("Retrieved source unit requires its verified excerpt and matching excerpt hash")
        key = (assertion_id, span_id)
        if key in seen:
            continue
        seen.add(key)
        units.append(
            {
                "paper_id": _text(raw.get("paper_id") or span.get("paper_id") or assertion.get("paper_id")),
                "document_version_hash": version,
                "source_unit_id": _text(raw.get("source_unit_id") or span.get("source_unit_id") or span_id),
                "source_span_id": span_id,
                "excerpt_hash": excerpt_hash,
                "excerpt": excerpt,
                "binding_status": "SOURCE_UNIT_VERIFIED",
                "source_field": _text(raw.get("source_field") or span.get("source_field") or span.get("section")),
                "section": _text(raw.get("section") or span.get("section")),
                "source_locator": _text(raw.get("source_locator") or span.get("source_locator")),
                "source_type": _text(raw.get("source_type") or span.get("source_type")),
                "conditions": dict(raw.get("conditions") or {}),
                "assertion_id": assertion_id,
                "evidence_assertion_id": assertion_id,
                "research_question_contract_id": contract_id,
                "assertion_kinds": list(assertion.get("assertion_kinds") or []),
                "textual_explicitness": _text(assertion.get("textual_explicitness")) or "EXPLICIT",
                "assertion_origin": "SOURCE_EXPLICIT",
                "derivation_status": "NOT_DERIVED",
                "admitted_slot_ids_v4": sorted(raw_slots),
                "evidence_admission_status": "ADMITTED_DIRECT_SLOT",
            }
        )
    if { _text(item.get("assertion_id")) for item in units } != requested_assertion_ids:
        raise ValueError("Every retrieved assertion must carry one verified rebindable source span")
    return units


def rebind_candidate_with_retrieved_evidence(
    candidate: dict[str, Any],
    retrieval_result: dict[str, Any],
    snapshot: dict[str, Any],
) -> dict[str, Any]:
    """Bind V3 retrieval evidence, invalidate old audit, and require re-audit.

    Retrieval may add evidence but may never inherit the previous semantic
    verdict.  This is the only path from a retrieval result to a candidate
    that can later be qualified.
    """

    try:
        from ._research_graph import bind_candidate_to_graph_snapshot, graph_snapshot_ref
    except ImportError:
        from _research_graph import bind_candidate_to_graph_snapshot, graph_snapshot_ref
    assessment = assessment_of(candidate)
    if assessment.get("candidate_stage") != CandidateStage.RETRIEVAL_PLANNED.value:
        raise ValueError("Only a V3 retrieval-planned candidate can be rebound")
    units = _v3_retrieved_units(candidate, retrieval_result, snapshot)
    existing = [dict(item) for item in candidate.get("source_evidence_units", []) if isinstance(item, dict)]
    by_key = {
        (_text(item.get("assertion_id") or item.get("evidence_assertion_id")), _text(item.get("source_span_id") or item.get("source_unit_id"))): item
        for item in existing
    }
    for unit in units:
        by_key[(_text(unit.get("assertion_id")), _text(unit.get("source_span_id")))] = unit
    rebound = dict(candidate)
    rebound["source_evidence_units"] = list(by_key.values())
    rebound["source_lineage"] = list(by_key.values())
    rebound["source_assertion_ids"] = sorted({
        _text(item.get("assertion_id") or item.get("evidence_assertion_id"))
        for item in by_key.values() if _text(item.get("assertion_id") or item.get("evidence_assertion_id"))
    })
    rebound["evidence_bundle"] = {
        **dict(candidate.get("evidence_bundle") or {}),
        "schema_version": "source_bound_gap_evidence_bundle_v3",
        "assertion_ids": list(rebound["source_assertion_ids"]),
        "source_units": list(by_key.values()),
        "assertion_count": len(rebound["source_assertion_ids"]),
        "source_unit_count": len(by_key),
        "document_version_hashes": sorted({
            _text(item.get("document_version_hash")) for item in by_key.values() if _text(item.get("document_version_hash"))
        }),
    }
    # Retrieval may enrich typed fields only through a cited, newly rebound
    # assertion.  Free-form values without an assertion provenance stay out
    # of the candidate and cannot quietly satisfy a primary contract.
    enrichment = retrieval_result.get("type_payload_enrichment")
    if enrichment is not None:
        if not isinstance(enrichment, dict):
            raise ValueError("type_payload_enrichment must be a field-to-provenance mapping")
        contract = contract_for(assessment.get("gap_type"))
        allowed_fields = set(contract.primary_required_payload_fields)
        payload = dict(candidate.get("type_payload") or {})
        rebound_assertion_ids = {_text(item.get("assertion_id")) for item in units}
        for field_name, evidence in enrichment.items():
            if field_name not in allowed_fields or not isinstance(evidence, dict):
                raise ValueError("Retrieved payload enrichment contains an unsupported field or invalid provenance")
            assertion_ids = {
                _text(item) for item in evidence.get("assertion_ids", []) if _text(item)
            }
            if not assertion_ids or not assertion_ids.issubset(rebound_assertion_ids) or "value" not in evidence:
                raise ValueError("Retrieved payload enrichment requires value and newly rebound assertion ids")
            payload[str(field_name)] = evidence.get("value")
        rebound["type_payload"] = payload
    rebound = bind_candidate_to_graph_snapshot(rebound, snapshot)
    rebind = {
        "schema_version": "gap_retrieval_evidence_rebind_v3",
        "candidate_identity": _text(candidate.get("candidate_identity")),
        "retrieval_result_fingerprint": _fingerprint(retrieval_result),
        "retrieval_plan_fingerprint": _fingerprint(candidate.get("retrieval_plan") or {}),
        "graph_snapshot_ref": graph_snapshot_ref(snapshot),
        "retrieved_assertion_ids": sorted({_text(item.get("assertion_id")) for item in units}),
        "rebound_source_unit_ids": sorted({_text(item.get("source_unit_id")) for item in units}),
    }
    rebind["rebind_fingerprint"] = _fingerprint(rebind)
    updated = dict(assessment)
    updated.update(
        {
            "candidate_stage": CandidateStage.RAW_CANDIDATE.value,
            "semantic_verdict": SemanticVerdict.UNVERIFIED.value,
            "semantic_confidence": 0.0,
            "semantic_failure_codes": ["RETRIEVED_EVIDENCE_REBOUND_REAUDIT_REQUIRED"],
            "evidence_maturity": EvidenceMaturity.SOURCE_BOUND.value,
            "route": GapRoute.DIAGNOSTIC.value,
            "decision_reasons": ["RETRIEVED_EVIDENCE_REBOUND_REAUDIT_REQUIRED"],
            "audit_refs": [],
        }
    )
    for field in ("semantic_audit", "semantic_assessment", "retrieval_assessment", "primary_source_span_gate", "retrieval_plan"):
        rebound.pop(field, None)
    rebound["retrieval_rebind"] = rebind
    result = synchronize_candidate_surface(rebound, updated, increment_assessment_version=True)
    log_event(
        "SCIENCE",
        "gap_retrieval_evidence_rebound",
        project_id=_text(candidate.get("project_id")),
        candidate_identity=_text(candidate.get("candidate_identity")),
        gap_id=_text(candidate.get("gap_id")),
        retrieved_assertion_ids=rebind["retrieved_assertion_ids"],
        rebind_fingerprint=rebind["rebind_fingerprint"],
        re_audit_required=True,
    )
    return result


_GAP_RESOLUTION_PENDING_EXECUTION_STATUSES = frozenset({
    "PENDING",
    "COMPILED",
    "PROVIDER_RUNNING",
    "CANDIDATES_DISCOVERED",
    "PROVIDER_COVERAGE_COMPLETE",
    "RETRY_PENDING",
    "SEARCH_ERROR",
    "TIMEOUT",
    "RATE_LIMITED",
    "NETWORK_ERROR",
    "COMPILATION_REPAIR_REQUIRED",
    "FULLTEXT_PENDING",
    "FULLTEXT_UNAVAILABLE_FINAL",
    "PROPOSITION_PARTIAL",
    "COMPOSITION_PENDING",
    "LLM_EXTRACTION_PENDING",
    "ADMISSION_PENDING",
    "REBIND_PENDING",
    "RE_AUDIT_PENDING",
    "WORKFLOW_ERROR",
    "PENDING_SLOT_BINDING",
    "PENDING_GRAPH_SNAPSHOT",
})


def _gap_resolution_pending_application(
    candidate: dict[str, Any],
    work_item: dict[str, Any],
    execution: dict[str, Any],
    *,
    reason_code: str,
) -> dict[str, Any]:
    """Return a non-scientific pending state without touching the candidate."""

    status = _text(execution.get("status")).upper() or "PENDING"
    stage = _text(execution.get("stage")) or "PROVIDER_EXECUTION"
    return {
        "schema_version": "gap_resolution_application_v3",
        "status": "RETRIEVAL_PENDING",
        "scientific_conclusion_allowed": False,
        "candidate": dict(candidate),
        "retrieval_state": {
            "schema_version": "gap_resolution_retrieval_state_v3",
            "status": status,
            "stage": stage,
            "reason_code": reason_code,
            "candidate_identity": _text(candidate.get("candidate_identity")),
            "work_item_id": _text(work_item.get("work_item_id")),
            "target_slot_ids": list(work_item.get("target_slot_ids") or []),
            "missing_obligation_slot_ids": list(work_item.get("target_slot_ids") or []),
            "next_stage": stage,
            "provider_outcomes": [
                dict(item)
                for item in execution.get("provider_outcomes", [])
                if isinstance(item, dict)
            ],
            "diagnostic": dict(execution.get("diagnostic") or {}),
        },
    }


def apply_gap_resolution_retrieval_cycle_v3(
    project: dict[str, Any],
    candidate: dict[str, Any],
    retrieval_work_item_v3: dict[str, Any],
    execution: dict[str, Any],
    *,
    positive_auditor: Any | None = None,
    red_team_auditor: Any | None = None,
) -> dict[str, Any]:
    """Apply a completed GAP_RESOLUTION item through the closed V3 lifecycle.

    The work item is the ownership boundary between TanXi scheduling and a
    provider/importer.  Metadata discovery, provider faults, missing full
    text, and non-admitted assertions are represented as resumable work.  No
    such state is allowed to reach rebind, semantic re-audit, qualification,
    primary routing, or Socrates.
    """

    try:
        from ._research_question_contract import validate_retrieval_work_item_v3
    except ImportError:
        from _research_question_contract import validate_retrieval_work_item_v3

    source = candidate if isinstance(candidate, dict) else {}
    work_item = validate_retrieval_work_item_v3(retrieval_work_item_v3)
    if _text(work_item.get("work_item_kind")) != "GAP_RESOLUTION":
        raise ValueError("Gap-resolution application requires a GAP_RESOLUTION retrieval work item")
    candidate_identity = _text(source.get("candidate_identity"))
    if not candidate_identity or _text(work_item.get("gap_candidate_id")) != candidate_identity:
        raise ValueError("Gap-resolution work item belongs to a different candidate")
    if _text(work_item.get("gap_candidate_fingerprint")) != _gap_candidate_retrieval_fingerprint(source):
        raise ValueError("Gap-resolution work item candidate fingerprint is stale")
    plan = source.get("retrieval_plan") if isinstance(source.get("retrieval_plan"), dict) else {}
    if _text(plan.get("schema_version")) != "gap_search_plan_v3":
        raise ValueError("Gap-resolution application requires the active gap_search_plan_v3")
    if _text(work_item.get("plan_fingerprint")) != _fingerprint(plan):
        raise ValueError("Gap-resolution work item does not match the active gap search plan")
    if _text(work_item.get("gap_type")) != _text(plan.get("gap_type")):
        raise ValueError("Gap-resolution work item gap type does not match the active plan")

    payload = execution if isinstance(execution, dict) else {}
    if _text(payload.get("schema_version")) != "gap_resolution_execution_v3":
        raise ValueError("Gap-resolution application requires gap_resolution_execution_v3")
    embedded_work_item = payload.get("retrieval_work_item_v3")
    if embedded_work_item is not None:
        embedded = validate_retrieval_work_item_v3(embedded_work_item)
        binding_fields = (
            "work_item_id",
            "work_item_kind",
            "project_id",
            "sub_hypothesis_id",
            "research_question_contract_id",
            "research_question_contract_revision",
            "gap_candidate_id",
            "gap_candidate_fingerprint",
            "gap_type",
            "target_slot_ids",
            "plan_fingerprint",
            "graph_snapshot_id",
        )
        if any(embedded.get(field) != work_item.get(field) for field in binding_fields):
            raise ValueError("Gap-resolution execution carries a different retrieval work item")

    execution_status = _text(payload.get("status")).upper() or "PENDING"
    if execution_status in _GAP_RESOLUTION_PENDING_EXECUTION_STATUSES:
        return _gap_resolution_pending_application(
            source,
            work_item,
            payload,
            reason_code=(
                _text((payload.get("diagnostic") or {}).get("reason_code"))
                or "GAP_RESOLUTION_EVIDENCE_ACQUISITION_INCOMPLETE"
            ),
        )
    if execution_status != "ASSERTION_ADMISSION_COMPLETE":
        raise ValueError("Gap-resolution execution status is not a supported V3 lifecycle state")

    cycle = payload.get("retrieval_cycle")
    if not isinstance(cycle, dict):
        return _gap_resolution_pending_application(
            source,
            work_item,
            payload,
            reason_code="GAP_RESOLUTION_REBIND_CYCLE_REQUIRED",
        )
    retrieval_result = cycle.get("retrieval_result") if isinstance(cycle.get("retrieval_result"), dict) else {}
    if _text(retrieval_result.get("schema_version")) != "gap_targeted_retrieval_result_v3":
        raise ValueError("Gap-resolution execution requires gap_targeted_retrieval_result_v3")
    if _text(retrieval_result.get("result_status")) != "ADMITTED_EVIDENCE_AVAILABLE":
        return _gap_resolution_pending_application(
            source,
            work_item,
            payload,
            reason_code="GAP_RESOLUTION_NO_ADMITTED_EVIDENCE_TO_REBIND",
        )
    result_work_item = retrieval_result.get("retrieval_work_item_v3")
    if not isinstance(result_work_item, dict):
        raise ValueError("Gap-targeted result must retain its V3 retrieval work item")
    result_item = validate_retrieval_work_item_v3(result_work_item)
    result_binding_fields = (
        "work_item_id",
        "work_item_kind",
        "project_id",
        "sub_hypothesis_id",
        "research_question_contract_id",
        "research_question_contract_revision",
        "gap_candidate_id",
        "gap_candidate_fingerprint",
        "gap_type",
        "target_slot_ids",
        "plan_fingerprint",
        "graph_snapshot_id",
    )
    if any(result_item.get(field) != work_item.get(field) for field in result_binding_fields):
        raise ValueError("Gap-targeted result does not belong to this GAP_RESOLUTION work item")
    if sorted({_text(item) for item in retrieval_result.get("target_slot_ids", []) if _text(item)}) != sorted(
        {_text(item) for item in work_item.get("target_slot_ids", []) if _text(item)}
    ):
        raise ValueError("Gap-targeted result target slots differ from the work item")

    expected_result_bindings = {
        "candidate_identity": candidate_identity,
        "gap_candidate_id": candidate_identity,
        "gap_candidate_fingerprint": _text(work_item.get("gap_candidate_fingerprint")),
        "retrieval_plan_fingerprint": _text(work_item.get("plan_fingerprint")),
        "gap_search_plan_fingerprint": _text(work_item.get("plan_fingerprint")),
        "research_question_contract_id": _text(work_item.get("research_question_contract_id")),
        "research_question_contract_revision": _text(
            work_item.get("research_question_contract_revision")
        ),
        "research_graph_snapshot_id": _text(work_item.get("graph_snapshot_id")),
    }
    for field, expected in expected_result_bindings.items():
        if _text(retrieval_result.get(field)) != expected:
            raise ValueError(f"Gap-targeted result {field} does not match the GAP_RESOLUTION work item")
    result_snapshot_ref = retrieval_result.get("graph_snapshot_ref")
    if (
        not isinstance(result_snapshot_ref, dict)
        or _text(result_snapshot_ref.get("snapshot_id"))
        != _text(work_item.get("graph_snapshot_id"))
    ):
        raise ValueError("Gap-targeted result graph snapshot reference does not match the GAP_RESOLUTION work item")

    target_slot_ids = {
        _text(item) for item in work_item.get("target_slot_ids", []) if _text(item)
    }
    covered_slot_ids = {
        _text(item) for item in retrieval_result.get("covered_slot_ids", []) if _text(item)
    }
    satisfied_slot_ids = {
        _text(item)
        for item in retrieval_result.get("satisfied_obligation_slot_ids", [])
        if _text(item)
    }
    remaining_slot_ids = {
        _text(item)
        for item in retrieval_result.get("remaining_obligation_slot_ids", [])
        if _text(item)
    }
    if (
        covered_slot_ids != target_slot_ids
        or satisfied_slot_ids != covered_slot_ids
        or remaining_slot_ids != target_slot_ids - satisfied_slot_ids
    ):
        raise ValueError("Gap-targeted result obligation slots are inconsistent with the GAP_RESOLUTION work item")

    raw_units = retrieval_result.get("retrieved_source_evidence_units")
    if not isinstance(raw_units, list) or not raw_units or any(not isinstance(item, dict) for item in raw_units):
        raise ValueError("Gap-targeted result requires non-empty source-bound admitted evidence units")
    unit_assertion_ids = {
        _text(item.get("assertion_id") or item.get("evidence_assertion_id"))
        for item in raw_units
        if _text(item.get("assertion_id") or item.get("evidence_assertion_id"))
    }
    unit_span_ids = {
        _text(item.get("source_span_id") or item.get("source_unit_id"))
        for item in raw_units
        if _text(item.get("source_span_id") or item.get("source_unit_id"))
    }
    unit_document_version_ids = {
        _text(item.get("document_version_hash"))
        for item in raw_units
        if _text(item.get("document_version_hash"))
    }
    unit_admitted_slot_ids = {
        _text(slot)
        for item in raw_units
        for slot in item.get("admitted_slot_ids_v4", [])
        if _text(slot)
    }
    result_assertion_ids = {
        _text(item) for item in retrieval_result.get("retrieved_assertion_ids", []) if _text(item)
    }
    result_span_ids = {
        _text(item) for item in retrieval_result.get("retrieved_source_span_ids", []) if _text(item)
    }
    result_document_version_ids = {
        _text(item)
        for item in retrieval_result.get("retrieved_document_version_ids", [])
        if _text(item)
    }
    if (
        not unit_assertion_ids
        or unit_assertion_ids != result_assertion_ids
        or unit_span_ids != result_span_ids
        or unit_document_version_ids != result_document_version_ids
        or unit_admitted_slot_ids != satisfied_slot_ids
    ):
        raise ValueError("Gap-targeted result evidence identifiers are inconsistent with its admitted source units")

    cycle_result = run_targeted_retrieval_cycle(
        project,
        source,
        cycle,
        positive_auditor=positive_auditor,
        red_team_auditor=red_team_auditor,
    )
    updated_candidate = cycle_result.get("candidate") if isinstance(cycle_result.get("candidate"), dict) else {}
    if not updated_candidate:
        raise ValueError("Gap-resolution cycle did not return an updated candidate")
    updated_assessment = assessment_of(updated_candidate)
    direct_resolution = (
        _text(updated_assessment.get("route")) == GapRoute.REJECT.value
        and "DIRECT_RESOLUTION_FOUND" in {
            _text(item) for item in updated_assessment.get("decision_reasons", [])
        }
    )
    completed = (
        direct_resolution
        or _text(updated_assessment.get("candidate_stage")) == CandidateStage.QUALIFIED.value
    )
    status = "DIRECTLY_RESOLVED" if direct_resolution else "QUALIFICATION_COMPLETED" if completed else "RETRIEVAL_PENDING"
    return {
        "schema_version": "gap_resolution_application_v3",
        "status": status,
        "scientific_conclusion_allowed": completed,
        "candidate": updated_candidate,
        "cycle_result": cycle_result,
        "retrieval_state": {
            "schema_version": "gap_resolution_retrieval_state_v3",
            "status": status,
            "stage": "QUALIFICATION" if completed else "RE_AUDIT",
            "reason_code": (
                "DIRECT_RESOLUTION_FOUND"
                if direct_resolution
                else "QUALIFICATION_COMPLETED"
                if completed
                else "REBOUND_AND_REAUDITED_RETRIEVAL_ASSESSMENT_REQUIRED"
            ),
            "candidate_identity": candidate_identity,
            "work_item_id": _text(work_item.get("work_item_id")),
            "target_slot_ids": list(work_item.get("target_slot_ids") or []),
            "missing_obligation_slot_ids": [] if completed else list(work_item.get("target_slot_ids") or []),
            "next_stage": "COMPLETE" if completed else "RETRIEVAL_ASSESSMENT",
        },
    }


def run_targeted_retrieval_cycle(
    project: dict[str, Any],
    candidate: dict[str, Any],
    retrieval_cycle_result: dict[str, Any],
    *,
    positive_auditor: Any | None = None,
    red_team_auditor: Any | None = None,
) -> dict[str, Any]:
    """Run exactly one V3 retrieval → rebind → re-audit → qualify cycle.

    The external retriever owns document discovery/import and supplies a
    current graph snapshot.  This function owns the scientific state
    transition and rejects an incomplete cycle instead of retaining a prior
    semantic verdict as a fallback.
    """

    cycle = retrieval_cycle_result if isinstance(retrieval_cycle_result, dict) else {}
    if cycle.get("schema_version") != "gap_targeted_retrieval_cycle_v3":
        raise ValueError("Targeted retrieval cycle requires gap_targeted_retrieval_cycle_v3")
    if int(cycle.get("cycle_index") or 0) != 1:
        raise ValueError("Only one bounded targeted retrieval cycle may be processed per invocation")
    retrieval_result = cycle.get("retrieval_result")
    snapshot = cycle.get("graph_snapshot")
    retrieval_assessment = cycle.get("retrieval_assessment")
    retrieval_assessment_draft = cycle.get("retrieval_assessment_draft")
    if not isinstance(retrieval_result, dict) or not isinstance(snapshot, dict):
        raise ValueError("Targeted retrieval cycle requires a V3 retrieval result and current graph snapshot")
    rebound = rebind_candidate_with_retrieved_evidence(candidate, retrieval_result, snapshot)
    try:
        from ._gap_semantic_audit import audit_gap_candidate_semantics
    except ImportError:
        from _gap_semantic_audit import audit_gap_candidate_semantics
    reaudited = audit_gap_candidate_semantics(
        project,
        rebound,
        positive_auditor=positive_auditor,
        red_team_auditor=red_team_auditor,
    )
    replanned = plan_targeted_retrieval(project, reaudited)
    if assessment_of(replanned).get("candidate_stage") != CandidateStage.RETRIEVAL_PLANNED.value:
        return {
            "schema_version": "gap_targeted_retrieval_cycle_result_v3",
            "candidate": replanned,
            "status": "REBOUND_REAUDIT_DID_NOT_REOPEN_TARGETED_RETRIEVAL",
            "cycle_index": 1,
        }
    if retrieval_assessment_draft is not None:
        if not isinstance(retrieval_assessment_draft, dict) or retrieval_assessment_draft.get("schema_version") != "gap_retrieval_assessment_draft_v3":
            raise ValueError("Targeted retrieval cycle assessment draft requires gap_retrieval_assessment_draft_v3")
        # The executor cannot know the rebind fingerprint or audit version
        # until the engine has bound its returned source text.  Seal those
        # two lifecycle-owned fields here, from the immediately preceding
        # V3 transitions, rather than asking the executor to guess them.
        retrieval_assessment = {
            **{
                key: value
                for key, value in retrieval_assessment_draft.items()
                if key != "schema_version"
            },
            "schema_version": "gap_retrieval_assessment_v3",
            "rebind_fingerprint": _text(
                (replanned.get("retrieval_rebind") or {}).get("rebind_fingerprint")
                if isinstance(replanned.get("retrieval_rebind"), dict)
                else ""
            ),
            "semantic_audit_assessment_version": int(replanned.get("assessment_version") or 0),
        }
    if not isinstance(retrieval_assessment, dict):
        return {
            "schema_version": "gap_targeted_retrieval_cycle_result_v3",
            "candidate": replanned,
            "status": "REBOUND_AND_REAUDITED_RETRIEVAL_ASSESSMENT_REQUIRED",
            "cycle_index": 1,
        }
    qualified = qualify_gap_candidate(
        project,
        replanned,
        replanned.get("semantic_audit") if isinstance(replanned.get("semantic_audit"), dict) else {},
        retrieval_assessment,
    )
    return {
        "schema_version": "gap_targeted_retrieval_cycle_result_v3",
        "candidate": qualified,
        "status": "QUALIFICATION_COMPLETED",
        "cycle_index": 1,
    }


def qualify_gap_candidate(
    project: dict[str, Any],
    candidate: dict[str, Any],
    semantic_audit: dict[str, Any],
    retrieval_assessment: dict[str, Any],
) -> dict[str, Any]:
    """Apply the contract after a bounded retrieval run.

    ``retrieval_assessment`` is intentionally an explicit artefact supplied by
    a retrieval agent.  This function refuses unknown schemas rather than
    interpreting old project fields as a hidden fallback.
    """
    if retrieval_assessment.get("schema_version") != "gap_retrieval_assessment_v3":
        raise ValueError("Unsupported retrieval assessment schema; legacy fallbacks are disabled")
    assessment = assessment_of(candidate)
    plan = candidate.get("retrieval_plan") if isinstance(candidate.get("retrieval_plan"), dict) else {}
    if assessment.get("candidate_stage") != CandidateStage.RETRIEVAL_PLANNED.value or plan.get("schema_version") != "gap_search_plan_v3":
        raise ValueError("A candidate must pass semantic audit and receive a V3 retrieval plan before qualification")
    required_retrieval_fields = {
        "novelty_verdict",
        "direct_resolution_found",
        "design_ready",
        "remaining_missing_axes",
        "supporting_source_unit_ids",
        "retrieved_source_evidence_units",
        "rebind_fingerprint",
        "semantic_audit_assessment_version",
    }
    missing_retrieval_fields = sorted(field for field in required_retrieval_fields if field not in retrieval_assessment)
    if missing_retrieval_fields:
        raise ValueError("Retrieval assessment is incomplete: " + ", ".join(missing_retrieval_fields))
    rebind = candidate.get("retrieval_rebind") if isinstance(candidate.get("retrieval_rebind"), dict) else {}
    if rebind.get("schema_version") != "gap_retrieval_evidence_rebind_v3":
        raise ValueError("Qualification requires V3 retrieval evidence rebind followed by re-audit")
    if _text(retrieval_assessment.get("rebind_fingerprint")) != _text(rebind.get("rebind_fingerprint")):
        raise ValueError("Retrieval assessment does not cite the candidate's current V3 evidence rebind")
    if int(retrieval_assessment.get("semantic_audit_assessment_version") or -1) != int(candidate.get("assessment_version") or 0):
        raise ValueError("Qualification requires a semantic audit performed after the current retrieval rebind")
    bound_source_unit_ids = {
        _text(item.get("source_unit_id"))
        for item in candidate.get("source_evidence_units", [])
        if isinstance(item, dict) and _text(item.get("source_unit_id"))
    }
    cited_source_unit_ids = {
        _text(item)
        for item in retrieval_assessment.get("supporting_source_unit_ids", [])
        if _text(item)
    }
    if not cited_source_unit_ids.issubset(bound_source_unit_ids):
        raise ValueError("Retrieval assessment cites source units that were not bound and re-audited on this candidate")
    contract = contract_for(assessment["gap_type"])
    semantic = semantic_audit if isinstance(semantic_audit, dict) else {}
    if not semantic:
        raise ValueError("Qualification requires the current source-span semantic audit artifact")
    if semantic.get("schema_version") != "gap_semantic_audit_result_v3":
        raise ValueError("Qualification requires a current V3 semantic audit result")
    if _text(semantic.get("candidate_identity")) != _text(candidate.get("candidate_identity")):
        raise ValueError("Semantic audit is bound to a different candidate")
    if int(semantic.get("assessment_version") or -1) != int(candidate.get("assessment_version") or 0):
        raise ValueError("Semantic audit is stale relative to the candidate's retrieval rebind")
    checks = semantic.get("checks") if isinstance(semantic.get("checks"), dict) else {}
    required_checks_pass = all(checks.get(key) is True for key in contract.required_semantic_checks)
    retrieval_verdict = _text(retrieval_assessment.get("novelty_verdict")).upper()
    direct_resolution = retrieval_verdict == "ALREADY_ADDRESSED" or retrieval_assessment.get("direct_resolution_found") is True
    design_ready = retrieval_assessment.get("design_ready") is True
    primary_payload_missing = missing_payload_fields(
        candidate,
        lifecycle_phase=GapLifecyclePhase.PRIMARY_QUALIFICATION,
    )
    eligible_scope = assessment.get("scope_status") == ScopeStatus.CORE.value
    primary_source_span_gate = _primary_source_span_gate(
        project,
        candidate,
        semantic,
        retrieval_assessment,
    )

    updated = dict(candidate)
    updated_assessment = dict(assessment)
    if direct_resolution:
        route = GapRoute.REJECT.value
        maturity = assessment.get("evidence_maturity", EvidenceMaturity.SOURCE_BOUND.value)
        reason = "DIRECT_RESOLUTION_FOUND"
    elif (
        assessment.get("semantic_verdict") == SemanticVerdict.ENTAILED.value
        and required_checks_pass
        and eligible_scope
        and design_ready
        and not primary_payload_missing
        and primary_source_span_gate["status"] == "PASSED"
        and retrieval_verdict in {"OPEN_WITHIN_SCOPE", "INCONCLUSIVE"}
    ):
        route = GapRoute.PRIMARY_CANDIDATE.value
        maturity = EvidenceMaturity.DESIGN_READY.value
        reason = "TYPE_CONTRACT_AND_RETRIEVAL_GATE_PASSED"
    elif (
        assessment.get("semantic_verdict") == SemanticVerdict.ENTAILED.value
        and required_checks_pass
        and assessment.get("scope_status") in {ScopeStatus.CORE.value, ScopeStatus.COMPONENT_BRIDGE.value}
        and primary_payload_missing
    ):
        route = GapRoute.TARGETED_RETRIEVAL.value
        maturity = EvidenceMaturity.SEMANTICALLY_VALIDATED.value
        reason = "PRIMARY_PAYLOAD_ENRICHMENT_REQUIRED"
    elif (
        assessment.get("semantic_verdict") == SemanticVerdict.ENTAILED.value
        and required_checks_pass
        and assessment.get("scope_status") in {ScopeStatus.CORE.value, ScopeStatus.COMPONENT_BRIDGE.value}
        and primary_source_span_gate["status"] != "PASSED"
    ):
        route = GapRoute.TARGETED_RETRIEVAL.value
        maturity = EvidenceMaturity.SEMANTICALLY_VALIDATED.value
        reason = "PRIMARY_SOURCE_SPAN_GATE_BLOCKED"
    elif (
        assessment.get("semantic_verdict") == SemanticVerdict.ENTAILED.value
        and required_checks_pass
        and assessment.get("scope_status") in {ScopeStatus.CORE.value, ScopeStatus.COMPONENT_BRIDGE.value}
    ):
        route = GapRoute.TARGETED_RETRIEVAL.value
        maturity = EvidenceMaturity.SEMANTICALLY_VALIDATED.value
        reason = "DESIGN_OR_NOVELTY_REMAINS_INCOMPLETE"
    else:
        route = GapRoute.SECONDARY_RESEARCH.value
        maturity = assessment.get("evidence_maturity", EvidenceMaturity.SOURCE_BOUND.value)
        reason = "TYPE_CONTRACT_NOT_SATISFIED"

    updated_assessment.update(
        {
            "candidate_stage": CandidateStage.QUALIFIED.value,
            "novelty_verdict": retrieval_verdict or "INCONCLUSIVE",
            "evidence_maturity": maturity,
            "route": route,
            "decision_reasons": [reason],
            "missing_evidence_axes": sorted({
                *[str(item) for item in retrieval_assessment.get("remaining_missing_axes", []) if str(item)],
                *primary_payload_missing,
            }),
        }
    )
    updated["primary_source_span_gate"] = primary_source_span_gate
    result = synchronize_candidate_surface(
        updated,
        updated_assessment,
        retrieval_assessment=retrieval_assessment,
        increment_retrieval_version=True,
    )
    log_event(
        "SCIENCE",
        "gap_candidate_qualified",
        project_id=_text(candidate.get("project_id")),
        candidate_identity=_text(candidate.get("candidate_identity")),
        gap_id=_text(candidate.get("gap_id")),
        route=route,
        primary_source_span_gate=primary_source_span_gate["status"],
        reason=reason,
    )
    return result
