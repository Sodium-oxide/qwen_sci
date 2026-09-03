"""Build explicit child documents for PDE grid and time-step studies."""

from __future__ import annotations

import copy
import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from typing import Any

from src.agents.quantitative_modeling.pdeir import PDEIRValidationError, validate_pdeir_document


class PDEConvergenceError(ValueError):
    """Raised when a refinement study cannot be planned safely."""


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _canonical(value: Mapping[str, object]) -> str:
    return json.dumps(dict(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _fingerprint(value: Mapping[str, object]) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _integer_levels(value: Sequence[int], *, name: str) -> tuple[int, ...]:
    levels = tuple(int(item) for item in value)
    if not levels or any(item < 1 for item in levels) or len(set(levels)) != len(levels):
        raise PDEConvergenceError(f"{name} must contain distinct positive integers")
    return levels


def _resample_field(
    values: Sequence[float],
    *,
    old_nx: int,
    old_ny: int | None,
    old_nz: int | None,
    new_nx: int,
    new_ny: int | None,
    new_nz: int | None,
) -> list[float]:
    old_values = [float(item) for item in values]
    if old_ny is None and old_nz is None and new_ny is None and new_nz is None:
        result: list[float] = []
        for new_index in range(new_nx):
            position = new_index * (old_nx - 1) / (new_nx - 1)
            left = min(int(position), old_nx - 2)
            weight = position - left
            result.append(old_values[left] * (1.0 - weight) + old_values[left + 1] * weight)
        return result
    if old_nz is None and new_nz is None:
        if old_ny is None or new_ny is None or len(old_values) != old_nx * old_ny:
            raise PDEConvergenceError("field dimensions do not match the refinement grid")
        result = []
        for new_j in range(new_ny):
            y_position = new_j * (old_ny - 1) / (new_ny - 1)
            lower_j = min(int(y_position), old_ny - 2)
            y_weight = y_position - lower_j
            for new_i in range(new_nx):
                x_position = new_i * (old_nx - 1) / (new_nx - 1)
                lower_i = min(int(x_position), old_nx - 2)
                x_weight = x_position - lower_i
                lower = lower_j * old_nx + lower_i
                upper = (lower_j + 1) * old_nx + lower_i
                result.append(
                    old_values[lower] * (1.0 - x_weight) * (1.0 - y_weight)
                    + old_values[lower + 1] * x_weight * (1.0 - y_weight)
                    + old_values[upper] * (1.0 - x_weight) * y_weight
                    + old_values[upper + 1] * x_weight * y_weight
                )
        return result
    if (
        old_ny is None
        or new_ny is None
        or old_nz is None
        or new_nz is None
        or len(old_values) != old_nx * old_ny * old_nz
    ):
        raise PDEConvergenceError("field dimensions do not match the refinement grid")
    result = []
    for new_k in range(new_nz):
        z_position = new_k * (old_nz - 1) / (new_nz - 1)
        lower_k = min(int(z_position), old_nz - 2)
        z_weight = z_position - lower_k
        for new_j in range(new_ny):
            y_position = new_j * (old_ny - 1) / (new_ny - 1)
            lower_j = min(int(y_position), old_ny - 2)
            y_weight = y_position - lower_j
            for new_i in range(new_nx):
                x_position = new_i * (old_nx - 1) / (new_nx - 1)
                lower_i = min(int(x_position), old_nx - 2)
                x_weight = x_position - lower_i

                def offset(i: int, j: int, k: int) -> int:
                    return i + old_nx * (j + old_ny * k)

                value = 0.0
                for z_index, z_factor in ((lower_k, 1.0 - z_weight), (lower_k + 1, z_weight)):
                    for y_index, y_factor in ((lower_j, 1.0 - y_weight), (lower_j + 1, y_weight)):
                        for x_index, x_factor in ((lower_i, 1.0 - x_weight), (lower_i + 1, x_weight)):
                            value += old_values[offset(x_index, y_index, z_index)] * z_factor * y_factor * x_factor
                result.append(value)
    return result


def build_refinement_documents(
    document: Mapping[str, object],
    *,
    grid_multipliers: Sequence[int] = (1, 2, 4),
    time_step_divisors: Sequence[int] = (1,),
) -> list[dict[str, Any]]:
    """Create validated child PDEIR documents; this function never executes them."""

    try:
        normalized = validate_pdeir_document(document)
    except PDEIRValidationError as exc:
        raise PDEConvergenceError(f"parent PDE document is invalid: {exc}") from exc
    grid_levels = _integer_levels(grid_multipliers, name="grid_multipliers")
    time_levels = _integer_levels(time_step_divisors, name="time_step_divisors")
    parent_fingerprint = _fingerprint(normalized)
    children: list[dict[str, Any]] = []
    for grid_multiplier in grid_levels:
        for time_step_divisor in time_levels:
            child = copy.deepcopy(normalized)
            parent_grid = dict(normalized["grid"])
            grid = dict(child["grid"])
            grid["nx"] = (int(grid["nx"]) - 1) * grid_multiplier + 1
            if "ny" in grid:
                grid["ny"] = (int(grid["ny"]) - 1) * grid_multiplier + 1
            if "nz" in grid:
                grid["nz"] = (int(grid["nz"]) - 1) * grid_multiplier + 1
            child["grid"] = grid
            for initial_name in ("initial_condition", "initial_velocity"):
                initial = dict(child.get(initial_name) or {})
                if "values" not in initial:
                    continue
                initial["values"] = _resample_field(
                    initial["values"],
                    old_nx=int(parent_grid["nx"]),
                    old_ny=int(parent_grid["ny"]) if "ny" in parent_grid else None,
                    old_nz=int(parent_grid["nz"]) if "nz" in parent_grid else None,
                    new_nx=int(grid["nx"]),
                    new_ny=int(grid["ny"]) if "ny" in grid else None,
                    new_nz=int(grid["nz"]) if "nz" in grid else None,
                )
                child[initial_name] = initial
            options = dict(child.get("solver_options") or {})
            if "time_step" in options:
                options["time_step"] = float(options["time_step"]) / time_step_divisor
                child["solver_options"] = options
            child = validate_pdeir_document(child)
            refinement_id = f"grid-{grid_multiplier}-dt-{time_step_divisor}"
            children.append(
                {
                    "refinement_id": refinement_id,
                    "parent_document_sha256": parent_fingerprint,
                    "grid_multiplier": grid_multiplier,
                    "time_step_divisor": time_step_divisor,
                    "requires_new_execution": True,
                    "document": child,
                }
            )
    return children


def build_refinement_plans(
    parent_plan: Mapping[str, object],
    *,
    grid_multipliers: Sequence[int] = (1, 2, 4),
    time_step_divisors: Sequence[int] = (1,),
) -> list[dict[str, Any]]:
    """Build new identity-bound plans without authorizing any execution."""

    from src.agents.quantitative_modeling.run_plan import (
        SimulationRunPlanError,
        build_simulation_run_plan,
        validate_simulation_run_plan,
    )

    try:
        normalized_plan = validate_simulation_run_plan(parent_plan)
    except SimulationRunPlanError as exc:
        raise PDEConvergenceError(f"parent simulation plan is invalid: {exc}") from exc
    execution_ir = normalized_plan.get("execution_ir")
    if not isinstance(execution_ir, Mapping) or execution_ir.get("kind") != "PDE":
        raise PDEConvergenceError("convergence refinement requires a PDE execution plan")
    documents = build_refinement_documents(
        _mapping(execution_ir.get("document")),
        grid_multipliers=grid_multipliers,
        time_step_divisors=time_step_divisors,
    )
    plans: list[dict[str, Any]] = []
    for child in documents:
        refinement_id = str(child["refinement_id"])
        identity = {
            **dict(_mapping(normalized_plan.get("model_identity"))),
            "parent_plan_identity": str(normalized_plan["plan_identity"]),
            "refinement_id": refinement_id,
        }
        plans.append(
            build_simulation_run_plan(
                model_identity=identity,
                execution_ir={
                    "kind": "PDE",
                    "schema_version": "execution_ir_v1",
                    "document": child["document"],
                },
                scenarios=normalized_plan.get("scenarios"),
                resource_limits=normalized_plan.get("resource_limits"),
                qualification_requirements=normalized_plan.get("qualification_requirements"),
                parameter_provenance=normalized_plan.get("parameter_provenance"),
            )
        )
    return plans


def estimate_convergence_order(errors: Sequence[float], resolutions: Sequence[float]) -> float:
    """Estimate a log-log convergence order from at least two error levels."""

    if len(errors) != len(resolutions) or len(errors) < 2:
        raise PDEConvergenceError("errors and resolutions need at least two matching entries")
    if any(float(error) <= 0 for error in errors) or any(float(value) <= 0 for value in resolutions):
        raise PDEConvergenceError("errors and resolutions must be positive")
    first_error, last_error = float(errors[0]), float(errors[-1])
    first_resolution, last_resolution = float(resolutions[0]), float(resolutions[-1])
    denominator = last_resolution / first_resolution
    if denominator <= 1:
        raise PDEConvergenceError("the final resolution must exceed the initial resolution")
    order = math.log(first_error / last_error) / math.log(denominator)
    if not math.isfinite(order):
        raise PDEConvergenceError("convergence order is not finite")
    return order


__all__ = [
    "PDEConvergenceError",
    "build_refinement_documents",
    "build_refinement_plans",
    "estimate_convergence_order",
]
