from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.pipeline import survey_handoff_persistence as persistence
from src.pipeline.survey_handoff_persistence import (
    SurveyArtifactPublicationError,
    publish_survey_run_artifacts,
    verify_survey_manifest_artifacts,
)
from src.pipeline.survey_idea_handoff import (
    validate_gap_ledger_payload,
    validate_handoff_payload,
)


def _project_context() -> dict:
    return {
        "input_fingerprint": "context-1",
        "domain": "Materials Science",
        "research_identity": {"core_entities": ["sample"]},
        "discovery_taxonomy": {
            "status": "unresolved",
            "primary_discipline": None,
            "discipline_ids": [],
            "requires_human_confirmation": True,
        },
    }


def _evidence_plan() -> dict:
    return {
        "schema_version": "survey_sh_evidence_plan_v1",
        "project_id": "sci_run_1",
        "project_context_fingerprint": "context-1",
        "evidence_bounded_writing": True,
        "subhypotheses": [
            {
                "sub_hypothesis_id": "SH1",
                "summary": "A bounded scientific question.",
                "required_slots": ["direct_observation"],
                "covered_slots": [],
                "background_only_slots": [],
                "missing_slots": ["direct_observation"],
                "slot_support": {
                    "direct_observation": {
                        "expected_evidence_role": "DIRECT_OBSERVATION",
                        "evidence_paper_ids": [],
                        "background_paper_ids": [],
                        "qualified_paper_ids": [],
                        "qualified_paper_constraints": {},
                    }
                },
                "relevant_clusters": [],
                "conclusion_admissibility": {"blockers": []},
                "limitations": {"blockers": []},
                "allowed_claim_modes": ["EVIDENCE_GAP_REPORT"],
                "forbidden_paper_ids": [],
                "direct_writing_blocked_paper_ids": [],
            }
        ],
    }


def _publish(tmp_path: Path, *, gap_llm_call=None) -> dict:
    return publish_survey_run_artifacts(
        base_dir=tmp_path,
        topic="A bounded materials question",
        survey_run_id="20260826-120000-000001",
        final_survey="\n# Survey\n\nCanonical body.\n",
        survey_payload={"topic": "A bounded materials question", "paper": "Canonical body."},
        survey_outline={"sections": [{"title": "Survey"}]},
        project_context=_project_context(),
        evidence_plan=_evidence_plan(),
        claim_traceability={"claims": []},
        gap_llm_call=gap_llm_call,
        created_at="2026-08-26T12:00:00Z",
    )


def test_completed_publication_writes_valid_linked_artifacts(tmp_path: Path) -> None:
    published = _publish(tmp_path)
    manifest = json.loads(Path(published["manifest_path"]).read_text(encoding="utf-8"))
    ledger = json.loads(Path(published["gap_ledger_path"]).read_text(encoding="utf-8"))
    handoff = json.loads(Path(published["idea_handoff_path"]).read_text(encoding="utf-8"))

    assert published["status"] == "completed"
    assert Path(published["artifacts"]["survey_markdown"]).read_text(encoding="utf-8") == "\n# Survey\n\nCanonical body.\n"
    assert validate_gap_ledger_payload(ledger, verify_fingerprint=True) == []
    assert validate_handoff_payload(handoff, verify_fingerprint=True) == []
    assert verify_survey_manifest_artifacts(manifest, base_dir=tmp_path) == []
    assert set(manifest["artifacts"]).issuperset(
        {
            "survey_markdown",
            "survey_json",
            "project_context",
            "evidence_plan",
            "claim_traceability",
            "gap_ledger",
            "idea_handoff",
        }
    )


def test_manifest_verifier_detects_tampered_artifact(tmp_path: Path) -> None:
    published = _publish(tmp_path)
    Path(published["artifacts"]["survey_markdown"]).write_text("tampered", encoding="utf-8")

    errors = verify_survey_manifest_artifacts(published["manifest_path"], base_dir=tmp_path)

    assert any("survey_markdown" in error and "sha256 mismatch" in error for error in errors)


def test_publish_projects_llm_gap_candidates_into_handoff(tmp_path: Path) -> None:
    calls: list[str] = []

    def mock_gap_llm(prompt: str) -> dict:
        calls.append(prompt)
        if "Adjudicate Survey gap candidates" in prompt:
            return {"decisions": []}
        return {
            "candidates": [{
                "subhypothesis_id": "SH1",
                "gap_kind": "missing_boundary_condition",
                "target_slot": "validity_domain",
                "statement": "The observed relation has no established validity regime.",
                "confidence": 0.9,
                "source_pointers": [{
                    "artifact": "survey.md",
                    "json_pointer": "/sections/0",
                    "section": "Survey",
                }],
            }]
        }

    published = _publish(tmp_path, gap_llm_call=mock_gap_llm)
    handoff = json.loads(Path(published["idea_handoff_path"]).read_text(encoding="utf-8"))

    assert Path(published["gap_candidates_path"]).is_file()
    assert Path(published["gap_coverage_path"]).is_file()
    assert calls
    assert any(gap["gap_kind"] == "missing_boundary_condition" for gap in handoff["gaps"])


def test_llm_gap_enrichment_failure_falls_back_to_deterministic_handoff(tmp_path: Path) -> None:
    published = _publish(
        tmp_path,
        gap_llm_call=lambda _prompt: (_ for _ in ()).throw(RuntimeError("offline")),
    )
    handoff = json.loads(Path(published["idea_handoff_path"]).read_text(encoding="utf-8"))

    assert published["status"] == "completed"
    assert handoff["gaps"]
    assert handoff["gap_triage"]["top_k"] == 15
    assert Path(published["gap_candidates_path"]).is_file()


def test_interrupted_publication_finishes_with_failed_manifest(tmp_path: Path, monkeypatch) -> None:
    original_write = persistence._atomic_write_bytes

    def fail_handoff_write(path: Path, content: bytes) -> None:
        if path.name == "survey_idea_handoff.json":
            raise OSError("simulated interrupted artifact write")
        original_write(path, content)

    monkeypatch.setattr(persistence, "_atomic_write_bytes", fail_handoff_write)

    with pytest.raises(SurveyArtifactPublicationError, match="did not complete"):
        _publish(tmp_path)

    manifest = json.loads((tmp_path / "survey_manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "failed"
    assert not (tmp_path / "survey_idea_handoff.json").exists()
    assert any(
        "manifest is not completed" in error
        for error in verify_survey_manifest_artifacts(tmp_path / "survey_manifest.json", base_dir=tmp_path)
    )


def test_incomplete_contract_publishes_partial_run_without_handoff(tmp_path: Path) -> None:
    published = publish_survey_run_artifacts(
        base_dir=tmp_path,
        topic="Legacy partial survey",
        survey_run_id="20260826-120000-000002",
        final_survey="Legacy body",
        survey_payload={"topic": "Legacy partial survey"},
        project_context=_project_context(),
        evidence_plan={},
    )

    manifest = json.loads(Path(published["manifest_path"]).read_text(encoding="utf-8"))
    assert published["status"] == "partial"
    assert manifest["status"] == "partial"
    assert not (tmp_path / "survey_gap_ledger.json").exists()
    assert not (tmp_path / "survey_idea_handoff.json").exists()
    assert any(
        "manifest is not completed" in error
        for error in verify_survey_manifest_artifacts(published["manifest_path"], base_dir=tmp_path)
    )
