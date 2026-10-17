"""Distilled academic-polishing prompts."""

from __future__ import annotations

from dataclasses import replace

from ..feature_contracts import PolishOutput
from .common import COMMON_GUARDRAILS, SKILL_SOURCE_HASHES, PromptSpec


def _source_hash(skill_id: str) -> str:
    return SKILL_SOURCE_HASHES[skill_id]


POLISH_GENERIC = PromptSpec(
    prompt_id="polish-generic",
    prompt_version="1.0.0",
    skill_ids=("nature-polishing", "academic-humanizer"),
    source_refs=("nature-polishing/SKILL.md", "academic-humanizer/SKILL.md"),
    source_hashes=tuple((skill_id, _source_hash(skill_id)) for skill_id in ("nature-polishing", "academic-humanizer")),
    system_prompt=(
        "Polish supplied academic prose without changing its factual content. Diagnose the paragraph job first, "
        "then improve clarity, evidence-bound wording, terminology, and sentence rhythm."
    ),
    output_schema={
        "type": "object",
        "additionalProperties": False,
        "required": ["schema_version", "segments", "global_notes"],
        "properties": {
            "schema_version": {"type": "string", "minLength": 1},
            "segments": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["segment_id", "original", "revised", "rationale", "risk", "preserved_entities", "unresolved_items"],
                    "properties": {
                        "segment_id": {"type": "string", "minLength": 1},
                        "original": {"type": "string"},
                        "revised": {"type": "string", "minLength": 1},
                        "rationale": {"type": "string"},
                        "risk": {"type": "string", "enum": ["low", "medium", "high"]},
                        "preserved_entities": {"type": "array", "items": {"type": "string"}},
                        "unresolved_items": {"type": "array", "items": {"type": "string"}},
                    },
                },
            },
            "global_notes": {"type": "array", "items": {"type": "string"}},
        },
    },
    guardrails=COMMON_GUARDRAILS
    + (
        "Never alter a number, unit, equation, citation key, DOI, variable name, or named method.",
        "Keep evidence-tied hedging when the supplied evidence is uncertain.",
        "Put the core claim first and remove defensive boilerplate that adds no evidence or boundary.",
        "Mark missing author facts as AUTHOR_INPUT_NEEDED instead of inventing them.",
    ),
    default_text_role="polish",
)

POLISH_V1 = replace(POLISH_GENERIC, output_schema={
    "type": "object", "additionalProperties": False,
    "required": ["schema_version", "segments", "global_notes"],
    "properties": {
        "schema_version": {"type": "string", "minLength": 1},
        "segments": {"type": "array", "items": {"type": "object"}},
        "global_notes": {"type": "array", "items": {"type": "string"}},
    },
})
POLISH_GENERIC = replace(POLISH_GENERIC, prompt_version="2.0.0", output_schema=PolishOutput.model_json_schema())
POLISH_NATURE = replace(
    POLISH_GENERIC, prompt_id="polish-nature",
    system_prompt=POLISH_GENERIC.system_prompt + " Use concise Nature-family academic prose, distinguish observation from interpretation, and retain evidence-bound hedging.",
)
