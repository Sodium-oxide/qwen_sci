from __future__ import annotations

import math
import os
from copy import deepcopy
from pathlib import Path

import pytest

from src.agents.computational_experiment_agent.analysis import analyze
from src.agents.computational_experiment_agent.artifacts import read_json, safe_path
from src.agents.computational_experiment_agent.code_builder import build_project
from src.agents.computational_experiment_agent.contracts import ExecutionRequest, validate_contract
from src.agents.computational_experiment_agent.domain_registry import validate_scientific_plan
from src.agents.computational_experiment_agent.execution.budget import BranchBudget, BudgetExhausted
from src.agents.computational_experiment_agent.execution.docker_runtime import DockerRuntime
from src.agents.computational_experiment_agent.execution.runtime import RunAuthorization
from src.agents.computational_experiment_agent.iteration import next_decision
from src.agents.computational_experiment_agent.orchestrator import ComputationalOrchestrator, DEFAULT_BUDGET
from src.pipeline.computational_manifests import verify_manifest
from src.pipeline.computational_state import load_state, update_state
from src.pipeline.science_run import atomic_write_json, file_sha256


def binding():
    return {"science_run_id": "acceptance", "survey_run_id": "survey-1", "project_id": "project-1",
        "project_context_fingerprint": "project-fp", "selected_direction_id": "direction-1",
        "idea_result_sha256": "a" * 64, "handoff_fingerprint": "handoff-fp"}


def context():
    return {"schema_version": "computational_context_v1", "source_binding": binding(),
        "topic": "Scalar relaxation reference solution", "research_brief": {"question": "Does relaxation decay?"},
        "target_gap_ids": ["gap-1"], "gaps": [{"gap_id": "gap-1"}], "evidence": [], "inputs": [],
        "user_constraints": {}, "resource_budget": {**DEFAULT_BUDGET, "max_code_repairs": 1, "max_protocol_revisions": 0}}


def ode_plan(backend="python_project"):
    reference = {"op": "exp", "args": [{"op": "neg", "args": [{"op": "variable", "name": "t"}]}]}
    plan = {"schema_version": "computational_experiment_plan_v1", "experiment_id": "CE001",
        "source_binding": binding(), "protocol_version": 1, "status": "READY", "title": "Decay reference",
        "target_gap_ids": ["gap-1"], "research_question": "Does scalar concentration decay accurately?",
        "hypothesis": "The final concentration is below 0.4", "competing_explanations": ["Numerical bias"],
        "scientific_role": "Verify the reference relaxation dynamics", "discipline_template": "physical_engineering",
        "method_family": "numerical_modeling", "backend_id": backend, "result_kind": "NUMERICAL_SIMULATION",
        "model_spec": {"variables": ["concentration"], "equations": ["dc/dt=-c"], "initial_conditions": {"concentration": 1},
            "boundary_conditions": {"not_applicable": "ODE"}, "time_span": [0., 1.], "assumptions": ["constant rate"]},
        "method_spec": {"solver": "solve_ivp", "tolerances": {"rtol": 1e-9}, "discretization": "adaptive",
            "convergence_plan": "compare loose and tight tolerances"}, "inputs": [], "parameters": [],
        "comparisons": [{"condition_id": "coarse", "role": "baseline", "definition": "coarse step", "overrides": {"max_step": .1}},
            {"condition_id": "fine", "role": "primary", "definition": "fine step", "overrides": {"max_step": .01}}],
        "endpoints": [{"metric_id": "final_concentration", "description": "Concentration at time 1", "unit": "dimensionless",
            "estimator": "final_concentration", "primary": True,
            "observation_binding": {"source_key": "traces", "value_key": "values", "statistic": "final_value"}}],
        "validation_plan": [{"check_id": "finite_outputs", "description": "finite", "settings": {}},
            {"check_id": "reference_or_invariant", "description": "analytic reference error", "settings": {
                "reference_expression": reference, "operator": "lt", "threshold": 1e-6}}],
        "error_analysis_plan": [{"check_id": "convergence", "description": "step convergence", "settings": {
            "metric_id": "final_concentration", "compare_conditions": ["coarse", "fine"], "operator": "lt", "threshold": 1e-6}}],
        "decision_rule": {"metric_id": "final_concentration", "condition_id": "fine", "operator": "lt", "threshold": .4},
        "claim_scope": "Scalar model dc/dt=-c, time interval 0 to 1, initial concentration 1", "stopping_rules": ["accept qualified negative results"],
        "resource_budget": context()["resource_budget"], "unresolved_inputs": []}
    if backend == "mathir":
        plan["model_spec"]["mathir"] = {"schema_version": "mathir_v1", "system_type": "ODE_IVP",
            "states": [{"id": "concentration", "initial": 1.}], "parameters": {}, "time_span": [0., 1.],
            "derivatives": {"concentration": {"op": "neg", "args": [{"op": "variable", "name": "concentration"}]}},
            "solver_options": {"max_step": .1}}
        plan["comparisons"][0]["overrides"] = {"solver_options": {"max_step": .1}}
        plan["comparisons"][1]["overrides"] = {"solver_options": {"max_step": .01}}
        plan["endpoints"][0]["estimator"] = "summary.final_state.concentration"
    return plan


