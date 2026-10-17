"""Frozen research text-model selection and supplementary scientific rules."""

from collections.abc import Mapping
from typing import Any

from omegaconf import OmegaConf

from .model_policy import validate_text_model


def freeze_research_policy(config: Any, *, model_name: str, prompt: Mapping[str, Any]) -> None:
    selected = validate_text_model(model_name)
    policy = {"model_name": selected, "provider": "qwen", "prompt": dict(prompt)}
    OmegaConf.update(config, "research_policy", policy, merge=False)
    OmegaConf.update(config, "survey.research_policy", policy, merge=False)
    overrides = {
        "llm.default_provider": "qwen",
        "survey.APIInfo.llm_provider": "qwen",
        "survey.APIInfo.llm_model_name": selected,
        "survey.ModuleInfo.Judge.provider": "qwen",
        "survey.ModuleInfo.Judge.model": selected,
        "idea.agent.model": selected,
        "idea.mcts.generation_model": selected,
        "idea.mcts.evaluation_model": selected,
        "experiment_design.provider": "qwen",
        "experiment_design.model": selected,
        "research_plan_author.provider": "qwen",
        "research_plan_author.model": selected,
        "quantitative_modeling.model": selected,
        "quantitative_modeling.repair_model": selected,
    }
    for key, value in overrides.items():
        OmegaConf.update(config, key, value, merge=False)
    defaults = OmegaConf.select(config, "llm.providers.qwen.default_models", default={})
    for role in list(defaults):
        OmegaConf.update(config, f"llm.providers.qwen.default_models.{role}", selected, merge=False)


def research_policy(config: Any) -> Mapping[str, Any]:
    value = config.get("research_policy", {}) if hasattr(config, "get") else {}
    return value if hasattr(value, "get") else {}


def research_messages(config: Any, prompt: str) -> list[dict[str, str]]:
    policy = research_policy(config)
    spec = policy.get("prompt", {})
    rules = str(spec.get("system_rules") or "").strip()
    messages = [{"role": "user", "content": prompt}]
    if rules:
        messages.insert(0, {"role": "system", "content": rules})
    return messages
