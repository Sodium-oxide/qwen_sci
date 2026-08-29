"""Deterministic, cross-discipline section routing for research-plan writing."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping


AUTHOR_TEMPLATE_FAMILIES = (
    "computational_digital",
    "mathematics_theory",
    "materials_chemical",
    "engineering_energy",
    "earth_environment_agro",
    "life_veterinary",
    "clinical_health",
)

_DISCIPLINE_TEMPLATE = {
    "17": "computational_digital",
    "26": "mathematics_theory",
    "15": "materials_chemical",
    "16": "materials_chemical",
    "25": "materials_chemical",
    "21": "engineering_energy",
    "22": "engineering_energy",
    "11": "earth_environment_agro",
    "19": "earth_environment_agro",
    "23": "earth_environment_agro",
    "13": "life_veterinary",
    "24": "life_veterinary",
    "28": "life_veterinary",
    "30": "life_veterinary",
    "34": "life_veterinary",
    "27": "clinical_health",
    "29": "clinical_health",
    "35": "clinical_health",
    "36": "clinical_health",
}

_COMMON_ROUTES = (
    ("abstract", "Abstract", "abstract", ("research_gap", "planned_contribution", "expected_outcome")),
    ("introduction", "Introduction", "sections", ("background", "research_gap")),
    ("survey_and_research_gap", "Background, Survey, and Research Gap", "sections", ("background", "survey_evidence", "research_gap")),
    ("research_questions_and_contributions", "Research Questions and Planned Contributions", "sections", ("research_question", "planned_contribution", "design_assumption")),
    ("idea_origin_and_selection", "Idea Source Checkpoints and Direction Selection Audit", "sections", ("idea_provenance", "design_assumption")),
    ("formal_problem_and_hypotheses", "Problem Definition, Assumptions, and Hypotheses", "sections", ("formal_definition", "formal_proposition", "hypothesis", "design_assumption")),
    ("study_design_and_methods", "Study Design and Methods", "sections", ("planned_method", "design_assumption", "needs_human_input")),
    ("expected_outcomes", "Expected Outcome Branches and Conditional Conclusions", "sections", ("expected_outcome", "conditional_conclusion")),
    ("risk_limitations_and_review", "Risks, Limitations, and Human Review Requirements", "sections", ("limitation", "needs_human_input", "review_requirement")),
    ("references", "References", "sections", ("citation_inventory",)),
    ("appendix_idea_evolution", "Idea Source Checkpoints and Direction Selection Audit", "appendices", ("idea_provenance",)),
    ("appendix_variables_and_definitions", "Variables, Symbols, and Operational Definitions", "appendices", ("formal_definition", "planned_method", "design_assumption", "needs_human_input")),
    ("appendix_evidence_and_review", "Evidence Coverage, Unknown Items, and Review Checklist", "appendices", ("survey_evidence", "limitation", "review_requirement", "needs_human_input")),
)

_TEMPLATE_ROUTES = {
    "computational_digital": (
        ("computational_evaluation_protocol", "Data, Baselines, Ablations, and Robustness", ("planned_method", "design_assumption", "needs_human_input")),
    ),
    "mathematics_theory": (
        ("definitions_and_propositions", "Definitions, Propositions, and Proof Obligations", ("formal_definition", "formal_proposition", "proof_obligation")),
        ("forward_derivation_and_counterexamples", "Forward Derivation and Counterexample Search Plan", ("forward_derivation", "counterexample_plan", "limitation")),
    ),
    "materials_chemical": (
        ("materials_and_characterization", "Material System, Characterization, and DOE Plan", ("planned_method", "design_assumption", "needs_human_input")),
    ),
    "engineering_energy": (
        ("system_boundary_and_validation", "System Boundary, Constraints, and Layered Validation", ("planned_method", "design_assumption", "needs_human_input")),
    ),
    "earth_environment_agro": (
        ("spatiotemporal_design", "Spatiotemporal Units, Sampling Frame, and Environmental Covariates", ("planned_method", "design_assumption", "needs_human_input")),
    ),
    "life_veterinary": (
        ("model_controls_and_repeats", "Model System, Controls, Assays, and Replicates", ("planned_method", "design_assumption", "needs_human_input", "review_requirement")),
    ),
    "clinical_health": (
        ("pico_endpoints_and_governance", "PICO, Endpoints, Bias Control, and Governance", ("planned_method", "design_assumption", "needs_human_input", "review_requirement")),
    ),
}


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _text(value: object) -> str:
    return str(value or "").strip()


def resolve_author_template(author_input: Mapping[str, Any]) -> str:
    """Resolve one author template from upstream routing, then declared disciplines."""

    provenance = _mapping(author_input.get("provenance"))
    configured = _text(provenance.get("template_id"))
    if configured in AUTHOR_TEMPLATE_FAMILIES:
        return configured
    composition = _mapping(author_input.get("template_composition"))
    configured = _text(composition.get("template_id"))
    if configured in AUTHOR_TEMPLATE_FAMILIES:
        return configured
    disciplines = provenance.get("discipline_ids") if isinstance(provenance.get("discipline_ids"), list) else []
    if "31" in {_text(item) for item in disciplines}:
        selected = _mapping(author_input.get("selected_direction"))
        context = " ".join(
            _text(value).casefold()
            for value in (
                selected.get("title"),
                selected.get("central_hypothesis"),
                selected.get("mechanism_or_relation"),
            )
        )
        return "mathematics_theory" if any(term in context for term in ("theorem", "proof", "derivation", "counterexample", "formal")) else "engineering_energy"
    for discipline_id in disciplines:
        resolved = _DISCIPLINE_TEMPLATE.get(_text(discipline_id))
        if resolved:
            return resolved
    return "computational_digital"


def route_author_sections(author_input: Mapping[str, Any]) -> dict[str, Any]:
    """Return a fixed route that the LLM may fill but never expand or reorder."""

    template_family = resolve_author_template(author_input)
    template_routes = _TEMPLATE_ROUTES[template_family]
    routes: list[dict[str, Any]] = []
    for section_id, title, target, claim_kinds in _COMMON_ROUTES:
        if section_id == "references":
            for extra_id, extra_title, extra_claim_kinds in template_routes:
                routes.append(
                    {
                        "section_id": extra_id,
                        "title": extra_title,
                        "target": "sections",
                        "applicability": "required",
                        "allowed_claim_kinds": list(extra_claim_kinds),
                    }
                )
        routes.append(
            {
                "section_id": section_id,
                "title": title,
                "target": target,
                "applicability": "required" if section_id != "appendix_idea_evolution" else "optional",
                "allowed_claim_kinds": list(claim_kinds),
            }
        )
    return {
        "schema_version": "research_plan_author_section_routing_v1",
        "template_family": template_family,
        "routes": routes,
        "theory_sampling_power_status": "not_applicable" if template_family == "mathematics_theory" else "route_specific",
    }


def required_route_ids(routing: Mapping[str, Any]) -> list[str]:
    return [
        _text(route.get("section_id"))
        for route in routing.get("routes") or []
        if isinstance(route, Mapping) and _text(route.get("applicability")) == "required"
    ]


def route_copy(routing: Mapping[str, Any]) -> dict[str, Any]:
    return deepcopy(dict(routing))


__all__ = [
    "AUTHOR_TEMPLATE_FAMILIES",
    "required_route_ids",
    "resolve_author_template",
    "route_author_sections",
    "route_copy",
]