def chemistry_plan():
    plan = ode_plan("pyscf")
    plan.update(title="Hydrogen basis sensitivity", discipline_template="materials_chemical", method_family="quantum_chemistry",
        research_question="How does the HF energy depend on basis size?",
        model_spec={"structure": "H 0 0 0; H 0 0 0.74", "structure_unit": "angstrom", "charge": 0,
            "spin": 0, "environment": "gas", "assumptions": ["fixed geometry; nonrelativistic HF"]},
        method_spec={"implementation_mode": "fixed", "task_type": "single_point", "method": "RHF", "basis": "sto-3g", "scf_tolerance": 1e-10,
            "max_scf_cycles": 50, "method_sensitivity": "6-31g basis comparison"},
        comparisons=[{"condition_id": "minimal", "role": "baseline", "definition": "sto-3g", "overrides": {}},
            {"condition_id": "extended", "role": "sensitivity", "definition": "6-31g", "overrides": {"basis": "6-31g"}}],
        endpoints=[{"metric_id": "energy", "description": "HF energy", "unit": "hartree", "estimator": "total_energy", "primary": True}],
        validation_plan=[{"check_id": check_id, "description": check_id, "settings": {}} for check_id in
            ("finite_outputs", "scf_convergence", "electronic_state")],
        error_analysis_plan=[{"check_id": "method_sensitivity", "description": "basis energy difference", "settings": {
            "metric_id": "energy", "compare_conditions": ["minimal", "extended"], "operator": "lt", "threshold": .1}}],
        decision_rule={"metric_id": "energy", "condition_id": "extended", "operator": "lt", "threshold": -1.1},
        claim_scope="Gas-phase H2 at fixed bond length 0.74 angstrom, restricted Hartree-Fock and two specified bases")
    return plan


ODE_CODE = '''import json
import os
from pathlib import Path
from scipy.integrate import solve_ivp
assert os.environ.get('QWENSCI_ACCEPTANCE_SECRET') is None
assert not Path('/var/run/docker.sock').exists()
plan=json.loads(Path('configs/experiment.json').read_text())
raw={'metrics': [], 'traces': []}
for condition in plan['comparisons']:
    solved=solve_ivp(lambda at_time, state: -state, [0,1], [1.], max_step=condition['overrides']['max_step'], rtol=1e-9, atol=1e-12)
    raw['traces'].append({'condition_id': condition['condition_id'], 'times': solved.t.tolist(), 'values': solved.y[0].tolist()})
    raw['metrics'].append({'metric_id': 'final_concentration', 'condition_id': condition['condition_id'], 'value': float(solved.y[0,-1]), 'unit':'dimensionless'})
Path('/output/observations.json').write_text(json.dumps(raw,allow_nan=False))
'''


def callback(plan=None, code=ODE_CODE):
    def call(prompt, **kwargs):
        if "Return JSON {plans:" in prompt:
            return {"plans": [deepcopy(plan or ode_plan())]}
        return {"files": [{"path": "src/run_experiment.py", "purpose": "reference solver", "content": code}], "dependencies": ["scipy"]}
    return call


def execution_record(tmp_path, status="COMPLETED"):
    output = tmp_path / "execution-001"
    output.mkdir(exist_ok=True)
    (output / "stderr.log").touch()
    (output / "stdout.log").touch()
    return {"schema_version": "computational_execution_v1", "execution_id": "execution-001", "experiment_id": "CE001",
        "source_binding": binding(), "protocol_version": 1, "implementation_version": 1, "purpose": "formal", "status": status,
        "command": ["python", "-m", "src.run_experiment"], "environment": {}, "started_at": "now", "finished_at": "now",
        "elapsed_seconds": 1., "exit_code": 0 if status == "COMPLETED" else 1, "resource_usage": {}, "output_dir": str(output),
        "stdout_path": str(output / "stdout.log"), "stderr_path": str(output / "stderr.log"), "authorization_id": "auth", "error": ""}


def observations():
    return {"metrics": [{"metric_id": "final_concentration", "condition_id": name, "value": math.exp(-1), "unit": "dimensionless"}
        for name in ("coarse", "fine")], "traces": [{"condition_id": name, "times": [0,1], "values": [1,math.exp(-1)]}
        for name in ("coarse", "fine")]}


