import json
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from types import SimpleNamespace

import pytest

from src.agents.survey_agent.modules.search_controller import SurveySearchController
from src.pipeline.retrieval_budget import (
    RetrievalBudget, RetrievalBudgetExceeded, model_request_scope, reserve_model_http_attempt,
    reserve_retrieval_http_attempt, retrieval_request_scope,
)
from src.pipeline.scientific_candidates import register_candidates, verify_candidate_ledger
from src.pipeline.survey_search_controller import (
    activate_candidates, admit_query, bounded_seed_selection, calibration_metrics,
    comparison_metrics, query_metrics,
    feedback_field_gaps, recover_feedback_fields, recover_query_context_level,
)
from src.pipeline.survey_response_normalization import FormatBatch, record_list, slot_contributions
from test_sh_paper_semantic_assessment import _collector, _CapturingLogger


TOPIC = "Compare reliable measurement methods for the target system with reproducible performance."
SH = {"sub_hypothesis_id": "SH1", "question": TOPIC, "required_slots": ["performance"],
      "slot_definitions": {"performance": {"meaning": "Reported measurement performance",
          "minimum_evidence": "Quantitative measurement", "minimum_independent_works": 1}},
      "slot_recovery_tasks": [{"slot_name": "performance"}]}


@pytest.mark.parametrize("raw,expected", [
    (" Solution Class ", "solution_class"),
    ("source-system", "source_system"),
    ("Target System", "target_system"),
])
def test_context_enum_spelling_recovers_without_semantic_inference(raw, expected):
    query_record = {"context_level": raw, "query": "method evidence"}
    normalized = recover_query_context_level(query_record)
    assert normalized["context_level"] == expected
    assert normalized["context_level_raw"] == raw
    assert normalized["context_level_recovery"] == "normalize_context_enum"
    assert query_record["context_level"] == raw


def test_unknown_context_label_still_fails_admission():
    normalized = recover_query_context_level({"context_level": "unsupported"})
    assert normalized["context_level"] == "unsupported"


def test_controller_hard_caps_results_per_query_at_32():
    collector, _calls = runtime()
    collector._candidate_retrieval_budget = RetrievalBudget()
    collector.config.ModuleInfo.WorkCollector.survey_results_per_query = 100
    controller = SurveySearchController(collector, TOPIC, {}, {}, [SH])
    assert controller.result_limit == 32


@pytest.mark.parametrize("level", ["target_system", "source_system", "solution_class"])
def test_dimension_context_repair_uses_model_judgment_and_preserves_query(level):
    class ContextModel(Model):
        def batch_remote_chat(self, prompts, desc, **options):
            if desc == "Repairing Survey Query Context":
                payload = json.loads(prompts[0][prompts[0].index('{"original_topic"'):])
                self.payloads.append((desc, payload))
                return [json.dumps({"queries": [{"repair_item_id": item["repair_item_id"],
                    "context_level": level, "context_reason": "Context assessed from the query and full topic"}
                    for item in payload["repair_items"]]})]
            outputs = super().batch_remote_chat(prompts, desc, **options)
            if desc == "Planning Survey Queries":
                for index, output in enumerate(outputs):
                    response = json.loads(output)
                    for item in response["queries"]:
                        item["context_level"] = "boundary_test"
                    outputs[index] = json.dumps(response)
            return outputs

    model = ContextModel()
    collector, _calls = runtime(model)
    collector._candidate_retrieval_budget = RetrievalBudget()
    controller = SurveySearchController(collector, TOPIC, {}, {}, [SH])
    planned = controller.planning(0)
    assert len(planned) == 3
    assert all(item["context_level"] == level for item in planned)
    assert all(item["context_level_raw"] == "boundary_test" for item in planned)
    assert all(item["context_level_recovery"] == "model_semantic_repair" for item in planned)
    assert all(entry["normalized_query"]["query"] == entry["query"]["query"]
               for entry in controller.query_audit if "normalized_query" in entry)
    assert controller.budget.snapshot()["model_assessment_requests"] == 2
    diagnostic = FormatBatch("planning", 2)
    unchanged = controller.repair_query_contexts([query("next", context="boundary_test")], diagnostic, 1)
    assert unchanged[0]["context_level"] == "boundary_test"
    assert controller.budget.snapshot()["model_assessment_requests"] == 2
    assert any("context_level:model_semantic_repair" in item["recoveries"] for item in controller.format_audit)


def test_context_repair_failure_is_bounded_and_keeps_valid_queries():
    class FailedRepairModel(Model):
        def batch_remote_chat(self, prompts, desc, **options):
            if desc == "Repairing Survey Query Context":
                return [None]
            return super().batch_remote_chat(prompts, desc, **options)

    collector, _calls = runtime(FailedRepairModel())
    collector._candidate_retrieval_budget = RetrievalBudget()
    controller = SurveySearchController(collector, TOPIC, {}, {}, [SH])
    diagnostic = FormatBatch("planning", 1)
    queries = [query("good"), *[query(f"bad{index}", context="boundary_test") for index in range(40)]]
    normalized = controller.repair_query_contexts(queries, diagnostic, 0)
    assert normalized == queries
    assert controller.prompt_audit[-1]["submitted_items"] == 32
    assert controller.prompt_audit[-1]["unresolved_items"] == 40
    assert admit_query(normalized[0], [SH], TOPIC, [])[1] == "admitted"
    assert admit_query(normalized[1], [SH], TOPIC, [])[1] == "invalid_context"


def query(identifier, context="target_system", phrase="target system measurement", **updates):
    return {"query_id": identifier, "sub_hypothesis_id": "SH1", "query": phrase,
        "purpose": "Discover reliable measurement alternatives", "context_level": context,
        "context_reason": "The class provides transferable measurement evidence",
        "expected_contribution": "Identify alternatives for comparison", "fit_score": 4,
        "purpose_score": 4, "context_score": 3,
        "term_origins": [{"term": phrase, "origin": "justified_generalization", "reason": "Measurement methods answer the stated selection question"}], **updates}


def paper(identifier="W1", name="Method Alpha", abstract=True):
    return {"paperId": identifier, "title": f"{name} measurement performance",
            "abstract": f"{name} reports reproducible measurement performance and limitations." if abstract else None}


def assessed_paper(identifier, name="Method Alpha", value=4):
    result = paper(identifier, name)
    result["project_relevance"] = {"assessment_status": "assessed", "relevance_score": value}
    result["sh_semantic_assessments"] = [{"sub_hypothesis_id": "SH1", "assessment_status": "assessed",
        "semantic_relevance_score": value, "recommended_graph_role": "evidence_seed", "evidence_spans": [{"source": "abstract", "text": result["abstract"]}]}]
    return result


class Model:
    def __init__(self, objects=2, relevant=True, evidence=True, feedback=True):
        self.objects, self.relevant, self.evidence, self.feedback = objects, relevant, evidence, feedback
        self.payloads = []

    def batch_remote_chat(self, prompts, desc, **kwargs):
        outputs = []
        for prompt in prompts:
            payload = json.loads(prompt[prompt.index('{"original_topic"'):])
            self.payloads.append((desc, payload))
            assert payload["original_topic"] == TOPIC
            if desc == "Planning Survey Queries":
                outputs.append(json.dumps({"queries": [query("q1"), query("q2", "solution_class", "measurement methods comparison"), query("q3", phrase="target system reliability")]}))
            elif desc == "Reviewing Survey Search Feedback":
                round_index = payload["round"]
                assert payload["query_history"]
                assert payload["paper_results"] or not payload["registered_objects"]
                queries = [query(f"f{round_index}.{index}", phrase=f"measurement methods alternative {round_index} {index}", action="compare_alternative",
                    feedback_reason="Independent alternatives lack complete evidence", feedback_references=["q1"]) for index in range(2)] if self.feedback else []
                outputs.append(json.dumps({"queries": queries, "decisions": [] if queries else [{"action": "stop", "reason": "No justified new query"}]}))
            elif desc == "Assessing Survey Papers and Objects":
                results = []
                for source in payload["papers"]:
                    value = 4 if self.relevant else 1
                    objects = [{"name": f"Method {index}", "aliases": [], "candidate_kind": "method",
                        "taxonomic_level": "method_family", "sub_hypothesis_ids": ["SH1"],
                        "roles_by_subhypothesis": {"SH1": "decision_candidate"}, "role_reason": "Selectable measurement method",
                        "evidence_spans": [{"source": "abstract", "text": source["abstract"]}],
                        "dimension_assessments": [{"sub_hypothesis_id": "SH1", "dimension": "performance", "scope_pass": True,
                            "evidence_role_pass": True, "minimum_evidence_pass": self.evidence, "stance": "supporting",
                            "evidence_spans": [{"source": "abstract", "text": source["abstract"]}]}]} for index in range(self.objects)]
                    results.append({"paper_id": source["paper_id"], "project_score": value, "project_reason": "Task match" if self.relevant else "Lexical overlap only",
                        "sh_assessments": [{"sub_hypothesis_id": "SH1", "semantic_relevance_score": value,
                            "overall_relation": "method" if self.relevant else "irrelevant", "reason": "Measurement comparison",
                            "recommended_graph_role": "evidence_seed", "evidence_spans": [{"source": "abstract", "text": source["abstract"]}]}],
                        "scientific_objects": objects})
                outputs.append(json.dumps({"papers": results}))
            elif desc == "Confirming Survey Candidate Relevance":
                outputs.append(json.dumps({"candidates": [{"candidate_id": record["candidate_id"], "assessments": [
                    {"sub_hypothesis_id": "SH1", "project_score": 4, "sh_score": 4, "candidate_role": "decision_candidate", "reason": "Grounded option"}]} for record in payload["candidates"]]}))
            else:
                raise AssertionError(desc)
        return outputs


