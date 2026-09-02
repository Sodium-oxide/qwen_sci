from __future__ import annotations

import pytest

from src.agents.quantitative_modeling.pde.convergence import (
    build_refinement_documents,
    estimate_convergence_order,
)
from src.agents.quantitative_modeling.pde.diagnostics import estimate_pde_execution
from src.agents.quantitative_modeling.pde.mesh import build_structured_mesh
from src.agents.quantitative_modeling.pde.operators import laplacian_3d
from src.agents.quantitative_modeling.pde_solver import PDESolverError, execute_pdeir, pde_adapter_registry
from src.agents.quantitative_modeling.pdeir import validate_pdeir_document
from src.agents.quantitative_modeling.pde_verification import verify_pde_result
from src.agents.quantitative_modeling.result_qualification import qualify_simulation_result
from src.agents.quantitative_modeling.run_plan import build_simulation_run_plan
from src.agents.quantitative_modeling.sandbox_runner import execute_simulation_run_plan


def _constant(value: float) -> dict[str, object]:
    return {"op": "constant", "value": value}


def _variable(name: str) -> dict[str, object]:
    return {"op": "variable", "name": name}


def test_documented_axes_and_equation_terms_are_normalized() -> None:
    document = {
        "schema_version": "pdeir_v1",
        "system_type": "HEAT_DIFFUSION_1D",
        "spatial_domain": {
            "axes": [{"symbol": "x", "lower": 0.0, "upper": 1.0, "unit": "m"}]
        },
        "discretization": {
            "method": "FINITE_DIFFERENCE",
            "grid_type": "UNIFORM",
            "grid_points": 11,
            "time_integrator": "EXPLICIT_EULER",
            "time_step": 0.0001,
        },
        "time_span": [0.0, 0.001],
        "fields": [{"field_id": "temperature", "symbol": "T", "unit": "K"}],
        "parameters": {"kappa": 0.01},
        "equation_terms": {"diffusion_coefficient": _variable("kappa")},
        "initial_condition": {"type": "SAMPLED_VALUES", "values": [1.0] * 11},
        "boundary_conditions": {
            "left": {"type": "DIRICHLET", "value": 1.0},
            "right": {"type": "NEUMANN_ZERO"},
        },
    }
    normalized = validate_pdeir_document(document)
    assert normalized["fields"][0]["id"] == "temperature"
    assert normalized["spatial_domain"] == {"x": [0.0, 1.0]}
    result = execute_pdeir(document)
    assert result["solver_id"] == "pde_fd_heat_diffusion_1d"


def test_spherical_radial_thermal_uses_origin_regularity() -> None:
    document = {
        "schema_version": "pdeir_v1",
        "system_type": "SPHERICAL_RADIAL_THERMAL",
        "spatial_domain": {"x": [0.0, 1.0]},
        "grid": {"nx": 9},
        "time_span": [0.0, 0.0005],
        "solver_options": {"time_step": 0.00001, "time_integrator": "EXPLICIT_EULER"},
        "fields": [{"id": "temperature", "bounds": {"lower": 0.0}}],
        "parameters": {"kappa": 1.0, "capacity": 1.0},
        "diffusion_coefficient": _variable("kappa"),
        "heat_capacity": _variable("capacity"),
        "source": _constant(0.0),
        "initial_condition": {"type": "SAMPLED_VALUES", "values": [1.0] * 9},
        "boundary_conditions": {
            "left": {"type": "SPHERICAL_ORIGIN_REGULARITY"},
            "right": {"type": "DIRICHLET", "value": _constant(1.0)},
        },
    }
    result = execute_pdeir(document)
    assert result["numerical_checks"]["spherical_origin_regularity"] is True
    assert result["summary"]["stability_limit"] == 1.0 / 6.0


