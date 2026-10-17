"""Trusted server-side Job handler registry."""

from __future__ import annotations

from collections.abc import Callable
from threading import RLock
from typing import Any

from .errors import JobStateError
from .models import JobKind


JobHandler = Callable[[Any], Any]


class JobRegistry:
    """Map an allow-listed Job kind to a server-owned worker callable."""

    def __init__(self) -> None:
        self._handlers: dict[JobKind, JobHandler] = {}
        self._lock = RLock()

    def register(self, kind: JobKind, handler: JobHandler, *, replace: bool = False) -> None:
        if kind not in {"science", "figure", "polish", "translation"}:
            raise JobStateError(f"Unsupported Job kind: {kind}")
        if not callable(handler):
            raise JobStateError("Job handler must be callable.")
        with self._lock:
            if kind in self._handlers and not replace:
                raise JobStateError(f"A handler is already registered for Job kind '{kind}'.")
            self._handlers[kind] = handler

    def get(self, kind: JobKind) -> JobHandler | None:
        with self._lock:
            return self._handlers.get(kind)

    def kinds(self) -> tuple[JobKind, ...]:
        with self._lock:
            return tuple(sorted(self._handlers))