def runtime(model=None, objects=2, provider_status="success", missing_abstract=False):
    collector = _collector(model or Model(objects=objects))
    settings = collector.config.ModuleInfo.WorkCollector
    del settings.survey_search_strategy
    settings.max_seed_paper_num = 18
    settings.min_seed_papers_per_sh = 2
    settings.sh_retrieval_cache_enabled = False
    collector.logger = _CapturingLogger()
    calls = []

    def search(lane):
        calls.append(deepcopy(lane))
        reserve_retrieval_http_attempt(collector._candidate_retrieval_budget, lane["query"])
        source = paper("W1", "Method 0", abstract=not missing_abstract)
        source["abstract"] = " ".join(f"Method {index} reports reproducible performance." for index in range(objects)) if not missing_abstract else None
        second = {**source, "paperId": "W2", "title": source["title"] + " independent replication"}
        return [source, second], provider_status in {"success", "valid_empty"}, provider_status

    collector._execute_query_lane_unbudgeted = search
    collector._store_subhypothesis_retrieval_artifact = lambda artifact: setattr(collector, "subhypothesis_retrieval_artifact", artifact)
    collector._initialize_sh_graph_provenance = lambda *_args: None
    return collector, calls


def test_default_controller_filters_early_and_keeps_hard_limits():
    collector, calls = runtime(objects=120)
    selected, selection = collector._collect_sh_seed_candidates(TOPIC, {}, {}, [SH])
    artifact = collector.subhypothesis_retrieval_artifact
    ledger = artifact["candidate_discovery"]
    assert len(selected) == 2
    assert len(ledger["records"]) == 120
    assert artifact["comparison_metrics"]["active_pairs"] <= 3
    assert artifact["comparison_metrics"]["all_relevant_pairs"] == 120
    assert artifact["comparison_metrics"]["relevant_holdout_pairs"] >= 117
    assert len(calls) == 3
    assert ledger["stop_reason"] == "seed_pool_ready"
    assert verify_candidate_ledger(ledger)
    assert selection["effective_seed_budget"] == 18
    assert collector._candidate_retrieval_budget.snapshot()["model_assessment_requests"] == 7
    assert all(source["retrieval_provenance"] for source in selected)


def test_irrelevant_source_objects_never_get_search_budget():
    collector, calls = runtime(Model(objects=3, relevant=False, feedback=False), objects=3)
    selected, _selection = collector._collect_sh_seed_candidates(TOPIC, {}, {}, [SH])
    assert not selected
    artifact = collector.subhypothesis_retrieval_artifact
    assert artifact["comparison_metrics"]["all_relevant_pairs"] == 0
    assert all(record["candidate_relevance_by_subhypothesis"]["SH1"] == "relevant" for record in artifact["candidate_discovery"]["records"])
    assert all(record["candidate_source_evidence_by_subhypothesis"]["SH1"]["status"] == "source_relevance_conflict" for record in artifact["candidate_discovery"]["records"])
    assert len(calls) == 3


def test_feedback_is_result_driven_and_limited_to_six_queries():
    model = Model(objects=3, evidence=False)
    collector, calls = runtime(model, objects=3)
    collector.config.ModuleInfo.WorkCollector.survey_queries_per_sh = 6
    collector.config.ModuleInfo.WorkCollector.survey_logical_query_limit = 36
    collector._collect_sh_seed_candidates(TOPIC, {}, {}, [SH])
    ledger = collector.subhypothesis_retrieval_artifact["candidate_discovery"]
    assert len(calls) == 6
    assert ledger["search_controller"]["per_sh_calls"] == {"SH1": 6}
    assert any(desc == "Reviewing Survey Search Feedback" for desc, _payload in model.payloads)
    assert ledger["best_candidate_claim_allowed"] is False
    assert ledger["stop_reason"] == "query_budget_exhausted"


def test_missing_abstract_remains_unknown_not_zero():
    collector, _calls = runtime(Model(feedback=False), missing_abstract=True)
    selected, _selection = collector._collect_sh_seed_candidates(TOPIC, {}, {}, [SH])
    assert selected == []
    for source in collector.subhypothesis_retrieval_artifact["candidate_papers"]:
        assert source["project_relevance"]["relevance_score"] is None
        assert source["sh_semantic_assessments"][0]["semantic_relevance_score"] is None


@pytest.mark.parametrize("updates,reason", [
    ({"fit_score": True}, "invalid_scores"), ({"context_score": 2}, "query_quality_below_threshold"),
    ({"sub_hypothesis_id": "SH9"}, "unknown_SH"),
    ({"query": " "}, "missing_query_description"),
    ({"context_level": "unsupported"}, "invalid_context"),
])
def test_query_admission_validates_scores_identity_and_structure(updates, reason):
    assert admit_query(query("q", **updates), [SH], TOPIC, [])[1] == reason


@pytest.mark.parametrize("origins", [
    None,
    [],
    [{"term": "measurement", "origin": "original_topic"}],
    [{"term": "measuring", "origin": "original_topic"}],
    [{"term": "reproducibility", "origin": "SH", "source_id": "SH1"}],
    [{"term": "method selection", "origin": "SH", "source_id": "SH2"}],
    [{"term": "measurement", "origin": "observed_paper", "source_id": "unknown"}],
    [{"term": "measurement", "origin": "justified_generalization"}],
])
def test_query_provenance_is_preserved_without_blocking_semantic_discovery(origins):
    raw = query("q", phrase="target system measurement comparison", term_origins=origins)
    admitted, status = admit_query(raw, [SH, {"sub_hypothesis_id": "SH2", "question": "method selection"}], TOPIC, [])
    assert status == "admitted"
    assert admitted["term_origins"] == origins


@pytest.mark.parametrize("initial_queries", [
    [query("q1")],
    [query("q1"), query("q2", phrase="target system reliability")],
    [query("q1"), query("q2", "solution_class", "measurement alternatives", context_score=2)],
])
def test_initial_coverage_gaps_preserve_queries_and_execute_search(initial_queries):
    class IncompletePlanModel(Model):
        def batch_remote_chat(self, prompts, desc, **kwargs):
            if desc == "Planning Survey Queries":
                return [json.dumps({"queries": initial_queries}) for _prompt in prompts]
            return super().batch_remote_chat(prompts, desc, **kwargs)

    collector, calls = runtime(IncompletePlanModel(feedback=False))
    selected, _selection = collector._collect_sh_seed_candidates(TOPIC, {}, {}, [SH])
    artifact = collector.subhypothesis_retrieval_artifact
    assert len(selected) == 2
    expected_calls = sum(raw["context_score"] >= 3 for raw in initial_queries)
    assert len(calls) == expected_calls
    assert artifact["stop_reason"] != "query_plan_unavailable"
    audit = artifact["candidate_discovery"]["search_controller"]["query_admission_audit"]
    gaps = [record for record in audit if record.get("reason") == "missing_initial_perspectives"]
    assert len(gaps) == 1
    assert gaps[0]["admission_status"] == "advisory"
    assert gaps[0]["retained_queries"] == expected_calls


def test_query_metrics_separate_failures_unknown_and_valid_zero():
    assert query_metrics([], "SH1", set(), "provider_failure")["feedback_hint"] == "provider_failure"
    assert query_metrics([], "SH1", set(), "valid_empty")["feedback_hint"] == "broaden_context"
    assert query_metrics([], "SH1", set(), "valid_empty")["precision"] is None
    sources = [assessed_paper(f"W{index}", value=1) for index in range(5)]
    assert query_metrics(sources, "SH1", set(), "success")["feedback_hint"] == "narrow_scope"
    sources = [assessed_paper(f"W{index}") for index in range(5)]
    assert query_metrics(sources, "SH1", set(), "success")["feedback_hint"] == "switch_uncovered_question"


@pytest.mark.parametrize("status", ["success", "valid_empty"])
def test_valid_zero_results_prioritize_intersection_reduction_before_context_broadening(status):
    metrics = query_metrics([], "SH1", set(), status)
    guidance = metrics["revision_guidance"]
    assert guidance["preferred_action"] == "broaden_context"
    assert guidance["priority_order"][0] == "reduce_intersection"
    assert guidance["priority_order"][-1] == "broaden_context_preserving_purpose"
    assert guidance["scientific_absence_established"] is False
    assert metrics["precision"] is None


@pytest.mark.parametrize("status", ["provider_failure", "rate_limited", "timeout", "deferred_budget"])
def test_provider_failures_and_budget_deferrals_do_not_recommend_zero_result_relaxation(status):
    assert query_metrics([], "SH1", set(), status)["revision_guidance"] is None


def test_missing_assessments_do_not_recommend_zero_result_relaxation():
    metrics = query_metrics([paper()], "SH1", set(), "success")
    assert metrics["revision_guidance"] is None
    assert metrics["feedback_hint"] == "complete_assessment"


