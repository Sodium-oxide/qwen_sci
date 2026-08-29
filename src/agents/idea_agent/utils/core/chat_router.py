from __future__ import annotations

from typing import Any, Dict, Mapping

from src.llm.provider_registry import resolve_model


HIGH_REASONING_STAGES = frozenset(
    {
        "advanced_analysis",
        "algorithm_alignment",
        "algorithm_structuring",
        "experiment_findings_extraction",
        "idea_fusion",
        "mcts_expand",
        "re_analysis_replan",
        "scientific_materialization",
    }
)


def _is_gpt5_family(model: str) -> bool:
    normalized = str(model or "").strip().lower()
    return normalized.startswith("gpt-5")


def _is_gemini_3_pro_family(model: str) -> bool:
    normalized = str(model or "").strip().lower()
    return normalized.startswith(("gemini-3-pro", "gemini-3.1-pro"))


def _is_claude_opus_4_6_family(model: str) -> bool:
    normalized = str(model or "").strip().lower()
    return normalized.startswith("claude-opus-4-6")


def _is_claude_sonnet_4_6_family(model: str) -> bool:
    normalized = str(model or "").strip().lower()
    return normalized.startswith("claude-sonnet-4-6")


def _is_deepseek_v3_2_family(model: str) -> bool:
    normalized = str(model or "").strip().lower()
    return normalized.startswith("deepseek-v3.2")


def _is_kimi_k2_5_family(model: str) -> bool:
    normalized = str(model or "").strip().lower()
    return normalized.startswith("kimi-k2.5")


def _is_glm_5_family(model: str) -> bool:
    normalized = str(model or "").strip().lower()
    return normalized.startswith("glm-5")


def _qwen_api_style(model: str) -> str | None:
    normalized = str(model or "").strip().lower()
    if normalized.startswith("qwen3-max"):
        return "responses"
    if normalized.startswith(("qwen3.", "qwen3-")):
        return "chat_completions"
    return None


def _strip_gpt_only_parameters(request_kwargs: Dict[str, Any]) -> None:
    for key in ("reasoning", "reasoning_effort", "verbosity", "service_tier"):
        request_kwargs.pop(key, None)


def prepare_ligagent_chat_request(
    *,
    model: str,
    stage: str,
    kwargs: Mapping[str, Any],
    config: Any = None,
) -> tuple[str, Dict[str, Any]]:
    resolved_model = str(model or "").strip()
    if not resolved_model:
        raise ValueError("LigAgent chat requires a non-empty model name.")

    request_kwargs = dict(kwargs)

    qwen_style = _qwen_api_style(resolved_model)
    if qwen_style is not None:
        _strip_gpt_only_parameters(request_kwargs)
        return resolved_model, request_kwargs

    try:
        model_spec = resolve_model(config, resolved_model)
    except (ValueError, TypeError):
        model_spec = None
    if model_spec is not None:
        if model_spec.provider == "qwen":
            if model_spec.api_style not in {"chat_completions", "responses"}:
                raise ValueError(
                    f"Unsupported LigAgent chat model protocol: {resolved_model} "
                    f"({model_spec.api_style})"
                )
            _strip_gpt_only_parameters(request_kwargs)
            return resolved_model, request_kwargs
        if model_spec.provider != "openai" and model_spec.api_style in {"chat_completions", "responses"}:
            return resolved_model, request_kwargs

    if _is_gpt5_family(resolved_model):
        request_kwargs["temperature"] = 1.0
        request_kwargs["reasoning"] = {
            "effort": "high" if stage in HIGH_REASONING_STAGES else "low"
        }
        return resolved_model, request_kwargs

    if _is_gemini_3_pro_family(resolved_model):
        return resolved_model, request_kwargs

    if _is_claude_opus_4_6_family(resolved_model):
        return resolved_model, request_kwargs

    if _is_claude_sonnet_4_6_family(resolved_model):
        return resolved_model, request_kwargs

    if _is_deepseek_v3_2_family(resolved_model):
        return resolved_model, request_kwargs

    if _is_kimi_k2_5_family(resolved_model):
        return resolved_model, request_kwargs

    if _is_glm_5_family(resolved_model):
        return resolved_model, request_kwargs

    raise ValueError(f"Unsupported LigAgent chat model: {resolved_model}")
