from __future__ import annotations

from copy import deepcopy
from io import StringIO
import json
from pathlib import Path

import pytest

from src.agents.experiment_design_agent.artifacts import build_author_handoff
from src.agents.experiment_design_agent.contracts import (
    EVIDENCE_BUNDLE_SCHEMA_VERSION,
    EXPERIMENT_DESIGN_SCHEMA_VERSION,
    OUTCOME_BRANCH_SCHEMA_VERSION,
    RESEARCH_BRIEF_SCHEMA_VERSION,
)
from src.agents.experiment_design_agent.discipline_catalog import resolve_execution_policy
from src.agents.research_plan_author.run import (
    AuthorCompositionError,
    AuthorRunError,
    run_author_preparation,
    run_research_plan_author,
)
from src.agents.research_plan_author.section_composer import (
    build_section_composer_prompt,
    validate_section_output,
)
from src.agents.research_plan_author.contract_repair import build_author_contract_repair_prompt
from src.agents.research_plan_author.authoring_blueprint import (
    AUTHORING_BLUEPRINT_SCHEMA,
    AUTHORING_BLUEPRINT_SECTION_ASSIGNMENT_SCHEMA_VERSION,
    AuthoringBlueprintError,
    AuthoringBlueprintPlanner,
    build_authoring_blueprint_section_assignment_prompt,
)
from src.agents.research_plan_author.section_router import route_author_sections
from src.agents.research_plan_author.semantic_validator import validate_composed_research_plan
from src.agents.research_plan_author.run_logging import AuthorRunLogger
from src.agents.research_plan_author.source_registry import (
    build_frozen_source_registry,
    source_registry_for_blueprint_section,
    source_registry_for_route,
)


def _branch(branch_id: str) -> dict:
    return {
        "schema_version": OUTCOME_BRANCH_SCHEMA_VERSION,
        "branch_id": branch_id,
        "trigger": "The prespecified condition is met.",
        "interpretation": "Interpret only within the stated proposal boundary.",
        "conclusion_scope": "The declared research boundary.",
        "improvement_actions": ["Revise the next design iteration."],
        "evidence_status": "EXPECTED_NOT_OBSERVED",
    }


def _author_input(discipline_id: str = "17") -> dict:
    policy = resolve_execution_policy([discipline_id])
    design = {
        "schema_version": EXPERIMENT_DESIGN_SCHEMA_VERSION,
        "design_id": f"design-{discipline_id}",
        "evidence_status": "DESIGNED_NOT_EXECUTED",
        "execution_policy": {"mode": policy["mode"], "allow_digital_execution": False, "reason": policy["reason"]},
        "research_brief": {
            "schema_version": RESEARCH_BRIEF_SCHEMA_VERSION,
            "brief_id": f"brief-{discipline_id}",
            "topic": "Bounded proposal test topic",
            "discipline_ids": [discipline_id],
            "selected_direction": {
                "id": "selected-direction",
                "title": "Bounded Proposal Direction",
                "central_hypothesis": "The stated relation may hold inside the declared boundary.",
                "mechanism_or_relation": "The relation is to be tested without execution.",
            },
            "research_object": {"object_type": "declared research object"},
            "intervention_or_transformation": "A proposed comparison.",
            "discriminating_observations": ["A prespecified observable."],
            "boundary_conditions": ["The stated boundary."],
            "alternative_explanations": ["A declared alternative explanation."],
            "known_unknowns": ["A required decision remains unresolved."],
            "evidence_status": "PROPOSED",
            "source": {"idea_result_schema": "idea_result_v5", "direction_id": "selected-direction"},
            "reasoning_context": {
                "schema_version": "reasoning_context_v1",
                "selected_direction_id": "selected-direction",
                "assumptions": [],
                "claim_scope": "The declared proposal scope.",
                "falsifiers": [],
                "boundary_conditions": ["The stated boundary."],
                "alternative_explanations": ["A declared alternative explanation."],
                "formal_symbols": [],
                "gap_records": [],
                "evidence_roles": [],
                "source_anchors": [],
                "upstream_source_paths": [],
                "source_priority": ["selected_direction"],
            },
        },
        "evidence_bundle": {
            "schema_version": EVIDENCE_BUNDLE_SCHEMA_VERSION,
            "brief_id": f"brief-{discipline_id}",
            "evidence_cards": [],
            "coverage": {"required_slots": ["measurement"], "covered_slots": [], "uncovered_slots": ["measurement"]},
        },
        "research_design": {"design_type": "proposal-only study", "experimental_unit": "declared unit", "time_structure": "to be confirmed"},
        "hypothesis_mapping": [{"hypothesis_id": "H1", "claim": "The stated relation may hold.", "observables": ["Declared observable"], "decision_rule": "Prespecify a decision rule."}],
        "variables_and_operationalization": {"independent_variables": [], "dependent_variables": [], "control_variables": [], "confounders": [], "operational_definitions": []},
        "sampling_and_eligibility": {"source": {"status": "needs_human_input"}, "eligibility_criteria": {"status": "needs_human_input"}, "sample_size_or_power_basis": {"status": "not_applicable" if discipline_id == "26" else "needs_human_input"}},
        "measurement_and_calibration": {"instruments": [], "measurement_plan": {"status": "needs_human_input"}, "calibration": {"status": "not_applicable"}, "quality_control": {"status": "needs_human_input"}},
        "comparison_and_robustness": {"groups": [], "controls": [], "baselines": [], "comparisons": [], "ablation_sensitivity_robustness": []},
        "analysis_plan": {"randomization": {"status": "needs_human_input"}, "blinding": {"status": "not_applicable"}, "repetitions": {"status": "needs_human_input"}, "batch_effects": {"status": "needs_human_input"}, "missing_data": {"status": "needs_human_input"}, "statistical_analysis": {"status": "not_applicable" if discipline_id == "26" else "needs_human_input"}},
        "data_governance_and_reproducibility": {"data_management": {"status": "needs_human_input"}, "reproducibility": {"status": "needs_human_input"}},
        "outcome_branches": [_branch(branch_id) for branch_id in ("supports_mechanism", "partial_or_heterogeneous", "null_or_contradictory", "uninformative_or_invalid")],
        "risk_and_human_review": {"risk_level": "medium", "human_review_required": False, "review_triggers": ["Confirm the unresolved methodology."], "execution_prohibited": True},
        "open_design_questions": ["Confirm the study-specific design details."],
        "observed_results": [],
        "validation_report": {"status": "DRAFT_REQUIRES_INPUT", "errors": [], "warnings": []},
    }
    _canonicalize_design(design)
    return build_author_handoff(design, idea_result_path="")


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


