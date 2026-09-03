"""Registered PDE families and their trusted numerical adapters."""

from __future__ import annotations

from typing import Any


PDE_IMPLEMENTATION_VERSION = "pde-fixed-backends-v1"


PDE_CAPABILITIES: dict[str, dict[str, Any]] = {
    "DIFFUSION_REACTION_1D": {
        "dimensions": [1],
        "temporal": True,
        "field_count": {"min": 1, "max": 1},
        "boundary_conditions": ["DIRICHLET", "NEUMANN_ZERO", "NEUMANN", "PERIODIC"],
        "discretizations": ["FINITE_DIFFERENCE"],
        "time_integrators": ["EXPLICIT_EULER"],
        "solver_id": "pde_fd_diffusion_reaction_1d",
        "execution_status": "EXECUTABLE",
        "solver_family": "parabolic_1d",
    },
    "ADVECTION_DIFFUSION_REACTION_1D": {
        "dimensions": [1],
        "temporal": True,
        "field_count": {"min": 1, "max": 1},
        "boundary_conditions": ["DIRICHLET", "NEUMANN_ZERO", "NEUMANN", "PERIODIC"],
        "discretizations": ["FINITE_DIFFERENCE"],
        "time_integrators": ["EXPLICIT_EULER", "SSPRK2"],
        "solver_id": "pde_fd_advection_diffusion_reaction_1d",
        "execution_status": "EXECUTABLE",
        "solver_family": "parabolic_1d",
    },
    "BURGERS_1D": {
        "dimensions": [1],
        "temporal": True,
        "field_count": {"min": 1, "max": 1},
        "boundary_conditions": ["DIRICHLET", "NEUMANN_ZERO", "NEUMANN", "PERIODIC"],
        "discretizations": ["FINITE_DIFFERENCE"],
        "time_integrators": ["EXPLICIT_EULER", "SSPRK2"],
        "solver_id": "pde_fd_burgers_1d",
        "execution_status": "EXECUTABLE",
        "solver_family": "parabolic_1d_nonlinear_advection",
    },
    "DIFFUSION_REACTION_2D": {
        "dimensions": [2],
        "temporal": True,
        "field_count": {"min": 1, "max": 1},
        "boundary_conditions": ["DIRICHLET", "NEUMANN_ZERO", "NEUMANN", "PERIODIC"],
        "discretizations": ["FINITE_DIFFERENCE"],
        "time_integrators": ["EXPLICIT_EULER"],
        "solver_id": "pde_fd_diffusion_reaction_2d",
        "execution_status": "EXECUTABLE",
        "solver_family": "parabolic_2d",
    },
    "DIFFUSION_REACTION_3D": {
        "dimensions": [3],
        "temporal": True,
        "field_count": {"min": 1, "max": 1},
        "boundary_conditions": ["DIRICHLET", "NEUMANN_ZERO", "NEUMANN", "PERIODIC"],
        "discretizations": ["FINITE_DIFFERENCE"],
        "time_integrators": ["EXPLICIT_EULER"],
        "solver_id": "pde_fd_diffusion_reaction_3d",
        "execution_status": "EXECUTABLE",
        "solver_family": "parabolic_3d",
    },
    "ELLIPTIC_DIFFUSION_1D": {
        "dimensions": [1],
        "temporal": False,
        "field_count": {"min": 1, "max": 1},
        "boundary_conditions": ["DIRICHLET", "NEUMANN_ZERO", "NEUMANN"],
        "discretizations": ["FINITE_DIFFERENCE"],
        "time_integrators": [],
        "solver_id": "pde_fd_elliptic_diffusion_1d",
        "execution_status": "EXECUTABLE",
        "solver_family": "elliptic_1d",
    },
    "ELLIPTIC_DIFFUSION_2D": {
        "dimensions": [2],
        "temporal": False,
        "field_count": {"min": 1, "max": 1},
        "boundary_conditions": ["DIRICHLET", "NEUMANN_ZERO", "NEUMANN"],
        "discretizations": ["FINITE_DIFFERENCE"],
        "time_integrators": [],
        "solver_id": "pde_fd_elliptic_diffusion_2d",
        "execution_status": "EXECUTABLE",
        "solver_family": "elliptic_2d",
    },
    "WAVE_1D": {
        "dimensions": [1],
        "temporal": True,
        "field_count": {"min": 1, "max": 1},
        "boundary_conditions": ["DIRICHLET", "NEUMANN_ZERO"],
        "discretizations": ["FINITE_DIFFERENCE"],
        "time_integrators": ["EXPLICIT_CENTRAL"],
        "solver_id": "pde_fd_wave_1d",
        "execution_status": "EXECUTABLE",
        "solver_family": "wave_1d",
    },
    "WAVE_2D": {
        "dimensions": [2],
        "temporal": True,
        "field_count": {"min": 1, "max": 1},
        "boundary_conditions": ["DIRICHLET", "NEUMANN_ZERO"],
        "discretizations": ["FINITE_DIFFERENCE"],
        "time_integrators": ["EXPLICIT_CENTRAL"],
        "solver_id": "pde_fd_wave_2d",
        "execution_status": "EXECUTABLE",
        "solver_family": "wave_2d",
    },
    "HEAT_DIFFUSION_1D": {
        "dimensions": [1],
        "temporal": True,
        "field_count": {"min": 1, "max": 1},
        "boundary_conditions": ["DIRICHLET", "NEUMANN_ZERO", "NEUMANN", "PERIODIC"],
        "discretizations": ["FINITE_DIFFERENCE"],
        "time_integrators": ["EXPLICIT_EULER", "SSPRK2"],
        "solver_id": "pde_fd_heat_diffusion_1d",
        "execution_status": "EXECUTABLE",
        "solver_family": "parabolic_1d",
    },
    "HEAT_DIFFUSION_2D": {
        "dimensions": [2],
        "temporal": True,
        "field_count": {"min": 1, "max": 1},
        "boundary_conditions": ["DIRICHLET", "NEUMANN_ZERO", "NEUMANN", "PERIODIC"],
        "discretizations": ["FINITE_DIFFERENCE"],
        "time_integrators": ["EXPLICIT_EULER"],
        "solver_id": "pde_fd_heat_diffusion_2d",
        "execution_status": "EXECUTABLE",
        "solver_family": "parabolic_2d",
    },
    "HEAT_DIFFUSION_3D": {
        "dimensions": [3],
        "temporal": True,
        "field_count": {"min": 1, "max": 1},
        "boundary_conditions": ["DIRICHLET", "NEUMANN_ZERO", "NEUMANN", "PERIODIC"],
        "discretizations": ["FINITE_DIFFERENCE"],
        "time_integrators": ["EXPLICIT_EULER"],
        "solver_id": "pde_fd_heat_diffusion_3d",
        "execution_status": "EXECUTABLE",
        "solver_family": "parabolic_3d",
    },
    "LINEAR_ADVECTION_1D": {
        "dimensions": [1],
        "temporal": True,
        "field_count": {"min": 1, "max": 1},
        "boundary_conditions": ["DIRICHLET", "NEUMANN_ZERO", "PERIODIC"],
        "discretizations": ["FINITE_DIFFERENCE"],
        "time_integrators": ["EXPLICIT_EULER", "SSPRK2"],
        "solver_id": "pde_fd_linear_advection_1d",
        "execution_status": "EXECUTABLE",
        "solver_family": "parabolic_1d",
    },
    "POISSON_1D": {
        "dimensions": [1],
        "temporal": False,
        "field_count": {"min": 1, "max": 1},
        "boundary_conditions": ["DIRICHLET", "NEUMANN_ZERO", "NEUMANN"],
        "discretizations": ["FINITE_DIFFERENCE"],
        "time_integrators": [],
        "solver_id": "pde_fd_poisson_1d",
        "execution_status": "EXECUTABLE",
        "solver_family": "elliptic_1d",
    },
    "POISSON_2D": {
        "dimensions": [2],
        "temporal": False,
        "field_count": {"min": 1, "max": 1},
        "boundary_conditions": ["DIRICHLET", "NEUMANN_ZERO", "NEUMANN"],
        "discretizations": ["FINITE_DIFFERENCE"],
        "time_integrators": [],
        "solver_id": "pde_fd_poisson_2d",
        "execution_status": "EXECUTABLE",
        "solver_family": "elliptic_2d",
    },
    "HELMHOLTZ_1D": {
        "dimensions": [1],
        "temporal": False,
        "field_count": {"min": 1, "max": 1},
        "boundary_conditions": ["DIRICHLET", "NEUMANN_ZERO", "NEUMANN"],
        "discretizations": ["FINITE_DIFFERENCE"],
        "time_integrators": [],
        "solver_id": "pde_fd_helmholtz_1d",
        "execution_status": "EXECUTABLE",
        "solver_family": "elliptic_1d",
    },
    "HELMHOLTZ_2D": {
        "dimensions": [2],
        "temporal": False,
        "field_count": {"min": 1, "max": 1},
        "boundary_conditions": ["DIRICHLET", "NEUMANN_ZERO", "NEUMANN"],
        "discretizations": ["FINITE_DIFFERENCE"],
        "time_integrators": [],
        "solver_id": "pde_fd_helmholtz_2d",
        "execution_status": "EXECUTABLE",
        "solver_family": "elliptic_2d",
    },
    "SPHERICAL_RADIAL_THERMAL": {
        "dimensions": [1],
        "temporal": True,
        "field_count": {"min": 1, "max": 1},
        "boundary_conditions": ["SPHERICAL_ORIGIN_REGULARITY", "DIRICHLET", "NEUMANN", "NEUMANN_ZERO"],
        "discretizations": ["FINITE_DIFFERENCE_SPHERICAL_RADIAL"],
        "time_integrators": ["EXPLICIT_EULER"],
        "solver_id": "pde_fd_spherical_radial_thermal",
        "execution_status": "EXECUTABLE",
        "solver_family": "spherical_radial_thermal",
    },
}


