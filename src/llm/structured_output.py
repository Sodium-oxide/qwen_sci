"""Local structured-output parsing and validation for model responses."""

from __future__ import annotations

import json
from typing import Any, Mapping


class StructuredOutputError(ValueError):
    """Raised when an LLM response cannot satisfy a local JSON contract."""


def extract_json_value(value: Any) -> Any:
    """Extract the first complete JSON object or array from model output."""
    if isinstance(value, (dict, list)):
        return value
    text = str(value or "").strip()
    if not text:
        raise StructuredOutputError("Model returned empty structured output.")
    text = text.replace("<think>", "").replace("</think>", "").strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    for start, char in enumerate(text):
        if char not in "[{":
            continue
        closing = "]" if char == "[" else "}"
        depth = 0
        in_string = False
        escaped = False
        for index in range(start, len(text)):
            current = text[index]
            if in_string:
                if escaped:
                    escaped = False
                elif current == "\\":
                    escaped = True
                elif current == '"':
                    in_string = False
                continue
            if current == '"':
                in_string = True
            elif current in "[{":
                depth += 1
            elif current in "]}":
                depth -= 1
                if depth == 0:
                    candidate = text[start : index + 1]
                    try:
                        return json.loads(candidate)
                    except json.JSONDecodeError:
                        break
                if current == closing and depth < 0:
                    break
    raise StructuredOutputError("No complete JSON object or array found in model output.")


def validate_json_value(value: Any, schema: Mapping[str, Any], path: str = "$") -> None:
    """Validate the JSON-schema subset used by Xcientist memory payloads."""
    expected_type = schema.get("type")
    if expected_type == "object":
        if not isinstance(value, dict):
            raise StructuredOutputError(f"{path} must be an object.")
        required = schema.get("required") or []
        missing = [key for key in required if key not in value]
        if missing:
            raise StructuredOutputError(f"{path} is missing required fields: {', '.join(missing)}")
        properties = schema.get("properties") or {}
        if schema.get("additionalProperties") is False:
            unknown = sorted(set(value) - set(properties))
            if unknown:
                raise StructuredOutputError(f"{path} contains unsupported fields: {', '.join(unknown)}")
        for key, child_schema in properties.items():
            if key in value and isinstance(child_schema, Mapping):
                validate_json_value(value[key], child_schema, f"{path}.{key}")
    elif expected_type == "array":
        if not isinstance(value, list):
            raise StructuredOutputError(f"{path} must be an array.")
        if "minItems" in schema and len(value) < int(schema["minItems"]):
            raise StructuredOutputError(f"{path} must contain at least {schema['minItems']} items.")
        if "maxItems" in schema and len(value) > int(schema["maxItems"]):
            raise StructuredOutputError(f"{path} must contain at most {schema['maxItems']} items.")
        item_schema = schema.get("items")
        if isinstance(item_schema, Mapping):
            for index, item in enumerate(value):
                validate_json_value(item, item_schema, f"{path}[{index}]")
    elif expected_type == "string":
        if not isinstance(value, str):
            raise StructuredOutputError(f"{path} must be a string.")
        if "minLength" in schema and len(value) < int(schema["minLength"]):
            raise StructuredOutputError(f"{path} must not be empty.")
        if "maxLength" in schema and len(value) > int(schema["maxLength"]):
            raise StructuredOutputError(f"{path} exceeds the maximum length.")
    elif expected_type == "integer":
        if not isinstance(value, int) or isinstance(value, bool):
            raise StructuredOutputError(f"{path} must be an integer.")
    elif expected_type == "number":
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise StructuredOutputError(f"{path} must be a number.")
    elif expected_type == "boolean" and not isinstance(value, bool):
        raise StructuredOutputError(f"{path} must be a boolean.")
    elif expected_type == "null" and value is not None:
        raise StructuredOutputError(f"{path} must be null.")

    if "enum" in schema and value not in schema["enum"]:
        raise StructuredOutputError(f"{path} must be one of: {', '.join(map(str, schema['enum']))}.")


def parse_and_validate(value: Any, schema: Mapping[str, Any]) -> Any:
    """Parse model output and enforce its local schema before persistence."""
    parsed = extract_json_value(value)
    validate_json_value(parsed, schema)
    return parsed


def schema_repair_prompt(schema: Mapping[str, Any], error: Exception) -> str:
    """Build a deterministic one-shot repair suffix for invalid model output."""
    return (
        "Your previous response failed local validation. Return only one JSON value, "
        "without Markdown fences or explanations. Fix this validation error: "
        f"{error}\nJSON schema:\n{json.dumps(schema, ensure_ascii=False, sort_keys=True)}"
    )
