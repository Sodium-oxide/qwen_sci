import json
import threading
import time
from types import SimpleNamespace

from src.agents.survey_agent.modules.search_controller import PLAN_PROMPT, SurveySearchController
from src.pipeline.retrieval_budget import RetrievalBudget
from src.pipeline.retrieval_budget import reserve_model_http_attempt
from src.pipeline.survey_prompt_budget import planning_batches, serialize_prompt
from test_survey_search_controller import Model, SH, TOPIC, runtime


def test_structured_batches_preserve_ids_and_valid_json_with_unicode():
    base = {"original_topic": "比较研究方案", "query_history": [{"query_id": "q1"}]}
    records = [{"paper_id": f"W{index}", "abstract": "研究摘要" * 400} for index in range(20)]
    measure = lambda text: len(text.encode("utf-8"))
    batches = planning_batches("Instructions\n", base, {"paper_results": records}, measure, 10000)
    assert len(batches) > 1
    assert [item["paper_id"] for batch in batches for item in batch["paper_results"]] == [item["paper_id"] for item in records]
    for batch in batches:
        prompt = serialize_prompt("Instructions\n", batch)
        assert measure(prompt) <= 10000
        assert json.loads(prompt.split("\n", 1)[1])["original_topic"] == base["original_topic"]
    assert len(records[0]["abstract"]) == 1600


def test_oversized_single_field_is_marked_without_modifying_original():
    record = {"paper_id": "W1", "abstract": "长摘要" * 50000}
    batches = planning_batches("", {"original_topic": "topic"}, {"paper_results": [record]}, len, 5000)
    prompt = serialize_prompt("", batches[0])
    assert len(prompt) <= 5000
    assert "truncated" in json.loads(prompt)["paper_results"][0]["abstract"]
    assert len(record["abstract"]) == 150000


def test_five_sh_can_use_sixty_logical_calls_and_http_limit_is_120():
    collector, _calls = runtime()
    collector._collect_sh_seed_candidates(TOPIC, {}, {}, [SH])
    hypotheses = [{**SH, "sub_hypothesis_id": f"SH{index}"} for index in range(5)]
    controller = SurveySearchController(collector, TOPIC, {}, {}, hypotheses)
    assert controller.logical_limit == 60
    assert controller.prompt_limit() == 120000
    assert controller.budget.snapshot()["http_limit"] == 120
    assert controller.budget.stages == {"primary": 96, "retry_fallback": 24}


def test_feedback_projects_large_nested_fields_and_splits_results():
    model = Model(objects=0)
    collector, _calls = runtime(model)
    collector._candidate_retrieval_budget = RetrievalBudget(assessment_limit=20)
    collector.config.ModuleInfo.WorkCollector.survey_prompt_input_limit = 15000
    collector.config.ModuleInfo.WorkCollector.survey_planning_batch_limit = 12
    controller = SurveySearchController(collector, TOPIC, {"subhypotheses": ["duplicate" * 100000]}, {}, [SH])
    controller.history = [{"query_id": "q1", "query": "measurement", "sub_hypothesis_id": "SH1"}]
    controller.papers = [{"paperId": f"W{index}", "title": "Measurement methods", "abstract": "useful evidence " * 220,
        "sh_semantic_assessments": [{"sub_hypothesis_id": "SH1", "reason": "Useful method",
            "duplicated_context": "duplicate" * 100000}]} for index in range(18)]
    controller.planning(1)
    payloads = [payload for desc, payload in model.payloads if desc == "Reviewing Survey Search Feedback"]
    assert len(payloads) > 1
    assert {paper["paper_id"] for payload in payloads for paper in payload["paper_results"]} == {f"W{index}" for index in range(18)}
    assert all(controller.measure_prompt(serialize_prompt(PLAN_PROMPT, payload)) <= 15000 for payload in payloads)
    assert all("duplicate" not in json.dumps(payload) for payload in payloads)
    assert controller.budget.snapshot()["model_assessment_requests"] == len(payloads)
    assert controller.budget.snapshot()["model_reserved"] == 0


def test_batch_deferred_when_model_capacity_runs_out_without_overspending():
    collector, _calls = runtime(Model(objects=0))
    collector._candidate_retrieval_budget = RetrievalBudget(assessment_limit=1)
    collector.config.ModuleInfo.WorkCollector.survey_prompt_input_limit = 12000
    controller = SurveySearchController(collector, TOPIC, {}, {}, [SH])
    controller.feedback_lease = controller.budget.reserve_model_capacity(1)
    controller.history = [{"query_id": "q1", "query": "measurement", "sub_hypothesis_id": "SH1"}]
    controller.papers = [{"paperId": f"W{index}", "abstract": "evidence " * 400} for index in range(12)]
    controller.planning(1)
    assert controller.budget.snapshot()["model_assessment_requests"] == 1
    assert controller.budget.snapshot()["model_reserved"] == 0
    assert any("deferred_model_budget_or_batch_limit" in str(item) for item in controller.format_audit)


