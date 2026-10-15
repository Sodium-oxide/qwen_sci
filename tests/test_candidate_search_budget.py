from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
from types import SimpleNamespace

import pytest
import requests

from src.pipeline.retrieval_budget import (
    RetrievalBudget, RetrievalBudgetExceeded, retrieval_request_scope, reserve_retrieval_http_attempt,
    bind_retrieval_budget, provider_retrieval_budget,
)
from src.pipeline.retrieval_lanes import build_candidate_evidence_tasks
from src.pipeline.scientific_candidates import build_candidate_ledger, register_candidates, freeze_candidate_ledger
from src.pipeline.candidate_search_schedule import promotion_order
from test_scientific_candidates import paper, observation, dimension, assess
from test_sh_paper_semantic_assessment import _collector, _CapturingLogger


def test_concurrent_http_attempts_never_exceed_global_budget():
    budget = RetrievalBudget(total=7, stages={"screening": 100, "supplement": 100})
    def execute(index):
        try:
            with retrieval_request_scope(budget, "screening", str(index)):
                reserve_retrieval_http_attempt()
            return True
        except RetrievalBudgetExceeded:
            return False
    with ThreadPoolExecutor(max_workers=12) as executor:
        results = list(executor.map(execute, range(80)))
    assert sum(results) == 7
    assert budget.snapshot()["http_attempts"] == 7


def test_request_retries_use_supplement_reservation():
    budget = RetrievalBudget(total=3, stages={"screening": 1, "supplement": 1})
    with retrieval_request_scope(budget, "screening", "request"):
        reserve_retrieval_http_attempt()
        reserve_retrieval_http_attempt()
        with pytest.raises(RetrievalBudgetExceeded):
            reserve_retrieval_http_attempt()
    assert budget.snapshot()["http_attempts_by_stage"] == {"screening": 1, "supplement": 1}
    assert budget.snapshot()["distinct_external_requests"] == 1
    reserve_retrieval_http_attempt()
    assert budget.snapshot()["http_attempts"] == 2


def test_openalex_real_session_boundary_counts_retry_and_propagates_cap(monkeypatch):
    from test_survey_openalex_unpaywall import api_call, OpenAlexAPI, _api_config
    provider = OpenAlexAPI(_api_config(openalex_api_max_retry=3))
    provider._wait_for_request_rate_slot = lambda: 0
    monkeypatch.setattr(api_call.time, "sleep", lambda _seconds: None)
    calls = []
    def send(_adapter, _request, **_kwargs):
        calls.append(True)
        raise requests.ReadTimeout("timeout")
    monkeypatch.setattr(requests.adapters.HTTPAdapter, "send", send)
    budget = RetrievalBudget(total=2, stages={"screening": 1, "supplement": 1})
    with retrieval_request_scope(budget, "screening", "openalex"):
        with pytest.raises(RetrievalBudgetExceeded):
            provider._call_pyalex("search", lambda session: session.get("https://example.test/works"), budgeted_search=True)
    assert len(calls) == 2
    assert budget.snapshot()["http_attempts"] == 2


def test_semantic_scholar_retries_do_not_consume_search_budget(monkeypatch):
    from test_survey_openalex_unpaywall import api_call
    calls = []
    def get(*_args, **_kwargs):
        calls.append(True)
        return SimpleNamespace(status_code=429)
    monkeypatch.setattr(api_call.requests, "get", get)
    monkeypatch.setattr(api_call.time, "sleep", lambda _seconds: None)
    provider = api_call.SemanticScholarAPI(SimpleNamespace(APIInfo=SimpleNamespace(
        semantic_scholar_api_key="", semantic_scholar_api_max_retry=4)))
    budget = RetrievalBudget(total=2, stages={"supplement": 2})
    with retrieval_request_scope(budget, "supplement", "fallback"):
        assert provider.search_papers("comparison", "title") is None
    assert len(calls) == 5
    assert budget.snapshot()["http_attempts"] == 0


def test_redirect_transport_cannot_bypass_budget(monkeypatch):
    from test_survey_openalex_unpaywall import api_call
    calls = []
    def send(_adapter, request, **_kwargs):
        calls.append(request.url)
        response = requests.Response()
        response.status_code = 302
        response.headers["Location"] = "https://example.test/redirected"
        response._content = b""
        response.request = request
        response.url = request.url
        return response
    monkeypatch.setattr(requests.adapters.HTTPAdapter, "send", send)
    budget = RetrievalBudget(total=1, stages={"screening": 1, "supplement": 1})
    with retrieval_request_scope(budget, "screening", "redirect"):
        with api_call._TimeoutSession((1, 1), budgeted_search=True) as session:
            with pytest.raises(RetrievalBudgetExceeded):
                session.get("https://example.test/works")
    assert len(calls) == 1
    assert budget.snapshot()["http_attempts"] == 1