def _survey_sources(tmp_path: Path, *, run_id: str = "survey-run", project_id: str = "project", fingerprint: str = "fingerprint") -> dict:
    return {
        "schema_version": "research_plan_author_survey_sources_v1",
        "manifest_path": str(tmp_path / "survey_manifest.json"),
        "base_dir": str(tmp_path),
        "survey_run_id": run_id,
        "project_id": project_id,
        "project_context_fingerprint": fingerprint,
        "topic": "Bounded proposal test topic",
        "manifest": {},
        "artifacts": {"claim_traceability": {}},
        "artifact_paths": {},
    }


def _write_input(tmp_path: Path, author_input: dict) -> Path:
    path = tmp_path / "experiment_design_author.json"
    path.write_text(json.dumps(author_input), encoding="utf-8")
    return path


def test_survey_route_receives_complete_verified_survey_excerpts_only() -> None:
    excerpts = [
        {
            "anchor_id": "survey:survey_markdown#section-001",
            "heading": "Verified Background",
            "ordinal": 1,
            "text": "# Verified Background\n\nThe first verified finding.",
        },
        {
            "anchor_id": "survey:survey_markdown#section-002",
            "heading": "Research Gap",
            "ordinal": 2,
            "text": "## Research Gap\n\nThe unresolved question.",
        },
    ]
    preparation = {
        "source_bundle": {
            "author_context": {},
            "survey_binding": {},
            "idea_evolution": {},
            "survey_sources": {"artifacts": {"survey_markdown": {"excerpts": excerpts}}},
        }
    }
    registry = build_frozen_source_registry(preparation)
    survey_route = {
        "section_id": "survey_and_research_gap",
        "title": "Background, Survey, and Research Gap",
        "applicability": "required",
        "allowed_claim_kinds": ["background", "survey_evidence", "research_gap"],
    }
    other_route = {**survey_route, "section_id": "introduction", "title": "Introduction"}
    survey_registry = source_registry_for_route(registry, survey_route)
    other_registry = source_registry_for_route(registry, other_route)

    survey_payload = json.loads(
        build_section_composer_prompt(
            preparation,
            {},
            survey_route,
            {"required_open_item_ids": [], "required_review_item_ids": []},
            survey_registry,
        ).rsplit("INPUT_JSON:\n", 1)[1]
    )
    other_payload = json.loads(
        build_section_composer_prompt(
            preparation,
            {},
            other_route,
            {"required_open_item_ids": [], "required_review_item_ids": []},
            other_registry,
        ).rsplit("INPUT_JSON:\n", 1)[1]
    )

    assert survey_payload["survey_excerpts"] == excerpts
    assert other_payload["survey_excerpts"] == []
    assert set(registry["allowed_survey_anchor_ids"]) >= {
        "survey:survey_markdown",
        "survey:survey_markdown#section-001",
        "survey:survey_markdown#section-002",
    }
    assert other_payload["source_registry"]["allowed_survey_anchor_ids"] == []


