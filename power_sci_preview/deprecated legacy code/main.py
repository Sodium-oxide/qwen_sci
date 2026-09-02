from __future__ import annotations

import argparse
import json
import time
from typing import Any

try:
    from .compact import compact_in_place, compact_messages
    from .cron_scheduler import agent_lock, consume_cron_queue, render_scheduled_prompt, start_cron_services
    from .hook import trigger_hook
    from .final_validation import extract_task_ids, validate_before_final
    from .llm import get_client
    from .log import log_event
    from .memory import extract_memories
    from .mcp_plugin import assemble_tool_pool
    from .recovery import RecoveryState, create_response_with_recovery
    from .skill import build_system
    from .task_system import collect_background_notifications, should_run_background, start_background_task, strip_control_args
    from .tools import (
        INTERNAL_SCIENCE_TOOL_NAMES,
        TOOL_HANDLERS as BUILTIN_TOOL_HANDLERS,
        TOOLS as BUILTIN_TOOLS,
    )
    from ._science_routing import science_workflow_requested
except ImportError:
    from compact import compact_in_place, compact_messages
    from cron_scheduler import agent_lock, consume_cron_queue, render_scheduled_prompt, start_cron_services
    from hook import trigger_hook
    from final_validation import extract_task_ids, validate_before_final
    from llm import get_client
    from log import log_event
    from memory import extract_memories
    from mcp_plugin import assemble_tool_pool
    from recovery import RecoveryState, create_response_with_recovery
    from skill import build_system
    from task_system import collect_background_notifications, should_run_background, start_background_task, strip_control_args
    from tools import (
        INTERNAL_SCIENCE_TOOL_NAMES,
        TOOL_HANDLERS as BUILTIN_TOOL_HANDLERS,
        TOOLS as BUILTIN_TOOLS,
    )
    from _science_routing import science_workflow_requested


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


def contains_unparsed_tool_request(text: str) -> bool:
    """Detect tool-call syntax that must not be finalized as ordinary text."""
    import re as _re
    source = str(text or "").strip()
    lowered = source.lower()
    if "[assistant requested tool]" in lowered:
        return True
    if _re.search(r'"(?:tool_uses|tool_calls|tools)"\s*:', source) and _re.search(r'"name"\s*:', source):
        return True
    return bool(
        source.startswith("{")
        and _re.search(r'"name"\s*:', source)
        and _re.search(r'"input"\s*:', source)
    )


def tool_result(tool_use_id: str, output: str, is_error: bool = False) -> dict[str, Any]:
    result: dict[str, Any] = {
        "type": "tool_result",
        "tool_use_id": tool_use_id,
        "content": output,
    }
    if is_error:
        result["is_error"] = True
    return result


def is_science_project_id(value: Any) -> bool:
    """Whether a value is a concrete persisted science-project identifier."""

    import re as _re

    return bool(_re.fullmatch(r"sci_[0-9A-Za-z_:-]+", str(value or "").strip()))


def is_unresolved_project_id_placeholder(value: Any) -> bool:
    """Whether a project-id value is still a tool-reference template."""

    import re as _re

    candidate = str(value or "").strip()
    if not candidate:
        return False
    return bool(
        _re.fullmatch(r"\$\{[^{}]+\}|\{\{[^{}]+\}\}|\$[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*", candidate)
        or candidate in {"<project_id>", "<project_id_from_create_research_project>"}
    )


def rejected_tool_call_correction(
    diagnostics: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    messages: list[dict[str, Any]],
) -> str:
    allowed_tools = [
        str(tool.get("name") or "").strip()
        for tool in tools
        if str(tool.get("name") or "").strip()
    ]
    requested_tools = sorted(
        {
            str(item.get("requested_tool") or "").strip()
            for item in diagnostics
            if str(item.get("requested_tool") or "").strip()
        }
    )
    reasons = sorted(
        {
            str(item.get("reason") or "UNKNOWN_TOOL_PROTOCOL_ERROR").strip()
            for item in diagnostics
        }
    )
    active_project_id = successful_session_project_id(messages)
    if not active_project_id and "create_research_project" in allowed_tools:
        required_next_tool = "create_research_project"
    elif active_project_id and "run_autogen_groupchat" in allowed_tools:
        required_next_tool = "run_autogen_groupchat"
    else:
        required_next_tool = ""
    correction = {
        "status": "REJECTED_TOOL_CALL_REQUIRES_CORRECTION",
        "reasons": reasons,
        "requested_tools": requested_tools,
        "allowed_tools": allowed_tools,
        "required_next_tool": required_next_tool,
        "instruction": (
            "Call exactly one currently allowed tool using "
            '{"tool_uses":[{"name":"...","input":{...}}]}. '
            "Do not use a historical project_id or an unadvertised tool."
        ),
    }
    return "[SYSTEM: TOOL_CALL_REJECTED]\n" + json.dumps(
        correction,
        ensure_ascii=False,
    )


