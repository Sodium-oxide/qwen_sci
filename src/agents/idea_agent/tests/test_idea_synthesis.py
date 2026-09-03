from __future__ import annotations

from types import SimpleNamespace

from src.agents.idea_agent.utils.workflow.idea_synthesis import (
    DEFAULT_DIRECTION_MODES,
    synthesize_direction_set,
)


def _entry(mode: str, *, title: str | None = None, score: float = 1.0) -> dict:
    return {
        "candidate_id": f"candidate-{mode}",
        "idea_taste_mode": mode,
        "direction_mode": mode,
        "title": title or f"{mode} idea",
        "abstract": f"Abstract for {mode}.",
        "core_contribution": f"Contribution for {mode}.",
        "method": "Use the profile-native mechanism and observe its discriminating relation.",
        "central_hypothesis": "The shared mechanism changes the target relation.",
        "mechanism_or_relation": "shared mechanism",
        "claim_scope": "Within the prepared scope.",
        "target_gap_ids": ["gap-1"],
        "evidence_requirement": "Observe the mechanism-specific contrast.",
        "evaluation": {"composite": score, "novelty": score, "feasibility": score},
        "search_score": score,
        "experiment_design": "must not survive synthesis",
    }


def test_synthesis_preserves_all_expected_directions_and_does_not_fuse() -> None:
    entries = [_entry(mode) for mode in DEFAULT_DIRECTION_MODES]

    result = synthesize_direction_set(entries)

    assert result["synthesis_mode"] == "direction_preserving"
    assert [item["direction_mode"] for item in result["directions"]] == list(DEFAULT_DIRECTION_MODES)
    assert len(result["directions"]) == 5
    assert all(item["idea_source"] == "direction_synthesis" for item in result["directions"])
    assert all("experiment_design" not in item for item in result["directions"])
    assert result["cross_direction_notes"]


def test_missing_direction_uses_shared_candidate_and_marks_lower_confidence() -> None:
    entries = [_entry(mode) for mode in DEFAULT_DIRECTION_MODES if mode != "evidence_first"]

    result = synthesize_direction_set(entries)
    evidence_first = next(item for item in result["directions"] if item["direction_mode"] == "evidence_first")

    assert len(result["directions"]) == 5
    assert evidence_first["scientificity_status"] == "LOWER_CONFIDENCE"
    assert evidence_first["fallback_reason"] == "direction_candidate_unavailable"
    assert evidence_first["direction_reframing"]["requested_direction"] == "evidence_first"


def test_empty_mcts_results_still_materialize_all_direction_placeholders() -> None:
    result = synthesize_direction_set([], mode_results={mode: None for mode in DEFAULT_DIRECTION_MODES})

    assert len(result["directions"]) == 5
    assert {item["direction_mode"] for item in result["directions"]} == set(DEFAULT_DIRECTION_MODES)
    assert all(item["scientificity_status"] == "LOWER_CONFIDENCE" for item in result["directions"])


def test_missing_direction_prefers_pareto_candidate_before_shared_pool() -> None:
    entries = [_entry(mode) for mode in DEFAULT_DIRECTION_MODES if mode != "bridge_builder"]
    entries[0]["pareto_candidates"] = {
        "highest_novelty": {
            "idea": _entry("moonshot_inventor", title="Pareto bridge candidate", score=9.0),
            "score": 9.0,
        }
    }
    pareto_result = SimpleNamespace(
        best=None,
        pareto={
            "highest_feasibility": SimpleNamespace(
                to_dict=lambda: {
                    "idea": _entry("bridge_builder", title="Bridge Pareto", score=8.0),
                    "score": 8.0,
                }
            )
        },
    )

    result = synthesize_direction_set(
        entries,
        mode_results={"bridge_builder": pareto_result},
    )
    bridge = next(item for item in result["directions"] if item["direction_mode"] == "bridge_builder")

    assert bridge["title"] == "Bridge Pareto"
    assert bridge["fallback_reason"] == "direction_candidate_unavailable"
    assert bridge["source_candidate_ids"]
