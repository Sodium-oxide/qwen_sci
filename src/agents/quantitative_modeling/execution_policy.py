"""Execution-policy helpers for immutable, explicitly authorized numerical plans."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from src.pipeline.science_run import utc_now


EXECUTION_AUTHORIZATION_SCHEMA_VERSION = "simulation_execution_authorization_v1"


class ExecutionPolicyError(ValueError):
    """Raised when an execution artifact is not bound to one approved plan."""


def build_execution_authorization(*, plan: Mapping[str, object], confirmed_plan_identity: str) -> dict[str, Any]:
    """Record the human CLI authorization without granting a reusable permission."""

    plan_identity = str(plan.get("plan_identity") or "").strip()
    if not plan_identity or confirmed_plan_identity != plan_identity:
        raise ExecutionPolicyError("execution authorization must confirm the exact plan identity")
    return {
        "schema_version": EXECUTION_AUTHORIZATION_SCHEMA_VERSION,
        "authorized_at": utc_now(),
        "execution_mode": "NUMERICAL_SIMULATION",
        "execute": True,
        "plan_identity": plan_identity,
        "confirmed_plan_identity": confirmed_plan_identity,
        "model_identity": dict(plan.get("model_identity") or {}),
    }


__all__ = [
    "EXECUTION_AUTHORIZATION_SCHEMA_VERSION",
    "ExecutionPolicyError",
    "build_execution_authorization",
]
