from __future__ import annotations

from copy import deepcopy
import hashlib
from io import StringIO
import json
from pathlib import Path
from threading import Lock
from time import sleep

import pytest
from jsonschema import Draft202012Validator

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
    SectionComposer,
    SectionCompositionError,
    build_section_composer_prompt,
    build_section_output_schema,
    validate_section_output,
)
from src.agents.research_plan_author.contract_repair import (
    build_author_contract_repair_prompt,
    validate_author_contract_repair,
)
from src.agents.research_plan_author.authoring_blueprint import (
    AUTHORING_BLUEPRINT_SCHEMA,
    AUTHORING_BLUEPRINT_SECTION_ASSIGNMENT_SCHEMA_VERSION,
    AuthoringBlueprintError,
    AuthoringBlueprintPlanner,
    argument_ledger_context_for_section,
    build_authoring_argument_ledger,
    build_authoring_blueprint_section_assignment_prompt,
)
from src.agents.research_plan_author.section_router import route_author_sections
from src.agents.research_plan_author.semantic_validator import validate_composed_research_plan
from src.agents.research_plan_author.document_quality import (
    AUTHOR_DOCUMENT_REVISION_SCHEMA_VERSION,
    _normalise_evidence_text,
    optimize_research_plan_document,
    render_document_quality_report,
)
from src.agents.research_plan_author.markdown_renderer import render_research_plan_markdown
from src.agents.research_plan_author.artifacts import write_author_preparation_artifacts
from src.agents.research_plan_author.run_logging import AuthorRunLogger
from src.agents.research_plan_author.source_registry import (
    build_authoring_knowledge_base,
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


def test_all_routes_receive_complete_verified_survey_excerpts_as_private_context() -> None:
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
    assert other_payload["survey_excerpts"] == excerpts
    assert survey_payload["authoring_detail_brief"]["target_prose_words"] == "1200-1500"
    assert survey_payload["authoring_detail_brief"]["target_substantive_blocks"] == "5-7"
    assert other_payload["authoring_detail_brief"]["target_prose_words"] == "600-800"
    assert survey_payload["output_contract"]["properties"]["blocks"]["items"]["properties"]["heading"] == {"type": "string"}
    assert "An equation block must contain mathematics only" in build_section_composer_prompt(
        preparation,
        {},
        survey_route,
        {"required_open_item_ids": [], "required_review_item_ids": []},
        survey_registry,
    )
    assert set(registry["allowed_survey_anchor_ids"]) >= {
        "survey:survey_markdown",
        "survey:survey_markdown#section-001",
        "survey:survey_markdown#section-002",
    }
    assert other_payload["source_registry"]["allowed_survey_anchor_ids"] == registry["allowed_survey_anchor_ids"]


def test_energy_condition_boundary_appendix_guidance_is_available_to_the_composer() -> None:
    preparation = {
        "source_bundle": {
            "author_context": {"provenance": {"template_id": "mathematics_theory"}},
            "survey_binding": {},
            "idea_evolution": {},
        }
    }
    route = {
        "section_id": "appendix_variables_and_definitions",
        "title": "Energy-Condition Taxonomy, Symbols, and Boundary Defense",
        "applicability": "required",
        "allowed_claim_kinds": ["formal_definition", "planned_method", "design_assumption", "needs_human_input"],
        "theory_role": "energy_condition_boundary_defense",
    }
    registry = {
        "allowed_source_ids": [],
        "allowed_survey_anchor_ids": [],
        "evidence_cards_by_id": {},
        "citation_registry": [],
        "unknown_items": [],
        "review_items": [],
    }

    prompt = build_section_composer_prompt(
        preparation,
        {},
        route,
        {"required_open_item_ids": [], "required_review_item_ids": []},
        registry,
    )

    assert "For `energy_condition_boundary_defense`" in prompt
    assert "NEC, ANEC/AANEC, null convergence or Ricci contraction, SEC" in prompt
    assert "SEC is not a substitute for AANEC" in prompt


def test_quality_evidence_normalization_accepts_public_theory_presentations() -> None:
    raw_text = "The dependency remains conditional until the stated review action."

    for prefix in (
        "**Lemma L1 (Candidate).** ",
        "**Proof Obligation PO1 (Unverified).** ",
        "**Equation [eq:formal-relation].**\n\n",
        "**Pre-registered Branch (Expected---Not Observed).**\n\n",
        "**Decision Status: No-information.**\n\n",
    ):
        assert _normalise_evidence_text(prefix + raw_text) == raw_text


def test_non_survey_routes_hide_survey_gap_context() -> None:
    gap_anchor = "anchor:gap_evidence_anchor:sh4:boundary_variable"
    preparation = {
        "source_bundle": {
            "author_context": {
                "reasoning_context": {
                    "claim_scope": "A bounded proposal.",
                    "gap_records": [{"gap_id": "gap-1"}],
                    "source_anchors": [{"anchor_id": gap_anchor}],
                    "evidence_roles": [{"anchor_ids": [gap_anchor]}],
                }
            },
            "survey_binding": {},
            "idea_evolution": {},
            "survey_sources": {"artifacts": {"survey_markdown": {"excerpts": []}}},
        }
    }
    introduction_route = {
        "section_id": "introduction",
        "title": "Introduction",
        "applicability": "required",
        "allowed_claim_kinds": ["design_assumption"],
    }
    survey_route = {
        "section_id": "survey_and_research_gap",
        "title": "Background, Survey, and Research Gap",
        "applicability": "required",
        "allowed_claim_kinds": ["research_gap"],
    }
    registry = {
        "allowed_source_ids": [],
        "allowed_survey_anchor_ids": [],
        "evidence_cards_by_id": {},
        "citation_registry": [],
        "unknown_items": [],
        "review_items": [],
    }

    introduction_payload = json.loads(
        build_section_composer_prompt(
            preparation,
            {},
            introduction_route,
            {"required_open_item_ids": [], "required_review_item_ids": []},
            registry,
        ).rsplit("INPUT_JSON:\n", 1)[1]
    )
    survey_payload = json.loads(
        build_section_composer_prompt(
            preparation,
            {},
            survey_route,
            {"required_open_item_ids": [], "required_review_item_ids": []},
            registry,
        ).rsplit("INPUT_JSON:\n", 1)[1]
    )

    assert introduction_payload["author_context"]["reasoning_context"] == {"claim_scope": "A bounded proposal."}
    assert survey_payload["author_context"]["reasoning_context"]["gap_records"] == [{"gap_id": "gap-1"}]
    assert survey_payload["author_context"]["reasoning_context"]["source_anchors"] == [{"anchor_id": gap_anchor}]


def test_theory_artifact_quota_guides_structured_derivation_without_blocking() -> None:
    route = {
        "section_id": "forward_derivation_and_counterexamples",
        "title": "Forward Derivation and Counterexample Search Plan",
        "applicability": "required",
        "allowed_claim_kinds": ["forward_derivation", "counterexample_plan", "limitation"],
    }
    preparation = {
        "source_bundle": {
            "author_context": {
                "provenance": {"discipline_ids": ["26"]},
                "formal_reasoning": {
                    "assumptions": [{"assumption_id": "A1", "statement": "The domain is retained."}],
                    "definitions": [{"definition_id": "D1", "symbol": "F", "statement": "F is defined on the declared domain."}],
                    "propositions": [{"proposition_id": "P1", "statement": "The proposed relation is bounded.", "conclusion": "F = G"}],
                    "proof_obligations": [{"obligation_id": "PO1", "target": "Check the proposed relation."}],
                    "forward_derivation": {"steps": [{"step_id": "S1", "derived_statement": "F = G"}]},
                },
            },
            "survey_binding": {},
            "idea_evolution": {},
        }
    }
    blueprint_section = {"required_open_item_ids": [], "required_review_item_ids": []}
    registry = {
        "allowed_source_ids": [],
        "allowed_survey_anchor_ids": [],
        "evidence_cards_by_id": {},
        "citation_registry": [],
        "unknown_items": [],
        "review_items": [],
    }
    prompt = build_section_composer_prompt(preparation, {}, route, blueprint_section, registry)
    prompt_payload = json.loads(prompt.rsplit("INPUT_JSON:\n", 1)[1])

    assert prompt_payload["theory_artifact_quota"]["required_block_kinds"] == [
        "definition",
        "equation",
        "list",
        "proposition",
        "table",
    ]
    assert prompt_payload["cross_section_deduplication"]["primary_definition_owner"] == "definitions_and_propositions"
    assert "writing task card" in prompt

    payload = {
        "schema_version": "research_plan_section_v1",
        "language": "en",
        "section_id": route["section_id"],
        "title": route["title"],
        "applicability": route["applicability"],
        "blocks": [
            {"block_id": "setup", "kind": "definition", "text": "The proposal defines the bounded derivation domain.", "claim_ids": ["D1"]},
            {"block_id": "assumptions", "kind": "list", "text": "- Retain the declared domain.\n- Treat the unresolved premise as human input.", "claim_ids": ["D1"]},
            {"block_id": "relation", "kind": "equation", "text": r"F = G", "claim_ids": ["D1"]},
            {"block_id": "obligation", "kind": "proposition", "text": "The proposed derivation must fail outside the stated domain.", "claim_ids": ["D1"], "reference_block_ids": ["relation"]},
            {"block_id": "matrix", "kind": "table", "text": "Candidate case | Assumption check | Action\nAdmissible case | Retained | Continue proof obligation\nBoundary case | Fails domain | Record counterexample", "claim_ids": ["D2"]},
        ],
        "claim_provenance": [
            {"claim_id": "D1", "claim_kind": "forward_derivation", "statement": "The proposal defines a bounded derivation domain.", "qualification": "proposed", "source_ids": [], "evidence_card_ids": [], "survey_anchor_ids": [], "formal_reference_ids": [], "outcome_branch_ids": [], "citation_keys": []},
            {"claim_id": "D2", "claim_kind": "counterexample_plan", "statement": "The plan records a boundary counterexample.", "qualification": "proposed", "source_ids": [], "evidence_card_ids": [], "survey_anchor_ids": [], "formal_reference_ids": [], "outcome_branch_ids": [], "citation_keys": []},
        ],
        "open_items": [],
        "review_items": [],
    }

    assert validate_section_output(
        payload,
        route=route,
        blueprint_section=blueprint_section,
        preparation=preparation,
        source_registry=registry,
    ) == []

    incomplete = deepcopy(payload)
    incomplete["blocks"] = [block for block in incomplete["blocks"] if block["kind"] != "table"]
    errors = validate_section_output(
        incomplete,
        route=route,
        blueprint_section=blueprint_section,
        preparation=preparation,
        source_registry=registry,
    )
    assert errors == []


def test_theory_artifact_quota_never_forces_an_unsupported_equation() -> None:
    route = {
        "section_id": "definitions_and_propositions",
        "title": "Definitions, Propositions, and Proof Obligations",
        "applicability": "required",
        "allowed_claim_kinds": ["formal_definition", "formal_proposition", "proof_obligation"],
    }
    preparation = {
        "source_bundle": {
            "author_context": {
                "provenance": {"discipline_ids": ["26"]},
                "formal_reasoning": {
                    "assumptions": [],
                    "definitions": [{"definition_id": "D1", "symbol": "F", "statement": "F remains to be specified."}],
                    "propositions": [],
                    "proof_obligations": [],
                    "forward_derivation": {"steps": []},
                },
            },
            "survey_binding": {},
            "idea_evolution": {},
        }
    }
    prompt = build_section_composer_prompt(
        preparation,
        {},
        route,
        {"required_open_item_ids": [], "required_review_item_ids": []},
        {"allowed_source_ids": [], "allowed_survey_anchor_ids": [], "evidence_cards_by_id": {}, "citation_registry": [], "unknown_items": [], "review_items": []},
    )
    quota = json.loads(prompt.rsplit("INPUT_JSON:\n", 1)[1])["theory_artifact_quota"]

    assert "equation" not in quota["required_block_kinds"]
    assert quota["requires_equation_reference"] is False
    assert "numbered equation" in quota["unavailable_artifacts"]


def test_section_composer_normalizes_a_non_equation_cross_reference_to_the_only_equation() -> None:
    route = {
        "section_id": "definitions_and_propositions",
        "title": "Definitions and Propositions",
        "applicability": "required",
        "allowed_claim_kinds": ["formal_definition", "formal_proposition", "proof_obligation"],
    }
    preparation = {
        "source_bundle": {
            "author_context": {
                "provenance": {"discipline_ids": ["26"]},
                "formal_reasoning": {
                    "definitions": [{"definition_id": "D1", "symbol": "F", "statement": "F is defined."}],
                    "assumptions": [{"assumption_id": "A1", "statement": "The domain is retained."}],
                    "propositions": [{"proposition_id": "P1", "conclusion": "F = G"}],
                    "proof_obligations": [{"obligation_id": "PO1", "target": "Check F = G."}],
                    "forward_derivation": {"steps": []},
                },
            },
            "survey_binding": {},
            "idea_evolution": {},
        },
    }
    registry = {
        "allowed_source_ids": [],
        "allowed_survey_anchor_ids": [],
        "evidence_cards_by_id": {},
        "citation_registry": [],
        "unknown_items": [],
        "review_items": [],
    }
    candidate = {
        "schema_version": "research_plan_section_v1",
        "language": "en",
        "section_id": route["section_id"],
        "title": route["title"],
        "applicability": route["applicability"],
        "blocks": [
            {"block_id": "definition", "kind": "definition", "text": "The proposal defines F.", "claim_ids": ["D1"]},
            {"block_id": "assumptions", "kind": "list", "text": "- Retain the declared domain.", "claim_ids": ["D1"]},
            {"block_id": "relation", "kind": "equation", "text": "F = G", "claim_ids": ["P1"]},
            {
                "block_id": "obligation",
                "kind": "proposition",
                "text": "The proposed obligation fails outside the declared domain.",
                "claim_ids": ["P1"],
                "reference_block_ids": ["assumptions"],
            },
        ],
        "claim_provenance": [
            {"claim_id": "D1", "claim_kind": "formal_definition", "statement": "The proposal defines F.", "qualification": "proposed", "source_ids": [], "evidence_card_ids": [], "survey_anchor_ids": [], "formal_reference_ids": [], "outcome_branch_ids": [], "citation_keys": []},
            {"claim_id": "P1", "claim_kind": "formal_proposition", "statement": "The proposal states a bounded relation.", "qualification": "proposed", "source_ids": [], "evidence_card_ids": [], "survey_anchor_ids": [], "formal_reference_ids": [], "outcome_branch_ids": [], "citation_keys": []},
        ],
        "open_items": [],
        "review_items": [],
    }

    section, audit = SectionComposer().compose(
        preparation,
        blueprint={},
        route=route,
        blueprint_section={"required_open_item_ids": [], "required_review_item_ids": []},
        source_registry=registry,
        llm_call=lambda _prompt, **_kwargs: deepcopy(candidate),
    )

    obligation = next(block for block in section["blocks"] if block["block_id"] == "obligation")
    assert obligation["reference_block_ids"] == ["relation"]
    assert audit is None

    scoped_candidate = deepcopy(candidate)
    scoped_candidate["blocks"][3]["reference_block_ids"] = ["formal_problem_and_hypotheses:relation"]
    scoped_section, scoped_audit = SectionComposer().compose(
        preparation,
        blueprint={},
        route=route,
        blueprint_section={"required_open_item_ids": [], "required_review_item_ids": []},
        source_registry=registry,
        llm_call=lambda _prompt, **_kwargs: deepcopy(scoped_candidate),
    )

    scoped_obligation = next(block for block in scoped_section["blocks"] if block["block_id"] == "obligation")
    assert scoped_obligation["reference_block_ids"] == ["formal_problem_and_hypotheses:relation", "relation"]
    assert scoped_audit is None


def test_section_composer_keeps_an_ambiguous_equation_reference_as_a_quality_warning() -> None:
    route = {
        "section_id": "definitions_and_propositions",
        "title": "Definitions and Propositions",
        "applicability": "required",
        "allowed_claim_kinds": ["formal_definition", "formal_proposition", "proof_obligation"],
    }
    preparation = {
        "source_bundle": {
            "author_context": {
                "provenance": {"discipline_ids": ["26"]},
                "formal_reasoning": {
                    "definitions": [{"definition_id": "D1", "symbol": "F", "statement": "F is defined."}],
                    "assumptions": [{"assumption_id": "A1", "statement": "The domain is retained."}],
                    "propositions": [{"proposition_id": "P1", "conclusion": "F = G"}],
                    "proof_obligations": [{"obligation_id": "PO1", "target": "Check F = G."}],
                    "forward_derivation": {"steps": []},
                },
            },
            "survey_binding": {},
            "idea_evolution": {},
        },
    }
    registry = {
        "allowed_source_ids": [],
        "allowed_survey_anchor_ids": [],
        "evidence_cards_by_id": {},
        "citation_registry": [],
        "unknown_items": [],
        "review_items": [],
    }
    candidate = {
        "schema_version": "research_plan_section_v1",
        "language": "en",
        "section_id": route["section_id"],
        "title": route["title"],
        "applicability": route["applicability"],
        "blocks": [
            {"block_id": "definition", "kind": "definition", "text": "The proposal defines F.", "claim_ids": ["D1"]},
            {"block_id": "assumptions", "kind": "list", "text": "- Retain the declared domain.", "claim_ids": ["D1"]},
            {"block_id": "relation-1", "kind": "equation", "text": "F = G", "claim_ids": ["P1"]},
            {"block_id": "relation-2", "kind": "equation", "text": "F = H", "claim_ids": ["P1"]},
            {
                "block_id": "obligation",
                "kind": "proposition",
                "text": "The proposed obligation fails outside the declared domain.",
                "claim_ids": ["P1"],
                "reference_block_ids": ["assumptions"],
            },
        ],
        "claim_provenance": [
            {"claim_id": "D1", "claim_kind": "formal_definition", "statement": "The proposal defines F.", "qualification": "proposed", "source_ids": [], "evidence_card_ids": [], "survey_anchor_ids": [], "formal_reference_ids": [], "outcome_branch_ids": [], "citation_keys": []},
            {"claim_id": "P1", "claim_kind": "formal_proposition", "statement": "The proposal states bounded relations.", "qualification": "proposed", "source_ids": [], "evidence_card_ids": [], "survey_anchor_ids": [], "formal_reference_ids": [], "outcome_branch_ids": [], "citation_keys": []},
        ],
        "open_items": [],
        "review_items": [],
    }

    section, audit = SectionComposer().compose(
        preparation,
        blueprint={},
        route=route,
        blueprint_section={"required_open_item_ids": [], "required_review_item_ids": []},
        source_registry=registry,
        llm_call=lambda _prompt, **_kwargs: deepcopy(candidate),
    )

    obligation = next(block for block in section["blocks"] if block["block_id"] == "obligation")
    assert obligation["reference_block_ids"] == []
    assert audit is not None
    assert audit["quality_warning_status"] == "WARNING"
    assert "theory artifact quota for definitions_and_propositions has no unambiguous explanatory cross-reference target" in audit["quality_warnings"]
    assert "theory artifact quota for definitions_and_propositions requires an explanatory cross-reference to its equation" in audit["quality_warnings"]


def test_argument_ledger_assigns_detail_to_one_owner_and_context_to_other_sections() -> None:
    routes = [
        {"section_id": "formal_problem_and_hypotheses"},
        {"section_id": "definitions_and_propositions"},
        {"section_id": "forward_derivation_and_counterexamples"},
        {"section_id": "expected_outcomes"},
        {"section_id": "risk_limitations_and_review"},
    ]
    preparation = {
        "source_bundle": {
            "author_context": {
                "formal_reasoning": {
                    "definitions": [
                        {"definition_id": "D1", "symbol": "F", "status": "proposed"},
                    ],
                },
            },
        },
    }
    registry = {
        "unknown_items": [
            {
                "source_item_id": "unknown-definition",
                "original_item": {"field_path": "definitions.D2"},
            },
        ],
        "review_items": [{"source_item_id": "review-release"}],
    }

    ledger = build_authoring_argument_ledger(
        preparation,
        routing={"routes": routes},
        source_registry=registry,
    )
    definition_owner = argument_ledger_context_for_section(
        ledger,
        section_id="definitions_and_propositions",
    )
    forward_context = argument_ledger_context_for_section(
        ledger,
        section_id="forward_derivation_and_counterexamples",
    )
    review_owner = argument_ledger_context_for_section(
        ledger,
        section_id="risk_limitations_and_review",
    )

    assert definition_owner["definition_ledger"]["mode"] == "owner"
    assert {entry["entry_id"] for entry in definition_owner["definition_ledger"]["entries"]} == {
        "definition:D1",
        "unknown:unknown-definition",
    }
    assert forward_context["definition_ledger"] == {
        "kind": "definition_ledger",
        "mode": "reference_only",
        "owner_section_id": "definitions_and_propositions",
        "entry_ids": ["definition:D1", "unknown:unknown-definition"],
    }
    assert forward_context["decision_ledger"]["mode"] == "reference_only"
    assert "entries" not in forward_context["decision_ledger"]
    assert review_owner["decision_ledger"]["mode"] == "owner"

    route = {
        "section_id": "forward_derivation_and_counterexamples",
        "title": "Forward Derivation and Counterexamples",
        "applicability": "required",
        "allowed_claim_kinds": ["forward_derivation", "counterexample_plan"],
    }
    prompt = build_section_composer_prompt(
        preparation,
        {"argument_ledger": ledger},
        route,
        {"required_open_item_ids": [], "required_review_item_ids": []},
        {
            "allowed_source_ids": [],
            "allowed_survey_anchor_ids": [],
            "evidence_cards_by_id": {},
            "citation_registry": [],
            "unknown_items": [],
            "review_items": [],
        },
    )
    prompt_payload = json.loads(prompt.rsplit("INPUT_JSON:\n", 1)[1])

    assert prompt_payload["section_argument_context"] == forward_context
    assert "rather than re-listing the ledger" in prompt


def test_route_registry_exposes_global_evidence_with_nonbinding_recommendations() -> None:
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

    assert set(methods["evidence_cards_by_id"]) == {"C1", "C2", "C3"}
    assert methods["allowed_source_ids"] == ["S1", "S2", "S3"]
    assert set(questions["evidence_cards_by_id"]) == {"C1", "C2", "C3"}
    assert questions["allowed_source_ids"] == ["S1", "S2", "S3"]
    assert set(methods["recommended_source_ids"]) >= {"S1", "S2"}

    knowledge_base = build_authoring_knowledge_base(
        preparation,
        preparation["source_bundle"]["author_context"]["source_registry"],
    )
    assert knowledge_base["source_catalog"]["allowed_source_ids"] == ["S1", "S2", "S3"]
    assert "formal_reasoning" in knowledge_base["upstream_artifacts"]


def test_blueprint_source_selection_never_restricts_global_evidence() -> None:
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

    assert selected["allowed_source_ids"] == ["S1", "S2"]
    assert set(selected["evidence_cards_by_id"]) == {"C1", "C2"}
    assert selected["citation_registry"] == [
        {"citation_key": "cite_s1", "source_id": "S1"},
        {"citation_key": "cite_s2", "source_id": "S2"},
    ]


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
    )
    payload = json.loads(prompt.rsplit("INPUT_JSON:\n", 1)[1])

    assert payload["operation"] == "research_plan_authoring_blueprint_section_assignment"
    assert payload["fixed_section"] == route
    assert "sections" not in payload
    assert payload["output_contract"]["properties"]["section_id"] == {"const": "abstract"}
    assert payload["output_contract"]["properties"]["schema_version"] == {
        "const": AUTHORING_BLUEPRINT_SECTION_ASSIGNMENT_SCHEMA_VERSION
    }
    assert "required_open_item_ids" not in payload["output_contract"]["properties"]
    assert "required_review_item_ids" not in payload["output_contract"]["properties"]
    assert "eligible_unknown_items" not in payload
    assert "eligible_review_items" not in payload
    assert "must_assign_all_remaining" not in payload


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


