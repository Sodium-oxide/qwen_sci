"""Validated paths and limits shared by web services and workers."""

from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class WebRuntimeSettings(BaseModel):
    run_root: Path
    database_path: Path
    job_root: Path
    file_root: Path
    max_workers: int = Field(default=4, ge=1, le=64)
    max_attempts: int = Field(default=3, ge=1, le=10)
    heartbeat_seconds: float = Field(default=15, ge=0.1, le=300)
    stale_after_seconds: float = Field(default=120, ge=1)
    default_timeout_seconds: float = Field(default=1800, gt=0)
    max_upload_bytes: int = Field(default=52_428_800, ge=1)
    max_project_bytes: int = Field(default=1_073_741_824, ge=1)
    max_uncompressed_bytes: int = Field(default=268_435_456, ge=1)

    @classmethod
    def from_config(
        cls,
        config: Any,
        *,
        repo_root: Path,
        run_root: str | Path | None = None,
        database_path: str | Path | None = None,
    ) -> "WebRuntimeSettings":
        web = config.get("web", {})
        jobs = web.get("jobs", {})
        files = web.get("files", {})
        if jobs.get("backend", "sqlite") != "sqlite":
            raise ValueError("The web Job backend must be sqlite.")

        def resolve_path(value: str | Path) -> Path:
            path = Path(str(value)).expanduser()
            return (path if path.is_absolute() else repo_root / path).resolve()

        workspace = resolve_path(config.get("workspace", {}).get("root", "workspace"))
        resolved_run_root = resolve_path(run_root) if run_root is not None else workspace / "science-runs"
        control_root = resolved_run_root.parent if run_root is not None else workspace
        selected_database = database_path or os.environ.get("QWENSCI_WEB_DATABASE")
        database = resolve_path(selected_database or (
            control_root / "qwensci.db" if run_root is not None else jobs.get("database", control_root / "qwensci.db")
        ))
        if os.name == "nt" and str(database).startswith("\\\\"):
            if selected_database:
                raise ValueError("QWENSCI_WEB_DATABASE must point to a local filesystem, not a UNC share.")
            cache_root = Path(os.environ.get("LOCALAPPDATA") or tempfile.gettempdir())
            workspace_key = hashlib.sha256(str(control_root).encode("utf-8")).hexdigest()[:16]
            database = cache_root / "QwenSci" / "control" / workspace_key / "qwensci.db"
        return cls(
            run_root=resolved_run_root,
            database_path=database,
            job_root=resolve_path(control_root / "jobs" if run_root is not None else jobs.get("root", control_root / "jobs")),
            file_root=control_root / "files",
            max_workers=jobs.get("max_workers", 4),
            max_attempts=int(jobs.get("max_retries", 2)) + 1,
            heartbeat_seconds=jobs.get("heartbeat_seconds", 15),
            stale_after_seconds=jobs.get("stale_after_seconds", 120),
            default_timeout_seconds=jobs.get("default_timeout_seconds", 1800),
            max_upload_bytes=files.get("max_upload_bytes", 52_428_800),
            max_project_bytes=files.get("max_project_bytes", 1_073_741_824),
            max_uncompressed_bytes=files.get("max_uncompressed_bytes", 268_435_456),
        )
