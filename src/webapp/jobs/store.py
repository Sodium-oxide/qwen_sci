"""SQLite-backed durable Job store with filesystem event snapshots."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import RLock
from typing import Any, Iterator, Mapping, Sequence

from filelock import FileLock, Timeout

from ..redaction import safe_payload, safe_text
from .errors import JobConflictError, JobLeaseLost, JobNotFoundError, JobStateError
from .migrations import migrate_job_store
from .models import (
    ALLOWED_JOB_TRANSITIONS,
    JOB_KINDS,
    JOB_STATUSES,
    JobKind,
    JobRecord,
    JobStatus,
)


_JOB_ID_PATTERN = re.compile(r"job-[A-Za-z0-9][A-Za-z0-9_-]{7,63}")
_MAX_ERROR_MESSAGE = 1_000


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def canonical_hash(value: object) -> str:
    """Hash JSON-compatible request data deterministically."""

    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _safe_error_message(value: object) -> str | None:
    if value is None:
        return None
    message = safe_text(str(value).strip())
    return message[:_MAX_ERROR_MESSAGE] or None


def _safe_job_id(value: str | None) -> str:
    job_id = str(value or f"job-{uuid.uuid4().hex}").strip()
    if not _JOB_ID_PATTERN.fullmatch(job_id):
        raise JobStateError("job_id must match job- followed by 8-64 safe characters.")
    return job_id


def _safe_key(value: object, *, label: str, maximum: int = 256) -> str:
    normalized = str(value or "").strip()
    if not normalized or len(normalized) > maximum:
        raise JobStateError(f"{label} must be non-empty and at most {maximum} characters.")
    return normalized


class JobStore:
    """Persist Job control state in SQLite and append redacted event records."""

    def __init__(
        self,
        database_path: str | Path,
        *,
        job_root: str | Path | None = None,
        busy_timeout_seconds: float = 30.0,
    ) -> None:
        self.database_path = Path(database_path).expanduser().resolve()
        self.job_root = (
            Path(job_root).expanduser().resolve()
            if job_root is not None
            else self.database_path.parent / "jobs"
        )
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.job_root.mkdir(parents=True, exist_ok=True)
        self.busy_timeout_seconds = max(1.0, float(busy_timeout_seconds))
        self._schema_lock = RLock()
        self._initialize_schema()

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(
            self.database_path,
            timeout=self.busy_timeout_seconds,
            isolation_level=None,
            check_same_thread=False,
        )
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute(f"PRAGMA busy_timeout = {int(self.busy_timeout_seconds * 1000)}")
            # WAL mode can block indefinitely on Windows-mounted WSL/UNC paths.
            # BEGIN IMMEDIATE below still serializes claims while the default
            # rollback journal remains portable across local filesystems.
            connection.execute("PRAGMA synchronous = NORMAL")
            yield connection
        finally:
            connection.close()

    def _initialize_schema(self) -> None:
        with self._schema_lock, self._connection() as connection:
            connection.executescript(
                """
                BEGIN IMMEDIATE;
                CREATE TABLE IF NOT EXISTS job_store_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS jobs (
                    job_id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    scope_key TEXT NOT NULL,
                    owner_id TEXT,
                    project_id TEXT,
                    run_id TEXT,
                    status TEXT NOT NULL,
                    progress INTEGER,
                    current_step TEXT,
                    idempotency_key TEXT,
                    request_hash TEXT NOT NULL,
                    input_manifest_id TEXT NOT NULL,
                    input_manifest_sha256 TEXT NOT NULL,
                    output_artifact_ids TEXT NOT NULL,
                    prompt_id TEXT,
                    prompt_version TEXT,
                    prompt_hash TEXT,
                    model_name TEXT,
                    provider_name TEXT,
                    attempt INTEGER NOT NULL DEFAULT 0,
                    max_attempts INTEGER NOT NULL DEFAULT 2,
                    lease_owner TEXT,
                    lease_until TEXT,
                    heartbeat_at TEXT,
                    error_code TEXT,
                    error_message TEXT,
                    retryable INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    started_at TEXT,
                    finished_at TEXT,
                    CHECK (kind IN ('science', 'figure', 'polish', 'translation')),
                    CHECK (status IN (
                        'QUEUED', 'RUNNING', 'WAITING_FOR_REVIEW', 'SUCCEEDED',
                        'FAILED', 'CANCEL_REQUESTED', 'CANCELLED', 'EXPIRED'
                    )),
                    CHECK (progress IS NULL OR (progress >= 0 AND progress <= 100)),
                    CHECK (attempt >= 0),
                    CHECK (max_attempts >= 1)
                );
                """
            )
            self._migrate_columns(connection)
            migrate_job_store(connection, self.job_root)
            connection.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS jobs_scope_idempotency
                    ON jobs(scope_key, idempotency_key)
                """
            )
            connection.execute("CREATE INDEX IF NOT EXISTS jobs_status_updated ON jobs(status, updated_at)")
            connection.execute("CREATE INDEX IF NOT EXISTS jobs_scope_created ON jobs(scope_key, created_at)")
            connection.execute("CREATE INDEX IF NOT EXISTS jobs_run_status ON jobs(run_id, status)")
            connection.execute("COMMIT")

    @staticmethod
    def _migrate_columns(connection: sqlite3.Connection) -> None:
        existing = {str(row[1]) for row in connection.execute("PRAGMA table_info(jobs)").fetchall()}
        additions = {
            "scope_key": "TEXT NOT NULL DEFAULT 'workspace'",
            "owner_id": "TEXT",
            "project_id": "TEXT",
            "run_id": "TEXT",
            "progress": "INTEGER",
            "current_step": "TEXT",
            "idempotency_key": "TEXT",
            "request_hash": "TEXT NOT NULL DEFAULT ''",
            "input_manifest_id": "TEXT NOT NULL DEFAULT ''",
            "input_manifest_sha256": "TEXT NOT NULL DEFAULT ''",
            "output_artifact_ids": "TEXT NOT NULL DEFAULT '[]'",
            "prompt_id": "TEXT",
            "prompt_version": "TEXT",
            "prompt_hash": "TEXT",
            "model_name": "TEXT",
            "provider_name": "TEXT",
            "attempt": "INTEGER NOT NULL DEFAULT 0",
            "max_attempts": "INTEGER NOT NULL DEFAULT 2",
            "lease_owner": "TEXT",
            "lease_until": "TEXT",
            "heartbeat_at": "TEXT",
            "error_code": "TEXT",
            "error_message": "TEXT",
            "retryable": "INTEGER NOT NULL DEFAULT 0",
            "created_at": "TEXT NOT NULL DEFAULT ''",
            "updated_at": "TEXT NOT NULL DEFAULT ''",
            "started_at": "TEXT",
            "finished_at": "TEXT",
        }
        for column, definition in additions.items():
            if column not in existing:
                connection.execute(f"ALTER TABLE jobs ADD COLUMN {column} {definition}")

    @property
    def schema_version(self) -> str:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT value FROM job_store_meta WHERE key = 'schema_version'"
            ).fetchone()
        return str(row[0]) if row else "job_store_v1"

    def job_directory(self, job_id: str) -> Path:
        normalized = _safe_job_id(job_id)
        path = (self.job_root / normalized).resolve()
        try:
            path.relative_to(self.job_root)
        except ValueError as exc:
            raise JobNotFoundError("Unknown Job.") from exc
        return path

    def create(
        self,
        *,
        kind: JobKind,
        input_manifest_id: str,
        input_manifest_sha256: str,
        request_hash: str,
        scope_key: str = "workspace",
        owner_id: str | None = None,
        project_id: str | None = None,
        run_id: str | None = None,
        idempotency_key: str | None = None,
        prompt_id: str | None = None,
        prompt_version: str | None = None,
        prompt_hash: str | None = None,
        model_name: str | None = None,
        provider_name: str | None = None,
        max_attempts: int = 2,
        job_id: str | None = None,
        input_file_ids: Sequence[str] = (),
    ) -> JobRecord:
        if kind not in JOB_KINDS:
            raise JobStateError(f"Unsupported Job kind: {kind}")
        scope_key = _safe_key(scope_key, label="scope_key")
        input_manifest_id = _safe_key(input_manifest_id, label="input_manifest_id")
        input_manifest_sha256 = _safe_key(input_manifest_sha256, label="input_manifest_sha256", maximum=128)
        request_hash = _safe_key(request_hash, label="request_hash", maximum=128)
        max_attempts = int(max_attempts)
        if max_attempts < 1 or max_attempts > 10:
            raise JobStateError("max_attempts must be between 1 and 10.")
        normalized_idempotency = str(idempotency_key or "").strip() or None
        if normalized_idempotency is not None and len(normalized_idempotency) > 256:
            raise JobStateError("idempotency_key is too long.")

        normalized_job_id = _safe_job_id(job_id)
        timestamp = utc_now()
        values = (
            normalized_job_id,
            kind,
            scope_key,
            owner_id,
            project_id,
            run_id,
            "QUEUED",
            None,
            None,
            normalized_idempotency,
            request_hash,
            input_manifest_id,
            input_manifest_sha256,
            "[]",
            prompt_id,
            prompt_version,
            prompt_hash,
            model_name,
            provider_name,
            0,
            max_attempts,
            None,
            None,
            None,
            None,
            None,
            0,
            timestamp,
            timestamp,
            None,
            None,
        )
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                if normalized_idempotency is not None:
                    existing = connection.execute(
                        """
                        SELECT * FROM jobs
                        WHERE scope_key = ? AND idempotency_key = ?
                        """,
                        (scope_key, normalized_idempotency),
                    ).fetchone()
                    if existing is not None:
                        existing_record = self._row_to_record(existing)
                        if existing_record.request_hash != request_hash:
                            raise JobConflictError(
                                "The idempotency key is already bound to a different request."
                            )
                        connection.execute("COMMIT")
                        return existing_record
                if kind == "science" and run_id and connection.execute(
                    "SELECT 1 FROM jobs WHERE kind = 'science' AND run_id = ? AND status IN ('QUEUED', 'RUNNING', 'CANCEL_REQUESTED')",
                    (run_id,),
                ).fetchone() is not None:
                    raise JobConflictError("A durable science task is already active for this run.")
                connection.execute(
                    """
                    INSERT INTO jobs(
                        job_id, kind, scope_key, owner_id, project_id, run_id,
                        status, progress, current_step, idempotency_key, request_hash,
                        input_manifest_id, input_manifest_sha256, output_artifact_ids,
                        prompt_id, prompt_version, prompt_hash, model_name, provider_name,
                        attempt, max_attempts, lease_owner, lease_until, heartbeat_at,
                        error_code, error_message, retryable, created_at, updated_at,
                        started_at, finished_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                              ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    values,
                )
                for file_id in input_file_ids:
                    connection.execute("INSERT OR IGNORE INTO job_file_references VALUES (?, ?)", (file_id, normalized_job_id))
                self._insert_event(connection, normalized_job_id, "JOB_CREATED", {"kind": kind})
                self._insert_event(connection, normalized_job_id, "JOB_QUEUED", {"revision": 1})
                connection.execute("COMMIT")
            except Exception:
                connection.execute("ROLLBACK")
                raise

        record = self.get(normalized_job_id)
        self._write_snapshot(record)
        self._mirror_events(record.job_id)
        return record

    def get(self, job_id: str) -> JobRecord:
        try:
            normalized = _safe_job_id(job_id)
        except JobStateError as exc:
            raise JobNotFoundError("Unknown Job.") from exc
        with self._connection() as connection:
            row = connection.execute("SELECT * FROM jobs WHERE job_id = ?", (normalized,)).fetchone()
        if row is None:
            raise JobNotFoundError("Unknown Job.")
        return self._row_to_record(row)

    def find_by_idempotency_key(self, scope_key: str, idempotency_key: str) -> JobRecord | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM jobs WHERE scope_key = ? AND idempotency_key = ?",
                (_safe_key(scope_key, label="scope_key"), _safe_key(idempotency_key, label="idempotency_key")),
            ).fetchone()
        return self._row_to_record(row) if row is not None else None

    def file_is_referenced(self, file_id: str) -> bool:
        with self._connection() as connection:
            return connection.execute("SELECT 1 FROM job_file_references WHERE file_id = ? LIMIT 1", (file_id,)).fetchone() is not None

    def file_references(self) -> list[tuple[str, str]]:
        with self._connection() as connection:
            return [(str(row[0]), str(row[1])) for row in connection.execute("SELECT file_id, job_id FROM job_file_references")]

    @contextmanager
    def lease_guard(self, job_id: str, *, lease_owner: str, attempt: int | None = None) -> Iterator[JobRecord]:
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                row = connection.execute("SELECT * FROM jobs WHERE job_id = ?", (_safe_job_id(job_id),)).fetchone()
                if row is None:
                    raise JobNotFoundError("Unknown Job.")
                record = self._row_to_record(row)
                self._require_lease(record, lease_owner=lease_owner, attempt=attempt)
                yield record
                connection.execute("COMMIT")
            except BaseException:
                connection.execute("ROLLBACK")
                raise

    @staticmethod
    def _require_lease(record: JobRecord, *, lease_owner: str, attempt: int | None = None) -> None:
        if (
            record.status not in {"RUNNING", "CANCEL_REQUESTED"}
            or record.lease_owner != lease_owner
            or not record.lease_until
            or record.lease_until <= utc_now()
            or (attempt is not None and record.attempt != attempt)
        ):
            raise JobLeaseLost("The Job execution lease is no longer owned by this worker.")

    def list(
        self,
        *,
        scope_key: str | None = None,
        kind: JobKind | None = None,
        run_id: str | None = None,
        project_id: str | None = None,
        statuses: Sequence[JobStatus] | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[JobRecord]:
        limit = max(1, min(int(limit), 1_000))
        clauses: list[str] = []
        parameters: list[object] = []
        if run_id is not None:
            clauses.append("run_id = ?")
            parameters.append(run_id)
        if project_id is not None:
            clauses.append("project_id = ?")
            parameters.append(project_id)
        if scope_key is not None:
            clauses.append("scope_key = ?")
            parameters.append(_safe_key(scope_key, label="scope_key"))
        if kind is not None:
            if kind not in JOB_KINDS:
                raise JobStateError(f"Unsupported Job kind: {kind}")
            clauses.append("kind = ?")
            parameters.append(kind)
        if statuses:
            invalid = [status for status in statuses if status not in JOB_STATUSES]
            if invalid:
                raise JobStateError(f"Unsupported Job statuses: {', '.join(invalid)}")
            placeholders = ",".join("?" for _ in statuses)
            clauses.append(f"status IN ({placeholders})")
            parameters.extend(statuses)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._connection() as connection:
            rows = connection.execute(
                f"SELECT * FROM jobs {where} ORDER BY created_at DESC, job_id DESC LIMIT ? OFFSET ?",
                (*parameters, limit, max(0, int(offset))),
            ).fetchall()
        return [self._row_to_record(row) for row in rows]

    def claim(self, job_id: str, *, lease_owner: str, lease_seconds: float = 120.0) -> JobRecord | None:
        normalized = _safe_job_id(job_id)
        lease_owner = _safe_key(lease_owner, label="lease_owner", maximum=256)
        now = utc_now()
        lease_until = (
            datetime.now(timezone.utc) + timedelta(seconds=max(1.0, float(lease_seconds)))
        ).isoformat().replace("+00:00", "Z")
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT * FROM jobs WHERE job_id = ?", (normalized,)).fetchone()
            if row is None:
                connection.execute("ROLLBACK")
                raise JobNotFoundError("Unknown Job.")
            record = self._row_to_record(row)
            if record.status != "QUEUED" or record.attempt >= record.max_attempts:
                connection.execute("ROLLBACK")
                return None
            connection.execute(
                """
                UPDATE jobs
                SET status = 'RUNNING', attempt = attempt + 1,
                    lease_owner = ?, lease_until = ?, heartbeat_at = ?,
                    started_at = COALESCE(started_at, ?), updated_at = ?,
                    error_code = NULL, error_message = NULL, retryable = 0,
                    finished_at = NULL
                WHERE job_id = ? AND status = 'QUEUED' AND attempt < max_attempts
                """,
                (lease_owner, lease_until, now, now, now, normalized),
            )
            updated = connection.execute("SELECT * FROM jobs WHERE job_id = ?", (normalized,)).fetchone()
            self._insert_event(connection, normalized, "JOB_STARTED", {
                "attempt": int(updated["attempt"]), "revision": int(updated["revision"]), "lease_until": lease_until,
            })
            connection.execute("COMMIT")
        claimed = self._row_to_record(updated)
        self._write_snapshot(claimed)
        self._mirror_events(claimed.job_id)
        return claimed

    def heartbeat(
        self,
        job_id: str,
        *,
        lease_owner: str,
        lease_seconds: float = 120.0,
        progress: int | None = None,
        current_step: str | None = None,
    ) -> JobRecord:
        normalized = _safe_job_id(job_id)
        lease_owner = _safe_key(lease_owner, label="lease_owner", maximum=256)
        now = utc_now()
        lease_until = (
            datetime.now(timezone.utc) + timedelta(seconds=max(1.0, float(lease_seconds)))
        ).isoformat().replace("+00:00", "Z")
        if progress is not None and not 0 <= int(progress) <= 100:
            raise JobStateError("progress must be between 0 and 100.")
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT * FROM jobs WHERE job_id = ?", (normalized,)).fetchone()
            if row is None:
                connection.execute("ROLLBACK")
                raise JobNotFoundError("Unknown Job.")
            record = self._row_to_record(row)
            try:
                self._require_lease(record, lease_owner=lease_owner)
            except JobLeaseLost:
                connection.execute("ROLLBACK")
                raise
            connection.execute(
                """
                UPDATE jobs
                SET lease_until = ?, heartbeat_at = ?, updated_at = ?,
                    progress = COALESCE(?, progress),
                    current_step = COALESCE(?, current_step)
                WHERE job_id = ? AND lease_owner = ?
                """,
                (lease_until, now, now, progress, current_step, normalized, lease_owner),
            )
            updated = connection.execute("SELECT * FROM jobs WHERE job_id = ?", (normalized,)).fetchone()
            if progress is not None or current_step is not None:
                self._insert_event(connection, normalized, "JOB_PROGRESS", {
                    "progress": updated["progress"], "current_step": updated["current_step"],
                })
            connection.execute("COMMIT")
        refreshed = self._row_to_record(updated)
        self._write_snapshot(refreshed)
        if progress is not None or current_step is not None:
            self._mirror_events(refreshed.job_id)
        return refreshed

    def transition(
        self,
        job_id: str,
        status: JobStatus,
        *,
        lease_owner: str | None = None,
        progress: int | None = None,
        current_step: str | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
        retryable: bool = False,
        expected_status: JobStatus | None = None,
        output_artifact_ids: Sequence[str] | None = None,
    ) -> JobRecord:
        normalized = _safe_job_id(job_id)
        if status not in JOB_STATUSES:
            raise JobStateError(f"Unsupported Job status: {status}")
        if progress is not None and not 0 <= int(progress) <= 100:
            raise JobStateError("progress must be between 0 and 100.")
        now = utc_now()
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT * FROM jobs WHERE job_id = ?", (normalized,)).fetchone()
            if row is None:
                connection.execute("ROLLBACK")
                raise JobNotFoundError("Unknown Job.")
            record = self._row_to_record(row)
            if expected_status is not None and record.status != expected_status:
                connection.execute("ROLLBACK")
                raise JobConflictError("The Job status changed while this action was being applied.")
            if status != record.status and status not in ALLOWED_JOB_TRANSITIONS[record.status]:
                connection.execute("ROLLBACK")
                raise JobStateError(f"Cannot transition Job from {record.status} to {status}.")
            if lease_owner is not None:
                try:
                    self._require_lease(record, lease_owner=lease_owner)
                except JobLeaseLost:
                    connection.execute("ROLLBACK")
                    raise
            clear_lease = status in {"QUEUED", "WAITING_FOR_REVIEW", "SUCCEEDED", "FAILED", "CANCELLED", "EXPIRED"}
            finished_at = now if status in {"SUCCEEDED", "FAILED", "CANCELLED", "EXPIRED"} else None
            artifact_ids = list(record.output_artifact_ids)
            for artifact_id in output_artifact_ids or ():
                artifact_id = _safe_key(artifact_id, label="artifact_id")
                if artifact_id not in artifact_ids:
                    artifact_ids.append(artifact_id)
            connection.execute(
                """
                UPDATE jobs
                SET status = ?, progress = COALESCE(?, progress),
                    current_step = COALESCE(?, current_step),
                    lease_owner = CASE WHEN ? THEN NULL ELSE lease_owner END,
                    lease_until = CASE WHEN ? THEN NULL ELSE lease_until END,
                    heartbeat_at = CASE WHEN ? THEN NULL ELSE heartbeat_at END,
                    error_code = ?, error_message = ?, retryable = ?,
                    finished_at = ?, updated_at = ?, output_artifact_ids = ?, revision = ?
                WHERE job_id = ?
                """,
                (
                    status,
                    progress,
                    current_step,
                    int(clear_lease),
                    int(clear_lease),
                    int(clear_lease),
                    error_code,
                    _safe_error_message(error_message),
                    int(bool(retryable)),
                    finished_at,
                    now,
                    json.dumps(artifact_ids, separators=(",", ":")),
                    record.revision + int(record.status == "WAITING_FOR_REVIEW" and status == "QUEUED"),
                    normalized,
                ),
            )
            updated = connection.execute("SELECT * FROM jobs WHERE job_id = ?", (normalized,)).fetchone()
            for artifact_id in artifact_ids:
                if artifact_id not in record.output_artifact_ids:
                    self._insert_event(connection, normalized, "JOB_ARTIFACT_PUBLISHED", {"artifact_id": artifact_id})
            if record.status == "FAILED" and status == "QUEUED":
                self._insert_event(connection, normalized, "JOB_RETRY_REQUESTED", {"revision": record.revision})
            self._insert_event(connection, normalized, f"JOB_{status}", {
                "progress": updated["progress"], "current_step": updated["current_step"],
                "error_code": error_code, "retryable": bool(retryable), "revision": int(updated["revision"]),
            })
            connection.execute("COMMIT")
        refreshed = self._row_to_record(updated)
        self._write_snapshot(refreshed)
        self._mirror_events(refreshed.job_id)
        return refreshed

    def request_cancel(self, job_id: str) -> JobRecord:
        for _attempt in range(3):
            record = self.get(job_id)
            target = {"QUEUED": "CANCELLED", "RUNNING": "CANCEL_REQUESTED", "WAITING_FOR_REVIEW": "CANCELLED"}.get(record.status)
            if target is None:
                return record
            try:
                return self.transition(job_id, target, expected_status=record.status, current_step="cancellation_requested")
            except JobConflictError:
                continue
        raise JobConflictError("The Job is changing state; retry cancellation shortly.")

    def acknowledge_cancel(self, job_id: str, *, lease_owner: str) -> JobRecord:
        return self.transition(job_id, "CANCELLED", lease_owner=lease_owner, expected_status="CANCEL_REQUESTED")

    def retry(self, job_id: str) -> JobRecord:
        record = self.get(job_id)
        if record.status != "FAILED":
            raise JobStateError("Only failed Jobs can be retried.")
        if not record.retryable:
            raise JobStateError("This Job failure is not retryable.")
        if record.attempt >= record.max_attempts:
            raise JobStateError("This Job has reached its retry limit.")
        return self.transition(job_id, "QUEUED", progress=0, current_step="retry_queued", expected_status="FAILED")

    def attach_artifact(
        self, job_id: str, artifact_id: str, *, expected_status: str | None = None,
        expected_attempt: int | None = None,
    ) -> JobRecord:
        artifact_id = _safe_key(artifact_id, label="artifact_id", maximum=256)
        now = utc_now()
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT * FROM jobs WHERE job_id = ?", (_safe_job_id(job_id),)).fetchone()
            if row is None:
                connection.execute("ROLLBACK")
                raise JobNotFoundError("Unknown Job.")
            record = self._row_to_record(row)
            if (expected_status is not None and record.status != expected_status) or (
                expected_attempt is not None and record.attempt != expected_attempt
            ):
                connection.execute("ROLLBACK")
                raise JobConflictError("The Job changed before the Artifact could be attached.")
            artifact_ids = list(record.output_artifact_ids)
            if artifact_id in artifact_ids:
                connection.execute("COMMIT")
                return record
            artifact_ids.append(artifact_id)
            connection.execute(
                "UPDATE jobs SET output_artifact_ids = ?, updated_at = ? WHERE job_id = ?",
                (json.dumps(artifact_ids, ensure_ascii=False, separators=(",", ":")), now, record.job_id),
            )
            self._insert_event(connection, record.job_id, "JOB_ARTIFACT_PUBLISHED", {"artifact_id": artifact_id})
            connection.execute("COMMIT")
        refreshed = self.get(record.job_id)
        self._write_snapshot(refreshed)
        self._mirror_events(refreshed.job_id)
        return refreshed

    def reclaim_stale_jobs(self, *, stale_after_seconds: float = 120.0) -> list[JobRecord]:
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(seconds=max(1.0, float(stale_after_seconds)))
        now_text = now.isoformat().replace("+00:00", "Z")
        cutoff_text = cutoff.isoformat().replace("+00:00", "Z")
        reclaimed_ids: list[str] = []
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                """
                SELECT * FROM jobs
                WHERE status IN ('RUNNING', 'CANCEL_REQUESTED')
                  AND (
                    lease_until IS NULL OR lease_until < ?
                    OR (heartbeat_at IS NOT NULL AND heartbeat_at < ?)
                  )
                """,
                (now_text, cutoff_text),
            ).fetchall()
            for row in rows:
                record = self._row_to_record(row)
                if record.status == "CANCEL_REQUESTED":
                    connection.execute(
                        """
                        UPDATE jobs SET status = 'CANCELLED', lease_owner = NULL, lease_until = NULL,
                            heartbeat_at = NULL, current_step = 'cancelled_after_worker_loss',
                            retryable = 0, finished_at = ?, updated_at = ? WHERE job_id = ?
                        """,
                        (now_text, now_text, record.job_id),
                    )
                elif record.attempt < record.max_attempts:
                    connection.execute(
                        """
                        UPDATE jobs
                        SET status = 'QUEUED', lease_owner = NULL, lease_until = NULL,
                            heartbeat_at = NULL, current_step = 'reclaimed_after_worker_loss',
                            error_code = 'WORKER_LOST',
                            error_message = 'The previous worker lease expired.',
                            retryable = 1, updated_at = ?
                        WHERE job_id = ?
                        """,
                        (utc_now(), record.job_id),
                    )
                else:
                    connection.execute(
                        """
                        UPDATE jobs
                        SET status = 'FAILED', lease_owner = NULL, lease_until = NULL,
                            heartbeat_at = NULL, current_step = 'worker_lost_after_retry_limit',
                            error_code = 'WORKER_LOST',
                            error_message = 'The worker lease expired after the retry limit.',
                            retryable = 0, finished_at = ?, updated_at = ?
                        WHERE job_id = ?
                        """,
                        (utc_now(), utc_now(), record.job_id),
                    )
                reclaimed_ids.append(record.job_id)
                updated_status = connection.execute("SELECT status FROM jobs WHERE job_id = ?", (record.job_id,)).fetchone()[0]
                self._insert_event(connection, record.job_id, "JOB_RECLAIMED", {
                    "status": updated_status, "revision": record.revision,
                })
            connection.execute("COMMIT")
        refreshed: list[JobRecord] = []
        for job_id in reclaimed_ids:
            record = self.get(job_id)
            refreshed.append(record)
            self._write_snapshot(record)
            self._mirror_events(record.job_id)
        return refreshed

    def events_path(self, job_id: str) -> Path:
        return self.job_directory(job_id) / "events.jsonl"

    def read_events(self, job_id: str, *, after: int = 0) -> list[dict[str, object]]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT * FROM job_events WHERE job_id = ? AND sequence > ? ORDER BY sequence",
                (_safe_job_id(job_id), max(0, int(after))),
            ).fetchall()
        return [
            {"event_id": str(row["sequence"]), "event_type": row["event_type"],
             "timestamp": row["timestamp"], "payload": json.loads(row["payload"])}
            for row in rows
        ]

    def _row_to_record(self, row: Mapping[str, Any]) -> JobRecord:
        return JobRecord.from_row(dict(row))

    def _write_snapshot(self, record: JobRecord) -> None:
        try:
            directory = self.job_directory(record.job_id)
            directory.mkdir(parents=True, exist_ok=True)
            with FileLock(str(directory / ".job.guard"), timeout=5):
                _atomic_write_json(directory / "job.json", self.get(record.job_id).as_dict())
        except (OSError, Timeout):
            return

    def _append_event(self, job_id: str, event_type: str, payload: Mapping[str, object]) -> None:
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._insert_event(connection, job_id, event_type, payload)
            connection.execute("COMMIT")
        self._mirror_events(job_id)

    @staticmethod
    def _insert_event(connection: sqlite3.Connection, job_id: str, event_type: str, payload: Mapping[str, object]) -> None:
        connection.execute(
            """
            INSERT INTO job_events(job_id, sequence, event_type, timestamp, payload)
            SELECT ?, COALESCE(MAX(sequence), 0) + 1, ?, ?, ? FROM job_events WHERE job_id = ?
            """,
            (job_id, event_type, utc_now(),
             json.dumps(safe_payload(dict(payload)), ensure_ascii=False, sort_keys=True, allow_nan=False), job_id),
        )

    def _mirror_events(self, job_id: str) -> None:
        try:
            path = self.events_path(job_id)
            path.parent.mkdir(parents=True, exist_ok=True)
            with FileLock(str(path.with_name(".events.guard")), timeout=5):
                temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
                try:
                    temporary.write_text(
                        "".join(json.dumps(event, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n"
                                for event in self.read_events(job_id)), encoding="utf-8",
                    )
                    temporary.replace(path)
                finally:
                    temporary.unlink(missing_ok=True)
        except (OSError, Timeout):
            return


def _atomic_write_json(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
