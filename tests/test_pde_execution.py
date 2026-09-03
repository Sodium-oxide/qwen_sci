from __future__ import annotations

import pytest

from src.agents.quantitative_modeling.execution_ir import (
    ExecutionIRValidationError,
    classify_execution_ir,
    execute_execution_ir,
    validate_execution_ir,
)
from src.agents.quantitative_modeling.execution_ir_compiler import compile_execution_ir_from_model_spec
from src.agents.quantitative_modeling.mathir_validator import audit_quantitative_model
from src.agents.quantitative_modeling.model_format import normalize_quantitative_model_spec
from src.agents.quantitative_modeling.pde_solver import PDESolverError, execute_pdeir
from src.agents.quantitative_modeling.run_plan import build_simulation_run_plan, validate_simulation_run_plan
from src.agents.quantitative_modeling.sandbox_runner import execute_simulation_run_plan


def _constant(value: float) -> dict[str, object]:
    return {"op": "constant", "value": value}


def _variable(name: str) -> dict[str, object]:
    return {"op": "variable", "name": name}


def _field(name: str) -> dict[str, object]:
    return {"op": "field", "name": name}


def _one_d(system_type: str = "ADVECTION_DIFFUSION_REACTION_1D") -> dict[str, object]:
    document: dict[str, object] = {
        "schema_version": "pdeir_v1",
        "system_type": system_type,
        "spatial_domain": {"x": [0.0, 1.0]},
        "grid": {"nx": 21},
        "time_span": [0.0, 0.01],
        "solver_options": {"time_step": 0.0001, "time_integrator": "EXPLICIT_EULER"},
        "fields": [{"id": "u", "symbol": "u", "unit": "1", "bounds": {"lower": 0.0}}],
        "parameters": {"D": 0.01, "v": 0.0, "k": 0.0},
        "initial_condition": {"type": "SAMPLED_VALUES", "values": [1.0] * 21},
        "diffusion_coefficient": _variable("D"),
        "reaction": {
            "op": "mul",
            "args": [{"op": "neg", "args": [_variable("k")]}, _field("u")],
        },
        "boundary_conditions": {
            "left": {"type": "DIRICHLET", "value": _constant(1.0)},
            "right": {"type": "NEUMANN_ZERO"},
        },
    }
    if system_type == "ADVECTION_DIFFUSION_REACTION_1D":
        document["advection_velocity"] = _variable("v")
    return document


def _envelope(document: dict[str, object]) -> dict[str, object]:
    return {"kind": "PDE", "schema_version": "execution_ir_v1", "document": document}


def _identity() -> dict[str, object]:
    return {"science_run_id": "science-test", "quantitative_idea_id": "Q1", "version": 0}


def _model_spec_v2(document: dict[str, object]) -> dict[str, object]:
    return {
        "schema_version": "ieee_math_model_v2",
        "lineage": {
            "science_run_id": "science-test",
            "survey_run_id": "survey-test",
            "project_id": "project-test",
            "project_context_fingerprint": "context-test",
            "selected_direction_id": "direction-test",
            "quantitative_idea_id": "Q1",
            "created_from_artifact": "quantitative_ideas_manifest.json",
            "version": 0,
            "parent_version": None,
        },
        "title": "One-dimensional transport model",
        "abstract": "A bounded PDEIR model.",
        "scientific_question": "How does a scalar field evolve?",
        "model_scope": "A one-dimensional advection-diffusion-reaction model.",
        "assumptions": [{"assumption_id": "Q1-A-001", "statement": "The domain is uniform.", "effect_if_violated": "The finite-difference approximation changes."}],
        "symbols": [{"symbol_id": "Q1-S-001", "latex": "u", "meaning": "field", "unit": "1", "dimension": "dimensionless", "role": "state"}],
        "equations": [{"equation_id": "Q1-EQ-001", "role": "governing", "latex": "\\partial_t u+v\\partial_x u=D\\partial_{xx}u+R", "where_symbol_ids": ["Q1-S-001"]}],
        "initial_conditions": ["u(x,0) is sampled on the grid."],
        "boundary_conditions": ["The left boundary is Dirichlet and the right is zero Neumann."],
        "parameterization": ["D, v, and k are declared scalar parameters."],
        "scenarios": ["baseline"],
        "objective_and_constraints": ["Use only the registered PDEIR family."],
        "algorithm": {"input": ["parameters"], "output": ["field series"], "steps": ["Run the fixed solver."]},
        "numerical_plan": {"solver_family": "ADVECTION_DIFFUSION_REACTION_1D", "discretization": "finite difference", "convergence_checks": ["explicit stability"]},
        "validation_plan": ["Check finite values."],
        "limitations": ["The result is a numerical simulation, not empirical evidence."],
        "references": [],
        "execution_ir": _envelope(document),
    }


def test_1d_advection_diffusion_executes_and_reports_stability() -> None:
    result = execute_pdeir(_one_d())
    assert result["solver_id"] == "pde_fd_advection_diffusion_reaction_1d"
    assert result["numerical_checks"] == {"explicit_stability": True, "finite_field": True}
    assert result["summary"]["maximum_diffusion_courant"] < 0.5


