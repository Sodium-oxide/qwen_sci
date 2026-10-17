from __future__ import annotations

import json
import time
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from src.webapp.jobs import (
    JobConflictError,
    JobExecutionResult,
    JobRegistry,
    JobRunner,
    JobStateError,
    JobStore,
)
from src.webapp.api import create_app
from fastapi.testclient import TestClient


def _store(tmp_path: Path) -> JobStore:
    return JobStore(tmp_path / "control" / "qwensci.db", job_root=tmp_path / "control" / "jobs")


def _create(store: JobStore, **kwargs):
    return store.create(
        kind=kwargs.pop("kind", "polish"),
        input_manifest_id=kwargs.pop("input_manifest_id", "manifest-1"),
        input_manifest_sha256=kwargs.pop("input_manifest_sha256", "a" * 64),
        request_hash=kwargs.pop("request_hash", "b" * 64),
        **kwargs,
    )


def test_job_store_is_idempotent_and_rejects_conflicting_reuse(tmp_path: Path) -> None:
    store = _store(tmp_path)
    first = _create(store, idempotency_key="same-request")
    same = _create(store, idempotency_key="same-request")

    assert same.job_id == first.job_id
    assert len(store.list()) == 1

    with pytest.raises(JobConflictError):
        _create(store, idempotency_key="same-request", request_hash="different")


def test_job_store_claim_transition_and_cancel_are_durable(tmp_path: Path) -> None:
    store = _store(tmp_path)
    created = _create(store)
    claimed = store.claim(created.job_id, lease_owner="worker-1")

    assert claimed is not None
    assert claimed.status == "RUNNING"
    assert claimed.attempt == 1
    assert store.heartbeat(created.job_id, lease_owner="worker-1", progress=30).progress == 30
    assert store.request_cancel(created.job_id).status == "CANCEL_REQUESTED"

    with pytest.raises(JobStateError):
        store.transition(created.job_id, "SUCCEEDED", lease_owner="worker-2")

    cancelled = store.transition(
        created.job_id,
        "CANCELLED",
        lease_owner="worker-1",
        current_step="safe-boundary",
    )
    assert cancelled.status == "CANCELLED"
    assert store.read_events(created.job_id)[-1]["event_type"] == "JOB_CANCELLED"


def test_job_store_reclaims_expired_lease_for_retry(tmp_path: Path) -> None:
    store = _store(tmp_path)
    created = _create(store, max_attempts=2)
    claimed = store.claim(created.job_id, lease_owner="dead-worker", lease_seconds=1)
    assert claimed is not None

    time.sleep(1.1)
    reclaimed = store.reclaim_stale_jobs(stale_after_seconds=1)

    assert [item.job_id for item in reclaimed] == [created.job_id]
    assert store.get(created.job_id).status == "QUEUED"
    assert store.get(created.job_id).retryable is True


def test_job_runner_persists_success_and_artifacts(tmp_path: Path) -> None:
    store = _store(tmp_path)
    registry = JobRegistry()

    def worker(context):
        context.checkpoint(progress=50, current_step="render")
        return JobExecutionResult(
            status="SUCCEEDED",
            output_artifact_ids=("artifact-1",),
            current_step="published",
        )

    registry.register("polish", worker)
    runner = JobRunner(store, registry, max_workers=1, lease_seconds=5)
    created = _create(store)
    runner.submit(created.job_id)

    deadline = time.time() + 5
    while time.time() < deadline and store.get(created.job_id).status not in {"SUCCEEDED", "FAILED"}:
        time.sleep(0.02)

    result = store.get(created.job_id)
    runner.shutdown()
    assert result.status == "SUCCEEDED"
    assert result.output_artifact_ids == ("artifact-1",)
    assert json.loads((store.job_directory(created.job_id) / "job.json").read_text())[
        "status"
    ] == "SUCCEEDED"


