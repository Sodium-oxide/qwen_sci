"""Epistemic evidence-role registry for multi-disciplinary sub-hypotheses.

Roles describe what a paper contributes to a claim.  They are intentionally
not a universal baseline/adverse/boundary checklist: a proof, a survey data
release, and a controlled intervention each need different evidence roles.
"""
from __future__ import annotations

from collections import Counter
from typing import Any


EVIDENCE_ROLE_SCHEMA_VERSION = "epistemic_evidence_role_contract_v1"


def _role(
    role_id: str,
    family: str,
    anchors: tuple[str, ...],
    *,
    core: bool = False,
    polarity: str = "supportive",
) -> dict[str, Any]:
    return {
        "id": role_id,
        "family": family,
        "retrieval_anchors": list(anchors),
        "core_eligible": core,
        "default_polarity": polarity,
    }


# This is a role library, not a discipline list.  The same role can be useful
# in more than one natural-science or engineering field.
EVIDENCE_ROLE_REGISTRY: dict[str, dict[str, Any]] = {
    # Experimental science
    "intervention_evidence": _role("intervention_evidence", "experimental_direct", ("controlled experiment", "intervention", "perturbation"), core=True),
    "control_evidence": _role("control_evidence", "experimental_design", ("control group", "matched control", "reference condition")),
    "dose_response": _role("dose_response", "experimental_design", ("dose response", "concentration series", "parameter gradient")),
    "mechanistic_evidence": _role("mechanistic_evidence", "mechanism", ("mechanism", "pathway", "mediator"), core=True),
    "adverse_result": _role("adverse_result", "negative_or_reversal", ("adverse effect", "toxicity", "negative result"), polarity="opposing"),
    "failure_or_reversal": _role("failure_or_reversal", "negative_or_reversal", ("null effect", "reversal", "failure mode"), polarity="opposing"),
    "replication_or_robustness": _role("replication_or_robustness", "robustness", ("replication", "robustness", "reproducibility")),
    "method_or_platform": _role("method_or_platform", "method", ("assay", "platform", "method validation")),
    "experimental_boundary_condition": _role("experimental_boundary_condition", "boundary", ("boundary condition", "heterogeneity", "validity regime"), polarity="boundary"),
    # Observational science
    "direct_observational_constraint": _role("direct_observational_constraint", "observational_direct", ("direct observation", "parameter constraint", "likelihood", "posterior"), core=True),
    "independent_observational_channel": _role("independent_observational_channel", "observational_replication", ("independent dataset", "independent observation", "cross survey")),
    "data_release_or_survey": _role("data_release_or_survey", "observational_data", ("data release", "survey", "catalog", "catalogue"), core=True),
    "calibration_or_data_processing": _role("calibration_or_data_processing", "measurement", ("calibration", "data processing", "pipeline validation"), core=True),
    "selection_effect": _role("selection_effect", "measurement", ("selection effect", "completeness", "sampling bias"), polarity="boundary"),
    "systematic_error": _role("systematic_error", "measurement", ("systematic error", "measurement bias", "systematics"), polarity="boundary"),
    "covariance_or_uncertainty": _role("covariance_or_uncertainty", "measurement", ("covariance", "uncertainty propagation", "error budget"), polarity="boundary"),
    "alternative_model_explanation": _role("alternative_model_explanation", "model_comparison", ("alternative model", "competing model", "model comparison"), core=True, polarity="opposing"),
    "tension_or_inconsistency": _role("tension_or_inconsistency", "model_comparison", ("tension", "inconsistency", "discrepant constraint"), polarity="opposing"),
    "cross_dataset_joint_constraint": _role("cross_dataset_joint_constraint", "observational_synthesis", ("joint constraint", "combined analysis", "cross dataset"), core=True),
    "predictive_test": _role("predictive_test", "prediction", ("predictive test", "forecast", "out of sample"), core=True),
    "historical_baseline_or_foundation": _role("historical_baseline_or_foundation", "foundation", ("foundational", "legacy survey", "historical baseline")),
    # Theory
    "fundamental_assumption": _role("fundamental_assumption", "theoretical_basis", ("assumption", "postulate", "model premise")),
    "analytical_derivation": _role("analytical_derivation", "theoretical_direct", ("analytical derivation", "equation", "derivation"), core=True),
    "symmetry_or_conservation": _role("symmetry_or_conservation", "theoretical_constraint", ("symmetry", "conservation law", "invariance")),
    "limiting_case": _role("limiting_case", "theoretical_constraint", ("limiting case", "asymptotic", "special case"), polarity="boundary"),
    "consistency_check": _role("consistency_check", "theoretical_constraint", ("consistency", "self consistency", "unitarity"), core=True),
    "stability_analysis": _role("stability_analysis", "theoretical_constraint", ("stability analysis", "instability", "perturbative stability")),
    "causality_or_ghost_condition": _role("causality_or_ghost_condition", "theoretical_constraint", ("causality condition", "ghost free", "no ghost"), polarity="boundary"),
    "no_go_theorem": _role("no_go_theorem", "theoretical_constraint", ("no-go theorem", "no go theorem", "impossibility"), polarity="opposing"),
    "numerical_solution": _role("numerical_solution", "theoretical_computation", ("numerical solution", "numerical integration", "simulation")),
    "observable_prediction": _role("observable_prediction", "prediction", ("observable prediction", "testable prediction", "observable consequence"), core=True),
    "empirical_connection": _role("empirical_connection", "theory_observation_bridge", ("observational test", "experimental test", "data constraint")),
    "alternative_theory_comparison": _role("alternative_theory_comparison", "model_comparison", ("alternative theory", "competing theory", "model comparison"), polarity="opposing"),
    # Mathematics and formal work
    "definition_and_premise": _role("definition_and_premise", "formal_basis", ("definition", "assumption", "premise")),
    "key_lemma": _role("key_lemma", "formal_dependency", ("lemma", "auxiliary result", "technical lemma")),
    "main_theorem": _role("main_theorem", "formal_direct", ("theorem", "main result", "formal statement"), core=True),
    "proof_strategy": _role("proof_strategy", "formal_dependency", ("proof strategy", "proof technique", "construction")),
    "prior_theorem_dependency": _role("prior_theorem_dependency", "formal_dependency", ("previous theorem", "known result", "theorem dependency")),
    "counterexample": _role("counterexample", "formal_boundary", ("counterexample", "counter model", "disproof"), core=True, polarity="opposing"),
    "formal_boundary_condition": _role("formal_boundary_condition", "formal_boundary", ("boundary case", "condition", "validity domain"), polarity="boundary"),
    "generalization_or_weakening": _role("generalization_or_weakening", "formal_extension", ("generalization", "weakened assumption", "extension")),
    "equivalent_formulation": _role("equivalent_formulation", "formal_extension", ("equivalence", "equivalent formulation", "characterization")),
    "open_case": _role("open_case", "formal_boundary", ("open problem", "unresolved case", "unknown"), polarity="boundary"),
    "independence_or_undecidability": _role("independence_or_undecidability", "formal_boundary", ("independence", "undecidability", "unprovable"), polarity="boundary"),
    "computer_assisted_proof": _role("computer_assisted_proof", "formal_validation", ("computer assisted proof", "verified computation", "proof assistant")),
    "formal_verification": _role("formal_verification", "formal_validation", ("formal verification", "machine checked proof", "proof assistant"), core=True),
    # Simulation / engineering / descriptive / synthesis
    "validated_simulation": _role("validated_simulation", "simulation_direct", ("validated simulation", "numerical model", "benchmark"), core=True),
    "convergence_or_sensitivity": _role("convergence_or_sensitivity", "simulation_validation", ("convergence", "sensitivity analysis", "uncertainty propagation"), polarity="boundary"),
    "performance_benchmark": _role("performance_benchmark", "engineering_direct", ("performance benchmark", "performance test", "metric"), core=True),
    "robustness_or_fault_mode": _role("robustness_or_fault_mode", "engineering_validation", ("robustness", "fault mode", "reliability"), polarity="boundary"),
    "descriptive_catalog": _role("descriptive_catalog", "descriptive_direct", ("catalog", "classification", "characterization"), core=True),
    "sampling_or_definition_boundary": _role("sampling_or_definition_boundary", "descriptive_boundary", ("sampling", "definition", "coverage"), polarity="boundary"),
    "evidence_synthesis": _role("evidence_synthesis", "synthesis_direct", ("systematic review", "meta analysis", "evidence synthesis"), core=True),
    "heterogeneity_or_evidence_quality": _role("heterogeneity_or_evidence_quality", "synthesis_qualification", ("heterogeneity", "risk of bias", "evidence quality"), polarity="boundary"),
}


