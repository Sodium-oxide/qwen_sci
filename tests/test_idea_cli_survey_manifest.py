from __future__ import annotations

import json
from pathlib import Path

from omegaconf import OmegaConf

from src import cli
from src.pipeline.survey_handoff_persistence import publish_survey_run_artifacts


def _publish_completed_survey(tmp_path: Path) -> Path:
    project_context = {
        "input_fingerprint": "cli-context",
        "domain": "Materials Science",
    }
    evidence_plan = {
        "schema_version": "survey_sh_evidence_plan_v1",
        "project_id": "sci_cli",
        "project_context_fingerprint": "cli-context",
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
                "evidence_paper_ids": [],
                "background_paper_ids": [],
                "qualified_paper_ids": [],
                "qualified_paper_constraints": {},
            }},
            "relevant_clusters": [],
            "conclusion_admissibility": {"blockers": []},
            "limitations": {"blockers": []},
            "allowed_claim_modes": ["EVIDENCE_GAP_REPORT"],
            "forbidden_paper_ids": [],
            "direct_writing_blocked_paper_ids": [],
        }],
    }
    published = publish_survey_run_artifacts(
        base_dir=tmp_path / "survey-run",
        topic="A bounded materials question",
        survey_run_id="20260826-130000-000001",
        final_survey="Survey body",
        survey_payload={"topic": "A bounded materials question"},
        project_context=project_context,
        evidence_plan=evidence_plan,
        claim_traceability={"claims": []},
    )
    return Path(published["manifest_path"])


def test_idea_cli_exposes_explicit_survey_manifest_and_passes_it_to_worker(monkeypatch, tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    OmegaConf.save(OmegaConf.create({"idea": {"run": {"survey_manifest": ""}}}), config_path)
    manifest_path = tmp_path / "survey_manifest.json"
    manifest_path.write_text(json.dumps({"schema_version": "survey_manifest_v0"}), encoding="utf-8")
    parser = cli._build_root_parser()
    args = parser.parse_args(["idea", "--config", str(config_path), "--survey-manifest", str(manifest_path)])

    captured: dict[str, object] = {}

    def fake_run(command, *, env=None):
        captured["command"] = list(command)
        captured["env"] = dict(env or {})
        return 0

    monkeypatch.setattr(cli, "_run_command", fake_run)
    assert cli._idea_command(args) == 2

    assert captured == {}


def test_idea_cli_passes_verified_manifest_to_worker_and_runtime_config(
    monkeypatch, tmp_path: Path
) -> None:
    config_path = tmp_path / "config.yaml"
    OmegaConf.save(OmegaConf.create({"idea": {"run": {"survey_manifest": ""}}}), config_path)
    manifest_path = _publish_completed_survey(tmp_path)
    parser = cli._build_root_parser()
    args = parser.parse_args([
        "idea", "--config", str(config_path), "--survey-manifest", str(manifest_path),
    ])
    captured: dict[str, object] = {}

    def fake_run(command, *, env=None):
        runtime_config = OmegaConf.load(str((env or {})["IDEA_AGENT_CONFIG"]))
        captured["command"] = list(command)
        captured["env"] = dict(env or {})
        captured["runtime_survey_manifest"] = runtime_config.idea.run.survey_manifest
        return 0

    monkeypatch.setattr(cli, "_run_command", fake_run)

    assert cli._idea_command(args) == 0
    environment = captured["env"]
    assert isinstance(environment, dict)
    assert environment["IDEA_AGENT_SURVEY_MANIFEST"] == str(manifest_path.resolve())
    assert captured["runtime_survey_manifest"] == str(manifest_path)
