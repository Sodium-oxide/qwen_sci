"""Build the bounded, traceable source bundle consumed by later Author stages."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from .contracts import AUTHORING_LANGUAGE, AUTHOR_SOURCE_BUNDLE_SCHEMA, AUTHOR_SOURCE_BUNDLE_SCHEMA_VERSION


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _text(value: object) -> str:
    return str(value or "").strip()


def build_author_source_bundle(
    author_input: Mapping[str, Any],
    *,
    author_input_path: str,
    author_input_identity: Mapping[str, Any],
    survey_sources: Mapping[str, Any],
    survey_binding: Mapping[str, Any],
    idea_evolution: Mapping[str, Any],
) -> dict[str, Any]:
    """Create a source-addressable bundle without parsing human-readable Markdown."""

    provenance = _mapping(author_input.get("provenance"))
    bundle = {
        "schema_version": AUTHOR_SOURCE_BUNDLE_SCHEMA_VERSION,
        "language": AUTHORING_LANGUAGE,
        "source_design_id": _text(author_input.get("source_design_id")),
        "selected_direction_id": _text(provenance.get("selected_direction_id")),
        "author_input_path": _text(author_input_path),
        "author_input_identity": deepcopy(dict(author_input_identity)),
        "author_context": deepcopy(dict(author_input)),
        "survey_sources": deepcopy(dict(survey_sources)),
        "survey_binding": deepcopy(dict(survey_binding)),
        "idea_evolution": deepcopy(dict(idea_evolution)),
    }
    return bundle


__all__ = ["AUTHOR_SOURCE_BUNDLE_SCHEMA", "build_author_source_bundle"]
