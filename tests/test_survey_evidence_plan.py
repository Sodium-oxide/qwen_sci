import pytest

from src.pipeline.survey_evidence_plan import (
    BACKGROUND_ONLY,
    EVIDENCE_BACKED_SYNTHESIS,
    EVIDENCE_GAP_REPORT,
    OUT_OF_SCOPE_OR_REJECTED,
    SURVEY_EVIDENCE_PLAN_SCHEMA_VERSION,
    build_survey_evidence_plan,
)


def _provenance() -> dict:
    return {
        "schema_version": "sh_graph_provenance_v1",
        "project_id": "sci_project",
        "project_context_fingerprint": "context-A",
        "paper_annotations": {},
        "graph_expansion_records": [],
    }


def _slot(
    name: str,
    role: str,
    *,
    covered: list[str] | None = None,
    background: list[str] | None = None,
    scope_rejections: list[dict] | None = None,
) -> dict:
    return {
        "task_id": f"task.{name}",
        "slot_name": name,
        "expected_evidence_role": role,
        "minimum_evidence": "admissible study",
        "admission_rule": "scope and role verified",
        "covered_by": [{"paper_id": paper_id} for paper_id in covered or []],
        "background_only_by": [
            {"paper_id": paper_id} for paper_id in background or []
        ],
        "scope_rejections": scope_rejections or [],
    }


def _ledger() -> dict:
    return {
        "schema_version": "evidence_coverage_ledger_v1",
        "project_id": "sci_project",
        "project_context_fingerprint": "context-A",
        "subhypotheses": [
            {
                "sub_hypothesis_id": "SH1",
                "question": "Does the direct relation hold under the stated condition?",
                "question_kind": "EMPIRICAL_COVERAGE",
                "required_slots": ["direct_observation", "comparison"],
                "slot_ledger": {
                    "direct_observation": _slot(
                        "direct_observation", "DIRECT_OBSERVATION", covered=["W1"]
                    ),
                    "comparison": _slot(
                        "comparison", "COMPARATIVE_OR_MEASUREMENT_EVIDENCE", covered=["W2"]
                    ),
                },
                "covered_slots": ["direct_observation", "comparison"],
                "background_only_slots": [],
                "missing_slots": [],
                "conclusion_admissibility": {"admissible": True, "blockers": []},
            },
            {
                "sub_hypothesis_id": "SH2",
                "question": "What background framework defines the phenomenon?",
                "question_kind": "EMPIRICAL_COVERAGE",
                "required_slots": ["direct_observation"],
                "slot_ledger": {
                    "direct_observation": _slot(
                        "direct_observation", "DIRECT_OBSERVATION", background=["W3"]
                    )
                },
                "covered_slots": [],
                "background_only_slots": ["direct_observation"],
                "missing_slots": ["direct_observation"],
                "conclusion_admissibility": {
                    "admissible": False,
                    "blockers": ["background_only_slot:direct_observation"],
                },
            },
            {
                "sub_hypothesis_id": "SH3",
                "question": "Does the relation transfer outside its verified scope?",
                "question_kind": "GENERALIZATION",
                "required_slots": ["generalization"],
                "slot_ledger": {
                    "generalization": _slot(
                        "generalization",
                        "DIRECT_OBSERVATION",
                        scope_rejections=[{"paper_id": "W4", "reason": "out_of_scope"}],
                    )
                },
                "covered_slots": [],
                "background_only_slots": [],
                "missing_slots": ["generalization"],
                "conclusion_admissibility": {
                    "admissible": False,
                    "blockers": ["scope_or_admission_insufficient"],
                },
            },
            {
                "sub_hypothesis_id": "SH4",
                "question": "Which direct observation remains unresolved?",
                "question_kind": "EMPIRICAL_COVERAGE",
                "required_slots": ["direct_observation"],
                "slot_ledger": {
                    "direct_observation": _slot(
                        "direct_observation", "DIRECT_OBSERVATION"
                    )
                },
                "covered_slots": [],
                "background_only_slots": [],
                "missing_slots": ["direct_observation"],
                "conclusion_admissibility": {
                    "admissible": False,
                    "blockers": ["missing_required_slot:direct_observation"],
                },
            },
        ],
    }


def _contracts() -> list[dict]:
    return [
        {
            "sub_hypothesis_id": report["sub_hypothesis_id"],
            "question_kind": report["question_kind"],
            "required_slots": list(report["required_slots"]),
            "research_role": role,
            "challenge_target": f"challenge target for {report['sub_hypothesis_id']}",
        }
        for report, role in zip(
            _ledger()["subhypotheses"],
            [
                "PRIMARY_QUESTION",
                "BACKGROUND_CONTEXT",
                "GENERALIZATION_TEST",
                "PRIMARY_QUESTION",
            ],
        )
    ]


