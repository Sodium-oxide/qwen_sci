"""Trusted finite-difference solvers for the supported PDEIR families."""

from __future__ import annotations

import copy
import math
from collections.abc import Mapping
from typing import Any

from src.agents.quantitative_modeling.pdeir import (
    PDEIRValidationError,
    evaluate_pde_expression,
    materialize_pdeir_document,
    validate_pdeir_document,
)
from src.agents.quantitative_modeling.pde_capability_registry import pde_capability
from src.agents.quantitative_modeling.pde.adapters import PDEAdapterRegistry


class PDESolverError(RuntimeError):
    """Raised when a validated PDE cannot be safely solved."""


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _limits(value: Mapping[str, object] | None) -> dict[str, int | float]:
    raw = {
        "max_cells": 100_000,
        "max_nx": 4_096,
        "max_ny": 1_024,
        "max_nz": 128,
        "max_time_steps": 20_000,
        "max_snapshots": 200,
        "max_matrix_size": 20_000,
        "max_matrix_nonzeros": 200_000,
        "max_fields": 8,
        "max_memory_mb": 512,
        **_mapping(value),
    }
    provided_limits = _mapping(value)
    if "max_cells" not in provided_limits and "max_grid_points" in provided_limits:
        raw["max_cells"] = provided_limits["max_grid_points"]
    if "max_snapshots" not in provided_limits and "max_pde_snapshots" in provided_limits:
        raw["max_snapshots"] = provided_limits["max_pde_snapshots"]
    result: dict[str, int | float] = {}
    for name in (
        "max_cells",
        "max_nx",
        "max_ny",
        "max_nz",
        "max_time_steps",
        "max_snapshots",
        "max_matrix_size",
        "max_matrix_nonzeros",
        "max_fields",
        "max_memory_mb",
    ):
        try:
            parsed = int(raw[name])
        except (TypeError, ValueError) as exc:
            raise PDESolverError(f"{name} must be an integer") from exc
        if parsed < 1:
            raise PDESolverError(f"{name} must be positive")
        result[name] = parsed
    return result


def _time_steps(document: Mapping[str, object], limits: Mapping[str, int | float]) -> int:
    start, end = (float(item) for item in document["time_span"])
    step = float(_mapping(document["solver_options"])["time_step"])
    count = math.ceil((end - start) / step)
    if count > int(limits["max_time_steps"]):
        raise PDESolverError("PDE time steps exceed the authorized max_time_steps")
    return count


def _check_resource_budget(document: Mapping[str, object], limits: Mapping[str, int | float]) -> None:
    grid = _mapping(document.get("grid"))
    cells = int(grid.get("nx", 0)) * int(grid.get("ny", 1)) * int(grid.get("nz", 1))
    if int(grid.get("nx", 0)) > int(limits["max_nx"]):
        raise PDESolverError("PDE nx exceeds the authorized max_nx")
    if int(grid.get("ny", 1)) > int(limits["max_ny"]):
        raise PDESolverError("PDE ny exceeds the authorized max_ny")
    if int(grid.get("nz", 1)) > int(limits["max_nz"]):
        raise PDESolverError("PDE nz exceeds the authorized max_nz")
    fields = len(document.get("fields") or [])
    if fields > int(limits["max_fields"]):
        raise PDESolverError("PDE field count exceeds the authorized max_fields")
    if cells > int(limits["max_cells"]):
        raise PDESolverError("PDE grid exceeds the authorized max_cells")
    if str(document.get("system_type")) in {"ELLIPTIC_DIFFUSION_1D", "ELLIPTIC_DIFFUSION_2D", "POISSON_1D", "POISSON_2D", "HELMHOLTZ_1D", "HELMHOLTZ_2D"}:
        stencil_width = 7 if "nz" in grid else 5 if "ny" in grid else 3
        if cells * stencil_width > int(limits["max_matrix_nonzeros"]):
            raise PDESolverError("elliptic matrix exceeds the authorized max_matrix_nonzeros")
        snapshots = 1
    else:
        steps = _time_steps(document, limits)
        snapshots = min(steps + 1, int(limits["max_snapshots"]))
    estimated_bytes = cells * max(fields, 1) * max(snapshots, 1) * 8
    if estimated_bytes > int(limits["max_memory_mb"]) * 1024 * 1024:
        raise PDESolverError("PDE output exceeds the authorized max_memory_mb")


def _eval(expression: Mapping[str, object], *, t: float, x: float, parameters: Mapping[str, float], field: float | None = None, y: float | None = None, z: float | None = None) -> float:
    environment = {"t": t, "x": x, **parameters}
    if y is not None:
        environment["y"] = y
    if z is not None:
        environment["z"] = z
    if field is not None:
        environment["field:" + str(_mapping(expression).get("field_name", ""))] = field
    try:
        return float(evaluate_pde_expression(expression, environment))
    except (KeyError, PDEIRValidationError, ValueError, OverflowError) as exc:
        raise PDESolverError(f"PDE expression evaluation failed: {exc}") from exc


def _eval_term(expression: Mapping[str, object], *, t: float, x: float, parameters: Mapping[str, float], state_id: str, field: float, y: float | None = None, z: float | None = None) -> float:
    environment = {"t": t, "x": x, "field:" + state_id: field, **parameters}
    if y is not None:
        environment["y"] = y
    if z is not None:
        environment["z"] = z
    try:
        return float(evaluate_pde_expression(expression, environment))
    except (KeyError, PDEIRValidationError, ValueError, OverflowError) as exc:
        raise PDESolverError(f"PDE expression evaluation failed: {exc}") from exc


def _boundary_value(boundary: Mapping[str, object], *, t: float, x: float, parameters: Mapping[str, float], y: float | None = None, z: float | None = None) -> float:
    environment = {"t": t, "x": x, **parameters}
    if y is not None:
        environment["y"] = y
    if z is not None:
        environment["z"] = z
    try:
        return float(evaluate_pde_expression(_mapping(boundary["value"]), environment))
    except (KeyError, PDEIRValidationError, ValueError, OverflowError) as exc:
        raise PDESolverError(f"PDE boundary evaluation failed: {exc}") from exc