def test_route_registry_exposes_only_matching_compact_evidence_slots() -> None:
    preparation = {
        "source_bundle": {
            "author_context": {
                "source_registry": {
                    "allowed_source_ids": ["S1", "S2", "S3"],
                    "allowed_survey_anchor_ids": [],
                    "evidence_cards_by_id": {
                        "C1": {
                            "card_id": "C1",
                            "source_id": "S1",
                            "citation_key": "cite_s1",
                            "evidence_level": "fulltext",
                            "claim_slot": "study_design",
                            "source_location": "loc-1",
                        },
                        "C2": {
                            "card_id": "C2",
                            "source_id": "S2",
                            "citation_key": "cite_s2",
                            "evidence_level": "fulltext",
                            "claim_slot": "statistics_bias",
                            "source_location": "loc-2",
                        },
                        "C3": {
                            "card_id": "C3",
                            "source_id": "S3",
                            "citation_key": "cite_s3",
                            "evidence_level": "abstract",
                            "claim_slot": "mechanism",
                            "source_location": "loc-3",
                        },
                    },
                    "citation_registry": [
                        {"citation_key": "cite_s1", "source_id": "S1", "evidence_level": "fulltext", "evidence_card_ids": ["C1"]},
                        {"citation_key": "cite_s2", "source_id": "S2", "evidence_level": "fulltext", "evidence_card_ids": ["C2"]},
                        {"citation_key": "cite_s3", "source_id": "S3", "evidence_level": "abstract", "evidence_card_ids": ["C3"]},
                    ],
                }
            }
        }
    }
    methods = source_registry_for_route(preparation["source_bundle"]["author_context"]["source_registry"], {"section_id": "computational_evaluation_protocol"})
    questions = source_registry_for_route(preparation["source_bundle"]["author_context"]["source_registry"], {"section_id": "research_questions_and_contributions"})

    assert set(methods["evidence_cards_by_id"]) == {"C1", "C2"}
    assert methods["allowed_source_ids"] == ["S1", "S2"]
    assert questions["evidence_cards_by_id"] == {}
    assert questions["allowed_source_ids"] == []


def test_blueprint_source_selection_further_restricts_route_evidence() -> None:
    registry = {
        "schema_version": "research_plan_author_source_registry_v2",
        "allowed_source_ids": ["S1", "S2"],
        "allowed_survey_anchor_ids": [],
        "evidence_cards_by_id": {
            "C1": {"source_id": "S1", "claim_slot": "study_design"},
            "C2": {"source_id": "S2", "claim_slot": "study_design"},
        },
        "citation_registry": [
            {"citation_key": "cite_s1", "source_id": "S1"},
            {"citation_key": "cite_s2", "source_id": "S2"},
        ],
        "unknown_items": [],
        "review_items": [],
    }
    route = {"section_id": "computational_evaluation_protocol"}

    selected = source_registry_for_blueprint_section(
        registry,
        route,
        {"allowed_source_ids": ["S2"]},
    )

    assert selected["allowed_source_ids"] == ["S2"]
    assert set(selected["evidence_cards_by_id"]) == {"C2"}
    assert selected["citation_registry"] == [{"citation_key": "cite_s2", "source_id": "S2"}]


def test_blueprint_assignment_prompt_exposes_one_fixed_route_not_full_blueprint() -> None:
    route = {
        "section_id": "abstract",
        "title": "Abstract",
        "applicability": "required",
        "allowed_claim_kinds": ["planned_contribution"],
    }
    prompt = build_authoring_blueprint_section_assignment_prompt(
        {"source_bundle": {"author_context": {}}},
        route=route,
        source_registry={"allowed_source_ids": ["S1"]},
        remaining_open_items=[],
        remaining_review_items=[],
        must_assign_all_remaining=False,
    )
    payload = json.loads(prompt.rsplit("INPUT_JSON:\n", 1)[1])

    assert payload["operation"] == "research_plan_authoring_blueprint_section_assignment"
    assert payload["fixed_section"] == route
    assert "sections" not in payload
    assert payload["output_contract"]["properties"]["section_id"] == {"const": "abstract"}
    assert payload["output_contract"]["properties"]["schema_version"] == {
        "const": AUTHORING_BLUEPRINT_SECTION_ASSIGNMENT_SCHEMA_VERSION
    }


def test_contract_repair_prompt_identifies_artifact_schema_and_output_boundary() -> None:
    prompt = build_author_contract_repair_prompt(
        artifact_kind="authoring_blueprint",
        initial_candidate={"language": "en"},
        validation_errors=["missing required fields"],
        allowed_structural_strings={"design-1"},
        contract_schema=AUTHORING_BLUEPRINT_SCHEMA,
    )
    payload = json.loads(prompt.rsplit("INPUT_JSON:\n", 1)[1])

    assert payload["target_contract_schema"] == AUTHORING_BLUEPRINT_SCHEMA
    assert "not the INPUT_JSON envelope" in prompt
    assert "artifact_kind" in prompt


