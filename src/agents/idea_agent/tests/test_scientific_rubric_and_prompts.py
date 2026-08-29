from __future__ import annotations

import importlib
import sys
import types
from types import SimpleNamespace

import pytest

from src.agents.idea_agent.agent.prompts.component_extraction import (
    COMPONENT_EXTRACTION_PROMPT,
)
from src.agents.idea_agent.agent.prompts.advanced_analysis import (
    ADVANCED_ANALYSIS_PROMPT,
    render_advanced_analysis_prompt,
)
from src.agents.idea_agent.agent.prompts.idea_fusion import (
    IDEA_FUSION_PROMPT,
    render_idea_fusion_prompt,
)
from src.agents.idea_agent.agent.prompts.mcts_evaluation import (
    MCTS_IDEA_EVALUATION_PROMPT,
)
from src.agents.idea_agent.agent.prompts.mcts_generation import (
    MCTS_IDEA_GENERATION_PROMPT,
)
from src.agents.idea_agent.agent.prompts.skill_instantiation import (
    SKILL_INSTANTIATION_PROMPT,
)
from src.agents.idea_agent.utils.mcts.defect_registry import format_defect_registry
from src.agents.idea_agent.utils.mcts.defect_registry import profile_skill_defect_tags
from src.agents.idea_agent.utils.mcts.idea_taste_presets import (
    SCORE_WEIGHT_FIELDS,
    get_idea_taste_preset,
)
from src.agents.idea_agent.utils.mcts.mcts_runtime import (
    _contract_from_instantiation,
    _direction_prompt_context,
    _route_contract_incomplete_fields,
    _route_contract_noop_fields,
    EditPlan,
    evaluation_prompt_cache_key,
    materialize_child_state,
    merge_hypothesis_contract,
    ValidationProtocol,
)
from src.agents.idea_agent.utils.mcts.scientific_intervention_ontology import (
    format_scientific_intervention_profile_for_prompt,
    get_scientific_intervention_profile,
)
from src.agents.idea_agent.utils.mcts.scientific_rubric import (
    format_scientific_rubric_for_prompt,
)
from src.agents.idea_agent.utils.workflow.idea_contract import normalize_idea_contract


def _profile_payload(profile_id: str) -> dict[str, object]:
    profile = get_scientific_intervention_profile(profile_id)
    assert profile is not None
    payload = profile.to_payload()
    payload["contribution_mode"] = profile.contribution_modes[0].mode_id
    return payload


def test_profile_text_is_injected_into_generation_and_extraction_prompts() -> None:
    profile_text = format_scientific_intervention_profile_for_prompt(
        _profile_payload("physical_materials_chemical")
    )
    assert "physical_materials_chemical" in profile_text
    assert "structure_property_mechanism" in profile_text
    generation = MCTS_IDEA_GENERATION_PROMPT.format(
        topic="battery degradation",
        direction_mode="evidence_first",
        direction_summary="Prefer defensible evidence.",
        taste_guidance="Use a narrow mechanism.",
        target_gap_ids="gap-1",
        profile_id="physical_materials_chemical",
        scientific_intervention_profile=profile_text,
        profile_native_object_schema="{}",
        gap_seed_context="seed-1",
        current_summary="parent",
        paper_context="papers",
        memory_bundle="memory",
        edit_operators="ops",
        constraints="constraints",
        max_children=2,
    )
    extraction = COMPONENT_EXTRACTION_PROMPT.format(
        mature_idea="materials idea",
        topic="battery degradation",
        scientific_intervention_profile=profile_text,
        prior_components="[]",
        component_decisions="[]",
    )
    assert "physical_materials_chemical" in generation
    assert "physical_materials_chemical" in extraction
    assert "Training signals and model objectives are primary only" in generation
    assert "flow_matching_generator" not in COMPONENT_EXTRACTION_PROMPT
    assert "controllability_gramian" not in COMPONENT_EXTRACTION_PROMPT
    assert "proof_obligation" in COMPONENT_EXTRACTION_PROMPT


