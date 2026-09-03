"""Deterministic state-to-task routing (M01)."""

from __future__ import annotations

from typing import Any

from .schema_registry import SchemaRegistry
from .state_machine import ResearchState, utc_now


_ROUTES: dict[ResearchState, tuple[str, str, list[str]]] = {
    ResearchState.BRIEF_DRAFT: ("VALIDATE_RESEARCH_BRIEF", "M00", ["ResearchBrief"]),
    ResearchState.BRIEF_VALIDATED: ("BIND_CASE", "M01", ["CaseManifest", "EquationIR", "LensSpec"]),
    ResearchState.CASE_BOUND: ("DRAFT_PROTOCOL", "M01", ["ExperimentProtocol"]),
    ResearchState.PROTOCOL_DRAFT: ("REQUEST_APPROVAL", "M17", ["ApprovalRecord"]),
    ResearchState.APPROVAL_PENDING: ("FREEZE_PROTOCOL", "M17", ["ExperimentProtocol"]),
    ResearchState.PROTOCOL_FROZEN: ("BUILD_RESULT_BUNDLE", "M15", ["RunManifest", "ResultBundleManifest"]),
}


def route_next_task(
    *,
    run_id: str,
    state: ResearchState,
    input_artifacts: list[dict[str, Any]],
    created_at: str | None = None,
    registry: SchemaRegistry | None = None,
) -> dict[str, Any]:
    task_type, owner_module, expected = _ROUTES[state]
    compact_refs = [
        {
            "artifact_id": item["artifact_id"],
            "artifact_type": item["artifact_type"],
            "content_hash": item["content_hash"],
            "relative_path": item["relative_path"],
        }
        for item in input_artifacts
    ]
    task = {
        "schema_version": "task_envelope_v1",
        "task_id": f"task_{run_id}_{state.value.lower()}",
        "run_id": run_id,
        "task_type": task_type,
        "owner_module": owner_module,
        "required_state": state.value,
        "input_artifacts": compact_refs,
        "expected_output_schemas": expected,
        "idempotency_key": f"route:{run_id}:{state.value}",
        "created_at": created_at or utc_now(),
    }
    return (registry or SchemaRegistry()).validate("TaskEnvelope", task)