def _apply_1d_boundary(values: list[float], boundary: Mapping[str, object], *, t: float, x0: float, x1: float, dx: float, parameters: Mapping[str, float]) -> None:
    left = _mapping(boundary["left"])
    right = _mapping(boundary["right"])
    if left["type"] == "DIRICHLET":
        values[0] = _boundary_value(left, t=t, x=x0, parameters=parameters)
    elif left["type"] == "NEUMANN":
        values[0] = values[1] - dx * _boundary_value(left, t=t, x=x0, parameters=parameters)
    elif left["type"] == "NEUMANN_ZERO":
        values[0] = values[1]
    if right["type"] == "DIRICHLET":
        values[-1] = _boundary_value(right, t=t, x=x1, parameters=parameters)
    elif right["type"] == "NEUMANN":
        values[-1] = values[-2] + dx * _boundary_value(right, t=t, x=x1, parameters=parameters)
    elif right["type"] == "NEUMANN_ZERO":
        values[-1] = values[-2]
    if left["type"] == "PERIODIC" and right["type"] == "PERIODIC":
        values[0] = values[-2]
        values[-1] = values[1]


def _one_dimensional_rhs(document: Mapping[str, object], values: list[float], *, current_time: float, time_step: float, x0: float, dx: float, parameters: Mapping[str, float]) -> tuple[list[float], float, float, float]:
    grid = int(_mapping(document["grid"])["nx"])
    fields = document.get("fields")
    if not isinstance(fields, list) or not fields:
        raise PDESolverError("PDE document has no state field")
    state_id = str(_mapping(fields[0])["id"])
    diffusion_expression = _mapping(document["diffusion_coefficient"])
    reaction_expression = _mapping(document["reaction"])
    velocity_expression = _mapping(document.get("advection_velocity"))
    has_advection = bool(velocity_expression)
    next_values = list(values)
    maximum_diffusion = 0.0
    maximum_advection = 0.0
    maximum_reaction = 0.0
    velocities: list[float] = []
    coefficients: list[float] = []
    for index in range(grid):
        coordinate = x0 + index * dx
        coefficients.append(_eval_term(diffusion_expression, t=current_time, x=coordinate, parameters=parameters, state_id=state_id, field=values[index]))
        if coefficients[-1] < 0:
            raise PDESolverError("PDE diffusion coefficient must remain non-negative")
        velocities.append(_eval_term(velocity_expression, t=current_time, x=coordinate, parameters=parameters, state_id=state_id, field=values[index]) if has_advection else 0.0)
    for index in range(1, grid - 1):
        coordinate = x0 + index * dx
        if velocities[index] >= 0:
            first_derivative = (values[index] - values[index - 1]) / dx
        else:
            first_derivative = (values[index + 1] - values[index]) / dx
        second_derivative = (values[index + 1] - 2.0 * values[index] + values[index - 1]) / (dx * dx)
        reaction = _eval_term(reaction_expression, t=current_time, x=coordinate, parameters=parameters, state_id=state_id, field=values[index])
        next_values[index] = values[index] + time_step * (
            coefficients[index] * second_derivative
            - velocities[index] * first_derivative
            + reaction
        )
        maximum_diffusion = max(maximum_diffusion, coefficients[index] * time_step / (dx * dx))
        maximum_advection = max(maximum_advection, abs(velocities[index]) * time_step / dx)
        maximum_reaction = max(maximum_reaction, abs(reaction) * time_step / max(abs(values[index]), 1.0))
    return next_values, maximum_diffusion, maximum_advection, maximum_reaction


def _run_parabolic_1d(document: Mapping[str, object], limits: Mapping[str, int | float]) -> dict[str, Any]:
    nx = int(_mapping(document["grid"])["nx"])
    cells = nx
    if cells > int(limits["max_cells"]):
        raise PDESolverError("PDE grid exceeds the authorized max_cells")
    x0, x1 = (float(item) for item in _mapping(document["spatial_domain"])["x"])
    dx = (x1 - x0) / (nx - 1)
    time_start, time_end = (float(item) for item in document["time_span"])
    requested_step = float(_mapping(document["solver_options"])["time_step"])
    time_steps = _time_steps(document, limits)
    parameters = {str(name): float(value) for name, value in _mapping(document["parameters"]).items()}
    state_id = str(_mapping(document["fields"][0])["id"])
    values = [float(item) for item in _mapping(document["initial_condition"])["values"]]
    boundaries = _mapping(document["boundary_conditions"])
    _apply_1d_boundary(values, boundaries, t=time_start, x0=x0, x1=x1, dx=dx, parameters=parameters)
    saved_times = [time_start]
    saved_fields = [list(values)]
    max_diffusion = 0.0
    max_advection = 0.0
    max_reaction = 0.0
    has_advection = "advection_velocity" in document
    snapshots = max(2, int(limits["max_snapshots"]))
    stride = max(1, math.ceil(max(1, time_steps) / (snapshots - 1)))
    for step_index in range(time_steps):
        current_time = time_start + step_index * requested_step
        step = min(requested_step, time_end - current_time)
        if step <= 0:
            break
        candidate, diffusion_courant, advection_courant, reaction_number = _one_dimensional_rhs(
            document, values, current_time=current_time, time_step=step, x0=x0, dx=dx, parameters=parameters
        )
        stability_limit = 1.0 if has_advection else 0.5
        if diffusion_courant + advection_courant > stability_limit + 1e-12:
            raise PDESolverError("PDE explicit advection-diffusion stability bound was exceeded")
        integrator = _mapping(document["solver_options"]).get("time_integrator", "EXPLICIT_EULER")
        if integrator == "SSPRK2":
            midpoint, _, _, _ = _one_dimensional_rhs(
                document, candidate, current_time=current_time + step, time_step=step, x0=x0, dx=dx, parameters=parameters
            )
            candidate = [(old + new) / 2.0 for old, new in zip(values, midpoint)]
        _apply_1d_boundary(candidate, boundaries, t=current_time + step, x0=x0, x1=x1, dx=dx, parameters=parameters)
        if not all(math.isfinite(item) for item in candidate):
            raise PDESolverError("PDE solver produced a non-finite field value")
        values = candidate
        max_diffusion = max(max_diffusion, diffusion_courant)
        max_advection = max(max_advection, advection_courant)
        max_reaction = max(max_reaction, reaction_number)
        if (step_index + 1) % stride == 0 or step_index + 1 == time_steps:
            saved_times.append(current_time + step)
            saved_fields.append(list(values))
    return {
        "solver_id": str(pde_capability(str(document["system_type"]))["solver_id"]),
        "status": "COMPLETED",
        "x": [x0 + index * dx for index in range(nx)],
        "time": saved_times,
        "field_series": {state_id: saved_fields},
        "summary": {
            "final_minimum": min(values),
            "final_maximum": max(values),
            "final_mean": sum(values) / len(values),
            "grid_points": nx,
            "time_steps": time_steps,
            "maximum_diffusion_courant": max_diffusion,
            "maximum_advection_courant": max_advection,
            "maximum_reaction_number": max_reaction,
        },
        "numerical_checks": {
            "explicit_stability": True,
            "finite_field": True,
        },
    }


