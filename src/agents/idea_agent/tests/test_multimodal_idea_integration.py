from __future__ import annotations

from pathlib import Path

from src.agents.idea_agent.agent.artifacts import artifact_init, artifact_set
from src.agents.idea_agent.utils.workflow.gap_hypothesis_bridge import (
    build_gap_hypothesis_seeds,
)
from src.agents.idea_agent.utils.workflow.idea_helpers import build_direction_result_document
from src.agents.idea_agent.utils.workflow.mature_idea_sources import (
    build_mature_idea_evidence_context,
    collect_mature_idea_sources,
)
from src.agents.idea_agent.utils.workflow.idea_portfolio import build_idea_portfolio
from src.agents.idea_agent.utils.workflow.multimodal_data_anchoring import (
    DATA_ANCHORED_CLAIM_SCOPE,
    DATA_ANCHORED_PRIORITY,
    apply_data_anchored_idea_constraints,
    build_data_anchored_coverage_schedule,
)


def _projection(*, status: str = "unresolved") -> dict:
    return {
        "schema_version": "multimodal_survey_projection_v1",
        "data_anchored_subhypotheses": [
            {
                "sub_hypothesis_id": "MM_SH_01",
                "analysis_priority": DATA_ANCHORED_PRIORITY,
                "must_cover": True,
                "question_kind": "MEASUREMENT_VALIDITY",
                "claim_ids": ["mme:claim:001"],
                "observation_ids": ["mme:obs:001"],
                "observations": [
                    {
                        "observation_id": "mme:obs:001",
                        "finding": "A bounded early pattern is visible in the supplied sample.",
                        "candidate_explanation": "a tentative interface mechanism",
                        "alternative_explanations": ["a preparation artifact"],
                        "claim_limits": "Only the supplied sampled records are covered.",
                    }
                ],
                "claims": [
                    {
                        "claim_id": "mme:claim:001",
                        "observation_id": "mme:obs:001",
                        "local_data_statement": "The supplied sample contains a bounded early pattern.",
                        "candidate_explanation": "a tentative interface mechanism",
                        "alternative_explanations": ["a preparation artifact"],
                        "discriminating_prediction": "A calibrated independent readout separates the explanations.",
                        "falsifier": "The pattern vanishes in a calibrated comparison.",
                        "claim_limits": "Only the supplied sampled records are covered.",
                        "literature_reconciliation": {
                            "status": status,
                            "search_coverage": {},
                        },
                    }
                ],
            }
        ],
    }


def _handoff() -> dict:
    return {
        "topic": "Bounded interface process",
        "profile_resolution": {"profile_id": "generic_scientific"},
        "gaps": [
            {
                "gap_id": "gap-data",
                "subhypothesis_id": "MM_SH_01",
                "gap_kind": "mechanism_gap",
                "target_slot": "mechanism",
                "statement": "The observed early pattern has no settled explanation.",
                "target_object": "the supplied interface sample",
                "priority": "medium",
                "status": "open",
                "anchor_ids": ["gap-anchor"],
            },
            {
                "gap_id": "gap-literature",
                "subhypothesis_id": "SH_02",
                "gap_kind": "boundary_gap",
                "target_slot": "boundary",
                "statement": "A literature boundary remains open.",
                "target_object": "reference system",
                "priority": "high",
                "status": "open",
                "anchor_ids": ["paper-anchor"],
            },
        ],
        "anchors": [
            {
                "anchor_id": "gap-anchor",
                "anchor_type": "gap_ledger",
                "subhypothesis_id": "MM_SH_01",
                "target_slot": "mechanism",
                "text_excerpt": "The observed early pattern has no settled explanation.",
            },
            {
                "anchor_id": "mm-anchor",
                "anchor_type": "multimodal_observation",
                "subhypothesis_id": "MM_SH_01",
                "target_slot": "multimodal_observation",
                "supports_gap_ids": ["gap-data"],
                "source_id": "mme:obs:001",
                "text_excerpt": "A bounded early pattern is visible in the supplied sample.",
                "source_pointer": {
                    "artifact": "multimodal_evidence.json",
                    "json_pointer": "/observations/0",
                },
            },
            {
                "anchor_id": "paper-anchor",
                "anchor_type": "paper_excerpt",
                "subhypothesis_id": "SH_02",
                "target_slot": "boundary",
                "source_pointer": {"artifact": "survey.md", "json_pointer": "/references/0", "paper_id": "W1"},
            },
            {
                "anchor_id": "unrelated-mm-anchor",
                "anchor_type": "multimodal_observation",
                "subhypothesis_id": "MM_SH_99",
                "target_slot": "multimodal_observation",
                "source_id": "mme:obs:999",
            },
        ],
        "evidence_roles": [
            {
                "evidence_role_id": "role-direct-data",
                "subhypothesis_id": "MM_SH_01",
                "target_slot": "multimodal_observation",
                "expected_role": "DIRECT_OBSERVATION",
                "anchor_ids": ["mm-anchor"],
            },
            {
                "evidence_role_id": "role-counter-data",
                "subhypothesis_id": "MM_SH_01",
                "target_slot": "multimodal_native_measurement",
                "expected_role": "METHOD_OR_MEASUREMENT",
                "anchor_ids": ["mm-anchor"],
                "paper_ids": ["W2"],
                "qualified_paper_ids": ["W3"],
                "background_paper_ids": ["W4"],
            },
            {
                "evidence_role_id": "role-unrelated",
                "subhypothesis_id": "MM_SH_99",
                "target_slot": "multimodal_observation",
                "expected_role": "DIRECT_OBSERVATION",
                "anchor_ids": ["unrelated-mm-anchor"],
            },
        ],
    }