def test_contract_repair_permits_source_bounded_prose_revision() -> None:
    initial = {"blocks": [{"content": "Existing proposal text."}]}
    repaired = {
        "blocks": [{"block_id": "block-1", "text": "A bounded revision of the proposal text.", "claim_ids": ["A1"]}],
        "claim_provenance": [{"claim_id": "A1", "statement": "A bounded revision of the proposal text."}],
    }

    assert validate_author_contract_repair(initial, repaired) == []


def test_survey_anchors_are_global_private_provenance_not_route_gates() -> None:
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

    assert errors == []

    schema = build_section_output_schema(
        preparation,
        route=route,
        blueprint_section={"required_open_item_ids": [], "required_review_item_ids": []},
        source_registry=registry,
    )
    claim_schema = schema["properties"]["claim_provenance"]["items"]
    assert claim_schema["properties"]["survey_anchor_ids"]["items"] == {
        "enum": ["survey:survey_markdown", "survey:survey_markdown#section-001"]
    }
    section["claim_provenance"][0].update(
        {
            "qualification": "survey_anchored",
            "survey_anchor_ids": ["survey:survey_markdown#section-001"],
        }
    )
    assert validate_section_output(
        section,
        route=route,
        blueprint_section={"required_open_item_ids": [], "required_review_item_ids": []},
        preparation=preparation,
        source_registry=registry,
    ) == []

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

    assert errors == []


def test_section_composer_accepts_survey_provenance_without_evidence_card_recomposition() -> None:
    route = {
        "section_id": "survey_and_research_gap",
        "title": "Background, Survey, and Research Gap",
        "applicability": "required",
        "allowed_claim_kinds": ["survey_evidence"],
    }
    preparation = {"source_bundle": {"author_context": {}, "survey_binding": {}, "idea_evolution": {}}}
    blueprint_section = {
        "section_id": route["section_id"],
        "allowed_source_ids": [],
        "required_open_item_ids": [],
        "required_review_item_ids": [],
    }
    registry = {
        "allowed_source_ids": [],
        "allowed_survey_anchor_ids": ["survey:survey_markdown#section-001"],
        "evidence_cards_by_id": {},
        "citation_registry": [],
        "unknown_items": [],
        "review_items": [],
    }
    initial = {
        "schema_version": "research_plan_section_v1",
        "language": "en",
        "section_id": route["section_id"],
        "title": route["title"],
        "applicability": route["applicability"],
        "blocks": [{"block_id": "survey", "kind": "paragraph", "text": "The verified Survey identifies a bounded gap.", "claim_ids": ["claim-1"]}],
        "claim_provenance": [
            {
                "claim_id": "claim-1",
                "claim_kind": "survey_evidence",
                "statement": "The verified Survey identifies a bounded gap.",
                "qualification": "evidence_backed",
                "source_ids": [],
                "evidence_card_ids": [],
                "survey_anchor_ids": ["survey:survey_markdown#section-001"],
                "formal_reference_ids": [],
                "outcome_branch_ids": [],
                "citation_keys": [],
            }
        ],
        "open_items": [],
        "review_items": [],
    }
    calls: list[dict] = []

    def survey_llm(prompt: str, *, response_format: object) -> dict:
        request = json.loads(prompt.rsplit("INPUT_JSON:\n", 1)[1])
        calls.append(request)
        return deepcopy(initial)

    section, audit = SectionComposer().compose(
        preparation,
        blueprint={"global_constraints": {}},
        route=route,
        blueprint_section=blueprint_section,
        source_registry=registry,
        llm_call=survey_llm,
    )

    assert len(calls) == 1
    assert section["claim_provenance"][0]["qualification"] == "evidence_backed"
    assert audit is None


def test_section_composer_accepts_global_survey_anchor_without_route_repair() -> None:
    route = {
        "section_id": "survey_and_research_gap",
        "title": "Background, Survey, and Research Gap",
        "applicability": "required",
        "allowed_claim_kinds": ["survey_evidence"],
    }
    preparation = {"source_bundle": {"author_context": {}, "survey_binding": {}, "idea_evolution": {}}}
    blueprint_section = {
        "section_id": route["section_id"],
        "allowed_source_ids": [],
        "required_open_item_ids": [],
        "required_review_item_ids": [],
    }
    registry = {
        "allowed_source_ids": [],
        "allowed_survey_anchor_ids": ["survey:survey_markdown#section-001"],
        "evidence_cards_by_id": {},
        "citation_registry": [],
        "unknown_items": [],
        "review_items": [],
    }
    missing_anchor = {
        "schema_version": "research_plan_section_v1",
        "language": "en",
        "section_id": route["section_id"],
        "title": route["title"],
        "applicability": route["applicability"],
        "blocks": [{"block_id": "survey", "kind": "paragraph", "text": "The verified Survey identifies a bounded gap.", "claim_ids": ["claim-1"]}],
        "claim_provenance": [
            {
                "claim_id": "claim-1",
                "claim_kind": "survey_evidence",
                "statement": "The verified Survey identifies a bounded gap.",
                "qualification": "survey_anchored",
                "source_ids": [],
                "evidence_card_ids": [],
                "survey_anchor_ids": ["survey:survey_markdown#section-001"],
                "formal_reference_ids": [],
                "outcome_branch_ids": [],
                "citation_keys": [],
            }
        ],
        "open_items": [],
        "review_items": [],
    }
    calls: list[dict] = []

    def survey_llm(prompt: str, *, response_format: object) -> dict:
        request = json.loads(prompt.rsplit("INPUT_JSON:\n", 1)[1])
        calls.append(request)
        return deepcopy(missing_anchor)

    section, audit = SectionComposer().compose(
        preparation,
        blueprint={"global_constraints": {}},
        route=route,
        blueprint_section=blueprint_section,
        source_registry=registry,
        llm_call=survey_llm,
        allow_contract_repair=False,
    )

    assert len(calls) == 1
    assert section["claim_provenance"][0]["survey_anchor_ids"] == ["survey:survey_markdown#section-001"]
    assert audit is None


def test_section_composer_allows_canonical_formal_references_in_synthesized_claims() -> None:
    route = {
        "section_id": "formal_problem_and_hypotheses",
        "title": "Problem Definition, Assumptions, and Hypotheses",
        "applicability": "required",
        "allowed_claim_kinds": ["formal_definition", "hypothesis"],
    }
    preparation = {
        "source_bundle": {
            "author_context": {
                "formal_reasoning": {"definitions": [{"definition_id": "F1"}]},
            },
            "survey_binding": {},
            "idea_evolution": {},
        }
    }
    blueprint_section = {
        "section_id": route["section_id"],
        "allowed_source_ids": [],
        "required_open_item_ids": [],
        "required_review_item_ids": [],
    }
    registry = {
        "allowed_source_ids": [],
        "allowed_survey_anchor_ids": [],
        "evidence_cards_by_id": {},
        "citation_registry": [],
        "unknown_items": [],
        "review_items": [],
    }
    initial = {
        "schema_version": "research_plan_section_v1",
        "language": "en",
        "section_id": route["section_id"],
        "title": route["title"],
        "applicability": route["applicability"],
        "blocks": [
            {"block_id": "hypothesis", "kind": "paragraph", "text": "The proposal states a testable hypothesis.", "claim_ids": ["A1"]},
            {"block_id": "formal", "kind": "definition", "text": "The proof establishes the required condition.", "claim_ids": ["P1"]},
        ],
        "claim_provenance": [
            {
                "claim_id": "A1",
                "claim_kind": "hypothesis",
                "statement": "The proposal states a testable hypothesis.",
                "qualification": "proposed",
                "source_ids": [],
                "evidence_card_ids": [],
                "survey_anchor_ids": [],
                "formal_reference_ids": ["F1"],
                "outcome_branch_ids": [],
                "citation_keys": [],
            },
            {
                "claim_id": "P1",
                "claim_kind": "formal_definition",
                "statement": "The proposal defines the required condition.",
                "qualification": "proposed",
                "source_ids": [],
                "evidence_card_ids": [],
                "survey_anchor_ids": [],
                "formal_reference_ids": [],
                "outcome_branch_ids": [],
                "citation_keys": [],
            },
        ],
        "open_items": [],
        "review_items": [],
    }
    calls: list[dict] = []

    def formal_llm(prompt: str, *, response_format: object) -> dict:
        request = json.loads(prompt.rsplit("INPUT_JSON:\n", 1)[1])
        calls.append(request)
        return deepcopy(initial)

    section, audit = SectionComposer().compose(
        preparation,
        blueprint={"global_constraints": {}},
        route=route,
        blueprint_section=blueprint_section,
        source_registry=registry,
        llm_call=formal_llm,
        allow_contract_repair=False,
    )

    assert len(calls) == 1
    assert section["claim_provenance"][0]["formal_reference_ids"] == ["F1"]
    assert section["blocks"][1]["text"] == "The proof establishes the required condition."
    assert audit is None