def _index_2d(index: int, nx: int) -> tuple[int, int]:
    return index % nx, index // nx


def _run_parabolic_2d(document: Mapping[str, object], limits: Mapping[str, int | float]) -> dict[str, Any]:
    grid = _mapping(document["grid"])
    nx, ny = int(grid["nx"]), int(grid["ny"])
    cells = nx * ny
    if cells > int(limits["max_cells"]):
        raise PDESolverError("PDE grid exceeds the authorized max_cells")
    x0, x1 = (float(item) for item in _mapping(document["spatial_domain"])["x"])
    y0, y1 = (float(item) for item in _mapping(document["spatial_domain"])["y"])
    dx, dy = (x1 - x0) / (nx - 1), (y1 - y0) / (ny - 1)
    time_start, time_end = (float(item) for item in document["time_span"])
    requested_step = float(_mapping(document["solver_options"])["time_step"])
    time_steps = _time_steps(document, limits)
    parameters = {str(name): float(value) for name, value in _mapping(document["parameters"]).items()}
    state_id = str(_mapping(document["fields"][0])["id"])
    values = [float(item) for item in _mapping(document["initial_condition"])["values"]]
    boundaries = _mapping(document["boundary_conditions"])

    def apply_boundary(field: list[float], time_value: float) -> None:
        for side, indices, coordinate, axis_step in (
            ("left", [j * nx for j in range(ny)], x0, dx),
            ("right", [j * nx + nx - 1 for j in range(ny)], x1, dx),
            ("bottom", list(range(nx)), y0, dy),
            ("top", [(ny - 1) * nx + i for i in range(nx)], y1, dy),
        ):
            boundary = _mapping(boundaries[side])
            if boundary["type"] == "DIRICHLET":
                for index in indices:
                    i, j = _index_2d(index, nx)
                    field[index] = _boundary_value(boundary, t=time_value, x=x0 + i * dx, y=y0 + j * dy, parameters=parameters)
            elif boundary["type"] == "NEUMANN_ZERO":
                for index in indices:
                    i, j = _index_2d(index, nx)
                    neighbor = index + 1 if side == "left" else index - 1 if side == "right" else index + nx if side == "bottom" else index - nx
                    field[index] = field[neighbor]
            elif boundary["type"] == "NEUMANN":
                for index in indices:
                    i, j = _index_2d(index, nx)
                    neighbor = index + 1 if side == "left" else index - 1 if side == "right" else index + nx if side == "bottom" else index - nx
                    field[index] = field[neighbor] + (1 if side in {"right", "top"} else -1) * axis_step * _boundary_value(boundary, t=time_value, x=x0 + i * dx, y=y0 + j * dy, parameters=parameters)
        if boundaries["left"]["type"] == "PERIODIC" and boundaries["right"]["type"] == "PERIODIC":
            for j in range(ny):
                field[j * nx] = field[j * nx + nx - 2]
                field[j * nx + nx - 1] = field[j * nx + 1]
        if boundaries["bottom"]["type"] == "PERIODIC" and boundaries["top"]["type"] == "PERIODIC":
            for i in range(nx):
                field[i] = field[(ny - 2) * nx + i]
                field[(ny - 1) * nx + i] = field[nx + i]

    apply_boundary(values, time_start)
    saved_times = [time_start]
    saved_fields = [list(values)]
    maximum_courant = 0.0
    stride = max(1, math.ceil(max(1, time_steps) / (max(2, int(limits["max_snapshots"])) - 1)))
    diffusion = _mapping(document["diffusion_coefficient"])
    reaction = _mapping(document["reaction"])
    for step_index in range(time_steps):
        current_time = time_start + step_index * requested_step
        step = min(requested_step, time_end - current_time)
        coefficients = []
        for index, value in enumerate(values):
            i, j = _index_2d(index, nx)
            coefficients.append(_eval_term(diffusion, t=current_time, x=x0 + i * dx, y=y0 + j * dy, parameters=parameters, state_id=state_id, field=value))
        max_coefficient = max(coefficients)
        if max_coefficient < 0:
            raise PDESolverError("PDE diffusion coefficient must remain non-negative")
        courant = max_coefficient * step * (1.0 / (dx * dx) + 1.0 / (dy * dy))
        if courant > 0.5 + 1e-12:
            raise PDESolverError("2D explicit diffusion stability bound was exceeded")
        candidate = list(values)
        for index in range(1, cells - 1):
            i, j = _index_2d(index, nx)
            if i == 0 or i == nx - 1 or j == 0 or j == ny - 1:
                continue
            laplacian = (
                (values[index + 1] - 2 * values[index] + values[index - 1]) / (dx * dx)
                + (values[index + nx] - 2 * values[index] + values[index - nx]) / (dy * dy)
            )
            local_reaction = _eval_term(reaction, t=current_time, x=x0 + i * dx, y=y0 + j * dy, parameters=parameters, state_id=state_id, field=values[index])
            candidate[index] = values[index] + step * (coefficients[index] * laplacian + local_reaction)
        apply_boundary(candidate, current_time + step)
        if not all(math.isfinite(item) for item in candidate):
            raise PDESolverError("PDE solver produced a non-finite field value")
        values = candidate
        maximum_courant = max(maximum_courant, courant)
        if (step_index + 1) % stride == 0 or step_index + 1 == time_steps:
            saved_times.append(current_time + step)
            saved_fields.append(list(values))
    return {
        "solver_id": str(pde_capability(str(document["system_type"]))["solver_id"]),
        "status": "COMPLETED",
        "x": [x0 + i * dx for i in range(nx)],
        "y": [y0 + j * dy for j in range(ny)],
        "time": saved_times,
        "field_series": {state_id: saved_fields},
        "summary": {
            "final_minimum": min(values),
            "final_maximum": max(values),
            "final_mean": sum(values) / len(values),
            "grid_points": cells,
            "grid_shape": [nx, ny],
            "time_steps": time_steps,
            "maximum_diffusion_courant": maximum_courant,
        },
        "numerical_checks": {"explicit_stability": True, "finite_field": True},
    }


def _index_3d(index: int, nx: int, ny: int) -> tuple[int, int, int]:
    plane = nx * ny
    layer_index = index % plane
    return layer_index % nx, layer_index // nx, index // plane


