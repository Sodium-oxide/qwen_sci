"""Load a verified Survey manifest and its Idea handoff artifacts."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from .survey_handoff_persistence import verify_survey_manifest_artifacts
from .survey_idea_handoff import (
    SURVEY_GAP_LEDGER_SCHEMA_VERSION,
    SURVEY_IDEA_HANDOFF_SCHEMA_VERSION,
    SURVEY_MANIFEST_SCHEMA_VERSION,
    validate_gap_ledger_payload,
    validate_handoff_payload,
)


class SurveyIdeaLoadError(ValueError):
    """Raised when a requested Survey run cannot be trusted or loaded."""


def _text(value: Any) -> str:
    return str(value or "").strip()


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise SurveyIdeaLoadError(f"Unable to read {label}: {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise SurveyIdeaLoadError(f"{label} is not valid JSON: {path}: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise SurveyIdeaLoadError(f"{label} must contain a JSON object: {path}")
    return dict(payload)


def _resolve_source(source: str | Path) -> tuple[Path, Path]:
    requested = Path(source).expanduser().resolve()
    if requested.is_file():
        if requested.name == "survey_manifest.json":
            return requested, requested.parent
        if requested.name == "survey.md":
            return requested.parent / "survey_manifest.json", requested.parent
        raise SurveyIdeaLoadError(
            "--survey-manifest must point to survey_manifest.json, a Survey run directory, or survey.md"
        )
    if requested.is_dir():
        return requested / "survey_manifest.json", requested
    raise SurveyIdeaLoadError(f"Survey manifest path does not exist: {requested}")


def _artifact_path(base_dir: Path, manifest: Mapping[str, Any], name: str) -> Path:
    entry = _mapping(_mapping(manifest.get("artifacts")).get(name))
    relative = _text(entry.get("path"))
    if not relative:
        raise SurveyIdeaLoadError(f"Survey manifest is missing artifact entry: {name}")
    candidate = (base_dir / relative).resolve()
    try:
        candidate.relative_to(base_dir)
    except ValueError as exc:
        raise SurveyIdeaLoadError(f"Survey artifact path escapes manifest directory: {name}") from exc
    if not candidate.is_file():
        raise SurveyIdeaLoadError(f"Survey artifact is missing: {candidate}")
    return candidate


def _unique_texts(values: Any) -> list[str]:
    items = values if isinstance(values, (list, tuple, set, frozenset)) else [values]
    result: list[str] = []
    seen: set[str] = set()
    for value in items:
        text = _text(value)
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result


def _handoff_defect_tags(handoff: Mapping[str, Any]) -> list[str]:
    tags: list[str] = []
    for gap in handoff.get("gaps", []):
        if not isinstance(gap, Mapping):
            continue
        audit = gap.get("gap_audit")
        route = _text(audit.get("eligibility_route")) if isinstance(audit, Mapping) else ""
        if route in {"supporting_constraint", "verification_only", "exclude"}:
            continue
        tags.extend(_unique_texts(gap.get("candidate_defect_tags")))
        gap_kind = _text(gap.get("gap_kind"))
        if gap_kind:
            tags.append(gap_kind)
    return _unique_texts(tags)


@dataclass(frozen=True)
class SurveyIdeaContext:
    manifest_path: Path
    base_dir: Path
    manifest: dict[str, Any]
    handoff: dict[str, Any]
    gap_ledger: dict[str, Any]
    project_context: dict[str, Any]
    survey_json: dict[str, Any]
    survey_markdown: str
    topic: str
    defect_tags: list[str] = field(default_factory=list)
    legacy: bool = False

    @property
    def survey_run_id(self) -> str:
        return _text(self.manifest.get("survey_run_id") or self.handoff.get("survey_run_id"))

    @property
    def project_id(self) -> str:
        return _text(self.manifest.get("project_id") or self.handoff.get("project_id"))

    @property
    def project_context_fingerprint(self) -> str:
        return _text(
            self.manifest.get("project_context_fingerprint")
            or self.handoff.get("project_context_fingerprint")
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "schema_version": "survey_idea_context_v1",
            "manifest_path": str(self.manifest_path),
            "base_dir": str(self.base_dir),
            "manifest": dict(self.manifest),
            "handoff": dict(self.handoff),
            "gap_ledger": dict(self.gap_ledger),
            "project_context": dict(self.project_context),
            "survey_json": dict(self.survey_json),
            "survey_markdown": self.survey_markdown,
            "topic": self.topic,
            "survey_run_id": self.survey_run_id,
            "project_id": self.project_id,
            "project_context_fingerprint": self.project_context_fingerprint,
            "defect_tags": list(self.defect_tags),
            "legacy": self.legacy,
        }


def _load_legacy_context(manifest_path: Path, base_dir: Path) -> SurveyIdeaContext:
    markdown_path = base_dir / "survey.md"
    survey_json_path = base_dir / "survey.json"
    if not markdown_path.is_file() or not survey_json_path.is_file():
        raise SurveyIdeaLoadError(
            f"Legacy Survey directory requires survey.md and survey.json: {base_dir}"
        )
    try:
        markdown = markdown_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise SurveyIdeaLoadError(f"Unable to read legacy Survey Markdown: {markdown_path}: {exc}") from exc
    survey_json = _read_json(survey_json_path, "legacy Survey JSON")
    topic = _text(survey_json.get("topic")) or base_dir.name.replace("-", " ")
    project_context = _mapping(survey_json.get("research_context"))
    manifest = {
        "schema_version": "legacy_survey_directory_v0",
        "status": "legacy_unverified",
        "survey_run_id": _text(survey_json.get("research_run_id") or base_dir.name),
        "project_id": _text(survey_json.get("project_id")),
        "topic": topic,
        "base_dir": str(base_dir),
    }
    return SurveyIdeaContext(
        manifest_path=manifest_path,
        base_dir=base_dir,
        manifest=manifest,
        handoff={},
        gap_ledger={},
        project_context=project_context,
        survey_json=survey_json,
        survey_markdown=markdown,
        topic=topic,
        legacy=True,
    )


def load_survey_idea_context(source: str | Path) -> SurveyIdeaContext:
    """Load a completed, hash-verified Survey run for an Idea invocation."""

    manifest_path, base_dir = _resolve_source(source)
    if not manifest_path.is_file():
        return _load_legacy_context(manifest_path, base_dir)

    manifest = _read_json(manifest_path, "Survey manifest")
    if _text(manifest.get("schema_version")) != SURVEY_MANIFEST_SCHEMA_VERSION:
        raise SurveyIdeaLoadError(
            f"Unsupported Survey manifest schema: {manifest.get('schema_version')!r}; "
            f"expected {SURVEY_MANIFEST_SCHEMA_VERSION}"
        )
    declared_base_dir = Path(_text(manifest.get("base_dir"))).expanduser().resolve()
    if declared_base_dir != base_dir:
        raise SurveyIdeaLoadError(
            f"Survey manifest base_dir does not match requested directory: {declared_base_dir} != {base_dir}"
        )
    errors = verify_survey_manifest_artifacts(
        manifest,
        base_dir=base_dir,
        require_completed=True,
    )
    if errors:
        raise SurveyIdeaLoadError("Survey manifest verification failed: " + "; ".join(errors))
    if _text(manifest.get("handoff_schema_version")) != SURVEY_IDEA_HANDOFF_SCHEMA_VERSION:
        raise SurveyIdeaLoadError("Survey manifest handoff schema version is unsupported")
    if _text(manifest.get("gap_ledger_schema_version")) != SURVEY_GAP_LEDGER_SCHEMA_VERSION:
        raise SurveyIdeaLoadError("Survey manifest Gap Ledger schema version is unsupported")

    handoff_path = _artifact_path(base_dir, manifest, "idea_handoff")
    ledger_path = _artifact_path(base_dir, manifest, "gap_ledger")
    context_path = _artifact_path(base_dir, manifest, "project_context")
    survey_json_path = _artifact_path(base_dir, manifest, "survey_json")
    markdown_path = _artifact_path(base_dir, manifest, "survey_markdown")
    handoff = _read_json(handoff_path, "Survey Idea Handoff")
    ledger = _read_json(ledger_path, "Survey Gap Ledger")
    project_context = _read_json(context_path, "Survey project context")
    survey_json = _read_json(survey_json_path, "Survey JSON")
    try:
        markdown = markdown_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise SurveyIdeaLoadError(f"Unable to read Survey Markdown: {markdown_path}: {exc}") from exc
    handoff_errors = validate_handoff_payload(handoff, verify_fingerprint=True)
    if handoff_errors:
        raise SurveyIdeaLoadError("Survey Idea Handoff validation failed: " + "; ".join(handoff_errors))
    ledger_errors = validate_gap_ledger_payload(ledger, verify_fingerprint=True)
    if ledger_errors:
        raise SurveyIdeaLoadError("Survey Gap Ledger validation failed: " + "; ".join(ledger_errors))

    identity_fields = (
        ("project_id", manifest.get("project_id"), handoff.get("project_id"), ledger.get("project_id")),
        ("survey_run_id", manifest.get("survey_run_id"), handoff.get("survey_run_id"), ledger.get("survey_run_id")),
        (
            "project_context_fingerprint",
            manifest.get("project_context_fingerprint"),
            handoff.get("project_context_fingerprint"),
            ledger.get("project_context_fingerprint"),
        ),
    )
    for label, *values in identity_fields:
        normalized = [_text(value) for value in values]
        if not normalized[0] or any(value != normalized[0] for value in normalized[1:]):
            raise SurveyIdeaLoadError(f"Survey artifact identity mismatch for {label}")
    topic = _text(manifest.get("topic")) or _text(handoff.get("topic")) or _text(survey_json.get("topic"))
    return SurveyIdeaContext(
        manifest_path=manifest_path,
        base_dir=base_dir,
        manifest=manifest,
        handoff=handoff,
        gap_ledger=ledger,
        project_context=project_context,
        survey_json=survey_json,
        survey_markdown=markdown,
        topic=topic,
        defect_tags=_handoff_defect_tags(handoff),
    )


__all__ = ["SurveyIdeaContext", "SurveyIdeaLoadError", "load_survey_idea_context"]