def test_metadata_after_exhausted_search_budget_still_runs(monkeypatch):
    from test_survey_openalex_unpaywall import OpenAlexAPI, _api_config
    provider = OpenAlexAPI(_api_config())
    provider._wait_for_request_rate_slot = lambda: 0
    budget = RetrievalBudget(total=1, stages={"screening": 1, "supplement": 1})
    budget.reserve_http("screening", "initial")
    provider.retrieval_budget = budget
    calls = []
    def send(_adapter, request, **kwargs):
        calls.append(request.url)
        response = requests.Response()
        response.status_code = 200
        response._content = b"{}"
        response.request = request
        response.url = request.url
        return response
    monkeypatch.setattr(requests.adapters.HTTPAdapter, "send", send)
    # Even inside an active search scope, metadata must bypass its exhausted budget.
    with retrieval_request_scope(budget, "screening", "query"):
        assert provider._call_pyalex("work W1", lambda session: session.get("https://example.test/metadata")) is not None
        assert provider._call_pyalex("citations", lambda session: session.get("https://example.test/citations")) is not None
    assert len(calls) == 2
    assert budget.snapshot()["http_attempts"] == 1


def test_public_openalex_query_search_charges_budget_but_details_do_not(monkeypatch):
    from test_survey_openalex_unpaywall import api_call, OpenAlexAPI, _api_config
    provider = OpenAlexAPI(_api_config())
    provider._wait_for_request_rate_slot = lambda: 0
    budget = RetrievalBudget(total=1, stages={"primary": 1, "retry_fallback": 1})
    provider.retrieval_budget = budget
    calls = []

    def send(_adapter, request, **kwargs):
        calls.append(request.url)
        response = requests.Response()
        response.status_code = 200
        response._content = b"{}"
        response.request = request
        response.url = request.url
        return response

    class Works:
        url = "https://example.test/works"

        def search(self, query):
            return self

        def _get_from_url(self, url, session):
            session.get(url)
            return {"id": "https://openalex.org/W1", "title": "Metadata"}

    def get_results(works, session, **kwargs):
        session.get("https://example.test/works?search=calibration")
        return []

    monkeypatch.setattr(requests.adapters.HTTPAdapter, "send", send)
    monkeypatch.setattr(api_call, "PyAlexWorks", Works)
    monkeypatch.setattr(provider, "_pyalex_get", get_results)
    assert provider.search_papers_with_status("calibration") == ([], True)
    assert provider.get_paper_details("W1")["title"] == "Metadata"
    assert provider.search_papers_with_status("calibration") == ([], False)
    assert len(calls) == 2
    assert budget.snapshot()["http_attempts"] == 1
    assert budget.snapshot()["http_budget_scope"] == "openalex_query_search_only"


def test_assessment_reservations_preserve_comparison_budget():
    budget = RetrievalBudget(assessment_limit=4, assessment_stages={"screening": 2, "comparison": 2})
    assert budget.reserve_assessment("screening")
    assert budget.reserve_assessment("screening")
    assert not budget.reserve_assessment("screening")
    assert budget.reserve_assessment("comparison")
    assert budget.reserve_assessment("comparison")
    assert not budget.reserve_assessment("comparison")


def test_role_filter_and_query_compiler_do_not_expand_background_objects():
    papers = [paper("W1", "Method Alpha"), paper("W2", "Method Beta"), paper("W3", "Target System")]
    observations = [observation(papers[0], "Method Alpha"), observation(papers[1], "Method Beta"),
                    {**observation(papers[2], "Target System"), "candidate_role": "target_system"}]
    registry = register_candidates(observations, papers)
    contract = {"sub_hypothesis_id": "SH1", "required_slots": ["performance"],
                "slot_definitions": {"performance": {"retrieval_concepts": ["Method Alpha target compatibility"],
                                                       "meaning": "Measured comparative performance"}}}
    tasks = build_candidate_evidence_tasks(contract, registry, max_tasks=2)
    assert len(tasks) == 2
    beta = next(task for task in tasks if task["candidate_id"] == next(record["candidate_id"] for record in registry if record["name"] == "Method Beta"))
    assert "Method Alpha" not in beta["retrieval_plan"]["query_lanes"][0]["query"]
    assert all(len(task["retrieval_plan"]["query_lanes"]) == 1 for task in tasks)
    ledger = freeze_candidate_ledger(build_candidate_ledger(registry, [], {"SH1": [dimension()]}, [], []))
    assert ledger["comparison_scope"]["discovered_objects"] == 3
    assert ledger["balance"]["registered_candidate_count"] == 2
    assert ledger["primary_candidate_id"] != next(record["candidate_id"] for record in registry if record["name"] == "Target System")


def test_unclassified_objects_cannot_become_decision_candidates():
    source = paper("W1", "Unclassified Object")
    raw = observation(source, "Unclassified Object")
    raw.pop("candidate_role")
    registry = register_candidates([raw], [source])
    assert registry[0]["roles_by_subhypothesis"] == {"SH1": "role_unresolved"}
    assert build_candidate_evidence_tasks({"sub_hypothesis_id": "SH1", "required_slots": ["performance"]}, registry) == []


def test_run_local_request_reuse_works_when_persistent_cache_disabled():
    collector = _collector(SimpleNamespace())
    collector.logger = _CapturingLogger()
    collector._candidate_retrieval_budget = RetrievalBudget(total=2, stages={"screening": 2})
    collector._candidate_request_results = {}
    calls = []
    def search(_lane):
        reserve_retrieval_http_attempt()
        calls.append(True)
        return [paper("W1", "Method Alpha")], True, "success"
    collector._execute_query_lane_unbudgeted = search
    lane = {"lane_id": "one", "provider": "openalex", "query": "Method Alpha", "budget_phase": "screening"}
    first = collector._execute_query_lane_with_status(lane)
    first[0][0]["title"] = "mutated"
    second = collector._execute_query_lane_with_status({**lane, "lane_id": "two", "candidate_id": "other"})
    assert len(calls) == 1
    assert second[0][0]["title"] == "Method Alpha evaluation"
    assert collector._candidate_retrieval_budget.snapshot()["request_reuse_hits"] == 1


