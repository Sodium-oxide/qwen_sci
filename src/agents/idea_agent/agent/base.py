import os
from typing import Any, Dict, Optional

try:
    from openai import OpenAI
except ImportError:  # pragma: no cover - exercised only in limited test environments
    OpenAI = None  # type: ignore[assignment]

from src.agents.idea_agent.utils.core.chat_transport import (
    extract_response_text,
    normalize_chat_completions_kwargs,
    normalize_responses_kwargs,
    clamp_chat_output_tokens,
    resolve_chat_transport,
)
from src.llm.provider_registry import resolve_model, resolve_provider


DEFAULT_IDEA_CHAT_MODEL = "qwen3.7-plus"


def resolve_idea_chat_model(*candidates: Any) -> str:
    for candidate in candidates:
        model = str(candidate or "").strip()
        if model:
            return model
    return DEFAULT_IDEA_CHAT_MODEL


def _load_runtime_project_config(config: Any) -> Any:
    if config is not None and hasattr(config, "get") and config.get("llm") is not None:
        return config
    try:
        from src.config import get_config

        return get_config()
    except Exception:
        try:
            from src.agents.idea_agent.utils.core.config_loader import load_project_config

            return load_project_config()
        except Exception:
            return config

class AgentBase:
    """
    Minimal agent base with an action space and a chat model.
    - action_space: list of allowed action names (strings)
    - chat_model: chat model to interact with the user
    """

    def __init__(self,
                    actions: Optional[Dict[str, str]] = None,
                    chat_model: Optional[Any] = None,
                    config: Optional[Any] = None,
                    provider_name: Optional[str] = None) -> None:
        self.action_space: Dict[str, str] = actions or {}
        self.project_config = _load_runtime_project_config(config)
        selected_provider = provider_name or os.getenv("QWENSCI_LLM_PROVIDER") or None
        self.provider = resolve_provider(self.project_config, selected_provider)
        self.base_url = (
            os.getenv("OPENAI_BASE_URL")
            if self.provider.name == "openai"
            else os.getenv("DASHSCOPE_BASE_URL")
        ) or self.provider.base_url
        self.api_style = os.getenv("OPENAI_API_STYLE", "auto")
        if chat_model is not None:
            self.chat_model = chat_model
        else:
            if OpenAI is None:
                raise ImportError(
                    "openai package is required to construct the default AgentBase chat client."
                )
            self.chat_model = OpenAI(
                api_key=self.provider.api_key,
                base_url=self.base_url,
            )

    def chat(self, prompt: str, model: Optional[str] = None, **kwargs) -> str:
        """
        Interact with the chat model using the given prompt.
        Returns the response text.
        """
        if not str(prompt or "").strip():
            raise ValueError("Chat prompt must not be empty.")
        resolved_model = resolve_idea_chat_model(model, self.default_model)
        resolve_model(self.project_config, resolved_model, self.provider.name)
        transport = resolve_chat_transport(
            self._current_base_url(),
            self.api_style,
            model=resolved_model,
            config=self.project_config,
        )
        request_kwargs = clamp_chat_output_tokens(
            self.project_config,
            resolved_model,
            kwargs,
        )
        if transport not in {"chat_completions", "responses"}:
            raise ValueError(
                f"Idea Agent text chat requires Chat Completions or Responses; "
                f"model '{resolved_model}' resolves to '{transport}'."
            )
        if transport == "chat_completions":
            request_kwargs = normalize_chat_completions_kwargs(
                request_kwargs,
                strip_reasoning=self.provider.name == "qwen",
            )
            response = self.chat_model.chat.completions.create(
                model=resolved_model,
                messages=[{"role": "user", "content": prompt}],
                **request_kwargs,
            )
            return extract_response_text(response)

        request_kwargs = normalize_responses_kwargs(
            request_kwargs,
            strip_gpt_parameters=self.provider.name == "qwen",
        )
        response = self.chat_model.responses.create(
            model=resolved_model,
            input=[{"role": "user", "content": prompt}],
            **request_kwargs,
        )
        return extract_response_text(response)

    def _current_base_url(self) -> Optional[str]:
        client_base_url = getattr(self.chat_model, "base_url", None)
        return str(client_base_url or self.base_url or "").strip() or None

    @property
    def default_model(self) -> str:
        return DEFAULT_IDEA_CHAT_MODEL
