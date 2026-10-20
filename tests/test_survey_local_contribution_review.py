from copy import deepcopy
import json

import pytest

from src.agents.survey_agent.modules.search_controller import SurveySearchController
from src.pipeline.retrieval_budget import RetrievalBudget
from src.pipeline.survey_evidence_judgments import has_local_contribution, needs_local_contribution_review
from src.pipeline.survey_search_controller import query_metrics
from test_survey_evidence_boundaries import BoundaryModel, boundaries
from test_survey_search_controller import SH, TOPIC, assessed_paper, runtime


class ReviewModel(BoundaryModel):
    def __init__(self, response="supported"):
        super().__init__(boundaries(local_contribution="none"))
        self.response = response

    def batch_remote_chat(self, prompts, desc, **options):
        if desc != "Reviewing Survey Local Contributions":
            return super().batch_remote_chat(prompts, desc, **options)
        outputs = []
        for prompt in prompts:
            payload = json.loads(prompt[prompt.index('{"original_topic"'):])
            self.payloads.append((desc, payload))
            if self.response == "unavailable":
                outputs.append(None)
                continue
            reviews = []
            for item in payload["review_items"]:
                review = {"paper_id": item["paper_id"], "sub_hypothesis_id": item["sub_hypothesis_id"],
                    "local_contribution": "none" if self.response == "none" else "supported",
                    "source_system": "The reported source measurement system",
                    "transfer_rationale": "The measurement control design informs reliability testing for this SH",
                    "supported_minimal_claims": ["A reproducible measurement procedure is reported for the source system"],
                    "evidence_spans": [{"source": "abstract" if item["source"].get("abstract") else "source_excerpt",
                        "text": item["source"].get("abstract") or item["source"].get("source_excerpt", "")}],
                    "reason": "Source-system contribution assessed separately from target applicability"}
                if self.response == "wrong_identity":
                    review["paper_id"] = "W999"
                elif self.response == "duplicate":
                    reviews.append(deepcopy(review))
                elif self.response == "missing_transfer":
                    review["transfer_rationale"] = ""
                elif self.response == "title_only":
                    review["evidence_spans"] = [{"source": "title", "text": item["source"]["title"]}]
                elif self.response == "unavailable_source":
                    review["evidence_spans"] = [{"source": "source_excerpt", "text": "Not actually supplied"}]
                elif self.response == "malformed":
                    review["local_contribution"] = []
                elif self.response == "overwrite_validation":
                    review.update(target_validation="direct", ranking_evidence="sufficient", semantic_relevance_score=5)
                reviews.append(review)
            outputs.append(json.dumps({"reviews": reviews}))
        return outputs


def controller(response="supported", *, assessment_limit=10, request_limit=4, item_limit=12):
    model = ReviewModel(response)
    collector, _calls = runtime(model)
    collector._candidate_retrieval_budget = RetrievalBudget(assessment_limit=assessment_limit)
    collector.config.ModuleInfo.WorkCollector.survey_local_contribution_review_request_limit = request_limit
    collector.config.ModuleInfo.WorkCollector.survey_local_contribution_review_item_limit = item_limit
    return SurveySearchController(collector, TOPIC, {}, {}, [SH]), model


def candidate(identifier="W1"):
    paper = assessed_paper(identifier, value=2)
    paper["sh_semantic_assessments"][0].update(evidence_boundaries=boundaries(local_contribution="none"),
        reason="No exact target validation was reported", supported_minimal_claims=[], claim_limits=["Source system only"])
    return paper


@pytest.mark.parametrize("response", ["supported", "overwrite_validation"])
def test_review_recovers_local_support_without_upgrading_target_or_ranking(response):
    runner, model = controller(response)
    paper = candidate()
    original = deepcopy(paper["sh_semantic_assessments"][0])
    runner.review_local_contributions([paper])
    assessment = paper["sh_semantic_assessments"][0]
    assert has_local_contribution(assessment)
    assert assessment["evidence_boundaries"] == {**original["evidence_boundaries"], "local_contribution": "supported"}
    assert assessment["semantic_relevance_score"] == original["semantic_relevance_score"]
    assert assessment["claim_limits"] == original["claim_limits"]
    assert assessment["local_contribution_review"]["original_assessment"] == original
    assert assessment["evidence_spans"][0]["verification_status"] == "model_semantic"
    assert runner.budget.snapshot()["model_assessment_requests"] == 1
    runner.review_local_contributions([paper])
    assert len(model.payloads) == 1
    metrics = query_metrics([paper], "SH1", set(), "success")
    assert metrics["useful"] == 1 and not metrics["non_admission_reasons"]


@pytest.mark.parametrize("response", ["none", "unavailable", "wrong_identity", "duplicate", "missing_transfer",
                                      "title_only", "unavailable_source", "malformed"])