def test_zero_result_feedback_preserves_boolean_queries_design_and_existing_budgets():
    rewritten_query = '("optical sensor" OR "electrical sensor") calibration'
    design = {"essential_context": ["measurement sensor"],
        "alternative_groups": [["optical sensor", "electrical sensor"]],
        "post_retrieval_criteria": ["reproducibility", "statistical validation"],
        "relaxation_strategy": ["Separate alternative methods and remove optional evaluation conditions"]}

    class RelaxingModel(Model):
        def batch_remote_chat(self, prompts, desc, **kwargs):
            results = super().batch_remote_chat(prompts, desc, **kwargs)
            if desc == "Reviewing Survey Search Feedback":
                payload = self.payloads[-1][1]
                assert payload["search_semantics"]["unseparated_terms_operator"] == "AND"
                assert payload["search_semantics"]["alternative_operator"] == "OR"
                assert payload["search_semantics"]["length_policy"] == "advisory_preserve_complete_names"
                zero_result = next(entry for entry in payload["query_history"]
                    if entry["metrics"].get("revision_guidance"))
                assert zero_result["metrics"]["revision_guidance"]["priority_order"][0] == "reduce_intersection"
                return [json.dumps({"queries": [query("relaxed", "solution_class", rewritten_query,
                    action="broaden_context", feedback_references=[zero_result["query_id"]],
                    feedback_reason="Keep one calibration purpose; treat sensor methods as alternatives and assess reproducibility after retrieval",
                    query_design=design)]})]
            return results

    model = RelaxingModel()
    collector, calls = runtime(model)
    original_search = collector._execute_query_lane_unbudgeted

    def search(lane):
        if lane["query_id"] == "relaxed":
            return original_search(lane)
        calls.append(deepcopy(lane))
        reserve_retrieval_http_attempt(collector._candidate_retrieval_budget, lane["query"])
        return [], True, "valid_empty"

    collector._execute_query_lane_unbudgeted = search
    selected, _selection = collector._collect_sh_seed_candidates(TOPIC, {}, {}, [SH])
    artifact = collector.subhypothesis_retrieval_artifact
    assert len(selected) == 2
    assert len(calls) == 4
    assert calls[-1]["query"] == rewritten_query
    assert calls[-1]["query_design"] == design
    assert all(lane["provider"] == "openalex" for lane in calls)
    ledger = artifact["candidate_discovery"]
    assert ledger["stop_reason"] == "seed_pool_ready"
    admission = next(item for item in ledger["search_controller"]["query_admission_audit"]
        if item.get("query", {}).get("query_id") == "relaxed")
    assert admission["query"]["query_design"] == design
    assert admission["admission_status"] == "admitted"
    assert collector._candidate_retrieval_budget.snapshot()["http_attempts"] == 4
    assert any("Query relaxation guidance" in message for message in collector.logger.messages)
    assert any("Survey query design" in message for message in collector.logger.messages)


def test_query_design_does_not_impose_word_matching_or_length_gates():
    complete_name = " ".join(f"component{index}" for index in range(20))
    proposal = query("complete_name", phrase=complete_name, query_design={
        "essential_context": ["A semantic description rather than a literal query substring"],
        "post_retrieval_criteria": ["Reproducibility"]})
    admitted, reason = admit_query(proposal, [SH], TOPIC, [])
    assert reason == "admitted"
    assert admitted["query"] == complete_name
    assert admitted["query_design"] == proposal["query_design"]


def test_seed_budget_is_hard_and_low_scores_do_not_fill_quotas():
    sources = [assessed_paper(f"W{index}") for index in range(30)] + [assessed_paper("low", value=2)]
    selection = bounded_seed_selection(sources, [SH], [], limit=3, minimum=10)
    assert len(selection["selected_papers"]) == 3
    assert selection["minimum_seed_unmet_by_sh"] == {"SH1": 7}
    assert selection["effective_seed_budget"] == 3
    assert "low" not in {source["paperId"] for source in selection["selected_papers"]}


def test_actual_model_attempts_are_atomic_and_reservations_protect_assessment():
    budget = RetrievalBudget(assessment_limit=5)
    reserved = budget.reserve_model_capacity(3)
    lease = budget.reserve_model_capacity(1)

    def attempt(_index):
        try:
            with model_request_scope(budget, lease):
                reserve_model_http_attempt()
            return True
        except RetrievalBudgetExceeded:
            return False

    with ThreadPoolExecutor(max_workers=8) as executor:
        assert sum(executor.map(attempt, range(12))) == 2
    for _attempt in range(3):
        budget.charge_model_attempt(reserved)
    assert budget.snapshot()["model_assessment_requests"] == 5
    budget.release_model_capacity(lease)
    budget.release_model_capacity(reserved)
    with pytest.raises(RetrievalBudgetExceeded):
        budget.charge_model_attempt(lease)


def test_http_search_retries_and_out_of_scope_search_share_total_budget():
    budget = RetrievalBudget(total=4, stages={"primary": 2, "retry_fallback": 2})
    with retrieval_request_scope(budget, "primary", "query"):
        for _attempt in range(3):
            reserve_retrieval_http_attempt()
    reserve_retrieval_http_attempt(budget, "later_query_search")
    with pytest.raises(RetrievalBudgetExceeded):
        reserve_retrieval_http_attempt(budget, "overflow")
    assert budget.snapshot()["http_attempts_by_stage"] == {"primary": 2, "retry_fallback": 2}


def test_calibration_reports_only_measured_labels():
    assert calibration_metrics([True, True, False], [True, False, True])["precision"] == 0.5
    assert calibration_metrics([], [])["recall"] is None


def test_query_without_term_origins_can_discover_alternatives():
    raw = query("q", phrase="transferable measurement alternatives")
    del raw["term_origins"]
    assert admit_query(raw, [SH], TOPIC, [])[1] == "admitted"


def test_semantic_names_and_paraphrased_evidence_do_not_require_literal_matches():
    class SemanticModel(Model):
        def batch_remote_chat(self, prompts, desc, **kwargs):
            results = super().batch_remote_chat(prompts, desc, **kwargs)
            if desc == "Assessing Survey Papers and Objects":
                for index, result in enumerate(results):
                    parsed = json.loads(result)
                    summary = [{"source": "abstract", "text": "The study quantifies repeatable measurement results."}]
                    for source in parsed["papers"]:
                        for assessment in source["sh_assessments"]:
                            assessment["evidence_spans"] = summary
                        for object_index, obj in enumerate(source["scientific_objects"]):
                            obj["name"] = f"Canonical measurement family {object_index}"
                            obj["aliases"] = [f"Normalized method label {object_index}"]
                            obj["evidence_spans"] = summary
                            for assessment in obj["dimension_assessments"]:
                                assessment["evidence_spans"] = summary
                    results[index] = json.dumps(parsed)
            return results

    collector, _calls = runtime(SemanticModel())
    selected, _selection = collector._collect_sh_seed_candidates(TOPIC, {}, {}, [SH])
    assert len(selected) == 2
    ledger = collector.subhypothesis_retrieval_artifact["candidate_discovery"]
    assert len(ledger["records"]) == 2
    assert ledger["balance"]["unique_effective_evidence_count"] == 2
    assert all(record["candidate_identity_status"] == "model_semantic" for record in ledger["records"])
    assert all(span["verification_status"] == "model_semantic" for record in ledger["records"] for span in record["discovery_evidence_spans"])
    assert all(span["verification_status"] == "model_semantic" for source in selected for assessment in source["sh_semantic_assessments"] for span in assessment["evidence_spans"])


@pytest.mark.parametrize("invalid_plan", ["invalid JSON", json.dumps({"queries": None}), json.dumps({"queries": [{"query": "measurement"}]})])
def test_invalid_initial_plan_warns_and_recovers_in_bounded_feedback(invalid_plan):
    class RecoveringPlanModel(Model):
        def batch_remote_chat(self, prompts, desc, **kwargs):
            if desc == "Planning Survey Queries":
                return [invalid_plan for _prompt in prompts]
            if desc == "Reviewing Survey Search Feedback":
                return [json.dumps({"queries": query("recovered", action="broaden_context",
                    feedback_reason="Recover an invalid initial plan", feedback_references=["SH1"])}) for _prompt in prompts]
            return super().batch_remote_chat(prompts, desc, **kwargs)

    collector, calls = runtime(RecoveringPlanModel())
    collector.logger = _CapturingLogger()
    selected, _selection = collector._collect_sh_seed_candidates(TOPIC, {}, {}, [SH])
    assert len(selected) == 2
    assert len(calls) == 1
    assert any("format warning" in message for message in collector.logger.messages)
    assert collector._candidate_retrieval_budget.snapshot()["model_reserved"] == 0


def test_persistently_invalid_plan_returns_diagnostics_without_search_or_exception():
    class InvalidPlanModel(Model):
        def __init__(self):
            super().__init__()
            self.plan_calls = 0

        def batch_remote_chat(self, prompts, desc, **kwargs):
            self.plan_calls += len(prompts)
            return ["invalid JSON" for _prompt in prompts]

    model = InvalidPlanModel()
    collector, calls = runtime(model)
    collector.logger = _CapturingLogger()
    selected, _selection = collector._collect_sh_seed_candidates(TOPIC, {}, {}, [SH])
    assert selected == []
    assert calls == []
    assert model.plan_calls == 3
    assert collector.subhypothesis_retrieval_artifact["stop_reason"] == "query_plan_unavailable"
    assert any("format warning" in message for message in collector.logger.messages)


def test_query_is_not_rejected_for_sharing_a_word_with_an_irrelevant_object():
    collector, _calls = runtime()
    collector._candidate_retrieval_budget = RetrievalBudget(total=60, assessment_limit=80)
    controller = SurveySearchController(collector, TOPIC, {}, {}, [SH])
    controller.registry = [{"candidate_id": "irrelevant_prior", "aliases": ["measurement"],
        "candidate_relevance_by_subhypothesis": {"SH1": "irrelevant"}}]
    queries = controller.planning(0)
    assert len(queries) == 3
    assert all(record.get("admission_status") == "admitted" for record in controller.query_audit)


