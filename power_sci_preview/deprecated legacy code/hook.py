from __future__ import annotations

import re
import time
from collections import defaultdict
from typing import Any, Callable

try:
    from .config import (
        AUTO_APPROVE,
        DISABLE_CONTEXT_INJECTION,
        LARGE_OUTPUT_CHARS,
        TOOL_RESULTS_DIR,
        WORKDIR,
    )
    from .log import log_event
    from .tools import safe_cwd, safe_path
except ImportError:
    from config import (
        AUTO_APPROVE,
        DISABLE_CONTEXT_INJECTION,
        LARGE_OUTPUT_CHARS,
        TOOL_RESULTS_DIR,
        WORKDIR,
    )
    from log import log_event
    from tools import safe_cwd, safe_path


HookHandler = Callable[..., str | None]
HOOKS: dict[str, list[HookHandler]] = defaultdict(list)
TOOL_STARTS: dict[str, float] = {}
TOOL_RESULT_ARTIFACT_READS: dict[str, int] = {}

STATS = {
    "tool_calls": 0,
    "blocked": 0,
    "large_outputs": 0,
    "subagents": 0,
}

DENY_PATTERNS = [
    r"\brm\s+-rf\s+[/\\~]?",
    r"\bsudo\b",
    r"\bshutdown\b",
    r"\breboot\b",
    r"\bmkfs\b",
    r"\bdiskpart\b",
    r"\bformat\s+[a-z]:",
    r"\bdel\s+/[sq]\b",
    r"\bRemove-Item\b.*\b-Recurse\b.*\b-Force\b",
]

RISKY_PATTERNS = [
    r"\brm\b",
    r"\bdel\b",
    r"\brmdir\b",
    r"\bchmod\s+777\b",
    r"\bchown\b",
    r"\bgit\s+push\b.*\b--force\b",
]


def register_hook(event: str, handler: HookHandler) -> None:
    HOOKS[event].append(handler)


def trigger_hook(event: str, *args: Any, **kwargs: Any) -> str | None:
    """Run handlers and return the first non-None result.

    PreToolUse and PostToolUse automatically emit internal OnToolStart and
    OnToolEnd events, so business code gets structured tool logs for free.
    """
    if event == "PreToolUse" and args:
        trigger_hook("OnToolStart", args[0])
    elif event == "PostToolUse" and len(args) >= 2:
        trigger_hook("OnToolEnd", args[0], args[1])

    for handler in HOOKS.get(event, []):
        result = handler(*args, **kwargs)
        if result is not None:
            return result
    return None


def block_attr(block: Any, name: str, default: Any = None) -> Any:
    if isinstance(block, dict):
        return block.get(name, default)
    return getattr(block, name, default)


def matches_any(command: str, patterns: list[str]) -> bool:
    return any(re.search(pattern, command, flags=re.IGNORECASE) for pattern in patterns)


def permission_hook(block: Any) -> str | None:
    name = normalize_tool_name(block_attr(block, "name"))
    tool_input = block_attr(block, "input", {}) or {}

    if name == "bash":
        command = str(tool_input.get("command", ""))
        if matches_any(command, DENY_PATTERNS):
            STATS["blocked"] += 1
            log_event("ERROR", "blocked", name="bash", reason="deny", command=command)
            return f"BLOCKED: dangerous command denied: {command}"
        if matches_any(command, RISKY_PATTERNS) and not approve(
            f"Allow risky command? {command}"
        ):
            STATS["blocked"] += 1
            log_event("WARN", "blocked", name="bash", reason="user_denied", command=command)
            return f"BLOCKED: user denied command: {command}"

    if name in {"bash", "read_file", "write_file", "edit_file", "glob"}:
        cwd = str(tool_input.get("cwd", ""))
        if cwd:
            try:
                safe_cwd(cwd)
            except Exception as exc:
                return block_permission(name, "cwd_escape", str(exc))

    if name in {"write_file", "edit_file", "read_file"}:
        path = str(tool_input.get("path", ""))
        cwd = str(tool_input.get("cwd", ""))
        if path:
            try:
                resolved_path = safe_path(path, cwd or None)
            except Exception as exc:
                return block_permission(name, "path_escape", str(exc))
            if name == "read_file" and is_tool_result_artifact_path(resolved_path):
                key = str(resolved_path.resolve()).lower()
                count = TOOL_RESULT_ARTIFACT_READS.get(key, 0)
                if count >= 1:
                    return block_permission(
                        name,
                        "repeated_tool_result_artifact_read",
                        (
                            f"{path}. This artifact was already previewed once in this run. "
                            "Do not keep reading v8/tool_results files; use the preview, "
                            "the original producing tool/search id, or provide a final summary."
                        ),
                    )
                TOOL_RESULT_ARTIFACT_READS[key] = count + 1

    if name.startswith("mcp__") and not re.fullmatch(r"mcp__[a-z0-9_-]+__[a-z0-9_-]+", name):
        return block_permission(name, "bad_mcp_tool_name", name)

    if name == "connect_mcp":
        server = str(tool_input.get("name", ""))
        if not re.fullmatch(r"[A-Za-z0-9 _.-]{1,64}", server):
            return block_permission(name, "bad_mcp_server_name", server)


    if name == "schedule_cron":
        cron = str(tool_input.get("cron", ""))
        prompt = str(tool_input.get("prompt", ""))
        try:
            from .cron_scheduler import validate_cron
        except ImportError:
            from cron_scheduler import validate_cron
        error = validate_cron(cron)
        if error:
            return block_permission(name, "bad_cron", error)
        if matches_any(prompt, DENY_PATTERNS):
            return block_permission(name, "dangerous_scheduled_prompt", prompt)
        if matches_any(prompt, RISKY_PATTERNS) and not approve(
            f"Allow risky scheduled prompt? {prompt}"
        ):
            return block_permission(name, "user_denied_scheduled_prompt", prompt)

    if name == "cancel_cron":
        job_id = str(tool_input.get("job_id", ""))
        if not re.fullmatch(r"cron_[0-9]+_[0-9]+", job_id):
            return block_permission(name, "bad_cron_id", job_id)

    return None


