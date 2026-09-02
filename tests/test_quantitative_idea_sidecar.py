from __future__ import annotations

import pytest

from src.agents.quantitative_modeling.contracts import (
    QuantitativeContractError,
    build_quantitative_idea_set,
    validate_quantitative_idea_set,
)
from src.agents.quantitative_modeling.idea_generation import generate_quantitative_idea_set


def _identity() -> dict[str, str]:
    return {
        "survey_run_id": "survey-1",
        "project_id": "project-1",
        "project_context_fingerprint": "context-1",
        "selected_direction_id": "mechanistic_direction",
        "idea_result_path": "C:/science/idea_result.json",
    }


def _idea(identifier: str = "Q1") -> dict[str, object]:
    return {
        "quantitative_idea_id": identifier,
        "title": "Reaction diffusion constraint",
        "domain": "EARTH_ENVIRONMENT",
        "base_hypothesis_reference": "directions[0].hypothesis",
        "quantitative_question": "Does transport constrain the observed gradient?",
        "model_intent": "Compare diffusion-reaction scenarios.",
        "candidate_model_strategy": {
            "mode": "OUTSIDE_CATALOG",
            "catalog_model_ids": [],
            "rationale": "The coupled boundary condition is problem-specific.",
        },
        "state_variables": ["concentration"],
        "parameters_and_sources": ["diffusivity from literature range"],
        "initial_boundary_requirements": ["initial profile and boundary flux"],
        "scenarios": ["reference flux", "reduced flux"],
        "observables": ["steady concentration gradient"],
        "comparator": "gradient under the reference flux",
        "falsification_condition": "No parameter range reproduces the direction of change.",
        "provisional_solver_family": "finite_difference_1d",
        "execution_readiness": "EXECUTABLE_CANDIDATE",
        "known_limitations": ["one-dimensional approximation"],
    }


def test_quantitative_idea_set_keeps_main_idea_identity_external() -> None:
    payload = build_quantitative_idea_set(
        topic="transport constraint",
        source_identity=_identity(),
        generation_status="READY",
        ideas=[_idea()],
    )

    validated = validate_quantitative_idea_set(
        payload,
        expected_identity=_identity(),
        expected_topic="transport constraint",
    )

    assert validated["schema_version"] == "quantitative_ideas_v1"
    assert validated["ideas"][0]["quantitative_idea_id"] == "Q1"
    assert "idea_result_v5" not in validated


def test_quantitative_idea_set_rejects_more_than_two_ideas() -> None:
    with pytest.raises(QuantitativeContractError, match="at most two"):
        build_quantitative_idea_set(
            topic="transport constraint",
            source_identity=_identity(),
            generation_status="READY",
            ideas=[_idea("Q1"), _idea("Q2"), _idea("Q1")],
        )


def test_quantitative_idea_set_rejects_nonready_ideas() -> None:
    with pytest.raises(QuantitativeContractError, match="non-ready"):
        build_quantitative_idea_set(
            topic="transport constraint",
            source_identity=_identity(),
            generation_status="NO_ELIGIBLE_IDEAS",
            ideas=[_idea()],
        )


def test_quantitative_idea_set_rejects_non_executable_ready_candidates() -> None:
    insufficient = {**_idea(), "execution_readiness": "INSUFFICIENT"}

    with pytest.raises(QuantitativeContractError, match="only executable candidates"):
        build_quantitative_idea_set(
            topic="transport constraint",
            source_identity=_identity(),
            generation_status="READY",
            ideas=[insufficient],
        )


def test_generator_requires_explicit_operational_fields() -> None:
    generated = generate_quantitative_idea_set(
        topic="transport constraint",
        idea_result={"schema_version": "idea_result_v5", "primary_direction": "mechanistic_direction"},
        source_identity=_identity(),
        llm_call=lambda _prompt, **_kwargs: {"ideas": [_idea()]},
    )

    assert generated["generation_status"] == "READY"
    assert generated["ideas"][0]["candidate_model_strategy"]["mode"] == "OUTSIDE_CATALOG"


def test_generator_repairs_scalar_operational_field_once() -> None:
    malformed = {"ideas": [{**_idea(), "initial_boundary_requirements": "initial profile"}]}
    repaired = {"ideas": [_idea()]}
    responses = iter([malformed, repaired])

    generated = generate_quantitative_idea_set(
        topic="transport constraint",
        idea_result={"schema_version": "idea_result_v5", "primary_direction": "mechanistic_direction"},
        source_identity=_identity(),
        llm_call=lambda _prompt, **_kwargs: next(responses),
    )

    assert generated["generation_status"] == "READY"
    assert generated["ideas"][0]["initial_boundary_requirements"] == ["initial profile and boundary flux"]


def test_generator_records_empty_set_when_no_idea_is_eligible() -> None:
    generated = generate_quantitative_idea_set(
        topic="transport constraint",
        idea_result={"schema_version": "idea_result_v5", "primary_direction": "mechanistic_direction"},
        source_identity=_identity(),
        llm_call=lambda _prompt, **_kwargs: {"ideas": []},
    )

    assert generated["generation_status"] == "NO_ELIGIBLE_IDEAS"
    assert generated["ideas"] == []
