"""Load and validate a canonical ExperimentDesign Author handoff."""

from __future__ import annotations

import json
import hashlib
from pathlib import Path
from typing import Any, Mapping

from .contracts import validate_author_input
from src.agents.experiment_design_agent.formal_storage import (
    SUMMARY_VERSION, compact_report, resolve_archive_reference, resolve_report_reference, revision_summary, semantic_content,
)


class AuthorInputLoadError(ValueError):
    """Raised when an Author handoff cannot safely enter the writing workflow."""


def load_author_input_with_identity(path: str | Path) -> tuple[Path, dict[str, Any], dict[str, Any]]:
    """Read, validate, snapshot, and identify one handoff from the same bytes."""

    resolved_path = Path(path).expanduser().resolve()
    if not resolved_path.is_file():
        raise AuthorInputLoadError(f"Research Plan Author input is not a file: {resolved_path}")
    try:
        raw_bytes = resolved_path.read_bytes()
    except OSError as error:
        raise AuthorInputLoadError(f"Cannot read Research Plan Author input '{resolved_path}': {error}") from error
    try:
        payload = json.loads(raw_bytes.decode("utf-8"))
    except json.JSONDecodeError as error:
        raise AuthorInputLoadError(f"Research Plan Author input is not valid JSON: {resolved_path}: {error}") from error
    except UnicodeDecodeError as error:
        raise AuthorInputLoadError(f"Research Plan Author input is not UTF-8 JSON: {resolved_path}: {error}") from error
    if not isinstance(payload, Mapping):
        raise AuthorInputLoadError("Research Plan Author input must contain one JSON object")
    report = payload.get("formal_verification_report")
    if isinstance(report, Mapping) and report.get("schema_version") == SUMMARY_VERSION:
        try:
            resolve_report_reference(report, base_dir=resolved_path.parent)
            report["archive_ref"]["path"] = str((resolved_path.parent / report["archive_ref"]["path"]).resolve())
        except (ValueError, TypeError) as error:
            raise AuthorInputLoadError(f"Research Plan Author verification reference is invalid: {error}") from error
    elif payload.get("formal_audit_ref"):
        try:
            archive = resolve_archive_reference(payload["formal_audit_ref"], base_dir=resolved_path.parent)
            summary = payload.get("formal_revision_audit")
            if summary and {key: value for key, value in summary.items() if key != "archive_ref"} != revision_summary(archive["revision_audit"]):
                raise ValueError("revision_summary_mismatch")
        except (ValueError, TypeError, KeyError) as error:
            raise AuthorInputLoadError(f"Research Plan Author audit reference is invalid: {error}") from error
    errors = validate_author_input(payload)
    if errors:
        raise AuthorInputLoadError("Research Plan Author input validation failed: " + "; ".join(errors))
    if isinstance(report, Mapping) and report.get("schema_version") != SUMMARY_VERSION:
        payload["formal_verification_report"] = compact_report(report)
    if "formal_revision_audit" in payload:
        payload["formal_revision_audit"] = revision_summary(payload["formal_revision_audit"])
    payload = semantic_content(payload)
    return (
        resolved_path,
        dict(payload),
        {
            "path": str(resolved_path),
            "sha256": hashlib.sha256(raw_bytes).hexdigest(),
            "byte_size": len(raw_bytes),
        },
    )


def load_author_input(path: str | Path) -> tuple[Path, dict[str, Any]]:
    """Read one explicit Author JSON artifact without selecting an ambiguous run file."""

    resolved_path, payload, _identity = load_author_input_with_identity(path)
    return resolved_path, payload


def identify_author_input(path: str | Path) -> dict[str, Any]:
    """Return a stable identity for the exact handoff bytes that were loaded."""

    resolved_path = Path(path).expanduser().resolve()
    try:
        raw_bytes = resolved_path.read_bytes()
    except OSError as error:
        raise AuthorInputLoadError(f"Cannot identify Research Plan Author input '{resolved_path}': {error}") from error
    return {
        "path": str(resolved_path),
        "sha256": hashlib.sha256(raw_bytes).hexdigest(),
        "byte_size": len(raw_bytes),
    }


__all__ = [
    "AuthorInputLoadError",
    "identify_author_input",
    "load_author_input",
    "load_author_input_with_identity",
]
