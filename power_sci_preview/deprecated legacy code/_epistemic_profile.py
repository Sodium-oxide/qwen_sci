"""Domain-neutral epistemic profiles for sub-hypothesis decomposition.

The profile answers *how a claim can be known* before retrieval asks for a
particular experimental design.  It deliberately models research paradigms
and claim types separately: a parameter constraint, a proof, and an
intervention effect should never inherit the same evidence requirements.
"""
from __future__ import annotations

import re
from typing import Any


EPISTEMIC_PROFILE_SCHEMA_VERSION = "epistemic_profile_v1"

EXPERIMENTAL_INTERVENTION = "experimental_intervention"
OBSERVATIONAL_INFERENCE = "observational_inference"
THEORETICAL_DERIVATION = "theoretical_derivation"
MATHEMATICAL_PROOF = "mathematical_proof"
COMPUTATIONAL_SIMULATION = "computational_simulation"
ENGINEERING_VALIDATION = "engineering_validation"
CLASSIFICATION_DESCRIPTION = "classification_description"
SYNTHESIS_EVALUATION = "synthesis_evaluation"
UNRESOLVED_EPISTEMIC_MODE = "unresolved"

EPISTEMIC_MODES = frozenset({
    EXPERIMENTAL_INTERVENTION,
    OBSERVATIONAL_INFERENCE,
    THEORETICAL_DERIVATION,
    MATHEMATICAL_PROOF,
    COMPUTATIONAL_SIMULATION,
    ENGINEERING_VALIDATION,
    CLASSIFICATION_DESCRIPTION,
    SYNTHESIS_EVALUATION,
    UNRESOLVED_EPISTEMIC_MODE,
})

CAUSAL_IDENTIFICATION_MODES = frozenset({
    "natural_experiment",
    "temporal_order",
    "comparative_population",
    "independent_observational_channels",
    "theory_constrained_identification",
    "instrumental_or_geometric_effect",
    "quasi_experimental_design",
})

CLAIM_TYPES = frozenset({
    "causal_effect",
    "mechanism",
    "parameter_constraint",
    "model_comparison",
    "prediction_or_forecast",
    "existence_or_detection",
    "association_or_structure",
    "theoretical_derivation",
    "consistency_or_no_go",
    "formal_theorem",
    "counterexample_or_boundary",
    "measurement_validity",
    "method_performance",
    "feasibility",
})

_MODE_ALIASES = {
    "experimental": EXPERIMENTAL_INTERVENTION,
    "experimental_intervention": EXPERIMENTAL_INTERVENTION,
    "controlled_intervention": EXPERIMENTAL_INTERVENTION,
    "controlled_experiment": EXPERIMENTAL_INTERVENTION,
    "observational": OBSERVATIONAL_INFERENCE,
    "observational_inference": OBSERVATIONAL_INFERENCE,
    "observational_model_discrimination": OBSERVATIONAL_INFERENCE,
    "natural_experiment_or_quasi_experiment": OBSERVATIONAL_INFERENCE,
    "natural_experiment": OBSERVATIONAL_INFERENCE,
    "theoretical": THEORETICAL_DERIVATION,
    "theoretical_derivation": THEORETICAL_DERIVATION,
    "theoretical_or_formal": THEORETICAL_DERIVATION,
    "mathematical": MATHEMATICAL_PROOF,
    "mathematical_proof": MATHEMATICAL_PROOF,
    "formal_proof": MATHEMATICAL_PROOF,
    "computational": COMPUTATIONAL_SIMULATION,
    "computational_simulation": COMPUTATIONAL_SIMULATION,
    "computational_intervention": COMPUTATIONAL_SIMULATION,
    "engineering": ENGINEERING_VALIDATION,
    "engineering_validation": ENGINEERING_VALIDATION,
    "instrumentation_or_measurement": ENGINEERING_VALIDATION,
    "classification": CLASSIFICATION_DESCRIPTION,
    "classification_description": CLASSIFICATION_DESCRIPTION,
    "descriptive": CLASSIFICATION_DESCRIPTION,
    "synthesis": SYNTHESIS_EVALUATION,
    "synthesis_evaluation": SYNTHESIS_EVALUATION,
    "review": SYNTHESIS_EVALUATION,
}

