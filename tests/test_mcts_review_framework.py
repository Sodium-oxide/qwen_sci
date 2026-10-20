"""Offline contracts for search, review, evidence and delivery across disciplines."""
from __future__ import annotations

import json
import re
from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace

import pytest

from src.agents.idea_agent.agent.mcts import (
    IdeaEvaluation, IdeaNode, IdeaState, MCTSConfig, MemoryGuidedMCTS, OperatorApplication, SearchCandidate,
)
from src.agents.idea_agent.utils.core import run_inputs
from src.agents.idea_agent.utils.core.task_contract import build_task_contract
from src.agents.idea_agent.utils.mcts.mcts_runtime import (
    EditPlan, EditOperatorSkill, ValidationProtocol, MemoryBundle,
    best_candidate, build_root_state, materialize_child_state, update_skill_prior_from_evaluation,
    evaluation_prompt_cache_key, cache_evaluation, get_cached_evaluation, instantiate_skill_plan_for_node,
)
from src.agents.idea_agent.utils.mcts.review_contracts import (
    ReviewIssue, active_defects, apply_field_updates, content_hash, delivery_assessment,
    progress_hash, reconcile_issues, scientific_content, transition_reward,
)
from src.agents.idea_agent.utils.mcts.review_execution import run_review, _ground_assessment
from src.agents.idea_agent.utils.mcts.retrieval_contracts import (
    CapabilityState, RetrievalResult, operator_retrieval_policy, probe_paper_graph, retrieve,
)
from src.agents.idea_agent.utils.mcts.scientific_intervention_ontology import detect_profile_drift
from src.agents.idea_agent.utils.prompting.review_packets import build_review_packets, token_bound
from src.agents.idea_agent.utils.workflow.claim_evidence import audit_claims, normalize_claims
from src.agents.idea_agent.utils.workflow.idea_debate import _apply_revision
from src.agents.idea_agent.utils.workflow.idea_portfolio import select_primary_and_competitors
from src.agents.idea_agent.utils.workflow.result_persistence import compact_candidate_entry, compact_result_payload


REQUEST = "Compare two mechanisms and give a discriminating observation."


def task(request=REQUEST, required=True):
    return build_task_contract(original_request=request, interpretation={
        "extraction_status": "complete", "user_constraints": [], "problem_premises": [],
        "required_deliverables": [{"source_quote": "discriminating observation", "acceptance_description": "Give an observable contrast."}] if required else [],
    })


def state(**overrides):
    return IdeaState(**{
        "title": "Competing mechanisms", "abstract": "Two alternative explanations.",
        "core_contribution": "A discriminating physical relation.", "method": "Compare both explanations.",
        "risks": "Limited observation range.", "tags": [], "operator": "seed", "target_defects": [], "rationale": "Seed.",
        "components": ["relation", "observation"],
        "scientific_intervention": {"profile_id": "physical_materials_chemical", "hypothesis_contract": {"mechanism_or_relation": "A influences B."}},
        "claims": [{"claim_id": "c1", "kind": "hypothesis", "text": "A changes B.", "validation_plan": "Compare B under an intervention on A."}],
        **overrides,
    })


def node(candidate=None, **kwargs):
    return IdeaNode(state=candidate or state(), node_id=kwargs.pop("node_id", 0), depth=0,
                    parent=kwargs.pop("parent", None), transformation=OperatorApplication("seed", [], "", []), **kwargs)


def assessment(**overrides):
    return {"novelty": 4, "feasibility": 4, "confidence": 4, "review_notes": "Examined the supplied fields.",
            "review_issues": [], "requirement_reviews": [], "claim_reviews": [],
            "contribution_review": {}, **overrides}


def evaluation(**overrides):
    overrides.setdefault("review_coverage", {"complete": True})
    return IdeaEvaluation.from_payload(assessment(**overrides))


@pytest.fixture
def make_engine(monkeypatch, tmp_path):
    def offline(*args, **kwargs):
        raise AssertionError("A test attempted a real LLM call.")
    monkeypatch.setattr(run_inputs.AgentBase, "chat", offline)

    def make(chat=lambda *a, **k: json.dumps(assessment()), **config):
        engine = MemoryGuidedMCTS(chat, "Review {idea} for {topic}.", config=MCTSConfig(
            enable_vector_memory=False, enable_symbolic_memory=False,
            symbolic_memory_path=str(tmp_path / "memory.json"), **config),
            memory_accessor=SimpleNamespace(), paper_graph_vector_store=SimpleNamespace())
        engine._score_component_novelty = lambda _: None
        return engine
    return make


def test_full_state_retains_tail_lists_case_and_component_explanations():
    text = "方法 A != a。" * 1600 + "TAIL_OBLIGATION"
    original = state(method=text, components=["A", "a", *[f"part{i}" for i in range(24)]],
                     component_explanations={"A": text},
                     scientific_intervention={"hypothesis_contract": {"assumptions": [f"a{i}" for i in range(40)]}})
    assert original.method == text
    assert original.component_explanations["A"] == text
    assert len(original.components) == 26
    assert len(original.scientific_intervention["hypothesis_contract"]["assumptions"]) == 40
    packets = build_review_packets(original.to_payload(), token_budget=6000)
    assert len(packets) > 1
    assert all(token_bound(p.text) <= 6000 for p in packets)
    assert any("TAIL_OBLIGATION" in p.text for p in packets)
    segments = [m.group(1) for p in packets for m in re.finditer(r"FIELD method \(continued segment\):\n(.*?)(?=\nFIELD |\Z)", p.text, re.S)]
    assert "".join(segments) == text
    assert all("method" not in p.included_paths for p in packets)


