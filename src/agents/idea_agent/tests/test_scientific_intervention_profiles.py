from __future__ import annotations

import pytest

from src.agents.idea_agent.utils.mcts.mcts_runtime import build_root_state
from src.agents.idea_agent.utils.mcts.scientific_intervention_ontology import (
    IGNORED_PAPERSEEK_OPENALEX_FIELDS,
    PAPERSEEK_FIELD_CROSSWALK,
    PAPERSEEK_FIELD_TO_PROFILE,
    RETAINED_PAPERSEEK_OPENALEX_FIELDS,
    get_scientific_field_spec,
    get_scientific_intervention_profile,
    get_scientific_object_spec,
    build_scientific_intervention_payload,
    normalize_project_context_discipline_resolution,
    resolve_scientific_intervention_profile,
)
from src.agents.idea_agent.utils.workflow.idea_contract import normalize_idea_contract


class CaptureIdeaState:
    def __init__(self, **payload: object) -> None:
        self.__dict__.update(payload)


def _resolution(discipline: str) -> dict[str, object]:
    return {
        "status": "resolved",
        "primary_discipline": discipline,
        "discipline_ids": [discipline],
    }


def test_all_retained_paperseek_fields_have_profiles() -> None:
    assert len(RETAINED_PAPERSEEK_OPENALEX_FIELDS) == 20
    assert set(RETAINED_PAPERSEEK_OPENALEX_FIELDS) == set(PAPERSEEK_FIELD_TO_PROFILE)
    assert set(PAPERSEEK_FIELD_CROSSWALK) == set(RETAINED_PAPERSEEK_OPENALEX_FIELDS)
    for field_id in RETAINED_PAPERSEEK_OPENALEX_FIELDS:
        profile = resolve_scientific_intervention_profile(
            {"paperseek_openalex_field_ids": [field_id]}
        )
        assert profile is not None
        assert profile.profile_id == PAPERSEEK_FIELD_TO_PROFILE[field_id]


def test_field_profile_object_registry_covers_retained_fields() -> None:
    for field_id in RETAINED_PAPERSEEK_OPENALEX_FIELDS:
        field_spec = get_scientific_field_spec(field_id)
        assert field_spec is not None
        assert field_spec.primary_profile == PAPERSEEK_FIELD_TO_PROFILE[field_id]
        assert field_spec.object_role_ids
        for object_id in field_spec.object_role_ids:
            assert get_scientific_object_spec(field_spec.primary_profile, object_id) is not None


def test_project_context_domain_is_normalized_to_canonical_discipline() -> None:
    project_context = {
        "domain": "Black Hole Formation and Existence",
        "research_identity": {
            "llm_payload": {
                "primary_discipline": "Astrophysics",
                "secondary_disciplines": ["General Relativity"],
            }
        },
    }

    resolution = normalize_project_context_discipline_resolution(project_context)

    assert resolution["primary_discipline"] == "physics_astronomy"
    assert resolution["source"] == "survey_project_context_domain"


def test_explicit_project_context_field_precedes_profile_and_root_domain() -> None:
    project_context = {
        "domain": "materials science",
        "research_context": {
            "taxonomy_resolution": {
                "provider_filters": {
                    "openalex": {"resolved_field_ids": ["25"]},
                }
            }
        },
    }

    profile = resolve_scientific_intervention_profile(
        {
            "profile_id": "computational_algorithmic",
            "root_domains": ["computer_science"],
        },
        project_context=project_context,
    )

    assert profile is not None
    assert profile.profile_id == "physical_materials_chemical"


def test_ignored_paperseek_fields_do_not_map_to_a_profile() -> None:
    assert len(IGNORED_PAPERSEEK_OPENALEX_FIELDS) == 6
    for field_id in IGNORED_PAPERSEEK_OPENALEX_FIELDS:
        assert resolve_scientific_intervention_profile(
            {"paperseek_openalex_field_ids": [field_id]}
        ) is None


def test_unresolved_profile_never_falls_back_to_computer_science() -> None:
    profile = resolve_scientific_intervention_profile({"status": "unresolved"})

    assert profile is not None
    assert profile.profile_id == "generic_scientific"
    assert profile.profile_id != "computational_algorithmic"


