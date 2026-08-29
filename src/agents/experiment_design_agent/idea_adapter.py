"""Adapter from Idea Agent artifacts to the ExperimentDesign intake contract."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from .contracts import build_research_brief_from_idea_result
from .idea_intake import load_idea_artifact_bundle


class IdeaResultAdapter:
    """Build a validated ResearchBrief without adding experimental details."""

    def adapt(
        self,
        idea_result: Mapping[str, Any],
        *,
        discipline_ids: object,
        brief_id: str,
        selected_direction: str = "",
        audit_sources: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        return build_research_brief_from_idea_result(
            idea_result,
            discipline_ids=discipline_ids,
            brief_id=brief_id,
            selected_direction=selected_direction,
            audit_sources=audit_sources,
        )

    def adapt_path(
        self,
        idea_result_path: str | Path,
        *,
        discipline_ids: object,
        brief_id: str | None = None,
        selected_direction: str = "",
    ) -> dict[str, Any]:
        """Adapt ``idea_result.json`` and same-run audit files as one intake."""

        bundle = load_idea_artifact_bundle(idea_result_path)
        resolved_brief_id = str(brief_id or Path(bundle["run_dir"]).name).strip()
        if not resolved_brief_id:
            raise ValueError("A non-empty brief_id is required for Idea artifact intake.")
        brief = self.adapt(
            bundle["idea_result"],
            discipline_ids=discipline_ids,
            brief_id=resolved_brief_id,
            selected_direction=selected_direction,
            audit_sources=bundle["audit_sources"],
        )
        source = dict(brief.get("source") or {})
        source["upstream_source_paths"] = dict(bundle["source_paths"])
        source["missing_audit_sources"] = list(bundle["missing_sources"])
        brief["source"] = source
        context = dict(brief.get("reasoning_context") or {})
        extracted_paths = list(context.get("upstream_source_paths") or [])
        for artifact_path in bundle["source_paths"].values():
            if artifact_path not in extracted_paths:
                extracted_paths.append(artifact_path)
        context["upstream_source_paths"] = extracted_paths
        brief["reasoning_context"] = context
        return brief


def adapt_idea_result(
    idea_result: Mapping[str, Any],
    *,
    discipline_ids: object,
    brief_id: str,
    selected_direction: str = "",
    audit_sources: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Adapt one selected ``idea_result_v5`` direction into ResearchBrief v1."""

    return IdeaResultAdapter().adapt(
        idea_result,
        discipline_ids=discipline_ids,
        brief_id=brief_id,
        selected_direction=selected_direction,
        audit_sources=audit_sources,
    )


def adapt_idea_result_path(
    idea_result_path: str | Path,
    *,
    discipline_ids: object,
    brief_id: str | None = None,
    selected_direction: str = "",
) -> dict[str, Any]:
    """Path-based adapter for the canonical Idea Agent run artifact."""

    return IdeaResultAdapter().adapt_path(
        idea_result_path,
        discipline_ids=discipline_ids,
        brief_id=brief_id,
        selected_direction=selected_direction,
    )
