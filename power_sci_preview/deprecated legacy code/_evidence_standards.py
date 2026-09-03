from __future__ import annotations

from copy import deepcopy
from typing import Any


DEFAULT_EVIDENCE_STANDARD_ID = "basic_mechanism_v1"


EVIDENCE_STANDARD_REGISTRY: dict[str, dict[str, Any]] = {
    "clinical_intervention_v1": {
        "schema_version": "evidence_standard_v1",
        "id": "clinical_intervention_v1",
        "hypothesis_type": "clinical_intervention",
        "default_research_mode_prior": "CONTROLLED_INTERVENTION",
        "peer_reviewed_full_text_target": 10,
        "direct_core_full_text_target": 10,
        "accepted_core_designs": [
            "controlled_intervention",
            "randomized_or_controlled_trial",
            "quasi_experiment",
            "before_after_comparison",
            "prospective_or_retrospective_cohort",
            "systematic_review_for_context",
        ],
        "support_designs": [
            "case_control",
            "cross_sectional",
            "implementation_study",
            "mechanistic_or_diagnostic_substudy",
        ],
        "claim_strength_cap": "setting_bound_interventional_or_quasi_causal_inference",
        "claim_strength_notes": (
            "Clinical intervention evidence can support setting-bound causal or quasi-causal claims, "
            "but does not authorize universal efficacy outside the studied population, protocol, and comparator."
        ),
    },
    "policy_population_v1": {
        "schema_version": "evidence_standard_v1",
        "id": "policy_population_v1",
        "hypothesis_type": "policy_population",
        "default_research_mode_prior": "NATURAL_EXPERIMENT_OR_QUASI_EXPERIMENT",
        "peer_reviewed_full_text_target": 10,
        "direct_core_full_text_target": 6,
        "accepted_core_designs": [
            "natural_experiment",
            "interrupted_time_series",
            "difference_in_differences",
            "regression_discontinuity",
            "instrumental_variable",
            "cross_jurisdiction_comparison",
        ],
        "support_designs": [
            "population_surveillance",
            "mechanistic_model",
            "simulation_or_counterfactual_model",
            "implementation_or_adoption_study",
        ],
        "claim_strength_cap": "population_or_policy_level_causal_inference_not_individual_causality",
        "claim_strength_notes": (
            "Policy evidence can support population-level causal inference when identification is credible; "
            "it does not prove individual-level biological or device-level mechanisms by itself."
        ),
    },
    "environmental_ecological_v1": {
        "schema_version": "evidence_standard_v1",
        "id": "environmental_ecological_v1",
        "hypothesis_type": "environmental_ecological",
        "default_research_mode_prior": "OBSERVATIONAL_MODEL_DISCRIMINATION",
        "peer_reviewed_full_text_target": 10,
        "direct_core_full_text_target": 6,
        "accepted_core_designs": [
            "ecological_association",
            "field_observation",
            "environmental_monitoring",
            "longitudinal_or_time_series_sampling",
            "cross_site_comparison",
            "natural_experiment",
        ],
        "support_designs": [
            "laboratory_microcosm_or_mesocosm",
            "remote_sensing_or_sensor_network",
            "mechanistic_model",
            "animal_or_system_model",
        ],
        "claim_strength_cap": "association_or_pathway_support_not_unbounded_intervention_claim",
        "claim_strength_notes": (
            "Environmental and ecological evidence can support associations, pathways, and bounded field mechanisms; "
            "it does not by itself prove downstream clinical, industrial, or planetary-scale outcomes."
        ),
    },
    "basic_mechanism_v1": {
        "schema_version": "evidence_standard_v1",
        "id": "basic_mechanism_v1",
        "hypothesis_type": "basic_mechanism",
        "default_research_mode_prior": "CONTROLLED_INTERVENTION",
        "peer_reviewed_full_text_target": 10,
        "direct_core_full_text_target": 6,
        "accepted_core_designs": [
            "controlled_experiment",
            "laboratory_measurement",
            "mechanistic_assay",
            "perturbation_or_ablation",
            "computational_model_or_simulation",
            "theoretical_framework_or_derivation",
        ],
        "support_designs": [
            "benchmark_dataset",
            "replication_or_robustness_test",
            "in_vivo_or_system_model",
            "structure_function_mapping",
        ],
        "claim_strength_cap": "source_traceable_mechanism_or_formal_model_plausibility",
        "claim_strength_notes": (
            "Basic mechanism evidence can support a source-traceable mechanism, parameter, model, or formal claim; "
            "translation to field, clinical, population, or deployment outcomes needs separate evidence."
        ),
    },
    "surveillance_monitoring_v1": {
        "schema_version": "evidence_standard_v1",
        "id": "surveillance_monitoring_v1",
        "hypothesis_type": "surveillance_monitoring",
        "default_research_mode_prior": "INSTRUMENTATION_OR_MEASUREMENT",
        "peer_reviewed_full_text_target": 10,
        "direct_core_full_text_target": 4,
        "accepted_core_designs": [
            "measurement_system_validation",
            "sensor_or_detector_validation",
            "genomic_or_signal_tracking",
            "spatiotemporal_monitoring",
            "benchmark_or_calibration_study",
            "sensitivity_specificity_or_uncertainty_assessment",
        ],
        "support_designs": [
            "field_deployment",
            "data_quality_audit",
            "decision_support_evaluation",
            "interoperability_or_reproducibility_test",
        ],
        "claim_strength_cap": "detection_measurement_or_decision_support_utility",
        "claim_strength_notes": (
            "Surveillance and monitoring evidence can support detection, measurement, warning, or decision-support utility; "
            "it does not establish that the monitored phenomenon is controlled or resolved."
        ),
    },
    "combined_strategy_v1": {
        "schema_version": "evidence_standard_v1",
        "id": "combined_strategy_v1",
        "hypothesis_type": "combined_strategy",
        "default_research_mode_prior": "OBSERVATIONAL_MODEL_DISCRIMINATION",
        "peer_reviewed_full_text_target": 10,
        "direct_core_full_text_target": 10,
        "accepted_core_designs": [
            "component_level_direct_evidence",
            "interaction_or_synergy_test",
            "factorial_or_ablation_design",
            "integrated_system_evaluation",
            "cross_scale_synthesis",
        ],
        "support_designs": [
            "component_review",
            "decision_model",
            "implementation_or_feasibility_study",
            "boundary_condition_test",
        ],
        "claim_strength_cap": "additive_or_synergistic_claim_capped_by_weakest_component",
        "claim_strength_notes": (
            "Combined-strategy evidence must not lower component standards. Any additive or synergistic claim is capped by "
            "the weakest directly evidenced component and by whether interaction evidence exists."
        ),
        "does_not_lower_component_standards": True,
    },
    # These standards are selected from an SH's epistemic profile rather than
    # from a discipline name.  They prevent a parameter constraint, theorem,
    # or observation from inheriting the controlled-intervention contract used
    # by experimental mechanism studies.
    "experimental_causal_v1": {
        "schema_version": "evidence_standard_v1",
        "id": "experimental_causal_v1",
        "hypothesis_type": "basic_mechanism",
        "default_research_mode_prior": "CONTROLLED_INTERVENTION",
        "peer_reviewed_full_text_target": 10,
        "direct_core_full_text_target": 1,
        "requires_intervention": True,
        "accepted_core_designs": [
            "controlled_experiment", "intervention", "perturbation",
            "randomized_comparison", "dose_response", "mechanistic_rescue",
            "randomized_or_controlled_trial", "perturbation_or_ablation",
        ],
        "support_designs": ["observational_context", "simulation", "review_or_background"],
        "required_properties": ["controlled_comparator", "intervention_definition", "observable_to_claim_link"],
        "claim_strength_cap": "bounded_interventional_or_mechanistic_inference",
        "claim_strength_notes": "Direct causal claims require a compatible intervention, control, or credible causal-identification design.",
    },
    "observational_inference_v1": {
        "schema_version": "evidence_standard_v1",
        "id": "observational_inference_v1",
        "hypothesis_type": "environmental_ecological",
        "default_research_mode_prior": "OBSERVATIONAL_MODEL_DISCRIMINATION",
        "peer_reviewed_full_text_target": 10,
        "direct_core_full_text_target": 1,
        "requires_intervention": False,
        "accepted_core_designs": [
            "direct_observation", "survey_or_catalog_analysis", "mission_or_data_release",
            "time_domain_observation", "multi_messenger_observation", "natural_experiment",
            "parameter_likelihood_or_posterior_analysis", "statistical_model_comparison",
            "cross_dataset_constraint", "time_series_or_longitudinal_observation",
        ],
        "support_designs": ["calibration_or_systematics", "forecast", "theoretical_context", "review_or_survey"],
        "required_properties": ["data_provenance", "quantified_uncertainty", "observable_to_claim_link"],
        "preferred_properties": ["covariance_handling", "systematic_error_analysis", "independent_observational_channel", "reproducible_likelihood_or_catalog"],
        "claim_strength_cap": "observation_bound_constraint_or_model_discrimination",
        "claim_strength_notes": "Core evidence may be an observation, likelihood, posterior, catalog, data release, or model fit with stated uncertainty; artificial intervention is not required.",
    },
    "theoretical_derivation_v1": {
        "schema_version": "evidence_standard_v1",
        "id": "theoretical_derivation_v1",
        "hypothesis_type": "basic_mechanism",
        "default_research_mode_prior": "THEORETICAL_OR_FORMAL",
        "peer_reviewed_full_text_target": 10,
        "direct_core_full_text_target": 1,
        "requires_intervention": False,
        "accepted_core_designs": [
            "analytical_derivation", "field_equation_solution", "consistency_analysis",
            "stability_analysis", "symmetry_argument", "limiting_case", "no_go_result",
            "numerical_solution", "observable_prediction", "equation_solution",
            "symmetry_or_conservation_argument", "consistency_or_stability_analysis",
        ],
        "support_designs": ["numerical_solution", "simulation", "observational_context", "review_or_background"],
        "required_properties": ["explicit_assumptions", "derivation_or_computational_chain", "stated_domain_of_validity"],
        "claim_strength_cap": "assumption_bound_theoretical_derivation",
        "claim_strength_notes": "Theory papers establish consequences of stated assumptions; empirical adequacy requires separately compatible observational or experimental evidence.",
    },
    "formal_mathematics_v1": {
        "schema_version": "evidence_standard_v1",
        "id": "formal_mathematics_v1",
        "hypothesis_type": "basic_mechanism",
        "default_research_mode_prior": "THEORETICAL_OR_FORMAL",
        "peer_reviewed_full_text_target": 10,
        "direct_core_full_text_target": 1,
        "requires_intervention": False,
        "accepted_core_designs": ["proof", "theorem", "lemma", "lemma_chain", "counterexample", "equivalence_result", "independence_result", "formally_verified_proof", "formal_proof", "formal_verification"],
        "support_designs": ["computational_example", "survey_or_background", "heuristic_argument"],
        "required_properties": ["precise_statement", "explicit_assumptions", "valid_proof_dependency"],
        "not_sufficient_alone": ["numerical_examples", "empirical_frequency", "simulation_without_proof"],
        "claim_strength_cap": "assumption_bound_formal_result",
        "claim_strength_notes": "A proof or counterexample is direct core evidence for a formal claim; numerical examples alone are not a substitute for proof.",
    },
    "computational_simulation_v1": {
        "schema_version": "evidence_standard_v1",
        "id": "computational_simulation_v1",
        "hypothesis_type": "basic_mechanism",
        "default_research_mode_prior": "COMPUTATIONAL_INTERVENTION",
        "peer_reviewed_full_text_target": 10,
        "direct_core_full_text_target": 1,
        "requires_intervention": False,
        "accepted_core_designs": ["validated_simulation", "convergence_analysis", "benchmark_comparison", "parameter_sensitivity", "ablation", "uncertainty_propagation", "sensitivity_analysis", "numerical_experiment"],
        "support_designs": ["theoretical_context", "measurement_or_observation_context", "review_or_background"],
        "required_properties": ["model_definition", "numerical_method", "convergence_or_validation", "parameter_and_initial_condition_disclosure"],
        "claim_strength_cap": "model_and_validation_bound_computational_inference",
        "claim_strength_notes": "Simulation evidence is core only when the model, numerical conditions, and validation or convergence basis are explicit.",
    },
    "engineering_validation_v1": {
        "schema_version": "evidence_standard_v1",
        "id": "engineering_validation_v1",
        "hypothesis_type": "surveillance_monitoring",
        "default_research_mode_prior": "INSTRUMENTATION_OR_MEASUREMENT",
        "peer_reviewed_full_text_target": 10,
        "direct_core_full_text_target": 1,
        "requires_intervention": False,
        "accepted_core_designs": ["performance_test", "benchmark_or_reference_comparison", "calibration_validation", "robustness_test", "fault_mode_analysis", "field_or_system_deployment"],
        "support_designs": ["simulation", "component_characterization", "review_or_background"],
        "claim_strength_cap": "specified_condition_engineering_performance",
        "claim_strength_notes": "Engineering claims are bounded by the tested configuration, metric, operating regime, and comparator.",
    },
    "classification_description_v1": {
        "schema_version": "evidence_standard_v1",
        "id": "classification_description_v1",
        "hypothesis_type": "surveillance_monitoring",
        "default_research_mode_prior": "OBSERVATIONAL_MODEL_DISCRIMINATION",
        "peer_reviewed_full_text_target": 10,
        "direct_core_full_text_target": 1,
        "requires_intervention": False,
        "accepted_core_designs": ["specimen_or_sample_description", "catalog_or_atlas", "morphological_or_structural_characterization", "phylogenetic_or_classification_analysis", "observational_catalog"],
        "support_designs": ["method_validation", "review_or_background", "comparative_description"],
        "claim_strength_cap": "sample_and_definition_bound_description",
        "claim_strength_notes": "Descriptive evidence supports classification or characterization within the stated sampling and definition boundary, not an intervention effect.",
    },
    "synthesis_evaluation_v1": {
        "schema_version": "evidence_standard_v1",
        "id": "synthesis_evaluation_v1",
        "hypothesis_type": "combined_strategy",
        "default_research_mode_prior": "OBSERVATIONAL_MODEL_DISCRIMINATION",
        "peer_reviewed_full_text_target": 10,
        "direct_core_full_text_target": 1,
        "requires_intervention": False,
        "accepted_core_designs": ["systematic_review", "meta_analysis", "evidence_synthesis", "technology_assessment", "cross_source_comparison"],
        "support_designs": ["primary_study", "data_release", "theoretical_context", "method_context"],
        "claim_strength_cap": "evidence_quality_bound_synthesis",
        "claim_strength_notes": "A synthesis can organize and qualify evidence, but it cannot convert heterogeneous source quality into a stronger causal claim.",
    },
}

