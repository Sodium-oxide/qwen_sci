"""Project selected, verified upstream evidence into a computational context."""

from pathlib import Path

from src.agents.experiment_design_agent.idea_adapter import IdeaResultAdapter
from src.pipeline.science_manifests import verify_idea_manifest, verify_survey_manifest
from src.pipeline.science_run import file_sha256
from src.pipeline.survey_idea_loader import load_survey_idea_context

from .artifacts import read_json
from .contracts import require_contract


def build_context(*, science_run_id: str, idea_manifest_path: Path, survey_manifest_path: Path,
                  discipline_ids: tuple[str, ...], budget: dict, inputs: list | None = None,
                  constraints: dict | None = None) -> dict:
    survey = verify_survey_manifest(survey_manifest_path)
    idea = verify_idea_manifest(idea_manifest_path, expected_survey_identity=survey.identity)
    selected = idea.identity["selected_direction_id"]
    brief = IdeaResultAdapter().adapt_path(idea.canonical_path, discipline_ids=discipline_ids,
        brief_id=f"{science_run_id}-computation", selected_direction=selected)
    source = load_survey_idea_context(survey_manifest_path).handoff
    raw = read_json(idea.canonical_path)
    direction = next((item for item in raw.get("directions", [])
        if selected in {item.get("direction_id"), item.get("direction_mode"), item.get("id")}), {})
    gap_ids = list(dict.fromkeys(direction.get("target_gap_ids", []) or
        brief.get("selected_direction", {}).get("target_gap_ids", [])))
    gaps = [item for item in source.get("gaps", []) if item.get("gap_id") in gap_ids]
    anchor_ids = {ref for item in gaps for ref in item.get("anchor_ids", [])}
    evidence = [{**item, "evidence_id": item["anchor_id"]} for item in source.get("anchors", [])
        if item.get("anchor_id") in anchor_ids or set(item.get("supports_gap_ids", [])) & set(gap_ids)]
    forbidden = {paper_id for item in gaps for paper_id in item.get("evidence_eligibility", {}).get("forbidden_paper_ids", [])}
    forbidden.update(paper_id for role in source.get("evidence_roles", []) for paper_id in role.get("forbidden_as_direct_evidence", []))
    for item in evidence:
        item["direct_parameter_evidence_eligible"] = bool(item.get("paper_ids")) and not (set(item.get("paper_ids", [])) & forbidden)
    binding = {key: str(idea.identity.get(key) or survey.identity.get(key) or "") for key in
        ("survey_run_id", "project_id", "project_context_fingerprint", "handoff_fingerprint")}
    binding.update(science_run_id=science_run_id, selected_direction_id=selected,
        idea_result_sha256=file_sha256(idea.canonical_path))
    return require_contract({"schema_version": "computational_context_v1", "source_binding": binding,
        "topic": source.get("topic") or brief["topic"], "research_brief": brief,
        "target_gap_ids": gap_ids, "gaps": gaps, "evidence": evidence,
        "inputs": inputs or [], "user_constraints": constraints or {}, "resource_budget": budget})