def is_tool_result_artifact_path(path: Any) -> bool:
    try:
        resolved = path.resolve()
        root = TOOL_RESULTS_DIR.resolve()
    except Exception:
        return False
    return resolved.is_relative_to(root) and resolved.suffix.lower() == ".txt"


def block_permission(name: str, reason: str, detail: str) -> str:
    STATS["blocked"] += 1
    log_event("ERROR", "blocked", name=name, reason=reason, detail=detail)
    return f"BLOCKED: {reason}: {detail}"


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
        "todowrite": "todo_write",
        "todo_write": "todo_write",
        "task": "task",
        "spawnsubagent": "spawn_subagent",
        "spawn_subagent": "spawn_subagent",
        "loadskill": "load_skill",
        "load_skill": "load_skill",
        "connectmcp": "connect_mcp",
        "connect_mcp": "connect_mcp",
        "schedulecron": "schedule_cron",
        "schedule_cron": "schedule_cron",
        "listcrons": "list_crons",
        "list_crons": "list_crons",
        "cancelcron": "cancel_cron",
        "cancel_cron": "cancel_cron",
    }
    key = raw.replace("-", "_").replace(" ", "_").lower()
    compact_key = key.replace("_", "")
    return aliases.get(key) or aliases.get(compact_key) or key


def large_output_hook(block: Any, output: str) -> str | None:
    name = block_attr(block, "name", "<unknown>")
    if len(output) > LARGE_OUTPUT_CHARS:
        STATS["large_outputs"] += 1
        log_event("WARN", "large_output", name=name, chars=len(output))
    return None


def context_inject_hook(user_input: str) -> str | None:
    if DISABLE_CONTEXT_INJECTION:
        return None
    return (
        f"{user_input}\n\n"
        f"[v4 context]\n"
        f"- workspace: {WORKDIR}\n"
        f"- hook events: {', '.join(sorted(HOOKS))}\n"
    )


def summary_hook(final_text: str | None = None) -> str | None:
    log_event(
        "AGENT",
        "summary",
        tool_calls=STATS["tool_calls"],
        blocked=STATS["blocked"],
        large_outputs=STATS["large_outputs"],
        subagents=STATS["subagents"],
    )
    return None


def on_tool_start(block: Any) -> str | None:
    name = block_attr(block, "name", "<unknown>")
    tool_id = block_attr(block, "id", "<no-id>")
    tool_input = block_attr(block, "input", {}) or {}
    TOOL_STARTS[tool_id] = time.perf_counter()
    STATS["tool_calls"] += 1
    if normalize_tool_name(name) in {"task", "spawn_subagent"}:
        STATS["subagents"] += 1
    category = "SUBAGENT" if normalize_tool_name(name) in {"task", "spawn_subagent"} else "TOOL"
    log_event(category, "start", name=name, id=tool_id, input=compact_input(tool_input))
    return None


def on_tool_end(block: Any, output: str) -> str | None:
    name = block_attr(block, "name", "<unknown>")
    tool_id = block_attr(block, "id", "<no-id>")
    start = TOOL_STARTS.pop(tool_id, None)
    elapsed_ms = None if start is None else int((time.perf_counter() - start) * 1000)
    category = "SUBAGENT" if normalize_tool_name(name) in {"task", "spawn_subagent"} else "TOOL"
    log_event(category, "end", name=name, id=tool_id, chars=len(output), elapsed_ms=elapsed_ms)
    return None


def approve(question: str) -> bool:
    if AUTO_APPROVE:
        return True
    answer = input(f"{question}\n[y/N] ").strip().lower()
    return answer in {"y", "yes"}


def compact_input(tool_input: dict[str, Any]) -> str:
    rendered = repr(tool_input)
    if len(rendered) <= 1000:
        return rendered
    return rendered[:1000] + "...[truncated]"


def register_default_hooks() -> None:
    if HOOKS:
        return
    register_hook("OnToolStart", on_tool_start)
    register_hook("OnToolEnd", on_tool_end)
    register_hook("UserPromptSubmit", context_inject_hook)
    register_hook("PreToolUse", permission_hook)
    register_hook("PostToolUse", large_output_hook)
    register_hook("Stop", summary_hook)


register_default_hooks()
