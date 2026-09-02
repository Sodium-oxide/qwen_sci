"""Keep the Markdown review copy subordinate to the audited JSON fact source."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from src.agents.quantitative_modeling.model_format import normalize_quantitative_model_spec
from src.agents.quantitative_modeling.publisher.markdown_profile import (
    validate_quantitative_markdown_profile,
)


class JsonMarkdownConsistencyError(ValueError):
    """Raised when a model draft's presentation cannot be tied to its JSON source."""


def validate_json_markdown_consistency(
    specification: Mapping[str, object], markdown: object
) -> dict[str, Any]:
    """Return the normalized publication inputs after traceable consistency checks."""

    normalized = normalize_quantitative_model_spec(specification)
    equation_ids = [str(item["equation_id"]) for item in normalized["equations"]]
    try:
        normalized_markdown = validate_quantitative_markdown_profile(
            markdown,
            equation_ids=equation_ids,
        )
    except ValueError as exc:
        raise JsonMarkdownConsistencyError(str(exc)) from exc
    missing_symbols = [
        str(symbol["symbol_id"])
        for symbol in normalized["symbols"]
        if str(symbol["symbol_id"]) not in normalized_markdown
    ]
    if missing_symbols:
        raise JsonMarkdownConsistencyError(
            "quantitative model Markdown omits symbol IDs: " + ", ".join(missing_symbols)
        )
    return {"model_spec": normalized, "markdown": normalized_markdown}


__all__ = ["JsonMarkdownConsistencyError", "validate_json_markdown_consistency"]
