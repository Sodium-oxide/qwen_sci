from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from src.pipeline.candidate_discovery_queries import broaden_discovery_lane
from src.pipeline.retrieval_budget import RetrievalBudget, reserve_retrieval_http_attempt
from src.pipeline.retrieval_lanes import build_candidate_discovery_tasks
from test_sh_paper_semantic_assessment import _collector, _CapturingLogger


def contract(identifier="SH1"):
    return {"sub_hypothesis_id": identifier, "question": "Compare scientific methods for a rare target using related systems.",
            "scientific_scope": {"research_object": ["Rare Target"], "source_system": ["Related System"]},
            "required_slots": ["performance"], "slot_definitions": {"performance": {"retrieval_concepts": ["reliability", "ABC", "Named Method"]}}}


def plan(identifier="SH1"):
    return {"sub_hypothesis_id": identifier, "contexts": [
        {"level": "target_system", "term": "Rare Target", "reason": "The requested target"},
        {"level": "source_system", "term": "Related System", "reason": "Provides transferable evidence"},
        {"level": "solution_class", "term": "measurement systems", "reason": "Covers alternative methods"}],
        "concepts": [{"concept": name, "kind": kind, "reason": reason} for name, kind, reason in [
            ("reliability", "evaluation_term", "General evaluation attribute"),
            ("ABC", "ambiguous_abbreviation", "The acronym has multiple meanings"),
            ("Named Method", "distinctive_name", "Identifies a specific scientific method")]]}


def tasks(identifier="SH1", semantic_plan=None):
    return build_candidate_discovery_tasks(contract(identifier), project_context={}, include_arxiv=False,
                                          discovery_semantic_plan=semantic_plan)


def collector_with_budget(total=20, batch=4, chat=None):
    collector = _collector(chat)
    collector.logger = _CapturingLogger()
    collector._candidate_retrieval_budget = RetrievalBudget(total=total, stages={"discovery": total, "supplement": 0})
    collector.config.ModuleInfo.WorkCollector.candidate_discovery_batch_size = batch
    collector._candidate_request_results = {}
    collector._executed_retrieval_lanes = []
    collector._slot_retrieval_summaries = []
    return collector


def test_only_model_classified_names_are_searched_alone():
    compiled = tasks(semantic_plan=plan())[0]
    queries = [spec["query"] for spec in compiled["query_variants"]]
    assert "Named Method" in queries
    assert "Rare Target reliability" in queries and "Rare Target ABC" in queries
    assert "reliability" not in queries and "ABC" not in queries
    assert all(len(query.split()) <= 12 for query in queries)
    assert all(spec.get("discovery_context_ladder") == [] for spec in compiled["query_variants"] if spec.get("discovery_concept_kind") == "distinctive_name")


@pytest.mark.parametrize("semantic_plan", [None, {}, {"concepts": [{"concept": "Named Method", "kind": "distinctive_name"}]},
    {"concepts": [{"concept": "Named Method", "kind": ["distinctive_name"], "reason": "Malformed"}], "contexts": [{"level": "target_system", "term": [], "reason": "Malformed"}]}])
def test_missing_or_invalid_model_response_keeps_context(semantic_plan):
    compiled = tasks(semantic_plan=semantic_plan)[0]
    assert all(spec["query"].startswith(("Rare Target", "Related System")) for spec in compiled["query_variants"])


def test_context_ladder_never_degrades_to_bare_property():
    lane = next(lane for lane in tasks(semantic_plan=plan())[0]["retrieval_plan"]["query_lanes"] if lane.get("discovery_concept") == "reliability")
    source = broaden_discovery_lane(lane)
    broad = broaden_discovery_lane(source)
    assert source["query"] == "Related System reliability"
    assert broad["query"] == "measurement systems reliability"
    assert broaden_discovery_lane(broad) is None
    assert len({lane["lane_id"], source["lane_id"], broad["lane_id"]}) == 3


def test_production_discovery_calls_llm_and_records_semantic_reasons():
    calls = []
    def chat(prompts, **kwargs):
        calls.append(kwargs["desc"])
        return [json.dumps({"plans": [plan()]})]
    collector = collector_with_budget(chat=SimpleNamespace(batch_remote_chat=chat))
    row = {**contract(), "candidate_discovery_tasks": tasks(), "slot_recovery_tasks": []}
    collector._prepare_candidate_discovery_queries([row])
    collector._prepare_candidate_discovery_queries([row])
    assert calls == ["Planning Candidate Discovery Queries"]
    task = row["candidate_discovery_tasks"][0]
    assert task["discovery_semantic_status"] == "model_classified"
    named = next(spec for spec in task["query_variants"] if spec.get("discovery_concept") == "Named Method")
    assert named["query"] == "Named Method" and named["discovery_semantic_reason"]
    assert collector._candidate_retrieval_budget.snapshot()["assessment_discovery"] == 1


