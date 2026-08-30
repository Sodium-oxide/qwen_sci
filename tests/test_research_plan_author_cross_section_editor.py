from __future__ import annotations

from copy import deepcopy
import json

import pytest

from src.agents.research_plan_author.cross_section_editor import (
    CROSS_SECTION_EDITOR_SCHEMA_VERSION,
    build_cross_section_editor_prompt,
    edit_cross_section_document,
)
from src.agents.research_plan_author.section_cache import SectionCompositionCache, section_cache_identity


def _document() -> dict:
    return {
        "schema_version": "research_plan_document_v1",
        "document_status": "PREPARATION_ONLY",
        "language": "en",
        "source_design_id": "editor-test",
        "document_metadata": {
            "title": "A Conditional Proposal",
            "discipline_ids": ["26"],
            "study_type": "theory",
        },
        "abstract": {"text": "", "claim_ids": []},
        "keywords": [],
        "sections": [
            {
                "section_id": "forward_derivation_and_counterexamples",
                "title": "Forward Derivation",
                "applicability": "required",
                "blocks": [
                    {
                        "block_id": "narrative",
                        "kind": "paragraph",
                        "heading": "Dependency",
                        "text": "The unresolved definition needs human confirmation before the argument can proceed.",
                        "claim_ids": [],
                    },
                    {
                        "block_id": "relation",
                        "kind": "equation",
                        "text": "F = G",
                        "claim_ids": [],
                    },
                    {
                        "block_id": "matrix",
                        "kind": "table",
                        "text": "Condition | Action\nBoundary | Revise",
                        "claim_ids": [],
                    },
                ],
            },
        ],
        "appendices": [
            {
                "section_id": "references",
                "title": "References",
                "applicability": "required",
                "blocks": [
                    {
                        "block_id": "bibliography",
                        "kind": "paragraph",
                        "text": "A. Author, A Source.",
                        "claim_ids": [],
                    },
                ],
            },
        ],
        "citation_registry": [],
        "claim_provenance": [],
        "open_items": [{"source_item_id": "unknown-definition"}],
        "review_items": [{"source_item_id": "review-release"}],
        "authoring_constraints": {},
        "source_manifest": {},
        "authoring_blueprint": {},
        "contract_repair_audit": [],
    }


def _ledger() -> dict:
    return {
        "definition_ledger": {
            "owner_section_id": "definitions_and_propositions",
            "entries": [{"entry_id": "definition:D1"}],
        },
        "decision_ledger": {
            "owner_section_id": "risk_limitations_and_review",
            "entries": [{"entry_id": "review:review-release"}],
        },
        "section_roles": [],
        "argument_graph": [],
    }


def _editor_response(response: dict):
    def call(prompt: str, *, response_format: object) -> dict:
        assert response_format == {"type": "json_object"}
        payload = json.loads(prompt.rsplit("INPUT_JSON:\n", 1)[1])
        assert payload["operation"] == "research_plan_cross_section_edit"
        return response

    return call


def _no_semantic_errors(_document: object) -> list[str]:
    return []


def test_editor_applies_only_existing_editable_prose_and_preserves_provenance() -> None:
    document = _document()
    original = deepcopy(document)

    edited, audit = edit_cross_section_document(
        document,
        argument_ledger=_ledger(),
        llm_call=_editor_response(
            {
                "schema_version": CROSS_SECTION_EDITOR_SCHEMA_VERSION,
                "edits": [
                    {
                        "section_id": "forward_derivation_and_counterexamples",
                        "block_id": "narrative",
                        "text": "The derivation therefore remains conditional on the definition ledger's owner decision.",
                    },
                ],
            },
        ),
        validate_candidate=_no_semantic_errors,
    )

    assert audit["edit_status"] == "APPLIED"
    assert audit["edit_count"] == 1
    assert edited["sections"][0]["blocks"][0]["text"] == (
        "The derivation therefore remains conditional on the definition ledger's owner decision."
    )
    assert edited["sections"][0]["blocks"][1:] == original["sections"][0]["blocks"][1:]
    assert edited["claim_provenance"] == original["claim_provenance"]
    assert edited["open_items"] == original["open_items"]
    assert edited["review_items"] == original["review_items"]
    assert edited["citation_registry"] == original["citation_registry"]
    assert document == original


