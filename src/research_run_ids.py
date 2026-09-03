"""Filesystem-safe identifiers for automatically created research runs."""

from __future__ import annotations

from datetime import datetime


def create_research_run_id(started_at: datetime | None = None) -> str:
    """Return a compact ID based on the research run's start time."""

    return (started_at or datetime.now()).strftime("%Y%m%d-%H%M%S-%f")
