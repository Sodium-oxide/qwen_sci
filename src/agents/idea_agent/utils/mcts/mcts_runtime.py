"""Runtime models and helper functions for memory-guided MCTS idea search."""

from __future__ import annotations

import hashlib
import itertools
import json
import math
import random
import re
from copy import deepcopy
from dataclasses import dataclass, field, replace
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set, Tuple
from src.agents.idea_agent.utils.core.json_utils import (
    pretty_json,
    read_json_file,
)
from src.agents.idea_agent.utils.core.response_parsing import parse_json_response
from src.agents.idea_agent.utils.mcts.defect_registry import (
    format_defect_registry,
    profile_skill_defect_tags,
)
from src.agents.idea_agent.utils.mcts.idea_taste_presets import IdeaTastePreset
from src.agents.idea_agent.utils.mcts.skill_parsing import (
    parse_blueprint_step,
    parse_markdown_sections,
    split_frontmatter,
)
from src.agents.idea_agent.utils.mcts.scientific_intervention_ontology import (
    build_scientific_intervention_payload,
    detect_profile_drift,
    format_scientific_intervention_profile_for_prompt,
    get_scientific_intervention_profile,
    get_scientific_object_schema,
    resolve_scientific_intervention_profile,
)
from src.agents.idea_agent.utils.mcts.scientific_rubric import (
    SCIENTIFIC_INTERVENTION_PROFILE_VERSION,
    SCIENTIFIC_RUBRIC_VERSION,
    PROFILE_NOVELTY_AXES,
    format_scientific_rubric_for_prompt,
    profile_score_weights,
)
from src.memory.memory_system.component_taxonomy import extract_component_families
from src.agents.idea_agent.utils.mcts.mcts_helpers import (
    _format_root_domains_for_prompt,
    _clean_component_explanation,
    _coerce_component_name,
    _dedupe_keep_order_strings,
    _filter_component_mapping_to_plan_keys,
    _normalize_component_mapping,
    build_structural_profile,
    clip_text,
    component_inventory_payload,
    normalize_component_explanations,
    parse_component_bundle_payload,
    plan_to_experiment_text,
    plan_to_method_text,
)
from src.agents.idea_agent.utils.prompting.prompt_views import (
    format_evaluator_edit_plan_prompt_view,
    format_evaluator_idea_prompt_view,
)
from src.agents.idea_agent.utils.workflow.idea_contract import (
    normalize_idea_contract,
    normalize_mature_idea,
)
from src.agents.idea_agent.utils.workflow.multimodal_data_anchoring import (
    DATA_ANCHORED_PRIORITY,
    is_data_anchored,
)


HYPOTHESIS_CONTRACT_FIELDS = (
    "direction_mode",
    "direction_summary",
    "central_hypothesis",
    "scientific_object",
    "mechanism_or_relation",
    "intervention_or_transformation",
    "expected_mechanism",
    "discriminating_observation",
    "boundary_or_failure_condition",
    "claim_scope",
    "assumptions",
    "target_gap_ids",
    "gap_alignment",
    "evidence_requirement",
    "evidence_basis",
)

_ROUTE_REQUIRED_CONTRACT_FIELDS = {
    "premise_inversion": ("central_hypothesis",),
    "object_substitution": ("scientific_object",),
    "mechanism_replacement": ("mechanism_or_relation", "expected_mechanism"),
    "representation_shift": ("intervention_or_transformation",),
    "verification_reversal": ("discriminating_observation",),
}


class AtomicEditOp(str, Enum):
    ADD_COMPONENT = "ADD_COMPONENT"
    REMOVE_COMPONENT = "REMOVE_COMPONENT"
    REPLACE_COMPONENT = "REPLACE_COMPONENT"
    REWIRE = "REWIRE"
    ADD_PROTOCOL = "ADD_PROTOCOL"


# Descriptions for each atomic edit operation, used in prompt formatting and skill documentation.
ATOMIC_OP_DESCRIPTIONS: Dict[str, str] = {
    AtomicEditOp.ADD_COMPONENT: "Introduce a new module or sub-module into the architecture. ",
    AtomicEditOp.REMOVE_COMPONENT: "Delete an existing module from the architecture. ",
    AtomicEditOp.REPLACE_COMPONENT: "Swap an existing module with a new implementation. ",
    AtomicEditOp.REWIRE: "Change how two components are connected (data flow, gradient path, or API coupling). ",
    AtomicEditOp.ADD_PROTOCOL: "Attach a validation protocol (regression, ablation, or stress test) to the plan. "
}


def format_op_descriptions(profile_id: Optional[str] = None) -> str:
    """Return a human-readable reference block describing every atomic edit operation."""
    if profile_id and str(profile_id).strip().lower() != "computational_algorithmic":
        return "\n".join(
            [
                "Scientific transformation reference (use the selected profile's native objects directly):",
                "  - ADD_COMPONENT: introduce one object, condition, mechanism, relation, or observation named by the profile.",
                "  - REMOVE_COMPONENT: remove one unsupported or redundant object, assumption, process, or condition.",
                "  - REPLACE_COMPONENT: replace one weak object, assumption, process, or mechanism with a refined one.",
                "  - REWIRE: change a causal relation, derivation, observation mapping, or process relation.",
                "  - ADD_PROTOCOL: attach the evidence, measurement, proof, comparator, or boundary check required by the profile.",
            ]
        )
    lines = ["Atomic edit operation reference:"]
    for op in AtomicEditOp:
        desc = ATOMIC_OP_DESCRIPTIONS.get(op, "No description.")
        lines.append(f"  - {op.value}: {desc}")
    return "\n".join(lines)


def render_profile_evaluation_prompt(prompt: str, profile_id: str) -> str:
    """Remove computational evaluation priors from non-computational prompts."""

    if str(profile_id or "").strip().lower() == "computational_algorithmic":
        return prompt
    replacements = {
        "- Evaluate the candidate using the scientific intervention profile and rubric above. The native contribution may be a material manipulation, biological or clinical causal intervention, environmental condition, engineering process, formal assumption/derivation/counterexample, measurement construct, or algorithmic mechanism.": "- Evaluate the candidate using the scientific intervention profile and rubric above. The native contribution must use the selected profile's object, process, mechanism, relation, observation, intervention, or formal claim.",
        "- Do not treat training signal, loss, backbone, benchmark, or learned model components as universal requirements. For non-computational profiles, judge innovation through the profile's native mechanism, object, observation, comparator, proof, or boundary conditions; missing training machinery is not an innovation defect.": "- Judge innovation through the selected profile's native object, mechanism, relation, observation, comparator, proof, intervention, or boundary conditions.",
        "- If the mature idea above is training-free or inference-time only, penalize candidates that add new training stages, learned controllers, auxiliary losses, or fine-tuning loops without a strong mechanism-level justification. Such drift should usually reduce alignment_score and increase complexity_penalty.": "- Penalize candidates that add unrelated optimization, control, or wrapper machinery without a strong profile-native mechanism justification.",
        "generator, objective, representation, planner, or data path": "scientific mechanism, intervention, relation, observation, or process",
        "- Do not speculate about compute/resource budgeting unless the candidate explicitly makes resource management part of its core mechanism.": "- Do not speculate about implementation resources unless the candidate explicitly makes resource constraints part of its core scientific claim.",
    }
    for source, target in replacements.items():
        prompt = prompt.replace(source, target)
    return prompt

def _synthesize_component_explanation_from_edit(component: str, edit: Optional["ComponentEdit"]) -> str:
    if edit is None:
        return _clean_component_explanation("", fallback_component=component)

    if edit.reason:
        return _clean_component_explanation(edit.reason, fallback_component=component)
    if edit.op == AtomicEditOp.REPLACE_COMPONENT and edit.target:
        return _clean_component_explanation(
            f"Replaces {edit.target} with a stronger implementation for the updated idea.",
            fallback_component=component,
        )
    if edit.op == AtomicEditOp.ADD_COMPONENT:
        return _clean_component_explanation(
            "Adds a targeted capability that was missing in the parent idea.",
            fallback_component=component,
        )
    if edit.details:
        return _clean_component_explanation(edit.details, fallback_component=component)
    return _clean_component_explanation("", fallback_component=component)


def build_child_component_explanations(
    parent_state: Any,
    new_components: Sequence[str],
    plan: "EditPlan",
    instantiated: Optional[Dict[str, Any]] = None,
) -> Dict[str, str]:
    parent_lookup = normalize_component_explanations(
        getattr(parent_state, "components", []),
        getattr(parent_state, "component_explanations", {}),
    )
    payload_lookup = normalize_component_explanations(
        list((instantiated or {}).get("component_role_explanations", {}).keys())
        if isinstance((instantiated or {}).get("component_role_explanations"), dict)
        else [],
        (instantiated or {}).get("component_role_explanations", {}),
    )
    edit_lookup: Dict[str, ComponentEdit] = {}
    for edit in getattr(plan, "component_edits", []) or []:
        name = _coerce_component_name(getattr(edit, "component", ""))
        if name:
            edit_lookup[name] = edit

    explanations: Dict[str, str] = {}
    for component in new_components:
        name = str(component).strip()
        if not name:
            continue
        if name in parent_lookup:
            explanations[name] = parent_lookup[name]
            continue
        if name in payload_lookup:
            explanations[name] = payload_lookup[name]
            continue
        explanations[name] = _synthesize_component_explanation_from_edit(
            name,
            edit_lookup.get(name),
        )
    return explanations


@dataclass
class ComponentEdit:
    op: AtomicEditOp
    component: str
    target: str = ""
    condition: str = ""
    details: str = ""
    reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "op": self.op.value,
            "component": _coerce_component_name(self.component),
            "target": _coerce_component_name(self.target),
            "condition": self.condition,
            "details": self.details,
            "reason": self.reason,
        }


@dataclass
class ValidationProtocol:
    regression_tests: List[str] = field(default_factory=list)
    ablation_tests: List[str] = field(default_factory=list)
    stress_tests: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "regression_tests": self.regression_tests,
            "ablation_tests": self.ablation_tests,
            "stress_tests": self.stress_tests,
        }


@dataclass
class EditPlan:
    skill_name: str
    objective: str
    target_defects: List[str]
    component_edits: List[ComponentEdit]
    validation: ValidationProtocol
    guardrails: List[str]
    memory_refs: List[str]
    compile_notes: str
    profile_id: str = ""
    profile_rendering_id: str = ""
    preferred_operations: List[str] = field(default_factory=list)
    scientific_object_schema: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "skill_name": self.skill_name,
            "objective": self.objective,
            "target_defects": self.target_defects,
            "component_edits": [edit.to_dict() for edit in self.component_edits],
            "validation": self.validation.to_dict(),
            "guardrails": self.guardrails,
            "memory_refs": self.memory_refs,
            "compile_notes": self.compile_notes,
            "profile_id": self.profile_id,
            "profile_rendering_id": self.profile_rendering_id,
            "preferred_operations": self.preferred_operations,
            "scientific_object_schema": self.scientific_object_schema,
        }


@dataclass
class EditOperatorSkill:
    name: str
    description: str
    structural_mode: str
    scope_preference: str
    requires_control_centered_parent: bool
    defects: List[str] = field(default_factory=list)
    guardrails: List[str] = field(default_factory=list)
    atomic_blueprint: List[str] = field(default_factory=list)
    required_protocols: List[str] = field(default_factory=list)
    avoid_combinations: List[str] = field(default_factory=list)
    execution_logic: List[str] = field(default_factory=list)
    source_path: str = ""
    profile_renderings: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    rendered_profile_id: str = ""
    allowed_object_types: List[str] = field(default_factory=list)
    preferred_operations: List[str] = field(default_factory=list)
    profile_rendering_id: str = ""

    def to_prompt_line(self) -> str:
        defects = ", ".join(self.defects) if self.defects else "unspecified"
        blueprint = ", ".join(self.atomic_blueprint) if self.atomic_blueprint else "none"
        guardrails = ", ".join(self.guardrails) if self.guardrails else "none"
        exec_logic = " | ".join(self.execution_logic) if self.execution_logic else "none"
        profile = f" | profile={self.rendered_profile_id}" if self.rendered_profile_id else ""
        native_ops = (
            f" | native_operations={','.join(self.preferred_operations)}"
            if self.preferred_operations
            else ""
        )
        native_objects = (
            f" | native_objects={','.join(self.allowed_object_types)}"
            if self.allowed_object_types
            else ""
        )
        return (
            f"- {self.name}: {self.description} | defects={defects} "
            f"| blueprint={blueprint} | guardrails={guardrails} "
            f"| execution_logic={exec_logic}{profile}{native_ops}{native_objects}"
        )


@dataclass
class SkillUsagePrior:
    attempts: int = 0
    successes: int = 0
    reward_ema: float = 0.5
    prior: float = 0.5
    rule_constraints: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "attempts": self.attempts,
            "successes": self.successes,
            "reward_ema": self.reward_ema,
            "prior": self.prior,
            "rule_constraints": self.rule_constraints,
        }


@dataclass
class SkillSelectionCandidate:
    skill: EditOperatorSkill
    defect_score: float
    prior_score: float
    preset_bias: float
    structure_fit: float
    structure_reason: str
    selection_total: float
    attempts: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "skill_name": self.skill.name,
            "defect_score": self.defect_score,
            "prior_score": self.prior_score,
            "preset_bias": self.preset_bias,
            "structure_fit": self.structure_fit,
            "structure_reason": self.structure_reason,
            "selection_total": self.selection_total,
            "attempts": self.attempts,
        }


@dataclass
class MemorySnippet:
    identifier: str
    title: str
    detail: str
    tags: List[str] = field(default_factory=list)

    def to_prompt_line(self) -> str:
        tags_str = f" tags={','.join(self.tags)}" if self.tags else ""
        return f"[{self.identifier}] {self.title}{tags_str}: {self.detail}"


