from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace

import pytest

from src.agents.idea_agent.utils.mcts.idea_routes import IDEA_ROUTE_POLICIES
from src.agents.idea_agent.utils.workflow.gap_search_schedule import (
    build_gap_refinement_tasks,
    build_gap_screening_tasks,
    gap_coverage_report,
    rank_gap_routes,
)


def _gap(identifier, slot, *, priority="medium", route="core_hypothesis"):
    return {
        "gap_id": identifier, "target_slot": slot, "gap_kind": slot,
        "priority": priority, "eligibility_route": route, "statement": "Unresolved scientific relation.",
    }


def _seed(identifier, *gap_ids):
    return {"idea_id": identifier, "target_gap_ids": list(gap_ids), "maturity_status": "mature"}


def _result(score):
    return SimpleNamespace(best=SimpleNamespace(evaluation=SimpleNamespace(composite=score)))


@pytest.mark.parametrize(("slot", "expected_route"), [
    ("target_object", "object_substitution"),
    ("nonidentifiable_mechanism", "verification_reversal"),
    ("comparable_endpoint", "representation_shift"),
    ("external_validation", "verification_reversal"),
    ("missing_assumption", "premise_inversion"),
    ("current_method_or_design", "mechanism_replacement"),
    ("unsupported_causal_link", "mechanism_replacement"),
])
def test_routes_match_scientific_gap_types(slot, expected_route):
    ranked = rank_gap_routes(_gap("gap-1", slot), IDEA_ROUTE_POLICIES)
    assert ranked[0].route_id == expected_route


def test_screening_covers_gaps_once_instead_of_crossing_seeds_and_routes():
    gaps = [_gap("object", "target_object"), _gap("endpoint", "comparable_endpoint"), _gap("boundary", "boundary", priority="high")]
    seeds = [_seed("broad", "object", "endpoint", "boundary"), _seed("specialized", "object")]
    original = deepcopy(seeds)
    tasks = build_gap_screening_tasks(seeds, IDEA_ROUTE_POLICIES, {"gaps": gaps}, iterations=3)
    assert len(tasks) == 3
    assert tasks[0].primary_gap_id == "boundary"
    assert {task.primary_gap_id for task in tasks} == {"object", "endpoint", "boundary"}
    object_task = next(task for task in tasks if task.primary_gap_id == "object")
    assert object_task.key[0] == "specialized"
    assert object_task.focused_seed()["target_gap_ids"] == ["object"]
    assert seeds == original
    assert sum(task.iterations for task in tasks) == 9


def test_budget_allocates_coverage_before_alternative_routes():
    gaps = [_gap("first", "target_object", priority="high"), _gap("second", "external_validation")]
    tasks = build_gap_screening_tasks([_seed("seed", "first", "second")], IDEA_ROUTE_POLICIES, {"gaps": gaps}, iterations=3)
    results = {tasks[0].key: _result(4.8)}
    refinement = build_gap_refinement_tasks(tasks, results, IDEA_ROUTE_POLICIES, iterations=6, search_budget=1)
    assert refinement[0].primary_gap_id == "second"
    assert refinement[0].coverage_before == "unsearched"
    assert refinement[0].route == tasks[1].route


def test_failed_gap_gets_budget_before_high_scoring_gap_and_an_alternate_route():
    gaps = [_gap("first", "target_object"), _gap("second", "external_validation")]
    tasks = build_gap_screening_tasks([_seed("seed", "first", "second")], IDEA_ROUTE_POLICIES, {"gaps": gaps}, iterations=3)
    results = {tasks[0].key: _result(4.8), tasks[1].key: None}
    refinement = build_gap_refinement_tasks(tasks, results, IDEA_ROUTE_POLICIES, iterations=8, search_budget=1)
    assert refinement[0].primary_gap_id == tasks[1].primary_gap_id
    assert refinement[0].coverage_before == "no_candidate"
    assert refinement[0].route != tasks[1].route


def test_successful_gap_can_be_explored_by_a_different_route():
    tasks = build_gap_screening_tasks([_seed("seed", "gap")], IDEA_ROUTE_POLICIES, {"gaps": [_gap("gap", "target_object")]}, iterations=3)
    refinement = build_gap_refinement_tasks(tasks, {tasks[0].key: _result(4)}, IDEA_ROUTE_POLICIES, iterations=8, search_budget=2)
    assert len(refinement) == 1
    assert refinement[0].primary_gap_id == "gap"
    assert refinement[0].route.route_id == "premise_inversion"


