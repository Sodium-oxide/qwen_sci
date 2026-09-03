from __future__ import annotations

import pytest

from src.agents.quantitative_modeling.capability_classifier import classify_mathir_capability
from src.agents.quantitative_modeling.mathir import (
    MathIRValidationError,
    evaluate_expression,
    validate_expression,
    validate_mathir_document,
)
from src.agents.quantitative_modeling.result_qualification import qualify_simulation_result
from src.agents.quantitative_modeling.run_plan import build_simulation_run_plan
from src.agents.quantitative_modeling.result_ledger import (
    append_result_ledger_entry,
    create_result_ledger,
    qualified_ledger_entries,
)
from src.agents.quantitative_modeling.sandbox_runner import (
    SimulationAuthorizationError,
    execute_simulation_run_plan,
)


def _variable(name: str) -> dict[str, str]:
    return {"op": "variable", "name": name}


def _constant(value: float) -> dict[str, float | str]:
    return {"op": "constant", "value": value}


def _ode_mathir() -> dict[str, object]:
    return {
        "schema_version": "mathir_v1",
        "system_type": "ODE_IVP",
        "states": [{"id": "x", "initial": 1.0}],
        "parameters": {"k": 1.0},
        "derivatives": {
            "x": {"op": "mul", "args": [{"op": "neg", "args": [_variable("k")]}, _variable("x")]}
        },
        "time_span": [0.0, 1.0],
        "solver_options": {"max_step": 0.1},
    }


def _identity() -> dict[str, object]:
    return {"science_run_id": "run-1", "quantitative_idea_id": "Q1", "version": 0}


def _diffusion_reaction_mathir() -> dict[str, object]:
    return {
        "schema_version": "mathir_v1",
        "system_type": "DIFFUSION_REACTION_1D",
        "state": {"id": "c"},
        "spatial_domain": [0.0, 1.0],
        "grid_points": 11,
        "initial_values": [0.0] * 11,
        "parameters": {"D": 0.1},
        "time_span": [0.0, 0.1],
        "solver_options": {"time_step": 0.001},
        "diffusion_coefficient": _variable("D"),
        "reaction": _constant(0.0),
        "boundary_conditions": {
            "left": {"type": "DIRICHLET", "value": _constant(1.0)},
            "right": {"type": "DIRICHLET", "value": _constant(0.0)},
        },
    }


def test_mathir_rejects_undeclared_dynamic_variable() -> None:
    payload = _ode_mathir()
    payload["derivatives"] = {"x": _variable("__import__")}

    with pytest.raises(MathIRValidationError, match="not declared"):
        validate_mathir_document(payload)


def test_mathir_conditionals_support_time_bounded_ode_phases() -> None:
    expression = {
        "op": "conditional",
        "args": [
            {"op": "lt", "args": [_variable("t"), _variable("t_acc")]},
            _constant(-2.0),
            _constant(1.0),
        ],
    }
    validated = validate_expression(expression, allowed_symbols={"t", "t_acc"})

    assert evaluate_expression(validated, {"t": 1.0, "t_acc": 2.0}) == -2.0
    assert evaluate_expression(validated, {"t": 3.0, "t_acc": 2.0}) == 1.0


def test_ode_plan_requires_explicit_authorization_and_runs_fixed_solver() -> None:
    plan = build_simulation_run_plan(
        model_identity=_identity(),
        mathir=_ode_mathir(),
        scenarios=[{"scenario_id": "baseline", "parameter_overrides": {}}],
    )

    with pytest.raises(SimulationAuthorizationError, match="--execute"):
        execute_simulation_run_plan(plan)

    result = execute_simulation_run_plan(
        plan,
        execute=True,
        confirmed_plan_identity=plan["plan_identity"],
    )

    final_value = result["scenario_results"][0]["result"]["summary"]["final_state"]["x"]
    assert final_value == pytest.approx(0.367879, rel=1e-4)


def test_plan_rejects_mutation_after_identity_confirmation() -> None:
    plan = build_simulation_run_plan(model_identity=_identity(), mathir=_ode_mathir())
    plan["resource_limits"]["max_output_points"] = 5_000

    with pytest.raises(Exception, match="identity"):
        execute_simulation_run_plan(
            plan,
            execute=True,
            confirmed_plan_identity=plan["plan_identity"],
        )


def test_qualified_negative_relation_is_retained() -> None:
    plan = build_simulation_run_plan(model_identity=_identity(), mathir=_ode_mathir())
    execution = execute_simulation_run_plan(
        plan,
        execute=True,
        confirmed_plan_identity=plan["plan_identity"],
    )

    qualification = qualify_simulation_result(
        execution,
        hypothesis_relation="REFUTED_WITHIN_MODEL",
    )

    assert qualification["result_quality"] == "QUALIFIED"
    assert qualification["hypothesis_relation"] == "REFUTED_WITHIN_MODEL"


def test_capability_defers_unsupported_model_type() -> None:
    capability = classify_mathir_capability(
        {"schema_version": "mathir_v1", "system_type": "PDE_3D"}
    )

    assert capability["capability"] == "DEFERRED"


def test_diffusion_reaction_plan_obeys_fixed_stability_bound() -> None:
    plan = build_simulation_run_plan(
        model_identity=_identity(),
        mathir=_diffusion_reaction_mathir(),
    )

    result = execute_simulation_run_plan(
        plan,
        execute=True,
        confirmed_plan_identity=plan["plan_identity"],
    )

    summary = result["scenario_results"][0]["result"]["summary"]
    assert summary["stability_bound_satisfied"] is True
    assert 0.0 < summary["final_mean"] < 1.0


def test_result_ledger_retains_qualified_refutation() -> None:
    plan = build_simulation_run_plan(model_identity=_identity(), mathir=_ode_mathir())
    execution = execute_simulation_run_plan(
        plan,
        execute=True,
        confirmed_plan_identity=plan["plan_identity"],
    )
    qualification = qualify_simulation_result(
        execution,
        hypothesis_relation="REFUTED_WITHIN_MODEL",
        required_validation_checks=plan["qualification_requirements"],
    )

    ledger = append_result_ledger_entry(
        create_result_ledger(model_identity=execution["model_identity"]),
        execution=execution,
        qualification=qualification,
        result_summary="The simulated model refutes the local hypothesis within its assumptions.",
        execution_record_path="execution_record.json",
        qualification_path="result_qualification.json",
    )

    assert qualified_ledger_entries(ledger)[0]["hypothesis_relation"] == "REFUTED_WITHIN_MODEL"