@dataclass
class MemoryBundle:
    field_knowledge: List[MemorySnippet] = field(default_factory=list)
    anti_patterns: List[MemorySnippet] = field(default_factory=list)
    fix_recipes: List[MemorySnippet] = field(default_factory=list)

    def to_prompt_block(self) -> str:
        sections: List[str] = []
        if self.field_knowledge:
            sections.append("== Field Knowledge ==")
            sections.extend(snippet.to_prompt_line() for snippet in self.field_knowledge)
        if self.anti_patterns:
            sections.append("== Anti-patterns ==")
            sections.extend(snippet.to_prompt_line() for snippet in self.anti_patterns)
        if self.fix_recipes:
            sections.append("== Fix Recipes ==")
            sections.extend(snippet.to_prompt_line() for snippet in self.fix_recipes)
        if not sections:
            return "No validated memory snippets matched. Rely on analysis context only."
        return "\n".join(sections)

    def referenced_ids(self) -> List[str]:
        ids: List[str] = []
        for bank in (self.field_knowledge, self.anti_patterns, self.fix_recipes):
            ids.extend(snippet.identifier for snippet in bank)
        return ids


DEFAULT_SKILL_TEMPLATES_PATH = (
    Path(__file__).resolve().parents[2]
    / "agent"
    / "skills"
    / "DEFAULT_SKILL_TEMPLATES.json"
)


def _load_default_skill_templates(path: Path) -> Dict[str, Dict[str, Any]]:
    if not path.exists():
        return {}
    payload = read_json_file(path)
    if not isinstance(payload, dict):
        return {}
    normalized: Dict[str, Dict[str, Any]] = {}
    for key, value in payload.items():
        name = str(key).strip()
        if not name or not isinstance(value, dict):
            continue
        normalized[name] = value
    return normalized


DEFAULT_SKILL_TEMPLATES: Dict[str, Dict[str, Any]] = _load_default_skill_templates(
    DEFAULT_SKILL_TEMPLATES_PATH
)

ANTI_PATTERN_CONSTRAINTS: List[str] = [
    "No feature dumping: every component edit must map to a measured defect.",
    "Use the lightest validation suite that can falsify the core mechanism; do not let protocol bulk replace mechanism work.",
    "Prefer mechanism clarity over loosely coupled add-ons.",
]


_PROFILE_SKILL_TOKEN_MAPS: Dict[str, Dict[str, str]] = {
    "physical_materials_chemical": {
        "weak_internal_component": "weak_process_or_mechanism",
        "refined_internal_component": "refined_process_or_mechanism",
        "alternative_path_module": "competing_mechanism_or_phase",
        "failure_regime_interface": "mechanism_discriminating_observation",
        "weak_block": "weak_process_or_composition",
        "modular_block": "localized_process_or_mechanism",
        "downstream_interface": "property_or_performance_endpoint",
        "scale_consistency_module": "structure_process_property_link",
        "scale_interface": "cross_scale_characterization",
        "flat_pipeline": "uncalibrated_process_structure_relation",
        "hierarchical_pipeline": "structure_process_property_decomposition",
        "execution_path": "process_observation_path",
        "feedback_monitor": "characterization_feedback",
        "adaptation_rule": "process_condition_update",
        "theory_transfer_module": "transferred_material_mechanism",
        "core_objective": "target_property_or_mechanism",
        "speculative_executor": "exploratory_process_condition",
        "repair_handler": "recovery_or_reprocessing_condition",
    },
    "life_molecular_mechanistic": {
        "weak_internal_component": "weak_pathway_or_assay",
        "refined_internal_component": "refined_mediator_or_perturbation",
        "alternative_path_module": "competing_biological_pathway",
        "failure_regime_interface": "mechanism_discriminating_assay",
        "weak_block": "weak_intervention_or_mediator",
        "modular_block": "localized_perturbation_pathway",
        "downstream_interface": "phenotype_or_endpoint",
        "scale_consistency_module": "mediator_phenotype_link",
        "scale_interface": "multi_level_assay",
        "flat_pipeline": "unresolved_perturbation_mediator_relation",
        "hierarchical_pipeline": "system_pathway_phenotype_decomposition",
        "execution_path": "perturbation_observation_path",
        "feedback_monitor": "assay_response_observation",
        "adaptation_rule": "dose_or_condition_update",
        "theory_transfer_module": "transferred_biological_mechanism",
        "core_objective": "target_phenotype_or_pathway",
        "speculative_executor": "exploratory_perturbation",
        "repair_handler": "recovery_or_control_condition",
    },
    "clinical_health": {
        "weak_internal_component": "weak_intervention_or_mediator",
        "refined_internal_component": "refined_intervention_or_mediator",
        "alternative_path_module": "competing_causal_explanation",
        "failure_regime_interface": "comparator_or_counterfactual",
        "weak_block": "weak_intervention_or_measurement",
        "modular_block": "targeted_intervention_or_mediator",
        "downstream_interface": "clinical_endpoint",
        "scale_consistency_module": "population_endpoint_mediation_link",
        "scale_interface": "cohort_subgroup_boundary",
        "flat_pipeline": "unresolved_intervention_outcome_relation",
        "hierarchical_pipeline": "population_intervention_mediator_endpoint_decomposition",
        "execution_path": "intervention_measurement_path",
        "feedback_monitor": "outcome_measurement",
        "adaptation_rule": "care_or_intervention_update",
        "theory_transfer_module": "transferred_causal_mechanism",
        "core_objective": "clinical_endpoint_or_utility",
        "speculative_executor": "pilot_intervention_condition",
        "repair_handler": "safety_or_escalation_condition",
    },
    "earth_environment_agro": {
        "weak_internal_component": "weak_forcing_or_process",
        "refined_internal_component": "refined_forcing_or_process",
        "alternative_path_module": "competing_regime_or_process",
        "failure_regime_interface": "spatiotemporal_regime_boundary",
        "weak_block": "weak_observation_or_attribution",
        "modular_block": "localized_process_or_observation",
        "downstream_interface": "response_or_endpoint",
        "scale_consistency_module": "spatiotemporal_scale_link",
        "scale_interface": "observation_scale_alignment",
        "flat_pipeline": "unresolved_forcing_process_response_relation",
        "hierarchical_pipeline": "forcing_process_response_decomposition",
        "execution_path": "forcing_observation_path",
        "feedback_monitor": "observation_response_update",
        "adaptation_rule": "scenario_or_management_update",
        "theory_transfer_module": "transferred_earth_system_mechanism",
        "core_objective": "response_or_attribution_claim",
        "speculative_executor": "exploratory_scenario",
        "repair_handler": "observation_or_scenario_recovery",
    },
    "energy_engineering_systems": {
        "weak_internal_component": "weak_design_or_mechanism",
        "refined_internal_component": "refined_design_or_mechanism",
        "alternative_path_module": "alternate_operating_or_failure_regime",
        "failure_regime_interface": "operating_state_boundary",
        "weak_block": "weak_design_or_control_condition",
        "modular_block": "localized_design_or_process",
        "downstream_interface": "performance_or_safety_readout",
        "scale_consistency_module": "component_system_link",
        "scale_interface": "system_constraint_boundary",
        "flat_pipeline": "uncalibrated_design_mechanism_relation",
        "hierarchical_pipeline": "component_process_system_decomposition",
        "execution_path": "operating_state_path",
        "feedback_monitor": "sensor_or_performance_readout",
        "adaptation_rule": "operating_condition_update",
        "theory_transfer_module": "transferred_engineering_mechanism",
        "core_objective": "design_or_safety_claim",
        "speculative_executor": "recoverable_operating_condition",
        "repair_handler": "fault_recovery_condition",
    },
    "formal_theoretical": {
        "weak_internal_component": "weak_assumption_or_derivation",
        "refined_internal_component": "refined_assumption_or_derivation",
        "alternative_path_module": "counterexample_or_alternative_derivation",
        "failure_regime_interface": "validity_domain_boundary",
        "weak_block": "weak_proof_obligation",
        "modular_block": "localized_proof_obligation",
        "downstream_interface": "target_relation",
        "scale_consistency_module": "multi_level_formal_relation",
        "scale_interface": "validity_domain",
        "flat_pipeline": "unresolved_assumption_derivation_relation",
        "hierarchical_pipeline": "object_assumption_relation_decomposition",
        "execution_path": "derivation_or_construction_path",
        "feedback_monitor": "counterexample_check",
        "adaptation_rule": "conjecture_refinement",
        "theory_transfer_module": "transferred_formal_invariant",
        "core_objective": "target_proposition_or_relation",
        "speculative_executor": "candidate_construction",
        "repair_handler": "counterexample_repair_obligation",
    },
    "generic_scientific": {
        "weak_internal_component": "weak_candidate_mechanism",
        "refined_internal_component": "refined_candidate_mechanism",
        "alternative_path_module": "competing_explanation",
        "failure_regime_interface": "boundary_condition",
        "weak_block": "weak_manipulable_condition",
        "modular_block": "localized_scientific_intervention",
        "downstream_interface": "observable_or_endpoint",
        "scale_consistency_module": "cross_scale_relation",
        "scale_interface": "validity_domain",
        "flat_pipeline": "unresolved_mechanism_relation",
        "hierarchical_pipeline": "object_mechanism_observation_decomposition",
        "execution_path": "intervention_observation_path",
        "feedback_monitor": "measurement_observation",
        "adaptation_rule": "condition_update",
        "theory_transfer_module": "transferred_scientific_mechanism",
        "core_objective": "target_scientific_relation",
        "speculative_executor": "exploratory_intervention",
        "repair_handler": "recovery_condition",
    },
}


_PROFILE_SKILL_DESCRIPTION_PREFIXES: Dict[str, str] = {
    "physical_materials_chemical": "materials/process-native",
    "life_molecular_mechanistic": "biological/mechanistic",
    "clinical_health": "clinical/causal",
    "earth_environment_agro": "earth-system/observational",
    "energy_engineering_systems": "engineering/system",
    "formal_theoretical": "formal/theoretical",
    "generic_scientific": "domain-neutral scientific",
}


_PROFILE_DISABLED_SKILLS: Dict[str, Set[str]] = {
    "formal_theoretical": {"speculative-execution-with-repair"},
    "clinical_health": {"speculative-execution-with-repair"},
    "earth_environment_agro": {"speculative-execution-with-repair"},
}


_PROFILE_ALLOWED_SKILLS: Dict[str, Set[str]] = {
    "physical_materials_chemical": {
        "mechanism-commit-innovation",
        "alternative-path-contrast",
        "feedback-closed-loop",
        "multi-scale-coordinator",
        "theory-transfer-injection",
    },
    "life_molecular_mechanistic": {
        "mechanism-commit-innovation",
        "alternative-path-contrast",
        "feedback-closed-loop",
        "multi-scale-coordinator",
        "theory-transfer-injection",
    },
    "clinical_health": {
        "mechanism-commit-innovation",
        "alternative-path-contrast",
        "feedback-closed-loop",
        "theory-transfer-injection",
    },
    "earth_environment_agro": {
        "mechanism-commit-innovation",
        "alternative-path-contrast",
        "feedback-closed-loop",
        "multi-scale-coordinator",
        "theory-transfer-injection",
    },
    "energy_engineering_systems": {
        "mechanism-commit-innovation",
        "alternative-path-contrast",
        "feedback-closed-loop",
        "multi-scale-coordinator",
        "theory-transfer-injection",
    },
    "formal_theoretical": {
        "mechanism-commit-innovation",
        "alternative-path-contrast",
        "hierarchical-decomposition",
        "theory-transfer-injection",
    },
    "generic_scientific": {
        "mechanism-commit-innovation",
        "alternative-path-contrast",
        "feedback-closed-loop",
        "multi-scale-coordinator",
        "theory-transfer-injection",
    },
}


def _profile_skill_description(skill_name: str, profile_id: str) -> str:
    prefix = _PROFILE_SKILL_DESCRIPTION_PREFIXES.get(profile_id, "profile-native scientific")
    descriptions = {
        "mechanism-commit-innovation": "Commit to one concrete mechanism-level intervention in the selected scientific object.",
        "alternative-path-contrast": "Contrast one competing mechanism, explanation, or validity regime.",
        "surgical-modularity": "Perform one localized intervention on a process, relation, object, or mechanism.",
        "multi-scale-coordinator": "Link the relevant scales, regimes, or levels of the scientific relation.",
        "hierarchical-decomposition": "Decompose the scientific object, assumptions, process, or evidence obligation across explicit levels.",
        "feedback-closed-loop": "Use observations or counterexamples to refine the intervention or scientific relation.",
        "theory-transfer-injection": "Transfer one principle or invariant into the selected scientific mechanism or relation.",
        "speculative-execution-with-repair": "Explore a recoverable alternative condition and state its repair or recovery boundary.",
    }
    return f"{prefix} {descriptions.get(skill_name, 'scientific intervention refinement')}"


