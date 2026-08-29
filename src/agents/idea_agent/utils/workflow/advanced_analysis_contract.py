"""Strict contract validation for advanced-analysis LLM responses."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any, List


_TOP_LEVEL_FIELDS = frozenset(
    {
        "key_methods",
        "field_consensus",
        "existing_problems",
        "evaluation_gaps",
        "future_directions",
        "preserve_current_idea",
        "mature_ideas",
        "grounded_mature_idea",
        "grounded_refinement_scope",
        "root_idea",
        "divergent_idea_seeds",
        "cross_domain_inspiration",
        "tldr",
    }
)
_NONEMPTY_STRING_LIST_FIELDS = (
    "key_methods",
    "field_consensus",
    "existing_problems",
    "future_directions",
)
_MATURE_IDEA_STRING_FIELDS = (
    "idea_id",
    "title",
    "hypothesis",
    "scientific_object",
    "mechanism",
    "refinement_scope",
    "falsifier",
    "anchor_policy",
    "maturity_status",
    "idea_source",
    "lineage",
    "independence_rationale",
)
_MATURE_IDEA_LIST_FIELDS = (
    "assumptions",
    "evidence_basis",
    "target_gap_ids",
    "counterexamples",
    "retrieval_queries",
    "mechanism_chain",
    "validation_targets",
)
_ROOT_IDEA_STRING_FIELDS = (
    "title",
    "abstract",
    "core_contribution",
    "method",
    "risks",
    "rationale",
)
_IDEA_SOURCES = {
    "user_input",
    "survey_gap",
    "prior_candidate",
    "experiment_feedback",
    "problem_reframing",
    "adversarial_generation",
    "cross_domain_transfer",
}


def _is_nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _validate_nonempty_string_list(value: Any, field_name: str, errors: List[str]) -> None:
    if not isinstance(value, list) or not value or not all(_is_nonempty_string(item) for item in value):
        errors.append(f"{field_name} must be a non-empty list of non-empty strings")


def _validate_mapping(value: Any, field_name: str, errors: List[str]) -> Mapping[str, Any] | None:
    if not isinstance(value, Mapping):
        errors.append(f"{field_name} must be an object")
        return None
    return value


def _validate_evaluation_gaps(value: Any, errors: List[str]) -> None:
    if not isinstance(value, list) or not value:
        errors.append("evaluation_gaps must be a non-empty list")
        return
    for index, gap in enumerate(value):
        item = _validate_mapping(gap, f"evaluation_gaps[{index}]", errors)
        if item is None:
            continue
        for field_name in ("gap", "why_it_matters", "validation_expectation"):
            if not _is_nonempty_string(item.get(field_name)):
                errors.append(f"evaluation_gaps[{index}].{field_name} must be a non-empty string")


def _validate_mature_ideas(value: Any, *, require_gap_ids: bool, errors: List[str]) -> None:
    if not isinstance(value, list) or not value:
        errors.append("mature_ideas must be a non-empty list")
        return
    for index, raw_idea in enumerate(value):
        idea = _validate_mapping(raw_idea, f"mature_ideas[{index}]", errors)
        if idea is None:
            continue
        for field_name in _MATURE_IDEA_STRING_FIELDS:
            if not _is_nonempty_string(idea.get(field_name)):
                errors.append(f"mature_ideas[{index}].{field_name} must be a non-empty string")
        for field_name in _MATURE_IDEA_LIST_FIELDS:
            value = idea.get(field_name)
            if not isinstance(value, list) or not all(_is_nonempty_string(item) for item in value):
                errors.append(f"mature_ideas[{index}].{field_name} must be a list of non-empty strings")
            elif field_name != "target_gap_ids" and not value:
                errors.append(f"mature_ideas[{index}].{field_name} must not be empty")
            elif field_name == "target_gap_ids" and require_gap_ids and not value:
                errors.append(f"mature_ideas[{index}].target_gap_ids must not be empty when Survey handoff is present")
        if idea.get("maturity_status") not in {"mature", "provisional"}:
            errors.append(f"mature_ideas[{index}].maturity_status must be mature or provisional")
        if idea.get("idea_source") not in _IDEA_SOURCES:
            errors.append(f"mature_ideas[{index}].idea_source is not an allowed source")


def _validate_root_idea(value: Any, errors: List[str]) -> None:
    root_idea = _validate_mapping(value, "root_idea", errors)
    if root_idea is None:
        return
    for field_name in _ROOT_IDEA_STRING_FIELDS:
        if not _is_nonempty_string(root_idea.get(field_name)):
            errors.append(f"root_idea.{field_name} must be a non-empty string")
    for field_name in ("target_defects", "supporting_papers"):
        _validate_nonempty_string_list(root_idea.get(field_name), f"root_idea.{field_name}", errors)


def _validate_optional_seed_records(
    value: Any,
    field_name: str,
    required_fields: Sequence[str],
    errors: List[str],
    *,
    allow_empty_fields: Sequence[str] = (),
) -> None:
    if not isinstance(value, list):
        errors.append(f"{field_name} must be a list")
        return
    for index, raw_record in enumerate(value):
        record = _validate_mapping(raw_record, f"{field_name}[{index}]", errors)
        if record is None:
            continue
        for item_field in required_fields:
            item_value = record.get(item_field)
            if item_field in allow_empty_fields and isinstance(item_value, str):
                continue
            if not _is_nonempty_string(item_value):
                errors.append(f"{field_name}[{index}].{item_field} must be a non-empty string")


def validate_advanced_analysis_response(
    response: Any,
    *,
    require_grounded_fields: bool,
    require_gap_ids: bool,
) -> List[str]:
    """Return contract violations; an empty list means the response is usable."""

    if not isinstance(response, Mapping):
        return ["advanced analysis response must be a JSON object"]

    errors: List[str] = []
    present_fields = set(response)
    for field_name in sorted(_TOP_LEVEL_FIELDS - present_fields):
        errors.append(f"missing required top-level field: {field_name}")
    for field_name in sorted(present_fields - _TOP_LEVEL_FIELDS):
        errors.append(f"unexpected top-level field: {field_name}")

    for field_name in _NONEMPTY_STRING_LIST_FIELDS:
        _validate_nonempty_string_list(response.get(field_name), field_name, errors)
    _validate_evaluation_gaps(response.get("evaluation_gaps"), errors)

    preserve = _validate_mapping(response.get("preserve_current_idea"), "preserve_current_idea", errors)
    if preserve is not None:
        if not isinstance(preserve.get("keep_original"), bool):
            errors.append("preserve_current_idea.keep_original must be a boolean")
        if not isinstance(preserve.get("reason"), str):
            errors.append("preserve_current_idea.reason must be a string")

    _validate_mature_ideas(response.get("mature_ideas"), require_gap_ids=require_gap_ids, errors=errors)
    for field_name in ("grounded_mature_idea", "grounded_refinement_scope"):
        value = response.get(field_name)
        if not isinstance(value, str):
            errors.append(f"{field_name} must be a string")
        elif require_grounded_fields and not value.strip():
            errors.append(f"{field_name} must be non-empty when no explicit mature idea is supplied")
    _validate_root_idea(response.get("root_idea"), errors)
    _validate_optional_seed_records(
        response.get("divergent_idea_seeds"),
        "divergent_idea_seeds",
        ("title", "hypothesis", "why_it_is_not_incremental", "method_sketch", "evaluation_plan", "risk"),
        errors,
        allow_empty_fields=("why_it_is_not_incremental",),
    )
    _validate_optional_seed_records(
        response.get("cross_domain_inspiration"),
        "cross_domain_inspiration",
        ("source_field", "transferable_mechanism", "application_hook"),
        errors,
    )
    if not _is_nonempty_string(response.get("tldr")):
        errors.append("tldr must be a non-empty string")
    return errors


def build_advanced_analysis_repair_prompt(
    base_prompt: str,
    invalid_response: Any,
    errors: Sequence[str],
) -> str:
    """Ask the model for a full replacement, retaining the original evidence context."""

    serialized_response = json.dumps(invalid_response, ensure_ascii=False, default=str)
    if len(serialized_response) > 12_000:
        serialized_response = serialized_response[:12_000] + "…[truncated]"
    error_lines = "\n".join(f"- {error}" for error in errors[:80])
    return (
        base_prompt
        + "\n\n== REQUIRED CONTRACT REPAIR ==\n"
        + "Your previous JSON response was syntactically valid but failed the mandatory advanced-analysis contract. "
        + "Return one complete replacement JSON object, with no Markdown and no commentary. Do not merely fill the omitted fields; "
        + "re-evaluate the supplied Survey evidence and make every required field mutually consistent.\n"
        + "The required top-level fields are exactly: "
        + ", ".join(sorted(_TOP_LEVEL_FIELDS))
        + ". `key_methods`, `field_consensus`, `existing_problems`, `evaluation_gaps`, `future_directions`, and `mature_ideas` must all be non-empty. "
        + "Always provide one concrete `root_idea` and at least one fully specified mature idea. "
        + "When Survey handoff is present, every mature idea must contain non-empty `target_gap_ids`.\n"
        + "Contract violations in the previous response:\n"
        + error_lines
        + "\nPrevious invalid JSON (for repair only):\n"
        + serialized_response
    )
