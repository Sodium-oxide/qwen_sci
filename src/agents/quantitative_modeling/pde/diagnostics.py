"""Non-executing resource and stability estimates for PDE plans."""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

from src.agents.quantitative_modeling.pde_capability_registry import pde_capability
from src.agents.quantitative_modeling.pde_solver import pde_solver_is_available
from src.agents.quantitative_modeling.pdeir import validate_pdeir_document


class PDEDiagnosticsError(ValueError):
    """Raised when a PDE dry-run estimate cannot be produced."""


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _positive_limit(value: object, *, name: str, default: int) -> int:
    try:
        parsed = int(default if value is None else value)
    except (TypeError, ValueError) as exc:
        raise PDEDiagnosticsError(f"{name} must be an integer") from exc
    if parsed < 1:
        raise PDEDiagnosticsError(f"{name} must be positive")
    return parsed


def estimate_pde_execution(
    document: Mapping[str, object],
    *,
    resource_limits: Mapping[str, object] | None = None,
) -> dict[str, Any]:
    """Estimate work and memory without starting a solver."""

    normalized = validate_pdeir_document(document)
    system_type = str(normalized["system_type"])
    capability = pde_capability(system_type)
    if capability is None or not pde_solver_is_available(system_type):
        raise PDEDiagnosticsError(f"no approved solver is available for {system_type}")
    grid = _mapping(normalized["grid"])
    cells = int(grid["nx"]) * int(grid.get("ny", 1)) * int(grid.get("nz", 1))
    fields = len(normalized["fields"])
    options = _mapping(normalized.get("solver_options"))
    raw_limits = _mapping(resource_limits)
    if "max_snapshots" not in raw_limits and "max_pde_snapshots" in raw_limits:
        raw_limits["max_snapshots"] = raw_limits["max_pde_snapshots"]
    if capability["temporal"]:
        start, end = (float(item) for item in normalized["time_span"])
        time_step = float(options["time_step"])
        time_steps = math.ceil((end - start) / time_step)
        snapshots = min(
            time_steps + 1,
            _positive_limit(raw_limits.get("max_snapshots"), name="max_snapshots", default=200),
        )
    else:
        time_steps = 0
        snapshots = 1
    limits = raw_limits
    max_cells = _positive_limit(limits.get("max_cells"), name="max_cells", default=100_000)
    max_nx = _positive_limit(limits.get("max_nx"), name="max_nx", default=4_096)
    max_ny = _positive_limit(limits.get("max_ny"), name="max_ny", default=1_024)
    max_nz = _positive_limit(limits.get("max_nz"), name="max_nz", default=128)
    max_time_steps = _positive_limit(limits.get("max_time_steps"), name="max_time_steps", default=20_000)
    max_memory_mb = _positive_limit(limits.get("max_memory_mb"), name="max_memory_mb", default=512)
    estimated_values = cells * fields * snapshots
    estimated_memory_bytes = estimated_values * 8
    return {
        "schema_version": "pde_dry_run_v1",
        "system_type": system_type,
        "solver_id": str(capability["solver_id"]),
        "solver_family": str(capability["solver_family"]),
        "grid_shape": [int(grid["nx"])]
        + ([int(grid["ny"])] if "ny" in grid else [])
        + ([int(grid["nz"])] if "nz" in grid else []),
        "cell_count": cells,
        "field_count": fields,
        "time_steps": time_steps,
        "snapshot_count": snapshots,
        "estimated_value_count": estimated_values,
        "estimated_memory_bytes": estimated_memory_bytes,
        "estimated_memory_mb": estimated_memory_bytes / (1024 * 1024),
        "limits": {
            "max_cells": max_cells,
            "max_nx": max_nx,
            "max_ny": max_ny,
            "max_nz": max_nz,
            "max_time_steps": max_time_steps,
            "max_memory_mb": max_memory_mb,
        },
        "within_limits": {
            "cells": cells <= max_cells,
            "nx": int(grid["nx"]) <= max_nx,
            "ny": int(grid.get("ny", 1)) <= max_ny,
            "nz": int(grid.get("nz", 1)) <= max_nz,
            "time_steps": time_steps <= max_time_steps,
            "memory": estimated_memory_bytes <= max_memory_mb * 1024 * 1024,
        },
        "execution_status": "READY"
        if cells <= max_cells
        and int(grid["nx"]) <= max_nx
        and int(grid.get("ny", 1)) <= max_ny
        and int(grid.get("nz", 1)) <= max_nz
        and time_steps <= max_time_steps
        and estimated_memory_bytes <= max_memory_mb * 1024 * 1024
        else "REJECTED",
    }


__all__ = ["PDEDiagnosticsError", "estimate_pde_execution"]