_SELECTIONS: dict[tuple[str, str], tuple[str, tuple[str, ...]]] = {
    ("experimental_intervention", "causal_effect"): ("intervention_evidence", ("control_evidence", "dose_response", "adverse_result", "failure_or_reversal", "replication_or_robustness", "experimental_boundary_condition")),
    ("experimental_intervention", "mechanism"): ("mechanistic_evidence", ("intervention_evidence", "control_evidence", "replication_or_robustness", "method_or_platform", "experimental_boundary_condition")),
    ("observational_inference", "parameter_constraint"): ("direct_observational_constraint", ("data_release_or_survey", "systematic_error", "covariance_or_uncertainty", "cross_dataset_joint_constraint", "independent_observational_channel")),
    ("observational_inference", "model_comparison"): ("alternative_model_explanation", ("direct_observational_constraint", "cross_dataset_joint_constraint", "tension_or_inconsistency", "systematic_error", "predictive_test")),
    ("observational_inference", "prediction_or_forecast"): ("predictive_test", ("data_release_or_survey", "direct_observational_constraint", "systematic_error", "historical_baseline_or_foundation")),
    ("observational_inference", "existence_or_detection"): ("direct_observational_constraint", ("data_release_or_survey", "calibration_or_data_processing", "selection_effect", "independent_observational_channel")),
    ("observational_inference", "association_or_structure"): ("direct_observational_constraint", ("data_release_or_survey", "selection_effect", "covariance_or_uncertainty", "alternative_model_explanation")),
    ("observational_inference", "measurement_validity"): ("calibration_or_data_processing", ("systematic_error", "covariance_or_uncertainty", "selection_effect", "independent_observational_channel")),
    ("theoretical_derivation", "theoretical_derivation"): ("analytical_derivation", ("fundamental_assumption", "consistency_check", "limiting_case", "observable_prediction", "empirical_connection")),
    ("theoretical_derivation", "consistency_or_no_go"): ("consistency_check", ("fundamental_assumption", "stability_analysis", "causality_or_ghost_condition", "no_go_theorem", "alternative_theory_comparison")),
    ("theoretical_derivation", "prediction_or_forecast"): ("observable_prediction", ("analytical_derivation", "numerical_solution", "empirical_connection", "alternative_theory_comparison")),
    ("mathematical_proof", "formal_theorem"): ("main_theorem", ("definition_and_premise", "key_lemma", "proof_strategy", "prior_theorem_dependency", "counterexample", "generalization_or_weakening")),
    ("mathematical_proof", "counterexample_or_boundary"): ("counterexample", ("formal_boundary_condition", "equivalent_formulation", "open_case", "independence_or_undecidability")),
    ("computational_simulation", "prediction_or_forecast"): ("validated_simulation", ("convergence_or_sensitivity", "empirical_connection", "observable_prediction")),
    ("computational_simulation", "method_performance"): ("validated_simulation", ("convergence_or_sensitivity", "performance_benchmark")),
    ("engineering_validation", "method_performance"): ("performance_benchmark", ("method_or_platform", "robustness_or_fault_mode", "calibration_or_data_processing")),
    ("engineering_validation", "feasibility"): ("performance_benchmark", ("robustness_or_fault_mode", "method_or_platform", "experimental_boundary_condition")),
    ("classification_description", "existence_or_detection"): ("descriptive_catalog", ("sampling_or_definition_boundary", "independent_observational_channel")),
    ("classification_description", "association_or_structure"): ("descriptive_catalog", ("sampling_or_definition_boundary", "equivalent_formulation")),
    ("synthesis_evaluation", "method_performance"): ("evidence_synthesis", ("heterogeneity_or_evidence_quality", "historical_baseline_or_foundation")),
}

