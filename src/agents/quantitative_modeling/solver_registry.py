"""Fixed numerical solver adapters for validated MathIR documents."""

from __future__ import annotations

import math
import random
from collections.abc import Mapping
from typing import Any

from src.agents.quantitative_modeling.mathir import (
    MathIREvaluationError,
    evaluate_expression,
    validate_mathir_document,
)


class NumericalSolverError(RuntimeError):
    """Raised when an approved solver cannot complete a validated run."""


SOLVER_BY_SYSTEM_TYPE = {
    "ODE_IVP": "scipy_solve_ivp",
    "LINEAR_OPTIMIZATION": "scipy_linprog",
    "MONTE_CARLO": "stdlib_monte_carlo",
    "DIFFUSION_REACTION_1D": "explicit_fd_diffusion_reaction_1d",
}


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _positive_int(value: object, *, field: str) -> int:
    if isinstance(value, bool):
        raise NumericalSolverError(f"{field} must be an integer")
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise NumericalSolverError(f"{field} must be an integer") from exc
    if result < 1:
        raise NumericalSolverError(f"{field} must be positive")
    return result


def solver_is_available(system_type: str) -> bool:
    """Report whether the trusted adapter is installed in the runtime."""

    if system_type in {"MONTE_CARLO", "DIFFUSION_REACTION_1D"}:
        return True
    if system_type in {"ODE_IVP", "LINEAR_OPTIMIZATION"}:
        try:
            import scipy  # noqa: F401
        except ImportError:
            return False
        return True
    return False


def _run_ode(document: Mapping[str, object], limits: Mapping[str, object]) -> dict[str, Any]:
    try:
        import numpy as np
        from scipy.integrate import solve_ivp
    except ImportError as exc:
        raise NumericalSolverError("scipy is required for ODE_IVP simulation") from exc
    states = list(document["states"])
    state_ids = [str(state["id"]) for state in states]
    initial_values = [float(state["initial"]) for state in states]
    parameters = {str(name): float(value) for name, value in _mapping(document["parameters"]).items()}
    derivatives = _mapping(document["derivatives"])
    time_span = list(document["time_span"])
    max_step = float(_mapping(document.get("solver_options")).get("max_step"))
    max_output_points = _positive_int(limits.get("max_output_points", 2_000), field="max_output_points")
    requested_points = max(2, math.ceil((float(time_span[1]) - float(time_span[0])) / max_step) + 1)
    if requested_points > max_output_points:
        raise NumericalSolverError("ODE output grid exceeds the authorized max_output_points")
    output_times = np.linspace(float(time_span[0]), float(time_span[1]), requested_points)

    def derivative(time_value: float, state_values: Any) -> list[float]:
        environment = {"t": float(time_value), **parameters}
        environment.update({name: float(state_values[index]) for index, name in enumerate(state_ids)})
        try:
            return [evaluate_expression(_mapping(derivatives[name]), environment) for name in state_ids]
        except MathIREvaluationError as exc:
            raise NumericalSolverError(str(exc)) from exc

    result = solve_ivp(
        derivative,
        (float(time_span[0]), float(time_span[1])),
        initial_values,
        t_eval=output_times,
        max_step=max_step,
        rtol=float(limits.get("rtol", 1e-6)),
        atol=float(limits.get("atol", 1e-9)),
    )
    if not result.success:
        raise NumericalSolverError(f"ODE solver failed: {result.message}")
    state_series = {
        name: [float(value) for value in result.y[index]] for index, name in enumerate(state_ids)
    }
    final_state = {name: values[-1] for name, values in state_series.items()}
    return {
        "solver_id": "scipy_solve_ivp",
        "status": "COMPLETED",
        "time": [float(value) for value in result.t],
        "state_series": state_series,
        "summary": {
            "final_state": final_state,
            "time_points": len(result.t),
            "function_evaluations": int(result.nfev),
        },
        "numerical_checks": {"solver_converged": True},
    }


