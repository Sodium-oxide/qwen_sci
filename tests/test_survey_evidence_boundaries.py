from copy import deepcopy
import json

import pytest

from src.pipeline.scientific_candidates import build_candidate_ledger
from src.pipeline.survey_evidence_judgments import (
    assessment_is_irrelevant, candidate_discovery_status, normalize_evidence_boundaries,
)
from src.pipeline.survey_search_controller import query_metrics
from test_survey_search_controller import Model, SH, TOPIC, assessed_paper, runtime


def boundaries(**updates):
    return {"discovery_relevance": "relevant", "local_contribution": "identity_only",
        "target_validation": "not_reported", "ranking_evidence": "insufficient",
        "exclusion_basis": "insufficient_evidence",
        "validation_gaps": ["Target applicability and comparable outcomes remain untested"], **updates}


class BoundaryModel(Model):
    def __init__(self, judgment=None, *, dimension_pass=False, declared_excluded=False,
                 project_basis="insufficient_evidence", candidate_judgment=None, stance="supporting"):
        super().__init__(objects=2, feedback=False)
        self.judgment = boundaries() if judgment is None else judgment
        self.candidate_judgment = self.judgment if candidate_judgment is None else candidate_judgment
        self.dimension_pass, self.declared_excluded = dimension_pass, declared_excluded
        self.project_basis, self.stance = project_basis, stance

    def batch_remote_chat(self, prompts, desc, **kwargs):
        outputs = super().batch_remote_chat(prompts, desc, **kwargs)
        for index, output in enumerate(outputs):
            response = json.loads(output)
            if desc == "Assessing Survey Papers and Objects":
                for paper in response["papers"]:
                    paper.update(project_score=2, excluded=self.declared_excluded,
                                 exclusion_basis=self.project_basis, exclusion_reason="Source evidence scope")
                    for assessment in paper["sh_assessments"]:
                        assessment.update(semantic_relevance_score=2, overall_relation="irrelevant",
                            explicit_exclusion_matches=["No target-specific test or ranking"],
                            evidence_boundaries=deepcopy(self.judgment))
                    for obj in paper["scientific_objects"]:
                        for dimension in obj["dimension_assessments"]:
                            dimension.update(minimum_evidence_pass=self.dimension_pass, stance=self.stance)
            elif desc == "Confirming Survey Candidate Relevance":
                for candidate in response["candidates"]:
                    for assessment in candidate["assessments"]:
                        assessment.update(project_score=2, sh_score=2,
                                          evidence_boundaries=deepcopy(self.candidate_judgment))
            outputs[index] = json.dumps(response)
        return outputs


def run_model(model):
    collector, calls = runtime(model)
    selected, _selection = collector._collect_sh_seed_candidates(TOPIC, {}, {}, [SH])
    return collector, selected, calls, collector.subhypothesis_retrieval_artifact["candidate_discovery"]


def test_identity_only_option_is_exploratory_with_explicit_validation_gaps():
    collector, selected, calls, ledger = run_model(BoundaryModel(declared_excluded=True))
    assert not selected
    assert len(calls) == 3
    assert ledger["comparison_metrics"]["active_pairs"] == 2
    for record in ledger["records"]:
        assert record["candidate_relevance_by_subhypothesis"]["SH1"] == "exploratory"
        assert record["candidate_admission_by_subhypothesis"]["SH1"] == "discovery_only"
        assert record["candidate_source_evidence_by_subhypothesis"]["SH1"]["status"] == "insufficient_evidence"
        readiness = record["ranking_readiness_by_subhypothesis"]["SH1"]
        assert readiness["evidence_status"] == "insufficient_evidence"
        assert readiness["missing_dimensions"]
        assert readiness["validation_gaps"]
        assert not record["ranking_eligible"]
    for paper in collector.subhypothesis_retrieval_artifact["candidate_papers"]:
        assert paper["project_relevance"]["excluded"] is False
        assert paper["project_relevance"]["excluded_raw"] is True
        assessment = paper["sh_semantic_assessments"][0]
        assert assessment["explicit_exclusion_matches"] == []
        assert assessment["explicit_exclusion_matches_raw"]
        assert assessment["overall_relation"] != "irrelevant"
    feedback = next(payload for stage, payload in collector.chat_agent.payloads
                    if stage == "Reviewing Survey Search Feedback")
    assert all(record["candidate_evidence_boundaries_by_subhypothesis"]["SH1"]["validation_gaps"]
               for record in feedback["registered_objects"])


