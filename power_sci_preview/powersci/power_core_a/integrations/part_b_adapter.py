"""Boundary adapter for the concrete ``part_b_xtl`` API.

Part B may keep its dataclasses and internal ``metadata`` dictionaries.  Only
the strict, JSON-serializable role-A contracts cross the team boundary.
"""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from typing import Any, Mapping
import json
import math

from ..canonical import canonical_json_bytes, sha256_bytes
from ..errors import ContractValidationError
from ..schema_registry import SchemaRegistry


_STAGE_TO_V = {"structure": "V1", "numerical": "V2", "physical": "V3"}
_RECOVERABLE_CODES = {
    "UNKNOWN_VARIABLE", "EMPTY_EQUATION_SET", "UNIT_MISMATCH", "DIMENSION_MISMATCH",
    "MISSING_DERIVATIVE_EQUATION", "STRUCTURE_INVALID", "ALGEBRAIC_CLOSURE_MISSING",
    "POWER_BALANCE_VIOLATION", "INITIALIZATION_FAILED", "NUMERICAL_DIVERGENCE",
    "NONFINITE_RESIDUAL", "PARAMETER_OUT_OF_BOUNDS", "EIGENVALUE_UNSTABLE",
    "ENERGY_DISSIPATION_VIOLATION",
}
_PUBLIC_CODES = _RECOVERABLE_CODES | {
    "CONTRACT_VALIDATION_FAILED", "ARTIFACT_INTEGRITY_FAILED", "INTERNAL_ERROR"
}


def _object_dict(value: Any) -> dict[str, Any]:
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, Mapping):
        return dict(value)
    if hasattr(value, "__dict__"):
        return dict(vars(value))
    raise TypeError(f"Expected a dataclass, mapping, or attribute object; got {type(value).__name__}")


def _required_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractValidationError(
            f"Part B boundary field {field} must be a non-empty string",
            field_path=f"/{field}", context={"schema": "CandidateModelV1"},
        )
    return value


def _bounded_text(value: Any, limit: int = 2000) -> str:
    text = str(value)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def b_candidate_to_contract(
    candidate: Any,
    *,
    variable_semantics: Mapping[str, Mapping[str, Any]],
    source: str,
    created_at: str,
    producer: str = "M10",
    fit_metadata: Mapping[str, Any] | None = None,
    registry: SchemaRegistry | None = None,
) -> dict[str, Any]:
    """Convert a concrete B ``CandidateModel`` into the public D→A→B contract.

    B's ``VariableRef`` does not carry coordinates or absolute/deviation
    semantics.  They are therefore required explicitly; the adapter never
    guesses them from a symbol name.
    """

    raw = _object_dict(candidate)
    variables: list[dict[str, Any]] = []
    for index, item in enumerate(raw.get("variables", [])):
        row = _object_dict(item)
        name = _required_text(row.get("name"), f"variables/{index}/name")
        semantic = variable_semantics.get(name)
        if semantic is None:
            raise ContractValidationError(
                f"Missing coordinate/reference semantics for B variable {name}",
                field_path=f"/variables/{index}", context={"variable": name},
            )
        converted = {
            "name": name,
            "alias": row.get("alias"),
            "unit": _required_text(row.get("unit"), f"variables/{index}/unit"),
            "coordinate": _required_text(semantic.get("coordinate"), f"variables/{index}/coordinate"),
            "reference_mode": semantic.get("reference_mode"),
        }
        if "nominal_value" in semantic:
            converted["nominal_value"] = semantic["nominal_value"]
        variables.append(converted)

    parameters = []
    for index, item in enumerate(raw.get("parameters", [])):
        row = _object_dict(item)
        parameters.append({
            "name": _required_text(row.get("name"), f"parameters/{index}/name"),
            "value": row.get("value"),
            "unit": _required_text(row.get("unit"), f"parameters/{index}/unit"),
        })

    equations = []
    for index, item in enumerate(raw.get("equations", [])):
        row = _object_dict(item)
        equations.append({
            "equation_id": f"eq-{index + 1:03d}",
            "kind": row.get("kind"),
            "lhs": _required_text(row.get("lhs"), f"equations/{index}/lhs"),
            "rhs": _required_text(row.get("rhs"), f"equations/{index}/rhs"),
            "unit": _required_text(row.get("unit"), f"equations/{index}/unit"),
            "expression": row.get("expression"),
        })

    fit = {"method": source, "random_seed": 0}
    fit.update(dict(fit_metadata or {}))
    contract = {
        "schema_version": "candidate_model_v1",
        "candidate_id": _required_text(raw.get("candidate_id"), "candidate_id"),
        "model_name": _required_text(raw.get("model_name"), "model_name"),
        "source": source,
        "variables": variables,
        "parameters": parameters,
        "equations": equations,
        "fit_metadata": fit,
        "created_at": created_at,
        "producer": producer,
    }
    return (registry or SchemaRegistry()).validate("CandidateModelV1", contract)


def candidate_contract_to_b_object(contract: Mapping[str, Any], part_b_api: Any) -> Any:
    """Build B's actual dataclass graph from a validated public contract."""

    payload = SchemaRegistry().validate("CandidateModelV1", dict(contract))
    variables = [
        part_b_api.VariableRef(name=row["name"], alias=row.get("alias"), unit=row["unit"])
        for row in payload["variables"]
    ]
    parameters = [
        part_b_api.ParameterRef(name=row["name"], value=row["value"], unit=row["unit"])
        for row in payload["parameters"]
    ]
    equations = [
        part_b_api.EquationNode(
            kind=row["kind"], lhs=row["lhs"], rhs=row["rhs"], unit=row["unit"],
            expression=row.get("expression"), metadata={},
        )
        for row in payload["equations"]
    ]
    return part_b_api.CandidateModel(
        candidate_id=payload["candidate_id"], model_name=payload["model_name"],
        equations=equations, variables=variables, parameters=parameters, metadata={},
    )


