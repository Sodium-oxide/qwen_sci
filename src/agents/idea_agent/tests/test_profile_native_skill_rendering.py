from __future__ import annotations

from src.agents.idea_agent.utils.mcts.mcts_runtime import SkillCatalog
from src.agents.idea_agent.utils.mcts.scientific_intervention_ontology import (
    get_scientific_intervention_profile,
    get_scientific_object_schema,
)


def test_profile_payload_exposes_native_object_schema() -> None:
    profile = get_scientific_intervention_profile("clinical_health")
    assert profile is not None
    payload = profile.to_payload()
    schema = payload["scientific_object_schema"]
    assert "intervention_or_exposure" in schema["object_types"]
    assert "intervene" in schema["allowed_operations"]
    assert "clinical_endpoint" in schema["measurement_or_observation_roles"]
    assert "safety_or_external_validity_boundary" in schema["boundary_condition_roles"]


def test_non_cs_skill_rendering_uses_native_placeholders() -> None:
    catalog = SkillCatalog()
    schema = get_scientific_object_schema("physical_materials_chemical")
    assert schema is not None
    rendered = catalog.render_skill_for_profile(
        "feedback-closed-loop",
        "physical_materials_chemical",
        schema,
    )
    blueprint = " ".join(rendered.atomic_blueprint)
    assert "feedback_monitor" not in blueprint
    assert "adaptation_rule" not in blueprint
    assert "characterization_feedback" in blueprint
    assert "profile-native" in " ".join(rendered.guardrails)
    assert "characterize" in rendered.preferred_operations


def test_cs_skill_rendering_preserves_legacy_blueprint() -> None:
    catalog = SkillCatalog()
    base = catalog.skills["mechanism-commit-innovation"]
    rendered = catalog.render_skill_for_profile(
        base,
        "computational_algorithmic",
        get_scientific_object_schema("computational_algorithmic"),
    )
    assert rendered.atomic_blueprint == base.atomic_blueprint
    assert rendered.rendered_profile_id == "computational_algorithmic"


def test_catalog_prompt_can_render_native_operation_reference() -> None:
    catalog = SkillCatalog()
    prompt = catalog.format_for_prompt(
        profile_id="formal_theoretical",
        object_schema=get_scientific_object_schema("formal_theoretical"),
    )
    assert "profile-native scientific objects" in prompt
    assert "proof_or_verification" in prompt
    assert "data flow" not in prompt.lower()


def test_non_cs_skill_prompt_hides_architecture_skills() -> None:
    catalog = SkillCatalog()
    prompt = catalog.format_for_prompt(
        profile_id="clinical_health",
        object_schema=get_scientific_object_schema("clinical_health"),
    )
    assert "surgical-modularity" not in prompt
    assert "speculative-execution-with-repair" not in prompt
    assert "pipeline" not in prompt.lower()


def test_profile_selection_disables_speculation_for_non_operational_profiles() -> None:
    catalog = SkillCatalog()
    selected = catalog.select_skills(
        defect_tags=["rollback_blindspot"],
        max_children=8,
        structural_profile={
            "control_centered": True,
            "scope_kind": "execution_path",
            "training_free_like": False,
            "has_multi_path_shape": True,
        },
        profile_id="formal_theoretical",
    )
    assert all(item.skill.name != "speculative-execution-with-repair" for item in selected)


def test_profile_native_defects_contribute_to_skill_overlap() -> None:
    catalog = SkillCatalog()
    selected = catalog.select_skills(
        defect_tags=["missing_boundary_condition"],
        max_children=8,
        structural_profile={
            "control_centered": True,
            "scope_kind": "execution_path",
            "training_free_like": False,
            "has_multi_path_shape": True,
        },
        profile_id="clinical_health",
    )
    alternative = next(
        item for item in selected if item.skill.name == "alternative-path-contrast"
    )
    assert alternative.defect_score > 0.0


def test_non_cs_feedback_skill_can_use_observation_loop_without_control_center() -> None:
    catalog = SkillCatalog()
    selected = catalog.select_skills(
        defect_tags=["measurement_construct_mismatch"],
        max_children=8,
        structural_profile={
            "profile_id": "physical_materials_chemical",
            "control_centered": False,
            "scope_kind": "existing_subsystem",
            "training_free_like": False,
            "has_multi_path_shape": False,
        },
        profile_id="physical_materials_chemical",
    )
    feedback = next(item for item in selected if item.skill.name == "feedback-closed-loop")
    assert feedback.structure_fit > 0.0