def successful_session_project_id(messages: list[dict[str, Any]]) -> str:
    """Return a project id established by a successful create result.

    A pending assistant tool call is not durable session state.  In
    particular, an import call may contain a stale project id before project
    creation, so it must not activate the canonical workflow.
    """

    tool_name_by_id: dict[str, str] = {}
    for message in messages:
        if message.get("role") != "assistant":
            continue
        blocks = message.get("content") if isinstance(message.get("content"), list) else []
        for block in blocks:
            if not isinstance(block, dict) or block.get("type") != "tool_use":
                continue
            tool_id = str(block.get("id") or "").strip()
            if tool_id:
                tool_name_by_id[tool_id] = normalize_tool_name(block.get("name"))

    for message in reversed(messages):
        if message.get("role") != "user":
            continue
        blocks = message.get("content") if isinstance(message.get("content"), list) else []
        for block in reversed(blocks):
            if not isinstance(block, dict) or block.get("type") != "tool_result":
                continue
            if block.get("is_error") is True:
                continue
            tool_name = tool_name_by_id.get(str(block.get("tool_use_id") or "").strip())
            if tool_name != "create_research_project":
                continue
            raw = str(block.get("content") or "")
            try:
                payload = json.loads(raw)
            except (TypeError, json.JSONDecodeError):
                payload = {}
            if isinstance(payload, dict) and payload.get("status") == "PROJECT_CREATED":
                project_id = str(payload.get("project_id") or "").strip()
                if is_science_project_id(project_id):
                    return project_id
    return ""


def session_tool_names(messages: list[dict[str, Any]]) -> list[str]:
    names: list[str] = []
    for message in messages:
        if message.get("role") != "assistant":
            continue
        content = message.get("content")
        blocks = content if isinstance(content, list) else []
        for block in blocks:
            if not isinstance(block, dict) or block.get("type") != "tool_use":
                continue
            names.append(normalize_tool_name(str(block.get("name") or "")))
    return names


def groupchat_business_decisions(messages: list[dict[str, Any]]) -> list[str]:
    """Read GroupChat business outcomes, not merely successful RPC envelopes."""

    active_project_id = successful_session_project_id(messages)
    tool_call_by_id: dict[str, tuple[str, str]] = {}
    decisions: list[str] = []
    for message in messages:
        content = message.get("content")
        blocks = content if isinstance(content, list) else []
        if message.get("role") == "assistant":
            for block in blocks:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    tool_id = str(block.get("id") or "").strip()
                    if tool_id:
                        tool_input = block.get("input") if isinstance(block.get("input"), dict) else {}
                        tool_call_by_id[tool_id] = (
                            normalize_tool_name(str(block.get("name") or "")),
                            str(tool_input.get("project_id") or "").strip(),
                        )
        elif message.get("role") == "user":
            for block in blocks:
                if not isinstance(block, dict) or block.get("type") != "tool_result":
                    continue
                if block.get("is_error") is True:
                    continue
                tool_name, requested_project_id = tool_call_by_id.get(
                    str(block.get("tool_use_id") or "").strip(),
                    ("", ""),
                )
                if (
                    tool_name != "run_autogen_groupchat"
                    or not active_project_id
                    or requested_project_id != active_project_id
                ):
                    continue
                raw = block.get("content")
                raw = raw if isinstance(raw, str) else response_text(raw if isinstance(raw, list) else [])
                try:
                    payload = json.loads(raw)
                except (TypeError, json.JSONDecodeError):
                    continue
                if isinstance(payload, dict):
                    result_project_id = str(payload.get("project_id") or "").strip()
                    if result_project_id and result_project_id != active_project_id:
                        continue
                    decision = str(payload.get("final_decision") or "").strip()
                    if decision:
                        decisions.append(decision)
    return decisions


CANONICAL_OUTER_SCIENCE_TOOLS = frozenset(
    {
        "create_research_project",
        "list_research_projects",
        "get_research_project",
        "run_autogen_groupchat",
    }
)

TERMINAL_GROUPCHAT_DECISIONS = frozenset(
    {
        "completed",
        "proposal_ready",
        "accept_for_experiment",
        "revision_required",
        "llm_decomposition_empty",
        "llm_decomposition_response_truncated",
        "llm_decomposition_root_protocol_invalid",
        "llm_decomposition_timeout",
        "llm_decomposition_invocation_failed",
        "llm_decomposition_disabled",
        "decomposition_candidate_repair_required",
        "decomposition_candidate_repair_exhausted",
    }
)
RECOVERABLE_GROUPCHAT_DECISIONS = frozenset(
    {"checkpointed_error", "retrieval_pending"}
)


def canonical_outer_tool_pool(
    tools: list[dict[str, Any]],
    messages: list[dict[str, Any]],
    user_input: str,
) -> list[dict[str, Any]]:
    """Expose only the science tools valid for the current outer stage."""

    science_requested = science_workflow_requested(user_input)
    project_id = successful_session_project_id(messages)
    decisions = groupchat_business_decisions(messages)
    latest_decision = decisions[-1] if decisions else ""
    if not project_id:
        allowed = {"create_research_project", "list_research_projects"}
    elif latest_decision and latest_decision not in RECOVERABLE_GROUPCHAT_DECISIONS:
        allowed = {"list_research_projects", "get_research_project"}
    else:
        allowed = {
            "list_research_projects",
            "get_research_project",
            "run_autogen_groupchat",
        }
    staged_science_tools = [
        tool
        for tool in tools
        if str(tool.get("name") or "") in allowed
    ]
    if science_requested:
        return staged_science_tools
    return [
        tool
        for tool in tools
        if str(tool.get("name") or "") not in CANONICAL_OUTER_SCIENCE_TOOLS
    ] + staged_science_tools


