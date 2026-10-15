"""Algorithm evaluation with fixed comparisons and independent repetitions."""

from .numerical_modeling import NumericalModelingProfile


class AlgorithmEvaluationProfile(NumericalModelingProfile):
    profile_id = "algorithm_evaluation"
    allowed_backends = ("python_project",)
    required_model_fields = ("algorithm", "dataset", "baselines", "assumptions")
    required_method_fields = ("partition", "leakage_prevention", "scoring", "seeds", "uncertainty", "resource_reporting")
    mandatory_checks = ("finite_outputs", "data_provenance", "fair_comparison", "uncertainty")