@pytest.mark.parametrize("field,value", [
    ("sh_assessments", None),
    ("scientific_objects", "invalid"),
    ("project_score", {}),
])
def test_malformed_assessment_fields_warn_and_preserve_retrieval_results(field, value):
    class MalformedAssessmentModel(Model):
        def batch_remote_chat(self, prompts, desc, **kwargs):
            results = super().batch_remote_chat(prompts, desc, **kwargs)
            if desc == "Assessing Survey Papers and Objects":
                for index, result in enumerate(results):
                    parsed = json.loads(result)
                    for source in parsed["papers"]:
                        source[field] = value
                    results[index] = json.dumps(parsed)
            return results

    collector, calls = runtime(MalformedAssessmentModel(feedback=False))
    collector.logger = _CapturingLogger()
    collector._collect_sh_seed_candidates(TOPIC, {}, {}, [SH])
    assert len(calls) == 3
    assert len(collector.subhypothesis_retrieval_artifact["candidate_papers"]) == 2
    assert any("format warning" in message for message in collector.logger.messages)


def test_assessment_array_response_is_recovered_without_derived_warning_fanout():
    class ArrayAssessmentModel(Model):
        def batch_remote_chat(self, prompts, desc, **kwargs):
            results = super().batch_remote_chat(prompts, desc, **kwargs)
            if desc == "Assessing Survey Papers and Objects":
                converted = []
                for result in results:
                    converted.append(json.dumps(json.loads(result)["papers"]))
                return converted
            return results

    collector, _calls = runtime(ArrayAssessmentModel(feedback=False))
    selected, _selection = collector._collect_sh_seed_candidates(TOPIC, {}, {}, [SH])
    assert len(selected) == 2
    audit = collector.subhypothesis_retrieval_artifact["format_normalization_audit"]
    assessment_audit = [batch for batch in audit if batch["stage"] == "assessment"]
    assert assessment_audit
    assert all(batch["recoveries"].get("response:paper_records_array_to_object") for batch in assessment_audit)
    assert all(not batch["visible_issues"] for batch in assessment_audit)
    assert not any("Survey format warning: stage=assessment" in message for message in collector.logger.messages)


def test_wrapped_reordered_url_ids_keep_seeds_and_save_alignment():
    class WrappedAssessmentModel(Model):
        def batch_remote_chat(self, prompts, desc, **kwargs):
            results = super().batch_remote_chat(prompts, desc, **kwargs)
            if desc == "Assessing Survey Papers and Objects":
                for index, result in enumerate(results):
                    records = list(reversed(json.loads(result)["papers"]))
                    for record in records:
                        record["paper_id"] = "https://api.openalex.org/works/" + record["paper_id"].lower()
                    results[index] = json.dumps({"data": {"results": records}})
            return results

    collector, _calls = runtime(WrappedAssessmentModel(feedback=False))
    selected, _selection = collector._collect_sh_seed_candidates(TOPIC, {}, {}, [SH])
    assert {source["paperId"] for source in selected} == {"W1", "W2"}
    audit = collector.subhypothesis_retrieval_artifact["assessment_alignment_audit"]
    assert len(audit) == 1
    assert audit[0]["collection_paths"] == ["$.data.results"]
    assert [record["returned_record_indices"] for record in audit[0]["expected_records"]] == [[1], [0]]
    assert audit[0]["returned_records"][0]["identity_fields_raw"] == {"paper_id": "https://api.openalex.org/works/w2"}
    assert audit[0]["parsed_response"]["data"]["results"][0]["paper_id"].endswith("w2")
    assert all(source["survey_assessment_alignment"]["status"] == "matched" for source in selected)
    assert not any("format warning: stage=assessment" in message for message in collector.logger.messages)


def test_successful_assessment_also_saves_expected_and_returned_record_alignment():
    collector, _calls = runtime(Model(feedback=False))
    collector._collect_sh_seed_candidates(TOPIC, {}, {}, [SH])
    audit = collector.subhypothesis_retrieval_artifact["assessment_alignment_audit"]
    assert len(audit) == 1
    assert audit[0]["collection_paths"] == ["$.papers"]
    assert {record["paper_id"] for record in audit[0]["expected_records"]} == {"W1", "W2"}
    assert all(record["status"] == "matched" for record in audit[0]["returned_records"])


def test_missing_paper_aggregates_all_sh_failures_and_preserves_other_paper():
    class MissingPaperModel(Model):
        def batch_remote_chat(self, prompts, desc, **kwargs):
            results = super().batch_remote_chat(prompts, desc, **kwargs)
            if desc == "Assessing Survey Papers and Objects":
                for index, result in enumerate(results):
                    records = [record for record in json.loads(result)["papers"] if record["paper_id"] != "W1"]
                    for record in records:
                        record["sh_assessments"] = [dict(record["sh_assessments"][0], sub_hypothesis_id=f"SH{number}")
                            for number in range(1, 6)]
                    results[index] = json.dumps({"papers": records})
            return results

    collector, _calls = runtime(MissingPaperModel())
    collector._candidate_retrieval_budget = RetrievalBudget(assessment_limit=20)
    hypotheses = [dict(SH, sub_hypothesis_id=f"SH{index}") for index in range(1, 6)]
    controller = SurveySearchController(collector, TOPIC, {}, {}, hypotheses)
    papers = [paper("W1"), paper("W2")]
    controller.assess(papers, None)
    assert papers[0]["survey_assessment_status"] == "assessment_unavailable"
    assert papers[1]["survey_assessment_status"] == "assessed"
    assert all(item["semantic_relevance_score"] is None for item in papers[0]["sh_semantic_assessments"])
    batch = controller.format_audit[0]
    assert [issue["reason"] for issue in batch["visible_issues"]] == ["assessment_alignment_incomplete"]
    assert len(batch["suppressed_issues"]) == 11
    assert len(papers[0]["format_issues"]) == 11
    assert not papers[1]["format_issues"]
    assert controller.assessment_alignment_audit[0]["missing_paper_ids"] == ["W1"]
    assert len([message for message in collector.logger.messages if "format warning" in message]) == 1


def test_missing_sh_does_not_hide_genuine_problem_in_another_sh():
    class MissingSHModel(Model):
        def batch_remote_chat(self, prompts, desc, **kwargs):
            results = super().batch_remote_chat(prompts, desc, **kwargs)
            if desc == "Assessing Survey Papers and Objects":
                for index, result in enumerate(results):
                    parsed = json.loads(result)
                    for record in parsed["papers"]:
                        record["sh_assessments"][0]["semantic_relevance_score"] = "unknown"
                    results[index] = json.dumps(parsed)
            return results

    collector, _calls = runtime(MissingSHModel())
    collector._candidate_retrieval_budget = RetrievalBudget(assessment_limit=20)
    controller = SurveySearchController(collector, TOPIC, {}, {}, [SH, dict(SH, sub_hypothesis_id="SH2")])
    controller.assess([paper("W1")], None)
    batch = controller.format_audit[0]
    assert {(issue["sub_hypothesis_id"], issue["reason"]) for issue in batch["visible_issues"]} == {
        ("SH1", "incomplete_assessment"), ("SH2", "missing_SH_assessment")}
    assert all(issue["sub_hypothesis_id"] == "SH2" for issue in batch["suppressed_issues"])


def test_invalid_json_saves_raw_response_and_only_one_visible_root_cause():
    class InvalidJSONModel(Model):
        def batch_remote_chat(self, prompts, desc, **kwargs):
            if desc == "Assessing Survey Papers and Objects":
                return ["{ truncated response" for _prompt in prompts]
            return super().batch_remote_chat(prompts, desc, **kwargs)

    collector, _calls = runtime(InvalidJSONModel())
    collector._candidate_retrieval_budget = RetrievalBudget(assessment_limit=20)
    controller = SurveySearchController(collector, TOPIC, {}, {}, [SH])
    controller.assess([paper("W1"), paper("W2")], None)
    assert [issue["reason"] for issue in controller.format_audit[0]["visible_issues"]] == ["invalid_or_missing_JSON"]
    assert controller.assessment_alignment_audit[0]["raw_response"] == "{ truncated response"
    assert controller.assessment_alignment_audit[0]["missing_paper_ids"] == ["W1", "W2"]


def test_assessment_audit_is_checkpointed_before_retrieval_finishes(tmp_path):
    collector, _calls = runtime(Model())
    collector.config.BasicInfo.base_dir = str(tmp_path)
    collector._candidate_retrieval_budget = RetrievalBudget(assessment_limit=20)
    controller = SurveySearchController(collector, TOPIC, {}, {}, [SH])
    controller.assess([paper("W1")], None)
    checkpoint = tmp_path / "survey_assessment_alignment.jsonl"
    saved = [json.loads(line) for line in checkpoint.read_text(encoding="utf-8").splitlines()]
    assert len(saved) == 1
    assert saved[0]["expected_records"][0]["paper_id"] == "W1"
    assert saved[0]["parsed_response"]["papers"][0]["paper_id"] == "W1"
    assert not saved[0]["visible_issues"]
    assert not getattr(collector, "subhypothesis_retrieval_artifact", None)
    controller.assess([paper("W2")], None)
    assert len(checkpoint.read_text(encoding="utf-8").splitlines()) == 2


def test_assessment_audit_write_failure_warns_once_and_keeps_valid_results(tmp_path):
    blocked = tmp_path / "not_a_directory"
    blocked.write_text("occupied", encoding="utf-8")
    collector, _calls = runtime(Model())
    collector.config.BasicInfo.base_dir = str(blocked)
    collector._candidate_retrieval_budget = RetrievalBudget(assessment_limit=20)
    controller = SurveySearchController(collector, TOPIC, {}, {}, [SH])
    for identifier in ("W1", "W2"):
        source = paper(identifier)
        controller.assess([source], None)
        assert source["survey_assessment_status"] == "assessed"
    assert len(controller.assessment_alignment_audit) == 2
    assert sum("audit checkpoint unavailable" in message for message in collector.logger.messages) == 1


