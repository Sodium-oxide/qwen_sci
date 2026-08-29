"""Load the Survey artifacts required by a complete Research Plan Author run."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Mapping

from src.pipeline.survey_idea_loader import SurveyIdeaLoadError, load_survey_idea_context


class SurveyAuthorSourceError(ValueError):
    """Raised when verified Survey sources cannot be used for Author writing."""


_REQUIRED_ARTIFACTS = (
    "idea_handoff",
    "gap_ledger",
    "project_context",
    "survey_json",
    "survey_markdown",
    "claim_traceability",
    "evidence_plan",
)
_MARKDOWN_HEADING = re.compile(r"^#{1,6}\s+.+?\s*$", re.MULTILINE)


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _text(value: object) -> str:
    return str(value or "").strip()


def _safe_artifact_path(base_dir: Path, entry: Mapping[str, Any], name: str) -> Path:
    relative_path = _text(entry.get("path"))
    if not relative_path:
        raise SurveyAuthorSourceError(f"Survey manifest is missing artifact entry: {name}")
    candidate = (base_dir / relative_path).resolve()
    try:
        candidate.relative_to(base_dir)
    except ValueError as error:
        raise SurveyAuthorSourceError(f"Survey artifact path escapes manifest directory: {name}") from error
    if not candidate.is_file():
        raise SurveyAuthorSourceError(f"Survey artifact is missing: {candidate}")
    return candidate


def _read_json(path: Path, name: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as error:
        raise SurveyAuthorSourceError(f"Cannot read Survey artifact '{name}': {error}") from error
    except json.JSONDecodeError as error:
        raise SurveyAuthorSourceError(f"Survey artifact '{name}' is not valid JSON: {error}") from error
    if not isinstance(payload, Mapping):
        raise SurveyAuthorSourceError(f"Survey artifact '{name}' must contain one JSON object")
    return dict(payload)


def _survey_markdown_excerpts(markdown: str) -> list[dict[str, Any]]:
    """Split verified Survey Markdown into complete, source-addressable excerpts."""

    starts = [match.start() for match in _MARKDOWN_HEADING.finditer(markdown)]
    boundaries = [0, *starts] if starts and starts[0] else starts
    if not boundaries:
        boundaries = [0] if markdown.strip() else []
    excerpts: list[dict[str, Any]] = []
    for ordinal, start in enumerate(boundaries, start=1):
        end = boundaries[ordinal] if ordinal < len(boundaries) else len(markdown)
        text = markdown[start:end].strip()
        if not text:
            continue
        first_line = text.splitlines()[0].strip()
        heading = first_line.lstrip("#").strip() if first_line.startswith("#") else "Survey preamble"
        excerpts.append(
            {
                "anchor_id": f"survey:survey_markdown#section-{ordinal:03d}",
                "heading": heading,
                "ordinal": ordinal,
                "text": text,
            }
        )
    return excerpts


def load_verified_survey_sources(source: str | Path) -> dict[str, Any]:
    """Return a verified, source-addressable Survey bundle for Author composition."""

    try:
        context = load_survey_idea_context(source)
    except SurveyIdeaLoadError as error:
        raise SurveyAuthorSourceError(str(error)) from error
    if context.legacy:
        raise SurveyAuthorSourceError(
            "Research Plan Author requires a completed, verified survey_manifest.json; legacy Survey directories are unsupported"
        )
    artifact_entries = _mapping(context.manifest.get("artifacts"))
    artifact_paths: dict[str, str] = {}
    artifacts: dict[str, Any] = {}
    for name in _REQUIRED_ARTIFACTS:
        path = _safe_artifact_path(context.base_dir, _mapping(artifact_entries.get(name)), name)
        artifact_paths[name] = str(path)
        if name == "survey_markdown":
            artifacts[name] = {
                "path": str(path),
                "content_available": True,
                "excerpts": _survey_markdown_excerpts(context.survey_markdown),
            }
        else:
            artifacts[name] = _read_json(path, name)
    for name, raw_entry in artifact_entries.items():
        if name in artifacts:
            continue
        entry = _mapping(raw_entry)
        relative_path = _text(entry.get("path"))
        if not relative_path:
            continue
        optional_path = _safe_artifact_path(context.base_dir, entry, str(name))
        artifact_paths[str(name)] = str(optional_path)
    return {
        "schema_version": "research_plan_author_survey_sources_v1",
        "manifest_path": str(context.manifest_path),
        "base_dir": str(context.base_dir),
        "survey_run_id": context.survey_run_id,
        "project_id": context.project_id,
        "project_context_fingerprint": context.project_context_fingerprint,
        "topic": context.topic,
        "manifest": dict(context.manifest),
        "artifacts": artifacts,
        "artifact_paths": artifact_paths,
    }


__all__ = ["SurveyAuthorSourceError", "load_verified_survey_sources"]
