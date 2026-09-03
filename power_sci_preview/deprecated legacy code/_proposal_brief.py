"""Build frozen, source-bound proposal briefs from qualified V2 packages."""

from __future__ import annotations

from hashlib import sha256
import json
import time
from typing import Any

try:
    from ._proposal_contracts import authoring_contract_payload
    from ._research_packages import research_package_gate
except ImportError:
    from _proposal_contracts import authoring_contract_payload
    from _research_packages import research_package_gate


PROPOSAL_BRIEF_SCHEMA_VERSION = "proposal_brief_v2"


def _text(value: Any) -> str:
    return " ".join(str(value or "").split())


def _digest(value: Any) -> str:
    return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")).hexdigest()


def _current_type_review(project: dict[str, Any], package: dict[str, Any]) -> dict[str, Any]:
    reviews = project.get("socrates_type_reviews") if isinstance(project.get("socrates_type_reviews"), dict) else {}
    review = reviews.get(str(package.get("gap_id") or ""))
    if not isinstance(review, dict):
        raise ValueError("A ProposalBriefV2 requires a persisted type-specific Socrates review")
    if str(review.get("research_package_id") or "") != str(package.get("research_package_id") or ""):
        raise ValueError("Socrates review belongs to a different research package")
    if int(review.get("package_version") or 0) != int(package.get("package_version") or 0):
        raise ValueError("Socrates review is stale for the package version")
    if review.get("review_ready") is not True:
        raise ValueError("Socrates type review is not ready for proposal construction")
    return dict(review)


def _evidence_bundle(package: dict[str, Any], project: dict[str, Any]) -> list[dict[str, Any]]:
    records = {
        str(item.get("paper_id") or item.get("id") or ""): item
        for item in project.get("papergraph", []) if isinstance(item, dict)
    }
    bundle: list[dict[str, Any]] = []
    for item in package.get("evidence_bundle", []):
        if not isinstance(item, dict):
            continue
        entry = dict(item)
        source = records.get(str(entry.get("paper_id") or ""), {})
        entry["citation"] = {
            "paper_id": str(entry.get("paper_id") or ""),
            "title": _text(source.get("title")),
            "doi": _text(source.get("doi")),
            "year": source.get("year"),
        }
        entry["claim_role"] = entry.get("evidence_role") or "SOURCE_BOUND_GAP_SUPPORT"
        entry["quote_or_verified_excerpt"] = _text(entry.get("verified_excerpt"))
        bundle.append(entry)
    return bundle


def _require_package_evidence_bindings(package: dict[str, Any]) -> None:
    """Reject generic paper-only citations at the V2 proposal boundary."""
    bundle = [item for item in package.get("evidence_bundle", []) if isinstance(item, dict)]
    if not bundle:
        raise ValueError("Proposal V2 requires a non-empty source-bound evidence bundle")
    missing = [
        item for item in bundle
        if not _text(item.get("assertion_id"))
        or not _text(item.get("source_span_id"))
        or not _text(item.get("document_version_hash"))
        or not _text(item.get("evidence_link_id"))
        or not _text(item.get("verified_excerpt"))
    ]
    if missing:
        raise ValueError("Proposal V2 requires assertion, source-span, and document-version references for every evidence bundle item")