def test_feedback_contract_violations_are_reported_once_per_batch():
    class MissingFeedbackModel(Model):
        def batch_remote_chat(self, prompts, desc, **kwargs):
            if desc == "Repairing Survey Feedback Structure":
                return [json.dumps({"queries": []}) for _prompt in prompts]
            if desc == "Reviewing Survey Search Feedback":
                return [json.dumps({"queries": [query("feedback_without_contract", action="broaden_context")]})
                    for _prompt in prompts]
            return super().batch_remote_chat(prompts, desc, **kwargs)

    collector, _calls = runtime(MissingFeedbackModel(objects=0))
    collector._candidate_retrieval_budget = RetrievalBudget(assessment_limit=20)
    controller = SurveySearchController(collector, TOPIC, {}, {}, [SH])
    controller.history = [{"query_id": "Q1", "sub_hypothesis_id": "SH1", "query": "target system"}]
    controller.papers = []
    controller.planning(1)
    planning_audit = [batch for batch in controller.format_audit if batch["stage"] == "planning"]
    assert planning_audit
    issues = [issue for batch in planning_audit for issue in batch["visible_issues"]]
    assert len(issues) == 1
    assert issues[0]["reason"] == "feedback_contract_violations"
    assert issues[0]["raw"]["count"] == 1
    assert not any(issue["reason"] == "missing_feedback_justification" for issue in issues)


def test_feedback_metadata_recovers_from_unique_decision_without_model_repair():
    class DecisionModel(Model):
        def batch_remote_chat(self, prompts, desc, **kwargs):
            if desc == "Reviewing Survey Search Feedback":
                return [json.dumps({"queries": [query("Q15")], "decisions": [{
                    "sub_hypothesis_id": "SH1", "action": "broaden_context",
                    "reason": "Q15 relaxes the restrictive context of Q1", "references": ["Q1"]}]})
                    for _prompt in prompts]
            raise AssertionError(desc)

    collector, _calls = runtime(DecisionModel(objects=0))
    collector._candidate_retrieval_budget = RetrievalBudget(assessment_limit=20)
    controller = SurveySearchController(collector, TOPIC, {}, {}, [SH])
    controller.history = [{"query_id": "Q1", "sub_hypothesis_id": "SH1", "query": "specific target"}]
    planned = controller.planning(1)
    assert len(planned) == 1
    assert planned[0]["feedback_references"] == ["Q1"]
    assert planned[0]["action"] == "broaden_context"
    assert controller.feedback_repair_attempts == 0
    assert "feedback_reason" not in controller.query_audit[0]["query"]
    assert controller.query_audit[0]["normalized_query"]["feedback_reason"]
    assert sum(batch["recoveries"].get("action:associated_decision_to_query", 0) for batch in controller.format_audit) == 1
    assert not any("Survey format warning" in message for message in collector.logger.messages)


@pytest.mark.parametrize("decisions", [
    [{"sub_hypothesis_id": "SH1", "query_ids": ["Q10"], "action": "broaden_context", "reason": "Relax", "references": ["Q1"]}],
    [{"sub_hypothesis_id": "SH1", "query_ids": ["Q10"], "action": "broaden_context", "reason": "Q1 failed so add Q10", "references": ["Q1"]}],
    [{"sub_hypothesis_id": "SH2", "query_ids": ["Q1"], "action": "broaden_context", "reason": "Relax", "references": ["Q1"]}],
    [{"sub_hypothesis_id": "SH1", "action": "broaden_context", "reason": "Q10 relaxes", "references": ["Q1"]}],
    [{"sub_hypothesis_id": "SH1", "query_ids": ["Q1"], "action": "broaden_context", "reason": "Relax", "references": ["Q1"]}] * 2,
])
def test_feedback_metadata_does_not_guess_ambiguous_or_wrong_query_links(decisions):
    recovered, fields = recover_feedback_fields(query("Q1"), decisions, {"Q1"})
    assert fields == []
    assert feedback_field_gaps(recovered, {"Q1"}) == ["action", "feedback_reason", "feedback_references"]


def test_feedback_recovery_preserves_valid_fields_and_rejects_unknown_action():
    original = query("Q2", action="seek_counterevidence", feedback_reason="Existing reason")
    decision = {"sub_hypothesis_id": "SH1", "query_id": "Q2", "action": "cover_gap",
                "reason": "Other reason", "references": ["Q1"]}
    recovered, fields = recover_feedback_fields(original, [decision], {"Q1"})
    assert fields == ["feedback_references"]
    assert recovered["action"] == "seek_counterevidence"
    assert recovered["feedback_reason"] == "Existing reason"
    incomplete, fields = recover_feedback_fields(query("Q2"), [decision], {"Q1"})
    assert "action" in feedback_field_gaps(incomplete, {"Q1"})
    assert "action" not in fields


def test_feedback_repair_is_bounded_and_only_updates_metadata():
    class RepairModel(Model):
        def __init__(self):
            super().__init__(objects=0)
            self.repairs = []

        def batch_remote_chat(self, prompts, desc, **kwargs):
            if desc == "Reviewing Survey Search Feedback":
                return [json.dumps({"queries": [query("needs_repair"), query("deferred_repair")], "decisions": []}) for _prompt in prompts]
            assert desc == "Repairing Survey Feedback Structure"
            payload = json.loads(prompts[0][prompts[0].index('{"original_topic"'):])
            self.repairs.append(payload)
            return [json.dumps({"queries": [{"repair_item_id": "0", "action": "compare_alternative",
                "feedback_reason": "Q1 lacks alternatives", "feedback_references": ["Q1"],
                "query": "MUST NOT REPLACE QUERY", "fit_score": 0}]})]

    model = RepairModel()
    collector, _calls = runtime(model)
    collector.config.ModuleInfo.WorkCollector.survey_feedback_repair_item_limit = 1
    collector._candidate_retrieval_budget = RetrievalBudget(assessment_limit=20)
    controller = SurveySearchController(collector, TOPIC, {}, {}, [SH])
    controller.history = [{"query_id": "Q1", "sub_hypothesis_id": "SH1", "query": "specific target"}]
    planned = controller.planning(1)
    assert len(planned) == 1
    assert planned[0]["query"] == "target system measurement"
    assert planned[0]["fit_score"] == 4
    assert len(model.repairs[0]["repair_items"]) == 1
    assert controller.planning(2) == []
    assert len(model.repairs) == 1
    assert collector._candidate_retrieval_budget.snapshot()["model_assessment_requests"] == 3
    assert collector._candidate_retrieval_budget.snapshot()["model_reserved"] == 0
    assert controller.planning_outcome["reason"] == "all_queries_rejected_by_feedback_contract"


def test_feedback_repair_respects_exhausted_model_budget():
    class NoRepairBudgetModel(Model):
        def batch_remote_chat(self, prompts, desc, **kwargs):
            assert desc == "Reviewing Survey Search Feedback"
            return [json.dumps({"queries": [query("missing_feedback")]})]

    collector, _calls = runtime(NoRepairBudgetModel())
    collector._candidate_retrieval_budget = RetrievalBudget(assessment_limit=1)
    controller = SurveySearchController(collector, TOPIC, {}, {}, [SH])
    assert controller.planning(1) == []
    assert controller.feedback_repair_attempts == 0
    assert controller.planning_outcome["reason"] == "all_queries_rejected_by_feedback_contract"


def test_parallel_planning_keeps_decisions_scoped_to_their_response(monkeypatch):
    from src.agents.survey_agent.modules import search_controller

    def two_batches(prefix, base, collections, measure, limit):
        return [dict(base, paper_results=[], registered_objects=[], evidence_ledger=[]) for _index in range(2)]

    class ScopedModel(Model):
        def batch_remote_chat(self, prompts, desc, **kwargs):
            assert desc == "Reviewing Survey Search Feedback"
            return [json.dumps({"queries": [query("same_id", phrase=f"measurement option {index}")],
                "decisions": [{"sub_hypothesis_id": "SH1", "query_ids": ["same_id"],
                    "action": "compare_alternative", "reason": f"Investigate option {index}",
                    "references": ["Q1"]}]}) for index, _prompt in enumerate(prompts)]

    monkeypatch.setattr(search_controller, "planning_batches", two_batches)
    collector, _calls = runtime(ScopedModel())
    collector._candidate_retrieval_budget = RetrievalBudget(assessment_limit=10)
    controller = SurveySearchController(collector, TOPIC, {}, {}, [SH])
    controller.history = [{"query_id": "Q1", "sub_hypothesis_id": "SH1", "query": "specific target"}]
    planned = controller.planning(1)
    assert len(planned) == 2
    assert planned[0]["feedback_reason"] == "Investigate option 0"
    assert planned[1]["feedback_reason"] == "Investigate option 1"
    assert planned[0]["query_id"] != planned[1]["query_id"]
    assert controller.feedback_repair_attempts == 0


