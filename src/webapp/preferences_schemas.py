"""Strict workspace preference schemas."""

from __future__ import annotations

from typing import Literal

from pydantic import Field
from src.llm.model_policy import TextModelName

from .schemas import StrictModel


class ResearchPreferences(StrictModel):
    version: int = Field(default=1, ge=1)
    language: Literal["zh-CN", "en"] = "zh-CN"
    disciplines: list[str] = Field(default_factory=list, max_length=20)
    target_journal: str = Field(default="", max_length=128)
    citation_style: str = Field(default="numeric", max_length=128)
    model_profile: Literal["fast", "balanced", "quality"] = "balanced"
    default_text_model: TextModelName | None = None
    default_research_depth: Literal["light", "full"] = "full"
    default_output_format: Literal["markdown", "docx", "pdf"] = "markdown"
    network_access: Literal["never", "ask", "allowed"] = "ask"
    remote_perception: bool = False
    privacy_mode: Literal["controlled-materials", "local-only"] = "controlled-materials"


class PreferenceEnvelope(StrictModel):
    scope: Literal["workspace"] = "workspace"
    auth_required: bool = False
    preferences: ResearchPreferences

