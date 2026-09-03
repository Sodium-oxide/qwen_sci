import pytest

from src.agents.idea_agent.utils.mcts.mcts_helpers import (
    _format_root_domains_for_prompt,
    _infer_root_domains_heuristically,
    _normalize_root_domains,
)
from src.agents.idea_agent.utils.workflow.idea_contract import normalize_idea_contract
from src.pipeline.discipline_taxonomy import (
    arxiv_category_expression,
    canonicalize_discipline_key,
    compile_provider_discipline_filter,
    resolve_discipline_taxonomy,
    resolve_subhypothesis_discipline_taxonomy,
)


@pytest.mark.parametrize(
    ("legacy_value", "canonical_key"),
    [
        ("cs.LG", "computer_science"),
        ("cs.CV", "computer_science"),
        ("stat.ML", "statistics"),
        ("Materials Science", "materials_science"),
    ],
)
def test_canonicalize_discipline_key_supports_aliases_and_legacy_values(
    legacy_value: str,
    canonical_key: str,
) -> None:
    assert canonicalize_discipline_key(legacy_value) == canonical_key


@pytest.mark.parametrize(
    ("topic", "expected_primary"),
    [
        ("battery degradation in solid-state electrolytes", "materials_science"),
        ("crop yield response to soil nutrient management", "agricultural_biological_sciences"),
        ("clinical diagnosis of early-stage disease", "medicine"),
        ("water treatment for industrial contamination", "environmental_science"),
        ("quantum mechanics of correlated materials", "physics_astronomy"),
        ("partial differential equations for wave propagation", "mathematics"),
        ("machine learning for scientific image analysis", "computer_science"),
    ],
)
def test_resolver_selects_allowlisted_science_and_engineering_disciplines(
    topic: str,
    expected_primary: str,
) -> None:
    resolution = resolve_discipline_taxonomy(topic)

    assert resolution["status"] in {"resolved", "ambiguous"}
    assert resolution["primary_discipline"] == expected_primary
    assert expected_primary in resolution["discipline_ids"]


def test_humanities_only_topic_is_explicitly_out_of_scope() -> None:
    resolution = resolve_discipline_taxonomy("historical analysis of industrial policy")

    assert resolution["status"] == "out_of_scope"
    assert resolution["discipline_ids"] == []
    assert "historical" in resolution["out_of_scope_terms"]


def test_unknown_topic_remains_unresolved_without_computer_science_fallback() -> None:
    resolution = resolve_discipline_taxonomy("optimization of resource allocation")

    assert resolution["status"] == "unresolved"
    assert resolution["primary_discipline"] is None
    assert resolution["discipline_ids"] == []


def test_parent_only_resolution_withholds_native_hard_filters() -> None:
    resolution = resolve_discipline_taxonomy("electrical engineering")

    assert resolution["primary_discipline"] == "electrical_engineering_systems"
    assert resolution["coverage"] == "parent_only"
    assert resolution["provider_filters"]["openalex"]["applied"] is False
    assert resolution["provider_filters"]["arxiv"]["applied"] is False
    assert resolution["provider_filters"]["openalex"]["mode"] == "native_filter_withheld"


def test_openalex_and_arxiv_metadata_are_explainable() -> None:
    materials_resolution = resolve_discipline_taxonomy("materials science")
    openalex_filter = compile_provider_discipline_filter("openalex", materials_resolution)

    assert openalex_filter["applied"] is True
    assert openalex_filter["filter"] == "primary_topic.field.id:25"
    assert openalex_filter["policy"] == "hard_filter"

    computer_science_resolution = resolve_discipline_taxonomy("machine learning")
    arxiv_filter = compile_provider_discipline_filter("arxiv", computer_science_resolution)

    assert arxiv_filter["applied"] is True
    assert "cat:cs.AI" in arxiv_category_expression(arxiv_filter)
    assert "cat:cs.LG" in arxiv_category_expression(arxiv_filter)


def test_subhypothesis_taxonomy_expands_an_exact_project_filter_with_direct_cross_field_terms() -> None:
    project_resolution = resolve_discipline_taxonomy("energy storage")
    resolution = resolve_subhypothesis_discipline_taxonomy(
        project_resolution,
        {
            "question": (
                "How do electrochemical impedance spectra and electrolyte formulations "
                "affect lithium-ion cell capacity retention?"
            ),
            "scientific_scope": {
                "research_object": ["lithium-ion cells"],
                "intervention_or_input": ["sulfur host and cathode architecture"],
            },
            "slot_definitions": {
                "discriminating_observation": {
                    "retrieval_concepts": [
                        "operando spectroscopy",
                        "electrochemical impedance spectroscopy",
                        "electrolyte formulation",
                    ]
                }
            },
        },
    )
    openalex_filter = resolution["provider_filters"]["openalex"]

    assert project_resolution["provider_filters"]["openalex"]["filter"] == "primary_topic.field.id:21"
    assert openalex_filter["filter"] == "primary_topic.field.id:21|16|25"
    assert openalex_filter["resolved_discipline_ids"] == [
        "energy",
        "chemistry",
        "materials_science",
    ]
    assert openalex_filter["source"] == "project_domain_plus_subhypothesis"
    assert resolution["subhypothesis_taxonomy"]["expanded"] is True


def test_subhypothesis_taxonomy_does_not_create_a_hard_filter_from_parent_only_project_domain() -> None:
    project_resolution = resolve_discipline_taxonomy("electrical engineering")
    resolution = resolve_subhypothesis_discipline_taxonomy(
        project_resolution,
        {"question": "How does electrolyte composition change electrochemical cell performance?"},
    )

    assert resolution["provider_filters"]["openalex"] == project_resolution["provider_filters"]["openalex"]
    assert resolution["subhypothesis_taxonomy"]["expanded"] is False


def test_root_domain_helpers_migrate_legacy_values_and_keep_empty_unset() -> None:
    assert _normalize_root_domains(["cs.LG", "cs.CV", "stat.ML"]) == [
        "computer_science",
        "statistics",
    ]
    assert _normalize_root_domains([]) == []
    assert _format_root_domains_for_prompt([]) == "Unspecified"


def test_idea_contract_canonicalizes_root_domains_without_losing_metadata() -> None:
    resolution = resolve_discipline_taxonomy("machine learning")
    idea = normalize_idea_contract(
        {
            "title": "Test idea",
            "abstract": "Test abstract",
            "core_contribution": "Test contribution",
            "method": "Test method",
            "root_domains": ["cs.LG", "history", "stat.ML", "cs.CV"],
            "discipline_resolution": resolution,
        }
    )

    assert idea["root_domains"] == ["computer_science", "statistics"]
    assert idea["discipline_resolution"] == resolution


def test_root_domain_fallback_helper_never_defaults_to_computer_science() -> None:
    assert _infer_root_domains_heuristically(
        "historical analysis of industrial policy",
        "",
    ) == []
    assert _infer_root_domains_heuristically(
        "optimization of resource allocation",
        "",
    ) == []
