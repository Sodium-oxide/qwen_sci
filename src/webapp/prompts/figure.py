"""Distilled scientific-figure prompts and Qwen image-model routing."""

from __future__ import annotations

from dataclasses import replace

from .common import COMMON_GUARDRAILS, SKILL_SOURCE_HASHES, PromptSpec
from ..figure_contracts import FigureSpec


def _source_hash(skill_id: str) -> str:
    return SKILL_SOURCE_HASHES[skill_id]


FIGURE_PYTHON_V1 = PromptSpec(
    prompt_id="figure-python-default",
    prompt_version="1.0.0",
    skill_ids=("nature-figure", "nature-statistics"),
    source_refs=("nature-figure/SKILL.md", "nature-statistics/SKILL.md"),
    source_hashes=tuple((skill_id, _source_hash(skill_id)) for skill_id in ("nature-figure", "nature-statistics")),
    system_prompt=(
        "Design one auditable scientific figure from the supplied data contract. Start from the figure claim, "
        "choose one evidence archetype, keep uncertainty visible, and return executable Python source metadata."
    ),
    output_schema={
        "type": "object",
        "additionalProperties": False,
        "required": ["schema_version", "figure_contract", "source_code", "unresolved_items"],
        "properties": {
            "schema_version": {"type": "string", "minLength": 1},
            "figure_contract": {"type": "object"},
            "source_code": {"type": "string", "minLength": 1},
            "unresolved_items": {"type": "array", "items": {"type": "string"}},
        },
    },
    guardrails=COMMON_GUARDRAILS
    + (
        "Use only variables and values present in the input manifest.",
        "Do not generate quantitative values from an image-generation model.",
        "A missing panel-alignment or collision audit is NOT_AUDITABLE, not a pass.",
    ),
    default_text_role="figure",
    image_model_role="academic_figure",
)


FIGURE_PYTHON_V101 = replace(FIGURE_PYTHON_V1, prompt_version="1.0.1", image_model_role=None)

FIGURE_PYTHON_DEFAULT = replace(
    FIGURE_PYTHON_V101, prompt_version="2.0.0",
    system_prompt=(
        "Plan one scientific figure from a verified table summary, user-supplied variable mapping, and figure claim. "
        "Return a declarative figure_spec_v1 object. Select a supported chart type, explicit axis labels, "
        "a colorblind-safe palette, and journal-sized dimensions. Keep the supplied variable mapping unchanged. "
        "Do not infer results from column types, create statistics, or return source code. "
        "List missing units, uncertainty definitions, or unsupported claims in unresolved_items."
    ),
    output_schema=FigureSpec.model_json_schema(),
)


FIGURE_AI_SCHEMATIC = PromptSpec(
    prompt_id="figure-ai-schematic",
    prompt_version="1.0.0",
    skill_ids=("nature-figure",),
    source_refs=("nature-figure/SKILL.md",),
    source_hashes=(("nature-figure", _source_hash("nature-figure")),),
    system_prompt=(
        "Prepare a draft scientific schematic or graphical abstract brief for the configured Qwen image model. "
        "Keep the mechanism and labels grounded in supplied evidence and separate the draft from a quantitative plot."
    ),
    output_schema={
        "type": "object",
        "additionalProperties": False,
        "required": ["schema_version", "image_prompt", "provenance", "unresolved_items"],
        "properties": {
            "schema_version": {"type": "string", "minLength": 1},
            "image_prompt": {"type": "string", "minLength": 1},
            "provenance": {"type": "object"},
            "unresolved_items": {"type": "array", "items": {"type": "string"}},
        },
    },
    guardrails=COMMON_GUARDRAILS
    + (
        "The image is a draft schematic, not a source of experimental values.",
        "Record the image model, prompt hash, input hashes, and human review status.",
    ),
    default_text_role="figure",
    image_model_role="academic_figure",
)
