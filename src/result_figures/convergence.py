"""Read explicitly registered, already executed refinement studies.

The optional study only describes saved dependencies and an error location. It
never authorizes a solve, estimates missing errors, or compares unrelated runs.
"""

import math
from pathlib import Path

from filelock import FileLock

from src.agents.computational_experiment_agent.artifacts import read_json, record
from src.pipeline.science_run import atomic_write_json

from .contracts import FigureError, FigureSource, digest
from .validation import check_reference


STUDY_SCHEMA = "result_figure_convergence_study_v1"


def register_saved_convergence_study(*, root, version_dir, records):
    """Register saved refinement evidence; never execute or authorize a solver.

    Each record supplies hashed plan/result/execution/qualification references,
    scenario_id, state_id, axis, error_path, error_norm, reference_id and unit.
    An existing study is immutable. Register before qualifying/finalizing the
    parent execution so its figures and finalization seal this study as well.
    """
    root, version_dir = Path(root).resolve(), Path(version_dir).resolve()
    version_dir.relative_to(root)
    if (version_dir.parent / "finalization.json").exists():
        raise FigureError("cannot_register_convergence_after_finalization")
    parent_plan = read_json(version_dir / "simulation_run_plan.json")
    study = {"schema_version": STUDY_SCHEMA, "parent_plan_identity": parent_plan["plan_identity"],
        "records": records}
    probe = FigureSource(root, {}, "QUALIFIED", "NUMERICAL_SIMULATION", [])
    _collect_study(probe, study, parent_plan)
    path = version_dir / "convergence/result_study.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    with FileLock(str(path.parent / ".result-study.lock"), timeout=30):
        if path.exists():
            if read_json(path) != study:
                raise FigureError("convergence_study_already_registered")
        else:
            for reference in probe.source_refs:
                check_reference(root, reference)
            atomic_write_json(path, study)
    return record(root, path)


def collect_saved_convergence(source, version_dir, parent_plan, *, frozen_refs=None):
    if frozen_refs is None:
        study_path = version_dir / "convergence/result_study.json"
        if not study_path.is_file():
            return
        study_ref = {**record(source.root, study_path), "role": "convergence_study"}
    else:
        study_ref = next((item for item in frozen_refs if item["role"] == "convergence_study"), None)
        if study_ref is None:
            return
    study = read_json(check_reference(source.root, study_ref))
    source.source_refs.append(study_ref)
    _collect_study(source, study, parent_plan)


