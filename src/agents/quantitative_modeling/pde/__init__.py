"""Reusable building blocks for declarative PDE execution."""

from .adapters import PDEAdapter, PDEAdapterRegistry
from .convergence import (
    PDEConvergenceError,
    build_refinement_documents,
    build_refinement_plans,
    estimate_convergence_order,
)
from .mesh import StructuredMesh, build_structured_mesh
from .operators import (
    divergence_2d,
    gradient_1d,
    laplacian_1d,
    laplacian_2d,
    laplacian_3d,
    upwind_derivative_1d,
)

__all__ = [
    "PDEAdapter",
    "PDEAdapterRegistry",
    "PDEConvergenceError",
    "StructuredMesh",
    "build_structured_mesh",
    "build_refinement_documents",
    "build_refinement_plans",
    "divergence_2d",
    "gradient_1d",
    "laplacian_1d",
    "laplacian_2d",
    "laplacian_3d",
    "estimate_convergence_order",
    "estimate_pde_execution",
    "upwind_derivative_1d",
]