def test_section_composer_fills_omitted_provenance_lists_without_repair() -> None:
    route = {
        "section_id": "definitions_and_propositions",
        "title": "Definitions and Propositions",
        "applicability": "required",
        "allowed_claim_kinds": ["formal_definition"],
    }
    preparation = {"source_bundle": {"author_context": {}, "survey_binding": {}, "idea_evolution": {}}}
    blueprint_section = {
        "section_id": route["section_id"],
        "allowed_source_ids": [],
        "required_open_item_ids": [],
        "required_review_item_ids": [],
    }
    incomplete = {
        "schema_version": "research_plan_section_v1",
        "language": "en",
        "section_id": route["section_id"],
        "title": route["title"],
        "applicability": route["applicability"],
        "blocks": [{"block_id": "definition", "kind": "definition", "text": "The proposal defines the bounded condition.", "claim_ids": ["D1"]}],
        "claim_provenance": [
            {
                "claim_id": "D1",
                "claim_kind": "formal_definition",
                "statement": "The proposal defines the bounded condition.",
                "qualification": "proposed",
                "source_ids": [],
                "evidence_card_ids": [],
                "survey_anchor_ids": [],
                "formal_reference_ids": [],
            }
        ],
        "open_items": [],
        "review_items": [],
    }

    def incomplete_llm(_prompt: str, *, response_format: object) -> dict:
        assert response_format == {"type": "json_object"}
        return deepcopy(incomplete)

    section, audit = SectionComposer().compose(
        preparation,
        blueprint={"global_constraints": {}},
        route=route,
        blueprint_section=blueprint_section,
        source_registry={
            "allowed_source_ids": [],
            "allowed_survey_anchor_ids": [],
            "evidence_cards_by_id": {},
            "citation_registry": [],
            "unknown_items": [],
            "review_items": [],
        },
        llm_call=incomplete_llm,
        allow_contract_repair=False,
    )

    assert audit is None
    assert section["claim_provenance"][0]["outcome_branch_ids"] == []
    assert section["claim_provenance"][0]["citation_keys"] == []


def test_section_composer_demotes_prose_disguised_as_an_equation_to_quality_warning() -> None:
    route = {
        "section_id": "formal_problem_and_hypotheses",
        "title": "Problem Definition, Assumptions, and Hypotheses",
        "applicability": "required",
        "allowed_claim_kinds": ["formal_definition"],
    }
    candidate = {
        "schema_version": "research_plan_section_v1",
        "language": "en",
        "section_id": route["section_id"],
        "title": route["title"],
        "applicability": route["applicability"],
        "blocks": [{"block_id": "relation", "kind": "equation", "text": "The proposed relation requires a missing premise.", "claim_ids": ["D1"]}],
        "claim_provenance": [{"claim_id": "D1", "claim_kind": "formal_definition", "statement": "The proposal defines a bounded relation.", "qualification": "proposed", "source_ids": [], "evidence_card_ids": [], "survey_anchor_ids": [], "formal_reference_ids": [], "outcome_branch_ids": [], "citation_keys": []}],
        "open_items": [],
        "review_items": [],
    }

    section, audit = SectionComposer().compose(
        {"source_bundle": {"author_context": {}, "survey_binding": {}, "idea_evolution": {}}},
        blueprint={"global_constraints": {}},
        route=route,
        blueprint_section={"required_open_item_ids": [], "required_review_item_ids": []},
        source_registry={"allowed_source_ids": [], "allowed_survey_anchor_ids": [], "evidence_cards_by_id": {}, "citation_registry": [], "unknown_items": [], "review_items": []},
        llm_call=lambda *_args, **_kwargs: deepcopy(candidate),
        allow_contract_repair=False,
    )

    assert section["blocks"][0]["kind"] == "paragraph"
    assert audit is not None
    assert any("rendered as prose" in warning for warning in audit["quality_warnings"])


def test_section_composer_keeps_valid_formulae_in_a_mixed_equation_block() -> None:
    route = {
        "section_id": "formal_problem_and_hypotheses",
        "title": "Problem Definition, Assumptions, and Hypotheses",
        "applicability": "required",
        "allowed_claim_kinds": ["formal_definition"],
    }
    candidate = {
        "schema_version": "research_plan_section_v1",
        "language": "en",
        "section_id": route["section_id"],
        "title": route["title"],
        "applicability": route["applicability"],
        "blocks": [
            {
                "block_id": "relation",
                "kind": "equation",
                "text": (
                    "The proposal introduces a null focusing relation.\n\n"
                    r"\int_\gamma T_{ab} k^a k^b \, d\lambda \geq 0 ."
                    "\n\n"
                    "The conclusion remains conditional on the stated domain."
                ),
                "claim_ids": ["D1"],
            }
        ],
        "claim_provenance": [
            {
                "claim_id": "D1",
                "claim_kind": "formal_definition",
                "statement": "The proposal defines a bounded null focusing relation.",
                "qualification": "proposed",
                "source_ids": [],
                "evidence_card_ids": [],
                "survey_anchor_ids": [],
                "formal_reference_ids": [],
                "outcome_branch_ids": [],
                "citation_keys": [],
            }
        ],
        "open_items": [],
        "review_items": [],
    }

    section, audit = SectionComposer().compose(
        {"source_bundle": {"author_context": {}, "survey_binding": {}, "idea_evolution": {}}},
        blueprint={"global_constraints": {}},
        route=route,
        blueprint_section={"required_open_item_ids": [], "required_review_item_ids": []},
        source_registry={"allowed_source_ids": [], "allowed_survey_anchor_ids": [], "evidence_cards_by_id": {}, "citation_registry": [], "unknown_items": [], "review_items": []},
        llm_call=lambda *_args, **_kwargs: deepcopy(candidate),
        allow_contract_repair=False,
    )

    assert section["blocks"][0]["kind"] == "equation"
    assert audit is not None
    assert any("will split it from valid mathematics" in warning for warning in audit["quality_warnings"])


def test_section_composer_normalizes_review_requirement_qualification_without_recomposition() -> None:
    route = {
        "section_id": "risk_limitations_and_review",
        "title": "Risks, Limitations, and Human Review Requirements",
        "applicability": "required",
        "allowed_claim_kinds": ["review_requirement"],
    }
    preparation = {"source_bundle": {"author_context": {}, "survey_binding": {}, "idea_evolution": {}}}
    blueprint_section = {
        "section_id": route["section_id"],
        "allowed_source_ids": [],
        "required_open_item_ids": [],
        "required_review_item_ids": [],
    }
    invalid = {
        "schema_version": "research_plan_section_v1",
        "language": "en",
        "section_id": route["section_id"],
        "title": route["title"],
        "applicability": route["applicability"],
        "blocks": [{"block_id": "review", "kind": "paragraph", "text": "A qualified reviewer must assess the unresolved premise.", "claim_ids": ["R1"]}],
        "claim_provenance": [
            {
                "claim_id": "R1",
                "claim_kind": "review_requirement",
                "statement": "A qualified reviewer must assess the unresolved premise.",
                "qualification": "review_requirement",
                "source_ids": [],
                "evidence_card_ids": [],
                "survey_anchor_ids": [],
                "formal_reference_ids": [],
                "outcome_branch_ids": [],
                "citation_keys": [],
            }
        ],
        "open_items": [],
        "review_items": [],
    }
    calls: list[dict] = []

    def review_llm(prompt: str, *, response_format: object) -> dict:
        request = json.loads(prompt.rsplit("INPUT_JSON:\n", 1)[1])
        calls.append(request)
        assert "provenance_recomposition" not in request
        return deepcopy(invalid)

    section, audit = SectionComposer().compose(
        preparation,
        blueprint={"global_constraints": {}},
        route=route,
        blueprint_section=blueprint_section,
        source_registry={
            "allowed_source_ids": [],
            "allowed_survey_anchor_ids": [],
            "evidence_cards_by_id": {},
            "citation_registry": [],
            "unknown_items": [],
            "review_items": [],
        },
        llm_call=review_llm,
        allow_contract_repair=False,
    )

    assert len(calls) == 1
    assert section["claim_provenance"][0]["qualification"] == "needs_human_input"
    assert audit is None


def test_section_composer_normalizes_limitation_qualification_without_recomposition() -> None:
    route = {
        "section_id": "risk_limitations_and_review",
        "title": "Risks, Limitations, and Human Review Requirements",
        "applicability": "required",
        "allowed_claim_kinds": ["limitation"],
    }
    preparation = {"source_bundle": {"author_context": {}, "survey_binding": {}, "idea_evolution": {}}}
    blueprint_section = {
        "section_id": route["section_id"],
        "allowed_source_ids": ["S1", "S2"],
        "required_open_item_ids": [],
        "required_review_item_ids": [],
    }
    invalid = {
        "schema_version": "research_plan_section_v1",
        "language": "en",
        "section_id": route["section_id"],
        "title": route["title"],
        "applicability": route["applicability"],
        "blocks": [
            {"block_id": "evidence", "kind": "paragraph", "text": "The supplied evidence identifies a bounded limitation.", "claim_ids": ["L1"]},
            {"block_id": "review", "kind": "paragraph", "text": "Human review is required for the unresolved limitation.", "claim_ids": ["L2"]},
            {"block_id": "mitigation", "kind": "paragraph", "text": "The plan will mitigate this limitation through a review step.", "claim_ids": ["L3"]},
            {"block_id": "unknown", "kind": "paragraph", "text": "The effect of this limitation remains unresolved.", "claim_ids": ["L4"]},
        ],
        "claim_provenance": [
            {"claim_id": "L1", "claim_kind": "limitation", "statement": "The supplied evidence identifies a bounded limitation.", "qualification": "limitation", "source_ids": ["S1"], "evidence_card_ids": ["C1"], "survey_anchor_ids": [], "formal_reference_ids": [], "outcome_branch_ids": [], "citation_keys": ["cite_s1"]},
            {"claim_id": "L2", "claim_kind": "limitation", "statement": "Human review is required for the unresolved limitation.", "qualification": "limitation", "source_ids": [], "evidence_card_ids": [], "survey_anchor_ids": [], "formal_reference_ids": [], "outcome_branch_ids": [], "citation_keys": []},
            {"claim_id": "L3", "claim_kind": "limitation", "statement": "The plan will mitigate this limitation through a review step.", "qualification": "limitation", "source_ids": [], "evidence_card_ids": [], "survey_anchor_ids": [], "formal_reference_ids": [], "outcome_branch_ids": [], "citation_keys": []},
            {"claim_id": "L4", "claim_kind": "limitation", "statement": "The effect of this limitation remains unresolved.", "qualification": "limitation", "source_ids": [], "evidence_card_ids": [], "survey_anchor_ids": [], "formal_reference_ids": [], "outcome_branch_ids": [], "citation_keys": []},
        ],
        "open_items": [],
        "review_items": [],
    }
    calls: list[str] = []

    def limitation_llm(prompt: str, *, response_format: object) -> dict:
        calls.append(prompt)
        return deepcopy(invalid)

    section, audit = SectionComposer().compose(
        preparation,
        blueprint={"global_constraints": {}},
        route=route,
        blueprint_section=blueprint_section,
        source_registry={
            "allowed_source_ids": ["S1"],
            "allowed_survey_anchor_ids": [],
            "evidence_cards_by_id": {"C1": {"source_id": "S1", "support_statement": "The supplied evidence identifies a bounded limitation."}},
            "citation_registry": [{"source_id": "S1", "citation_key": "cite_s1"}],
            "unknown_items": [],
            "review_items": [],
        },
        llm_call=limitation_llm,
        allow_contract_repair=False,
    )

    assert len(calls) == 1
    assert [claim["qualification"] for claim in section["claim_provenance"]] == [
        "evidence_backed",
        "needs_human_input",
        "proposed",
        "unverified",
    ]
    assert audit is None


def test_section_composer_derives_source_and_citation_from_evidence_card() -> None:
    route = {
        "section_id": "introduction",
        "title": "Introduction",
        "applicability": "required",
        "allowed_claim_kinds": ["background"],
    }
    preparation = {"source_bundle": {"author_context": {}, "survey_binding": {}, "idea_evolution": {}}}
    blueprint_section = {
        "section_id": route["section_id"],
        "allowed_source_ids": ["S1", "S2"],
        "required_open_item_ids": [],
        "required_review_item_ids": [],
    }
    candidate = {
        "schema_version": "research_plan_section_v1",
        "language": "en",
        "section_id": route["section_id"],
        "title": route["title"],
        "applicability": route["applicability"],
        "blocks": [{"block_id": "background", "kind": "paragraph", "text": "The supplied evidence states a bounded background relation.", "claim_ids": ["B1"]}],
        "claim_provenance": [
            {
                "claim_id": "B1",
                "claim_kind": "background",
                "statement": "The supplied evidence states a bounded background relation.",
                "qualification": "evidence_backed",
                "source_ids": ["S2"],
                "evidence_card_ids": ["C1"],
                "survey_anchor_ids": [],
                "formal_reference_ids": [],
                "outcome_branch_ids": [],
                "citation_keys": ["cite_invented"],
            }
        ],
        "open_items": [],
        "review_items": [],
    }
    calls: list[str] = []

    def evidence_llm(prompt: str, *, response_format: object) -> dict:
        calls.append(prompt)
        return deepcopy(candidate)

    section, audit = SectionComposer().compose(
        preparation,
        blueprint={"global_constraints": {}},
        route=route,
        blueprint_section=blueprint_section,
        source_registry={
            "allowed_source_ids": ["S1", "S2"],
            "allowed_survey_anchor_ids": [],
            "evidence_cards_by_id": {"C1": {"source_id": "S1", "support_statement": "The supplied evidence states a bounded background relation."}},
            "citation_registry": [
                {"source_id": "S1", "citation_key": "cite_s1"},
                {"source_id": "S2", "citation_key": "cite_s2"},
            ],
            "unknown_items": [],
            "review_items": [],
        },
        llm_call=evidence_llm,
        allow_contract_repair=False,
    )

    assert len(calls) == 1
    assert section["claim_provenance"][0]["source_ids"] == ["S1", "S2"]
    assert section["claim_provenance"][0]["citation_keys"] == ["cite_s1", "cite_s2"]
    assert audit is None


def test_section_validator_allows_evidence_backed_paraphrase_without_support_statement() -> None:
    route = {
        "section_id": "introduction",
        "title": "Introduction",
        "applicability": "required",
        "allowed_claim_kinds": ["background"],
    }
    registry = {
        "allowed_source_ids": ["S1"],
        "allowed_survey_anchor_ids": [],
        "evidence_cards_by_id": {
            "C1": {
                "source_id": "S1",
                "claim_slot": "mechanism",
                "citation_key": "cite_s1",
            }
        },
        "citation_registry": [{"source_id": "S1", "citation_key": "cite_s1"}],
        "unknown_items": [],
        "review_items": [],
    }
    section = {
        "schema_version": "research_plan_section_v1",
        "language": "en",
        "section_id": route["section_id"],
        "title": route["title"],
        "applicability": route["applicability"],
        "blocks": [{"block_id": "background", "kind": "paragraph", "text": "An unsupported factual statement.", "claim_ids": ["claim-1"]}],
        "claim_provenance": [
            {
                "claim_id": "claim-1",
                "claim_kind": "background",
                "statement": "An unsupported factual statement.",
                "qualification": "evidence_backed",
                "source_ids": ["S1"],
                "evidence_card_ids": ["C1"],
                "survey_anchor_ids": [],
                "formal_reference_ids": [],
                "outcome_branch_ids": [],
                "citation_keys": ["cite_s1"],
            }
        ],
        "open_items": [],
        "review_items": [],
    }

    errors = validate_section_output(
        section,
        route=route,
        blueprint_section={"required_open_item_ids": [], "required_review_item_ids": []},
        preparation={"source_bundle": {"author_context": {}}},
        source_registry=registry,
    )

    assert errors == []


