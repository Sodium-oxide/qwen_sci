"""Milestone tests for the seven cross-disciplinary design templates."""

from __future__ import annotations

from io import StringIO
import json

import pytest

from src.agents.experiment_design_agent import (
    EXCLUDED_DISCIPLINE_IDS,
    PERMITTED_DISCIPLINE_IDS,
    ExperimentDesignOrchestrator,
    STUDY_TYPE_TEMPLATE_COMPOSER_PROMPTS,
    StudyTypeTemplateComposer,
    TemplateRouter,
    build_study_type_template_composer_prompt,
    validate_experiment_design,
)
from src.agents.experiment_design_agent.contracts import RESEARCH_BRIEF_SCHEMA_VERSION
from src.agents.experiment_design_agent.run_logging import ExperimentDesignRunLogger
from src.agents.experiment_design_agent.study_type_composer import (
    _normalize_unqualified_evidence_statuses,
)


_EXPECTED_TEMPLATE_BY_FIELD = {
    "11": "earth_environment_agro",
    "13": "life_veterinary",
    "15": "materials_chemical",
    "16": "materials_chemical",
    "17": "computational_digital",
    "19": "earth_environment_agro",
    "21": "engineering_energy",
    "22": "engineering_energy",
    "23": "earth_environment_agro",
    "24": "life_veterinary",
    "25": "materials_chemical",
    "26": "mathematics_theory",
    "27": "clinical_health",
    "28": "life_veterinary",
    "29": "clinical_health",
    "30": "life_veterinary",
    "31": "engineering_energy",
    "34": "life_veterinary",
    "35": "clinical_health",
    "36": "clinical_health",
}


def _brief(discipline_id: str, *, topic: str = "A declared research relation.") -> dict:
    return {
        "schema_version": RESEARCH_BRIEF_SCHEMA_VERSION,
        "brief_id": f"brief-{discipline_id}",
        "topic": topic,
        "discipline_ids": [discipline_id],
        "selected_direction": {
            "id": f"direction-{discipline_id}",
            "title": topic,
            "central_hypothesis": "The declared intervention may change the declared observable within stated conditions.",
            "mechanism_or_relation": "The mechanism or relation still requires traceable design evidence.",
        },
        "research_object": {"description": "A declared scientific research object."},
        "intervention_or_transformation": "A declared intervention or transformation.",
        "discriminating_observations": ["A declared observable that can distinguish the claim from an alternative explanation."],
        "boundary_conditions": ["The declared scientific boundary."],
        "alternative_explanations": ["A declared alternative explanation."],
        "known_unknowns": ["Required study-specific parameters are unresolved."],
        "evidence_status": "PROPOSED",
        "source": {"idea_result_schema": "idea_result_v5", "direction_id": f"direction-{discipline_id}"},
        "reasoning_context": {
            "schema_version": "reasoning_context_v1",
            "selected_direction_id": f"direction-{discipline_id}",
            "assumptions": [],
            "claim_scope": topic,
            "falsifiers": [],
            "boundary_conditions": ["The declared scientific boundary."],
            "alternative_explanations": ["A declared alternative explanation."],
            "formal_symbols": [],
            "gap_records": [],
            "evidence_roles": [],
            "source_anchors": [],
            "upstream_source_paths": [],
            "source_priority": ["selected_direction"],
        },
    }


def _template_llm(prompt: str, **kwargs: object) -> dict:
    assert kwargs["response_format"] == {"type": "json_object"}
    if "Variable and Claim Extractor" in prompt:
        return {
            "schema_version": "variable_claim_model_v1",
            "status": "complete_or_requires_input",
            "claims": [],
            "variables": [],
            "unknown_items": [],
        }
    if "Formal Reasoning Planner" in prompt:
        return {
            "schema_version": "formal_reasoning_plan_v1",
            "applicability": "formal_theory",
            "assumptions": [],
            "definitions": [],
            "propositions": [{
                "proposition_id": "P1",
                "statement": "The declared proposition.",
                "premises": [],
                "conclusion": "The declared conclusion.",
                "scope": "declared scope",
                "symbol_references": [],
                "variable_references": [],
                "status": "candidate_formalization",
            }],
            "proof_obligations": [],
            "forward_derivation": {
                "steps": [],
                "target_proposition_id": "P1",
                "final_conclusion_step": "",
                "final_conclusion": "The declared conclusion.",
                "status": "unresolved",
            },
            "unknown_items": [],
            "status": "unverified",
        }
    if "Counterexample Analyzer" in prompt:
        return {
            "schema_version": "counterexample_analysis_v1",
            "applicability": "formal_theory",
            "target_claim_id": "P1",
            "negated_conclusion": "not (The declared conclusion.)",
            "search_domain": "declared scope",
            "candidate_counterexamples": [],
            "exhaustiveness": {"scope": "bounded", "is_exhaustive": False, "reason": "No exhaustive search was run."},
            "status": "no_candidate_found_in_declared_scope",
            "limitations": ["No proof of absence was performed."],
            "unknown_items": [],
        }
    return {"open_design_questions": ["Confirm unresolved template requirements."]}


