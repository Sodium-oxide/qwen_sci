import asyncio
from types import SimpleNamespace

import pytest

from src.llm.structured_output import StructuredOutputError, parse_and_validate
from src.memory.api.slot_process_api import MemoryConversionError, SlotProcess
from src.memory.memory_system.llm import OpenAIClient
from src.memory.memory_system.working_slot import WorkingSlot


SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string", "minLength": 1},
        "tags": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["summary", "tags"],
    "additionalProperties": False,
}


class FakeResponses:
    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(output_text=self.outputs.pop(0))


class FakeCompletions:
    def __init__(self, outputs, reject_response_format=False):
        self.outputs = list(outputs)
        self.calls = []
        self.reject_response_format = reject_response_format

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.reject_response_format and "response_format" in kwargs:
            raise TypeError("response_format is unsupported")
        message = SimpleNamespace(content=self.outputs.pop(0))
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


class FakeClient:
    def __init__(self, *, responses=None, chat=None):
        self.responses = responses or FakeResponses([])
        self.chat = SimpleNamespace(completions=chat or FakeCompletions([]))


def _complete_json(client, **kwargs):
    return asyncio.run(client.complete_json(**kwargs))


def test_qwen_responses_uses_strict_json_schema_without_chat_fallback():
    fake = FakeClient(responses=FakeResponses(['{"summary":"kept","tags":[]}']))
    client = OpenAIClient(
        model="qwen3-max-2026-01-23",
        provider="qwen",
        client=fake,
    )

    result = _complete_json(
        client,
        system_prompt="system",
        user_prompt="user",
        json_schema=SCHEMA,
        max_tokens=999999,
    )

    assert result == {"summary": "kept", "tags": []}
    request = fake.responses.calls[0]
    assert request["max_output_tokens"] == 32768
    assert request["text"]["format"]["type"] == "json_schema"
    assert request["text"]["format"]["strict"] is True
    assert not fake.chat.completions.calls


def test_qwen_chat_model_does_not_attempt_responses():
    chat = FakeCompletions(['{"summary":"chat","tags":[]}'])
    fake = FakeClient(chat=chat)
    client = OpenAIClient(model="qwen3.8-max", provider="qwen", client=fake)

    result = _complete_json(
        client,
        system_prompt="system",
        user_prompt="user",
        json_schema=SCHEMA,
    )

    assert result["summary"] == "chat"
    assert not fake.responses.calls
    assert chat.calls[0]["response_format"] == {"type": "json_object"}
    assert "Return JSON matching this schema" in chat.calls[0]["messages"][-1]["content"]


def test_chat_response_format_rejection_falls_back_to_local_validation():
    chat = FakeCompletions(
        ['{"summary":"fallback","tags":[]}'],
        reject_response_format=True,
    )
    fake = FakeClient(chat=chat)
    client = OpenAIClient(model="qwen3.6-flash", provider="qwen", client=fake)

    result = _complete_json(
        client,
        system_prompt="system",
        user_prompt="user",
        json_schema=SCHEMA,
    )

    assert result["summary"] == "fallback"
    assert len(chat.calls) == 2
    assert "response_format" not in chat.calls[1]


def test_invalid_structured_output_is_repaired_once():
    chat = FakeCompletions(["not json", '{"summary":"repaired","tags":[]}'])
    fake = FakeClient(chat=chat)
    client = OpenAIClient(model="qwen3.8-max", provider="qwen", client=fake)

    result = _complete_json(
        client,
        system_prompt="system",
        user_prompt="user",
        json_schema=SCHEMA,
        repair_attempts=1,
    )

    assert result["summary"] == "repaired"
    assert len(chat.calls) == 2
    assert "failed local validation" in chat.calls[1]["messages"][-1]["content"]


def test_local_schema_rejects_missing_and_extra_fields():
    with pytest.raises(StructuredOutputError, match="missing required fields"):
        parse_and_validate('{"summary":"missing tags"}', SCHEMA)
    with pytest.raises(StructuredOutputError, match="unsupported fields"):
        parse_and_validate('{"summary":"ok","tags":[],"extra":1}', SCHEMA)


class EnumLLM:
    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.calls = []

    async def complete(self, system_prompt, user_prompt, **kwargs):
        self.calls.append((system_prompt, user_prompt, kwargs))
        return self.outputs.pop(0)


def test_slot_filter_and_router_repair_invalid_enum_outputs():
    slot = WorkingSlot(stage="analysis", topic="topic", summary="summary")
    llm = EnumLLM(["maybe", "yes", '{"memory_type":"semantic"}'])

    assert asyncio.run(slot.slot_filter(llm, task="idea")) is True
    assert asyncio.run(slot.slot_router(llm, task="idea")) == "semantic"
    assert len(llm.calls) == 3


def test_provider_conversion_failure_stops_before_store_writes(monkeypatch):
    process = SlotProcess(llm_client=SimpleNamespace())

    def fail_conversion(slot):
        raise MemoryConversionError("Qwen output could not be validated")

    monkeypatch.setattr(process, "transfer_slot_to_semantic_record", fail_conversion)
    slot = WorkingSlot(stage="analysis", topic="topic", summary="summary")

    with pytest.raises(MemoryConversionError, match="no records are safe to persist"):
        asyncio.run(
            process.generate_long_term_memory(
                [{"memory_type": "semantic", "slot": slot}]
            )
        )

    assert process.memory_dict == []