class SkillCatalog:
    def __init__(self, skill_root: Optional[Path] = None) -> None:
        if skill_root is None:
            skill_root = (
                Path(__file__).resolve().parents[2]
                / "agent"
                / "skills"
                / "edit_operator_skills"
            )
        self.skill_root = skill_root
        self.skills: Dict[str, EditOperatorSkill] = {}
        self.priors: Dict[str, SkillUsagePrior] = {}
        self._load()

    def _load(self) -> None:
        loaded: Dict[str, EditOperatorSkill] = {}
        if self.skill_root.exists():
            for skill_file in sorted(self.skill_root.glob("*/SKILL.md")):
                parsed = self._parse_skill_file(skill_file)
                if parsed:
                    loaded[parsed.name] = parsed
        for name, payload in DEFAULT_SKILL_TEMPLATES.items():
            if name in loaded:
                continue
            loaded[name] = EditOperatorSkill(
                name=name,
                description=payload["description"],
                structural_mode=payload["structural_mode"],
                scope_preference=payload["scope_preference"],
                requires_control_centered_parent=bool(payload["requires_control_centered_parent"]),
                defects=list(payload.get("defects", [])),
                guardrails=list(payload.get("guardrails", [])),
                atomic_blueprint=list(payload.get("atomic_blueprint", [])),
                required_protocols=list(payload.get("required_protocols", [])),
                avoid_combinations=list(payload.get("avoid_combinations", [])),
                execution_logic=list(payload.get("execution_logic", [])),
                source_path="builtin-default",
                profile_renderings=(
                    dict(payload.get("profile_renderings"))
                    if isinstance(payload.get("profile_renderings"), dict)
                    else {}
                ),
            )
        self.skills = loaded
        for name in self.skills:
            self.priors.setdefault(name, SkillUsagePrior())

    def _parse_skill_file(self, path: Path) -> Optional[EditOperatorSkill]:
        text = path.read_text(encoding="utf-8")
        frontmatter, body = split_frontmatter(text)
        name = str(frontmatter.get("name", "")).strip() or path.parent.name
        description = str(frontmatter.get("description", "")).strip()
        sections = parse_markdown_sections(body)
        template = DEFAULT_SKILL_TEMPLATES.get(name, {})
        structural_mode_entries = sections.get("structural_mode", [])
        scope_preference_entries = sections.get("scope_preference", [])
        requires_control_centered_entries = sections.get("requires_control_centered_parent", [])
        structural_mode = (
            structural_mode_entries[0].strip()
            if structural_mode_entries and str(structural_mode_entries[0]).strip()
            else str(template.get("structural_mode", "local_refinement")).strip()
        )
        scope_preference = (
            scope_preference_entries[0].strip()
            if scope_preference_entries and str(scope_preference_entries[0]).strip()
            else str(template.get("scope_preference", "existing_subsystem")).strip()
        )
        if (
            requires_control_centered_entries
            and str(requires_control_centered_entries[0]).strip()
        ):
            requires_control_centered_parent = (
                requires_control_centered_entries[0].strip().lower() == "true"
            )
        else:
            requires_control_centered_parent = bool(
                template.get("requires_control_centered_parent", False)
            )
        defects = sections.get("defect_tags", []) or sections.get("defects", [])
        guardrails = sections.get("guardrails", [])
        atomic_blueprint = sections.get("atomic_blueprint", [])
        required_protocols = sections.get("required_protocols", [])
        avoid_combinations = sections.get("avoid_combinations", [])
        execution_logic = sections.get("execution_logic", [])
        if not description:
            description = str(template.get("description", ""))
        if not defects:
            defects = list(template.get("defects", []))
        if not guardrails:
            guardrails = list(template.get("guardrails", []))
        if not atomic_blueprint:
            atomic_blueprint = list(template.get("atomic_blueprint", []))
        if not required_protocols:
            required_protocols = list(template.get("required_protocols", []))
        if not execution_logic:
            execution_logic = list(template.get("execution_logic", []))
        if not description:
            return None

        return EditOperatorSkill(
            name=name,
            description=description,
            structural_mode=structural_mode,
            scope_preference=scope_preference,
            requires_control_centered_parent=requires_control_centered_parent,
            defects=defects,
            guardrails=guardrails,
            atomic_blueprint=atomic_blueprint,
            required_protocols=required_protocols,
            avoid_combinations=avoid_combinations,
            execution_logic=execution_logic,
            source_path=str(path),
            profile_renderings=(
                dict(template.get("profile_renderings"))
                if isinstance(template.get("profile_renderings"), dict)
                else {}
            ),
        )

    def list_skills(self) -> List[EditOperatorSkill]:
        return [self.skills[key] for key in sorted(self.skills.keys())]

    def render_skill_for_profile(
        self,
        skill: EditOperatorSkill | str,
        profile_id: str,
        object_schema: Optional[Dict[str, Any]] = None,
    ) -> EditOperatorSkill:
        """Render a skill using the selected profile's native object vocabulary.

        The atomic operation names remain legacy-compatible.  Only their
        placeholders, descriptions, and guardrails are rendered, so existing
        parsers and persisted edit plans continue to work.
        """

        base = self.skills[skill] if isinstance(skill, str) else skill
        normalized_profile = str(profile_id or "generic_scientific").strip().lower()
        explicit_rendering = base.profile_renderings.get(normalized_profile)
        if not isinstance(explicit_rendering, dict):
            explicit_rendering = {}

        def schema_payload(value: Any) -> Dict[str, Any]:
            if isinstance(value, dict):
                return value
            if hasattr(value, "to_payload"):
                rendered = value.to_payload()
                return rendered if isinstance(rendered, dict) else {}
            return {}

        if normalized_profile == "computational_algorithmic":
            schema = schema_payload(object_schema)
            if not schema:
                schema_spec = get_scientific_object_schema(normalized_profile)
                schema = schema_spec.to_payload() if schema_spec is not None else {}
            rendered = replace(
                base,
                rendered_profile_id=normalized_profile,
                profile_rendering_id=f"{base.name}:{normalized_profile}:v1",
                allowed_object_types=list(schema.get("object_types") or []),
                preferred_operations=list(schema.get("allowed_operations") or []),
            )
            if explicit_rendering:
                rendered = replace(rendered, **{
                    key: value for key, value in explicit_rendering.items()
                    if key in {"description", "structural_mode", "scope_preference", "guardrails", "atomic_blueprint", "required_protocols", "avoid_combinations", "execution_logic", "allowed_object_types", "preferred_operations"}
                })
            return rendered

        if normalized_profile not in _PROFILE_SKILL_TOKEN_MAPS:
            normalized_profile = "generic_scientific"
        schema = schema_payload(object_schema)
        if not schema:
            schema_spec = get_scientific_object_schema(normalized_profile)
            schema = schema_spec.to_payload() if schema_spec is not None else {}
        token_map = _PROFILE_SKILL_TOKEN_MAPS[normalized_profile]

        def render_text(value: str) -> str:
            rendered = str(value or "")
            for source, target in token_map.items():
                rendered = rendered.replace(source, target)
            return rendered

        native_guardrails = [
            "Use profile-native scientific objects and operations; do not recast the intervention as software architecture by default.",
            "Keep the claim delta, mechanism delta, evidence obligation, and boundary condition explicit.",
        ]
        rendered = replace(
            base,
            description=_profile_skill_description(base.name, normalized_profile),
            guardrails=[render_text(item) for item in base.guardrails] + native_guardrails,
            atomic_blueprint=[render_text(item) for item in base.atomic_blueprint],
            required_protocols=list(base.required_protocols),
            execution_logic=[render_text(item) for item in base.execution_logic],
            rendered_profile_id=normalized_profile,
            profile_rendering_id=f"{base.name}:{normalized_profile}:v1",
            allowed_object_types=list(schema.get("object_types") or []),
            preferred_operations=list(schema.get("allowed_operations") or []),
        )
        if explicit_rendering:
            rendered = replace(rendered, **{
                key: value for key, value in explicit_rendering.items()
                if key in {"description", "structural_mode", "scope_preference", "guardrails", "atomic_blueprint", "required_protocols", "avoid_combinations", "execution_logic", "allowed_object_types", "preferred_operations"}
            })
        return rendered

    def format_for_prompt(
        self,
        skills: Optional[Sequence[EditOperatorSkill]] = None,
        *,
        profile_id: Optional[str] = None,
        object_schema: Optional[Dict[str, Any]] = None,
    ) -> str:
        chosen = list(skills) if skills is not None else self.list_skills()
        if profile_id:
            normalized_profile = str(profile_id).strip().lower()
            allowed_skills = _PROFILE_ALLOWED_SKILLS.get(normalized_profile)
            if allowed_skills is not None:
                chosen = [skill for skill in chosen if skill.name in allowed_skills]
            chosen = [
                self.render_skill_for_profile(skill, profile_id, object_schema)
                for skill in chosen
            ]
        if not chosen:
            return "No edit-operator skills available."
        op_ref = format_op_descriptions(profile_id)
        skill_lines = "\n".join(skill.to_prompt_line() for skill in chosen)
        return f"{op_ref}\n\nAvailable edit-operator skills:\n{skill_lines}"

    def render_for_profile(
        self,
        skill: EditOperatorSkill | str,
        profile_id: str,
        object_schema: Optional[Dict[str, Any]] = None,
    ) -> EditOperatorSkill:
        """Compatibility alias for callers using the shorter renderer name."""

        return self.render_skill_for_profile(skill, profile_id, object_schema)

    def render_references_for_prompt(self, skill_name: str) -> str:
        skill = self.skills[skill_name]
        if skill.source_path == "builtin-default":
            return "None."
        reference_dir = Path(skill.source_path).parent / "references"
        if not reference_dir.exists():
            return "None."
        sections: List[str] = []
        for reference_file in sorted(reference_dir.glob("*.md")):
            content = reference_file.read_text(encoding="utf-8").strip()
            if content:
                sections.append(f"== {reference_file.name} ==\n{content}")
        return "\n\n".join(sections) if sections else "None."

    def select_skills(
        self,
        defect_tags: Sequence[str],
        max_children: int,
        structural_profile: Dict[str, Any],
        preset: Optional[IdeaTastePreset] = None,
        profile_id: Optional[str] = None,
    ) -> List[SkillSelectionCandidate]:
        defects = {str(tag).strip().lower() for tag in defect_tags if str(tag).strip()}
        if not defects:
            defects = {"unexplored_gap"}

        preset_bias_map = dict(getattr(preset, "skill_bias", {}) or {})
        scored: List[SkillSelectionCandidate] = []
        disabled_skills = _PROFILE_DISABLED_SKILLS.get(
            str(profile_id or "").strip().lower(),
            set(),
        )
        normalized_profile = str(profile_id or "").strip().lower()
        allowed_skills = _PROFILE_ALLOWED_SKILLS.get(normalized_profile)
        for skill in self.skills.values():
            if skill.name in disabled_skills or (
                allowed_skills is not None and skill.name not in allowed_skills
            ):
                continue
            skill_defects = {d.lower() for d in skill.defects}
            skill_defects.update(
                profile_skill_defect_tags(profile_id, skill.name)
            )
            overlap = len(defects & skill_defects)
            defect_score = overlap / max(1, len(defects))
            prior_state = self.priors.get(skill.name, SkillUsagePrior())
            prior = prior_state.prior
            attempts = max(0, int(prior_state.attempts))
            raw_preset_bias = preset_bias_map.get(skill.name, 0.0)
            try:
                preset_bias = max(0.0, min(1.0, float(raw_preset_bias)))
            except (TypeError, ValueError):
                preset_bias = 0.0
            structure_fit, structure_reason = self._structure_fit(skill, structural_profile)
            if structure_fit == 0.0:
                continue
            total = (
                0.60 * defect_score
                + 0.20 * prior
                + 0.20 * preset_bias
            ) * structure_fit
            scored.append(
                SkillSelectionCandidate(
                    skill=skill,
                    defect_score=defect_score,
                    prior_score=prior,
                    preset_bias=preset_bias,
                    structure_fit=structure_fit,
                    structure_reason=structure_reason,
                    selection_total=total,
                    attempts=attempts,
                )
            )

        scored.sort(key=lambda item: (-item.selection_total, -item.defect_score, item.skill.name))
        max_children = max(1, int(max_children))
        if max_children == 1:
            picked = [scored[0]] if scored else []
        else:
            exploit_count = min(len(scored), max(0, max_children - 1))
            picked = list(scored[:exploit_count])
            remaining = scored[exploit_count:]
            if remaining and len(picked) < max_children:
                eligible = [entry for entry in remaining if float(entry.defect_score) > 0.0]
                if eligible:
                    weights = [
                        float(entry.defect_score)
                        * (1.0 + 1.0 / math.sqrt(float(entry.attempts) + 1.0))
                        for entry in eligible
                    ]
                    picked.append(random.choices(eligible, weights=weights, k=1)[0])
                else:
                    picked.append(random.choice(remaining))
        if not picked:
            return scored[: max(1, max_children)]
        return picked

    def _scope_fit(self, scope_preference: str, scope_kind: str) -> float:
        if scope_preference == scope_kind:
            return 1.0
        if {scope_preference, scope_kind} <= {"existing_component", "existing_subsystem"}:
            return 0.85
        if {scope_preference, scope_kind} <= {"execution_path", "broad_architecture"}:
            return 0.75
        if scope_preference == "core_objective" and scope_kind in {
            "existing_subsystem",
            "execution_path",
            "broad_architecture",
        }:
            return 0.7
        return 0.0

    def _structure_fit(
        self,
        skill: EditOperatorSkill,
        structural_profile: Dict[str, Any],
    ) -> tuple[float, str]:
        if (
            skill.requires_control_centered_parent
            and not bool(structural_profile["control_centered"])
            and str(structural_profile.get("profile_id") or "").strip().lower()
            == "computational_algorithmic"
        ):
            return 0.0, "requires_control_centered_parent"

        scope_kind = str(structural_profile["scope_kind"])
        fit = self._scope_fit(skill.scope_preference, scope_kind)
        profile_id = str(structural_profile.get("profile_id") or "").strip().lower()
        if (
            fit == 0.0
            and profile_id != "computational_algorithmic"
            and skill.structural_mode == "feedback_loop"
            and scope_kind == "existing_subsystem"
        ):
            fit = 0.85
        if fit == 0.0:
            return 0.0, "scope_mismatch"

        if skill.structural_mode == "path_branching" and scope_kind == "existing_component":
            return 0.0, "path_branching_out_of_scope"
        if skill.structural_mode == "feedback_loop" and bool(structural_profile["training_free_like"]):
            return 0.0, "feedback_loop_out_of_scope"
        if skill.structural_mode == "path_branching" and not bool(structural_profile["has_multi_path_shape"]):
            return fit * 0.75, "scope_only"
        return fit, "aligned"

    def compile_plan(
        self,
        skill: EditOperatorSkill,
        parent_title: str,
        parent_components: Sequence[str],
        target_defects: Sequence[str],
        memory_refs: Sequence[str],
        *,
        profile_id: str = "",
        object_schema: Optional[Dict[str, Any]] = None,
    ) -> EditPlan:
        if isinstance(object_schema, dict):
            normalized_object_schema = dict(object_schema)
        elif hasattr(object_schema, "to_payload"):
            rendered_schema = object_schema.to_payload()
            normalized_object_schema = (
                dict(rendered_schema) if isinstance(rendered_schema, dict) else {}
            )
        else:
            normalized_object_schema = {}
        parsed_steps = [parse_blueprint_step(step) for step in skill.atomic_blueprint]
        parsed_steps = [step for step in parsed_steps if step is not None]

        component_edits: List[ComponentEdit] = []
        validation = ValidationProtocol()

        required_protocols = {
            token.lower().strip()
            for token in skill.required_protocols
            if token and token.strip()
        }

        for step in parsed_steps:
            op = step["op"]
            if op == AtomicEditOp.ADD_PROTOCOL.value:
                protocols = step.get("protocols", [])
                for protocol in protocols:
                    required_protocols.add(protocol.lower().strip())
                continue
            component_edits.append(
                ComponentEdit(
                    op=AtomicEditOp(op),
                    component=step.get("component", ""),
                    target=step.get("target", ""),
                    condition=step.get("condition", ""),
                    details=step.get("details", ""),
                )
            )

        if not required_protocols:
            required_protocols = {"ablation"}

        for protocol in sorted(required_protocols):
            test_text = _default_protocol_text(protocol, skill.name, parent_title, target_defects)
            if protocol == "regression":
                validation.regression_tests.append(test_text)
            elif protocol == "ablation":
                validation.ablation_tests.append(test_text)
            else:
                validation.stress_tests.append(test_text)
            component_edits.append(
                ComponentEdit(
                    op=AtomicEditOp.ADD_PROTOCOL,
                    component=protocol,
                    details=test_text,
                )
            )

        objective_defect = next(iter(target_defects), "unspecified_defect")
        plan = EditPlan(
            skill_name=skill.name,
            objective=f"Use {skill.name} to address {objective_defect}",
            target_defects=[str(tag) for tag in target_defects] or skill.defects[:1] or ["unspecified_defect"],
            component_edits=component_edits,
            validation=validation,
            guardrails=list(skill.guardrails),
            memory_refs=[str(ref) for ref in memory_refs][:6],
            compile_notes=(
                f"Compiled from skill '{skill.name}' with blueprint ops={len(skill.atomic_blueprint)}; "
                f"source={skill.source_path or 'builtin'}"
            ),
            profile_id=str(profile_id or skill.rendered_profile_id or ""),
            profile_rendering_id=str(skill.profile_rendering_id or ""),
            preferred_operations=list(skill.preferred_operations),
            scientific_object_schema=normalized_object_schema,
        )
        return plan

    def update_prior(
        self,
        skill_name: str,
        reward: float,
        feedback: str,
        failure_modes: Sequence[str],
        success_threshold: float = 0.6,
    ) -> SkillUsagePrior:
        prior = self.priors.setdefault(skill_name, SkillUsagePrior())
        prior.attempts += 1
        clipped_reward = max(0.0, min(1.0, reward))
        if clipped_reward >= max(0.0, min(1.0, success_threshold)):
            prior.successes += 1
        prior.reward_ema = 0.8 * prior.reward_ema + 0.2 * clipped_reward
        beta_mean = (prior.successes + 1.0) / (prior.attempts + 2.0)
        prior.prior = 0.55 * beta_mean + 0.45 * prior.reward_ema

        for failure in failure_modes:
            text = str(failure).strip()
            if not text:
                continue
            rule = f"Avoid failure mode: {text}"
            if rule not in prior.rule_constraints:
                prior.rule_constraints.append(rule)
        prior.rule_constraints = prior.rule_constraints[:8]
        return prior



