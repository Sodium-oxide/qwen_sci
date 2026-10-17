"""Shared research boundaries for CLI workflows and web actions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True, slots=True)
class ResearchProfile:
    research_depth: str
    workflow_profile: str
    prompt_profile: str
    stages: tuple[str, ...]
    quantitative_allowed: bool

    def validate_stage(self, stage: str) -> None:
        if stage not in self.stages:
            raise ValueError(f"{self.research_depth.capitalize()} research can only run through {', '.join(self.stages)}.")


RESEARCH_PROFILES = {
    "full": ResearchProfile("full", "full_research", "research-default", ("survey", "idea", "exp_design", "author"), True),
    "light": ResearchProfile("light", "light_research", "research-light", ("survey", "idea"), False),
}


def resolve_research_profile(
    depth: str = "full", *, workflow: str | None = None, prompt: str | None = None,
    quantitative_mode: str = "off", computation_mode: str = "off",
) -> ResearchProfile:
    try:
        profile = RESEARCH_PROFILES[depth]
    except KeyError as exc:
        raise ValueError("research_depth must be light or full") from exc
    if workflow is not None and workflow != profile.workflow_profile:
        raise ValueError(f"{depth.capitalize()} research requires workflow_profile={profile.workflow_profile}")
    if prompt is not None and prompt != profile.prompt_profile:
        raise ValueError(f"{depth.capitalize()} research requires prompt_profile={profile.prompt_profile}")
    if not profile.quantitative_allowed and (quantitative_mode != "off" or computation_mode != "off"):
        raise ValueError("Light research requires quantitative_mode=off and computation_mode=off")
    return profile


def profile_from_options(options: Mapping[str, object]) -> ResearchProfile:
    research = options.get("research", {})
    research = research if isinstance(research, Mapping) else {}
    quantitative = options.get("quantitative", {})
    computation = options.get("computation", {})
    return resolve_research_profile(
        str(research.get("research_depth") or "full"),
        workflow=research.get("workflow_profile"), prompt=research.get("prompt_profile"),
        quantitative_mode=str(quantitative.get("mode", "off")) if isinstance(quantitative, Mapping) else "off",
        computation_mode=str(computation.get("mode", "off")) if isinstance(computation, Mapping) else "off",
    )
