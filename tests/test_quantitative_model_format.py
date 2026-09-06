from __future__ import annotations

import json

import pytest

from src.agents.quantitative_modeling.model_synthesis import (
    QuantitativeModelSynthesisError,
    build_quantitative_model_prompt,
    parse_quantitative_model_response,
    synthesize_quantitative_model,
)
from src.agents.quantitative_modeling.publisher.json_markdown_consistency import (
    validate_json_markdown_consistency,
)
from src.agents.quantitative_modeling.publisher.tex_renderer import render_quantitative_models_tex
from src.agents.research_plan_author.quantitative_disclosure_validator import (
    validate_quantitative_disclosure,
)
from src.agents.research_plan_author.quantitative_evidence_adapter import (
    append_quantitative_evidence_section,
)


def _lineage() -> dict[str, object]:
    return {
        "science_run_id": "science-1",
        "survey_run_id": "survey-1",
        "project_id": "project-1",
        "project_context_fingerprint": "context-1",
        "selected_direction_id": "direction-1",
        "quantitative_idea_id": "Q1",
        "version": 0,
        "parent_version": None,
        "created_from_artifact": "quantitative_ideas_manifest.json",
    }


def _specification() -> dict[str, object]:
    return {
        "schema_version": "ieee_math_model_v1",
        "lineage": _lineage(),
        "title": "Exponential decay model",
        "abstract": "A bounded ODE model.",
        "scientific_question": "How does x change under a constant rate?",
        "model_scope": "A one-state local approximation.",
        "assumptions": [{"assumption_id": "A-001", "statement": "k is constant.", "effect_if_violated": "The rate law is misspecified."}],
        "symbols": [
            {"symbol_id": "S-001", "latex": "x", "meaning": "state", "unit": "1", "dimension": "1", "role": "STATE_VARIABLE"},
            {"symbol_id": "S-002", "latex": "k", "meaning": "rate", "unit": "s^{-1}", "dimension": "T^{-1}", "role": "PARAMETER"},
        ],
        "equations": [{"equation_id": "Q1-EQ-001", "role": "GOVERNING_EQUATION", "latex": "\\frac{dx}{dt}=-kx", "where_symbol_ids": ["S-001", "S-002"]}],
        "initial_conditions": ["x(0)=1"],
        "boundary_conditions": ["Initial-value boundary at t=0."],
        "parameterization": ["k is supplied as a bounded scenario parameter."],
        "scenarios": ["baseline"],
        "objective_and_constraints": ["Compute the bounded state trajectory."],
        "algorithm": {"input": ["k", "x0"], "output": ["x(t)"], "steps": ["Integrate the ODE."]},
        "numerical_plan": {"solver_family": "ODE_IVP", "discretization": "adaptive ODE integration", "convergence_checks": ["solver_converged"]},
        "validation_plan": ["Check solver convergence."],
        "limitations": ["No empirical validation is implied."],
        "references": [],
        "mathir": {
            "schema_version": "mathir_v1",
            "system_type": "ODE_IVP",
            "states": [{"id": "x", "initial": 1.0}],
            "parameters": {"k": 1.0},
            "derivatives": {"x": {"op": "mul", "args": [{"op": "neg", "args": [{"op": "variable", "name": "k"}]}, {"op": "variable", "name": "x"}]}},
            "time_span": [0.0, 1.0],
            "solver_options": {"max_step": 0.1},
        },
    }


