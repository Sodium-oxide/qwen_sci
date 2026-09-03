"""Explicitly authorized execution of fixed numerical solvers.

The runner accepts only an audited MathIR plan. It never evaluates model text,
imports user-selected modules, executes shell commands, or accesses a network.
"""

from __future__ import annotations

import copy
import time
import uuid
from collections.abc import Mapping
from typing import Any

from src.agents.quantitative_modeling.run_plan import (
    SimulationRunPlanError,
    validate_simulation_run_plan,
)
from src.agents.quantitative_modeling.execution_ir import execute_execution_ir
from src.agents.quantitative_modeling.pde_solver import PDESolverError
from src.agents.quantitative_modeling.pde_verification import PDEVerificationError, verify_pde_result
from src.agents.quantitative_modeling.solver_registry import NumericalSolverError, execute_mathir


SIMULATION_EXECUTION_SCHEMA_VERSION = "simulation_execution_v1"


class SimulationAuthorizationError(PermissionError):
    """Raised unless the caller explicitly authorizes the exact execution plan."""


class SimulationExecutionError(RuntimeError):
    """Raised when an authorized execution cannot safely complete."""


def _apply_scenario(mathir: Mapping[str, object], scenario: Mapping[str, object]) -> dict[str, Any]:
    materialized = copy.deepcopy(dict(mathir))
    overrides = dict(scenario.get("parameter_overrides") or {})
    if overrides:
        parameters = dict(materialized.get("parameters") or {})
        parameters.update(overrides)
        materialized["parameters"] = parameters
    return materialized


def _apply_execution_scenario(execution_ir: Mapping[str, object], scenario: Mapping[str, object]) -> dict[str, Any]:
    materialized = copy.deepcopy(dict(execution_ir))
    document = dict(materialized.get("document") or {})
    overrides = dict(scenario.get("parameter_overrides") or {})
    if overrides:
        parameters = dict(document.get("parameters") or {})
        parameters.update(overrides)
        document["parameters"] = parameters
    materialized["document"] = document
    return materialized


def execute_simulation_run_plan(
    plan: Mapping[str, object],
    *,
    execute: bool = False,
    confirmed_plan_identity: str | None = None,
) -> dict[str, Any]:
    """Execute a plan only after explicit, identity-bound caller authorization."""

    try:
        normalized = validate_simulation_run_plan(plan)
    except SimulationRunPlanError as exc:
        raise SimulationExecutionError(f"simulation plan validation failed: {exc}") from exc
    plan_identity = str(normalized["plan_identity"])
    if not execute:
        raise SimulationAuthorizationError("simulation requires explicit --execute authorization")
    if str(confirmed_plan_identity or "").strip() != plan_identity:
        raise SimulationAuthorizationError("confirmed plan identity does not match the execution plan")
    started = time.monotonic()
    scenario_results: list[dict[str, Any]] = []
    for scenario in normalized["scenarios"]:
        elapsed = time.monotonic() - started
        if elapsed > normalized["resource_limits"]["max_wall_seconds"]:
            raise SimulationExecutionError("authorized simulation exceeded its wall-clock limit")
        try:
            if normalized.get("execution_ir"):
                result = execute_execution_ir(
                    _apply_execution_scenario(normalized["execution_ir"], scenario),
                    resource_limits=normalized["resource_limits"],
                )
                if normalized["execution_ir"]["kind"] == "PDE":
                    materialized_ir = _apply_execution_scenario(normalized["execution_ir"], scenario)
                    result["verification"] = verify_pde_result(
                        result,
                        document=materialized_ir["document"],
                    )
            else:
                result = execute_mathir(
                    _apply_scenario(normalized["mathir"], scenario),
                    resource_limits=normalized["resource_limits"],
                )
        except (NumericalSolverError, PDESolverError, PDEVerificationError) as exc:
            raise SimulationExecutionError(
                f"scenario {scenario['scenario_id']} failed: {exc}"
            ) from exc
        scenario_results.append({"scenario_id": scenario["scenario_id"], "result": result})
    elapsed_seconds = time.monotonic() - started
    if elapsed_seconds > normalized["resource_limits"]["max_wall_seconds"]:
        raise SimulationExecutionError("authorized simulation exceeded its wall-clock limit")
    return {
        "schema_version": SIMULATION_EXECUTION_SCHEMA_VERSION,
        "execution_id": f"sim-{uuid.uuid4().hex}",
        "status": "COMPLETED",
        "execution_mode": "NUMERICAL_SIMULATION",
        "result_kind": "SIMULATED",
        "empirical_claim_status": "NOT_EMPIRICAL",
        "execution_ir_kind": "PDE" if normalized.get("execution_ir") else "MATHIR",
        "plan_identity": plan_identity,
        "model_identity": normalized["model_identity"],
        "authorization": {
            "execute": True,
            "confirmed_plan_identity": confirmed_plan_identity,
        },
        "elapsed_seconds": elapsed_seconds,
        "scenario_results": scenario_results,
    }


__all__ = [
    "SIMULATION_EXECUTION_SCHEMA_VERSION",
    "SimulationAuthorizationError",
    "SimulationExecutionError",
    "execute_simulation_run_plan",
]
