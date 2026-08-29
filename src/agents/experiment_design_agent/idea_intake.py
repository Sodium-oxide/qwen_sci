"""Filesystem intake for one Idea Agent run and its audit artifacts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping


MAIN_ARTIFACT_NAME = "idea_result.json"
AUDIT_ARTIFACT_NAMES = (
    "idea_candidate.json",
    "idea_portfolio.json",
    "idea_directions.json",
    "idea_route_clusters.json",
    "mature_ideas.json",
)


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Cannot load Idea artifact '{path}': {exc}") from exc
    if not isinstance(value, Mapping):
        raise ValueError(f"Idea artifact '{path}' must contain one JSON object.")
    return dict(value)


def _resolve_main_path(path: str | Path) -> Path:
    candidate = Path(path).expanduser()
    if candidate.is_dir():
        candidate = candidate / MAIN_ARTIFACT_NAME
    return candidate.resolve()


def load_idea_artifact_bundle(path: str | Path) -> dict[str, Any]:
    """Load one canonical idea result plus optional same-run audit files.

    ``idea_result.json`` is always the authoritative input.  The returned
    ``audit_sources`` object is intentionally keyed by artifact role and is
    consumed only for missing-field enrichment and provenance.  In particular,
    ``idea_directions.json`` is never merged into the selected direction.
    """

    main_path = _resolve_main_path(path)
    if not main_path.exists():
        raise FileNotFoundError(f"Canonical Idea artifact not found: {main_path}")
    idea_result = _load_json(main_path)
    if idea_result.get("schema_version") != "idea_result_v5":
        raise ValueError("ExperimentDesign intake requires idea_result_v5 in idea_result.json.")

    run_dir = main_path.parent
    audit_sources: dict[str, Any] = {}
    source_paths: dict[str, str] = {"idea_result": str(main_path)}
    missing_sources: list[str] = []
    for filename in AUDIT_ARTIFACT_NAMES:
        artifact_path = run_dir / filename
        role = Path(filename).stem
        if not artifact_path.exists():
            missing_sources.append(filename)
            continue
        artifact = _load_json(artifact_path)
        audit_sources[role] = artifact
        source_paths[role] = str(artifact_path)

    portfolio = audit_sources.get("idea_portfolio")
    if isinstance(portfolio, Mapping):
        selected_primary_idea = portfolio.get("selected_primary_idea")
        if isinstance(selected_primary_idea, Mapping):
            audit_sources["selected_primary_idea"] = dict(selected_primary_idea)

    return {
        "idea_result": idea_result,
        "audit_sources": audit_sources,
        "source_paths": source_paths,
        "missing_sources": missing_sources,
        "canonical_path": str(main_path),
        "run_dir": str(run_dir),
    }


def load_idea_result_and_audit_sources(path: str | Path) -> tuple[dict[str, Any], dict[str, Any]]:
    """Convenience wrapper returning the canonical result and audit mapping."""

    bundle = load_idea_artifact_bundle(path)
    return dict(bundle["idea_result"]), dict(bundle["audit_sources"])
