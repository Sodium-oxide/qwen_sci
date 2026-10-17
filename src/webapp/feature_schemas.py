"""Strict request schemas for figure, polishing, and paper-translation Jobs."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, field_validator, model_validator

from .jobs.models import JobRecord
from .jobs.schemas import JobView
from src.llm.model_policy import TextModelName
from .schemas import StrictModel
from .figure_contracts import FigureStyle


class FigureStatisticalComparison(StrictModel):
    method: Literal["welch_ttest"]
    independent_units: Literal[True]


class FigureJobCreate(StrictModel):
    project_id: str | None = Field(default=None, max_length=256)
    run_id: str | None = Field(default=None, max_length=128)
    input_file_ids: list[str] = Field(min_length=1, max_length=16)
    figure_claim: str = Field(min_length=8, max_length=2_000)
    audience: Literal["manuscript", "presentation", "review", "exploration"] = "manuscript"
    chart_type: str | None = Field(default=None, max_length=128)
    planning_mode: Literal["auto", "model", "explicit"] = "auto"
    backend: Literal["python", "r"] = "python"
    variable_mapping: dict[str, str] = Field(min_length=1, max_length=32)
    figure_style: FigureStyle | None = None
    statistical_comparison: FigureStatisticalComparison | None = None
    target_journal: str = Field(default="generic", max_length=128)
    output_formats: list[Literal["png", "svg", "pdf", "source", "qa"]] = Field(
        default_factory=lambda: ["png", "pdf", "source", "qa"], min_length=1, max_length=5
    )
    use_ai_schematic: bool = False
    image_generation_authorized: bool = False
    network_authorized: bool = False
    model_name: TextModelName | None = None
    prompt_profile: Literal["figure-python-default", "figure-ai-schematic"] = "figure-python-default"
    idempotency_key: str | None = Field(default=None, max_length=256)

    @model_validator(mode="after")
    def validate_figure_route(self) -> "FigureJobCreate":
        if self.backend == "r":
            raise ValueError("R figure execution is not enabled in the first backend release.")
        if self.use_ai_schematic and self.prompt_profile != "figure-ai-schematic":
            raise ValueError("AI schematics require prompt_profile='figure-ai-schematic'.")
        if self.prompt_profile == "figure-ai-schematic" and not self.use_ai_schematic:
            raise ValueError("figure-ai-schematic requires use_ai_schematic=true.")
        if self.use_ai_schematic and not self.image_generation_authorized:
            raise ValueError("AI schematic generation requires explicit image_generation_authorized=true.")
        if self.use_ai_schematic and self.figure_style is not None:
            raise ValueError("figure_style only applies to data plots.")
        if len(set(self.input_file_ids)) != len(self.input_file_ids):
            raise ValueError("input_file_ids must not contain duplicates.")
        if not self.use_ai_schematic and len(self.input_file_ids) != 1:
            raise ValueError("Data plots require exactly one tabular input.")
        if not self.use_ai_schematic and set(self.variable_mapping) - {"x", "y", "group", "error"}:
            raise ValueError("Data plots accept x, y, group, and error variable mappings.")
        return self


class PolishJobCreate(StrictModel):
    project_id: str | None = Field(default=None, max_length=256)
    run_id: str | None = Field(default=None, max_length=128)
    input_file_id: str | None = Field(default=None, max_length=128)
    text: str | None = Field(default=None, max_length=200_000)
    source_language: Literal["zh-CN", "en", "auto"] = "auto"
    target_language: Literal["zh-CN", "en"] = "en"
    paper_type: Literal["research", "methods", "review", "hypothesis", "algorithmic", "proposal"] = "research"
    section: list[Literal["abstract", "introduction", "results", "discussion", "conclusion", "methods", "title"]] = Field(
        default_factory=list, max_length=7
    )
    target_journal: str = Field(default="generic", max_length=128)
    style_profile: Literal["clear", "concise", "formal", "native_academic"] = "clear"
    preserve_terms: list[str] = Field(default_factory=list, max_length=200)
    citation_style: str | None = Field(default=None, max_length=128)
    model_name: TextModelName | None = None
    prompt_profile: Literal["polish-generic", "polish-nature"] = "polish-generic"
    output_formats: list[Literal["markdown", "json", "docx", "pdf"]] = Field(default_factory=lambda: ["markdown", "json"], min_length=1, max_length=4)
    idempotency_key: str | None = Field(default=None, max_length=256)

    @field_validator("preserve_terms")
    @classmethod
    def validate_preserved_terms(cls, terms: list[str]) -> list[str]:
        if any(not term.strip() or len(term) > 256 for term in terms):
            raise ValueError("preserve_terms must contain nonblank terms up to 256 characters.")
        return list(dict.fromkeys(terms))

    @model_validator(mode="after")
    def require_one_input(self) -> "PolishJobCreate":
        has_file = bool(self.input_file_id and self.input_file_id.strip())
        has_text = bool(self.text and self.text.strip())
        if has_file == has_text:
            raise ValueError("Provide exactly one of input_file_id or text.")
        return self


class TranslationJobCreate(StrictModel):
    project_id: str | None = Field(default=None, max_length=256)
    run_id: str | None = Field(default=None, max_length=128)
    input_file_id: str = Field(min_length=8, max_length=128)
    source_language: Literal["en", "zh-CN", "auto"] = "auto"
    target_language: Literal["zh-CN", "en"] = "zh-CN"
    mode: Literal["text_preserving", "image_page_translation"] = "text_preserving"
    page_start: int | None = Field(default=None, ge=1, le=10_000)
    page_end: int | None = Field(default=None, ge=1, le=10_000)
    terminology_overrides: dict[str, str] = Field(default_factory=dict, max_length=500)
    target_journal: str = Field(default="generic", max_length=128)
    output_formats: list[Literal["markdown", "json", "docx", "pdf"]] = Field(
        default_factory=lambda: ["markdown", "json"], min_length=1, max_length=4
    )
    image_generation_authorized: bool = False
    model_name: TextModelName | None = None
    prompt_profile: Literal["translation-text-preserving", "translation-image-page"] = "translation-text-preserving"
    idempotency_key: str | None = Field(default=None, max_length=256)

    @field_validator("terminology_overrides")
    @classmethod
    def validate_terminology(cls, terms: dict[str, str]) -> dict[str, str]:
        if any(not source.strip() or not target.strip() or len(source) > 256 or len(target) > 512 for source, target in terms.items()):
            raise ValueError("Terminology mappings require nonblank source and target terms within the length limits.")
        return terms

    @model_validator(mode="after")
    def validate_page_translation(self) -> "TranslationJobCreate":
        if self.page_start is not None and self.page_end is not None and self.page_start > self.page_end:
            raise ValueError("page_start must not exceed page_end.")
        if self.mode == "image_page_translation":
            if self.prompt_profile != "translation-image-page":
                raise ValueError("Image page translation requires translation-image-page prompt profile.")
            if not self.image_generation_authorized:
                raise ValueError("Image page translation requires explicit image_generation_authorized=true.")
        elif self.prompt_profile != "translation-text-preserving":
            raise ValueError("text_preserving translation requires translation-text-preserving prompt profile.")
        return self


class FeatureActionRequest(StrictModel):
    type: Literal[
        "cancel",
        "retry",
        "accept",
        "reject",
        "accept_segments",
        "reject_segments",
        "accept_pages",
        "reject_pages",
        "regenerate_segments",
        "regenerate_pages",
    ]
    notes: str = Field(default="", max_length=2_000)
    segment_ids: list[str] = Field(default_factory=list, max_length=2_000)
    page_numbers: list[int] = Field(default_factory=list, max_length=2_000)
    expected_attempt: int | None = Field(default=None, ge=1)
    expected_review_version: int | None = Field(default=None, ge=0)
    figure_style: FigureStyle | None = None


class FeatureExportRequest(StrictModel):
    format: Literal["markdown", "json", "docx", "pdf"] = "markdown"
    expected_review_version: int | None = Field(default=None, ge=1)


def job_view(record: JobRecord) -> JobView:
    return JobView.from_record(record)
