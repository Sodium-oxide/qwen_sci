"""Compile a quantitative model specification to its trusted execution IR."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from src.agents.quantitative_modeling.execution_ir import ExecutionIRValidationError, validate_execution_ir
from src.agents.quantitative_modeling.mathir_compiler import MathIRCompilationError, compile_mathir_from_model_spec
from src.agents.quantitative_modeling.model_format import normalize_quantitative_model_spec


class ExecutionIRCompilationError(ValueError):
    """Raised when a model specification cannot compile to a trusted backend."""


def compile_execution_ir_from_model_spec(specification: Mapping[str, object]) -> dict[str, Any]:
    """Compile either legacy MathIR v1 or PDEIR v2 without parsing source text."""

    try:
        normalized = normalize_quantitative_model_spec(specification)
        if normalized["schema_version"] == "ieee_math_model_v1":
            return {"kind": "MATHIR", "schema_version": "execution_ir_v1", "document": compile_mathir_from_model_spec(normalized)}
        return validate_execution_ir(normalized["execution_ir"])
    except (ValueError, MathIRCompilationError, ExecutionIRValidationError) as exc:
        raise ExecutionIRCompilationError(f"model specification cannot compile to execution IR: {exc}") from exc


__all__ = ["ExecutionIRCompilationError", "compile_execution_ir_from_model_spec"]