def test_transferable_local_support_becomes_seed_without_becoming_target_efficacy():
    model = BoundaryModel(boundaries(local_contribution="supported", target_validation="indirect"))
    _collector, selected, _calls, ledger = run_model(model)
    assert len(selected) == 2
    assert all(paper["sh_matches"][0]["semantic_seed_candidate"] for paper in selected)
    assert all(record["candidate_admission_by_subhypothesis"]["SH1"] == "evidence_supported" for record in ledger["records"])
    assert all(not record["ranking_eligible"] for record in ledger["records"])
    assert not ledger["best_candidate_claim_allowed"]
    assert all(not record["effective_evidence_ids"] for record in ledger["records"])


def test_complete_local_matrix_does_not_override_declared_ranking_gap():
    model = BoundaryModel(boundaries(local_contribution="supported", target_validation="direct"), dimension_pass=True)
    _collector, selected, _calls, ledger = run_model(model)
    assert selected
    assert all(record["minimum_evidence_satisfied"] for record in ledger["records"])
    assert all(record["effective_evidence_ids"] for record in ledger["records"])
    assert all(not record["ranking_eligible"] for record in ledger["records"])
    assert not ledger["best_candidate_claim_allowed"]


def test_model_declared_ranking_sufficiency_cannot_bypass_missing_dimensions():
    judgment = boundaries(local_contribution="supported", target_validation="direct", ranking_evidence="sufficient")
    _collector, selected, _calls, ledger = run_model(BoundaryModel(judgment))
    assert selected
    assert all(not record["minimum_evidence_satisfied"] for record in ledger["records"])
    assert all(not record["ranking_eligible"] for record in ledger["records"])


def test_explicit_irrelevance_still_blocks_candidates_with_otherwise_positive_scores():
    judgment = boundaries(discovery_relevance="irrelevant", local_contribution="none", exclusion_basis="irrelevant")
    _collector, selected, _calls, ledger = run_model(BoundaryModel(judgment, project_basis="none"))
    assert not selected
    assert ledger["comparison_metrics"]["active_pairs"] == 0
    assert all(record["candidate_relevance_by_subhypothesis"]["SH1"] == "irrelevant" for record in ledger["records"])


def test_explicit_exclusion_remains_distinct_from_unperformed_validation():
    judgment = boundaries(local_contribution="supported", exclusion_basis="explicit_criterion")
    _collector, selected, _calls, ledger = run_model(BoundaryModel(judgment,
        declared_excluded=True, project_basis="explicit_criterion", dimension_pass=True))
    assert not selected
    assert ledger["comparison_metrics"]["active_pairs"] == 0
    assert all(not record["ranking_eligible"] for record in ledger["records"])


def test_missing_abstract_does_not_turn_legacy_exclusion_flag_into_confirmed_exclusion():
    from test_survey_admission_separation import SourceLimitedModel

    collector, _calls = runtime(SourceLimitedModel(excluded=True), missing_abstract=True)
    selected, _selection = collector._collect_sh_seed_candidates(TOPIC, {}, {}, [SH])
    assert not selected
    for paper in collector.subhypothesis_retrieval_artifact["candidate_papers"]:
        assert paper["project_relevance"]["excluded"] is False
        assert paper["project_relevance"]["relevance_score"] is None


def test_counterevidence_remains_relevant_and_cannot_establish_positive_ranking():
    judgment = boundaries(local_contribution="supported", target_validation="direct", ranking_evidence="sufficient")
    _collector, selected, _calls, ledger = run_model(BoundaryModel(judgment, dimension_pass=True, stance="negative"))
    assert selected
    assert all(record["negative_evidence_ids"] for record in ledger["records"])
    assert all(record["candidate_relevance_by_subhypothesis"]["SH1"] == "exploratory" for record in ledger["records"])
    assert all(not record["ranking_eligible"] for record in ledger["records"])


@pytest.mark.parametrize("judgment,reason,action", [
    (boundaries(), "identity_only", "broaden_context"),
    (boundaries(local_contribution="none"), "target_validation_gap", "broaden_context"),
    (boundaries(local_contribution="none", target_validation="direct"), "ranking_evidence_gap", "compare_alternative"),
])
def test_zero_useful_results_preserve_candidate_and_diagnose_failed_condition(judgment, reason, action):
    papers = [assessed_paper(f"W{index}", value=2) for index in range(6)]
    for paper in papers:
        paper["sh_semantic_assessments"][0]["evidence_boundaries"] = judgment
    metrics = query_metrics(papers, "SH1", set(), "success")
    assert metrics["returned_unique"] == 6
    assert metrics["useful"] == 0
    assert metrics["contribution_outcomes"] == {reason: 6}
    assert metrics["revision_guidance"]["reason"] == reason
    assert metrics["revision_guidance"]["preferred_action"] == action
    assert metrics["revision_guidance"]["preserve_candidate"]
    assert not metrics["candidate_rejection_established"]