_FALLBACK_BY_MODE: dict[str, tuple[str, tuple[str, ...]]] = {
    "experimental_intervention": ("intervention_evidence", ("control_evidence", "replication_or_robustness", "experimental_boundary_condition")),
    "observational_inference": ("direct_observational_constraint", ("systematic_error", "independent_observational_channel", "data_release_or_survey")),
    "theoretical_derivation": ("analytical_derivation", ("consistency_check", "limiting_case", "observable_prediction")),
    "mathematical_proof": ("main_theorem", ("key_lemma", "counterexample", "formal_boundary_condition")),
    "computational_simulation": ("validated_simulation", ("convergence_or_sensitivity", "performance_benchmark")),
    "engineering_validation": ("performance_benchmark", ("robustness_or_fault_mode", "calibration_or_data_processing")),
    "classification_description": ("descriptive_catalog", ("sampling_or_definition_boundary",)),
    "synthesis_evaluation": ("evidence_synthesis", ("heterogeneity_or_evidence_quality",)),
    "unresolved": ("evidence_synthesis", ("heterogeneity_or_evidence_quality",)),
}


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


def _role_id(value: Any) -> str:
    text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    return text if text in EVIDENCE_ROLE_REGISTRY else ""


def _path_roles(paths: Any) -> list[str]:
    output: list[str] = []
    for path in paths if isinstance(paths, list) else []:
        if not isinstance(path, dict):
            continue
        role = _role_id(path.get("role") or path.get("id"))
        if role:
            output.append(role)
    return _unique(output)


