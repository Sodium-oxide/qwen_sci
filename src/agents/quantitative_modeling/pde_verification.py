"""Numerical verification helpers for PDE execution records."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

from src.agents.quantitative_modeling.pdeir import evaluate_pde_expression


PDE_VERIFICATION_SCHEMA_VERSION = "pde_verification_v1"


class PDEVerificationError(ValueError):
    """Raised when a PDE result cannot be checked."""


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _finite(value: object) -> bool:
    if isinstance(value, bool):
        return True
    if isinstance(value, (int, float)):
        return math.isfinite(float(value))
    if isinstance(value, Mapping):
        return all(_finite(item) for item in value.values())
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return all(_finite(item) for item in value)
    return value is None or isinstance(value, str)


def _series_values(result: Mapping[str, object]) -> list[float]:
    field_series = _mapping(result.get("field_series"))
    values: list[float] = []
    for raw_series in field_series.values():
        if not isinstance(raw_series, Sequence) or isinstance(raw_series, (str, bytes, bytearray)):
            raise PDEVerificationError("field_series must contain arrays")
        for snapshot in raw_series:
            if not isinstance(snapshot, Sequence) or isinstance(snapshot, (str, bytes, bytearray)):
                raise PDEVerificationError("field_series snapshots must be arrays")
            values.extend(float(item) for item in snapshot)
    if not values:
        field = _mapping(result.get("field"))
        for raw_values in field.values():
            if isinstance(raw_values, Sequence) and not isinstance(raw_values, (str, bytes, bytearray)):
                values.extend(float(item) for item in raw_values)
    return values


def _boundary_expression_value(
    boundary: Mapping[str, object],
    *,
    x: float,
    y: float | None,
    t: float,
    parameters: Mapping[str, float],
    z: float | None = None,
) -> float:
    expression = boundary.get("value")
    if not isinstance(expression, Mapping):
        return float(expression)
    environment = {"x": x, "t": t, **parameters}
    if y is not None:
        environment["y"] = y
    if z is not None:
        environment["z"] = z
    return float(evaluate_pde_expression(expression, environment))


def _max_boundary_residual(
    document: Mapping[str, object],
    result: Mapping[str, object],
) -> tuple[float, dict[str, float]]:
    """Compute residuals from the final sampled field when a document is available."""

    if not document:
        return 0.0, {}
    fields = document.get("fields")
    if not isinstance(fields, Sequence) or not fields:
        return 0.0, {}
    field_id = str(dict(fields[0]).get("id") or "") if isinstance(fields[0], Mapping) else ""
    series = _mapping(result.get("field_series"))
    if series and isinstance(series.get(field_id), Sequence):
        raw_snapshots = series[field_id]
        if not raw_snapshots:
            return 0.0, {}
        values = [float(item) for item in raw_snapshots[-1]]
        raw_times = result.get("time")
        time_value = float(raw_times[-1]) if isinstance(raw_times, Sequence) and raw_times else 0.0
    else:
        field = _mapping(result.get("field"))
        raw_values = field.get(field_id)
        if not isinstance(raw_values, Sequence):
            return 0.0, {}
        values = [float(item) for item in raw_values]
        time_value = 0.0
    domain = _mapping(document.get("spatial_domain"))
    grid = _mapping(document.get("grid"))
    boundaries = _mapping(document.get("boundary_conditions"))
    parameters = {str(key): float(value) for key, value in _mapping(document.get("parameters")).items()}
    residuals: dict[str, float] = {}
    if "nz" in grid:
        nx, ny, nz = int(grid["nx"]), int(grid["ny"]), int(grid["nz"])
        cells = nx * ny * nz
        if len(values) != cells:
            return 0.0, {}
        x0, x1 = (float(item) for item in domain["x"])
        y0, y1 = (float(item) for item in domain["y"])
        z0, z1 = (float(item) for item in domain["z"])
        dx, dy, dz = (x1 - x0) / (nx - 1), (y1 - y0) / (ny - 1), (z1 - z0) / (nz - 1)
        plane = nx * ny
        faces = (
            ("left", [nx * (j + ny * k) for k in range(nz) for j in range(ny)], dx, 1, -1.0),
            ("right", [nx * (j + ny * k) + nx - 1 for k in range(nz) for j in range(ny)], dx, -1, 1.0),
            ("bottom", [i + nx * ny * k for k in range(nz) for i in range(nx)], dy, nx, -1.0),
            ("top", [i + nx * (ny - 1) + nx * ny * k for k in range(nz) for i in range(nx)], dy, -nx, 1.0),
            ("front", [i + nx * j for j in range(ny) for i in range(nx)], dz, plane, -1.0),
            ("back", [i + nx * j + plane * (nz - 1) for j in range(ny) for i in range(nx)], dz, -plane, 1.0),
        )
        for side, indices, spacing, neighbor_offset, outward_sign in faces:
            boundary = _mapping(boundaries.get(side))
            kind = str(boundary.get("type") or "")
            if kind not in {"DIRICHLET", "NEUMANN", "NEUMANN_ZERO"}:
                continue
            side_values: list[float] = []
            for index in indices:
                i = index % nx
                j = (index % plane) // nx
                k = index // plane
                coordinate_x = x0 + i * dx
                coordinate_y = y0 + j * dy
                coordinate_z = z0 + k * dz
                if kind == "DIRICHLET":
                    side_values.append(
                        abs(
                            values[index]
                            - _boundary_expression_value(
                                boundary,
                                x=coordinate_x,
                                y=coordinate_y,
                                z=coordinate_z,
                                t=time_value,
                                parameters=parameters,
                            )
                        )
                    )
                else:
                    target = 0.0 if kind == "NEUMANN_ZERO" else _boundary_expression_value(
                        boundary,
                        x=coordinate_x,
                        y=coordinate_y,
                        z=coordinate_z,
                        t=time_value,
                        parameters=parameters,
                    )
                    neighbor = index + neighbor_offset
                    side_values.append(abs(outward_sign * (values[index] - values[neighbor]) / spacing - target))
            if side_values:
                residuals[side] = max(side_values)
        periodic_mismatch: list[float] = []
        if _mapping(boundaries.get("left")).get("type") == "PERIODIC" and _mapping(boundaries.get("right")).get("type") == "PERIODIC":
            for k in range(nz):
                for j in range(ny):
                    row = nx * (j + ny * k)
                    periodic_mismatch.extend((abs(values[row] - values[row + nx - 2]), abs(values[row + nx - 1] - values[row + 1])))
        if _mapping(boundaries.get("bottom")).get("type") == "PERIODIC" and _mapping(boundaries.get("top")).get("type") == "PERIODIC":
            for k in range(nz):
                for i in range(nx):
                    bottom = i + plane * k
                    top = i + nx * (ny - 1) + plane * k
                    periodic_mismatch.extend((abs(values[bottom] - values[i + nx * (ny - 2) + plane * k]), abs(values[top] - values[i + nx + plane * k])))
        if _mapping(boundaries.get("front")).get("type") == "PERIODIC" and _mapping(boundaries.get("back")).get("type") == "PERIODIC":
            for j in range(ny):
                for i in range(nx):
                    front = i + nx * j
                    back = front + plane * (nz - 1)
                    periodic_mismatch.extend((abs(values[front] - values[front + plane * (nz - 2)]), abs(values[back] - values[front + plane])))
        if periodic_mismatch:
            residuals["periodic"] = max(periodic_mismatch)
    elif "ny" not in grid:
        nx = int(grid.get("nx", len(values)))
        if nx < 3 or len(values) != nx:
            return 0.0, {}
        x0, x1 = (float(item) for item in domain["x"])
        dx = (x1 - x0) / (nx - 1)
        for side, index, neighbor, coordinate, sign in (
            ("left", 0, 1, x0, -1.0),
            ("right", nx - 1, nx - 2, x1, 1.0),
        ):
            boundary = _mapping(boundaries.get(side))
            kind = str(boundary.get("type") or "")
            if kind == "SPHERICAL_ORIGIN_REGULARITY":
                residuals[side] = abs(values[index] - values[neighbor]) / dx
            elif kind == "DIRICHLET":
                residuals[side] = abs(values[index] - _boundary_expression_value(boundary, x=coordinate, y=None, t=time_value, parameters=parameters))
            elif kind in {"NEUMANN", "NEUMANN_ZERO"}:
                target = 0.0 if kind == "NEUMANN_ZERO" else _boundary_expression_value(boundary, x=coordinate, y=None, t=time_value, parameters=parameters)
                residuals[side] = abs(sign * (values[index] - values[neighbor]) / dx - target)
        if str(_mapping(boundaries.get("left")).get("type")) == "PERIODIC" and str(_mapping(boundaries.get("right")).get("type")) == "PERIODIC":
            residuals["periodic"] = max(abs(values[0] - values[-2]), abs(values[-1] - values[1]))
    else:
        nx, ny = int(grid["nx"]), int(grid["ny"])
        if len(values) != nx * ny:
            return 0.0, {}
        x0, x1 = (float(item) for item in domain["x"])
        y0, y1 = (float(item) for item in domain["y"])
        dx, dy = (x1 - x0) / (nx - 1), (y1 - y0) / (ny - 1)
        sides = (
            ("left", range(0, nx * ny, nx), x0, dx, "x"),
            ("right", range(nx - 1, nx * ny, nx), x1, dx, "x"),
            ("bottom", range(nx), y0, dy, "y"),
            ("top", range((ny - 1) * nx, ny * nx), y1, dy, "y"),
        )
        for side, indices, coordinate, spacing, axis in sides:
            boundary = _mapping(boundaries.get(side))
            kind = str(boundary.get("type") or "")
            side_values: list[float] = []
            for index in indices:
                i, j = index % nx, index // nx
                coordinate_x = x0 + i * dx
                coordinate_y = y0 + j * dy
                neighbor = index + 1 if side == "left" else index - 1 if side == "right" else index + nx if side == "bottom" else index - nx
                if kind == "DIRICHLET":
                    side_values.append(abs(values[index] - _boundary_expression_value(boundary, x=coordinate_x, y=coordinate_y, t=time_value, parameters=parameters)))
                elif kind in {"NEUMANN", "NEUMANN_ZERO"}:
                    target = 0.0 if kind == "NEUMANN_ZERO" else _boundary_expression_value(boundary, x=coordinate_x, y=coordinate_y, t=time_value, parameters=parameters)
                    outward = -1.0 if side in {"left", "bottom"} else 1.0
                    side_values.append(abs(outward * (values[index] - values[neighbor]) / spacing - target))
            if side_values:
                residuals[side] = max(side_values)
    return max(residuals.values(), default=0.0), residuals


def verify_pde_result(
    result: Mapping[str, object],
    *,
    document: Mapping[str, object] | None = None,
    required_checks: Sequence[str] = (),
    bounds: Mapping[str, object] | None = None,
) -> dict[str, Any]:
    """Check finite output and solver diagnostics without re-running the solver."""

    if result.get("status") != "COMPLETED":
        raise PDEVerificationError("only completed PDE results can be verified")
    values = _series_values(result)
    checks: dict[str, bool] = {
        "finite_field": bool(values) and all(math.isfinite(value) for value in values),
    }
    numerical_checks = _mapping(result.get("numerical_checks"))
    for name, value in numerical_checks.items():
        checks[str(name)] = bool(value)
    summary = _mapping(result.get("summary"))
    if "maximum_diffusion_courant" in summary:
        stability_limit = float(summary.get("stability_limit", 0.5))
        checks["explicit_stability"] = float(summary["maximum_diffusion_courant"]) <= stability_limit + 1e-12
    if "maximum_advection_courant" in summary:
        checks["advection_stability"] = float(summary["maximum_advection_courant"]) <= 1.0 + 1e-12
    if "courant_number" in summary:
        checks["wave_cfl"] = float(summary["courant_number"]) <= 1.0 + 1e-12
    if "linear_residual" in summary:
        checks["linear_residual"] = float(summary["linear_residual"]) <= 1e-8
    boundary_residual, boundary_residuals = _max_boundary_residual(document or {}, result)
    checks["boundary_residual"] = boundary_residual <= 1e-8 if boundary_residuals else True
    checks["periodic_mismatch"] = boundary_residuals.get("periodic", 0.0) <= 1e-8
    if bounds is None:
        fields = document.get("fields") if document else None
        if isinstance(fields, Sequence) and fields and isinstance(fields[0], Mapping):
            bounds = _mapping(fields[0]).get("bounds")
    bounds_payload = _mapping(bounds)
    if "lower" in bounds_payload:
        checks["lower_bound"] = min(values) >= float(bounds_payload["lower"]) - 1e-12
    if "upper" in bounds_payload:
        checks["upper_bound"] = max(values) <= float(bounds_payload["upper"]) + 1e-12
    requested = list(dict.fromkeys(str(name).strip() for name in required_checks))
    if any(not name for name in requested):
        raise PDEVerificationError("required_checks cannot contain empty names")
    required_results = {name: checks.get(name, False) for name in requested}
    checks_passed = all(required_results.values()) if required_results else all(checks.values())
    return {
        "schema_version": PDE_VERIFICATION_SCHEMA_VERSION,
        "status": "NUMERICALLY_VERIFIED" if checks_passed else "NUMERICALLY_UNVERIFIED",
        "checks": checks,
        "required_checks": requested,
        "required_check_results": required_results,
        "finite_output": _finite(result),
        "sampled_value_count": len(values),
        "boundary_residual": boundary_residual,
        "boundary_residuals": boundary_residuals,
    }


__all__ = ["PDE_VERIFICATION_SCHEMA_VERSION", "PDEVerificationError", "verify_pde_result"]
