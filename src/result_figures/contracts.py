"""Small, versioned contracts for reproducible result figures."""

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path


RENDERER_VERSION = "result-figures-v1"
DEFAULT_SETTINGS = {
    "enabled": True, "qualified_only": True, "formats": ["png", "pdf"],
    "max_figures_per_execution": 6, "timeout_seconds_per_figure": 30,
    "max_total_seconds_per_execution": 120, "max_output_bytes": 52_428_800,
    "failure_policy": "continue_with_warning",
}


class FigureError(ValueError):
    """Figure creation or provenance verification failed."""


@dataclass
class FigureSource:
    root: Path
    identity: dict
    quality: str
    result_kind: str
    source_refs: list
    traces: list = field(default_factory=list)
    fields: list = field(default_factory=list)
    metrics: list = field(default_factory=list)
    samples: list = field(default_factory=list)
    convergence: list = field(default_factory=list)
    notes: list = field(default_factory=list)
    error: str = ""


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
        separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def settings_for_run(root: Path, overrides=None) -> dict:
    from omegaconf import OmegaConf

    path = root / "config.resolved.yaml"
    config = OmegaConf.load(path) if path.is_file() else {}
    settings = {**DEFAULT_SETTINGS, **dict(config.get("result_figures", {})), **(overrides or {})}
    formats = list(settings["formats"])
    if not formats or len(formats) != len(set(formats)) or not set(formats) <= {"png", "pdf", "svg"}:
        raise FigureError("unsupported_result_figure_formats")
    for key in ("max_figures_per_execution", "timeout_seconds_per_figure", "max_total_seconds_per_execution", "max_output_bytes"):
        if isinstance(settings[key], bool) or not 0 < float(settings[key]) < float("inf"):
            raise FigureError("invalid_result_figure_setting:" + key)
    if settings["failure_policy"] != "continue_with_warning":
        raise FigureError("unsupported_result_figure_failure_policy")
    return settings
