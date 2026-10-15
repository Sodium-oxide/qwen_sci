"""Registered method requirements, separate from discipline template selection."""

from collections.abc import Mapping
from typing import Any

from .contracts import ComputationalContractError, ValidationReport, validate_contract
from .domain_profiles.algorithm_evaluation import AlgorithmEvaluationProfile
from .domain_profiles.data_analysis import DataAnalysisProfile
from .domain_profiles.molecular_dynamics import MolecularDynamicsProfile
from .domain_profiles.numerical_modeling import NumericalModelingProfile
from .domain_profiles.quantum_chemistry import QuantumChemistryProfile


PROFILES = {profile.profile_id: profile for profile in (
    NumericalModelingProfile(), QuantumChemistryProfile(), DataAnalysisProfile(),
    MolecularDynamicsProfile(), AlgorithmEvaluationProfile(),
)}


def get_domain_profile(profile_id: str):
    if profile_id not in PROFILES:
        raise ComputationalContractError(f"unknown_method_family:{profile_id}")
    return PROFILES[profile_id]


def validate_scientific_plan(plan: Mapping[str, Any]) -> ValidationReport:
    errors = validate_contract(plan, "computational_experiment_plan_v1")
    if errors:
        return ValidationReport(tuple(errors))
    try:
        profile = get_domain_profile(plan["method_family"])
    except ComputationalContractError as error:
        return ValidationReport((str(error),))
    if plan["backend_id"] not in profile.allowed_backends:
        errors.append("backend_method_incompatible")
    if plan["status"] == "READY":
        errors.extend(profile.validate_plan(plan).errors)
        declared_checks = {item["check_id"] for item in [*plan["validation_plan"], *plan["error_analysis_plan"]]}
        errors.extend(f"missing_mandatory_check:{check_id}" for check_id in profile.required_checks(plan)
                      if check_id not in declared_checks)
    return ValidationReport(tuple(errors))


def planning_catalog() -> list[dict[str, Any]]:
    return [{
        "method_family": profile.profile_id, "allowed_backends": list(profile.allowed_backends),
        "required_model_fields": list(profile.required_model_fields),
        "required_method_fields": list(profile.required_method_fields),
        "mandatory_checks": list(profile.mandatory_checks),
    } for profile in PROFILES.values()]