def validate_science_workflow_before_final(
    user_input: str,
    messages: list[dict[str, Any]],
    final_text: str,
) -> str:
    tool_names = session_tool_names(messages)
    business_decisions = groupchat_business_decisions(messages)
    if business_decisions and business_decisions[-1] in TERMINAL_GROUPCHAT_DECISIONS:
        return ""
    if business_decisions and business_decisions[-1] in RECOVERABLE_GROUPCHAT_DECISIONS:
        project_id = successful_session_project_id(messages)
        return (
            "[SYSTEM: GROUPCHAT_CHECKPOINT_REQUIRED]\n"
            "run_autogen_groupchat returned a recoverable or integrity error. Do not create pipeline tasks, "
            "delegation tasks, DAGs, crews, or use any V1 workflow. Resume the same V3 GroupChat checkpoint "
            f"for project_id={project_id} by calling run_autogen_groupchat again."
        )
    if business_decisions:
        return ""
    workflow_started = "create_research_project" in tool_names
    if not workflow_started:
        if not science_workflow_requested(user_input):
            return ""
        compact_goal = compact_text(user_input, limit=1400)
        return (
            "[SYSTEM: SCIENCE_WORKFLOW_NOT_STARTED]\n"
            "The user submitted a science research question or research brief, but no science "
            "workflow tool has run in this session. A plain-text scientific answer cannot finalize "
            "this python -m v8.main request. Start the canonical workflow now; do not ask whether "
            "to proceed and do not merely describe what the workflow could do.\n"
            "Call create_research_project exactly once now, and make it the only tool call in this "
            "assistant turn. Populate title, domain, objective, and strategic_need from the user's "
            "actual topic. Omit research_brief so the canonical GroupChat decomposition remains "
            "authoritative. Preserve this research goal:\n"
            + compact_goal
            + "\nAfter the tool result, the next outer-loop tool is run_autogen_groupchat; "
            "do not call decompose_research_objective directly."
        )

    project_id = successful_session_project_id(messages)
    if not project_id:
        return (
            "[SYSTEM: SCIENCE_PROJECT_CREATION_INCOMPLETE]\n"
            "The dedicated AI-scientist runtime still has no successful science "
            "project result, so a plain-text answer cannot finalize this request. "
            "Retry create_research_project with compact title, domain, and objective "
            "fields. Do not answer the topic directly."
        )

    compact_goal = compact_text(user_input, limit=1400)
    return (
        "[SYSTEM: SCIENCE_WORKFLOW_INCOMPLETE]\n"
        "A science project has been created in this session, but the canonical Boxue/AI Scientist "
        "workflow has not run yet. For python -m v8.main, a bare research topic means continue "
        "through the workflow unless the user explicitly asked for setup only. The next outer-loop "
        "tool after create_research_project is run_autogen_groupchat, not decompose_research_objective; "
        "the GroupChat executor owns decomposition as its first internal stage. Do not ask whether "
        "to proceed.\n"
        "Call run_autogen_groupchat exactly once now with the active project_id. Use this input "
        "shape, preserving the user's original goal:\n"
        + json.dumps(
            {
                "project_id": project_id,
                "goal": compact_goal,
            },
            ensure_ascii=False,
        )
        + "\nAfter run_autogen_groupchat returns, summarize the actual run result."
    )


def is_explicit_true(value: Any) -> bool:
    return value is True or (isinstance(value, str) and value.strip().lower() in {"true", "1", "yes"})


def compact_text(value: Any, limit: int = 420) -> str:
    text = str(value or "").strip()
    return text if len(text) <= limit else text[: max(0, limit - 1)].rstrip() + "…"


CANONICAL_PROJECT_DEPENDENT_TOOLS = frozenset(
    {"get_research_project", "run_autogen_groupchat"}
)


def bind_tool_to_active_session_project(
    tool_name: str,
    tool_input: dict[str, Any],
    active_project_id: str,
) -> tuple[dict[str, Any], str]:
    """Bind malformed or omitted V3 project references to the active session project."""

    normalized_tool = normalize_tool_name(tool_name)
    active = str(active_project_id or "").strip()
    supplied = str(tool_input.get("project_id") or "").strip()
    if (
        normalized_tool not in CANONICAL_PROJECT_DEPENDENT_TOOLS
        or not is_science_project_id(active)
        or is_science_project_id(supplied)
        or is_unresolved_project_id_placeholder(supplied)
    ):
        return tool_input, ""
    rebound = dict(tool_input)
    rebound["project_id"] = active
    return rebound, supplied