def test_composer_has_exactly_the_requested_seven_prompt_variants() -> None:
    assert set(STUDY_TYPE_TEMPLATE_COMPOSER_PROMPTS) == {
        "computational_digital",
        "mathematics_theory",
        "materials_chemical",
        "engineering_energy",
        "earth_environment_agro",
        "life_veterinary",
        "clinical_health",
    }


@pytest.mark.parametrize(
    ("template_id", "required_terms"),
    (
        ("computational_digital", ("data partitioning", "baseline", "ablation", "robustness", "resource")),
        ("mathematics_theory", ("assumptions", "definitions", "proof", "counterexamples", "numerical verification")),
        ("materials_chemical", ("material system", "process variables", "design of experiments", "characterization", "repeats")),
        ("engineering_energy", ("system boundary", "operating conditions", "failure or stress", "constraints", "hil")),
        ("earth_environment_agro", ("spatial-temporal", "sampling frame", "seasonality", "spatial autocorrelation", "covariates")),
        ("life_veterinary", ("model system", "technical and biological", "positive and negative controls", "assays", "biosafety")),
        ("clinical_health", ("pico", "target population", "endpoints", "confounding", "data governance", "ethics")),
    ),
)
def test_each_prompt_has_its_required_domain_constraints(template_id: str, required_terms: tuple[str, ...]) -> None:
    prompt = STUDY_TYPE_TEMPLATE_COMPOSER_PROMPTS[template_id].casefold()

    assert all(term in prompt for term in required_terms)
    assert "observed_results set to []" in prompt
    assert "design_only" in prompt


@pytest.mark.parametrize("discipline_id", sorted(PERMITTED_DISCIPLINE_IDS, key=int))
def test_every_permitted_field_routes_to_one_of_the_seven_templates(discipline_id: str) -> None:
    routing = TemplateRouter().route(_brief(discipline_id))

    assert routing["status"] == "ROUTED"
    assert routing["primary_template"] == _EXPECTED_TEMPLATE_BY_FIELD[discipline_id]
    assert routing["primary_template"] in STUDY_TYPE_TEMPLATE_COMPOSER_PROMPTS


def test_physics_formal_signal_uses_the_mathematics_variant_without_an_eighth_template() -> None:
    routing = TemplateRouter().route(
        _brief("31", topic="A theorem and proof for a symbolic physical model."),
    )

    assert routing["primary_template"] == "mathematics_theory"
    assert routing["submode"] == "formal_theory"


@pytest.mark.parametrize("discipline_id", sorted(EXCLUDED_DISCIPLINE_IDS, key=int))
def test_every_excluded_field_is_rejected_before_template_composition(discipline_id: str) -> None:
    routing = TemplateRouter().route(_brief(discipline_id))

    assert routing["status"] == "NOT_ROUTED"
    with pytest.raises(ValueError, match="in-scope"):
        StudyTypeTemplateComposer().compose(_brief(discipline_id))


def test_theory_design_marks_sampling_and_power_not_applicable() -> None:
    design = ExperimentDesignOrchestrator(llm_call=_template_llm).compose_design(
        _brief("26", topic="A theorem with a proof obligation and counterexample boundary."),
    )

    sampling = design["sampling_and_eligibility"]
    assert all("status" not in item for item in sampling.values())
    assert design["field_statuses"]["sampling_and_eligibility.sample_size_or_power_basis"] == "not_applicable"
    assert validate_experiment_design(design) == []


