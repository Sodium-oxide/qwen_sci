"""Versioned contracts shared by planning, implementation, execution and analysis."""

from __future__ import annotations

import math
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator


class ComputationalContractError(ValueError):
    """A computational artifact fails its structural or semantic contract."""


TEXT = {"type": "string", "minLength": 1}
TEXTS = {"type": "array", "items": TEXT, "uniqueItems": True}
OBJECT = {"type": "object"}
OBJECTS = {"type": "array", "items": OBJECT}


def object_schema(properties: dict[str, Any], required: tuple[str, ...] | None = None) -> dict[str, Any]:
    return {
        "type": "object", "properties": properties,
        "required": list(required if required is not None else properties), "additionalProperties": False,
    }


SOURCE_BINDING = object_schema({
    "science_run_id": TEXT, "survey_run_id": TEXT, "project_id": TEXT,
    "project_context_fingerprint": TEXT, "selected_direction_id": TEXT,
    "idea_result_sha256": {"type": "string", "pattern": "^[a-f0-9]{64}$"},
    "handoff_fingerprint": TEXT,
})

BUDGET = object_schema({
    "max_wall_seconds": {"type": "number", "minimum": 0},
    "max_execution_seconds": {"type": "number", "minimum": 0},
    "max_total_executions": {"type": "integer", "minimum": 0},
    "max_code_repairs": {"type": "integer", "minimum": 0},
    "max_protocol_revisions": {"type": "integer", "minimum": 0},
    "cpu_cores": {"type": "integer", "minimum": 1},
    "memory_mb": {"type": "integer", "minimum": 64},
    "network_enabled": {"type": "boolean"},
})

PARAMETER = object_schema({
    "name": TEXT, "value": {}, "unit": TEXT,
    "provenance": object_schema({
        "kind": {"enum": ["literature", "user_provided", "design_assumption"]},
        "evidence_id": {"type": "string"}, "justification": TEXT,
    }),
})

ENDPOINT = object_schema({
    "metric_id": {"type": "string", "pattern": "^[A-Za-z][A-Za-z0-9_-]*$"},
    "description": TEXT, "unit": TEXT, "estimator": TEXT, "primary": {"type": "boolean"},
    "observation_binding": object_schema({"source_key": TEXT, "value_key": TEXT,
        "statistic": {"enum": ["value", "final_value", "mean", "min", "max", "integral"]},
        "state_id": TEXT}, ("source_key", "value_key", "statistic")),
}, ("metric_id", "description", "unit", "estimator", "primary"))

CHECK = object_schema({
    "check_id": TEXT, "description": TEXT, "settings": OBJECT,
})

CONTEXT_SCHEMA = object_schema({
    "schema_version": {"const": "computational_context_v1"},
    "source_binding": SOURCE_BINDING, "topic": TEXT, "research_brief": OBJECT,
    "target_gap_ids": TEXTS, "gaps": OBJECTS, "evidence": OBJECTS,
    "inputs": OBJECTS, "user_constraints": OBJECT, "resource_budget": BUDGET,
})

PLAN_SCHEMA = object_schema({
    "schema_version": {"const": "computational_experiment_plan_v1"},
    "experiment_id": {"type": "string", "pattern": "^CE[0-9]{3,}$"},
    "source_binding": SOURCE_BINDING, "protocol_version": {"type": "integer", "minimum": 1},
    "status": {"enum": ["READY", "NEEDS_INPUT"]}, "title": TEXT,
    "target_gap_ids": TEXTS, "research_question": TEXT, "hypothesis": TEXT,
    "competing_explanations": TEXTS, "scientific_role": TEXT,
    "discipline_template": TEXT, "method_family": TEXT, "backend_id": TEXT,
    "result_kind": {"enum": ["NUMERICAL_SIMULATION", "EMPIRICAL_REANALYSIS", "ALGORITHM_BENCHMARK"]},
    "model_spec": OBJECT, "method_spec": OBJECT, "inputs": OBJECTS,
    "parameters": {"type": "array", "items": PARAMETER},
    "comparisons": {"type": "array", "minItems": 1, "items": object_schema({
        "condition_id": TEXT, "role": {"enum": ["baseline", "primary", "sensitivity", "validation"]},
        "definition": TEXT, "overrides": OBJECT,
    })},
    "endpoints": {"type": "array", "minItems": 1, "items": ENDPOINT},
    "validation_plan": {"type": "array", "minItems": 1, "items": CHECK},
    "error_analysis_plan": {"type": "array", "minItems": 1, "items": CHECK},
    "decision_rule": OBJECT, "claim_scope": TEXT, "stopping_rules": TEXTS,
    "resource_budget": BUDGET, "unresolved_inputs": TEXTS,
})

