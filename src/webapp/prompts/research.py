"""Distilled research prompts sourced from the existing scientific workflow skills."""

from __future__ import annotations

from dataclasses import replace

from .common import COMMON_GUARDRAILS, SKILL_SOURCE_HASHES, PromptSpec


def _source_hash(skill_id: str) -> str:
    return SKILL_SOURCE_HASHES[skill_id]


RESEARCH_GUARDRAILS = (
    "Do not fabricate literature-reported data, measured numerical values, observed experimental results, "
    "reported sample sizes, citations, DOIs, or sources. Explicitly proposed design values and planned sample sizes "
    "are allowed when labeled as proposals and accompanied by rationale and validation criteria.",
    "Separate literature facts, user-supplied premises, proposed design decisions, hypotheses, predictions, and "
    "observed results. Mark missing source facts as unresolved_items; continue with explicit testable choices "
    "where the task calls for design or prediction.",
    "The original user task defines the objective and explicit constraints. Evidence limits and model-proposed "
    "scopes do not remove requested deliverables or become new user prohibitions.",
    *COMMON_GUARDRAILS[2:],
)


RESEARCH_DEFAULT = PromptSpec(
    prompt_id="research-default",
    prompt_version="1.1.0",
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
    guardrails=RESEARCH_GUARDRAILS,
    inherit_common_guardrails=False,
    default_text_role="research",
)


RESEARCH_LIGHT = PromptSpec(
    prompt_id="research-light",
    prompt_version="1.1.0",
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
    guardrails=RESEARCH_GUARDRAILS,
    inherit_common_guardrails=False,
    default_text_role="research",
)


RESEARCH_DEFAULT_V1 = replace(RESEARCH_DEFAULT, prompt_version="1.0.0", guardrails=COMMON_GUARDRAILS, inherit_common_guardrails=True)
RESEARCH_LIGHT_V1 = replace(RESEARCH_LIGHT, prompt_version="1.0.0", guardrails=COMMON_GUARDRAILS, inherit_common_guardrails=True)
