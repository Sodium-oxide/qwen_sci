"""Pure, bounded finite-difference spatial operators."""

from __future__ import annotations

import math
from collections.abc import Sequence


class OperatorError(ValueError):
    """Raised when an operator receives an incompatible field."""


def _values(field: Sequence[float]) -> list[float]:
    if isinstance(field, (str, bytes, bytearray)) or len(field) < 3:
        raise OperatorError("a field must contain at least three numeric values")
    values = [float(item) for item in field]
    if not all(math.isfinite(item) for item in values):
        raise OperatorError("field values must be finite")
    return values


def gradient_1d(field: Sequence[float], spacing: float) -> list[float]:
    values = _values(field)
    if spacing <= 0 or not math.isfinite(spacing):
        raise OperatorError("spacing must be positive and finite")
    result = [0.0] * len(values)
    result[0] = (values[1] - values[0]) / spacing
    result[-1] = (values[-1] - values[-2]) / spacing
    for index in range(1, len(values) - 1):
        result[index] = (values[index + 1] - values[index - 1]) / (2.0 * spacing)
    return result


def upwind_derivative_1d(field: Sequence[float], spacing: float, velocity: float) -> list[float]:
    values = _values(field)
    if spacing <= 0 or not math.isfinite(spacing):
        raise OperatorError("spacing must be positive and finite")
    result = [0.0] * len(values)
    for index in range(1, len(values) - 1):
        if velocity >= 0:
            result[index] = (values[index] - values[index - 1]) / spacing
        else:
            result[index] = (values[index + 1] - values[index]) / spacing
    result[0], result[-1] = result[1], result[-2]
    return result


def laplacian_1d(field: Sequence[float], spacing: float) -> list[float]:
    values = _values(field)
    if spacing <= 0 or not math.isfinite(spacing):
        raise OperatorError("spacing must be positive and finite")
    scale = spacing * spacing
    result = [0.0] * len(values)
    for index in range(1, len(values) - 1):
        result[index] = (values[index + 1] - 2.0 * values[index] + values[index - 1]) / scale
    result[0], result[-1] = result[1], result[-2]
    return result


def laplacian_2d(field: Sequence[float], nx: int, ny: int, dx: float, dy: float) -> list[float]:
    values = _values(field)
    if len(values) != nx * ny:
        raise OperatorError("2D field length does not match the mesh")
    if min(dx, dy) <= 0 or not all(math.isfinite(item) for item in (dx, dy)):
        raise OperatorError("mesh spacing must be positive and finite")
    result = [0.0] * len(values)
    dx2, dy2 = dx * dx, dy * dy
    for j in range(1, ny - 1):
        for i in range(1, nx - 1):
            index = j * nx + i
            result[index] = (
                (values[index + 1] - 2.0 * values[index] + values[index - 1]) / dx2
                + (values[index + nx] - 2.0 * values[index] + values[index - nx]) / dy2
            )
    for i in range(nx):
        result[i] = result[nx + i]
        result[(ny - 1) * nx + i] = result[(ny - 2) * nx + i]
    for j in range(ny):
        result[j * nx] = result[j * nx + 1]
        result[j * nx + nx - 1] = result[j * nx + nx - 2]
    return result


def laplacian_3d(field: Sequence[float], nx: int, ny: int, nz: int, dx: float, dy: float, dz: float) -> list[float]:
    values = _values(field)
    if len(values) != nx * ny * nz:
        raise OperatorError("3D field length does not match the mesh")
    if min(dx, dy, dz) <= 0 or not all(math.isfinite(item) for item in (dx, dy, dz)):
        raise OperatorError("mesh spacing must be positive and finite")
    result = [0.0] * len(values)
    plane = nx * ny
    dx2, dy2, dz2 = dx * dx, dy * dy, dz * dz
    for k in range(1, nz - 1):
        for j in range(1, ny - 1):
            for i in range(1, nx - 1):
                index = i + nx * (j + ny * k)
                result[index] = (
                    (values[index + 1] - 2.0 * values[index] + values[index - 1]) / dx2
                    + (values[index + nx] - 2.0 * values[index] + values[index - nx]) / dy2
                    + (values[index + plane] - 2.0 * values[index] + values[index - plane]) / dz2
                )
    for k in range(nz):
        layer = plane * k
        for i in range(nx):
            result[layer + i] = result[layer + nx + i]
            result[layer + (ny - 1) * nx + i] = result[layer + (ny - 2) * nx + i]
        for j in range(ny):
            row = layer + j * nx
            result[row] = result[row + 1]
            result[row + nx - 1] = result[row + nx - 2]
    for j in range(ny):
        for i in range(nx):
            result[i + nx * j] = result[plane + i + nx * j]
            result[plane * (nz - 1) + i + nx * j] = result[plane * (nz - 2) + i + nx * j]
    return result


def divergence_2d(
    flux_x: Sequence[float],
    flux_y: Sequence[float],
    nx: int,
    ny: int,
    dx: float,
    dy: float,
) -> list[float]:
    x_values = _values(flux_x)
    y_values = _values(flux_y)
    if len(x_values) != nx * ny or len(y_values) != nx * ny:
        raise OperatorError("flux lengths do not match the mesh")
    if min(dx, dy) <= 0:
        raise OperatorError("mesh spacing must be positive")
    result = [0.0] * (nx * ny)
    for j in range(1, ny - 1):
        for i in range(1, nx - 1):
            index = j * nx + i
            result[index] = (
                (x_values[index + 1] - x_values[index - 1]) / (2.0 * dx)
                + (y_values[index + nx] - y_values[index - nx]) / (2.0 * dy)
            )
    return result


__all__ = [
    "OperatorError",
    "divergence_2d",
    "gradient_1d",
    "laplacian_1d",
    "laplacian_2d",
    "laplacian_3d",
    "upwind_derivative_1d",
]
