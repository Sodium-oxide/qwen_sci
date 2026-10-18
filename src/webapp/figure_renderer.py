"""Bounded execution of server-owned plotting templates."""

from __future__ import annotations

from pathlib import Path

from src.result_figures.contracts import FigureError
from src.result_figures.runtime import execution_prelude as shared_execution_prelude, run_template

from .feature_service_base import FeatureJobError


def execution_prelude(*, cpu_seconds: int, memory_bytes: int, output_bytes: int) -> str:
    return shared_execution_prelude(cpu_seconds=cpu_seconds, memory_bytes=memory_bytes, output_bytes=output_bytes)


def run_figure_template(context, directory: Path, *, timeout: float) -> None:
    def cancelled():
        context.check_cancelled()
        return False

    try:
        run_template(directory, timeout=context.remaining_seconds(timeout), cancel_check=cancelled)
    except FigureError as error:
        raise FeatureJobError(str(error)) from error
