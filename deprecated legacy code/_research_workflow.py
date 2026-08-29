"""Domain-neutral control contracts for the staged research workflow.

The scientific agents remain responsible for retrieval, gap analysis, and
hypothesis reasoning.  This module only controls admissible stage transitions,
idempotent replays, and compact execution summaries.
"""
from __future__ import annotations

import hashlib
import json
import time
from typing import Any, Mapping


WORKFLOW_CONTROL_KEY = "research_workflow_control"
WORKFLOW_SCHEMA_VERSION = "research_workflow_control_v2"

TANXI_TOOL = "run_tanxi_gap_exploration"
SOCRATES_TOOL = "run_socrates_mechanism_enrichment"
MINGLI_TOOL = "run_mingli_hypothesis_evolution"
PROPOSAL_BRIEF_STAGE = "build_proposal_brief_v2"
PROPOSAL_WRITER_STAGE = "write_research_proposal_v2"
PROPOSAL_AUDIT_STAGE = "audit_research_proposal_v2"
NEAR_PASS_RETRIEVAL_STAGE = "run_zhizhi_near_pass_source_role_retrieval"
TYPE_DIRECTED_RETRIEVAL_STAGE = "apply_gap_retrieval_assessment"
TYPE_SPECIFIC_SOCRATES_REVIEW_STAGE = "run_socrates_type_specific_review"
RESEARCH_QUESTION_RETRIEVAL_STAGE = "execute_research_question_retrieval_plan"

WORKFLOW_TOOLS = frozenset({
    TANXI_TOOL,
    NEAR_PASS_RETRIEVAL_STAGE,
    TYPE_DIRECTED_RETRIEVAL_STAGE,
    RESEARCH_QUESTION_RETRIEVAL_STAGE,
    TYPE_SPECIFIC_SOCRATES_REVIEW_STAGE,
    PROPOSAL_BRIEF_STAGE,
    PROPOSAL_WRITER_STAGE,
    PROPOSAL_AUDIT_STAGE,
    SOCRATES_TOOL,
    MINGLI_TOOL,
})
V3_GROUPCHAT_ONLY_TASK_TOOLS = frozenset({
    "create_science_pipeline_tasks",
    "create_science_delegation_tasks",
    "create_science_crew",
    "run_science_crew_flow",
})
TERMINAL_STATUSES = frozenset(
    {
        "INSUFFICIENT_GROUNDED_GAPS",
        "BLOCKED_INVALID_UPSTREAM_ARTIFACT",
        "BLOCKED_NO_READY_HANDOFF",
        "BLOCKED_UPSTREAM",
        "BLOCKED_TERMINAL_STATE",
    }
)


_RESTRICTED_BRIDGE_REQUIRED_ROLES = ("input", "mediator", "outcome", "comparison")


def _role_text(value: Any) -> str:
    if isinstance(value, Mapping):
        for key in ("value", "normalized_value", "candidate", "text", "label", "name"):
            text = _role_text(value.get(key))
            if text:
                return text
        return ""
    if isinstance(value, (list, tuple, set)):
        return "; ".join(text for text in (_role_text(item) for item in value) if text)
    text = str(value or "").strip()
    if not text:
        return ""
    lowered = text.lower()
    if lowered in {"unresolved", "unknown", "none", "n/a", "generic_placeholder"}:
        return ""
    if lowered.startswith("requires_") or lowered.startswith("requires-"):
        return ""
    if "fragment_refs" in lowered and ("'value': ''" in lowered or '"value": ""' in lowered):
        return ""
    return text


def restricted_component_bridge_role_contract_ready(item: Mapping[str, Any] | None) -> bool:
    payload = item if isinstance(item, Mapping) else {}
    contract = (
        payload.get("restricted_bridge_role_contract")
        if isinstance(payload.get("restricted_bridge_role_contract"), Mapping)
        else {}
    )
    roles = contract.get("roles") if isinstance(contract.get("roles"), Mapping) else {}
    if contract and contract.get("ready") is False:
        return False
    for role in _RESTRICTED_BRIDGE_REQUIRED_ROLES:
        if isinstance(roles.get(role), Mapping):
            value = roles.get(role)
        elif role == "input":
            value = payload.get("input") or payload.get("intervention")
        elif role == "mediator":
            value = payload.get("mediator") or payload.get("proposed_mediator")
        else:
            value = payload.get(role)
        if not _role_text(value):
            return False
    return True


def is_workflow_tool(name: Any) -> bool:
    return str(name or "").strip() in WORKFLOW_TOOLS


def workflow_control(project: dict[str, Any]) -> dict[str, Any]:
    current = project.get(WORKFLOW_CONTROL_KEY)
    if isinstance(current, dict):
        current["schema_version"] = WORKFLOW_SCHEMA_VERSION
        current.setdefault("executions", {})
        current.setdefault("history", [])
        return current
    created: dict[str, Any] = {
        "schema_version": WORKFLOW_SCHEMA_VERSION,
        "state_version": int(project.get("state_version") or 0),
        "active_stage": "",
        "status": "NOT_STARTED",
        "terminal": False,
        "allowed_next_stages": [TANXI_TOOL],
        "blocked_stages": [],
        "reason_code": "",
        "artifact_ids": [],
        "remediation_plan": {},
        "executions": {},
        "history": [],
        "updated_at": time.time(),
    }
    project[WORKFLOW_CONTROL_KEY] = created
    return created


def artifact_provenance_refs(
    project: Mapping[str, Any],
    artifact_ids: list[str] | tuple[str, ...],
) -> list[dict[str, Any]]:
    """Resolve workflow artifacts by immutable candidate identity and state.

    ``gap_id`` remains an invocation convenience for older tools, but every
    workflow history entry records the candidate/state tuple required to join
    a result across TanXi snapshots.  Registry lookup also covers candidates
    that are intentionally absent from ``knowledge_gaps`` (for example an
    extraction-shortage near-pass candidate).
    """
    requested = {str(value) for value in artifact_ids if str(value)}
    if not requested:
        return []
    tanxi = project.get("tanxi_gap_analysis") if isinstance(project.get("tanxi_gap_analysis"), Mapping) else {}
    collections = [
        project.get("knowledge_gaps") or [],
        tanxi.get("ranked_gaps") or [],
        tanxi.get("evidence_extraction_shortages") or [],
        tanxi.get("secondary_research_opportunities") or [],
        tanxi.get("rejected_evidence_audit") or [],
    ]
    refs_by_id: dict[str, dict[str, Any]] = {}
    for collection in collections:
        for item in collection:
            if not isinstance(item, Mapping):
                continue
            gap_id = str(item.get("gap_id") or "")
            if gap_id not in requested:
                continue
            provenance = item.get("gap_provenance") if isinstance(item.get("gap_provenance"), Mapping) else {}
            refs_by_id[gap_id] = {
                "candidate_identity": str(item.get("candidate_identity") or provenance.get("candidate_identity") or ""),
                "state_version": int(
                    provenance.get("state_version") or item.get("state_version") or project.get("state_version") or 0
                ),
                "canonical_gap_id": str(provenance.get("canonical_gap_id") or gap_id),
            }
    registry = project.get("gap_identity_registry") if isinstance(project.get("gap_identity_registry"), Mapping) else {}
    assignments = registry.get("assignments") if isinstance(registry.get("assignments"), Mapping) else {}
    for identity, assignment in assignments.items():
        if not isinstance(assignment, Mapping):
            continue
        canonical_id = str(assignment.get("canonical_gap_id") or "")
        if canonical_id in requested and canonical_id not in refs_by_id:
            versions = assignment.get("state_versions") if isinstance(assignment.get("state_versions"), list) else []
            refs_by_id[canonical_id] = {
                "candidate_identity": str(identity),
                "state_version": int(max(versions) if versions else project.get("state_version") or 0),
                "canonical_gap_id": canonical_id,
            }
    return [
        {"gap_id": gap_id, **refs_by_id.get(gap_id, {"candidate_identity": "", "state_version": int(project.get("state_version") or 0), "canonical_gap_id": gap_id})}
        for gap_id in sorted(requested)
    ]


