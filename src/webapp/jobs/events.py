"""Replay durable Job events without the legacy run-event envelope."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator

from fastapi import Request

from ..redaction import safe_payload
from .store import JobStore


async def stream_job_events(
    request: Request,
    *,
    store: JobStore,
    job_id: str,
    after: int = 0,
    follow: bool = True,
) -> AsyncIterator[dict[str, str]]:
    cursor = max(0, after)
    while True:
        for event in store.read_events(job_id, after=cursor):
            cursor = int(str(event["event_id"]))
            yield {
                "id": str(cursor),
                "event": str(event.get("event_type", "JOB_EVENT")),
                "data": json.dumps(safe_payload(event), ensure_ascii=False),
            }
        if not follow or await request.is_disconnected():
            return
        yield {"event": "keepalive", "data": "{}"}
        await asyncio.sleep(1)