def _run_linear_optimization(document: Mapping[str, object]) -> dict[str, Any]:
    try:
        from scipy.optimize import linprog
    except ImportError as exc:
        raise NumericalSolverError("scipy is required for LINEAR_OPTIMIZATION simulation") from exc
    variables = list(document["variables"])
    variable_ids = [str(variable["id"]) for variable in variables]
    coefficients = [float(variable["objective_coefficient"]) for variable in variables]
    maximize = document.get("objective_sense") == "maximize"
    objective = [-value for value in coefficients] if maximize else coefficients
    bounds = [(float(variable["lower"]), float(variable["upper"])) for variable in variables]
    unequal_rows: list[list[float]] = []
    unequal_rhs: list[float] = []
    equal_rows: list[list[float]] = []
    equal_rhs: list[float] = []
    for constraint in document.get("constraints", []):
        payload = _mapping(constraint)
        row = [float(_mapping(payload.get("coefficients")).get(name, 0.0)) for name in variable_ids]
        sense = str(payload["sense"])
        rhs = float(payload["rhs"])
        if sense == "<=":
            unequal_rows.append(row)
            unequal_rhs.append(rhs)
        elif sense == ">=":
            unequal_rows.append([-value for value in row])
            unequal_rhs.append(-rhs)
        else:
            equal_rows.append(row)
            equal_rhs.append(rhs)
    result = linprog(
        objective,
        A_ub=unequal_rows or None,
        b_ub=unequal_rhs or None,
        A_eq=equal_rows or None,
        b_eq=equal_rhs or None,
        bounds=bounds,
        method="highs",
    )
    if not result.success or result.x is None:
        raise NumericalSolverError(f"linear optimization failed: {result.message}")
    solution = {name: float(result.x[index]) for index, name in enumerate(variable_ids)}
    value = float(result.fun)
    if maximize:
        value = -value
    return {
        "solver_id": "scipy_linprog",
        "status": "COMPLETED",
        "solution": solution,
        "summary": {"objective_value": value, "iterations": int(result.nit or 0)},
        "numerical_checks": {"solver_feasible": True},
    }


def _run_monte_carlo(document: Mapping[str, object], limits: Mapping[str, object]) -> dict[str, Any]:
    samples = int(document["samples"])
    maximum = _positive_int(limits.get("max_samples", 100_000), field="max_samples")
    if samples > maximum:
        raise NumericalSolverError("Monte Carlo samples exceed the authorized max_samples")
    generator = random.Random(int(document["seed"]))
    observations: list[float] = []
    for _ in range(samples):
        environment: dict[str, float] = {}
        for raw_variable in document["random_variables"]:
            variable = _mapping(raw_variable)
            parameters = _mapping(variable["parameters"])
            if variable["distribution"] == "uniform":
                value = generator.uniform(float(parameters["low"]), float(parameters["high"]))
            else:
                value = generator.gauss(float(parameters["mean"]), float(parameters["stddev"]))
            environment[str(variable["id"])] = value
        try:
            observations.append(evaluate_expression(_mapping(document["observable"]), environment))
        except MathIREvaluationError as exc:
            raise NumericalSolverError(str(exc)) from exc
    mean = sum(observations) / len(observations)
    variance = sum((value - mean) ** 2 for value in observations) / len(observations)
    return {
        "solver_id": "stdlib_monte_carlo",
        "status": "COMPLETED",
        "summary": {
            "sample_count": samples,
            "mean": mean,
            "standard_deviation": math.sqrt(variance),
            "minimum": min(observations),
            "maximum": max(observations),
        },
        "numerical_checks": {"sample_count_bound": True},
    }


