"""Allow-listed prompt and model selection for web Jobs."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from typing import Any

from src.llm.provider_registry import ModelSpec, require_model_capabilities, resolve_role_model
from src.llm.model_policy import TEXT_MODEL_CHOICES

from .common import PromptSpec
from .figure import FIGURE_AI_SCHEMATIC, FIGURE_PYTHON_DEFAULT, FIGURE_PYTHON_V1, FIGURE_PYTHON_V101
from .polish import POLISH_GENERIC, POLISH_NATURE, POLISH_V1
from .research import RESEARCH_DEFAULT, RESEARCH_DEFAULT_V1, RESEARCH_LIGHT, RESEARCH_LIGHT_V1
from .translation import TRANSLATION_IMAGE_PAGE, TRANSLATION_TEXT_PRESERVING, TRANSLATION_TEXT_V1


IMAGE_MODEL_ROLE = "academic_figure"


class PromptRegistry:
    """Resolve only server-registered prompt profiles and Qwen model choices."""

    def __init__(self, specs: Mapping[str, PromptSpec] | None = None) -> None:
        self._specs = dict(specs or {})
        self._versions = {(spec.prompt_id, spec.prompt_version): spec for spec in self._specs.values()}

    def register_version(self, spec: PromptSpec) -> None:
        existing = self._versions.get((spec.prompt_id, spec.prompt_version))
        if existing is not None and existing.prompt_hash != spec.prompt_hash:
            raise ValueError("A prompt version cannot be replaced with different content.")
        self._versions[(spec.prompt_id, spec.prompt_version)] = spec

    def register(self, spec: PromptSpec, *, replace_existing: bool = False) -> None:
        if spec.prompt_id in self._specs and not replace_existing:
            raise ValueError(f"Prompt profile already exists: {spec.prompt_id}")
        self.register_version(spec)
        self._specs[spec.prompt_id] = spec

    def get(self, prompt_id: str, *, prompt_version: str | None = None, prompt_hash: str | None = None) -> PromptSpec:
        try:
            spec = self._versions[(prompt_id, prompt_version)] if prompt_version else self._specs[prompt_id]
        except KeyError as exc:
            raise ValueError(f"Unknown prompt profile or version: {prompt_id}") from exc
        if prompt_hash is not None and spec.prompt_hash != prompt_hash:
            raise ValueError("The registered prompt no longer matches the frozen prompt hash.")
        return spec

    def resolve(
        self,
        *,
        job_kind: str,
        profile: str,
        axes: Mapping[str, str] | None = None,
        prompt_version: str | None = None,
        prompt_hash: str | None = None,
    ) -> PromptSpec:
        spec = self.get(profile, prompt_version=prompt_version, prompt_hash=prompt_hash)
        expected_kinds = {
            "research-default": {"science"},
            "research-light": {"science"},
            "figure-python-default": {"figure"},
            "figure-ai-schematic": {"figure"},
            "polish-generic": {"polish"},
            "polish-nature": {"polish"},
            "translation-text-preserving": {"translation"},
            "translation-image-page": {"translation"},
        }
        if job_kind not in expected_kinds.get(profile, set()):
            raise ValueError(f"Prompt profile '{profile}' cannot be used for Job kind '{job_kind}'.")
        if axes:
            unknown_axes = set(axes) - {"paper_type", "section", "language", "journal", "backend", "mode"}
            if unknown_axes:
                raise ValueError(f"Unsupported prompt axes: {', '.join(sorted(unknown_axes))}")
        return spec

    def build_messages(
        self,
        *,
        job_kind: str,
        profile: str,
        input_manifest: Mapping[str, object],
        task_context: Mapping[str, object],
        axes: Mapping[str, str] | None = None,
    ) -> list[dict[str, object]]:
        return self.resolve(job_kind=job_kind, profile=profile, axes=axes).build_messages(
            input_manifest=input_manifest,
            task_context=task_context,
        )

    @property
    def profiles(self) -> tuple[str, ...]:
        return tuple(sorted(self._specs))


def build_default_prompt_registry() -> PromptRegistry:
    registry = PromptRegistry(
        {
            spec.prompt_id: spec
            for spec in (
                RESEARCH_DEFAULT,
                RESEARCH_LIGHT,
                FIGURE_PYTHON_DEFAULT,
                FIGURE_AI_SCHEMATIC,
                POLISH_GENERIC,
                POLISH_NATURE,
                TRANSLATION_TEXT_PRESERVING,
                TRANSLATION_IMAGE_PAGE,
            )
        }
    )
    registry.register_version(FIGURE_PYTHON_V1)
    registry.register_version(FIGURE_PYTHON_V101)
    registry.register_version(POLISH_V1)
    registry.register_version(TRANSLATION_TEXT_V1)
    registry.register_version(RESEARCH_DEFAULT_V1)
    registry.register_version(RESEARCH_LIGHT_V1)
    return registry


def resolve_text_model(
    config: Any,
    spec: PromptSpec,
    *,
    model_name: str | None = None,
    provider_name: str = "qwen",
) -> ModelSpec:
    """Resolve a user-selectable Qwen text model for a PromptSpec."""

    selected = str(model_name or "").strip() or None
    if selected is not None and selected not in TEXT_MODEL_CHOICES:
        raise ValueError(
            f"Unsupported text model '{selected}'. Choose one of: {', '.join(TEXT_MODEL_CHOICES)}."
        )
    role = spec.default_text_role or "worker"
    model = resolve_role_model(config, role, provider_name, selected)
    if model.name not in TEXT_MODEL_CHOICES:
        raise ValueError(
            f"Resolved text model '{model.name}' is outside the web model allow-list."
        )
    if spec.allowed_model_names and model.name not in spec.allowed_model_names:
        raise ValueError("The selected text model is disabled for this prompt profile.")
    require_model_capabilities(model, ("json_object",), "Web feature JSON output")
    return model


def with_selected_text_models(spec: PromptSpec, allowed_models: tuple[str, ...]) -> PromptSpec:
    """Return a copy with a narrowed model allow-list for a deployment profile."""

    invalid = set(allowed_models) - set(TEXT_MODEL_CHOICES)
    if invalid or not allowed_models:
        raise ValueError(f"Unsupported text models: {', '.join(sorted(invalid))}")
    return replace(spec, allowed_model_names=tuple(dict.fromkeys(allowed_models)))
