"""Domain-aware scientific intervention profiles for Idea Agent roots.

The runtime discipline taxonomy remains the source of canonical discipline IDs.
This module adds an Idea-Agent-local crosswalk from PaperSeek OpenAlex fields to
domain-native intervention profiles.  It intentionally contains no LLM calls or
filesystem lookups so profile selection is deterministic and easy to test.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Dict, Mapping, Optional, Sequence

from src.pipeline.discipline_taxonomy import (
    canonicalize_discipline_key,
    resolve_discipline_taxonomy,
)


@dataclass(frozen=True)
class ComponentRoleSpec:
    role_id: str
    label: str
    description: str
    examples: tuple[str, ...] = ()
    required_for_root: bool = True

    def to_payload(self) -> Dict[str, Any]:
        return {
            "role_id": self.role_id,
            "label": self.label,
            "description": self.description,
            "examples": list(self.examples),
            "required_for_root": self.required_for_root,
        }


@dataclass(frozen=True)
class ContributionModeSpec:
    mode_id: str
    label: str
    primary_contribution: str
    secondary_only: str
    required_evidence_or_validation: str

    def to_payload(self) -> Dict[str, Any]:
        return {
            "mode_id": self.mode_id,
            "label": self.label,
            "primary_contribution": self.primary_contribution,
            "secondary_only": self.secondary_only,
            "required_evidence_or_validation": self.required_evidence_or_validation,
        }


@dataclass(frozen=True)
class ValidationRequirement:
    requirement_id: str
    label: str
    description: str

    def to_payload(self) -> Dict[str, str]:
        return {
            "requirement_id": self.requirement_id,
            "label": self.label,
            "description": self.description,
        }


@dataclass(frozen=True)
class ScientificObjectSchema:
    """Profile-native vocabulary for representing a scientific intervention.

    The legacy MCTS still stores a list of ``components``.  This schema gives
    those components a domain-native interpretation without requiring a new
    atomic-edit protocol, so old idea contracts remain readable.
    """

    profile_id: str
    object_types: tuple[str, ...]
    allowed_operations: tuple[str, ...]
    target_object_roles: tuple[str, ...] = ()
    claim_delta_roles: tuple[str, ...] = ()
    mechanism_delta_roles: tuple[str, ...] = ()
    evidence_obligation_roles: tuple[str, ...] = ()
    boundary_condition_roles: tuple[str, ...] = ()
    measurement_or_observation_roles: tuple[str, ...] = ()

    def to_payload(self) -> Dict[str, Any]:
        return {
            "schema_version": "scientific_object_schema_v1",
            "profile_id": self.profile_id,
            "object_types": list(self.object_types),
            "allowed_operations": list(self.allowed_operations),
            "target_object_roles": list(self.target_object_roles),
            "claim_delta_roles": list(self.claim_delta_roles),
            "mechanism_delta_roles": list(self.mechanism_delta_roles),
            "evidence_obligation_roles": list(self.evidence_obligation_roles),
            "boundary_condition_roles": list(self.boundary_condition_roles),
            "measurement_or_observation_roles": list(self.measurement_or_observation_roles),
        }


@dataclass(frozen=True)
class ScientificInterventionProfile:
    profile_id: str
    label: str
    discipline_keys: tuple[str, ...]
    component_roles: tuple[ComponentRoleSpec, ...]
    contribution_modes: tuple[ContributionModeSpec, ...]
    defect_tags: tuple[str, ...]
    validation_requirements: tuple[ValidationRequirement, ...]
    generation_rules: tuple[str, ...]
    evaluation_anchors: Dict[str, tuple[str, ...]]
    forbidden_default_patterns: tuple[str, ...]

    def default_component_roles(self) -> tuple[ComponentRoleSpec, ...]:
        return tuple(role for role in self.component_roles if role.required_for_root)

    def default_component_names(self) -> list[str]:
        return [role.role_id for role in self.default_component_roles()]

    def to_payload(self) -> Dict[str, Any]:
        payload = {
            "schema_version": "scientific_intervention_profile_v1",
            "profile_id": self.profile_id,
            "label": self.label,
            "discipline_keys": list(self.discipline_keys),
            "component_roles": [role.to_payload() for role in self.component_roles],
            "contribution_modes": [mode.to_payload() for mode in self.contribution_modes],
            "defect_tags": list(self.defect_tags),
            "validation_requirements": [
                requirement.to_payload() for requirement in self.validation_requirements
            ],
            "generation_rules": list(self.generation_rules),
            "evaluation_anchors": {
                key: list(values) for key, values in self.evaluation_anchors.items()
            },
            "forbidden_default_patterns": list(self.forbidden_default_patterns),
        }
        object_schema = get_scientific_object_schema(self.profile_id)
        if object_schema is not None:
            object_payload = object_schema.to_payload()
            payload["scientific_object_schema"] = object_payload
            payload["object_roles"] = list(object_payload.get("object_types") or [])
            payload["allowed_operations"] = list(object_payload.get("allowed_operations") or [])
            payload["evidence_obligations"] = list(
                object_payload.get("evidence_obligation_roles") or []
            )
            payload["boundary_obligations"] = list(
                object_payload.get("boundary_condition_roles") or []
            )
        return payload


@dataclass(frozen=True)
class ScientificObjectSpec:
    object_id: str
    profile_id: str
    label: str
    description: str
    examples: tuple[str, ...] = ()
    object_type: str = "scientific_object"
    allowed_operations: tuple[str, ...] = ()
    evidence_obligations: tuple[str, ...] = ()
    boundary_roles: tuple[str, ...] = ()
    measurement_roles: tuple[str, ...] = ()

    def to_payload(self) -> Dict[str, Any]:
        return {
            "object_id": self.object_id,
            "profile_id": self.profile_id,
            "label": self.label,
            "description": self.description,
            "examples": list(self.examples),
            "object_type": self.object_type,
            "allowed_operations": list(self.allowed_operations),
            "evidence_obligations": list(self.evidence_obligations),
            "boundary_roles": list(self.boundary_roles),
            "measurement_roles": list(self.measurement_roles),
        }


@dataclass(frozen=True)
class ScientificFieldSpec:
    field_id: str
    label: str
    paperseek_domain: str
    discipline_key: str
    primary_profile: str
    secondary_profiles: tuple[str, ...] = ()
    object_role_ids: tuple[str, ...] = ()

    def to_payload(self) -> Dict[str, Any]:
        return {
            "field_id": self.field_id,
            "label": self.label,
            "paperseek_domain": self.paperseek_domain,
            "discipline_key": self.discipline_key,
            "primary_profile": self.primary_profile,
            "secondary_profiles": list(self.secondary_profiles),
            "object_role_ids": list(self.object_role_ids),
        }


RETAINED_PAPERSEEK_OPENALEX_FIELDS: tuple[str, ...] = (
    "11",
    "13",
    "15",
    "16",
    "17",
    "19",
    "21",
    "22",
    "23",
    "24",
    "25",
    "26",
    "27",
    "28",
    "29",
    "30",
    "31",
    "34",
    "35",
    "36",
)

IGNORED_PAPERSEEK_OPENALEX_FIELDS: frozenset[str] = frozenset(
    {"12", "14", "18", "20", "32", "33"}
)


def _role(
    role_id: str,
    label: str,
    description: str,
    *examples: str,
) -> ComponentRoleSpec:
    return ComponentRoleSpec(
        role_id=role_id,
        label=label,
        description=description,
        examples=tuple(examples),
    )


def _mode(
    mode_id: str,
    label: str,
    primary_contribution: str,
    secondary_only: str,
    required_evidence_or_validation: str,
) -> ContributionModeSpec:
    return ContributionModeSpec(
        mode_id=mode_id,
        label=label,
        primary_contribution=primary_contribution,
        secondary_only=secondary_only,
        required_evidence_or_validation=required_evidence_or_validation,
    )


def _validation(requirement_id: str, label: str, description: str) -> ValidationRequirement:
    return ValidationRequirement(requirement_id, label, description)


_COMMON_GENERATION_RULES = (
    "Introduce one concrete intervention compatible with the fixed scientific profile.",
    "Keep the primary contribution tied to a mechanism, relation, measurement, or boundary.",
    "Do not make a generic benchmark, audit, or reporting layer the primary contribution.",
)

_COMPUTATIONAL_ROLES = (
    _role("backbone_model", "Representation or model", "Computational representation or model family."),
    _role("objective", "Objective or decision rule", "Optimization, inference, or decision criterion."),
    _role("evaluation_harness", "Task and evaluation protocol", "Task interface, protocol, and measurable outcome."),
)

_PROFILE_REGISTRY: Dict[str, ScientificInterventionProfile] = {
    "computational_algorithmic": ScientificInterventionProfile(
        profile_id="computational_algorithmic",
        label="Computational and Algorithmic Research",
        discipline_keys=("computer_science",),
        component_roles=_COMPUTATIONAL_ROLES,
        contribution_modes=(
            _mode(
                "algorithmic_mechanism",
                "Algorithmic mechanism",
                "Change representation, algorithm, objective, training, or inference behavior.",
                "A benchmark or generic monitoring wrapper without a mechanism change.",
                "Ablation, counterfactual, stress, resource, and task-level comparison.",
            ),
        ),
        defect_tags=(
            "feature_dumping",
            "latency_bottleneck",
            "weak_fallback_behavior",
            "monolithic_design",
            "unresolved_alternative_explanation",
        ),
        validation_requirements=(
            _validation("task_baseline", "Task baseline", "Compare against a relevant task and method baseline."),
            _validation("mechanism_ablation", "Mechanism ablation", "Remove or replace the proposed mechanism."),
            _validation("resource_stress", "Resource stress", "Report relevant compute, latency, or memory boundaries."),
        ),
        generation_rules=_COMMON_GENERATION_RULES
        + ("Algorithmic or training language is valid when grounded in the topic.",),
        evaluation_anchors={
            "explanatory_power": ("changes task-solving mechanism", "connects intervention to behavior"),
            "identifiability": ("ablation", "counterfactual", "mechanism comparison"),
            "protocol_score": ("baseline", "stress", "resource", "ablation"),
        },
        forbidden_default_patterns=(),
    ),
    "formal_theoretical": ScientificInterventionProfile(
        profile_id="formal_theoretical",
        label="Formal and Theoretical Research",
        discipline_keys=("mathematics", "physics_astronomy"),
        component_roles=(
            _role("formal_object", "Formal object", "Object, structure, or system under formal study."),
            _role("assumptions_or_axioms", "Assumptions or axioms", "Conditions under which the claim is posed."),
            _role("target_relation", "Target proposition or relation", "The theorem, relation, or impossibility claim."),
            _role("derivation_or_construction", "Derivation or construction", "Proof, construction, or mathematical derivation."),
            _role("validity_domain", "Validity domain", "Regime, domain, or conditions where the result applies."),
            _role("counterexample_boundary", "Counterexample or boundary", "Counterexample space and limiting cases."),
            _role("proof_or_verification", "Proof or verification", "Proof audit or reproducible computational check."),
        ),
        contribution_modes=(
            _mode("theorem_or_condition_relaxation", "Theorem or condition relaxation", "Add, relax, or unify a formal condition with a justified result.", "A numerical benchmark without a formal claim.", "Complete assumptions, derivation or proof, and boundary cases."),
            _mode("counterexample_or_unification", "Counterexample or unification", "Separate competing claims with a counterexample or unifying relation.", "A new software module without a formal consequence.", "Reproducible proof, counterexample, or symbolic/numerical verification."),
        ),
        defect_tags=("missing_assumption", "proof_gap", "missing_counterexample", "invalid_generalization", "unresolved_alternative_explanation"),
        validation_requirements=(
            _validation("complete_assumptions", "Complete assumptions", "State assumptions and quantifiers explicitly."),
            _validation("proof_or_derivation", "Proof or derivation", "Provide a proof, derivation, or auditable construction."),
            _validation("boundary_case", "Boundary case", "Check a counterexample or limiting regime."),
        ),
        generation_rules=_COMMON_GENERATION_RULES + ("Prefer formal assumptions, relations, constructions, proofs, or counterexamples over software components.",),
        evaluation_anchors={
            "explanatory_power": ("unifies a relation", "explains a formal obstruction"),
            "identifiability": ("proof", "counterexample", "condition boundary"),
            "protocol_score": ("formal proof", "derivation audit", "numerical example"),
        },
        forbidden_default_patterns=("backbone_model", "objective", "evaluation_harness"),
    ),
    "physical_materials_chemical": ScientificInterventionProfile(
        profile_id="physical_materials_chemical",
        label="Physical, Materials, and Chemical Research",
        discipline_keys=("materials_science", "chemistry", "chemical_engineering"),
        component_roles=(
            _role("material_or_reactant_system", "Material or reactant system", "Material, composition, reactant, or sample system."),
            _role("controllable_process_or_composition", "Controllable process or composition", "Composition, synthesis, processing, or operating variable."),
            _role("structural_or_state", "Structural or state variable", "Microstructure, phase, state, or intermediate species."),
            _role("candidate_mechanism", "Candidate mechanism", "Structure-process-property or reaction mechanism."),
            _role("property_or_performance_endpoint", "Property or performance endpoint", "Measured property, yield, stability, or performance endpoint."),
            _role("characterization_and_comparator", "Characterization and comparator", "Characterization method, reference sample, and comparison."),
        ),
        contribution_modes=(
            _mode("structure_property_mechanism", "Structure-property mechanism", "Explain or discriminate a structure/process/property mechanism.", "A characterization list without a mechanism or validity question.", "Reference comparison, direct or proxy characterization, endpoint, and competing mechanism test."),
            _mode("process_structure_control", "Process-structure control", "Identify a controllable processing window and its structural consequence.", "A parameter sweep without a causal or reproducible interpretation.", "Process baseline, structure characterization, endpoint, and environmental boundary."),
            _mode("measurement_or_characterization_validity", "Measurement or characterization validity", "Resolve a measurement construct or calibration bottleneck.", "A generic reporting protocol unrelated to a scientific measurement claim.", "Calibration, comparator, repeatability, and construct validity."),
        ),
        defect_tags=("measurement_construct_mismatch", "unsupported_causal_link", "missing_boundary_condition", "insufficient_reproducibility", "unresolved_alternative_explanation"),
        validation_requirements=(
            _validation("material_or_process_comparator", "Material or process comparator", "Include a baseline material, composition, or process."),
            _validation("structure_characterization", "Structure characterization", "Measure a direct or proxy structural state."),
            _validation("property_endpoint", "Property endpoint", "Define a measurable property or performance endpoint."),
            _validation("mechanism_competition", "Mechanism competition", "Design an observation that distinguishes candidate mechanisms."),
            _validation("process_boundary", "Process boundary", "Report process, environmental, and failure boundaries."),
        ),
        generation_rules=_COMMON_GENERATION_RULES + ("Prefer material, process, structure, mechanism, property, and characterization language.",),
        evaluation_anchors={
            "explanatory_power": ("structure-process-property mechanism", "reaction path"),
            "identifiability": ("characterization distinguishes mechanisms", "reference comparator"),
            "protocol_score": ("process control", "characterization", "performance", "repeatability"),
        },
        forbidden_default_patterns=("backbone_model", "objective", "evaluation_harness"),
    ),
    "life_molecular_mechanistic": ScientificInterventionProfile(
        profile_id="life_molecular_mechanistic",
        label="Life and Molecular Mechanistic Research",
        discipline_keys=("agricultural_biological_sciences", "biochemistry_genetics_molecular_biology", "immunology_microbiology", "neuroscience", "pharmacology_toxicology_pharmaceutics", "veterinary"),
        component_roles=(
            _role("biological_system", "Biological system", "Organism, cell, tissue, pathogen, or biological system."),
            _role("intervention_or_perturbation", "Intervention or perturbation", "Treatment, exposure, perturbation, or environmental condition."),
            _role("mediator_or_pathway", "Mediator or pathway", "Mediator, pathway, molecular process, or circuit."),
            _role("phenotype_or_endpoint", "Phenotype or endpoint", "Phenotype, assay output, or biological endpoint."),
            _role("assay_or_measurement", "Assay or measurement", "Assay, imaging, sampling, or measurement mapping."),
            _role("comparator_or_control", "Comparator or control", "Control, counterfactual, or competing biological explanation."),
        ),
        contribution_modes=(
            _mode("causal_mechanism", "Causal mechanism", "Identify a perturbation-mediator-phenotype mechanism.", "A descriptive association without intervention or mediator evidence.", "Perturbation, comparator, mediator measurement, endpoint, and boundary."),
            _mode("pathway_or_biomarker", "Pathway or biomarker", "Discriminate a pathway or biomarker with a causal or mechanistic role.", "A predictive marker with no scientific interpretation.", "Assay validity, competing pathway, temporal ordering, and replication."),
            _mode("dose_or_condition_boundary", "Dose or condition boundary", "Identify a dose, exposure, or condition range with a mechanistic transition.", "A threshold selected only for benchmark performance.", "Dose/exposure control, response measurement, safety or ecological boundary."),
        ),
        defect_tags=("unsupported_causal_link", "missing_comparator", "measurement_construct_mismatch", "missing_boundary_condition", "insufficient_reproducibility", "confounding_or_selection_bias"),
        validation_requirements=(
            _validation("perturbation_control", "Perturbation control", "Specify intervention, exposure, or perturbation."),
            _validation("mediator_measurement", "Mediator measurement", "Measure a mediator or pathway rather than only an endpoint."),
            _validation("biological_comparator", "Biological comparator", "Include a control, counterfactual, or competing explanation."),
            _validation("replication_boundary", "Replication and boundary", "Report replication, condition, and failure boundaries."),
        ),
        generation_rules=_COMMON_GENERATION_RULES + ("Prefer biological system, perturbation, mediator, phenotype, assay, and comparator language.",),
        evaluation_anchors={
            "explanatory_power": ("intervention-mediator-phenotype path", "pathway mechanism"),
            "identifiability": ("mediator measurement", "control", "temporal ordering"),
            "protocol_score": ("perturbation", "assay", "replication", "dose boundary"),
        },
        forbidden_default_patterns=("backbone_model", "objective", "evaluation_harness"),
    ),
    "clinical_health": ScientificInterventionProfile(
        profile_id="clinical_health",
        label="Clinical and Health Research",
        discipline_keys=("medicine", "nursing", "dentistry", "health_professions"),
        component_roles=(
            _role("target_population_or_cohort", "Target population or cohort", "Population, cohort, inclusion, and exclusion scope."),
            _role("intervention_or_exposure", "Intervention or exposure", "Treatment, diagnostic action, care pathway, or exposure."),
            _role("comparator_or_counterfactual", "Comparator or counterfactual", "Usual care, control, counterfactual, or comparator."),
            _role("biological_or_clinical_mediator", "Biological or clinical mediator", "Mediator, mechanism, or clinical process."),
            _role("clinical_endpoint", "Clinical endpoint", "Outcome, endpoint, time point, and clinical utility."),
            _role("measurement_and_confounding_control", "Measurement and confounding control", "Measurement validity, bias, confounding, and selection control."),
            _role("safety_or_external_validity_boundary", "Safety or external validity boundary", "Safety, subgroup, transportability, and external validity boundary."),
        ),
        contribution_modes=(
            _mode("causal_mechanism_or_mediation", "Causal mechanism or mediation", "Identify a treatment/exposure-mediator-outcome relation.", "A predictor-only model without clinical causal or utility interpretation.", "Population, comparator, endpoint timing, confounding, and mediator evidence."),
            _mode("treatment_or_diagnostic_strategy", "Treatment or diagnostic strategy", "Improve a clinically actionable intervention or diagnostic decision.", "A benchmark-only score increase without utility or safety evidence.", "Comparator, clinical endpoint, harms, subgroup, and external validity."),
            _mode("outcome_or_measurement_validity", "Outcome or measurement validity", "Resolve an endpoint, measurement, or clinical construct validity bottleneck.", "A generic dashboard or reporting layer.", "Measurement timing, calibration, comparator, reproducibility, and clinical relevance."),
        ),
        defect_tags=("missing_comparator", "confounding_or_selection_bias", "invalid_generalization", "claim_overreach", "measurement_construct_mismatch", "missing_boundary_condition"),
        validation_requirements=(
            _validation("population_scope", "Population scope", "State population and inclusion/exclusion scope."),
            _validation("clinical_comparator", "Clinical comparator", "Specify usual care, control, or counterfactual."),
            _validation("endpoint_timing", "Endpoint timing", "Define endpoint and measurement time points."),
            _validation("bias_and_safety", "Bias and safety", "Address confounding, selection, safety, and subgroup limits."),
            _validation("external_validity", "External validity", "State transportability and generalization boundaries."),
        ),
        generation_rules=_COMMON_GENERATION_RULES + ("Prefer population, intervention, comparator, mediator, endpoint, confounding, safety, and external validity language.",),
        evaluation_anchors={
            "explanatory_power": ("intervention-mediator-outcome path", "clinical mechanism"),
            "identifiability": ("comparator", "confounding control", "endpoint validity"),
            "protocol_score": ("cohort", "endpoint", "safety", "external validity"),
        },
        forbidden_default_patterns=("backbone_model", "objective", "evaluation_harness"),
    ),
    "earth_environment_agro": ScientificInterventionProfile(
        profile_id="earth_environment_agro",
        label="Earth, Environmental, and Agro-ecological Research",
        discipline_keys=("earth_planetary_science", "environmental_science", "agricultural_biological_sciences"),
        component_roles=(
            _role("system_or_ecosystem", "System or ecosystem", "Earth, environmental, agricultural, or ecological system."),
            _role("forcing_or_exposure", "Forcing or exposure", "Forcing, exposure, intervention, or environmental driver."),
            _role("spatiotemporal_scale", "Spatiotemporal scale", "Spatial, temporal, seasonal, or planetary scale."),
            _role("process_or_pathway", "Process or pathway", "Physical, chemical, ecological, or biogeochemical process."),
            _role("response_or_endpoint", "Response or endpoint", "Observed response, yield, risk, or environmental endpoint."),
            _role("observation_platform", "Observation platform", "Sensor, field observation, sample, or model-observation link."),
        ),
        contribution_modes=(
            _mode("forcing_process_response", "Forcing-process-response mechanism", "Explain a forcing or exposure through a process to a response.", "A map, dataset, or forecast benchmark without process interpretation.", "Scale, observation, process comparison, and scenario boundary."),
            _mode("scale_or_regime_boundary", "Scale or regime boundary", "Identify where a process changes across spatial, temporal, or environmental regimes.", "A parameter threshold with no process or scale meaning.", "Multi-scale observation or model comparison and boundary conditions."),
            _mode("observation_or_attribution_design", "Observation or attribution design", "Resolve an observation or causal attribution bottleneck.", "A generic data pipeline without a measurement or attribution claim.", "Observation validity, forcing control, confounders, and cross-validation."),
        ),
        defect_tags=("unsupported_causal_link", "missing_boundary_condition", "measurement_construct_mismatch", "invalid_generalization", "confounding_or_selection_bias", "insufficient_reproducibility"),
        validation_requirements=(
            _validation("forcing_definition", "Forcing definition", "Define driver, exposure, or intervention."),
            _validation("scale_alignment", "Scale alignment", "Match process, observation, and claim scales."),
            _validation("process_observation_link", "Process-observation link", "Connect process claim to observation or model evidence."),
            _validation("scenario_boundary", "Scenario boundary", "Report spatial, temporal, and scenario limits."),
        ),
        generation_rules=_COMMON_GENERATION_RULES + ("Prefer system, forcing, scale, process, response, observation, and scenario language.",),
        evaluation_anchors={
            "explanatory_power": ("forcing-process-response chain", "scale mechanism"),
            "identifiability": ("observation distinguishes process", "spatiotemporal alignment"),
            "protocol_score": ("scenario", "scale sensitivity", "observation/model cross-check"),
        },
        forbidden_default_patterns=("backbone_model", "objective", "evaluation_harness"),
    ),
    "energy_engineering_systems": ScientificInterventionProfile(
        profile_id="energy_engineering_systems",
        label="Energy, Engineering, and Systems Research",
        discipline_keys=("energy", "engineering", "electrical_engineering_systems"),
        component_roles=(
            _role("engineered_system", "Engineered system", "Device, process, infrastructure, or system boundary."),
            _role("controllable_variable", "Controllable variable", "Design, operating, control, or material variable."),
            _role("physical_mechanism", "Physical mechanism", "Mechanism linking controllable variable to system state."),
            _role("constraint_or_safety_condition", "Constraint or safety condition", "Physical, resource, stability, or safety constraint."),
            _role("operating_state", "Operating state", "Operating regime, load, environment, or transient state."),
            _role("performance_or_safety_readout", "Performance or safety readout", "Performance, reliability, efficiency, or safety endpoint."),
        ),
        contribution_modes=(
            _mode("mechanism_or_design_rule", "Mechanism or design rule", "Derive a mechanism-grounded design or operating rule.", "A control wrapper or benchmark without a physical/system mechanism.", "Baseline, mechanism measurement, operating states, and constraints."),
            _mode("stability_or_safety_boundary", "Stability or safety boundary", "Identify a stability, reliability, or safety boundary.", "A metric improvement without a safety or operating interpretation.", "Stress, failure boundary, repeatability, and safety evidence."),
            _mode("cross_scale_system_optimization", "Cross-scale system optimization", "Link component, process, and system-scale variables under constraints.", "A generic optimizer without system-level causal interpretation.", "Operating scenarios, constraint checks, and component/system comparison."),
        ),
        defect_tags=("unsupported_causal_link", "missing_boundary_condition", "insufficient_reproducibility", "claim_overreach", "weak_fallback_behavior", "invalid_generalization"),
        validation_requirements=(
            _validation("system_baseline", "System baseline", "Compare against a relevant design or operating baseline."),
            _validation("mechanism_measurement", "Mechanism measurement", "Measure the physical or system mechanism."),
            _validation("constraint_check", "Constraint and safety check", "Check operating, stability, resource, and safety constraints."),
            _validation("regime_stress", "Regime stress", "Evaluate relevant load, environment, and failure regimes."),
        ),
        generation_rules=_COMMON_GENERATION_RULES + ("Prefer system, controllable variable, mechanism, constraint, operating state, and performance language.",),
        evaluation_anchors={
            "explanatory_power": ("physical mechanism", "system constraint closure"),
            "identifiability": ("measurable state", "constraint or mechanism contrast"),
            "protocol_score": ("baseline", "operating regime", "stability", "safety"),
        },
        forbidden_default_patterns=("backbone_model", "objective", "evaluation_harness"),
    ),
    "generic_scientific": ScientificInterventionProfile(
        profile_id="generic_scientific",
        label="Generic Scientific Intervention",
        discipline_keys=(),
        component_roles=(
            _role("research_object", "Research object", "Object, system, population, or formal entity under study."),
            _role("manipulable_condition", "Manipulable condition", "Condition, exposure, assumption, or intervention that can vary."),
            _role("candidate_mechanism", "Candidate mechanism", "Mechanism or relation proposed to explain the observation."),
            _role("observable_or_endpoint", "Observable or endpoint", "Observable, outcome, property, or formal consequence."),
            _role("comparator_or_counterfactual", "Comparator or counterfactual", "Comparator, control, alternative, or counterfactual."),
            _role("boundary_condition", "Boundary condition", "Conditions where the relation holds or fails."),
        ),
        contribution_modes=(
            _mode("testable_mechanism", "Testable mechanism", "Propose a falsifiable relation between intervention and observable.", "A generic software or reporting wrapper.", "Comparator, discriminating observation, and boundary."),
            _mode("measurement_or_relation", "Measurement or relation", "Clarify an observable mapping or scientific relation.", "A measurement change with no construct or relation claim.", "Measurement validity, alternative explanation, and reproducible check."),
        ),
        defect_tags=("unsupported_causal_link", "unresolved_alternative_explanation", "missing_comparator", "missing_boundary_condition", "claim_overreach"),
        validation_requirements=(
            _validation("object_scope", "Object scope", "State object, scope, and unit of analysis."),
            _validation("discriminating_observation", "Discriminating observation", "Identify an observation that separates explanations."),
            _validation("boundary_or_falsifier", "Boundary or falsifier", "State failure conditions or a falsifier."),
        ),
        generation_rules=_COMMON_GENERATION_RULES + ("Use domain-neutral scientific objects, interventions, mechanisms, observables, comparators, and boundaries.",),
        evaluation_anchors={
            "explanatory_power": ("mechanism explains observation", "relation is explicit"),
            "identifiability": ("comparator", "discriminating observation", "falsifier"),
            "protocol_score": ("reproducible check", "boundary", "alternative explanation"),
        },
        forbidden_default_patterns=("backbone_model", "objective", "evaluation_harness"),
    ),
}

SCIENTIFIC_INTERVENTION_PROFILES = _PROFILE_REGISTRY


PAPERSEEK_FIELD_TO_PROFILE: Dict[str, str] = {
    "11": "earth_environment_agro",
    "13": "life_molecular_mechanistic",
    "15": "physical_materials_chemical",
    "16": "physical_materials_chemical",
    "17": "computational_algorithmic",
    "19": "earth_environment_agro",
    "21": "energy_engineering_systems",
    "22": "energy_engineering_systems",
    "23": "earth_environment_agro",
    "24": "life_molecular_mechanistic",
    "25": "physical_materials_chemical",
    "26": "formal_theoretical",
    "27": "clinical_health",
    "28": "life_molecular_mechanistic",
    "29": "clinical_health",
    "30": "life_molecular_mechanistic",
    "31": "formal_theoretical",
    "34": "life_molecular_mechanistic",
    "35": "clinical_health",
    "36": "clinical_health",
}

PAPERSEEK_FIELD_LABELS: Dict[str, str] = {
    "11": "Agricultural and Biological Sciences",
    "13": "Biochemistry, Genetics and Molecular Biology",
    "15": "Chemical Engineering",
    "16": "Chemistry",
    "17": "Computer Science",
    "19": "Earth and Planetary Sciences",
    "21": "Energy",
    "22": "Engineering",
    "23": "Environmental Science",
    "24": "Immunology and Microbiology",
    "25": "Materials Science",
    "26": "Mathematics",
    "27": "Medicine",
    "28": "Neuroscience",
    "29": "Nursing",
    "30": "Pharmacology, Toxicology and Pharmaceutics",
    "31": "Physics and Astronomy",
    "34": "Veterinary",
    "35": "Dentistry",
    "36": "Health Professions",
}

PAPERSEEK_FIELD_CROSSWALK: Dict[str, Dict[str, str]] = {
    field_id: {
        "openalex_field_id": field_id,
        "label": PAPERSEEK_FIELD_LABELS[field_id],
        "profile_id": profile_id,
        "coverage": "exact",
    }
    for field_id, profile_id in PAPERSEEK_FIELD_TO_PROFILE.items()
}

PAPERSEEK_FIELD_DOMAINS: Dict[str, str] = {
    "11": "Life Sciences",
    "13": "Life Sciences",
    "15": "Physical Sciences",
    "16": "Physical Sciences",
    "17": "Physical Sciences",
    "19": "Physical Sciences",
    "21": "Physical Sciences",
    "22": "Physical Sciences",
    "23": "Physical Sciences",
    "24": "Life Sciences",
    "25": "Physical Sciences",
    "26": "Physical Sciences",
    "27": "Health Sciences",
    "28": "Life Sciences",
    "29": "Health Sciences",
    "30": "Life Sciences",
    "31": "Physical Sciences",
    "34": "Health Sciences",
    "35": "Health Sciences",
    "36": "Health Sciences",
}

PAPERSEEK_FIELD_TO_DISCIPLINE: Dict[str, str] = {
    "11": "agricultural_biological_sciences",
    "13": "biochemistry_genetics_molecular_biology",
    "15": "chemical_engineering",
    "16": "chemistry",
    "17": "computer_science",
    "19": "earth_planetary_science",
    "21": "energy",
    "22": "engineering",
    "23": "environmental_science",
    "24": "immunology_microbiology",
    "25": "materials_science",
    "26": "mathematics",
    "27": "medicine",
    "28": "neuroscience",
    "29": "nursing",
    "30": "pharmacology_toxicology_pharmaceutics",
    "31": "physics_astronomy",
    "34": "veterinary",
    "35": "dentistry",
    "36": "health_professions",
}

PAPERSEEK_FIELD_SECONDARY_PROFILES: Dict[str, tuple[str, ...]] = {
    "11": ("life_molecular_mechanistic",),
    "28": ("clinical_health",),
    "31": ("physical_materials_chemical",),
    "34": ("clinical_health",),
}


def _object_schema(
    profile_id: str,
    object_types: Sequence[str],
    allowed_operations: Sequence[str],
    *,
    target_object_roles: Sequence[str] = (),
    claim_delta_roles: Sequence[str] = (),
    mechanism_delta_roles: Sequence[str] = (),
    evidence_obligation_roles: Sequence[str] = (),
    boundary_condition_roles: Sequence[str] = (),
    measurement_or_observation_roles: Sequence[str] = (),
) -> ScientificObjectSchema:
    return ScientificObjectSchema(
        profile_id=profile_id,
        object_types=tuple(object_types),
        allowed_operations=tuple(allowed_operations),
        target_object_roles=tuple(target_object_roles),
        claim_delta_roles=tuple(claim_delta_roles),
        mechanism_delta_roles=tuple(mechanism_delta_roles),
        evidence_obligation_roles=tuple(evidence_obligation_roles),
        boundary_condition_roles=tuple(boundary_condition_roles),
        measurement_or_observation_roles=tuple(measurement_or_observation_roles),
    )


PROFILE_NATIVE_OBJECT_SCHEMAS: Dict[str, ScientificObjectSchema] = {
    "computational_algorithmic": _object_schema(
        "computational_algorithmic",
        ("backbone_model", "objective", "evaluation_harness"),
        ("replace", "rewire", "optimize", "train", "infer", "ablate", "stress"),
        target_object_roles=("backbone_model", "objective"),
        claim_delta_roles=("objective", "evaluation_harness"),
        mechanism_delta_roles=("backbone_model", "objective"),
        evidence_obligation_roles=("evaluation_harness",),
        boundary_condition_roles=("evaluation_harness",),
        measurement_or_observation_roles=("evaluation_harness",),
    ),
    "formal_theoretical": _object_schema(
        "formal_theoretical",
        ("formal_object", "assumptions_or_axioms", "target_relation", "derivation_or_construction", "validity_domain", "counterexample_boundary", "proof_or_verification"),
        ("assume", "relax", "derive", "construct", "unify", "falsify", "bound", "verify"),
        target_object_roles=("formal_object", "target_relation"),
        claim_delta_roles=("target_relation", "validity_domain"),
        mechanism_delta_roles=("assumptions_or_axioms", "derivation_or_construction"),
        evidence_obligation_roles=("proof_or_verification",),
        boundary_condition_roles=("validity_domain", "counterexample_boundary"),
        measurement_or_observation_roles=("proof_or_verification",),
    ),
    "physical_materials_chemical": _object_schema(
        "physical_materials_chemical",
        ("material_or_reactant_system", "controllable_process_or_composition", "structural_or_state", "candidate_mechanism", "property_or_performance_endpoint", "characterization_and_comparator"),
        ("alter", "synthesize", "anneal", "perturb", "characterize", "compare", "calibrate", "bound"),
        target_object_roles=("material_or_reactant_system", "structural_or_state"),
        claim_delta_roles=("property_or_performance_endpoint", "controllable_process_or_composition"),
        mechanism_delta_roles=("candidate_mechanism", "structural_or_state"),
        evidence_obligation_roles=("characterization_and_comparator", "property_or_performance_endpoint"),
        boundary_condition_roles=("controllable_process_or_composition", "characterization_and_comparator"),
        measurement_or_observation_roles=("characterization_and_comparator", "property_or_performance_endpoint"),
    ),
    "life_molecular_mechanistic": _object_schema(
        "life_molecular_mechanistic",
        ("biological_system", "intervention_or_perturbation", "mediator_or_pathway", "phenotype_or_endpoint", "assay_or_measurement", "comparator_or_control"),
        ("perturb", "intervene", "stratify", "mediate", "measure", "compare", "replicate", "bound"),
        target_object_roles=("biological_system", "mediator_or_pathway"),
        claim_delta_roles=("phenotype_or_endpoint", "intervention_or_perturbation"),
        mechanism_delta_roles=("mediator_or_pathway", "intervention_or_perturbation"),
        evidence_obligation_roles=("assay_or_measurement", "comparator_or_control"),
        boundary_condition_roles=("comparator_or_control", "intervention_or_perturbation"),
        measurement_or_observation_roles=("assay_or_measurement", "phenotype_or_endpoint"),
    ),
    "clinical_health": _object_schema(
        "clinical_health",
        ("target_population_or_cohort", "intervention_or_exposure", "comparator_or_counterfactual", "biological_or_clinical_mediator", "clinical_endpoint", "measurement_and_confounding_control", "safety_or_external_validity_boundary"),
        ("intervene", "stratify", "mediate", "measure", "compare", "calibrate", "bound", "replicate"),
        target_object_roles=("target_population_or_cohort", "clinical_endpoint"),
        claim_delta_roles=("intervention_or_exposure", "clinical_endpoint"),
        mechanism_delta_roles=("biological_or_clinical_mediator", "measurement_and_confounding_control"),
        evidence_obligation_roles=("comparator_or_counterfactual", "measurement_and_confounding_control"),
        boundary_condition_roles=("safety_or_external_validity_boundary", "target_population_or_cohort"),
        measurement_or_observation_roles=("clinical_endpoint", "measurement_and_confounding_control"),
    ),
    "earth_environment_agro": _object_schema(
        "earth_environment_agro",
        ("system_or_ecosystem", "forcing_or_exposure", "spatiotemporal_scale", "process_or_pathway", "response_or_endpoint", "observation_platform"),
        ("perturb", "rescale", "observe", "attribute", "compare", "calibrate", "bound", "scenario_test"),
        target_object_roles=("system_or_ecosystem", "spatiotemporal_scale"),
        claim_delta_roles=("response_or_endpoint", "forcing_or_exposure"),
        mechanism_delta_roles=("process_or_pathway", "forcing_or_exposure"),
        evidence_obligation_roles=("observation_platform", "process_or_pathway"),
        boundary_condition_roles=("spatiotemporal_scale", "forcing_or_exposure"),
        measurement_or_observation_roles=("observation_platform", "response_or_endpoint"),
    ),
    "energy_engineering_systems": _object_schema(
        "energy_engineering_systems",
        ("engineered_system", "controllable_variable", "physical_mechanism", "constraint_or_safety_condition", "operating_state", "performance_or_safety_readout"),
        ("redesign", "operate", "stress", "constrain", "measure", "compare", "calibrate", "bound"),
        target_object_roles=("engineered_system", "operating_state"),
        claim_delta_roles=("performance_or_safety_readout", "controllable_variable"),
        mechanism_delta_roles=("physical_mechanism", "controllable_variable"),
        evidence_obligation_roles=("performance_or_safety_readout", "constraint_or_safety_condition"),
        boundary_condition_roles=("constraint_or_safety_condition", "operating_state"),
        measurement_or_observation_roles=("performance_or_safety_readout", "operating_state"),
    ),
    "generic_scientific": _object_schema(
        "generic_scientific",
        ("research_object", "manipulable_condition", "candidate_mechanism", "observable_or_endpoint", "comparator_or_counterfactual", "boundary_condition"),
        ("define", "perturb", "propose", "measure", "compare", "calibrate", "falsify", "bound"),
        target_object_roles=("research_object",),
        claim_delta_roles=("observable_or_endpoint", "manipulable_condition"),
        mechanism_delta_roles=("candidate_mechanism", "manipulable_condition"),
        evidence_obligation_roles=("comparator_or_counterfactual", "observable_or_endpoint"),
        boundary_condition_roles=("boundary_condition",),
        measurement_or_observation_roles=("observable_or_endpoint",),
    ),
}


def get_scientific_object_schema(profile_id: Any) -> Optional[ScientificObjectSchema]:
    key = str(profile_id or "").strip().lower()
    if not key:
        return None
    return PROFILE_NATIVE_OBJECT_SCHEMAS.get(key)


def list_scientific_object_schemas() -> tuple[ScientificObjectSchema, ...]:
    return tuple(PROFILE_NATIVE_OBJECT_SCHEMAS.values())


def _build_scientific_object_registry() -> Dict[str, ScientificObjectSpec]:
    registry: Dict[str, ScientificObjectSpec] = {}
    for profile_id, profile in _PROFILE_REGISTRY.items():
        for role in profile.component_roles:
            key = f"{profile_id}:{role.role_id}"
            registry[key] = ScientificObjectSpec(
                object_id=role.role_id,
                profile_id=profile_id,
                label=role.label,
                description=role.description,
                examples=role.examples,
                object_type=role.role_id,
                allowed_operations=(get_scientific_object_schema(profile_id).allowed_operations
                                     if get_scientific_object_schema(profile_id) else ()),
                evidence_obligations=(
                    (get_scientific_object_schema(profile_id).evidence_obligation_roles
                     if get_scientific_object_schema(profile_id) else ())
                ),
                boundary_roles=(
                    (get_scientific_object_schema(profile_id).boundary_condition_roles
                     if get_scientific_object_schema(profile_id) else ())
                ),
                measurement_roles=(
                    (get_scientific_object_schema(profile_id).measurement_or_observation_roles
                     if get_scientific_object_schema(profile_id) else ())
                ),
            )
    return registry


SCIENTIFIC_OBJECT_REGISTRY: Dict[str, ScientificObjectSpec] = (
    _build_scientific_object_registry()
)

PAPERSEEK_FIELD_PROFILE_REGISTRY: Dict[str, ScientificFieldSpec] = {
    field_id: ScientificFieldSpec(
        field_id=field_id,
        label=PAPERSEEK_FIELD_LABELS[field_id],
        paperseek_domain=PAPERSEEK_FIELD_DOMAINS[field_id],
        discipline_key=PAPERSEEK_FIELD_TO_DISCIPLINE[field_id],
        primary_profile=profile_id,
        secondary_profiles=PAPERSEEK_FIELD_SECONDARY_PROFILES.get(field_id, ()),
        object_role_ids=tuple(
            role.role_id for role in _PROFILE_REGISTRY[profile_id].default_component_roles()
        ),
    )
    for field_id, profile_id in PAPERSEEK_FIELD_TO_PROFILE.items()
}
PAPERSEEK_FIELD_REGISTRY = PAPERSEEK_FIELD_PROFILE_REGISTRY


def get_scientific_field_spec(field_id: Any) -> Optional[ScientificFieldSpec]:
    return PAPERSEEK_FIELD_PROFILE_REGISTRY.get(str(field_id or "").strip())


def list_scientific_field_specs() -> tuple[ScientificFieldSpec, ...]:
    return tuple(PAPERSEEK_FIELD_PROFILE_REGISTRY.values())


def get_scientific_object_spec(
    profile_id: Any,
    object_id: Any,
) -> Optional[ScientificObjectSpec]:
    profile_key = str(profile_id or "").strip().lower()
    object_key = str(object_id or "").strip().lower()
    if not profile_key or not object_key:
        return None
    return SCIENTIFIC_OBJECT_REGISTRY.get(f"{profile_key}:{object_key}")


DISCIPLINE_TO_PROFILE: Dict[str, str] = {
    discipline: profile_id
    for profile_id, profile in _PROFILE_REGISTRY.items()
    for discipline in profile.discipline_keys
}
DISCIPLINE_TO_PROFILE.update(
    {
        "quantitative_biology": "life_molecular_mechanistic",
        "electrical_engineering": "energy_engineering_systems",
        "statistics": "formal_theoretical",
    }
)


def get_scientific_intervention_profile(profile_id: Any) -> Optional[ScientificInterventionProfile]:
    key = str(profile_id or "").strip().lower()
    if not key:
        return None
    return _PROFILE_REGISTRY.get(key)


def list_scientific_intervention_profiles() -> tuple[ScientificInterventionProfile, ...]:
    return tuple(_PROFILE_REGISTRY.values())


def _as_string_list(value: Any) -> list[str]:
    if value is None:
        return []
    values = value if isinstance(value, (list, tuple, set, frozenset)) else [value]
    return [str(item).strip() for item in values if str(item).strip()]


def _extract_field_ids(resolution: Mapping[str, Any]) -> list[str]:
    field_values: list[str] = []
    for key in (
        "paperseek_openalex_field_ids",
        "openalex_field_ids",
        "resolved_openalex_field_ids",
        "selected_openalex_field_ids",
        "openalex_field_id",
    ):
        field_values.extend(_as_string_list(resolution.get(key)))
    provider_filters = resolution.get("provider_filters")
    if isinstance(provider_filters, Mapping):
        openalex = provider_filters.get("openalex")
        if isinstance(openalex, Mapping):
            field_values.extend(_as_string_list(openalex.get("resolved_field_ids")))
    return list(dict.fromkeys(field_values))


def _iter_project_context_mappings(
    project_context: Mapping[str, Any] | None,
) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(project_context, Mapping):
        return ()
    mappings: list[Mapping[str, Any]] = []
    queue: list[Mapping[str, Any]] = [project_context]
    seen: set[int] = set()
    while queue:
        current = queue.pop(0)
        marker = id(current)
        if marker in seen:
            continue
        seen.add(marker)
        mappings.append(current)
        for key in (
            "research_context",
            "research_identity",
            "llm_payload",
            "domain_context",
            "taxonomy_resolution",
            "discovery_taxonomy",
            "catalog_resolution",
        ):
            nested = current.get(key)
            if isinstance(nested, Mapping):
                queue.append(nested)
    return tuple(mappings)


def _extract_project_context_domain_values(
    project_context: Mapping[str, Any] | None,
) -> list[str]:
    values: list[str] = []
    keys = (
        "primary_discipline",
        "primary_domain",
        "discipline_ids",
        "primary",
        "declared_domain",
        "domain",
        "research_domains",
        "secondary_discipline",
        "secondary_disciplines",
        "secondary_labels",
        "taxonomy_labels",
        "primary_label",
    )
    mappings = _iter_project_context_mappings(project_context)
    for key in keys:
        for mapping in mappings:
            value = mapping.get(key)
            if isinstance(value, Mapping):
                value = value.get("label") or value.get("name") or value.get("id")
            if isinstance(value, (list, tuple, set, frozenset)):
                for item in value:
                    if isinstance(item, Mapping):
                        item = item.get("label") or item.get("name") or item.get("id")
                    text = str(item or "").strip()
                    if text:
                        values.append(text)
            else:
                text = str(value or "").strip()
                if text:
                    values.append(text)
    return list(dict.fromkeys(values))


def _extract_project_context_field_ids(
    project_context: Mapping[str, Any] | None,
) -> list[str]:
    field_ids: list[str] = []
    for mapping in _iter_project_context_mappings(project_context):
        field_ids.extend(_extract_field_ids(mapping))
    return list(dict.fromkeys(field_ids))


def normalize_project_context_discipline_resolution(
    project_context: Mapping[str, Any] | None,
) -> Dict[str, Any]:
    """Extract and canonicalize discipline evidence published by Survey Agent.

    Explicit OpenAlex field IDs in the artifact are preserved as the strongest
    evidence. Domain labels and the LLM primary discipline are normalized
    through the shared canonical discipline taxonomy only when no field ID is
    available.
    """

    if not isinstance(project_context, Mapping):
        return {}

    field_ids = _extract_project_context_field_ids(project_context)
    retained_fields = [
        field_id for field_id in field_ids if field_id in RETAINED_PAPERSEEK_OPENALEX_FIELDS
    ]
    ignored_fields = [
        field_id for field_id in field_ids if field_id in IGNORED_PAPERSEEK_OPENALEX_FIELDS
    ]
    if retained_fields:
        discipline_ids = [
            PAPERSEEK_FIELD_TO_DISCIPLINE[field_id]
            for field_id in retained_fields
            if field_id in PAPERSEEK_FIELD_TO_DISCIPLINE
        ]
        field_spec = get_scientific_field_spec(retained_fields[0])
        return {
            "schema_version": "discipline_taxonomy_v1",
            "status": "resolved",
            "source": "survey_project_context_openalex_field",
            "primary_discipline": discipline_ids[0] if discipline_ids else None,
            "discipline_ids": discipline_ids,
            "paperseek_openalex_field_ids": retained_fields,
            "ignored_openalex_field_ids": ignored_fields,
            "coverage": "exact",
            "field_profile": field_spec.to_payload() if field_spec is not None else {},
        }
    if ignored_fields:
        return {
            "schema_version": "discipline_taxonomy_v1",
            "status": "out_of_scope",
            "source": "survey_project_context_openalex_field",
            "primary_discipline": None,
            "discipline_ids": [],
            "paperseek_openalex_field_ids": ignored_fields,
            "coverage": "unsupported",
        }

    domain_values = _extract_project_context_domain_values(project_context)
    for value in domain_values:
        canonical_key = canonicalize_discipline_key(value)
        if not canonical_key:
            continue
        resolution = dict(resolve_discipline_taxonomy(canonical_key))
        resolution["source"] = "survey_project_context_domain"
        resolution["source_domain_value"] = value
        return resolution

    domain_text = " ".join(domain_values).strip()
    if domain_text:
        resolution = dict(resolve_discipline_taxonomy(domain_text, query=domain_text))
        if resolution.get("status") in {"resolved", "ambiguous"}:
            resolution["source"] = "survey_project_context_domain_heuristic"
            resolution["source_domain_value"] = domain_values[0]
            return resolution
    return {
        "schema_version": "discipline_taxonomy_v1",
        "status": "unresolved",
        "source": "survey_project_context_domain",
        "primary_discipline": None,
        "discipline_ids": [],
        "coverage": "unsupported",
    }


def _extract_discipline_keys(resolution: Mapping[str, Any]) -> list[str]:
    values: list[str] = []
    for key in ("primary_discipline", "primary_domain", "discipline_ids", "root_domains"):
        values.extend(_as_string_list(resolution.get(key)))
    return list(dict.fromkeys(canonicalize_discipline_key(value) for value in values if canonicalize_discipline_key(value)))


def resolve_scientific_intervention_profile(
    discipline_resolution: Mapping[str, Any] | None,
    *,
    root_domains: Sequence[Any] = (),
    project_context: Mapping[str, Any] | None = None,
) -> Optional[ScientificInterventionProfile]:
    """Resolve a deterministic profile from a taxonomy resolution.

    ``out_of_scope`` and explicitly ignored PaperSeek fields return ``None`` so
    callers can preserve the existing human-confirmation/rejection behavior.
    An unresolved topic without an ignored field maps to ``generic_scientific``;
    it never falls back to Computer Science.
    """

    if not isinstance(discipline_resolution, Mapping):
        resolution: Dict[str, Any] = {}
    else:
        resolution = dict(discipline_resolution)
    nested = resolution.get("discipline_resolution")
    if isinstance(nested, Mapping):
        resolution = {**dict(nested), **resolution}

    project_resolution = normalize_project_context_discipline_resolution(project_context)
    field_ids = _extract_project_context_field_ids(project_context)
    field_ids.extend(_extract_field_ids(resolution))
    field_ids = list(dict.fromkeys(field_ids))
    status = str(resolution.get("status") or "").strip().lower()
    if status == "out_of_scope" and not field_ids:
        return None
    ignored_fields = set(field_ids).intersection(IGNORED_PAPERSEEK_OPENALEX_FIELDS)
    retained_fields = set(field_ids).intersection(RETAINED_PAPERSEEK_OPENALEX_FIELDS)
    if ignored_fields and not retained_fields:
        return None
    for field_id in field_ids:
        profile_id = PAPERSEEK_FIELD_TO_PROFILE.get(field_id)
        if profile_id:
            return _PROFILE_REGISTRY[profile_id]

    explicit_profile = resolution.get("scientific_intervention_profile") or resolution.get("profile_id")
    profile = get_scientific_intervention_profile(explicit_profile)
    if profile is not None:
        return profile

    project_discipline_keys = _extract_discipline_keys(project_resolution)
    for discipline_key in project_discipline_keys:
        profile_id = DISCIPLINE_TO_PROFILE.get(discipline_key)
        if profile_id:
            return _PROFILE_REGISTRY[profile_id]

    discipline_keys = _extract_discipline_keys(resolution)
    discipline_keys.extend(
        canonicalize_discipline_key(value)
        for value in root_domains
        if canonicalize_discipline_key(value)
    )
    for discipline_key in discipline_keys:
        profile_id = DISCIPLINE_TO_PROFILE.get(discipline_key)
        if profile_id:
            return _PROFILE_REGISTRY[profile_id]

    if status in {"out_of_scope", "rejected"}:
        return None
    return _PROFILE_REGISTRY["generic_scientific"]


def _component_role_for_name(
    component: str,
    profile: ScientificInterventionProfile,
) -> Optional[ComponentRoleSpec]:
    normalized = str(component or "").strip().lower().replace(" ", "_")
    if not normalized:
        return None
    for role in profile.component_roles:
        candidates = {role.role_id.lower(), role.label.lower().replace(" ", "_")}
        candidates.update(example.lower().replace(" ", "_") for example in role.examples)
        if normalized in candidates or any(candidate in normalized for candidate in candidates):
            return role
    return None


def build_scientific_intervention_payload(
    profile: ScientificInterventionProfile,
    components: Sequence[Any],
    component_explanations: Mapping[str, Any] | None = None,
    existing: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    """Build the backward-compatible structured root intervention payload."""

    existing_payload = dict(existing) if isinstance(existing, Mapping) else {}
    normalized_components = [str(component).strip() for component in components if str(component).strip()]
    explanation_map = (
        {str(key).strip(): str(value).strip() for key, value in component_explanations.items()}
        if isinstance(component_explanations, Mapping)
        else {}
    )
    existing_roles = existing_payload.get("component_roles")
    existing_role_by_component: Dict[str, Mapping[str, Any]] = {}
    if isinstance(existing_roles, list):
        for role_entry in existing_roles:
            if not isinstance(role_entry, Mapping):
                continue
            component = str(role_entry.get("component") or "").strip()
            if component:
                existing_role_by_component[component] = role_entry

    role_entries: list[Dict[str, Any]] = []
    schema_spec = get_scientific_object_schema(profile.profile_id)
    schema_payload = schema_spec.to_payload() if schema_spec is not None else {}
    for component in normalized_components:
        prior = existing_role_by_component.get(component, {})
        role = _component_role_for_name(component, profile)
        role_entries.append(
            {
                "role_id": str(prior.get("role_id") or (role.role_id if role else "unmapped_component")),
                "component": component,
                "role_explanation": str(
                    prior.get("role_explanation")
                    or explanation_map.get(component)
                    or (role.description if role else "Existing idea component retained from the input." )
                ).strip(),
                "evidence_status": str(prior.get("evidence_status") or "existing").strip(),
                "object_type": str(
                    prior.get("object_type")
                    or (role.role_id if role else "scientific_object")
                ).strip(),
                "allowed_operations": list(schema_payload.get("allowed_operations") or []),
            }
        )

    contribution_modes = profile.contribution_modes
    default_mode = contribution_modes[0].mode_id if contribution_modes else "testable_mechanism"
    requested_mode = str(existing_payload.get("contribution_mode") or "").strip()
    valid_mode_ids = {mode.mode_id for mode in contribution_modes}
    selected_mode = requested_mode if requested_mode in valid_mode_ids else default_mode
    payload = profile.to_payload()
    payload.update(existing_payload)
    payload.update(
        {
            "schema_version": "scientific_intervention_v1",
            "profile_id": profile.profile_id,
            "profile_label": profile.label,
            "algorithmic_semantics_allowed": profile.profile_id == "computational_algorithmic",
            "contribution_mode": selected_mode,
            "component_roles": role_entries,
            "validation_requirements": [
                requirement.to_payload() for requirement in profile.validation_requirements
            ],
            "forbidden_default_patterns": list(profile.forbidden_default_patterns),
            "scientific_object_schema": schema_payload or payload.get("scientific_object_schema", {}),
            "object_roles": list(schema_payload.get("object_types") or []),
            "allowed_operations": list(schema_payload.get("allowed_operations") or []),
            "evidence_obligations": list(schema_payload.get("evidence_obligation_roles") or []),
            "boundary_obligations": list(schema_payload.get("boundary_condition_roles") or []),
            "measurement_or_observation_roles": list(
                schema_payload.get("measurement_or_observation_roles") or []
            ),
        }
    )
    return payload


def format_scientific_intervention_profile_for_prompt(
    intervention: Mapping[str, Any] | ScientificInterventionProfile | None,
) -> str:
    """Render a bounded profile block for generation and evaluation prompts."""

    if isinstance(intervention, ScientificInterventionProfile):
        payload = intervention.to_payload()
        profile = intervention
    elif isinstance(intervention, Mapping):
        payload = dict(intervention)
        profile = get_scientific_intervention_profile(payload.get("profile_id"))
    else:
        payload = {}
        profile = get_scientific_intervention_profile("generic_scientific")

    if profile is None:
        profile = get_scientific_intervention_profile("generic_scientific")
    if profile is None:  # pragma: no cover - registry invariant
        return "Profile unavailable; use domain-neutral scientific objects, mechanisms, observables, and boundaries."

    role_entries = payload.get("component_roles")
    role_lines: list[str] = []
    if isinstance(role_entries, list) and role_entries:
        for entry in role_entries[:10]:
            if not isinstance(entry, Mapping):
                continue
            role_id = str(entry.get("role_id") or "unmapped_component").strip()
            component = str(entry.get("component") or role_id).strip()
            explanation = str(entry.get("role_explanation") or "").strip()
            role_lines.append(f"- {role_id}: {component}{' — ' + explanation if explanation else ''}")
    if not role_lines:
        role_lines = [
            f"- {role.role_id}: {role.description}"
            for role in profile.default_component_roles()
        ]

    modes = payload.get("contribution_modes")
    mode_lines: list[str] = []
    if isinstance(modes, list) and modes:
        for mode in modes[:8]:
            if not isinstance(mode, Mapping):
                continue
            mode_lines.append(
                f"- {mode.get('mode_id')}: {mode.get('primary_contribution')}"
            )
    if not mode_lines:
        mode_lines = [
            f"- {mode.mode_id}: {mode.primary_contribution}"
            for mode in profile.contribution_modes
        ]

    rules = payload.get("generation_rules") or list(profile.generation_rules)
    rule_lines = [f"- {str(rule).strip()}" for rule in rules if str(rule).strip()][:8]
    forbidden = payload.get("forbidden_default_patterns")
    if not isinstance(forbidden, list):
        forbidden = list(profile.forbidden_default_patterns)
    if profile.profile_id == "computational_algorithmic":
        forbidden_lines = [f"- {str(item).strip()}" for item in forbidden if str(item).strip()]
    else:
        forbidden_lines = [
            "- Do not introduce unrelated software-specific objects or optimization contracts.",
            "- Do not treat an observation, measurement, or validation artifact as the primary intervention unless the profile explicitly allows it.",
        ]
    if not forbidden_lines:
        forbidden_lines = ["- None beyond the profile rules."]

    object_schema = payload.get("scientific_object_schema")
    if not isinstance(object_schema, Mapping):
        schema = get_scientific_object_schema(profile.profile_id)
        object_schema = schema.to_payload() if schema is not None else {}
    object_types = object_schema.get("object_types") or []
    allowed_operations = object_schema.get("allowed_operations") or []
    target_object_roles = object_schema.get("target_object_roles") or []
    claim_delta_roles = object_schema.get("claim_delta_roles") or []
    mechanism_delta_roles = object_schema.get("mechanism_delta_roles") or []
    evidence_roles = object_schema.get("evidence_obligation_roles") or []
    boundary_roles = object_schema.get("boundary_condition_roles") or []
    measurement_roles = object_schema.get("measurement_or_observation_roles") or []
    schema_lines = [
        "Profile-native scientific object schema:",
        f"- object_types: {', '.join(str(item) for item in object_types) or 'domain-neutral scientific object'}",
        f"- allowed_operations: {', '.join(str(item) for item in allowed_operations) or 'define, compare, measure, bound'}",
        f"- target_object: {', '.join(str(item) for item in target_object_roles) or 'research object'}",
        f"- claim_delta: {', '.join(str(item) for item in claim_delta_roles) or 'explicit claim or relation'}",
        f"- mechanism_delta: {', '.join(str(item) for item in mechanism_delta_roles) or 'candidate mechanism'}",
        f"- evidence_obligation: {', '.join(str(item) for item in evidence_roles) or 'discriminating observation'}",
        f"- boundary_condition: {', '.join(str(item) for item in boundary_roles) or 'validity and failure boundary'}",
        f"- measurement_or_observation: {', '.join(str(item) for item in measurement_roles) or 'observable or endpoint'}",
        "Use these native objects and operations directly; do not translate them into software modules by default.",
    ]
    gap_routing = payload.get("gap_routing")
    routing_lines: list[str] = []
    if isinstance(gap_routing, Mapping):
        counts = {
            key: len(value)
            for key, value in gap_routing.items()
            if isinstance(value, list) and value
        }
        if counts:
            routing_lines = [
                "Survey Gap Routing:",
                "- core/active gaps may define the main hypothesis target.",
                "- provisional and exploratory gaps may diversify hypotheses but are not automatic novelty evidence.",
                "- supporting constraints affect feasibility, identifiability, and boundary calibration rather than primary novelty.",
                "- verification-only gaps constrain evidence or protocol and must not become primary novelty.",
                "- future-work seeds are exploratory, not established evidence.",
                "- routed counts: " + ", ".join(f"{key}={value}" for key, value in sorted(counts.items())),
            ]

    return "\n".join(
        [
            f"Profile: {payload.get('profile_label') or profile.label}",
            f"Profile ID: {payload.get('profile_id') or profile.profile_id}",
            f"Selected contribution mode: {payload.get('contribution_mode') or profile.contribution_modes[0].mode_id}",
            "Required/root component roles:",
            *role_lines,
            "Allowed primary contribution modes:",
            *mode_lines,
            *schema_lines,
            "Generation rules:",
            *(rule_lines or ["- Follow the selected profile's scientific object and validation semantics."]),
            *routing_lines,
            "Do not default to:",
            *forbidden_lines,
        ]
    )


_PROFILE_DRIFT_PRIMARY_PATTERNS: Dict[str, str] = {
    "training_objective": r"\b(?:training\s+objective|optimization\s+objective|loss\s+function|auxiliary\s+loss)\b",
    "neural_architecture": r"\b(?:neural\s+architecture|network\s+architecture|deep\s+architecture)\b",
    "backbone": r"\bbackbone(?:\s+model)?\b",
    "learned_controller": r"\b(?:learned\s+controller|neural\s+controller|learned\s+policy)\b",
    "benchmark": r"\bbenchmark(?:ing)?\b",
    "router": r"\b(?:router|routing\s+layer|mixture[-\s]of[-\s]experts)\b",
    "inference_time_policy": r"\b(?:inference[-\s]time\s+policy|test[-\s]time\s+policy)\b",
    "model_fine_tuning": r"\b(?:model\s+fine[-\s]?tun(?:e|ing)|fine[-\s]?tuning\s+the\s+model)\b",
    "machine_learning": r"\b(?:machine\s+learning|deep\s+learning)\b",
}

_PROFILE_DRIFT_AUXILIARY_MARKERS = (
    "auxiliary",
    "for analysis",
    "data processing",
    "numerical simulation",
    "computational analysis",
    "secondary tool",
    "supporting tool",
    "post hoc",
    "downstream analysis",
    "machine learning as a tool",
)

_PROFILE_DRIFT_CONTENT_FIELDS = (
    "title",
    "abstract",
    "core_contribution",
    "method",
    "central_hypothesis",
    "scientific_object",
    "mechanism_or_relation",
    "expected_mechanism",
    "intervention_or_transformation",
    "discriminating_observation",
    "boundary_or_failure_condition",
    "claim_scope",
    "assumptions",
    "alternative_explanations",
    "evidence_requirement",
    "evidence_basis",
    "falsifier",
    "risks",
)


def _profile_drift_content(value: Any) -> Any:
    """Return scientific candidate content without profile/control metadata."""

    if not isinstance(value, Mapping):
        return value
    content = {
        field_name: value[field_name]
        for field_name in _PROFILE_DRIFT_CONTENT_FIELDS
        if field_name in value
    }
    return content


def _flatten_profile_drift_text(value: Any, *, limit: int = 12000) -> str:
    chunks: list[str] = []

    def visit(item: Any) -> None:
        if sum(len(chunk) for chunk in chunks) >= limit:
            return
        if isinstance(item, Mapping):
            for key, nested in item.items():
                visit(key)
                visit(nested)
        elif isinstance(item, (list, tuple, set)):
            for nested in item:
                visit(nested)
        elif item is not None:
            text = str(item).strip()
            if text:
                chunks.append(text)

    visit(value)
    return " ".join(chunks)[:limit]


def detect_profile_drift(
    profile_id: Any,
    text: Any = None,
    *,
    candidate: Mapping[str, Any] | None = None,
    survey_handoff: Mapping[str, Any] | None = None,
    research_object: Any = None,
) -> Dict[str, Any]:
    """Detect CS/ML primary-contribution drift without rejecting an idea.

    Computational profiles are intentionally exempt.  For other profiles,
    strong software/optimization terms are material only when they are used as
    the candidate's primary contribution; auxiliary analysis mentions remain
    soft secondary-tool signals.
    """

    if isinstance(profile_id, ScientificInterventionProfile):
        resolved_profile_id = profile_id.profile_id
    elif isinstance(profile_id, Mapping):
        resolved_profile_id = str(profile_id.get("profile_id") or "generic_scientific")
        if candidate is None:
            candidate = profile_id
    else:
        resolved_profile_id = str(profile_id or "generic_scientific")
    resolved_profile_id = resolved_profile_id.strip().lower()
    candidate_value = candidate if candidate is not None else text
    candidate_text = _flatten_profile_drift_text(_profile_drift_content(candidate_value))
    anchor_text = _flatten_profile_drift_text(
        {
            "survey_handoff": survey_handoff or {},
            "research_object": research_object,
        }
    ).lower()
    anchor_text_normalized = anchor_text.replace("_", " ")
    candidate_lower = candidate_text.lower()
    matched_terms: list[str] = []
    secondary_tool_mentions: list[str] = []
    forbidden_primary_terms: list[str] = []
    rewrite_targets: list[str] = []

    for term_name, pattern in _PROFILE_DRIFT_PRIMARY_PATTERNS.items():
        match = re.search(pattern, candidate_lower)
        if not match:
            continue
        matched_terms.append(term_name)
        start = max(0, match.start() - 90)
        end = min(len(candidate_lower), match.end() + 90)
        context = candidate_lower[start:end]
        is_auxiliary = any(marker in context for marker in _PROFILE_DRIFT_AUXILIARY_MARKERS)
        explicitly_scientific = term_name in anchor_text or term_name.replace("_", " ") in anchor_text_normalized
        explicitly_scientific = explicitly_scientific and any(
            marker in anchor_text_normalized
            for marker in ("research object", "scientific object", "mechanism", "gap", "target")
        )
        if is_auxiliary:
            secondary_tool_mentions.append(term_name)
            continue
        if explicitly_scientific:
            secondary_tool_mentions.append(term_name)
            continue
        forbidden_primary_terms.append(term_name)
        rewrite_targets.append(
            f"{term_name}: rewrite as the selected profile's native mechanism, process, relation, object, or boundary"
        )

    if resolved_profile_id == "computational_algorithmic":
        return {
            "profile_id": resolved_profile_id,
            "primary_drift": False,
            "secondary_tool_mentions": [],
            "forbidden_primary_terms": [],
            "drift_severity": "none",
            "rewrite_targets": [],
        }

    if forbidden_primary_terms:
        severity = "material"
    elif secondary_tool_mentions:
        severity = "soft"
    else:
        severity = "none"
    return {
        "profile_id": resolved_profile_id,
        "primary_drift": bool(forbidden_primary_terms),
        "secondary_tool_mentions": list(dict.fromkeys(secondary_tool_mentions)),
        "forbidden_primary_terms": list(dict.fromkeys(forbidden_primary_terms)),
        "drift_severity": severity,
        "rewrite_targets": list(dict.fromkeys(rewrite_targets)),
    }


__all__ = [
    "ComponentRoleSpec",
    "ContributionModeSpec",
    "ValidationRequirement",
    "ScientificInterventionProfile",
    "ScientificObjectSchema",
    "ScientificObjectSpec",
    "ScientificFieldSpec",
    "RETAINED_PAPERSEEK_OPENALEX_FIELDS",
    "IGNORED_PAPERSEEK_OPENALEX_FIELDS",
    "PAPERSEEK_FIELD_TO_PROFILE",
    "PAPERSEEK_FIELD_LABELS",
    "PAPERSEEK_FIELD_CROSSWALK",
    "PAPERSEEK_FIELD_DOMAINS",
    "PAPERSEEK_FIELD_TO_DISCIPLINE",
    "PAPERSEEK_FIELD_SECONDARY_PROFILES",
    "PAPERSEEK_FIELD_PROFILE_REGISTRY",
    "PAPERSEEK_FIELD_REGISTRY",
    "SCIENTIFIC_OBJECT_REGISTRY",
    "PROFILE_NATIVE_OBJECT_SCHEMAS",
    "SCIENTIFIC_INTERVENTION_PROFILES",
    "DISCIPLINE_TO_PROFILE",
    "get_scientific_intervention_profile",
    "list_scientific_intervention_profiles",
    "get_scientific_field_spec",
    "list_scientific_field_specs",
    "get_scientific_object_spec",
    "get_scientific_object_schema",
    "list_scientific_object_schemas",
    "normalize_project_context_discipline_resolution",
    "resolve_scientific_intervention_profile",
    "build_scientific_intervention_payload",
    "format_scientific_intervention_profile_for_prompt",
    "detect_profile_drift",
]
