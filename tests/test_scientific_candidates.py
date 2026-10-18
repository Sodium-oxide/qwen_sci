from copy import deepcopy
import json

import pytest

from src.pipeline.scientific_candidates import (
    register_candidates, normalize_evidence_assessment, build_candidate_ledger,
    candidate_balance, freeze_candidate_ledger, verify_candidate_ledger, refresh_candidate_fulltext,
)
from src.pipeline.retrieval_lanes import build_candidate_evidence_tasks
from src.pipeline.evidence_coverage_ledger import select_sh_seed_candidates
from src.pipeline.survey_handoff_projection import build_survey_idea_handoff_projection
from src.agents.idea_agent.utils.workflow.mature_idea_sources import collect_mature_idea_sources
from src.agents.idea_agent.utils.workflow.gap_search_schedule import build_gap_screening_tasks
from src.agents.idea_agent.utils.mcts.idea_routes import IDEA_ROUTE_POLICIES


def paper(pid, name, *, doi=None):
    return {"paperId": pid, "title": name + " evaluation", "abstract": name + " reports stable performance and limitations.",
            **({"doi": doi} if doi else {})}


def observation(p, name, aliases=(), sh="SH1"):
    return {"name": name, "aliases": list(aliases), "paper_id": p["paperId"], "sub_hypothesis_ids": [sh],
            "candidate_kind": "method", "taxonomic_level": "method_family",
            "candidate_role": "decision_candidate",
            "evidence_spans": [{"source": "title", "text": p["title"]}]}


def dimension(name="performance", required=True):
    return {"slot_name": name, "retrieval_concepts": [name], "evidence_role": "DIRECT_OBSERVATION",
            "minimum_evidence": "Reported result", "admission_rule": "Grounded result", "required": required}


def assess(p, record, d=None, *, sh="SH1", stance="supporting", **kwargs):
    d = d or dimension()
    raw = {"scope_pass": True, "evidence_role_pass": True, "minimum_evidence_pass": True, "stance": stance,
           "evidence_spans": [{"source": "abstract", "text": p["abstract"]}], **kwargs}
    p.setdefault("candidate_evidence_assessments", []).append(normalize_evidence_assessment(raw, paper=p, candidate=record, sh_id=sh, dimension=d))


def ledger(records, papers, dimensions=None, lanes=(), summaries=(), selected=(), status="completed"):
    return build_candidate_ledger(records, papers, dimensions or {"SH1": [dimension()]}, lanes, summaries,
                                 selected_paper_ids=selected, discovery_status=status)


def pair():
    papers = [paper("W1", "Method Alpha"), paper("W2", "Method Beta")]
    records = register_candidates([observation(p, name) for p, name in zip(papers, ["Method Alpha", "Method Beta"])], papers)
    for p in papers:
        assess(p, next(r for r in records if r["name"] in p["title"]))
    return records, papers


def test_identity_requires_source_object_and_grounded_aliases():
    p = paper("W1", "Method Alpha")
    raw = observation(p, "Method Alpha", ["Invented Alias"])
    rows = register_candidates([raw, observation(p, "generic candidate"), observation(p, "W1")], [p])
    assert len(rows) == 1 and rows[0]["aliases"] == ["Method Alpha"]
    assert register_candidates([{**raw, "evidence_spans": [{"source": "abstract", "text": "fake quote"}]}], [p]) == []


def test_alias_merge_is_transitive_and_order_independent():
    p = paper("W1", "Method Alpha AlphaNet ANet")
    obs = [observation(p, "Method Alpha", ["AlphaNet"]), observation(p, "AlphaNet", ["ANet"])]
    assert register_candidates(obs, [p]) == register_candidates(list(reversed(obs)), [p])
    assert len(register_candidates(obs, [p])) == 1


def test_evidence_must_pass_each_dimension_and_quotes_are_verified():
    records, papers = pair()
    result = normalize_evidence_assessment({"eligible": True, "scope_pass": True, "evidence_role_pass": True,
        "minimum_evidence_pass": True, "evidence_spans": [{"source": "abstract", "text": "fabricated"}]},
        paper=papers[0], candidate=next(r for r in records if r["name"] == "Method Alpha"), sh_id="SH1", dimension=dimension())
    assert result["eligible"] is False


