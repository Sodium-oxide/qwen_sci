from __future__ import annotations

import json
import time
from copy import deepcopy
from pathlib import Path
from typing import Any

try:
    from .config import (
        EMERGENCY_KEEP_MESSAGES,
        L0_SERIALIZED_LIMIT,
        L0_SUMMARY_TOKENS,
        L1_COMPACT_TRIGGER_MESSAGES,
        L1_KEEP_HEAD,
        L1_KEEP_TAIL,
        L1_MAX_MESSAGES,
        L2_KEEP_TOOL_RESULTS,
        L3_SNIPPET_CHARS,
        L3_TOOL_RESULT_BUDGET,
        MODEL_ID,
        TOOL_RESULTS_DIR,
        TRANSCRIPTS_DIR,
    )
    from .llm import get_client
    from .log import log_event
except ImportError:
    from config import (
        EMERGENCY_KEEP_MESSAGES,
        L0_SERIALIZED_LIMIT,
        L0_SUMMARY_TOKENS,
        L1_COMPACT_TRIGGER_MESSAGES,
        L1_KEEP_HEAD,
        L1_KEEP_TAIL,
        L1_MAX_MESSAGES,
        L2_KEEP_TOOL_RESULTS,
        L3_SNIPPET_CHARS,
        L3_TOOL_RESULT_BUDGET,
        MODEL_ID,
        TOOL_RESULTS_DIR,
        TRANSCRIPTS_DIR,
    )
    from llm import get_client
    from log import log_event


def compact_messages(
    messages: list[dict[str, Any]],
    *,
    focus: str = "",
    force_l0: bool = False,
) -> list[dict[str, Any]]:
    compacted = deepcopy(messages)
    compacted = tool_result_budget(compacted)
    compacted = snip_compact(compacted)
    compacted = micro_compact(compacted)
    compacted = normalize_messages(compacted)

    if force_l0 or serialized_len(compacted) > L0_SERIALIZED_LIMIT:
        try:
            compacted = compact_history(compacted, focus=focus)
        except Exception as exc:
            log_event("ERROR", "l0_failed", error=exc)
            compacted = local_fallback_compact(
                compacted,
                reason="manual compact failed" if force_l0 else "serialized history too large",
            )

    return normalize_messages(compacted)


def compact_in_place(
    messages: list[dict[str, Any]],
    *,
    focus: str = "",
    force_l0: bool = False,
) -> None:
    messages[:] = compact_messages(messages, focus=focus, force_l0=force_l0)


def emergency_compact(messages: list[dict[str, Any]], *, focus: str = "") -> list[dict[str, Any]]:
    log_event("COMPACT", "emergency_start", messages=len(messages), focus=focus)
    try:
        return compact_history(messages, focus=focus or "recover from prompt_too_long")
    except Exception as exc:
        log_event("ERROR", "emergency_llm_failed", error=exc)
        return local_fallback_compact(messages, reason="prompt_too_long emergency")


