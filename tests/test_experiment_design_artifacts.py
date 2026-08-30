from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

import pytest

from src.agents.experiment_design_agent.artifacts import (
    AUTHOR_HANDOFF_SCHEMA_VERSION,
    ArtifactValidationError,
    ArtifactWriteError,
    build_author_handoff,
    generate_timestamp,
    write_experiment_design_artifacts,
)
from src.agents.experiment_design_agent.contracts import (
    EVIDENCE_BUNDLE_SCHEMA_VERSION,
    EXPERIMENT_DESIGN_SCHEMA_VERSION,
    OUTCOME_BRANCH_SCHEMA_VERSION,
    RESEARCH_BRIEF_SCHEMA_VERSION,
)
from src.agents.experiment_design_agent.counterexample_analyzer import unavailable_counterexample_analysis
from src.agents.experiment_design_agent.discipline_catalog import resolve_execution_policy
from src.agents.experiment_design_agent.formal_reasoning_planner import unavailable_formal_reasoning_plan


def _brief() -> dict:
    return {
        "schema_version": RESEARCH_BRIEF_SCHEMA_VERSION,
        "brief_id": "brief-1",
        "topic": "Reliable scientific image analysis",
        "discipline_ids": ["17"],
        "selected_direction": {
            "id": "computational_route",
            "title": "Reliable scientific image analysis",
            "central_hypothesis": "The representation improves robust image analysis.",
            "mechanism_or_relation": "The representation changes error behavior under shift.",
        },
        "research_object": {"object_type": "scientific image dataset"},
        "intervention_or_transformation": "Use the proposed representation.",
        "discriminating_observations": ["Robustness changes under held-out shifts."],
        "boundary_conditions": ["Only for the stated dataset family."],
        "alternative_explanations": ["An unrelated preprocessing change explains the effect."],
        "known_unknowns": ["The deployment distribution is not yet known."],
        "evidence_status": "PROPOSED",
        "source": {"idea_result_schema": "idea_result_v5", "direction_id": "computational_route"},
        "reasoning_context": {
            "schema_version": "reasoning_context_v1",
            "selected_direction_id": "computational_route",
            "assumptions": [],
            "claim_scope": "The declared image-analysis proposal.",
            "falsifiers": [],
            "boundary_conditions": ["Only for the stated dataset family."],
            "alternative_explanations": ["An unrelated preprocessing change explains the effect."],
            "formal_symbols": [],
            "gap_records": [],
            "evidence_roles": [],
            "source_anchors": [],
            "upstream_source_paths": [],
            "source_priority": ["selected_direction"],
        },
    }


def _branch(branch_id: str) -> dict:
    return {
        "schema_version": OUTCOME_BRANCH_SCHEMA_VERSION,
        "branch_id": branch_id,
        "trigger": "The preregistered decision rule for this branch is met.",
        "interpretation": "Interpret the result only within the declared design boundary.",
        "conclusion_scope": "The stated scientific image dataset family.",
        "improvement_actions": ["Update the next design iteration from this branch."],
        "evidence_status": "EXPECTED_NOT_OBSERVED",
    }


