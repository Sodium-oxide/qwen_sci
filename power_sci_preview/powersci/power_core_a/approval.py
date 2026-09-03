"""Hash-bound approval gate used before protocol freezing (M17)."""

from __future__ import annotations

from typing import Any

from .errors import ApprovalRequired
from .schema_registry import SchemaRegistry


def require_protocol_approval(
    approval: dict[str, Any],
    *,
    run_id: str,
    protocol_hash: str,
    registry: SchemaRegistry | None = None,
) -> dict[str, Any]:
    checked = (registry or SchemaRegistry()).validate("ApprovalRecord", approval)
    if checked["run_id"] != run_id:
        raise ApprovalRequired(
            "Approval belongs to a different run",
            context={"expected_run_id": run_id, "observed_run_id": checked["run_id"]},
        )
    if checked["decision"] != "APPROVED":
        raise ApprovalRequired("Protocol freeze was not approved", context={"decision": checked["decision"]})
    if checked["subject_artifact_hash"] != protocol_hash:
        raise ApprovalRequired(
            "Approval is stale because the protocol hash changed",
            context={"expected_hash": protocol_hash, "approved_hash": checked["subject_artifact_hash"]},
        )
    return checked