def test_section_output_contract_exposes_global_references_to_abstract() -> None:
    route = {
        "section_id": "abstract",
        "title": "Abstract",
        "applicability": "required",
        "allowed_claim_kinds": ["planned_contribution", "expected_outcome"],
    }
    preparation = {
        "source_bundle": {
            "author_context": {
                "outcome_branches": [{"branch_id": "supports_mechanism"}],
            }
        }
    }
    schema = build_section_output_schema(
        preparation,
        route=route,
        blueprint_section={"required_open_item_ids": [], "required_review_item_ids": []},
        source_registry={
            "allowed_source_ids": [],
            "allowed_survey_anchor_ids": ["survey:survey_markdown#section-001"],
            "evidence_cards_by_id": {},
            "citation_registry": [],
        },
    )
    claim_schema = schema["properties"]["claim_provenance"]["items"]

    assert schema["properties"]["section_id"] == {"const": "abstract"}
    assert schema["properties"]["blocks"]["items"]["properties"]["heading"] == {"type": "string"}
    assert claim_schema["properties"]["claim_kind"] == {"enum": ["expected_outcome", "planned_contribution"]}
    assert claim_schema["properties"]["survey_anchor_ids"] == {
        "type": "array",
        "items": {"enum": ["survey:survey_markdown#section-001"]},
        "uniqueItems": True,
    }
    assert claim_schema["properties"]["outcome_branch_ids"]["items"] == {"enum": ["supports_mechanism"]}
    assert claim_schema["allOf"][0]["then"]["properties"]["outcome_branch_ids"] == {"minItems": 1}


def test_introduction_contract_preserves_evidence_claim_kinds_without_selected_sources() -> None:
    route = {
        "section_id": "introduction",
        "title": "Introduction",
        "applicability": "required",
        "allowed_claim_kinds": ["background", "research_gap", "planned_contribution", "design_assumption"],
    }
    schema = build_section_output_schema(
        {"source_bundle": {"author_context": {}}},
        route=route,
        blueprint_section={"required_open_item_ids": [], "required_review_item_ids": []},
        source_registry={
            "allowed_source_ids": [],
            "allowed_survey_anchor_ids": [],
            "evidence_cards_by_id": {},
            "citation_registry": [],
        },
    )
    claim_schema = schema["properties"]["claim_provenance"]["items"]

    assert claim_schema["properties"]["claim_kind"] == {
        "enum": ["background", "design_assumption", "planned_contribution", "research_gap"]
    }

    sourced_schema = build_section_output_schema(
        {"source_bundle": {"author_context": {}}},
        route=route,
        blueprint_section={"required_open_item_ids": [], "required_review_item_ids": []},
        source_registry={
            "allowed_source_ids": ["S1"],
            "allowed_survey_anchor_ids": [],
            "evidence_cards_by_id": {"C1": {"source_id": "S1"}},
            "citation_registry": [{"source_id": "S1", "citation_key": "cite_s1"}],
        },
    )

    assert sourced_schema["properties"]["claim_provenance"]["items"]["properties"]["claim_kind"] == {
        "enum": ["background", "design_assumption", "planned_contribution", "research_gap"]
    }


def test_section_output_schema_allows_unlinked_background_synthesis() -> None:
    route = {
        "section_id": "introduction",
        "title": "Introduction",
        "applicability": "required",
        "allowed_claim_kinds": ["background", "planned_contribution"],
    }
    registry = {
        "allowed_source_ids": ["S1"],
        "allowed_survey_anchor_ids": [],
        "evidence_cards_by_id": {"C1": {"source_id": "S1", "claim_slot": "mechanism"}},
        "citation_registry": [{"source_id": "S1", "citation_key": "cite_s1"}],
        "unknown_items": [],
        "review_items": [],
    }
    schema = build_section_output_schema(
        {"source_bundle": {"author_context": {}}},
        route=route,
        blueprint_section={"required_open_item_ids": [], "required_review_item_ids": []},
        source_registry=registry,
    )
    section = {
        "schema_version": "research_plan_section_v1",
        "language": "en",
        "section_id": "introduction",
        "title": "Introduction",
        "applicability": "required",
        "blocks": [{"block_id": "background", "kind": "paragraph", "text": "A bounded background statement.", "claim_ids": ["claim-1"]}],
        "claim_provenance": [
            {
                "claim_id": "claim-1",
                "claim_kind": "background",
                "statement": "A bounded background statement.",
                "qualification": "evidence_backed",
                "source_ids": [],
                "evidence_card_ids": [],
                "survey_anchor_ids": [],
                "formal_reference_ids": [],
                "outcome_branch_ids": [],
                "citation_keys": [],
            }
        ],
        "open_items": [],
        "review_items": [],
    }

    errors = list(Draft202012Validator(schema).iter_errors(section))

    assert errors == []
    validation_errors = validate_section_output(
        section,
        route=route,
        blueprint_section={"required_open_item_ids": [], "required_review_item_ids": []},
        preparation={"source_bundle": {"author_context": {}}},
        source_registry=registry,
    )
    assert validation_errors == []


def test_section_composer_allows_proposed_synthesis_without_evidence_card_recomposition() -> None:
    route = {
        "section_id": "introduction",
        "title": "Introduction",
        "applicability": "required",
        "allowed_claim_kinds": ["background", "planned_contribution"],
    }
    preparation = {"source_bundle": {"author_context": {}, "survey_binding": {}, "idea_evolution": {}}}
    blueprint_section = {
        "section_id": "introduction",
        "allowed_source_ids": ["S1"],
        "required_open_item_ids": [],
        "required_review_item_ids": [],
    }
    registry = {
        "allowed_source_ids": ["S1"],
        "allowed_survey_anchor_ids": [],
        "evidence_cards_by_id": {
            "C1": {
                "source_id": "S1",
                "claim_slot": "mechanism",
                "citation_key": "cite_s1",
                "support_statement": "The supplied evidence establishes a bounded background relation.",
            }
        },
        "citation_registry": [{"source_id": "S1", "citation_key": "cite_s1"}],
        "unknown_items": [],
        "review_items": [],
    }
    initial = {
        "schema_version": "research_plan_section_v1",
        "language": "en",
        "section_id": "introduction",
        "title": "Introduction",
        "applicability": "required",
        "blocks": [{"block_id": "background", "kind": "paragraph", "text": "An unsupported source-bounded background statement.", "claim_ids": ["claim-1"]}],
        "claim_provenance": [
            {
                "claim_id": "claim-1",
                "claim_kind": "planned_contribution",
                "statement": "An unsupported source-bounded background statement.",
                "qualification": "proposed",
                "source_ids": [],
                "evidence_card_ids": [],
                "survey_anchor_ids": [],
                "formal_reference_ids": [],
                "outcome_branch_ids": [],
                "citation_keys": [],
            }
        ],
        "open_items": [],
        "review_items": [],
    }
    calls: list[dict] = []

    def provenance_llm(prompt: str, *, response_format: object) -> dict:
        request = json.loads(prompt.rsplit("INPUT_JSON:\n", 1)[1])
        calls.append(request)
        return deepcopy(initial)

    section, audit = SectionComposer().compose(
        preparation,
        blueprint={"global_constraints": {}},
        route=route,
        blueprint_section=blueprint_section,
        source_registry=registry,
        llm_call=provenance_llm,
    )

    assert len(calls) == 1
    assert section["claim_provenance"][0]["source_ids"] == []
    assert audit is None


def test_section_validator_still_rejects_forged_source_citation_and_formal_ids() -> None:
    route = {
        "section_id": "formal_problem_and_hypotheses",
        "title": "Problem Definition, Assumptions, and Hypotheses",
        "applicability": "required",
        "allowed_claim_kinds": ["formal_definition"],
    }
    payload = {
        "schema_version": "research_plan_section_v1",
        "language": "en",
        "section_id": route["section_id"],
        "title": route["title"],
        "applicability": route["applicability"],
        "blocks": [{"block_id": "definition", "kind": "definition", "text": "The proposal defines a bounded object.", "claim_ids": ["D1"]}],
        "claim_provenance": [{"claim_id": "D1", "claim_kind": "formal_definition", "statement": "The proposal defines a bounded object.", "qualification": "proposed", "source_ids": ["S-forged"], "evidence_card_ids": [], "survey_anchor_ids": [], "formal_reference_ids": ["F-forged"], "outcome_branch_ids": [], "citation_keys": ["cite_forged"]}],
        "open_items": [],
        "review_items": [],
    }
    errors = validate_section_output(
        payload,
        route=route,
        blueprint_section={"required_open_item_ids": [], "required_review_item_ids": []},
        preparation={"source_bundle": {"author_context": {"formal_reasoning": {"definitions": [{"definition_id": "F1"}]}}}},
        source_registry={"allowed_source_ids": ["S1"], "allowed_survey_anchor_ids": [], "evidence_cards_by_id": {}, "citation_registry": [{"source_id": "S1", "citation_key": "cite_s1"}]},
    )

    assert any("unknown source IDs" in error for error in errors)
    assert any("unknown formal records" in error for error in errors)
    assert any("invented citation keys" in error for error in errors)


def test_section_validator_allows_multi_source_synthesis_without_card_slot_matching() -> None:
    route = {
        "section_id": "introduction",
        "title": "Introduction",
        "applicability": "required",
        "allowed_claim_kinds": ["background"],
    }
    registry = {
        "allowed_source_ids": ["S1", "S2", "S3"],
        "allowed_survey_anchor_ids": [],
        "evidence_cards_by_id": {
            "C2": {
                "source_id": "S2",
                "claim_slot": "mechanism",
                "support_statement": "The source supports a different bounded statement.",
            }
        },
        "citation_registry": [
            {"source_id": "S1", "citation_key": "cite_s1"},
            {"source_id": "S2", "citation_key": "cite_s2"},
            {"source_id": "S3", "citation_key": "cite_s3"},
        ],
        "unknown_items": [],
        "review_items": [],
    }
    section = {
        "schema_version": "research_plan_section_v1",
        "language": "en",
        "section_id": "introduction",
        "title": "Introduction",
        "applicability": "required",
        "blocks": [{"block_id": "background", "kind": "paragraph", "text": "A bounded background statement.", "claim_ids": ["claim-1"]}],
        "claim_provenance": [
            {
                "claim_id": "claim-1",
                "claim_kind": "background",
                "statement": "A bounded background statement.",
                "qualification": "evidence_backed",
                "source_ids": ["S1"],
                "evidence_card_ids": ["C2"],
                "survey_anchor_ids": [],
                "formal_reference_ids": [],
                "outcome_branch_ids": [],
                "citation_keys": ["cite_s3"],
            }
        ],
        "open_items": [],
        "review_items": [],
    }

    errors = validate_section_output(
        section,
        route=route,
        blueprint_section={"required_open_item_ids": [], "required_review_item_ids": []},
        preparation={"source_bundle": {"author_context": {}}},
        source_registry=registry,
    )

    assert errors == []

    section["claim_provenance"][0].update({"source_ids": ["S2"], "citation_keys": ["cite_s2"]})
    assert validate_section_output(
        section,
        route=route,
        blueprint_section={"required_open_item_ids": [], "required_review_item_ids": []},
        preparation={"source_bundle": {"author_context": {}}},
        source_registry=registry,
    ) == []


def test_section_composer_compiles_citation_keys_from_sources_not_private_survey_anchors() -> None:
    route = {
        "section_id": "survey_and_research_gap",
        "title": "Background, Survey, and Research Gap",
        "applicability": "required",
        "allowed_claim_kinds": ["survey_evidence"],
    }
    preparation = {"source_bundle": {"author_context": {}, "survey_binding": {}, "idea_evolution": {}}}
    blueprint_section = {"required_open_item_ids": [], "required_review_item_ids": []}
    registry = {
        "allowed_source_ids": [],
        "allowed_survey_anchor_ids": ["survey:survey_markdown#section-003"],
        "evidence_cards_by_id": {},
        "citation_registry": [{"source_id": "S1", "citation_key": "cite_s1"}],
        "unknown_items": [],
        "review_items": [],
    }
    payload = {
        "schema_version": "research_plan_section_v1",
        "language": "en",
        "section_id": route["section_id"],
        "title": route["title"],
        "applicability": route["applicability"],
        "blocks": [{"block_id": "survey-finding", "kind": "paragraph", "text": "The Survey identifies a bounded finding.", "claim_ids": ["c2"]}],
        "claim_provenance": [
            {
                "claim_id": "c2",
                "claim_kind": "survey_evidence",
                "statement": "The Survey identifies a bounded finding.",
                "qualification": "survey_anchored",
                "source_ids": [],
                "evidence_card_ids": [],
                "survey_anchor_ids": ["survey:survey_markdown#section-003"],
                "formal_reference_ids": [],
                "outcome_branch_ids": [],
                "citation_keys": ["cite_s1"],
            }
        ],
        "open_items": [],
        "review_items": [],
    }

    raw_errors = validate_section_output(
        payload,
        route=route,
        blueprint_section=blueprint_section,
        preparation=preparation,
        source_registry=registry,
    )
    assert raw_errors == []

    section, audit = SectionComposer().compose(
        preparation,
        blueprint={"global_constraints": {}},
        route=route,
        blueprint_section=blueprint_section,
        source_registry=registry,
        llm_call=lambda *_args, **_kwargs: deepcopy(payload),
        allow_contract_repair=False,
    )

    assert audit is None
    assert section["claim_provenance"][0]["citation_keys"] == []


def test_section_composer_preserves_valid_survey_anchors_outside_the_survey_route() -> None:
    route = {
        "section_id": "introduction",
        "title": "Introduction",
        "applicability": "required",
        "allowed_claim_kinds": ["background"],
    }
    preparation = {"source_bundle": {"author_context": {}, "survey_binding": {}, "idea_evolution": {}}}
    blueprint_section = {"required_open_item_ids": [], "required_review_item_ids": []}
    registry = {
        "allowed_source_ids": ["S1"],
        "allowed_survey_anchor_ids": ["anchor:gap_evidence_anchor:sh4:boundary_variable"],
        "evidence_cards_by_id": {
            "C1": {"source_id": "S1", "citation_key": "cite_s1", "support_statement": "A bounded background statement."}
        },
        "citation_registry": [{"source_id": "S1", "citation_key": "cite_s1"}],
        "unknown_items": [],
        "review_items": [],
    }
    payload = {
        "schema_version": "research_plan_section_v1",
        "language": "en",
        "section_id": route["section_id"],
        "title": route["title"],
        "applicability": route["applicability"],
        "blocks": [{"block_id": "background", "kind": "paragraph", "text": "A bounded background statement.", "claim_ids": ["c1"]}],
        "claim_provenance": [
            {
                "claim_id": "c1",
                "claim_kind": "background",
                "statement": "A bounded background statement.",
                "qualification": "evidence_backed",
                "source_ids": ["S1"],
                "evidence_card_ids": ["C1"],
                "survey_anchor_ids": ["anchor:gap_evidence_anchor:sh4:boundary_variable"],
                "formal_reference_ids": [],
                "outcome_branch_ids": [],
                "citation_keys": ["cite_s1"],
            }
        ],
        "open_items": [],
        "review_items": [],
    }

    section, audit = SectionComposer().compose(
        preparation,
        blueprint={"global_constraints": {}},
        route=route,
        blueprint_section=blueprint_section,
        source_registry=registry,
        llm_call=lambda *_args, **_kwargs: deepcopy(payload),
        allow_contract_repair=False,
    )

    assert audit is None
    assert section["claim_provenance"][0]["survey_anchor_ids"] == ["anchor:gap_evidence_anchor:sh4:boundary_variable"]


