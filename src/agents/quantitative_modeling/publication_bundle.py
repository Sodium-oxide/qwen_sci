"""Bind the two formal PDFs and their controlled quantitative evidence boundary."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.agents.research_plan_author.quantitative_evidence_adapter import (
    QuantitativeEvidenceLoadError,
    load_quantitative_evidence_capsule,
)
from src.pipeline.science_run import atomic_write_json, file_sha256, utc_now


PUBLICATION_BUNDLE_SCHEMA_VERSION = "publication_bundle_v1"


class PublicationBundleError(ValueError):
    """Raised when the main and supplementary PDFs cannot be safely paired."""


def _record(path: Path) -> dict[str, str]:
    if not path.is_file() or path.stat().st_size == 0:
        raise PublicationBundleError(f"published artifact is missing or empty: {path}")
    return {"path": str(path), "sha256": file_sha256(path)}


def build_publication_bundle(
    *,
    run_dir: str | Path,
    main_article_pdf: str | Path,
    quantitative_author_handoff_manifest: str | Path,
) -> Path:
    """Publish one manifest for exactly two formal PDFs, without merging them."""

    root = Path(run_dir).expanduser().resolve()
    try:
        from src.pipeline.quantitative_workflow import (
            QuantitativeWorkflowError,
            require_experiment_design_completed,
        )

        require_experiment_design_completed(root)
    except QuantitativeWorkflowError as exc:
        raise PublicationBundleError(str(exc)) from exc
    main_pdf = Path(main_article_pdf).expanduser().resolve()
    handoff_manifest = Path(quantitative_author_handoff_manifest).expanduser().resolve()
    quantitative_pdf = root / "quantitative" / "publication" / "quantitative_mathematical_models.pdf"
    for label, path in (("main article PDF", main_pdf), ("quantitative Author handoff", handoff_manifest), ("quantitative PDF", quantitative_pdf)):
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise PublicationBundleError(f"{label} must remain within this science run") from exc
    try:
        load_quantitative_evidence_capsule(handoff_manifest, expected_identity={})
    except QuantitativeEvidenceLoadError as exc:
        raise PublicationBundleError(f"quantitative Author handoff is invalid: {exc}") from exc
    manifest_path = root / "quantitative" / "publication" / "publication_bundle_manifest.json"
    if manifest_path.exists():
        raise PublicationBundleError("publication bundle manifest already exists")
    payload: dict[str, Any] = {
        "schema_version": PUBLICATION_BUNDLE_SCHEMA_VERSION,
        "status": "COMPLETED",
        "generated_at": utc_now(),
        "main_article_pdf": _record(main_pdf),
        "quantitative_models_pdf": _record(quantitative_pdf),
        "quantitative_author_handoff_manifest": _record(handoff_manifest),
        "formal_pdf_count": 2,
        "evidence_boundary": "NUMERICAL_SIMULATION / SIMULATED / NOT_EMPIRICAL",
    }
    atomic_write_json(manifest_path, payload)
    return manifest_path


__all__ = ["PUBLICATION_BUNDLE_SCHEMA_VERSION", "PublicationBundleError", "build_publication_bundle"]
