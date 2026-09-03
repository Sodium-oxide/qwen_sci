from types import SimpleNamespace

import src.agents.idea_agent.agent.base as base


class _FakeCompletions:
    def __init__(self) -> None:
        self.kwargs = {}

    def create(self, **kwargs):
        self.kwargs = kwargs
        return iter(
            [
                SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="first "))]),
                SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="second"))]),
            ]
        )


class _FakeChatModel:
    def __init__(self) -> None:
        self.completions = _FakeCompletions()
        self.chat = SimpleNamespace(completions=self.completions)


def test_agent_base_consumes_chat_stream_and_reports_fragments(monkeypatch) -> None:
    model = _FakeChatModel()
    provider = SimpleNamespace(name="qwen", default_models={}, base_url="https://example.test/v1")
    model_spec = SimpleNamespace()
    monkeypatch.setattr(base, "resolve_provider", lambda *_args, **_kwargs: provider)
    monkeypatch.setattr(base, "resolve_model", lambda *_args, **_kwargs: model_spec)
    monkeypatch.setattr(base, "resolve_chat_transport", lambda *_args, **_kwargs: "chat_completions")

    fragments: list[str] = []
    agent = base.AgentBase(chat_model=model, config={"llm": {}})

    result = agent.chat(
        "return text",
        model="qwen3.7-plus",
        stream=True,
        stream_callback=fragments.append,
        max_output_tokens=128,
    )

    assert result == "first second"
    assert fragments == ["first ", "second"]
    assert model.completions.kwargs["stream"] is True
    assert model.completions.kwargs["max_tokens"] == 128