def normalized_workflow_input(tool_name: str, tool_input: Mapping[str, Any] | None) -> dict[str, Any]:
    ignored = {
        "project_id",
        "max_runtime_seconds",
        "poll_interval_seconds",
        "run_in_background",
        "force_new_project",
    }
    normalized = {
        str(key): value
        for key, value in sorted(dict(tool_input or {}).items())
        if str(key) not in ignored
    }
    if tool_name == SOCRATES_TOOL:
        supplied_gap = normalized.pop("gap", "")
        if not normalized.get("gap_id"):
            if isinstance(supplied_gap, Mapping):
                normalized["gap_id"] = str(supplied_gap.get("gap_id") or "")
            else:
                normalized["gap_id"] = str(supplied_gap or "")
    return normalized


def workflow_dependency_signature(
    project: Mapping[str, Any],
    tool_name: str,
    tool_input: Mapping[str, Any] | None = None,
) -> str:
    """Fingerprint only the upstream artifacts relevant to one workflow stage."""

    paper_ids = sorted(
        str(item.get("paper_id") or item.get("unique_key") or "")
        for item in project.get("papergraph", [])
        if isinstance(item, Mapping) and item.get("active", True) is not False
    )
    gap_artifacts = sorted(
        [
            {
                "candidate_identity": str(item.get("candidate_identity") or ""),
                "gap_id": str(item.get("gap_id") or ""),
                "state_version": int(
                    ((item.get("gap_provenance") or {}).get("state_version"))
                    or item.get("state_version")
                    or project.get("state_version")
                    or 0
                ),
            }
        for item in project.get("knowledge_gaps", [])
        if isinstance(item, Mapping) and str(item.get("gap_id") or "")
        ],
        key=lambda item: (item["candidate_identity"], item["gap_id"], item["state_version"]),
    )
    ranked = (
        project.get("tanxi_gap_analysis", {}).get("ranked_gaps", [])
        if isinstance(project.get("tanxi_gap_analysis"), Mapping)
        else []
    )
    ranked_gap_artifacts = sorted(
        [
            {
                "candidate_identity": str(item.get("candidate_identity") or ""),
                "gap_id": str(item.get("gap_id") or ""),
                "state_version": int(
                    ((item.get("gap_provenance") or {}).get("state_version"))
                    or item.get("state_version")
                    or project.get("state_version")
                    or 0
                ),
            }
        for item in ranked
        if isinstance(item, Mapping) and str(item.get("gap_id") or "")
        ],
        key=lambda item: (item["candidate_identity"], item["gap_id"], item["state_version"]),
    )
    contracts = project.get("socrates_mechanism_contracts")
    contract_statuses = {
        str(key): _contract_readiness_status(value)
        for key, value in dict(contracts or {}).items()
        if str(key)
    }
    include_gap_artifacts = tool_name != TANXI_TOOL
    include_socrates_contracts = tool_name == MINGLI_TOOL
    payload = {
        "tool": str(tool_name),
        "input": normalized_workflow_input(tool_name, tool_input),
        "paper_ids": paper_ids,
        # A gap id is retained for backwards compatibility, but mutable
        # ordinal ids are no longer the join key for workflow replay/audit.
        "gap_artifacts": gap_artifacts if include_gap_artifacts else [],
        "ranked_gap_artifacts": ranked_gap_artifacts if include_gap_artifacts else [],
        "contract_statuses": contract_statuses if include_socrates_contracts else {},
        "research_evidence_graph_ref": (
            dict(project.get("active_research_evidence_graph_ref") or {})
            if tool_name in {
                TYPE_SPECIFIC_SOCRATES_REVIEW_STAGE,
                PROPOSAL_BRIEF_STAGE,
                PROPOSAL_WRITER_STAGE,
                PROPOSAL_AUDIT_STAGE,
            }
            else {}
        ),
        "research_packages": (
            [
                {
                    "research_package_id": str(item.get("research_package_id") or ""),
                    "package_version": int(item.get("package_version") or 0),
                    "lifecycle_status": str(item.get("lifecycle_status") or ""),
                    "graph_snapshot_ref": dict(item.get("graph_snapshot_ref") or {}),
                }
                for item in project.get("research_packages", [])
                if isinstance(item, Mapping)
            ]
            if tool_name in {TYPE_SPECIFIC_SOCRATES_REVIEW_STAGE, PROPOSAL_BRIEF_STAGE}
            else []
        ),
        "proposal_briefs": (
            [
                {
                    "proposal_brief_id": str(item.get("proposal_brief_id") or ""),
                    "brief_version": int(item.get("brief_version") or 0),
                    "lifecycle_status": str(item.get("lifecycle_status") or ""),
                    "graph_snapshot_ref": dict(item.get("graph_snapshot_ref") or {}),
                }
                for item in project.get("proposal_briefs", [])
                if isinstance(item, Mapping)
            ]
            if tool_name == PROPOSAL_WRITER_STAGE
            else []
        ),
        "research_proposals": (
            [
                {
                    "proposal_id": str(item.get("proposal_id") or ""),
                    "proposal_version": int(item.get("proposal_version") or 0),
                    "lifecycle_status": str(item.get("lifecycle_status") or ""),
                    "graph_snapshot_ref": dict(item.get("graph_snapshot_ref") or {}),
                }
                for item in project.get("research_proposals", [])
                if isinstance(item, Mapping)
            ]
            if tool_name == PROPOSAL_AUDIT_STAGE
            else []
        ),
    }
    encoded = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:24]


def workflow_execution_key(
    project: Mapping[str, Any],
    tool_name: str,
    tool_input: Mapping[str, Any] | None = None,
) -> str:
    return f"{tool_name}:{workflow_dependency_signature(project, tool_name, tool_input)}"