@pytest.mark.parametrize("patches", [
    [{"repair_item_id": "0", "action": "broaden_context", "feedback_reason": "Relax", "feedback_references": ["invented"]}],
    [{"repair_item_id": "0", "action": "broaden_context", "feedback_reason": "Relax", "feedback_references": ["Q1"]}] * 2,
    [{"repair_item_id": "unknown", "action": "broaden_context", "feedback_reason": "Relax", "feedback_references": ["Q1"]}],
])
def test_invalid_repair_patches_preserve_unresolved_queries(patches):
    class InvalidRepairModel(Model):
        def batch_remote_chat(self, prompts, desc, **kwargs):
            if desc == "Reviewing Survey Search Feedback":
                return [json.dumps({"queries": [query("missing_fields")]})]
            assert desc == "Repairing Survey Feedback Structure"
            return [json.dumps({"queries": patches})]

    collector, _calls = runtime(InvalidRepairModel())
    collector._candidate_retrieval_budget = RetrievalBudget(assessment_limit=10)
    controller = SurveySearchController(collector, TOPIC, {}, {}, [SH])
    controller.history = [{"query_id": "Q1", "sub_hypothesis_id": "SH1", "query": "specific target"}]
    assert controller.planning(1) == []
    assert controller.query_audit[0]["admission_status"] == "missing_feedback_justification"
    audit = next(batch for batch in controller.format_audit if batch["stage"] == "planning")
    assert audit["issues"][0]["raw"]["violations"][0]["missing_fields"] == ["action", "feedback_reason", "feedback_references"]


def test_rejected_feedback_does_not_end_as_no_information_gain():
    class RejectedFeedbackModel(Model):
        def batch_remote_chat(self, prompts, desc, **kwargs):
            if desc == "Reviewing Survey Search Feedback":
                return [json.dumps({"queries": [query("needs_metadata")]}) for _prompt in prompts]
            if desc == "Repairing Survey Feedback Structure":
                return [json.dumps({"queries": []})]
            return super().batch_remote_chat(prompts, desc, **kwargs)

    collector, _calls = runtime(RejectedFeedbackModel(objects=0, relevant=False))
    collector._collect_sh_seed_candidates(TOPIC, {}, {}, [SH])
    artifact = collector.subhypothesis_retrieval_artifact
    assert artifact["stop_reason"] == "query_plan_unavailable"
    assert any("reason=all_queries_rejected_by_feedback_contract" in message for message in collector.logger.messages)


@pytest.mark.parametrize("response,expected", [
    ({"queries": []}, "no_queries_proposed"),
    ({"queries": [query("weak", fit_score=1)]}, "all_queries_filtered"),
    (None, "response_unavailable"),
])
def test_empty_planning_outcomes_are_distinguished(response, expected):
    class EmptyModel(Model):
        def batch_remote_chat(self, prompts, desc, **kwargs):
            return [json.dumps(response)]

    collector, _calls = runtime(EmptyModel())
    collector._candidate_retrieval_budget = RetrievalBudget(assessment_limit=10)
    controller = SurveySearchController(collector, TOPIC, {}, {}, [SH])
    assert controller.planning(1) == []
    assert controller.planning_outcome["reason"] == expected


def test_duplicate_feedback_query_ids_are_reassigned_and_history_ids_remain_references():
    class DuplicateFeedbackModel(Model):
        def batch_remote_chat(self, prompts, desc, **kwargs):
            if desc == "Reviewing Survey Search Feedback":
                return [json.dumps({"queries": [query("Q1", action="broaden_context",
                    feedback_reason="Relax the failed intersection", feedback_references=["Q1"])]})
                    for _prompt in prompts]
            return super().batch_remote_chat(prompts, desc, **kwargs)

    collector, _calls = runtime(DuplicateFeedbackModel(objects=0))
    collector._candidate_retrieval_budget = RetrievalBudget(assessment_limit=20)
    controller = SurveySearchController(collector, TOPIC, {}, {}, [SH])
    controller.history = [{"query_id": "Q1", "sub_hypothesis_id": "SH1", "query": "target system"}]
    controller.papers = []
    queries = controller.planning(1)
    assert len(queries) == 1
    assert queries[0]["query_id"] != "Q1"
    assert queries[0]["source_query_id"] == "Q1"
    assert queries[0]["query_id"] in controller.query_ids


@pytest.mark.parametrize("representation", ["4", 4.0, "4/5", {"score": "4"}])
def test_score_recovery_preserves_seeds_evidence_and_candidate_activation(representation):
    class AlternateScoreModel(Model):
        def batch_remote_chat(self, prompts, desc, **kwargs):
            results = super().batch_remote_chat(prompts, desc, **kwargs)
            for index, result in enumerate(results):
                parsed = json.loads(result)
                if desc == "Planning Survey Queries":
                    for entry in parsed["queries"]:
                        for field in ("fit_score", "purpose_score", "context_score"):
                            entry[field] = str(entry[field])
                elif desc == "Assessing Survey Papers and Objects":
                    for entry in parsed["papers"]:
                        entry["project_relevance_score"] = representation
                        del entry["project_score"]
                        for assessment in entry["sh_assessments"]:
                            assessment["sh_score"] = representation
                            del assessment["semantic_relevance_score"]
                elif desc == "Confirming Survey Candidate Relevance":
                    for entry in parsed["candidates"]:
                        for assessment in entry["assessments"]:
                            assessment["project_score"] = representation
                            assessment["sh_score"] = representation
                results[index] = json.dumps(parsed)
            return results

    collector, calls = runtime(AlternateScoreModel())
    selected, _selection = collector._collect_sh_seed_candidates(TOPIC, {}, {}, [SH])
    artifact = collector.subhypothesis_retrieval_artifact
    assert len(selected) == 2
    assert len(calls) == 3
    assert artifact["comparison_metrics"]["active_pairs"] == 2
    for source in selected:
        assert source["project_relevance"]["relevance_score"] == 4
        assessment = source["sh_semantic_assessments"][0]
        assert assessment["semantic_relevance_score"] == 4
        assert type(assessment["semantic_relevance_score"]) is int
        assert assessment["score_fields_raw"] == {"sh_score": representation}
        assert source["candidate_evidence_assessments"]
    for record in artifact["candidate_discovery"]["records"]:
        assert record["candidate_relevance_scores_by_subhypothesis"]["SH1"]["weighted_score"] == 80
    assert any("format recovery" in message for message in collector.logger.messages)
    assert not any("format warning" in message for message in collector.logger.messages)


@pytest.mark.parametrize("representation", [None, True, 3.7, 6, "unknown", {"confidence": 4}])
def test_unrecoverable_scores_keep_raw_values_and_do_not_become_seeds(representation):
    class UnknownScoreModel(Model):
        def batch_remote_chat(self, prompts, desc, **kwargs):
            results = super().batch_remote_chat(prompts, desc, **kwargs)
            if desc == "Assessing Survey Papers and Objects":
                for index, result in enumerate(results):
                    parsed = json.loads(result)
                    for entry in parsed["papers"]:
                        entry["project_score"] = representation
                        for assessment in entry["sh_assessments"]:
                            assessment["semantic_relevance_score"] = representation
                    results[index] = json.dumps(parsed)
            return results

    collector, _calls = runtime(UnknownScoreModel(feedback=False))
    selected, _selection = collector._collect_sh_seed_candidates(TOPIC, {}, {}, [SH])
    assert not selected
    artifact = collector.subhypothesis_retrieval_artifact
    for source in artifact["candidate_papers"]:
        assert source["survey_assessment_attempts"] <= 2
        assert source["project_relevance"]["relevance_score"] is None
        assessment = source["sh_semantic_assessments"][0]
        assert assessment["semantic_relevance_score"] is None
        issues = source["format_issues"]
        score_issues = [issue for issue in issues if issue["field"] in {"project_score", "sh_assessments"}]
        assert len(score_issues) == 2
        assert all(issue["paper_id"] == source["paperId"] for issue in score_issues)
        sh_issue = next(issue for issue in score_issues if issue["field"] == "sh_assessments")
        assert sh_issue["raw"] == {"semantic_relevance_score": representation}
        assert sh_issue["sub_hypothesis_id"] == "SH1"
        assert sh_issue["missing_fields"] == ["semantic_relevance_score"]


def test_conflicting_sh_scores_do_not_discard_other_papers_in_the_batch():
    class ConflictingScoreModel(Model):
        def batch_remote_chat(self, prompts, desc, **kwargs):
            results = super().batch_remote_chat(prompts, desc, **kwargs)
            if desc == "Assessing Survey Papers and Objects":
                for index, result in enumerate(results):
                    parsed = json.loads(result)
                    for entry in parsed["papers"]:
                        for assessment in entry["sh_assessments"]:
                            if entry["paper_id"] == "W1":
                                assessment["sh_score"] = 1
                            else:
                                assessment["semantic_relevance_score"] = "4/5"
                    results[index] = json.dumps(parsed)
            return results

    collector, _calls = runtime(ConflictingScoreModel(feedback=False))
    selected, _selection = collector._collect_sh_seed_candidates(TOPIC, {}, {}, [SH])
    assert [source["paperId"] for source in selected] == ["W2"]
    sources = {source["paperId"]: source for source in collector.subhypothesis_retrieval_artifact["candidate_papers"]}
    assert sources["W1"]["project_relevance"]["relevance_score"] == 4
    assessment = sources["W1"]["sh_semantic_assessments"][0]
    assert assessment["semantic_relevance_score"] is None
    assert assessment["score_fields_raw"] == {"semantic_relevance_score": 4, "sh_score": 1}
    assert sources["W2"]["sh_semantic_assessments"][0]["semantic_relevance_score"] == 4


def test_invalid_candidate_scores_do_not_remove_valid_paper_seeds():
    class InvalidConfirmationModel(Model):
        def batch_remote_chat(self, prompts, desc, **kwargs):
            results = super().batch_remote_chat(prompts, desc, **kwargs)
            if desc == "Confirming Survey Candidate Relevance":
                for index, result in enumerate(results):
                    parsed = json.loads(result)
                    for entry in parsed["candidates"]:
                        for assessment in entry["assessments"]:
                            assessment["sh_score"] = 3.7
                    results[index] = json.dumps(parsed)
            return results

    collector, _calls = runtime(InvalidConfirmationModel(feedback=False))
    selected, _selection = collector._collect_sh_seed_candidates(TOPIC, {}, {}, [SH])
    assert len(selected) == 2
    artifact = collector.subhypothesis_retrieval_artifact
    assert artifact["comparison_metrics"]["active_pairs"] == 0
    issues = [issue for batch in artifact["format_normalization_audit"]
        if batch["stage"] == "confirmation" for issue in batch["issues"]]
    assert issues
    assert all(issue["raw"]["sh_score"] == 3.7 for issue in issues)