def test_skill_prompt_accepts_profile_native_objects_and_roles() -> None:
    profile_text = format_scientific_intervention_profile_for_prompt(
        _profile_payload("formal_theoretical")
    )
    prompt = SKILL_INSTANTIATION_PROMPT.format(
        topic="mathematical dynamics",
        root_domains="mathematics",
        scientific_intervention_profile=profile_text,
        refinement_scope="theorem assumptions",
        taste_guidance="none",
        mature_idea="theorem",
        parent_summary="parent",
        parent_components="proof_object",
        paper_context="papers",
        memory_bundle="memory",
        skill_references="references",
        additional_retrieval_context="",
        skill_name="mechanism-commit-innovation",
        plan_objective="repair proof gap",
        target_defects="proof_gap",
        component_edits="[]",
        validation_protocols="counterexample",
        guardrails="none",
    )
    assert "formal_theoretical" in prompt
    assert "scientific object, role, mechanism, process, relation" in prompt


def test_profiles_expose_native_contribution_modes() -> None:
    for profile_id in (
        "physical_materials_chemical",
        "clinical_health",
        "formal_theoretical",
        "computational_algorithmic",
    ):
        profile = get_scientific_intervention_profile(profile_id)
        assert profile is not None
        assert profile.contribution_modes
        assert all(mode.mode_id for mode in profile.contribution_modes)


def test_non_cs_rubric_does_not_require_training_signal() -> None:
    rubric = format_scientific_rubric_for_prompt(
        _profile_payload("clinical_health")
    )
    assert "not universal quality requirements" not in rubric
    assert "training signal" not in rubric
    assert "native objects" in rubric
    assert "causal" in rubric.lower()


def test_non_cs_early_prompts_use_profile_neutral_vocabulary() -> None:
    advanced = render_advanced_analysis_prompt(
        ADVANCED_ANALYSIS_PROMPT.format(
            topic="clinical endpoint",
            mature_idea="",
            mature_idea_source="empty",
            refinement_scope="",
            refinement_scope_source="empty",
            survey_contents="",
            papers="",
            experiment_findings="None",
        ),
        "clinical_health",
    ).lower()
    fusion = render_idea_fusion_prompt(
        IDEA_FUSION_PROMPT.format(
            topic="clinical endpoint",
            mature_idea="",
            refinement_scope="",
            root_domains="medicine",
            scientific_intervention_profile="clinical_health",
            scientific_object_schema="{}",
            analysis="",
            mode_count=2,
            candidate_ideas_json="[]",
        ),
        "clinical_health",
    ).lower()
    for prompt in (advanced, fusion):
        assert "training signals" not in prompt
        assert "task-solving mechanism" not in prompt
        assert "gate/router/controller" not in prompt
        assert "specific computational role" not in prompt


def test_evaluation_prompt_accepts_profile_and_rubric_blocks() -> None:
    rendered = MCTS_IDEA_EVALUATION_PROMPT.format(
        topic="clinical endpoint",
        direction_mode="evidence_first",
        direction_summary="Prefer defensible evidence.",
        taste_guidance="Use a narrow mechanism.",
        target_gap_ids="gap-1",
        profile_id="clinical_health",
        gap_seed_context="seed-1",
        root_domains="medicine",
        mature_idea="causal intervention",
        refinement_scope="mediator identification",
        edit_plan="plan",
        idea="candidate",
        scientific_intervention_profile=format_scientific_intervention_profile_for_prompt(
            _profile_payload("clinical_health")
        ),
        profile_native_object_schema="{}",
        scientific_rubric=format_scientific_rubric_for_prompt(
            _profile_payload("clinical_health")
        ),
        defect_registry=format_defect_registry("clinical_health"),
        symbolic_memory_hints="none",
    )
    assert '"explanatory_power": 0-5' in rendered
    assert "clinical_health" in rendered


