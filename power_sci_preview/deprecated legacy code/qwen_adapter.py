from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any

try:
    from ._science_routing import science_workflow_requested
except ImportError:  # pragma: no cover - direct module execution compatibility
    from _science_routing import science_workflow_requested


DASHSCOPE_INPUT_LIMIT = 30_720
DASHSCOPE_SAFE_INPUT_UNITS = 25_000
DASHSCOPE_FULL_TOOL_CONTEXT_UNITS = 6_000

RESEARCH_CONTEXT_MARKERS = (
    "create_research_project",
    "boxue",
    "zhizhi",
    "tanxi",
    "socrates",
    "mingli",
    "yanzhen",
    "duzhi",
    "bianlun",
    "research brief",
    "research project",
    "research objective",
    "scientific hypothesis",
    "literature search",
    "knowledge gap",
    "文献检索",
    "科研闭环",
    "科研流程",
    "研究目标",
    "学术文段",
    "知识缺口",
)

RESEARCH_WORKFLOW_TOOL_NAMES = (
    "create_research_project",
    "list_research_projects",
    "get_research_project",
    "run_autogen_groupchat",
)

GENERAL_BOOTSTRAP_TOOL_NAMES = (
    # These two tools must survive contextual compaction even when a
    # domain-neutral science classifier misses an unfamiliar discipline.
    "create_research_project",
    "run_autogen_groupchat",
    "bash",
    "read_file",
    "write_file",
    "edit_file",
    "glob",
    "todo_write",
    "load_skill",
    "compact",
    "create_task",
    "list_tasks",
    "get_task",
)


@dataclass
class QwenResponse:
    content: list[dict[str, Any]]
    stop_reason: str | None = None
    provider_code: str | None = None
    request_id: str | None = None
    status_code: str | None = None
    requires_tool_json_retry: bool = False
    tool_call_diagnostics: list[dict[str, Any]] = field(default_factory=list)


class QwenMessages:
    def __init__(self, api_key: str, default_model: str, api_base: str = "") -> None:
        self.api_key = api_key
        self.default_model = self._qwen_model_or_default(default_model)
        self.api_base = api_base

    def create(
        self,
        *,
        model: str | None = None,
        max_tokens: int | None = None,
        system: str = "",
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        request_timeout: float | tuple[float, float] | None = None,
        **_: Any,
    ) -> QwenResponse:
        try:
            import dashscope
            from dashscope import Generation
        except ImportError as exc:
            raise RuntimeError("The dashscope package is not installed. Run: pip install dashscope") from exc

        if self.api_base:
            dashscope.base_http_api_url = self.api_base
        qwen_messages, request_tools, request_budget = prepare_qwen_request(
            system,
            messages,
            tools or [],
        )
        kwargs: dict[str, Any] = {
            "model": self.effective_model(model),
            "messages": qwen_messages,
            "result_format": "message",
            "api_key": self.api_key,
        }
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        if request_timeout is not None:
            if isinstance(request_timeout, tuple):
                connect_timeout, read_timeout = request_timeout
                kwargs["request_timeout"] = (
                    max(1.0, float(connect_timeout)),
                    max(1.0, float(read_timeout)),
                )
            else:
                kwargs["request_timeout"] = max(1.0, float(request_timeout))

        response = Generation.call(**kwargs)
        ensure_success(response)
        stop_reason = qwen_finish_reason(response)
        provider_code = str(response_value(response, "code") or "") or None
        request_id = str(response_value(response, "request_id") or "") or None
        status_code = str(response_value(response, "status_code") or "") or None
        native_tool_calls = extract_qwen_native_tool_calls(response)
        if native_tool_calls:
            content, diagnostics = parse_qwen_content_with_diagnostics(
                json.dumps(
                    {"tool_calls": native_tool_calls},
                    ensure_ascii=False,
                ),
                request_tools,
            )
            return QwenResponse(
                content=content,
                stop_reason=stop_reason,
                provider_code=provider_code,
                request_id=request_id,
                status_code=status_code,
                tool_call_diagnostics=diagnostics,
            )
        text = extract_qwen_text(response)
        if is_incomplete_tool_json(text):
            return QwenResponse(
                content=[],
                stop_reason=stop_reason,
                provider_code=provider_code,
                request_id=request_id,
                status_code=status_code,
                requires_tool_json_retry=True,
            )
        content, diagnostics = parse_qwen_content_with_diagnostics(text, request_tools)
        return QwenResponse(
            content=content,
            stop_reason=stop_reason,
            provider_code=provider_code,
            request_id=request_id,
            status_code=status_code,
            tool_call_diagnostics=diagnostics,
        )

    def effective_model(self, requested: str | None) -> str:
        value = str(requested or "").strip()
        if not value:
            return self.default_model
        return self._qwen_model_or_default(value, fallback=self.default_model)

    @staticmethod
    def _qwen_model_or_default(value: str | None, *, fallback: str = "qwen-plus") -> str:
        model = str(value or "").strip()
        if model.lower().startswith("qwen"):
            return model
        return fallback