@pytest.mark.parametrize("change", [
    {"method": "a != A"}, {"evidence_records": [{"source_id": "new", "quote": "Evidence changed."}]},
    {"scientific_intervention": {"hypothesis_contract": {"boundary_or_failure_condition": "Different domain."}}},
])
def test_scientific_changes_invalidate_signature_and_cache(change):
    parent = state()
    altered = replace(parent, **change)
    assert altered.signature != parent.signature
    key = evaluation_prompt_cache_key("p", content_hash=parent.signature, review_version="2")
    assert key != evaluation_prompt_cache_key("p", content_hash=altered.signature, review_version="2")
    assert key != evaluation_prompt_cache_key("p", content_hash=parent.signature, review_version="3")
    cache = {}
    cache_evaluation(parent.signature, key, evaluation(), cache)
    cached = get_cached_evaluation(parent.signature, key, cache)
    cached.review_issues.append({"kind": "mutated"})
    assert get_cached_evaluation(parent.signature, key, cache).review_issues == []
    parent.skill_metrics["visits"] = 900
    parent.scientific_intervention["profile_drift"] = {"signal": "backbone"}
    assert evaluation_prompt_cache_key("p", content_hash=parent.signature, review_version="2") == key


def test_review_coverage_failures_cannot_become_missing_candidate_content(make_engine):
    calls = []
    rid = task()["required_deliverables"][0]["requirement_id"]
    def chat(prompt, **_):
        calls.append(prompt)
        if len(calls) == 2:
            raise RuntimeError("review provider unavailable")
        return json.dumps(assessment(
            requirement_reviews=[{"requirement_id": rid, "status": "missing"}],
            review_issues=[{"kind": "missing_parameter", "target_path": "candidate.nonexistent", "origin": "candidate"}]))
    engine = make_engine(chat, review_prompt_token_budget=6500, max_review_packets=2)
    payload, coverage = run_review(engine, node(state(method="x" * 20000)), "Review.\n", {"task_contract": task()})
    assert not coverage["complete"]
    assert coverage["errors"]
    assert payload["requirement_reviews"][0]["status"] == "unassessed"
    assert payload["review_issues"][0]["origin"] == "context"


def test_complete_segment_review_has_separate_consistency_pass(make_engine):
    prompts = []
    def chat(prompt, **_):
        prompts.append(prompt)
        return json.dumps(assessment())
    engine = make_engine(chat, review_prompt_token_budget=8000)
    _, coverage = run_review(engine, node(state(method="x" * 15000)), "Review.\n", {"task_contract": task(required=False)})
    assert coverage["complete"], coverage["errors"]
    assert coverage["consistency_reviewed"]
    assert len(prompts) > coverage["packets_total"]
    assert all(token_bound(p) <= 8000 for p in prompts)


def test_issue_ledger_keeps_omitted_problems_and_requires_cited_recheck():
    old = ReviewIssue.from_payload({"kind": "missing_boundary", "target_path": "method"}).to_dict()
    assert reconcile_issues([old], [], included_paths=["$"], complete=True) == [old]
    closure = {**old, "status": "resolved", "rechecked": True, "rationale": "Fixed.", "evidence_refs": ["unknown"]}
    assert reconcile_issues([old], [closure], included_paths=["$"], complete=True, valid_evidence_refs=["method"])[0]["status"] == "open"
    closure["evidence_refs"] = ["method"]
    resolved = reconcile_issues([old], [closure], included_paths=["$"], complete=True, valid_evidence_refs=["method"])
    assert resolved[0]["status"] == "resolved"
    assert reconcile_issues(resolved, [], included_paths=["title"], complete=False, invalidated_paths=["method"])[0]["status"] == "unassessed"
    unobserved = reconcile_issues([], [old], included_paths=["title"], complete=False)
    assert unobserved[0]["origin"] == "context"
    assert active_defects(unobserved) == []


def test_task_extraction_retries_separately_and_preserves_explicit_scope(monkeypatch):
    outputs = iter(["bad-json", json.dumps({"extraction_status": "complete", "required_deliverables": [], "user_constraints": [], "problem_premises": []})])
    calls = []
    def chat(*args, **kwargs):
        calls.append(args[0])
        return next(outputs)
    extracted = run_inputs._extract_task_contract(REQUEST, None, chat_fn=chat)
    assert len(calls) == 2
    assert extracted["extraction_status"] == "complete"
    contract = build_task_contract(original_request=REQUEST, interpretation=extracted,
        refinement_scope="Use only symbolic reasoning.", refinement_scope_source="config_explicit")
    restored = build_task_contract(original_request=REQUEST, interpretation=contract,
        refinement_scope="Use only symbolic reasoning.", refinement_scope_source="config_explicit")
    assert restored == contract
    assert restored["user_constraints"][0]["source"] == "config_explicit"
    failed = run_inputs._extract_task_contract(REQUEST, None, chat_fn=lambda *a, **k: "not-json")
    assert failed["extraction_status"] == "failed"
    assert len(failed["extraction_errors"]) == 2
    assert task(required=False)["extraction_status"] == "complete"


