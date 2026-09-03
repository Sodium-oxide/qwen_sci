"""Validate the required human-readable profile for mathematical-model drafts."""

from __future__ import annotations

import re


class QuantitativeMarkdownProfileError(ValueError):
    """Raised when the LLM Markdown companion omits required review material."""


_REQUIRED_PATTERNS = {
    "abstract": re.compile(r"\A\s*Abstract—", re.IGNORECASE),
    "assumptions": re.compile(r"\bassumptions?\b", re.IGNORECASE),
    "symbols": re.compile(r"\b(symbols?|notation)\b", re.IGNORECASE),
    "where": re.compile(r"\bwhere\b", re.IGNORECASE),
    "algorithm": re.compile(r"\balgorithm\b", re.IGNORECASE),
    "algorithm_input": re.compile(r"\binput\b", re.IGNORECASE),
    "algorithm_output": re.compile(r"\boutput\b", re.IGNORECASE),
    "algorithm_steps": re.compile(r"\bsteps?\b", re.IGNORECASE),
    "parameter": re.compile(r"\bparameters?\b", re.IGNORECASE),
    "scenario": re.compile(r"\bscenarios?\b", re.IGNORECASE),
    "validation": re.compile(r"\b(numerical\s+)?validation\b", re.IGNORECASE),
    "limitations": re.compile(r"\blimitations?\b", re.IGNORECASE),
    "references": re.compile(r"\breferences?\b", re.IGNORECASE),
}


def validate_quantitative_markdown_profile(markdown: object, *, equation_ids: list[str]) -> str:
    """Check format evidence only; numerical facts remain governed by JSON artifacts."""

    text = str(markdown or "").strip()
    if not text:
        raise QuantitativeMarkdownProfileError("quantitative model Markdown is empty")
    missing = [name for name, pattern in _REQUIRED_PATTERNS.items() if pattern.search(text) is None]
    if missing:
        raise QuantitativeMarkdownProfileError(
            "quantitative model Markdown is missing required sections: " + ", ".join(missing)
        )
    missing_equations = [equation_id for equation_id in equation_ids if equation_id not in text]
    if missing_equations:
        raise QuantitativeMarkdownProfileError(
            "quantitative model Markdown omits equation IDs: " + ", ".join(missing_equations)
        )
    return text


__all__ = ["QuantitativeMarkdownProfileError", "validate_quantitative_markdown_profile"]