_LEGACY_MODE_MAP = {
    "CONTROLLED_INTERVENTION": EXPERIMENTAL_INTERVENTION,
    "NATURAL_EXPERIMENT_OR_QUASI_EXPERIMENT": OBSERVATIONAL_INFERENCE,
    "OBSERVATIONAL_MODEL_DISCRIMINATION": OBSERVATIONAL_INFERENCE,
    "COMPUTATIONAL_INTERVENTION": COMPUTATIONAL_SIMULATION,
    "INSTRUMENTATION_OR_MEASUREMENT": ENGINEERING_VALIDATION,
    "LABORATORY_CONSTRAINT": EXPERIMENTAL_INTERVENTION,
    "THEORETICAL_OR_FORMAL": THEORETICAL_DERIVATION,
}

_CLAIM_ALIASES = {
    "causal": "causal_effect",
    "causal_effect": "causal_effect",
    "mechanistic": "mechanism",
    "parameter": "parameter_constraint",
    "parameter_constraint": "parameter_constraint",
    "model_comparison": "model_comparison",
    "forecast": "prediction_or_forecast",
    "prediction": "prediction_or_forecast",
    "prediction_or_forecast": "prediction_or_forecast",
    "detection": "existence_or_detection",
    "existence": "existence_or_detection",
    "existence_or_detection": "existence_or_detection",
    "association": "association_or_structure",
    "structure": "association_or_structure",
    "association_or_structure": "association_or_structure",
    "derivation": "theoretical_derivation",
    "theoretical_derivation": "theoretical_derivation",
    "consistency": "consistency_or_no_go",
    "no_go": "consistency_or_no_go",
    "consistency_or_no_go": "consistency_or_no_go",
    "theorem": "formal_theorem",
    "formal_theorem": "formal_theorem",
    "counterexample": "counterexample_or_boundary",
    "boundary": "counterexample_or_boundary",
    "counterexample_or_boundary": "counterexample_or_boundary",
    "measurement_validity": "measurement_validity",
    "method_performance": "method_performance",
    "feasibility": "feasibility",
}

_CLAIM_MARKERS: dict[str, tuple[str, ...]] = {
    "causal_effect": ("causal effect", "causes", "causal impact", "treatment effect", "intervention effect"),
    "mechanism": ("mechanism", "pathway", "mediates", "mediator", "mechanistic"),
    "parameter_constraint": ("parameter constraint", "posterior", "likelihood", "confidence interval", "credible interval", "constrain", "constraint on"),
    "model_comparison": ("model comparison", "competing model", "model selection", "bayes factor", "information criterion", "goodness of fit"),
    "prediction_or_forecast": ("forecast", "prediction", "projected", "projection", "future state"),
    "existence_or_detection": ("detection", "detected", "existence", "catalog", "catalogue", "identify whether"),
    "association_or_structure": ("association", "correlation", "relationship", "structure", "distribution", "network"),
    "theoretical_derivation": ("derivation", "derive", "analytical solution", "field equation", "theoretical prediction"),
    "consistency_or_no_go": ("consistency", "no-go", "no go", "stability", "causality condition", "unitarity"),
    "formal_theorem": ("theorem", "proof", "lemma", "axiom", "proposition"),
    "counterexample_or_boundary": ("counterexample", "boundary case", "validity regime", "necessary condition", "sufficient condition"),
    "measurement_validity": ("calibration", "systematic error", "measurement bias", "uncertainty propagation", "measurement validity"),
    "method_performance": ("benchmark", "accuracy", "precision", "robustness", "performance evaluation", "ablation"),
    "feasibility": ("feasibility", "implementability", "deployment", "scalability", "technical viability"),
}

