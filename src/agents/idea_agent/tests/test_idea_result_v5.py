from __future__ import annotations

from pathlib import Path

from src.agents.idea_agent.agent.artifacts import artifact_get, artifact_init, artifact_set
from src.agents.idea_agent.utils.workflow.idea_helpers import (
    build_direction_result_document,
    build_survey_binding,
)


def _direction() -> dict:
    return {
        "direction_mode": "ambitious_realist",
        "title": "A bounded direction",
        "abstract": "A direction-specific abstract.",
        "central_hypothesis": "The mechanism changes the target relation under the stated condition.",
        "scientific_object": {"object_type": "electrochemical interface"},
        "mechanism_or_relation": "interfacial transport relation",
        "discriminating_observation": "The mechanism-specific contrast is observable.",
        "boundary_or_failure_condition": "Only within the stated operating regime.",
        "claim_scope": "The prepared material and operating regime.",
        "assumptions": ["The interface remains in the specified regime."],
        "target_gap_ids": ["gap-1"],
        "gap_alignment": [{"gap_id": "gap-1", "alignment": "direct"}],
        "evidence_requirement": "Observe the mechanism-specific contrast.",
        "risks": "The relation may have a competing explanation.",
        "scientificity_status": "SCIENTIFICALLY_QUALIFIED_WITH_UNCERTAINTY",
        "debate_trace": [{"alternative_explanations": ["A competing transport pathway."], "round": 2}],
        "scientific_intervention": {
            "hypothesis_seed_refs": [
                {
                    "gap_id": "gap-1",
                    "gap_route": "provisional_hypothesis",
                    "seed_status": "provisional",
                    "unknown_or_unverified": ["verification remains open"],
                }
            ]
        },
    }


def test_v5_document_projects_hypothesis_and_restricted_experiment_handoff(tmp_path: Path) -> None:
    manifest = tmp_path / "survey_manifest.json"
    manifest.write_text("{}", encoding="utf-8")
    artifact = artifact_init()
    artifact_set(
        artifact,
        "survey_idea_context",
        {
            "manifest_path": str(manifest),
            "survey_run_id": "survey-1",
            "project_id": "project-1",
            "project_context_fingerprint": "project-fp",
            "handoff": {
                "handoff_fingerprint": "handoff-fp",
                "gaps": [{"gap_id": "gap-1", "statement": "The relation is unresolved."}],
            },
        },
    )

    document = build_direction_result_document("Topic", _direction(), artifact)
    assert document["schema_version"] == "idea_result_v5"
    assert document["survey_binding"]["status"] == "bound"
    assert document["survey_binding"]["handoff_fingerprint"] == "handoff-fp"
    public_direction = document["directions"][0]
    assert public_direction["hypothesis"]["central_hypothesis"]
    handoff = public_direction["experiment_handoff"]
    assert handoff["claim_to_test"] == _direction()["central_hypothesis"]
    assert handoff["gap_ids"] == ["gap-1"]
    assert "A competing transport pathway." in handoff["alternative_explanations"]
    assert "Observe the mechanism-specific contrast." in handoff["required_observations"]
    forbidden = {
        "experiment_design",
        "predicted_results",
        "sample_size",
        "statistical_test",
        "instrument_configuration",
        "ablation_plan",
        "failure_repair_plan",
    }
    assert forbidden.isdisjoint(handoff)


def test_missing_survey_manifest_marks_direction_for_review_without_empty_result() -> None:
    artifact = artifact_init()
    document = build_direction_result_document("Topic", _direction(), artifact)
    assert build_survey_binding(artifact)["status"] == "missing"
    assert document["directions"]
    assert document["directions"][0]["scientificity_status"] == "REQUIRES_REVIEW"
    assert document["directions"][0]["hypothesis"]["central_hypothesis"]


def test_new_direction_artifacts_are_typed_lists() -> None:
    artifact = artifact_init()
    artifact_set(artifact, "idea_direction_results", [{"direction_mode": "steady_engineer"}])
    artifact_set(artifact, "idea_hypotheses", [{"central_hypothesis": "H"}])
    assert artifact_get(artifact, "idea_direction_results")[0]["direction_mode"] == "steady_engineer"
    assert artifact_get(artifact, "idea_hypotheses")[0]["central_hypothesis"] == "H"