def test_survey_claim_requires_a_specific_markdown_excerpt_anchor() -> None:
    preparation = {"source_bundle": {"author_context": {}}}
    route = {
        "section_id": "survey_and_research_gap",
        "title": "Background, Survey, and Research Gap",
        "applicability": "required",
        "allowed_claim_kinds": ["survey_evidence"],
    }
    section = {
        "schema_version": "research_plan_section_v1",
        "language": "en",
        "section_id": route["section_id"],
        "title": route["title"],
        "applicability": route["applicability"],
        "blocks": [{"block_id": "block-1", "kind": "paragraph", "text": "The survey identifies a bounded gap.", "claim_ids": ["claim-1"]}],
        "claim_provenance": [{"claim_id": "claim-1", "claim_kind": "survey_evidence", "statement": "The survey identifies a bounded gap.", "qualification": "metadata_lead", "source_ids": [], "evidence_card_ids": [], "survey_anchor_ids": ["survey:survey_markdown"], "formal_reference_ids": [], "outcome_branch_ids": [], "citation_keys": []}],
        "open_items": [],
        "review_items": [],
    }
    registry = {
        "allowed_source_ids": [],
        "allowed_survey_anchor_ids": [
            "survey:survey_markdown",
            "survey:survey_markdown#section-001",
        ],
        "evidence_cards_by_id": {},
        "citation_registry": [],
        "unknown_items": [],
        "review_items": [],
    }

    errors = validate_section_output(
        section,
        route=route,
        blueprint_section={"required_open_item_ids": [], "required_review_item_ids": []},
        preparation=preparation,
        source_registry=registry,
    )

    assert errors == ["Survey claim claim-1 must cite a specific verified Survey Markdown excerpt"]

    non_survey_route = {**route, "section_id": "introduction", "title": "Introduction", "allowed_claim_kinds": ["background"]}
    non_survey_section = deepcopy(section)
    non_survey_section["section_id"] = non_survey_route["section_id"]
    non_survey_section["title"] = non_survey_route["title"]
    non_survey_section["claim_provenance"][0]["claim_kind"] = "background"
    non_survey_section["claim_provenance"][0]["survey_anchor_ids"] = ["survey:survey_markdown#section-001"]
    errors = validate_section_output(
        non_survey_section,
        route=non_survey_route,
        blueprint_section={"required_open_item_ids": [], "required_review_item_ids": []},
        preparation=preparation,
        source_registry=registry,
    )

    assert errors == ["claim claim-1 may not cite Survey anchors outside the Survey section"]