def _run_parabolic_3d(document: Mapping[str, object], limits: Mapping[str, int | float]) -> dict[str, Any]:
    grid = _mapping(document["grid"])
    nx, ny, nz = int(grid["nx"]), int(grid["ny"]), int(grid["nz"])
    cells = nx * ny * nz
    if cells > int(limits["max_cells"]):
        raise PDESolverError("PDE grid exceeds the authorized max_cells")
    domain = _mapping(document["spatial_domain"])
    x0, x1 = (float(item) for item in domain["x"])
    y0, y1 = (float(item) for item in domain["y"])
    z0, z1 = (float(item) for item in domain["z"])
    dx, dy, dz = (x1 - x0) / (nx - 1), (y1 - y0) / (ny - 1), (z1 - z0) / (nz - 1)
    time_start, time_end = (float(item) for item in document["time_span"])
    requested_step = float(_mapping(document["solver_options"])["time_step"])
    time_steps = _time_steps(document, limits)
    parameters = {str(name): float(value) for name, value in _mapping(document["parameters"]).items()}
    state_id = str(_mapping(document["fields"][0])["id"])
    values = [float(item) for item in _mapping(document["initial_condition"])["values"]]
    boundaries = _mapping(document["boundary_conditions"])
    plane = nx * ny

    def apply_boundary(field: list[float], time_value: float) -> None:
        faces = (
            ("left", [nx * (j + ny * k) for k in range(nz) for j in range(ny)], x0, dx, 1, -1.0),
            ("right", [nx * (j + ny * k) + nx - 1 for k in range(nz) for j in range(ny)], x1, dx, -1, 1.0),
            ("bottom", [i + nx * ny * k for k in range(nz) for i in range(nx)], y0, dy, nx, -1.0),
            ("top", [i + nx * (ny - 1) + nx * ny * k for k in range(nz) for i in range(nx)], y1, dy, -nx, 1.0),
            ("front", [i + nx * j for j in range(ny) for i in range(nx)], z0, dz, plane, -1.0),
            ("back", [i + nx * j + plane * (nz - 1) for j in range(ny) for i in range(nx)], z1, dz, -plane, 1.0),
        )
        for side, indices, _, axis_step, neighbor_offset, outward_sign in faces:
            boundary = _mapping(boundaries[side])
            boundary_type = boundary["type"]
            if boundary_type == "PERIODIC":
                continue
            for index in indices:
                i, j, k = _index_3d(index, nx, ny)
                coordinate_x = x0 + i * dx
                coordinate_y = y0 + j * dy
                coordinate_z = z0 + k * dz
                neighbor = index + neighbor_offset
                if boundary_type == "DIRICHLET":
                    field[index] = _boundary_value(
                        boundary,
                        t=time_value,
                        x=coordinate_x,
                        y=coordinate_y,
                        z=coordinate_z,
                        parameters=parameters,
                    )
                elif boundary_type == "NEUMANN_ZERO":
                    field[index] = field[neighbor]
                elif boundary_type == "NEUMANN":
                    field[index] = field[neighbor] + outward_sign * axis_step * _boundary_value(
                        boundary,
                        t=time_value,
                        x=coordinate_x,
                        y=coordinate_y,
                        z=coordinate_z,
                        parameters=parameters,
                    )
        if boundaries["left"]["type"] == "PERIODIC" and boundaries["right"]["type"] == "PERIODIC":
            for k in range(nz):
                for j in range(ny):
                    row = nx * (j + ny * k)
                    field[row] = field[row + nx - 2]
                    field[row + nx - 1] = field[row + 1]
        if boundaries["bottom"]["type"] == "PERIODIC" and boundaries["top"]["type"] == "PERIODIC":
            for k in range(nz):
                for i in range(nx):
                    field[i + plane * k] = field[i + nx * (ny - 2) + plane * k]
                    field[i + nx * (ny - 1) + plane * k] = field[i + nx + plane * k]
        if boundaries["front"]["type"] == "PERIODIC" and boundaries["back"]["type"] == "PERIODIC":
            for j in range(ny):
                for i in range(nx):
                    field[i + nx * j] = field[i + nx * j + plane * (nz - 2)]
                    field[i + nx * j + plane * (nz - 1)] = field[i + nx * j + plane]

    apply_boundary(values, time_start)
    saved_times = [time_start]
    saved_fields = [list(values)]
    maximum_courant = 0.0
    stride = max(1, math.ceil(max(1, time_steps) / (max(2, int(limits["max_snapshots"])) - 1)))
    diffusion = _mapping(document["diffusion_coefficient"])
    reaction = _mapping(document["reaction"])
    inverse_spacing_sum = 1.0 / (dx * dx) + 1.0 / (dy * dy) + 1.0 / (dz * dz)
    for step_index in range(time_steps):
        current_time = time_start + step_index * requested_step
        step = min(requested_step, time_end - current_time)
        if step <= 0:
            break
        coefficients = []
        for index, value in enumerate(values):
            i, j, k = _index_3d(index, nx, ny)
            coefficients.append(
                _eval_term(
                    diffusion,
                    t=current_time,
                    x=x0 + i * dx,
                    y=y0 + j * dy,
                    z=z0 + k * dz,
                    parameters=parameters,
                    state_id=state_id,
                    field=value,
                )
            )
        max_coefficient = max(coefficients)
        if max_coefficient < 0:
            raise PDESolverError("PDE diffusion coefficient must remain non-negative")
        courant = max_coefficient * step * inverse_spacing_sum
        if courant > 0.5 + 1e-12:
            raise PDESolverError("3D explicit diffusion stability bound was exceeded")
        candidate = list(values)
        for k in range(1, nz - 1):
            for j in range(1, ny - 1):
                for i in range(1, nx - 1):
                    index = i + nx * (j + ny * k)
                    laplacian = (
                        (values[index + 1] - 2.0 * values[index] + values[index - 1]) / (dx * dx)
                        + (values[index + nx] - 2.0 * values[index] + values[index - nx]) / (dy * dy)
                        + (values[index + plane] - 2.0 * values[index] + values[index - plane]) / (dz * dz)
                    )
                    local_reaction = _eval_term(
                        reaction,
                        t=current_time,
                        x=x0 + i * dx,
                        y=y0 + j * dy,
                        z=z0 + k * dz,
                        parameters=parameters,
                        state_id=state_id,
                        field=values[index],
                    )
                    candidate[index] = values[index] + step * (coefficients[index] * laplacian + local_reaction)
        apply_boundary(candidate, current_time + step)
        if not all(math.isfinite(item) for item in candidate):
            raise PDESolverError("PDE solver produced a non-finite field value")
        values = candidate
        maximum_courant = max(maximum_courant, courant)
        if (step_index + 1) % stride == 0 or step_index + 1 == time_steps:
            saved_times.append(current_time + step)
            saved_fields.append(list(values))
    return {
        "solver_id": str(pde_capability(str(document["system_type"]))["solver_id"]),
        "status": "COMPLETED",
        "x": [x0 + i * dx for i in range(nx)],
        "y": [y0 + j * dy for j in range(ny)],
        "z": [z0 + k * dz for k in range(nz)],
        "time": saved_times,
        "field_series": {state_id: saved_fields},
        "summary": {
            "final_minimum": min(values),
            "final_maximum": max(values),
            "final_mean": sum(values) / len(values),
            "grid_points": cells,
            "grid_shape": [nx, ny, nz],
            "time_steps": time_steps,
            "maximum_diffusion_courant": maximum_courant,
            "stability_limit": 0.5,
        },
        "numerical_checks": {"explicit_stability": True, "finite_field": True},
    }