IMPLEMENTATION_SCHEMA = object_schema({
    "schema_version": {"const": "computational_implementation_v1"},
    "experiment_id": TEXT, "source_binding": SOURCE_BINDING,
    "protocol_version": {"type": "integer", "minimum": 1},
    "implementation_version": {"type": "integer", "minimum": 1},
    "backend_id": TEXT, "environment_id": TEXT, "entrypoint": TEXT,
    "files": {"type": "array", "minItems": 1, "items": object_schema({
        "path": TEXT, "purpose": TEXT, "sha256": {"type": "string", "pattern": "^[a-f0-9]{64}$"},
    })},
    "dependencies": TEXTS, "input_manifest": OBJECT, "output_contract": OBJECT,
})

EXECUTION_SCHEMA = object_schema({
    "schema_version": {"const": "computational_execution_v1"},
    "execution_id": TEXT, "experiment_id": TEXT, "source_binding": SOURCE_BINDING,
    "protocol_version": {"type": "integer", "minimum": 1},
    "implementation_version": {"type": "integer", "minimum": 1},
    "purpose": {"enum": ["smoke", "formal", "replicate", "validation"]},
    "status": {"enum": ["COMPLETED", "FAILED", "CANCELLED", "TIMEOUT", "ENVIRONMENT_UNAVAILABLE"]},
    "command": {"type": "array", "items": TEXT, "minItems": 1}, "environment": OBJECT, "started_at": TEXT, "finished_at": TEXT,
    "elapsed_seconds": {"type": "number", "minimum": 0},
    "exit_code": {"type": ["integer", "null"]}, "resource_usage": OBJECT,
    "output_dir": TEXT, "stdout_path": TEXT, "stderr_path": TEXT,
    "authorization_id": TEXT, "error": {"type": "string"},
})

METRIC = object_schema({
    "metric_id": TEXT, "condition_id": TEXT, "value": {"type": "number"},
    "unit": TEXT, "source_ref": TEXT,
})

RESULT_SCHEMA = object_schema({
    "schema_version": {"const": "computational_result_v1"},
    "experiment_id": TEXT, "source_binding": SOURCE_BINDING,
    "protocol_version": {"type": "integer", "minimum": 1},
    "execution_status": {"enum": ["COMPLETED", "PARTIAL", "FAILED", "NOT_EXECUTED"]},
    "result_kind": {"enum": ["NUMERICAL_SIMULATION", "EMPIRICAL_REANALYSIS", "ALGORITHM_BENCHMARK"]},
    "validation_status": {"enum": ["QUALIFIED", "PARTIAL", "UNQUALIFIED", "NOT_EXECUTED"]},
    "metrics": {"type": "array", "items": METRIC}, "checks": OBJECTS,
    "uncertainty": OBJECTS, "error_analysis": OBJECTS,
    "hypothesis_relation": {"enum": ["SUPPORTED", "CONSTRAINED", "REFUTED", "INCONCLUSIVE"]},
    "claim_scope": TEXT, "interpretation": OBJECT,
    "unresolved_items": TEXTS, "lineage": OBJECTS,
})

HANDOFF_SCHEMA = object_schema({
    "schema_version": {"const": "computational_author_handoff_v1"},
    "source_binding": SOURCE_BINDING,
    "branch_status": {"enum": ["PLANNED", "COMPLETED", "PARTIAL", "NEEDS_INPUT", "FAILED", "CANCELLED", "ENVIRONMENT_UNAVAILABLE", "BUDGET_EXHAUSTED"]},
    "plans": {"type": "array", "items": PLAN_SCHEMA},
    "results": {"type": "array", "items": RESULT_SCHEMA},
    "unresolved_items": TEXTS, "artifact_refs": OBJECTS,
})

