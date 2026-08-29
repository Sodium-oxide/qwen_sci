from __future__ import annotations

import os
from dataclasses import dataclass, fields
from typing import Any, Mapping, Optional, Sequence


_SUPPORTED_API_STYLES = {"chat_completions", "images", "responses"}


@dataclass(frozen=True)
class ProviderSpec:
    name: str
    api_key: str
    api_key_env: str
    base_url: str
    api_style: str
    openhands_model_prefix: str
    tokenizer_fallback: str
    token_limit_parameter: str
    default_models: Mapping[str, str]


@dataclass(frozen=True)
class ModelCapabilities:
    chat_completions: bool = False
    responses: bool = False
    reasoning: bool = False
    tools: bool = False
    streaming: bool = False
    streaming_tools: bool = False
    json_schema: bool = False
    json_object: bool = False
    vision: bool = False
    image_generation: bool = False


@dataclass(frozen=True)
class ModelSpec:
    name: str
    provider: str
    api_style: str
    tokenizer_fallback: str
    capabilities: ModelCapabilities
    max_output_tokens: int = 16384


def provider_required_settings(provider: ProviderSpec) -> list[tuple[str, bool, str]]:
    return [
        (
            provider.api_key_env or f"{provider.name.upper()} API key",
            bool(provider.api_key),
            f"required by provider={provider.name}",
        ),
        (
            f"{provider.name} base URL",
            bool(provider.base_url),
            provider.base_url or "<missing>",
        ),
    ]


_BUILTIN_PROVIDERS: dict[str, dict[str, Any]] = {
    "openai": {
        "api_key_env": "OPENAI_API_KEY",
        "base_url": "https://api.openai.com/v1",
        "api_style": "chat_completions",
        "openhands_model_prefix": "openai",
        "tokenizer_fallback": "o200k_base",
        "token_limit_parameter": "",
        "default_models": {
            "survey": "gpt-5.4-mini",
            "judge": "gpt-5.5",
            "blog": "gpt-5.5",
            "idea": "gpt-5.5",
            "idea_generation": "gpt-5-mini",
            "idea_evaluation": "gpt-5.5",
            "experiment": "gpt-5.4",
            "experiment_design": "gpt-5.4",
            "planner": "gpt-5.4",
            "worker": "gpt-5-mini",
            "reviewer": "gpt-5.4",
            "master": "gpt-5.4",
            "memory_filter": "gpt-5-mini",
            "memory_router": "gpt-5-mini",
            "memory_synthesis": "gpt-5.4",
        },
    },
    "qwen": {
        "api_key_env": "DASHSCOPE_API_KEY",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "api_style": "chat_completions",
        "openhands_model_prefix": "openai",
        "tokenizer_fallback": "utf8_bytes",
        "token_limit_parameter": "max_tokens",
        "default_models": {
            "survey": "qwen3.6-flash",
            "judge": "qwen3.8-max",
            "blog": "qwen3.8-max",
            "idea": "qwen3.8-flash",
            "idea_generation": "qwen3.8-flash",
            "idea_evaluation": "qwen3-max-2026-01-23",
            "experiment": "qwen3.7-plus",
            "experiment_design": "qwen3.8-flash",
            "planner": "qwen3.7-plus",
            "worker": "qwen3.7-plus",
            "reviewer": "qwen3.7-plus",
            "master": "qwen3.7-plus",
            "memory_filter": "qwen3.6-flash",
            "memory_router": "qwen3.6-flash",
            "memory_synthesis": "qwen3.8-max",
        },
    },
}