def test_gap_bridge_prioritizes_data_anchor_and_limits_measurement_risk() -> None:
    handoff = _handoff()
    seeds = build_gap_hypothesis_seeds(
        handoff,
        multimodal_evidence_projection=_projection(status="measurement_at_risk"),
    )

    assert seeds[0]["gap_id"] == "gap-data"
    data_seed = next(seed for seed in seeds if seed["gap_id"] == "gap-data")
    assert data_seed["analysis_priority"] == DATA_ANCHORED_PRIORITY
    assert data_seed["data_anchor_refs"] == ["mme:obs:001"]
    assert data_seed["literature_reconciliation_status"] == "measurement_at_risk"
    assert data_seed["gap_kind"] == "measurement_validity_gap"
    assert data_seed["target_slot"] == "multimodal_native_measurement"
    assert "calibration" in data_seed["gap_statement"]


def test_unresolved_data_seed_does_not_become_a_first_discovery_claim() -> None:
    handoff = _handoff()
    handoff["gaps"][0]["statement"] = "This is the first discovery in the supplied sample."
    data_seed = next(
        seed
        for seed in build_gap_hypothesis_seeds(
            handoff,
            multimodal_evidence_projection=_projection(status="unresolved"),
        )
        if seed["gap_id"] == "gap-data"
    )

    assert any("first discovery" in item for item in data_seed["unknown_or_unverified"])
    assert data_seed["literature_reconciliation_status"] == "unresolved"
    assert "first discovery" not in data_seed["gap_statement"].casefold()


def test_data_coverage_schedule_reserves_all_three_branches_within_cap() -> None:
    data_seed = next(
        seed
        for seed in build_gap_hypothesis_seeds(
            _handoff(),
            multimodal_evidence_projection=_projection(),
        )
        if seed["gap_id"] == "gap-data"
    )
    schedule = build_data_anchored_coverage_schedule(
        [data_seed],
        ordinary_task_count=2,
        iterations_per_search=12,
        budget_cap=0.50,
    )

    assert schedule["coverage_pass_order"] == "before_ordinary_mcts"
    assert schedule["allocated_data_expansion_budget"] <= schedule["data_expansion_budget_cap"]
    actual_total = (
        schedule["ordinary_expansion_budget"]
        + schedule["allocated_data_expansion_budget"]
    )
    assert schedule["allocated_data_expansion_budget"] <= 0.50 * actual_total
    assert [branch["branch_id"] for branch in schedule["assignments"][0]["coverage_branches"]] == [
        "candidate_mechanism",
        "alternative_explanation",
        "measurement_artifact",
    ]
    assert schedule["assignments"][0]["mcts_depth_multiplier"] == 1.75

    maximum_cap_schedule = build_data_anchored_coverage_schedule(
        [data_seed],
        ordinary_task_count=1,
        iterations_per_search=12,
        budget_cap=1.0,
    )
    assert maximum_cap_schedule["data_expansion_budget_share_cap"] == 0.50
    assert maximum_cap_schedule["allocated_data_expansion_budget"] <= 0.50 * (
        maximum_cap_schedule["ordinary_expansion_budget"]
        + maximum_cap_schedule["allocated_data_expansion_budget"]
    )

    deferred_schedule = build_data_anchored_coverage_schedule(
        [data_seed],
        ordinary_task_count=0,
        iterations_per_search=12,
    )
    assert deferred_schedule["enabled"] is False
    assert deferred_schedule["assignments"] == []
    assert deferred_schedule["deferred_subhypothesis_ids"] == ["MM_SH_01"]


def test_data_anchor_requires_explicit_gap_binding() -> None:
    handoff = _handoff()
    handoff["gaps"].append(
        {
            **handoff["gaps"][0],
            "gap_id": "gap-same-sh-unbound",
            "anchor_ids": ["gap-anchor"],
        }
    )

    seeds = build_gap_hypothesis_seeds(
        handoff,
        multimodal_evidence_projection=_projection(),
    )
    by_gap = {seed["gap_id"]: seed for seed in seeds}

    assert by_gap["gap-data"]["analysis_priority"] == DATA_ANCHORED_PRIORITY
    assert "analysis_priority" not in by_gap["gap-same-sh-unbound"]


