"""Data provenance, estimator and uncertainty requirements."""

from .numerical_modeling import NumericalModelingProfile


class DataAnalysisProfile(NumericalModelingProfile):
    profile_id = "data_analysis"
    allowed_backends = ("python_project",)
    required_model_fields = ("dataset", "experimental_unit", "estimand", "assumptions")
    required_method_fields = ("preprocessing", "estimator", "missing_data", "uncertainty", "sensitivity_analysis")
    mandatory_checks = ("finite_outputs", "data_provenance", "estimator_validation", "uncertainty")