def _fake_author_llm(prompt: str, *, response_format: object) -> dict:
    assert response_format == {"type": "json_object"}
    payload = json.loads(prompt.rsplit("INPUT_JSON:\n", 1)[1])
    operation = payload.get("operation")
    if operation == "research_plan_authoring_blueprint_section_assignment":
        fixed_section = payload["fixed_section"]
        section_id = fixed_section["section_id"]
        response = {
            "schema_version": "research_plan_authoring_blueprint_section_assignment_v1",
            "section_id": section_id,
            "allowed_source_ids": [],
            "required_open_item_ids": [
                item["source_item_id"]
                for item in payload["remaining_unknown_items"]
                if section_id == "risk_limitations_and_review"
            ],
            "required_review_item_ids": [
                item["source_item_id"]
                for item in payload["remaining_review_items"]
                if section_id == "risk_limitations_and_review"
            ],
        }
        if section_id == "abstract":
            response["document_title"] = "An English Proposal Title"
            response["keywords"] = ["proposal", "design"]
        if payload["must_assign_all_remaining"]:
            response["required_open_item_ids"] = [
                item["source_item_id"] for item in payload["remaining_unknown_items"]
            ]
            response["required_review_item_ids"] = [
                item["source_item_id"] for item in payload["remaining_review_items"]
            ]
        return response
    assert operation == "research_plan_section_composition"
    route = payload["route"]
    claim_kind = "planned_contribution" if route["section_id"] == "abstract" else route["allowed_claim_kinds"][0]
    evidence_claim = claim_kind in {"background", "survey_evidence", "research_gap"}
    has_verified_survey_anchor = any(
        str(anchor).startswith("survey:survey_markdown#section-")
        for anchor in payload["source_registry"].get("allowed_survey_anchor_ids", [])
    )
    if evidence_claim and not payload["source_registry"].get("evidence_cards_by_id") and not has_verified_survey_anchor:
        return {
            "schema_version": "research_plan_section_v1",
            "language": "en",
            "section_id": route["section_id"],
            "title": route["title"],
            "applicability": route["applicability"],
            "blocks": [],
            "claim_provenance": [],
            "open_items": [],
            "review_items": [],
        }
    qualification = "proposed" if claim_kind in {"formal_definition", "formal_proposition", "proof_obligation", "forward_derivation", "counterexample_plan"} else "design_assumption"
    statement = f"This proposal specifies the bounded role of {route['title']}."
    outcome_branch_ids: list[str] = []
    if claim_kind == "expected_outcome":
        qualification = "expected_not_observed"
        outcome_branch_ids = ["supports_mechanism"]
        statement = "If the prespecified branch condition is met, the proposal permits a conditional conclusion."
    claim_id = f"claim-{route['section_id']}"
    blueprint_section = payload["blueprint_section"]
    return {
        "schema_version": "research_plan_section_v1",
        "language": "en",
        "section_id": route["section_id"],
        "title": route["title"],
        "applicability": route["applicability"],
        "blocks": [{"block_id": f"block-{route['section_id']}", "kind": "paragraph", "text": statement, "claim_ids": [claim_id]}],
        "claim_provenance": [{"claim_id": claim_id, "claim_kind": claim_kind, "statement": statement, "qualification": qualification, "source_ids": [], "evidence_card_ids": [], "survey_anchor_ids": ["survey:survey_markdown#section-001"] if route["section_id"] == "survey_and_research_gap" and "survey:survey_markdown#section-001" in payload["source_registry"].get("allowed_survey_anchor_ids", []) and claim_kind in {"background", "survey_evidence", "research_gap"} else [], "formal_reference_ids": [], "outcome_branch_ids": outcome_branch_ids, "citation_keys": []}],
        "open_items": [
            {"source_item_id": item_id, "text": "Human input is required before this proposal can proceed.", "status": "needs_human_input"}
            for item_id in blueprint_section["required_open_item_ids"]
        ],
        "review_items": [
            {"source_item_id": item_id, "text": "Qualified human review is required before this proposal can proceed.", "status": "review_required"}
            for item_id in blueprint_section["required_review_item_ids"]
        ],
    }


def test_blueprint_keeps_every_router_owned_field_canonical(monkeypatch, tmp_path: Path) -> None:
    path = _write_input(tmp_path, _author_input("26"))
    import src.agents.research_plan_author.run as author_run

    monkeypatch.setattr(author_run, "load_verified_survey_sources", lambda _path: _survey_sources(tmp_path))
    preparation = run_author_preparation(
        path,
        survey_manifest_path=tmp_path / "survey_manifest.json",
        include_idea_evolution="off",
    )
    routing = route_author_sections(preparation["source_bundle"]["author_context"])
    registry = build_frozen_source_registry(preparation)
    blueprint = AuthoringBlueprintPlanner().plan(
        preparation,
        routing=routing,
        source_registry=registry,
        llm_call=_fake_author_llm,
    )

    assert [section["section_id"] for section in blueprint["sections"]] == [
        route["section_id"] for route in routing["routes"]
    ]
    for section, route in zip(blueprint["sections"], routing["routes"], strict=True):
        assert {
            key: section[key]
            for key in ("section_id", "title", "applicability", "allowed_claim_kinds")
        } == {
            key: route[key]
            for key in ("section_id", "title", "applicability", "allowed_claim_kinds")
        }


def test_blueprint_logs_each_section_assignment(monkeypatch, tmp_path: Path) -> None:
    path = _write_input(tmp_path, _author_input("26"))
    import src.agents.research_plan_author.run as author_run

    monkeypatch.setattr(author_run, "load_verified_survey_sources", lambda _path: _survey_sources(tmp_path))
    log_path = tmp_path / "author.jsonl"
    logger = AuthorRunLogger("blueprint-log-test", jsonl_path=log_path, console_stream=StringIO())
    try:
        run_research_plan_author(
            path,
            survey_manifest_path=tmp_path / "survey_manifest.json",
            include_idea_evolution="off",
            llm_call=_fake_author_llm,
            logger=logger,
        )
    finally:
        logger.close()
    records = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    started = [
        record
        for record in records
        if record["stage"] == "blueprint" and record["event"] == "section_assignment_started"
    ]
    validated = [
        record
        for record in records
        if record["stage"] == "blueprint" and record["event"] == "section_assignment_validated"
    ]

    assert len(started) == len(validated) == 15
    assert [record["section_index"] for record in started] == list(range(1, 16))
    assert [record["section_id"] for record in started] == [record["section_id"] for record in validated]
    assert all("available_source_count" in record for record in started)
    assert all("remaining_unknown_item_count" in record for record in validated)