def test_computer_science_keeps_algorithmic_profile() -> None:
    profile = resolve_scientific_intervention_profile(_resolution("computer_science"))

    assert profile is not None
    assert profile.profile_id == "computational_algorithmic"


@pytest.mark.parametrize(
    ("discipline", "profile_id"),
    [
        ("materials_science", "physical_materials_chemical"),
        ("medicine", "clinical_health"),
        ("earth_planetary_science", "earth_environment_agro"),
        ("mathematics", "formal_theoretical"),
        ("engineering", "energy_engineering_systems"),
        ("computer_science", "computational_algorithmic"),
    ],
)
def test_root_components_follow_the_resolved_profile(
    discipline: str,
    profile_id: str,
) -> None:
    state = build_root_state(
        f"fixture for {discipline}",
        {"discipline_resolution": _resolution(discipline)},
        CaptureIdeaState,
    )
    profile = get_scientific_intervention_profile(profile_id)

    assert profile is not None
    assert state.scientific_intervention["profile_id"] == profile_id
    assert state.components == profile.default_component_names()
    assert [entry["component"] for entry in state.scientific_intervention["component_roles"]] == state.components
    if profile_id != "computational_algorithmic":
        assert not set(state.components).intersection(
            {"backbone_model", "objective", "evaluation_harness"}
        )


def test_prepare_root_context_freezes_profile_for_children() -> None:
    pytest.importorskip("faiss")
    from src.agents.idea_agent.agent.mcts import MemoryGuidedMCTS

    mcts = MemoryGuidedMCTS.__new__(MemoryGuidedMCTS)

    prepared = MemoryGuidedMCTS.prepare_root_context(
        mcts,
        "battery degradation",
        {
            "root_domains": ["materials_science"],
            "components": [],
        },
    )

    assert prepared["scientific_intervention_profile"]["profile_id"] == "physical_materials_chemical"
    assert prepared["discipline_resolution"]["primary_discipline"] == "materials_science"


def test_explicit_algorithm_component_is_preserved_for_non_cs_input() -> None:
    state = build_root_state(
        "materials fixture with an explicit machine-learning surrogate model",
        {
            "discipline_resolution": _resolution("materials_science"),
            "components": ["backbone_model"],
        },
        CaptureIdeaState,
    )

    assert state.scientific_intervention["profile_id"] == "physical_materials_chemical"
    assert state.components == ["backbone_model"]


def test_non_cs_legacy_algorithm_component_is_dropped_without_explicit_algorithm_idea() -> None:
    state = build_root_state(
        "materials fixture",
        {
            "discipline_resolution": _resolution("materials_science"),
            "components": ["backbone_model", "candidate_mechanism"],
        },
        CaptureIdeaState,
    )

    assert "backbone_model" not in state.components
    assert "candidate_mechanism" in state.components


def test_non_cs_simulation_word_does_not_count_as_explicit_algorithm_semantics() -> None:
    state = build_root_state(
        "materials simulation fixture",
        {
            "discipline_resolution": _resolution("materials_science"),
            "components": ["backbone_model", "candidate_mechanism"],
            "method": "Use physical simulation to inspect the reaction pathway.",
        },
        CaptureIdeaState,
    )

    assert "backbone_model" not in state.components
    assert "candidate_mechanism" in state.components


def test_invalid_contribution_mode_falls_back_to_profile_default() -> None:
    profile = get_scientific_intervention_profile("clinical_health")
    assert profile is not None
    payload = build_scientific_intervention_payload(
        profile,
        profile.default_component_names(),
        {},
        {"contribution_mode": "not_a_clinical_mode"},
    )

    assert payload["contribution_mode"] == profile.contribution_modes[0].mode_id


def test_legacy_idea_contract_loads_without_intervention_payload() -> None:
    idea = normalize_idea_contract(
        {
            "title": "Legacy title",
            "abstract": "Legacy abstract",
            "core_contribute": "Legacy contribution",
            "methodology": "Legacy method",
            "components": ["legacy_component"],
        },
        allow_legacy=True,
    )

    assert idea["core_contribution"] == "Legacy contribution"
    assert idea["method"] == "Legacy method"
    assert idea["scientific_intervention"] == {}