def test_formatted_scores_cannot_replace_missing_abstract_evidence():
    class FormattedScoreModel(Model):
        def batch_remote_chat(self, prompts, desc, **kwargs):
            results = super().batch_remote_chat(prompts, desc, **kwargs)
            if desc == "Assessing Survey Papers and Objects":
                for index, result in enumerate(results):
                    parsed = json.loads(result)
                    for entry in parsed["papers"]:
                        entry["project_score"] = "4/5"
                        for assessment in entry["sh_assessments"]:
                            assessment["semantic_relevance_score"] = "4"
                    results[index] = json.dumps(parsed)
            return results

    collector, _calls = runtime(FormattedScoreModel(feedback=False), missing_abstract=True)
    selected, _selection = collector._collect_sh_seed_candidates(TOPIC, {}, {}, [SH])
    assert not selected
    for source in collector.subhypothesis_retrieval_artifact["candidate_papers"]:
        assert source["project_relevance"]["relevance_score"] is None
        assessment = source["sh_semantic_assessments"][0]
        assert assessment["assessment_status"] == "uncertain"
        assert assessment["semantic_relevance_score"] is None


def test_empty_seed_collection_warns_and_returns_without_download():
    collector, _calls = runtime()
    collector.logger = _CapturingLogger()
    collector.get_project_research_context = lambda _topic: {}
    collector._build_configured_subhypothesis_plan = lambda *_args: ({}, [SH])
    collector._subhypothesis_retrieval_enabled = lambda: True
    collector._collect_sh_seed_candidates = lambda *_args: ([], {})
    collector._candidate_stop_reason = "query_plan_unavailable"
    collector.data_manager = SimpleNamespace(_resolve_paper_reference_id=lambda source: source.get("paperId"))
    assert collector.collect_seed_papers(TOPIC) == []
    assert any("no eligible seed papers" in message for message in collector.logger.messages)


@pytest.mark.parametrize("raw", [
    [{"slot_name": "performance", "support_level": "partial", "reason": "Reported comparison"}],
    {"slot_name": "performance", "support_level": "partial", "reason": "Reported comparison"},
    {"performance": {"support_level": "partial", "reason": "Reported comparison"}},
    {"performance": "partial"},
    ["performance: partial"],
    [{"slot": "performance", "level": "partial", "explanation": "Reported comparison"}],
    {"performance": {"support_level": " PARTIAL "}},
])
def test_slot_contribution_shapes_recover_without_warning_or_inventing_support(raw):
    diagnostic = FormatBatch("assessment", 1)
    records, unresolved = slot_contributions(raw, {"performance"}, diagnostic, paper_id="W1", sub_hypothesis_id="SH1")
    assert len(records) == 1
    assert records[0]["slot_name"] == "performance"
    assert records[0]["support_level"] == "partial"
    assert unresolved == []
    assert diagnostic.issues == []
    logger = _CapturingLogger()
    diagnostic.publish(logger)
    assert not any("format warning" in message for message in logger.messages)


@pytest.mark.parametrize("raw", [
    ["performance"],
    {"performance": {"reason": "Needs investigation"}},
    [{"slot_name": "performance", "support_level": "unknown"}],
    [{"slot_name": "outside_contract", "support_level": "direct"}],
    {"performance": {"slot_name": "conflicting", "support_level": "direct"}},
])
def test_unresolved_contributions_preserve_raw_information_and_context(raw):
    diagnostic = FormatBatch("assessment", 1)
    records, unresolved = slot_contributions(raw, {"performance"}, diagnostic, paper_id="W1", sub_hypothesis_id="SH1")
    assert records == []
    assert unresolved
    assert all(issue["paper_id"] == "W1" and issue["sub_hypothesis_id"] == "SH1" for issue in diagnostic.issues)
    assert all(issue["raw"] is not None for issue in diagnostic.issues)


def test_keyed_response_records_preserve_identity_and_report_conflicts():
    diagnostic = FormatBatch("assessment", 1)
    records = record_list({"SH1": {"reason": "Reported result"}, "SH2": {"sub_hypothesis_id": "SH3"}},
        "sh_assessments", diagnostic, paper_id="W1")
    assert records == [{"sub_hypothesis_id": "SH1", "reason": "Reported result"}]
    assert diagnostic.issues[0]["reason"] == "conflicting_identity"


def test_recovery_and_data_loss_logs_are_bounded_and_full_audit_is_saved():
    class AlternateShapesModel(Model):
        def batch_remote_chat(self, prompts, desc, **kwargs):
            results = super().batch_remote_chat(prompts, desc, **kwargs)
            if desc == "Assessing Survey Papers and Objects":
                for index, result in enumerate(results):
                    parsed = json.loads(result)
                    for source in parsed["papers"]:
                        for assessment in source["sh_assessments"]:
                            assessment["candidate_slot_contributions"] = {"performance": "partial"}
                            assessment["evidence_spans"] = {"abstract": "The study compares measurement performance."}
                            if source["paper_id"] == "W2":
                                assessment["candidate_slot_contributions"] = ["performance"]
                                del assessment["reason"]
                    results[index] = json.dumps(parsed)
            return results

    collector, _calls = runtime(AlternateShapesModel(feedback=False))
    collector._collect_sh_seed_candidates(TOPIC, {}, {}, [SH])
    artifact = collector.subhypothesis_retrieval_artifact
    sources = {source["paperId"]: source for source in artifact["candidate_papers"]}
    contribution = sources["W1"]["sh_semantic_assessments"][0]["candidate_slot_contributions"]
    assert contribution == [{"slot_name": "performance", "support_level": "partial", "reason": ""}]
    assert sources["W2"]["sh_semantic_assessments"][0]["unresolved_slot_contributions"] == ["performance"]
    audit = [batch for batch in artifact["format_normalization_audit"] if batch["stage"] == "assessment"]
    recovery_logs = [message for message in collector.logger.messages if "format recovery: stage=assessment" in message]
    warning_logs = [message for message in collector.logger.messages if "format warning: stage=assessment" in message]
    assert len(recovery_logs) == len(audit)
    assert len(warning_logs) == len(audit)
    issues = [issue for batch in audit for issue in batch["issues"]]
    assert any(issue["paper_id"] == "W2" and issue["sub_hypothesis_id"] == "SH1"
        and issue.get("missing_fields") == ["reason"] for issue in issues)
    assert all("W2" in message and "SH1" in message and "reason" in message for message in warning_logs)


def test_successfully_recovered_contributions_emit_only_batch_info():
    class KeyedSlotsModel(Model):
        def batch_remote_chat(self, prompts, desc, **kwargs):
            results = super().batch_remote_chat(prompts, desc, **kwargs)
            if desc == "Assessing Survey Papers and Objects":
                for index, result in enumerate(results):
                    parsed = json.loads(result)
                    for source in parsed["papers"]:
                        for assessment in source["sh_assessments"]:
                            assessment["candidate_slot_contributions"] = {"performance": "partial"}
                    results[index] = json.dumps(parsed)
            return results

    collector, _calls = runtime(KeyedSlotsModel())
    selected, _selection = collector._collect_sh_seed_candidates(TOPIC, {}, {}, [SH])
    assert len(selected) == 2
    logs = collector.logger.messages
    assert len([message for message in logs if "format recovery: stage=assessment" in message]) == 1
    assert not any("format warning" in message for message in logs)
    assert all(source["sh_semantic_assessments"][0]["candidate_slot_contributions"][0]["support_level"] == "partial" for source in selected)


def test_diagnostic_console_samples_are_limited_without_losing_audit_details():
    diagnostic = FormatBatch("assessment", 1)
    for index in range(20):
        diagnostic.unresolved("semantic_relevance_score", "invalid_score", "unknown", paper_id=f"W{index}", sub_hypothesis_id="SH1")
    logger = _CapturingLogger()
    audit = diagnostic.publish(logger)
    assert len(logger.messages) == 1
    assert "omitted_details=12" in logger.messages[0]
    assert len(audit["issues"]) == 20


def test_malformed_object_in_valid_batch_cannot_abort_survey():
    class PartialModel(Model):
        def batch_remote_chat(self, prompts, desc, **kwargs):
            results = super().batch_remote_chat(prompts, desc, **kwargs)
            if desc == "Assessing Survey Papers and Objects":
                for index, result in enumerate(results):
                    parsed = json.loads(result)
                    for source in parsed["papers"]:
                        source["scientific_objects"].append({"sub_hypothesis_ids": ["SH1"], "evidence_spans": source["sh_assessments"][0]["evidence_spans"]})
                    results[index] = json.dumps(parsed)
            return results
    collector, _calls = runtime(PartialModel())
    selected, _selection = collector._collect_sh_seed_candidates(TOPIC, {}, {}, [SH])
    assert len(selected) == 2
    assert len(collector.subhypothesis_retrieval_artifact["candidate_discovery"]["records"]) == 2