@pytest.mark.parametrize("state", ["failed", "searched_zero", "unsearched"])
def test_zero_and_failure_candidates_remain_in_denominator_without_negative_evidence(state):
    records, papers = pair()
    papers[1]["candidate_evidence_assessments"] = []
    cid = next(r["candidate_id"] for r in records if r["name"] == "Method Beta")
    lane = {"lane_id": "beta.performance", "candidate_id": cid, "sub_hypothesis_id": "SH1", "evidence_dimension": "performance"}
    summary = [] if state == "unsearched" else [{"raw_candidates_by_lane": {lane["lane_id"]: 0}, "failed_lanes": [lane["lane_id"]] if state == "failed" else []}]
    result = ledger(records, papers, lanes=[lane], summaries=summary)
    beta = next(r for r in result["records"] if r["candidate_id"] == cid)
    assert beta["minimum_evidence_matrix"]["SH1:performance"]["status"] == state
    assert beta["negative_evidence_ids"] == []
    assert result["balance"]["candidate_coverage"] == .5
    assert result["best_candidate_claim_allowed"] is False


def test_existing_eligible_flag_does_not_bypass_revalidation_or_project_exclusion():
    records, papers = pair()
    papers[0]["candidate_evidence_assessments"][0]["evidence_spans"] = []
    papers[1]["project_relevance"] = {"violated_exclusions": ["explicit exclusion"]}
    assert ledger(records, papers)["balance"]["unique_effective_evidence_count"] == 0


def test_independent_mentions_count_and_paper_order_does_not_change_balance():
    records, papers = pair()
    extra = paper("W3", "Method Alpha")
    assess(extra, next(r for r in records if r["name"] == "Method Alpha"))
    result = ledger(records, [*papers, extra])
    assert result["balance"] == ledger(records, [extra, *reversed(papers)])["balance"]
    assert result["balance"]["unique_effective_evidence_count"] == 3


def test_doi_duplicates_shared_credit_and_zero_candidates():
    rows = [{"candidate_id": "a", "effective_evidence_ids": ["shared", "shared"], "minimum_evidence_satisfied": True},
            {"candidate_id": "b", "effective_evidence_ids": ["shared"], "minimum_evidence_satisfied": True},
            {"candidate_id": "c", "effective_evidence_ids": [], "minimum_evidence_satisfied": False}]
    result = candidate_balance(rows)
    assert result["effective_evidence_weights_by_candidate"] == {"a": .5, "b": .5, "c": 0}
    assert result["unique_effective_evidence_count"] == 1
    assert result["candidate_coverage"] == pytest.approx(2/3)
    records, papers = pair()
    papers[0]["doi"] = "https://doi.org/10.1/SAME"
    duplicate = deepcopy(papers[0]); duplicate["paperId"] = "W3"; duplicate["doi"] = "10.1/same"
    assert ledger(records, [*papers, duplicate])["balance"]["unique_effective_evidence_count"] == 2


def test_negative_and_mixed_evidence_have_distinct_ranking_effects():
    records, papers = pair()
    for p in papers:
        p["candidate_evidence_assessments"][0]["stance"] = "negative"
    result = ledger(records, papers)
    assert all(not r["ranking_eligible"] for r in result["records"])
    assert not result["best_candidate_claim_allowed"]
    papers[0]["candidate_evidence_assessments"][0]["stance"] = "mixed"
    assert any(r["ranking_eligible"] for r in ledger(records, papers)["records"])


def test_per_sh_metrics_do_not_borrow_other_sh_evidence():
    records, papers = pair()
    for r in records:
        r["sub_hypothesis_ids"].append("SH2")
    result = ledger(records, papers, {"SH1": [dimension()], "SH2": [dimension()]})
    assert result["balance_by_comparator_group"]["SH1"]["candidate_coverage"] == 1
    assert result["balance_by_comparator_group"]["SH2"]["candidate_coverage"] == 0
    assert not result["best_candidate_claim_allowed"]


def test_all_candidate_dimensions_receive_independent_interleaved_budget():
    records, _papers = pair()
    slots = [f"axis_{i}" for i in range(15)]
    contract = {"sub_hypothesis_id": "SH1", "required_slots": slots,
                "slot_definitions": {slot: dimension(slot) for slot in slots}}
    tasks = build_candidate_evidence_tasks(contract, records)
    assert len(tasks) == 2 * 16  # all required axes plus counterevidence
    assert tasks[0]["candidate_id"] != tasks[1]["candidate_id"]
    for record in records:
        own = [t for t in tasks if t["candidate_id"] == record["candidate_id"]]
        assert len(own) == 16
        assert all(t["retrieval_plan"]["query_lanes"] for t in own)


