import json
import threading
from copy import deepcopy
from types import SimpleNamespace

import pytest

from src.agents.survey_agent.modules.search_controller import SurveySearchController
from src.pipeline.retrieval_budget import RetrievalBudget, reserve_model_http_attempt
from test_survey_search_controller import Model, SH, TOPIC, paper, runtime


class ConfirmationModel(Model):
    def __init__(self, **options):
        super().__init__(**options)
        self.confirmation_calls = []
        self.repair_calls = []
        self.originals = []

    def confirmation(self, payload):
        records = [{"candidate_id": candidate["candidate_id"], "assessments": [
            {"sub_hypothesis_id": sh_id, "candidate_role": "decision_candidate", "reason": "Grounded option",
                "evidence_boundaries": {"discovery_relevance": "relevant"}}
            for sh_id in candidate["sub_hypothesis_ids"]]} for candidate in payload["candidates"]]
        self.originals.extend(deepcopy(records))
        return {"candidates": records}

    def repair(self, payload):
        grouped = {}
        for item in payload["repair_items"]:
            grouped.setdefault(item["candidate_id"], []).append({"sub_hypothesis_id": item["sub_hypothesis_id"],
                "project_score": 4, "sh_score": 3, "candidate_role": "background_entity", "reason": "Unrequested edit"})
        return {"candidates": [{"candidate_id": identifier, "assessments": assessments}
            for identifier, assessments in grouped.items()]}

    def batch_remote_chat(self, prompts, desc, **options):
        if desc not in {"Confirming Survey Candidate Relevance", "Repairing Survey Confirmation Scores"}:
            return super().batch_remote_chat(prompts, desc, **options)
        payloads = [json.loads(prompt[prompt.index('{"original_topic"'):]) for prompt in prompts]
        if desc == "Confirming Survey Candidate Relevance":
            self.confirmation_calls.append((payloads, options))
            return [json.dumps(self.confirmation(payload)) for payload in payloads]
        self.repair_calls.extend(payloads)
        return [json.dumps(self.repair(payload)) for payload in payloads]


def controller_for(model, *, hypothesis_count=1, assessment_limit=40):
    collector, _calls = runtime(model)
    collector._candidate_retrieval_budget = RetrievalBudget(assessment_limit=assessment_limit)
    hypotheses = [dict(SH, sub_hypothesis_id=f"SH{index + 1}") for index in range(hypothesis_count)]
    controller = SurveySearchController(collector, TOPIC, {}, {}, hypotheses)
    source = paper("W1")
    controller.assess([source], None)
    controller.papers = [source]
    for observation in controller.observations:
        observation["sub_hypothesis_ids"] = list(controller.by_sh)
        observation["roles_by_subhypothesis"] = {sh_id: "decision_candidate" for sh_id in controller.by_sh}
    return controller


def test_missing_confirmation_scores_are_repaired_for_each_candidate_and_sh():
    model = ConfirmationModel(objects=2)
    controller = controller_for(model, hypothesis_count=4)
    controller.confirm()
    assert len(model.repair_calls) == 1
    assert len(model.repair_calls[0]["repair_items"]) == 8
    for record in controller.registry:
        for sh_id in controller.by_sh:
            assert record["candidate_relevance_scores_by_subhypothesis"][sh_id]["project_score"] == 4
            assert record["candidate_relevance_scores_by_subhypothesis"][sh_id]["sh_score"] == 3
            assert record["roles_by_subhypothesis"][sh_id] == "decision_candidate"
            assert record["candidate_relevance_reasons"][sh_id] == "Grounded option"
    assert not any("format warning: stage=confirmation" in message for message in controller.collector.logger.messages)
    audit = next(entry for entry in controller.prompt_audit if entry["stage"] == "confirmation_score_repair")
    assert audit["recovered_scores"] == 16
    assert "project_score" not in audit["repair_items"][0]["assessment"]
    assert "project_score" not in model.originals[0]["assessments"][0]
    requests = controller.budget.snapshot()["model_assessment_requests"]
    controller.confirm()
    assert controller.budget.snapshot()["model_assessment_requests"] == requests