def update_tool_input_in_messages(
    messages: list[dict[str, Any]],
    tool_use_id: Any,
    tool_input: dict[str, Any],
) -> None:
    target_id = str(tool_use_id or "").strip()
    if not target_id:
        return
    for message in reversed(messages):
        if message.get("role") != "assistant":
            continue
        blocks = message.get("content") if isinstance(message.get("content"), list) else []
        for message_block in blocks:
            if not isinstance(message_block, dict):
                continue
            if str(message_block.get("id") or "").strip() == target_id:
                message_block["input"] = dict(tool_input)
                return


def compact_research_project_creation_result(output: str) -> str:
    """Return the durable create-to-GroupChat handoff, not a full project snapshot."""

    try:
        project = json.loads(output)
    except (TypeError, json.JSONDecodeError):
        return output
    if not isinstance(project, dict):
        return output
    project_id = str(project.get("project_id") or "").strip()
    if not is_science_project_id(project_id):
        return output
    if str(project.get("status") or "") == "PROJECT_INITIALIZATION_FAILED":
        return json.dumps(
            {
                "status": "PROJECT_INITIALIZATION_FAILED",
                "terminal": False,
                "project_id": project_id,
                "workflow_mode": "V3_GROUPCHAT_ONLY",
                "initialization_stage": compact_text(
                    project.get("initialization_stage"), 120
                ),
                "reason_code": compact_text(project.get("reason_code"), 160),
                "error_type": compact_text(project.get("error_type"), 120),
                "error": compact_text(project.get("error"), 600),
                "allowed_next_stages": ["create_research_project"],
                "next_tool": "create_research_project",
            },
            ensure_ascii=False,
            indent=2,
        )
    research_domains = project.get("research_domains")
    labels = [
        str(item.get("label") or "").strip()
        for item in research_domains
        if isinstance(item, dict) and str(item.get("label") or "").strip()
    ] if isinstance(research_domains, list) else []
    resolution = project.get("domain_resolution")
    return json.dumps(
        {
            "status": "PROJECT_CREATED",
            "project_id": project_id,
            "title": compact_text(project.get("title"), 240),
            "domain": compact_text(project.get("domain"), 180),
            "research_domains": labels[:8],
            "domain_resolution_source": (
                str(resolution.get("resolution_source") or "")
                if isinstance(resolution, dict)
                else ""
            ),
            "requires_human_confirmation": bool(
                resolution.get("requires_human_confirmation")
                if isinstance(resolution, dict)
                else False
            ),
            "workflow_mode": "V3_GROUPCHAT_ONLY",
            "next_tool": "run_autogen_groupchat",
        },
        ensure_ascii=False,
        indent=2,
    )


def inject_verbatim_research_brief(
    tool_name: str,
    tool_input: dict[str, Any],
    raw_user_prompt: str,
) -> dict[str, Any]:
    if tool_name != "create_research_project" or not raw_user_prompt or str(tool_input.get("research_brief") or "").strip():
        return tool_input
    enriched = dict(tool_input)
    enriched["research_brief"] = raw_user_prompt
    return enriched


