from __future__ import annotations

import random
import time
from dataclasses import dataclass
from typing import Any

try:
    from .compact import emergency_compact
    from .config import (
        FALLBACK_MODEL_ID,
        MAX_TOKENS,
        MODEL_ID,
        RECOVERY_BASE_DELAY_MS,
        RECOVERY_CONTINUATION_LIMIT,
        RECOVERY_MAX_DELAY_MS,
        RECOVERY_MAX_TOKENS_ESCALATED,
        RECOVERY_RETRY_LIMIT,
    )
    from .log import log_event
except ImportError:
    from compact import emergency_compact
    from config import (
        FALLBACK_MODEL_ID,
        MAX_TOKENS,
        MODEL_ID,
        RECOVERY_BASE_DELAY_MS,
        RECOVERY_CONTINUATION_LIMIT,
        RECOVERY_MAX_DELAY_MS,
        RECOVERY_MAX_TOKENS_ESCALATED,
        RECOVERY_RETRY_LIMIT,
    )
    from log import log_event


@dataclass
class RecoveryState:
    current_model: str = MODEL_ID
    current_max_tokens: int = MAX_TOKENS
    has_escalated: bool = False
    has_attempted_reactive_compact: bool = False
    recovery_count: int = 0
    consecutive_529: int = 0
    retry_count: int = 0


def create_response_with_recovery(
    client: Any,
    *,
    system: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    state: RecoveryState,
    focus: str = "",
) -> Any:
    while True:
        try:
            response = client.messages.create(
                model=state.current_model,
                max_tokens=state.current_max_tokens,
                system=system,
                messages=messages,
                tools=tools,
            )
            state.retry_count = 0
            state.consecutive_529 = 0
            if getattr(response, "stop_reason", None) == "max_tokens":
                if handle_max_tokens(response, messages, state) == "retry":
                    continue
            return response
        except Exception as exc:
            if recover_exception(exc, messages, state, focus=focus) == "retry":
                continue
            raise


def handle_max_tokens(response: Any, messages: list[dict[str, Any]], state: RecoveryState) -> str:
    if not state.has_escalated:
        state.current_max_tokens = max(state.current_max_tokens, RECOVERY_MAX_TOKENS_ESCALATED)
        state.has_escalated = True
        log_event("RECOVERY", "max_tokens_escalate", max_tokens=state.current_max_tokens)
        return "retry"

    if state.recovery_count >= RECOVERY_CONTINUATION_LIMIT:
        log_event("WARN", "max_tokens_continuation_limit", count=state.recovery_count)
        return "done"

    text = response_text(getattr(response, "content", []))
    if text:
        messages.append({"role": "assistant", "content": text})
    messages.append({"role": "user", "content": "Continue exactly where you left off. Be concise and do not restart."})
    state.recovery_count += 1
    log_event("RECOVERY", "max_tokens_continue", count=state.recovery_count)
    return "retry"


def recover_exception(
    exc: Exception,
    messages: list[dict[str, Any]],
    state: RecoveryState,
    *,
    focus: str = "",
) -> str:
    if is_prompt_too_long_error(exc):
        if state.has_attempted_reactive_compact:
            log_event("ERROR", "prompt_too_long_unrecoverable", error=exc)
            return "raise"
        messages[:] = emergency_compact(messages, focus=focus)
        state.has_attempted_reactive_compact = True
        log_event("RECOVERY", "prompt_too_long_compacted", messages=len(messages))
        return "retry"

    if is_rate_limit_error(exc):
        state.retry_count += 1
        state.consecutive_529 = state.consecutive_529 + 1 if is_overloaded_error(exc) else 0
        if state.consecutive_529 >= 3 and FALLBACK_MODEL_ID != state.current_model:
            state.current_model = FALLBACK_MODEL_ID
            state.consecutive_529 = 0
            log_event("RECOVERY", "fallback_model", model=state.current_model)
        if state.retry_count > RECOVERY_RETRY_LIMIT:
            log_event("ERROR", "rate_limit_retries_exhausted", error=exc)
            return "raise"
        delay = backoff_seconds(state.retry_count)
        log_event("RECOVERY", "backoff", attempt=state.retry_count, seconds=round(delay, 2))
        time.sleep(delay)
        return "retry"

    return "raise"


def backoff_seconds(attempt: int) -> float:
    delay_ms = min(RECOVERY_BASE_DELAY_MS * (2 ** max(0, attempt - 1)), RECOVERY_MAX_DELAY_MS)
    jitter_ms = random.uniform(0, delay_ms * 0.1)
    return (delay_ms + jitter_ms) / 1000


def is_prompt_too_long_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return any(marker in text for marker in ("prompt_too_long", "context length", "context_length", "too many tokens", "maximum context"))


def is_rate_limit_error(exc: Exception) -> bool:
    text = str(exc).lower()
    status = getattr(exc, "status_code", None)
    return status in {429, 529} or "429" in text or "529" in text or "rate limit" in text or "overloaded" in text


def is_overloaded_error(exc: Exception) -> bool:
    text = str(exc).lower()
    status = getattr(exc, "status_code", None)
    return status == 529 or "529" in text or "overloaded" in text


def response_text(content: list[Any]) -> str:
    parts: list[str] = []
    for block in content:
        block_type = block.get("type") if isinstance(block, dict) else getattr(block, "type", None)
        if block_type == "text":
            parts.append(block.get("text", "") if isinstance(block, dict) else getattr(block, "text", ""))
    return "\n".join(part for part in parts if part)
