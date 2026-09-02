"""Publish the separate mathematical-model PDF from final audited artifacts."""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from src.agents.quantitative_modeling.author_handoff import (
    expected_quantitative_idea_ids,
    load_finalized_quantitative_record,
)
from src.agents.quantitative_modeling.publisher.tex_renderer import render_quantitative_models_tex
from src.agents.research_plan_author.latex_compiler import (
    LatexCompilerError,
    compile_latex_project,
    resolve_executable,
)
from src.agents.research_plan_author.pdf_validator import PdfValidationError, validate_pdf
from src.pipeline.quantitative_workflow import QuantitativeWorkflowError, require_experiment_design_completed
from src.pipeline.science_run import atomic_write_json, atomic_write_text, utc_now


QUANTITATIVE_PDF_RENDER_MANIFEST_SCHEMA_VERSION = "quantitative_pdf_render_manifest_v1"


class QuantitativePublicationError(RuntimeError):
    """Raised when a standalone supplement cannot be safely rendered and validated."""


def _finalized_records(run_dir: Path) -> list[dict[str, Any]]:
    expected_ids = expected_quantitative_idea_ids(root=run_dir)
    records: list[dict[str, Any]] = []
    missing_finalizations = [
        quantitative_idea_id
        for quantitative_idea_id in expected_ids
        if not (run_dir / "quantitative" / quantitative_idea_id / "finalization.json").is_file()
    ]
    if missing_finalizations:
        raise QuantitativePublicationError(
            "all quantitative ideas must be finalized before publication; missing: "
            + ", ".join(missing_finalizations)
        )
    for quantitative_idea_id in expected_ids:
        finalization_path = run_dir / "quantitative" / quantitative_idea_id / "finalization.json"
        if not finalization_path.is_file():
            continue
        try:
            finalized = load_finalized_quantitative_record(root=run_dir, finalization_path=finalization_path)
        except RuntimeError as exc:
            raise QuantitativePublicationError(str(exc)) from exc
        specification = finalized["model_spec"]
        qualified = finalized["qualified_entries"]
        lineage = [
            f"v{entry['version']}: {entry['relation']} ({entry['reason']})"
            for entry in finalized["lineage_summary"]
        ]
        records.append(
            {
                "model_spec": specification,
                "qualified_entries": qualified,
                "lineage_summary": lineage,
                "finalization_path": str(finalization_path),
            }
        )
    if not records:
        raise QuantitativePublicationError("no finalized Q1/Q2 model is available for the supplementary PDF")
    return records


def _validate_quantitative_pdf_structure(pdf_path: Path, *, renderer: Path) -> dict[str, Any]:
    validation = validate_pdf(pdf_path, renderer=renderer, minimum_pages=1)
    try:
        from pypdf import PdfReader

        reader = PdfReader(str(pdf_path))
        visible_text = "\n".join(page.extract_text() or "" for page in reader.pages)
    except Exception as exc:
        raise QuantitativePublicationError(f"Cannot extract published quantitative PDF text: {exc}") from exc
    required = (
        "Abstract",
        "Assumptions",
        "Symbols",
        "Algorithm",
        "Parameters",
        "Scenarios",
        "Numerical Validation",
        "NOT_EMPIRICAL",
    )
    missing = [value for value in required if value not in visible_text]
    if missing:
        raise QuantitativePublicationError(
            "quantitative PDF is missing required visible material: " + ", ".join(missing)
        )
    if "Acknowledg" in visible_text:
        raise QuantitativePublicationError("quantitative PDF must not contain an acknowledgements section")
    return {**validation.report, "quantitative_structure": {"missing": [], "acknowledgements_absent": True}}


