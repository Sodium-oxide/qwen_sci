"""Lossless, precedence-aware reasoning context extracted from Idea artifacts."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from typing import Any


REASONING_CONTEXT_SCHEMA_VERSION = "reasoning_context_v1"


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _records(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return [dict(item) for item in value if isinstance(item, Mapping)]


def _texts(value: object) -> list[str]:
    values = value if isinstance(value, Sequence) and not isinstance(value, (str, bytes)) else [value]
    result: list[str] = []
    for item in values:
        text = str(item or "").strip()
        if text and text not in result:
            result.append(text)
    return result


def _first_value(sources: Sequence[tuple[str, Mapping[str, Any]]], keys: Sequence[str]) -> tuple[Any, str]:
    for source_name, source in sources:
        for key in keys:
            value = source.get(key)
            if value not in (None, "", [], {}):
                return deepcopy(value), f"{source_name}.{key}"
    return [], ""


def _source_layers(
    direction: Mapping[str, Any],
    idea_result: Mapping[str, Any],
    audit_sources: Mapping[str, Any] | None,
) -> list[tuple[str, Mapping[str, Any]]]:
    audit = _mapping(audit_sources)
    layers: list[tuple[str, Mapping[str, Any]]] = []

    def add_source(prefix: str, value: object) -> None:
        source = _mapping(value)
        for nested_key in ("hypothesis", "experiment_handoff"):
            nested = _mapping(source.get(nested_key))
            if nested:
                layers.append((f"{prefix}.{nested_key}", nested))
        layers.append((prefix, source))

    add_source("selected_direction", direction)
    add_source("legacy_best_entry", idea_result.get("legacy_best_entry"))
    add_source("selected_primary_idea", audit.get("selected_primary_idea"))
    add_source("idea_candidate", audit.get("idea_candidate"))
    return layers


def build_reasoning_context_from_idea_result(
    idea_result: Mapping[str, Any],
    *,
    selected_direction: str = "",
    audit_sources: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Extract reasoning inputs while retaining source precedence and JSON paths."""

    directions = [item for item in idea_result.get("directions") or [] if isinstance(item, Mapping)]
    requested = str(selected_direction or idea_result.get("primary_direction") or "").strip()
    matching = [
        direction
        for direction in directions
        if str(direction.get("direction_mode") or "").strip() == requested
        or str(direction.get("id") or "").strip() == requested
        or str(direction.get("title") or "").strip() == requested
    ]
    if len(matching) != 1:
        raise ValueError("ReasoningContext requires one unambiguous selected Idea Agent direction.")
    direction = matching[0]
    sources = _source_layers(direction, idea_result, audit_sources)
    source_paths: list[str] = []

    assumptions, path = _first_value(sources, ("assumptions",))
    if path:
        source_paths.append(path)
    claim_scope, path = _first_value(sources, ("claim_scope",))
    if path:
        source_paths.append(path)
    falsifiers, path = _first_value(sources, ("falsifiers", "falsifier", "falsifiers_or_failure_conditions"))
    if path:
        source_paths.append(path)
    boundaries, path = _first_value(sources, ("boundary_conditions", "boundary_or_failure_condition"))
    if path:
        source_paths.append(path)
    alternatives, path = _first_value(sources, ("alternative_explanations",))
    if path:
        source_paths.append(path)
    formal_symbols, path = _first_value(sources, ("formal_symbols", "symbols"))
    if path:
        source_paths.append(path)

    handoff = _mapping(direction.get("experiment_handoff"))
    legacy = _mapping(idea_result.get("legacy_best_entry"))
    audit = _mapping(audit_sources)
    gap_records = _records(handoff.get("gap_records")) or _records(legacy.get("gap_records"))
    evidence_roles = _records(handoff.get("evidence_roles")) or _records(legacy.get("evidence_roles"))
    source_anchors = _records(handoff.get("source_anchors")) or _records(legacy.get("source_anchors"))
    if not gap_records:
        gap_records = _records(audit.get("gap_records"))
    if not evidence_roles:
        evidence_roles = _records(audit.get("evidence_roles"))
    if not source_anchors:
        source_anchors = _records(audit.get("source_anchors"))

    direction_id = str(direction.get("direction_mode") or direction.get("id") or direction.get("title") or "").strip()
    return {
        "schema_version": REASONING_CONTEXT_SCHEMA_VERSION,
        "selected_direction_id": direction_id,
        "assumptions": _texts(assumptions),
        "claim_scope": str(claim_scope or "").strip(),
        "falsifiers": _texts(falsifiers),
        "boundary_conditions": _texts(boundaries),
        "alternative_explanations": _texts(alternatives),
        "formal_symbols": _texts(formal_symbols),
        "gap_records": gap_records,
        "evidence_roles": evidence_roles,
        "source_anchors": source_anchors,
        "upstream_source_paths": source_paths,
        "source_priority": [
            "selected_direction",
            "legacy_best_entry",
            "selected_primary_idea",
            "idea_candidate",
        ],
    }


def build_reasoning_context_from_brief(research_brief: Mapping[str, Any]) -> dict[str, Any]:
    """Return the single canonical context stored on ResearchBrief."""

    existing = _mapping(research_brief.get("reasoning_context"))
    if not existing:
        raise ValueError("ResearchBrief is missing canonical reasoning_context")
    return existing


REASONING_CONTEXT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema_version",
        "assumptions",
        "claim_scope",
        "falsifiers",
        "boundary_conditions",
        "alternative_explanations",
        "formal_symbols",
        "gap_records",
        "evidence_roles",
        "source_anchors",
        "upstream_source_paths",
    ],
    "properties": {
        "schema_version": {"const": REASONING_CONTEXT_SCHEMA_VERSION},
        "selected_direction_id": {"type": "string"},
        "assumptions": {"type": "array"},
        "claim_scope": {"type": "string"},
        "falsifiers": {"type": "array"},
        "boundary_conditions": {"type": "array"},
        "alternative_explanations": {"type": "array"},
        "formal_symbols": {"type": "array"},
        "gap_records": {"type": "array"},
        "evidence_roles": {"type": "array"},
        "source_anchors": {"type": "array"},
        "upstream_source_paths": {"type": "array"},
        "source_priority": {"type": "array"},
    },
}