def test_direction_context_exposes_mode_profile_and_gap_seeds() -> None:
    preset = get_idea_taste_preset("evidence_first")
    assert preset is not None
    mcts = SimpleNamespace(
        idea_taste_preset=preset,
        scientific_intervention_profile={
            "profile_id": "physical_materials_chemical",
            "scientific_object_schema": {"object_types": ["material_process"]},
        },
        gap_hypothesis_seeds=[{"gap_id": "gap-1"}],
        gap_seed_context="seed-1",
    )
    state = SimpleNamespace(scientific_intervention={})

    context = _direction_prompt_context(mcts, state)

    assert context["direction_mode"] == "evidence_first"
    assert context["profile_id"] == "physical_materials_chemical"
    assert context["target_gap_ids"] == "gap-1"
    assert "seed-1" in context["gap_seed_context"]
    assert "material_process" in context["profile_native_object_schema"]


def test_optional_scientific_contract_fields_are_preserved_without_new_required_fields() -> None:
    normalized = normalize_idea_contract(
        {
            "title": "A hypothesis",
            "abstract": "A concise abstract.",
            "core_contribution": "A scientific claim.",
            "method": "A profile-native method.",
            "direction_mode": "bridge_builder",
            "central_hypothesis": "The relation changes under the condition.",
            "scientific_object": {"object_type": "process"},
            "target_gap_ids": ["gap-1"],
            "gap_alignment": [{"gap_id": "gap-1", "alignment": "direct"}],
            "evidence_basis": ["SURVEY_ANCHOR: mechanism remains unresolved"],
            "experiment_design": "must be discarded",
        }
    )

    assert normalized["direction_mode"] == "bridge_builder"
    assert normalized["central_hypothesis"] == "The relation changes under the condition."
    assert normalized["scientific_object"] == {"object_type": "process"}
    assert normalized["target_gap_ids"] == ["gap-1"]
    assert normalized["gap_alignment"] == [{"gap_id": "gap-1", "alignment": "direct"}]
    assert normalized["evidence_basis"] == ["SURVEY_ANCHOR: mechanism remains unresolved"]
    assert "experiment_design" not in normalized


def test_instantiation_contract_collects_top_level_scientific_fields() -> None:
    contract = _contract_from_instantiation(
        {
            "central_hypothesis": "A claim",
            "target_gap_ids": ["gap-1"],
            "evidence_basis": ["anchor-1"],
            "scientific_contract": {"direction_mode": "moonshot_inventor"},
        }
    )

    assert contract == {
        "direction_mode": "moonshot_inventor",
        "central_hypothesis": "A claim",
        "target_gap_ids": ["gap-1"],
        "evidence_basis": ["anchor-1"],
    }


def test_child_contract_inherits_parent_fields_without_treating_blanks_as_clears() -> None:
    parent_contract = {
        "central_hypothesis": "The relation changes under a bounded condition.",
        "mechanism_or_relation": "A native mediator links the intervention to the outcome.",
        "target_gap_ids": ["gap-1"],
        "claim_scope": "The measured operating regime.",
    }
    child_contract = {
        "central_hypothesis": "",
        "claim_scope": "A narrower operating regime.",
    }

    merged = merge_hypothesis_contract(parent_contract, child_contract)

    assert merged["central_hypothesis"] == parent_contract["central_hypothesis"]
    assert merged["mechanism_or_relation"] == parent_contract["mechanism_or_relation"]
    assert merged["target_gap_ids"] == ["gap-1"]
    assert merged["claim_scope"] == "A narrower operating regime."


def test_route_specific_omission_is_marked_instead_of_being_silently_inherited() -> None:
    parent_contract = {
        "scientific_object": {"object_type": "parent_object"},
        "mechanism_or_relation": "parent mechanism",
        "expected_mechanism": "parent expectation",
    }

    assert _route_contract_incomplete_fields(
        "mechanism_replacement",
        parent_contract,
        {},
    ) == ["mechanism_or_relation"]
    assert _route_contract_incomplete_fields(
        "object_substitution",
        parent_contract,
        {"scientific_object": {"object_type": "child_object"}},
    ) == []
    assert _route_contract_noop_fields(
        "mechanism_replacement",
        parent_contract,
        {"mechanism_or_relation": "parent mechanism"},
    ) == ["mechanism_or_relation"]
    assert _route_contract_noop_fields(
        "object_substitution",
        parent_contract,
        {"scientific_object": {"object_type": "parent_object"}},
    ) == ["scientific_object"]