def _run_spherical_radial_thermal(document: Mapping[str, object], limits: Mapping[str, int | float]) -> dict[str, Any]:
    """Solve a radial spherical heat equation on a node-centered grid."""

    nx = int(_mapping(document["grid"])["nx"])
    if nx > int(limits["max_cells"]):
        raise PDESolverError("spherical radial grid exceeds the authorized max_cells")
    r0, radius = (float(item) for item in _mapping(document["spatial_domain"])["x"])
    if abs(r0) > 1e-12 or radius <= 0:
        raise PDESolverError("spherical radial thermal models require a domain starting at r=0")
    dr = radius / (nx - 1)
    time_start, time_end = (float(item) for item in document["time_span"])
    requested_step = float(_mapping(document["solver_options"])["time_step"])
    time_steps = _time_steps(document, limits)
    parameters = {str(name): float(value) for name, value in _mapping(document["parameters"]).items()}
    state_id = str(_mapping(document["fields"][0])["id"])
    values = [float(item) for item in _mapping(document["initial_condition"])["values"]]
    boundaries = _mapping(document["boundary_conditions"])
    conductivity = _mapping(document["diffusion_coefficient"])
    heat_capacity = _mapping(document["heat_capacity"])
    source = _mapping(document["source"])
    coordinates = [index * dr for index in range(nx)]

    def apply_boundary(field: list[float], time_value: float) -> None:
        origin = _mapping(boundaries["left"])
        if origin["type"] != "SPHERICAL_ORIGIN_REGULARITY":
            raise PDESolverError("spherical radial origin must use SPHERICAL_ORIGIN_REGULARITY")
        field[0] = field[1]
        surface = _mapping(boundaries["right"])
        if surface["type"] == "DIRICHLET":
            field[-1] = _boundary_value(surface, t=time_value, x=radius, parameters=parameters)
        elif surface["type"] == "NEUMANN_ZERO":
            field[-1] = field[-2]
        elif surface["type"] == "NEUMANN":
            field[-1] = field[-2] + dr * _boundary_value(surface, t=time_value, x=radius, parameters=parameters)
        else:
            raise PDESolverError("unsupported spherical radial surface boundary")

    apply_boundary(values, time_start)
    saved_times = [time_start]
    saved_fields = [list(values)]
    maximum_courant = 0.0
    stride = max(1, math.ceil(max(1, time_steps) / (max(2, int(limits["max_snapshots"])) - 1)))
    for step_index in range(time_steps):
        current_time = time_start + step_index * requested_step
        step = min(requested_step, time_end - current_time)
        if step <= 0:
            break
        candidate = list(values)
        maximum_alpha = 0.0
        for index, value in enumerate(values):
            r = coordinates[index]
            capacity_value = _eval_term(
                heat_capacity,
                t=current_time,
                x=r,
                parameters=parameters,
                state_id=state_id,
                field=value,
            )
            if capacity_value <= 0:
                raise PDESolverError("spherical radial heat capacity must be positive")
            center_conductivity = _eval_term(
                conductivity,
                t=current_time,
                x=r,
                parameters=parameters,
                state_id=state_id,
                field=value,
            )
            if center_conductivity < 0:
                raise PDESolverError("spherical radial conductivity must be non-negative")
            maximum_alpha = max(maximum_alpha, center_conductivity / capacity_value)
            if index == 0:
                laplacian_term = 6.0 * center_conductivity * (values[1] - values[0]) / (dr * dr)
            elif index == nx - 1:
                continue
            else:
                r_minus = r - dr / 2.0
                r_plus = r + dr / 2.0
                k_minus = _eval_term(
                    conductivity,
                    t=current_time,
                    x=r_minus,
                    parameters=parameters,
                    state_id=state_id,
                    field=value,
                )
                k_plus = _eval_term(
                    conductivity,
                    t=current_time,
                    x=r_plus,
                    parameters=parameters,
                    state_id=state_id,
                    field=value,
                )
                if min(k_minus, k_plus) < 0:
                    raise PDESolverError("spherical radial conductivity must be non-negative")
                outward_flux = r_plus * r_plus * k_plus * (values[index + 1] - values[index]) / dr
                inward_flux = r_minus * r_minus * k_minus * (values[index] - values[index - 1]) / dr
                laplacian_term = (outward_flux - inward_flux) / (r * r * dr)
            source_value = _eval_term(
                source,
                t=current_time,
                x=r,
                parameters=parameters,
                state_id=state_id,
                field=value,
            )
            candidate[index] = value + step * (laplacian_term + source_value) / capacity_value
        courant = maximum_alpha * step / (dr * dr)
        if courant > 1.0 / 6.0 + 1e-12:
            raise PDESolverError("spherical radial explicit diffusion stability bound was exceeded")
        apply_boundary(candidate, current_time + step)
        if not all(math.isfinite(item) for item in candidate):
            raise PDESolverError("PDE solver produced a non-finite field value")
        values = candidate
        maximum_courant = max(maximum_courant, courant)
        if (step_index + 1) % stride == 0 or step_index + 1 == time_steps:
            saved_times.append(current_time + step)
            saved_fields.append(list(values))
    return {
        "solver_id": str(pde_capability(str(document["system_type"]))["solver_id"]),
        "status": "COMPLETED",
        "x": coordinates,
        "r": coordinates,
        "time": saved_times,
        "field_series": {state_id: saved_fields},
        "summary": {
            "final_minimum": min(values),
            "final_maximum": max(values),
            "final_mean": sum(values) / len(values),
            "grid_points": nx,
            "time_steps": time_steps,
            "maximum_diffusion_courant": maximum_courant,
            "stability_limit": 1.0 / 6.0,
        },
        "numerical_checks": {
            "explicit_stability": True,
            "spherical_origin_regularity": abs(values[0] - values[1]) <= 1e-8,
            "finite_field": True,
        },
    }


