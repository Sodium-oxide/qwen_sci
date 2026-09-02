"""Immutable, explicitly authorized simulation run plans."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping, Sequence
from typing import Any

from src.agents.quantitative_modeling.capability_classifier import classify_mathir_capability
from src.agents.quantitative_modeling.execution_ir import (
    ExecutionIRValidationError,
    classify_execution_ir,
    validate_execution_ir,
)
from src.agents.quantitative_modeling.mathir import MathIRValidationError, validate_mathir_document
from src.agents.quantitative_modeling.parameter_contracts import (
    ParameterContractError,
    approved_mathir_parameters,
    normalize_approved_parameter_set,
)
from src.agents.quantitative_modeling.pde_capability_registry import pde_capability


SIMULATION_RUN_PLAN_SCHEMA_VERSION = "simulation_run_plan_v1"
DEFAULT_RESOURCE_LIMITS = {
    "max_output_points": 2_000,
    "max_samples": 100_000,
    "max_grid_points": 512,
    "max_nx": 4_096,
    "max_ny": 1_024,
    "max_nz": 128,
    "max_cells": 100_000,
    "max_time_steps": 20_000,
    "max_pde_snapshots": 200,
    "max_matrix_size": 20_000,
    "max_matrix_nonzeros": 200_000,
    "max_fields": 8,
    "max_memory_mb": 512,
    "max_wall_seconds": 120,
    "rtol": 1e-6,
    "atol": 1e-9,
}
_DEFAULT_QUALIFICATION_REQUIREMENTS = {
    "ODE_IVP": ["solver_converged"],
    "LINEAR_OPTIMIZATION": ["solver_feasible"],
    "MONTE_CARLO": ["sample_count_bound"],
    "DIFFUSION_REACTION_1D": ["explicit_stability"],
    "ADVECTION_DIFFUSION_REACTION_1D": ["explicit_stability", "finite_field"],
    "BURGERS_1D": ["explicit_stability", "finite_field"],
    "DIFFUSION_REACTION_2D": ["explicit_stability", "finite_field"],
    "DIFFUSION_REACTION_3D": ["explicit_stability", "finite_field"],
    "HEAT_DIFFUSION_1D": ["explicit_stability", "finite_field"],
    "HEAT_DIFFUSION_2D": ["explicit_stability", "finite_field"],
    "HEAT_DIFFUSION_3D": ["explicit_stability", "finite_field"],
    "LINEAR_ADVECTION_1D": ["explicit_stability", "finite_field"],
    "ELLIPTIC_DIFFUSION_1D": ["linear_residual", "finite_field"],
    "ELLIPTIC_DIFFUSION_2D": ["linear_residual", "finite_field"],
    "POISSON_1D": ["linear_residual", "finite_field"],
    "POISSON_2D": ["linear_residual", "finite_field"],
    "HELMHOLTZ_1D": ["linear_residual", "finite_field"],
    "HELMHOLTZ_2D": ["linear_residual", "finite_field"],
    "WAVE_1D": ["wave_cfl", "finite_field"],
    "WAVE_2D": ["wave_cfl", "finite_field"],
    "SPHERICAL_RADIAL_THERMAL": ["explicit_stability", "spherical_origin_regularity", "finite_field"],
}


class SimulationRunPlanError(ValueError):
    """Raised when a plan is not an immutable, executable simulation request."""


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _text(value: object) -> str:
    return str(value).strip() if value is not None else ""


def _number(value: object, *, field: str) -> float:
    if isinstance(value, bool):
        raise SimulationRunPlanError(f"{field} must be numeric")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise SimulationRunPlanError(f"{field} must be numeric") from exc
    if not math.isfinite(result):
        raise SimulationRunPlanError(f"{field} must be finite")
    return result


def _positive_int(value: object, *, field: str) -> int:
    if isinstance(value, bool):
        raise SimulationRunPlanError(f"{field} must be an integer")
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise SimulationRunPlanError(f"{field} must be an integer") from exc
    if result < 1:
        raise SimulationRunPlanError(f"{field} must be positive")
    return result


def _canonical_json(value: Mapping[str, object]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _plan_identity(value: Mapping[str, object]) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _validate_identity(value: Mapping[str, object]) -> dict[str, str]:
    normalized = {str(key): _text(item) for key, item in value.items() if _text(item)}
    for field in ("science_run_id", "quantitative_idea_id", "version"):
        if not normalized.get(field):
            raise SimulationRunPlanError(f"model_identity.{field} is required")
    if normalized["quantitative_idea_id"] not in {"Q1", "Q2"}:
        raise SimulationRunPlanError("model_identity.quantitative_idea_id must be Q1 or Q2")
    try:
        version = int(normalized["version"])
    except ValueError as exc:
        raise SimulationRunPlanError("model_identity.version must be an integer") from exc
    if version < 0 or version > 2:
        raise SimulationRunPlanError("model_identity.version must be between 0 and 2")
    normalized["version"] = str(version)
    return normalized


def _normalize_limits(value: Mapping[str, object] | None) -> dict[str, Any]:
    limits = {**DEFAULT_RESOURCE_LIMITS, **_mapping(value)}
    normalized = {
        "max_output_points": _positive_int(limits.get("max_output_points"), field="max_output_points"),
        "max_samples": _positive_int(limits.get("max_samples"), field="max_samples"),
        "max_grid_points": _positive_int(
            limits.get("max_grid_points"), field="max_grid_points"
        ),
        "max_nx": _positive_int(limits.get("max_nx"), field="max_nx"),
        "max_ny": _positive_int(limits.get("max_ny"), field="max_ny"),
        "max_nz": _positive_int(limits.get("max_nz"), field="max_nz"),
        "max_cells": _positive_int(limits.get("max_cells"), field="max_cells"),
        "max_time_steps": _positive_int(
            limits.get("max_time_steps"), field="max_time_steps"
        ),
        "max_pde_snapshots": _positive_int(
            limits.get("max_pde_snapshots"), field="max_pde_snapshots"
        ),
        "max_matrix_size": _positive_int(limits.get("max_matrix_size"), field="max_matrix_size"),
        "max_matrix_nonzeros": _positive_int(
            limits.get("max_matrix_nonzeros"), field="max_matrix_nonzeros"
        ),
        "max_fields": _positive_int(limits.get("max_fields"), field="max_fields"),
        "max_memory_mb": _positive_int(limits.get("max_memory_mb"), field="max_memory_mb"),
        "max_wall_seconds": _positive_int(limits.get("max_wall_seconds"), field="max_wall_seconds"),
        "rtol": _number(limits.get("rtol"), field="rtol"),
        "atol": _number(limits.get("atol"), field="atol"),
    }
    if normalized["rtol"] <= 0 or normalized["atol"] <= 0:
        raise SimulationRunPlanError("rtol and atol must be positive")
    return normalized


def _normalize_scenarios(
    value: object,
    *,
    mathir: Mapping[str, object],
    allowed_override_names: set[str] | None = None,
) -> list[dict[str, Any]]:
    raw_scenarios = value if value is not None else [{"scenario_id": "baseline", "parameter_overrides": {}}]
    if not isinstance(raw_scenarios, Sequence) or isinstance(raw_scenarios, (str, bytes, bytearray)):
        raise SimulationRunPlanError("scenarios must be a list")
    if not raw_scenarios:
        raise SimulationRunPlanError("scenarios must contain at least one scenario")
    parameter_names = set(_mapping(mathir.get("parameters")))
    scenarios: list[dict[str, Any]] = []
    scenario_ids: set[str] = set()
    for index, raw_scenario in enumerate(raw_scenarios):
        scenario = _mapping(raw_scenario)
        identifier = _text(scenario.get("scenario_id"))
        if not identifier:
            raise SimulationRunPlanError(f"scenarios[{index}].scenario_id is required")
        if identifier in scenario_ids:
            raise SimulationRunPlanError("scenario_id values must be unique")
        scenario_ids.add(identifier)
        overrides = _mapping(scenario.get("parameter_overrides"))
        capability = pde_capability(str(mathir["system_type"]))
        supports_overrides = str(mathir["system_type"]) == "ODE_IVP" or capability is not None
        if not supports_overrides and overrides:
            raise SimulationRunPlanError(
                "parameter overrides are not supported for this execution system"
            )
        unknown = set(overrides) - parameter_names
        if unknown:
            raise SimulationRunPlanError("scenario overrides reference undeclared parameters")
        if allowed_override_names is not None:
            disallowed = set(overrides) - allowed_override_names
            if disallowed:
                raise SimulationRunPlanError(
                    "evidence-bound scenario overrides may target only approved SCENARIO_INPUT parameters"
                )
        scenarios.append(
            {
                "scenario_id": identifier,
                "parameter_overrides": {
                    name: _number(raw_value, field=f"scenarios[{index}].parameter_overrides.{name}")
                    for name, raw_value in overrides.items()
                },
            }
        )
    return scenarios


def _normalize_parameter_set_manifest(value: object) -> dict[str, str]:
    manifest = _mapping(value)
    path = _text(manifest.get("path"))
    sha256 = _text(manifest.get("sha256"))
    if not path or not re.fullmatch(r"[0-9a-f]{64}", sha256):
        raise SimulationRunPlanError("parameter-set manifest requires a path and SHA-256 digest")
    return {"path": path, "sha256": sha256}


def _normalize_parameter_provenance(
    value: object,
    *,
    parameter_set: Mapping[str, object] | None,
    parameter_set_manifest: Mapping[str, object] | None,
    mathir: Mapping[str, object],
) -> dict[str, Any]:
    if parameter_set is not None and value is not None:
        raise SimulationRunPlanError("supply either parameter_set or parameter_provenance, not both")
    if parameter_set is not None:
        try:
            approved = normalize_approved_parameter_set(parameter_set)
        except ParameterContractError as error:
            raise SimulationRunPlanError(f"approved parameter set is invalid: {error}") from error
        expected_parameters = approved_mathir_parameters(approved)
        actual_parameters = _mapping(mathir.get("parameters"))
        if actual_parameters != expected_parameters:
            raise SimulationRunPlanError("MathIR parameters must exactly match the approved parameter set")
        manifest = _normalize_parameter_set_manifest(parameter_set_manifest)
        return {
            "mode": "APPROVED_PARAMETER_SET",
            "parameter_set_identity": approved["parameter_set_identity"],
            "parameter_set_manifest": manifest,
            "allowed_scenario_parameter_ids": sorted(
                entry["mathir_symbol"]
                for entry in approved["entries"]
                if entry["role"] == "SCENARIO_INPUT"
            ),
        }
    raw = _mapping(value)
    if not raw:
        return {"mode": "LEGACY_INLINE_ASSUMPTIONS"}
    if _text(raw.get("mode")) == "LEGACY_INLINE_ASSUMPTIONS":
        if set(raw) != {"mode"}:
            raise SimulationRunPlanError("legacy parameter_provenance cannot carry evidence-bound fields")
        return {"mode": "LEGACY_INLINE_ASSUMPTIONS"}
    if _text(raw.get("mode")) != "APPROVED_PARAMETER_SET":
        raise SimulationRunPlanError("parameter_provenance mode is unsupported")
    identity = _text(raw.get("parameter_set_identity"))
    if not re.fullmatch(r"[0-9a-f]{64}", identity):
        raise SimulationRunPlanError("parameter_provenance requires a parameter_set_identity")
    allowed = raw.get("allowed_scenario_parameter_ids")
    if not isinstance(allowed, Sequence) or isinstance(allowed, (str, bytes, bytearray)):
        raise SimulationRunPlanError("parameter_provenance allowed_scenario_parameter_ids must be a list")
    allowed_names = sorted({_text(name) for name in allowed if _text(name)})
    if len(allowed_names) != len(allowed):
        raise SimulationRunPlanError("parameter_provenance scenario parameter IDs must be unique non-empty values")
    if set(allowed_names) - set(_mapping(mathir.get("parameters"))):
        raise SimulationRunPlanError("parameter_provenance refers to undeclared MathIR parameters")
    return {
        "mode": "APPROVED_PARAMETER_SET",
        "parameter_set_identity": identity,
        "parameter_set_manifest": _normalize_parameter_set_manifest(raw.get("parameter_set_manifest")),
        "allowed_scenario_parameter_ids": allowed_names,
    }


def _normalize_qualification_requirements(value: object, *, system_type: str) -> list[str]:
    raw_values = value if value is not None else _DEFAULT_QUALIFICATION_REQUIREMENTS.get(system_type, [])
    if not isinstance(raw_values, Sequence) or isinstance(raw_values, (str, bytes, bytearray)):
        raise SimulationRunPlanError("qualification_requirements must be a list")
    requirements = [_text(item) for item in raw_values]
    if any(not item for item in requirements):
        raise SimulationRunPlanError("qualification_requirements cannot contain empty values")
    if not requirements:
        raise SimulationRunPlanError("qualification_requirements must not be empty")
    return list(dict.fromkeys(requirements))


def build_simulation_run_plan(
    *,
    model_identity: Mapping[str, object],
    mathir: Mapping[str, object] | None = None,
    execution_ir: Mapping[str, object] | None = None,
    scenarios: object = None,
    resource_limits: Mapping[str, object] | None = None,
    qualification_requirements: object = None,
    parameter_set: Mapping[str, object] | None = None,
    parameter_set_manifest: Mapping[str, object] | None = None,
    parameter_provenance: object = None,
) -> dict[str, Any]:
    """Build a deterministic plan; this function never starts a numerical solver."""

    if mathir is not None and execution_ir is not None:
        raise SimulationRunPlanError("supply either mathir or execution_ir, not both")
    if mathir is None and execution_ir is None:
        raise SimulationRunPlanError("a simulation plan requires mathir or execution_ir")
    normalized_execution_ir: dict[str, Any] | None = None
    if execution_ir is not None:
        try:
            normalized_execution_ir = validate_execution_ir(execution_ir)
        except ExecutionIRValidationError as exc:
            raise SimulationRunPlanError(f"execution IR is invalid: {exc}") from exc
        normalized_mathir = normalized_execution_ir["document"]
        capability = classify_execution_ir(normalized_execution_ir)
    else:
        try:
            normalized_mathir = validate_mathir_document(mathir)
        except MathIRValidationError as exc:
            raise SimulationRunPlanError(f"MathIR is invalid: {exc}") from exc
        capability = classify_mathir_capability(normalized_mathir)
    if capability["capability"] not in {"NATIVE", "COMPOSABLE"}:
        raise SimulationRunPlanError(f"MathIR is not executable: {capability['reason']}")
    provenance = _normalize_parameter_provenance(
        parameter_provenance,
        parameter_set=parameter_set,
        parameter_set_manifest=parameter_set_manifest,
        mathir=normalized_mathir,
    )
    model_identity_normalized = _validate_identity(model_identity)
    if provenance["mode"] == "APPROVED_PARAMETER_SET":
        if model_identity_normalized.get("parameter_set_identity") != provenance["parameter_set_identity"]:
            raise SimulationRunPlanError("model_identity must bind the approved parameter_set_identity")
        allowed_override_names: set[str] | None = set(provenance["allowed_scenario_parameter_ids"])
    else:
        allowed_override_names = None
    plan_without_identity: dict[str, Any] = {
        "schema_version": SIMULATION_RUN_PLAN_SCHEMA_VERSION,
        "execution_mode": "NUMERICAL_SIMULATION",
        "result_kind": "SIMULATED",
        "empirical_claim_status": "NOT_EMPIRICAL",
        "model_identity": model_identity_normalized,
        "capability": capability,
        "parameter_provenance": provenance,
        "scenarios": _normalize_scenarios(
            scenarios,
            mathir=normalized_mathir,
            allowed_override_names=allowed_override_names,
        ),
        "resource_limits": _normalize_limits(resource_limits),
        "qualification_requirements": _normalize_qualification_requirements(
            qualification_requirements,
            system_type=str(normalized_mathir["system_type"]),
        ),
    }
    if normalized_execution_ir is None:
        plan_without_identity["mathir"] = normalized_mathir
    else:
        plan_without_identity["execution_ir"] = normalized_execution_ir
    return {**plan_without_identity, "plan_identity": _plan_identity(plan_without_identity)}


def validate_simulation_run_plan(value: object) -> dict[str, Any]:
    """Rebuild a supplied plan and prove that its identity still matches its content."""

    payload = _mapping(value)
    if _text(payload.get("schema_version")) != SIMULATION_RUN_PLAN_SCHEMA_VERSION:
        raise SimulationRunPlanError("unsupported simulation run plan schema")
    if _text(payload.get("execution_mode")) != "NUMERICAL_SIMULATION":
        raise SimulationRunPlanError("simulation run plan execution mode is invalid")
    if _text(payload.get("result_kind")) != "SIMULATED":
        raise SimulationRunPlanError("simulation run plan result kind is invalid")
    if _text(payload.get("empirical_claim_status")) != "NOT_EMPIRICAL":
        raise SimulationRunPlanError("simulation run plan empirical claim status is invalid")
    raw_execution_ir = payload.get("execution_ir")
    if raw_execution_ir not in (None, {}):
        rebuilt = build_simulation_run_plan(
            model_identity=_mapping(payload.get("model_identity")),
            execution_ir=_mapping(raw_execution_ir),
            scenarios=payload.get("scenarios"),
            resource_limits=_mapping(payload.get("resource_limits")),
            qualification_requirements=payload.get("qualification_requirements"),
            parameter_provenance=payload.get("parameter_provenance"),
        )
    else:
        rebuilt = build_simulation_run_plan(
            model_identity=_mapping(payload.get("model_identity")),
            mathir=_mapping(payload.get("mathir")),
            scenarios=payload.get("scenarios"),
            resource_limits=_mapping(payload.get("resource_limits")),
            qualification_requirements=payload.get("qualification_requirements"),
            parameter_provenance=payload.get("parameter_provenance"),
        )
    if _text(payload.get("plan_identity")) != rebuilt["plan_identity"]:
        raise SimulationRunPlanError("simulation run plan identity does not match its content")
    return rebuilt


__all__ = [
    "DEFAULT_RESOURCE_LIMITS",
    "SIMULATION_RUN_PLAN_SCHEMA_VERSION",
    "SimulationRunPlanError",
    "build_simulation_run_plan",
    "validate_simulation_run_plan",
]
