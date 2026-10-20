from __future__ import annotations

import logging
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.agents.idea_agent.utils.workflow.advanced_analysis_contract import (
    build_advanced_analysis_repair_prompt,
    validate_advanced_analysis_response,
)


def _valid_response() -> dict:
    mature_idea = {
        "idea_id": "seed-1",
        "title": "A grounded mature idea",
        "hypothesis": "The stated mechanism changes the outcome.",
        "scientific_object": "The target physical process",
        "mechanism": "A bounded causal relation",
        "assumptions": ["The boundary condition holds."],
        "evidence_basis": ["SURVEY_ANCHOR: The survey identifies the missing relation."],
        "target_gap_ids": ["gap-1"],
        "refinement_scope": "Derive and test the bounded relation.",
        "falsifier": "A measurement that contradicts the predicted relation.",
        "counterexamples": ["The relation fails outside the stated boundary."],
        "retrieval_queries": ["bounded causal relation evidence"],
        "mechanism_chain": ["object -> mechanism -> observable consequence"],
        "validation_targets": ["Derive the predicted boundary."],
        "anchor_policy": "scoped_survey_anchor",
        "maturity_status": "mature",
        "idea_source": "survey_gap",
        "lineage": "Derived from Survey gap-1.",
        "independence_rationale": "Uses a distinct causal relation and falsifier.",
    }
    return {
        "key_methods": ["Formal causal analysis"],
        "field_consensus": ["The stated boundary constrains the process."],
        "existing_problems": ["The causal relation has not been established."],
        "evaluation_gaps": [{
            "gap": "No direct discriminating measurement exists.",
            "why_it_matters": "The mechanism cannot otherwise be validated.",
            "validation_expectation": "Measure the predicted boundary relation.",
        }],
        "future_directions": ["Test the relation in an adjacent regime."],
        "preserve_current_idea": {"keep_original": False, "reason": ""},
        "mature_ideas": [mature_idea],
        "grounded_mature_idea": "The Survey gap supports a bounded causal relation.",
        "grounded_refinement_scope": "Derive and validate the stated relation.",
        "root_idea": {
            "title": "Bounded relation root idea",
            "abstract": "Derive a bounded causal relation for the target process.",
            "core_contribution": "A falsifiable boundary relation.",
            "method": "Construct and test the formal relation.",
            "risks": "The boundary may not hold in all regimes.",
            "target_defects": ["unclear_mechanism"],
            "rationale": "It directly resolves the Survey bottleneck.",
            "supporting_papers": ["SURVEY_ANCHOR: The Survey identifies the missing relation."],
        },
        "divergent_idea_seeds": [],
        "cross_domain_inspiration": [],
        "tldr": "Derive and validate the bounded relation identified by the Survey.",
    }


def test_advanced_analysis_contract_accepts_complete_response() -> None:
    errors = validate_advanced_analysis_response(
        _valid_response(),
        require_grounded_fields=True,
        require_gap_ids=True,
    )

    assert errors == []


def test_advanced_analysis_contract_rejects_the_partial_response_seen_in_run() -> None:
    response = {
        "key_methods": [],
        "existing_problems": [],
        "future_directions": [],
        "tldr": "A short concept list",
    }

    errors = validate_advanced_analysis_response(
        response,
        require_grounded_fields=True,
        require_gap_ids=True,
    )
    repair_prompt = build_advanced_analysis_repair_prompt("original evidence prompt", response, errors)

    assert "missing required top-level field: root_idea" in errors
    assert "key_methods must be a non-empty list of non-empty strings" in errors
    assert "mature_ideas must be a non-empty list" in errors
    assert "REQUIRED CONTRACT REPAIR" in repair_prompt
    assert "root_idea" in repair_prompt


def _design_response() -> dict:
    response = _valid_response()
    for field in ("field_consensus", "existing_problems", "evaluation_gaps", "future_directions"):
        response[field] = []
    for field in ("assumptions", "evidence_basis", "target_gap_ids", "counterexamples", "retrieval_queries"):
        response["mature_ideas"][0][field] = []
    response["mature_ideas"][0]["idea_source"] = "user_input"
    response["root_idea"]["target_defects"] = []
    response["root_idea"]["supporting_papers"] = []
    response["grounded_refinement_scope"] = ""
    return response


