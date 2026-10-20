from __future__ import annotations

import pytest

from src.agents.idea_agent.utils.core.task_contract import (
    build_task_contract,
    refinement_scope_context,
    survey_evidence_for_prompt,
    with_task_contract,
)


def test_requirements_must_be_quoted_from_original_input() -> None:
    request = "Design a battery experiment. Use existing instruments. Propose two mechanisms."
    contract = build_task_contract(
        original_request=request,
        interpretation={
            "task_mode": "protocol_design",
            "required_deliverables": [
                {"text": "Invented instruction", "source_quote": "Propose two mechanisms."},
                {"source_quote": "Use a newly purchased instrument."},
            ],
            "user_constraints": [{"source_quote": "Use existing instruments."}],
        },
    )

    assert contract["original_request"] == request
    assert contract["task_mode"] == "protocol_design"
    assert [item["text"] for item in contract["required_deliverables"]] == ["Propose two mechanisms."]
    assert [item["text"] for item in contract["user_constraints"]] == ["Use existing instruments."]


@pytest.mark.parametrize("source", ["input_inferred", "analysis_grounded", "empty", "unknown"])
def test_model_scope_is_advisory(source: str) -> None:
    scope = refinement_scope_context("Do not make predictions", source)

    assert scope["refinement_scope"] == ""
    assert scope["proposed_scope"] == "Do not make predictions"
    assert build_task_contract(topic="A physical process", refinement_scope="Only diagnose", refinement_scope_source=source)["user_constraints"] == []


@pytest.mark.parametrize("source", ["config_explicit", "input_explicit", "user_explicit"])
def test_explicit_scope_remains_a_constraint(source: str) -> None:
    contract = build_task_contract(
        topic="A physical process",
        refinement_scope="Keep the measurement apparatus fixed",
        refinement_scope_source=source,
    )

    assert contract["task_mode"] == "idea_refinement"
    assert contract["user_constraints"][0]["source"] == source
    assert refinement_scope_context("Keep the measurement apparatus fixed", source)["refinement_scope"]


def test_contract_rebuild_is_stable_and_does_not_promote_model_scope() -> None:
    request = "Keep the apparatus fixed and improve the model."
    contract = build_task_contract(
        original_request=request,
        refinement_scope="Keep the apparatus fixed",
        refinement_scope_source="config_explicit",
    )
    rebuilt = build_task_contract(
        original_request=request,
        interpretation=contract,
        refinement_scope="Keep the apparatus fixed",
        refinement_scope_source="config_explicit",
    )

    assert rebuilt == contract


def test_interpreter_cannot_impose_local_refinement_without_source_support() -> None:
    contract = build_task_contract(
        original_request="Propose alternative mechanisms for the process.",
        interpretation={"task_mode": "idea_refinement", "task_mode_source_quote": "Only make minimal edits"},
    )

    assert contract["task_mode"] == "idea_generation"
    assert contract["task_mode_source_quote"] == ""


def test_prompt_preserves_original_request_without_extracted_deliverables() -> None:
    request = "Propose an ecological mechanism and a concrete discriminating observation."
    contract = build_task_contract(original_request=request)
    prompt = with_task_contract("Return the current stage JSON.", contract, scope="Validation only", scope_source="analysis_grounded")

    assert request in prompt
    assert '"refinement_scope": ""' in prompt
    assert '"proposed_scope": "Validation only"' in prompt
    assert "proposed design choices" in prompt
    assert with_task_contract(prompt, contract) == prompt


def test_handoff_projection_preserves_fields_and_separates_operational_constraints() -> None:
    handoff = {
        "topic": "A scientific task",
        "scope": {"research_object": ["A receptor"]},
        "constraints": {"may_generate_new_gap": False, "requires_human_confirmation": True},
        "rubric": {"criteria": ["Mechanistic plausibility"]},
        "research_notes": {"reference_answer": "A mechanistic reference"},
        "score_breakdown": {"evidence_quality": 4},
        "gaps": [{"gap_id": "gap-1", "statement": "An unresolved relation", "rubric_feedback": "Separate observations from predictions"}],
        "anchors": [{"anchor_id": "anchor-1", "text_excerpt": "Reported observation"}],
        "field_consensus": ["Reported agreement"],
    }

    projected = survey_evidence_for_prompt(handoff)

    assert projected["anchors"] == handoff["anchors"]
    assert projected["gaps"] == handoff["gaps"]
    assert projected["rubric"] == handoff["rubric"]
    assert projected["research_notes"] == handoff["research_notes"]
    assert projected["score_breakdown"] == handoff["score_breakdown"]
    assert projected["survey_coverage"] == handoff["scope"]
    assert "constraints" not in projected
    projected["anchors"][0]["text_excerpt"] = "Changed copy"
    projected["rubric"]["criteria"].append("A discriminating observation")
    projected["survey_coverage"]["research_object"].append("Another receptor")
    assert handoff["anchors"][0]["text_excerpt"] == "Reported observation"
    assert handoff["rubric"]["criteria"] == ["Mechanistic plausibility"]
    assert handoff["scope"]["research_object"] == ["A receptor"]


def test_ligagent_transport_keeps_task_during_json_repair(monkeypatch) -> None:
    pytest.importorskip("faiss")
    from src.agents.idea_agent.agent.artifacts import artifact_init, artifact_set
    from src.agents.idea_agent.agent.base import AgentBase
    from src.agents.idea_agent.agent.ligagent import LigAgent
    from src.agents.idea_agent.agent import ligagent as ligagent_module

    captured: list[str] = []

    def fake_chat(self, prompt: str, **kwargs):
        captured.append(prompt)
        return "{}"

    monkeypatch.setattr(AgentBase, "chat", fake_chat)
    monkeypatch.setattr(ligagent_module, "prepare_ligagent_chat_request", lambda **kwargs: (kwargs["model"], kwargs["kwargs"]))
    agent = LigAgent.__new__(LigAgent)
    agent.artifact = artifact_init()
    agent.model = "test-model"
    agent.project_config = {}
    agent.chat_max_retries = 1
    artifact_set(agent.artifact, "task_contract", build_task_contract(original_request="Design an optical test and predict a distinguishing signal."))

    assert agent.chat("Repair only the malformed JSON field.", stage="contract_repair") == "{}"
    assert "Design an optical test and predict a distinguishing signal." in captured[0]
    assert "Repair only the malformed JSON field." in captured[0]


def test_mcts_keeps_user_task_and_treats_inferred_scope_as_advisory() -> None:
    pytest.importorskip("faiss")
    from src.agents.idea_agent.agent.mcts import MemoryGuidedMCTS

    mcts = MemoryGuidedMCTS.__new__(MemoryGuidedMCTS)
    contract = build_task_contract(original_request="Design a battery study and propose competing mechanisms.")
    prepared = mcts.prepare_root_context("battery degradation", {
        "root_domains": ["materials_science"],
        "components": [],
        "task_contract": contract,
        "refinement_scope": "Record uncertainties only",
        "refinement_scope_source": "analysis_grounded",
    })

    assert prepared["task_contract"] == contract
    assert mcts.task_contract == contract
    assert prepared["refinement_scope"] == ""
    assert prepared["proposed_scope"] == "Record uncertainties only"
