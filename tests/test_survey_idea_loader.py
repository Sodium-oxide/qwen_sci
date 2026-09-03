from __future__ import annotations

import json
from pathlib import Path

import pytest
from omegaconf import OmegaConf

from src.agents.idea_agent.utils.papers.paper_repository import PaperRepository
from src.pipeline.survey_handoff_persistence import publish_survey_run_artifacts
from src.pipeline.survey_idea_loader import SurveyIdeaLoadError, load_survey_idea_context


def _context() -> dict:
    return {
        "input_fingerprint": "context-1",
        "domain": "Materials Science",
        "research_identity": {"core_entities": ["sample"]},
        "discovery_taxonomy": {"status": "unresolved", "requires_human_confirmation": True},
    }


def _plan() -> dict:
    return {
        "schema_version": "survey_sh_evidence_plan_v1",
        "project_id": "sci_run_1",
        "project_context_fingerprint": "context-1",
        "evidence_bounded_writing": True,
        "subhypotheses": [{
            "sub_hypothesis_id": "SH1",
            "summary": "A bounded question.",
            "required_slots": ["direct_observation"],
            "covered_slots": [],
            "background_only_slots": [],
            "missing_slots": ["direct_observation"],
            "slot_support": {"direct_observation": {
                "expected_evidence_role": "DIRECT_OBSERVATION",
                "evidence_paper_ids": [], "background_paper_ids": [],
                "qualified_paper_ids": [], "qualified_paper_constraints": {},
            }},
            "relevant_clusters": [],
            "conclusion_admissibility": {"blockers": []},
            "limitations": {"blockers": []},
            "allowed_claim_modes": ["EVIDENCE_GAP_REPORT"],
            "forbidden_paper_ids": [],
            "direct_writing_blocked_paper_ids": [],
        }],
    }


def _publish(tmp_path: Path) -> dict:
    return publish_survey_run_artifacts(
        base_dir=tmp_path,
        topic="A bounded materials question",
        survey_run_id="20260826-130000-000001",
        final_survey="Survey body",
        survey_payload={"topic": "A bounded materials question"},
        project_context=_context(),
        evidence_plan=_plan(),
        claim_traceability={"claims": []},
    )


def test_loader_verifies_manifest_and_extracts_handoff_defects(tmp_path: Path) -> None:
    published = _publish(tmp_path)

    context = load_survey_idea_context(published["manifest_path"])

    assert context.topic == "A bounded materials question"
    assert context.survey_run_id == "20260826-130000-000001"
    assert context.handoff["schema_version"] == "survey_idea_handoff_v1"
    assert "evidence_role_deficit" in context.defect_tags
    assert context.project_context_fingerprint == "context-1"


def test_loader_rejects_tampered_hash_and_unsupported_schema(tmp_path: Path) -> None:
    published = _publish(tmp_path)
    (tmp_path / "survey_idea_handoff.json").write_text("{}", encoding="utf-8")
    with pytest.raises(SurveyIdeaLoadError, match="verification failed"):
        load_survey_idea_context(published["manifest_path"])

    second = _publish(tmp_path / "second")
    manifest_path = Path(second["manifest_path"])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["schema_version"] = "survey_manifest_v0"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(SurveyIdeaLoadError, match="Unsupported Survey manifest schema"):
        load_survey_idea_context(manifest_path)


def test_loader_explicitly_supports_old_directory_without_manifest(tmp_path: Path) -> None:
    (tmp_path / "survey.md").write_text("Legacy body", encoding="utf-8")
    (tmp_path / "survey.json").write_text(
        json.dumps({"topic": "Legacy topic", "research_run_id": "legacy-run"}),
        encoding="utf-8",
    )

    context = load_survey_idea_context(tmp_path)

    assert context.legacy is True
    assert context.topic == "Legacy topic"
    assert context.handoff == {}


def test_explicit_manifest_never_falls_back_to_topic_selected_survey(tmp_path: Path) -> None:
    config = OmegaConf.create({
        "BasicInfo": {
            "survey_manifest_path": str(tmp_path / "survey_manifest.json"),
            "topic": "A topic that happens to have older Survey runs",
            "save_path": str(tmp_path / "missing-survey.md"),
            "save_json_path": str(tmp_path / "missing-survey.json"),
        }
    })

    PaperRepository.__new__(PaperRepository)._repair_runtime_survey_paths(config)

    assert config.BasicInfo.save_path == str(tmp_path / "missing-survey.md")
    assert config.BasicInfo.save_json_path == str(tmp_path / "missing-survey.json")
