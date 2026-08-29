from __future__ import annotations

import json
from pathlib import Path

from src.pipeline.survey_gap_ledger import build_deterministic_gap_ledger
from src.pipeline.survey_handoff_projection import build_survey_idea_handoff_projection
from src.pipeline.survey_idea_handoff import validate_handoff_payload


FIXTURE_DIR = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "agents"
    / "survey_agent"
    / "outputs"
    / "20260826-002857-396164"
)


def _fixture(name: str) -> dict:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


def _fixture_ledger() -> dict:
    return build_deterministic_gap_ledger(
        evidence_plan=FIXTURE_DIR / "survey_evidence_plan.json",
        claim_traceability=FIXTURE_DIR / "survey_claim_traceability.json",
        project_context=FIXTURE_DIR / "project_context.json",
        survey_json=FIXTURE_DIR / "survey.json",
    )


def test_fixture_ledger_projects_to_valid_handoff_with_traceable_anchors() -> None:
    ledger = _fixture_ledger()
    handoff = build_survey_idea_handoff_projection(
        gap_ledger=ledger,
        evidence_plan=_fixture("survey_evidence_plan.json"),
        project_context=_fixture("project_context.json"),
        survey_json=_fixture("survey.json"),
    )

    assert validate_handoff_payload(handoff, verify_fingerprint=True) == []
    assert {gap["gap_id"] for gap in handoff["gaps"]} == {
        gap["gap_id"]
        for gap in ledger["gaps"]
        if gap["status"] not in {"out_of_scope", "rejected"}
    }
    anchors = {anchor["anchor_id"]: anchor for anchor in handoff["anchors"]}
    assert all(gap["anchor_ids"] for gap in handoff["gaps"])
    assert all(anchor_id in anchors for gap in handoff["gaps"] for anchor_id in gap["anchor_ids"])
    assert all(anchor.get("source_pointer") for anchor in handoff["anchors"])
    assert handoff["evidence_roles"]
    assert handoff["profile_resolution"]["status"] == "unresolved"
    assert handoff["profile_resolution"].get("profile_id_hint", "") != "computational_algorithmic"


def test_only_accepted_candidate_groups_extend_the_deterministic_projection() -> None:
    ledger = _fixture_ledger()
    accepted_candidate = {
        "candidate_id": "candidate-accepted",
        "subhypothesis_id": "SH1",
        "gap_kind": "measurement_construct_mismatch",
        "target_slot": "independent_calibration",
        "statement": "The proposed measurement lacks an independently calibrated construct.",
        "rationale": "A distinct calibration observation is needed.",
        "support_level": "explicit",
        "evidence_role": "METHOD_OR_MEASUREMENT",
        "candidate_defect_tags": ["measurement_construct_mismatch"],
        "candidate_contribution_modes": ["calibration"],
        "source_pointers": [
            {
                "artifact": "survey.md",
                "json_pointer": "/sections/1",
                "paper_id": "W1",
                "section": "Limitations",
            }
        ],
        "claim_scope": "The indicated measurement claim only.",
    }
    duplicate_candidate = {
        **accepted_candidate,
        "candidate_id": "candidate-duplicate",
        "subhypothesis_id": ledger["gaps"][0]["subhypothesis_id"],
        "gap_kind": ledger["gaps"][0]["gap_kind"],
        "target_slot": ledger["gaps"][0]["target_slot"],
        "statement": "This duplicate must be represented by its deterministic gap.",
    }
    rejected_candidate = {
        **accepted_candidate,
        "candidate_id": "candidate-rejected",
        "target_slot": "rejected_observation",
        "statement": "This rejected candidate must not reach the handoff.",
    }
    adjudication = {
        "synthesis": {
            "groups": [
                {"group_id": "group-accepted", "representative": accepted_candidate},
                {"group_id": "group-duplicate", "representative": duplicate_candidate},
                {"group_id": "group-rejected", "representative": rejected_candidate},
            ]
        },
        "decisions": [
            {"group_id": "group-accepted", "decision": "accept"},
            {"group_id": "group-duplicate", "decision": "merge"},
            {"group_id": "group-rejected", "decision": "reject"},
        ],
    }

    handoff = build_survey_idea_handoff_projection(
        gap_ledger=ledger,
        adjudication=adjudication,
        evidence_plan=_fixture("survey_evidence_plan.json"),
        project_context=_fixture("project_context.json"),
        survey_json=_fixture("survey.json"),
    )

    candidate_gaps = [
        gap for gap in handoff["gaps"] if gap.get("source_kind") == "accepted_llm_gap_candidate"
    ]
    assert len(candidate_gaps) == 1
    assert candidate_gaps[0]["target_slot"] == "independent_calibration"
    assert candidate_gaps[0]["gap_group_id"] == "group-accepted"
    assert not any(gap["target_slot"] == "rejected_observation" for gap in handoff["gaps"])
    assert validate_handoff_payload(handoff, verify_fingerprint=True) == []
