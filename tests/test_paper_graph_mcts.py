"""Cross-domain exhaustion, transfer review and shared-resource recovery."""
from __future__ import annotations

import copy
import json
from types import SimpleNamespace

import pytest

from src.agents.idea_agent.agent.mcts import IdeaState, MCTSConfig, MemoryGuidedMCTS
from src.agents.idea_agent.agent.ligagent import LigAgent
from src.agents.idea_agent.utils.core import run_inputs
from src.agents.idea_agent.utils.mcts.retrieval_contracts import RetrievalResult
from src.agents.idea_agent.utils.mcts.mcts_runtime import EditPlan, MemoryBundle, ValidationProtocol
from src.paper_graph.transfer import qualify_transfer


def hit(i, domain="chemistry", score=.9):
    return {"node_id": f"core:{i}", "score": score, "core_node": {"node_id": f"core:{i}", "paper_domain": domain,
        "paper_title": f"Paper {i}", "components": [], "evidence_records": [{"evidence_id": f"e:{i}",
        "quote": "A conserves B assuming stationarity, only at equilibrium.", "locator": {"section": "Method"}}]}}


def review(i, decision="compatible"):
    citation = {"evidence_id": f"e:{i}", "source_quote": "A conserves B assuming stationarity, only at equilibrium.",
                "rationale": "Same conservation relation under the same explicit conditions."}
    return {"node_id": f"core:{i}", "decision": decision, "rationale": "A structural mapping is available.",
        "structure_mapping": [{**citation, "source": "Conservation", "target": "Conservation"}],
        "assumption_checks": [{**citation, "source_assumption": "stationarity", "target_condition": "stationarity", "assessment": "satisfied"}],
        "boundary_checks": [{**citation, "source_boundary": "equilibrium", "target_condition": "equilibrium", "assessment": "satisfied"}],
        "validation_obligations": ["Measure the conserved quantity under a controlled perturbation."]}


def state(**overrides):
    return IdeaState(title="Target", abstract="Target relation", core_contribution="Conservation",
        method="Compare conservation relations", risks="Unknown boundary", tags=[], operator="seed",
        target_defects=[], rationale="A candidate transfer", **overrides)


@pytest.fixture
def engine(monkeypatch, tmp_path):
    def no_call(*a, **k):
        raise AssertionError("Unstubbed LLM call")
    monkeypatch.setattr(run_inputs.AgentBase, "chat", no_call)
    return MemoryGuidedMCTS(no_call, "Evaluate {idea} in {topic}", config=MCTSConfig(
        enable_vector_memory=False, enable_symbolic_memory=False, symbolic_memory_path=str(tmp_path / "memory.json")),
        memory_accessor=SimpleNamespace(), paper_graph_vector_store=SimpleNamespace())


def provider(engine, hits):
    calls = []
    def search(*, query, top_k, **kwargs):
        calls.append(top_k)
        return hits[:top_k]
    engine.paper_graph_vector_store = SimpleNamespace(search=search)
    return calls


def test_widening_finds_cross_domain_nodes_beyond_initial_18(engine):
    calls = provider(engine, [hit(i, "physics") for i in range(38)] + [hit(i) for i in range(38, 42)])
    result = engine._retrieve_theory_transfer_references({"query": "conservation"}, ["physics"])
    assert result.status == "success" and len(result.hits) == 3
    assert calls == [18, 36, 72]
    assert result.diagnostics["same_domain"] == 38
    assert result.diagnostics["raw_hits"] == 42 and result.diagnostics["eligible"] == 4


def test_unknown_missing_same_domain_and_low_score_have_distinct_counts(engine):
    provider(engine, [hit(0, "Others"), hit(1, ""), hit(2, "physics"), hit(3, score=-1), hit(4)])
    result = engine._retrieve_theory_transfer_references({"query": "q"}, ["physics"])
    assert len(result.hits) == 1
    for key in ("unrecognized_domain", "missing_domain", "same_domain", "low_score", "eligible"):
        assert result.diagnostics[key] == 1
    assert result.diagnostics["stop_reason"] == "corpus_exhausted"


@pytest.mark.parametrize("mode,expected", [("exhausted", "no_hits"), ("candidates", "budget_exhausted"), ("calls", "budget_exhausted")])
def test_no_hits_is_distinct_from_budget_exhaustion(engine, mode, expected):
    provider(engine, [hit(i, "physics") for i in range(5 if mode == "exhausted" else 100)])
    if mode == "candidates":
        engine.config.retrieval_candidate_budget = 18
    if mode == "calls":
        engine.config.retrieval_call_budget = 1
    result = engine._retrieve_theory_transfer_references({"query": "q"}, ["physics"])
    assert result.status == expected
    assert result.diagnostics["stop_reason"] == {"exhausted": "corpus_exhausted", "candidates": "candidate_budget", "calls": "call_budget"}[mode]


def test_unresolved_target_discipline_is_not_treated_as_cross_domain(engine):
    calls = provider(engine, [hit(0)])
    result = engine._retrieve_theory_transfer_references({"query": "q"}, ["Others"])
    assert result.status == "no_hits" and not calls
    assert result.diagnostics["stop_reason"] == "unresolved_root_discipline"