_MODE_MARKERS: dict[str, tuple[str, ...]] = {
    EXPERIMENTAL_INTERVENTION: ("controlled experiment", "randomized", "perturbation", "intervention", "ablation", "dose-response", "treated with"),
    OBSERVATIONAL_INFERENCE: ("survey", "telescope", "observatory", "time series", "remote sensing", "natural experiment", "monitoring", "likelihood", "posterior", "catalog"),
    THEORETICAL_DERIVATION: ("derivation", "derive", "analytical", "theoretical", "equation", "symmetry", "stability analysis"),
    MATHEMATICAL_PROOF: ("theorem", "proof", "lemma", "axiom", "counterexample", "formal verification"),
    COMPUTATIONAL_SIMULATION: ("simulation", "numerical", "monte carlo", "parameter sweep", "convergence", "sensitivity analysis"),
    ENGINEERING_VALIDATION: ("prototype", "instrument", "sensor", "detector", "calibration", "fault mode", "reliability", "performance test"),
    CLASSIFICATION_DESCRIPTION: ("taxonomy", "morphology", "specimen", "classification", "catalog", "descriptive"),
    SYNTHESIS_EVALUATION: ("systematic review", "meta-analysis", "evidence synthesis", "technology assessment", "roadmap"),
}

_STANDARD_BY_MODE = {
    EXPERIMENTAL_INTERVENTION: "experimental_causal_v1",
    OBSERVATIONAL_INFERENCE: "observational_inference_v1",
    THEORETICAL_DERIVATION: "theoretical_physics_v1",
    MATHEMATICAL_PROOF: "formal_mathematics_v1",
    COMPUTATIONAL_SIMULATION: "computational_simulation_v1",
    ENGINEERING_VALIDATION: "engineering_validation_v1",
    CLASSIFICATION_DESCRIPTION: "classification_description_v1",
    SYNTHESIS_EVALUATION: "synthesis_evaluation_v1",
    UNRESOLVED_EPISTEMIC_MODE: "synthesis_evaluation_v1",
}


def _key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value or "").lower()).strip("_")


def _flatten(value: Any) -> str:
    if isinstance(value, dict):
        return " ".join(_flatten(item) for item in value.values())
    if isinstance(value, (list, tuple, set)):
        return " ".join(_flatten(item) for item in value)
    return str(value or "")


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


def _normalize_mode(value: Any) -> str:
    raw = str(value or "").strip()
    if raw.upper() in _LEGACY_MODE_MAP:
        return _LEGACY_MODE_MAP[raw.upper()]
    return _MODE_ALIASES.get(_key(raw), raw if raw in EPISTEMIC_MODES else "")


def _normalize_claims(value: Any) -> list[str]:
    values = value if isinstance(value, (list, tuple, set)) else [value]
    claims: list[str] = []
    for item in values:
        key = _key(item)
        claim = _CLAIM_ALIASES.get(key, key if key in CLAIM_TYPES else "")
        if claim and claim not in claims:
            claims.append(claim)
    return claims


