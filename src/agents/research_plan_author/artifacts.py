"""Atomic preparation artifacts for the staged Research Plan Author workflow."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any, Mapping

from src.agents.experiment_design_agent.artifacts import generate_timestamp

from .contracts import (
    AUTHOR_PREPARATION_SCHEMA_VERSION,
    validate_author_preparation,
)
from .document_quality import render_document_quality_report
from .markdown_renderer import render_research_plan_markdown


_TIMESTAMP_PATTERN = re.compile(r"^\d{8}-\d{6}-\d{6}$")


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


class AuthorArtifactError(RuntimeError):
    """Base error for Author preparation artifact publication."""


class AuthorArtifactValidationError(AuthorArtifactError):
    """Raised when a preparation payload does not meet its contract."""


class AuthorArtifactWriteError(AuthorArtifactError):
    """Raised when preparation artifacts cannot be published atomically."""


@dataclass(frozen=True)
class AuthorPreparationArtifactPaths:
    timestamp: str
    collision_index: int
    preparation_json: Path
    author_context_json: Path
    document_json: Path
    document_markdown: Path
    idea_evolution_json: Path
    document_quality_json: Path
    document_quality_report_markdown: Path
    candidate_markdowns: tuple[Path, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "collision_index": self.collision_index,
            "preparation_json": str(self.preparation_json),
            "author_context_json": str(self.author_context_json),
            "document_json": str(self.document_json),
            "document_markdown": str(self.document_markdown),
            "idea_evolution_json": str(self.idea_evolution_json),
            "document_quality_json": str(self.document_quality_json),
            "document_quality_report_markdown": str(self.document_quality_report_markdown),
            "candidate_markdowns": [str(path) for path in self.candidate_markdowns],
        }


def _json_text(payload: object) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n"


def _validate_payload(payload: Mapping[str, Any]) -> None:
    if payload.get("schema_version") != AUTHOR_PREPARATION_SCHEMA_VERSION:
        raise AuthorArtifactValidationError("preparation schema_version is invalid")
    preparation_errors = validate_author_preparation(payload)
    if preparation_errors:
        details = list(preparation_errors)
        raise AuthorArtifactValidationError("preparation validation failed: " + "; ".join(details))


def _write_temp_text(directory: Path, filename: str, content: str) -> Path:
    try:
        descriptor, raw_path = tempfile.mkstemp(prefix=f".{filename}.", suffix=".tmp", dir=directory, text=True)
    except OSError as error:
        raise AuthorArtifactWriteError(f"Cannot create temporary artifact for '{filename}': {error}") from error
    temp_path = Path(raw_path)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
    except OSError as error:
        temp_path.unlink(missing_ok=True)
        raise AuthorArtifactWriteError(f"Cannot write temporary artifact for '{filename}': {error}") from error
    return temp_path


def _publish_without_overwrite(temp_path: Path, target_path: Path) -> None:
    try:
        os.link(temp_path, target_path)
    except FileExistsError as error:
        raise AuthorArtifactWriteError(f"Artifact target already exists: {target_path}") from error
    except OSError:
        try:
            descriptor = os.open(target_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
        except FileExistsError as error:
            raise AuthorArtifactWriteError(f"Artifact target already exists: {target_path}") from error
        try:
            with os.fdopen(descriptor, "wb") as target_handle, temp_path.open("rb") as source_handle:
                target_handle.write(source_handle.read())
                target_handle.flush()
                os.fsync(target_handle.fileno())
        except OSError as error:
            target_path.unlink(missing_ok=True)
            raise AuthorArtifactWriteError(f"Cannot publish artifact '{target_path}': {error}") from error
    finally:
        temp_path.unlink(missing_ok=True)


def _candidate_paths(output_dir: Path, timestamp: str, collision_index: int, *, candidate_count: int) -> AuthorPreparationArtifactPaths:
    suffix = "" if collision_index == 0 else f"_{collision_index}"
    return AuthorPreparationArtifactPaths(
        timestamp=timestamp,
        collision_index=collision_index,
        preparation_json=output_dir / f"research_plan_author_preparation_{timestamp}{suffix}.json",
        author_context_json=output_dir / f"research_plan_author_context_{timestamp}{suffix}.json",
        document_json=output_dir / f"research_plan_document_{timestamp}{suffix}.json",
        document_markdown=output_dir / f"research_plan_document_{timestamp}{suffix}.md",
        idea_evolution_json=output_dir / f"idea_evolution_appendix_{timestamp}{suffix}.json",
        document_quality_json=output_dir / f"research_plan_document_quality_{timestamp}{suffix}.json",
        document_quality_report_markdown=output_dir / f"research_plan_document_quality_{timestamp}{suffix}.md",
        candidate_markdowns=tuple(
            output_dir / f"research_plan_document_{timestamp}{suffix}_candidate_{index:02d}.md"
            for index in range(candidate_count)
        ),
    )


class AuthorPreparationArtifactWriter:
    """Write only validated Batch-A preparation artifacts without prose generation."""

    def __init__(self, output_dir: str | Path) -> None:
        self.output_dir = Path(output_dir).expanduser().resolve()

    def write(
        self,
        payload: Mapping[str, Any],
        *,
        generated_at: datetime | None = None,
        timestamp: str | None = None,
    ) -> AuthorPreparationArtifactPaths:
        _validate_payload(payload)
        effective_timestamp = timestamp or generate_timestamp(generated_at or datetime.now().astimezone())
        if not _TIMESTAMP_PATTERN.fullmatch(effective_timestamp):
            raise AuthorArtifactValidationError(
                f"timestamp must match YYYYMMDD-HHMMSS-ffffff: {effective_timestamp}"
            )
        try:
            self.output_dir.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            raise AuthorArtifactWriteError(f"Cannot create Author output directory '{self.output_dir}': {error}") from error
        document_quality = _mapping(payload.get("document_quality"))
        candidates = [item for item in document_quality.get("candidates") or [] if isinstance(item, Mapping)]
        contents = {
            "preparation_json": _json_text(payload),
            "author_context_json": _json_text(payload["source_bundle"]["author_context"]),
            "document_json": _json_text(payload["document"]),
            "document_markdown": render_research_plan_markdown(payload["document"]),
            "idea_evolution_json": _json_text(payload["source_bundle"]["idea_evolution"]),
            "document_quality_json": _json_text(document_quality),
            "document_quality_report_markdown": render_document_quality_report(document_quality),
        }
        for collision_index in range(1000):
            paths = _candidate_paths(
                self.output_dir,
                effective_timestamp,
                collision_index,
                candidate_count=len(candidates),
            )
            artifact_entries = [
                (paths.preparation_json, contents["preparation_json"]),
                (paths.author_context_json, contents["author_context_json"]),
                (paths.document_json, contents["document_json"]),
                (paths.document_markdown, contents["document_markdown"]),
                (paths.idea_evolution_json, contents["idea_evolution_json"]),
                (paths.document_quality_json, contents["document_quality_json"]),
                (paths.document_quality_report_markdown, contents["document_quality_report_markdown"]),
                *[
                    (target, str(candidate.get("markdown") or ""))
                    for target, candidate in zip(paths.candidate_markdowns, candidates)
                ],
            ]
            targets = [target for target, _content in artifact_entries]
            if any(target.exists() for target in targets):
                continue
            temp_paths: list[tuple[Path, Path]] = []
            published: list[Path] = []
            try:
                for target, content in artifact_entries:
                    temp_paths.append((_write_temp_text(self.output_dir, target.name, content), target))
                for temp_path, target in temp_paths:
                    _publish_without_overwrite(temp_path, target)
                    published.append(target)
                return paths
            except Exception as error:
                for temp_path, _target in temp_paths:
                    temp_path.unlink(missing_ok=True)
                for published_path in published:
                    published_path.unlink(missing_ok=True)
                if isinstance(error, AuthorArtifactError):
                    raise
                raise AuthorArtifactWriteError(f"Cannot publish Author preparation artifacts: {error}") from error
        raise AuthorArtifactWriteError(f"Could not find an unused filename for timestamp '{effective_timestamp}'")


def write_author_preparation_artifacts(
    payload: Mapping[str, Any],
    output_dir: str | Path,
    *,
    generated_at: datetime | None = None,
    timestamp: str | None = None,
) -> AuthorPreparationArtifactPaths:
    return AuthorPreparationArtifactWriter(output_dir).write(
        payload,
        generated_at=generated_at,
        timestamp=timestamp,
    )


def write_author_contract_failure_audit(
    audit: Mapping[str, Any],
    output_dir: str | Path,
    *,
    timestamp: str,
) -> Path:
    """Persist the raw failed JSON contract for review without logging it to console."""

    if not isinstance(audit, Mapping):
        raise AuthorArtifactValidationError("contract failure audit must be an object")
    destination = Path(output_dir).expanduser().resolve()
    try:
        destination.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise AuthorArtifactWriteError(f"Cannot create Author audit directory '{destination}': {error}") from error
    for collision_index in range(1000):
        suffix = "" if collision_index == 0 else f"_{collision_index}"
        target = destination / f"author_contract_failure_{timestamp}{suffix}.json"
        if target.exists():
            continue
        temp_path = _write_temp_text(destination, target.name, _json_text(audit))
        try:
            _publish_without_overwrite(temp_path, target)
            return target
        except FileExistsError:
            continue
    raise AuthorArtifactWriteError(f"Could not find an unused contract audit filename for timestamp '{timestamp}'")


__all__ = [
    "AuthorArtifactError",
    "AuthorArtifactValidationError",
    "AuthorArtifactWriteError",
    "AuthorPreparationArtifactPaths",
    "AuthorPreparationArtifactWriter",
    "write_author_contract_failure_audit",
    "write_author_preparation_artifacts",
]
