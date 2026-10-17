"""Typed records and state transitions for durable web Jobs."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Literal, Mapping, cast


JobKind = Literal["science", "figure", "polish", "translation"]
JobStatus = Literal[
    "QUEUED",
    "RUNNING",
    "WAITING_FOR_REVIEW",
    "SUCCEEDED",
    "FAILED",
    "CANCEL_REQUESTED",
    "CANCELLED",
    "EXPIRED",
]

JOB_KINDS = frozenset({"science", "figure", "polish", "translation"})
JOB_STATUSES = frozenset(
    {
        "QUEUED",
        "RUNNING",
        "WAITING_FOR_REVIEW",
        "SUCCEEDED",
        "FAILED",
        "CANCEL_REQUESTED",
        "CANCELLED",
        "EXPIRED",
    }
)
TERMINAL_JOB_STATUSES = frozenset({"SUCCEEDED", "CANCELLED", "EXPIRED"})

ALLOWED_JOB_TRANSITIONS: dict[str, frozenset[str]] = {
    "QUEUED": frozenset({"RUNNING", "CANCELLED", "EXPIRED"}),
    "RUNNING": frozenset(
        {"WAITING_FOR_REVIEW", "SUCCEEDED", "FAILED", "CANCEL_REQUESTED", "CANCELLED"}
    ),
    "WAITING_FOR_REVIEW": frozenset({"QUEUED", "SUCCEEDED", "CANCELLED", "EXPIRED"}),
    "FAILED": frozenset({"QUEUED", "EXPIRED"}),
    "CANCEL_REQUESTED": frozenset({"CANCELLED", "FAILED"}),
    "SUCCEEDED": frozenset(),
    "CANCELLED": frozenset(),
    "EXPIRED": frozenset(),
}


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    return int(value)


def _decode_artifact_ids(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    if value is None:
        return []
    try:
        decoded = json.loads(str(value))
    except (TypeError, json.JSONDecodeError):
        return []
    return [str(item) for item in decoded] if isinstance(decoded, list) else []


@dataclass(frozen=True, slots=True)
class JobRecord:
    """Durable Job metadata kept small enough for SQLite."""

    job_id: str
    kind: JobKind
    scope_key: str
    owner_id: str | None
    project_id: str | None
    run_id: str | None
    status: JobStatus
    progress: int | None
    current_step: str | None
    idempotency_key: str | None
    request_hash: str
    input_manifest_id: str
    input_manifest_sha256: str
    output_artifact_ids: tuple[str, ...] = field(default_factory=tuple)
    prompt_id: str | None = None
    prompt_version: str | None = None
    prompt_hash: str | None = None
    model_name: str | None = None
    provider_name: str | None = None
    attempt: int = 0
    revision: int = 1
    max_attempts: int = 2
    lease_owner: str | None = None
    lease_until: str | None = None
    heartbeat_at: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    retryable: bool = False
    created_at: str = ""
    updated_at: str = ""
    started_at: str | None = None
    finished_at: str | None = None

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "JobRecord":
        kind = str(row["kind"])
        status = str(row["status"])
        if kind not in JOB_KINDS:
            raise ValueError(f"Unsupported Job kind: {kind}")
        if status not in JOB_STATUSES:
            raise ValueError(f"Unsupported Job status: {status}")
        return cls(
            job_id=str(row["job_id"]),
            kind=cast(JobKind, kind),
            scope_key=str(row["scope_key"]),
            owner_id=_optional_text(row.get("owner_id")),
            project_id=_optional_text(row.get("project_id")),
            run_id=_optional_text(row.get("run_id")),
            status=cast(JobStatus, status),
            progress=_optional_int(row.get("progress")),
            current_step=_optional_text(row.get("current_step")),
            idempotency_key=_optional_text(row.get("idempotency_key")),
            request_hash=str(row.get("request_hash") or ""),
            input_manifest_id=str(row.get("input_manifest_id") or ""),
            input_manifest_sha256=str(row.get("input_manifest_sha256") or ""),
            output_artifact_ids=tuple(_decode_artifact_ids(row.get("output_artifact_ids"))),
            prompt_id=_optional_text(row.get("prompt_id")),
            prompt_version=_optional_text(row.get("prompt_version")),
            prompt_hash=_optional_text(row.get("prompt_hash")),
            model_name=_optional_text(row.get("model_name")),
            provider_name=_optional_text(row.get("provider_name")),
            attempt=int(row.get("attempt") or 0),
            revision=int(row.get("revision") or 1),
            max_attempts=int(row.get("max_attempts") or 1),
            lease_owner=_optional_text(row.get("lease_owner")),
            lease_until=_optional_text(row.get("lease_until")),
            heartbeat_at=_optional_text(row.get("heartbeat_at")),
            error_code=_optional_text(row.get("error_code")),
            error_message=_optional_text(row.get("error_message")),
            retryable=bool(row.get("retryable")),
            created_at=str(row.get("created_at") or ""),
            updated_at=str(row.get("updated_at") or ""),
            started_at=_optional_text(row.get("started_at")),
            finished_at=_optional_text(row.get("finished_at")),
        )

    def as_dict(self) -> dict[str, object]:
        """Return a JSON-safe public snapshot without local paths."""

        return {
            "job_id": self.job_id,
            "kind": self.kind,
            "scope_key": self.scope_key,
            "owner_id": self.owner_id,
            "project_id": self.project_id,
            "run_id": self.run_id,
            "status": self.status,
            "progress": self.progress,
            "current_step": self.current_step,
            "idempotency_key": self.idempotency_key,
            "request_hash": self.request_hash,
            "input_manifest_id": self.input_manifest_id,
            "input_manifest_sha256": self.input_manifest_sha256,
            "output_artifact_ids": list(self.output_artifact_ids),
            "prompt_id": self.prompt_id,
            "prompt_version": self.prompt_version,
            "prompt_hash": self.prompt_hash,
            "model_name": self.model_name,
            "provider_name": self.provider_name,
            "attempt": self.attempt,
            "revision": self.revision,
            "max_attempts": self.max_attempts,
            "lease_until": self.lease_until,
            "heartbeat_at": self.heartbeat_at,
            "error_code": self.error_code,
            "error_message": self.error_message,
            "retryable": self.retryable,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }


@dataclass(frozen=True, slots=True)
class JobExecutionResult:
    """Worker result used to choose the terminal or review state."""

    status: Literal["SUCCEEDED", "WAITING_FOR_REVIEW"] = "SUCCEEDED"
    output_artifact_ids: tuple[str, ...] = ()
    progress: int | None = 100
    current_step: str | None = None