EXECUTABLE_PDE_SYSTEMS = frozenset(
    name for name, capability in PDE_CAPABILITIES.items() if capability["execution_status"] == "EXECUTABLE"
)


def pde_capability(system_type: str) -> dict[str, Any] | None:
    """Return a copy of a registered PDE capability description."""

    capability = PDE_CAPABILITIES.get(str(system_type).strip())
    return {**dict(capability), "implementation_version": PDE_IMPLEMENTATION_VERSION} if capability is not None else None


def pde_is_executable(system_type: str) -> bool:
    """Return whether a trusted PDE adapter is registered."""

    return str(system_type).strip() in EXECUTABLE_PDE_SYSTEMS


def executable_pde_catalog() -> list[dict[str, Any]]:
    """Return bounded capability metadata suitable for an LLM model prompt."""

    catalog: list[dict[str, Any]] = []
    for system_type in sorted(EXECUTABLE_PDE_SYSTEMS):
        capability = PDE_CAPABILITIES[system_type]
        catalog.append(
            {
                "system_type": system_type,
                "dimensions": list(capability["dimensions"]),
                "temporal": bool(capability["temporal"]),
                "boundary_conditions": list(capability["boundary_conditions"]),
                "discretizations": list(capability["discretizations"]),
                "time_integrators": list(capability["time_integrators"]),
                "solver_id": capability["solver_id"],
                "solver_family": capability.get("solver_family", ""),
                "implementation_version": PDE_IMPLEMENTATION_VERSION,
                "execution_status": capability.get("execution_status", "DESIGN_ONLY"),
                "field_count": dict(capability.get("field_count", {})),
            }
        )
    return catalog