def _solve_dense(matrix: list[list[float]], vector: list[float]) -> list[float]:
    size = len(vector)
    augmented = [row[:] + [vector[index]] for index, row in enumerate(matrix)]
    for pivot in range(size):
        pivot_row = max(range(pivot, size), key=lambda row: abs(augmented[row][pivot]))
        if abs(augmented[pivot_row][pivot]) < 1e-14:
            raise PDESolverError("elliptic PDE matrix is singular")
        augmented[pivot], augmented[pivot_row] = augmented[pivot_row], augmented[pivot]
        divisor = augmented[pivot][pivot]
        augmented[pivot] = [item / divisor for item in augmented[pivot]]
        for row in range(size):
            if row == pivot:
                continue
            factor = augmented[row][pivot]
            if factor:
                augmented[row] = [left - factor * right for left, right in zip(augmented[row], augmented[pivot])]
    return [augmented[index][-1] for index in range(size)]


def _run_elliptic_1d(document: Mapping[str, object], limits: Mapping[str, int | float]) -> dict[str, Any]:
    nx = int(_mapping(document["grid"])["nx"])
    if nx > int(limits["max_matrix_size"]):
        raise PDESolverError("elliptic matrix exceeds the authorized max_matrix_size")
    x0, x1 = (float(item) for item in _mapping(document["spatial_domain"])["x"])
    dx = (x1 - x0) / (nx - 1)
    params = {str(name): float(value) for name, value in _mapping(document["parameters"]).items()}
    state_id = str(_mapping(document["fields"][0])["id"])
    coefficient = _mapping(document["diffusion_coefficient"])
    reaction = _mapping(document["reaction_coefficient"])
    source = _mapping(document["source"])
    boundaries = _mapping(document["boundary_conditions"])
    matrix = [[0.0 for _ in range(nx)] for _ in range(nx)]
    vector = [0.0 for _ in range(nx)]
    for index in range(nx):
        x = x0 + index * dx
        if index == 0 or index == nx - 1:
            boundary = _mapping(boundaries["left" if index == 0 else "right"])
            if boundary["type"] == "DIRICHLET":
                matrix[index][index] = 1.0
                vector[index] = _boundary_value(boundary, t=0.0, x=x, parameters=params)
            else:
                neighbor = 1 if index == 0 else nx - 2
                matrix[index][index] = 1.0
                matrix[index][neighbor] = -1.0
                flux = 0.0 if boundary["type"] == "NEUMANN_ZERO" else _boundary_value(
                    boundary, t=0.0, x=x, parameters=params
                )
                vector[index] = (-1.0 if index == 0 else 1.0) * dx * flux
            continue
        k = _eval_term(coefficient, t=0.0, x=x, parameters=params, state_id=state_id, field=0.0)
        r = _eval_term(reaction, t=0.0, x=x, parameters=params, state_id=state_id, field=0.0)
        f = _eval_term(source, t=0.0, x=x, parameters=params, state_id=state_id, field=0.0)
        if k <= 0:
            raise PDESolverError("elliptic diffusion coefficient must be positive")
        matrix[index][index - 1] = -k / (dx * dx)
        matrix[index][index] = 2 * k / (dx * dx) + r
        matrix[index][index + 1] = -k / (dx * dx)
        vector[index] = f
    solution = _solve_dense(matrix, vector)
    residual = max(abs(sum(matrix[row][col] * solution[col] for col in range(nx)) - vector[row]) for row in range(nx))
    return {
        "solver_id": str(pde_capability(str(document["system_type"]))["solver_id"]),
        "status": "COMPLETED",
        "x": [x0 + index * dx for index in range(nx)],
        "field": {state_id: solution},
        "summary": {"minimum": min(solution), "maximum": max(solution), "mean": sum(solution) / len(solution), "grid_points": nx, "linear_residual": residual},
        "numerical_checks": {"linear_residual": residual <= 1e-8, "finite_field": all(math.isfinite(item) for item in solution)},
    }


def _run_elliptic_2d(document: Mapping[str, object], limits: Mapping[str, int | float]) -> dict[str, Any]:
    grid = _mapping(document["grid"])
    nx, ny = int(grid["nx"]), int(grid["ny"])
    cells = nx * ny
    if cells > int(limits["max_matrix_size"]):
        raise PDESolverError("elliptic 2D matrix exceeds the authorized max_matrix_size")
    x0, x1 = (float(item) for item in _mapping(document["spatial_domain"])["x"])
    y0, y1 = (float(item) for item in _mapping(document["spatial_domain"])["y"])
    dx, dy = (x1 - x0) / (nx - 1), (y1 - y0) / (ny - 1)
    params = {str(name): float(value) for name, value in _mapping(document["parameters"]).items()}
    state_id = str(_mapping(document["fields"][0])["id"])
    coefficient = _mapping(document["diffusion_coefficient"])
    reaction = _mapping(document["reaction_coefficient"])
    source = _mapping(document["source"])
    boundaries = _mapping(document["boundary_conditions"])
    matrix = [[0.0 for _ in range(cells)] for _ in range(cells)]
    vector = [0.0 for _ in range(cells)]

    def value(expression: Mapping[str, object], x: float, y: float) -> float:
        return _eval_term(expression, t=0.0, x=x, y=y, parameters=params, state_id=state_id, field=0.0)

    for index in range(cells):
        i, j = _index_2d(index, nx)
        x, y = x0 + i * dx, y0 + j * dy
        side = "left" if i == 0 else "right" if i == nx - 1 else "bottom" if j == 0 else "top" if j == ny - 1 else ""
        if side:
            boundary = _mapping(boundaries[side])
            boundary_type = boundary["type"]
            if boundary_type == "DIRICHLET":
                matrix[index][index] = 1.0
                vector[index] = _boundary_value(boundary, t=0.0, x=x, y=y, parameters=params)
            else:
                neighbor = index + 1 if side == "left" else index - 1 if side == "right" else index + nx if side == "bottom" else index - nx
                spacing = dx if side in {"left", "right"} else dy
                outward_sign = -1.0 if side in {"left", "bottom"} else 1.0
                matrix[index][index] = 1.0
                matrix[index][neighbor] = -1.0
                flux = 0.0 if boundary_type == "NEUMANN_ZERO" else _boundary_value(
                    boundary, t=0.0, x=x, y=y, parameters=params
                )
                vector[index] = outward_sign * spacing * flux
            continue
        west = value(coefficient, x - dx / 2.0, y)
        east = value(coefficient, x + dx / 2.0, y)
        south = value(coefficient, x, y - dy / 2.0)
        north = value(coefficient, x, y + dy / 2.0)
        if min(west, east, south, north) <= 0:
            raise PDESolverError("elliptic 2D diffusion coefficient must be positive")
        reaction_value = value(reaction, x, y)
        source_value = value(source, x, y)
        matrix[index][index] = (west + east) / (dx * dx) + (south + north) / (dy * dy) + reaction_value
        matrix[index][index - 1] = -west / (dx * dx)
        matrix[index][index + 1] = -east / (dx * dx)
        matrix[index][index - nx] = -south / (dy * dy)
        matrix[index][index + nx] = -north / (dy * dy)
        vector[index] = source_value
    solution = _solve_dense(matrix, vector)
    residual = max(
        abs(sum(matrix[row][col] * solution[col] for col in range(cells)) - vector[row])
        for row in range(cells)
    )
    return {
        "solver_id": str(pde_capability(str(document["system_type"]))["solver_id"]),
        "status": "COMPLETED",
        "x": [x0 + i * dx for i in range(nx)],
        "y": [y0 + j * dy for j in range(ny)],
        "field": {state_id: solution},
        "summary": {
            "minimum": min(solution),
            "maximum": max(solution),
            "mean": sum(solution) / len(solution),
            "grid_points": cells,
            "grid_shape": [nx, ny],
            "linear_residual": residual,
        },
        "numerical_checks": {
            "linear_residual": residual <= 1e-8,
            "finite_field": all(math.isfinite(item) for item in solution),
        },
    }