def test_deferred_lane_is_neither_empty_nor_failed():
    collector = _collector(SimpleNamespace())
    lane = {"lane_id": "deferred", "candidate_id": "a", "retrieval_cache": {"provider_status": "deferred_budget"}}
    summary = collector._slot_retrieval_summary([lane], [(lane, [])], [],
        min_candidates_before_relaxation=1, relaxation_used=False, fallback_used=False)
    assert summary["deferred_lanes"] == ["deferred"]
    assert summary["zero_result_lanes"] == []
    assert summary["failed_lanes"] == []


def test_hundreds_of_objects_have_bounded_screening_and_visible_deferrals():
    collector = _collector(SimpleNamespace())
    collector.logger = _CapturingLogger()
    collector._candidate_retrieval_budget = RetrievalBudget(total=5, stages={"screening": 5, "comparison": 0, "supplement": 0}, assessment_limit=0)
    collector._candidate_request_results = {}
    collector._executed_retrieval_lanes = []
    collector._slot_retrieval_summaries = []
    papers = [paper("W" + str(index), "Method " + str(index)) for index in range(350)]
    collector._scientific_candidate_registry = register_candidates([observation(source, "Method " + str(index))
        for index, source in enumerate(papers)], papers)
    calls = []
    def discover(rows, retrieval_round=0):
        lanes = [lane for row in rows for task in row["slot_recovery_tasks"] for lane in task["retrieval_plan"]["query_lanes"]]
        calls.append(lanes)
        assert len(lanes) <= 4
        for lane in lanes:
            collector._candidate_retrieval_budget.reserve_http("screening", lane["lane_id"])
        collector._executed_retrieval_lanes.extend([{**lane, "retrieval_cache": {"provider_status": "valid_empty"}} for lane in lanes])
        collector._slot_retrieval_summaries.append({"raw_candidates_by_lane": {lane["lane_id"]: 0 for lane in lanes}})
        return []
    collector._discover_subhypothesis_candidates = discover
    contract = {"sub_hypothesis_id": "SH1", "required_slots": ["performance", "quality", "reliability"],
                "slot_definitions": {name: dimension(name) for name in ("performance", "quality", "reliability")}}
    pool = collector._run_staged_candidate_search(papers, [contract], {})
    result = collector._build_candidate_discovery_ledger(pool, pool, [contract], {})
    assert sum(len(lanes) for lanes in calls) == 5
    assert len(result["records"]) == 350
    assert result["comparison_scope"]["deferred_candidates"] == 350
    assert not result["best_candidate_claim_allowed"]
    assert all(not record["negative_evidence_ids"] for record in result["records"])


def test_promotion_reserves_independent_same_class_challenger():
    papers = [paper("W1", "Method Alpha"), paper("W2", "Method Beta"), paper("W3", "Other Family")]
    registry = register_candidates([observation(source, name) for source, name in zip(papers, ["Method Alpha", "Method Beta", "Other Family"])], papers)
    for record in registry:
        record["screening_status_by_subhypothesis"] = {"SH1": "completed"}
    for source in papers:
        assess(source, next(record for record in registry if record["name"] in source["title"]))
    registry[-1]["candidate_kind"] = "another_family"
    ordered = promotion_order(registry, papers, "SH1", [dimension()], 2)
    assert len(ordered) == 2
    assert ordered[0]["candidate_id"] != ordered[1]["candidate_id"]


def test_independent_work_minimum_is_enforced_in_ledger():
    source = paper("W1", "Method Alpha", doi="10.1/shared")
    registry = register_candidates([observation(source, "Method Alpha")], [source])
    axis = {**dimension(), "minimum_independent_works": 2}
    assess(source, registry[0], axis)
    duplicate = deepcopy(source)
    duplicate["paperId"] = "W2"
    result = build_candidate_ledger(registry, [source, duplicate], {"SH1": [axis]}, [], [])
    assert not result["records"][0]["minimum_evidence_satisfied"]
    assert result["records"][0]["minimum_evidence_matrix"]["SH1:performance"]["requirement_satisfied"] is False


def test_separate_provider_instances_share_run_budget_and_rebinding(monkeypatch):
    from test_survey_openalex_unpaywall import OpenAlexAPI, _api_config
    config = _api_config()
    first = OpenAlexAPI(config)
    second = OpenAlexAPI(config)
    budget = RetrievalBudget(total=1, stages={"supplement": 1})
    bind_retrieval_budget(config, budget)
    assert provider_retrieval_budget(first) is budget
    assert provider_retrieval_budget(second) is budget
    first._wait_for_request_rate_slot = lambda: 0
    second._wait_for_request_rate_slot = lambda: 0
    calls = []
    def send(_adapter, request, **_kwargs):
        calls.append(request.url)
        response = requests.Response()
        response.status_code = 200
        response._content = b"{}"
        response.request = request
        response.url = request.url
        return response
    monkeypatch.setattr(requests.adapters.HTTPAdapter, "send", send)
    assert first._call_pyalex("search", lambda session: session.get("https://example.test/one"), budgeted_search=True) is not None
    assert second._call_pyalex("search", lambda session: session.get("https://example.test/two"), budgeted_search=True) is None
    assert len(calls) == 1
    next_budget = RetrievalBudget()
    bind_retrieval_budget(config, next_budget)
    assert provider_retrieval_budget(second) is next_budget


