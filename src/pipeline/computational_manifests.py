"""Seal and verify branch evidence, including all execution and result dependencies."""

from pathlib import Path

from src.agents.computational_experiment_agent.artifacts import read_json, record, safe_path
from src.agents.computational_experiment_agent.contracts import require_contract
from src.pipeline.science_run import atomic_write_json, file_sha256


def write_manifest(root: Path, handoff: dict) -> Path:
    require_contract(handoff)
    atomic_write_json(root / "author_handoff.json", handoff)
    references = {item["path"]: item for item in handoff["artifact_refs"]}
    payload = {"schema_version": "computational_manifest_v1", "source_binding": handoff["source_binding"],
        "branch_status": handoff["branch_status"], "handoff": record(root, root / "author_handoff.json"),
        "artifacts": list(references.values())}
    atomic_write_json(root / "manifest.json", payload)
    return root / "manifest.json"


def verify_manifest(path: Path, expected_identity: dict | None = None) -> dict:
    root = path.resolve().parent
    manifest = read_json(path)
    if manifest.get("schema_version") != "computational_manifest_v1":
        raise ValueError("unsupported_computational_manifest")
    for item in [manifest["handoff"], *manifest["artifacts"]]:
        candidate = safe_path(root, item["path"])
        if file_sha256(candidate) != item["sha256"]:
            raise ValueError("computational_artifact_modified:" + item["path"])
    handoff = require_contract(read_json(safe_path(root, manifest["handoff"]["path"])))
    if handoff["source_binding"] != manifest["source_binding"] or handoff["branch_status"] != manifest["branch_status"]:
        raise ValueError("manifest_handoff_binding_mismatch")
    for key, value in (expected_identity or {}).items():
        if key in handoff["source_binding"] and str(value) != handoff["source_binding"][key]:
            raise ValueError("computational_source_mismatch:" + key)
    registered = {item["path"] for item in manifest["artifacts"]}
    plans = {(item["experiment_id"], item["protocol_version"]): item for item in handoff["plans"]}
    from src.agents.computational_experiment_agent.domain_registry import validate_scientific_plan
    from src.agents.computational_experiment_agent.capability_registry import get_backend
    for plan in plans.values():
        errors = list(validate_scientific_plan(plan).errors)
        if plan["status"] == "READY":
            errors.extend(get_backend(plan["backend_id"]).validate(plan))
        if errors:
            raise ValueError("sealed_scientific_protocol_invalid:" + ";".join(errors))
    for result in handoff["results"]:
        plan = plans.get((result["experiment_id"], result["protocol_version"]))
        if plan is None:
            raise ValueError("result_without_matching_protocol")
        if any(result[key] != plan[key] for key in ("result_kind", "claim_scope", "source_binding")):
            raise ValueError("result_protocol_semantics_mismatch")
        for entry in result["lineage"]:
            execution_path = Path(entry["execution_path"]).resolve()
            relative = execution_path.relative_to(root).as_posix()
            if relative not in registered:
                raise ValueError("unsealed_execution_record")
            execution = require_contract(read_json(safe_path(root, relative)))
            if Path(execution["output_dir"]).resolve() != execution_path.parent or any(
                Path(execution[field]).resolve() != execution_path.parent / filename
                for field, filename in (("stdout_path", "stdout.log"), ("stderr_path", "stderr.log"))
            ):
                raise ValueError("execution_output_paths_mismatch")
            if execution["source_binding"] != handoff["source_binding"] or any(execution[key] != result[key]
                    for key in ("experiment_id", "protocol_version")) or execution["execution_id"] != entry.get("execution_id") or execution["implementation_version"] != entry.get("implementation_version"):
                raise ValueError("result_execution_binding_mismatch")
            if result["validation_status"] == "QUALIFIED" and execution["status"] != "COMPLETED":
                raise ValueError("qualified_result_without_completed_execution")
            if execution["status"] == "COMPLETED":
                from src.agents.computational_experiment_agent.analysis import analyze
                from src.agents.computational_experiment_agent.capability_registry import get_backend
                from src.agents.computational_experiment_agent.validation import validate_implementation
                implementation_dir = execution_path.parent.parent
                implementation_relative = (implementation_dir / "implementation.json").relative_to(root).as_posix()
                observations_relative = (execution_path.parent / "raw" / "observations.json").relative_to(root).as_posix()
                protocol_relative = (implementation_dir.parent / "plan.json").relative_to(root).as_posix()
                if not {implementation_relative, protocol_relative}.issubset(registered) or (
                    (result["metrics"] or (execution_path.parent / "raw/observations.json").exists()) and observations_relative not in registered
                ):
                    raise ValueError("unsealed_qualification_dependencies")
                implementation = require_contract(read_json(safe_path(root, implementation_relative)))
                if implementation["implementation_version"] != execution["implementation_version"]:
                    raise ValueError("execution_implementation_version_mismatch")
                if read_json(safe_path(root, protocol_relative)) != plan:
                    raise ValueError("handoff_protocol_differs_from_sealed_protocol")
                if not validate_implementation(plan, implementation, implementation_dir / "project").passed:
                    raise ValueError("sealed_implementation_invalid")
                try:
                    observations = get_backend(plan["backend_id"]).parse(execution)
                except (ValueError, OSError, KeyError):
                    if result["validation_status"] == "QUALIFIED" or result["metrics"]:
                        raise
                    observations = {}
                checked = analyze(plan, execution, observations)
                for field in ("metrics", "checks", "uncertainty", "error_analysis", "validation_status", "hypothesis_relation",
                    "execution_status", "result_kind", "claim_scope", "lineage"):
                    if checked[field] != result[field]:
                        raise ValueError("qualification_differs_from_raw_execution:" + field)
                if not set(checked["unresolved_items"]).issubset(result["unresolved_items"]) or (
                    result["validation_status"] == "QUALIFIED" and checked["unresolved_items"] != result["unresolved_items"]
                ):
                    raise ValueError("qualification_differs_from_raw_execution:unresolved_items")
    from src.result_figures.validation import verify_figure_manifest

    expected_executions = {row["execution_id"] for result in handoff["results"] for row in result["lineage"]}
    for artifact in manifest["artifacts"]:
        if artifact.get("role") != "result_figures":
            continue
        figure_manifest = verify_figure_manifest(safe_path(root, artifact["path"]), root=root.parent,
            expected_identity={**handoff["source_binding"], "branch": "computation"})
        identity = figure_manifest["source_identity"]
        if identity["execution_id"] not in expected_executions:
            raise ValueError("figure_without_handoff_execution")
        dependencies = [*figure_manifest["source_refs"], *[item for figure in figure_manifest["figures"]
            for item in [*figure["artifacts"], *figure["outputs"]]]]
        for item in dependencies:
            dependency = safe_path(root.parent, item["path"]).relative_to(root).as_posix()
            if dependency not in registered:
                raise ValueError("unsealed_result_figure_dependency")
    return handoff