@pytest.mark.parametrize("error,status", [(FileNotFoundError("index"), "unavailable"), (ImportError("faiss"), "unavailable"), (RuntimeError("timeout"), "error"), (None, "no_hits")])
def test_typed_retrieval_statuses(error, status):
    def search(**_):
        if error:
            raise error
        return []
    assert retrieve(SimpleNamespace(search=search), "query", top_k=1).status == status
    assert retrieve(None, "query", top_k=1, budget_available=False).status == "budget_exhausted"
    assert retrieve(SimpleNamespace(search=lambda **_: [{"source_id": "s1"}]), "query", top_k=1).status == "success"


def test_missing_index_is_detected_without_initializing_models(tmp_path):
    store = SimpleNamespace(index_dir=tmp_path / "missing", search=lambda **_: pytest.fail("should not search"))
    missing = probe_paper_graph(store)
    capabilities = CapabilityState()
    assert not capabilities.eligible(["paper_graph"])
    capabilities.record(missing)
    assert not capabilities.eligible(["paper_graph"])
    assert operator_retrieval_policy(SimpleNamespace(evidence_policy="required"), missing) == "skip"
    assert operator_retrieval_policy(SimpleNamespace(evidence_policy="exploratory"), missing) == "exploratory"
    capabilities.record(RetrievalResult("no_hits"))
    assert capabilities.eligible(["paper_graph"])


@pytest.mark.parametrize("first", [[], RuntimeError("retry")])
def test_no_hits_changes_query_and_errors_retry_with_call_budget(make_engine, first):
    calls = []
    def search(query, **_):
        calls.append(query)
        if len(calls) == 1:
            if isinstance(first, Exception):
                raise first
            return first
        return [{"score": 1.0, "core_node": {"paper_id": "s", "paper_domain": "physics", "text": "Support."}}]
    engine = make_engine(retrieval_call_budget=2)
    engine.paper_graph_vector_store = SimpleNamespace(search=search)
    result = engine._retrieve_references({"query": "first", "needed_content": "alternative"}, cross_domain=False)
    assert result.status == "success"
    assert calls == ["first", "first" if isinstance(first, Exception) else "alternative"]
    assert engine._retrieve_references({"query": "third"}, cross_domain=False).status == "budget_exhausted"


@pytest.mark.parametrize("profile,method", [("physical_materials_chemical", "Measure the polymer backbone."), ("social_behavioral", "Use a neural architecture as an analysis tool.")])
def test_keywords_and_cross_domain_tools_do_not_prove_drift(profile, method):
    result = detect_profile_drift(profile, {"method": method})
    assert not result["primary_drift"]
    assert result["drift_severity"] == "none"


def test_actual_task_replacement_can_drift_even_inside_computational_profile():
    candidate = {"core_contribution": "Replace the proof with an unrelated image benchmark."}
    review = {"role": "primary_contribution", "replaces_task_objective": True, "serves_task_objective": False,
              "triggering_text": "unrelated image benchmark", "task_boundary_quote": "Prove convergence", "rationale": "No requested proof is provided."}
    assert detect_profile_drift("computational_algorithmic", candidate, contribution_review=review, task_request="Prove convergence of the solver.")["primary_drift"]
    review["role"] = "analysis_tool"
    assert not detect_profile_drift("computational_algorithmic", candidate, contribution_review=review, task_request="Prove convergence of the solver.")["primary_drift"]


def test_sources_quotes_and_semantic_support_are_independent():
    claims = normalize_claims([{"claim_id": "f", "kind": "literature_fact", "text": "A causes B.", "support_refs": ["e1"], "verified": True}])
    records = [{"evidence_id": "e1", "source_id": "s1", "quote": "A is correlated with B.", "locator": "paragraph 1"}]
    sources = {"s1": {"text": "A is correlated with B."}}
    audits, issues = audit_claims(claims, records, sources)
    assert "verified" not in claims[0]
    assert audits[0]["sources"][0]["quote_matches"]
    assert audits[0]["support_assessment"] == "unassessed"
    assert any(i["origin"] == "context" for i in issues)
    rejected = [{"claim_id": "f", "support_assessment": "unsupported", "evidence_refs": ["s1"], "rationale": "Correlation does not establish the proposed causal direction."}]
    audits, issues = audit_claims(claims, records, sources, semantic_reviews=rejected)
    assert audits[0]["support_assessment"] == "unsupported"
    assert any(i["kind"] == "unsupported_claim" and i["origin"] == "candidate" for i in issues)
    _, missing = audit_claims(claims, records, {})
    assert any(i["kind"] == "source_unavailable" and i["origin"] == "dependency" for i in missing)


