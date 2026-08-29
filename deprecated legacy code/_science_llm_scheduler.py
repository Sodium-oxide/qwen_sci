"""Fair process-wide scheduling for scientific LLM batches."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from threading import Condition
from time import perf_counter
from typing import Any, Callable

try:
    from .config import SCIENCE_PROPOSITION_LLM_MAX_INFLIGHT
    from ._science_execution_policy import resolve_science_execution_policy
    from .log import log_event
except ImportError:
    from config import SCIENCE_PROPOSITION_LLM_MAX_INFLIGHT
    from _science_execution_policy import resolve_science_execution_policy
    from log import log_event


@dataclass(frozen=True)
class LLMJob:
    candidate_id: str
    stage: str
    batch_id: str
    prompt_chars: int
    max_tokens: int
    priority: int = 0
    input_span_count: int = 0
    candidate_max_inflight: int = 1


class ScienceLLMScheduler:
    def __init__(self, max_inflight: int) -> None:
        self.max_inflight = max(1, int(max_inflight))
        self._condition = Condition()
        self._pending: deque[tuple[int, LLMJob]] = deque()
        self._active_candidates: dict[str, int] = {}
        self._inflight = 0
        self._ticket = 0

    def _next_eligible_ticket(self) -> int | None:
        for ticket, job in self._pending:
            if self._active_candidates.get(job.candidate_id, 0) < max(
                1, int(job.candidate_max_inflight or 1)
            ):
                return ticket
        return None

    def run(self, job: LLMJob, call: Callable[[], Any]) -> Any:
        queued_at = perf_counter()
        candidate_limit = max(1, int(job.candidate_max_inflight or 1))
        with self._condition:
            self._ticket += 1
            ticket = self._ticket
            self._pending.append((ticket, job))
            while (
                self._inflight >= self.max_inflight
                or self._active_candidates.get(job.candidate_id, 0) >= candidate_limit
                or self._next_eligible_ticket() != ticket
            ):
                self._condition.wait()
            self._pending.remove((ticket, job))
            self._inflight += 1
            self._active_candidates[job.candidate_id] = (
                self._active_candidates.get(job.candidate_id, 0) + 1
            )
            scheduler_inflight_at_start = self._inflight
            candidate_inflight_at_start = self._active_candidates[job.candidate_id]
        queued_ms = round((perf_counter() - queued_at) * 1000, 2)
        started_at = perf_counter()
        status = "COMPLETED"
        error_type = ""
        error_message = ""
        provider_code = ""
        request_id = ""
        try:
            return call()
        except Exception as exc:
            error_type = type(exc).__name__
            error_message = " ".join(str(exc).split())[:500]
            diagnostics = getattr(exc, "diagnostics", None)
            if isinstance(diagnostics, dict):
                error_message = str(
                    diagnostics.get("error_message") or error_message
                )[:500]
                provider_code = str(diagnostics.get("provider_code") or "")
                request_id = str(diagnostics.get("request_id") or "")
            error_text = str(exc).casefold()
            status = (
                "LLM_BATCH_TIMEOUT"
                if "timeout" in error_text or "timed out" in error_text
                else "LLM_RATE_LIMITED"
                if "rate limit" in error_text or "too many requests" in error_text
                else "LLM_BATCH_FAILED"
            )
            raise
        finally:
            elapsed_ms = round((perf_counter() - started_at) * 1000, 2)
            with self._condition:
                self._inflight -= 1
                remaining = self._active_candidates.get(job.candidate_id, 1) - 1
                if remaining > 0:
                    self._active_candidates[job.candidate_id] = remaining
                else:
                    self._active_candidates.pop(job.candidate_id, None)
                self._condition.notify_all()
            log_event(
                "SCIENCE" if status == "COMPLETED" else "WARN",
                "science_llm_job_completed",
                candidate_id=job.candidate_id,
                stage=job.stage,
                batch_id=job.batch_id,
                input_chars=job.prompt_chars,
                input_span_count=job.input_span_count,
                max_tokens=job.max_tokens,
                priority=job.priority,
                queued_ms=queued_ms,
                scheduler_inflight_at_start=scheduler_inflight_at_start,
                candidate_inflight_at_start=candidate_inflight_at_start,
                candidate_max_inflight=candidate_limit,
                elapsed_ms=elapsed_ms,
                status=status,
                error_type=error_type,
                error_message=error_message,
                provider_code=provider_code,
                request_id=request_id,
            )


_DEFAULT_POLICY = resolve_science_execution_policy({})
_SCHEDULER = ScienceLLMScheduler(_DEFAULT_POLICY.max_inflight)
_PROPOSITION_SCHEDULER = ScienceLLMScheduler(
    SCIENCE_PROPOSITION_LLM_MAX_INFLIGHT
)


def run_science_llm_job(job: LLMJob, call: Callable[[], Any]) -> Any:
    scheduler = (
        _PROPOSITION_SCHEDULER
        if job.stage.startswith(("proposition_", "slot_alignment_"))
        else _SCHEDULER
    )
    return scheduler.run(job, call)
