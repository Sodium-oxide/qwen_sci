"""Build immutable, versioned projects with host-owned configs and file manifests."""

import ast
import json
from pathlib import Path

from src.agents.experiment_design_agent.llm_json import call_required_json
from src.pipeline.science_run import file_sha256

from .artifacts import atomic_write_json, atomic_write_text, safe_path
from .capability_registry import get_backend
from .contracts import require_contract


def build_project(plan: dict, directory: Path, llm_call, *, environment_id: str,
                  implementation_version: int = 1, diagnosis: dict | None = None,
                  previous_project: Path | None = None) -> dict:
    backend = get_backend(plan["backend_id"])
    errors = backend.validate(plan)
    if errors:
        raise ValueError(";".join(errors))
    files = backend.files(plan)
    if backend.uses_generated_code(plan):
        previous = {}
        if previous_project:
            previous = {path.relative_to(previous_project).as_posix(): safe_path(previous_project,
                path.relative_to(previous_project).as_posix()).read_text(encoding="utf-8")
                for path in previous_project.rglob("*.py") if path.stat().st_size < 100_000}
            if sum(len(value.encode()) for value in previous.values()) > 1_000_000:
                raise ValueError("previous_project_prompt_size_exceeded")
        prompt = "\n".join([
            "Implement this exact scientific protocol as a reproducible Python project.",
            "Return JSON {files: [{path, purpose, content}], dependencies: [...]}. No trusted statuses.",
            "Dependencies must already exist in the assigned image; do not install packages in the experiment.",
            "Entry: src/run_experiment.py. Read configs/experiment.json; write /output/observations.json.",
            "Observations: {metrics: [{metric_id, condition_id, value, unit}], traces: [...]}; numerical values only.",
            "Include raw traces, repeat samples and reference cases needed for independent host verification.",
            "Trace rows: {condition_id, times: [...], values: [...]} for scalar ODE validation.",
            "Every endpoint observation_binding selects raw records by condition_id and optional state_id. Emit the declared raw source and values.",
            "Inputs are in /inputs; never invent an unavailable dataset. All conditions/endpoints must be computed.",
            "Implement errors and convergence as declared. Tests cannot replace independent reference validation.",
            backend.generation_guidance(plan),
            json.dumps({"plan": plan, "diagnosis": diagnosis or {}, "previous_files": previous}, ensure_ascii=False),
        ])
        proposed = call_required_json(llm_call, prompt, stage="computational_code_builder")
        rows = proposed.get("files", [])
        if not isinstance(rows, list) or not 1 <= len(rows) <= 40:
            raise ValueError("invalid_project_file_count")
        files = {}
        normalized_paths = set()
        for row in rows:
            relative, content = row["path"], row["content"]
            safe_path(directory / "project", relative)
            normalized = relative.replace("\\", "/").casefold()
            if normalized in normalized_paths:
                raise ValueError("aliased_project_file")
            normalized_paths.add(normalized)
            if relative in files or not isinstance(content, str) or len(content.encode()) > 250_000:
                raise ValueError("duplicate_or_oversized_project_file")
            if normalized.startswith(("configs/", "inputs/")) or normalized in {"environment.lock", "pyproject.toml"}:
                raise ValueError("generated_file_conflicts_with_host_configuration")
            safe_path(directory / "project", relative)
            if relative.endswith(".py"):
                ast.parse(content, filename=relative)
            files[relative] = content
        dependencies = proposed.get("dependencies", [])
        if not isinstance(dependencies, list) or any(not isinstance(value, str) for value in dependencies):
            raise ValueError("invalid_dependency_request")
    else:
        dependencies = ["numpy", "scipy", "jsonschema"] + (["pyscf"] if plan["backend_id"] == "pyscf" else [])
    if "src/run_experiment.py" not in files:
        raise ValueError("missing_project_entrypoint")
    files["configs/experiment.json"] = json.dumps(plan, ensure_ascii=False, indent=2, allow_nan=False)
    files["configs/smoke.json"] = json.dumps({"protocol": "experiment.json", "purpose": "bounded reference checks"})
    files["environment.lock"] = json.dumps({"image": environment_id, "requested_dependencies": dependencies})
    files["pyproject.toml"] = '[project]\nname = "computational-experiment"\nversion = "0.1.0"\nrequires-python = ">=3.12,<3.13"\n'
    files.setdefault("README.md", "Run in the declared container image with /inputs read-only and /output writable.\n"
        "Command: python -m src.run_experiment\nProtocol: configs/experiment.json\n")
    project = directory / "project"
    if project.exists():
        raise ValueError("implementation_directory_must_be_fresh")
    for relative, content in files.items():
        atomic_write_text(safe_path(project, relative), content)
    implementation = require_contract({"schema_version": "computational_implementation_v1",
        "experiment_id": plan["experiment_id"], "source_binding": plan["source_binding"],
        "protocol_version": plan["protocol_version"], "implementation_version": implementation_version,
        "backend_id": plan["backend_id"], "environment_id": environment_id, "entrypoint": "src/run_experiment.py",
        "files": [{"path": relative, "purpose": "protocol implementation", "sha256": file_sha256(safe_path(project, relative))}
            for relative in sorted(files)], "dependencies": list(dict.fromkeys(dependencies)),
        "input_manifest": {"inputs": plan["inputs"]},
        "output_contract": {"path": "observations.json", "metrics": plan["endpoints"], "trusted_statuses": False}})
    atomic_write_json(directory / "implementation.json", implementation)
    return implementation
