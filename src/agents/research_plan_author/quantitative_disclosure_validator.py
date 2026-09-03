"""Validate that rendered Author evidence stays explicitly numerical and non-empirical."""

from __future__ import annotations

from collections.abc import Mapping
from .latex_safety import contains_observed_result_language


def validate_quantitative_disclosure(document: Mapping[str, object]) -> list[str]:
    sections = [
        section
        for section in document.get("sections") or []
        if isinstance(section, Mapping) and section.get("section_id") == "computational_evidence"
    ]
    if len(sections) != 1:
        return ["quantitative Author evidence requires exactly one computational_evidence section"]
    errors: list[str] = []
    for block in sections[0].get("blocks") or []:
        if not isinstance(block, Mapping):
            errors.append("quantitative Author evidence has an invalid block")
            continue
        text = str(block.get("text") or "")
        for label in ("NUMERICAL_SIMULATION", "SIMULATED", "NOT_EMPIRICAL"):
            if label not in text:
                errors.append(f"quantitative Author evidence omits {label}")
        if contains_observed_result_language(text):
            errors.append("quantitative Author evidence presents an observed result")
    return sorted(set(errors))


__all__ = ["validate_quantitative_disclosure"]
