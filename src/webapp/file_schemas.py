"""Public schemas for project-scoped files shared by web Jobs."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict


class FileView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    file_id: str
    original_name: str
    mime_type: str
    detected_type: str
    size_bytes: int
    sha256: str
    source: Literal["upload", "run_material", "generated"]
    owner_id: str | None = None
    project_id: str | None = None
    run_id: str | None = None
    job_id: str | None = None
    sensitivity: Literal["public", "controlled", "sensitive"]
    parser_backend: str | None = None
    parser_version: str | None = None
    created_at: str
    retention_until: str | None = None
    content_url: str
    material_scope: str | None = None
    source_artifact_id: str | None = None