class QwenClient:
    def __init__(self, api_key: str, model: str = "qwen-plus", api_base: str = "") -> None:
        if not api_key:
            raise RuntimeError("Qwen API key is not set. Set QWEN_API_KEY or DASHSCOPE_API_KEY.")
        self.messages = QwenMessages(api_key=api_key, default_model=model, api_base=api_base)


def to_qwen_messages(
    system: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    *,
    compact_tool_catalog: bool = False,
) -> list[dict[str, str]]:
    rendered: list[dict[str, str]] = []
    full_system = system
    if tools:
        full_system += "\n\n" + tool_protocol_prompt(tools, compact=compact_tool_catalog)
    if full_system.strip():
        rendered.append({"role": "system", "content": full_system.strip()})

    for message in messages:
        role = str(message.get("role", "user"))
        if role not in {"system", "user", "assistant"}:
            role = "user"
        rendered.append({"role": role, "content": render_content(message.get("content", ""))})
    return rendered


def tool_protocol_prompt(tools: list[dict[str, Any]], *, compact: bool = False) -> str:
    if compact:
        catalog = compact_tool_catalog(tools)
        catalog_label = "Available tools (schema summaries)"
    else:
        catalog = [transport_tool_definition(tool) for tool in tools]
        catalog_label = "Available tools"
    return (
        "You have access to tools. When you need tools, respond with JSON only, "
        "with no markdown and no surrounding explanation:\n"
        "{\"tool_uses\":[{\"name\":\"tool_name\",\"input\":{}}]}\n"
        "Call exactly one tool per response. Wait for its result before selecting the next tool. "
        "Use exact tool names and JSON inputs matching the schemas. If you call create_research_project, never include "
        "research_brief: the runtime injects the complete original user prompt automatically. "
        "If you are done, answer normally in text.\n\n"
        f"{catalog_label}:\n{json.dumps(catalog, ensure_ascii=False, separators=(',', ':'))}"
    )


def transport_tool_description(tool: dict[str, Any]) -> str:
    description = str(tool.get("description", ""))
    if str(tool.get("name", "")) == "create_research_project":
        return description + " The runtime preserves the complete original task automatically; omit research_brief."
    return description


def transport_tool_definition(tool: dict[str, Any]) -> dict[str, Any]:
    schema = tool.get("input_schema") if isinstance(tool.get("input_schema"), dict) else {}
    properties = schema.get("properties") if isinstance(schema, dict) else {}
    sanitized_schema = dict(schema)
    if isinstance(properties, dict):
        sanitized_schema["properties"] = {
            str(name): spec
            for name, spec in properties.items()
            if not (str(tool.get("name", "")) == "create_research_project" and str(name) == "research_brief")
        }
    return {
        "name": tool.get("name"),
        "description": transport_tool_description(tool),
        "input_schema": sanitized_schema,
    }