def test_irrelevant_noise_does_not_erase_a_minority_candidate_evidence_gap():
    papers = [assessed_paper(f"W{index}", value=1) for index in range(6)]
    papers[-1]["sh_semantic_assessments"][0]["evidence_boundaries"] = boundaries()
    metrics = query_metrics(papers, "SH1", set(), "success")
    assert metrics["feedback_hint"] == "narrow_scope"
    assert metrics["contribution_outcomes"]["identity_only"] == 1
    assert not metrics["candidate_rejection_established"]


@pytest.mark.parametrize("raw", [None, [], "unsupported", {"target_validation": [], "validation_gaps": 9}])
def test_malformed_optional_boundaries_remain_unknown(raw):
    result = normalize_evidence_boundaries(raw)
    assert result["target_validation"] == "unknown"
    assert result["validation_gaps"] == []


def test_unknown_structured_relevance_is_not_rejected_from_low_scores_alone():
    judgment = boundaries(discovery_relevance="unknown", local_contribution="unknown", exclusion_basis="unknown")
    assessment = {"evidence_boundaries": judgment, "semantic_relevance_score": 1, "overall_relation": "uncertain"}
    status, _priority = candidate_discovery_status(assessment, 1, 1)
    assert status == "exploratory"
    assert not assessment_is_irrelevant(assessment)
    # Legacy records keep the established meaning of 0..1 scores.
    assert candidate_discovery_status({}, 1, 1)[0] == "irrelevant"
    assert assessment_is_irrelevant({"semantic_relevance_score": 1})


def test_incomparable_candidate_classes_cannot_receive_final_ranking_eligibility():
    from test_scientific_candidates import pair, dimension

    records, papers = pair()
    records[1]["taxonomic_level"] = "method_instance"
    ledger = build_candidate_ledger(records, papers, {"SH1": [dimension()]}, [], [])
    assert all(record["minimum_evidence_satisfied"] for record in ledger["records"])
    assert all(not record["ranking_eligible"] for record in ledger["records"])
    assert all(record["ranking_readiness_by_subhypothesis"]["SH1"]["comparability_status"] == "insufficient_comparison"
               for record in ledger["records"])


def test_handoff_retains_discovery_and_ranking_boundaries_from_frozen_ledger():
    from src.pipeline.scientific_candidates import freeze_candidate_ledger, verify_candidate_ledger
    from src.pipeline.survey_handoff_projection import build_survey_idea_handoff_projection
    from src.pipeline.survey_idea_handoff import GapLedger, build_gap_ledger_payload, validate_handoff_payload
    from test_scientific_candidates import pair, dimension
    from test_survey_idea_handoff_contract import _gap

    records, papers = pair()
    for record in records:
        record["sub_hypothesis_ids"] = ["SH3"]
        record["candidate_evidence_boundaries_by_subhypothesis"] = {"SH3": boundaries()}
    for paper in papers:
        paper["candidate_evidence_assessments"][0]["sub_hypothesis_id"] = "SH3"
    frozen = freeze_candidate_ledger(build_candidate_ledger(records, papers, {"SH3": [dimension()]}, [], []))
    gaps = build_gap_ledger_payload(GapLedger(project_id="p", survey_run_id="r", project_context_fingerprint="ctx", gaps=[_gap()]))
    handoff = build_survey_idea_handoff_projection(gap_ledger=gaps,
        project_context={"original_topic": "Compare methods"},
        survey_json={"subhypothesis_retrieval": {"candidate_discovery": frozen}})

    assert verify_candidate_ledger(frozen)
    assert validate_handoff_payload(handoff, verify_fingerprint=True) == []
    projected = handoff["scientific_candidates"]["records"]
    for source, record in zip(frozen["records"], projected):
        assert record["candidate_evidence_boundaries_by_subhypothesis"] == source["candidate_evidence_boundaries_by_subhypothesis"]
        assert record["ranking_readiness_by_subhypothesis"] == source["ranking_readiness_by_subhypothesis"]
        assert record["ranking_readiness_by_subhypothesis"]["SH3"]["evidence_status"] == "insufficient_evidence"
        assert not record["ranking_eligible"]
