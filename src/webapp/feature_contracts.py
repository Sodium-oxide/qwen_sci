"""Strict nested model-output contracts used before publishing candidates."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class PolishRevision(Contract):
    segment_id: str = Field(min_length=1)
    original: str
    revised: str = Field(min_length=1)
    rationale: str
    risk: Literal["low", "medium", "high"]
    preserved_entities: list[str]
    unresolved_items: list[str]


class PolishOutput(Contract):
    schema_version: Literal["polish_revision_v1"]
    segments: list[PolishRevision]
    global_notes: list[str]


class TranslatedBlock(Contract):
    block_id: str = Field(min_length=1)
    text: str = Field(min_length=1)


class TranslationItem(Contract):
    page_number: int = Field(ge=1)
    translated_blocks: list[TranslatedBlock]
    unresolved_items: list[str]


class TerminologyEntry(Contract):
    source: str = Field(min_length=1)
    target: str = Field(min_length=1)


class TranslationOutput(Contract):
    schema_version: Literal["translation_page_v1"]
    pages: list[TranslationItem]
    terminology_ledger: list[TerminologyEntry]
    unresolved_items: list[str]