def test_formal_measurement_and_user_premise_obligations():
    formal = normalize_claims([{"claim_id": "proof", "kind": "formal_derivation", "text": "The sequence converges.", "assumptions": ["bounded"], "derivation": "Apply the stated lemma.", "proof_obligations": ["Check monotonicity."]}])
    fake_review = [{"claim_id": "proof", "support_assessment": "supported", "rationale": "Proved.", "evidence_refs": ["claims[0].nonexistent_proof"]}]
    audits, issues = audit_claims(formal, [], {}, semantic_reviews=fake_review)
    assert audits[0]["support_assessment"] == "unassessed"
    assert issues
    measure = normalize_claims([{"kind": "hypothesis", "text": "The proxy measures the target.", "relation_type": "measurement", "validation_plan": "Calibrate against the reference."}])
    _, issues = audit_claims(measure, [], {})
    assert any(i["kind"] == "measurement_construct_mismatch" for i in issues)
    premise = normalize_claims([{"kind": "user_premise", "text": "User confirmed the result.", "source_quote": "invented"}])
    _, issues = audit_claims(premise, [], {}, original_request=REQUEST)
    assert any(i["kind"] == "premise_provenance_gap" for i in issues)


def test_delta_clears_fields_inherits_exactly_and_invalidates_dependencies(make_engine):
    parent = state(paper_graph_context="old", evidence_records=[{"source_id": "s"}])
    delta = {"parent_content_hash": parent.signature, "field_updates": {
        "scientific_intervention.hypothesis_contract.mechanism_or_relation": "Different mechanism.",
        "claims": [], "evidence_records": [], "root_domains": ["mathematics"],
        "discipline_resolution": {"primary_discipline": "mathematics"}, "paper_graph_context": "",
    }}
    with pytest.raises(ValueError, match="parent_content_hash"):
        apply_field_updates(parent.to_payload(), {**delta, "parent_content_hash": "stale"}, parent.signature)
    plan = EditPlan("synthetic-refine", "Refine.", [], [], ValidationProtocol(), [], [], "Plan.")
    child = materialize_child_state(make_engine(), parent, plan, delta, idea_state_cls=IdeaState)
    assert child.method == parent.method
    assert child.claims == child.evidence_records == []
    assert child.root_domains == ["mathematics"]
    assert child.discipline_resolution["primary_discipline"] == "mathematics"
    assert child.paper_graph_context == ""
    assert "scientific_intervention.hypothesis_contract.evidence_basis" in child.skill_metrics["dependency_rechecks"]
    assert parent.claims and parent.evidence_records


def test_quality_skill_gain_and_delivery_eligibility_have_distinct_roles():
    low = node(node_id=0, task_contract=task(required=False))
    low.evaluation = evaluation(novelty=1, review_coverage={"complete": True, "content_hash": low.state.signature})
    high = node(node_id=1, parent=low, task_contract=task(required=False))
    high.evaluation = evaluation(novelty=5, review_coverage={"complete": True, "content_hash": high.state.signature},
        review_issues=[ReviewIssue.from_payload({"kind": "proof_gap", "target_path": "method"}).to_dict()])
    low.children = [high]
    assert best_candidate(low, SearchCandidate).node is low
    assert best_candidate(low, SearchCandidate, ready_first=False).node is high
    low.evaluation.review_coverage = {"complete": False}
    assert not best_candidate(low, SearchCandidate).node.delivery["delivery_ready"]
    assert transition_reward(high.evaluation, high.evaluation) == 0
    assert not delivery_assessment(evaluation(), task())["delivery_ready"]


def test_transposition_skill_credit_uses_the_rollout_parent_and_ignores_infrastructure(make_engine):
    engine = make_engine()
    original_parent, actual_parent = node(node_id=0), node(node_id=1)
    original_parent.evaluation, actual_parent.evaluation = evaluation(novelty=0), evaluation(novelty=5)
    child = node(state(operator="synthetic-refine"), node_id=2, parent=original_parent)
    child._rollout_parent = actual_parent
    child._rollout_metadata = {"skill_name": "synthetic-refine", "skill_metrics": {}}
    update_skill_prior_from_evaluation(engine, child, evaluation(novelty=5))
    assert child.state.skill_metrics["transition_reward"] == 0
    child._rollout_metadata = {"skill_name": "other", "skill_metrics": {"evidence_mode": "exploratory", "retrieval_result": {"status": "unavailable"}}}
    update_skill_prior_from_evaluation(engine, child, evaluation(novelty=0))
    assert "other" not in engine.skill_catalog.priors


def test_full_snapshot_and_issue_ledger_survive_persistence_and_reload():
    original = state(method="long method " * 3000 + "TAIL", components=["relation", "observation"])
    entry = {**original.to_payload(), "scientific_snapshot": original.to_payload(),
             "delivery": {"delivery_ready": False}, "search_status": "partial",
             "evaluation": evaluation(review_issues=[ReviewIssue.from_payload({"kind": "missing_boundary"}).to_dict()]).to_dict()}
    compact = compact_candidate_entry(entry)
    restored = build_root_state(REQUEST, {"latest_candidate": compact}, IdeaState)
    assert restored.signature == original.signature
    assert compact["evaluation"]["review_issues"] == entry["evaluation"]["review_issues"]
    assert compact["search_status"] == "partial"


