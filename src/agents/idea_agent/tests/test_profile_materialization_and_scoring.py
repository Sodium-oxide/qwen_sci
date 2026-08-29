from __future__ import annotations

import sys
import types

if "faiss" not in sys.modules:
    sys.modules["faiss"] = types.ModuleType("faiss")

from src.agents.idea_agent.agent.mcts import IdeaEvaluation
from src.agents.idea_agent.agent.prompts.mcts_generation import MCTS_IDEA_GENERATION_PROMPT
from src.agents.idea_agent.agent.prompts.skill_instantiation import SKILL_INSTANTIATION_PROMPT
from src.agents.idea_agent.utils.mcts.component_novelty import (
    ComponentNoveltyScorer,
    PROFILE_NOVELTY_AXES,
)
from src.agents.idea_agent.utils.mcts.scientific_intervention_ontology import (
    get_scientific_intervention_profile,
)
from src.agents.idea_agent.utils.workflow.ligagent_helpers import (
    build_replanned_idea_entry,
    build_profile_aware_materialization,
)


def _idea(profile_id: str) -> dict[str, object]:
    profile = get_scientific_intervention_profile(profile_id)
    assert profile is not None
    return {
        "title": "Causal intervention",
        "abstract": "A profile-native research idea.",
        "core_contribution": "The intervention changes a mediator and outcome relation.",
        "method": "Measure the mediator before the endpoint; compare against control.",
        "risks": "Confounding and boundary failure.",
        "components": profile.default_component_names(),
        "scientific_intervention": profile.to_payload(),
    }


def test_generation_and_instantiation_prompts_require_scientific_contract() -> None:
    assert "central_hypothesis" in MCTS_IDEA_GENERATION_PROMPT
    assert "discriminating_observation" in MCTS_IDEA_GENERATION_PROMPT
    assert "evidence_requirement" in SKILL_INSTANTIATION_PROMPT
    assert "scientific_object" in SKILL_INSTANTIATION_PROMPT


def test_non_cs_materialization_uses_native_spec_and_no_legacy_algorithm() -> None:
    result = build_profile_aware_materialization(
        _idea("clinical_health"),
        "clinical intervention",
        prompts={},
        chat_fn=lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("mock failure")),
        model="mock",
        logger=type("Logger", (), {"warning": lambda self, *args: None})(),
    )
    assert result["profile_id"] == "clinical_health"
    assert result["spec_type"] == "intervention_measurement_spec"
    assert result["legacy_algorithm"] == []
    assert result["scientific_spec"]["boundary_condition"]


def test_replan_preserves_profile_and_discipline_context() -> None:
    source = _idea("clinical_health")
    source.update(
        {
            "root_domains": ["medicine"],
            "discipline_resolution": {
                "primary_discipline": "medicine",
                "discipline_ids": ["medicine"],
            },
        }
    )
    replanned = build_replanned_idea_entry(
        latest_candidate=source,
        root_idea=source,
        mature_idea="A revised causal intervention.",
        component_decisions=[],
    )
    assert replanned["root_domains"] == ["medicine"]
    assert replanned["discipline_resolution"]["primary_discipline"] == "medicine"
    assert replanned["scientific_intervention"]["profile_id"] == "clinical_health"


def test_materialization_normalizes_values_to_profile_schema() -> None:
    def mock_chat(*args, **kwargs):
        return (
            '{"scientific_spec": {'
            '"object_type": "neural_network", '
            '"evidence_obligation": "benchmark_score", '
            '"boundary_condition": "training_loss", '
            '"measurement_or_observation": "accuracy"'
            '}}'
        )

    result = build_profile_aware_materialization(
        _idea("clinical_health"),
        "clinical intervention",
        prompts={},
        chat_fn=mock_chat,
        model="mock",
        logger=type("Logger", (), {"warning": lambda self, *args: None})(),
    )
    schema = result["scientific_spec"]
    assert schema["object_type"] == "target_population_or_cohort"
    assert schema["evidence_obligation"] == "comparator_or_counterfactual"
    assert schema["boundary_condition"] == "safety_or_external_validity_boundary"
    assert schema["measurement_or_observation"] == "clinical_endpoint"


