from __future__ import annotations

import json
import sys
from pathlib import Path
from types import ModuleType

from omegaconf import OmegaConf

from src.agents.quantitative_modeling import idea_generation
from src.pipeline.quantitative_manifests import verify_quantitative_ideas_manifest
from src.pipeline.science_manifests import verify_survey_manifest
from src.pipeline.science_stages import IdeaStageRequest, run_idea_stage
from src.pipeline.survey_handoff_persistence import publish_survey_run_artifacts


def _valid_quantitative_idea() -> dict[str, object]:
    return {
        "quantitative_idea_id": "Q1",
        "title": "Reaction transport test",
        "domain": "EARTH_ENVIRONMENT",
        "base_hypothesis_reference": "directions[0].hypothesis",
        "quantitative_question": "Can transport explain the observed gradient?",
        "model_intent": "Compare reaction-transport scenarios.",
        "candidate_model_strategy": {
            "mode": "OUTSIDE_CATALOG",
            "catalog_model_ids": [],
            "rationale": "The boundary forcing is problem-specific.",
        },
        "state_variables": ["concentration"],
        "parameters_and_sources": ["diffusivity range"],
        "initial_boundary_requirements": ["initial profile and boundary flux"],
        "scenarios": ["reference", "reduced forcing"],
        "observables": ["steady gradient"],
        "comparator": "reference forcing gradient",
        "falsification_condition": "No parameter range reproduces the observed direction.",
        "provisional_solver_family": "finite_difference_1d",
        "execution_readiness": "EXECUTABLE_CANDIDATE",
        "known_limitations": ["one-dimensional approximation"],
    }


def _publish_survey(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    evidence_plan = {
        "schema_version": "survey_sh_evidence_plan_v1",
        "project_id": "quantitative-stage",
        "project_context_fingerprint": "context-fingerprint",
        "evidence_bounded_writing": True,
        "subhypotheses": [
            {
                "sub_hypothesis_id": "SH1",
                "summary": "A bounded quantitative question.",
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
    published = publish_survey_run_artifacts(
        base_dir=tmp_path / "survey",
        topic="quantitative sidecar topic",
        survey_run_id="survey-quantitative",
        final_survey="Survey body",
        survey_payload={"topic": "quantitative sidecar topic"},
        project_context={"input_fingerprint": "context-fingerprint", "domain": "Earth science"},
        evidence_plan=evidence_plan,
        claim_traceability={"claims": []},
    )
    manifest = Path(published["manifest_path"])
    return manifest, dict(verify_survey_manifest(manifest).identity)


def test_idea_stage_publishes_isolated_quantitative_sidecar(tmp_path, monkeypatch) -> None:
    config_path = tmp_path / "science.yaml"
    OmegaConf.save(OmegaConf.create({"research": {"model": "test-model"}}), config_path)
    survey_manifest, survey_identity = _publish_survey(tmp_path)
    attempt_dir = tmp_path / "idea" / "attempt-001"

    def fake_run_idea_workflow(**kwargs: object) -> str:
        result_dir = Path(str(kwargs["output_root"])) / str(kwargs["run_id"])
        result_dir.mkdir(parents=True)
        result = {
            "schema_version": "idea_result_v5",
            "topic": "quantitative sidecar topic",
            "survey_binding": survey_identity,
            "primary_direction": "primary-direction",
            "directions": [{"direction_id": "primary-direction", "hypothesis": "test"}],
        }
        (result_dir / "idea_result.json").write_text(json.dumps(result), encoding="utf-8")
        return str(result_dir)

    fake_idea_run_module = ModuleType("src.agents.idea_agent.run")
    fake_idea_run_module.run_idea_workflow = fake_run_idea_workflow
    monkeypatch.setitem(sys.modules, "src.agents.idea_agent.run", fake_idea_run_module)
    monkeypatch.setattr(
        idea_generation,
        "build_quantitative_json_llm_call",
        lambda **_kwargs: lambda _prompt, **_call_kwargs: {"ideas": [_valid_quantitative_idea()]},
    )

    result = run_idea_stage(
        IdeaStageRequest(
            config_path=config_path,
            topic="quantitative sidecar topic",
            survey_manifest_path=survey_manifest,
            survey_identity=survey_identity,
            attempt_dir=attempt_dir,
            quiet=True,
            quantitative_mode="required",
        )
    )

    sidecar_path = Path(result.outputs["quantitative_ideas"])
    manifest_path = Path(result.outputs["quantitative_ideas_manifest"])
    sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
    verified = verify_quantitative_ideas_manifest(
        manifest_path,
        expected_identity=result.identity,
        expected_topic="quantitative sidecar topic",
    )
    canonical = json.loads(Path(result.outputs["idea_result"]).read_text(encoding="utf-8"))

    assert sidecar["ideas"][0]["quantitative_idea_id"] == "Q1"
    assert verified.payload["generation_status"] == "READY"
    assert canonical["schema_version"] == "idea_result_v5"
    assert "quantitative_ideas" not in canonical
