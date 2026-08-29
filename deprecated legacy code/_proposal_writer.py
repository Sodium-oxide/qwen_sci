"""Deterministic, evidence-bounded proposal rendering for ProposalBriefV2."""

from __future__ import annotations

from hashlib import sha256
import json
import time
from typing import Any


RESEARCH_PROPOSAL_SCHEMA_VERSION = "research_proposal_v2"


def _text(value: Any) -> str:
    return " ".join(str(value or "").split())


def _digest(value: Any) -> str:
    return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")).hexdigest()


def _field_label(name: str) -> str:
    return name.replace("_", " ").strip().capitalize()


def _design_rows(brief: dict[str, Any]) -> list[dict[str, Any]]:
    required = list((brief.get("authoring_contract") or {}).get("required_design_fields") or [])
    payload = brief.get("type_specific_design") if isinstance(brief.get("type_specific_design"), dict) else {}
    rows: list[dict[str, Any]] = []
    for field in required:
        current = payload.get(field)
        rows.append({
            "field": field,
            "label": _field_label(field),
            "value": current if current not in (None, "", [], {}) else "TO_BE_SPECIFIED_IN_EXECUTION_DESIGN",
            "status": "SPECIFIED" if current not in (None, "", [], {}) else "REQUIRES_DESIGN_SPECIFICATION",
        })
    return rows


def _aims(brief: dict[str, Any]) -> list[dict[str, Any]]:
    kind = _text(brief.get("proposal_kind"))
    question = _text((brief.get("research_question") or {}).get("question_text"))
    payload = brief.get("type_specific_design") if isinstance(brief.get("type_specific_design"), dict) else {}
    fields = [item for item in (brief.get("authoring_contract") or {}).get("required_design_fields", []) if item]
    return [
        {
            "aim_id": "AIM_1",
            "title": "Establish the scoped evidence and design baseline",
            "statement": question or "Specify the declared research question within its frozen scope.",
            "claim_kind": "PROPOSED_ACTION",
        },
        {
            "aim_id": "AIM_2",
            "title": "Execute the type-specific discriminating or validation design",
            "statement": f"For {kind}, operationalize: " + ", ".join(_field_label(item) for item in fields) + ".",
            "claim_kind": "PROPOSED_ACTION",
        },
        {
            "aim_id": "AIM_3",
            "title": "Apply prespecified decision rules and report scope-bounded outcomes",
            "statement": "Assess the stated success and falsification/discrimination criteria without upgrading a planned result into an established conclusion.",
            "claim_kind": "PROPOSED_ACTION",
        },
    ]


def build_proposal_claim_ledger(brief: dict[str, Any], proposal: dict[str, Any]) -> list[dict[str, Any]]:
    """Bind every evidence-backed draft statement to a frozen bundle item."""
    evidence = [item for item in brief.get("evidence_bundle", []) if isinstance(item, dict)]
    bindings = [
        {
            "evidence_link_id": _text(item.get("evidence_link_id")),
            "assertion_id": _text(item.get("assertion_id")),
            "source_span_id": _text(item.get("source_span_id") or item.get("source_unit_id")),
            "document_version_hash": _text(item.get("document_version_hash")),
            "evidence_role": _text(item.get("evidence_role") or item.get("claim_role")),
            "allowed_use": _text(item.get("allowed_use")),
        }
        for item in evidence
    ]
    return [
        {
            "claim_id": "PC_001",
            "claim_kind": "EVIDENCE_BACKED_GAP_MOTIVATION",
            "text": proposal["gap_motivation"],
            "evidence_bindings": bindings,
            "evidence_refs": [item["assertion_id"] for item in bindings if item["assertion_id"]],
            "allowed_strength": _text((brief.get("gap_statement") or {}).get("allowed_conclusion_strength")),
        },
        *[
            {
                "claim_id": f"PC_{index + 2:03d}",
                "claim_kind": "PROPOSED_ACTION",
                "text": aim["statement"],
                "evidence_refs": [],
                "allowed_strength": "PROPOSAL_ONLY",
            }
            for index, aim in enumerate(proposal.get("aims", []))
        ],
    ]


