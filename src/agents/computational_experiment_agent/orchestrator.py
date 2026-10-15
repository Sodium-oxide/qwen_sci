"""Resumable controller owning protocols, authorization and qualification."""

import json
import shutil
import uuid
from copy import deepcopy
from pathlib import Path

from filelock import FileLock

from src.agents.experiment_design_agent.llm_json import call_required_json
from src.pipeline.computational_manifests import verify_manifest, write_manifest
from src.pipeline.computational_state import event, load_state, owner, update_state
from src.pipeline.science_run import atomic_write_json, atomic_write_text, file_sha256, utc_now

from .analysis import analyze, render_analysis
from .artifacts import read_json, safe_path
from .author_handoff import build_handoff
from .capability_registry import get_backend
from .code_builder import build_project
from .contracts import ExecutionRequest, require_contract, validate_budget
from .domain_registry import validate_scientific_plan
from .execution.budget import BranchBudget, BudgetExhausted
from .execution.docker_runtime import DockerRuntime
from .execution.runtime import RunAuthorization
from .iteration import next_decision
from .planner import plan_experiments
from .validation import validate_implementation


DEFAULT_BUDGET = {
    "max_wall_seconds": 3600., "max_execution_seconds": 900., "max_total_executions": 12,
    "max_code_repairs": 3, "max_protocol_revisions": 1, "cpu_cores": 4,
    "memory_mb": 4096, "network_enabled": True,
}