def _default_protocol_text(
    protocol: str,
    skill_name: str,
    parent_title: str,
    target_defects: Sequence[str],
) -> str:
    defect = next((str(tag) for tag in target_defects if str(tag).strip()), "target defect")
    if protocol == "regression":
        return (
            f"Run regression against parent '{parent_title}' and verify no degradation on core metrics while fixing {defect}."
        )
    if protocol == "ablation":
        return (
            f"Ablate the {skill_name} delta to isolate contribution and confirm defect-level lift on {defect}."
        )
    return (
        f"Stress test {skill_name} under worst-case conditions tied to {defect} and record failure boundaries."
    )


def apply_edit_plan_to_components(
    components: Sequence[str],
    edit_plan: EditPlan,
) -> List[str]:
    ordered = [str(comp) for comp in components if str(comp).strip()]
    existing = list(ordered)

    def _contains(name: str) -> bool:
        return any(name == item for item in existing)

    for edit in edit_plan.component_edits:
        component = _coerce_component_name(edit.component)
        target = _coerce_component_name(edit.target)
        if edit.op == AtomicEditOp.ADD_COMPONENT:
            if component and not _contains(component):
                existing.append(component)
        elif edit.op == AtomicEditOp.REMOVE_COMPONENT:
            if component:
                existing = [item for item in existing if item != component]
        elif edit.op == AtomicEditOp.REPLACE_COMPONENT:
            if target:
                replaced = False
                for idx, item in enumerate(existing):
                    if item == target:
                        existing[idx] = component or target
                        replaced = True
                        break
                if not replaced and component and not _contains(component):
                    existing.append(component)
            elif component and not _contains(component):
                existing.append(component)
        elif edit.op == AtomicEditOp.REWIRE:
            # REWIRE affects topology, not component inventory.
            continue
        elif edit.op == AtomicEditOp.ADD_PROTOCOL:
            # Protocols are first-class edits but not structural components.
            continue

    return existing


def log_message(
    logger: Any,
    log_sink: Optional[Any],
    level: str,
    message: str,
    *args: Any,
) -> None:
    log_fn = getattr(logger, level, logger.info)
    try:
        log_fn(message, *args)
    except Exception:
        logger.exception("MCTS logging failure for message: %s", message)
    if log_sink:
        try:
            formatted = message % args if args else message
        except Exception:
            formatted = f"{message} | args={args}"
        try:
            log_sink(level, formatted)
        except Exception as exc:
            logger.debug("MCTS log sink failed: %s", exc)


def compute_protocol_score_from_plan(plan: Optional[Dict[str, Any]]) -> float:
    if not plan:
        return 0.0
    validation = plan.get("validation") if isinstance(plan.get("validation"), dict) else {}
    score = 0.0
    if validation.get("regression_tests"):
        score += 0.9
    if validation.get("ablation_tests"):
        score += 1.2
    if validation.get("stress_tests"):
        score += 0.9
    return min(3.0, score)


def memory_bundle_log_payload(bundle: Any) -> Dict[str, Any]:
    def _snippet_payload(snippet: Any) -> Dict[str, Any]:
        return {
            "id": getattr(snippet, "identifier", ""),
            "title": getattr(snippet, "title", ""),
            "detail": getattr(snippet, "detail", ""),
            "tags": list(getattr(snippet, "tags", []) or []),
        }

    return {
        "field_knowledge": [_snippet_payload(s) for s in getattr(bundle, "field_knowledge", []) or []],
        "anti_patterns": [_snippet_payload(s) for s in getattr(bundle, "anti_patterns", []) or []],
        "fix_recipes": [_snippet_payload(s) for s in getattr(bundle, "fix_recipes", []) or []],
    }


def simulate_log_payload(evaluation: Any) -> Dict[str, Any]:
    payload = {**evaluation.to_dict(), "composite": evaluation.composite}
    return payload


def _direction_prompt_context(
    mcts: Any,
    state: Any,
    *,
    object_schema: Optional[Dict[str, Any]] = None,
) -> Dict[str, str]:
    intervention = getattr(state, "scientific_intervention", {})
    intervention = intervention if isinstance(intervention, Mapping) else {}
    profile_payload = getattr(mcts, "scientific_intervention_profile", {})
    profile_payload = profile_payload if isinstance(profile_payload, Mapping) else {}
    profile_id = str(
        intervention.get("profile_id")
        or profile_payload.get("profile_id")
        or "generic_scientific"
    ).strip().lower()
    preset = getattr(mcts, "idea_taste_preset", None)
    direction_mode = str(
        intervention.get("direction_mode")
        or getattr(preset, "mode", None)
        or "default"
    ).strip()
    direction_summary = str(
        intervention.get("direction_summary")
        or getattr(preset, "summary", None)
        or "Use the default scientific search balance."
    ).strip()
    taste_guidance = str(
        getattr(preset, "instantiation_guidance", None)
        or "No special taste guidance."
    ).strip()
    seed_records = [
        dict(seed)
        for seed in getattr(mcts, "gap_hypothesis_seeds", []) or []
        if isinstance(seed, Mapping)
    ]
    hypothesis_contract = intervention.get("hypothesis_contract")
    hypothesis_contract = (
        hypothesis_contract if isinstance(hypothesis_contract, Mapping) else {}
    )
    raw_target_gap_ids = hypothesis_contract.get("target_gap_ids")
    if isinstance(raw_target_gap_ids, (list, tuple, set, frozenset)):
        target_gap_ids = [
            str(gap_id).strip()
            for gap_id in raw_target_gap_ids
            if str(gap_id).strip()
        ]
    elif str(raw_target_gap_ids or "").strip():
        target_gap_ids = [str(raw_target_gap_ids).strip()]
    else:
        target_gap_ids = [
            str(seed.get("gap_id") or "").strip()
            for seed in seed_records
            if str(seed.get("gap_id") or "").strip()
        ]
    selected_schema = object_schema
    if not isinstance(selected_schema, Mapping):
        selected_schema = intervention.get("scientific_object_schema")
    if not isinstance(selected_schema, Mapping):
        selected_schema = profile_payload.get("scientific_object_schema")
    return {
        "direction_mode": direction_mode,
        "direction_summary": direction_summary,
        "taste_guidance": taste_guidance,
        "seed_id": str(getattr(mcts, "seed_id", "") or "None supplied"),
        "route_id": str(getattr(mcts, "route_id", "") or "None supplied"),
        "route_policy": pretty_json(getattr(mcts, "route_policy", {}) or {}),
        "target_gap_ids": ", ".join(dict.fromkeys(target_gap_ids)) or "None supplied",
        "profile_id": profile_id,
        "profile_native_object_schema": pretty_json(dict(selected_schema or {})),
        "gap_seed_context": str(getattr(mcts, "gap_seed_context", "") or "No gap seeds supplied."),
    }


def _data_anchored_contract_prompt(state: Any) -> str:
    intervention = getattr(state, "scientific_intervention", {})
    intervention = intervention if isinstance(intervention, Mapping) else {}
    contract = intervention.get("data_anchored_contract")
    if not isinstance(contract, Mapping) or not contract.get("data_anchor_refs"):
        return ""
    return (
        "\n\n== Bounded supplied-data requirement ==\n"
        + pretty_json(dict(contract))
        + "\nThe data anchors are local observations, not paper citations. Keep their claim scope "
        "dataset-local and do not state that they prove a mechanism or a first discovery. "
        "The coverage pass must explicitly distinguish candidate_mechanism, "
        "alternative_explanation, and measurement_artifact branches. A measurement-at-risk "
        "anchor may support only measurement validity or workflow reasoning."
    )


def _contract_from_instantiation(instantiated: Mapping[str, Any]) -> Dict[str, Any]:
    explicit_contract = instantiated.get("scientific_contract")
    if isinstance(explicit_contract, Mapping):
        contract = dict(explicit_contract)
    else:
        contract = {}
    for field_name in HYPOTHESIS_CONTRACT_FIELDS:
        value = instantiated.get(field_name)
        if value not in (None, "", [], {}):
            contract.setdefault(field_name, value)
    return contract


def _nonempty_contract_value(value: Any) -> bool:
    return value not in (None, "", [], {})


def _parent_hypothesis_contract(parent_state: Any) -> Dict[str, Any]:
    """Return the parent scientific contract without exposing mutable state."""

    intervention = getattr(parent_state, "scientific_intervention", {}) or {}
    if not isinstance(intervention, Mapping):
        return {}
    parent_contract = intervention.get("hypothesis_contract")
    merged = (
        {
            field_name: deepcopy(value)
            for field_name, value in parent_contract.items()
            if field_name in HYPOTHESIS_CONTRACT_FIELDS
            and _nonempty_contract_value(value)
        }
        if isinstance(parent_contract, Mapping)
        else {}
    )
    for field_name in HYPOTHESIS_CONTRACT_FIELDS:
        value = intervention.get(field_name)
        if _nonempty_contract_value(value):
            merged.setdefault(field_name, deepcopy(value))
    return merged


def merge_hypothesis_contract(
    parent_contract: Mapping[str, Any],
    instantiated_contract: Mapping[str, Any],
) -> Dict[str, Any]:
    """Merge a child instantiation onto its parent without treating blanks as clears."""

    merged = {
        field_name: deepcopy(value)
        for field_name, value in parent_contract.items()
        if field_name in HYPOTHESIS_CONTRACT_FIELDS
        and _nonempty_contract_value(value)
    }
    for field_name, value in instantiated_contract.items():
        if field_name not in HYPOTHESIS_CONTRACT_FIELDS:
            continue
        if _nonempty_contract_value(value):
            merged[field_name] = deepcopy(value)
    return merged


def _route_contract_incomplete_fields(
    route_id: str,
    parent_contract: Mapping[str, Any],
    instantiated_contract: Mapping[str, Any],
) -> List[str]:
    """Identify route-defining fields that a child omitted and would only inherit."""

    required_fields = _ROUTE_REQUIRED_CONTRACT_FIELDS.get(route_id, ())
    if route_id == "mechanism_replacement":
        child_has_mechanism = any(
            _nonempty_contract_value(instantiated_contract.get(field_name))
            for field_name in required_fields
        )
        parent_has_mechanism = any(
            _nonempty_contract_value(parent_contract.get(field_name))
            for field_name in required_fields
        )
        return ["mechanism_or_relation"] if parent_has_mechanism and not child_has_mechanism else []
    incomplete: List[str] = []
    for field_name in required_fields:
        child_value = instantiated_contract.get(field_name)
        if _nonempty_contract_value(child_value):
            continue
        if _nonempty_contract_value(parent_contract.get(field_name)):
            incomplete.append(field_name)
    return incomplete


def _contract_value_signature(value: Any) -> str:
    if isinstance(value, (Mapping, list, tuple, set, frozenset)):
        try:
            return json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            pass
    return re.sub(r"\s+", " ", str(value or "")).strip().casefold()


