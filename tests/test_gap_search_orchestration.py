from __future__ import annotations

import logging
from types import SimpleNamespace

from omegaconf import OmegaConf

from src.agents.idea_agent.agent.artifacts import artifact_get, artifact_set
from src.agents.idea_agent.utils.core.task_contract import build_task_contract
from src.agents.idea_agent.utils.workflow import ligagent_handlers as handlers
from src.agents.idea_agent.utils.workflow.result_persistence import compact_candidate_entry, compact_direction_document
from src.agents.idea_agent.utils.workflow.stage_contract import StageContext


def _run_stage(monkeypatch, tmp_path, *, screening_budget=0, refinement_budget=1, routes=None, screening_iterations=3, fail_gap="", task_contract=None, scope="", scope_source="", seed_scope="", handoff_metadata=None):
    gaps = [
        {"gap_id": "gap-a", "target_slot": "comparable_endpoint", "gap_kind": "comparable_endpoint"},
        {"gap_id": "gap-b", "target_slot": "comparable_endpoint", "gap_kind": "comparable_endpoint"},
        {"gap_id": "gap-c", "target_slot": "target_object", "gap_kind": "target_object"},
    ]
    seed = {
        "idea_id": "seed", "title": "A scientific hypothesis", "hypothesis": "A relation is testable.",
        "target_gap_ids": [gap["gap_id"] for gap in gaps], "maturity_status": "mature",
    }
    if seed_scope:
        seed["refinement_scope"] = seed_scope
    artifact = {
        "topic": ["A general scientific question"], "mature_ideas": [seed],
        "survey_idea_context": {"handoff": {"gaps": gaps, **(handoff_metadata or {})}},
    }
    artifact_set(artifact, "task_contract", task_contract or {})
    artifact_set(artifact, "refinement_scope", scope)
    artifact_set(artifact, "refinement_scope_source", scope_source)
    requests = []
    captured_candidates = []

    def search(topic, context):
        requests.append(context)
        gap_id = context["gap_search_focus"]["primary_gap_id"]
        first_attempt = context["gap_search_focus"]["coverage_before"] == "unsearched"
        best = None if gap_id == fail_gap and first_attempt else SimpleNamespace(
            evaluation=SimpleNamespace(composite=4.0 if first_attempt else 3.0),
            to_dict=lambda: {"evaluation": {"feasibility": 3}},
        )
        return SimpleNamespace(best=best, context=context, pareto={}, experiences=[])

    mcts = SimpleNamespace(
        config=SimpleNamespace(max_iterations=8),
        symbolic_memory_path=tmp_path / "memory.json",
        symbolic_memory=SimpleNamespace(save=lambda path: None),
        reload_symbolic_memory=lambda: None,
        prepare_root_context=lambda topic, context: context,
        search=search,
    )
    agent = SimpleNamespace(
        artifact=artifact, logger=logging.getLogger("gap-schedule-test"), mcts=mcts,
        model="test-model", run_dir=tmp_path, idea_result_path=tmp_path / "idea_result.json",
        config={
            "run": {"route_matrix_enabled": True, "max_mature_ideas": 12},
            "portfolio": {"screening_search_budget": screening_budget, "refinement_search_budget": refinement_budget},
            "mcts": {"screening_max_iterations": screening_iterations, "refinement_max_iterations": 8},
        },
        chat=lambda *args, **kwargs: "",
        build_mcts_for_mode=lambda *args, **kwargs: mcts,
    )
    if routes is not None:
        agent.config["portfolio"]["screening_route_ids"] = routes
    agent.config = OmegaConf.create(agent.config)
    monkeypatch.setattr(handlers, "collect_mature_idea_sources", lambda **kwargs: [seed])

    def best_entry(result, mode):
        return {
            "title": "Candidate " + result.context["gap_search_focus"]["primary_gap_id"],
            "search_score": result.best.evaluation.composite,
            "target_gap_ids": result.context["target_gap_ids"],
            "evaluation": {"feasibility": 3},
        }

    def portfolio(entries, mature_ideas, **kwargs):
        captured_candidates.extend(entries)
        return {"selected_primary_idea": entries[0], "competitive_ideas": entries}

    monkeypatch.setattr(handlers, "result_to_best_entry", best_entry)
    monkeypatch.setattr(handlers, "build_idea_portfolio", portfolio)
    monkeypatch.setattr(handlers, "persist_final_idea", lambda **kwargs: {"directions": kwargs["idea_portfolio"]["competitive_ideas"]})
    monkeypatch.setattr(handlers, "_build_mode_result_document", lambda topic, direction, source, artifact, binding: direction)
    result = handlers.execute_idea_generation_stage(agent, StageContext(agent, artifact, "idea_generation"))
    return result, requests, captured_candidates