def _monte_carlo_specification(
    *,
    empty_conditions: bool = False,
    symbolic_samples: bool = False,
    unsafe_identifier: bool = False,
) -> dict[str, object]:
    specification = _specification()
    specification["title"] = "Monte Carlo posterior sampler"
    specification["abstract"] = "A bounded zero-dimensional posterior sampler."
    specification["model_scope"] = "A prior-distribution sampling model for a scalar observable."
    specification["algorithm"] = {
        "input": ["prior distributions"],
        "output": ["sampled observable values"],
        "steps": ["Draw independent samples and evaluate the observable."],
    }
    specification["numerical_plan"] = {
        "solver_family": "MONTE_CARLO",
        "discretization": "independent prior sampling",
        "convergence_checks": ["Increase the sample count and compare summary statistics."],
    }
    variable_id = "τ_f" if unsafe_identifier else "tau_f"
    specification["mathir"] = {
        "schema_version": "mathir_v1",
        "system_type": "MONTE_CARLO",
        "parameters": {"offset": 0.5},
        "samples": "N_samples" if symbolic_samples else 128,
        "seed": 7,
        "random_variables": [
            {
                "id": variable_id,
                "distribution": "normal",
                "parameters": {"mean": 2.3, "stddev": 0.1},
            }
        ],
        "observable": {
            "op": "add",
            "args": [
                {"op": "variable", "name": variable_id},
                {"op": "variable", "name": "offset"},
            ],
        },
    }
    if empty_conditions:
        specification["initial_conditions"] = []
        specification["boundary_conditions"] = []
    else:
        specification["initial_conditions"] = [
            "Monte Carlo variables are initialized by sampling from the declared prior distributions."
        ]
        specification["boundary_conditions"] = [
            "No spatial boundary conditions apply to this zero-dimensional posterior sampler."
        ]
    return specification


def _optimization_specification() -> dict[str, object]:
    specification = _specification()
    specification["title"] = "Linear resource allocation"
    specification["abstract"] = "A bounded linear optimization model."
    specification["model_scope"] = "A two-variable allocation problem with finite bounds."
    specification["initial_conditions"] = []
    specification["boundary_conditions"] = []
    specification["scenarios"] = []
    specification["mathir"] = {
        "schema_version": "mathir_v1",
        "system_type": "LINEAR_OPTIMIZATION",
        "parameters": {"budget": 10.0},
        "variables": [
            {"id": "x", "lower": 0.0, "upper": 10.0, "objective_coefficient": 1.0},
            {"id": "y", "lower": 0.0, "upper": 10.0, "objective_coefficient": 2.0},
        ],
        "constraints": [],
        "objective_sense": "maximize",
    }
    return specification


def _markdown() -> str:
    return """Abstract— A bounded ODE model.

# Assumptions
A-001 holds.
# Symbols
S-001 is the state and S-002 is the rate.
# Equations
Q1-EQ-001: where S-001 is x and S-002 is k.
# Algorithm
Input: k, x0. Output: x(t). Steps: integrate the system.
# Parameters and Scenarios
Parameters include k; scenarios include baseline.
# Numerical Validation
Validation checks solver convergence.
# Limitations
No empirical claim is made.
# References
None.
"""


def test_dual_block_model_response_is_auditable_against_its_json_source() -> None:
    response = (
        "<QUANTITATIVE_MODEL_JSON>\n"
        + json.dumps(_specification())
        + "\n</QUANTITATIVE_MODEL_JSON>\n<QUANTITATIVE_MODEL_MARKDOWN>\n"
        + _markdown()
        + "</QUANTITATIVE_MODEL_MARKDOWN>"
    )

    specification, markdown = parse_quantitative_model_response(response)
    consistent = validate_json_markdown_consistency(specification, markdown)

    assert consistent["model_spec"]["equations"][0]["equation_id"] == "Q1-EQ-001"


def test_json_only_model_response_is_supported() -> None:
    response = (
        "<QUANTITATIVE_MODEL_JSON>\n"
        + json.dumps(_specification())
        + "\n</QUANTITATIVE_MODEL_JSON>"
    )

    specification, markdown = parse_quantitative_model_response(response)

    assert specification["title"] == "Exponential decay model"
    assert markdown == ""


def test_fenced_json_only_model_response_is_supported() -> None:
    response = "```json\n<QUANTITATIVE_MODEL_JSON>\n" + json.dumps(_specification()) + "\n</QUANTITATIVE_MODEL_JSON>\n```"

    specification, markdown = parse_quantitative_model_response(response)

    assert specification["title"] == "Exponential decay model"
    assert markdown == ""