def test_budget_registry_releases_finished_run():
    import gc
    import weakref
    from src.pipeline import retrieval_budget
    config = SimpleNamespace()
    budget = RetrievalBudget()
    bind_retrieval_budget(config, budget)
    reference = weakref.ref(budget)
    del budget
    gc.collect()
    assert reference() is None
    assert id(config) not in retrieval_budget._run_budgets


@pytest.mark.parametrize("response", [SimpleNamespace(status_code=503), SimpleNamespace(status_code=200, content=b"invalid XML")])
def test_arxiv_failure_is_not_valid_zero(monkeypatch, response):
    from test_survey_openalex_unpaywall import api_call
    provider = api_call.ArxivAPI(SimpleNamespace(APIInfo=SimpleNamespace(arxiv_api_max_retry=1)))
    monkeypatch.setattr(api_call.requests, "get", lambda *_args, **_kwargs: response)
    with pytest.raises(requests.RequestException):
        provider.search_papers("method", provider_filter={"applied": True, "coverage": "exact", "policy": "hard_filter", "category_expression": "cat:cs.AI"})


def test_malformed_role_mapping_does_not_crash_registration():
    source = paper("W1", "Method Alpha")
    raw = {**observation(source, "Method Alpha"), "roles_by_subhypothesis": []}
    registry = register_candidates([raw], [source])
    assert registry[0]["roles_by_subhypothesis"] == {"SH1": "decision_candidate"}


@pytest.mark.parametrize("role", [["decision_candidate"], {"role": "comparator"}, None, 7, "invalid_role"])
def test_invalid_role_values_preserve_grounded_object_without_admitting_candidate(role):
    from src.pipeline.scientific_candidates import candidate_role, is_decision_candidate
    source = paper("W1", "Method Alpha")
    raw = {**observation(source, "Method Alpha"), "roles_by_subhypothesis": {"SH1": role}}
    registry = register_candidates([raw], [source])
    assert len(registry) == 1
    assert candidate_role(registry[0], "SH1") == "role_unresolved"
    assert not is_decision_candidate(registry[0])


def test_extraction_budget_deferral_is_not_a_failed_or_missing_response():
    papers = [paper("W" + str(index), "Method " + str(index)) for index in range(25)]
    submitted = []
    def extract(prompts, **_kwargs):
        submitted.extend(prompts)
        return [json.dumps({"candidates": [observation(papers[0], "Method 0")]}) for _prompt in prompts]
    collector = _collector(SimpleNamespace(batch_remote_chat=extract))
    collector.logger = _CapturingLogger()
    collector._candidate_retrieval_budget = RetrievalBudget(assessment_stages={"discovery": 2})
    registry = collector._extract_scientific_candidates(papers, [{"sub_hypothesis_id": "SH1", "question": "Compare methods"}])
    audit = collector._candidate_extraction_audit
    assert len(submitted) == 2
    assert len(registry) == 1
    assert audit["planned_batches"] == 4
    assert audit["submitted_batches"] == 2
    assert audit["deferred_batches"] == 2
    assert audit["failed_batches"] == 0
    assert audit["deferred_paper_ids"] == [source["paperId"] for source in papers[16:]]
    assert audit["status"] == "partial"
    assert not any("list index out of range" in message for message in collector.logger.messages)


def test_submitted_batch_missing_response_still_counts_as_failure():
    papers = [paper("W" + str(index), "Method " + str(index)) for index in range(9)]
    collector = _collector(SimpleNamespace(batch_remote_chat=lambda *_args, **_kwargs: [json.dumps({"candidates": []})]))
    collector.logger = _CapturingLogger()
    collector._candidate_retrieval_budget = RetrievalBudget()
    collector._extract_scientific_candidates(papers, [{"sub_hypothesis_id": "SH1"}])
    assert collector._candidate_extraction_audit["failed_batches"] == 1
    assert collector._candidate_extraction_audit["deferred_batches"] == 0


def test_role_clarification_skips_malformed_items_and_continues_valid_objects():
    papers = [paper("W1", "Method Alpha"), paper("W2", "Method Beta")]
    registry = register_candidates([{**observation(source, name), "candidate_role": "role_unresolved"}
        for source, name in zip(papers, ["Method Alpha", "Method Beta"])], papers)
    items = ["invalid item", {"candidate_id": registry[0]["candidate_id"], "sub_hypothesis_id": "SH1", "role": ["decision_candidate"]},
        {"candidate_id": registry[1]["candidate_id"], "sub_hypothesis_id": "SH1", "role": "decision_candidate"}]
    collector = _collector(SimpleNamespace(batch_remote_chat=lambda *_args, **_kwargs: [json.dumps({"roles": items})]))
    collector.logger = _CapturingLogger()
    collector._candidate_retrieval_budget = RetrievalBudget()
    collector._clarify_candidate_roles(registry, [{"sub_hypothesis_id": "SH1"}])
    assert registry[0]["roles_by_subhypothesis"]["SH1"] == "role_unresolved"
    assert registry[1]["roles_by_subhypothesis"]["SH1"] == "decision_candidate"


