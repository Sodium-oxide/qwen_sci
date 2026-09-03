"""Shared response parsing helpers for Idea Agent LLM outputs."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, Dict


class JsonObjectResponseError(ValueError):
    """Raised when a structured stage did not return one JSON object."""


def _strip_json_fence(raw: str) -> str:
    text = (raw or "").strip()
    if text.startswith("```"):
        fence_end = text.find("\n")
        if fence_end != -1:
            text = text[fence_end + 1 :]
        if text.endswith("```"):
            text = text[: -3]
    return text.strip()


def parse_json_response(raw: str) -> Any:
    text = _strip_json_fence(raw)
    if not text:
        raise ValueError("Empty response")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        decoder = json.JSONDecoder()
        for idx, ch in enumerate(text):
            if ch in "{[":
                try:
                    parsed, _ = decoder.raw_decode(text[idx:])
                    return parsed
                except json.JSONDecodeError:
                    continue
    raise ValueError(f"Unable to parse JSON from response: {text[:200]}")


def parse_json_object_response(raw: str) -> Dict[str, Any]:
    """Parse exactly one top-level JSON object without permissive fragment recovery."""

    text = _strip_json_fence(raw)
    if not text:
        raise JsonObjectResponseError("advanced analysis response was empty; expected one JSON object")
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise JsonObjectResponseError(
            "advanced analysis response must be one complete JSON object without prose or JSON fragments"
        ) from exc
    if not isinstance(parsed, Mapping):
        raise JsonObjectResponseError("advanced analysis response must be a JSON object")
    return dict(parsed)