def normalize_evidence_role_contract(
    value: Any,
    *,
    epistemic_profile: dict[str, Any] | None = None,
    evidence_paths: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    source = value if isinstance(value, dict) else {}
    profile = epistemic_profile if isinstance(epistemic_profile, dict) else {}
    primary_mode = str(profile.get("primary_mode") or "unresolved")
    claim_types = [str(item) for item in profile.get("claim_types", []) if str(item)]
    selected_claim = claim_types[0] if claim_types else ""
    primary_role, recommended = _SELECTIONS.get(
        (primary_mode, selected_claim), _FALLBACK_BY_MODE.get(primary_mode, _FALLBACK_BY_MODE["unresolved"])
    )
    supplied_selected = source.get("selected_roles") or source.get("roles") or []
    if isinstance(supplied_selected, str):
        supplied_selected = [supplied_selected]
    selected = [_role_id(item) for item in supplied_selected]
    selected = [item for item in selected if item]
    path_roles = _path_roles(evidence_paths)
    # Existing explicit paths are intentional selections.  With no explicit
    # selection, add just one qualification role rather than the entire menu.
    if not selected:
        selected = [primary_role, *path_roles]
        if not path_roles and recommended:
            selected.append(recommended[0])
    selected = _unique([primary_role, *selected])[:5]
    return {
        "schema_version": EVIDENCE_ROLE_SCHEMA_VERSION,
        "primary_mode": primary_mode,
        "claim_types": claim_types,
        "direct_core_role": primary_role,
        "selected_roles": selected,
        "recommended_roles": list(recommended),
        "optional_role_library": list(recommended),
        "minimum_required_roles": [primary_role],
        "role_policy": "claim_and_profile_selected_roles_not_universal_template",
        "project_coverage_policy": "diversity_is_a_project_level_quality_diagnostic_not_a_single_sh_hard_gate",
    }


def role_evidence_path(
    role_id: str,
    *,
    focus: str,
    scientific_object: str,
    target: str,
    fallback_query: str,
) -> dict[str, Any]:
    role = EVIDENCE_ROLE_REGISTRY.get(role_id) or EVIDENCE_ROLE_REGISTRY["evidence_synthesis"]
    anchors = " ".join(str(item) for item in role.get("retrieval_anchors", [])[:3])
    core = bool(role.get("core_eligible") is True)
    return {
        "id": role["id"],
        "role": role["id"],
        "polarity": role.get("default_polarity") or "supportive",
        "causal_steps": [f"{role['id']}: {target or focus}"],
        "retrieval_query": " ".join(item for item in (scientific_object or focus, anchors, target) if item).strip() or fallback_query,
        "failure_scope": "whole_sh_core_falsification" if core else "claim_qualification_or_boundary_gap",
        "can_independently_falsify_sh": core,
        "missing_path_blocks_sh": core,
        "evidence_role_family": role.get("family") or "",
        "source": "deterministic_evidence_role_registry",
    }


def evidence_role_retrieval_metadata(role_id: str, primary_mode: str = "") -> dict[str, str]:
    """Translate an epistemic role into retrieval semantics, not a discipline.

    The target lane is deliberately driven by the evidence contribution.  For
    example, a systematic-error paper is measurement evidence even when the
    surrounding project is cosmology, ecology, or epidemiology.
    """
    role = EVIDENCE_ROLE_REGISTRY.get(_role_id(role_id), {})
    family = str(role.get("family") or "")
    if family.startswith("observational") or family == "measurement":
        return {"evidence_kind": "association", "target_lane": "OBSERVATIONAL_COHORT_EVIDENCE"}
    if family.startswith("theoretical") or family.startswith("formal"):
        return {"evidence_kind": "theoretical_framework", "target_lane": "THEORETICAL_OR_FORMAL_EVIDENCE"}
    if family.startswith("simulation"):
        return {"evidence_kind": "experimental_evidence", "target_lane": "COMPUTATIONAL_MODEL_DISCRIMINATION"}
    if family.startswith("engineering"):
        return {"evidence_kind": "predictive_validation", "target_lane": "SURVEILLANCE_SYSTEM_VALIDATION"}
    if family.startswith("descriptive"):
        return {"evidence_kind": "association", "target_lane": "ECOLOGICAL_FIELD_OBSERVATION"}
    if family.startswith("synthesis") or family == "foundation":
        return {"evidence_kind": "theoretical_framework", "target_lane": "SYSTEMATIC_REVIEW_CONTEXT"}
    if family.startswith("experimental") or family == "mechanism":
        return {"evidence_kind": "experimental_evidence", "target_lane": "PENDING_FULLTEXT_TYPE_DIRECTED_EVIDENCE"}
    fallback = {
        "observational_inference": ("association", "OBSERVATIONAL_COHORT_EVIDENCE"),
        "theoretical_derivation": ("theoretical_framework", "THEORETICAL_OR_FORMAL_EVIDENCE"),
        "mathematical_proof": ("theoretical_framework", "THEORETICAL_OR_FORMAL_EVIDENCE"),
        "computational_simulation": ("experimental_evidence", "COMPUTATIONAL_MODEL_DISCRIMINATION"),
        "engineering_validation": ("predictive_validation", "SURVEILLANCE_SYSTEM_VALIDATION"),
    }
    kind, lane = fallback.get(primary_mode, ("association", "OBSERVATIONAL_COHORT_EVIDENCE"))
    return {"evidence_kind": kind, "target_lane": lane}


def evidence_role_time_bucket(role_id: str) -> str:
    """Return the evidence-lifecycle bucket implied by a role, not paper age."""
    role = _role_id(role_id)
    if role in {"historical_baseline_or_foundation", "fundamental_assumption", "definition_and_premise", "prior_theorem_dependency"}:
        return "P_foundational"
    if role in {"evidence_synthesis", "heterogeneity_or_evidence_quality"}:
        return "P_review_or_consensus"
    if role in {"data_release_or_survey", "descriptive_catalog"}:
        return "P_authoritative_data_release"
    if role in {"calibration_or_data_processing", "selection_effect", "systematic_error", "covariance_or_uncertainty"}:
        return "P_systematics_or_reanalysis"
    if role in {"predictive_test", "observable_prediction", "cross_dataset_joint_constraint", "alternative_model_explanation"}:
        return "P_recent_constraint"
    return "P_recent_constraint"


def summarize_project_evidence_role_coverage(sub_hypotheses: list[dict[str, Any]] | Any) -> dict[str, Any]:
    items = [item for item in (sub_hypotheses or []) if isinstance(item, dict)]
    roles: Counter[str] = Counter()
    families: Counter[str] = Counter()
    modes: Counter[str] = Counter()
    per_sh: dict[str, list[str]] = {}
    for index, item in enumerate(items, start=1):
        sub_id = str(item.get("id") or f"SH{index}")
        profile = item.get("epistemic_profile") if isinstance(item.get("epistemic_profile"), dict) else {}
        contract = item.get("evidence_role_contract") if isinstance(item.get("evidence_role_contract"), dict) else {}
        selected = [_role_id(role) for role in contract.get("selected_roles", [])]
        if not selected:
            selected = _path_roles(item.get("evidence_paths"))
        selected = [role for role in selected if role]
        per_sh[sub_id] = selected
        roles.update(selected)
        modes[str(profile.get("primary_mode") or "unresolved")] += 1
        for role in selected:
            families[str((EVIDENCE_ROLE_REGISTRY.get(role) or {}).get("family") or "other")] += 1
    recommendations: list[str] = []
    if len(items) >= 3 and len(families) < 2:
        recommendations.append("Project evidence roles are concentrated in one epistemic family; consider a complementary SH or retrieval path only if it addresses a source-grounded direction.")
    if len(items) >= 4 and not any(family in families for family in ("measurement", "model_comparison", "boundary", "formal_boundary", "theoretical_constraint")):
        recommendations.append("No uncertainty, alternative-model, or validity-boundary role is represented at project level; report this as a gap-generation opportunity when source scope supports it.")
    return {
        "schema_version": "project_epistemic_role_coverage_v1",
        "scope": "project_level_quality_diagnostic",
        "by_role": dict(sorted(roles.items())),
        "by_role_family": dict(sorted(families.items())),
        "by_primary_mode": dict(sorted(modes.items())),
        "roles_by_sub_hypothesis_id": per_sh,
        "non_blocking_recommendations": recommendations,
    }
