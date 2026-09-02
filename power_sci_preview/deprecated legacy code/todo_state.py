from __future__ import annotations

import json
import threading
import time
from dataclasses import asdict, dataclass, field
from typing import Any

try:
    from .log import log_event
except ImportError:
    from log import log_event


todo_lock = threading.Lock()
todos: list["TodoItem"] = []


@dataclass
class TodoItem:
    content: str
    status: str = "pending"
    priority: str = "medium"
    id: str = field(default_factory=lambda: f"todo_{time.time_ns()}")


def todo_write(items: list[dict[str, Any]] | list[str]) -> str:
    normalized: list[TodoItem] = []
    for item in items:
        if isinstance(item, str):
            normalized.append(TodoItem(content=item))
            continue
        content = str(item.get("content", "")).strip()
        if not content:
            continue
        status = normalize_status(str(item.get("status", "pending")))
        priority = normalize_priority(str(item.get("priority", "medium")))
        item_id = str(item.get("id") or f"todo_{time.time_ns()}")
        normalized.append(TodoItem(id=item_id, content=content, status=status, priority=priority))

    with todo_lock:
        todos[:] = normalized
        snapshot = [asdict(todo) for todo in todos]
    log_event("TODO", "write", count=len(snapshot))
    return render_todos(snapshot)


def list_todos() -> str:
    with todo_lock:
        snapshot = [asdict(todo) for todo in todos]
    return render_todos(snapshot)


def render_todos(snapshot: list[dict[str, str]]) -> str:
    if not snapshot:
        return "(no todos)"
    return json.dumps({"todos": snapshot}, ensure_ascii=False, indent=2)


def normalize_status(value: str) -> str:
    lowered = value.strip().lower()
    return lowered if lowered in {"pending", "in_progress", "completed"} else "pending"


def normalize_priority(value: str) -> str:
    lowered = value.strip().lower()
    return lowered if lowered in {"low", "medium", "high"} else "medium"