def publish_quantitative_models_pdf(
    *,
    run_dir: str | Path,
    latex_engine: str | Path | None = None,
    pdf_renderer: str | Path | None = None,
    timeout_seconds: int = 180,
) -> dict[str, str]:
    """Render exactly one formal supplementary PDF for all finalized Q ideas."""

    root = Path(run_dir).expanduser().resolve()
    publication_dir = root / "quantitative" / "publication"
    pdf_path = publication_dir / "quantitative_mathematical_models.pdf"
    project_dir = publication_dir / "quantitative_models_project"
    tex_path = project_dir / "quantitative_models.tex"
    staged_pdf = publication_dir / ".quantitative_mathematical_models.pdf.staging"
    manifest_path = publication_dir / "quantitative_pdf_render_manifest.json"
    validation_path = publication_dir / "quantitative_pdf_validation.json"
    compile_path = publication_dir / "quantitative_pdf_compile.json"
    compile_log_path = publication_dir / "quantitative_pdf_compile.log"
    if any(path.exists() for path in (pdf_path, project_dir, staged_pdf, manifest_path, validation_path, compile_path, compile_log_path)):
        raise QuantitativePublicationError("quantitative publication artifacts already exist")
    try:
        require_experiment_design_completed(root)
    except QuantitativeWorkflowError as exc:
        raise QuantitativePublicationError(str(exc)) from exc
    records = _finalized_records(root)
    tex = render_quantitative_models_tex(records)
    publication_dir.mkdir(parents=True, exist_ok=False)
    project_dir.mkdir()
    atomic_write_text(tex_path, tex)
    try:
        engine = resolve_executable(
            explicit=latex_engine,
            environment_variable="SCIENCE_LATEX_ENGINE",
            configured=None,
            fallback="pdflatex",
            label="LaTeX engine",
        )
        renderer = resolve_executable(
            explicit=pdf_renderer,
            environment_variable="SCIENCE_PDF_RENDERER",
            configured=None,
            fallback="pdftoppm",
            label="PDF renderer",
        )
        compile_result = compile_latex_project(
            project_dir,
            main_tex=tex_path,
            latex_engine=engine,
            bibtex=None,
            run_bibtex=False,
            timeout_seconds=max(1, int(timeout_seconds)),
            staged_pdf_path=staged_pdf,
        )
    except LatexCompilerError as exc:
        raise QuantitativePublicationError(str(exc)) from exc
    atomic_write_json(compile_path, compile_result.report)
    atomic_write_text(compile_log_path, compile_result.log_text)
    if not compile_result.success or compile_result.staged_pdf is None:
        raise QuantitativePublicationError("quantitative LaTeX compilation failed; retained diagnostics")
    try:
        validation = _validate_quantitative_pdf_structure(staged_pdf, renderer=renderer)
    except (PdfValidationError, QuantitativePublicationError) as exc:
        staged_pdf.unlink(missing_ok=True)
        report = getattr(exc, "report", None)
        if isinstance(report, Mapping):
            atomic_write_json(validation_path, dict(report))
        raise QuantitativePublicationError(str(exc)) from exc
    atomic_write_json(validation_path, validation)
    os.replace(staged_pdf, pdf_path)
    manifest = {
        "schema_version": QUANTITATIVE_PDF_RENDER_MANIFEST_SCHEMA_VERSION,
        "status": "COMPLETED",
        "generated_at": utc_now(),
        "pdf": str(pdf_path),
        "tex": str(tex_path),
        "included_versions": [
            {
                "quantitative_idea_id": record["model_spec"]["lineage"]["quantitative_idea_id"],
                "version": record["model_spec"]["lineage"]["version"],
            }
            for record in records
        ],
        "execution_boundary": "NUMERICAL_SIMULATION / SIMULATED / NOT_EMPIRICAL",
    }
    atomic_write_json(manifest_path, manifest)
    return {
        "pdf": str(pdf_path),
        "tex": str(tex_path),
        "render_manifest": str(manifest_path),
        "validation": str(validation_path),
    }


__all__ = [
    "QUANTITATIVE_PDF_RENDER_MANIFEST_SCHEMA_VERSION",
    "QuantitativePublicationError",
    "publish_quantitative_models_pdf",
]