def _run_wave_1d(document: Mapping[str, object], limits: Mapping[str, int | float]) -> dict[str, Any]:
    nx = int(_mapping(document["grid"])["nx"])
    if nx > int(limits["max_cells"]):
        raise PDESolverError("wave grid exceeds the authorized max_cells")
    x0, x1 = (float(item) for item in _mapping(document["spatial_domain"])["x"])
    dx = (x1 - x0) / (nx - 1)
    start, end = (float(item) for item in document["time_span"])
    dt = float(_mapping(document["solver_options"])["time_step"])
    steps = _time_steps(document, limits)
    params = {str(name): float(value) for name, value in _mapping(document["parameters"]).items()}
    state_id = str(_mapping(document["fields"][0])["id"])
    current = [float(item) for item in _mapping(document["initial_condition"])["values"]]
    previous_velocity = [float(item) for item in _mapping(document["initial_velocity"])["values"]]
    speed_expression = _mapping(document["wave_speed"])
    source_expression = _mapping(document["source"])
    speed = max(_eval_term(speed_expression, t=start, x=x0 + i * dx, parameters=params, state_id=state_id, field=current[i]) for i in range(nx))
    if speed <= 0:
        raise PDESolverError("wave speed must be positive")
    courant = speed * dt / dx
    if courant > 1.0 + 1e-12:
        raise PDESolverError("wave CFL stability bound was exceeded")
    boundaries = _mapping(document["boundary_conditions"])
    saved_times = [start]
    saved_fields = [list(current)]
    _apply_1d_boundary(current, boundaries, t=start, x0=x0, x1=x1, dx=dx, parameters=params)
    previous = [current[i] - dt * previous_velocity[i] for i in range(nx)]
    for step_index in range(steps):
        current_time = start + step_index * dt
        step = min(dt, end - current_time)
        candidate = list(current)
        for index in range(1, nx - 1):
            x = x0 + index * dx
            source = _eval_term(source_expression, t=current_time, x=x, parameters=params, state_id=state_id, field=current[index])
            candidate[index] = 2 * current[index] - previous[index] + (speed * speed * step * step / (dx * dx)) * (current[index + 1] - 2 * current[index] + current[index - 1]) + step * step * source
        _apply_1d_boundary(candidate, boundaries, t=current_time + step, x0=x0, x1=x1, dx=dx, parameters=params)
        previous, current = current, candidate
        if not all(math.isfinite(item) for item in current):
            raise PDESolverError("wave solver produced a non-finite field value")
        if len(saved_times) < int(limits["max_snapshots"]) and ((step_index + 1) % max(1, math.ceil(max(1, steps) / (int(limits["max_snapshots"]) - 1))) == 0 or step_index + 1 == steps):
            saved_times.append(current_time + step)
            saved_fields.append(list(current))
    return {
        "solver_id": "pde_fd_wave_1d",
        "status": "COMPLETED",
        "x": [x0 + i * dx for i in range(nx)],
        "time": saved_times,
        "field_series": {state_id: saved_fields},
        "summary": {"final_minimum": min(current), "final_maximum": max(current), "grid_points": nx, "time_steps": steps, "courant_number": courant},
        "numerical_checks": {"wave_cfl": True, "finite_field": True},
    }