def tool_result_budget(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    changed = 0
    for message in messages:
        content = message.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if not is_tool_result(block):
                continue
            text = str(block.get("content", ""))
            if is_l3_compacted_tool_result(text):
                continue
            if is_tool_result_artifact_read(text):
                block["content"] = summarize_tool_result_artifact_read(text)
                changed += 1
                continue
            if len(text) <= L3_TOOL_RESULT_BUDGET:
                continue
            if "[Full tool result saved at:" in text:
                continue
            path = save_tool_result(block, text)
            block["content"] = summarize_large_result(text, path)
            changed += 1
    if changed:
        log_event("COMPACT", "l3_tool_result_budget", changed=changed)
    return messages


def snip_compact(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if len(messages) <= L1_COMPACT_TRIGGER_MESSAGES:
        return messages

    repeated_snip = any(is_l1_snip_marker(message) for message in messages)
    if repeated_snip:
        # A previous L1 snip plus many new tool turns means the loop is still active.
        # Keep a larger runway so we do not re-enter L1 every few tool calls.
        head_count = min(max(8, L1_KEEP_HEAD // 2), max(1, L1_MAX_MESSAGES - 1))
        tail_budget = max(12, L1_MAX_MESSAGES - head_count - 1)
        tail_count = min(max(20, L1_KEEP_TAIL // 2), tail_budget)
    else:
        head_count = min(L1_KEEP_HEAD, max(1, L1_MAX_MESSAGES - 1))
        tail_count = min(L1_KEEP_TAIL, max(0, L1_MAX_MESSAGES - head_count - 1))
    head = messages[:head_count]
    tail = messages[-tail_count:] if tail_count else []
    omitted = len(messages) - len(head) - len(tail)
    if omitted <= 0:
        log_event("COMPACT", "l1_snip_skipped_no_progress", before=len(messages), repeated=repeated_snip)
        return messages
    log_event(
        "COMPACT",
        "l1_snip",
        before=len(messages),
        omitted=omitted,
        target=L1_MAX_MESSAGES,
        trigger=L1_COMPACT_TRIGGER_MESSAGES,
        repeated=repeated_snip,
    )
    return [
        *head,
        {
            "role": "user",
            "content": f"[snip_compact omitted {omitted} middle messages]",
        },
        *tail,
    ]


def is_l1_snip_marker(message: dict[str, Any]) -> bool:
    content = message.get("content", "")
    return isinstance(content, str) and content.startswith("[snip_compact omitted ")


def _build_tool_use_index(messages: list[dict[str, Any]]) -> dict[str, tuple[str, dict[str, Any]]]:
    """Build mapping from tool_use_id to (tool_name, tool_input) for all tool_use blocks."""
    index: dict[str, tuple[str, dict[str, Any]]] = {}
    for message in messages:
        if message.get("role") != "assistant":
            continue
        content = message.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_use":
                tool_id = block.get("id", "")
                tool_name = block.get("name", "")
                tool_input = block.get("input", {})
                if tool_id:
                    index[tool_id] = (tool_name, tool_input if isinstance(tool_input, dict) else {})
    return index


def _summarize_tool_result(tool_name: str, tool_input: dict[str, Any], result_text: str) -> str:
    """Generate a compact summary preserving key metadata instead of generic placeholder."""
    name_lower = tool_name.lower().replace("_", "")

    # File read operations: preserve path and size info
    if name_lower in {"readfile", "read"}:
        path = str(tool_input.get("path", ""))
        if path:
            # Count lines in the result (read_file returns numbered lines)
            line_count = result_text.count("\n") + 1 if result_text else 0
            char_count = len(result_text)
            path_short = path.split("/")[-1] if "/" in path else path.split("\\")[-1] if "\\" in path else path
            return f"[Previously read: {path_short} ({line_count} lines, {char_count} chars)]"

    # Glob operations: preserve pattern and match count
    if name_lower == "glob":
        pattern = str(tool_input.get("pattern", ""))
        if pattern:
            # Count matches (glob returns one path per line)
            match_count = len([l for l in result_text.splitlines() if l.strip()]) if result_text else 0
            return f"[Previously globbed: {pattern} ({match_count} matches)]"

    # List operations
    if "list" in name_lower:
        count = len([l for l in result_text.splitlines() if l.strip()]) if result_text else 0
        return f"[Previously listed: {tool_name} ({count} items)]"

    # Default: generic compressed with tool name
    return f"[tool result compressed: {tool_name}]"


def micro_compact(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    # Build index of tool_use_id -> (tool_name, tool_input) for meaningful summaries
    tool_use_index = _build_tool_use_index(messages)

    seen = 0
    changed = 0
    for message in reversed(messages):
        content = message.get("content")
        if not isinstance(content, list):
            continue
        for block in reversed(content):
            if not is_tool_result(block):
                continue
            seen += 1
            if seen <= L2_KEEP_TOOL_RESULTS:
                continue
            text = str(block.get("content", ""))
            if text.startswith("[tool result compressed"):
                continue
            # Exempt previously summarized results
            if text.startswith("[Previously"):
                continue
            # Exempt error results — they are small and critical for preventing retry loops
            if block.get("is_error") or _is_error_tool_result(text):
                continue
            # Exempt very small results — they don't contribute to context bloat
            if len(text) < 200:
                continue

            # Generate meaningful summary if we have tool_use metadata
            tool_use_id = block.get("tool_use_id", "")
            if tool_use_id and tool_use_id in tool_use_index:
                tool_name, tool_input = tool_use_index[tool_use_id]
                summary = _summarize_tool_result(tool_name, tool_input, text)
            else:
                summary = "[tool result compressed by micro_compact]"

            block["content"] = summary
            changed += 1
    if changed:
        log_event("COMPACT", "l2_micro", changed=changed, kept=L2_KEEP_TOOL_RESULTS)
    return messages


def _is_error_tool_result(text: str) -> bool:
    """Check if a tool result text indicates an error or suppression message."""
    if not text:
        return False
    lower = text[:200].lower()
    return any(marker in lower for marker in (
        "error:", "error :", "errno",
        "no such file", "not found", "does not exist",
        "no files", "no matches", "no results",
        "no records", "no papers", "no projects",
        "no papergraph", "(empty)",
        "duplicate", "suppressed", "repeated",
        "extension-cycling", "loop detected",
        "traceback", "exception",
    ))


def compact_history(messages: list[dict[str, Any]], *, focus: str = "") -> list[dict[str, Any]]:
    transcript_path = save_transcript(messages)
    summary = summarize_with_llm(messages, focus=focus)
    log_event(
        "COMPACT",
        "l0_summary",
        before=len(messages),
        transcript=transcript_path,
        chars=len(summary),
    )
    return [
        {
            "role": "user",
            "content": (
                "[Conversation compacted. Full transcript saved at: "
                f"{transcript_path}]\n\n{summary}"
            ),
        }
    ]


def local_fallback_compact(messages: list[dict[str, Any]], *, reason: str) -> list[dict[str, Any]]:
    transcript_path = save_transcript(messages)
    kept = deepcopy(messages[-EMERGENCY_KEEP_MESSAGES:])
    log_event(
        "COMPACT",
        "local_fallback",
        reason=reason,
        kept=len(kept),
        transcript=transcript_path,
    )
    return normalize_messages(
        [
            {
                "role": "user",
                "content": (
                    f"[Local fallback compaction: {reason}. Full transcript saved at: "
                    f"{transcript_path}. Earlier context was dropped.]"
                ),
            },
            *kept,
        ]
    )


def summarize_with_llm(messages: list[dict[str, Any]], *, focus: str = "") -> str:
    client = get_client()
    focus_text = f"\nFocus on: {focus}" if focus else ""
    response = client.messages.create(
        model=MODEL_ID,
        max_tokens=L0_SUMMARY_TOKENS,
        system=(
            "Summarize an agent conversation for continuation. Include the original "
            "task, important decisions, files touched, tool results that still matter, "
            "current state, and remaining work."
        ),
        messages=[
            {
                "role": "user",
                "content": (
                    "Compact this conversation without losing operational context."
                    f"{focus_text}\n\n{serialize_messages(messages)}"
                ),
            }
        ],
    )
    return response_text(response.content) or "[LLM summary was empty]"


def save_tool_result(block: dict[str, Any], text: str) -> Path:
    TOOL_RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    tool_use_id = str(block.get("tool_use_id") or f"tool_result_{time.time_ns()}")
    path = TOOL_RESULTS_DIR / f"{safe_filename(tool_use_id)}.txt"
    path.write_text(text, encoding="utf-8")
    return path


def save_transcript(messages: list[dict[str, Any]]) -> Path:
    TRANSCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
    path = TRANSCRIPTS_DIR / f"transcript_{time.strftime('%Y%m%d_%H%M%S')}_{time.time_ns()}.json"
    path.write_text(serialize_messages(messages), encoding="utf-8")
    return path


def summarize_large_result(text: str, path: Path) -> str:
    head = text[:L3_SNIPPET_CHARS]
    tail = text[-L3_SNIPPET_CHARS:] if len(text) > L3_SNIPPET_CHARS else ""
    return (
        f"[Full tool result saved at: {path}]\n"
        f"[Original length: {len(text)} characters]\n\n"
        f"--- head ---\n{head}\n"
        f"--- tail ---\n{tail}"
    )


def is_l3_compacted_tool_result(text: str) -> bool:
    stripped = text.lstrip()
    return (
        stripped.startswith("[Full tool result saved at:")
        or stripped.startswith("[tool result artifact read compressed]")
        or stripped.startswith("[tool result compressed")
    )


def is_tool_result_artifact_read(text: str) -> bool:
    lowered = text.lower()
    return (
        "[tool result artifact preview]" in lowered
        or "v8/tool_results/" in lowered
        or "v8\\tool_results\\" in lowered
        or str(TOOL_RESULTS_DIR).lower() in lowered
    )


def summarize_tool_result_artifact_read(text: str) -> str:
    head = sanitize_tool_result_artifact_preview(text[:L3_SNIPPET_CHARS])
    return (
        "[tool result artifact read compressed]\n"
        "A previous read_file call targeted the tool-result artifact directory. Full content was not re-saved "
        "to avoid recursive tool-result growth.\n\n"
        f"--- preview ---\n{head}"
    )


def sanitize_tool_result_artifact_preview(text: str) -> str:
    return (
        text.replace(str(TOOL_RESULTS_DIR), "<tool_results_dir>")
        .replace(str(TOOL_RESULTS_DIR).replace("\\", "/"), "<tool_results_dir>")
        .replace("v8/tool_results", "<tool_results>")
        .replace("v8\\tool_results", "<tool_results>")
    )


def normalize_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for message in messages:
        role = message.get("role", "user")
        content = message.get("content", "")
        if (
            normalized
            and normalized[-1].get("role") == role
            and can_merge(normalized[-1].get("content", ""))
            and can_merge(content)
        ):
            normalized[-1]["content"] = merge_content(normalized[-1].get("content", ""), content)
        else:
            normalized.append({"role": role, "content": content})
    return normalized


def can_merge(content: Any) -> bool:
    if not isinstance(content, list):
        return True
    return not any(
        isinstance(block, dict)
        and block.get("type") in {"tool_use", "tool_result"}
        for block in content
    )


def merge_content(left: Any, right: Any) -> Any:
    if isinstance(left, list) or isinstance(right, list):
        return as_blocks(left) + as_blocks(right)
    return f"{left}\n\n{right}"


def as_blocks(content: Any) -> list[Any]:
    if isinstance(content, list):
        return content
    return [{"type": "text", "text": str(content)}]


def serialized_len(messages: list[dict[str, Any]]) -> int:
    return len(serialize_messages(messages))


def serialize_messages(messages: list[dict[str, Any]]) -> str:
    return json.dumps(messages, ensure_ascii=False, indent=2, default=str)


def safe_filename(value: str) -> str:
    return "".join(char if char.isalnum() or char in "-_." else "_" for char in value)


def is_tool_result(block: Any) -> bool:
    return isinstance(block, dict) and block.get("type") == "tool_result"


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


def is_prompt_too_long_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return any(
        marker in text
        for marker in (
            "prompt_too_long",
            "context length",
            "context_length",
            "too many tokens",
            "maximum context",
        )
    )
