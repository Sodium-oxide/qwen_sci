from __future__ import annotations

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