def test_seed_budget_reserves_each_candidate_and_keeps_holdout_status():
    records, papers = pair()
    preselection = ledger(records, papers)
    selection = select_sh_seed_candidates(papers, [], max_seed_papers=1, candidate_ledger=preselection)
    assert len(selection["selected_papers"]) == 2
    assert all(p["seed_selection"]["selection_basis"] == "scientific_candidate_minimum" for p in selection["selected_papers"])
    result = ledger(records, papers, selected=["W1"])
    assert {r["seed_status"] for r in result["records"]} == {"selected", "holdout"}


def test_concentration_uses_normalized_gini_for_two_candidates():
    rows = [{"candidate_id": "a", "effective_evidence_ids": list(map(str, range(9)))},
            {"candidate_id": "b", "effective_evidence_ids": ["last"]}]
    result = candidate_balance(rows)
    assert result["normalized_evidence_gini"] == pytest.approx(.8)
    assert result["evidence_concentration_status"] == "concentrated"
    assert candidate_balance(rows[:1])["evidence_concentration_status"] == "single_candidate"
    assert candidate_balance([])["evidence_concentration_status"] == "no_effective_evidence"


def test_discovery_failure_blocks_best_claim_even_with_complete_balanced_matrix():
    records, papers = pair()
    result = ledger(records, papers, lanes=[{"lane_id": "discovery", "retrieval_stage": "candidate_discovery"}],
                    summaries=[{"raw_candidates_by_lane": {"discovery": 0}, "failed_lanes": ["discovery"]}])
    assert result["discovery_retrieval_status"] == "degraded"
    assert not result["best_candidate_claim_allowed"]


@pytest.mark.parametrize("status", ["irrelevant", "deferred_budget", "assessment_unavailable"])
def test_relevance_pending_blocks_complete_comparison_but_exclusions_do_not(status):
    records, papers = pair()
    source = paper("W3", "Unrelated Object")
    extra = register_candidates([observation(source, "Unrelated Object")], [source])[0]
    extra["roles_by_subhypothesis"] = {"SH1": "role_unresolved"}
    extra["candidate_relevance_by_subhypothesis"] = {"SH1": status}
    result = ledger([*records, extra], [*papers, source],
        lanes=[{"lane_id": "discovery", "retrieval_stage": "candidate_discovery"}],
        summaries=[{"raw_candidates_by_lane": {"discovery": 3}}])
    assert result["comparison_scope"]["decision_candidates"] == 2
    assert result["comparison_scope"]["unresolved_roles"] == 0
    assert result["best_candidate_claim_allowed"] is (status == "irrelevant")
    assert result["comparison_scope"]["relevance_pending_objects"] == (0 if status == "irrelevant" else 1)


def test_freeze_verifies_integrity_and_tracks_acquisition_without_changing_admission():
    records, papers = pair()
    frozen = freeze_candidate_ledger(ledger(records, papers))
    assert verify_candidate_ledger(frozen)
    assert freeze_candidate_ledger(frozen) == frozen
    assert frozen["challenger_status"] == "retained"
    updated = refresh_candidate_fulltext(frozen, {"W1": {"status": "pending"}, "W2": {"status": "metadata_only_by_fulltext_budget"}})
    assert verify_candidate_ledger(updated)
    assert {r["fulltext_status"] for r in updated["records"]} == {"pending", "not_requested_by_budget"}
    assert updated["balance"] == frozen["balance"]
    corrupted = deepcopy(frozen); corrupted["records"][0]["name"] = "tampered"
    assert not verify_candidate_ledger(corrupted)