def _validate_package_bundle_against_graph(project: dict[str, Any], package: dict[str, Any]) -> None:
    """Make the brief boundary a real graph join, not a reference-shaped check."""
    graph_ref = package.get("graph_snapshot_ref") if isinstance(package.get("graph_snapshot_ref"), dict) else {}
    try:
        from ._project import science_state_manager
    except ImportError:
        from _project import science_state_manager
    snapshot = science_state_manager().get_research_evidence_graph(
        _text(project.get("project_id")),
        graph_ref,
    ) or {}
    if not isinstance(snapshot, dict) or not snapshot:
        raise ValueError("Proposal V2 requires the package's exact Research Evidence Graph V3 snapshot")
    quality_audit = snapshot.get("quality_audit") if isinstance(snapshot.get("quality_audit"), dict) else {}
    if quality_audit.get("passes") is not True:
        raise ValueError("Proposal V2 requires a Research Evidence Graph V3 snapshot that passed its quality audit")
    nodes = [item for item in snapshot.get("nodes", []) if isinstance(item, dict)]
    assertions = {
        str(item.get("node_id") or "")
        for item in nodes
        if item.get("node_type") == "EVIDENCE_ASSERTION"
    }
    spans = {
        str(item.get("node_id") or "")
        for item in nodes
        if item.get("node_type") == "SOURCE_SPAN"
    }
    links = {
        str(item.get("node_id") or ""): item
        for item in nodes
        if item.get("node_type") == "EVIDENCE_LINK"
    }
    assertion_spans = {
        str(item.get("node_id") or ""): {
            "source_span_ids": {str(value) for value in item.get("source_span_ids", []) if str(value)},
            "document_version_hash": _text(item.get("document_version_hash")),
        }
        for item in nodes
        if item.get("node_type") == "EVIDENCE_ASSERTION"
    }
    invalid = [
        item
        for item in package.get("evidence_bundle", [])
        if isinstance(item, dict)
        and (
            _text(item.get("assertion_id")) not in assertions
            or _text(item.get("source_span_id") or item.get("source_unit_id")) not in spans
            or _text(item.get("evidence_link_id")) not in links
            or _text(item.get("source_span_id") or item.get("source_unit_id")) not in assertion_spans.get(_text(item.get("assertion_id")), {}).get("source_span_ids", set())
            or _text(item.get("document_version_hash")) != assertion_spans.get(_text(item.get("assertion_id")), {}).get("document_version_hash")
            or _text(links.get(_text(item.get("evidence_link_id")), {}).get("assertion_id")) != _text(item.get("assertion_id"))
            or (
                _text(links.get(_text(item.get("evidence_link_id")), {}).get("document_version_hash"))
                and _text(links.get(_text(item.get("evidence_link_id")), {}).get("document_version_hash")) != _text(item.get("document_version_hash"))
            )
        )
    ]
    if invalid:
        raise ValueError("Proposal V2 evidence bundle does not resolve to the package's frozen V3 graph nodes")


def build_proposal_brief(project: dict[str, Any], package: dict[str, Any]) -> dict[str, Any]:
    """Create a type-directed brief; no LLM or legacy hypothesis fields enter."""
    if str(package.get("schema_version") or "") != "research_package_v2":
        raise ValueError("Proposal V2 accepts research_package_v2 only")
    gate = research_package_gate(package)
    if gate.get("passes") is not True:
        raise ValueError("Proposal V2 requires a research package that passes its current gate")
    if str(package.get("lifecycle_status") or "CURRENT") != "CURRENT":
        raise ValueError("Proposal V2 refuses a stale research package")
    graph_ref = package.get("graph_snapshot_ref") if isinstance(package.get("graph_snapshot_ref"), dict) else {}
    if not graph_ref.get("graph_id") or not graph_ref.get("input_fingerprint"):
        raise ValueError("Proposal V2 requires a versioned Research Evidence Graph reference")
    _require_package_evidence_bindings(package)
    _validate_package_bundle_against_graph(project, package)
    review = _current_type_review(project, package)
    authoring_contract = authoring_contract_payload(package)
    identity = {
        "project_id": package.get("project_id"),
        "research_package_id": package.get("research_package_id"),
        "package_version": package.get("package_version"),
        "graph_snapshot_ref": graph_ref,
    }
    brief_id = "pb_" + _digest(identity)[:20]
    payload = dict(package.get("type_payload") or {})
    return {
        "schema_version": PROPOSAL_BRIEF_SCHEMA_VERSION,
        "proposal_brief_id": brief_id,
        "brief_version": 1,
        "project_id": _text(package.get("project_id")),
        "research_package_ref": {
            "research_package_id": _text(package.get("research_package_id")),
            "package_version": int(package.get("package_version") or 0),
        },
        "graph_snapshot_ref": dict(graph_ref),
        "proposal_kind": authoring_contract["proposal_kind"],
        "gap_statement": {
            "gap_id": _text(package.get("gap_id")),
            "gap_type": _text(package.get("gap_type")),
            "gap_subtype": _text(package.get("gap_subtype")),
            "allowed_conclusion_strength": _text((package.get("execution_requirements") or {}).get("claim_strength")),
            "decision_reasons": list((package.get("qualification") or {}).get("decision_reasons") or []),
        },
        "research_question": dict(package.get("research_question") or {}),
        "scope_contract": dict((package.get("research_question") or {}).get("declared_scope") or {}),
        "authoring_contract": authoring_contract,
        "evidence_bundle": _evidence_bundle(package, project),
        "confirmed_knowledge": [
            {
                "statement": "The package has source-bound evidence sufficient to motivate the declared, scoped research question.",
                "evidence_refs": [str(item.get("assertion_id") or item.get("source_span_id") or "") for item in package.get("evidence_bundle", []) if isinstance(item, dict)],
            }
        ],
        "unresolved_knowledge": {
            "gap_type": _text(package.get("gap_type")),
            "type_payload": payload,
            "remaining_missing_axes": list((package.get("execution_requirements") or {}).get("remaining_missing_axes") or []),
        },
        "proposed_aims": [],
        "type_specific_design": payload,
        "success_criteria": list(authoring_contract["success_criteria"]),
        "falsification_or_discrimination": dict((package.get("execution_requirements") or {}).get("falsification_or_discrimination") or {}),
        "risks_and_limitations": [
            "The proposal does not convert its motivating gap or planned observations into an established scientific conclusion.",
            "All claims are limited to the declared research-question scope and current graph snapshot.",
        ],
        "prohibited_claim_patterns": list(authoring_contract["prohibited_claim_patterns"]),
        "socrates_review_ref": {
            "research_package_id": _text(review.get("research_package_id")),
            "package_version": int(review.get("package_version") or 0),
            "review_mode": _text(review.get("review_mode")),
        },
        "lifecycle_status": "CURRENT",
        "created_at": time.time(),
    }


