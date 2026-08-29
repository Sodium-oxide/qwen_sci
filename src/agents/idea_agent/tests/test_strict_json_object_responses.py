from __future__ import annotations

import pytest

from src.agents.idea_agent.utils.core.response_parsing import (
    JsonObjectResponseError,
    parse_json_object_response,
)
from src.agents.idea_agent.utils.workflow.ligagent_utils import LigRuntime


class _CapturingAgent:
    model = "mock-model"

    def __init__(self) -> None:
        self.request_kwargs: dict = {}

    def chat(self, prompt: str, **kwargs):
        del prompt
        self.request_kwargs = kwargs
        return '{"status": "ok"}'


def test_strict_json_object_parser_accepts_only_one_top_level_object() -> None:
    assert parse_json_object_response('{"status": "ok"}') == {"status": "ok"}

    with pytest.raises(JsonObjectResponseError):
        parse_json_object_response('["not", "an object"]')
    with pytest.raises(JsonObjectResponseError):
        parse_json_object_response('Preamble\n["fragment"]\n{"status": "ok"}')


def test_runtime_forwards_json_object_mode_without_leaking_internal_flag() -> None:
    agent = _CapturingAgent()
    runtime = LigRuntime(agent)

    result = runtime.llm_json(
        session=None,
        stage="advanced_analysis",
        op_name="test",
        prompt="Return an object.",
        require_json_object=True,
        response_format={"type": "json_object"},
    )

    assert result == {"status": "ok"}
    assert agent.request_kwargs["response_format"] == {"type": "json_object"}
    assert "require_json_object" not in agent.request_kwargs
