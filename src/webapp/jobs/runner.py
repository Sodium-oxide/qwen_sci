"""Thread-based Job runner backed by durable leases and cooperative cancel."""

from __future__ import annotations

import os
import socket
import threading
import time
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .errors import JobInputError, JobLeaseLost, JobStateError
from .models import JobExecutionResult, JobRecord
from .registry import JobRegistry
from .store import JobStore


class JobCancelled(RuntimeError):
    """Raised by a worker at a safe cancellation boundary."""


class JobInterrupted(RuntimeError):
    """Raised at a safe boundary while the service is shutting down."""


@dataclass(slots=True)
class JobContext:
    """Trusted worker context; it never exposes a client-supplied command."""

    job: JobRecord
    job_dir: Path
    store: JobStore
    lease_owner: str
    lease_seconds: float
    _cancel_event: threading.Event
    _shutdown_event: threading.Event | None = None
    deadline: float | None = None

    def is_cancel_requested(self) -> bool:
        if self._shutdown_event is not None and self._shutdown_event.is_set():
            raise JobInterrupted("The Job will resume after the service restarts.")
        latest = self.store.get(self.job.job_id)
        if (
            latest.lease_owner != self.lease_owner
            or latest.attempt != self.job.attempt
            or latest.status not in {"RUNNING", "CANCEL_REQUESTED"}
        ):
            raise JobLeaseLost("The Job execution attempt has changed.")
        requested = latest.status == "CANCEL_REQUESTED"
        if requested:
            self._cancel_event.set()
        return requested or self._cancel_event.is_set()

    def check_cancelled(self) -> None:
        if self.is_cancel_requested():
            raise JobCancelled("Job cancellation was requested.")
        if self.deadline is not None and time.monotonic() >= self.deadline:
            raise TimeoutError("The Job exceeded its execution time limit.")

    def remaining_seconds(self, maximum: float = 1800) -> float:
        self.check_cancelled()
        if self.deadline is None:
            return maximum
        return max(0.01, min(maximum, self.deadline - time.monotonic()))

    def checkpoint(self, *, progress: int | None = None, current_step: str | None = None) -> JobRecord:
        self.check_cancelled()
        return self.store.heartbeat(
            self.job.job_id,
            lease_owner=self.lease_owner,
            lease_seconds=self.lease_seconds,
            progress=progress,
            current_step=current_step,
        )