def build_and_persist_proposal_brief(project_id: str, research_package_id: str) -> dict[str, Any]:
    try:
        from ._project import load_project, save_project
    except ImportError:
        from _project import load_project, save_project
    project = load_project(project_id)
    try:
        from ._research_workflow import (
            PROPOSAL_BRIEF_STAGE,
            PROPOSAL_WRITER_STAGE,
            record_workflow_execution,
            record_workflow_status,
            workflow_tool_gate,
        )
    except ImportError:
        from _research_workflow import (
            PROPOSAL_BRIEF_STAGE,
            PROPOSAL_WRITER_STAGE,
            record_workflow_execution,
            record_workflow_status,
            workflow_tool_gate,
        )
    gate = workflow_tool_gate(project, PROPOSAL_BRIEF_STAGE, {"research_package_id": research_package_id})
    if not gate.get("allowed"):
        return dict(gate.get("result") or {})
    package = next(
        (
            item for item in project.get("research_packages", [])
            if isinstance(item, dict) and str(item.get("research_package_id") or "") == str(research_package_id)
        ),
        None,
    )
    if not isinstance(package, dict):
        raise ValueError("No current research_package_v2 exists for the supplied research_package_id")
    brief = build_proposal_brief(project, package)
    briefs = [item for item in project.get("proposal_briefs", []) if isinstance(item, dict) and item.get("proposal_brief_id") != brief["proposal_brief_id"]]
    briefs.append(brief)
    project["proposal_briefs"] = briefs
    workflow_state = record_workflow_status(
        project,
        stage=PROPOSAL_BRIEF_STAGE,
        status="PROPOSAL_BRIEF_READY",
        terminal=False,
        allowed_next_stages=[PROPOSAL_WRITER_STAGE],
        blocked_stages=[],
        reason_code="TYPE_SPECIFIC_RESEARCH_PACKAGE_FROZEN_AS_PROPOSAL_BRIEF",
        artifact_ids=[brief["proposal_brief_id"]],
        remediation_plan={},
    )
    brief.update(workflow_state)
    try:
        from ._research_graph import persist_research_task_graph
    except ImportError:
        from _research_graph import persist_research_task_graph
    persist_research_task_graph(project)
    record_workflow_execution(project, PROPOSAL_BRIEF_STAGE, {"research_package_id": research_package_id}, brief, execution_key=str(gate.get("execution_key") or ""))
    project["updatedAt"] = time.time()
    save_project(project)
    return brief