def test_frozen_projection_and_shared_gap_scheduling_retain_challenger():
    from test_survey_idea_handoff_contract import _gap
    from src.pipeline.survey_idea_handoff import GapLedger, build_gap_ledger_payload, validate_handoff_payload
    records, papers = pair()
    for r in records:
        r["sub_hypothesis_ids"] = ["SH3"]
    for p in papers:
        p["candidate_evidence_assessments"][0]["sub_hypothesis_id"] = "SH3"
    frozen = freeze_candidate_ledger(ledger(records, papers, {"SH3": [dimension()]}))
    gaps = build_gap_ledger_payload(GapLedger(project_id="p", survey_run_id="r", project_context_fingerprint="ctx", gaps=[_gap()]))
    handoff = build_survey_idea_handoff_projection(gap_ledger=gaps, project_context={"original_topic": "Compare methods"}, survey_json={"subhypothesis_retrieval": {"candidate_discovery": frozen}})
    assert validate_handoff_payload(handoff, verify_fingerprint=True) == []
    roots = collect_mature_idea_sources(survey_handoff=handoff, max_ideas=1, allow_high_risk_seed=False)
    assert len(roots) == 2
    assert {r["scientific_candidate_root_role"] for r in roots} == {"primary", "challenger"}
    tasks = build_gap_screening_tasks(roots, IDEA_ROUTE_POLICIES, handoff, iterations=2, search_budget=1)
    assert len(tasks) == 2
    assert len({t.seed["scientific_candidate_id"] for t in tasks}) == 2
    corrupt = deepcopy(frozen); corrupt["comparison_status"] = "tampered"
    with pytest.raises(ValueError, match="verified frozen"):
        build_survey_idea_handoff_projection(gap_ledger=gaps, project_context={"original_topic": "Compare methods"}, survey_json={"subhypothesis_retrieval": {"candidate_discovery": corrupt}})


def test_survey_writing_receives_comparison_restriction():
    from test_survey_evidence_plan import _provenance, _ledger, _contracts, _clusters
    from src.pipeline.survey_evidence_plan import build_survey_evidence_plan
    result = build_survey_evidence_plan(provenance_artifact=_provenance(), coverage_ledger=_ledger(),
        cluster_coverage_artifact=_clusters(), subhypothesis_contracts=_contracts(),
        candidate_ledger={"schema_version": "scientific_candidate_ledger_v2", "comparison_status": "insufficient", "best_candidate_claim_allowed": False})
    assert result["scientific_candidate_comparison"]["best_candidate_claim_allowed"] is False
    assert result["writing_rules"]["best_candidate_claim_requires_balanced_effective_evidence"]


def test_discovery_uses_non_candidate_named_axes_and_secondary_system():
    from src.pipeline.retrieval_lanes import build_candidate_discovery_tasks
    tasks = build_candidate_discovery_tasks({"sub_hypothesis_id": "SH1", "scientific_scope": {
        "research_object": ["Rare Target"], "source_system": ["Established Proxy"]}, "required_slots": ["readout"],
        "slot_definitions": {"readout": {"retrieval_concepts": ["optical sensing", "electrical sensing"]}}}, project_context={})
    queries = [lane["query"] for task in tasks for lane in task["retrieval_plan"]["query_lanes"]]
    assert "Rare Target optical sensing" in queries and "Rare Target electrical sensing" in queries
    assert "optical sensing" not in queries and "electrical sensing" not in queries
    assert any("Established Proxy" in query for query in queries)


def test_long_dimension_names_and_aliases_have_unique_lane_ids():
    records, _papers = pair()
    for record in records:
        record["aliases"].append("alias " + record["name"])
    slots = ["shared_" + "x" * 65 + suffix for suffix in ("one", "two")]
    tasks = build_candidate_evidence_tasks({"sub_hypothesis_id": "SH1", "required_slots": slots,
        "slot_definitions": {slot: dimension(slot) for slot in slots}}, records)
    ids = [lane["lane_id"] for task in tasks for lane in task["retrieval_plan"]["query_lanes"]]
    assert len(ids) == len(set(ids))


def test_different_scientific_roles_do_not_establish_a_sufficient_comparison():
    records, papers = pair()
    records[0]["candidate_kind"] = "dataset"
    result = freeze_candidate_ledger(ledger(records, papers))
    assert not result["best_candidate_claim_allowed"]
    assert result["balance_by_comparator_group"]["SH1"]["comparability_status"] == "unresolved"
    assert result["challenger_status"] == "exploratory_comparability_unresolved"


def test_persisted_mature_sources_keep_independent_candidate_identity():
    from src.agents.idea_agent.utils.workflow.result_persistence import compact_mature_ideas, compact_candidate_entry, compact_idea_portfolio
    record = {"idea_id": "i", "scientific_candidate_id": "a", "scientific_candidate_root_role": "challenger", "candidate_ledger_fingerprint": "f" * 64}
    assert compact_mature_ideas([record])[0] == record
    for key in ("scientific_candidate_id", "scientific_candidate_root_role", "candidate_ledger_fingerprint"):
        assert compact_candidate_entry(record)[key] == record[key]
        assert compact_idea_portfolio({"competitive_ideas": [record]})["competitive_ideas"][0][key] == record[key]