def test_model_synthesis_renders_markdown_locally_from_json_only_response() -> None:
    response = (
        "<QUANTITATIVE_MODEL_JSON>\n"
        + json.dumps(_specification())
        + "\n</QUANTITATIVE_MODEL_JSON>"
    )

    result = synthesize_quantitative_model(
        quantitative_idea={"quantitative_idea_id": "Q1"},
        lineage=_lineage(),
        llm_call=lambda _prompt: response,
    )

    assert result["markdown"].startswith("Abstract—")
    assert "Q1-EQ-001" in result["markdown"]


def test_model_prompt_requires_symbol_objects_with_stable_ids() -> None:
    prompt = build_quantitative_model_prompt(
        quantitative_idea={"quantitative_idea_id": "Q1"},
        lineage=_lineage(),
    )

    assert "symbols is an array, never an object" in prompt
    assert "symbol_id, latex, meaning, unit, dimension, and role" in prompt
    assert "mathir.system_type is exactly one string" in prompt
    assert '"system_type":"ODE_IVP"' in prompt
    assert "at most 2000" in prompt
    assert "do not leave compared scenarios mathematically identical" in prompt


def test_model_prompt_documents_monte_carlo_integer_and_condition_contract() -> None:
    prompt = build_quantitative_model_prompt(
        quantitative_idea={"quantitative_idea_id": "Q2"},
        lineage={**_lineage(), "quantitative_idea_id": "Q2"},
    )

    assert 'mathir.system_type must be exactly "MONTE_CARLO"' in prompt
    assert "mathir.samples must be a JSON integer from 1 through 100000" in prompt
    assert "Every random_variables[].id and every AST variable.name must be an ASCII identifier" in prompt
    assert 'use names such as "tau_f"' in prompt
    assert "initial_conditions, boundary_conditions, and objective_and_constraints may be empty lists" in prompt
    assert "no spatial boundary conditions apply to the zero-dimensional sampler" in prompt


@pytest.mark.parametrize(
    ("model_form", "required_marker", "forbidden_marker"),
    [
        ("ODE", "Selected family: ODE", "Selected family: Monte Carlo"),
        ("OPTIMIZATION", "Selected family: linear optimization", "Selected family: ODE"),
        ("MONTE_CARLO", "Selected family: Monte Carlo sampling", "Selected family: registered PDE"),
        ("PDE", "Selected family: registered PDE execution", "Selected family: ODE"),
    ],
)
def test_model_prompt_selects_only_the_requested_model_family(
    model_form: str,
    required_marker: str,
    forbidden_marker: str,
) -> None:
    prompt = build_quantitative_model_prompt(
        quantitative_idea={"quantitative_idea_id": "Q1", "model_form": model_form},
        lineage=_lineage(),
    )

    assert required_marker in prompt
    assert forbidden_marker not in prompt


def test_model_prompt_uses_provisional_solver_family_for_family_routing() -> None:
    prompt = build_quantitative_model_prompt(
        quantitative_idea={
            "quantitative_idea_id": "Q1",
            "provisional_solver_family": "finite_difference_1d",
        },
        lineage=_lineage(),
    )

    assert "Selected family: registered PDE execution" in prompt
    assert "Selected family: ODE" not in prompt
    assert "Selected family: Monte Carlo sampling" not in prompt


def test_model_prompt_binds_external_execution_scenarios() -> None:
    prompt = build_quantitative_model_prompt(
        quantitative_idea={"quantitative_idea_id": "Q1"},
        lineage=_lineage(),
        execution_scenarios=[
            {"scenario_id": "isolated", "parameter_overrides": {"Mdot": 0.0}},
            {"scenario_id": "recycled", "parameter_overrides": {"Mdot": 1.0}},
        ],
    )

    assert '"scenario_id": "isolated"' in prompt
    assert '"Mdot": 1.0' in prompt
    assert "narrative-only scenario differences are forbidden" in prompt