def test_dry_run_refinement_and_mesh_are_non_executing() -> None:
    document = {
        "schema_version": "pdeir_v1",
        "system_type": "HEAT_DIFFUSION_1D",
        "spatial_domain": {"x": [0.0, 1.0]},
        "grid": {"nx": 11},
        "time_span": [0.0, 0.001],
        "solver_options": {"time_step": 0.00001, "time_integrator": "EXPLICIT_EULER"},
        "fields": [{"id": "u"}],
        "parameters": {"kappa": 0.01},
        "diffusion_coefficient": _variable("kappa"),
        "reaction": _constant(0.0),
        "initial_condition": {"type": "SAMPLED_VALUES", "values": [1.0] * 11},
        "boundary_conditions": {
            "left": {"type": "DIRICHLET", "value": _constant(1.0)},
            "right": {"type": "NEUMANN_ZERO"},
        },
    }
    mesh = build_structured_mesh(document)
    estimate = estimate_pde_execution(document)
    refinements = build_refinement_documents(document, grid_multipliers=(1, 2), time_step_divisors=(1, 2))
    assert mesh.shape == (11,)
    assert estimate["execution_status"] == "READY"
    assert len(refinements) == 4
    assert all(item["requires_new_execution"] for item in refinements)
    assert estimate_convergence_order((0.25, 0.0625), (1.0, 2.0)) == 2.0


def test_all_registered_pde_adapters_have_a_dispatch_entry() -> None:
    registry = pde_adapter_registry()
    assert registry.contains("HEAT_DIFFUSION_1D")
    assert registry.contains("SPHERICAL_RADIAL_THERMAL")


def _heat_3d_document(*, time_step: float = 0.0001) -> dict[str, object]:
    return {
        "schema_version": "pdeir_v1",
        "system_type": "HEAT_DIFFUSION_3D",
        "spatial_domain": {"x": [0.0, 1.0], "y": [0.0, 2.0], "z": [-1.0, 1.0]},
        "grid": {"nx": 3, "ny": 3, "nz": 3},
        "time_span": [0.0, 0.0002],
        "solver_options": {"time_step": time_step, "time_integrator": "EXPLICIT_EULER"},
        "fields": [{"id": "temperature", "bounds": {"lower": 0.0}}],
        "parameters": {"kappa": 0.1},
        "diffusion_coefficient": _variable("kappa"),
        "reaction": _constant(0.0),
        "initial_condition": {"type": "SAMPLED_VALUES", "values": [1.0] * 27},
        "boundary_conditions": {
            "left": {"type": "NEUMANN_ZERO"},
            "right": {"type": "NEUMANN_ZERO"},
            "bottom": {"type": "NEUMANN_ZERO"},
            "top": {"type": "NEUMANN_ZERO"},
            "front": {"type": "NEUMANN_ZERO"},
            "back": {"type": "NEUMANN_ZERO"},
        },
    }


def test_heat_diffusion_3d_executes_and_verifies_six_faces() -> None:
    document = _heat_3d_document()
    normalized = validate_pdeir_document(document)
    assert normalized["spatial_dimension"] == 3
    assert normalized["grid"] == {"nx": 3, "ny": 3, "nz": 3}
    mesh = build_structured_mesh(normalized)
    assert mesh.dimensions == 3
    assert mesh.shape == (3, 3, 3)
    result = execute_pdeir(document)
    assert result["z"] == [-1.0, 0.0, 1.0]
    assert result["summary"]["grid_shape"] == [3, 3, 3]
    verification = verify_pde_result(result, document=normalized)
    assert verification["status"] == "NUMERICALLY_VERIFIED"
    assert verification["boundary_residuals"]["front"] == 0.0


def test_heat_diffusion_3d_rejects_unstable_step_and_resource_overrun() -> None:
    unstable = _heat_3d_document(time_step=1.0)
    unstable["time_span"] = [0.0, 1.0]
    with pytest.raises(PDESolverError, match="3D explicit diffusion stability"):
        execute_pdeir(unstable)
    with pytest.raises(PDESolverError, match="max_cells"):
        execute_pdeir(_heat_3d_document(), resource_limits={"max_cells": 26})
    with pytest.raises(PDESolverError, match="max_nz"):
        execute_pdeir(_heat_3d_document(), resource_limits={"max_nz": 2})


def test_heat_diffusion_3d_refinement_and_operator() -> None:
    document = _heat_3d_document()
    refinements = build_refinement_documents(document, grid_multipliers=(2,), time_step_divisors=(1,))
    refined = refinements[0]["document"]
    assert refined["grid"] == {"nx": 5, "ny": 5, "nz": 5}
    assert len(refined["initial_condition"]["values"]) == 125
    field = [float(i * i + j * j + k * k) for k in range(3) for j in range(3) for i in range(3)]
    laplacian = laplacian_3d(field, 3, 3, 3, 1.0, 1.0, 1.0)
    assert laplacian[1 + 3 * (1 + 3 * 1)] == 6.0


