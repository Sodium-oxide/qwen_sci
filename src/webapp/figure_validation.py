"""Audit exported plot files independently of the plotting worker."""

from __future__ import annotations

from pathlib import Path

from src.result_figures.contracts import FigureError
from src.result_figures.validation import audit_outputs as shared_audit_outputs, audit_pdf as shared_audit_pdf

from .feature_service_base import FeatureJobError


def audit_outputs(directory: Path, formats: set[str], *, max_bytes: int) -> dict[str, object]:
    try:
        return shared_audit_outputs(directory, formats & {"png", "pdf", "svg"}, max_bytes=max_bytes)
    except FigureError as error:
        raise FeatureJobError(str(error)) from error


def audit_pdf(path: Path) -> dict[str, object]:
    return shared_audit_pdf(path)