def test_model_synthesis_repairs_one_invalid_contract_response() -> None:
    valid_response = (
        "<QUANTITATIVE_MODEL_JSON>\n"
        + json.dumps(_specification())
        + "\n</QUANTITATIVE_MODEL_JSON>\n<QUANTITATIVE_MODEL_MARKDOWN>\n"
        + _markdown()
        + "</QUANTITATIVE_MODEL_MARKDOWN>"
    )
    invalid_specification = _specification()
    invalid_specification["symbols"] = [{"latex": "x"}]
    invalid_response = (
        "<QUANTITATIVE_MODEL_JSON>\n"
        + json.dumps(invalid_specification)
        + "\n</QUANTITATIVE_MODEL_JSON>\n<QUANTITATIVE_MODEL_MARKDOWN>\n"
        + _markdown()
        + "</QUANTITATIVE_MODEL_MARKDOWN>"
    )
    responses = iter((invalid_response, valid_response))

    result = synthesize_quantitative_model(
        quantitative_idea={"quantitative_idea_id": "Q1"},
        lineage=_lineage(),
        llm_call=lambda _prompt: next(responses),
    )

    assert result["model_spec"]["symbols"][0]["symbol_id"] == "S-001"


def test_model_synthesis_repairs_monte_carlo_samples_and_empty_conditions() -> None:
    invalid_specification = _monte_carlo_specification(
        empty_conditions=True,
        symbolic_samples=True,
        unsafe_identifier=True,
    )
    invalid_response = (
        "<QUANTITATIVE_MODEL_JSON>\n"
        + json.dumps(invalid_specification)
        + "\n</QUANTITATIVE_MODEL_JSON>"
    )
    valid_response = (
        "<QUANTITATIVE_MODEL_JSON>\n"
        + json.dumps(_monte_carlo_specification())
        + "\n</QUANTITATIVE_MODEL_JSON>"
    )
    responses = iter((invalid_response, valid_response))
    prompts: list[str] = []

    def llm_call(prompt: str) -> str:
        prompts.append(prompt)
        return next(responses)

    result = synthesize_quantitative_model(
        quantitative_idea={"quantitative_idea_id": "Q1"},
        lineage=_lineage(),
        llm_call=llm_call,
    )

    assert result["model_spec"]["mathir"]["system_type"] == "MONTE_CARLO"
    assert result["model_spec"]["mathir"]["parameters"] == {"offset": 0.5}
    assert result["model_spec"]["mathir"]["samples"] == 128
    assert result["model_spec"]["initial_conditions"]
    assert result["model_spec"]["boundary_conditions"]
    assert len(prompts) == 2
    assert "preserve the selected executable model family" in prompts[1]


def test_monte_carlo_model_rejects_unsafe_random_variable_identifier() -> None:
    invalid_specification = _monte_carlo_specification(unsafe_identifier=True)
    response = "<QUANTITATIVE_MODEL_JSON>\n" + json.dumps(invalid_specification, ensure_ascii=False) + "\n</QUANTITATIVE_MODEL_JSON>"

    with pytest.raises(QuantitativeModelSynthesisError, match=r"random_variables\[0\]\.id must be a safe identifier"):
        parse_quantitative_model_response(response)


def test_monte_carlo_model_rejects_non_integer_sample_count() -> None:
    invalid_specification = _monte_carlo_specification()
    invalid_specification["mathir"]["samples"] = 128.5
    response = "<QUANTITATIVE_MODEL_JSON>\n" + json.dumps(invalid_specification) + "\n</QUANTITATIVE_MODEL_JSON>"

    with pytest.raises(QuantitativeModelSynthesisError, match="samples must be an integer"):
        parse_quantitative_model_response(response)