def test_theory_llm_patch_cannot_override_locked_sampling_fields() -> None:
    design = StudyTypeTemplateComposer().compose(
        _brief("26", topic="A theorem with a proof obligation and counterexample boundary."),
        llm_call=lambda *_args, **_kwargs: {
            "sampling_and_eligibility": {
                "source": {"status": "needs_human_input", "reason": "do-not-use"},
                "eligibility_criteria": {"status": "needs_human_input", "reason": "do-not-use"},
                "sample_size_or_power_basis": {"status": "needs_human_input", "reason": "do-not-use"},
            },
            "field_statuses": {
                "sampling_and_eligibility.source": "needs_human_input",
                "sampling_and_eligibility.eligibility_criteria": "needs_human_input",
                "sampling_and_eligibility.sample_size_or_power_basis": "needs_human_input",
            },
        },
    )

    assert all("status" not in item for item in design["sampling_and_eligibility"].values())
    assert {
        design["field_statuses"][path]
        for path in (
            "sampling_and_eligibility.source",
            "sampling_and_eligibility.eligibility_criteria",
            "sampling_and_eligibility.sample_size_or_power_basis",
        )
    } == {"not_applicable"}
    assert validate_experiment_design(design) == []


def test_template_prompt_exposes_the_writable_schema_contract() -> None:
    routing = TemplateRouter().route(_brief("26"))
    prompt = build_study_type_template_composer_prompt(
        _brief("26"),
        routing,
        {"schema_version": "evidence_bundle_v1", "brief_id": "brief-26", "evidence_cards": [], "coverage": {"required_slots": [], "covered_slots": [], "uncovered_slots": []}},
    )

    assert "WRITABLE_PATCH_CONTRACT:" in prompt
    assert '"randomization"' in prompt
    assert "Never emit evidence_backed" in prompt
    assert "Do not output every section merely to cover this list." in prompt
    assert "Include the common ExperimentDesign v1 sections" not in prompt


def test_template_prompt_serializes_canonical_reasoning_context_once() -> None:
    brief = _brief("17")
    routing = TemplateRouter().route(brief)
    prompt = build_study_type_template_composer_prompt(brief, routing, {})
    payload = json.loads(prompt.rsplit("INPUT_JSON:\n", 1)[1])

    assert "reasoning_context" not in payload["research_brief"]
    assert payload["reasoning_context"] == brief["reasoning_context"]


def test_evidence_backed_status_is_derived_locally_from_the_ledger() -> None:
    baseline = {
        "field_statuses": {
            "analysis_plan": "needs_human_input",
            "sampling_and_eligibility.source": "not_applicable",
        },
    }
    routing = TemplateRouter().route(_brief("26"))

    locally_derived, downgraded, derived = _normalize_unqualified_evidence_statuses(
        baseline,
        baseline,
        {"field_evidence_ledger": [{"field_path": "analysis_plan", "status": "evidence_backed"}]},
        routing,
    )
    assert locally_derived["field_statuses"]["analysis_plan"] == "evidence_backed"
    assert locally_derived["field_statuses"]["sampling_and_eligibility.source"] == "not_applicable"
    assert downgraded == 0
    assert derived == 1

    unqualified_llm_status, downgraded, derived = _normalize_unqualified_evidence_statuses(
        {"field_statuses": {"analysis_plan": "evidence_backed"}},
        baseline,
        {"field_evidence_ledger": []},
        routing,
    )
    assert unqualified_llm_status["field_statuses"]["analysis_plan"] == "needs_human_input"
    assert downgraded == 1
    assert derived == 0


