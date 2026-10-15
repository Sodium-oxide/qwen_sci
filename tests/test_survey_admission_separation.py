import json

import pytest

from src.pipeline.survey_response_normalization import FormatBatch, graph_role_fields
from src.pipeline.survey_search_controller import bounded_seed_selection
from test_survey_search_controller import Model, SH, TOPIC, assessed_paper, runtime


@pytest.mark.parametrize("value", [None, "", "not_a_role", 4, ["evidence_seed"]])
def test_unknown_graph_role_is_audited_and_does_not_block_relevant_seed(value):
    source = assessed_paper("W1")
    diagnostic = FormatBatch("assessment", 1)
    fields = graph_role_fields(value, diagnostic, paper_id="W1", sub_hypothesis_id="SH1")
    source["sh_semantic_assessments"][0].update(fields)
    assert fields["recommended_graph_role"] == "undetermined"
    assert fields["recommended_graph_role_raw"] == value
    assert fields["graph_role_assessment_status"] == "undetermined"
    assert len(diagnostic.issues) == 1
    selection = bounded_seed_selection([source], [SH], [])
    assert selection["selected_papers"] == [source]
    assert selection["minimum_seed_counts_by_sh"]["SH1"] == 1
    assert source["seed_selection"]["graph_expansion_eligible"] is False
    assert source["seed_selection"]["graph_expansion_mode"] == "undetermined"


@pytest.mark.parametrize("value,expected", [("Evidence Seed", "evidence_seed"), ("context", "context_seed"),
    ("do-not-expand", "do_not_expand"), ("unknown", "undetermined")])
def test_common_graph_role_formats_recover_without_warning(value, expected):
    diagnostic = FormatBatch("assessment", 1)
    fields = graph_role_fields(value, diagnostic)
    assert fields["recommended_graph_role"] == expected
    assert fields["recommended_graph_role_raw"] == value
    assert diagnostic.recoveries
    assert not diagnostic.issues


class SourceLimitedModel(Model):
    def __init__(self, role="decision_candidate", project_score=2, excluded=False, graph_role="do_not_expand"):
        super().__init__(objects=2, feedback=False)
        self.role, self.project_score, self.excluded, self.graph_role = role, project_score, excluded, graph_role

    def batch_remote_chat(self, prompts, desc, **kwargs):
        outputs = super().batch_remote_chat(prompts, desc, **kwargs)
        for index, output in enumerate(outputs):
            response = json.loads(output)
            if desc == "Assessing Survey Papers and Objects":
                for paper in response["papers"]:
                    paper.update(project_score=self.project_score, excluded=self.excluded)
                    for assessment in paper["sh_assessments"]:
                        if self.graph_role is None:
                            assessment.pop("recommended_graph_role")
                        else:
                            assessment["recommended_graph_role"] = self.graph_role
                    for obj in paper["scientific_objects"]:
                        obj["roles_by_subhypothesis"] = {"SH1": self.role}
            elif desc == "Confirming Survey Candidate Relevance":
                for record in response["candidates"]:
                    for assessment in record["assessments"]:
                        assessment["candidate_role"] = self.role
            outputs[index] = json.dumps(response)
        return outputs


def test_local_sh_contribution_survives_low_project_score():
    collector, calls = runtime(SourceLimitedModel())
    selected, _selection = collector._collect_sh_seed_candidates(TOPIC, {}, {}, [SH])
    assert len(selected) == 2
    assert len(calls) == 3
    ledger = collector.subhypothesis_retrieval_artifact["candidate_discovery"]
    assert ledger["comparison_metrics"]["active_pairs"] == 2
    for record in ledger["records"]:
        assert record["roles_by_subhypothesis"]["SH1"] == "decision_candidate"
        assert record["candidate_relevance_by_subhypothesis"]["SH1"] == "relevant"
        assert record["candidate_source_evidence_by_subhypothesis"]["SH1"]["status"] == "eligible"
        assert record["candidate_admission_by_subhypothesis"]["SH1"] == "evidence_supported"
        assert record["effective_evidence_ids"]
        assert record["ranking_eligible"]


@pytest.mark.parametrize("role", ["mechanism_or_component", "background_entity"])
def test_relevant_auxiliary_objects_preserve_roles_without_activating(role):
    collector, _calls = runtime(SourceLimitedModel(role=role))
    collector._collect_sh_seed_candidates(TOPIC, {}, {}, [SH])
    artifact = collector.subhypothesis_retrieval_artifact
    assert artifact["comparison_metrics"]["active_pairs"] == 0
    for record in artifact["candidate_discovery"]["records"]:
        assert record["roles_by_subhypothesis"]["SH1"] == role
        assert record["candidate_relevance_by_subhypothesis"]["SH1"] == "relevant"
        assert record["candidate_admission_by_subhypothesis"]["SH1"] == "auxiliary"
        assert record["candidate_source_evidence_by_subhypothesis"]["SH1"]["status"] == "eligible"


@pytest.mark.parametrize("graph_role", ["do_not_expand", None, "not_a_role"])
def test_relevant_papers_become_seeds_without_graph_expansion(graph_role):
    collector, calls = runtime(SourceLimitedModel(project_score=4, graph_role=graph_role))
    selected, _selection = collector._collect_sh_seed_candidates(TOPIC, {}, {}, [SH])
    assert len(selected) == 2
    assert len(calls) == 3
    for paper in selected:
        assert paper["seed_selection"]["graph_expansion_eligible"] is False
        assert paper["sh_semantic_assessments"][0]["recommended_graph_role_raw"] == graph_role
    if graph_role != "do_not_expand":
        assert collector.subhypothesis_retrieval_artifact["format_normalization_audit"]


def test_explicit_exclusion_keeps_role_but_blocks_seeds_and_activation():
    collector, _calls = runtime(SourceLimitedModel(project_score=4, excluded=True))
    selected, _selection = collector._collect_sh_seed_candidates(TOPIC, {}, {}, [SH])
    artifact = collector.subhypothesis_retrieval_artifact
    assert not selected
    assert artifact["comparison_metrics"]["active_pairs"] == 0
    assert artifact["comparison_metrics"]["all_relevant_pairs"] == 0
    for record in artifact["candidate_discovery"]["records"]:
        assert record["roles_by_subhypothesis"]["SH1"] == "decision_candidate"
        assert record["candidate_relevance_by_subhypothesis"]["SH1"] == "relevant"
        assert record["candidate_source_evidence_by_subhypothesis"]["SH1"]["status"] == "excluded"
        assert not record["effective_evidence_ids"]