# Canonical wording for the theoretical-physics family.  Keep the earlier id
# as a compatibility alias because persisted projects may already contain it.
EVIDENCE_STANDARD_REGISTRY["theoretical_physics_v1"] = {
    **EVIDENCE_STANDARD_REGISTRY["theoretical_derivation_v1"],
    "id": "theoretical_physics_v1",
}

EVIDENCE_STANDARD_ALIASES = {
    "theoretical_derivation_v1": "theoretical_physics_v1",
}


STANDARD_BY_HYPOTHESIS_TYPE: dict[str, str] = {}
for _standard_key, _standard_value in EVIDENCE_STANDARD_REGISTRY.items():
    # Legacy hypothesis-type fallback remains stable.  The newer standards are
    # selected through ``epistemic_profile.evidence_standard_id`` instead of
    # silently changing all historic ``basic_mechanism`` SHs.
    STANDARD_BY_HYPOTHESIS_TYPE.setdefault(
        str(_standard_value.get("hypothesis_type") or ""),
        _standard_key,
    )


def normalize_evidence_standard_id(
    value: Any,
    *,
    hypothesis_type: str = "",
) -> str:
    key = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    key = EVIDENCE_STANDARD_ALIASES.get(key, key)
    if key in EVIDENCE_STANDARD_REGISTRY:
        return key
    type_key = str(hypothesis_type or "").strip().lower().replace("-", "_").replace(" ", "_")
    return STANDARD_BY_HYPOTHESIS_TYPE.get(type_key, DEFAULT_EVIDENCE_STANDARD_ID)


def get_evidence_standard(standard_id: Any, *, hypothesis_type: str = "") -> dict[str, Any]:
    normalized = normalize_evidence_standard_id(standard_id, hypothesis_type=hypothesis_type)
    return deepcopy(EVIDENCE_STANDARD_REGISTRY[normalized])


def evidence_standard_retrieval_policy(standard_id: Any, *, hypothesis_type: str = "") -> dict[str, Any]:
    standard = get_evidence_standard(standard_id, hypothesis_type=hypothesis_type)
    return {
        "peer_reviewed_full_text_target": int(standard["peer_reviewed_full_text_target"]),
        "direct_core_full_text_target": int(standard["direct_core_full_text_target"]),
        "accepted_core_designs": list(standard.get("accepted_core_designs") or []),
        "support_designs": list(standard.get("support_designs") or []),
        "required_properties": list(standard.get("required_properties") or []),
        "preferred_properties": list(standard.get("preferred_properties") or []),
        "not_sufficient_alone": list(standard.get("not_sufficient_alone") or []),
        "requires_intervention": bool(standard.get("requires_intervention") is True),
        "claim_strength_cap": str(standard.get("claim_strength_cap") or ""),
        "claim_strength_notes": str(standard.get("claim_strength_notes") or ""),
    }