_BUILTIN_MODELS: dict[str, dict[str, Any]] = {
    "qwen3-max-2026-01-23": {
        "provider": "qwen",
        "api_style": "responses",
        "capabilities": {
            "responses": True,
            "reasoning": True,
            "streaming": True,
            "json_schema": True,
            "json_object": True,
        },
        "max_output_tokens": 32768,
    },
    "qwen3.7-plus": {
        "provider": "qwen",
        "api_style": "chat_completions",
        "capabilities": {
            "chat_completions": True,
            "streaming": True,
            "tools": True,
            "streaming_tools": True,
            "vision": True,
            "json_object": True,
        },
        "max_output_tokens": 32768,
    },
    "qwen3.8-max": {
        "provider": "qwen",
        "api_style": "chat_completions",
        "capabilities": {
            "chat_completions": True,
            "streaming": True,
            "vision": True,
            "json_object": True,
        },
        "max_output_tokens": 32768,
    },
    "qwen3.8-flash": {
        "provider": "qwen",
        "api_style": "chat_completions",
        "capabilities": {
            "chat_completions": True,
            "streaming": True,
            "json_object": True,
        },
        "max_output_tokens": 128000,
    },
    "qwen3.6-flash": {
        "provider": "qwen",
        "api_style": "chat_completions",
        "capabilities": {
            "chat_completions": True,
            "streaming": True,
            "json_object": True,
        },
        "max_output_tokens": 32768,
    },
    "qwen3-vl-plus": {
        "provider": "qwen",
        "api_style": "chat_completions",
        "capabilities": {
            "chat_completions": True,
            "streaming": True,
            "vision": True,
            "json_object": True,
        },
        "max_output_tokens": 16384,
    },
    "qwen3-vl-flash": {
        "provider": "qwen",
        "api_style": "chat_completions",
        "capabilities": {
            "chat_completions": True,
            "streaming": True,
            "vision": True,
            "json_object": True,
        },
        "max_output_tokens": 16384,
    },
    "wan2.7-image-pro": {
        "provider": "qwen",
        "api_style": "images",
        "capabilities": {"image_generation": True},
    },
    "qwen-image-3.0-pro": {
        "provider": "qwen",
        "api_style": "images",
        "capabilities": {"image_generation": True},
    },
    "z-image-turbo": {
        "provider": "qwen",
        "api_style": "images",
        "capabilities": {"image_generation": True},
    },
}


def _as_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _nested_mapping(config: Any, *keys: str) -> Mapping[str, Any]:
    current: Any = config
    for key in keys:
        current = _as_mapping(current).get(key)
    return _as_mapping(current)


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _infer_provider_name(model_name: str) -> str:
    normalized = _clean_text(model_name).lower()
    if normalized.startswith(("qwen", "wan", "z-image")):
        return "qwen"
    if normalized.startswith(("gpt", "o1", "o3", "o4")):
        return "openai"
    return ""


def get_default_provider_name(config: Any = None) -> str:
    configured = _clean_text(_nested_mapping(config, "llm").get("default_provider"))
    return configured or _clean_text(os.environ.get("QWENSCI_LLM_PROVIDER")) or "qwen"


def resolve_provider(config: Any = None, provider_name: Optional[str] = None) -> ProviderSpec:
    name = _clean_text(provider_name or get_default_provider_name(config)).lower()
    configured = _nested_mapping(config, "llm", "providers").get(name)
    configured_mapping = _as_mapping(configured)
    merged: dict[str, Any] = dict(_BUILTIN_PROVIDERS.get(name, {}))
    merged.update(configured_mapping)
    if not merged:
        raise ValueError(f"Unknown LLM provider: {name}")

    api_key_env = _clean_text(merged.get("api_key_env"))
    api_key = _clean_text(merged.get("api_key"))
    if not api_key and api_key_env:
        api_key = _clean_text(os.environ.get(api_key_env))
    api_style = _clean_text(merged.get("api_style")) or "chat_completions"
    if api_style not in _SUPPORTED_API_STYLES:
        supported = ", ".join(sorted(_SUPPORTED_API_STYLES))
        raise ValueError(
            f"Unsupported API style '{api_style}' for provider '{name}'. Expected one of: {supported}."
        )

    base_url = _clean_text(configured_mapping.get("base_url"))
    if not base_url and name == "openai":
        legacy_openai = _nested_mapping(config, "api", "openai")
        base_url = (
            _clean_text(os.environ.get("OPENAI_BASE_URL"))
            or _clean_text(os.environ.get("OPENAI_API_BASE"))
            or _clean_text(legacy_openai.get("base_url"))
            or _clean_text(legacy_openai.get("api_base"))
        )
    if not base_url:
        base_url = (
            _clean_text(merged.get("base_url"))
            or _clean_text(_BUILTIN_PROVIDERS.get(name, {}).get("base_url"))
        )

    builtin_default_models = _as_mapping(
        _BUILTIN_PROVIDERS.get(name, {}).get("default_models")
    )
    configured_default_models = _as_mapping(configured_mapping.get("default_models"))
    default_models = {
        str(role): _clean_text(model)
        for role, model in {**builtin_default_models, **configured_default_models}.items()
        if _clean_text(model)
    }

    return ProviderSpec(
        name=name,
        api_key=api_key,
        api_key_env=api_key_env,
        base_url=base_url,
        api_style=api_style,
        openhands_model_prefix=_clean_text(merged.get("openhands_model_prefix")) or "openai",
        tokenizer_fallback=_clean_text(merged.get("tokenizer_fallback")) or "o200k_base",
        token_limit_parameter=_clean_text(merged.get("token_limit_parameter")),
        default_models=default_models,
    )