def test_template_composer_repairs_one_invalid_nested_contract_patch_without_logging_content() -> None:
    logger = ExperimentDesignRunLogger("template-contract-repair", console_stream=StringIO())
    invalid_content = "do-not-log-this-invalid-value"
    invalid_value = {"private": invalid_content}
    calls: list[str] = []

    def llm_call(prompt: str, **kwargs: object) -> dict:
        assert kwargs["response_format"] == {"type": "json_object"}
        calls.append(prompt)
        if "Contract Repairer" in prompt:
            return {
                "schema_version": "template_contract_repair_patch_v1",
                "operations": [{
                    "op": "replace",
                    "path": "/research_design/design_type",
                    "value": "A design type requiring human confirmation.",
                }],
            }
        return {"research_design": {"design_type": invalid_value}}

    design = StudyTypeTemplateComposer().compose(
        _brief("17"),
        llm_call=llm_call,
        logger=logger,
        brief_id="brief-17",
    )

    assert len(calls) == 2
    assert design["template_composition"]["llm_used"] is True
    assert validate_experiment_design(design) == []
    composer_events = [record for record in logger.records if record["stage"] == "template_composer"]
    initial_validation = next(record for record in composer_events if record["event"] == "candidate_design_validated")
    repair_validation = next(record for record in composer_events if record["event"] == "contract_repair_validated")
    assert initial_validation["validation_errors"] == ["$/research_design/design_type:type_mismatch"]
    assert repair_validation["status"] == "REPAIRED"
    assert repair_validation["validation_errors"] == []
    assert all(invalid_content not in str(record) for record in logger.records)


def test_template_composer_normalizes_logged_extra_properties_before_one_targeted_repair() -> None:
    logger = ExperimentDesignRunLogger("template-contract-normalization", console_stream=StringIO())
    calls = 0

    def status_note() -> dict:
        return {"status": "needs_human_input", "reason": "A responsible human must confirm this design field."}

    def llm_call(prompt: str, **kwargs: object) -> dict:
        nonlocal calls
        assert kwargs["response_format"] == {"type": "json_object"}
        calls += 1
        if "Contract Repairer" in prompt:
            return {
                "schema_version": "template_contract_repair_patch_v1",
                "operations": [
                    {
                        "op": "replace",
                        "path": "/analysis_plan/statistical_analysis",
                        "value": status_note(),
                    },
                    {
                        "op": "replace",
                        "path": "/comparison_and_robustness/ablation_sensitivity_robustness",
                        "value": [],
                    },
                    {
                        "op": "replace",
                        "path": "/hypothesis_mapping",
                        "value": [{
                            "hypothesis_id": "H1",
                            "claim": "The declared relation remains a design hypothesis.",
                            "observables": ["A declared discriminating observable."],
                            "decision_rule": "A human must confirm the decision rule.",
                        }],
                    },
                ],
            }
        return {
            "research_design": {
                "design_type": "Formal theory design.",
                "experimental_unit": "A declared proposition.",
                "time_structure": "Static proof review.",
                "status": "needs_human_input",
            },
            "hypothesis_mapping": {"claim": "invalid container"},
            "variables_and_operationalization": {
                "independent_variables": [],
                "dependent_variables": [],
                "control_variables": [],
                "confounders": [],
                "operational_definitions": [],
                "key_variables": [],
                "status": "needs_human_input",
            },
            "sampling_and_eligibility": {
                "sampling_source": status_note(),
                "sample_size_power_basis": status_note(),
                "status": "not_applicable",
            },
            "measurement_and_calibration": {
                "instruments": [],
                "measurement_plan": status_note(),
                "calibration": status_note(),
                "quality_control": status_note(),
                "measurement_metrics": [],
                "calibration_requirements": status_note(),
                "status": "needs_human_input",
            },
            "comparison_and_robustness": {
                "groups": [],
                "controls": [],
                "baselines": [],
                "comparisons": [],
                "ablation_sensitivity_robustness": "invalid container",
                "baseline_conditions": [],
                "comparison_groups": [],
                "counterexample_analysis": {},
                "status": "needs_human_input",
            },
            "analysis_plan": {
                "randomization": status_note(),
                "blinding": status_note(),
                "repetitions": status_note(),
                "batch_effects": status_note(),
                "missing_data": status_note(),
                "statistical_analysis": "invalid container",
                "proof_obligations": [],
                "numerical_verification_plan": status_note(),
                "status": "needs_human_input",
            },
            "data_governance_and_reproducibility": {
                "data_management": status_note(),
                "reproducibility": status_note(),
                "data_management_plan": status_note(),
                "reproducibility_plan": status_note(),
                "status": "needs_human_input",
            },
            "field_statuses": {"analysis_plan": "evidence_backed"},
        }

    design = StudyTypeTemplateComposer().compose(
        _brief("26"),
        llm_call=llm_call,
        logger=logger,
    )

    assert calls == 1
    assert validate_experiment_design(design) == []
    assert design["field_statuses"]["analysis_plan"] == "needs_human_input"
    events = [record for record in logger.records if record["stage"] == "template_composer"]
    normalization = next(record for record in events if record["event"] == "patch_contract_normalized")
    assert normalization["removed_extra_property_count"] >= 14
    assert normalization["downgraded_unqualified_evidence_status_count"] == 1
    initial_validation = next(record for record in events if record["event"] == "candidate_design_validated")
    assert normalization["restored_invalid_type_count"] == 3
    assert initial_validation["validation_errors"] == []
    assert all(record["event"] != "contract_repair_started" for record in events)