def test_recovered_paper_assessment_invalidates_candidate_confirmation():
    class RecoveringModel(Model):
        def __init__(self):
            super().__init__(feedback=False)
            self.assessment_calls = 0

        def batch_remote_chat(self, prompts, desc, **kwargs):
            results = super().batch_remote_chat(prompts, desc, **kwargs)
            if desc == "Assessing Survey Papers and Objects":
                self.assessment_calls += 1
                if self.assessment_calls == 1:
                    for index, result in enumerate(results):
                        parsed = json.loads(result)
                        for source in parsed["papers"]:
                            source["sh_assessments"] = []
                        results[index] = json.dumps(parsed)
            return results
    model = RecoveringModel()
    collector, _calls = runtime(model)
    selected, _selection = collector._collect_sh_seed_candidates(TOPIC, {}, {}, [SH])
    assert len(selected) == 2
    assert model.assessment_calls == 2
    assert sum(desc == "Confirming Survey Candidate Relevance" for desc, _payload in model.payloads) == 2
    assert all(record["candidate_relevance_by_subhypothesis"]["SH1"] == "relevant" for record in collector.subhypothesis_retrieval_artifact["candidate_discovery"]["records"])


def test_excluded_source_cannot_promote_candidates_even_when_scores_are_high():
    class ExcludedModel(Model):
        def batch_remote_chat(self, prompts, desc, **kwargs):
            results = super().batch_remote_chat(prompts, desc, **kwargs)
            if desc == "Assessing Survey Papers and Objects":
                for index, result in enumerate(results):
                    parsed = json.loads(result)
                    for source in parsed["papers"]:
                        source["excluded"] = True
                    results[index] = json.dumps(parsed)
            return results
    collector, _calls = runtime(ExcludedModel(feedback=False))
    selected, _selection = collector._collect_sh_seed_candidates(TOPIC, {}, {}, [SH])
    assert not selected
    assert collector.subhypothesis_retrieval_artifact["comparison_metrics"]["all_relevant_pairs"] == 0


def test_feedback_contract_does_not_materialize_legacy_query_matrix():
    from src.pipeline.retrieval_lanes import build_subhypothesis_retrieval_plan
    from test_subhypothesis_evidence import _project_context, _comparative_contract
    context = _project_context()
    plan = build_subhypothesis_retrieval_plan(context, [_comparative_contract(context)], search_strategy="model_feedback")
    sh = plan["subhypotheses"][0]
    assert sh["validation"]["valid"] is True
    assert sh["candidate_discovery_tasks"] == []
    assert sh["candidate_discovery_lanes"] == []
    assert sh["slot_query_lanes"] == []
    assert sh["slot_recovery_tasks"]


def test_handoff_preserves_scores_holdouts_and_only_active_seed_roots():
    from src.pipeline.survey_handoff_projection import build_survey_idea_handoff_projection
    from src.pipeline.survey_idea_handoff import GapLedger, build_gap_ledger_payload
    from test_survey_idea_handoff_contract import _gap
    collector, _calls = runtime(objects=5)
    collector._collect_sh_seed_candidates(TOPIC, {}, {}, [SH])
    ledger = collector.subhypothesis_retrieval_artifact["candidate_discovery"]
    gaps = build_gap_ledger_payload(GapLedger(project_id="p", survey_run_id="r", project_context_fingerprint="ctx", gaps=[_gap()]))
    handoff = build_survey_idea_handoff_projection(gap_ledger=gaps, project_context={"original_topic": TOPIC}, survey_json={"subhypothesis_retrieval": {"candidate_discovery": ledger}})
    projected = handoff["scientific_candidates"]
    assert projected["comparison_metrics"]["all_relevant_pairs"] == 5
    roots = {projected["primary_candidate_id"], *projected["challenger_candidate_ids"]}
    assert len(roots) == 2
    for record in projected["records"]:
        assert record["candidate_relevance_scores_by_subhypothesis"]["SH1"]["weighted_score"] == 80
        assert record["candidate_source_evidence_by_subhypothesis"]["SH1"]["status"] == "eligible"
        assert record["candidate_admission_by_subhypothesis"]["SH1"] == "evidence_supported"
        if record["candidate_id"] in roots:
            assert record["active_status_by_subhypothesis"]["SH1"] == "active"
            assert record["root_seed_source_ids"]


def test_feedback_model_capacity_is_reserved_before_any_http():
    collector, calls = runtime()
    collector.config.ModuleInfo.WorkCollector.survey_model_request_limit = 4
    collector._collect_sh_seed_candidates(TOPIC, {}, {}, [SH])
    budget = collector._candidate_retrieval_budget.snapshot()
    assert budget["model_assessment_requests"] <= 4
    assert len(calls) <= 1
    assert budget["model_reserved"] == 0


def test_shared_queries_across_six_sh_keep_provenance_and_logical_limits():
    class MultiModel(Model):
        def batch_remote_chat(self, prompts, desc, **kwargs):
            results = super().batch_remote_chat(prompts, desc, **kwargs)
            for index, result in enumerate(results):
                payload = self.payloads[-len(prompts) + index][1]
                identifiers = [sh["sub_hypothesis_id"] for sh in payload["subhypotheses"]]
                parsed = json.loads(result)
                if "queries" in parsed:
                    parsed["queries"] = [{**raw, "query_id": sh_id + "." + raw["query_id"], "sub_hypothesis_id": sh_id,
                        **({"feedback_references": ["SH1.q1"]} if desc != "Planning Survey Queries" else {})} for sh_id in identifiers for raw in parsed["queries"]]
                if "papers" in parsed:
                    for source in parsed["papers"]:
                        source["sh_assessments"] = [{**assessment, "sub_hypothesis_id": sh_id} for sh_id in identifiers for assessment in source["sh_assessments"]]
                        for obj in source["scientific_objects"]:
                            obj["sub_hypothesis_ids"] = identifiers
                            obj["roles_by_subhypothesis"] = {sh_id: "decision_candidate" for sh_id in identifiers}
                            obj["dimension_assessments"] = [{**assessment, "sub_hypothesis_id": sh_id} for sh_id in identifiers for assessment in obj["dimension_assessments"]]
                if "candidates" in parsed:
                    for candidate in parsed["candidates"]:
                        candidate["assessments"] = [{**assessment, "sub_hypothesis_id": sh_id} for sh_id in identifiers for assessment in candidate["assessments"]]
                results[index] = json.dumps(parsed)
            return results
    collector, calls = runtime(MultiModel(objects=3, evidence=False), objects=3)
    collector.config.ModuleInfo.WorkCollector.survey_queries_per_sh = 6
    collector.config.ModuleInfo.WorkCollector.survey_logical_query_limit = 36
    subhypotheses = [{**deepcopy(SH), "sub_hypothesis_id": f"SH{index}"} for index in range(1, 7)]
    collector._collect_sh_seed_candidates(TOPIC, {}, {}, subhypotheses)
    artifact = collector.subhypothesis_retrieval_artifact
    state = artifact["candidate_discovery"]["search_controller"]
    assert state["logical_calls"] == 36
    assert set(state["per_sh_calls"].values()) == {6}
    assert len(calls) == 6
    assert {item["sub_hypothesis_id"] for item in artifact["candidate_papers"][0]["retrieval_provenance"]} == {f"SH{index}" for index in range(1, 7)}


def test_current_exclusion_overrides_historical_eligible_objects():
    class ChangedSourceModel(Model):
        def __init__(self):
            super().__init__(feedback=False)
            self.assessment_calls = 0

        def batch_remote_chat(self, prompts, desc, **kwargs):
            results = super().batch_remote_chat(prompts, desc, **kwargs)
            if desc == "Assessing Survey Papers and Objects":
                self.assessment_calls += 1
                if self.assessment_calls > 1:
                    for index, result in enumerate(results):
                        parsed = json.loads(result)
                        for source in parsed["papers"]:
                            source["excluded"] = True
                        results[index] = json.dumps(parsed)
            return results
    model = ChangedSourceModel()
    collector, _calls = runtime(model)
    selected, _selection = collector._collect_sh_seed_candidates(TOPIC, {}, {}, [SH, {**deepcopy(SH), "sub_hypothesis_id": "SH2"}])
    assert model.assessment_calls == 2
    assert not selected
    ledger = collector.subhypothesis_retrieval_artifact["candidate_discovery"]
    assert all(record["candidate_relevance_by_subhypothesis"]["SH1"] == "relevant" for record in ledger["records"])
    assert all(record["roles_by_subhypothesis"]["SH1"] == "decision_candidate" for record in ledger["records"])
    assert all(record["candidate_source_evidence_by_subhypothesis"]["SH1"]["status"] == "excluded" for record in ledger["records"])
    assert ledger["comparison_metrics"]["all_relevant_pairs"] == 0
    assert ledger["best_candidate_claim_allowed"] is False


def test_duplicate_work_does_not_duplicate_seed_role_lists():
    first, duplicate = assessed_paper("W1"), assessed_paper("W2")
    first["doi"] = duplicate["doi"] = "10.1000/shared"
    selection = bounded_seed_selection([first, duplicate], [SH], [], limit=18)
    assert len(selection["selected_papers"]) == len(selection["evidence_seed_papers"]) == 1
    assert selection["minimum_seed_counts_by_sh"] == {"SH1": 1}


@pytest.mark.parametrize("role", ["do_not_expand", "context_seed"])
def test_seed_selection_preserves_the_assessed_graph_role(role):
    source = assessed_paper("W1")
    source["sh_semantic_assessments"][0]["recommended_graph_role"] = role
    selection = bounded_seed_selection([source], [SH], [])
    assert selection["selected_papers"] == [source]
    assert selection["minimum_seed_counts_by_sh"]["SH1"] == 1
    assert selection["context_seed_papers"] == [source]
    assert source["seed_selection"]["graph_expansion_eligible"] is False
    assert source["sh_semantic_assessments"][0]["recommended_graph_role"] == role