def test_section_contract_diagnostics_collects_multiple_route_failures(monkeypatch, tmp_path: Path) -> None:
    path = _write_input(tmp_path, _author_input("26"))
    import src.agents.research_plan_author.run as author_run

    monkeypatch.setattr(author_run, "load_verified_survey_sources", lambda _path: _survey_sources(tmp_path))
    monkeypatch.setattr(
        author_run,
        "_render_composed_document",
        lambda *_args, **_kwargs: pytest.fail("diagnostic failures must not render a partial document"),
    )
    log_path = tmp_path / "author.jsonl"
    logger = AuthorRunLogger("author-test", jsonl_path=log_path)
    attempted_sections: list[str] = []

    def invalid_route_llm(prompt: str, *, response_format: object) -> dict:
        response = _fake_author_llm(prompt, response_format=response_format)
        payload = json.loads(prompt.rsplit("INPUT_JSON:\n", 1)[1])
        if payload.get("operation") == "research_plan_section_composition":
            section_id = payload["route"]["section_id"]
            attempted_sections.append(section_id)
            if section_id in {"abstract", "idea_origin_and_selection"}:
                response["claim_provenance"][0]["qualification"] = "unsupported_qualification"
        return response

    with pytest.raises(AuthorCompositionError) as error:
        run_research_plan_author(
            path,
            survey_manifest_path=tmp_path / "survey_manifest.json",
            include_idea_evolution="off",
            llm_call=invalid_route_llm,
            max_contract_repairs=0,
            logger=logger,
        )
    logger.close()

    audit = error.value.audit
    assert audit["schema_version"] == "research_plan_author_section_contract_diagnostics_v1"
    assert audit["mode"] == "complete_all_sections_before_abort"
    assert audit["section_count"] == 15
    assert audit["attempted_section_count"] == 15
    assert audit["failed_section_count"] == 2
    assert [failure["section_id"] for failure in audit["failures"]] == ["abstract", "idea_origin_and_selection"]
    assert set(attempted_sections) == {
        route["section_id"] for route in route_author_sections(_author_input("26"))["routes"]
    }
    failed_section_records = [
        json.loads(line)
        for line in log_path.read_text(encoding="utf-8").splitlines()
        if json.loads(line)["stage"] == "section_composition" and json.loads(line)["event"] == "failed"
    ]
    assert [record["level"] for record in failed_section_records] == ["WARNING", "WARNING"]
    assert [record["section_id"] for record in failed_section_records] == ["abstract", "idea_origin_and_selection"]


def test_section_composition_continues_after_an_early_failure(monkeypatch, tmp_path: Path) -> None:
    path = _write_input(tmp_path, _author_input("26"))
    import src.agents.research_plan_author.run as author_run

    monkeypatch.setattr(author_run, "load_verified_survey_sources", lambda _path: _survey_sources(tmp_path))
    attempted_sections: list[str] = []

    def invalid_abstract_llm(prompt: str, *, response_format: object) -> dict:
        response = _fake_author_llm(prompt, response_format=response_format)
        payload = json.loads(prompt.rsplit("INPUT_JSON:\n", 1)[1])
        if payload.get("operation") == "research_plan_section_composition":
            section_id = payload["route"]["section_id"]
            attempted_sections.append(section_id)
            if section_id == "abstract":
                response["claim_provenance"][0]["qualification"] = "unsupported_qualification"
        return response

    with pytest.raises(AuthorCompositionError):
        run_research_plan_author(
            path,
            survey_manifest_path=tmp_path / "survey_manifest.json",
            include_idea_evolution="off",
            llm_call=invalid_abstract_llm,
            max_contract_repairs=0,
        )

    assert len(attempted_sections) == 15
    assert set(attempted_sections) == {
        route["section_id"] for route in route_author_sections(_author_input("26"))["routes"]
    }


def test_section_composition_defaults_to_five_concurrent_workers(monkeypatch, tmp_path: Path) -> None:
    path = _write_input(tmp_path, _author_input("26"))
    import src.agents.research_plan_author.run as author_run

    monkeypatch.setattr(author_run, "load_verified_survey_sources", lambda _path: _survey_sources(tmp_path))
    active_calls = 0
    peak_calls = 0
    call_lock = Lock()

    def parallel_llm(prompt: str, *, response_format: object) -> dict:
        nonlocal active_calls, peak_calls
        payload = json.loads(prompt.rsplit("INPUT_JSON:\n", 1)[1])
        if payload.get("operation") != "research_plan_section_composition":
            return _fake_author_llm(prompt, response_format=response_format)
        with call_lock:
            active_calls += 1
            peak_calls = max(peak_calls, active_calls)
        try:
            sleep(0.02)
            return _fake_author_llm(prompt, response_format=response_format)
        finally:
            with call_lock:
                active_calls -= 1

    result = run_research_plan_author(
        path,
        survey_manifest_path=tmp_path / "survey_manifest.json",
        include_idea_evolution="off",
        llm_call=parallel_llm,
        max_contract_repairs=0,
    )

    assert peak_calls == 5
    assert result["status"] == "COMPOSED_FOR_RENDERING"


def test_concurrent_sections_receive_independent_generic_repairs(monkeypatch, tmp_path: Path) -> None:
    path = _write_input(tmp_path, _author_input("26"))
    import src.agents.research_plan_author.run as author_run

    monkeypatch.setattr(author_run, "load_verified_survey_sources", lambda _path: _survey_sources(tmp_path))
    repair_calls = 0
    repair_lock = Lock()

    def invalid_sections_llm(prompt: str, *, response_format: object) -> dict:
        nonlocal repair_calls
        if "constrained JSON contract repair" in prompt:
            with repair_lock:
                repair_calls += 1
            request = json.loads(prompt.rsplit("INPUT_JSON:\n", 1)[1])
            candidate = deepcopy(request["initial_candidate"])
            candidate["schema_version"] = "research_plan_section_v1"
            return candidate
        response = _fake_author_llm(prompt, response_format=response_format)
        payload = json.loads(prompt.rsplit("INPUT_JSON:\n", 1)[1])
        if payload.get("operation") == "research_plan_section_composition":
            response.pop("schema_version")
        return response

    result = run_research_plan_author(
        path,
        survey_manifest_path=tmp_path / "survey_manifest.json",
        include_idea_evolution="off",
        llm_call=invalid_sections_llm,
        max_contract_repairs=1,
    )

    assert repair_calls == 15
    assert result["status"] == "COMPOSED_FOR_RENDERING"


def test_author_reuses_validated_sections_after_a_partial_run(monkeypatch, tmp_path: Path) -> None:
    path = _write_input(tmp_path, _author_input("26"))
    import src.agents.research_plan_author.run as author_run

    monkeypatch.setattr(author_run, "load_verified_survey_sources", lambda _path: _survey_sources(tmp_path))
    composition_calls = 0
    fail_abstract = True

    def cached_llm(prompt: str, *, response_format: object) -> dict:
        nonlocal composition_calls
        payload = json.loads(prompt.rsplit("INPUT_JSON:\n", 1)[1])
        if payload.get("operation") == "research_plan_section_composition":
            composition_calls += 1
        response = _fake_author_llm(prompt, response_format=response_format)
        if (
            fail_abstract
            and payload.get("operation") == "research_plan_section_composition"
            and payload["route"]["section_id"] == "abstract"
        ):
            response["claim_provenance"][0]["qualification"] = "unsupported_qualification"
        return response

    with pytest.raises(AuthorCompositionError) as error:
        run_research_plan_author(
            path,
            survey_manifest_path=tmp_path / "survey_manifest.json",
            include_idea_evolution="off",
            llm_call=cached_llm,
            max_contract_repairs=0,
            section_cache_config={"root": tmp_path / "section-cache"},
        )
    assert composition_calls == 15
    assert error.value.audit["section_cache"]["writes"] == 14

    fail_abstract = False
    second = run_research_plan_author(
        path,
        survey_manifest_path=tmp_path / "survey_manifest.json",
        include_idea_evolution="off",
        llm_call=cached_llm,
        max_contract_repairs=0,
        section_cache_config={"root": tmp_path / "section-cache"},
    )

    assert composition_calls == 16
    assert second["section_cache"]["hits"] == 14
    assert second["section_cache"]["writes"] == 1


def _fake_author_llm(prompt: str, *, response_format: object) -> dict:
    assert response_format == {"type": "json_object"}
    payload = json.loads(prompt.rsplit("INPUT_JSON:\n", 1)[1])
    operation = payload.get("operation")
    if operation == "research_plan_authoring_blueprint_section_assignment":
        fixed_section = payload["fixed_section"]
        section_id = fixed_section["section_id"]
        response = {
            "schema_version": AUTHORING_BLUEPRINT_SECTION_ASSIGNMENT_SCHEMA_VERSION,
            "section_id": section_id,
        }
        properties = payload["output_contract"]["properties"]
        if "allowed_source_ids" in properties:
            response["allowed_source_ids"] = []
        if section_id == "abstract":
            response["document_title"] = "An English Proposal Title"
            response["keywords"] = ["proposal", "design"]
        return response
    if operation == "research_plan_cross_section_edit":
        return {
            "schema_version": "research_plan_author_cross_section_edit_v1",
            "edits": [],
        }
    assert operation == "research_plan_section_composition"
    route = payload["route"]
    blueprint_section = payload["blueprint_section"]
    claim_kind = "planned_contribution" if route["section_id"] == "abstract" else route["allowed_claim_kinds"][0]
    if payload.get("theory_artifact_quota"):
        section_id = route["section_id"]
        open_items = [
            {"source_item_id": item_id, "text": "Human input is required before this proposal can proceed.", "status": "needs_human_input"}
            for item_id in blueprint_section["required_open_item_ids"]
        ]
        review_items = [
            {"source_item_id": item_id, "text": "Qualified human review is required before this proposal can proceed.", "status": "review_required"}
            for item_id in blueprint_section["required_review_item_ids"]
        ]
        if section_id in {"formal_problem_and_hypotheses", "definitions_and_propositions"}:
            definition_id = f"definition-{section_id}"
            blocks = [
                {"block_id": "definition", "kind": "definition", "text": "The proposal defines a bounded formal domain.", "claim_ids": [definition_id]},
                {"block_id": "assumptions", "kind": "list", "text": "- Retain the declared domain.\n- Treat unresolved inputs as human review items.", "claim_ids": [definition_id]},
                {"block_id": "relation", "kind": "equation", "text": r"F = G", "claim_ids": [definition_id]},
                {"block_id": "obligation", "kind": "proposition", "text": "The proposed proof obligation fails outside the stated domain.", "claim_ids": [definition_id], "reference_block_ids": ["relation"]},
            ]
            claims = [
                {"claim_id": definition_id, "claim_kind": "formal_definition", "statement": "The proposal defines a bounded formal domain.", "qualification": "proposed", "source_ids": [], "evidence_card_ids": [], "survey_anchor_ids": [], "formal_reference_ids": [], "outcome_branch_ids": [], "citation_keys": []},
            ]
        elif section_id == "forward_derivation_and_counterexamples":
            derivation_id = "derivation-forward"
            blocks = [
                {"block_id": "setup", "kind": "definition", "text": "The proposal defines a bounded derivation setup.", "claim_ids": [derivation_id]},
                {"block_id": "assumptions", "kind": "list", "text": "- Retain the declared domain.\n- Escalate unresolved premises to review.", "claim_ids": [derivation_id]},
                {"block_id": "relation", "kind": "equation", "text": r"F = G", "claim_ids": [derivation_id]},
                {"block_id": "obligation", "kind": "proposition", "text": "The proposed derivation fails outside the stated domain.", "claim_ids": [derivation_id], "reference_block_ids": ["relation"]},
                {"block_id": "matrix", "kind": "table", "text": "Candidate case | Assumption check | Action\nAdmissible case | Retained | Continue obligation\nBoundary case | Fails domain | Record counterexample", "claim_ids": [derivation_id]},
            ]
            claims = [
                {"claim_id": derivation_id, "claim_kind": "forward_derivation", "statement": "The proposal defines a bounded derivation.", "qualification": "proposed", "source_ids": [], "evidence_card_ids": [], "survey_anchor_ids": [], "formal_reference_ids": [], "outcome_branch_ids": [], "citation_keys": []},
            ]
        elif section_id == "expected_outcomes":
            outcome_id = "outcome-expected"
            theory_spine = payload.get("section_argument_context", {}).get("theory_spine", {})
            decision_branches = theory_spine.get("decision_branches") or []
            theory_unit_ids = (
                [decision_branches[0]["branch_id"]]
                if decision_branches and isinstance(decision_branches[0], dict)
                else []
            )
            blocks = [{"block_id": "matrix", "kind": "table", "text": "Condition | Interpretation | Action\nSupportive branch | Conditional support | Continue plan\nNull branch | No conclusion | Revise design", "claim_ids": [outcome_id], "theory_unit_ids": theory_unit_ids}]
            claims = [{"claim_id": outcome_id, "claim_kind": "expected_outcome", "statement": "The proposal specifies conditional outcomes.", "qualification": "expected_not_observed", "source_ids": [], "evidence_card_ids": [], "survey_anchor_ids": [], "formal_reference_ids": [], "outcome_branch_ids": ["supports_mechanism"], "citation_keys": []}]
        else:
            risk_id = "risk-review"
            blocks = [{"block_id": "matrix", "kind": "table", "text": "Condition | Interpretation | Review action\nMissing premise | Scope remains limited | Request human confirmation\nBoundary failure | Do not escalate claim | Revise ledger", "claim_ids": [risk_id]}]
            claims = [{"claim_id": risk_id, "claim_kind": "limitation", "statement": "The proposal retains a bounded limitation.", "qualification": "unverified", "source_ids": [], "evidence_card_ids": [], "survey_anchor_ids": [], "formal_reference_ids": [], "outcome_branch_ids": [], "citation_keys": []}]
        return {
            "schema_version": "research_plan_section_v1",
            "language": "en",
            "section_id": section_id,
            "title": route["title"],
            "applicability": route["applicability"],
            "blocks": blocks,
            "claim_provenance": claims,
            "open_items": open_items,
            "review_items": review_items,
        }
    qualification = "proposed" if claim_kind in {"formal_definition", "formal_proposition", "proof_obligation", "forward_derivation", "counterexample_plan"} else "design_assumption"
    statement = f"This proposal specifies the bounded role of {route['title']}."
    outcome_branch_ids: list[str] = []
    if claim_kind == "expected_outcome":
        qualification = "expected_not_observed"
        outcome_branch_ids = ["supports_mechanism"]
        statement = "If the prespecified branch condition is met, the proposal permits a conditional conclusion."
    claim_id = f"claim-{route['section_id']}"
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


def test_author_composition_does_not_call_the_legacy_cross_section_editor(monkeypatch, tmp_path: Path) -> None:
    path = _write_input(tmp_path, _author_input("26"))
    import src.agents.research_plan_author.run as author_run

    monkeypatch.setattr(author_run, "load_verified_survey_sources", lambda _path: _survey_sources(tmp_path))
    operations: list[str] = []

    def author_llm_without_legacy_editor(prompt: str, *, response_format: object) -> dict:
        payload = json.loads(prompt.rsplit("INPUT_JSON:\n", 1)[1])
        operations.append(str(payload.get("operation") or ""))
        return _fake_author_llm(prompt, response_format=response_format)

    result = run_research_plan_author(
        path,
        survey_manifest_path=tmp_path / "survey_manifest.json",
        include_idea_evolution="off",
        llm_call=author_llm_without_legacy_editor,
        document_quality_config={"enabled": False},
    )

    assert result["status"] == "COMPOSED_FOR_RENDERING"
    assert "research_plan_cross_section_edit" not in operations