def test_task_design_does_not_require_manufactured_gaps_or_scope() -> None:
    assert validate_advanced_analysis_response(
        _design_response(), require_grounded_fields=True, require_gap_ids=True, valid_gap_ids=[],
    ) == []


def test_unknown_gap_ids_are_rejected_when_reference_set_is_available() -> None:
    errors = validate_advanced_analysis_response(
        _valid_response(), require_grounded_fields=True, require_gap_ids=False, valid_gap_ids=["different-gap"],
    )

    assert any("unknown gap ID: gap-1" in error for error in errors)


def test_design_still_requires_a_method_and_validation_path() -> None:
    response = _design_response()
    response["root_idea"]["method"] = ""
    response["mature_ideas"][0]["validation_targets"] = []

    errors = validate_advanced_analysis_response(response, require_grounded_fields=True, require_gap_ids=False)

    assert "root_idea.method must be a non-empty string" in errors
    assert "mature_ideas[0].validation_targets must not be empty" in errors


@pytest.mark.parametrize("task_mode", ["protocol_design", "idea_refinement"])
def test_advanced_analysis_keeps_requested_design_and_model_scope_advisory(task_mode: str) -> None:
    pytest.importorskip("faiss")
    from src.agents.idea_agent.agent.artifacts import artifact_init, artifact_set
    from src.agents.idea_agent.utils.core.task_contract import build_task_contract
    from src.agents.idea_agent.utils.workflow.ligagent_handlers import execute_advanced_analysis_stage
    from src.agents.idea_agent.utils.workflow.stage_contract import StageContext

    artifact = artifact_init()
    activity = "Refine" if task_mode == "idea_refinement" else "Design"
    task = f"{activity} an optical experiment and predict a distinguishing signal."
    artifact_set(artifact, "topic", ["Optical experiment"])
    artifact_set(artifact, "mature_idea", "Compare two optical mechanisms.")
    artifact_set(artifact, "mature_idea_source", "input_explicit")
    artifact_set(artifact, "refinement_scope", "Only record missing evidence")
    artifact_set(artifact, "refinement_scope_source", "analysis_grounded")
    artifact_set(artifact, "task_contract", build_task_contract(
        original_request=task, interpretation={"task_mode": task_mode, "task_mode_source_quote": f"{activity} an optical experiment"},
    ))
    artifact_set(artifact, "survey_idea_context", {"handoff": {
        "gaps": [], "constraints": {"may_generate_new_gap": False},
        "research_notes": {"working_hypothesis": "Mechanism A changes optical phase."},
    }})
    response = _design_response()
    response["root_idea"]["title"] = "Validation protocol with a predicted distinguishing signal"
    response["grounded_refinement_scope"] = "Focus on optical discrimination"
    invalid = _design_response()
    invalid["root_idea"]["method"] = ""
    runtime = SimpleNamespace(llm_json=Mock(side_effect=[invalid, response]))
    agent = SimpleNamespace(
        artifact=artifact, model="test-model", config={"agent": {"advanced_analysis_contract_retries": 1}},
        logger=logging.getLogger("task-analysis-test"), runtime=runtime, session=None,
    )

    result = execute_advanced_analysis_stage(agent, StageContext(agent, artifact, "analysis"))

    assert runtime.llm_json.call_count == 2
    for call in runtime.llm_json.call_args_list:
        assert task in call.kwargs["prompt"]
        assert "Mechanism A changes optical phase." in call.kwargs["prompt"]
        assert "may_generate_new_gap" not in call.kwargs["prompt"]
    assert result.artifact_patch.replace["refinement_scope"] == ""
    assert result.artifact_patch.replace["proposed_scope"] == "Focus on optical discrimination"
    assert result.artifact_patch.replace["root_idea"]["title"] == response["root_idea"]["title"]
    assert result.metrics["preserved_mature_idea"] is False