def test_blueprint_repair_log_uses_safe_path_and_error_codes(monkeypatch, tmp_path: Path) -> None:
    path = _write_input(tmp_path, _author_input("26"))
    import src.agents.research_plan_author.run as author_run

    monkeypatch.setattr(author_run, "load_verified_survey_sources", lambda _path: _survey_sources(tmp_path))
    preparation = run_author_preparation(
        path,
        survey_manifest_path=tmp_path / "survey_manifest.json",
        include_idea_evolution="off",
    )
    routing = route_author_sections(preparation["source_bundle"]["author_context"])
    registry = build_frozen_source_registry(preparation)

    def missing_sources_llm(prompt: str, *, response_format: object) -> dict:
        response = _fake_author_llm(prompt, response_format=response_format)
        request = json.loads(prompt.rsplit("INPUT_JSON:\n", 1)[1])
        if (
            request.get("operation") == "research_plan_authoring_blueprint_section_assignment"
            and request["fixed_section"]["section_id"] == "formal_problem_and_hypotheses"
        ):
            response.pop("allowed_source_ids")
        return response

    log_path = tmp_path / "author.jsonl"
    logger = AuthorRunLogger("blueprint-repair-log-test", jsonl_path=log_path, console_stream=StringIO())
    try:
        with pytest.raises(AuthoringBlueprintError):
            AuthoringBlueprintPlanner().plan(
                preparation,
                routing=routing,
                source_registry=registry,
                llm_call=missing_sources_llm,
                logger=logger,
            )
    finally:
        logger.close()
    records = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    repair_record = next(record for record in records if record["event"] == "section_assignment_repair_required")

    assert repair_record["validation_error_count"] == 1
    assert repair_record["validation_error_codes"] == ["$/allowed_source_ids:missing_property"]


@pytest.mark.parametrize(
    ("discipline_id", "template_family"),
    [
        ("26", "mathematics_theory"),
        ("15", "materials_chemical"),
        ("13", "life_veterinary"),
        ("21", "engineering_energy"),
        ("11", "earth_environment_agro"),
        ("27", "clinical_health"),
    ],
)
def test_author_composes_all_non_cs_template_fixtures(monkeypatch, tmp_path: Path, discipline_id: str, template_family: str) -> None:
    author_input = _author_input(discipline_id)
    path = _write_input(tmp_path, author_input)
    import src.agents.research_plan_author.run as author_run

    monkeypatch.setattr(author_run, "load_verified_survey_sources", lambda _path: _survey_sources(tmp_path))
    result = run_research_plan_author(
        path,
        survey_manifest_path=tmp_path / "survey_manifest.json",
        include_idea_evolution="off",
        llm_call=_fake_author_llm,
    )

    assert result["status"] == "COMPOSED_FOR_RENDERING"
    assert result["document"]["source_manifest"]["template_family"] == template_family
    assert result["document"]["document_metadata"]["title"] == "An English Proposal Title"
    assert not any(claim["claim_kind"] == "observed_result" for claim in result["document"]["claim_provenance"])
    assert result["document"]["review_items"] == [
        {
            "source_item_id": "review-1",
            "text": "Qualified human review is required before this proposal can proceed.",
            "status": "review_required",
        }
    ]


def test_survey_binding_is_hard_matched_and_unbound_requires_confirmation(monkeypatch, tmp_path: Path) -> None:
    author_input = _author_input()
    author_input["provenance"]["survey_binding"] = {
        "survey_run_id": "expected-run",
        "project_id": "expected-project",
        "project_context_fingerprint": "expected-fingerprint",
    }
    path = _write_input(tmp_path, author_input)
    import src.agents.research_plan_author.run as author_run

    monkeypatch.setattr(author_run, "load_verified_survey_sources", lambda _path: _survey_sources(tmp_path))
    with pytest.raises(AuthorRunError, match="does not match"):
        run_author_preparation(path, survey_manifest_path=tmp_path / "survey_manifest.json")

    unbound_path = _write_input(tmp_path, _author_input())
    with pytest.raises(AuthorRunError, match="strict Survey binding"):
        run_author_preparation(
            unbound_path,
            survey_manifest_path=tmp_path / "survey_manifest.json",
            strict_survey_binding=True,
        )


def test_preparation_freezes_input_and_defers_non_english_title(monkeypatch, tmp_path: Path) -> None:
    author_input = _author_input()
    author_input["selected_direction"]["title"] = "中文来源标题"
    path = _write_input(tmp_path, author_input)
    import src.agents.research_plan_author.run as author_run

    monkeypatch.setattr(author_run, "load_verified_survey_sources", lambda _path: _survey_sources(tmp_path))
    result = run_author_preparation(path, survey_manifest_path=tmp_path / "survey_manifest.json", include_idea_evolution="off")

    assert result["source_bundle"]["author_context"] == author_input
    assert result["document"]["document_metadata"]["title"] == ""
    assert result["document"]["document_metadata"]["source_title"] == "中文来源标题"
    assert result["document"]["document_metadata"]["title_status"] == "requires_english_llm_composition"