def _design() -> dict:
    policy = resolve_execution_policy(["17"])
    design = {
        "schema_version": EXPERIMENT_DESIGN_SCHEMA_VERSION,
        "design_id": "design-1",
        "evidence_status": "DESIGNED_NOT_EXECUTED",
        "execution_policy": {
            "mode": policy["mode"],
            "allow_digital_execution": False,
            "reason": policy["reason"],
        },
        "research_brief": _brief(),
        "evidence_bundle": {
            "schema_version": EVIDENCE_BUNDLE_SCHEMA_VERSION,
            "brief_id": "brief-1",
            "evidence_cards": [],
            "coverage": {
                "required_slots": ["comparison", "measurement"],
                "covered_slots": [],
                "uncovered_slots": ["comparison", "measurement"],
            },
        },
        "research_design": {
            "design_type": "comparative computational study",
            "experimental_unit": "held-out scientific image",
            "time_structure": "fixed train-validation-test split",
        },
        "hypothesis_mapping": [
            {
                "hypothesis_id": "H1",
                "claim": "The representation improves robustness.",
                "observables": ["shifted-distribution error"],
                "decision_rule": "Compare against the preregistered baseline.",
            }
        ],
        "variables_and_operationalization": {
            "independent_variables": [],
            "dependent_variables": [],
            "control_variables": [],
            "confounders": [],
            "operational_definitions": [],
        },
        "sampling_and_eligibility": {
            "source": {"status": "needs_human_input"},
            "eligibility_criteria": {"status": "needs_human_input"},
            "sample_size_or_power_basis": {"status": "needs_human_input"},
        },
        "measurement_and_calibration": {
            "instruments": [],
            "measurement_plan": {"status": "needs_human_input"},
            "calibration": {"status": "not_applicable"},
            "quality_control": {"status": "needs_human_input"},
        },
        "comparison_and_robustness": {
            "groups": [],
            "controls": [],
            "baselines": [],
            "comparisons": [],
            "ablation_sensitivity_robustness": [],
        },
        "analysis_plan": {
            "randomization": {"status": "needs_human_input"},
            "blinding": {"status": "not_applicable"},
            "repetitions": {"status": "needs_human_input"},
            "batch_effects": {"status": "needs_human_input"},
            "missing_data": {"status": "needs_human_input"},
            "statistical_analysis": {"status": "needs_human_input"},
        },
        "data_governance_and_reproducibility": {
            "data_management": {"status": "needs_human_input"},
            "reproducibility": {"status": "needs_human_input"},
        },
        "outcome_branches": [
            _branch("supports_mechanism"),
            _branch("partial_or_heterogeneous"),
            _branch("null_or_contradictory"),
            _branch("uninformative_or_invalid"),
        ],
        "risk_and_human_review": {
            "risk_level": "medium",
            "human_review_required": False,
            "review_triggers": [],
            "execution_prohibited": True,
        },
        "open_design_questions": ["Select the final dataset and baseline."],
        "observed_results": [],
        "validation_report": {
            "status": "DRAFT_REQUIRES_INPUT",
            "errors": [],
            "warnings": ["Evidence retrieval has not yet completed."],
        },
    }
    _canonicalize_design(design)
    return design


def _canonicalize_design(design: dict) -> None:
    statuses = dict(design.get("field_statuses") or {})
    sections = {
        "research_design",
        "hypothesis_mapping",
        "variables_and_operationalization",
        "sampling_and_eligibility",
        "measurement_and_calibration",
        "comparison_and_robustness",
        "analysis_plan",
        "data_governance_and_reproducibility",
        "template_details",
    }

    def visit(value: object, path: str) -> object:
        if isinstance(value, dict):
            output = {}
            for key, child in value.items():
                child_path = f"{path}.{key}" if path else key
                if key == "status":
                    statuses.setdefault(path, child)
                else:
                    output[key] = visit(child, child_path)
            return output
        if isinstance(value, list):
            return [visit(child, f"{path}[{index}]") for index, child in enumerate(value)]
        return value

    for section in sections:
        if section in design:
            design[section] = visit(design[section], section)
    design["field_statuses"] = statuses