SCHEMAS = {
    "computational_context_v1": CONTEXT_SCHEMA,
    "computational_experiment_plan_v1": PLAN_SCHEMA,
    "computational_implementation_v1": IMPLEMENTATION_SCHEMA,
    "computational_execution_v1": EXECUTION_SCHEMA,
    "computational_result_v1": RESULT_SCHEMA,
    "computational_author_handoff_v1": HANDOFF_SCHEMA,
}


def _finite(value: Any) -> bool:
    if isinstance(value, float):
        return math.isfinite(value)
    if isinstance(value, Mapping):
        return all(_finite(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return all(_finite(item) for item in value)
    return True


def validate_contract(payload: Any, schema_version: str | None = None) -> list[str]:
    version = schema_version or (payload.get("schema_version") if isinstance(payload, Mapping) else "")
    schema = SCHEMAS.get(version)
    if schema is None:
        return ["unknown_computational_schema"]
    errors = [
        f"{'.'.join(map(str, error.absolute_path)) or '$'}: {error.message}"
        for error in Draft202012Validator(schema).iter_errors(payload)
    ]
    if not _finite(payload):
        errors.append("nonfinite_numeric_value")
    if errors:
        return errors
    if version == "computational_experiment_plan_v1":
        if payload["status"] == "READY" and payload["unresolved_inputs"]:
            errors.append("ready_plan_has_unresolved_inputs")
        if payload["status"] == "NEEDS_INPUT" and not payload["unresolved_inputs"]:
            errors.append("needs_input_plan_has_no_missing_inputs")
        for section, identifier in (("parameters", "name"), ("comparisons", "condition_id"), ("endpoints", "metric_id"), ("validation_plan", "check_id"), ("error_analysis_plan", "check_id")):
            identifiers = [row[identifier] for row in payload[section]]
            if len(set(identifiers)) != len(identifiers):
                errors.append(f"duplicate_{section}_identifier")
        if not any(endpoint["primary"] for endpoint in payload["endpoints"]):
            errors.append("missing_primary_endpoint")
        if not any(condition["role"] == "baseline" for condition in payload["comparisons"]):
            errors.append("missing_baseline_condition")
        for parameter in payload["parameters"]:
            if parameter["provenance"]["kind"] == "literature" and not parameter["provenance"]["evidence_id"]:
                errors.append(f"parameter_without_literature_evidence:{parameter['name']}")
    if version == "computational_result_v1":
        if payload["validation_status"] != "QUALIFIED" and payload["hypothesis_relation"] != "INCONCLUSIVE":
            errors.append("unqualified_result_must_be_inconclusive")
        if payload["validation_status"] == "QUALIFIED" and (not payload["metrics"] or payload["execution_status"] != "COMPLETED"):
            errors.append("qualified_result_requires_completed_execution_and_metrics")
        if payload["validation_status"] == "QUALIFIED" and (not payload["lineage"] or not payload["checks"] or
                any(item.get("passed") is not True for item in payload["checks"])):
            errors.append("qualified_result_requires_execution_lineage_and_passed_checks")
    if version == "computational_author_handoff_v1":
        for record in [*payload["plans"], *payload["results"]]:
            if record["source_binding"] != payload["source_binding"]:
                errors.append("handoff_source_binding_mismatch")
            errors.extend(validate_contract(record))
    return errors


def require_contract(payload: Any, schema_version: str | None = None) -> dict[str, Any]:
    errors = validate_contract(payload, schema_version)
    if errors:
        raise ComputationalContractError("; ".join(errors))
    return deepcopy(dict(payload))


def validate_budget(value: Any) -> list[str]:
    """Validate the resource object embedded in context and plans."""

    errors = [f"{'.'.join(map(str, error.absolute_path)) or '$'}: {error.message}"
              for error in Draft202012Validator(BUDGET).iter_errors(value)]
    if not _finite(value):
        errors.append("nonfinite_numeric_value")
    return errors


@dataclass(frozen=True)
class ValidationReport:
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    @property
    def passed(self) -> bool:
        return not self.errors


@dataclass(frozen=True)
class CapabilityReport:
    backend_id: str
    available: bool
    reason: str = ""
    details: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ExecutionRequest:
    experiment_id: str
    protocol_version: int
    implementation_version: int
    purpose: str
    command: tuple[str, ...]
    environment_id: str
    project_dir: Path
    input_dir: Path
    output_dir: Path
    source_binding: Mapping[str, str]
    max_wall_seconds: float
    cpu_cores: int
    memory_mb: int
    network_enabled: bool

