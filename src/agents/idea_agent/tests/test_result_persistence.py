from __future__ import annotations

import json
from pathlib import Path

from src.agents.idea_agent.utils.core.json_utils import read_json_file
from src.agents.idea_agent.utils.workflow.ligagent_flow import (
    save_candidate_payload,
    save_idea_result_payload,
)
from src.agents.idea_agent.utils.workflow.ligagent_handlers import _build_mode_result_document
from src.agents.idea_agent.agent.artifacts import artifact_init
from src.agents.idea_agent.utils.workflow.result_persistence import (
    compact_candidate_entry,
    compact_debate_summary,
    compact_result_payload,
)


class _Logger:
    def info(self, *args, **kwargs) -> None:
        return None

    def error(self, *args, **kwargs) -> None:
        raise AssertionError(args)


def _candidate() -> dict:
    return {
        "title": "A candidate",
        "abstract": "A bounded abstract.",
        "core_contribution": "A mechanism claim.",
        "method": "Compare the mechanism-specific observation.",
        "components": ["sample preparation"],
        "root_domains": ["materials_science"],
        "scientific_intervention": {
            "profile_id": "materials_mechanistic",
            "contribution_mode": "mechanism",
            "hypothesis_contract": {"central_hypothesis": "The mechanism changes the relation."},
            "paper_graph_context": "x" * 200_000,
        },
        "evaluation": {"novelty": 0.8, "composite": 0.7, "debug_payload": "y" * 100_000},
        "search_score": 0.7,
        "search_path": "root -> mechanism",
        "search_trace": [{"payload": "z" * 200_000}],
        "pareto_candidates": {"novel": {"payload": "p" * 200_000}},
        "idea_result": {"title": "Nested result", "directions": [{"title": "Nested"}]},
    }


def test_compact_candidate_drops_diagnostics_but_keeps_root_seed_fields() -> None:
    compact = compact_candidate_entry(_candidate())

    assert compact["title"] == "A candidate"
    assert compact["components"] == ["sample preparation"]
    assert compact["scientific_intervention"]["profile_id"] == "materials_mechanistic"
    assert "search_trace" not in compact
    assert "pareto_candidates" not in compact
    assert "idea_result" not in compact
    assert "paper_graph_context" not in compact["scientific_intervention"]
    assert "debug_payload" not in compact["evaluation"]


def test_compact_result_projects_stage_snapshots_and_handoff_evidence() -> None:
    payload = {
        "schema_version": "idea_result_v5",
        "topic": "Topic",
        "title": "Final idea",
        "abstract": "Abstract",
        "method": "Method",
        "scientific_spec": {"central_hypothesis": "H"},
        "directions": [
            {
                "direction_mode": "evidence_first",
                "title": "Direction",
                "hypothesis": {"central_hypothesis": "H"},
                "experiment_handoff": {
                    "gap_ids": ["gap-1"],
                    "gap_records": [{"gap_id": "gap-1", "statement": "Unresolved", "full": "x" * 100_000}],
                    "evidence_roles": [{
                        "role_id": "role-1",
                        "evidence_role": "direct",
                        "expected_role": "direct observation",
                        "claim_limits": "Only supports the stated regime.",
                        "excerpt": "y" * 100_000,
                    }],
                    "source_anchors": [{
                        "anchor_id": "anchor-1",
                        "paper_id": "p-1",
                        "claim_anchor": "The paper reports the mechanism.",
                        "source_pointer": {"section": "Results", "paragraph": 2},
                        "abstract": "z" * 100_000,
                    }],
                },
            }
        ],
        "direction_synthesis": {"directions": [{"direction_mode": "evidence_first", "search_trace": ["raw"]}]},
        "debate_result": {"directions": [{"direction_mode": "evidence_first", "search_trace": ["raw"]}], "round_count": 2},
        "legacy_best_entry": _candidate(),
        "mcts_evolution": {
            "iterations": [{"iteration": 1, "title": "t", "evaluation": {"large": "x" * 100_000}}],
            "pareto_front": {"novel": {"idea": {"title": "P", "components": ["large"]}, "evaluation": {"composite": 0.6}}},
        },
    }

    compact = compact_result_payload(payload)
    encoded = json.dumps(compact, ensure_ascii=False)

    assert len(encoded) < 50_000
    assert compact["directions"][0]["experiment_handoff"]["gap_ids"] == ["gap-1"]
    roles = compact["directions"][0]["experiment_handoff"]["evidence_roles"]
    anchors = compact["directions"][0]["experiment_handoff"]["source_anchors"]
    assert roles[0]["expected_role"] == "direct observation"
    assert roles[0]["claim_limits"] == "Only supports the stated regime."
    assert anchors[0]["claim_anchor"] == "The paper reports the mechanism."
    assert anchors[0]["source_pointer"]["section"] == "Results"
    assert compact["direction_synthesis"]["directions"][0]["direction_mode"] == "evidence_first"
    assert compact["debate_result"]["round_count"] == 2
    assert "search_trace" not in compact["legacy_best_entry"]
    assert "evaluation" not in compact["mcts_evolution"]["iterations"][0]


def test_compact_debate_preserves_scientific_challenge_semantics() -> None:
    event = compact_debate_summary(
        {
            "round": 2,
            "direction_mode": "evidence_first",
            "question_type": "causal_mechanism",
            "target_claim": "The treatment changes the outcome through mechanism M.",
            "scientific_concern": "The observed effect may have an alternative pathway.",
            "required_revision": "Specify the boundary condition and falsifier.",
            "alternative_explanations": ["Pathway N"],
            "final_scope": "Only the prepared cohort.",
            "final_status": "SCIENTIFICALLY_QUALIFIED_WITH_UNCERTAINTY",
        }
    )

    assert event["target_claim"].startswith("The treatment")
    assert event["scientific_concern"].startswith("The observed")
    assert event["required_revision"].startswith("Specify")
    assert event["alternative_explanations"] == ["Pathway N"]
    assert event["final_scope"] == "Only the prepared cohort."


def test_persisted_json_remains_pretty_indented(tmp_path: Path) -> None:
    logger = _Logger()
    result_path = tmp_path / "idea_result.json"
    candidate_path = tmp_path / "idea_candidate.json"
    payload = {"title": "A", "directions": [], "legacy_best_entry": _candidate()}

    save_idea_result_payload(payload, result_path, logger)
    save_candidate_payload(_candidate(), candidate_path, logger)

    raw_result = result_path.read_text(encoding="utf-8")
    raw_candidate = candidate_path.read_text(encoding="utf-8")
    assert "\n  \"" in raw_result
    assert "\n  \"" in raw_candidate
    assert read_json_file(result_path)["persistence"]["mode"] == "public_compact"


def test_mode_document_uses_raw_candidate_for_hypothesis_projection() -> None:
    source_entry = _candidate()
    source_entry.update(
        {
            "direction_mode": "evidence_first",
            "central_hypothesis": "The mechanism changes the relation.",
            "scientific_object": {"object_type": "interface"},
            "mechanism_or_relation": "interfacial transport",
            "claim_scope": "the prepared interface",
        }
    )
    mode_payload = _build_mode_result_document(
        "Topic",
        {"direction_mode": "evidence_first"},
        source_entry,
        artifact_init(),
        {},
    )

    public_direction = mode_payload["directions"][0]
    assert public_direction["hypothesis"]["central_hypothesis"] == "The mechanism changes the relation."
    assert mode_payload["legacy_best_entry"]["title"] == "A candidate"
    assert "search_trace" not in mode_payload["legacy_best_entry"]