def run_tool(
    block: Any,
    messages: list[dict[str, Any]],
    handlers: dict[str, Any],
    raw_user_prompt: str = "",
) -> dict[str, Any]:
    name = normalize_tool_name(block_attr(block, "name"))
    tool_input = block_attr(block, "input", {}) or {}
    tool_use_id = block_attr(block, "id")

    if name in INTERNAL_SCIENCE_TOOL_NAMES or (
        science_workflow_requested(raw_user_prompt)
        and name not in CANONICAL_OUTER_SCIENCE_TOOLS
    ):
        output = json.dumps(
            {
                "status": "BLOCKED_NON_CANONICAL_OUTER_TOOL",
                "terminal": False,
                "reason_code": "AUTOGEN_GROUPCHAT_OWNS_INTERNAL_SCIENCE_STAGES",
                "blocked_tool": name,
                "allowed_outer_tools": sorted(CANONICAL_OUTER_SCIENCE_TOOLS),
            },
            ensure_ascii=False,
            indent=2,
        )
        return tool_result(tool_use_id, output, is_error=True)

    active_project_id = successful_session_project_id(messages)

    enriched_tool_input = inject_verbatim_research_brief(name, tool_input, raw_user_prompt)
    if enriched_tool_input is not tool_input:
        tool_input = enriched_tool_input
        log_event("SCIENCE", "research_brief_auto_injected", chars=len(raw_user_prompt))

    if name in CANONICAL_PROJECT_DEPENDENT_TOOLS and not active_project_id:
        output = json.dumps(
            {
                "status": "BLOCKED_ACTIVE_PROJECT_REQUIRED",
                "terminal": False,
                "reason_code": "SUCCESSFUL_PROJECT_CREATION_REQUIRED_IN_CURRENT_SESSION",
                "blocked_tool": name,
                "allowed_next_stages": [
                    "create_research_project",
                    "list_research_projects",
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
        log_event("WARN", "active_project_required", tool=name)
        return tool_result(tool_use_id, output, is_error=True)

    session_bound_input, _ = bind_tool_to_active_session_project(
        name,
        tool_input,
        active_project_id,
    )
    if session_bound_input is not tool_input:
        tool_input = session_bound_input
        if isinstance(block, dict):
            block["input"] = tool_input
        else:
            block = dict(block_to_dict(block))
            block["input"] = tool_input
        update_tool_input_in_messages(messages, tool_use_id, tool_input)
        log_event(
            "SCIENCE",
            "tool_session_project_rebound",
            tool=name,
            active_project_id=active_project_id,
        )

    requested_project_id = str(tool_input.get("project_id") or "").strip()
    if (
        name in CANONICAL_PROJECT_DEPENDENT_TOOLS
        and is_unresolved_project_id_placeholder(requested_project_id)
    ):
        output = json.dumps(
            {
                "status": "BLOCKED_UNRESOLVED_PROJECT_ID_PLACEHOLDER",
                "terminal": False,
                "reason_code": "PROJECT_ID_PLACEHOLDER_NOT_RESOLVED",
                "blocked_tool": name,
                "allowed_next_stages": [],
                "remediation_plan": {
                    "kind": "resolve_project_id_before_dispatch",
                    "instruction": (
                        "Use the concrete sci_ project_id returned by create_research_project. "
                        "Do not dispatch a project-dependent workflow tool with an unresolved template."
                    ),
                },
            },
            ensure_ascii=False,
            indent=2,
        )
        log_event(
            "WARN",
            "unresolved_project_id_placeholder_blocked",
            tool=name,
        )
        return tool_result(tool_use_id, output, is_error=True)
    if (
        name in CANONICAL_PROJECT_DEPENDENT_TOOLS
        and requested_project_id != active_project_id
    ):
        output = json.dumps(
            {
                "status": "BLOCKED_CROSS_PROJECT_TOOL_CALL",
                "terminal": False,
                "reason_code": "PROJECT_ID_MUST_MATCH_CURRENT_SESSION_PROJECT",
                "blocked_tool": name,
                "allowed_next_stages": [],
            },
            ensure_ascii=False,
            indent=2,
        )
        log_event(
            "WARN",
            "cross_project_tool_call_blocked",
            tool=name,
        )
        return tool_result(tool_use_id, output, is_error=True)
    if (
        name in CANONICAL_PROJECT_DEPENDENT_TOOLS
        and requested_project_id
        and not is_science_project_id(requested_project_id)
    ):
        output = json.dumps(
            {
                "status": "BLOCKED_INVALID_PROJECT_ID",
                "terminal": False,
                "reason_code": "PROJECT_ID_MUST_REFERENCE_A_PERSISTED_SCIENCE_PROJECT",
                "blocked_tool": name,
                "allowed_next_stages": [],
                "remediation_plan": {
                    "kind": "use_persisted_science_project_id",
                    "instruction": (
                        "Use the sci_ project_id returned by create_research_project. "
                        "A title-derived slug is not a project identifier."
                    ),
                },
            },
            ensure_ascii=False,
            indent=2,
        )
        log_event(
            "WARN",
            "invalid_project_id_blocked",
            tool=name,
        )
        return tool_result(tool_use_id, output, is_error=True)

    if name == "create_research_project" and not is_explicit_true(tool_input.get("force_new_project", False)):
        current_project_id = successful_session_project_id(messages)
        if current_project_id:
            output = json.dumps(
                {
                    "status": "BLOCKED_ACTIVE_PROJECT_EXISTS",
                    "terminal": False,
                    "reason_code": "EXPLICIT_CONFIRMATION_REQUIRED_FOR_SECOND_PROJECT",
                    "project_id": current_project_id,
                    "allowed_next_stages": [],
                    "remediation_plan": {
                        "kind": "continue_or_confirm_new_project",
                        "instruction": (
                            "Continue with the active project_id, or set force_new_project=true "
                            "to explicitly create a separate project."
                        ),
                    },
                },
                ensure_ascii=False,
                indent=2,
            )
            log_event("WARN", "active_project_creation_blocked", project_id=current_project_id)
            return tool_result(tool_use_id, output)

    duplicate_count = repeated_tool_call_count(messages, name, strip_control_args(tool_input))
    if name in {"verify_citation_uniqueness"} and duplicate_count >= 3:
        output = (
            "Duplicate idempotent tool call suppressed: this exact verify_citation_uniqueness input "
            f"has already been requested {duplicate_count} times in the current run. "
            "Stop repeating this check; use the cached uniqueness result or continue to import/search with real retrieved papers."
        )
        log_event("WARN", "duplicate_tool_call_suppressed", name=name, count=duplicate_count)
        return tool_result(tool_use_id, output, is_error=True)

    # General file-operation loop detector: suppress repeated identical file reads/globs
    _FILE_LOOP_TOOLS = {"read_file", "read", "glob", "list_dir", "list_papergraph_records", "get_research_project"}
    if name in _FILE_LOOP_TOOLS and duplicate_count >= 2:
        path_hint = str(tool_input.get("path") or tool_input.get("pattern") or tool_input.get("project_id") or "")
        output = (
            f"Repeated file operation suppressed: `{name}` with similar input has been called "
            f"{duplicate_count} times. The file or data you are looking for is likely NOT at this path. "
            f"Path/pattern tried: {path_hint[:200]}. "
            "STOP retrying this path. Instead: (1) use list_papergraph_records or get_research_project to see what "
            "records/papers actually exist, (2) check if the data is embedded inside a project JSON rather than "
            "stored as separate files, (3) try a completely different approach to access the information you need."
        )
        log_event("WARN", "file_loop_suppressed", name=name, count=duplicate_count, path=path_hint[:120])
        return tool_result(tool_use_id, output, is_error=True)

    # Cross-extension loop detector: same base path, different extensions
    if name in {"read_file", "read"} and duplicate_count < 3:
        base_path = str(tool_input.get("path", ""))
        similar_count = similar_path_tool_call_count(messages, name, base_path)
        if similar_count >= 4:
            output = (
                f"Extension-cycling loop detected: you have tried {similar_count} different extensions on "
                f"the same base path `{base_path[:200]}`. This file does not exist in any format. "
                "STOP trying different extensions. The data you need is likely stored inside a project JSON "
                "(access via get_research_project or list_papergraph_records), not as individual files on disk."
            )
            log_event("WARN", "extension_cycling_suppressed", name=name, count=similar_count, path=base_path[:120])
            return tool_result(tool_use_id, output, is_error=True)

    blocked = trigger_hook("PreToolUse", block)
    if blocked is not None:
        return tool_result(tool_use_id, blocked, is_error=True)

    try:
        if name == "compact":
            focus = str(tool_input.get("focus", ""))
            compact_in_place(messages, focus=focus, force_l0=False)
            output = "Context compacted."
        else:
            handler = handlers[name]
            if should_run_background(block):
                output = start_background_task(block, handler, strip_control_args(tool_input))
            else:
                output = handler(**strip_control_args(tool_input))
    except Exception as exc:
        output = f"ERROR: {exc}"
        trigger_hook("PostToolUse", block, output)
        return tool_result(tool_use_id, output, is_error=True)

    raw_output = output
    if name == "create_research_project" and not should_run_background(block):
        output = compact_research_project_creation_result(raw_output)
    trigger_hook("PostToolUse", block, raw_output)
    return tool_result(tool_use_id, output)


def repeated_tool_call_count(messages: list[dict[str, Any]], name: str, tool_input: dict[str, Any]) -> int:
    signature = tool_call_signature(name, tool_input)
    count = 0
    for message in messages[-120:]:
        if message.get("role") != "assistant":
            continue
        content = message.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict) or block.get("type") != "tool_use":
                continue
            prior_name = normalize_tool_name(block.get("name"))
            prior_input = strip_control_args(block.get("input") or {})
            if tool_call_signature(prior_name, prior_input) == signature:
                count += 1
    return count


def tool_call_signature(name: str, tool_input: dict[str, Any]) -> str:
    try:
        payload = json.dumps(tool_input, ensure_ascii=False, sort_keys=True, default=str)
    except Exception:
        payload = str(tool_input)
    return f"{name}:{payload}"


def _strip_extension(path: str) -> str:
    """Remove the file extension from a path for base-path comparison."""
    dot_idx = path.rfind(".")
    slash_idx = max(path.rfind("/"), path.rfind("\\"))
    if dot_idx > slash_idx + 1:
        return path[:dot_idx]
    return path


def similar_path_tool_call_count(
    messages: list[dict[str, Any]],
    name: str,
    path: str,
) -> int:
    """Count how many times the same base path (ignoring extension) was used with this tool."""
    base = _strip_extension(path)
    if not base:
        return 0
    count = 0
    for message in messages[-120:]:
        if message.get("role") != "assistant":
            continue
        content = message.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict) or block.get("type") != "tool_use":
                continue
            prior_name = normalize_tool_name(block.get("name"))
            if prior_name != name:
                continue
            prior_input = block.get("input") or {}
            prior_path = str(prior_input.get("path", ""))
            if _strip_extension(prior_path) == base:
                count += 1
    return count


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
        "spawnsubagent": "task",
        "spawn_subagent": "task",
        "loadskill": "load_skill",
        "load_skill": "load_skill",
        "createtask": "create_task",
        "create_task": "create_task",
        "listtasks": "list_tasks",
        "list_tasks": "list_tasks",
        "gettask": "get_task",
        "get_task": "get_task",
        "claimtask": "claim_task",
        "claim_task": "claim_task",
        "completetask": "complete_task",
        "complete_task": "complete_task",
                                        "messageactiongateway": "send_message",
        "message_action_gateway": "send_message",
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


def create_response(
    client: Any,
    user_input: str,
    messages: list[dict[str, Any]],
    recovery_state: RecoveryState,
    tools: list[dict[str, Any]],
) -> Any:
    memory_types = frozenset({"user", "reference"})
    return create_response_with_recovery(
        client,
        system=build_system(user_input, memory_types=memory_types),
        messages=messages,
        tools=tools,
        state=recovery_state,
        focus=user_input,
    )


def run_agent(user_input: str) -> str:
    with agent_lock:
        start_cron_services(agent_callback=run_agent)
        return run_agent_locked(user_input)


def run_agent_locked(user_input: str) -> str:
    client = get_client()
    recovery_state = RecoveryState()
    log_event("USER", "prompt", chars=len(user_input))
    injected = trigger_hook("UserPromptSubmit", user_input)
    prompt = injected if injected is not None else user_input
    messages: list[dict[str, Any]] = [{"role": "user", "content": prompt}]
    tracked_task_ids: set[str] = set()
    validation_attempts = 0
    science_validation_attempts = 0
    incomplete_tool_json_attempts = 0
    unparsed_tool_request_attempts = 0
    rejected_tool_call_attempts = 0
    recent_tool_patterns: list[str] = []  # track per-iteration tool call patterns

    while True:
        current_tools, current_handlers = assemble_tool_pool(BUILTIN_TOOLS, BUILTIN_TOOL_HANDLERS)
        current_tools = canonical_outer_tool_pool(current_tools, messages, user_input)
        fired_crons = consume_cron_queue()
        if fired_crons:
            messages.append({"role": "user", "content": render_scheduled_prompt(fired_crons)})
        notifications = collect_background_notifications()
        if notifications:
            messages.append({"role": "user", "content": "\n\n".join(notifications)})
        messages[:] = compact_messages(messages)
        log_event("AGENT", "model_request", messages=len(messages), tools=len(current_tools))
        response = create_response(client, user_input, messages, recovery_state, current_tools)

        if getattr(response, "requires_tool_json_retry", False):
            incomplete_tool_json_attempts += 1
            if incomplete_tool_json_attempts <= 2:
                log_event("WARN", "incomplete_tool_json_retry", attempt=incomplete_tool_json_attempts)
                messages.append(
                    {
                        "role": "assistant",
                        "content": "[Previous tool-call JSON was truncated before it could be executed.]",
                    }
                )
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "Retry the tool call as compact JSON only. Do not repeat the research brief or any long user text. "
                            "For create_research_project, include only title, domain, objective, and optional strategic_need; "
                            "the runtime injects research_brief automatically."
                        ),
                    }
                )
                messages[:] = compact_messages(messages)
                continue
            final_text = (
                "The model repeatedly returned truncated tool-call JSON, so no tool was executed. "
                "Please retry the request; the runtime will preserve the original research brief automatically."
            )
            trigger_hook("Stop", final_text)
            extract_memories(messages, final_text)
            log_event("AGENT", "final", text=final_text)
            return final_text

        response_content = list(getattr(response, "content", None) or [])
        tool_call_diagnostics = [
            item
            for item in (getattr(response, "tool_call_diagnostics", None) or [])
            if isinstance(item, dict)
        ]
        for diagnostic in tool_call_diagnostics:
            log_event(
                "WARN",
                "tool_call_rejected",
                reason=diagnostic.get("reason", "UNKNOWN_TOOL_PROTOCOL_ERROR"),
                requested_tool=diagnostic.get("requested_tool", ""),
                allowed_tools=diagnostic.get("allowed_tools", []),
            )
        tool_blocks = [
            block
            for block in response_content
            if block_attr(block, "type") == "tool_use"
        ]
        if len(tool_blocks) > 1:
            log_event(
                "SCIENCE",
                "outer_multi_tool_response_reduced",
                requested_tools=[
                    normalize_tool_name(block_attr(block, "name"))
                    for block in tool_blocks
                ],
                executed_tool=normalize_tool_name(block_attr(tool_blocks[0], "name")),
            )
            tool_blocks = tool_blocks[:1]
            response_content = [tool_blocks[0]]
        if not tool_blocks:
            final_text = response_text(response_content)
            if tool_call_diagnostics:
                rejected_tool_call_attempts += 1
                if rejected_tool_call_attempts <= 2:
                    log_event(
                        "WARN",
                        "rejected_tool_call_retry",
                        attempt=rejected_tool_call_attempts,
                    )
                    messages.append(
                        {
                            "role": "assistant",
                            "content": (
                                "[Rejected tool call omitted from conversation context; "
                                "use the structured correction that follows.]"
                            ),
                        }
                    )
                    messages.append(
                        {
                            "role": "user",
                            "content": rejected_tool_call_correction(
                                tool_call_diagnostics,
                                current_tools,
                                messages,
                            ),
                        }
                    )
                    messages[:] = compact_messages(messages)
                    continue
                final_text = (
                    "The model repeatedly requested a tool that is unavailable in the current "
                    "workflow stage or used an invalid tool-call protocol. The call was not executed."
                )
            elif contains_unparsed_tool_request(final_text):
                unparsed_tool_request_attempts += 1
                if unparsed_tool_request_attempts <= 2:
                    log_event(
                        "WARN",
                        "unparsed_tool_request_retry",
                        attempt=unparsed_tool_request_attempts,
                    )
                    messages.append(
                        {
                            "role": "assistant",
                            "content": [block_to_dict(block) for block in response_content],
                        }
                    )
                    messages.append(
                        {
                            "role": "user",
                            "content": (
                                "Your previous response contained tool-call syntax, but no executable tool call was parsed. "
                                "Retry as exactly one compact JSON object with a tool_uses array, using only currently "
                                "advertised tool names and no prose or [assistant requested tool] markers. If a later tool "
                                "depends on an earlier result, call only the prerequisite tool now."
                            ),
                        }
                    )
                    messages[:] = compact_messages(messages)
                    continue
                final_text = (
                    "The model repeatedly emitted tool-call-looking text that could not be parsed, so the requested "
                    "tools were not executed. The run stopped explicitly instead of reporting the workflow as complete."
                )
            science_validation_issue = validate_science_workflow_before_final(user_input, messages, final_text)
            if science_validation_issue:
                science_validation_attempts += 1
                if science_validation_attempts <= 3:
                    log_event(
                        "WARN",
                        "science_workflow_final_blocked",
                        attempt=science_validation_attempts,
                        project_id=successful_session_project_id(messages),
                    )
                    messages.append({"role": "assistant", "content": [block_to_dict(block) for block in response_content]})
                    messages.append({"role": "user", "content": science_validation_issue})
                    messages[:] = compact_messages(messages)
                    continue
                final_text = (
                    final_text.strip()
                    + "\n\n"
                    + "Science workflow validation is still failing after multiple attempts:\n"
                    + science_validation_issue
                ).strip()
            validation_issue = validate_before_final(user_input, tracked_task_ids)
            if validation_issue:
                validation_attempts += 1
                if validation_attempts <= 6:
                    messages.append({"role": "assistant", "content": [block_to_dict(block) for block in response_content]})
                    messages.append({"role": "user", "content": validation_issue})
                    messages[:] = compact_messages(messages)
                    continue
                final_text = (
                    final_text.strip()
                    + "\n\n"
                    + "Validation is still failing after multiple attempts:\n"
                    + validation_issue
                ).strip()
            trigger_hook("Stop", final_text)
            extract_memories(messages, final_text)
            log_event("AGENT", "final", text=final_text)
            return final_text

        rejected_tool_call_attempts = 0
        unparsed_tool_request_attempts = 0
        incomplete_tool_json_attempts = 0
        messages.append(
            {
                "role": "assistant",
                "content": [block_to_dict(block) for block in response_content],
            }
        )
        block = tool_blocks[0]
        result = run_tool(block, messages, current_handlers, raw_user_prompt=user_input)
        if normalize_tool_name(block_attr(block, "name")) == "create_task":
            tracked_task_ids.update(extract_task_ids(str(result.get("content", ""))))
        messages.append({"role": "user", "content": [result]})

        # Stuck-loop detector: track tool-name patterns across iterations
        iteration_pattern = "+".join(
            sorted(normalize_tool_name(block_attr(b, "name")) for b in tool_blocks)
        )
        recent_tool_patterns.append(iteration_pattern)
        if len(recent_tool_patterns) > 8:
            recent_tool_patterns[:] = recent_tool_patterns[-8:]
        if len(recent_tool_patterns) >= 5:
            tail = recent_tool_patterns[-5:]
            # Check if 4+ of the last 5 iterations use the same tool set
            from collections import Counter as _Counter
            pattern_counts = _Counter(tail)
            most_common_pattern, most_common_count = pattern_counts.most_common(1)[0]
            if most_common_count >= 4 and any(
                t in most_common_pattern for t in ("read_file", "glob", "read", "list_")
            ):
                nudge = (
                    f"[SYSTEM: STUCK LOOP DETECTED] You have called `{most_common_pattern}` "
                    f"in {most_common_count} of the last 5 iterations without making progress. "
                    "This is a dead loop. STOP repeating the same operations. "
                    "Reassess: (1) What are you actually trying to find or accomplish? "
                    "(2) Why have your previous attempts failed? "
                    "(3) What DIFFERENT approach can you take? "
                    "If you cannot find a file, the data may be stored inside a JSON structure "
                    "rather than as individual files. Use get_research_project or list_papergraph_records "
                    "to access it. If you are done, produce your final answer now."
                )
                messages.append({"role": "user", "content": nudge})
                log_event("WARN", "stuck_loop_nudge", pattern=most_common_pattern, count=most_common_count)
                recent_tool_patterns.clear()  # reset after nudge to avoid spamming

        messages[:] = compact_messages(messages)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the v8 autonomous multi-agent loop.")
    parser.add_argument(
        "--serve-cron",
        action="store_true",
        help="Keep the process alive after the prompt so durable cron jobs can fire.",
    )
    parser.add_argument("prompt", nargs="*", help="Task prompt. If omitted, read one line.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    user_input = " ".join(args.prompt).strip()
    if not user_input:
        user_input = input("User> ").strip()
    if not user_input:
        raise SystemExit("Empty prompt.")
    final_text = run_agent(user_input)
    if final_text.strip():
        print(final_text, flush=True)
    if args.serve_cron:
        while True:
            time.sleep(60)


if __name__ == "__main__":
    main()