def test_portfolio_and_debate_do_not_promote_partial_or_rewritten_candidates():
    ready = {**state().to_payload(), "candidate_id": "ready", "delivery": {"delivery_ready": True}, "evaluation": {"novelty": 1}}
    partial = {**state().to_payload(), "candidate_id": "partial", "delivery": {"delivery_ready": False}, "evaluation": {"novelty": 5}}
    assert select_primary_and_competitors([partial, ready])["primary"]["candidate_id"] == "ready"
    assert select_primary_and_competitors([partial])["primary"] == {}
    revised, _, changed, _ = _apply_revision(ready, {"mechanism_or_relation": "A different mechanism."}, direction_mode="default", original_gap_ids=[])
    assert changed
    assert revised["delivery"]["status"] == "partial"


def test_real_search_repairs_requirement_with_mock_chat_and_keeps_feedback(make_engine):
    contract = task()
    rid = contract["required_deliverables"][0]["requirement_id"]
    seen_generation = []
    def chat(prompt, **kwargs):
        if kwargs.get("stage"):
            seen_generation.append(prompt)
            digest = re.search(r"parent_content_hash=([0-9a-f]{64})", prompt).group(1)
            return json.dumps({"parent_content_hash": digest, "field_updates": {"method": "DISTINGUISH: intervention A changes B; the alternative leaves B constant."}})
        fixed = "DISTINGUISH:" in prompt or "Explicit contrasting predictions." in prompt
        return json.dumps(assessment(requirement_reviews=[{"requirement_id": rid, "status": "satisfied" if fixed else "missing",
            "candidate_paths": ["candidate.method"] if fixed else [], "rationale": "Explicit contrasting predictions." if fixed else "No contrast provided."}]))
    engine = make_engine(chat, max_iterations=1, branching_factor=1)
    skill = EditOperatorSkill("alternative-path-contrast", "Repair an explicit requirement.", "local", "existing_subsystem", False)
    engine.skill_catalog.skills = {skill.name: skill}
    result = engine.search(REQUEST, {"task_contract": contract, "root_domains": ["physics"], "root_idea": state().to_payload()})
    assert result.status == "ready", (result.unresolved, len(seen_generation), result.best.node.evaluation.review_coverage.get("errors"))
    assert "DISTINGUISH:" in result.best.node.state.method
    assert result.best.node.delivery["delivery_ready"]
    assert seen_generation and result.trace
    assert "No contrast provided." in seen_generation[0]
    assert rid in seen_generation[0]
    assert result.trace[0]["skill_metrics"]["changed_paths"] == ["method"]
    assert engine.skill_catalog.priors[skill.name].attempts == 1


def test_search_stagnation_switches_actions_and_returns_partial(make_engine):
    engine = make_engine(max_iterations=10, stagnation_patience=2, branching_factor=1)
    engine.skill_catalog.skills = {}
    result = engine.search(REQUEST, {"task_contract": task(), "root_domains": ["physics"], "root_idea": state().to_payload()})
    assert result.status == "partial"
    assert result.unresolved and result.best_available
    assert result.stop_reason == "stagnation"
    assert any(event.get("action") == "switch_operators" for event in result.operational_events)
    assert progress_hash(state().to_payload()) == progress_hash(state(title="Another label").to_payload())


def test_required_evidence_operator_is_skipped_before_generation(make_engine, monkeypatch, tmp_path):
    engine = make_engine(max_iterations=1, branching_factor=1)
    skill = replace(engine.skill_catalog.skills["theory-transfer-injection"], scope_preference="existing_subsystem")
    engine.skill_catalog.skills = {skill.name: skill}
    engine.paper_graph_vector_store = SimpleNamespace(index_dir=tmp_path / "absent-index",
        search=lambda **_: pytest.fail("A missing index must not initialize retrieval."))
    monkeypatch.setattr(engine, "_instantiate_skill_plan", lambda *a, **k: pytest.fail("Evidence preflight must precede generation."))
    result = engine.search(REQUEST, {"task_contract": task(required=False), "root_domains": ["physics"], "root_idea": state().to_payload()})
    assert not result.best.node.children
    assert any(e.get("status") == "unavailable" for e in result.operational_events)
    assert result.acquisition_requests[0]["skill"] == skill.name
    assert engine.skill_catalog.priors.get(skill.name, SimpleNamespace(attempts=0)).attempts == 0


def test_exploratory_operator_exposes_missing_grounding(make_engine, tmp_path):
    parent = state()
    prompts = []
    def chat(prompt, **_):
        prompts.append(prompt)
        return json.dumps({"parent_content_hash": parent.signature, "field_updates": {"method": "Proposed comparison with a validation path."}})
    engine = make_engine(chat)
    engine.paper_graph_vector_store = SimpleNamespace(index_dir=tmp_path / "absent-index")
    plan = EditPlan("mechanism-commit-innovation", "Refine a mechanism.", [], [], ValidationProtocol(), [], [], "Explore.")
    payload = engine._instantiate_skill_plan(plan, parent, MemoryBundle())
    assert payload["_evidence_mode"] == "exploratory"
    assert payload["_retrieval_result"]["status"] == "unavailable"
    assert "No retrieved grounding is available" in prompts[0]
    assert engine.capabilities.acquisition_requests


