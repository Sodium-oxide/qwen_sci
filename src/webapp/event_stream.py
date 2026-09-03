"""SSE projection over durable per-run event logs."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Mapping
from pathlib import Path

from fastapi import Request

from .redaction import safe_payload
from .schemas import RunEventView


def read_events(path: Path, *, after: int = 0) -> list[RunEventView]:
    if after < 0:
        after = 0
    if not path.is_file():
        return []
    events: list[RunEventView] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    for sequence, line in enumerate(lines, start=1):
        if sequence <= after:
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(item, Mapping):
            continue
        events.append(
            RunEventView(
                event_id=str(sequence),
                event_type=str(item.get("event_type") or "RUN_EVENT"),
                timestamp=str(item.get("timestamp") or ""),
                payload=safe_payload({key: value for key, value in item.items() if key not in {"event_type", "timestamp"}}),
            )
        )
    return events


async def stream_events(
    request: Request,
    *,
    events_path: Path,
    after: int = 0,
    follow: bool = True,
) -> AsyncIterator[dict[str, str]]:
    cursor = after
    while True:
        for event in read_events(events_path, after=cursor):
            cursor = int(event.event_id)
            data = event.model_dump_json()
            yield {
                "id": event.event_id,
                "event": event.event_type,
                "data": data,
            }
            yield {
                "id": event.event_id,
                "event": "run_event",
                "data": data,
            }
        if not follow or await request.is_disconnected():
            return
        yield {"event": "keepalive", "data": "{}"}
        await asyncio.sleep(1)