def test_heat_diffusion_3d_dry_run_counts_volume() -> None:
    estimate = estimate_pde_execution(_heat_3d_document())
    assert estimate["cell_count"] == 27
    assert estimate["grid_shape"] == [3, 3, 3]


def test_documented_three_axis_contract_and_periodic_faces_are_supported() -> None:
    document = {
        "schema_version": "pdeir_v1",
        "pde_family": "HEAT_DIFFUSION_3D",
        "spatial_domain": {
            "axes": [
                {"symbol": "x", "lower": 0.0, "upper": 1.0},
                {"symbol": "y", "lower": 0.0, "upper": 1.0},
                {"symbol": "z", "lower": 0.0, "upper": 1.0},
            ]
        },
        "grid": {"shape": [3, 3, 3]},
        "discretization": {"time_integrator": "EXPLICIT_EULER", "time_step": 0.0001},
        "time_span": [0.0, 0.0002],
        "fields": [{"field_id": "temperature"}],
        "parameters": {"kappa": 0.01},
        "equation_terms": {"diffusion_coefficient": _variable("kappa")},
        "observables": ["field_mean", "field_at_center"],
        "verification_plan": {"boundary_residual": True, "grid_refinement": False},
        "initial_condition": {"type": "SAMPLED_VALUES", "values": [float(i) for i in range(27)]},
        "boundary_conditions": {side: {"type": "PERIODIC"} for side in ("left", "right", "bottom", "top", "front", "back")},
    }
    normalized = validate_pdeir_document(document)
    assert normalized["grid"] == {"nx": 3, "ny": 3, "nz": 3}
    assert normalized["discretization"]["method"] == "FINITE_DIFFERENCE"
    assert normalized["verification_plan"]["boundary_residual"] is True
    result = execute_pdeir(document)
    verification = verify_pde_result(result, document=normalized)
    assert verification["checks"]["periodic_mismatch"] is True
    assert verification["boundary_residuals"]["periodic"] == 0.0


def test_heat_diffusion_3d_runs_through_authorized_execution_ir_plan() -> None:
    plan = build_simulation_run_plan(
        model_identity={
            "science_run_id": "science-pde-3d",
            "quantitative_idea_id": "Q1",
            "version": "0",
        },
        execution_ir={
            "kind": "PDE",
            "schema_version": "execution_ir_v1",
            "document": _heat_3d_document(),
        },
    )
    assert plan["qualification_requirements"] == ["explicit_stability", "finite_field"]
    execution = execute_simulation_run_plan(
        plan,
        execute=True,
        confirmed_plan_identity=plan["plan_identity"],
    )
    assert execution["status"] == "COMPLETED"
    assert execution["execution_ir_kind"] == "PDE"
    assert execution["scenario_results"][0]["result"]["verification"]["status"] == "NUMERICALLY_VERIFIED"


def test_diffusion_reaction_3d_reuses_the_registered_fixed_backend() -> None:
    document = _heat_3d_document()
    document["system_type"] = "DIFFUSION_REACTION_3D"
    document["reaction"] = {"op": "mul", "args": [{"op": "constant", "value": -0.1}, {"op": "field", "name": "temperature"}]}
    result = execute_pdeir(document)
    assert result["solver_id"] == "pde_fd_diffusion_reaction_3d"
    assert result["summary"]["grid_shape"] == [3, 3, 3]


def test_pde_qualification_rejects_unverified_numerical_result() -> None:
    execution = {
        "status": "COMPLETED",
        "execution_mode": "NUMERICAL_SIMULATION",
        "result_kind": "SIMULATED",
        "empirical_claim_status": "NOT_EMPIRICAL",
        "execution_ir_kind": "PDE",
        "scenario_results": [
            {
                "scenario_id": "baseline",
                "result": {
                    "numerical_checks": {"explicit_stability": True, "finite_field": True},
                    "verification": {"status": "NUMERICALLY_UNVERIFIED"},
                },
            }
        ],
    }
    qualification = qualify_simulation_result(
        execution,
        required_validation_checks=("explicit_stability", "finite_field"),
    )
    assert qualification["result_quality"] == "UNQUALIFIED"
    assert qualification["checks"]["pde_numeric_verification"] is False
