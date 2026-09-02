"""Separate numerical validity from the model-internal hypothesis relationship."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any


RESULT_QUALIFICATION_SCHEMA_VERSION = "simulation_result_qualification_v1"
RELATION_VALUES = frozenset(
    {
        "SUPPORTED_WITHIN_MODEL",
        "CONSTRAINED",
        "REFUTED_WITHIN_MODEL",
        "INCONCLUSIVE",
    }
)


class ResultQualificationError(ValueError):
    """Raised when a caller tries to qualify an untrusted execution record."""


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _finite_values(value: object) -> bool:
    if isinstance(value, bool):
        return True
    if isinstance(value, (int, float)):
        return math.isfinite(float(value))
    if isinstance(value, Mapping):
        return all(_finite_values(item) for item in value.values())
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return all(_finite_values(item) for item in value)
    return isinstance(value, str) or value is None


def qualify_simulation_result(
    execution: Mapping[str, object],
    *,
    hypothesis_relation: str = "INCONCLUSIVE",
    required_validation_checks: Sequence[str] = (),
) -> dict[str, Any]:
    """Qualify numerical integrity while retaining every valid relationship state."""

    if hypothesis_relation not in RELATION_VALUES:
        raise ResultQualificationError("hypothesis_relation is unsupported")
    record = _mapping(execution)
    if record.get("status") != "COMPLETED":
        raise ResultQualificationError("only completed executions can be qualified")
    scenario_results = record.get("scenario_results")
    if not isinstance(scenario_results, Sequence) or isinstance(
        scenario_results, (str, bytes, bytearray)
    ) or not scenario_results:
        raise ResultQualificationError("completed execution has no scenario results")
    numerical_checks: dict[str, bool] = {}
    verification_statuses: list[str] = []
    for scenario in scenario_results:
        scenario_payload = _mapping(scenario)
        result = _mapping(scenario_payload.get("result"))
        for name, passed in _mapping(result.get("numerical_checks")).items():
            normalized_name = str(name or "").strip()
            if normalized_name:
                numerical_checks[normalized_name] = numerical_checks.get(normalized_name, True) and bool(passed)
        verification = _mapping(result.get("verification"))
        if verification:
            status = str(verification.get("status") or "").strip()
            if status:
                verification_statuses.append(status)
    requested_checks = [str(name or "").strip() for name in required_validation_checks]
    if any(not name for name in requested_checks):
        raise ResultQualificationError("required_validation_checks cannot contain empty names")
    required_checks = list(dict.fromkeys(requested_checks))
    checks: dict[str, bool] = {
        "completed": True,
        "execution_mode": record.get("execution_mode") == "NUMERICAL_SIMULATION",
        "result_kind": record.get("result_kind") == "SIMULATED",
        "not_empirical": record.get("empirical_claim_status") == "NOT_EMPIRICAL",
        "finite_outputs": _finite_values(scenario_results),
    }
    if record.get("execution_ir_kind") == "PDE":
        checks["pde_numeric_verification"] = bool(verification_statuses) and all(
            status == "NUMERICALLY_VERIFIED" for status in verification_statuses
        )
    checks.update({f"validation:{name}": numerical_checks.get(name, False) for name in required_checks})
    quality = "QUALIFIED" if all(checks.values()) else "UNQUALIFIED"
    numerical_quality = "NUMERICALLY_VERIFIED" if verification_statuses and all(
        status == "NUMERICALLY_VERIFIED" for status in verification_statuses
    ) else "NUMERICALLY_UNVERIFIED" if verification_statuses else "NOT_REPORTED"
    return {
        "schema_version": RESULT_QUALIFICATION_SCHEMA_VERSION,
        "execution_id": str(record.get("execution_id") or "").strip(),
        "plan_identity": str(record.get("plan_identity") or "").strip(),
        "model_identity": _mapping(record.get("model_identity")),
        "result_quality": quality,
        "hypothesis_relation": hypothesis_relation if quality == "QUALIFIED" else "INCONCLUSIVE",
        "execution_mode": "NUMERICAL_SIMULATION",
        "result_kind": "SIMULATED",
        "empirical_claim_status": "NOT_EMPIRICAL",
        "checks": checks,
        "numerical_checks": numerical_checks,
        "numerical_quality": {
            "status": numerical_quality,
            "scenario_statuses": verification_statuses,
        },
        "required_validation_checks": required_checks,
        "reason": "" if quality == "QUALIFIED" else "One or more numerical integrity checks failed.",
    }


__all__ = [
    "RELATION_VALUES",
    "RESULT_QUALIFICATION_SCHEMA_VERSION",
    "ResultQualificationError",
    "qualify_simulation_result",
]