def test_mature_context_scopes_data_anchor_and_related_papers_to_target_gap() -> None:
    handoff = _handoff()
    ideas = collect_mature_idea_sources(
        survey_handoff=handoff,
        multimodal_evidence_projection=_projection(),
    )
    idea = next(item for item in ideas if item.get("target_gap_ids") == ["gap-data"])
    context = build_mature_idea_evidence_context(
        idea,
        survey_handoff=handoff,
        multimodal_evidence_projection=_projection(),
        references=[
            {"paper_id": "W1", "title": "Unrelated boundary study"},
            {"paper_id": "W2", "title": "Calibration counterexample"},
            {"paper_id": "W3", "title": "Qualified measurement support"},
            {"paper_id": "W4", "title": "Background measurement context"},
        ],
    )

    assert context["multimodal_evidence_context"]["data_anchor_refs"] == ["mme:obs:001"]
    scoped_anchor_ids = {anchor["anchor_id"] for anchor in context["survey_handoff"]["anchors"]}
    assert {"gap-anchor", "mm-anchor"}.issubset(scoped_anchor_ids)
    assert "unrelated-mm-anchor" not in scoped_anchor_ids
    assert [item["paper_id"] for item in context["evidence_subset"]] == ["W2", "W3", "W4"]
    assert "a preparation artifact" in context["counterexamples"]


def test_data_anchored_final_candidate_requires_bounded_evidence_contract() -> None:
    data_seed = next(
        seed
        for seed in build_gap_hypothesis_seeds(
            _handoff(),
            multimodal_evidence_projection=_projection(),
        )
        if seed["gap_id"] == "gap-data"
    )
    completed = apply_data_anchored_idea_constraints(
        {
            "title": "Calibrated data hypothesis",
            "abstract": "A bounded candidate.",
            "core_contribution": "A discriminating mechanism test.",
            "method": "Contrast the candidate with a calibrated alternative.",
            "expected_mechanism": "The local pattern follows the candidate interface mechanism.",
            "discriminating_observation": "A calibrated contrast separates the alternatives.",
            "target_gap_ids": ["gap-data"],
        },
        seed=data_seed,
    )
    incomplete = apply_data_anchored_idea_constraints(
        {
            "title": "Unspecified data hypothesis",
            "abstract": "A bounded candidate.",
            "core_contribution": "A claim without a mechanism.",
            "method": "Inspect the supplied observation.",
            "target_gap_ids": ["gap-data"],
        },
        seed=data_seed,
    )

    assert completed["data_anchored_contract_status"] == "complete"
    assert completed["claim_scope"] == DATA_ANCHORED_CLAIM_SCOPE
    assert completed["data_anchor_refs"] == ["mme:obs:001"]
    assert completed["competing_explanations"] == ["a preparation artifact"]
    assert completed["falsifier"]
    assert incomplete["data_anchored_contract_status"] == "incomplete"
    assert incomplete["invariant_status"] == "violated"
    assert "missing_data_anchored_candidate_mechanism" in incomplete["invariant_violations"]

    incomplete_portfolio = build_idea_portfolio(
        [incomplete],
        has_survey_handoff=True,
    )
    complete_portfolio = build_idea_portfolio(
        [completed],
        has_survey_handoff=True,
    )
    assert incomplete_portfolio["selected_primary_idea"] == {}
    assert incomplete_portfolio["diversity_report"]["invariant_violation_count"] == 1
    assert complete_portfolio["selected_primary_idea"]["idea_id"] == "Calibrated data hypothesis"


def test_public_idea_result_exposes_required_bounded_data_fields(tmp_path: Path) -> None:
    data_seed = next(
        seed
        for seed in build_gap_hypothesis_seeds(
            _handoff(),
            multimodal_evidence_projection=_projection(),
        )
        if seed["gap_id"] == "gap-data"
    )
    candidate = apply_data_anchored_idea_constraints(
        {
            "title": "Calibrated data hypothesis",
            "abstract": "A bounded candidate.",
            "core_contribution": "A discriminating mechanism test.",
            "method": "Contrast the candidate with a calibrated alternative.",
            "expected_mechanism": "The local pattern follows the candidate interface mechanism.",
            "discriminating_observation": "A calibrated contrast separates the alternatives.",
            "target_gap_ids": ["gap-data"],
        },
        seed=data_seed,
    )
    manifest = tmp_path / "survey_manifest.json"
    manifest.write_text("{}", encoding="utf-8")
    artifact = artifact_init()
    artifact_set(
        artifact,
        "survey_idea_context",
        {
            "manifest_path": str(manifest),
            "handoff": _handoff(),
            "survey_run_id": "survey-data",
        },
    )

    document = build_direction_result_document("Bounded interface process", candidate, artifact)
    direction = document["directions"][0]

    assert direction["data_anchor_refs"] == ["mme:obs:001"]
    assert direction["literature_reconciliation_status"] == "unresolved"
    assert direction["candidate_mechanism"]
    assert direction["discriminating_measurement_plan"]
    assert direction["falsifier"]
    assert direction["claim_scope"] == DATA_ANCHORED_CLAIM_SCOPE
