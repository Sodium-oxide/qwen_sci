"""Pydantic responses and actions for the generic Job API."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .models import JobRecord


class JobView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: str
    kind: Literal["science", "figure", "polish", "translation"]
    scope_key: str
    owner_id: str | None = None
    project_id: str | None = None
    run_id: str | None = None
    status: str
    progress: int | None = None
    current_step: str | None = None
    idempotency_key: str | None = None
    request_hash: str
    input_manifest_id: str
    input_manifest_sha256: str
    output_artifact_ids: list[str] = Field(default_factory=list)
    prompt_id: str | None = None
    prompt_version: str | None = None
    prompt_hash: str | None = None
    model_name: str | None = None
    provider_name: str | None = None
    attempt: int
    revision: int = 1
    max_attempts: int
    lease_until: str | None = None
    heartbeat_at: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    retryable: bool
    created_at: str
    updated_at: str
    started_at: str | None = None
    finished_at: str | None = None
    available_actions: list[str] = Field(default_factory=list)

    @classmethod
    def from_record(cls, record: JobRecord) -> "JobView":
        actions = []
        if record.status in {"QUEUED", "RUNNING", "WAITING_FOR_REVIEW"}:
            actions.append("cancel")
        if record.status == "FAILED" and record.retryable and record.attempt < record.max_attempts:
            actions.append("retry")
        if record.status == "WAITING_FOR_REVIEW":
            actions.append("accept")
            if record.attempt < record.max_attempts:
                actions.append("reject")
            field = {"polish": "segments", "translation": "pages"}.get(record.kind)
            if field:
                actions.extend((f"accept_{field}", f"reject_{field}"))
                if record.attempt < record.max_attempts:
                    actions.append(f"regenerate_{field}")
        return cls.model_validate({**record.as_dict(), "available_actions": actions})


class JobActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["cancel", "retry"]


class JobReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    accepted: bool
    notes: str = Field(default="", max_length=2_000)
    expected_attempt: int | None = Field(default=None, ge=1)
    expected_review_version: int | None = Field(default=None, ge=0)


class JobReviewView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: str
    attempt: int
    revision: int
    review_version: int
    decision: Literal["accept", "reject"] | None = None
    segments: dict[str, Literal["accepted", "rejected"]] = Field(default_factory=dict)
    pages: dict[str, Literal["accepted", "rejected"]] = Field(default_factory=dict)