class ComputationalOrchestrator:
    def __init__(self, run_dir: str | Path, *, llm_call=None, analysis_llm_call=None, runtime=None,
                 environment_id: str = "qwensci-computation:py312-v1"):
        self.root = Path(run_dir).expanduser().resolve()
        self.branch = self.root / "computation"
        self.llm_call, self.analysis_llm_call = llm_call, analysis_llm_call
        self.runtime = runtime or DockerRuntime()
        self.environment_id = environment_id

    def cancelled(self) -> bool:
        return bool(load_state(self.branch).get("cancel_requested"))

    def start(self, *, context: dict, mode: str, budget: dict | None = None, max_experiments: int = 2,
              enabled_backends: tuple[str, ...] = ("mathir", "python_project", "pyscf")) -> dict:
        if mode not in {"off", "plan", "run"}:
            raise ValueError("computation_mode_must_be_off_plan_or_run")
        if mode == "off":
            return {"mode": "off", "status": "DISABLED"}
        self.branch.mkdir(parents=True, exist_ok=True)
        with FileLock(str(self.branch / ".controller.lock"), timeout=0):
            context = require_contract(context)
            limits = {**DEFAULT_BUDGET, **context["resource_budget"], **(budget or {})}
            if errors := validate_budget(limits):
                raise ValueError("invalid_computation_budget:" + ";".join(errors))
            context["resource_budget"] = limits
            prior = load_state(self.branch)
            if prior.get("mode"):
                if read_json(self.branch / "context.json") != context or prior["mode"] != mode:
                    raise ValueError("existing_branch_inputs_or_mode_differ")
                return self._resume_locked()
            atomic_write_json(self.branch / "context.json", context)
            update_state(self.branch, mode=mode, status="PLANNING", owner=owner(), budget=limits,
                execution_count=0, used_wall_seconds=0., started_at=utc_now(),
                environment_id=self.environment_id, max_experiments=max_experiments,
                enabled_backends=list(enabled_backends), experiments={})
            if mode == "run":
                atomic_write_json(self.branch / "authorization.json", {
                    "authorization_id": uuid.uuid4().hex, "source_binding": context["source_binding"],
                    "resource_budget": limits, "issued_at": utc_now(), "mode": "run"})
            self._stage_inputs(context)
            return self._resume_locked()

    def _stage_inputs(self, context: dict) -> None:
        input_root = self.branch / "inputs"
        input_root.mkdir(parents=True, exist_ok=True)
        for item in context["inputs"]:
            if not {"source_path", "path", "sha256"}.issubset(item):
                raise ValueError("input_requires_explicit_path_and_hash")
            source = Path(item["source_path"]).expanduser().resolve()
            if not source.is_file() or file_sha256(source) != item["sha256"] or source.stat().st_size > 64_000_000:
                raise ValueError("declared_input_unavailable_or_modified")
            destination = safe_path(input_root, item["path"])
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)
            if file_sha256(destination) != item["sha256"]:
                raise ValueError("input_changed_during_staging")
        atomic_write_json(input_root / "input_manifest.json", {"inputs": context["inputs"]})
        declared = {item["path"].replace("\\", "/") for item in context["inputs"]} | {"input_manifest.json"}
        if {path.relative_to(input_root).as_posix() for path in input_root.rglob("*") if path.is_file()} != declared:
            raise ValueError("undeclared_input_file")

    def resume(self) -> dict:
        if not self.branch.is_dir():
            raise ValueError("computational_branch_not_initialized")
        with FileLock(str(self.branch / ".controller.lock"), timeout=0):
            return self._resume_locked()

    def _resume_locked(self) -> dict:
        state = load_state(self.branch)
        if (self.branch / "manifest.json").is_file():
            verify_manifest(self.branch / "manifest.json")
        if state.get("status") in {"COMPLETED", "PLANNED", "NEEDS_INPUT", "BUDGET_EXHAUSTED"} and (self.branch / "manifest.json").is_file():
            verify_manifest(self.branch / "manifest.json")
            return state
        context = require_contract(read_json(self.branch / "context.json"))
        self._stage_inputs(context)
        budget = BranchBudget(self.branch, state["budget"])
        self.environment_id = state["environment_id"]
        update_state(self.branch, owner=owner(), status="RUNNING" if state["mode"] == "run" else "PLANNING")
        plans, results, unresolved = [], [], []
        branch_status = "FAILED"
        try:
            if not state.get("plan_paths"):
                if self.cancelled():
                    return self._publish(context, [], [], "CANCELLED", ["cancelled_before_planning"])
                if budget.remaining() <= 0:
                    raise BudgetExhausted("wall_budget_exhausted_before_planning")
                plans = plan_experiments(context, self.llm_call, max_experiments=state["max_experiments"],
                    enabled_backends=tuple(state["enabled_backends"]))
                paths = []
                for plan in plans:
                    plan_path = self.branch / plan["experiment_id"] / "protocol-v001" / "plan.json"
                    atomic_write_json(plan_path, plan)
                    paths.append(plan_path.relative_to(self.branch).as_posix())
                update_state(self.branch, plan_paths=paths)
                event(self.branch, "PLANS_CREATED", count=len(plans))
            plans = [require_contract(read_json(safe_path(self.branch, path)))
                for path in load_state(self.branch)["plan_paths"]]
            if any(plan["source_binding"] != context["source_binding"] for plan in plans):
                raise ValueError("resumed_plan_source_mismatch")
            if state["mode"] == "plan":
                branch_status = "NEEDS_INPUT" if any(plan["status"] == "NEEDS_INPUT" for plan in plans) else "PLANNED"
                if self.cancelled():
                    branch_status = "CANCELLED"
                elif budget.remaining() <= 0:
                    branch_status = "BUDGET_EXHAUSTED"
                budget.checkpoint()
                return self._publish(context, plans, [], branch_status,
                    [item for plan in plans for item in plan["unresolved_inputs"]])
            record = read_json(self.branch / "authorization.json")
            if record["source_binding"] != context["source_binding"] or record["resource_budget"] != state["budget"] or record["mode"] != "run":
                raise ValueError("persisted_authorization_mismatch")
            authorization = RunAuthorization(record["authorization_id"], context["source_binding"], state["budget"])
            for index, plan in enumerate(plans):
                if self.cancelled():
                    branch_status = "CANCELLED"
                    break
                if plan["status"] == "NEEDS_INPUT":
                    results.append(analyze(plan, None, {}))
                    unresolved.extend(plan["unresolved_inputs"])
                    continue
                try:
                    final_plan, result = self._run_experiment(plan, context, budget, authorization)
                    plans[index] = final_plan
                    results.append(result)
                except BudgetExhausted as failure:
                    branch_status = "BUDGET_EXHAUSTED"
                    unresolved.append(str(failure))
                    break
                except Exception as failure:
                    unresolved.append(plan["experiment_id"] + ":" + type(failure).__name__ + ":" + str(failure))
                    event(self.branch, "EXPERIMENT_FAILED", experiment_id=plan["experiment_id"], error=str(failure))
            if self.cancelled():
                branch_status = "CANCELLED"
            elif budget.remaining() <= 0:
                branch_status = "BUDGET_EXHAUSTED"
            if branch_status not in {"CANCELLED", "BUDGET_EXHAUSTED"}:
                if any("ENVIRONMENT_UNAVAILABLE" in item.get("unresolved_items", []) for item in results):
                    branch_status = "ENVIRONMENT_UNAVAILABLE"
                elif any(plan["status"] == "NEEDS_INPUT" for plan in plans):
                    branch_status = "NEEDS_INPUT"
                elif len(results) == len(plans) and all(item["validation_status"] == "QUALIFIED" for item in results):
                    branch_status = "COMPLETED"
                else:
                    branch_status = "PARTIAL" if results else "FAILED"
        except BudgetExhausted as failure:
            branch_status, unresolved = "BUDGET_EXHAUSTED", [str(failure)]
        except Exception as failure:
            unresolved.append(type(failure).__name__ + ":" + str(failure))
            event(self.branch, "BRANCH_FAILED", error=str(failure))
        finally:
            if load_state(self.branch).get("owner"):
                budget.checkpoint()
        return self._publish(context, plans, results, branch_status, unresolved)

    def _run_experiment(self, plan: dict, context: dict, budget: BranchBudget, authorization: RunAuthorization) -> tuple[dict, dict]:
        requested_id = plan["experiment_id"]
        experiment = load_state(self.branch).get("experiments", {}).get(requested_id, {})
        if experiment.get("protocol_path"):
            plan = require_contract(read_json(safe_path(self.branch, experiment["protocol_path"])))
        if plan["experiment_id"] != requested_id or plan["source_binding"] != context["source_binding"] or plan["experiment_id"] not in {
            read_json(safe_path(self.branch, path))["experiment_id"] for path in load_state(self.branch).get("plan_paths", [])
        }:
            raise ValueError("resumed_protocol_identity_mismatch")
        if experiment.get("accepted_result_path"):
            accepted = require_contract(read_json(safe_path(self.branch, experiment["accepted_result_path"])))
            if any(accepted[key] != plan[key] for key in ("source_binding", "experiment_id", "protocol_version")) or accepted["validation_status"] != "QUALIFIED":
                raise ValueError("accepted_result_identity_or_status_mismatch")
            return plan, accepted
        if experiment.get("execution_path") and Path(experiment["execution_path"]).is_file():
            execution_path = Path(experiment["execution_path"]).resolve()
            execution_path.relative_to(self.branch)
            recovered = require_contract(read_json(execution_path))
            if Path(recovered["output_dir"]).resolve() != execution_path.parent or any(
                Path(recovered[field]).resolve() != execution_path.parent / filename
                for field, filename in (("stdout_path", "stdout.log"), ("stderr_path", "stderr.log"))
            ):
                raise ValueError("recovered_execution_output_paths_mismatch")
            if any(recovered[key] != plan[key] for key in ("source_binding", "experiment_id", "protocol_version")) or recovered["authorization_id"] != authorization.authorization_id or recovered["implementation_version"] != experiment.get("implementation_version"):
                raise ValueError("recovered_execution_source_mismatch")
            if recovered["status"] == "COMPLETED":
                recovered_result = analyze(plan, recovered, get_backend(plan["backend_id"]).parse(recovered))
                if recovered_result["validation_status"] == "QUALIFIED":
                    result_path = execution_path.parents[1].parent / "result.json"
                    atomic_write_json(result_path, recovered_result)
                    atomic_write_text(result_path.with_name("analysis.md"), render_analysis(plan, recovered_result))
                    self._checkpoint(plan, accepted_result_path=result_path.relative_to(self.branch).as_posix(), active_container=None)
                    event(self.branch, "COMPLETED_EXECUTION_RECOVERED", execution_id=recovered["execution_id"])
                    return plan, recovered_result
        if experiment.get("active_container"):
            self.runtime.cancel(experiment["active_container"])
            event(self.branch, "INTERRUPTED_EXECUTION_CANCELLED", container_name=experiment["active_container"])
        repairs, revisions = int(experiment.get("repairs", 0)), int(experiment.get("revisions", 0))
        implementation_version = int(experiment.get("implementation_version", 1))
        diagnosis, previous_project = experiment.get("diagnosis", {}), None
        while True:
            if self.cancelled():
                return plan, analyze(plan, None, {})
            if budget.remaining() <= 0:
                raise BudgetExhausted("wall_budget_exhausted")
            self._stage_inputs(context)
            backend = get_backend(plan["backend_id"])
            if errors := [*validate_scientific_plan(plan).errors, *backend.validate(plan)]:
                raise ValueError("protocol_invalid:" + ";".join(errors))
            plan_dir = self.branch / plan["experiment_id"] / f"protocol-v{plan['protocol_version']:03d}"
            atomic_write_json(plan_dir / "plan.json", plan)
            impl_dir = plan_dir / f"implementation-v{implementation_version:03d}"
            try:
                if (impl_dir / "implementation.json").is_file():
                    implementation = require_contract(read_json(impl_dir / "implementation.json"))
                else:
                    implementation = build_project(plan, impl_dir, self.llm_call,
                        environment_id=self.environment_id, implementation_version=implementation_version,
                        diagnosis=diagnosis, previous_project=previous_project)
                if errors := validate_implementation(plan, implementation, impl_dir / "project").errors:
                    raise ValueError("implementation_invalid:" + ";".join(errors))
            except (ValueError, SyntaxError) as failure:
                if not backend.uses_generated_code(plan) or repairs >= plan["resource_budget"]["max_code_repairs"]:
                    raise
                repairs += 1
                implementation_version += 1
                diagnosis = {"engineering_error": str(failure)}
                self._checkpoint(plan, repairs=repairs, revisions=revisions, implementation_version=implementation_version, diagnosis=diagnosis)
                event(self.branch, "REPAIR_IMPLEMENTATION", reason=str(failure))
                continue
            number, timeout = budget.reserve()
            execution_dir = impl_dir / f"execution-{number:03d}"
            request = ExecutionRequest(experiment_id=plan["experiment_id"], protocol_version=plan["protocol_version"],
                implementation_version=implementation_version, purpose="formal", command=("python", "-m", "src.run_experiment"),
                environment_id=implementation["environment_id"], project_dir=impl_dir / "project", input_dir=self.branch / "inputs",
                output_dir=execution_dir, source_binding=context["source_binding"], max_wall_seconds=timeout,
                cpu_cores=authorization.resource_budget["cpu_cores"], memory_mb=authorization.resource_budget["memory_mb"],
                network_enabled=authorization.resource_budget["network_enabled"])
            self._checkpoint(plan, repairs=repairs, revisions=revisions, implementation_version=implementation_version,
                execution_path=str(execution_dir / "execution.json"), active_container=None)
            execution = self.runtime.run(request, authorization, cancel=self.cancelled,
                on_started=lambda name: self._checkpoint(plan, active_container=name))
            atomic_write_json(execution_dir / "execution.json", execution)
            self._checkpoint(plan, active_container=None)
            try:
                observations = backend.parse(execution)
            except (ValueError, OSError, KeyError) as failure:
                observations, diagnosis = {}, {"parsing_error": str(failure)}
            result = analyze(plan, execution, observations)
            atomic_write_json(execution_dir / "parsed_result.json", observations)
            atomic_write_json(execution_dir / "qualification.json", result)
            atomic_write_json(plan_dir / "result.json", result)
            atomic_write_text(plan_dir / "analysis.md", render_analysis(plan, result))
            decision = next_decision(plan, execution, result, repairs=repairs, revisions=revisions, remaining_seconds=budget.remaining())
            event(self.branch, "ITERATION_DECISION", experiment_id=plan["experiment_id"], decision=decision.kind, reason=decision.reason)
            budget.checkpoint()
            if decision.kind == "ACCEPT_RESULT":
                if self.analysis_llm_call:
                    try:
                        result = analyze(plan, execution, observations, llm_call=self.analysis_llm_call)
                    except Exception as failure:
                        event(self.branch, "INTERPRETATION_UNAVAILABLE", error=str(failure))
                atomic_write_json(plan_dir / "result.json", result)
                atomic_write_text(plan_dir / "analysis.md", render_analysis(plan, result))
                self._checkpoint(plan, accepted_result_path=(plan_dir / "result.json").relative_to(self.branch).as_posix())
                return plan, result
            if decision.kind == "REPAIR_IMPLEMENTATION":
                repairs += 1
                implementation_version += 1
                previous_project = impl_dir / "project"
                diagnosis = {**diagnosis, "result": result, "stderr": Path(execution["stderr_path"]).read_text(encoding="utf-8")[-6000:]}
                self._checkpoint(plan, repairs=repairs, implementation_version=implementation_version, diagnosis=diagnosis)
                continue
            if decision.kind == "REFINE_NUMERICS":
                try:
                    plan = self._refine(plan, result)
                except Exception as failure:
                    result["unresolved_items"].append("refinement_unavailable:" + str(failure))
                    atomic_write_json(plan_dir / "result.json", result)
                    return plan, result
                revisions += 1
                implementation_version = 1
                self._checkpoint(plan, revisions=revisions, implementation_version=1, diagnosis={})
                continue
            return plan, result

    def _refine(self, plan: dict, result: dict) -> dict:
        response = call_required_json(self.llm_call, "Refine numerical settings to address failed diagnostics. "
            "Return {kind: REFINE_NUMERICS|REVISE_PROTOCOL, reason: string, method_spec: object, comparisons: array}. "
            "Preserve model, hypothesis, endpoints, thresholds and condition identities. "
            "Numerical solver changes use REFINE_NUMERICS; scientific method/basis changes use REVISE_PROTOCOL. "
            "Never revise a qualified negative result.\n" + json.dumps({"plan": plan, "result": result}), stage="computational_refinement")
        if set(response) != {"kind", "reason", "method_spec", "comparisons"} or response["kind"] not in {"REFINE_NUMERICS", "REVISE_PROTOCOL"}:
            raise ValueError("invalid_refinement")
        revised = deepcopy(plan)
        revised.update(method_spec=response["method_spec"], comparisons=response["comparisons"], protocol_version=plan["protocol_version"] + 1)
        if {row["condition_id"] for row in revised["comparisons"]} != {row["condition_id"] for row in plan["comparisons"]}:
            raise ValueError("refinement_cannot_change_condition_identity")
        for original, updated in zip(plan["comparisons"], revised["comparisons"], strict=True):
            if any(original[key] != updated[key] for key in ("condition_id", "role", "definition")):
                raise ValueError("refinement_cannot_change_comparison_meaning")
        numerical_fields = {"solver", "solver_options", "tolerances", "discretization", "convergence_plan",
            "scf_tolerance", "max_scf_cycles", "time_step", "samples", "replicates"}
        if response["kind"] == "REFINE_NUMERICS":
            changed = {key for key in set(plan["method_spec"]) | set(revised["method_spec"])
                if plan["method_spec"].get(key) != revised["method_spec"].get(key)}
            if changed - numerical_fields:
                raise ValueError("scientific_method_change_requires_protocol_revision")
            for original, updated in zip(plan["comparisons"], revised["comparisons"], strict=True):
                changed = {key for key in set(original["overrides"]) | set(updated["overrides"])
                    if original["overrides"].get(key) != updated["overrides"].get(key)}
                if changed - numerical_fields:
                    raise ValueError("scientific_condition_change_requires_protocol_revision")
        if errors := validate_scientific_plan(revised).errors:
            raise ValueError("invalid_revised_protocol:" + ";".join(errors))
        path = self.branch / plan["experiment_id"] / f"protocol-v{revised['protocol_version']:03d}"
        atomic_write_json(path / "plan.json", revised)
        atomic_write_json(path / "revision.json", {"kind": response["kind"], "reason": response["reason"],
            "prior_protocol_version": plan["protocol_version"], "prior_result": result})
        event(self.branch, response["kind"], reason=response["reason"], protocol_version=revised["protocol_version"])
        return require_contract(revised)

    def _checkpoint(self, plan: dict, **changes) -> None:
        experiments = load_state(self.branch).get("experiments", {})
        current = experiments.get(plan["experiment_id"], {})
        current.update(changes, protocol_path=f"{plan['experiment_id']}/protocol-v{plan['protocol_version']:03d}/plan.json")
        experiments[plan["experiment_id"]] = current
        update_state(self.branch, experiments=experiments)

    def _publish(self, context: dict, plans: list, results: list, status: str, unresolved: list) -> dict:
        unresolved = list(dict.fromkeys([*unresolved, *[item for result in results for item in result["unresolved_items"]]]))
        manifest = write_manifest(self.branch, build_handoff(self.branch, context, plans, results, status, unresolved))
        return update_state(self.branch, status=status, owner=None, manifest_path=str(manifest),
            unresolved_items=unresolved, result_ids=[item["experiment_id"] for item in results], budget_session_started_at=None)