def test_runtime_discovers_new_objects_then_validates_independent_matrix(monkeypatch):
    from test_sh_paper_semantic_assessment import _collector, _CapturingLogger
    from test_subhypothesis_evidence import _project_context, _comparative_contract
    from src.pipeline.retrieval_lanes import build_subhypothesis_retrieval_plan
    context = _project_context()
    sh = build_subhypothesis_retrieval_plan(context, [_comparative_contract(context)])["subhypotheses"][0]
    identifier = sh["sub_hypothesis_id"]
    initial = [paper("W1", "Method Alpha"), paper("W2", "Method Beta")]
    for p, name in zip(initial, ["Method Alpha", "Method Beta"]):
        p["scientific_candidates"] = [observation(p, name, sh=identifier)]
    class Chat:
        def batch_remote_chat(self, prompts, **kwargs):
            if kwargs.get("desc") == "Discovering Scientific Candidates":
                return [json.dumps({"candidates": []}) for prompt in prompts]
            if kwargs.get("desc") == "Assessing Candidate Relevance":
                answers = []
                for prompt in prompts:
                    data = json.loads(prompt.split("\n", 1)[1])
                    assert data["original_topic"] == context["original_topic"]
                    answers.append(json.dumps({"relevance": [{"candidate_id": record["candidate_id"],
                        "sub_hypothesis_id": identifier, "relevant": True, "role": "decision_candidate",
                        "reason": "Alternative method for the research decision"} for record in data["candidates"]]}))
                return answers
            assert kwargs.get("desc") == "Assessing Candidate Evidence"
            answers = []
            for prompt in prompts:
                data = json.loads(prompt.split("\n", 1)[1])
                answers.append(json.dumps({"assessments": [{"dimension": d["slot_name"], "scope_pass": True,
                    "evidence_role_pass": True, "minimum_evidence_pass": True, "stance": "supporting",
                    "evidence_spans": [{"source": "abstract", "text": data["paper"]["abstract"]}]}
                    for d in data["dimensions"]]}))
            return answers
    collector = _collector(Chat())
    collector.logger = _CapturingLogger()
    calls = []
    def discover(rows, retrieval_round=0):
        calls.append((deepcopy(rows), retrieval_round))
        tasks = [task for row in rows for key in ("candidate_discovery_tasks", "slot_recovery_tasks") for task in row.get(key, [])]
        lanes = [lane for task in tasks for lane in task["retrieval_plan"]["query_lanes"]]
        collector._executed_retrieval_lanes.extend(lanes)
        collector._slot_retrieval_summaries.append({"raw_candidates_by_lane": {lane["lane_id"]: 1 for lane in lanes}, "failed_lanes": []})
        return deepcopy(initial) if len(calls) == 1 else [paper("W3", "Method Alpha"), paper("W4", "Method Beta")]
    collector._discover_subhypothesis_candidates = discover
    def filter_papers(_topic, papers, *_args, **_kwargs):
        for p in papers:
            p["project_relevance"] = {"relevance_score": 5, "violated_exclusions": []}
        return papers
    collector._filter_project_candidates_if_enabled = filter_papers
    collector.assess_papers_against_subhypotheses = lambda papers, *_args: papers
    selected, selection = collector._collect_sh_seed_candidates(context["original_topic"], context, {"subhypotheses": [sh]}, [sh])
    result = collector.subhypothesis_retrieval_artifact["candidate_discovery"]
    assert len(calls) == 1 and all(round_number == 0 for _, round_number in calls)
    assert calls[0][0][0]["slot_recovery_tasks"] == []
    assert all(r["screening_status_by_subhypothesis"][identifier] == "completed" for r in result["records"])
    assert result["balance"]["candidate_coverage"] == 1
    assert result["balance"]["unique_effective_evidence_count"] == 2
    assert result["best_candidate_claim_allowed"] is True
    assert len({p["paperId"] for p in selected}) >= 2
    assert verify_candidate_ledger(result)
    assert result["funnel"]["unsearched_queries"] == []
    assert all(r["retrieval_budget"]["allocated_queries"] == r["retrieval_budget"]["executed_queries"] for r in result["records"])
    assert any("entropy=" in log for log in collector.logger.messages)