def _clusters() -> dict:
    return {
        "schema_version": "sh_cluster_coverage_projection_v1",
        "project_id": "sci_project",
        "project_context_fingerprint": "context-A",
        "clusters": [
            {
                "cluster_index": 1,
                "cluster_name": "verified evidence",
                "subhypotheses": [
                    {
                        "sub_hypothesis_id": "SH1",
                        "cluster_evidence_state": "DIRECT_EVIDENCE",
                        "evidence_paper_ids": ["W1", "W2"],
                        "background_paper_ids": [],
                        "graph_expanded_candidate_paper_ids": ["W-candidate"],
                        "seed_candidate_paper_ids": [],
                        "cluster_covered_slots": ["direct_observation", "comparison"],
                        "cluster_background_slots": [],
                        "cluster_uncovered_required_slots": [],
                    },
                    {
                        "sub_hypothesis_id": "SH2",
                        "cluster_evidence_state": "BACKGROUND_ONLY",
                        "evidence_paper_ids": [],
                        "background_paper_ids": ["W3"],
                        "graph_expanded_candidate_paper_ids": [],
                        "seed_candidate_paper_ids": [],
                        "cluster_covered_slots": [],
                        "cluster_background_slots": ["direct_observation"],
                        "cluster_uncovered_required_slots": ["direct_observation"],
                    },
                ],
            }
        ],
    }


def _plan() -> dict:
    return build_survey_evidence_plan(
        provenance_artifact=_provenance(),
        coverage_ledger=_ledger(),
        cluster_coverage_artifact=_clusters(),
        subhypothesis_contracts=_contracts(),
    )


def test_survey_evidence_plan_compiles_modes_slots_and_cluster_contributions() -> None:
    plan = _plan()
    by_sh = {item["sub_hypothesis_id"]: item for item in plan["subhypotheses"]}

    assert plan["schema_version"] == SURVEY_EVIDENCE_PLAN_SCHEMA_VERSION
    assert plan["writing_rules"]["graph_expanded_candidates_are_not_evidence"] is True
    assert by_sh["SH1"]["allowed_writing_mode"] == EVIDENCE_BACKED_SYNTHESIS
    assert by_sh["SH1"]["evidence_paper_ids"] == ["W1", "W2"]
    assert by_sh["SH1"]["forbidden_paper_ids"] == ["W-candidate"]
    assert by_sh["SH1"]["relevant_clusters"][0]["cluster_id"] == "cluster_1"
    assert by_sh["SH1"]["research_role"] == "PRIMARY_QUESTION"
    assert by_sh["SH2"]["allowed_writing_mode"] == BACKGROUND_ONLY
    assert by_sh["SH2"]["context_paper_ids"] == ["W3"]
    assert by_sh["SH3"]["allowed_writing_mode"] == OUT_OF_SCOPE_OR_REJECTED
    assert by_sh["SH4"]["allowed_writing_mode"] == EVIDENCE_GAP_REPORT


def test_unavailable_fulltext_blocks_direct_writing_without_changing_sh_role() -> None:
    provenance = _provenance()
    provenance["paper_annotations"] = {
        "W1": [
            {
                "project_id": "sci_project",
                "project_context_fingerprint": "context-A",
                "sub_hypothesis_id": "SH1",
                "association_status": "LEDGER_CONFIRMED_EVIDENCE",
                "evidence_use_mode": "DIRECT_LEDGER_EVIDENCE",
                "semantic_overall_relation": "direct",
            }
        ]
    }
    provenance["fulltext_acquisition_by_paper"] = {
        "W1": {
            "status": "institution_auth_required",
            "fulltext_available": False,
            "writing_direct_evidence_allowed": False,
        }
    }

    plan = build_survey_evidence_plan(
        provenance_artifact=provenance,
        coverage_ledger=_ledger(),
        cluster_coverage_artifact=_clusters(),
        subhypothesis_contracts=_contracts(),
    )
    sh1 = next(item for item in plan["subhypotheses"] if item["sub_hypothesis_id"] == "SH1")
    constraint = sh1["paper_role_constraints"]["W1"][0]

    assert constraint["evidence_use_mode"] == "DIRECT_LEDGER_EVIDENCE"
    assert constraint["semantic_overall_relation"] == "direct"
    assert constraint["allowed_support_kinds"] == []
    assert constraint["writing_direct_evidence_allowed"] is False
    assert sh1["direct_writing_blocked_paper_ids"] == ["W1"]


def test_survey_evidence_plan_rejects_cross_project_cluster_projection() -> None:
    clusters = _clusters()
    clusters["project_id"] = "sci_other"

    with pytest.raises(ValueError, match="different project"):
        build_survey_evidence_plan(
            provenance_artifact=_provenance(),
            coverage_ledger=_ledger(),
            cluster_coverage_artifact=clusters,
            subhypothesis_contracts=_contracts(),
        )


def test_survey_evidence_plan_requires_a_contract_for_every_ledger_sh() -> None:
    with pytest.raises(ValueError, match="exact contract/ledger SH set"):
        build_survey_evidence_plan(
            provenance_artifact=_provenance(),
            coverage_ledger=_ledger(),
            cluster_coverage_artifact=_clusters(),
            subhypothesis_contracts=_contracts()[:-1],
        )