def test_materialized_child_preserves_parent_contract_and_marks_missing_route_change() -> None:
    parent = SimpleNamespace(
        title="Parent hypothesis",
        abstract="Parent abstract",
        core_contribution="Parent contribution",
        method="Parent method",
        risks="Parent risks",
        tags=["parent"],
        target_defects=["unexplored_gap"],
        components=[],
        component_explanations={},
        root_domains=["physics"],
        discipline_resolution={},
        paper_graph_context="",
        scientific_intervention={
            "hypothesis_contract": {
                "central_hypothesis": "Parent hypothesis remains available.",
                "mechanism_or_relation": "Parent mechanism must not disappear.",
                "target_gap_ids": ["gap-1"],
            }
        },
    )
    plan = EditPlan(
        skill_name="route-test",
        objective="Refine the mechanism.",
        target_defects=["unexplored_gap"],
        component_edits=[],
        validation=ValidationProtocol(),
        guardrails=[],
        memory_refs=[],
        compile_notes="test plan",
    )
    mcts = SimpleNamespace(
        route_id="mechanism_replacement",
        idea_taste_preset=None,
        _skill_prior_for_prompt=lambda _skill_name: 0.0,
    )

    child = materialize_child_state(
        mcts,
        parent,
        plan,
        {"claim_scope": "A narrower scope."},
        idea_state_cls=lambda **payload: SimpleNamespace(**payload),
    )

    contract = child.scientific_intervention["hypothesis_contract"]
    assert contract["central_hypothesis"] == "Parent hypothesis remains available."
    assert contract["mechanism_or_relation"] == "Parent mechanism must not disappear."
    assert contract["claim_scope"] == "A narrower scope."
    assert child.scientific_intervention["route_contract_incomplete_fields"] == [
        "mechanism_or_relation"
    ]


def test_materialized_child_marks_parent_mechanism_restatement_as_route_noop() -> None:
    parent = SimpleNamespace(
        title="Parent hypothesis",
        abstract="Parent abstract",
        core_contribution="Parent contribution",
        method="Parent method",
        risks="Parent risks",
        tags=["parent"],
        target_defects=["unexplored_gap"],
        components=[],
        component_explanations={},
        root_domains=["physics"],
        discipline_resolution={},
        paper_graph_context="",
        scientific_intervention={
            "hypothesis_contract": {
                "mechanism_or_relation": "Parent mechanism.",
                "target_gap_ids": ["gap-1"],
            }
        },
    )
    plan = EditPlan(
        skill_name="route-test",
        objective="Replace the mechanism.",
        target_defects=["unexplored_gap"],
        component_edits=[],
        validation=ValidationProtocol(),
        guardrails=[],
        memory_refs=[],
        compile_notes="test plan",
    )
    mcts = SimpleNamespace(
        route_id="mechanism_replacement",
        idea_taste_preset=None,
        _skill_prior_for_prompt=lambda _skill_name: 0.0,
    )

    child = materialize_child_state(
        mcts,
        parent,
        plan,
        {"mechanism_or_relation": "Parent mechanism."},
        idea_state_cls=lambda **payload: SimpleNamespace(**payload),
    )

    assert "route_contract_incomplete_fields" not in child.scientific_intervention
    assert child.scientific_intervention["route_contract_noop_fields"] == [
        "mechanism_or_relation"
    ]
    assert child.scientific_intervention["route_contract_parent_values"] == {
        "mechanism_or_relation": "Parent mechanism."
    }


def test_profile_priority_defects_are_visible() -> None:
    registry = format_defect_registry("formal_theoretical")
    assert "Profile priority: formal_theoretical" in registry
    assert "missing_assumption [profile-priority]" in registry
    assert "proof_gap [profile-priority]" in registry


def test_profile_priority_defects_drive_skill_overlap() -> None:
    assert "missing_boundary_condition" in profile_skill_defect_tags(
        "clinical_health",
        "alternative-path-contrast",
    )
    assert "proof_gap" in profile_skill_defect_tags(
        "formal_theoretical",
        "theory-transfer-injection",
    )