def test_writer_generates_three_consistent_artifacts_and_author_handoff(tmp_path: Path) -> None:
    design = _design()
    generated_at = datetime(2026, 8, 28, 0, 46, 10, 870347, tzinfo=timezone(timedelta(hours=9)))
    payload = {
        "status": "COMPLETED",
        "intake": {
            "canonical_input_path": "/mnt/c/project/idea_result.json",
            "selected_direction_id": "computational_route",
            "audit_source_paths": {"idea_result": "/mnt/c/project/idea_result.json"},
        },
        "preparation": {
            "unknown_items": [{"field_path": "sampling.source", "status": "needs_human_input"}]
        },
        "experiment_design": design,
    }

    paths = write_experiment_design_artifacts(
        payload,
        tmp_path,
        generated_at=generated_at,
        idea_result_path="/mnt/c/project/idea_result.json",
    )

    assert generate_timestamp(generated_at) == "20260828-004610-870347"
    assert paths.timestamp == "20260828-004610-870347"
    assert paths.collision_index == 0
    assert paths.experiment_design_json.name == "experiment_design_20260828-004610-870347.json"
    assert paths.experiment_design_markdown.name == "experiment_design_20260828-004610-870347.md"
    assert paths.author_json.name == "experiment_design_author_20260828-004610-870347.json"
    assert json.loads(paths.experiment_design_json.read_text(encoding="utf-8")) == design

    markdown = paths.experiment_design_markdown.read_text(encoding="utf-8")
    assert "## Expected Outcome Branches" in markdown
    assert "Execution Mode: `DESIGN_ONLY`" in markdown
    assert "Observed Results: none" in markdown
    snapshot = markdown.split("~~~json\n", 1)[1].split("\n~~~", 1)[0]
    assert json.loads(snapshot) == design

    author = json.loads(paths.author_json.read_text(encoding="utf-8"))
    assert author["schema_version"] == AUTHOR_HANDOFF_SCHEMA_VERSION
    assert author["source_design_id"] == "design-1"
    assert "experiment_design" not in author
    assert "evidence_bundle" not in author
    assert "formal_reasoning_plan" not in author
    assert author["selected_direction"] == design["research_brief"]["selected_direction"]
    assert author["research_design"] == design["research_design"]
    assert author["reasoning_context"] == design["research_brief"]["reasoning_context"]
    assert all(item["field_path"] != "sampling.source" for item in author["unknown_items"])
    assert {
        (item["field_path"], item["status"])
        for item in author["unknown_items"]
    } >= {
        ("sampling_and_eligibility.source", "needs_human_input"),
        ("open_design_questions[1]", "needs_human_input"),
        ("research_brief.known_unknowns[1]", "needs_human_input"),
    }
    assert all(item["reason"] != "missing_required_field" for item in author["unknown_items"])
    assert author["authoring_constraints"]["observed_results_are_absent"] is True
    assert author["provenance"]["idea_result_path"] == "/mnt/c/project/idea_result.json"


def test_author_handoff_derives_final_unknowns_and_review_items_without_preparation_snapshot() -> None:
    design = _design()
    design["formal_reasoning_plan"] = unavailable_formal_reasoning_plan(
        reason="The final formal definition must be supplied."
    )
    design["counterexample_analysis"] = unavailable_counterexample_analysis(
        reason="The final assumption check remains unresolved."
    )
    design["variable_claim_model"] = {
        "schema_version": "variable_claim_model_v1",
        "status": "complete_or_requires_input",
        "claims": [],
        "variables": [],
        "unknown_items": [
            {
                "field_path": "variable_claim_model.V1.definition",
                "status": "needs_formal_definition",
                "reason": "The final operational definition is unresolved.",
            }
        ]
    }
    design["risk_and_human_review"] = {
        "risk_level": "medium",
        "human_review_required": True,
        "review_triggers": ["A qualified reviewer must confirm the boundary."],
        "execution_prohibited": True,
    }
    handoff = build_author_handoff(
        {
            "preparation": {
                "unknown_items": [
                    {
                        "field_path": "stale.preparation.field",
                        "status": "needs_human_input",
                        "reason": "missing_required_field",
                    }
                ]
            },
            "experiment_design": design,
        }
    )

    assert all(item["field_path"] != "stale.preparation.field" for item in handoff["unknown_items"])
    assert {
        item["field_path"]
        for item in handoff["unknown_items"]
    } >= {
        "formal_reasoning_plan",
        "counterexample_analysis",
        "variable_claim_model.V1.definition",
    }
    assert len(handoff["unknown_items"]) == len(
        {(item["field_path"], item["status"]) for item in handoff["unknown_items"]}
    )
    assert handoff["review_items"] == [
        {
            "field_path": "counterexample_analysis",
            "status": "review_required",
            "reason": "The final canonical counterexample_analysis status requires qualified human review.",
        },
        {
            "field_path": "formal_reasoning_plan",
            "status": "review_required",
            "reason": "The final canonical formal_reasoning_plan status requires qualified human review.",
        },
        {
            "field_path": "risk_and_human_review.human_review_required",
            "status": "review_required",
            "reason": "The final canonical risk gate requires qualified human review.",
        },
        {
            "field_path": "risk_and_human_review.review_triggers[1]",
            "status": "review_required",
            "reason": "A qualified reviewer must confirm the boundary.",
        },
    ]