def test_survey_evidence_plan_rejects_a_contract_without_final_ledger_report() -> None:
    contracts = _contracts() + [
        {
            "sub_hypothesis_id": "SH5",
            "question_kind": "EMPIRICAL_COVERAGE",
            "required_slots": ["direct_observation"],
            "research_role": "PRIMARY_QUESTION",
            "challenge_target": "unreported SH",
        }
    ]

    with pytest.raises(ValueError, match="exact contract/ledger SH set"):
        build_survey_evidence_plan(
            provenance_artifact=_provenance(),
            coverage_ledger=_ledger(),
            cluster_coverage_artifact=_clusters(),
            subhypothesis_contracts=contracts,
        )


def test_survey_evidence_plan_rejects_duplicate_contract_or_mismatched_slots() -> None:
    duplicate = [*_contracts(), dict(_contracts()[0])]
    with pytest.raises(ValueError, match="duplicate SH contract"):
        build_survey_evidence_plan(
            provenance_artifact=_provenance(),
            coverage_ledger=_ledger(),
            cluster_coverage_artifact=_clusters(),
            subhypothesis_contracts=duplicate,
        )

    mismatched = _contracts()
    mismatched[0]["required_slots"] = ["direct_observation"]
    with pytest.raises(ValueError, match="mismatched required_slots"):
        build_survey_evidence_plan(
            provenance_artifact=_provenance(),
            coverage_ledger=_ledger(),
            cluster_coverage_artifact=_clusters(),
            subhypothesis_contracts=mismatched,
        )


def test_survey_evidence_plan_rejects_ledger_from_a_different_project() -> None:
    ledger = _ledger()
    ledger["project_context_fingerprint"] = "context-other"

    with pytest.raises(ValueError, match="Evidence coverage ledger belongs"):
        build_survey_evidence_plan(
            provenance_artifact=_provenance(),
            coverage_ledger=ledger,
            cluster_coverage_artifact=_clusters(),
            subhypothesis_contracts=_contracts(),
        )


def test_writing_cap_prefers_nonexpanded_then_ranks_fulltext_promotions() -> None:
    """An expanded paper fills a deficit only after its own promotion record."""

    ledger = _ledger()
    first_slot = ledger["subhypotheses"][0]["slot_ledger"]["direct_observation"]
    nonexpanded_ids = [f"W{i}" for i in range(1, 19)]
    first_slot["covered_by"] = [{"paper_id": paper_id} for paper_id in nonexpanded_ids]
    provenance = _provenance()
    promoted_ids_and_scores = [("W19", 2), ("W20", 5), ("W21", 4), ("W22", 3)]
    provenance["paper_annotations"] = {
        paper_id: [
            {
                "project_id": "sci_project",
                "project_context_fingerprint": "context-A",
                "sub_hypothesis_id": "SH1",
                "association_stage": "FULLTEXT_PROMOTION",
                "association_status": "FULLTEXT_PROMOTED_EXPANDED",
                "evidence_use_mode": "DIRECT_LEDGER_EVIDENCE",
                "semantic_relevance_score": score,
                "promotion_relatedness_score": score / 10,
                "semantic_slot_contributions": [
                    {
                        "slot_name": "direct_observation",
                        "support_level": "direct",
                        "reason": "independently assessed complete-section evidence",
                    }
                ],
                "evidence_spans": [{"source": "complete_section_keynote", "text": "result"}],
            }
        ]
        for paper_id, score in promoted_ids_and_scores
    }

    plan = build_survey_evidence_plan(
        provenance_artifact=provenance,
        coverage_ledger=ledger,
        cluster_coverage_artifact=_clusters(),
        subhypothesis_contracts=_contracts(),
        max_writable_papers_per_sh=20,
    )
    sh1 = next(item for item in plan["subhypotheses"] if item["sub_hypothesis_id"] == "SH1")

    assert sh1["evidence_paper_ids"] == [*nonexpanded_ids, "W20", "W21"]
    assert len(sh1["evidence_paper_ids"]) == 20
    assert sh1["slot_support"]["direct_observation"]["evidence_paper_ids"] == [
        *nonexpanded_ids,
        "W20",
        "W21",
    ]
    assert sh1["writing_paper_selection"] == {
        "max_writable_papers": 20,
        "non_expanded_available": 18,
        "promoted_expanded_available": 4,
        "selected_non_expanded_paper_ids": nonexpanded_ids,
        "selected_promoted_expanded_paper_ids": ["W20", "W21"],
        "excluded_by_writing_cap_paper_ids": ["W19", "W22"],
        "selection_policy": "non_expanded_first_then_fulltext_promotion_role_and_sh_relevance_ranked_expansions",
    }
    assert sh1["paper_role_constraints"]["W20"][0][
        "association_stage"
    ] == "FULLTEXT_PROMOTION"
