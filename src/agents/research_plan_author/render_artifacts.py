"""Atomic, non-overwriting publication of Author TeX/PDF render artifacts."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import tempfile
from typing import Any, Mapping

from .tex_renderer import TexRenderResult


class RenderArtifactError(RuntimeError):
    """Raised when a render artifact cannot be allocated or published safely."""


@dataclass(frozen=True)
class AuthorRenderArtifactPaths:
    timestamp: str
    preparation_collision_index: int
    render_collision_index: int
    project_dir: Path
    tex: Path
    bibtex: Path
    bibliography_needs_completion: Path
    render_manifest: Path
    compile_log: Path
    compile_json: Path
    pdf_validation_json: Path
    pdf: Path
    staged_pdf: Path

    def as_dict(self) -> dict[str, str | int]:
        return {
            "timestamp": self.timestamp,
            "preparation_collision_index": self.preparation_collision_index,
            "render_collision_index": self.render_collision_index,
            "project_dir": str(self.project_dir),
            "tex": str(self.tex),
            "bibtex": str(self.bibtex),
            "bibliography_needs_completion": str(self.bibliography_needs_completion),
            "render_manifest": str(self.render_manifest),
            "compile_log": str(self.compile_log),
            "compile_json": str(self.compile_json),
            "pdf_validation_json": str(self.pdf_validation_json),
            "pdf": str(self.pdf),
        }


def _json_text(payload: object) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n"


def _write_bytes_without_overwrite(path: Path, content: bytes) -> None:
    temporary: Path | None = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, raw_path = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
        temporary = Path(raw_path)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError as error:
            raise RenderArtifactError(f"artifact target already exists: {path}") from error
        except OSError:
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
            with os.fdopen(descriptor, "wb") as handle, temporary.open("rb") as source:
                handle.write(source.read())
                handle.flush()
                os.fsync(handle.fileno())
    except OSError as error:
        raise RenderArtifactError(f"cannot publish artifact '{path.name}': {error}") from error
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _write_text_without_overwrite(path: Path, content: str) -> None:
    _write_bytes_without_overwrite(path, content.encode("utf-8"))


class AuthorRenderArtifactWriter:
    """Reserve one timestamped artifact family and publish it without overwrites."""

    def __init__(self, output_dir: str | Path) -> None:
        self.output_dir = Path(output_dir).expanduser().resolve()

    def allocate(
        self,
        *,
        timestamp: str,
        preparation_collision_index: int,
    ) -> AuthorRenderArtifactPaths:
        try:
            self.output_dir.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            raise RenderArtifactError(f"cannot create Author render output directory: {error}") from error
        preparation_suffix = "" if preparation_collision_index == 0 else f"_{preparation_collision_index}"
        for render_collision_index in range(1000):
            render_suffix = "" if render_collision_index == 0 else f"_render{render_collision_index}"
            stem = f"research_plan_{timestamp}{preparation_suffix}{render_suffix}"
            paths = AuthorRenderArtifactPaths(
                timestamp=timestamp,
                preparation_collision_index=preparation_collision_index,
                render_collision_index=render_collision_index,
                project_dir=self.output_dir / f"{stem}_project",
                tex=self.output_dir / f"{stem}.tex",
                bibtex=self.output_dir / f"references_{timestamp}{preparation_suffix}{render_suffix}.bib",
                bibliography_needs_completion=self.output_dir
                / f"bibliography_needs_completion_{timestamp}{preparation_suffix}{render_suffix}.json",
                render_manifest=self.output_dir / f"research_plan_render_{timestamp}{preparation_suffix}{render_suffix}.json",
                compile_log=self.output_dir / f"compile_{timestamp}{preparation_suffix}{render_suffix}.log",
                compile_json=self.output_dir / f"compile_{timestamp}{preparation_suffix}{render_suffix}.json",
                pdf_validation_json=self.output_dir / f"pdf_validation_{timestamp}{preparation_suffix}{render_suffix}.json",
                pdf=self.output_dir / f"{stem}.pdf",
                staged_pdf=self.output_dir / f".{stem}.pdf.staging",
            )
            targets = [
                paths.project_dir,
                paths.tex,
                paths.bibtex,
                paths.bibliography_needs_completion,
                paths.render_manifest,
                paths.compile_log,
                paths.compile_json,
                paths.pdf_validation_json,
                paths.pdf,
                paths.staged_pdf,
            ]
            if not any(target.exists() for target in targets):
                return paths
        raise RenderArtifactError(f"could not allocate an unused render artifact family for timestamp '{timestamp}'")

    def publish_sources(self, rendered: TexRenderResult, paths: AuthorRenderArtifactPaths) -> None:
        if rendered.project_dir.resolve() != paths.project_dir.resolve():
            raise RenderArtifactError("rendered TeX project does not match its allocated artifact directory")
        try:
            _write_bytes_without_overwrite(paths.tex, rendered.main_tex.read_bytes())
            _write_bytes_without_overwrite(paths.bibtex, rendered.bibtex.read_bytes())
            _write_text_without_overwrite(
                paths.bibliography_needs_completion,
                _json_text(
                    {
                        "schema_version": "research_plan_author_bibliography_completion_v1",
                        "needs_completion": list(rendered.bibliography.needs_completion),
                    }
                ),
            )
            _write_text_without_overwrite(paths.render_manifest, _json_text(rendered.as_dict()))
        except OSError as error:
            raise RenderArtifactError(f"cannot publish generated TeX/BibTeX sources: {error}") from error

    def publish_compile_diagnostics(
        self,
        paths: AuthorRenderArtifactPaths,
        *,
        report: Mapping[str, Any],
        log_text: str,
    ) -> None:
        _write_text_without_overwrite(paths.compile_log, str(log_text))
        _write_text_without_overwrite(paths.compile_json, _json_text(dict(report)))

    def publish_pdf_validation(self, paths: AuthorRenderArtifactPaths, report: Mapping[str, Any]) -> None:
        _write_text_without_overwrite(paths.pdf_validation_json, _json_text(dict(report)))

    def publish_validated_pdf(self, paths: AuthorRenderArtifactPaths) -> None:
        if not paths.staged_pdf.is_file():
            raise RenderArtifactError("validated PDF staging file does not exist")
        try:
            _write_bytes_without_overwrite(paths.pdf, paths.staged_pdf.read_bytes())
        finally:
            paths.staged_pdf.unlink(missing_ok=True)

    def discard_staged_pdf(self, paths: AuthorRenderArtifactPaths) -> None:
        paths.staged_pdf.unlink(missing_ok=True)


__all__ = [
    "AuthorRenderArtifactPaths",
    "AuthorRenderArtifactWriter",
    "RenderArtifactError",
]