def test_author_appends_verified_quantitative_evidence_after_llm_composition(monkeypatch, tmp_path: Path) -> None:
    path = _write_input(tmp_path, _author_input("26"))
    import src.agents.research_plan_author.run as author_run

    monkeypatch.setattr(author_run, "load_verified_survey_sources", lambda _path: _survey_sources(tmp_path))
    author_dir = tmp_path / "quantitative" / "author"
    publication_dir = tmp_path / "quantitative" / "publication"
    author_dir.mkdir(parents=True)
    publication_dir.mkdir(parents=True)
    pdf_path = publication_dir / "quantitative_mathematical_models.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\nquantitative test artifact\n")
    handoff_path = author_dir / "quantitative_author_handoff.json"
    handoff = {
        "schema_version": "quantitative_author_handoff_v1",
        "source_identity": {
            "science_run_id": "science-run",
            "survey_run_id": "survey-run",
            "project_id": "project",
            "project_context_fingerprint": "fingerprint",
            "selected_direction_id": "selected-direction",
        },
        "evidence": [
            {
                "quantitative_idea_id": "Q1",
                "final_version": 1,
                "question": "Does the bounded state decay under the specified rate?",
                "model_family": "ODE_IVP",
                "execution_mode": "NUMERICAL_SIMULATION",
                "result_kind": "SIMULATED",
                "empirical_claim_status": "NOT_EMPIRICAL",
                "result_quality": "QUALIFIED",
                "hypothesis_relation": "REFUTED_WITHIN_MODEL",
                "result_summary": "The model-internal trajectory decays under the stated assumptions.",
                "applicability_conditions": ["The specified rate remains constant."],
                "limitations": ["The result is not an empirical observation."],
                "lineage_summary": [
                    {"version": 0, "relation": "CONSTRAINED", "reason": "The initial regime is bounded."},
                    {"version": 1, "relation": "REFUTED_WITHIN_MODEL", "reason": "The revised regime decays."},
                ],
                "supplement_pdf_reference": "quantitative_mathematical_models.pdf#Q1",
            }
        ],
    }
    handoff_path.write_text(json.dumps(handoff), encoding="utf-8")
    manifest_path = author_dir / "quantitative_author_handoff_manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": "quantitative_author_handoff_manifest_v1",
                "status": "COMPLETED",
                "source_identity": handoff["source_identity"],
                "inputs": {"finalizations": {"Q1": {}}},
                "artifacts": {
                    "handoff": {
                        "path": str(handoff_path),
                        "sha256": hashlib.sha256(handoff_path.read_bytes()).hexdigest(),
                    },
                    "quantitative_models_pdf": {
                        "path": str(pdf_path),
                        "sha256": hashlib.sha256(pdf_path.read_bytes()).hexdigest(),
                    },
                },
            }
        ),
        encoding="utf-8",
    )

    result = run_research_plan_author(
        path,
        survey_manifest_path=tmp_path / "survey_manifest.json",
        include_idea_evolution="off",
        quantitative_handoff_manifest_path=manifest_path,
        llm_call=_fake_author_llm,
        document_quality_config={"enabled": False},
    )

    evidence_section = result["document"]["sections"][-1]
    evidence_text = evidence_section["blocks"][0]["text"]
    assert evidence_section["title"] == "Computational Evidence (Numerical Simulation; Non-empirical)"
    assert evidence_section["blocks"][0]["kind"] == "quantitative_evidence"
    assert "NUMERICAL_SIMULATION" in evidence_text
    assert "SIMULATED" in evidence_text
    assert "NOT_EMPIRICAL" in evidence_text
    assert "REFUTED_WITHIN_MODEL" in evidence_text
    assert "Acknowledg" not in json.dumps(result["document"])


def test_author_reports_ambiguous_equation_reference_as_a_warning(monkeypatch, tmp_path: Path) -> None:
    path = _write_input(tmp_path, _author_input("26"))
    import src.agents.research_plan_author.run as author_run

    monkeypatch.setattr(author_run, "load_verified_survey_sources", lambda _path: _survey_sources(tmp_path))
    log_path = tmp_path / "author.jsonl"
    logger = AuthorRunLogger("cross-reference-warning", jsonl_path=log_path)

    class ComposerWithQualityWarning(SectionComposer):
        def compose(self, *args, **kwargs):
            section, audit = super().compose(*args, **kwargs)
            if kwargs["route"]["section_id"] != "definitions_and_propositions":
                return section, audit
            return section, {
                "schema_version": "research_plan_author_section_quality_audit_v1",
                "artifact_kind": "section_composer:definitions_and_propositions",
                "quality_warning_status": "WARNING",
                "quality_warnings": ["ambiguous equation cross-reference"],
                "normalization_actions": [],
            }

    monkeypatch.setattr(author_run, "SectionComposer", ComposerWithQualityWarning)

    try:
        result = run_research_plan_author(
            path,
            survey_manifest_path=tmp_path / "survey_manifest.json",
            include_idea_evolution="off",
            llm_call=_fake_author_llm,
            logger=logger,
        )
    finally:
        logger.close()

    quality_audits = [
        audit
        for audit in result["document"]["contract_repair_audit"]
        if audit.get("quality_warning_status") == "WARNING"
    ]
    records = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    warning_records = [
        record
        for record in records
        if record["stage"] == "section_composition" and record["event"] == "quality_warning"
    ]

    assert result["status"] == "COMPOSED_FOR_RENDERING"
    assert len(quality_audits) == 1
    assert quality_audits[0]["artifact_kind"] == "section_composer:definitions_and_propositions"
    assert len(warning_records) == 1
    assert warning_records[0]["level"] == "WARNING"
    assert warning_records[0]["status"] == "WARNING"
    assert warning_records[0]["section_id"] == "definitions_and_propositions"
    assert warning_records[0]["warning_count"] == 1


def test_composition_namespaces_duplicate_claim_ids_across_sections(monkeypatch, tmp_path: Path) -> None:
    path = _write_input(tmp_path, _author_input("26"))
    import src.agents.research_plan_author.run as author_run

    monkeypatch.setattr(author_run, "load_verified_survey_sources", lambda _path: _survey_sources(tmp_path))

    def duplicate_claim_ids_llm(prompt: str, *, response_format: object) -> dict:
        response = _fake_author_llm(prompt, response_format=response_format)
        payload = json.loads(prompt.rsplit("INPUT_JSON:\n", 1)[1])
        if payload.get("operation") != "research_plan_section_composition":
            return response
        for claim in response.get("claim_provenance") or []:
            claim["claim_id"] = "shared-claim"
        for block in response.get("blocks") or []:
            block["claim_ids"] = ["shared-claim" for _claim_id in block.get("claim_ids") or []]
        return response

    result = run_research_plan_author(
        path,
        survey_manifest_path=tmp_path / "survey_manifest.json",
        include_idea_evolution="off",
        llm_call=duplicate_claim_ids_llm,
    )

    document = result["document"]
    claim_ids = [claim["claim_id"] for claim in document["claim_provenance"]]
    assert len(claim_ids) == len(set(claim_ids))
    assert all(claim_id.endswith(":shared-claim") for claim_id in claim_ids)
    assert set(document["abstract"]["claim_ids"]) <= set(claim_ids)
    for section in [*document["sections"], *document["appendices"]]:
        for block in section["blocks"]:
            assert set(block["claim_ids"]) <= set(claim_ids)


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


def test_blueprint_routes_items_before_the_llm_and_assigns_final_residuals_locally() -> None:
    author_context = {
        "provenance": {"template_id": "mathematics_theory"},
        "selected_direction": {"title": "A bounded formal proposal"},
        "research_design": {},
        "hypothesis_mapping": [],
        "field_statuses": {},
        "authoring_constraints": {},
    }
    preparation = {
        "source_design_id": "routing-design",
        "source_bundle": {"author_context": author_context},
    }
    routing = route_author_sections(author_context)

    def source_item(source_item_id: str, field_path: str) -> dict:
        return {
            "source_item_id": source_item_id,
            "original_item": {
                "field_path": field_path,
                "status": "needs_human_input",
            },
        }

    registry = {
        "allowed_source_ids": ["source-variable"],
        "allowed_survey_anchor_ids": [],
        "evidence_cards_by_id": {
            "card-variable": {
                "source_id": "source-variable",
                "claim_slot": "study_design",
            }
        },
        "citation_registry": [{"source_id": "source-variable", "citation_key": "cite_variable"}],
        "unknown_items": [
            source_item("unknown-formal", "definitions.D1"),
            source_item("unknown-counterexample", "candidate_counterexamples.C1.assumption_checks.A1"),
            source_item("unknown-counterexample-root", "counterexample_analysis"),
            source_item("unknown-method", "measurement_and_calibration.measurement_plan"),
            source_item("unknown-question", "open_design_questions[1]"),
            source_item("unknown-variable", "variables.V1.operational_definition"),
            source_item("unknown-variable-root", "variable_claim_model"),
            source_item("unknown-fallback", "unroutable_contract_metadata"),
        ],
        "review_items": [
            {
                "source_item_id": "review-formal",
                "original_item": {
                    "field_path": "formal_reasoning_plan",
                    "status": "review_required",
                },
            }
        ],
    }
    called_sections: list[str] = []

    def greedy_assignment_llm(prompt: str, *, response_format: object) -> dict:
        assert response_format == {"type": "json_object"}
        request = json.loads(prompt.rsplit("INPUT_JSON:\n", 1)[1])
        assert request["operation"] == "research_plan_authoring_blueprint_section_assignment"
        section_id = request["fixed_section"]["section_id"]
        called_sections.append(section_id)
        properties = request["output_contract"]["properties"]
        assert "required_open_item_ids" not in properties
        assert "required_review_item_ids" not in properties
        response = {
            "schema_version": AUTHORING_BLUEPRINT_SECTION_ASSIGNMENT_SCHEMA_VERSION,
            "section_id": section_id,
        }
        if "allowed_source_ids" in properties:
            response["allowed_source_ids"] = []
        if section_id == "abstract":
            response["document_title"] = "A Bounded Formal Proposal"
            response["keywords"] = ["formal", "proposal"]
        return response

    blueprint = AuthoringBlueprintPlanner().plan(
        preparation,
        routing=routing,
        source_registry=registry,
        llm_call=greedy_assignment_llm,
    )
    sections = {section["section_id"]: section for section in blueprint["sections"]}

    assert "introduction" not in called_sections
    assert sections["introduction"]["required_open_item_ids"] == []
    assert sections["definitions_and_propositions"]["required_open_item_ids"] == ["unknown-formal"]
    assert sections["forward_derivation_and_counterexamples"]["required_open_item_ids"] == [
        "unknown-counterexample",
        "unknown-counterexample-root",
    ]
    assert sections["study_design_and_methods"]["required_open_item_ids"] == ["unknown-method"]
    assert sections["research_questions_and_contributions"]["required_open_item_ids"] == ["unknown-question"]
    assert sections["appendix_variables_and_definitions"]["required_open_item_ids"] == [
        "unknown-variable",
        "unknown-variable-root",
    ]
    assert called_sections == ["abstract"]
    assert sections["risk_limitations_and_review"]["required_review_item_ids"] == ["review-formal"]
    assert sections["appendix_evidence_and_review"]["required_open_item_ids"] == ["unknown-fallback"]
    assert sections["appendix_evidence_and_review"]["required_review_item_ids"] == []
    assert "appendix_evidence_and_review" not in called_sections


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
    assert all(record["local_item_assignment"] is True for record in started)
    assert all(record["local_item_assignment"] is True for record in validated)


def test_blueprint_source_catalog_is_local_and_never_needs_source_assignment_repair(monkeypatch, tmp_path: Path) -> None:
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
    registry["allowed_source_ids"] = ["source-1"]
    registry["evidence_cards_by_id"] = {
        "card-1": {"source_id": "source-1", "claim_slot": "research_object_measurability"}
    }
    registry["citation_registry"] = [{"source_id": "source-1", "citation_key": "cite_source_1"}]

    def missing_sources_llm(prompt: str, *, response_format: object) -> dict:
        response = _fake_author_llm(prompt, response_format=response_format)
        request = json.loads(prompt.rsplit("INPUT_JSON:\n", 1)[1])
        if (
            request.get("operation") == "research_plan_authoring_blueprint_section_assignment"
            and request["fixed_section"]["section_id"] == "introduction"
        ):
            response.pop("allowed_source_ids")
        return response

    log_path = tmp_path / "author.jsonl"
    logger = AuthorRunLogger("blueprint-repair-log-test", jsonl_path=log_path, console_stream=StringIO())
    try:
        blueprint = AuthoringBlueprintPlanner().plan(
            preparation,
            routing=routing,
            source_registry=registry,
            llm_call=missing_sources_llm,
            logger=logger,
        )
    finally:
        logger.close()
    records = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    assert blueprint["document_title"] == "An English Proposal Title"
    assert not any(record["event"] == "section_assignment_repair_required" for record in records)


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


def test_preparation_freezes_input_and_defers_source_title(monkeypatch, tmp_path: Path) -> None:
    author_input = _author_input()
    author_input["selected_direction"]["title"] = "中文来源标题"
    path = _write_input(tmp_path, author_input)
    import src.agents.research_plan_author.run as author_run

    monkeypatch.setattr(author_run, "load_verified_survey_sources", lambda _path: _survey_sources(tmp_path))
    result = run_author_preparation(path, survey_manifest_path=tmp_path / "survey_manifest.json", include_idea_evolution="off")

    assert result["source_bundle"]["author_context"] == author_input
    assert result["document"]["document_metadata"]["title"] == ""
    assert result["document"]["document_metadata"]["source_title"] == "中文来源标题"
    assert result["document"]["document_metadata"]["title_status"] == "requires_llm_composition"


def test_contract_repair_is_bounded_per_assignment_and_allows_a_prose_revision(monkeypatch, tmp_path: Path) -> None:
    path = _write_input(tmp_path, _author_input("26"))
    import src.agents.research_plan_author.run as author_run

    monkeypatch.setattr(author_run, "load_verified_survey_sources", lambda _path: _survey_sources(tmp_path))
    repair_calls = 0

    def repaired_llm(prompt: str, *, response_format: object) -> dict:
        nonlocal repair_calls
        if "constrained JSON contract repair" in prompt:
            repair_calls += 1
            payload = json.loads(prompt.rsplit("INPUT_JSON:\n", 1)[1])
            candidate = deepcopy(payload["initial_candidate"])
            candidate["schema_version"] = AUTHORING_BLUEPRINT_SECTION_ASSIGNMENT_SCHEMA_VERSION
            return candidate
        output = _fake_author_llm(prompt, response_format=response_format)
        request = json.loads(prompt.rsplit("INPUT_JSON:\n", 1)[1])
        if (
            request.get("operation") == "research_plan_authoring_blueprint_section_assignment"
            and request["fixed_section"]["section_id"] in {"abstract", "introduction"}
        ):
            output.pop("schema_version")
        return output

    preparation = run_author_preparation(
        path,
        survey_manifest_path=tmp_path / "survey_manifest.json",
        include_idea_evolution="off",
    )
    routing = route_author_sections(preparation["source_bundle"]["author_context"])
    registry = build_frozen_source_registry(preparation)
    registry["allowed_source_ids"] = ["source-background"]
    registry["evidence_cards_by_id"] = {
        "card-background": {"source_id": "source-background", "claim_slot": "background"}
    }
    registry["citation_registry"] = [{"source_id": "source-background", "citation_key": "cite_background"}]
    repaired, repair_audit = AuthoringBlueprintPlanner().plan_with_audit(
        preparation,
        routing=routing,
        source_registry=registry,
        llm_call=repaired_llm,
        allow_contract_repair=True,
    )
    assert repair_calls == 1
    assert repaired["document_title"] == "An English Proposal Title"
    assert repair_audit is not None
    assert repair_audit["repair_status"] == "REPAIRED"
    assert [record["artifact_kind"] for record in repair_audit["section_assignment_repairs"]] == [
        "authoring_blueprint_section_assignment:abstract",
    ]

    def revised_title_repair(prompt: str, *, response_format: object) -> dict:
        if "constrained JSON contract repair" in prompt:
            payload = json.loads(prompt.rsplit("INPUT_JSON:\n", 1)[1])
            candidate = deepcopy(payload["initial_candidate"])
            candidate["schema_version"] = AUTHORING_BLUEPRINT_SECTION_ASSIGNMENT_SCHEMA_VERSION
            candidate["document_title"] = "A Revised English Proposal Title"
            return candidate
        output = _fake_author_llm(prompt, response_format=response_format)
        request = json.loads(prompt.rsplit("INPUT_JSON:\n", 1)[1])
        if (
            request.get("operation") == "research_plan_authoring_blueprint_section_assignment"
            and request["fixed_section"]["section_id"] == "abstract"
        ):
            output.pop("schema_version")
        return output

    revised = run_research_plan_author(
        path,
        survey_manifest_path=tmp_path / "survey_manifest.json",
        include_idea_evolution="off",
        llm_call=revised_title_repair,
        max_contract_repairs=1,
    )
    assert revised["document"]["document_metadata"]["title"] == "A Revised English Proposal Title"


def test_author_rejects_multiple_generic_repairs_before_preparation(tmp_path: Path) -> None:
    with pytest.raises(AuthorRunError, match="must be 0 or 1"):
        run_research_plan_author(
            tmp_path / "unused-author-input.json",
            survey_manifest_path=tmp_path / "unused-survey-manifest.json",
            max_contract_repairs=2,
        )


