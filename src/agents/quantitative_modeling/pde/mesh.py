"""Bounded structured meshes used by the fixed PDE adapters."""

from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Mapping
from typing import Any


class MeshError(ValueError):
    """Raised when a structured mesh cannot be constructed safely."""


@dataclass(frozen=True)
class StructuredMesh:
    """Uniform one-, two-, or three-dimensional tensor-product mesh."""

    dimensions: int
    shape: tuple[int, ...]
    lower: tuple[float, ...]
    upper: tuple[float, ...]
    spacing: tuple[float, ...]
    coordinates: tuple[tuple[float, ...], ...]

    @property
    def cell_count(self) -> int:
        result = 1
        for size in self.shape:
            result *= size
        return result


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _axis_bounds(value: object, *, name: str) -> tuple[float, float]:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise MeshError(f"{name} must contain two bounds")
    lower, upper = float(value[0]), float(value[1])
    if not lower < upper:
        raise MeshError(f"{name} must be increasing")
    return lower, upper


def _axis_coordinates(lower: float, upper: float, count: int) -> tuple[float, ...]:
    if count < 3:
        raise MeshError("each mesh axis requires at least three points")
    step = (upper - lower) / (count - 1)
    return tuple(lower + index * step for index in range(count))


def build_structured_mesh(document: Mapping[str, object]) -> StructuredMesh:
    """Build a uniform mesh from canonical or documented PDE fields."""

    domain = _mapping(document.get("spatial_domain"))
    grid = _mapping(document.get("grid"))
    if "axes" in domain:
        axes = domain["axes"]
        if not isinstance(axes, (list, tuple)):
            raise MeshError("spatial_domain.axes must be a list")
        bounds: list[tuple[float, float]] = []
        for index, raw_axis in enumerate(axes):
            axis = _mapping(raw_axis)
            bounds.append(
                _axis_bounds(
                    [axis.get("lower"), axis.get("upper")],
                    name=f"spatial_domain.axes[{index}]",
                )
            )
        shape_values = grid.get("shape", grid.get("sizes"))
        if shape_values is None:
            raise MeshError("grid.shape is required when axes are used")
        if not isinstance(shape_values, (list, tuple)):
            raise MeshError("grid.shape must be a list")
        shape = tuple(int(value) for value in shape_values)
    else:
        names = ("x", "y", "z")
        dimensions = 3 if "z" in domain else 2 if "y" in domain else 1
        bounds = [_axis_bounds(domain.get(name), name=f"spatial_domain.{name}") for name in names[:dimensions]]
        shape = tuple(int(grid.get("n" + name)) for name in names[:dimensions])
    if len(bounds) != len(shape) or len(bounds) not in (1, 2, 3):
        raise MeshError("only one-, two-, and three-dimensional meshes are supported")
    if any(size < 3 for size in shape):
        raise MeshError("each mesh axis requires at least three points")
    coordinates = tuple(_axis_coordinates(lower, upper, size) for (lower, upper), size in zip(bounds, shape))
    return StructuredMesh(
        dimensions=len(bounds),
        shape=shape,
        lower=tuple(item[0] for item in bounds),
        upper=tuple(item[1] for item in bounds),
        spacing=tuple((item[1] - item[0]) / (size - 1) for item, size in zip(bounds, shape)),
        coordinates=coordinates,
    )


__all__ = ["MeshError", "StructuredMesh", "build_structured_mesh"]