def test_template_composer_restores_a_malformed_container_without_authorizing_repair_rewrite() -> None:
    logger = ExperimentDesignRunLogger("template-container-type-restoration", console_stream=StringIO())
    calls = 0

    def llm_call(prompt: str, **kwargs: object) -> dict:
        nonlocal calls
        assert kwargs["response_format"] == {"type": "json_object"}
        calls += 1
        if "Contract Repairer" in prompt:
            pytest.fail("A malformed container must be restored locally, not sent for repair.")
        return {"research_design": "invalid container"}

    design = StudyTypeTemplateComposer().compose(
        _brief("17"),
        llm_call=llm_call,
        logger=logger,
    )

    assert calls == 1
    assert design["research_design"]["design_type"].startswith("Template-guided")
    assert validate_experiment_design(design) == []
    normalization = next(
        record
        for record in logger.records
        if record["stage"] == "template_composer"
        and record["event"] == "patch_contract_normalized"
    )
    assert normalization["restored_invalid_type_count"] == 1


def test_template_contract_repair_rejects_unrelated_scientific_field_changes() -> None:
    logger = ExperimentDesignRunLogger("template-contract-repair-scope", console_stream=StringIO())
    calls = 0
    secret_key = "do-not-log-this-repair-key"

    def llm_call(prompt: str, **kwargs: object) -> dict:
        nonlocal calls
        assert kwargs["response_format"] == {"type": "json_object"}
        calls += 1
        if "Contract Repairer" in prompt:
            return {
                "schema_version": "template_contract_repair_patch_v1",
                "operations": [{
                    "op": "replace",
                    "path": "/hypothesis_mapping",
                    "value": [{"claim": secret_key}],
                }],
            }
        return {"research_design": {"design_type": ["invalid-scalar-type"]}}

    with pytest.raises(ValueError, match="outside validation errors"):
        StudyTypeTemplateComposer().compose(
            _brief("17"),
            llm_call=llm_call,
            logger=logger,
            brief_id="brief-17",
        )

    assert calls == 2
    repair_event = next(
        record
        for record in logger.records
        if record["stage"] == "template_composer"
        and record["event"] == "contract_repair_validated"
    )
    assert repair_event["status"] == "REJECTED"
    assert repair_event["validation_errors"] == ["contract_repair_may_only_modify_invalid_path"]
    assert all(secret_key not in str(record) for record in logger.records)


def test_template_contract_repair_cannot_replace_array_for_an_element_error() -> None:
    logger = ExperimentDesignRunLogger("template-contract-repair-array-scope", console_stream=StringIO())
    calls = 0

    def llm_call(prompt: str, **kwargs: object) -> dict:
        nonlocal calls
        assert kwargs["response_format"] == {"type": "json_object"}
        calls += 1
        if "Contract Repairer" in prompt:
            return {
                "schema_version": "template_contract_repair_patch_v1",
                "operations": [{
                    "op": "replace",
                    "path": "/hypothesis_mapping",
                    "value": [],
                }],
            }
        return {"hypothesis_mapping": [{
            "hypothesis_id": 123,
            "claim": "A declared claim.",
            "observables": ["A declared observable."],
            "decision_rule": "A declared decision rule.",
        }]}

    with pytest.raises(ValueError, match="outside validation errors"):
        StudyTypeTemplateComposer().compose(
            _brief("17"),
            llm_call=llm_call,
            logger=logger,
            brief_id="brief-17",
        )

    assert calls == 2
    repair_event = next(
        record
        for record in logger.records
        if record["stage"] == "template_composer"
        and record["event"] == "contract_repair_validated"
    )
    assert repair_event["validation_errors"] == ["contract_repair_may_only_modify_invalid_path"]