def test_cs_materialization_preserves_legacy_algorithm_contract() -> None:
    def mock_chat(*args, **kwargs):
        return '{"algorithms": [{"name": "Method", "input": ["x"], "output": ["y"], "pipeline": ["Step 1: use backbone_model"]}]}'

    result = build_profile_aware_materialization(
        _idea("computational_algorithmic"),
        "algorithmic topic",
        prompts={},
        chat_fn=mock_chat,
        model="mock",
        logger=type("Logger", (), {"warning": lambda self, *args: None})(),
    )
    assert result["profile_id"] == "computational_algorithmic"
    assert result["legacy_algorithm"]
    assert result["scientific_spec"]["spec_type"] == "algorithm_spec"


def test_novelty_queries_include_claim_and_mechanism_context() -> None:
    scorer = ComponentNoveltyScorer(vector_store=object())
    queries = scorer._prepare_component_queries(
        [{"component": "mediator", "explanation": "biological mediator"}],
        {"core_contribution": "central causal hypothesis", "method": "measure endpoint"},
    )
    labels = {item["component"] for item in queries}
    assert {"mediator", "central_hypothesis", "mechanism_or_relation"} <= labels
    assert "causal_intervention_or_mediation" in PROFILE_NOVELTY_AXES["clinical_health"]


def test_novelty_axes_are_restricted_to_current_profile() -> None:
    scorer = ComponentNoveltyScorer(
        vector_store=object(),
        chat_fn=lambda *args, **kwargs: (
            '{"rubric_score": 4, "novelty_axes": {'
            '"causal_intervention_or_mediation": 4, '
            '"unrelated_algorithm_axis": 5}}'
        ),
    )
    scorer._evaluate_with_llm(
        topic="clinical topic",
        idea_payload={
            "scientific_intervention": {"profile_id": "clinical_health"},
        },
        components_with_explanations=[],
        evidence_nodes=[],
    )
    assert scorer.last_novelty_axes == {"causal_intervention_or_mediation": 4.0}


def test_main_evaluation_axes_are_restricted_to_current_profile() -> None:
    payload = {
        "novelty": 4,
        "novelty_axes": {
            "causal_intervention_or_mediation": 4,
            "unrelated_algorithm_axis": 5,
        },
    }
    evaluation = IdeaEvaluation.from_payload(payload, profile_id="clinical_health")
    assert evaluation.novelty_axes == {
        "causal_intervention_or_mediation": 4.0,
        "scientific_novelty": 4.0,
    }


def test_profile_composite_uses_scientific_novelty_axes() -> None:
    common = {
        "novelty": 5,
        "novelty_axes": {
            "scientific_novelty": 2,
            "relation_or_claim": 5,
            "boundary_or_regime": 5,
        },
        "surprise": 3,
        "feasibility": 4,
        "clarity": 4,
        "impact": 4,
        "risk": 1,
        "conciseness": 3,
        "alignment_score": 4,
        "complexity_penalty": 1,
        "protocol_score": 4,
        "explanatory_power": 5,
        "identifiability": 5,
        "boundary_calibration": 5,
        "claim_overreach_penalty": 0,
    }
    clinical_payload = {
        **common,
        "novelty_axes": {
            "causal_intervention_or_mediation": 2,
            "population_or_endpoint_relation": 5,
            "comparator_or_measurement_design": 5,
            "safety_or_external_validity_boundary": 5,
        },
    }
    cs_payload = {
        **common,
        "novelty_axes": {
            "algorithmic_mechanism": 2,
            "representation_or_inference": 5,
            "training_or_execution_strategy": 5,
            "protocol_or_resource_boundary": 5,
        },
    }
    clinical = IdeaEvaluation.from_payload(
        clinical_payload,
        profile_id="clinical_health",
    )
    cs = IdeaEvaluation.from_payload(
        cs_payload,
        profile_id="computational_algorithmic",
    )
    assert clinical.composite != cs.composite
    assert clinical.novelty_axes["population_or_endpoint_relation"] == 5
