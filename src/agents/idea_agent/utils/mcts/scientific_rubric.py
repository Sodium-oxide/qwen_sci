"""Profile-aware scientific quality rubric used by Idea Agent evaluation."""

from __future__ import annotations

from typing import Any, Mapping

from src.agents.idea_agent.utils.mcts.scientific_intervention_ontology import (
    format_scientific_intervention_profile_for_prompt,
    get_scientific_intervention_profile,
)


SCIENTIFIC_RUBRIC_VERSION = "scientific_rubric_v3"
SCIENTIFIC_INTERVENTION_PROFILE_VERSION = "scientific_intervention_v2"

SCIENTIFIC_RUBRIC_FIELDS: tuple[str, ...] = (
    "explanatory_power",
    "identifiability",
    "boundary_calibration",
    "claim_overreach_penalty",
)

SCIENTIFIC_RUBRIC_WEIGHT_DEFAULTS: dict[str, float] = {
    "explanatory_power_weight": 0.06,
    "identifiability_weight": 0.06,
    "boundary_calibration_weight": 0.04,
    "claim_overreach_weight": 0.10,
}

PROFILE_SCORE_WEIGHT_MULTIPLIERS: dict[str, dict[str, float]] = {
    "computational_algorithmic": {},
    "physical_materials_chemical": {
        "novelty_weight": 0.85,
        "explanatory_power_weight": 1.45,
        "identifiability_weight": 1.35,
        "boundary_calibration_weight": 1.25,
        "protocol_weight": 0.95,
    },
    "life_molecular_mechanistic": {
        "novelty_weight": 0.85,
        "explanatory_power_weight": 1.40,
        "identifiability_weight": 1.45,
        "boundary_calibration_weight": 1.25,
    },
    "clinical_health": {
        "novelty_weight": 0.80,
        "explanatory_power_weight": 1.35,
        "identifiability_weight": 1.50,
        "boundary_calibration_weight": 1.45,
        "claim_overreach_weight": 1.35,
    },
    "earth_environment_agro": {
        "novelty_weight": 0.85,
        "explanatory_power_weight": 1.35,
        "identifiability_weight": 1.35,
        "boundary_calibration_weight": 1.50,
    },
    "formal_theoretical": {
        "novelty_weight": 0.85,
        "explanatory_power_weight": 1.45,
        "identifiability_weight": 1.35,
        "boundary_calibration_weight": 1.40,
        "protocol_weight": 0.80,
    },
    "energy_engineering_systems": {
        "novelty_weight": 0.85,
        "explanatory_power_weight": 1.30,
        "identifiability_weight": 1.25,
        "boundary_calibration_weight": 1.45,
    },
    "generic_scientific": {
        "novelty_weight": 0.90,
        "explanatory_power_weight": 1.20,
        "identifiability_weight": 1.25,
        "boundary_calibration_weight": 1.20,
    },
}

PROFILE_NOVELTY_AXES: dict[str, tuple[str, ...]] = {
    "computational_algorithmic": (
        "algorithmic_mechanism",
        "representation_or_inference",
        "training_or_execution_strategy",
        "protocol_or_resource_boundary",
    ),
    "physical_materials_chemical": (
        "composition_or_processing",
        "mechanism_or_structure_property_relation",
        "characterization_or_measurement_design",
        "process_or_failure_boundary",
    ),
    "life_molecular_mechanistic": (
        "causal_pathway_or_perturbation",
        "mediator_or_phenotype_relation",
        "assay_or_measurement_design",
        "dose_or_condition_boundary",
    ),
    "clinical_health": (
        "causal_intervention_or_mediation",
        "population_or_endpoint_relation",
        "comparator_or_measurement_design",
        "safety_or_external_validity_boundary",
    ),
    "earth_environment_agro": (
        "forcing_or_process",
        "scale_or_regime_relation",
        "observation_or_attribution_design",
        "scenario_or_failure_boundary",
    ),
    "formal_theoretical": (
        "proposition_or_assumption",
        "proof_or_construction",
        "counterexample_or_validity_domain",
        "formal_evidence_obligation",
    ),
    "energy_engineering_systems": (
        "design_rule_or_physical_mechanism",
        "operating_condition_or_constraint",
        "performance_or_measurement_design",
        "stability_or_safety_boundary",
    ),
    "generic_scientific": (
        "intervention_or_mechanism",
        "relation_or_claim",
        "measurement_or_observation_design",
        "boundary_or_falsifier",
    ),
}


