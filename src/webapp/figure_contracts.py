"""Declarative plotting contracts; model output cannot contain executable code."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Literal

from pydantic import Field

from .feature_contracts import Contract


class FigureStyle(Contract):
    x_label: str = Field(default="", max_length=200)
    y_label: str = Field(default="", max_length=200)
    title: str = Field(default="", max_length=200)
    width_mm: float = Field(default=180.0, ge=80, le=300)
    height_mm: float = Field(default=120.0, ge=60, le=250)
    palette: Literal["colorblind", "blue", "neutral"] = "colorblind"


class FigureSpec(FigureStyle):
    schema_version: Literal["figure_spec_v1"] = "figure_spec_v1"
    chart_type: Literal["line", "bar", "scatter", "hist", "box"]
    variable_mapping: dict[str, str]
    unresolved_items: list[str] = Field(default_factory=list, max_length=100)


def apply_figure_style(spec: FigureSpec, *styles: Mapping[str, object] | None) -> FigureSpec:
    """Apply only explicitly supplied style fields and revalidate the full spec."""

    candidate = spec.model_dump()
    for raw_style in styles:
        if raw_style is None:
            continue
        style = FigureStyle.model_validate(dict(raw_style))
        candidate.update(style.model_dump(exclude_unset=True))
    return FigureSpec.model_validate(candidate)