def test_monte_carlo_model_allows_empty_nonphysical_condition_sections() -> None:
    invalid_specification = _monte_carlo_specification(empty_conditions=True)
    response = "<QUANTITATIVE_MODEL_JSON>\n" + json.dumps(invalid_specification) + "\n</QUANTITATIVE_MODEL_JSON>"

    specification, _ = parse_quantitative_model_response(response)

    assert specification["initial_conditions"] == []
    assert specification["boundary_conditions"] == []


def test_model_format_applies_family_specific_outer_section_requirements() -> None:
    monte_carlo = _monte_carlo_specification(empty_conditions=True)
    monte_carlo["objective_and_constraints"] = []
    monte_carlo_response = "<QUANTITATIVE_MODEL_JSON>\n" + json.dumps(monte_carlo) + "\n</QUANTITATIVE_MODEL_JSON>"
    monte_carlo_specification, _ = parse_quantitative_model_response(monte_carlo_response)
    assert monte_carlo_specification["objective_and_constraints"] == []

    ode = _specification()
    ode["boundary_conditions"] = []
    ode_response = "<QUANTITATIVE_MODEL_JSON>\n" + json.dumps(ode) + "\n</QUANTITATIVE_MODEL_JSON>"
    ode_specification, _ = parse_quantitative_model_response(ode_response)
    assert ode_specification["boundary_conditions"] == []

    ode["initial_conditions"] = []
    invalid_ode_response = "<QUANTITATIVE_MODEL_JSON>\n" + json.dumps(ode) + "\n</QUANTITATIVE_MODEL_JSON>"
    with pytest.raises(QuantitativeModelSynthesisError, match="initial_conditions must not be empty"):
        parse_quantitative_model_response(invalid_ode_response)

    optimization = _optimization_specification()
    optimization_response = "<QUANTITATIVE_MODEL_JSON>\n" + json.dumps(optimization) + "\n</QUANTITATIVE_MODEL_JSON>"
    optimization_specification, _ = parse_quantitative_model_response(optimization_response)
    assert optimization_specification["initial_conditions"] == []
    assert optimization_specification["boundary_conditions"] == []
    assert optimization_specification["scenarios"] == []


def test_model_synthesis_normalizes_equivalent_abstract_heading() -> None:
    valid_response = (
        "<QUANTITATIVE_MODEL_JSON>\n"
        + json.dumps(_specification())
        + "\n</QUANTITATIVE_MODEL_JSON>\n<QUANTITATIVE_MODEL_MARKDOWN>\n"
        + _markdown()
        + "</QUANTITATIVE_MODEL_MARKDOWN>"
    )
    invalid_markdown_response = valid_response.replace("Abstract—", "# Abstract\n", 1)
    result = synthesize_quantitative_model(
        quantitative_idea={"quantitative_idea_id": "Q1"},
        lineage=_lineage(),
        llm_call=lambda _prompt: invalid_markdown_response,
    )

    assert result["markdown"].startswith("Abstract—")


def test_model_synthesis_renders_markdown_from_valid_json_when_profile_is_incomplete() -> None:
    incomplete_markdown = "# Model Draft\n\nThe JSON contains the complete model."
    response = (
        "<QUANTITATIVE_MODEL_JSON>\n"
        + json.dumps(_specification())
        + "\n</QUANTITATIVE_MODEL_JSON>\n<QUANTITATIVE_MODEL_MARKDOWN>\n"
        + incomplete_markdown
        + "\n</QUANTITATIVE_MODEL_MARKDOWN>"
    )

    result = synthesize_quantitative_model(
        quantitative_idea={"quantitative_idea_id": "Q1"},
        lineage=_lineage(),
        llm_call=lambda _prompt: response,
    )

    assert result["markdown"].startswith("Abstract—")
    assert "# Parameters and Scenarios" in result["markdown"]
    assert "Q1-EQ-001" in result["markdown"]
    assert "S-001" in result["markdown"]