def test_section_composer_repair_permits_missing_schema_version(monkeypatch, tmp_path: Path) -> None:
    path = _write_input(tmp_path, _author_input())
    import src.agents.research_plan_author.run as author_run

    monkeypatch.setattr(author_run, "load_verified_survey_sources", lambda _path: _survey_sources(tmp_path))
    preparation = run_author_preparation(
        path,
        survey_manifest_path=tmp_path / "survey_manifest.json",
        include_idea_evolution="off",
    )
    route = next(
        item
        for item in route_author_sections(preparation["source_bundle"]["author_context"])["routes"]
        if item["section_id"] == "abstract"
    )
    blueprint_section = {
        "section_id": "abstract",
        "allowed_source_ids": [],
        "required_open_item_ids": [],
        "required_review_item_ids": [],
    }
    source_registry = source_registry_for_blueprint_section(
        build_frozen_source_registry(preparation),
        route,
        blueprint_section,
    )

    def missing_version_llm(prompt: str, *, response_format: object) -> dict:
        if "constrained JSON contract repair" in prompt:
            request = json.loads(prompt.rsplit("INPUT_JSON:\n", 1)[1])
            candidate = deepcopy(request["initial_candidate"])
            candidate["schema_version"] = "research_plan_section_v1"
            return candidate
        candidate = _fake_author_llm(prompt, response_format=response_format)
        candidate.pop("schema_version")
        return candidate

    section, audit = SectionComposer().compose(
        preparation,
        blueprint={"global_constraints": {}},
        route=route,
        blueprint_section=blueprint_section,
        source_registry=source_registry,
        llm_call=missing_version_llm,
    )

    assert section["schema_version"] == "research_plan_section_v1"
    assert audit is not None
    assert audit["repair_status"] == "REPAIRED"


def test_section_validator_rejects_observed_method_claims_without_fulltext_gate(monkeypatch, tmp_path: Path) -> None:
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
    assert not any("requires fulltext" in error for error in errors)


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


def test_section_validator_allows_formal_contextual_evidence_without_lexical_safety_gate(monkeypatch, tmp_path: Path) -> None:
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
    assert errors == []


def test_section_validator_allows_unresolved_formal_definition() -> None:
    route = {
        "section_id": "formal_problem_and_hypotheses",
        "title": "Problem Definition, Assumptions, and Hypotheses",
        "applicability": "required",
        "allowed_claim_kinds": ["formal_definition"],
    }
    payload = {
        "schema_version": "research_plan_section_v1",
        "language": "en",
        "section_id": route["section_id"],
        "title": route["title"],
        "applicability": route["applicability"],
        "blocks": [
            {
                "block_id": "unresolved-assumption",
                "kind": "definition",
                "text": "The exact focusing condition requires human input.",
                "claim_ids": ["A2"],
            }
        ],
        "claim_provenance": [
            {
                "claim_id": "A2",
                "claim_kind": "formal_definition",
                "statement": "The exact focusing condition requires human input.",
                "qualification": "needs_human_input",
                "source_ids": [],
                "evidence_card_ids": [],
                "survey_anchor_ids": [],
                "formal_reference_ids": [],
                "outcome_branch_ids": [],
                "citation_keys": [],
            }
        ],
        "open_items": [],
        "review_items": [],
    }

    registry = {
        "allowed_source_ids": [],
        "allowed_survey_anchor_ids": [],
        "evidence_cards_by_id": {},
        "citation_registry": [],
    }

    assert validate_section_output(
        payload,
        route=route,
        blueprint_section={"required_open_item_ids": [], "required_review_item_ids": []},
        preparation={"source_bundle": {"author_context": {}}},
        source_registry=registry,
    ) == []

    block_assertion = deepcopy(payload)
    block_assertion["blocks"][0]["text"] = "The proof establishes the exact focusing condition."
    assert validate_section_output(
        block_assertion,
        route=route,
        blueprint_section={"required_open_item_ids": [], "required_review_item_ids": []},
        preparation={"source_bundle": {"author_context": {}}},
        source_registry=registry,
    ) == []

    claim_assertion = deepcopy(payload)
    claim_assertion["claim_provenance"][0]["statement"] = "The exact focusing condition has been verified."
    assert validate_section_output(
        claim_assertion,
        route=route,
        blueprint_section={"required_open_item_ids": [], "required_review_item_ids": []},
        preparation={"source_bundle": {"author_context": {}}},
        source_registry=registry,
    ) == []

    card_assertion = deepcopy(payload)
    card_assertion["claim_provenance"][0]["evidence_card_ids"] = ["E1"]
    assert validate_section_output(
        card_assertion,
        route=route,
        blueprint_section={"required_open_item_ids": [], "required_review_item_ids": []},
        preparation={"source_bundle": {"author_context": {}}},
        source_registry={**registry, "evidence_cards_by_id": {"E1": {"evidence_level": "fulltext"}}},
    ) == []


def test_section_validator_allows_unicode_reference_inventory_metadata() -> None:
    route = {
        "section_id": "references",
        "title": "References",
        "applicability": "required",
        "allowed_claim_kinds": ["citation_inventory"],
    }
    payload = {
        "schema_version": "research_plan_section_v1",
        "language": "en",
        "section_id": "references",
        "title": "参考文献",
        "applicability": "required",
        "blocks": [
            {
                "block_id": "ref_inventory",
                "kind": "list",
                "text": "张伟 and Иван Петров. 量子场中的能量条件. 物理学报.",
                "claim_ids": ["cite-1"],
            }
        ],
        "claim_provenance": [
            {
                "claim_id": "cite-1",
                "claim_kind": "citation_inventory",
                "statement": "The registered bibliography includes this supplied metadata record.",
                "qualification": "metadata_lead",
                "source_ids": ["W1"],
                "evidence_card_ids": [],
                "survey_anchor_ids": [],
                "formal_reference_ids": [],
                "outcome_branch_ids": [],
                "citation_keys": ["cite_w1"],
            }
        ],
        "open_items": [],
        "review_items": [],
    }
    registry = {
        "allowed_source_ids": ["W1"],
        "allowed_survey_anchor_ids": [],
        "evidence_cards_by_id": {},
        "citation_registry": [{"source_id": "W1", "citation_key": "cite_w1"}],
    }

    assert validate_section_output(
        payload,
        route=route,
        blueprint_section={"required_open_item_ids": [], "required_review_item_ids": []},
        preparation={"source_bundle": {"author_context": {}}},
        source_registry=registry,
    ) == []

    payload["blocks"][0]["block_id"] = "ordinary_reference_block"
    errors = validate_section_output(
        payload,
        route=route,
        blueprint_section={"required_open_item_ids": [], "required_review_item_ids": []},
        preparation={"source_bundle": {"author_context": {}}},
        source_registry=registry,
    )
    assert errors == []


def test_final_semantic_validation_allows_unresolved_formal_claims_and_proof_language(monkeypatch, tmp_path: Path) -> None:
    path = _write_input(tmp_path, _author_input("26"))
    import src.agents.research_plan_author.run as author_run

    monkeypatch.setattr(author_run, "load_verified_survey_sources", lambda _path: _survey_sources(tmp_path))
    result = run_research_plan_author(
        path,
        survey_manifest_path=tmp_path / "survey_manifest.json",
        include_idea_evolution="off",
        llm_call=_fake_author_llm,
    )
    routing = route_author_sections(result["source_bundle"]["author_context"])
    registry = build_frozen_source_registry(result)
    unresolved = deepcopy(result["document"])
    formal_claim = next(
        claim for claim in unresolved["claim_provenance"] if claim["claim_kind"] in {"formal_definition", "formal_proposition"}
    )
    formal_claim["qualification"] = "needs_human_input"

    errors = validate_composed_research_plan(
        unresolved,
        preparation=result,
        routing=routing,
        source_registry=registry,
    )

    assert not any("is upgraded beyond the upstream verification state" in error for error in errors)

    proof_block_document = deepcopy(unresolved)
    formal_claim_id = formal_claim["claim_id"]
    formal_block = next(
        block
        for section in [*proof_block_document["sections"], *proof_block_document["appendices"]]
        for block in section["blocks"]
        if formal_claim_id in block["claim_ids"]
    )
    formal_block["text"] = "The proof establishes the unresolved formal condition."
    errors = validate_composed_research_plan(
        proof_block_document,
        preparation=result,
        routing=routing,
        source_registry=registry,
    )

    assert errors == []


def test_final_semantic_validation_allows_unlinked_synthesis_claims(monkeypatch, tmp_path: Path) -> None:
    path = _write_input(tmp_path, _author_input("26"))
    import src.agents.research_plan_author.run as author_run

    monkeypatch.setattr(author_run, "load_verified_survey_sources", lambda _path: _survey_sources(tmp_path))
    result = run_research_plan_author(
        path,
        survey_manifest_path=tmp_path / "survey_manifest.json",
        include_idea_evolution="off",
        llm_call=_fake_author_llm,
    )
    routing = route_author_sections(result["source_bundle"]["author_context"])
    registry = build_frozen_source_registry(result)
    candidate = deepcopy(result["document"])
    claim = next(
        item
        for item in candidate["claim_provenance"]
        if item["claim_kind"] in {"background", "survey_evidence", "research_gap"}
    )
    claim["qualification"] = "evidence_backed"
    claim["source_ids"] = []
    claim["evidence_card_ids"] = []
    claim["survey_anchor_ids"] = []
    claim["citation_keys"] = []

    errors = validate_composed_research_plan(
        candidate,
        preparation=result,
        routing=routing,
        source_registry=registry,
    )

    assert errors == []


def test_author_quality_loop_selects_the_best_math_candidate_and_writes_markdown(monkeypatch, tmp_path: Path) -> None:
    path = _write_input(tmp_path, _author_input("26"))
    import src.agents.research_plan_author.run as author_run

    monkeypatch.setattr(author_run, "load_verified_survey_sources", lambda _path: _survey_sources(tmp_path))
    result = run_research_plan_author(
        path,
        survey_manifest_path=tmp_path / "survey_manifest.json",
        include_idea_evolution="off",
        llm_call=_fake_author_llm,
        document_quality_config={"enabled": False},
    )
    routing = route_author_sections(result["source_bundle"]["author_context"])
    registry = build_frozen_source_registry(result)
    target_section = result["document"]["sections"][0]
    target_block = target_section["blocks"][0]
    original_text = target_block["text"]
    improved_text = "Improved source-bounded scholarly exposition with a clearer conditional transition."

    def quality_judge(prompt: str, *, response_format: object) -> dict:
        payload = json.loads(prompt.rsplit("INPUT_JSON:\n", 1)[1])
        dimension = payload["dimension"]
        improved = improved_text in payload["manuscript_markdown"]
        return {
            "dimension": dimension,
            "score": 9 if improved else 7,
            "rationale": "The candidate presents a coherent, evidence-based basis for this score.",
            "evidence": [
                {
                    "section_id": target_section["section_id"],
                    "block_id": target_block["block_id"],
                    "excerpt": improved_text if improved else original_text,
                    "assessment": "The selected block provides a concrete basis for the assessment.",
                }
            ],
            "maximum_strength": {"present": False},
            "major_weaknesses": [],
            "polish_directions": [{"priority": 1, "direction": "Keep the strongest explanatory transition.", "expected_gain": "Preserves coherence."}],
        }

    def quality_reviser(prompt: str, *, response_format: object) -> dict:
        return {
            "schema_version": AUTHOR_DOCUMENT_REVISION_SCHEMA_VERSION,
            "revision_summary": "Improved the opening explanatory transition.",
            "block_edits": [
                {
                    "section_id": target_section["section_id"],
                    "block_id": target_block["block_id"],
                    "text": improved_text,
                    "supporting_claim_ids": list(target_block["claim_ids"]),
                }
            ],
        }

    optimized, audit = optimize_research_plan_document(
        result["document"],
        preparation=result,
        routing=routing,
        source_registry=registry,
        quality_config={"enabled": True, "max_iterations": 1, "special_score_weight": 0.25},
        judge_llm_call=quality_judge,
        revision_llm_call=quality_reviser,
    )

    assert audit["selected_candidate_index"] == 1
    assert audit["candidates"][1]["scorecard"]["special_score_weight"] == 0.25
    assert audit["special_dimensions"] == [
        {"dimension": "Theory Auditability", "weight": 0.35},
        {"dimension": "Boundary and Status Discipline", "weight": 0.25},
        {"dimension": "Falsifiability and Decision Completeness", "weight": 0.25},
        {"dimension": "Energy-Condition Defense", "weight": 0.15},
    ]
    assert audit["candidates"][1]["scorecard"]["special_dimension_weights"] == {
        "Theory Auditability": 0.35,
        "Boundary and Status Discipline": 0.25,
        "Falsifiability and Decision Completeness": 0.25,
        "Energy-Condition Defense": 0.15,
    }
    assert optimized["sections"][0]["blocks"][0]["text"] == improved_text
    markdown = render_research_plan_markdown(optimized)
    assert "# Appendices" in markdown
    assert "## References" in markdown
    assert "survey:" not in markdown

    result["document"] = optimized
    result["document_quality"] = audit
    paths = write_author_preparation_artifacts(result, tmp_path / "artifacts", timestamp="20260830-120000-000001")
    assert paths.document_markdown.is_file()
    assert paths.document_quality_json.is_file()
    assert len(paths.candidate_markdowns) == 2


def test_author_quality_zero_iterations_scores_without_calling_the_reviser(monkeypatch, tmp_path: Path) -> None:
    path = _write_input(tmp_path, _author_input("26"))
    import src.agents.research_plan_author.run as author_run

    monkeypatch.setattr(author_run, "load_verified_survey_sources", lambda _path: _survey_sources(tmp_path))
    result = run_research_plan_author(
        path,
        survey_manifest_path=tmp_path / "survey_manifest.json",
        include_idea_evolution="off",
        llm_call=_fake_author_llm,
        document_quality_config={"enabled": False},
    )
    routing = route_author_sections(result["source_bundle"]["author_context"])
    registry = build_frozen_source_registry(result)
    target_section = result["document"]["sections"][0]
    target_block = target_section["blocks"][0]
    revision_calls = 0

    def quality_judge(prompt: str, *, response_format: object) -> dict:
        payload = json.loads(prompt.rsplit("INPUT_JSON:\n", 1)[1])
        return {
            "dimension": payload["dimension"],
            "score": 7,
            "rationale": "The manuscript supplies a concrete basis for this score.",
            "evidence": [{
                "section_id": target_section["section_id"],
                "block_id": target_block["block_id"],
                "excerpt": target_block["text"],
                "assessment": "The block is a grounded location for the assessment.",
            }],
            "maximum_strength": {"present": False},
            "major_weaknesses": [],
            "polish_directions": [{"priority": 1, "direction": "Improve one transition.", "expected_gain": "Clearer flow."}],
        }

    def quality_reviser(prompt: str, *, response_format: object) -> dict:
        nonlocal revision_calls
        revision_calls += 1
        return {
            "schema_version": AUTHOR_DOCUMENT_REVISION_SCHEMA_VERSION,
            "revision_summary": "This response must not be used.",
            "block_edits": [],
        }

    optimized, audit = optimize_research_plan_document(
        result["document"],
        preparation=result,
        routing=routing,
        source_registry=registry,
        quality_config={"enabled": True, "max_iterations": 0, "special_score_weight": 0},
        judge_llm_call=quality_judge,
        revision_llm_call=quality_reviser,
    )

    assert revision_calls == 0
    assert audit["selected_candidate_index"] == 0
    assert audit["candidates"][0]["scorecard"]["special_score_weight"] == 0
    assert optimized == result["document"]