@pytest.mark.parametrize(
    "definition",
    [
        {"type": "ANALYTIC_PROFILE", "profile": "UNIFORM", "value": 1.0},
        {
            "type": "ANALYTIC_PROFILE",
            "profile": "GAUSSIAN",
            "amplitude": 1.0,
            "offset": 0.0,
            "center": 0.5,
            "sigma": 0.2,
        },
        {
            "type": "ANALYTIC_PROFILE",
            "profile": "ANALYTIC_EXPRESSION",
            "expression": {"op": "variable", "name": "x"},
        },
    ],
)
def test_compact_initial_condition_is_materialized_by_trusted_solver(
    definition: dict[str, object],
) -> None:
    document = _one_d()
    document["initial_condition"] = definition
    normalized = validate_execution_ir(_envelope(document))
    assert normalized["document"]["initial_condition"]["type"] == "ANALYTIC_PROFILE"
    result = execute_pdeir(document)
    assert result["status"] == "COMPLETED"
    assert result["numerical_checks"]["finite_field"] is True


def test_compact_wave_initial_velocity_is_materialized_without_llm_samples() -> None:
    document = {
        **_one_d("WAVE_1D"),
        "initial_condition": {
            "type": "ANALYTIC_PROFILE",
            "profile": "UNIFORM",
            "value": 0.0,
        },
        "initial_velocity": {
            "type": "ANALYTIC_PROFILE",
            "profile": "GAUSSIAN",
            "center": 0.5,
            "sigma": 0.2,
            "amplitude": 1.0,
            "offset": 0.0,
        },
        "wave_speed": _constant(1.0),
        "solver_options": {"time_step": 0.01, "time_integrator": "EXPLICIT_CENTRAL"},
    }
    result = execute_pdeir(document)
    assert result["numerical_checks"]["wave_cfl"] is True


def test_execution_ir_plan_requires_explicit_exact_authorization() -> None:
    plan = build_simulation_run_plan(model_identity=_identity(), execution_ir=_envelope(_one_d()))
    assert classify_execution_ir(_envelope(_one_d()))["capability"] == "COMPOSABLE"
    assert validate_simulation_run_plan(plan)["plan_identity"] == plan["plan_identity"]
    with pytest.raises(PermissionError):
        execute_simulation_run_plan(plan, execute=False, confirmed_plan_identity=plan["plan_identity"])
    result = execute_simulation_run_plan(plan, execute=True, confirmed_plan_identity=plan["plan_identity"])
    assert result["status"] == "COMPLETED"
    assert result["scenario_results"][0]["result"]["solver_id"] == "pde_fd_advection_diffusion_reaction_1d"


def test_model_spec_v2_audits_and_compiles_to_pde_execution_ir() -> None:
    specification = normalize_quantitative_model_spec(_model_spec_v2(_one_d()))
    audit = audit_quantitative_model(specification)
    compiled = compile_execution_ir_from_model_spec(specification)
    assert specification["schema_version"] == "ieee_math_model_v2"
    assert audit["status"] == "MODEL_AUDITED"
    assert audit["capability"]["kind"] == "PDE"
    assert compiled["kind"] == "PDE"


def test_2d_diffusion_reaction_executes() -> None:
    nx, ny = 9, 7
    document = _one_d("DIFFUSION_REACTION_2D")
    document["spatial_domain"] = {"x": [0.0, 1.0], "y": [0.0, 1.0]}
    document["grid"] = {"nx": nx, "ny": ny}
    document["initial_condition"] = {"type": "SAMPLED_VALUES", "values": [1.0] * (nx * ny)}
    document["boundary_conditions"] = {
        "left": {"type": "DIRICHLET", "value": _constant(1.0)},
        "right": {"type": "NEUMANN_ZERO"},
        "bottom": {"type": "NEUMANN_ZERO"},
        "top": {"type": "NEUMANN_ZERO"},
    }
    result = execute_pdeir(document)
    assert result["summary"]["grid_shape"] == [nx, ny]
    assert result["numerical_checks"]["explicit_stability"] is True