def generated_chemistry_plan():
    plan = chemistry_plan()
    plan["method_spec"].update(implementation_mode="generated", method="MP2", task_type="correlated_properties",
        iterative_method=False, noniterative_justification="Canonical MP2 correlation energy is evaluated without a correlated iterative solver")
    plan["endpoints"] = [
        {"metric_id": "energy", "description": "MP2 total energy", "unit": "hartree", "estimator": "mp2.e_tot", "primary": True,
            "observation_binding": {"source_key": "calculation_results", "value_key": "total_energy", "statistic": "value"}},
        {"metric_id": "dipole", "description": "Reference dipole magnitude", "unit": "debye", "estimator": "norm(reference.dip_moment())", "primary": False,
            "observation_binding": {"source_key": "calculation_results", "value_key": "dipole_norm", "statistic": "value"}}]
    plan["claim_scope"] = "MP2 H2 energies and reference dipoles at fixed geometry in the declared bases"
    return plan


GENERATED_PYSCF_CODE = '''import json
from pathlib import Path
import numpy as np
from pyscf import gto, scf, mp
plan = json.loads(Path('configs/experiment.json').read_text())
raw = {'metrics': [], 'calculation_results': [], 'electronic_states': []}
for condition in plan['comparisons']:
    options = {**plan['model_spec'], **plan['method_spec'], **condition['overrides']}
    molecule = gto.M(atom=options['structure'], unit=options['structure_unit'], charge=options['charge'],
        spin=options['spin'], basis=options['basis'], verbose=4, output='/output/' + condition['condition_id'] + '.log')
    reference = scf.RHF(molecule)
    reference.conv_tol = options['scf_tolerance']
    reference.max_cycle = options['max_scf_cycles']
    reference.kernel()
    calculation = mp.MP2(reference).run()
    energy = float(calculation.e_tot)
    dipole = float(np.linalg.norm(reference.dip_moment(unit='Debye')))
    raw['calculation_results'].append({'condition_id': condition['condition_id'], 'total_energy': energy, 'dipole_norm': dipole})
    raw['electronic_states'].append({'condition_id': condition['condition_id'], 'converged': bool(reference.converged),
        'charge': molecule.charge, 'spin': molecule.spin, 'nelectron': molecule.nelectron})
    for metric_id, value, unit in [('energy', energy, 'hartree'), ('dipole', dipole, 'debye')]:
        raw['metrics'].append({'metric_id': metric_id, 'condition_id': condition['condition_id'], 'value': value, 'unit': unit})
Path('/output/observations.json').write_text(json.dumps(raw, allow_nan=False))
'''


def generated_chemistry_observations():
    return {'metrics': [{'metric_id': metric_id, 'condition_id': name, 'value': value, 'unit': unit}
            for name in ('minimal', 'extended') for metric_id, value, unit in [('energy', -1.13, 'hartree'), ('dipole', 0., 'debye')]],
        'calculation_results': [{'condition_id': name, 'total_energy': -1.13, 'dipole_norm': 0.} for name in ('minimal', 'extended')],
        'electronic_states': [{'condition_id': name, 'converged': True, 'charge': 0, 'spin': 0, 'nelectron': 2}
            for name in ('minimal', 'extended')]}


def test_generated_pyscf_accepts_api_methods_and_nonenergy_properties(tmp_path):
    from src.agents.computational_experiment_agent.backends.pyscf_backend import PySCFBackend
    plan = generated_chemistry_plan()
    assert validate_scientific_plan(plan).passed
    assert PySCFBackend().validate(plan) == []
    implementation = build_project(plan, tmp_path / 'implementation', callback(code=GENERATED_PYSCF_CODE), environment_id='image')
    assert 'mp.MP2' in (tmp_path / 'implementation/project/src/run_experiment.py').read_text()
    assert implementation['backend_id'] == 'pyscf'
    result = analyze(plan, execution_record(tmp_path), generated_chemistry_observations())
    assert result['validation_status'] == 'QUALIFIED', result


def test_generated_pyscf_checks_raw_values_and_electronic_conditions(tmp_path):
    plan = generated_chemistry_plan()
    raw = generated_chemistry_observations()
    raw['metrics'][0]['value'] = -99.
    assert analyze(plan, execution_record(tmp_path), raw)['validation_status'] == 'UNQUALIFIED'
    raw = generated_chemistry_observations()
    raw['electronic_states'][1]['converged'] = False
    assert analyze(plan, execution_record(tmp_path), raw)['validation_status'] != 'QUALIFIED'
    raw = generated_chemistry_observations()
    raw['electronic_states'][1]['condition_id'] = 'minimal'
    assert analyze(plan, execution_record(tmp_path), raw)['validation_status'] != 'QUALIFIED'
    raw = generated_chemistry_observations()
    plan['comparisons'][1]['overrides']['charge'] = 1
    assert analyze(plan, execution_record(tmp_path), raw)['validation_status'] != 'QUALIFIED'


def test_new_pyscf_plans_default_to_generated_mode():
    from src.agents.computational_experiment_agent.planner import plan_experiments
    plan = generated_chemistry_plan()
    plan['method_spec'].pop('implementation_mode')
    assert plan_experiments(context(), callback(plan))[0]['method_spec']['implementation_mode'] == 'generated'