@pytest.mark.parametrize("decision", ["compatible", "uncertain", "incompatible"])
def test_semantic_transfer_requires_compatible_complete_review(decision):
    qualified, audits = qualify_transfer((hit(1),), {"reviews": [review(1, decision)]})
    assert bool(qualified) == (decision == "compatible")
    assert audits[0]["qualified"] == bool(qualified)


@pytest.mark.parametrize("field,change", [
    ("assumption_checks", {"assessment": "unknown"}), ("boundary_checks", {"assessment": "violated"}),
    ("structure_mapping", {"evidence_id": "forged"}), ("assumption_checks", {"source_quote": "invented source assumption"}),
])
def test_unknown_conditions_and_forged_source_claims_cannot_qualify(field, change):
    packet = review(1)
    packet[field][0].update(change)
    qualified, audits = qualify_transfer((hit(1),), {"reviews": [packet]})
    assert not qualified and audits[0]["contract_issues"]


@pytest.mark.parametrize("payload", [{}, {"reviews": []}, {"reviews": [review(2)]}, {"reviews": [review(1), review(1)]}])
def test_malformed_semantic_review_rejected(payload):
    with pytest.raises(ValueError):
        qualify_transfer((hit(1),), payload)


def test_engine_calls_semantic_assessment_and_records_audit(engine):
    engine.chat_fn = lambda prompt, **kwargs: json.dumps({"reviews": [review(1)]})
    result = engine._assess_theory_transfer(RetrievalResult("success", hits=(hit(1),)), state())
    assert result.status == "success" and result.hits[0]["transfer_review"]
    engine.chat_fn = lambda prompt, **kwargs: "malformed"
    assert engine._assess_theory_transfer(RetrievalResult("success", hits=(hit(1),)), state()).status == "error"


def test_skill_instantiation_applies_transfer_review_before_generation(engine, monkeypatch):
    import src.agents.idea_agent.agent.mcts as module
    engine._build_theory_transfer_query = lambda *a: {"query": "q"}
    provider(engine, [hit(1)])
    engine.chat_fn = lambda *a, **k: json.dumps({"reviews": [review(1, "uncertain")]})
    def fail(*a, **k):
        raise AssertionError("Unqualified transfer reached child generation")
    monkeypatch.setattr(module, "instantiate_skill_plan_for_node", fail)
    parent = state(root_domains=["physics"])
    plan = EditPlan("theory-transfer-injection", "Find a transferable relation", [], [], ValidationProtocol(), [], [], "")
    result = engine._instantiate_skill_plan(plan, parent, MemoryBundle())
    assert result["_skip_child_creation"]
    assert result["_retrieval_result"]["diagnostics"]["transfer_reviews"][0]["decision"] == "uncertain"


def test_shared_reload_resets_all_consumers_only_after_success(engine):
    other = copy.copy(engine)
    for consumer in (engine, other):
        consumer.capabilities.unavailable["paper_graph"] = "initial failure"
        consumer.component_novelty_scorer._disabled_error = "initial failure"
        consumer._paper_graph_source_ids.add("stale-graph-source")
        consumer.evidence_sources["stale-graph-source"] = {"text": "old evidence"}
        consumer.evaluation_cache["stale-evaluation"] = {}
    agent = object.__new__(LigAgent)
    agent._paper_graph_consumers = [engine, other]
    calls = []
    agent._shared_paper_graph_vector_store = SimpleNamespace(reload=lambda **kwargs: calls.append(kwargs), size=12)
    result = agent.reload_paper_graph()
    assert result == {"status": "ready", "components": 12, "consumers": 2}
    assert len(calls) == 1
    assert all(not c.capabilities.unavailable and c.component_novelty_scorer._disabled_error is None for c in (engine, other))
    assert all(not c.evaluation_cache and "stale-graph-source" not in c.evidence_sources for c in (engine, other))


def test_failed_shared_reload_preserves_unavailable_capability(engine):
    agent = object.__new__(LigAgent)
    agent._paper_graph_consumers = [engine]
    engine.capabilities.unavailable["paper_graph"] = "initial failure"
    def fail(**kwargs):
        raise ValueError("replacement incompatible")
    agent._shared_paper_graph_vector_store = SimpleNamespace(reload=fail)
    with pytest.raises(ValueError, match="incompatible"):
        agent.reload_paper_graph()
    assert engine.capabilities.unavailable["paper_graph"] == "initial failure"


def test_ligagent_uses_explicit_detached_graph_configuration(monkeypatch, tmp_path):
    import src.agents.idea_agent.agent.ligagent as module
    captured = {}
    class Store:
        def __init__(self, **kwargs):
            captured.update(kwargs)
        def warmup(self):
            return self
    monkeypatch.setattr(module, "PaperGraphComponentVectorStore", Store)
    agent = object.__new__(LigAgent)
    agent.config = {"paper_graph": {"db_path": str(tmp_path / "custom.db"), "index_dir": str(tmp_path / "idx"), "model_path": str(tmp_path / "model")}}
    agent.project_config = {"paper_graph": {"db_path": str(tmp_path / "ignored.db")}}
    settings = MCTSConfig()
    agent._build_shared_paper_graph_vector_store(settings)
    assert captured["db_path"] == settings.paper_graph_db_path == str(tmp_path / "custom.db")