def test_editor_no_changes_is_a_nonblocking_noop() -> None:
    document = _document()

    edited, audit = edit_cross_section_document(
        document,
        argument_ledger=_ledger(),
        llm_call=_editor_response({"schema_version": CROSS_SECTION_EDITOR_SCHEMA_VERSION, "edits": []}),
        validate_candidate=_no_semantic_errors,
    )

    assert audit["edit_status"] == "NO_CHANGES"
    assert audit["edit_count"] == 0
    assert edited == document


@pytest.mark.parametrize(
    ("block_id", "text"),
    [
        ("relation", "F = H"),
        ("matrix", "Condition | Action\nBoundary | Continue"),
        ("bibliography", "A. Different Author, A Different Source."),
        ("narrative", "The experiment demonstrated a measured effect."),
        ("narrative", "See anchor:private-survey-record for support."),
    ],
)
def test_editor_rejects_unsafe_or_immutable_targets(block_id: str, text: str) -> None:
    document = _document()

    edited, audit = edit_cross_section_document(
        document,
        argument_ledger=_ledger(),
        llm_call=_editor_response(
            {
                "schema_version": CROSS_SECTION_EDITOR_SCHEMA_VERSION,
                "edits": [
                    {
                        "section_id": "forward_derivation_and_counterexamples",
                        "block_id": block_id,
                        "text": text,
                    },
                ],
            },
        ),
        validate_candidate=_no_semantic_errors,
    )

    assert audit["edit_status"] == "SKIPPED_INVALID_EDITOR_OUTPUT"
    assert audit["validation_errors"]
    assert edited == document


def test_editor_rolls_back_when_the_callers_full_semantic_validation_rejects_an_edit() -> None:
    document = _document()

    edited, audit = edit_cross_section_document(
        document,
        argument_ledger=_ledger(),
        llm_call=_editor_response(
            {
                "schema_version": CROSS_SECTION_EDITOR_SCHEMA_VERSION,
                "edits": [
                    {
                        "section_id": "forward_derivation_and_counterexamples",
                        "block_id": "narrative",
                        "text": "The planned protocol specifies a sample size.",
                    },
                ],
            },
        ),
        validate_candidate=lambda candidate: [
            "mathematics/theory sampling and power must remain not_applicable"
        ]
        if "sample size" in candidate["sections"][0]["blocks"][0]["text"].casefold()
        else [],
    )

    assert audit["edit_status"] == "SKIPPED_INVALID_EDITOR_OUTPUT"
    assert audit["validation_errors"] == [
        "mathematics/theory sampling and power must remain not_applicable"
    ]
    assert edited == document


def test_editor_prompt_excludes_definition_equation_table_and_references_from_editable_targets() -> None:
    payload = json.loads(
        build_cross_section_editor_prompt(_document(), argument_ledger=_ledger()).rsplit("INPUT_JSON:\n", 1)[1]
    )
    blocks = {
        (section["section_id"], block["block_id"]): block["editable"]
        for section in payload["sections"]
        for block in section["blocks"]
    }

    assert blocks[("forward_derivation_and_counterexamples", "narrative")] is True
    assert blocks[("forward_derivation_and_counterexamples", "relation")] is False
    assert blocks[("forward_derivation_and_counterexamples", "matrix")] is False
    assert blocks[("references", "bibliography")] is False


def test_section_cache_identity_changes_when_the_argument_ledger_changes(tmp_path) -> None:
    cache = SectionCompositionCache({"root": tmp_path / "section-cache"})
    base = {
        "preparation": {"source_bundle": {"author_context": {"source_design_id": "editor-test"}}},
        "blueprint": {"global_constraints": {}, "argument_ledger": _ledger()},
        "route": {"section_id": "forward_derivation_and_counterexamples"},
        "blueprint_section": {"section_id": "forward_derivation_and_counterexamples"},
        "source_registry": {},
    }
    original_identity = section_cache_identity(**base)
    cache.write(original_identity, {"section_id": "forward_derivation_and_counterexamples"})

    revised = deepcopy(base)
    revised["blueprint"]["argument_ledger"]["definition_ledger"]["owner_section_id"] = "formal_problem_and_hypotheses"
    revised_identity = section_cache_identity(**revised)

    assert original_identity["composer_revision"] == "4"
    assert original_identity["blueprint_argument_ledger"] != revised_identity["blueprint_argument_ledger"]
    assert cache.read(revised_identity) is None