def test_generated_geometry_task_requires_its_own_checks():
    plan = generated_chemistry_plan()
    plan['method_spec'].update(task_type='geometry_optimization', geometry_convergence='gradient norm threshold')
    assert 'missing_mandatory_check:geometry_convergence' in validate_scientific_plan(plan).errors
    plan['validation_plan'].append({'check_id': 'geometry_convergence', 'description': 'gradient', 'settings': {'metric_id': 'gradient'}})
    assert validate_scientific_plan(plan).passed


def test_generated_condition_task_override_cannot_skip_diagnostics(tmp_path):
    plan = generated_chemistry_plan()
    plan['comparisons'][1]['overrides'].update(task_type='geometry_optimization', geometry_convergence='gradient norm')
    assert 'missing_mandatory_check:geometry_convergence' in validate_scientific_plan(plan).errors
    assert analyze(plan, execution_record(tmp_path), generated_chemistry_observations())['validation_status'] == 'UNQUALIFIED'
    plan['validation_plan'].append({'check_id': 'geometry_convergence', 'description': 'gradient norm', 'settings': {
        'metric_id': 'dipole', 'condition_id': 'minimal', 'operator': 'lt', 'threshold': 1e-6}})
    assert analyze(plan, execution_record(tmp_path), generated_chemistry_observations())['validation_status'] != 'QUALIFIED'
    plan['validation_plan'][-1]['settings']['condition_id'] = 'extended'
    assert analyze(plan, execution_record(tmp_path), generated_chemistry_observations())['validation_status'] == 'QUALIFIED'


def test_generated_iterative_method_requires_post_scf_convergence():
    plan = generated_chemistry_plan()
    plan['method_spec'].update(method='CCSD', iterative_method=True)
    assert 'missing_mandatory_check:method_convergence' in validate_scientific_plan(plan).errors
    plan['method_spec'].pop('iterative_method')
    assert any('explicit_classification_required' in error for error in validate_scientific_plan(plan).errors)
    assert 'missing_mandatory_check:method_convergence' in validate_scientific_plan(plan).errors


def test_generated_non_scf_algorithm_can_use_its_own_diagnostics(tmp_path):
    plan = generated_chemistry_plan()
    plan['method_spec'].update(method='direct FCI', reference_scf_required=False,
        reference_scf_justification='Direct Hamiltonian diagonalization without a mean-field reference')
    plan['method_spec'].pop('scf_tolerance')
    plan['method_spec'].pop('max_scf_cycles')
    plan['validation_plan'] = [check for check in plan['validation_plan'] if check['check_id'] != 'scf_convergence']
    assert validate_scientific_plan(plan).passed
    raw = generated_chemistry_observations()
    for record in raw['electronic_states']:
        record.pop('converged')
    assert analyze(plan, execution_record(tmp_path), raw)['validation_status'] == 'QUALIFIED'


@pytest.mark.parametrize("relative", ["../escape", "/absolute", "C:/secret", "./alias", "folder//alias"])
def test_artifact_paths_reject_aliases(tmp_path, relative):
    with pytest.raises(ValueError):
        safe_path(tmp_path, relative)


def test_plan_domain_checks_and_missing_mandatory_checks():
    assert validate_scientific_plan(ode_plan()).passed
    assert validate_scientific_plan(chemistry_plan()).passed
    plan = ode_plan()
    plan["validation_plan"] = plan["validation_plan"][:1]
    assert "missing_mandatory_check:reference_or_invariant" in validate_scientific_plan(plan).errors


@pytest.mark.parametrize("case,expected", [("solvent", "gas_phase_only"), ("spin", "requires_closed_shell"),
    ("geometry", "condition_override"), ("duplicate_basis", "missing_method_sensitivity")])
def test_fixed_chemistry_backend_rejects_unimplemented_physical_conditions(case, expected):
    from src.agents.computational_experiment_agent.backends.pyscf_backend import PySCFBackend
    plan = chemistry_plan()
    if case == "solvent":
        plan["model_spec"]["environment"] = "aqueous"
    elif case == "spin":
        plan["model_spec"]["spin"] = 1
    elif case == "geometry":
        plan["comparisons"][1]["overrides"]["structure"] = "H 0 0 0; H 0 0 0.8"
    else:
        plan["comparisons"][1]["overrides"] = {}
    assert any(expected in error for error in PySCFBackend().validate(plan))


def test_statuses_are_host_qualified_and_negative_result_stops(tmp_path):
    plan = ode_plan()
    plan["decision_rule"]["threshold"] = .1
    result = analyze(plan, execution_record(tmp_path), observations())
    assert result["validation_status"] == "QUALIFIED"
    assert result["hypothesis_relation"] == "REFUTED"
    assert next_decision(plan, execution_record(tmp_path), result, repairs=0, revisions=0, remaining_seconds=30).kind == "ACCEPT_RESULT"
    result["validation_status"] = "UNQUALIFIED"
    assert "unqualified_result_must_be_inconclusive" in validate_contract(result)


def test_nonfinite_or_missing_condition_cannot_qualify(tmp_path):
    raw = observations()
    raw["metrics"][0]["value"] = float("nan")
    assert analyze(ode_plan(), execution_record(tmp_path), raw)["validation_status"] == "UNQUALIFIED"