def test_author_quality_prefers_auditable_theory_closure_over_repeated_dependency_prose(monkeypatch, tmp_path: Path) -> None:
    path = _write_input(tmp_path, _author_input("26"))
    import src.agents.research_plan_author.run as author_run

    monkeypatch.setattr(author_run, "load_verified_survey_sources", lambda _path: _survey_sources(tmp_path))
    result = run_research_plan_author(
        path,
        survey_manifest_path=tmp_path / "survey_manifest.json",
        include_idea_evolution="off",
        llm_call=_fake_author_llm,
        document_quality_config={"enabled": False},
    )
    routing = route_author_sections(result["source_bundle"]["author_context"])
    registry = build_frozen_source_registry(result)
    target_section = result["document"]["sections"][0]
    target_block = target_section["blocks"][0]
    original_text = target_block["text"]
    closure_text = (
        "The candidate lemma is tied to a named proof obligation, a falsifier condition, "
        "and a pre-registered no-information response that leaves theorem status unchanged."
    )
    requested_dimensions: set[str] = set()
    requested_lock = Lock()
    special_baseline_scores = {
        "Theory Auditability": 4,
        "Boundary and Status Discipline": 5,
        "Falsifiability and Decision Completeness": 4,
        "Energy-Condition Defense": 5,
    }

    def quality_judge(prompt: str, *, response_format: object) -> dict:
        payload = json.loads(prompt.rsplit("INPUT_JSON:\n", 1)[1])
        dimension = payload["dimension"]
        improved = closure_text in payload["manuscript_markdown"]
        with requested_lock:
            requested_dimensions.add(dimension)
        score = 9 if improved and dimension in special_baseline_scores else special_baseline_scores.get(dimension, 8)
        return {
            "dimension": dimension,
            "score": score,
            "rationale": "The score follows from the manuscript's explicit reasoning and decision structure.",
            "evidence": [{
                "section_id": target_section["section_id"],
                "block_id": target_block["block_id"],
                "excerpt": closure_text if improved else original_text,
                "assessment": "The block makes the theory-state transition inspectable.",
            }],
            "maximum_strength": (
                {
                    "present": True,
                    "description": "The theory chain is auditable.",
                    "evidence_refs": [{"section_id": target_section["section_id"], "block_id": target_block["block_id"]}],
                }
                if improved
                else {"present": False}
            ),
            "major_weaknesses": [],
            "polish_directions": [{"priority": 1, "direction": "Keep the decision chain explicit.", "expected_gain": "Better auditability."}],
        }

    def theory_reviser(prompt: str, *, response_format: object) -> dict:
        return {
            "schema_version": AUTHOR_DOCUMENT_REVISION_SCHEMA_VERSION,
            "revision_summary": "Connected the proposed theory units to a decision response.",
            "block_edits": [{
                "section_id": target_section["section_id"],
                "block_id": target_block["block_id"],
                "text": closure_text,
                "supporting_claim_ids": list(target_block["claim_ids"]),
            }],
        }

    _optimized, audit = optimize_research_plan_document(
        result["document"],
        preparation=result,
        routing=routing,
        source_registry=registry,
        quality_config={"enabled": True, "max_iterations": 1, "special_score_weight": 0.25},
        judge_llm_call=quality_judge,
        revision_llm_call=theory_reviser,
    )

    baseline = audit["candidates"][0]["scorecard"]
    revised = audit["candidates"][1]["scorecard"]
    assert audit["selected_candidate_index"] == 1
    assert revised["selection_score"] > baseline["selection_score"]
    assert all(
        revised["special_dimension_scores"][dimension] > baseline["special_dimension_scores"][dimension]
        for dimension in special_baseline_scores
    )
    assert requested_dimensions >= set(special_baseline_scores)


def test_author_quality_runs_one_partial_score_recovery_and_requires_complete_revised_scorecard(monkeypatch, tmp_path: Path) -> None:
    path = _write_input(tmp_path, _author_input("26"))
    import src.agents.research_plan_author.run as author_run

    monkeypatch.setattr(author_run, "load_verified_survey_sources", lambda _path: _survey_sources(tmp_path))
    result = run_research_plan_author(
        path,
        survey_manifest_path=tmp_path / "survey_manifest.json",
        include_idea_evolution="off",
        llm_call=_fake_author_llm,
        document_quality_config={"enabled": False},
    )
    routing = route_author_sections(result["source_bundle"]["author_context"])
    registry = build_frozen_source_registry(result)
    target_section = result["document"]["sections"][0]
    target_block = target_section["blocks"][0]
    original_text = target_block["text"]
    recovery_text = "The candidate theorem now closes its no-information branch with a specific review action."
    revision_calls = 0

    def partial_judge(prompt: str, *, response_format: object) -> dict:
        payload = json.loads(prompt.rsplit("INPUT_JSON:\n", 1)[1])
        improved = recovery_text in payload["manuscript_markdown"]
        score = 8 if improved or payload["dimension"] != "Readability" else 11
        return {
            "dimension": payload["dimension"],
            "score": score,
            "rationale": "The report identifies a concrete location in the manuscript.",
            "evidence": [{
                "section_id": target_section["section_id"],
                "block_id": target_block["block_id"],
                "excerpt": recovery_text if improved else original_text,
                "assessment": "This excerpt supports the rating.",
            }],
            "maximum_strength": {"present": False},
            "major_weaknesses": [],
            "polish_directions": [{"priority": 1, "direction": "Clarify the theory response.", "expected_gain": "Complete scorecard."}],
        }

    def recovery_reviser(prompt: str, *, response_format: object) -> dict:
        nonlocal revision_calls
        revision_calls += 1
        return {
            "schema_version": AUTHOR_DOCUMENT_REVISION_SCHEMA_VERSION,
            "revision_summary": "Recovered the quality pass with one focused theory revision.",
            "block_edits": [{
                "section_id": target_section["section_id"],
                "block_id": target_block["block_id"],
                "text": recovery_text,
                "supporting_claim_ids": list(target_block["claim_ids"]),
            }],
        }

    optimized, audit = optimize_research_plan_document(
        result["document"],
        preparation=result,
        routing=routing,
        source_registry=registry,
        quality_config={"enabled": True, "max_iterations": 2, "judge_max_retries": 1},
        judge_llm_call=partial_judge,
        revision_llm_call=recovery_reviser,
    )

    assert revision_calls == 1
    assert [candidate["status"] for candidate in audit["candidates"]] == ["PARTIALLY_SCORED", "SCORED"]
    assert audit["candidates"][0]["partial_score_recovery_attempted"] is True
    assert audit["selected_candidate_index"] == 1
    assert optimized["sections"][0]["blocks"][0]["text"] == recovery_text


def test_author_quality_rejects_a_revision_without_existing_claim_support(monkeypatch, tmp_path: Path) -> None:
    path = _write_input(tmp_path, _author_input("26"))
    import src.agents.research_plan_author.run as author_run

    monkeypatch.setattr(author_run, "load_verified_survey_sources", lambda _path: _survey_sources(tmp_path))
    result = run_research_plan_author(
        path,
        survey_manifest_path=tmp_path / "survey_manifest.json",
        include_idea_evolution="off",
        llm_call=_fake_author_llm,
        document_quality_config={"enabled": False},
    )
    routing = route_author_sections(result["source_bundle"]["author_context"])
    registry = build_frozen_source_registry(result)
    target_section = result["document"]["sections"][0]
    target_block = target_section["blocks"][0]

    def quality_judge(prompt: str, *, response_format: object) -> dict:
        payload = json.loads(prompt.rsplit("INPUT_JSON:\n", 1)[1])
        return {
            "dimension": payload["dimension"],
            "score": 7,
            "rationale": "The manuscript supplies a concrete basis for this score.",
            "evidence": [{
                "section_id": target_section["section_id"],
                "block_id": target_block["block_id"],
                "excerpt": target_block["text"],
                "assessment": "The block is a grounded location for the assessment.",
            }],
            "maximum_strength": {"present": False},
            "major_weaknesses": [],
            "polish_directions": [{"priority": 1, "direction": "Improve one transition.", "expected_gain": "Clearer flow."}],
        }

    def unbound_reviser(prompt: str, *, response_format: object) -> dict:
        return {
            "schema_version": AUTHOR_DOCUMENT_REVISION_SCHEMA_VERSION,
            "revision_summary": "Adds a conclusion that no retained claim supports.",
            "block_edits": [{
                "section_id": target_section["section_id"],
                "block_id": target_block["block_id"],
                "text": "This unsupported conclusion must not enter the manuscript.",
            }],
        }

    optimized, audit = optimize_research_plan_document(
        result["document"],
        preparation=result,
        routing=routing,
        source_registry=registry,
        quality_config={"enabled": True, "max_iterations": 1},
        judge_llm_call=quality_judge,
        revision_llm_call=unbound_reviser,
    )

    assert optimized == result["document"]
    assert len(audit["candidates"]) == 1
    assert any("must identify existing block claim_ids" in warning for warning in audit["warnings"])


def test_author_quality_logs_each_invalid_judge_attempt_with_a_safe_diagnostic(monkeypatch, tmp_path: Path) -> None:
    path = _write_input(tmp_path, _author_input("26"))
    import src.agents.research_plan_author.run as author_run

    monkeypatch.setattr(author_run, "load_verified_survey_sources", lambda _path: _survey_sources(tmp_path))
    result = run_research_plan_author(
        path,
        survey_manifest_path=tmp_path / "survey_manifest.json",
        include_idea_evolution="off",
        llm_call=_fake_author_llm,
        document_quality_config={"enabled": False},
    )
    routing = route_author_sections(result["source_bundle"]["author_context"])
    registry = build_frozen_source_registry(result)
    target_section = result["document"]["sections"][0]
    target_block = target_section["blocks"][0]

    def judge_with_invalid_readability(prompt: str, *, response_format: object) -> dict:
        payload = json.loads(prompt.rsplit("INPUT_JSON:\n", 1)[1])
        score = 11 if payload["dimension"] == "Readability" else 7
        return {
            "dimension": payload["dimension"],
            "score": score,
            "rationale": "The manuscript supplies a concrete basis for this score.",
            "evidence": [{
                "section_id": target_section["section_id"],
                "block_id": target_block["block_id"],
                "excerpt": target_block["text"],
                "assessment": "The block is a grounded location for the assessment.",
            }],
            "maximum_strength": {"present": False},
            "major_weaknesses": [],
            "polish_directions": [{"priority": 1, "direction": "Improve one transition.", "expected_gain": "Clearer flow."}],
        }

    log_path = tmp_path / "quality-diagnostics.jsonl"
    logger = AuthorRunLogger("quality-diagnostics", jsonl_path=log_path, console_enabled=False)
    _optimized, audit = optimize_research_plan_document(
        result["document"],
        preparation=result,
        routing=routing,
        source_registry=registry,
        quality_config={"enabled": True, "max_iterations": 0, "judge_max_retries": 3, "score_concurrency": 1},
        judge_llm_call=judge_with_invalid_readability,
        revision_llm_call=None,
        logger=logger,
    )
    logger.close()

    candidate = audit["candidates"][0]
    attempts = [attempt for attempt in candidate["judge_attempts"] if attempt["dimension"] == "Readability"]
    assert candidate["status"] == "PARTIALLY_SCORED"
    assert candidate["failed_dimensions"] == ["Readability"]
    assert candidate["partial_scorecard"]["valid_dimension_count"] == 13
    assert candidate["partial_scorecard"]["requested_dimension_count"] == 14
    assert "Readability" not in candidate["partial_scorecard"]["available_dimension_scores"]
    assert audit["winning_candidate_index"] is None
    assert audit["selection_status"] == "PARTIAL_SCORECARD_RETAINED_AS_FALLBACK"
    assert len(attempts) == 3
    assert all(attempt["failure_category"] == "score_contract" for attempt in attempts)
    assert all(attempt["response_summary"]["score"] == 11 for attempt in attempts)
    assert all(attempt["validation_errors"] == ["response.score must be an integer from 1 through 10"] for attempt in attempts)

    records = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    attempt_records = [record for record in records if record["event"] == "dimension_score_attempt" and record["dimension"] == "Readability"]
    assert len(attempt_records) == 3
    assert all(record["failure_category"] == "score_contract" for record in attempt_records)
    candidate_record = next(record for record in records if record["event"] == "candidate_scored")
    assert candidate_record["failed_dimensions"] == ["Readability"]
    assert "Readability attempt 1: score_contract" in render_document_quality_report(audit)
    assert "this candidate cannot be selected" in render_document_quality_report(audit)


def test_author_quality_keeps_a_grounded_score_when_auxiliary_locations_are_imprecise(monkeypatch, tmp_path: Path) -> None:
    path = _write_input(tmp_path, _author_input("26"))
    import src.agents.research_plan_author.run as author_run

    monkeypatch.setattr(author_run, "load_verified_survey_sources", lambda _path: _survey_sources(tmp_path))
    result = run_research_plan_author(
        path,
        survey_manifest_path=tmp_path / "survey_manifest.json",
        include_idea_evolution="off",
        llm_call=_fake_author_llm,
        document_quality_config={"enabled": False},
    )
    routing = route_author_sections(result["source_bundle"]["author_context"])
    registry = build_frozen_source_registry(result)
    target_section = result["document"]["sections"][0]
    target_block = target_section["blocks"][0]

    def tolerant_judge(prompt: str, *, response_format: object) -> dict:
        payload = json.loads(prompt.rsplit("INPUT_JSON:\n", 1)[1])
        dimension = payload["dimension"]
        response = {
            "dimension": dimension,
            "score": 8,
            "rationale": "The manuscript provides a coherent basis for this dimension score.",
            "evidence": [{
                "section_id": target_section["section_id"],
                "block_id": target_block["block_id"],
                "excerpt": target_block["text"],
                "assessment": "This block supplies a traceable rationale for the score.",
            }],
            "maximum_strength": {"present": False},
            "major_weaknesses": [],
            "polish_directions": [{"priority": 1, "direction": "Strengthen one transition.", "expected_gain": "Clearer coherence."}],
        }
        if dimension == "Coherence":
            response["evidence"].extend([
                {
                    "section_id": target_section["section_id"],
                    "block_id": target_block["block_id"],
                    "excerpt": "A paraphrase that does not occur verbatim.",
                    "assessment": "This auxiliary location is intentionally imprecise.",
                },
                {
                    "section_id": "unknown-section",
                    "block_id": "unknown-block",
                    "excerpt": "Unknown location.",
                    "assessment": "This auxiliary location is intentionally unavailable.",
                },
            ])
            response["maximum_strength"] = {
                "present": True,
                "description": "The document retains a coherent proposal boundary.",
                "evidence_refs": [
                    {"section_id": target_section["section_id"], "block_id": target_block["block_id"]},
                    {"section_id": "unknown-section", "block_id": "unknown-block"},
                ],
            }
            response["major_weaknesses"] = [{
                "severity": "moderate",
                "description": "One cross-section transition remains terse.",
                "impact": "Readers may need to reconstruct the dependency.",
                "repair_direction": "Add one explicit transition sentence.",
                "evidence_refs": [{"section_id": "unknown-section", "block_id": "unknown-block"}],
            }]
        return response

    log_path = tmp_path / "quality-grounding-warnings.jsonl"
    logger = AuthorRunLogger("quality-grounding-warnings", jsonl_path=log_path, console_enabled=False)
    _optimized, audit = optimize_research_plan_document(
        result["document"],
        preparation=result,
        routing=routing,
        source_registry=registry,
        quality_config={"enabled": True, "max_iterations": 0, "judge_max_retries": 2, "score_concurrency": 1},
        judge_llm_call=tolerant_judge,
        revision_llm_call=None,
        logger=logger,
    )
    logger.close()

    candidate = audit["candidates"][0]
    coherence_attempts = [attempt for attempt in candidate["judge_attempts"] if attempt["dimension"] == "Coherence"]
    coherence_report = next(report for report in candidate["dimension_reports"] if report["dimension"] == "Coherence")
    assert candidate["status"] == "SCORED"
    assert len(coherence_attempts) == 1
    assert coherence_attempts[0]["status"] == "VALID"
    assert coherence_attempts[0]["warning_category"] == "grounding_warning"
    assert len(coherence_report["evidence"]) == 1
    assert len(coherence_report["grounding_warnings"]) == 4
    assert coherence_report["maximum_strength"]["evidence_refs"] == [
        {"section_id": target_section["section_id"], "block_id": target_block["block_id"]}
    ]
    assert coherence_report["major_weaknesses"][0]["location_status"] == "pending_review"

    records = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    coherence_record = next(
        record for record in records if record["event"] == "dimension_score_attempt" and record["dimension"] == "Coherence"
    )
    assert coherence_record["status"] == "VALID"
    assert len(coherence_record["grounding_warnings"]) == 4
    rendered_report = render_document_quality_report(audit)
    assert "**Grounding warning:** evidence[2].excerpt is not found" in rendered_report
    assert "**Location:** pending review" in rendered_report