def _route_contract_noop_fields(
    route_id: str,
    parent_contract: Mapping[str, Any],
    instantiated_contract: Mapping[str, Any],
) -> List[str]:
    """Identify explicit route fields that only restate the parent contract."""

    required_fields = _ROUTE_REQUIRED_CONTRACT_FIELDS.get(route_id, ())
    if route_id == "mechanism_replacement":
        child_values = [
            (field_name, instantiated_contract.get(field_name))
            for field_name in required_fields
            if _nonempty_contract_value(instantiated_contract.get(field_name))
        ]
        if child_values and all(
            _nonempty_contract_value(parent_contract.get(field_name))
            and _contract_value_signature(child_value)
            == _contract_value_signature(parent_contract.get(field_name))
            for field_name, child_value in child_values
        ):
            return ["mechanism_or_relation"]
        return []
    noops: List[str] = []
    for field_name in required_fields:
        child_value = instantiated_contract.get(field_name)
        parent_value = parent_contract.get(field_name)
        if (
            _nonempty_contract_value(child_value)
            and _nonempty_contract_value(parent_value)
            and _contract_value_signature(child_value)
            == _contract_value_signature(parent_value)
        ):
            noops.append(field_name)
    return noops


def _route_parent_values(
    route_id: str,
    parent_contract: Mapping[str, Any],
) -> Dict[str, Any]:
    return {
        field_name: deepcopy(parent_contract[field_name])
        for field_name in _ROUTE_REQUIRED_CONTRACT_FIELDS.get(route_id, ())
        if _nonempty_contract_value(parent_contract.get(field_name))
    }


def materialize_child_state(
    mcts: Any,
    parent_state: Any,
    plan: Any,
    instantiated: Optional[Dict[str, Any]] = None,
    selection_metadata: Optional[Dict[str, Any]] = None,
    *,
    idea_state_cls: Any,
) -> Any:
    new_components = apply_edit_plan_to_components(parent_state.components, plan)
    component_explanations = build_child_component_explanations(
        parent_state,
        new_components,
        plan,
        instantiated,
    )

    inst = instantiated or {}
    title = inst.get("title") or f"{parent_state.title} | {plan.skill_name.replace('-', ' ').title()}"
    abstract = inst.get("abstract") or (
        f"Component-level macro action '{plan.skill_name}' targets defects "
        f"{', '.join(plan.target_defects)} via {len(plan.component_edits)} atomic edits."
    )
    core = inst.get("core_contribution") or plan.objective
    method = inst.get("method") or plan_to_method_text(plan)
    risks = inst.get("risks") or f"Guardrails: {'; '.join(plan.guardrails)}"
    rationale = inst.get("rationale") or plan.compile_notes
    tags = _dedupe_keep_order_strings(list(parent_state.tags) + [plan.skill_name] + list(plan.target_defects))
    selection_metadata = selection_metadata or {}
    skill_metrics = {
        "idea_taste_mode": str(selection_metadata.get("idea_taste_mode") or "none"),
        "skill_prior_before": mcts._skill_prior_for_prompt(plan.skill_name),
        "guardrails": plan.guardrails,
        "constraints": ANTI_PATTERN_CONSTRAINTS,
        "llm_instantiated": bool(inst),
    }
    skill_selection_breakdown = selection_metadata.get("skill_selection_breakdown")
    if isinstance(skill_selection_breakdown, dict) and skill_selection_breakdown:
        skill_metrics["skill_selection_breakdown"] = skill_selection_breakdown
    scientific_intervention = dict(
        getattr(parent_state, "scientific_intervention", {}) or {}
    )
    coverage_branch = selection_metadata.get("data_anchored_coverage_branch")
    if isinstance(coverage_branch, Mapping):
        coverage_branch = dict(coverage_branch)
        branch_id = str(coverage_branch.get("branch_id") or "").strip()
        if branch_id:
            tags = _dedupe_keep_order_strings(
                [*tags, f"data_coverage:{branch_id}"]
            )
            skill_metrics["data_anchored_coverage_branch"] = coverage_branch
            scientific_intervention["data_anchored_coverage_branch"] = coverage_branch
            inherited_data_contract = scientific_intervention.get("data_anchored_contract")
            if isinstance(inherited_data_contract, Mapping):
                inherited_data_contract = dict(inherited_data_contract)
                inherited_data_contract["active_coverage_branch"] = coverage_branch
                scientific_intervention["data_anchored_contract"] = inherited_data_contract
    parent_contract = _parent_hypothesis_contract(parent_state)
    instantiated_contract = _contract_from_instantiation(inst)
    scientific_contract = merge_hypothesis_contract(
        parent_contract,
        instantiated_contract,
    )
    if scientific_contract:
        scientific_intervention["hypothesis_contract"] = scientific_contract
    direction_mode = str(
        scientific_contract.get("direction_mode")
        or selection_metadata.get("idea_taste_mode")
        or getattr(getattr(mcts, "idea_taste_preset", None), "mode", None)
        or "default"
    ).strip()
    if direction_mode:
        scientific_intervention["direction_mode"] = direction_mode
    direction_summary = str(
        scientific_contract.get("direction_summary")
        or getattr(getattr(mcts, "idea_taste_preset", None), "summary", None)
        or ""
    ).strip()
    if direction_summary:
        scientific_intervention["direction_summary"] = direction_summary
    route_id = str(getattr(mcts, "route_id", "") or "").strip()
    incomplete_route_fields = _route_contract_incomplete_fields(
        route_id,
        parent_contract,
        instantiated_contract,
    )
    if incomplete_route_fields:
        scientific_intervention["route_contract_incomplete_fields"] = incomplete_route_fields
    else:
        scientific_intervention.pop("route_contract_incomplete_fields", None)
    noop_route_fields = _route_contract_noop_fields(
        route_id,
        parent_contract,
        instantiated_contract,
    )
    if noop_route_fields:
        scientific_intervention["route_contract_noop_fields"] = noop_route_fields
    else:
        scientific_intervention.pop("route_contract_noop_fields", None)
    if incomplete_route_fields or noop_route_fields:
        scientific_intervention["route_contract_parent_values"] = _route_parent_values(
            route_id,
            parent_contract,
        )
    else:
        scientific_intervention.pop("route_contract_parent_values", None)
    return idea_state_cls(
        title=title,
        abstract=abstract,
        core_contribution=core,
        method=method,
        risks=risks,
        tags=tags,
        operator=plan.skill_name,
        target_defects=plan.target_defects,
        rationale=rationale,
        memory_refs=plan.memory_refs,
        components=new_components,
        component_explanations=component_explanations,
        root_domains=list(getattr(parent_state, "root_domains", []) or []),
        discipline_resolution=dict(
            getattr(parent_state, "discipline_resolution", {}) or {}
        ),
        scientific_intervention=scientific_intervention,
        paper_graph_context=(
            str(inst.get("_paper_graph_context") or "")
            if isinstance(inst, dict) and str(inst.get("_paper_graph_context") or "").strip()
            else parent_state.paper_graph_context
        ),
        edit_plan=plan.to_dict(),
        skill_metrics=skill_metrics,
    )

def apply_instantiated_mapping_to_plan(
    plan: Any,
    instantiated: Optional[Dict[str, Any]],
    *,
    rewrite_components: bool = True,
) -> None:
    if not instantiated:
        return
    edit_reasons = instantiated.get("edit_reasons")
    if isinstance(edit_reasons, list):
        for reason_idx, edit in enumerate(plan.component_edits):
            if reason_idx < len(edit_reasons) and isinstance(edit_reasons[reason_idx], str):
                edit.reason = edit_reasons[reason_idx]
    if not rewrite_components or not isinstance(instantiated.get("component_mapping"), dict):
        return
    mapping = _normalize_component_mapping(instantiated.get("component_mapping"))

    for edit in plan.component_edits:
        component_name = _coerce_component_name(edit.component)
        target_name = _coerce_component_name(edit.target)
        edit.component = mapping.get(component_name, component_name)
        edit.target = mapping.get(target_name, target_name) if target_name else ""
        if edit.op == AtomicEditOp.REWIRE:
            edit.details = f"Rewire {edit.component} -> {edit.target}"
        elif edit.op == AtomicEditOp.REPLACE_COMPONENT:
            edit.details = f"Replace {edit.target} with {edit.component}"
        elif edit.op == AtomicEditOp.ADD_COMPONENT:
            edit.details = f"ADD_COMPONENT on {edit.component}"


def instantiate_compiled_plan_for_node(
    mcts: Any,
    plan: Any,
    parent_state: Any,
    bundle: Any,
    *,
    prompt_template: str,
    plan_name: str,
    plan_references: str = "None.",
    taste_guidance: str = "No special taste guidance.",
    root_domains_text: str = "Unspecified",
    additional_retrieval_context: str = "",
    stage: str = "mcts_expand",
) -> Optional[Dict[str, Any]]:
    component_edits_text = plan_to_method_text(plan)
    validation_text = plan_to_experiment_text(plan)
    schema = getattr(plan, "scientific_object_schema", {}) or {}
    native_guidance = list(plan.guardrails)
    if schema:
        native_guidance.extend(
            [
                "Profile rendering: " + str(getattr(plan, "profile_rendering_id", "") or "native"),
                "Allowed scientific object types: " + ", ".join(str(item) for item in schema.get("object_types", [])),
                "Preferred native operations: " + ", ".join(str(item) for item in schema.get("allowed_operations", [])),
                "Keep target_object, claim_delta, mechanism_delta, evidence_obligation, boundary_condition, and measurement_or_observation explicit.",
            ]
        )

    prompt = prompt_template.format(
        topic=mcts.topic,
        root_domains=root_domains_text,
        scientific_intervention_profile=format_scientific_intervention_profile_for_prompt(
            getattr(parent_state, "scientific_intervention", None)
        ),
        refinement_scope=mcts.refinement_scope or "None",
        taste_guidance=taste_guidance,
        mature_idea=mcts.mature_idea or "None",
        parent_summary=parent_state.describe(),
        parent_components=", ".join(parent_state.components) if parent_state.components else "None",
        paper_context=mcts.paper_context,
        memory_bundle=bundle.to_prompt_block(),
        skill_references=plan_references,
        additional_retrieval_context=additional_retrieval_context,
        skill_name=plan_name,
        plan_objective=plan.objective,
        target_defects=", ".join(plan.target_defects),
        component_edits=component_edits_text,
        validation_protocols=validation_text,
        guardrails="; ".join(native_guidance) if native_guidance else "None",
    )
    direction_context = _direction_prompt_context(
        mcts,
        parent_state,
        object_schema=schema if isinstance(schema, dict) else None,
    )
    prompt += (
        "\n\n== Direction and Gap-to-Hypothesis Contract ==\n"
        f"Direction mode: {direction_context['direction_mode']}\n"
        f"Direction summary: {direction_context['direction_summary']}\n"
        f"Taste guidance: {direction_context['taste_guidance']}\n"
        f"Mature idea seed ID: {direction_context['seed_id']}\n"
        f"Search route ID: {direction_context['route_id']}\n"
        f"Search route policy: {direction_context['route_policy']}\n"
        f"Target gap IDs: {direction_context['target_gap_ids']}\n"
        f"Resolved profile ID: {direction_context['profile_id']}\n"
        "Profile-native scientific object schema:\n"
        f"{direction_context['profile_native_object_schema']}\n"
        "Gap-to-hypothesis seeds:\n"
        f"{direction_context['gap_seed_context']}\n"
        "\n== Required Directional Scientific Fields ==\n"
        "Return these fields in the JSON payload, either at the top level or mirrored inside scientific_contract: "
        "direction_mode, direction_summary, central_hypothesis, scientific_object, mechanism_or_relation, "
        "intervention_or_transformation, expected_mechanism, discriminating_observation, "
        "boundary_or_failure_condition, claim_scope, assumptions, target_gap_ids, gap_alignment, "
        "evidence_requirement, and evidence_basis.\n"
        "evidence_requirement must name the observation, contrast, proof, measurement, or boundary needed "
        "to distinguish the claim; it must not contain an experiment design. Do not return predicted results, "
        "sample sizes, statistical tests, instrument configurations, ablation plans, or failure-repair plans."
    )
    prompt += _data_anchored_contract_prompt(parent_state)
    survey_handoff = getattr(mcts, "survey_idea_handoff", {})
    if isinstance(survey_handoff, dict) and survey_handoff:
        prompt += "\n\n== Verified Survey -> Idea handoff ==\n" + pretty_json(survey_handoff)
    try:
        response = mcts.chat_fn(
            prompt,
            model=mcts.config.generation_model,
            stage=stage,
            temperature=mcts.config.generation_temperature,
            max_output_tokens=mcts.config.generation_max_tokens,
        )
        payload = parse_json_response(response)
        if isinstance(payload, list):
            payload = payload[0]
        if not isinstance(payload, dict):
            return None
        contract = payload.get("scientific_contract")
        if not isinstance(contract, dict):
            contract = {
                key: payload.get(key)
                for key in (
                    "contribution_mode",
                    "scientific_object",
                    "central_hypothesis",
                    "intervention_or_transformation",
                    "expected_mechanism",
                    "discriminating_observation",
                    "boundary_or_failure_condition",
                    "evidence_requirement",
                )
                if payload.get(key) not in (None, "", [], {})
            }
        if contract:
            payload["scientific_contract"] = contract
        payload["component_mapping"] = _filter_component_mapping_to_plan_keys(
            payload.get("component_mapping"),
            plan,
        )
        payload["component_role_explanations"] = normalize_component_explanations(
            list(payload["component_mapping"].values()),
            payload.get("component_role_explanations"),
        )
        return payload
    except Exception as exc:
        log_message(
            mcts.logger,
            mcts.log_sink,
            "warning",
            "⚠️  Plan instantiation failed for %s: %s",
            plan_name,
            exc,
        )
        return None


