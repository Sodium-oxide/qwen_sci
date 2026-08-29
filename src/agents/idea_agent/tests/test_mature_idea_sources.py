from __future__ import annotations

from src.agents.idea_agent.utils.workflow.mature_idea_sources import _survey_gap_ideas


def test_survey_gap_sources_use_four_atomic_gaps_and_three_leading_pair_combinations() -> None:
    handoff = {
        "gaps": [
            {
                "gap_id": f"gap-{index}",
                "statement": f"Gap statement {index}",
                "target_slot": "mechanism",
            }
            for index in range(1, 6)
        ]
    }

    ideas = _survey_gap_ideas(handoff)
    atomic_ideas = [idea for idea in ideas if not idea["idea_id"].startswith("survey-gap-combination-")]
    combination_ideas = [idea for idea in ideas if idea["idea_id"].startswith("survey-gap-combination-")]

    assert [idea["target_gap_ids"] for idea in atomic_ideas] == [["gap-1"], ["gap-2"], ["gap-3"], ["gap-4"]]
    assert [idea["target_gap_ids"] for idea in combination_ideas] == [
        ["gap-1", "gap-2"],
        ["gap-1", "gap-3"],
        ["gap-2", "gap-3"],
    ]