def _profile_source(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _scientific_disciplines(project: dict[str, Any]) -> list[str]:
    """Read only the existing natural-science taxonomy, never an HSS label."""

    taxonomy = project.get("discovery_taxonomy") if isinstance(project.get("discovery_taxonomy"), dict) else {}
    if not taxonomy:
        resolution = project.get("domain_resolution") if isinstance(project.get("domain_resolution"), dict) else {}
        taxonomy = resolution.get("discovery_taxonomy") if isinstance(resolution.get("discovery_taxonomy"), dict) else {}
    values = [str(item).strip() for item in taxonomy.get("resolved_discipline_ids", []) if str(item).strip()]
    primary = taxonomy.get("primary") if isinstance(taxonomy.get("primary"), dict) else {}
    if str(primary.get("key") or "").strip():
        values.append(str(primary["key"]).strip())
    return _unique(values)


def _infer_claims(text: str) -> tuple[list[str], dict[str, list[str]]]:
    matches = {
        claim: [marker for marker in markers if marker in text]
        for claim, markers in _CLAIM_MARKERS.items()
    }
    claims = [claim for claim, values in matches.items() if values]
    return claims, {claim: values for claim, values in matches.items() if values}


def _infer_modes(text: str, claims: list[str]) -> tuple[list[str], dict[str, list[str]]]:
    matches = {
        mode: [marker for marker in markers if marker in text]
        for mode, markers in _MODE_MARKERS.items()
    }
    inferred = [mode for mode, values in matches.items() if values]
    if "formal_theorem" in claims or "counterexample_or_boundary" in claims:
        inferred.append(MATHEMATICAL_PROOF)
    if "theoretical_derivation" in claims or "consistency_or_no_go" in claims:
        inferred.append(THEORETICAL_DERIVATION)
    if any(claim in claims for claim in ("parameter_constraint", "model_comparison", "existence_or_detection", "association_or_structure")):
        inferred.append(OBSERVATIONAL_INFERENCE)
    if any(claim in claims for claim in ("measurement_validity", "method_performance", "feasibility")):
        inferred.append(ENGINEERING_VALIDATION)
    if "prediction_or_forecast" in claims and COMPUTATIONAL_SIMULATION in inferred:
        inferred.append(COMPUTATIONAL_SIMULATION)
    if any(claim in claims for claim in ("causal_effect", "mechanism")) and matches[EXPERIMENTAL_INTERVENTION]:
        inferred.append(EXPERIMENTAL_INTERVENTION)
    return _unique(inferred), {mode: values for mode, values in matches.items() if values}


def _mode_for_claims(claims: list[str]) -> str:
    if "formal_theorem" in claims or "counterexample_or_boundary" in claims:
        return MATHEMATICAL_PROOF
    if "theoretical_derivation" in claims or "consistency_or_no_go" in claims:
        return THEORETICAL_DERIVATION
    if any(claim in claims for claim in ("parameter_constraint", "model_comparison", "existence_or_detection", "association_or_structure")):
        return OBSERVATIONAL_INFERENCE
    if any(claim in claims for claim in ("measurement_validity", "method_performance", "feasibility")):
        return ENGINEERING_VALIDATION
    return UNRESOLVED_EPISTEMIC_MODE


def normalize_epistemic_profile(
    value: Any,
    *,
    project: dict[str, Any] | None = None,
    fallback_text: str = "",
) -> dict[str, Any]:
    project = project if isinstance(project, dict) else {}
    source = _profile_source(value)
    explicit_primary = _normalize_mode(source.get("primary_mode") or source.get("epistemic_mode") or source.get("research_paradigm"))
    explicit_secondary = [
        _normalize_mode(item)
        for item in (source.get("secondary_modes") or source.get("secondary_mode") or [])
    ]
    explicit_secondary = [item for item in explicit_secondary if item]
    explicit_claims = _normalize_claims(source.get("claim_types") or source.get("claim_type"))
    text = _flatten([fallback_text, source]).lower()
    inferred_claims, claim_matches = _infer_claims(text)
    claims = _unique([*explicit_claims, *inferred_claims])
    inferred_modes, mode_matches = _infer_modes(text, claims)
    primary = explicit_primary or (_mode_for_claims(claims) if claims else "")
    # The legacy THEORETICAL_OR_FORMAL label intentionally conflated two
    # distinct epistemic standards.  A theorem/proof/counterexample claim
    # resolves the ambiguity in favour of formal mathematics.
    if (
        primary == THEORETICAL_DERIVATION
        and any(claim in claims for claim in ("formal_theorem", "counterexample_or_boundary"))
    ):
        primary = MATHEMATICAL_PROOF
    if not primary:
        primary = inferred_modes[0] if inferred_modes else UNRESOLVED_EPISTEMIC_MODE
    secondary = _unique([*explicit_secondary, *inferred_modes])
    secondary = [item for item in secondary if item != primary and item != UNRESOLVED_EPISTEMIC_MODE]
    requires_intervention = bool(
        primary == EXPERIMENTAL_INTERVENTION
        and any(claim in claims for claim in ("causal_effect", "mechanism"))
    )
    standard_id = str(source.get("evidence_standard_id") or source.get("evidence_standard_hint") or "").strip()
    if not standard_id:
        standard_id = _STANDARD_BY_MODE[primary]
    supplied_standards = source.get("evidence_standard_ids") or source.get("evidence_standards") or []
    if isinstance(supplied_standards, str):
        supplied_standards = [supplied_standards]
    secondary_standards = [_STANDARD_BY_MODE.get(mode, "") for mode in secondary]
    standard_ids = _unique([standard_id, *[str(item).strip() for item in supplied_standards], *secondary_standards])
    supplied_identification_modes = source.get("causal_identification_modes") or []
    if isinstance(supplied_identification_modes, str):
        supplied_identification_modes = [supplied_identification_modes]
    inferred_identification_modes: list[str] = []
    if primary == OBSERVATIONAL_INFERENCE:
        marker_map = {
            "natural_experiment": ("natural experiment", "exogenous event"),
            "temporal_order": ("time series", "temporal", "redshift", "longitudinal"),
            "comparative_population": ("comparative population", "population comparison", "object population"),
            "independent_observational_channels": ("independent dataset", "independent channel", "multi-messenger", "cross survey"),
            "theory_constrained_identification": ("theory constrained", "physical prior", "model prior"),
            "instrumental_or_geometric_effect": ("gravitational lens", "geometric", "instrumental variable"),
            "quasi_experimental_design": ("quasi-experiment", "quasi experiment"),
        }
        inferred_identification_modes = [
            key for key, markers in marker_map.items() if any(marker in text for marker in markers)
        ]
    causal_identification_modes = _unique([
        str(item).strip().lower().replace("-", "_").replace(" ", "_")
        for item in [*supplied_identification_modes, *inferred_identification_modes]
        if str(item).strip()
    ])
    causal_identification_modes = [
        item for item in causal_identification_modes if item in CAUSAL_IDENTIFICATION_MODES
    ]
    scientific_disciplines = _scientific_disciplines(project) or [
        str(item).strip()
        for item in source.get("scientific_disciplines", [])
        if str(item).strip()
    ]
    return {
        "schema_version": EPISTEMIC_PROFILE_SCHEMA_VERSION,
        "scope": "natural_science_health_engineering_only",
        "scientific_disciplines": _unique(scientific_disciplines),
        "primary_mode": primary,
        "secondary_modes": secondary[:4],
        "claim_types": claims[:4],
        "evidence_standard_id": standard_id,
        "evidence_standard_ids": standard_ids[:4],
        "requires_intervention": requires_intervention,
        "causal_identification_modes": causal_identification_modes,
        "accepted_core_evidence": list(source.get("accepted_core_evidence") or []),
        "classification_audit": {
            "declared_primary_mode": explicit_primary,
            "declared_claim_types": explicit_claims,
            "inferred_mode_matches": mode_matches,
            "inferred_claim_matches": claim_matches,
            "mode_selection": "declared" if explicit_primary else "claim_compatible_or_text_inferred",
            "discipline_source": "existing_natural_science_taxonomy",
        },
    }


def infer_epistemic_profile(project: dict[str, Any], sub_hypothesis: dict[str, Any]) -> dict[str, Any]:
    sub_hypothesis = sub_hypothesis if isinstance(sub_hypothesis, dict) else {}
    existing = _profile_source(sub_hypothesis.get("epistemic_profile"))
    text = _flatten({
        key: sub_hypothesis.get(key)
        for key in (
            "focus", "scientific_object", "primary_field", "retrieval_query", "evidence_mode",
            "causal_chain", "causal_contract", "evidence_paths", "independent_variable",
            "dependent_variables", "comparison", "falsification_condition", "declared_research_mode",
        )
    })
    if not existing and sub_hypothesis.get("declared_research_mode"):
        existing = {"primary_mode": sub_hypothesis.get("declared_research_mode")}
    if (
        not existing
        and sub_hypothesis.get("independent_variable")
        and sub_hypothesis.get("causal_chain")
        and not any(marker in text.lower() for marker in ("theorem", "proof", "lemma", "axiom", "counterexample", "derivation"))
    ):
        # Historic normalized SHs used these fields as an explicit causal
        # experiment signature.  Preserve that intent while leaving new
        # observation/theory/formal SHs free to declare their own profile.
        existing = {
            "primary_mode": EXPERIMENTAL_INTERVENTION,
            "claim_types": ["causal_effect"],
        }
    return normalize_epistemic_profile(existing, project=project, fallback_text=text)