def test_compose_internal_steps_emit_progress_events() -> None:
    logger = ExperimentDesignRunLogger("compose-progress-test", console_stream=StringIO())

    ExperimentDesignOrchestrator(llm_call=_template_llm).compose_design(
        _brief("25"),
        logger=logger,
    )

    events_by_stage = {
        stage: [record["event"] for record in logger.records if record["stage"] == stage]
        for stage in (
            "reasoning_context",
            "variable_claim_extraction",
            "formal_reasoning_planner",
            "counterexample_analyzer",
            "reasoning_validation",
            "template_composer",
            "compose_final_validation",
        )
    }
    assert events_by_stage["reasoning_context"] == ["completed"]
    assert events_by_stage["variable_claim_extraction"] == ["started", "completed"]
    assert events_by_stage["formal_reasoning_planner"] == ["completed"]
    assert events_by_stage["counterexample_analyzer"] == ["completed"]
    assert events_by_stage["reasoning_validation"] == ["started", "completed"]
    assert events_by_stage["template_composer"] == [
        "started",
        "llm_request_started",
        "llm_response_received",
        "llm_json_parsed",
        "patch_envelope_validated",
        "patch_contract_normalized",
        "candidate_design_validated",
        "completed",
    ]
    assert events_by_stage["compose_final_validation"] == [
        "started",
        "input_profiled",
        "contract_validated",
        "completed",
    ]

    theory_logger = ExperimentDesignRunLogger("theory-compose-progress-test", console_stream=StringIO())
    ExperimentDesignOrchestrator(llm_call=_template_llm).compose_design(
        _brief("26", topic="A theorem with a proof obligation."),
        logger=theory_logger,
    )

    assert [
        record["event"]
        for record in theory_logger.records
        if record["stage"] == "formal_reasoning_planner"
    ] == [
        "started",
        "llm_request_started",
        "llm_response_received",
        "llm_json_parsed",
        "initial_contract_validated",
        "completed",
    ]
    initial_contract_event = next(
        record
        for record in theory_logger.records
        if record["stage"] == "formal_reasoning_planner"
        and record["event"] == "initial_contract_validated"
    )
    assert initial_contract_event["validation_error_count"] == 0
    assert initial_contract_event["proposition_count"] == 1
    assert initial_contract_event["forward_step_count"] == 0
    assert all(
        key not in initial_contract_event
        for key in ("prompt", "raw_response", "response", "initial_candidate")
    )
    assert [
        record["event"]
        for record in theory_logger.records
        if record["stage"] == "counterexample_analyzer"
    ] == [
        "started",
        "llm_request_started",
        "llm_response_received",
        "llm_json_parsed",
        "contract_validated",
        "completed",
    ]
    counterexample_contract_event = next(
        record
        for record in theory_logger.records
        if record["stage"] == "counterexample_analyzer"
        and record["event"] == "contract_validated"
    )
    assert counterexample_contract_event["candidate_count"] == 0
    assert counterexample_contract_event["assumption_check_count"] == 0
    assert counterexample_contract_event["validation_error_count"] == 0
    assert all(
        key not in counterexample_contract_event
        for key in ("prompt", "raw_response", "response", "negated_conclusion", "search_domain")
    )
    assert [
        record["event"]
        for record in theory_logger.records
        if record["stage"] == "template_composer"
    ] == [
        "started",
        "llm_request_started",
        "llm_response_received",
        "llm_json_parsed",
        "patch_envelope_validated",
        "patch_contract_normalized",
        "candidate_design_validated",
        "completed",
    ]
    patch_event = next(
        record
        for record in theory_logger.records
        if record["stage"] == "template_composer"
        and record["event"] == "patch_envelope_validated"
    )
    assert patch_event["patch_sections"] == ["open_design_questions"]
    assert patch_event["validation_error_count"] == 0
    assert all(key not in patch_event for key in ("prompt", "raw_response", "response", "patch"))
    assert [
        record["event"]
        for record in theory_logger.records
        if record["stage"] == "compose_final_validation"
    ] == ["started", "input_profiled", "contract_validated", "completed"]
    final_validation_event = next(
        record
        for record in theory_logger.records
        if record["stage"] == "compose_final_validation"
        and record["event"] == "contract_validated"
    )
    assert final_validation_event["status"] == "VALID"
    assert final_validation_event["observed_results_count"] == 0
    assert final_validation_event["outcome_branch_count"] == 4
    assert all(key not in final_validation_event for key in ("design", "evidence_bundle", "formal_reasoning_plan"))