def test_metrics_are_derived_from_bound_raw_observations_and_all_conditions(tmp_path):
    raw = observations()
    for row in raw["metrics"]:
        row["value"] = .001
    result = analyze(ode_plan(), execution_record(tmp_path), raw)
    assert result["validation_status"] == "UNQUALIFIED"
    assert "metric_differs_from_bound_observation" in result["unresolved_items"]
    raw = observations()
    raw["traces"].pop()
    assert analyze(ode_plan(), execution_record(tmp_path), raw)["validation_status"] != "QUALIFIED"
    plan = ode_plan()
    plan["endpoints"][0]["observation_binding"] = {"source_key": "metrics", "value_key": "value", "statistic": "value"}
    assert analyze(plan, execution_record(tmp_path), observations())["validation_status"] == "UNQUALIFIED"
    raw = observations()
    raw["metrics"].pop()
    assert analyze(ode_plan(), execution_record(tmp_path), raw)["validation_status"] == "UNQUALIFIED"


def test_budget_zero_and_failed_execution_count(tmp_path):
    limits = {**DEFAULT_BUDGET, "max_total_executions": 1}
    update_state(tmp_path, execution_count=0)
    budget = BranchBudget(tmp_path, limits)
    assert budget.reserve()[0] == 1
    with pytest.raises(BudgetExhausted):
        budget.reserve()
    limits["max_wall_seconds"] = 0
    with pytest.raises(BudgetExhausted):
        BranchBudget(tmp_path, limits).reserve()


def test_plan_mode_has_no_execution_authorization_and_seals_inputs(tmp_path):
    controller = ComputationalOrchestrator(tmp_path, llm_call=callback())
    assert controller.start(context=context(), mode="plan")["status"] == "PLANNED"
    assert not (tmp_path / "computation" / "authorization.json").exists()
    assert verify_manifest(tmp_path / "computation" / "manifest.json")["results"] == []
    path = tmp_path / "computation" / "CE001" / "protocol-v001" / "plan.json"
    path.write_text("{}")
    with pytest.raises(ValueError, match="modified"):
        verify_manifest(tmp_path / "computation" / "manifest.json")


def test_off_mode_creates_no_branch(tmp_path):
    assert ComputationalOrchestrator(tmp_path).start(context={}, mode="off")["status"] == "DISABLED"
    assert not (tmp_path / "computation").exists()


def test_project_source_does_not_override_trusted_configs(tmp_path):
    def bad_callback(*args, **kwargs):
        return {"files": [{"path": "configs/experiment.json", "content": "{}"}], "dependencies": []}
    with pytest.raises(ValueError, match="host_configuration"):
        build_project(ode_plan(), tmp_path, bad_callback, environment_id="image")


def test_runtime_authorization_rejects_nan_and_binding_mismatch(tmp_path):
    request = ExecutionRequest("CE001", 1, 1, "formal", ("python", "-m", "src.run_experiment"), "image",
        tmp_path, tmp_path, tmp_path, binding(), float("nan"), 1, 1024, True)
    authorization = RunAuthorization("auth", binding(), DEFAULT_BUDGET)
    with pytest.raises(ValueError, match="resource_exceeded"):
        authorization.validate(request)


class FakeRuntime:
    def __init__(self, statuses=("COMPLETED",)):
        self.statuses = statuses
        self.calls = []

    def run(self, request, authorization, *, cancel, on_started):
        self.calls.append(request)
        on_started("fake-container")
        request.output_dir.mkdir(parents=True, exist_ok=True)
        raw = request.output_dir / "raw"
        raw.mkdir()
        atomic_write_json(raw / "observations.json", observations())
        (request.output_dir / "stdout.log").touch()
        (request.output_dir / "stderr.log").write_text("simulated engineering failure")
        status = self.statuses[min(len(self.calls) - 1, len(self.statuses) - 1)]
        return {**execution_record(request.output_dir.parent, status), "execution_id": request.output_dir.name,
            "implementation_version": request.implementation_version, "protocol_version": request.protocol_version,
            "source_binding": request.source_binding, "experiment_id": request.experiment_id,
            "authorization_id": authorization.authorization_id, "output_dir": str(request.output_dir),
            "stdout_path": str(request.output_dir / "stdout.log"), "stderr_path": str(request.output_dir / "stderr.log")}

    def cancel(self, name):
        pass


def test_generated_pyscf_code_failure_is_repaired(tmp_path):
    runtime = FakeRuntime(('FAILED', 'COMPLETED'))
    original_run = runtime.run

    def run(*args, **kwargs):
        execution = original_run(*args, **kwargs)
        atomic_write_json(Path(execution['output_dir']) / 'raw/observations.json', generated_chemistry_observations())
        return execution

    runtime.run = run
    controller = ComputationalOrchestrator(tmp_path, llm_call=callback(generated_chemistry_plan(), GENERATED_PYSCF_CODE), runtime=runtime)
    state = controller.start(context=context(), mode='run')
    assert state['status'] == 'COMPLETED', state
    assert [request.implementation_version for request in runtime.calls] == [1, 2]
    assert verify_manifest(tmp_path / 'computation/manifest.json')['results'][0]['validation_status'] == 'QUALIFIED'


