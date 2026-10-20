"""Traceable result figures shared by quantitative and computational experiments."""

from .service import ensure_result_figures
from .convergence import register_saved_convergence_study

__all__ = ["ensure_result_figures", "register_saved_convergence_study"]
