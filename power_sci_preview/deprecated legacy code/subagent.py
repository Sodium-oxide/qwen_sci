from __future__ import annotations

from typing import Any

try:
    from .compact import compact_in_place, compact_messages
    from .config import SUB_MAX_TOKENS, SUB_MAX_TURNS
    from .hook import trigger_hook
    from .llm import get_client
    from .log import log_event
    from .recovery import RecoveryState, create_response_with_recovery
    from .skill import build_system
    from .task_system import strip_control_args
    from .tools import BASIC_TOOLS, COMPACT_TOOL, TOOL_HANDLERS
except ImportError:
    from compact import compact_in_place, compact_messages
    from config import SUB_MAX_TOKENS, SUB_MAX_TURNS
    from hook import trigger_hook
    from llm import get_client
    from log import log_event
    from recovery import RecoveryState, create_response_with_recovery
    from skill import build_system
    from task_system import strip_control_args
    from tools import BASIC_TOOLS, COMPACT_TOOL, TOOL_HANDLERS


SUB_TOOL_NAMES = {"bash", "read_file", "write_file", "edit_file", "glob", "compact"}


def spawn_subagent(description: str) -> str:
    client = get_client()
    recovery_state = RecoveryState(current_max_tokens=SUB_MAX_TOKENS)
    messages: list[dict[str, Any]] = [{"role": "user", "content": description}]
    last_response_content: list[Any] = []
    log_event("SUBAGENT", "start", chars=len(description))

    for turn in range(SUB_MAX_TURNS):
        messages[:] = compact_messages(messages)
        response = create_sub_response(client, description, messages, recovery_state)
        last_response_content = list(response.content)

        if response.stop_reason == "end_turn":
            summary = extract_summary(messages, response.content)
            log_event("SUBAGENT", "end", turn=turn + 1, chars=len(summary))
            return summary

        tool_blocks = [
            block for block in response.content if block_attr(block, "type") == "tool_use"
        ]
        if not tool_blocks:
            summary = extract_summary(messages, response.content)
            log_event("SUBAGENT", "end", turn=turn + 1, chars=len(summary))
            return summary

        messages.append(
            {
                "role": "assistant",
                "content": [block_to_dict(block) for block in response.content],
            }
        )
        messages.append(
            {
                "role": "user",
                "content": [run_sub_tool(block, messages) for block in tool_blocks],
            }
        )
        messages[:] = compact_messages(messages)

    summary = extract_summary(messages, last_response_content)
    log_event("WARN", "subagent_max_turns", turns=SUB_MAX_TURNS)
    return (
        f"[Sub-agent reached SUB_MAX_TURNS={SUB_MAX_TURNS}.]\n"
        f"{summary}"
    )


def create_sub_response(
    client: Any,
    description: str,
    messages: list[dict[str, Any]],
    recovery_state: RecoveryState,
) -> Any:
    return create_response_with_recovery(
        client,
        system=build_system(description, subagent=True),
        messages=messages,
        tools=sub_tools(),
        state=recovery_state,
        focus=description,
    )


def sub_tools() -> list[dict[str, Any]]:
    return [tool for tool in [*BASIC_TOOLS, COMPACT_TOOL] if tool["name"] in SUB_TOOL_NAMES]


def run_sub_tool(block: Any, messages: list[dict[str, Any]]) -> dict[str, Any]:
    name = normalize_tool_name(block_attr(block, "name"))
    tool_input = block_attr(block, "input", {}) or {}
    tool_use_id = block_attr(block, "id")

    if name not in SUB_TOOL_NAMES:
        return tool_result(tool_use_id, f"BLOCKED: sub-agent cannot use tool {name}", True)

    blocked = trigger_hook("PreToolUse", block)
    if blocked is not None:
        return tool_result(tool_use_id, blocked, True)

    try:
        if name == "compact":
            focus = str(tool_input.get("focus", ""))
            compact_in_place(messages, focus=focus, force_l0=False)
            output = "Context compacted."
        else:
            output = TOOL_HANDLERS[name](**strip_control_args(tool_input))
    except Exception as exc:
        output = f"ERROR: {exc}"
        trigger_hook("PostToolUse", block, output)
        return tool_result(tool_use_id, output, True)

    trigger_hook("PostToolUse", block, output)
    return tool_result(tool_use_id, output)


def normalize_tool_name(name: Any) -> str:
    raw = str(name)
    aliases = {
        "bash": "bash",
        "read": "read_file",
        "readfile": "read_file",
        "read_file": "read_file",
        "write": "write_file",
        "writefile": "write_file",
        "write_file": "write_file",
        "edit": "edit_file",
        "editfile": "edit_file",
        "edit_file": "edit_file",
        "glob": "glob",
        "compact": "compact",
    }
    key = raw.replace("-", "_").replace(" ", "_").lower()
    compact_key = key.replace("_", "")
    return aliases.get(key) or aliases.get(compact_key) or key


def extract_summary(messages: list[dict[str, Any]], latest_content: list[Any]) -> str:
    latest_text = response_text(latest_content)
    if latest_text:
        return latest_text

    for message in reversed(messages):
        if message.get("role") != "assistant":
            continue
        text = response_text(message_content(message))
        if text:
            return text

    return "[Sub-agent did not produce a text response]"


def message_content(message: dict[str, Any]) -> list[Any]:
    content = message.get("content", [])
    if isinstance(content, list):
        return content
    return [{"type": "text", "text": str(content)}]


def block_to_dict(block: Any) -> dict[str, Any]:
    if isinstance(block, dict):
        return block
    if hasattr(block, "model_dump"):
        return block.model_dump(exclude_none=True)
    if hasattr(block, "dict"):
        return block.dict(exclude_none=True)
    raise TypeError(f"Unsupported response block: {type(block)!r}")


def block_attr(block: Any, name: str, default: Any = None) -> Any:
    if isinstance(block, dict):
        return block.get(name, default)
    return getattr(block, name, default)


def response_text(content: list[Any]) -> str:
    parts: list[str] = []
    for block in content:
        if block_attr(block, "type") == "text":
            parts.append(block_attr(block, "text", ""))
    return "\n".join(part for part in parts if part)


def tool_result(tool_use_id: str, output: str, is_error: bool = False) -> dict[str, Any]:
    result: dict[str, Any] = {
        "type": "tool_result",
        "tool_use_id": tool_use_id,
        "content": output,
    }
    if is_error:
        result["is_error"] = True
    return result
