"""Independent persistent ownership, cancellation and event state for branch B."""

import json
import os
from pathlib import Path

import psutil
from filelock import FileLock

from src.pipeline.science_run import atomic_write_json, utc_now


def state_lock(root: Path) -> FileLock:
    root.mkdir(parents=True, exist_ok=True)
    return FileLock(str(root / ".state.lock"), timeout=5)


def load_state(root: Path) -> dict:
    path = root / "branch_state.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def update_state(root: Path, **changes) -> dict:
    with state_lock(root):
        state = load_state(root)
        state.update(changes, updated_at=utc_now())
        atomic_write_json(root / "branch_state.json", state)
        return state


def event(root: Path, kind: str, **details) -> None:
    with state_lock(root):
        with (root / "events.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"at": utc_now(), "kind": kind, **details}, allow_nan=False) + "\n")


def owner() -> dict:
    return {"pid": os.getpid(), "create_time": psutil.Process().create_time()}


def owner_alive(identity: dict) -> bool:
    try:
        return abs(psutil.Process(identity["pid"]).create_time() - identity["create_time"]) < .01
    except (psutil.Error, KeyError, TypeError):
        return False


def request_cancel(root: Path) -> dict:
    return update_state(root, cancel_requested=True)
