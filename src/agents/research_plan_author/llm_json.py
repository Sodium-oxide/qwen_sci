"""Required JSON-only LLM invocation for Research Plan Author stages."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from threading import local
from typing import Any, Optional

from src.agents.experiment_design_agent.llm_json import (
    JSON_OBJECT_RESPONSE_FORMAT,
    RequiredJsonLLMError,
    call_required_json,
)
from src.llm.provider_registry import resolve_model


def build_author_json_llm_call(
    *,
    config: Any = None,
    model: Optional[str] = None,
    temperature: float | None = None,
) -> Callable[..., object]:
    """Build the configured Author callback while preserving strict JSON mode."""

    holder = local()

    def setting(value: Any, key: str, default: Any = "") -> Any:
        if isinstance(value, Mapping):
            return value.get(key, default)
        return getattr(value, key, default)

    def _call(prompt: str, **kwargs: Any) -> object:
        if kwargs.get("response_format", JSON_OBJECT_RESPONSE_FORMAT) != JSON_OBJECT_RESPONSE_FORMAT:
            raise RequiredJsonLLMError("research_plan_author: only JSON object response format is permitted")
        runtime_config = config
        if runtime_config is None:
            from src.config import get_config

            runtime_config = get_config()
        author_config = setting(runtime_config, "research_plan_author", {})
        authoring_config = setting(author_config, "authoring", {})
        resolved_model = str(model or setting(author_config, "model") or "").strip()
        provider_name = str(setting(author_config, "provider") or "").strip()
        resolved_temperature = float(
            setting(authoring_config, "temperature", 0.5) if temperature is None else temperature
        )
        if model:
            provider_name = resolve_model(runtime_config, resolved_model).provider
        agent = getattr(holder, "agent", None)
        if agent is None:
            from src.agents.idea_agent.agent.base import AgentBase

            agent = AgentBase(config=runtime_config, provider_name=provider_name or None)
            holder.agent = agent
        if not resolved_model:
            resolved_model = str(agent.provider.default_models.get("author") or "").strip()
        if not resolved_model:
            raise RequiredJsonLLMError("research_plan_author: no model is configured for the author LLM role")
        return agent.chat(
            prompt,
            model=resolved_model,
            response_format=JSON_OBJECT_RESPONSE_FORMAT,
            temperature=resolved_temperature,
        )

    return _call


__all__ = [
    "JSON_OBJECT_RESPONSE_FORMAT",
    "RequiredJsonLLMError",
    "build_author_json_llm_call",
    "call_required_json",
]