def test_failed_or_negative_review_preserves_original_non_admission(response):
    runner, model = controller(response)
    paper = candidate()
    original = deepcopy(paper["sh_semantic_assessments"][0])
    runner.review_local_contributions([paper])
    assessment = paper["sh_semantic_assessments"][0]
    assert not has_local_contribution(assessment)
    assert assessment["evidence_boundaries"] == original["evidence_boundaries"]
    assert assessment["local_contribution_review"]["status"] == ("reviewed" if response == "none"
        else "unavailable" if response == "unavailable" else "invalid_response")
    runner.review_local_contributions([paper])
    assert len(model.payloads) == 1
    assert runner.local_contribution_review_audit[0]["results"][0]["original_assessment"] == original


@pytest.mark.parametrize("change", ["supported", "direct", "excluded", "irrelevant", "title_only", "unassessed"])
def test_review_selection_respects_source_scope_and_existing_judgments(change):
    paper = candidate()
    assessment = paper["sh_semantic_assessments"][0]
    if change == "supported":
        assessment["evidence_boundaries"]["local_contribution"] = "supported"
    elif change == "direct":
        assessment["evidence_boundaries"]["target_validation"] = "direct"
    elif change == "excluded":
        paper["project_relevance"].update(excluded=True, exclusion_basis="explicit_criterion")
    elif change == "irrelevant":
        assessment["evidence_boundaries"].update(discovery_relevance="irrelevant", exclusion_basis="irrelevant")
    elif change == "title_only":
        paper["abstract"] = None
    elif change == "unassessed":
        assessment["assessment_status"] = "assessment_unavailable"
    assert not needs_local_contribution_review(paper, assessment)


def test_review_limits_and_global_budget_preserve_pending_records():
    runner, model = controller(request_limit=1, item_limit=1)
    papers = [candidate("W1"), candidate("W2")]
    runner.review_local_contributions(papers)
    assert has_local_contribution(papers[0]["sh_semantic_assessments"][0])
    assert papers[1]["sh_semantic_assessments"][0]["local_contribution_review"] == {"status": "deferred", "reason": "review_limit"}
    assert len(model.payloads) == 1
    runner, model = controller(assessment_limit=0)
    paper = candidate()
    runner.review_local_contributions([paper])
    assert paper["sh_semantic_assessments"][0]["local_contribution_review"]["reason"] == "model_budget_exhausted"
    assert not model.payloads


def test_review_uses_existing_reservation_without_exceeding_model_budget():
    runner, _model = controller(assessment_limit=1)
    lease = runner.budget.reserve_model_capacity(1)
    paper = candidate()
    runner.review_local_contributions([paper], lease)
    assert has_local_contribution(paper["sh_semantic_assessments"][0])
    runner.budget.release_model_capacity(lease)
    assert runner.budget.snapshot()["model_assessment_requests"] == 1
    assert runner.budget.model_reserved == 0


def test_verified_excerpt_is_usable_but_discovery_snippet_is_not():
    runner, _model = controller()
    paper = candidate()
    paper.update(abstract=None, verified_source_sha256="a" * 64,
        verified_source_excerpt="The source system reports a reproducible measurement procedure.")
    paper["sh_semantic_assessments"][0]["evidence_spans"] = [{"source": "source_excerpt", "text": "Reported procedure"}]
    runner.review_local_contributions([paper])
    assert has_local_contribution(paper["sh_semantic_assessments"][0])
    assert paper["sh_semantic_assessments"][0]["evidence_spans"][0]["source"] == "source_excerpt"
    paper = candidate()
    paper.update(abstract=None, discovery_snippet="An unverified mechanism claim from search")
    assert not needs_local_contribution_review(paper, paper["sh_semantic_assessments"][0])


def test_review_cannot_consume_capacity_reserved_for_feedback():
    runner, model = controller(assessment_limit=1)
    feedback_lease = runner.budget.reserve_model_capacity(1)
    paper = candidate()
    runner.review_local_contributions([paper])
    assert not model.payloads
    assert paper["sh_semantic_assessments"][0]["local_contribution_review"]["reason"] == "model_budget_exhausted"
    assert feedback_lease["remaining"] == 1
    runner.budget.release_model_capacity(feedback_lease)


def test_review_runs_before_seed_selection_and_logs_the_actual_admission():
    model = ReviewModel()
    collector, _calls = runtime(model)
    selected, _selection = collector._collect_sh_seed_candidates(TOPIC, {}, {}, [SH])
    assert len(selected) == 2
    artifact = collector.subhypothesis_retrieval_artifact
    assert artifact["local_contribution_review_audit"]
    assert all(paper["sh_semantic_assessments"][0]["evidence_boundaries"]["target_validation"] == "not_reported" for paper in selected)
    assert all(not record["ranking_eligible"] for record in artifact["candidate_discovery"]["records"])
    messages = collector.logger.messages
    assert any("Query paper admission:" in message and "admitted=True" in message
        and "target_validation=not_reported" in message and "non_admission_reason=None" in message for message in messages)
    assert any("Query evidence boundaries:" in message and "non_admission_reasons={}" in message for message in messages)
