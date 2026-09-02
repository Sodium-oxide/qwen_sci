"""Project- and sub-hypothesis-scoped relevance contracts.

The literature stack already has generic quality and domain checks.  This
module adds the missing *scientific-object* boundary: a paper may not enter a
causal PaperGraph merely because it shares a broad word with the project.  The
same contract records research design separately from causal responsibility,
so high-value observational evidence is retained without being mistaken for
causal validation.  A primary gap still cannot be assembled from one evidence
lane alone when its contract requires complementary discovery and validation.

All terms are derived from the current project and its sub-hypothesis.  There
are deliberately no astrobiology-specific allow-lists in this module.
"""
from __future__ import annotations

from collections import Counter
from hashlib import sha256
from typing import Any
import json
import math
import re

try:
    from .log import log_event
    from ._evidence_roles import evidence_role_retrieval_metadata, evidence_role_time_bucket
except ImportError:
    from log import log_event
    from _evidence_roles import evidence_role_retrieval_metadata, evidence_role_time_bucket

try:
    from ._evidence_fragment_alignment import (
        EVIDENCE_FRAGMENT_ALIGNMENT_VERSION,
        assess_evidence_fragment_alignment,
        normalize_causal_field_from_evidence,
        persist_evidence_fragment_alignments,
        primary_source_span_gate,
        source_bound_field_support,
    )
except ImportError:
    from _evidence_fragment_alignment import (
        EVIDENCE_FRAGMENT_ALIGNMENT_VERSION,
        assess_evidence_fragment_alignment,
        normalize_causal_field_from_evidence,
        persist_evidence_fragment_alignments,
        primary_source_span_gate,
        source_bound_field_support,
    )

try:
    from ._type_directed_evidence import type_directed_admission
except ImportError:
    from _type_directed_evidence import type_directed_admission


ALIGNMENT_VERSION = "research_alignment_v7"
PAPER_EVIDENCE_GENRE_VERSION = "paper_evidence_genre_v5"
MECHANISM_OUTCOME_SYNONYM_DICTIONARY_VERSION = "mechanism_outcome_synonym_dictionary_v1"
SUBHYPOTHESIS_SCOPE_POLICY_VERSION = "subhypothesis_scope_policy_v2"
PREDICTIVE_GENERALIZATION_EVIDENCE_MODE = "predictive_generalization"
CAUSAL_MECHANISM_EVIDENCE_MODE = "causal_mechanism"

# Evidence has two independent axes.  ``research_design`` says how a result
# was obtained; ``causal_role`` says what responsibility it can carry in a
# causal argument.  Neither axis is a domain catalogue, so the same model
# works for clinical, environmental, physical, and computational sciences.
RESEARCH_DESIGN_VALUES = frozenset({
    "theoretical_or_formal_model",
    "observational_human",
    "observational_multiomics",
    "observational_human_multiomics",
    "longitudinal_or_natural_experiment",
    "interventional_human",
    "experimental_animal_or_cellular",
    "experimental_controlled_system",
    "evidence_synthesis",
    "unclassified",
})
CAUSAL_ROLE_VALUES = frozenset({
    "background_or_framework",
    "association",
    "mechanism_discovery",
    "causal_identification",
    "causal_validation",
    "adverse_or_reversal",
    "predictive_validation",
    "unclassified",
})
DIRECT_EVIDENCE_KINDS = frozenset({
    "theoretical_framework",
    "experimental_evidence",
    "mechanism_discovery",
    "causal_validation",
    "causal_identification",
    "adverse_or_reversal",
    "association",
    "predictive_validation",
})
STANDARD_EVIDENCE_LANE_BY_DESIGN = {
    "intervention": "CONTROLLED_INTERVENTION_EVIDENCE",
    "perturbation": "CONTROLLED_EXPERIMENTAL_VALIDATION",
    "randomized_comparison": "CONTROLLED_INTERVENTION_EVIDENCE",
    "dose_response": "CONTROLLED_EXPERIMENTAL_VALIDATION",
    "mechanistic_rescue": "MECHANISTIC_ASSAY",
    "direct_observation": "OBSERVATIONAL_COHORT_EVIDENCE",
    "survey_or_catalog_analysis": "OBSERVATIONAL_COHORT_EVIDENCE",
    "mission_or_data_release": "OBSERVATIONAL_COHORT_EVIDENCE",
    "time_domain_observation": "OBSERVATIONAL_COHORT_EVIDENCE",
    "multi_messenger_observation": "OBSERVATIONAL_COHORT_EVIDENCE",
    "parameter_likelihood_or_posterior_analysis": "OBSERVATIONAL_COHORT_EVIDENCE",
    "cross_dataset_constraint": "OBSERVATIONAL_COHORT_EVIDENCE",
    "statistical_model_comparison": "OBSERVATIONAL_COHORT_EVIDENCE",
    "analytical_derivation": "THEORETICAL_OR_FORMAL_EVIDENCE",
    "field_equation_solution": "THEORETICAL_OR_FORMAL_EVIDENCE",
    "consistency_analysis": "THEORETICAL_OR_FORMAL_EVIDENCE",
    "stability_analysis": "THEORETICAL_OR_FORMAL_EVIDENCE",
    "symmetry_argument": "THEORETICAL_OR_FORMAL_EVIDENCE",
    "limiting_case": "THEORETICAL_OR_FORMAL_EVIDENCE",
    "no_go_result": "THEORETICAL_OR_FORMAL_EVIDENCE",
    "numerical_solution": "THEORETICAL_OR_FORMAL_EVIDENCE",
    "observable_prediction": "THEORETICAL_OR_FORMAL_EVIDENCE",
    "proof": "THEORETICAL_OR_FORMAL_EVIDENCE",
    "theorem": "THEORETICAL_OR_FORMAL_EVIDENCE",
    "lemma": "THEORETICAL_OR_FORMAL_EVIDENCE",
    "counterexample": "THEORETICAL_OR_FORMAL_EVIDENCE",
    "equivalence_result": "THEORETICAL_OR_FORMAL_EVIDENCE",
    "independence_result": "THEORETICAL_OR_FORMAL_EVIDENCE",
    "formally_verified_proof": "THEORETICAL_OR_FORMAL_EVIDENCE",
    "validated_simulation": "COMPUTATIONAL_MODEL_DISCRIMINATION",
    "convergence_analysis": "COMPUTATIONAL_MODEL_DISCRIMINATION",
    "benchmark_comparison": "COMPUTATIONAL_MODEL_DISCRIMINATION",
    "parameter_sensitivity": "COMPUTATIONAL_MODEL_DISCRIMINATION",
    "uncertainty_propagation": "COMPUTATIONAL_MODEL_DISCRIMINATION",
    "controlled_intervention": "CONTROLLED_INTERVENTION_EVIDENCE",
    "randomized_or_controlled_trial": "CONTROLLED_INTERVENTION_EVIDENCE",
    "controlled_experiment": "CONTROLLED_EXPERIMENTAL_VALIDATION",
    "quasi_experiment": "POLICY_CAUSAL_IDENTIFICATION",
    "natural_experiment": "POLICY_CAUSAL_IDENTIFICATION",
    "interrupted_time_series": "POLICY_CAUSAL_IDENTIFICATION",
    "difference_in_differences": "POLICY_CAUSAL_IDENTIFICATION",
    "regression_discontinuity": "POLICY_CAUSAL_IDENTIFICATION",
    "instrumental_variable": "POLICY_CAUSAL_IDENTIFICATION",
    "cross_jurisdiction_comparison": "POLICY_POPULATION_COMPARISON",
    "cross_regional_comparison": "POLICY_POPULATION_COMPARISON",
    "prospective_or_retrospective_cohort": "OBSERVATIONAL_COHORT_EVIDENCE",
    "ecological_association": "ECOLOGICAL_ASSOCIATION",
    "field_observation": "ECOLOGICAL_FIELD_OBSERVATION",
    "environmental_monitoring": "ECOLOGICAL_MONITORING",
    "ecological_monitoring": "ECOLOGICAL_MONITORING",
    "longitudinal_or_time_series_sampling": "ECOLOGICAL_LONGITUDINAL_MONITORING",
    "cross_site_comparison": "ECOLOGICAL_CROSS_SITE_COMPARISON",
    "mic_assay": "IN_VITRO_ANTIMICROBIAL_ACTIVITY",
    "in_vitro_antimicrobial_activity": "IN_VITRO_ANTIMICROBIAL_ACTIVITY",
    "mechanistic_assay": "MECHANISTIC_ASSAY",
    "laboratory_measurement": "LABORATORY_MEASUREMENT",
    "animal_infection_model": "IN_VIVO_PRECLINICAL_VALIDATION",
    "in_vivo_or_system_model": "IN_VIVO_PRECLINICAL_VALIDATION",
    "computational_model_or_simulation": "COMPUTATIONAL_MODEL_DISCRIMINATION",
    "theoretical_framework_or_derivation": "THEORETICAL_OR_FORMAL_EVIDENCE",
    "measurement_system_validation": "SURVEILLANCE_SYSTEM_VALIDATION",
    "sensor_or_detector_validation": "SURVEILLANCE_SYSTEM_VALIDATION",
    "genomic_or_signal_tracking": "SURVEILLANCE_SYSTEM_VALIDATION",
    "spatiotemporal_monitoring": "SURVEILLANCE_SPATIOTEMPORAL_MONITORING",
    "benchmark_or_calibration_study": "SURVEILLANCE_SYSTEM_VALIDATION",
    "sensitivity_specificity_or_uncertainty_assessment": "SURVEILLANCE_SYSTEM_VALIDATION",
    "component_level_direct_evidence": "COMPONENT_LEVEL_DIRECT_EVIDENCE",
    "interaction_or_synergy_test": "INTERACTION_OR_SYNERGY_EVIDENCE",
    "factorial_or_ablation_design": "FACTORIAL_OR_ABLATION_EVIDENCE",
    "integrated_system_evaluation": "INTEGRATED_SYSTEM_EVALUATION",
    "cross_scale_synthesis": "CROSS_SCALE_SYNTHESIS",
    "systematic_review_for_context": "SYSTEMATIC_REVIEW_CONTEXT",
}

# Keep formula-like identifiers (CO2, H2O, pH, 10x), Greek-labelled physics
# quantities, and Chinese scientific terms.  Scientific identity cannot be
# defined by an English-only tokenizer.
_TOKEN_RE = re.compile(r"[A-Za-z\u0370-\u03ff][A-Za-z0-9_+\-./]*|[\u4e00-\u9fff]{2,}")
_STOPWORDS = {
    "about", "across", "after", "also", "and", "are", "as", "at", "be", "but", "by", "can",
    "conditions", "context", "different", "for", "from", "have", "in", "into", "is", "it", "many",
    "may", "of", "on", "or", "other", "such", "than", "that", "the", "their", "this", "through",
    "to", "under", "use", "using", "versus", "vs", "vs.", "whether", "with", "within",
}
_LOW_SIGNAL = {
    "activity", "change", "composition", "effect", "efficiency", "function", "integrity", "molecular",
    "polarity", "process", "rate", "stability", "structure", "transfer", "variable",
}
_RETRIEVAL_OBJECT_GENERIC_TERMS = _LOW_SIGNAL | {
    "algorithm", "algorithms", "application", "applications", "assay", "assays",
    "activation", "activated", "cell", "cells", "immune", "immunity",
    "constraint", "constraints", "data", "disease", "diseases", "gene", "genes",
    "inflammation", "inflammatory", "response", "responses", "system", "systems",
    "implementation", "material", "materials", "measurement", "measurements",
    "mechanism", "mechanisms", "method", "methods", "model", "models",
    "mutation", "mutations", "organ", "organs", "platform", "platforms",
    "population", "populations", "protein", "proteins", "technology",
    "technologies", "technique", "techniques", "therapy", "tissue", "tissues",
    # These describe a broad capability, endpoint, or implementation context.
    # They are meaningful only when paired in a declared, source-bound object
    # phrase; a single occurrence must never establish a paper's identity.
    "accuracy", "control", "controls", "digital", "memory", "storage",
}
_COMPONENT_BRIDGE_MODIFIER_ONLY_PHRASES = {
    "assay",
    "boundary condition",
    "cross scale feasibility",
    "cross scale validation",
    "cross-scale feasibility",
    "cross-scale validation",
    "ethical implication",
    "ethical implications",
    "failure mode",
    "feasibility",
    "framework",
    "heterogeneity",
    "improvement in symptoms",
    "limitation",
    "limitations",
    "mechanism assay",
    "model system",
    "model system platform validation",
    "neurological damage",
    "platform validation",
    "review framework",
    "review framework feasibility limitation roadmap",
    "roadmap",
    "safety",
    "safety failure mode",
    "safety failure mode heterogeneity stability boundary",
    "safety failure mode heterogeneity stability limitation",
    "stability",
    "therapeutic applications",
    "therapeutic intervention",
    "therapeutic interventions",
    "translation",
    "translation model system",
    "translation model system cross scale validation",
    "translation model system cross-scale feasibility validation",
    "translation model system cross-scale validation",
    "translational bridge",
    "disease-related pathway",
    "disease-related pathways",
}
_COMPONENT_BRIDGE_PROTECTED_CONCRETE_PHRASES = {
    # These are phrase-level anchors: their individual tokens are weak, but
    # the phrase is searchable and source-bound when supplied by the typed
    # object-maturity audit.
    "artificial memory",
    "artificial memories",
    "synthetic memory",
    "synthetic memories",
    "engineered memory",
    "engineered memories",
    "false memory",
    "false memories",
    "memory engram",
    "memory engrams",
    "engram cell",
    "engram cells",
    "memory circuit",
    "memory circuits",
    "neural circuit stimulation",
    "hippocampal circuit",
    "hippocampal circuits",
}
_QUERY_METHOD_OR_READOUT_ONLY_PHRASES = {
    # Study-design / platform phrases: useful retrieval support, but not the
    # scientific object identity by themselves.
    "agricultural plot",
    "agricultural plots",
    "benchmark dataset",
    "case control study",
    "case-control study",
    "clinical response",
    "clinical trial",
    "controlled environment chamber",
    "controlled environment chambers",
    "controlled experiment",
    "controlled experiments",
    "controlled study",
    "controlled studies",
    "controlled trial",
    "diagnostic assay",
    "diagnostic assays",
    "external validation",
    "field experiment",
    "field experiments",
    "field trial",
    "field trials",
    "greenhouse experiment",
    "greenhouse experiments",
    "growth chamber",
    "growth chambers",
    "in vitro model",
    "in vitro models",
    "laboratory assay",
    "laboratory assays",
    "life cycle assessment",
    "lifecycle assessment",
    "patient level heterogeneity",
    "patient-level heterogeneity",
    "plot experiment",
    "plot experiments",
    "randomised controlled trial",
    "randomized controlled trial",
    "treatment exposure method",
    "treatment exposure methods",
    # Endpoint/statistic phrases: they may satisfy mechanism/outcome support,
    # never object identity.
    "adverse event",
    "adverse events",
    "biomass yield",
    "crop yield",
    "crop yields",
    "effect size",
    "growth rate",
    "hazard ratio",
    "mortality rate",
    "response rate",
    "survival rate",
}
_QUERY_METHOD_OR_READOUT_ONLY_HEAD_TERMS = {
    "adverse", "agricultural", "benchmark", "case", "clinical", "controlled",
    "diagnostic", "external", "field", "greenhouse", "growth", "laboratory",
    "patient", "plot", "randomised", "randomized", "treatment",
}
_QUERY_METHOD_OR_READOUT_ONLY_TAIL_TERMS = {
    "analysis", "analyses", "assay", "assays", "assessment", "assessments",
    "benchmark", "calibration", "chamber", "chambers", "cohort", "cohorts",
    "dataset", "datasets", "design", "designs", "endpoint", "endpoints",
    "evaluation", "evaluations", "event", "events", "experiment",
    "experiments", "exposure", "exposures", "heterogeneity", "measurement",
    "measurements", "method", "methods", "model", "models", "monitoring",
    "outcome", "outcomes", "platform", "platforms", "plot", "plots",
    "probe", "probes", "rate", "rates", "readout", "readouts", "response",
    "responses", "screen", "screening", "screens", "study", "studies",
    "trial", "trials", "validation", "yield", "yields",
}
_QUERY_READOUT_ONLY_TERMS = {
    "accuracy", "auc", "biomass", "burden", "confidence", "effect", "effects",
    "emission", "emissions", "endpoint", "endpoints", "error", "events",
    "failure", "hazard", "heterogeneity", "leakage", "mortality", "outcome",
    "outcomes", "permanence", "ratio", "rate", "rates", "readout",
    "readouts", "response", "responses", "risk", "sensitivity", "stability",
    "survival", "threshold", "toxicity", "yield", "yields",
}
_COMPONENT_BRIDGE_MODIFIER_ONLY_TERMS = _RETRIEVAL_OBJECT_GENERIC_TERMS | {
    "application", "applications", "artificial", "assay", "boundary", "bridge",
    "cross", "cross-scale", "damage", "ethical", "feasibility", "failure",
    "framework", "heterogeneity", "human", "implication", "implications",
    "intervention", "interventions", "limitation", "limitations",
    "manipulate", "manipulated", "manipulation", "mechanism", "mouse",
    "mice", "neurological", "platform", "review", "roadmap", "safety",
    "scale", "stability", "stimulate", "stimulated", "stimulation",
    "symptom", "symptoms", "therapeutic", "translation", "translational",
    "validation",
    # Broad words may be valid inside a protected concrete phrase, but they
    # are too generic to let a component-bridge SH pass object identity by
    # themselves.
    "brain", "circuit", "circuits", "formation", "memory", "memories",
    "natural", "neural", "pathway", "pathways", "storage",
}

LOW_SIGNAL_STANDALONE_QUERY_TERMS = frozenset({
    "artificial", "natural", "memory", "memories", "neural", "brain",
    "system", "systems", "model", "models", "platform", "platforms",
    "validation", "translation", "cross-scale", "cross", "scale",
    "feasibility", "framework", "roadmap", "therapeutic", "applications",
    "application", "symptoms", "symptom", "damage", "ethical", "safety",
    "failure", "effects", "effect", "quality", "performance",
})

# These strings describe a measurement, generic experimental posture, or a
# statistical reporting convention.  They can be useful after a paper is
# found, but must not occupy one of the scarce object/causal-edge slots in a
# provider discovery query.  This is deliberately discipline-neutral.
_QUERY_TEMPLATE_SUPPORT_PHRASES = frozenset({
    "effect size", "effect sizes", "statistical significance",
    "controlled experiment", "controlled experiments", "controlled study",
    "controlled studies", "theoretical model", "theoretical models",
    "computational simulation", "computational simulations", "data analysis",
    "statistical analysis", "tc measurement",
})
_QUERY_METHOD_SUPPORT_TAIL_TERMS = frozenset({
    "analysis", "analyses", "assay", "assays", "measurement", "measurements",
    "microscopy", "simulation", "simulations", "spectroscopy", "study",
    "studies", "survey", "surveys", "model", "models", "effect", "effects",
    "size", "sizes", "yield", "yields",
})


def is_query_template_support_anchor(value: Any) -> bool:
    """Whether a support anchor is a generic method/readout/template phrase.

    The check is only used when composing broad discovery queries.  It does
    not deny that a method can be strong evidence; it prevents the method
    from making the retrieval query an accidental multi-way intersection.
    """

    normalized = _normalize(value).lower().replace("-", " ")
    if not normalized:
        return True
    if normalized in _QUERY_TEMPLATE_SUPPORT_PHRASES:
        return True
    tokens = [
        token.lower() for token in _TOKEN_RE.findall(normalized)
        if token.lower() not in _STOPWORDS
    ]
    if not tokens:
        return True
    if len(tokens) == 1 and tokens[0] in {
        "measurement", "measurements", "analysis", "analyses", "perturbation",
        "perturbations", "simulation", "simulations", "spectroscopy",
    }:
        return True
    return tokens[-1] in _QUERY_METHOD_SUPPORT_TAIL_TERMS
_EXCLUSION_VARIANT_DICTIONARY = {
    "addiction": {
        "domain_tags": {
            "biomedical", "health", "medicine", "neuro", "neuroscience",
            "psych", "psychology", "psychiatry", "clinical", "life science",
        },
        "variants": [
            "addiction",
            "addictive behavior",
            "addictive behaviour",
            "substance use disorder",
            "drug seeking",
            "compulsive drug seeking",
            "compulsive drug use",
            "reward circuitry",
            "craving",
            "relapse",
        ],
        "provider_not_variants": [
            "addiction",
            "addictive behavior",
            "addictive behaviour",
            "substance use disorder",
            "drug seeking",
            "compulsive drug seeking",
            "compulsive drug use",
            "reward circuitry",
            "craving",
            "relapse",
        ],
    },
    "substance use disorder": {
        "domain_tags": {"biomedical", "health", "medicine", "neuro", "psych", "clinical"},
        "variants": [
            "substance use disorder",
            "addiction",
            "addictive behavior",
            "drug seeking",
            "compulsive drug seeking",
            "compulsive drug use",
            "craving",
            "relapse",
        ],
        "provider_not_variants": [
            "substance use disorder",
            "addiction",
            "drug seeking",
            "compulsive drug seeking",
            "compulsive drug use",
            "craving",
            "relapse",
        ],
    },
    "alzheimer disease": {
        "domain_tags": {
            "biomedical", "health", "medicine", "neuro", "neuroscience",
            "psych", "psychology", "psychiatry", "clinical", "life science",
        },
        "variants": [
            "Alzheimer's disease",
            "Alzheimer disease",
            "Alzheimer’s disease",
            "AD",
            "dementia",
        ],
        # ``AD`` is useful for SH-local fast rejection, but it is too
        # ambiguous for a provider-level NOT clause.
        "provider_not_variants": [
            "Alzheimer's disease",
            "Alzheimer disease",
            "Alzheimer’s disease",
            "dementia",
        ],
    },
    "alzheimer's disease": {
        "alias_of": "alzheimer disease",
    },
    "alzheimers disease": {
        "alias_of": "alzheimer disease",
    },
    "ptsd": {
        "domain_tags": {
            "biomedical", "health", "medicine", "neuro", "neuroscience",
            "psych", "psychology", "psychiatry", "clinical", "life science",
        },
        "variants": [
            "PTSD",
            "posttraumatic stress disorder",
            "post-traumatic stress disorder",
            "post traumatic stress disorder",
        ],
        "provider_not_variants": [
            "PTSD",
            "posttraumatic stress disorder",
            "post-traumatic stress disorder",
            "post traumatic stress disorder",
        ],
    },
    "posttraumatic stress disorder": {
        "alias_of": "ptsd",
    },
    "post-traumatic stress disorder": {
        "alias_of": "ptsd",
    },
}

# These tokens may be valid inside a declared scientific-object phrase, but a
# single occurrence is too weak to prove object identity before full-text
# review.  Keep this as a structural singleton policy rather than a domain
# blacklist; concrete words from the current multi-word object are handled by
# the per-contract protected-positive policy.
_CONTEXT_WEAK_SINGLE_OBJECT_TERMS = {
    "acid-based", "based",
}

OBJECT_SEMANTIC_EQUIVALENCE_POLICY_VERSION = "scientific_object_semantic_equivalence_v1"
_MEASUREMENT_METHOD_OBJECT_MARKERS = (
    "assay", "benchmark", "calibration", "characterization", "characterisation",
    "chromatography", "detector", "imaging", "instrument", "instrumentation",
    "measurement", "microscopy", "monitoring", "platform", "sensor",
    "sequencing", "spectrometry", "spectroscopy", "tomography",
)
_CORPUS_METHOD_PLATFORM_MARKERS = _MEASUREMENT_METHOD_OBJECT_MARKERS + (
    # Discipline-derived natural-science / engineering method and platform
    # anchors.  Derived from the OpenAlex/WoS discipline inventory used by
    # paperseek_core.disciplines while intentionally excluding humanities and
    # social-science framing fields.  These are evidence-form markers, not
    # broad discipline names, so they can admit related auxiliary corpus
    # without turning "medicine" or "chemistry" itself into a method hit.
    "workflow", "pipeline", "protocol", "preparation", "synthesis",
    "fabrication", "processing", "ablation", "deposition", "screening",
    "profiling", "mapping", "visualization", "visualisation", "validation",
    # Life sciences, molecular biology, immunology, microbiology, veterinary.
    "cell culture", "tissue culture", "organoid", "animal model", "mouse model",
    "murine model", "zebrafish model", "in vivo model", "in vitro model",
    "ex vivo", "culture assay", "growth assay", "infection model",
    "challenge study", "vaccination study", "immunoassay", "elisa",
    "western blot", "immunoblot", "flow cytometry", "cell sorting",
    "facS", "immunofluorescence", "confocal microscopy", "cryo-em",
    "cryo electron microscopy", "cryo-et", "cryo electron tomography",
    "cryo-clem", "correlative light and electron microscopy",
    "single-cell sequencing", "single cell sequencing", "rna-seq", "rnaseq",
    "scrna-seq", "transcriptomics", "proteomics", "metabolomics",
    "multiomics", "multi-omics", "genomics", "epigenomics", "qpcr",
    "pcr", "crispr", "knockout", "knockdown", "rna interference",
    "reporter assay", "binding assay", "enzyme assay", "kinetic assay",
    "fermentation", "bioreactor", "microfluidics", "microfluidic platform",
    # Medicine, pharmacology, toxicology, dentistry, health professions.
    "clinical trial", "randomized controlled trial", "randomised controlled trial",
    "controlled trial", "prospective cohort", "retrospective cohort",
    "case-control study", "case control study", "diagnostic test",
    "diagnostic assay", "clinical validation", "external validation",
    "dose response", "dose-response", "pharmacokinetic", "pharmacodynamics",
    "pharmacodynamic", "toxicology assay", "toxicity assay", "safety assay",
    "biomarker assay", "medical imaging", "mri", "ct imaging", "pet imaging",
    "ultrasound imaging", "radiomics", "pathology assay", "histology",
    "histopathology", "rehabilitation trial", "dental assay",
    # Chemistry, chemical engineering, energy, environmental engineering.
    "reactor", "batch reactor", "flow reactor", "continuous reactor",
    "catalysis", "catalytic test", "electrocatalysis", "photocatalysis",
    "electrolysis", "photolysis", "hydrothermal synthesis",
    "solvothermal synthesis", "pyrolysis", "gasification", "combustion test",
    "polymerization", "crystallization", "distillation", "extraction",
    "membrane separation", "adsorption", "desorption", "separation process",
    "process optimization", "design of experiments", "doe", "pilot-scale",
    "pilot scale", "scale-up", "scale up", "life cycle assessment", "lca",
    "techno-economic analysis", "tea", "xrd", "x-ray diffraction",
    "xray diffraction", "xps", "nmr", "ftir", "raman", "uv-vis", "uv vis",
    "mass spectrometry", "lc-ms", "gc-ms", "hplc", "titration",
    "cyclic voltammetry", "electrochemical impedance", "impedance spectroscopy",
    "thermal analysis", "tga", "dsc",
    # Materials science, nanoscience, metallurgy, manufacturing.
    "materials characterization", "mechanical testing", "tensile test",
    "compression test", "fatigue test", "hardness test", "fracture test",
    "sem", "scanning electron microscopy", "tem", "transmission electron microscopy",
    "afm", "atomic force microscopy", "dls", "ellipsometry", "nanoindentation",
    "thin film deposition", "chemical vapor deposition", "cvd",
    "physical vapor deposition", "pvd", "atomic layer deposition", "ald",
    "sputtering", "lithography", "etching", "annealing", "sintering",
    "additive manufacturing", "3d printing", "powder bed fusion",
    "laser sintering", "laser ablation", "electrospinning", "spin coating",
    "coating process", "composite fabrication", "metallurgical processing",
    # Physics, astronomy, optics, quantum science.
    "diffraction", "scattering", "x-ray scattering", "small-angle scattering",
    "neutron scattering", "spectrometer", "interferometry", "ellipsometric",
    "magnetometry", "calorimetry", "optical measurement", "laser spectroscopy",
    "fluorescence microscopy", "super-resolution microscopy",
    "single molecule imaging", "particle detector", "accelerator experiment",
    "plasma experiment", "quantum simulation", "quantum device",
    "telescope observation", "astronomical observation",
    # Earth, planetary, agricultural, environmental sciences.
    "field sampling", "field experiment", "field trial", "greenhouse experiment",
    "growth chamber", "mesocosm", "microcosm", "plot experiment",
    "soil analysis", "water sampling", "air sampling", "sediment core",
    "isotope analysis", "geochemical analysis", "geophysical survey",
    "seismic survey", "remote sensing", "satellite observation",
    "satellite imagery", "gis", "lidar", "radar", "weather station",
    "climate model", "earth system model", "oceanographic survey",
    "watershed monitoring", "wastewater monitoring", "biodiversity survey",
    "ecological monitoring", "species distribution model",
    # Engineering, robotics, instrumentation, control, transport.
    "prototype", "testbed", "bench-scale", "bench scale", "lab-scale",
    "lab scale", "finite element", "finite element analysis", "fea",
    "computational fluid dynamics", "cfd", "control system", "robotic platform",
    "automation platform", "sensor network", "wireless sensor", "structural test",
    "wind tunnel", "hydraulic test", "transport model", "manufacturing process",
    "process control", "quality control", "release assay",
    # Computer science, mathematics, statistics as scientific method platforms.
    "algorithm", "computational model", "simulation", "numerical simulation",
    "mathematical model", "statistical model", "machine learning",
    "deep learning", "neural network", "classifier", "segmentation",
    "computer vision", "image analysis", "signal processing", "optimization",
    "inference", "bayesian model", "monte carlo", "ablation study",
    "software pipeline", "database benchmark", "benchmark dataset",
    "cross-validation", "cross validation", "calibration curve",
)
_CORPUS_MATERIAL_SYSTEM_POPULATION_MARKERS = (
    "material", "materials", "polymer", "polymers", "compound", "compounds",
    "catalyst", "catalysts", "membrane", "membranes", "electrode", "electrodes",
    "nanoparticle", "nanoparticles", "quantum dot", "quantum dots", "cell",
    "cells", "tissue", "organism", "organisms", "cohort", "population",
    "populations", "sample", "samples", "ecosystem", "waste stream",
    "product", "products", "platform", "system", "systems",
)
_CORPUS_MEASURABLE_READOUT_MARKERS = (
    "resolution", "precision", "accuracy", "error rate", "sensitivity",
    "specificity", "auc", "rmse", "signal-to-noise", "signal to noise",
    "artifact", "artefact", "yield", "potency", "toxicity", "survival",
    "expression", "concentration", "mass", "flux", "emission", "carbon footprint",
    "lifecycle", "life cycle", "leakage", "purity", "sterility", "calibration",
    "reproducibility", "repeatability", "threshold", "kinetics", "rate",
)
_OBJECT_ANCHOR_RELATIONAL_TERMS = {
    "accelerate", "accelerated", "accelerating", "advancement", "advancements",
    "application", "applications", "development", "effectiveness", "efficacy",
    "generate", "generates", "generating", "generation", "impact", "induce",
    "induces", "inducing", "induction", "latest", "role",
}
_OBJECT_ALIAS_OPERATION_PREFIX_RE = re.compile(
    r"^(?:administration|application|delivery|deployment|exposure|implantation|"
    r"intervention|stimulation|supplementation|treatment|use|vaccination)\s+"
    r"(?:of|with|using)\s+",
    re.IGNORECASE,
)
_EXPLANATORY_ALIAS_PATTERNS = (
    re.compile(
        r"(?P<canonical>[^()\n,;:.!?]{1,120}?)\s*"
        r"\(\s*(?P<alias>[^()\n,;:.!?]{1,80}?)\s+for\s+short\s*\)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?P<canonical>[^()\n,;:.!?]{1,120}?)\s*"
        r"\(\s*abbreviated\s+as\s+(?P<alias>[^()\n,;:.!?]{1,80}?)\s*\)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?P<canonical>[^()\n,;:.!?]{1,120}?)\s*,\s*"
        r"hereafter\s+referred\s+to\s+as\s+"
        r"(?P<alias>[^()\n,;:.!?]{1,80})",
        re.IGNORECASE,
    ),
)
_EXPLANATORY_ALIAS_DANGLING_SUFFIX_RE = re.compile(
    r"(?:\s+|^)(?:for\s+short)(?=\s|$)",
    re.IGNORECASE,
)
_EXPLANATORY_ALIAS_LEADING_MARKER_RE = re.compile(
    r"^\s*(?:hereafter\s+referred\s+to\s+as|abbreviated\s+as)\s+",
    re.IGNORECASE,
)
# These tokens can appear in a legitimate scientific variable, but cannot
# identify an axis *by themselves*.  The direct-core gate below requires a
# phrase or a non-generic, axis-specific token set in addition to the normal
# project/object boundary.  This prevents a contract such as
# ``prebiotic -> organic molecule formation -> life`` from treating the
# background words ``prebiotic``, ``formation``, or ``life`` as evidence for
# a missing focal variable.
_CORE_AXIS_GENERIC_TERMS = _STOPWORDS | _LOW_SIGNAL | {
    "absence", "activity", "activities", "background", "cell", "cellular", "chemical", "chemistry",
    "complex", "condition", "conditions", "context", "contexts", "effect", "effects", "emergence",
    "formation", "function", "functional", "general", "interaction", "interactions", "life", "living",
    "molecule", "molecules", "necessity", "normal", "normally", "organic", "outcome", "outcomes",
    "presence", "process", "processes", "reaction", "reactions", "requirement", "result", "results",
    "specific", "system", "systems",
}
_FOCAL_VARIABLE_OPERATION_PREFIX_RE = re.compile(
    r"^(?:controlled\s+(?:variation|change)\s+of|parameter\s+sweep\s+of|"
    r"perturbation\s+of|manipulation\s+of|replacement\s+of|presence\s+of|absence\s+of)\s+",
    re.IGNORECASE,
)
_FOCAL_VARIABLE_CONTEXT_SPLIT_RE = re.compile(
    r"\s+(?:in|under|within|across|during|among|for|at)\s+",
    re.IGNORECASE,
)
# Only grammatical/research glue is globally weak.  Every scientific word
# (water, solvent, digital, neural, signal, algorithm, simulation, data, ...)
# can be a primary project entity when the current project declares it so.
# Relevance comes from co-occurrence with project-local entity/relation anchors,
# not a global blacklist of whole scientific domains.
_PROJECT_ANCHOR_GLUE_TERMS = _STOPWORDS | {
    "analysis", "approach", "evidence", "framework", "method", "methods", "research",
    "result", "results", "science", "study", "studies", "work",
}
_GENERALIZED_OBJECT_DECLARATION_TERMS = {
    "aim", "aims", "assess", "assesses", "assessing", "assessment",
    "compare", "compares", "comparing", "determine", "determines", "determining",
    "effect", "effects", "effectiveness", "efficacy", "evaluate", "evaluates",
    "evaluating", "evaluation", "examine", "examines", "examining",
    "explore", "explores", "exploring", "feasibility", "goal", "impact",
    "investigate", "investigates", "investigating", "objective", "objectives",
    "outcome", "outcomes", "performance", "question", "role", "safety",
    "test", "tests", "testing", "whether",
}
_GENERALIZED_OBJECT_DECLARATION_PREFIX_RE = re.compile(
    r"^(?:the\s+)?(?:aim|goal|objective|purpose)\s+(?:is|was|of\s+this\s+"
    r"(?:study|work)\s+is)?\b|^(?:to\s+)?(?:assess|compare|determine|evaluate|"
    r"examine|explore|investigate|test)\b|^whether\b",
    flags=re.IGNORECASE,
)
# These words are valid *measurement* or *experimental-operation* signals,
# but do not by themselves establish that a record belongs to a particular
# sub-hypothesis.  Without this distinction a generic "controlled temperature
# study" can inherit a relevance point simply because the target contract
# happens to include a control or stability word.  They remain visible in the
# audit record; they are just not sufficient to cross the L1 relevance
# boundary on their own.
_L1_GENERIC_RELEVANCE_TERMS = {
    "temperature", "pressure", "concentration", "dose", "loading", "flow rate", "humidity", "ph",
    "acidity", "salinity", "composition", "ratio", "water activity", "heat", "energy source", "voltage",
    "current", "time", "cycle", "treatment", "controlled", "control", "perturbation", "unchanged",
    "rate", "capacity", "efficiency", "yield", "selectivity", "stability", "retention", "degradation",
    "conversion", "uptake", "removal", "storage", "sequestration", "emission", "performance",
    "energy consumption", "activation energy",
}
_THEORY_MARKERS = (
    "theory", "theoretical", "framework", "conceptual", "feasibility", "model", "modelling", "modeling",
    "simulation", "review", "perspective", "hypothesis", "principle", "thermodynamic", "prediction",
)
_EXPERIMENT_MARKERS = (
    "experiment", "experimental", "measured", "measurement", "observed", "observation", "assay", "in vitro",
    "laboratory", "synthesis", "kinetic", "spectroscopy", "microscopy", "titration", "culture", "replication",
    "control", "perturbation", "temperature dependence", "pressure dependence",
)
_FOUNDATION_OBSERVATION_MARKERS = (
    "experiment", "experimental", "measured", "measurement", "observed", "observation",
    "assay", "spectroscopy", "microscopy", "kinetic", "simulation", "model", "theory",
    "theoretical", "thermodynamic", "calculated", "characterized", "investigated",
    "self-assembly", "self assembly", "solvation", "phase behavior", "phase separation",
)
_REVIEW_MARKERS = (
    "review", "survey", "systematic review", "meta-analysis", "meta analysis",
    "perspective", "overview", "tutorial", "roadmap", "state of the art",
)

# Policy, economic, tax, market, and deployment papers can be useful project
# context, but they are not mechanistic/technical evidence for most SH-local
# causal claims.  Keep this as a generic evidence-role policy: these markers
# are admitted into the SH-local pool only when the current sub-hypothesis
# explicitly declares such a policy/economic/deployment axis as its object,
# input/comparison, mechanism, or endpoint.
_POLICY_ECONOMIC_STRONG_CONTEXT_MARKERS = (
    "tax credit", "tax credits", "tax incentive", "tax incentives",
    "tax policy", "taxation policy", "carbon pricing", "emissions trading",
    "cap-and-trade", "cap and trade", "market mechanism", "market mechanisms",
    "carbon market", "carbon markets", "policy analysis", "policy assessment",
    "policy framework", "policy mix", "regulatory framework", "regulatory policy",
    "legal framework", "public policy", "government policy", "governance framework",
    "economic assessment", "economic analysis", "economic evaluation",
    "economic feasibility", "techno-economic", "techno economic", "technoeconomic",
    "cost-benefit", "cost benefit", "cost-effectiveness", "cost effectiveness",
    "cost analysis", "cost model", "cost modelling", "cost modeling",
    "levelized cost", "levelised cost", "business model", "business models",
    "market adoption", "commercial deployment", "deployment policy",
    "deployment pathway", "deployment pathways", "financial incentive",
    "financial incentives", "financing mechanism", "project finance",
    "investment decision", "investment decisions", "permitting", "liability",
    "public acceptance", "social acceptance", "stakeholder engagement",
)
_POLICY_ECONOMIC_WEAK_CONTEXT_MARKERS = (
    "policy", "policies", "regulation", "regulations", "regulatory",
    "governance", "legal", "liability", "tax", "taxes", "taxation",
    "subsidy", "subsidies", "incentive", "incentives", "market", "markets",
    "pricing", "economic", "economics", "cost", "costs", "investment",
    "investments", "finance", "financing", "financial", "business",
    "commercial", "commercialization", "commercialisation", "deployment",
    "adoption", "stakeholder", "stakeholders", "acceptance",
)
_POLICY_ECONOMIC_SH_AXIS_MARKERS = (
    _POLICY_ECONOMIC_STRONG_CONTEXT_MARKERS
    + _POLICY_ECONOMIC_WEAK_CONTEXT_MARKERS
    + (
        "levelized cost of energy", "levelised cost of energy",
        "levelized cost of storage", "levelised cost of storage",
        "abatement cost", "marginal abatement cost", "net present value",
        "payback period", "return on investment", "capital expenditure",
        "capex", "operating expenditure", "opex", "deployment rate",
        "adoption rate", "market share",
    )
)

# Predictive generalization is a validation design, not an intervention
# design. These markers describe how a model is evaluated across a declared
# population or deployment boundary. They are intentionally methodological:
# the scientific object and the boundary itself still come from the current
# sub-hypothesis contract.
_PREDICTIVE_MODEL_MARKERS = (
    "artificial intelligence", "machine learning", "deep learning", "statistical model",
    "prediction model", "predictive model", "risk model", "classifier", "algorithm",
    "clinical model", "prognostic model", "diagnostic model",
)
_PREDICTIVE_GENERALIZATION_MARKERS = (
    "generalization", "generalisation", "generalizability", "generalisability",
    "external validation", "temporal validation", "geographic validation", "geographical validation",
    "multi-site", "multisite", "multi-center", "multicenter", "cross-site", "cross site",
    "subgroup performance", "performance heterogeneity", "transportability", "transportable",
    "domain shift", "distribution shift", "dataset shift", "fairness", "algorithmic bias",
    "calibration", "discrimination", "clinical settings", "deployment setting",
)
_PREDICTIVE_VALIDATION_MARKERS = _PREDICTIVE_GENERALIZATION_MARKERS + (
    "external cohort", "independent cohort", "held-out cohort", "validation cohort",
    "out-of-sample", "out of sample", "cross-validation", "cross validation",
    "area under the curve", "auc", "c-statistic", "sensitivity", "specificity",
    "calibration slope", "calibration-in-the-large", "brier score", "equalized odds",
    "demographic parity", "subgroup analysis", "stratified performance",
)
_ADVERSE_OR_REVERSAL_EVIDENCE_MARKERS = (
    "negative effect", "adverse effect", "adverse event", "unintended consequence",
    "rebound effect", "substitution effect", "substitution burden", "burden shifting",
    "trade-off", "tradeoff", "life cycle burden", "lifecycle burden",
    "increased emissions", "higher carbon footprint", "resource competition",
    "failure mode", "implementation failure", "policy failure", "robustness failure",
    "distribution shift", "out-of-distribution failure", "fairness degradation",
    "performance regression", "off-target effect", "toxicity", "nonresponse",
    "treatment resistance", "null effect", "no significant effect", "reduced effectiveness",
    "worse outcome",
)
_ADVERSE_OR_REVERSAL_ROLE_MARKERS = (
    "adverse", "reversal", "opposing", "tradeoff", "trade-off", "rebound",
    "burden", "negative_evidence", "adverse_or_reversal",
    "adverse_or_reversal_evidence",
)
_PREDICTIVE_MODERATOR_GROUPS: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = (
    (("ancestry", "ancestral", "ethnicity", "ethnic", "race", "racial"),
     ("ancestry", "ancestral", "ethnicity", "ethnic", "race", "racial", "population group")),
    (("sex", "gender"), ("sex", "gender", "female", "male", "women", "men")),
    (("age", "older", "younger", "pediatric", "geriatric"),
     ("age", "age group", "older adults", "younger adults", "pediatric", "geriatric")),
    (("comorbidity", "comorbid", "multimorbidity"),
     ("comorbidity", "comorbid", "multimorbidity", "disease subgroup")),
    (("clinical setting", "clinical settings", "hospital", "site", "sites", "institution", "geographic"),
     ("clinical setting", "hospital", "site", "institution", "external cohort", "multi-site", "multicenter", "geographic")),
)

# These are intentionally evidence-language families rather than a catalogue
# of one scientific discipline.  They make a temperature/pressure/dose style
# manipulation visible even when an abstract does not use the artificial words
# "input", "method", or "output".  Domain-specific terms still come from the
# persisted sub-hypothesis contract and remain the hard relevance boundary.
_SEMANTIC_AXIS_LEXICON: dict[str, tuple[str, ...]] = {
    "input": (
        "temperature", "pressure", "partial pressure", "concentration", "dose", "loading", "flow rate",
        "humidity", "ph", "acidity", "salinity", "composition", "ratio", "water activity", "solvent",
        "sorbent", "catalyst", "material", "heat", "energy source", "voltage", "current", "time",
        "cycle", "treatment", "perturb", "varied", "controlled", "increased", "decreased", "changed",
    ),
    "method": (
        "experiment", "experimental", "measured", "measurement", "observed", "monitor", "quantified",
        "determined", "analyzed", "assessed", "characterized", "tested", "reactor", "assay", "spectroscopy",
        "microscopy", "calorimetry", "gravimetric", "isothermal", "kinetic", "simulation", "model",
        "field trial", "field experiment", "long-term", "long term", "control group", "comparison",
    ),
    "outcome": (
        "rate", "capacity", "efficiency", "yield", "selectivity", "stability", "retention", "degradation",
        "conversion", "uptake", "removal", "storage", "sequestration", "emission", "concentration",
        "fidelity", "error rate", "activity", "performance", "energy consumption", "activation energy",
        "observed", "increased", "decreased", "improved", "reduced", "remained",
    ),
    "mediator": (
        "mechanism", "pathway", "hydrogen bond", "ion pair", "oxidation", "degradation", "capacity decay",
        "surface", "interface", "phase", "conformation", "transport", "diffusion", "proton transfer",
        "reaction intermediate", "adsorption", "desorption", "membrane", "microstructure", "kinetics",
    ),
}

# Deterministic readout-language expansions for source-bound mechanism and
# outcome gates.  These are deliberately evidence/readout families rather than
# topic-specific patches: an expansion is only activated when the current
# sub-hypothesis already declares a matching mechanism/outcome concept.
_MECHANISM_OUTCOME_SYNONYM_GROUPS: tuple[dict[str, Any], ...] = (
    {
        "id": "stability_degradation_readouts",
        "axes": ("mechanism", "outcome"),
        "triggers": (
            "stability", "stable", "instability", "degradation", "degrade", "decay",
            "storage", "temperature", "thermal", "shelf life", "half-life", "retention",
        ),
        "expansions": (
            "thermal stability", "accelerated stability", "degradation rate",
            "decay rate", "half life", "retention", "activity retention",
            "potency retention", "storage stability", "freeze thaw stability",
        ),
    },
    {
        "id": "catalysis_activity_readouts",
        "axes": ("mechanism", "outcome"),
        "triggers": (
            "catalyst", "catalytic", "catalysis", "reaction", "activity",
            "conversion", "selectivity", "yield", "turnover", "kinetic", "kinetics",
        ),
        "expansions": (
            "catalytic activity", "turnover frequency", "turnover number",
            "reaction rate", "conversion", "selectivity", "yield",
            "activation energy", "rate constant",
        ),
    },
    {
        "id": "transport_conductivity_readouts",
        "axes": ("mechanism", "outcome"),
        "triggers": (
            "transport", "diffusion", "conductivity", "conduction", "mobility",
            "charge", "electron", "ion", "ionic", "current", "voltage", "impedance",
        ),
        "expansions": (
            "ionic conductivity", "electrical conductivity", "charge transport",
            "electron transport", "ion transport", "diffusion coefficient",
            "mobility", "impedance", "current density",
        ),
    },
    {
        "id": "mechanical_property_readouts",
        "axes": ("outcome",),
        "triggers": (
            "mechanical", "strength", "modulus", "fracture", "toughness",
            "strain", "stress", "elastic", "stiffness", "hardness",
        ),
        "expansions": (
            "tensile strength", "compressive strength", "young modulus",
            "elastic modulus", "fracture toughness", "strain", "stress",
            "hardness", "stiffness",
        ),
    },
    {
        "id": "immune_response_readouts",
        "axes": ("mechanism", "outcome"),
        "triggers": (
            "immune", "immunity", "immunogenicity", "antigen", "antigen-specific",
            "t-cell", "t cell", "b-cell", "b cell", "antibody", "humoral", "cellular",
        ),
        "expansions": (
            "immunogenicity", "humoral immune response", "cellular immune response",
            "neutralizing antibody", "binding antibody", "antibody titer",
            "seroconversion", "cd4 t cell", "cd8 t cell", "t cell response",
            "b cell response", "elispot", "interferon gamma",
        ),
    },
    {
        "id": "expression_regulation_readouts",
        "axes": ("mechanism", "outcome"),
        "triggers": (
            "expression", "gene", "protein", "transcription", "translation",
            "regulation", "pathway", "signaling", "signalling", "transcript",
        ),
        "expansions": (
            "gene expression", "protein expression", "transcript abundance",
            "mrna expression", "translation", "reporter assay",
            "western blot", "pathway activation", "signaling activity",
        ),
    },
    {
        "id": "binding_interaction_readouts",
        "axes": ("mechanism",),
        "triggers": (
            "binding", "interaction", "affinity", "complex", "receptor",
            "ligand", "adsorption", "desorption", "interface",
        ),
        "expansions": (
            "binding affinity", "dissociation constant", "association rate",
            "interaction strength", "receptor binding", "ligand binding",
            "adsorption capacity", "surface coverage",
        ),
    },
    {
        "id": "detection_monitoring_readouts",
        "axes": ("mechanism", "outcome"),
        "triggers": (
            "detection", "detect", "sensor", "monitoring", "surveillance",
            "tracking", "classification", "diagnostic", "screening", "measurement system",
        ),
        "expansions": (
            "sensitivity", "specificity", "limit of detection", "false positive",
            "false negative", "calibration", "precision", "recall",
            "receiver operating characteristic", "auc",
        ),
    },
    {
        "id": "growth_yield_productivity_readouts",
        "axes": ("outcome",),
        "triggers": (
            "growth", "yield", "biomass", "productivity", "crop", "plant",
            "agriculture", "livestock", "fermentation",
        ),
        "expansions": (
            "growth rate", "biomass", "productivity", "crop yield",
            "survival", "viability", "fermentation yield",
        ),
    },
    {
        "id": "uptake_removal_capacity_readouts",
        "axes": ("mechanism", "outcome"),
        "triggers": (
            "uptake", "removal", "adsorption", "absorption", "sequestration",
            "capture", "capacity", "loading", "sorption",
        ),
        "expansions": (
            "uptake capacity", "adsorption capacity", "removal efficiency",
            "capture capacity", "loading capacity", "sorption capacity",
            "sequestration rate",
        ),
    },
    {
        "id": "model_performance_readouts",
        "axes": ("outcome",),
        "triggers": (
            "model", "prediction", "predictive", "generalization", "validation",
            "classifier", "algorithm", "simulation", "benchmark",
        ),
        "expansions": (
            "external validation", "held-out validation", "cross validation",
            "calibration", "discrimination", "generalization performance",
            "benchmark performance", "prediction error",
        ),
    },
)
_LAB_MARKERS = (
    "laboratory", "lab-scale", "bench-scale", "bench scale", "in vitro", "reactor", "assay", "controlled experiment",
    "isothermal", "titration", "spectroscopy", "calorimetry", "thermogravimetric", "randomized", "perturbation",
)
_FIELD_EXPERIMENT_MARKERS = (
    "field experiment", "field trial", "field demonstration", "demonstration project", "pilot project",
    "pilot-scale", "pilot scale", "injection test", "injection site", "manipulation", "plot experiment", "mesocosm",
)
_COMMERCIAL_OPERATION_MARKERS = (
    "commercial-scale", "commercial scale", "full-scale", "full scale", "industrial-scale", "industrial scale",
    "commercial operation", "operational project", "operating facility", "plant operation", "deployment project",
)
_OBSERVATION_MARKERS = (
    "observational", "monitoring", "monitored", "survey", "cohort", "long-term", "long term", "time series",
    "eddy covariance", "remote sensing", "field observation", "case study", "field monitoring", "operational monitoring",
)
_HUMAN_OBSERVATIONAL_MARKERS = (
    "human", "humans", "patient", "patients", "participant", "participants", "healthy control",
    "healthy controls", "case-control", "case control", "cross-sectional", "cross sectional",
    "clinical cohort", "clinical sample", "population-based", "population based",
)
_MULTIOMICS_MARKERS = (
    "multiomics", "multi-omics", "multi omics", "metabolomics", "metagenomics", "proteomics",
    "transcriptomics", "genomics", "epigenomics", "lipidomics", "integrated omics", "omics integration",
)
_LONGITUDINAL_OR_NATURAL_EXPERIMENT_MARKERS = (
    "longitudinal", "prospective", "retrospective cohort", "follow-up", "follow up", "time series",
    "natural experiment", "quasi-experiment", "quasi experiment", "instrumental variable",
    "difference-in-differences", "interrupted time series", "mendelian randomization",
)
_HUMAN_INTERVENTION_MARKERS = (
    "randomized", "randomised", "clinical trial", "controlled trial", "placebo", "double-blind",
    "double blind", "treatment arm", "intervention arm", "assigned to",
)
_ANIMAL_OR_CELLULAR_MARKERS = (
    "animal model", "mouse model", "mice", "rat model", "rats", "zebrafish", "drosophila",
    "cell culture", "cellular", "cell line", "organoid", "ex vivo", "in vivo", "knockout",
    "knockdown", "overexpression", "gene editing", "crispr",
)
_MECHANISM_DISCOVERY_MARKERS = (
    "mechanism", "mechanistic", "pathway", "mediator", "mediation", "crosstalk", "network",
    "cross-modal", "cross modal", "integrated analysis", "systems-level", "systems level",
)
_MODELING_MARKERS = (
    "simulation", "simulated", "computational", "numerical model", "mathematical model", "modeling", "modelling",
    "density functional", "monte carlo", "finite element",
)
# Complete method expressions have precedence over isolated role words.  The
# lists describe research designs rather than disciplines, so they work for a
# molecular simulation, a climate solver, a lattice calculation, a digital
# experiment, microscopy, spectroscopy, field instrumentation, and biomedical
# assays without assuming a particular project topic.
_STRONG_COMPUTATIONAL_METHOD_MARKERS = (
    "nonequilibrium molecular dynamics", "non-equilibrium molecular dynamics", "molecular dynamics simulation",
    "density functional theory", "ab initio calculation", "first-principles calculation",
    "monte carlo simulation", "finite element simulation", "finite volume simulation",
    "numerical simulation", "computational fluid dynamics", "reaction network simulation",
    "agent-based simulation", "discrete-event simulation", "parameter sweep", "feature ablation",
)
_STRONG_EXPERIMENTAL_OR_INSTRUMENTATION_MARKERS = (
    "operando 4d-stem", "operando microscopy", "operando spectroscopy", "in situ microscopy",
    "in-situ microscopy", "in situ spectroscopy", "in-situ spectroscopy", "electron microscopy",
    "scanning probe microscopy", "atomic force microscopy", "transmission electron microscopy",
    "electrode circuit", "experimental apparatus", "experimental setup", "controlled trial",
    "randomized trial", "bench-scale experiment", "laboratory experiment", "field experiment",
)
_WEAK_GENRE_SIGNALS = ("model", "observed", "observation", "measured", "measurement")
_NUMERIC_RE = re.compile(
    r"(?:\b\d+(?:\.\d+)?\b\s*(?:%|°?\s*c\b|k\b|pa\b|kpa\b|mpa\b|bar\b|atm\b|mol\b|mmol\b|g\b|kg\b|tonnes?\b|tons?\b|mt\b|kt\b|m3\b|km\b|h\b|min\b|day\b|year\b|cycles?\b|j\b|ev\b|ppm\b)|\b\d+(?:\.\d+)?\s*(?:to|-)\s*\d+(?:\.\d+)?\b|\b(?:p\s*[<=>]|r\s*[=]|n\s*[=]))",
    re.IGNORECASE,
)
L1_MATURITY_ACCEPTANCE_THRESHOLD = 6


def classify_research_design(
    paper: dict[str, Any],
    *,
    is_review: bool = False,
    genre: str = "",
) -> dict[str, Any]:
    """Classify study design independently of its causal responsibility."""
    text = _normalize(" ".join(_paper_text_sections(paper).values())).lower()
    publication_types = " ".join(
        str(item or "")
        for item in (paper.get("publication_types") or paper.get("publicationTypes") or [])
    ).lower()
    metadata_text = _normalize(f"{text} {publication_types}").lower()
    human_hits = _hits(metadata_text, list(_HUMAN_OBSERVATIONAL_MARKERS))
    multiomics_hits = _hits(metadata_text, list(_MULTIOMICS_MARKERS))
    longitudinal_hits = _hits(metadata_text, list(_LONGITUDINAL_OR_NATURAL_EXPERIMENT_MARKERS))
    intervention_hits = _hits(metadata_text, list(_HUMAN_INTERVENTION_MARKERS))
    animal_or_cellular_hits = _hits(metadata_text, list(_ANIMAL_OR_CELLULAR_MARKERS))
    experimental_hits = _hits(
        metadata_text,
        list(_EXPERIMENT_MARKERS) + list(_STRONG_EXPERIMENTAL_OR_INSTRUMENTATION_MARKERS),
    )

    if is_review:
        design = "evidence_synthesis"
    # Study-design precedence matters.  A randomized multi-omics trial is an
    # intervention, and a longitudinal multi-omics cohort carries a stronger
    # causal-identification responsibility than a cross-sectional profile.
    # Do not let the presence of omics measurements silently downgrade either
    # design to the observational-human-multiomics category.
    elif human_hits and intervention_hits:
        design = "interventional_human"
    elif animal_or_cellular_hits and experimental_hits:
        design = "experimental_animal_or_cellular"
    elif longitudinal_hits:
        design = "longitudinal_or_natural_experiment"
    elif human_hits and multiomics_hits:
        design = "observational_human_multiomics"
    elif genre in {
        "controlled_experiment",
        "field_demonstration_project",
        "full_scale_commercial_operation",
        "experimental_unspecified",
    }:
        design = "experimental_controlled_system"
    elif multiomics_hits:
        design = "observational_multiomics"
    elif human_hits:
        design = "observational_human"
    elif genre in {"theoretical_framework", "computational_or_mechanistic_model"}:
        design = "theoretical_or_formal_model"
    else:
        design = "unclassified"

    return {
        "design": design,
        "human_subjects": bool(human_hits),
        "multiomics": bool(multiomics_hits),
        "interventional": bool(intervention_hits),
        "longitudinal_or_natural": bool(longitudinal_hits),
        "animal_or_cellular": bool(animal_or_cellular_hits),
        "signals": {
            "human_observational": human_hits,
            "multiomics": multiomics_hits,
            "longitudinal_or_natural": longitudinal_hits,
            "human_intervention": intervention_hits,
            "animal_or_cellular": animal_or_cellular_hits,
        },
    }


def classify_causal_role(
    paper: dict[str, Any],
    *,
    paper_genre: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """State the strongest causal responsibility justified by the design.

    This deliberately does not turn a high-quality observational study into a
    causal validation.  It can nevertheless retain that study as a direct,
    high-value mechanism-discovery or association record.
    """
    genre = dict(paper_genre or {})
    design_assessment = genre.get("research_design_assessment")
    if not isinstance(design_assessment, dict):
        design_assessment = classify_research_design(
            paper,
            is_review=bool(genre.get("is_review")),
            genre=str(genre.get("genre") or ""),
        )
    design = str(genre.get("research_design") or design_assessment.get("design") or "unclassified")
    text = _normalize(" ".join(_paper_text_sections(paper).values())).lower()
    mechanism_hits = _hits(text, list(_MECHANISM_DISCOVERY_MARKERS))
    if design in {"evidence_synthesis", "theoretical_or_formal_model"}:
        role = "background_or_framework"
    elif design in {
        "interventional_human",
        "experimental_animal_or_cellular",
        "experimental_controlled_system",
    }:
        role = "causal_validation"
    elif design == "longitudinal_or_natural_experiment":
        role = "causal_identification"
    elif design in {"observational_human_multiomics", "observational_multiomics"}:
        role = "mechanism_discovery" if mechanism_hits or design_assessment.get("multiomics") else "association"
    elif design == "observational_human":
        role = "mechanism_discovery" if mechanism_hits else "association"
    else:
        role = "unclassified"

    if role == "causal_validation":
        strength = "high_for_perturbation_or_controlled_model_validation"
        validation_status = "supported_by_interventional_or_model_perturbation"
    elif role == "causal_identification":
        strength = "high_for_natural_or_longitudinal_causal_identification"
        validation_status = "identified_by_natural_or_longitudinal_design"
    elif design == "observational_human_multiomics":
        strength = "high_for_human_association_and_cross_modal_triangulation"
        validation_status = "insufficient_without_perturbation_or_stronger_causal_design"
    elif role == "mechanism_discovery":
        strength = "moderate_for_mechanism_discovery"
        validation_status = "insufficient_without_perturbation_or_stronger_causal_design"
    elif role == "association":
        strength = "moderate_for_association"
        validation_status = "insufficient_without_perturbation_or_stronger_causal_design"
    elif role == "background_or_framework":
        strength = "contextual_not_direct_causal_validation"
        validation_status = "not_applicable"
    else:
        strength = "unclassified"
        validation_status = "unresolved"

    supported_roles = [role] if role != "unclassified" else []
    if role == "causal_validation":
        supported_roles.extend(["mechanism_discovery", "association"])
    elif role == "causal_identification":
        supported_roles.extend(["mechanism_discovery", "association"])
    elif role == "mechanism_discovery":
        supported_roles.append("association")
    return {
        "causal_role": role,
        "supported_causal_roles": supported_roles,
        "evidence_strength": strength,
        "causal_validation_status": validation_status,
        "mechanism_signals": mechanism_hits,
        "research_design": design,
    }


def classify_paper_evidence_genre(
    paper: dict[str, Any],
    *,
    semantic_contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Classify a paper's evidence genre and expose auditable semantic spans.

    The classifier is deliberately conservative: a review or market overview
    can be useful background, but never becomes direct theory/experimental
    evidence merely because it mentions a result.  The returned object is
    persisted with every PaperGraph record and can also classify older records
    lazily during a TanXi audit.
    """
    text_sections = _paper_text_sections(paper)
    text = _normalize(" ".join(text_sections.values())).lower()
    publication_types = " ".join(str(item or "") for item in (paper.get("publication_types") or paper.get("publicationTypes") or []))
    metadata_text = _normalize(f"{text} {publication_types}").lower()
    title_text = _normalize(paper.get("title") or "").lower()
    publication_type_text = _normalize(publication_types).lower()
    # Self-identification as a review is authoritative only in the title,
    # abstract, or provider publication type.  Searching the complete PDF
    # caused primary articles to become reviews when their introduction or
    # reference list merely contained a sentence such as "this paper
    # reviews...".  Full text remains available to every other genre signal.
    review_payload = (
        paper.get("papergraph_input")
        if isinstance(paper.get("papergraph_input"), dict)
        else {}
    )
    review_scope = _normalize(
        " ".join(
            str(value or "")
            for value in (
                paper.get("title") or review_payload.get("title"),
                paper.get("abstract") or review_payload.get("abstract"),
                publication_types,
            )
        )
    ).lower()
    explicit_review_statement = bool(re.search(
        r"\b(?:this\s+(?:article|paper|work|study)\s+)?(?:reviews?|surveys?|provides?\s+an?\s+overview)\b",
        review_scope,
    ))
    is_review = bool(
        any(marker in title_text or marker in publication_type_text for marker in _REVIEW_MARKERS)
        or explicit_review_statement
    )
    theory_hits = _hits(metadata_text, list(_THEORY_MARKERS))
    model_hits = _hits(metadata_text, list(_MODELING_MARKERS))
    experiment_hits = _hits(metadata_text, list(_EXPERIMENT_MARKERS))
    strong_theory_hits = [hit for hit in theory_hits if hit not in _WEAK_GENRE_SIGNALS]
    strong_experiment_signal_hits = [hit for hit in experiment_hits if hit not in _WEAK_GENRE_SIGNALS]
    lab_hits = _hits(metadata_text, list(_LAB_MARKERS))
    field_experiment_hits = _hits(metadata_text, list(_FIELD_EXPERIMENT_MARKERS))
    commercial_operation_hits = _hits(metadata_text, list(_COMMERCIAL_OPERATION_MARKERS))
    observation_hits = _hits(metadata_text, list(_OBSERVATION_MARKERS))
    strong_computational_hits = _hits(metadata_text, list(_STRONG_COMPUTATIONAL_METHOD_MARKERS))
    strong_experimental_hits = _hits(metadata_text, list(_STRONG_EXPERIMENTAL_OR_INSTRUMENTATION_MARKERS))
    weak_genre_hits = _hits(metadata_text, list(_WEAK_GENRE_SIGNALS))
    semantic_axes = {
        axis: _semantic_axis_detection(text_sections, terms)
        for axis, terms in _SEMANTIC_AXIS_LEXICON.items()
    }
    has_numeric_output = bool(_NUMERIC_RE.search(text))
    has_directional_outcome = bool(
        semantic_axes["outcome"]["hits"]
        and any(marker in text for marker in ("increased", "decreased", "improved", "reduced", "higher", "lower", "changed"))
    )

    if is_review:
        genre = "review"
    elif commercial_operation_hits:
        genre = "full_scale_commercial_operation"
    elif field_experiment_hits:
        genre = "field_demonstration_project"
    elif strong_experimental_hits:
        genre = "controlled_experiment"
    elif strong_computational_hits:
        genre = "computational_or_mechanistic_model"
    elif lab_hits or (
        # Isolated "observed" or "measurement" signals are insufficient.
        # Require an experimental signal that is not solely one of those weak
        # words, together with a source-visible input and output.
        bool(strong_experiment_signal_hits)
        and semantic_axes["input"]["hits"]
        and semantic_axes["outcome"]["hits"]
    ):
        genre = "controlled_experiment"
    elif observation_hits:
        genre = "longitudinal_or_observational_study"
    elif model_hits:
        genre = "computational_or_mechanistic_model"
    elif strong_theory_hits:
        genre = "theoretical_framework"
    elif strong_experiment_signal_hits:
        genre = "experimental_unspecified"
    else:
        genre = "unclassified"

    if genre == "controlled_experiment":
        control_score = 3
    elif genre == "field_demonstration_project":
        control_score = 2
    elif genre == "full_scale_commercial_operation":
        control_score = 1
    elif genre == "longitudinal_or_observational_study":
        control_score = 1
    else:
        control_score = 0
    quantification_score = 3 if has_numeric_output else 1 if has_directional_outcome else 0
    contract_axes = _contract_axis_hits(metadata_text, semantic_contract or {})
    required_contract_axes = [axis for axis, values in contract_axes.items() if values.get("anchors")]
    # A complete causal-chain match must contain at least two non-generic
    # contract anchors.  Generic measurement terms such as ``temperature``
    # and ``capacity`` remain useful semantic evidence but cannot make an
    # unrelated paper look like a mechanism bridge.
    meaningful_axis_count = sum(1 for values in contract_axes.values() if values.get("meaningful_hits"))
    meaningful_hit_count = sum(len(values.get("meaningful_hits") or []) for values in contract_axes.values())
    complete_contract_match = bool(required_contract_axes) and all(contract_axes[axis]["hits"] for axis in required_contract_axes) and meaningful_axis_count >= 2
    any_contract_match = meaningful_hit_count > 0
    alignment_assessment = paper.get("alignment_assessment") if isinstance(paper.get("alignment_assessment"), dict) else {}
    if complete_contract_match or bool(alignment_assessment.get("core_eligible")):
        direct_relevance_score = 3
    elif any_contract_match:
        direct_relevance_score = 1
    else:
        direct_relevance_score = 0
    maturity_total = control_score + quantification_score + direct_relevance_score
    raw_score_threshold_passes = maturity_total >= L1_MATURITY_ACCEPTANCE_THRESHOLD
    # The score contains a relevance component, but make the associated hard
    # boundary explicit instead of allowing a 3+3+0 generic experiment to be
    # reported as a passed L1 record.  Thus a score of 7+ with genuine branch
    # relevance passes automatically; a numerically rich but unrelated paper
    # is rejected for one named reason, never an opaque semantic mismatch.
    maturity_threshold_passes = bool(raw_score_threshold_passes and direct_relevance_score >= 1)
    direct_experimental = genre in {
        "controlled_experiment", "field_demonstration_project", "full_scale_commercial_operation",
        "longitudinal_or_observational_study", "experimental_unspecified",
    } or bool(strong_experimental_hits)
    direct_theoretical = genre in {"theoretical_framework", "computational_or_mechanistic_model"} or bool(strong_computational_hits)
    evidence_level = {
        "controlled_experiment": "laboratory_micro_evidence",
        "field_demonstration_project": "demonstration_level_evidence",
        "full_scale_commercial_operation": "commercial_operational_evidence",
        "longitudinal_or_observational_study": "quantitative_observational_evidence",
        "experimental_unspecified": "experimental_evidence_scale_unresolved",
        "theoretical_framework": "theoretical_context_only",
        "computational_or_mechanistic_model": "model_context_only",
        "review": "background_only",
    }.get(genre, "unclassified")
    ecological_validity = {
        "laboratory_micro_evidence": "low",
        "demonstration_level_evidence": "high",
        "commercial_operational_evidence": "very_high",
        "quantitative_observational_evidence": "high",
        "experimental_evidence_scale_unresolved": "unknown",
        "theoretical_context_only": "not_applicable",
        "model_context_only": "not_applicable",
        "background_only": "not_applicable",
    }.get(evidence_level, "unknown")
    research_design_assessment = classify_research_design(
        paper,
        is_review=is_review,
        genre=genre,
    )
    return {
        "version": PAPER_EVIDENCE_GENRE_VERSION,
        "genre": genre,
        "is_review": is_review,
        "research_design": research_design_assessment["design"],
        "research_design_assessment": research_design_assessment,
        "direct_theoretical_evidence": bool(direct_theoretical and not is_review),
        "direct_experimental_evidence": bool(direct_experimental and not is_review),
        "semantic_axes": semantic_axes,
        "contract_axis_match": contract_axes,
        "evidence_maturity": {
            "control_score": control_score,
            "quantification_score": quantification_score,
            "direct_relevance_score": direct_relevance_score,
            "meaningful_contract_axis_count": meaningful_axis_count,
            "meaningful_contract_hit_count": meaningful_hit_count,
            "total_score": maturity_total,
            "maximum_score": 9,
            "automatic_l1_acceptance_threshold": L1_MATURITY_ACCEPTANCE_THRESHOLD,
            "raw_score_threshold_passes": raw_score_threshold_passes,
            "threshold_passes": maturity_threshold_passes,
            "threshold_definition": "total_score >= 6 and direct_relevance_score >= 1",
            "automatic_l1_acceptance": bool(
                not is_review
                and direct_experimental
                and maturity_threshold_passes
                and all(semantic_axes[axis]["hits"] for axis in ("input", "method", "outcome"))
                and direct_relevance_score >= 1
            ),
        },
        "verification_scale": {
            "evidence_level": evidence_level,
            "ecological_validity": ecological_validity,
            "control_level": control_score,
            "acceptance_policy": (
                "L1 auxiliary bridge only; never direct target evidence or a primary-gap evidence slot."
                if evidence_level in {"demonstration_level_evidence", "commercial_operational_evidence", "quantitative_observational_evidence"}
                else "Classified from abstract/metadata evidence signals."
            ),
        },
        "classification_signals": {
            "theory": theory_hits,
            "strong_theory": strong_theory_hits,
            "modeling": model_hits,
            "experiment": experiment_hits,
            "strong_experiment": strong_experiment_signal_hits,
            "laboratory": lab_hits,
            "field_experiment": field_experiment_hits,
            "commercial_operation": commercial_operation_hits,
            "observation": observation_hits,
            "strong_computational_method": strong_computational_hits,
            "strong_experimental_or_instrumentation_method": strong_experimental_hits,
            "weak_genre_signals": weak_genre_hits,
            "numeric_output_detected": has_numeric_output,
            "directional_outcome_detected": has_directional_outcome,
        },
    }


def build_project_alignment_card(project: dict[str, Any]) -> dict[str, Any]:
    """Build a domain-agnostic, versioned project alignment boundary."""
    # ``research_brief`` is deliberately excluded from the hard context
    # boundary.  It often contains explanatory comparisons (for example DNA
    # or proteins in an astrobiology brief); treating those examples as
    # project identity lets an unrelated paper pass merely because it matches
    # the prose used to introduce the question.
    declared_domain = str(project.get("declared_domain") or "").strip()
    # ``domain`` may be a coarse classifier output.  If a user- or
    # project-declared domain exists, it is the scientific boundary and a
    # mistaken classifier label (for example ``Artificial Intelligence`` for
    # an astrobiology project) must not become an alternative admission path.
    inferred_domain = "" if declared_domain else str(project.get("domain") or "")
    scope_parts = [
        str(project.get("title") or ""),
        declared_domain,
        inferred_domain,
        str(project.get("objective") or ""),
        str(project.get("strategic_need") or ""),
    ]
    scope_source = " ".join(part for part in scope_parts if part.strip())
    terms = _ranked_terms(scope_source, limit=48)
    phrases = _phrases(scope_source, limit=24)
    background_source = str(project.get("research_brief") or "")
    # Anchors are project-local rather than globally "rare".  ``water`` is a
    # weak word for an unrelated project but a decisive identity anchor in an
    # alternative-solvent project; likewise signal, algorithm, simulation, or
    # neural may be the scientific object of another project.  A second
    # branch/relation anchor is required downstream, so retaining these terms
    # does not let a single broad word admit an unrelated paper.
    anchors = [term for term in terms if term not in _PROJECT_ANCHOR_GLUE_TERMS]
    card = {
        "version": ALIGNMENT_VERSION,
        "project_id": str(project.get("project_id") or ""),
        "project_version": int(project.get("state_version") or 0),
        "project_title": str(project.get("title") or ""),
        "project_domain": str(project.get("domain") or ""),
        "project_context_terms": terms,
        "project_context_anchor_terms": anchors[:32],
        "project_context_phrases": phrases,
        # Kept for diagnostics only.  These terms are never used by the hard
        # context gate because a background example is not an object boundary.
        "project_background_terms": _ranked_terms(background_source, limit=24),
        "evidence_chain_policy": {
            "required_evidence_roles": ["mechanism_discovery", "causal_validation"],
            "legacy_required_evidence_kinds": ["theoretical_framework", "experimental_evidence"],
            "background_can_support_rationale_only": True,
            "require_same_subhypothesis_for_primary_gap": True,
        },
    }
    card["alignment_card_hash"] = _stable_hash(card)
    return card


def infer_subhypothesis_evidence_mode(sub_hypothesis: dict[str, Any]) -> str:
    """Resolve the retrieval evidence design without changing research claims."""

    declared = str(
        sub_hypothesis.get("evidence_mode")
        or sub_hypothesis.get("retrieval_evidence_mode")
        or ""
    ).strip().lower().replace("-", "_").replace(" ", "_")
    if declared in {
        PREDICTIVE_GENERALIZATION_EVIDENCE_MODE,
        "predictive_validation",
        "model_generalization",
        "model_generalisation",
        "transportability_validation",
    }:
        return PREDICTIVE_GENERALIZATION_EVIDENCE_MODE
    if declared in {CAUSAL_MECHANISM_EVIDENCE_MODE, "causal", "mechanistic"}:
        return CAUSAL_MECHANISM_EVIDENCE_MODE
    source = _normalize(
        " ".join(
            str(sub_hypothesis.get(key) or "")
            for key in (
                "focus", "scientific_object", "retrieval_query", "independent_variable",
                "falsification_condition", "source_objective",
            )
        )
        + " "
        + " ".join(str(item) for item in (sub_hypothesis.get("causal_chain") or []))
        + " "
        + " ".join(str(item) for item in (sub_hypothesis.get("dependent_variables") or []))
    ).lower()
    model_signal = any(marker in source for marker in _PREDICTIVE_MODEL_MARKERS)
    validation_signal = any(marker in source for marker in _PREDICTIVE_GENERALIZATION_MARKERS)
    return (
        PREDICTIVE_GENERALIZATION_EVIDENCE_MODE
        if model_signal and validation_signal
        else CAUSAL_MECHANISM_EVIDENCE_MODE
    )


def predictive_generalization_moderator_terms(source: Any) -> list[str]:
    """Expand only moderator concepts explicitly declared by the SH."""

    text = _normalize(source).lower()
    expanded: list[str] = []
    for triggers, values in _PREDICTIVE_MODERATOR_GROUPS:
        if any(trigger in text for trigger in triggers):
            expanded.extend(values)
    # External validation itself declares a setting/population boundary even
    # when the objective does not name a demographic attribute.
    if any(marker in text for marker in _PREDICTIVE_GENERALIZATION_MARKERS):
        expanded.extend(("external validation", "external cohort", "subgroup performance", "transportability"))
    return _unique(expanded)


def build_mechanism_outcome_synonym_dictionary(
    *,
    mechanism_text: str = "",
    outcome_text: str = "",
    dependent_variables: list[str] | tuple[str, ...] | None = None,
    causal_steps: list[str] | tuple[str, ...] | None = None,
    primary_field: str = "",
) -> dict[str, Any]:
    """Create deterministic readout synonyms for declared mechanism/outcome axes.

    This does not infer a new scientific claim.  It only records common
    measurement/readout language for an axis that the sub-hypothesis already
    declared.  The source-bound gate still requires object/input support and a
    concrete causal edge before any synonym can help a paper become CORE.
    """

    # Trigger expansions only from the canonical declared axis itself.  Project
    # field labels, arbitrary dependent variables, and a broad causal-chain
    # tail are useful diagnostics but cannot license a cross-domain dictionary
    # to manufacture a new mechanism or endpoint vocabulary.
    axis_sources = {
        "mechanism": _normalize(
            str(mechanism_text or "")
        ).lower(),
        "outcome": _normalize(
            str(outcome_text or "")
            or " ".join(
                str(item or "") for item in (dependent_variables or [])
            )
        ).lower(),
    }
    entries: list[dict[str, str]] = []
    audit: list[dict[str, Any]] = []
    for group in _MECHANISM_OUTCOME_SYNONYM_GROUPS:
        axes = tuple(str(axis) for axis in (group.get("axes") or ()))
        triggers = tuple(str(trigger).lower() for trigger in (group.get("triggers") or ()))
        expansions = tuple(str(value).strip() for value in (group.get("expansions") or ()) if str(value).strip())
        for axis in axes:
            source = axis_sources.get(axis, "")
            matched = [
                trigger
                for trigger in triggers
                if trigger and trigger in source
            ]
            if not matched:
                continue
            canonical = "mechanism/readout axis" if axis == "mechanism" else "outcome/readout axis"
            axis_entries = [
                {
                    "axis": axis,
                    "source_phrase": expansion,
                    # ``_core_axis_support`` already understands this field
                    # for semantic equivalents.  Keep the historical key for
                    # compatibility and add a clearer axis-specific alias.
                    "canonical_focal_variable": canonical,
                    "canonical_axis_value": canonical,
                    "relation": "deterministic_readout_or_measurement_synonym",
                    "status": "deterministic_auxiliary_candidate",
                    "group_id": str(group.get("id") or ""),
                    "origin": "deterministic_axis_trigger",
                    "trigger_phrases": matched[:8],
                    "promotion_policy": "auxiliary_query_only",
                    "eligible_for_canonical_axis": False,
                }
                for expansion in expansions
            ]
            entries.extend(axis_entries)
            audit.append({
                "axis": axis,
                "group_id": str(group.get("id") or ""),
                "matched_triggers": matched[:8],
                "added": [entry["source_phrase"] for entry in axis_entries[:12]],
            })
    serialized_entries = _unique([
        json.dumps(item, sort_keys=True, ensure_ascii=False)
        for item in entries
    ])
    entries = [json.loads(item) for item in serialized_entries]
    mechanism_terms = _unique([
        str(item.get("source_phrase") or "")
        for item in entries
        if str(item.get("axis") or "") == "mechanism"
    ])
    outcome_terms = _unique([
        str(item.get("source_phrase") or "")
        for item in entries
        if str(item.get("axis") or "") == "outcome"
    ])
    dictionary = {
        "version": MECHANISM_OUTCOME_SYNONYM_DICTIONARY_VERSION,
        "status": "ready" if entries else "empty",
        "entries": entries,
        "mechanism_terms": mechanism_terms,
        "outcome_terms": outcome_terms,
        "audit": audit[:12],
    }
    dictionary["dictionary_hash"] = _stable_hash(dictionary)
    return dictionary


def mechanism_outcome_synonym_entries(
    contract: dict[str, Any],
    *,
    axis: str,
) -> list[dict[str, Any]]:
    """Return deterministic semantic-equivalent entries for one causal axis."""

    policy = contract.get("core_axis_policy") if isinstance(contract.get("core_axis_policy"), dict) else {}
    dictionary = (
        policy.get("mechanism_outcome_synonym_dictionary")
        if isinstance(policy.get("mechanism_outcome_synonym_dictionary"), dict)
        else contract.get("mechanism_outcome_synonym_dictionary")
        if isinstance(contract.get("mechanism_outcome_synonym_dictionary"), dict)
        else {}
    )
    if str(dictionary.get("status") or "") != "ready":
        return []
    normalized_axis = str(axis or "").strip().lower()
    return [
        dict(entry)
        for entry in (dictionary.get("entries") or [])
        if isinstance(entry, dict) and str(entry.get("axis") or "").strip().lower() == normalized_axis
    ]


def mechanism_outcome_synonym_terms(
    contract: dict[str, Any],
    *,
    axis: str,
    limit: int = 12,
) -> list[str]:
    """Return source phrases for query building and coarse alignment audits."""

    return _unique([
        str(entry.get("source_phrase") or "")
        for entry in mechanism_outcome_synonym_entries(contract, axis=axis)
        if str(entry.get("source_phrase") or "").strip()
    ])[:limit]


def _object_anchor_tokens(value: Any) -> list[str]:
    return [token.lower() for token in _TOKEN_RE.findall(_normalize(value)) if token]


def _scientific_object_informative_tokens(value: Any) -> list[str]:
    weak = (
        _STOPWORDS
        | _LOW_SIGNAL
        | _PROJECT_ANCHOR_GLUE_TERMS
        | _GENERALIZED_OBJECT_DECLARATION_TERMS
        | _RETRIEVAL_OBJECT_GENERIC_TERMS
        | _OBJECT_ANCHOR_RELATIONAL_TERMS
        | _CONTEXT_WEAK_SINGLE_OBJECT_TERMS
        | {"based", "acid-based"}
    )
    return [
        token
        for token in _object_anchor_tokens(value)
        if token not in weak
    ]


def _looks_like_atomic_scientific_identifier(value: Any) -> bool:
    raw = _normalize(value)
    raw_tokens = _TOKEN_RE.findall(raw)
    if len(raw_tokens) != 1:
        return False
    token = raw_tokens[0]
    normalized = token.lower()
    if (
        not normalized
        or normalized in _STOPWORDS
        or normalized in _LOW_SIGNAL
        or normalized in _PROJECT_ANCHOR_GLUE_TERMS
        or normalized in _RETRIEVAL_OBJECT_GENERIC_TERMS
        or normalized in _CONTEXT_WEAK_SINGLE_OBJECT_TERMS
        or normalized in _OBJECT_ANCHOR_RELATIONAL_TERMS
    ):
        return False
    if normalized == "ph":
        return True
    if any(char.isdigit() for char in token):
        return True
    if re.search(r"[+\-./]", token):
        return True
    if re.search(r"[\u0370-\u03ff\u4e00-\u9fff]", token):
        return True
    if re.search(r"[a-z][A-Z]|[A-Z]{2,}", token):
        return True
    # Lowercase forms can arise from persisted/generated contracts.  Keep a
    # compact identifier allow-list for common molecule/platform symbols, not
    # for any one project domain.
    if normalized in {"dna", "rna", "mrna", "sirna", "mirna", "lnp", "crispr"}:
        return True
    return False


def is_specific_object_anchor(value: Any) -> bool:
    """Return whether an anchor can identify a scientific object by itself."""
    normalized = _normalize(value).lower()
    if not normalized:
        return False
    if _GENERALIZED_OBJECT_DECLARATION_PREFIX_RE.search(normalized):
        return False
    tokens = [token.lower() for token in _TOKEN_RE.findall(normalized)]
    if not tokens:
        return False
    if len(tokens) == 1:
        token = tokens[0]
        if token in _CONTEXT_WEAK_SINGLE_OBJECT_TERMS:
            return False
        return (
            token not in _RETRIEVAL_OBJECT_GENERIC_TERMS
            or _looks_like_atomic_scientific_identifier(value)
            or token in {"t", "b", "nk", "cd4", "cd8"}
        )
    return bool(_scientific_object_informative_tokens(normalized))


def _is_strong_scientific_object_anchor(value: Any, *, declared_single_object: bool = False) -> bool:
    normalized = _normalize(value)
    if not normalized:
        return False
    if _GENERALIZED_OBJECT_DECLARATION_PREFIX_RE.search(normalized):
        return False
    tokens = _object_anchor_tokens(normalized)
    if not tokens:
        return False
    if len(tokens) == 1:
        token = tokens[0]
        if token in _CONTEXT_WEAK_SINGLE_OBJECT_TERMS:
            return False
        if _looks_like_atomic_scientific_identifier(normalized):
            return True
        return bool(
            declared_single_object
            and token not in _RETRIEVAL_OBJECT_GENERIC_TERMS
            and token not in _OBJECT_ANCHOR_RELATIONAL_TERMS
            and len(token) >= 4
        )
    # A fragment ending in "-based" stops at a modifier before naming the
    # object class.  It may help a query, but cannot by itself prove identity.
    if re.search(r"(?:^|\s)[a-z0-9]+-based$", normalized, flags=re.IGNORECASE):
        return False
    return bool(_scientific_object_informative_tokens(normalized))


def _specific_scientific_object_recovery_candidates(
    *,
    project: dict[str, Any],
    project_card: dict[str, Any],
    sub_hypothesis: dict[str, Any],
) -> list[tuple[str, str, int]]:
    """Return project-local entity candidates, strongest identity sources first."""

    candidates: list[tuple[str, str, int]] = []
    source_specs = (
        (project.get("research_identity"), "research_identity", 100),
        (project.get("domain_context"), "domain_context", 90),
        (project_card, "project_card", 80),
    )
    key_weights = {
        "core_entities": 30,
        "core_objects": 28,
        "core_systems": 26,
        "experimental_systems": 22,
        "measurement_modalities": 18,
        "methods": 16,
        "retrieval_synonyms": 12,
        "retrieval_terms": 10,
    }
    for container, source, base_weight in source_specs:
        if not isinstance(container, dict):
            continue
        for key, key_weight in key_weights.items():
            for raw in _iter_scientific_object_alias_values(container.get(key)):
                value = _scientific_text_without_explanatory_alias_markers(raw)
                tokens = _object_anchor_tokens(value)
                if (
                    not value
                    or not tokens
                    or len(tokens) > 10
                    or not _is_strong_scientific_object_anchor(
                        value,
                        declared_single_object=len(tokens) == 1,
                    )
                ):
                    continue
                candidates.append((value, f"{source}.{key}", base_weight + key_weight))
    for key in (
        "scientific_object_aliases",
        "focus_anchor",
    ):
        for raw in _iter_scientific_object_alias_values(sub_hypothesis.get(key)):
            value = _scientific_text_without_explanatory_alias_markers(raw)
            tokens = _object_anchor_tokens(value)
            if (
                value
                and tokens
                and len(tokens) <= 10
                and _is_strong_scientific_object_anchor(
                    value,
                    declared_single_object=len(tokens) == 1,
                )
            ):
                candidates.append((value, f"sub_hypothesis.{key}", 125))
    for key, source_score in (
        ("independent_variable", 118),
        ("dependent_variables", 108),
    ):
        for raw in _iter_scientific_object_alias_values(sub_hypothesis.get(key)):
            tokens = _object_anchor_tokens(raw)
            while (
                len(tokens) > 1
                and tokens[-1]
                in (
                    _LOW_SIGNAL
                    | _GENERALIZED_OBJECT_DECLARATION_TERMS
                    | _L1_GENERIC_RELEVANCE_TERMS
                )
            ):
                tokens.pop()
            value = _normalize(" ".join(tokens))
            if (
                value
                and len(tokens) <= 8
                and _is_strong_scientific_object_anchor(
                    value,
                    declared_single_object=len(tokens) == 1,
                )
            ):
                candidates.append((value, f"sub_hypothesis.{key}", source_score))
    return candidates


def _recover_specific_scientific_object(
    *,
    declared: str,
    project: dict[str, Any],
    project_card: dict[str, Any],
    sub_hypothesis: dict[str, Any],
) -> tuple[str, str]:
    """Replace an objective/endpoint clause with the strongest local entity."""

    declared_tokens = _object_anchor_tokens(declared)
    if _is_strong_scientific_object_anchor(
        declared,
        declared_single_object=len(declared_tokens) == 1,
    ):
        return declared, ""
    focus_context = _normalize(
        " ".join(
            str(sub_hypothesis.get(key) or "")
            for key in (
                "focus",
                "retrieval_query",
                "independent_variable",
                "dependent_variables",
                "causal_chain",
            )
        )
    ).lower()
    ranked: list[tuple[int, int, str, str]] = []
    seen: set[str] = set()
    for value, source, source_score in _specific_scientific_object_recovery_candidates(
        project=project,
        project_card=project_card,
        sub_hypothesis=sub_hypothesis,
    ):
        key = value.lower()
        if key in seen:
            continue
        seen.add(key)
        context_overlap = sum(
            1 for token in _scientific_object_informative_tokens(value)
            if token in focus_context
        )
        atomic_bonus = 8 if _looks_like_atomic_scientific_identifier(value) else 0
        brevity_bonus = max(0, 8 - len(_object_anchor_tokens(value)))
        ranked.append(
            (
                source_score + 12 * context_overlap + atomic_bonus + brevity_bonus,
                -len(value),
                value,
                source,
            )
        )
    if not ranked:
        return "", ""
    _, _, value, source = max(ranked)
    return value, source


def _final_noun_number_variants(value: str) -> list[str]:
    normalized = _normalize(value)
    if not normalized:
        return []
    # Atomic scientific identifiers (for example CRISPR-Cas9, CFTR, IL-6,
    # or a registered platform name) are proper identifiers rather than
    # count nouns.  Inflecting them creates false strong anchors such as
    # "CRISPR-Cas9s" and weakens object precision.
    if _looks_like_atomic_scientific_identifier(normalized):
        return [normalized]
    parts = normalized.split()
    if not parts:
        return []
    last = parts[-1]
    variants = [normalized]
    singular = last
    plural = last
    # Many scientific method nouns ending in -y are mass nouns or method
    # families, not count nouns.  Blindly appending "s" creates anchors such
    # as "microscopys" that are neither useful nor auditable.
    if last.lower().endswith((
        "scopy", "metry", "graphy", "ography", "ology", "omics",
    )):
        return _unique(variants)
    if re.search(r"ies$", last, flags=re.IGNORECASE) and len(last) > 4:
        singular = re.sub(r"ies$", "y", last, flags=re.IGNORECASE)
    elif last.lower().endswith("s") and not last.lower().endswith("ss") and len(last) > 3:
        singular = last[:-1]
    else:
        plural = f"{last}s"
    if singular != last:
        variants.append(" ".join(parts[:-1] + [singular]))
    elif plural != last and not last.lower().endswith(("s", "x", "z")):
        variants.append(" ".join(parts[:-1] + [plural]))
    return _unique(variants)


def _object_phrase_variants(value: Any) -> list[str]:
    normalized = _normalize(value)
    if not normalized:
        return []
    normalized = re.sub(r"[\u2010-\u2015\u2212]", "-", normalized)
    if re.search(r"(?:^|\s)[A-Za-z0-9]+-based$", normalized, flags=re.IGNORECASE):
        return [normalized]
    variants = [normalized]
    if "-based" in normalized:
        variants.append(normalized.replace("-based", " based"))
        variants.append(_normalize(normalized.replace("-based", "")))
    if " based " in normalized:
        variants.append(_normalize(normalized.replace(" based ", " ")))
    context_head = _FOCAL_VARIABLE_CONTEXT_SPLIT_RE.split(normalized, maxsplit=1)[0].strip()
    if context_head and context_head != normalized and len(_object_anchor_tokens(context_head)) >= 2:
        variants.append(context_head)
    expanded: list[str] = []
    for variant in variants:
        expanded.extend(_final_noun_number_variants(variant) or [variant])
    return _unique(expanded)


def _object_phrase_overlap(left: Any, right: Any) -> bool:
    left_key = _normalize(left).lower()
    right_key = _normalize(right).lower()
    if not left_key or not right_key:
        return False
    if left_key == right_key:
        return True
    left_tokens = _object_anchor_tokens(left_key)
    right_tokens = _object_anchor_tokens(right_key)
    if min(len(left_tokens), len(right_tokens)) >= 2 and (
        left_key in right_key or right_key in left_key
    ):
        return True
    informative_overlap = set(_scientific_object_informative_tokens(left_key)) & set(
        _scientific_object_informative_tokens(right_key)
    )
    return len(informative_overlap) >= 2


_OBJECT_MATURITY_COMPONENT_STATUSES = frozenset({
    "component_evidence_only",
    "translational_bridge",
    "speculative_unanchored",
})


def _object_maturity_audit_from_subhypothesis(
    sub_hypothesis: dict[str, Any] | None,
) -> dict[str, Any]:
    sh = sub_hypothesis if isinstance(sub_hypothesis, dict) else {}
    audit = (
        sh.get("object_maturity_resolution")
        if isinstance(sh.get("object_maturity_resolution"), dict)
        else sh.get("object_maturity_preflight")
        if isinstance(sh.get("object_maturity_preflight"), dict)
        else sh.get("object_maturity_audit")
        if isinstance(sh.get("object_maturity_audit"), dict)
        else {}
    )
    return dict(audit) if isinstance(audit, dict) else {}


def _object_maturity_status_from_audit(audit: dict[str, Any] | None) -> str:
    data = audit if isinstance(audit, dict) else {}
    status = _normalize(
        data.get("object_status")
        or data.get("literature_anchorability")
        or data.get("status")
        or "directly_established"
    ).lower().replace("-", "_").replace(" ", "_")
    if status in {"component", "component_only", "component_evidence"}:
        return "component_evidence_only"
    if status in {"bridge", "translation_bridge", "translational"}:
        return "translational_bridge"
    if status in {"speculative", "unanchored", "future_vision"}:
        return "speculative_unanchored"
    if status in {"contract_repair_required", "invalid_object_contract", "object_contract_invalid"}:
        return "contract_repair_required"
    if status in _OBJECT_MATURITY_COMPONENT_STATUSES or status == "directly_established":
        return status
    return "directly_established"


def _object_maturity_direct_core_allowed(audit: dict[str, Any] | None) -> bool:
    data = audit if isinstance(audit, dict) else {}
    if isinstance(data.get("direct_local_edge_evidence_allowed"), bool):
        return bool(data.get("direct_local_edge_evidence_allowed"))
    status = _object_maturity_status_from_audit(data)
    if status == "contract_repair_required":
        return False
    if status in _OBJECT_MATURITY_COMPONENT_STATUSES:
        return False
    if isinstance(data.get("direct_core_evidence_allowed"), bool):
        return bool(data.get("direct_core_evidence_allowed"))
    return True


def is_component_bridge_modifier_only_anchor(value: Any) -> bool:
    """Return true for bridge/query role words that are not object anchors.

    Component-bridge retrieval needs current component, model-system, method,
    or readout anchors.  Phrases such as ``translation model system`` or
    ``safety failure mode`` describe the evidence role; if they are allowed to
    count as object anchors they become broad corpus passports.
    """

    normalized = (
        _normalize(value)
        .lower()
        .replace("–", "-")
        .replace("—", "-")
        .replace("−", "-")
    )
    if not normalized:
        return True
    comparable = normalized.replace("-", " ")
    phrase_keys = _COMPONENT_BRIDGE_MODIFIER_ONLY_PHRASES | {
        item.replace("-", " ")
        for item in _COMPONENT_BRIDGE_MODIFIER_ONLY_PHRASES
    }
    if normalized in phrase_keys or comparable in phrase_keys:
        return True
    protected_phrase_keys = _COMPONENT_BRIDGE_PROTECTED_CONCRETE_PHRASES | {
        item.replace("-", " ")
        for item in _COMPONENT_BRIDGE_PROTECTED_CONCRETE_PHRASES
    }
    if normalized in protected_phrase_keys or comparable in protected_phrase_keys:
        return False
    tokens = [
        token.lower()
        for token in _TOKEN_RE.findall(comparable)
        if token.lower() not in _STOPWORDS
    ]
    if not tokens:
        return True
    concrete_tokens = [
        token
        for token in tokens
        if token not in _COMPONENT_BRIDGE_MODIFIER_ONLY_TERMS
    ]
    return not concrete_tokens


def is_query_method_or_readout_only_anchor(value: Any) -> bool:
    """Return true when a query-plan object anchor is really method/readout role.

    This is intentionally role-local.  A term such as ``field trial`` or
    ``survival rate`` is useful in a provider query, but it cannot be the only
    evidence that the query preserved the current SH's scientific object.  We
    keep these terms available as support anchors and only demote them from the
    object-identity requirement.
    """

    normalized = _normalize(value).lower().replace("-", " ")
    if not normalized:
        return True
    if is_component_bridge_modifier_only_anchor(normalized):
        return True
    if normalized in _QUERY_METHOD_OR_READOUT_ONLY_PHRASES:
        return True
    tokens = [
        token.lower()
        for token in _TOKEN_RE.findall(normalized)
        if token.lower() not in _STOPWORDS
    ]
    if not tokens:
        return True
    if len(tokens) == 1:
        return tokens[0] in (
            _QUERY_METHOD_OR_READOUT_ONLY_TAIL_TERMS
            | _QUERY_READOUT_ONLY_TERMS
            | _COMPONENT_BRIDGE_MODIFIER_ONLY_TERMS
        )
    if tokens[-1] in _QUERY_METHOD_OR_READOUT_ONLY_TAIL_TERMS:
        specific_tokens = [
            token
            for token in tokens[:-1]
            if token not in (
                _QUERY_METHOD_OR_READOUT_ONLY_HEAD_TERMS
                | _QUERY_METHOD_OR_READOUT_ONLY_TAIL_TERMS
                | _QUERY_READOUT_ONLY_TERMS
                | _COMPONENT_BRIDGE_MODIFIER_ONLY_TERMS
            )
        ]
        # A phrase like "crop diversity studies" should not become object
        # identity just because it contains a domain word before "studies".
        if tokens[-1] in {"study", "studies", "analysis", "analyses", "assessment", "assessments", "evaluation", "evaluations"}:
            return True
        if not specific_tokens:
            return True
    if set(tokens).issubset(
        _QUERY_METHOD_OR_READOUT_ONLY_HEAD_TERMS
        | _QUERY_METHOD_OR_READOUT_ONLY_TAIL_TERMS
        | _QUERY_READOUT_ONLY_TERMS
        | _COMPONENT_BRIDGE_MODIFIER_ONLY_TERMS
    ):
        return True
    return False


def _filter_component_bridge_modifier_only_anchors(values: list[str]) -> tuple[list[str], list[str]]:
    kept: list[str] = []
    removed: list[str] = []
    for value in values:
        normalized = _normalize(value)
        if not normalized:
            continue
        if is_component_bridge_modifier_only_anchor(normalized):
            removed.append(normalized)
        else:
            kept.append(normalized)
    return _unique(kept), _unique(removed)


def _object_maturity_anchor_values(
    audit: dict[str, Any] | None,
    *keys: str,
    limit: int = 24,
) -> list[str]:
    data = audit if isinstance(audit, dict) else {}
    values: list[str] = []
    selected_keys = keys or (
        "object_anchors",
        "method_or_platform_anchors",
        "readout_anchors",
        "model_system_anchors",
    )
    for key in selected_keys:
        raw = data.get(key)
        values.extend(_iter_scientific_object_alias_values(raw))
    support_anchor_keys = {
        "method_or_platform_anchors",
        "readout_anchors",
        "model_system_anchors",
        "component_bridge_method_or_platform_anchor_phrases",
        "component_bridge_readout_anchor_phrases",
        "component_bridge_model_system_anchor_phrases",
    }
    support_mode = bool(set(selected_keys) & support_anchor_keys)
    anchors: list[str] = []
    for value in values:
        normalized = _normalize(value)
        if not normalized:
            continue
        if support_mode:
            if len(_object_anchor_tokens(normalized)) < 1:
                continue
            anchors.append(normalized)
        elif _is_strong_scientific_object_anchor(normalized):
            anchors.append(normalized)
    anchors, _removed = _filter_component_bridge_modifier_only_anchors(_unique(anchors))
    return anchors[: max(0, int(limit))]


def _is_measurement_or_method_object_text(value: Any) -> bool:
    normalized = _normalize(value).lower()
    return any(marker in normalized for marker in _MEASUREMENT_METHOD_OBJECT_MARKERS)


def _semantic_measurement_object_aliases(
    *,
    declared_object: str,
    scientific_object_text: str,
    focus_text: str,
    project_context_text: str,
) -> dict[str, Any]:
    """Return method-equivalent and related-context object anchors.

    The function is deliberately role-based rather than field-based.  It only
    activates when the current object/context already declares a measurement,
    imaging, assay, sensor, sequencing, spectroscopy, or similar method.  Exact
    equivalents may later prove object identity; related-context anchors only
    support high-recall auxiliary full-text admission.
    """

    source = _normalize(
        " ".join(
            value
            for value in (
                declared_object,
                scientific_object_text,
                focus_text,
                project_context_text,
            )
            if str(value or "").strip()
        )
    )
    lowered = source.lower()
    method_like = _is_measurement_or_method_object_text(source)
    equivalent: list[str] = []
    related: list[str] = []
    audit: list[dict[str, str]] = []
    if not method_like:
        return {
            "version": OBJECT_SEMANTIC_EQUIVALENCE_POLICY_VERSION,
            "status": "not_method_or_measurement_object",
            "semantic_equivalent_anchors": [],
            "related_context_anchors": [],
            "alias_audit": [],
        }

    def add_equivalent(anchor: str, source_id: str) -> None:
        normalized = _normalize(anchor)
        if (
            normalized
            and _is_strong_scientific_object_anchor(normalized)
            and normalized not in equivalent
        ):
            equivalent.append(normalized)
            audit.append({"anchor": normalized, "source": source_id, "strength": "semantic_equivalent"})

    def add_related(anchor: str, source_id: str) -> None:
        normalized = _normalize(anchor)
        if (
            normalized
            and _is_strong_scientific_object_anchor(normalized)
            and normalized not in related
            and normalized not in equivalent
        ):
            related.append(normalized)
            audit.append({"anchor": normalized, "source": source_id, "strength": "related_context"})

    # Generic hyphen/spacing variants are semantic equivalents for all method
    # objects, and they are still source-bound by the current declared object.
    for variant in _object_phrase_variants(declared_object):
        if variant and variant != _normalize(declared_object):
            add_equivalent(variant, "declared_object_orthographic_variant")

    # Method-family equivalence: cryogenic fluorescence/light/electron
    # correlative microscopy terminology is an instrumentation vocabulary, not
    # a cell-biology patch.  It only activates when the user/project text
    # already names cryo imaging/tomography methods.
    has_cryo = "cryo" in lowered or "cryogenic" in lowered
    has_fluorescence_microscopy = (
        ("fluorescence microscopy" in lowered or "fluorescence-microscopy" in lowered)
        and "microscopy" in lowered
    )
    has_electron_tomography = (
        "electron tomography" in lowered
        or "electron-tomography" in lowered
        or "cryo-et" in lowered
        or "cryo et" in lowered
    )
    if has_cryo and has_fluorescence_microscopy:
        for anchor in (
            "cryo fluorescence microscopy",
            "cryo-fluorescence microscopy",
            "cryogenic fluorescence microscopy",
            "cryo light microscopy",
            "cryo-light microscopy",
        ):
            add_equivalent(anchor, "measurement_method_semantic_equivalence")
    if has_cryo and has_fluorescence_microscopy and has_electron_tomography:
        for anchor in (
            "cryo-CLEM",
            "cryo CLEM",
            "correlative cryo-fluorescence and cryo-electron tomography",
            "correlative cryo fluorescence and cryo electron tomography",
            "correlative light and electron microscopy",
            "correlative cryo light and electron microscopy",
        ):
            add_equivalent(anchor, "correlative_measurement_method_equivalence")
    if has_cryo and has_electron_tomography:
        for anchor in (
            "cryo-electron tomography",
            "cryo electron tomography",
            "cryo-ET",
            "cryo ET",
            "in situ cryo-electron tomography",
            "in situ cryo electron tomography",
        ):
            add_related(anchor, "complementary_measurement_context")
    return {
        "version": OBJECT_SEMANTIC_EQUIVALENCE_POLICY_VERSION,
        "status": "ready",
        "semantic_equivalent_anchors": equivalent[:32],
        "related_context_anchors": related[:32],
        "alias_audit": audit[:48],
    }


def _project_context_object_anchor_values(
    *,
    project: dict[str, Any],
    project_card: dict[str, Any],
    sub_hypothesis: dict[str, Any],
    evidence_paths: list[dict[str, Any]] | None = None,
) -> list[str]:
    values: list[Any] = []
    for container in (
        project.get("domain_context") if isinstance(project.get("domain_context"), dict) else {},
        project.get("research_identity") if isinstance(project.get("research_identity"), dict) else {},
        project_card,
    ):
        if not isinstance(container, dict):
            continue
        for key in (
            "core_entities",
            "core_objects",
            "core_systems",
            "complementary_objects",
            "complementary_modalities",
            "complementary_technologies",
            "measurement_modalities",
            "methods",
            "experimental_systems",
            "retrieval_terms",
            "retrieval_synonyms",
            "project_context_phrases",
            "project_context_anchor_terms",
        ):
            values.extend(_iter_scientific_object_alias_values(container.get(key)))
    raw_causal_contract = (
        sub_hypothesis.get("causal_contract")
        if isinstance(sub_hypothesis.get("causal_contract"), dict)
        else {}
    )
    for key in (
        "scientific_object_aliases",
        "focus_anchor",
        "causal_chain",
        "independent_variable",
        "dependent_variables",
        "controls",
        "comparison",
        "comparison_conditions",
        "baseline_or_comparator",
        "moderators",
        "tradeoff_or_conflict",
        "counter_hypothesis",
        "alternative_mechanisms",
    ):
        values.extend(_iter_scientific_object_alias_values(sub_hypothesis.get(key)))
    for key in (
        "pivotal_mechanism",
        "supporting_mediators",
        "outcome",
        "boundary_conditions",
        "confounders_or_alternatives",
    ):
        values.extend(_iter_scientific_object_alias_values(raw_causal_contract.get(key)))
    for path in evidence_paths or []:
        if not isinstance(path, dict):
            continue
        values.extend(_iter_scientific_object_alias_values(path.get("causal_steps")))
        values.extend(_iter_scientific_object_alias_values(path.get("retrieval_query")))
    return _unique([_normalize(value) for value in values if _normalize(value)])


def _explanatory_scientific_object_alias_pairs(
    value: Any,
) -> list[tuple[str, str, str]]:
    """Return canonical/alias pairs without treating discourse as an entity."""

    text = _normalize(value)
    pairs: list[tuple[str, str, str]] = []
    if not text:
        return pairs
    for pattern in _EXPLANATORY_ALIAS_PATTERNS:
        for match in pattern.finditer(text):
            canonical = _normalize(match.group("canonical"))
            alias = _normalize(match.group("alias"))
            if not canonical or not alias:
                continue
            pairs.append((canonical, alias, match.group(0)))
    return pairs


def _scientific_text_without_explanatory_alias_markers(value: Any) -> str:
    """Remove linguistic alias markers while retaining both entity strings."""

    text = _normalize(value)
    if not text:
        return ""
    for pattern in _EXPLANATORY_ALIAS_PATTERNS:
        text = pattern.sub(
            lambda match: (
                f"{_normalize(match.group('canonical'))} "
                f"{_normalize(match.group('alias'))}"
            ),
            text,
        )
    text = _EXPLANATORY_ALIAS_DANGLING_SUFFIX_RE.sub("", text)
    text = _EXPLANATORY_ALIAS_LEADING_MARKER_RE.sub("", text)
    return _normalize(text)


def _scientific_object_declaration_context_values(
    *,
    project: dict[str, Any] | None = None,
    project_card: dict[str, Any] | None = None,
    sub_hypothesis: dict[str, Any] | None = None,
) -> list[str]:
    """Collect only project-local declaration/identity text for alias recovery."""

    values: list[Any] = []
    project_payload = project if isinstance(project, dict) else {}
    card = project_card if isinstance(project_card, dict) else {}
    sh = sub_hypothesis if isinstance(sub_hypothesis, dict) else {}
    for key in (
        "research_brief",
        "domain_research_brief",
        "objective",
        "original_objective",
        "title",
        "research_question",
    ):
        values.append(project_payload.get(key))
        values.append(card.get(key))
    for container in (
        project_payload.get("domain_context")
        if isinstance(project_payload.get("domain_context"), dict)
        else {},
        project_payload.get("research_identity")
        if isinstance(project_payload.get("research_identity"), dict)
        else {},
        card,
        sh,
    ):
        if not isinstance(container, dict):
            continue
        for key in (
            "core_entities",
            "core_objects",
            "core_systems",
            "retrieval_terms",
            "retrieval_synonyms",
            "project_context_phrases",
            "scientific_object_aliases",
        ):
            values.extend(
                _iter_scientific_object_alias_values(container.get(key))
            )
    return _unique(
        [
            _normalize(value)
            for value in values
            if isinstance(value, str) and _normalize(value)
        ]
    )


def normalize_scientific_object_declaration(
    declared_scientific_object: Any,
    *,
    context_values: list[str] | None = None,
) -> dict[str, Any]:
    """Normalize ``X (Y for short)``-style declarations field-neutrally."""

    raw = _normalize(declared_scientific_object)
    direct_pairs = _explanatory_scientific_object_alias_pairs(raw)
    aliases: list[str] = []
    source = "declared_object"
    if direct_pairs:
        canonical, alias, _ = direct_pairs[0]
        aliases.append(alias)
        source = "declared_explanatory_alias"
    else:
        canonical = _scientific_text_without_explanatory_alias_markers(raw)

    cleaned_declared = canonical
    contextual_candidates: list[tuple[int, int, str, str]] = []
    for position, context_value in enumerate(context_values or []):
        context = _normalize(context_value)
        contextual_pairs = _explanatory_scientific_object_alias_pairs(context)
        for contextual_canonical, contextual_alias, _ in contextual_pairs:
            if (
                cleaned_declared
                and contextual_alias.lower() == cleaned_declared.lower()
            ):
                contextual_candidates.append(
                    (
                        position,
                        len(_object_anchor_tokens(contextual_canonical)),
                        contextual_canonical,
                        contextual_alias,
                    )
                )
        context_without_markers = _scientific_text_without_explanatory_alias_markers(
            context
        )
        # A short named entity may safely expand a shorthand declaration
        # (e.g. ``perovskite cells`` -> ``hybrid perovskite solar cells``).
        # A sentence-like project objective is not an alias declaration:
        # replacing ``photovoltaic cells`` with ``photon wavelength
        # optimization of photovoltaic cells`` would collapse the primary
        # object into an input/readout context.  Explicit explanatory alias
        # syntax remains handled above irrespective of length.
        if (
            not contextual_pairs
            and cleaned_declared
            and context_without_markers.lower() != cleaned_declared.lower()
            and len(_object_anchor_tokens(context_without_markers)) <= 4
            and re.search(
                rf"(?<![A-Za-z0-9]){re.escape(cleaned_declared)}(?![A-Za-z0-9])",
                context_without_markers,
                flags=re.IGNORECASE,
            )
        ):
            contextual_candidates.append(
                (
                    position,
                    len(_object_anchor_tokens(context_without_markers)),
                    context_without_markers,
                    cleaned_declared,
                )
            )
    if not direct_pairs and contextual_candidates:
        contextual_candidates.sort(key=lambda item: (item[1], item[0]))
        _, _, contextual_canonical, contextual_alias = contextual_candidates[0]
        canonical = contextual_canonical
        aliases.append(contextual_alias)
        source = "project_context_explanatory_alias"

    canonical = _scientific_text_without_explanatory_alias_markers(canonical)
    aliases = _unique(
        [
            _scientific_text_without_explanatory_alias_markers(alias)
            for alias in aliases
            if _scientific_text_without_explanatory_alias_markers(alias)
        ]
    )
    aliases = [
        alias for alias in aliases
        if alias.lower() != canonical.lower()
    ]
    return {
        "canonical": canonical,
        "aliases": aliases,
        "source": source,
        "raw": raw,
        "markers_removed": bool(raw and raw != canonical) or bool(direct_pairs),
    }


def _filter_excluded_nearby_objects_against_protected_context(
    exclusions: list[str],
    *,
    protected_context_anchors: list[str],
) -> tuple[list[str], dict[str, Any]]:
    kept: list[str] = []
    removed: list[str] = []
    matched: dict[str, list[str]] = {}
    for excluded in exclusions:
        hits = [
            anchor
            for anchor in protected_context_anchors
            if _scope_term_overlaps_any(excluded, [anchor])
        ]
        if hits:
            removed.append(excluded)
            matched[excluded] = hits[:8]
        else:
            kept.append(excluded)
    return kept, {
        "schema_version": "excluded_context_reconciliation_v1",
        "policy": (
            "explicit exclusions may contain only true competing, out-of-scope, "
            "or irrelevant nearby objects; current-SH scientific objects, "
            "declared inputs, dependent variables, mechanisms, typed anchors, "
            "comparison levels, and project-identity terms overlapping those "
            "positive anchors are protected context"
        ),
        "reason_code": "CURRENT_SH_POSITIVE_CONTEXT_WAS_MARKED_EXCLUDED",
        "removed_protected_context_exclusions": removed,
        "matched_protected_context_anchors": matched,
        "remaining_excluded_nearby_objects": kept,
    }


_COMPARISON_MARKER_PHRASES = (
    "compared with",
    "compared to",
    "relative to",
    "versus",
    "vs",
)
_COMPARISON_SPLIT_RE = re.compile(
    r"\s+(?:vs\.?|versus|compared\s+(?:with|to)|relative\s+to)\s+",
    flags=re.IGNORECASE,
)
_QUESTION_PREFIX_RE = re.compile(
    r"^\s*(?:"
    r"to\s+what\s+extent\s+(?:do|does|can|could|will|would|is|are)?\s*"
    r"|whether\s+"
    r"|if\s+"
    r"|how\s+(?:do|does|can|could|will|would|is|are)\s+"
    r")",
    flags=re.IGNORECASE,
)
_COMPARISON_TAIL_RE = re.compile(
    r"\b(?:when\s+)?(?:compared(?:\s+(?:with|to))?|relative\s+to)\b.*$",
    flags=re.IGNORECASE,
)
_QUERY_SYNTAX_ONLY_ANCHORS = frozenset({
    "a",
    "an",
    "the",
    "as",
    "to",
    "do",
    "does",
    "than",
    "when",
    "then",
    "where",
    "which",
    "what",
    "whether",
    "if",
    "vs",
    "vs.",
    "versus",
    "compare",
    "compared",
    "comparison",
    "comparative",
    "compared a",
    "compared an",
    "compared the",
    "compared with",
    "compared to",
    "when compared",
    "when compared with",
    "when compared to",
    "relative",
    "relative to",
    "extent",
    "to what extent",
    "what extent",
    "baseline when",
})
_BASELINE_COMPARATOR_EXACT_ANCHORS = frozenset({
    "baseline",
    "baselines",
    "control",
    "controls",
    "control group",
    "control arm",
    "control condition",
    "comparison group",
    "comparator",
    "comparators",
    "reference",
    "reference case",
    "reference scenario",
    "status quo",
    "counterfactual",
    "counterfactual baseline",
    "placebo",
    "placebo control",
    "usual care",
    "standard care",
    "standard-of-care",
    "business as usual",
    "business-as-usual",
    "bau",
    "no intervention",
    "no-intervention",
    "no-intervention baseline",
    "no intervention baseline",
    "no treatment",
    "no-treatment",
    "untreated",
    "untreated control",
    "null intervention",
    "null treatment",
    "no mitigation",
    "no-mitigation",
})
_BASELINE_COMPARATOR_PHRASE_RE = re.compile(
    r"(?<![a-z0-9])(?:"
    r"no[-\s]?intervention|no[-\s]?treatment|no[-\s]?mitigation|"
    r"untreated(?:\s+control)?|placebo(?:\s+control)?|usual\s+care|"
    r"standard[-\s]?of[-\s]?care|standard\s+care|business[-\s]+as[-\s]+usual|"
    r"counterfactual(?:\s+baseline)?|status\s+quo|"
    r"reference\s+(?:case|scenario)|"
    r"control\s+(?:group|arm|condition)|"
    r"(?:comparison\s+)?baseline(?:s)?"
    r")(?![a-z0-9])",
    flags=re.IGNORECASE,
)


def _strip_question_prefix(value: Any) -> str:
    """Remove question grammar that is not a scientific anchor."""

    text = _normalize(value)
    if not text:
        return ""
    text = _QUESTION_PREFIX_RE.sub("", text)
    text = _COMPARISON_TAIL_RE.sub("", text)
    text = re.sub(r"\bwhen\s*$", "", text, flags=re.IGNORECASE)
    return _normalize(text)


def _is_query_syntax_only_anchor(value: Any) -> bool:
    """True for grammar/comparison-marker fragments that must not be queried."""

    text = _normalize(value).strip(" .,:;\"'()[]{}").lower()
    if not text:
        return True
    if text in _QUERY_SYNTAX_ONLY_ANCHORS:
        return True
    if text.startswith("to what extent"):
        return True
    if re.fullmatch(
        r"(?:when\s+)?compared(?:\s+(?:with|to|a|an|the))?",
        text,
        flags=re.IGNORECASE,
    ):
        return True
    if re.fullmatch(
        r"(?:baseline|control|comparator)\s+when",
        text,
        flags=re.IGNORECASE,
    ):
        return True
    return False


def _is_baseline_or_comparator_anchor(value: Any) -> bool:
    """Classify baseline/control/counterfactual anchors independently of domain."""

    text = _normalize(value).strip(" .,:;\"'()[]{}").lower()
    if not text or _is_query_syntax_only_anchor(text):
        return False
    if text in _BASELINE_COMPARATOR_EXACT_ANCHORS:
        return True
    token_count = len(re.findall(r"[a-z0-9]+", text))
    if token_count <= 6 and _BASELINE_COMPARATOR_PHRASE_RE.search(text):
        return True
    return False


def _anchor_matches_baseline_or_comparator_terms(
    value: Any,
    baseline_or_comparator_terms: Any,
) -> bool:
    """Return True when a value is itself a declared comparator/baseline."""

    text = _normalize(value).lower()
    if not text:
        return False
    for raw_term in _scope_policy_values(baseline_or_comparator_terms):
        term = _normalize(raw_term).lower()
        if not term:
            continue
        if text == term:
            return True
        term_token_count = len(re.findall(r"[a-z0-9]+", term))
        if term_token_count >= 2 and _scope_term_matches_text(term, text):
            return True
    return False


def _non_baseline_terms_from_structured_declared_input(
    structured_declared_input: dict[str, Any] | None,
) -> list[str]:
    payload = structured_declared_input if isinstance(structured_declared_input, dict) else {}
    return _unique(
        _scope_policy_values(payload.get("non_baseline_comparison_level_terms"))
        or _scope_policy_values(payload.get("comparison_level_terms"))
    )


def _declared_baseline_or_comparator_terms(
    structured_declared_input: dict[str, Any] | None,
    *sources: Any,
) -> list[str]:
    """Return comparator terms that are not protected non-baseline levels."""

    payload = structured_declared_input if isinstance(structured_declared_input, dict) else {}
    positive_levels = _non_baseline_terms_from_structured_declared_input(payload)
    raw_terms = (
        _scope_policy_values(payload.get("baseline_or_comparator_terms"))
        + [term for source in sources for term in _scope_policy_values(source)]
    )
    return _unique([
        term
        for term in raw_terms
        if term and not _anchor_matches_baseline_or_comparator_terms(term, positive_levels)
    ])


def _clean_anchor_for_query_role(
    value: Any,
    *,
    role: str = "generic",
    baseline_or_comparator_terms: Any = (),
) -> str:
    """Normalize an anchor under its query role.

    Baselines, controls, and counterfactuals are valid comparison context, but
    they cannot satisfy object identity or the SH-local causal input/exposure.
    """

    text = _clean_comparison_fragment(value)
    if not text or _is_query_syntax_only_anchor(text):
        return ""
    normalized_role = str(role or "generic").strip().lower()
    baseline_allowed_roles = {
        "baseline_or_comparator",
        "boundary_or_cost_or_comparison",
        "comparison_boundary",
        "project_background",
    }
    if normalized_role not in baseline_allowed_roles:
        if _is_baseline_or_comparator_anchor(text):
            return ""
        if normalized_role in {"causal_input", "non_baseline_comparison"} and _anchor_matches_baseline_or_comparator_terms(
            text,
            baseline_or_comparator_terms,
        ):
            return ""
    return text


def _clean_anchor_group_for_query_role(
    values: Any,
    *,
    role: str = "generic",
    baseline_or_comparator_terms: Any = (),
    limit: int | None = None,
) -> list[str]:
    cleaned = _unique([
        item
        for value in _scope_policy_values(values)
        for item in [
            _clean_anchor_for_query_role(
                value,
                role=role,
                baseline_or_comparator_terms=baseline_or_comparator_terms,
            )
        ]
        if item
    ])
    if limit is None:
        return cleaned
    return cleaned[: max(0, int(limit))]


def _clean_comparison_fragment(value: Any) -> str:
    text = _strip_question_prefix(value)
    if not text:
        return ""
    text = re.sub(r"^[,;:/()\[\]\s]+|[,;:/()\[\]\s]+$", "", text)
    text = re.sub(r"(?<![A-Za-z0-9])vs\.?(?![A-Za-z0-9])", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"(?<![A-Za-z0-9])versus(?![A-Za-z0-9])", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\bcompared\s+(?:with|to)\b", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\brelative\s+to\b", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"^[,;:/()\[\]\s]+|[,;:/()\[\]\s]+$", "", _normalize(text))
    if _is_query_syntax_only_anchor(text):
        return ""
    return text


def _comparison_level_labels_from_text(value: Any) -> list[str]:
    text = _normalize(value)
    if not text:
        return []
    paren_candidates: list[str] = []
    for paren in re.findall(r"\(([^()]*)\)", text):
        if _COMPARISON_SPLIT_RE.search(f" {paren} "):
            paren_candidates.extend(_COMPARISON_SPLIT_RE.split(f" {paren} "))
    if paren_candidates:
        return _unique([
            cleaned
            for candidate in paren_candidates
            for cleaned in [_clean_comparison_fragment(candidate)]
            if cleaned
        ])
    candidates: list[str] = []
    if _COMPARISON_SPLIT_RE.search(f" {text} "):
        candidates.extend(_COMPARISON_SPLIT_RE.split(f" {text} "))
    labels: list[str] = []
    for candidate in candidates:
        cleaned = _clean_comparison_fragment(candidate)
        if cleaned:
            labels.append(cleaned)
    return _unique(labels)


def _declared_input_without_inline_comparison(value: Any) -> str:
    text = _strip_question_prefix(value)
    if not text:
        return ""
    cleaned = re.sub(
        r"\([^()]*(?:vs\.?|versus|compared\s+(?:with|to)|relative\s+to)[^()]*\)",
        " ",
        text,
        flags=re.IGNORECASE,
    )
    return _clean_comparison_fragment(cleaned) or text


def _contains_comparison_marker(value: Any) -> bool:
    text = _normalize(value)
    return bool(text and _COMPARISON_SPLIT_RE.search(f" {text} "))


def _comparison_level_terms(
    label: str,
    *,
    declared_input_variable: str,
    scientific_object: str,
) -> list[str]:
    cleaned_label = _clean_comparison_fragment(label)
    if not cleaned_label or _is_query_syntax_only_anchor(cleaned_label):
        return []
    terms = [cleaned_label]
    for base in (scientific_object, declared_input_variable):
        cleaned_base = _declared_input_without_inline_comparison(base)
        if not cleaned_base:
            continue
        if _scope_term_matches_text(cleaned_label, cleaned_base):
            terms.append(cleaned_base)
            continue
        terms.append(_normalize(f"{cleaned_label} {cleaned_base}"))
    return _unique([
        term for term in terms
        if term and not _clean_comparison_fragment(term).lower() in {"vs", "versus"}
    ])


def build_structured_declared_input_comparison(
    *,
    independent_variable: Any,
    comparison_text: Any = "",
    comparison_conditions: Any = "",
    controls: Any = (),
    scientific_object: Any = "",
) -> dict[str, Any]:
    """Normalize comparative inputs without leaking marker fragments as terms."""

    independent_text = _strip_question_prefix(independent_variable)
    declared_input_variable = _declared_input_without_inline_comparison(independent_text)
    comparison_values = _scope_policy_values([comparison_text, comparison_conditions, controls])
    comparison_source = " ".join(value for value in comparison_values if value)
    input_level_labels = _comparison_level_labels_from_text(independent_text)
    comparison_context_labels = _comparison_level_labels_from_text(comparison_source)
    labels = _unique(input_level_labels + comparison_context_labels)
    if not input_level_labels and comparison_source:
        cleaned_comparator = _clean_comparison_fragment(comparison_source)
        if cleaned_comparator and _is_baseline_or_comparator_anchor(cleaned_comparator):
            labels = _unique(labels + [cleaned_comparator])
    scientific_object_text = _normalize(scientific_object)
    levels: list[dict[str, Any]] = []
    baseline_levels: list[dict[str, Any]] = []
    for label in labels:
        cleaned_label = _clean_comparison_fragment(label)
        if not cleaned_label or _is_query_syntax_only_anchor(cleaned_label):
            continue
        level_terms = _comparison_level_terms(
            cleaned_label,
            declared_input_variable=declared_input_variable,
            scientific_object=scientific_object_text,
        )[:8]
        level_payload = {
            "label": cleaned_label,
            "terms": level_terms,
        }
        if _is_baseline_or_comparator_anchor(cleaned_label):
            baseline_levels.append({
                "label": cleaned_label,
                "terms": [cleaned_label],
            })
            continue
        levels.append(level_payload)
    non_baseline_terms = _unique(
        [str(level.get("label") or "") for level in levels]
        + [
            term
            for level in levels
            for term in _scope_policy_values(level.get("terms"))
        ]
    )[:32]
    baseline_terms = _unique(
        [str(level.get("label") or "") for level in baseline_levels]
        + [
            term
            for level in baseline_levels
            for term in _scope_policy_values(level.get("terms"))
        ]
        + [
            term
            for term in _scope_policy_values(comparison_values)
            if _is_baseline_or_comparator_anchor(term)
        ]
    )[:24]
    return {
        "schema_version": "structured_declared_input_comparison_v1",
        "declared_input_variable": declared_input_variable,
        "comparison_levels": levels[:8],
        "non_baseline_comparison_levels": levels[:8],
        "baseline_or_comparator_levels": baseline_levels[:8],
        "comparison_levels_as_declared_input": bool(input_level_labels),
        "comparison_level_terms": non_baseline_terms,
        "non_baseline_comparison_level_terms": non_baseline_terms,
        "baseline_or_comparator_terms": baseline_terms,
        "comparison_markers": list(_COMPARISON_MARKER_PHRASES),
        "fragment_cleanup_policy": (
            "comparison markers such as vs/versus are syntax only; they are "
            "not provider query terms or object anchors; baseline/control/"
            "counterfactual anchors are comparison context and cannot satisfy "
            "declared causal input"
        ),
    }


def _iter_scientific_object_alias_values(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple, set)):
        output: list[str] = []
        for item in value:
            output.extend(_iter_scientific_object_alias_values(item))
        return output
    if isinstance(value, dict):
        output: list[str] = []
        for key in (
            "anchor",
            "scientific_object",
            "object",
            "object_anchor",
            "canonical",
            "canonical_object",
            "alias",
            "aliases",
            "synonym",
            "synonyms",
            "mediator",
            "mediators",
            "modality",
            "modalities",
            "technology",
            "technologies",
            "method",
            "methods",
            "comparator",
            "comparators",
            "comparison",
            "boundary_condition",
            "boundary_conditions",
            "experimental_system",
            "experimental_systems",
            "strong_object_anchors",
            "supporting_concrete_objects",
            "exclusive_concrete_objects",
            "declared_exclusive_concrete_objects",
        ):
            if key in value:
                output.extend(_iter_scientific_object_alias_values(value.get(key)))
        return output
    return []


def _object_alias_candidate(value: Any, *, declared_object: str) -> str:
    normalized = _scientific_text_without_explanatory_alias_markers(value)
    if not normalized:
        return ""
    normalized = _normalize(_OBJECT_ALIAS_OPERATION_PREFIX_RE.sub("", normalized))
    if _is_query_syntax_only_anchor(normalized) or _is_baseline_or_comparator_anchor(normalized):
        return ""
    declared = _normalize(declared_object)
    if declared and declared.lower() in normalized.lower():
        # If a focus/retrieval sentence wraps the object in an effect clause,
        # keep the source-bound object span instead of manufacturing
        # cross-boundary phrases such as "<object> effectiveness" or
        # "generating <outcome>".
        return declared
    if _contains_comparison_marker(normalized):
        # ``A vs B`` / ``A compared with B`` expresses a research design or
        # comparison level, not an object identity.  Let structured comparison
        # terms carry it through the causal-input module instead of promoting
        # the whole retrieval sentence into an object anchor.
        return ""
    return normalized


def _object_alias_is_excluded(value: str, exclusions: list[str]) -> bool:
    normalized = _normalize(value).lower()
    if not normalized:
        return True
    for exclusion in exclusions:
        excluded = _normalize(exclusion).lower()
        if excluded and (normalized == excluded or normalized in excluded or excluded in normalized):
            return True
    return False


def _scope_policy_values(value: Any) -> list[str]:
    return [
        _normalize(item)
        for item in _iter_scientific_object_alias_values(value)
        if _normalize(item)
    ]


def _exclusion_variant_key(value: Any) -> str:
    text = _normalize(value).lower()
    text = (
        text.replace("\u2019", "'")
        .replace("\u2018", "'")
        .replace("\u2010", "-")
        .replace("\u2011", "-")
        .replace("\u2012", "-")
        .replace("\u2013", "-")
        .replace("\u2014", "-")
        .replace("\u2212", "-")
    )
    text = re.sub(r"\balzheimer[’']?s\b", "alzheimer", text)
    return _normalize(text)


def _exclusion_domain_tags(domain: Any) -> set[str]:
    text = _normalize(domain).lower()
    if not text:
        return set()
    tags: set[str] = set()
    if any(marker in text for marker in ("neuro", "brain", "cognitive")):
        tags.update({"neuro", "neuroscience", "biomedical", "life science"})
    if any(marker in text for marker in ("medicine", "medical", "clinical", "health", "disease")):
        tags.update({"medicine", "health", "clinical", "biomedical"})
    if any(marker in text for marker in ("psych", "psychiatry", "behavior", "behaviour")):
        tags.update({"psych", "psychology", "psychiatry", "biomedical"})
    if any(marker in text for marker in ("biology", "biomedical", "life science", "pharma")):
        tags.update({"biomedical", "life science"})
    return tags


def _orthographic_exclusion_variants(term: Any) -> list[str]:
    normalized = _normalize(term)
    if not normalized:
        return []
    variants = [
        normalized,
        normalized.replace("\u2019", "'").replace("\u2018", "'"),
        normalized.replace("'", "\u2019"),
        normalized.replace("-", " "),
        normalized.replace(" ", "-") if " " in normalized else normalized,
    ]
    lowered = _exclusion_variant_key(normalized)
    if lowered.endswith("ies"):
        variants.append(normalized[:-3] + "y")
    elif lowered.endswith("s") and len(lowered) > 4 and not lowered.endswith("ss"):
        variants.append(normalized[:-1])
    else:
        variants.append(normalized + "s")
    return _unique([_normalize(item) for item in variants if _normalize(item)])


def expand_exclusion_variants(term: Any, domain: Any = "") -> list[str]:
    """Return SH-local exclusion variants for query pruning and fast reject.

    The first layer is provider/domain-neutral orthographic normalization
    (apostrophes, hyphens, and simple number variants).  A small optional
    domain dictionary is used only when the excluded term itself names the
    concept or the declared domain is biomedical/clinical/neuroscience-like.
    This keeps the expansion SH-local instead of turning parent-project
    context into a global blacklist.
    """

    base_variants = _orthographic_exclusion_variants(term)
    key = _exclusion_variant_key(term)
    dictionary_entry = _EXCLUSION_VARIANT_DICTIONARY.get(key)
    if isinstance(dictionary_entry, dict) and dictionary_entry.get("alias_of"):
        dictionary_entry = _EXCLUSION_VARIANT_DICTIONARY.get(
            str(dictionary_entry.get("alias_of") or "")
        )
    expanded = list(base_variants)
    if isinstance(dictionary_entry, dict):
        domain_tags = set(dictionary_entry.get("domain_tags") or [])
        current_tags = _exclusion_domain_tags(domain)
        concept_named = bool(key in _EXCLUSION_VARIANT_DICTIONARY)
        if concept_named or not domain_tags or current_tags & domain_tags:
            expanded.extend(
                _normalize(item)
                for item in (dictionary_entry.get("variants") or [])
                if _normalize(item)
            )
    return _unique(expanded)[:32]


def provider_not_exclusion_variants(term: Any, domain: Any = "") -> list[str]:
    """High-precision subset of exclusion variants safe for provider NOT."""

    key = _exclusion_variant_key(term)
    dictionary_entry = _EXCLUSION_VARIANT_DICTIONARY.get(key)
    if isinstance(dictionary_entry, dict) and dictionary_entry.get("alias_of"):
        dictionary_entry = _EXCLUSION_VARIANT_DICTIONARY.get(
            str(dictionary_entry.get("alias_of") or "")
        )
    if isinstance(dictionary_entry, dict):
        domain_tags = set(dictionary_entry.get("domain_tags") or [])
        current_tags = _exclusion_domain_tags(domain)
        concept_named = bool(key in _EXCLUSION_VARIANT_DICTIONARY)
        if concept_named or not domain_tags or current_tags & domain_tags:
            values = dictionary_entry.get("provider_not_variants") or []
            return _unique(
                _normalize(item)
                for item in values
                if _normalize(item) and len(_exclusion_variant_key(item)) >= 3
            )[:24]
    return [
        item for item in _orthographic_exclusion_variants(term)
        if len(_exclusion_variant_key(item)) >= 3
    ][:12]


def expand_exclusion_variant_map(
    terms: Any,
    domain: Any = "",
    *,
    provider_not_only: bool = False,
) -> dict[str, list[str]]:
    output: dict[str, list[str]] = {}
    for term in _scope_policy_values(terms):
        variants = (
            provider_not_exclusion_variants(term, domain)
            if provider_not_only
            else expand_exclusion_variants(term, domain)
        )
        if variants:
            output[term] = variants
    return output


def _scope_term_matches_text(term: Any, text: Any) -> bool:
    needle = _exclusion_variant_key(term).replace("-", " ")
    haystack = _exclusion_variant_key(text).replace("-", " ")
    if not needle or not haystack:
        return False
    if " " in needle:
        return bool(re.search(rf"(?<![a-z0-9]){re.escape(needle)}(?![a-z0-9])", haystack))
    return bool(re.search(rf"(?<![a-z0-9]){re.escape(needle)}(?![a-z0-9])", haystack))


def _mixed_parent_preflight_from_project(project: dict[str, Any]) -> dict[str, Any]:
    for source in (
        project,
        project.get("academic_reframing") if isinstance(project.get("academic_reframing"), dict) else {},
        project.get("objective_decomposition") if isinstance(project.get("objective_decomposition"), dict) else {},
    ):
        if not isinstance(source, dict):
            continue
        preflight = source.get("mixed_parent_objective_preflight")
        if isinstance(preflight, dict):
            return preflight
    return {}


def _scope_forbidden_hits(value: Any, forbidden_terms: list[str]) -> list[str]:
    normalized = _normalize(value)
    if not normalized:
        return []
    hits: list[str] = []
    for term in forbidden_terms:
        clean = _normalize(term)
        if clean and _scope_term_matches_text(clean, normalized):
            hits.append(clean)
    return _unique(hits)


_SOFT_SINGLE_TOKEN_EXCLUSION_TERMS = frozenset({
    # Query/exclusion infrastructure must not turn broad scientific or prose
    # words into a hard blacklist.  These examples are intentionally
    # field-neutral: the same failure mode appears as "cell", "memory",
    # "storage", "source", "model", or "energy" depending on the discipline.
    "all", "were", "was", "been", "being", "estimated", "estimate",
    "estimates", "information", "source", "sources", "natural", "global",
    "field", "fields", "area", "areas", "type", "types", "level", "levels",
    "factor", "factors", "case", "cases", "term", "terms", "topic",
    "topics", "domain", "domains", "sample", "samples", "production",
    "environment", "environmental", "energy", "emission", "emissions",
    "storage", "sequestration", "formation", "method", "methods",
    "system", "systems", "model", "models", "process", "processes",
    "cell", "cells", "protein", "proteins", "signal", "signals",
    "memory", "memories", "rate", "effect", "effects", "change",
    "changes", "validation", "assessment", "analysis",
})


def _scope_term_overlaps_any(term: Any, values: list[str]) -> bool:
    normalized = _normalize(term)
    if not normalized:
        return False
    for value in values:
        other = _normalize(value)
        if not other:
            continue
        if (
            _scope_term_matches_text(normalized, other)
            or _scope_term_matches_text(other, normalized)
            or _object_phrase_overlap(normalized, other)
        ):
            return True
    return False


def _exclusion_term_can_hard_reject(
    term: Any,
    *,
    protected_positive_terms: list[str] | None = None,
) -> bool:
    """Return whether an exclusion term is safe for NOT/fast hard reject.

    Hard exclusion is intentionally conservative.  Single-token terms and
    low-specificity role words are kept as diagnostics/demotion signals only;
    they are not allowed to remove project context or reject provider results.
    """

    normalized = _normalize(term)
    if not normalized:
        return False
    protected = [
        _normalize(item)
        for item in (protected_positive_terms or [])
        if _normalize(item)
    ]
    if protected and _scope_term_overlaps_any(normalized, protected):
        return False
    tokens = _object_anchor_tokens(normalized)
    if len(tokens) < 2:
        return False
    lowered_tokens = [token.lower() for token in tokens]
    if all(
        token in _STOPWORDS
        or token in _LOW_SIGNAL
        or token in _PROJECT_ANCHOR_GLUE_TERMS
        or token in _RETRIEVAL_OBJECT_GENERIC_TERMS
        or token in _CORE_AXIS_GENERIC_TERMS
        or token in _SOFT_SINGLE_TOKEN_EXCLUSION_TERMS
        for token in lowered_tokens
    ):
        return False
    if is_component_bridge_modifier_only_anchor(normalized):
        return False
    return True


def _protected_positive_seed_values(
    *,
    project: dict[str, Any],
    project_card: dict[str, Any],
    sub_hypothesis: dict[str, Any],
) -> list[str]:
    sh = sub_hypothesis if isinstance(sub_hypothesis, dict) else {}
    raw_causal_contract = (
        sh.get("causal_contract")
        if isinstance(sh.get("causal_contract"), dict)
        else {}
    )
    object_maturity_audit = _object_maturity_audit_from_subhypothesis(sh)
    values: list[Any] = []
    for key in (
        "scientific_object",
        "scientific_object_aliases",
        "focus_anchor",
        "independent_variable",
        "dependent_variables",
        "causal_chain",
        "controls",
        "comparison",
        "comparison_conditions",
        "baseline_or_comparator",
        "moderators",
        "tradeoff_or_conflict",
        "counter_hypothesis",
        # Focus is weaker than the structured fields above, but it is often
        # the only place a normalized decomposition keeps the project-local
        # object identity (for example a comparator phrase).  Raw retrieval
        # queries are deliberately excluded: they may already be polluted.
        "focus",
    ):
        values.extend(_iter_scientific_object_alias_values(sh.get(key)))
    for key in (
        "pivotal_mechanism",
        "supporting_mediators",
        "outcome",
        "boundary_conditions",
        "confounders_or_alternatives",
    ):
        values.extend(_iter_scientific_object_alias_values(raw_causal_contract.get(key)))
    for path in sh.get("evidence_paths") or []:
        if not isinstance(path, dict):
            continue
        values.extend(_iter_scientific_object_alias_values(path.get("causal_steps")))
        values.extend(_iter_scientific_object_alias_values(path.get("component_anchor_group")))
    for key in (
        "object_anchors",
        "method_or_platform_anchors",
        "readout_anchors",
        "model_system_anchors",
    ):
        values.extend(_iter_scientific_object_alias_values(object_maturity_audit.get(key)))
    seed_values = _unique([
        _normalize(value)
        for value in values
        if _normalize(value)
    ])
    seed_terms = _unique(
        seed_values
        + [
            term
            for value in seed_values
            for term in _ranked_terms(value, limit=12)
            if term
        ]
        + [
            phrase
            for value in seed_values
            for phrase in _phrases(value, limit=8)
            if phrase
        ]
    )
    project_context_candidates: list[str] = []
    for container in (
        project.get("domain_context") if isinstance(project.get("domain_context"), dict) else {},
        project.get("research_identity") if isinstance(project.get("research_identity"), dict) else {},
        project_card if isinstance(project_card, dict) else {},
    ):
        if not isinstance(container, dict):
            continue
        for key in (
            "core_entities",
            "core_objects",
            "core_systems",
            "retrieval_terms",
            "retrieval_synonyms",
            "project_context_phrases",
            "project_context_anchor_terms",
        ):
            project_context_candidates.extend(_scope_policy_values(container.get(key)))
    for candidate in project_context_candidates:
        if _scope_term_overlaps_any(candidate, seed_terms):
            seed_terms.append(candidate)
            seed_terms.extend(_ranked_terms(candidate, limit=8))
            seed_terms.extend(_phrases(candidate, limit=4))
    return _unique(seed_terms)[:160]


def _classify_scope_exclusions(
    base_terms: list[str],
    *,
    domain: Any = "",
    protected_positive_terms: list[str] | None = None,
) -> dict[str, Any]:
    protected = _unique([
        _normalize(item)
        for item in (protected_positive_terms or [])
        if _normalize(item)
    ])
    hard_terms: list[str] = []
    fast_terms: list[str] = []
    soft_terms: list[str] = []
    conflict_terms: list[str] = []
    variant_map: dict[str, list[str]] = {}
    provider_not_map: dict[str, list[str]] = {}
    conflict_map: dict[str, list[str]] = {}
    soft_map: dict[str, list[str]] = {}
    for base in _scope_policy_values(base_terms):
        variants = _unique([base] + expand_exclusion_variants(base, domain))
        safe_variants: list[str] = []
        for variant in variants:
            normalized = _normalize(variant)
            if not normalized:
                continue
            if _scope_term_overlaps_any(normalized, protected):
                conflict_terms.append(normalized)
                conflict_map.setdefault(base, []).append(normalized)
                soft_terms.append(normalized)
                continue
            if not _exclusion_term_can_hard_reject(
                normalized,
                protected_positive_terms=protected,
            ):
                soft_terms.append(normalized)
                soft_map.setdefault(base, []).append(normalized)
                continue
            safe_variants.append(normalized)
            if _exclusion_variant_key(normalized) == _exclusion_variant_key(base):
                hard_terms.append(normalized)
            else:
                fast_terms.append(normalized)
        if safe_variants:
            variant_map[base] = _unique(safe_variants)[:16]
        provider_safe = [
            variant
            for variant in provider_not_exclusion_variants(base, domain)
            if _exclusion_term_can_hard_reject(
                variant,
                protected_positive_terms=protected,
            )
        ]
        if provider_safe:
            provider_not_map[base] = _unique(provider_safe)[:12]
    return {
        "hard_exclusion_terms": _unique(hard_terms)[:96],
        "fast_reject_terms": _unique(fast_terms)[:128],
        "soft_exclusion_terms": _unique(soft_terms)[:160],
        "scope_conflict_soft_terms": _unique(conflict_terms)[:96],
        "query_forbidden_terms": _unique(hard_terms + fast_terms)[:128],
        "query_forbidden_term_variants": {
            key: values[:16] for key, values in variant_map.items()
        },
        "provider_not_exclusion_variants": {
            key: values[:12] for key, values in provider_not_map.items()
        },
        "soft_exclusion_term_variants": {
            key: _unique(values)[:16] for key, values in soft_map.items()
        },
        "scope_conflict_soft_term_variants": {
            key: _unique(values)[:16] for key, values in conflict_map.items()
        },
        "protected_positive_terms": protected[:160],
    }


def protected_positive_terms_for_contract(
    contract: dict[str, Any] | None,
) -> list[str]:
    payload = contract if isinstance(contract, dict) else {}
    scope_policy = (
        payload.get("subhypothesis_scope_policy")
        if isinstance(payload.get("subhypothesis_scope_policy"), dict)
        else {}
    )
    object_policy = (
        payload.get("scientific_object_anchor_policy")
        if isinstance(payload.get("scientific_object_anchor_policy"), dict)
        else {}
    )
    return _unique(
        _scope_policy_values(scope_policy.get("protected_positive_terms"))
        + _scope_policy_values(object_policy.get("protected_positive_terms"))
        + _scope_policy_values(payload.get("protected_positive_terms"))
        + _scope_policy_values(payload.get("scientific_object_phrases"))
        + _scope_policy_values(payload.get("scientific_object_terms"))
        + _scope_policy_values(payload.get("input_phrases"))
        + _scope_policy_values(payload.get("input_terms"))
        + _scope_policy_values(payload.get("focal_variable_phrases"))
        + _scope_policy_values(payload.get("focal_variable_terms"))
        + _scope_policy_values(payload.get("mechanism_phrases"))
        + _scope_policy_values(payload.get("mechanism_terms"))
        + _scope_policy_values(payload.get("outcome_phrases"))
        + _scope_policy_values(payload.get("outcome_terms"))
        + _scope_policy_values(object_policy.get("object_group"))
        + _scope_policy_values(object_policy.get("component_bridge_object_anchor_phrases"))
        + _scope_policy_values(object_policy.get("component_bridge_method_or_platform_anchor_phrases"))
        + _scope_policy_values(object_policy.get("component_bridge_readout_anchor_phrases"))
        + _scope_policy_values(object_policy.get("component_bridge_model_system_anchor_phrases"))
    )[:192]


def exclusion_terms_by_confidence_for_contract(
    contract: dict[str, Any] | None,
    *,
    domain: Any = "",
) -> dict[str, Any]:
    payload = contract if isinstance(contract, dict) else {}
    scope_policy = (
        payload.get("subhypothesis_scope_policy")
        if isinstance(payload.get("subhypothesis_scope_policy"), dict)
        else {}
    )
    protected = protected_positive_terms_for_contract(payload)
    if (
        scope_policy.get("hard_exclusion_terms") is not None
        or scope_policy.get("fast_reject_terms") is not None
        or scope_policy.get("soft_exclusion_terms") is not None
    ):
        # Sibling SHs are not a vocabulary blacklist.  Older persisted
        # contracts may still carry ``sibling_scope_terms``; strip them from
        # every pre-retrieval exclusion channel instead of letting a legacy
        # term silently become a provider NOT clause or a fast reject.
        sibling_terms = _scope_policy_values(scope_policy.get("sibling_scope_terms"))
        sibling_terms.extend(
            _scope_policy_values(
                [
                    item.get("term")
                    for item in (
                    scope_policy.get("sibling_object_role_conflict_candidates")
                    or []
                )
                    if isinstance(item, dict)
                ]
            )
        )
        sibling_terms = _unique(sibling_terms)
        authoritative_exclusions = _scope_policy_values(
            scope_policy.get("authoritative_exclusion_terms")
        )
        def is_sibling_term(value: Any) -> bool:
            return bool(
                _scope_term_overlaps_any(value, sibling_terms)
                and not _scope_term_overlaps_any(value, authoritative_exclusions)
            )
        hard = [
            term for term in _scope_policy_values(scope_policy.get("hard_exclusion_terms"))
            if not is_sibling_term(term)
        ]
        demoted_fast = [
            term for term in _scope_policy_values(scope_policy.get("fast_reject_terms"))
            if is_sibling_term(term)
        ]
        fast = [
            term for term in _scope_policy_values(scope_policy.get("fast_reject_terms"))
            if not is_sibling_term(term)
        ]
        soft = _unique(
            [
                term
                for term in _scope_policy_values(scope_policy.get("soft_exclusion_terms"))
                if not is_sibling_term(term)
            ]
            + demoted_fast
        )
        conflicts = [
            term
            for term in _scope_policy_values(scope_policy.get("scope_conflict_soft_terms"))
            if not is_sibling_term(term)
        ]
        persisted_query_forbidden = [
            term
            for term in _scope_policy_values(scope_policy.get("query_forbidden_terms"))
            if not is_sibling_term(term)
        ]
        return {
            "hard_exclusion_terms": hard,
            "fast_reject_terms": fast,
            "soft_exclusion_terms": soft,
            "scope_conflict_soft_terms": conflicts,
            "query_forbidden_terms": _unique(
                persisted_query_forbidden
                or (hard + fast)
            )[:128],
            "protected_positive_terms": protected,
        }
    legacy_sibling_terms = _unique(
        _scope_policy_values(scope_policy.get("sibling_scope_terms"))
        + _scope_policy_values([
            item.get("term")
            for item in (
                scope_policy.get("sibling_object_role_conflict_candidates") or []
            )
            if isinstance(item, dict)
        ])
    )
    authoritative_exclusions = _scope_policy_values(
        scope_policy.get("authoritative_exclusion_terms")
    )
    base_terms = _scope_policy_values(
        list(payload.get("explicit_exclusion_terms") or [])
        + list(payload.get("excluded_nearby_objects") or [])
        + list(payload.get("query_forbidden_terms") or [])
        + list(scope_policy.get("query_forbidden_terms") or [])
    )
    if legacy_sibling_terms:
        base_terms = [
            term
            for term in base_terms
            if not (
                _scope_term_overlaps_any(term, legacy_sibling_terms)
                and not _scope_term_overlaps_any(term, authoritative_exclusions)
            )
        ]
    return _classify_scope_exclusions(
        base_terms,
        domain=domain,
        protected_positive_terms=protected,
    )


def _scope_value_has_validated_positive_provenance(
    value: Any,
    validated_positive_terms: list[str],
) -> bool:
    normalized = _normalize(value)
    if not normalized:
        return False
    return any(
        _object_phrase_overlap(normalized, declared)
        or _object_phrase_overlap(declared, normalized)
        for declared in validated_positive_terms
        if _normalize(declared)
    )


def _filter_values_against_scope_policy(
    values: list[str],
    scope_policy: dict[str, Any],
    *,
    source: str,
) -> tuple[list[str], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Apply SH scope isolation without turning soft lexical overlap into deletion.

    ``query_forbidden_terms`` have already passed the specific-entity safety
    check and may remove a context phrase. ``scope_conflict_soft_terms`` do
    not: they describe an unresolved explicit-scope collision that needs later
    alignment validation. Sibling SH objects are intentionally absent from
    this lexical path. Removing a parent context phrase merely because it
    contains a broad topical word loses retrieval recall and makes a soft
    diagnostic behave like a hard blacklist.
    """
    forbidden = [
        _normalize(item)
        for item in (scope_policy.get("query_forbidden_terms") or [])
        if _normalize(item)
    ]
    protected_conflict_terms = [
        _normalize(item)
        for item in (scope_policy.get("scope_conflict_soft_terms") or [])
        if _normalize(item)
    ]
    validated_positive_terms = [
        _normalize(item)
        for item in (scope_policy.get("validated_positive_anchor_terms") or [])
        if _normalize(item)
    ]
    kept: list[str] = []
    removed: list[dict[str, Any]] = []
    resolved: list[dict[str, Any]] = []
    risks: list[dict[str, Any]] = []
    for value in values:
        normalized = _normalize(value)
        if not normalized:
            continue
        hits = _scope_forbidden_hits(normalized, forbidden)
        if hits:
            removed.append({
                "term": normalized,
                "matched_forbidden_terms": hits[:8],
                "removed_from": source,
                "reason": "excluded_by_current_subhypothesis_scope",
            })
            continue
        conflict_hits = _scope_forbidden_hits(normalized, protected_conflict_terms)
        if conflict_hits:
            provenance_passes = _scope_value_has_validated_positive_provenance(
                normalized,
                validated_positive_terms,
            )
            if not provenance_passes:
                risks.append({
                    "term": normalized,
                    "matched_forbidden_terms": conflict_hits[:8],
                    "source": source,
                    "action": "kept_nonblocking_scope_risk",
                    "reason": "soft_scope_conflict_lacks_declared_or_canonical_provenance",
                })
            else:
                resolved.append({
                    "term": normalized,
                    "attempted_forbidden_terms": conflict_hits[:8],
                    "source": source,
                    "resolution": "kept_as_current_sh_positive_context",
                    "reason": "scope_conflict_resolved_by_current_sh_positive_anchor",
                })
        kept.append(normalized)
    return _unique(kept), removed, resolved, risks



def build_subhypothesis_scope_policy(
    project: dict[str, Any] | None,
    sub_hypothesis: dict[str, Any] | None,
    *,
    project_card: dict[str, Any] | None = None,
    excluded_nearby_objects: list[str] | None = None,
) -> dict[str, Any]:
    """Build SH-local scope guards before query/context anchor expansion."""

    project_payload = project if isinstance(project, dict) else {}
    sh = sub_hypothesis if isinstance(sub_hypothesis, dict) else {}
    card = project_card if isinstance(project_card, dict) else {}
    sub_id = str(sh.get("id") or sh.get("sub_hypothesis_id") or "").strip()
    scope_domain = _normalize(
        project_payload.get("domain")
        or card.get("domain")
        or card.get("primary_field")
        or sh.get("primary_field")
        or ""
    )
    current_values = _scope_policy_values([
        sh.get("focus"),
        sh.get("focus_anchor"),
        sh.get("scientific_object"),
        sh.get("scientific_object_aliases"),
        sh.get("independent_variable"),
        sh.get("dependent_variables"),
        sh.get("causal_chain"),
        sh.get("retrieval_query"),
        (sh.get("causal_contract") or {}).get("pivotal_mechanism")
        if isinstance(sh.get("causal_contract"), dict) else "",
        (sh.get("causal_contract") or {}).get("outcome")
        if isinstance(sh.get("causal_contract"), dict) else "",
    ])
    validated_positive_anchor_terms = _scope_policy_values([
        sh.get("scientific_object"),
        sh.get("scientific_object_aliases"),
        sh.get("independent_variable"),
        sh.get("dependent_variables"),
        (sh.get("causal_contract") or {}).get("pivotal_mechanism")
        if isinstance(sh.get("causal_contract"), dict) else "",
        (sh.get("causal_contract") or {}).get("outcome")
        if isinstance(sh.get("causal_contract"), dict) else "",
    ])
    current_text = _normalize(" ".join(current_values)).lower()
    allowed_scope_terms = _unique(current_values[:24])
    reconciliation = (
        sh.get("excluded_nearby_objects_reconciliation")
        if isinstance(sh.get("excluded_nearby_objects_reconciliation"), dict)
        else {}
    )
    protected_reconciled_exclusions = _scope_policy_values(
        reconciliation.get("removed_protected_context_exclusions")
    )
    declared_excluded_scope_terms = [
        item for item in _scope_policy_values(sh.get("declared_excluded_nearby_objects"))
        if not _scope_forbidden_hits(item, protected_reconciled_exclusions)
    ]
    # These terms were declared on the current SH, not inferred merely from a
    # sibling.  When they name a concrete entity/comparison system they retain
    # hard-exclusion eligibility even if that entity is also a sibling's
    # object.  Generic one-word terms are still demoted by the normal
    # confidence classifier below.
    authoritative_exclusion_terms = _unique(
        list(excluded_nearby_objects or [])
        + _scope_policy_values(sh.get("excluded_nearby_objects"))
        + declared_excluded_scope_terms
        + _scope_policy_values(sh.get("explicit_exclusion_terms"))
    )
    excluded_scope_terms = _unique(
        authoritative_exclusion_terms
        + _scope_policy_values(
            (sh.get("subhypothesis_scope_policy") or {}).get("excluded_scope_terms")
            if isinstance(sh.get("subhypothesis_scope_policy"), dict)
            else []
        )
    )

    # A sibling can contribute a *post-retrieval* role-conflict candidate only
    # when it explicitly owns a concrete object.  Its broad scientific
    # object, focus, aliases, and query language are shared context, not
    # forbidden vocabulary for the current SH.
    sibling_object_role_conflict_candidates: list[dict[str, str]] = []
    sibling_candidate_keys: set[tuple[str, str]] = set()
    for sibling in project_payload.get("sub_hypotheses") or []:
        if not isinstance(sibling, dict):
            continue
        sibling_id = str(sibling.get("id") or sibling.get("sub_hypothesis_id") or "").strip()
        if sub_id and sibling_id == sub_id:
            continue
        for source_field in (
            "exclusive_concrete_objects",
            "declared_exclusive_concrete_objects",
        ):
            for value in _scope_policy_values(sibling.get(source_field)):
                if (
                    not value
                    or not is_specific_object_anchor(value)
                    or any(_object_phrase_overlap(value, current) for current in current_values)
                ):
                    continue
                key = (sibling_id, value.lower())
                if key in sibling_candidate_keys:
                    continue
                sibling_candidate_keys.add(key)
                sibling_object_role_conflict_candidates.append({
                    "term": value,
                    "source_sh_id": sibling_id,
                    "source_field": source_field,
                    "enforcement": "post_retrieval_object_role_conflict_only",
                })

    other_parent_thread_terms: list[str] = []
    protected_parent_terms: list[str] = []
    mixed_preflight = _mixed_parent_preflight_from_project(project_payload)
    threads = mixed_preflight.get("detected_threads") if isinstance(mixed_preflight, dict) else []
    if mixed_preflight.get("mixed_parent_objective") and isinstance(threads, list):
        scored_threads: list[tuple[int, dict[str, Any]]] = []
        for thread in threads:
            if not isinstance(thread, dict):
                continue
            # Thread membership can use the broad thread vocabulary, but only
            # the thread's explicitly designated cross-thread exclusions can
            # later enter the negative retrieval scope.
            terms = _scope_policy_values(
                list(thread.get("core_terms") or [])
                + list(thread.get("query_forbidden_terms_if_other_thread") or [])
            )
            score = sum(1 for term in terms if _object_alias_is_excluded(term, [current_text]) or _object_alias_is_excluded(current_text, [term]))
            if not score:
                score = sum(1 for term in terms if term.lower() in current_text)
            scored_threads.append((score, thread))
        best_score = max([score for score, _thread in scored_threads] or [0])
        for score, thread in scored_threads:
            terms = _scope_policy_values(
                list(thread.get("core_terms") or [])
                + list(thread.get("query_forbidden_terms_if_other_thread") or [])
            )
            if best_score and score == best_score:
                protected_parent_terms.extend(terms)
            elif best_score:
                other_parent_thread_terms.extend(
                    term
                    for term in _scope_policy_values(
                        thread.get("query_forbidden_terms_if_other_thread")
                    )
                    # A mixed-thread detector may expose ranked words from a
                    # prose segment (for example ``deep`` or ``climate``).
                    # Those diagnose a possible parent-thread split, but are
                    # not a named foreign scientific object and must never
                    # enter negative retrieval scope.
                    if (
                        len(_object_anchor_tokens(term)) >= 2
                        and is_specific_object_anchor(term)
                    )
                )
        if other_parent_thread_terms:
            for declared_exclusion in _scope_policy_values(
                sh.get("declared_excluded_nearby_objects")
            ):
                if _scope_forbidden_hits(declared_exclusion, other_parent_thread_terms):
                    other_parent_thread_terms.append(declared_exclusion)

    # Persisted query-forbidden terms that lack an explicit current-SH or
    # foreign-parent provenance are deliberately not replayed.  They may have
    # been generated by the older sibling lexical blacklist and cannot be
    # safely promoted into a new provider query.
    legacy_unprovenanced_scope_terms = _scope_policy_values(
        (sh.get("subhypothesis_scope_policy") or {}).get("query_forbidden_terms")
        if isinstance(sh.get("subhypothesis_scope_policy"), dict)
        else []
    )
    base_query_forbidden_terms = _unique(
        excluded_scope_terms + other_parent_thread_terms
    )
    protected_positive_terms = _protected_positive_seed_values(
        project=project_payload,
        project_card=card,
        sub_hypothesis=sh,
    )
    exclusion_confidence = _classify_scope_exclusions(
        base_query_forbidden_terms,
        domain=scope_domain,
        protected_positive_terms=protected_positive_terms,
    )
    query_forbidden_terms = _unique(
        list(exclusion_confidence.get("query_forbidden_terms") or [])
    )
    return {
        "schema_version": SUBHYPOTHESIS_SCOPE_POLICY_VERSION,
        "sub_hypothesis_id": sub_id,
        "allowed_scope_terms": allowed_scope_terms[:32],
        "validated_positive_anchor_terms": _unique(validated_positive_anchor_terms)[:48],
        "excluded_scope_terms": excluded_scope_terms[:32],
        "authoritative_exclusion_terms": authoritative_exclusion_terms[:32],
        # Deprecated compatibility field.  It is intentionally empty: sibling
        # terms are no longer lexical exclusions in any retrieval stage.
        "sibling_scope_terms": [],
        "sibling_scope_policy": "post_retrieval_object_role_conflict_only",
        "sibling_object_role_conflict_candidates": (
            sibling_object_role_conflict_candidates[:32]
        ),
        "sibling_terms_demoted_from_fast_reject": [],
        "protected_parent_terms": _unique(protected_parent_terms)[:32],
        "other_parent_thread_terms": _unique(other_parent_thread_terms)[:32],
        "legacy_unprovenanced_scope_terms": legacy_unprovenanced_scope_terms[:32],
        "base_query_forbidden_terms": base_query_forbidden_terms[:64],
        "query_forbidden_terms": query_forbidden_terms[:96],
        "hard_exclusion_terms": list(exclusion_confidence.get("hard_exclusion_terms") or [])[:96],
        "fast_reject_terms": list(exclusion_confidence.get("fast_reject_terms") or [])[:96],
        "soft_exclusion_terms": list(exclusion_confidence.get("soft_exclusion_terms") or [])[:128],
        "scope_conflict_soft_terms": list(exclusion_confidence.get("scope_conflict_soft_terms") or [])[:96],
        "protected_positive_terms": list(exclusion_confidence.get("protected_positive_terms") or [])[:160],
        "query_forbidden_term_variants": {
            key: values[:16]
            for key, values in dict(
                exclusion_confidence.get("query_forbidden_term_variants") or {}
            ).items()
        },
        "provider_not_exclusion_variants": {
            key: values[:12]
            for key, values in dict(
                exclusion_confidence.get("provider_not_exclusion_variants") or {}
            ).items()
        },
        "soft_exclusion_term_variants": {
            key: values[:16]
            for key, values in dict(
                exclusion_confidence.get("soft_exclusion_term_variants") or {}
            ).items()
        },
        "scope_conflict_soft_term_variants": {
            key: values[:16]
            for key, values in dict(
                exclusion_confidence.get("scope_conflict_soft_term_variants") or {}
            ).items()
        },
        "mixed_parent_objective_detected": bool(mixed_preflight.get("mixed_parent_objective")),
        "mixed_parent_recommended_action": str(mixed_preflight.get("recommended_action") or ""),
        "context_removals": [],
        "context_conflict_resolutions": [],
        # Soft lexical overlap is diagnostic data, not an exclusion decision.
        # Keeping it in the policy lets later alignment distinguish a genuine
        # entity conflict from a broad shared domain word.
        "context_conflict_risks": [],
        "context_anchor_fallbacks": [],
        "project_id": str(card.get("project_id") or project_payload.get("project_id") or project_payload.get("id") or ""),
    }


def _candidate_alias_matches_declared(
    value: str,
    *,
    declared_object: str,
    allow_head_subtype: bool = True,
) -> bool:
    normalized = _normalize(value).lower()
    declared = _normalize(declared_object).lower()
    if not normalized:
        return False
    if not declared:
        return _is_strong_scientific_object_anchor(normalized, declared_single_object=False)
    if normalized == declared or declared in normalized:
        return True
    declared_tokens = _scientific_object_informative_tokens(declared)
    candidate_tokens = _scientific_object_informative_tokens(normalized)
    if len(set(declared_tokens) & set(candidate_tokens)) >= 2:
        return True
    declared_all = _object_anchor_tokens(declared)
    if allow_head_subtype and declared_all:
        head = declared_all[-1]
        head_variants = set(_object_anchor_tokens(" ".join(_final_noun_number_variants(head))))
        if set(_object_anchor_tokens(normalized)) & head_variants:
            modifiers = [
                token
                for token in candidate_tokens
                if token not in head_variants
                and token not in _OBJECT_ANCHOR_RELATIONAL_TERMS
                and token not in _PROJECT_ANCHOR_GLUE_TERMS
            ]
            if modifiers:
                return True
    return False


_PANEL_STRONG_MARKERS = (
    "panel", "multi-gene", "multigene", "multi gene", "multi-entity",
    "multi entity", "multi-omics", "multiomics", "multi omics",
    "multi-modal", "multimodal", "multi modal", "integrated",
    "integrative", "combinatorial", "combination", "composite",
    "signature", "feature set", "parameter set", "parameter combination",
    "critical process parameter", "process parameter", "workflow",
)
_PANEL_WEAK_MODEL_MARKERS = (
    "model", "predictor", "classifier", "score", "index", "algorithm",
)
_PANEL_COMPONENT_ROLE_MARKERS = (
    "support", "component", "mediator", "mechanism", "constraint",
    "deployment", "boundary", "context",
)
_PANEL_CORE_ROLE_MARKERS = (
    "core", "increment", "compar", "validation", "integrative",
    "integrated", "panel", "external", "adverse", "reversal",
    "opposing", "tradeoff", "trade-off", "rebound", "burden",
)
_PANEL_COMPONENT_GENERIC_TOKENS = frozenset({
    "activity", "altered", "assurance", "attribute", "attributes", "baseline",
    "candidate", "clinical", "cohort", "component", "condition", "conditions",
    "constraint", "constraints", "disposition", "dose", "dosing", "drug",
    "evidence", "exposure", "external", "feature", "features", "gene",
    "genes", "genotype", "integrated", "mechanism", "model", "multi",
    "omics", "outcome", "panel", "path", "pathway", "phenotype",
    "prediction", "predictive", "process", "quality", "release", "risk",
    "state", "support", "therapy", "toxicity", "validation", "variation",
    "workflow",
})


def _panel_marker_strength(text: str) -> str:
    normalized = _normalize(text).lower()
    if not normalized:
        return "none"
    if any(marker in normalized for marker in _PANEL_STRONG_MARKERS):
        return "strong"
    if any(marker in normalized for marker in _PANEL_WEAK_MODEL_MARKERS):
        return "weak"
    return "none"


def _evidence_path_panel_tier(path: dict[str, Any]) -> str:
    role = str(path.get("role") or path.get("id") or "").lower()
    path_id = str(path.get("id") or "").lower()
    text = f"{role} {path_id}"
    # Reviews/frameworks are context.  Boundary paths only become context when
    # they lack an explicit validation/comparison/incremental signal: an
    # "external_validation" path is panel-level evidence even if its role text
    # also says boundary.
    if any(marker in text for marker in ("background", "framework", "review")):
        return "context"
    if any(marker in text for marker in _PANEL_CORE_ROLE_MARKERS):
        return "core"
    if "context" in text or "boundary" in text:
        return "context"
    if any(marker in text for marker in ("support", "component", "constraint", "deployment")):
        return "support"
    return "support" if any(marker in text for marker in _PANEL_COMPONENT_ROLE_MARKERS) else "core"


def _panel_path_evidence_kind(
    *,
    tier: str,
    role: str,
    evidence_mode: str,
) -> str:
    normalized_role = str(role or "").lower()
    if "background" in normalized_role or "framework" in normalized_role:
        return "theoretical_framework"
    if any(marker in normalized_role for marker in ("adverse", "reversal", "opposing", "tradeoff", "trade-off", "rebound", "burden")):
        return "predictive_validation" if str(evidence_mode or "") == PREDICTIVE_GENERALIZATION_EVIDENCE_MODE else "causal_validation"
    if str(evidence_mode or "") == PREDICTIVE_GENERALIZATION_EVIDENCE_MODE:
        if tier == "core" or any(marker in normalized_role for marker in ("validation", "external", "compar")):
            return "predictive_validation"
        if "mechanism" in normalized_role or "component" in normalized_role:
            return "mechanism_discovery"
        return "association"
    if tier == "core":
        if "compar" in normalized_role:
            return "causal_identification"
        if "validation" in normalized_role or "core" in normalized_role:
            return "causal_validation"
        return "experimental_evidence"
    if "mechanism" in normalized_role or "component" in normalized_role:
        return "mechanism_discovery"
    return "association"


def panel_path_retrieval_layer_policy(
    *,
    tier: str,
    role: str = "",
    evidence_kind: str = "",
) -> dict[str, Any]:
    """Map a panel evidence path to retrieval layers without field patches.

    The mapping keeps retrieval broad enough to acquire full text, while
    preserving the later quality distinction: only integrative/panel-level
    paths can satisfy panel core quotas; component paths remain auxiliary.
    """

    normalized_tier = str(tier or "").strip().lower()
    normalized_role = str(role or "").strip().lower()
    normalized_kind = str(evidence_kind or "").strip().lower()
    role_text = f"{normalized_tier} {normalized_role} {normalized_kind}"

    panel_core_path = bool(
        normalized_tier == "core"
        or normalized_kind in {
            "predictive_validation",
            "causal_validation",
            "causal_identification",
            "experimental_evidence",
        }
        and any(
            marker in role_text
            for marker in (
                "core", "validation", "validated", "external", "compar",
                "increment", "integrat", "panel", "combination", "model",
            )
        )
    )
    if panel_core_path:
        preferred_layers = ["L2_top_latest", "L4_regular"]
        layer_role = "panel_level_core_validation"
    elif any(marker in role_text for marker in ("boundary", "generalization", "generalisation", "heterogeneity", "external")):
        preferred_layers = ["L2_top_latest", "L4_regular", "L0_review"]
        layer_role = "boundary_or_generalization"
    elif normalized_tier == "context" or any(
        marker in role_text for marker in ("background", "framework", "review")
    ):
        preferred_layers = ["L0_review", "L2_top_latest", "L4_regular"]
        layer_role = "context_or_boundary"
    else:
        preferred_layers = ["L4_regular", "L1_milestone", "L0_review"]
        layer_role = "component_auxiliary_support"

    return {
        "version": "panel_path_retrieval_layer_policy_v1",
        "retrieval_layer_role": layer_role,
        "preferred_retrieval_layers": preferred_layers,
        "preprint_signal_layers": ["L3_preprint"] if normalized_tier != "context" else [],
        "core_evidence_capable": panel_core_path,
        "panel_core_path": panel_core_path,
        "panel_component_path": not panel_core_path,
        "component_evidence_counts_as_core": False if not panel_core_path else None,
        "component_evidence_counts_as_panel_core": False if not panel_core_path else None,
        "preprints_count_toward_peer_reviewed_target": False,
    }


def _panel_component_anchor_candidates(value: Any) -> list[str]:
    normalized = _normalize(value)
    if not normalized:
        return []
    output: list[str] = []
    # Keep compact technical identifiers such as CYP2D6, SLCO1B1, UGT1A1,
    # BCR-ABL, ABCG2, but do not assume any one discipline.
    for match in re.findall(r"\b[A-Za-z]{1,16}[A-Za-z0-9+./-]*\d+[A-Za-z0-9+./-]*\b|\b[A-Z]{2,}(?:-[A-Za-z0-9]+)+\b", str(value or "")):
        if _looks_like_atomic_scientific_identifier(match):
            output.append(_normalize(match))
    tokens = [
        token
        for token in _ranked_terms(normalized, limit=10)
        if token.lower() not in _PANEL_COMPONENT_GENERIC_TOKENS
        and token.lower() not in _RETRIEVAL_OBJECT_GENERIC_TERMS
    ]
    for token in tokens:
        if _looks_like_atomic_scientific_identifier(token):
            output.append(token)
    if (
        len(_object_anchor_tokens(normalized)) >= 2
        and len(_object_anchor_tokens(normalized)) <= 7
        and _panel_marker_strength(normalized) == "none"
        and _is_strong_scientific_object_anchor(normalized)
    ):
        output.append(normalized)
    return _unique(output)


def build_multi_entity_panel_policy(
    *,
    declared_scientific_object: str,
    focus_text: str,
    evidence_paths: list[dict[str, Any]],
    supporting_mediators: list[str],
    raw_causal_contract: dict[str, Any],
    comparison_text: str = "",
    evidence_mode: str = "",
    scientific_object_anchor_policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Identify panel/integrated-object SHs without domain-specific patches.

    A panel SH has one panel-level object and several component or path-level
    mechanisms.  The component anchors are useful for recall and auxiliary
    evidence routing, but they are explicitly not allowed to prove the panel
    object or satisfy panel-level core evidence by themselves.
    """

    paths = [dict(path) for path in evidence_paths if isinstance(path, dict)]
    contract_text = " ".join(
        str(value or "")
        for value in (
            declared_scientific_object,
            focus_text,
            raw_causal_contract.get("pivotal_mechanism"),
            raw_causal_contract.get("core_evidence_definition"),
            raw_causal_contract.get("auxiliary_evidence_definition"),
            comparison_text,
        )
    )
    marker_strength = _panel_marker_strength(contract_text)
    component_sources: list[tuple[str, str]] = []
    for mediator in supporting_mediators:
        component_sources.append((mediator, "supporting_mediator"))
    path_policies: list[dict[str, Any]] = []
    for path in paths:
        tier = _evidence_path_panel_tier(path)
        role = str(path.get("role") or path.get("id") or "").strip()
        evidence_kind = _panel_path_evidence_kind(
            tier=tier,
            role=role,
            evidence_mode=evidence_mode,
        )
        layer_policy = panel_path_retrieval_layer_policy(
            tier=tier,
            role=role,
            evidence_kind=evidence_kind,
        )
        path_text = " ".join(
            str(value or "")
            for value in (
                path.get("id"),
                role,
                path.get("retrieval_query"),
                " ".join(str(step) for step in (path.get("causal_steps") or [])),
            )
        )
        path_components = _unique([
            anchor
            for anchor in _panel_component_anchor_candidates(path_text)
            if anchor
        ])
        if tier != "core":
            component_sources.extend((anchor, f"evidence_path:{role or path.get('id') or 'path'}") for anchor in path_components)
        path_policies.append({
            "id": str(path.get("id") or role or ""),
            "role": role,
            "panel_evidence_tier": tier,
            "evidence_kind": evidence_kind,
            "retrieval_layer_policy": layer_policy,
            "preferred_retrieval_layers": list(layer_policy.get("preferred_retrieval_layers") or []),
            "preprint_signal_layers": list(layer_policy.get("preprint_signal_layers") or []),
            "core_evidence_capable": bool(layer_policy.get("core_evidence_capable")),
            "panel_core_path": bool(layer_policy.get("panel_core_path")),
            "component_evidence_counts_as_core": layer_policy.get("component_evidence_counts_as_core"),
            "component_evidence_counts_as_panel_core": layer_policy.get("component_evidence_counts_as_panel_core"),
            "failure_scope": str(path.get("failure_scope") or ""),
            "can_independently_falsify_sh": bool(path.get("can_independently_falsify_sh")),
            "missing_path_blocks_sh": bool(path.get("missing_path_blocks_sh")),
            "retrieval_query": str(path.get("retrieval_query") or ""),
            "component_anchor_group": path_components[:16],
            "panel_level_core_required": tier == "core",
        })
    component_anchor_group = _unique([
        anchor
        for value, _source in component_sources
        for anchor in _panel_component_anchor_candidates(value)
        if anchor
    ])
    explicit_definitions = bool(
        raw_causal_contract.get("core_evidence_definition")
        or raw_causal_contract.get("auxiliary_evidence_definition")
    )
    has_path_split = len(paths) >= 2
    has_component_split = len(component_anchor_group) >= 2 or len(supporting_mediators) >= 2
    is_panel = bool(
        marker_strength == "strong"
        and (has_path_split or has_component_split or explicit_definitions)
    ) or bool(
        marker_strength == "weak"
        and has_path_split
        and has_component_split
    )
    object_policy = scientific_object_anchor_policy if isinstance(scientific_object_anchor_policy, dict) else {}
    panel_object_anchors = _unique([
        str(item)
        for item in (object_policy.get("object_group") or [])
        if str(item).strip()
    ])
    return {
        "version": "multi_entity_panel_policy_v1",
        "is_multi_entity_panel": is_panel,
        "panel_detection": {
            "marker_strength": marker_strength,
            "has_path_split": has_path_split,
            "has_component_split": has_component_split,
            "explicit_core_auxiliary_definitions": explicit_definitions,
        },
        "policy": (
            "panel object anchors prove panel identity; component anchors are "
            "auxiliary/support retrieval anchors and cannot independently "
            "satisfy panel-level core evidence"
        ),
        "panel_object_anchor_group": panel_object_anchors[:48],
        "component_anchor_group": component_anchor_group[:48],
        "component_sources": [
            {"anchor": anchor, "source": source}
            for value, source in component_sources
            for anchor in _panel_component_anchor_candidates(value)
        ][:48],
        "path_policies": path_policies[:12],
        "core_evidence_definition": str(raw_causal_contract.get("core_evidence_definition") or ""),
        "auxiliary_evidence_definition": str(raw_causal_contract.get("auxiliary_evidence_definition") or ""),
        "component_evidence_counts_as_core": False,
    }


_COMPARATIVE_OBJECT_CONTEXT_RE = re.compile(
    r"\b(?:vs\.?|versus|compared\s+with|compared\s+to|relative\s+to|"
    r"alternative(?:s)?|comparator|baseline|counterfactual)\b",
    flags=re.IGNORECASE,
)
_COMPARATIVE_OBJECT_SPLIT_RE = re.compile(
    r"\s+(?:vs\.?|versus|compared\s+with|compared\s+to|relative\s+to)\s+|\s+\band\b\s+",
    flags=re.IGNORECASE,
)


def _comparative_declared_object_parts(
    declared: str,
    *,
    focus_text: str = "",
    sub_hypothesis: dict[str, Any] | None = None,
) -> list[str]:
    """Split a comparative declared object into recall-safe component anchors.

    This activates only when the SH context itself says the relation is a
    comparison.  Generic conjunctive objects such as "gas and liquid interface"
    stay intact unless the surrounding SH declares vs/compared/baseline logic.
    """

    normalized = _normalize(declared)
    if not normalized:
        return []
    sh = sub_hypothesis if isinstance(sub_hypothesis, dict) else {}
    context_values: list[str] = [focus_text]
    for key in (
        "focus",
        "independent_variable",
        "comparison",
        "baseline_or_comparator",
        "counter_hypothesis",
        "falsification_condition",
    ):
        value = sh.get(key)
        if isinstance(value, str):
            context_values.append(value)
        elif isinstance(value, list):
            context_values.extend(str(item) for item in value if str(item).strip())
    context = _normalize(" ".join(context_values))
    has_explicit_splitter = bool(re.search(
        r"\b(?:vs\.?|versus|compared\s+with|compared\s+to|relative\s+to)\b",
        normalized,
        flags=re.IGNORECASE,
    ))
    if not has_explicit_splitter and not (
        " and " in f" {normalized.lower()} "
        and _COMPARATIVE_OBJECT_CONTEXT_RE.search(context)
    ):
        return []
    parts = [
        _normalize(part)
        for part in _COMPARATIVE_OBJECT_SPLIT_RE.split(normalized)
        if _normalize(part)
    ]
    parts = [
        part
        for part in parts
        if len(_object_anchor_tokens(part)) >= 1
        and _is_strong_scientific_object_anchor(part)
        and not _normalize(part).lower().startswith(("under ", "which ", "what "))
    ]
    if len(parts) < 2:
        return []
    return _unique(parts)[:6]


def build_scientific_object_anchor_policy(
    *,
    declared_scientific_object: str,
    scientific_object_text: str,
    focus_text: str = "",
    sub_hypothesis: dict[str, Any] | None = None,
    project: dict[str, Any] | None = None,
    project_card: dict[str, Any] | None = None,
    excluded_nearby_objects: list[str] | None = None,
) -> dict[str, Any]:
    """Build field-neutral strong/auxiliary anchors for one SH object.

    Strong anchors are object phrases or true atomic identifiers.  Single
    words carved out of a multi-word object are retained as auxiliary terms
    for ranking/diagnostics, but they cannot independently establish object
    identity in retrieval or source-bound evidence gates.
    """

    sh = dict(sub_hypothesis) if isinstance(sub_hypothesis, dict) else {}
    project_payload = project if isinstance(project, dict) else {}
    card = project_card if isinstance(project_card, dict) else {}
    object_maturity_audit = _object_maturity_audit_from_subhypothesis(sh)
    object_maturity_status = _object_maturity_status_from_audit(object_maturity_audit)
    direct_core_object_allowed = _object_maturity_direct_core_allowed(object_maturity_audit)
    preliminary_exclusions = [
        _normalize(item)
        for item in (excluded_nearby_objects or [])
        if _normalize(item)
    ]
    scope_policy = build_subhypothesis_scope_policy(
        project_payload,
        sh,
        project_card=card,
        excluded_nearby_objects=preliminary_exclusions,
    )
    typed_anchor_groups_declared = bool(
        object_maturity_audit.get("typed_component_bridge_anchors")
        or object_maturity_audit.get("component_bridge_anchor_quality")
        or object_maturity_audit.get("object_anchors")
        or object_maturity_audit.get("method_or_platform_anchors")
        or object_maturity_audit.get("readout_anchors")
        or object_maturity_audit.get("model_system_anchors")
    )
    typed_object_anchors = _object_maturity_anchor_values(
        object_maturity_audit,
        "object_anchors",
        limit=24,
    )
    maturity_component_anchors = (
        typed_object_anchors
        if typed_anchor_groups_declared
        else []
    )
    maturity_method_or_platform_anchors = _object_maturity_anchor_values(
        object_maturity_audit,
        "method_or_platform_anchors",
        limit=24,
    )
    maturity_readout_anchors = _object_maturity_anchor_values(
        object_maturity_audit,
        "readout_anchors",
        limit=16,
    )
    maturity_model_system_anchors = _object_maturity_anchor_values(
        object_maturity_audit,
        "model_system_anchors",
        limit=16,
    )
    maturity_bridge_anchors: list[str] = []
    maturity_boundary_anchors: list[str] = []
    maturity_component_anchors, removed_component_scope, resolved_component_scope, risk_component_scope = _filter_values_against_scope_policy(
        maturity_component_anchors,
        scope_policy,
        source="object_anchors",
    )
    removed_bridge_scope: list[dict[str, Any]] = []
    resolved_bridge_scope: list[dict[str, Any]] = []
    risk_bridge_scope: list[dict[str, Any]] = []
    removed_boundary_scope: list[dict[str, Any]] = []
    resolved_boundary_scope: list[dict[str, Any]] = []
    risk_boundary_scope: list[dict[str, Any]] = []
    maturity_method_or_platform_anchors, removed_method_scope, resolved_method_scope, risk_method_scope = _filter_values_against_scope_policy(
        maturity_method_or_platform_anchors,
        scope_policy,
        source="method_or_platform_anchors",
    )
    maturity_readout_anchors, removed_readout_scope, resolved_readout_scope, risk_readout_scope = _filter_values_against_scope_policy(
        maturity_readout_anchors,
        scope_policy,
        source="readout_anchors",
    )
    maturity_model_system_anchors, removed_model_scope, resolved_model_scope, risk_model_scope = _filter_values_against_scope_policy(
        maturity_model_system_anchors,
        scope_policy,
        source="model_system_anchors",
    )
    declaration_normalization = normalize_scientific_object_declaration(
        declared_scientific_object,
        context_values=_scientific_object_declaration_context_values(
            project=project_payload,
            project_card=card,
            sub_hypothesis=sh,
        ),
    )
    declared = _normalize(declaration_normalization.get("canonical"))
    recovered_declared, recovery_source = _recover_specific_scientific_object(
        declared=declared,
        project=project_payload,
        project_card=card,
        sub_hypothesis=sh,
    )
    if recovered_declared != declared:
        declaration_normalization = {
            **declaration_normalization,
            "original_canonical": declared,
            "canonical": recovered_declared,
            "recovered_from_generalized_declaration": bool(declared),
            "recovery_source": recovery_source,
        }
        declared = recovered_declared
    normalized_aliases = list(declaration_normalization.get("aliases") or [])
    if normalized_aliases:
        sh["scientific_object_aliases"] = _unique(
            _iter_scientific_object_alias_values(
                sh.get("scientific_object_aliases")
            )
            + normalized_aliases
        )
    scientific_object_text = _scientific_text_without_explanatory_alias_markers(
        scientific_object_text
    )
    focus_text = _scientific_text_without_explanatory_alias_markers(focus_text)
    exclusions = _unique(
        list(preliminary_exclusions)
        + [
            _normalize(item)
            for item in (scope_policy.get("query_forbidden_terms") or [])
            if _normalize(item)
        ]
    )
    declared_single = bool(declared and len(_object_anchor_tokens(declared)) == 1)
    alias_sources: list[tuple[str, str, bool, bool]] = []
    if declared and direct_core_object_allowed:
        alias_sources.append((declared, "declared_object", True, False))
    comparative_declared_object_parts = _comparative_declared_object_parts(
        declared,
        focus_text=focus_text,
        sub_hypothesis=sh,
    )
    if direct_core_object_allowed:
        alias_sources.extend(
            (part, "comparative_declared_object_part", True, True)
            for part in comparative_declared_object_parts
        )
    raw_context_anchor_values = _project_context_object_anchor_values(
        project=project_payload,
        project_card=card,
        sub_hypothesis=sh,
        evidence_paths=[
            path for path in (sh.get("evidence_paths") or [])
            if isinstance(path, dict)
        ],
    )
    context_anchor_values, removed_context_scope, resolved_context_scope, risk_context_scope = _filter_values_against_scope_policy(
        raw_context_anchor_values,
        scope_policy,
        source="project_context_terms",
    )
    # A valid SH must never lose every contextual retrieval anchor simply
    # because project-level context contained a specific, hard-excluded sibling
    # object.  Restore only the smallest declared/canonical positive anchors
    # that themselves do not hit the hard exclusion list.  This is deliberately
    # not a rollback of removed context: an excluded entity remains excluded.
    context_anchor_fallbacks: list[dict[str, Any]] = []
    has_validated_context_anchor = any(
        _scope_value_has_validated_positive_provenance(
            value,
            list(scope_policy.get("validated_positive_anchor_terms") or []),
        )
        for value in context_anchor_values
    )
    if raw_context_anchor_values and not has_validated_context_anchor:
        fallback_candidates = _unique(
            [declared]
            + list(declaration_normalization.get("aliases") or [])
            + list(scope_policy.get("validated_positive_anchor_terms") or [])
            + list(scope_policy.get("allowed_scope_terms") or [])
        )
        hard_forbidden_context_terms = list(scope_policy.get("query_forbidden_terms") or [])
        for candidate in fallback_candidates:
            normalized_candidate = _normalize(candidate)
            if not normalized_candidate:
                continue
            if _scope_forbidden_hits(normalized_candidate, hard_forbidden_context_terms):
                continue
            # The fallback is a parent/SH context anchor, rather than a bag of
            # generic tokens.  Atomic identifiers remain valid when declared.
            if (
                len(_object_anchor_tokens(normalized_candidate)) < 2
                and normalized_candidate != declared
            ):
                continue
            context_anchor_values.append(normalized_candidate)
            context_anchor_fallbacks.append({
                "term": normalized_candidate,
                "source": "declared_or_canonical_positive_anchor",
                "reason": "minimum_declared_or_canonical_context_restored_after_scope_filter",
            })
            if len(context_anchor_values) >= 2:
                break
    scope_policy = {
        **scope_policy,
        "context_removals": (
            removed_component_scope
            + removed_bridge_scope
            + removed_boundary_scope
            + removed_method_scope
            + removed_readout_scope
            + removed_model_scope
            + removed_context_scope
        )[:64],
        "context_conflict_resolutions": (
            resolved_component_scope
            + resolved_bridge_scope
            + resolved_boundary_scope
            + resolved_method_scope
            + resolved_readout_scope
            + resolved_model_scope
            + resolved_context_scope
        )[:64],
        "context_conflict_risks": (
            risk_component_scope
            + risk_bridge_scope
            + risk_boundary_scope
            + risk_method_scope
            + risk_readout_scope
            + risk_model_scope
            + risk_context_scope
        )[:64],
        "context_anchor_fallbacks": context_anchor_fallbacks[:8],
    }
    semantic_object_policy = _semantic_measurement_object_aliases(
        declared_object=declared,
        scientific_object_text=scientific_object_text,
        focus_text=focus_text,
        project_context_text=" ".join(context_anchor_values),
    )
    trusted_alias_keys = ("scientific_object_aliases",)
    if direct_core_object_allowed:
        for key in trusted_alias_keys:
            alias_sources.extend(
                (value, f"subhypothesis_{key}", True, True)
                for value in _iter_scientific_object_alias_values(sh.get(key))
            )
        alias_sources.extend(
            (value, "subhypothesis_strong_object_anchors", True, False)
            for value in _iter_scientific_object_alias_values(sh.get("strong_object_anchors"))
        )
        alias_sources.extend(
            (value, "focus_anchor", True, False)
            for value in _iter_scientific_object_alias_values(sh.get("focus_anchor"))
        )
        for value in (sh.get("query_variants") or []):
            if isinstance(value, str) and declared and declared.lower() in value.lower():
                alias_sources.append((value, "query_variant_contains_declared_object", True, False))
        for path in (sh.get("evidence_paths") or []):
            if not isinstance(path, dict):
                continue
            retrieval_query = str(path.get("retrieval_query") or "")
            if declared and declared.lower() in retrieval_query.lower():
                alias_sources.append((retrieval_query, "evidence_path_query_contains_declared_object", True, False))
    for container in (
        project_payload.get("domain_context") if isinstance(project_payload.get("domain_context"), dict) else {},
        project_payload.get("research_identity") if isinstance(project_payload.get("research_identity"), dict) else {},
        card,
    ):
        if not isinstance(container, dict):
            continue
        for key in ("core_entities", "retrieval_terms", "retrieval_synonyms", "project_context_phrases"):
            for value in _iter_scientific_object_alias_values(container.get(key)):
                normalized_value = _normalize(value)
                if not normalized_value:
                    continue
                hits = _scope_forbidden_hits(
                    normalized_value,
                    list(scope_policy.get("query_forbidden_terms") or []),
                )
                if hits:
                    removals = list(scope_policy.get("context_removals") or [])
                    removals.append({
                        "term": normalized_value,
                        "matched_forbidden_terms": hits[:8],
                        "removed_from": f"context_{key}",
                        "reason": "excluded_by_current_subhypothesis_scope",
                    })
                    scope_policy = {**scope_policy, "context_removals": removals[:64]}
                    continue
                conflict_hits = _scope_forbidden_hits(
                    normalized_value,
                    list(scope_policy.get("scope_conflict_soft_terms") or []),
                )
                if conflict_hits:
                    if _scope_value_has_validated_positive_provenance(
                        normalized_value,
                        list(scope_policy.get("validated_positive_anchor_terms") or []),
                    ):
                        resolutions = list(scope_policy.get("context_conflict_resolutions") or [])
                        resolutions.append({
                            "term": normalized_value,
                            "attempted_forbidden_terms": conflict_hits[:8],
                            "source": f"context_{key}",
                            "resolution": "kept_as_current_sh_positive_context",
                            "reason": "scope_conflict_resolved_by_current_sh_positive_anchor",
                        })
                        scope_policy = {
                            **scope_policy,
                            "context_conflict_resolutions": resolutions[:64],
                        }
                    else:
                        risks = list(scope_policy.get("context_conflict_risks") or [])
                        risks.append({
                            "term": normalized_value,
                            "matched_forbidden_terms": conflict_hits[:8],
                            "source": f"context_{key}",
                            "action": "kept_nonblocking_scope_risk",
                            "reason": "soft_scope_conflict_lacks_declared_or_canonical_provenance",
                        })
                        scope_policy = {
                            **scope_policy,
                            "context_conflict_risks": risks[:64],
                        }
                alias_sources.append((value, f"context_{key}", False, False))
    if focus_text and direct_core_object_allowed:
        alias_sources.append((focus_text, "focus_text", False, False))

    strong_phrases: list[str] = []
    strong_terms: list[str] = []
    alias_audit: list[dict[str, str]] = []

    def add_anchor(
        value: str,
        *,
        source: str,
        allow_head_subtype: bool,
        trusted_semantic_alias: bool = False,
    ) -> None:
        candidate = _object_alias_candidate(value, declared_object=declared)
        if not candidate or _object_alias_is_excluded(candidate, exclusions):
            return
        if (
            declared
            and not trusted_semantic_alias
            and not _candidate_alias_matches_declared(
            candidate,
            declared_object=declared,
            allow_head_subtype=allow_head_subtype,
            )
        ):
            return
        variants = _object_phrase_variants(candidate)
        for variant in _unique(variants):
            if _object_alias_is_excluded(variant, exclusions):
                continue
            if _is_strong_scientific_object_anchor(variant, declared_single_object=declared_single):
                if len(_object_anchor_tokens(variant)) == 1:
                    strong_terms.append(variant)
                else:
                    strong_phrases.append(variant)
                    alias_audit.append({
                        "anchor": variant,
                        "source": source,
                        "trusted_semantic_alias": str(bool(trusted_semantic_alias)).lower(),
                    })

    for value, source, allow_head_subtype, trusted_semantic_alias in alias_sources:
        add_anchor(
            str(value),
            source=source,
            allow_head_subtype=allow_head_subtype,
            trusted_semantic_alias=trusted_semantic_alias,
        )

    semantic_equivalent_phrases: list[str] = []
    semantic_equivalent_terms: list[str] = []
    for semantic_anchor in semantic_object_policy.get("semantic_equivalent_anchors") or []:
        for variant in _object_phrase_variants(semantic_anchor):
            if _object_alias_is_excluded(variant, exclusions):
                continue
            if not _is_strong_scientific_object_anchor(
                variant,
                declared_single_object=declared_single,
            ):
                continue
            if len(_object_anchor_tokens(variant)) == 1:
                semantic_equivalent_terms.append(variant)
            else:
                semantic_equivalent_phrases.append(variant)
                alias_audit.append({
                    "anchor": variant,
                    "source": "semantic_object_equivalence",
                })

    related_context_anchors: list[str] = []
    method_or_measurement_context = _is_measurement_or_method_object_text(
        " ".join((declared, scientific_object_text, focus_text, " ".join(context_anchor_values)))
    )
    if method_or_measurement_context:
        for anchor in list(semantic_object_policy.get("related_context_anchors") or []) + context_anchor_values:
            normalized_anchor = _normalize(anchor)
            if not normalized_anchor or _object_alias_is_excluded(normalized_anchor, exclusions):
                continue
            if _object_phrase_overlap(normalized_anchor, declared):
                continue
            if len(_object_anchor_tokens(normalized_anchor)) < 2:
                continue
            if not _is_strong_scientific_object_anchor(normalized_anchor):
                continue
            related_context_anchors.append(normalized_anchor)
    component_or_bridge_anchor_group = _unique(
        maturity_component_anchors
    )
    if not direct_core_object_allowed:
        related_context_anchors.extend(maturity_component_anchors)

    if not strong_phrases and declared and direct_core_object_allowed:
        # Last-resort preservation for a multi-word declared object.  It is
        # still source-bound later; this only avoids an empty contract.
        if _is_strong_scientific_object_anchor(declared, declared_single_object=declared_single):
            strong_phrases.append(declared)
            alias_audit.append({"anchor": declared, "source": "declared_object_fallback"})

    raw_auxiliary_terms = _unique(
        _ranked_terms(scientific_object_text, limit=32)
        + _ranked_terms(focus_text, limit=24)
    )
    strong_term_keys = {_normalize(term).lower() for term in strong_terms}
    phrase_component_terms = _unique([
        token
        for phrase in strong_phrases
        for token in _ranked_terms(phrase, limit=8)
    ])
    single_terms_not_sufficient = _unique([
        term
        for term in raw_auxiliary_terms + phrase_component_terms
        if _normalize(term).lower() not in strong_term_keys
    ])
    auxiliary_terms = _unique([
        term
        for term in single_terms_not_sufficient
        if (
            _normalize(term).lower() in _CONTEXT_WEAK_SINGLE_OBJECT_TERMS
            or not _looks_like_atomic_scientific_identifier(term)
            or not declared_single
        )
    ])
    strong_phrases = _unique(strong_phrases)
    strong_terms = _unique(strong_terms)
    semantic_equivalent_phrases = _unique(semantic_equivalent_phrases)
    semantic_equivalent_terms = _unique(semantic_equivalent_terms)
    related_context_anchors = _unique(related_context_anchors)
    object_group = _unique(
        ([] if not direct_core_object_allowed else comparative_declared_object_parts)
        + strong_phrases
        + strong_terms
        + semantic_equivalent_phrases
        + semantic_equivalent_terms
        + ([] if direct_core_object_allowed else maturity_component_anchors)
    )
    if scope_policy.get("context_removals"):
        removed_terms = _unique([
            str(item.get("term") or "")
            for item in (scope_policy.get("context_removals") or [])
            if isinstance(item, dict) and str(item.get("term") or "").strip()
        ])
        log_event(
            "SCIENCE",
            "subhypothesis_scope_context_exclusions_applied",
            project_id=str(scope_policy.get("project_id") or ""),
            sub_hypothesis_id=str(scope_policy.get("sub_hypothesis_id") or ""),
            removed_count=len(removed_terms),
            removed_term_sample=removed_terms[:5],
            source="sh_scope_isolation",
        )
    if scope_policy.get("context_conflict_resolutions"):
        log_event(
            "SCIENCE",
            "scope_exclusion_conflict_resolved",
            project_id=str(scope_policy.get("project_id") or ""),
            sub_hypothesis_id=str(scope_policy.get("sub_hypothesis_id") or ""),
            resolution_count=len(scope_policy.get("context_conflict_resolutions") or []),
            source="sh_scope_isolation",
        )
    if scope_policy.get("context_conflict_risks"):
        log_event(
            "SCIENCE",
            "subhypothesis_scope_context_soft_conflict_retained",
            project_id=str(scope_policy.get("project_id") or ""),
            sub_hypothesis_id=str(scope_policy.get("sub_hypothesis_id") or ""),
            retained_risk_count=len(scope_policy.get("context_conflict_risks") or []),
            source="sh_scope_isolation",
            policy="retain_soft_conflicts_for_post_retrieval_alignment",
        )
    if scope_policy.get("context_anchor_fallbacks"):
        log_event(
            "SCIENCE",
            "subhypothesis_scope_context_minimum_fallback_restored",
            project_id=str(scope_policy.get("project_id") or ""),
            sub_hypothesis_id=str(scope_policy.get("sub_hypothesis_id") or ""),
            restorations=list(scope_policy.get("context_anchor_fallbacks") or [])[:8],
            source="sh_scope_isolation",
        )
    return {
        "version": "scientific_object_anchor_policy_v2",
        "requires_specific_anchor": bool(declared or scientific_object_text),
        "policy": (
            "strong_phrase_or_atomic_identifier_required; single tokens from "
            "multi-word objects are auxiliary and cannot independently prove object identity; "
            "semantic-equivalent method aliases can establish retrieval identity; related-context "
            "anchors can only support auxiliary pending-fulltext admission"
        ),
        "object_maturity_status": object_maturity_status,
        "direct_core_object_allowed": direct_core_object_allowed,
        "direct_object_anchor_suppressed_by_maturity": bool(
            declared and not direct_core_object_allowed
        ),
        "component_or_bridge_anchor_phrases": [],
        "component_bridge_object_anchor_phrases": maturity_component_anchors[:24],
        "component_bridge_method_or_platform_anchor_phrases": maturity_method_or_platform_anchors[:24],
        "component_bridge_readout_anchor_phrases": maturity_readout_anchors[:16],
        "component_bridge_model_system_anchor_phrases": maturity_model_system_anchors[:16],
        "component_bridge_anchor_groups_typed": typed_anchor_groups_declared,
        "component_evidence_anchor_phrases": [],
        "translational_bridge_anchor_phrases": [],
        "boundary_or_safety_anchor_phrases": [],
        "strong_anchor_phrases": strong_phrases[:40],
        "strong_anchor_terms": strong_terms[:16],
        "semantic_equivalent_anchor_phrases": semantic_equivalent_phrases[:32],
        "semantic_equivalent_anchor_terms": semantic_equivalent_terms[:16],
        "semantic_object_equivalence_policy": semantic_object_policy,
        "comparative_declared_object_parts": comparative_declared_object_parts[:12],
        "related_context_anchor_phrases": related_context_anchors[:48],
        "object_group": object_group[:64],
        "subhypothesis_scope_policy": scope_policy,
        "query_forbidden_terms": list(scope_policy.get("query_forbidden_terms") or [])[:96],
        "query_forbidden_term_variants": dict(scope_policy.get("query_forbidden_term_variants") or {}),
        "provider_not_exclusion_variants": dict(scope_policy.get("provider_not_exclusion_variants") or {}),
        "scope_context_removals": list(scope_policy.get("context_removals") or [])[:64],
        "scope_conflict_resolutions": list(scope_policy.get("context_conflict_resolutions") or [])[:64],
        "scope_context_conflict_risks": list(scope_policy.get("context_conflict_risks") or [])[:64],
        "scope_context_anchor_fallbacks": list(scope_policy.get("context_anchor_fallbacks") or [])[:8],
        "protected_positive_terms": list(scope_policy.get("protected_positive_terms") or [])[:160],
        "hard_exclusion_terms": list(scope_policy.get("hard_exclusion_terms") or [])[:96],
        "fast_reject_terms": list(scope_policy.get("fast_reject_terms") or [])[:96],
        "soft_exclusion_terms": list(scope_policy.get("soft_exclusion_terms") or [])[:128],
        "scope_conflict_soft_terms": list(scope_policy.get("scope_conflict_soft_terms") or [])[:96],
        "auxiliary_terms": auxiliary_terms[:40],
        "single_terms_not_sufficient": single_terms_not_sufficient[:40],
        "generic_terms_not_sufficient": sorted(
            _RETRIEVAL_OBJECT_GENERIC_TERMS | _CONTEXT_WEAK_SINGLE_OBJECT_TERMS
        ),
        "specific_anchor_count": len(strong_phrases) + len(strong_terms),
        "alias_audit": alias_audit[:24],
        "declaration_normalization": declaration_normalization,
    }


def _retrieval_object_profiles_for_contract(
    sub_hypothesis: dict[str, Any],
    *,
    primary_object: str,
    primary_aliases: list[str],
    input_text: str,
    mechanism_text: str,
    outcome_text: str,
) -> list[dict[str, Any]]:
    """Normalize 1 primary plus up to 2 SH-local retrieval entry points.

    These profiles expand corpus recall through separate searches.  They are
    intentionally kept separate from ``scientific_object_anchor_policy`` so
    an input such as photon wavelength cannot impersonate the primary object
    during direct-core classification.
    """
    profiles: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add(value: Any, *, role: str, aliases: Any = (), source: str = "", core_capable: bool = False) -> None:
        anchor = _normalize(value)
        key = anchor.lower()
        if not anchor or not key or key in seen or len(anchor) < 3:
            return
        tokens = _query_word_tokens(anchor)
        if len(tokens) == 1 and tokens[0] in _RETRIEVAL_OBJECT_GENERIC_TERMS:
            return
        normalized_role = _normalize(role).lower()
        if normalized_role not in {
            "primary_system", "input_or_parameter", "mechanism_or_material",
            "model_or_platform", "measurement_or_readout",
        }:
            normalized_role = "mechanism_or_material"
        alias_values = _unique([
            _normalize(alias) for alias in _scope_policy_values(aliases)
            if _normalize(alias) and _normalize(alias).lower() != key
        ])[:6]
        profiles.append({
            "id": f"OBJ{len(profiles) + 1}",
            "object": anchor,
            "role": normalized_role,
            "aliases": alias_values,
            "query_anchor": anchor,
            "source": source,
            "core_capable": bool(core_capable),
        })
        seen.add(key)

    add(primary_object, role="primary_system", aliases=primary_aliases, source="scientific_object", core_capable=True)
    raw_profiles = sub_hypothesis.get("retrieval_object_profiles")
    for raw in raw_profiles if isinstance(raw_profiles, list) else []:
        if not isinstance(raw, dict) or len(profiles) >= 3:
            continue
        add(
            raw.get("query_anchor") or raw.get("object") or raw.get("anchor"),
            role=str(raw.get("role") or "mechanism_or_material"),
            aliases=raw.get("aliases") or [],
            source=str(raw.get("source") or "llm_declared"),
            # Only the primary identity may become core by default.  A
            # non-primary profile needs an explicit runtime contract later.
            core_capable=bool(raw.get("core_capable") is True and not profiles),
        )
    # New SHs are normalized upstream into 2-3 profiles.  Do not synthesize
    # extra profiles here for legacy/manual contracts: callers that explicitly
    # construct an old one-object contract must retain its original branch
    # count, and a migration must not unexpectedly multiply its provider load.
    return profiles[:3]


def _derive_scientific_object_identity_anchor(
    declared_object: str,
    declared_input: str,
    *,
    project: dict[str, Any],
    project_card: dict[str, Any],
) -> dict[str, Any]:
    """Separate a contextual object identity from a copied intervention.

    LLM decompositions sometimes declare values such as ``information density
    in quantum computing`` as the object while also declaring ``information
    density`` as the input.  The declaration is retained for auditability, but
    retrieval needs the residual system identity (``quantum computing``).
    This helper only removes literal declared input text or selects a
    project-context phrase already present in the current scope; it never
    invents a domain synonym.
    """

    raw_object = re.sub(r"\s+", " ", str(declared_object or "").strip())
    raw_input = re.sub(r"\s+", " ", str(declared_input or "").strip())

    def informative_tokens(value: str) -> list[str]:
        return [
            token.lower()
            for token in _TOKEN_RE.findall(value)
            if token.lower() not in _STOPWORDS and token.lower() not in _LOW_SIGNAL
        ]

    audit: dict[str, Any] = {
        "schema_version": "scientific_object_identity_anchor_v1",
        "declared_object": raw_object,
        "declared_input": raw_input,
        "method": "declared_object",
        "anchor": raw_object,
        "overlap_detected": False,
        "repair_required": False,
    }
    if not raw_object:
        audit.update({"anchor": "", "method": "missing", "repair_required": True})
        return audit
    if not raw_input:
        return audit

    object_key = " ".join(informative_tokens(raw_object))
    input_key = " ".join(informative_tokens(raw_input))
    exact_overlap = bool(
        input_key
        and (
            object_key == input_key
            or re.search(rf"\b{re.escape(raw_input)}\b", raw_object, flags=re.IGNORECASE)
        )
    )
    if not exact_overlap:
        return audit

    audit["overlap_detected"] = True
    residual = re.sub(
        rf"\b{re.escape(raw_input)}\b",
        " ",
        raw_object,
        flags=re.IGNORECASE,
    )
    residual = re.sub(r"\s+", " ", residual).strip(" ,;:/->")
    residual_tokens = informative_tokens(residual)
    if len(residual_tokens) >= 2:
        # Preserve the residual phrase's spelling while avoiding connector
        # words such as ``in`` that can become weak provider anchors.
        residual_anchor = " ".join(
            token for token in _TOKEN_RE.findall(residual)
            if token.lower() not in _STOPWORDS
        ).strip()
        if len(informative_tokens(residual_anchor)) >= 2:
            audit.update({
                "anchor": residual_anchor,
                "method": "remove_declared_input_from_object",
            })
            return audit

    # If the object is exactly the input, use only a compact, already-declared
    # project-context phrase.  The full objective sentence is intentionally
    # excluded because it is not a scientific object anchor.
    context_values: list[str] = []
    for source in (
        project_card.get("project_context_phrases"),
        project_card.get("project_context_anchor_terms"),
        project_card.get("project_context_anchor_phrases"),
    ):
        values = source if isinstance(source, (list, tuple, set)) else [source]
        context_values.extend(
            re.sub(r"\s+", " ", str(value or "").strip())
            for value in values
            if str(value or "").strip()
        )
    candidates: list[tuple[int, str]] = []
    for candidate in context_values:
        candidate_tokens = informative_tokens(candidate)
        if len(candidate_tokens) < 2 or len(candidate_tokens) > 6:
            continue
        if " ".join(candidate_tokens) == input_key:
            continue
        # Prefer phrases that are outside the input vocabulary and contain
        # more than a single generic field word.
        overlap_count = len(set(candidate_tokens) & set(input_key.split()))
        if overlap_count >= len(candidate_tokens):
            continue
        score = len(candidate_tokens) * 10 - overlap_count
        candidates.append((score, candidate))
    if candidates:
        candidates.sort(key=lambda item: (-item[0], item[1].lower()))
        audit.update({
            "anchor": candidates[0][1],
            "method": "declared_project_context_phrase",
        })
        return audit

    audit.update({
        "anchor": "",
        "method": "unresolved_object_input_overlap",
        "repair_required": True,
    })
    return audit


def build_subhypothesis_alignment_contract(
    project: dict[str, Any],
    sub_hypothesis: dict[str, Any],
    project_card: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the V2/V3 alignment envelope from a declared question contract.

    A retrieval alignment contract is no longer a generated causal graph.  A
    valid V2 research-question declaration supplies the gap-type priors,
    evidence slots, and scope axes used by V3 source admission.  A missing
    declaration remains explicitly blocked; this function never rebuilds a
    causal-chain fallback for a legacy SH.
    """
    card = dict(project_card or build_project_alignment_card(project))
    annotation = (
        sub_hypothesis.get("annotation")
        if isinstance(sub_hypothesis.get("annotation"), dict)
        else sub_hypothesis.get("hypothesis_annotation")
        if isinstance(sub_hypothesis.get("hypothesis_annotation"), dict)
        else {}
    )
    question_contract_raw = (
        sub_hypothesis.get("research_question_contract")
        if isinstance(sub_hypothesis.get("research_question_contract"), dict)
        else annotation.get("research_question_contract")
        if isinstance(annotation.get("research_question_contract"), dict)
        else {}
    )
    try:
        from ._research_question_contract import validate_research_question_contract
        from ._type_directed_evidence import evidence_profile_for_contract
    except ImportError:
        from _research_question_contract import validate_research_question_contract
        from _type_directed_evidence import evidence_profile_for_contract
    try:
        question_contract = validate_research_question_contract(question_contract_raw)
    except (TypeError, ValueError) as exc:
        return {
            "version": ALIGNMENT_VERSION,
            "status": "BLOCKED_V2_RESEARCH_QUESTION_CONTRACT_REQUIRED",
            "project_id": str(project.get("project_id") or card.get("project_id") or ""),
            "sub_hypothesis_id": str(sub_hypothesis.get("id") or sub_hypothesis.get("sub_hypothesis_id") or ""),
            "reason": f"current V2 research-question contract is required: {exc}",
            "type_directed_evidence_profile": {},
        }
    scope = (
        question_contract.get("scientific_scope")
        if isinstance(question_contract.get("scientific_scope"), dict)
        else {}
    )
    research_object = str(scope.get("research_object") or "").strip()
    return {
        "version": ALIGNMENT_VERSION,
        "status": "V2_V3_TYPE_DIRECTED_ALIGNMENT_CONTRACT",
        "project_id": str(project.get("project_id") or card.get("project_id") or ""),
        "project_version": card.get("project_version", 0),
        "alignment_card_hash": card.get("alignment_card_hash", ""),
        "sub_hypothesis_id": str(question_contract.get("sub_hypothesis_id") or sub_hypothesis.get("id") or ""),
        "contract_id": str(question_contract.get("contract_id") or ""),
        "contract_revision": str(question_contract.get("contract_revision") or question_contract.get("declaration_hash") or ""),
        "research_question": dict(question_contract.get("research_question") or {}),
        "evidence_contract": dict(question_contract.get("evidence_contract") or {}),
        "scientific_scope": dict(scope),
        "scientific_object": research_object,
        "scientific_object_phrases": [research_object] if research_object else [],
        "research_question_contract": question_contract,
        "type_directed_evidence_profile": evidence_profile_for_contract(question_contract),
        "direct_core_evidence_allowed": True,
        "evidence_path_policy": "type_directed_contract_slots_only",
        "legacy_causal_artifacts_status": "PROHIBITED_IN_V2_V3_ALIGNMENT",
    }

    # Unreachable: retained code below is being removed in the staged V2/V3
    # cutover.  The public builder above is the only executable route.
    causal_chain = sub_hypothesis.get("causal_chain")
    causal_steps = [str(item).strip() for item in causal_chain if str(item).strip()] if isinstance(causal_chain, list) else []
    raw_causal_contract = (
        sub_hypothesis.get("causal_contract")
        if isinstance(sub_hypothesis.get("causal_contract"), dict)
        else {}
    )
    pivotal_mechanism = str(raw_causal_contract.get("pivotal_mechanism") or "").strip()
    input_contract = (
        raw_causal_contract.get("input_contract")
        if isinstance(raw_causal_contract.get("input_contract"), dict)
        else {}
    )
    claim_layer_contract = (
        raw_causal_contract.get("claim_layer_contract")
        if isinstance(raw_causal_contract.get("claim_layer_contract"), dict)
        else {}
    )
    supporting_mediators = [
        str(item).strip()
        for item in (raw_causal_contract.get("supporting_mediators") or [])
        if str(item).strip()
    ]
    input_text = " ".join(
        part for part in (
            str(sub_hypothesis.get("independent_variable") or ""),
        ) if part
    )
    # Core admission follows the pivotal edge, not an accidental conjunction
    # of every bridge mediator in a long generated chain.  Supporting
    # mediators remain visible in the contract for corpus-level synthesis.
    mechanism_text = pivotal_mechanism
    dependent_variable_text = " ".join(
        str(item) for item in (sub_hypothesis.get("dependent_variables") or [])
        if str(item).strip()
    )
    # The explicitly declared causal-contract outcome is the canonical
    # endpoint for retrieval and core-axis alignment.  Missing outcome values
    # are contract defects: do not recover them from dependent variables or
    # terminal legacy causal-chain steps.
    outcome_primary_text = str(
        claim_layer_contract.get("local_empirical_outcome")
        or raw_causal_contract.get("outcome")
        or ""
    ).strip()
    outcome_text = " ".join(
        part for part in (
            outcome_primary_text,
            str(sub_hypothesis.get("falsification_condition") or ""),
        ) if part
    )
    focus_text = " ".join(
        str(sub_hypothesis.get(key) or "")
        for key in ("focus", "retrieval_query", "source_objective")
    )
    explicit_declared_scientific_object = str(
        sub_hypothesis.get("scientific_object") or ""
    ).strip()
    raw_declared_scientific_object = explicit_declared_scientific_object
    scientific_object_normalization = normalize_scientific_object_declaration(
        raw_declared_scientific_object,
        context_values=[],
    )
    declared_scientific_object = str(
        scientific_object_normalization.get("canonical") or ""
    ).strip()
    if not declared_scientific_object:
        scientific_object_normalization = {
            **scientific_object_normalization,
            "missing_required_declaration": True,
            "recovery_source": "disabled_legacy_object_recovery",
        }
    scientific_object_identity_audit = _derive_scientific_object_identity_anchor(
        declared_scientific_object,
        input_text,
        project=project,
        project_card=card,
    )
    scientific_object_identity_anchor = str(
        scientific_object_identity_audit.get("anchor") or ""
    ).strip()
    normalized_sub_hypothesis = dict(sub_hypothesis)
    if scientific_object_normalization.get("aliases"):
        normalized_sub_hypothesis["scientific_object_aliases"] = _unique(
            _iter_scientific_object_alias_values(
                sub_hypothesis.get("scientific_object_aliases")
            )
            + list(scientific_object_normalization.get("aliases") or [])
        )
    scientific_object_text = " ".join(
        value
        for value in (
            declared_scientific_object,
            _scientific_text_without_explanatory_alias_markers(
                sub_hypothesis.get("focus")
            ),
        )
        if value
    )
    primary_field = str(
        sub_hypothesis.get("primary_field")
        or project.get("declared_domain")
        or project.get("domain")
        or ""
    ).strip()
    adjacent_fields = [
        str(item).strip()
        for item in (sub_hypothesis.get("adjacent_fields") or [])
        if str(item).strip()
    ]
    excluded_nearby_objects = [
        str(item).strip()
        for item in (sub_hypothesis.get("excluded_nearby_objects") or [])
        if str(item).strip()
    ]
    declared_excluded_nearby_objects = list(excluded_nearby_objects)
    try:
        from ._project import (
            ensure_core_adverse_boundary_evidence_paths,
            normalize_evidence_paths,
        )
        from ._epistemic_profile import normalize_epistemic_profile
        from ._evidence_roles import normalize_evidence_role_contract
    except ImportError:
        from _project import (
            ensure_core_adverse_boundary_evidence_paths,
            normalize_evidence_paths,
        )
        from _epistemic_profile import normalize_epistemic_profile
        from _evidence_roles import normalize_evidence_role_contract
    evidence_paths = normalize_evidence_paths(
        sub_hypothesis.get("evidence_paths"),
        focus=str(sub_hypothesis.get("focus") or ""),
        causal_chain=causal_steps,
        fallback_query=str(sub_hypothesis.get("retrieval_query") or sub_hypothesis.get("focus") or ""),
    )
    annotation = (
        sub_hypothesis.get("annotation")
        if isinstance(sub_hypothesis.get("annotation"), dict)
        else sub_hypothesis.get("hypothesis_annotation")
        if isinstance(sub_hypothesis.get("hypothesis_annotation"), dict)
        else {}
    )
    raw_epistemic_profile = (
        sub_hypothesis.get("epistemic_profile")
        or annotation.get("epistemic_profile")
    )
    epistemic_profile = (
        normalize_epistemic_profile(
            raw_epistemic_profile,
            project=project,
            fallback_text=" ".join(
                str(sub_hypothesis.get(key) or "")
                for key in ("focus", "scientific_object", "causal_chain", "causal_contract", "evidence_paths", "declared_research_mode")
            ),
        )
        if isinstance(raw_epistemic_profile, dict)
        else None
    )
    evidence_role_contract = normalize_evidence_role_contract(
        sub_hypothesis.get("evidence_role_contract"),
        epistemic_profile=epistemic_profile,
        evidence_paths=evidence_paths,
    )
    role_contract_for_paths = (
        evidence_role_contract
        if isinstance(sub_hypothesis.get("evidence_role_contract"), dict)
        else None
    )
    try:
        from ._evidence_standards import (
            evidence_standard_retrieval_policy,
            normalize_evidence_standard_id,
        )
    except ImportError:
        from _evidence_standards import (
            evidence_standard_retrieval_policy,
            normalize_evidence_standard_id,
        )
    standard_id = normalize_evidence_standard_id(
        annotation.get("evidence_standard_id")
        or sub_hypothesis.get("evidence_standard_hint"),
        hypothesis_type=str(annotation.get("hypothesis_type") or sub_hypothesis.get("hypothesis_type") or ""),
    )
    evidence_standard_policy = evidence_standard_retrieval_policy(
        standard_id,
        hypothesis_type=str(annotation.get("hypothesis_type") or sub_hypothesis.get("hypothesis_type") or ""),
    )
    local_edge_standard_ids = _unique(
        [
            standard_id,
            *(
                list(epistemic_profile.get("evidence_standard_ids") or [])
                if isinstance(epistemic_profile, dict) else []
            ),
        ]
    )
    local_edge_accepted_designs: list[str] = []
    for local_standard_id in local_edge_standard_ids:
        local_policy = evidence_standard_retrieval_policy(
            local_standard_id,
            hypothesis_type=str(annotation.get("hypothesis_type") or sub_hypothesis.get("hypothesis_type") or ""),
        )
        local_edge_accepted_designs.extend(
            str(item) for item in (local_policy.get("accepted_core_designs") or []) if str(item)
        )
    evidence_standard = {
        "id": standard_id,
        "hypothesis_type": str(annotation.get("hypothesis_type") or sub_hypothesis.get("hypothesis_type") or ""),
        "accepted_core_designs": list(evidence_standard_policy.get("accepted_core_designs") or []),
        "local_edge_accepted_core_designs": _unique(local_edge_accepted_designs),
        "local_edge_evidence_standard_ids": local_edge_standard_ids,
        "support_designs": list(evidence_standard_policy.get("support_designs") or []),
        "required_properties": list(evidence_standard_policy.get("required_properties") or []),
        "preferred_properties": list(evidence_standard_policy.get("preferred_properties") or []),
        "not_sufficient_alone": list(evidence_standard_policy.get("not_sufficient_alone") or []),
        "excluded_as_core": ["narrative_review", "commentary", "preprint_only"],
        "claim_strength_cap": str(evidence_standard_policy.get("claim_strength_cap") or ""),
        "claim_strength_notes": str(evidence_standard_policy.get("claim_strength_notes") or ""),
    }
    evidence_mode = infer_subhypothesis_evidence_mode(sub_hypothesis)
    moderator_source = " ".join(
        value
        for value in (
            focus_text,
            input_text,
            outcome_text,
            " ".join(str(item) for item in (sub_hypothesis.get("moderators") or []) if str(item).strip()),
        )
        if value
    )
    moderator_terms = (
        predictive_generalization_moderator_terms(moderator_source)
        if evidence_mode == PREDICTIVE_GENERALIZATION_EVIDENCE_MODE
        else []
    )
    # The normal axis term sets remain deliberately broad for discovery.  A
    # direct-core claim needs a second, stricter representation that is tied
    # to the named focal variable and does not recycle generic or upstream
    # terms as a downstream result.  This is a retrieval/alignment policy,
    # not a change to the SH's scientific claim.
    focal_variable_source = str(sub_hypothesis.get("independent_variable") or "")
    focal_variable = _focal_variable_text(
        _declared_input_without_inline_comparison(focal_variable_source)
    )
    focal_variable_terms = _core_axis_terms(focal_variable)
    # The compact focal variable deliberately removes a trailing context for
    # term-level matching (for example, ``exposure in a defined system`` ->
    # ``exposure``).  That compact form must not also erase the declared
    # multi-word input from the phrase-level contract: its setting/condition
    # can be what makes an exposure, parameter, or comparison retrievable and
    # distinguishable.  Terms remain compact; phrases preserve the declared
    # input wording and are evaluated separately by the contract gate.
    focal_variable_phrases = _core_axis_phrases(
        focal_variable_source or focal_variable,
        focal_variable_terms,
    )
    mechanism_core_terms = _core_axis_terms(
        mechanism_text,
        excluded_terms=focal_variable_terms,
    )
    mechanism_core_phrases = _core_axis_phrases(mechanism_text, mechanism_core_terms)
    outcome_core_terms = _core_axis_terms(
        outcome_primary_text,
        excluded_terms=_unique(focal_variable_terms + mechanism_core_terms),
    )
    outcome_core_phrases = _core_axis_phrases(outcome_primary_text, outcome_core_terms)
    mechanism_outcome_dictionary = build_mechanism_outcome_synonym_dictionary(
        mechanism_text=mechanism_text,
        outcome_text=outcome_primary_text,
        dependent_variables=[
            str(item)
            for item in (sub_hypothesis.get("dependent_variables") or [])
            if str(item).strip()
        ],
        causal_steps=causal_steps,
        primary_field=primary_field,
    )
    # Some older or manually supplied SH payloads express comparisons as a
    # list.  Convert them to the same declared text used by normalized SHs;
    # ``str([..])`` would leak brackets/quotes into retrieval anchors and make
    # an otherwise valid comparison impossible to audit consistently.
    def _declared_comparison_text(value: Any) -> str:
        if isinstance(value, (list, tuple)):
            return " ".join(str(item).strip() for item in value if str(item).strip())
        return str(value or "").strip()

    comparison_text = _declared_comparison_text(
        sub_hypothesis.get("comparison") or sub_hypothesis.get("control_condition")
    )
    comparison_conditions_text = _declared_comparison_text(
        sub_hypothesis.get("comparison_conditions")
    )
    comparison_source = " ".join(
        value for value in (
            comparison_text,
            comparison_conditions_text,
            " ".join(str(item) for item in (sub_hypothesis.get("controls") or []) if str(item).strip()),
        ) if value
    )
    structured_declared_input = build_structured_declared_input_comparison(
        independent_variable=sub_hypothesis.get("independent_variable") or "",
        comparison_text=comparison_text,
        comparison_conditions=comparison_conditions_text,
        controls=sub_hypothesis.get("controls") or [],
        scientific_object=declared_scientific_object or scientific_object_text,
    )
    boundary_source = raw_causal_contract.get("boundary_conditions") or sub_hypothesis.get("moderators") or []
    boundary_values = (
        list(boundary_source)
        if isinstance(boundary_source, (list, tuple, set))
        else [boundary_source]
    )
    evidence_paths = ensure_core_adverse_boundary_evidence_paths(
        evidence_paths,
        focus=str(sub_hypothesis.get("focus") or ""),
        scientific_object=declared_scientific_object,
        independent_variable=str(sub_hypothesis.get("independent_variable") or ""),
        causal_chain=causal_steps,
        dependent_variables=[
            str(item)
            for item in (sub_hypothesis.get("dependent_variables") or [])
            if str(item).strip()
        ],
        comparison=comparison_source,
        boundary_conditions=[str(item).strip() for item in boundary_values if str(item).strip()],
        fallback_query=str(sub_hypothesis.get("retrieval_query") or sub_hypothesis.get("focus") or ""),
        epistemic_profile=epistemic_profile,
        evidence_role_contract=role_contract_for_paths,
    )
    protected_context_anchors = _protected_positive_seed_values(
        project=project,
        project_card=card,
        sub_hypothesis={
            **normalized_sub_hypothesis,
            "evidence_paths": evidence_paths,
            "object_maturity_preflight": sub_hypothesis.get("object_maturity_preflight"),
        },
    )
    excluded_nearby_objects, exclusion_reconciliation = (
        _filter_excluded_nearby_objects_against_protected_context(
            excluded_nearby_objects,
            protected_context_anchors=protected_context_anchors,
        )
        if excluded_nearby_objects
        else (
            excluded_nearby_objects,
            {
                "schema_version": "excluded_context_reconciliation_v1",
                "removed_protected_context_exclusions": [],
                "matched_protected_context_anchors": {},
                "remaining_excluded_nearby_objects": excluded_nearby_objects,
            },
        )
    )
    if exclusion_reconciliation.get("removed_protected_context_exclusions"):
        log_event(
            "SCIENCE",
            "subhypothesis_excluded_context_reconciled",
            project_id=str(card.get("project_id") or ""),
            sub_hypothesis_id=str(sub_hypothesis.get("id") or ""),
            removed=exclusion_reconciliation.get("removed_protected_context_exclusions"),
            remaining=excluded_nearby_objects,
        )
    normalized_sub_hypothesis["excluded_nearby_objects"] = list(excluded_nearby_objects)
    normalized_sub_hypothesis["declared_excluded_nearby_objects"] = declared_excluded_nearby_objects
    normalized_sub_hypothesis["excluded_nearby_objects_reconciliation"] = exclusion_reconciliation
    scientific_object_anchor_policy = build_scientific_object_anchor_policy(
        declared_scientific_object=declared_scientific_object,
        scientific_object_text=scientific_object_text,
        focus_text=focus_text,
        sub_hypothesis=normalized_sub_hypothesis,
        project=project,
        project_card=card,
        excluded_nearby_objects=excluded_nearby_objects,
    )
    subhypothesis_scope_policy = (
        scientific_object_anchor_policy.get("subhypothesis_scope_policy")
        if isinstance(scientific_object_anchor_policy.get("subhypothesis_scope_policy"), dict)
        else {}
    )
    query_forbidden_terms = _unique(
        [
            _normalize(item)
            for item in (
                list(subhypothesis_scope_policy.get("query_forbidden_terms") or [])
                + list(scientific_object_anchor_policy.get("query_forbidden_terms") or [])
            )
            if _normalize(item)
        ]
    )[:96]
    project_context_scope_removals = list(
        subhypothesis_scope_policy.get("context_removals") or []
    )
    project_context_scope_resolutions = list(
        subhypothesis_scope_policy.get("context_conflict_resolutions") or []
    )
    project_context_scope_risks = list(
        subhypothesis_scope_policy.get("context_conflict_risks") or []
    )

    def _scope_filtered_contract_context(values: Any, *, source: str) -> list[str]:
        kept: list[str] = []
        nonlocal project_context_scope_removals, project_context_scope_resolutions, project_context_scope_risks
        for value in _scope_policy_values(values):
            hits = _scope_forbidden_hits(value, query_forbidden_terms)
            if hits:
                project_context_scope_removals.append({
                    "term": value,
                    "matched_forbidden_terms": hits[:8],
                    "removed_from": source,
                    "reason": "excluded_by_current_subhypothesis_scope",
                })
                continue
            conflict_hits = _scope_forbidden_hits(
                value,
                list(subhypothesis_scope_policy.get("scope_conflict_soft_terms") or []),
            )
            if conflict_hits:
                if _scope_value_has_validated_positive_provenance(
                    value,
                    list(subhypothesis_scope_policy.get("validated_positive_anchor_terms") or []),
                ):
                    project_context_scope_resolutions.append({
                        "term": value,
                        "attempted_forbidden_terms": conflict_hits[:8],
                        "source": source,
                        "resolution": "kept_as_current_sh_positive_context",
                        "reason": "scope_conflict_resolved_by_current_sh_positive_anchor",
                    })
                else:
                    project_context_scope_risks.append({
                        "term": value,
                        "matched_forbidden_terms": conflict_hits[:8],
                        "source": source,
                        "action": "kept_nonblocking_scope_risk",
                        "reason": "soft_scope_conflict_lacks_declared_or_canonical_provenance",
                    })
            kept.append(value)
        return _unique(kept)

    filtered_project_context_anchor_terms = _scope_filtered_contract_context(
        card.get("project_context_anchor_terms"),
        source="contract_project_context_anchor_terms",
    )
    filtered_project_context_phrases = _scope_filtered_contract_context(
        card.get("project_context_phrases"),
        source="contract_project_context_phrases",
    )
    if project_context_scope_removals != list(subhypothesis_scope_policy.get("context_removals") or []):
        subhypothesis_scope_policy = {
            **subhypothesis_scope_policy,
            "context_removals": project_context_scope_removals[:64],
        }
        scientific_object_anchor_policy = {
            **scientific_object_anchor_policy,
            "subhypothesis_scope_policy": subhypothesis_scope_policy,
            "scope_context_removals": project_context_scope_removals[:64],
        }
    if project_context_scope_resolutions != list(
        subhypothesis_scope_policy.get("context_conflict_resolutions") or []
    ):
        subhypothesis_scope_policy = {
            **subhypothesis_scope_policy,
            "context_conflict_resolutions": project_context_scope_resolutions[:64],
        }
        scientific_object_anchor_policy = {
            **scientific_object_anchor_policy,
            "subhypothesis_scope_policy": subhypothesis_scope_policy,
            "scope_conflict_resolutions": project_context_scope_resolutions[:64],
        }
    if project_context_scope_risks != list(
        subhypothesis_scope_policy.get("context_conflict_risks") or []
    ):
        subhypothesis_scope_policy = {
            **subhypothesis_scope_policy,
            "context_conflict_risks": project_context_scope_risks[:64],
        }
        scientific_object_anchor_policy = {
            **scientific_object_anchor_policy,
            "subhypothesis_scope_policy": subhypothesis_scope_policy,
            "scope_context_conflict_risks": project_context_scope_risks[:64],
        }
    object_maturity_audit = _object_maturity_audit_from_subhypothesis(
        normalized_sub_hypothesis
    )
    scientific_object_contract_audit = (
        normalized_sub_hypothesis.get("scientific_object_contract_audit")
        if isinstance(normalized_sub_hypothesis.get("scientific_object_contract_audit"), dict)
        else {}
    )
    multi_entity_panel_policy = build_multi_entity_panel_policy(
        declared_scientific_object=declared_scientific_object,
        focus_text=focus_text,
        evidence_paths=evidence_paths,
        supporting_mediators=supporting_mediators,
        raw_causal_contract=raw_causal_contract,
        comparison_text=comparison_text,
        evidence_mode=evidence_mode,
        scientific_object_anchor_policy=scientific_object_anchor_policy,
    )
    panel_path_policy_by_id = {
        str(item.get("id") or item.get("role") or "").strip().lower(): item
        for item in (multi_entity_panel_policy.get("path_policies") or [])
        if isinstance(item, dict)
    }
    panel_path_policy_by_role = {
        str(item.get("role") or item.get("id") or "").strip().lower(): item
        for item in (multi_entity_panel_policy.get("path_policies") or [])
        if isinstance(item, dict)
    }
    scientific_object_terms = _unique(
        ([scientific_object_identity_anchor] if scientific_object_identity_anchor else [])
        + list(scientific_object_anchor_policy.get("strong_anchor_terms") or [])
        + list(scientific_object_anchor_policy.get("semantic_equivalent_anchor_terms") or [])
    )
    scientific_object_phrases = _unique(
        ([scientific_object_identity_anchor] if scientific_object_identity_anchor else [])
        + list(scientific_object_anchor_policy.get("strong_anchor_phrases") or [])
        + list(scientific_object_anchor_policy.get("semantic_equivalent_anchor_phrases") or [])
    )
    retrieval_object_profiles = _retrieval_object_profiles_for_contract(
        normalized_sub_hypothesis,
        primary_object=declared_scientific_object,
        primary_aliases=list(normalized_sub_hypothesis.get("scientific_object_aliases") or []),
        input_text=input_text,
        mechanism_text=mechanism_text,
        outcome_text=outcome_primary_text,
    )
    object_auxiliary_terms = list(scientific_object_anchor_policy.get("auxiliary_terms") or [])
    focus_terms = [
        term
        for term in _ranked_terms(focus_text, limit=18)
        if is_specific_object_anchor(term)
        and term not in set(scientific_object_anchor_policy.get("single_terms_not_sufficient") or [])
    ]
    # The scientific unit of readiness is a graph of source-bound causal
    # edges, not a single paper that happens to restate every SH field.  Keep
    # the graph deliberately small: the pivotal mediator is the required
    # bridge, while supporting mediators remain searchable/contextual until a
    # later SH explicitly promotes one to a critical edge.  This prevents a
    # generated long mediator list from silently becoming an impossible
    # all-in-one-paper gate.
    hypothesis_evidence_graph_nodes = {
        "input": {
            "id": "input",
            "label": focal_variable,
            "role": "input",
        },
        "mediator": {
            "id": "mediator",
            "label": mechanism_text,
            "role": "mediator",
        },
        "outcome": {
            "id": "outcome",
            "label": outcome_primary_text,
            "role": "outcome",
        },
    }
    hypothesis_evidence_graph_edges: list[dict[str, Any]] = []
    if focal_variable and mechanism_text:
        hypothesis_evidence_graph_edges.append({
            "id": "E1_input_to_mediator",
            "source": "input",
            "target": "mediator",
            "canonical_edge": "input->mediator",
            "critical": True,
        })
    if mechanism_text and outcome_primary_text:
        hypothesis_evidence_graph_edges.append({
            "id": "E2_mediator_to_outcome",
            "source": "mediator",
            "target": "outcome",
            "canonical_edge": "mediator->outcome",
            "critical": True,
        })
    transfer_target = str(claim_layer_contract.get("transfer_target") or "").strip()
    claim_layer = str(claim_layer_contract.get("claim_layer") or "LOCAL_EMPIRICAL")
    if claim_layer != "LOCAL_EMPIRICAL" and transfer_target and outcome_primary_text:
        hypothesis_evidence_graph_nodes["transfer_target"] = {
            "id": "transfer_target",
            "label": transfer_target,
            "role": "transfer_target",
        }
        hypothesis_evidence_graph_edges.append({
            "id": "T1_local_outcome_to_transfer_target",
            "source": "outcome",
            "target": "transfer_target",
            "canonical_edge": "local_outcome->transfer_target",
            "critical": False,
            "claim_layer": claim_layer,
            "requires_transfer_basis": True,
        })
    if not hypothesis_evidence_graph_edges and focal_variable and outcome_primary_text:
        hypothesis_evidence_graph_edges.append({
            "id": "E1_input_to_outcome",
            "source": "input",
            "target": "outcome",
            "canonical_edge": "input->outcome",
            "critical": True,
        })
    hypothesis_evidence_graph = {
        "schema_version": "hypothesis_evidence_graph_v1",
        "graph_source": "alignment_contract_declared_axes",
        "nodes": hypothesis_evidence_graph_nodes,
        "required_edges": hypothesis_evidence_graph_edges,
        "comparison": {
            "declared": comparison_source,
            "required": bool(comparison_source),
        },
        "alternatives": [
            str(item).strip()
            for item in (raw_causal_contract.get("confounders_or_alternatives") or [])
            if str(item).strip()
        ],
        "falsification_condition": str(
            sub_hypothesis.get("falsification_condition") or ""
        ).strip(),
        "policy": (
            "cross_paper_edge_composition_allowed; each critical edge requires "
            "source-bound SH-local evidence; one-paper whole-chain evidence is "
            "a strengthening signal rather than a default prerequisite"
        ),
    }
    contract = {
        "version": ALIGNMENT_VERSION,
        "project_id": card.get("project_id", ""),
        "project_version": card.get("project_version", 0),
        "alignment_card_hash": card.get("alignment_card_hash", ""),
        "sub_hypothesis_id": str(sub_hypothesis.get("id") or ""),
        "focus": str(sub_hypothesis.get("focus") or ""),
        "primary_field": primary_field,
        "primary_field_source": (
            "llm_subhypothesis_identity"
            if sub_hypothesis.get("primary_field")
            else "declared_project_domain_fallback"
        ),
        "adjacent_fields": adjacent_fields,
        "retrieval_domain_profile": {
            "schema_version": "retrieval_domain_profile_v1",
            "primary_evidence_domains": [primary_field] if primary_field else [],
            "transfer_interpretation_domains": (
                list(adjacent_fields)[:4]
                if claim_layer != "LOCAL_EMPIRICAL" else []
            ),
            "policy": "retrieve_local_empirical_edges_in_primary_domains_before_transfer_interpretation",
        },
        "scientific_object": declared_scientific_object,
        "scientific_object_identity_anchor": scientific_object_identity_anchor,
        "scientific_object_identity_phrases": (
            [scientific_object_identity_anchor]
            if scientific_object_identity_anchor
            else []
        ),
        "scientific_object_identity_audit": scientific_object_identity_audit,
        "retrieval_object_profiles": retrieval_object_profiles,
        "retrieval_object_profile_policy": {
            "version": "retrieval_object_profiles_v1",
            "primary_profile_id": str((retrieval_object_profiles[0] if retrieval_object_profiles else {}).get("id") or ""),
            "profile_count": len(retrieval_object_profiles),
            "separate_query_required": len(retrieval_object_profiles) > 1,
            "nonprimary_profiles_are_corpus_only_by_default": True,
        },
        "scientific_object_normalization": scientific_object_normalization,
        "scientific_object_contract_audit": dict(scientific_object_contract_audit),
        "object_contract_valid": (
            bool(scientific_object_contract_audit.get("valid") is True)
            if scientific_object_contract_audit
            else bool(declared_scientific_object)
        ),
        "object_contract_error": str(
            scientific_object_contract_audit.get("error_code")
            or scientific_object_contract_audit.get("error")
            or ("scientific_object_missing" if not declared_scientific_object else "")
            or ""
        ),
        "object_maturity_audit": object_maturity_audit,
        "object_maturity_status": _object_maturity_status_from_audit(object_maturity_audit),
        "direct_core_evidence_allowed": (
            False
            if scientific_object_contract_audit.get("valid") is False
            or not declared_scientific_object
            else _object_maturity_direct_core_allowed(object_maturity_audit)
        ),
        "object_maturity_retrieval_mode": str(
            "contract_repair_required"
            if scientific_object_contract_audit.get("valid") is False
            or not declared_scientific_object
            else object_maturity_audit.get("retrieval_mode")
            or (
                "direct_core"
                if _object_maturity_direct_core_allowed(object_maturity_audit)
                else "component_bridge_boundary"
            )
        ),
        "excluded_nearby_objects": excluded_nearby_objects,
        "subhypothesis_scope_policy": subhypothesis_scope_policy,
        "query_forbidden_terms": query_forbidden_terms,
        "hard_exclusion_terms": list(subhypothesis_scope_policy.get("hard_exclusion_terms") or [])[:96],
        "fast_reject_terms": list(subhypothesis_scope_policy.get("fast_reject_terms") or [])[:96],
        "soft_exclusion_terms": list(subhypothesis_scope_policy.get("soft_exclusion_terms") or [])[:128],
        "scope_conflict_soft_terms": list(subhypothesis_scope_policy.get("scope_conflict_soft_terms") or [])[:96],
        "scope_context_removals": project_context_scope_removals[:64],
        "scope_conflict_resolutions": project_context_scope_resolutions[:64],
        "scope_context_conflict_risks": project_context_scope_risks[:64],
        "scope_context_anchor_fallbacks": list(
            subhypothesis_scope_policy.get("context_anchor_fallbacks") or []
        )[:8],
        "protected_positive_terms": list(subhypothesis_scope_policy.get("protected_positive_terms") or [])[:160],
        "query_forbidden_term_variants": dict(
            subhypothesis_scope_policy.get("query_forbidden_term_variants") or {}
        ),
        "provider_not_exclusion_variants": dict(
            subhypothesis_scope_policy.get("provider_not_exclusion_variants") or {}
        ),
        "excluded_nearby_objects_reconciliation": exclusion_reconciliation,
        "causal_chain": causal_steps,
        "hypothesis_evidence_graph": hypothesis_evidence_graph,
        "causal_contract": {
            "version": str(raw_causal_contract.get("version") or "causal_contract_v1"),
            "parent_decision_link": str(raw_causal_contract.get("parent_decision_link") or ""),
            "constraint_type": str(raw_causal_contract.get("constraint_type") or ""),
            "input_contract": dict(input_contract),
            "pivotal_mechanism": pivotal_mechanism,
            "pivotal_mechanism_role": str(
                raw_causal_contract.get("pivotal_mechanism_role") or "UNSPECIFIED"
            ),
            "supporting_mediators": supporting_mediators,
            "core_evidence_definition": str(raw_causal_contract.get("core_evidence_definition") or ""),
            "auxiliary_evidence_definition": str(raw_causal_contract.get("auxiliary_evidence_definition") or ""),
            "outcome": str(raw_causal_contract.get("outcome") or ""),
            "claim_layer_contract": dict(claim_layer_contract),
            "boundary_conditions": [
                str(item).strip()
                for item in (raw_causal_contract.get("boundary_conditions") or [])
                if str(item).strip()
            ],
            "confounders_or_alternatives": [
                str(item).strip()
                for item in (raw_causal_contract.get("confounders_or_alternatives") or [])
                if str(item).strip()
            ],
            "path_failure_policy": (
                dict(raw_causal_contract.get("path_failure_policy"))
                if isinstance(raw_causal_contract.get("path_failure_policy"), dict)
                else {}
            ),
        },
        "evidence_paths": [
            {
                "id": str(path.get("id") or path.get("role") or ""),
                "role": str(path.get("role") or ""),
                "polarity": str(path.get("polarity") or ""),
                "causal_steps": [
                    str(step) for step in (path.get("causal_steps") or []) if str(step).strip()
                ],
                "retrieval_query": str(path.get("retrieval_query") or ""),
                "source": str(path.get("source") or ""),
                "panel_evidence_tier": str(
                    (
                        panel_path_policy_by_id.get(str(path.get("id") or path.get("role") or "").strip().lower())
                        or panel_path_policy_by_role.get(str(path.get("role") or path.get("id") or "").strip().lower())
                        or {}
                    ).get("panel_evidence_tier")
                    or ""
                ),
                "evidence_kind": str(
                    (
                        panel_path_policy_by_id.get(str(path.get("id") or path.get("role") or "").strip().lower())
                        or panel_path_policy_by_role.get(str(path.get("role") or path.get("id") or "").strip().lower())
                        or {}
                    ).get("evidence_kind")
                    or ""
                ),
                "preferred_retrieval_layers": list(
                    (
                        panel_path_policy_by_id.get(str(path.get("id") or path.get("role") or "").strip().lower())
                        or panel_path_policy_by_role.get(str(path.get("role") or path.get("id") or "").strip().lower())
                        or {}
                    ).get("preferred_retrieval_layers")
                    or []
                ),
                "preprint_signal_layers": list(
                    (
                        panel_path_policy_by_id.get(str(path.get("id") or path.get("role") or "").strip().lower())
                        or panel_path_policy_by_role.get(str(path.get("role") or path.get("id") or "").strip().lower())
                        or {}
                    ).get("preprint_signal_layers")
                    or []
                ),
                "core_evidence_capable": bool(
                    (
                        panel_path_policy_by_id.get(str(path.get("id") or path.get("role") or "").strip().lower())
                        or panel_path_policy_by_role.get(str(path.get("role") or path.get("id") or "").strip().lower())
                        or {}
                    ).get("core_evidence_capable")
                ),
                "component_evidence_counts_as_panel_core": (
                    path.get("component_evidence_counts_as_panel_core")
                    if path.get("component_evidence_counts_as_panel_core") is not None
                    else
                    panel_path_policy_by_id.get(str(path.get("id") or path.get("role") or "").strip().lower())
                    or panel_path_policy_by_role.get(str(path.get("role") or path.get("id") or "").strip().lower())
                    or {}
                ).get("component_evidence_counts_as_panel_core")
                if not isinstance(path.get("component_evidence_counts_as_panel_core"), bool)
                else path.get("component_evidence_counts_as_panel_core"),
                "failure_scope": str(path.get("failure_scope") or ""),
                "can_independently_falsify_sh": bool(path.get("can_independently_falsify_sh")),
                "missing_path_blocks_sh": bool(path.get("missing_path_blocks_sh")),
                "direct_core_disallowed_by_object_maturity": bool(
                    path.get("direct_core_disallowed_by_object_maturity")
                ),
                "component_evidence_counts_as_core": path.get(
                    "component_evidence_counts_as_core"
                ),
                "component_anchor_group": list(
                    path.get("component_anchor_group")
                    or
                    (
                        panel_path_policy_by_id.get(str(path.get("id") or path.get("role") or "").strip().lower())
                        or panel_path_policy_by_role.get(str(path.get("role") or path.get("id") or "").strip().lower())
                        or {}
                    ).get("component_anchor_group")
                    or []
                ),
            }
            for path in evidence_paths
            if isinstance(path, dict) and str(path.get("role") or path.get("id") or "").strip()
        ],
        "epistemic_profile": dict(epistemic_profile or {}),
        "evidence_role_contract": evidence_role_contract,
        "evidence_standard": evidence_standard,
        "evidence_path_policy": str(
            sub_hypothesis.get("evidence_path_policy")
            or (
                "complementary_discovery_and_validation_paths"
                if {str(path.get("role") or "") for path in evidence_paths}
                >= {"mechanism_discovery", "causal_validation"}
                else "single_causal_path"
            )
        ),
        "independent_variable": str(sub_hypothesis.get("independent_variable") or ""),
        "dependent_variables": [
            str(item) for item in (sub_hypothesis.get("dependent_variables") or [])
            if str(item).strip()
        ],
        "controls": [
            str(item) for item in (sub_hypothesis.get("controls") or [])
            if str(item).strip()
        ],
        "comparison": comparison_text,
        "baseline_or_comparator": str(
            sub_hypothesis.get("baseline_or_comparator")
            or comparison_text
            or comparison_conditions_text
            or ""
        ),
        "tradeoff_or_conflict": [
            str(item).strip()
            for item in (
                sub_hypothesis.get("tradeoff_or_conflict")
                if isinstance(sub_hypothesis.get("tradeoff_or_conflict"), list)
                else [sub_hypothesis.get("tradeoff_or_conflict")]
            )
            if str(item).strip()
        ],
        "counter_hypothesis": str(sub_hypothesis.get("counter_hypothesis") or ""),
        "falsification_condition": str(sub_hypothesis.get("falsification_condition") or ""),
        "evidence_mode": evidence_mode,
        "declared_research_mode": str(
            sub_hypothesis.get("declared_research_mode")
            or sub_hypothesis.get("research_mode")
            or sub_hypothesis.get("research_design")
            or ""
        ),
        "scientific_object_terms": scientific_object_terms,
        "scientific_object_phrases": scientific_object_phrases,
        "object_auxiliary_terms": object_auxiliary_terms,
        "scientific_object_anchor_policy": scientific_object_anchor_policy,
        "multi_entity_panel_policy": multi_entity_panel_policy,
        "evidence_path_failure_policy": (
            dict(sub_hypothesis.get("evidence_path_failure_policy"))
            if isinstance(sub_hypothesis.get("evidence_path_failure_policy"), dict)
            else dict(raw_causal_contract.get("path_failure_policy"))
            if isinstance(raw_causal_contract.get("path_failure_policy"), dict)
            else {}
        ),
        "input_terms": _ranked_terms(input_text, limit=12),
        "input_phrases": _phrases(input_text, limit=8),
        "structured_declared_input": structured_declared_input,
        "comparison_level_terms": list(
            structured_declared_input.get("comparison_level_terms") or []
        )[:32],
        "focal_variable": focal_variable,
        "focal_variable_terms": focal_variable_terms,
        "focal_variable_phrases": focal_variable_phrases,
        "mechanism_terms": _ranked_terms(mechanism_text, limit=14),
        "mechanism_phrases": _phrases(mechanism_text, limit=8),
        # Falsification wording states a rejection condition; it is not an
        # endpoint synonym.  Keep it in its dedicated field above, while the
        # endpoint anchor remains bound to the canonical outcome only.
        "outcome_terms": _ranked_terms(outcome_primary_text, limit=16),
        "outcome_phrases": _phrases(outcome_primary_text, limit=8),
        "mechanism_outcome_synonym_dictionary": mechanism_outcome_dictionary,
        "core_axis_policy": {
            "version": "direct_core_axis_policy_v1",
            "focal_variable": focal_variable,
            "focal_variable_terms": focal_variable_terms,
            "focal_variable_phrases": focal_variable_phrases,
            "mechanism_terms": mechanism_core_terms,
            "mechanism_phrases": mechanism_core_phrases,
            "outcome_terms": outcome_core_terms,
            "outcome_phrases": outcome_core_phrases,
            "mechanism_outcome_synonym_dictionary": mechanism_outcome_dictionary,
            "mechanism_synonym_terms": list(mechanism_outcome_dictionary.get("mechanism_terms") or []),
            "outcome_synonym_terms": list(mechanism_outcome_dictionary.get("outcome_terms") or []),
            "comparison_structure": structured_declared_input,
            "comparison_terms": _unique(
                _core_axis_terms(comparison_source)
                + list(structured_declared_input.get("comparison_level_terms") or [])
            ),
            "requires_focal_variable_support": True,
            "requires_explicit_comparison_or_perturbation": True,
            "requires_specific_non_circular_endpoint": True,
            "requires_primary_content_source": True,
            "generic_terms_are_not_axis_proof": True,
        },
        "focus_terms": focus_terms,
        "moderator_terms": moderator_terms,
        "moderator_phrases": [item for item in moderator_terms if " " in item],
        "predictive_validation_terms": (
            list(_PREDICTIVE_VALIDATION_MARKERS)
            if evidence_mode == PREDICTIVE_GENERALIZATION_EVIDENCE_MODE
            else []
        ),
        "project_context_anchor_terms": filtered_project_context_anchor_terms,
        "project_context_phrases": filtered_project_context_phrases,
        "explicit_exclusion_terms": excluded_nearby_objects,
        "expanded_exclusion_terms": query_forbidden_terms,
        "required_evidence_kinds": (
            ["theoretical_framework", "predictive_validation"]
            if evidence_mode == PREDICTIVE_GENERALIZATION_EVIDENCE_MODE
            else list(
                (card.get("evidence_chain_policy") or {}).get(
                    "legacy_required_evidence_kinds", ["theoretical_framework", "experimental_evidence"]
                )
            )
        ),
        "required_evidence_roles": (
            ["background_or_framework", "predictive_validation"]
            if evidence_mode == PREDICTIVE_GENERALIZATION_EVIDENCE_MODE
            else list(
                (card.get("evidence_chain_policy") or {}).get(
                    "required_evidence_roles", ["mechanism_discovery", "causal_validation"]
                )
            )
        ),
    }
    try:
        from ._subhypothesis_retrieval import (
            assess_contract_axis_degeneracy,
            repair_contract_evidence_path_query_scope_conflicts,
        )
    except ImportError:
        from _subhypothesis_retrieval import (
            assess_contract_axis_degeneracy,
            repair_contract_evidence_path_query_scope_conflicts,
        )
    contract_axis_audit = assess_contract_axis_degeneracy(
        contract,
        sub_hypothesis=sub_hypothesis,
    )
    evidence_path_scope_repair = repair_contract_evidence_path_query_scope_conflicts(
        contract,
        sub_hypothesis=sub_hypothesis,
        audit=contract_axis_audit,
    )
    if (
        evidence_path_scope_repair.get("changed")
        or (
            isinstance(evidence_path_scope_repair.get("repair_audit"), dict)
            and evidence_path_scope_repair["repair_audit"].get("status")
            == "no_repairable_conflicting_evidence_paths"
        )
    ):
        contract = dict(evidence_path_scope_repair.get("contract") or contract)
        contract_axis_audit = (
            evidence_path_scope_repair.get("post_repair_audit")
            if isinstance(evidence_path_scope_repair.get("post_repair_audit"), dict)
            else contract_axis_audit
        )
    contract["contract_axis_degeneracy_audit"] = contract_axis_audit
    contract["contract_hash"] = _stable_hash(contract)
    return contract


def ensure_all_subhypothesis_alignment_contracts(
    project: dict[str, Any],
    *,
    project_card: dict[str, Any] | None = None,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Persist a deterministic alignment contract for every declared SH.

    Retrieval used to materialize contracts only for the SHs selected in the
    current provider round.  Downstream TanXi/near-pass stages then saw a
    partially populated ``subhypothesis_alignment_contracts`` map (often only
    ``SH1``), which made later role repair fall back to empty contracts.  This
    helper builds contracts only for SHs emitted by the current normalization
    path.  It never upgrades an unmarked SH or an existing noncurrent contract
    as a side effect of retrieval.
    """
    if not isinstance(project, dict):
        return {
            "changed": False,
            "built_sub_hypothesis_ids": [],
            "contract_count": 0,
            "status": "INVALID_PROJECT",
        }
    card = dict(project_card or build_project_alignment_card(project))
    contracts = project.get("subhypothesis_alignment_contracts")
    contracts = dict(contracts) if isinstance(contracts, dict) else {}
    built_ids: list[str] = []
    skipped_unmarked_subhypothesis_ids: list[str] = []
    skipped_noncurrent_contract_ids: list[str] = []
    for sub_hypothesis in project.get("sub_hypotheses", []) if isinstance(project.get("sub_hypotheses"), list) else []:
        if not isinstance(sub_hypothesis, dict):
            continue
        sub_id = str(
            sub_hypothesis.get("id")
            or sub_hypothesis.get("sub_hypothesis_id")
            or ""
        ).strip()
        if not sub_id:
            continue
        if sub_hypothesis.get("scientific_operationality_preflight_required") is not True:
            skipped_unmarked_subhypothesis_ids.append(sub_id)
            continue
        existing_contract = (
            contracts.get(sub_id)
            if isinstance(contracts.get(sub_id), dict)
            else {}
        )
        if existing_contract and existing_contract.get("version") != ALIGNMENT_VERSION:
            skipped_noncurrent_contract_ids.append(sub_id)
            continue
        if not overwrite and existing_contract:
            continue
        contracts[sub_id] = build_subhypothesis_alignment_contract(
            project,
            sub_hypothesis,
            card,
        )
        built_ids.append(sub_id)
    project["research_alignment_card"] = card
    project["subhypothesis_alignment_contracts"] = contracts
    return {
        "changed": bool(built_ids),
        "built_sub_hypothesis_ids": built_ids,
        "skipped_unmarked_sub_hypothesis_ids": skipped_unmarked_subhypothesis_ids,
        "skipped_noncurrent_contract_sub_hypothesis_ids": skipped_noncurrent_contract_ids,
        "contract_count": len(contracts),
        "status": (
            "CURRENT_NORMALIZATION_REQUIRED"
            if skipped_unmarked_subhypothesis_ids or skipped_noncurrent_contract_ids
            else "BUILT"
            if built_ids
            else "UNCHANGED"
        ),
    }


def expanded_exclusion_terms_for_contract(
    contract: dict[str, Any] | None,
    *,
    domain: Any = "",
    provider_not_only: bool = False,
) -> list[str]:
    payload = contract if isinstance(contract, dict) else {}
    scope_policy = (
        payload.get("subhypothesis_scope_policy")
        if isinstance(payload.get("subhypothesis_scope_policy"), dict)
        else {}
    )
    variant_map_key = (
        "provider_not_exclusion_variants"
        if provider_not_only
        else "query_forbidden_term_variants"
    )
    variants_map = (
        payload.get(variant_map_key)
        if isinstance(payload.get(variant_map_key), dict)
        else scope_policy.get(variant_map_key)
        if isinstance(scope_policy.get(variant_map_key), dict)
        else {}
    )
    values: list[str] = []
    if isinstance(variants_map, dict):
        for raw_values in variants_map.values():
            values.extend(_scope_policy_values(raw_values))
    if provider_not_only:
        confidence = exclusion_terms_by_confidence_for_contract(
            payload,
            domain=domain,
        )
        safe_provider_terms = _scope_policy_values(
            list(confidence.get("hard_exclusion_terms") or [])
            + list(confidence.get("fast_reject_terms") or [])
        )
        return _unique(
            [
                term
                for term in values + safe_provider_terms
                if _exclusion_term_can_hard_reject(
                    term,
                    protected_positive_terms=confidence.get("protected_positive_terms") or [],
                )
            ]
        )[:128]
    base_terms = _scope_policy_values(
        list(payload.get("explicit_exclusion_terms") or [])
        + list(payload.get("excluded_nearby_objects") or [])
        + list(payload.get("query_forbidden_terms") or [])
        + list(scope_policy.get("query_forbidden_terms") or [])
    )
    values.extend(base_terms)
    for term in base_terms:
        values.extend(expand_exclusion_variants(term, domain))
    return _unique(values)[:128]


def _query_word_tokens(value: Any) -> list[str]:
    return [
        token.lower()
        for token in re.findall(r"[A-Za-z0-9][A-Za-z0-9_+./-]*", str(value or ""))
        if token.strip()
    ]


def _query_without_protected_phrases(query: Any, protected_phrases: list[str]) -> str:
    remaining = _normalize(query).lower()
    for phrase in sorted(protected_phrases, key=len, reverse=True):
        normalized = _normalize(phrase).lower()
        if not normalized or " " not in normalized:
            continue
        variants = {
            normalized,
            normalized.replace("-", " "),
            normalized.replace(" ", "-"),
        }
        for variant in variants:
            remaining = re.sub(
                rf"(?<![a-z0-9]){re.escape(variant)}(?![a-z0-9])",
                " ",
                remaining,
            )
    return _normalize(remaining)


def _query_plan_values(plan: dict[str, Any] | None, *keys: str) -> list[str]:
    payload = plan if isinstance(plan, dict) else {}
    values: list[str] = []
    for key in keys:
        values.extend(_scope_policy_values(payload.get(key)))
    return _unique(values)


def declared_input_anchor_group_for_contract(
    contract: dict[str, Any] | None,
    *,
    limit: int = 16,
) -> list[str]:
    """Return SH-local input/exposure/intervention anchors that must not vanish.

    Project/object context and outcome terms can legitimately support broad
    background retrieval.  A causal SH's declared input, exposure, intervention,
    or condition is different: if a non-background branch drops it, the branch
    has stopped asking the current sub-hypothesis.
    """

    payload = contract if isinstance(contract, dict) else {}
    core_axis_policy = (
        payload.get("core_axis_policy")
        if isinstance(payload.get("core_axis_policy"), dict)
        else {}
    )
    if not core_axis_policy:
        return []
    structured_declared_input = (
        core_axis_policy.get("comparison_structure")
        if isinstance(core_axis_policy.get("comparison_structure"), dict)
        else {}
    )
    baseline_or_comparator_terms = _declared_baseline_or_comparator_terms(
        structured_declared_input,
        core_axis_policy.get("baseline_or_comparator"),
        core_axis_policy.get("controls"),
    )
    structured_non_baseline_terms = (
        _scope_policy_values(structured_declared_input.get("non_baseline_comparison_level_terms"))
        or _scope_policy_values(structured_declared_input.get("comparison_level_terms"))
    )
    raw_values = (
        _scope_policy_values(structured_declared_input.get("declared_input_variable"))
        + (
            structured_non_baseline_terms
            + _scope_policy_values(core_axis_policy.get("comparison_level_terms"))
            if bool(structured_declared_input.get("comparison_levels_as_declared_input"))
            else []
        )
        + _scope_policy_values(core_axis_policy.get("focal_variable_phrases"))
        + _scope_policy_values(core_axis_policy.get("focal_variable_terms"))
    )
    output: list[str] = []
    for value in raw_values:
        normalized = _clean_anchor_for_query_role(
            value,
            role="causal_input",
            baseline_or_comparator_terms=baseline_or_comparator_terms,
        )
        if not normalized:
            continue
        lowered = normalized.lower()
        if lowered.rstrip(".") in {"vs", "versus"}:
            continue
        if lowered in _LOW_SIGNAL or lowered in _CORE_AXIS_GENERIC_TERMS:
            continue
        if lowered in _PROJECT_ANCHOR_GLUE_TERMS or lowered in _RETRIEVAL_OBJECT_GENERIC_TERMS:
            continue
        if is_component_bridge_modifier_only_anchor(normalized):
            continue
        output.append(normalized)
    return _unique(output)[: max(1, int(limit))]


def query_plan_is_background_context(plan: dict[str, Any] | None) -> bool:
    """True when a branch is explicitly project/context background."""

    payload = plan if isinstance(plan, dict) else {}
    lane = str(payload.get("target_lane") or "").strip().upper()
    if lane in {"THEORETICAL_FRAMEWORK", "BACKGROUND_REVIEW"}:
        return True
    role_text = " ".join(
        str(payload.get(key) or "")
        for key in (
            "branch",
            "query_family",
            "evidence_path_role",
            "retrieval_layer_role",
            "purpose",
        )
    ).lower()
    return any(
        marker in role_text
        for marker in (
            "background",
            "context_review",
            "context review",
            "framework",
            "theoretical_framework",
            "review",
        )
    )


def query_plan_requires_declared_input(
    plan: dict[str, Any] | None,
    contract: dict[str, Any] | None,
) -> bool:
    """Whether a provider branch must preserve the SH-local causal input."""

    payload = plan if isinstance(plan, dict) else {}
    if payload.get("query_requires_declared_input") is True:
        return bool(declared_input_anchor_group_for_contract(contract))
    if payload.get("query_requires_declared_input") is False:
        return False
    return bool(
        declared_input_anchor_group_for_contract(contract)
        and not query_plan_is_background_context(payload)
    )


def audit_subhypothesis_query_contamination(
    raw_query: Any,
    alignment_contract: dict[str, Any] | None = None,
    *,
    plan: dict[str, Any] | None = None,
    branch: str = "",
    provider_candidate_count: int = 0,
) -> dict[str, Any]:
    """Diagnose query pollution without changing retrieval semantics."""

    query = _normalize(raw_query)
    contract = alignment_contract if isinstance(alignment_contract, dict) else {}
    object_policy = (
        contract.get("scientific_object_anchor_policy")
        if isinstance(contract.get("scientific_object_anchor_policy"), dict)
        else {}
    )
    scope_policy = (
        contract.get("subhypothesis_scope_policy")
        if isinstance(contract.get("subhypothesis_scope_policy"), dict)
        else {}
    )
    core_axis_policy = (
        contract.get("core_axis_policy")
        if isinstance(contract.get("core_axis_policy"), dict)
        else {}
    )
    structured_declared_input = (
        contract.get("structured_declared_input")
        if isinstance(contract.get("structured_declared_input"), dict)
        else core_axis_policy.get("comparison_structure")
        if isinstance(core_axis_policy.get("comparison_structure"), dict)
        else {}
    )
    baseline_or_comparator_group = _clean_anchor_group_for_query_role(
        _declared_baseline_or_comparator_terms(
            structured_declared_input,
            contract.get("baseline_or_comparator"),
            contract.get("controls"),
        ),
        role="baseline_or_comparator",
        limit=24,
    )
    raw_plan_required_object_group = _clean_anchor_group_for_query_role(
        _query_plan_values(plan, "required_object_group", "scientific_object_anchor_group"),
        role="object",
        baseline_or_comparator_terms=baseline_or_comparator_group,
    )
    raw_policy_component_object_group = _clean_anchor_group_for_query_role(
        _scope_policy_values(object_policy.get("component_bridge_object_anchor_phrases")),
        role="object",
        baseline_or_comparator_terms=baseline_or_comparator_group,
    )
    trusted_declared_object_group = _clean_anchor_group_for_query_role(
        _scope_policy_values(object_policy.get("strong_anchor_phrases"))
        + _scope_policy_values(object_policy.get("semantic_equivalent_anchor_phrases"))
        + _scope_policy_values(contract.get("scientific_object_phrases")),
        role="object",
        baseline_or_comparator_terms=baseline_or_comparator_group,
    )
    required_object_group: list[str] = []
    method_or_readout_object_anchor_demotions: list[str] = []
    for candidate in raw_plan_required_object_group + raw_policy_component_object_group:
        if is_query_method_or_readout_only_anchor(candidate):
            method_or_readout_object_anchor_demotions.append(candidate)
        else:
            required_object_group.append(candidate)
    required_object_group = _unique(required_object_group + trusted_declared_object_group)
    object_edge_required = bool(
        raw_plan_required_object_group
        or raw_policy_component_object_group
        or trusted_declared_object_group
    )
    object_edge_exhausted_by_method_or_readout_demotions = bool(
        object_edge_required and not required_object_group
    )
    support_group = _clean_anchor_group_for_query_role(
        _query_plan_values(
            plan,
            "required_method_or_mechanism_group",
            "optional_readout_group",
            "optional_model_group",
            "component_support_anchor_group",
        )
        + method_or_readout_object_anchor_demotions
        + _scope_policy_values(object_policy.get("component_bridge_method_or_platform_anchor_phrases"))
        + _scope_policy_values(object_policy.get("component_bridge_readout_anchor_phrases"))
        + _scope_policy_values(object_policy.get("component_bridge_model_system_anchor_phrases")),
        role="support",
        baseline_or_comparator_terms=baseline_or_comparator_group,
    )
    non_baseline_structured_comparison_terms = (
        _scope_policy_values(structured_declared_input.get("non_baseline_comparison_level_terms"))
        or _scope_policy_values(structured_declared_input.get("comparison_level_terms"))
    )
    comparison_group = _clean_anchor_group_for_query_role(
        _query_plan_values(plan, "comparison_group", "comparison_terms", "comparison_anchor_group")
        + _scope_policy_values(core_axis_policy.get("comparison_terms"))
        + _scope_policy_values(contract.get("comparison"))
        + _scope_policy_values(contract.get("comparison_conditions"))
        + non_baseline_structured_comparison_terms,
        role="non_baseline_comparison",
        baseline_or_comparator_terms=baseline_or_comparator_group,
    )
    non_baseline_comparison_group = _unique(
        _clean_anchor_group_for_query_role(
            non_baseline_structured_comparison_terms,
            role="non_baseline_comparison",
            baseline_or_comparator_terms=baseline_or_comparator_group,
        )
        + comparison_group
    )[:16]
    declared_input_group = _clean_anchor_group_for_query_role(
        _query_plan_values(plan, "required_causal_input_group", "causal_input_anchor_group")
        + declared_input_anchor_group_for_contract(contract),
        role="causal_input",
        baseline_or_comparator_terms=baseline_or_comparator_group,
    )[:16]
    requires_declared_input = query_plan_requires_declared_input(plan, contract)
    protected_phrases = _unique([
        item for item in required_object_group + declared_input_group + support_group
        if " " in _normalize(item)
    ])
    query_for_low_signal = _query_without_protected_phrases(query, protected_phrases)
    standalone_low_signal_terms = _unique([
        token for token in _query_word_tokens(query_for_low_signal)
        if token in LOW_SIGNAL_STANDALONE_QUERY_TERMS
    ])
    template_modifier_terms = _unique([
        item for item in (
            list(_COMPONENT_BRIDGE_MODIFIER_ONLY_PHRASES)
            + list(_COMPONENT_BRIDGE_MODIFIER_ONLY_TERMS)
        )
        if _scope_term_matches_text(item, query)
    ])
    required_object_anchor_hits = _unique([
        item for item in required_object_group
        if _scope_term_matches_text(item, query)
    ])
    query_for_single_token_input_hits = _query_without_protected_phrases(
        query,
        _unique(required_object_group + support_group),
    )

    def input_anchor_hits_text(item: str, source_text: str) -> bool:
        tokens = _query_word_tokens(item)
        if len(tokens) <= 1:
            return _scope_term_matches_text(item, source_text)
        return _scope_term_matches_text(item, query)

    declared_input_hits = _unique([
        item for item in declared_input_group
        if input_anchor_hits_text(item, query_for_single_token_input_hits)
    ])
    comparison_hits = _unique([
        item for item in comparison_group
        if _scope_term_matches_text(item, query)
    ])
    non_baseline_comparison_hits = _unique([
        item for item in non_baseline_comparison_group
        if input_anchor_hits_text(item, query_for_single_token_input_hits)
    ])
    baseline_or_comparator_hits = _unique([
        item for item in baseline_or_comparator_group
        if _scope_term_matches_text(item, query)
    ])
    exclusion_confidence = exclusion_terms_by_confidence_for_contract(
        contract,
        domain=str(contract.get("primary_field") or ""),
    )
    legacy_sibling_terms = _scope_policy_values(scope_policy.get("sibling_scope_terms"))
    direct_contract_query_forbidden = [
        term
        for term in _scope_policy_values(contract.get("query_forbidden_terms"))
        if term not in legacy_sibling_terms
    ]
    hard_forbidden_terms = _unique(
        _scope_policy_values(exclusion_confidence.get("hard_exclusion_terms"))
        + _scope_policy_values(exclusion_confidence.get("fast_reject_terms"))
        + _scope_policy_values(exclusion_confidence.get("query_forbidden_terms"))
        + direct_contract_query_forbidden
    )
    soft_forbidden_terms = _unique(
        _scope_policy_values(scope_policy.get("soft_exclusion_terms"))
        + _scope_policy_values(contract.get("soft_exclusion_terms"))
        + _scope_policy_values(scope_policy.get("scope_conflict_soft_terms"))
        + _scope_policy_values(contract.get("scope_conflict_soft_terms"))
    )
    hard_forbidden_terms_present = _unique([
        term for term in hard_forbidden_terms
        if _scope_term_matches_text(term, query)
    ])
    soft_forbidden_terms_present = _unique([
        term for term in soft_forbidden_terms
        if _scope_term_matches_text(term, query)
    ])
    sibling_object_role_conflict_candidates = [
        {
            "term": _normalize(item.get("term")),
            "source_sh_id": str(item.get("source_sh_id") or ""),
            "source_field": str(item.get("source_field") or ""),
            "enforcement": "post_retrieval_object_role_conflict_only",
        }
        for item in (
            scope_policy.get("sibling_object_role_conflict_candidates") or []
        )
        if isinstance(item, dict) and _normalize(item.get("term"))
    ][:24]
    protected_phrase_count = sum(
        1 for phrase in protected_phrases
        if _scope_term_matches_text(phrase, query)
    )
    support_hits = _unique([
        item for item in support_group
        if _scope_term_matches_text(item, query)
    ])
    declared_input_or_non_baseline_comparison_hits = _unique(
        declared_input_hits + non_baseline_comparison_hits
    )
    baseline_only_declared_input_match = bool(
        requires_declared_input
        and (declared_input_group or non_baseline_comparison_group)
        and not declared_input_or_non_baseline_comparison_hits
        and baseline_or_comparator_hits
    )
    branch_text = _normalize(
        " ".join(
            str(value or "")
            for value in (
                branch,
                (plan or {}).get("branch") if isinstance(plan, dict) else "",
                (plan or {}).get("query_branch") if isinstance(plan, dict) else "",
                (plan or {}).get("query_family") if isinstance(plan, dict) else "",
                (plan or {}).get("query_variant_reason") if isinstance(plan, dict) else "",
                (plan or {}).get("query_optimizer_round") if isinstance(plan, dict) else "",
            )
        )
    ).lower()
    optimizer_query_scientific_edge_required = bool(
        "optimized_r" in branch_text
        or "optimizer" in branch_text
        or str((plan or {}).get("query_optimizer_round") or "").strip() not in {"", "0"}
    )
    modifier_only_or_method_only_query = bool(
        object_edge_required
        and not required_object_anchor_hits
        and (
            object_edge_exhausted_by_method_or_readout_demotions
            or method_or_readout_object_anchor_demotions
            or template_modifier_terms
            or standalone_low_signal_terms
        )
    )
    risk_score = 0
    if len(standalone_low_signal_terms) >= 4:
        risk_score += 2
    elif standalone_low_signal_terms:
        risk_score += 1
    if len(template_modifier_terms) >= 2:
        risk_score += 2
    elif template_modifier_terms:
        risk_score += 1
    if required_object_group and not required_object_anchor_hits:
        risk_score += 2
    elif object_edge_exhausted_by_method_or_readout_demotions:
        risk_score += 2
    if (
        requires_declared_input
        and (declared_input_group or non_baseline_comparison_group)
        and not declared_input_or_non_baseline_comparison_hits
    ):
        risk_score += 4
    if baseline_only_declared_input_match:
        risk_score += 2
    if hard_forbidden_terms_present:
        risk_score += 3
    if soft_forbidden_terms_present and not hard_forbidden_terms_present:
        risk_score += 1
    query_contamination_risk = (
        "high" if risk_score >= 4
        else "medium" if risk_score >= 2
        else "low"
    )
    recompiled_terms = _unique(
        required_object_group[:3]
        + (declared_input_group[:2] if requires_declared_input else [])
        + non_baseline_comparison_group[:2]
        + comparison_group[:2]
        + support_group[:6]
    )
    recompiled_query = _normalize(
        " ".join(
            f'"{term}"' if " " in _normalize(term) else _normalize(term)
            for term in recompiled_terms
            if _normalize(term)
            and not _scope_forbidden_hits(term, hard_forbidden_terms)
            and not is_component_bridge_modifier_only_anchor(term)
        )
    )
    recompiled_required_object_anchor_hits = _unique([
        item for item in required_object_group
        if _scope_term_matches_text(item, recompiled_query)
    ])
    recompiled_query_for_single_token_input_hits = _query_without_protected_phrases(
        recompiled_query,
        _unique(required_object_group + support_group),
    )

    def recompiled_input_anchor_hits_text(item: str, source_text: str) -> bool:
        tokens = _query_word_tokens(item)
        if len(tokens) <= 1:
            return _scope_term_matches_text(item, source_text)
        return _scope_term_matches_text(item, recompiled_query)

    recompiled_declared_input_hits = _unique([
        item for item in declared_input_group
        if recompiled_input_anchor_hits_text(item, recompiled_query_for_single_token_input_hits)
    ])
    recompiled_comparison_hits = _unique([
        item for item in comparison_group
        if _scope_term_matches_text(item, recompiled_query)
    ])
    recompiled_non_baseline_comparison_hits = _unique([
        item for item in non_baseline_comparison_group
        if recompiled_input_anchor_hits_text(item, recompiled_query_for_single_token_input_hits)
    ])
    recompiled_baseline_or_comparator_hits = _unique([
        item for item in baseline_or_comparator_group
        if _scope_term_matches_text(item, recompiled_query)
    ])
    recompiled_support_hits = _unique([
        item for item in support_group
        if _scope_term_matches_text(item, recompiled_query)
    ])
    recompiled_declared_input_or_non_baseline_hits = _unique(
        recompiled_declared_input_hits + recompiled_non_baseline_comparison_hits
    )
    recompiled_query_scientific_edge_valid = bool(
        (not object_edge_required or recompiled_required_object_anchor_hits)
        and (
            not requires_declared_input
            or not (declared_input_group or non_baseline_comparison_group)
            or recompiled_declared_input_or_non_baseline_hits
        )
        and (not support_group or recompiled_support_hits)
        and not _unique(
            [
                term for term in hard_forbidden_terms
                if _scope_term_matches_text(term, recompiled_query)
            ]
        )
    )
    raw_query_scientific_edge_valid = bool(
        (not object_edge_required or required_object_anchor_hits)
        and (
            not requires_declared_input
            or not (declared_input_group or non_baseline_comparison_group)
            or declared_input_or_non_baseline_comparison_hits
        )
        and (not support_group or support_hits)
        and not hard_forbidden_terms_present
    )
    if (
        requires_declared_input
        and (declared_input_group or non_baseline_comparison_group)
        and not declared_input_or_non_baseline_comparison_hits
    ):
        repair_action = (
            "recompile_from_structured_anchor_groups"
            if recompiled_query and recompiled_query_scientific_edge_valid
            else "blocked_recompile_missing_required_causal_variable"
        )
    elif not raw_query_scientific_edge_valid:
        repair_action = (
            "recompile_from_structured_anchor_groups"
            if recompiled_query and recompiled_query_scientific_edge_valid
            else "blocked_recompile_failed_scientific_edge_validation"
        )
    elif query_contamination_risk in {"medium", "high"} and recompiled_query:
        repair_action = "recompile_from_structured_anchor_groups"
    else:
        repair_action = ""
    repair_failed_missing_declared_input = bool(
        repair_action == "blocked_recompile_missing_required_causal_variable"
    )
    repair_failed_scientific_edge = bool(
        (
            repair_action == "recompile_from_structured_anchor_groups"
            and recompiled_query
            and not recompiled_query_scientific_edge_valid
        )
        or repair_action == "blocked_recompile_failed_scientific_edge_validation"
    )
    optimizer_scientific_edge_blocked = bool(
        optimizer_query_scientific_edge_required
        and not raw_query_scientific_edge_valid
        and not (
            repair_action == "recompile_from_structured_anchor_groups"
            and recompiled_query_scientific_edge_valid
        )
    )
    scientific_edge_blocked_reason = ""
    if object_edge_exhausted_by_method_or_readout_demotions:
        scientific_edge_blocked_reason = "object_anchor_group_exhausted_by_method_or_readout_demotions"
    elif object_edge_required and not required_object_anchor_hits:
        scientific_edge_blocked_reason = "missing_real_scientific_object_anchor"
    elif (
        requires_declared_input
        and (declared_input_group or non_baseline_comparison_group)
        and not declared_input_or_non_baseline_comparison_hits
    ):
        scientific_edge_blocked_reason = (
            "baseline_only_declared_input_match"
            if baseline_only_declared_input_match
            else "missing_declared_input_or_non_baseline_comparison"
        )
    elif support_group and not support_hits:
        scientific_edge_blocked_reason = "missing_mechanism_or_endpoint_support"
    elif hard_forbidden_terms_present:
        scientific_edge_blocked_reason = "hard_forbidden_conflict"
    provider_query_executed = bool(
        not repair_failed_missing_declared_input
        and not repair_failed_scientific_edge
        and not optimizer_scientific_edge_blocked
    )
    background_context_branch = query_plan_is_background_context(plan)
    return {
        "schema_version": "subhypothesis_query_contamination_audit_v2",
        "project_id": str(contract.get("project_id") or ""),
        "sub_hypothesis_id": str(contract.get("sub_hypothesis_id") or ""),
        "branch": str(branch or (plan or {}).get("branch") or (plan or {}).get("query_branch") or ""),
        "raw_query": query,
        "protected_phrase_count": protected_phrase_count,
        "standalone_low_signal_terms": standalone_low_signal_terms[:24],
        "object_edge_required": bool(object_edge_required),
        "required_object_terms": required_object_group[:16],
        "raw_plan_required_object_terms": raw_plan_required_object_group[:16],
        "method_or_readout_object_anchor_demotions": (
            _unique(method_or_readout_object_anchor_demotions)[:16]
        ),
        "object_edge_exhausted_by_method_or_readout_demotions": bool(
            object_edge_exhausted_by_method_or_readout_demotions
        ),
        "required_object_anchor_hits_in_query": required_object_anchor_hits[:16],
        "required_object_anchor_hits_in_recompiled_query": recompiled_required_object_anchor_hits[:16],
        "declared_input_terms": declared_input_group[:16],
        "declared_input_terms_present_in_query": declared_input_hits[:16],
        "declared_input_or_non_baseline_comparison_terms_present_in_query": (
            declared_input_or_non_baseline_comparison_hits[:16]
        ),
        "comparison_terms": comparison_group[:16],
        "comparison_terms_present_in_query": comparison_hits[:16],
        "non_baseline_comparison_terms": non_baseline_comparison_group[:16],
        "non_baseline_comparison_terms_present_in_query": non_baseline_comparison_hits[:16],
        "baseline_or_comparator_terms": baseline_or_comparator_group[:16],
        "baseline_or_comparator_terms_present_in_query": baseline_or_comparator_hits[:16],
        "baseline_only_declared_input_match": baseline_only_declared_input_match,
        "missing_declared_input_terms": (
            []
            if declared_input_or_non_baseline_comparison_hits
            else (declared_input_group or non_baseline_comparison_group)[:16]
        ),
        "declared_input_required_for_branch": bool(requires_declared_input),
        "query_valid_for_sh": raw_query_scientific_edge_valid,
        "raw_query_scientific_edge_valid": raw_query_scientific_edge_valid,
        "recompiled_query_valid_for_sh": recompiled_query_scientific_edge_valid,
        "recompiled_query_scientific_edge_valid": recompiled_query_scientific_edge_valid,
        "optimizer_query_scientific_edge_required": bool(
            optimizer_query_scientific_edge_required
        ),
        "optimizer_scientific_edge_blocked": bool(optimizer_scientific_edge_blocked),
        "modifier_only_or_method_only_query": bool(modifier_only_or_method_only_query),
        "scientific_edge_blocked_reason": scientific_edge_blocked_reason,
        "provider_query_executed": provider_query_executed,
        "provider_suppressed_reason": (
            "repaired_query_missing_declared_input"
            if repair_failed_missing_declared_input and not baseline_only_declared_input_match
            else "repaired_query_missing_non_baseline_declared_input"
            if repair_failed_missing_declared_input and baseline_only_declared_input_match
            else "optimizer_query_failed_scientific_edge_validation"
            if optimizer_scientific_edge_blocked
            else scientific_edge_blocked_reason
            if repair_failed_scientific_edge and scientific_edge_blocked_reason
            else "repaired_query_failed_scientific_edge_validation"
            if repair_failed_scientific_edge
            else "object_anchor_group_exhausted_by_method_or_readout_demotions"
            if object_edge_exhausted_by_method_or_readout_demotions and not provider_query_executed
            else "method_or_readout_only_query_missing_real_object_anchor"
            if modifier_only_or_method_only_query and not provider_query_executed
            else ""
        ),
        "branch_demoted_to_project_background_query": bool(
            background_context_branch
            and (declared_input_group or non_baseline_comparison_group)
            and not declared_input_or_non_baseline_comparison_hits
        ),
        "template_modifier_terms": template_modifier_terms[:24],
        "excluded_scope_terms_present": hard_forbidden_terms_present[:24],
        "soft_exclusion_terms_present": soft_forbidden_terms_present[:24],
        # Retained as an empty compatibility field.  Sibling objects must not
        # change query-risk scoring or query recompilation by lexical match.
        "sibling_scope_terms_present": [],
        "sibling_object_role_conflict_candidates": (
            sibling_object_role_conflict_candidates
        ),
        "query_contamination_risk": query_contamination_risk,
        "risk_score": risk_score,
        "repair_action": repair_action,
        "recompiled_query": recompiled_query,
        "recompiled_declared_input_terms_present": recompiled_declared_input_hits[:16],
        "recompiled_comparison_terms_present": recompiled_comparison_hits[:16],
        "recompiled_non_baseline_comparison_terms_present": (
            recompiled_non_baseline_comparison_hits[:16]
        ),
        "recompiled_baseline_or_comparator_terms_present": (
            recompiled_baseline_or_comparator_hits[:16]
        ),
        "recompiled_support_terms_present": recompiled_support_hits[:16],
        "provider_candidate_count": max(0, int(provider_candidate_count or 0)),
    }


def summarize_query_contamination_audits(audits: Any) -> dict[str, Any]:
    items = [item for item in (audits or []) if isinstance(item, dict)]
    if not items:
        return {
            "query_contamination_risk": "not_audited",
            "high_risk_queries": 0,
            "medium_risk_queries": 0,
            "standalone_low_signal_terms": [],
            "template_modifier_terms": [],
            "excluded_scope_terms_present": [],
            "sibling_scope_terms_present": [],
            "scientific_edge_invalid_queries": 0,
            "optimizer_scientific_edge_blocked_queries": 0,
            "modifier_or_method_only_blocked_queries": 0,
            "method_or_readout_object_anchor_demotions": [],
            "scientific_edge_blocked_reasons": [],
        }
    high = [item for item in items if item.get("query_contamination_risk") == "high"]
    medium = [item for item in items if item.get("query_contamination_risk") == "medium"]
    risk = "high" if high else "medium" if medium else "low"
    return {
        "query_contamination_risk": risk,
        "high_risk_queries": len(high),
        "medium_risk_queries": len(medium),
        "audited_queries": len(items),
        "standalone_low_signal_terms": _unique([
            value for item in items for value in (item.get("standalone_low_signal_terms") or [])
        ])[:24],
        "template_modifier_terms": _unique([
            value for item in items for value in (item.get("template_modifier_terms") or [])
        ])[:24],
        "excluded_scope_terms_present": _unique([
            value for item in items for value in (item.get("excluded_scope_terms_present") or [])
        ])[:24],
        "sibling_scope_terms_present": _unique([
            value for item in items for value in (item.get("sibling_scope_terms_present") or [])
        ])[:24],
        "declared_input_required_queries": sum(
            1 for item in items if item.get("declared_input_required_for_branch")
        ),
        "declared_input_missing_queries": sum(
            1
            for item in items
            if item.get("declared_input_required_for_branch")
            and not item.get("declared_input_or_non_baseline_comparison_terms_present_in_query")
        ),
        "baseline_only_declared_input_match_queries": sum(
            1 for item in items if item.get("baseline_only_declared_input_match")
        ),
        "declared_input_terms": _unique([
            value for item in items for value in (item.get("declared_input_terms") or [])
        ])[:24],
        "baseline_or_comparator_terms_present": _unique([
            value
            for item in items
            for value in (item.get("baseline_or_comparator_terms_present_in_query") or [])
        ])[:24],
        "non_baseline_comparison_terms_present": _unique([
            value
            for item in items
            for value in (item.get("non_baseline_comparison_terms_present_in_query") or [])
        ])[:24],
        "missing_declared_input_terms": _unique([
            value
            for item in items
            if item.get("declared_input_required_for_branch")
            for value in (item.get("missing_declared_input_terms") or [])
        ])[:24],
        "query_invalid_for_sh": sum(
            1 for item in items if item.get("query_valid_for_sh") is False
        ),
        "scientific_edge_invalid_queries": sum(
            1
            for item in items
            if item.get("raw_query_scientific_edge_valid") is False
        ),
        "optimizer_scientific_edge_blocked_queries": sum(
            1 for item in items if item.get("optimizer_scientific_edge_blocked") is True
        ),
        "modifier_or_method_only_blocked_queries": sum(
            1
            for item in items
            if item.get("modifier_only_or_method_only_query") is True
            and item.get("provider_query_executed") is False
        ),
        "method_or_readout_object_anchor_demotions": _unique([
            value
            for item in items
            for value in (item.get("method_or_readout_object_anchor_demotions") or [])
        ])[:24],
        "scientific_edge_blocked_reasons": _unique([
            str(item.get("scientific_edge_blocked_reason") or "")
            for item in items
            if str(item.get("scientific_edge_blocked_reason") or "").strip()
        ])[:12],
        "provider_suppressed_queries": sum(
            1 for item in items if item.get("provider_query_executed") is False
        ),
        "branch_demoted_to_project_background_queries": sum(
            1
            for item in items
            if item.get("branch_demoted_to_project_background_query") is True
        ),
        "repair_actions": _unique([
            value for item in items for value in [item.get("repair_action")] if value
        ])[:8],
        "sample_recompiled_queries": _unique([
            str(item.get("recompiled_query") or "")
            for item in items
            if str(item.get("recompiled_query") or "").strip()
        ])[:4],
    }


def _annotate_core_corpus_query_pools(
    plans: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Attach the retrieval-budget contract without changing branch semantics."""

    if not plans:
        return []
    core_indexes = [
        index
        for index, plan in enumerate(plans)
        if plan.get("core_evidence_capable") is True
        and str(plan.get("evidence_path_role") or "").lower()
        in {
            "causal_validation",
            "core_validation",
            "whole_causal_chain",
            "predictive_validation",
            "integrated_system_evaluation",
        }
    ]
    if not core_indexes:
        core_indexes = [
            index
            for index, plan in enumerate(plans)
            if (
                plan.get("core_evidence_capable") is True
                or plan.get("panel_core_path") is True
            )
            and str(
                plan.get("evidence_path_polarity") or "supportive"
            ).lower()
            not in {"opposing", "boundary"}
            and str(plan.get("panel_evidence_tier") or "core").lower()
            not in {"support", "context"}
        ]
    # One focused branch still prioritizes integrative causal evidence, but it
    # no longer owns an all-in-one-paper requirement.  Complementary branches
    # can recover source-bound input→mediator and mediator→outcome edges that
    # the hypothesis-level bundle will compose after full-text review.
    primary_core_index = core_indexes[0] if core_indexes else -1
    corpus_count = max(1, len(plans) - (1 if primary_core_index >= 0 else 0))
    core_share = 0.25 if primary_core_index >= 0 else 0.0
    corpus_share = (1.0 - core_share) / corpus_count
    annotated: list[dict[str, Any]] = []
    for index, raw in enumerate(plans):
        plan = dict(raw)
        is_core_pool = index == primary_core_index
        plan["query_pool"] = "core" if is_core_pool else "corpus"
        plan["candidate_budget_share"] = round(
            core_share if is_core_pool else corpus_share,
            4,
        )
        plan["requires_complete_causal_chain"] = False
        plan["requires_source_bound_declared_edge"] = bool(
            plan.get("core_evidence_capable") is True
        )
        # Pool origin never determines corpus admission. A focused hit that
        # only supports one declared edge remains eligible for the cross-paper
        # evidence bundle after its full text is structured.
        plan["corpus_import_eligible_after_fulltext"] = True
        plan["query_pool_policy"] = (
            "integrative_source_bound_edge_bundle"
            if is_core_pool
            else "broad_corpus_scientific_object_plus_one_axis"
        )
        annotated.append(plan)
    return annotated


def _annotate_abstract_edge_query_plans(
    plans: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Persist the provider-independent semantic contract for each branch.

    Provider lowering may change Boolean syntax, but it may not erase the
    object anchor or the one declared evidence edge that the branch was built
    to test.  The concrete provider query and its execution receipt are added
    later by the literature layer; keeping this representation separate avoids
    mistaking an OpenAlex syntax adaptation for a changed scientific plan.
    """

    prepared: list[dict[str, Any]] = []
    for raw in plans:
        if not isinstance(raw, dict):
            continue
        plan = dict(raw)
        modules = plan.get("query_modules") if isinstance(plan.get("query_modules"), dict) else {}
        query_tokens = set(re.findall(r"[a-z][a-z0-9+_-]*", str(plan.get("query") or "").lower()))

        def present(values: Any) -> list[str]:
            source = values if isinstance(values, (list, tuple, set)) else [values]
            kept: list[str] = []
            for value in source:
                normalized = _normalize(value)
                tokens = set(re.findall(r"[a-z][a-z0-9+_-]*", normalized.lower()))
                if normalized and tokens and tokens.issubset(query_tokens):
                    kept.append(normalized)
            return _unique(kept)[:12]

        object_group = present(
            modules.get("object")
            or plan.get("scientific_object_anchor_group")
            or plan.get("required_object_group")
        )
        input_group = present(modules.get("causal_input") or modules.get("input"))
        mechanism_group = present(modules.get("mediator") or modules.get("mechanism") or modules.get("method_or_assessment"))
        outcome_group = present(modules.get("outcome") or modules.get("endpoint") or modules.get("readout") or modules.get("readout_or_endpoint"))
        edge_id = str(
            plan.get("target_evidence_edge_id")
            or plan.get("evidence_path_id")
            or plan.get("evidence_path_role")
            or ""
        ).lower()
        required_groups: list[list[str]] = []
        if object_group:
            required_groups.append(object_group)
        if "e1" in edge_id or "input" in edge_id:
            required_groups.extend(group for group in (input_group, mechanism_group) if group)
        elif "e2" in edge_id or "outcome" in edge_id or "endpoint" in edge_id:
            required_groups.extend(group for group in (mechanism_group, outcome_group) if group)
        else:
            edge_group = _unique(input_group + mechanism_group + outcome_group)
            if edge_group:
                required_groups.append(edge_group)
        plan["abstract_edge_query_plan"] = {
            "schema_version": "abstract_edge_query_plan_v1",
            "branch": str(plan.get("branch") or "primary"),
            "target_evidence_edge_id": str(plan.get("target_evidence_edge_id") or plan.get("evidence_path_id") or ""),
            "required_anchor_groups": required_groups,
            "required_anchor_roles": {
                "object": bool(object_group),
                "input": bool(input_group),
                "mechanism": bool(mechanism_group),
                "outcome": bool(outcome_group),
            },
            "status": "READY" if required_groups else "PLAN_UNEXECUTABLE",
        }
        retrieval_anchor_contract = dict(
            plan.get("retrieval_anchor_contract") or plan.get("anchor_contract") or {}
        )
        retrieval_anchor_contract["required_anchor_groups"] = required_groups
        plan["retrieval_anchor_contract"] = retrieval_anchor_contract
        plan["provider_compiled_plan"] = {
            "schema_version": "provider_compiled_plan_v1",
            "status": "PENDING_PROVIDER_LOWERING",
            "semantic_plan_branch": str(plan.get("branch") or "primary"),
            "required_anchor_groups": required_groups,
        }
        prepared.append(plan)
    return prepared


def _finalize_retrieval_object_query_plan(
    plans: list[dict[str, Any]],
    contract: dict[str, Any],
) -> list[dict[str, Any]]:
    """Annotate primary branches and add one bounded corpus branch per object.

    A profile branch deliberately combines just its profile anchor with one
    compatible SH axis.  This avoids the accidental mega-query produced by
    concatenating the primary object, input, mechanism, outcome, and every
    implementation constraint into a single provider request.
    """
    profiles = [
        dict(profile) for profile in (contract.get("retrieval_object_profiles") or [])
        if isinstance(profile, dict) and _normalize(profile.get("query_anchor") or profile.get("object"))
    ][:3]
    if not plans:
        return []
    primary_profile = profiles[0] if profiles else {}
    primary_id = str(primary_profile.get("id") or "OBJ1")
    prepared = []
    for raw in plans:
        plan = dict(raw)
        plan.setdefault("retrieval_object_profile_id", primary_id)
        plan.setdefault("retrieval_object_profile_role", "primary_system")
        plan.setdefault("retrieval_object_profile_object", str(primary_profile.get("object") or contract.get("scientific_object") or ""))
        plan.setdefault("retrieval_object_profile_count", len(profiles) or 1)
        prepared.append(plan)
    if len(profiles) <= 1:
        return _annotate_abstract_edge_query_plans(
            _annotate_core_corpus_query_pools(prepared)
        )

    # Reuse a broad corpus branch as lane/provenance template; profile
    # branches must never consume the narrow direct-core budget.
    corpus_template = next(
        (plan for plan in prepared if plan.get("core_evidence_capable") is not True),
        prepared[0],
    )
    sub_id = str(contract.get("sub_hypothesis_id") or "subhypothesis")
    core_axis_policy = (
        contract.get("core_axis_policy")
        if isinstance(contract.get("core_axis_policy"), dict)
        else {}
    )
    input_anchors = (
        list(core_axis_policy.get("focal_variable_phrases") or [])
        + list(core_axis_policy.get("focal_variable_terms") or [])
    )
    mechanism_anchors = (
        list(core_axis_policy.get("mechanism_phrases") or [])
        + list(core_axis_policy.get("mechanism_terms") or [])
    )
    outcome_anchors = (
        list(core_axis_policy.get("outcome_phrases") or [])
        + list(core_axis_policy.get("outcome_terms") or [])
    )

    def support_for(role: str) -> list[str]:
        if role == "input_or_parameter":
            return mechanism_anchors[:1] or outcome_anchors[:1]
        if role == "measurement_or_readout":
            return input_anchors[:1] or mechanism_anchors[:1]
        if role in {"model_or_platform", "mechanism_or_material"}:
            return outcome_anchors[:1] or input_anchors[:1]
        return mechanism_anchors[:1] or outcome_anchors[:1] or input_anchors[:1]

    used_queries = {
        _normalize(plan.get("l2_query") or plan.get("query")).lower()
        for plan in prepared
    }
    for profile in profiles[1:]:
        profile_id = str(profile.get("id") or f"OBJ{len(prepared) + 1}")
        profile_role = str(profile.get("role") or "mechanism_or_material")
        profile_anchor = _normalize(profile.get("query_anchor") or profile.get("object"))
        support = [_normalize(value) for value in support_for(profile_role) if _normalize(value)]
        # Keep the standalone profile anchor even when no safe second axis is
        # available; its exact-phrase profile gate remains in force.
        short_query = _normalize(" ".join([profile_anchor, *support[:1]]))
        if not short_query:
            continue
        if short_query.lower() in used_queries:
            short_query = profile_anchor
        used_queries.add(short_query.lower())
        clone = dict(corpus_template)
        clone.update({
            "branch": f"{sub_id}:retrieval_object_{profile_id.lower()}",
            "query": short_query,
            "l2_query": short_query,
            "purpose": (
                f"retrieve SH-local corpus evidence through independent object profile "
                f"{profile_id} ({profile_role}); this branch cannot establish direct-core identity by itself"
            ),
            "query_family": "retrieval_object_profile_corpus",
            "core_evidence_capable": False,
            "retrieval_layer_role": "retrieval_object_profile_corpus",
            "preferred_retrieval_layers": ["L2_top_latest", "L4_regular"],
            "retrieval_object_profile_id": profile_id,
            "retrieval_object_profile_role": profile_role,
            "retrieval_object_profile_object": str(profile.get("object") or profile_anchor),
            "retrieval_object_profile_aliases": list(profile.get("aliases") or [])[:6],
            "retrieval_object_profile_count": len(profiles),
            "scientific_object_anchor": str(profile.get("object") or profile_anchor),
            "scientific_object_anchor_group": _unique(
                [profile_anchor] + list(profile.get("aliases") or [])
            )[:8],
            "required_object_group": _unique(
                [profile_anchor] + list(profile.get("aliases") or [])
            )[:8],
            "query_modules": {
                "object": [profile_anchor],
                "causal_input": support[:1] if profile_role != "input_or_parameter" else [],
                "method_or_assessment": support[:1] if profile_role == "input_or_parameter" else [],
                "readout_or_endpoint": support[:1] if profile_role in {"mechanism_or_material", "model_or_platform"} else [],
                "model_system": [],
                "boundary_or_cost_or_comparison": [],
                "exclusion": list(contract.get("query_forbidden_terms") or [])[:48],
            },
        })
        clone["l2_query_modules"] = dict(clone["query_modules"])
        prepared.append(clone)
    return _annotate_abstract_edge_query_plans(
        _annotate_core_corpus_query_pools(prepared)
    )


def build_dual_evidence_query_plan(
    base_query: str,
    contract: dict[str, Any],
) -> list[dict[str, Any]]:
    """Create background, discovery, and validation searches for one object.

    The three branches share the same bounded project/sub-hypothesis query.
    They preserve a theory/framework map while keeping observational discovery
    evidence distinct from causal-validation evidence.
    """
    raw_base_terms = _ranked_terms(_normalize(base_query), limit=5)
    object_policy = (
        contract.get("scientific_object_anchor_policy")
        if isinstance(contract.get("scientific_object_anchor_policy"), dict)
        else {}
    )
    scope_policy = (
        object_policy.get("subhypothesis_scope_policy")
        if isinstance(object_policy.get("subhypothesis_scope_policy"), dict)
        else contract.get("subhypothesis_scope_policy")
        if isinstance(contract.get("subhypothesis_scope_policy"), dict)
        else {}
    )
    query_forbidden_terms = _unique(
        [
            _normalize(item)
            for item in (
                list(scope_policy.get("query_forbidden_terms") or [])
                + list(contract.get("query_forbidden_terms") or [])
                + list(object_policy.get("query_forbidden_terms") or [])
            )
            if _normalize(item)
        ]
    )[:64]
    query_scope_removals: list[dict[str, Any]] = []
    component_bridge_modifier_terms_suppressed: list[str] = []
    structured_declared_input = (
        contract.get("structured_declared_input")
        if isinstance(contract.get("structured_declared_input"), dict)
        else {}
    )
    core_axis_policy = (
        contract.get("core_axis_policy")
        if isinstance(contract.get("core_axis_policy"), dict)
        else {}
    )
    if isinstance(core_axis_policy.get("comparison_structure"), dict):
        structured_declared_input = core_axis_policy.get("comparison_structure") or {}
    baseline_or_comparator_terms_for_query = _declared_baseline_or_comparator_terms(
        structured_declared_input,
        core_axis_policy.get("baseline_or_comparator"),
        core_axis_policy.get("controls"),
    )

    def query_scope_filter(
        values: Any,
        *,
        source: str,
        drop_component_bridge_modifiers: bool = False,
        drop_template_support: bool = False,
        role: str = "generic",
    ) -> list[str]:
        kept: list[str] = []
        for value in _scope_policy_values(values):
            normalized = _clean_anchor_for_query_role(
                value,
                role=role,
                baseline_or_comparator_terms=baseline_or_comparator_terms_for_query,
            )
            if not normalized:
                query_scope_removals.append({
                    "term": _normalize(value),
                    "matched_forbidden_terms": [],
                    "removed_from": source,
                    "reason": "syntax_or_baseline_not_allowed_for_query_role",
                    "query_role": role,
                })
                continue
            if role == "object" and is_query_template_support_anchor(normalized):
                query_scope_removals.append({
                    "term": normalized,
                    "matched_forbidden_terms": [],
                    "removed_from": source,
                    "reason": "method_readout_or_statistical_template_cannot_be_scientific_object_anchor",
                    "query_role": role,
                })
                continue
            scope_hits = _scope_forbidden_hits(normalized, query_forbidden_terms)
            if scope_hits:
                query_scope_removals.append({
                    "term": normalized,
                    "matched_forbidden_terms": scope_hits[:8],
                    "removed_from": source,
                    "reason": "excluded_by_current_subhypothesis_scope",
                })
                continue
            if drop_component_bridge_modifiers and is_component_bridge_modifier_only_anchor(normalized):
                component_bridge_modifier_terms_suppressed.append(normalized)
                query_scope_removals.append({
                    "term": normalized,
                    "matched_forbidden_terms": [],
                    "removed_from": source,
                    "reason": "component_bridge_modifier_only_not_object_anchor",
                })
                continue
            if drop_template_support and is_query_template_support_anchor(normalized):
                query_scope_removals.append({
                    "term": normalized,
                    "matched_forbidden_terms": [],
                    "removed_from": source,
                    "reason": "method_readout_or_statistical_template_not_primary_edge_anchor",
                    "query_role": role,
                })
                continue
            kept.append(normalized)
        return _unique(kept)

    base_terms = query_scope_filter(raw_base_terms, source="base_query_terms")[:5]
    object_phrases = [
        item
        for item in query_scope_filter(
            object_policy.get("strong_anchor_phrases")
            or [],
            source="object_phrases",
            role="object",
        )
        if item
        and is_specific_object_anchor(item)
        and not _scope_forbidden_hits(item, query_forbidden_terms)
    ][:2]
    object_terms = [
        item
        for item in query_scope_filter(
            object_policy.get("strong_anchor_terms")
            or [],
            source="object_terms",
            role="object",
        )
        if item
        and is_specific_object_anchor(item)
        and not _scope_forbidden_hits(item, query_forbidden_terms)
    ][:5]
    object_anchor_group = _unique([
        item
        for item in query_scope_filter(
            object_policy.get("object_group")
            or object_phrases + object_terms,
            source="object_anchor_group",
            role="object",
        )
        if item
        and not _scope_forbidden_hits(item, query_forbidden_terms)
    ])[:18]
    structured_input_terms = _unique(
        (
            query_scope_filter(
                list(
                    structured_declared_input.get("non_baseline_comparison_level_terms")
                    or structured_declared_input.get("comparison_level_terms")
                    or []
                )[:8],
                source="comparison_level_terms",
                role="causal_input",
            )
            + query_scope_filter(
                list(core_axis_policy.get("comparison_level_terms") or [])[:8],
                source="comparison_level_terms",
                role="causal_input",
            )
            if bool(structured_declared_input.get("comparison_levels_as_declared_input"))
            else []
        )
        + query_scope_filter(
            [structured_declared_input.get("declared_input_variable")],
            source="declared_input_variable",
            role="causal_input",
        )
    )
    input_terms = _unique(
        structured_input_terms
        + query_scope_filter(list(core_axis_policy.get("focal_variable_phrases") or [])[:3], source="core_axis_policy.focal_variable_phrases", role="causal_input")
        + query_scope_filter(list(core_axis_policy.get("focal_variable_terms") or [])[:4], source="core_axis_policy.focal_variable_terms", role="causal_input")
    )
    mechanism_terms = _unique(
        query_scope_filter(list(core_axis_policy.get("mechanism_phrases") or [])[:3], source="core_axis_policy.mechanism_phrases", drop_template_support=True, role="method_or_assessment")
        + query_scope_filter(list(core_axis_policy.get("mechanism_terms") or [])[:4], source="core_axis_policy.mechanism_terms", drop_template_support=True, role="method_or_assessment")
        + query_scope_filter(
            mechanism_outcome_synonym_terms(contract, axis="mechanism", limit=6),
            source="mechanism_synonym_terms",
            drop_template_support=True,
            role="method_or_assessment",
        )
    )
    outcome_terms = _unique(
        query_scope_filter(list(core_axis_policy.get("outcome_phrases") or [])[:3], source="core_axis_policy.outcome_phrases", drop_template_support=True, role="readout_or_endpoint")
        + query_scope_filter(list(core_axis_policy.get("outcome_terms") or [])[:4], source="core_axis_policy.outcome_terms", drop_template_support=True, role="readout_or_endpoint")
        + query_scope_filter(
            mechanism_outcome_synonym_terms(contract, axis="outcome", limit=6),
            source="outcome_synonym_terms",
            drop_template_support=True,
            role="readout_or_endpoint",
        )
    )
    outcome_phrases_for_query = [
        item
        for item in query_scope_filter(
            core_axis_policy.get("outcome_phrases") or [],
            source="core_axis_policy.outcome_phrases_for_query",
            drop_template_support=True,
            role="readout_or_endpoint",
        )
        if item and not _scope_forbidden_hits(item, query_forbidden_terms)
    ][:6]
    evidence_paths = [
        dict(path)
        for path in (contract.get("evidence_paths") or [])
        if isinstance(path, dict)
    ]
    comparative_object_parts = [
        item
        for item in query_scope_filter(
            object_policy.get("comparative_declared_object_parts") or [],
            source="comparative_declared_object_parts",
            role="object",
        )
        if item and not _scope_forbidden_hits(item, query_forbidden_terms)
    ]
    object_clause_terms = _unique(
        object_anchor_group
        + object_phrases
        + object_terms
    )[:12]
    object_clause = " OR ".join(object_clause_terms[:6])
    panel_policy = (
        contract.get("multi_entity_panel_policy")
        if isinstance(contract.get("multi_entity_panel_policy"), dict)
        else {}
    )
    panel_path_policies = [
        dict(item)
        for item in (panel_policy.get("path_policies") or [])
        if isinstance(item, dict)
    ]
    object_maturity_audit = (
        contract.get("object_maturity_audit")
        if isinstance(contract.get("object_maturity_audit"), dict)
        else {}
    )
    direct_core_allowed_by_maturity = _object_maturity_direct_core_allowed(
        object_maturity_audit
    )
    component_bridge_anchor_quality = (
        object_maturity_audit.get("component_bridge_anchor_quality")
        if isinstance(object_maturity_audit.get("component_bridge_anchor_quality"), dict)
        else {}
    )
    component_bridge_anchor_groups_typed = bool(
        object_policy.get("component_bridge_anchor_groups_typed")
        or object_maturity_audit.get("typed_component_bridge_anchors")
        or component_bridge_anchor_quality
    )
    component_bridge_object_anchor_group = _unique(
        list(object_policy.get("component_bridge_object_anchor_phrases") or [])
        + _object_maturity_anchor_values(object_maturity_audit, "object_anchors", limit=24)
    )
    component_bridge_method_anchor_group = _unique(
        list(object_policy.get("component_bridge_method_or_platform_anchor_phrases") or [])
        + _object_maturity_anchor_values(object_maturity_audit, "method_or_platform_anchors", limit=24)
    )
    component_bridge_readout_anchor_group = _unique(
        list(object_policy.get("component_bridge_readout_anchor_phrases") or [])
        + _object_maturity_anchor_values(object_maturity_audit, "readout_anchors", limit=16)
    )
    component_bridge_model_system_anchor_group = _unique(
        list(object_policy.get("component_bridge_model_system_anchor_phrases") or [])
        + _object_maturity_anchor_values(object_maturity_audit, "model_system_anchors", limit=16)
    )
    typed_component_bridge_groups_available = bool(
        component_bridge_anchor_groups_typed
        and (
            component_bridge_object_anchor_group
            or component_bridge_method_anchor_group
            or component_bridge_readout_anchor_group
            or component_bridge_model_system_anchor_group
            or component_bridge_anchor_quality
        )
    )
    raw_maturity_component_anchor_group = _unique(
        component_bridge_object_anchor_group
        + object_anchor_group
    )
    maturity_component_anchor_group = query_scope_filter(
        raw_maturity_component_anchor_group,
        source="component_bridge_anchor_group",
        drop_component_bridge_modifiers=True,
        role="object",
    )[:32]

    def build_component_bridge_query_plan() -> list[dict[str, Any]]:
        """Route unanchored future objects through current component literature."""

        if direct_core_allowed_by_maturity:
            return []
        if not typed_component_bridge_groups_available:
            return []
        if component_bridge_anchor_quality.get("passes") is False:
            return []
        method_support_anchors = query_scope_filter(
            component_bridge_method_anchor_group,
            source="component_bridge_method_or_platform_query_anchors",
            drop_component_bridge_modifiers=True,
            role="method_or_assessment",
        )
        readout_support_anchors = query_scope_filter(
            component_bridge_readout_anchor_group,
            source="component_bridge_readout_query_anchors",
            drop_component_bridge_modifiers=True,
            role="readout_or_endpoint",
        )
        model_support_anchors = query_scope_filter(
            component_bridge_model_system_anchor_group,
            source="component_bridge_model_system_query_anchors",
            drop_component_bridge_modifiers=True,
            role="model_system",
        )
        support_anchors = _unique(
            method_support_anchors
            + readout_support_anchors
            + model_support_anchors
        )[:18]
        anchors = query_scope_filter(
            component_bridge_object_anchor_group,
            source="component_bridge_query_anchors",
            drop_component_bridge_modifiers=True,
            role="object",
        )[:12]
        if not anchors or not support_anchors:
            return []
        sub_id = str(contract.get("sub_hypothesis_id") or "subhypothesis")

        def short_query(*parts: Any, limit: int = 12) -> str:
            terms: list[str] = []
            for part in parts:
                if isinstance(part, (list, tuple, set)):
                    for nested in part:
                        normalized_nested = _clean_anchor_for_query_role(
                            nested,
                            role="generic",
                            baseline_or_comparator_terms=baseline_or_comparator_terms_for_query,
                        )
                        if not normalized_nested:
                            continue
                        if _scope_forbidden_hits(normalized_nested, query_forbidden_terms):
                            continue
                        if is_component_bridge_modifier_only_anchor(normalized_nested):
                            component_bridge_modifier_terms_suppressed.append(normalized_nested)
                            continue
                        terms.append(normalized_nested)
                    continue
                normalized = _clean_anchor_for_query_role(
                    part,
                    role="generic",
                    baseline_or_comparator_terms=baseline_or_comparator_terms_for_query,
                )
                if not normalized:
                    continue
                if _scope_forbidden_hits(normalized, query_forbidden_terms):
                    continue
                if is_component_bridge_modifier_only_anchor(normalized):
                    component_bridge_modifier_terms_suppressed.append(normalized)
                    continue
                terms.append(normalized)
            return _normalize(" ".join(_unique(terms)[: max(1, min(int(limit), 12))]))

        def module_terms(values: Any, *, limit: int = 8, role: str = "generic") -> list[str]:
            terms: list[str] = []
            source_values = values if isinstance(values, (list, tuple, set)) else [values]
            for value in source_values:
                normalized = _clean_anchor_for_query_role(
                    value,
                    role=role,
                    baseline_or_comparator_terms=baseline_or_comparator_terms_for_query,
                )
                if not normalized:
                    continue
                if _scope_forbidden_hits(normalized, query_forbidden_terms):
                    continue
                if is_component_bridge_modifier_only_anchor(normalized):
                    component_bridge_modifier_terms_suppressed.append(normalized)
                    continue
                terms.append(normalized)
            return _unique(terms)[: max(0, int(limit))]

        def query_modules(
            *,
            object_values: Any,
            causal_input_values: Any = (),
            method_values: Any = (),
            readout_values: Any = (),
            model_values: Any = (),
            boundary_values: Any = (),
        ) -> dict[str, Any]:
            modules = {
                "object": module_terms(object_values, limit=8, role="object"),
                "causal_input": module_terms(causal_input_values, limit=6, role="causal_input"),
                "method_or_assessment": module_terms(method_values, limit=6, role="method_or_assessment"),
                "readout_or_endpoint": module_terms(readout_values, limit=6, role="readout_or_endpoint"),
                "model_system": module_terms(model_values, limit=4, role="model_system"),
                "boundary_or_cost_or_comparison": module_terms(boundary_values, limit=5, role="boundary_or_cost_or_comparison"),
                "exclusion": module_terms(query_forbidden_terms, limit=24),
            }
            modules["module_policy"] = (
                "OR within each nonempty module; AND across object plus support modules; "
                "exclusions are SH-local and enforced by provider syntax when supported "
                "or by the immediate local fast-reject gate"
            )
            return modules

        def module_compact_query(
            modules: dict[str, Any],
            *,
            include_boundary: bool = True,
            limit: int = 10,
        ) -> str:
            """Build a balanced provider-safe query from structured modules."""

            slots = (
                ("object", 2),
                ("causal_input", 2),
                ("method_or_assessment", 1),
                ("readout_or_endpoint", 1),
                ("model_system", 1),
                ("boundary_or_cost_or_comparison", 1 if include_boundary else 0),
            )
            terms: list[str] = []
            for key, slot_limit in slots:
                if slot_limit <= 0:
                    continue
                values = modules.get(key) if isinstance(modules, dict) else []
                if not isinstance(values, (list, tuple)):
                    continue
                terms.extend(str(value) for value in values[:slot_limit] if str(value or "").strip())
            return _normalize(" ".join(_unique(terms)[: max(1, min(int(limit), 12))]))

        bridge_anchors = _unique(
            anchors[:6]
            + method_support_anchors[:4]
            + model_support_anchors[:4]
        )
        boundary_anchors: list[str] = []
        shared = {
            "path_composition_policy": "object_maturity_component_bridge_boundary_paths",
            "scientific_object_anchor": str(contract.get("scientific_object") or ""),
            "scientific_object_anchor_group": anchors[:18],
            "required_object_group": anchors[:18],
            "required_causal_input_group": input_terms[:12],
            "causal_input_anchor_group": input_terms[:12],
            "required_method_or_mechanism_group": method_support_anchors[:18],
            "optional_model_group": model_support_anchors[:18],
            "optional_readout_group": readout_support_anchors[:18],
            "modifiers": list(object_maturity_audit.get("role_modifiers") or [])[:18],
            "component_anchor_group": anchors[:18],
            "component_support_anchor_group": support_anchors[:18],
            "component_bridge_anchor_quality": component_bridge_anchor_quality,
            "object_maturity_audit": object_maturity_audit,
            "object_maturity_status": _object_maturity_status_from_audit(object_maturity_audit),
            "direct_core_evidence_allowed": False,
            "direct_core_disallowed_by_object_maturity": True,
            "primary_field": str(contract.get("primary_field") or ""),
            "causal_edge_anchors": _unique(input_terms + mechanism_terms + outcome_terms)[:12],
            "excluded_nearby_objects": list(contract.get("excluded_nearby_objects") or []),
            "query_forbidden_terms": query_forbidden_terms,
            "subhypothesis_scope_policy": scope_policy,
            "query_scope_removals": query_scope_removals[:64],
            "component_bridge_modifier_terms_suppressed": _unique(
                component_bridge_modifier_terms_suppressed
            )[:64],
            "core_evidence_capable": False,
            "component_evidence_counts_as_core": False,
            "component_evidence_counts_as_panel_core": False,
            "can_independently_falsify_sh": False,
            "missing_path_blocks_sh": False,
            "negative_evidence_interpretation": (
                "component, bridge, or boundary evidence informs feasibility and gaps; "
                "it must not be counted as direct-core validation of the final unanchored object"
            ),
        }
        component_modules = query_modules(
            object_values=anchors[:6],
            causal_input_values=input_terms[:4],
            method_values=method_support_anchors[:5] or mechanism_terms[:4] or input_terms[:4],
            readout_values=readout_support_anchors[:4] or outcome_terms[:4],
            model_values=model_support_anchors[:3],
        )
        bridge_modules = query_modules(
            object_values=anchors[:5],
            causal_input_values=input_terms[:4],
            method_values=method_support_anchors[:4] or mechanism_terms[:3],
            readout_values=readout_support_anchors[:3] or outcome_terms[:3],
            model_values=model_support_anchors[:4],
            boundary_values=bridge_anchors[:5],
        )
        boundary_modules = query_modules(
            object_values=anchors[:5],
            causal_input_values=input_terms[:4],
            method_values=method_support_anchors[:4] or mechanism_terms[:3],
            readout_values=readout_support_anchors[:3] or outcome_terms[:3],
            model_values=model_support_anchors[:3],
            boundary_values=boundary_anchors[:6],
        )
        review_modules = query_modules(
            object_values=anchors[:5],
            causal_input_values=input_terms[:3],
            method_values=method_support_anchors[:3],
            readout_values=readout_support_anchors[:2],
            model_values=model_support_anchors[:3],
            boundary_values=bridge_anchors[:3] + boundary_anchors[:3],
        )
        component_query = module_compact_query(component_modules, include_boundary=False)
        bridge_query = module_compact_query(bridge_modules)
        boundary_query = module_compact_query(boundary_modules)
        review_query = module_compact_query(review_modules)
        shared["query_scope_removals"] = query_scope_removals[:64]
        shared["component_bridge_modifier_terms_suppressed"] = _unique(
            component_bridge_modifier_terms_suppressed
        )[:64]
        return _finalize_retrieval_object_query_plan([
            {
                "branch": f"{sub_id}:component_evidence",
                "query": component_query,
                "l2_query": short_query(anchors[:5], input_terms[:3], mechanism_terms[:3], outcome_terms[:2]),
                "query_modules": component_modules,
                "l2_query_modules": component_modules,
                "purpose": "retrieve current component, enabling-method, platform, model-system, or readout evidence without treating it as direct-core proof of the final object",
                "query_family": "object_maturity_component_evidence",
                "evidence_kind": "mechanism_discovery",
                "evidence_path_id": "component_evidence_path",
                "evidence_path_role": "component_evidence",
                "evidence_path_polarity": "supportive",
                "target_lane": "COMPONENT_EVIDENCE",
                "preferred_retrieval_layers": ["L2_top_latest", "L4_regular"],
                "retrieval_layer_role": "component_evidence",
                "failure_scope": "component_support_gap_not_direct_core_falsification",
                "query_requires_declared_input": bool(input_terms),
                **shared,
            },
            {
                "branch": f"{sub_id}:translational_bridge",
                "query": bridge_query,
                "l2_query": short_query(anchors[:4], input_terms[:3], bridge_anchors[:4]),
                "query_modules": bridge_modules,
                "l2_query_modules": bridge_modules,
                "purpose": "retrieve model-system, cross-scale, or deployment bridge evidence that may connect components to the long-range objective",
                "query_family": "object_maturity_translational_bridge",
                "evidence_kind": "association",
                "evidence_path_id": "translational_bridge_path",
                "evidence_path_role": "translational_bridge",
                "evidence_path_polarity": "boundary",
                "target_lane": "TRANSLATIONAL_BRIDGE_EVIDENCE",
                "preferred_retrieval_layers": ["L2_top_latest", "L4_regular"],
                "retrieval_layer_role": "translational_bridge",
                "failure_scope": "translation_bridge_gap",
                "query_requires_declared_input": bool(input_terms),
                **shared,
            },
            {
                "branch": f"{sub_id}:boundary_or_safety",
                "query": boundary_query,
                "l2_query": short_query(anchors[:4], input_terms[:3], boundary_anchors[:4]),
                "query_modules": boundary_modules,
                "l2_query_modules": boundary_modules,
                "purpose": "retrieve safety, failure, instability, heterogeneity, or boundary evidence that limits extrapolation from components to the final object",
                "query_family": "object_maturity_boundary_or_safety",
                "evidence_kind": "causal_validation",
                "evidence_path_id": "boundary_or_safety_evidence_path",
                "evidence_path_role": "boundary_or_safety_evidence",
                "evidence_path_polarity": "boundary",
                "target_lane": "BOUNDARY_OR_NEGATIVE_EVIDENCE",
                "preferred_retrieval_layers": ["L2_top_latest", "L4_regular"],
                "retrieval_layer_role": "boundary_or_safety_evidence",
                "failure_scope": "boundary_safety_gap",
                "query_requires_declared_input": bool(input_terms),
                **shared,
            },
            {
                "branch": f"{sub_id}:component_bridge_context_review",
                "query": review_query,
                "l2_query": short_query(anchors[:6], bridge_anchors[:4]),
                "query_modules": review_modules,
                "l2_query_modules": review_modules,
                "purpose": "map definitions, feasibility, and unresolved bridge gaps for the immature direct object; reviews remain background-only",
                "query_family": "object_maturity_context_review",
                "evidence_kind": "theoretical_framework",
                "evidence_path_id": "context_review",
                "evidence_path_role": "background_or_framework",
                "evidence_path_polarity": "context",
                "target_lane": "THEORETICAL_FRAMEWORK",
                "preferred_retrieval_layers": ["L0_review"],
                "retrieval_layer_role": "context_review",
                "failure_scope": "context_only_gap",
                "query_requires_declared_input": False,
                **shared,
            },
        ], contract)

    def panel_query_marker_terms(evidence_kind: str, tier: str) -> list[str]:
        kind = str(evidence_kind or "").lower()
        if kind == "predictive_validation":
            return ["external validation", "independent cohort", "calibration", "prediction"]
        if kind in {"causal_validation", "experimental_evidence"}:
            return ["validation", "controlled study", "experiment", "assay", "perturbation"]
        if kind == "causal_identification":
            return ["comparison", "baseline", "incremental value", "validation"]
        if kind == "mechanism_discovery":
            return ["mechanism", "pathway", "profiling", "association", "measurement"]
        if kind == "theoretical_framework":
            return ["review", "framework", "model", "theory"]
        return (
            ["association", "cohort", "observational", "measurement"]
            if str(tier or "").lower() != "core"
            else ["validation", "model", "comparison"]
        )

    def panel_short_branch_query(*parts: str, limit: int = 12) -> str:
        terms: list[str] = []
        for part in parts:
            normalized = _normalize(part)
            if not normalized:
                continue
            if " OR " in part or " AND " in part or "(" in part or ")" in part:
                terms.extend(_ranked_terms(normalized, limit=limit))
            else:
                terms.append(normalized)
        return _normalize(" ".join(_unique(terms)[: max(4, min(int(limit), 12))]))

    def panel_branch_slug(value: str, fallback: str) -> str:
        normalized = re.sub(r"[^a-z0-9]+", "_", str(value or "").lower()).strip("_")
        return normalized[:64] or fallback

    def panel_path_source_query(policy: dict[str, Any], path: dict[str, Any]) -> str:
        return _normalize(
            str(policy.get("retrieval_query") or path.get("retrieval_query") or "")
            or " ".join(str(step) for step in (path.get("causal_steps") or []) if str(step).strip())
            or base_query
        )

    def build_panel_query_plan() -> list[dict[str, str]]:
        if not panel_policy.get("is_multi_entity_panel") or not panel_path_policies:
            return []
        sub_id = str(contract.get("sub_hypothesis_id") or "subhypothesis")
        policy_by_key = {
            str(item.get("id") or item.get("role") or "").strip().lower(): item
            for item in panel_path_policies
        }
        policy_by_role = {
            str(item.get("role") or item.get("id") or "").strip().lower(): item
            for item in panel_path_policies
        }
        path_items: list[tuple[dict[str, Any], dict[str, Any]]] = []
        for index, path in enumerate(evidence_paths):
            key = str(path.get("id") or path.get("role") or "").strip().lower()
            role_key = str(path.get("role") or path.get("id") or "").strip().lower()
            policy = policy_by_key.get(key) or policy_by_role.get(role_key) or {}
            if not policy:
                policy = {
                    "id": str(path.get("id") or path.get("role") or f"path_{index + 1}"),
                    "role": str(path.get("role") or path.get("id") or ""),
                    "panel_evidence_tier": "support",
                    "evidence_kind": "association",
                    "retrieval_query": str(path.get("retrieval_query") or ""),
                    "component_anchor_group": list(path.get("component_anchor_group") or []),
                }
            path_items.append((path, policy))
        path_items.sort(key=lambda pair: 0 if str(pair[1].get("panel_evidence_tier") or "") == "core" else 1)
        shared = {
            "path_composition_policy": "multi_entity_panel_paths_independent_or",
            "scientific_object_anchor": str(contract.get("scientific_object") or ""),
            "scientific_object_anchor_group": object_anchor_group,
            "main_retrieval_query": panel_short_branch_query(
                *object_clause_terms[:5],
                *_ranked_terms(base_query, limit=8),
                limit=12,
            ),
            "primary_field": str(contract.get("primary_field") or ""),
            "causal_edge_anchors": _unique(input_terms + mechanism_terms + outcome_terms)[:16],
            "excluded_nearby_objects": list(contract.get("excluded_nearby_objects") or []),
            "multi_entity_panel": True,
            "panel_object_anchor_group": list(panel_policy.get("panel_object_anchor_group") or [])[:24],
        }
        plans: list[dict[str, Any]] = []
        if object_clause:
            review_layer_policy = panel_path_retrieval_layer_policy(
                tier="context",
                role="background_or_framework",
                evidence_kind="theoretical_framework",
            )
            review_query = panel_short_branch_query(
                *object_clause_terms[:7],
                *panel_query_marker_terms("theoretical_framework", "context"),
                limit=12,
            )
            plans.append({
                "branch": f"{sub_id}:panel_background_framework",
                "query": review_query,
                "l2_query": _normalize(" ".join(object_clause_terms[:8])),
                "purpose": "map panel-level definitions, reporting standards, and synthesized evidence; reviews remain background-only",
                "query_family": "multi_entity_panel_background",
                "evidence_kind": "theoretical_framework",
                "evidence_path_id": "context_review",
                "evidence_path_role": "background_or_framework",
                "evidence_path_polarity": "context",
                "target_lane": "THEORETICAL_FRAMEWORK",
                "panel_evidence_tier": "context",
                "panel_component_path": False,
                "component_anchor_group": [],
                "preferred_retrieval_layers": list(review_layer_policy.get("preferred_retrieval_layers") or []),
                "preprint_signal_layers": list(review_layer_policy.get("preprint_signal_layers") or []),
                "retrieval_layer_role": str(review_layer_policy.get("retrieval_layer_role") or "context_or_boundary"),
                "core_evidence_capable": False,
                "panel_core_path": False,
                "component_evidence_counts_as_core": False,
                "component_evidence_counts_as_panel_core": False,
                "failure_scope": "supporting_gap_or_boundary_context",
                "can_independently_falsify_sh": False,
                "missing_path_blocks_sh": False,
                "negative_evidence_interpretation": "missing context evidence limits boundary framing but does not falsify the whole SH",
                **shared,
            })
        for ordinal, (path, policy) in enumerate(path_items, start=1):
            tier = str(policy.get("panel_evidence_tier") or "support")
            evidence_kind = str(policy.get("evidence_kind") or "association")
            role = str(policy.get("role") or path.get("role") or path.get("id") or "")
            layer_policy = (
                policy.get("retrieval_layer_policy")
                if isinstance(policy.get("retrieval_layer_policy"), dict)
                else panel_path_retrieval_layer_policy(
                    tier=tier,
                    role=role,
                    evidence_kind=evidence_kind,
                )
            )
            source_query = panel_path_source_query(policy, path)
            source_terms = _ranked_terms(source_query, limit=12)
            source_term_set = {term.lower() for term in source_terms}
            relevant_global_components = [
                anchor
                for anchor in (panel_policy.get("component_anchor_group") or [])
                if any(
                    term
                    and (
                        term in _normalize(anchor).lower().split()
                        or _normalize(anchor).lower().startswith(term)
                    )
                    for term in source_term_set
                )
            ]
            component_group = _unique(
                list(policy.get("component_anchor_group") or [])
                + list(path.get("component_anchor_group") or [])
                + relevant_global_components
            )[:18]
            marker_terms = panel_query_marker_terms(evidence_kind, tier)
            if tier == "core":
                l2_query = _normalize(" ".join(_unique(object_clause_terms[:5] + source_terms[:9])))
                query_text = panel_short_branch_query(
                    *object_clause_terms[:4],
                    *source_terms[:8],
                    *marker_terms[:4],
                    limit=12,
                ) or source_query
            else:
                l2_query = _normalize(" ".join(_unique(component_group[:6] + source_terms[:10]))) or source_query
                support_terms = _unique(component_group[:6] + source_terms[:8])
                query_text = panel_short_branch_query(
                    *support_terms[:8],
                    *marker_terms[:4],
                    limit=12,
                ) or source_query
            branch_slug = panel_branch_slug(str(policy.get("id") or role), f"panel_path_{ordinal}")
            normalized_role = _normalize(role).lower()
            polarity = str(path.get("polarity") or policy.get("polarity") or "").strip().lower()
            if not polarity:
                polarity = (
                    "opposing"
                    if any(marker in normalized_role for marker in ("adverse", "reversal", "opposing", "tradeoff", "trade-off", "rebound", "burden"))
                    else "boundary"
                    if any(marker in normalized_role for marker in ("boundary", "generalization", "generalisation"))
                    else "supportive"
                )
            target_lane = (
                "ADVERSE_OR_REVERSAL_EVIDENCE"
                if polarity == "opposing" or any(marker in normalized_role for marker in ("adverse", "reversal", "opposing", "tradeoff", "trade-off", "rebound", "burden"))
                else "BOUNDARY_OR_NEGATIVE_EVIDENCE"
                if polarity == "boundary" or any(marker in normalized_role for marker in ("boundary", "generalization", "generalisation"))
                else "PREDICTIVE_VALIDATION"
                if evidence_kind == "predictive_validation"
                else "CAUSAL_VALIDATION"
                if tier == "core"
                else "MECHANISM_DISCOVERY"
            )
            can_falsify = bool(
                path.get("can_independently_falsify_sh")
                if isinstance(path.get("can_independently_falsify_sh"), bool)
                else layer_policy.get("core_evidence_capable")
            )
            failure_scope = str(path.get("failure_scope") or "").strip() or (
                "whole_sh_core_falsification"
                if can_falsify
                else "supporting_gap_or_mechanism_weakening"
            )
            plans.append({
                "branch": f"{sub_id}:{branch_slug}",
                "query": query_text,
                "l2_query": l2_query,
                "purpose": (
                    "retrieve panel-level core validation or incremental-value evidence"
                    if tier == "core"
                    else "retrieve component-level support evidence for one independent panel path; this branch does not by itself satisfy panel-level core"
                ),
                "query_family": f"multi_entity_panel_{tier}",
                "evidence_kind": evidence_kind,
                "evidence_path_id": str(path.get("id") or policy.get("id") or branch_slug),
                "evidence_path_role": role,
                "evidence_path_polarity": polarity,
                "target_lane": target_lane,
                "panel_evidence_tier": tier,
                "panel_component_path": tier != "core",
                "component_anchor_group": component_group,
                "preferred_retrieval_layers": list(layer_policy.get("preferred_retrieval_layers") or []),
                "preprint_signal_layers": list(layer_policy.get("preprint_signal_layers") or []),
                "retrieval_layer_role": str(layer_policy.get("retrieval_layer_role") or ""),
                "core_evidence_capable": bool(layer_policy.get("core_evidence_capable")),
                "panel_core_path": bool(layer_policy.get("panel_core_path")),
                "component_evidence_counts_as_core": layer_policy.get("component_evidence_counts_as_core"),
                "component_evidence_counts_as_panel_core": layer_policy.get("component_evidence_counts_as_panel_core"),
                "failure_scope": failure_scope,
                "can_independently_falsify_sh": can_falsify,
                "missing_path_blocks_sh": bool(path.get("missing_path_blocks_sh") is True and can_falsify),
                "negative_evidence_interpretation": (
                    "negative core/integrative validation can falsify or materially weaken the whole SH"
                    if can_falsify
                    else "negative or absent support evidence becomes a localized mechanism/boundary gap"
                ),
                **shared,
            })
        return _finalize_retrieval_object_query_plan(plans[:8], contract)

    component_bridge_query_plan = build_component_bridge_query_plan()
    if component_bridge_query_plan:
        return component_bridge_query_plan
    if not direct_core_allowed_by_maturity:
        return []

    panel_query_plan = build_panel_query_plan()
    if panel_query_plan:
        return panel_query_plan

    if str(contract.get("evidence_mode") or "") == PREDICTIVE_GENERALIZATION_EVIDENCE_MODE:
        identity_terms = _unique(object_phrases + object_terms)[:6]
        if not identity_terms:
            return []
        identity_clause = " OR ".join(identity_terms[:4])
        moderator_terms = _unique(
            list(contract.get("moderator_phrases") or [])
            + list(contract.get("moderator_terms") or [])
        )[:10]
        moderator_clause = " OR ".join(moderator_terms[:6]) or "external validation OR subgroup performance"
        bounded_query = _normalize(f"({identity_clause}) AND ({moderator_clause})")
        validation_markers = (
            "external validation OR temporal validation OR geographic validation OR multi-site "
            "OR multicenter OR independent cohort OR calibration OR discrimination OR transportability"
        )
        boundary_markers = (
            "subgroup performance OR performance heterogeneity OR fairness OR bias OR domain shift "
            "OR distribution shift OR calibration OR transportability"
        )
        adverse_markers = (
            "distribution shift OR robustness failure OR fairness degradation OR performance regression "
            "OR negative transfer OR adverse event OR toxicity OR nonresponse OR reduced effectiveness "
            "OR failure mode OR null effect"
        )
        review_markers = "systematic review OR scoping review OR meta-analysis OR review OR framework"
        sub_id = str(contract.get("sub_hypothesis_id") or "subhypothesis")
        shared = {
            "path_composition_policy": "predictive_generalization_validation_paths",
            "scientific_object_anchor": str(contract.get("scientific_object") or ""),
            "scientific_object_anchor_group": object_anchor_group,
            "primary_field": str(contract.get("primary_field") or ""),
            "causal_edge_anchors": _unique(input_terms + mechanism_terms + outcome_terms + moderator_terms)[:16],
            "moderator_anchors": moderator_terms,
            "excluded_nearby_objects": list(contract.get("excluded_nearby_objects") or []),
        }
        return _finalize_retrieval_object_query_plan([
            {
                "branch": f"{sub_id}:predictive_generalization_review",
                "query": _normalize(f"({bounded_query}) AND ({review_markers})"),
                "l2_query": bounded_query,
                "purpose": "map definitions, reporting standards, and synthesized evidence for the declared model-generalization boundary",
                "query_family": "predictive_generalization_review",
                "evidence_kind": "theoretical_framework",
                "evidence_path_id": "context_review",
                "evidence_path_role": "background_or_framework",
                "evidence_path_polarity": "context",
                "target_lane": "THEORETICAL_FRAMEWORK",
                "preferred_retrieval_layers": ["L0_review"],
                "retrieval_layer_role": "context_review",
                "core_evidence_capable": False,
                "component_evidence_counts_as_core": False,
                "component_evidence_counts_as_panel_core": False,
                **shared,
            },
            {
                "branch": f"{sub_id}:predictive_external_validation",
                "query": _normalize(f"({bounded_query}) AND ({validation_markers})"),
                "l2_query": bounded_query,
                "purpose": "identify independent external, temporal, geographic, or multi-site validation with quantitative model performance",
                "query_family": "predictive_external_validation",
                "evidence_kind": "predictive_validation",
                "evidence_path_id": "predictive_validation",
                "evidence_path_role": "predictive_validation",
                "evidence_path_polarity": "supportive",
                "target_lane": "PREDICTIVE_VALIDATION",
                "preferred_retrieval_layers": ["L2_top_latest", "L4_regular"],
                "retrieval_layer_role": "predictive_generalization",
                "core_evidence_capable": True,
                **shared,
            },
            {
                "branch": f"{sub_id}:predictive_boundary_validation",
                "query": _normalize(f"({bounded_query}) AND ({boundary_markers})"),
                "l2_query": bounded_query,
                "purpose": "identify subgroup, fairness, calibration, transportability, and distribution-shift boundary evidence",
                "query_family": "predictive_boundary_validation",
                "evidence_kind": "predictive_validation",
                "evidence_path_id": "boundary_or_generalization_path",
                "evidence_path_role": "boundary_or_negative_evidence",
                "evidence_path_polarity": "boundary",
                "target_lane": "BOUNDARY_OR_NEGATIVE_EVIDENCE",
                "preferred_retrieval_layers": ["L2_top_latest", "L4_regular"],
                "retrieval_layer_role": "boundary_or_negative_evidence",
                "core_evidence_capable": False,
                **shared,
            },
            {
                "branch": f"{sub_id}:predictive_adverse_or_reversal",
                "query": _normalize(f"({bounded_query}) AND ({adverse_markers})"),
                "l2_query": bounded_query,
                "purpose": "identify adverse, reversal, null, robustness-failure, or performance-regression evidence for the declared predictive model boundary",
                "query_family": "predictive_adverse_or_reversal",
                "evidence_kind": "causal_validation",
                "evidence_path_id": "adverse_or_reversal_path",
                "evidence_path_role": "adverse_or_reversal",
                "evidence_path_polarity": "opposing",
                "target_lane": "ADVERSE_OR_REVERSAL_EVIDENCE",
                "preferred_retrieval_layers": ["L2_top_latest", "L4_regular"],
                "retrieval_layer_role": "adverse_or_reversal",
                "core_evidence_capable": True,
                "can_independently_falsify_sh": True,
                "failure_scope": "whole_sh_core_falsification",
                "negative_evidence_interpretation": "opposing predictive validation can falsify or materially qualify the SH after full-text review",
                **shared,
            },
        ], contract)

    def evidence_path(role: str) -> dict[str, Any]:
        return next(
            (
                path
                for path in evidence_paths
                if str(path.get("role") or path.get("id") or "").strip().lower() == role
            ),
            {},
        )

    def evidence_path_id(role: str, fallback: str) -> str:
        path = evidence_path(role)
        return str(path.get("id") or fallback)

    def path_failure_metadata(role: str, *, fallback_can_falsify: bool) -> dict[str, Any]:
        path = evidence_path(role)
        can_falsify = (
            path.get("can_independently_falsify_sh")
            if isinstance(path.get("can_independently_falsify_sh"), bool)
            else fallback_can_falsify
        )
        failure_scope = str(path.get("failure_scope") or "").strip() or (
            "whole_sh_core_falsification"
            if can_falsify
            else "supporting_gap_or_mechanism_weakening"
        )
        return {
            "evidence_path_polarity": str(path.get("polarity") or ""),
            "failure_scope": failure_scope,
            "can_independently_falsify_sh": bool(can_falsify),
            "missing_path_blocks_sh": bool(path.get("missing_path_blocks_sh") is True and can_falsify),
            "negative_evidence_interpretation": (
                "opposing evidence can falsify, reverse, or materially qualify the primary SH claim"
                if str(path.get("polarity") or "").lower() == "opposing"
                else
                "negative core/validation evidence can falsify or materially weaken the whole SH"
                if can_falsify
                else "negative or absent support evidence becomes a localized mechanism/boundary gap"
            ),
        }

    def path_causal_query(role: str, fallback: str) -> str:
        path = evidence_path(role)
        source_query_terms = _ranked_terms(str(path.get("retrieval_query") or ""), limit=8)
        steps = [
            _normalize(step)
            for step in (path.get("causal_steps") or [])
            if _normalize(step)
        ]
        if not steps and not source_query_terms:
            return fallback
        if comparative_object_parts:
            object_terms_for_query = _unique(
                comparative_object_parts
                + [
                    term for term in object_anchor_group[:8]
                    if not any(_object_phrase_overlap(term, part) for part in comparative_object_parts)
                ]
            )[:8]
            object_token_set = {
                token
                for part in object_terms_for_query
                for token in _object_anchor_tokens(part)
            }
            path_axis_terms = _unique(
                outcome_phrases_for_query[:4]
                + outcome_terms[:4]
                + source_query_terms
                + [
                    term
                    for step in steps
                    for term in _ranked_terms(step, limit=4)
                ]
            )
            path_axis_terms = [
                term
                for term in path_axis_terms
                if term
                and not (
                    set(_object_anchor_tokens(term))
                    and set(_object_anchor_tokens(term)) <= object_token_set
                )
                and term.lower() not in {
                    "type", "technology", "technologies", "storage technology",
                    "energy storage technology", "compared", "comparison",
                }
            ][:8]
            if object_terms_for_query and path_axis_terms:
                return _normalize(
                    f"({' OR '.join(object_terms_for_query[:6])}) AND "
                    f"({' OR '.join(path_axis_terms[:6])})"
                ) or fallback
        path_groups = [
            _ranked_terms(step, limit=4)
            for step in steps
        ]
        if source_query_terms:
            path_groups = [source_query_terms[:4], *path_groups]
        path_groups = [group for group in path_groups if group]
        if not path_groups:
            return fallback
        clauses = [f"({object_clause})"] if object_clause else []
        clauses.extend(f"({' OR '.join(group[:3])})" for group in path_groups[:3])
        return _normalize(" AND ".join(clauses)) or fallback

    def experimental_context_terms() -> list[str]:
        validation_path = evidence_path("causal_validation")
        structured_input = (
            contract.get("structured_declared_input")
            if isinstance(contract.get("structured_declared_input"), dict)
            else {}
        )
        sources = [
            str(structured_input.get("declared_input_variable") or contract.get("independent_variable") or ""),
            *[
                str(item)
                for item in (
                    structured_input.get("non_baseline_comparison_level_terms")
                    or structured_input.get("comparison_level_terms")
                    if bool(structured_input.get("comparison_levels_as_declared_input"))
                    else []
                )
            ],
            *[str(step) for step in (validation_path.get("causal_steps") or [])],
        ]
        source_text = " ".join(
            _clean_comparison_fragment(source)
            for source in sources
            if _clean_comparison_fragment(source)
        )
        # These terms originate in the sub-hypothesis contract rather than a
        # discipline vocabulary.  They describe the named intervention or
        # model entity that makes the validation lane distinct from discovery.
        terms = _ranked_terms(source_text, limit=10)
        return [
            term for term in terms
            if term not in {"analysis", "data", "mechanism", "model", "models", "validation"}
            and term not in {"vs", "vs.", "versus"}
            and _clean_anchor_for_query_role(
                term,
                role="causal_input",
                baseline_or_comparator_terms=baseline_or_comparator_terms_for_query,
            )
        ][:6]

    epistemic_profile = (
        contract.get("epistemic_profile")
        if isinstance(contract.get("epistemic_profile"), dict)
        else {}
    )
    primary_epistemic_mode = str(epistemic_profile.get("primary_mode") or "")
    role_contract = (
        contract.get("evidence_role_contract")
        if isinstance(contract.get("evidence_role_contract"), dict)
        else {}
    )
    if primary_epistemic_mode and (
        not bool(epistemic_profile.get("requires_intervention") is True)
        or bool(role_contract.get("selected_roles"))
    ):
        # A profile-compatible SH must never be routed through the default
        # intervention/adverse/boundary query trio.  Keep one direct-core path
        # and one qualification path, both already normalized from the SH.
        sub_id = str(contract.get("sub_hypothesis_id") or "subhypothesis")
        profile_paths = [
            path for path in evidence_paths
            if str(path.get("role") or path.get("id") or "").strip()
        ]
        if not profile_paths:
            profile_paths = [{
                "id": "direct_claim_validation",
                "role": "direct_claim_validation",
                "polarity": "supportive",
                "retrieval_query": base_query,
                "can_independently_falsify_sh": True,
            }]
        plan: list[dict[str, Any]] = []
        for index, path in enumerate(profile_paths[:5]):
            role = str(path.get("role") or path.get("id") or "direct claim evidence")
            path_id = str(path.get("id") or role)
            role_metadata = evidence_role_retrieval_metadata(role, primary_epistemic_mode)
            evidence_kind = str(role_metadata.get("evidence_kind") or "association")
            target_lane = str(role_metadata.get("target_lane") or "OBSERVATIONAL_COHORT_EVIDENCE")
            label = role.replace("_", " ")
            is_core = bool(path.get("can_independently_falsify_sh") is True) or index == 0
            direct_query = path_causal_query(role, _normalize(base_query))
            query_marker = " ".join(_ranked_terms(str(path.get("retrieval_query") or role), limit=5))
            query = _normalize(
                f"({direct_query}) AND ({query_marker})"
                if direct_query and query_marker else direct_query or query_marker or base_query
            )
            failure = path_failure_metadata(role, fallback_can_falsify=is_core)
            plan.append({
                "branch": f"{sub_id}:{re.sub(r'[^a-z0-9]+', '_', role.lower()).strip('_') or index}",
                "query": query,
                "l2_query": direct_query or _normalize(base_query),
                "purpose": (
                    f"retrieve {label} evidence for the direct claim" if is_core
                    else f"retrieve a profile-compatible qualification of the direct claim"
                ),
                "query_family": re.sub(r"[^a-z0-9]+", "_", role.lower()).strip("_") or "profile_compatible",
                "evidence_kind": evidence_kind,
                "evidence_path_id": path_id,
                "evidence_path_role": role,
                "evidence_path_polarity": str(path.get("polarity") or ("supportive" if is_core else "boundary")),
                "evidence_time_bucket": evidence_role_time_bucket(role),
                "target_lane": target_lane,
                "preferred_retrieval_layers": ["L2_top_latest", "L4_regular"] if is_core else ["L0_review", "L4_regular"],
                "retrieval_layer_role": "core_validation" if is_core else "qualification",
                "core_evidence_capable": is_core,
                "path_composition_policy": str(contract.get("evidence_path_policy") or "profile_compatible_evidence_paths"),
                "scientific_object_anchor": str(contract.get("scientific_object") or ""),
                "scientific_object_anchor_group": object_anchor_group,
                "primary_field": str(contract.get("primary_field") or ""),
                "causal_edge_anchors": _unique(input_terms + mechanism_terms + outcome_terms)[:12],
                "excluded_nearby_objects": list(contract.get("excluded_nearby_objects") or []),
                **failure,
            })
        return _finalize_retrieval_object_query_plan(plan, contract)

    # Keep the concrete scientific object at the front of every provider
    # query.  Generic method words can supplement this identity but can never
    # replace it.  Each causal axis contributes its own bounded clause so a
    # broad field or method match cannot dominate all branches.
    causal_axis_terms = _unique(input_terms + mechanism_terms + outcome_terms)
    causal_query_parts = []
    if object_clause:
        causal_query_parts.append(f"({object_clause})")
    if input_terms:
        causal_query_parts.append(f"({' OR '.join(input_terms[:3])})")
    if mechanism_terms:
        causal_query_parts.append(f"({' OR '.join(mechanism_terms[:3])})")
    if outcome_terms:
        causal_query_parts.append(f"({' OR '.join(outcome_terms[:3])})")
    causal_query = _normalize(" AND ".join(causal_query_parts))
    if not causal_query:
        return []
    if comparative_object_parts:
        object_terms_for_query = _unique(comparative_object_parts + object_anchor_group[:8])[:8]
        comparative_axis_terms = _unique(
            outcome_phrases_for_query[:4] + outcome_terms[:5] + mechanism_terms[:3] + input_terms[:2]
        )[:8]
        if object_terms_for_query and comparative_axis_terms:
            causal_query = _normalize(
                f"({' OR '.join(object_terms_for_query[:6])}) AND "
                f"({' OR '.join(comparative_axis_terms[:6])})"
            ) or causal_query
    def corpus_axis_query(axis_terms: list[str], fallback: str = "") -> str:
        clauses = [f"({object_clause})"] if object_clause else []
        bounded_axis_terms = _unique(
            [
                term
                for term in axis_terms
                if term and term.lower() not in _CORE_AXIS_GENERIC_TERMS
            ]
        )[:4]
        if bounded_axis_terms:
            clauses.append(f"({' OR '.join(bounded_axis_terms)})")
        return _normalize(" AND ".join(clauses)) or _normalize(fallback)

    def sh_local_axis_query(axis_terms: list[str], fallback: str = "") -> str:
        """Object + declared input + one support axis for non-background branches."""

        clauses = [f"({object_clause})"] if object_clause else []
        bounded_input_terms = _unique(
            [
                term
                for term in input_terms
                if term and term.lower() not in _CORE_AXIS_GENERIC_TERMS
            ]
        )[:3]
        if bounded_input_terms:
            clauses.append(f"({' OR '.join(bounded_input_terms)})")
        bounded_axis_terms = _unique(
            [
                term
                for term in axis_terms
                if term
                and term.lower() not in _CORE_AXIS_GENERIC_TERMS
                and term not in bounded_input_terms
            ]
        )[:3]
        if bounded_axis_terms:
            clauses.append(f"({' OR '.join(bounded_axis_terms)})")
        return _normalize(" AND ".join(clauses)) or _normalize(fallback)

    def structured_modules_for_branch(
        *,
        include_input: bool,
        method_values: list[str] | None = None,
        readout_values: list[str] | None = None,
        boundary_values: list[str] | None = None,
        model_values: list[str] | None = None,
    ) -> dict[str, Any]:
        return {
            "object": object_clause_terms[:8],
            "causal_input": input_terms[:8] if include_input else [],
            "method_or_assessment": _unique(method_values or mechanism_terms)[:8],
            "readout_or_endpoint": _unique(readout_values or outcome_terms)[:8],
            "model_system": _unique(model_values or [])[:6],
            "boundary_or_cost_or_comparison": _unique(boundary_values or [])[:8],
            "exclusion": query_forbidden_terms[:48],
        }

    # Only the core pool carries the full input--mechanism--outcome contract.
    # Corpus branches deliberately pair the scientific object with one axis so
    # realistic mechanism, method, review, safety, model, and boundary papers
    # can be recalled without restating the entire SH in title/abstract.
    theory_query = corpus_axis_query([], base_query)
    discovery_query = corpus_axis_query(
        mechanism_terms or input_terms or outcome_terms,
        base_query,
    )
    core_validation_role = (
        "causal_validation"
        if evidence_path("causal_validation")
        else "core_validation"
        if evidence_path("core_validation")
        else "whole_causal_chain"
    )
    validation_query = path_causal_query(core_validation_role, causal_query)
    discovery_query = sh_local_axis_query(
        mechanism_terms or outcome_terms,
        discovery_query,
    )
    adverse_query = sh_local_axis_query(
        outcome_terms or mechanism_terms,
        base_query,
    )
    boundary_query = sh_local_axis_query(
        outcome_terms or mechanism_terms,
        base_query,
    )
    validation_context_terms = experimental_context_terms()
    theory_markers = "review OR systematic review OR field map OR terminology OR theoretical framework OR formal model"
    discovery_markers = (
        "observational OR cohort OR case-control OR cross-sectional OR longitudinal OR natural experiment "
        "OR multiomics OR multi-omics OR profiling OR mediation OR assay OR functional readout"
    )
    validation_markers = (
        "intervention OR perturbation OR controlled study OR randomized trial OR assay "
        "OR model system OR in vivo OR in vitro OR animal model OR cell culture OR causal identification "
        "OR control group OR compared with OR measurable endpoint"
    )
    adverse_markers = (
        "negative effect OR adverse effect OR rebound effect OR substitution effect OR burden shifting "
        "OR trade-off OR tradeoff OR resource competition OR failure mode OR implementation failure "
        "OR null effect OR no significant effect OR reduced effectiveness"
    )
    boundary_markers = (
        "boundary condition OR heterogeneity OR subgroup OR implementation context OR regional variation "
        "OR external validation OR sensitivity analysis OR moderator OR threshold OR transportability"
    )
    if validation_context_terms:
        validation_markers = (
            f"{validation_markers} OR {' OR '.join(validation_context_terms)}"
        )
    sub_id = str(contract.get("sub_hypothesis_id") or "subhypothesis")
    return _finalize_retrieval_object_query_plan([
        {
            "branch": f"{sub_id}:theoretical_framework",
            "query": _normalize(f"({theory_query}) AND ({theory_markers})"),
            "l2_query": theory_query,
            "query_modules": structured_modules_for_branch(include_input=False),
            "l2_query_modules": structured_modules_for_branch(include_input=False),
            "purpose": "identify a theory, definition, feasibility framework, or explicit formal/causal/systems model for this exact sub-hypothesis; reviews remain background-only",
            "query_family": "theoretical_framework",
            "evidence_kind": "theoretical_framework",
            "evidence_path_id": "context_review",
            "evidence_path_role": "background_or_framework",
            "evidence_path_polarity": "context",
            "target_lane": "THEORETICAL_FRAMEWORK",
            "preferred_retrieval_layers": ["L0_review"],
            "retrieval_layer_role": "context_review",
            "core_evidence_capable": False,
            "component_evidence_counts_as_core": False,
            "component_evidence_counts_as_panel_core": False,
            "path_composition_policy": str(contract.get("evidence_path_policy") or "single_causal_path"),
            "scientific_object_anchor": str(contract.get("scientific_object") or ""),
            "scientific_object_anchor_group": object_anchor_group,
            "required_object_group": object_clause_terms[:12],
            "required_causal_input_group": input_terms[:12],
            "query_requires_declared_input": False,
            "primary_field": str(contract.get("primary_field") or ""),
            "causal_edge_anchors": causal_axis_terms[:12],
            "excluded_nearby_objects": list(contract.get("excluded_nearby_objects") or []),
            **path_failure_metadata("background_or_framework", fallback_can_falsify=False),
        },
        {
            "branch": f"{sub_id}:mechanism_discovery",
            "query": _normalize(f"({discovery_query}) AND ({discovery_markers})"),
            "l2_query": discovery_query,
            "query_modules": structured_modules_for_branch(include_input=bool(input_terms), method_values=mechanism_terms),
            "l2_query_modules": structured_modules_for_branch(include_input=bool(input_terms), method_values=mechanism_terms),
            "purpose": "identify direct observational, multi-modal, profiling, or natural-design evidence that discovers a candidate mechanism for the same input--mechanism--outcome chain",
            "query_family": "mechanism_discovery",
            "evidence_kind": "mechanism_discovery",
            "evidence_path_id": evidence_path_id("mechanism_discovery", "mechanism_discovery"),
            "evidence_path_role": "mechanism_discovery" if evidence_path("mechanism_discovery") else "whole_causal_chain",
            "evidence_path_polarity": "supportive",
            "target_lane": "MECHANISM_DISCOVERY",
            "preferred_retrieval_layers": ["L4_regular"],
            "retrieval_layer_role": "supporting_mechanism",
            "core_evidence_capable": False,
            "path_composition_policy": str(contract.get("evidence_path_policy") or "single_causal_path"),
            "scientific_object_anchor": str(contract.get("scientific_object") or ""),
            "scientific_object_anchor_group": object_anchor_group,
            "required_object_group": object_clause_terms[:12],
            "required_causal_input_group": input_terms[:12],
            "query_requires_declared_input": bool(input_terms),
            "primary_field": str(contract.get("primary_field") or ""),
            "causal_edge_anchors": causal_axis_terms[:12],
            "excluded_nearby_objects": list(contract.get("excluded_nearby_objects") or []),
            **path_failure_metadata("mechanism_discovery", fallback_can_falsify=False),
        },
        {
            "branch": f"{sub_id}:causal_validation",
            "query": _normalize(f"({validation_query}) AND ({validation_markers})"),
            "l2_query": causal_query,
            "query_modules": structured_modules_for_branch(include_input=bool(input_terms), method_values=mechanism_terms, readout_values=outcome_terms),
            "l2_query_modules": structured_modules_for_branch(include_input=bool(input_terms), method_values=mechanism_terms, readout_values=outcome_terms),
            "purpose": "identify intervention, controlled model, or strong causal-identification evidence for the validation responsibility of the same input--mechanism--outcome chain",
            "query_family": "causal_validation",
            "evidence_kind": "causal_validation",
            "evidence_path_id": evidence_path_id(core_validation_role, "core_effect_path"),
            "evidence_path_role": core_validation_role,
            "evidence_path_polarity": "supportive",
            "target_lane": "CAUSAL_VALIDATION",
            "preferred_retrieval_layers": ["L2_top_latest", "L4_regular"],
            "retrieval_layer_role": "core_validation",
            "core_evidence_capable": True,
            "path_composition_policy": str(contract.get("evidence_path_policy") or "single_causal_path"),
            "experimental_context_terms": validation_context_terms,
            "scientific_object_anchor": str(contract.get("scientific_object") or ""),
            "scientific_object_anchor_group": object_anchor_group,
            "required_object_group": object_clause_terms[:12],
            "required_causal_input_group": input_terms[:12],
            "query_requires_declared_input": bool(input_terms),
            "primary_field": str(contract.get("primary_field") or ""),
            "causal_edge_anchors": causal_axis_terms[:12],
            "excluded_nearby_objects": list(contract.get("excluded_nearby_objects") or []),
            **path_failure_metadata(core_validation_role, fallback_can_falsify=True),
        },
        {
            "branch": f"{sub_id}:adverse_or_reversal",
            "query": _normalize(f"({adverse_query}) AND ({adverse_markers})"),
            "l2_query": adverse_query,
            "query_modules": structured_modules_for_branch(include_input=bool(input_terms), readout_values=outcome_terms, boundary_values=outcome_terms[:3]),
            "l2_query_modules": structured_modules_for_branch(include_input=bool(input_terms), readout_values=outcome_terms, boundary_values=outcome_terms[:3]),
            "purpose": "identify negative, reversal, rebound, substitution, burden-shifting, resource-competition, or implementation-failure evidence for the same sub-hypothesis",
            "query_family": "adverse_or_reversal",
            "evidence_kind": "causal_validation",
            "evidence_path_id": evidence_path_id("adverse_or_reversal", "adverse_or_reversal_path"),
            "evidence_path_role": "adverse_or_reversal",
            "evidence_path_polarity": "opposing",
            "target_lane": "ADVERSE_OR_REVERSAL_EVIDENCE",
            "preferred_retrieval_layers": ["L2_top_latest", "L4_regular"],
            "retrieval_layer_role": "adverse_or_reversal",
            "core_evidence_capable": True,
            "path_composition_policy": str(contract.get("evidence_path_policy") or "core_adverse_boundary_paths"),
            "scientific_object_anchor": str(contract.get("scientific_object") or ""),
            "scientific_object_anchor_group": object_anchor_group,
            "required_object_group": object_clause_terms[:12],
            "required_causal_input_group": input_terms[:12],
            "query_requires_declared_input": bool(input_terms),
            "primary_field": str(contract.get("primary_field") or ""),
            "causal_edge_anchors": causal_axis_terms[:12],
            "excluded_nearby_objects": list(contract.get("excluded_nearby_objects") or []),
            **path_failure_metadata("adverse_or_reversal", fallback_can_falsify=True),
        },
        {
            "branch": f"{sub_id}:boundary_or_generalization",
            "query": _normalize(f"({boundary_query}) AND ({boundary_markers})"),
            "l2_query": boundary_query,
            "query_modules": structured_modules_for_branch(include_input=bool(input_terms), readout_values=outcome_terms, boundary_values=outcome_terms[:3]),
            "l2_query_modules": structured_modules_for_branch(include_input=bool(input_terms), readout_values=outcome_terms, boundary_values=outcome_terms[:3]),
            "purpose": "identify boundary, moderator, heterogeneity, external-validity, and transportability evidence for the same sub-hypothesis",
            "query_family": "boundary_or_generalization",
            "evidence_kind": "predictive_validation",
            "evidence_path_id": evidence_path_id("boundary_or_generalization", "boundary_or_generalization_path"),
            "evidence_path_role": "boundary_or_generalization",
            "evidence_path_polarity": "boundary",
            "target_lane": "BOUNDARY_OR_NEGATIVE_EVIDENCE",
            "preferred_retrieval_layers": ["L2_top_latest", "L4_regular"],
            "retrieval_layer_role": "boundary_or_generalization",
            "core_evidence_capable": False,
            "path_composition_policy": str(contract.get("evidence_path_policy") or "core_adverse_boundary_paths"),
            "scientific_object_anchor": str(contract.get("scientific_object") or ""),
            "scientific_object_anchor_group": object_anchor_group,
            "required_object_group": object_clause_terms[:12],
            "required_causal_input_group": input_terms[:12],
            "query_requires_declared_input": bool(input_terms),
            "primary_field": str(contract.get("primary_field") or ""),
            "causal_edge_anchors": causal_axis_terms[:12],
            "excluded_nearby_objects": list(contract.get("excluded_nearby_objects") or []),
            **path_failure_metadata("boundary_or_generalization", fallback_can_falsify=False),
        },
    ], contract)


def build_foundational_mechanism_contract(contract: dict[str, Any]) -> dict[str, Any]:
    """Build a domain-neutral contract for one historical mechanism bridge.

    This intentionally omits project-domain terms.  A foundation paper may be
    from the source discipline of a mechanism rather than the final application
    domain, but it must still explicitly cover the same manipulable input,
    mediator, and structural/functional outcome.
    """
    if str(contract.get("evidence_mode") or "") == PREDICTIVE_GENERALIZATION_EVIDENCE_MODE:
        foundation = {
            "version": "foundational_mechanism_bridge_v1",
            "project_id": str(contract.get("project_id") or ""),
            "project_version": int(contract.get("project_version") or 0),
            "alignment_contract_hash": str(contract.get("contract_hash") or ""),
            "sub_hypothesis_id": str(contract.get("sub_hypothesis_id") or ""),
            "input_anchors": [],
            "mediator_anchors": [],
            "outcome_anchors": [],
            "role": "NOT_APPLICABLE_PREDICTIVE_GENERALIZATION",
            "direct_target_evidence": False,
            "eligible_for_primary_gap_evidence": False,
            "eligible_for_mechanism_rationale": False,
            "eligible_for_competing_mechanism": False,
            "valid": False,
            "reason": "Predictive generalization uses external and subgroup validation evidence; it does not require a foundational mechanism bridge.",
        }
        foundation["foundation_contract_hash"] = _stable_hash(foundation)
        return foundation
    core_axis_policy = (
        contract.get("core_axis_policy")
        if isinstance(contract.get("core_axis_policy"), dict)
        else {}
    )
    input_anchors = _unique([
        str(item)
        for item in (
            list(core_axis_policy.get("focal_variable_phrases") or [])
            + list(core_axis_policy.get("focal_variable_terms") or [])
        )
        if str(item).strip()
    ])[:6]
    mediator_anchors = _unique([
        str(item)
        for item in (
            list(core_axis_policy.get("mechanism_phrases") or [])
            + list(core_axis_policy.get("mechanism_terms") or [])
        )
        if str(item).strip()
    ])[:7]
    outcome_anchors = _unique([
        str(item)
        for item in (
            list(core_axis_policy.get("outcome_phrases") or [])
            + list(core_axis_policy.get("outcome_terms") or [])
        )
        if str(item).strip()
    ])[:7]
    foundation = {
        "version": "foundational_mechanism_bridge_v1",
        "project_id": str(contract.get("project_id") or ""),
        "project_version": int(contract.get("project_version") or 0),
        "alignment_contract_hash": str(contract.get("contract_hash") or ""),
        "sub_hypothesis_id": str(contract.get("sub_hypothesis_id") or ""),
        "input_anchors": input_anchors,
        "mediator_anchors": mediator_anchors,
        "outcome_anchors": outcome_anchors,
        "role": "FOUNDATIONAL_MECHANISM_BRIDGE",
        "direct_target_evidence": False,
        "eligible_for_primary_gap_evidence": False,
        "eligible_for_mechanism_rationale": True,
        "eligible_for_competing_mechanism": True,
        "valid": bool(input_anchors and mediator_anchors and outcome_anchors),
    }
    foundation["foundation_contract_hash"] = _stable_hash(foundation)
    return foundation


def build_foundational_mechanism_query(
    foundation_contract: dict[str, Any],
    *,
    max_terms: int = 12,
) -> str:
    """Derive one stable causal-anchor query without recency/domain modifiers."""
    axis_groups = [
        _unique([str(item) for item in foundation_contract.get("input_anchors", []) if str(item).strip()]),
        _unique([str(item) for item in foundation_contract.get("mediator_anchors", []) if str(item).strip()]),
        _unique([str(item) for item in foundation_contract.get("outcome_anchors", []) if str(item).strip()]),
    ]
    # The L1 query is bounded for provider stability, but its bound must never
    # silently trim away a causal axis.  Reserve one source-bound anchor from
    # input, mediator, and outcome before filling the remaining term budget.
    anchors = _unique(
        [group[0] for group in axis_groups if group]
        + [item for group in axis_groups for item in group]
    )
    return _normalize(" ".join(anchors[: max(3, min(int(max_terms), 16))]))


def assess_foundational_mechanism_bridge(
    candidate: dict[str, Any],
    foundation_contract: dict[str, Any],
) -> dict[str, Any]:
    """Qualify a historical mechanism bridge without treating it as core proof.

    Qualification is strict on the causal chain and explicitly excludes reviews.
    Ranking has no recency component: it uses causal-chain coverage, field-
    normalized citation impact, metadata quality, and mechanism evidence only.
    """
    input_anchors = [str(item) for item in foundation_contract.get("input_anchors", []) if str(item).strip()]
    mediator_anchors = [str(item) for item in foundation_contract.get("mediator_anchors", []) if str(item).strip()]
    outcome_anchors = [str(item) for item in foundation_contract.get("outcome_anchors", []) if str(item).strip()]
    # The foundation contract intentionally carries only the three causal
    # anchor groups, whereas the common paper-genre classifier consumes the
    # alignment contract's ``core_axis_policy`` representation.  Adapt the
    # former to the latter at this boundary so that the L1 maturity audit
    # measures the *same* input--mediator--outcome continuity used by the
    # bridge gate.  Passing the raw foundation contract made every candidate
    # look unanchored (and therefore fail the maturity check) despite exact
    # matches to its L1 anchors.
    foundation_semantic_contract = {
        "core_axis_policy": {
            "focal_variable_phrases": input_anchors,
            "focal_variable_terms": input_anchors,
            "mechanism_phrases": mediator_anchors,
            "mechanism_terms": mediator_anchors,
            "outcome_phrases": outcome_anchors,
            "outcome_terms": outcome_anchors,
        },
    }
    text = _candidate_text(candidate)
    genre = classify_paper_evidence_genre(
        candidate,
        semantic_contract=foundation_semantic_contract,
    )
    input_hits = _hits(text, input_anchors)
    mediator_hits = _hits(text, mediator_anchors)
    outcome_hits = _hits(text, outcome_anchors)
    observation_hits = _hits(text, list(_FOUNDATION_OBSERVATION_MARKERS))
    exclusion_hits = _explicit_exclusion_hits(candidate, foundation_contract)
    is_review = bool(genre.get("is_review")) or _candidate_is_review(candidate)
    quality_raw = candidate.get("publication_quality_score")
    quality = _float_or_default(quality_raw, 0.0)
    quality_available = quality_raw not in (None, "")
    low_quality = bool(quality_available and quality < 0.45)

    semantic_axes = genre.get("semantic_axes") if isinstance(genre.get("semantic_axes"), dict) else {}
    # Contract-anchor hits prove the strongest continuity; semantic axes make
    # equivalent wording (e.g. temperature / isothermal TGA / rate) visible.
    # L1 is rationale-only, so a quantitative field demonstration may qualify
    # with partial (not necessarily word-for-word complete) branch overlap.
    input_pass = bool(input_hits) or bool((semantic_axes.get("input") or {}).get("hits"))
    mediator_pass = bool(mediator_hits) or bool((semantic_axes.get("mediator") or {}).get("hits"))
    outcome_pass = bool(outcome_hits) or bool((semantic_axes.get("outcome") or {}).get("hits"))
    method_pass = bool((semantic_axes.get("method") or {}).get("hits"))
    observation_pass = bool(observation_hits) or method_pass
    mechanism_match = (
        0.34 * _coverage(input_hits, input_anchors)
        + 0.40 * _coverage(mediator_hits, mediator_anchors)
        + 0.26 * _coverage(outcome_hits, outcome_anchors)
    )
    citation_impact = _field_normalized_citation_impact(candidate)
    metadata_quality = quality if quality_available else 0.5
    maturity = genre.get("evidence_maturity") if isinstance(genre.get("evidence_maturity"), dict) else {}
    verification_scale = genre.get("verification_scale") if isinstance(genre.get("verification_scale"), dict) else {}
    direct_experimental = bool(genre.get("direct_experimental_evidence"))
    maturity_score = int(maturity.get("total_score") or 0)
    maturity_threshold = int(maturity.get("automatic_l1_acceptance_threshold") or L1_MATURITY_ACCEPTANCE_THRESHOLD)
    direct_relevance_score = int(maturity.get("direct_relevance_score") or 0)
    maturity_threshold_passes = bool(
        maturity.get(
            "threshold_passes",
            maturity_score >= maturity_threshold and direct_relevance_score >= 1,
        )
    )
    # A demonstration may report monitoring/quantification rather than the
    # word "experiment".  Treat that recorded observation signal as evidence
    # strength, particularly for field and operational scales.
    observation_signal_count = max(
        len(observation_hits),
        len(list((semantic_axes.get("method") or {}).get("hits") or [])),
        1 if int(maturity.get("quantification_score") or 0) >= 3 else 0,
    )
    observation_strength = min(1.0, observation_signal_count / 2.0)
    foundation_score = round(
        0.45 * mechanism_match
        + 0.30 * citation_impact
        + 0.15 * metadata_quality
        + 0.10 * observation_strength,
        4,
    )
    semantic_observation_complete = bool(input_pass and method_pass and outcome_pass)
    bridge_eligible = bool(
        foundation_contract.get("valid")
        and semantic_observation_complete
        and not is_review
        and not exclusion_hits
        and not low_quality
        and direct_experimental
        and maturity_threshold_passes
        and direct_relevance_score >= 1
    )
    # ``missing`` contains only blocking requirements.  A field case may
    # provide strong, quantitative operational evidence without observing the
    # molecular mediator directly; retain it as L1 rationale and surface that
    # limitation separately instead of contradicting an ACCEPT decision.
    missing: list[str] = []
    mechanism_limitations: list[str] = []
    if not foundation_contract.get("valid"):
        missing.append("incomplete_foundation_contract")
    if not input_pass:
        missing.append("input_anchor")
    if not mediator_pass:
        mechanism_limitations.append("mediator_not_explicitly_observed")
    if not outcome_pass:
        missing.append("structural_or_functional_outcome")
    if not method_pass:
        missing.append("method_or_observation_signal")
    if is_review:
        missing.append("review_not_primary_foundation")
    if exclusion_hits:
        missing.append("explicit_project_exclusion")
    if low_quality:
        missing.append("low_metadata_quality")
    if not direct_experimental:
        missing.append("direct_quantitative_experiment_or_observation")
    if not maturity_threshold_passes:
        missing.append(f"evidence_maturity_below_threshold_{maturity_threshold}")
    if direct_relevance_score < 1:
        missing.append("no_subhypothesis_mechanism_relevance")
    if is_review:
        decision = "REJECT"
    elif bridge_eligible:
        decision = "ACCEPT"
    elif direct_experimental and maturity_threshold_passes and direct_relevance_score >= 1:
        # This branch makes a remaining exclusion explicit instead of silently
        # treating a high-scoring demonstration as a generic rejection.
        decision = "NEEDS_HUMAN_REVIEW"
    else:
        decision = "REJECT"
    transparent_report = {
        "decision": decision,
        "paper": str(candidate.get("title") or candidate.get("citation") or "untitled"),
        "genre": genre.get("genre"),
        "verification_scale": verification_scale,
        "reason_codes": missing,
        "mechanism_limitations": mechanism_limitations,
        "semantic_equivalents": {
            axis: {
                "detected": list((semantic_axes.get(axis) or {}).get("hits") or []),
                "source_spans": list((semantic_axes.get(axis) or {}).get("source_spans") or []),
            }
            for axis in ("input", "method", "outcome")
        },
        "evidence_maturity": maturity,
        "human_review_recommendation": (
            "The paper meets the quantitative evidence threshold but has an explicit non-maturity exclusion; review the recorded reason before using it as an L1 mechanism bridge."
            if decision == "NEEDS_HUMAN_REVIEW"
            else (
                "Accepted as demonstration-/operation-level L1 rationale only; it cannot supply direct target evidence or a primary-gap evidence slot."
                if decision == "ACCEPT" and verification_scale.get("evidence_level") in {"demonstration_level_evidence", "commercial_operational_evidence", "quantitative_observational_evidence"}
                else "No manual override is suggested: this record cannot occupy the L1 primary-foundation slot."
            )
        ),
    }
    return {
        "version": "foundational_mechanism_bridge_v1",
        "project_id": str(foundation_contract.get("project_id") or ""),
        "project_version": int(foundation_contract.get("project_version") or 0),
        "sub_hypothesis_id": str(foundation_contract.get("sub_hypothesis_id") or ""),
        "alignment_contract_hash": str(foundation_contract.get("alignment_contract_hash") or ""),
        "foundation_contract_hash": str(foundation_contract.get("foundation_contract_hash") or ""),
        "research_role": "FOUNDATIONAL_MECHANISM_BRIDGE",
        "bridge_eligible": bridge_eligible,
        "core_eligible": False,
        "direct_target_evidence": False,
        "eligible_for_primary_gap_evidence": False,
        "eligible_for_mechanism_rationale": bridge_eligible,
        "eligible_for_competing_mechanism": bridge_eligible,
        "verdict": "FOUNDATIONAL_MECHANISM_BRIDGE" if bridge_eligible else "REJECTED_FOUNDATION_BRIDGE",
        "reason": (
            f"Non-review {verification_scale.get('evidence_level') or 'empirical'} record meets the explicit L1 maturity threshold ({maturity_score}/{maturity_threshold}) and is retained as rationale only."
            if bridge_eligible
            else "Foundation bridge requirements missing: " + ", ".join(missing)
        ),
        "missing_requirements": missing,
        "mechanism_limitations": mechanism_limitations,
        "input": _axis(input_hits, input_pass),
        "mediator": _axis(mediator_hits, mediator_pass),
        "outcome": _axis(outcome_hits, outcome_pass),
        "method_or_observation": _axis(observation_hits + list((semantic_axes.get("method") or {}).get("hits") or []), method_pass),
        "is_review": is_review,
        "paper_genre": genre,
        "verification_scale": verification_scale,
        "l1_review_report": transparent_report,
        "exclusion_hits": exclusion_hits,
        "ranking": {
            "foundation_score": foundation_score,
            "mechanism_chain_match": round(mechanism_match, 4),
            "field_normalized_citation_impact": citation_impact,
            "metadata_quality": round(metadata_quality, 4),
            "mechanism_evidence_strength": round(observation_strength, 4),
            "recency_used": False,
            "weights": {
                "input_mediator_outcome_match": 0.45,
                "field_normalized_citation_impact": 0.30,
                "publication_metadata_quality": 0.15,
                "mechanism_evidence_strength": 0.10,
            },
        },
        "transfer_assumptions": [
            "The matched input--mediator--outcome relationship transfers from the source system to the target system only after direct target-domain testing.",
            "This record may motivate a mediator or a competing mechanism, but cannot supply direct target evidence or satisfy the primary-gap evidence contract.",
        ],
    }


def evidence_kind_from_branch(branch: str) -> str:
    normalized = str(branch or "").lower()
    if "adverse_or_reversal" in normalized or "adverse" in normalized or "reversal" in normalized:
        return "causal_validation"
    if "predictive_external_validation" in normalized or "predictive_boundary_validation" in normalized:
        return "predictive_validation"
    if "mechanism_discovery" in normalized:
        return "mechanism_discovery"
    if "causal_validation" in normalized:
        return "causal_validation"
    if "theoretical_framework" in normalized:
        return "theoretical_framework"
    if "experimental_evidence" in normalized:
        return "experimental_evidence"
    return ""


def matched_evidence_kinds_for_candidate(candidate: dict[str, Any]) -> list[str]:
    """Return every direct-evidence lane that retrieved a candidate.

    ``query_branch`` is retained as a backward-compatible primary assignment,
    while ``matched_query_branches`` captures all branch matches after
    identity fusion.  Do not turn those matches into evidence automatically:
    each lane is assessed separately below.
    """

    raw_kinds = candidate.get("matched_evidence_kinds")
    values = raw_kinds if isinstance(raw_kinds, (list, tuple, set)) else [raw_kinds]
    branches = candidate.get("matched_query_branches")
    branch_values = branches if isinstance(branches, (list, tuple, set)) else [branches]
    branch_values = [
        *branch_values,
        candidate.get("primary_query_branch"),
        candidate.get("query_branch"),
    ]
    kinds: list[str] = []
    for value in (*values, candidate.get("evidence_kind")):
        kind = str(value or "").strip().lower()
        if kind in DIRECT_EVIDENCE_KINDS and kind not in kinds:
            kinds.append(kind)
    for branch in branch_values:
        kind = evidence_kind_from_branch(str(branch or ""))
        if kind and kind not in kinds:
            kinds.append(kind)
    return kinds


def assess_candidate_alignment_across_matched_evidence_lanes(
    candidate: dict[str, Any],
    contract: dict[str, Any],
    *,
    requested_evidence_kinds: list[str] | tuple[str, ...] | None = None,
    enable_focal_variable_synonym_dictionary: bool = False,
) -> dict[str, Any]:
    """Evaluate every matched direct-evidence lane without double counting.

    The returned ``alignment_assessment`` is for one deterministically
    assigned import role.  ``lane_assessments`` retains the independent
    theory/experiment verdicts so one fused paper remains visible to both
    retrieval lanes, but a single import still fills at most one evidence
    slot.
    """

    forced_kinds: list[str] = []
    for value in requested_evidence_kinds or ():
        kind = str(value or "").strip().lower()
        if kind in DIRECT_EVIDENCE_KINDS and kind not in forced_kinds:
            forced_kinds.append(kind)
    matched_kinds = matched_evidence_kinds_for_candidate(candidate)
    kinds = list(forced_kinds)
    for kind in matched_kinds:
        if kind not in kinds:
            kinds.append(kind)
    if not kinds:
        kinds = [""]

    lane_assessments: dict[str, dict[str, Any]] = {}
    for kind in kinds:
        key = kind or "unspecified"
        lane_assessments[key] = assess_candidate_alignment(
            candidate,
            contract,
            requested_evidence_kind=kind,
            enable_focal_variable_synonym_dictionary=enable_focal_variable_synonym_dictionary,
        )

    preferred_kind = ""
    if forced_kinds:
        preferred_kind = forced_kinds[0]
    else:
        preferred_kind = evidence_kind_from_branch(
            str(candidate.get("primary_query_branch") or candidate.get("query_branch") or "")
        )
    # A primary branch is provenance, not an entitlement to an evidence role.
    # If it fails its own genre/alignment gate, an independently qualified
    # matched lane may carry this one import instead.  A caller that explicitly
    # selected one import role remains strict and must not silently switch it.
    # L2 retrieval may explicitly provide several acceptable direct lanes
    # (e.g. mechanism_discovery and causal_validation) because provider
    # supplements are often branch-bound only after local stratification; in
    # that case choose the first forced lane that is actually import-eligible.
    if len(forced_kinds) > 1 and not lane_assessments.get(preferred_kind, {}).get("import_eligible"):
        forced_eligible_kind = next(
            (
                kind
                for kind in forced_kinds
                if lane_assessments.get(kind, {}).get("import_eligible")
            ),
            "",
        )
        if forced_eligible_kind:
            preferred_kind = forced_eligible_kind
    if (
        preferred_kind not in lane_assessments
        or (
            not forced_kinds
            and not lane_assessments[preferred_kind].get("import_eligible")
        )
    ):
        eligible_kind = next(
            (
                kind
                for kind, assessment in lane_assessments.items()
                if assessment.get("import_eligible")
            ),
            "",
        )
        preferred_kind = eligible_kind or next(iter(lane_assessments))

    selected = dict(lane_assessments[preferred_kind])
    selected["assigned_evidence_kind"] = (
        preferred_kind if preferred_kind != "unspecified" else ""
    )
    selected["matched_evidence_kinds"] = list(matched_kinds)
    selected["matched_query_branches"] = [
        str(value)
        for value in (candidate.get("matched_query_branches") or [])
        if str(value).strip()
    ]
    selected["lane_assessments"] = lane_assessments
    selected["multi_lane_candidate"] = len(lane_assessments) > 1
    selected["independent_evidence_slots_consumed"] = 1
    return selected


def standard_evidence_design_assessment(
    candidate: dict[str, Any],
    evidence_standard: dict[str, Any] | None = None,
    *,
    research_design: str = "",
    causal_role: str = "",
    paper_genre: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Map a candidate into an evidence-standard-specific lane.

    ``research_design`` remains the generic axis; this function adds the
    standard-aware lane used by v6 retrieval gates, e.g. policy causal
    identification, ecological monitoring, MIC assay, animal model, or
    surveillance validation.
    """

    standard = evidence_standard if isinstance(evidence_standard, dict) else {}
    accepted = {str(item) for item in (standard.get("accepted_core_designs") or []) if str(item)}
    local_edge_accepted = {
        str(item) for item in (standard.get("local_edge_accepted_core_designs") or [])
        if str(item)
    }
    support = {str(item) for item in (standard.get("support_designs") or []) if str(item)}
    genre = paper_genre if isinstance(paper_genre, dict) else {}
    text = _candidate_text(candidate).lower()
    generic_design = str(research_design or "").strip()
    generic_role = str(causal_role or "").strip()
    if not generic_design or generic_design == "unclassified":
        generic_design = str(
            genre.get("research_design")
            or genre.get("genre")
            or candidate.get("research_design")
            or candidate.get("study_design")
            or ""
        ).strip()
    candidates: list[str] = []

    marker_designs: tuple[tuple[str, tuple[str, ...]], ...] = (
        ("direct_observation", ("direct observation", "observed", "measurement")),
        ("survey_or_catalog_analysis", ("survey analysis", "catalog analysis", "catalogue analysis")),
        ("mission_or_data_release", ("data release", "mission data", "legacy archive")),
        ("time_domain_observation", ("time-domain", "time domain observation", "time series observation")),
        ("multi_messenger_observation", ("multi-messenger", "multimessenger")),
        ("parameter_likelihood_or_posterior_analysis", ("likelihood", "posterior", "credible interval", "confidence interval")),
        ("cross_dataset_constraint", ("joint constraint", "combined constraint", "cross dataset", "cross-dataset")),
        ("statistical_model_comparison", ("model comparison", "bayes factor", "information criterion", "goodness of fit")),
        ("analytical_derivation", ("analytical derivation", "derive", "derivation")),
        ("field_equation_solution", ("field equation", "equation solution", "solution of the equations")),
        ("consistency_analysis", ("consistency analysis", "self-consistency", "unitarity")),
        ("stability_analysis", ("stability analysis", "stable solution", "instability")),
        ("symmetry_argument", ("symmetry argument", "conservation law", "invariance")),
        ("limiting_case", ("limiting case", "asymptotic limit")),
        ("no_go_result", ("no-go", "no go theorem", "impossibility result")),
        ("numerical_solution", ("numerical solution", "numerical integration")),
        ("observable_prediction", ("observable prediction", "testable prediction")),
        ("proof", ("proof", "proved", "proven")),
        ("lemma", ("lemma",)),
        ("theorem", ("theorem",)),
        ("counterexample", ("counterexample",)),
        ("equivalence_result", ("equivalence", "equivalent formulation")),
        ("independence_result", ("independence result", "undecidable", "independence")),
        ("formally_verified_proof", ("formally verified", "machine-checked proof", "proof assistant")),
        ("validated_simulation", ("validated simulation", "simulation validation")),
        ("convergence_analysis", ("convergence analysis", "grid convergence")),
        ("benchmark_comparison", ("benchmark comparison", "benchmark validation")),
        ("parameter_sensitivity", ("parameter sensitivity", "sensitivity analysis")),
        ("uncertainty_propagation", ("uncertainty propagation",)),
        ("interrupted_time_series", ("interrupted time series", "segmented regression")),
        ("difference_in_differences", ("difference-in-differences", "difference in differences", "did analysis")),
        ("regression_discontinuity", ("regression discontinuity",)),
        ("instrumental_variable", ("instrumental variable",)),
        ("natural_experiment", ("natural experiment", "policy shock", "exogenous shock")),
        ("quasi_experiment", ("quasi-experiment", "quasi experiment", "before-after", "before after")),
        ("cross_jurisdiction_comparison", ("cross-jurisdiction", "cross jurisdiction", "cross-country", "cross country")),
        ("environmental_monitoring", ("environmental monitoring", "wastewater", "resistome monitoring", "water monitoring", "soil monitoring")),
        ("ecological_monitoring", ("ecological monitoring", "field monitoring", "watershed monitoring")),
        ("ecological_association", ("ecological association", "ecological study", "ecological epidemiology")),
        ("longitudinal_or_time_series_sampling", ("longitudinal sampling", "time series sampling", "spatiotemporal trend")),
        ("cross_site_comparison", ("cross-site", "cross site", "multi-site", "multisite")),
        ("mic_assay", ("minimum inhibitory concentration", " mic ", "mic assay", "broth microdilution")),
        ("in_vitro_antimicrobial_activity", ("in vitro antimicrobial", "antimicrobial activity", "zone of inhibition")),
        ("animal_infection_model", ("animal infection model", "mouse infection", "murine infection", "in vivo infection")),
        ("measurement_system_validation", ("measurement system validation", "method validation", "assay validation")),
        ("sensor_or_detector_validation", ("sensor validation", "detector validation")),
        ("genomic_or_signal_tracking", ("genomic surveillance", "genomic tracking", "sequence tracking", "variant tracking")),
        ("spatiotemporal_monitoring", ("spatiotemporal monitoring", "spatial-temporal", "spatio-temporal")),
        ("sensitivity_specificity_or_uncertainty_assessment", ("sensitivity", "specificity", "uncertainty assessment")),
        ("computational_model_or_simulation", ("simulation", "computational model", "numerical model", "in silico")),
        ("theoretical_framework_or_derivation", ("formal model", "analytical solution")),
        ("systematic_review_for_context", ("systematic review", "meta-analysis", "meta analysis")),
        ("interaction_or_synergy_test", ("synergy", "synergistic", "interaction test")),
        ("factorial_or_ablation_design", ("factorial", "ablation")),
        ("integrated_system_evaluation", ("integrated system", "system evaluation")),
        ("cross_scale_synthesis", ("cross-scale", "cross scale", "multi-scale", "multiscale")),
    )
    padded_text = f" {text} "
    for design, markers in marker_designs:
        if any(marker in padded_text for marker in markers):
            candidates.append(design)

    if generic_design == "interventional_human":
        candidates.extend(["randomized_comparison", "intervention", "randomized_or_controlled_trial", "controlled_intervention"])
    elif generic_design == "experimental_animal_or_cellular":
        candidates.extend(["animal_infection_model", "mechanistic_assay", "controlled_experiment", "intervention"])
    elif generic_design == "experimental_controlled_system":
        candidates.extend(["controlled_experiment", "intervention", "laboratory_measurement", "mechanistic_assay"])
    elif generic_design in {"controlled_experiment", "laboratory_measurement", "mechanistic_assay"}:
        candidates.extend([generic_design])
    elif generic_design == "longitudinal_or_natural_experiment":
        candidates.extend(["natural_experiment", "longitudinal_or_time_series_sampling", "quasi_experiment"])
    elif generic_design in {"observational_human", "observational_multiomics", "observational_human_multiomics"}:
        candidates.extend(["prospective_or_retrospective_cohort", "ecological_association", "population_surveillance"])
    elif generic_design == "theoretical_or_formal_model":
        candidates.extend(["analytical_derivation", "theoretical_framework_or_derivation", "computational_model_or_simulation"])
    elif generic_design == "evidence_synthesis":
        candidates.extend(["systematic_review_for_context"])

    if generic_role == "causal_identification":
        candidates.extend(["natural_experiment", "quasi_experiment"])
    elif generic_role == "causal_validation":
        candidates.extend(["controlled_experiment", "controlled_intervention"])
    elif generic_role == "mechanism_discovery":
        candidates.extend(["mechanistic_assay"])

    ordered = _unique([item for item in candidates if item])
    selected = next((item for item in ordered if item in accepted), "")
    if not selected:
        selected = next((item for item in ordered if item in local_edge_accepted), "")
    if not selected:
        selected = next((item for item in ordered if item in support), "")
    if not selected and ordered:
        selected = ordered[0]

    excluded_as_core = {str(item) for item in (standard.get("excluded_as_core") or []) if str(item)}
    publication_values = candidate.get("publication_types") or candidate.get("publicationTypes") or []
    if not isinstance(publication_values, (list, tuple, set)):
        publication_values = [publication_values]
    publication_type = " ".join(
        str(value or "")
        for value in (candidate.get("publication_type"), *publication_values)
    ).lower()
    is_commentary = any(marker in publication_type or marker in text for marker in ("commentary", "editorial", "letter"))
    is_narrative_review = bool(genre.get("is_review")) and selected != "systematic_review_for_context"
    excluded_reason = ""
    if is_commentary and "commentary" in excluded_as_core:
        excluded_reason = "commentary"
    elif is_narrative_review and "narrative_review" in excluded_as_core:
        excluded_reason = "narrative_review"

    return {
        "schema_version": "standard_evidence_design_assessment_v1",
        "evidence_standard_id": str(standard.get("id") or ""),
        "generic_research_design": generic_design or "unclassified",
        "generic_causal_role": generic_role or "unclassified",
        "standard_research_design": selected or "unclassified",
        "standard_evidence_lane": STANDARD_EVIDENCE_LANE_BY_DESIGN.get(selected, "UNCLASSIFIED_STANDARD_EVIDENCE"),
        "candidate_designs": ordered[:8],
        "core_design_match": bool(selected and selected in accepted and not excluded_reason),
        "local_edge_core_design_match": bool(
            selected and (selected in accepted or selected in local_edge_accepted)
            and not excluded_reason
        ),
        "support_design_match": bool(selected and selected in support and not excluded_reason),
        "excluded_as_core_reason": excluded_reason,
        "accepted_core_designs": sorted(accepted),
        "local_edge_accepted_core_designs": sorted(local_edge_accepted),
        "support_designs": sorted(support),
    }


def fulltext_epistemic_revalidation(
    candidate: dict[str, Any],
    *,
    epistemic_profile: dict[str, Any] | None = None,
    standard_design: str = "",
) -> dict[str, Any]:
    """Classify a full text with the checklist appropriate to its paradigm.

    This is deliberately a *classification* result, not a second attempt to
    force every paper through an experimental-intervention rubric.  The two
    dimensions are intentionally independent: a derivation can establish
    internal theoretical validity without assessing the real universe, while a
    survey analysis can empirically constrain a model without proving it.
    """

    profile = epistemic_profile if isinstance(epistemic_profile, dict) else {}
    primary_mode = str(profile.get("primary_mode") or "unresolved")
    text = _candidate_text(candidate).lower()
    design = str(standard_design or candidate.get("standard_research_design") or "").lower()
    theory_designs = {
        "analytical_derivation", "field_equation_solution", "consistency_analysis",
        "stability_analysis", "symmetry_argument", "limiting_case", "no_go_result",
        "numerical_solution", "observable_prediction",
    }
    formal_designs = {
        "proof", "theorem", "lemma", "counterexample", "equivalence_result",
        "independence_result", "formally_verified_proof", "formal_proof",
        "formal_verification",
    }
    observational_designs = {
        "direct_observation", "survey_or_catalog_analysis", "mission_or_data_release",
        "time_domain_observation", "multi_messenger_observation",
        "parameter_likelihood_or_posterior_analysis", "cross_dataset_constraint",
        "statistical_model_comparison", "natural_experiment",
    }
    simulation_designs = {
        "validated_simulation", "convergence_analysis", "benchmark_comparison",
        "parameter_sensitivity", "uncertainty_propagation",
    }
    theoretical_core = design in theory_designs
    formal_core = design in formal_designs
    observational_core = design in observational_designs
    simulation_core = design in simulation_designs
    # Metadata can be incomplete.  These markers only assign a provisional
    # evidence dimension; standard-core admission still owns the actual gate.
    theoretical_core = theoretical_core or any(marker in text for marker in (
        "analytical derivation", "consistency analysis", "stability analysis",
        "symmetry argument", "no-go theorem", "field equation",
    ))
    formal_core = formal_core or any(marker in text for marker in (
        " theorem", " proof", "counterexample", "formally verified",
        "machine-checked", "proof assistant",
    ))
    observational_core = observational_core or any(marker in text for marker in (
        "likelihood", "posterior", "confidence interval", "credible interval",
        "survey data", "catalog", "data release", "observational constraint",
    ))
    simulation_core = simulation_core or any(marker in text for marker in (
        "convergence analysis", "benchmark comparison", "validated simulation",
        "uncertainty propagation",
    ))
    computer_assisted_complete = bool(
        any(marker in text for marker in (
            "formally verified", "machine-checked proof", "proof assistant",
        ))
        and any(marker in text for marker in (
            "algorithm", "formal system", "verification", "kernel", "checker",
        ))
    )
    if "computer-assisted proof" in text and not computer_assisted_complete:
        formal_core = False

    theory_status = "CORE" if (theoretical_core or formal_core) else (
        "NOT_APPLICABLE" if primary_mode == "observational_inference" else "NOT_ASSESSED"
    )
    empirical_status = "CORE" if (observational_core or simulation_core) else (
        "NOT_APPLICABLE" if primary_mode == "mathematical_proof" else "NOT_ASSESSED"
    )
    if formal_core:
        checklist_id = "formal_mathematics_fulltext_v1"
        checklist = [
            "precise_statement", "explicit_assumptions", "proof_dependency",
            "counterexample_or_boundary", "formal_verification_chain_if_computer_assisted",
        ]
    elif theoretical_core or primary_mode == "theoretical_derivation":
        checklist_id = "theoretical_physics_fulltext_v1"
        checklist = [
            "explicit_assumptions", "derivation_or_computational_chain",
            "approximations_and_domain_of_validity", "stability_or_consistency",
            "observable_prediction_if_claim_is_empirical",
        ]
    elif observational_core or primary_mode == "observational_inference":
        checklist_id = "observational_inference_fulltext_v1"
        checklist = [
            "observable_or_parameter_relevance", "data_provenance_or_mission",
            "quantified_uncertainty_or_covariance", "systematic_error_treatment",
            "model_or_prior_dependence", "evidence_role_classification",
        ]
    else:
        checklist_id = "general_claim_compatible_fulltext_v1"
        checklist = ["claim_relevance", "research_design", "directness", "limitations"]
    return {
        "schema_version": "fulltext_epistemic_revalidation_v1",
        "detail_revalidation_is_normal_classification": True,
        "primary_mode": primary_mode,
        "checklist_id": checklist_id,
        "checklist": checklist,
        "theoretical_validity": theory_status,
        "empirical_support": empirical_status,
        "formal_proof_candidate": bool(formal_core),
        "computer_assisted_proof_verification_chain_clear": computer_assisted_complete,
        "classification": (
            "direct_claim_compatible_evidence"
            if any((theoretical_core, formal_core, observational_core, simulation_core))
            else "support_or_context_pending"
        ),
    }


def _candidate_panel_alignment_metadata(
    candidate: dict[str, Any],
    contract: dict[str, Any],
) -> dict[str, Any]:
    """Recover panel-path provenance for final alignment/core accounting."""

    panel_policy = (
        contract.get("multi_entity_panel_policy")
        if isinstance(contract.get("multi_entity_panel_policy"), dict)
        else {}
    )
    is_panel = bool(panel_policy.get("is_multi_entity_panel"))
    if not is_panel:
        return {}

    def normalized_values(*values: Any) -> list[str]:
        output: list[str] = []
        seen: set[str] = set()
        for value in values:
            nested = value if isinstance(value, (list, tuple, set)) else [value]
            for item in nested:
                normalized = _normalize(str(item or "")).lower()
                if normalized and normalized not in seen:
                    seen.add(normalized)
                    output.append(normalized)
        return output

    candidate_roles = normalized_values(
        candidate.get("evidence_path_role"),
        candidate.get("query_family"),
        candidate.get("query_branch"),
        candidate.get("primary_query_branch"),
        candidate.get("matched_evidence_path_roles"),
        candidate.get("matched_query_branches"),
    )
    policy_match: dict[str, Any] = {}
    for policy in (panel_policy.get("path_policies") or []):
        if not isinstance(policy, dict):
            continue
        keys = normalized_values(policy.get("id"), policy.get("role"))
        if any(key and any(key in role for role in candidate_roles) for key in keys):
            policy_match = policy
            break

    explicit_tier = _normalize(str(candidate.get("panel_evidence_tier") or "")).lower()
    tier = explicit_tier or str(policy_match.get("panel_evidence_tier") or "").strip().lower()
    role = (
        str(candidate.get("evidence_path_role") or "").strip()
        or str(policy_match.get("role") or policy_match.get("id") or "").strip()
    )
    evidence_kind = (
        str(candidate.get("evidence_kind") or "").strip()
        or str(policy_match.get("evidence_kind") or "").strip()
    )
    path_metadata_present = bool(
        tier
        or role
        or policy_match
        or candidate.get("panel_component_path") is not None
        or candidate.get("core_evidence_capable") is not None
        or candidate.get("component_evidence_counts_as_panel_core") is not None
    )
    if not path_metadata_present:
        layer_policy = {}
    else:
        layer_policy = (
            policy_match.get("retrieval_layer_policy")
            if isinstance(policy_match.get("retrieval_layer_policy"), dict)
            else panel_path_retrieval_layer_policy(
                tier=tier or "support",
                role=role,
                evidence_kind=evidence_kind,
            )
        )
    if candidate.get("core_evidence_capable") is not None:
        core_capable = bool(candidate.get("core_evidence_capable"))
    elif not path_metadata_present:
        core_capable = True
    else:
        core_capable = bool(layer_policy.get("core_evidence_capable"))
    component_path = bool(
        path_metadata_present
        and (
            candidate.get("panel_component_path") is True
            or layer_policy.get("panel_component_path")
            or tier in {"support", "context"}
            or any(
                marker in role_value
                for role_value in candidate_roles
                for marker in ("support", "component", "constraint", "deployment", "background", "framework")
            )
        )
    )
    auxiliary_only = bool(not core_capable)
    component_support_only = bool(component_path and auxiliary_only)
    can_falsify = (
        bool(candidate.get("can_independently_falsify_sh"))
        if candidate.get("can_independently_falsify_sh") is not None
        else bool(core_capable and not component_path)
    )
    failure_scope = str(candidate.get("failure_scope") or "").strip() or (
        "whole_sh_core_falsification"
        if can_falsify
        else "supporting_gap_or_mechanism_weakening"
    )
    return {
        "multi_entity_panel": True,
        "panel_evidence_tier": tier or ("core" if core_capable else "support"),
        "panel_component_path": component_path,
        "panel_core_path": bool(core_capable and not component_path),
        "panel_path_metadata_present": path_metadata_present,
        "panel_auxiliary_evidence_only": auxiliary_only,
        "panel_component_support_only": component_support_only,
        "core_evidence_capable": core_capable,
        "component_evidence_counts_as_panel_core": False if auxiliary_only else True,
        "component_evidence_counts_as_core": False if auxiliary_only else True,
        "preferred_retrieval_layers": list(layer_policy.get("preferred_retrieval_layers") or []),
        "preprint_signal_layers": list(layer_policy.get("preprint_signal_layers") or []),
        "retrieval_layer_role": str(layer_policy.get("retrieval_layer_role") or ""),
        "failure_scope": failure_scope,
        "can_independently_falsify_sh": can_falsify,
        "missing_path_blocks_sh": bool(candidate.get("missing_path_blocks_sh") is True and can_falsify),
        "negative_evidence_interpretation": (
            "negative core/integrative validation can falsify or materially weaken the whole SH"
            if can_falsify
            else "negative or absent support evidence becomes a localized mechanism/boundary gap"
        ),
        "panel_path_policy_id": str(policy_match.get("id") or ""),
        "panel_path_policy_role": str(policy_match.get("role") or ""),
    }


def _evidence_path_anchor_terms(contract: dict[str, Any]) -> list[str]:
    terms: list[str] = []
    for path in contract.get("evidence_paths") or []:
        if not isinstance(path, dict):
            continue
        terms.extend(_ranked_terms(str(path.get("retrieval_query") or ""), limit=10))
        for step in path.get("causal_steps") or []:
            terms.extend(_ranked_terms(str(step or ""), limit=8))
        terms.extend(
            str(value)
            for value in (path.get("id"), path.get("role"))
            if str(value or "").strip()
        )
    return [
        term
        for term in _unique(terms)
        if term and term not in _PROJECT_ANCHOR_GLUE_TERMS
    ][:48]


def _flatten_policy_economic_axis_values(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        normalized = _normalize(value)
        return [normalized] if normalized else []
    if isinstance(value, (list, tuple, set)):
        output: list[str] = []
        for item in value:
            output.extend(_flatten_policy_economic_axis_values(item))
        return output
    if isinstance(value, dict):
        output: list[str] = []
        for item in value.values():
            output.extend(_flatten_policy_economic_axis_values(item))
        return output
    return []


def _policy_economic_declared_axis_hits(contract: dict[str, Any]) -> list[str]:
    payload = contract if isinstance(contract, dict) else {}
    values: list[str] = []
    for key in (
        "scientific_object",
        "focal_variable",
        "independent_variable",
        "baseline_or_comparator",
        "falsification_condition",
        "declared_research_mode",
        "input_terms",
        "input_phrases",
        "focal_variable_terms",
        "focal_variable_phrases",
        "mechanism_terms",
        "mechanism_phrases",
        "outcome_terms",
        "outcome_phrases",
        "comparison_level_terms",
    ):
        values.extend(_flatten_policy_economic_axis_values(payload.get(key)))
    core_axis_policy = (
        payload.get("core_axis_policy")
        if isinstance(payload.get("core_axis_policy"), dict)
        else {}
    )
    for key in (
        "focal_variable",
        "focal_variable_terms",
        "focal_variable_phrases",
        "mechanism_terms",
        "mechanism_phrases",
        "outcome_terms",
        "outcome_phrases",
        "comparison_terms",
        "comparison_structure",
    ):
        values.extend(_flatten_policy_economic_axis_values(core_axis_policy.get(key)))
    structured_declared_input = (
        payload.get("structured_declared_input")
        if isinstance(payload.get("structured_declared_input"), dict)
        else {}
    )
    values.extend(_flatten_policy_economic_axis_values(structured_declared_input))
    axis_text = _normalize(" ".join(values)).lower()
    if not axis_text:
        return []
    return _unique(_hits(axis_text, list(_POLICY_ECONOMIC_SH_AXIS_MARKERS)))


def _policy_economic_context_audit(
    candidate: dict[str, Any],
    contract: dict[str, Any],
    *,
    text: str | None = None,
) -> dict[str, Any]:
    candidate_text = str(text if text is not None else _candidate_text(candidate)).lower()
    title_text = _normalize(
        " ".join(
            str(candidate.get(key) or "")
            for key in ("title", "citation", "venue")
        )
    ).lower()
    role_text = _normalize(
        " ".join(
            str(candidate.get(key) or "")
            for key in (
                "research_role",
                "query_branch",
                "query_family",
                "evidence_path_role",
                "target_lane",
                "retrieval_layer_role",
            )
        )
    ).lower()
    strong_hits = _hits(candidate_text, list(_POLICY_ECONOMIC_STRONG_CONTEXT_MARKERS))
    weak_hits = _hits(candidate_text, list(_POLICY_ECONOMIC_WEAK_CONTEXT_MARKERS))
    title_hits = _unique(
        _hits(title_text, list(_POLICY_ECONOMIC_STRONG_CONTEXT_MARKERS))
        + _hits(title_text, list(_POLICY_ECONOMIC_WEAK_CONTEXT_MARKERS))
    )
    role_hits = _unique(
        _hits(role_text, list(_POLICY_ECONOMIC_STRONG_CONTEXT_MARKERS))
        + _hits(role_text, list(_POLICY_ECONOMIC_WEAK_CONTEXT_MARKERS))
    )
    declared_axis_hits = _policy_economic_declared_axis_hits(contract)
    # Single weak words such as "cost" or "market" are intentionally not
    # enough in the abstract.  They become decisive when clustered in the
    # title/role or when a high-specificity policy/economic phrase appears.
    context_detected = bool(
        strong_hits
        or role_hits
        or len(title_hits) >= 2
        or len(weak_hits) >= 4
    )
    declares_axis = bool(declared_axis_hits)
    return {
        "schema_version": "policy_economic_context_audit_v1",
        "policy_economic_context": context_detected,
        "policy_economic_context_hits": _unique(
            strong_hits + title_hits + role_hits + weak_hits
        )[:16],
        "policy_economic_strong_context_hits": strong_hits[:12],
        "policy_economic_title_hits": title_hits[:12],
        "policy_economic_role_hits": role_hits[:12],
        "policy_economic_weak_context_hits": weak_hits[:12],
        "sh_declares_policy_economic_endpoint": declares_axis,
        "sh_policy_economic_axis_hits": declared_axis_hits[:16],
    }


def _corpus_policy_economic_alignment_fields(corpus: dict[str, Any]) -> dict[str, Any]:
    return {
        "policy_economic_context": bool(corpus.get("policy_economic_context")),
        "policy_economic_context_hits": list(
            corpus.get("policy_economic_context_hits") or []
        )[:16],
        "policy_economic_context_demoted": bool(
            corpus.get("policy_economic_context_demoted")
        ),
        "policy_economic_demoted_scope": str(
            corpus.get("policy_economic_demoted_scope") or ""
        ),
        "sh_declares_policy_economic_endpoint": bool(
            corpus.get("sh_declares_policy_economic_endpoint")
        ),
        "sh_policy_economic_axis_hits": list(
            corpus.get("sh_policy_economic_axis_hits") or []
        )[:16],
    }


def _corpus_admission_assessment(
    candidate: dict[str, Any],
    contract: dict[str, Any],
    *,
    scientific_object_hits: list[str],
    retrieval_object_profile_hits: list[str] | None = None,
    project_context_hits: list[str],
    input_hits: list[str],
    mechanism_hits: list[str],
    outcome_hits: list[str],
    focus_hits: list[str],
    exclusions: list[str],
    genre: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Layer-A admission: decide whether a paper remains in the SH corpus.

    This is intentionally wider than evidence/core admission.  A related
    method, platform, material system, measurement paper, adverse/boundary
    branch, or L1 foundation can be useful for gap discovery even when it does
    not satisfy the full input--mediator--outcome--comparison contract.
    """

    text = _candidate_text(candidate)
    genre = genre if isinstance(genre, dict) else {}
    declared_input_group = declared_input_anchor_group_for_contract(contract)
    declared_input_hits = _unique([
        item for item in declared_input_group
        if _scope_term_matches_text(item, text)
    ])
    declared_input_required = bool(declared_input_group)
    declared_input_pass = bool(
        not declared_input_required or declared_input_hits
    )
    # Project context supports ranking after identity is established; it must
    # not itself become object identity.  Otherwise broad words such as
    # ``digital``, ``memory`` or ``control`` can admit one off-topic auxiliary
    # record after the strong-object prefilter rejected the rest of the pool.
    object_entity_hits = [
        hit for hit in _unique(scientific_object_hits)
        if hit not in _LOW_SIGNAL
        and hit not in _PROJECT_ANCHOR_GLUE_TERMS
        and hit not in _RETRIEVAL_OBJECT_GENERIC_TERMS
    ]
    profile_object_hits = [
        hit for hit in _unique(retrieval_object_profile_hits or [])
        if hit not in _LOW_SIGNAL
        and hit not in _PROJECT_ANCHOR_GLUE_TERMS
        and hit not in _RETRIEVAL_OBJECT_GENERIC_TERMS
    ]
    specific_project_context_hits = [
        hit for hit in _unique(project_context_hits)
        if hit not in _LOW_SIGNAL
        and hit not in _PROJECT_ANCHOR_GLUE_TERMS
        and hit not in _RETRIEVAL_OBJECT_GENERIC_TERMS
    ]
    method_hits = _hits(text, list(_CORPUS_METHOD_PLATFORM_MARKERS))
    material_system_hits = _hits(text, list(_CORPUS_MATERIAL_SYSTEM_POPULATION_MARKERS))
    readout_hits = _unique(
        outcome_hits
        + _hits(text, list(_CORPUS_MEASURABLE_READOUT_MARKERS))
    )
    evidence_path_hits = _hits(text, _evidence_path_anchor_terms(contract))
    mechanism_or_readout_hits = _unique(mechanism_hits + focus_hits + readout_hits)
    specific_mechanism_or_readout_hits = [
        hit for hit in mechanism_or_readout_hits
        if hit not in _CORE_AXIS_GENERIC_TERMS
        and hit not in _LOW_SIGNAL
        and hit not in _PROJECT_ANCHOR_GLUE_TERMS
        # A broad focus/query token cannot create a method-context admission
        # after the record failed the source-bound object gate.
        and hit not in _RETRIEVAL_OBJECT_GENERIC_TERMS
    ]
    specific_evidence_path_hits = [
        hit for hit in evidence_path_hits
        if hit not in _CORE_AXIS_GENERIC_TERMS
        and hit not in _LOW_SIGNAL
        and hit not in _PROJECT_ANCHOR_GLUE_TERMS
    ]
    layer = str(
        candidate.get("stratified_layer")
        or candidate.get("target_layer")
        or ""
    )
    role_text = " ".join(
        str(value or "")
        for value in (
            candidate.get("research_role"),
            candidate.get("query_branch"),
            candidate.get("query_family"),
            candidate.get("evidence_path_role"),
            candidate.get("target_lane"),
        )
    ).lower()
    foundation_candidate = bool(
        layer == "L1_milestone"
        or "foundation" in role_text
        or "foundational" in role_text
        or isinstance(candidate.get("foundational_bridge_assessment"), dict)
    )
    review_like = bool(genre.get("is_review")) or bool(_hits(text, list(_REVIEW_MARKERS)))
    policy_economic_audit = _policy_economic_context_audit(
        candidate,
        contract,
        text=text,
    )
    policy_economic_context = bool(policy_economic_audit.get("policy_economic_context"))
    sh_declares_policy_economic_endpoint = bool(
        policy_economic_audit.get("sh_declares_policy_economic_endpoint")
    )

    reason = ""
    if exclusions:
        return {
            "schema_version": "corpus_admission_v1",
            "corpus_admitted": False,
            "corpus_admission_reason": "explicit_exclusion",
            "off_topic": True,
            "true_off_topic": True,
            "auxiliary_eligible": False,
            "admission_scope": "rejected",
            "sh_locality_scope": "rejected",
            "admission_scope_hint": "rejected",
            "project_background_only": False,
            "counts_toward_gate": False,
            "counts_toward_corpus_target": False,
            "excluded_from_sh_gap_synthesis": True,
            "declared_input_required": declared_input_required,
            "declared_input_terms": declared_input_group[:16],
            "declared_input_hits": declared_input_hits[:16],
            "declared_input_supported": declared_input_pass,
            "project_background_reason": "",
            "policy_economic_context": policy_economic_context,
            "policy_economic_context_hits": list(
                policy_economic_audit.get("policy_economic_context_hits") or []
            )[:16],
            "policy_economic_context_demoted": False,
            "policy_economic_demoted_scope": "",
            "sh_declares_policy_economic_endpoint": sh_declares_policy_economic_endpoint,
            "sh_policy_economic_axis_hits": list(
                policy_economic_audit.get("sh_policy_economic_axis_hits") or []
            )[:16],
            "policy_economic_context_audit": policy_economic_audit,
            "object_plus_dimension_auxiliary": False,
            "relatedness_axes": {
                "object": object_entity_hits[:12],
                "specific_project_context": specific_project_context_hits[:12],
                "declared_input": declared_input_hits[:12],
                "method_platform": method_hits[:12],
                "material_system_population": material_system_hits[:12],
                "mechanism_or_readout": mechanism_or_readout_hits[:12],
                "evidence_path": evidence_path_hits[:12],
                "policy_economic_context": list(
                    policy_economic_audit.get("policy_economic_context_hits") or []
                )[:12],
            },
        }
    object_plus_dimension_auxiliary = bool(
        object_entity_hits
        and (
            method_hits
            or material_system_hits
            or specific_mechanism_or_readout_hits
            or specific_evidence_path_hits
        )
    )
    if object_entity_hits:
        reason = "strong_scientific_object_or_semantic_alias"
    elif profile_object_hits:
        reason = "retrieval_object_profile_related"
    elif method_hits and (specific_project_context_hits or specific_evidence_path_hits or specific_mechanism_or_readout_hits):
        reason = "method_platform_context"
    elif material_system_hits and specific_mechanism_or_readout_hits:
        reason = "material_system_population_plus_mechanism_or_readout"
    elif specific_evidence_path_hits and (method_hits or material_system_hits or specific_mechanism_or_readout_hits):
        reason = "evidence_path_partial_anchor"
    elif foundation_candidate and (method_hits or material_system_hits or specific_mechanism_or_readout_hits or specific_evidence_path_hits):
        reason = "l1_foundational_local_bridge"
    elif review_like and (specific_project_context_hits or specific_evidence_path_hits):
        reason = "context_review_or_boundary_background"

    admitted = bool(reason)
    missing_declared_input_background = bool(
        admitted
        and declared_input_required
        and not declared_input_pass
    )
    policy_economic_context_demoted = bool(
        admitted
        and policy_economic_context
        and not sh_declares_policy_economic_endpoint
    )
    project_background_only = bool(
        missing_declared_input_background
        or policy_economic_context_demoted
    )
    project_background_reasons = []
    if missing_declared_input_background:
        project_background_reasons.append("missing_declared_input")
    if policy_economic_context_demoted:
        project_background_reasons.append(
            "policy_economic_context_not_declared_by_current_sh"
        )
    project_background_reason = ";".join(project_background_reasons)
    if policy_economic_context_demoted:
        reason = (
            "policy_economic_or_implementation_context"
            if not reason
            else reason
        )
    sh_local_auxiliary = bool(admitted and not project_background_only)
    component_bridge_evidence = bool(
        sh_local_auxiliary
        and (
            object_plus_dimension_auxiliary
            or specific_evidence_path_hits
            or specific_mechanism_or_readout_hits
        )
    )
    sh_locality_scope = (
        "project_background_only"
        if project_background_only
        else "component_bridge_evidence"
        if component_bridge_evidence
        else "sh_local_auxiliary"
        if sh_local_auxiliary
        else ""
    )
    return {
        "schema_version": "corpus_admission_v1",
        "corpus_admitted": admitted,
        "corpus_admission_reason": reason if admitted else "no_object_method_system_or_path_anchor",
        "off_topic": not admitted,
        "true_off_topic": not admitted,
        "auxiliary_eligible": bool(
            admitted
            and not project_background_only
            and (
                object_plus_dimension_auxiliary
                or reason
                in {
                    "retrieval_object_profile_related",
                    "method_platform_context",
                    "material_system_population_plus_mechanism_or_readout",
                    "evidence_path_partial_anchor",
                    "l1_foundational_local_bridge",
                    "context_review_or_boundary_background",
                }
            )
        ),
        "admission_scope": sh_locality_scope or "rejected",
        "sh_locality_scope": sh_locality_scope,
        "admission_scope_hint": sh_locality_scope or "rejected",
        "project_background_only": project_background_only,
        "sh_local_auxiliary": sh_local_auxiliary,
        "component_bridge_evidence": component_bridge_evidence,
        "counts_toward_gate": False if project_background_only else None,
        "counts_toward_corpus_target": False if project_background_only else None,
        "excluded_from_sh_gap_synthesis": bool(project_background_only or not admitted),
        "project_background_reason": project_background_reason,
        "declared_input_required": declared_input_required,
        "declared_input_terms": declared_input_group[:16],
        "declared_input_hits": declared_input_hits[:16],
        "declared_input_supported": declared_input_pass,
        "policy_economic_context": policy_economic_context,
        "policy_economic_context_hits": list(
            policy_economic_audit.get("policy_economic_context_hits") or []
        )[:16],
        "policy_economic_context_demoted": policy_economic_context_demoted,
        "policy_economic_demoted_scope": (
            "project_background_only" if policy_economic_context_demoted else ""
        ),
        "sh_declares_policy_economic_endpoint": sh_declares_policy_economic_endpoint,
        "sh_policy_economic_axis_hits": list(
            policy_economic_audit.get("sh_policy_economic_axis_hits") or []
        )[:16],
        "policy_economic_context_audit": policy_economic_audit,
        "counts_toward_component_bridge_gap": bool(component_bridge_evidence),
        "object_plus_dimension_auxiliary": object_plus_dimension_auxiliary,
        "relatedness_axes": {
            "object": object_entity_hits[:12],
            "retrieval_object_profile": profile_object_hits[:12],
            "specific_project_context": specific_project_context_hits[:12],
            "declared_input": declared_input_hits[:12],
            "method_platform": method_hits[:12],
            "material_system_population": material_system_hits[:12],
            "mechanism_or_readout": mechanism_or_readout_hits[:12],
            "evidence_path": evidence_path_hits[:12],
            "policy_economic_context": list(
                policy_economic_audit.get("policy_economic_context_hits") or []
            )[:12],
        },
    }


def _noncore_alignment_verdict(
    corpus: dict[str, Any],
    *,
    object_pass: bool,
    edge_pass: bool,
    outcome_pass: bool,
    actual_kind: str = "",
    review_like: bool = False,
    foundation_candidate: bool = False,
) -> str:
    if corpus.get("corpus_admitted") is not True:
        return "TRUE_OFF_TOPIC_REJECTED"
    reason = str(corpus.get("corpus_admission_reason") or "")
    axes = corpus.get("relatedness_axes") if isinstance(corpus.get("relatedness_axes"), dict) else {}
    if foundation_candidate or reason == "l1_foundational_local_bridge":
        return "FOUNDATIONAL_PLATFORM_ONLY"
    if review_like:
        return "BACKGROUND_OR_REVIEW_ADMITTED"
    if reason == "method_platform_context":
        return "METHOD_RELATED_BUT_OUTCOME_MISSING" if not outcome_pass else "METHOD_OR_PLATFORM_CONTEXT_ADMITTED"
    if object_pass and not edge_pass:
        return "OBJECT_RELATED_BUT_CAUSAL_EDGE_MISSING"
    if axes.get("mechanism_or_readout") and not object_pass:
        return "MECHANISM_RELATED_BUT_OBJECT_MISMATCH"
    if actual_kind == "unclassified":
        return "FULLTEXT_DOES_NOT_SUPPORT_DECLARED_ROLE"
    return "CORE_CLAIM_NOT_SUPPORTED_BUT_AUXILIARY_RELEVANT"


def assess_candidate_alignment(
    candidate: dict[str, Any],
    contract: dict[str, Any],
    *,
    requested_evidence_kind: str = "",
    enable_focal_variable_synonym_dictionary: bool = False,
) -> dict[str, Any]:
    """Assess a candidate on project context, causal branch, and outcome.

    Scores are deliberately reported separately and eligibility is conjunctive:
    a high score for one broad word cannot compensate for zero project-context
    or outcome alignment.
    """
    text = _candidate_text(candidate)
    context_terms = [term for term in contract.get("project_context_anchor_terms", []) if term]
    context_phrases = [phrase for phrase in contract.get("project_context_phrases", []) if phrase]
    input_terms = [term for term in contract.get("input_terms", []) if term]
    mechanism_terms = [term for term in contract.get("mechanism_terms", []) if term]
    outcome_terms = [term for term in contract.get("outcome_terms", []) if term]
    mechanism_synonym_terms = mechanism_outcome_synonym_terms(contract, axis="mechanism", limit=16)
    outcome_synonym_terms = mechanism_outcome_synonym_terms(contract, axis="outcome", limit=16)
    focus_terms = [term for term in contract.get("focus_terms", []) if term]

    context_hits = _hits(text, context_terms)
    context_phrase_hits = _hits(text, context_phrases)
    input_hits = _hits(text, input_terms)
    mechanism_hits = _unique(_hits(text, mechanism_terms) + _hits(text, mechanism_synonym_terms))
    outcome_hits = _unique(_hits(text, outcome_terms) + _hits(text, outcome_synonym_terms))
    focus_hits = _hits(text, focus_terms)
    # A project-local entity word can establish context even when that word is
    # broad elsewhere (water, signal, algorithm, neural, ...).  A generic
    # outcome/property alone (e.g. merely ``stability``) cannot: it needs an
    # adjacent project phrase or a non-generic project entity.  This keeps
    # ``DNA replication stability`` out of an alternative-solvent project
    # without globally banning the vocabulary of materials or physics.
    context_entity_hits = [hit for hit in context_hits if hit not in _LOW_SIGNAL]
    context_pass = bool(context_phrase_hits or context_entity_hits)
    input_pass = bool(input_hits) if input_terms else True
    # A sub-hypothesis may intentionally leave its mediator unresolved; in
    # that case the candidate may supply it, but it must still match the input
    # and outcome.  Where a mediator is specified, it reinforces the branch.
    mechanism_or_focus_pass = bool(mechanism_hits or focus_hits) if (mechanism_terms or focus_terms) else True
    outcome_pass = bool(outcome_hits) if outcome_terms else True
    # Use the already domain-neutral genre classifier for a dedicated lane.
    # A valid direct observation, field demonstration, or operating system
    # study need not literally call itself an "experiment" in every natural
    # science.  This preserves the separate theory/experiment lanes without
    # privileging laboratory vocabulary over field, ecological, geological, or
    # astronomical evidence forms.
    genre = classify_paper_evidence_genre(candidate, semantic_contract=contract)
    requested_kind = str(requested_evidence_kind or "").strip().lower()
    evidence_mode = str(contract.get("evidence_mode") or CAUSAL_MECHANISM_EVIDENCE_MODE)
    exclusions = _explicit_exclusion_hits(candidate, contract)
    panel_alignment = _candidate_panel_alignment_metadata(candidate, contract)
    panel_core_allowed = bool(
        not panel_alignment.get("multi_entity_panel")
        or panel_alignment.get("core_evidence_capable")
    )
    if evidence_mode == PREDICTIVE_GENERALIZATION_EVIDENCE_MODE:
        # A predictive/generalization SH follows the same identity rule as
        # every other SH: broad project context may rank a result, but it
        # cannot substitute for the declared scientific object.
        object_hits = _source_bound_scientific_object_hits(text, contract)
        retrieval_profile_alignment = _retrieval_object_profile_hits(
            text, contract, candidate
        )
        object_entity_hits = [
            hit for hit in object_hits
            if hit not in _LOW_SIGNAL
            and hit not in _RETRIEVAL_OBJECT_GENERIC_TERMS
        ]
        object_pass = bool(object_entity_hits)
        moderator_hits = _hits(text, list(contract.get("moderator_terms") or []))
        validation_hits = _hits(text, list(contract.get("predictive_validation_terms") or []))
        moderator_pass = bool(moderator_hits)
        validation_pass = bool(validation_hits)
        review_like = bool(genre.get("is_review")) or bool(_hits(text, list(_REVIEW_MARKERS)))
        review_requested = requested_kind == "theoretical_framework"
        predictive_requested = requested_kind in {"", "predictive_validation"}
        requested_role_text = " ".join(
            str(value or "")
            for value in (
                requested_kind,
                candidate.get("target_lane"),
                candidate.get("evidence_path_role"),
                candidate.get("query_family"),
                candidate.get("retrieval_layer_role"),
                candidate.get("evidence_path_polarity"),
            )
        ).lower()
        adverse_requested = any(
            marker in requested_role_text
            for marker in _ADVERSE_OR_REVERSAL_ROLE_MARKERS
        )
        adverse_hits = _hits(text, list(_ADVERSE_OR_REVERSAL_EVIDENCE_MARKERS))
        review_eligible = bool(
            review_requested
            and review_like
            and object_pass
            and moderator_pass
            and not exclusions
        )
        predictive_eligible = bool(
            predictive_requested
            and not review_like
            and object_pass
            and moderator_pass
            and validation_pass
            and not exclusions
        )
        adverse_eligible = bool(
            adverse_requested
            and not review_like
            and object_pass
            and (moderator_pass or validation_pass)
            and adverse_hits
            and not exclusions
        )
        actual_kind = (
            "theoretical_framework" if review_eligible
            else "adverse_or_reversal" if adverse_eligible
            else "predictive_validation" if predictive_eligible
            else "unclassified"
        )
        evidence_lane = (
            "BACKGROUND_REVIEW" if review_eligible
            else "ADVERSE_OR_REVERSAL_EVIDENCE" if adverse_eligible
            else "BOUNDARY_OR_NEGATIVE_EVIDENCE" if predictive_eligible
            else "PENDING_FULLTEXT_TYPE_DIRECTED_EVIDENCE"
        )
        standard_assessment = standard_evidence_design_assessment(
            candidate,
            contract.get("evidence_standard") if isinstance(contract.get("evidence_standard"), dict) else {},
            research_design="predictive_validation" if (predictive_eligible or adverse_eligible) else str(genre.get("research_design") or "unclassified"),
            causal_role="adverse_or_reversal" if adverse_eligible else "predictive_validation" if predictive_eligible else "background_or_framework" if review_eligible else "unclassified",
            paper_genre=genre,
        )
        standard_core_eligible = bool(
            (predictive_eligible or adverse_eligible)
            and (
                standard_assessment.get("core_design_match")
                or standard_assessment.get("local_edge_core_design_match")
            )
            and panel_core_allowed
        )
        reason_parts: list[str] = []
        if not object_pass:
            reason_parts.append("no current clinical-model or scientific-object anchor")
        if not moderator_pass:
            reason_parts.append("no declared population or deployment-boundary anchor")
        if predictive_requested and not review_like and not validation_pass:
            reason_parts.append("no external, subgroup, calibration, fairness, or transportability validation evidence")
        if adverse_requested and not review_like and not adverse_hits:
            reason_parts.append("no adverse, reversal, rebound, burden-shifting, or failure-mode evidence")
        if review_requested and not review_like:
            reason_parts.append("not an aligned review or framework paper")
        if review_like and predictive_requested:
            reason_parts.append("review cannot fill a direct predictive-validation slot")
        if review_like and adverse_requested:
            reason_parts.append("review cannot fill an adverse/reversal validation slot")
        if exclusions:
            reason_parts.append("matched explicit exclusion: " + ", ".join(exclusions[:3]))
        corpus = _corpus_admission_assessment(
            candidate,
            contract,
            scientific_object_hits=object_hits,
            retrieval_object_profile_hits=list(
                retrieval_profile_alignment.get("hits") or []
            ),
            project_context_hits=context_hits + context_phrase_hits,
            input_hits=input_hits,
            mechanism_hits=mechanism_hits,
            outcome_hits=outcome_hits,
            focus_hits=focus_hits,
            exclusions=exclusions,
            genre=genre,
        )
        corpus_project_background_only = bool(corpus.get("project_background_only"))
        type_directed = type_directed_admission(
            candidate,
            contract,
            context_admitted=bool(corpus.get("corpus_admitted") or object_pass),
            excluded=bool(exclusions) or corpus_project_background_only,
            panel_core_allowed=panel_core_allowed,
            requested_evidence_kind=requested_kind,
        )
        evidence_lane = str(type_directed.get("evidence_lane") or evidence_lane)
        foundation_candidate = bool(
            str(candidate.get("stratified_layer") or candidate.get("target_layer") or "") == "L1_milestone"
            or "foundation" in str(candidate.get("research_role") or "").lower()
            or isinstance(candidate.get("foundational_bridge_assessment"), dict)
        )
        object_maturity_audit = (
            contract.get("object_maturity_audit")
            if isinstance(contract.get("object_maturity_audit"), dict)
            else {}
        )
        if not _object_maturity_direct_core_allowed(object_maturity_audit):
            maturity_project_background_only = bool(
                corpus.get("corpus_admitted")
                and corpus_project_background_only
            )
            maturity_auxiliary_eligible = bool(
                corpus.get("corpus_admitted")
                and not corpus_project_background_only
            )
            maturity_role = (
                "background_review"
                if review_like or review_requested
                else "boundary_or_safety_evidence"
                if adverse_requested or bool(adverse_hits)
                else "translational_bridge"
                if validation_hits or moderator_hits
                else "component_evidence"
            )
            maturity_lane = (
                "BACKGROUND_REVIEW"
                if maturity_role == "background_review"
                else "BOUNDARY_OR_NEGATIVE_EVIDENCE"
                if maturity_role == "boundary_or_safety_evidence"
                else "TRANSLATIONAL_BRIDGE_EVIDENCE"
                if maturity_role == "translational_bridge"
                else "COMPONENT_EVIDENCE"
            )
            return {
                "version": ALIGNMENT_VERSION,
                "project_id": str(contract.get("project_id") or ""),
                "project_version": int(contract.get("project_version") or 0),
                "alignment_card_hash": str(contract.get("alignment_card_hash") or ""),
                "contract_hash": str(contract.get("contract_hash") or ""),
                "sub_hypothesis_id": str(contract.get("sub_hypothesis_id") or ""),
                "evidence_mode": evidence_mode,
                "requested_evidence_kind": requested_kind,
                "evidence_kind": actual_kind if actual_kind != "unclassified" else "component_context",
                "paper_genre": genre,
                "research_design": str(genre.get("research_design") or "unclassified"),
                "causal_role": maturity_role,
                "supported_causal_roles": [maturity_role] if maturity_auxiliary_eligible else [],
                "standard_evidence_design": standard_assessment,
                "standard_research_design": str(standard_assessment.get("standard_research_design") or "unclassified"),
                "standard_evidence_lane": str(standard_assessment.get("standard_evidence_lane") or "UNCLASSIFIED_STANDARD_EVIDENCE"),
                "standard_core_eligible": False,
                "evidence_strength": "component_or_bridge_context" if maturity_auxiliary_eligible else "unclassified",
                "evidence_admission_status": "DIRECT_CORE_DISALLOWED_BY_OBJECT_MATURITY",
                "type_directed_evidence": {
                    **type_directed,
                    "core_eligible": False,
                    "import_eligible": maturity_auxiliary_eligible,
                    "object_maturity_direct_core_disallowed": True,
                },
                "evidence_lane": maturity_lane,
                "import_eligible": maturity_auxiliary_eligible,
                "core_eligible": False,
                "corpus_admitted": bool(corpus.get("corpus_admitted")),
                "corpus_admission_reason": str(corpus.get("corpus_admission_reason") or ""),
                "corpus_admission": corpus,
                "off_topic": not (
                    maturity_auxiliary_eligible
                    or maturity_project_background_only
                ),
                "auxiliary_eligible": maturity_auxiliary_eligible,
                "gate_counting_evidence": False,
                "corpus_target_counting_evidence": bool(
                    corpus.get("counts_toward_component_bridge_gap")
                ),
                "counts_toward_gate": False,
                "counts_toward_corpus_target": bool(
                    corpus.get("counts_toward_component_bridge_gap")
                ),
                "admission_scope": str(
                    corpus.get("admission_scope")
                    or corpus.get("sh_locality_scope")
                    or (
                        "project_background_only"
                        if maturity_project_background_only
                        else ""
                    )
                ),
                "sh_locality_scope": str(corpus.get("sh_locality_scope") or ""),
                "project_background_only": maturity_project_background_only,
                "excluded_from_sh_gap_synthesis": maturity_project_background_only,
                "declared_input_required": bool(corpus.get("declared_input_required")),
                "declared_input_terms": list(corpus.get("declared_input_terms") or [])[:16],
                "declared_input_hits": list(corpus.get("declared_input_hits") or [])[:16],
                "counts_toward_component_bridge_gap": bool(
                    corpus.get("counts_toward_component_bridge_gap")
                ),
                **_corpus_policy_economic_alignment_fields(corpus),
                "context_only_evidence": maturity_role == "background_review",
                "evidence_role": (
                    "project_background"
                    if maturity_project_background_only
                    else maturity_role
                ),
                "evidence_polarity": (
                    "context"
                    if maturity_role == "background_review"
                    else "supportive"
                    if maturity_role == "component_evidence"
                    else "boundary"
                ),
                "object_maturity_audit": object_maturity_audit,
                "object_maturity_status": _object_maturity_status_from_audit(object_maturity_audit),
                "direct_core_disallowed_by_object_maturity": True,
                "verdict": (
                    "PROJECT_BACKGROUND_ONLY_ADMITTED"
                    if maturity_project_background_only
                    else
                    "RELATED_COMPONENT_OR_BRIDGE_EVIDENCE_ADMITTED"
                    if maturity_auxiliary_eligible and maturity_role != "background_review"
                    else "BACKGROUND_OR_REVIEW_ADMITTED"
                    if maturity_auxiliary_eligible
                    else "TRUE_OFF_TOPIC_REJECTED"
                ),
                "reason": (
                    "Project/background context matched, but the paper does not mention the declared SH input/exposure/intervention; excluded from SH-local gate and gap synthesis."
                    if maturity_project_background_only
                    else
                    "Direct predictive/core validation is disabled because the declared SH object is not a mature literature identity; retained only as component, bridge, boundary, or context evidence."
                    if maturity_auxiliary_eligible
                    else "No component, bridge, boundary, or context evidence matched the immature-object retrieval profile."
                ),
                "project_context": _axis(object_hits, bool(object_hits)),
                "project_context_entity_hits": object_entity_hits[:12],
                "subhypothesis_input": _axis(input_hits, input_pass),
                "mechanism_or_focus": _axis(mechanism_hits + focus_hits, mechanism_or_focus_pass),
                "functional_outcome": _axis(outcome_hits, outcome_pass),
                "predictive_boundary": _axis(moderator_hits, moderator_pass),
                "predictive_validation": _axis(validation_hits, validation_pass),
                "adverse_or_reversal": _axis(adverse_hits, bool(adverse_hits)),
                "exclusion_hits": exclusions,
                **panel_alignment,
            }
        noncore_verdict = _noncore_alignment_verdict(
            corpus,
            object_pass=object_pass,
            edge_pass=bool(predictive_eligible or adverse_eligible),
            outcome_pass=bool(validation_pass or moderator_pass or outcome_pass),
            actual_kind=actual_kind,
            review_like=review_like,
            foundation_candidate=foundation_candidate,
        )
        predictive_or_adverse_core_eligible = bool(type_directed.get("core_eligible"))
        sh_local_import_eligible = bool(type_directed.get("import_eligible"))
        standard_core_eligible = bool(
            predictive_or_adverse_core_eligible
            and (
                standard_assessment.get("core_design_match")
                or standard_assessment.get("local_edge_core_design_match")
            )
        )
        return {
            "version": ALIGNMENT_VERSION,
            "project_id": str(contract.get("project_id") or ""),
            "project_version": int(contract.get("project_version") or 0),
            "alignment_card_hash": str(contract.get("alignment_card_hash") or ""),
            "contract_hash": str(contract.get("contract_hash") or ""),
            "sub_hypothesis_id": str(contract.get("sub_hypothesis_id") or ""),
            "evidence_mode": evidence_mode,
            "requested_evidence_kind": requested_kind,
            "evidence_kind": actual_kind,
            "paper_genre": genre,
            "research_design": "predictive_validation" if (predictive_eligible or adverse_eligible) else str(genre.get("research_design") or "unclassified"),
            "causal_role": "adverse_or_reversal" if adverse_eligible else "predictive_validation" if predictive_eligible else "background_or_framework" if review_eligible else "unclassified",
            "supported_causal_roles": ["adverse_or_reversal"] if adverse_eligible else ["predictive_validation"] if predictive_eligible else (["background_or_framework"] if review_eligible else []),
            "standard_evidence_design": standard_assessment,
            "standard_research_design": str(standard_assessment.get("standard_research_design") or "unclassified"),
            "standard_evidence_lane": str(standard_assessment.get("standard_evidence_lane") or "UNCLASSIFIED_STANDARD_EVIDENCE"),
            "standard_core_eligible": standard_core_eligible,
            "evidence_strength": "direct" if (predictive_eligible or adverse_eligible) else "contextual" if review_eligible else "unclassified",
            "evidence_admission_status": str(type_directed.get("admission_status") or ""),
            "type_directed_evidence": type_directed,
            "evidence_lane": evidence_lane,
            "import_eligible": sh_local_import_eligible,
            "core_eligible": predictive_or_adverse_core_eligible,
            "corpus_admitted": bool(corpus.get("corpus_admitted")),
            "corpus_admission_reason": str(corpus.get("corpus_admission_reason") or ""),
            "corpus_admission": corpus,
            "off_topic": bool(corpus.get("off_topic")) and not corpus_project_background_only,
            "auxiliary_eligible": bool(
                corpus.get("auxiliary_eligible")
                and not (predictive_eligible or adverse_eligible)
                and not corpus_project_background_only
            ),
            "gate_counting_evidence": bool(
                sh_local_import_eligible
            ),
            "corpus_target_counting_evidence": bool(
                sh_local_import_eligible
                or corpus.get("counts_toward_component_bridge_gap")
            ),
            "counts_toward_gate": bool(sh_local_import_eligible),
            "counts_toward_corpus_target": bool(
                sh_local_import_eligible
                or corpus.get("counts_toward_component_bridge_gap")
            ),
            "admission_scope": (
                "core_or_core_compatible"
                if predictive_or_adverse_core_eligible
                else str(
                    corpus.get("admission_scope")
                    or corpus.get("sh_locality_scope")
                    or ""
                )
            ),
            "sh_locality_scope": (
                "core_or_core_compatible"
                if predictive_or_adverse_core_eligible
                else str(corpus.get("sh_locality_scope") or "")
            ),
            "project_background_only": corpus_project_background_only,
            "excluded_from_sh_gap_synthesis": corpus_project_background_only,
            "declared_input_required": bool(corpus.get("declared_input_required")),
            "declared_input_terms": list(corpus.get("declared_input_terms") or [])[:16],
            "declared_input_hits": list(corpus.get("declared_input_hits") or [])[:16],
            "counts_toward_component_bridge_gap": bool(
                corpus.get("counts_toward_component_bridge_gap")
            ),
            **_corpus_policy_economic_alignment_fields(corpus),
            "evidence_role": (
                "adverse_or_reversal" if adverse_eligible
                else "boundary_or_generalization" if predictive_eligible
                else "project_background" if corpus_project_background_only
                else "background_review" if review_eligible
                else "foundational_bridge" if foundation_candidate and corpus.get("corpus_admitted")
                else "method_or_platform_context" if str(corpus.get("corpus_admission_reason") or "") == "method_platform_context"
                else "related_reserve" if corpus.get("corpus_admitted")
                else ""
            ),
            "evidence_polarity": (
                "opposing" if adverse_eligible
                else "boundary" if predictive_eligible
                else "unclear"
            ),
            "verdict": (
                "CORE_ADVERSE_OR_REVERSAL_EVIDENCE"
                if adverse_eligible and predictive_or_adverse_core_eligible
                else "AUXILIARY_ADVERSE_OR_REVERSAL_EVIDENCE"
                if adverse_eligible and not corpus_project_background_only
                else
                "CORE_PREDICTIVE_VALIDATION_EVIDENCE"
                if predictive_eligible and predictive_or_adverse_core_eligible
                else "AUXILIARY_PREDICTIVE_PANEL_COMPONENT_EVIDENCE"
                if predictive_eligible and not corpus_project_background_only
                else "AUXILIARY_BACKGROUND_EVIDENCE"
                if review_eligible and not corpus_project_background_only
                else "PROJECT_BACKGROUND_ONLY_ADMITTED"
                if corpus_project_background_only
                else noncore_verdict
            ),
            "reason": str(type_directed.get("reason") or "; ".join(reason_parts)),
            "project_context": _axis(object_hits, object_pass),
            "project_context_entity_hits": object_entity_hits[:12],
            "subhypothesis_input": _axis(input_hits, input_pass),
            "mechanism_or_focus": _axis(mechanism_hits + focus_hits, mechanism_or_focus_pass),
            "functional_outcome": _axis(outcome_hits, outcome_pass),
            "predictive_boundary": _axis(moderator_hits, moderator_pass),
            "predictive_validation": _axis(validation_hits, validation_pass),
            "adverse_or_reversal": _axis(adverse_hits, bool(adverse_hits)),
            "exclusion_hits": exclusions,
            **panel_alignment,
        }
    responsibility = classify_causal_role(candidate, paper_genre=genre)
    causal_role = str(responsibility.get("causal_role") or "unclassified")
    supported_roles = {
        str(value)
        for value in (responsibility.get("supported_causal_roles") or [])
        if str(value).strip()
    }
    if requested_kind == "theoretical_framework":
        actual_kind = (
            "theoretical_framework"
            if bool(genre.get("direct_theoretical_evidence"))
            else "unclassified"
        )
    elif requested_kind == "experimental_evidence":
        actual_kind = (
            "experimental_evidence"
            if bool(genre.get("direct_experimental_evidence"))
            else "unclassified"
        )
    elif requested_kind == "mechanism_discovery":
        actual_kind = (
            "mechanism_discovery"
            if "mechanism_discovery" in supported_roles
            else "unclassified"
        )
    elif requested_kind == "causal_validation":
        actual_kind = (
            causal_role
            if causal_role in {"causal_validation", "causal_identification"}
            else "unclassified"
        )
    else:
        legacy_kind = classify_evidence_kind(text, requested_evidence_kind=requested_evidence_kind)
        actual_kind = (
            legacy_kind
            if legacy_kind != "unclassified"
            else causal_role
            if causal_role not in {"background_or_framework", "unclassified"}
            else "unclassified"
        )
    type_directed = type_directed_admission(
        candidate,
        contract,
        context_admitted=context_pass,
        excluded=bool(exclusions),
        panel_core_allowed=panel_core_allowed,
        requested_evidence_kind=requested_evidence_kind,
    )
    if actual_kind == "unclassified" and bool(genre.get("is_review")):
        actual_kind = "background_review"
    # A metadata candidate can be imported for full-text acquisition when it
    # is within the RQ boundary.  Direct/core eligibility is later decided
    # only from the current contract-keyed V3 source admission.
    import_eligible = bool(type_directed.get("import_eligible"))
    core_eligible = bool(type_directed.get("core_eligible"))
    standard_assessment = standard_evidence_design_assessment(
        candidate,
        contract.get("evidence_standard") if isinstance(contract.get("evidence_standard"), dict) else {},
        research_design=str(genre.get("research_design") or "unclassified"),
        causal_role=causal_role,
        paper_genre=genre,
    )
    standard_core_eligible = bool(
        core_eligible
        and (
            standard_assessment.get("core_design_match")
            or standard_assessment.get("local_edge_core_design_match")
        )
        and panel_core_allowed
    )
    reason_parts = []
    if not context_pass:
        reason_parts.append("no project-context anchor")
    if not type_directed.get("source_admission_present"):
        reason_parts.append("contract-bound source admission pending full-text extraction")
    for slot in type_directed.get("missing_required_slots") or []:
        reason_parts.append(f"required evidence slot not source-bound: {slot}")
    if exclusions:
        reason_parts.append("matched explicit exclusion: " + ", ".join(exclusions[:3]))
    if actual_kind == "unclassified":
        if requested_kind == "mechanism_discovery":
            reason_parts.append("does not identify as mechanism-discovery evidence")
        elif requested_kind == "causal_validation":
            reason_parts.append("does not identify as causal-validation or causal-identification evidence")
        else:
            reason_parts.append("does not identify as an eligible evidence design and causal role")
    if type_directed.get("core_eligible") and not panel_core_allowed:
        reason_parts.append("panel component/context path cannot satisfy panel-level core")
    source_bound_object_hits = _source_bound_scientific_object_hits(text, contract)
    retrieval_profile_alignment = _retrieval_object_profile_hits(
        text, contract, candidate
    )
    corpus = _corpus_admission_assessment(
        candidate,
        contract,
        scientific_object_hits=source_bound_object_hits,
        retrieval_object_profile_hits=list(
            retrieval_profile_alignment.get("hits") or []
        ),
        project_context_hits=context_hits + context_phrase_hits,
        input_hits=input_hits,
        mechanism_hits=mechanism_hits,
        outcome_hits=outcome_hits,
        focus_hits=focus_hits,
        exclusions=exclusions,
        genre=genre,
    )
    corpus_project_background_only = bool(corpus.get("project_background_only"))
    type_directed = type_directed_admission(
        candidate,
        contract,
        context_admitted=bool(corpus.get("corpus_admitted") or context_pass),
        excluded=bool(exclusions) or corpus_project_background_only,
        panel_core_allowed=panel_core_allowed,
        requested_evidence_kind=requested_evidence_kind,
    )
    import_eligible = bool(type_directed.get("import_eligible"))
    core_eligible = bool(type_directed.get("core_eligible"))
    standard_core_eligible = bool(
        core_eligible
        and (
            standard_assessment.get("core_design_match")
            or standard_assessment.get("local_edge_core_design_match")
        )
        and panel_core_allowed
    )
    foundation_candidate = bool(
        str(candidate.get("stratified_layer") or candidate.get("target_layer") or "") == "L1_milestone"
        or "foundation" in str(candidate.get("research_role") or "").lower()
        or isinstance(candidate.get("foundational_bridge_assessment"), dict)
    )
    object_maturity_audit = (
        contract.get("object_maturity_audit")
        if isinstance(contract.get("object_maturity_audit"), dict)
        else {}
    )
    if not _object_maturity_direct_core_allowed(object_maturity_audit):
        role_text = " ".join(
            str(value or "")
            for value in (
                candidate.get("target_lane"),
                candidate.get("evidence_path_role"),
                candidate.get("query_family"),
                candidate.get("retrieval_layer_role"),
                candidate.get("evidence_path_polarity"),
            )
        ).lower()
        if "bridge" in role_text or "translation" in role_text:
            maturity_role = "translational_bridge"
            maturity_lane = "TRANSLATIONAL_BRIDGE_EVIDENCE"
            maturity_polarity = "boundary"
        elif "safety" in role_text or "boundary" in role_text or "failure" in role_text:
            maturity_role = "boundary_or_safety_evidence"
            maturity_lane = "BOUNDARY_OR_NEGATIVE_EVIDENCE"
            maturity_polarity = "boundary"
        elif "review" in role_text or "framework" in role_text or bool(genre.get("is_review")):
            maturity_role = "background_review"
            maturity_lane = "BACKGROUND_REVIEW"
            maturity_polarity = "context"
        else:
            maturity_role = "component_evidence"
            maturity_lane = "COMPONENT_EVIDENCE"
            maturity_polarity = "supportive"
        corpus_project_background_only = bool(corpus.get("project_background_only"))
        maturity_project_background_only = bool(
            corpus.get("corpus_admitted")
            and corpus_project_background_only
        )
        maturity_auxiliary_eligible = bool(
            (
                corpus.get("corpus_admitted")
                or type_directed.get("import_eligible")
                or type_directed.get("supporting_source_span_ids")
            )
            and not corpus_project_background_only
        )
        maturity_noncore_verdict = (
            "PROJECT_BACKGROUND_ONLY_ADMITTED"
            if maturity_project_background_only
            else
            "RELATED_COMPONENT_OR_BRIDGE_EVIDENCE_ADMITTED"
            if maturity_auxiliary_eligible and maturity_role != "background_review"
            else "BACKGROUND_OR_REVIEW_ADMITTED"
            if maturity_auxiliary_eligible
            else "TRUE_OFF_TOPIC_REJECTED"
        )
        return {
            "version": ALIGNMENT_VERSION,
            "project_id": str(contract.get("project_id") or ""),
            "project_version": int(contract.get("project_version") or 0),
            "alignment_card_hash": str(contract.get("alignment_card_hash") or ""),
            "contract_hash": str(contract.get("contract_hash") or ""),
            "sub_hypothesis_id": str(contract.get("sub_hypothesis_id") or ""),
            "requested_evidence_kind": str(requested_evidence_kind or ""),
            "evidence_kind": actual_kind if actual_kind != "unclassified" else str(candidate.get("evidence_kind") or "component_context"),
            "paper_genre": genre,
            "research_design": str(genre.get("research_design") or "unclassified"),
            "causal_role": maturity_role,
            "supported_causal_roles": sorted(supported_roles),
            "standard_evidence_design": standard_assessment,
            "standard_research_design": str(standard_assessment.get("standard_research_design") or "unclassified"),
            "standard_evidence_lane": str(standard_assessment.get("standard_evidence_lane") or "UNCLASSIFIED_STANDARD_EVIDENCE"),
            "standard_core_eligible": False,
            "evidence_strength": "component_or_bridge_context" if maturity_auxiliary_eligible else "unclassified",
            "evidence_admission_status": "DIRECT_CORE_DISALLOWED_BY_OBJECT_MATURITY",
            "type_directed_evidence": {
                **type_directed,
                "core_eligible": False,
                "import_eligible": maturity_auxiliary_eligible,
                "object_maturity_direct_core_disallowed": True,
            },
            "evidence_lane": maturity_lane,
            "import_eligible": maturity_auxiliary_eligible,
            "core_eligible": False,
            "corpus_admitted": bool(corpus.get("corpus_admitted")),
            "corpus_admission_reason": str(corpus.get("corpus_admission_reason") or ""),
            "corpus_admission": corpus,
            "off_topic": not (
                maturity_auxiliary_eligible
                or maturity_project_background_only
            ),
            "auxiliary_eligible": maturity_auxiliary_eligible,
            "gate_counting_evidence": False,
            "corpus_target_counting_evidence": bool(
                corpus.get("counts_toward_component_bridge_gap")
            ),
            "counts_toward_gate": False,
            "counts_toward_corpus_target": bool(
                corpus.get("counts_toward_component_bridge_gap")
            ),
            "admission_scope": str(
                corpus.get("admission_scope")
                or corpus.get("sh_locality_scope")
                or (
                    "project_background_only"
                    if maturity_project_background_only
                    else ""
                )
            ),
            "sh_locality_scope": str(corpus.get("sh_locality_scope") or ""),
            "project_background_only": maturity_project_background_only,
            "excluded_from_sh_gap_synthesis": maturity_project_background_only,
            "declared_input_required": bool(corpus.get("declared_input_required")),
            "declared_input_terms": list(corpus.get("declared_input_terms") or [])[:16],
            "declared_input_hits": list(corpus.get("declared_input_hits") or [])[:16],
            "counts_toward_component_bridge_gap": bool(
                corpus.get("counts_toward_component_bridge_gap")
            ),
            **_corpus_policy_economic_alignment_fields(corpus),
            "context_only_evidence": maturity_role == "background_review",
            "evidence_role": (
                "project_background"
                if maturity_project_background_only
                else maturity_role
            ),
            "evidence_polarity": maturity_polarity,
            "object_maturity_audit": object_maturity_audit,
            "object_maturity_status": _object_maturity_status_from_audit(object_maturity_audit),
            "direct_core_disallowed_by_object_maturity": True,
            "verdict": maturity_noncore_verdict,
            "reason": (
                "Project/background context matched, but the paper does not mention the declared SH input/exposure/intervention; excluded from SH-local gate and gap synthesis."
                if maturity_project_background_only
                else
                "Direct-core validation is disabled because the declared SH object is not a mature literature identity; "
                "this paper is retained only as component, bridge, boundary, or context evidence."
                if maturity_auxiliary_eligible
                else "No component, bridge, boundary, or source-bound object evidence matched the immature-object retrieval profile."
            ),
            "project_context": _axis(context_hits + context_phrase_hits, bool(context_hits or context_phrase_hits)),
            "project_context_entity_hits": context_entity_hits[:12],
            "subhypothesis_input": _axis(input_hits, input_pass),
            "mechanism_or_focus": _axis(mechanism_hits + focus_hits, mechanism_or_focus_pass),
            "functional_outcome": _axis(outcome_hits, outcome_pass),
            "exclusion_hits": exclusions,
            **panel_alignment,
        }
    noncore_verdict = _noncore_alignment_verdict(
        corpus,
        object_pass=bool(context_pass or corpus.get("corpus_admitted")),
        edge_pass=bool(type_directed.get("source_admission_present")),
        outcome_pass=outcome_pass,
        actual_kind=actual_kind,
        review_like=bool(genre.get("is_review")),
        foundation_candidate=foundation_candidate,
    )
    evidence_role = (
        "core_validation" if core_eligible
        else "supporting_mechanism" if import_eligible
        else "foundational_bridge" if foundation_candidate and corpus.get("corpus_admitted")
        else "method_or_platform_context" if str(corpus.get("corpus_admission_reason") or "") == "method_platform_context"
        else "background_review" if bool(genre.get("is_review")) and corpus.get("corpus_admitted")
        else "related_reserve" if corpus.get("corpus_admitted")
        else ""
    )
    corpus_project_background_only = bool(corpus.get("project_background_only"))
    if corpus_project_background_only:
        evidence_role = "project_background"
    return {
        "version": ALIGNMENT_VERSION,
        "project_id": str(contract.get("project_id") or ""),
        "project_version": int(contract.get("project_version") or 0),
        "alignment_card_hash": str(contract.get("alignment_card_hash") or ""),
        "contract_hash": str(contract.get("contract_hash") or ""),
        "sub_hypothesis_id": str(contract.get("sub_hypothesis_id") or ""),
        "requested_evidence_kind": str(requested_evidence_kind or ""),
        "evidence_kind": actual_kind,
        "paper_genre": genre,
        "research_design": str(genre.get("research_design") or "unclassified"),
        "causal_role": causal_role,
        "supported_causal_roles": sorted(supported_roles),
        "standard_evidence_design": standard_assessment,
        "standard_research_design": str(standard_assessment.get("standard_research_design") or "unclassified"),
        "standard_evidence_lane": str(standard_assessment.get("standard_evidence_lane") or "UNCLASSIFIED_STANDARD_EVIDENCE"),
        "standard_core_eligible": standard_core_eligible,
        "evidence_strength": str(responsibility.get("evidence_strength") or "unclassified"),
        "evidence_admission_status": str(type_directed.get("admission_status") or ""),
        "core_evidence_role": (
            "DIRECT_TYPE_DIRECTED_SOURCE_EVIDENCE" if core_eligible else "NONCORE_OR_AUXILIARY"
        ),
        "whole_sh_claim_contribution": (
            "partial"
            if core_eligible
            and str(object_maturity_audit.get("claim_completeness") or "")
            != "WHOLE_CLAIM_ESTABLISHED"
            else "whole_claim_compatible"
            if core_eligible else "none"
        ),
        "type_directed_evidence": type_directed,
        "evidence_lane": str(type_directed.get("evidence_lane") or "PENDING_FULLTEXT_TYPE_DIRECTED_EVIDENCE"),
        "import_eligible": import_eligible,
        "core_eligible": core_eligible,
        "corpus_admitted": bool(corpus.get("corpus_admitted")),
        "corpus_admission_reason": str(corpus.get("corpus_admission_reason") or ""),
        "corpus_admission": corpus,
        "off_topic": bool(corpus.get("off_topic")) and not corpus_project_background_only,
        "auxiliary_eligible": bool(
            corpus.get("auxiliary_eligible")
            and not import_eligible
            and not corpus_project_background_only
        ),
        "gate_counting_evidence": bool(import_eligible and not corpus_project_background_only),
        "corpus_target_counting_evidence": bool(
            (import_eligible and not corpus_project_background_only)
            or corpus.get("counts_toward_component_bridge_gap")
        ),
        "counts_toward_gate": bool(import_eligible and not corpus_project_background_only),
        "counts_toward_corpus_target": bool(
            (import_eligible and not corpus_project_background_only)
            or corpus.get("counts_toward_component_bridge_gap")
        ),
        "admission_scope": (
            "core_or_core_compatible"
            if core_eligible or standard_core_eligible
            else str(
                corpus.get("admission_scope")
                or corpus.get("sh_locality_scope")
                or ""
            )
        ),
        "sh_locality_scope": (
            "core_or_core_compatible"
            if core_eligible or standard_core_eligible
            else str(corpus.get("sh_locality_scope") or "")
        ),
        "project_background_only": corpus_project_background_only,
        "excluded_from_sh_gap_synthesis": corpus_project_background_only,
        "declared_input_required": bool(corpus.get("declared_input_required")),
        "declared_input_terms": list(corpus.get("declared_input_terms") or [])[:16],
        "declared_input_hits": list(corpus.get("declared_input_hits") or [])[:16],
        "counts_toward_component_bridge_gap": bool(
            corpus.get("counts_toward_component_bridge_gap")
        ),
        **_corpus_policy_economic_alignment_fields(corpus),
        "evidence_role": evidence_role,
        "evidence_polarity": "supportive" if core_eligible or import_eligible else "unclear",
        "verdict": (
            "CORE_TYPE_DIRECTED_SOURCE_EVIDENCE" if core_eligible
            else "AUXILIARY_TYPE_DIRECTED_EVIDENCE" if import_eligible
            else "PROJECT_BACKGROUND_ONLY_ADMITTED" if corpus_project_background_only
            else noncore_verdict
        ),
        "reason": (
            str(type_directed.get("reason") or "contract-bound source admission pending")
            if import_eligible else (
                "; ".join(reason_parts)
                or str(corpus.get("corpus_admission_reason") or "")
            )
        ),
        "project_context": _axis(context_hits + context_phrase_hits, context_pass),
        "project_context_entity_hits": context_entity_hits[:12],
        "subhypothesis_input": _axis(input_hits, input_pass),
        "mechanism_or_focus": _axis(mechanism_hits + focus_hits, mechanism_or_focus_pass),
        "functional_outcome": _axis(outcome_hits, outcome_pass),
        "exclusion_hits": exclusions,
        **panel_alignment,
    }


def classify_evidence_kind(text: str, *, requested_evidence_kind: str = "") -> str:
    theory_hits = _hits(text, list(_THEORY_MARKERS))
    experiment_hits = _hits(text, list(_EXPERIMENT_MARKERS))
    requested = str(requested_evidence_kind or "").strip().lower()
    # The two retrieval lanes are intentionally not interchangeable.  A
    # theory/review abstract often *mentions* experiments, and an experiment
    # often mentions a model.  When the candidate came from an explicit lane,
    # record the role it actually demonstrated for that lane; a complete
    # evidence chain must still obtain the other role from its own search.
    if requested == "theoretical_framework":
        return "theoretical_framework" if theory_hits else "unclassified"
    if requested == "experimental_evidence":
        return "experimental_evidence" if experiment_hits else "unclassified"
    if theory_hits and experiment_hits:
        return "mixed_theory_and_experiment"
    if theory_hits:
        return "theoretical_framework"
    if experiment_hits:
        return "experimental_evidence"
    # A result retrieved from a dedicated lane is not automatically allowed to
    # inherit that role: it must expose at least one content signal.
    return "unclassified"


def _source_text_handoff_role_to_field(role: Any) -> str:
    normalized = str(role or "").strip().lower()
    if normalized in {"input", "intervention", "premise", "causal_input"}:
        return "input"
    if normalized in {"mediator", "mechanism", "mechanistic_support", "specific_causal_mediator"}:
        return "mediator"
    if normalized in {"outcome", "output", "observable_outcome", "endpoint"}:
        return "outcome"
    if normalized in {"measurement", "readout", "metric", "measurement_validity"}:
        return "measurement"
    return ""


def _source_text_handoff_slot(field: str) -> str:
    return "mechanism" if field == "mediator" else field


def _source_text_handoff_text(handoff: dict[str, Any]) -> str:
    return _normalize(
        handoff.get("bounded_excerpt")
        or handoff.get("bounded_text")
        or handoff.get("excerpt")
        or handoff.get("gap_signal_text")
        or ""
    )


def _source_text_handoff_mentions_value(text: str, value: Any) -> tuple[bool, list[str]]:
    candidate = _normalize(value)
    if not text or not candidate:
        return False, []
    lowered = text.lower()
    normalized_candidate = candidate.lower()
    if normalized_candidate and normalized_candidate in lowered:
        return True, [normalized_candidate]
    terms = _ranked_terms(candidate, limit=10)
    if not terms:
        terms = [
            token.lower()
            for token in _TOKEN_RE.findall(candidate)
            if token.lower() not in _STOPWORDS and len(token) >= 3
        ][:10]
    hits = _hits(lowered, terms)
    required = 1 if len(terms) == 1 else min(2, len(terms))
    return len(hits) >= required, hits


def _handoff_supports_field(
    handoff: dict[str, Any],
    *,
    field: str,
    value: Any,
) -> dict[str, Any]:
    role_field = _source_text_handoff_role_to_field(handoff.get("source_role"))
    if role_field and role_field != field:
        return {
            "passes": False,
            "reason": f"handoff_role_{role_field}_does_not_match_{field}",
            "support_terms": [],
        }
    if str(handoff.get("binding_status") or "") != "SOURCE_UNIT_VERIFIED":
        return {
            "passes": False,
            "reason": "source_unit_not_verified",
            "support_terms": [],
        }
    if not str(handoff.get("paper_id") or "") or not str(handoff.get("source_unit_id") or ""):
        return {
            "passes": False,
            "reason": "source_identity_missing",
            "support_terms": [],
        }
    text = _source_text_handoff_text(handoff)
    passes, terms = _source_text_handoff_mentions_value(text, value)
    return {
        "passes": passes,
        "reason": "source_text_mentions_declared_value" if passes else "source_text_does_not_support_declared_value",
        "support_terms": terms[:8],
    }


def _compact_source_text_handoff_ref(handoff: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_text_handoff_id": str(handoff.get("source_text_handoff_id") or ""),
        "paper_id": str(handoff.get("paper_id") or ""),
        "source_unit_id": str(handoff.get("source_unit_id") or ""),
        "excerpt_hash": str(handoff.get("excerpt_hash") or ""),
        "source_field": str(handoff.get("source_field") or ""),
        "source_origin": str(handoff.get("source_origin") or ""),
        "source_role": str(handoff.get("source_role") or ""),
        "binding_status": str(handoff.get("binding_status") or ""),
        "acceptance_status": str(handoff.get("acceptance_status") or ""),
        "package_slot": str(handoff.get("package_slot") or ""),
    }


def _slot_source_lineage_entry(
    handoff: dict[str, Any],
    *,
    field: str,
    value: Any,
    support: dict[str, Any],
) -> dict[str, Any]:
    slot = _source_text_handoff_slot(field)
    return {
        **_compact_source_text_handoff_ref(handoff),
        "schema_version": "slot_source_lineage_v1",
        "slot": slot,
        "causal_field": field,
        "value": _normalize(value),
        "support_terms": list(support.get("support_terms") or [])[:8],
        "bounded_excerpt": _source_text_handoff_text(handoff)[:800],
    }


def _evaluate_source_text_handoffs(
    gap: dict[str, Any],
    values: dict[str, Any],
) -> dict[str, Any]:
    raw_handoffs = gap.get("source_text_handoffs")
    if not raw_handoffs and isinstance(gap.get("source_text_handoff"), list):
        raw_handoffs = gap.get("source_text_handoff")
    handoffs = [
        dict(item)
        for item in (raw_handoffs or [])
        if isinstance(item, dict)
    ]
    field_values = {
        "input": values.get("intervention") or values.get("intervention_candidate") or "",
        "mediator": values.get("mediator") or values.get("mediator_candidate") or "",
        "outcome": values.get("outcome") or values.get("outcome_candidate") or "",
        "measurement": values.get("outcome") or values.get("outcome_candidate") or "",
    }
    slot_lineage: dict[str, list[dict[str, Any]]] = {
        "input": [],
        "mechanism": [],
        "outcome": [],
        "measurement": [],
    }
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for handoff in handoffs:
        role_field = _source_text_handoff_role_to_field(handoff.get("source_role"))
        candidate_fields = [role_field] if role_field else ["input", "mediator", "outcome"]
        accepted_any = False
        rejection_reasons: list[str] = []
        for field in candidate_fields:
            value = field_values.get(field, "")
            if not _concrete(value):
                rejection_reasons.append(f"{field}_value_not_concrete")
                continue
            support = _handoff_supports_field(handoff, field=field, value=value)
            if not support.get("passes"):
                rejection_reasons.append(str(support.get("reason") or "source_text_not_accepted"))
                continue
            slot = _source_text_handoff_slot(field)
            accepted_handoff = {
                **handoff,
                "acceptance_status": "ACCEPTED_FOR_PACKAGE_SLOT",
                "package_slot": slot,
                "accepted_causal_field": field,
                "supported_value": _normalize(value),
                "support_terms": list(support.get("support_terms") or [])[:8],
            }
            accepted.append(accepted_handoff)
            lineage_entry = _slot_source_lineage_entry(
                accepted_handoff,
                field=field,
                value=value,
                support=support,
            )
            lineage_key = (
                lineage_entry.get("source_unit_id"),
                lineage_entry.get("slot"),
                lineage_entry.get("value"),
            )
            existing = {
                (item.get("source_unit_id"), item.get("slot"), item.get("value"))
                for item in slot_lineage[slot]
            }
            if lineage_key not in existing:
                slot_lineage[slot].append(lineage_entry)
            accepted_any = True
        if not accepted_any:
            rejected.append({
                **handoff,
                "acceptance_status": "REJECTED_FOR_PACKAGE_SLOT",
                "package_slot": "",
                "rejection_reason": "; ".join(dict.fromkeys(rejection_reasons)) or "no_package_slot_supported",
            })
    # Measurement lineage may be the same bounded outcome source when the
    # package measurement slot is simply the observable outcome.  Keep an
    # explicit copy so MingLi can cite the readout path without inventing a
    # separate measurement paper.
    if not slot_lineage["measurement"] and slot_lineage["outcome"]:
        for item in slot_lineage["outcome"]:
            measurement_item = {**item, "slot": "measurement", "causal_field": "measurement"}
            slot_lineage["measurement"].append(measurement_item)
    covered = sorted(slot for slot, items in slot_lineage.items() if items)
    required = ["input", "mechanism", "outcome"]
    missing = [slot for slot in required if not slot_lineage.get(slot)]
    return {
        "schema_version": "source_text_handoff_evaluation_v1",
        "source_text_handoffs": handoffs,
        "accepted_source_text_handoffs": accepted,
        "rejected_source_text_handoffs": rejected,
        "slot_source_lineage": slot_lineage,
        "source_text_handoff_gate": {
            "schema_version": "source_text_handoff_gate_v1",
            "passes": not missing,
            "covered_slots": covered,
            "missing_slots": missing,
            "reason": (
                "Verified source text supports input, mechanism, and outcome slots."
                if not missing else
                "Verified source text is missing role support for: " + ", ".join(missing)
            ),
        },
    }


def _tanxi_source_bound_state_machine_gate(
    gap: dict[str, Any],
    handoff_evaluation: dict[str, Any],
) -> bool:
    contract = gap.get("evidence_graph_contract") if isinstance(gap.get("evidence_graph_contract"), dict) else {}
    state = str(gap.get("gap_state") or contract.get("gap_state") or "")
    source_verdict = gap.get("source_alignment_verdict") if isinstance(gap.get("source_alignment_verdict"), dict) else {}
    epistemic_verdict = gap.get("gap_epistemic_verdict") if isinstance(gap.get("gap_epistemic_verdict"), dict) else {}
    causal_verdict = gap.get("causal_readiness_verdict") if isinstance(gap.get("causal_readiness_verdict"), dict) else {}
    handoff_gate = handoff_evaluation.get("source_text_handoff_gate") if isinstance(handoff_evaluation.get("source_text_handoff_gate"), dict) else {}
    return bool(
        contract
        and state in {"VALIDATED_SCIENTIFIC_GAP", "TESTABLE_PARTIAL_GAP"}
        and (source_verdict.get("passes") is True or source_verdict.get("passes_for_direct") is True)
        and epistemic_verdict.get("passes") is True
        and causal_verdict.get("passes") is True
        and handoff_gate.get("passes") is True
    )


def build_gap_mechanism_evidence_bundle(project: dict[str, Any], gap: dict[str, Any]) -> dict[str, Any]:
    """Build the actual evidence unit consumed by TanXi and Socrates.

    A scientific gap is not a sentence copied out of a review.  It is a
    sub-hypothesis-scoped bundle that joins direct theory/model and direct
    experimental papers, while retaining a source span for every core causal
    field.  L1 records are purposely excluded from both direct-evidence slots.
    """
    # This historical bundle is exclusively for an explicitly selected v2
    # causal-identification candidate.  It may not reconstruct an A→M→Y
    # package for measurement, boundary, theory, or a legacy gap record.
    question_contract = gap.get("research_question_contract") if isinstance(gap.get("research_question_contract"), dict) else {}
    question_kind = str((question_contract.get("research_question") or {}).get("question_kind") or "")
    if question_contract.get("schema_version") == "research_question_contract_v2" and question_kind != "CAUSAL_IDENTIFICATION":
        return {
            "version": "gap_evidence_bundle_v2_rejected_noncausal",
            "status": "REJECTED_NONCAUSAL_RESEARCH_QUESTION",
            "gap_id": str(gap.get("gap_id") or ""),
            "research_question_contract_id": str(question_contract.get("contract_id") or ""),
            "reason": "Only a qualified CAUSAL_IDENTIFICATION research question may enter the historical mechanism bundle.",
        }
    records = [
        record for record in project.get("papergraph", [])
        if isinstance(record, dict) and record.get("active", True) is not False
    ]
    references = [str(item) for item in gap.get("supporting_references", []) if str(item).strip()]
    matched = [record for record in records if any(_reference_matches(reference, record) for reference in references)]
    branch_candidates = _unique([_paper_branch(record) for record in matched])
    declared_branch = _normalize(gap.get("sub_hypothesis_id"))
    branch = declared_branch or (branch_candidates[0] if len(branch_candidates) == 1 else "")
    subhypothesis = _subhypothesis_by_id(project, branch)
    contract = (
        (project.get("subhypothesis_alignment_contracts") or {}).get(branch)
        if isinstance(project.get("subhypothesis_alignment_contracts"), dict)
        else {}
    )
    if not contract and branch:
        gap["mechanism_evidence_bundle_contract_error"] = (
            "subhypothesis_alignment_contract_missing"
        )
    mechanism_seed_contract = (
        gap.get("mechanism_seed_contract")
        if isinstance(gap.get("mechanism_seed_contract"), dict)
        else {}
    )
    mechanism_seed = (
        mechanism_seed_contract.get("mechanism_seed")
        if isinstance(mechanism_seed_contract.get("mechanism_seed"), dict)
        else {}
    )
    seed_context_contract = (
        mechanism_seed_contract.get("seed_context_contract")
        if isinstance(mechanism_seed_contract.get("seed_context_contract"), dict)
        else {}
    )
    composite_seed_gate_passed = bool(
        mechanism_seed_contract.get("status") == "COMPLETE_COMPOSITE_MECHANISM_SEED"
        and all(
            seed_context_contract.get(key) is True
            for key in (
                "same_sub_hypothesis", "compatible_object",
                "compatible_system", "compatible_regime",
            )
        )
        and all(
            str((mechanism_seed.get(role) or {}).get("value") or "").strip()
            and (mechanism_seed.get(role) or {}).get("fragment_refs")
            for role in ("input", "mediator", "outcome")
        )
        and mechanism_seed_contract.get("original_source_role_mutated") is False
    )
    values = _bundle_causal_values(
        gap,
        subhypothesis,
        mechanism_seed if composite_seed_gate_passed else {},
    )
    source_text_handoff_evaluation = _evaluate_source_text_handoffs(gap, values)
    source_text_handoff_gate = (
        source_text_handoff_evaluation.get("source_text_handoff_gate")
        if isinstance(source_text_handoff_evaluation.get("source_text_handoff_gate"), dict)
        else {}
    )
    tanxi_source_bound_state_machine_gate_passed = _tanxi_source_bound_state_machine_gate(
        gap,
        source_text_handoff_evaluation,
    )
    direct_records: list[dict[str, Any]] = []
    theory_records: list[dict[str, Any]] = []
    experimental_records: list[dict[str, Any]] = []
    discovery_records: list[dict[str, Any]] = []
    validation_records: list[dict[str, Any]] = []
    for record in records:
        if branch and _paper_branch(record) != branch:
            continue
        alignment = record.get("alignment_assessment") if isinstance(record.get("alignment_assessment"), dict) else {}
        stored_genre = record.get("paper_genre") if isinstance(record.get("paper_genre"), dict) else {}
        genre = (
            stored_genre
            if stored_genre.get("version") == PAPER_EVIDENCE_GENRE_VERSION
            else classify_paper_evidence_genre(record, semantic_contract=contract)
        )
        # Backfill older PaperGraph records while TanXi is already performing
        # the evidence audit; the enclosing project save persists this once.
        record["paper_genre"] = genre
        if not bool(alignment.get("core_eligible")):
            continue
        if _is_foundational_bridge_record(record):
            continue
        if bool(genre.get("is_review")):
            continue
        # Keep the canonical PaperGraph record by reference: fragment audits
        # below are deliberately persisted on that record for later gaps.
        record["paper_genre"] = genre
        annotated = record
        direct_records.append(annotated)
        evidence_kind = str(
            record.get("evidence_kind") or alignment.get("evidence_kind") or ""
        ).lower()
        genre_name = str(genre.get("genre") or "").lower()
        inferred_theory_lane = not evidence_kind and genre_name in {
            "theoretical_framework", "computational_or_mechanistic_model",
        }
        inferred_experimental_lane = not evidence_kind and genre_name in {
            "controlled_experiment", "experimental_unspecified", "field_demonstration_project",
            "longitudinal_or_observational_study", "full_scale_commercial_operation",
        }
        # A mixed/background classification may discuss both theory and data,
        # but it may not silently fill both primary slots.  The record must be
        # admitted through the matching direct retrieval lane.
        if genre.get("direct_theoretical_evidence") and (
            evidence_kind == "theoretical_framework" or inferred_theory_lane
        ):
            theory_records.append(annotated)
        if genre.get("direct_experimental_evidence") and (
            evidence_kind == "experimental_evidence" or inferred_experimental_lane
        ):
            experimental_records.append(annotated)
        causal_role = str(
            alignment.get("causal_role")
            or classify_causal_role(record, paper_genre=genre).get("causal_role")
            or ""
        )
        if causal_role in {"association", "mechanism_discovery", "causal_identification", "causal_validation"}:
            discovery_records.append(annotated)
        if causal_role in {"causal_identification", "causal_validation"}:
            validation_records.append(annotated)

    # A paper-level core-eligible label is only a retrieval admission result.
    # The primary bundle below may use a record only through bounded local
    # source units that jointly identify object, causal process, and outcome.
    fragment_alignments: list[dict[str, Any]] = []
    anchor_fragment_alignments: list[dict[str, Any]] = []
    citation_by_paper_id: dict[str, str] = {}
    fragment_settings = project.get("evidence_fragment_alignment") if isinstance(project.get("evidence_fragment_alignment"), dict) else {}
    use_llm_fragment_alignment = bool(
        fragment_settings.get("use_llm")
        or project.get("use_llm_fragment_alignment")
    )
    for record in direct_records:
        paper_id = str(record.get("paper_id") or "")
        if paper_id:
            citation_by_paper_id[paper_id] = str(record.get("citation") or record.get("title") or "")
        record_fragments = assess_evidence_fragment_alignment(
            record,
            contract,
            use_llm=use_llm_fragment_alignment,
        )
        # Persist the immutable source-unit assessment on the PaperGraph
        # record as well as in this gap-local bundle.  A later gap can reuse
        # the audit without promoting a full-paper keyword match to evidence.
        persist_evidence_fragment_alignments(record, record_fragments)
        fragment_alignments.extend(record_fragments)
        # The original TanXi gap signal must be anchored in one of its stated
        # supporting references.  Other same-branch direct papers may extend
        # theory/experiment lanes, but they cannot rescue an off-topic source
        # such as a detector limitation that created the gap in the first
        # place.
        if not references or any(_reference_matches(reference, record) for reference in references):
            anchor_fragment_alignments.extend(record_fragments)
    fragment_source_span_gate = primary_source_span_gate(anchor_fragment_alignments)
    source_span_gate = dict(fragment_source_span_gate)
    if (
        not bool(source_span_gate.get("passes"))
        and source_text_handoff_gate.get("passes") is True
    ):
        source_span_gate = {
            **source_span_gate,
            "passes": True,
            "status": "SOURCE_TEXT_HANDOFF_BOUND",
            "source": "source_text_handoff_gate",
            "covered_fields": list(source_text_handoff_gate.get("covered_slots") or []),
            "missing_fields": list(source_text_handoff_gate.get("missing_slots") or []),
            "reason": "Verified source_text_handoffs carry bounded source units for the causal slots.",
        }

    # Preserve the scientific identity of the *original* TanXi candidate.
    # Evidence discovered later in the same sub-hypothesis may strengthen a
    # valid causal candidate, but it must never turn a rationale sentence, an
    # unresolved input/readout, or an out-of-scope source object into a new
    # primary gap.  Doing so would silently replace the question TanXi found.
    input_role_assessment = (
        gap.get("input_role_assessment")
        if isinstance(gap.get("input_role_assessment"), dict)
        else {}
    )
    output_role_assessment = (
        gap.get("output_role_assessment")
        if isinstance(gap.get("output_role_assessment"), dict)
        else {}
    )
    unresolved_role_categories = {"unresolved", "generic_placeholder"}
    original_object_out_of_scope = bool(
        references
        and not tanxi_source_bound_state_machine_gate_passed
        and (
            not anchor_fragment_alignments
            or not any(
                isinstance(item, dict)
                and bool((item.get("object_alignment") or {}).get("passes"))
                for item in anchor_fragment_alignments
            )
        )
    )
    original_semantic_failures: list[str] = []
    original_source_role_audit = (
        gap.get("original_source_role_audit")
        if isinstance(gap.get("original_source_role_audit"), dict)
        else {}
    )
    source_clue_role = str(
        gap.get("source_clue_role")
        or original_source_role_audit.get("source_clue_role")
        or ""
    ).strip().lower()
    if (
        source_clue_role != "direct"
        and not composite_seed_gate_passed
        and not tanxi_source_bound_state_machine_gate_passed
    ):
        original_semantic_failures.append({
            "partial": "PARTIAL_SOURCE_ROLE",
            "rationale_only": "RATIONALE_ONLY_SOURCE",
            "out_of_scope": "OUT_OF_SCOPE_SOURCE_OBJECT",
        }.get(source_clue_role, "UNVERIFIABLE_SOURCE_ROLE"))
    scientific_verdicts = gap.get("scientific_verdicts") if isinstance(gap.get("scientific_verdicts"), dict) else {}
    detailed_source_verdict = gap.get("source_alignment_verdict") if isinstance(gap.get("source_alignment_verdict"), dict) else {}
    detailed_epistemic_verdict = gap.get("gap_epistemic_verdict") if isinstance(gap.get("gap_epistemic_verdict"), dict) else {}
    detailed_causal_verdict = gap.get("causal_readiness_verdict") if isinstance(gap.get("causal_readiness_verdict"), dict) else {}
    accepted_epistemic_verdicts = {
        "EXPLICIT_AUTHOR_STATED_GAP", "COMPOSITE_CONTRADICTION_GAP",
        "COMPOSITE_CAUSAL_MEDIATION_GAP", "THEORY_OBSERVATION_MISMATCH",
        "BOUNDARY_CONDITION_GAP", "COMPOSITE_TABI_GAP",
    }
    original_audit_hash_payload = {
        key: value for key, value in original_source_role_audit.items()
        if key != "audit_hash"
    }
    original_audit_expected_hash = (
        sha256(json.dumps(
            original_audit_hash_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")).hexdigest()
        if original_source_role_audit else ""
    )
    original_source_role_audit_intact = bool(
        original_source_role_audit.get("immutable") is True
        and str(original_source_role_audit.get("audit_hash") or "") == original_audit_expected_hash
    )
    three_verdict_details_present = bool(
        detailed_source_verdict and detailed_epistemic_verdict and detailed_causal_verdict
    )
    three_verdict_values_valid = bool(
        str(detailed_source_verdict.get("verdict") or "") == "DIRECTLY_ALIGNED"
        and detailed_source_verdict.get("passes_for_direct") is True
        and str(detailed_epistemic_verdict.get("verdict") or "") in accepted_epistemic_verdicts
        and detailed_epistemic_verdict.get("passes") is True
        and str(detailed_causal_verdict.get("verdict") or "") == "CAUSAL_CHAIN_VALID"
        and detailed_causal_verdict.get("passes") is True
        and scientific_verdicts.get("all_primary_prerequisites_pass") is True
        and str(scientific_verdicts.get("source_alignment_verdict") or "")
        == str(detailed_source_verdict.get("verdict") or "")
        and str(scientific_verdicts.get("gap_epistemic_verdict") or "")
        == str(detailed_epistemic_verdict.get("verdict") or "")
        and str(scientific_verdicts.get("causal_readiness_verdict") or "")
        == str(detailed_causal_verdict.get("verdict") or "")
    )
    scientific_identity_gate_passed = bool(
        three_verdict_values_valid
        or composite_seed_gate_passed
        or tanxi_source_bound_state_machine_gate_passed
    )
    if not three_verdict_details_present and not tanxi_source_bound_state_machine_gate_passed:
        original_semantic_failures.append("THREE_VERDICT_PRIMARY_GATE_MISSING")
    elif not scientific_identity_gate_passed:
        original_semantic_failures.append("THREE_VERDICT_PRIMARY_GATE_FAILED")
    if not original_source_role_audit_intact and not tanxi_source_bound_state_machine_gate_passed:
        original_semantic_failures.append("ORIGINAL_SOURCE_ROLE_AUDIT_MISSING_OR_CORRUPT")
    elif (
        original_source_role_audit.get("allowed_transition") != "PRIMARY_MECHANISM_CANDIDATE"
        and not composite_seed_gate_passed
        and not tanxi_source_bound_state_machine_gate_passed
    ):
        original_semantic_failures.append("ORIGINAL_SOURCE_ROLE_TRANSITION_NOT_PRIMARY")
    elif (
        str(original_source_role_audit.get("source_clue_role") or "") != source_clue_role
        and not tanxi_source_bound_state_machine_gate_passed
    ):
        original_semantic_failures.append("ORIGINAL_SOURCE_ROLE_HANDOFF_CONFLICT")
    if (
        not input_role_assessment
        and not composite_seed_gate_passed
        and not tanxi_source_bound_state_machine_gate_passed
    ):
        original_semantic_failures.append("INPUT_ROLE_ASSESSMENT_MISSING")
    elif (
        str(input_role_assessment.get("category") or "").strip().lower() in unresolved_role_categories
        or input_role_assessment.get("admissible_as_input") is False
    ) and not composite_seed_gate_passed and not tanxi_source_bound_state_machine_gate_passed:
        original_semantic_failures.append("UNRESOLVED_INPUT_ROLE")
    if (
        not output_role_assessment
        and not composite_seed_gate_passed
        and not tanxi_source_bound_state_machine_gate_passed
    ):
        original_semantic_failures.append("OUTPUT_ROLE_ASSESSMENT_MISSING")
    elif (
        str(output_role_assessment.get("category") or "").strip().lower() in unresolved_role_categories
        or output_role_assessment.get("admissible_as_outcome") is False
    ) and not composite_seed_gate_passed and not tanxi_source_bound_state_machine_gate_passed:
        original_semantic_failures.append("UNRESOLVED_OUTPUT_ROLE")
    if original_object_out_of_scope:
        original_semantic_failures.append("OUT_OF_SCOPE_SOURCE_OBJECT")
    original_semantic_failures = list(dict.fromkeys(original_semantic_failures))
    original_semantics_irreversibly_invalid = bool(original_semantic_failures)
    # Do not let unrelated same-SH records populate the causal fields of a
    # candidate whose original identity already failed.  Anchor fragments are
    # retained only to produce an auditable rejection record.
    causal_fragment_pool = (
        anchor_fragment_alignments
        if original_semantics_irreversibly_invalid
        else fragment_alignments
    )

    # A candidate causal field is not a primary-bundle field until a bounded,
    # direct source unit establishes its requested role.  In particular, do
    # not turn a bare noun into ``controlled variation of <noun>`` simply
    # because the model can imagine varying it.
    field_normalizations: dict[str, dict[str, Any]] = {}
    for field, expected_role, source_key in (
        ("input", "input", "intervention"),
        ("mediator", "specific_causal_mediator", "mediator"),
        ("outcome", "observable_or_calculable_outcome", "outcome"),
    ):
        declared_value = str(values.get(source_key) or "")
        raw_candidate = str(
            declared_value if _concrete(declared_value)
            else values.get(f"{source_key}_candidate")
            or ""
        )
        normalized = normalize_causal_field_from_evidence(
            raw_candidate,
            # Once the original gap source has passed the triadic identity
            # gate, direct same-subhypothesis papers may supply the specific
            # operation/readout needed to complete its causal fields.  They
            # cannot rescue an off-topic original gap because the source gate
            # remains mandatory below.
            causal_fragment_pool,
            expected_role=expected_role,
        )
        field_normalizations[field] = normalized
        normalized_value = str(normalized.get("normalized_value") or "").strip()
        if normalized_value:
            values[source_key] = normalized_value
        else:
            accepted_field_handoffs = [
                item for item in source_text_handoff_evaluation.get("accepted_source_text_handoffs", [])
                if isinstance(item, dict)
                and str(item.get("accepted_causal_field") or "") == field
            ]
            if accepted_field_handoffs and _concrete(raw_candidate):
                source_unit_ids = list(dict.fromkeys(
                    str(item.get("source_unit_id") or "")
                    for item in accepted_field_handoffs
                    if str(item.get("source_unit_id") or "")
                ))
                source_text_handoff_ids = list(dict.fromkeys(
                    str(item.get("source_text_handoff_id") or "")
                    for item in accepted_field_handoffs
                    if str(item.get("source_text_handoff_id") or "")
                ))
                field_normalizations[field] = {
                    **normalized,
                    "candidate": raw_candidate,
                    "normalized_value": raw_candidate,
                    "source_status": "DIRECT_SOURCE_SUPPORTED",
                    "source_unit_ids": source_unit_ids,
                    "source_text_handoff_ids": source_text_handoff_ids,
                    "reason": "Accepted source_text_handoffs support the declared TanXi causal field.",
                }
                values[source_key] = raw_candidate
                continue
            # Preserve the candidate for secondary reporting, but remove it
            # from the causal chain that determines primary eligibility.
            values[f"{source_key}_candidate"] = raw_candidate
            values[source_key] = ""
    values["intervention_source_unit_ids"] = list(field_normalizations["input"].get("source_unit_ids") or [])

    # Infer the epistemic design after source-bound evidence is available.
    # A stray word such as "detector" in an unrelated paper cannot select an
    # instrumentation mode before this gate has accepted the paper's object.
    try:
        from ._research_mode import (
            COMPUTATIONAL_INTERVENTION,
            THEORETICAL_OR_FORMAL,
            UNRESOLVED_RESEARCH_DESIGN,
            resolve_research_mode,
        )
    except ImportError:
        from _research_mode import (
            COMPUTATIONAL_INTERVENTION,
            THEORETICAL_OR_FORMAL,
            UNRESOLVED_RESEARCH_DESIGN,
            resolve_research_mode,
        )
    mode_seed = {
        "input": values["intervention"],
        "proposed_mediator": values["mediator"],
        "output": values["outcome"],
        "comparison": values["comparison"],
        "falsification": values["falsification"],
        "context": subhypothesis.get("focus") or "",
        "research_design_evidence": {
            "status": "SOURCE_BOUND" if (
                source_span_gate.get("passes")
                or (
                    isinstance(mechanism_seed_contract.get("research_design_evidence"), dict)
                    and mechanism_seed_contract.get("research_design_evidence", {}).get("status") == "SOURCE_BOUND"
                )
            ) else "UNSUPPORTED",
            # The original source gate fixes the scientific object.  Direct
            # same-subhypothesis evidence can then establish its actual
            # design (for example, a model sensitivity paper plus a laboratory
            # constraint paper), without allowing a foreign object to rescue
            # the gap.
            "fragment_alignments": list(causal_fragment_pool) + [
                dict(item)
                for item in (
                    (mechanism_seed_contract.get("research_design_evidence") or {}).get("fragment_alignments")
                    if isinstance(mechanism_seed_contract.get("research_design_evidence"), dict)
                    else []
                )
                if isinstance(item, dict)
            ],
            "primary_source_span_gate": source_span_gate,
        },
    }
    mode_resolution = resolve_research_mode(
        project,
        gap,
        mode_seed,
        {"sub_hypothesis_id": branch, **values, "research_design_evidence": mode_seed["research_design_evidence"]},
    )
    research_mode = str(mode_resolution.get("mode") or "CONTROLLED_INTERVENTION")
    try:
        from ._input_ontology import classify_input_candidate
        from ._outcome_ontology import classify_outcome_candidate
    except ImportError:
        from _input_ontology import classify_input_candidate
        from _outcome_ontology import classify_outcome_candidate
    mode_input_assessment = classify_input_candidate(
        values["intervention"],
        research_mode=research_mode,
        source_unit_ids=list(field_normalizations["input"].get("source_unit_ids") or []),
        require_source_bound=True,
    )
    target_outcome_terms = [
        *(str(item) for item in (subhypothesis.get("dependent_variables") or []) if str(item).strip()),
        str((subhypothesis.get("causal_chain") or [""])[-1]) if subhypothesis.get("causal_chain") else "",
        *(str(item) for item in (contract.get("outcome_terms") or []) if str(item).strip()),
    ]
    mode_outcome_assessment = classify_outcome_candidate(
        values["outcome"],
        research_mode=research_mode,
        target_outcome_terms=target_outcome_terms,
        source_unit_ids=list(field_normalizations["outcome"].get("source_unit_ids") or []),
        require_target_alignment=True,
        require_source_bound=True,
    )
    field_normalizations["input"]["role_assessment"] = mode_input_assessment
    field_normalizations["outcome"]["role_assessment"] = mode_outcome_assessment
    research_design_evidence = {
        **mode_seed["research_design_evidence"],
        "recommended_mode": research_mode,
        "mode_candidates": list(mode_resolution.get("mode_candidates") or []),
        "supporting_fragment_ids": list(mode_resolution.get("supporting_fragment_ids") or []),
        "source": str(mode_resolution.get("source") or ""),
        "research_design_inference": (
            mode_resolution.get("research_design_inference")
            if isinstance(mode_resolution.get("research_design_inference"), dict)
            else {}
        ),
    }

    source_spans: list[dict[str, Any]] = []
    fields_with_spans: set[str] = set()
    for field, value in (("input", values["intervention"]), ("mediator", values["mediator"]), ("outcome", values["outcome"])):
        if not _concrete(value):
            continue
        spans = source_bound_field_support(causal_fragment_pool, field=field, value=value)
        for span in spans:
            span["citation"] = citation_by_paper_id.get(str(span.get("paper_id") or ""), "")
        source_spans.extend(spans)
        if spans:
            fields_with_spans.add(field)
    handoff_source_spans: list[dict[str, Any]] = []
    for handoff in source_text_handoff_evaluation.get("accepted_source_text_handoffs", []):
        if not isinstance(handoff, dict):
            continue
        field = str(handoff.get("accepted_causal_field") or "")
        if field not in {"input", "mediator", "outcome"}:
            continue
        span = {
            "source": "source_text_handoff",
            "field": field,
            "paper_id": str(handoff.get("paper_id") or ""),
            "source_unit_id": str(handoff.get("source_unit_id") or ""),
            "source_text_handoff_id": str(handoff.get("source_text_handoff_id") or ""),
            "excerpt_hash": str(handoff.get("excerpt_hash") or ""),
            "source_field": str(handoff.get("source_field") or ""),
            "source_location": dict(handoff.get("source_location") or {}) if isinstance(handoff.get("source_location"), dict) else {},
            "excerpt": str(handoff.get("bounded_excerpt") or "")[:800],
            "citation": citation_by_paper_id.get(str(handoff.get("paper_id") or ""), ""),
            "support_terms": list(handoff.get("support_terms") or [])[:8],
            "source_status": "DIRECT_SOURCE_SUPPORTED",
        }
        handoff_source_spans.append(span)
        source_spans.append(span)
        fields_with_spans.add(field)
    source_text_direct_ids = list(dict.fromkeys(
        str(item.get("paper_id") or "")
        for item in source_text_handoff_evaluation.get("accepted_source_text_handoffs", [])
        if isinstance(item, dict) and str(item.get("paper_id") or "")
    ))
    direct_ids = list(dict.fromkeys(
        [str(record.get("paper_id") or "") for record in direct_records if str(record.get("paper_id") or "")]
        + source_text_direct_ids
    ))
    theory_ids = [str(record.get("paper_id") or "") for record in theory_records if str(record.get("paper_id") or "")]
    experimental_ids = [str(record.get("paper_id") or "") for record in experimental_records if str(record.get("paper_id") or "")]
    discovery_ids = [str(record.get("paper_id") or "") for record in discovery_records if str(record.get("paper_id") or "")]
    validation_ids = [str(record.get("paper_id") or "") for record in validation_records if str(record.get("paper_id") or "")]
    required_path_roles = {
        str(path.get("role") or path.get("id") or "").strip().lower()
        for path in (contract.get("evidence_paths") or [])
        if isinstance(path, dict)
    }
    complementary_discovery_validation = {
        "mechanism_discovery", "causal_validation"
    }.issubset(required_path_roles)
    computational_ids = [
        str(record.get("paper_id") or "")
        for record in direct_records
        if str((record.get("paper_genre") or {}).get("genre") or "") == "computational_or_mechanistic_model"
        or any(marker in _candidate_text(record).lower() for marker in (
            "simulation", "numerical experiment", "feature ablation", "parameter sweep", "in silico",
        ))
    ]
    missing: list[str] = []
    missing.extend(f"original_semantic_failure:{reason}" for reason in original_semantic_failures)
    if not branch:
        missing.append("sub_hypothesis_traceability")
    if not direct_ids:
        missing.append("aligned_direct_evidence")
        # Retain the former diagnostic name for downstream reports produced
        # before evidence bundles existed; it now means no eligible direct
        # records were available to assemble the bundle.
        missing.append("aligned_supporting_evidence")
    if complementary_discovery_validation:
        if not discovery_ids:
            missing.append("mechanism_discovery")
        if not validation_ids:
            missing.append("causal_validation_or_identification")
    else:
        if not theory_ids:
            missing.append("theoretical_framework")
        if research_mode == THEORETICAL_OR_FORMAL:
            pass
        elif research_mode == COMPUTATIONAL_INTERVENTION:
            if not (computational_ids or experimental_ids):
                missing.append("computational_evidence")
        elif not experimental_ids:
            missing.append("experimental_evidence")
    if research_mode == UNRESOLVED_RESEARCH_DESIGN:
        missing.append("source_bound_research_design")
    if not mode_input_assessment.get("admissible_as_input"):
        missing.append("valid_mode_specific_input")
        # Compatibility label retained for older reports; it now means a
        # legal input for the resolved research mode, not necessarily an
        # experimentally manipulable intervention.
        missing.append("concrete_intervention")
    if not _concrete(values["mediator"]):
        missing.append("supported_mediator_or_competing_mechanism")
    if not mode_outcome_assessment.get("admissible_as_outcome"):
        missing.append("observable_outcome")
    if not source_span_gate.get("passes"):
        missing.append("source_bound_object_process_outcome_evidence")
    for field in ("input", "mediator", "outcome"):
        if field not in fields_with_spans:
            missing.append(f"{field}_source_span")
    concrete_chain = bool(
        mode_input_assessment.get("admissible_as_input")
        and _concrete(values["mediator"])
        and mode_outcome_assessment.get("admissible_as_outcome")
    )
    source_role_invalid = bool(
        original_semantics_irreversibly_invalid
        or (
            not source_span_gate.get("passes")
            and bool(direct_records)
        )
    )
    if original_semantics_irreversibly_invalid:
        status = "SECONDARY_INSUFFICIENT_MECHANISM_MATERIAL"
    elif not missing:
        status = "READY_FOR_PRIMARY_QUALIFICATION"
    elif concrete_chain and not source_role_invalid:
        status = "CANDIDATE_FOR_SOCRATES_TARGETED_RETRIEVAL"
    else:
        status = "SECONDARY_INSUFFICIENT_MECHANISM_MATERIAL"
    if original_semantic_failures:
        state_reason_code = original_semantic_failures[0]
    elif status == "READY_FOR_PRIMARY_QUALIFICATION":
        state_reason_code = "PRIMARY_SOURCE_VALID"
    elif status == "CANDIDATE_FOR_SOCRATES_TARGETED_RETRIEVAL":
        state_reason_code = "CONCRETE_CHAIN_BUT_EVIDENCE_LANE_MISSING"
    elif not source_span_gate.get("passes"):
        state_reason_code = "OUT_OF_SCOPE_SOURCE"
    elif field_normalizations["input"].get("source_status") != "DIRECT_SOURCE_SUPPORTED":
        state_reason_code = "UNRESOLVED_INPUT_ROLE"
    elif field_normalizations["outcome"].get("source_status") != "DIRECT_SOURCE_SUPPORTED":
        state_reason_code = "UNRESOLVED_OUTPUT_ROLE"
    elif research_mode == UNRESOLVED_RESEARCH_DESIGN:
        state_reason_code = "UNRESOLVED_RESEARCH_DESIGN"
    else:
        state_reason_code = "SOURCE_ROLE_INVALID"
    def source_unit_ids_for_field(field: str) -> list[str]:
        return list(dict.fromkeys(
            [str(item) for item in (field_normalizations[field].get("source_unit_ids") or []) if str(item)]
            + [
                str(item.get("source_unit_id") or "")
                for item in source_text_handoff_evaluation.get("accepted_source_text_handoffs", [])
                if isinstance(item, dict)
                and str(item.get("accepted_causal_field") or "") == field
                and str(item.get("source_unit_id") or "")
            ]
        ))

    def source_handoff_refs_for_field(field: str) -> list[dict[str, Any]]:
        refs: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item in source_text_handoff_evaluation.get("accepted_source_text_handoffs", []):
            if not isinstance(item, dict) or str(item.get("accepted_causal_field") or "") != field:
                continue
            ref = _compact_source_text_handoff_ref(item)
            key = str(ref.get("source_text_handoff_id") or ref.get("source_unit_id") or "")
            if key and key not in seen:
                seen.add(key)
                refs.append(ref)
        return refs

    def source_status_for_field(field: str) -> str:
        if source_unit_ids_for_field(field):
            return "DIRECT_SOURCE_SUPPORTED"
        return str(field_normalizations[field].get("source_status") or "")

    return {
        "version": "gap_evidence_bundle_v6",
        "gap_id": str(gap.get("gap_id") or ""),
        "sub_hypothesis_id": branch,
        "status": status,
        "state_reason_code": state_reason_code,
        "state_transition": (
            "READY_FOR_PRIMARY_QUALIFICATION"
            if status == "READY_FOR_PRIMARY_QUALIFICATION"
            else "CANDIDATE_FOR_SOCRATES_TARGETED_RETRIEVAL"
            if status == "CANDIDATE_FOR_SOCRATES_TARGETED_RETRIEVAL"
            else "SECONDARY_RESEARCH_OPPORTUNITY"
        ),
        "socrates_targeted_retrieval_allowed": status in {
            "READY_FOR_PRIMARY_QUALIFICATION", "CANDIDATE_FOR_SOCRATES_TARGETED_RETRIEVAL",
        } and not original_semantics_irreversibly_invalid,
        "original_semantic_audit": {
            "irreversibly_invalid": original_semantics_irreversibly_invalid,
            "failure_reasons": original_semantic_failures,
                "source_clue_role": source_clue_role,
            "input_role_category": str(input_role_assessment.get("category") or ""),
            "output_role_category": str(output_role_assessment.get("category") or ""),
            "source_object_out_of_scope": original_object_out_of_scope,
            "same_subhypothesis_upgrade_allowed": not original_semantics_irreversibly_invalid,
            "source_alignment_verdict": str(detailed_source_verdict.get("verdict") or "UNVERIFIABLE_SOURCE"),
            "gap_epistemic_verdict": str(detailed_epistemic_verdict.get("verdict") or "EVIDENCE_EXTRACTION_SHORTAGE"),
            "causal_readiness_verdict": str(detailed_causal_verdict.get("verdict") or "SOURCE_ROLE_CONFLICT"),
            "three_verdict_details_present": three_verdict_details_present,
            "three_verdict_primary_gate_passed": three_verdict_values_valid,
            "composite_mechanism_seed_gate_passed": composite_seed_gate_passed,
            "tanxi_source_bound_state_machine_gate_passed": tanxi_source_bound_state_machine_gate_passed,
            "scientific_identity_gate_passed": scientific_identity_gate_passed,
            "original_source_role_audit_intact": original_source_role_audit_intact,
            "original_source_role_audit_hash": str(original_source_role_audit.get("audit_hash") or ""),
            "original_source_role_allowed_transition": str(original_source_role_audit.get("allowed_transition") or ""),
        },
        "mechanism_seed_contract": mechanism_seed_contract,
        "intervention": values["intervention"],
        "normalized_input": str(mode_input_assessment.get("normalized_value") or values["intervention"]),
        "comparison": values["comparison"],
        "mediator": values["mediator"],
        "outcome": values["outcome"],
        "falsification": values["falsification"],
        "causal_chain": {
            "input": {
                "value": values["intervention"],
                "candidate": field_normalizations["input"].get("candidate") or values.get("intervention_candidate") or "",
                "role": "PARAMETERIZED_COMPUTATIONAL_INTERVENTION" if research_mode == COMPUTATIONAL_INTERVENTION else "SOURCE_BOUND_INTERVENTION",
                "source_status": field_normalizations["input"].get("source_status"),
                "fragment_ids": list(field_normalizations["input"].get("source_unit_ids") or []),
                "reason": field_normalizations["input"].get("reason"),
                "role_assessment": mode_input_assessment,
            },
            "mediator": {
                "value": values["mediator"],
                "candidate": field_normalizations["mediator"].get("candidate") or values.get("mediator_candidate") or "",
                "role": "SPECIFIC_CAUSAL_MEDIATOR",
                "source_status": field_normalizations["mediator"].get("source_status"),
                "fragment_ids": list(field_normalizations["mediator"].get("source_unit_ids") or []),
                "reason": field_normalizations["mediator"].get("reason"),
            },
            "outcome": {
                "value": values["outcome"],
                "candidate": field_normalizations["outcome"].get("candidate") or values.get("outcome_candidate") or "",
                "role": "CALCULABLE_OUTCOME" if research_mode in {COMPUTATIONAL_INTERVENTION, THEORETICAL_OR_FORMAL} else "OBSERVABLE_OUTCOME",
                "source_status": field_normalizations["outcome"].get("source_status"),
                "fragment_ids": list(field_normalizations["outcome"].get("source_unit_ids") or []),
                "reason": field_normalizations["outcome"].get("reason"),
                "role_assessment": mode_outcome_assessment,
            },
        },
        "research_mode": research_mode,
        "research_mode_resolution": mode_resolution,
        "research_design_evidence": research_design_evidence,
        "theory_evidence_ids": theory_ids,
        "experimental_evidence_ids": experimental_ids,
        "mechanism_discovery_evidence_ids": discovery_ids,
        "causal_validation_evidence_ids": validation_ids,
        "complementary_discovery_validation_required": complementary_discovery_validation,
        "computational_evidence_ids": computational_ids,
        "direct_evidence_ids": direct_ids,
        "direct_evidence_lanes": {
            "theoretical_framework": theory_ids,
            "computational_evidence": computational_ids,
            "experimental_or_observational_evidence": experimental_ids,
            "mechanism_discovery": discovery_ids,
            "causal_validation_or_identification": validation_ids,
        },
        "mechanism_source_spans": source_spans,
        "handoff_source_spans": handoff_source_spans,
        "source_span_fields": sorted(fields_with_spans),
        "evidence_fragment_alignment_version": EVIDENCE_FRAGMENT_ALIGNMENT_VERSION,
        "evidence_fragment_alignments": fragment_alignments,
        "gap_anchor_fragment_alignments": anchor_fragment_alignments,
        "primary_source_span_gate": source_span_gate,
        "fragment_primary_source_span_gate": fragment_source_span_gate,
        "source_text_handoff_gate": source_text_handoff_gate,
        "source_text_handoffs": list(source_text_handoff_evaluation.get("source_text_handoffs") or []),
        "accepted_source_text_handoffs": list(source_text_handoff_evaluation.get("accepted_source_text_handoffs") or []),
        "rejected_source_text_handoffs": list(source_text_handoff_evaluation.get("rejected_source_text_handoffs") or []),
        "slot_source_lineage": dict(source_text_handoff_evaluation.get("slot_source_lineage") or {}),
        "causal_field_provenance": {
            "input": {
                "value": values["intervention"],
                "candidate": field_normalizations["input"].get("candidate") or values.get("intervention_candidate") or "",
                "source_status": source_status_for_field("input"),
                "source_unit_ids": source_unit_ids_for_field("input"),
                "source_text_handoff_refs": source_handoff_refs_for_field("input"),
                "reason": field_normalizations["input"].get("reason"),
            },
            "mediator": {
                "value": values["mediator"],
                "candidate": field_normalizations["mediator"].get("candidate") or values.get("mediator_candidate") or "",
                "source_status": source_status_for_field("mediator"),
                "source_unit_ids": source_unit_ids_for_field("mediator"),
                "source_text_handoff_refs": source_handoff_refs_for_field("mediator"),
                "reason": field_normalizations["mediator"].get("reason"),
            },
            "outcome": {
                "value": values["outcome"],
                "candidate": field_normalizations["outcome"].get("candidate") or values.get("outcome_candidate") or "",
                "source_status": source_status_for_field("outcome"),
                "source_unit_ids": source_unit_ids_for_field("outcome"),
                "source_text_handoff_refs": source_handoff_refs_for_field("outcome"),
                "reason": field_normalizations["outcome"].get("reason"),
            },
        },
        "matched_gap_signal_record_ids": [str(record.get("paper_id") or "") for record in matched if str(record.get("paper_id") or "")],
        "excluded_background_record_ids": [
            str(record.get("paper_id") or "")
            for record in records
            if _paper_branch(record) == branch and _is_foundational_bridge_record(record)
        ],
        "missing_requirements": list(dict.fromkeys(missing)),
        "direct_evidence_policy": {
            "same_subhypothesis_required": True,
            "review_market_future_work_background_only": True,
            "foundational_l1_never_direct_evidence": True,
            "research_mode": research_mode,
            "source_bound_triadic_evidence_required": True,
            "required_evidence_lanes": (
                ["mechanism_discovery", "causal_validation_or_identification"]
                if complementary_discovery_validation
                else ["theoretical_framework"]
                if research_mode == THEORETICAL_OR_FORMAL
                else ["theoretical_framework", "computational_evidence"]
                if research_mode == COMPUTATIONAL_INTERVENTION
                else ["theoretical_framework", "experimental_evidence"]
            ),
        },
    }


def _primary_gap_anchor_terms(values: list[Any], *, limit: int = 48) -> list[str]:
    """Return project-local entity anchors while retaining domain terms.

    No global list may declare ``water``, ``signal``, ``neural``, ``digital``,
    ``algorithm``, or ``simulation`` non-scientific.  The caller combines the
    result with an independent branch/relation anchor, which is the actual
    protection against cross-domain AI or methodology collisions.
    """
    merged = " ".join(str(value or "") for value in values)
    return [
        term for term in _ranked_terms(merged, limit=limit)
        if term not in _PROJECT_ANCHOR_GLUE_TERMS
    ]


def _primary_gap_anchor_phrases(values: list[Any], *, limit: int = 32) -> list[str]:
    """Keep project-local entity/relation phrases for collision-resistant matching."""
    merged = " ".join(str(value or "") for value in values)
    return [
        phrase for phrase in _phrases(merged, limit=limit)
        if any(token not in _PROJECT_ANCHOR_GLUE_TERMS for token in _ranked_terms(phrase, limit=4))
    ]


def assess_primary_gap_project_alignment(
    project: dict[str, Any],
    gap: dict[str, Any],
    bundle: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Audit that a primary gap remains inside one scientific object.

    This is stricter than a paper-level relevance label.  A primary causal gap
    must join records from one declared sub-hypothesis, whose source text
    contains (1) at least one project identity anchor and (2) at least two
    non-generic anchors overall.  Consequently, a generic AI/multi-omics
    paper cannot become a memory, climate, materials, or chemistry mechanism
    anchor merely because words such as *model*, *activity*, or *prediction*
    happen to overlap.
    """
    materialized_bundle = bundle if isinstance(bundle, dict) else build_gap_mechanism_evidence_bundle(project, gap)
    branch = str(materialized_bundle.get("sub_hypothesis_id") or gap.get("sub_hypothesis_id") or "").strip()
    contracts = project.get("subhypothesis_alignment_contracts") if isinstance(project.get("subhypothesis_alignment_contracts"), dict) else {}
    contract = contracts.get(branch) if isinstance(contracts.get(branch), dict) else {}
    card = build_project_alignment_card(project)
    project_values = [
        project.get("title"), project.get("declared_domain"), project.get("domain"),
        project.get("objective"), project.get("strategic_need"),
        card.get("project_context_anchor_terms"),
    ]
    subhypothesis_values = [
        contract.get("input_terms"), contract.get("mechanism_terms"),
        contract.get("outcome_terms"), contract.get("focus_terms"),
    ]
    project_terms = _primary_gap_anchor_terms(project_values)
    project_phrases = _primary_gap_anchor_phrases(project_values)
    subhypothesis_terms = _primary_gap_anchor_terms(subhypothesis_values)
    subhypothesis_phrases = _primary_gap_anchor_phrases(subhypothesis_values)
    direct_ids = [str(item) for item in materialized_bundle.get("direct_evidence_ids", []) if str(item).strip()]
    source_span_gate = (
        materialized_bundle.get("primary_source_span_gate")
        if isinstance(materialized_bundle.get("primary_source_span_gate"), dict)
        else {}
    )
    records_by_id = {
        str(record.get("paper_id") or ""): record
        for record in project.get("papergraph", [])
        if isinstance(record, dict) and str(record.get("paper_id") or "")
    }
    direct_records = [records_by_id[item] for item in direct_ids if item in records_by_id]
    accepted_handoffs = [
        item for item in materialized_bundle.get("accepted_source_text_handoffs", [])
        if isinstance(item, dict)
    ]
    source_text_handoff_gate = (
        materialized_bundle.get("source_text_handoff_gate")
        if isinstance(materialized_bundle.get("source_text_handoff_gate"), dict)
        else {}
    )
    original_audit = (
        materialized_bundle.get("original_semantic_audit")
        if isinstance(materialized_bundle.get("original_semantic_audit"), dict)
        else {}
    )
    tanxi_source_bound_alignment = bool(
        original_audit.get("tanxi_source_bound_state_machine_gate_passed")
        and source_text_handoff_gate.get("passes") is True
    )
    handoff_text = " ".join(str(item.get("bounded_excerpt") or "") for item in accepted_handoffs)
    direct_text = " ".join([*(_candidate_text(record) for record in direct_records), handoff_text])
    project_hits = _unique(_hits(direct_text, project_terms) + _hits(direct_text, project_phrases))
    subhypothesis_hits = _unique(_hits(direct_text, subhypothesis_terms) + _hits(direct_text, subhypothesis_phrases))
    all_hits = _unique(project_hits + subhypothesis_hits)
    branch_mismatches: list[str] = []
    alignment_failures: list[str] = []
    for record in direct_records:
        record_branch = _paper_branch(record)
        assessment = record.get("alignment_assessment") if isinstance(record.get("alignment_assessment"), dict) else {}
        if branch and record_branch != branch:
            branch_mismatches.append(str(record.get("paper_id") or ""))
        if not bool(assessment.get("core_eligible")):
            alignment_failures.append(str(record.get("paper_id") or ""))
    missing: list[str] = []
    # Imported records retain their branch provenance even in older persisted
    # projects whose explicit alignment-contract map was introduced later.
    # That provenance is enough to audit one-sub-hypothesis identity; do not
    # demote an otherwise complete historical bundle merely for migration
    # metadata that can be rebuilt lazily.
    if not branch:
        missing.append("sub_hypothesis_traceability")
    if not direct_ids or (len(direct_records) != len(direct_ids) and not tanxi_source_bound_alignment):
        missing.append("resolvable_same_snapshot_direct_evidence")
    if branch_mismatches:
        missing.append("same_subhypothesis_direct_evidence")
    if alignment_failures and not tanxi_source_bound_alignment:
        missing.append("primary_aligned_direct_evidence")
    source_span_gate_required = str(materialized_bundle.get("version") or "").startswith("gap_evidence_bundle_v")
    if source_span_gate_required and not bool(source_span_gate.get("passes")):
        missing.append("source_bound_object_process_outcome_evidence")
    if project_terms and not project_hits and not tanxi_source_bound_alignment:
        missing.append("project_scientific_object_anchor")
    if subhypothesis_terms and not subhypothesis_hits and not tanxi_source_bound_alignment:
        missing.append("subhypothesis_entity_or_relation_anchor")
    if len(all_hits) < 2 and not tanxi_source_bound_alignment:
        missing.append("two_project_local_entity_or_relation_anchors")
    passes = not missing
    return {
        "version": "primary_gap_project_alignment_v2",
        "project_id": str(project.get("project_id") or ""),
        "sub_hypothesis_id": branch,
        "verdict": "PROJECT_TOPIC_ALIGNED" if passes else "DOMAIN_MISMATCH",
        "passes": passes,
        "project_anchor_terms": project_terms[:32],
        "project_anchor_phrases": project_phrases[:24],
        "subhypothesis_anchor_terms": subhypothesis_terms[:32],
        "subhypothesis_anchor_phrases": subhypothesis_phrases[:24],
        "project_anchor_hits": project_hits[:16],
        "subhypothesis_anchor_hits": subhypothesis_hits[:16],
        "project_local_entity_or_relation_anchor_count": len(all_hits),
        # Compatibility name for reports written against v1.  Its meaning is
        # now project-local anchors, never a global scientific blacklist.
        "non_generic_anchor_count": len(all_hits),
        "direct_evidence_ids": direct_ids,
        "primary_source_span_gate": source_span_gate,
        "source_text_handoff_gate": source_text_handoff_gate,
        "tanxi_source_bound_alignment": tanxi_source_bound_alignment,
        "primary_source_span_gate_required": source_span_gate_required,
        "branch_mismatch_paper_ids": branch_mismatches,
        "alignment_failure_paper_ids": alignment_failures,
        "missing_requirements": missing,
        "reason": (
            "Direct evidence is bound to the declared project object and one sub-hypothesis."
            if passes else "Primary gap lacks a project-local entity/relation match in direct same-branch evidence; missing: " + ", ".join(missing)
        ),
    }


def qualify_gap_for_primary_hypothesis(project: dict[str, Any], gap: dict[str, Any]) -> dict[str, Any]:
    """Validate a TanXi gap by its multi-paper direct-evidence bundle."""
    bundle = gap.get("mechanism_evidence_bundle") if isinstance(gap.get("mechanism_evidence_bundle"), dict) else build_gap_mechanism_evidence_bundle(project, gap)
    topic_alignment = assess_primary_gap_project_alignment(project, gap, bundle)
    missing = list(bundle.get("missing_requirements") or [])
    scientific_verdicts = gap.get("scientific_verdicts") if isinstance(gap.get("scientific_verdicts"), dict) else {}
    original_audit = bundle.get("original_semantic_audit") if isinstance(bundle.get("original_semantic_audit"), dict) else {}
    three_verdict_gate_present = bool(original_audit.get("three_verdict_details_present"))
    three_verdict_gate_passes = bool(original_audit.get("three_verdict_primary_gate_passed"))
    composite_seed_gate_passes = bool(original_audit.get("composite_mechanism_seed_gate_passed"))
    tanxi_source_bound_gate_passes = bool(original_audit.get("tanxi_source_bound_state_machine_gate_passed"))
    scientific_identity_gate_passes = bool(
        original_audit.get("scientific_identity_gate_passed")
        or three_verdict_gate_passes
        or composite_seed_gate_passes
        or tanxi_source_bound_gate_passes
    )
    if not three_verdict_gate_present and not tanxi_source_bound_gate_passes:
        missing.append("three_verdict_scientific_audit_missing")
    elif not scientific_identity_gate_passes:
        missing.append("scientific_identity_audit_failed")
    if not topic_alignment.get("passes"):
        missing.extend(topic_alignment.get("missing_requirements") or ["project_topic_alignment"])
    missing = list(dict.fromkeys(str(item) for item in missing if str(item).strip()))
    eligible = bool(
        str(bundle.get("status") or "") == "READY_FOR_PRIMARY_QUALIFICATION"
        and (three_verdict_gate_present or tanxi_source_bound_gate_passes)
        and scientific_identity_gate_passes
        and not missing
    )
    return {
        "version": ALIGNMENT_VERSION,
        "primary_eligible": eligible,
        "verdict": "PRIMARY_SCIENTIFIC_GAP" if eligible else "SECONDARY_BACKGROUND_OPPORTUNITY",
        "reason": (
            (
                "Gap evidence bundle joins direct same-sub-hypothesis mechanism-discovery and causal-validation/identification evidence with source-traceable input--mediator--outcome fields and project-topic alignment."
                if bundle.get("complementary_discovery_validation_required")
                else "Gap evidence bundle joins direct same-sub-hypothesis theory/model and experimental evidence with source-traceable input--mediator--outcome fields and project-topic alignment."
            )
            if eligible
            else "Primary-gap evidence bundle requirements missing: " + ", ".join(missing)
        ),
        "sub_hypothesis_id": str(bundle.get("sub_hypothesis_id") or ""),
        "matched_supporting_record_ids": list(bundle.get("matched_gap_signal_record_ids") or []),
        "aligned_supporting_record_ids": list(bundle.get("direct_evidence_ids") or []),
        "theory_evidence_ids": list(bundle.get("theory_evidence_ids") or []),
        "experimental_evidence_ids": list(bundle.get("experimental_evidence_ids") or []),
        "mechanism_discovery_evidence_ids": list(bundle.get("mechanism_discovery_evidence_ids") or []),
        "causal_validation_evidence_ids": list(bundle.get("causal_validation_evidence_ids") or []),
        "has_theoretical_framework": bool(bundle.get("theory_evidence_ids")),
        "has_experimental_evidence": bool(bundle.get("experimental_evidence_ids")),
        "has_mechanism_discovery_evidence": bool(bundle.get("mechanism_discovery_evidence_ids")),
        "has_causal_validation_evidence": bool(bundle.get("causal_validation_evidence_ids")),
        "complementary_discovery_validation_required": bool(bundle.get("complementary_discovery_validation_required")),
        "has_concrete_input": bool(_concrete(bundle.get("intervention"))),
        "has_concrete_mediator": bool(_concrete(bundle.get("mediator"))),
        "has_observable_outcome": bool(_concrete(bundle.get("outcome"))),
        "has_source_spans": all(field in set(bundle.get("source_span_fields") or []) for field in ("input", "mediator", "outcome")),
        "evidence_bundle_status": bundle.get("status"),
        "scientific_verdicts": {
            "source_alignment_verdict": str(scientific_verdicts.get("source_alignment_verdict") or "UNVERIFIABLE_SOURCE"),
            "gap_epistemic_verdict": str(scientific_verdicts.get("gap_epistemic_verdict") or "EVIDENCE_EXTRACTION_SHORTAGE"),
            "causal_readiness_verdict": str(scientific_verdicts.get("causal_readiness_verdict") or "SOURCE_ROLE_CONFLICT"),
            "all_primary_prerequisites_pass": three_verdict_gate_passes,
            "composite_mechanism_seed_gate_passed": composite_seed_gate_passes,
            "scientific_identity_gate_passed": scientific_identity_gate_passes,
        },
        "project_topic_alignment": topic_alignment,
        "missing_requirements": missing,
    }


def _paper_text_sections(paper: dict[str, Any]) -> dict[str, str]:
    payload = paper.get("papergraph_input") if isinstance(paper.get("papergraph_input"), dict) else {}
    sections: dict[str, str] = {}
    for key in (
        "title", "abstract", "conclusion", "method", "scenario", "benchmark", "contribution", "limitation", "full_text_excerpt",
    ):
        value = paper.get(key) or payload.get(key) or ""
        normalized = _normalize(value)
        if normalized:
            sections[key] = normalized
    return sections


def _sentences_with_sources(sections: dict[str, str]) -> list[tuple[str, str]]:
    result: list[tuple[str, str]] = []
    for source_field, text in sections.items():
        for sentence in re.split(r"(?<=[.!?。；;])\s+", text):
            normalized = _normalize(sentence)
            if normalized:
                result.append((source_field, normalized))
    return result


def _semantic_axis_detection(sections: dict[str, str], terms: tuple[str, ...]) -> dict[str, Any]:
    text = _normalize(" ".join(sections.values())).lower()
    hits = _hits(text, list(terms))
    spans = []
    for source_field, sentence in _sentences_with_sources(sections):
        sentence_hits = _hits(sentence.lower(), list(terms))
        if sentence_hits:
            spans.append({"source_field": source_field, "excerpt": sentence[:500], "matched_terms": sentence_hits[:8]})
    return {"hits": hits, "source_spans": spans[:4]}


def _contract_axis_hits(text: str, contract: dict[str, Any]) -> dict[str, dict[str, Any]]:
    core_axis_policy = (
        contract.get("core_axis_policy")
        if isinstance(contract.get("core_axis_policy"), dict)
        else {}
    )
    axes = {
        "input": (
            list(core_axis_policy.get("focal_variable_phrases") or [])
            + list(core_axis_policy.get("focal_variable_terms") or [])
        ),
        "mediator": (
            list(core_axis_policy.get("mechanism_phrases") or [])
            + list(core_axis_policy.get("mechanism_terms") or [])
        ),
        "outcome": (
            list(core_axis_policy.get("outcome_phrases") or [])
            + list(core_axis_policy.get("outcome_terms") or [])
        ),
    }
    result: dict[str, dict[str, Any]] = {}
    for axis, anchors in axes.items():
        normalized_anchors = [str(item) for item in anchors if str(item).strip()]
        hits = _hits(text, normalized_anchors)
        # Keep all hits for traceability and causal-chain scoring, but expose
        # the subset that identifies the scientific object rather than a
        # generic experimental variable or performance word.
        meaningful_hits = [item for item in hits if _normalize(item).lower() not in _L1_GENERIC_RELEVANCE_TERMS]
        result[axis] = {
            "anchors": normalized_anchors,
            "hits": hits,
            "meaningful_hits": meaningful_hits,
            "generic_only_hits": [item for item in hits if item not in meaningful_hits],
        }
    return result


def _paper_branch(record: dict[str, Any]) -> str:
    alignment = record.get("alignment_assessment") if isinstance(record.get("alignment_assessment"), dict) else {}
    import_context = record.get("import_context") if isinstance(record.get("import_context"), dict) else {}
    branch = str(alignment.get("sub_hypothesis_id") or record.get("retrieval_branch") or import_context.get("query_branch") or "")
    # Dedicated searches encode their lane as SH2:experimental_evidence.
    return branch.split(":", 1)[0].strip()


def _subhypothesis_by_id(project: dict[str, Any], sub_hypothesis_id: str) -> dict[str, Any]:
    for item in project.get("sub_hypotheses", []):
        if isinstance(item, dict) and str(item.get("id") or "") == str(sub_hypothesis_id or ""):
            return item
    return {}


def _first_concrete(values: list[Any]) -> str:
    for value in values:
        normalized = _concrete(value)
        if normalized:
            return normalized
    return ""


def _bundle_causal_values(
    gap: dict[str, Any],
    subhypothesis: dict[str, Any],
    mechanism_seed: dict[str, Any],
) -> dict[str, str]:
    ingredients = gap.get("hypothesis_ingredients") if isinstance(gap.get("hypothesis_ingredients"), dict) else {}
    comparison_value = _first_concrete([
        gap.get("comparison"), subhypothesis.get("comparison"), subhypothesis.get("control"),
        " / ".join(str(item) for item in (subhypothesis.get("controls") or []) if str(item).strip()),
        " / ".join(str(item) for item in (ingredients.get("scenarios") or []) if str(item).strip()),
    ])
    def seed_role_value(role: str) -> str:
        payload = (
            mechanism_seed.get(role)
            if isinstance(mechanism_seed.get(role), dict)
            else {}
        )
        return _first_concrete([payload.get("value")])

    evidence_graph_contract = (
        gap.get("evidence_graph_contract")
        if isinstance(gap.get("evidence_graph_contract"), dict)
        else {}
    )
    source_bound_fields = (
        gap.get("source_bound_causal_fields")
        if isinstance(gap.get("source_bound_causal_fields"), dict)
        else {}
    )
    source_bound_state = str(gap.get("gap_state") or evidence_graph_contract.get("gap_state") or "")
    source_bound_handoff_available = bool(
        evidence_graph_contract
        and source_bound_state in {"VALIDATED_SCIENTIFIC_GAP", "TESTABLE_PARTIAL_GAP"}
        and gap.get("source_text_handoffs")
    )

    def source_bound_role_value(role: str) -> str:
        if not source_bound_handoff_available:
            return ""
        payload = (
            source_bound_fields.get(role)
            if isinstance(source_bound_fields.get(role), dict)
            else {}
        )
        return _first_concrete([
            payload.get("value"),
            source_bound_fields.get(role),
            evidence_graph_contract.get(role),
        ])

    raw_intervention = _first_concrete([
        seed_role_value("input"),
        source_bound_role_value("input"),
    ])
    raw_mediator = _first_concrete([
        seed_role_value("mediator"),
        source_bound_role_value("mediator"),
    ])
    try:
        from ._intervention_ontology import classify_mediator_candidate
    except ImportError:
        from _intervention_ontology import classify_mediator_candidate
    mediator_assessment = classify_mediator_candidate(raw_mediator)
    raw_outcome = _first_concrete([
        seed_role_value("outcome"),
        source_bound_role_value("outcome"),
    ])
    return {
        # Preserve the source-facing condition.  Whether it is a legal input
        # is decided only after the research mode has been resolved.
        "intervention": raw_intervention,
        "intervention_candidate": raw_intervention,
        "comparison": comparison_value or "unresolved",
        "mediator": raw_mediator if mediator_assessment.get("admissible_as_mediator") else "unresolved",
        "mediator_candidate": raw_mediator,
        "outcome": raw_outcome if _bundle_outcome_is_usable(raw_outcome) else "unresolved",
        "outcome_candidate": raw_outcome,
        "falsification": _first_concrete([gap.get("falsification"), subhypothesis.get("falsification_condition")]) or "unresolved",
    }


def _bundle_outcome_is_usable(value: Any) -> bool:
    try:
        from ._outcome_ontology import classify_outcome_candidate
    except ImportError:
        from _outcome_ontology import classify_outcome_candidate
    return bool(classify_outcome_candidate(
        value,
        require_target_alignment=False,
        require_source_bound=False,
    ).get("ontology_valid"))


def _is_foundational_bridge_record(record: dict[str, Any]) -> bool:
    assessment = record.get("foundational_bridge_assessment") if isinstance(record.get("foundational_bridge_assessment"), dict) else {}
    return bool(
        assessment.get("research_role") == "FOUNDATIONAL_MECHANISM_BRIDGE"
        or assessment.get("direct_target_evidence") is False and assessment
        or str(record.get("research_role") or "").upper() == "FOUNDATIONAL_MECHANISM_BRIDGE"
        or str(record.get("stratified_layer") or (record.get("import_context") or {}).get("stratified_layer") or "") == "L1_milestone"
    )


def _value_match_terms(value: str, contract: dict[str, Any], field: str) -> list[str]:
    if not _normalize(value):
        return []
    direct = _ranked_terms(value, limit=10)
    if " " in _normalize(value):
        direct.insert(0, _normalize(value))
    core_axis_policy = (
        contract.get("core_axis_policy")
        if isinstance(contract.get("core_axis_policy"), dict)
        else {}
    )
    policy_keys = {
        "input": ("focal_variable_phrases", "focal_variable_terms"),
        "mediator": ("mechanism_phrases", "mechanism_terms"),
        "outcome": ("outcome_phrases", "outcome_terms"),
    }[field]
    policy_terms: list[str] = []
    for key in policy_keys:
        policy_terms.extend(str(item) for item in (core_axis_policy.get(key) or []))
    return _unique(direct + policy_terms)[:14]


def _field_source_spans(
    records: list[dict[str, Any]],
    field: str,
    value: str,
    contract: dict[str, Any],
) -> list[dict[str, Any]]:
    terms = _value_match_terms(value, contract, field)
    spans: list[dict[str, Any]] = []
    for record in records:
        for source_field, sentence in _sentences_with_sources(_paper_text_sections(record)):
            hits = _hits(sentence.lower(), terms)
            if not hits:
                continue
            spans.append({
                "field": field,
                "paper_id": str(record.get("paper_id") or ""),
                "citation": str(record.get("citation") or record.get("title") or ""),
                "evidence_genre": str((record.get("paper_genre") or {}).get("genre") or ""),
                "source_field": source_field,
                "excerpt": sentence[:500],
                "matched_terms": hits[:8],
            })
            break
    return spans[:6]


def _candidate_text(candidate: dict[str, Any]) -> str:
    payload = candidate.get("papergraph_input") if isinstance(candidate.get("papergraph_input"), dict) else {}
    full_text_excerpt = str(
        candidate.get("full_text_excerpt")
        or payload.get("full_text_excerpt")
        or ""
    )[:6000]
    return _normalize(" ".join(
        str(candidate.get(key) or payload.get(key) or "")
        for key in ("title", "abstract", "citation", "conclusion", "contribution", "limitation", "venue")
    ) + " " + full_text_excerpt).lower()


def _explicit_exclusion_hits(candidate: dict[str, Any], contract: dict[str, Any]) -> list[str]:
    # Explicit exclusions are optional project metadata.  The core gate is
    # semantic alignment, not a fragile global blacklist.
    exclusions = (
        contract.get("hard_exclusion_terms")
        or contract.get("explicit_exclusion_terms")
        or []
    )
    text = _candidate_text(candidate)
    return [
        str(term)
        for term in exclusions
        if str(term).lower() in text
        and _exclusion_term_can_hard_reject(
            term,
            protected_positive_terms=protected_positive_terms_for_contract(contract),
        )
    ]


def _axis(hits: list[str], passes: bool) -> dict[str, Any]:
    unique_hits = _unique(hits)
    return {"passes": bool(passes), "hits": unique_hits[:12], "score": round(min(1.0, len(unique_hits) / 3.0), 3)}


def _hits(text: str, terms: list[str]) -> list[str]:
    lowered = str(text or "").lower()
    hits: list[str] = []
    for term in terms:
        normalized = _normalize(term).lower()
        if not normalized:
            continue
        if " " in normalized:
            if normalized in lowered:
                hits.append(normalized)
        # Formula-like/CJK/Greek anchors have no reliable ASCII word boundary.
        # Substring matching is safe here because the anchor comes from this
        # project/sub-hypothesis and must be paired with another local anchor.
        elif re.search(r"[\u0370-\u03ff\u4e00-\u9fff+\-./]", normalized):
            if normalized in lowered:
                hits.append(normalized)
        elif re.search(rf"(?<![a-z0-9_]){re.escape(normalized)}(?![a-z0-9_])", lowered):
            hits.append(normalized)
    return _unique(hits)


def _strong_object_anchor_matches_candidate(phrase: str, text: str) -> bool:
    """Match source-bound object identity without bag-of-words leakage.

    Multi-token object anchors must occur as a bounded phrase (allowing only
    hyphen/space spelling variants).  This deliberately differs from the
    recall-oriented causal-axis matcher: finding ``digital`` in one place and
    ``memory`` elsewhere must not turn an unrelated paper into a digital-memory
    record.
    """

    normalized = _normalize(phrase).lower()
    if not normalized:
        return False
    if " " not in normalized:
        return bool(_hits(str(text or "").lower(), [normalized]))
    comparable_text = _normalize(
        re.sub(r"[\u2010-\u2015\u2212]", "-", str(text or "").lower())
    )
    comparable_space_text = _normalize(comparable_text.replace("-", " "))
    comparable_anchor = _normalize(
        re.sub(r"[\u2010-\u2015\u2212]", "-", normalized)
    )
    variants = {
        comparable_anchor,
        _normalize(comparable_anchor.replace("-", " ")),
    }
    if "-based" in comparable_anchor:
        variants.add(_normalize(comparable_anchor.replace("-based", " based")))
    if " based " in comparable_anchor:
        variants.add(_normalize(comparable_anchor.replace(" based ", "-based ")))

    def _bounded_phrase_present(variant: str, haystack: str) -> bool:
        return bool(variant) and re.search(
            rf"(?<![a-z0-9]){re.escape(variant)}(?![a-z0-9])",
            haystack,
        ) is not None

    return any(
        _bounded_phrase_present(variant, comparable_text)
        or _bounded_phrase_present(variant, comparable_space_text)
        for variant in variants
    )


def _source_bound_scientific_object_hits(
    text: str,
    contract: dict[str, Any],
) -> list[str]:
    """Return only identity hits certified by the SH object-anchor contract."""

    policy = (
        contract.get("scientific_object_anchor_policy")
        if isinstance(contract.get("scientific_object_anchor_policy"), dict)
        else {}
    )
    anchors = _unique(
        list(policy.get("strong_anchor_phrases") or [])
        + list(policy.get("strong_anchor_terms") or [])
        + list(policy.get("semantic_equivalent_anchor_phrases") or [])
        + list(policy.get("semantic_equivalent_anchor_terms") or [])
    )
    if policy.get("direct_core_object_allowed") is False:
        anchors = _unique(
            anchors
            + list(policy.get("component_bridge_object_anchor_phrases") or [])
            + list(policy.get("object_group") or [])
        )
    hits = [
        anchor for anchor in anchors
        if _strong_object_anchor_matches_candidate(anchor, text)
    ]
    return _unique(hits)


def _retrieval_object_profile_hits(
    text: str,
    contract: dict[str, Any],
    candidate: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Match only the profile that produced this candidate's query branch.

    Profile hits are admissible for corpus relevance, never a silent
    substitute for source-bound primary-object hits used by direct core.
    """
    payload = candidate if isinstance(candidate, dict) else {}
    profile_id = _normalize(payload.get("retrieval_object_profile_id")).upper()
    profiles = [
        dict(profile) for profile in (contract.get("retrieval_object_profiles") or [])
        if isinstance(profile, dict)
    ]
    profile = next(
        (
            item for item in profiles
            if _normalize(item.get("id")).upper() == profile_id
        ),
        {},
    )
    role = _normalize(profile.get("role")).lower()
    if not profile or role == "primary_system":
        return {
            "profile_id": profile_id,
            "profile_role": role,
            "profile_object": _normalize(profile.get("object")),
            "hits": [],
            "nonprimary_profile": False,
        }
    anchors = _unique([
        _normalize(profile.get("query_anchor")),
        _normalize(profile.get("object")),
        *[_normalize(value) for value in _scope_policy_values(profile.get("aliases"))],
    ])
    hits = [
        anchor for anchor in anchors
        if anchor and _strong_object_anchor_matches_candidate(anchor, text)
    ]
    return {
        "profile_id": profile_id,
        "profile_role": role,
        "profile_object": _normalize(profile.get("object")),
        "hits": _unique(hits),
        "nonprimary_profile": True,
    }


def _ranked_terms(text: str, *, limit: int) -> list[str]:
    def token_candidates(value: str) -> list[str]:
        candidates: list[str] = []
        for token in _TOKEN_RE.findall(value):
            candidates.append(token)
            if re.fullmatch(r"[\u4e00-\u9fff]{2,}", token):
                # Chinese scientific text normally has no whitespace.  Retain
                # the complete phrase and overlapping entity-sized segments so
                # CO2矿化/碳酸盐/成核 can still align across differently
                # worded titles and abstracts.
                for width in (2, 3, 4):
                    candidates.extend(token[index:index + width] for index in range(len(token) - width + 1))
        return candidates

    def is_scientific_token(token: str) -> bool:
        return (
            len(token) >= 3
            or any(char.isdigit() for char in token)
            or re.search(r"[\u4e00-\u9fff\u0370-\u03ff]", token) is not None
            or token.lower() == "ph"
        )

    counts = Counter(
        token.lower()
        for token in token_candidates(str(text or ""))
        if token.lower() not in _STOPWORDS and is_scientific_token(token)
    )
    # Frequency is useful for project identity, while alphabetical tie breaks
    # make persisted contracts deterministic.
    return [term for term, _ in sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:limit]]


def _phrases(text: str, *, limit: int) -> list[str]:
    tokens = [token for token in _ranked_terms(text, limit=80) if token not in _PROJECT_ANCHOR_GLUE_TERMS]
    # Preserve source-order phrases as well as individual anchors.  Two-word
    # phrases sharply reduce collisions such as generic "solvent polarity".
    source_tokens = [token.lower() for token in _TOKEN_RE.findall(str(text or "")) if token.lower() not in _STOPWORDS]
    phrases = []
    for index in range(len(source_tokens) - 1):
        left, right = source_tokens[index], source_tokens[index + 1]
        if left in _LOW_SIGNAL and right in _LOW_SIGNAL:
            continue
        phrase = f"{left} {right}"
        if left in tokens or right in tokens:
            phrases.append(phrase)
    return _unique(phrases)[:limit]


def _focal_variable_text(value: Any) -> str:
    """Extract the named variable from an operational/contextual wrapper.

    This is intentionally shallow and field-neutral.  It does not attempt to
    infer a scientific entity; it merely prevents an attached setting from
    becoming an alternative focal variable when the SH explicitly names an
    intervention or exposure.
    """
    source = _normalize(value)
    if not source:
        return ""
    source = _normalize(_FOCAL_VARIABLE_OPERATION_PREFIX_RE.sub("", source))
    head = _FOCAL_VARIABLE_CONTEXT_SPLIT_RE.split(source, maxsplit=1)[0].strip()
    return head or source


def _core_axis_terms(
    text: Any,
    *,
    excluded_terms: list[str] | tuple[str, ...] | set[str] | None = None,
) -> list[str]:
    """Return terms permitted to establish a direct causal axis.

    Discovery remains allowed to use a richer vocabulary.  Direct-core
    evidence, however, may not use general scientific prose or a term already
    assigned to an upstream causal axis to prove an independent downstream
    endpoint.
    """
    excluded = {_normalize(value).lower() for value in (excluded_terms or []) if _normalize(value)}
    values = []
    for term in _ranked_terms(str(text or ""), limit=32):
        normalized = _normalize(term).lower()
        if not normalized or normalized in _CORE_AXIS_GENERIC_TERMS or normalized in excluded:
            continue
        values.append(normalized)
    return _unique(values)[:16]


def _core_axis_phrases(text: Any, terms: list[str]) -> list[str]:
    """Retain exact multi-token anchors for direct-core provenance checks.

    The phrase is retained from the *declared source text*, not rebuilt from
    only the surviving non-generic tokens.  A connector such as ``interaction``
    can be too broad to establish an axis alone while still being essential to
    the integrity of ``magnetic interaction strength``.  Dropping that
    connector before phrase construction used to turn a repairable declared
    input into unrelated one-word remnants.
    """
    allowed = {_normalize(term).lower() for term in terms if _normalize(term)}
    source_tokens = [
        token.lower()
        for token in _TOKEN_RE.findall(str(text or ""))
        if token.lower() not in _STOPWORDS
    ]
    phrases: list[str] = []
    # Retain bounded source-order n-grams, including trigrams and longer
    # compact declarations.  One surviving content token is sufficient here:
    # the phrase itself must have at least two tokens and the downstream axis
    # gate rechecks that it contains identifying content.  Requiring two
    # surviving terms here incorrectly destroyed valid declared phrases such
    # as ``metabolic activity`` when ``activity`` was filtered as a generic
    # readout connector, or condition-bound inputs such as ``pollution in a
    # defined system`` when only the exposure noun survived term filtering.
    for width in range(2, min(6, len(source_tokens)) + 1):
        for start in range(0, len(source_tokens) - width + 1):
            phrase_tokens = source_tokens[start:start + width]
            meaningful = [token for token in phrase_tokens if token in allowed]
            if meaningful:
                phrases.append(" ".join(phrase_tokens))
    return _unique(phrases)[:12]


def _reference_matches(reference: str, record: dict[str, Any]) -> bool:
    normalized_reference = _normalize(reference).lower()
    if not normalized_reference:
        return False
    values = [str(record.get(key) or "") for key in ("citation", "title", "doi", "paper_id")]
    for value in values:
        normalized_value = _normalize(value).lower()
        if normalized_value and (
            normalized_reference == normalized_value
            or normalized_reference in normalized_value
            or normalized_value in normalized_reference
        ):
            return True
    return False


def _concrete(value: Any) -> str:
    text = _normalize(str(value or ""))
    return "" if text.lower() in {"", "unknown", "unresolved", "not applicable", "none"} else text


def _candidate_is_review(candidate: dict[str, Any]) -> bool:
    publication_types = " ".join(str(item or "") for item in (candidate.get("publication_types") or []))
    text = " ".join(
        str(candidate.get(key) or "")
        for key in ("title", "abstract", "citation", "venue")
    ) + " " + publication_types
    lowered = _normalize(text).lower()
    return any(marker in lowered for marker in _REVIEW_MARKERS)


def _coverage(hits: list[str], anchors: list[str]) -> float:
    if not anchors:
        return 0.0
    # A foundation needs one precise anchor in every causal segment.  Cap the
    # denominator so a verbose falsification clause cannot suppress a strong
    # historical paper merely because it omits an incidental synonym.
    return min(1.0, len(set(hits)) / max(1, min(3, len(set(anchors)))))


def _field_normalized_citation_impact(candidate: dict[str, Any]) -> float:
    try:
        from ._literature_scoring import field_citation_baseline, infer_research_field
    except ImportError:
        from _literature_scoring import field_citation_baseline, infer_research_field
    citations = _float_or_default(candidate.get("citation_count"), 0.0)
    influential = _float_or_default(candidate.get("influential_citation_count"), 0.0)
    try:
        baseline = max(1.0, float(field_citation_baseline(infer_research_field(candidate))))
    except Exception:
        baseline = 500.0
    # Deliberately do not call the generic impact score: it includes a
    # recent-paper special case, which would reintroduce a recency preference
    # into this historical lane.
    citation_score = min(1.0, math.log1p(max(0.0, citations)) / math.log1p(baseline))
    influential_score = min(
        1.0,
        math.log1p(max(0.0, influential)) / math.log1p(max(50.0, baseline * 0.3)),
    )
    return round(max(citation_score, 0.75 * citation_score + 0.25 * influential_score), 4)


def _float_or_default(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _unique(values: list[str]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = _normalize(value)
        key = normalized.lower()
        if normalized and key not in seen:
            seen.add(key)
            output.append(normalized)
    return output


def _normalize(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _stable_hash(payload: dict[str, Any]) -> str:
    material = {key: value for key, value in payload.items() if key not in {"alignment_card_hash", "contract_hash"}}
    return sha256(json.dumps(material, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest()[:24]