def resolve_role_model(
    config: Any,
    role: str,
    provider_name: Optional[str] = None,
    configured_model: Optional[str] = None,
) -> ModelSpec:
    provider = resolve_provider(config, provider_name)
    model_name = _clean_text(configured_model) or _clean_text(
        provider.default_models.get(_clean_text(role).lower())
    )
    if not model_name:
        raise ValueError(
            f"No default model is configured for role '{role}' and provider '{provider.name}'."
        )
    return resolve_model(config, model_name, provider.name)


def require_model_capabilities(
    model: ModelSpec,
    capabilities: Sequence[str],
    consumer: str,
) -> ModelSpec:
    missing = [
        capability
        for capability in capabilities
        if not hasattr(model.capabilities, capability)
        or not getattr(model.capabilities, capability)
    ]
    if missing:
        required = ", ".join(missing)
        raise ValueError(
            f"{consumer} cannot use model '{model.name}' from provider '{model.provider}': "
            f"missing required capabilities: {required}."
        )
    return model


def resolve_model(
    config: Any,
    model_name: str,
    provider_name: Optional[str] = None,
) -> ModelSpec:
    name = _clean_text(model_name)
    if not name:
        raise ValueError("LLM model name must not be empty.")

    provider = resolve_provider(config, provider_name)
    configured = _as_mapping(_nested_mapping(config, "llm", "models").get(name))
    builtin = _as_mapping(_BUILTIN_MODELS.get(name))
    merged_model: dict[str, Any] = {**builtin, **configured}
    configured_provider = (
        _clean_text(merged_model.get("provider"))
        or _infer_provider_name(name)
        or provider.name
    )
    if provider_name and configured_provider != provider.name:
        raise ValueError(
            f"Model '{name}' is registered for provider '{configured_provider}', not '{provider.name}'."
        )

    resolved_provider = resolve_provider(config, configured_provider)
    api_style = _clean_text(merged_model.get("api_style")) or resolved_provider.api_style
    if api_style not in _SUPPORTED_API_STYLES:
        supported = ", ".join(sorted(_SUPPORTED_API_STYLES))
        raise ValueError(
            f"Unsupported API style '{api_style}' for model '{name}'. Expected one of: {supported}."
        )

    raw_capabilities = _as_mapping(merged_model.get("capabilities"))
    capability_values = {
        field.name: bool(raw_capabilities.get(field.name, False))
        for field in fields(ModelCapabilities)
    }
    if not merged_model:
        if api_style in {"chat_completions", "responses"}:
            capability_values[api_style] = True
        capability_values["streaming"] = api_style == "chat_completions"
        if resolved_provider.name == "openai" and api_style == "chat_completions":
            capability_values["tools"] = True
            capability_values["streaming_tools"] = True

    return ModelSpec(
        name=name,
        provider=resolved_provider.name,
        api_style=api_style,
        tokenizer_fallback=(
            _clean_text(merged_model.get("tokenizer_fallback"))
            or resolved_provider.tokenizer_fallback
        ),
        capabilities=ModelCapabilities(**capability_values),
        max_output_tokens=max(
            1,
            int(merged_model.get("max_output_tokens") or 16384),
        ),
    )


def clamp_output_tokens(
    config: Any,
    model_name: str,
    requested: Any,
    provider_name: Optional[str] = None,
) -> int:
    """Clamp a requested output budget to the registered model limit."""
    model = resolve_model(config, model_name, provider_name)
    try:
        value = int(requested)
    except Exception:
        value = model.max_output_tokens
    return max(1, min(value, model.max_output_tokens))


def build_chat_completions_url(base_url: str) -> str:
    normalized = _clean_text(base_url).rstrip("/")
    if not normalized:
        raise ValueError("Chat Completions base URL must not be empty.")
    if normalized.endswith("/chat/completions"):
        return normalized
    return f"{normalized}/chat/completions"