def test_stage_focuses_context_and_preserves_screening_coverage(monkeypatch, tmp_path):
    result, requests, candidates = _run_stage(monkeypatch, tmp_path, fail_gap="gap-b")
    assert result.status == "success"
    assert len(requests) == 4
    assert [request["mcts_iteration_budget"] for request in requests[:3]] == [3, 3, 3]
    assert requests[-1]["gap_search_focus"]["primary_gap_id"] == "gap-b"
    assert requests[-1]["mcts_iteration_budget"] == 8
    for request in requests:
        focus_id = request["gap_search_focus"]["primary_gap_id"]
        assert request["target_gap_ids"] == [focus_id]
        assert [gap["gap_id"] for gap in request["survey_idea_handoff"]["gaps"]] == [focus_id]
        assert request["mature_idea_record"]["target_gap_ids"] == [focus_id]
        constraints = request["gap_search_focus"]["context_constraints"]
        assert {gap["gap_id"] for gap in constraints} == {"gap-a", "gap-b", "gap-c"} - {focus_id}
        assert all(gap["target_slot"] for gap in constraints)
    assert {entry["target_gap_ids"][0] for entry in candidates} == {"gap-a", "gap-b", "gap-c"}
    report = result.artifact_patch.replace["gap_route_schedule"]
    assert report["screening_coverage"]["gaps_without_candidates"] == ["gap-b"]
    assert report["final_coverage"]["gaps_without_candidates"] == []
    assert report["final_coverage"]["iteration_budget"] == 17


def test_refinement_fills_unsearched_gaps_before_revisiting_success(monkeypatch, tmp_path):
    result, requests, candidates = _run_stage(monkeypatch, tmp_path, screening_budget=2)
    assert len(requests) == 3
    assert requests[-1]["gap_search_focus"]["primary_gap_id"] == "gap-c"
    assert requests[-1]["gap_search_focus"]["coverage_before"] == "unsearched"
    assert result.artifact_patch.replace["gap_route_schedule"]["unsearched_gap_ids"] == []


def test_same_route_for_different_gaps_does_not_overwrite_results(monkeypatch, tmp_path):
    result, requests, candidates = _run_stage(monkeypatch, tmp_path, routes=["representation_shift"], refinement_budget=0)
    assert len(candidates) == 3
    assert len(list((tmp_path / "mode_idea_results").glob("*.json"))) == 3
    assert result.artifact_patch.replace["gap_route_schedule"]["final_coverage"]["candidate_gap_ids"] == ["gap-a", "gap-b", "gap-c"]


def test_weaker_refinement_does_not_replace_screening_candidate(monkeypatch, tmp_path):
    result, requests, candidates = _run_stage(monkeypatch, tmp_path, routes=["representation_shift"])
    assert len(requests) == 4
    assert len(candidates) == 3
    assert all(entry["search_score"] == 4.0 for entry in candidates)


def test_logged_and_recorded_budget_matches_mcts_cap(monkeypatch, tmp_path):
    result, requests, candidates = _run_stage(monkeypatch, tmp_path, screening_iterations=12, refinement_budget=0)
    assert all(request["mcts_iteration_budget"] == 8 for request in requests)
    schedule = result.artifact_patch.replace["gap_route_schedule"]
    assert schedule["screening_coverage"]["iteration_budget"] == 24


def test_task_and_constraint_provenance_survive_seed_and_gap_isolation(monkeypatch, tmp_path):
    request = "Design an ecological comparison and predict a discriminating observation."
    contract = build_task_contract(original_request=request, interpretation={"task_mode": "protocol_design"})
    _, requests, _ = _run_stage(
        monkeypatch, tmp_path, refinement_budget=0, task_contract=contract,
        scope="Only report uncertainty", scope_source="analysis_grounded", seed_scope="Inspect a local relation",
        handoff_metadata={
            "constraints": {"may_generate_new_gap": False},
            "field_consensus": ["A source-reported consensus"],
        },
    )

    assert requests
    for context in requests:
        assert context["task_contract"]["original_request"] == request
        assert not context.get("refinement_scope")
        assert context["proposed_scope"] == "Inspect a local relation"
        assert context["public_facts"]["verified_facts"] == []
        assert context["public_facts"]["hard_constraints"] == []
        assert context["public_facts"]["field_consensus"] == ["A source-reported consensus"]


def test_seed_focus_cannot_replace_explicit_user_scope(monkeypatch, tmp_path):
    _, requests, _ = _run_stage(
        monkeypatch, tmp_path, refinement_budget=0,
        scope="Keep the study population fixed", scope_source="config_explicit",
        seed_scope="Explore a different population",
    )

    for context in requests:
        assert context["refinement_scope"] == "Keep the study population fixed"
        assert context["proposed_scope"] == "Explore a different population"
        assert context["task_contract"]["user_constraints"][0]["text"] == "Keep the study population fixed"


def test_schedule_and_focus_survive_artifact_and_candidate_projection():
    artifact = {}
    schedule = {"policy": "gap_coverage_first", "eligible_gap_ids": ["gap-a"]}
    artifact_set(artifact, "gap_route_schedule", schedule)
    assert artifact_get(artifact, "gap_route_schedule") == schedule
    focus = {"primary_gap_id": "gap-a", "iteration_budget": 3}
    candidate = {"gap_search_focus": focus, "scientific_intervention": {"gap_search_focus": focus}}
    assert compact_candidate_entry(candidate)["gap_search_focus"] == focus
    assert compact_direction_document(candidate)["gap_search_focus"] == focus