def test_code_failure_creates_bounded_repair_and_preserves_versions(tmp_path):
    runtime = FakeRuntime(("FAILED", "COMPLETED"))
    controller = ComputationalOrchestrator(tmp_path, llm_call=callback(), runtime=runtime)
    state = controller.start(context=context(), mode="run")
    assert state["status"] == "COMPLETED", state
    assert [request.implementation_version for request in runtime.calls] == [1, 2]
    assert state["experiments"]["CE001"]["repairs"] == 1
    assert verify_manifest(tmp_path / "computation" / "manifest.json")["results"][0]["validation_status"] == "QUALIFIED"


def test_completed_program_without_observations_remains_unqualified_and_publishable(tmp_path):
    runtime = FakeRuntime()
    original_run = runtime.run

    def missing_output(*args, **kwargs):
        execution = original_run(*args, **kwargs)
        (Path(execution["output_dir"]) / "raw/observations.json").unlink()
        return execution

    runtime.run = missing_output
    state = ComputationalOrchestrator(tmp_path, llm_call=callback(), runtime=runtime).start(context=context(), mode="run")
    assert state["status"] == "PARTIAL", state
    handoff = verify_manifest(tmp_path / "computation/manifest.json")
    assert handoff["results"][0]["validation_status"] == "UNQUALIFIED"
    assert state["execution_count"] == 2


@pytest.mark.parametrize("case,expected", [("missing_input", "NEEDS_INPUT"), ("missing_image", "ENVIRONMENT_UNAVAILABLE"),
    ("budget", "BUDGET_EXHAUSTED"), ("cancel", "CANCELLED")])
def test_unavailable_and_stopped_branches_publish_handoff(tmp_path, case, expected):
    plan = ode_plan()
    runtime = FakeRuntime(("ENVIRONMENT_UNAVAILABLE",)) if case == "missing_image" else FakeRuntime()
    inputs = context()
    if case == "missing_input":
        plan.update(status="NEEDS_INPUT", unresolved_inputs=["reference input missing"])
    if case == "budget":
        inputs["resource_budget"]["max_total_executions"] = 0
    controller = ComputationalOrchestrator(tmp_path, llm_call=callback(plan), runtime=runtime)
    if case == "cancel":
        controller.cancelled = lambda: True
    state = controller.start(context=inputs, mode="run")
    assert state["status"] == expected, state
    assert verify_manifest(tmp_path / "computation" / "manifest.json")["branch_status"] == expected
    if case != "missing_image":
        assert not runtime.calls


def test_resume_recovers_completed_execution_without_resubmission(tmp_path):
    runtime = FakeRuntime()
    controller = ComputationalOrchestrator(tmp_path, llm_call=callback(), runtime=runtime)
    original = controller._checkpoint

    def interrupted_checkpoint(plan, **changes):
        if changes.get("accepted_result_path"):
            raise KeyboardInterrupt("simulated interruption after completed execution")
        original(plan, **changes)

    controller._checkpoint = interrupted_checkpoint
    with pytest.raises(KeyboardInterrupt):
        controller.start(context=context(), mode="run")
    controller._checkpoint = original
    state = controller.resume()
    assert state["status"] == "COMPLETED", state
    assert state["execution_count"] == 1
    assert len(runtime.calls) == 1
    assert verify_manifest(tmp_path / "computation" / "manifest.json")["results"]


def test_recovery_rejects_other_experiment_protocol(tmp_path):
    from src.agents.computational_experiment_agent.execution.runtime import RunAuthorization
    branch = tmp_path / "computation"
    other = ode_plan()
    other["experiment_id"] = "CE002"
    atomic_write_json(branch / "CE002/protocol-v001/plan.json", other)
    update_state(branch, plan_paths=["CE002/protocol-v001/plan.json"],
        experiments={"CE001": {"protocol_path": "CE002/protocol-v001/plan.json"}})
    controller = ComputationalOrchestrator(tmp_path, runtime=FakeRuntime())
    with pytest.raises(ValueError, match="resumed_protocol_identity"):
        controller._run_experiment(ode_plan(), context(), BranchBudget(branch, DEFAULT_BUDGET),
            RunAuthorization("auth", binding(), DEFAULT_BUDGET))


def test_author_verification_recomputes_numeric_evidence(tmp_path):
    controller = ComputationalOrchestrator(tmp_path, llm_call=callback(), runtime=FakeRuntime())
    controller.start(context=context(), mode="run")
    root = tmp_path / "computation"
    handoff = read_json(root / "author_handoff.json")
    handoff["results"][0]["metrics"][0]["value"] = .123
    from src.pipeline.computational_manifests import write_manifest
    manifest = write_manifest(root, handoff)
    with pytest.raises(ValueError, match="qualification_differs_from_raw_execution:metrics"):
        verify_manifest(manifest)
    with pytest.raises(ValueError, match="computational_source_mismatch"):
        verify_manifest(manifest, expected_identity={"selected_direction_id": "other"})


