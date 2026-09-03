"""Structured lifecycle-event formatting for scientific Survey projects."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any


def _event_value(value: Any) -> str:
    if isinstance(value, Mapping):
        value = "|".join(f"{key}:{item}" for key, item in value.items())
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        value = "|".join(str(item) for item in value)
    return re.sub(r"\s+", " ", str(value if value is not None else "")).strip()


def format_science_event(event: str, **fields: Any) -> str:
    """Return one event line for the Survey Rich logger."""

    serialized = ", ".join(
        f"{key}={_event_value(value)}" for key, value in fields.items()
    )
    return f"[SCIENCE] {event}: {serialized}"


def emit_science_event(logger: Any, event: str, **fields: Any) -> None:
    """Emit through the caller's logger to preserve its existing format."""

    logger.info(format_science_event(event, **fields))
