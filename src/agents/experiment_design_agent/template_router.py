"""Domain-template routing for design-only experiment preparation."""

from __future__ import annotations

from copy import deepcopy
import json
import re
from collections.abc import Mapping, Sequence
from typing import Any

from .discipline_catalog import resolve_design_scope


TEMPLATE_ROUTING_SCHEMA_VERSION = "experiment_design_template_routing_v1"

_COMMON_REQUIREMENTS = (
    "research_design.design_type",
    "research_design.experimental_unit",
    "research_design.time_structure",
    "hypothesis_mapping",
    "variables_and_operationalization",
    "sampling_and_eligibility",
    "measurement_and_calibration",
    "comparison_and_robustness",
    "analysis_plan",
    "data_governance_and_reproducibility",
    "outcome_branches",
)

_TEMPLATE_PROFILES: dict[str, dict[str, Any]] = {
    "computational_digital": {
        "label": "Computational and digital systems",
        "discipline_ids": ("17",),
        "required_design_fields": ("template_details.dataset_or_corpus", "template_details.baseline_systems", "template_details.ablation_plan", "template_details.resource_constraints"),
        "query_terms": ("benchmark protocol", "baseline comparison", "ablation study", "robustness evaluation"),
    },
    "mathematics_theory": {
        "label": "Formal theory and mathematics",
        "discipline_ids": ("26",),
        "required_design_fields": ("template_details.formal_claim", "template_details.assumptions", "template_details.counterexample_or_boundary_analysis", "template_details.verification_plan"),
        "query_terms": ("formal proof", "assumption analysis", "counterexample", "numerical verification"),
    },
    "materials_chemical": {
        "label": "Chemistry, materials, and chemical engineering",
        "discipline_ids": ("15", "16", "25"),
        "required_design_fields": ("template_details.sample_or_material", "template_details.process_variables", "template_details.characterization_plan", "template_details.comparison_samples", "template_details.replicate_strategy"),
        "query_terms": ("process structure property", "characterization method", "control sample", "technical replicate"),
    },
    "engineering_energy": {
        "label": "Engineering and energy systems",
        "discipline_ids": ("21", "22"),
        "required_design_fields": ("template_details.system_boundary", "template_details.failure_modes", "template_details.validation_layers", "template_details.safety_constraints"),
        "query_terms": ("test bench", "system boundary", "failure mode", "hardware in the loop"),
    },
    "earth_environment_agro": {
        "label": "Earth, environmental, and agricultural systems",
        "discipline_ids": ("11", "19", "23"),
        "required_design_fields": ("template_details.sampling_frame", "template_details.spatial_temporal_design", "template_details.exposure_or_driver", "template_details.field_or_remote_measurement", "template_details.confounding_plan"),
        "query_terms": ("field sampling", "spatiotemporal design", "exposure measurement", "causal attribution"),
    },
    "life_veterinary": {
        "label": "Life sciences and veterinary science",
        "discipline_ids": ("13", "24", "28", "30", "34"),
        "required_design_fields": ("template_details.biological_system", "template_details.perturbation", "template_details.phenotype_or_pathway_readout", "template_details.technical_and_biological_replicates", "template_details.positive_and_negative_controls"),
        "query_terms": ("biological replicate", "assay validation", "positive control", "negative control"),
    },
    "clinical_health": {
        "label": "Clinical and health research",
        "discipline_ids": ("27", "29", "35", "36"),
        "required_design_fields": ("template_details.study_type", "template_details.target_population", "template_details.primary_endpoint", "template_details.bias_and_confounding_control", "template_details.ethics_and_data_approval"),
        "query_terms": ("PICO", "clinical endpoint", "eligibility criteria", "confounding control", "risk of bias"),
    },
}
_FIELD_TO_TEMPLATE = {
    discipline_id: template_id
    for template_id, profile in _TEMPLATE_PROFILES.items()
    for discipline_id in profile["discipline_ids"]
}
_FORMAL_SIGNALS = ("theorem", "proof", "derive", "derivation", "symbolic", "formal", "counterexample")
_PHYSICAL_SIGNALS = ("observation", "measurement", "instrument", "experiment", "detector", "laboratory", "physical")


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _text(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _payload_text(*values: object) -> str:
    parts: list[str] = []
    for value in values:
        try:
            parts.append(json.dumps(value, ensure_ascii=False, sort_keys=True))
        except (TypeError, ValueError):
            parts.append(str(value))
    return " ".join(parts).casefold()


def _signals(research_brief: Mapping[str, Any], user_constraints: Mapping[str, Any]) -> list[str]:
    selected_direction = _mapping(research_brief.get("selected_direction"))
    payload = _payload_text(
        research_brief.get("topic"),
        selected_direction.get("title"),
        selected_direction.get("central_hypothesis"),
        selected_direction.get("mechanism_or_relation"),
        research_brief.get("research_object"),
        research_brief.get("intervention_or_transformation"),
        user_constraints,
    )
    resolved: list[str] = []
    if any(signal in payload for signal in _FORMAL_SIGNALS):
        resolved.append("formal_or_symbolic")
    if any(signal in payload for signal in _PHYSICAL_SIGNALS):
        resolved.append("physical_observation_or_validation")
    if "simulation" in payload or "computational model" in payload:
        resolved.append("simulation_or_computation")
    if any(signal in payload for signal in ("cohort", "diagnostic", "patient", "clinical")):
        resolved.append("clinical_or_observational")
    return resolved


def get_template_profile(template_id: str) -> dict[str, Any]:
    """Return an immutable-copy view of one supported design template."""

    if template_id not in _TEMPLATE_PROFILES:
        raise ValueError(f"Unknown ExperimentDesign template: {template_id}")
    return deepcopy(_TEMPLATE_PROFILES[template_id])


class TemplateRouter:
    """Choose one primary template and at most one controlled secondary template."""

    def route(
        self,
        research_brief: Mapping[str, Any],
        *,
        user_constraints: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        brief = _mapping(research_brief)
        constraints = _mapping(user_constraints)
        scope = resolve_design_scope(brief.get("discipline_ids"))
        discipline_ids = list(scope["discipline_ids"])
        if scope["status"] != "IN_SCOPE":
            return {
                "schema_version": TEMPLATE_ROUTING_SCHEMA_VERSION,
                "status": "NOT_ROUTED",
                "reason": "A supported template cannot be selected until scope is in range.",
                "primary_template": "",
                "secondary_template": "",
                "discipline_ids": discipline_ids,
                "routing_signals": [],
                "required_design_fields": [],
                "query_terms": [],
            }
        routing_signals = _signals(brief, constraints)
        template_candidates = [_FIELD_TO_TEMPLATE[identifier] for identifier in discipline_ids if identifier in _FIELD_TO_TEMPLATE]
        primary = template_candidates[0] if template_candidates else ""
        physics_submode = ""
        if "31" in discipline_ids:
            physics_submode = "formal_theory" if "formal_or_symbolic" in routing_signals else "physical_validation"
            physics_template = "mathematics_theory" if physics_submode == "formal_theory" else "engineering_energy"
            if not primary:
                primary = physics_template
            elif primary == physics_template:
                primary = physics_template
        clinical_candidates = [candidate for candidate in template_candidates if candidate == "clinical_health"]
        if clinical_candidates:
            primary = "clinical_health"
        secondary_candidates = [candidate for candidate in template_candidates if candidate != primary]
        if "31" in discipline_ids:
            physics_template = "mathematics_theory" if physics_submode == "formal_theory" else "engineering_energy"
            if physics_template != primary:
                secondary_candidates.insert(0, physics_template)
        secondary = next(iter(dict.fromkeys(secondary_candidates)), "")
        primary_profile = get_template_profile(primary)
        secondary_profile = get_template_profile(secondary) if secondary else None
        required_fields = list(_COMMON_REQUIREMENTS) + list(primary_profile["required_design_fields"])
        query_terms = list(primary_profile["query_terms"])
        if secondary_profile:
            required_fields.extend(secondary_profile["required_design_fields"])
            query_terms.extend(term for term in secondary_profile["query_terms"] if term not in query_terms)
        return {
            "schema_version": TEMPLATE_ROUTING_SCHEMA_VERSION,
            "status": "ROUTED",
            "reason": "The route is derived from declared disciplines and research-object signals, not literature claims.",
            "primary_template": primary,
            "secondary_template": secondary,
            "discipline_ids": discipline_ids,
            "routing_signals": routing_signals,
            "submode": physics_submode,
            "required_design_fields": required_fields,
            "query_terms": query_terms,
        }