@pytest.mark.parametrize("builder", ["_build_theory_transfer_query", "_build_mechanism_commit_query"])
def test_cross_domain_queries_are_not_rejected_by_ambiguous_terms(make_engine, builder):
    query = "threshold gating and suppression as a physical relation"
    engine = make_engine(lambda *a, **k: json.dumps({"query": query,
        "needed_content": "A competing model.", "mechanism_gap": "A competing model.", "expected_role": "analysis_tool"}))
    plan = EditPlan("mechanism-commit-innovation", "Compare models.", [], [], ValidationProtocol(), [], [], "Explore.")
    assert getattr(engine, builder)(plan, state())["query"] == query


def test_claim_support_requires_joint_visibility_and_consistency_cannot_invent_it(make_engine):
    candidate = state(claims=[{"claim_id": "f", "kind": "literature_fact", "text": "A changes B.", "support_refs": ["e"]}],
        evidence_records=[{"evidence_id": "e", "source_id": "s", "quote": "A changes B.", "locator": "paragraph 1"}])
    review = {"claim_id": "f", "support_assessment": "supported", "link_assessment": "supported",
        "rationale": "Source reports the relation.", "link_rationale": "The measurement is calibrated.", "evidence_refs": ["s"]}
    context = {"task_contract": task(required=False), "trusted_sources": {"s": {"text": "A changes B."}}}
    separated = _ground_assessment(assessment(claim_reviews=[deepcopy(review)]),
        ["claims[0]"], ("candidate.claims[0]", "context.task_contract"), candidate.to_payload(), context, False)
    assert separated["claim_reviews"][0]["support_assessment"] == "unassessed"
    joint = _ground_assessment(assessment(claim_reviews=[deepcopy(review)]),
        ["claims[0]", "evidence_records[0]"], ("context.task_contract", "context.trusted_sources.s"), candidate.to_payload(), context, False)
    assert joint["claim_reviews"][0]["support_assessment"] == "supported"
    # A later synthesis that has only findings must not fabricate positive support.
    def chat(prompt, **_):
        return json.dumps(assessment(claim_reviews=[review] if "Audit consistency across" in prompt else []))
    engine = make_engine(chat, review_prompt_token_budget=8000)
    payload, coverage = run_review(engine, node(replace(candidate, method="long text " * 2000)), "Review.\n", context)
    assert coverage["complete"], coverage["errors"]
    assert not any(r.get("support_assessment") == "supported" for r in payload["claim_reviews"])


def test_reviewer_cannot_certify_program_checks_or_cite_missing_candidate_fields(make_engine):
    rid = task()["required_deliverables"][0]["requirement_id"]
    def chat(*_, **__):
        return json.dumps(assessment(
            review_issues=[{"kind": "review_incomplete", "checker": "review_execution_v2", "target_path": "method"}],
            requirement_reviews=[{"requirement_id": rid, "status": "satisfied", "candidate_paths": ["invented_field"], "rationale": "Present."}]))
    payload, _ = run_review(make_engine(chat), node(), "Review.\n", {"task_contract": task()})
    assert payload["review_issues"][0]["checker"] == ""
    assert payload["requirement_reviews"][0]["status"] == "unassessed"


def test_claim_issues_follow_ids_across_reordering_and_close_after_actual_recheck(make_engine):
    formal = {"claim_id": "f", "kind": "formal_derivation", "text": "The sequence converges.",
        "assumptions": ["bounded"], "derivation": "Apply the lemma.", "proof_obligations": ["Verify the lemma applies."]}
    design = {"claim_id": "d", "kind": "design_choice", "text": "Use a comparison arm."}
    engine = make_engine()
    engine.task_contract = task(required=False)
    parent = node(state(claims=[formal, design]))
    engine._simulate(parent, [parent], [])
    issue = next(i for i in parent.review_issues if i["kind"] == "proof_support_unassessed")
    reordered = node(replace(parent.state, claims=[design, formal]), node_id=1, parent=parent)
    engine._simulate(reordered, [parent, reordered], [])
    retained = next(i for i in reordered.review_issues if i["issue_id"] == issue["issue_id"])
    assert retained["status"] != "resolved"
    assert retained["target_path"] == "claims[1]"
    removed = node(replace(reordered.state, claims=[design]), node_id=2, parent=reordered)
    engine._simulate(removed, [parent, reordered, removed], [])
    closed = next(i for i in removed.review_issues if i["issue_id"] == issue["issue_id"])
    assert closed["status"] == "resolved" and closed["rechecked"]
    assert removed.delivery["delivery_ready"]


def test_complete_review_rechecks_program_context_issue(make_engine):
    engine = make_engine()
    engine.task_contract = task(required=False)
    candidate = node()
    issue = ReviewIssue.from_payload({"kind": "review_incomplete", "origin": "context", "status": "unassessed",
        "checker": "review_execution_v2", "rationale": "Previous review provider failed."}).to_dict()
    candidate.review_issues = [issue]
    engine._simulate(candidate, [candidate], [])
    assert candidate.review_issues[0]["status"] == "resolved"
    assert candidate.delivery["delivery_ready"]