def instantiate_skill_plan_for_node(
    mcts: Any,
    plan: Any,
    parent_state: Any,
    bundle: Any,
    *,
    prompt_template: str,
    root_domains_text: str = "Unspecified",
    additional_retrieval_context: str = "",
) -> Optional[Dict[str, Any]]:
    return instantiate_compiled_plan_for_node(
        mcts,
        plan,
        parent_state,
        bundle,
        prompt_template=prompt_template,
        plan_name=plan.skill_name,
        plan_references=mcts.skill_catalog.render_references_for_prompt(plan.skill_name),
        taste_guidance=(
            getattr(getattr(mcts, "idea_taste_preset", None), "instantiation_guidance", None)
            or "No special taste guidance."
        ),
        root_domains_text=root_domains_text,
        additional_retrieval_context=additional_retrieval_context,
        stage="mcts_expand",
    )


def build_symbolic_eval_hints(mcts: Any, node: Any) -> str:
    if not getattr(mcts, "enable_symbolic_memory", True):
        return "No symbolic memory hints available."
    component_families = extract_component_families(node.state.components, node.state.method)
    if not component_families:
        return "No symbolic memory hints available."

    retrieved_records: List[Tuple[str, str, float, Any]] = []

    for cf in component_families:
        component_name = str(cf.get("component", "") or "").strip()
        family = cf.get("family", "")
        if not component_name and not family:
            continue

        records = mcts.symbolic_memory.retrieve_hierarchical(
            target_component=component_name,
            target_family=family,
            limit=2,
            threshold=0.2,
            agent_id="idea_agent",
            query_context=str(getattr(node.state, "abstract", "") or "").strip(),
        )
        if not records:
            continue

        for score, rec in records:
            retrieved_records.append((component_name, str(family or ""), float(score), rec))

    if not retrieved_records:
        return "No symbolic memory hints available."

    deduped_records: Dict[Tuple[str, ...], Tuple[str, str, float, Any]] = {}
    for query_component, query_family, score, rec in retrieved_records:
        dedupe_key = (
            str(getattr(rec, "component", "") or "").strip().lower(),
            str(getattr(rec, "component_family", "") or "").strip().lower(),
            str(getattr(rec, "result", "") or "").strip().lower(),
            str(getattr(rec, "metric", "") or "").strip().lower(),
            str(getattr(rec, "value", "") or "").strip().lower(),
            str(getattr(rec, "analysis", "") or "").strip().lower(),
        )
        existing = deduped_records.get(dedupe_key)
        if existing is None or score > existing[2]:
            deduped_records[dedupe_key] = (query_component, query_family, score, rec)

    if not deduped_records:
        return "No symbolic memory hints available."

    hints_parts: List[str] = []
    for query_component, query_family, score, rec in sorted(
        deduped_records.values(),
        key=lambda item: item[2],
        reverse=True,
    ):
        component = clip_text(getattr(rec, "component", "")) or "unknown_component"
        component_family = clip_text(getattr(rec, "component_family", "")) or "unknown_family"
        result = clip_text(getattr(rec, "result", "")) or "inconclusive"
        metric = clip_text(getattr(rec, "metric", "")) or "unspecified_metric"
        value = clip_text(getattr(rec, "value", "")) or "unspecified_value"
        confidence = float(getattr(rec, "confidence", 0.0))
        analysis = clip_text(getattr(rec, "analysis", ""))
        line = (
            f"  - query_component={query_component or 'unknown_component'}"
            f" | query_family={query_family or 'unknown_family'}"
            f" | matched_family={component_family}"
            f" | component={component}"
            f" | result={result} | metric={metric} | value={value}"
            f" (conf={confidence:.2f}, score={score:.3f})"
        )
        if analysis:
            line += f"  analysis: {analysis}"
        hints_parts.append(line)

    header = (
        "Historical ablation records for the component families in this idea "
        "(positive result means removing the component helped, "
        "negative result means removing the component hurt):"
    )
    return header + "\n" + "\n".join(hints_parts)


def update_skill_prior_from_evaluation(mcts: Any, node: Any, evaluation: Any) -> None:
    skill_name = node.state.operator
    if not skill_name or skill_name == "seed":
        return

    normalized_reward = max(0.0, min(1.0, evaluation.composite / 5.0))
    prior = mcts.skill_catalog.update_prior(
        skill_name=skill_name,
        reward=normalized_reward,
        feedback=evaluation.feedback,
        failure_modes=evaluation.failure_modes,
        success_threshold=mcts.config.skill_prior_success_threshold,
    )
    node.state.skill_metrics["skill_prior_after"] = prior.to_dict()


def extract_mature_idea_components_via_llm(
    mcts: Any,
    mature_idea: str,
    topic: str,
    *,
    prompt_template: str,
    max_components: int,
    prior_components: Optional[Sequence[str]] = None,
    prior_component_explanations: Optional[Any] = None,
    component_decisions: Optional[Sequence[Dict[str, Any]]] = None,
) -> Tuple[List[str], Dict[str, str]]:
    normalized_prior_components = [
        str(component).strip()
        for component in (prior_components or [])
        if str(component).strip()
    ]
    normalized_prior_explanations = normalize_component_explanations(
        normalized_prior_components,
        prior_component_explanations,
    )
    normalized_component_decisions = [
        decision for decision in (component_decisions or []) if isinstance(decision, dict)
    ]
    prompt = prompt_template.format(
        mature_idea=mature_idea,
        topic=topic,
        scientific_intervention_profile=format_scientific_intervention_profile_for_prompt(
            getattr(mcts, "scientific_intervention_profile", None)
        ),
        prior_components=pretty_json(
            component_inventory_payload(
                normalized_prior_components,
                normalized_prior_explanations,
            ),
        )
        if normalized_prior_components
        else "[]",
        component_decisions=pretty_json(normalized_component_decisions)
        if normalized_component_decisions
        else "[]",
    )
    try:
        response = mcts.chat_fn(
            prompt,
            model=mcts.config.generation_model,
            temperature=0.3,
            max_output_tokens=mcts.config.generation_max_tokens,
        )
        payload = parse_json_response(response)
        if isinstance(payload, list):
            payload = payload[0]
        components, explanations = parse_component_bundle_payload(
            payload,
            max_components=max_components,
        )
        if components:
            return components, explanations
    except Exception as exc:
        log_message(
            mcts.logger,
            mcts.log_sink,
            "warning",
            "⚠️  Component extraction from mature idea failed: %s",
            exc,
        )
    return [], {}


def select_leaf_for_rollout(mcts: Any, node: Any) -> Tuple[Any, List[Any]]:
    current = node
    path = [node]
    while current.children and current.expanded:
        parent = current
        current = max(
            parent.children,
            key=lambda child: child.uct_value(
                parent_visits=parent.visits or 1,
                exploration_constant=mcts.config.exploration_constant,
            ),
        )
        path.append(current)
    return current, path


def expand_node_with_skills(
    mcts: Any,
    node: Any,
    path: List[Any],
    *,
    min_components: int,
    max_components: int,
) -> Tuple[Optional[Any], List[Any]]:
    bundle = MemoryBundle()
    if getattr(mcts, "enable_vector_memory", True):
        bundle = mcts.memory_accessor.retrieve_bundle(
            query=(
                f"{mcts.topic}\n{node.state.title}\n"
                f"{node.state.core_contribution}\n"
                f"defects={','.join(node.state.target_defects)}"
            )
        )
        log_message(
            mcts.logger,
            mcts.log_sink,
            "info",
            "[MCTS] Expand: vector_memory\n%s",
            pretty_json(mcts._memory_bundle_log_payload(bundle)),
        )
    structural_profile = build_structural_profile(
        node.state,
        refinement_scope=mcts.refinement_scope,
        mature_idea=mcts.mature_idea,
        defect_tags=node.state.target_defects,
        profile_id=str(
            (getattr(node.state, "scientific_intervention", {}) or {}).get("profile_id")
            or "generic_scientific"
        ).strip().lower(),
    )
    log_message(
        mcts.logger,
        mcts.log_sink,
        "info",
        "[MCTS] Expand: structural_profile\n%s",
        pretty_json(structural_profile),
    )
    scientific_intervention = getattr(node.state, "scientific_intervention", {}) or {}
    profile_id = str(
        scientific_intervention.get("profile_id") or "generic_scientific"
    ).strip().lower()
    object_schema = scientific_intervention.get("scientific_object_schema")
    if not isinstance(object_schema, dict):
        schema_spec = get_scientific_object_schema(profile_id)
        object_schema = schema_spec.to_payload() if schema_spec is not None else {}
    selected_skill_candidates = mcts.skill_catalog.select_skills(
        defect_tags=node.state.target_defects,
        max_children=mcts.config.branching_factor,
        preset=getattr(mcts, "idea_taste_preset", None),
        structural_profile=structural_profile,
        profile_id=profile_id,
    )
    skill_candidates = list(selected_skill_candidates)
    data_contract = scientific_intervention.get("data_anchored_contract")
    data_contract = data_contract if isinstance(data_contract, Mapping) else {}
    coverage_assignment = data_contract.get("coverage_assignment")
    coverage_assignment = (
        coverage_assignment if isinstance(coverage_assignment, Mapping) else {}
    )
    coverage_branches = [
        dict(branch)
        for branch in data_contract.get("coverage_branches", [])
        if isinstance(branch, Mapping) and str(branch.get("branch_id") or "").strip()
    ]
    is_coverage_root = bool(coverage_assignment and coverage_branches) and int(
        getattr(node, "depth", len(path) - 1)
    ) == 0
    expansion_specs: list[tuple[Any, Mapping[str, Any] | None]]
    if is_coverage_root and skill_candidates:
        expansion_specs = [
            (skill_candidates[index % len(skill_candidates)], branch)
            for index, branch in enumerate(coverage_branches)
        ]
    else:
        expansion_specs = [(selection_candidate, None) for selection_candidate in skill_candidates]
    log_message(
        mcts.logger,
        mcts.log_sink,
        "info",
        "[MCTS] Expand: skill_prior\n%s",
        pretty_json(
            {candidate.skill.name: candidate.to_dict() for candidate in skill_candidates},
        ),
    )
    payload_count = len(skill_candidates)
    pre_children = len(node.children)
    new_child: Optional[Any] = None

    idea_node_cls = type(node)
    operator_application_cls = type(node.transformation)
    for selection_candidate, coverage_branch in expansion_specs:
        skill = mcts.skill_catalog.render_skill_for_profile(
            selection_candidate.skill,
            profile_id,
            object_schema=object_schema,
        )
        plan = mcts.skill_catalog.compile_plan(
            skill=skill,
            parent_title=node.state.title,
            parent_components=node.state.components,
            target_defects=node.state.target_defects,
            memory_refs=bundle.referenced_ids(),
            profile_id=profile_id,
            object_schema=object_schema,
        )
        prior_constraints = mcts.skill_catalog.priors.get(skill.name, SkillUsagePrior()).rule_constraints
        if prior_constraints:
            plan.guardrails = _dedupe_keep_order_strings(plan.guardrails + list(prior_constraints))
        if coverage_branch is not None:
            branch_id = str(coverage_branch.get("branch_id") or "").strip()
            branch_instruction = str(coverage_branch.get("instruction") or "").strip()
            plan.objective = (
                f"{plan.objective} Data-coverage branch `{branch_id}`: {branch_instruction}"
            ).strip()
            plan.guardrails = _dedupe_keep_order_strings(
                [
                    *plan.guardrails,
                    f"Materialize the required data-coverage branch `{branch_id}`.",
                    "Keep this branch dataset-local; it cannot establish a universal mechanism or novelty claim.",
                ]
            )
            plan.compile_notes = (
                f"{plan.compile_notes}\nRequired data-coverage branch: {branch_id}. "
                f"{branch_instruction}"
            ).strip()

        current_count = len(node.state.components)
        filtered_edits: List[ComponentEdit] = []
        for edit in plan.component_edits:
            if current_count <= min_components and edit.op == AtomicEditOp.REMOVE_COMPONENT:
                continue
            if current_count >= max_components and edit.op == AtomicEditOp.ADD_COMPONENT:
                continue
            if edit.op == AtomicEditOp.ADD_COMPONENT:
                current_count += 1
            elif edit.op == AtomicEditOp.REMOVE_COMPONENT:
                current_count -= 1
            filtered_edits.append(edit)
        plan.component_edits = filtered_edits

        instantiated = mcts._instantiate_skill_plan(plan, node.state, bundle)
        if isinstance(instantiated, dict) and instantiated.get("_skip_child_creation"):
            log_message(
                mcts.logger,
                mcts.log_sink,
                "info",
                "[MCTS] Expand: skipping skill=%s child creation (%s)",
                skill.name,
                instantiated.get("_skip_reason", "no reason provided"),
            )
            continue
        log_message(
            mcts.logger,
            mcts.log_sink,
            "info",
            "[MCTS] Expand: skill=%s instantiation_result\n%s",
            skill.name,
            pretty_json(
                instantiated
                if instantiated is not None
                else {"status": "empty", "message": "instantiation returned no output"},
            ),
        )

        apply_instantiated_mapping_to_plan(plan, instantiated)

        protocol_names: List[str] = []
        for edit_idx, edit in enumerate(plan.component_edits):
            if edit.op == AtomicEditOp.ADD_PROTOCOL:
                protocol_names.append(edit.component)
                continue
            op_dict = {
                "op": edit.op.value if hasattr(edit.op, "value") else edit.op,
                "component": edit.component,
                "target": edit.target,
                "condition": edit.condition,
                "details": edit.details or "",
                "reason": edit.reason or "",
            }

        selection_metadata: Dict[str, Any] = {
            "idea_taste_mode": getattr(getattr(mcts, "idea_taste_preset", None), "mode", None) or "none",
            "skill_selection_breakdown": {
                "defect_score": selection_candidate.defect_score,
                "prior_score": selection_candidate.prior_score,
                "preset_bias": selection_candidate.preset_bias,
                "selection_total": selection_candidate.selection_total,
            },
        }
        if coverage_branch is not None:
            selection_metadata["data_anchored_coverage_branch"] = dict(coverage_branch)
        child_state = mcts._materialize_child_state(
            node.state,
            plan,
            instantiated,
            selection_metadata=selection_metadata,
        )
        child_node = attach_child(
            node,
            child_state,
            signature_nodes=mcts.signature_nodes,
            id_iter=mcts._id_iter,
            idea_node_cls=idea_node_cls,
            operator_application_cls=operator_application_cls,
            logger=mcts.logger,
            log_sink=mcts.log_sink,
        )
        if child_node is None:
            continue
        cached_eval = get_best_cached_evaluation(child_state.signature, mcts.evaluation_cache)
        if cached_eval:
            child_node.evaluation = cached_eval
        if new_child is None and child_node.visits == 0:
            new_child = child_node

    node.expanded = True

    if new_child is None and node.children:
        new_child = min(node.children, key=lambda c: c.visits)
    if new_child:
        return new_child, path + [new_child]
    return node, path


