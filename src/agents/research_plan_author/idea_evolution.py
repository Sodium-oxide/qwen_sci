"""Project a bounded, source-anchored Idea evolution appendix without invention."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping

from src.agents.experiment_design_agent.idea_intake import load_idea_artifact_bundle


IDEA_EVOLUTION_APPENDIX_SCHEMA_VERSION = "idea_evolution_appendix_v1"


class IdeaEvolutionError(ValueError):
    """Raised when the requested Idea history conflicts with the selected direction."""


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _text(value: object) -> str:
    return str(value or "").strip()


def _identifier_candidates(direction: Mapping[str, Any]) -> set[str]:
    values = (
        direction.get("id"),
        direction.get("direction_id"),
        direction.get("direction_mode"),
        direction.get("title"),
    )
    return {_text(value) for value in values if _text(value)}


def _selected_direction(idea_result: Mapping[str, Any], selected_direction_id: str) -> tuple[dict[str, Any], str]:
    directions = idea_result.get("directions")
    candidates = directions if isinstance(directions, list) else []
    for index, raw_direction in enumerate(candidates):
        direction = _mapping(raw_direction)
        if selected_direction_id in _identifier_candidates(direction):
            return direction, f"/directions/{index}"
    primary_direction = _text(idea_result.get("primary_direction"))
    if selected_direction_id == primary_direction:
        for index, raw_direction in enumerate(candidates):
            direction = _mapping(raw_direction)
            if primary_direction in _identifier_candidates(direction):
                return direction, f"/directions/{index}"
    raise IdeaEvolutionError(
        f"selected direction mismatch: '{selected_direction_id}' is not present in idea_result.json directions"
    )


def _snapshot(record: Mapping[str, Any]) -> dict[str, Any]:
    allowed_fields = (
        "id",
        "direction_id",
        "direction_mode",
        "title",
        "research_question",
        "central_hypothesis",
        "hypothesis",
        "mechanism_or_relation",
        "contribution",
        "contributions",
        "claim_scope",
        "boundary_conditions",
        "alternative_explanations",
        "falsifiers",
        "known_unknowns",
        "target_gap_ids",
    )
    return {
        field: deepcopy(record[field])
        for field in allowed_fields
        if field in record and record[field] not in (None, "", [], {})
    }


def _append_checkpoint(
    checkpoints: list[dict[str, Any]],
    *,
    source_file: str,
    source_path: str,
    source_json_pointer: str,
    record: Mapping[str, Any],
) -> None:
    snapshot = _snapshot(record)
    if not snapshot:
        return
    if any(item["snapshot"] == snapshot for item in checkpoints):
        return
    checkpoints.append(
        {
            "checkpoint_id": f"checkpoint-{len(checkpoints) + 1}",
            "checkpoint_type": "available_audit_snapshot",
            "temporal_order": "unknown",
            "source_file": source_file,
            "source_path": source_path,
            "source_json_pointer": source_json_pointer,
            "snapshot": snapshot,
        }
    )


def project_idea_evolution(
    idea_result_path: str | Path,
    *,
    selected_direction_id: str,
    max_iterations: int = 3,
) -> dict[str, Any]:
    """Project available Idea audit snapshots without inventing an iteration history.

    The common Idea artifacts are parallel audit outputs from one run.  Their
    filenames do not establish chronology or parentage, so they remain neutral
    source checkpoints unless a future producer supplies auditable evolution
    metadata.
    """

    if max_iterations not in {2, 3}:
        raise ValueError("max_iterations must be either 2 or 3")
    expected_direction_id = _text(selected_direction_id)
    if not expected_direction_id:
        raise IdeaEvolutionError("selected_direction_id is required for Idea evolution projection")
    try:
        bundle = load_idea_artifact_bundle(idea_result_path)
    except (FileNotFoundError, ValueError) as error:
        raise IdeaEvolutionError(str(error)) from error
    idea_result = _mapping(bundle.get("idea_result"))
    selected, selected_pointer = _selected_direction(idea_result, expected_direction_id)
    source_paths = _mapping(bundle.get("source_paths"))
    audit_sources = _mapping(bundle.get("audit_sources"))
    checkpoints: list[dict[str, Any]] = []
    candidate = _mapping(audit_sources.get("idea_candidate"))
    _append_checkpoint(
        checkpoints,
        source_file="idea_candidate.json",
        source_path=_text(source_paths.get("idea_candidate")),
        source_json_pointer="/",
        record=candidate,
    )
    portfolio = _mapping(audit_sources.get("idea_portfolio"))
    selected_primary_idea = _mapping(
        audit_sources.get("selected_primary_idea") or portfolio.get("selected_primary_idea")
    )
    _append_checkpoint(
        checkpoints,
        source_file="idea_portfolio.json",
        source_path=_text(source_paths.get("idea_portfolio")),
        source_json_pointer="/selected_primary_idea",
        record=selected_primary_idea,
    )
    _append_checkpoint(
        checkpoints,
        source_file="idea_result.json",
        source_path=_text(source_paths.get("idea_result")),
        source_json_pointer=selected_pointer,
        record=selected,
    )
    if len(checkpoints) > max_iterations:
        checkpoints = [checkpoints[0], checkpoints[-1]] if max_iterations == 2 else checkpoints[-max_iterations:]
        for index, checkpoint in enumerate(checkpoints, start=1):
            checkpoint["checkpoint_id"] = f"checkpoint-{index}"
    return {
        "schema_version": IDEA_EVOLUTION_APPENDIX_SCHEMA_VERSION,
        "status": "CHECKPOINTS_AVAILABLE" if len(checkpoints) >= 2 else "INSUFFICIENT_HISTORY",
        "selected_direction_id": expected_direction_id,
        "max_iterations": max_iterations,
        "temporal_order": "unknown",
        "checkpoints": checkpoints,
        "iterations": [],
        "missing_audit_sources": list(bundle.get("missing_sources") or []),
        "authoring_constraints": {
            "language": "en",
            "do_not_invent_missing_iterations": True,
            "do_not_describe_checkpoints_as_temporal_iterations": True,
            "temporal_order_is_unknown_without_iteration_id_timestamp_parent_or_auditable_diff": True,
            "do_not_present_idea_history_as_empirical_evidence": True,
            "all_displayed_checkpoints_require_source_anchors": True,
        },
    }


def disabled_idea_evolution() -> dict[str, Any]:
    """Represent an explicit CLI opt-out without pretending history was unavailable."""

    return {
        "schema_version": IDEA_EVOLUTION_APPENDIX_SCHEMA_VERSION,
        "status": "DISABLED",
        "selected_direction_id": "",
        "max_iterations": 0,
        "temporal_order": "not_applicable",
        "checkpoints": [],
        "iterations": [],
        "missing_audit_sources": [],
        "authoring_constraints": {
            "language": "en",
            "do_not_invent_missing_iterations": True,
            "do_not_describe_checkpoints_as_temporal_iterations": True,
            "temporal_order_is_unknown_without_iteration_id_timestamp_parent_or_auditable_diff": True,
            "do_not_present_idea_history_as_empirical_evidence": True,
            "all_displayed_checkpoints_require_source_anchors": True,
        },
    }


def unavailable_idea_evolution(reason: str) -> dict[str, Any]:
    """Expose missing optional history explicitly rather than fabricating an appendix."""

    payload = disabled_idea_evolution()
    payload["status"] = "UNAVAILABLE"
    payload["unavailable_reason"] = _text(reason)
    return payload


__all__ = [
    "IDEA_EVOLUTION_APPENDIX_SCHEMA_VERSION",
    "IdeaEvolutionError",
    "disabled_idea_evolution",
    "project_idea_evolution",
    "unavailable_idea_evolution",
]
