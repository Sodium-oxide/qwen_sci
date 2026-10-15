"""Molecular dynamics scientific obligations."""

from .numerical_modeling import NumericalModelingProfile


class MolecularDynamicsProfile(NumericalModelingProfile):
    profile_id = "molecular_dynamics"
    allowed_backends = ("python_project",)
    required_model_fields = ("structure", "force_field", "boundary_conditions", "composition", "assumptions")
    required_method_fields = ("ensemble", "time_step", "equilibration", "production", "independent_repeats", "correlation_analysis")
    mandatory_checks = ("finite_outputs", "equilibration", "effective_sample_size", "force_field_sensitivity")

