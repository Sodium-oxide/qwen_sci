"""Frozen-input readers and content-addressed checkpoints for feature workers."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from .job_artifacts import _atomic_write_json
from .jobs import JobContext, JobInputError
from .jobs.store import canonical_hash


def source_text(file_service: Any, input_data: Mapping[str, object]) -> str:
    if isinstance(input_data.get("text"), str):
        return str(input_data["text"])
    files = input_data.get("files")
    if not isinstance(files, list) or len(files) != 1:
        raise JobInputError("The document requires one source file.")
    record = files[0]
    path = file_service.content_path(str(record["file_id"]))
    suffix = Path(str(record.get("original_name") or "")).suffix.casefold()
    if suffix == ".docx":
        from docx import Document

        document = Document(path)
        if document.element.xpath(".//m:oMath"):
            raise JobInputError("DOCX equations require a LaTeX or Markdown source to preserve their exact content.")
        from docx.table import Table

        paragraphs = []
        for item in document.iter_inner_content():
            if isinstance(item, Table):
                paragraphs.append("\n".join("| " + " | ".join(cell.text.replace("|", "\\|") for cell in row.cells) + " |" for row in item.rows))
            else:
                paragraphs.append(item.text)
        return "\n\n".join(paragraphs)
    if suffix not in {".txt", ".md", ".markdown", ".tex", ".latex"}:
        raise JobInputError("Polishing accepts UTF-8 text, Markdown, LaTeX, or DOCX.")
    try:
        return path.read_text(encoding="utf-8-sig")
    except UnicodeError as exc:
        raise JobInputError("The source document is not valid UTF-8.") from exc


def revision_request(context: JobContext) -> dict[str, Any]:
    path = context.job_dir / "review_feedback.json"
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("target_revision", context.job.revision) != context.job.revision:
        return {}
    if "previous_result" in payload and canonical_hash(payload["previous_result"]) != payload.get("previous_result_sha256"):
        raise JobInputError("The retained revision result no longer matches its hash.")
    return payload


def revision_feedback(context: JobContext) -> dict[str, object]:
    payload = revision_request(context)
    return {key: value for key, value in payload.items() if key in {"attempt", "target_revision", "notes", "scope", "unit_ids", "segments", "pages", "figure_style"}}


_DEFAULT_FEEDBACK = object()


def checkpoint_value(
    context: JobContext, key: object, produce: Callable[[], dict[str, Any]],
    validate: Callable[[dict[str, Any]], Any] | None = None,
    *, feedback: object = _DEFAULT_FEEDBACK,
) -> dict[str, Any]:
    digest = canonical_hash({
        "input": context.job.input_manifest_sha256, "prompt": context.job.prompt_hash,
        "feedback": revision_feedback(context) if feedback is _DEFAULT_FEEDBACK else feedback, "unit": key,
        "model": context.job.model_name, "provider": context.job.provider_name,
    })
    path = context.job_dir / "checkpoints" / f"{digest}.json"
    if path.exists():
        context.check_cancelled()
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("sha256") != canonical_hash(payload.get("value")):
            raise JobInputError("The worker checkpoint no longer matches its recorded hash.")
        if validate is not None:
            validate(payload["value"])
        return payload["value"]
    value = produce()
    if validate is not None:
        validate(value)
    context.check_cancelled()
    with context.store.lease_guard(context.job.job_id, lease_owner=context.lease_owner, attempt=context.job.attempt):
        path.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write_json(path, {"sha256": canonical_hash(value), "value": value})
    return value
