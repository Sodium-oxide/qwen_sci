"""Strict, cumulative contracts for one sub-hypothesis retrieval loop.

Discovery counts are not evidence counts.  This module only admits a paper to
the coverage gate after it is bound to the current sub-hypothesis, has acquired
full text, is not an unpublished preprint, and passes the relevant alignment
or historical-foundation contract.  It is deliberately provider-agnostic so
the serial controller and restart logic share exactly the same readiness rule.
"""
from __future__ import annotations

from collections import Counter
from hashlib import sha256
from typing import Any
import json
import re

try:
    from ._type_directed_evidence import (
        evidence_profile_for_contract,
        type_directed_missing_axes,
    )
except ImportError:
    from _type_directed_evidence import (
        evidence_profile_for_contract,
        type_directed_missing_axes,
    )


NON_PREPRINT_LAYERS = ("L0_review", "L1_milestone", "L2_top_latest", "L4_regular")
SUBHYPOTHESIS_IMPORTED_FULL_TEXT_TARGET = 10
SUBHYPOTHESIS_EVIDENCE_PORTFOLIO_MINIMUMS = {
    "direct_contract_core": 1,
    "component_or_bridge": 1,
    "boundary_or_negative": 0,
    "adverse_or_reversal": 0,
    "background_or_framework": 1,
    "method_or_foundation": 1,
}
QUERY_OPTIMIZER_FAILURE_CLASSES = frozenset({
    "RELATED_FULLTEXT_COUNT_SHORTFALL",
    "COMPATIBLE_DIRECT_CORE_SHORTFALL",
    "TYPE_DIRECTED_EVIDENCE_BUNDLE_SHORTFALL",
})
RETRIEVAL_TERMINAL_STATUSES = frozenset({
    "FULLTEXT_TARGET_MET",
    "DIRECT_CORE_SUPPORT_AVAILABLE",
    "EVIDENCE_SATURATED_SHORTFALL",
    "PROVIDER_ACCESS_BLOCKED",
    "FULLTEXT_ACCESS_BLOCKED",
    "NO_NEW_UNIQUE_RESULTS",
    "NO_PROVIDER_RESULTS",
    "NO_DEDUPED_CANDIDATES",
    "NO_NET_NEW_FULLTEXT",
    "NO_FRESH_QUERY_BRANCHES",
    "RETRIEVAL_EXCEPTION_BEFORE_PROVIDER",
    "PROVIDER_RATE_LIMITED",
    "FULLTEXT_SHORTFALL_NO_FRESH_QUERY",
    "PARTIAL_RELATED_CORPUS_NO_FRESH_QUERY",
    "COMPONENT_BRIDGE_GAP_SYNTHESIS_READY",
    "QUERY_ALIGNMENT_FAILED",
    "CONTRACT_AXIS_DEGENERATE",
    "CALIBRATION_PLAN_MISMATCH_REFINEMENT_UNAVAILABLE",
})

_GENERIC_RETRIEVAL_TERMS = frozenset({
    "analysis", "analyses", "approach", "approaches", "biological", "biology",
    "biochemistry", "causal", "condition", "conditions", "data", "effect", "effects",
    "evidence", "experiment", "experiments", "experimental", "function", "functions",
    "impact", "intervention", "interventions", "investigate", "investigation", "life",
    "measurement", "measurements", "mechanism", "mechanisms", "method", "methods",
    "model", "models", "molecular", "molecule", "molecules", "outcome", "outcomes",
    "pathway", "pathways", "process", "processes", "research", "result", "results",
    "role", "roles", "selection", "selective", "study", "studies", "system", "systems",
    "understanding", "validation", "validated",
})

_CONTEXT_ONLY_QUERY_MARKERS = (
    "review",
    "systematic review",
    "scoping review",
    "meta-analysis",
    "meta analysis",
    "survey",
    "overview",
    "perspective",
    "progress",
    "advances",
    "advancements",
    "current trends",
    "tutorial",
    "roadmap",
    "guideline",
    "consensus",
    "field map",
    "theoretical framework",
    "conceptual framework",
    "formal model",
    "framework",
)

_QUERY_DESIGN_ANCHORS = (
    "controlled study",
    "controlled experiment",
    "controlled evaluation",
    "randomized trial",
    "randomised trial",
    "clinical trial",
    "field trial",
    "field experiment",
    "cohort",
    "case-control",
    "case control",
    "longitudinal",
    "prospective",
    "retrospective",
    "external validation",
    "independent validation",
    "validation cohort",
    "multi-site",
    "multisite",
    "multicenter",
    "multicentre",
    "assay",
    "in vivo",
    "in vitro",
    "ex vivo",
    "animal model",
    "cell culture",
    "laboratory measurement",
    "design of experiments",
    "factorial",
    "benchmark",
    "simulation study",
    "numerical experiment",
    "empirical evaluation",
    "natural experiment",
    "quasi-experiment",
    "quasi experiment",
    "instrumental variable",
    "difference-in-differences",
    "difference in differences",
    "regression discontinuity",
    "interrupted time series",
    "parameter sweep",
    "stress test",
    "prototype test",
    "hardware experiment",
    "field monitoring",
    # Agricultural and biological sciences.
    "greenhouse experiment",
    "growth chamber",
    "treatment plot",
    "field plot",
    "field sampling",
    "phenotyping",
    "bioassay",
    "feeding trial",
    # Molecular biology, microbiology, immunology, neuroscience, and health.
    "crispr",
    "flow cytometry",
    "western blot",
    "qpcr",
    "rna-seq",
    "single-cell",
    "sequencing",
    "enzyme assay",
    "binding assay",
    "cell viability",
    "infection model",
    "diagnostic accuracy",
    "patient cohort",
    "case series",
    "pragmatic trial",
    # Chemistry, chemical engineering, materials, energy, and physics.
    "reactor experiment",
    "kinetic study",
    "spectroscopy",
    "chromatography",
    "electrochemical test",
    "crystallography",
    "thermal analysis",
    "characterization",
    "operando measurement",
    "in situ measurement",
    "cycling test",
    "accelerated aging",
    "mechanical testing",
    "tensile test",
    "fatigue test",
    "fracture test",
    "prototype evaluation",
    # Computer science, mathematics, statistics, and quantitative sciences.
    "ablation study",
    "cross-validation",
    "cross validation",
    "train test split",
    "test set",
    "holdout set",
    "reproducibility test",
    "robustness test",
    "theorem",
    "proof",
    "counterexample",
    "derivation",
    "convergence analysis",
    # Earth, planetary, environmental, and remote-sensing sciences.
    "remote sensing",
    "source attribution",
    "tracer study",
    "mesocosm",
    "environmental monitoring",
    "water quality monitoring",
    "soil analysis",
    "climate model",
    # Discipline-catalog coverage: agriculture/biology.
    "randomized block",
    "randomised block",
    "split plot",
    "common garden",
    "plant phenotyping",
    "ecological survey",
    "population survey",
    "biodiversity survey",
    "seed germination assay",
    "greenhouse trial",
    "crop trial",
    "feeding experiment",
    "animal feeding trial",
    # Discipline-catalog coverage: molecular/life sciences and health.
    "elisa",
    "immunoassay",
    "plaque assay",
    "neutralization assay",
    "neutralisation assay",
    "microbial culture",
    "minimum inhibitory concentration",
    "mic assay",
    "chip-seq",
    "proteomics",
    "metabolomics",
    "mass spectrometry",
    "lc-ms",
    "gc-ms",
    "electrophysiology",
    "calcium imaging",
    "optogenetics",
    "lesion study",
    "neuroimaging",
    "pk study",
    "pharmacokinetic study",
    "pharmacodynamic study",
    "adme assay",
    "toxicology assay",
    "implant trial",
    "split-mouth trial",
    "split mouth trial",
    "rehabilitation trial",
    "implementation trial",
    "quality improvement study",
    # Discipline-catalog coverage: chemistry/materials/physics/energy.
    "nmr",
    "xrd",
    "x-ray diffraction",
    "x ray diffraction",
    "sem",
    "tem",
    "afm",
    "dsc",
    "tga",
    "bet surface area",
    "rheology",
    "corrosion test",
    "hardness test",
    "nanoindentation",
    "battery cycling",
    "galvanostatic cycling",
    "impedance spectroscopy",
    "photovoltaic test",
    "solar simulator",
    "electrolyzer test",
    "fuel cell test",
    "scattering experiment",
    "interferometry",
    "detector calibration",
    "telescope observation",
    "beam test",
    # Discipline-catalog coverage: engineering/computing/earth/environment.
    "finite element validation",
    "wind tunnel",
    "vibration test",
    "calibration experiment",
    "instrument calibration",
    "control experiment",
    "manufacturing trial",
    "process validation",
    "additive manufacturing test",
    "dataset benchmark",
    "baseline evaluation",
    "out-of-distribution test",
    "out of distribution test",
    "geochemical analysis",
    "sediment core",
    "ice core",
    "isotope analysis",
    "geochronology",
    "atmospheric monitoring",
    "air quality monitoring",
    "ecotoxicity assay",
    "life cycle assessment",
)

_QUERY_INTERVENTION_ANCHORS = (
    "knockout",
    "knockdown",
    "overexpression",
    "inhibition",
    "inhibit",
    "inhibitor",
    "perturbation",
    "perturb",
    "ablation",
    "treatment",
    "intervention",
    "dose response",
    "dose-response",
    "exposure",
    "controlled condition",
    "input perturbation",
    "fault injection",
    "stress testing",
    "field tuning",
    "policy shock",
    "regime shift",
    "isotope labeling",
    "isotope labelling",
    "catalyst loading",
    "concentration",
    "temperature",
    "pressure",
    "doping",
    "strain",
    # Cross-disciplinary intervention or controllable-input terms derived from
    # the non-humanities/non-social-science discipline catalog.
    "fertilization",
    "irrigation",
    "management intervention",
    "gene editing",
    "mutagenesis",
    "transfection",
    "stimulation",
    "challenge",
    "infection",
    "drug exposure",
    "compound treatment",
    "catalyst",
    "solvent",
    "ph",
    "flow rate",
    "residence time",
    "composition",
    "processing condition",
    "annealing",
    "sintering",
    "thermal cycling",
    "charge discharge",
    "load test",
    "fault injection",
    "algorithm change",
    "architecture change",
    "hyperparameter",
    "regularization",
    "forcing",
    "emission scenario",
    # Discipline-catalog coverage: agriculture/biology/environment.
    "fertilizer",
    "fertiliser",
    "fertilizer application",
    "fertiliser application",
    "nutrient addition",
    "planting density",
    "pesticide treatment",
    "herbicide treatment",
    "grazing treatment",
    "salinity stress",
    "drought stress",
    "pollutant exposure",
    "contaminant exposure",
    "remediation",
    "bioaugmentation",
    "land use change",
    # Discipline-catalog coverage: molecular/life/health sciences.
    "crispr knockout",
    "rna interference",
    "sirna",
    "shrna",
    "gene knock-in",
    "gene knockin",
    "transgenic",
    "antigen challenge",
    "pathogen challenge",
    "microbial inoculation",
    "optogenetic stimulation",
    "electrical stimulation",
    "lesion",
    "formulation",
    "dose escalation",
    "drug combination",
    "surgical intervention",
    "care protocol",
    "rehabilitation protocol",
    # Discipline-catalog coverage: chemistry/materials/physics/engineering.
    "feed composition",
    "mixing rate",
    "stirring rate",
    "voltage window",
    "current density",
    "laser pulse",
    "magnetic field",
    "electric field",
    "irradiation",
    "surface treatment",
    "coating thickness",
    "particle size",
    "grain size",
    "alloying",
    "heat treatment",
    "curing condition",
    "printing parameter",
    "machining parameter",
    "load profile",
    "vibration input",
    "control parameter",
    "mesh resolution",
    # Discipline-catalog coverage: computing/math/earth/energy.
    "model architecture",
    "training data",
    "data augmentation",
    "optimizer",
    "loss function",
    "constraint relaxation",
    "initial condition",
    "boundary condition",
    "voltage",
    "state of charge",
    "discharge rate",
    "solar irradiance",
    "wind speed",
    "climate forcing",
)

_QUERY_COMPARISON_ANCHORS = (
    "versus",
    " vs ",
    "compared with",
    "comparison",
    "control group",
    "control",
    "baseline",
    "usual care",
    "single marker",
    "single-component",
    "single component",
    "clinical-only",
    "counterfactual",
    "placebo",
    "out-of-sample",
    "out of sample",
    "external validation",
    "calibration",
    "discrimination",
    "incremental prediction",
    "incremental value",
    "decision curve",
    "benchmark",
    "reference standard",
    "gold standard",
    "negative control",
    "positive control",
    "untreated control",
    "sham control",
    "wild type",
    "knockout control",
    "ablation study",
    "state of the art",
    "sota",
    "standard method",
    "reference material",
    "blank control",
    "replicate",
)

_QUERY_ENDPOINT_ANCHORS = (
    "endpoint",
    "outcome",
    "readout",
    "functional readout",
    "measurable endpoint",
    "measurable outcome",
    "quantitative measurement",
    "measurement",
    "performance",
    "accuracy",
    "sensitivity",
    "specificity",
    "calibration",
    "discrimination",
    "auc",
    "cmax",
    "toxicity",
    "survival",
    "yield",
    "potency",
    "sterility",
    "purity",
    "expression",
    "antigen expression",
    "antibody titer",
    "antibody titre",
    "ifn",
    "t-cell",
    "t cell",
    "activity",
    "retention",
    "efficiency",
    "coverage",
    "error",
    "loss",
    "throughput",
    "cost",
    "turnaround time",
    # Life, health, and environmental endpoints.
    "biomass",
    "yield measurement",
    "growth rate",
    "phenotype",
    "biodiversity",
    "species richness",
    "disease severity",
    "viral load",
    "pathogen load",
    "immune response",
    "cytokine",
    "gene expression",
    "protein expression",
    "enzyme activity",
    "cell viability",
    "apoptosis",
    "toxicity incidence",
    "adverse event",
    "symptom score",
    "quality of life",
    "diagnostic sensitivity",
    "diagnostic specificity",
    "hazard ratio",
    "odds ratio",
    # Chemistry, physics, materials, engineering, and energy endpoints.
    "conversion",
    "selectivity",
    "reaction rate",
    "kinetics",
    "binding affinity",
    "detection limit",
    "limit of detection",
    "conductivity",
    "resistivity",
    "capacity",
    "cycle life",
    "degradation",
    "failure mode",
    "tensile strength",
    "elastic modulus",
    "fracture toughness",
    "thermal stability",
    "optical response",
    "signal to noise",
    "power density",
    "energy density",
    # Computer science, mathematics, statistics, and quantitative endpoints.
    "f1 score",
    "precision",
    "recall",
    "latency",
    "runtime",
    "memory usage",
    "generalization error",
    "robustness",
    "confidence interval",
    "error bound",
    "convergence rate",
    "statistical power",
    # Earth, environmental, and planetary endpoints.
    "concentration",
    "flux",
    "water quality",
    "soil carbon",
    "emission",
    "temperature anomaly",
    "spatiotemporal trend",
    # Discipline-catalog coverage: agricultural and biological sciences.
    "crop yield",
    "grain yield",
    "plant height",
    "root biomass",
    "germination rate",
    "photosynthetic rate",
    "chlorophyll content",
    "soil nutrient",
    "soil moisture",
    "pest pressure",
    "disease incidence",
    "population abundance",
    "community composition",
    # Discipline-catalog coverage: molecular biology, microbiology, immunology,
    # neuroscience, pharmacology, and health sciences.
    "mrna expression",
    "protein abundance",
    "phosphorylation",
    "pathway activation",
    "binding constant",
    "ki",
    "ic50",
    "ec50",
    "minimal inhibitory concentration",
    "minimum inhibitory concentration",
    "colony forming units",
    "cfu",
    "plaque forming units",
    "pfu",
    "neutralizing antibody",
    "neutralising antibody",
    "seroconversion",
    "bacterial load",
    "parasite burden",
    "spike rate",
    "firing rate",
    "synaptic plasticity",
    "neural activity",
    "signal amplitude",
    "auc0-inf",
    "trough concentration",
    "clearance",
    "half-life",
    "bioavailability",
    "adme",
    "mortality",
    "morbidity",
    "response rate",
    "progression-free survival",
    "progression free survival",
    "overall survival",
    "relapse rate",
    "pain score",
    "functional status",
    "mobility",
    "implant survival",
    "periodontal pocket depth",
    "plaque index",
    "caries incidence",
    "bond strength",
    # Discipline-catalog coverage: chemistry, chemical engineering, energy,
    # materials science, physics, and engineering.
    "space time yield",
    "productivity",
    "mass transfer coefficient",
    "heat transfer coefficient",
    "separation factor",
    "faradaic efficiency",
    "coulombic efficiency",
    "overpotential",
    "open circuit voltage",
    "power conversion efficiency",
    "quantum yield",
    "band gap",
    "surface area",
    "pore size",
    "porosity",
    "particle size distribution",
    "grain size",
    "hardness",
    "wear rate",
    "corrosion rate",
    "adhesion strength",
    "compressive strength",
    "fatigue life",
    "creep rate",
    "dimensional accuracy",
    "surface roughness",
    "vibration amplitude",
    "displacement",
    "stress",
    "strain",
    "reliability",
    "mean time to failure",
    "tolerance",
    "cross section",
    "phase transition",
    "luminosity",
    # Discipline-catalog coverage: computer science, mathematics, statistics,
    # earth sciences, environmental science, and quantitative science.
    "mean average precision",
    "map score",
    "auroc",
    "balanced accuracy",
    "perplexity",
    "bleu",
    "rouge",
    "ndcg",
    "regret",
    "approximation ratio",
    "stability bound",
    "sample complexity",
    "wall clock time",
    "energy consumption",
    "contaminant concentration",
    "dissolved oxygen",
    "chemical oxygen demand",
    "biochemical oxygen demand",
    "cod",
    "bod",
    "particulate matter",
    "pm2.5",
    "greenhouse gas emission",
    "carbon sequestration",
    "runoff",
    "erosion rate",
    "sea level",
    "precipitation anomaly",
    "mineral composition",
    "seismic velocity",
    "remote sensing index",
)

ADVERSE_OR_REVERSAL_EVIDENCE_LANE = "ADVERSE_OR_REVERSAL_EVIDENCE"
BOUNDARY_OR_NEGATIVE_EVIDENCE_LANE = "BOUNDARY_OR_NEGATIVE_EVIDENCE"

_ADVERSE_OR_REVERSAL_QUERY_ANCHORS = (
    "negative effect",
    "adverse effect",
    "adverse event",
    "unintended consequence",
    "unintended consequences",
    "rebound effect",
    "substitution effect",
    "substitution burden",
    "burden shifting",
    "burden-shifting",
    "trade-off",
    "tradeoff",
    "life cycle burden",
    "lifecycle burden",
    "higher carbon footprint",
    "increased emissions",
    "increased toxicity",
    "resource competition",
    "feedstock competition",
    "failure mode",
    "implementation failure",
    "policy failure",
    "robustness failure",
    "distribution shift",
    "off-target effect",
    "resistance",
    "toxicity",
    "null effect",
    "no significant effect",
    "reduced effectiveness",
    "worse outcome",
)

# Query profiles derived from the OpenAlex discipline catalog used by
# PaperSeek.  Humanities and social-science disciplines are intentionally not
# represented here (e.g. Arts and Humanities, Business/Management, Economics,
# Psychology, Social Sciences).  The profiles do not change the SH contract;
# they only help deficit-repair queries use discipline-appropriate experimental,
# validation, or measurable-outcome vocabulary.
_IGNORED_DISCIPLINE_QUERY_PROFILE_MARKERS = (
    "arts and humanities",
    "business management and accounting",
    "business",
    "management",
    "economics econometrics and finance",
    "economics",
    "econometrics",
    "finance",
    "psychology",
    "social sciences",
    "sociology",
    "political science",
    "law",
    "education",
    "linguistics",
    "history",
    "philosophy",
    "religion",
)

_DISCIPLINE_QUERY_KEYWORD_PROFILES: tuple[dict[str, tuple[str, ...]], ...] = (
    {
        "id": ("11",),
        "match": (
            "agricultural and biological sciences",
            "agronomy",
            "agriculture",
            "biology",
            "ecology",
            "biodiversity conservation",
            "plant sciences",
            "soil science",
            "zoology",
            "forestry",
            "horticulture",
            "food science",
            "fisheries",
            "marine freshwater biology",
        ),
        "design": (
            "field trial",
            "greenhouse experiment",
            "randomized block",
            "phenotyping",
            "field sampling",
        ),
        "intervention": (
            "fertilizer application",
            "irrigation",
            "planting density",
            "pesticide treatment",
            "drought stress",
        ),
        "endpoint": (
            "crop yield",
            "biomass",
            "growth rate",
            "phenotype",
            "species richness",
        ),
    },
    {
        "id": ("13",),
        "match": (
            "biochemistry genetics and molecular biology",
            "biochemistry",
            "molecular biology",
            "genetics heredity",
            "cell biology",
            "developmental biology",
            "reproductive biology",
            "biotechnology applied microbiology",
            "mathematical computational biology",
        ),
        "design": (
            "crispr",
            "rna-seq",
            "qpcr",
            "western blot",
            "enzyme assay",
        ),
        "intervention": (
            "knockout",
            "knockdown",
            "overexpression",
            "inhibition",
            "transfection",
        ),
        "endpoint": (
            "gene expression",
            "protein expression",
            "enzyme activity",
            "binding affinity",
            "cell viability",
        ),
    },
    {
        "id": ("15",),
        "match": (
            "chemical engineering",
            "engineering chemical",
            "thermodynamics",
            "polymer science",
            "process engineering",
        ),
        "design": (
            "reactor experiment",
            "kinetic study",
            "design of experiments",
            "process validation",
            "response surface",
        ),
        "intervention": (
            "temperature",
            "pressure",
            "flow rate",
            "residence time",
            "catalyst loading",
        ),
        "endpoint": (
            "conversion",
            "selectivity",
            "yield",
            "productivity",
            "purity",
        ),
    },
    {
        "id": ("16",),
        "match": (
            "chemistry",
            "analytical chemistry",
            "organic chemistry",
            "inorganic chemistry",
            "physical chemistry",
            "medicinal chemistry",
            "crystallography",
            "electrochemistry",
            "spectroscopy",
        ),
        "design": (
            "spectroscopy",
            "chromatography",
            "mass spectrometry",
            "nmr",
            "electrochemical test",
        ),
        "intervention": (
            "solvent",
            "ph",
            "concentration",
            "temperature",
            "catalyst",
        ),
        "endpoint": (
            "conversion",
            "selectivity",
            "binding affinity",
            "detection limit",
            "quantum yield",
        ),
    },
    {
        "id": ("17",),
        "match": (
            "computer science",
            "artificial intelligence",
            "machine learning",
            "information systems",
            "software engineering",
            "theory methods",
            "robotics",
            "telecommunications",
        ),
        "design": (
            "benchmark",
            "ablation study",
            "cross-validation",
            "test set",
            "out-of-distribution test",
        ),
        "intervention": (
            "model architecture",
            "training data",
            "data augmentation",
            "hyperparameter",
            "regularization",
        ),
        "endpoint": (
            "accuracy",
            "f1 score",
            "latency",
            "throughput",
            "robustness",
        ),
    },
    {
        "id": ("19",),
        "match": (
            "earth and planetary sciences",
            "geology",
            "geochemistry geophysics",
            "geosciences",
            "meteorology atmospheric sciences",
            "oceanography",
            "paleontology",
            "remote sensing",
            "mineralogy",
            "astronomy astrophysics",
        ),
        "design": (
            "field sampling",
            "remote sensing",
            "geochemical analysis",
            "sediment core",
            "climate model",
        ),
        "intervention": (
            "forcing",
            "emission scenario",
            "land use change",
            "temperature",
            "pressure",
        ),
        "endpoint": (
            "concentration",
            "flux",
            "temperature anomaly",
            "spatiotemporal trend",
            "seismic velocity",
        ),
    },
    {
        "id": ("21",),
        "match": (
            "energy",
            "energy fuels",
            "nuclear science technology",
            "green sustainable science technology",
            "petroleum engineering",
        ),
        "design": (
            "cycling test",
            "battery cycling",
            "fuel cell test",
            "electrolyzer test",
            "photovoltaic test",
        ),
        "intervention": (
            "charge discharge",
            "current density",
            "voltage window",
            "thermal cycling",
            "load profile",
        ),
        "endpoint": (
            "energy density",
            "power density",
            "cycle life",
            "efficiency",
            "degradation",
        ),
    },
    {
        "id": ("22",),
        "match": (
            "engineering",
            "aerospace engineering",
            "biomedical engineering",
            "civil engineering",
            "electrical electronic engineering",
            "environmental engineering",
            "industrial engineering",
            "manufacturing engineering",
            "mechanical engineering",
            "instruments instrumentation",
            "mechanics",
            "transportation science technology",
        ),
        "design": (
            "prototype test",
            "finite element validation",
            "wind tunnel",
            "mechanical testing",
            "instrument calibration",
        ),
        "intervention": (
            "load test",
            "strain",
            "vibration input",
            "processing condition",
            "control parameter",
        ),
        "endpoint": (
            "failure mode",
            "reliability",
            "throughput",
            "dimensional accuracy",
            "mean time to failure",
        ),
    },
    {
        "id": ("23",),
        "match": (
            "environmental science",
            "environmental sciences",
            "environmental studies",
            "water resources",
            "limnology",
            "biodiversity conservation",
            "green sustainable science technology",
        ),
        "design": (
            "environmental monitoring",
            "water quality monitoring",
            "mesocosm",
            "ecotoxicity assay",
            "life cycle assessment",
        ),
        "intervention": (
            "pollutant exposure",
            "contaminant exposure",
            "remediation",
            "nutrient addition",
            "land use change",
        ),
        "endpoint": (
            "water quality",
            "contaminant concentration",
            "dissolved oxygen",
            "greenhouse gas emission",
            "species richness",
        ),
    },
    {
        "id": ("24",),
        "match": (
            "immunology and microbiology",
            "immunology",
            "microbiology",
            "infectious diseases",
            "virology",
            "mycology",
            "parasitology",
            "biotechnology applied microbiology",
        ),
        "design": (
            "infection model",
            "challenge model",
            "flow cytometry",
            "elisa",
            "plaque assay",
        ),
        "intervention": (
            "infection",
            "pathogen challenge",
            "stimulation",
            "inhibition",
            "antigen challenge",
        ),
        "endpoint": (
            "pathogen load",
            "viral load",
            "cytokine",
            "antibody titer",
            "t-cell response",
        ),
    },
    {
        "id": ("25",),
        "match": (
            "materials science",
            "biomaterials",
            "ceramics",
            "coatings films",
            "composites",
            "metallurgy metallurgical engineering",
            "nanoscience nanotechnology",
            "textiles",
        ),
        "design": (
            "characterization",
            "xrd",
            "sem",
            "tem",
            "mechanical testing",
        ),
        "intervention": (
            "doping",
            "annealing",
            "sintering",
            "composition",
            "surface treatment",
        ),
        "endpoint": (
            "tensile strength",
            "conductivity",
            "thermal stability",
            "porosity",
            "corrosion rate",
        ),
    },
    {
        "id": ("26",),
        "match": (
            "mathematics",
            "applied mathematics",
            "statistics probability",
            "mathematics interdisciplinary applications",
            "logic",
        ),
        "design": (
            "theorem",
            "proof",
            "counterexample",
            "convergence analysis",
            "numerical experiment",
        ),
        "intervention": (
            "regularization",
            "constraint relaxation",
            "perturbation",
            "initial condition",
            "boundary condition",
        ),
        "endpoint": (
            "error bound",
            "convergence rate",
            "regret",
            "approximation ratio",
            "statistical power",
        ),
    },
    {
        "id": ("27",),
        "match": (
            "medicine",
            "clinical neurology",
            "oncology",
            "hematology",
            "infectious diseases",
            "cardiovascular systems",
            "endocrinology metabolism",
            "gastroenterology hepatology",
            "surgery",
            "urology nephrology",
            "radiology nuclear medicine medical imaging",
            "medicine research experimental",
            "medicine general internal",
        ),
        "design": (
            "randomized trial",
            "clinical trial",
            "patient cohort",
            "case-control",
            "diagnostic accuracy",
        ),
        "intervention": (
            "treatment",
            "dose response",
            "drug exposure",
            "surgical intervention",
            "usual care",
        ),
        "endpoint": (
            "survival",
            "response rate",
            "toxicity incidence",
            "adverse event",
            "hazard ratio",
        ),
    },
    {
        "id": ("28",),
        "match": (
            "neuroscience",
            "neurosciences",
            "neuroimaging",
            "clinical neurology",
        ),
        "design": (
            "electrophysiology",
            "calcium imaging",
            "optogenetics",
            "neuroimaging",
            "animal model",
        ),
        "intervention": (
            "stimulation",
            "optogenetic stimulation",
            "inhibition",
            "lesion",
            "treatment",
        ),
        "endpoint": (
            "neural activity",
            "firing rate",
            "synaptic plasticity",
            "signal amplitude",
            "functional status",
        ),
    },
    {
        "id": ("29",),
        "match": (
            "nursing",
            "primary health care",
            "health care sciences services",
        ),
        "design": (
            "patient cohort",
            "pragmatic trial",
            "implementation trial",
            "quality improvement study",
            "clinical trial",
        ),
        "intervention": (
            "care protocol",
            "nursing intervention",
            "usual care",
            "rehabilitation protocol",
            "treatment",
        ),
        "endpoint": (
            "quality of life",
            "functional status",
            "adverse event",
            "readmission",
            "mortality",
        ),
    },
    {
        "id": ("30",),
        "match": (
            "pharmacology toxicology and pharmaceutics",
            "pharmacology pharmacy",
            "toxicology",
            "pharmaceutics",
            "medicinal chemistry",
        ),
        "design": (
            "dose response",
            "pk study",
            "pharmacokinetic study",
            "adme assay",
            "toxicology assay",
        ),
        "intervention": (
            "drug exposure",
            "dose escalation",
            "compound treatment",
            "formulation",
            "inhibitor",
        ),
        "endpoint": (
            "auc",
            "cmax",
            "clearance",
            "ic50",
            "toxicity incidence",
        ),
    },
    {
        "id": ("31",),
        "match": (
            "physics and astronomy",
            "physics",
            "astronomy astrophysics",
            "optics",
            "acoustics",
            "condensed matter",
            "fluids plasmas",
            "nuclear physics",
            "particles fields",
            "quantum science technology",
        ),
        "design": (
            "spectroscopy",
            "scattering experiment",
            "interferometry",
            "detector calibration",
            "simulation study",
        ),
        "intervention": (
            "magnetic field",
            "electric field",
            "laser pulse",
            "temperature",
            "pressure",
        ),
        "endpoint": (
            "cross section",
            "phase transition",
            "conductivity",
            "band gap",
            "signal to noise",
        ),
    },
    {
        "id": ("34",),
        "match": (
            "veterinary",
            "veterinary sciences",
            "zoology",
            "animal health",
        ),
        "design": (
            "animal model",
            "feeding trial",
            "challenge model",
            "clinical trial",
            "case series",
        ),
        "intervention": (
            "treatment",
            "pathogen challenge",
            "feeding intervention",
            "drug exposure",
            "husbandry intervention",
        ),
        "endpoint": (
            "weight gain",
            "pathogen load",
            "mortality",
            "morbidity",
            "immune response",
        ),
    },
    {
        "id": ("35",),
        "match": (
            "dentistry",
            "oral surgery medicine",
            "dental",
            "periodontal",
            "orthodontic",
        ),
        "design": (
            "randomized trial",
            "split-mouth trial",
            "implant trial",
            "clinical trial",
            "mechanical testing",
        ),
        "intervention": (
            "treatment",
            "surface treatment",
            "implant placement",
            "bonding protocol",
            "usual care",
        ),
        "endpoint": (
            "implant survival",
            "periodontal pocket depth",
            "plaque index",
            "caries incidence",
            "bond strength",
        ),
    },
    {
        "id": ("36",),
        "match": (
            "health professions",
            "health care sciences services",
            "health policy services",
            "medical informatics",
            "rehabilitation",
            "sport sciences",
        ),
        "design": (
            "clinical trial",
            "diagnostic accuracy",
            "rehabilitation trial",
            "implementation trial",
            "patient cohort",
        ),
        "intervention": (
            "care protocol",
            "rehabilitation protocol",
            "treatment",
            "training program",
            "usual care",
        ),
        "endpoint": (
            "functional status",
            "mobility",
            "pain score",
            "quality of life",
            "diagnostic sensitivity",
        ),
    },
)

_DISCIPLINE_ADVERSE_QUERY_PROFILES: tuple[dict[str, tuple[str, ...]], ...] = (
    {
        "id": ("11", "23",),
        "match": (
            "agricultural and biological sciences",
            "agronomy",
            "agriculture",
            "ecology",
            "biodiversity conservation",
            "plant sciences",
            "soil science",
            "forestry",
            "fisheries",
            "marine freshwater biology",
            "environmental science",
            "environmental sciences",
            "environmental studies",
            "water resources",
            "limnology",
            "green sustainable science technology",
        ),
        "adverse": (
            "yield penalty",
            "biodiversity loss",
            "nutrient runoff",
            "pesticide resistance",
            "ecotoxicity",
            "leakage displacement",
            "burden shifting",
        ),
    },
    {
        "id": ("13", "24",),
        "match": (
            "biochemistry genetics and molecular biology",
            "molecular biology",
            "genetics heredity",
            "cell biology",
            "immunology and microbiology",
            "immunology",
            "microbiology",
            "infectious diseases",
            "virology",
            "biotechnology applied microbiology",
        ),
        "adverse": (
            "off-target effect",
            "compensatory pathway",
            "escape mutation",
            "immune escape",
            "fitness cost",
            "cytotoxicity",
            "null effect",
        ),
    },
    {
        "id": ("15", "16", "21", "23",),
        "match": (
            "chemical engineering",
            "chemistry",
            "analytical chemistry",
            "organic chemistry",
            "physical chemistry",
            "electrochemistry",
            "energy",
            "energy fuels",
            "petroleum engineering",
            "environmental engineering",
            "green sustainable science technology",
        ),
        "adverse": (
            "deactivation",
            "degradation",
            "byproduct formation",
            "lower selectivity",
            "energy penalty",
            "life cycle burden",
            "increased emissions",
        ),
    },
    {
        "id": ("17", "26",),
        "match": (
            "computer science",
            "artificial intelligence",
            "machine learning",
            "information systems",
            "software engineering",
            "robotics",
            "mathematics",
            "statistics probability",
            "applied mathematics",
        ),
        "adverse": (
            "distribution shift",
            "out-of-distribution failure",
            "robustness failure",
            "fairness degradation",
            "performance regression",
            "compute cost",
            "negative transfer",
        ),
    },
    {
        "id": ("19", "23",),
        "match": (
            "earth and planetary sciences",
            "geology",
            "geochemistry geophysics",
            "geosciences",
            "meteorology atmospheric sciences",
            "oceanography",
            "remote sensing",
            "environmental science",
            "environmental studies",
        ),
        "adverse": (
            "regional heterogeneity",
            "model bias",
            "uncertainty propagation",
            "false hotspot",
            "burden shifting",
            "leakage displacement",
            "rebound effect",
        ),
    },
    {
        "id": ("22", "25", "31",),
        "match": (
            "engineering",
            "aerospace engineering",
            "biomedical engineering",
            "civil engineering",
            "electrical electronic engineering",
            "industrial engineering",
            "manufacturing engineering",
            "mechanical engineering",
            "materials science",
            "biomaterials",
            "composites",
            "metallurgy metallurgical engineering",
            "physics and astronomy",
            "physics",
        ),
        "adverse": (
            "failure mode",
            "reliability loss",
            "fatigue",
            "corrosion",
            "degradation",
            "thermal runaway",
            "manufacturing defect",
        ),
    },
    {
        "id": ("27", "29", "30", "34", "35", "36",),
        "match": (
            "medicine",
            "clinical neurology",
            "oncology",
            "hematology",
            "surgery",
            "nursing",
            "primary health care",
            "pharmacology toxicology and pharmaceutics",
            "pharmacology pharmacy",
            "toxicology",
            "pharmaceutics",
            "veterinary",
            "dentistry",
            "health professions",
            "medical informatics",
            "rehabilitation",
        ),
        "adverse": (
            "adverse event",
            "toxicity",
            "nonresponse",
            "treatment resistance",
            "dose-limiting toxicity",
            "off-target effect",
            "clinical deterioration",
        ),
    },
    {
        "id": ("28",),
        "match": (
            "neuroscience",
            "neurosciences",
            "neuroimaging",
            "clinical neurology",
        ),
        "adverse": (
            "adverse event",
            "neurotoxicity",
            "off-target effect",
            "compensatory plasticity",
            "behavioral impairment",
            "signal artifact",
            "null effect",
        ),
    },
)

_LOW_INFORMATION_QUERY_AXIS_TERMS = frozenset({
    "cell",
    "cells",
    "immune",
    "response",
    "responses",
    "role",
    "effect",
    "effects",
    "activation",
    "efficacy",
    "platform",
    "platforms",
    "development",
})


# These are not forbidden scientific words.  They are, however, too broad to
# identify an input, mechanism, outcome, object alias, or evidence path by
# themselves.  For example, ``transistor density`` can be informative because
# of ``transistor``; ``density`` and ``information`` alone cannot establish a
# retrievable causal axis. Keeping this list small and domain-neutral is
# important: it is a contract-quality check, not an ontology for any field.
_CONTRACT_AXIS_NONIDENTIFYING_TOKENS = frozenset({
    "amount", "change", "data", "density", "factor", "information",
    "level", "levels", "rate", "rates", "speed", "state", "states",
    "time", "times", "type", "types", "value", "values", "variable",
    "variables",
})


# An LLM metadata-refinement query may use only terms from the active contract
# or terms explicitly observed in the small diagnostic paper batch. Generic
# retrieval scaffolding is never an admissible addition in that route.
_CALIBRATION_REFINEMENT_GENERIC_TOKENS = frozenset({
    "and", "or", "not", "article", "comparison", "control", "controls",
    "controlled", "derivation", "experiment", "experiments", "formal",
    "framework", "model", "models", "paper", "papers", "query", "queries",
    "review", "reviews", "search", "study", "studies", "theoretical",
    "validation",
})


_REASSESSMENT_CHANGE_LEVELS = frozenset({
    "retrieval_only", "evidence_path", "scientific_contract",
})


def _reassessment_text(value: Any, *, limit: int = 800) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())[:limit]


def _reassessment_query_entries(source: dict[str, Any]) -> list[dict[str, Any]]:
    """Normalize an LLM retrieval strategy without making it a SH mutation."""

    strategy = source.get("retrieval_strategy")
    raw_queries = strategy.get("queries") if isinstance(strategy, dict) else source.get("queries")
    if not isinstance(raw_queries, list):
        # Accept the pre-v2 shape as one retrieval-only branch.  It is still
        # validated below and is never applied to the scientific contract.
        raw_queries = [{"query": source.get("retrieval_query")}]
    entries: list[dict[str, Any]] = []
    for raw in raw_queries[:5]:
        if not isinstance(raw, dict):
            continue
        query = _reassessment_text(raw.get("query") or raw.get("retrieval_query"))
        if not query:
            continue
        entries.append({
            "query": query,
            "target_layer": _reassessment_text(raw.get("target_layer"), limit=40) or "L4_regular",
            "target_lane": _reassessment_text(raw.get("target_lane"), limit=80) or "MECHANISM_DISCOVERY",
            "evidence_path_role": _reassessment_text(raw.get("evidence_path_role"), limit=80),
            "rationale": _reassessment_text(raw.get("rationale"), limit=400),
        })
    return entries


def validate_low_admission_subhypothesis_reassessment(
    payload: dict[str, Any],
    *,
    sub_hypothesis: dict[str, Any],
    alignment_contract: dict[str, Any],
    allow_scientific_contract: bool = False,
) -> dict[str, Any]:
    """Validate a reassessment without silently changing the active contract.

    Retrieval scarcity is normally a search-space problem, not proof that the
    causal model is wrong.  Retrieval-only and evidence-path revisions may
    create new query branches.  A proposed scientific-contract revision is
    persisted only as a ``shadow_required`` candidate and cannot mutate the
    active sub-hypothesis, alignment contract, or evidence gate.
    """

    source = payload if isinstance(payload, dict) else {}
    reasons: list[str] = []
    change_level = str(source.get("change_level") or "retrieval_only").strip().lower()
    if change_level not in _REASSESSMENT_CHANGE_LEVELS:
        reasons.append("unsupported_change_level")

    preserved_scope = source.get("preserved_scope") if isinstance(source.get("preserved_scope"), dict) else {}
    immutable_pairs = {
        "focus": _reassessment_text(sub_hypothesis.get("focus"), limit=420),
        "scientific_object": _reassessment_text(alignment_contract.get("scientific_object"), limit=420),
    }
    for key, expected in immutable_pairs.items():
        supplied = _reassessment_text(preserved_scope.get(key) or source.get(key), limit=420)
        if supplied and expected and supplied != expected:
            reasons.append(f"immutable_{key}_changed")
    expected_exclusions = [
        _reassessment_text(value, limit=240).lower()
        for value in (alignment_contract.get("excluded_nearby_objects") or [])
        if _reassessment_text(value, limit=240)
    ]
    supplied_exclusions = preserved_scope.get("excluded_nearby_objects")
    if supplied_exclusions is not None:
        normalized_supplied = [
            _reassessment_text(value, limit=240).lower()
            for value in supplied_exclusions
            if _reassessment_text(value, limit=240)
        ] if isinstance(supplied_exclusions, list) else []
        if normalized_supplied != expected_exclusions:
            reasons.append("immutable_exclusions_changed")

    retrieval_queries = _reassessment_query_entries(source)
    if change_level in {"retrieval_only", "evidence_path"} and not retrieval_queries:
        reasons.append("retrieval_strategy_missing")
    original_signature = scientific_query_signature(sub_hypothesis.get("retrieval_query"))
    query_signatures: set[str] = set()
    for item in retrieval_queries:
        query = str(item.get("query") or "")
        signature = scientific_query_signature(query)
        if len(query.split()) < 4 or re.search(r"[\u3400-\u9fff\uf900-\ufaff]", query):
            reasons.append("retrieval_query_invalid")
        if not signature or signature == original_signature or signature in query_signatures:
            reasons.append("retrieval_query_not_materially_novel")
        query_signatures.add(signature)

    invariants = source.get("invariants") if isinstance(source.get("invariants"), dict) else {}
    required_invariants = (
        "parent_decision_link_preserved",
        "exclusive_objects_preserved",
        "outcome_preserved_or_explicitly_revised",
        "no_cross_sh_object_leakage",
    )
    scientific_contract_patch = (
        source.get("scientific_contract_patch")
        if isinstance(source.get("scientific_contract_patch"), dict)
        else {}
    )
    if change_level == "scientific_contract":
        if not allow_scientific_contract:
            reasons.append("scientific_contract_revision_not_justified_by_diagnostics")
        if not scientific_contract_patch:
            reasons.append("scientific_contract_patch_missing")
        for key in required_invariants:
            if invariants.get(key) is not True:
                reasons.append(f"scientific_contract_invariant_failed:{key}")
        # A contract patch describes a candidate only.  Keep the allowable
        # surface explicit so unrelated SH fields cannot hitch a ride.
        allowed_patch_fields = {
            "parent_decision_link", "constraint_type", "pivotal_mechanism",
            "supporting_mediators", "outcome", "boundary_conditions",
            "confounders_or_alternatives", "rationale",
        }
        unexpected = set(scientific_contract_patch) - allowed_patch_fields
        if unexpected:
            reasons.append("scientific_contract_patch_contains_unsupported_fields")

    return {
        "schema_version": "subhypothesis_reassessment_v2",
        "valid": not reasons,
        "rejection_reasons": list(dict.fromkeys(reasons)),
        "change_level": change_level,
        "retrieval_queries": retrieval_queries if not reasons else [],
        "scientific_contract_patch": scientific_contract_patch if change_level == "scientific_contract" and not reasons else {},
        "invariants": {key: invariants.get(key) is True for key in required_invariants},
        "preserved_scope": {
            "focus": immutable_pairs["focus"],
            "scientific_object": immutable_pairs["scientific_object"],
            "excluded_nearby_objects": list(alignment_contract.get("excluded_nearby_objects") or []),
        },
        "removed_generic_terms": [
            _reassessment_text(value, limit=80)
            for value in (source.get("removed_generic_terms") or [])
            if _reassessment_text(value, limit=80)
        ][:12],
        "added_specific_terms": [
            _reassessment_text(value, limit=80)
            for value in (source.get("added_specific_terms") or [])
            if _reassessment_text(value, limit=80)
        ][:12],
        "rationale": _reassessment_text(source.get("rationale"), limit=800),
        "application_policy": (
            "query_branches_only"
            if change_level in {"retrieval_only", "evidence_path"}
            else "shadow_required_no_active_contract_mutation"
        ),
    }


def subhypothesis_full_text_gate_contract(
    *,
    total_target: int = 10,
    direct_core_target: int = 1,
    foundation_required: bool = False,
) -> dict[str, Any]:
    """Return the two-invariant SH corpus gate.

    Readiness requires the configured related-full-text total (10 in normal
    runs).  Direct/compatible core evidence controls claim strength and gap
    wording, but it must not block a sub-hypothesis from entering downstream
    gap analysis once the related full-text corpus is sufficient.
    """

    total = max(
        1,
        min(
            SUBHYPOTHESIS_IMPORTED_FULL_TEXT_TARGET,
            int(total_target or SUBHYPOTHESIS_IMPORTED_FULL_TEXT_TARGET),
        ),
    )
    recommended_direct = max(1, min(total, int(direct_core_target or 1)))
    direct = 1
    layer_minimums = {layer: 0 for layer in NON_PREPRINT_LAYERS}
    preferred_targets = {
        "L0_review": min(total, 2),
        "L1_milestone": 1 if foundation_required and total >= 2 else 0,
        "L2_top_latest": min(total, 4),
        "L4_regular": min(total, 8),
    }
    return {
        "schema_version": "subhypothesis_full_text_gate_v7",
        "imported_full_text_target": total,
        "imported_related_full_text_target": total,
        "peer_reviewed_full_text_target": total,
        "direct_core_full_text_target": direct,
        "direct_contract_core_target": 1,
        "recommended_direct_core_full_text_target": recommended_direct,
        "evidence_portfolio_policy_active": total >= SUBHYPOTHESIS_IMPORTED_FULL_TEXT_TARGET,
        "evidence_portfolio_minimums": dict(
            SUBHYPOTHESIS_EVIDENCE_PORTFOLIO_MINIMUMS
        ),
        "evidence_portfolio_policy": (
            "The related-full-text total is the only workflow-blocking "
            "invariant. Direct/compatible core and evidence-role diversity "
            "are claim-strength and quality diagnostics."
        ),
        "review_peer_reviewed_total_cap": min(total, 2),
        "review_gate_policy": (
            "Usable, related reviews count toward the corpus total; review "
            "concentration remains a non-blocking quality diagnostic."
        ),
        "layer_minimums": layer_minimums,
        "layer_preferred_targets": preferred_targets,
        "flexible_layers": ["L2_top_latest", "L4_regular"],
        "flexible_slots": total,
        "preprint_policy": "INDEPENDENT_SIGNAL_NOT_COUNTED",
        "paper_admission": [
            "full_text_acquired",
            "subhypothesis_alignment_passes",
            "research_object_matches",
            "at_least_one_declared_relevance_axis_matches",
            "not_explicitly_excluded_or_true_off_topic",
            "project_unique_paper_identity",
        ],
    }


def _subhypothesis_annotation(source: dict[str, Any]) -> dict[str, Any]:
    for key in ("annotation", "hypothesis_annotation"):
        value = source.get(key) if isinstance(source, dict) else {}
        if isinstance(value, dict) and value:
            return value
    return {}


def _attach_subhypothesis_gate_context(
    gate: dict[str, Any],
    sub_hypothesis: dict[str, Any],
) -> dict[str, Any]:
    gate = dict(gate)
    source = sub_hypothesis if isinstance(sub_hypothesis, dict) else {}
    audit = (
        source.get("object_maturity_resolution")
        if isinstance(source.get("object_maturity_resolution"), dict)
        else source.get("object_maturity_preflight")
        if isinstance(source.get("object_maturity_preflight"), dict)
        else source.get("object_maturity_audit")
        if isinstance(source.get("object_maturity_audit"), dict)
        else {}
    )
    object_contract = (
        source.get("scientific_object_contract_audit")
        if isinstance(source.get("scientific_object_contract_audit"), dict)
        else {}
    )
    if object_contract:
        gate["scientific_object_contract_audit"] = dict(object_contract)
        gate["object_contract_valid"] = bool(object_contract.get("valid") is True)
        if object_contract.get("valid") is False:
            gate["object_contract_error"] = str(
                object_contract.get("error_code")
                or object_contract.get("error")
                or ""
            )
    if audit:
        gate["object_maturity_audit"] = dict(audit)
    if source.get("object_maturity_status") or audit.get("object_status"):
        gate["object_maturity_status"] = str(
            source.get("object_maturity_status")
            or audit.get("object_status")
            or audit.get("status")
            or ""
        )
    if source.get("object_maturity_retrieval_mode") or audit.get("retrieval_mode"):
        gate["object_maturity_retrieval_mode"] = str(
            source.get("object_maturity_retrieval_mode")
            or audit.get("retrieval_mode")
            or ""
        )
    if (
        source.get("direct_core_evidence_allowed") is False
        or audit.get("direct_core_evidence_allowed") is False
    ):
        gate["direct_core_evidence_allowed"] = False
        # A non-direct object cannot both forbid direct-core evidence and
        # require a direct-core quota.  Preserve the count as a diagnostic in
        # coverage, but make the requirement explicitly not applicable.
        gate["direct_core_full_text_target"] = 0
        gate["direct_contract_core_target"] = 0
        gate["compatible_direct_core_target"] = 0
        gate["direct_core_requirement_state"] = "NOT_APPLICABLE_OBJECT_REWRITE_OR_BRIDGE"
    elif source.get("direct_core_evidence_allowed") is True:
        gate["direct_core_evidence_allowed"] = True
    return gate


def subhypothesis_full_text_gate_contract_for_standard(
    sub_hypothesis: dict[str, Any],
    *,
    default_total_target: int,
    default_direct_core_target: int,
    foundation_required: bool = False,
) -> dict[str, Any]:
    """Return a per-SH v7 gate with field standards as diagnostics."""

    sub_hypothesis = sub_hypothesis if isinstance(sub_hypothesis, dict) else {}
    annotation = _subhypothesis_annotation(sub_hypothesis)
    question_context = _research_question_retrieval_context(annotation)
    standard_id = str(annotation.get("evidence_standard_id") or "").strip()
    if not standard_id:
        gate = _attach_subhypothesis_gate_context(
            subhypothesis_full_text_gate_contract(
                total_target=default_total_target,
                direct_core_target=default_direct_core_target,
                foundation_required=foundation_required,
            ),
            sub_hypothesis,
        )
        gate.update(question_context)
        return gate
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
    hypothesis_type = str(annotation.get("hypothesis_type") or sub_hypothesis.get("hypothesis_type") or "")
    normalized_standard_id = normalize_evidence_standard_id(
        standard_id,
        hypothesis_type=hypothesis_type,
    )
    policy = evidence_standard_retrieval_policy(
        normalized_standard_id,
        hypothesis_type=hypothesis_type,
    )
    requested_standard_ids = annotation.get("evidence_standard_ids") or sub_hypothesis.get("evidence_standard_ids") or []
    if isinstance(requested_standard_ids, str):
        requested_standard_ids = [requested_standard_ids]
    standard_ids: list[str] = []
    for value in [normalized_standard_id, *requested_standard_ids]:
        normalized_id = normalize_evidence_standard_id(value, hypothesis_type=hypothesis_type)
        if normalized_id and normalized_id not in standard_ids:
            standard_ids.append(normalized_id)
    standard_policies = {
        standard: evidence_standard_retrieval_policy(standard, hypothesis_type=hypothesis_type)
        for standard in standard_ids
    }
    combined_core_designs = list(dict.fromkeys(
        design
        for standard_policy in standard_policies.values()
        for design in (standard_policy.get("accepted_core_designs") or [])
    ))
    evidence_requirements = (
        sub_hypothesis.get("evidence_requirements")
        if isinstance(sub_hypothesis.get("evidence_requirements"), dict)
        else {}
    )
    default_total = max(
        1,
        min(
            SUBHYPOTHESIS_IMPORTED_FULL_TEXT_TARGET,
            int(default_total_target or SUBHYPOTHESIS_IMPORTED_FULL_TEXT_TARGET),
        ),
    )
    default_direct = max(1, int(default_direct_core_target or 10))
    standard_total = max(1, int(policy.get("peer_reviewed_full_text_target") or default_total))
    standard_core = max(1, int(policy.get("direct_core_full_text_target") or default_direct))
    # A normal caller default must not erase the standard-specific target, but
    # persisted or caller-expanded larger contracts are migrated down to the
    # current 10-full-text standard.
    total = min(
        SUBHYPOTHESIS_IMPORTED_FULL_TEXT_TARGET,
        max(standard_total, default_total),
    )
    recommended_standard_core_target = min(total, standard_core)
    gate = subhypothesis_full_text_gate_contract(
        total_target=total,
        direct_core_target=default_direct,
        foundation_required=foundation_required,
    )
    gate.update(
        {
            "schema_version": "subhypothesis_full_text_gate_v7",
            "evidence_standard_id": normalized_standard_id,
            "evidence_standard_ids": standard_ids,
            "epistemic_profile": (
                annotation.get("epistemic_profile")
                if isinstance(annotation.get("epistemic_profile"), dict)
                else sub_hypothesis.get("epistemic_profile")
                if isinstance(sub_hypothesis.get("epistemic_profile"), dict)
                else {}
            ),
            "hypothesis_type": hypothesis_type,
            "standard_core_full_text_target": 1,
            "recommended_standard_core_full_text_target": (
                recommended_standard_core_target
            ),
            "standard_core_designs": combined_core_designs,
            "evidence_standard_definitions": [
                {"id": standard, "accepted_core_designs": list(standard_policy.get("accepted_core_designs") or [])}
                for standard, standard_policy in standard_policies.items()
            ],
            "standard_anchor_minimums": {
                str(key): max(0, int(value or 0))
                for key, value in evidence_requirements.items()
                if str(key).endswith("_anchor_min")
            },
            "support_designs": list(policy.get("support_designs") or []),
            "required_evidence_properties": list(policy.get("required_properties") or []),
            "preferred_evidence_properties": list(policy.get("preferred_properties") or []),
            "not_sufficient_alone": list(policy.get("not_sufficient_alone") or []),
            "excluded_as_core": ["narrative_review", "commentary", "preprint_only"],
            "claim_strength_cap": str(policy.get("claim_strength_cap") or ""),
            "claim_strength_notes": str(policy.get("claim_strength_notes") or ""),
            "readiness_core_metric": "compatible_direct_core",
            "compatibility_policy": (
                "v7 readiness records claim-compatible direct-core tests as "
                "claim-strength diagnostics. They do not block workflow once "
                "the related full-text corpus target is met."
            ),
            **question_context,
        }
    )
    gate["paper_admission"] = list(gate.get("paper_admission") or []) + [
        "standard_core_design_matches_evidence_standard",
        "claim_strength_capped_by_evidence_standard",
    ]
    return _attach_subhypothesis_gate_context(gate, sub_hypothesis)


def normalize_subhypothesis_full_text_gate_contract(
    gate_contract: dict[str, Any] | None,
) -> dict[str, Any]:
    """Normalize an active gate to the v7 two-invariant readiness policy.

    This normalizes a gate selected for the current run; it deliberately does
    not reconstitute a missing alignment contract or scientific evidence graph.
    """

    if not isinstance(gate_contract, dict) or not gate_contract:
        return subhypothesis_full_text_gate_contract()
    gate = dict(gate_contract)
    schema_version = str(gate.get("schema_version") or "")
    if schema_version != "subhypothesis_full_text_gate_v7":
        replacement = subhypothesis_full_text_gate_contract()
        replacement["contract_rebuild_required"] = True
        replacement["contract_rebuild_reason"] = "noncurrent_full_text_gate_schema"
        replacement["received_schema_version"] = schema_version or "unversioned"
        return replacement
    is_standard_gate = bool(
        gate.get("evidence_standard_id")
        or schema_version in {
            "subhypothesis_full_text_gate_v6",
            "subhypothesis_full_text_gate_v7",
        }
        and gate.get("standard_core_full_text_target") is not None
    )
    layer_minimums = {
        layer: max(0, int((gate.get("layer_minimums") or {}).get(layer) or 0))
        for layer in NON_PREPRINT_LAYERS
    }
    layer_minimums = {layer: 0 for layer in NON_PREPRINT_LAYERS}
    gate["schema_version"] = "subhypothesis_full_text_gate_v7"
    gate["layer_minimums"] = layer_minimums
    preferred = dict(gate.get("layer_preferred_targets") or {})
    preferred.setdefault("L0_review", min(int(gate.get("peer_reviewed_full_text_target") or SUBHYPOTHESIS_IMPORTED_FULL_TEXT_TARGET), 2))
    preferred.setdefault("L1_milestone", 0)
    preferred.setdefault("L2_top_latest", min(int(gate.get("peer_reviewed_full_text_target") or SUBHYPOTHESIS_IMPORTED_FULL_TEXT_TARGET), 4))
    preferred.setdefault("L4_regular", min(int(gate.get("peer_reviewed_full_text_target") or SUBHYPOTHESIS_IMPORTED_FULL_TEXT_TARGET), 8))
    gate["layer_preferred_targets"] = preferred
    total = max(
        1,
        min(
            SUBHYPOTHESIS_IMPORTED_FULL_TEXT_TARGET,
            int(
                gate.get("imported_full_text_target")
                or gate.get("peer_reviewed_full_text_target")
                or SUBHYPOTHESIS_IMPORTED_FULL_TEXT_TARGET
            ),
        ),
    )
    portfolio_policy_active = bool(
        gate.get("evidence_portfolio_policy_active")
        or total >= SUBHYPOTHESIS_IMPORTED_FULL_TEXT_TARGET
    )
    if portfolio_policy_active:
        total = min(SUBHYPOTHESIS_IMPORTED_FULL_TEXT_TARGET, total)
    gate["imported_full_text_target"] = total
    gate["imported_related_full_text_target"] = total
    gate["peer_reviewed_full_text_target"] = total
    gate["evidence_portfolio_policy_active"] = portfolio_policy_active
    portfolio_minimums = dict(gate.get("evidence_portfolio_minimums") or {})
    for role, minimum in SUBHYPOTHESIS_EVIDENCE_PORTFOLIO_MINIMUMS.items():
        portfolio_minimums[role] = max(
            int(minimum),
            int(portfolio_minimums.get(role) or 0),
        )
    gate["evidence_portfolio_minimums"] = portfolio_minimums
    gate.setdefault(
        "evidence_portfolio_policy",
        "10 unique imported non-preprint related full texts. Direct/compatible core and diversified auxiliary evidence roles are quality diagnostics, not workflow blockers.",
    )
    review_cap_raw = gate.get("review_peer_reviewed_total_cap")
    try:
        review_cap = int(review_cap_raw) if review_cap_raw is not None else 2
    except (TypeError, ValueError):
        review_cap = 2
    gate["review_peer_reviewed_total_cap"] = max(0, min(total, review_cap))
    gate.setdefault(
        "review_gate_policy",
        "L0/review full text above this cap remains context-only and does not satisfy peer-reviewed total readiness.",
    )
    direct_core_not_applicable = gate.get("direct_core_evidence_allowed") is False
    previous_direct_target = (
        0 if direct_core_not_applicable else max(
            1,
            min(total, int(gate.get("direct_core_full_text_target") or 1)),
        )
    )
    gate.setdefault(
        "recommended_direct_core_full_text_target",
        previous_direct_target,
    )
    gate["direct_core_full_text_target"] = 0 if direct_core_not_applicable else 1
    gate["direct_contract_core_target"] = 0 if direct_core_not_applicable else 1
    gate["compatible_direct_core_target"] = 0 if direct_core_not_applicable else 1
    if is_standard_gate:
        previous_standard_target = max(
            1,
            min(
                total,
                int(gate.get("standard_core_full_text_target") or 1),
            ),
        )
        gate.setdefault(
            "recommended_standard_core_full_text_target",
            previous_standard_target,
        )
        gate["standard_core_full_text_target"] = 1
        gate.setdefault("standard_core_designs", [])
        gate.setdefault("support_designs", [])
        gate.setdefault("required_evidence_properties", [])
        gate.setdefault("preferred_evidence_properties", [])
        gate.setdefault("not_sufficient_alone", [])
        gate.setdefault("excluded_as_core", ["narrative_review", "commentary", "preprint_only"])
        gate.setdefault("claim_strength_cap", "")
        gate.setdefault("claim_strength_notes", "")
        gate["readiness_core_metric"] = "compatible_direct_core"
    gate["flexible_slots"] = total
    gate.setdefault("flexible_layers", ["L2_top_latest", "L4_regular"])
    return gate


def _normalized_subhypothesis_id(value: Any) -> str:
    match = re.search(r"(?<![A-Za-z0-9])SH\d+(?![A-Za-z0-9])", str(value or ""), flags=re.IGNORECASE)
    return match.group(0).upper() if match else ""


def _record_layer(record: dict[str, Any], binding: dict[str, Any]) -> str:
    context = record.get("import_context") if isinstance(record.get("import_context"), dict) else {}
    return str(
        binding.get("stratified_layer")
        or record.get("stratified_layer")
        or context.get("stratified_layer")
        or "L4_regular"
    )


def _record_binding(record: dict[str, Any], sub_hypothesis_id: str) -> dict[str, Any]:
    sub_id = _normalized_subhypothesis_id(sub_hypothesis_id)
    bindings = record.get("subhypothesis_bindings") if isinstance(record.get("subhypothesis_bindings"), list) else []
    for item in bindings:
        if not isinstance(item, dict):
            continue
        if _normalized_subhypothesis_id(item.get("sub_hypothesis_id")) == sub_id:
            return dict(item)

    context = record.get("import_context") if isinstance(record.get("import_context"), dict) else {}
    alignment = record.get("alignment_assessment") if isinstance(record.get("alignment_assessment"), dict) else {}
    possible = [
        record.get("retrieval_branch"),
        record.get("sub_hypothesis_id"),
        context.get("query_branch"),
        context.get("primary_query_branch"),
        *(context.get("matched_query_branches") or []),
        alignment.get("sub_hypothesis_id"),
    ]
    if sub_id and any(_normalized_subhypothesis_id(value) == sub_id for value in possible):
        return {
            "sub_hypothesis_id": sub_id,
            "stratified_layer": _record_layer(record, {}),
            "alignment_assessment": alignment,
            "evidence_kind": str(record.get("evidence_kind") or context.get("evidence_kind") or ""),
        }
    return {}


def _paper_identity(record: dict[str, Any]) -> str:
    try:
        from ._literature_retrieval_foundation import canonical_paper_identity
    except ImportError:
        from _literature_retrieval_foundation import canonical_paper_identity
    identity = canonical_paper_identity(record)
    key = str(identity.get("canonical_key") or "")
    if key:
        return key
    return str(record.get("unique_key") or record.get("paper_id") or record.get("title") or "")


def _is_unpublished_preprint(record: dict[str, Any], layer: str) -> bool:
    if layer == "L3_preprint":
        return True
    try:
        from ._literature_search import is_preprint_literature_result
    except ImportError:
        from _literature_search import is_preprint_literature_result
    return bool(is_preprint_literature_result(record))


def _is_review(record: dict[str, Any], layer: str, alignment: dict[str, Any]) -> bool:
    genre = record.get("paper_genre") if isinstance(record.get("paper_genre"), dict) else {}
    alignment_genre = alignment.get("paper_genre") if isinstance(alignment.get("paper_genre"), dict) else {}
    label = " ".join(
        str(value or "")
        for value in (
            genre.get("genre"), genre.get("research_design"),
            alignment_genre.get("genre"), alignment_genre.get("research_design"),
            record.get("publication_type"),
        )
    ).lower()
    return layer == "L0_review" or bool(genre.get("is_review")) or "review" in label or "meta-analysis" in label


def _alignment_for_binding(record: dict[str, Any], binding: dict[str, Any]) -> dict[str, Any]:
    bound = binding.get("alignment_assessment") if isinstance(binding.get("alignment_assessment"), dict) else {}
    if bound:
        return bound
    return record.get("alignment_assessment") if isinstance(record.get("alignment_assessment"), dict) else {}


def _alignment_contract_for_subhypothesis(
    project: dict[str, Any],
    sub_hypothesis_id: str,
) -> dict[str, Any]:
    """Load the active V2 research-question contract for an SH.

    Retrieval coverage consumes the type-directed research-question contract,
    never the retired alignment-card causal graph.  Missing V2 declaration is
    therefore a configuration error rather than a reason to reconstruct a
    historical mechanism template.
    """

    try:
        from ._research_question_contract import validate_research_question_contract
    except ImportError:
        from _research_question_contract import validate_research_question_contract
    for item in project.get("sub_hypotheses") or []:
        if not isinstance(item, dict) or str(item.get("id") or "") != sub_hypothesis_id:
            continue
        annotation = _subhypothesis_annotation(item)
        candidate = annotation.get("research_question_contract") if isinstance(annotation.get("research_question_contract"), dict) else item.get("research_question_contract")
        try:
            return validate_research_question_contract(candidate)
        except (TypeError, ValueError):
            return {}
    return {}


def _research_question_retrieval_context(annotation: dict[str, Any]) -> dict[str, Any]:
    """Expose the V3 SH slot plan to the retrieval gate without a fallback.

    The evidence-standard policy controls corpus size and source quality. This
    context controls which claims and disconfirming evidence the current SH
    may seek. It never substitutes a causal-chain template when the V3
    research-question contract is absent.
    """
    annotation = annotation if isinstance(annotation, dict) else {}
    contract = (
        annotation.get("research_question_contract")
        if isinstance(annotation.get("research_question_contract"), dict)
        else {}
    )
    try:
        from ._research_question_contract import (
            RESEARCH_QUESTION_RETRIEVAL_PLAN_VERSION,
            build_question_retrieval_plan,
            validate_research_question_contract,
        )
    except ImportError:
        from _research_question_contract import (
            RESEARCH_QUESTION_RETRIEVAL_PLAN_VERSION,
            build_question_retrieval_plan,
            validate_research_question_contract,
        )
    try:
        contract = validate_research_question_contract(contract)
        contract_valid = True
    except (TypeError, ValueError):
        contract_valid = False
    plan = build_question_retrieval_plan(contract) if contract_valid else {}
    plan_valid = plan.get("schema_version") == RESEARCH_QUESTION_RETRIEVAL_PLAN_VERSION
    if not contract_valid or not plan_valid:
        return {
            "research_question_evidence_status": "V3_RESEARCH_QUESTION_PLAN_REQUIRED",
            "research_question_contract_id": "",
            "research_question_kind": "",
            "research_question_slot_tasks": [],
            "research_question_no_result_rule": "No literature absence may be interpreted as a gap until a V3 plan is available.",
        }
    return {
        "research_question_evidence_status": "V3_RESEARCH_QUESTION_PLAN_BOUND",
        "research_question_contract_id": str(contract.get("contract_id") or ""),
        "research_question_kind": str((contract.get("research_question") or {}).get("question_kind") or ""),
        "research_question_required_slots": list((contract.get("evidence_contract") or {}).get("required_slots") or []),
        "research_question_required_comparability_axes": list((contract.get("evidence_contract") or {}).get("required_comparability_axes") or []),
        "research_question_slot_tasks": [
            {
                "slot": str(task.get("slot") or ""),
                "provider_query": str(
                    (task.get("retrieval_spec_v3") or {}).get("provider_query") or ""
                ),
                "query_fingerprint": str(
                    (task.get("retrieval_spec_v3") or {}).get("semantic_fingerprint") or ""
                ),
                "required_source_role": str(task.get("required_source_role") or ""),
            }
            for task in plan.get("slot_tasks", [])
            if isinstance(task, dict)
        ],
        "research_question_tasks": [
            dict(task)
            for task in plan.get("research_question_tasks", [])
            if isinstance(task, dict)
        ],
        "research_question_scope_guard": dict(plan.get("scope_guard") or {}),
        "research_question_no_result_rule": str(plan.get("rule") or ""),
    }


def research_question_query_branch_plan(sub_hypothesis: dict[str, Any]) -> dict[str, Any]:
    """Materialise executable V3 slot-recovery work items as query branches.

    This adapter turns the validated contract-directed V3 plan into portable
    portable branch list that a provider loop can execute and record.  An
    empty provider result keeps its ``coverage_status`` diagnostic-only.
    """
    source = sub_hypothesis if isinstance(sub_hypothesis, dict) else {}
    annotation = {
        "research_question_contract": (
            source.get("research_question_contract")
            if isinstance(source.get("research_question_contract"), dict)
            else {}
        ),
    }
    context = _research_question_retrieval_context(annotation)
    if context.get("research_question_evidence_status") != "V3_RESEARCH_QUESTION_PLAN_BOUND":
        return {
            "schema_version": "research_question_query_branch_plan_v3",
            "status": "BLOCKED_V3_RESEARCH_QUESTION_PLAN_REQUIRED",
            "research_question_contract_id": "",
            "branches": [],
            "rule": context.get("research_question_no_result_rule"),
        }
    try:
        from ._research_question_contract import build_question_retrieval_plan
    except ImportError:
        from _research_question_contract import build_question_retrieval_plan
    plan = build_question_retrieval_plan(annotation["research_question_contract"])
    raw_tasks = plan.get("tasks") if isinstance(plan.get("tasks"), list) else []
    if not raw_tasks:
        raw_tasks = plan.get("slot_tasks") if isinstance(plan.get("slot_tasks"), list) else []
    branches: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in raw_tasks:
        if not isinstance(raw, dict):
            continue
        mode = str(raw.get("query_mode") or "POSITIVE_EVIDENCE")
        retrieval_spec = (
            raw.get("retrieval_spec_v3")
            if isinstance(raw.get("retrieval_spec_v3"), dict)
            else {}
        )
        query = str(retrieval_spec.get("provider_query") or "").strip()
        task_id = str(raw.get("task_id") or "").strip()
        if not query or not task_id or task_id in seen:
            continue
        seen.add(task_id)
        branches.append(
            {
                "role": "research_question_slot",
                "evidence_path_role": "research_question_slot",
                "branch": str(retrieval_spec.get("query_branch") or f"rq:{task_id}"),
                "query": query,
                "l2_query": query,
                "query_family": "research_question_v3",
                "research_question_contract_id": context["research_question_contract_id"],
                "research_question_kind": context["research_question_kind"],
                "research_question_task_id": task_id,
                "object_task_id": str(raw.get("object_task_id") or ""),
                "object_scope": dict(raw.get("object_scope") or {}) if isinstance(raw.get("object_scope"), dict) else {},
                "evidence_slot": str(raw.get("slot") or raw.get("requirement") or ""),
                "target_slot_ids": list(
                    raw.get("target_slot_ids")
                    or (raw.get("retrieval_work_item_v3") or {}).get("target_slot_ids")
                    or [str(raw.get("slot") or raw.get("requirement") or "")]
                ),
                "query_mode": mode,
                "required_source_role": str(raw.get("required_source_role") or ""),
                "required_source_types": list(raw.get("required_source_types") or []),
                "reuse_policy": (
                    dict(raw.get("reuse_policy") or {})
                    if isinstance(raw.get("reuse_policy"), dict)
                    else {}
                ),
                "query_fingerprint": str(retrieval_spec.get("semantic_fingerprint") or ""),
                "retrieval_spec_v3": dict(retrieval_spec),
                "retrieval_obligation_v3": dict(raw.get("retrieval_obligation_v3") or {}),
                "retrieval_obligations_v3": [
                    dict(item) for item in raw.get("retrieval_obligations_v3") or []
                    if isinstance(item, dict)
                ],
                "retrieval_work_item_v3": dict(raw.get("retrieval_work_item_v3") or {}),
                "plan_revision": str(plan.get("plan_revision") or ""),
                "coverage_status": "PLANNED",
                "empty_result_policy": "RETRIEVAL_COVERAGE_DIAGNOSTIC_ONLY",
                "prohibited_inference": "An empty result set cannot be converted into a scientific-gap assertion.",
            }
        )
    return {
        "schema_version": "research_question_query_branch_plan_v3",
        "status": "READY_FOR_PROVIDER_EXECUTION" if branches else "BLOCKED_EMPTY_V3_RESEARCH_QUESTION_PLAN",
        "research_question_contract_id": context["research_question_contract_id"],
        "research_question_kind": context["research_question_kind"],
        "scope_guard": dict(context.get("research_question_scope_guard") or {}),
        "branches": branches,
        "rule": context.get("research_question_no_result_rule"),
    }


def record_research_question_query_results(
    sub_hypothesis: dict[str, Any],
    results: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    """Record only task-scoped retrieval coverage, never a gap verdict.

    This is intentionally small and schema-strict: provider adapters may add
    bibliographic records elsewhere, but this ledger captures whether every
    question-contract task was executed and which sources were inspected.
    """
    plan = research_question_query_branch_plan(sub_hypothesis)
    if plan.get("status") != "READY_FOR_PROVIDER_EXECUTION":
        return {
            "schema_version": "research_question_retrieval_execution_v3",
            "status": "BLOCKED_V3_RESEARCH_QUESTION_PLAN_REQUIRED",
            "results": [],
            "scientific_gap_verdict": "PROHIBITED",
        }
    try:
        from ._research_question_contract import (
            RESEARCH_QUESTION_RETRIEVAL_PLAN_VERSION,
            RETRIEVAL_WORK_ITEM_VERSION,
            incompatible_retrieval_artifact,
            validate_provider_outcome_v3,
            validate_retrieval_work_item_v3,
        )
    except ImportError:
        from _research_question_contract import (
            RESEARCH_QUESTION_RETRIEVAL_PLAN_VERSION,
            RETRIEVAL_WORK_ITEM_VERSION,
            incompatible_retrieval_artifact,
            validate_provider_outcome_v3,
            validate_retrieval_work_item_v3,
        )
    known = {str(item.get("research_question_task_id") or ""): item for item in plan["branches"]}
    normalised: list[dict[str, Any]] = []
    normalised_by_task: dict[str, dict[str, Any]] = {}
    seen: set[str] = set()
    for raw in results or []:
        if not isinstance(raw, dict):
            continue
        task_id = str(raw.get("task_id") or raw.get("research_question_task_id") or "").strip()
        canonical_task_id = task_id
        branch = known.get(canonical_task_id)
        if not branch or canonical_task_id in seen:
            continue
        submitted_schema = str(raw.get("schema_version") or "")
        submitted_plan_schema = str(raw.get("plan_schema_version") or "")
        expected_work_item = branch.get("retrieval_work_item_v3")
        provider_outcomes_raw = raw.get("provider_outcomes_v3")
        if not isinstance(provider_outcomes_raw, list):
            variant_execution = (
                raw.get("query_variant_execution_v3")
                if isinstance(raw.get("query_variant_execution_v3"), dict)
                else {}
            )
            provider_outcomes_raw = variant_execution.get("provider_outcomes")
        try:
            expected_work_item = validate_retrieval_work_item_v3(expected_work_item)
            submitted_work_item = validate_retrieval_work_item_v3(
                raw.get("retrieval_work_item_v3")
            )
            work_item_matches = (
                submitted_work_item["work_item_kind"] == expected_work_item["work_item_kind"]
                and submitted_work_item["research_question_contract_id"]
                == expected_work_item["research_question_contract_id"]
                and submitted_work_item["research_question_contract_revision"]
                == expected_work_item["research_question_contract_revision"]
                and submitted_work_item["plan_fingerprint"] == expected_work_item["plan_fingerprint"]
                and submitted_work_item["target_slot_ids"] == expected_work_item["target_slot_ids"]
            )
            if submitted_schema != "retrieval_task_execution_v3":
                raise ValueError("task execution schema must be retrieval_task_execution_v3")
            if submitted_plan_schema != RESEARCH_QUESTION_RETRIEVAL_PLAN_VERSION:
                raise ValueError("plan schema is not the current V3 retrieval plan")
            if not work_item_matches:
                raise ValueError("retrieval work item does not match the current task contract")
            if not isinstance(provider_outcomes_raw, list) or not provider_outcomes_raw:
                raise ValueError("V3 task execution requires one or more typed provider_outcomes_v3")
            provider_outcomes = [
                validate_provider_outcome_v3(item)
                for item in provider_outcomes_raw
                if isinstance(item, dict)
            ]
            if not provider_outcomes:
                raise ValueError("V3 task execution provider_outcomes_v3 contains no valid ProviderOutcomeV3")
        except (TypeError, ValueError) as exc:
            rejection = incompatible_retrieval_artifact(
                raw,
                required_schema="retrieval_task_execution_v3",
                artifact_kind="retrieval_task_execution",
            )
            normalised.append(
                {
                    "task_id": canonical_task_id,
                    "status": rejection["status"],
                    "coverage_status": "RETRIEVAL_COVERAGE_DIAGNOSTIC_ONLY",
                    "reason_code": rejection["reason_code"],
                    "received_schema": submitted_schema or rejection["received_schema"],
                    "received_plan_schema": submitted_plan_schema or "MISSING_PLAN_SCHEMA_VERSION",
                    "failure_stage": "CONTRACT_VALIDATION",
                    "exception_message": str(exc),
                    "query_mode": branch["query_mode"],
                    "evidence_slot": branch["evidence_slot"],
                    "interpretation": "The submitted task result cannot be adapted or reused because it is not bound to the current V3 retrieval work item.",
                }
            )
            continue
        expected_revision = str(branch.get("plan_revision") or "")
        submitted_revision = str(raw.get("plan_revision") or expected_revision)
        if expected_revision and submitted_revision != expected_revision:
            normalised.append(
                {
                    "task_id": canonical_task_id,
                    "executed_query": str(raw.get("executed_query") or branch["query"]),
                    "source_ids": [],
                    "new_source_ids": [],
                    "reused_source_ids": [],
                    "assertion_ids": [],
                    "plan_revision": submitted_revision,
                    "expected_plan_revision": expected_revision,
                    "status": "STALE_PLAN_REVISION_RESULT",
                    "coverage_status": "RETRIEVAL_COVERAGE_DIAGNOSTIC_ONLY",
                    "query_mode": branch["query_mode"],
                    "evidence_slot": branch["evidence_slot"],
                    "interpretation": "This result belongs to a superseded retrieval plan and cannot complete the current V3 revision.",
                }
            )
            continue
        seen.add(canonical_task_id)
        source_ids = list(dict.fromkeys(str(item) for item in raw.get("source_ids", []) if str(item)))
        new_source_ids = list(dict.fromkeys(str(item) for item in raw.get("new_source_ids", []) if str(item)))
        reused_source_ids = list(dict.fromkeys(str(item) for item in raw.get("reused_source_ids", []) if str(item)))
        direct_slot_admitted_ids = list(dict.fromkeys(
            str(item) for item in raw.get("direct_slot_admitted_ids", []) if str(item)
        ))
        task_slot = str(branch.get("evidence_slot") or "")
        slot_policy_verdict = str(raw.get("slot_policy_verdict") or "")
        if not slot_policy_verdict:
            slot_policy_verdict = (
                "SATISFIED_BY_NEW_EVIDENCE"
                if task_slot in direct_slot_admitted_ids
                else "UNSATISFIED"
            )
        comparison_contract = (
            (branch.get("retrieval_spec_v3") or {}).get("comparison_contract_v4")
            if isinstance(branch.get("retrieval_spec_v3"), dict)
            and isinstance(
                (branch.get("retrieval_spec_v3") or {}).get(
                    "comparison_contract_v4"
                ),
                dict,
            )
            else {}
        )
        comparison_required_pair_ids = sorted({
            "::".join(str(arm_id) for arm_id in pair)
            for pair in (comparison_contract.get("target_comparison_pairs") or [])
            if isinstance(pair, list)
            and len(pair) == 2
            and all(str(arm_id).strip() for arm_id in pair)
        })
        comparison_covered_pair_ids = sorted({
            str(pair_id)
            for pair_id in raw.get("comparison_direct_pair_ids", [])
            if str(pair_id)
        })
        if (
            not comparison_covered_pair_ids
            and len(comparison_required_pair_ids) == 1
            and str(raw.get("coverage_bundle_kind") or "")
            == "direct_pair_comparison_v4"
            and str(raw.get("coverage_bundle_id") or "")
        ):
            comparison_covered_pair_ids = list(comparison_required_pair_ids)
        comparison_missing_pair_ids = [
            pair_id for pair_id in comparison_required_pair_ids
            if pair_id not in set(comparison_covered_pair_ids)
        ]
        direct_pair_coverage_complete = bool(
            comparison_contract
            and comparison_required_pair_ids
            and not comparison_missing_pair_ids
        )
        task_slot_admitted = (
            task_slot in direct_slot_admitted_ids
            and slot_policy_verdict in {"SATISFIED_BY_REUSE", "SATISFIED_BY_NEW_EVIDENCE"}
            # Single-arm benchmark evidence remains a valid source-bound
            # assertion. Cross-source comparison synthesis is evaluated only
            # after aggregation, never as a per-task admission condition.
        )
        coverage = (
            "DIRECT_SLOT_ADMITTED"
            if task_slot_admitted
            else "CANDIDATES_IMPORTED_AWAITING_ADMISSION"
            if source_ids
            else "RETRIEVAL_COVERAGE_DIAGNOSTIC_ONLY"
        )
        task_status = str(raw.get("status") or (
            "DIRECT_SLOT_ADMITTED"
            if task_slot_admitted
            else "CANDIDATES_IMPORTED_AWAITING_ADMISSION"
            if source_ids
            else "COVERAGE_SHORTAGE"
        ))
        if (
            comparison_contract
            and not direct_pair_coverage_complete
            and task_status == "DIRECT_SLOT_ADMITTED"
        ):
            task_status = "ARM_EVIDENCE_COLLECTED"
        normalised.append(
            {
                "task_id": canonical_task_id,
                "schema_version": "retrieval_task_execution_v3",
                "plan_schema_version": RESEARCH_QUESTION_RETRIEVAL_PLAN_VERSION,
                "executed_query": str(raw.get("executed_query") or branch["query"]),
                "query_branch": str(raw.get("query_branch") or branch.get("branch") or ""),
                "source_ids": source_ids,
                "new_source_ids": new_source_ids,
                "reused_source_ids": reused_source_ids,
                "assertion_ids": list(dict.fromkeys(str(item) for item in raw.get("assertion_ids", []) if str(item))),
                "query_fingerprint": str(raw.get("query_fingerprint") or branch.get("query_fingerprint") or ""),
                "retrieval_work_item_v3": submitted_work_item,
                "retrieval_obligation_v3": dict(branch.get("retrieval_obligation_v3") or {}),
                "retrieval_obligations_v3": [
                    dict(item) for item in branch.get("retrieval_obligations_v3") or []
                    if isinstance(item, dict)
                ],
                "target_slot_ids": list(
                    submitted_work_item.get("target_slot_ids")
                    or branch.get("target_slot_ids")
                    or [branch["evidence_slot"]]
                ),
                "provider_outcomes_v3": provider_outcomes,
                "provider_outcome_v3": dict(provider_outcomes[-1]),
                "retrieval_purpose": str(raw.get("retrieval_purpose") or "PRIMARY_SLOT_RETRIEVAL"),
                "plan_revision": str(raw.get("plan_revision") or branch.get("plan_revision") or ""),
                "status": task_status,
                "candidate_count": max(0, int(raw.get("candidate_count") or 0)),
                "metadata_kept_count": max(0, int(raw.get("metadata_kept_count") or 0)),
                "fulltext_available_count": max(0, int(raw.get("fulltext_available_count") or 0)),
                "alignment_completed_count": max(0, int(raw.get("alignment_completed_count") or 0)),
                "alignment_not_executed_count": max(0, int(raw.get("alignment_not_executed_count") or 0)),
                "alignment_integrity_error_count": max(0, int(raw.get("alignment_integrity_error_count") or 0)),
                "direct_slot_admitted_count": max(0, int(raw.get("direct_slot_admitted_count") or 0)),
                "direct_slot_admitted_ids": direct_slot_admitted_ids,
                "direct_slot_admitted_source_ids": list(dict.fromkeys(
                    str(item) for item in raw.get("direct_slot_admitted_source_ids", []) if str(item)
                )),
                "direct_slot_admitted_assertion_ids_by_slot": {
                    str(slot): list(dict.fromkeys(str(item) for item in values if str(item)))
                    for slot, values in (raw.get("direct_slot_admitted_assertion_ids_by_slot") or {}).items()
                    if isinstance(values, list) and str(slot)
                },
                "direct_slot_admitted_source_ids_by_slot": {
                    str(slot): list(dict.fromkeys(str(item) for item in values if str(item)))
                    for slot, values in (raw.get("direct_slot_admitted_source_ids_by_slot") or {}).items()
                    if isinstance(values, list) and str(slot)
                },
                "direct_slot_admitted_span_ids_by_slot": {
                    str(slot): list(dict.fromkeys(str(item) for item in values if str(item)))
                    for slot, values in (raw.get("direct_slot_admitted_span_ids_by_slot") or {}).items()
                    if isinstance(values, list) and str(slot)
                },
                "new_direct_slot_admitted_source_count": max(
                    0, int(raw.get("new_direct_slot_admitted_source_count") or 0)
                ),
                "reused_direct_slot_admitted_source_count": max(
                    0, int(raw.get("reused_direct_slot_admitted_source_count") or 0)
                ),
                "reused_direct_slot_admitted_assertion_count": max(
                    0, int(raw.get("reused_direct_slot_admitted_assertion_count") or 0)
                ),
                "direct_slot_admitted_span_count": max(
                    0, int(raw.get("direct_slot_admitted_span_count") or 0)
                ),
                "coverage_bundle_id": str(raw.get("coverage_bundle_id") or ""),
                "coverage_bundle_kind": str(raw.get("coverage_bundle_kind") or ""),
                "comparison_signature": str(raw.get("comparison_signature") or ""),
                "comparison_coverage_bundle_ids": list(dict.fromkeys(
                    str(item)
                    for item in raw.get("comparison_coverage_bundle_ids", [])
                    if str(item)
                )),
                "comparison_target_pair_ids": comparison_required_pair_ids,
                "comparison_direct_pair_ids": comparison_covered_pair_ids,
                "comparison_missing_direct_pair_ids": comparison_missing_pair_ids,
                "direct_pair_coverage_complete": direct_pair_coverage_complete,
                "slot_policy_verdict": slot_policy_verdict,
                "provider_dispatch_status": str(raw.get("provider_dispatch_status") or ""),
                "provider_dispatch_reason": str(raw.get("provider_dispatch_reason") or ""),
                "failure_stage": str(raw.get("failure_stage") or ""),
                "exception_type": str(raw.get("exception_type") or ""),
                "exception_message": str(raw.get("exception_message") or ""),
                "independent_confirmation_required": bool(
                    raw.get("independent_confirmation_required")
                ),
                "foundation_context_count": max(0, int(raw.get("foundation_context_count") or 0)),
                "background_only_count": max(0, int(raw.get("background_only_count") or 0)),
                "contract_rejected_count": max(0, int(raw.get("contract_rejected_count") or 0)),
                "raw_provider_result_count": max(0, int(raw.get("raw_provider_result_count") or 0)),
                "configured_providers": list(raw.get("configured_providers") or []),
                "dispatched_providers": list(raw.get("dispatched_providers") or []),
                "skipped_providers": list(raw.get("skipped_providers") or []),
                "deferred_provider_count": max(0, int(raw.get("deferred_provider_count") or 0)),
                "provider_error_count": max(0, int(raw.get("provider_error_count") or 0)),
                "provider_submission_count": max(0, int(raw.get("provider_submission_count") or 0)),
                "provider_terminal_response_count": max(
                    0, int(raw.get("provider_terminal_response_count") or 0)
                ),
                "local_query_compilation_rejection_count": max(
                    0, int(raw.get("local_query_compilation_rejection_count") or 0)
                ),
                "provider_continuation_attempts": max(
                    0,
                    int(raw.get("provider_continuation_attempts") or 0),
                ),
                "query_variant_execution_v3": (
                    dict(raw.get("query_variant_execution_v3") or {})
                    if isinstance(raw.get("query_variant_execution_v3"), dict)
                    else {}
                ),
                "comparison_retrieval_phase_v4": (
                    dict(raw.get("comparison_retrieval_phase_v4") or {})
                    if isinstance(raw.get("comparison_retrieval_phase_v4"), dict)
                    else {}
                ),
                "assertion_admission_status": str(
                    raw.get("assertion_admission_status") or ""
                ),
                "scientific_obligation_status": str(
                    raw.get("scientific_obligation_status") or ""
                ),
                "comparison_obligation_diagnostics": (
                    dict(raw.get("comparison_obligation_diagnostics") or {})
                    if isinstance(raw.get("comparison_obligation_diagnostics"), dict)
                    else {}
                ),
                "comparison_candidate_diagnostics": [
                    dict(item)
                    for item in raw.get("comparison_candidate_diagnostics", [])
                    if isinstance(item, dict)
                ],
                "candidate_pool_diagnostics": (
                    dict(raw.get("candidate_pool_diagnostics") or {})
                    if isinstance(raw.get("candidate_pool_diagnostics"), dict)
                    else {}
                ),
                "candidate_disposition": str(raw.get("candidate_disposition") or ""),
                "candidate_disposition_counts": (
                    dict(raw.get("candidate_disposition_counts") or {})
                    if isinstance(raw.get("candidate_disposition_counts"), dict)
                    else {}
                ),
                "excluded_candidate_key_count": max(0, int(raw.get("excluded_candidate_key_count") or 0)),
                "foundation_context_execution": (
                    dict(raw.get("foundation_context_execution") or {})
                    if isinstance(raw.get("foundation_context_execution"), dict)
                    else {}
                ),
                "coverage_status": coverage,
                "query_mode": branch["query_mode"],
                "evidence_slot": branch["evidence_slot"],
                "candidate_redundancy_profile": (
                    dict(raw.get("candidate_redundancy_profile") or {})
                    if isinstance(raw.get("candidate_redundancy_profile"), dict)
                    else {}
                ),
                "interpretation": (
                    "Source ids require source-span extraction and contract-bound assertion audit before they affect a candidate."
                    if source_ids
                    else "No result is a retrieval coverage diagnostic only; it is not a scientific unknown or gap."
                ),
            }
        )
        normalised_by_task[canonical_task_id] = normalised[-1]
    missing_task_ids = sorted(set(known) - seen)
    source_found_count = sum(1 for row in normalised if row.get("source_ids"))
    candidate_count = sum(int(row.get("candidate_count") or 0) for row in normalised)
    raw_provider_result_count = sum(int(row.get("raw_provider_result_count") or 0) for row in normalised)
    deferred_provider_count = sum(int(row.get("deferred_provider_count") or 0) for row in normalised)
    provider_error_count = sum(int(row.get("provider_error_count") or 0) for row in normalised)
    provider_submission_count = sum(
        int(row.get("provider_submission_count") or 0) for row in normalised
    )
    provider_terminal_response_count = sum(
        int(row.get("provider_terminal_response_count") or 0) for row in normalised
    )
    local_query_compilation_rejection_count = sum(
        int(row.get("local_query_compilation_rejection_count") or 0)
        for row in normalised
    )
    deferred_provider_continuation_attempts = sum(
        int(row.get("provider_continuation_attempts") or 0)
        for row in normalised
    )
    configured_providers = list(dict.fromkeys(
        str(provider)
        for row in normalised if isinstance(row, dict)
        for provider in row.get("configured_providers", [])
        if str(provider)
    ))
    dispatched_providers = list(dict.fromkeys(
        str(provider)
        for row in normalised if isinstance(row, dict)
        for provider in row.get("dispatched_providers", [])
        if str(provider)
    ))
    skipped_providers = [
        dict(item)
        for row in normalised if isinstance(row, dict)
        for item in row.get("skipped_providers", [])
        if isinstance(item, dict)
    ]
    metadata_kept_count = sum(int(row.get("metadata_kept_count") or 0) for row in normalised)
    fulltext_available_count = sum(int(row.get("fulltext_available_count") or 0) for row in normalised)
    alignment_completed_count = sum(int(row.get("alignment_completed_count") or 0) for row in normalised)
    alignment_not_executed_count = sum(int(row.get("alignment_not_executed_count") or 0) for row in normalised)
    alignment_integrity_error_count = sum(int(row.get("alignment_integrity_error_count") or 0) for row in normalised)
    direct_slot_admitted_source_ids = sorted({
        str(source_id)
        for row in normalised
        if isinstance(row, dict)
        for source_id in row.get("direct_slot_admitted_source_ids", [])
        if str(source_id)
    })
    direct_slot_admitted_count = len(direct_slot_admitted_source_ids)
    required_direct_slots = sorted({
        str(slot)
        for branch in known.values()
        if str(branch.get("query_mode") or "").upper() == "POSITIVE_EVIDENCE"
        for slot in (
            branch.get("target_slot_ids")
            or [branch.get("evidence_slot")]
        )
        if str(slot)
    })
    positive_rows_by_slot: dict[str, list[dict[str, Any]]] = {}
    for row in normalised:
        if isinstance(row, dict) and str(row.get("query_mode") or "").upper() == "POSITIVE_EVIDENCE":
            for slot in row.get("target_slot_ids") or [row.get("evidence_slot")]:
                if str(slot):
                    positive_rows_by_slot.setdefault(str(slot), []).append(row)

    def slot_source_ids(row: dict[str, Any], slot: str) -> list[str]:
        return list(dict.fromkeys(
            str(item)
            for item in (
                (row.get("direct_slot_admitted_source_ids_by_slot") or {}).get(slot)
                or row.get("direct_slot_admitted_source_ids")
                or []
            )
            if str(item)
        ))

    def slot_assertion_ids(row: dict[str, Any], slot: str) -> list[str]:
        return list(dict.fromkeys(
            str(item)
            for item in (
                (row.get("direct_slot_admitted_assertion_ids_by_slot") or {}).get(slot)
                or row.get("assertion_ids")
                or []
            )
            if str(item)
        ))

    def slot_span_ids(row: dict[str, Any], slot: str) -> list[str]:
        return list(dict.fromkeys(
            str(item)
            for item in (
                (row.get("direct_slot_admitted_span_ids_by_slot") or {}).get(slot)
                or []
            )
            if str(item)
        ))

    def slot_ledger_entry(slot: str, row: dict[str, Any]) -> dict[str, Any]:
        source_ids = slot_source_ids(row, slot)
        assertion_ids = slot_assertion_ids(row, slot)
        source_span_ids = slot_span_ids(row, slot)
        policy = dict(next(
            (
                branch.get("reuse_policy")
                for branch in known.values()
                if str(branch.get("evidence_slot") or "") == slot
            ),
            {},
        ) or {})
        policy_verdict = str(row.get("slot_policy_verdict") or "UNSATISFIED")
        direct_slot_admitted = slot in set(
            row.get("direct_slot_admitted_ids") or []
        )
        qualified = (
            direct_slot_admitted
            and policy_verdict in {
                "SATISFIED_BY_REUSE", "SATISFIED_BY_NEW_EVIDENCE"
            }
        )
        provider_reason = str(row.get("provider_dispatch_reason") or "")
        missing_policy_requirements = {
            item.strip()
            for item in provider_reason.split(",")
            if item.strip()
        }
        shortfall_reason_codes: list[str] = []
        independent_short = (
            "independent_confirmation" in missing_policy_requirements
            or (
                bool(policy.get("require_independent_confirmation"))
                and len(source_ids) < 2
            )
        )
        bundle_short = (
            any(item.startswith("coverage_bundle:") for item in missing_policy_requirements)
            or (
                bool(policy.get("coverage_bundle_requirement"))
                and not str(row.get("coverage_bundle_id") or "")
            )
        )
        if not qualified and independent_short:
            shortfall_reason_codes.append("EVIDENCE_DIVERSITY_SHORTAGE")
        if not qualified and bundle_short:
            shortfall_reason_codes.append("COMPARABILITY_COHERENCE_SHORTAGE")
        if not qualified and (
            not shortfall_reason_codes
            or any(
                item in missing_policy_requirements
                for item in (
                    "min_admitted_assertion_count",
                    "min_distinct_span_count",
                    "min_distinct_paper_count",
                )
            )
            or not direct_slot_admitted
        ):
            shortfall_reason_codes.append("SLOT_REQUIREMENT_UNSATISFIED")
        shortfall_reason_codes = list(dict.fromkeys(shortfall_reason_codes))
        shortfall_category = (
            "EVIDENCE_DIVERSITY_OR_COHERENCE_SHORTAGE"
            if any(
                item in {
                    "EVIDENCE_DIVERSITY_SHORTAGE",
                    "COMPARABILITY_COHERENCE_SHORTAGE",
                }
                for item in shortfall_reason_codes
            )
            else "SLOT_REQUIREMENT_UNSATISFIED"
        )
        return {
            "slot_id": slot,
            "policy": policy,
            "policy_verdict": policy_verdict,
            "direct_slot_admitted": direct_slot_admitted,
            "provider_dispatch_status": str(row.get("provider_dispatch_status") or ""),
            "provider_dispatch_reason": str(row.get("provider_dispatch_reason") or ""),
            "independent_confirmation_required": bool(
                row.get("independent_confirmation_required")
            ),
            "query_branch": str(row.get("query_branch") or ""),
            "query_fingerprint": str(row.get("query_fingerprint") or ""),
            "retrieval_purpose": str(row.get("retrieval_purpose") or ""),
            "assertion_ids": assertion_ids,
            "source_ids": source_ids,
            "source_span_ids": source_span_ids,
            "distinct_assertion_count": len(assertion_ids),
            "distinct_paper_count": len(source_ids),
            "distinct_span_count": len(source_span_ids) or int(
                row.get("direct_slot_admitted_span_count") or 0
            ),
            "coverage_bundle_id": str(row.get("coverage_bundle_id") or ""),
            "coverage_bundle_kind": str(row.get("coverage_bundle_kind") or ""),
            "comparison_signature": str(row.get("comparison_signature") or ""),
            "new_direct_slot_admitted_source_count": int(
                row.get("new_direct_slot_admitted_source_count") or 0
            ),
            "reused_direct_slot_admitted_source_count": int(
                row.get("reused_direct_slot_admitted_source_count") or 0
            ),
            "reused_direct_slot_admitted_assertion_count": int(
                row.get("reused_direct_slot_admitted_assertion_count") or 0
            ),
            "qualified_for_gap_readiness": qualified,
            "shortfall_category": "" if qualified else shortfall_category,
            "shortfall_reason_codes": [] if qualified else shortfall_reason_codes,
            "claim_readiness": "READY" if qualified else shortfall_category,
        }

    slot_coverage_ledger = {
        slot: slot_ledger_entry(
            slot,
            next(
                (
                    row
                    for row in positive_rows_by_slot.get(slot, [])
                    if str(row.get("slot_policy_verdict") or "")
                    in {"SATISFIED_BY_REUSE", "SATISFIED_BY_NEW_EVIDENCE"}
                    and slot in set(row.get("direct_slot_admitted_ids") or [])
                ),
                next(iter(positive_rows_by_slot.get(slot, [])), {}),
            ),
        )
        for slot in required_direct_slots
    }
    covered_direct_slots = sorted(
        slot
        for slot, entry in slot_coverage_ledger.items()
        if isinstance(entry, dict) and entry.get("qualified_for_gap_readiness") is True
    )
    missing_direct_slots = sorted(set(required_direct_slots) - set(covered_direct_slots))
    aggregate_evidence_ready = bool(required_direct_slots) and not missing_direct_slots
    candidate_intake_status = (
        "EMPTY" if not source_found_count else
        "COMPLETE" if not missing_task_ids and source_found_count == len(normalised) else
        "PARTIAL"
    )
    alignment_status = (
        "INTEGRITY_ERROR" if alignment_integrity_error_count else
        "NOT_EXECUTED" if metadata_kept_count and not alignment_completed_count else
        "PARTIAL" if alignment_not_executed_count else
        "COMPLETE" if metadata_kept_count and not missing_task_ids and alignment_completed_count >= metadata_kept_count else
        "NOT_EXECUTED" if not alignment_completed_count else
        "PARTIAL"
    )
    admission_status = (
        "EMPTY" if not direct_slot_admitted_count else
        "PARTIAL" if direct_slot_admitted_count < source_found_count else
        "COMPLETE"
    )
    evidence_coverage_status = (
        "EMPTY" if not covered_direct_slots else
        "COMPLETE" if aggregate_evidence_ready else
        "PARTIAL"
    )
    terminal_statuses = {str(row.get("status") or "") for row in normalised}
    retrieval_execution_status = (
        "RETRIEVAL_EXECUTION_ERROR" if "RETRIEVAL_EXECUTION_ERROR" in terminal_statuses else
        "PARTIAL" if missing_task_ids else
        "PROVIDER_DEFERRED" if "PROVIDER_DEFERRED" in terminal_statuses else
        "INVALID_QUERY" if "INVALID_QUERY" in terminal_statuses else
        "QUERY_PLAN_CONTRACT_ERROR" if "QUERY_PLAN_CONTRACT_ERROR" in terminal_statuses else
        "QUERY_COMPILATION_REPAIR_REQUIRED" if "QUERY_COMPILATION_REPAIR_REQUIRED" in terminal_statuses else
        "SEARCH_ERROR" if "SEARCH_ERROR" in terminal_statuses else
        "COMPLETE"
    )
    return {
        "schema_version": "research_question_retrieval_execution_v3",
        "status": retrieval_execution_status,
        "retrieval_execution_status": retrieval_execution_status,
        "candidate_intake_status": candidate_intake_status,
        "alignment_status": alignment_status,
        "candidate_count": candidate_count,
        "raw_provider_result_count": raw_provider_result_count,
        "deferred_provider_count": deferred_provider_count,
        "provider_error_count": provider_error_count,
        "provider_submission_count": provider_submission_count,
        "provider_terminal_response_count": provider_terminal_response_count,
        "local_query_compilation_rejection_count": local_query_compilation_rejection_count,
        "provider_continuation_attempts": deferred_provider_continuation_attempts,
        "configured_providers": configured_providers,
        "dispatched_providers": dispatched_providers,
        "skipped_providers": skipped_providers,
        "metadata_kept_count": metadata_kept_count,
        "fulltext_available_count": fulltext_available_count,
        "alignment_completed_count": alignment_completed_count,
        "alignment_not_executed_count": alignment_not_executed_count,
        "alignment_integrity_error_count": alignment_integrity_error_count,
        "admission_status": admission_status,
        "evidence_coverage_status": evidence_coverage_status,
        "aggregate_evidence_ready": aggregate_evidence_ready,
        "slot_coverage_ledger": slot_coverage_ledger,
        "required_direct_slot_ids": required_direct_slots,
        "covered_direct_slot_ids": covered_direct_slots,
        "missing_direct_slot_ids": missing_direct_slots,
        "direct_evidence_paper_count": direct_slot_admitted_count,
        "research_question_contract_id": plan["research_question_contract_id"],
        "query_variant_policy": "contract_slot_query_variants_v3",
        "results": normalised,
        "unexecuted_task_ids": missing_task_ids,
        "scientific_gap_verdict": "PROHIBITED",
        "rule": plan["rule"],
    }


def _project_background_only_for_binding(
    record: dict[str, Any],
    binding: dict[str, Any],
    alignment: dict[str, Any],
) -> bool:
    scope = str(
        alignment.get("admission_scope")
        or binding.get("admission_scope")
        or record.get("admission_scope")
        or alignment.get("sh_locality_scope")
        or binding.get("sh_locality_scope")
        or record.get("sh_locality_scope")
        or ""
    )
    return bool(
        scope == "project_background_only"
        or alignment.get("project_background_only") is True
        or alignment.get("excluded_from_sh_gap_synthesis") is True
        or binding.get("project_background_only") is True
        or binding.get("excluded_from_sh_gap_synthesis") is True
        or record.get("project_background_only") is True
        or record.get("excluded_from_sh_gap_synthesis") is True
    )


def _alignment_axis_pass(alignment: dict[str, Any], *keys: str) -> bool:
    for key in keys:
        axis = alignment.get(key)
        if isinstance(axis, dict) and axis.get("passes") is True:
            return True
    return False


def _noncore_missing_contract_requirements(
    record: dict[str, Any], alignment: dict[str, Any],
) -> list[str]:
    return type_directed_missing_axes(record, alignment)


def _noncore_evidence_pool_name(record: dict[str, Any], alignment: dict[str, Any]) -> str:
    role = " ".join(
        str(value or "")
        for value in (
            record.get("evidence_role"),
            record.get("evidence_path_role"),
            alignment.get("evidence_role"),
            alignment.get("evidence_path_role"),
            alignment.get("evidence_lane"),
            alignment.get("corpus_admission_reason"),
            record.get("corpus_admission_reason"),
        )
    ).lower()
    polarity = str(record.get("evidence_polarity") or alignment.get("evidence_polarity") or "").lower()
    if "adverse" in role or "reversal" in role or polarity == "opposing":
        return "adverse_context"
    if "boundary" in role or "generalization" in role or polarity == "boundary":
        return "boundary_context"
    if "foundation" in role or "foundational" in role or "l1_foundational" in role:
        return "related_foundation"
    if "component" in role or "mechanism" in role:
        return "component_mechanism"
    if "platform" in role:
        return "platform_context"
    if "method" in role:
        return "method_context"
    return "method_context"


def _related_fulltext_reporting_role(
    record: dict[str, Any],
    alignment: dict[str, Any],
    *,
    layer: str,
) -> tuple[str, str]:
    """Return the stable corpus tier and display role for a non-core paper."""

    context = (
        record.get("import_context")
        if isinstance(record.get("import_context"), dict)
        else {}
    )
    type_evidence = (
        alignment.get("type_directed_evidence")
        if isinstance(alignment.get("type_directed_evidence"), dict)
        else {}
    )
    role_text = " ".join(
        str(value or "")
        for value in (
            record.get("corpus_evidence_tier"),
            record.get("evidence_role"),
            record.get("evidence_path_role"),
            record.get("evidence_lane"),
            record.get("corpus_admission_reason"),
            alignment.get("corpus_evidence_tier"),
            alignment.get("evidence_role"),
            alignment.get("evidence_path_role"),
            alignment.get("evidence_lane"),
            alignment.get("corpus_admission_reason"),
            type_evidence.get("evidence_lane"),
            context.get("target_lane"),
            context.get("evidence_path_role"),
        )
    ).lower()
    polarity = str(
        record.get("evidence_polarity")
        or alignment.get("evidence_polarity")
        or ""
    ).lower()
    if "adverse" in role_text or "reversal" in role_text or polarity == "opposing":
        return "ADVERSE_OR_REVERSAL", "adverse_context"
    if "boundary" in role_text or "generalization" in role_text or polarity == "boundary":
        return "BOUNDARY_OR_NEGATIVE", "boundary_context"
    if (
        layer == "L0_review"
        or _is_review(record, layer, alignment)
        or "background" in role_text
        or "framework" in role_text
        or "review" in role_text
    ):
        return "BACKGROUND_OR_REVIEW", "background_or_framework"
    if "component" in role_text:
        return "COMPONENT_SUPPORT", "component_support"
    if "supporting_mechanism" in role_text or "mechanism_link" in role_text:
        return "SUPPORTING_MECHANISM", "supporting_mechanism"
    if "platform" in role_text or "method" in role_text or "foundation" in role_text:
        return "METHOD_OR_PLATFORM", "method_context"
    return "RELATED_CONTEXT", "related_context"


def _evidence_portfolio_roles(
    record: dict[str, Any],
    alignment: dict[str, Any],
    *,
    layer: str,
) -> set[str]:
    """Classify one imported full text into gap-generating portfolio roles."""

    context = (
        record.get("import_context")
        if isinstance(record.get("import_context"), dict)
        else {}
    )
    type_evidence = (
        alignment.get("type_directed_evidence")
        if isinstance(alignment.get("type_directed_evidence"), dict)
        else {}
    )
    role_text = " ".join(
        str(value or "")
        for value in (
            record.get("evidence_role"),
            record.get("evidence_path_role"),
            record.get("evidence_kind"),
            record.get("evidence_lane"),
            record.get("target_lane"),
            record.get("research_role"),
            record.get("corpus_admission_reason"),
            alignment.get("evidence_role"),
            alignment.get("evidence_path_role"),
            alignment.get("evidence_kind"),
            alignment.get("evidence_lane"),
            alignment.get("corpus_admission_reason"),
            type_evidence.get("evidence_lane"),
            context.get("target_lane"),
            context.get("evidence_path_role"),
            context.get("query_branch"),
        )
    ).lower()
    polarity = str(
        record.get("evidence_polarity")
        or alignment.get("evidence_polarity")
        or ""
    ).lower()
    roles: set[str] = set()
    if (
        "adverse" in role_text
        or "reversal" in role_text
        or "opposing" in role_text
        or polarity == "opposing"
    ):
        roles.add("adverse_or_reversal")
    if (
        "boundary" in role_text
        or "generalization" in role_text
        or "negative_evidence" in role_text
        or polarity == "boundary"
    ):
        roles.add("boundary_or_negative")
    if any(
        marker in role_text
        for marker in (
            "component",
            "bridge",
            "type_directed_component_bridge",
        )
    ) or type_evidence.get("component_bridge_eligible") is True:
        roles.add("component_or_bridge")
    if (
        layer == "L0_review"
        or _is_review(record, layer, alignment)
        or any(
            marker in role_text
            for marker in (
                "background",
                "framework",
                "context_review",
                "theoretical_framework",
            )
        )
    ):
        roles.add("background_or_framework")
    if (
        layer == "L1_milestone"
        or any(
            marker in role_text
            for marker in (
                "method",
                "platform",
                "foundation",
                "benchmark",
                "calibration",
                "measurement_context",
            )
        )
    ):
        roles.add("method_or_foundation")
    return roles


def _noncore_evidence_pool_item(
    record: dict[str, Any],
    alignment: dict[str, Any],
    *,
    layer: str,
    full_text: dict[str, Any],
) -> dict[str, Any]:
    return {
        "paper_id": str(record.get("paper_id") or ""),
        "title": str(record.get("title") or "")[:220],
        "citation": str(record.get("citation") or record.get("title") or "")[:260],
        "layer": layer,
        "evidence_role": str(record.get("evidence_role") or alignment.get("evidence_role") or ""),
        "evidence_polarity": str(record.get("evidence_polarity") or alignment.get("evidence_polarity") or "unclear"),
        "corpus_admission_reason": str(record.get("corpus_admission_reason") or alignment.get("corpus_admission_reason") or ""),
        "alignment_verdict": str(alignment.get("verdict") or ""),
        "missing_contract_requirements": _noncore_missing_contract_requirements(
            record, alignment
        ),
        "full_text_available": bool(full_text.get("full_text_available")),
        "full_text_excerpt_chars": int(full_text.get("full_text_excerpt_chars") or 0),
    }


def _record_panel_evidence_metadata(
    record: dict[str, Any],
    binding: dict[str, Any],
    alignment: dict[str, Any],
) -> dict[str, Any]:
    """Normalize panel/component path markers across record/binding/alignment."""

    context = record.get("import_context") if isinstance(record.get("import_context"), dict) else {}
    prefulltext = (
        alignment.get("prefulltext_import_assessment")
        if isinstance(alignment.get("prefulltext_import_assessment"), dict)
        else {}
    )
    sources = [alignment, prefulltext, binding, context, record]

    def first_value(key: str, default: Any = "") -> Any:
        for source in sources:
            if not isinstance(source, dict):
                continue
            value = source.get(key)
            if value not in (None, "", [], {}):
                return value
        return default

    def first_bool(key: str) -> bool | None:
        for source in sources:
            if not isinstance(source, dict):
                continue
            value = source.get(key)
            if value is True or value is False:
                return bool(value)
        return None

    tier = str(first_value("panel_evidence_tier", "") or "").strip().lower()
    role = str(first_value("evidence_path_role", "") or "").strip()
    polarity = str(first_value("evidence_path_polarity", "") or "").strip().lower()
    type_evidence = (
        alignment.get("type_directed_evidence")
        if isinstance(alignment.get("type_directed_evidence"), dict)
        else {}
    )
    lane = str(
        alignment.get("evidence_lane")
        or type_evidence.get("evidence_lane")
        or prefulltext.get("provisional_evidence_lane")
        or ""
    ).strip()
    component_counts_as_panel_core = first_bool("component_evidence_counts_as_panel_core")
    component_counts_as_core = first_bool("component_evidence_counts_as_core")
    core_capable = first_bool("core_evidence_capable")
    explicit_panel = first_bool("multi_entity_panel")
    explicit_component_path = first_bool("panel_component_path")
    path_metadata_present = bool(
        tier
        or role
        or explicit_component_path is not None
        or component_counts_as_panel_core is not None
        or component_counts_as_core is not None
        or core_capable is not None
        or first_bool("panel_core_path") is not None
        or first_bool("panel_auxiliary_evidence_only") is not None
        or first_bool("panel_component_support_only") is not None
        or lane == "PANEL_COMPONENT_SUPPORT_EVIDENCE"
    )
    component_path = bool(
        explicit_component_path is True
        or tier in {"support", "context"}
        or lane == "PANEL_COMPONENT_SUPPORT_EVIDENCE"
        or any(marker in role.lower() for marker in ("support", "component", "constraint", "deployment"))
    )
    panel_like_hint = bool(
        explicit_panel is True
        or tier
        or component_counts_as_panel_core is False
        or component_counts_as_core is False
        or explicit_component_path is not None
        or first_bool("panel_core_path") is not None
        or first_bool("panel_auxiliary_evidence_only") is not None
        or first_bool("panel_component_support_only") is not None
    )
    auxiliary_only = bool(
        panel_like_hint
        and (
            first_bool("panel_auxiliary_evidence_only") is True
            or component_counts_as_panel_core is False
            or component_counts_as_core is False
            or core_capable is False
            or tier in {"support", "context"}
            or lane == "PANEL_COMPONENT_SUPPORT_EVIDENCE"
        )
    )
    component_support_only = bool(
        panel_like_hint
        and (
            first_bool("panel_component_support_only") is True
            or (component_path and auxiliary_only)
            or lane == "PANEL_COMPONENT_SUPPORT_EVIDENCE"
        )
    )
    panel_core_path = bool(
        panel_like_hint
        and not auxiliary_only
        and (
            first_bool("panel_core_path") is True
            or core_capable is True
            or tier == "core"
            or not path_metadata_present
        )
    )
    is_panel = bool(
        panel_like_hint
        or tier
        or component_counts_as_panel_core is False
        or component_support_only
        or panel_core_path
    )
    return {
        "multi_entity_panel": is_panel,
        "panel_evidence_tier": tier,
        "panel_evidence_path_role": role,
        "evidence_path_polarity": polarity,
        "panel_component_path": component_path,
        "panel_core_path": panel_core_path,
        "panel_path_metadata_present": path_metadata_present,
        "panel_auxiliary_evidence_only": bool(is_panel and auxiliary_only),
        "panel_component_support_only": bool(is_panel and component_support_only),
        "component_evidence_counts_as_panel_core": (
            False if is_panel and auxiliary_only else True if is_panel and panel_core_path else None
        ),
        "failure_scope": str(first_value("failure_scope", "") or ""),
        "can_independently_falsify_sh": first_bool("can_independently_falsify_sh"),
        "missing_path_blocks_sh": first_bool("missing_path_blocks_sh"),
        "negative_evidence_interpretation": str(first_value("negative_evidence_interpretation", "") or ""),
    }


_OPPOSING_EVIDENCE_MARKERS = (
    "adverse",
    "reversal",
    "opposing",
    "tradeoff",
    "trade-off",
    "burden",
    "burden-shifting",
    "rebound",
    "substitution",
    "resource competition",
    "implementation failure",
    "failure mode",
    "robustness failure",
    "null effect",
    "reduced effectiveness",
    "worse",
    "harm",
    "toxicity",
    "negative mechanism",
    "adverse_or_reversal",
    "adverse_or_reversal_evidence",
)

_BOUNDARY_EVIDENCE_MARKERS = (
    "boundary",
    "generalization",
    "generalisation",
    "heterogeneity",
    "moderator",
    "threshold",
    "transportability",
    "external validity",
    "boundary_or_generalization",
    "boundary_or_negative_evidence",
)


def _claim_evidence_polarity_from_text(*values: Any) -> str:
    text = " ".join(str(value or "") for value in values if value not in (None, "", [], {}))
    lowered = text.lower()
    if not lowered.strip():
        return "unclear"
    if "mixed" in lowered:
        return "mixed"
    if any(marker in lowered for marker in _OPPOSING_EVIDENCE_MARKERS):
        return "opposing"
    if any(marker in lowered for marker in _BOUNDARY_EVIDENCE_MARKERS):
        return "boundary"
    if any(
        marker in lowered
        for marker in (
            "supportive",
            "support",
            "core_validation",
            "causal_validation",
            "predictive_validation",
            "direct_triadic",
            "standard_core",
        )
    ):
        return "supportive"
    return "unclear"


def _record_claim_effect_metadata(
    record: dict[str, Any],
    binding: dict[str, Any],
    alignment: dict[str, Any],
    item: dict[str, Any],
) -> dict[str, Any]:
    context = record.get("import_context") if isinstance(record.get("import_context"), dict) else {}
    type_evidence = alignment.get("type_directed_evidence") if isinstance(alignment.get("type_directed_evidence"), dict) else {}
    sources = [item, alignment, binding, context, record]

    def first_value(key: str, default: Any = "") -> Any:
        for source in sources:
            if not isinstance(source, dict):
                continue
            value = source.get(key)
            if value not in (None, "", [], {}):
                return value
        return default

    def first_bool(key: str) -> bool | None:
        for source in sources:
            if not isinstance(source, dict):
                continue
            value = source.get(key)
            if value is True or value is False:
                return bool(value)
        return None

    role = str(
        first_value("evidence_path_role")
        or first_value("panel_evidence_path_role")
        or first_value("retrieval_layer_role")
        or ""
    ).strip()
    explicit_polarity = str(
        first_value("evidence_polarity")
        or first_value("evidence_path_polarity")
        or first_value("polarity")
        or ""
    ).strip().lower()
    lane = str(
        first_value("target_lane")
        or first_value("evidence_lane")
        or type_evidence.get("evidence_lane")
        or ""
    ).strip()
    if explicit_polarity in {"supportive", "opposing", "mixed", "boundary", "unclear"}:
        polarity = explicit_polarity
    else:
        polarity = _claim_evidence_polarity_from_text(
            role,
            lane,
            first_value("negative_evidence_interpretation"),
            alignment.get("causal_role"),
            alignment.get("alignment_verdict"),
        )
    if polarity == "unclear" and bool(alignment.get("core_eligible") or alignment.get("import_eligible")):
        polarity = "supportive"
    if not role:
        if polarity == "opposing":
            role = "adverse_or_reversal"
        elif polarity == "boundary":
            role = "boundary_or_generalization"
        elif str(lane).upper() == "PREDICTIVE_VALIDATION":
            role = "predictive_validation"
        elif bool(alignment.get("core_eligible")):
            role = "core_validation"
    eligible = bool(alignment.get("core_eligible") or alignment.get("import_eligible"))
    supports = first_bool("supports_primary_claim")
    weakens = first_bool("weakens_primary_claim")
    boundary_supported = first_bool("boundary_condition_supported")
    if supports is None:
        supports = bool(polarity == "supportive" and eligible)
    if weakens is None:
        weakens = bool(polarity == "opposing" and eligible)
    if polarity == "mixed" and eligible:
        supports = True
        weakens = True
    if boundary_supported is None:
        boundary_supported = bool(polarity == "boundary" and eligible)
    return {
        "evidence_polarity": polarity,
        "evidence_path_role": role,
        "supports_primary_claim": bool(supports),
        "weakens_primary_claim": bool(weakens),
        "boundary_condition_supported": bool(boundary_supported),
    }


def _claim_strength_modifier_from_core_counts(
    *,
    supportive_core: int,
    opposing_core: int,
    boundary_core: int,
    mixed_core: int,
    unclear_core: int,
) -> dict[str, Any]:
    if mixed_core or (supportive_core and opposing_core):
        verdict = "mixed_or_condition_dependent"
    elif opposing_core and not supportive_core:
        verdict = "primarily_opposing_or_reversal"
    elif boundary_core and supportive_core:
        verdict = "conditional_or_boundary_limited"
    elif supportive_core:
        verdict = "supportive"
    elif boundary_core:
        verdict = "boundary_only"
    elif unclear_core:
        verdict = "direction_unclear"
    else:
        verdict = "insufficient_core_direction"
    return {
        "supportive_core": int(supportive_core),
        "opposing_core": int(opposing_core),
        "boundary_core": int(boundary_core),
        "mixed_core": int(mixed_core),
        "unclear_core": int(unclear_core),
        "verdict": verdict,
        "interpretation": (
            "Core/full-text review is polarity-aware: opposing or boundary core can satisfy evidence-audit sufficiency, "
            "but only supportive core strengthens the primary positive claim."
        ),
    }


def subhypothesis_full_text_coverage(
    project: dict[str, Any],
    sub_hypothesis_id: str,
    *,
    gate_contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Count imported and evidence-admitted non-preprint full texts cumulatively."""

    try:
        from ._literature_import import (
            assess_full_text_acquisition,
            fulltext_structuring_admission_assessment,
        )
    except ImportError:
        from _literature_import import (
            assess_full_text_acquisition,
            fulltext_structuring_admission_assessment,
        )
    sub_id = _normalized_subhypothesis_id(sub_hypothesis_id)
    gate = normalize_subhypothesis_full_text_gate_contract(gate_contract)
    alignment_contract = _alignment_contract_for_subhypothesis(project, sub_id)
    admitted: dict[str, dict[str, Any]] = {}
    preprints: dict[str, dict[str, Any]] = {}
    imported_fulltexts: set[str] = set()
    project_background_fulltexts: set[str] = set()
    related_fulltexts: dict[str, dict[str, Any]] = {}
    fulltext_epistemic_revalidation_by_identity: dict[str, dict[str, Any]] = {}
    portfolio_role_identities: dict[str, set[str]] = {
        role: set() for role in SUBHYPOTHESIS_EVIDENCE_PORTFOLIO_MINIMUMS
    }
    rejected = Counter()
    noncore_pool: dict[str, list[dict[str, Any]]] = {
        "method_context": [],
        "platform_context": [],
        "component_mechanism": [],
        "related_foundation": [],
        "boundary_context": [],
        "adverse_context": [],
    }
    metadata_only_auxiliary_pool: dict[str, list[dict[str, Any]]] = {
        "method_context": [],
        "platform_context": [],
        "component_mechanism": [],
        "related_foundation": [],
        "boundary_context": [],
        "adverse_context": [],
    }
    metadata_only_auxiliary_identities: set[str] = set()
    bound_fulltext_count = 0
    visual_scope_counts: Counter[str] = Counter()
    visual_evidence_count = 0

    for record in project.get("papergraph", []) if isinstance(project.get("papergraph"), list) else []:
        if not isinstance(record, dict):
            continue
        binding = _record_binding(record, sub_id)
        if not binding:
            continue
        identity = _paper_identity(record)
        if not identity:
            rejected["missing_identity"] += 1
            continue
        layer = _record_layer(record, binding)
        full_text = assess_full_text_acquisition(record)
        alignment = _alignment_for_binding(record, binding)
        project_background_only = _project_background_only_for_binding(
            record,
            binding,
            alignment,
        )
        corpus_related = bool(
            not project_background_only
            and (
                record.get("corpus_admitted") is True
                or alignment.get("corpus_admitted") is True
            )
        )
        corpus_target_counting = bool(
            not project_background_only
            and (
                record.get("corpus_target_counting_evidence") is True
                or binding.get("corpus_target_counting_evidence") is True
            )
        )
        related_to_current_sh = bool(
            not project_background_only
            and not alignment.get("off_topic")
            and not alignment.get("true_off_topic")
            and not alignment.get("exclusion_hits")
            and (
                corpus_target_counting
                or corpus_related
                or alignment.get("import_eligible") is True
                or alignment.get("core_eligible") is True
            )
        )
        if full_text.get("full_text_available") is not True:
            if (
                related_to_current_sh
                and layer in NON_PREPRINT_LAYERS
                and not _is_unpublished_preprint(record, layer)
            ):
                metadata_only_auxiliary_identities.add(identity)
                pool_name = _noncore_evidence_pool_name(record, alignment)
                metadata_only_auxiliary_pool.setdefault(pool_name, [])
                if len(metadata_only_auxiliary_pool[pool_name]) < 12:
                    metadata_only_auxiliary_pool[pool_name].append(
                        {
                            **_noncore_evidence_pool_item(
                                record,
                                alignment,
                                layer=layer,
                                full_text=full_text,
                            ),
                            "auxiliary_material_only": True,
                            "counts_toward_fulltext_gate": False,
                            "claim_strength_effect": "no_claim_strength_increase",
                            "reserve_status": str(
                                record.get("reserve_status")
                                or "METADATA_ONLY_IMPORTED_AWAITING_FULL_TEXT"
                            ),
                        }
                    )
                rejected["metadata_only_auxiliary"] += 1
            else:
                rejected["full_text_not_acquired"] += 1
                continue
            rejected["full_text_not_acquired"] += 1
            continue
        bound_fulltext_count += 1
        # Import/display accounting is intentionally broader than evidence-gate
        # accounting.  A successfully acquired non-preprint full text remains an
        # imported full text even when alignment or evidence-admission rules later
        # classify it as auxiliary/context-only.  Keep this identity-deduplicated
        # source of truth separate from ``admitted`` below.
        if layer in NON_PREPRINT_LAYERS and not _is_unpublished_preprint(record, layer):
            imported_fulltexts.add(identity)
            if project_background_only:
                project_background_fulltexts.add(identity)
        for visual in record.get("visual_evidence") or []:
            if not isinstance(visual, dict):
                continue
            visual_sub_id = _normalized_subhypothesis_id(
                visual.get("sub_hypothesis_id")
            )
            if visual_sub_id and visual_sub_id != sub_id:
                continue
            scope = str(
                visual.get("admission_scope")
                or visual.get("evidence_role")
                or "visual_project_background_only"
            )
            if scope not in {
                "visual_project_background_only",
                "visual_sh_local_auxiliary",
                "visual_component_bridge_candidate",
                "visual_core_candidate_pending_review",
            }:
                scope = "visual_project_background_only"
            visual_scope_counts[scope] += 1
            visual_evidence_count += 1
        # Full-text revalidation classifies every acquired, related candidate
        # before deciding whether it is direct core, support, or context.  It
        # must not disappear merely because metadata could not yet prove a
        # causal lane.
        try:
            from ._research_alignment import fulltext_epistemic_revalidation
        except ImportError:
            from _research_alignment import fulltext_epistemic_revalidation
        fulltext_epistemic_revalidation_by_identity[identity] = fulltext_epistemic_revalidation(
            record,
            epistemic_profile=(
                gate.get("epistemic_profile")
                if isinstance(gate.get("epistemic_profile"), dict)
                else {}
            ),
            standard_design=str(
                alignment.get("standard_research_design")
                or record.get("standard_research_design")
                or ""
            ),
        )
        if (
            related_to_current_sh
            and layer in NON_PREPRINT_LAYERS
            and not _is_unpublished_preprint(record, layer)
        ):
            related_fulltexts.setdefault(
                identity,
                {
                    "record": record,
                    "alignment": alignment,
                    "layer": layer,
                },
            )
        fulltext_structuring = fulltext_structuring_admission_assessment(record)
        if fulltext_structuring.get("eligible_for_evidence_admission") is not True:
            if corpus_related:
                pool_name = _noncore_evidence_pool_name(record, alignment)
                noncore_pool.setdefault(pool_name, [])
                if len(noncore_pool[pool_name]) < 12:
                    noncore_pool[pool_name].append(
                        _noncore_evidence_pool_item(
                            record,
                            alignment,
                            layer=layer,
                            full_text=full_text,
                        )
                    )
            rejected[
                "fulltext_pending_structuring"
                if fulltext_structuring.get("status")
                == "metadata_plus_fulltext_pending_structuring"
                else "fulltext_not_evidence_admissible"
            ] += 1
            continue
        portfolio_relevant = bool(
            corpus_related
            or alignment.get("import_eligible")
            or alignment.get("core_eligible")
        )
        if portfolio_relevant:
            for portfolio_role in _evidence_portfolio_roles(
                record,
                alignment,
                layer=layer,
            ):
                portfolio_role_identities.setdefault(portfolio_role, set()).add(
                    identity
                )
        bound_foundation = (
            binding.get("foundational_bridge_assessment")
            if isinstance(binding.get("foundational_bridge_assessment"), dict)
            else {}
        )
        foundation = bound_foundation or (
            record.get("foundational_bridge_assessment")
            if isinstance(record.get("foundational_bridge_assessment"), dict)
            else {}
        )
        foundation_sub_id = _normalized_subhypothesis_id(foundation.get("sub_hypothesis_id"))
        foundation_matches_binding = bool(
            foundation.get("bridge_eligible")
            and (bound_foundation or not foundation_sub_id or foundation_sub_id == sub_id)
        )
        aligned = bool(
            alignment.get("import_eligible")
            or alignment.get("core_eligible")
            or foundation_matches_binding
        )
        if not aligned:
            if corpus_related:
                reason = str(
                    record.get("corpus_admission_reason")
                    or alignment.get("corpus_admission_reason")
                    or "related_noncore"
                )
                rejected[f"corpus_related_noncounting:{reason}"] += 1
                pool_name = _noncore_evidence_pool_name(record, alignment)
                noncore_pool.setdefault(pool_name, [])
                if len(noncore_pool[pool_name]) < 12:
                    noncore_pool[pool_name].append(
                        _noncore_evidence_pool_item(
                            record,
                            alignment,
                            layer=layer,
                            full_text=full_text,
                        )
                    )
            else:
                rejected["subhypothesis_alignment_not_admitted"] += 1
            continue
        item = {
            "paper_id": str(record.get("paper_id") or ""),
            "identity": identity,
            "layer": layer,
            "title": str(record.get("title") or "")[:200],
            "alignment": alignment,
            "full_text": full_text,
            "fulltext_structuring": fulltext_structuring,
        }
        if _is_unpublished_preprint(record, layer):
            preprints.setdefault(identity, item)
            continue
        if layer not in NON_PREPRINT_LAYERS:
            rejected["unknown_nonpreprint_layer"] += 1
            continue
        item["is_review"] = _is_review(record, layer, alignment)
        type_evidence = alignment.get("type_directed_evidence") if isinstance(alignment.get("type_directed_evidence"), dict) else {}
        lane = str(alignment.get("evidence_lane") or type_evidence.get("evidence_lane") or "PENDING_FULLTEXT_TYPE_DIRECTED_EVIDENCE")
        item["evidence_lane"] = lane
        panel_meta = _record_panel_evidence_metadata(record, binding, alignment)
        item.update(panel_meta)
        item.update(_record_claim_effect_metadata(record, binding, alignment, item))
        panel_core_allowed = bool(
            not panel_meta.get("multi_entity_panel")
            or (
                panel_meta.get("panel_core_path") is True
                and panel_meta.get("panel_auxiliary_evidence_only") is not True
            )
        )
        item["direct_core"] = bool(
            alignment.get("core_eligible") is True
            and type_evidence.get("direct_evidence_eligible") is True
            and lane == "TYPE_DIRECTED_PRIMARY_SOURCE_EVIDENCE"
            and not item["is_review"]
            and panel_core_allowed
        )
        # A current V3 contract-bound source admission counts as core whether
        # the result supports, falsifies, bounds, measures, formalises, or
        # otherwise fills the RQ's declared evidence slot.
        if item["direct_core"]:
            portfolio_role_identities["direct_contract_core"].add(identity)
        standard_assessment = (
            alignment.get("standard_evidence_design")
            if isinstance(alignment.get("standard_evidence_design"), dict)
            else {}
        )
        if gate.get("evidence_standard_id") and not standard_assessment:
            try:
                from ._research_alignment import standard_evidence_design_assessment
            except ImportError:
                from _research_alignment import standard_evidence_design_assessment
            standard_assessment = standard_evidence_design_assessment(
                record,
                {
                    "id": str(gate.get("evidence_standard_id") or ""),
                    "accepted_core_designs": list(gate.get("standard_core_designs") or []),
                    "support_designs": list(gate.get("support_designs") or []),
                    "excluded_as_core": list(gate.get("excluded_as_core") or []),
                },
                research_design=str(alignment.get("research_design") or ""),
                causal_role=str(alignment.get("causal_role") or ""),
                paper_genre=(
                    alignment.get("paper_genre")
                    if isinstance(alignment.get("paper_genre"), dict)
                    else record.get("paper_genre")
                    if isinstance(record.get("paper_genre"), dict)
                    else {}
                ),
            )
        standard_design = str(
            alignment.get("standard_research_design")
            or standard_assessment.get("standard_research_design")
            or "unclassified"
        )
        standard_lane = str(
            alignment.get("standard_evidence_lane")
            or standard_assessment.get("standard_evidence_lane")
            or "UNCLASSIFIED_STANDARD_EVIDENCE"
        )
        item["standard_research_design"] = standard_design
        item["standard_evidence_lane"] = standard_lane
        item["standard_evidence_design"] = standard_assessment
        item["standard_core"] = bool(
            gate.get("evidence_standard_id")
            and (
                alignment.get("standard_core_eligible") is True
                or standard_assessment.get("core_design_match") is True
            )
            and not standard_assessment.get("excluded_as_core_reason")
            and not item["is_review"]
            and panel_core_allowed
        )
        # A direct core is defined by compatibility with this SH's declared
        # epistemic contract.  Causal-edge evidence remains one valid subtype,
        # but an observational likelihood, proof, derivation, or validated
        # simulation must not be discarded merely because it lacks an
        # intervention-shaped causal edge.
        item["compatible_direct_core"] = bool(
            item["direct_core"] or item["standard_core"]
        )
        item["epistemic_fulltext_revalidation"] = fulltext_epistemic_revalidation(
            record,
            epistemic_profile=(
                gate.get("epistemic_profile")
                if isinstance(gate.get("epistemic_profile"), dict)
                else {}
            ),
            standard_design=standard_design,
        )
        if corpus_related and not (item["direct_core"] or item["standard_core"]):
            pool_name = _noncore_evidence_pool_name(record, alignment)
            noncore_pool.setdefault(pool_name, [])
            if len(noncore_pool[pool_name]) < 12:
                noncore_pool[pool_name].append(
                    _noncore_evidence_pool_item(
                        record,
                        alignment,
                        layer=layer,
                        full_text=full_text,
                    )
                )
        admitted.setdefault(identity, item)

    layer_counts = Counter(str(item.get("layer") or "") for item in admitted.values())
    lane_counts = Counter(str(item.get("evidence_lane") or "") for item in admitted.values() if item.get("direct_core"))
    standard_design_counts = Counter(
        str(item.get("standard_research_design") or "unclassified")
        for item in admitted.values()
        if item.get("standard_core")
    )
    standard_lane_counts = Counter(
        str(item.get("standard_evidence_lane") or "UNCLASSIFIED_STANDARD_EVIDENCE")
        for item in admitted.values()
        if item.get("standard_core")
    )
    panel_items = [
        item for item in admitted.values()
        if item.get("multi_entity_panel")
    ]
    panel_auxiliary_items = [
        item for item in panel_items
        if item.get("panel_auxiliary_evidence_only")
    ]
    panel_component_auxiliary_items = [
        item for item in panel_items
        if item.get("panel_component_support_only")
    ]
    panel_level_core = sum(bool(item.get("direct_core")) for item in panel_items)
    panel_full_text_by_tier = Counter(
        str(item.get("panel_evidence_tier") or "unclassified")
        for item in panel_items
    )
    panel_auxiliary_by_role = Counter(
        str(
            item.get("panel_evidence_path_role")
            or item.get("evidence_lane")
            or "unclassified"
        )
        for item in panel_auxiliary_items
    )
    evidence_by_failure_scope = Counter(
        str(item.get("failure_scope") or "unclassified")
        for item in admitted.values()
        if item.get("failure_scope")
    )
    total = len(admitted)
    review_total = sum(bool(item.get("is_review")) for item in admitted.values())
    review_total_cap = max(
        0,
        int(
            gate.get("review_peer_reviewed_total_cap")
            if gate.get("review_peer_reviewed_total_cap") is not None
            else 2
        ),
    )
    review_gate_counting = min(review_total, review_total_cap)
    review_context_only = max(0, review_total - review_gate_counting)
    gate_counting_total = max(0, total - review_context_only)
    direct = sum(bool(item.get("direct_core")) for item in admitted.values())
    standard_core = sum(bool(item.get("standard_core")) for item in admitted.values())
    direct_core_identities = {
        identity
        for identity, item in admitted.items()
        if item.get("direct_core")
    }
    compatible_direct_core_identities = {
        identity
        for identity, item in admitted.items()
        if item.get("compatible_direct_core")
    }
    compatible_core_evidence_by_type: Counter[str] = Counter()
    for identity in compatible_direct_core_identities:
        core_item = admitted[identity]
        design = str(core_item.get("standard_research_design") or "").lower()
        lane = str(core_item.get("evidence_lane") or "").lower()
        if design in {
            "direct_observation", "survey_or_catalog_analysis", "mission_or_data_release",
            "time_domain_observation", "multi_messenger_observation",
            "parameter_likelihood_or_posterior_analysis", "cross_dataset_constraint",
            "statistical_model_comparison", "natural_experiment",
        }:
            evidence_type = "observational_constraint"
        elif design in {
            "analytical_derivation", "field_equation_solution", "consistency_analysis",
            "stability_analysis", "symmetry_argument", "limiting_case", "no_go_result",
            "numerical_solution", "observable_prediction",
        }:
            evidence_type = "theoretical_derivation"
        elif design in {
            "proof", "theorem", "lemma", "lemma_chain", "counterexample",
            "equivalence_result", "independence_result", "formally_verified_proof",
            "formal_proof", "formal_verification",
        }:
            evidence_type = "formal_proof"
        elif design in {
            "validated_simulation", "convergence_analysis", "benchmark_comparison",
            "parameter_sensitivity", "sensitivity_analysis", "uncertainty_propagation",
            "numerical_experiment", "computational_model_or_simulation",
        }:
            evidence_type = "simulation_validation"
        elif design in {
            "controlled_experiment", "intervention", "perturbation", "randomized_comparison",
            "randomized_or_controlled_trial", "perturbation_or_ablation", "dose_response",
            "mechanistic_rescue", "controlled_intervention",
        } or "causal" in lane or "mechanism" in lane:
            evidence_type = "causal_intervention"
        else:
            evidence_type = "compatible_direct_evidence"
        compatible_core_evidence_by_type[evidence_type] += 1
    theoretical_validity_by_status: Counter[str] = Counter()
    empirical_support_by_status: Counter[str] = Counter()
    fulltext_epistemic_classifications: list[dict[str, Any]] = []
    for identity, assessed_item in admitted.items():
        revalidation = (
            assessed_item.get("epistemic_fulltext_revalidation")
            if isinstance(assessed_item.get("epistemic_fulltext_revalidation"), dict)
            else {}
        )
        theoretical_status = str(revalidation.get("theoretical_validity") or "NOT_ASSESSED")
        empirical_status = str(revalidation.get("empirical_support") or "NOT_ASSESSED")
        theoretical_validity_by_status[theoretical_status] += 1
        empirical_support_by_status[empirical_status] += 1
        if len(fulltext_epistemic_classifications) < 30:
            fulltext_epistemic_classifications.append({
                "identity": identity,
                "title": str(assessed_item.get("title") or "")[:200],
                "compatible_direct_core": bool(assessed_item.get("compatible_direct_core")),
                "theoretical_validity": theoretical_status,
                "empirical_support": empirical_status,
                "checklist_id": str(revalidation.get("checklist_id") or ""),
                "classification": str(revalidation.get("classification") or ""),
                "standard_research_design": str(assessed_item.get("standard_research_design") or ""),
            })
    related_fulltext_epistemic_classifications = [
        {
            "identity": identity,
            "theoretical_validity": str(classification.get("theoretical_validity") or "NOT_ASSESSED"),
            "empirical_support": str(classification.get("empirical_support") or "NOT_ASSESSED"),
            "checklist_id": str(classification.get("checklist_id") or ""),
            "classification": str(classification.get("classification") or ""),
        }
        for identity, classification in fulltext_epistemic_revalidation_by_identity.items()
        if identity in related_fulltexts and isinstance(classification, dict)
    ][:50]
    imported_related_full_text_count = len(related_fulltexts)
    direct_contract_core_count = len(direct_core_identities)
    compatible_direct_core_count = len(compatible_direct_core_identities)
    standard_anchor_counts: Counter[str] = Counter()
    for definition in gate.get("evidence_standard_definitions") or []:
        if not isinstance(definition, dict):
            continue
        standard_id = str(definition.get("id") or "")
        anchor_key = standard_id.removesuffix("_v1").replace("_physics", "").replace("_inference", "") + "_anchor"
        accepted_designs = {str(value) for value in (definition.get("accepted_core_designs") or [])}
        standard_anchor_counts[anchor_key] = sum(
            1 for identity in compatible_direct_core_identities
            if str(admitted[identity].get("standard_research_design") or "") in accepted_designs
        )
    standard_anchor_minimums = {
        str(key): max(0, int(value or 0))
        for key, value in (gate.get("standard_anchor_minimums") or {}).items()
    }
    standard_anchor_shortfalls = {
        key: max(0, minimum - int(standard_anchor_counts.get(key.removesuffix("_min")) or 0))
        for key, minimum in standard_anchor_minimums.items()
    }
    noncore_related_full_text_count = max(
        0,
        imported_related_full_text_count
        - len(set(related_fulltexts) & compatible_direct_core_identities),
    )
    imported_full_text_by_layer = Counter(
        str(item.get("layer") or "")
        for item in related_fulltexts.values()
    )
    core_full_text_by_layer = Counter(
        str(item.get("layer") or "")
        for identity, item in admitted.items()
        if identity in compatible_direct_core_identities
    )
    imported_full_text_by_evidence_tier: Counter[str] = Counter()
    noncore_full_text_by_role: Counter[str] = Counter()
    for identity, related_item in related_fulltexts.items():
        record = (
            related_item.get("record")
            if isinstance(related_item.get("record"), dict)
            else {}
        )
        alignment = (
            related_item.get("alignment")
            if isinstance(related_item.get("alignment"), dict)
            else {}
        )
        if identity in compatible_direct_core_identities:
            tier = "CORE_COMPATIBLE_DIRECT"
            reporting_role = ""
        else:
            tier, reporting_role = _related_fulltext_reporting_role(
                record,
                alignment,
                layer=str(related_item.get("layer") or ""),
            )
        imported_full_text_by_evidence_tier[tier] += 1
        if identity not in compatible_direct_core_identities:
            noncore_full_text_by_role[reporting_role] += 1
    noncore_pool_counts = {
        key: len(value)
        for key, value in sorted(noncore_pool.items())
    }
    noncore_total = sum(noncore_pool_counts.values())
    metadata_only_auxiliary_counts = {
        key: len(value)
        for key, value in sorted(metadata_only_auxiliary_pool.items())
    }
    metadata_only_auxiliary_total = len(metadata_only_auxiliary_identities)
    auxiliary_material_counts = dict(noncore_pool_counts)
    for key, value in metadata_only_auxiliary_counts.items():
        auxiliary_material_counts[key] = int(auxiliary_material_counts.get(key) or 0) + int(value or 0)
    auxiliary_material_total = noncore_total + metadata_only_auxiliary_total
    portfolio_minimums = {
        str(role): max(0, int(minimum or 0))
        for role, minimum in (
            gate.get("evidence_portfolio_minimums")
            or SUBHYPOTHESIS_EVIDENCE_PORTFOLIO_MINIMUMS
        ).items()
    }
    portfolio_counts = {
        role: len(portfolio_role_identities.get(role) or set())
        for role in portfolio_minimums
    }
    portfolio_shortfalls = {
        role: max(0, minimum - int(portfolio_counts.get(role) or 0))
        for role, minimum in portfolio_minimums.items()
    }
    portfolio_role_families_present = sum(
        int(count or 0) > 0 for count in portfolio_counts.values()
    )
    portfolio_policy_active = bool(gate.get("evidence_portfolio_policy_active"))
    portfolio_ready = bool(
        not portfolio_policy_active
        or all(shortfall == 0 for shortfall in portfolio_shortfalls.values())
    )
    noncore_missing_axis_counts = Counter(
        axis
        for items in noncore_pool.values()
        for item in items
        for axis in (item.get("missing_contract_requirements") or [])
    )
    core_items = [
        item for item in admitted.values()
        if bool(item.get("direct_core") or item.get("standard_core"))
    ]
    core_polarity_counts = Counter(
        str(item.get("evidence_polarity") or "unclear")
        for item in core_items
    )
    direct_core_polarity_counts = Counter(
        str(item.get("evidence_polarity") or "unclear")
        for item in admitted.values()
        if item.get("direct_core")
    )
    standard_core_polarity_counts = Counter(
        str(item.get("evidence_polarity") or "unclear")
        for item in admitted.values()
        if item.get("standard_core")
    )
    supportive_core = int(core_polarity_counts.get("supportive") or 0)
    opposing_core = int(core_polarity_counts.get("opposing") or 0)
    boundary_core = int(core_polarity_counts.get("boundary") or 0)
    mixed_core = int(core_polarity_counts.get("mixed") or 0)
    unclear_core = int(core_polarity_counts.get("unclear") or 0)
    claim_strength_modifier = _claim_strength_modifier_from_core_counts(
        supportive_core=supportive_core,
        opposing_core=opposing_core,
        boundary_core=boundary_core,
        mixed_core=mixed_core,
        unclear_core=unclear_core,
    )
    layer_minimums = dict(gate.get("layer_minimums") or {})
    layer_shortfalls = {
        layer: max(0, int(layer_minimums.get(layer) or 0) - int(layer_counts.get(layer) or 0))
        for layer in NON_PREPRINT_LAYERS
    }
    layer_preferred_targets = dict(gate.get("layer_preferred_targets") or {})
    layer_preferred_shortfalls = {
        layer: max(
            0,
            int(layer_preferred_targets.get(layer) or 0) - int(layer_counts.get(layer) or 0),
        )
        for layer in NON_PREPRINT_LAYERS
    }
    total_target = int(
        gate.get("peer_reviewed_full_text_target")
        or SUBHYPOTHESIS_IMPORTED_FULL_TEXT_TARGET
    )
    imported_full_text_target = int(
        gate.get("imported_full_text_target") or total_target
    )
    imported_related_full_text_target = int(
        gate.get("imported_related_full_text_target")
        or gate.get("imported_full_text_target")
        or SUBHYPOTHESIS_IMPORTED_FULL_TEXT_TARGET
    )
    direct_contract_core_target = int(gate.get("direct_contract_core_target") or 1)
    direct_target_raw = gate.get("direct_core_full_text_target")
    direct_target = int(direct_target_raw) if direct_target_raw is not None else 1
    standard_core_target = int(gate.get("standard_core_full_text_target") or 0)
    # A source can contribute a contract-bound evidence slot without being a
    # universal causal-chain paper.  Evaluate all acquired SH-local sources
    # against the current V3 research-question evidence contract.
    try:
        from ._type_directed_evidence_bundle import evaluate_type_directed_evidence_bundle
    except ImportError:
        from _type_directed_evidence_bundle import evaluate_type_directed_evidence_bundle
    type_directed_evidence_bundle = evaluate_type_directed_evidence_bundle(
        project,
        sub_id,
        [
            {
                "identity": identity,
                "record": related_item.get("record") if isinstance(related_item.get("record"), dict) else {},
                "alignment": related_item.get("alignment") if isinstance(related_item.get("alignment"), dict) else {},
                "layer": str(related_item.get("layer") or ""),
            }
            for identity, related_item in related_fulltexts.items()
            if isinstance(related_item, dict)
        ],
        alignment_contract=alignment_contract,
    )
    bundle_status = str(type_directed_evidence_bundle.get("status") or "")
    bundle_research_question_ready = bool(
        type_directed_evidence_bundle.get("research_question_ready")
    )
    bundle_core_ready = bool(
        type_directed_evidence_bundle.get("core_contract_evidence_ready")
    )
    bundle_partial_ready = bool(
        type_directed_evidence_bundle.get("partial_contract_evidence_ready")
    )
    contract_repair_recommended = bool(
        bound_fulltext_count > 0
        and imported_related_full_text_count > 0
        and direct == 0
        and standard_core == 0
        and noncore_total > 0
        and not bundle_research_question_ready
    )
    contract_too_narrow_audit = {
        "schema_version": "subhypothesis_contract_too_narrow_audit_v2",
        "contract_repair_recommended": contract_repair_recommended,
        "reason": (
            "related fulltexts do not yet supply a source-bound bundle for the declared contract slots; inspect slot coverage and source admission before narrowing the SH contract"
            if contract_repair_recommended
            else ""
        ),
        "fulltext_acquired": bound_fulltext_count,
        "corpus_related_fulltext": imported_related_full_text_count,
        "direct_core_fulltext": direct,
        "standard_core_fulltext": standard_core,
        "noncore_evidence_total": noncore_total,
        "metadata_only_auxiliary_total": metadata_only_auxiliary_total,
        "metadata_only_auxiliary_counts": metadata_only_auxiliary_counts,
        "noncore_pool_counts": noncore_pool_counts,
        "auxiliary_material_total": auxiliary_material_total,
        "auxiliary_material_counts": auxiliary_material_counts,
        "missing_core_axis_counts": dict(sorted(noncore_missing_axis_counts.items())),
        "audit_questions": [
            "scientific_object 是否过窄或缺少语义同义词？",
            "aliases 是否缺失关键方法、材料、平台、模型或人群表达？",
            "evidence_contract 是否把方法/平台论文误要求成不适用的核心证据？",
            "dependent_variables 是否过度具体、占位式或与检索文献错配？",
            "L1/foundation 是否错误要求完整因果链？",
            "evidence_path role 是否错配为 core 而不是 method/platform/foundation？",
            "exclusion terms 是否误排父问题相关对象、互补技术或 mediator？",
        ],
        "suggested_relaxation": (
            [
                "allow method_or_platform_context and related_foundation as auxiliary/noncore corpus evidence",
                "add missing scientific_object aliases from repeated corpus-related records",
                "move platform-only papers to foundational_platform_evidence or method_context",
                "reclassify source-bound component evidence by the declared gap type and contract slot before treating it as non-core",
                "require comparability only when the active gap-type contract declares it",
                "keep source provenance, SH-local object identity, and cross-paper compatibility strict",
            ]
            if contract_repair_recommended
            else []
        ),
    }
    return {
        "schema_version": "subhypothesis_full_text_coverage_v5",
        "sub_hypothesis_id": sub_id,
        "alignment_contract_available": bool(alignment_contract),
        "type_directed_evidence_bundle": type_directed_evidence_bundle,
        "type_directed_evidence_bundle_status": bundle_status,
        "research_question_evidence_ready": bundle_research_question_ready,
        "type_directed_bundle_core_ready": bundle_core_ready,
        "partial_contract_evidence_ready": bundle_partial_ready,
        "imported_full_text_count": len(imported_fulltexts),
        "project_background_only_full_text_count": len(project_background_fulltexts),
        "sh_local_imported_full_text_count": max(
            0,
            len(imported_fulltexts) - len(project_background_fulltexts),
        ),
        "imported_full_text_target": imported_full_text_target,
        "imported_full_text_shortfall": max(
            0,
            imported_full_text_target - len(imported_fulltexts),
        ),
        "imported_related_full_text_count": imported_related_full_text_count,
        "imported_related_full_text": imported_related_full_text_count,
        "imported_related_full_text_target": imported_related_full_text_target,
        "imported_related_full_text_shortfall": max(
            0,
            imported_related_full_text_target
            - imported_related_full_text_count,
        ),
        "direct_contract_core_count": direct_contract_core_count,
        "direct_contract_core_target": direct_contract_core_target,
        "direct_contract_core_shortfall": max(
            0,
            direct_contract_core_target - direct_contract_core_count,
        ),
        "type_directed_bundle_shortfall": (
            0 if bundle_research_question_ready else 1
        ),
        "compatible_direct_core_count": compatible_direct_core_count,
        "compatible_direct_core_target": direct_contract_core_target,
        "compatible_direct_core_shortfall": max(
            0,
            direct_contract_core_target - compatible_direct_core_count,
        ),
        "core_evidence_by_type": dict(sorted(compatible_core_evidence_by_type.items())),
        "theoretical_validity_by_status": dict(sorted(theoretical_validity_by_status.items())),
        "empirical_support_by_status": dict(sorted(empirical_support_by_status.items())),
        "theoretical_validity_core_count": int(theoretical_validity_by_status.get("CORE") or 0),
        "empirical_support_core_count": int(empirical_support_by_status.get("CORE") or 0),
        "fulltext_epistemic_classifications": fulltext_epistemic_classifications,
        "related_fulltext_epistemic_classifications": related_fulltext_epistemic_classifications,
        "standard_anchor_counts": dict(sorted(standard_anchor_counts.items())),
        "standard_anchor_minimums": standard_anchor_minimums,
        "standard_anchor_shortfalls": standard_anchor_shortfalls,
        "noncore_related_full_text_count": noncore_related_full_text_count,
        "noncore_related_full_text": noncore_related_full_text_count,
        "peer_reviewed_full_text_count": total,
        "raw_peer_reviewed_full_text_count": total,
        "gate_counting_peer_reviewed_full_text_count": gate_counting_total,
        "peer_reviewed_full_text_target": total_target,
        "peer_reviewed_full_text_shortfall": max(
            0,
            imported_full_text_target - len(imported_fulltexts),
        ),
        "admitted_peer_reviewed_full_text_shortfall": max(
            0,
            total_target - gate_counting_total,
        ),
        "gate_counting_peer_reviewed_full_text_shortfall": max(0, total_target - gate_counting_total),
        "raw_peer_reviewed_full_text_shortfall": max(0, total_target - total),
        "review_full_text_count": review_total,
        "review_peer_reviewed_total_cap": review_total_cap,
        "review_full_text_gate_counting_count": review_gate_counting,
        "review_full_text_context_only_count": review_context_only,
        "direct_core_full_text_count": direct,
        "direct_core_full_text_target": direct_target,
        "direct_core_full_text_shortfall": max(0, direct_target - direct),
        "standard_core_full_text_count": standard_core,
        "standard_core_full_text_target": standard_core_target,
        "standard_core_full_text_shortfall": (
            max(0, standard_core_target - standard_core)
            if standard_core_target > 0
            else 0
        ),
        "corpus_related_full_text_count": imported_related_full_text_count,
        "visual_evidence_count": visual_evidence_count,
        "visual_project_background_only_count": int(
            visual_scope_counts.get("visual_project_background_only") or 0
        ),
        "visual_sh_local_auxiliary_count": int(
            visual_scope_counts.get("visual_sh_local_auxiliary") or 0
        ),
        "visual_component_bridge_candidate_count": int(
            visual_scope_counts.get("visual_component_bridge_candidate") or 0
        ),
        "visual_core_candidate_pending_review_count": int(
            visual_scope_counts.get("visual_core_candidate_pending_review") or 0
        ),
        "visual_evidence_counts_toward_gate": False,
        "visual_evidence_gate_policy": "candidate_only_until_human_review",
        "imported_full_text_by_layer": {
            layer: int(imported_full_text_by_layer.get(layer) or 0)
            for layer in NON_PREPRINT_LAYERS
        },
        "core_full_text_by_layer": {
            layer: int(core_full_text_by_layer.get(layer) or 0)
            for layer in NON_PREPRINT_LAYERS
        },
        "noncore_full_text_by_role": dict(
            sorted(noncore_full_text_by_role.items())
        ),
        "imported_full_text_by_evidence_tier": dict(
            sorted(imported_full_text_by_evidence_tier.items())
        ),
        "noncore_evidence_pool": noncore_pool,
        "noncore_evidence_pool_counts": noncore_pool_counts,
        "noncore_evidence_total": noncore_total,
        "metadata_only_auxiliary_pool": metadata_only_auxiliary_pool,
        "metadata_only_auxiliary_counts": metadata_only_auxiliary_counts,
        "metadata_only_auxiliary_total": metadata_only_auxiliary_total,
        "metadata_only_auxiliary_paper_ids": sorted(metadata_only_auxiliary_identities),
        "auxiliary_material_total": auxiliary_material_total,
        "auxiliary_material_counts": auxiliary_material_counts,
        "evidence_portfolio_policy_active": portfolio_policy_active,
        "evidence_portfolio_minimums": portfolio_minimums,
        "evidence_portfolio_counts": portfolio_counts,
        "evidence_portfolio_shortfalls": portfolio_shortfalls,
        "evidence_portfolio_role_families_present": (
            portfolio_role_families_present
        ),
        "evidence_portfolio_ready": portfolio_ready,
        "noncore_missing_contract_requirement_counts": dict(
            sorted(noncore_missing_axis_counts.items())
        ),
        "contract_too_narrow_audit": contract_too_narrow_audit,
        "contract_repair_recommended": contract_repair_recommended,
        "supportive_core_count": supportive_core,
        "opposing_core_count": opposing_core,
        "boundary_core_count": boundary_core,
        "mixed_core_count": mixed_core,
        "unclear_core_count": unclear_core,
        "core_full_text_by_evidence_polarity": dict(sorted(core_polarity_counts.items())),
        "direct_core_by_evidence_polarity": dict(sorted(direct_core_polarity_counts.items())),
        "standard_core_by_evidence_polarity": dict(sorted(standard_core_polarity_counts.items())),
        "claim_strength_modifier": claim_strength_modifier,
        "standard_core_by_design": dict(sorted(standard_design_counts.items())),
        "standard_core_by_evidence_lane": dict(sorted(standard_lane_counts.items())),
        "panel_level_core_full_text_count": int(panel_level_core),
        "panel_auxiliary_full_text_count": len(panel_auxiliary_items),
        "panel_component_auxiliary_full_text_count": len(panel_component_auxiliary_items),
        "panel_full_text_by_evidence_tier": dict(sorted(panel_full_text_by_tier.items())),
        "panel_component_auxiliary_by_path_role": dict(sorted(panel_auxiliary_by_role.items())),
        "full_text_by_evidence_path_failure_scope": dict(sorted(evidence_by_failure_scope.items())),
        "panel_integrative_core_missing": bool(
            panel_items
            and panel_level_core == 0
            and panel_auxiliary_items
        ),
        "panel_component_only_gap_hint": (
            "component mechanisms are individually supported, but integrated panel-level validation is missing"
            if panel_items and panel_level_core == 0 and panel_auxiliary_items
            else ""
        ),
        "evidence_standard_id": str(gate.get("evidence_standard_id") or ""),
        "epistemic_profile": (
            dict(gate.get("epistemic_profile") or {})
            if isinstance(gate.get("epistemic_profile"), dict)
            else {}
        ),
        "claim_strength_cap": str(gate.get("claim_strength_cap") or ""),
        # Backward-compatible display name: this now means every imported,
        # related, usable full text, not only the narrower admitted-core set.
        "full_text_by_layer": {
            layer: int(imported_full_text_by_layer.get(layer) or 0)
            for layer in NON_PREPRINT_LAYERS
        },
        "layer_minimums": layer_minimums,
        "layer_shortfalls": layer_shortfalls,
        "layer_preferred_targets": layer_preferred_targets,
        "layer_preferred_shortfalls": layer_preferred_shortfalls,
        "direct_core_by_evidence_lane": dict(sorted(lane_counts.items())),
        "preprint_full_text_count": len(preprints),
        "preprints_count_toward_peer_reviewed_target": False,
        "unique_imported_related_paper_ids": [
            str(
                (
                    item.get("record")
                    if isinstance(item.get("record"), dict)
                    else {}
                ).get("paper_id")
                or identity
            )
            for identity, item in related_fulltexts.items()
        ],
        "unique_admitted_paper_ids": [str(item.get("paper_id") or "") for item in admitted.values()],
        "rejected_record_counts": dict(sorted(rejected.items())),
        "gate_contract": gate,
    }


def _subhypothesis_readiness_gate_checks(coverage: dict[str, Any]) -> dict[str, Any]:
    """Evaluate the SH import workflow gate and claim-core diagnostics.

    Layer mix, standard-design counts, alignment conversion, evidence lanes,
    and role diversity remain available below as quality diagnostics.  They
    must never change workflow readiness or produce blocking failure classes.
    Direct/compatible core evidence is retained as a strict claim-strength
    diagnostic, not as a blocker for downstream gap analysis.
    """

    imported_related_target = max(
        1,
        int(
            coverage.get("imported_related_full_text_target")
            or coverage.get("imported_full_text_target")
            or coverage.get("peer_reviewed_full_text_target")
            or SUBHYPOTHESIS_IMPORTED_FULL_TEXT_TARGET
        ),
    )
    explicit_related_count = any(
        coverage.get(key) is not None
        for key in (
            "imported_related_full_text_count",
            "imported_related_full_text",
            "corpus_related_full_text_count",
            "imported_full_text_count",
            "gate_counting_peer_reviewed_full_text_count",
            "peer_reviewed_full_text_count",
        )
    )
    imported_related_count = int(
        coverage.get("imported_related_full_text_count")
        if coverage.get("imported_related_full_text_count") is not None
        else coverage.get("imported_related_full_text")
        if coverage.get("imported_related_full_text") is not None
        else coverage.get("corpus_related_full_text_count")
        if coverage.get("corpus_related_full_text_count") is not None
        else coverage.get("imported_full_text_count")
        if coverage.get("imported_full_text_count") is not None
        else coverage.get("gate_counting_peer_reviewed_full_text_count")
        if coverage.get("gate_counting_peer_reviewed_full_text_count") is not None
        else coverage.get("peer_reviewed_full_text_count")
        or 0
    )
    if not explicit_related_count and coverage.get("peer_reviewed_full_text_shortfall") is not None:
        imported_related_count = max(
            0,
            imported_related_target
            - int(coverage.get("peer_reviewed_full_text_shortfall") or 0),
        )
    total_shortfall = max(
        0,
        imported_related_target - imported_related_count,
    )
    total_pass = total_shortfall == 0

    explicit_core_count = any(
        coverage.get(key) is not None
        for key in (
            "compatible_direct_core_count",
            "direct_contract_core_count",
            "direct_core_full_text_count",
        )
    )
    compatible_direct_core_count = int(
        coverage.get("compatible_direct_core_count")
        if coverage.get("compatible_direct_core_count") is not None
        else coverage.get("direct_contract_core_count")
        if coverage.get("direct_contract_core_count") is not None
        else coverage.get("direct_core_full_text_count")
        or 0
    )
    direct_core_not_applicable = bool(
        coverage.get("direct_core_evidence_allowed") is False
        or (
            isinstance(coverage.get("gate_contract"), dict)
            and coverage["gate_contract"].get("direct_core_evidence_allowed") is False
        )
    )
    compatible_direct_core_target = (
        0 if direct_core_not_applicable else max(
            1,
            int(coverage.get("compatible_direct_core_target") or coverage.get("direct_contract_core_target") or 1),
        )
    )
    if not explicit_core_count and coverage.get("direct_core_full_text_shortfall") is not None:
        compatible_direct_core_count = (
            compatible_direct_core_target
            if int(coverage.get("direct_core_full_text_shortfall") or 0) == 0
            else 0
        )
    compatible_direct_core_shortfall = max(
        0,
        compatible_direct_core_target - compatible_direct_core_count,
    )
    type_directed_bundle = (
        coverage.get("type_directed_evidence_bundle")
        if isinstance(coverage.get("type_directed_evidence_bundle"), dict)
        else {}
    )
    type_directed_bundle_status = str(
        type_directed_bundle.get("status")
        or coverage.get("type_directed_evidence_bundle_status")
        or ""
    )
    research_question_evidence_ready = bool(
        type_directed_bundle.get("research_question_ready")
        or coverage.get("research_question_evidence_ready")
    )
    type_directed_bundle_core_ready = bool(
        type_directed_bundle.get("core_contract_evidence_ready")
        or coverage.get("type_directed_bundle_core_ready")
    )
    partial_contract_evidence_ready = bool(
        type_directed_bundle.get("partial_contract_evidence_ready")
        or coverage.get("partial_contract_evidence_ready")
    )
    direct_core_count = int(coverage.get("direct_core_full_text_count") or 0)
    standard_core_count = int(coverage.get("standard_core_full_text_count") or 0)
    supportive_core_count = int(coverage.get("supportive_core_count") or 0)
    direct_supportive_core_available = bool(
        supportive_core_count >= 1
        and (
            compatible_direct_core_count >= 1
            or direct_core_count >= 1
            or standard_core_count >= 1
        )
    )
    gate_contract = (
        coverage.get("gate_contract")
        if isinstance(coverage.get("gate_contract"), dict)
        else {}
    )
    gate_contract_current = not bool(
        gate_contract.get("contract_rebuild_required")
    )
    maturity_contract = dict(gate_contract)
    if coverage.get("direct_core_evidence_allowed") is False:
        maturity_contract["direct_core_evidence_allowed"] = False
    if coverage.get("object_maturity_retrieval_mode"):
        maturity_contract["object_maturity_retrieval_mode"] = str(
            coverage.get("object_maturity_retrieval_mode") or ""
        )
    if coverage.get("object_maturity_status"):
        maturity_contract["object_maturity_status"] = str(
            coverage.get("object_maturity_status") or ""
        )
    direct_core_allowed_by_maturity = _direct_core_allowed_by_object_maturity(
        maturity_contract
    )
    standard_anchor_shortfalls = {
        str(key): int(value or 0)
        for key, value in (coverage.get("standard_anchor_shortfalls") or {}).items()
    }
    compatible_direct_core_pass = bool(
        compatible_direct_core_shortfall == 0
        and all(value == 0 for value in standard_anchor_shortfalls.values())
    )
    if not direct_core_allowed_by_maturity:
        # Component/bridge/boundary retrieval can produce papers that look
        # "compatible" with a future-object contract.  Those records are useful
        # for restricted gap synthesis, but the object-maturity preflight has
        # explicitly disallowed direct-core validation.  Never let the
        # compatibility counter promote a branch into strict/core readiness.
        compatible_direct_core_pass = False
    # A source-bound bundle composes contract slots across papers; it does not
    # impose a causal-chain shape on non-mechanism questions.
    evidence_bundle_pass = bool(
        research_question_evidence_ready
        and direct_core_allowed_by_maturity
    )
    core_evidence_pass = bool(compatible_direct_core_pass or evidence_bundle_pass)
    effective_core_shortfall = 0 if core_evidence_pass else max(
        1,
        compatible_direct_core_shortfall,
    )

    # Legacy/standard-core targets are diagnostics only.
    standard_core_target = int(coverage.get("standard_core_full_text_target") or 0)
    uses_standard_core = standard_core_target > 0
    standard_or_direct_core_pass = bool(
        int(coverage.get("standard_core_full_text_shortfall") or 0) == 0
        if uses_standard_core
        else int(coverage.get("direct_core_full_text_shortfall") or 0) == 0
    )
    portfolio_shortfalls = dict(
        coverage.get("evidence_portfolio_shortfalls") or {}
    )
    portfolio_policy_active = bool(
        coverage.get("evidence_portfolio_policy_active")
    )
    portfolio_pass = bool(
        not portfolio_policy_active
        or coverage.get("evidence_portfolio_ready") is True
        or (
            portfolio_shortfalls
            and all(int(value or 0) == 0 for value in portfolio_shortfalls.values())
        )
    )
    layer_shortfalls = dict(coverage.get("layer_shortfalls") or {})
    preferred_shortfalls = dict(coverage.get("layer_preferred_shortfalls") or {})
    layers_pass = all(int(value or 0) == 0 for value in layer_shortfalls.values())
    quality_diagnostics_met = bool(
        (standard_or_direct_core_pass or type_directed_bundle_core_ready)
        and portfolio_pass and layers_pass
    )
    # The imported related-full-text target is a portfolio-saturation goal,
    # not a veto over a source-bound, cross-paper contract assessment.  A
    # partially supported contract can enter gap synthesis while its
    # portfolio remains incomplete; the shortfall stays visible as a quality
    # diagnostic and a retrieval-planning signal.
    partial_contract_workflow_override = bool(
        gate_contract_current and partial_contract_evidence_ready
    )
    release_gate_pass = bool(
        gate_contract_current and (total_pass or partial_contract_workflow_override)
    )
    strict_passes = bool(
        gate_contract_current and (total_pass or partial_contract_workflow_override)
        and (core_evidence_pass or partial_contract_evidence_ready)
    )
    passes = release_gate_pass
    readiness_basis: list[str] = []
    if total_pass and gate_contract_current:
        readiness_basis.append("imported_related_full_text_total")
    if partial_contract_workflow_override and not total_pass:
        readiness_basis.append("partial_contract_evidence_overrides_portfolio_saturation")
    if compatible_direct_core_pass:
        readiness_basis.append("compatible_direct_core")
    if type_directed_bundle_core_ready:
        readiness_basis.append("cross_paper_contract_evidence_bundle")
    elif partial_contract_evidence_ready:
        readiness_basis.append("cross_paper_partial_contract_evidence")
    return {
        "total_pass": total_pass,
        "total_shortfall": total_shortfall,
        "imported_related_full_text_count": imported_related_count,
        "imported_related_full_text_target": imported_related_target,
        "release_gate_pass": release_gate_pass,
        "partial_contract_workflow_override": partial_contract_workflow_override,
        "gate_contract_current": gate_contract_current,
        "gate_contract_rebuild_reason": str(
            gate_contract.get("contract_rebuild_reason") or ""
        ),
        "direct_supportive_core_available": direct_supportive_core_available,
        "uses_standard_core": uses_standard_core,
        "core_shortfall_key": "type_directed_bundle_shortfall",
        "core_pass": core_evidence_pass,
        "standard_or_direct_core_pass": standard_or_direct_core_pass,
        "compatible_direct_core_pass": compatible_direct_core_pass,
        "compatible_direct_core_shortfall": compatible_direct_core_shortfall,
        "compatible_direct_core_count": compatible_direct_core_count,
        "compatible_direct_core_target": compatible_direct_core_target,
        "direct_core_validation_allowed": direct_core_allowed_by_maturity,
        "direct_core_disallowed_by_object_maturity": not direct_core_allowed_by_maturity,
        "standard_anchor_shortfalls": standard_anchor_shortfalls,
        "direct_contract_core_pass": core_evidence_pass,
        "direct_contract_core_shortfall": effective_core_shortfall,
        "direct_contract_core_count": int(coverage.get("direct_contract_core_count") or 0),
        "direct_contract_core_target": int(coverage.get("direct_contract_core_target") or compatible_direct_core_target),
        "type_directed_evidence_bundle_status": type_directed_bundle_status,
        "type_directed_evidence_bundle_pass": evidence_bundle_pass,
        "type_directed_bundle_core_ready": type_directed_bundle_core_ready,
        "partial_contract_evidence_ready": partial_contract_evidence_ready,
        "type_directed_bundle_shortfall": 0 if evidence_bundle_pass else 1,
        "portfolio_policy_active": portfolio_policy_active,
        "portfolio_pass": portfolio_pass,
        "portfolio_shortfalls": portfolio_shortfalls,
        "layers_pass": layers_pass,
        "layer_minimums_met": layers_pass,
        "quality_diagnostics_met": quality_diagnostics_met,
        "strict_passes": strict_passes,
        "passes": passes,
        "readiness_basis": readiness_basis,
        "preferred_shortfalls": preferred_shortfalls,
        "layer_shortfalls": layer_shortfalls,
    }


def evaluate_subhypothesis_retrieval_readiness(coverage: dict[str, Any]) -> dict[str, Any]:
    gate_checks = _subhypothesis_readiness_gate_checks(coverage)
    total_pass = bool(gate_checks["total_pass"])
    uses_standard_core = bool(gate_checks["uses_standard_core"])
    core_pass = bool(gate_checks["core_pass"])
    layers_pass = bool(gate_checks["layers_pass"])
    passes = bool(gate_checks["passes"])
    strict_passes = bool(gate_checks["strict_passes"])
    release_gate_pass = bool(gate_checks.get("release_gate_pass"))
    direct_supportive_core_available = bool(
        gate_checks.get("direct_supportive_core_available")
    )
    layer_shortfalls = dict(gate_checks["layer_shortfalls"])
    preferred_shortfalls = dict(gate_checks["preferred_shortfalls"])
    # Evidence readiness is reported independently from corpus readiness:
    # a compatible single-paper core or a cross-paper evidence bundle can be
    # scientifically meaningful before the ten-paper corpus is complete, but
    # neither bypasses the corpus release gate.
    claim_core_ready = bool(core_pass)
    total_only_pass = bool(total_pass and not claim_core_ready)
    workflow_passes = bool(release_gate_pass)
    review_context_only = int(coverage.get("review_full_text_context_only_count") or 0)
    review_total = int(coverage.get("review_full_text_count") or 0)
    gate_counting_total = int(
        coverage.get("gate_counting_peer_reviewed_full_text_count")
        if coverage.get("gate_counting_peer_reviewed_full_text_count") is not None
        else coverage.get("peer_reviewed_full_text_count")
        or 0
    )
    context_heavy = bool(
        review_context_only > 0
        or (
            review_total > 0
            and gate_counting_total > 0
            and review_total / max(1, int(coverage.get("peer_reviewed_full_text_count") or gate_counting_total)) >= 0.35
        )
    )
    claim_strength_modifier = (
        dict(coverage.get("claim_strength_modifier") or {})
        if isinstance(coverage.get("claim_strength_modifier"), dict)
        else {}
    )
    polarity_verdict = str(claim_strength_modifier.get("verdict") or "")
    polarity_strength_cap = (
        "mixed_or_condition_dependent"
        if polarity_verdict == "mixed_or_condition_dependent"
        else "opposing_evidence_limits_primary_claim"
        if polarity_verdict == "primarily_opposing_or_reversal"
        else "conditional_or_boundary_limited"
        if polarity_verdict in {"conditional_or_boundary_limited", "boundary_only"}
        else ""
    )
    evidence_strength_cap = (
        "partial_contract_evidence_missing_required_slots"
        if bool(gate_checks.get("partial_contract_evidence_ready"))
        else "weak_context_heavy_total_only"
        if total_only_pass and context_heavy
        else "soft_total_only_non_core"
        if total_only_pass
        else polarity_strength_cap
        if polarity_strength_cap
        else str(coverage.get("claim_strength_cap") or "")
    )
    direct_core_count = int(coverage.get("direct_core_full_text_count") or 0)
    standard_core_count = int(coverage.get("standard_core_full_text_count") or 0)
    # Readiness is based on evidence directly compatible with the declared
    # contract slots.  Causal papers are one subtype; measurement validation,
    # proofs, boundary comparisons, and benchmarks are equally direct when
    # their gap-type contract declares them.
    core_evidence_count = int(
        coverage.get("compatible_direct_core_count")
        if coverage.get("compatible_direct_core_count") is not None
        else coverage.get("direct_contract_core_count")
        if coverage.get("direct_contract_core_count") is not None
        else direct_core_count
    )
    type_directed_bundle = (
        coverage.get("type_directed_evidence_bundle")
        if isinstance(coverage.get("type_directed_evidence_bundle"), dict)
        else {}
    )
    type_directed_bundle_status = str(
        gate_checks.get("type_directed_evidence_bundle_status")
        or type_directed_bundle.get("status")
        or ""
    )
    type_directed_bundle_core_ready = bool(
        gate_checks.get("type_directed_bundle_core_ready")
    )
    partial_contract_evidence_ready = bool(
        gate_checks.get("partial_contract_evidence_ready")
    )
    type_directed_bundle_slot_count = int(
        type_directed_bundle.get("source_bound_slot_support_count") or 0
    )
    noncore_total = int(coverage.get("noncore_evidence_total") or 0)
    metadata_only_auxiliary_total = int(
        coverage.get("metadata_only_auxiliary_total") or 0
    )
    auxiliary_material_total = int(
        coverage.get("auxiliary_material_total")
        if coverage.get("auxiliary_material_total") is not None
        else noncore_total + metadata_only_auxiliary_total
    )
    visual_evidence_count = int(coverage.get("visual_evidence_count") or 0)
    visual_project_background_only_count = int(
        coverage.get("visual_project_background_only_count") or 0
    )
    visual_sh_local_auxiliary_count = int(
        coverage.get("visual_sh_local_auxiliary_count") or 0
    )
    visual_component_bridge_candidate_count = int(
        coverage.get("visual_component_bridge_candidate_count") or 0
    )
    visual_core_candidate_pending_review_count = int(
        coverage.get("visual_core_candidate_pending_review_count") or 0
    )
    visual_evidence_available_but_not_gate_counting = bool(
        visual_evidence_count > 0
    )
    visual_core_candidate_pending_human_review = bool(
        visual_core_candidate_pending_review_count > 0
    )
    corpus_related_total = int(
        coverage.get("imported_related_full_text_count")
        if coverage.get("imported_related_full_text_count") is not None
        else coverage.get("corpus_related_full_text_count")
        or 0
    )
    noncore_pool_counts = (
        dict(coverage.get("noncore_evidence_pool_counts") or {})
        if isinstance(coverage.get("noncore_evidence_pool_counts"), dict)
        else {}
    )
    has_auxiliary_pool = any(
        int(noncore_pool_counts.get(key) or 0) > 0
        for key in (
            "method_context",
            "platform_context",
            "component_mechanism",
            "related_foundation",
            "boundary_context",
            "adverse_context",
        )
    )
    gate_contract = (
        coverage.get("gate_contract")
        if isinstance(coverage.get("gate_contract"), dict)
        else {}
    )
    direct_core_allowed_by_maturity = bool(
        gate_checks.get("direct_core_validation_allowed")
    )
    supportive_core = int(coverage.get("supportive_core_count") or 0)
    opposing_core = int(coverage.get("opposing_core_count") or 0)
    boundary_core = int(coverage.get("boundary_core_count") or 0)
    mixed_core = int(coverage.get("mixed_core_count") or 0)
    gate_contract_current = bool(gate_checks.get("gate_contract_current"))
    component_bridge_gap_synthesis_ready = bool(
        gate_contract_current
        and
        not direct_core_allowed_by_maturity
        and total_pass
        and (corpus_related_total > 0 or noncore_total > 0)
    )
    conflict_available = bool(
        (supportive_core > 0 and (opposing_core > 0 or boundary_core > 0 or mixed_core > 0))
        or polarity_verdict in {
            "mixed_or_condition_dependent",
            "primarily_opposing_or_reversal",
            "conditional_or_boundary_limited",
            "boundary_only",
        }
    )
    profile = (
        coverage.get("epistemic_profile")
        if isinstance(coverage.get("epistemic_profile"), dict)
        else (
            (coverage.get("gate_contract") or {}).get("epistemic_profile")
            if isinstance(coverage.get("gate_contract"), dict)
            else {}
        )
    )
    primary_mode = str((profile or {}).get("primary_mode") or "unresolved")
    classifications = [
        item for item in (coverage.get("fulltext_epistemic_classifications") or [])
        if isinstance(item, dict) and item.get("compatible_direct_core")
    ]
    formal_counterexample = any(
        str(item.get("standard_research_design") or "") == "counterexample"
        for item in classifications
    )
    formal_proof = any(
        str(item.get("standard_research_design") or "") in {
            "proof", "theorem", "lemma", "formally_verified_proof",
        }
        for item in classifications
    )
    empirical_core_count = int(coverage.get("empirical_support_core_count") or 0)
    theoretical_core_count = int(coverage.get("theoretical_validity_core_count") or 0)
    # Scientific assessment is a report of the evidence direction, never a
    # synonym for workflow completion.  In particular, a sufficient corpus can
    # still be inconclusive and a mathematical proof does not become truer by
    # adding fourteen context papers.
    claim_core_evidence_count = core_evidence_count if direct_core_allowed_by_maturity else 0
    if primary_mode == "mathematical_proof":
        scientific_assessment = (
            "REFUTED" if formal_counterexample else
            "FORMALLY_PROVED" if formal_proof else
            "OPEN_PROBLEM" if claim_core_evidence_count == 0 else
            "INCONCLUSIVE"
        )
    elif not direct_core_allowed_by_maturity and (corpus_related_total > 0 or noncore_total > 0 or auxiliary_material_total > 0):
        scientific_assessment = "COMPONENT_BRIDGE_CONTEXT_ONLY"
    elif type_directed_bundle_core_ready:
        scientific_assessment = "SUPPORTED_BY_CROSS_PAPER_CONTRACT_EVIDENCE"
    elif partial_contract_evidence_ready:
        scientific_assessment = "PARTIAL_CONTRACT_EVIDENCE"
    elif opposing_core > 0 and supportive_core == 0 and mixed_core == 0:
        scientific_assessment = "REFUTED"
    elif conflict_available:
        scientific_assessment = "CONTESTED"
    elif primary_mode == "theoretical_derivation" and theoretical_core_count > 0 and empirical_core_count == 0:
        scientific_assessment = "NOT_EMPIRICALLY_TESTABLE"
    elif claim_core_evidence_count > 0 and supportive_core > 0:
        scientific_assessment = "SUPPORTED"
    elif claim_core_evidence_count > 0:
        scientific_assessment = "PARTIALLY_SUPPORTED"
    else:
        scientific_assessment = "INCONCLUSIVE"
    contract_repair_recommended = bool(coverage.get("contract_repair_recommended"))
    if not gate_contract_current:
        evidence_review_state = "SH_CONTRACT_REBUILD_REQUIRED"
        gap_mode = "contract_rebuild_required"
        next_action = "rebuild_current_full_text_gate_contract_before_retrieval"
    elif not total_pass and partial_contract_evidence_ready:
        evidence_review_state = "SH_PARTIAL_CONTRACT_EVIDENCE"
        gap_mode = "partial_contract_evidence_corpus"
        next_action = "continue_broad_corpus_retrieval_and_target_missing_slots"
    elif not total_pass and direct_core_allowed_by_maturity and core_evidence_count > 0:
        evidence_review_state = "SH_CORE_EVIDENCE_PARTIAL"
        gap_mode = "partial_core_gap"
        next_action = "continue_broad_corpus_retrieval"
    elif type_directed_bundle_core_ready and conflict_available:
        evidence_review_state = "SH_CONFLICTED_CONTRACT_EVIDENCE_BUNDLE"
        gap_mode = "cross_paper_conflict_boundary_gap"
        next_action = "conditionalize_contract_claim_and_map_conflicting_slots"
    elif type_directed_bundle_core_ready:
        evidence_review_state = "SH_CONTRACT_EVIDENCE_BUNDLE_AVAILABLE"
        gap_mode = "cross_paper_contract_evidence_bundle"
        next_action = "proceed_to_gap_detection_with_slot_provenance"
    elif partial_contract_evidence_ready:
        evidence_review_state = "SH_PARTIAL_CONTRACT_EVIDENCE_AVAILABLE"
        gap_mode = "partial_contract_evidence_gap"
        next_action = "proceed_to_gap_detection_with_missing_slot_plan"
    elif claim_core_ready and conflict_available:
        evidence_review_state = "SH_CONFLICT_EVIDENCE_AVAILABLE"
        gap_mode = "conflict_boundary_gap"
        next_action = "conditionalize_claim_and_map_boundary"
    elif claim_core_ready:
        evidence_review_state = "SH_CORE_EVIDENCE_SUFFICIENT"
        gap_mode = "core_evidence_gap_detection"
        next_action = "proceed_to_gap_detection"
    elif component_bridge_gap_synthesis_ready:
        evidence_review_state = "SH_COMPONENT_BRIDGE_EVIDENCE_AVAILABLE"
        gap_mode = "component_bridge_gap_synthesis"
        next_action = "synthesize_component_bridge_gap_without_direct_core_claim"
    elif workflow_passes and direct_core_allowed_by_maturity and core_evidence_count > 0:
        evidence_review_state = "SH_CORE_EVIDENCE_PARTIAL"
        gap_mode = "partial_core_gap"
        next_action = "proceed_to_gap_detection_with_claim_strength_cap"
    elif workflow_passes:
        evidence_review_state = (
            "SH_AUXILIARY_EVIDENCE_AVAILABLE"
            if auxiliary_material_total > 0 or has_auxiliary_pool
            else "SH_RELATED_CORPUS_AVAILABLE"
        )
        gap_mode = "related_corpus_gap_without_direct_core"
        next_action = "proceed_to_gap_detection_without_direct_core_claim"
    elif direct_core_allowed_by_maturity and core_evidence_count > 0:
        evidence_review_state = "SH_CORE_EVIDENCE_PARTIAL"
        gap_mode = "partial_core_gap"
        next_action = "continue_broad_corpus_retrieval"
    elif corpus_related_total > 0 or auxiliary_material_total > 0 or has_auxiliary_pool:
        evidence_review_state = "SH_RELATED_CORPUS_PARTIAL"
        gap_mode = "related_corpus_shortfall"
        next_action = "continue_broad_corpus_and_narrow_core_retrieval"
    else:
        evidence_review_state = "SH_RETRIEVAL_EMPTY"
        gap_mode = "retrieval_shortfall"
        next_action = "continue_related_corpus_retrieval"
    return {
        "schema_version": "subhypothesis_retrieval_readiness_v7",
        "passes": workflow_passes,
        "status": (
            "CONTRACT_REBUILD_REQUIRED"
            if not gate_contract_current
            else "PARTIAL_CONTRACT_EVIDENCE_PORTFOLIO_INCOMPLETE"
            if partial_contract_evidence_ready and not total_pass
            else "FULLTEXT_TARGET_MET"
            if total_pass
            else "FULLTEXT_SHORTFALL_RETRYABLE"
        ),
        "corpus_ready": total_pass,
        "evidence_ready": core_pass,
        "workflow_ready": workflow_passes,
        "release_gate_pass": release_gate_pass,
        "release_gate_reason": (
            "noncurrent_full_text_gate_contract"
            if not gate_contract_current
            else "cross_paper_partial_contract_evidence"
            if partial_contract_evidence_ready and not total_pass
            else "imported_related_full_text_target_met"
            if total_pass
            else "release_gate_shortfall"
        ),
        "direct_supportive_core_available": direct_supportive_core_available,
        "scientific_assessment": scientific_assessment,
        "evidence_review_state": evidence_review_state,
        "core_ready": claim_core_ready,
        "direct_core_ready": bool(
            gate_checks.get("compatible_direct_core_pass")
        ),
        "claim_core_ready": claim_core_ready,
        "type_directed_evidence_bundle_status": type_directed_bundle_status,
        "type_directed_bundle_core_ready": type_directed_bundle_core_ready,
        "partial_contract_evidence_ready": partial_contract_evidence_ready,
        "type_directed_bundle_slot_support_count": type_directed_bundle_slot_count,
        "gap_mode": gap_mode,
        "next_action": next_action,
        "ready_for_gap_detection": workflow_passes,
        "ready_for_claim_gap_detection": workflow_passes,
        "ready_for_component_bridge_gap_synthesis": component_bridge_gap_synthesis_ready,
        "component_bridge_gap_synthesis_ready": component_bridge_gap_synthesis_ready,
        "direct_core_validation_allowed": direct_core_allowed_by_maturity,
        "core_metric": "cross_paper_type_directed_evidence_bundle",
        "claim_evidence_metric": "source_bound_cross_paper_contract_slots",
        "claim_strength_cap": str(coverage.get("claim_strength_cap") or ""),
        "gate_policy": (
            "imported_related_full_text_target_is_portfolio_saturation_goal;"
            "source_bound_partial_contract_evidence_can_enable_workflow;"
            "compatible_direct_core_controls_claim_strength_not_workflow;"
            "layer_mix_and_role_diversity_non_blocking"
        ),
        "type_directed_evidence_bundle_policy": (
            "source_bound_cross_paper contract slots can establish a core evidence bundle "
            "or partial contract evidence without a single universal mechanism paper; partial evidence may proceed before portfolio saturation"
        ),
        "release_gate_policy": (
            "release_requires_current_contract_and_either_portfolio_saturation_or_partial_contract_evidence;"
            "portfolio_shortfall_remains_quality_diagnostic;"
            "component_bridge_gap_synthesis_requires_full_related_corpus_target"
        ),
        "strict_passes": strict_passes,
        "quality_diagnostics_met": bool(
            gate_checks.get("quality_diagnostics_met")
        ),
        "readiness_basis": list(gate_checks["readiness_basis"]),
        "checks": {
            "current_full_text_gate_contract": gate_contract_current,
            "imported_related_full_text": total_pass,
            "release_gate": release_gate_pass,
            "direct_supportive_core": direct_supportive_core_available,
            "compatible_direct_core": bool(
                gate_checks.get("compatible_direct_core_pass")
            ),
            "type_directed_evidence_bundle": bool(
                gate_checks.get("type_directed_evidence_bundle_pass")
            ),
            "direct_contract_core": core_pass,
            "peer_reviewed_full_text_total": total_pass,
            "direct_core_full_text": bool(
                gate_checks.get("compatible_direct_core_pass")
            ),
            "standard_core_full_text": None,
            "readiness_core": core_pass,
            "evidence_portfolio_diversity": bool(
                gate_checks.get("portfolio_pass")
            ),
            "imported_full_text_total": total_pass,
            "layer_minimums": layers_pass,
            "preprints_excluded_from_target": coverage.get("preprints_count_toward_peer_reviewed_target") is False,
        },
        "remaining": {
            "imported_related_full_text": int(gate_checks["total_shortfall"]),
            "compatible_direct_core": int(
                gate_checks.get("compatible_direct_core_shortfall") or 0
            ),
            "type_directed_evidence_bundle": int(
                gate_checks.get("type_directed_bundle_shortfall") or 0
            ),
            "standard_anchors": dict(gate_checks.get("standard_anchor_shortfalls") or {}),
            "direct_contract_core": int(gate_checks.get("direct_contract_core_shortfall") or 0),
            "peer_reviewed_full_text": int(
                coverage.get("peer_reviewed_full_text_shortfall") or 0
            ),
            "imported_full_text": int(
                coverage.get("imported_full_text_shortfall") or 0
            ),
            "gate_counting_peer_reviewed_full_text": int(
                coverage.get("gate_counting_peer_reviewed_full_text_shortfall")
                or 0
            ),
            "direct_core_full_text": int(
                gate_checks.get("compatible_direct_core_shortfall") or 0
            ),
            "standard_core_full_text": int(coverage.get("standard_core_full_text_shortfall") or 0),
            "layers": layer_shortfalls,
            "evidence_portfolio": dict(
                gate_checks.get("portfolio_shortfalls") or {}
            ),
        },
        "quality_signals": {
            "preferred_layer_mix_met": all(
                int(value or 0) == 0 for value in preferred_shortfalls.values()
            ),
            "preferred_layer_shortfalls": preferred_shortfalls,
            "raw_peer_reviewed_full_text_count": int(
                coverage.get("raw_peer_reviewed_full_text_count")
                or coverage.get("peer_reviewed_full_text_count")
                or 0
            ),
            "gate_counting_peer_reviewed_full_text_count": gate_counting_total,
            "review_full_text_count": review_total,
            "review_full_text_context_only_count": review_context_only,
            "total_only_soft_pass": total_only_pass,
            "context_heavy": context_heavy,
            "evidence_strength_cap": evidence_strength_cap,
            "type_directed_evidence_bundle": type_directed_bundle,
            "claim_strength_modifier": claim_strength_modifier,
            "noncore_evidence_total": noncore_total,
            "metadata_only_auxiliary_total": metadata_only_auxiliary_total,
            "auxiliary_material_total": auxiliary_material_total,
            "corpus_related_full_text_count": corpus_related_total,
            "noncore_evidence_pool_counts": noncore_pool_counts,
            "metadata_only_auxiliary_counts": dict(
                coverage.get("metadata_only_auxiliary_counts") or {}
            ),
            "auxiliary_material_counts": dict(
                coverage.get("auxiliary_material_counts") or {}
            ),
            "contract_repair_recommended": contract_repair_recommended,
            "evidence_portfolio_counts": dict(
                coverage.get("evidence_portfolio_counts") or {}
            ),
            "evidence_portfolio_shortfalls": dict(
                gate_checks.get("portfolio_shortfalls") or {}
            ),
            "evidence_portfolio_ready": bool(
                gate_checks.get("portfolio_pass")
            ),
            "quality_diagnostics_met": bool(
                gate_checks.get("quality_diagnostics_met")
            ),
            "supportive_core_count": int(coverage.get("supportive_core_count") or 0),
            "direct_supportive_core_available": direct_supportive_core_available,
            "opposing_core_count": int(coverage.get("opposing_core_count") or 0),
            "boundary_core_count": int(coverage.get("boundary_core_count") or 0),
            "mixed_core_count": int(coverage.get("mixed_core_count") or 0),
            "primary_epistemic_mode": primary_mode,
            "component_bridge_gap_synthesis_ready": component_bridge_gap_synthesis_ready,
            "direct_core_validation_allowed": direct_core_allowed_by_maturity,
            "theoretical_validity_core_count": theoretical_core_count,
            "empirical_support_core_count": empirical_core_count,
            "theoretical_validity_by_status": dict(coverage.get("theoretical_validity_by_status") or {}),
            "empirical_support_by_status": dict(coverage.get("empirical_support_by_status") or {}),
            "visual_evidence_count": visual_evidence_count,
            "visual_project_background_only_count": visual_project_background_only_count,
            "visual_sh_local_auxiliary_count": visual_sh_local_auxiliary_count,
            "visual_component_bridge_candidate_count": visual_component_bridge_candidate_count,
            "visual_core_candidate_pending_review_count": visual_core_candidate_pending_review_count,
            "visual_evidence_counts_toward_gate": False,
            "visual_evidence_gate_policy": "candidate_only_until_human_review",
            "visual_evidence_available_but_not_gate_counting": visual_evidence_available_but_not_gate_counting,
            "visual_core_candidate_pending_human_review": visual_core_candidate_pending_human_review,
            "blocking": False,
        },
    }


def _epistemic_retrieval_repair_diagnostic(
    report: dict[str, Any],
    coverage: dict[str, Any],
) -> dict[str, Any]:
    """Recognize repeated paradigm-invalid rejections as a contract fault."""

    profile = coverage.get("epistemic_profile") if isinstance(coverage.get("epistemic_profile"), dict) else (
        (coverage.get("gate_contract") or {}).get("epistemic_profile")
        if isinstance(coverage.get("gate_contract"), dict)
        else {}
    )
    mode = str((profile or {}).get("primary_mode") or "unresolved")
    noninterventional = mode in {
        "observational_inference", "theoretical_derivation", "mathematical_proof",
        "computational_simulation", "classification_description", "synthesis_evaluation",
    }
    counters: Counter[str] = Counter()
    for container in (
        report.get("candidate_funnel"), report.get("rejection_reason_counts"),
        report.get("detail_rejection_counts"), coverage.get("rejected_record_counts"),
    ):
        if isinstance(container, dict):
            for key, value in container.items():
                try:
                    counters[str(key).lower()] += int(value or 0)
                except (TypeError, ValueError):
                    continue
    intervention_rejections = sum(
        count for reason, count in counters.items()
        if any(marker in reason for marker in (
            "missing intervention", "missing_intervention", "controlled experiment",
            "controlled_experiment", "missing perturbation", "missing_perturbation",
        ))
    )
    total_rejections = sum(counters.values())
    mismatch = bool(
        noninterventional
        and intervention_rejections >= 3
        and intervention_rejections / max(1, total_rejections) >= 0.4
    )
    return {
        "primary_mode": mode,
        "intervention_shaped_rejections": intervention_rejections,
        "total_observed_rejections": total_rejections,
        "status": "EPISTEMIC_CONTRACT_MISMATCH" if mismatch else "NO_PATTERN",
        "recovery_sequence": [
            "check_research_paradigm", "check_claim_type", "check_evidence_standard",
            "check_query_constraint_count", "split_into_evidence_path_queries",
            "relax_abstract_metadata_classification", "acquire_fulltext_and_reclassify",
        ],
    }


def _contract_lexical_alignment_repair_diagnostic(
    *,
    provider_deduplicated: int,
    project_object_aligned: int,
    coarse_rejections: dict[str, int],
) -> dict[str, Any]:
    """Detect a query/contract vocabulary mismatch before full-text work.

    This diagnosis intentionally uses only alignment-funnel reason codes.  It
    does not infer a replacement scientific term from a provider result: such
    an inference would turn a retrieval failure into an unproven scientific
    assertion.  The recovery path is therefore constrained to terms that are
    already declared by the active SH contract.
    """

    normalized_counts = {
        str(reason or "").upper(): max(0, int(count or 0))
        for reason, count in (coarse_rejections or {}).items()
    }
    coarse_evaluated = sum(normalized_counts.values())
    object_mismatch = sum(
        count
        for reason, count in normalized_counts.items()
        if "OBJECT_MISMATCH" in reason
    )
    declared_input_missing = sum(
        count
        for reason, count in normalized_counts.items()
        if "DECLARED_INPUT_MISSING" in reason
        or "INPUT_MISSING" in reason
    )
    declared_axis_missing = sum(
        count
        for reason, count in normalized_counts.items()
        if "DECLARED_" in reason
        and "MISSING" in reason
        and any(axis in reason for axis in ("INPUT", "MEDIATOR", "OUTCOME", "COMPARISON"))
    )
    # Use the evaluated coarse pool, not the provider-wide deduplicated count,
    # as the denominator.  A provider may return hundreds of records while the
    # coarse gate deliberately inspects a bounded batch; comparing those two
    # quantities hid mixed object/input failures in practice.
    meaningful_coarse_pool = coarse_evaluated >= 20
    object_pressure = object_mismatch >= max(8, int(coarse_evaluated * 0.25))
    input_pressure = declared_input_missing >= max(8, int(coarse_evaluated * 0.25))
    axis_pressure = declared_axis_missing >= max(10, int(coarse_evaluated * 0.40))
    triggered = bool(
        provider_deduplicated >= 25
        and project_object_aligned <= 0
        and meaningful_coarse_pool
        and (object_pressure or input_pressure or axis_pressure)
    )
    return {
        "status": (
            "CONTRACT_LEXICAL_ALIGNMENT_FAILURE"
            if triggered
            else "NO_PATTERN"
        ),
        "provider_deduplicated": max(0, int(provider_deduplicated or 0)),
        "project_object_aligned": max(0, int(project_object_aligned or 0)),
        "coarse_evaluated_candidates": coarse_evaluated,
        "coarse_object_mismatch_rejections": object_mismatch,
        "coarse_declared_input_missing_rejections": declared_input_missing,
        "coarse_declared_axis_missing_rejections": declared_axis_missing,
        "trigger_conditions": {
            "meaningful_coarse_pool": meaningful_coarse_pool,
            "object_pressure": object_pressure,
            "input_pressure": input_pressure,
            "axis_pressure": axis_pressure,
        },
        "recovery_sequence": [
            "freeze_fulltext_promotion_for_explicitly_unaligned_reserve_candidates",
            "reuse_only_active_contract_object_and_axis_terms",
            "run_small_object_plus_declared_axis_calibration_queries",
            "rerun_coarse_alignment_before_any_fulltext_expansion",
            "request_contract_repair_only_if_the_active_contract_has_no_usable_object_or_input_anchor",
        ],
        "scientific_claim_authority": "RETRIEVAL_CALIBRATION_ONLY_NOT_SCIENTIFIC_CONTRACT_MUTATION",
    }


def diagnose_retrieval_failure(
    *,
    report: dict[str, Any],
    coverage: dict[str, Any],
    qualified_fulltext_new: int,
    reserve_count: int = 0,
) -> dict[str, Any]:
    funnel = report.get("candidate_funnel") if isinstance(report.get("candidate_funnel"), dict) else {}
    pool = (
        report.get("candidate_pool_diagnostics")
        if isinstance(report.get("candidate_pool_diagnostics"), dict)
        else {}
    )
    # ``report.total_results`` is the stratified top-k returned to the caller,
    # while the alignment funnel may also contain strictly aligned reserve
    # candidates audited before that truncation.  Do not compare a 19-paper
    # alignment numerator with a misleading 10-paper ``round_candidates``
    # denominator.
    stratified_returned = int(report.get("total_results") or 0)
    alignment_pool_candidates = int(
        funnel.get("retrieved") or stratified_returned
    )
    deduplicated = int(
        funnel.get("deduplicated") or alignment_pool_candidates
    )
    object_aligned = int(funnel.get("project_object_aligned") or 0)
    contract_aligned = int(funnel.get("type_directed_contract_aligned") or 0)
    provider_raw = int(
        pool.get("provider_raw")
        or funnel.get("provider_raw")
        or alignment_pool_candidates
    )
    provider_deduplicated = int(
        pool.get("provider_deduplicated")
        or funnel.get("provider_deduplicated")
        or deduplicated
    )
    alignment_evaluated_candidates = int(
        pool.get("deep_alignment_pool")
        or pool.get("strict_alignment_evaluated")
        or alignment_pool_candidates
    )
    layer_eligible = int(funnel.get("layer_eligible") or 0)
    papergraph_written = int(
        report.get("papergraph_records_written")
        or funnel.get("papergraph_records_written")
        or (
            int(funnel.get("imported_direct") or 0)
            + int(funnel.get("imported_auxiliary") or 0)
            + int(funnel.get("imported_foundation") or 0)
        )
    )
    metadata_only = int(
        report.get("metadata_only_imported_records")
        or funnel.get("metadata_only_reserved")
        or 0
    )
    post_fulltext_demoted = int(
        report.get("post_fulltext_demoted_review")
        or funnel.get("post_fulltext_demoted_review")
        or 0
    )
    round_fulltext_records = int(
        funnel.get("round_fulltext_records")
        or funnel.get("fulltext_acquired")
        or 0
    )
    fulltext_cached_or_resolved = int(
        funnel.get("fulltext_markdown_cached")
        or funnel.get("fulltext_cached_or_resolved")
        or funnel.get("fulltext_acquired")
        or 0
    )
    fulltext_pending_structuring = int(
        funnel.get("fulltext_pending_structuring") or 0
    )
    net_new_admitted_fulltext = int(qualified_fulltext_new or 0)
    full_text_resolution_audit = (
        report.get("full_text_resolution_audit")
        if isinstance(report.get("full_text_resolution_audit"), dict)
        else {}
    )
    full_text_failure_counts = {
        str(key): int(value or 0)
        for key, value in (full_text_resolution_audit.get("failure_class_counts") or {}).items()
    }
    structured_full_text_failures = sum(
        value
        for key, value in full_text_failure_counts.items()
        if key not in {"NONE", "NOT_ATTEMPTED"}
    )
    provider_errors = [
        item for item in (report.get("provider_errors") or []) if isinstance(item, dict)
    ]
    if not provider_errors and str(report.get("error") or "").strip():
        provider_errors = [{
            "status": str(report.get("status") or "retrieval_error"),
            "error": str(report.get("error") or "")[:500],
        }]
    cross_round_duplicates = int(
        pool.get("cross_round_duplicates_excluded")
        or funnel.get("cross_round_duplicates_excluded")
        or 0
    )
    readiness_checks = _subhypothesis_readiness_gate_checks(coverage)
    related_fulltext_shortfall = int(
        readiness_checks.get("total_shortfall") or 0
    )
    direct_contract_core_shortfall = int(
        readiness_checks.get("direct_contract_core_shortfall") or 0
    )
    direct_supportive_core_available = bool(
        readiness_checks.get("direct_supportive_core_available")
    )
    corpus_ready = bool(readiness_checks.get("total_pass"))
    gate_satisfied = bool(readiness_checks.get("release_gate_pass"))
    strict_gate_satisfied = bool(readiness_checks.get("strict_passes"))
    partial_contract_evidence_ready = bool(
        readiness_checks.get("partial_contract_evidence_ready")
    )

    uses_standard_core = int(
        coverage.get("standard_core_full_text_target") or 0
    ) > 0
    direct_shortfall = int(
        coverage.get("direct_core_full_text_shortfall") or 0
    )
    portfolio_shortfalls = {
        str(key): int(value or 0)
        for key, value in (
            coverage.get("evidence_portfolio_shortfalls") or {}
        ).items()
    }
    has_portfolio_shortfall = any(
        value > 0 for value in portfolio_shortfalls.values()
    )
    raw_layer_shortfalls = coverage.get("layer_shortfalls")
    layer_shortfalls = dict(raw_layer_shortfalls or {}) if isinstance(raw_layer_shortfalls, dict) else {}
    has_complete_gate_state = (
        "peer_reviewed_full_text_shortfall" in coverage
        and (
            "standard_core_full_text_shortfall" in coverage
            if uses_standard_core
            else "direct_core_full_text_shortfall" in coverage
        )
        and isinstance(raw_layer_shortfalls, dict)
    )
    has_layer_shortfall = any(
        int(value or 0) > 0 for value in layer_shortfalls.values()
    )
    failure_classes: list[str] = []
    quality_diagnostic_classes: list[str] = []
    # Corpus completeness is independent of whether one direct-core paper has
    # already been found.  Keeping this failure visible is essential for the
    # next-round planner: a direct wavelength--efficiency experiment, for
    # example, must not suppress recovery of complementary measurement,
    # material, method, model, and boundary evidence.  This is deliberately
    # domain-neutral rather than a special rule for any one technology.
    if related_fulltext_shortfall > 0:
        if partial_contract_evidence_ready:
            quality_diagnostic_classes.append("RELATED_FULLTEXT_COUNT_SHORTFALL")
        else:
            failure_classes.append("RELATED_FULLTEXT_COUNT_SHORTFALL")
    claim_limiting_shortfall_classes: list[str] = []
    type_directed_bundle = (
        coverage.get("type_directed_evidence_bundle")
        if isinstance(coverage.get("type_directed_evidence_bundle"), dict)
        else {}
    )
    type_directed_bundle_configured = bool(
        type_directed_bundle
        and str(type_directed_bundle.get("status") or "") not in {"", "NOT_CONFIGURED"}
    )
    if direct_contract_core_shortfall > 0:
        claim_limiting_shortfall_classes.append(
            "TYPE_DIRECTED_EVIDENCE_BUNDLE_SHORTFALL"
            if type_directed_bundle_configured
            else "COMPATIBLE_DIRECT_CORE_SHORTFALL"
        )
    failure_class = failure_classes[0] if failure_classes else "NONE"

    epistemic_repair = _epistemic_retrieval_repair_diagnostic(report, coverage)

    # A large pool can legitimately have few contract-direct papers, but it should
    # not have *zero* source-bound object matches after a coarse object gate.
    # That pattern means the SH's object declaration/aliases or its query
    # realization is wrong or too generic.  Treat it as a contract-repair
    # signal, never as permission to count a merely word-overlapping paper.
    coarse_rejections = {
        str(key): int(value or 0)
        for key, value in (
            pool.get("coarse_prefilter_rejection_reason_counts") or {}
        ).items()
    }
    object_mismatch_rejections = sum(
        count
        for reason, count in coarse_rejections.items()
        if "OBJECT_MISMATCH" in reason.upper()
    )
    object_anchor_zero_recall = bool(
        provider_deduplicated >= 25
        and object_aligned <= 0
        and object_mismatch_rejections >= max(12, int(provider_deduplicated * 0.45))
    )
    object_contract_repair = {
        "status": (
            "OBJECT_CONTRACT_ZERO_RECALL"
            if object_anchor_zero_recall
            else "NO_PATTERN"
        ),
        "provider_deduplicated": provider_deduplicated,
        "project_object_aligned": object_aligned,
        "coarse_object_mismatch_rejections": object_mismatch_rejections,
        "recovery_sequence": [
            "verify_scientific_object_is_a_concrete_entity_or_system",
            "recover_only_source_bound_object_aliases",
            "rebuild_short_object_plus_single_axis_queries",
            "retain_domain_filter_as_a_ranking_hint_for_repair_retry",
            "rerun_coarse_object_prefilter_before_fulltext_resolution",
        ],
    }
    lexical_alignment_repair = _contract_lexical_alignment_repair_diagnostic(
        provider_deduplicated=provider_deduplicated,
        project_object_aligned=object_aligned,
        coarse_rejections=coarse_rejections,
    )

    alignment_denominator = max(1, alignment_evaluated_candidates)
    aligned_numerator = max(object_aligned, layer_eligible)
    diagnostic_signals = {
        "zero_results": alignment_pool_candidates <= 0,
        "no_new_unique_results": bool(
            deduplicated <= 0 or cross_round_duplicates > 0
        ),
        "low_alignment_conversion": bool(
            alignment_pool_candidates > 0
            and aligned_numerator / alignment_denominator < 0.35
        ),
        "no_type_directed_contract_candidates": contract_aligned <= 0,
        "provider_error_without_results": bool(
            provider_errors and provider_raw <= 0
        ),
        "fulltext_resolution_failures": structured_full_text_failures,
        "post_fulltext_genre_demotions": post_fulltext_demoted,
        "layer_mix_diagnostic_not_met": has_layer_shortfall,
        "standard_core_diagnostic_not_met": bool(
            int(coverage.get("standard_core_full_text_shortfall") or 0) > 0
        ),
        "evidence_lane_diagnostic_not_met": not bool(
            dict(coverage.get("direct_core_by_evidence_lane") or {})
        ),
        "evidence_portfolio_diagnostic_not_met": has_portfolio_shortfall,
        "epistemic_contract_mismatch": (
            epistemic_repair.get("status") == "EPISTEMIC_CONTRACT_MISMATCH"
        ),
        "object_contract_zero_recall": object_anchor_zero_recall,
        "contract_lexical_alignment_failure": (
            lexical_alignment_repair.get("status")
            == "CONTRACT_LEXICAL_ALIGNMENT_FAILURE"
        ),
    }
    return {
        "schema_version": "subhypothesis_retrieval_failure_v7",
        "failure_class": failure_class,
        "failure_classes": failure_classes,
        "claim_limiting_shortfall_classes": claim_limiting_shortfall_classes,
        "gate_satisfied": gate_satisfied,
        "strict_gate_satisfied": strict_gate_satisfied,
        "corpus_ready": corpus_ready,
        "release_gate_pass": gate_satisfied,
        "release_gate_reason": (
            "imported_related_full_text_target_met"
            if corpus_ready
            else "release_gate_shortfall"
        ),
        "direct_supportive_core_available": direct_supportive_core_available,
        "gate_policy": (
            "release_requires_imported_related_full_text_target;"
            "direct_supportive_core_controls_claim_assessment_not_corpus_completion"
        ),
        "type_directed_evidence_bundle_policy": (
            "source_bound_cross_paper_contract_slots_or_direct_support_controls_claim_assessment_not_corpus_completion"
        ),
        "readiness_basis": list(readiness_checks.get("readiness_basis") or []),
        "non_blocking_shortfall_classes": claim_limiting_shortfall_classes,
        "diagnostic_signals": diagnostic_signals,
        "type_directed_evidence_bundle": {
            "status": str(type_directed_bundle.get("status") or "NOT_CONFIGURED"),
            "research_question_ready": bool(type_directed_bundle.get("research_question_ready")),
            "source_bound_slot_support_count": int(
                type_directed_bundle.get("source_bound_slot_support_count") or 0
            ),
            "missing_required_slot_ids": list(
                type_directed_bundle.get("missing_required_slot_ids") or []
            )[:8],
            "gap_types": list(type_directed_bundle.get("gap_types") or []),
        },
        "epistemic_contract_repair": epistemic_repair,
        "object_contract_repair": object_contract_repair,
        "lexical_alignment_repair": lexical_alignment_repair,
        "has_failure": not gate_satisfied,
        "quality_diagnostic_classes": quality_diagnostic_classes,
        "provider_results": dict(report.get("provider_results") or {}),
        "provider_errors": provider_errors,
        "full_text_resolution_audit": full_text_resolution_audit,
        "conversion": {
            "provider_raw": provider_raw,
            "provider_deduplicated": provider_deduplicated,
            "round_candidates": alignment_pool_candidates,
            "stratified_returned": stratified_returned,
            "alignment_pool_candidates": alignment_pool_candidates,
            "alignment_evaluated_candidates": alignment_evaluated_candidates,
            "object_aligned": object_aligned,
            "type_directed_contract_aligned": contract_aligned,
            "layer_eligible": layer_eligible,
            "papergraph_written": papergraph_written,
            # Backward-compatible name: this is the net increase in cumulative
            # unique, admitted full texts, not the number of import attempts
            # that happened to resolve a full-text record this round.
            "fulltext_acquired": net_new_admitted_fulltext,
            "net_new_admitted_fulltext": net_new_admitted_fulltext,
            "round_fulltext_records": round_fulltext_records,
            "metadata_only_reserved": metadata_only,
            "direct_core": int(coverage.get("direct_core_full_text_count") or 0),
            "standard_core": int(coverage.get("standard_core_full_text_count") or 0),
            "post_fulltext_demoted_review": post_fulltext_demoted,
        },
        "fulltext_metrics": {
            "net_new_gate_counting_fulltext": net_new_admitted_fulltext,
            "net_new_admitted_fulltext": net_new_admitted_fulltext,
            "fulltext_cached_or_resolved": fulltext_cached_or_resolved,
            "fulltext_structured_records": round_fulltext_records,
            "fulltext_pending_structuring": fulltext_pending_structuring,
            "metadata_only_reserved": metadata_only,
        },
        "funnel": {
            "retrieved": alignment_pool_candidates,
            "stratified_returned": stratified_returned,
            "deduplicated_new": deduplicated,
            "object_aligned": object_aligned,
            "type_directed_contract_aligned": contract_aligned,
            "qualified_fulltext_new": net_new_admitted_fulltext,
        },
        "candidate_funnel": dict(funnel),
        "pre_import_precision_audit": dict(
            funnel.get("pre_import_precision_audit") or {}
        ),
        "rejection_reason_counts": dict(funnel.get("rejected_reason_counts") or {}),
        "coarse_prefilter_rejection_reason_counts": dict(
            pool.get("coarse_prefilter_rejection_reason_counts") or {}
        ),
        "strict_alignment_rejection_reason_counts": dict(
            pool.get("strict_admission_rejection_reason_counts") or {}
        ),
        "rejected_samples": list(funnel.get("rejected_samples") or [])[:8],
        "coverage_deficit": {
            "imported_related_fulltext_shortfall": related_fulltext_shortfall,
            "direct_contract_core_shortfall": direct_contract_core_shortfall,
            "type_directed_bundle_shortfall": int(
                readiness_checks.get("type_directed_bundle_shortfall")
                if readiness_checks.get("type_directed_bundle_shortfall") is not None
                else direct_contract_core_shortfall
            ),
            "peer_reviewed_fulltext_shortfall": int(coverage.get("peer_reviewed_full_text_shortfall") or 0),
            "direct_core_fulltext_shortfall": int(coverage.get("direct_core_full_text_shortfall") or 0),
            "standard_core_fulltext_shortfall": int(coverage.get("standard_core_full_text_shortfall") or 0),
            "core_metric": "type_directed_bundle_or_compatible_direct_core",
            "type_directed_evidence_bundle": {
                "status": str(type_directed_bundle.get("status") or "NOT_CONFIGURED"),
                "missing_required_slot_ids": list(
                    type_directed_bundle.get("missing_required_slot_ids") or []
                )[:8],
                "slot_source_lineage": dict(
                    type_directed_bundle.get("slot_source_lineage") or {}
                ),
            },
            "layers": dict(coverage.get("layer_shortfalls") or {}),
            "preferred_layers": dict(coverage.get("layer_preferred_shortfalls") or {}),
            "evidence_lanes": dict(coverage.get("direct_core_by_evidence_lane") or {}),
            "standard_core_by_design": dict(coverage.get("standard_core_by_design") or {}),
            "evidence_portfolio_shortfalls": portfolio_shortfalls,
            "claim_strength_cap": str(coverage.get("claim_strength_cap") or ""),
        },
        "reserve_count": int(reserve_count or 0),
        "cross_round_duplicates_excluded": cross_round_duplicates,
    }


def retrieval_terminal_status_for_diagnostics(diagnostics: dict[str, Any]) -> str:
    """Map one structured failure diagnosis to a non-overloaded terminal state."""

    if diagnostics.get("gate_satisfied") is True or str(diagnostics.get("failure_class") or "") == "NONE":
        return (
            "FULLTEXT_TARGET_MET"
            if diagnostics.get("corpus_ready") is True
            else "FULLTEXT_SHORTFALL_NO_FRESH_QUERY"
        )
    conversion = (
        diagnostics.get("conversion")
        if isinstance(diagnostics.get("conversion"), dict)
        else {}
    )
    fulltext_metrics = (
        diagnostics.get("fulltext_metrics")
        if isinstance(diagnostics.get("fulltext_metrics"), dict)
        else {}
    )
    provider_errors = [
        item
        for item in (diagnostics.get("provider_errors") or [])
        if isinstance(item, dict)
    ]
    provider_error_text = json.dumps(provider_errors, ensure_ascii=False).lower()
    provider_raw = int(conversion.get("provider_raw") or 0)
    provider_deduplicated = int(conversion.get("provider_deduplicated") or 0)
    deduplicated_new = int(
        (diagnostics.get("funnel") or {}).get("deduplicated_new")
        if isinstance(diagnostics.get("funnel"), dict)
        else provider_deduplicated
    )
    net_new_fulltext = int(
        fulltext_metrics.get("net_new_admitted_fulltext")
        if fulltext_metrics.get("net_new_admitted_fulltext") is not None
        else fulltext_metrics.get("net_new_gate_counting_fulltext")
        if fulltext_metrics.get("net_new_gate_counting_fulltext") is not None
        else conversion.get("net_new_admitted_fulltext")
        if conversion.get("net_new_admitted_fulltext") is not None
        else conversion.get("fulltext_acquired")
        or 0
    )
    fulltext_attempt_signal = int(
        fulltext_metrics.get("fulltext_cached_or_resolved")
        or fulltext_metrics.get("fulltext_structured_records")
        or conversion.get("round_fulltext_records")
        or 0
    )
    if provider_errors and (
        "429" in provider_error_text
        or "rate limit" in provider_error_text
        or "rate_limited" in provider_error_text
        or "too many requests" in provider_error_text
    ):
        return "PROVIDER_RATE_LIMITED"
    if provider_errors and provider_raw <= 0:
        return "RETRIEVAL_EXCEPTION_BEFORE_PROVIDER"
    if provider_raw <= 0:
        return "NO_PROVIDER_RESULTS"
    if provider_deduplicated <= 0 or deduplicated_new <= 0:
        return "NO_DEDUPED_CANDIDATES"
    if fulltext_attempt_signal > 0 and net_new_fulltext <= 0:
        return "NO_NET_NEW_FULLTEXT"
    return "EVIDENCE_SATURATED_SHORTFALL"


def retrieval_failure_action_plan(
    diagnostics: dict[str, Any],
    *,
    newly_admitted_evidence_records: int,
    low_admission_threshold: int,
) -> dict[str, Any]:
    """Map coexisting failures to retrieval recovery before model revision.

    Low yield by itself says nothing about the scientific contract.  Provider
    and full-text failures are resolver problems; repeated candidates are a
    query-novelty problem.  Only a large evaluated pool with persistently low
    semantic conversion may justify a *proposed* contract review, and that
    proposal is shadow-validated before it can affect future research.
    """

    source = diagnostics if isinstance(diagnostics, dict) else {}
    raw_failure_class = str(source.get("failure_class") or "").upper()
    raw_failure_classes = [
        str(item).upper()
        for item in (source.get("failure_classes") or [])
        if str(item).strip()
    ]
    if raw_failure_class and raw_failure_class not in raw_failure_classes:
        raw_failure_classes.insert(0, raw_failure_class)
    # Persisted projects may contain historical failure names. They are not
    # allowed to re-enter the active control plane after the v5 migration.
    failure_classes = [
        item
        for item in raw_failure_classes
        if item in QUERY_OPTIMIZER_FAILURE_CLASSES
    ]
    failure_class = failure_classes[0] if failure_classes else "NONE"
    failure_set = set(failure_classes)
    diagnostic_signals = (
        source.get("diagnostic_signals")
        if isinstance(source.get("diagnostic_signals"), dict)
        else {}
    )
    candidate_funnel = (
        source.get("candidate_funnel")
        if isinstance(source.get("candidate_funnel"), dict)
        else {}
    )
    precision_audit = (
        source.get("pre_import_precision_audit")
        if isinstance(source.get("pre_import_precision_audit"), dict)
        else candidate_funnel.get("pre_import_precision_audit")
        if isinstance(candidate_funnel.get("pre_import_precision_audit"), dict)
        else {}
    )
    precision_refinement = bool(precision_audit.get("refinement_recommended"))
    threshold = max(0, int(low_admission_threshold or 0))
    admitted = max(0, int(newly_admitted_evidence_records or 0))
    low_admission = bool(threshold > 0 and admitted <= threshold)
    count_recovery = "RELATED_FULLTEXT_COUNT_SHORTFALL" in failure_set
    core_recovery = bool(
        {
            "TYPE_DIRECTED_EVIDENCE_BUNDLE_SHORTFALL",
            "COMPATIBLE_DIRECT_CORE_SHORTFALL",
            "DIRECT_CONTRACT_CORE_SHORTFALL",
        }
        & failure_set
    )
    low_alignment = bool(
        diagnostic_signals.get("low_alignment_conversion")
        or diagnostic_signals.get("no_type_directed_contract_candidates")
    )
    provider_recovery = bool(
        count_recovery
        and diagnostic_signals.get("provider_error_without_results")
    )
    fulltext_recovery = bool(
        count_recovery
        and int(diagnostic_signals.get("fulltext_resolution_failures") or 0) > 0
    )
    layer_recovery = bool(count_recovery or core_recovery)
    no_new_results = bool(
        diagnostic_signals.get("zero_results")
        or diagnostic_signals.get("no_new_unique_results")
    )
    conversion = source.get("conversion") if isinstance(source.get("conversion"), dict) else {}
    evaluated = max(
        int(conversion.get("alignment_evaluated_candidates") or 0),
        int(conversion.get("provider_deduplicated") or 0),
        int(candidate_funnel.get("deep_alignment_pool") or 0),
    )
    aligned = max(
        int(conversion.get("object_aligned") or 0),
        int(conversion.get("type_directed_contract_aligned") or 0),
        int(conversion.get("layer_eligible") or 0),
    )
    high_recall_low_alignment = bool(
        low_alignment
        and evaluated >= 30
        and aligned <= max(2, int(evaluated * 0.08))
        and not provider_recovery
        and not fulltext_recovery
    )
    object_contract_zero_recall = bool(
        diagnostic_signals.get("object_contract_zero_recall")
    )
    contract_lexical_alignment_failure = bool(
        diagnostic_signals.get("contract_lexical_alignment_failure")
    )
    # A high-recall/low-alignment pattern normally permits a *shadow* contract
    # review.  When the coarse funnel already localizes the failure to missing
    # declared object/input vocabulary, repair that lexical realization first;
    # otherwise the system treats a query-shaping fault as evidence that the
    # scientific hypothesis itself should change.
    if contract_lexical_alignment_failure:
        high_recall_low_alignment = False

    actions: list[dict[str, Any]] = []

    def add_action(action: str, *, reasons: list[str], executed_by: str) -> None:
        actions.append({
            "action": action,
            "reasons": reasons,
            "executed_by": executed_by,
        })

    if provider_recovery:
        add_action(
            "retry_provider_search",
            reasons=["RELATED_FULLTEXT_COUNT_SHORTFALL"],
            executed_by="next_retrieval_round",
        )
    if fulltext_recovery:
        add_action(
            "retry_fulltext_resolution",
            reasons=sorted(
                {item for item in failure_set if item == "RELATED_FULLTEXT_COUNT_SHORTFALL"}
            ),
            executed_by="reserve_promotion_and_next_retrieval_round",
        )
    if object_contract_zero_recall:
        add_action(
            "rebuild_scientific_object_contract",
            reasons=["OBJECT_CONTRACT_ZERO_RECALL"],
            executed_by="shadow_contract_reassessment",
        )
    if contract_lexical_alignment_failure:
        add_action(
            "run_contract_lexical_calibration",
            reasons=["CONTRACT_LEXICAL_ALIGNMENT_FAILURE"],
            executed_by="contract_anchored_query_planner",
        )
    if low_alignment or low_admission or precision_refinement or no_new_results:
        reasons: list[str] = []
        if low_alignment:
            reasons.append("RELATED_CORPUS_QUERY_REFINEMENT")
        if low_admission:
            reasons.append("LOW_ADMISSION")
        if precision_refinement:
            reasons.append("PRE_IMPORT_PRECISION_AUDIT")
        if no_new_results:
            reasons.append("QUERY_NOVELTY_EXHAUSTED")
        add_action(
            "refine_retrieval_strategy",
            reasons=reasons,
            executed_by="retrieval_reassessment",
        )
    if high_recall_low_alignment:
        add_action(
            "propose_scientific_contract_revision",
            reasons=["HIGH_RECALL_LOW_ALIGNMENT"],
            executed_by="shadow_contract_reassessment",
        )
    if layer_recovery or low_alignment or no_new_results or precision_refinement:
        reasons = sorted(failure_set)
        add_action(
            "refine_role_query_branches",
            reasons=(
                reasons
                + (["PRE_IMPORT_PRECISION_AUDIT"] if precision_refinement else [])
            ) or ["LOW_ADMISSION"],
            executed_by="query_optimizer",
        )
    return {
        "schema_version": "subhypothesis_retrieval_failure_actions_v1",
        "failure_class": failure_class,
        "failure_classes": failure_classes,
        "signals": {
            "low_admission": low_admission,
            "low_alignment": low_alignment,
            "provider_recovery": provider_recovery,
            "fulltext_recovery": fulltext_recovery,
            "layer_recovery": layer_recovery,
            "related_fulltext_count_recovery": count_recovery,
            "direct_contract_core_recovery": core_recovery,
            "no_new_results": no_new_results,
            "precision_refinement": precision_refinement,
            "newly_admitted_evidence_records": admitted,
            "low_admission_threshold": threshold,
            "alignment_evaluated_candidates": evaluated,
            "aligned_candidates": aligned,
            "high_recall_low_alignment": high_recall_low_alignment,
            "object_contract_zero_recall": object_contract_zero_recall,
            "contract_lexical_alignment_failure": contract_lexical_alignment_failure,
        },
        "actions": actions,
        "reassessment_required": bool(
            count_recovery
            or core_recovery
            or low_alignment
            or low_admission
            or precision_refinement
            or no_new_results
            or object_contract_zero_recall
            or contract_lexical_alignment_failure
        ),
        "scientific_contract_reassessment_required": bool(
            high_recall_low_alignment or object_contract_zero_recall
        ),
        "query_refinement_required": bool(
            count_recovery
            or core_recovery
            or low_alignment
            or no_new_results
            or precision_refinement
            or contract_lexical_alignment_failure
        ),
    }


def query_fingerprint(query: Any) -> str:
    normalized = re.sub(r"\s+", " ", str(query or "").strip().lower())
    normalized = re.sub(r"\s*([()])\s*", r"\1", normalized)
    return sha256(normalized.encode("utf-8")).hexdigest()[:20] if normalized else ""


# These are orchestration labels, rather than required scientific concepts.
# They are stripped only for novelty comparison.  Alignment and admission
# still use the actual scientific contract, so a topic whose *real* object is
# named "validation" is not otherwise excluded from retrieval.
_SYSTEM_QUERY_ROLE_PHRASES = (
    "causal validation",
    "mechanism discovery",
    "predictive validation",
    "boundary or negative evidence",
    "adverse or reversal evidence",
    "adverse reversal evidence",
    "functional analysis",
    "target layer",
    "target lane",
)


def scientific_query_signature(query: Any) -> str:
    """Return a role-insensitive signature used to prevent fake novelty."""

    normalized = _positive_query_text(str(query or "")).lower()
    for phrase in _SYSTEM_QUERY_ROLE_PHRASES:
        normalized = re.sub(rf"\b{re.escape(phrase)}\b", " ", normalized)
    normalized = re.sub(r"\b(?:and|or|not)\b", " ", normalized)
    normalized = re.sub(r"[^a-z0-9_-]+", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return sha256(normalized.encode("utf-8")).hexdigest()[:20] if normalized else ""


_QUERY_BRANCH_REGISTRY_SCHEMA_VERSION = "subhypothesis_role_query_branches_v1"
_QUERY_BRANCH_HISTORY_LIMIT = 24
_QUERY_BRANCH_SERIALIZED_FIELDS = (
    "branch",
    "query",
    "l2_query",
    "purpose",
    "query_family",
    "evidence_kind",
    "evidence_path_role",
    "evidence_path_polarity",
    "target_lane",
    "target_layer",
    "query_optimizer_round",
    "query_fingerprint",
    "scientific_query_signature",
    "evidence_shape_role",
    "scientific_object_anchor",
    "primary_field",
    "excluded_nearby_objects",
    "path_composition_policy",
    "causal_edge_anchors",
    "experimental_context_terms",
    "lexical_calibration",
    "calibration_route",
    "calibration_contract_axes",
)


def _normalized_query_branch_entry(
    raw: dict[str, Any],
    *,
    role_hint: str = "",
) -> dict[str, Any]:
    """Retain only a portable, role-addressable query-plan entry."""

    query = re.sub(r"\s+", " ", str(raw.get("query") or "").strip())
    fingerprint = str(raw.get("query_fingerprint") or query_fingerprint(query))
    role = str(
        raw.get("evidence_path_role")
        or raw.get("role")
        or role_hint
        or "whole_causal_chain"
    ).strip().lower() or "whole_causal_chain"
    if not query or not fingerprint:
        return {}
    entry: dict[str, Any] = {
        "role": role,
        "query": query,
        "query_fingerprint": fingerprint,
    }
    for field in _QUERY_BRANCH_SERIALIZED_FIELDS:
        value = raw.get(field)
        if field in {"query", "query_fingerprint"} or value in (None, "", [], {}):
            continue
        entry[field] = value
    entry["evidence_path_role"] = role
    entry.setdefault("branch", f"{role}:{fingerprint[:8]}")
    entry.setdefault("l2_query", query)
    return entry


def normalize_subhypothesis_query_branch_registry(value: Any) -> dict[str, Any]:
    """Normalize persisted SH query branches by evidence-path role.

    The registry deliberately distinguishes attempted branches from a plan
    prepared at the final failed round.  This lets a restarted retrieval loop
    consume an unexecuted optimized plan while using only executed branches to
    reject query duplicates.
    """

    source = value if isinstance(value, dict) else {}
    raw_by_role = source.get("by_role") if isinstance(source.get("by_role"), dict) else {}
    normalized: dict[str, Any] = {
        "schema_version": _QUERY_BRANCH_REGISTRY_SCHEMA_VERSION,
        "by_role": {},
    }
    for role_hint, raw_role_state in raw_by_role.items():
        state = raw_role_state if isinstance(raw_role_state, dict) else {}
        role = str(role_hint or "whole_causal_chain").strip().lower() or "whole_causal_chain"
        normalized["by_role"][role] = {"attempted": [], "pending": []}
        for bucket in ("attempted", "pending"):
            seen: set[str] = set()
            for raw in state.get(bucket) or []:
                if not isinstance(raw, dict):
                    continue
                entry = _normalized_query_branch_entry(raw, role_hint=role)
                fingerprint = str(entry.get("query_fingerprint") or "")
                if not entry or fingerprint in seen:
                    continue
                seen.add(fingerprint)
                normalized["by_role"][role][bucket].append(entry)

    return normalized


def query_branch_registry_attempted_queries(registry: dict[str, Any]) -> list[str]:
    source = normalize_subhypothesis_query_branch_registry(registry)
    output: list[str] = []
    seen: set[str] = set()
    for role_state in source.get("by_role", {}).values():
        if not isinstance(role_state, dict):
            continue
        for item in role_state.get("attempted") or []:
            if not isinstance(item, dict):
                continue
            query = str(item.get("query") or "").strip()
            fingerprint = query_fingerprint(query)
            if query and fingerprint and fingerprint not in seen:
                seen.add(fingerprint)
                output.append(query)
    return output


def query_branch_registry_pending_plan(registry: dict[str, Any]) -> list[dict[str, Any]]:
    source = normalize_subhypothesis_query_branch_registry(registry)
    plan: list[dict[str, Any]] = []
    seen: set[str] = set()
    attempted_fingerprints = {
        str(item.get("query_fingerprint") or query_fingerprint(item.get("query")))
        for role_state in source.get("by_role", {}).values()
        if isinstance(role_state, dict)
        for item in role_state.get("attempted") or []
        if isinstance(item, dict)
        and str(item.get("query_fingerprint") or query_fingerprint(item.get("query")))
    }
    for role_state in source.get("by_role", {}).values():
        if not isinstance(role_state, dict):
            continue
        for item in role_state.get("pending") or []:
            if not isinstance(item, dict):
                continue
            fingerprint = str(item.get("query_fingerprint") or query_fingerprint(item.get("query")))
            if (
                not fingerprint
                or fingerprint in seen
                or fingerprint in attempted_fingerprints
            ):
                continue
            seen.add(fingerprint)
            plan.append(dict(item))
    return plan


def record_subhypothesis_query_branches(
    registry: dict[str, Any] | None,
    plan: list[dict[str, Any]] | None,
    *,
    bucket: str,
    round_index: int,
    source: str,
) -> dict[str, Any]:
    """Record a role-specific plan as attempted or pending for one SH."""

    if bucket not in {"attempted", "pending"}:
        raise ValueError("bucket must be attempted or pending")
    normalized = normalize_subhypothesis_query_branch_registry(registry or {})
    if bucket == "pending":
        for role_state in normalized["by_role"].values():
            if isinstance(role_state, dict):
                role_state["pending"] = []
    for raw in plan or []:
        if not isinstance(raw, dict):
            continue
        entry = _normalized_query_branch_entry(raw)
        if not entry:
            continue
        role = str(entry["role"])
        role_state = normalized["by_role"].setdefault(
            role, {"attempted": [], "pending": []}
        )
        fingerprint = str(entry["query_fingerprint"])
        current_entries = role_state[bucket]
        existing = next(
            (
                item
                for item in current_entries
                if isinstance(item, dict)
                and str(item.get("query_fingerprint") or "") == fingerprint
            ),
            None,
        )
        if isinstance(existing, dict):
            existing.update(entry)
        else:
            current_entries.append(entry)
            existing = entry
        existing["last_updated_round"] = int(round_index)
        existing["last_source"] = str(source or "")
        if bucket == "attempted":
            existing["last_attempted_round"] = int(round_index)
            existing["attempt_count"] = int(existing.get("attempt_count") or 0) + 1
            role_state["pending"] = [
                item
                for item in role_state["pending"]
                if str(item.get("query_fingerprint") or "") != fingerprint
            ]
        role_state[bucket] = role_state[bucket][-_QUERY_BRANCH_HISTORY_LIMIT:]
    normalized["updated_round"] = int(round_index)
    return normalized


def _positive_query_text(query: str) -> str:
    # Exclusion terms are allowed in an explicit NOT clause but must not be
    # introduced as positive scientific objects.
    without_groups = re.sub(r"\bNOT\s*\([^)]*\)", " ", query, flags=re.IGNORECASE)
    return re.sub(r"\bNOT\s+[^()]+?(?=\bAND\b|\bOR\b|$)", " ", without_groups, flags=re.IGNORECASE)


def _anchor_terms(contract: dict[str, Any]) -> list[str]:
    """Return retrieval anchors declared by the active contract.

    ResearchQuestionContractV2 owns its scientific object through
    ``scientific_scope``.  It must therefore be usable directly here rather
    than requiring the retired alignment-era ``scientific_object_*`` fields.
    The latter remain readable only for callers outside the V2/V3 route.
    """
    research_question = (
        contract.get("research_question")
        if isinstance(contract.get("research_question"), dict)
        else {}
    )
    scientific_scope = (
        contract.get("scientific_scope")
        if isinstance(contract.get("scientific_scope"), dict)
        else {}
    )
    v2_object_values = (
        [scientific_scope.get("research_object")]
        if research_question.get("question_kind")
        else []
    )
    policy = (
        contract.get("scientific_object_anchor_policy")
        if isinstance(contract.get("scientific_object_anchor_policy"), dict)
        else {}
    )
    values = (
        v2_object_values
        + list(contract.get("scientific_object_identity_phrases") or [])
        + ([contract.get("scientific_object_identity_anchor")] if contract.get("scientific_object_identity_anchor") else [])
        + list(policy.get("strong_anchor_phrases") or [])
        + list(policy.get("strong_anchor_terms") or [])
        + list(policy.get("object_group") or [])
    )
    output: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = re.sub(r"\s+", " ", str(value or "").strip().lower())
        if len(normalized) < 4 or normalized in seen:
            continue
        seen.add(normalized)
        output.append(normalized)
    return output


_OBJECT_MATURITY_COMPONENT_STATUSES = frozenset({
    "component_evidence_only",
    "translational_bridge",
    "speculative_unanchored",
})


def _object_maturity_status_key(value: Any) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower()).strip("_")
    if normalized in {"component", "component_only", "component_evidence"}:
        return "component_evidence_only"
    if normalized in {"bridge", "translation_bridge", "translational"}:
        return "translational_bridge"
    if normalized in {"speculative", "unanchored", "future_vision"}:
        return "speculative_unanchored"
    if normalized in {"contract_repair_required", "invalid_object_contract", "object_contract_invalid"}:
        return "contract_repair_required"
    return normalized


def _direct_core_allowed_by_object_maturity(
    alignment_contract: dict[str, Any],
) -> bool:
    contract = alignment_contract if isinstance(alignment_contract, dict) else {}
    audit = (
        contract.get("object_maturity_audit")
        if isinstance(contract.get("object_maturity_audit"), dict)
        else {}
    )
    status = _object_maturity_status_key(
        contract.get("object_maturity_status")
        or audit.get("object_status")
        or audit.get("status")
        or ""
    )
    retrieval_mode = str(
        contract.get("object_maturity_retrieval_mode")
        or audit.get("retrieval_mode")
        or ""
    ).strip().lower()
    if isinstance(audit.get("direct_local_edge_evidence_allowed"), bool):
        return bool(audit.get("direct_local_edge_evidence_allowed"))
    if (
        contract.get("direct_core_evidence_allowed") is False
        or audit.get("direct_core_evidence_allowed") is False
        or retrieval_mode == "component_bridge_boundary"
        or retrieval_mode == "contract_repair_required"
        or status == "contract_repair_required"
        or status in _OBJECT_MATURITY_COMPONENT_STATUSES
    ):
        return False
    return True


def _object_maturity_anchor_terms(
    alignment_contract: dict[str, Any],
) -> list[str]:
    contract = alignment_contract if isinstance(alignment_contract, dict) else {}
    try:
        from ._research_alignment import is_component_bridge_modifier_only_anchor
    except ImportError:
        from _research_alignment import is_component_bridge_modifier_only_anchor
    audit = (
        contract.get("object_maturity_audit")
        if isinstance(contract.get("object_maturity_audit"), dict)
        else {}
    )
    policy = (
        contract.get("scientific_object_anchor_policy")
        if isinstance(contract.get("scientific_object_anchor_policy"), dict)
        else {}
    )
    values: list[Any] = []
    def add_values(raw_values: Any) -> None:
        if isinstance(raw_values, (list, tuple, set)):
            values.extend(raw_values)
        elif raw_values not in (None, "", [], {}):
            values.append(raw_values)
    for source in (policy, audit, contract):
        if not isinstance(source, dict):
            continue
        for key in (
            "object_anchors",
            "method_or_platform_anchors",
            "readout_anchors",
            "model_system_anchors",
            "component_bridge_object_anchor_phrases",
            "component_bridge_method_or_platform_anchor_phrases",
            "component_bridge_readout_anchor_phrases",
            "component_bridge_model_system_anchor_phrases",
        ):
            add_values(source.get(key))
    scope_policy = (
        contract.get("subhypothesis_scope_policy")
        if isinstance(contract.get("subhypothesis_scope_policy"), dict)
        else policy.get("subhypothesis_scope_policy")
        if isinstance(policy.get("subhypothesis_scope_policy"), dict)
        else {}
    )
    query_forbidden_terms = [
        re.sub(r"\s+", " ", str(item or "").strip().lower())
        for item in (
            list(contract.get("query_forbidden_terms") or [])
            + list(policy.get("query_forbidden_terms") or [])
            + list(scope_policy.get("query_forbidden_terms") or [])
        )
        if re.sub(r"\s+", " ", str(item or "").strip())
    ]
    output: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = re.sub(r"\s+", " ", str(value or "").strip().lower())
        if len(normalized) < 4 or normalized in seen:
            continue
        if is_component_bridge_modifier_only_anchor(normalized):
            continue
        if any(
            forbidden
            and (
                normalized == forbidden
                or normalized in forbidden
                or forbidden in normalized
            )
            for forbidden in query_forbidden_terms
        ):
            continue
        seen.add(normalized)
        output.append(normalized)
    return output


def _optimizer_object_anchor_terms(
    alignment_contract: dict[str, Any],
) -> list[str]:
    if not _direct_core_allowed_by_object_maturity(alignment_contract):
        maturity_anchors = _object_maturity_anchor_terms(alignment_contract)
        if maturity_anchors:
            return maturity_anchors
    return _anchor_terms(alignment_contract)


def _query_match_text(value: Any) -> str:
    normalized = re.sub(r"[^a-z0-9+_-]+", " ", str(value or "").lower())
    compact = re.sub(r"\s+", " ", normalized).strip()
    return f" {compact} "


def _query_contains_any(text: Any, markers: tuple[str, ...] | list[str] | set[str]) -> bool:
    haystack = _query_match_text(text)
    for marker in markers:
        normalized = _query_match_text(marker).strip()
        if normalized and f" {normalized} " in haystack:
            return True
    return False


def _discipline_profile_match_text(alignment_contract: dict[str, Any]) -> str:
    """Collect non-authoritative field hints for discipline-shaped queries.

    These hints are deliberately weaker than the SH contract: they can choose
    better query vocabulary, but they cannot create object/axis evidence by
    themselves.
    """

    values: list[Any] = []
    for key in (
        "primary_field",
        "field",
        "fields",
        "domain",
        "discipline",
        "disciplines",
        "openalex_field",
        "openalex_fields",
        "openalex_field_id",
        "openalex_field_ids",
        "wos_category",
        "wos_categories",
        "source_filter_values",
        "source_filters",
        "focus",
        "focus_anchor",
        "scientific_object",
        "scientific_object_aliases",
        "retrieval_query",
    ):
        if key in alignment_contract:
            values.append(alignment_contract.get(key))
    causal_contract = alignment_contract.get("causal_contract")
    if isinstance(causal_contract, dict):
        values.extend(
            [
                causal_contract.get("constraint_type"),
                causal_contract.get("boundary_conditions"),
                causal_contract.get("outcome"),
            ]
        )
    evidence_paths = alignment_contract.get("evidence_paths")
    if isinstance(evidence_paths, list):
        for path in evidence_paths[:8]:
            if isinstance(path, dict):
                values.extend(
                    [
                        path.get("id"),
                        path.get("role"),
                        path.get("retrieval_query"),
                    ]
                )
    return json.dumps(values, ensure_ascii=False, default=str).lower()


def _discipline_profile_terms(
    alignment_contract: dict[str, Any],
    term_kind: str,
    *,
    limit: int = 6,
) -> list[str]:
    """Return field-appropriate query terms while ignoring social/HSS fields."""

    text = _discipline_profile_match_text(alignment_contract)
    if not text:
        return []
    # The exclusion list is recorded as an explicit guardrail: excluded fields
    # do not have profiles below, and a contract that only names them should
    # not receive generic science keywords just because it says "science".
    ignored_only = _query_contains_any(text, _IGNORED_DISCIPLINE_QUERY_PROFILE_MARKERS)
    selected: list[str] = []
    seen: set[str] = set()
    for profile in _DISCIPLINE_QUERY_KEYWORD_PROFILES:
        markers = profile.get("match") or ()
        if not _query_contains_any(text, markers):
            continue
        # If the text contains an ignored discipline and the only matching
        # marker is a broad overlap such as "clinical", let the explicit
        # natural/health/technical profile marker still win; otherwise skip.
        if ignored_only and not any(
            str(marker or "").strip().isdigit() and str(marker or "").strip() in text
            for marker in profile.get("id") or ()
        ):
            profile_label_hit = any(
                _query_match_text(marker).strip() in _query_match_text(text)
                for marker in markers
                if len(str(marker or "").strip()) >= 8
            )
            if not profile_label_hit:
                continue
        for term in profile.get(term_kind) or ():
            normalized = re.sub(r"\s+", " ", str(term or "").strip())
            if not normalized:
                continue
            key = normalized.lower()
            if key in seen:
                continue
            seen.add(key)
            selected.append(normalized)
            if len(selected) >= max(1, int(limit)):
                return selected
    return selected


def _discipline_adverse_profile_terms(
    alignment_contract: dict[str, Any],
    *,
    limit: int = 5,
) -> list[str]:
    """Return field-appropriate adverse/reversal terms for non-HSS sciences."""

    text = _discipline_profile_match_text(alignment_contract)
    if not text:
        return []
    ignored_only = _query_contains_any(text, _IGNORED_DISCIPLINE_QUERY_PROFILE_MARKERS)
    selected: list[str] = []
    seen: set[str] = set()
    for profile in _DISCIPLINE_ADVERSE_QUERY_PROFILES:
        markers = profile.get("match") or ()
        if not _query_contains_any(text, markers):
            continue
        if ignored_only and not any(
            str(marker or "").strip().isdigit() and str(marker or "").strip() in text
            for marker in profile.get("id") or ()
        ):
            profile_label_hit = any(
                _query_match_text(marker).strip() in _query_match_text(text)
                for marker in markers
                if len(str(marker or "").strip()) >= 8
            )
            if not profile_label_hit:
                continue
        for term in profile.get("adverse") or ():
            normalized = re.sub(r"\s+", " ", str(term or "").strip())
            if not normalized:
                continue
            key = normalized.lower()
            if key in seen:
                continue
            seen.add(key)
            selected.append(normalized)
            if len(selected) >= max(1, int(limit)):
                return selected
    return selected


def _query_validation_role(item: dict[str, Any], *, layer: str, lane: str) -> str:
    role_text = " ".join(
        str(value or "")
        for value in (
            item.get("evidence_path_role"),
            item.get("role"),
            item.get("query_family"),
            item.get("purpose"),
            item.get("rationale"),
        )
    ).lower()
    lane = str(lane or "").upper()
    if lane in {
        "THEORETICAL_OR_FORMAL_EVIDENCE",
        "COMPUTATIONAL_MODEL_DISCRIMINATION",
    }:
        return "theoretical_or_formal"
    if lane in {
        "OBSERVATIONAL_COHORT_EVIDENCE",
        "ECOLOGICAL_FIELD_OBSERVATION",
        "ECOLOGICAL_MONITORING",
        "ECOLOGICAL_LONGITUDINAL_MONITORING",
        "SURVEILLANCE_SYSTEM_VALIDATION",
    }:
        return "observational_or_system"
    if lane == ADVERSE_OR_REVERSAL_EVIDENCE_LANE or any(
        marker in role_text
        for marker in ("adverse", "reversal", "opposing", "tradeoff", "trade-off", "rebound", "burden")
    ):
        return "adverse_or_reversal"
    if lane == BOUNDARY_OR_NEGATIVE_EVIDENCE_LANE or "boundary" in role_text or "negative" in role_text:
        return "boundary"
    if (
        layer == "L0_review"
        or lane == "THEORETICAL_FRAMEWORK"
        or any(marker in role_text for marker in ("background", "framework", "context", "review"))
    ):
        return "context_review"
    if lane == "COMPONENT_EVIDENCE" or "component" in role_text:
        return "supporting_mechanism"
    if lane == "TRANSLATIONAL_BRIDGE_EVIDENCE" or any(
        marker in role_text for marker in ("bridge", "translation", "translational")
    ):
        return "boundary"
    if lane == "PREDICTIVE_VALIDATION" or any(
        marker in role_text
        for marker in ("predictive", "external_validation", "external validation", "generalization")
    ):
        return "predictive_generalization"
    if lane == "CAUSAL_VALIDATION" or "core_validation" in role_text or "causal_validation" in role_text:
        return "core_validation"
    if lane == "MECHANISM_DISCOVERY" or any(
        marker in role_text for marker in ("support", "component", "mechanism")
    ):
        return "supporting_mechanism"
    return "core_validation"


def _contract_endpoint_anchors(alignment_contract: dict[str, Any]) -> list[str]:
    core_axis_policy = (
        alignment_contract.get("core_axis_policy")
        if isinstance(alignment_contract.get("core_axis_policy"), dict)
        else {}
    )
    values: list[Any] = [
        core_axis_policy.get("outcome_phrases"),
        core_axis_policy.get("outcome_terms"),
    ]
    causal_contract = alignment_contract.get("causal_contract")
    if isinstance(causal_contract, dict):
        values.extend(
            [
                causal_contract.get("outcome"),
            ]
        )
    flattened: list[str] = []
    for value in values:
        items = value if isinstance(value, (list, tuple, set)) else [value]
        for item in items:
            normalized = re.sub(r"\s+", " ", str(item or "").strip().lower())
            if len(normalized) < 4:
                continue
            tokens = re.findall(r"[a-z0-9+_-]+", normalized)
            informative = [
                token
                for token in tokens
                if token not in _GENERIC_RETRIEVAL_TERMS
                and token not in _LOW_INFORMATION_QUERY_AXIS_TERMS
            ]
            if not informative and not _query_contains_any(normalized, _QUERY_ENDPOINT_ANCHORS):
                continue
            flattened.append(normalized)
    output: list[str] = []
    seen: set[str] = set()
    for item in flattened:
        if item in seen:
            continue
        seen.add(item)
        output.append(item)
    return output[:12]


def _contract_declared_axis_terms(
    alignment_contract: dict[str, Any],
    *,
    axis: str,
    limit: int = 8,
) -> list[str]:
    """Read reusable retrieval phrases from the declared SH contract only.

    The helper is deliberately lexical rather than ontological: it never
    expands an abbreviation, guesses a synonymous material/platform, or adds
    discipline-specific vocabulary.  Any such expansion needs independent
    source support and belongs upstream in contract construction.
    """

    contract = alignment_contract if isinstance(alignment_contract, dict) else {}
    core_axis_policy = (
        contract.get("core_axis_policy")
        if isinstance(contract.get("core_axis_policy"), dict)
        else {}
    )
    key_map = {
        "input": ("focal_variable_phrases", "focal_variable_terms"),
        "mechanism": ("mechanism_phrases", "mechanism_terms"),
        "outcome": ("outcome_phrases", "outcome_terms"),
    }
    values: list[Any] = []
    for key in key_map.get(axis, ()):
        values.append(core_axis_policy.get(key))
    output: list[str] = []
    seen: set[str] = set()
    for raw in values:
        items = raw if isinstance(raw, (list, tuple, set)) else [raw]
        for item in items:
            normalized = re.sub(r"\s+", " ", str(item or "").strip().lower())
            if len(normalized) < 3 or normalized in seen:
                continue
            if normalized in _GENERIC_RETRIEVAL_TERMS:
                continue
            seen.add(normalized)
            output.append(normalized)
            if len(output) >= max(1, int(limit)):
                return output
    return output


def _contract_axis_text_values(value: Any) -> list[str]:
    """Flatten declared contract values without inventing any vocabulary."""

    values = value if isinstance(value, (list, tuple, set)) else [value]
    output: list[str] = []
    seen: set[str] = set()
    for raw in values:
        if isinstance(raw, (list, tuple, set)):
            for item in _contract_axis_text_values(raw):
                if item not in seen:
                    seen.add(item)
                    output.append(item)
            continue
        if isinstance(raw, dict):
            emitted = False
            for key in (
                "query", "l2_query", "retrieval_query", "phrase", "term",
                "source", "candidate", "outcome", "mechanism", "input",
                "description", "rationale",
            ):
                if key in raw:
                    emitted = True
                    output.extend(_contract_axis_text_values(raw.get(key)))
            if not emitted:
                for nested in raw.values():
                    output.extend(_contract_axis_text_values(nested))
            continue
        normalized = re.sub(r"\s+", " ", str(raw or "").strip().lower())
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        output.append(normalized)
    return output


def _contract_axis_content_tokens(value: Any) -> set[str]:
    tokens = {
        token
        for text in _contract_axis_text_values(value)
        for token in re.findall(r"[a-z0-9][a-z0-9+_-]*", text)
    }
    return {
        token
        for token in tokens
        if token not in _GENERIC_RETRIEVAL_TERMS
        and token not in _LOW_INFORMATION_QUERY_AXIS_TERMS
        and token not in _CONTRACT_AXIS_NONIDENTIFYING_TOKENS
    }


def _contract_axis_phrase_is_informative(value: str) -> bool:
    """Require a phrase plus at least one identifying token for an SH axis."""

    normalized = re.sub(r"\s+", " ", str(value or "").strip().lower())
    tokens = re.findall(r"[a-z0-9][a-z0-9+_-]*", normalized)
    return bool(len(tokens) >= 2 and _contract_axis_content_tokens(normalized))


def _contract_axis_overlap(left: Any, right: Any) -> dict[str, Any]:
    left_phrases = _contract_axis_text_values(left)
    right_phrases = _contract_axis_text_values(right)
    left_tokens = _contract_axis_content_tokens(left_phrases)
    right_tokens = _contract_axis_content_tokens(right_phrases)
    shared = sorted(left_tokens & right_tokens)
    union = left_tokens | right_tokens
    exact_phrase = bool(set(left_phrases) & set(right_phrases))
    jaccard = len(shared) / len(union) if union else 0.0
    return {
        "left_phrases": left_phrases[:12],
        "right_phrases": right_phrases[:12],
        "left_content_tokens": sorted(left_tokens)[:20],
        "right_content_tokens": sorted(right_tokens)[:20],
        "shared_content_tokens": shared[:20],
        "exact_phrase_overlap": exact_phrase,
        "content_token_jaccard": round(jaccard, 4),
        "high_overlap": bool(exact_phrase or (union and jaccard >= 0.8)),
    }


def _contract_axis_structured_text_values(
    value: Any,
    *,
    allowed_keys: tuple[str, ...],
) -> list[str]:
    """Extract declared scientific text while ignoring structural metadata.

    Contracts intentionally persist provenance such as ``source=llm_explicit``
    next to an evidence-path query.  That provenance is not a synonym, a
    scientific object, or a query clause.  A generic recursive flattening of
    those dictionaries turned such labels into false cross-SH conflicts and
    could therefore stop every provider call in a project.

    This helper is deliberately allow-listed.  A dictionary contributes only
    values stored in its declared semantic text fields; identifiers, roles,
    source labels, flags, and registry names never enter lexical validation.
    """

    values = value if isinstance(value, (list, tuple, set)) else [value]
    output: list[str] = []
    seen: set[str] = set()
    for raw in values:
        if isinstance(raw, (list, tuple, set)):
            nested = _contract_axis_structured_text_values(
                raw,
                allowed_keys=allowed_keys,
            )
        elif isinstance(raw, dict):
            nested = []
            for key in allowed_keys:
                if key in raw:
                    nested.extend(_contract_axis_structured_text_values(
                        raw.get(key),
                        allowed_keys=allowed_keys,
                    ))
        else:
            normalized = re.sub(r"\s+", " ", str(raw or "").strip().lower())
            nested = [normalized] if normalized else []
        for item in nested:
            if item and item not in seen:
                seen.add(item)
                output.append(item)
    return output


def _contract_axis_unique(values: list[str]) -> list[str]:
    """Preserve lexical order while deduplicating audit-only values."""

    output: list[str] = []
    seen: set[str] = set()
    for raw in values:
        normalized = re.sub(r"\s+", " ", str(raw or "").strip().lower())
        if normalized and normalized not in seen:
            seen.add(normalized)
            output.append(normalized)
    return output


def _contract_axis_evidence_paths(alignment_contract: dict[str, Any]) -> dict[str, list[str]]:
    """Return query text separately from aliases for scope auditing.

    A provider-bound evidence-path query must retain a current-SH anchor.
    An alias can be a non-overlapping lexical synonym (for example, an
    abbreviation), so it must *not* be treated as a contradictory query just
    because it shares no literal tokens with the canonical object.  Explicit
    exclusions still audit aliases below.
    """

    contract = alignment_contract if isinstance(alignment_contract, dict) else {}
    retrieval_queries = _contract_axis_structured_text_values(
        [contract.get("evidence_paths")],
        allowed_keys=("query", "l2_query", "retrieval_query"),
    )
    alias_values = _contract_axis_structured_text_values(
        [contract.get("scientific_object_aliases")],
        allowed_keys=("phrase", "term", "alias", "synonym", "query"),
    )
    policy = contract.get("core_axis_policy")
    if isinstance(policy, dict):
        alias_values.extend(_contract_axis_structured_text_values(
            policy.get("focal_variable_synonym_dictionary"),
            allowed_keys=("phrase", "term", "alias", "synonym"),
        ))
    return {
        "retrieval_queries": _contract_axis_unique(retrieval_queries)[:48],
        "aliases": _contract_axis_unique(alias_values)[:48],
    }


def _contract_axis_gate_values(
    alignment_contract: dict[str, Any],
    *,
    axis: str,
) -> tuple[list[str], str]:
    """Prefer compact, canonical axis declarations for the pre-provider gate.

    Discovery fields intentionally retain broad ranked terms and a complete
    falsification sentence.  They are useful downstream, but phrases such as
    ``does not`` or a copied generic readout must never become a causal axis
    merely because they occur in a falsification condition.  When available,
    ``core_axis_policy`` is the canonical axis representation produced before
    those broad discovery expansions.  Contracts that lack both this policy
    and a compact causal contract now fail closed instead of recovering axis
    values from legacy declared fields.
    """

    contract = alignment_contract if isinstance(alignment_contract, dict) else {}
    policy = (
        contract.get("core_axis_policy")
        if isinstance(contract.get("core_axis_policy"), dict)
        else {}
    )
    policy_keys = {
        "input": ("focal_variable_phrases", "focal_variable_terms"),
        "mechanism": ("mechanism_phrases", "mechanism_terms"),
        "outcome": ("outcome_phrases", "outcome_terms"),
    }
    # The causal-contract outcome and pivotal mechanism are concise declared
    # values.  In particular, do not append comparison/falsification prose
    # to a canonical result axis just to make a lexical audit look complete.
    causal_contract = (
        contract.get("causal_contract")
        if isinstance(contract.get("causal_contract"), dict)
        else {}
    )
    causal_key = {
        "input": ("input", "independent_variable", "exposure", "intervention"),
        "mechanism": ("pivotal_mechanism", "mediator", "supporting_mediators"),
        "outcome": ("outcome",),
    }
    # The core mechanism policy has already removed terms recycled from the
    # input.  Prefer it for mechanism independence, otherwise a phrase such
    # as "quantum superposition of qubits" could appear distinct merely by
    # appending the named object to the independent variable.  Outcomes are
    # different: their compact causal declaration is preferred because the
    # core policy may intentionally strip shared upstream vocabulary and
    # leave an uninformative remainder such as "speed".
    preferred = _contract_axis_text_values([
        policy.get(key) for key in policy_keys.get(axis, ())
    ])
    causal_values = _contract_axis_text_values([
        causal_contract.get(key) for key in causal_key.get(axis, ())
    ])
    if axis == "outcome" and causal_values:
        return causal_values[:16], "causal_contract"
    if preferred:
        return preferred[:16], "core_axis_policy"
    if causal_values:
        return causal_values[:16], "causal_contract"

    return [], "missing_canonical_axis_policy"


def assess_contract_axis_degeneracy(
    alignment_contract: dict[str, Any],
    *,
    sub_hypothesis: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Fail closed when a retrieval contract has no independent causal axes.

    This is a pre-provider gate. It deliberately evaluates the *declared*
    contract and never learns replacement science from a provider response.
    A retrieval query cannot repair an object that is also its intervention, a
    copied mechanism, or an outcome/evidence-path mixture from another SH.
    """

    contract = alignment_contract if isinstance(alignment_contract, dict) else {}
    sub = sub_hypothesis if isinstance(sub_hypothesis, dict) else {}
    identity_values = _contract_axis_text_values([
        contract.get("scientific_object_identity_anchor"),
        contract.get("scientific_object_identity_phrases"),
    ])
    object_anchor_policy = (
        contract.get("scientific_object_anchor_policy")
        if isinstance(contract.get("scientific_object_anchor_policy"), dict)
        else {}
    )
    object_values = identity_values or _contract_axis_text_values([
        object_anchor_policy.get("strong_anchor_phrases"),
        object_anchor_policy.get("strong_anchor_terms"),
        object_anchor_policy.get("object_group"),
    ])
    input_values, input_source = _contract_axis_gate_values(contract, axis="input")
    mechanism_values, mechanism_source = _contract_axis_gate_values(contract, axis="mechanism")
    outcome_values, outcome_source = _contract_axis_gate_values(contract, axis="outcome")
    axis_values = {
        "scientific_object": object_values,
        "input": input_values,
        "mechanism": mechanism_values,
        "outcome": outcome_values,
    }
    focus_values = _contract_axis_text_values([
        contract.get("focus"),
        sub.get("focus"),
        sub.get("retrieval_query"),
    ])
    axis_sources = {
        "scientific_object": "declared_scientific_object",
        "input": input_source,
        "mechanism": mechanism_source,
        "outcome": outcome_source,
    }
    axis_information = {
        axis: {
            "source": axis_sources.get(axis, ""),
            "declared_phrases": list(values)[:16],
            "independent_high_information_phrases": [
                value for value in values if _contract_axis_phrase_is_informative(value)
            ][:12],
            "content_tokens": sorted(_contract_axis_content_tokens(values))[:24],
        }
        for axis, values in axis_values.items()
    }
    causal_contract = (
        contract.get("causal_contract")
        if isinstance(contract.get("causal_contract"), dict)
        else {}
    )
    constraint_type = str(causal_contract.get("constraint_type") or "").strip().lower()
    claim_types = " ".join(
        str(value or "").strip().lower()
        for value in (
            contract.get("claim_types") or causal_contract.get("claim_types") or []
        )
    )
    evidence_mode = str(
        contract.get("evidence_mode")
        or (sub.get("evidence_mode") if isinstance(sub, dict) else "")
        or ""
    ).strip().lower()
    # A parameter/theorem/observation contract may legitimately have no
    # mediator.  Requiring a mechanism axis for those claims turns a valid
    # object-input-outcome query into a false hard stop.  Causal/mechanistic
    # claims still require an independent pivotal edge.
    noncausal_markers = (
        "parameter_constraint", "theoretical_derivation", "formal_theorem",
        "consistency_or_no_go", "existence_or_detection", "measurement_validity",
        "method_performance", "model_comparison", "association_or_structure",
        "prediction_or_forecast", "feasibility",
    )
    mechanism_required = not (
        any(marker in constraint_type for marker in noncausal_markers)
        or any(marker in claim_types for marker in noncausal_markers)
    )
    if evidence_mode in {"theoretical_or_formal", "observational_inference"} and not constraint_type:
        mechanism_required = False
    weak_axes = [
        axis
        for axis in ("input", "mechanism", "outcome")
        if axis != "mechanism" or mechanism_required
        if not axis_information[axis]["independent_high_information_phrases"]
    ]
    overlaps = {
        "scientific_object_vs_input": _contract_axis_overlap(object_values, input_values),
        "input_vs_mechanism": _contract_axis_overlap(input_values, mechanism_values),
        "mechanism_vs_outcome": _contract_axis_overlap(mechanism_values, outcome_values),
    }
    object_input_overlap = bool(overlaps["scientific_object_vs_input"]["high_overlap"])
    duplicated_axis_pairs = [
        name for name, audit in overlaps.items()
        if name != "scientific_object_vs_input"
        and audit.get("high_overlap")
        and (mechanism_required or name != "input_vs_mechanism")
    ]

    focus_tokens = _contract_axis_content_tokens(focus_values)
    identity_scope_tokens = _contract_axis_content_tokens(
        [object_values, input_values, mechanism_values, focus_values]
    )
    scope_tokens = identity_scope_tokens | _contract_axis_content_tokens(outcome_values)
    outcome_scope_warnings: list[dict[str, Any]] = []
    if focus_tokens:
        for value in outcome_values:
            tokens = _contract_axis_content_tokens(value)
            if tokens and not (tokens & identity_scope_tokens):
                # A result axis is often lexically distinct from its input or
                # mediator (e.g. dose -> biomarker concentration).  Literal
                # non-overlap is therefore a diagnostic, not evidence of
                # cross-SH leakage.  Actual leakage is caught by explicit
                # sibling/exclusion terms below.
                outcome_scope_warnings.append({
                    "value": value[:240],
                    "reason": "declared_outcome_has_no_literal_input_or_mechanism_anchor",
                    "content_tokens": sorted(tokens)[:16],
                })
    evidence_path_audit_values = _contract_axis_evidence_paths(contract)
    evidence_paths = list(evidence_path_audit_values.get("retrieval_queries") or [])
    aliases = list(evidence_path_audit_values.get("aliases") or [])
    scope_conflicts: list[dict[str, Any]] = []
    for value in evidence_paths:
        tokens = _contract_axis_content_tokens(value)
        if not tokens:
            # A one-word alias such as "density" is not a harmless synonym:
            # retain the signal so the audit explains why calibration cannot
            # expand it into a provider query.
            raw_tokens = re.findall(r"[a-z0-9][a-z0-9+_-]*", value)
            if raw_tokens and all(
                token in _CONTRACT_AXIS_NONIDENTIFYING_TOKENS
                or token in _GENERIC_RETRIEVAL_TERMS
                or token in _LOW_INFORMATION_QUERY_AXIS_TERMS
                for token in raw_tokens
            ):
                scope_conflicts.append({
                    "value": value[:240],
                    "reason": "alias_or_evidence_path_has_only_nonidentifying_tokens",
                    "content_tokens": [],
                })
            continue
        if scope_tokens and not (tokens & scope_tokens):
            scope_conflicts.append({
                "value": value[:240],
                "reason": "evidence_path_query_has_no_declared_sh_scope_anchor",
                "content_tokens": sorted(tokens)[:16],
            })
    scope_conflicts = scope_conflicts[:16]

    explicit_scope_conflicts: list[str] = []
    forbidden = _contract_axis_text_values([
        contract.get("hard_exclusion_terms"),
        contract.get("query_forbidden_terms"),
    ])
    declared_text = " ".join(
        [
            *outcome_values,
            *evidence_paths,
            *aliases,
            *(_contract_axis_text_values(sub.get("focus"))),
        ]
    )
    for term in forbidden:
        if len(term) >= 3 and term in declared_text:
            explicit_scope_conflicts.append(term)

    failure_reasons: list[str] = []
    if object_input_overlap:
        failure_reasons.append("SCIENTIFIC_OBJECT_OVERLAPS_DECLARED_INPUT")
    if weak_axes:
        failure_reasons.append("AXIS_LACKS_INDEPENDENT_HIGH_INFORMATION_PHRASE")
    if duplicated_axis_pairs:
        failure_reasons.append("CAUSAL_AXES_HIGHLY_OVERLAP")
    if scope_conflicts:
        failure_reasons.append("EVIDENCE_PATH_QUERY_SCOPE_CONFLICT")
    if explicit_scope_conflicts:
        failure_reasons.append("DECLARED_SCOPE_FORBIDDEN_TERM_REENTERED")

    # Exact object/input duplication, a missing independent axis, duplicate causal axes, and a real
    # provider-bound query with no current-SH anchor are each sufficient:
    # their retrieval would either repeat one concept or dispatch a known
    # off-scope query.  Metadata labels and merely lexically distinct outcome
    # names are deliberately excluded from this decision.
    blocking = bool(
        object_input_overlap
        or weak_axes
        or duplicated_axis_pairs
        or scope_conflicts
        or explicit_scope_conflicts
    )
    return {
        "schema_version": "contract_axis_degeneracy_gate_v1",
        "status": "CONTRACT_AXIS_DEGENERATE" if blocking else "PASS",
        "blocking": blocking,
        "sub_hypothesis_id": str(contract.get("sub_hypothesis_id") or sub.get("id") or ""),
        "scientific_object_input_overlap": overlaps["scientific_object_vs_input"],
        "axis_overlaps": overlaps,
        "axis_information": axis_information,
        "axis_sources": axis_sources,
        "required_axes": {
            "scientific_object": True,
            "input": True,
            "mechanism": mechanism_required,
            "outcome": True,
        },
        "weak_axes": weak_axes,
        "duplicated_axis_pairs": duplicated_axis_pairs,
        "focus_phrases": focus_values[:12],
        "outcome_scope_warnings": outcome_scope_warnings[:16],
        # Kept for one schema cycle so existing project artifacts can be read;
        # callers must treat this as non-blocking diagnostics.
        "outcome_scope_conflicts": outcome_scope_warnings[:16],
        "evidence_path_and_synonym_scope_conflicts": scope_conflicts,
        "evidence_path_query_scope_conflicts": scope_conflicts,
        "alias_values_audited_for_explicit_exclusions": aliases[:48],
        "explicit_scope_conflicts": explicit_scope_conflicts[:16],
        "failure_reasons": failure_reasons,
        "recovery_sequence": [
            "freeze_provider_dispatch",
            "rebuild_scientific_object_independent_variable_mechanism_outcome_contract",
            "replace_word_level_anchors_with_independent_high_information_phrases",
            "remove_cross_subhypothesis_outcome_evidence_path_and_synonym_terms",
            "rerun_contract_validation_before_any_provider_query",
        ],
        "scientific_claim_authority": "CONTRACT_VALIDATION_ONLY_NO_PROVIDER_OR_LLM_VOCABULARY_LEARNING",
    }


def _contract_axis_query_clean(value: Any) -> str:
    """Normalize one phrase for a provider-bound repaired query."""

    text = re.sub(r"\s+", " ", str(value or "").strip())
    if not text:
        return ""
    text = re.sub(r"\b(?:AND|OR|NOT)\b", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"[()\"“”]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip(" -–—:;；,.")
    return text


def _contract_axis_query_terms(
    values: Any,
    *,
    limit: int = 4,
    require_content: bool = True,
) -> list[str]:
    """Select compact declared terms without learning replacement vocabulary."""

    output: list[str] = []
    seen: set[str] = set()
    for value in _contract_axis_text_values(values):
        clean = _contract_axis_query_clean(value)
        if not clean:
            continue
        if require_content and not _contract_axis_content_tokens(clean):
            continue
        key = clean.lower()
        if key in seen:
            continue
        seen.add(key)
        output.append(clean)
        if len(output) >= max(1, int(limit)):
            break
    return output


def _contract_axis_role_query_terms(role_id: Any, path_id: Any = "") -> tuple[list[str], bool]:
    """Return evidence-role modifiers for a repaired provider query."""

    role_key = re.sub(
        r"[^a-z0-9_]+",
        "_",
        str(role_id or path_id or "").strip().lower().replace("-", "_"),
    ).strip("_")
    registry: dict[str, Any] = {}
    try:  # pragma: no cover - import style depends on package execution mode
        from ._evidence_roles import EVIDENCE_ROLE_REGISTRY
        registry = EVIDENCE_ROLE_REGISTRY
    except ImportError:  # pragma: no cover
        try:
            from _evidence_roles import EVIDENCE_ROLE_REGISTRY
            registry = EVIDENCE_ROLE_REGISTRY
        except ImportError:
            registry = {}
    role = registry.get(role_key) if role_key else None
    anchors = [
        _contract_axis_query_clean(anchor)
        for anchor in ((role or {}).get("retrieval_anchors") or [])[:3]
    ]
    anchors = [anchor for anchor in anchors if anchor]
    if anchors:
        return anchors, True
    fallback_markers = {
        "direct_core": ["direct evidence", "validation"],
        "direct_core_evidence": ["direct evidence", "validation"],
        "core_path": ["direct evidence", "validation"],
        "core_validation": ["direct evidence", "validation"],
        "causal_validation": ["validation", "comparison"],
        "mechanism_discovery": ["mechanism", "association", "measurement"],
        "supporting_mechanism": ["mechanism", "measurement"],
        "boundary_or_generalization": ["boundary condition", "heterogeneity"],
        "boundary_or_safety_evidence": ["boundary condition", "failure mode"],
    }
    if role_key in fallback_markers:
        return fallback_markers[role_key], True
    if any(
        marker in role_key
        for marker in (
            "constraint", "observation", "validation", "systematic",
            "uncertainty", "calibration", "comparison", "boundary",
            "mechanism", "core",
        )
    ):
        return [_contract_axis_query_clean(role_key.replace("_", " "))], True
    return [], False


def _contract_axis_path_is_llm_explicit(path: dict[str, Any]) -> bool:
    """Only LLM-declared explicit evidence paths are eligible for query repair."""

    source_values = [
        path.get("source"),
        path.get("generated_by"),
        path.get("path_source"),
        path.get("origin"),
    ]
    normalized_sources = {
        re.sub(r"[^a-z0-9_]+", "_", str(value or "").strip().lower()).strip("_")
        for value in source_values
        if str(value or "").strip()
    }
    return bool(normalized_sources & {"llm_explicit", "explicit_llm_path", "explicit_llm"})


def _contract_axis_scope_policy_tokens(
    alignment_contract: dict[str, Any],
    *,
    sub_hypothesis: dict[str, Any] | None = None,
) -> set[str]:
    """Current-SH protected context used only to decide repair eligibility."""

    contract = alignment_contract if isinstance(alignment_contract, dict) else {}
    sub = sub_hypothesis if isinstance(sub_hypothesis, dict) else {}
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
    values: list[Any] = [
        scope_policy.get("validated_positive_anchor_terms"),
        scope_policy.get("protected_positive_terms"),
        scope_policy.get("allowed_scope_terms"),
        contract.get("protected_positive_terms"),
        contract.get("focus"),
        sub.get("focus"),
        sub.get("retrieval_query"),
    ]
    return _contract_axis_content_tokens(values)


def _contract_axis_join_query_terms(*groups: Any, limit: int = 12) -> str:
    output: list[str] = []
    seen: set[str] = set()
    for group in groups:
        values = group if isinstance(group, (list, tuple, set)) else [group]
        for value in values:
            clean = _contract_axis_query_clean(value)
            if not clean:
                continue
            key = clean.lower()
            if key in seen:
                continue
            seen.add(key)
            output.append(clean)
            if len(output) >= max(1, int(limit)):
                return re.sub(r"\s+", " ", " ".join(output)).strip()
    return re.sub(r"\s+", " ", " ".join(output)).strip()


def repair_contract_evidence_path_query_scope_conflicts(
    alignment_contract: dict[str, Any],
    *,
    sub_hypothesis: dict[str, Any] | None = None,
    audit: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Repair stale provider-bound evidence-path queries without weakening the gate.

    The pre-provider axis gate must still fail closed for genuinely unanchored
    or cross-scope queries.  This repair is intentionally narrow: it only runs
    when the contract axes are otherwise healthy and the sole blocking reason
    is that an evidence-role query lost the declared SH anchor.  The repaired
    query is rebuilt from declared contract axes plus evidence-role modifiers;
    stale object/readout text from the bad query is not used as the primary
    anchor.
    """

    contract = dict(alignment_contract) if isinstance(alignment_contract, dict) else {}
    base_audit = (
        dict(audit)
        if isinstance(audit, dict)
        else assess_contract_axis_degeneracy(contract, sub_hypothesis=sub_hypothesis)
    )
    failure_reasons = {
        str(reason)
        for reason in (base_audit.get("failure_reasons") or [])
        if str(reason)
    }
    conflicts = [
        item for item in (base_audit.get("evidence_path_query_scope_conflicts") or [])
        if isinstance(item, dict)
    ]
    repair_audit: dict[str, Any] = {
        "schema_version": "evidence_path_query_scope_repair_v1",
        "status": "not_applicable",
        "initial_failure_reasons": sorted(failure_reasons),
        "post_failure_reasons": sorted(failure_reasons),
        "repair_count": 0,
        "rejected_count": 0,
        "repairs": [],
        "rejections": [],
        "policy": (
            "repair only stale provider-bound evidence-role queries; preserve "
            "contract-axis gate semantics and keep real cross-scope queries blocked"
        ),
    }
    if failure_reasons != {"EVIDENCE_PATH_QUERY_SCOPE_CONFLICT"} or not conflicts:
        repair_audit["status"] = "not_repairable_failure_class"
        return {
            "changed": False,
            "contract": contract,
            "initial_audit": base_audit,
            "post_repair_audit": base_audit,
            "repair_audit": repair_audit,
        }
    if (
        base_audit.get("weak_axes")
        or base_audit.get("duplicated_axis_pairs")
        or base_audit.get("explicit_scope_conflicts")
        or (
            isinstance(base_audit.get("scientific_object_input_overlap"), dict)
            and base_audit["scientific_object_input_overlap"].get("high_overlap")
        )
    ):
        repair_audit["status"] = "not_repairable_axis_unhealthy"
        return {
            "changed": False,
            "contract": contract,
            "initial_audit": base_audit,
            "post_repair_audit": base_audit,
            "repair_audit": repair_audit,
        }

    object_policy = (
        contract.get("scientific_object_anchor_policy")
        if isinstance(contract.get("scientific_object_anchor_policy"), dict)
        else {}
    )
    identity_anchor_terms = _contract_axis_query_terms(
        contract.get("scientific_object_identity_anchor"),
        limit=1,
    )
    object_values = _contract_axis_query_terms(
        [
            identity_anchor_terms,
            contract.get("scientific_object_identity_phrases"),
            object_policy.get("strong_anchor_phrases"),
            object_policy.get("strong_anchor_terms"),
            object_policy.get("object_group"),
        ],
        limit=3,
    )
    input_values, _ = _contract_axis_gate_values(contract, axis="input")
    mechanism_values, _ = _contract_axis_gate_values(contract, axis="mechanism")
    outcome_values, _ = _contract_axis_gate_values(contract, axis="outcome")
    input_terms = _contract_axis_query_terms(input_values, limit=2)
    mechanism_terms = _contract_axis_query_terms(mechanism_values, limit=2)
    outcome_terms = _contract_axis_query_terms(
        [
            outcome_values,
            contract.get("dependent_variables"),
            contract.get("dependent_variable"),
        ],
        limit=2,
        require_content=False,
    )
    if not identity_anchor_terms or not object_values or not (input_terms or mechanism_terms):
        repair_audit["status"] = "not_repairable_missing_declared_anchor_terms"
        return {
            "changed": False,
            "contract": contract,
            "initial_audit": base_audit,
            "post_repair_audit": base_audit,
            "repair_audit": repair_audit,
        }

    conflict_values = {
        re.sub(r"\s+", " ", str(item.get("value") or "").strip().lower())
        for item in conflicts
        if str(item.get("value") or "").strip()
    }
    protected_tokens = _contract_axis_scope_policy_tokens(
        contract,
        sub_hypothesis=sub_hypothesis,
    )
    evidence_paths = [
        dict(path) if isinstance(path, dict) else path
        for path in (contract.get("evidence_paths") or [])
    ]
    changed = False
    repairs: list[dict[str, Any]] = []
    rejections: list[dict[str, Any]] = []
    for index, path in enumerate(evidence_paths):
        if not isinstance(path, dict):
            continue
        raw_query = str(
            path.get("retrieval_query")
            or path.get("query")
            or path.get("l2_query")
            or ""
        ).strip()
        query_key = re.sub(r"\s+", " ", raw_query.lower())
        if query_key not in conflict_values:
            continue
        role_terms, role_known = _contract_axis_role_query_terms(
            path.get("role"),
            path.get("id"),
        )
        path_label = str(path.get("id") or path.get("role") or f"path_{index + 1}")
        if not _contract_axis_path_is_llm_explicit(path):
            rejections.append({
                "path_id": path_label,
                "old_query": raw_query[:240],
                "rejection_reason": "evidence_path_source_not_llm_explicit",
                "source": str(path.get("source") or ""),
            })
            continue
        if not role_known:
            rejections.append({
                "path_id": path_label,
                "old_query": raw_query[:240],
                "rejection_reason": "missing_registered_or_recognized_evidence_role",
            })
            continue
        query_tokens = _contract_axis_content_tokens(raw_query)
        protected_overlap = sorted(query_tokens & protected_tokens)[:16]
        if not protected_overlap:
            rejections.append({
                "path_id": path_label,
                "old_query": raw_query[:240],
                "rejection_reason": "conflicting_query_lacks_current_sh_protected_context",
            })
            continue
        repaired_query = _contract_axis_join_query_terms(
            object_values[:2],
            input_terms[:1],
            mechanism_terms[:1],
            role_terms[:3],
            outcome_terms[:1],
            limit=12,
        )
        if not repaired_query:
            rejections.append({
                "path_id": path_label,
                "old_query": raw_query[:240],
                "rejection_reason": "empty_repaired_query",
            })
            continue
        path["retrieval_query_before_scope_repair"] = raw_query
        path["retrieval_query"] = repaired_query
        path["query_rewrite_reason"] = "provider_bound_query_scope_repaired"
        path["provider_bound_query_scope_repair"] = {
            "schema_version": "provider_bound_query_scope_repair_v1",
            "reason": "evidence_path_query_has_no_declared_sh_scope_anchor",
            "required_object_anchors": object_values[:3],
            "required_edge_anchors": (input_terms + mechanism_terms)[:4],
            "role_query_terms": role_terms[:4],
            "readout_or_measurement_terms": outcome_terms[:3],
            "protected_context_overlap": protected_overlap,
            "old_query": raw_query[:240],
            "repaired_query": repaired_query[:240],
        }
        repairs.append({
            "path_id": path_label,
            "role": str(path.get("role") or ""),
            "old_query": raw_query[:240],
            "repaired_query": repaired_query[:240],
            "protected_context_overlap": protected_overlap,
        })
        changed = True
    contract["evidence_paths"] = evidence_paths
    repair_audit.update({
        "repair_count": len(repairs),
        "rejected_count": len(rejections),
        "repairs": repairs[:16],
        "rejections": rejections[:16],
        "status": (
            "repair_applied"
            if changed
            else "no_repairable_conflicting_evidence_paths"
        ),
    })
    if changed:
        post_audit = assess_contract_axis_degeneracy(
            contract,
            sub_hypothesis=sub_hypothesis,
        )
        repair_audit["post_failure_reasons"] = list(post_audit.get("failure_reasons") or [])
        repair_audit["post_status"] = str(post_audit.get("status") or "")
    else:
        post_audit = base_audit
    contract["evidence_path_query_scope_repair_audit"] = repair_audit
    return {
        "changed": changed,
        "contract": contract,
        "initial_audit": base_audit,
        "post_repair_audit": post_audit,
        "repair_audit": repair_audit,
    }


def contract_axis_auxiliary_dispatch_allowed(
    alignment_contract: dict[str, Any],
    audit: dict[str, Any] | None = None,
) -> bool:
    """A malformed causal contract is never routed through an auxiliary fallback.

    Related-corpus retrieval used to hide an invalid object/input/mechanism/
    outcome contract behind a non-core branch.  That produces attractive but
    untraceable papers and lets downstream state mutate a maturity decision.
    Contract repair must now happen before any provider dispatch.
    """

    del alignment_contract, audit
    return False


def calibration_diagnostic_metadata_batch(
    candidates: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    *,
    alignment_contract: dict[str, Any],
    limit: int = 8,
) -> dict[str, Any]:
    """Make a bounded, source-addressable metadata batch for mismatch repair.

    Only non-generic terms from candidates that independently contain the
    declared object *and* input are permitted as optional LLM refinements.
    If the small batch contains no such candidate, the correct answer is to
    rebuild the contract, not to append broad methodology words.
    """

    contract = alignment_contract if isinstance(alignment_contract, dict) else {}
    object_anchors = [
        value for value in _optimizer_object_anchor_terms(contract)
        if _contract_axis_phrase_is_informative(value)
    ]
    input_anchors = [
        value for value in _contract_declared_axis_terms(contract, axis="input", limit=12)
        if _contract_axis_phrase_is_informative(value)
    ]
    source_papers: list[dict[str, Any]] = []
    permitted_terms: set[str] = set()
    source_ids_by_term: dict[str, set[str]] = {}
    for ordinal, raw in enumerate(candidates or []):
        if len(source_papers) >= max(1, min(int(limit or 8), 12)):
            break
        if not isinstance(raw, dict):
            continue
        title = re.sub(r"\s+", " ", str(raw.get("title") or "").strip())
        abstract = re.sub(r"\s+", " ", str(raw.get("abstract") or "").strip())
        if not title and not abstract:
            continue
        source_id = str(
            raw.get("doi") or raw.get("paper_id") or raw.get("id")
            or raw.get("result_index") or f"batch_{ordinal + 1}"
        ).strip()
        text = f"{title} {abstract}".lower()
        object_hits = [anchor for anchor in object_anchors if anchor in text]
        input_hits = [anchor for anchor in input_anchors if anchor in text]
        source_papers.append({
            "source_id": source_id,
            "title": title[:300],
            "abstract": abstract[:900],
            "object_anchor_hits": object_hits[:6],
            "input_anchor_hits": input_hits[:6],
            "eligible_for_term_refinement": bool(object_hits and input_hits),
        })
        if not (object_hits and input_hits):
            continue
        for token in re.findall(r"[a-z][a-z0-9+_-]{2,}", text):
            if (
                token in _GENERIC_RETRIEVAL_TERMS
                or token in _LOW_INFORMATION_QUERY_AXIS_TERMS
                or token in _CONTRACT_AXIS_NONIDENTIFYING_TOKENS
                or token in _CALIBRATION_REFINEMENT_GENERIC_TOKENS
            ):
                continue
            permitted_terms.add(token)
            source_ids_by_term.setdefault(token, set()).add(source_id)
    contract_terms = _contract_axis_content_tokens([
        object_anchors,
        input_anchors,
        _contract_declared_axis_terms(contract, axis="mechanism", limit=12),
        _contract_declared_axis_terms(contract, axis="outcome", limit=12),
    ])
    return {
        "schema_version": "calibration_mismatch_metadata_batch_v1",
        "status": (
            "SOURCE_GROUNDED_REFINEMENT_TERMS_READY"
            if permitted_terms
            else "NO_CONTRACT_ALIGNED_METADATA_TERMS"
        ),
        "paper_count": len(source_papers),
        "papers": source_papers,
        "contract_terms": sorted(contract_terms)[:96],
        "permitted_refinement_terms": sorted(permitted_terms - contract_terms)[:96],
        "term_source_ids": {
            term: sorted(source_ids)[:8]
            for term, source_ids in sorted(source_ids_by_term.items())
            if term in permitted_terms - contract_terms
        },
        "policy": "new_query_terms_must_be_contract_terms_or_non_generic_terms_observed_in_object_and_input_aligned_batch_papers",
    }


def _quoted_contract_clause(terms: list[str], *, limit: int = 3) -> str:
    selected: list[str] = []
    seen: set[str] = set()
    for term in terms:
        normalized = re.sub(r"\s+", " ", str(term or "").replace('"', " ").strip())
        key = normalized.lower()
        if len(normalized) < 3 or key in seen:
            continue
        seen.add(key)
        selected.append(f'"{normalized}"')
        if len(selected) >= max(1, int(limit)):
            break
    return " OR ".join(selected)


def _lexical_calibration_target_lane(alignment_contract: dict[str, Any]) -> str:
    profile = (
        alignment_contract.get("epistemic_profile")
        if isinstance(alignment_contract.get("epistemic_profile"), dict)
        else {}
    )
    mode = str(
        profile.get("primary_mode")
        or alignment_contract.get("epistemic_mode")
        or alignment_contract.get("evidence_mode")
        or ""
    ).strip().lower()
    if mode in {"theoretical_derivation", "mathematical_proof", "formal_analysis"}:
        return "THEORETICAL_OR_FORMAL_EVIDENCE"
    if mode in {"computational_simulation", "computational_modeling", "simulation"}:
        return "COMPUTATIONAL_MODEL_DISCRIMINATION"
    return "MECHANISM_DISCOVERY"


def contract_lexical_alignment_repair_payload(
    *,
    alignment_contract: dict[str, Any],
    failure_diagnostics: dict[str, Any],
) -> dict[str, Any] | None:
    """Build a small, contract-anchored calibration plan for lexical mismatch.

    The plan separates declared input, mechanism, and outcome routes.  It is
    intentionally shorter and less assumption-heavy than a normal evidence
    search: first establish whether provider vocabulary can retrieve the SH's
    declared object plus axis, then let the existing coarse alignment gate
    decide whether any candidate merits full-text resolution.
    """

    diagnostics = failure_diagnostics if isinstance(failure_diagnostics, dict) else {}
    repair = (
        diagnostics.get("lexical_alignment_repair")
        if isinstance(diagnostics.get("lexical_alignment_repair"), dict)
        else {}
    )
    if repair.get("status") != "CONTRACT_LEXICAL_ALIGNMENT_FAILURE":
        return None

    axis_audit = assess_contract_axis_degeneracy(alignment_contract)
    if axis_audit.get("blocking"):
        return {
            "failure_class": str(
                diagnostics.get("failure_class") or "RELATED_FULLTEXT_COUNT_SHORTFALL"
            ),
            "repair_template": "contract_axis_degeneracy_gate_v1",
            "repair_status": "CONTRACT_AXIS_DEGENERATE",
            "queries": [],
            "preserved_anchors": [],
            "proposed_synonyms": [],
            "negative_terms": [],
            "contract_axis_degeneracy": axis_audit,
            "expected_improvement": (
                "No calibration query is emitted. Rebuild the independent scientific-object, "
                "input, mechanism, and outcome contract before provider retrieval."
            ),
            "scientific_claim_authority": "NO_QUERY_EXPANSION_WITH_DEGENERATE_CONTRACT",
        }

    object_anchors = _optimizer_object_anchor_terms(alignment_contract)
    input_terms = _contract_declared_axis_terms(alignment_contract, axis="input")
    mechanism_terms = _contract_declared_axis_terms(alignment_contract, axis="mechanism")
    outcome_terms = _contract_declared_axis_terms(alignment_contract, axis="outcome")
    object_anchor = next(
        (item for item in object_anchors if len(item.split()) >= 2),
        object_anchors[0] if object_anchors else "",
    )
    if not object_anchor or not input_terms:
        missing = []
        if not object_anchor:
            missing.append("scientific_object_anchor")
        if not input_terms:
            missing.append("declared_input_anchor")
        return {
            "failure_class": str(
                diagnostics.get("failure_class") or "RELATED_FULLTEXT_COUNT_SHORTFALL"
            ),
            "repair_template": "contract_lexical_alignment_v1",
            "repair_status": "CONTRACT_UNDERSPECIFIED_FOR_LEXICAL_CALIBRATION",
            "missing_contract_fields": missing,
            "queries": [],
            "preserved_anchors": [*object_anchors[:3], *input_terms[:3]],
            "proposed_synonyms": [],
            "negative_terms": [],
            "expected_improvement": (
                "No provider query is emitted because the active contract lacks a usable "
                "object or declared-input anchor; require contract repair before retrieval."
            ),
            "scientific_claim_authority": "NO_QUERY_EXPANSION_WITHOUT_DECLARED_ANCHORS",
        }

    lane = _lexical_calibration_target_lane(alignment_contract)
    object_clause = _quoted_contract_clause([object_anchor], limit=1)
    input_clause = _quoted_contract_clause(input_terms, limit=3)
    route_specs: list[tuple[str, list[str], str]] = [
        ("declared_input", [], "L2_top_latest"),
    ]
    if mechanism_terms:
        route_specs.append(("declared_input_plus_mechanism", mechanism_terms, "L4_regular"))
    if outcome_terms:
        route_specs.append(("declared_input_plus_outcome", outcome_terms, "L4_regular"))

    queries: list[dict[str, Any]] = []
    seen: set[str] = set()
    for route, secondary_terms, layer in route_specs:
        clauses = [f"({object_clause})", f"({input_clause})"]
        secondary_clause = _quoted_contract_clause(secondary_terms, limit=2)
        if secondary_clause:
            clauses.append(f"({secondary_clause})")
        query = " AND ".join(clauses)
        signature = scientific_query_signature(query)
        if not signature or signature in seen:
            continue
        seen.add(signature)
        queries.append({
            "target_layer": layer,
            "target_lane": lane,
            "query": query,
            "evidence_path_role": "contract_lexical_calibration",
            "lexical_calibration": True,
            "calibration_route": route,
            "calibration_contract_axes": [
                "scientific_object",
                "declared_input",
                *( ["mechanism"] if route.endswith("mechanism") else [] ),
                *( ["outcome"] if route.endswith("outcome") else [] ),
            ],
            "rationale": (
                "Contract lexical calibration: retrieve only the declared scientific object "
                "plus declared causal axis before any broader evidence-role expansion."
            ),
        })
    return {
        "failure_class": str(
            diagnostics.get("failure_class") or "RELATED_FULLTEXT_COUNT_SHORTFALL"
        ),
        "repair_template": "contract_lexical_alignment_v1",
        "repair_status": "CALIBRATION_QUERIES_READY",
        "preserved_anchors": [object_anchor, *input_terms[:3]],
        "proposed_synonyms": [],
        "negative_terms": [],
        "queries": queries[:3],
        "expected_improvement": (
            "Measure object-plus-input recall with only active-contract terms, then route "
            "only coarse-aligned candidates to full-text resolution."
        ),
        "scientific_claim_authority": "RETRIEVAL_CALIBRATION_ONLY_NOT_SCIENTIFIC_CONTRACT_MUTATION",
    }


def _query_has_context_only_marker(positive_query: str) -> bool:
    return _query_contains_any(positive_query, _CONTEXT_ONLY_QUERY_MARKERS)


def _query_shape_diagnostics(
    positive_query: str,
    *,
    role: str,
    alignment_contract: dict[str, Any],
) -> dict[str, bool]:
    endpoint_anchors = _contract_endpoint_anchors(alignment_contract)
    has_design = _query_contains_any(positive_query, _QUERY_DESIGN_ANCHORS)
    has_intervention = _query_contains_any(positive_query, _QUERY_INTERVENTION_ANCHORS)
    has_comparison = _query_contains_any(positive_query, _QUERY_COMPARISON_ANCHORS)
    has_adverse_or_reversal = _query_contains_any(
        positive_query,
        _ADVERSE_OR_REVERSAL_QUERY_ANCHORS,
    )
    has_endpoint = _query_contains_any(positive_query, _QUERY_ENDPOINT_ANCHORS) or any(
        anchor in positive_query for anchor in endpoint_anchors
    )
    predictive = role == "predictive_generalization"
    return {
        "has_design": has_design,
        "has_intervention": has_intervention,
        "has_comparison": has_comparison,
        "has_adverse_or_reversal": has_adverse_or_reversal,
        "has_endpoint": has_endpoint,
        "experimental_or_validation_shaped": (
            bool((has_design or has_intervention or has_comparison) and (has_endpoint or has_comparison))
            if not predictive
            else bool((has_design or has_comparison) and (has_endpoint or has_comparison))
        ),
    }


def enrich_unique_provider_execution_replan_provenance(
    payload: dict[str, Any] | None,
    *,
    required_replan_branches: list[str] | tuple[str, ...] | set[str] | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Fill omitted branch provenance only when the target is unambiguous.

    Provider-execution replan queries are constrained to replace named failed
    branches. An LLM may omit that metadata even when its query text is valid.
    A single requested branch makes the missing value deterministic; multiple
    requests do not, so they remain subject to the strict validator.
    """

    result = dict(payload) if isinstance(payload, dict) else {}
    requested = list(dict.fromkeys(
        str(item).strip()
        for item in (required_replan_branches or [])
        if str(item).strip()
    ))
    audit = {
        "schema_version": "provider_execution_replan_provenance_normalization_v1",
        "required_replan_branches": requested,
        "status": "NOT_APPLICABLE",
        "autofilled_query_indexes": [],
    }
    if not requested:
        return result, audit
    if len(requested) != 1:
        audit["status"] = "NOT_APPLIED_AMBIGUOUS_BRANCH_TARGET"
        return result, audit

    raw_queries = result.get("queries")
    if not isinstance(raw_queries, list):
        audit["status"] = "NOT_APPLIED_NO_QUERY_LIST"
        return result, audit

    target_branch = requested[0]
    normalized_queries: list[Any] = []
    autofilled_indexes: list[int] = []
    for index, raw_query in enumerate(raw_queries):
        if not isinstance(raw_query, dict):
            normalized_queries.append(raw_query)
            continue
        item = dict(raw_query)
        if not str(item.get("replan_of_branch") or "").strip():
            item["replan_of_branch"] = target_branch
            autofilled_indexes.append(index)
        normalized_queries.append(item)

    result["queries"] = normalized_queries
    audit["autofilled_query_indexes"] = autofilled_indexes
    audit["status"] = (
        "APPLIED_UNAMBIGUOUS_BRANCH_TARGET"
        if autofilled_indexes
        else "NO_MISSING_BRANCH_PROVENANCE"
    )
    return result, audit


def validate_query_optimizer_payload(
    payload: dict[str, Any],
    *,
    alignment_contract: dict[str, Any],
    previous_queries: list[str] | None = None,
    max_queries: int = 5,
    required_replan_branches: list[str] | tuple[str, ...] | set[str] | None = None,
) -> dict[str, Any]:
    previous_fingerprints = {
        query_fingerprint(item)
        for item in (previous_queries or [])
        if query_fingerprint(item)
    }
    previous_signatures = {
        scientific_query_signature(item)
        for item in (previous_queries or [])
        if scientific_query_signature(item)
    }
    normalized_required_replan_branches = {
        str(item).strip()
        for item in (required_replan_branches or [])
        if str(item).strip()
    }
    direct_core_allowed_by_maturity = _direct_core_allowed_by_object_maturity(
        alignment_contract
    )
    object_anchors = _optimizer_object_anchor_terms(alignment_contract)
    predictive_mode = str(alignment_contract.get("evidence_mode") or "") == "predictive_generalization"
    moderator_anchors = [
        re.sub(r"\s+", " ", str(item or "").strip().lower())
        for item in alignment_contract.get("moderator_terms") or []
        if len(re.sub(r"\s+", " ", str(item or "").strip())) >= 3
    ]
    causal_anchors = list(dict.fromkeys(
        _contract_declared_axis_terms(alignment_contract, axis="input", limit=16)
        + _contract_declared_axis_terms(alignment_contract, axis="mechanism", limit=16)
        + _contract_declared_axis_terms(alignment_contract, axis="outcome", limit=16)
    ))
    explicit_exclusions = [
        re.sub(r"\s+", " ", str(item or "").strip().lower())
        for item in (
            alignment_contract.get("hard_exclusion_terms")
            or alignment_contract.get("explicit_exclusion_terms")
            or []
        )
        if re.sub(r"\s+", " ", str(item or "").strip())
    ]
    scope_policy = (
        alignment_contract.get("subhypothesis_scope_policy")
        if isinstance(alignment_contract.get("subhypothesis_scope_policy"), dict)
        else {}
    )
    scope_forbidden_terms = [
        re.sub(r"\s+", " ", str(item or "").strip().lower())
        for item in (
            list(alignment_contract.get("query_forbidden_terms") or [])
            + list(scope_policy.get("query_forbidden_terms") or [])
            + list(alignment_contract.get("hard_exclusion_terms") or [])
        )
        if re.sub(r"\s+", " ", str(item or "").strip())
    ]
    metadata_grounded_calibration_refinement = bool(
        str(payload.get("repair_template") or "")
        == "calibration_plan_mismatch_metadata_refinement_v1"
    )
    permitted_refinement_tokens = {
        token
        for value in (payload.get("permitted_refinement_terms") or [])
        for token in re.findall(r"[a-z][a-z0-9+_-]*", str(value or "").lower())
        if token
    }
    contract_refinement_tokens = _contract_axis_content_tokens([
        object_anchors,
        _contract_declared_axis_terms(alignment_contract, axis="input", limit=16),
        _contract_declared_axis_terms(alignment_contract, axis="mechanism", limit=16),
        _contract_declared_axis_terms(alignment_contract, axis="outcome", limit=16),
    ])
    allowed_metadata_refinement_tokens = contract_refinement_tokens | permitted_refinement_tokens
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    seen = set(previous_fingerprints)
    seen_signatures = set(previous_signatures)
    allowed_layers = set(NON_PREPRINT_LAYERS)
    allowed_lanes = {
        "THEORETICAL_FRAMEWORK",
        "THEORETICAL_OR_FORMAL_EVIDENCE",
        "COMPUTATIONAL_MODEL_DISCRIMINATION",
        "OBSERVATIONAL_COHORT_EVIDENCE",
        "ECOLOGICAL_FIELD_OBSERVATION",
        "ECOLOGICAL_MONITORING",
        "ECOLOGICAL_LONGITUDINAL_MONITORING",
        "SURVEILLANCE_SYSTEM_VALIDATION",
        "MECHANISM_DISCOVERY",
        "CAUSAL_VALIDATION",
        "PREDICTIVE_VALIDATION",
        "COMPONENT_EVIDENCE",
        "TRANSLATIONAL_BRIDGE_EVIDENCE",
        BOUNDARY_OR_NEGATIVE_EVIDENCE_LANE,
        ADVERSE_OR_REVERSAL_EVIDENCE_LANE,
    }
    for raw in list(payload.get("queries") or [])[: max(0, int(max_queries))]:
        if not isinstance(raw, dict):
            continue
        item = dict(raw)
        query = re.sub(r"\s+", " ", str(item.get("query") or "").strip())
        layer = str(item.get("target_layer") or "L4_regular")
        lane = str(item.get("target_lane") or "MECHANISM_DISCOVERY").upper()
        lexical_calibration = item.get("lexical_calibration") is True
        replan_of_branch = str(item.get("replan_of_branch") or "").strip()
        reasons: list[str] = []
        if not query or len(query) > 800:
            reasons.append("empty_or_too_long")
        if normalized_required_replan_branches:
            if not replan_of_branch:
                reasons.append("provider_execution_replan_branch_missing")
            elif replan_of_branch not in normalized_required_replan_branches:
                reasons.append("provider_execution_replan_branch_not_requested")
        if re.search(r"[\u3400-\u9fff\uf900-\ufaff]", query):
            reasons.append("query_not_english")
        positive = _positive_query_text(query).lower()
        if metadata_grounded_calibration_refinement:
            query_tokens = {
                token
                for token in re.findall(r"[a-z][a-z0-9+_-]*", positive)
                if token not in {"and", "or", "not"}
            }
            generic_additions = sorted(
                token
                for token in query_tokens - contract_refinement_tokens
                if token in _CALIBRATION_REFINEMENT_GENERIC_TOKENS
                or token in _GENERIC_RETRIEVAL_TERMS
                or token in _LOW_INFORMATION_QUERY_AXIS_TERMS
                or token in _CONTRACT_AXIS_NONIDENTIFYING_TOKENS
            )
            ungrounded_additions = sorted(
                token
                for token in query_tokens
                if token not in allowed_metadata_refinement_tokens
                and token not in _CALIBRATION_REFINEMENT_GENERIC_TOKENS
            )
            if generic_additions:
                reasons.append(
                    "metadata_calibration_refinement_inserts_generic_terms:"
                    + ",".join(generic_additions[:8])
                )
            if ungrounded_additions:
                reasons.append(
                    "metadata_calibration_refinement_has_unverified_terms:"
                    + ",".join(ungrounded_additions[:8])
                )
            if not permitted_refinement_tokens:
                reasons.append("metadata_calibration_refinement_has_no_source_grounded_terms")
        if object_anchors and not any(anchor in positive for anchor in object_anchors):
            reasons.append("scientific_object_anchor_missing")
        if predictive_mode:
            if lane not in {
                "THEORETICAL_FRAMEWORK",
                "PREDICTIVE_VALIDATION",
                BOUNDARY_OR_NEGATIVE_EVIDENCE_LANE,
                ADVERSE_OR_REVERSAL_EVIDENCE_LANE,
            }:
                reasons.append("causal_intervention_lane_not_applicable_to_predictive_generalization")
            if (
                lane in {"PREDICTIVE_VALIDATION", BOUNDARY_OR_NEGATIVE_EVIDENCE_LANE}
                and moderator_anchors
                and not any(anchor in positive for anchor in moderator_anchors)
            ):
                reasons.append("predictive_boundary_anchor_missing")
        # Evidence lanes route a query after retrieval.  They are not words a
        # paper must contain.  Every query instead needs one actual scientific
        # axis declared by the active contract.
        if causal_anchors and not any(anchor in positive for anchor in causal_anchors):
            reasons.append("scientific_axis_anchor_missing")
        if lexical_calibration:
            declared_input_anchors = _contract_declared_axis_terms(
                alignment_contract,
                axis="input",
            )
            if not declared_input_anchors:
                reasons.append("lexical_calibration_requires_declared_input_anchor")
            elif not any(anchor in positive for anchor in declared_input_anchors):
                reasons.append("lexical_calibration_declared_input_anchor_missing")
        if any(exclusion and exclusion in positive for exclusion in explicit_exclusions):
            reasons.append("positive_query_hits_excluded_object")
        if any(forbidden and forbidden in positive for forbidden in scope_forbidden_terms):
            reasons.append("positive_query_hits_forbidden_scope_term")
        if layer not in allowed_layers:
            reasons.append("unsupported_or_preprint_target_layer")
        if lane not in allowed_lanes:
            reasons.append("unsupported_target_lane")
        if lane == ADVERSE_OR_REVERSAL_EVIDENCE_LANE and layer not in {"L2_top_latest", "L4_regular"}:
            reasons.append("adverse_or_reversal_lane_must_target_l2_or_l4")
        if lane == BOUNDARY_OR_NEGATIVE_EVIDENCE_LANE and layer not in {"L0_review", "L2_top_latest", "L4_regular"}:
            reasons.append("boundary_lane_must_target_l0_l2_or_l4")
        if lane == "COMPONENT_EVIDENCE" and layer not in {"L2_top_latest", "L4_regular"}:
            reasons.append("component_evidence_lane_must_target_l2_or_l4")
        if lane == "TRANSLATIONAL_BRIDGE_EVIDENCE" and layer not in {"L2_top_latest", "L4_regular"}:
            reasons.append("translational_bridge_lane_must_target_l2_or_l4")
        query_role = _query_validation_role(item, layer=layer, lane=lane)
        if query_role == "context_review":
            if layer != "L0_review":
                reasons.append("context_or_review_query_must_target_L0_review")
        else:
            if _query_has_context_only_marker(positive):
                reasons.append("context_only_marker_in_non_context_query")
            shape = _query_shape_diagnostics(
                positive,
                role=query_role,
                alignment_contract=alignment_contract,
            )
            if lexical_calibration:
                # Calibration establishes whether the declared object plus
                # declared input can be retrieved at all.  Requiring a design
                # word at this stage reintroduces the same vocabulary drift
                # that the calibration path is meant to diagnose.
                pass
            elif query_role in {"theoretical_or_formal", "observational_or_system"}:
                # Formal, computational, observational, and surveillance
                # paths are still bound by object and scientific-axis anchors
                # above, but are not invalid merely for lacking an experimental
                # intervention or control-group phrase.
                pass
            elif query_role == "predictive_generalization":
                if not (shape["has_design"] or shape["has_comparison"]):
                    reasons.append("predictive_validation_or_comparison_anchor_missing")
                if not (shape["has_endpoint"] or shape["has_comparison"]):
                    reasons.append("predictive_endpoint_or_performance_anchor_missing")
            elif query_role in {"core_validation", "supporting_mechanism", "boundary", "adverse_or_reversal"}:
                if query_role == "adverse_or_reversal" and not shape["has_adverse_or_reversal"]:
                    reasons.append("adverse_or_reversal_anchor_missing")
                if not (
                    shape["has_design"]
                    or shape["has_intervention"]
                    or shape["has_comparison"]
                    or (query_role == "adverse_or_reversal" and shape["has_adverse_or_reversal"])
                ):
                    reasons.append("experimental_design_or_perturbation_anchor_missing")
                if not (shape["has_endpoint"] or shape["has_comparison"]):
                    reasons.append("measurable_endpoint_or_comparison_anchor_missing")
        fingerprint = query_fingerprint(query)
        if not fingerprint or fingerprint in seen:
            reasons.append("duplicate_query")
        scientific_signature = scientific_query_signature(query)
        if not scientific_signature or scientific_signature in seen_signatures:
            reasons.append("role_only_query_variant")
        if reasons:
            rejected.append({"query": query[:800], "target_layer": layer, "target_lane": lane, "reasons": reasons})
            continue
        seen.add(fingerprint)
        seen_signatures.add(scientific_signature)
        item.update({
            "query": query,
            "target_layer": layer,
            "target_lane": lane,
            "query_fingerprint": fingerprint,
            "scientific_query_signature": scientific_signature,
            "evidence_shape_role": query_role,
            "query_shape": _query_shape_diagnostics(
                positive,
                role=query_role,
                alignment_contract=alignment_contract,
            ),
            "replan_of_branch": replan_of_branch,
            "validation_status": "ACCEPTED",
        })
        accepted.append(item)
    failure_class = str(
        payload.get("failure_class") or "RELATED_FULLTEXT_COUNT_SHORTFALL"
    ).upper()
    if failure_class not in QUERY_OPTIMIZER_FAILURE_CLASSES:
        failure_class = "RELATED_FULLTEXT_COUNT_SHORTFALL"
    return {
        "schema_version": "constrained_query_optimizer_validation_v1",
        "failure_class": failure_class,
        "repair_template": str(payload.get("repair_template") or ""),
        "repair_status": str(payload.get("repair_status") or ""),
        "accepted_queries": accepted,
        "rejected_queries": rejected,
        "preserved_anchors": [str(item) for item in payload.get("preserved_anchors") or []],
        "proposed_synonyms": [dict(item) for item in payload.get("proposed_synonyms") or [] if isinstance(item, dict)],
        "negative_terms": [str(item) for item in payload.get("negative_terms") or []],
        "expected_improvement": str(payload.get("expected_improvement") or ""),
        "scientific_claim_authority": "QUERY_EXPANSION_ONLY_NOT_KNOWLEDGE_GRAPH_FACT",
        "metadata_grounded_calibration_refinement": metadata_grounded_calibration_refinement,
        "permitted_refinement_terms": sorted(permitted_refinement_tokens)[:96],
        "object_maturity_direct_core_allowed": direct_core_allowed_by_maturity,
        "object_maturity_anchor_terms": object_anchors[:16],
        "required_replan_branches": sorted(normalized_required_replan_branches),
    }


def query_plan_from_optimizer_validation(
    validation: dict[str, Any],
    *,
    alignment_contract: dict[str, Any],
    round_index: int,
) -> list[dict[str, Any]]:
    sub_id = _normalized_subhypothesis_id(alignment_contract.get("sub_hypothesis_id")) or "SH"
    direct_core_allowed_by_maturity = _direct_core_allowed_by_object_maturity(
        alignment_contract
    )
    object_maturity_audit = (
        alignment_contract.get("object_maturity_audit")
        if isinstance(alignment_contract.get("object_maturity_audit"), dict)
        else {}
    )
    object_maturity_status = str(
        alignment_contract.get("object_maturity_status")
        or object_maturity_audit.get("object_status")
        or ""
    )
    maturity_component_anchors = _object_maturity_anchor_terms(alignment_contract)
    kind_by_lane = {
        "THEORETICAL_FRAMEWORK": ("theoretical_framework", "background_or_framework"),
        "THEORETICAL_OR_FORMAL_EVIDENCE": ("theoretical_framework", "theoretical_or_formal_evidence"),
        "COMPUTATIONAL_MODEL_DISCRIMINATION": ("mechanism_discovery", "computational_model_discrimination"),
        "OBSERVATIONAL_COHORT_EVIDENCE": ("association", "observational_cohort_evidence"),
        "ECOLOGICAL_FIELD_OBSERVATION": ("association", "ecological_field_observation"),
        "ECOLOGICAL_MONITORING": ("association", "ecological_monitoring"),
        "ECOLOGICAL_LONGITUDINAL_MONITORING": ("association", "ecological_longitudinal_monitoring"),
        "SURVEILLANCE_SYSTEM_VALIDATION": ("predictive_validation", "surveillance_system_validation"),
        "MECHANISM_DISCOVERY": ("mechanism_discovery", "mechanism_discovery"),
        "CAUSAL_VALIDATION": ("causal_validation", "causal_validation"),
        "COMPONENT_EVIDENCE": ("mechanism_discovery", "component_evidence"),
        "TRANSLATIONAL_BRIDGE_EVIDENCE": ("association", "translational_bridge"),
        BOUNDARY_OR_NEGATIVE_EVIDENCE_LANE: ("causal_validation", "boundary_or_generalization"),
        ADVERSE_OR_REVERSAL_EVIDENCE_LANE: ("causal_validation", "adverse_or_reversal"),
        "PREDICTIVE_VALIDATION": ("predictive_validation", "predictive_validation"),
    }
    allowed_output_roles = {
        "background_or_framework",
        "mechanism_discovery",
        "causal_validation",
        "core_validation",
        "supporting_mechanism",
        "predictive_validation",
        "predictive_generalization",
        "adverse_or_reversal",
        "boundary_or_generalization",
        "context_review",
        "contract_lexical_calibration",
        "theoretical_or_formal_evidence",
        "computational_model_discrimination",
        "observational_cohort_evidence",
        "ecological_field_observation",
        "ecological_monitoring",
        "ecological_longitudinal_monitoring",
        "surveillance_system_validation",
        "component_evidence",
        "translational_bridge",
        "boundary_or_safety_evidence",
    }
    plan: list[dict[str, Any]] = []
    for index, item in enumerate(validation.get("accepted_queries") or []):
        if not isinstance(item, dict):
            continue
        lane = str(item.get("target_lane") or "MECHANISM_DISCOVERY").upper()
        evidence_kind, role = kind_by_lane.get(lane, ("mechanism_discovery", "mechanism_discovery"))
        requested_role = str(item.get("evidence_path_role") or "").strip().lower()
        if requested_role in allowed_output_roles:
            role = requested_role
        if lane == ADVERSE_OR_REVERSAL_EVIDENCE_LANE:
            role = "adverse_or_reversal"
        elif lane == BOUNDARY_OR_NEGATIVE_EVIDENCE_LANE and role not in {"boundary_or_generalization", "context_review"}:
            role = "boundary_or_generalization"
        target_layer = str(item.get("target_layer") or "L4_regular")
        shape_role = str(item.get("evidence_shape_role") or role or "").strip().lower()
        context_path = bool(shape_role == "context_review" or target_layer == "L0_review")
        object_maturity_support_only = not direct_core_allowed_by_maturity
        if object_maturity_support_only:
            role_text = " ".join(
                str(value or "")
                for value in (
                    requested_role,
                    role,
                    shape_role,
                    item.get("target_lane"),
                    item.get("rationale"),
                )
            ).lower()
            if context_path:
                role = "background_or_framework"
                lane = "THEORETICAL_FRAMEWORK"
                evidence_kind = "theoretical_framework"
            elif any(marker in role_text for marker in ("bridge", "translation", "translational")):
                role = "translational_bridge"
                lane = "TRANSLATIONAL_BRIDGE_EVIDENCE"
                evidence_kind = "association"
            elif any(
                marker in role_text
                for marker in (
                    "boundary",
                    "safety",
                    "adverse",
                    "reversal",
                    "failure",
                    "toxicity",
                    "instability",
                    "heterogeneity",
                )
            ):
                role = "boundary_or_safety_evidence"
                lane = BOUNDARY_OR_NEGATIVE_EVIDENCE_LANE
                evidence_kind = "causal_validation"
            else:
                role = "component_evidence"
                lane = "COMPONENT_EVIDENCE"
                evidence_kind = "mechanism_discovery"
            shape_role = role
        core_capable = bool(
            not object_maturity_support_only
            and
            not context_path
            and lane in {"CAUSAL_VALIDATION", "PREDICTIVE_VALIDATION", ADVERSE_OR_REVERSAL_EVIDENCE_LANE}
        )
        polarity = (
            "opposing"
            if lane == ADVERSE_OR_REVERSAL_EVIDENCE_LANE
            else "boundary"
            if shape_role in {"boundary", "boundary_or_safety_evidence", "translational_bridge"}
            or lane == BOUNDARY_OR_NEGATIVE_EVIDENCE_LANE
            else "context"
            if context_path
            else "supportive"
        )
        plan.append({
            "branch": f"{sub_id}:optimized_r{int(round_index)}_{index + 1}",
            "query": str(item.get("query") or ""),
            "l2_query": str(item.get("query") or ""),
            "purpose": str(item.get("rationale") or "failure-feedback query optimization"),
            "query_family": (
                f"object_maturity_optimizer_{role}"
                if object_maturity_support_only
                else f"optimized_{lane.lower()}"
            ),
            "evidence_kind": evidence_kind,
            "evidence_path_role": role,
            "evidence_path_polarity": polarity,
            "target_layer": target_layer,
            "target_lane": lane,
            "preferred_retrieval_layers": [target_layer],
            "retrieval_layer_role": shape_role or role,
            "core_evidence_capable": core_capable,
            "panel_core_path": core_capable,
            "component_evidence_counts_as_core": (
                False if object_maturity_support_only or context_path else None
            ),
            "component_evidence_counts_as_panel_core": (
                False if object_maturity_support_only or context_path else None
            ),
            "component_anchor_group": maturity_component_anchors[:18],
            "object_maturity_audit": object_maturity_audit,
            "object_maturity_status": object_maturity_status,
            "direct_core_evidence_allowed": direct_core_allowed_by_maturity,
            "direct_core_disallowed_by_object_maturity": object_maturity_support_only,
            "query_optimizer_round": int(round_index),
            "query_fingerprint": str(item.get("query_fingerprint") or ""),
            "scientific_query_signature": str(item.get("scientific_query_signature") or ""),
            "evidence_shape_role": shape_role,
            "lexical_calibration": bool(item.get("lexical_calibration")),
            "calibration_route": str(item.get("calibration_route") or ""),
            "calibration_contract_axes": list(item.get("calibration_contract_axes") or []),
            "replan_of_branch": str(item.get("replan_of_branch") or ""),
            "can_independently_falsify_sh": bool(
                lane == ADVERSE_OR_REVERSAL_EVIDENCE_LANE
                and not object_maturity_support_only
            ),
            "failure_scope": (
                "component_support_gap_not_direct_core_falsification"
                if object_maturity_support_only and role == "component_evidence"
                else "translation_bridge_gap"
                if object_maturity_support_only and role == "translational_bridge"
                else "boundary_safety_gap"
                if object_maturity_support_only
                and role == "boundary_or_safety_evidence"
                else "context_only_gap"
                if object_maturity_support_only
                else
                "whole_sh_core_falsification"
                if lane == ADVERSE_OR_REVERSAL_EVIDENCE_LANE
                else "supporting_gap_or_mechanism_weakening"
                if not core_capable
                else "whole_sh_core_validation"
            ),
            "negative_evidence_interpretation": (
                "Component/bridge/boundary evidence may expose feasibility limits, but cannot falsify or validate the final unanchored object as direct core."
                if object_maturity_support_only
                else
                "opposing adverse/reversal evidence can falsify or materially qualify the SH after full-text review"
                if lane == ADVERSE_OR_REVERSAL_EVIDENCE_LANE
                else ""
            ),
            "scientific_object_anchor": str(alignment_contract.get("scientific_object") or ""),
            "primary_field": str(alignment_contract.get("primary_field") or ""),
            "excluded_nearby_objects": list(alignment_contract.get("excluded_nearby_objects") or []),
        })
    return plan


_LABORATORY_CONSTRAINT_FAILURE_TRIGGERS = frozenset({
    "RELATED_FULLTEXT_COUNT_SHORTFALL",
    "HYPOTHESIS_EVIDENCE_BUNDLE_SHORTFALL",
    "COMPATIBLE_DIRECT_CORE_SHORTFALL",
    # Persisted diagnostics from pre-v7 projects remain understood.
    "CAUSAL_CHAIN_CORE_SHORTFALL",
})

_LABORATORY_CONSTRAINT_GENERIC_TERMS = (
    "stability",
    "storage",
    "temperature",
    "thermal",
    "cold chain",
    "shelf life",
    "freeze thaw",
    "freeze-thaw",
    "humidity",
    "pressure",
    "operating condition",
    "operating regime",
    "regime",
    "degradation",
    "durability",
    "retention",
)

_LABORATORY_CONSTRAINT_PHYSICAL_CONTEXT_TERMS = (
    "accelerated aging",
    "active pharmaceutical ingredient",
    "additive",
    "alloy",
    "anode",
    "antibody",
    "assay storage",
    "battery",
    "biologic",
    "biomaterial",
    "biospecimen",
    "catalyst",
    "cathode",
    "cell therapy",
    "coating",
    "cold chain",
    "compound",
    "device",
    "dosage",
    "drug product",
    "electrode",
    "electrolyte",
    "enzyme",
    "fabrication",
    "formulation",
    "freeze thaw",
    "freeze-thaw",
    "implant",
    "manufacturing",
    "material",
    "membrane",
    "nanoparticle",
    "physical sample",
    "polymer",
    "preservation",
    "protein",
    "reagent",
    "sample preparation",
    "semiconductor",
    "sensor",
    "shelf life",
    "solvent",
    "specimen",
    "storage temperature",
    "thermal analysis",
    "thermal cycling",
    "thermal stability",
    "vaccine",
    "viral vector",
)

_LABORATORY_CONSTRAINT_NONPHYSICAL_CONTEXT_TERMS = (
    "cognitive",
    "computer memory",
    "data storage",
    "digital memory",
    "episodic memory",
    "human memory",
    "information retrieval",
    "long term memory",
    "long-term memory",
    "memory consolidation",
    "memory recall",
    "memory storage",
    "neural representation",
    "retention rate",
    "recall accuracy",
    "social",
    "software",
    "working memory",
)

_LABORATORY_CONSTRAINT_MODES = frozenset({
    "LABORATORY_CONSTRAINT",
    "INSTRUMENTATION_OR_MEASUREMENT",
})


def _contract_text_for_laboratory_constraint(
    *,
    base_query: str,
    alignment_contract: dict[str, Any],
) -> str:
    core_axis_policy = (
        alignment_contract.get("core_axis_policy")
        if isinstance(alignment_contract.get("core_axis_policy"), dict)
        else {}
    )
    values: list[Any] = [
        base_query,
        alignment_contract.get("focus"),
        alignment_contract.get("declared_research_mode"),
        alignment_contract.get("evidence_mode"),
        alignment_contract.get("scientific_object"),
        alignment_contract.get("focal_variable"),
        alignment_contract.get("comparison"),
        alignment_contract.get("falsification_condition"),
        core_axis_policy.get("focal_variable_phrases"),
        core_axis_policy.get("mechanism_phrases"),
        core_axis_policy.get("outcome_phrases"),
        core_axis_policy.get("focal_variable_terms"),
        core_axis_policy.get("mechanism_terms"),
        core_axis_policy.get("outcome_terms"),
    ]
    causal_contract = alignment_contract.get("causal_contract")
    if isinstance(causal_contract, dict):
        values.extend(
            [
                causal_contract.get("constraint_type"),
                causal_contract.get("pivotal_mechanism"),
                causal_contract.get("supporting_mediators"),
                causal_contract.get("outcome"),
                causal_contract.get("boundary_conditions"),
            ]
        )
    evidence_standard = alignment_contract.get("evidence_standard")
    if isinstance(evidence_standard, dict):
        values.extend(
            [
                evidence_standard.get("id"),
                evidence_standard.get("accepted_core_designs"),
                evidence_standard.get("claim_strength_cap"),
            ]
        )
    return json.dumps(values, ensure_ascii=False, default=str).lower()


def _laboratory_constraint_mode_active(alignment_contract: dict[str, Any]) -> bool:
    declared_mode = str(alignment_contract.get("declared_research_mode") or "").upper()
    if declared_mode in _LABORATORY_CONSTRAINT_MODES:
        return True
    evidence_standard = alignment_contract.get("evidence_standard")
    if isinstance(evidence_standard, dict):
        accepted = {
            str(item or "").lower()
            for item in (evidence_standard.get("accepted_core_designs") or [])
        }
        if {
            "controlled_experiment",
            "laboratory_measurement",
            "mechanistic_assay",
        } & accepted:
            return True
    return False


def _laboratory_constraint_failure_active(failure_diagnostics: dict[str, Any]) -> bool:
    failures = {
        str(item or "").upper()
        for item in (failure_diagnostics.get("failure_classes") or [])
        if str(item or "").strip()
    }
    failure_class = str(failure_diagnostics.get("failure_class") or "").upper()
    if failure_class:
        failures.add(failure_class)
    return bool(failures & _LABORATORY_CONSTRAINT_FAILURE_TRIGGERS)


def _laboratory_constraint_terms_present(text: str) -> bool:
    lowered = str(text or "").lower()
    return any(term in lowered for term in _LABORATORY_CONSTRAINT_GENERIC_TERMS)


def _laboratory_constraint_physical_context_present(text: str) -> bool:
    lowered = str(text or "").lower()
    physical_hit = any(
        term in lowered for term in _LABORATORY_CONSTRAINT_PHYSICAL_CONTEXT_TERMS
    )
    if not physical_hit:
        return False
    nonphysical_hits = [
        term
        for term in _LABORATORY_CONSTRAINT_NONPHYSICAL_CONTEXT_TERMS
        if term in lowered
    ]
    # A genuine materials/chemistry/biologic/device contract may also mention
    # retention or stability.  But if the only apparent context is human/digital
    # memory, data storage, cognition, software, or social retention, the
    # thermal/cold-chain template is a false friend and must stay off.
    if nonphysical_hits and not any(
        term in lowered
        for term in (
            "material",
            "formulation",
            "sample",
            "specimen",
            "device",
            "battery",
            "catalyst",
            "polymer",
            "protein",
            "vaccine",
            "drug product",
        )
    ):
        return False
    return True


def _best_axis_phrase(alignment_contract: dict[str, Any]) -> str:
    core_axis_policy = (
        alignment_contract.get("core_axis_policy")
        if isinstance(alignment_contract.get("core_axis_policy"), dict)
        else {}
    )
    readout_terms = {
        "activity",
        "capacity",
        "conductivity",
        "conversion",
        "degradation",
        "durability",
        "efficiency",
        "immunization",
        "infectivity",
        "potency",
        "retention",
        "selectivity",
        "stability",
        "titer",
        "titre",
        "yield",
    }
    candidates: list[tuple[int, str]] = []

    def append_axis_candidate(source_priority: int, value: Any) -> None:
        phrase = re.sub(r"\s+", " ", str(value or "").strip().lower())
        if len(phrase) < 4 or phrase in _GENERIC_RETRIEVAL_TERMS:
            return
        if len(phrase) >= 5:
            candidates.append((source_priority, phrase))
        tokens = re.findall(r"[a-z0-9_-]+", phrase)
        if len(tokens) <= 2:
            return
        for index, token in enumerate(tokens):
            if token not in readout_terms:
                continue
            if index > 0:
                window = f"{tokens[index - 1]} {token}"
                if len(window) >= 5:
                    candidates.append((source_priority + 1, window))
            if index + 1 < len(tokens):
                window = f"{token} {tokens[index + 1]}"
                if len(window) >= 5:
                    candidates.append((source_priority + 1, window))

    explicit_sources = (
        (3, core_axis_policy.get("mechanism_phrases") or []),
        (3, core_axis_policy.get("outcome_phrases") or []),
        (2, core_axis_policy.get("focal_variable_phrases") or []),
    )
    for source_priority, values in explicit_sources:
        if not isinstance(values, list):
            values = [values]
        for value in values:
            append_axis_candidate(source_priority, value)
    term_sources = (
        (1, core_axis_policy.get("mechanism_terms") or []),
        (1, core_axis_policy.get("outcome_terms") or []),
        (0, core_axis_policy.get("focal_variable_terms") or []),
    )
    for source_priority, values in term_sources:
        for value in values:
            term = re.sub(r"\s+", " ", str(value or "").strip().lower())
            if len(term) >= 4 and term not in _GENERIC_RETRIEVAL_TERMS:
                candidates.append((source_priority, term))
    if not candidates:
        return ""

    def score(item: tuple[int, str]) -> tuple[int, int, int, int, str]:
        source_priority, candidate = item
        tokens = re.findall(r"[a-z0-9_-]+", candidate)
        readout_hit = int(any(token in readout_terms for token in tokens))
        generic_hits = sum(1 for token in tokens if token in _GENERIC_RETRIEVAL_TERMS)
        return (
            readout_hit,
            source_priority,
            -generic_hits,
            -abs(len(tokens) - 2),
            candidate,
        )

    return max(candidates, key=score)[1]


def _laboratory_readout_profile(text: str) -> list[str]:
    lowered = str(text or "").lower()
    profiles: list[str] = []
    if any(term in lowered for term in ("vaccine", "viral vector", "adenoviral", "antibody", "protein", "enzyme", "cell therapy", "biologic")):
        profiles.extend(
            [
                "potency assay OR activity retention OR functional readout",
                "infectivity OR viral titer OR immunogenicity retention",
            ]
        )
    if any(term in lowered for term in ("battery", "electrolyte", "electrode", "catalyst", "membrane", "polymer", "material", "semiconductor", "coating")):
        profiles.extend(
            [
                "retention OR degradation kinetics OR failure mode",
                "thermal analysis OR cycling stability OR accelerated aging",
            ]
        )
    if any(term in lowered for term in ("reaction", "catalysis", "chemical", "compound", "formulation", "solvent")):
        profiles.extend(
            [
                "conversion OR selectivity OR activity retention",
                "stress testing OR degradation kinetics OR formulation stability",
            ]
        )
    profiles.extend(
        [
            "assay OR characterization OR quantitative measurement",
            "controlled experiment OR laboratory measurement OR stress test",
        ]
    )
    output: list[str] = []
    seen: set[str] = set()
    for profile in profiles:
        key = profile.lower()
        if key not in seen:
            seen.add(key)
            output.append(profile)
    return output


def laboratory_constraint_query_repair_payload(
    *,
    base_query: str,
    alignment_contract: dict[str, Any],
    failure_diagnostics: dict[str, Any],
) -> dict[str, Any] | None:
    """Return a bounded LABORATORY_CONSTRAINT query repair payload.

    This is a retrieval-only repair.  It does not relax the SH gate, does not
    mutate the scientific contract, and still must pass
    ``validate_query_optimizer_payload`` before execution.  The purpose is to
    replace vague operating-condition words (``storage requirements``,
    ``temperature stability``) with experiment-shaped terms: a preserved object
    anchor, a declared scientific axis, a condition perturbation, and a
    measurable laboratory readout.
    """

    if not _direct_core_allowed_by_object_maturity(alignment_contract):
        return None
    if not _laboratory_constraint_mode_active(alignment_contract):
        return None
    if not _laboratory_constraint_failure_active(failure_diagnostics):
        return None
    contract_text = _contract_text_for_laboratory_constraint(
        base_query=base_query,
        alignment_contract=alignment_contract,
    )
    if not _laboratory_constraint_terms_present(contract_text):
        return None
    if not _laboratory_constraint_physical_context_present(contract_text):
        return None
    anchors = _optimizer_object_anchor_terms(alignment_contract)
    object_anchor = next(
        (item for item in anchors if " " in item),
        anchors[0] if anchors else "",
    )
    object_anchor = re.sub(r"\s+", " ", object_anchor.strip().lower())
    axis = _best_axis_phrase(alignment_contract)
    if not object_anchor or not axis:
        return None

    readouts = _laboratory_readout_profile(contract_text)
    condition_panels = [
        "thermal stability OR accelerated stability OR temperature excursion",
        "storage temperature OR shelf life OR cold chain OR freeze thaw",
        "formulation stability OR degradation kinetics OR stress testing",
        "controlled storage condition OR boundary condition OR operating regime",
    ]
    target_layers = ["L4_regular", "L2_top_latest"]

    query_specs: list[tuple[str, str, str]] = []
    for index, condition_panel in enumerate(condition_panels):
        layer = target_layers[min(index, len(target_layers) - 1)]
        lane = "CAUSAL_VALIDATION" if index % 2 else "MECHANISM_DISCOVERY"
        readout = readouts[index % len(readouts)]
        query = f'("{object_anchor}") AND ("{axis}") AND ({condition_panel}) AND ({readout})'
        query_specs.append((layer, lane, query))

    queries = [
        {
            "target_layer": layer,
            "target_lane": lane,
            "query": query,
            "rationale": (
                "LABORATORY_CONSTRAINT repair: preserve the declared object and "
                "scientific axis while replacing generic condition wording with "
                "controlled-condition and quantitative-readout terminology."
            ),
        }
        for layer, lane, query in query_specs
    ]
    return {
        "failure_class": str(
            failure_diagnostics.get("failure_class")
            or "RELATED_FULLTEXT_COUNT_SHORTFALL"
        ),
        "preserved_anchors": [object_anchor, axis],
        "proposed_synonyms": [],
        "queries": queries,
        "negative_terms": [],
        "expected_improvement": (
            "Recover standard-core laboratory evidence for operating-condition "
            "constraints without treating review-level requirements as direct "
            "experimental support."
        ),
        "repair_template": "laboratory_constraint_v1",
    }


def _sanitize_non_context_query_axis(value: Any) -> str:
    """Remove review/framework bait when reusing a path's own retrieval text."""

    sanitized = str(value or "")
    for marker in sorted(_CONTEXT_ONLY_QUERY_MARKERS, key=len, reverse=True):
        sanitized = re.sub(
            rf"\b{re.escape(marker)}\b",
            " ",
            sanitized,
            flags=re.IGNORECASE,
        )
    sanitized = re.sub(r"\b(?:AND|OR)\s*(?:AND|OR)\b", " ", sanitized, flags=re.IGNORECASE)
    sanitized = re.sub(r"\s+", " ", sanitized).strip(" ;,")
    return sanitized


def _query_clause(values: list[str], *, fallback: str, limit: int = 5) -> str:
    selected: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = re.sub(r"\s+", " ", str(value or "").strip())
        if not normalized:
            continue
        key = normalized.lower()
        if key in seen:
            continue
        seen.add(key)
        selected.append(normalized)
        if len(selected) >= max(1, int(limit)):
            break
    return " OR ".join(selected) if selected else fallback


def _endpoint_query_clause(alignment_contract: dict[str, Any]) -> str:
    discipline_endpoints = _discipline_profile_terms(
        alignment_contract,
        "endpoint",
        limit=4,
    )
    return _query_clause(
        _contract_endpoint_anchors(alignment_contract) + discipline_endpoints,
        fallback="measurable endpoint OR functional readout OR quantitative measurement",
        limit=4,
    )


def _design_query_clause(alignment_contract: dict[str, Any], *, fallback: str) -> str:
    return _query_clause(
        _discipline_profile_terms(alignment_contract, "design", limit=4),
        fallback=fallback,
        limit=4,
    )


def _intervention_query_clause(alignment_contract: dict[str, Any], *, fallback: str) -> str:
    return _query_clause(
        _discipline_profile_terms(alignment_contract, "intervention", limit=4),
        fallback=fallback,
        limit=4,
    )


def _adverse_query_clause(alignment_contract: dict[str, Any], *, fallback: str) -> str:
    return _query_clause(
        _discipline_adverse_profile_terms(alignment_contract, limit=4)
        + list(_ADVERSE_OR_REVERSAL_QUERY_ANCHORS),
        fallback=fallback,
        limit=6,
    )


def _path_axis_query(path: dict[str, Any], *, fallback_axis: str) -> str:
    pieces: list[str] = []
    for key in ("retrieval_query", "query", "focus"):
        value = str(path.get(key) or "").strip()
        if value:
            pieces.append(value)
    steps = path.get("causal_steps")
    if isinstance(steps, (list, tuple)):
        pieces.extend(str(item) for item in steps if str(item or "").strip())
    source = " ".join(pieces)
    source = _sanitize_non_context_query_axis(source)
    if not source:
        return fallback_axis
    tokens = re.findall(r"[a-z0-9+_-]+", source.lower())
    if len(tokens) > 18:
        source = " ".join(tokens[:18])
    return source or fallback_axis


def _role_shaped_query(
    *,
    object_anchor: str,
    axis: str,
    endpoint_clause: str,
    layer: str,
    lane: str,
    predictive_mode: bool,
    design_clause: str = "",
    intervention_clause: str = "",
    adverse_clause: str = "",
) -> str:
    axis_clause = axis or endpoint_clause
    validation_design_clause = (
        design_clause
        or "external validation OR validation cohort OR calibration OR baseline comparison OR benchmark"
    )
    mechanism_design_clause = (
        design_clause
        or "assay OR in vivo OR in vitro OR controlled experiment OR perturbation"
    )
    causal_design_clause = (
        design_clause
        or "controlled study OR randomized trial OR perturbation OR dose response OR treatment"
    )
    perturbation_clause = intervention_clause or "perturbation OR controlled condition OR treatment"
    adverse_or_reversal_clause = adverse_clause or (
        "negative effect OR adverse effect OR rebound effect OR substitution effect OR "
        "burden shifting OR trade-off OR resource competition OR failure mode OR null effect"
    )
    if lane in {
        "OBSERVATIONAL_COHORT_EVIDENCE", "ECOLOGICAL_FIELD_OBSERVATION",
        "ECOLOGICAL_MONITORING", "ECOLOGICAL_LONGITUDINAL_MONITORING",
    }:
        return f'("{object_anchor}") AND ({axis_clause})'
    if lane in {"THEORETICAL_OR_FORMAL_EVIDENCE", "COMPUTATIONAL_MODEL_DISCRIMINATION"}:
        return f'("{object_anchor}") AND ({axis_clause})'
    if lane == "SURVEILLANCE_SYSTEM_VALIDATION":
        return f'("{object_anchor}") AND ({axis_clause}) AND (calibration OR validation OR benchmark OR robustness)'
    if layer == "L0_review" or lane == "THEORETICAL_FRAMEWORK":
        return f'("{object_anchor}") AND ({axis_clause}) AND (review OR systematic review OR field map OR terminology)'
    if predictive_mode or lane == "PREDICTIVE_VALIDATION":
        return (
            f'("{object_anchor}") AND ({axis_clause}) AND '
            f"({validation_design_clause} OR external validation OR baseline comparison OR benchmark) AND "
            f"({endpoint_clause} OR performance OR prediction accuracy)"
        )
    if lane == "MECHANISM_DISCOVERY":
        return (
            f'("{object_anchor}") AND ({axis_clause}) AND '
            f"({mechanism_design_clause} OR assay OR controlled experiment OR {perturbation_clause}) AND "
            f"({endpoint_clause} OR functional readout OR measurable endpoint)"
        )
    if lane == ADVERSE_OR_REVERSAL_EVIDENCE_LANE:
        return (
            f'("{object_anchor}") AND ({axis_clause}) AND '
            f"({adverse_or_reversal_clause}) AND "
            f"({endpoint_clause} OR baseline OR control group OR compared with OR reduced effectiveness OR worse outcome)"
        )
    if lane == BOUNDARY_OR_NEGATIVE_EVIDENCE_LANE:
        return (
            f'("{object_anchor}") AND ({axis_clause}) AND '
            "(external validation OR subgroup comparison OR boundary condition OR counterfactual) AND "
            f"({endpoint_clause} OR control group OR baseline)"
        )
    return (
        f'("{object_anchor}") AND ({axis_clause}) AND '
        f"({causal_design_clause} OR {perturbation_clause} OR controlled study OR dose response) AND "
        f"(control group OR compared with OR {endpoint_clause})"
    )


def _evidence_path_deficit_queries(
    *,
    alignment_contract: dict[str, Any],
    object_anchor: str,
    fallback_axis: str,
    endpoint_clause: str,
    deficits: dict[str, Any],
    direct_shortfall: int,
    total_shortfall: int,
) -> list[dict[str, Any]]:
    paths = [
        path for path in (alignment_contract.get("evidence_paths") or [])
        if isinstance(path, dict)
    ]
    if not paths:
        return []
    predictive_mode = str(alignment_contract.get("evidence_mode") or "") == "predictive_generalization"
    target_pressure = {
        layer for layer in NON_PREPRINT_LAYERS
        if int(deficits.get(layer) or 0) > 0
    }
    if not target_pressure and direct_shortfall > 0:
        target_pressure = {"L2_top_latest", "L4_regular"}
    if not target_pressure and total_shortfall > 0:
        target_pressure = {"L2_top_latest", "L4_regular"}
    design_clause = _design_query_clause(
        alignment_contract,
        fallback="assay OR controlled experiment OR validation study OR benchmark",
    )
    intervention_clause = _intervention_query_clause(
        alignment_contract,
        fallback="perturbation OR controlled condition OR treatment",
    )
    adverse_clause = _adverse_query_clause(
        alignment_contract,
        fallback="negative effect OR adverse effect OR rebound effect OR burden shifting OR failure mode",
    )
    try:
        from ._evidence_roles import EVIDENCE_ROLE_REGISTRY, evidence_role_retrieval_metadata
    except ImportError:
        from _evidence_roles import EVIDENCE_ROLE_REGISTRY, evidence_role_retrieval_metadata

    specs: list[dict[str, Any]] = []
    for index, path in enumerate(paths, start=1):
        role = str(path.get("role") or path.get("id") or "").strip().lower()
        role_text = role.replace("-", "_")
        axis = _path_axis_query(path, fallback_axis=fallback_axis)
        role_retrieval = evidence_role_retrieval_metadata(
            role,
            str((alignment_contract.get("epistemic_profile") or {}).get("primary_mode") or ""),
        ) if role in EVIDENCE_ROLE_REGISTRY else {}
        role_lane = str(role_retrieval.get("target_lane") or "")
        if role_lane == "OBSERVATIONAL_COHORT_EVIDENCE":
            layer_lanes = [("L2_top_latest", role_lane), ("L4_regular", role_lane)]
        elif role_lane == "THEORETICAL_OR_FORMAL_EVIDENCE":
            layer_lanes = [("L2_top_latest", role_lane), ("L4_regular", role_lane)]
        elif role_lane == "COMPUTATIONAL_MODEL_DISCRIMINATION":
            layer_lanes = [("L2_top_latest", role_lane), ("L4_regular", role_lane)]
        elif role_lane == "SURVEILLANCE_SYSTEM_VALIDATION":
            layer_lanes = [("L2_top_latest", role_lane), ("L4_regular", role_lane)]
        elif role_lane == "SYSTEMATIC_REVIEW_CONTEXT":
            layer_lanes = [("L0_review", "THEORETICAL_FRAMEWORK")]
        elif any(marker in role_text for marker in ("context", "background", "review", "framework")):
            layer_lanes = [("L0_review", "THEORETICAL_FRAMEWORK")]
        elif any(marker in role_text for marker in ("external", "generalization", "predictive", "validation_boundary")):
            layer_lanes = [
                ("L2_top_latest", "PREDICTIVE_VALIDATION"),
                ("L4_regular", "PREDICTIVE_VALIDATION"),
            ]
        elif "core" in role_text or "incremental" in role_text or "integrative" in role_text:
            lane = "PREDICTIVE_VALIDATION" if predictive_mode else "CAUSAL_VALIDATION"
            layer_lanes = [("L2_top_latest", lane), ("L4_regular", lane)]
        elif any(marker in role_text for marker in ("adverse", "reversal", "opposing", "tradeoff", "trade_off", "rebound", "burden")):
            layer_lanes = [
                ("L2_top_latest", ADVERSE_OR_REVERSAL_EVIDENCE_LANE),
                ("L4_regular", ADVERSE_OR_REVERSAL_EVIDENCE_LANE),
            ]
        elif any(marker in role_text for marker in ("boundary", "negative")):
            layer_lanes = [("L4_regular", BOUNDARY_OR_NEGATIVE_EVIDENCE_LANE)]
        else:
            layer_lanes = [("L4_regular", "MECHANISM_DISCOVERY")]
        for layer, lane in layer_lanes:
            if target_pressure and layer not in target_pressure and layer != "L0_review":
                continue
            if layer == "L0_review" and target_pressure and layer not in target_pressure:
                continue
            specs.append({
                "target_layer": layer,
                "target_lane": lane,
                "query": _role_shaped_query(
                    object_anchor=object_anchor,
                    axis=axis,
                    endpoint_clause=endpoint_clause,
                    layer=layer,
                    lane=lane,
                    predictive_mode=predictive_mode,
                    design_clause=design_clause,
                    intervention_clause=intervention_clause,
                    adverse_clause=adverse_clause,
                ),
                "evidence_path_role": role or f"path_{index}",
                "evidence_path_polarity": (
                    "opposing"
                    if lane == ADVERSE_OR_REVERSAL_EVIDENCE_LANE
                    else "boundary"
                    if lane == BOUNDARY_OR_NEGATIVE_EVIDENCE_LANE
                    else "supportive"
                ),
                "rationale": (
                    "Evidence-path diversification: switch retrieval to a distinct path and bind it to "
                    "study design, validation, measurable endpoint, or comparison anchors."
                ),
            })
    return specs


def _type_directed_bundle_missing_slot_queries(
    *,
    alignment_contract: dict[str, Any],
    failure_diagnostics: dict[str, Any],
    object_anchor: str,
    endpoint_clause: str,
) -> list[dict[str, Any]]:
    """Target unsupported V3 contract slots without inventing a causal path."""

    deficit = (
        failure_diagnostics.get("coverage_deficit")
        if isinstance(failure_diagnostics.get("coverage_deficit"), dict)
        else {}
    )
    bundle = (
        deficit.get("type_directed_evidence_bundle")
        if isinstance(deficit.get("type_directed_evidence_bundle"), dict)
        else {}
    )
    if not bundle or str(bundle.get("status") or "") in {
        "", "NOT_CONFIGURED", "CONTRACT_EVIDENCE_SLOTS_UNDECLARED", "CORE_CONTRACT_EVIDENCE_BUNDLE",
    }:
        return []
    profile = evidence_profile_for_contract(alignment_contract)
    missing_slots = [
        str(value).strip()
        for value in (bundle.get("missing_required_slot_ids") or [])
        if str(value).strip()
    ]
    if not missing_slots:
        missing_slots = [
            str(value).strip()
            for value in (profile.get("required_slots") or [])
            if str(value).strip()
        ]
    if not missing_slots:
        return []
    design_clause = _design_query_clause(
        alignment_contract,
        fallback="validation study OR direct observation OR controlled study OR benchmark",
    )
    gap_types = list(profile.get("gap_types") or [])
    lane = (
        "MECHANISM_DISCOVERY"
        if profile.get("causal_requirement_active") is True
        else "TYPE_DIRECTED_SLOT_EVIDENCE"
    )
    queries: list[dict[str, Any]] = []
    for slot_id in missing_slots[:3]:
        slot_phrase = slot_id.replace("_", " ")
        queries.append({
            "target_layer": "L4_regular",
            "target_lane": lane,
            "query": f'("{object_anchor}") AND ("{slot_phrase}") AND ({design_clause})',
            "evidence_path_role": "contract_slot_recovery",
            "target_evidence_slot_id": slot_id,
            "gap_types": gap_types,
            "evidence_path_polarity": "supportive",
            "rationale": (
                "Type-directed bundle recovery: retrieve source-bound support for one "
                "missing research-question evidence slot without imposing undeclared axes."
            ),
        })
    return queries


def deterministic_deficit_query_payload(
    *,
    base_query: str,
    alignment_contract: dict[str, Any],
    failure_diagnostics: dict[str, Any],
) -> dict[str, Any]:
    """Bounded fallback when the external optimizer is disabled/unavailable."""

    anchors = _optimizer_object_anchor_terms(alignment_contract)
    object_anchor = next(
        (item for item in anchors if " " in item),
        anchors[0] if anchors else "",
    )
    if not object_anchor:
        return {
            "failure_class": str(
                failure_diagnostics.get("failure_class")
                or "RELATED_FULLTEXT_COUNT_SHORTFALL"
            ),
            "repair_template": "deterministic_deficit_query_v2",
            "repair_status": "CONTRACT_UNDERSPECIFIED_FOR_DETERMINISTIC_DEFICIT_QUERY",
            "queries": [],
            "preserved_anchors": [],
            "proposed_synonyms": [],
            "negative_terms": [],
            "expected_improvement": (
                "No deterministic deficit query is emitted because the active "
                "contract lacks a canonical scientific-object anchor."
            ),
            "scientific_claim_authority": "NO_QUERY_EXPANSION_WITHOUT_DECLARED_ANCHORS",
        }
    # A persisted contract-slot deficit is more specific than a broad axis
    # shortfall.  Resolve it before any generic query expansion.
    bundle_slot_queries = _type_directed_bundle_missing_slot_queries(
        alignment_contract=alignment_contract,
        failure_diagnostics=failure_diagnostics,
        object_anchor=object_anchor,
        endpoint_clause="",
    )
    if bundle_slot_queries:
        return {
            "failure_class": str(
                failure_diagnostics.get("failure_class")
                or "TYPE_DIRECTED_EVIDENCE_BUNDLE_SHORTFALL"
            ),
            "repair_template": "type_directed_contract_slot_recovery_v1",
            "preserved_anchors": [object_anchor],
            "proposed_synonyms": [],
            "queries": bundle_slot_queries,
            "negative_terms": [],
            "expected_improvement": (
                "Fill only the explicitly missing source-bound contract slot; do not rerun an all-purpose quota query."
            ),
        }
    lexical_calibration_payload = contract_lexical_alignment_repair_payload(
        alignment_contract=alignment_contract,
        failure_diagnostics=failure_diagnostics,
    )
    if lexical_calibration_payload is not None:
        return lexical_calibration_payload

    laboratory_payload = laboratory_constraint_query_repair_payload(
        base_query=base_query,
        alignment_contract=alignment_contract,
        failure_diagnostics=failure_diagnostics,
    )
    if laboratory_payload:
        return laboratory_payload
    # Evidence paths are one explicitly declared representation of a
    # scientific contract.  Evaluate them before generic slot wording so a
    # contract can use its own measurement, boundary, theory, or data axes.
    coverage_deficit = failure_diagnostics.get("coverage_deficit") or {}
    path_deficits = (
        coverage_deficit.get("layers")
        if isinstance(coverage_deficit, dict)
        and isinstance(coverage_deficit.get("layers"), dict)
        else {}
    )
    path_total_shortfall = int(
        coverage_deficit.get("imported_related_fulltext_shortfall") or 0
    ) if isinstance(coverage_deficit, dict) else 0
    path_direct_shortfall_value = (
        coverage_deficit.get("type_directed_bundle_shortfall")
        if isinstance(coverage_deficit, dict)
        and coverage_deficit.get("type_directed_bundle_shortfall") is not None
        else coverage_deficit.get("direct_contract_core_shortfall")
        if isinstance(coverage_deficit, dict)
        else 0
    )
    path_direct_shortfall = int(path_direct_shortfall_value or 0)
    declared_path_queries = _evidence_path_deficit_queries(
        alignment_contract=alignment_contract,
        object_anchor=object_anchor,
        fallback_axis=base_query,
        endpoint_clause=_endpoint_query_clause(alignment_contract),
        deficits=path_deficits,
        direct_shortfall=path_direct_shortfall,
        total_shortfall=path_total_shortfall,
    )
    if declared_path_queries:
        return {
            "failure_class": str(
                failure_diagnostics.get("failure_class")
                or "RELATED_FULLTEXT_COUNT_SHORTFALL"
            ),
            "preserved_anchors": [object_anchor],
            "proposed_synonyms": [],
            "queries": declared_path_queries[:3],
            "negative_terms": [],
            "expected_improvement": (
                "Recover evidence through the declared evidence paths without imposing undeclared causal axes."
            ),
        }
    profile = evidence_profile_for_contract(alignment_contract)
    slot_terms = list(dict.fromkeys(
        str(value).replace("_", " ").strip()
        for value in (profile.get("required_slots") or [])
        if str(value).strip()
    ))
    if not slot_terms:
        return {
            "failure_class": str(
                failure_diagnostics.get("failure_class")
                or "RELATED_FULLTEXT_COUNT_SHORTFALL"
            ),
            "repair_template": "deterministic_deficit_query_v2",
            "repair_status": "CONTRACT_EVIDENCE_SLOTS_MISSING_FOR_DETERMINISTIC_DEFICIT_QUERY",
            "queries": [],
            "preserved_anchors": [object_anchor],
            "proposed_synonyms": [],
            "negative_terms": [],
            "expected_improvement": (
                "No deterministic deficit query is emitted because the active "
                "contract lacks declared research-question evidence slots."
            ),
            "scientific_claim_authority": "NO_QUERY_EXPANSION_WITHOUT_DECLARED_AXES",
        }
    # The active contract supplies the scientific retrieval axis.  Do not
    # compensate for an underspecified contract with generic role labels.
    axis = " OR ".join(slot_terms[:4])

    def axis_variant(index: int) -> str:
        # Different missing layers receive different declared scientific
        # sub-axes.  This produces actual retrieval diversity without using
        # an evidence-role phrase as fake novelty.
        if len(slot_terms) > 1:
            return " OR ".join(slot_terms[index:index + 3] or slot_terms[-1:])
        return axis
    coverage_deficit = failure_diagnostics.get("coverage_deficit") or {}
    # Layer and standard-design deficits are quality diagnostics only. Query
    # planning responds exclusively to the two blocking corpus invariants.
    deficits: dict[str, int] = {}
    preferred_deficits: dict[str, int] = {}
    total_shortfall = int(
        coverage_deficit.get("imported_related_fulltext_shortfall") or 0
    )
    direct_shortfall = int(
        coverage_deficit.get("type_directed_bundle_shortfall")
        if coverage_deficit.get("type_directed_bundle_shortfall") is not None
        else coverage_deficit.get("direct_contract_core_shortfall")
        or 0
    )
    endpoint_clause = _endpoint_query_clause(alignment_contract)
    design_clause = _design_query_clause(
        alignment_contract,
        fallback="controlled study OR assay OR validation study OR benchmark",
    )
    intervention_clause = _intervention_query_clause(
        alignment_contract,
        fallback="perturbation OR controlled condition OR treatment",
    )
    adverse_clause = _adverse_query_clause(
        alignment_contract,
        fallback="negative effect OR adverse effect OR rebound effect OR burden shifting OR failure mode",
    )
    path_queries = _evidence_path_deficit_queries(
        alignment_contract=alignment_contract,
        object_anchor=object_anchor,
        fallback_axis=axis,
        endpoint_clause=endpoint_clause,
        deficits=deficits if isinstance(deficits, dict) else {},
        direct_shortfall=direct_shortfall,
        total_shortfall=total_shortfall,
    )
    if path_queries:
        return {
            "failure_class": str(
                failure_diagnostics.get("failure_class")
                or "RELATED_FULLTEXT_COUNT_SHORTFALL"
            ),
            "preserved_anchors": [object_anchor],
            "proposed_synonyms": [],
            "queries": path_queries[:3],
            "negative_terms": [],
            "expected_improvement": (
                "Reduce duplicate overlap by switching evidence path, declared slot, endpoint, or validation design "
                "instead of emitting synonym-only variants."
            ),
        }
    if str(alignment_contract.get("evidence_mode") or "") == "predictive_generalization":
        moderators = [
            str(item).strip()
            for item in alignment_contract.get("moderator_terms") or []
            if str(item).strip()
        ]
        boundary = " OR ".join(moderators[:5]) or "external cohort OR clinical setting"
        predictive_specs = [
            ("L0_review", "THEORETICAL_FRAMEWORK"),
            ("L2_top_latest", "PREDICTIVE_VALIDATION"),
            ("L4_regular", "PREDICTIVE_VALIDATION"),
        ]
        blocking = {
            layer for layer, _lane in predictive_specs
            if int(deficits.get(layer) or 0) > 0
        }
        targets = blocking or (
            {"L2_top_latest", "L4_regular"}
            if direct_shortfall > 0
            else {"L0_review", "L2_top_latest", "L4_regular"}
        )
        queries = [
            {
                "target_layer": layer,
                "target_lane": lane,
                "query": _role_shaped_query(
                    object_anchor=object_anchor,
                    axis=f"({boundary}) AND ({axis_variant(index)})",
                    endpoint_clause=endpoint_clause,
                    layer=layer,
                    lane=lane,
                    predictive_mode=True,
                    design_clause=design_clause,
                    intervention_clause=intervention_clause,
                    adverse_clause=adverse_clause,
                ),
                "rationale": "Predictive-generalization deficit query preserving the declared object while requiring external validation, calibration, performance, or baseline-comparison anchors.",
            }
            for index, (layer, lane) in enumerate(predictive_specs)
            if layer in targets
        ]
        return {
            "failure_class": str(
                failure_diagnostics.get("failure_class")
                or "RELATED_FULLTEXT_COUNT_SHORTFALL"
            ),
            "preserved_anchors": [object_anchor, *moderators[:3]],
            "proposed_synonyms": [],
            "queries": queries[:3],
            "negative_terms": [],
            "expected_improvement": "Recover external, subgroup, calibration, fairness, and transportability validation evidence without intervention constraints.",
        }
    layer_specs = [
        ("L0_review", "THEORETICAL_FRAMEWORK"),
        ("L2_top_latest", "MECHANISM_DISCOVERY"),
        ("L4_regular", "CAUSAL_VALIDATION"),
    ]
    blocking_targets = {
        layer for layer, _lane in layer_specs
        if int(deficits.get(layer) or 0) > 0
    }
    if blocking_targets:
        target_layers = blocking_targets
    elif direct_shortfall > 0:
        target_layers = {"L2_top_latest", "L4_regular"}
    elif total_shortfall > 0:
        target_layers = {
            layer for layer in ("L2_top_latest", "L4_regular")
            if int(preferred_deficits.get(layer) or 0) > 0
        } or {"L2_top_latest", "L4_regular"}
    else:
        target_layers = {"L2_top_latest", "L4_regular"}
    queries = []
    for index, (layer, lane) in enumerate(layer_specs):
        if layer not in target_layers:
            continue
        queries.append({
            "target_layer": layer,
            "target_lane": lane,
            "query": _role_shaped_query(
                object_anchor=object_anchor,
                axis=axis_variant(index),
                endpoint_clause=endpoint_clause,
                layer=layer,
                lane=lane,
                predictive_mode=False,
                design_clause=design_clause,
                intervention_clause=intervention_clause,
                adverse_clause=adverse_clause,
            ),
            "rationale": "Deterministic deficit-targeted fallback: preserve object/axis, then force design, perturbation, measurable endpoint, or comparison anchors instead of topic-only recall.",
        })
    return {
        "failure_class": str(
            failure_diagnostics.get("failure_class")
            or "RELATED_FULLTEXT_COUNT_SHORTFALL"
        ),
        "preserved_anchors": [object_anchor],
        "proposed_synonyms": [],
        "queries": queries[:3],
        "negative_terms": [],
        "expected_improvement": "Target the missing peer-reviewed layer without relaxing the alignment gate.",
    }


def stable_retrieval_audit_hash(payload: dict[str, Any]) -> str:
    material = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return sha256(material.encode("utf-8")).hexdigest()[:24]
