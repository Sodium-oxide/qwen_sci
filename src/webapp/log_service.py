"""Safe, paginated access to run-owned stage logs for the browser workspace."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from src.pipeline.science_run import ScienceRunPaths

from .redaction import safe_payload, safe_text
from .schemas import RunLogChunkView, RunLogView


_LOG_SUFFIXES = frozenset({".jsonl", ".log"})
_STAGE_LOG_DIRECTORIES = {
    "survey": "survey",
    "idea": "idea",
    "exp_design": "experiment_design",
    "author": "author",
}
_STAGE_LABELS = {
    "survey": "Survey",
    "idea": "Idea",
    "exp_design": "ExperimentDesign",
    "author": "Author",
}
_ATTEMPT_DIRECTORY = re.compile(r"attempt-(\d+)$")
MAX_LOG_SOURCES = 256
MAX_LOG_CHUNK_BYTES = 262_144


class RunLogError(ValueError):
    """Raised when a requested run log is unavailable or outside the log allowlist."""


@dataclass(frozen=True)
class _LogSource:
    log_id: str
    stage: str
    attempt: int | None
    path: Path
    log_format: str

    def view(self) -> RunLogView:
        attempt_label = f"第 {self.attempt} 次尝试" if self.attempt is not None else "阶段日志"
        return RunLogView(
            log_id=self.log_id,
            label=f"{_STAGE_LABELS[self.stage]} · {attempt_label} · {self.path.name}",
            stage=self.stage,
            attempt=self.attempt,
            format=self.log_format,
            size_bytes=self.path.stat().st_size,
        )


def _safe_stage_file(path: Path, stage_root: Path) -> Path | None:
    try:
        resolved = path.resolve(strict=True)
        resolved.relative_to(stage_root.resolve())
    except (OSError, ValueError):
        return None
    return resolved if resolved.is_file() else None


def _attempt_from(relative_path: Path) -> int | None:
    for part in relative_path.parts:
        match = _ATTEMPT_DIRECTORY.fullmatch(part)
        if match:
            return int(match.group(1))
    return None


def _discover_log_sources(paths: ScienceRunPaths) -> Iterable[_LogSource]:
    discovered = 0
    for stage, directory_name in _STAGE_LOG_DIRECTORIES.items():
        stage_root = paths.run_dir / directory_name
        if not stage_root.is_dir():
            continue
        try:
            candidates = sorted(path for path in stage_root.rglob("*") if path.is_file())
        except OSError:
            continue
        for candidate in candidates:
            if discovered >= MAX_LOG_SOURCES or candidate.suffix.casefold() not in _LOG_SUFFIXES:
                continue
            safe_path = _safe_stage_file(candidate, stage_root)
            if safe_path is None:
                continue
            try:
                relative_path = safe_path.relative_to(stage_root.resolve())
                size_bytes = safe_path.stat().st_size
            except (OSError, ValueError):
                continue
            if size_bytes < 0:
                continue
            log_format = "jsonl" if safe_path.suffix.casefold() == ".jsonl" else "text"
            yield _LogSource(
                log_id=f"{stage}:{relative_path.as_posix()}",
                stage=stage,
                attempt=_attempt_from(relative_path),
                path=safe_path,
                log_format=log_format,
            )
            discovered += 1


def _indexed_sources(paths: ScienceRunPaths) -> dict[str, _LogSource]:
    return {source.log_id: source for source in _discover_log_sources(paths)}


def list_run_logs(paths: ScienceRunPaths) -> list[RunLogView]:
    """List run-generated log files without revealing server paths."""

    views: list[RunLogView] = []
    for source in _indexed_sources(paths).values():
        try:
            views.append(source.view())
        except OSError:
            continue
    return sorted(
        views,
        key=lambda view: (view.stage, view.attempt is None, view.attempt or 0, view.label),
    )


def _safe_jsonl_chunk(text: str) -> str:
    rendered_lines: list[str] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            decoded = json.loads(line)
        except json.JSONDecodeError:
            rendered_lines.append(safe_text(line))
            continue
        rendered_lines.append(json.dumps(safe_payload(decoded), ensure_ascii=False, indent=2, sort_keys=True))
    return "\n".join(rendered_lines)


def _read_chunk(path: Path, *, offset: int, limit: int) -> tuple[bytes, int, int]:
    try:
        size_bytes = path.stat().st_size
    except OSError as exc:
        raise RunLogError("The requested log is no longer available.") from exc
    offset = min(offset, size_bytes)
    try:
        with path.open("rb") as handle:
            handle.seek(offset)
            chunk = handle.read(limit)
    except OSError as exc:
        raise RunLogError("The requested log could not be read.") from exc
    if offset + len(chunk) < size_bytes:
        newline = chunk.rfind(b"\n")
        if newline >= 0:
            chunk = chunk[: newline + 1]
    return chunk, offset + len(chunk), size_bytes


def read_run_log(paths: ScienceRunPaths, *, log_id: str, offset: int, limit: int) -> RunLogChunkView:
    """Return one bounded, redacted log chunk selected by a server-issued identifier."""

    source = _indexed_sources(paths).get(log_id)
    if source is None:
        raise RunLogError("Unknown research log.")
    chunk, next_offset, size_bytes = _read_chunk(source.path, offset=offset, limit=min(limit, MAX_LOG_CHUNK_BYTES))
    decoded = chunk.decode("utf-8", errors="replace")
    content = _safe_jsonl_chunk(decoded) if source.log_format == "jsonl" else safe_text(decoded)
    return RunLogChunkView(
        log_id=source.log_id,
        format=source.log_format,
        offset=offset,
        next_offset=next_offset,
        has_more=next_offset < size_bytes,
        content=content,
    )
