"""Copy and adapt declared LaTeX templates without changing their source tree."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import shutil
import tempfile
from typing import Mapping

from .template_profile import TemplateInsertion, TemplateProfile


class TemplateAdapterError(RuntimeError):
    """Raised when an explicit template cannot be copied or adapted safely."""


@dataclass(frozen=True)
class MaterializedTemplate:
    profile_id: str
    source_dir: Path
    project_dir: Path
    main_tex: Path
    generated_bib: Path


def _resolve_relative(root: Path, value: str, *, label: str) -> Path:
    relative = Path(value)
    if relative.is_absolute() or ".." in relative.parts:
        raise TemplateAdapterError(f"{label} must be a relative path inside the template")
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as error:
        raise TemplateAdapterError(f"{label} escapes the template root") from error
    return candidate


def _reject_symlinks(root: Path) -> None:
    for candidate in root.rglob("*"):
        if candidate.is_symlink():
            raise TemplateAdapterError(
                f"template contains unsupported symlink '{candidate.relative_to(root)}'; copy real supporting files instead"
            )


def _find_exact(content: str, needle: str, *, label: str) -> int:
    count = content.count(needle)
    if count != 1:
        raise TemplateAdapterError(
            f"template insertion '{label}' must occur exactly once; found {count} occurrences"
        )
    return content.index(needle)


def _replacement_span(content: str, insertion: TemplateInsertion, *, label: str) -> tuple[int, int]:
    if insertion.kind == "marker":
        start = _find_exact(content, insertion.marker, label=label)
        return start, start + len(insertion.marker)
    if insertion.kind != "region":
        raise TemplateAdapterError(f"template insertion '{label}' has unsupported kind '{insertion.kind}'")
    start_anchor = _find_exact(content, insertion.start, label=f"{label}.start")
    end_anchor = _find_exact(content, insertion.end, label=f"{label}.end")
    if end_anchor <= start_anchor:
        raise TemplateAdapterError(f"template insertion '{label}' end anchor must follow its start anchor")
    start = start_anchor if insertion.include_start else start_anchor + len(insertion.start)
    end = end_anchor + len(insertion.end) if insertion.include_end else end_anchor
    if end <= start:
        raise TemplateAdapterError(f"template insertion '{label}' resolves to an empty or reversed span")
    return start, end


class TemplateAdapter:
    """Materialize a user-owned template and apply one prevalidated replacement set."""

    def materialize(
        self,
        template_dir: str | Path,
        project_dir: str | Path,
        profile: TemplateProfile,
    ) -> MaterializedTemplate:
        source_dir = Path(template_dir).expanduser().resolve()
        destination = Path(project_dir).expanduser().resolve()
        if not source_dir.is_dir():
            raise TemplateAdapterError(f"template directory does not exist: {source_dir}")
        _reject_symlinks(source_dir)
        source_main = _resolve_relative(source_dir, profile.main_tex, label="template main TeX path")
        if not source_main.is_file():
            raise TemplateAdapterError(
                f"template profile '{profile.profile_id}' main TeX file does not exist: {profile.main_tex}"
            )
        reserved_destination = False
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.mkdir(exist_ok=False)
            reserved_destination = True
            shutil.copytree(source_dir, destination, dirs_exist_ok=True)
        except OSError as error:
            try:
                if reserved_destination and destination.exists():
                    shutil.rmtree(destination, ignore_errors=True)
            except OSError:
                pass
            raise TemplateAdapterError(f"cannot copy template to output-owned project: {error}") from error
        return MaterializedTemplate(
            profile_id=profile.profile_id,
            source_dir=source_dir,
            project_dir=destination,
            main_tex=_resolve_relative(destination, profile.main_tex, label="template main TeX path"),
            generated_bib=_resolve_relative(destination, profile.generated_bib, label="generated BibTeX path"),
        )

    def apply(
        self,
        materialized: MaterializedTemplate,
        profile: TemplateProfile,
        replacements: Mapping[str, str],
    ) -> Path:
        required = set(profile.insertions)
        missing = sorted(required - set(replacements))
        unexpected = sorted(set(replacements) - required)
        if missing or unexpected:
            details: list[str] = []
            if missing:
                details.append("missing replacements: " + ", ".join(missing))
            if unexpected:
                details.append("unexpected replacements: " + ", ".join(unexpected))
            raise TemplateAdapterError("; ".join(details))
        try:
            content = materialized.main_tex.read_text(encoding="utf-8")
        except OSError as error:
            raise TemplateAdapterError(f"cannot read copied template main TeX file: {error}") from error
        spans: list[tuple[int, int, str, str]] = []
        for label, insertion in profile.insertions.items():
            start, end = _replacement_span(content, insertion, label=label)
            spans.append((start, end, label, str(replacements[label])))
        for index, insertion in enumerate(profile.discard_regions):
            start, end = _replacement_span(content, insertion, label=f"discard_regions[{index}]")
            spans.append((start, end, f"discard_regions[{index}]", ""))
        ordered = sorted(spans)
        for previous, current in zip(ordered, ordered[1:]):
            if previous[1] > current[0]:
                raise TemplateAdapterError(
                    f"template profile '{profile.profile_id}' contains overlapping insertion regions "
                    f"('{previous[2]}' and '{current[2]}')"
                )
        rendered = content
        for start, end, _label, replacement in sorted(spans, reverse=True):
            rendered = rendered[:start] + replacement + rendered[end:]
        temporary: Path | None = None
        try:
            descriptor, raw_path = tempfile.mkstemp(
                prefix=f".{materialized.main_tex.name}.",
                suffix=".tmp",
                dir=materialized.main_tex.parent,
                text=True,
            )
            temporary = Path(raw_path)
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(rendered)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, materialized.main_tex)
        except OSError as error:
            raise TemplateAdapterError(f"cannot write adapted TeX file: {error}") from error
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        return materialized.main_tex


__all__ = ["MaterializedTemplate", "TemplateAdapter", "TemplateAdapterError"]
