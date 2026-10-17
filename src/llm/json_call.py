"""Shared JSON transport with role-preserving messages and bounded requests."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from typing import Any

from .provider_registry import clamp_output_tokens, require_model_capabilities, resolve_model, resolve_provider


JSON_OBJECT_RESPONSE_FORMAT = {"type": "json_object"}


class RequiredJsonLLMError(RuntimeError):
    code = "LLM_REQUEST_FAILED"
    retryable = True


def call_required_json(llm_call: Callable[..., object] | None, prompt: object, *, stage: str) -> dict[str, Any]:
    if llm_call is None:
        raise RequiredJsonLLMError(f"{stage}: an LLM callback is required.")
    try:
        raw = llm_call(prompt, response_format=JSON_OBJECT_RESPONSE_FORMAT)
    except RequiredJsonLLMError:
        raise
    except Exception as exc:
        raise RequiredJsonLLMError(f"{stage}: provider request failed ({type(exc).__name__}).") from exc
    if isinstance(raw, Mapping):
        return dict(raw)
    if not isinstance(raw, str):
        raise ValueError(f"{stage}: the model response must contain a JSON object.")
    try:
        parsed = json.loads(raw, parse_constant=_reject_constant)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"{stage}: the model response is not one complete JSON object.") from exc
    if not isinstance(parsed, dict):
        raise ValueError(f"{stage}: the model response must be an object.")
    return parsed


def _reject_constant(value: str) -> None:
    raise ValueError("Non-finite JSON numbers are not permitted.")


def build_web_json_llm_call(
    *, config: Any, model: str, provider_name: str = "qwen", timeout: float = 120,
    temperature: float = 0.2, max_output_tokens: int = 16384,
) -> Callable[..., object]:
    resolved = resolve_model(config, model, provider_name)
    require_model_capabilities(resolved, ("json_object",), "Web feature JSON transport")
    provider = resolve_provider(config, resolved.provider)
    budget = clamp_output_tokens(config, model, max_output_tokens, provider.name)

    def invoke(prompt: object, **kwargs: Any) -> str:
        from openai import OpenAI

        if kwargs.get("response_format", JSON_OBJECT_RESPONSE_FORMAT) != JSON_OBJECT_RESPONSE_FORMAT:
            raise ValueError("Web feature transport requires JSON object mode.")
        if not provider.api_key or not provider.base_url:
            raise RequiredJsonLLMError("The selected model provider is not configured.")
        messages = prompt if isinstance(prompt, list) else [{"role": "user", "content": str(prompt)}]
        with OpenAI(api_key=provider.api_key, base_url=provider.base_url, timeout=max(0.01, timeout), max_retries=0) as client:
            if resolved.api_style == "responses":
                response = client.responses.create(
                    model=model, input=messages, max_output_tokens=budget,
                    text={"format": JSON_OBJECT_RESPONSE_FORMAT},
                )
                return response.output_text
            response = client.chat.completions.create(
                model=model, messages=messages, response_format=JSON_OBJECT_RESPONSE_FORMAT,
                temperature=temperature, max_tokens=budget,
            )
            return response.choices[0].message.content or ""

    return invoke


__all__ = ["JSON_OBJECT_RESPONSE_FORMAT", "RequiredJsonLLMError", "call_required_json", "build_web_json_llm_call"]
