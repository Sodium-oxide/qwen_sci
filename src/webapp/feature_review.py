"""Review ledgers bound to a Job attempt and validated output identifiers."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from filelock import FileLock

from .feature_schemas import FeatureActionRequest
from .figure_contracts import FigureStyle
from .job_artifacts import _atomic_write_json, list_job_artifacts, resolve_job_artifact
from .jobs import JobConflictError, JobNotFoundError, JobStateError, JobStore
from .jobs.models import JobRecord
from .jobs.store import canonical_hash, utc_now


def read_feature_result(store: JobStore, record: JobRecord, role: str) -> dict[str, Any]:
    if record.status not in {"WAITING_FOR_REVIEW", "SUCCEEDED"}:
        raise JobStateError("The feature result is not ready for review or export.")
    directory = store.job_directory(record.job_id)
    candidates = [
        item for item in list_job_artifacts(directory)
        if (
            item.get("artifact_id") in record.output_artifact_ids
            and item.get("role") == role
            and int(item.get("attempt", -1)) == record.attempt
        )
    ]
    for item in sorted(candidates, key=lambda item: int(item["attempt"]), reverse=True):
        resolved = resolve_job_artifact(directory, str(item["artifact_id"]))
        if resolved is None:
            continue
        try:
            payload = json.loads(resolved[0].read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise JobStateError("The reviewed feature result is invalid.") from exc
        if isinstance(payload, dict):
            return payload
    raise JobNotFoundError("The requested feature result is not ready.")


def read_review(store: JobStore, record: JobRecord) -> dict[str, Any]:
    path = store.job_directory(record.job_id) / "review.json"
    if not path.exists():
        return {"attempt": record.attempt, "version": 0, "segments": {}, "pages": {}}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise JobStateError("The review ledger is invalid.") from exc
    if not isinstance(payload, dict):
        raise JobStateError("The review ledger must be an object.")
    if payload.get("attempt") != record.attempt:
        feedback_path = store.job_directory(record.job_id) / "review_feedback.json"
        if feedback_path.exists():
            feedback = json.loads(feedback_path.read_text(encoding="utf-8"))
            if feedback.get("target_revision") == record.revision:
                return {
                    "attempt": record.attempt, "revision": record.revision,
                    "version": feedback.get("review_version", 0),
                    "segments": feedback.get("retained_review", {}).get("segments", {}),
                    "pages": feedback.get("retained_review", {}).get("pages", {}),
                }
        return {"attempt": record.attempt, "version": 0, "segments": {}, "pages": {}}
    if not isinstance(payload.get("version", 0), int) or any(
        not isinstance(payload.get(field, {}), dict) for field in ("segments", "pages")
    ):
        raise JobStateError("The review ledger has an invalid structure.")
    payload.setdefault("version", 0)
    return payload


def _review_ids(store: JobStore, record: JobRecord, field: str) -> set[str]:
    role = "polish_revision_set" if field == "segments" else "translation_pages"
    result = read_feature_result(store, record, role)
    key = "segment_id" if field == "segments" else "page_number"
    return {str(item[key]) for item in result.get(field, []) if isinstance(item, dict) and key in item}


def _figure_revision_style(store: JobStore, record: JobRecord, action: FeatureActionRequest) -> dict[str, object] | None:
    directory = store.job_directory(record.job_id)
    try:
        raw = (directory / "input.json").read_bytes()
        manifest = json.loads(raw)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise JobStateError("The figure input manifest is unavailable.") from exc
    if not isinstance(manifest, dict):
        raise JobStateError("The figure input manifest is invalid.")
    expected_hash = (
        canonical_hash(manifest.get("input")) if manifest.get("schema_version") == "web_job_input_v1"
        else hashlib.sha256(raw).hexdigest()
    )
    if expected_hash != record.input_manifest_sha256:
        raise JobStateError("The figure input manifest no longer matches its hash.")
    input_data = manifest.get("input", {})
    if not isinstance(input_data, dict):
        raise JobStateError("The figure input manifest is invalid.")
    if input_data.get("use_ai_schematic"):
        if action.figure_style is not None:
            raise JobStateError("figure_style only applies to data plots.")
        return None
    style = dict(input_data.get("figure_style") or {})
    feedback_path = directory / "review_feedback.json"
    if feedback_path.exists():
        try:
            feedback = json.loads(feedback_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise JobStateError("The figure revision feedback is invalid.") from exc
        if isinstance(feedback, dict) and feedback.get("target_revision") == record.revision:
            style.update(feedback.get("figure_style") or {})
    requested_style = action.figure_style.model_dump(exclude_unset=True) if action.figure_style else {}
    if input_data.get("planning_mode") != "model":
        if not requested_style:
            raise JobStateError("Explicit figure revisions require figure_style feedback.")
        current = read_feature_result(store, record, "figure_spec")
        if all(current.get(key) == value for key, value in requested_style.items()):
            raise JobStateError("Explicit figure revisions must change the current figure style.")
    style.update(requested_style)
    return FigureStyle.model_validate(style).model_dump(exclude_unset=True)


def apply_feature_review(store: JobStore, runner: Any, record: JobRecord, action: FeatureActionRequest) -> JobRecord:
    if action.figure_style is not None and action.type != "reject":
        raise JobStateError("figure_style is only supported on a full figure reject action.")
    if action.figure_style is not None and record.kind != "figure":
        raise JobStateError("figure_style only applies to figure Jobs.")
    if action.type == "cancel":
        return runner.request_cancel(record.job_id)
    if action.type == "retry":
        updated = store.retry(record.job_id)
        runner.submit(record.job_id)
        return updated
    directory = store.job_directory(record.job_id)
    with FileLock(str(directory / ".review.guard"), timeout=10):
        record = store.get(record.job_id)
        if record.status != "WAITING_FOR_REVIEW":
            raise JobConflictError("Only Jobs waiting for review can receive review decisions.")
        ledger = read_review(store, record)
        if action.expected_attempt is not None and action.expected_attempt != record.attempt:
            raise JobConflictError("The reviewed Job attempt has changed.")
        if action.expected_review_version is not None and action.expected_review_version != ledger["version"]:
            raise JobConflictError("The review version has changed.")
        figure_style = _figure_revision_style(store, record, action) if action.type == "reject" and record.kind == "figure" else None
        ledger["version"] += 1
        if action.type.startswith("regenerate_"):
            field = "segments" if action.type.endswith("segments") else "pages"
            if (field == "segments" and record.kind != "polish") or (field == "pages" and record.kind != "translation"):
                raise JobStateError("This regeneration action does not apply to this Job kind.")
            selected = action.segment_ids if field == "segments" else [str(page) for page in action.page_numbers]
            if not selected or len(selected) != len(set(selected)) or set(selected) - _review_ids(store, record, field):
                raise JobStateError("Regeneration must select distinct identifiers present in the current result.")
            if not action.notes.strip():
                raise JobStateError("Provide revision notes when regenerating selected content.")
            if record.attempt >= record.max_attempts:
                raise JobStateError("This Job has reached its revision attempt limit.")
            role = "polish_revision_set" if field == "segments" else "translation_pages"
            previous = read_feature_result(store, record, role)
            retained = {key: dict(ledger.get(key, {})) for key in ("segments", "pages")}
            for identifier in selected:
                retained[field].pop(identifier, None)
            _atomic_write_json(directory / "review_feedback.json", {
                "attempt": record.attempt, "target_revision": record.revision + 1, "notes": action.notes,
                "scope": field, "unit_ids": selected, "previous_result": previous,
                "previous_result_sha256": canonical_hash(previous), "retained_review": retained,
                "review_version": ledger["version"],
            })
            _atomic_write_json(directory / "review.json", ledger)
            updated = store.transition(
                record.job_id, "QUEUED", expected_status="WAITING_FOR_REVIEW", progress=0,
                current_step="selected_revision_requested",
            )
        elif action.type in {"accept", "reject"}:
            if action.type == "reject":
                if not action.notes.strip():
                    raise JobStateError("Provide revision notes when requesting another attempt.")
                if record.attempt >= record.max_attempts:
                    raise JobStateError("This Job has reached its revision attempt limit.")
            ledger.update({"decision": action.type, "notes": action.notes, "updated_at": utc_now()})
            _atomic_write_json(directory / "review.json", ledger)
            if action.type == "reject":
                _atomic_write_json(directory / "review_feedback.json", {
                    "attempt": record.attempt, "notes": action.notes,
                    "segments": ledger.get("segments", {}), "pages": ledger.get("pages", {}),
                    "figure_style": figure_style,
                    "target_revision": record.revision + 1, "review_version": ledger["version"],
                })
            updated = store.transition(
                record.job_id, "SUCCEEDED" if action.type == "accept" else "QUEUED",
                expected_status="WAITING_FOR_REVIEW", progress=100 if action.type == "accept" else 0,
                current_step="review_accepted" if action.type == "accept" else "revision_requested",
            )
        else:
            field = "segments" if action.type.endswith("segments") else "pages"
            if (field == "segments" and record.kind != "polish") or (field == "pages" and record.kind != "translation"):
                raise JobStateError("This review action does not apply to this Job kind.")
            selected = action.segment_ids if field == "segments" else [str(page) for page in action.page_numbers]
            allowed = _review_ids(store, record, field)
            if not selected or len(selected) != len(set(selected)) or set(selected) - allowed:
                raise JobStateError("Review must select distinct identifiers present in the current result.")
            decision = "accepted" if action.type.startswith("accept") else "rejected"
            ledger.setdefault(field, {}).update({key: decision for key in selected})
            ledger.update({"notes": action.notes, "updated_at": utc_now()})
            _atomic_write_json(directory / "review.json", ledger)
            updated = store.get(record.job_id)
        store._append_event(record.job_id, "JOB_REVIEW_RECORDED", {
            "action": action.type, "notes_provided": bool(action.notes.strip()),
            "selected_count": len(action.segment_ids) + len(action.page_numbers),
            "review_version": ledger["version"], "attempt": record.attempt,
        })
    if action.type == "reject" or action.type.startswith("regenerate_"):
        runner.submit(record.job_id)
    return updated