def test_relevance_screens_hundreds_of_objects_in_batches_with_original_topic():
    from src.pipeline.scientific_candidates import is_decision_candidate
    papers = [paper("W" + str(index), "Option " + str(index)) for index in range(346)]
    registry = register_candidates([observation(source, "Option " + str(index))
        for index, source in enumerate(papers)], papers)
    topic = "Choose suitable options for a novel target system, including transferable alternatives."
    payloads = []
    def screen(prompts, **kwargs):
        assert kwargs["desc"] == "Assessing Candidate Relevance"
        answers = []
        for prompt in prompts:
            data = json.loads(prompt.split("\n", 1)[1])
            payloads.append(data)
            answers.append(json.dumps({"relevance": [{"candidate_id": record["candidate_id"],
                "sub_hypothesis_id": "SH1", "relevant": record["name"] in {"Option 0", "Option 1"},
                "role": "decision_candidate" if record["name"] in {"Option 0", "Option 1"} else "background_entity",
                "reason": "Decision option" if record["name"] in {"Option 0", "Option 1"} else "Incidental source mention"}
                for record in data["candidates"]]}))
        return answers
    collector = _collector(SimpleNamespace(batch_remote_chat=screen))
    collector.logger = _CapturingLogger()
    collector._candidate_retrieval_budget = RetrievalBudget()
    collector._assess_candidate_relevance(registry, [{"sub_hypothesis_id": "SH1", "question": "Compare options"}], topic, {})
    assert len(payloads) == 15
    assert all(data["original_topic"] == topic and len(data["candidates"]) <= 24 for data in payloads)
    assert sum(len(data["candidates"]) for data in payloads) == 346
    assert all(record["sub_hypothesis_ids"] == ["SH1"] and record["discovery_evidence_spans"]
        for data in payloads for record in data["candidates"])
    assert len(registry) == 346
    assert sum(is_decision_candidate(record) for record in registry) == 2
    tasks = build_candidate_evidence_tasks({"sub_hypothesis_id": "SH1", "required_slots": ["performance"]}, registry)
    assert {task["candidate_id"] for task in tasks} == {record["candidate_id"] for record in registry if is_decision_candidate(record)}
    assert collector._candidate_retrieval_budget.snapshot()["assessment_relevance"] == 15
    assert collector._candidate_retrieval_budget.snapshot()["http_attempts"] == 0


def test_relevance_budget_deferrals_preserve_identity_and_do_not_admit_objects():
    from src.pipeline.scientific_candidates import is_decision_candidate
    papers = [paper("W" + str(index), "Option " + str(index)) for index in range(50)]
    registry = register_candidates([observation(source, "Option " + str(index))
        for index, source in enumerate(papers)], papers)
    def screen(prompts, **_kwargs):
        return [json.dumps({"relevance": [{"candidate_id": record["candidate_id"], "sub_hypothesis_id": "SH1",
            "relevant": False, "role": "background_entity", "reason": "Incidental mention"}
            for record in json.loads(prompt.split("\n", 1)[1])["candidates"]]}) for prompt in prompts]
    collector = _collector(SimpleNamespace(batch_remote_chat=screen))
    collector._candidate_retrieval_budget = RetrievalBudget(assessment_stages={"relevance": 1})
    collector._assess_candidate_relevance(registry, [{"sub_hypothesis_id": "SH1"}], "Compare methods", {})
    assert collector._candidate_relevance_audit["pair_counts"] == {
        "relevant": 0, "irrelevant": 24, "assessment_unavailable": 0, "deferred_budget": 26}
    assert collector._candidate_relevance_audit["deferred_batches"] == 2
    assert all(not is_decision_candidate(record) for record in registry)
    assert all(record["roles_by_subhypothesis"]["SH1"] == "decision_candidate" for record in registry[24:])
    ledger = build_candidate_ledger(registry, papers, {"SH1": [dimension()]}, [], [])
    assert ledger["comparison_scope"]["relevance_pending_objects"] == 26
    assert ledger["comparison_scope"]["relevance_excluded_objects"] == 24
    assert not ledger["best_candidate_claim_allowed"]


@pytest.mark.parametrize("answer", [
    {}, {"relevance": None}, {"relevance": "invalid"}, {"relevance": ["invalid"]},
    {"relevance": [{"sub_hypothesis_id": [], "relevant": False}]},
])
def test_unavailable_relevance_is_not_negative_or_irrelevant(answer):
    from src.pipeline.scientific_candidates import is_decision_candidate
    source = paper("W1", "Method Alpha")
    registry = register_candidates([observation(source, "Method Alpha")], [source])
    collector = _collector(SimpleNamespace(batch_remote_chat=lambda *_args, **_kwargs: [json.dumps(answer)]))
    collector._candidate_retrieval_budget = RetrievalBudget()
    collector._assess_candidate_relevance(registry, [{"sub_hypothesis_id": "SH1"}], "Compare methods", {})
    assert registry[0]["candidate_relevance_status"] == "assessment_unavailable"
    assert registry[0]["roles_by_subhypothesis"]["SH1"] == "decision_candidate"
    assert not is_decision_candidate(registry[0])
    assert collector._candidate_relevance_audit["pair_counts"]["irrelevant"] == 0


