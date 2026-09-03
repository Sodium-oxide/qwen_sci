"""LLM-backed, schema-bounded generation of optional Q1/Q2 sidecar ideas."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from typing import Any

from src.agents.experiment_design_agent.llm_json import RequiredJsonLLMError, call_required_json
from src.agents.quantitative_modeling.catalog import load_model_catalog_context
from src.agents.quantitative_modeling.contracts import (
    QuantitativeContractError,
    build_quantitative_idea_set,
    normalize_quantitative_ideas,
)


class QuantitativeIdeaGenerationError(RuntimeError):
    """Raised when Q1/Q2 cannot be generated as one complete JSON object."""


def _bounded_json(value: object, *, max_characters: int) -> str:
    serialized = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return serialized[:max_characters]


def build_quantitative_idea_prompt(
    *,
    topic: str,
    idea_result: Mapping[str, object],
    catalog_context: str,
) -> str:
    """Create a constrained prompt that does not request equations or executable code."""

    return "\n".join(
        (
            "You are the quantitative-idea sidecar of a scientific Idea agent.",
            "Return exactly one JSON object; do not use Markdown, prose outside JSON, equations, code, or commands.",
            "Generate zero, one, or two independent quantitative ideas named Q1 and Q2.",
            "Only propose an idea if a mathematical model or numerical simulation can be specified with",
            "state variables, parameter sources, initial or boundary conditions, scenarios, observables,",
            "a comparator, and a falsification condition. Never invent missing evidence merely to fill Q1/Q2.",
            "The only allowed domains are MATH_PHYS_ASTRONOMY, ENGINEERING_ENERGY,",
            "EARTH_ENVIRONMENT, and MATERIALS_CHEMISTRY.",
            "The model catalog is advisory, not a whitelist. candidate_model_strategy.mode must be",
            "CATALOG_MATCH, CATALOG_COMPOSITION, or OUTSIDE_CATALOG.",
            "Each idea must contain: quantitative_idea_id, title, domain, base_hypothesis_reference,",
            "quantitative_question, model_intent, candidate_model_strategy {mode, catalog_model_ids, rationale},",
            "state_variables, parameters_and_sources, initial_boundary_requirements, scenarios, observables,",
            "comparator, falsification_condition, provisional_solver_family, execution_readiness, known_limitations.",
            "Set execution_readiness to EXECUTABLE_CANDIDATE only when the required information is explicit;",
            "otherwise return no idea. Return {\"ideas\": []} when none qualify.",
            f"Research topic: {topic}",
            "Canonical Idea result (read-only; do not modify it):",
            _bounded_json(idea_result, max_characters=24_000),
            "Approved advisory model catalog excerpt:",
            catalog_context or "No catalog file is available; OUTSIDE_CATALOG remains permitted.",
        )
    )


def build_quantitative_idea_repair_prompt(
    *,
    original_response: object,
    validation_error: str,
) -> str:
    """Create one structural-only repair request for a rejected Q payload."""

    return "\n".join(
        (
            "Repair the JSON object below so it satisfies the quantitative-idea contract.",
            "Return exactly one JSON object and no Markdown, prose, equations, code, commands, or new scientific claims.",
            "Preserve every scientific statement and value; change structure only.",
            "The fields state_variables, parameters_and_sources, initial_boundary_requirements, scenarios,",
            "observables, and known_limitations must each be non-empty arrays of text values.",
            "If one of those fields is a single string, wrap it in a one-element array.",
            "Do not add sources, equations, parameter values, solver code, or ideas.",
            f"Validator error: {validation_error}",
            "Rejected JSON object:",
            _bounded_json(original_response, max_characters=40_000),
        )
    )


def build_quantitative_json_llm_call(*, config: Any, model: str | None = None) -> Callable[..., object]:
    """Reuse the repository's configured JSON-only transport without a new provider path."""

    from src.agents.research_plan_author.llm_json import build_author_json_llm_call

    return build_author_json_llm_call(config=config, model=model, temperature=0.2)


def generate_quantitative_idea_set(
    *,
    topic: str,
    idea_result: Mapping[str, object],
    source_identity: Mapping[str, object],
    llm_call: Callable[..., object],
) -> dict[str, Any]:
    """Generate and validate Q1/Q2, wrapping only verified LLM JSON in a sidecar."""

    catalog, catalog_context = load_model_catalog_context()
    prompt = build_quantitative_idea_prompt(
        topic=topic,
        idea_result=idea_result,
        catalog_context=catalog_context,
    )
    try:
        response = call_required_json(llm_call, prompt, stage="quantitative_idea_generation")
    except RequiredJsonLLMError as exc:
        raise QuantitativeIdeaGenerationError(str(exc)) from exc
    try:
        ideas = normalize_quantitative_ideas(response)
    except QuantitativeContractError as exc:
        repair_prompt = build_quantitative_idea_repair_prompt(
            original_response=response,
            validation_error=str(exc),
        )
        try:
            repaired_response = call_required_json(
                llm_call,
                repair_prompt,
                stage="quantitative_idea_generation_repair",
            )
            ideas = normalize_quantitative_ideas(repaired_response)
        except (RequiredJsonLLMError, QuantitativeContractError) as repair_exc:
            raise QuantitativeIdeaGenerationError(str(repair_exc)) from repair_exc
    if not ideas:
        return build_quantitative_idea_set(
            topic=topic,
            source_identity=source_identity,
            generation_status="NO_ELIGIBLE_IDEAS",
            generation_message="No quantitative idea met the explicit executability requirements.",
            ideas=[],
            catalog=catalog,
        )
    return build_quantitative_idea_set(
        topic=topic,
        source_identity=source_identity,
        generation_status="READY",
        generation_message="",
        ideas=ideas,
        catalog=catalog,
    )


def build_failed_optional_quantitative_idea_set(
    *,
    topic: str,
    source_identity: Mapping[str, object],
    message: str,
) -> dict[str, Any]:
    """Publish a non-success sidecar without exposing provider response contents."""

    return build_quantitative_idea_set(
        topic=topic,
        source_identity=source_identity,
        generation_status="FAILED_OPTIONAL",
        generation_message=str(message or "Quantitative idea generation failed.")[:500],
        ideas=[],
    )


__all__ = [
    "QuantitativeIdeaGenerationError",
    "build_failed_optional_quantitative_idea_set",
    "build_quantitative_idea_prompt",
    "build_quantitative_idea_repair_prompt",
    "build_quantitative_json_llm_call",
    "generate_quantitative_idea_set",
]