@pytest.mark.parametrize("field,value", [("result_kind", "EMPIRICAL_REANALYSIS"), ("claim_scope", "All physical systems")])
def test_author_verification_rejects_result_scope_upgrade(tmp_path, field, value):
    from src.pipeline.computational_manifests import write_manifest
    controller = ComputationalOrchestrator(tmp_path, llm_call=callback(), runtime=FakeRuntime())
    controller.start(context=context(), mode="run")
    root = tmp_path / "computation"
    handoff = read_json(root / "author_handoff.json")
    handoff["results"][0][field] = value
    with pytest.raises(ValueError, match="result_protocol_semantics_mismatch"):
        verify_manifest(write_manifest(root, handoff))


def test_author_verification_rejects_redirected_output(tmp_path):
    from src.pipeline.computational_manifests import write_manifest
    from src.agents.computational_experiment_agent.artifacts import record
    controller = ComputationalOrchestrator(tmp_path, llm_call=callback(), runtime=FakeRuntime())
    controller.start(context=context(), mode="run")
    root = tmp_path / "computation"
    handoff = read_json(root / "author_handoff.json")
    execution_path = Path(handoff["results"][0]["lineage"][0]["execution_path"])
    execution = read_json(execution_path)
    execution["output_dir"] = str(tmp_path / "unsealed")
    atomic_write_json(execution_path, execution)
    relative = execution_path.relative_to(root).as_posix()
    handoff["artifact_refs"] = [record(root, execution_path) if item["path"] == relative else item for item in handoff["artifact_refs"]]
    with pytest.raises(ValueError, match="execution_output_paths_mismatch"):
        verify_manifest(write_manifest(root, handoff))


def test_stop_rereads_final_container_checkpoint_and_respects_owner(tmp_path, monkeypatch):
    from src.pipeline import computational_workflow as workflow
    root = tmp_path / "computation"
    identity = {"pid": 123, "create_time": 1.}
    update_state(root, owner=identity, experiments={})
    calls = []

    class Process:
        pid = 123

        def suspend(self):
            calls.append("suspend")

        def children(self, recursive):
            return []

        def terminate(self):
            update_state(root, experiments={"CE001": {"active_container": "late-container"}})

        def wait(self, timeout):
            return 0

    monkeypatch.setattr(workflow, "owner_alive", lambda identity: True)
    monkeypatch.setattr(workflow.psutil, "Process", lambda pid: Process())
    monkeypatch.setattr(workflow.psutil, "wait_procs", lambda processes, timeout: ([], []))
    runtime = FakeRuntime()
    runtime.cancel = calls.append
    workflow._stop_branch_locked(root, "CANCELLED", "test", runtime, safe_path, {"pid": 456, "create_time": 2.})
    assert calls == []
    workflow._stop_branch_locked(root, "CANCELLED", "test", runtime, safe_path, identity)
    assert calls == ["suspend", "late-container"]
    assert load_state(root)["status"] == "CANCELLED"


def test_module_cli_status_and_cancel(tmp_path, capsys):
    from src.agents.computational_experiment_agent.run import main
    assert main(["--run-dir", str(tmp_path), "status"]) == 0
    assert main(["--run-dir", str(tmp_path), "cancel"]) == 0
    assert load_state(tmp_path / "computation")["cancel_requested"] is True


def test_interpretation_rejects_invented_numbers(tmp_path):
    with pytest.raises(ValueError, match="numeric_literals"):
        analyze(ode_plan(), execution_record(tmp_path), observations(),
            llm_call=lambda *args, **kwargs: {"discussion": "The measured output is 99.", "metric_ids": ["final_concentration"]})


@pytest.mark.parametrize("case,expected", [("deadline", "BUDGET_EXHAUSTED"), ("cancel", "CANCELLED"),
    ("parent_exit", "CANCELLED"), ("worker_exit", "PARTIAL")])
def test_supervisor_bounds_worker_without_waiting_for_a(tmp_path, monkeypatch, case, expected):
    from src.pipeline import computational_workflow as workflow
    identity = {"pid": 123, "create_time": 1.}
    parent = {"pid": 456, "create_time": 2.}
    root = tmp_path / "computation"
    update_state(root, owner=identity, controller_started_at="2000-01-01T00:00:00Z", budget=DEFAULT_BUDGET,
        cancel_requested=case == "cancel")
    monkeypatch.setattr(workflow, "owner_alive", lambda candidate: not (
        (case == "worker_exit" and candidate == identity) or (case == "parent_exit" and candidate == parent)))
    calls = []
    monkeypatch.setattr(workflow, "stop_branch", lambda *args, **kwargs: calls.append(args))
    workflow.watch_branch(tmp_path, identity, parent)
    assert calls[0][1] == expected


