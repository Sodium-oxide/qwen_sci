from __future__ import annotations

from src.agents.idea_agent.utils.mcts.idea_routes import IDEA_ROUTE_POLICIES
from src.agents.idea_agent.utils.workflow.ligagent_handlers import (
    _build_route_matrix_tasks,
    _resolve_screening_routes,
    _select_refinement_seeds,
    _two_stage_mcts_budget,
)


def _seed(index: int) -> dict[str, str]:
    return {"idea_id": f"seed-{index:02d}"}


def test_two_stage_mcts_schedule_uses_264_ordinary_iterations() -> None:
    seeds = [_seed(index) for index in range(1, 13)]
    screening_routes = _resolve_screening_routes(
        ["object_substitution", "mechanism_replacement"],
        route_count=2,
    )
    screening_tasks = _build_route_matrix_tasks(seeds, screening_routes)
    screening_scores = {
        seed["idea_id"]: float(index)
        for index, seed in enumerate(seeds, start=1)
    }

    top_seeds = _select_refinement_seeds(seeds, screening_scores, top_seed_count=3)
    refinement_routes = IDEA_ROUTE_POLICIES[:5]
    refinement_tasks = _build_route_matrix_tasks(top_seeds, refinement_routes)
    budget = _two_stage_mcts_budget(
        screening_seed_count=len(seeds),
        screening_route_count=len(screening_routes),
        screening_iterations=6,
        refinement_seed_count=len(top_seeds),
        refinement_route_count=len(refinement_routes),
        refinement_iterations=8,
    )

    assert len(screening_tasks) == 24
    assert len(refinement_tasks) == 15
    assert [route.route_id for route in screening_routes] == [
        "object_substitution",
        "mechanism_replacement",
    ]
    assert [seed["idea_id"] for seed in top_seeds] == ["seed-12", "seed-11", "seed-10"]
    assert budget == {
        "screening_searches": 24,
        "refinement_searches": 15,
        "screening_iterations": 144,
        "refinement_iterations": 120,
        "total_iterations": 264,
    }


def test_refinement_ranking_prefers_successful_screening_scores() -> None:
    seeds = [_seed(index) for index in range(1, 6)]

    selected = _select_refinement_seeds(
        seeds,
        {
            "seed-01": 7.0,
            "seed-03": 9.0,
            "seed-05": 8.0,
        },
        top_seed_count=3,
    )

    assert [seed["idea_id"] for seed in selected] == ["seed-03", "seed-05", "seed-01"]


def test_refinement_ranking_uses_failed_seed_only_when_slots_remain() -> None:
    seeds = [_seed(index) for index in range(1, 5)]

    selected = _select_refinement_seeds(
        seeds,
        {"seed-02": 5.0},
        top_seed_count=3,
    )

    assert [seed["idea_id"] for seed in selected] == ["seed-02", "seed-01", "seed-03"]
