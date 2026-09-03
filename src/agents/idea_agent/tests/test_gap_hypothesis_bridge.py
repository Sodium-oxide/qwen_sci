from __future__ import annotations

import pytest

pytest.importorskip("faiss")

from src.agents.idea_agent.agent.mcts import IdeaState
from src.agents.idea_agent.utils.mcts.mcts_runtime import build_root_state
from src.agents.idea_agent.utils.workflow.gap_hypothesis_bridge import (
    build_gap_hypothesis_seeds,
    build_gap_seed_context,
    build_gap_seed_status,
)


class CaptureIdeaState:
    def __init__(self, **payload: object) -> None:
        self.__dict__.update(payload)


def _handoff(*gaps: dict) -> dict:
    return {
        "topic": "A scientific topic",
        "profile_resolution": {"profile_id": "generic_scientific"},
        "scope": {"research_object": ["target object"]},
        "gaps": list(gaps),
        "anchors": [
            {
                "anchor_id": "anchor-1",
                "label": "Survey anchor",
                "text_excerpt": "The mechanism remains unresolved.",
                "source_pointer": {"artifact": "survey.md", "json_pointer": "/gaps/0"},
            }
        ],
        "evidence_roles": [
            {
                "subhypothesis_id": "SH1",
                "target_slot": "mechanism",
                "expected_role": "MECHANISTIC_EVIDENCE",
            }
        ],
    }


def _gap(gap_id: str, **overrides: object) -> dict:
    payload = {
        "gap_id": gap_id,
        "subhypothesis_id": "SH1",
        "gap_kind": "mechanism_gap",
        "target_slot": "mechanism",
        "statement": "The mechanism remains unresolved.",
        "target_object": "target object",
        "priority": "high",
        "status": "open",
        "anchor_ids": ["anchor-1"],
        "candidate_defect_tags": [],
    }
    payload.update(overrides)
    return payload


def test_bridge_keeps_non_excluded_routes_and_marks_constraints() -> None:
    handoff = _handoff(
        _gap("core", candidate_defect_tags=["unclear_mechanism"]),
        _gap("provisional"),
        _gap("exploratory"),
        _gap("future", gap_kind="future_work"),
        _gap("supporting", target_slot="boundary", gap_kind="boundary_gap"),
        _gap("verification", target_slot="evaluation", gap_kind="benchmark_only"),
        _gap("excluded", status="rejected"),
    )
    triage = {
        "gaps": [
            {"gap_id": "core", "eligibility_route": "core_hypothesis", "audit_status": "verified", "existence_confidence": 0.9, "verification_status": "verified"},
            {"gap_id": "provisional", "eligibility_route": "provisional_hypothesis", "audit_status": "plausible", "existence_confidence": 0.5},
            {"gap_id": "exploratory", "eligibility_route": "exploratory_frontier", "audit_status": "weakly_supported", "existence_confidence": 0.2},
            {"gap_id": "future", "eligibility_route": "future_work_seed", "audit_status": "weakly_supported", "existence_confidence": 0.2},
            {"gap_id": "supporting", "eligibility_route": "supporting_constraint", "audit_status": "verified", "existence_confidence": 0.8},
            {"gap_id": "verification", "eligibility_route": "verification_only", "audit_status": "verified", "existence_confidence": 0.8},
            {"gap_id": "excluded", "eligibility_route": "exclude", "audit_status": "contradicted", "existence_confidence": 0.9},
        ]
    }

    seeds = build_gap_hypothesis_seeds(handoff, triage)
    by_gap = {seed["gap_id"]: seed for seed in seeds}

    assert set(by_gap) == {"core", "provisional", "exploratory", "future", "supporting", "verification"}
    assert by_gap["core"]["seed_status"] == "verified"
    assert by_gap["future"]["seed_status"] == "exploratory"
    assert by_gap["supporting"]["seed_status"] == "constraint"
    assert by_gap["verification"]["seed_status"] == "constraint"
    assert by_gap["exploratory"]["candidate_defect_tags"] == ["unexplored_gap"]


def test_bridge_falls_back_to_topic_seed_without_usable_gap() -> None:
    seeds = build_gap_hypothesis_seeds(
        {"topic": "Electrochemical interfaces", "gaps": []},
        {"gaps": []},
        topic="Electrochemical interfaces",
    )

    assert len(seeds) == 1
    assert seeds[0]["gap_kind"] == "topic_seed"
    assert seeds[0]["gap_route"] == "exploratory_frontier"
    assert seeds[0]["fallback"] is True
    assert build_gap_seed_status(seeds)["fallback_used"] is True
    assert "Gap-to-Hypothesis Seeds" in build_gap_seed_context(seeds)


def test_root_state_keeps_hypothesis_seed_refs_without_expanding_idea_state() -> None:
    context = {
        "scientific_intervention_profile": {"profile_id": "generic_scientific"},
        "gap_hypothesis_seeds": [
            {
                "seed_id": "seed-1",
                "gap_id": "gap-1",
                "gap_route": "provisional_hypothesis",
                "seed_status": "provisional",
                "target_slot": "mechanism",
            }
        ],
        "gap_seed_status": {"seed_count": 1, "admission_mode": "fail_open_except_explicit_exclusion"},
    }

    root_state = build_root_state("topic", context, CaptureIdeaState)
    intervention = root_state.scientific_intervention

    assert intervention["hypothesis_seed_refs"] == [
        {
            "seed_id": "seed-1",
            "gap_id": "gap-1",
            "gap_route": "provisional_hypothesis",
            "seed_status": "provisional",
            "target_slot": "mechanism",
        }
    ]
    assert intervention["gap_seed_status"]["seed_count"] == 1


def test_idea_state_projects_hypothesis_contract_fields_without_new_required_fields() -> None:
    state = IdeaState(
        title="Title",
        abstract="Abstract",
        core_contribution="Contribution",
        method="Method",
        risks="Risks",
        tags=["tag"],
        operator="seed",
        target_defects=["unexplored_gap"],
        rationale="Rationale",
        scientific_intervention={
            "direction_mode": "bridge_builder",
            "hypothesis_contract": {
                "central_hypothesis": "The relation changes under the condition.",
                "target_gap_ids": ["gap-1"],
                "claim_scope": "The stated regime.",
            },
        },
    )

    payload = state.to_payload()

    assert payload["direction_mode"] == "bridge_builder"
    assert payload["central_hypothesis"] == "The relation changes under the condition."
    assert payload["target_gap_ids"] == ["gap-1"]
    assert payload["claim_scope"] == "The stated regime."
