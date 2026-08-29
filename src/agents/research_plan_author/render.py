"""End-to-end, design-only Research Plan TeX/PDF rendering orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from collections.abc import Mapping
from typing import Any

from .latex_compiler import LatexCompilerError, compile_latex_project, resolve_executable
from .pdf_validator import PdfValidationError, PdfValidationResult, validate_pdf
from .render_artifacts import AuthorRenderArtifactPaths, AuthorRenderArtifactWriter, RenderArtifactError
from .template_profile import TemplateProfileError, load_template_profile
from .tex_renderer import TexRenderError, TexRenderResult, render_tex_project


class AuthorRenderingError(RuntimeError):
    """Typed render failure with retained source/diagnostic artifacts."""

    def __init__(self, stage: str, message: str, *, paths: AuthorRenderArtifactPaths | None = None) -> None:
        super().__init__(f"{stage}: {message}")
        self.stage = stage
        self.paths = paths


@dataclass(frozen=True)
class AuthorRenderingResult:
    artifacts: AuthorRenderArtifactPaths
    tex: TexRenderResult
    pdf_validation: PdfValidationResult


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _text(value: object) -> str:
    return str(value or "").strip()


def render_research_plan_document(
    document: Mapping[str, Any],
    *,
    output_dir: str | Path,
    timestamp: str,
    preparation_collision_index: int,
    template_dir: str | Path,
    template_profile: str | Path | None = None,
    template_main: str | None = None,
    latex_engine: str | Path | None = None,
    bibtex: str | Path | None = None,
    pdf_renderer: str | Path | None = None,
    compile_timeout_seconds: int = 180,
    configured_rendering: Mapping[str, Any] | None = None,
    author_name: str = "Anonymous Research Plan Author",
    logger: Any | None = None,
) -> AuthorRenderingResult:
    """Render, compile, and validate a proposal PDF without an execution fallback."""

    settings = _mapping(configured_rendering)
    writer = AuthorRenderArtifactWriter(output_dir)
    paths = writer.allocate(timestamp=timestamp, preparation_collision_index=preparation_collision_index)
    try:
        profile = load_template_profile(template_profile or _text(settings.get("template_profile")) or "markers_v1", main_tex=template_main or _text(settings.get("main_tex")) or None)
    except TemplateProfileError as error:
        raise AuthorRenderingError("template", str(error), paths=paths) from error
    try:
        if logger is not None:
            logger.emit("tex_render", "started", status="RUNNING", profile_id=profile.profile_id)
        tex = render_tex_project(
            document,
            template_dir=template_dir,
            project_dir=paths.project_dir,
            profile=profile,
            author_name=author_name,
        )
        writer.publish_sources(tex, paths)
        if logger is not None:
            logger.emit(
                "tex_render",
                "completed",
                status="COMPLETED",
                profile_id=profile.profile_id,
                emitted_bibliography_count=len(tex.bibliography.emitted_keys),
                bibliography_needs_completion_count=len(tex.bibliography.needs_completion),
            )
    except (TexRenderError, RenderArtifactError) as error:
        if logger is not None:
            logger.emit("tex_render", "failed", level="ERROR", status="FAILED", error=str(error))
        raise AuthorRenderingError("tex_render", str(error), paths=paths) from error
    try:
        engine = resolve_executable(
            explicit=latex_engine,
            environment_variable="SCIENCE_LATEX_ENGINE",
            configured=settings.get("engine"),
            fallback="pdflatex",
            label="LaTeX engine",
        )
        bibtex_engine = None
        if tex.bibliography.emitted_keys:
            bibtex_engine = resolve_executable(
                explicit=bibtex,
                environment_variable="SCIENCE_BIBTEX",
                configured=settings.get("bibtex"),
                fallback="bibtex",
                label="BibTeX engine",
            )
    except LatexCompilerError as error:
        raise AuthorRenderingError("latex_compile", str(error), paths=paths) from error
    try:
        compile_result = compile_latex_project(
            tex.project_dir,
            main_tex=tex.main_tex,
            latex_engine=engine,
            bibtex=bibtex_engine,
            run_bibtex=bool(tex.bibliography.emitted_keys),
            timeout_seconds=max(1, int(compile_timeout_seconds)),
            staged_pdf_path=paths.staged_pdf,
            logger=logger,
        )
    except LatexCompilerError as error:
        writer.discard_staged_pdf(paths)
        raise AuthorRenderingError("latex_compile", str(error), paths=paths) from error
    try:
        writer.publish_compile_diagnostics(paths, report=compile_result.report, log_text=compile_result.log_text)
    except RenderArtifactError as error:
        writer.discard_staged_pdf(paths)
        raise AuthorRenderingError("artifacts", str(error), paths=paths) from error
    if not compile_result.success:
        writer.discard_staged_pdf(paths)
        raise AuthorRenderingError(
            "latex_compile",
            "LaTeX compilation failed; retained compile log and structured diagnostics",
            paths=paths,
        )
    try:
        renderer = resolve_executable(
            explicit=pdf_renderer,
            environment_variable="SCIENCE_PDF_RENDERER",
            configured=settings.get("pdf_renderer"),
            fallback="pdftoppm",
            label="PDF renderer",
        )
        validation = validate_pdf(
            paths.staged_pdf,
            renderer=renderer,
            timeout_seconds=max(1, int(settings.get("pdf_validation_timeout_seconds") or 60)),
            logger=logger,
        )
        writer.publish_pdf_validation(paths, validation.report)
    except (PdfValidationError, LatexCompilerError, RenderArtifactError) as error:
        if isinstance(error, PdfValidationError) and error.report is not None:
            try:
                writer.publish_pdf_validation(paths, error.report)
            except RenderArtifactError:
                pass
        writer.discard_staged_pdf(paths)
        raise AuthorRenderingError("pdf_validation", str(error), paths=paths) from error
    try:
        writer.publish_validated_pdf(paths)
    except RenderArtifactError as error:
        raise AuthorRenderingError("artifacts", str(error), paths=paths) from error
    return AuthorRenderingResult(artifacts=paths, tex=tex, pdf_validation=validation)


__all__ = ["AuthorRenderingError", "AuthorRenderingResult", "render_research_plan_document"]
