"""Structural and first-page render validation for generated Author PDFs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import subprocess
import tempfile
from time import perf_counter
from typing import Any


PDF_VALIDATION_SCHEMA_VERSION = "research_plan_author_pdf_validation_v1"


class PdfValidationError(RuntimeError):
    """Raised when a generated PDF cannot be parsed or rendered safely."""

    def __init__(self, message: str, *, report: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.report = dict(report) if isinstance(report, dict) else None


@dataclass(frozen=True)
class PdfValidationResult:
    valid: bool
    report: dict[str, Any]


def validate_pdf(
    pdf_path: str | Path,
    *,
    renderer: str | Path,
    minimum_pages: int = 1,
    timeout_seconds: int = 60,
    logger: Any | None = None,
) -> PdfValidationResult:
    """Require a parseable PDF with a renderable first page and page minimum."""

    source = Path(pdf_path).expanduser().resolve()
    renderer_path = Path(renderer).expanduser().resolve()
    if isinstance(minimum_pages, bool) or not isinstance(minimum_pages, int) or minimum_pages < 1:
        raise PdfValidationError("minimum_pages must be a positive integer")
    if not source.is_file() or source.stat().st_size == 0:
        raise PdfValidationError(f"generated PDF does not exist or is empty: {source}")
    if not renderer_path.is_file():
        raise PdfValidationError(f"PDF renderer is not an executable file: {renderer_path}")
    parser_report: dict[str, Any] = {}
    try:
        from pypdf import PdfReader

        reader = PdfReader(str(source))
        page_count = len(reader.pages)
        if page_count < 1:
            raise PdfValidationError("generated PDF has no pages")
        first_page = reader.pages[0]
        box = first_page.mediabox
        width = float(box.width)
        height = float(box.height)
        if width <= 0 or height <= 0:
            raise PdfValidationError("generated PDF has invalid first-page dimensions")
        extracted = ""
        for page in reader.pages[: min(page_count, 3)]:
            try:
                extracted += page.extract_text() or ""
            except Exception:
                continue
        parser_report = {
            "backend": "pypdf",
            "status": "parsed",
            "page_count": page_count,
            "minimum_page_count": minimum_pages,
            "page_count_requirement_met": page_count >= minimum_pages,
            "first_page_width": width,
            "first_page_height": height,
            "extractable_text": bool(extracted.strip()),
            "warning": "non_text_pdf" if not extracted.strip() else "",
        }
    except PdfValidationError:
        raise
    except Exception as error:
        raise PdfValidationError(
            f"pypdf could not parse generated PDF: {type(error).__name__}: {error}",
            report={
                "schema_version": PDF_VALIDATION_SCHEMA_VERSION,
                "generated_at": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
                "valid": False,
                "pdf_path": str(source),
                "file_size_bytes": source.stat().st_size,
                "parser": {"backend": "pypdf", "status": "parse_failed", "error": type(error).__name__},
                "renderer": {"backend": "pdftoppm", "status": "not_started"},
            },
        ) from error
    if page_count < minimum_pages:
        raise PdfValidationError(
            f"generated PDF has {page_count} pages; minimum is {minimum_pages}",
            report={
                "schema_version": PDF_VALIDATION_SCHEMA_VERSION,
                "generated_at": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
                "valid": False,
                "pdf_path": str(source),
                "file_size_bytes": source.stat().st_size,
                "parser": parser_report,
                "renderer": {"backend": "pdftoppm", "status": "not_started"},
            },
        )
    with tempfile.TemporaryDirectory(prefix="research-plan-author-pdf-") as temporary_root:
        prefix = Path(temporary_root) / "page"
        command = [str(renderer_path), "-f", "1", "-l", "1", "-png", str(source), str(prefix)]
        started_at = perf_counter()
        if logger is not None:
            logger.emit("pdf_validation", "render_started", status="RUNNING", renderer=str(renderer_path))
        try:
            completed = subprocess.run(
                command,
                shell=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=max(1, int(timeout_seconds)),
                check=False,
            )
        except subprocess.TimeoutExpired as error:
            raise PdfValidationError(f"PDF first-page renderer timed out after {timeout_seconds} seconds") from error
        except OSError as error:
            raise PdfValidationError(f"PDF first-page renderer could not start: {error}") from error
        images = sorted(Path(temporary_root).glob("page-*.png"))
        render_success = completed.returncode == 0 and bool(images) and images[0].stat().st_size > 0
        render_report = {
            "backend": "pdftoppm",
            "status": "rendered" if render_success else "render_failed",
            "command": [str(value) for value in command],
            "return_code": completed.returncode,
            "elapsed_ms": round((perf_counter() - started_at) * 1000, 3),
            "rendered_first_page_bytes": images[0].stat().st_size if images else 0,
            "stderr_tail": (completed.stderr or "")[-2000:],
        }
        if logger is not None:
            logger.emit(
                "pdf_validation",
                "render_completed" if render_success else "render_failed",
                level="INFO" if render_success else "ERROR",
                status="COMPLETED" if render_success else "FAILED",
                return_code=completed.returncode,
                elapsed_ms=render_report["elapsed_ms"],
            )
        report = {
            "schema_version": PDF_VALIDATION_SCHEMA_VERSION,
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "valid": render_success,
            "pdf_path": str(source),
            "file_size_bytes": source.stat().st_size,
            "parser": parser_report,
            "renderer": render_report,
        }
        if not render_success:
            raise PdfValidationError(
                "PDF first-page render validation failed: "
                + (completed.stderr or completed.stdout or "renderer produced no PNG")[-1000:],
                report=report,
            )
    return PdfValidationResult(valid=True, report=report)


__all__ = ["PDF_VALIDATION_SCHEMA_VERSION", "PdfValidationError", "PdfValidationResult", "validate_pdf"]