def test_relevance_rejects_cross_batch_ids_and_malformed_boolean():
    papers = [paper("W" + str(index), "Option " + str(index)) for index in range(3)]
    registry = register_candidates([observation(source, "Option " + str(index))
        for index, source in enumerate(papers)], papers)
    def screen(prompts, **_kwargs):
        return [json.dumps({"relevance": [{"candidate_id": registry[2]["candidate_id"], "sub_hypothesis_id": "SH1",
            "relevant": True, "role": "decision_candidate", "reason": "From another batch"},
            {"candidate_id": registry[0]["candidate_id"], "sub_hypothesis_id": "SH1",
            "relevant": "false", "reason": "Malformed boolean"}]}), json.dumps({"relevance": []})]
    collector = _collector(SimpleNamespace(batch_remote_chat=screen))
    collector.config.ModuleInfo.WorkCollector.candidate_relevance_batch_size = 2
    collector._candidate_retrieval_budget = RetrievalBudget()
    collector._assess_candidate_relevance(registry, [{"sub_hypothesis_id": "SH1"}], "Compare methods", {})
    assert all(record["candidate_relevance_status"] == "assessment_unavailable" for record in registry)


def test_relevance_admission_is_specific_to_each_subhypothesis():
    from src.pipeline.scientific_candidates import is_decision_candidate
    source = paper("W1", "Method Alpha")
    registry = register_candidates([{**observation(source, "Method Alpha"), "sub_hypothesis_ids": ["SH1", "SH2"]}], [source])
    answers = [{"candidate_id": registry[0]["candidate_id"], "sub_hypothesis_id": "SH1", "relevant": True,
        "role": "comparator", "reason": "Plausible transferable alternative; target evidence remains to be checked"},
        {"candidate_id": registry[0]["candidate_id"], "sub_hypothesis_id": "SH2", "relevant": False,
        "role": "mechanism_or_component", "reason": "Component rather than an option for the second decision"}]
    collector = _collector(SimpleNamespace(batch_remote_chat=lambda *_args, **_kwargs: [json.dumps({"relevance": answers})]))
    collector._candidate_retrieval_budget = RetrievalBudget()
    collector._assess_candidate_relevance(registry, [{"sub_hypothesis_id": "SH1"}, {"sub_hypothesis_id": "SH2"}], "Choose methods", {})
    assert is_decision_candidate(registry[0], "SH1")
    assert not is_decision_candidate(registry[0], "SH2")
    assert registry[0]["candidate_relevance_reasons"][0]["reason"] == answers[0]["reason"]
    assert build_candidate_evidence_tasks({"sub_hypothesis_id": "SH2", "required_slots": ["performance"]}, registry) == []


def test_missing_model_is_unavailable_not_budget_deferred_or_irrelevant():
    source = paper("W1", "Method Alpha")
    registry = register_candidates([observation(source, "Method Alpha")], [source])
    collector = _collector(None)
    collector._candidate_retrieval_budget = RetrievalBudget()
    collector._assess_candidate_relevance(registry, [{"sub_hypothesis_id": "SH1"}], "Choose methods", {})
    assert registry[0]["candidate_relevance_status"] == "assessment_unavailable"
    assert collector._candidate_relevance_audit["deferred_batches"] == 0
    assert collector._candidate_retrieval_budget.snapshot()["http_attempts"] == 0


def test_valid_ineligible_assessment_clears_deferral():
    source = paper("W1", "Method Alpha")
    registry = register_candidates([observation(source, "Method Alpha")], [source])
    registry[0]["assessment_status_by_subhypothesis"] = {"SH1": "deferred_budget"}
    chat = SimpleNamespace(batch_remote_chat=lambda *_args, **_kwargs: [json.dumps({"assessments": [{
        "dimension": "performance", "scope_pass": False, "evidence_role_pass": True, "minimum_evidence_pass": True,
        "evidence_spans": [{"source": "abstract", "text": source["abstract"]}]}]})])
    collector = _collector(chat)
    collector._candidate_retrieval_budget = RetrievalBudget()
    collector._assess_scientific_candidate_evidence([source], registry, {"SH1": [dimension()]}, phase="screening")
    assert registry[0]["assessment_status_by_subhypothesis"] == {}
    assert source["candidate_evidence_assessments"][0]["assessment_status"] == "assessed"
    assert not source["candidate_evidence_assessments"][0]["eligible"]


