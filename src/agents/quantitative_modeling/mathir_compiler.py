"""Compile only the audited MathIR field from a declarative model specification."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from src.agents.quantitative_modeling.mathir import MathIRValidationError, validate_mathir_document
from src.agents.quantitative_modeling.model_format import normalize_quantitative_model_spec


class MathIRCompilationError(ValueError):
    """Raised when a model specification cannot be reduced to safe MathIR."""


def compile_mathir_from_model_spec(specification: Mapping[str, object]) -> dict[str, Any]:
    """Extract a fresh, validated MathIR document without parsing arbitrary formula text."""

    try:
        normalized = normalize_quantitative_model_spec(specification)
        if normalized["schema_version"] != "ieee_math_model_v1":
            raise MathIRCompilationError("PDE model specifications must be compiled through execution_ir")
        return validate_mathir_document(normalized["mathir"])
    except (ValueError, MathIRValidationError) as exc:
        raise MathIRCompilationError(f"model specification cannot compile to MathIR: {exc}") from exc


__all__ = ["MathIRCompilationError", "compile_mathir_from_model_spec"]
