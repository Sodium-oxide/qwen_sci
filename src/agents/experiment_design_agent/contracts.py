"""Versioned JSON contracts for ExperimentDesign Agent's design-only phase."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from jsonschema import Draft202012Validator

from .reasoning_context import (
    REASONING_CONTEXT_SCHEMA,
    REASONING_CONTEXT_SCHEMA_VERSION,
    build_reasoning_context_from_idea_result,
)

from .discipline_catalog import (
    DESIGN_ONLY,
    DIGITAL_EXECUTION_ELIGIBLE,
    normalize_discipline_ids,
    resolve_design_scope,
    resolve_execution_policy,
)


RESEARCH_BRIEF_SCHEMA_VERSION = "research_brief_v1"
EVIDENCE_BUNDLE_SCHEMA_VERSION = "evidence_bundle_v1"
OUTCOME_BRANCH_SCHEMA_VERSION = "outcome_branch_v1"
EXPERIMENT_DESIGN_SCHEMA_VERSION = "experiment_design_v1"

_NONEMPTY_STRING = {"type": "string", "minLength": 1}
_STRING_LIST = {"type": "array", "items": _NONEMPTY_STRING}
_STATUS_VALUE = {
    "type": "string",
    "enum": [
        "evidence_backed",
        "user_declared",
        "design_assumption",
        "needs_human_input",
        "not_applicable",
    ],
}

RESEARCH_BRIEF_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "ResearchBrief v1",
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema_version",
        "brief_id",
        "topic",
        "discipline_ids",
        "selected_direction",
        "research_object",
        "evidence_status",
        "known_unknowns",
        "source",
        "reasoning_context",
    ],
    "properties": {
        "schema_version": {"const": RESEARCH_BRIEF_SCHEMA_VERSION},
        "brief_id": _NONEMPTY_STRING,
        "topic": _NONEMPTY_STRING,
        "discipline_ids": {"type": "array", "minItems": 1, "uniqueItems": True, "items": _NONEMPTY_STRING},
        "selected_direction": {
            "type": "object",
            "additionalProperties": False,
            "required": ["id", "title", "central_hypothesis", "mechanism_or_relation"],
            "properties": {
                "id": _NONEMPTY_STRING,
                "title": _NONEMPTY_STRING,
                "central_hypothesis": _NONEMPTY_STRING,
                "mechanism_or_relation": {"type": "string"},
            },
        },
        "research_object": {"type": "object", "minProperties": 1},
        "intervention_or_transformation": {"type": "string"},
        "discriminating_observations": _STRING_LIST,
        "boundary_conditions": _STRING_LIST,
        "alternative_explanations": _STRING_LIST,
        "known_unknowns": _STRING_LIST,
        "evidence_status": {"const": "PROPOSED"},
        "source": {
            "type": "object",
            "additionalProperties": False,
            "required": ["idea_result_schema", "direction_id"],
            "properties": {
                "idea_result_schema": {"const": "idea_result_v5"},
                "direction_id": _NONEMPTY_STRING,
                "survey_binding": {"type": "object"},
                "upstream_source_paths": {"type": "object"},
                "missing_audit_sources": _STRING_LIST,
            },
        },
        "reasoning_context": deepcopy(REASONING_CONTEXT_SCHEMA),
    },
}

EVIDENCE_BUNDLE_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "EvidenceBundle v1",
    "type": "object",
    "additionalProperties": False,
    "required": ["schema_version", "brief_id", "evidence_cards", "coverage"],
    "properties": {
        "schema_version": {"const": EVIDENCE_BUNDLE_SCHEMA_VERSION},
        "brief_id": _NONEMPTY_STRING,
        "evidence_cards": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "card_id",
                    "claim_slot",
                    "statement",
                    "design_implication",
                    "source_id",
                    "source_location",
                    "evidence_level",
                    "evidence_excerpt",
                    "limitations",
                    "does_not_establish",
                ],
                "properties": {
                    "card_id": _NONEMPTY_STRING,
                    "claim_slot": _NONEMPTY_STRING,
                    "statement": _NONEMPTY_STRING,
                    "design_implication": _NONEMPTY_STRING,
                    "source_id": _NONEMPTY_STRING,
                    "source_location": _NONEMPTY_STRING,
                    "evidence_level": {"enum": ["fulltext", "abstract", "metadata", "user_supplied"]},
                    "evidence_excerpt": _NONEMPTY_STRING,
                    "limitations": _STRING_LIST,
                    "does_not_establish": _STRING_LIST,
                },
            },
        },
        "paper_registry": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "canonical_paper_id",
                    "title",
                    "provider_ids",
                    "providers",
                    "query_task_ids",
                    "content_availability",
                    "fulltext_source_location",
                ],
                "properties": {
                    "canonical_paper_id": _NONEMPTY_STRING,
                    "title": _NONEMPTY_STRING,
                    "doi": {"type": "string"},
                    "authors": _STRING_LIST,
                    "year": {"type": "string"},
                    "venue": {"type": "string"},
                    "url": {"type": "string"},
                    "citation_rendering_status": {
                        "enum": ["RENDERABLE", "NOT_RENDERABLE_NEEDS_HUMAN_METADATA"]
                    },
                    "citation_missing_fields": _STRING_LIST,
                    "provider_ids": {"type": "object", "minProperties": 1},
                    "providers": _STRING_LIST,
                    "query_task_ids": _STRING_LIST,
                    "content_availability": {"enum": ["fulltext", "abstract", "metadata", "user_supplied", "unavailable"]},
                    "fulltext_source_location": {"type": "string"},
                    "keynote_status": {"enum": ["TRACEABLE_CARDS_AVAILABLE", "NO_CARDS_EXTRACTED", "NO_ELIGIBLE_TEXT"]},
                },
            },
        },
        "keynotes": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["canonical_paper_id", "status", "evidence_card_ids", "covered_slots", "source_locations"],
                "properties": {
                    "canonical_paper_id": _NONEMPTY_STRING,
                    "status": {"enum": ["TRACEABLE_CARDS_AVAILABLE", "NO_CARDS_EXTRACTED", "NO_ELIGIBLE_TEXT"]},
                    "evidence_card_ids": _STRING_LIST,
                    "covered_slots": _STRING_LIST,
                    "source_locations": _STRING_LIST,
                },
            },
        },
        "field_evidence_ledger": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["field_path", "status", "card_ids", "source_ids", "required_evidence_levels", "reason"],
                "properties": {
                    "field_path": _NONEMPTY_STRING,
                    "status": _STATUS_VALUE,
                    "card_ids": _STRING_LIST,
                    "source_ids": _STRING_LIST,
                    "required_evidence_levels": _STRING_LIST,
                    "reason": _NONEMPTY_STRING,
                },
            },
        },
        "retrieval_audit": {"type": "object"},
        "coverage": {
            "type": "object",
            "additionalProperties": False,
            "required": ["required_slots", "covered_slots", "uncovered_slots"],
            "properties": {
                "required_slots": _STRING_LIST,
                "covered_slots": _STRING_LIST,
                "uncovered_slots": _STRING_LIST,
            },
        },
    },
}

OUTCOME_BRANCH_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "OutcomeBranch v1",
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema_version",
        "branch_id",
        "trigger",
        "interpretation",
        "conclusion_scope",
        "improvement_actions",
        "evidence_status",
    ],
    "properties": {
        "schema_version": {"const": OUTCOME_BRANCH_SCHEMA_VERSION},
        "branch_id": {"enum": ["supports_mechanism", "partial_or_heterogeneous", "null_or_contradictory", "uninformative_or_invalid"]},
        "trigger": _NONEMPTY_STRING,
        "interpretation": _NONEMPTY_STRING,
        "conclusion_scope": _NONEMPTY_STRING,
        "improvement_actions": {"type": "array", "minItems": 1, "items": _NONEMPTY_STRING},
        "evidence_status": {"const": "EXPECTED_NOT_OBSERVED"},
    },
}

EXPERIMENT_DESIGN_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "ExperimentDesign v1",
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema_version",
        "design_id",
        "evidence_status",
        "execution_policy",
        "research_brief",
        "evidence_bundle",
        "research_design",
        "hypothesis_mapping",
        "variables_and_operationalization",
        "sampling_and_eligibility",
        "measurement_and_calibration",
        "comparison_and_robustness",
        "analysis_plan",
        "data_governance_and_reproducibility",
        "field_statuses",
        "outcome_branches",
        "risk_and_human_review",
        "open_design_questions",
        "observed_results",
        "validation_report",
    ],
    "properties": {
        "schema_version": {"const": EXPERIMENT_DESIGN_SCHEMA_VERSION},
        "design_id": _NONEMPTY_STRING,
        "evidence_status": {"const": "DESIGNED_NOT_EXECUTED"},
        "execution_policy": {
            "type": "object",
            "additionalProperties": False,
            "required": ["mode", "allow_digital_execution", "reason"],
            "properties": {
                "mode": {"enum": [DESIGN_ONLY, DIGITAL_EXECUTION_ELIGIBLE]},
                "allow_digital_execution": {"type": "boolean"},
                "reason": _NONEMPTY_STRING,
            },
        },
        "research_brief": deepcopy(RESEARCH_BRIEF_SCHEMA),
        "evidence_bundle": deepcopy(EVIDENCE_BUNDLE_SCHEMA),
        "variable_claim_model": {"type": "object"},
        "formal_reasoning_plan": {"type": "object"},
        "counterexample_analysis": {"type": "object"},
        "reasoning_validation_report": {"type": "object"},
        "research_design": {
            "type": "object",
            "additionalProperties": False,
            "required": ["design_type", "experimental_unit", "time_structure"],
            "properties": {
                "design_type": _NONEMPTY_STRING,
                "experimental_unit": _NONEMPTY_STRING,
                "time_structure": _NONEMPTY_STRING,
            },
        },
        "hypothesis_mapping": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["hypothesis_id", "claim", "observables", "decision_rule"],
                "properties": {
                    "hypothesis_id": _NONEMPTY_STRING,
                    "claim": _NONEMPTY_STRING,
                    "observables": _STRING_LIST,
                    "decision_rule": _NONEMPTY_STRING,
                },
            },
        },
        "variables_and_operationalization": {
            "type": "object",
            "additionalProperties": False,
            "required": ["independent_variables", "dependent_variables", "control_variables", "confounders", "operational_definitions"],
            "properties": {
                "independent_variables": {"type": "array"},
                "dependent_variables": {"type": "array"},
                "control_variables": {"type": "array"},
                "confounders": {"type": "array"},
                "operational_definitions": {"type": "array"},
            },
        },
        "sampling_and_eligibility": {
            "type": "object",
            "additionalProperties": False,
            "required": ["source", "eligibility_criteria", "sample_size_or_power_basis"],
            "properties": {
                "source": {"type": "object"},
                "eligibility_criteria": {"type": "object"},
                "sample_size_or_power_basis": {"type": "object"},
            },
        },
        "measurement_and_calibration": {
            "type": "object",
            "additionalProperties": False,
            "required": ["instruments", "measurement_plan", "calibration", "quality_control"],
            "properties": {
                "instruments": {"type": "array"},
                "measurement_plan": {"type": "object"},
                "calibration": {"type": "object"},
                "quality_control": {"type": "object"},
            },
        },
        "comparison_and_robustness": {
            "type": "object",
            "additionalProperties": False,
            "required": ["groups", "controls", "baselines", "comparisons", "ablation_sensitivity_robustness"],
            "properties": {
                "groups": {"type": "array"},
                "controls": {"type": "array"},
                "baselines": {"type": "array"},
                "comparisons": {"type": "array"},
                "ablation_sensitivity_robustness": {"type": "array"},
            },
        },
        "analysis_plan": {
            "type": "object",
            "additionalProperties": False,
            "required": ["randomization", "blinding", "repetitions", "batch_effects", "missing_data", "statistical_analysis"],
            "properties": {
                "randomization": {"type": "object"},
                "blinding": {"type": "object"},
                "repetitions": {"type": "object"},
                "batch_effects": {"type": "object"},
                "missing_data": {"type": "object"},
                "statistical_analysis": {"type": "object"},
            },
        },
        "data_governance_and_reproducibility": {
            "type": "object",
            "additionalProperties": False,
            "required": ["data_management", "reproducibility"],
            "properties": {
                "data_management": {"type": "object"},
                "reproducibility": {"type": "object"},
            },
        },
        "outcome_branches": {"type": "array", "minItems": 4, "items": deepcopy(OUTCOME_BRANCH_SCHEMA)},
        "risk_and_human_review": {
            "type": "object",
            "additionalProperties": False,
            "required": ["risk_level", "human_review_required", "review_triggers", "execution_prohibited"],
            "properties": {
                "risk_level": {"enum": ["low", "medium", "high", "critical"]},
                "human_review_required": {"type": "boolean"},
                "review_triggers": _STRING_LIST,
                "approval_dependencies": _STRING_LIST,
                "restricted_content": _STRING_LIST,
                "execution_prohibited": {"type": "boolean"},
            },
        },
        "template_composition": {
            "type": "object",
            "additionalProperties": False,
            "required": ["template_id", "secondary_template", "submode", "prompt_variant", "llm_used"],
            "properties": {
                "template_id": _NONEMPTY_STRING,
                "secondary_template": {"type": "string"},
                "submode": {"type": "string"},
                "prompt_variant": _NONEMPTY_STRING,
                "llm_used": {"type": "boolean"},
            },
        },
        "template_details": {"type": "object"},
        "field_statuses": {
            "type": "object",
            "additionalProperties": _NONEMPTY_STRING,
        },
        "open_design_questions": {"type": "array"},
        "observed_results": {"type": "array", "maxItems": 0},
        "validation_report": {
            "type": "object",
            "additionalProperties": False,
            "required": ["status", "errors", "warnings"],
            "properties": {
                "status": {"enum": ["READY_FOR_HUMAN_REVIEW", "DRAFT_REQUIRES_INPUT", "BLOCKED_BY_SCOPE", "BLOCKED_BY_RISK_REVIEW"]},
                "errors": _STRING_LIST,
                "warnings": _STRING_LIST,
            },
        },
    },
}


def _schema_errors(payload: Any, schema: Mapping[str, Any], *, prefix: str = "$") -> list[str]:
    errors: list[str] = []
    for error in sorted(Draft202012Validator(schema).iter_errors(payload), key=lambda item: list(item.absolute_path)):
        path = "/".join(str(part) for part in error.absolute_path)
        errors.append(f"{prefix}/{path}: {error.message}" if path else f"{prefix}: {error.message}")
    return errors


def _scope_errors(discipline_ids: object) -> list[str]:
    scope = resolve_design_scope(discipline_ids)
    if scope["status"] == "IN_SCOPE":
        return []
    errors: list[str] = []
    errors.extend(f"excluded_discipline:{identifier}" for identifier in scope["excluded_discipline_ids"])
    errors.extend(f"unresolved_discipline:{identifier}" for identifier in scope["unresolved_disciplines"])
    if not errors:
        errors.append("discipline_scope_requires_clarification")
    return errors


def validate_research_brief(payload: Any) -> list[str]:
    errors = _schema_errors(payload, RESEARCH_BRIEF_SCHEMA)
    if isinstance(payload, Mapping):
        errors.extend(_scope_errors(payload.get("discipline_ids")))
    return errors


def validate_evidence_bundle(payload: Any) -> list[str]:
    errors = _schema_errors(payload, EVIDENCE_BUNDLE_SCHEMA)
    if not isinstance(payload, Mapping):
        return errors
    registry = payload.get("paper_registry")
    paper_ids = {
        str(record.get("canonical_paper_id") or "").strip()
        for record in registry
        if isinstance(record, Mapping)
    } if isinstance(registry, list) else set()
    if isinstance(registry, list) and len(paper_ids) != len(registry):
        errors.append("paper_registry_contains_missing_or_duplicate_canonical_paper_id")
    if isinstance(registry, list):
        for record in registry:
            if not isinstance(record, Mapping):
                continue
            rendering_status = str(record.get("citation_rendering_status") or "").strip()
            if not rendering_status:
                continue
            missing_fields = {
                str(field).strip()
                for field in record.get("citation_missing_fields") or []
                if str(field).strip()
            }
            expected_missing_fields = {
                field
                for field, value in (
                    ("authors", record.get("authors")),
                    ("year", record.get("year")),
                    ("venue", record.get("venue")),
                )
                if not value
            }
            if rendering_status == "RENDERABLE" and missing_fields:
                errors.append("renderable_citation_lists_missing_metadata")
            elif rendering_status == "RENDERABLE" and expected_missing_fields:
                errors.append("renderable_citation_is_missing_required_metadata")
            elif rendering_status == "NOT_RENDERABLE_NEEDS_HUMAN_METADATA":
                if not missing_fields:
                    errors.append("non_renderable_citation_omits_missing_metadata")
                elif missing_fields != expected_missing_fields:
                    errors.append("non_renderable_citation_missing_metadata_mismatch")
    cards = payload.get("evidence_cards")
    card_ids: set[str] = set()
    card_by_id: dict[str, Mapping[str, Any]] = {}
    if isinstance(cards, list):
        if cards and not isinstance(registry, list):
            errors.append("evidence_cards_require_paper_registry")
        for card in cards:
            if not isinstance(card, Mapping):
                continue
            card_id = str(card.get("card_id") or "").strip()
            source_id = str(card.get("source_id") or "").strip()
            if card_id in card_ids:
                errors.append(f"duplicate_evidence_card_id:{card_id}")
            if card_id:
                card_ids.add(card_id)
                card_by_id[card_id] = card
            if isinstance(registry, list) and source_id not in paper_ids:
                errors.append(f"evidence_card_unknown_source_id:{source_id}")
    ledger = payload.get("field_evidence_ledger")
    if isinstance(ledger, list):
        seen_fields: set[str] = set()
        for record in ledger:
            if not isinstance(record, Mapping):
                continue
            field_path = str(record.get("field_path") or "").strip()
            if field_path in seen_fields:
                errors.append(f"duplicate_field_evidence_ledger_path:{field_path}")
            if field_path:
                seen_fields.add(field_path)
            referenced_cards = [
                str(card_id).strip()
                for card_id in record.get("card_ids") or []
                if str(card_id).strip()
            ]
            for card_id in referenced_cards:
                if card_id not in card_ids:
                    errors.append(f"field_evidence_ledger_unknown_card_id:{field_path}:{card_id}")
            if record.get("status") == "evidence_backed":
                required_levels = set(record.get("required_evidence_levels") or [])
                qualifying = [
                    card_by_id[card_id]
                    for card_id in referenced_cards
                    if card_id in card_by_id
                    and card_by_id[card_id].get("evidence_level") in required_levels
                ]
                if not qualifying:
                    errors.append(f"evidence_backed_field_without_qualifying_card:{field_path}")
    return errors


def validate_outcome_branch(payload: Any) -> list[str]:
    return _schema_errors(payload, OUTCOME_BRANCH_SCHEMA)


def validate_experiment_design(payload: Any) -> list[str]:
    errors = _schema_errors(payload, EXPERIMENT_DESIGN_SCHEMA)
    if not isinstance(payload, Mapping):
        return errors
    research_brief = payload.get("research_brief")
    evidence_bundle = payload.get("evidence_bundle")
    if isinstance(research_brief, Mapping):
        errors.extend(f"research_brief:{error}" for error in validate_research_brief(research_brief))
    if isinstance(evidence_bundle, Mapping):
        errors.extend(f"evidence_bundle:{error}" for error in validate_evidence_bundle(evidence_bundle))
    if isinstance(research_brief, Mapping) and isinstance(evidence_bundle, Mapping):
        if evidence_bundle.get("brief_id") != research_brief.get("brief_id"):
            errors.append("evidence_bundle_brief_id_mismatch")
    reasoning_context = _mapping(research_brief.get("reasoning_context")) if isinstance(research_brief, Mapping) else {}
    if reasoning_context:
        errors.extend(
            f"research_brief.reasoning_context:{error}"
            for error in _schema_errors(reasoning_context, REASONING_CONTEXT_SCHEMA)
        )
    from .reasoning_validation import validate_reasoning_artifacts

    errors.extend(
        validate_reasoning_artifacts(
            variable_claim_model=payload.get("variable_claim_model") if isinstance(payload.get("variable_claim_model"), Mapping) else None,
            formal_reasoning_plan=payload.get("formal_reasoning_plan") if isinstance(payload.get("formal_reasoning_plan"), Mapping) else None,
            counterexample_analysis=payload.get("counterexample_analysis") if isinstance(payload.get("counterexample_analysis"), Mapping) else None,
            design=payload,
            template_composition=payload.get("template_composition") if isinstance(payload.get("template_composition"), Mapping) else None,
        )
    )
    field_statuses = payload.get("field_statuses")
    status_sections = {
        "research_design",
        "hypothesis_mapping",
        "variables_and_operationalization",
        "sampling_and_eligibility",
        "measurement_and_calibration",
        "comparison_and_robustness",
        "analysis_plan",
        "data_governance_and_reproducibility",
        "template_details",
    }
    def nested_status_paths(value: object, path: str) -> list[str]:
        found: list[str] = []
        if isinstance(value, Mapping):
            for key, child in value.items():
                child_path = f"{path}.{key}" if path else str(key)
                if key == "status":
                    found.append(child_path)
                else:
                    found.extend(nested_status_paths(child, child_path))
        elif isinstance(value, list):
            for index, child in enumerate(value):
                found.extend(nested_status_paths(child, f"{path}[{index}]"))
        return found
    for section in status_sections:
        for path in nested_status_paths(payload.get(section), section):
            errors.append(f"{path}:status_must_use_top_level_field_statuses")
    if isinstance(field_statuses, Mapping) and isinstance(evidence_bundle, Mapping):
        qualifying_fields = {
            str(record.get("field_path") or "").strip()
            for record in evidence_bundle.get("field_evidence_ledger") or []
            if isinstance(record, Mapping) and record.get("status") == "evidence_backed"
        }
        for field_path, status in field_statuses.items():
            if status == "evidence_backed" and str(field_path) not in qualifying_fields:
                errors.append(f"field_status_evidence_not_qualified:{field_path}")
    branches = payload.get("outcome_branches")
    if isinstance(branches, list):
        errors.extend(
            f"outcome_branches[{index}]:{error}"
            for index, branch in enumerate(branches)
            for error in validate_outcome_branch(branch)
        )
        expected_ids = {
            "supports_mechanism",
            "partial_or_heterogeneous",
            "null_or_contradictory",
            "uninformative_or_invalid",
        }
        actual_ids = [branch.get("branch_id") for branch in branches if isinstance(branch, Mapping)]
        if set(actual_ids) != expected_ids or len(actual_ids) != len(expected_ids):
            errors.append("outcome_branches_must_cover_each_required_branch_once")
    policy = payload.get("execution_policy")
    if isinstance(research_brief, Mapping) and isinstance(policy, Mapping):
        expected = resolve_execution_policy(
            research_brief.get("discipline_ids"),
            allow_digital_execution=bool(policy.get("allow_digital_execution")),
        )
        if policy.get("mode") != expected["mode"]:
            errors.append("execution_policy_mode_does_not_match_discipline_scope")
    return errors


def assert_valid(payload: Any, validator) -> dict[str, Any]:
    errors = validator(payload)
    if errors:
        raise ValueError("; ".join(errors))
    return dict(payload)


def _text(value: Any) -> str:
    return str(value or "").strip()


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _texts(value: Any) -> list[str]:
    values = value if isinstance(value, (list, tuple, set)) else [value]
    result: list[str] = []
    for item in values:
        text = _text(item)
        if text and text not in result:
            result.append(text)
    return result


def _idea_source_layers(
    direction: Mapping[str, Any],
    idea_result: Mapping[str, Any],
    audit_sources: Mapping[str, Any] | None,
) -> list[tuple[str, Mapping[str, Any]]]:
    """Expose source precedence without ever combining multiple directions."""

    layers: list[tuple[str, Mapping[str, Any]]] = []

    def add_nested(prefix: str, value: object) -> None:
        record = value if isinstance(value, Mapping) else {}
        for nested_key in ("hypothesis", "experiment_handoff"):
            nested = record.get(nested_key)
            if isinstance(nested, Mapping):
                layers.append((f"{prefix}.{nested_key}", nested))
        layers.append((prefix, record))

    add_nested("selected_direction", direction)
    add_nested("legacy_best_entry", idea_result.get("legacy_best_entry"))
    audit = audit_sources if isinstance(audit_sources, Mapping) else {}
    add_nested("selected_primary_idea", audit.get("selected_primary_idea"))
    add_nested("idea_candidate", audit.get("idea_candidate"))
    return layers


def _first_idea_value(
    layers: list[tuple[str, Mapping[str, Any]]],
    keys: tuple[str, ...],
) -> Any:
    for _, layer in layers:
        for key in keys:
            value = layer.get(key)
            if value not in (None, "", [], {}):
                return deepcopy(value)
    return ""


def build_research_brief_from_idea_result(
    idea_result: Mapping[str, Any],
    *,
    discipline_ids: object,
    brief_id: str,
    selected_direction: str = "",
    audit_sources: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Create a v1 ResearchBrief from one explicitly selected Idea Agent direction."""

    if idea_result.get("schema_version") != "idea_result_v5":
        raise ValueError("ResearchBrief v1 requires an idea_result_v5 input.")
    directions = [item for item in idea_result.get("directions") or [] if isinstance(item, Mapping)]
    requested = _text(selected_direction) or _text(idea_result.get("primary_direction"))
    matching = [
        direction
        for direction in directions
        if _text(direction.get("direction_mode")) == requested
        or _text(direction.get("id")) == requested
        or _text(direction.get("title")) == requested
    ]
    if len(matching) != 1:
        raise ValueError("ResearchBrief v1 requires one unambiguous selected Idea Agent direction.")
    direction = matching[0]
    hypothesis = direction.get("hypothesis") if isinstance(direction.get("hypothesis"), Mapping) else {}
    handoff = direction.get("experiment_handoff") if isinstance(direction.get("experiment_handoff"), Mapping) else {}
    direction_id = _text(direction.get("direction_mode")) or _text(direction.get("id")) or _text(direction.get("title"))
    idea_layers = _idea_source_layers(direction, idea_result, audit_sources)
    research_object = _first_idea_value(idea_layers, ("scientific_object", "research_object")) or {}
    if not isinstance(research_object, Mapping):
        research_object = {"description": _text(research_object)} if _text(research_object) else {}
    title = _text(direction.get("title")) or _text(_first_idea_value(idea_layers, ("title",))) or _text(idea_result.get("title"))
    payload = {
        "schema_version": RESEARCH_BRIEF_SCHEMA_VERSION,
        "brief_id": _text(brief_id),
        "topic": _text(idea_result.get("topic")) or _text(idea_result.get("title")) or title,
        "discipline_ids": list(normalize_discipline_ids(discipline_ids)),
        "selected_direction": {
            "id": direction_id,
            "title": title,
            "central_hypothesis": _text(_first_idea_value(idea_layers, ("central_hypothesis", "claim_to_test"))),
            "mechanism_or_relation": _text(_first_idea_value(idea_layers, ("mechanism_or_relation", "mechanism_to_discriminate"))),
        },
        "research_object": dict(research_object),
        "intervention_or_transformation": _text(_first_idea_value(idea_layers, ("intervention_or_transformation",))),
        "discriminating_observations": _texts(_first_idea_value(idea_layers, ("required_observations", "discriminating_observations", "discriminating_observation"))),
        "boundary_conditions": _texts(_first_idea_value(idea_layers, ("boundary_conditions", "boundary_or_failure_condition"))),
        "alternative_explanations": _texts(_first_idea_value(idea_layers, ("alternative_explanations",))),
        "known_unknowns": _texts(_first_idea_value(idea_layers, ("known_unknowns",))),
        "evidence_status": "PROPOSED",
        "source": {
            "idea_result_schema": "idea_result_v5",
            "direction_id": direction_id,
            "survey_binding": dict(idea_result.get("survey_binding") or {}),
        },
        "reasoning_context": build_reasoning_context_from_idea_result(
            idea_result,
            selected_direction=selected_direction,
            audit_sources=audit_sources,
        ),
    }
    assert_valid(payload, validate_research_brief)
    return payload