def test_survey_constraints_and_unknown_ids_do_not_become_primary_gaps():
    gaps = [_gap("constraint", "boundary", route="supporting_constraint"), _gap("verify", "external_validation", route="verification_only"), _gap("excluded", "target_object", route="exclude")]
    tasks = build_gap_screening_tasks([_seed("seed", "constraint", "verify", "excluded", "invented")], IDEA_ROUTE_POLICIES, {"gaps": gaps}, iterations=3)
    assert tasks == []


def test_separate_triage_overrides_gap_defaults():
    handoff = {"gaps": [_gap("gap", "target_object")], "gap_triage": {"gaps": [{"gap_id": "gap", "eligibility_route": "exclude"}]}}
    assert build_gap_screening_tasks([_seed("seed", "gap")], IDEA_ROUTE_POLICIES, handoff, iterations=3) == []


def test_explicit_route_allowlist_is_respected():
    routes = [route for route in IDEA_ROUTE_POLICIES if route.route_id == "mechanism_replacement"]
    tasks = build_gap_screening_tasks([_seed("seed", "gap")], routes, {"gaps": [_gap("gap", "target_object")]}, iterations=3)
    refinement = build_gap_refinement_tasks(tasks, {tasks[0].key: _result(3)}, routes, iterations=5, search_budget=1)
    assert tasks[0].route == routes[0]
    assert refinement[0].route == routes[0]


def test_coverage_reports_failure_without_claiming_scientific_resolution():
    tasks = build_gap_screening_tasks([_seed("seed", "first", "second")], IDEA_ROUTE_POLICIES, {"gaps": [_gap("first", "target_object"), _gap("second", "external_validation")]}, iterations=3)
    report = gap_coverage_report(tasks, {tasks[0].key: _result(3), tasks[1].key: None})
    assert report["candidate_gap_ids"] == [tasks[0].primary_gap_id]
    assert report["gaps_without_candidates"] == [tasks[1].primary_gap_id]
    assert report["iteration_budget"] == 6
    assert "unverified" in report["coverage_definition"]


def test_gapless_seed_gets_one_fallback_route_without_a_handoff():
    tasks = build_gap_screening_tasks([_seed("seed")], IDEA_ROUTE_POLICIES, {}, iterations=3)
    assert len(tasks) == 1
    assert tasks[0].primary_gap_id == ""


def test_unanchored_seed_keeps_one_fallback_with_survey_after_gap_coverage():
    seed = {**_seed("reframing"), "idea_source": "problem_reframing"}
    tasks = build_gap_screening_tasks(
        [seed, _seed("anchored", "gap")], IDEA_ROUTE_POLICIES,
        {"gaps": [_gap("gap", "target_object")]}, iterations=3,
    )
    assert len(tasks) == 2
    assert tasks[0].primary_gap_id == "gap"
    assert tasks[1].key[0] == "reframing"
    assert tasks[1].primary_gap_id == ""
    assert gap_coverage_report(tasks, {tasks[1].key: _result(4)})["candidate_gap_ids"] == []


def test_context_constraints_keep_authoritative_content_without_becoming_targets():
    gaps = [_gap("gap", "target_object"), _gap("constraint", "boundary", route="supporting_constraint")]
    handoff = {"gaps": gaps, "gap_triage": {"gaps": [{
        "gap_id": "constraint", "eligibility_route": "verification_only", "evidence_eligibility": "background_only",
    }]}}
    task = build_gap_screening_tasks(
        [_seed("seed", "gap", "constraint", "invented")], IDEA_ROUTE_POLICIES, handoff, iterations=3,
    )[0]
    focus = task.focused_seed()["gap_search_focus"]
    assert focus["context_gap_ids"] == ["constraint"]
    assert focus["context_constraints"][0]["statement"] == gaps[1]["statement"]
    assert focus["context_constraints"][0]["eligibility_route"] == "verification_only"
    assert focus["context_constraints"][0]["evidence_eligibility"] == "background_only"
    assert task.focused_seed()["target_gap_ids"] == ["gap"]
    refined = build_gap_refinement_tasks([task], {task.key: _result(3)}, IDEA_ROUTE_POLICIES, iterations=8, search_budget=1)[0]
    assert refined.focus()["context_constraints"] == focus["context_constraints"]


def test_zero_budget_and_search_cap_are_respected():
    seeds = [_seed("seed", "first", "second")]
    handoff = {"gaps": [_gap("first", "target_object"), _gap("second", "external_validation")]}
    assert build_gap_screening_tasks(seeds, IDEA_ROUTE_POLICIES, handoff, iterations=0) == []
    tasks = build_gap_screening_tasks(seeds, IDEA_ROUTE_POLICIES, handoff, iterations=3, search_budget=1)
    assert len(tasks) == 1
    assert build_gap_refinement_tasks(tasks, {}, IDEA_ROUTE_POLICIES, iterations=8, search_budget=0) == []