def test_dual_block_response_rejects_unbound_lineage() -> None:
    response = (
        "<QUANTITATIVE_MODEL_JSON>\n"
        + json.dumps(_specification())
        + "\n</QUANTITATIVE_MODEL_JSON>\n<QUANTITATIVE_MODEL_MARKDOWN>\n"
        + _markdown()
        + "</QUANTITATIVE_MODEL_MARKDOWN>"
    )

    with pytest.raises(QuantitativeModelSynthesisError, match="lineage differs"):
        synthesize_quantitative_model(
            quantitative_idea={"quantitative_idea_id": "Q1"},
            lineage={**_lineage(), "science_run_id": "other-run"},
            llm_call=lambda _prompt: response,
        )


def test_separate_pdf_renderer_uses_audited_json_and_numbered_equations() -> None:
    tex = render_quantitative_models_tex(
        [
            {
                "model_spec": _specification(),
                "qualified_entries": [
                    {
                        "execution_id": "sim-001",
                        "hypothesis_relation": "REFUTED_WITHIN_MODEL",
                        "result_summary": "The model-internal trajectory crosses the stated threshold.",
                    }
                ],
                "lineage_summary": ["v0: REFUTED_WITHIN_MODEL (bounded result)"],
            }
        ]
    )

    assert "\\begin{equation}" in tex
    assert r"NOT\_EMPIRICAL" in tex
    assert "Acknowledg" not in tex


def test_separate_pdf_renderer_accepts_safe_piecewise_model_notation() -> None:
    specification = _specification()
    specification["scenarios"] = ["isolated_dipole"]
    specification["symbols"].append(
        {
            "symbol_id": "SYM-002",
            "latex": r"K_{\text{acc}}",
            "meaning": "Accretion coefficient",
            "unit": "kg_s^2_m^-3",
        }
    )
    specification["equations"] = [
        {
            "equation_id": "Q1-EQ-001",
            "kind": "DERIVATIVE",
            "latex": (
                r"\frac{dP}{dt}=\begin{cases}"
                r"-\frac{K_{\text{acc}}\dot{M}}{P} & \text{if } t<t_{\text{acc}}\land\dot{M}>0 \\ "
                r"\frac{K_{\text{dipole}}B_0^2}{P} & \text{otherwise}"
                r"\end{cases}"
            ),
            "where_symbol_ids": ["SYM-001", "SYM-002"],
        }
    ]

    tex = render_quantitative_models_tex(
        [
            {
                "model_spec": specification,
                "qualified_entries": [],
                "lineage_summary": ["v0: CONSTRAINED (bounded result)"],
            }
        ]
    )

    assert r"K_{\mathrm{acc}}" in tex
    assert r"\begin{cases}" in tex
    assert r"\mathrm{otherwise}" in tex
    assert r"$\mathrm{kg}\,\mathrm{s}^{2}\,\mathrm{m}^{-3}$" in tex
    assert r"isolated\_\allowbreak{}dipole" in tex


def test_author_disclosure_keeps_simulation_labels_and_rejects_no_boundary() -> None:
    document = {
        "sections": [],
        "source_manifest": {},
    }
    capsule = {
        "schema_version": "quantitative_author_handoff_v1",
        "evidence": [
            {
                "quantitative_idea_id": "Q1",
                "final_version": 0,
                "question": "How does x change?",
                "model_family": "ODE_IVP",
                "hypothesis_relation": "CONSTRAINED",
                "result_summary": "The model-internal trajectory remains bounded.",
                "applicability_conditions": ["k is constant"],
                "limitations": ["No empirical validation"],
                "lineage_summary": [{"version": 0, "relation": "CONSTRAINED", "reason": "bounded result"}],
                "supplement_pdf_reference": "quantitative_mathematical_models.pdf#Q1",
            }
        ],
    }

    rendered = append_quantitative_evidence_section(document, capsule)

    assert validate_quantitative_disclosure(rendered) == []