@pytest.mark.parametrize("statement", [
    "Method Alpha is the best candidate.",
    "Method Alpha is the optimal choice.",
    "Method Alpha is best understood as a testable framework.",
    "Method Alpha 是最佳候选。",
])
def test_claim_validator_does_not_gate_candidate_keywords(statement):
    from test_survey_evidence_bounded_writing import _generator
    generator = _generator()
    generator.survey_evidence_plan["scientific_candidate_comparison"] = {
        "best_candidate_claim_allowed": False, "candidate_aliases": ["Method Alpha"]}
    claim = {"claim_text": statement, "sub_hypothesis_ids": ["SH1"],
             "claim_mode": "EVIDENCE_BACKED_SYNTHESIS", "evidence_paths": []}
    errors = generator._validate_claim_trace(claim["claim_text"], [claim])
    assert not any("best_candidate" in error for error in errors)
    claim["candidate_claim_type"] = "best_candidate"
    errors = generator._validate_claim_trace(claim["claim_text"], [claim])
    assert any("best_candidate claim is prohibited" in error for error in errors)


def test_provider_errors_remain_failures_when_caching_is_disabled():
    from test_sh_paper_semantic_assessment import _collector, _FakeChatAgent
    collector = _collector(_FakeChatAgent([]))
    lane = {"lane_id": "failed", "retrieval_cache": {"status": "disabled", "provider_status": "provider_failure"}}
    summary = collector._slot_retrieval_summary([lane], [(lane, [])], [], min_candidates_before_relaxation=1, relaxation_used=False, fallback_used=False)
    assert summary["failed_lanes"] == ["failed"] and summary["zero_result_lanes"] == []
    lane = {"lane_id": "success", "retrieval_cache": {"status": "cache_write_failure", "provider_status": "success"}}
    summary = collector._slot_retrieval_summary([lane], [(lane, [])], [], min_candidates_before_relaxation=1, relaxation_used=False, fallback_used=False)
    assert summary["failed_lanes"] == [] and summary["zero_result_lanes"] == ["success"]


@pytest.mark.parametrize("statement", [
    "Method Alpha is the optimal choice.",
    "Method Alpha is the best candidate.",
    "Method Alpha is most suitable for the task.",
    "Method Alpha is best understood as a testable framework.",
])
def test_final_survey_does_not_repair_or_reject_candidate_keywords(statement):
    from test_survey_evidence_bounded_writing import _quality_draft, _quality_generator
    generator = _quality_generator([])
    generator.config.ModuleInfo.SurveyGenerator.evidence_bounded_section_quality_review_enabled = False
    generator.survey_evidence_plan["scientific_candidate_comparison"] = {
        "best_candidate_claim_allowed": False, "candidate_aliases": ["Method Alpha"]}
    generator.extract_and_process_citations = lambda text: (text, [], [], [])

    survey, references = generator.refine_draft(_quality_draft("## 1. Evidence\n\n" + statement))

    assert statement in survey
    assert references == []
    assert generator.chat_agent.calls == []


def test_same_alias_at_different_scientific_levels_is_not_merged():
    p = paper("W1", "Method Alpha")
    family = observation(p, "Method Alpha")
    instance = {**family, "taxonomic_level": "method_instance"}
    records = register_candidates([family, instance], [p])
    assert len(records) == 2
    assert len({r["candidate_id"] for r in records}) == 2


def test_missing_assessment_and_mixed_dimension_results_are_preserved():
    records, papers = pair()
    papers[0]["candidate_evidence_assessments"][0]["assessment_status"] = "unavailable"
    result = ledger(records, papers)
    row = next(r for r in result["records"] if r["name"] == "Method Alpha")
    assert row["minimum_evidence_matrix"]["SH1:performance"]["status"] == "assessment_unavailable"
    assert not row["minimum_evidence_satisfied"]
    papers[0]["candidate_evidence_assessments"][0]["assessment_status"] = "assessed"
    assess(papers[0], next(r for r in records if r["name"] == "Method Alpha"), dimension("limits"), stance="negative")
    result = ledger(records, papers, {"SH1": [dimension(), dimension("limits", False)]})
    assert next(r for r in result["records"] if r["name"] == "Method Alpha")["ranking_eligible"]


def test_absent_discovery_history_does_not_establish_comparison_sufficiency():
    records, papers = pair()
    assert ledger(records, papers)["comparison_status"] == "insufficient"
    lane = {"lane_id": "discovery", "retrieval_stage": "candidate_discovery"}
    summary = {"raw_candidates_by_lane": {"discovery": 2}, "failed_lanes": []}
    result = ledger(records, papers, lanes=[lane], summaries=[summary])
    assert result["comparison_status"] == "sufficient"
    assert result["best_candidate_claim_allowed"]