def _run_wave_2d(document: Mapping[str, object], limits: Mapping[str, int | float]) -> dict[str, Any]:
    grid = _mapping(document["grid"])
    nx, ny = int(grid["nx"]), int(grid["ny"])
    cells = nx * ny
    if cells > int(limits["max_cells"]):
        raise PDESolverError("wave 2D grid exceeds the authorized max_cells")
    x0, x1 = (float(item) for item in _mapping(document["spatial_domain"])["x"])
    y0, y1 = (float(item) for item in _mapping(document["spatial_domain"])["y"])
    dx, dy = (x1 - x0) / (nx - 1), (y1 - y0) / (ny - 1)
    start, end = (float(item) for item in document["time_span"])
    dt = float(_mapping(document["solver_options"])["time_step"])
    steps = _time_steps(document, limits)
    params = {str(name): float(value) for name, value in _mapping(document["parameters"]).items()}
    state_id = str(_mapping(document["fields"][0])["id"])
    current = [float(item) for item in _mapping(document["initial_condition"])["values"]]
    velocity = [float(item) for item in _mapping(document["initial_velocity"])["values"]]
    speed_expression = _mapping(document["wave_speed"])
    source_expression = _mapping(document["source"])
    boundaries = _mapping(document["boundary_conditions"])

    def apply_boundary(field: list[float], time_value: float) -> None:
        for side, indices in (
            ("left", [j * nx for j in range(ny)]),
            ("right", [j * nx + nx - 1 for j in range(ny)]),
            ("bottom", list(range(nx))),
            ("top", [(ny - 1) * nx + i for i in range(nx)]),
        ):
            boundary = _mapping(boundaries[side])
            for index in indices:
                i, j = _index_2d(index, nx)
                x, y = x0 + i * dx, y0 + j * dy
                if boundary["type"] == "DIRICHLET":
                    field[index] = _boundary_value(boundary, t=time_value, x=x, y=y, parameters=params)
                else:
                    neighbor = index + 1 if side == "left" else index - 1 if side == "right" else index + nx if side == "bottom" else index - nx
                    field[index] = field[neighbor]

    def local_speed(time_value: float, field: list[float]) -> list[float]:
        return [
            _eval_term(
                speed_expression,
                t=time_value,
                x=x0 + (index % nx) * dx,
                y=y0 + (index // nx) * dy,
                parameters=params,
                state_id=state_id,
                field=field[index],
            )
            for index in range(cells)
        ]

    apply_boundary(current, start)
    speeds = local_speed(start, current)
    maximum_speed = max(speeds)
    if maximum_speed <= 0:
        raise PDESolverError("wave speed must be positive")
    courant = maximum_speed * dt * math.sqrt(1.0 / (dx * dx) + 1.0 / (dy * dy))
    if courant > 1.0 + 1e-12:
        raise PDESolverError("2D wave CFL stability bound was exceeded")
    previous = [current[index] - dt * velocity[index] for index in range(cells)]
    saved_times = [start]
    saved_fields = [list(current)]
    stride = max(1, math.ceil(max(1, steps) / (max(2, int(limits["max_snapshots"])) - 1)))
    for step_index in range(steps):
        current_time = start + step_index * dt
        step = min(dt, end - current_time)
        if step <= 0:
            break
        speeds = local_speed(current_time, current)
        candidate = list(current)
        for index in range(1, cells - 1):
            i, j = _index_2d(index, nx)
            if i == 0 or i == nx - 1 or j == 0 or j == ny - 1:
                continue
            source = _eval_term(
                source_expression,
                t=current_time,
                x=x0 + i * dx,
                y=y0 + j * dy,
                parameters=params,
                state_id=state_id,
                field=current[index],
            )
            laplacian = (
                (current[index + 1] - 2 * current[index] + current[index - 1]) / (dx * dx)
                + (current[index + nx] - 2 * current[index] + current[index - nx]) / (dy * dy)
            )
            candidate[index] = 2 * current[index] - previous[index] + speeds[index] ** 2 * step * step * laplacian + step * step * source
        apply_boundary(candidate, current_time + step)
        previous, current = current, candidate
        if not all(math.isfinite(item) for item in current):
            raise PDESolverError("2D wave solver produced a non-finite field value")
        if (step_index + 1) % stride == 0 or step_index + 1 == steps:
            saved_times.append(current_time + step)
            saved_fields.append(list(current))
    return {
        "solver_id": "pde_fd_wave_2d",
        "status": "COMPLETED",
        "x": [x0 + i * dx for i in range(nx)],
        "y": [y0 + j * dy for j in range(ny)],
        "time": saved_times,
        "field_series": {state_id: saved_fields},
        "summary": {
            "final_minimum": min(current),
            "final_maximum": max(current),
            "grid_points": cells,
            "grid_shape": [nx, ny],
            "time_steps": steps,
            "courant_number": courant,
        },
        "numerical_checks": {"wave_cfl": True, "finite_field": True},
    }


_PDE_SOLVER_ADAPTERS = {
    "DIFFUSION_REACTION_1D": _run_parabolic_1d,
    "ADVECTION_DIFFUSION_REACTION_1D": _run_parabolic_1d,
    "BURGERS_1D": _run_parabolic_1d,
    "DIFFUSION_REACTION_2D": _run_parabolic_2d,
    "DIFFUSION_REACTION_3D": _run_parabolic_3d,
    "ELLIPTIC_DIFFUSION_1D": _run_elliptic_1d,
    "ELLIPTIC_DIFFUSION_2D": _run_elliptic_2d,
    "WAVE_1D": _run_wave_1d,
    "WAVE_2D": _run_wave_2d,
    "SPHERICAL_RADIAL_THERMAL": _run_spherical_radial_thermal,
    "HEAT_DIFFUSION_1D": _run_parabolic_1d,
    "HEAT_DIFFUSION_2D": _run_parabolic_2d,
    "HEAT_DIFFUSION_3D": _run_parabolic_3d,
    "LINEAR_ADVECTION_1D": _run_parabolic_1d,
    "POISSON_1D": _run_elliptic_1d,
    "POISSON_2D": _run_elliptic_2d,
    "HELMHOLTZ_1D": _run_elliptic_1d,
    "HELMHOLTZ_2D": _run_elliptic_2d,
}


def pde_adapter_registry() -> PDEAdapterRegistry:
    """Return the fixed adapter registry derived from the executable dispatch table."""

    registry = PDEAdapterRegistry()
    grouped: dict[str, tuple[list[str], Any]] = {}
    for family_id, adapter in _PDE_SOLVER_ADAPTERS.items():
        capability = pde_capability(family_id)
        if capability is None:
            continue
        solver_id = str(capability["solver_id"])
        families, registered_adapter = grouped.setdefault(solver_id, ([], adapter))
        families.append(family_id)
        if registered_adapter is not adapter:
            raise PDESolverError(f"solver ID {solver_id} maps to multiple adapters")
    for solver_id, (families, adapter) in grouped.items():
        registry.register(solver_id=solver_id, family_ids=tuple(families), adapter=adapter)
    return registry


def pde_solver_is_available(system_type: str) -> bool:
    """Return whether a registered PDE family has a trusted adapter."""

    family_id = str(system_type).strip()
    return pde_adapter_registry().contains(family_id)


def execute_pdeir(document: Mapping[str, object], *, resource_limits: Mapping[str, object] | None = None) -> dict[str, Any]:
    """Validate and execute one PDEIR document through a fixed adapter."""

    normalized = materialize_pdeir_document(document)
    limits = _limits(resource_limits)
    _check_resource_budget(normalized, limits)
    system_type = str(normalized["system_type"])
    registered = pde_adapter_registry().get(system_type)
    if registered is None:
        raise PDESolverError(f"no approved PDE solver is registered for {system_type}")
    return registered.adapter(normalized, limits)


def apply_pde_scenario(document: Mapping[str, object], scenario: Mapping[str, object]) -> dict[str, Any]:
    """Apply only numeric declared-parameter overrides to a PDEIR document."""

    result = copy.deepcopy(dict(document))
    parameters = dict(_mapping(result.get("parameters")))
    overrides = _mapping(scenario.get("parameter_overrides"))
    unknown = set(overrides) - set(parameters)
    if unknown:
        raise PDESolverError("PDE scenario overrides reference undeclared parameters")
    for name, value in overrides.items():
        if isinstance(value, bool):
            raise PDESolverError("PDE scenario parameters must be numeric")
        try:
            numeric = float(value)
        except (TypeError, ValueError) as exc:
            raise PDESolverError("PDE scenario parameters must be numeric") from exc
        if not math.isfinite(numeric):
            raise PDESolverError("PDE scenario parameters must be finite")
        parameters[name] = numeric
    result["parameters"] = parameters
    return result


__all__ = [
    "PDESolverError",
    "apply_pde_scenario",
    "execute_pdeir",
    "pde_adapter_registry",
    "pde_solver_is_available",
]
