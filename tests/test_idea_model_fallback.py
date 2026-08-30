from pathlib import Path

from src.agents.idea_agent.agent.base import (
    DEFAULT_IDEA_CHAT_MODEL,
    resolve_idea_chat_model,
)
from src.agents.idea_agent.utils.core.chat_router import prepare_ligagent_chat_request
from src.agents.idea_agent.utils.core.config_loader import load_idea_agent_config


def test_empty_idea_chat_model_uses_qwen_plus_fallback() -> None:
    assert resolve_idea_chat_model(None, "", "   ") == DEFAULT_IDEA_CHAT_MODEL
    assert resolve_idea_chat_model("qwen3.8-max", "qwen3.7-plus") == "qwen3.8-max"


def test_empty_ligagent_request_model_uses_qwen_plus_fallback() -> None:
    model, request_kwargs = prepare_ligagent_chat_request(
        model="",
        stage="mcts_expand",
        kwargs={"temperature": 0.7},
    )

    assert model == DEFAULT_IDEA_CHAT_MODEL
    assert request_kwargs == {"temperature": 0.7}


def test_default_idea_models_use_qwen_plus_when_environment_is_unset(monkeypatch) -> None:
    for variable in (
        "IDEA_LLM_MODEL",
        "IDEA_GENERATION_MODEL",
        "IDEA_EVALUATION_MODEL",
    ):
        monkeypatch.delenv(variable, raising=False)

    config_path = Path("src/config/default.yaml")
    config = load_idea_agent_config(str(config_path))

    assert config.agent.model == DEFAULT_IDEA_CHAT_MODEL
    assert config.mcts.generation_model == DEFAULT_IDEA_CHAT_MODEL
    assert config.mcts.evaluation_model == DEFAULT_IDEA_CHAT_MODEL
    assert config.mcts.component_novelty_eval_model == DEFAULT_IDEA_CHAT_MODEL
    assert config.mcts.max_iterations == 8
