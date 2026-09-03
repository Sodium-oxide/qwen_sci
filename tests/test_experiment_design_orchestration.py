"""Focused tests for Batch B design-state orchestration."""

from __future__ import annotations

from copy import deepcopy
from io import StringIO
import json

import pytest

from src.agents.experiment_design_agent import (
    DESIGN_ONLY,
    DIGITAL_EXECUTION_ELIGIBLE,
    EVIDENCE_RETRIEVAL_PLANNER_PROMPT,
    CompletenessValidator,
    EvidenceRetrievalPlanner,
    ExperimentDesignOrchestrator,
    IdeaResultAdapter,
    TemplateRouter,
)
from src.agents.experiment_design_agent.contracts import RESEARCH_BRIEF_SCHEMA_VERSION
from src.agents.experiment_design_agent.evidence_planner import _baseline_queries
from src.agents.experiment_design_agent.run_logging import ExperimentDesignRunLogger


DESIGN_FIXTURES = (
    ("mathematics", "26", "mathematics_theory", "Stability conditions for a symbolic numerical method."),
    ("materials", "25", "materials_chemical", "Interface stability of a coating material."),
    ("life", "13", "life_veterinary", "Cellular response to a declared perturbation."),
    ("engineering", "22", "engineering_energy", "Failure behavior of a designed energy subsystem."),
    ("environment", "23", "earth_environment_agro", "Environmental response to a declared exposure."),
    ("clinical", "27", "clinical_health", "Observed clinical outcome in a defined patient population."),
)


def _brief(discipline_id: str, topic: str) -> dict:
    return {
        "schema_version": RESEARCH_BRIEF_SCHEMA_VERSION,
        "brief_id": f"brief-{discipline_id}",
        "topic": topic,
        "discipline_ids": [discipline_id],
        "selected_direction": {
            "id": f"route-{discipline_id}",
            "title": topic,
            "central_hypothesis": "The declared intervention is associated with the declared observable under the stated conditions.",
            "mechanism_or_relation": "The relevant mechanism or relation remains to be checked with design evidence.",
        },
        "research_object": {"description": "A declared scientific system with an unresolved measurement plan."},
        "intervention_or_transformation": "A declared intervention or transformation.",
        "discriminating_observations": ["A predeclared observable that distinguishes the target relation from alternatives."],
        "boundary_conditions": ["Declared boundary conditions require evidence planning."],
        "alternative_explanations": ["Alternative explanations require explicit comparison and control planning."],
        "known_unknowns": ["Final sampling or availability constraints are not yet confirmed."],
        "evidence_status": "PROPOSED",
        "source": {"idea_result_schema": "idea_result_v5", "direction_id": f"route-{discipline_id}"},
        "reasoning_context": {
            "schema_version": "reasoning_context_v1",
            "selected_direction_id": f"route-{discipline_id}",
            "assumptions": [],
            "claim_scope": "",
            "falsifiers": [],
            "boundary_conditions": [],
            "alternative_explanations": [],
            "formal_symbols": [],
            "gap_records": [],
            "evidence_roles": [],
            "source_anchors": [],
            "upstream_source_paths": [],
        },
    }


def _json_llm(prompt: str, **kwargs: object) -> dict:
    assert kwargs["response_format"] == {"type": "json_object"}
    if "Evidence Retrieval Planner" in prompt:
        return {
            "queries": [
                {key: value for key, value in task.items() if key != "task_id"}
                for task in _baseline_queries(_brief("26", "A declared research relation."))
            ]
        }
    if "Variable and Claim Extractor" in prompt:
        return {
            "schema_version": "variable_claim_model_v1",
            "status": "complete_or_requires_input",
            "claims": [],
            "variables": [],
            "unknown_items": [],
        }
    return {"open_design_questions": ["Confirm unresolved design requirements."]}


