"""Append-only state machine with idempotent transitions and recovery (M00)."""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Any
from uuid import uuid4
from datetime import datetime, timezone
import json
import os

from .canonical import canonical_json_bytes, require_safe_identifier, sha256_bytes
from .errors import IdempotencyConflict, InvalidStateTransition, StateJournalCorruption
from .schema_registry import SchemaRegistry


class ResearchState(str, Enum):
    BRIEF_DRAFT = "BRIEF_DRAFT"
    BRIEF_VALIDATED = "BRIEF_VALIDATED"
    CASE_BOUND = "CASE_BOUND"
    PROTOCOL_DRAFT = "PROTOCOL_DRAFT"
    APPROVAL_PENDING = "APPROVAL_PENDING"
    PROTOCOL_FROZEN = "PROTOCOL_FROZEN"


ALLOWED_TRANSITIONS: dict[ResearchState, ResearchState] = {
    ResearchState.BRIEF_DRAFT: ResearchState.BRIEF_VALIDATED,
    ResearchState.BRIEF_VALIDATED: ResearchState.CASE_BOUND,
    ResearchState.CASE_BOUND: ResearchState.PROTOCOL_DRAFT,
    ResearchState.PROTOCOL_DRAFT: ResearchState.APPROVAL_PENDING,
    ResearchState.APPROVAL_PENDING: ResearchState.PROTOCOL_FROZEN,
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class StateJournal:
    def __init__(self, root: Path | str, run_id: str, registry: SchemaRegistry | None = None) -> None:
        self.root = Path(root).resolve()
        self.run_id = require_safe_identifier(run_id, field="run_id")
        self.registry = registry or SchemaRegistry()
        self.events_dir = self.root / "runs" / self.run_id / "state" / "events"

    def _lock(self):
        try:
            from filelock import FileLock
        except ImportError as exc:
            raise RuntimeError(
                "Role A state locking requires filelock; install requirements-power-core-a.txt"
            ) from exc
        lock_path = self.root / ".locks" / "state" / f"{self.run_id}.lock"
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        return FileLock(str(lock_path), timeout=10)

    @staticmethod
    def _write_event_exclusive(path: Path, body: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.parent / f".{path.name}.tmp.{uuid4().hex}"
        try:
            with temporary.open("xb") as stream:
                stream.write(body)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(temporary, path)
            except FileExistsError as exc:
                raise StateJournalCorruption(
                    "State event path already exists", context={"path": str(path)}
                ) from exc
            except OSError:
                try:
                    with path.open("xb") as destination:
                        destination.write(body)
                        destination.flush()
                        os.fsync(destination.fileno())
                except FileExistsError as exc:
                    raise StateJournalCorruption(
                        "State event path already exists", context={"path": str(path)}
                    ) from exc
        finally:
            temporary.unlink(missing_ok=True)

    def events(self) -> list[dict[str, Any]]:
        paths = sorted(self.events_dir.glob("[0-9][0-9][0-9][0-9][0-9][0-9]_*.json"))
        events: list[dict[str, Any]] = []
        previous_hash: str | None = None
        previous_state: str | None = None
        for expected_sequence, path in enumerate(paths, start=1):
            try:
                event = json.loads(path.read_text(encoding="utf-8"))
                self.registry.validate("StateTransitionEvent", event)
            except Exception as exc:
                raise StateJournalCorruption(
                    "State event cannot be decoded or validated", context={"path": str(path)}
                ) from exc
            if event["sequence"] != expected_sequence or event["run_id"] != self.run_id:
                raise StateJournalCorruption("State event sequence or run identity mismatch", context={"path": str(path)})
            if event["previous_event_hash"] != previous_hash or event["from_state"] != previous_state:
                raise StateJournalCorruption("State event hash chain is broken", context={"path": str(path)})
            previous_hash = sha256_bytes(canonical_json_bytes(event))
            previous_state = event["to_state"]
            events.append(event)
        return events

    def current_state(self) -> ResearchState | None:
        events = self.events()
        return ResearchState(events[-1]["to_state"]) if events else None

    def initialize(
        self,
        *,
        actor: str,
        input_hashes: list[str],
        idempotency_key: str,
        occurred_at: str | None = None,
    ) -> dict[str, Any]:
        return self._append(
            expected_from=None,
            target=ResearchState.BRIEF_DRAFT,
            trigger="INITIALIZE_RUN",
            actor=actor,
            input_hashes=input_hashes,
            idempotency_key=idempotency_key,
            occurred_at=occurred_at,
        )

    def transition(
        self,
        target: ResearchState,
        *,
        trigger: str,
        actor: str,
        input_hashes: list[str],
        idempotency_key: str,
        occurred_at: str | None = None,
    ) -> dict[str, Any]:
        return self._append(
            expected_from=self.current_state(), target=target, trigger=trigger, actor=actor,
            input_hashes=input_hashes, idempotency_key=idempotency_key, occurred_at=occurred_at,
        )

    def _append(
        self,
        *,
        expected_from: ResearchState | None,
        target: ResearchState,
        trigger: str,
        actor: str,
        input_hashes: list[str],
        idempotency_key: str,
        occurred_at: str | None,
    ) -> dict[str, Any]:
        with self._lock():
            events = self.events()
            for event in events:
                if event["idempotency_key"] == idempotency_key:
                    if event["to_state"] != target.value or event["input_hashes"] != sorted(set(input_hashes)):
                        raise IdempotencyConflict(
                            "State idempotency key was reused for a different transition",
                            context={"key": idempotency_key, "event_id": event["event_id"]},
                        )
                    return event

            current = ResearchState(events[-1]["to_state"]) if events else None
            if current != expected_from:
                raise InvalidStateTransition(
                    "State changed before transition commit",
                    context={"expected": expected_from.value if expected_from else None, "current": current.value if current else None},
                )
            if current is None:
                if target is not ResearchState.BRIEF_DRAFT:
                    raise InvalidStateTransition("A new run must start at BRIEF_DRAFT")
            elif ALLOWED_TRANSITIONS.get(current) is not target:
                raise InvalidStateTransition(
                    f"Transition {current.value} -> {target.value} is not allowed",
                    context={"from": current.value, "to": target.value},
                )

            sequence = len(events) + 1
            prior_hash = sha256_bytes(canonical_json_bytes(events[-1])) if events else None
            event_seed = f"{self.run_id}:{sequence}:{idempotency_key}:{target.value}"
            event = {
                "schema_version": "state_transition_event_v1",
                "event_id": "evt_" + sha256_bytes(event_seed.encode("utf-8")).split(":", 1)[1][:24],
                "sequence": sequence,
                "run_id": self.run_id,
                "from_state": current.value if current else None,
                "to_state": target.value,
                "trigger": trigger,
                "actor": actor,
                "occurred_at": occurred_at or utc_now(),
                "idempotency_key": idempotency_key,
                "input_hashes": sorted(set(input_hashes)),
                "previous_event_hash": prior_hash,
            }
            self.registry.validate("StateTransitionEvent", event)
            path = self.events_dir / f"{sequence:06d}_{event['event_id']}.json"
            self._write_event_exclusive(path, canonical_json_bytes(event, pretty=True) + b"\n")
            return event