def write_research_proposal(brief: dict[str, Any]) -> dict[str, Any]:
    """Render a structured proposal without inventing unbound scientific facts."""
    if str(brief.get("schema_version") or "") != "proposal_brief_v2":
        raise ValueError("Proposal writer requires proposal_brief_v2")
    if str(brief.get("lifecycle_status") or "CURRENT") != "CURRENT":
        raise ValueError("Proposal writer refuses a stale ProposalBriefV2")
    package_ref = brief.get("research_package_ref") if isinstance(brief.get("research_package_ref"), dict) else {}
    graph_ref = brief.get("graph_snapshot_ref") if isinstance(brief.get("graph_snapshot_ref"), dict) else {}
    if not package_ref.get("research_package_id") or not graph_ref.get("input_fingerprint"):
        raise ValueError("ProposalBriefV2 lacks immutable package or graph provenance")
    proposal_id = "proposal_" + _digest({"brief": brief.get("proposal_brief_id"), "brief_version": brief.get("brief_version")})[:20]
    gap = brief.get("gap_statement") if isinstance(brief.get("gap_statement"), dict) else {}
    question = brief.get("research_question") if isinstance(brief.get("research_question"), dict) else {}
    gap_motivation = (
        f"This proposal addresses the declared {gap.get('gap_type') or 'research'} deficit for the scoped question: "
        f"{question.get('question_text') or question.get('target_knowledge_need') or 'research question to be specified'} ."
    )
    proposal = {
        "schema_version": RESEARCH_PROPOSAL_SCHEMA_VERSION,
        "proposal_id": proposal_id,
        "proposal_version": 1,
        "project_id": _text(brief.get("project_id")),
        "proposal_brief_ref": {"proposal_brief_id": _text(brief.get("proposal_brief_id")), "brief_version": int(brief.get("brief_version") or 0)},
        "research_package_ref": dict(package_ref),
        "graph_snapshot_ref": dict(graph_ref),
        "proposal_kind": _text(brief.get("proposal_kind")),
        "title": f"{_text(brief.get('proposal_kind')).replace('_', ' ').title()}: {_text(question.get('question_text') or question.get('target_knowledge_need'))}",
        "research_question": dict(question),
        "scope_contract": dict(brief.get("scope_contract") or {}),
        "gap_motivation": gap_motivation,
        "evidence_basis": list(brief.get("evidence_bundle") or []),
        "aims": _aims(brief),
        "type_specific_design": _design_rows(brief),
        "analysis_and_decision_rules": {
            "success_criteria": list(brief.get("success_criteria") or []),
            "falsification_or_discrimination": dict(brief.get("falsification_or_discrimination") or {}),
            "scope_rule": "Report only conclusions licensed by the frozen research-question scope and source-bound evidence bundle.",
        },
        "risks_and_limitations": list(brief.get("risks_and_limitations") or []),
        "prohibited_claim_patterns": list(brief.get("prohibited_claim_patterns") or []),
        "socrates_review_ref": dict(brief.get("socrates_review_ref") or {}),
        "lifecycle_status": "DRAFT_REQUIRES_AUDIT",
        "created_at": time.time(),
    }
    proposal["claim_ledger"] = build_proposal_claim_ledger(brief, proposal)
    return proposal


def write_and_persist_research_proposal(project_id: str, proposal_brief_id: str) -> dict[str, Any]:
    try:
        from ._project import load_project, save_project
    except ImportError:
        from _project import load_project, save_project
    project = load_project(project_id)
    try:
        from ._research_workflow import (
            PROPOSAL_AUDIT_STAGE,
            PROPOSAL_WRITER_STAGE,
            record_workflow_execution,
            record_workflow_status,
            workflow_tool_gate,
        )
    except ImportError:
        from _research_workflow import (
            PROPOSAL_AUDIT_STAGE,
            PROPOSAL_WRITER_STAGE,
            record_workflow_execution,
            record_workflow_status,
            workflow_tool_gate,
        )
    gate = workflow_tool_gate(project, PROPOSAL_WRITER_STAGE, {"proposal_brief_id": proposal_brief_id})
    if not gate.get("allowed"):
        return dict(gate.get("result") or {})
    brief = next(
        (item for item in project.get("proposal_briefs", []) if isinstance(item, dict) and str(item.get("proposal_brief_id") or "") == str(proposal_brief_id)),
        None,
    )
    if not isinstance(brief, dict):
        raise ValueError("No current ProposalBriefV2 exists for the supplied proposal_brief_id")
    proposal = write_research_proposal(brief)
    proposals = [item for item in project.get("research_proposals", []) if isinstance(item, dict) and item.get("proposal_id") != proposal["proposal_id"]]
    proposals.append(proposal)
    project["research_proposals"] = proposals
    workflow_state = record_workflow_status(
        project,
        stage=PROPOSAL_WRITER_STAGE,
        status="RESEARCH_PROPOSAL_DRAFT_READY_FOR_AUDIT",
        terminal=False,
        allowed_next_stages=[PROPOSAL_AUDIT_STAGE],
        blocked_stages=[],
        reason_code="TYPE_DIRECTED_PROPOSAL_DRAFT_CREATED",
        artifact_ids=[proposal["proposal_id"]],
        remediation_plan={},
    )
    proposal.update(workflow_state)
    try:
        from ._research_graph import persist_research_task_graph
    except ImportError:
        from _research_graph import persist_research_task_graph
    persist_research_task_graph(project)
    record_workflow_execution(project, PROPOSAL_WRITER_STAGE, {"proposal_brief_id": proposal_brief_id}, proposal, execution_key=str(gate.get("execution_key") or ""))
    project["updatedAt"] = time.time()
    save_project(project)
    return proposal
