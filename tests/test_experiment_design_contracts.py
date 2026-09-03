from __future__ import annotations

from pathlib import Path

from src.agents.experiment_design_agent.contracts import (
    EVIDENCE_BUNDLE_SCHEMA,
    EVIDENCE_BUNDLE_SCHEMA_VERSION,
    EXPERIMENT_DESIGN_SCHEMA,
    EXPERIMENT_DESIGN_SCHEMA_VERSION,
    OUTCOME_BRANCH_SCHEMA,
    OUTCOME_BRANCH_SCHEMA_VERSION,
    RESEARCH_BRIEF_SCHEMA,
    RESEARCH_BRIEF_SCHEMA_VERSION,
    build_research_brief_from_idea_result,
    validate_experiment_design,
    validate_research_brief,
)
from src.agents.experiment_design_agent.discipline_catalog import (
    DESIGN_ONLY,
    DIGITAL_EXECUTION_ELIGIBLE,
    EXCLUDED_DISCIPLINE_IDS,
    PERMITTED_DISCIPLINE_IDS,
    list_discipline_catalog,
    normalize_discipline_ids,
    resolve_design_scope,
    resolve_execution_policy,
)
from src.config import get_experiment_design_config, reload_config


def _brief() -> dict:
    return {
        "schema_version": RESEARCH_BRIEF_SCHEMA_VERSION,
        "brief_id": "brief-1",
        "topic": "Reliable scientific image analysis",
        "discipline_ids": ["17"],
        "selected_direction": {
            "id": "computational_route",
            "title": "Reliable scientific image analysis",
            "central_hypothesis": "The proposed representation improves robust image analysis.",
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


def _evidence_bundle() -> dict:
    return {
        "schema_version": EVIDENCE_BUNDLE_SCHEMA_VERSION,
        "brief_id": "brief-1",
        "evidence_cards": [],
        "coverage": {
            "required_slots": ["comparison", "measurement"],
            "covered_slots": [],
            "uncovered_slots": ["comparison", "measurement"],
        },
    }


def _outcome_branch(branch_id: str) -> dict:
    return {
        "schema_version": OUTCOME_BRANCH_SCHEMA_VERSION,
        "branch_id": branch_id,
        "trigger": "The preregistered decision rule for this branch is met.",
        "interpretation": "Interpret the result only within the declared design boundary.",
        "conclusion_scope": "The stated scientific image dataset family.",
        "improvement_actions": ["Update the next design iteration from this branch."],
        "evidence_status": "EXPECTED_NOT_OBSERVED",
    }


def _design(*, allow_digital_execution: bool = False) -> dict:
    policy = resolve_execution_policy(["17"], allow_digital_execution=allow_digital_execution)
    design = {
        "schema_version": EXPERIMENT_DESIGN_SCHEMA_VERSION,
        "design_id": "design-1",
        "evidence_status": "DESIGNED_NOT_EXECUTED",
        "execution_policy": {
            "mode": policy["mode"],
            "allow_digital_execution": policy["allow_digital_execution"],
            "reason": policy["reason"],
        },
        "research_brief": _brief(),
        "evidence_bundle": _evidence_bundle(),
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
            _outcome_branch("supports_mechanism"),
            _outcome_branch("partial_or_heterogeneous"),
            _outcome_branch("null_or_contradictory"),
            _outcome_branch("uninformative_or_invalid"),
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


def test_internal_catalog_has_exactly_twenty_permitted_and_six_excluded_fields() -> None:
    assert len(PERMITTED_DISCIPLINE_IDS) == 20
    assert EXCLUDED_DISCIPLINE_IDS == {"12", "14", "18", "20", "32", "33"}
    assert len(list_discipline_catalog()) == 26
    assert len(list_discipline_catalog(include_excluded=False)) == 20


def test_scope_blocks_social_science_and_humanities_fields() -> None:
    scope = resolve_design_scope(["Computer Science", "Psychology"])

    assert scope["status"] == "BLOCKED_BY_SCOPE"
    assert scope["discipline_ids"] == ["17", "32"]
    assert scope["excluded_discipline_ids"] == ["32"]


def test_scope_accepts_shared_taxonomy_keys_from_science_runs() -> None:
    assert normalize_discipline_ids(["physics_astronomy"]) == ("31",)
    scope = resolve_design_scope(["physics_astronomy"])

    assert scope["status"] == "IN_SCOPE"
    assert scope["discipline_ids"] == ["31"]
    assert scope["unresolved_disciplines"] == []


def test_digital_execution_is_off_by_default_even_for_computer_science() -> None:
    default_policy = resolve_execution_policy(["17"])
    enabled_policy = resolve_execution_policy(["17"], allow_digital_execution=True)
    non_cs_policy = resolve_execution_policy(["25"], allow_digital_execution=True)

    assert default_policy["mode"] == DESIGN_ONLY
    assert default_policy["allow_digital_execution"] is False
    assert enabled_policy["mode"] == DIGITAL_EXECUTION_ELIGIBLE
    assert non_cs_policy["mode"] == DESIGN_ONLY


def test_default_config_disables_digital_execution() -> None:
    reload_config()

    assert get_experiment_design_config().execution.allow_digital_execution is False


def test_contract_versions_and_json_schemas_are_exported() -> None:
    assert RESEARCH_BRIEF_SCHEMA["properties"]["schema_version"]["const"] == RESEARCH_BRIEF_SCHEMA_VERSION
    assert EVIDENCE_BUNDLE_SCHEMA["properties"]["schema_version"]["const"] == EVIDENCE_BUNDLE_SCHEMA_VERSION
    assert OUTCOME_BRANCH_SCHEMA["properties"]["schema_version"]["const"] == OUTCOME_BRANCH_SCHEMA_VERSION
    assert EXPERIMENT_DESIGN_SCHEMA["properties"]["schema_version"]["const"] == EXPERIMENT_DESIGN_SCHEMA_VERSION


def test_research_brief_rejects_excluded_discipline() -> None:
    brief = _brief()
    brief["discipline_ids"] = ["32"]

    assert "excluded_discipline:32" in validate_research_brief(brief)


def test_complete_design_contract_is_valid_and_cannot_contain_observed_results() -> None:
    design = _design()

    assert validate_experiment_design(design) == []
    design["observed_results"] = [{"metric": "invented"}]

    assert any("observed_results" in error for error in validate_experiment_design(design))


def test_field_statuses_permit_descriptive_string_labels() -> None:
    design = _design()
    design["field_statuses"] = {
        "counterexample_analysis.validity": "candidate_found_unverified",
        "hypothesis_mapping.CE1.decision_rule": "requires_human_review",
    }
    assert validate_experiment_design(design) == []


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
                if key == "status":
                    statuses.setdefault(path, child)
                else:
                    output[key] = visit(child, f"{path}.{key}" if path else key)
            return output
        if isinstance(value, list):
            return [visit(child, f"{path}[{index}]") for index, child in enumerate(value)]
        return value

    for section in sections:
        if section in design:
            design[section] = visit(design[section], section)
    design["field_statuses"] = statuses


def test_design_execution_mode_must_match_the_embedded_policy() -> None:
    design = _design()
    design["execution_policy"]["mode"] = DIGITAL_EXECUTION_ELIGIBLE

    assert "execution_policy_mode_does_not_match_discipline_scope" in validate_experiment_design(design)


def test_idea_result_adapter_requires_one_selected_direction() -> None:
    idea_result = {
        "schema_version": "idea_result_v5",
        "topic": "Material interface stability",
        "primary_direction": "materials_route",
        "survey_binding": {},
        "directions": [
            {
                "direction_mode": "materials_route",
                "title": "Material interface stability",
                "hypothesis": {
                    "central_hypothesis": "The interface changes stability.",
                    "mechanism_or_relation": "Interfacial transport changes stability.",
                    "scientific_object": {"object_type": "electrochemical interface"},
                    "intervention_or_transformation": "Change the process condition.",
                },
                "experiment_handoff": {
                    "required_observations": ["Measure the stability contrast."],
                    "boundary_conditions": ["The stated operating regime."],
                    "alternative_explanations": ["A competing transport route."],
                    "known_unknowns": ["The sample preparation remains open."],
                },
            }
        ],
    }

    brief = build_research_brief_from_idea_result(
        idea_result,
        discipline_ids=["Materials Science"],
        brief_id="brief-materials",
    )

    assert brief["source"]["direction_id"] == "materials_route"
    assert brief["discipline_ids"] == ["25"]
    assert validate_research_brief(brief) == []