def test_taste_presets_include_scientific_weights_and_normalize() -> None:
    for mode in ("moonshot_inventor", "bridge_builder", "steady_engineer", "ambitious_realist"):
        preset = get_idea_taste_preset(mode)
        assert preset is not None
        assert set(SCORE_WEIGHT_FIELDS).issubset(preset.weights)
        assert sum(preset.weights[field] for field in SCORE_WEIGHT_FIELDS) == pytest.approx(1.0)


def test_cache_key_changes_with_profile_and_rubric_versions() -> None:
    base = evaluation_prompt_cache_key("candidate")
    other_profile = evaluation_prompt_cache_key("candidate", profile_id="clinical_health")
    other_rubric = evaluation_prompt_cache_key("candidate", rubric_version="scientific_rubric_v2")
    assert base != other_profile
    assert base != other_rubric


def test_idea_evaluation_scientific_dimensions_are_backward_compatible() -> None:
    if "faiss" not in sys.modules:
        sys.modules["faiss"] = types.ModuleType("faiss")
    mcts = importlib.import_module("src.agents.idea_agent.agent.mcts")
    legacy = mcts.IdeaEvaluation.from_payload(
        {
            "novelty": 4,
            "surprise": 3,
            "feasibility": 4,
            "clarity": 3,
            "impact": 4,
            "risk": 1,
            "conciseness": 3,
            "alignment_score": 4,
            "complexity_penalty": 1,
            "protocol_score": 3,
        }
    )
    assert legacy.explanatory_power == 0
    assert "claim_overreach_penalty" in legacy.to_dict()
    low_overreach = mcts.IdeaEvaluation.from_payload(
        {**legacy.to_dict(), "claim_overreach_penalty": 0}
    )
    high_overreach = mcts.IdeaEvaluation.from_payload(
        {**legacy.to_dict(), "claim_overreach_penalty": 5}
    )
    assert low_overreach.composite > high_overreach.composite


def test_fixed_scientific_candidate_fixtures_do_not_lose_to_benchmark_only_cs() -> None:
    if "faiss" not in sys.modules:
        sys.modules["faiss"] = types.ModuleType("faiss")
    mcts = importlib.import_module("src.agents.idea_agent.agent.mcts")

    common = {
        "surprise": 3,
        "feasibility": 4,
        "clarity": 4,
        "impact": 4,
        "risk": 1,
        "conciseness": 3,
        "alignment_score": 4,
        "complexity_penalty": 1,
        "protocol_score": 4,
        "confidence": 0.9,
    }
    benchmark_only_cs = mcts.IdeaEvaluation.from_payload(
        {
            **common,
            "novelty": 5,
            "feasibility": 5,
            "clarity": 3,
            "impact": 3,
            "protocol_score": 2,
            "explanatory_power": 1,
            "identifiability": 1,
            "boundary_calibration": 1,
            "claim_overreach_penalty": 3,
        },
        profile_id="computational_algorithmic",
    )
    fixture_scores = {}
    for name, (profile_id, values) in {
        "materials_mechanism": ("physical_materials_chemical", (4, 5, 5, 4, 1)),
        "medicine_causal": ("clinical_health", (4, 5, 4, 4, 1)),
        "math_counterexample": ("formal_theoretical", (4, 5, 5, 5, 0)),
        "cs_typical": ("computational_algorithmic", (5, 4, 4, 4, 1)),
    }.items():
        novelty, explanatory, identifiability, boundary, overreach = values
        fixture_scores[name] = mcts.IdeaEvaluation.from_payload(
            {
                **common,
                "novelty": novelty,
                "explanatory_power": explanatory,
                "identifiability": identifiability,
                "boundary_calibration": boundary,
                "claim_overreach_penalty": overreach,
            },
            profile_id=profile_id,
        ).composite

    assert fixture_scores["materials_mechanism"] >= benchmark_only_cs.composite
    assert fixture_scores["medicine_causal"] >= benchmark_only_cs.composite
    assert fixture_scores["math_counterexample"] >= benchmark_only_cs.composite
    assert fixture_scores["cs_typical"] >= benchmark_only_cs.composite