def test_screening_accepts_valid_fallback_after_primary_and_old_assessment_failure():
    source = paper("W1", "Method Alpha")
    registry = register_candidates([observation(source, "Method Alpha")], [source])
    assess(source, registry[0], scope_pass=False)
    source["candidate_evidence_assessments"][0]["assessment_status"] = "unavailable"
    chat = SimpleNamespace(batch_remote_chat=lambda prompts, **_kwargs: [json.dumps({"assessments": [{
        "dimension": "performance", "scope_pass": False, "evidence_role_pass": True, "minimum_evidence_pass": True,
        "evidence_spans": [{"source": "abstract", "text": source["abstract"]}]}]}) for _prompt in prompts])
    collector = _collector(chat)
    collector.logger = _CapturingLogger()
    collector._candidate_retrieval_budget = RetrievalBudget(total=2, stages={"screening": 1, "comparison": 0, "supplement": 1})
    collector._scientific_candidate_registry = registry
    collector._executed_retrieval_lanes = []
    collector._slot_retrieval_summaries = []
    def discover(rows, retrieval_round=0):
        lane = rows[0]["slot_recovery_tasks"][0]["retrieval_plan"]["query_lanes"][0]
        collector._candidate_retrieval_budget.reserve_http("screening", "primary")
        collector._candidate_retrieval_budget.reserve_http("supplement", "fallback")
        collector._executed_retrieval_lanes.extend([
            {**lane, "retrieval_cache": {"provider_status": "provider_failure"}},
            {**lane, "lane_id": lane["lane_id"] + ".fallback", "budget_phase": "supplement", "retrieval_cache": {"provider_status": "success"}},
        ])
        return [source]
    collector._discover_subhypothesis_candidates = discover
    contract = {"sub_hypothesis_id": "SH1", "required_slots": ["performance"], "slot_definitions": {"performance": dimension()}}
    collector._run_staged_candidate_search([], [contract], {})
    assert registry[0]["screening_status_by_subhypothesis"]["SH1"] == "completed"
    assert registry[0]["promoted_subhypothesis_ids"] == ["SH1"]


def test_query_rewrite_is_separate_bounded_variant_without_rival_pollution():
    papers = [paper("W1", "Method Alpha"), paper("W2", "Method Beta")]
    registry = register_candidates([observation(papers[0], "Method Alpha"), observation(papers[1], "Method Beta")], papers)
    contract = {"sub_hypothesis_id": "SH1", "required_slots": ["performance"], "slot_definitions": {
        "performance": {"retrieval_concepts": ["Method Alpha fixed result", "replicated effect", "independent measurement"], "meaning": "Measured comparative performance"}}}
    canonical = build_candidate_evidence_tasks(contract, registry, max_tasks=2)
    rewritten = build_candidate_evidence_tasks(contract, registry, max_tasks=2, query_rewrite=True)
    assert len(rewritten) == 2
    for task, original in zip(rewritten, canonical):
        lanes = task["retrieval_plan"]["query_lanes"]
        assert len(lanes) == 1
        assert lanes[0]["query"] != original["retrieval_plan"]["query_lanes"][0]["query"]
        assert lanes[0]["budget_phase"] == "supplement"
        assert lanes[0]["query_variant_id"] == "rewrite_1"
        if "Method Beta" in lanes[0]["query"]:
            assert "Method Alpha" not in lanes[0]["query"]


def test_long_evidence_purpose_survives_execution_query_compiler():
    source = paper("W1", "Method Alpha")
    registry = register_candidates([observation(source, "Method Alpha")], [source])
    contract = {"sub_hypothesis_id": "SH1", "required_slots": ["performance"], "slot_definitions": {
        "performance": {"retrieval_concepts": ["replicated quantitative performance measurements with independent controls across multiple laboratories and conditions"]}}}
    tasks = build_candidate_evidence_tasks(contract, registry, max_tasks=1)
    collector = _collector(SimpleNamespace())
    lane = collector._slot_recovery_task_lanes([{**contract, "slot_recovery_tasks": tasks}])[0]
    assert "replicated quantitative performance" in lane["query"]
    assert len(lane["query"].split()) <= 12


def test_supplement_gap_closure_cancels_pending_alias_request():
    source = paper("W1", "Method Alpha Legacy Alpha")
    registry = register_candidates([observation(source, "Method Alpha", ["Legacy Alpha"])], [source])
    assess(source, registry[0])
    added = paper("W2", "Method Alpha")
    collector = _collector(SimpleNamespace())
    collector.logger = _CapturingLogger()
    collector._scientific_candidate_registry = registry
    collector._executed_retrieval_lanes = []
    collector._slot_retrieval_summaries = []
    collector.config.ModuleInfo.WorkCollector.candidate_comparison_batch_size = 1
    collector._candidate_retrieval_budget = RetrievalBudget(total=5, stages={"screening": 1, "comparison": 1, "supplement": 3})
    def assess_missing(papers, candidates, dimensions_by_sh, phase="comparison"):
        if phase == "supplement":
            for candidate in candidates:
                assess(next(item for item in papers if item["paperId"] == "W2"), candidate, dimension("counterevidence_search", required=False))
        return papers
    collector._assess_scientific_candidate_evidence = assess_missing
    phases = []
    def discover(rows, retrieval_round=0):
        lane = rows[0]["slot_recovery_tasks"][0]["retrieval_plan"]["query_lanes"][0]
        phase = lane["budget_phase"]
        phases.append(phase)
        collector._candidate_retrieval_budget.reserve_http(phase, lane["lane_id"])
        return [added] if phase == "supplement" else []
    collector._discover_subhypothesis_candidates = discover
    contract = {"sub_hypothesis_id": "SH1", "required_slots": ["performance"], "slot_definitions": {"performance": dimension()}}
    collector._run_staged_candidate_search([source], [contract], {})
    assert phases == ["comparison", "supplement"]
    assert collector._candidate_retrieval_budget.snapshot()["http_attempts"] == 2
    assert collector._candidate_stop_reason == "evidence_requirements_completed"