def design_pde_catalog() -> list[dict[str, Any]]:
    """Return registered PDE families that require a future specialized backend."""

    return [
        {
            "system_type": system_type,
            "dimensions": list(capability.get("dimensions", [])),
            "temporal": bool(capability.get("temporal", False)),
            "boundary_conditions": list(capability.get("boundary_conditions", [])),
            "discretizations": list(capability.get("discretizations", [])),
            "time_integrators": list(capability.get("time_integrators", [])),
            "solver_id": str(capability.get("solver_id", "")),
            "solver_family": str(capability.get("solver_family", "")),
            "implementation_version": PDE_IMPLEMENTATION_VERSION,
            "execution_status": str(capability.get("execution_status", "DESIGN_ONLY")),
            "field_count": dict(capability.get("field_count", {})),
        }
        for system_type, capability in sorted(PDE_CAPABILITIES.items())
        if capability.get("execution_status") != "EXECUTABLE"
    ]


def validate_pde_registry() -> list[str]:
    """Report registration/backend mismatches without executing a model."""

    from src.agents.quantitative_modeling.pde_solver import pde_solver_is_available

    errors: list[str] = []
    for system_type, capability in sorted(PDE_CAPABILITIES.items()):
        if capability.get("execution_status") != "EXECUTABLE":
            continue
        if not str(capability.get("solver_id", "")).strip():
            errors.append(f"{system_type}: executable family has no solver_id")
        if not pde_solver_is_available(system_type):
            errors.append(f"{system_type}: executable family has no trusted adapter")
    return errors


__all__ = [
    "EXECUTABLE_PDE_SYSTEMS",
    "PDE_CAPABILITIES",
    "PDE_IMPLEMENTATION_VERSION",
    "design_pde_catalog",
    "executable_pde_catalog",
    "pde_capability",
    "pde_is_executable",
    "validate_pde_registry",
]