def test_supervisor_observes_main_cancellation_while_a_is_busy(tmp_path, monkeypatch):
    from src.pipeline import computational_workflow as workflow
    from src.pipeline.science_run import science_run_paths
    identity = {"pid": 123, "create_time": 1.}
    update_state(tmp_path / "computation", owner=identity, budget=DEFAULT_BUDGET)
    paths = science_run_paths(tmp_path)
    paths.state.touch()
    monkeypatch.setattr(workflow, "owner_alive", lambda identity: True)
    monkeypatch.setattr(workflow, "load_science_run", lambda paths: ({}, {"cancellation": {"requested_at": "now"}}))
    calls = []
    monkeypatch.setattr(workflow, "stop_branch", lambda *args, **kwargs: calls.append(args))
    workflow.watch_branch(tmp_path, identity)
    assert calls[0][1:] == ("CANCELLED", "main_workflow_cancelled")


@pytest.mark.skipif(os.environ.get("QWENSCI_REAL_COMPUTATION_TESTS") != "1", reason="requires built Docker image")
@pytest.mark.parametrize("backend", ["python_project", "mathir", "pyscf"])
def test_real_reference_and_chemistry_execution(tmp_path, backend):
    plan = chemistry_plan() if backend == "pyscf" else ode_plan(backend)
    controller = ComputationalOrchestrator(tmp_path, llm_call=callback(plan))
    state = controller.start(context=context(), mode="run")
    assert state["status"] == "COMPLETED", state
    handoff = verify_manifest(tmp_path / "computation" / "manifest.json")
    result = handoff["results"][0]
    assert result["validation_status"] == "QUALIFIED", result
    if backend == "pyscf":
        assert -1.2 < result["metrics"][0]["value"] < -1.0
        assert any(row["check_id"] == "method_sensitivity" and row["value"] > 0 for row in result["error_analysis"])
    else:
        assert abs(result["metrics"][0]["value"] - math.exp(-1)) < 1e-6
        assert any(row["check_id"] == "reference_or_invariant" for row in result["error_analysis"])
    count = state["execution_count"]
    assert controller.resume()["execution_count"] == count


@pytest.mark.skipif(os.environ.get('QWENSCI_REAL_COMPUTATION_TESTS') != '1', reason='requires built Docker image')
def test_real_generated_pyscf_mp2_and_properties(tmp_path):
    controller = ComputationalOrchestrator(tmp_path, llm_call=callback(generated_chemistry_plan(), GENERATED_PYSCF_CODE))
    state = controller.start(context=context(), mode='run')
    assert state['status'] == 'COMPLETED', state
    result = verify_manifest(tmp_path / 'computation/manifest.json')['results'][0]
    assert result['validation_status'] == 'QUALIFIED', result
    energies = [metric['value'] for metric in result['metrics'] if metric['metric_id'] == 'energy']
    dipoles = [metric['value'] for metric in result['metrics'] if metric['metric_id'] == 'dipole']
    assert len(energies) == len(dipoles) == 2
    assert all(-1.3 < energy < -1.1 for energy in energies)
    assert all(abs(dipole) < 1e-8 for dipole in dipoles)
    assert state['execution_count'] == 1
    assert controller.resume()['execution_count'] == 1


@pytest.mark.skipif(os.environ.get("QWENSCI_REAL_COMPUTATION_TESTS") != "1", reason="requires built Docker image")
@pytest.mark.parametrize("case,expected", [("forged_completion", "TIMEOUT"), ("output_link", "FAILED"), ("cancel", "CANCELLED")])
def test_real_runtime_stops_and_rejects_unsafe_outputs(tmp_path, case, expected):
    import time
    code = "from pathlib import Path\nimport time\n"
    if case == "output_link":
        code += "Path('/output/escape').symlink_to('/etc/passwd')\n"
    else:
        code += "Path('/output/completed').write_text('success')\ntime.sleep(60)\n"
    implementation_dir = tmp_path / "implementation-v001"
    implementation = build_project(ode_plan(), implementation_dir, callback(code=code), environment_id="qwensci-computation:py312-v1")
    input_dir = tmp_path / "inputs"
    input_dir.mkdir()
    request = ExecutionRequest("CE001", 1, 1, "formal", ("python", "-m", "src.run_experiment"),
        implementation["environment_id"], implementation_dir / "project", input_dir, tmp_path / "execution-001",
        binding(), 15., 1, 1024, True)
    runtime = DockerRuntime()
    started = time.monotonic()
    names = []
    record = runtime.run(request, RunAuthorization("auth", binding(), DEFAULT_BUDGET),
        cancel=lambda: case == "cancel" and time.monotonic() - started >= 8,
        on_started=names.append)
    assert record["status"] == expected, record
    assert names
    assert runtime.invoke(["inspect", names[0]], cleanup=True).returncode != 0
    assert runtime.invoke(["volume", "inspect", names[0] + "-output"], cleanup=True).returncode != 0