def test_elliptic_and_wave_families_execute() -> None:
    elliptic = {
        "schema_version": "pdeir_v1",
        "system_type": "ELLIPTIC_DIFFUSION_1D",
        "spatial_domain": {"x": [0.0, 1.0]},
        "grid": {"nx": 11},
        "fields": [{"id": "u"}],
        "parameters": {"k": 1.0},
        "diffusion_coefficient": _variable("k"),
        "reaction_coefficient": _constant(0.0),
        "source": _constant(1.0),
        "boundary_conditions": {
            "left": {"type": "DIRICHLET", "value": _constant(0.0)},
            "right": {"type": "DIRICHLET", "value": _constant(0.0)},
        },
    }
    elliptic_result = execute_pdeir(elliptic)
    assert elliptic_result["numerical_checks"]["linear_residual"] is True

    wave = {
        "schema_version": "pdeir_v1",
        "system_type": "WAVE_1D",
        "spatial_domain": {"x": [0.0, 1.0]},
        "grid": {"nx": 21},
        "time_span": [0.0, 0.1],
        "solver_options": {"time_step": 0.01, "time_integrator": "EXPLICIT_CENTRAL"},
        "fields": [{"id": "u"}],
        "parameters": {"c": 1.0},
        "wave_speed": _variable("c"),
        "source": _constant(0.0),
        "initial_condition": {"type": "SAMPLED_VALUES", "values": [0.0] * 21},
        "initial_velocity": {"type": "SAMPLED_VALUES", "values": [1.0] * 21},
        "boundary_conditions": {
            "left": {"type": "DIRICHLET", "value": _constant(0.0)},
            "right": {"type": "DIRICHLET", "value": _constant(0.0)},
        },
    }
    wave_result = execute_pdeir(wave)
    assert wave_result["numerical_checks"]["wave_cfl"] is True


def test_unsupported_expression_and_unstable_grid_are_rejected() -> None:
    invalid = _one_d()
    invalid["reaction"] = {"op": "call", "name": "dangerous"}
    with pytest.raises(ExecutionIRValidationError):
        validate_execution_ir(_envelope(invalid))

    unstable = _one_d()
    unstable["time_span"] = [0.0, 1.0]
    unstable["solver_options"] = {"time_step": 1.0}
    with pytest.raises(PDESolverError):
        execute_pdeir(unstable)


def test_burgers_family_uses_the_registered_nonlinear_advection_adapter() -> None:
    document = _one_d("BURGERS_1D")
    document["advection_velocity"] = _field("u")
    document["parameters"]["D"] = 0.001
    result = execute_pdeir(document)
    assert result["solver_id"] == "pde_fd_burgers_1d"
    assert result["numerical_checks"]["finite_field"] is True


def test_elliptic_2d_family_executes_with_a_linear_residual() -> None:
    nx, ny = 5, 5
    document: dict[str, object] = {
        "schema_version": "pdeir_v1",
        "system_type": "ELLIPTIC_DIFFUSION_2D",
        "spatial_domain": {"x": [0.0, 1.0], "y": [0.0, 1.0]},
        "grid": {"nx": nx, "ny": ny},
        "fields": [{"id": "u"}],
        "parameters": {"k": 1.0},
        "diffusion_coefficient": _variable("k"),
        "reaction_coefficient": _constant(0.0),
        "source": _constant(1.0),
        "boundary_conditions": {
            "left": {"type": "DIRICHLET", "value": _constant(0.0)},
            "right": {"type": "DIRICHLET", "value": _constant(0.0)},
            "bottom": {"type": "DIRICHLET", "value": _constant(0.0)},
            "top": {"type": "DIRICHLET", "value": _constant(0.0)},
        },
    }
    result = execute_pdeir(document)
    assert result["solver_id"] == "pde_fd_elliptic_diffusion_2d"
    assert result["summary"]["grid_shape"] == [nx, ny]
    assert result["numerical_checks"]["linear_residual"] is True
    document["boundary_conditions"]["right"] = {"type": "NEUMANN_ZERO"}
    mixed_result = execute_pdeir(document)
    assert mixed_result["numerical_checks"]["linear_residual"] is True


def test_wave_2d_family_executes_and_checks_cfl() -> None:
    nx, ny = 7, 6
    document: dict[str, object] = {
        "schema_version": "pdeir_v1",
        "system_type": "WAVE_2D",
        "spatial_domain": {"x": [0.0, 1.0], "y": [0.0, 1.0]},
        "grid": {"nx": nx, "ny": ny},
        "time_span": [0.0, 0.02],
        "solver_options": {"time_step": 0.001, "time_integrator": "EXPLICIT_CENTRAL"},
        "fields": [{"id": "u"}],
        "parameters": {"c": 1.0},
        "wave_speed": _variable("c"),
        "source": _constant(0.0),
        "initial_condition": {"type": "SAMPLED_VALUES", "values": [0.0] * (nx * ny)},
        "initial_velocity": {"type": "SAMPLED_VALUES", "values": [1.0] * (nx * ny)},
        "boundary_conditions": {
            "left": {"type": "DIRICHLET", "value": _constant(0.0)},
            "right": {"type": "DIRICHLET", "value": _constant(0.0)},
            "bottom": {"type": "DIRICHLET", "value": _constant(0.0)},
            "top": {"type": "DIRICHLET", "value": _constant(0.0)},
        },
    }
    result = execute_pdeir(document)
    assert result["solver_id"] == "pde_fd_wave_2d"
    assert result["numerical_checks"]["wave_cfl"] is True


def test_periodic_boundaries_must_be_a_complete_pair() -> None:
    document = _one_d()
    document["boundary_conditions"]["left"] = {"type": "PERIODIC"}
    with pytest.raises(ExecutionIRValidationError, match="complete opposing pair"):
        validate_execution_ir(_envelope(document))