def test_contract_repair_is_once_and_cannot_add_a_fact(monkeypatch, tmp_path: Path) -> None:
    path = _write_input(tmp_path, _author_input())
    import src.agents.research_plan_author.run as author_run

    monkeypatch.setattr(author_run, "load_verified_survey_sources", lambda _path: _survey_sources(tmp_path))
    repair_calls = 0

    def repaired_llm(prompt: str, *, response_format: object) -> dict:
        nonlocal repair_calls
        if "constrained JSON contract repair" in prompt:
            repair_calls += 1
            payload = json.loads(prompt.rsplit("INPUT_JSON:\n", 1)[1])
            candidate = deepcopy(payload["initial_candidate"])
            candidate["schema_version"] = "research_plan_authoring_blueprint_section_assignment_v1"
            return candidate
        output = _fake_author_llm(prompt, response_format=response_format)
        request = json.loads(prompt.rsplit("INPUT_JSON:\n", 1)[1])
        if (
            request.get("operation") == "research_plan_authoring_blueprint_section_assignment"
            and request["fixed_section"]["section_id"] == "abstract"
        ):
            output.pop("schema_version")
        return output

    repaired = run_research_plan_author(
        path,
        survey_manifest_path=tmp_path / "survey_manifest.json",
        include_idea_evolution="off",
        llm_call=repaired_llm,
        max_contract_repairs=1,
    )
    assert repair_calls == 1
    assert repaired["document"]["contract_repair_audit"][0]["repair_status"] == "REPAIRED"

    def invented_fact_repair(prompt: str, *, response_format: object) -> dict:
        if "constrained JSON contract repair" in prompt:
            payload = json.loads(prompt.rsplit("INPUT_JSON:\n", 1)[1])
            candidate = deepcopy(payload["initial_candidate"])
            candidate["schema_version"] = "research_plan_authoring_blueprint_section_assignment_v1"
            candidate["document_title"] = "An unsupported new factual title"
            return candidate
        output = _fake_author_llm(prompt, response_format=response_format)
        request = json.loads(prompt.rsplit("INPUT_JSON:\n", 1)[1])
        if (
            request.get("operation") == "research_plan_authoring_blueprint_section_assignment"
            and request["fixed_section"]["section_id"] == "abstract"
        ):
            output.pop("schema_version")
        return output

    with pytest.raises(AuthorCompositionError) as error:
        run_research_plan_author(
            path,
            survey_manifest_path=tmp_path / "survey_manifest.json",
            include_idea_evolution="off",
            llm_call=invented_fact_repair,
            max_contract_repairs=1,
        )
    assert error.value.audit["initial_candidate"]["document_title"] == "An English Proposal Title"


def test_section_validator_rejects_observed_and_abstract_only_critical_method_claims(monkeypatch, tmp_path: Path) -> None:
    path = _write_input(tmp_path, _author_input())
    import src.agents.research_plan_author.run as author_run

    monkeypatch.setattr(author_run, "load_verified_survey_sources", lambda _path: _survey_sources(tmp_path))
    preparation = run_author_preparation(path, survey_manifest_path=tmp_path / "survey_manifest.json", include_idea_evolution="off")
    routing = route_author_sections(preparation["source_bundle"]["author_context"])
    route = next(item for item in routing["routes"] if item["section_id"] == "study_design_and_methods")
    registry = {
        "allowed_source_ids": ["W1"],
        "allowed_survey_anchor_ids": [],
        "evidence_cards_by_id": {"E1": {"evidence_level": "abstract"}},
        "citation_registry": [{"citation_key": "source:W1"}],
    }
    payload = {
        "schema_version": "research_plan_section_v1",
        "language": "en",
        "section_id": route["section_id"],
        "title": route["title"],
        "applicability": route["applicability"],
        "blocks": [{"block_id": "B1", "kind": "paragraph", "text": "This study observed the outcome.", "claim_ids": ["C1"]}],
        "claim_provenance": [{"claim_id": "C1", "claim_kind": "planned_method", "statement": "This study observed the outcome.", "qualification": "evidence_backed", "method_field": "calibration", "source_ids": ["W1"], "evidence_card_ids": ["E1"], "survey_anchor_ids": [], "formal_reference_ids": [], "outcome_branch_ids": [], "citation_keys": ["source:W1"]}],
        "open_items": [],
        "review_items": [],
    }
    errors = validate_section_output(payload, route=route, blueprint_section={"required_open_item_ids": [], "required_review_item_ids": []}, preparation=preparation, source_registry=registry)
    assert any("observed result" in error for error in errors)
    assert any("requires fulltext" in error for error in errors)