def compact_tool_catalog(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    catalog: list[dict[str, Any]] = []
    for tool in tools:
        schema = tool.get("input_schema") or {}
        properties = schema.get("properties") if isinstance(schema, dict) else {}
        summarized_properties: dict[str, str] = {}
        if isinstance(properties, dict):
            for name, spec in properties.items():
                if str(tool.get("name", "")) == "create_research_project" and str(name) == "research_brief":
                    continue
                if isinstance(spec, dict):
                    summarized_properties[str(name)] = str(spec.get("type") or "value")
                else:
                    summarized_properties[str(name)] = "value"
        entry: dict[str, Any] = {
            "name": tool.get("name"),
            "description": transport_tool_description(tool),
            "parameters": summarized_properties,
        }
        required = schema.get("required") if isinstance(schema, dict) else []
        if isinstance(required, list) and required:
            entry["required"] = required
        catalog.append(entry)
    return catalog


def prepare_qwen_request(
    system: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
) -> tuple[list[dict[str, str]], list[dict[str, Any]], dict[str, Any]]:
    full_messages = to_qwen_messages(system, messages, tools)
    full_units = estimate_qwen_messages_units(full_messages)
    conversation_units = estimate_qwen_messages_units(
        [message for message in full_messages if message.get("role") != "system"]
    )
    if (
        full_units <= DASHSCOPE_SAFE_INPUT_UNITS
        and conversation_units <= DASHSCOPE_FULL_TOOL_CONTEXT_UNITS
    ):
        return full_messages, tools, {
            "estimated_input_units": full_units,
            "tool_mode": "full",
            "messages_compacted_for_transport": False,
        }

    selected_tools = select_context_tools(messages, tools)
    compact_messages = to_qwen_messages(
        system,
        messages,
        selected_tools,
        compact_tool_catalog=True,
    )
    compact_units = estimate_qwen_messages_units(compact_messages)
    if compact_units <= DASHSCOPE_SAFE_INPUT_UNITS:
        return compact_messages, selected_tools, {
            "estimated_input_units": compact_units,
            "tool_mode": "contextual_compact",
            "messages_compacted_for_transport": False,
        }

    fitted_messages = fit_messages_to_budget(
        compact_messages,
        DASHSCOPE_SAFE_INPUT_UNITS,
    )
    return fitted_messages, selected_tools, {
        "estimated_input_units": estimate_qwen_messages_units(fitted_messages),
        "tool_mode": "contextual_compact",
        "messages_compacted_for_transport": True,
    }


def select_context_tools(
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    raw_context = "\n".join(render_content(message.get("content", "")) for message in messages)
    context = raw_context.lower()
    is_research_context = science_workflow_requested(raw_context) or any(
        marker in context for marker in RESEARCH_CONTEXT_MARKERS
    )
    preferred_names = (
        RESEARCH_WORKFLOW_TOOL_NAMES
        if is_research_context
        else GENERAL_BOOTSTRAP_TOOL_NAMES
    )
    by_name = {str(tool.get("name", "")): tool for tool in tools}
    selected = [by_name[name] for name in preferred_names if name in by_name]
    return selected or tools[: min(12, len(tools))]


def estimate_qwen_text_units(text: str) -> int:
    cjk_or_fullwidth = sum(1 for char in text if ord(char) >= 0x2E80)
    other = len(text) - cjk_or_fullwidth
    return cjk_or_fullwidth + (other + 3) // 4


def estimate_qwen_messages_units(messages: list[dict[str, str]]) -> int:
    return sum(estimate_qwen_text_units(str(message.get("content", ""))) + 8 for message in messages)


def fit_messages_to_budget(
    messages: list[dict[str, str]],
    budget_units: int,
) -> list[dict[str, str]]:
    if estimate_qwen_messages_units(messages) <= budget_units:
        return messages

    system_messages = [message for message in messages if message.get("role") == "system"]
    conversation_messages = [message for message in messages if message.get("role") != "system"]
    system_units = estimate_qwen_messages_units(system_messages)
    available_units = max(1_200, budget_units - system_units - 8 * len(conversation_messages))
    retained: list[dict[str, str]] = []
    total_messages = max(1, len(conversation_messages))

    for index, message in enumerate(conversation_messages):
        weight = 2 if index in {0, total_messages - 1} else 1
        allocation = max(320, available_units * weight // (total_messages + 2))
        content = str(message.get("content", ""))
        retained.append({"role": str(message.get("role", "user")), "content": clip_text_to_units(content, allocation)})

    fitted = system_messages + retained
    overflow = estimate_qwen_messages_units(fitted) - budget_units
    if overflow <= 0:
        return fitted

    for index in range(len(retained) - 1, -1, -1):
        content = retained[index]["content"]
        current_units = estimate_qwen_text_units(content)
        target_units = max(160, current_units - overflow - 16)
        retained[index]["content"] = clip_text_to_units(content, target_units)
        fitted = system_messages + retained
        overflow = estimate_qwen_messages_units(fitted) - budget_units
        if overflow <= 0:
            break

    if overflow > 0 and system_messages:
        content = system_messages[-1]["content"]
        target_units = max(400, estimate_qwen_text_units(content) - overflow - 16)
        system_messages[-1] = {
            "role": "system",
            "content": clip_text_to_units(content, target_units),
        }
        fitted = system_messages + retained
    return fitted


def clip_text_to_units(text: str, budget_units: int) -> str:
    if estimate_qwen_text_units(text) <= budget_units:
        return text

    marker = "\n...[transport preview; original message retained by runtime]...\n"
    marker_units = estimate_qwen_text_units(marker)
    usable_units = max(1, budget_units - marker_units)
    prefix = take_text_units(text, usable_units * 2 // 3)
    suffix = take_text_units(text[::-1], usable_units - estimate_qwen_text_units(prefix))[::-1]
    return prefix + marker + suffix


def take_text_units(text: str, budget_units: int) -> str:
    consumed = 0
    end = 0
    for end, char in enumerate(text, start=1):
        char_units = 1 if ord(char) >= 0x2E80 else 1 / 4
        if consumed + char_units > budget_units:
            return text[: end - 1]
        consumed += char_units
    return text


def render_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return str(content)

    chunks: list[str] = []
    for block in content:
        if not isinstance(block, dict):
            chunks.append(str(block))
            continue
        block_type = block.get("type")
        if block_type == "text":
            chunks.append(str(block.get("text", "")))
        elif block_type == "tool_use":
            chunks.append(
                "[assistant requested tool]\n"
                + json.dumps(
                    {
                        "id": block.get("id"),
                        "name": block.get("name"),
                        "input": block.get("input", {}),
                    },
                    ensure_ascii=False,
                )
            )
        elif block_type == "tool_result":
            chunks.append(
                "[tool result]\n"
                + json.dumps(
                    {
                        "tool_use_id": block.get("tool_use_id"),
                        "is_error": bool(block.get("is_error", False)),
                        "content": block.get("content", ""),
                    },
                    ensure_ascii=False,
                )
            )
        else:
            chunks.append(json.dumps(block, ensure_ascii=False))
    return "\n\n".join(part for part in chunks if part)


def extract_qwen_text(response: Any) -> str:
    try:
        return str(response.output.choices[0].message.content or "")
    except Exception:
        pass
    if isinstance(response, dict):
        try:
            return str(response["output"]["choices"][0]["message"]["content"] or "")
        except Exception:
            pass
    return str(response)


def extract_qwen_native_tool_calls(response: Any) -> list[dict[str, Any]]:
    try:
        tool_calls = response.output.choices[0].message.tool_calls
    except Exception:
        tool_calls = None
    if tool_calls is None and isinstance(response, dict):
        try:
            tool_calls = response["output"]["choices"][0]["message"].get("tool_calls")
        except Exception:
            tool_calls = None
    if not isinstance(tool_calls, list):
        return []

    normalized: list[dict[str, Any]] = []
    for tool_call in tool_calls:
        if isinstance(tool_call, dict):
            normalized.append(tool_call)
            continue
        if hasattr(tool_call, "model_dump"):
            dumped = tool_call.model_dump(exclude_none=True)
            if isinstance(dumped, dict):
                normalized.append(dumped)
                continue
        if hasattr(tool_call, "dict"):
            dumped = tool_call.dict(exclude_none=True)
            if isinstance(dumped, dict):
                normalized.append(dumped)
                continue
        function = getattr(tool_call, "function", None)
        if function is None:
            continue
        normalized.append(
            {
                "id": getattr(tool_call, "id", None),
                "type": getattr(tool_call, "type", "function"),
                "function": {
                    "name": getattr(function, "name", ""),
                    "arguments": getattr(function, "arguments", {}),
                },
            }
        )
    return normalized


def ensure_success(response: Any) -> None:
    status_code = response_value(response, "status_code")
    if status_code in {None, "", 200, "200"}:
        return
    code = response_value(response, "code")
    message = response_value(response, "message")
    request_id = response_value(response, "request_id")
    raise RuntimeError(
        "DashScope call failed: "
        f"status_code={status_code}, code={code or '(none)'}, "
        f"message={message or '(none)'}, request_id={request_id or '(none)'}"
    )


def response_value(response: Any, name: str) -> Any:
    if isinstance(response, dict):
        return response.get(name)
    return getattr(response, name, None)


def qwen_finish_reason(response: Any) -> str | None:
    for field in ("finish_reason", "stop_reason", "finishReason", "stopReason"):
        value = response_value(response, field)
        if value:
            return str(value)
    output = response_value(response, "output")
    if isinstance(output, dict):
        for field in ("finish_reason", "stop_reason"):
            if output.get(field):
                return str(output[field])
        choices = output.get("choices")
        if isinstance(choices, list):
            for choice in choices:
                if isinstance(choice, dict):
                    for field in ("finish_reason", "stop_reason"):
                        if choice.get(field):
                            return str(choice[field])
    return None


def parse_qwen_content(text: str, tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    content, _ = parse_qwen_content_with_diagnostics(text, tools)
    return content


def parse_qwen_content_with_diagnostics(
    text: str,
    tools: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    tool_names = {str(tool.get("name", "")) for tool in tools}
    blocks: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []
    seen_calls: set[str] = set()
    block_index = 0
    for payload in parse_json_objects(text):
        tool_uses, normalization_diagnostics = normalize_tool_uses_with_diagnostics(payload)
        diagnostics.extend(normalization_diagnostics)
        for item in tool_uses:
            name = str(item.get("name", "")).strip()
            if not name:
                diagnostics.append({"reason": "MISSING_TOOL_NAME"})
                continue
            if tool_names and name not in tool_names:
                diagnostics.append(
                    {
                        "reason": "TOOL_NOT_AVAILABLE_IN_CURRENT_STAGE",
                        "requested_tool": name,
                        "allowed_tools": sorted(tool_names),
                    }
                )
                continue
            tool_input = item.get("input", {})
            if not isinstance(tool_input, dict):
                diagnostics.append(
                    {
                        "reason": "TOOL_INPUT_MUST_BE_OBJECT",
                        "requested_tool": name,
                    }
                )
                continue
            supplied_id = str(item.get("id") or "").strip()
            try:
                signature = supplied_id or f"{name}:{json.dumps(tool_input, ensure_ascii=False, sort_keys=True)}"
            except (TypeError, ValueError):
                signature = supplied_id or f"{name}:{tool_input!r}"
            if signature in seen_calls:
                continue
            seen_calls.add(signature)
            blocks.append(
                {
                    "type": "tool_use",
                    "id": supplied_id or f"toolu_qwen_{int(time.time() * 1000)}_{block_index}",
                    "name": name,
                    "input": tool_input,
                }
            )
            block_index += 1
    if blocks:
        return blocks, diagnostics
    return [{"type": "text", "text": text}], diagnostics


def is_incomplete_tool_json(text: str) -> bool:
    source = str(text or "").strip()
    tool_markers = ('"tool_uses"', '"tool_calls"', '"tools"')
    if not source or not any(marker in source for marker in tool_markers):
        return False
    return not bool(parse_json_object(source))


def normalize_tool_uses(payload: dict[str, Any]) -> list[dict[str, Any]]:
    tool_uses, _ = normalize_tool_uses_with_diagnostics(payload)
    return tool_uses


def normalize_tool_uses_with_diagnostics(
    payload: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    raw_items: list[dict[str, Any]] | None = None
    value = payload.get("tool_uses") or payload.get("tools") or payload.get("tool_calls")
    if isinstance(value, list):
        raw_items = [item for item in value if isinstance(item, dict)]
    elif value is not None:
        return [], [{"reason": "TOOL_CALL_COLLECTION_MUST_BE_ARRAY"}]
    elif "name" in payload and ("input" in payload or "arguments" in payload):
        raw_items = [payload]
    if "tool" in payload:
        raw_items = [
            {
                "name": payload.get("tool"),
                "input": payload.get("input", payload.get("arguments", {})),
            }
        ]
    elif raw_items is None:
        return [], []

    normalized: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []
    for item in raw_items:
        function = item.get("function")
        if isinstance(function, dict):
            name = str(function.get("name") or item.get("name") or "").strip()
            tool_input, error = normalize_tool_input(function.get("arguments", {}))
        else:
            name = str(item.get("name") or item.get("tool") or "").strip()
            tool_input, error = normalize_tool_input(
                item.get("input", item.get("arguments", {}))
            )
        if error:
            diagnostics.append(
                {
                    "reason": error,
                    "requested_tool": name,
                }
            )
            continue
        normalized.append(
            {
                "id": item.get("id"),
                "name": name,
                "input": tool_input,
            }
        )
    return normalized, diagnostics


def normalize_tool_input(value: Any) -> tuple[dict[str, Any], str]:
    if value is None or value == "":
        return {}, ""
    if isinstance(value, dict):
        return value, ""
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}, "TOOL_ARGUMENTS_JSON_INVALID"
        if isinstance(parsed, dict):
            return parsed, ""
    return {}, "TOOL_INPUT_MUST_BE_OBJECT"


def parse_json_object(text: str) -> dict[str, Any]:
    payloads = parse_json_objects(text)
    return payloads[0] if payloads else {}


def parse_json_objects(text: str) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    seen: set[str] = set()
    for candidate in json_candidates(text):
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if not isinstance(parsed, dict):
            continue
        try:
            signature = json.dumps(parsed, ensure_ascii=False, sort_keys=True)
        except (TypeError, ValueError):
            signature = repr(parsed)
        if signature in seen:
            continue
        seen.add(signature)
        payloads.append(parsed)
    return payloads


def json_candidates(text: str) -> list[str]:
    stripped = text.strip()
    candidates: list[str] = []
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if len(lines) >= 3 and lines[-1].strip().startswith("```"):
            candidates.append("\n".join(lines[1:-1]).strip())

    candidates.extend(balanced_json_objects(stripped))

    start = stripped.find("{")
    end = stripped.rfind("}")
    if start != -1 and end >= start:
        candidates.append(stripped[start : end + 1])

    deduped: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        normalized = candidate.strip()
        if normalized and normalized not in seen:
            deduped.append(normalized)
            seen.add(normalized)
    return deduped


def balanced_json_objects(text: str) -> list[str]:
    """Return every top-level balanced JSON object embedded in model text."""
    objects: list[str] = []
    start = -1
    depth = 0
    in_string = False
    escaped = False
    for index, char in enumerate(text):
        if start < 0:
            if char == "{":
                start = index
                depth = 1
                in_string = False
                escaped = False
            continue
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                objects.append(text[start : index + 1])
                start = -1
    return objects


def first_balanced_json_object(text: str) -> str:
    start = text.find("{")
    if start == -1:
        return ""
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    return ""