def validate_contract_with_part_b(
    contract: Mapping[str, Any], part_b_api: Any, *, context: Any = None,
    sample_points: Any = None,
) -> Any:
    candidate = candidate_contract_to_b_object(contract, part_b_api)
    kwargs: dict[str, Any] = {}
    if context is not None:
        kwargs["context"] = context
    if sample_points is not None:
        kwargs["sample_points"] = sample_points
    return part_b_api.validate_candidate_model(candidate, **kwargs)


def _diagnostics(details: Any, original_code: str | None = None) -> list[dict[str, Any]]:
    values: list[dict[str, Any]] = []
    if isinstance(details, Mapping):
        for name, value in sorted(details.items(), key=lambda pair: str(pair[0])):
            scalar = value if value is None or isinstance(value, (str, int, float, bool)) else json.dumps(value, ensure_ascii=False, sort_keys=True)
            if isinstance(scalar, float) and not math.isfinite(scalar):
                scalar = str(scalar)
            values.append({"name": str(name), "value": scalar})
    if original_code:
        values.append({"name": "part_b_original_code", "value": original_code})
    return values


def build_validation_report_v2(
    raw_report: Any,
    *,
    run_id: str,
    candidate_contract: Mapping[str, Any],
    case_manifest: Mapping[str, Any],
    lens_spec: Mapping[str, Any],
    created_at: str | None = None,
    validator_version: str = "part_b_xtl",
    registry: SchemaRegistry | None = None,
) -> dict[str, Any]:
    """Normalize B's terminal-stage report to A's full V1/V2/V3 report."""

    candidate = (registry or SchemaRegistry()).validate("CandidateModelV1", dict(candidate_contract))
    raw = _object_dict(raw_report)
    stage_name = str(raw.get("stage", "structure")).lower()
    completed = _STAGE_TO_V.get(stage_name, "V1")
    passed = bool(raw.get("passed", False))
    raw_errors = list(raw.get("errors", []))
    errors: list[dict[str, Any]] = []
    for item in raw_errors:
        row = _object_dict(item)
        original_code = str(row.get("code", "INTERNAL_ERROR"))
        code = original_code if original_code in _PUBLIC_CODES else "INTERNAL_ERROR"
        target = row.get("target")
        errors.append({
            "schema_version": "structured_error_v2", "code": code, "severity": "ERROR",
            "message": _bounded_text(row.get("message") or code), "target": None if target is None else str(target),
            "field_path": "", "recoverable": code in _RECOVERABLE_CODES, "origin_module": "M12",
            "diagnostics": _diagnostics(row.get("details", {}), original_code if code != original_code else None),
        })
    if not passed and not errors:
        errors.append({
            "schema_version": "structured_error_v2", "code": "INTERNAL_ERROR", "severity": "ERROR",
            "message": "Part B rejected the candidate without a structured error", "target": None,
            "field_path": "", "recoverable": False, "origin_module": "M12", "diagnostics": [],
        })

    checks = []
    metrics = []
    for name, value in sorted(dict(raw.get("metrics", {})).items()):
        if isinstance(value, (int, float)) and math.isfinite(float(value)):
            metrics.append({"name": str(name), "value": float(value), "unit": "dimensionless", "status": "PASS" if passed else "FAIL"})
    if passed:
        statuses = {"V1": "PASS", "V2": "PASS", "V3": "PASS"}
    elif completed == "V3":
        # B currently performs its physical pre-check before numerical samples.
        # Do not claim that V2 ran when that pre-check rejected the candidate.
        statuses = {"V1": "PASS", "V2": "NOT_RUN", "V3": "FAIL"}
    elif completed == "V2":
        statuses = {"V1": "PASS", "V2": "FAIL", "V3": "NOT_RUN"}
    else:
        statuses = {"V1": "FAIL", "V2": "NOT_RUN", "V3": "NOT_RUN"}
    for current in ("V1", "V2", "V3"):
        checks.append({
            "check_id": f"{current.lower()}-{candidate['candidate_id']}", "stage": current,
            "status": statuses[current], "metrics": metrics if current == completed else [],
        })

    internal_failure = any(row["code"] == "INTERNAL_ERROR" for row in errors)
    verdict = "PASS" if passed else ("BLOCKED" if internal_failure else "HARD_REJECT")
    report_hash = sha256_bytes(canonical_json_bytes({"run_id": run_id, "candidate_id": candidate["candidate_id"]})).split(":", 1)[1][:20]
    report = {
        "schema_version": "validation_report_v2", "report_id": f"validation-{report_hash}",
        "run_id": run_id, "candidate_id": candidate["candidate_id"], "model_name": candidate["model_name"],
        "case_id": str(case_manifest["case_id"]), "lens_id": str(lens_spec["lens_id"]),
        "candidate_model_hash": sha256_bytes(canonical_json_bytes(candidate)),
        "case_manifest_hash": sha256_bytes(canonical_json_bytes(dict(case_manifest))),
        "lens_spec_hash": sha256_bytes(canonical_json_bytes(dict(lens_spec))),
        "verdict": verdict, "completed_stage": completed, "checks": checks, "errors": errors,
        "warnings": [_bounded_text(item) for item in raw.get("warnings", [])],
        "created_at": created_at or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "validator_version": validator_version,
    }
    return (registry or SchemaRegistry()).validate("ValidationReportV2", report)