def test_production_scheduler_rotates_sh_and_defers_without_entering_provider():
    collector = collector_with_budget(total=2, batch=2)
    rows = [{**contract(identifier), "candidate_discovery_tasks": tasks(identifier, plan(identifier)), "slot_recovery_tasks": []}
            for identifier in ("SH1", "SH2", "SH3")]
    for row in rows:
        row["candidate_discovery_tasks"][0]["discovery_planning_attempted"] = True
        for lane in row["candidate_discovery_tasks"][0]["retrieval_plan"]["query_lanes"]:
            lane["query"] += " " + row["sub_hypothesis_id"]
            lane["query_variant_terms"].append(row["sub_hypothesis_id"])
    submitted = []
    def execute(lane):
        reserve_retrieval_http_attempt()
        submitted.append(lane["sub_hypothesis_id"])
        return [{"paperId": lane["sub_hypothesis_id"], "title": "Result"}], True, "success"
    collector._execute_query_lane_unbudgeted = execute
    collector._discover_subhypothesis_candidates(rows)
    assert set(submitted) == {"SH1", "SH2"} and len(submitted) == 2
    assert collector._candidate_retrieval_budget.snapshot()["http_attempts"] == 2
    deferred = [lane for lane in collector._executed_retrieval_lanes if lane["retrieval_cache"]["provider_status"] == "deferred_budget"]
    assert deferred and all(not lane["retrieval_cache"]["network_request_made"] for lane in deferred)
    assert all(not summary["zero_result_lanes"] and not summary["failed_lanes"] for summary in collector._slot_retrieval_summaries)
    assert any(lane["sub_hypothesis_id"] == "SH3" for lane in deferred)


@pytest.mark.parametrize("status,count,expected", [("valid_empty", 0, 3), ("success", 1, 3), ("success", 5, 1), ("provider_failure", 0, 1)])
def test_context_expansion_is_conditional_and_bounded(status, count, expected):
    collector = collector_with_budget()
    lane = next(lane for lane in tasks(semantic_plan=plan())[0]["retrieval_plan"]["query_lanes"] if lane.get("discovery_concept") == "reliability")
    queries = []
    def execute(current):
        queries.append(current["query"])
        return ({**current, "retrieval_cache": {"provider_status": status}},
                [{"paperId": str(index), "title": "Result"} for index in range(count)])
    collector._execute_slot_recovery_lane = execute
    outcomes = collector._execute_candidate_discovery_lanes([lane], min_candidates=5, fallback_enabled=False)
    assert len(queries) == expected
    if expected == 3:
        assert queries == ["Rare Target reliability", "Related System reliability", "measurement systems reliability"]
    assert not outcomes[0][1]["deferred_lanes"]


def test_no_budget_does_not_submit_model_or_network_requests():
    collector = collector_with_budget(total=0, chat=SimpleNamespace(batch_remote_chat=lambda *_args, **_kwargs: pytest.fail("model must not run")))
    collector._execute_slot_recovery_lane = lambda *_args: pytest.fail("provider must not run")
    row = {**contract(), "candidate_discovery_tasks": tasks(), "slot_recovery_tasks": []}
    collector._discover_subhypothesis_candidates([row])
    assert collector._slot_retrieval_summaries[0]["deferred_lanes"]
    assert collector._slot_retrieval_summaries[0]["zero_result_lanes"] == []


def test_budgeted_expansion_has_fair_first_opportunity_across_sh():
    collector = collector_with_budget(total=6, batch=2)
    lanes = []
    for identifier in ("SH1", "SH2", "SH3"):
        lanes.extend([lane for lane in tasks(identifier, plan(identifier))[0]["retrieval_plan"]["query_lanes"]
                      if lane.get("discovery_concept") == "reliability"])
    submitted = []
    def execute(lane):
        collector._candidate_retrieval_budget.reserve_http("discovery", lane["lane_id"])
        submitted.append((lane["sub_hypothesis_id"], lane["discovery_context_level"]))
        return {**lane, "retrieval_cache": {"provider_status": "valid_empty"}}, []
    collector._execute_slot_recovery_lane = execute
    collector._execute_candidate_discovery_lanes(lanes, min_candidates=5, fallback_enabled=False)
    assert set(submitted[:3]) == {(identifier, "target_system") for identifier in ("SH1", "SH2", "SH3")}
    assert {identifier for identifier, _level in submitted} == {"SH1", "SH2", "SH3"}
    assert len(submitted) == 6


