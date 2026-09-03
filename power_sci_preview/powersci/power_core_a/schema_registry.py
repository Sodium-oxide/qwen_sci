"""JSON Schema registry and validator for every cross-role contract."""

from __future__ import annotations

from pathlib import Path
from typing import Any
import copy
import json

from .errors import ContractValidationError, UnknownSchemaError


SCHEMA_FILES: dict[str, str] = {
    "ResearchBrief": "research_brief.schema.json",
    "EquationIR": "equation_ir.schema.json",
    "CaseManifest": "case_manifest.schema.json",
    "LensSpec": "lens_spec.schema.json",
    "RunManifest": "run_manifest.schema.json",
    "ValidationReport": "validation_report.schema.json",
    "ArtifactDescriptor": "artifact_descriptor.schema.json",
    "ApprovalRecord": "approval_record.schema.json",
    "ExperimentProtocol": "experiment_protocol.schema.json",
    "ResultBundleManifest": "result_bundle_manifest.schema.json",
    "StateTransitionEvent": "state_transition_event.schema.json",
    "TaskEnvelope": "task_envelope.schema.json",
    "StructuredError": "structured_error.schema.json",
    "CandidateModelV1": "candidate_model_v1.schema.json",
    "EquationIRV2": "equation_ir_v2.schema.json",
    "CaseManifestV2": "case_manifest_v2.schema.json",
    "LensSpecV2": "lens_spec_v2.schema.json",
    "ValidationReportV2": "validation_report_v2.schema.json",
    "StructuredErrorV2": "structured_error_v2.schema.json",
    "TaskEnvelopeV2": "task_envelope_v2.schema.json",
}


class SchemaRegistry:
    def __init__(self, schema_dir: Path | str | None = None) -> None:
        self.schema_dir = Path(schema_dir) if schema_dir else Path(__file__).with_name("schemas")
        self._schemas: dict[str, dict[str, Any]] = {}

    def names(self) -> tuple[str, ...]:
        return tuple(SCHEMA_FILES)

    def schema(self, name: str) -> dict[str, Any]:
        if name not in SCHEMA_FILES:
            raise UnknownSchemaError(f"Unknown contract schema: {name}", context={"schema": name})
        if name not in self._schemas:
            path = self.schema_dir / SCHEMA_FILES[name]
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise UnknownSchemaError(
                    f"Cannot load contract schema {name}: {exc}", context={"path": str(path)}
                ) from exc
            self._schemas[name] = payload
        return copy.deepcopy(self._schemas[name])

    def validate(self, name: str, instance: Any) -> dict[str, Any]:
        try:
            from jsonschema import Draft202012Validator, FormatChecker
        except ImportError as exc:
            raise RuntimeError(
                "Role A contract validation requires jsonschema; install requirements-power-core-a.txt"
            ) from exc

        schema = self.schema(name)
        Draft202012Validator.check_schema(schema)
        errors = sorted(
            Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(instance),
            key=lambda item: tuple(str(part) for part in item.absolute_path),
        )
        if errors:
            error = errors[0]
            field_path = "/" + "/".join(str(part) for part in error.absolute_path)
            raise ContractValidationError(
                f"{name} failed validation at {field_path or '/'}: {error.message}",
                field_path=field_path or "/",
                context={"schema": name, "validator": error.validator},
            )
        from .semantic_validation import validate_semantics
        validate_semantics(name, instance)
        return copy.deepcopy(instance)

    def validate_schema_catalog(self) -> dict[str, Any]:
        try:
            from jsonschema import Draft202012Validator
        except ImportError as exc:
            raise RuntimeError(
                "Role A contract validation requires jsonschema; install requirements-power-core-a.txt"
            ) from exc
        checked: list[str] = []
        for name in self.names():
            Draft202012Validator.check_schema(self.schema(name))
            checked.append(name)
        return {"valid": True, "schemas": checked, "count": len(checked)}