def test_template_composer_logs_invalid_patch_without_patch_content() -> None:
    logger = ExperimentDesignRunLogger("invalid-composer-patch", console_stream=StringIO())
    rejected_value = "do-not-log-this-patch-value"

    with pytest.raises(ValueError, match="unsupported patch sections"):
        StudyTypeTemplateComposer().compose(
            _brief("26"),
            llm_call=lambda *_args, **_kwargs: {"unrecognized_section": rejected_value},
            logger=logger,
            brief_id="brief-26",
        )

    events = [record for record in logger.records if record["stage"] == "template_composer"]
    assert [record["event"] for record in events] == [
        "llm_request_started",
        "llm_response_received",
        "llm_json_parsed",
        "patch_envelope_validated",
    ]
    patch_event = events[-1]
    assert patch_event["status"] == "INVALID"
    assert patch_event["validation_errors"] == ["unsupported_patch_sections"]
    assert all(rejected_value not in str(record) for record in events)


@pytest.mark.parametrize(
    ("discipline_id", "review_trigger"),
    (
        ("13", "LIFE_SCIENCE_OR_VETERINARY_REVIEW"),
        ("16", "CHEMISTRY_OR_CHEMICAL_ENGINEERING_SAFETY_REVIEW"),
        ("15", "CHEMISTRY_OR_CHEMICAL_ENGINEERING_SAFETY_REVIEW"),
        ("27", "CLINICAL_OR_HEALTH_EXPERT_REVIEW"),
    ),
)
def test_high_risk_template_families_end_in_human_review(
    discipline_id: str,
    review_trigger: str,
) -> None:
    design = ExperimentDesignOrchestrator(llm_call=_template_llm).compose_design(_brief(discipline_id))

    assert design["risk_and_human_review"]["human_review_required"] is True
    assert review_trigger in design["risk_and_human_review"]["review_triggers"]
    assert design["validation_report"]["status"] == "BLOCKED_BY_RISK_REVIEW"
    assert design["execution_policy"]["mode"] == "DESIGN_ONLY"
    assert design["execution_policy"]["allow_digital_execution"] is False


def test_design_has_the_complete_four_branch_expected_outcome_tree() -> None:
    brief = _brief("17")
    routing = TemplateRouter().route(brief)
    prompt = build_study_type_template_composer_prompt(brief, routing, {})
    design = StudyTypeTemplateComposer().compose(brief, template_routing=routing, llm_call=_template_llm)

    assert "CS/ML" in prompt
    assert [branch["branch_id"] for branch in design["outcome_branches"]] == [
        "supports_mechanism",
        "partial_or_heterogeneous",
        "null_or_contradictory",
        "uninformative_or_invalid",
    ]
    assert {branch["evidence_status"] for branch in design["outcome_branches"]} == {"EXPECTED_NOT_OBSERVED"}
    assert design["observed_results"] == []
    assert validate_experiment_design(design) == []


def test_low_risk_llm_patch_cannot_replace_design_only_invariants() -> None:
    submitted: dict[str, str] = {}

    def llm_call(prompt: str, **kwargs: object) -> dict:
        assert kwargs["response_format"] == {"type": "json_object"}
        submitted["prompt"] = prompt
        if "Variable and Claim Extractor" in prompt:
            return {
                "schema_version": "variable_claim_model_v1",
                "status": "complete_or_requires_input",
                "claims": [],
                "variables": [],
                "unknown_items": [],
            }
        return {
            "template_details": {
                "dataset_or_corpus": {
                    "status": "needs_human_input",
                    "reason": "The dataset or corpus remains to be confirmed by a responsible human.",
                }
            },
            "field_statuses": {"template_details.dataset_or_corpus": "needs_human_input"},
        }

    design = ExperimentDesignOrchestrator(llm_call=llm_call, composer_llm_call=llm_call).compose_design(_brief("17"))

    assert "Template: CS/ML" in submitted["prompt"]
    assert design["template_composition"]["llm_used"] is True
    assert design["execution_policy"]["mode"] == "DESIGN_ONLY"
    assert design["observed_results"] == []
    assert validate_experiment_design(design) == []