def test_partial_generation_cannot_overwrite_unseen_parent_content(make_engine):
    parent = state(method="x" * 50000 + "TAIL")
    plan = EditPlan("alternative-path-contrast", "Repair method.", [], [], ValidationProtocol(), [], [], "Explore.")
    prompts = []
    def chat(prompt, **_):
        prompts.append(prompt)
        return json.dumps({"title": "Rewrite", "method": "An incomplete full replacement."})
    payload = instantiate_skill_plan_for_node(make_engine(chat, review_prompt_token_budget=16000), plan, parent,
        MemoryBundle(), prompt_template="Edit {topic}: {plan_objective}.")
    assert prompts
    assert payload is None
    assert parent.method.endswith("TAIL")


def test_task_extractor_runs_independently_of_successful_topic_interpretation():
    calls = []
    initial = {"extraction_status": "complete", "required_deliverables": [], "user_constraints": [], "problem_premises": []}
    def chat(prompt, **_):
        calls.append(prompt)
        return json.dumps({**initial, "required_deliverables": [{"source_quote": "discriminating observation", "acceptance_description": "State the observation."}]})
    result = run_inputs._extract_task_contract(REQUEST, None, initial, chat_fn=chat)
    assert len(calls) == 1
    assert result["required_deliverables"]


def test_state_rejects_invalid_contract_and_preserves_all_disciplines():
    with pytest.raises(TypeError, match="hypothesis_contract must be an object"):
        state(scientific_intervention={"hypothesis_contract": ["invalid"]})
    domains = ["physics", "chemistry", "mathematics", "computer_science"]
    assert len(state(root_domains=domains).root_domains) == len(domains)


def test_formal_support_cannot_use_the_claim_statement_as_its_own_proof():
    claim = normalize_claims([{"claim_id": "f", "kind": "formal_derivation", "text": "The sequence converges.",
        "assumptions": ["bounded"], "derivation": "Apply a monotone convergence argument.", "proof_obligations": ["Monotonicity."]}])
    review = {"claim_id": "f", "support_assessment": "supported", "rationale": "It is stated.", "evidence_refs": ["claims[0].text"]}
    assert audit_claims(claim, [], {}, semantic_reviews=[review])[0][0]["support_assessment"] == "unassessed"
    review["evidence_refs"] = ["claims[0].assumptions", "claims[0].derivation", "claims[0].proof_obligations"]
    assert audit_claims(claim, [], {}, semantic_reviews=[review])[0][0]["support_assessment"] == "supported"


def test_public_materialization_downgrades_delivery_and_preserves_reviewed_snapshot(monkeypatch):
    from src.agents.idea_agent.agent.artifacts import artifact_init, artifact_set
    from src.agents.idea_agent.utils.workflow import ligagent_flow
    original = state().to_payload()
    entry = {**deepcopy(original), "scientific_snapshot": deepcopy(original), "delivery": {"delivery_ready": True, "status": "ready"}}
    artifact = artifact_init()
    artifact_set(artifact, "topic", [REQUEST])
    monkeypatch.setattr(ligagent_flow, "align_public_idea_entry", lambda *a, **k: deepcopy(entry))
    monkeypatch.setattr(ligagent_flow, "build_profile_aware_materialization", lambda *a, **k: {
        "scientific_spec": {"proposed_analysis": "A newly generated comparison."}, "legacy_algorithm": []})
    monkeypatch.setattr(ligagent_flow, "generate_idea_introduction", lambda **k: "A newly generated explanation.")
    payload = ligagent_flow.build_idea_result_payload(entry, [], artifact, lambda *a, **k: pytest.fail("offline"), "mock",
        SimpleNamespace(info=lambda *a: None, warning=lambda *a: None))
    persisted = compact_result_payload(payload)
    assert payload["delivery"]["status"] == "partial"
    assert persisted["delivery"]["delivery_ready"] is False
    assert persisted["legacy_best_entry"]["delivery"]["delivery_ready"] is False
    assert persisted["legacy_best_entry"]["scientific_snapshot"] == original


def test_candidate_selection_rejects_review_of_an_older_content_version(make_engine):
    engine = make_engine()
    engine.task_contract = task(required=False)
    candidate = node(task_contract=engine.task_contract)
    engine._simulate(candidate, [candidate], [])
    assert best_candidate(candidate, SearchCandidate).node.delivery["delivery_ready"]
    candidate.state.method += " An additional unreviewed assumption."
    assert best_candidate(candidate, SearchCandidate).node is candidate
    assert candidate.delivery["status"] == "partial"
    assert "reviewed snapshot" in " ".join(candidate.delivery["reasons"])


