"""Independent control process started alongside ExperimentDesign A."""

import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import psutil
from filelock import FileLock

from src.pipeline.computational_state import load_state, owner_alive, request_cancel, update_state
from src.pipeline.science_run import load_science_run, science_run_paths, utc_now


def computation_mode(metadata: dict) -> str:
    return str(metadata.get("immutable_inputs", {}).get("options", {}).get("computation", {}).get("mode", "off"))


def start_branch(run_dir: Path, *, force_resume: bool = False):
    metadata, _ = load_science_run(science_run_paths(run_dir))
    if computation_mode(metadata) == "off":
        raise ValueError("computational_branch_disabled_in_original_run")
    root = run_dir / "computation"
    root.mkdir(parents=True, exist_ok=True)
    with FileLock(str(root / ".launch.lock"), timeout=5), FileLock(str(root / ".stop.lock"), timeout=30):
        state = load_state(root)
        terminal = {"COMPLETED", "PLANNED", "NEEDS_INPUT", "BUDGET_EXHAUSTED", "CANCELLED"}
        if not force_resume:
            terminal.add("ENVIRONMENT_UNAVAILABLE")
        if state.get("status") in terminal or owner_alive(state.get("owner") or {}):
            return None
        from src.config import load_config
        from src.agents.computational_experiment_agent.orchestrator import DEFAULT_BUDGET
        config = load_config(str(science_run_paths(run_dir).config_snapshot))
        settings = config.get("computational_experiments", {})
        limits = {**DEFAULT_BUDGET, **settings.get("iteration", {}), **settings.get("runtime", {})}
        limits = {key: limits[key] for key in DEFAULT_BUDGET}
        from src.agents.computational_experiment_agent.contracts import validate_budget
        if errors := validate_budget(limits):
            raise ValueError("invalid_computation_budget:" + ";".join(errors))
        if settings.get("runtime", {}).get("backend", "docker") != "docker" or settings.get("runtime", {}).get("max_parallel_experiments", 1) != 1:
            raise ValueError("computation_v1_requires_docker_and_one_active_experiment")
        with (root / "controller.log").open("ab") as log:
            process = subprocess.Popen([sys.executable, "-m", "src.agents.computational_experiment_agent.run",
                "--run-dir", str(run_dir), "worker"], cwd=Path(__file__).resolve().parents[2],
                stdout=log, stderr=log, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        identity = {"pid": process.pid, "create_time": psutil.Process(process.pid).create_time()}
        update_state(root, owner=identity, budget=limits,
            controller_started_at=utc_now(), controller_prior_used_wall_seconds=state.get("used_wall_seconds", 0),
            cancel_requested=False)
        try:
            with (root / "supervisor.log").open("ab") as log:
                subprocess.Popen([sys.executable, "-m", "src.agents.computational_experiment_agent.run",
                    "--run-dir", str(run_dir), "--owner-pid", str(identity["pid"]),
                    "--owner-create-time", str(identity["create_time"]),
                    "--parent-pid", str(os.getpid()), "--parent-create-time", str(psutil.Process().create_time()),
                    "watch"], cwd=Path(__file__).resolve().parents[2], stdout=log, stderr=log,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        except Exception:
            from src.agents.computational_experiment_agent.execution.docker_runtime import DockerRuntime
            from src.agents.computational_experiment_agent.artifacts import safe_path
            _stop_branch_locked(root, "FAILED", "supervisor_launch_failed", DockerRuntime(), safe_path, identity)
            raise
        return process


def stop_branch(root: Path, status: str, reason: str, *, expected_owner: dict | None = None) -> None:
    from src.agents.computational_experiment_agent.execution.docker_runtime import DockerRuntime
    from src.agents.computational_experiment_agent.artifacts import safe_path
    with FileLock(str(root / ".stop.lock"), timeout=30):
        _stop_branch_locked(root, status, reason, DockerRuntime(), safe_path, expected_owner)


def _stop_branch_locked(root: Path, status: str, reason: str, runtime, safe_path, expected_owner: dict | None = None) -> None:
    state = load_state(root)
    identity = state.get("owner") or {}
    if expected_owner is not None and identity != expected_owner:
        return
    if owner_alive(identity):
        process = psutil.Process(identity["pid"])
        if process.pid != os.getpid():
            try:
                process.suspend()
                descendants = process.children(recursive=True)
                for descendant in descendants:
                    try:
                        descendant.terminate()
                    except psutil.NoSuchProcess:
                        pass
                _, surviving = psutil.wait_procs(descendants, timeout=3)
                for descendant in surviving:
                    try:
                        descendant.kill()
                    except psutil.NoSuchProcess:
                        pass
                psutil.wait_procs(surviving, timeout=3)
                process.terminate()
                process.wait(timeout=5)
            except psutil.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
            except psutil.NoSuchProcess:
                pass
    state = load_state(root)
    for experiment in state.get("experiments", {}).values():
        if experiment.get("active_container"):
            runtime.cancel(experiment["active_container"])
    used_seconds = state.get("used_wall_seconds", 0)
    started = state.get("budget_session_started_at")
    if started:
        used_seconds += max(0., (datetime.now(timezone.utc) - datetime.fromisoformat(started.replace("Z", "+00:00"))).total_seconds())
    update_state(root, owner=None, status=status, error=reason, used_wall_seconds=used_seconds, budget_session_started_at=None)
    if (root / "context.json").is_file():
        from src.agents.computational_experiment_agent.artifacts import read_json
        from src.agents.computational_experiment_agent.author_handoff import build_handoff
        from src.pipeline.computational_manifests import write_manifest
        plans, results = [], []
        for experiment_id, experiment in state.get("experiments", {}).items():
            protocol = safe_path(root, experiment.get("protocol_path", f"{experiment_id}/protocol-v001/plan.json"))
            if protocol.is_file():
                plans.append(read_json(protocol))
                result = protocol.with_name("result.json")
                if result.is_file():
                    results.append(read_json(result))
        if not plans:
            plans = [read_json(path) for path in root.glob("CE*/protocol-v001/plan.json")]
        write_manifest(root, build_handoff(root, read_json(root / "context.json"), plans, results, status, [reason]))


def watch_branch(run_dir: Path, identity: dict, parent_identity: dict | None = None) -> None:
    root = run_dir / "computation"
    while True:
        state = load_state(root)
        if state.get("owner") != identity:
            return
        if not owner_alive(identity):
            stop_branch(root, "PARTIAL", "controller_interrupted", expected_owner=identity)
            return
        if state.get("cancel_requested"):
            stop_branch(root, "CANCELLED", "user_cancelled_branch", expected_owner=identity)
            return
        paths = science_run_paths(run_dir)
        if paths.state.is_file():
            from src.pipeline.science_run import is_science_cancellation_requested
            _, main_state = load_science_run(paths)
            if is_science_cancellation_requested(main_state):
                stop_branch(root, "CANCELLED", "main_workflow_cancelled", expected_owner=identity)
                return
        if parent_identity and not owner_alive(parent_identity):
            stop_branch(root, "CANCELLED", "main_controller_interrupted", expected_owner=identity)
            return
        started = state.get("controller_started_at")
        if started:
            elapsed = (datetime.now(timezone.utc) - datetime.fromisoformat(started.replace("Z", "+00:00"))).total_seconds()
            remaining = state.get("budget", {}).get("max_wall_seconds", 3600) - state.get("controller_prior_used_wall_seconds", 0)
            if elapsed >= max(0., remaining):
                stop_branch(root, "BUDGET_EXHAUSTED", "branch_wall_deadline_exceeded", expected_owner=identity)
                return
        time.sleep(.2)


def join_branch(run_dir: Path, process=None, *, cancel=None) -> Path | None:
    root = run_dir / "computation"
    while (process is not None and process.poll() is None) or owner_alive(load_state(root).get("owner") or {}):
        state = load_state(root)
        identity = state.get("owner") or {}
        if state.get("cancel_requested") or (cancel and cancel()):
            if identity:
                request_cancel(root)
                stop_branch(root, "CANCELLED", "user_cancelled_branch", expected_owner=identity)
            break
        started = state.get("controller_started_at")
        if started:
            elapsed = (datetime.now(timezone.utc) - datetime.fromisoformat(started.replace("Z", "+00:00"))).total_seconds()
            limit = state.get("budget", {}).get("max_wall_seconds", 3600)
            if elapsed >= max(0, limit - state.get("controller_prior_used_wall_seconds", 0)):
                if identity:
                    stop_branch(root, "BUDGET_EXHAUSTED", "branch_wall_deadline_exceeded", expected_owner=identity)
                break
        time.sleep(.2)
    manifest = root / "manifest.json"
    if manifest.is_file():
        from src.pipeline.computational_manifests import verify_manifest
        try:
            verify_manifest(manifest)
        except Exception as error:
            update_state(root, status="FAILED", error="handoff_verification_failed:" + str(error))
            return None
        return manifest
    return None


def worker(run_dir: Path) -> dict:
    from omegaconf import OmegaConf
    from src.config import load_config
    from src.agents.experiment_design_agent.llm_json import build_default_json_llm_call
    from src.agents.computational_experiment_agent.intake import build_context
    from src.agents.computational_experiment_agent.orchestrator import ComputationalOrchestrator, DEFAULT_BUDGET

    root = run_dir / "computation"
    with FileLock(str(root / ".launch.lock"), timeout=30):
        pass
    paths = science_run_paths(run_dir)
    metadata, state = load_science_run(paths)
    options = metadata["immutable_inputs"]["options"]
    mode = computation_mode(metadata)
    if mode == "off":
        return {"status": "DISABLED"}
    config = load_config(str(paths.config_snapshot))
    settings = OmegaConf.to_container(config.get("computational_experiments", {}), resolve=True)
    budget = {**DEFAULT_BUDGET, **settings.get("iteration", {}), **settings.get("runtime", {})}
    budget = {key: budget[key] for key in DEFAULT_BUDGET}
    callback = build_default_json_llm_call(config=config, model=options.get("computation", {}).get("model"))
    controller = ComputationalOrchestrator(run_dir, llm_call=callback, analysis_llm_call=callback,
        environment_id=settings.get("runtime", {}).get("environment_id", "qwensci-computation:py312-v1"),
        figure_settings=OmegaConf.to_container(config.get("result_figures", {}), resolve=True))
    try:
        context = build_context(science_run_id=metadata["science_run_id"],
            idea_manifest_path=Path(state["stages"]["idea"]["result_manifest_path"]),
            survey_manifest_path=Path(state["stages"]["survey"]["result_manifest_path"]),
            discipline_ids=tuple(options["discipline_ids"]), budget=budget,
            inputs=settings.get("inputs", []), constraints=settings.get("constraints", {}))
        if (root / "context.json").is_file():
            from src.agents.computational_experiment_agent.artifacts import read_json
            if read_json(root / "context.json")["source_binding"] != context["source_binding"]:
                raise ValueError("resumed_branch_upstream_source_mismatch")
            return controller.resume()
        return controller.start(context=context, mode=mode, budget=budget,
            max_experiments=settings.get("planning", {}).get("max_experiments", 2),
            enabled_backends=tuple(settings.get("backends", {}).get("enabled", ["mathir", "python_project", "pyscf"])))
    except Exception as error:
        reason = f"{type(error).__name__}:{error}"
        try:
            stop_branch(root, "FAILED", reason)
        except Exception as publication_error:
            update_state(root, owner=None, status="FAILED", error=reason, publication_error=str(publication_error))
        return load_state(root)
