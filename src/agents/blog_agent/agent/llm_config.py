from __future__ import annotations

from typing import Any, Mapping, Optional

from src.llm.provider_registry import (
    get_default_provider_name,
    require_model_capabilities,
    resolve_model,
    resolve_provider,
    resolve_role_model,
)


def _as_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def resolve_blog_model(
    project_config: Any,
    model: Optional[str] = None,
    provider: Optional[str] = None,
) -> str:
    blog_config = _as_mapping(_as_mapping(project_config).get("blog"))
    configured_model = str(model or blog_config.get("model") or "").strip()
    if configured_model:
        return configured_model

    configured_provider = str(provider or blog_config.get("provider") or "").strip()
    if configured_provider or _as_mapping(project_config).get("llm"):
        return resolve_role_model(
            project_config,
            "blog",
            configured_provider or get_default_provider_name(project_config),
        ).name
    return "MiniMax-M2.5"


def build_openhands_config(
    project_config: Any,
    model: Optional[str] = None,
    provider: Optional[str] = None,
) -> dict[str, str]:
    blog_config = _as_mapping(project_config).get("blog")
    blog_config = _as_mapping(blog_config)
    configured_model = resolve_blog_model(project_config, model, provider)
    resolved_provider_name = str(provider or blog_config.get("provider") or "").strip()

    minimax_config = _as_mapping(blog_config.get("minimax"))
    if not resolved_provider_name and "minimax" in configured_model.lower():
        return {
            "api_key": str(minimax_config.get("api_key") or ""),
            "model": f"minimax/{configured_model}",
            "base_url": str(
                minimax_config.get("base_url") or "https://api.minimaxi.com/v1"
            ),
        }

    gemini_config = _as_mapping(blog_config.get("gemini"))
    if not resolved_provider_name and "gemini" in configured_model.lower():
        return {
            "api_key": str(gemini_config.get("api_key") or ""),
            "model": f"gemini/{configured_model}",
            "base_url": str(gemini_config.get("base_url") or ""),
        }

    openai_config = _as_mapping(blog_config.get("openai"))
    if (
        not resolved_provider_name
        and configured_model.lower().startswith(("gpt", "o1", "o3", "o4"))
        and (openai_config.get("api_key") or openai_config.get("base_url"))
    ):
        openai_provider = resolve_provider(project_config, "openai")
        model_spec = require_model_capabilities(
            resolve_model(project_config, configured_model, "openai"),
            ["chat_completions"],
            "Blog OpenHands text agent",
        )
        return {
            "api_key": str(openai_config.get("api_key") or ""),
            "model": f"openai/{model_spec.name}",
            "base_url": str(openai_config.get("base_url") or openai_provider.base_url),
        }

    if resolved_provider_name or _as_mapping(project_config).get("llm"):
        provider_spec = resolve_provider(
            project_config,
            resolved_provider_name or get_default_provider_name(project_config),
        )
        model_spec = (
            resolve_model(project_config, configured_model, provider_spec.name)
            if configured_model
            else resolve_role_model(project_config, "blog", provider_spec.name)
        )
        require_model_capabilities(
            model_spec,
            ["chat_completions"],
            "Blog OpenHands text agent",
        )
        return {
            "api_key": provider_spec.api_key,
            "model": f"{provider_spec.openhands_model_prefix}/{model_spec.name}",
            "base_url": provider_spec.base_url,
        }

    return {
        "api_key": str(openai_config.get("api_key") or ""),
        "model": f"openai/{configured_model or 'gpt-5.5'}",
        "base_url": str(openai_config.get("base_url") or ""),
    }