def test_input_measure_uses_same_encoder_and_reserves_output_space():
    collector, _calls = runtime()
    collector._candidate_retrieval_budget = RetrievalBudget()
    collector.chat_agent = SimpleNamespace(model_name="example", config=SimpleNamespace(APIInfo=SimpleNamespace(llm_max_context_length=40000)),
        encode_with_fallback=lambda text, model: (list(text.encode("utf-8")), None))
    controller = SurveySearchController(collector, TOPIC, {}, {}, [SH])
    assert controller.measure_prompt("研究") == 6
    assert controller.prompt_limit() == 40000 - 16000 - 1024


def test_planning_uses_ten_parallel_workers_and_merges_in_input_order(monkeypatch):
    from src.agents.survey_agent.utils.api_call import ChatAgent
    from src.agents.survey_agent.modules import search_controller
    collector, _calls = runtime()
    collector._candidate_retrieval_budget = RetrievalBudget(assessment_limit=20)
    active, maximum = 0, 0
    lock = threading.Lock()
    first_ten = threading.Event()

    class ParallelChat:
        accounts_model_attempts = True
        batch_workers = 1
        config = SimpleNamespace(APIInfo=SimpleNamespace(batch_chat_timeout=10, low_flow_mode=False))
        logger = collector.logger

        def batch_remote_chat(self, prompts, **options):
            assert options["workers"] == 10
            return ChatAgent.batch_remote_chat(self, prompts, **options)

        def _token_admitted_remote_chat(self, index, prompt, **options):
            nonlocal active, maximum
            reserve_model_http_attempt()
            with lock:
                active += 1
                maximum = max(maximum, active)
                if active == 10:
                    first_ten.set()
            try:
                assert first_ten.wait(5)
                time.sleep((10 - index % 10) * .005)
                return index, json.dumps({"queries": [], "decisions": [{"action": "continue", "reason": str(index)}]})
            finally:
                with lock:
                    active -= 1

    collector.chat_agent = ParallelChat()
    controller = SurveySearchController(collector, TOPIC, {}, {}, [SH])
    controller.feedback_lease = controller.budget.reserve_model_capacity(1)
    monkeypatch.setattr(search_controller, "planning_batches", lambda prefix, base, collections, measure, limit:
        [{**base, "paper_results": [], "registered_objects": [], "evidence_ledger": []} for _index in range(14)])
    controller.planning(1)
    assert maximum == 10
    assert [item["reason"] for item in controller.decisions] == [str(index) for index in range(14)]
    assert controller.budget.snapshot()["model_assessment_requests"] == 14
    assert controller.budget.snapshot()["model_reserved"] == 0
    assert controller.feedback_lease is None


def test_parallel_planning_limits_submission_and_keeps_valid_responses(monkeypatch):
    from src.agents.survey_agent.modules import search_controller
    collector, _calls = runtime()
    collector._candidate_retrieval_budget = RetrievalBudget(assessment_limit=3)

    class PartialChat:
        def batch_remote_chat(self, prompts, **options):
            assert len(prompts) == 3
            assert options["workers"] == 10
            return ['{"queries": [], "decisions": [{"action": "continue", "reason": "first"}]}', None,
                '{"queries": [], "decisions": [{"action": "continue", "reason": "third"}]}']

    collector.chat_agent = PartialChat()
    controller = SurveySearchController(collector, TOPIC, {}, {}, [SH])
    controller.feedback_lease = controller.budget.reserve_model_capacity(1)
    monkeypatch.setattr(search_controller, "planning_batches", lambda prefix, base, collections, measure, limit:
        [{**base, "paper_results": [], "registered_objects": [], "evidence_ledger": []} for _index in range(14)])
    controller.planning(1)
    assert [item["reason"] for item in controller.decisions] == ["first", "third"]
    assert controller.budget.snapshot()["model_assessment_requests"] == 3
    assert controller.budget.snapshot()["model_reserved"] == 0
    assert any(item.get("deferred_batches") == 11 for item in controller.prompt_audit)
    assert any("invalid_or_missing_JSON" in str(item) for item in controller.format_audit)


def test_planning_default_submits_up_to_64_batches_with_shared_budget(monkeypatch):
    from src.agents.survey_agent.modules import search_controller

    model = Model(objects=0, feedback=False)
    collector, _calls = runtime(model)
    collector._candidate_retrieval_budget = RetrievalBudget(assessment_limit=80)
    controller = SurveySearchController(collector, TOPIC, {}, {}, [SH])
    controller.history = [{"query_id": "q1", "query": "measurement", "sub_hypothesis_id": "SH1"}]
    monkeypatch.setattr(search_controller, "planning_batches", lambda prefix, base, collections, measure, limit:
        [{**base, "paper_results": [], "registered_objects": [], "evidence_ledger": []} for _index in range(65)])
    controller.planning(1)
    assert len(model.payloads) == 64
    assert controller.budget.snapshot()["model_assessment_requests"] == 64
    assert any(item.get("deferred_batches") == 1 for item in controller.prompt_audit)