def test_section_validator_rejects_unanchored_visible_block_prose(monkeypatch, tmp_path: Path) -> None:
    path = _write_input(tmp_path, _author_input())
    import src.agents.research_plan_author.run as author_run

    monkeypatch.setattr(author_run, "load_verified_survey_sources", lambda _path: _survey_sources(tmp_path))
    preparation = run_author_preparation(path, survey_manifest_path=tmp_path / "survey_manifest.json", include_idea_evolution="off")
    routing = route_author_sections(preparation["source_bundle"]["author_context"])
    route = next(item for item in routing["routes"] if item["section_id"] == "study_design_and_methods")
    payload = {
        "schema_version": "research_plan_section_v1",
        "language": "en",
        "section_id": route["section_id"],
        "title": route["title"],
        "applicability": route["applicability"],
        "blocks": [
            {
                "block_id": "B1",
                "kind": "paragraph",
                "text": "This study observed a treatment effect.",
                "claim_ids": [],
            },
            {
                "block_id": "B2",
                "kind": "paragraph",
                "text": "The intervention improves the endpoint.",
                "claim_ids": [],
            },
        ],
        "claim_provenance": [],
        "open_items": [],
        "review_items": [],
    }

    errors = validate_section_output(
        payload,
        route=route,
        blueprint_section={"required_open_item_ids": [], "required_review_item_ids": []},
        preparation=preparation,
        source_registry={"allowed_source_ids": [], "allowed_survey_anchor_ids": [], "evidence_cards_by_id": {}, "citation_registry": []},
    )

    assert any("must reference at least one claim ID" in error for error in errors)
    assert any("observed result" in error for error in errors)


def test_final_semantic_validation_scans_abstract_and_free_block_text(monkeypatch, tmp_path: Path) -> None:
    path = _write_input(tmp_path, _author_input())
    import src.agents.research_plan_author.run as author_run

    monkeypatch.setattr(author_run, "load_verified_survey_sources", lambda _path: _survey_sources(tmp_path))
    result = run_research_plan_author(
        path,
        survey_manifest_path=tmp_path / "survey_manifest.json",
        include_idea_evolution="off",
        llm_call=_fake_author_llm,
    )
    invalid = deepcopy(result["document"])
    invalid["abstract"]["text"] = "This study observed a treatment effect."
    invalid["sections"][0]["blocks"] = [
        {"block_id": "invalid-block", "kind": "paragraph", "text": "The intervention improves the endpoint.", "claim_ids": []}
    ]
    preparation = result
    routing = route_author_sections(preparation["source_bundle"]["author_context"])
    registry = build_frozen_source_registry(preparation)

    errors = validate_composed_research_plan(
        invalid,
        preparation=preparation,
        routing=routing,
        source_registry=registry,
    )

    assert any("abstract presents an observed result" in error for error in errors)
    assert any("must reference at least one claim ID" in error for error in errors)


def test_section_validator_keeps_formal_proofs_and_counterexamples_unverified(monkeypatch, tmp_path: Path) -> None:
    path = _write_input(tmp_path, _author_input("26"))
    import src.agents.research_plan_author.run as author_run

    monkeypatch.setattr(author_run, "load_verified_survey_sources", lambda _path: _survey_sources(tmp_path))
    preparation = run_author_preparation(path, survey_manifest_path=tmp_path / "survey_manifest.json", include_idea_evolution="off")
    routing = route_author_sections(preparation["source_bundle"]["author_context"])
    route = next(item for item in routing["routes"] if item["section_id"] == "definitions_and_propositions")
    payload = {
        "schema_version": "research_plan_section_v1",
        "language": "en",
        "section_id": route["section_id"],
        "title": route["title"],
        "applicability": route["applicability"],
        "blocks": [{"block_id": "B1", "kind": "proposition", "text": "The theorem is proved.", "claim_ids": ["C1"]}],
        "claim_provenance": [{"claim_id": "C1", "claim_kind": "formal_proposition", "statement": "The theorem is proved from a source paper.", "qualification": "proposed", "source_ids": [], "evidence_card_ids": ["E1"], "survey_anchor_ids": [], "formal_reference_ids": [], "outcome_branch_ids": [], "citation_keys": []}],
        "open_items": [],
        "review_items": [],
    }
    errors = validate_section_output(
        payload,
        route=route,
        blueprint_section={"required_open_item_ids": [], "required_review_item_ids": []},
        preparation=preparation,
        source_registry={"allowed_source_ids": [], "allowed_survey_anchor_ids": [], "evidence_cards_by_id": {"E1": {"evidence_level": "fulltext"}}, "citation_registry": []},
    )
    assert any("may not use empirical evidence cards" in error for error in errors)
    assert any("asserts verification" in error for error in errors)
