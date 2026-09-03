from __future__ import annotations

from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import json

import pytest

from power_core_a.approval import require_protocol_approval
from power_core_a.artifact_store import ArtifactStore
from power_core_a.canonical import sha256_digest
from power_core_a.errors import (
    ApprovalRequired,
    IdempotencyConflict,
    InvalidStateTransition,
    StateJournalCorruption,
)
from power_core_a.schema_registry import SchemaRegistry
from power_core_a.state_machine import ResearchState, StateJournal


FIXTURES = Path(__file__).resolve().parents[1] / "examples_power_core_a" / "b0"


def brief() -> dict:
    return json.loads((FIXTURES / "research_brief.json").read_text(encoding="utf-8"))


def test_artifact_store_is_idempotent_and_versions_changed_content(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)
    first_payload = brief()
    first = store.put_json(
        artifact_id=first_payload["brief_id"], artifact_type="research_brief",
        contract_schema="ResearchBrief", payload=first_payload, producer="M00",
        created_at=first_payload["created_at"], idempotency_key="brief:first",
    )
    repeated = store.put_json(
        artifact_id=first_payload["brief_id"], artifact_type="research_brief",
        contract_schema="ResearchBrief", payload=first_payload, producer="M00",
        created_at=first_payload["created_at"], idempotency_key="brief:first",
    )
    assert repeated == first

    changed = {**first_payload, "title": "A changed but valid immutable revision"}
    second = store.put_json(
        artifact_id=changed["brief_id"], artifact_type="research_brief",
        contract_schema="ResearchBrief", payload=changed, producer="M00",
        created_at=changed["created_at"], idempotency_key="brief:second",
    )
    assert first["artifact_version"] == 1
    assert second["artifact_version"] == 2
    assert Path(tmp_path / first["relative_path"]).read_text(encoding="utf-8")


def test_artifact_idempotency_key_rejects_drift(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)
    payload = brief()
    kwargs = dict(
        artifact_id=payload["brief_id"], artifact_type="research_brief", contract_schema="ResearchBrief",
        producer="M00", created_at=payload["created_at"], idempotency_key="same-key",
    )
    store.put_json(payload=payload, **kwargs)
    with pytest.raises(IdempotencyConflict):
        store.put_json(payload={**payload, "title": "drift"}, **kwargs)


def test_artifact_write_recovers_after_payload_was_published_before_descriptor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = ArtifactStore(tmp_path)
    payload = brief()
    original = store._write_exclusive
    calls = 0

    def interrupt_after_payload(path: Path, body: bytes) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("simulated interruption before descriptor publication")
        original(path, body)

    with monkeypatch.context() as scoped:
        scoped.setattr(store, "_write_exclusive", interrupt_after_payload)
        with pytest.raises(OSError, match="simulated interruption"):
            store.put_json(
                artifact_id=payload["brief_id"], artifact_type="research_brief",
                contract_schema="ResearchBrief", payload=payload, producer="M00",
                created_at=payload["created_at"], idempotency_key="interrupted-write",
            )

    recovered = store.put_json(
        artifact_id=payload["brief_id"], artifact_type="research_brief",
        contract_schema="ResearchBrief", payload=payload, producer="M00",
        created_at=payload["created_at"], idempotency_key="interrupted-write",
    )
    assert recovered["artifact_version"] == 1
    assert store.read_json(recovered) == payload


def test_concurrent_identical_writers_converge_on_one_version(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)
    payload = brief()

    def write(index: int) -> dict:
        return store.put_json(
            artifact_id=payload["brief_id"], artifact_type="research_brief",
            contract_schema="ResearchBrief", payload=payload, producer="M00",
            created_at=payload["created_at"], idempotency_key=f"concurrent:{index}",
        )

    with ThreadPoolExecutor(max_workers=4) as executor:
        descriptors = list(executor.map(write, range(8)))
    assert {row["artifact_version"] for row in descriptors} == {1}
    assert len({row["content_hash"] for row in descriptors}) == 1


def test_state_machine_is_idempotent_and_recovers_from_events(tmp_path: Path) -> None:
    journal = StateJournal(tmp_path, "run_state_test")
    brief_hash = sha256_digest(brief())
    first = journal.initialize(actor="test", input_hashes=[brief_hash], idempotency_key="init")
    assert journal.initialize(actor="test", input_hashes=[brief_hash], idempotency_key="init") == first
    journal.transition(
        ResearchState.BRIEF_VALIDATED, trigger="VALID", actor="test",
        input_hashes=[brief_hash], idempotency_key="validated",
    )
    recovered = StateJournal(tmp_path, "run_state_test")
    assert recovered.current_state() is ResearchState.BRIEF_VALIDATED
    assert len(recovered.events()) == 2
    with pytest.raises(InvalidStateTransition):
        recovered.transition(
            ResearchState.PROTOCOL_FROZEN, trigger="SKIP", actor="test",
            input_hashes=[brief_hash], idempotency_key="illegal",
        )


def test_state_event_hash_chain_detects_tampering(tmp_path: Path) -> None:
    journal = StateJournal(tmp_path, "run_state_tamper")
    brief_hash = sha256_digest(brief())
    journal.initialize(actor="test", input_hashes=[brief_hash], idempotency_key="init")
    journal.transition(
        ResearchState.BRIEF_VALIDATED, trigger="VALID", actor="test",
        input_hashes=[brief_hash], idempotency_key="validated",
    )
    first_path = sorted(journal.events_dir.glob("*.json"))[0]
    event = json.loads(first_path.read_text(encoding="utf-8"))
    event["actor"] = "tampered_actor"
    first_path.write_text(json.dumps(event, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(StateJournalCorruption, match="hash chain"):
        journal.events()


def test_approval_is_bound_to_exact_protocol_hash() -> None:
    approval = {
        "schema_version": "approval_record_v1", "approval_id": "approval_test", "run_id": "run_test",
        "approval_type": "PROTOCOL_FREEZE", "decision": "APPROVED",
        "subject_artifact_hash": "sha256:" + "1" * 64, "approver_id": "teacher",
        "decided_at": "2026-08-25T12:00:00Z", "reason": "approved for test",
    }
    assert require_protocol_approval(
        approval, run_id="run_test", protocol_hash="sha256:" + "1" * 64
    )["decision"] == "APPROVED"
    with pytest.raises(ApprovalRequired, match="stale"):
        require_protocol_approval(
            approval, run_id="run_test", protocol_hash="sha256:" + "2" * 64
        )