def test_semantic_planning_failure_is_auditable_and_does_not_repeat():
    calls = []
    def chat(*_args, **_kwargs):
        calls.append(True)
        return ["malformed response"]
    collector = collector_with_budget(chat=SimpleNamespace(batch_remote_chat=chat))
    row = {**contract(), "candidate_discovery_tasks": tasks(), "slot_recovery_tasks": []}
    collector._prepare_candidate_discovery_queries([row])
    collector._prepare_candidate_discovery_queries([row])
    assert len(calls) == 1
    assert row["candidate_discovery_tasks"][0]["discovery_semantic_status"] == "fallback_contextual"
    assert all(spec["query"].startswith(("Rare Target", "Related System"))
               for spec in row["candidate_discovery_tasks"][0]["query_variants"])


def test_discovery_retry_uses_supplement_and_stops_before_pending_provider_calls():
    collector = collector_with_budget(total=2, batch=1)
    collector._candidate_retrieval_budget.stages["supplement"] = 1
    rows = [{**contract(identifier), "candidate_discovery_tasks": tasks(identifier, plan(identifier)), "slot_recovery_tasks": []}
            for identifier in ("SH1", "SH2")]
    for row in rows:
        row["candidate_discovery_tasks"][0]["discovery_planning_attempted"] = True
    submitted = []
    def execute(lane):
        submitted.append(lane)
        reserve_retrieval_http_attempt()
        reserve_retrieval_http_attempt()
        return [], True, "valid_empty"
    collector._execute_query_lane_unbudgeted = execute
    collector._discover_subhypothesis_candidates(rows)
    assert len(submitted) == 1
    assert collector._candidate_retrieval_budget.snapshot()["http_attempts_by_stage"] == {"discovery": 1, "supplement": 1}
    assert all(lane.get("defer_reason") == "global_budget_exhausted" for lane in collector._executed_retrieval_lanes
               if lane["retrieval_cache"]["provider_status"] == "deferred_budget")


def test_initial_concept_views_precede_anchor_context_expansion():
    collector = collector_with_budget(total=3, batch=1)
    lanes = tasks(semantic_plan=plan())[0]["retrieval_plan"]["query_lanes"]
    queries = []
    def execute(lane):
        collector._candidate_retrieval_budget.reserve_http("discovery", lane["lane_id"])
        queries.append(lane["query"])
        return {**lane, "retrieval_cache": {"provider_status": "valid_empty"}}, []
    collector._execute_slot_recovery_lane = execute
    collector._execute_candidate_discovery_lanes(lanes, min_candidates=5, fallback_enabled=False)
    assert queries == ["Rare Target candidate", "Rare Target reliability", "Rare Target ABC"]
    assert "Related System candidate" not in queries


def test_executed_failure_can_use_fallback_despite_other_deferred_lanes():
    collector = collector_with_budget(total=4, batch=1)
    collector._candidate_retrieval_budget.stages = {"discovery": 1, "supplement": 3}
    lanes = tasks(semantic_plan=plan())[0]["retrieval_plan"]["query_lanes"]
    def execute(lane):
        collector._candidate_retrieval_budget.reserve_http("discovery", lane["lane_id"])
        return {**lane, "retrieval_cache": {"provider_status": "provider_failure"}}, []
    collector._execute_slot_recovery_lane = execute
    fallback_calls = []
    def fallback(usable):
        collector._candidate_retrieval_budget.reserve_http("supplement", "fallback")
        fallback_calls.append(usable)
        return {**usable[0], "lane_id": "fallback", "retrieval_cache": {"provider_status": "success"}}, [{"paperId": "W1", "title": "Recovered"}]
    collector._execute_slot_semantic_scholar_fallback = fallback
    outcomes = collector._execute_candidate_discovery_lanes(lanes, min_candidates=5, fallback_enabled=True)
    assert len(fallback_calls) == 1
    assert outcomes[0][1]["deferred_lanes"] and outcomes[0][1]["fallback_used"]
    assert outcomes[0][1]["failed_lanes"] and not outcomes[0][1]["zero_result_lanes"]
    assert collector._candidate_retrieval_budget.snapshot()["http_attempts"] == 2


def test_deferred_only_discovery_never_uses_fallback():
    collector = collector_with_budget(total=3)
    collector._candidate_retrieval_budget.stages = {"discovery": 0, "supplement": 3}
    collector._execute_slot_semantic_scholar_fallback = lambda *_args: pytest.fail("No executed query can trigger fallback")
    outcomes = collector._execute_candidate_discovery_lanes(tasks(semantic_plan=plan())[0]["retrieval_plan"]["query_lanes"],
        min_candidates=5, fallback_enabled=True)
    assert outcomes[0][1]["deferred_lanes"] and not outcomes[0][1]["fallback_used"]
