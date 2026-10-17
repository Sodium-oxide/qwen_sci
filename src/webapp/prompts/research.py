"""Distilled research prompts sourced from the existing scientific workflow skills."""

from __future__ import annotations

from .common import COMMON_GUARDRAILS, SKILL_SOURCE_HASHES, PromptSpec


def _source_hash(skill_id: str) -> str:
    return SKILL_SOURCE_HASHES[skill_id]


RESEARCH_DEFAULT = PromptSpec(
    prompt_id="research-default",
    prompt_version="1.0.0",
    skill_ids=("nature-writing", "nature-data", "nature-statistics"),
    source_refs=(
        "nature-writing/SKILL.md",
        "nature-data/SKILL.md",
        "nature-statistics/SKILL.md",
    ),
    source_hashes=tuple((skill_id, _source_hash(skill_id)) for skill_id in ("nature-writing", "nature-data", "nature-statistics")),
    system_prompt=(
        "Act as the structured research workflow assistant. Build claims from supplied evidence, "
        "keep the research question and evidence ledger aligned, and leave missing author facts unresolved."
    ),
    output_schema={
        "type": "object",
        "additionalProperties": False,
        "required": ["schema_version", "claims", "unresolved_items"],
        "properties": {
            "schema_version": {"type": "string", "minLength": 1},
            "claims": {"type": "array", "items": {"type": "object"}},
            "unresolved_items": {"type": "array", "items": {"type": "string"}},
        },
    },
    guardrails=COMMON_GUARDRAILS,
    default_text_role="research",
)


RESEARCH_LIGHT = PromptSpec(
    prompt_id="research-light",
    prompt_version="1.0.0",
    skill_ids=("nature-writing", "nature-data"),
    source_refs=("nature-writing/SKILL.md", "nature-data/SKILL.md"),
    source_hashes=tuple((skill_id, _source_hash(skill_id)) for skill_id in ("nature-writing", "nature-data")),
    system_prompt=(
        "Act as a bounded research survey assistant. Produce an evidence map and research gap ledger; "
        "do not silently expand a light survey into experiment design or a complete research plan."
    ),
    output_schema={
        "type": "object",
        "additionalProperties": False,
        "required": ["schema_version", "evidence_ledger", "gap_ledger", "unresolved_items"],
        "properties": {
            "schema_version": {"type": "string", "minLength": 1},
            "evidence_ledger": {"type": "array", "items": {"type": "object"}},
            "gap_ledger": {"type": "array", "items": {"type": "object"}},
            "unresolved_items": {"type": "array", "items": {"type": "string"}},
        },
    },
    guardrails=COMMON_GUARDRAILS,
    default_text_role="research",
)
