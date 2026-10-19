"""Shared prompt contracts and evidence guardrails."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping


COMMON_GUARDRAILS: tuple[str, ...] = (
    "Do not invent data, numerical values, experimental results, citations, DOIs, sample sizes, or sources.",
    "Mark unsupported or ambiguous input as unresolved_items instead of guessing.",
    "Preserve numbers, units, equations, variable names, entity IDs, citation keys, and figure/table IDs.",
    "Do not turn a model assumption into a literature fact.",
    "Return only the requested JSON object; do not wrap it in Markdown or explanations.",
    "Model output is a candidate and must pass local validation before it becomes an artifact.",
    "Match claim strength to the supplied evidence; do not turn association into causation.",
)

# SHA-256 values of the installed skill routers used to distil these prompts.
# Updating a skill requires updating this table and the PromptSpec version.
SKILL_SOURCE_HASHES: dict[str, str] = {
    "nature-figure": "5aefe708a2531c5ddaa8ee74d5155d747e96c0f21a33143d38316b7c5c88ffc4",
    "nature-polishing": "9391b2a2487306cf2ed560377d4bc10c339fd2c220a79db278cb7f9d31e79023",
    "nature-reader": "999a5c1b116558133d0389ce6c1bbc3dc9cf5242d1be2870358789769d97a84e",
    "nature-paper-trans": "f340351f110b67d37a7b272b81c15740ec4863e125698a817d68b8b27866a7fe",
    "academic-humanizer": "dfa9eda654c7904aed87d80e081817a0bbbbddc82aff2292c96a95c420f54594",
    "nature-data": "4ef9c383411b069265901e9f157cb4d73861f42f6ddd28611084005e67eafa43",
    "nature-statistics": "89d2a101fc45d7adf8ca327a6da4bda4a696d6364d7c36ead4f53413627a9b6f",
    "nature-writing": "ce7c4d20329b96b03b0f0c0bb744411b1b4deaa7a7b69b90757705a83c195b12",
}


def _canonical_hash(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _freeze(value: object) -> object:
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, (tuple, list)):
        return tuple(_freeze(item) for item in value)
    return value


def _json_value(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    return value


@dataclass(frozen=True, slots=True)
class PromptSpec:
    """Immutable prompt metadata persisted with each Job manifest."""

    prompt_id: str
    prompt_version: str
    skill_ids: tuple[str, ...]
    source_refs: tuple[str, ...]
    source_hashes: tuple[tuple[str, str], ...]
    system_prompt: str
    output_schema: Mapping[str, object]
    guardrails: tuple[str, ...]
    default_text_role: str | None = None
    image_model_role: str | None = None
    allowed_model_names: tuple[str, ...] = ()
    inherit_common_guardrails: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "output_schema", _freeze(self.output_schema))

    @property
    def prompt_hash(self) -> str:
        return _canonical_hash(
            {
                "prompt_id": self.prompt_id,
                "prompt_version": self.prompt_version,
                "skill_ids": self.skill_ids,
                "source_refs": self.source_refs,
                "source_hashes": self.source_hashes,
                "system_prompt": self.system_prompt,
                "output_schema": _json_value(self.output_schema),
                "guardrails": self.guardrails,
                "default_text_role": self.default_text_role,
                "image_model_role": self.image_model_role,
                "allowed_model_names": self.allowed_model_names,
                **({"inherit_common_guardrails": False} if not self.inherit_common_guardrails else {}),
            }
        )

    def snapshot(self) -> dict[str, object]:
        return {
            "prompt_id": self.prompt_id,
            "prompt_version": self.prompt_version,
            "skill_ids": list(self.skill_ids),
            "source_refs": list(self.source_refs),
            "source_hashes": {key: value for key, value in self.source_hashes},
            "prompt_hash": self.prompt_hash,
            "output_schema": _json_value(self.output_schema),
            "default_text_role": self.default_text_role,
            "image_model_role": self.image_model_role,
            "allowed_model_names": list(self.allowed_model_names),
        }

    def build_messages(
        self,
        *,
        input_manifest: Mapping[str, object],
        task_context: Mapping[str, object],
    ) -> list[dict[str, object]]:
        """Build a JSON-only message envelope without storing raw prompt input."""

        system = self.system_prompt.strip()
        common_guardrails = COMMON_GUARDRAILS if self.inherit_common_guardrails else ()
        guardrails = "\n".join(f"- {rule}" for rule in (*self.guardrails, *common_guardrails))
        system_message = (
            f"{system}\n\nGuardrails:\n{guardrails}\n\n"
            "Return exactly one JSON object matching the supplied output schema."
        )
        user_payload = {
            "task_context": dict(task_context),
            "input_manifest": dict(input_manifest),
            "output_schema": _json_value(self.output_schema),
        }
        return [
            {"role": "system", "content": system_message},
            {
                "role": "user",
                "content": json.dumps(user_payload, ensure_ascii=False, sort_keys=True),
            },
        ]