def _collect_study(source, study, parent_plan):
    from src.agents.quantitative_modeling.pde.convergence import build_refinement_plans
    from src.agents.quantitative_modeling.result_qualification import qualify_simulation_result
    from src.agents.quantitative_modeling.run_plan import validate_simulation_run_plan

    validate_simulation_run_plan(parent_plan)
    if study.get("schema_version") != STUDY_SCHEMA or study.get("parent_plan_identity") != parent_plan["plan_identity"]:
        raise FigureError("convergence_study_parent_mismatch")
    if parent_plan.get("execution_ir", {}).get("kind") != "PDE":
        raise FigureError("convergence_requires_parent_pde_plan")
    if not isinstance(study.get("records"), list) or not study["records"]:
        raise FigureError("convergence_requires_saved_records")
    parent_document = parent_plan["execution_ir"]["document"]
    seen = set()
    for index, entry in enumerate(study["records"]):
        required = {"plan", "result", "execution", "qualification", "scenario_id", "state_id", "axis", "error_path", "error_norm", "reference_id", "unit"}
        if not isinstance(entry, dict) or set(entry) != required or any(
                not isinstance(entry[name], str) or not entry[name].strip()
                for name in ("scenario_id", "state_id", "axis", "error_norm", "reference_id", "unit")):
            raise FigureError("invalid_convergence_record")
        objects = {}
        for name in ("plan", "result", "execution", "qualification"):
            if not isinstance(entry[name], dict) or set(entry[name]) != {"path", "sha256"}:
                raise FigureError("invalid_convergence_reference")
            reference = {**entry[name], "role": f"convergence_{name}:{index}"}
            objects[name] = read_json(check_reference(source.root, reference), max_bytes=64_000_000)
            source.source_refs.append(reference)
        plan, result, execution, qualification = (objects[name] for name in ("plan", "result", "execution", "qualification"))
        if plan["model_identity"].get("parent_plan_identity") != parent_plan["plan_identity"] or any(
                item["plan_identity"] != plan["plan_identity"] or item["model_identity"] != plan["model_identity"]
                for item in (result, execution, qualification)) or any(
                item["execution_id"] != execution["execution_id"] for item in (result, qualification)):
            raise FigureError("convergence_execution_binding_mismatch")
        validate_simulation_run_plan(plan)
        document = plan["execution_ir"]["document"]
        grid_multiplier = (document["grid"]["nx"] - 1) / (parent_document["grid"]["nx"] - 1)
        parent_step = parent_document.get("solver_options", {}).get("time_step")
        time_divisor = parent_step / document["solver_options"]["time_step"] if parent_step is not None else 1
        rounded_divisor = round(time_divisor)
        if grid_multiplier < 1 or not grid_multiplier.is_integer() or rounded_divisor < 1 or not math.isclose(
                time_divisor, rounded_divisor, rel_tol=1e-12, abs_tol=1e-12):
            raise FigureError("convergence_invalid_refinement_levels")
        expected = build_refinement_plans(parent_plan, grid_multipliers=(int(grid_multiplier),), time_step_divisors=(rounded_divisor,))[0]
        if plan != expected:
            raise FigureError("convergence_refinement_changed_scientific_plan")
        checked = qualify_simulation_result({**execution, "scenario_results": result["scenario_results"]},
            hypothesis_relation=qualification["hypothesis_relation"], required_validation_checks=plan["qualification_requirements"])
        if checked != qualification or qualification["result_quality"] != "QUALIFIED":
            raise FigureError("convergence_requires_qualified_saved_executions")
        scenario = next(item for item in result["scenario_results"] if item["scenario_id"] == entry["scenario_id"])
        error = scenario["result"]
        if not isinstance(entry["error_path"], list) or len(entry["error_path"]) < 2 or entry["error_path"][0] != "verification" or any(
                not isinstance(part, str) or not part for part in entry["error_path"]):
            raise FigureError("convergence_requires_saved_verification_error")
        for part in entry["error_path"]:
            error = error[part]
        if isinstance(error, bool) or not isinstance(error, (int, float)) or not math.isfinite(error) or error < 0:
            raise FigureError("convergence_error_must_be_finite_nonnegative")
        field = next((field for field in document["fields"] if field["id"] == entry["state_id"]), None)
        if field is None or (field.get("unit") and field["unit"] != entry["unit"]):
            raise FigureError("convergence_field_or_unit_mismatch")
        axis = entry["axis"]
        if axis == "time_step":
            step = document["solver_options"]["time_step"]
            fixed = document["grid"]
        elif axis in {"x", "y", "z"}:
            bounds = document["spatial_domain"][axis]
            step = (bounds[1] - bounds[0]) / (document["grid"]["n" + axis] - 1)
            fixed = document.get("solver_options", {})
        else:
            raise FigureError("unsupported_convergence_axis")
        check_id = ":".join((entry["reference_id"], entry["error_norm"], axis, entry["scenario_id"], digest(fixed)[:12]))
        key = (entry["state_id"], entry["unit"], check_id, step)
        if key in seen:
            raise FigureError("duplicate_convergence_resolution")
        seen.add(key)
        source.convergence.append({"condition_id": execution["execution_id"] + ":" + entry["scenario_id"],
            "state_id": entry["state_id"], "unit": entry["unit"], "step": step, "error": error,
            "check_id": check_id,
            "axis_label": "Time step" if axis == "time_step" else "Grid spacing " + axis,
            "selection": "Saved verification errors for registered qualified refinement executions; " + entry["error_norm"]})
