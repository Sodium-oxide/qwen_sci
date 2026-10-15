"""Electronic structure protocol requirements and physical input checks."""

from collections.abc import Mapping
import re
from typing import Any

from ..contracts import ValidationReport
from .numerical_modeling import NumericalModelingProfile


class QuantumChemistryProfile(NumericalModelingProfile):
    profile_id = "quantum_chemistry"
    allowed_backends = ("pyscf", "python_project")
    required_model_fields = ("structure", "structure_unit", "charge", "spin", "environment", "assumptions")
    required_method_fields = ("task_type", "method", "basis", "method_sensitivity")
    mandatory_checks = ("finite_outputs", "electronic_state", "method_sensitivity")

    def iterative_method(self, method: Mapping[str, Any]) -> bool:
        return method.get("iterative_method") is True or bool(re.search(r"CCSD|CISD|CASSCF|EOM", str(method.get("method", "")).upper()))

    def effective_methods(self, plan: Mapping[str, Any]):
        return [(condition["condition_id"], {**plan["method_spec"], **condition["overrides"]})
            for condition in plan["comparisons"]]

    def check_conditions(self, plan: Mapping[str, Any]) -> dict[str, set[str]]:
        requirements = {}
        for condition_id, method in self.effective_methods(plan):
            checks = []
            if method.get("reference_scf_required", True):
                checks.append("scf_convergence")
            if method.get("task_type") in {"geometry_optimization", "transition_state"}:
                checks.append("geometry_convergence")
            if method.get("task_type") in {"frequency", "transition_state"}:
                checks.append("frequency_analysis")
            if self.iterative_method(method):
                checks.append("method_convergence")
            additional = method.get("required_checks", [])
            if isinstance(additional, list) and all(isinstance(item, str) and item for item in additional):
                checks.extend(additional)
            for check in checks:
                requirements.setdefault(check, set()).add(condition_id)
        return requirements

    def validate_plan(self, plan: Mapping[str, Any]) -> ValidationReport:
        errors = list(super().validate_plan(plan).errors)
        model = plan.get("model_spec", {})
        for condition in plan["comparisons"]:
            effective_model = {**model, **condition["overrides"]}
            for name in ("charge", "spin"):
                value = effective_model.get(name)
                if isinstance(value, bool) or not isinstance(value, int):
                    errors.append(f"quantum_chemistry:{condition['condition_id']}:{name}:integer_required")
            if isinstance(effective_model.get("spin"), int) and effective_model["spin"] < 0:
                errors.append("quantum_chemistry:spin:nonnegative_required")
            if effective_model.get("structure_unit") not in {"angstrom", "bohr"}:
                errors.append("quantum_chemistry:structure_unit:unsupported")
        for condition_id, method in self.effective_methods(plan):
            errors.extend(condition_id + ":" + error for error in self.validate_method(method, plan))
        return ValidationReport(tuple(errors))

    def validate_method(self, method: Mapping[str, Any], plan: Mapping[str, Any]) -> list[str]:
        errors = []
        reference_scf_required = method.get("reference_scf_required", True)
        if not isinstance(reference_scf_required, bool):
            errors.append("quantum_chemistry:reference_scf_required:boolean_required")
        if reference_scf_required is False and plan["backend_id"] == "pyscf" and method.get("implementation_mode", "fixed") == "fixed":
            errors.append("quantum_chemistry:fixed_driver_requires_reference_scf")
        if reference_scf_required is False and not method.get("reference_scf_justification"):
            errors.append("quantum_chemistry:non_scf_justification:missing")
        tolerance = method.get("scf_tolerance")
        if reference_scf_required and (isinstance(tolerance, bool) or not isinstance(tolerance, (int, float)) or tolerance <= 0):
            errors.append("quantum_chemistry:scf_tolerance:positive_required")
        cycles = method.get("max_scf_cycles")
        if reference_scf_required and (isinstance(cycles, bool) or not isinstance(cycles, int) or cycles <= 0):
            errors.append("quantum_chemistry:max_scf_cycles:positive_integer_required")
        additional = method.get("required_checks", [])
        if not isinstance(additional, list) or any(not isinstance(item, str) or not item.strip() for item in additional):
            errors.append("quantum_chemistry:required_checks:nonempty_string_array_required")
        if "iterative_method" in method and not isinstance(method["iterative_method"], bool):
            errors.append("quantum_chemistry:iterative_method:boolean_required")
        if plan["backend_id"] == "pyscf" and method.get("implementation_mode") == "generated":
            if not isinstance(method.get("iterative_method"), bool):
                errors.append("quantum_chemistry:iterative_method:explicit_classification_required")
            elif method["iterative_method"] is False and self.iterative_method(method):
                errors.append("quantum_chemistry:iterative_method:known_iterative_algorithm")
            elif method["iterative_method"] is False and not method.get("noniterative_justification"):
                errors.append("quantum_chemistry:noniterative_justification:missing")
        task = method.get("task_type")
        if not isinstance(task, str) or not task.strip():
            errors.append("quantum_chemistry:task_type:nonempty_required")
        if task in {"geometry_optimization", "transition_state"} and not method.get("geometry_convergence"):
            errors.append("quantum_chemistry:geometry_convergence:missing")
        if task in {"frequency", "transition_state"} and not method.get("frequency_analysis"):
            errors.append("quantum_chemistry:frequency_analysis:missing")
        return errors

    def required_checks(self, plan: Mapping[str, Any]) -> tuple[str, ...]:
        return tuple(dict.fromkeys([*self.mandatory_checks, *self.check_conditions(plan)]))