class JobRunner:
    """Execute registered handlers while persisting lifecycle changes."""

    def __init__(
        self,
        store: JobStore,
        registry: JobRegistry | None = None,
        *,
        max_workers: int = 4,
        lease_seconds: float = 120.0,
        stale_after_seconds: float = 120.0,
        heartbeat_seconds: float | None = None,
        default_timeout_seconds: float = 1800.0,
    ) -> None:
        self.store = store
        self.registry = registry or JobRegistry()
        self.max_workers = max(1, int(max_workers))
        self.lease_seconds = max(5.0, float(lease_seconds))
        self.stale_after_seconds = max(5.0, float(stale_after_seconds))
        self.heartbeat_seconds = min(self.lease_seconds / 3.0, float(heartbeat_seconds or 15.0))
        self.default_timeout_seconds = max(0.01, float(default_timeout_seconds))
        self.worker_id = f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:12]}"
        self._executor = ThreadPoolExecutor(max_workers=self.max_workers, thread_name_prefix="qwensci-job")
        self._futures: dict[str, Future[object]] = {}
        self._lock = threading.RLock()
        self._closed = False
        self._stop_event = threading.Event()
        self._maintenance_thread: threading.Thread | None = None

    def submit(self, job_id: str) -> bool:
        with self._lock:
            if self._closed:
                raise JobStateError("Job runner is shut down.")
            active = self._futures.get(job_id)
            if active is not None and not active.done():
                return False
            future = self._executor.submit(self._execute, job_id)
            self._futures[job_id] = future
            future.add_done_callback(lambda completed, current=job_id: self._finish(current, completed))
            return True

    def start(self) -> None:
        with self._lock:
            if self._closed:
                raise JobStateError("Job runner is shut down.")
            if self._maintenance_thread is not None:
                return
            self._maintenance_thread = threading.Thread(
                target=self._maintenance_loop, name="qwensci-job-recovery", daemon=True
            )
            self._maintenance_thread.start()

    def _maintenance_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self.recover_and_submit()
            except (JobStateError, OSError):
                if self._closed:
                    return
            except Exception:
                if self._closed:
                    return
            self._stop_event.wait(min(5.0, self.stale_after_seconds / 3.0))

    def recover_and_submit(self) -> list[str]:
        self.store.reclaim_stale_jobs(stale_after_seconds=self.stale_after_seconds)
        queued = self.store.list(statuses=("QUEUED",), limit=1_000)
        submitted: list[str] = []
        for record in queued:
            if self.registry.get(record.kind) is None:
                continue
            try:
                if not self.submit(record.job_id):
                    continue
            except JobStateError:
                continue
            submitted.append(record.job_id)
        return submitted

    def request_cancel(self, job_id: str) -> JobRecord:
        return self.store.request_cancel(job_id)

    def is_active(self, job_id: str) -> bool:
        with self._lock:
            future = self._futures.get(job_id)
            return future is not None and not future.done()

    def shutdown(self, *, wait: bool = True) -> None:
        with self._lock:
            self._closed = True
            self._stop_event.set()
        if self._maintenance_thread is not None:
            self._maintenance_thread.join(timeout=5)
        self._executor.shutdown(wait=wait, cancel_futures=False)

    def _execute(self, job_id: str) -> None:
        execution_owner = f"{self.worker_id}:{uuid.uuid4().hex[:12]}"
        claimed = self.store.claim(
            job_id,
            lease_owner=execution_owner,
            lease_seconds=self.lease_seconds,
        )
        if claimed is None:
            return
        handler = self.registry.get(claimed.kind)
        if handler is None:
            self.store.transition(
                claimed.job_id,
                "FAILED",
                lease_owner=execution_owner,
                error_code="HANDLER_UNAVAILABLE",
                error_message=f"No handler is registered for Job kind '{claimed.kind}'.",
                retryable=False,
            )
            return

        cancel_event = threading.Event()
        stop_heartbeat = threading.Event()
        heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop,
            args=(claimed.job_id, execution_owner, cancel_event, stop_heartbeat),
            name=f"qwensci-heartbeat-{claimed.job_id}",
            daemon=True,
        )
        context = JobContext(
            job=claimed,
            job_dir=self.store.job_directory(claimed.job_id),
            store=self.store,
            lease_owner=execution_owner,
            lease_seconds=self.lease_seconds,
            _cancel_event=cancel_event,
            _shutdown_event=self._stop_event,
            deadline=time.monotonic() + self.default_timeout_seconds,
        )
        heartbeat_thread.start()
        try:
            result = handler(context)
            if context.is_cancel_requested():
                self.store.transition(
                    claimed.job_id,
                    "CANCELLED",
                    lease_owner=execution_owner,
                    current_step="cancelled_at_safe_boundary",
                )
                return
            execution_result = self._normalize_result(result)
            self.store.transition(
                claimed.job_id,
                execution_result.status,
                lease_owner=execution_owner,
                progress=execution_result.progress,
                current_step=execution_result.current_step,
                output_artifact_ids=execution_result.output_artifact_ids,
            )
        except (JobLeaseLost, JobInterrupted):
            return
        except JobCancelled:
            try:
                self.store.transition(
                    claimed.job_id, "CANCELLED", lease_owner=execution_owner,
                    current_step="cancelled_at_safe_boundary",
                )
            except JobLeaseLost:
                return
        except Exception as exc:
            try:
                latest = self.store.get(claimed.job_id)
                self.store.transition(
                    claimed.job_id,
                    "CANCELLED" if latest.status == "CANCEL_REQUESTED" else "FAILED",
                    lease_owner=execution_owner,
                    error_code=getattr(exc, "code", exc.__class__.__name__.upper()),
                    error_message=str(exc) or exc.__class__.__name__,
                    retryable=getattr(exc, "retryable", not isinstance(exc, (ValueError, JobInputError))),
                    current_step="worker_failed",
                )
            except JobLeaseLost:
                return
        finally:
            stop_heartbeat.set()
            heartbeat_thread.join(timeout=2)

    def _heartbeat_loop(
        self,
        job_id: str,
        lease_owner: str,
        cancel_event: threading.Event,
        stop_event: threading.Event,
    ) -> None:
        interval = max(0.1, self.heartbeat_seconds)
        while not stop_event.wait(interval):
            if self._stop_event.is_set():
                return
            try:
                record = self.store.heartbeat(
                    job_id,
                    lease_owner=lease_owner,
                    lease_seconds=self.lease_seconds,
                )
                if record.status == "CANCEL_REQUESTED":
                    cancel_event.set()
            except Exception:
                return

    @staticmethod
    def _normalize_result(value: Any) -> JobExecutionResult:
        if value is None:
            return JobExecutionResult()
        if isinstance(value, JobExecutionResult):
            return value
        if isinstance(value, dict):
            status = value.get("status", "SUCCEEDED")
            if status not in {"SUCCEEDED", "WAITING_FOR_REVIEW"}:
                raise JobStateError("Worker result has an unsupported status.")
            raw_artifacts = value.get("output_artifact_ids", ())
            artifacts = tuple(str(item) for item in raw_artifacts) if isinstance(raw_artifacts, (list, tuple)) else ()
            return JobExecutionResult(
                status=status,
                output_artifact_ids=artifacts,
                progress=value.get("progress", 100),
                current_step=value.get("current_step"),
            )
        raise JobStateError("Worker must return JobExecutionResult, a mapping, or None.")

    def _finish(self, job_id: str, future: Future[object]) -> None:
        with self._lock:
            if self._futures.get(job_id) is future:
                self._futures.pop(job_id, None)
