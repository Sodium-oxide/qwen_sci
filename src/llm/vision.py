"""Provider-aware vision helpers for Qwen-compatible multimodal models."""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from typing import Any, Mapping, Optional

from openai import OpenAI

from src.llm.provider_registry import require_model_capabilities, resolve_model, resolve_provider
from src.llm.structured_output import parse_and_validate


@dataclass(frozen=True)
class VisionReviewResult:
    problematic_indices: tuple[int, ...]
    notes: tuple[str, ...]
    raw_text: str
    model: str
    provider: str


class QwenVisionClient:
    """Call Qwen VL models through the DashScope OpenAI-compatible endpoint."""

    def __init__(
        self,
        *,
        model: str = "qwen3-vl-plus",
        provider: str = "qwen",
        api_key: str = "",
        base_url: str = "",
        timeout: float = 120.0,
        client: Optional[OpenAI] = None,
        config: Any = None,
    ) -> None:
        if config is None:
            from src.config import get_config

            config = get_config()
        self.model_spec = require_model_capabilities(
            resolve_model(config, model, provider),
            ("chat_completions", "vision"),
            "Qwen vision client",
        )
        self.provider = resolve_provider(config, self.model_spec.provider)
        self.client = client or OpenAI(
            api_key=api_key or self.provider.api_key,
            base_url=base_url or self.provider.base_url,
            timeout=timeout,
        )

    def describe(
        self,
        image_bytes: bytes,
        *,
        prompt: str,
        media_type: str = "image/png",
        max_tokens: int = 2048,
        response_format: Optional[Mapping[str, Any]] = None,
    ) -> str:
        encoded = base64.b64encode(image_bytes).decode("ascii")
        payload: dict[str, Any] = {
            "model": self.model_spec.name,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:{media_type};base64,{encoded}"},
                        },
                    ],
                }
            ],
            "max_tokens": max(1, min(int(max_tokens), self.model_spec.max_output_tokens)),
            "temperature": 0.0,
        }
        if response_format:
            payload["response_format"] = dict(response_format)
        response = self.client.chat.completions.create(**payload)
        message = response.choices[0].message
        content = message.get("content") if isinstance(message, dict) else message.content
        if isinstance(content, list):
            text = "".join(
                str(part.get("text") or "")
                for part in content
                if isinstance(part, Mapping)
            ).strip()
        else:
            text = str(content or "").strip()
        if not text:
            raise RuntimeError("Qwen vision model returned empty content.")
        return text

    def review_ocr_labels(
        self,
        image_bytes: bytes,
        labels: list[str],
        *,
        media_type: str = "image/png",
        max_tokens: int = 2048,
    ) -> VisionReviewResult:
        schema = {
            "type": "object",
            "properties": {
                "problematic_indices": {
                    "type": "array",
                    "items": {"type": "integer"},
                },
                "notes": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["problematic_indices", "notes"],
            "additionalProperties": False,
        }
        label_block = "\n".join(f"{index}: {label}" for index, label in enumerate(labels))
        prompt = (
            "Review the scientific figure and the OCR labels below. Identify only obvious spelling, "
            "OCR, missing-label, or semantic-label errors. Preserve technical identifiers, variables, "
            "equations, and acronyms. Return one JSON object with problematic_indices and notes.\n\n"
            f"OCR labels:\n{label_block}\n\nJSON schema:\n"
            f"{json.dumps(schema, ensure_ascii=False, sort_keys=True)}"
        )
        raw = self.describe(
            image_bytes,
            prompt=prompt,
            media_type=media_type,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
        )
        parsed = parse_and_validate(raw, schema)
        indices = tuple(
            sorted(
                {
                    int(index)
                    for index in parsed["problematic_indices"]
                    if 0 <= int(index) < len(labels)
                }
            )
        )
        return VisionReviewResult(
            problematic_indices=indices,
            notes=tuple(str(note) for note in parsed["notes"]),
            raw_text=raw,
            model=self.model_spec.name,
            provider=self.provider.name,
        )

    def describe_json(
        self,
        image_bytes: bytes,
        *,
        prompt: str,
        schema: Mapping[str, Any],
        media_type: str = "image/png",
        max_tokens: int = 2048,
    ) -> dict[str, Any]:
        """Describe one prepared image and validate the provider's JSON object."""

        raw = self.describe(
            image_bytes,
            prompt=prompt,
            media_type=media_type,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
        )
        parsed = parse_and_validate(raw, dict(schema))
        if not isinstance(parsed, Mapping):
            raise RuntimeError("Qwen vision model did not return a JSON object.")
        return dict(parsed)


def resolve_vision_settings(config: Any, *, batch: bool = False) -> dict[str, Any]:
    vision = config.get("vision", {}) if hasattr(config, "get") else {}
    provider_name = str(vision.get("provider") or "qwen").strip().lower()
    if provider_name == "dashscope":
        provider_name = "qwen"
    provider = resolve_provider(config, provider_name)
    model = str(
        vision.get("batch_model" if batch else "quality_model")
        or ("qwen3-vl-flash" if batch else "qwen3-vl-plus")
    ).strip()
    require_model_capabilities(
        resolve_model(config, model, provider.name),
        ("chat_completions", "vision"),
        "Vision settings",
    )
    return {
        "provider": provider.name,
        "model": model,
        "api_key": str(vision.get("api_key") or provider.api_key).strip(),
        "base_url": str(vision.get("base_url") or provider.base_url).strip(),
        "timeout": float(vision.get("timeout_seconds") or 120),
        "max_tokens": int(vision.get("max_tokens") or 2048),
    }
