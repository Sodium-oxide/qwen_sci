"""Audit Proposal V2 provenance, type-contract completeness and claim scope."""

from __future__ import annotations

import time
from typing import Any


PROPOSAL_AUDIT_SCHEMA_VERSION = "proposal_audit_v2"


def _text(value: Any) -> str:
    return " ".join(str(value or "").split())


def _graph_snapshot(project: dict[str, Any], graph_ref: dict[str, Any]) -> dict[str, Any]:
    """Resolve exactly the graph version named by an artefact reference."""
    try:
        from ._project import science_state_manager
    except ImportError:
        from _project import science_state_manager
    try:
        return science_state_manager().get_research_evidence_graph(
            _text(project.get("project_id")),
            graph_ref,
        ) or {}
    except (FileNotFoundError, RuntimeError, ValueError):
        return {}


def _validate_evidence_bundle_against_graph(
    proposal: dict[str, Any],
    graph_snapshot: dict[str, Any],
) -> list[dict[str, Any]]:
    """Ensure the frozen proposal bundle still names real V3 ledger nodes."""
    if not graph_snapshot:
        return [{"code": "PROPOSAL_GRAPH_SNAPSHOT_NOT_PERSISTED"}]
    quality_audit = graph_snapshot.get("quality_audit") if isinstance(graph_snapshot.get("quality_audit"), dict) else {}
    if quality_audit.get("passes") is not True:
        return [{"code": "PROPOSAL_GRAPH_QUALITY_AUDIT_FAILED", "errors": list(quality_audit.get("errors") or [])}]
    nodes = [item for item in graph_snapshot.get("nodes", []) if isinstance(item, dict)]
    assertion_ids = {
        str(item.get("node_id") or "")
        for item in nodes
        if item.get("node_type") == "EVIDENCE_ASSERTION"
    }
    span_ids = {
        str(item.get("node_id") or "")
        for item in nodes
        if item.get("node_type") == "SOURCE_SPAN"
    }
    link_ids = {
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
    errors: list[dict[str, Any]] = []
    for index, item in enumerate(proposal.get("evidence_basis", [])):
        if not isinstance(item, dict):
            errors.append({"code": "PROPOSAL_EVIDENCE_BUNDLE_ITEM_INVALID", "index": index})
            continue
        assertion_id = _text(item.get("assertion_id"))
        source_span_id = _text(item.get("source_span_id") or item.get("source_unit_id"))
        evidence_link_id = _text(item.get("evidence_link_id"))
        verified_excerpt = _text(item.get("verified_excerpt") or item.get("quote_or_verified_excerpt"))
        missing = [
            name
            for name, value, known in (
                ("assertion_id", assertion_id, assertion_ids),
                ("source_span_id", source_span_id, span_ids),
                ("evidence_link_id", evidence_link_id, set(link_ids)),
            )
            if not value or value not in known
        ]
        if missing:
            errors.append(
                {
                    "code": "PROPOSAL_EVIDENCE_BUNDLE_NOT_BOUND_TO_GRAPH",
                    "index": index,
                    "missing_or_unknown": missing,
                }
            )
            continue
        if not verified_excerpt:
            errors.append({"code": "PROPOSAL_EVIDENCE_BUNDLE_WITHOUT_VERIFIED_EXCERPT", "index": index})
        if source_span_id not in assertion_spans.get(assertion_id, {}).get("source_span_ids", set()):
            errors.append({"code": "PROPOSAL_EVIDENCE_SPAN_DOES_NOT_BELONG_TO_ASSERTION", "index": index})
        if _text(item.get("document_version_hash")) != assertion_spans.get(assertion_id, {}).get("document_version_hash"):
            errors.append({"code": "PROPOSAL_EVIDENCE_DOCUMENT_VERSION_DOES_NOT_MATCH_ASSERTION", "index": index})
        if _text(link_ids.get(evidence_link_id, {}).get("assertion_id")) != assertion_id:
            errors.append({"code": "PROPOSAL_EVIDENCE_LINK_DOES_NOT_BIND_ASSERTION", "index": index})
        link_version = _text(link_ids.get(evidence_link_id, {}).get("document_version_hash"))
        if link_version and link_version != _text(item.get("document_version_hash")):
            errors.append({"code": "PROPOSAL_EVIDENCE_LINK_DOCUMENT_VERSION_MISMATCH", "index": index})
    return errors


def audit_research_proposal(project: dict[str, Any], proposal: dict[str, Any]) -> dict[str, Any]:
    if str(proposal.get("schema_version") or "") != "research_proposal_v2":
        raise ValueError("Proposal audit requires research_proposal_v2")
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    brief_ref = proposal.get("proposal_brief_ref") if isinstance(proposal.get("proposal_brief_ref"), dict) else {}
    brief = next(
        (item for item in project.get("proposal_briefs", []) if isinstance(item, dict) and item.get("proposal_brief_id") == brief_ref.get("proposal_brief_id")),
        {},
    )
    if not brief:
        errors.append({"code": "PROPOSAL_BRIEF_NOT_FOUND"})
    elif str(brief.get("lifecycle_status") or "CURRENT") != "CURRENT":
        errors.append({"code": "PROPOSAL_BRIEF_STALE"})
    package_ref = proposal.get("research_package_ref") if isinstance(proposal.get("research_package_ref"), dict) else {}
    package = next(
        (item for item in project.get("research_packages", []) if isinstance(item, dict) and item.get("research_package_id") == package_ref.get("research_package_id")),
        {},
    )
    if not package:
        errors.append({"code": "RESEARCH_PACKAGE_NOT_FOUND"})
    elif int(package.get("package_version") or 0) != int(package_ref.get("package_version") or 0):
        errors.append({"code": "RESEARCH_PACKAGE_VERSION_STALE"})
    elif str(package.get("lifecycle_status") or "CURRENT") != "CURRENT":
        errors.append({"code": "RESEARCH_PACKAGE_STALE_GRAPH"})
    graph_ref = proposal.get("graph_snapshot_ref") if isinstance(proposal.get("graph_snapshot_ref"), dict) else {}
    active_graph_ref = project.get("active_research_evidence_graph_ref") if isinstance(project.get("active_research_evidence_graph_ref"), dict) else {}
    if not graph_ref.get("input_fingerprint"):
        errors.append({"code": "PROPOSAL_GRAPH_PROVENANCE_MISSING"})
    else:
        graph_snapshot = _graph_snapshot(project, graph_ref)
        if not graph_snapshot:
            errors.append({"code": "PROPOSAL_GRAPH_SNAPSHOT_NOT_PERSISTED"})
        elif str(package.get("lifecycle_status") or "CURRENT") == "STALE_GRAPH_SNAPSHOT":
            errors.append({"code": "PROPOSAL_GRAPH_SNAPSHOT_STALE"})
        else:
            # A newer *unrelated* evidence snapshot does not invalidate a
            # frozen proposal.  Its own snapshot remains auditable until a
            # dependency-aware invalidation marks the package stale.
            errors.extend(_validate_evidence_bundle_against_graph(proposal, graph_snapshot))
    evidence_ids = {
        _text(item.get("assertion_id") or item.get("source_span_id") or item.get("source_unit_id"))
        for item in proposal.get("evidence_basis", []) if isinstance(item, dict)
    }
    evidence_bindings = {
        (
            _text(item.get("evidence_link_id")),
            _text(item.get("assertion_id")),
            _text(item.get("source_span_id") or item.get("source_unit_id")),
            _text(item.get("document_version_hash")),
        )
        for item in proposal.get("evidence_basis", [])
        if isinstance(item, dict)
    }
    for claim in proposal.get("claim_ledger", []):
        if not isinstance(claim, dict):
            continue
        kind = _text(claim.get("claim_kind"))
        refs = {_text(item) for item in claim.get("evidence_refs", []) if _text(item)}
        if kind == "EVIDENCE_BACKED_GAP_MOTIVATION" and not refs:
            errors.append({"code": "EVIDENCE_CLAIM_WITHOUT_REFERENCE", "claim_id": claim.get("claim_id")})
        if kind == "EVIDENCE_BACKED_GAP_MOTIVATION":
            bindings = claim.get("evidence_bindings") if isinstance(claim.get("evidence_bindings"), list) else []
            if not bindings:
                errors.append({"code": "EVIDENCE_CLAIM_WITHOUT_FULL_PROVENANCE_BINDING", "claim_id": claim.get("claim_id")})
            for binding in bindings:
                if not isinstance(binding, dict):
                    errors.append({"code": "EVIDENCE_CLAIM_BINDING_INVALID", "claim_id": claim.get("claim_id")})
                    continue
                key = (
                    _text(binding.get("evidence_link_id")),
                    _text(binding.get("assertion_id")),
                    _text(binding.get("source_span_id")),
                    _text(binding.get("document_version_hash")),
                )
                if not all(key) or key not in evidence_bindings:
                    errors.append({
                        "code": "EVIDENCE_CLAIM_BINDING_OUTSIDE_FROZEN_BUNDLE",
                        "claim_id": claim.get("claim_id"),
                    })
        if refs and not refs.issubset(evidence_ids):
            errors.append({"code": "CLAIM_REFERENCE_OUTSIDE_FROZEN_BUNDLE", "claim_id": claim.get("claim_id"), "unknown_refs": sorted(refs - evidence_ids)})
        if kind == "PROPOSED_ACTION" and refs:
            warnings.append({"code": "PROPOSED_ACTION_HAS_UNNEEDED_EVIDENCE_REFERENCE", "claim_id": claim.get("claim_id")})
    prohibited = [str(item).casefold() for item in proposal.get("prohibited_claim_patterns", []) if str(item)]
    narrative_values = [proposal.get("gap_motivation", "")] + [item.get("statement", "") for item in proposal.get("aims", []) if isinstance(item, dict)]
    for pattern in prohibited:
        if pattern and any(pattern in _text(value).casefold() for value in narrative_values):
            errors.append({"code": "PROHIBITED_CLAIM_PATTERN_PRESENT", "pattern": pattern})
    required_fields = list((brief.get("authoring_contract") or {}).get("required_design_fields") or []) if isinstance(brief, dict) else []
    design = {str(item.get("field") or ""): item for item in proposal.get("type_specific_design", []) if isinstance(item, dict)}
    for field in required_fields:
        if field not in design:
            errors.append({"code": "REQUIRED_DESIGN_FIELD_OMITTED", "field": field})
    return {
        "schema_version": PROPOSAL_AUDIT_SCHEMA_VERSION,
        "proposal_id": _text(proposal.get("proposal_id")),
        "status": "PROPOSAL_AUDIT_PASSED" if not errors else "PROPOSAL_AUDIT_BLOCKED",
        "passes": not errors,
        "errors": errors,
        "warnings": warnings,
        "checked_claim_count": len([item for item in proposal.get("claim_ledger", []) if isinstance(item, dict)]),
        "checked_at": time.time(),
    }


def audit_and_persist_research_proposal(project_id: str, proposal_id: str) -> dict[str, Any]:
    try:
        from ._project import load_project, save_project
    except ImportError:
        from _project import load_project, save_project
    project = load_project(project_id)
    try:
        from ._research_workflow import (
            PROPOSAL_AUDIT_STAGE,
            record_workflow_execution,
            record_workflow_status,
            workflow_tool_gate,
        )
    except ImportError:
        from _research_workflow import (
            PROPOSAL_AUDIT_STAGE,
            record_workflow_execution,
            record_workflow_status,
            workflow_tool_gate,
        )
    gate = workflow_tool_gate(project, PROPOSAL_AUDIT_STAGE, {"proposal_id": proposal_id})
    if not gate.get("allowed"):
        return dict(gate.get("result") or {})
    proposal = next(
        (item for item in project.get("research_proposals", []) if isinstance(item, dict) and str(item.get("proposal_id") or "") == str(proposal_id)),
        None,
    )
    if not isinstance(proposal, dict):
        raise ValueError("No current research_proposal_v2 exists for the supplied proposal_id")
    audit = audit_research_proposal(project, proposal)
    proposal["audit"] = audit
    proposal["lifecycle_status"] = "CURRENT" if audit["passes"] else "AUDIT_BLOCKED"
    workflow_state = record_workflow_status(
        project,
        stage=PROPOSAL_AUDIT_STAGE,
        status="RESEARCH_PROPOSAL_READY" if audit["passes"] else "RESEARCH_PROPOSAL_AUDIT_BLOCKED",
        terminal=False,
        allowed_next_stages=["export_research_proposal_v2"] if audit["passes"] else [],
        blocked_stages=[] if audit["passes"] else ["export_research_proposal_v2"],
        reason_code="PROPOSAL_AUDIT_PASSED" if audit["passes"] else "PROPOSAL_AUDIT_FAILED",
        artifact_ids=[proposal_id],
        remediation_plan={} if audit["passes"] else {"kind": "repair_proposal_brief_or_design", "errors": list(audit.get("errors") or [])},
    )
    audit.update(workflow_state)
    project["proposal_audits"] = {
        **(project.get("proposal_audits") if isinstance(project.get("proposal_audits"), dict) else {}),
        str(proposal_id): audit,
    }
    try:
        from ._research_graph import persist_research_task_graph
    except ImportError:
        from _research_graph import persist_research_task_graph
    persist_research_task_graph(project)
    project["updatedAt"] = time.time()
    record_workflow_execution(project, PROPOSAL_AUDIT_STAGE, {"proposal_id": proposal_id}, audit, execution_key=str(gate.get("execution_key") or ""))
    save_project(project)
    return audit