@pytest.mark.parametrize(("fixture_name", "discipline_id", "template_id", "topic"), DESIGN_FIXTURES)
def test_design_fixtures_stay_in_design_only_mode(
    fixture_name: str,
    discipline_id: str,
    template_id: str,
    topic: str,
) -> None:
    prepared = ExperimentDesignOrchestrator(llm_call=_json_llm).prepare(_brief(discipline_id, topic))

    assert prepared["scope_gate"]["status"] == "IN_SCOPE", fixture_name
    assert prepared["scope_gate"]["execution"]["mode"] == DESIGN_ONLY, fixture_name
    assert prepared["scope_gate"]["execution"]["execution_prohibited"] is True, fixture_name
    assert prepared["template_routing"]["primary_template"] == template_id, fixture_name
    assert prepared["evidence_retrieval_plan"]["planning_mode"] == "QUERY_PLANNING_ONLY", fixture_name
    assert [task["slot"] for task in prepared["evidence_retrieval_plan"]["queries"]] == [
        "mechanism",
        "research_object_measurability",
        "study_design",
        "comparison_controls",
        "measurement_calibration",
        "statistics_bias",
        "boundary_conditions",
        "risk_ethics_reproducibility",
    ], fixture_name
    assert prepared["evidence_retrieval_plan"]["retrieved_evidence"] == [], fixture_name
    assert prepared["observed_results"] == [], fixture_name
    assert prepared["completeness"]["status"] == "DRAFT_REQUIRES_INPUT", fixture_name
    assert prepared["unknown_items"], fixture_name


def test_clinical_fixture_requires_human_review_and_never_executes() -> None:
    prepared = ExperimentDesignOrchestrator(llm_call=_json_llm).prepare(_brief("27", "Clinical outcome in a patient population."))

    review = prepared["risk_and_human_review"]
    assert review["human_review_required"] is True
    assert "CLINICAL_OR_HEALTH_EXPERT_REVIEW" in review["review_triggers"]
    assert prepared["validation_report"]["status"] == "BLOCKED_BY_RISK_REVIEW"
    assert prepared["scope_gate"]["execution"]["mode"] == DESIGN_ONLY


def test_cs_remains_design_only_when_future_eligibility_is_enabled() -> None:
    prepared = ExperimentDesignOrchestrator(allow_digital_execution=True, llm_call=_json_llm).prepare(
        _brief("17", "Robust evaluation of a computational representation.")
    )

    execution = prepared["scope_gate"]["execution"]
    assert execution["mode"] == DESIGN_ONLY
    assert execution["execution_prohibited"] is True
    assert execution["future_digital_execution_eligibility"] == DIGITAL_EXECUTION_ELIGIBLE


def test_scope_gate_blocks_excluded_fields_before_query_planning() -> None:
    prepared = ExperimentDesignOrchestrator().prepare(_brief("32", "A psychology study outside the supported catalog."))

    assert prepared["scope_gate"]["status"] == "BLOCKED_BY_SCOPE"
    assert prepared["template_routing"]["status"] == "NOT_ROUTED"
    assert prepared["evidence_retrieval_plan"]["planning_status"] == "NOT_PLANNED_BLOCKED_SCOPE"
    assert prepared["evidence_retrieval_plan"]["queries"] == []
    assert prepared["validation_report"]["status"] == "BLOCKED_BY_SCOPE"


def test_llm_query_plan_is_prompted_and_accepted_only_as_query_tasks() -> None:
    brief = _brief("25", "Material interface stability.")
    routing = TemplateRouter().route(brief)
    planner = EvidenceRetrievalPlanner()
    baseline = {
        "queries": _baseline_queries(brief),
    }
    submitted: dict[str, str] = {}

    def llm_call(prompt: str, **kwargs: object) -> dict:
        assert kwargs["response_format"] == {"type": "json_object"}
        submitted["prompt"] = prompt
        return {"queries": [{key: value for key, value in task.items() if key != "task_id"} for task in baseline["queries"]]}

    planned = planner.plan(brief, routing, llm_call=llm_call)

    assert EVIDENCE_RETRIEVAL_PLANNER_PROMPT in submitted["prompt"]
    assert "Do not retrieve, cite, invent" in submitted["prompt"]
    assert "Do not emit any discipline or OpenAlex field filter" in submitted["prompt"]
    assert planned["llm_used"] is True
    assert planned["retrieved_evidence"] == []
    assert planned["query_variant_count"] == sum(len(task["query_variants"]) for task in planned["queries"])
    assert all("openalex_field_filter" not in task for task in planned["queries"])
    assert all(
        1 <= len(task["query_variants"]) <= 2
        and all("doi" not in variant["query"].casefold() for variant in task["query_variants"])
        for task in planned["queries"]
    )


