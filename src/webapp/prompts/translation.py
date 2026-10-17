"""Distilled source-grounded paper-translation prompts."""

from __future__ import annotations

from dataclasses import replace

from ..feature_contracts import TranslationOutput
from .common import COMMON_GUARDRAILS, SKILL_SOURCE_HASHES, PromptSpec


def _source_hash(skill_id: str) -> str:
    return SKILL_SOURCE_HASHES[skill_id]


TRANSLATION_TEXT_PRESERVING = PromptSpec(
    prompt_id="translation-text-preserving",
    prompt_version="1.0.0",
    skill_ids=("nature-reader", "nature-polishing"),
    source_refs=("nature-reader/SKILL.md", "nature-polishing/SKILL.md"),
    source_hashes=tuple((skill_id, _source_hash(skill_id)) for skill_id in ("nature-reader", "nature-polishing")),
    system_prompt=(
        "Translate the supplied paper blocks while preserving source-map IDs, terminology, figures, tables, equations, "
        "citations, and page boundaries. Return block-level translations and unresolved parsing or terminology items."
    ),
    output_schema={
        "type": "object",
        "additionalProperties": False,
        "required": ["schema_version", "pages", "terminology_ledger", "unresolved_items"],
        "properties": {
            "schema_version": {"type": "string", "minLength": 1},
            "pages": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["page_number", "source_blocks", "translated_blocks", "parser_backend", "parser_version", "ocr_used", "figures", "tables", "equations", "review_status", "unresolved_items"],
                    "properties": {
                        "page_number": {"type": "integer", "minimum": 1},
                        "source_blocks": {"type": "array", "items": {"type": "object"}},
                        "translated_blocks": {"type": "array", "items": {"type": "object"}},
                        "parser_backend": {"type": "string"},
                        "parser_version": {"type": ["string", "null"]},
                        "ocr_used": {"type": "boolean"},
                        "figures": {"type": "array", "items": {"type": "string"}},
                        "tables": {"type": "array", "items": {"type": "string"}},
                        "equations": {"type": "array", "items": {"type": "string"}},
                        "review_status": {"type": "string"},
                        "unresolved_items": {"type": "array", "items": {"type": "string"}},
                    },
                },
            },
            "terminology_ledger": {"type": "array", "items": {"type": "object", "additionalProperties": False}},
            "unresolved_items": {"type": "array", "items": {"type": "object", "additionalProperties": False}},
        },
    },
    guardrails=COMMON_GUARDRAILS
    + (
        "Do not drop or renumber source blocks, equations, figures, tables, or citation anchors.",
        "Preserve technical terms consistently through the terminology ledger.",
        "Mark OCR or equation uncertainty with a page and block locator.",
    ),
    default_text_role="translation",
)

TRANSLATION_TEXT_V1 = replace(TRANSLATION_TEXT_PRESERVING, output_schema={
    "type": "object", "additionalProperties": False,
    "required": ["schema_version", "pages", "terminology_ledger", "unresolved_items"],
    "properties": {
        "schema_version": {"type": "string", "minLength": 1},
        "pages": {"type": "array", "items": {"type": "object"}},
        "terminology_ledger": {"type": "array", "items": {"type": "object"}},
        "unresolved_items": {"type": "array", "items": {"type": "object"}},
    },
})
TRANSLATION_TEXT_PRESERVING = replace(
    TRANSLATION_TEXT_PRESERVING, prompt_version="2.0.0", output_schema=TranslationOutput.model_json_schema(),
)


TRANSLATION_IMAGE_PAGE = PromptSpec(
    prompt_id="translation-image-page",
    prompt_version="1.0.0",
    skill_ids=("nature-paper-trans",),
    source_refs=("nature-paper-trans/SKILL.md",),
    source_hashes=(("nature-paper-trans", _source_hash("nature-paper-trans")),),
    system_prompt=(
        "Prepare one page-level Chinese translation image brief from the supplied source page. Preserve page size, "
        "orientation, figures, equations, and layout intent; do not introduce unsupported scientific content."
    ),
    output_schema={
        "type": "object",
        "additionalProperties": False,
        "required": ["schema_version", "image_prompt", "page_provenance", "unresolved_items"],
        "properties": {
            "schema_version": {"type": "string", "minLength": 1},
            "image_prompt": {"type": "string", "minLength": 1},
            "page_provenance": {"type": "object"},
            "unresolved_items": {"type": "array", "items": {"type": "string"}},
        },
    },
    guardrails=COMMON_GUARDRAILS
    + (
        "This route creates a page image and does not create an editable document.",
        "Record the original page number, source hash, image model, and one generation attempt.",
    ),
    default_text_role="translation",
    image_model_role="academic_figure",
)