def apply_profile_drift_to_evaluation(
    node: Any,
    evaluation: Any,
    profile_drift: Mapping[str, Any],
) -> None:
    """Apply a soft profile-drift penalty without rejecting the candidate."""

    severity = str(profile_drift.get("drift_severity") or "none").strip().lower()
    if severity == "none":
        return
    intervention_payload = getattr(node.state, "scientific_intervention", None)
    if isinstance(intervention_payload, dict):
        intervention_payload["profile_drift"] = dict(profile_drift)
    detected_defects = getattr(evaluation, "detected_defects", None)
    if isinstance(detected_defects, list) and "profile_drift" not in detected_defects:
        detected_defects.append("profile_drift")
    target_defects = getattr(node.state, "target_defects", None)
    if isinstance(target_defects, list) and "profile_drift" not in target_defects:
        target_defects.append("profile_drift")
    if "profile_drift" in (detected_defects or []):
        penalty = 1.0 if severity == "material" else 0.5
        current_alignment = float(getattr(evaluation, "alignment_score", 0.0) or 0.0)
        if not getattr(evaluation, "_profile_drift_penalized", False):
            evaluation.alignment_score = max(0, round(current_alignment - penalty))
            setattr(evaluation, "_profile_drift_penalized", True)
    drift_terms = profile_drift.get("forbidden_primary_terms") or profile_drift.get("secondary_tool_mentions") or []
    drift_note = "Profile drift detected: " + ", ".join(str(term) for term in drift_terms)
    feedback = str(getattr(evaluation, "feedback", "") or "")
    if drift_note not in feedback:
        evaluation.feedback = f"{feedback}; {drift_note}" if feedback else drift_note


def simulate_node_value(
    mcts: Any,
    node: Any,
    path: List[Any],
    experiences: List[Dict[str, Any]],
    *,
    idea_evaluation_cls: Any,
) -> Optional[Any]:
    path_summary_text = path_summary(path)
    scientific_intervention = getattr(node.state, "scientific_intervention", {})
    profile_id = str(
        scientific_intervention.get("profile_id") or "generic_scientific"
    ).strip().lower()

    symbolic_hints = mcts._build_symbolic_eval_hints(node)
    log_message(
        mcts.logger,
        mcts.log_sink,
        "info",
        "[MCTS] Simulate: symbolic_memory\n%s",
        symbolic_hints,
    )

    direction_context = _direction_prompt_context(mcts, node.state)
    prompt = mcts.evaluation_prompt.format(
        topic=mcts.topic,
        direction_mode=direction_context["direction_mode"],
        direction_summary=direction_context["direction_summary"],
        taste_guidance=direction_context["taste_guidance"],
        target_gap_ids=direction_context["target_gap_ids"],
        profile_id=direction_context["profile_id"],
        gap_seed_context=direction_context["gap_seed_context"],
        root_domains=_format_root_domains_for_prompt(getattr(node.state, "root_domains", [])),
        refinement_scope=mcts.refinement_scope or "None",
        mature_idea=mcts.mature_idea or "None",
        edit_plan=format_evaluator_edit_plan_prompt_view(node.state.edit_plan)
        if node.state.edit_plan
        else "No edit plan available.",
        idea=format_evaluator_idea_prompt_view(node.state, heading="Candidate Idea"),
        scientific_intervention_profile=format_scientific_intervention_profile_for_prompt(
            scientific_intervention
        ),
        profile_native_object_schema=direction_context["profile_native_object_schema"],
        scientific_rubric=format_scientific_rubric_for_prompt(scientific_intervention),
        defect_registry=format_defect_registry(profile_id),
        symbolic_memory_hints=symbolic_hints,
    )
    prompt += _data_anchored_contract_prompt(node.state)
    survey_handoff = getattr(mcts, "survey_idea_handoff", {})
    if isinstance(survey_handoff, dict) and survey_handoff:
        prompt += "\n\n== Verified Survey -> Idea handoff ==\n" + pretty_json(survey_handoff)
    prompt = render_profile_evaluation_prompt(prompt, profile_id)
    allowed_novelty_axes = PROFILE_NOVELTY_AXES.get(
        profile_id,
        PROFILE_NOVELTY_AXES["generic_scientific"],
    )
    prompt += (
        "\nFor `novelty_axes`, output only these profile-native keys: "
        + ", ".join(allowed_novelty_axes)
        + ". Do not add any other axis names.\n"
    )
    cache_key = evaluation_prompt_cache_key(
        prompt,
        rubric_version=SCIENTIFIC_RUBRIC_VERSION,
        profile_version=SCIENTIFIC_INTERVENTION_PROFILE_VERSION,
        profile_id=profile_id,
    )

    survey_handoff = getattr(mcts, "survey_idea_handoff", {})
    profile_drift = detect_profile_drift(
        profile_id,
        candidate=node.state.to_payload(),
        survey_handoff=survey_handoff if isinstance(survey_handoff, Mapping) else None,
        research_object=getattr(node.state, "scientific_intervention", {}).get("scientific_object_schema")
        if isinstance(getattr(node.state, "scientific_intervention", {}), Mapping)
        else None,
    )

    cached_evaluation = get_cached_evaluation(node.state.signature, cache_key, mcts.evaluation_cache)
    if cached_evaluation:
        apply_profile_drift_to_evaluation(node, cached_evaluation, profile_drift)
        node.evaluation = cached_evaluation
        node.latest_path_summary = path_summary_text
        log_message(
            mcts.logger,
            mcts.log_sink,
            "info",
            "[MCTS] Simulate (cache hit): node=%s\n[MCTS] Score: %.4f\n%s",
            node.state.title,
            cached_evaluation.composite,
            pretty_json(mcts._simulate_log_payload(cached_evaluation)),
        )
        maybe_record_experience(
            cache_key,
            node,
            cached_evaluation,
            path_summary_text,
            experiences,
            mcts.experience_cache,
            getattr(mcts, "enable_vector_memory", True),
            mcts.memory_accessor,
            mcts.config.min_confidence_for_memory,
        )
        return cached_evaluation

    try:
        response = mcts.chat_fn(
            prompt,
            model=mcts.config.evaluation_model,
            temperature=mcts.config.evaluation_temperature,
            max_output_tokens=mcts.config.evaluation_max_tokens,
        )
        payload = parse_json_response(response)
        if isinstance(payload, list):
            payload = payload[0]
        legacy_weights = {
            "novelty_weight": mcts.config.novelty_weight,
            "surprise_weight": mcts.config.surprise_weight,
            "impact_weight": mcts.config.impact_weight,
            "feasibility_weight": mcts.config.feasibility_weight,
            "clarity_weight": mcts.config.clarity_weight,
            "conciseness_weight": mcts.config.conciseness_weight,
            "risk_weight": mcts.config.risk_weight,
            "alignment_weight": mcts.config.alignment_weight,
            "complexity_weight": mcts.config.complexity_weight,
            "protocol_weight": mcts.config.protocol_weight,
            "explanatory_power_weight": getattr(
                mcts.config, "explanatory_power_weight", 0.06
            ),
            "identifiability_weight": getattr(
                mcts.config, "identifiability_weight", 0.06
            ),
            "boundary_calibration_weight": getattr(
                mcts.config, "boundary_calibration_weight", 0.04
            ),
            "claim_overreach_weight": getattr(
                mcts.config, "claim_overreach_weight", 0.10
            ),
        }
        evaluation = idea_evaluation_cls.from_payload(
            payload,
            weights=profile_score_weights(profile_id, legacy_weights),
            profile_id=profile_id,
        )
    except Exception as exc:
        log_message(mcts.logger, mcts.log_sink, "warning", "⚠️  Simulation failed: %s", exc)
        return None

    novelty_override = (
        mcts._score_component_novelty(node.state)
        if profile_id == "computational_algorithmic"
        else None
    )
    if novelty_override is not None:
        evaluation.novelty = round(novelty_override)
        evaluation.novelty_axes["scientific_novelty"] = float(evaluation.novelty)
        novelty_axes = getattr(mcts.component_novelty_scorer, "last_novelty_axes", {})
        if isinstance(novelty_axes, dict):
            evaluation.novelty_axes.update(novelty_axes)

    if evaluation.protocol_score <= 0.0:
        evaluation.protocol_score = mcts._compute_protocol_score(node.state.edit_plan)

    apply_profile_drift_to_evaluation(node, evaluation, profile_drift)

    log_message(
        mcts.logger,
        mcts.log_sink,
        "info",
        "[MCTS] Simulate: node=%s\n[MCTS] Score: %.4f\n%s",
        node.state.title,
        evaluation.composite,
        pretty_json(mcts._simulate_log_payload(evaluation)),
    )

    cache_evaluation(node.state.signature, cache_key, evaluation, mcts.evaluation_cache)
    node.evaluation = evaluation
    node.latest_path_summary = path_summary_text

    maybe_record_experience(
        cache_key,
        node,
        evaluation,
        path_summary_text,
        experiences,
        mcts.experience_cache,
        getattr(mcts, "enable_vector_memory", True),
        mcts.memory_accessor,
        mcts.config.min_confidence_for_memory,
    )

    return evaluation


def backpropagate_rollout(path: List[Any], evaluation: Any) -> None:
    score = evaluation.composite
    for hop in reversed(path):
        hop.visits += 1
        hop.value_sum += score


def reset_search_state(mcts: Any) -> None:
    mcts.signature_nodes = {}
    mcts.evaluation_cache = {}
    mcts.experience_cache.clear()
    mcts.trace = []
    mcts.retrieved_core_titles = []
    mcts._id_iter = itertools.count()


def new_node(
    state: Any,
    depth: int,
    parent: Optional[Any],
    signature_nodes: Dict[str, Any],
    id_iter: Any,
    idea_node_cls: Any,
    operator_application_cls: Any,
) -> Any:
    existing = signature_nodes.get(state.signature)
    if existing:
        return existing
    node = idea_node_cls(
        node_id=next(id_iter),
        state=state,
        depth=depth,
        parent=parent,
        transformation=operator_application_cls(
            operator=state.operator,
            defects=state.target_defects,
            rationale=state.rationale,
            memory_refs=state.memory_refs,
        ),
    )
    signature_nodes[state.signature] = node
    if parent:
        parent.children.append(node)
    return node


def attach_child(
    parent: Any,
    state: Any,
    signature_nodes: Dict[str, Any],
    id_iter: Any,
    idea_node_cls: Any,
    operator_application_cls: Any,
    logger: Any,
    log_sink: Optional[Any] = None,
) -> Optional[Any]:
    child = signature_nodes.get(state.signature)
    if child is None:
        return new_node(
            state,
            depth=parent.depth + 1,
            parent=parent,
            signature_nodes=signature_nodes,
            id_iter=id_iter,
            idea_node_cls=idea_node_cls,
            operator_application_cls=operator_application_cls,
        )
    if child is parent or is_ancestor(parent, child):
        return None
    if child not in parent.children:
        parent.children.append(child)
    return child


def is_ancestor(node: Any, candidate: Any) -> bool:
    cursor: Optional[Any] = node
    while cursor is not None:
        if cursor is candidate:
            return True
        cursor = cursor.parent
    return False


def path_summary(path: Sequence[Any], limit: int = 2048) -> str:
    steps: List[str] = []
    for hop in path:
        defects = hop.transformation.defects or ["unspecified"]
        steps.append(f"{hop.state.title} [{hop.transformation.operator}] -> defects {defects}")
    return clip_text(" | ".join(steps), limit)


def evaluation_prompt_cache_key(
    prompt_text: str,
    *,
    rubric_version: str = SCIENTIFIC_RUBRIC_VERSION,
    profile_version: str = SCIENTIFIC_INTERVENTION_PROFILE_VERSION,
    profile_id: str = "generic_scientific",
) -> str:
    cache_material = "\n".join(
        [
            str(rubric_version),
            str(profile_version),
            str(profile_id),
            str(prompt_text),
        ]
    )
    return hashlib.sha256(cache_material.encode("utf-8")).hexdigest()


def get_cached_evaluation(
    signature: str,
    path_key: str,
    evaluation_cache: Dict[str, Dict[str, Any]],
) -> Optional[Any]:
    sig_cache = evaluation_cache.get(signature)
    if not sig_cache:
        return None
    return sig_cache.get(path_key)


def cache_evaluation(
    signature: str,
    path_key: str,
    evaluation: Any,
    evaluation_cache: Dict[str, Dict[str, Any]],
) -> None:
    evaluation_cache.setdefault(signature, {})[path_key] = evaluation


def get_best_cached_evaluation(
    signature: str,
    evaluation_cache: Dict[str, Dict[str, Any]],
) -> Optional[Any]:
    sig_cache = evaluation_cache.get(signature)
    if not sig_cache:
        return None
    return max(sig_cache.values(), key=lambda ev: ev.composite)


def maybe_record_experience(
    cache_key: str,
    node: Any,
    evaluation: Any,
    path_summary_text: str,
    experiences: List[Dict[str, Any]],
    experience_cache: Set[str],
    enable_vector_memory: bool,
    memory_accessor: Any,
    min_confidence_for_memory: float,
) -> None:
    if not enable_vector_memory:
        return
    if cache_key in experience_cache:
        return
    experience = harvest_experience(
        node,
        evaluation,
        path_summary_text,
        min_confidence_for_memory,
    )
    if not experience:
        return
    memory_accessor.persist_experience(experience)
    experiences.append(experience)
    experience_cache.add(cache_key)