def test_job_api_and_shared_file_api_use_safe_ids(tmp_path: Path) -> None:
    app = create_app(run_root=tmp_path / "science-runs", serve_frontend=False)
    client = TestClient(app)
    uploaded = client.post(
        "/api/files",
        files={"file": ("evidence.csv", b"a,b\n1,2\n", "text/csv")},
        data={"project_id": "project-1", "sensitivity": "controlled"},
    )

    assert uploaded.status_code == 201, uploaded.text
    record = uploaded.json()
    assert record["file_id"].startswith("file-")
    assert "tmp" not in json.dumps(record).lower()
    assert client.get(record["content_url"]).content == b"a,b\n1,2\n"
    assert client.get("/api/files/file-../../secret").status_code == 404

    job = app.state.job_store.create(
        kind="polish",
        input_manifest_id=record["file_id"],
        input_manifest_sha256=record["sha256"],
        request_hash="c" * 64,
        project_id="project-1",
    )
    response = client.get(f"/api/jobs/{job.job_id}")
    assert response.status_code == 200
    assert response.json()["status"] == "QUEUED"
    cancelled = client.post(f"/api/jobs/{job.job_id}/actions", json={"type": "cancel"})
    assert cancelled.status_code == 202
    assert cancelled.json()["status"] == "CANCELLED"


def test_competing_workers_claim_once_and_preserve_revision_on_recovery(tmp_path: Path) -> None:
    store = _store(tmp_path)
    record = _create(store)
    with ThreadPoolExecutor(max_workers=2) as executor:
        claims = list(executor.map(lambda owner: store.claim(record.job_id, lease_owner=owner), ("first", "second")))
    assert sum(claim is not None for claim in claims) == 1
    with store._connection() as connection:
        connection.execute("UPDATE jobs SET lease_until = '2000-01-01T00:00:00Z' WHERE job_id = ?", (record.job_id,))
    store.reclaim_stale_jobs()
    recovered = store.claim(record.job_id, lease_owner="recovered")
    assert recovered.attempt == 2
    assert recovered.revision == 1
    store.transition(record.job_id, "WAITING_FOR_REVIEW", lease_owner="recovered")
    assert store.transition(record.job_id, "QUEUED").revision == 2


def test_state_and_events_rollback_together_on_event_failure(tmp_path: Path, monkeypatch) -> None:
    store = _store(tmp_path)
    record = _create(store)
    before = store.read_events(record.job_id)

    def fail_event(*_args, **_kwargs):
        raise sqlite3.OperationalError("simulated disk failure")

    monkeypatch.setattr(store, "_insert_event", fail_event)
    with pytest.raises(sqlite3.OperationalError):
        store.claim(record.job_id, lease_owner="worker")
    assert store.get(record.job_id).status == "QUEUED"
    assert store.read_events(record.job_id) == before


def test_event_replay_survives_missing_jsonl_and_restart(tmp_path: Path) -> None:
    store = _store(tmp_path)
    record = _create(store)
    cursor = int(store.read_events(record.job_id)[-1]["event_id"])
    store.claim(record.job_id, lease_owner="worker")
    store.events_path(record.job_id).unlink()
    reopened = _store(tmp_path)
    assert reopened.schema_version == "job_store_v3"
    events = reopened.read_events(record.job_id, after=cursor)
    assert [event["event_type"] for event in events] == ["JOB_STARTED"]


def test_v2_migration_imports_legacy_event_cursor_once(tmp_path: Path) -> None:
    store = _store(tmp_path)
    record = _create(store)
    manifest = {"input": {"files": [{"file_id": "file-" + "a" * 32}]}}
    content = json.dumps(manifest).encode("utf-8")
    (store.job_directory(record.job_id) / "input.json").write_bytes(content)
    with store._connection() as connection:
        import hashlib

        connection.execute("UPDATE jobs SET input_manifest_sha256 = ? WHERE job_id = ?", (hashlib.sha256(content).hexdigest(), record.job_id))
        connection.execute("DROP TABLE job_events")
        connection.execute("DROP TABLE job_file_references")
        connection.execute("ALTER TABLE jobs DROP COLUMN revision")
        connection.execute("PRAGMA user_version = 2")
    reopened = _store(tmp_path)
    assert reopened.get(record.job_id).revision == 1
    assert len(reopened.read_events(record.job_id)) == 2
    assert len(_store(tmp_path).read_events(record.job_id)) == 2
    assert reopened.file_is_referenced("file-" + "a" * 32)