def test_writer_uses_collision_suffix_without_overwriting_existing_artifacts(tmp_path: Path) -> None:
    generated_at = datetime(2026, 8, 28, 0, 46, 10, 870347, tzinfo=timezone.utc)
    first = write_experiment_design_artifacts(
        _design(),
        tmp_path,
        generated_at=generated_at,
    )
    original = first.experiment_design_json.read_text(encoding="utf-8")

    second = write_experiment_design_artifacts(
        _design(),
        tmp_path,
        generated_at=generated_at,
    )

    assert second.collision_index == 1
    assert second.experiment_design_json.name.endswith("_1.json")
    assert second.experiment_design_markdown.name.endswith("_1.md")
    assert second.author_json.name.endswith("_1.json")
    assert first.experiment_design_json.read_text(encoding="utf-8") == original


def test_writer_validates_before_creating_output(tmp_path: Path) -> None:
    design = _design()
    design["observed_results"] = [{"result": "not allowed"}]
    output_dir = tmp_path / "not-created"

    with pytest.raises(ArtifactValidationError, match="validation failed"):
        write_experiment_design_artifacts(design, output_dir)

    assert not output_dir.exists()


def test_author_handoff_rejects_an_unvalidated_design() -> None:
    design = _design()
    design["observed_results"] = [{"result": "not allowed"}]

    with pytest.raises(ArtifactValidationError, match="validation failed"):
        build_author_handoff(design)


def test_author_handoff_preserves_evidence_card_support_statement() -> None:
    design = _design()
    design["evidence_bundle"]["evidence_cards"] = [
        {
            "card_id": "EC-1",
            "claim_slot": "mechanism",
            "statement": "The source supports the bounded mechanism statement.",
            "design_implication": "The proposal must keep the mechanism within its stated boundary.",
            "source_id": "W1",
            "source_location": "fulltext:W1:section-1",
            "evidence_level": "fulltext",
            "evidence_excerpt": "The source supports the bounded mechanism statement in section one.",
            "limitations": [],
            "does_not_establish": [],
        }
    ]
    design["evidence_bundle"]["paper_registry"] = [
        {
            "canonical_paper_id": "W1",
            "title": "A traceable source record",
            "authors": ["Ada Example", "Ben Example"],
            "year": "2026",
            "venue": "Journal of Testable Plans",
            "doi": "10.1000/w1",
            "url": "https://example.test/W1",
            "citation_rendering_status": "RENDERABLE",
            "citation_missing_fields": [],
            "provider_ids": {"canonical": "W1"},
            "providers": ["test"],
            "query_task_ids": [],
            "content_availability": "fulltext",
            "fulltext_source_location": "fulltext:W1",
        }
    ]

    handoff = build_author_handoff(design)
    compact_card = handoff["source_registry"]["evidence_cards_by_id"]["EC-1"]
    citation = handoff["source_registry"]["citation_registry"][0]

    assert compact_card["support_statement"] == "The source supports the bounded mechanism statement."
    assert citation["citation_rendering_status"] == "RENDERABLE"
    assert citation["bibliographic_metadata"] == {
        "authors": ["Ada Example", "Ben Example"],
        "title": "A traceable source record",
        "year": "2026",
        "venue": "Journal of Testable Plans",
        "doi": "10.1000/w1",
        "url": "https://example.test/W1",
    }


def test_writer_removes_partial_artifacts_when_atomic_publish_fails(monkeypatch, tmp_path: Path) -> None:
    import src.agents.experiment_design_agent.artifacts as artifacts

    original_publish = artifacts._publish_without_overwrite
    call_count = 0

    def fail_on_second_publish(temp_path: Path, target_path: Path) -> None:
        nonlocal call_count
        call_count += 1
        if call_count == 2:
            raise OSError("simulated publish failure")
        original_publish(temp_path, target_path)

    monkeypatch.setattr(artifacts, "_publish_without_overwrite", fail_on_second_publish)

    with pytest.raises(ArtifactWriteError, match="Cannot publish"):
        write_experiment_design_artifacts(
            _design(),
            tmp_path,
            timestamp="20260828-004610-870347",
        )

    assert list(tmp_path.glob("experiment_design_*.json")) == []
    assert list(tmp_path.glob("experiment_design_*.md")) == []
    assert list(tmp_path.glob(".*.tmp")) == []