def _run_diffusion_reaction_1d(
    document: Mapping[str, object],
    limits: Mapping[str, object],
) -> dict[str, Any]:
    """Execute a bounded explicit finite-difference diffusion--reaction solve."""

    grid_points = int(document["grid_points"])
    maximum_grid_points = _positive_int(
        limits.get("max_grid_points", 512), field="max_grid_points"
    )
    if grid_points > maximum_grid_points:
        raise NumericalSolverError("PDE grid exceeds the authorized max_grid_points")
    time_start, time_end = (float(value) for value in document["time_span"])
    requested_time_step = float(_mapping(document.get("solver_options")).get("time_step"))
    time_steps = math.ceil((time_end - time_start) / requested_time_step)
    maximum_time_steps = _positive_int(
        limits.get("max_time_steps", 20_000), field="max_time_steps"
    )
    if time_steps > maximum_time_steps:
        raise NumericalSolverError("PDE time steps exceed the authorized max_time_steps")
    domain_start, domain_end = (float(value) for value in document["spatial_domain"])
    spacing = (domain_end - domain_start) / (grid_points - 1)
    state_id = str(_mapping(document["state"])["id"])
    parameters = {str(name): float(value) for name, value in _mapping(document["parameters"]).items()}
    field = [float(value) for value in document["initial_values"]]
    diffusion_expression = _mapping(document["diffusion_coefficient"])
    reaction_expression = _mapping(document["reaction"])
    boundaries = _mapping(document["boundary_conditions"])
    maximum_snapshots = _positive_int(
        limits.get("max_pde_snapshots", 200), field="max_pde_snapshots"
    )
    snapshot_stride = max(1, math.ceil(max(1, time_steps) / max(1, maximum_snapshots - 1)))
    maximum_courant = 0.0

    def apply_boundaries(values: list[float], time_value: float) -> None:
        for side, index, coordinate in (
            ("left", 0, domain_start),
            ("right", len(values) - 1, domain_end),
        ):
            boundary = _mapping(boundaries[side])
            if boundary["type"] == "NEUMANN_ZERO":
                values[index] = values[1] if index == 0 else values[-2]
                continue
            environment = {"t": time_value, "x": coordinate, **parameters}
            try:
                values[index] = evaluate_expression(_mapping(boundary["value"]), environment)
            except MathIREvaluationError as exc:
                raise NumericalSolverError(f"PDE {side} boundary evaluation failed: {exc}") from exc

    apply_boundaries(field, time_start)
    saved_times = [time_start]
    saved_fields = [list(field)]
    for step_index in range(time_steps):
        current_time = time_start + step_index * requested_time_step
        time_step = min(requested_time_step, time_end - current_time)
        if time_step <= 0:
            break
        coefficients: list[float] = []
        for index in range(grid_points):
            environment = {
                "t": current_time,
                "x": domain_start + index * spacing,
                **parameters,
            }
            try:
                coefficient = evaluate_expression(diffusion_expression, environment)
            except MathIREvaluationError as exc:
                raise NumericalSolverError(f"PDE diffusion coefficient evaluation failed: {exc}") from exc
            if coefficient < 0:
                raise NumericalSolverError("PDE diffusion coefficient must remain non-negative")
            coefficients.append(coefficient)
        maximum_coefficient = max(coefficients)
        courant = maximum_coefficient * time_step / (spacing * spacing)
        maximum_courant = max(maximum_courant, courant)
        if courant > 0.5 + 1e-12:
            raise NumericalSolverError(
                "PDE explicit finite-difference stability bound was exceeded; reduce time_step"
            )
        next_field = list(field)
        for index in range(1, grid_points - 1):
            coordinate = domain_start + index * spacing
            environment = {
                "t": current_time,
                "x": coordinate,
                state_id: field[index],
                **parameters,
            }
            try:
                reaction = evaluate_expression(reaction_expression, environment)
            except MathIREvaluationError as exc:
                raise NumericalSolverError(f"PDE reaction evaluation failed: {exc}") from exc
            laplacian = (field[index + 1] - 2 * field[index] + field[index - 1]) / (spacing * spacing)
            next_field[index] = field[index] + time_step * (coefficients[index] * laplacian + reaction)
        apply_boundaries(next_field, current_time + time_step)
        if not all(math.isfinite(value) for value in next_field):
            raise NumericalSolverError("PDE solver produced a non-finite field value")
        field = next_field
        completed_time = current_time + time_step
        if (step_index + 1) % snapshot_stride == 0 or step_index + 1 == time_steps:
            saved_times.append(completed_time)
            saved_fields.append(list(field))
    return {
        "solver_id": "explicit_fd_diffusion_reaction_1d",
        "status": "COMPLETED",
        "x": [domain_start + index * spacing for index in range(grid_points)],
        "time": saved_times,
        "field_series": {state_id: saved_fields},
        "summary": {
            "final_minimum": min(field),
            "final_maximum": max(field),
            "final_mean": sum(field) / len(field),
            "grid_points": grid_points,
            "time_steps": time_steps,
            "maximum_diffusion_courant": maximum_courant,
            "stability_bound_satisfied": True,
        },
        "numerical_checks": {"explicit_stability": True},
    }


def execute_mathir(document: Mapping[str, object], *, resource_limits: Mapping[str, object]) -> dict[str, Any]:
    """Run exactly one validated MathIR document with a fixed trusted adapter."""

    normalized = validate_mathir_document(document)
    system_type = str(normalized["system_type"])
    if not solver_is_available(system_type):
        raise NumericalSolverError(f"No approved solver is available for {system_type}")
    if system_type == "ODE_IVP":
        return _run_ode(normalized, resource_limits)
    if system_type == "LINEAR_OPTIMIZATION":
        return _run_linear_optimization(normalized)
    if system_type == "MONTE_CARLO":
        return _run_monte_carlo(normalized, resource_limits)
    if system_type == "DIFFUSION_REACTION_1D":
        return _run_diffusion_reaction_1d(normalized, resource_limits)
    raise NumericalSolverError(f"No approved solver is registered for {system_type}")


__all__ = [
    "NumericalSolverError",
    "SOLVER_BY_SYSTEM_TYPE",
    "execute_mathir",
    "solver_is_available",
]