def test_consistency_cannot_replace_support_with_an_unreviewed_reference(make_engine):
    candidate = state(claims=[{
        "claim_id": "f", "kind": "literature_fact", "text": "A changes B.", "support_refs": ["e1", "e2"],
    }], evidence_records=[
        {"evidence_id": "e1", "source_id": "s1", "quote": "A changes B.", "locator": "paragraph 1"},
        {"evidence_id": "e2", "source_id": "s2", "quote": "A changes B.", "locator": "paragraph 2"},
    ])
    def chat(prompt, **_):
        review = {"claim_id": "f", "support_assessment": "supported", "link_assessment": "supported",
            "rationale": "The source reports the relation.", "link_rationale": "The source supports the calibration.",
            "evidence_refs": ["s2" if "Audit consistency across" in prompt else "s1"]}
        return json.dumps(assessment(claim_reviews=[review]))
    payload, coverage = run_review(make_engine(chat, review_prompt_token_budget=48000), node(candidate), "Review.\n", {
        "task_contract": task(required=False), "trusted_sources": {"s1": {"text": "A changes B."}, "s2": {"text": "A changes B."}},
        "additional_context": "long text " * 12000,
    })
    assert coverage["complete"], coverage["errors"]
    supported = [r for r in payload["claim_reviews"] if r.get("support_assessment") == "supported"]
    assert supported
    assert all(r["evidence_refs"] == ["s1"] for r in supported)


@pytest.mark.parametrize("status", ["ready", "partial"])
def test_final_handoff_preserves_materialized_content_and_delivery(status):
    from src.agents.idea_agent.agent.artifacts import artifact_init, artifact_set
    from src.agents.idea_agent.utils.workflow.ligagent_handlers import execute_primary_idea_materialization_stage
    from src.agents.idea_agent.utils.workflow.stage_contract import StageContext
    artifact = artifact_init()
    artifact_set(artifact, "idea_portfolio", {"selected_primary_idea": {
        "title": "Before materialization", "delivery": {"delivery_ready": True, "status": "ready"},
    }})
    delivery = {"delivery_ready": status == "ready", "status": status}
    artifact_set(artifact, "idea_result", {
        "delivery": delivery, "legacy_best_entry": {"title": "Materialized candidate", "method": "Current method."},
    })
    agent = SimpleNamespace(artifact=artifact)
    result = execute_primary_idea_materialization_stage(agent, StageContext(agent, artifact, "test"))
    primary = result.artifact_patch.replace["latest_candidate"]
    assert primary["title"] == "Materialized candidate"
    assert primary["delivery"] == delivery
    assert result.status == ("success" if status == "ready" else "degraded")


@pytest.mark.parametrize("field,value", [
    ("claims", {"text": "This is not a list."}),
    ("claims", [{"kind": "literature_fact"}]),
    ("evidence_records", ["This is not a record."]),
])
def test_invalid_structured_claim_content_is_rejected_instead_of_dropped(field, value):
    from src.agents.idea_agent.utils.workflow.idea_contract import normalize_idea_contract
    with pytest.raises((TypeError, ValueError)):
        normalize_idea_contract({field: value})
    with pytest.raises((TypeError, ValueError)):
        state(**{field: value})


def test_custom_operator_with_required_paper_graph_evidence_cannot_generate_on_no_hits(make_engine):
    engine = make_engine(lambda *a, **k: pytest.fail("Generation ran without required evidence."))
    skill = replace(engine.skill_catalog.skills["mechanism-commit-innovation"], name="custom-grounded", evidence_policy="required")
    engine.skill_catalog.skills[skill.name] = skill
    engine.paper_graph_vector_store = SimpleNamespace(search=lambda **kwargs: [])
    engine._build_mechanism_commit_query = lambda *args: {"query": "A relevant scientific relation."}
    plan = EditPlan(skill.name, "Compare models.", [], [], ValidationProtocol(), [], [], "Explore.")
    payload = engine._instantiate_skill_plan(plan, state(), MemoryBundle())
    assert payload["_skip_child_creation"] is True
    assert payload["_retrieval_result"]["status"] == "no_hits"
    assert engine.capabilities.acquisition_requests[0]["skill"] == skill.name


def test_malformed_generated_claim_does_not_abort_search_or_disappear_silently(make_engine):
    def chat(prompt, **kwargs):
        if kwargs.get("stage"):
            digest = re.search(r"parent_content_hash=([0-9a-f]{64})", prompt).group(1)
            return json.dumps({"parent_content_hash": digest, "field_updates": {"claims": [{"kind": "literature_fact"}]}})
        return json.dumps(assessment())
    engine = make_engine(chat, max_iterations=1, branching_factor=1, review_prompt_token_budget=200000)
    skill = EditOperatorSkill("alternative-path-contrast", "Repair an explicit requirement.", "local", "existing_subsystem", False)
    engine.skill_catalog.skills = {skill.name: skill}
    original = state().to_payload()
    result = engine.search(REQUEST, {"task_contract": task(), "root_domains": ["physics"], "root_idea": original})
    assert result.status == "partial"
    assert not result.best.node.children
    assert result.best.node.state.claims == original["claims"]
    rejected = [event for event in result.operational_events if event.get("status") == "invalid_candidate_contract"]
    assert len(rejected) == 1 and "non-empty text" in rejected[0]["reason"]
    assert engine.skill_catalog.priors.get(skill.name, SimpleNamespace(attempts=0)).attempts == 0