def scientific_weight_defaults() -> dict[str, float]:
    return dict(SCIENTIFIC_RUBRIC_WEIGHT_DEFAULTS)


def profile_score_weights(
    profile_id: str,
    base_weights: Mapping[str, float] | None = None,
) -> dict[str, float]:
    """Scale the legacy score weights toward profile-native evidence."""

    weights = dict(base_weights or {})
    for key, value in SCIENTIFIC_RUBRIC_WEIGHT_DEFAULTS.items():
        weights.setdefault(key, value)
    multipliers = PROFILE_SCORE_WEIGHT_MULTIPLIERS.get(
        str(profile_id or "generic_scientific").strip().lower(),
        PROFILE_SCORE_WEIGHT_MULTIPLIERS["generic_scientific"],
    )
    for key, multiplier in multipliers.items():
        if key in weights:
            weights[key] = float(weights[key]) * float(multiplier)
    total = sum(max(0.0, float(value)) for value in weights.values())
    if total <= 0.0:
        return weights
    return {key: max(0.0, float(value)) / total for key, value in weights.items()}


def format_scientific_rubric_for_prompt(
    intervention: Mapping[str, Any] | None,
) -> str:
    """Render scoring anchors without making training a universal requirement."""

    payload = dict(intervention) if isinstance(intervention, Mapping) else {}
    profile_id = str(payload.get("profile_id") or "generic_scientific").strip()
    profile = get_scientific_intervention_profile(profile_id)
    anchors = payload.get("evaluation_anchors")
    if not isinstance(anchors, Mapping) and profile is not None:
        anchors = profile.evaluation_anchors
    anchor_lines: list[str] = []
    if isinstance(anchors, Mapping):
        for metric in SCIENTIFIC_RUBRIC_FIELDS[:3]:
            values = anchors.get(metric, ())
            if isinstance(values, str):
                values = [values]
            if values:
                anchor_lines.append(f"- {metric}: {', '.join(str(value) for value in values)}")

    profile_text = format_scientific_intervention_profile_for_prompt(payload)
    lines = [
            f"Rubric version: {SCIENTIFIC_RUBRIC_VERSION}",
            "Scientific quality dimensions (all 0-5 integer scores):",
            "- explanatory_power: explanatory, mechanistic, theoretical, or causal value of the proposed contribution.",
            "- identifiability: whether evidence, controls, proof, counterexample, or observation can distinguish the claim.",
            "- boundary_calibration: whether validity, failure, transfer, and regime boundaries are explicit.",
            "- claim_overreach_penalty: penalty for claims exceeding evidence, measurement, method, or validation scope; higher is worse.",
            "Profile-specific anchors:",
            *(anchor_lines or ["- Use the fixed profile's native objects, mechanisms, observables, and boundaries."]),
            "Profile context:",
            profile_text,
        ]
    if profile_id == "computational_algorithmic":
        lines.append(
            "Computational evidence note: training signal, loss, backbone, and benchmark may be primary when the algorithmic profile makes them central."
        )
    else:
        lines.append(
            "Evaluate completeness using only the selected profile's native objects, mechanisms, observations, proofs, interventions, and boundaries."
        )
    return "\n".join(lines)


__all__ = [
    "SCIENTIFIC_RUBRIC_VERSION",
    "SCIENTIFIC_INTERVENTION_PROFILE_VERSION",
    "SCIENTIFIC_RUBRIC_FIELDS",
    "SCIENTIFIC_RUBRIC_WEIGHT_DEFAULTS",
    "PROFILE_SCORE_WEIGHT_MULTIPLIERS",
    "PROFILE_NOVELTY_AXES",
    "scientific_weight_defaults",
    "profile_score_weights",
    "format_scientific_rubric_for_prompt",
]