def test_saved_survey_refreshes_budget_after_additional_search_and_refreezes_ledger(tmp_path):
    from test_survey_revision_contract import SurveyGenerator, _Logger
    from src.pipeline.scientific_candidates import verify_candidate_ledger
    source = paper("W1", "Method Alpha")
    registry = register_candidates([observation(source, "Method Alpha")], [source])
    assess(source, registry[0])
    budget = RetrievalBudget()
    budget.reserve_http("discovery", "first")
    frozen = freeze_candidate_ledger(build_candidate_ledger(registry, [source], {"SH1": [dimension()]}, [], []))
    frozen["retrieval_budget"] = budget.snapshot()
    frozen = freeze_candidate_ledger(frozen)
    budget.reserve_http("supplement", "additional_query_search")
    generator = object.__new__(SurveyGenerator)
    generator.logger = _Logger()
    generator.survey_evidence_plan = {"scientific_candidate_comparison": {"retrieval_budget": frozen["retrieval_budget"]}}
    generator.work_analyzer = SimpleNamespace(work_collector=SimpleNamespace(_candidate_retrieval_budget=budget))
    generator.config = SimpleNamespace(BasicInfo=SimpleNamespace(
        save_path=str(tmp_path / "survey.md"), save_json_path=str(tmp_path / "survey.json"),
        topic="Generic comparison", debug=False, research_context={},
        subhypothesis_retrieval={"candidate_discovery": frozen}))
    generator.save_survey("Survey body", [])
    payload = json.loads((tmp_path / "survey.json").read_text(encoding="utf-8"))
    result = payload["subhypothesis_retrieval"]["candidate_discovery"]
    assert result["retrieval_budget"]["http_attempts"] == 2
    assert payload["survey_evidence_plan"]["scientific_candidate_comparison"]["retrieval_budget"]["http_attempts"] == 2
    assert verify_candidate_ledger(result)


def test_partial_effective_evidence_prevents_false_low_yield_stop():
    source = paper("W1", "Method Alpha")
    registry = register_candidates([observation(source, "Method Alpha")], [source])
    assess(source, registry[0], dimension("feasibility"))
    collector = _collector(SimpleNamespace())
    collector.logger = _CapturingLogger()
    collector._scientific_candidate_registry = registry
    collector._executed_retrieval_lanes = []
    collector._slot_retrieval_summaries = []
    collector.config.ModuleInfo.WorkCollector.candidate_comparison_batch_size = 1
    collector.config.ModuleInfo.WorkCollector.candidate_low_yield_batches = 1
    collector._candidate_retrieval_budget = RetrievalBudget()
    def assess_new(papers, candidates, dimensions_by_sh, phase="comparison"):
        for item in papers:
            if item["paperId"] != "W1" and not item.get("candidate_evidence_assessments"):
                for candidate in candidates:
                    for axis in dimensions_by_sh["SH1"]:
                        assess(item, candidate, axis)
        return papers
    collector._assess_scientific_candidate_evidence = assess_new
    calls = []
    def discover(rows, retrieval_round=0):
        lane = rows[0]["slot_recovery_tasks"][0]["retrieval_plan"]["query_lanes"][0]
        calls.append(lane)
        collector._candidate_retrieval_budget.reserve_http(lane["budget_phase"], lane["lane_id"])
        return [paper("W" + str(len(calls) + 1), "Method Alpha")]
    collector._discover_subhypothesis_candidates = discover
    definitions = {"feasibility": dimension("feasibility"),
        "performance": {**dimension(), "minimum_independent_works": 3},
        "quality": {**dimension("quality"), "minimum_independent_works": 3}}
    contract = {"sub_hypothesis_id": "SH1", "required_slots": list(definitions), "slot_definitions": definitions}
    collector._run_staged_candidate_search([source], [contract], {})
    assert len(calls) == 2
    assert collector._candidate_stop_reason == "search_variants_exhausted"


def test_concurrent_identical_requests_execute_once_without_persistent_cache():
    import threading
    import time
    collector = _collector(SimpleNamespace())
    collector.logger = _CapturingLogger()
    collector._candidate_retrieval_budget = RetrievalBudget(total=5, stages={"screening": 5})
    collector._candidate_request_results = {}
    collector._sh_retrieval_cache_lock_guard = threading.Lock()
    collector._sh_retrieval_cache_locks = {}
    calls = []
    def search(_lane):
        reserve_retrieval_http_attempt()
        calls.append(True)
        time.sleep(0.02)
        return [paper("W1", "Method Alpha")], True, "success"
    collector._execute_query_lane_unbudgeted = search
    def execute(index):
        return collector._execute_query_lane_with_status({"lane_id": str(index), "provider": "openalex", "query": "Method Alpha", "budget_phase": "screening"})
    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(execute, range(20)))
    assert len(calls) == 1
    assert all(result[0][0]["paperId"] == "W1" for result in results)
    assert collector._candidate_retrieval_budget.snapshot()["http_attempts"] == 1
    assert collector._candidate_retrieval_budget.snapshot()["request_reuse_hits"] == 19
