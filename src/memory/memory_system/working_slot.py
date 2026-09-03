import asyncio
import json

from typing import Dict, Iterable, List, Literal, Optional, Tuple, Union, Protocol
from src.memory.memory_system.utils import new_id, dump_slot_json
from pydantic import BaseModel, Field, field_validator, validate_call
from openai import OpenAI
from textwrap import dedent
from src.memory.memory_system.user_prompt import (
    EXPERIMENT_WORKING_SLOT_FILTER_USER_PROMPT,
    EXPERIMENT_WORKING_SLOT_ROUTE_USER_PROMPT,
    IDEA_WORKING_SLOT_FILTER_USER_PROMPT,
    IDEA_WORKING_SLOT_ROUTE_USER_PROMPT,
)
from src.memory.memory_system.llm import OpenAIClient, LLMClient


def _parse_enum_output(value: str, allowed: set[str], field_name: str) -> str:
    text = str(value or "").strip()
    normalized = text.lower().strip('"\'` ')
    if normalized in allowed:
        return normalized
    try:
        payload = json.loads(text)
    except Exception:
        payload = None
    if isinstance(payload, dict):
        for key in (field_name, "value", "result", "label"):
            candidate = str(payload.get(key) or "").strip().lower()
            if candidate in allowed:
                return candidate
    raise ValueError(f"Invalid {field_name} output: {value}")


async def _complete_enum(
    llm: LLMClient,
    system_prompt: str,
    user_prompt: str,
    allowed: set[str],
    field_name: str,
) -> str:
    response = await llm.complete(system_prompt, user_prompt)
    try:
        return _parse_enum_output(response, allowed, field_name)
    except ValueError as first_error:
        repair_prompt = (
            f"{user_prompt}\n\nYour previous output was invalid: {first_error}. "
            f"Return exactly one of: {', '.join(sorted(allowed))}."
        )
        repaired = await llm.complete(system_prompt, repair_prompt)
        return _parse_enum_output(repaired, allowed, field_name)

class SlotPayload(BaseModel):
    id: str = Field(default_factory=lambda: new_id("work"))
    stage: str = Field("", description="Stage of the working.")
    topic: str = Field("", description="Topic of the working slot.")
    summary: str = Field("", description="Summary of the working slot.")
    attachments: Dict[str, Dict] = Field(
        default_factory=dict,
        description="List of attachment identifiers associated with the slot.",
    )
    tags: List[str] = Field(
        default_factory=list,
        description="List of tags associated with the slot.",
    )

class WorkingSlot(SlotPayload):
    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "stage": self.stage,
            "topic": self.topic,
            "summary": self.summary,
            "attachments": self.attachments,
            "tags": self.tags,
        }
    
    async def slot_filter(self, llm: LLMClient, task: Literal["experiment", "idea"] = "experiment") -> bool:
        system_prompt = "You are a memory access reviewer. Only output 'yes' or 'no'."
        if task == "experiment":
            user_prompt = EXPERIMENT_WORKING_SLOT_FILTER_USER_PROMPT.format(slot_dump=dump_slot_json(self))
        elif task == "idea":
            user_prompt = IDEA_WORKING_SLOT_FILTER_USER_PROMPT.format(slot_dump=dump_slot_json(self))
        out = await _complete_enum(llm, system_prompt, user_prompt, {"yes", "no"}, "decision")
        return out == "yes"
    
    async def slot_router(self, llm: LLMClient, task: Literal["experiment", "idea"] = "experiment") -> Literal["semantic", "procedural", "episodic"]:
        system_prompt = "You are a memory type classifier. Only output legal string: 'semantic', 'procedural', or 'episodic'."
        if task == "experiment":
            user_prompt = EXPERIMENT_WORKING_SLOT_ROUTE_USER_PROMPT.format(slot_dump=dump_slot_json(self))
        elif task == "idea":
            user_prompt = IDEA_WORKING_SLOT_ROUTE_USER_PROMPT.format(slot_dump=dump_slot_json(self))
        return await _complete_enum(
            llm,
            system_prompt,
            user_prompt,
            {"semantic", "procedural", "episodic"},
            "memory_type",
        )