def record_workflow_status(
    project: dict[str, Any],
    *,
    stage: str,
    status: str,
    terminal: bool,
    allowed_next_stages: list[str] | tuple[str, ...] = (),
    blocked_stages: list[str] | tuple[str, ...] = (),
    reason_code: str = "",
    artifact_ids: list[str] | tuple[str, ...] = (),
    artifact_modes: Mapping[str, Any] | None = None,
    remediation_plan: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    control = workflow_control(project)
    artifact_values = [str(value) for value in artifact_ids if str(value)]
    artifact_id_set = set(artifact_values)
    artifact_mode_values = {
        str(artifact_id): str(mode)
        for artifact_id, mode in (artifact_modes or {}).items()
        if str(artifact_id) in artifact_id_set and str(mode)
    }
    record = {
        "stage": str(stage),
        "status": str(status),
        "terminal": bool(terminal),
        "allowed_next_stages": list(dict.fromkeys(str(value) for value in allowed_next_stages if str(value))),
        "blocked_stages": list(dict.fromkeys(str(value) for value in blocked_stages if str(value))),
        "reason_code": str(reason_code),
        "artifact_ids": artifact_values,
        # TanXi owns the per-gap Socrates retrieval mode. Keep it with the
        # handoff record so status persistence cannot discard that contract.
        "artifact_modes": artifact_mode_values,
        "artifact_provenance": artifact_provenance_refs(project, artifact_values),
        "remediation_plan": dict(remediation_plan or {}),
        "state_version": int(project.get("state_version") or control.get("state_version") or 0),
        "upstream_signature": workflow_dependency_signature(project, stage),
        "updated_at": time.time(),
    }
    control.update(record)
    control["active_stage"] = str(stage)
    history = control.setdefault("history", [])
    if isinstance(history, list):
        history.append(dict(record))
        control["history"] = history[-60:]
    return record


def workflow_result(
    project: Mapping[str, Any],
    *,
    status: str,
    terminal: bool,
    reason_code: str,
    allowed_next_stages: list[str] | tuple[str, ...] = (),
    blocked_stages: list[str] | tuple[str, ...] = (),
    remediation_plan: Mapping[str, Any] | None = None,
    artifact_ids: list[str] | tuple[str, ...] = (),
) -> dict[str, Any]:
    return {
        "status": str(status),
        "terminal": bool(terminal),
        "project_id": str(project.get("project_id") or ""),
        "state_version": int(project.get("state_version") or 0),
        "reason_code": str(reason_code),
        "allowed_next_stages": [str(value) for value in allowed_next_stages if str(value)],
        "blocked_stages": [str(value) for value in blocked_stages if str(value)],
        "remediation_plan": dict(remediation_plan or {}),
        "artifact_ids": [str(value) for value in artifact_ids if str(value)],
        "artifact_provenance": artifact_provenance_refs(project, artifact_ids),
    }


def tanxi_workflow_contract(report: Mapping[str, Any]) -> dict[str, Any]:
    """Route only the current, type-directed TanXi report contract."""
    if str(report.get("schema_version") or "") != "tanxi_gap_report_v3":
        raise ValueError("TanXi workflow requires tanxi_gap_report_v3; legacy report fallbacks are disabled")
    try:
        from ._gap_types import GapRoute, assessment_of, is_primary_research_candidate
    except ImportError:
        from _gap_types import GapRoute, assessment_of, is_primary_research_candidate
    ranked = [item for item in report.get("ranked_gaps", []) if isinstance(item, Mapping)]
    for item in ranked:
        assessment_of(dict(item))
    primary_research = [item for item in ranked if is_primary_research_candidate(dict(item))]
    targeted = [
        item for item in ranked
        if assessment_of(dict(item)).get("route") == GapRoute.TARGETED_RETRIEVAL.value
    ]
    gap_resolution_work_items = [
        item
        for item in report.get("gap_resolution_work_items_v3", [])
        if isinstance(item, Mapping)
        and str(item.get("schema_version") or "") == "retrieval_work_item_v3"
        and str(item.get("work_item_kind") or "") == "GAP_RESOLUTION"
    ]
    work_items_by_candidate = {
        str(item.get("gap_candidate_id") or ""): item
        for item in gap_resolution_work_items
        if str(item.get("gap_candidate_id") or "")
    }
    packages = [item for item in report.get("research_packages", []) if isinstance(item, Mapping)]
    workflow_integrity = (
        report.get("research_evidence_graph_workflow_integrity")
        if isinstance(report.get("research_evidence_graph_workflow_integrity"), Mapping)
        else {}
    )
    if str(workflow_integrity.get("status") or "") == "INTEGRITY_ERROR":
        return {
            "status": "NEEDS_EVIDENCE_ARTIFACT_INTEGRITY_REPAIR",
            "terminal": False,
            "allowed_next_stages": [RESEARCH_QUESTION_RETRIEVAL_STAGE, TANXI_TOOL],
            "blocked_stages": [TYPE_DIRECTED_RETRIEVAL_STAGE, SOCRATES_TOOL, MINGLI_TOOL, PROPOSAL_BRIEF_STAGE, PROPOSAL_WRITER_STAGE, PROPOSAL_AUDIT_STAGE],
            "reason_code": "REFERENCE_FIRST_ASSERTION_PROVENANCE_INCOMPLETE",
            "artifact_ids": [],
            "remediation_plan": {
                "kind": "reference_first_artifact_integrity_repair",
                "instruction": "Repair or re-extract assertions that lack immutable document and source-span provenance, then rerun TanXi. This is a workflow-integrity diagnostic, not a scientific gap.",
                "artifact_integrity_errors_v3": list(
                    workflow_integrity.get("artifact_integrity_errors_v3") or []
                ),
            },
        }
    if targeted:
        retrieval_candidates = []
        for item in targeted:
            candidate = dict(item)
            candidate_identity = str(candidate.get("candidate_identity") or "")
            work_item = work_items_by_candidate.get(candidate_identity, {})
            retrieval_state = (
                candidate.get("gap_resolution_retrieval")
                if isinstance(candidate.get("gap_resolution_retrieval"), Mapping)
                else {}
            )
            execution_state = (
                work_item.get("execution_state")
                if isinstance(work_item.get("execution_state"), Mapping)
                else retrieval_state
            )
            retrieval_candidates.append({
                "gap_id": str(candidate.get("gap_id") or ""),
                "candidate_identity": candidate_identity,
                "gap_type": assessment_of(candidate).get("gap_type"),
                "retrieval_plan": dict(candidate.get("retrieval_plan") or {}),
                "retrieval_pending": True,
                "work_item_id": str(
                    work_item.get("work_item_id")
                    or retrieval_state.get("work_item_id")
                    or ""
                ),
                "target_slot_ids": list(
                    work_item.get("target_slot_ids")
                    or retrieval_state.get("target_slot_ids")
                    or []
                ),
                "missing_obligation_slot_ids": list(
                    execution_state.get("missing_obligation_slot_ids")
                    or retrieval_state.get("missing_obligation_slot_ids")
                    or []
                ),
                "retrieval_status": str(
                    execution_state.get("status")
                    or retrieval_state.get("status")
                    or "PENDING_SLOT_BINDING"
                ),
                "retrieval_stage": str(
                    execution_state.get("stage")
                    or retrieval_state.get("stage")
                    or "CONTRACT_VALIDATION"
                ),
                "retrieval_reason_code": str(
                    execution_state.get("reason_code")
                    or retrieval_state.get("reason_code")
                    or "GAP_RESOLUTION_SLOT_BINDING_REQUIRED"
                ),
            })
        return {
            "status": "NEEDS_TYPE_DIRECTED_RETRIEVAL",
            "terminal": False,
            "allowed_next_stages": [TYPE_DIRECTED_RETRIEVAL_STAGE],
            "blocked_stages": [SOCRATES_TOOL, MINGLI_TOOL],
            "reason_code": (
                "GAP_RESOLUTION_WORK_ITEMS_PENDING"
                if gap_resolution_work_items
                else "GAP_RESOLUTION_SLOT_BINDING_REQUIRED"
            ),
            "artifact_ids": [str(item.get("gap_id") or "") for item in targeted if str(item.get("gap_id") or "")],
            "remediation_plan": {
                "kind": "type_directed_retrieval",
                "instruction": (
                    "Execute each GAP_RESOLUTION work item against its exact target slots, then import full text, "
                    "extract and admit source spans/assertions, build gap_targeted_retrieval_result_v3, and submit "
                    "it through the V3 rebind, mandatory re-audit, and qualification boundary."
                ),
                "candidates": retrieval_candidates,
                "gap_resolution_work_item_ids": [
                    str(item.get("work_item_id") or "")
                    for item in gap_resolution_work_items
                    if str(item.get("work_item_id") or "")
                ],
            },
        }
    if primary_research:
        return {
            "status": "READY_FOR_TYPE_SPECIFIC_SOCRATES_REVIEW",
            "terminal": False,
            "allowed_next_stages": [TYPE_SPECIFIC_SOCRATES_REVIEW_STAGE],
            "blocked_stages": [SOCRATES_TOOL, MINGLI_TOOL, PROPOSAL_BRIEF_STAGE, PROPOSAL_WRITER_STAGE, PROPOSAL_AUDIT_STAGE],
            "reason_code": "QUALIFIED_TYPE_DIRECTED_RESEARCH_PACKAGE_READY",
            "artifact_ids": [str(item.get("gap_id") or "") for item in primary_research if str(item.get("gap_id") or "")],
            "remediation_plan": {
                "kind": "execute_type_specific_research_package",
                "instruction": "Execute the package's declared design and falsification/discrimination requirements; do not convert any package into a legacy hypothesis package.",
                "research_package_ids": [
                    str(item.get("research_package_id") or "")
                    for item in packages
                    if str(item.get("research_package_id") or "")
                ],
            },
        }
    branch_states = [item for item in report.get("branch_gap_states", []) if isinstance(item, Mapping)]
    missing_assertion_branches = [
        item for item in branch_states
        if str(item.get("state") or "") == "INSUFFICIENT_EVIDENCE_FOR_GAP_ANALYSIS"
        and str(item.get("first_blocking_stage") or "") == "EXPLICIT_ASSERTION_EXTRACTION"
    ]
    if missing_assertion_branches:
        return {
            "status": "NEEDS_RESEARCH_QUESTION_RETRIEVAL",
            "terminal": False,
            "allowed_next_stages": [RESEARCH_QUESTION_RETRIEVAL_STAGE],
            "blocked_stages": [TYPE_DIRECTED_RETRIEVAL_STAGE, SOCRATES_TOOL, MINGLI_TOOL, PROPOSAL_BRIEF_STAGE, PROPOSAL_WRITER_STAGE, PROPOSAL_AUDIT_STAGE],
            "reason_code": "V3_RESEARCH_QUESTION_HAS_NO_SOURCE_BOUND_ASSERTIONS",
            "artifact_ids": [str(item.get("sub_hypothesis_id") or "") for item in missing_assertion_branches if str(item.get("sub_hypothesis_id") or "")],
            "remediation_plan": {
                "kind": "research_question_slot_retrieval_and_extraction",
                "instruction": (
                    "Execute the SH's v2 slot and disconfirmation tasks, import only explicit research-question-bound sources, "
                    "then extract source spans and explicit assertions. Empty search results remain coverage diagnostics."
                ),
            },
        }
    shortages = [item for item in report.get("evidence_extraction_shortages", []) if isinstance(item, Mapping)]
    if shortages:
        return {
            "status": "NEEDS_EXTRACTION_REMEDIATION",
            "terminal": False,
            "allowed_next_stages": ["run_document_evidence_remediation", TANXI_TOOL],
            "blocked_stages": [TYPE_DIRECTED_RETRIEVAL_STAGE, SOCRATES_TOOL, MINGLI_TOOL, PROPOSAL_BRIEF_STAGE, PROPOSAL_WRITER_STAGE, PROPOSAL_AUDIT_STAGE],
            "reason_code": "EVIDENCE_EXTRACTION_SHORTAGE",
            "artifact_ids": [str(item.get("gap_id") or "") for item in shortages if str(item.get("gap_id") or "")],
            "remediation_plan": {"kind": "evidence_extraction", "instruction": "Repair source conversion or source-unit extraction before rerunning TanXi."},
        }
    return {
        "status": "NEEDS_TYPE_SPECIFIC_SEMANTIC_REPAIR",
        "terminal": False,
        "allowed_next_stages": [TANXI_TOOL],
        "blocked_stages": [TYPE_DIRECTED_RETRIEVAL_STAGE, SOCRATES_TOOL, MINGLI_TOOL, PROPOSAL_BRIEF_STAGE, PROPOSAL_WRITER_STAGE, PROPOSAL_AUDIT_STAGE],
        "reason_code": "NO_CANDIDATE_PASSED_SEMANTIC_AND_PAYLOAD_GATE",
        "artifact_ids": [],
        "remediation_plan": {
            "kind": "source_span_and_type_payload_repair",
            "instruction": "Recover source spans or the fields required by the declared gap type, then rerun TanXi; do not promote a discovery lead by graph topology alone.",
        },
    }

def socrates_workflow_contract(report: Mapping[str, Any]) -> dict[str, Any]:
    readiness = report.get("hypothesis_readiness") if isinstance(report.get("hypothesis_readiness"), Mapping) else {}
    verdict = str(report.get("verdict") or report.get("status") or "")
    gap_id = str(report.get("gap_id") or "")
    if report.get("post_draft_restricted_bridge") is True:
        return {
            "status": "POST_DRAFT_SOCRATES_ENRICHMENT_COMPLETE",
            "terminal": False,
            "allowed_next_stages": ["run_yanzhen_mechanism_verification", "run_mingli_debate_iteration_loop"],
            "blocked_stages": [],
            "reason_code": "RESTRICTED_BRIDGE_DRAFT_ENRICHED_FOR_DEBATE",
            "artifact_ids": [gap_id] if gap_id else [],
            "remediation_plan": {
                "kind": "conclusion_scope_disclaimer",
                "instruction": (
                    "Use the Socrates enrichment dossier in debate. The final conclusion must state that "
                    "the declared object has not been verified."
                ),
            },
        }
    is_ready = verdict == "READY_FOR_HYPOTHESIS" or str(readiness.get("contract_status") or "") == "READY_FOR_HYPOTHESIS"
    if verdict == "MECHANISM_VERIFICATION_COMPLETED_PENDING_TANXI_READMISSION":
        return {
            "status": verdict,
            "terminal": False,
            "allowed_next_stages": [TANXI_TOOL],
            "blocked_stages": [MINGLI_TOOL],
            "reason_code": "MECHANISM_LEAD_REQUIRES_TANXI_READMISSION",
            "artifact_ids": [gap_id] if gap_id else [],
            "remediation_plan": {
                "kind": "tanxi_scientific_readmission",
                "instruction": "Re-audit the retrieved transmission evidence in TanXi before the candidate can become a primary gap.",
            },
        }
    if is_ready:
        return {
            "status": "READY_FOR_HYPOTHESIS",
            "terminal": False,
            "allowed_next_stages": [SOCRATES_TOOL, MINGLI_TOOL],
            "blocked_stages": [],
            "reason_code": "SOCRATES_HANDOFF_READY",
            "artifact_ids": [gap_id] if gap_id else [],
            "remediation_plan": {},
        }
    if verdict in {"BLOCKED_INVALID_UPSTREAM_ARTIFACT", "SECONDARY_RESEARCH_OPPORTUNITY"}:
        return {
            "status": "BLOCKED_UPSTREAM",
            "terminal": False,
            "allowed_next_stages": [SOCRATES_TOOL],
            "blocked_stages": [MINGLI_TOOL],
            "reason_code": verdict or "INVALID_UPSTREAM_ARTIFACT",
            "artifact_ids": [gap_id] if gap_id else [],
            "remediation_plan": {},
        }
    return {
        "status": "INSUFFICIENT_EVIDENCE",
        "terminal": False,
        "allowed_next_stages": [SOCRATES_TOOL],
        "blocked_stages": [MINGLI_TOOL],
        "reason_code": "SOCRATES_HANDOFF_NOT_READY",
        "artifact_ids": [gap_id] if gap_id else [],
        "remediation_plan": {
            "kind": "bounded_evidence_retrieval",
            "instruction": "Run only the missing evidence-role repair specified by the Socrates contract.",
        },
    }


def mingli_workflow_contract(report: Mapping[str, Any]) -> dict[str, Any]:
    status = str(report.get("status") or "")
    hypothesis_ids = [
        str(item.get("hypothesis_id") or "")
        for item in report.get("top_hypotheses", [])
        if isinstance(item, Mapping) and str(item.get("hypothesis_id") or "")
    ]
    if hypothesis_ids:
        restricted_hypothesis_ids: list[str] = []
        for item in report.get("top_hypotheses", []):
            if not isinstance(item, Mapping):
                continue
            package = item.get("hypothesis_package") if isinstance(item.get("hypothesis_package"), Mapping) else {}
            source_gap = item.get("source_gap") if isinstance(item.get("source_gap"), Mapping) else {}
            is_restricted_bridge = (
                str(package.get("package_type") or package.get("hypothesis_package_type") or "")
                == "restricted_component_bridge"
                or bool(item.get("final_object_claim_disclaimer"))
                or source_gap.get("component_bridge_gap_synthesis_ready") is True
                or source_gap.get("restricted_component_bridge_hypothesis_allowed") is True
            )
            if is_restricted_bridge and str(item.get("hypothesis_id") or ""):
                restricted_hypothesis_ids.append(str(item.get("hypothesis_id") or ""))
        if restricted_hypothesis_ids:
            return {
                "status": "HYPOTHESIS_DRAFT_READY_FOR_POST_DRAFT_SOCRATES",
                "terminal": False,
                "allowed_next_stages": [SOCRATES_TOOL],
                "blocked_stages": [MINGLI_TOOL],
                "reason_code": "RESTRICTED_BRIDGE_DRAFT_REQUIRES_POST_DRAFT_SOCRATES",
                "artifact_ids": restricted_hypothesis_ids,
                "remediation_plan": {
                    "kind": "post_draft_socrates_enrichment",
                    "instruction": (
                        "Run Socrates after the first MingLi hypothesis, then enter debate. "
                        "Do not use direct-core availability as a gate; preserve the final-object disclaimer."
                    ),
                },
            }
        return {
            "status": "HYPOTHESIS_READY",
            "terminal": False,
            "allowed_next_stages": ["run_yanzhen_mechanism_verification", "run_mingli_debate_iteration_loop"],
            "blocked_stages": [],
            "reason_code": "HYPOTHESIS_GENERATED",
            "artifact_ids": hypothesis_ids,
            "remediation_plan": {},
        }
    return {
        "status": status or "BLOCKED_NO_READY_HANDOFF",
        "terminal": True,
        "allowed_next_stages": [],
        "blocked_stages": [],
        "reason_code": "NO_READY_SOCRATES_HANDOFF",
        "artifact_ids": [],
        "remediation_plan": {},
    }


def workflow_tool_gate(
    project: Mapping[str, Any],
    tool_name: str,
    tool_input: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a domain-neutral admission decision without mutating the project."""

    name = str(tool_name or "")
    if name in V3_GROUPCHAT_ONLY_TASK_TOOLS:
        subhypotheses = project.get("sub_hypotheses") if isinstance(project, Mapping) else []
        has_v3_contracts = any(
            isinstance(item, Mapping)
            and isinstance(item.get("research_question_contract"), Mapping)
            and str((item.get("research_question_contract") or {}).get("schema_version") or "")
            == "research_question_contract_v3"
            for item in (subhypotheses or [])
        )
        if str(project.get("workflow_mode") or "") == "V3_GROUPCHAT_ONLY" or has_v3_contracts:
            project_id = str(project.get("project_id") or "")
            return {
                "allowed": False,
                "result": {
                    "status": "BLOCKED_V3_GROUPCHAT_ONLY",
                    "terminal": False,
                    "project_id": project_id,
                    "reason_code": "V3_GROUPCHAT_RESUME_REQUIRED",
                    "blocked_tool": name,
                    "instruction": (
                        "The canonical V3 GroupChat owns decomposition, retrieval, evidence admission, "
                        "TanXi, review, and revision. Resume the same GroupChat checkpoint; do not create "
                        "persistent pipeline tasks, delegation tasks, DAGs, or crews."
                    ),
                },
            }
    if name not in WORKFLOW_TOOLS:
        return {"allowed": True}
    control = project.get(WORKFLOW_CONTROL_KEY)
    state = control if isinstance(control, Mapping) else {}
    execution_key = workflow_execution_key(project, name, tool_input)
    prior = state.get("executions", {}).get(execution_key) if isinstance(state.get("executions"), Mapping) else None
    if isinstance(prior, Mapping):
        return {
            "allowed": False,
            "result": workflow_result(
                project,
                status="DUPLICATE_STATE_UNCHANGED",
                terminal=bool(prior.get("terminal")),
                reason_code="WORKFLOW_INPUT_ALREADY_EXECUTED_FOR_SAME_UPSTREAM_STATE",
                allowed_next_stages=prior.get("allowed_next_stages") or [],
                blocked_stages=[name],
                remediation_plan=prior.get("remediation_plan") if isinstance(prior.get("remediation_plan"), Mapping) else {},
                artifact_ids=prior.get("artifact_ids") or [],
            ),
        }

    current_status = str(state.get("status") or "")
    terminal = bool(state.get("terminal")) or current_status in TERMINAL_STATUSES
    if name == TANXI_TOOL:
        prior_signature = str(state.get("upstream_signature") or "")
        current_signature = workflow_dependency_signature(project, TANXI_TOOL)
        if terminal and prior_signature == current_signature:
            return _blocked(project, "BLOCKED_TERMINAL_STATE", "WORKFLOW_TERMINAL_REQUIRES_NEW_EVIDENCE_OR_CONTRACT", name)
        return {"allowed": True, "execution_key": execution_key}

    known_gap_ids = canonical_gap_ids(project)
    if name == NEAR_PASS_RETRIEVAL_STAGE:
        task_rows = (
            project.get("tanxi_gap_analysis", {}).get("near_pass_targeted_retrieval_tasks", [])
            if isinstance(project.get("tanxi_gap_analysis"), Mapping)
            else []
        )
        requested_identity = str((tool_input or {}).get("candidate_identity") or "").strip()
        requested_gap_id = str((tool_input or {}).get("gap_id") or "").strip()
        matching_tasks = [
            task for task in task_rows
            if isinstance(task, Mapping)
            and task.get("eligible") is True
            and (
                (requested_identity and str(task.get("candidate_identity") or "") == requested_identity)
                or (requested_gap_id and str(task.get("gap_id") or "") == requested_gap_id)
            )
        ]
        if not matching_tasks:
            return _blocked(project, "BLOCKED_INVALID_UPSTREAM_ARTIFACT", "NO_ELIGIBLE_NEAR_PASS_RETRIEVAL_TASK", name)
        if name not in set(state.get("allowed_next_stages") or []):
            return _blocked(project, "BLOCKED_UPSTREAM", "TANXI_HAS_NOT_AUTHORIZED_NEAR_PASS_RETRIEVAL", name)
        return {"allowed": True, "execution_key": execution_key}

    if name == RESEARCH_QUESTION_RETRIEVAL_STAGE:
        try:
            from ._research_question_contract import (
                RESEARCH_QUESTION_RETRIEVAL_PLAN_VERSION,
                build_question_retrieval_plan,
                validate_research_question_contract,
            )
        except ImportError:
            from _research_question_contract import (
                RESEARCH_QUESTION_RETRIEVAL_PLAN_VERSION,
                build_question_retrieval_plan,
                validate_research_question_contract,
            )
        sub_hypothesis_id = str((tool_input or {}).get("sub_hypothesis_id") or "").strip()
        sub_hypothesis = next(
            (
                item for item in project.get("sub_hypotheses", [])
                if isinstance(item, Mapping) and str(item.get("id") or item.get("sub_hypothesis_id") or "") == sub_hypothesis_id
            ),
            None,
        )
        contract = (
            sub_hypothesis.get("research_question_contract")
            if isinstance(sub_hypothesis, Mapping)
            and isinstance(sub_hypothesis.get("research_question_contract"), Mapping)
            else {}
        )
        try:
            plan = build_question_retrieval_plan(
                validate_research_question_contract(contract)
            )
        except (TypeError, ValueError):
            plan = {}
        if not isinstance(sub_hypothesis, Mapping) or plan.get("schema_version") != RESEARCH_QUESTION_RETRIEVAL_PLAN_VERSION:
            return _blocked(project, "BLOCKED_INVALID_UPSTREAM_ARTIFACT", "V3_RESEARCH_QUESTION_RETRIEVAL_PLAN_REQUIRED", name)
        initial_v3_retrieval_bootstrap = bool(
            not state
            or (
                str(state.get("status") or "") in {"", "NOT_STARTED"}
                and not state.get("history")
                and not state.get("executions")
            )
        )
        if (
            name not in set(state.get("allowed_next_stages") or [])
            and not initial_v3_retrieval_bootstrap
        ):
            return _blocked(project, "BLOCKED_UPSTREAM", "TANXI_HAS_NOT_AUTHORIZED_RESEARCH_QUESTION_RETRIEVAL", name)
        return {"allowed": True, "execution_key": execution_key}

    if name == TYPE_DIRECTED_RETRIEVAL_STAGE:
        try:
            from ._gap_types import GapRoute, assessment_of
            from ._research_question_contract import validate_retrieval_work_item_v3
        except ImportError:
            from _gap_types import GapRoute, assessment_of
            from _research_question_contract import validate_retrieval_work_item_v3
        gap_id = str((tool_input or {}).get("gap_id") or "").strip()
        tanxi = project.get("tanxi_gap_analysis") if isinstance(project.get("tanxi_gap_analysis"), Mapping) else {}
        candidates = tanxi.get("ranked_gaps") if isinstance(tanxi.get("ranked_gaps"), list) else []
        candidate = next(
            (
                item for item in candidates
                if isinstance(item, Mapping) and str(item.get("gap_id") or "") == gap_id
            ),
            None,
        )
        if candidate is None:
            return _blocked(project, "BLOCKED_INVALID_UPSTREAM_ARTIFACT", "UNKNOWN_OR_UNPERSISTED_GAP_ID", name)
        try:
            route = assessment_of(dict(candidate)).get("route")
        except ValueError:
            return _blocked(project, "BLOCKED_INVALID_UPSTREAM_ARTIFACT", "NON_V2_GAP_CANDIDATE", name)
        if route != GapRoute.TARGETED_RETRIEVAL.value:
            return _blocked(project, "BLOCKED_INVALID_UPSTREAM_ARTIFACT", "GAP_IS_NOT_ON_TARGETED_RETRIEVAL_ROUTE", name)
        work_item = (
            candidate.get("retrieval_work_item_v3")
            if isinstance(candidate.get("retrieval_work_item_v3"), Mapping)
            else {}
        )
        retrieval_state = (
            candidate.get("gap_resolution_retrieval")
            if isinstance(candidate.get("gap_resolution_retrieval"), Mapping)
            else {}
        )
        if str(retrieval_state.get("status") or "") == "PENDING_SLOT_BINDING":
            return _blocked(project, "BLOCKED_UPSTREAM", "GAP_RESOLUTION_SLOT_BINDING_REQUIRED", name)
        if str(retrieval_state.get("status") or "") == "PENDING_GRAPH_SNAPSHOT":
            return _blocked(project, "BLOCKED_UPSTREAM", "GAP_RESOLUTION_CURRENT_GRAPH_SNAPSHOT_REQUIRED", name)
        try:
            validated_work_item = validate_retrieval_work_item_v3(work_item)
        except (TypeError, ValueError):
            return _blocked(project, "BLOCKED_INVALID_UPSTREAM_ARTIFACT", "GAP_RESOLUTION_WORK_ITEM_V3_REQUIRED", name)
        if (
            str(validated_work_item.get("work_item_kind") or "") != "GAP_RESOLUTION"
            or str(validated_work_item.get("gap_candidate_id") or "")
            != str(candidate.get("candidate_identity") or "")
        ):
            return _blocked(project, "BLOCKED_INVALID_UPSTREAM_ARTIFACT", "GAP_RESOLUTION_WORK_ITEM_BINDING_MISMATCH", name)
        if name not in set(state.get("allowed_next_stages") or []):
            return _blocked(project, "BLOCKED_UPSTREAM", "TANXI_HAS_NOT_AUTHORIZED_TYPE_DIRECTED_RETRIEVAL", name)
        return {"allowed": True, "execution_key": execution_key}

    if name == TYPE_SPECIFIC_SOCRATES_REVIEW_STAGE:
        try:
            from ._gap_types import is_primary_research_candidate
        except ImportError:
            from _gap_types import is_primary_research_candidate
        gap_id = str((tool_input or {}).get("gap_id") or "").strip()
        package = next(
            (
                item for item in project.get("research_packages", [])
                if isinstance(item, Mapping) and str(item.get("gap_id") or "") == gap_id
            ),
            None,
        )
        tanxi = project.get("tanxi_gap_analysis") if isinstance(project.get("tanxi_gap_analysis"), Mapping) else {}
        candidate = next(
            (
                item for item in tanxi.get("ranked_gaps", [])
                if isinstance(item, Mapping) and str(item.get("gap_id") or "") == gap_id
            ),
            None,
        )
        if not isinstance(package, Mapping) or not isinstance(candidate, Mapping):
            return _blocked(project, "BLOCKED_INVALID_UPSTREAM_ARTIFACT", "NO_QUALIFIED_TYPE_SPECIFIC_PACKAGE", name)
        try:
            qualified = is_primary_research_candidate(dict(candidate))
        except ValueError:
            qualified = False
        if not qualified:
            return _blocked(project, "BLOCKED_INVALID_UPSTREAM_ARTIFACT", "GAP_IS_NOT_QUALIFIED_PRIMARY_RESEARCH", name)
        # TanXi can admit several heterogeneous primary ResearchPackages in a
        # single run.  Completing the review for one package must not erase
        # the authorization for its siblings merely because the current
        # workflow record becomes that first review result.
        authorized_gap_ids = {
            str(value)
            for value in (state.get("artifact_ids") or [])
            if str(value)
        }
        history = state.get("history") if isinstance(state.get("history"), list) else []
        for entry in history:
            if not isinstance(entry, Mapping):
                continue
            if name not in set(entry.get("allowed_next_stages") or []):
                continue
            authorized_gap_ids.update(
                str(value) for value in (entry.get("artifact_ids") or []) if str(value)
            )
        if gap_id not in authorized_gap_ids:
            return _blocked(project, "BLOCKED_UPSTREAM", "TANXI_HAS_NOT_AUTHORIZED_TYPE_SPECIFIC_SOCRATES_REVIEW", name)
        return {"allowed": True, "execution_key": execution_key}

    if name == PROPOSAL_BRIEF_STAGE:
        package_id = str((tool_input or {}).get("research_package_id") or "").strip()
        package = next(
            (
                item for item in project.get("research_packages", [])
                if isinstance(item, Mapping) and str(item.get("research_package_id") or "") == package_id
            ),
            None,
        )
        if not isinstance(package, Mapping) or str(package.get("schema_version") or "") != "research_package_v2":
            return _blocked(project, "BLOCKED_INVALID_UPSTREAM_ARTIFACT", "CURRENT_RESEARCH_PACKAGE_V2_REQUIRED", name)
        if str(package.get("lifecycle_status") or "CURRENT") != "CURRENT":
            return _blocked(project, "BLOCKED_INVALID_UPSTREAM_ARTIFACT", "RESEARCH_PACKAGE_STALE_GRAPH", name)
        review = (project.get("socrates_type_reviews") or {}).get(str(package.get("gap_id") or "")) if isinstance(project.get("socrates_type_reviews"), Mapping) else {}
        if not isinstance(review, Mapping) or review.get("review_ready") is not True:
            return _blocked(project, "BLOCKED_UPSTREAM", "TYPE_SPECIFIC_SOCRATES_REVIEW_NOT_READY_FOR_PROPOSAL", name)
        # The persisted ready review is the authority.  Several qualified
        # packages may share a run, so a later sibling review must not erase
        # an earlier package's authorization merely by becoming the current
        # workflow status.
        if terminal:
            return _blocked(project, "BLOCKED_UPSTREAM", "WORKFLOW_TERMINAL_BEFORE_PROPOSAL_BRIEF", name)
        return {"allowed": True, "execution_key": execution_key}

    if name == PROPOSAL_WRITER_STAGE:
        brief_id = str((tool_input or {}).get("proposal_brief_id") or "").strip()
        brief = next(
            (
                item for item in project.get("proposal_briefs", [])
                if isinstance(item, Mapping) and str(item.get("proposal_brief_id") or "") == brief_id
            ),
            None,
        )
        if not isinstance(brief, Mapping) or str(brief.get("schema_version") or "") != "proposal_brief_v2":
            return _blocked(project, "BLOCKED_INVALID_UPSTREAM_ARTIFACT", "CURRENT_PROPOSAL_BRIEF_V2_REQUIRED", name)
        if str(brief.get("lifecycle_status") or "CURRENT") != "CURRENT":
            return _blocked(project, "BLOCKED_INVALID_UPSTREAM_ARTIFACT", "PROPOSAL_BRIEF_STALE", name)
        if terminal:
            return _blocked(project, "BLOCKED_UPSTREAM", "WORKFLOW_TERMINAL_BEFORE_PROPOSAL_WRITING", name)
        return {"allowed": True, "execution_key": execution_key}

    if name == PROPOSAL_AUDIT_STAGE:
        proposal_id = str((tool_input or {}).get("proposal_id") or "").strip()
        proposal = next(
            (
                item for item in project.get("research_proposals", [])
                if isinstance(item, Mapping) and str(item.get("proposal_id") or "") == proposal_id
            ),
            None,
        )
        if not isinstance(proposal, Mapping) or str(proposal.get("schema_version") or "") != "research_proposal_v2":
            return _blocked(project, "BLOCKED_INVALID_UPSTREAM_ARTIFACT", "CURRENT_RESEARCH_PROPOSAL_V2_REQUIRED", name)
        if str(proposal.get("lifecycle_status") or "") != "DRAFT_REQUIRES_AUDIT":
            return _blocked(project, "BLOCKED_INVALID_UPSTREAM_ARTIFACT", "PROPOSAL_IS_NOT_A_CURRENT_AUDITABLE_DRAFT", name)
        if terminal:
            return _blocked(project, "BLOCKED_UPSTREAM", "WORKFLOW_TERMINAL_BEFORE_PROPOSAL_AUDIT", name)
        return {"allowed": True, "execution_key": execution_key}

    if name == SOCRATES_TOOL:
        gap_id = str((tool_input or {}).get("gap_id") or "").strip()
        if not gap_id or gap_id not in known_gap_ids:
            return _blocked(project, "BLOCKED_INVALID_UPSTREAM_ARTIFACT", "UNKNOWN_OR_UNPERSISTED_GAP_ID", name)
        if name not in set(state.get("allowed_next_stages") or []):
            return _blocked(project, "BLOCKED_UPSTREAM", "TANXI_HAS_NOT_AUTHORIZED_SOCRATES", name)
        return {"allowed": True, "execution_key": execution_key}

    if name == MINGLI_TOOL:
        ready_ids = ready_socrates_gap_ids(project)
        restricted_ready_ids = ready_restricted_component_bridge_gap_ids(project)
        ready_handoff_ids = ready_ids | restricted_ready_ids
        if not ready_handoff_ids:
            return _blocked(project, "BLOCKED_NO_READY_HANDOFF", "NO_READY_SOCRATES_HANDOFF", name)
        requested = {
            str(value)
            for value in ((tool_input or {}).get("gap_ids") or [])
            if str(value)
        }
        if requested and not requested.intersection(ready_handoff_ids):
            return _blocked(project, "BLOCKED_NO_READY_HANDOFF", "REQUESTED_GAPS_HAVE_NO_READY_SOCRATES_HANDOFF", name)
        if ready_ids:
            if (
                current_status != "TYPE_SPECIFIC_REVIEW_COMPLETE_READY_FOR_MINGLI"
                or name not in set(state.get("allowed_next_stages") or [])
            ):
                return _blocked(
                    project,
                    "BLOCKED_UPSTREAM",
                    "TYPE_SPECIFIC_CAUSAL_REVIEW_NOT_COMPLETE",
                    name,
                )
        return {"allowed": True, "execution_key": execution_key}

    return {"allowed": True, "execution_key": execution_key}


def record_workflow_execution(
    project: dict[str, Any],
    tool_name: str,
    tool_input: Mapping[str, Any] | None,
    result: Mapping[str, Any],
    *,
    execution_key: str | None = None,
) -> None:
    if tool_name not in WORKFLOW_TOOLS:
        return
    control = workflow_control(project)
    key = str(execution_key or workflow_execution_key(project, tool_name, tool_input))
    executions = control.setdefault("executions", {})
    if not isinstance(executions, dict):
        executions = {}
        control["executions"] = executions
    executions[key] = {
        "tool_name": tool_name,
        "status": str(result.get("status") or "completed"),
        "terminal": bool(result.get("terminal")),
        "allowed_next_stages": list(result.get("allowed_next_stages") or []),
        "artifact_ids": list(result.get("artifact_ids") or []),
        "remediation_plan": dict(result.get("remediation_plan") or {}),
        "recorded_state_version": int(project.get("state_version") or 0),
        "recorded_at": time.time(),
    }
    if len(executions) > 80:
        oldest = sorted(
            executions,
            key=lambda item: float(executions[item].get("recorded_at") or 0),
        )[: len(executions) - 80]
        for stale_key in oldest:
            executions.pop(stale_key, None)


def compact_workflow_tool_output(tool_name: str, output: str) -> str:
    """Return a small model-facing decision while keeping full reports persisted."""

    if tool_name not in WORKFLOW_TOOLS:
        return output
    try:
        payload = json.loads(output)
    except (TypeError, json.JSONDecodeError):
        return output
    if not isinstance(payload, Mapping):
        return output
    summary = {
        key: payload.get(key)
        for key in (
            "status", "terminal", "project_id", "state_version", "reason_code",
            "allowed_next_stages", "blocked_stages", "remediation_plan", "artifact_ids",
            "verdict", "next_step", "final_decision", "gap_id",
        )
        if key in payload
    }
    if tool_name == TANXI_TOOL:
        summary.update(
            {
                "ranked_gap_count": len(payload.get("ranked_gaps") or []),
                "primary_research_candidate_count": len(payload.get("primary_research_candidates") or []),
                "primary_mechanism_candidate_count": len(payload.get("primary_mechanism_candidates") or []),
                "targeted_retrieval_candidate_count": len(payload.get("targeted_retrieval_candidates") or []),
                "evidence_extraction_shortage_count": len(payload.get("evidence_extraction_shortages") or []),
                "artifact_ref": {"project_id": payload.get("project_id"), "path": "tanxi_gap_analysis"},
            }
        )
    elif tool_name == SOCRATES_TOOL:
        summary["artifact_ref"] = {"project_id": payload.get("project_id"), "path": "socrates_mechanism_contracts"}
    elif tool_name == TYPE_SPECIFIC_SOCRATES_REVIEW_STAGE:
        summary.update(
            {
                "review_mode": payload.get("review_mode"),
                "review_ready": bool(payload.get("review_ready")),
                "artifact_ref": {"project_id": payload.get("project_id"), "path": "socrates_type_reviews"},
            }
        )
    elif tool_name == PROPOSAL_BRIEF_STAGE:
        summary["proposal_brief_id"] = payload.get("proposal_brief_id")
        summary["proposal_kind"] = payload.get("proposal_kind")
        summary["artifact_ref"] = {"project_id": payload.get("project_id"), "path": "proposal_briefs"}
    elif tool_name == PROPOSAL_WRITER_STAGE:
        summary["proposal_id"] = payload.get("proposal_id")
        summary["proposal_kind"] = payload.get("proposal_kind")
        summary["artifact_ref"] = {"project_id": payload.get("project_id"), "path": "research_proposals"}
    elif tool_name == PROPOSAL_AUDIT_STAGE:
        summary["proposal_id"] = payload.get("proposal_id")
        summary["passes"] = payload.get("passes")
        summary["artifact_ref"] = {"project_id": payload.get("project_id"), "path": "proposal_audits"}
    elif tool_name == MINGLI_TOOL:
        summary["hypothesis_count"] = len(payload.get("top_hypotheses") or [])
        summary["artifact_ref"] = {"project_id": payload.get("project_id"), "path": "mingli_hypothesis_evolution_runs"}
    return json.dumps(summary, ensure_ascii=False, indent=2)


def canonical_gap_ids(project: Mapping[str, Any]) -> set[str]:
    tanxi = project.get("tanxi_gap_analysis") if isinstance(project.get("tanxi_gap_analysis"), Mapping) else {}
    candidates = list(tanxi.get("ranked_gaps") or []) + list(project.get("knowledge_gaps") or [])
    ids: set[str] = set()
    for item in candidates:
        if not isinstance(item, Mapping):
            continue
        gap_id = str(item.get("gap_id") or "").strip()
        if gap_id:
            ids.add(gap_id)
        ids.update(str(alias).strip() for alias in (item.get("merged_gap_ids") or []) if str(alias).strip())
    return ids


def ready_socrates_gap_ids(project: Mapping[str, Any]) -> set[str]:
    """Return currently qualified v2 causal gaps admitted to hypothesis work.

    The historical name remains because the MingLi gate imports it, but it no
    longer consults Socrates contracts or old readiness fields.  Socrates is a
    bounded audit/retrieval participant, not a backdoor qualification gate.
    """
    try:
        from ._gap_types import is_primary_mechanism_candidate
    except ImportError:
        from _gap_types import is_primary_mechanism_candidate
    tanxi = project.get("tanxi_gap_analysis") if isinstance(project.get("tanxi_gap_analysis"), Mapping) else {}
    candidates = tanxi.get("ranked_gaps") if isinstance(tanxi.get("ranked_gaps"), list) else []
    ready: set[str] = set()
    for item in candidates:
        if not isinstance(item, Mapping):
            continue
        try:
            if is_primary_mechanism_candidate(dict(item)) and str(item.get("gap_id") or ""):
                ready.add(str(item.get("gap_id") or ""))
        except ValueError:
            continue
    return ready


def ready_restricted_component_bridge_gap_ids(project: Mapping[str, Any]) -> set[str]:
    """Return TanXi-approved bridge gaps that go to MingLi before Socrates.

    These are not primary scientific gaps.  They are admitted only to the
    capped MingLi track, where the hypothesis package requires post-draft
    Socrates enrichment and preserves a no-final-object-claim disclaimer.
    """
    tanxi = project.get("tanxi_gap_analysis") if isinstance(project.get("tanxi_gap_analysis"), Mapping) else {}
    candidates = list(project.get("knowledge_gaps") or []) + list(tanxi.get("ranked_gaps") or [])
    control = project.get(WORKFLOW_CONTROL_KEY)
    control = control if isinstance(control, Mapping) else {}
    authorized_by_tanxi = bool(
        str(control.get("status") or "") == "READY_FOR_RESTRICTED_BRIDGE_MINGLI"
        and MINGLI_TOOL in set(control.get("allowed_next_stages") or [])
    )
    if not authorized_by_tanxi:
        return set()
    return {
        str(item.get("gap_id") or "")
        for item in candidates
        if isinstance(item, Mapping)
        and str(item.get("gap_id") or "")
        and (
            item.get("restricted_component_bridge_hypothesis_allowed") is True
            or item.get("component_bridge_gap_synthesis_ready") is True
        )
        and restricted_component_bridge_role_contract_ready(item)
        and (
            (item.get("hypothesis_readiness") or {}).get("ready_for_hypothesis_generation") is True
            or str((item.get("hypothesis_readiness") or {}).get("status") or "")
            == "READY_FOR_RESTRICTED_BRIDGE_HYPOTHESIS"
        )
    }


def _contract_readiness_status(value: Any) -> str:
    contract = value if isinstance(value, Mapping) else {}
    readiness = contract.get("hypothesis_readiness") if isinstance(contract.get("hypothesis_readiness"), Mapping) else {}
    return str(
        readiness.get("contract_status")
        or contract.get("verdict")
        or contract.get("status")
        or ""
    )


def _blocked(project: Mapping[str, Any], status: str, reason_code: str, blocked_stage: str) -> dict[str, Any]:
    return {
        "allowed": False,
        "result": workflow_result(
            project,
            status=status,
            terminal=True,
            reason_code=reason_code,
            allowed_next_stages=[],
            blocked_stages=[blocked_stage],
            remediation_plan={},
            artifact_ids=[],
        ),
    }
