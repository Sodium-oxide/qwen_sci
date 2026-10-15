from __future__ import annotations

from types import SimpleNamespace

from src.agents.idea_agent.agent.mcts import IdeaState
from src.agents.idea_agent.utils.mcts.mcts_runtime import (
    EditPlan,
    ValidationProtocol,
    _gap_focus_prompt,
    build_root_state,
    materialize_child_state,
)
from src.agents.idea_agent.utils.workflow.idea_portfolio import _candidate_key, select_seed_representatives


def _focus():
    return {
        "primary_gap_id": "gap-a", "primary_gap": {"gap_id": "gap-a", "statement": "An unresolved relation."},
        "context_gap_ids": ["gap-b"], "route_id": "mechanism_replacement", "iteration_budget": 3,
        "context_constraints": [{"gap_id": "gap-b", "statement": "A boundary must hold.", "eligibility_route": "supporting_constraint"}],
    }


def test_root_state_carries_the_assigned_primary_gap():
    root = build_root_state("A general question", {
        "mature_idea": {"title": "Root idea", "hypothesis": "A relation is testable."},
        "target_gap_ids": ["gap-a"], "gap_search_focus": _focus(),
        "route_id": "mechanism_replacement",
    }, IdeaState)
    assert root.scientific_intervention["gap_search_focus"] == _focus()
    assert root.scientific_intervention["hypothesis_contract"]["target_gap_ids"] == ["gap-a"]


def test_child_cannot_replace_assigned_gap_with_generated_ids():
    parent = IdeaState(
        title="Parent", abstract="A relation.", core_contribution="A claim.", method="A mechanism.",
        risks="Uncertain.", tags=[], operator="root", target_defects=[], rationale="A question.", memory_refs=[],
        scientific_intervention={"gap_search_focus": _focus(), "hypothesis_contract": {"target_gap_ids": ["gap-a"]}},
    )
    plan = EditPlan(
        "mechanism-commit-innovation", "Clarify the mechanism", ["nonidentifiable_mechanism"], [],
        ValidationProtocol([], [], []), [], [], "Scientific edit",
    )
    mcts = SimpleNamespace(_skill_prior_for_prompt=lambda name: {}, route_id="mechanism_replacement")
    child = materialize_child_state(mcts, parent, plan, {
        "scientific_contract": {"target_gap_ids": ["invented", "gap-b"]},
    }, idea_state_cls=IdeaState)
    assert child.scientific_intervention["hypothesis_contract"]["target_gap_ids"] == ["gap-a"]
    assert child.scientific_intervention["gap_search_focus"] == _focus()
    assert parent.scientific_intervention["hypothesis_contract"]["target_gap_ids"] == ["gap-a"]
    prompt = _gap_focus_prompt(child)
    assert "primary_gap_id" in prompt
    assert "not evidence" in prompt
    assert "A boundary must hold." in prompt
    assert "supporting_constraint" in prompt


def test_portfolio_identity_distinguishes_gap_tasks_for_the_same_seed_and_route():
    first = {"idea_id": "seed", "seed_id": "seed", "route_id": "verification_reversal", "gap_search_focus": {"primary_gap_id": "gap-a"}}
    second = {**first, "gap_search_focus": {"primary_gap_id": "gap-b"}}
    assert _candidate_key(first) != _candidate_key(second)


def test_real_portfolio_keeps_distinct_gaps_on_the_same_route():
    entries = [{
        "idea_id": "seed", "seed_id": "seed", "route_id": "verification_reversal",
        "gap_search_focus": {"primary_gap_id": gap_id},
        "route_signature": {"route_id": "verification_reversal", "primary_gap_id": gap_id},
    } for gap_id in ["gap-a", "gap-b"]]
    selected = select_seed_representatives(entries)["seed"]
    assert {entry["gap_search_focus"]["primary_gap_id"] for entry in selected} == {"gap-a", "gap-b"}
