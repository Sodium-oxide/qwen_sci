"""Persistent state for the independent Q1/Q2 quantitative branch.

The science state machine intentionally remains four stages.  This module
stores the resumable status of the quantitative sidecar beneath the same run
directory without making it a fifth science stage.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from src.pipeline.science_run import atomic_write_json, utc_now


QUANTITATIVE_STATE_SCHEMA_VERSION = "quantitative_workflow_state_v1"
QUANTITATIVE_STATUSES = {
    "WAITING_FOR_EXPERIMENT_DESIGN",
    "WAITING_FOR_BLUEPRINT",
    "WAITING_FOR_PARAMETER_EVIDENCE",
    "WAITING_FOR_PARAMETER_REVIEW",
    "WAITING_FOR_PARAMETER_APPROVAL",
    "PARAMETERS_APPROVED",
    "MODEL_MATERIALIZED",
    "WAITING_FOR_EXECUTION_AUTHORIZATION",
    "EXECUTED",
    "WAITING_FOR_QUALIFICATION",
    "QUALIFIED_WAITING_FOR_REVISION_DECISION",
    "WAITING_FOR_REVISION_APPROVAL",
    "REVISION_ACCEPTED",
    "FINALIZED",
    "READY_TO_PUBLISH",
    "PUBLISHED",
    "HANDED_OFF",
    "NO_QUANTITATIVE_IDEAS",
}


class QuantitativeStateError(ValueError):
    """Raised when persisted quantitative state is malformed."""


def quantitative_state_path(run_dir: str | Path) -> Path:
    return Path(run_dir).expanduser().resolve() / "quantitative" / "workflow_state.json"


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _text(value: object) -> str:
    return str(value or "").strip()


def validate_quantitative_state(value: Mapping[str, object]) -> dict[str, Any]:
    payload = dict(value)
    if payload.get("schema_version") != QUANTITATIVE_STATE_SCHEMA_VERSION:
        raise QuantitativeStateError("unsupported quantitative workflow state schema")
    if not _text(payload.get("science_run_id")):
        raise QuantitativeStateError("quantitative workflow state has no science_run_id")
    status = _text(payload.get("status"))
    if status not in QUANTITATIVE_STATUSES:
        raise QuantitativeStateError(f"unsupported quantitative workflow status: {status}")
    if not isinstance(payload.get("ideas"), Mapping):
        raise QuantitativeStateError("quantitative workflow state has no ideas object")
    for idea_id, idea_state in payload["ideas"].items():
        if idea_id not in {"Q1", "Q2"} or not isinstance(idea_state, Mapping):
            raise QuantitativeStateError("quantitative workflow state has an invalid Q entry")
        idea_status = _text(idea_state.get("status"))
        if idea_status not in QUANTITATIVE_STATUSES:
            raise QuantitativeStateError(f"unsupported quantitative status for {idea_id}: {idea_status}")
        versions = idea_state.get("versions")
        if not isinstance(versions, Mapping):
            raise QuantitativeStateError(f"quantitative workflow state has no versions for {idea_id}")
        for version, version_state in versions.items():
            if version not in {"v0", "v1", "v2"} or not isinstance(version_state, Mapping):
                raise QuantitativeStateError(f"quantitative workflow state has an invalid version for {idea_id}")
            if _text(version_state.get("status")) not in QUANTITATIVE_STATUSES:
                raise QuantitativeStateError(f"unsupported quantitative version status for {idea_id}/{version}")
    return payload


def load_quantitative_state(run_dir: str | Path) -> dict[str, Any] | None:
    path = quantitative_state_path(run_dir)
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise QuantitativeStateError(f"cannot read quantitative workflow state: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise QuantitativeStateError("quantitative workflow state must be a JSON object")
    return validate_quantitative_state(payload)


def save_quantitative_state(run_dir: str | Path, state: Mapping[str, object]) -> Path:
    payload = validate_quantitative_state(state)
    payload["updated_at"] = utc_now()
    path = quantitative_state_path(run_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(path, payload)
    return path


def new_quantitative_state(*, science_run_id: str, status: str = "WAITING_FOR_EXPERIMENT_DESIGN") -> dict[str, Any]:
    if status not in QUANTITATIVE_STATUSES:
        raise QuantitativeStateError(f"unsupported quantitative workflow status: {status}")
    return {
        "schema_version": QUANTITATIVE_STATE_SCHEMA_VERSION,
        "science_run_id": science_run_id,
        "status": status,
        "created_at": utc_now(),
        "updated_at": utc_now(),
        "experiment_design": {},
        "quantitative_ideas_manifest": {},
        "ideas": {},
        "next_actions": [],
    }


__all__ = [
    "QUANTITATIVE_STATE_SCHEMA_VERSION",
    "QUANTITATIVE_STATUSES",
    "QuantitativeStateError",
    "load_quantitative_state",
    "new_quantitative_state",
    "quantitative_state_path",
    "save_quantitative_state",
    "validate_quantitative_state",
]