@pytest.mark.parametrize("invalid", [None, 3.7, "unknown", True, {"confidence": 4}, "conflicting_alias"])
def test_repair_replaces_only_invalid_scores_and_preserves_valid_scores(invalid):
    class PartiallyScoredModel(ConfirmationModel):
        def confirmation(self, payload):
            response = super().confirmation(payload)
            for record in response["candidates"]:
                for assessment in record["assessments"]:
                    assessment.update(project_score=5, sh_score=invalid)
                    if invalid == "conflicting_alias":
                        assessment.update(sh_score=4, semantic_relevance_score=1)
            return response

    model = PartiallyScoredModel(objects=1)
    controller = controller_for(model)
    controller.confirm()
    assert model.repair_calls[0]["repair_items"][0]["missing_fields"] == ["sh_score"]
    scores = controller.registry[0]["candidate_relevance_scores_by_subhypothesis"]["SH1"]
    assert scores["project_score"] == 5
    assert scores["sh_score"] == 3


@pytest.mark.parametrize("failure", ["null", "wrong_candidate", "wrong_sh", "duplicate_candidate", "duplicate_sh"])
def test_failed_or_ambiguous_repair_is_bounded_and_keeps_scores_unavailable(failure):
    class FailedRepairModel(ConfirmationModel):
        def repair(self, payload):
            response = super().repair(payload)
            record = response["candidates"][0]
            if failure == "null":
                record["assessments"][0].update(project_score=None, sh_score=None)
            elif failure == "wrong_candidate":
                record["candidate_id"] = "unknown_candidate"
            elif failure == "wrong_sh":
                record["assessments"][0]["sub_hypothesis_id"] = "SH9"
            elif failure == "duplicate_candidate":
                response["candidates"].append(deepcopy(record))
            else:
                record["assessments"].append(deepcopy(record["assessments"][0]))
            return response

    model = FailedRepairModel(objects=1)
    controller = controller_for(model)
    controller.confirm()
    controller.confirm()
    assert len(model.repair_calls) == 1
    assert controller.registry[0]["candidate_relevance_by_subhypothesis"]["SH1"] == "assessment_unavailable"
    assert "candidate_relevance_scores_by_subhypothesis" not in controller.registry[0]
    assert any("incomplete_confirmation" in str(entry) for entry in controller.format_audit)
    assert controller.budget.snapshot()["model_reserved"] == 0


def test_confirmation_repair_respects_request_and_global_model_budgets():
    model = ConfirmationModel(objects=3)
    controller = controller_for(model)
    settings = controller.collector.config.ModuleInfo.WorkCollector
    settings.survey_confirmation_score_repair_item_limit = 1
    settings.survey_confirmation_score_repair_request_limit = 1
    controller.confirm()
    assert len(model.repair_calls) == 1
    assert sum("candidate_relevance_scores_by_subhypothesis" in record for record in controller.registry) == 1
    model = ConfirmationModel(objects=1)
    controller = controller_for(model, assessment_limit=2)
    controller.confirm()
    assert not model.repair_calls
    assert controller.budget.snapshot()["model_assessment_requests"] == 2
    assert controller.budget.snapshot()["model_reserved"] == 0


def test_missing_scores_do_not_trigger_repair_for_an_invalid_role():
    class InvalidRoleModel(ConfirmationModel):
        def confirmation(self, payload):
            response = super().confirmation(payload)
            response["candidates"][0]["assessments"][0]["candidate_role"] = []
            return response

    model = InvalidRoleModel(objects=1)
    controller = controller_for(model)
    controller.confirm()
    assert not model.repair_calls
    assert controller.registry[0]["candidate_relevance_by_subhypothesis"]["SH1"] == "assessment_unavailable"


