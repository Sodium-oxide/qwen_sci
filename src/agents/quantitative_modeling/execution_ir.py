"""Dispatch and validate legacy MathIR and versioned PDEIR documents."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from src.agents.quantitative_modeling.mathir import MathIRValidationError, validate_mathir_document
from src.agents.quantitative_modeling.pde_capability_registry import pde_capability, pde_is_executable
from src.agents.quantitative_modeling.pdeir import PDEIRValidationError, validate_pdeir_document
from src.agents.quantitative_modeling.pde_solver import PDESolverError, execute_pdeir, pde_solver_is_available
from src.agents.quantitative_modeling.solver_registry import execute_mathir


class ExecutionIRValidationError(ValueError):
    """Raised when an execution IR envelope is malformed or unsupported."""


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def validate_execution_ir(value: object) -> dict[str, Any]:
    """Validate an explicit execution envelope and return normalized content."""

    payload = _mapping(value)
    if str(payload.get("schema_version") or "").strip() != "execution_ir_v1":
        raise ExecutionIRValidationError("execution_ir.schema_version must be execution_ir_v1")
    kind = str(payload.get("kind") or "").strip()
    document = _mapping(payload.get("document"))
    if kind == "MATHIR":
        try:
            normalized = validate_mathir_document(document)
        except MathIRValidationError as exc:
            raise ExecutionIRValidationError(str(exc)) from exc
        return {"kind": kind, "schema_version": "execution_ir_v1", "document": normalized}
    if kind == "PDE":
        try:
            normalized = validate_pdeir_document(document)
        except PDEIRValidationError as exc:
            raise ExecutionIRValidationError(str(exc)) from exc
        return {"kind": kind, "schema_version": "execution_ir_v1", "document": normalized}
    raise ExecutionIRValidationError("execution_ir.kind must be MATHIR or PDE")


def classify_execution_ir(value: Mapping[str, object]) -> dict[str, Any]:
    """Return an explicit capability assessment without running a solver."""

    try:
        normalized = validate_execution_ir(value)
    except ExecutionIRValidationError as exc:
        return {"capability": "DEFERRED", "reason": str(exc), "solver_id": "", "kind": ""}
    document = normalized["document"]
    if normalized["kind"] == "MATHIR":
        from src.agents.quantitative_modeling.capability_classifier import classify_mathir_capability

        assessment = classify_mathir_capability(document)
        return {**assessment, "kind": "MATHIR"}
    system_type = str(document["system_type"])
    capability = pde_capability(system_type)
    if capability is None or not pde_is_executable(system_type) or not pde_solver_is_available(system_type):
        return {
            "capability": "DEFERRED",
            "reason": f"No approved PDE solver is available for {system_type}",
            "solver_id": str((capability or {}).get("solver_id") or ""),
            "system_type": system_type,
            "kind": "PDE",
        }
    return {
        "capability": "COMPOSABLE",
        "reason": "The PDEIR is valid and has an approved fixed solver adapter.",
        "solver_id": capability["solver_id"],
        "solver_implementation_version": capability.get("implementation_version", ""),
        "system_type": system_type,
        "kind": "PDE",
    }


def execute_execution_ir(value: Mapping[str, object], *, resource_limits: Mapping[str, object] | None = None) -> dict[str, Any]:
    """Execute only a validated, registered execution IR document."""

    normalized = validate_execution_ir(value)
    if normalized["kind"] == "MATHIR":
        return execute_mathir(normalized["document"], resource_limits=_mapping(resource_limits))
    try:
        return execute_pdeir(normalized["document"], resource_limits=resource_limits)
    except PDESolverError:
        raise


__all__ = [
    "ExecutionIRValidationError",
    "classify_execution_ir",
    "execute_execution_ir",
    "validate_execution_ir",
]
