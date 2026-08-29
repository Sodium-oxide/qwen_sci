"""Strict, English-only contracts for Research Plan Author preparation."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from jsonschema import Draft202012Validator

from src.agents.experiment_design_agent.artifacts import AUTHOR_HANDOFF_SCHEMA_VERSION
from src.agents.experiment_design_agent.reasoning_context import REASONING_CONTEXT_SCHEMA

from .latex_safety import contains_non_english_script, contains_observed_result_language


RESEARCH_PLAN_AUTHOR_INPUT_SCHEMA_VERSION = AUTHOR_HANDOFF_SCHEMA_VERSION
AUTHOR_SOURCE_BUNDLE_SCHEMA_VERSION = "research_plan_author_source_bundle_v2"
RESEARCH_PLAN_DOCUMENT_SCHEMA_VERSION = "research_plan_document_v1"
AUTHOR_PREPARATION_SCHEMA_VERSION = "research_plan_author_preparation_v1"
AUTHORING_LANGUAGE = "en"

_NONEMPTY_STRING = {"type": "string", "minLength": 1}
_OBJECT = {"type": "object"}
_COMPACT_CARD_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["card_id", "source_id", "citation_key", "evidence_level", "claim_slot", "source_location"],
    "properties": {
        "card_id": _NONEMPTY_STRING,
        "source_id": _NONEMPTY_STRING,
        "citation_key": _NONEMPTY_STRING,
        "evidence_level": _NONEMPTY_STRING,
        "claim_slot": {"type": "string"},
        "source_location": {"type": "string"},
    },
}
_COMPACT_CITATION_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["citation_key", "source_id", "evidence_level", "evidence_card_ids"],
    "properties": {
        "citation_key": _NONEMPTY_STRING,
        "source_id": _NONEMPTY_STRING,
        "evidence_level": _NONEMPTY_STRING,
        "evidence_card_ids": {"type": "array", "items": _NONEMPTY_STRING, "uniqueItems": True},
    },
}
_SOURCE_REGISTRY_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["allowed_source_ids", "allowed_survey_anchor_ids", "evidence_cards_by_id", "citation_registry"],
    "properties": {
        "allowed_source_ids": {"type": "array", "items": {"type": "string"}, "uniqueItems": True},
        "allowed_survey_anchor_ids": {"type": "array", "items": {"type": "string"}, "uniqueItems": True},
        "evidence_cards_by_id": {"type": "object", "additionalProperties": _COMPACT_CARD_SCHEMA},
        "citation_registry": {"type": "array", "items": _COMPACT_CITATION_SCHEMA},
    },
}

AUTHOR_INPUT_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "Research Plan Author Input v3",
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema_version",
        "generated_at",
        "source_design_id",
        "selected_direction",
        "research_design",
        "hypothesis_mapping",
        "variables_and_operationalization",
        "field_statuses",
        "reasoning_context",
        "formal_reasoning",
        "counterexample_analysis",
        "outcome_branches",
        "unknown_items",
        "review_items",
        "source_registry",
        "authoring_constraints",
        "provenance",
    ],
    "properties": {
        "schema_version": {"const": RESEARCH_PLAN_AUTHOR_INPUT_SCHEMA_VERSION},
        "generated_at": _NONEMPTY_STRING,
        "source_design_id": _NONEMPTY_STRING,
        "selected_direction": _OBJECT,
        "research_design": _OBJECT,
        "hypothesis_mapping": {"type": "array"},
        "variables_and_operationalization": _OBJECT,
        "field_statuses": {"type": "object", "additionalProperties": _NONEMPTY_STRING},
        "reasoning_context": deepcopy(REASONING_CONTEXT_SCHEMA),
        "formal_reasoning": _OBJECT,
        "counterexample_analysis": _OBJECT,
        "outcome_branches": {"type": "array"},
        "unknown_items": {"type": "array"},
        "review_items": {"type": "array"},
        "source_registry": _SOURCE_REGISTRY_SCHEMA,
        "authoring_constraints": {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "proposal_without_observed_results",
                "unverified_reasoning_must_be_labeled",
                "unsupported_claims_forbidden",
                "counterexample_must_satisfy_all_assumptions",
                "formal_and_empirical_claims_must_remain_separate",
                "observed_results_are_absent",
            ],
            "properties": {
                "proposal_without_observed_results": {"type": "boolean"},
                "unverified_reasoning_must_be_labeled": {"type": "boolean"},
                "unsupported_claims_forbidden": {"type": "boolean"},
                "counterexample_must_satisfy_all_assumptions": {"type": "boolean"},
                "formal_and_empirical_claims_must_remain_separate": {"type": "boolean"},
                "observed_results_are_absent": {"type": "boolean"},
            },
        },
        "provenance": {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "idea_result_path",
                "audit_source_paths",
                "selected_direction_id",
                "template_id",
                "validation_status",
                "discipline_ids",
                "survey_binding",
                "risk_level",
            ],
            "properties": {
                "idea_result_path": {"type": "string"},
                "audit_source_paths": _OBJECT,
                "selected_direction_id": _NONEMPTY_STRING,
                "template_id": {"type": "string"},
                "discipline_ids": {"type": "array", "items": _NONEMPTY_STRING, "uniqueItems": True},
                "survey_binding": _OBJECT,
                "risk_level": {"type": "string"},
                "validation_status": {"type": "string"},
            },
        },
    },
}

_BLOCK_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["block_id", "kind", "text", "claim_ids"],
    "properties": {
        "block_id": _NONEMPTY_STRING,
        "kind": {
            "enum": [
                "paragraph",
                "list",
                "table",
                "definition",
                "proposition",
                "equation",
                "protocol",
                "outcome_branch",
                "review_checklist",
            ]
        },
        "text": {"type": "string"},
        "claim_ids": {"type": "array", "items": _NONEMPTY_STRING, "uniqueItems": True},
    },
}

_SECTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["section_id", "title", "applicability", "blocks"],
    "properties": {
        "section_id": _NONEMPTY_STRING,
        "title": _NONEMPTY_STRING,
        "applicability": {"enum": ["required", "optional", "not_applicable"]},
        "blocks": {"type": "array", "items": _BLOCK_SCHEMA},
    },
}

RESEARCH_PLAN_DOCUMENT_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "Research Plan Document v1",
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema_version",
        "document_status",
        "language",
        "source_design_id",
        "document_metadata",
        "abstract",
        "keywords",
        "sections",
        "appendices",
        "citation_registry",
        "claim_provenance",
        "open_items",
        "review_items",
        "authoring_constraints",
        "source_manifest",
    ],
    "properties": {
        "schema_version": {"const": RESEARCH_PLAN_DOCUMENT_SCHEMA_VERSION},
        "document_status": {"enum": ["PREPARATION_ONLY", "PROPOSAL_NO_OBSERVED_RESULTS"]},
        "language": {"const": AUTHORING_LANGUAGE},
        "source_design_id": _NONEMPTY_STRING,
        "document_metadata": {
            "type": "object",
            "additionalProperties": False,
            "required": ["title", "discipline_ids", "study_type"],
            "properties": {
                "title": {"type": "string"},
                "source_title": {"type": "string"},
                "title_status": {"type": "string"},
                "discipline_ids": {"type": "array", "items": _NONEMPTY_STRING, "uniqueItems": True},
                "study_type": {"type": "string"},
            },
        },
        "abstract": {"type": "object", "additionalProperties": False, "required": ["text", "claim_ids"], "properties": {"text": {"type": "string"}, "claim_ids": {"type": "array", "items": _NONEMPTY_STRING, "uniqueItems": True}}},
        "keywords": {"type": "array", "items": _NONEMPTY_STRING, "uniqueItems": True},
        "sections": {"type": "array", "items": _SECTION_SCHEMA},
        "appendices": {"type": "array", "items": _SECTION_SCHEMA},
        "citation_registry": {"type": "array", "items": _OBJECT},
        "claim_provenance": {"type": "array", "items": _OBJECT},
        "open_items": {"type": "array", "items": {}},
        "review_items": {"type": "array", "items": {}},
        "authoring_constraints": _OBJECT,
        "source_manifest": _OBJECT,
        "authoring_blueprint": _OBJECT,
        "contract_repair_audit": {"type": "array", "items": _OBJECT},
    },
}

AUTHOR_SOURCE_BUNDLE_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "Research Plan Author Source Bundle v2",
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema_version",
        "language",
        "source_design_id",
        "selected_direction_id",
        "author_input_path",
        "author_input_identity",
        "author_context",
        "survey_sources",
        "survey_binding",
        "idea_evolution",
    ],
    "properties": {
        "schema_version": {"const": AUTHOR_SOURCE_BUNDLE_SCHEMA_VERSION},
        "language": {"const": AUTHORING_LANGUAGE},
        "source_design_id": _NONEMPTY_STRING,
        "selected_direction_id": _NONEMPTY_STRING,
        "author_input_path": _NONEMPTY_STRING,
        "author_input_identity": {
            "type": "object",
            "additionalProperties": False,
            "required": ["path", "sha256", "byte_size"],
            "properties": {
                "path": _NONEMPTY_STRING,
                "sha256": {"type": "string", "pattern": "^[a-f0-9]{64}$"},
                "byte_size": {"type": "integer", "minimum": 1},
            },
        },
        "author_context": AUTHOR_INPUT_SCHEMA,
        "survey_sources": _OBJECT,
        "survey_binding": {
            "type": "object",
            "additionalProperties": False,
            "required": ["status", "expected", "resolved", "human_confirmation_required"],
            "properties": {
                "status": {
                    "enum": [
                        "BOUND_VERIFIED",
                        "UNBOUND_REQUIRES_HUMAN_CONFIRMATION",
                    ]
                },
                "expected": _OBJECT,
                "resolved": _OBJECT,
                "human_confirmation_required": {"type": "boolean"},
            },
        },
        "idea_evolution": _OBJECT,
    },
}

AUTHOR_PREPARATION_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "Research Plan Author Preparation v1",
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema_version",
        "status",
        "generated_at",
        "language",
        "source_design_id",
        "selected_direction_id",
        "source_bundle",
        "document",
    ],
    "properties": {
        "schema_version": {"const": AUTHOR_PREPARATION_SCHEMA_VERSION},
        "status": {"enum": ["PREPARED_FOR_COMPOSITION", "COMPOSED_FOR_RENDERING"]},
        "generated_at": _NONEMPTY_STRING,
        "language": {"const": AUTHORING_LANGUAGE},
        "source_design_id": _NONEMPTY_STRING,
        "selected_direction_id": _NONEMPTY_STRING,
        "source_bundle": AUTHOR_SOURCE_BUNDLE_SCHEMA,
        "document": RESEARCH_PLAN_DOCUMENT_SCHEMA,
    },
}


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _text(value: object) -> str:
    return str(value or "").strip()


def _schema_errors(schema: Mapping[str, Any], payload: object) -> list[str]:
    errors: list[str] = []
    for error in Draft202012Validator(schema).iter_errors(payload):
        path = "/".join(str(part) for part in error.absolute_path) or "$"
        errors.append(f"{path}: {error.message}")
    return sorted(errors)


def validate_author_input(payload: object) -> list[str]:
    """Validate the handoff and preserve proposal-only research boundaries."""

    errors = _schema_errors(AUTHOR_INPUT_SCHEMA, payload)
    if not isinstance(payload, Mapping):
        return errors
    handoff = dict(payload)
    selected_direction = _mapping(handoff.get("selected_direction"))
    if not _text(selected_direction.get("id")):
        errors.append("selected_direction.id is required")
    selected_direction_id = _text(_mapping(handoff.get("provenance")).get("selected_direction_id"))
    design_direction_id = _text(selected_direction.get("id"))
    if selected_direction_id != design_direction_id:
        errors.append("provenance.selected_direction_id does not match the design selected direction")
    context_direction_id = _text(_mapping(handoff.get("reasoning_context")).get("selected_direction_id"))
    if context_direction_id and context_direction_id != design_direction_id:
        errors.append("reasoning_context.selected_direction_id does not match selected_direction.id")
    constraints = _mapping(handoff.get("authoring_constraints"))
    for name in (
        "proposal_without_observed_results",
        "unverified_reasoning_must_be_labeled",
        "unsupported_claims_forbidden",
        "counterexample_must_satisfy_all_assumptions",
        "formal_and_empirical_claims_must_remain_separate",
        "observed_results_are_absent",
    ):
        if constraints.get(name) is not True:
            errors.append(f"authoring_constraints.{name} must be true")
    if not _mapping(handoff.get("reasoning_context")):
        errors.append("reasoning_context is required")
    registry = _mapping(handoff.get("source_registry"))
    for card_id, card in (_mapping(registry.get("evidence_cards_by_id"))).items():
        if not isinstance(card, Mapping):
            errors.append(f"source_registry.evidence_cards_by_id.{card_id} must be an object")
            continue
        required_card_fields = {"card_id", "source_id", "citation_key", "evidence_level", "claim_slot", "source_location"}
        missing = required_card_fields - set(card)
        if missing:
            errors.append(f"source_registry.evidence_cards_by_id.{card_id} is missing fields: {sorted(missing)}")
        allowed = required_card_fields
        extra = set(card) - allowed
        if extra:
            errors.append(f"source_registry.evidence_cards_by_id.{card_id} contains unsupported fields: {sorted(extra)}")
        if _text(card.get("card_id")) != _text(card_id):
            errors.append(f"source_registry.evidence_cards_by_id.{card_id}.card_id does not match its registry key")
        if _text(card.get("source_id")) not in {
            _text(source_id) for source_id in registry.get("allowed_source_ids") or []
        }:
            errors.append(f"source_registry.evidence_cards_by_id.{card_id}.source_id is not allowed")
    citation_keys = set()
    for index, citation in enumerate(registry.get("citation_registry") or []):
        if not isinstance(citation, Mapping):
            continue
        citation_key = _text(citation.get("citation_key"))
        if citation_key in citation_keys:
            errors.append(f"source_registry.citation_registry contains duplicate citation_key: {citation_key}")
        citation_keys.add(citation_key)
        source_id = _text(citation.get("source_id"))
        if source_id not in {
            _text(value) for value in registry.get("allowed_source_ids") or []
        }:
            errors.append(f"source_registry.citation_registry[{index}].source_id is not allowed")
    return sorted(set(errors))


def validate_research_plan_document(payload: object) -> list[str]:
    """Validate the document container before future prose or TeX rendering."""

    errors = _schema_errors(RESEARCH_PLAN_DOCUMENT_SCHEMA, payload)
    if not isinstance(payload, Mapping):
        return errors
    document = dict(payload)
    if document.get("language") != AUTHORING_LANGUAGE:
        errors.append("Research Plan Author documents must use English (language='en')")
    if document.get("document_status") == "PROPOSAL_NO_OBSERVED_RESULTS":
        for record in document.get("claim_provenance") or []:
            if isinstance(record, Mapping) and record.get("claim_kind") == "observed_result":
                errors.append("proposal document must not contain observed_result claims")
        claim_id_set = {
            _text(record.get("claim_id"))
            for record in document.get("claim_provenance") or []
            if isinstance(record, Mapping) and _text(record.get("claim_id"))
        }

        def validate_visible_text(label: str, value: object) -> None:
            text = _text(value)
            if not text:
                return
            if contains_non_english_script(text):
                errors.append(f"{label} contains non-English-script visible prose")
            if contains_observed_result_language(text):
                errors.append(f"{label} presents an observed result")

        metadata = _mapping(document.get("document_metadata"))
        validate_visible_text("document title", metadata.get("title"))
        abstract = _mapping(document.get("abstract"))
        validate_visible_text("abstract", abstract.get("text"))
        abstract_claim_ids = {_text(claim_id) for claim_id in abstract.get("claim_ids") or [] if _text(claim_id)}
        if _text(abstract.get("text")) and not abstract_claim_ids:
            errors.append("visible abstract must reference at least one claim ID")
        if abstract_claim_ids - claim_id_set:
            errors.append("visible abstract references an unknown claim ID")
        for keyword in document.get("keywords") or []:
            validate_visible_text("keyword", keyword)
        for collection_name in ("sections", "appendices"):
            for section in document.get(collection_name) or []:
                if not isinstance(section, Mapping):
                    continue
                section_id = _text(section.get("section_id")) or collection_name
                validate_visible_text(f"section {section_id} title", section.get("title"))
                for block in section.get("blocks") or []:
                    if not isinstance(block, Mapping):
                        continue
                    block_id = _text(block.get("block_id")) or "unnamed"
                    block_text = _text(block.get("text"))
                    validate_visible_text(f"section block {block_id}", block_text)
                    block_claim_ids = {
                        _text(claim_id)
                        for claim_id in block.get("claim_ids") or []
                        if _text(claim_id)
                    }
                    if block_text and not block_claim_ids:
                        errors.append(f"visible section block {block_id} must reference at least one claim ID")
                    if block_claim_ids - claim_id_set:
                        errors.append(f"visible section block {block_id} references an unknown claim ID")
    section_ids = [
        _text(section.get("section_id"))
        for section in document.get("sections") or []
        if isinstance(section, Mapping)
    ]
    if len(section_ids) != len(set(section_ids)):
        errors.append("document contains duplicate section_id values")
    return sorted(set(errors))


def validate_author_preparation(payload: object) -> list[str]:
    """Validate the frozen cross-agent boundary consumed by Author composition."""

    errors = _schema_errors(AUTHOR_PREPARATION_SCHEMA, payload)
    if not isinstance(payload, Mapping):
        return errors
    preparation = dict(payload)
    source_bundle = _mapping(preparation.get("source_bundle"))
    document = _mapping(preparation.get("document"))
    errors.extend(f"source_bundle: {error}" for error in _schema_errors(AUTHOR_SOURCE_BUNDLE_SCHEMA, source_bundle))
    errors.extend(f"document: {error}" for error in validate_research_plan_document(document))
    source_design_id = _text(preparation.get("source_design_id"))
    selected_direction_id = _text(preparation.get("selected_direction_id"))
    if source_design_id != _text(source_bundle.get("source_design_id")):
        errors.append("source_design_id does not match source_bundle.source_design_id")
    if source_design_id != _text(document.get("source_design_id")):
        errors.append("source_design_id does not match document.source_design_id")
    if selected_direction_id != _text(source_bundle.get("selected_direction_id")):
        errors.append("selected_direction_id does not match source_bundle.selected_direction_id")
    source_manifest = _mapping(document.get("source_manifest"))
    if selected_direction_id != _text(source_manifest.get("selected_direction_id")):
        errors.append("selected_direction_id does not match document.source_manifest.selected_direction_id")
    context = _mapping(source_bundle.get("author_context"))
    if context:
        errors.extend(f"author_context: {error}" for error in validate_author_input(context))
        if source_design_id != _text(context.get("source_design_id")):
            errors.append("source_design_id does not match source_bundle.author_context.source_design_id")
    binding = _mapping(source_bundle.get("survey_binding"))
    status = _text(binding.get("status"))
    expected = _mapping(binding.get("expected"))
    resolved = _mapping(binding.get("resolved"))
    binding_fields = ("survey_run_id", "project_id", "project_context_fingerprint")
    if status == "BOUND_VERIFIED":
        if binding.get("human_confirmation_required") is not False:
            errors.append("bound survey binding may not require human confirmation")
        for field in binding_fields:
            if not _text(expected.get(field)):
                errors.append(f"bound survey binding is missing expected.{field}")
            if _text(expected.get(field)) != _text(resolved.get(field)):
                errors.append(f"bound survey binding mismatch for {field}")
    elif status == "UNBOUND_REQUIRES_HUMAN_CONFIRMATION":
        if binding.get("human_confirmation_required") is not True:
            errors.append("unbound survey binding must require human confirmation")
    return sorted(set(errors))


def build_research_plan_document_skeleton(
    author_input: Mapping[str, Any],
    source_bundle: Mapping[str, Any],
) -> dict[str, Any]:
    """Create an English-only empty document contract for later composition."""

    selected_direction = _mapping(author_input.get("selected_direction"))
    research_design = _mapping(author_input.get("research_design"))
    required_sections = [
        ("introduction", "Introduction"),
        ("survey_and_research_gap", "Background, Survey, and Research Gap"),
        ("research_questions_and_contributions", "Research Questions and Planned Contributions"),
        ("idea_origin_and_selection", "Idea Origin and Direction Selection"),
        ("formal_problem_and_hypotheses", "Problem Definition, Assumptions, and Hypotheses"),
        ("study_design_and_methods", "Study Design and Methods"),
        ("expected_outcomes", "Expected Outcome Branches and Conditional Conclusions"),
        ("risk_limitations_and_review", "Risks, Limitations, and Human Review Requirements"),
        ("references", "References"),
    ]
    sections = [
        {"section_id": section_id, "title": title, "applicability": "required", "blocks": []}
        for section_id, title in required_sections
    ]
    appendices = [
        {
            "section_id": "appendix_idea_evolution",
            "title": "Idea Evolution and Direction Selection Audit",
            "applicability": "optional",
            "blocks": [],
        },
        {
            "section_id": "appendix_variables_and_definitions",
            "title": "Variables, Symbols, and Operational Definitions",
            "applicability": "required",
            "blocks": [],
        },
        {
            "section_id": "appendix_evidence_and_review",
            "title": "Evidence Coverage, Unknown Items, and Review Checklist",
            "applicability": "required",
            "blocks": [],
        },
    ]
    return {
        "schema_version": RESEARCH_PLAN_DOCUMENT_SCHEMA_VERSION,
        "document_status": "PREPARATION_ONLY",
        "language": AUTHORING_LANGUAGE,
        "source_design_id": _text(author_input.get("source_design_id")),
        "document_metadata": {
            "title": "",
            "source_title": _text(selected_direction.get("title")),
            "title_status": "requires_english_llm_composition",
            "discipline_ids": list(_mapping(author_input.get("provenance")).get("discipline_ids") or []),
            "study_type": _text(research_design.get("design_type")),
        },
        "abstract": {"text": "", "claim_ids": []},
        "keywords": [],
        "sections": sections,
        "appendices": appendices,
        "citation_registry": [],
        "claim_provenance": [],
        "open_items": deepcopy(author_input.get("unknown_items") or []),
        "review_items": deepcopy(author_input.get("review_items") or []),
        "authoring_constraints": deepcopy(author_input.get("authoring_constraints") or {}),
        "source_manifest": {
            "source_bundle_schema_version": _text(source_bundle.get("schema_version")),
            "author_input_path": _text(source_bundle.get("author_input_path")),
            "selected_direction_id": _text(source_bundle.get("selected_direction_id")),
        },
        "authoring_blueprint": {},
        "contract_repair_audit": [],
    }


__all__ = [
    "AUTHORING_LANGUAGE",
    "AUTHOR_INPUT_SCHEMA",
    "AUTHOR_PREPARATION_SCHEMA_VERSION",
    "AUTHOR_PREPARATION_SCHEMA",
    "AUTHOR_SOURCE_BUNDLE_SCHEMA",
    "AUTHOR_SOURCE_BUNDLE_SCHEMA_VERSION",
    "RESEARCH_PLAN_AUTHOR_INPUT_SCHEMA_VERSION",
    "RESEARCH_PLAN_DOCUMENT_SCHEMA",
    "RESEARCH_PLAN_DOCUMENT_SCHEMA_VERSION",
    "build_research_plan_document_skeleton",
    "validate_author_input",
    "validate_author_preparation",
    "validate_research_plan_document",
]