def test_oversized_confirmation_does_not_discard_other_batches(monkeypatch):
    model = Model(objects=2)
    controller = controller_for(model, assessment_limit=3)
    controller.collector.config.ModuleInfo.WorkCollector.survey_confirmation_pairs_per_batch = 1
    original_inputs = controller.confirmation_inputs

    def inputs_with_oversized_record(pending):
        jobs = original_inputs(pending)
        batch, sources, prompt = jobs[0]
        jobs[0] = (batch, sources, prompt + " " * 200000)
        return jobs

    monkeypatch.setattr(controller, "confirmation_inputs", inputs_with_oversized_record)
    controller.confirm()
    statuses = [record["candidate_relevance_by_subhypothesis"]["SH1"] for record in controller.registry]
    assert statuses == ["assessment_unavailable", "relevant"]
    assert controller.budget.snapshot()["model_assessment_requests"] == 2
    assert controller.budget.snapshot()["model_reserved"] == 0
    warning = next(entry for entry in controller.format_audit if entry["visible_issues"])
    assert [issue["reason"] for issue in warning["visible_issues"]] == ["prompt_budget_too_small"]


def test_confirmation_batches_are_parallel_and_budget_deferrals_do_not_drop_results():
    from src.agents.survey_agent.utils.api_call import ChatAgent

    controller = controller_for(Model(objects=5), assessment_limit=4)
    controller.collector.config.ModuleInfo.WorkCollector.survey_confirmation_pairs_per_batch = 1
    lock, overlap = threading.Lock(), threading.Event()
    active = 0
    maximum = 0

    class ParallelChat:
        accounts_model_attempts = True
        batch_workers = 1
        config = SimpleNamespace(APIInfo=SimpleNamespace(batch_chat_timeout=10, low_flow_mode=False))
        logger = controller.collector.logger

        def batch_remote_chat(self, prompts, **options):
            assert len(prompts) == 3
            assert options["workers"] == 10
            return ChatAgent.batch_remote_chat(self, prompts, **options)

        def _token_admitted_remote_chat(self, index, prompt, **options):
            nonlocal active, maximum
            reserve_model_http_attempt()
            payload = json.loads(prompt[prompt.index('{"original_topic"'):])
            with lock:
                active += 1
                maximum = max(maximum, active)
                if active == 3:
                    overlap.set()
            try:
                assert overlap.wait(5)
                if index == 1:
                    return index, "{invalid JSON"
                return index, json.dumps({"candidates": [{"candidate_id": item["candidate_id"], "assessments": [
                    {"sub_hypothesis_id": "SH1", "project_score": 4, "sh_score": 4,
                        "candidate_role": "decision_candidate", "reason": "Grounded option"}]} for item in payload["candidates"]]})
            finally:
                with lock:
                    active -= 1

    controller.collector.chat_agent = ParallelChat()
    controller.confirm()
    assert maximum == 3
    statuses = [record["candidate_relevance_by_subhypothesis"]["SH1"] for record in controller.registry]
    assert statuses.count("relevant") == 2
    assert statuses.count("assessment_unavailable") == 1
    assert statuses.count("deferred_budget") == 2
    assert controller.budget.snapshot()["model_assessment_requests"] == 4
    assert controller.budget.snapshot()["model_reserved"] == 0
    failed = next(entry for entry in controller.format_audit if entry["visible_issues"])
    assert len(failed["visible_issues"]) == 1


def test_confirmation_inputs_limit_pairs_and_split_oversized_prompts():
    controller = controller_for(Model(objects=10), hypothesis_count=4)
    controller.confirm()
    model = controller.collector.chat_agent
    payloads = [payload for stage, payload in model.payloads if stage == "Confirming Survey Candidate Relevance"]
    assert [len(payload["candidates"]) for payload in payloads] == [4, 4, 2]
    assert all("candidate_source_evidence_by_subhypothesis" not in candidate
        for payload in payloads for candidate in payload["candidates"])
    controller.collector.config.ModuleInfo.WorkCollector.survey_prompt_input_limit = 12000
    for record in controller.registry:
        record["discovery_evidence_spans"] = [{"source": "abstract", "text": "evidence " * 1000} for _index in range(10)]
    jobs = controller.confirmation_inputs(controller.registry)
    assert len(jobs) > 3
    assert sum(len(batch) for batch, _sources, _prompt in jobs) == 10
    assert all(len(batch) == 1 or controller.measure_prompt(prompt) <= controller.prompt_limit()
        for batch, _sources, prompt in jobs)
