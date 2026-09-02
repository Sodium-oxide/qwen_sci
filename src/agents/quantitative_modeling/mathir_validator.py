"""Static audit report for restricted numerical MathIR documents."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

from src.agents.quantitative_modeling.capability_classifier import classify_mathir_capability
from src.agents.quantitative_modeling.execution_ir import classify_execution_ir
from src.agents.quantitative_modeling.execution_ir_compiler import (
    ExecutionIRCompilationError,
    compile_execution_ir_from_model_spec,
)
from src.agents.quantitative_modeling.mathir_compiler import (
    MathIRCompilationError,
    compile_mathir_from_model_spec,
)
from src.agents.quantitative_modeling.model_format import model_spec_identity, normalize_quantitative_model_spec


MODEL_AUDIT_SCHEMA_VERSION = "quantitative_model_audit_v1"


def _digest(value: object) -> str:
    serialized = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def audit_quantitative_model(specification: Mapping[str, object]) -> dict[str, Any]:
    """Produce a reviewable audit report; a failed audit has no executable plan."""

    try:
        normalized = normalize_quantitative_model_spec(specification)
        if normalized["schema_version"] == "ieee_math_model_v1":
            mathir = compile_mathir_from_model_spec(normalized)
            execution_ir = {"kind": "MATHIR", "schema_version": "execution_ir_v1", "document": mathir}
        else:
            execution_ir = compile_execution_ir_from_model_spec(normalized)
    except (ValueError, MathIRCompilationError, ExecutionIRCompilationError) as exc:
        return {
            "schema_version": MODEL_AUDIT_SCHEMA_VERSION,
            "status": "MODEL_AUDIT_FAILED",
            "model_spec_identity": "",
            "mathir_identity": "",
            "capability": {"capability": "DEFERRED", "reason": str(exc), "solver_id": "", "system_type": ""},
            "checks": {"model_spec_valid": False, "mathir_valid": False, "trusted_expression_ast": False},
            "errors": [str(exc)],
        }
    capability = classify_execution_ir(execution_ir)
    status = "MODEL_AUDITED" if capability["capability"] in {"NATIVE", "COMPOSABLE"} else "DEFERRED"
    return {
        "schema_version": MODEL_AUDIT_SCHEMA_VERSION,
        "status": status,
        "model_spec_identity": model_spec_identity(normalized),
        "mathir_identity": _digest(execution_ir["document"]),
        "execution_ir_identity": _digest(execution_ir),
        "execution_ir": execution_ir,
        "capability": capability,
        "checks": {
            "model_spec_valid": True,
            "mathir_valid": execution_ir["kind"] == "MATHIR",
            "pdeir_valid": execution_ir["kind"] == "PDE",
            "trusted_expression_ast": True,
            "solver_available": capability["capability"] in {"NATIVE", "COMPOSABLE"},
            "execution_text_or_code_absent": True,
        },
        "errors": [],
    }


def require_executable_model_audit(audit_report: Mapping[str, object]) -> dict[str, Any]:
    """Reject any failed or deferred audit before creating a run plan."""

    report = dict(audit_report)
    if report.get("schema_version") != MODEL_AUDIT_SCHEMA_VERSION:
        raise ValueError("unsupported quantitative model audit schema")
    if report.get("status") != "MODEL_AUDITED":
        raise ValueError("a simulation run plan requires a MODEL_AUDITED model")
    capability = report.get("capability")
    if not isinstance(capability, Mapping) or capability.get("capability") not in {"NATIVE", "COMPOSABLE"}:
        raise ValueError("a simulation run plan requires an executable capability assessment")
    return report


__all__ = [
    "MODEL_AUDIT_SCHEMA_VERSION",
    "audit_quantitative_model",
    "require_executable_model_audit",
]