def test_query_planner_rejects_source_like_llm_output() -> None:
    brief = _brief("22", "A safe engineering system boundary study.")
    routing = TemplateRouter().route(brief)

    with pytest.raises(ValueError, match="llm_query_plan_contains_source_or_doi:mechanism"):
        EvidenceRetrievalPlanner().plan(
            brief,
            routing,
            llm_call=lambda _, **__: {
                "queries": [
                    {
                        "slot": "mechanism",
                        "objective": "A source-backed statement from https://example.org.",
                        "keywords": ["engineering"],
                        "query_variants": [
                            {
                                "variant_id": "core",
                                "query": "engineering mechanism",
                                "purpose": "Find a mechanism source.",
                            }
                        ],
                        "evidence_needed": "A future check.",
                    }
                ]
            },
        )


def test_query_planner_accepts_single_term_variants_and_logs_them(tmp_path) -> None:
    brief = _brief("25", "Material interface stability.")
    routing = TemplateRouter().route(brief)
    response = {
        "queries": [
            {key: value for key, value in task.items() if key != "task_id"}
            for task in _baseline_queries(brief)
        ]
    }
    response["queries"][1]["query_variants"][1]["query"] = "single"
    console = StringIO()
    logger = ExperimentDesignRunLogger(
        "planner-log-test",
        jsonl_path=tmp_path / "planner.jsonl",
        console_stream=console,
    )

    planned = EvidenceRetrievalPlanner().plan(
        brief,
        routing,
        llm_call=lambda _, **__: response,
        logger=logger,
    )
    logger.close()

    assert planned["planning_status"] == "READY_FOR_RETRIEVAL"
    records = [json.loads(line) for line in (tmp_path / "planner.jsonl").read_text(encoding="utf-8").splitlines()]
    variant_records = [record for record in records if record["event"] == "query_plan_variant_received"]
    assert variant_records
    assert any(
        record["slot"] == "research_object_measurability"
        and record["variant_position"] == 2
        and record["query"] == "single"
        and record["query_term_count"] == 1
        for record in variant_records
    )
    assert not any(record["event"] == "query_plan_validation_failed" for record in records)
    assert "query=single" in console.getvalue()


def test_completeness_validator_keeps_unknowns_explicit() -> None:
    brief = _brief("25", "Material interface stability.")
    routing = TemplateRouter().route(brief)
    report = CompletenessValidator().assess(brief, routing)

    assert report["status"] == "DRAFT_REQUIRES_INPUT"
    assert any(item["status"] == "needs_human_input" for item in report["field_assessments"])
    assert any(item["field_path"] == "research_brief.known_unknowns[1]" for item in report["unknown_items"])


def test_idea_result_adapter_only_extracts_the_selected_direction() -> None:
    idea_result = {
        "schema_version": "idea_result_v5",
        "topic": "Stability of a material interface",
        "primary_direction": "materials_route",
        "survey_binding": {},
        "directions": [
            {
                "direction_mode": "materials_route",
                "title": "Materials route",
                "hypothesis": {
                    "central_hypothesis": "A process transformation changes interface stability.",
                    "mechanism_or_relation": "A declared process-structure relation.",
                    "scientific_object": {"description": "material interface"},
                },
                "experiment_handoff": {
                    "claim_to_test": "A process transformation changes interface stability.",
                    "required_observations": ["An interface stability observable."],
                    "known_unknowns": ["Final sample availability."],
                },
            }
        ],
    }

    brief = IdeaResultAdapter().adapt(
        deepcopy(idea_result),
        discipline_ids=["Materials Science"],
        brief_id="materials-brief",
    )

    assert brief["discipline_ids"] == ["25"]
    assert brief["selected_direction"]["id"] == "materials_route"
