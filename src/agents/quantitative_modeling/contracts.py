"""Stable contracts for quantitative ideas and their provenance.

The quantitative branch intentionally has its own schema. It never extends
``idea_result_v5`` because that artifact remains the canonical handoff for the
existing ExperimentDesign workflow.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any


QUANTITATIVE_IDEAS_SCHEMA_VERSION = "quantitative_ideas_v1"
QUANTITATIVE_IDEA_MANIFEST_SCHEMA_VERSION = "quantitative_ideas_manifest_v1"
MAX_QUANTITATIVE_IDEAS = 2
SUPPORTED_QUANTITATIVE_DOMAINS = frozenset(
    {
        "MATH_PHYS_ASTRONOMY",
        "ENGINEERING_ENERGY",
        "EARTH_ENVIRONMENT",
        "MATERIALS_CHEMISTRY",
    }
)
QUANTITATIVE_IDEA_GENERATION_STATUSES = frozenset(
    {
        "READY",
        "NO_ELIGIBLE_IDEAS",
        "FAILED_OPTIONAL",
    }
)
QUANTITATIVE_IDEA_READINESS = frozenset({"EXECUTABLE_CANDIDATE", "INSUFFICIENT"})
MODEL_SELECTION_MODES = frozenset(
    {"CATALOG_MATCH", "CATALOG_COMPOSITION", "OUTSIDE_CATALOG"}
)
_QUANTITATIVE_ID_PATTERN = re.compile(r"Q[1-2]")


class QuantitativeContractError(ValueError):
    """Raised when a quantitative sidecar cannot be trusted."""


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _text(value: object) -> str:
    return str(value or "").strip()


def _text_list(value: object, *, field: str, allow_empty: bool = False) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise QuantitativeContractError(f"{field} must be a list of text values")
    normalized = [_text(item) for item in value]
    normalized = [item for item in normalized if item]
    if not normalized and not allow_empty:
        raise QuantitativeContractError(f"{field} must not be empty")
    return list(dict.fromkeys(normalized))


def _required_text(payload: Mapping[str, object], field: str) -> str:
    value = _text(payload.get(field))
    if not value:
        raise QuantitativeContractError(f"{field} is required")
    return value


def _normalize_candidate_model_strategy(value: object) -> dict[str, Any]:
    payload = _mapping(value)
    mode = _required_text(payload, "mode")
    if mode not in MODEL_SELECTION_MODES:
        raise QuantitativeContractError("candidate_model_strategy.mode is unsupported")
    catalog_model_ids = _text_list(
        payload.get("catalog_model_ids", []),
        field="candidate_model_strategy.catalog_model_ids",
        allow_empty=True,
    )
    if mode == "CATALOG_MATCH" and not catalog_model_ids:
        raise QuantitativeContractError(
            "candidate_model_strategy.catalog_model_ids is required for CATALOG_MATCH"
        )
    return {
        "mode": mode,
        "catalog_model_ids": catalog_model_ids,
        "rationale": _required_text(payload, "rationale"),
    }


def normalize_quantitative_idea(value: object, *, index: int) -> dict[str, Any]:
    """Validate one executable-candidate description without generating equations."""

    payload = _mapping(value)
    if not payload:
        raise QuantitativeContractError(f"ideas[{index}] must be an object")
    quantitative_idea_id = _required_text(payload, "quantitative_idea_id")
    if not _QUANTITATIVE_ID_PATTERN.fullmatch(quantitative_idea_id):
        raise QuantitativeContractError("quantitative_idea_id must be Q1 or Q2")
    domain = _required_text(payload, "domain")
    if domain not in SUPPORTED_QUANTITATIVE_DOMAINS:
        raise QuantitativeContractError("domain is outside the phase-one quantitative domains")
    readiness = _required_text(payload, "execution_readiness")
    if readiness not in QUANTITATIVE_IDEA_READINESS:
        raise QuantitativeContractError("execution_readiness is unsupported")
    return {
        "quantitative_idea_id": quantitative_idea_id,
        "title": _required_text(payload, "title"),
        "domain": domain,
        "base_hypothesis_reference": _required_text(payload, "base_hypothesis_reference"),
        "quantitative_question": _required_text(payload, "quantitative_question"),
        "model_intent": _required_text(payload, "model_intent"),
        "candidate_model_strategy": _normalize_candidate_model_strategy(
            payload.get("candidate_model_strategy")
        ),
        "state_variables": _text_list(payload.get("state_variables"), field="state_variables"),
        "parameters_and_sources": _text_list(
            payload.get("parameters_and_sources"), field="parameters_and_sources"
        ),
        "initial_boundary_requirements": _text_list(
            payload.get("initial_boundary_requirements"),
            field="initial_boundary_requirements",
        ),
        "scenarios": _text_list(payload.get("scenarios"), field="scenarios"),
        "observables": _text_list(payload.get("observables"), field="observables"),
        "comparator": _required_text(payload, "comparator"),
        "falsification_condition": _required_text(payload, "falsification_condition"),
        "provisional_solver_family": _required_text(payload, "provisional_solver_family"),
        "execution_readiness": readiness,
        "known_limitations": _text_list(
            payload.get("known_limitations"), field="known_limitations"
        ),
    }


def normalize_quantitative_ideas(value: object) -> list[dict[str, Any]]:
    """Validate the bounded Q1/Q2 payload returned by the Idea-side LLM call."""

    payload = _mapping(value)
    raw_ideas = payload.get("ideas", [])
    if not isinstance(raw_ideas, Sequence) or isinstance(raw_ideas, (str, bytes, bytearray)):
        raise QuantitativeContractError("ideas must be a list")
    if len(raw_ideas) > MAX_QUANTITATIVE_IDEAS:
        raise QuantitativeContractError("ideas must contain at most two entries")
    ideas = [normalize_quantitative_idea(item, index=index) for index, item in enumerate(raw_ideas)]
    identifiers = [item["quantitative_idea_id"] for item in ideas]
    if len(identifiers) != len(set(identifiers)):
        raise QuantitativeContractError("quantitative_idea_id values must be unique")
    return ideas


def build_quantitative_idea_set(
    *,
    topic: object,
    source_identity: Mapping[str, object],
    generation_status: object,
    ideas: object,
    generation_message: object = "",
    catalog: Mapping[str, object] | None = None,
) -> dict[str, Any]:
    """Build the persisted Q sidecar from a validated model response."""

    status = _text(generation_status)
    if status not in QUANTITATIVE_IDEA_GENERATION_STATUSES:
        raise QuantitativeContractError("generation_status is unsupported")
    normalized_identity = {
        key: _text(value)
        for key, value in dict(source_identity).items()
        if _text(value)
    }
    for field in (
        "survey_run_id",
        "project_id",
        "project_context_fingerprint",
        "selected_direction_id",
        "idea_result_path",
    ):
        if not normalized_identity.get(field):
            raise QuantitativeContractError(f"source_identity.{field} is required")
    normalized_ideas = normalize_quantitative_ideas({"ideas": ideas})
    if status == "READY" and not normalized_ideas:
        raise QuantitativeContractError("READY quantitative idea set must contain at least one idea")
    if status == "READY" and any(
        idea["execution_readiness"] != "EXECUTABLE_CANDIDATE" for idea in normalized_ideas
    ):
        raise QuantitativeContractError(
            "READY quantitative idea set may contain only executable candidates"
        )
    if status != "READY" and normalized_ideas:
        raise QuantitativeContractError("non-ready quantitative idea set must not contain ideas")
    result: dict[str, Any] = {
        "schema_version": QUANTITATIVE_IDEAS_SCHEMA_VERSION,
        "topic": _required_text({"topic": topic}, "topic"),
        "source_identity": normalized_identity,
        "generation_status": status,
        "generation_message": _text(generation_message),
        "ideas": normalized_ideas,
    }
    if catalog:
        result["catalog"] = {
            key: _text(value) for key, value in dict(catalog).items() if _text(value)
        }
    return result


def validate_quantitative_idea_set(
    value: object,
    *,
    expected_identity: Mapping[str, object] | None = None,
    expected_topic: object = "",
) -> dict[str, Any]:
    """Validate an on-disk Q sidecar and return a normalized representation."""

    payload = _mapping(value)
    if _text(payload.get("schema_version")) != QUANTITATIVE_IDEAS_SCHEMA_VERSION:
        raise QuantitativeContractError("unsupported quantitative idea schema")
    if expected_topic and _text(payload.get("topic")).casefold() != _text(expected_topic).casefold():
        raise QuantitativeContractError("quantitative idea topic differs from its expected topic")
    normalized = build_quantitative_idea_set(
        topic=payload.get("topic"),
        source_identity=_mapping(payload.get("source_identity")),
        generation_status=payload.get("generation_status"),
        generation_message=payload.get("generation_message"),
        ideas=payload.get("ideas"),
        catalog=_mapping(payload.get("catalog")) or None,
    )
    if expected_identity:
        for field in (
            "survey_run_id",
            "project_id",
            "project_context_fingerprint",
            "selected_direction_id",
        ):
            expected = _text(expected_identity.get(field))
            actual = _text(normalized["source_identity"].get(field))
            if expected and actual != expected:
                raise QuantitativeContractError(f"source_identity differs for {field}")
    return normalized


__all__ = [
    "MAX_QUANTITATIVE_IDEAS",
    "MODEL_SELECTION_MODES",
    "QUANTITATIVE_IDEA_GENERATION_STATUSES",
    "QUANTITATIVE_IDEA_MANIFEST_SCHEMA_VERSION",
    "QUANTITATIVE_IDEAS_SCHEMA_VERSION",
    "QUANTITATIVE_IDEA_READINESS",
    "SUPPORTED_QUANTITATIVE_DOMAINS",
    "QuantitativeContractError",
    "build_quantitative_idea_set",
    "normalize_quantitative_idea",
    "normalize_quantitative_ideas",
    "validate_quantitative_idea_set",
]
