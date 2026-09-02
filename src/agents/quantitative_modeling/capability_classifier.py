"""Classify a MathIR model without promising unsupported numerical execution."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from src.agents.quantitative_modeling.mathir import MathIRValidationError, validate_mathir_document
from src.agents.quantitative_modeling.solver_registry import SOLVER_BY_SYSTEM_TYPE, solver_is_available


CAPABILITY_VALUES = frozenset({"NATIVE", "COMPOSABLE", "DEFERRED"})


def classify_mathir_capability(value: Mapping[str, object]) -> dict[str, Any]:
    """Return an explicit execution classification for an audited model."""

    try:
        normalized = validate_mathir_document(value)
    except MathIRValidationError as exc:
        return {
            "capability": "DEFERRED",
            "reason": f"MathIR audit failed: {exc}",
            "solver_id": "",
            "system_type": str(value.get("system_type") or "").strip(),
        }
    system_type = str(normalized["system_type"])
    solver_id = SOLVER_BY_SYSTEM_TYPE.get(system_type, "")
    if not solver_id or not solver_is_available(system_type):
        return {
            "capability": "DEFERRED",
            "reason": f"No approved solver is available for {system_type}",
            "solver_id": solver_id,
            "system_type": system_type,
        }
    return {
        "capability": "COMPOSABLE",
        "reason": "The model is fully represented by audited MathIR and an approved solver adapter.",
        "solver_id": solver_id,
        "system_type": system_type,
    }


__all__ = ["CAPABILITY_VALUES", "classify_mathir_capability"]
