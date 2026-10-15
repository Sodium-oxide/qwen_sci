"""Numerical model obligations independent of the research discipline."""

from collections.abc import Mapping
from typing import Any

from ..contracts import ValidationReport


class NumericalModelingProfile:
    profile_id = "numerical_modeling"
    allowed_backends = ("mathir", "python_project")
    required_model_fields = ("variables", "equations", "initial_conditions", "boundary_conditions", "assumptions")
    required_method_fields = ("solver", "tolerances", "discretization", "convergence_plan")
    mandatory_checks = ("finite_outputs", "reference_or_invariant", "convergence")

    def validate_plan(self, plan: Mapping[str, Any]) -> ValidationReport:
        errors = []
        for section, fields in (("model_spec", self.required_model_fields), ("method_spec", self.required_method_fields)):
            for name in fields:
                if plan.get(section, {}).get(name) in (None, "", [], {}):
                    errors.append(f"{self.profile_id}:{section}.{name}:missing")
        if self.profile_id == "numerical_modeling" and plan["backend_id"] == "python_project" and any(
            "reference_expression" in row["settings"] for row in plan["validation_plan"]
        ) and any(endpoint.get("observation_binding", {}).get("source_key") != "traces" for endpoint in plan["endpoints"]):
            errors.append("reference_validated_endpoints_must_bind_to_reference_traces")
        return ValidationReport(tuple(errors))

    def required_checks(self, plan: Mapping[str, Any]) -> tuple[str, ...]:
        return self.mandatory_checks

