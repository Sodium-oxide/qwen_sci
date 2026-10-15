"""Query strategy changes must preserve the evidence path through Survey writing."""

import pytest

from src.pipeline.evidence_coverage_ledger import (
    associate_papers_with_subhypotheses,
    build_evidence_coverage_ledger,
)
from src.pipeline.survey_evidence_plan import build_survey_evidence_plan, EVIDENCE_GAP_REPORT


def _contract():
    return {
        "sub_hypothesis_id": "SH1",
        "retrieval_strategy": "model_feedback",
        "question": "Which method measures the response?",
        "question_kind": "METHOD_DESIGN",
        "research_role": "PRIMARY_QUESTION",
        "required_slots": ["method", "validation"],
        "slot_recovery_tasks": [
            {"task_id": f"SH1.{slot}", "slot_name": slot,
             "expected_evidence_role": "DIRECT_OBSERVATION"}
            for slot in ("method", "validation")
        ],
    }


def _paper(level="direct", status="assessed"):
    return {
        "paperId": "W1", "title": "A reported finding", "abstract": "Source information.",
        "sh_semantic_assessments": [{
            "sub_hypothesis_id": "SH1", "assessment_status": status,
            "semantic_relevance_score": 4, "overall_relation": "direct",
            "recommended_graph_role": "do_not_expand",
            "evidence_spans": [{"source": "abstract", "text": "Source information."}],
            "candidate_slot_contributions": [
                {"slot_name": slot, "support_level": level, "reason": "Reported contribution"}
                for slot in ("method", "validation")
            ],
        }],
    }


def _plan(ledger, papers=None):
    identity = {"project_id": "project", "project_context_fingerprint": "fingerprint"}
    return build_survey_evidence_plan(
        provenance_artifact={"schema_version": "sh_graph_provenance_v1", **identity},
        coverage_ledger={**ledger, **identity},
        cluster_coverage_artifact={"schema_version": "sh_cluster_coverage_projection_v1", **identity},
        subhypothesis_contracts=[_contract()], candidate_papers=papers,
    )


@pytest.mark.parametrize("strategy", ["model_feedback", "slot_driven_required_slot_recovery", None])
def test_association_and_ledger_do_not_depend_on_query_strategy(strategy):
    contract = {**_contract(), "retrieval_strategy": strategy}
    associated = associate_papers_with_subhypotheses([_paper()], [contract])
    assert associated[0]["sh_matches"][0]["coverage_slots"] == ["method", "validation"]
    ledger = build_evidence_coverage_ledger(associated, [contract])
    assert ledger["complete"] is True
    report = ledger["subhypotheses"][0]
    assert report["covered_slots"] == ["method", "validation"]
    assert _plan(ledger)["subhypotheses"][0]["evidence_paper_ids"] == ["W1"]


@pytest.mark.parametrize("papers", [[], [{"paperId": "W1"}], [_paper("partial")],
                                    [_paper(status="assessment_unavailable")]])
def test_feedback_preserves_missing_evidence_without_promoting_hits(papers):
    associated = associate_papers_with_subhypotheses(papers, [_contract()])
    ledger = build_evidence_coverage_ledger(associated, [_contract()])
    assert ledger["complete"] is False
    assert ledger["subhypotheses"][0]["missing_slots"] == ["method", "validation"]
    assert all(not slot["covered_by"] for slot in ledger["subhypotheses"][0]["slot_ledger"].values())


def test_missing_task_metadata_preserves_required_slot_gaps():
    contract = {**_contract(), "slot_recovery_tasks": []}
    ledger = build_evidence_coverage_ledger([], [contract])
    assert ledger["subhypotheses"][0]["missing_slots"] == ["method", "validation"]
    assert ledger["complete"] is False


@pytest.mark.parametrize("papers,expected_ids", [(None, []), ([_paper()], ["W1"])])
def test_empty_historical_ledger_recovers_from_saved_assessments_or_gaps(papers, expected_ids):
    plan = _plan({"schema_version": "evidence_coverage_ledger_v1", "subhypotheses": []}, papers)
    report = plan["subhypotheses"][0]
    assert report["evidence_paper_ids"] == expected_ids
    assert plan["coverage_ledger_recovery"]["recovered_subhypothesis_ids"] == ["SH1"]
    if not expected_ids:
        assert report["allowed_writing_mode"] == EVIDENCE_GAP_REPORT
        assert report["missing_slots"] == ["method", "validation"]
        assert report["conclusion_admissibility"]["admissible"] is False