def build_root_state(
    topic: str,
    context: Dict[str, Any],
    idea_state_cls: Any,
) -> Any:
    latest_candidate = context.get("latest_candidate")
    root_idea = context.get("root_idea")
    mature_value = context.get("mature_idea")
    mature_record = context.get("mature_idea_record")
    if isinstance(mature_value, Mapping):
        mature_record = mature_value
    if isinstance(mature_record, Mapping):
        mature_record = normalize_mature_idea(mature_record)
        mature_idea = str(
            mature_record.get("hypothesis")
            or mature_record.get("abstract")
            or mature_record.get("title")
            or ""
        ).strip()
    else:
        mature_idea = str(mature_value or "").strip()
    background = context.get("background_knowledge") or []
    raw_defect_tags = context.get("defect_tags")
    if isinstance(raw_defect_tags, (list, tuple)):
        defect_tags = [str(tag).strip() for tag in raw_defect_tags if str(tag).strip()]
    elif str(raw_defect_tags or "").strip():
        defect_tags = [str(raw_defect_tags).strip()]
    else:
        defect_tags = []
    components = context.get("components") if isinstance(context.get("components"), list) else []
    context_component_explanations = (
        context.get("component_explanations")
        if isinstance(context.get("component_explanations"), (dict, list))
        else {}
    )
    root_domains = context.get("root_domains") if isinstance(context.get("root_domains"), list) else []
    discipline_resolution = (
        context.get("discipline_resolution")
        if isinstance(context.get("discipline_resolution"), dict)
        else {}
    )
    latest_payload: Dict[str, Any] = {}

    if mature_idea:
        title = re.split(r"(?<=[.!?])\s+", mature_idea, maxsplit=1)[0].strip() or f"{topic} mature idea"
        abstract = mature_idea
        core = mature_idea
        method = mature_idea
        risks = "Primary risk is mechanism drift away from the mature idea during refinement."
        tags = ["seed", "mature_idea", "contract_root"]
        rationale = "Starting point anchored directly in the selected mature idea seed."
        if isinstance(mature_record, Mapping):
            title = str(mature_record.get("title") or title).strip()
            abstract = str(mature_record.get("abstract") or abstract).strip()
            core = str(
                mature_record.get("central_hypothesis")
                or mature_record.get("hypothesis")
                or core
            ).strip()
            method = str(
                mature_record.get("mechanism_or_relation")
                or mature_record.get("mechanism")
                or method
            ).strip()
            risks = "Primary risk is falsification of the mature idea mechanism or its stated assumptions."
            tags = ["seed", "mature_idea", "contract_root", str(mature_record.get("idea_id") or "")]
            tags = [tag for tag in tags if tag]
    elif isinstance(latest_candidate, dict) and latest_candidate:
        latest_payload = normalize_idea_contract(latest_candidate, keep_extra=True)
        title = latest_payload.get("title", f"{topic} seed idea")
        abstract = latest_payload.get("abstract", "")
        core = latest_payload.get("core_contribution", "")
        method = latest_payload.get("method", "")
        risks = latest_payload.get("risks", latest_payload.get("evaluation", ""))
        tags = latest_payload.get("tags")
        rationale = "Starting point from the latest candidate in the current run."
        if not components and isinstance(latest_payload.get("components"), list):
            components = [str(comp).strip() for comp in latest_payload.get("components", []) if str(comp).strip()]
        if not context_component_explanations:
            context_component_explanations = latest_payload.get("component_explanations", {})
    elif isinstance(root_idea, dict) and root_idea:
        latest_payload = normalize_idea_contract(root_idea, keep_extra=True)
        title = latest_payload.get("title", f"{topic} root idea")
        abstract = latest_payload.get("abstract", "")
        core = latest_payload.get("core_contribution", "")
        method = latest_payload.get("method", "")
        risks = latest_payload.get("risks", latest_payload.get("evaluation", ""))
        tags = latest_payload.get("tags")
        rationale = "Starting point from the explicit root idea produced by advanced analysis."
        if not components and isinstance(latest_payload.get("components"), list):
            components = [str(comp).strip() for comp in latest_payload.get("components", []) if str(comp).strip()]
        if not context_component_explanations:
            context_component_explanations = latest_payload.get("component_explanations", {})
    else:
        title = f"{topic} baseline"
        abstract = background[-1] if background else "Kick-off seed idea from analysis."
        core = "Seed idea derived from current analysis and background knowledge."
        method = "Synthesize referenced methods and expose unresolved bottlenecks."
        risks = "Need fairness checks and failure-mode surfacing."
        tags = ["seed"]
        rationale = "Starting point from existing analysis and background knowledge."

    profile_payload = context.get("scientific_intervention_profile")
    existing_intervention = context.get("scientific_intervention")
    if not isinstance(existing_intervention, dict):
        existing_intervention = latest_payload.get("scientific_intervention")
    profile_resolution: Dict[str, Any] = {}
    if isinstance(profile_payload, dict):
        profile_resolution.update(profile_payload)
    if isinstance(existing_intervention, dict) and existing_intervention.get("profile_id"):
        profile_resolution.setdefault("profile_id", existing_intervention.get("profile_id"))
    profile_resolution.update(discipline_resolution)
    profile = resolve_scientific_intervention_profile(
        profile_resolution,
        root_domains=root_domains,
        project_context=(
            context.get("project_context")
            if isinstance(context.get("project_context"), dict)
            else None
        ),
    )
    if profile is None:
        profile = get_scientific_intervention_profile("generic_scientific")
    if profile is None:  # pragma: no cover - registry invariant
        raise RuntimeError("generic_scientific intervention profile is unavailable")
    if profile.profile_id != "computational_algorithmic" and components:
        forbidden_algorithm_components = set(profile.forbidden_default_patterns)
        idea_text = " ".join(
            str(value or "")
            for value in (title, abstract, core, method)
        ).lower()
        high_precision_algorithm_terms = re.search(
            r"\b(?:algorithm(?:ic)?|machine\s+learning|deep\s+learning|neural\s+(?:network|model)|model\s+training|training\s+(?:a|the)\s+(?:model|network)|model\s+inference|inference[- ]time|trained\s+model|learned\s+(?:model|representation))\b",
            idea_text,
        )
        algorithmic_compound_terms = re.search(
            r"\b(?:algorithmic|machine[- ]learning|deep[- ]learning|neural|trained|learned)\s+(?:predictor|classifier|optimizer|surrogate\s+model|computational\s+(?:model|method))\b",
            idea_text,
        )
        algorithm_explicit = bool(high_precision_algorithm_terms or algorithmic_compound_terms)
        if not algorithm_explicit:
            components = [
                component
                for component in components
                if component not in forbidden_algorithm_components
            ]
    if not defect_tags:
        defect_tags = list(profile.defect_tags) or ["unexplored_gap"]
    if not components:
        components = profile.default_component_names()
    component_explanations = normalize_component_explanations(
        components,
        context_component_explanations,
    )
    scientific_intervention = build_scientific_intervention_payload(
        profile,
        components,
        component_explanations,
        existing_intervention,
    )
    seed_identity = str(
        context.get("seed_id")
        or context.get("idea_id")
        or (mature_record.get("idea_id") if isinstance(mature_record, Mapping) else "")
        or ""
    ).strip()
    route_identity = str(context.get("route_id") or "").strip()
    seed_gap_ids = context.get("target_gap_ids")
    if not isinstance(seed_gap_ids, list) and isinstance(mature_record, Mapping):
        seed_gap_ids = mature_record.get("target_gap_ids")
    seed_gap_ids = [str(item).strip() for item in (seed_gap_ids or []) if str(item).strip()]
    hypothesis_contract = dict(scientific_intervention.get("hypothesis_contract") or {})
    if seed_gap_ids:
        hypothesis_contract["target_gap_ids"] = seed_gap_ids
    if isinstance(mature_record, Mapping):
        for field_name, source_name in (
            ("central_hypothesis", "central_hypothesis"),
            ("scientific_object", "scientific_object"),
            ("mechanism_or_relation", "mechanism_or_relation"),
            ("assumptions", "assumptions"),
            ("evidence_basis", "evidence_basis"),
        ):
            value = mature_record.get(source_name)
            if value not in (None, "", [], {}):
                hypothesis_contract.setdefault(field_name, value)
    if hypothesis_contract:
        scientific_intervention["hypothesis_contract"] = hypothesis_contract
    if seed_identity:
        scientific_intervention["seed_id"] = seed_identity
    if route_identity:
        scientific_intervention["route_id"] = route_identity
        scientific_intervention["route_policy"] = context.get("route_policy") or {}
    routed_gap_context = {
        key: [dict(item) for item in context.get(key, []) if isinstance(item, dict)]
        for key in (
            "active_gaps",
            "provisional_gaps",
            "supporting_constraints",
            "verification_only_gaps",
            "future_work_seeds",
        )
        if isinstance(context.get(key), list) and context.get(key)
    }
    if routed_gap_context:
        scientific_intervention["gap_routing"] = routed_gap_context
    gap_hypothesis_seeds = [
        dict(seed)
        for seed in context.get("gap_hypothesis_seeds", [])
        if isinstance(seed, dict) and str(seed.get("seed_id") or "").strip()
    ]
    if gap_hypothesis_seeds:
        hypothesis_seed_refs = []
        for seed in gap_hypothesis_seeds:
            seed_ref = {
                "seed_id": str(seed.get("seed_id") or "").strip(),
                "gap_id": str(seed.get("gap_id") or "").strip(),
                "gap_route": str(seed.get("gap_route") or "").strip(),
                "seed_status": str(seed.get("seed_status") or "").strip(),
                "target_slot": str(seed.get("target_slot") or "").strip(),
            }
            if is_data_anchored(seed):
                seed_ref.update(
                    {
                        "analysis_priority": DATA_ANCHORED_PRIORITY,
                        "data_anchor_refs": list(seed.get("data_anchor_refs") or []),
                        "literature_reconciliation_status": str(
                            seed.get("literature_reconciliation_status") or "unresolved"
                        ),
                    }
                )
            hypothesis_seed_refs.append(seed_ref)
        scientific_intervention["hypothesis_seed_refs"] = hypothesis_seed_refs
        scientific_intervention["gap_seed_status"] = (
            dict(context.get("gap_seed_status"))
            if isinstance(context.get("gap_seed_status"), dict)
            else {}
        )
    data_anchored_context = context.get("data_anchored_context")
    if not isinstance(data_anchored_context, Mapping) and isinstance(mature_record, Mapping):
        data_anchored_context = mature_record
    if is_data_anchored(data_anchored_context):
        scientific_intervention["data_anchored_contract"] = {
            "data_anchor_refs": list(data_anchored_context.get("data_anchor_refs") or []),
            "literature_reconciliation_status": str(
                data_anchored_context.get("literature_reconciliation_status") or "unresolved"
            ),
            "competing_explanations": list(
                data_anchored_context.get("competing_explanations") or []
            ),
            "measurement_needs": list(data_anchored_context.get("measurement_needs") or []),
            "claim_limits": list(data_anchored_context.get("claim_limits") or []),
            "mcts_depth_multiplier": float(
                data_anchored_context.get("mcts_depth_multiplier") or 1.75
            ),
            "coverage_branches": list(
                data_anchored_context.get("coverage_branches") or []
            ),
        }
        coverage_assignment = data_anchored_context.get(
            "data_anchored_coverage_assignment"
        )
        if isinstance(coverage_assignment, Mapping):
            scientific_intervention["data_anchored_contract"][
                "coverage_assignment"
            ] = dict(coverage_assignment)

    return idea_state_cls(
        title=str(title),
        abstract=str(abstract),
        core_contribution=str(core),
        method=str(method),
        risks=str(risks),
        tags=[str(t) for t in tags] if isinstance(tags, list) else [str(tags)],
        operator="seed",
        target_defects=[str(tag) for tag in defect_tags],
        rationale=str(rationale),
        memory_refs=[],
        components=components,
        component_explanations=component_explanations,
        root_domains=[str(domain).strip() for domain in root_domains if str(domain).strip()][:2],
        discipline_resolution=discipline_resolution,
        scientific_intervention=scientific_intervention,
        paper_graph_context=str(context.get("paper_context") or ""),
    )


def best_candidate(root: Any, candidate_cls: Any) -> Optional[Any]:
    candidates: List[Any] = []
    stack = [root]
    visited: Set[int] = set()
    while stack:
        node = stack.pop()
        if node.node_id in visited:
            continue
        visited.add(node.node_id)
        if node.evaluation:
            candidates.append(candidate_cls(node=node, evaluation=node.evaluation))
        stack.extend(node.children)
    if not candidates:
        return None
    return max(candidates, key=lambda c: c.evaluation.composite)


def pareto_candidates(root: Any, candidate_cls: Any) -> Dict[str, Optional[Any]]:
    by_metric = {
        "novel": lambda ev: ev.novelty,
        "feasible": lambda ev: ev.feasibility,
        "concise": lambda ev: ev.conciseness,
    }
    pareto: Dict[str, Optional[Any]] = {k: None for k in by_metric}
    stack = [root]
    visited_ids: Set[int] = set()
    visited: List[Any] = []
    while stack:
        node = stack.pop()
        if node.node_id in visited_ids:
            continue
        visited_ids.add(node.node_id)
        if node.evaluation:
            visited.append(candidate_cls(node=node, evaluation=node.evaluation))
        stack.extend(node.children)

    for label, scorer in by_metric.items():
        if visited:
            pareto[label] = max(visited, key=lambda c, s=scorer: s(c.evaluation))
    return pareto


def harvest_experience(
    node: Any,
    evaluation: Any,
    path_summary_text: str,
    min_confidence_for_memory: float,
) -> Optional[Dict[str, Any]]:
    if evaluation.confidence > min_confidence_for_memory:
        experience = {
            "defect": ", ".join(node.state.target_defects) or evaluation.defect_fix_summary,
            "action": node.state.operator,
            "idea": node.state.title,
            "context": path_summary_text,
            "feedback": evaluation.feedback,
            "tags": node.state.tags + ["defect_fix"],
            "edit_plan": node.state.edit_plan,
        }
        return experience
    return None
