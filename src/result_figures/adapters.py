"""Read frozen experiment data without executing scientific programs."""

import math
from pathlib import Path

from src.agents.computational_experiment_agent.artifacts import read_json, record, safe_path

from .contracts import FigureError, FigureSource, digest


def _reference(source, path, role):
    reference = {**record(source.root, Path(path).resolve()), "role": role}
    if reference not in source.source_refs:
        source.source_refs.append(reference)
    return reference


def _units(model):
    units = {row.get("symbol_id", ""): row.get("unit", "unit not declared") for row in model.get("symbols", [])}
    for row in model.get("symbols", []):
        units[row.get("latex", "")] = row.get("unit", "unit not declared")
    document = model.get("execution_ir", {}).get("document", {})
    for row in document.get("fields", []):
        units[row.get("id", "")] = row.get("unit") or "unit not declared"
    return units


def _solver_data(source, condition, result, units, execution_dir=None):
    for state, values in result.get("state_series", {}).items():
        source.traces.append({"condition_id": condition, "state_id": state,
            "unit": units.get(state, "unit not declared"), "times": result["time"], "values": values})
    fields = result.get("field_series", {})
    artifact = result.get("field_series_artifact")
    if artifact:
        import numpy as np

        path = Path(artifact["path"]).resolve()
        path.relative_to(execution_dir.resolve())
        reference = _reference(source, path, "pde_field_series")
        if reference["sha256"] != artifact["sha256"]:
            raise FigureError("pde_field_series_modified")
        with np.load(path, allow_pickle=False) as archive:
            fields = {name: archive["field_" + name].tolist() for name in artifact["fields"]}
    for state, values in fields.items():
        source.fields.append({"condition_id": condition, "state_id": state,
            "unit": units.get(state, "unit not declared"), "values": values,
            **{axis: result[axis] for axis in ("x", "y", "z", "time") if axis in result}})
    for name, value in result.get("summary", {}).items():
        if isinstance(value, (int, float)) and not isinstance(value, bool) and name in {
            "objective_value", "mean", "standard_deviation", "minimum", "maximum", "final_mean", "final_minimum", "final_maximum"}:
            source.metrics.append({"metric_id": name, "condition_id": condition, "value": value,
                "unit": units.get(name, "unit not declared")})
    for state, value in result.get("summary", {}).get("final_state", {}).items():
        source.metrics.append({"metric_id": "final_" + state, "condition_id": condition,
            "value": value, "unit": units.get(state, "unit not declared")})
    if result.get("solver_id") == "stdlib_monte_carlo" and not result.get("samples"):
        source.notes.append("sample_distribution_skipped:raw_monte_carlo_samples_not_saved:" + condition)
    if result.get("samples"):
        source.samples.append({"condition_id": condition, "state_id": "observable",
            "unit": units.get("observable", "unit not declared"), "values": result["samples"]})


def quantitative_source(root: Path, version_dir: Path, execution_id: str, *, convergence_refs=None) -> FigureSource:
    root, version_dir = root.resolve(), version_dir.resolve()
    directory = safe_path(version_dir / "executions", execution_id)
    result = read_json(directory / "simulation_result.json", max_bytes=64_000_000)
    qualification = read_json(directory / "result_qualification.json")
    execution = read_json(directory / "execution_record.json")
    plan = read_json(version_dir / "simulation_run_plan.json")
    model = read_json(version_dir / "quantitative_model_spec.json")
    for item in (result, qualification, execution):
        if item["execution_id"] != execution_id or item["model_identity"] != plan["model_identity"] or item["plan_identity"] != plan["plan_identity"]:
            raise FigureError("quantitative_figure_source_identity_mismatch")
    from src.agents.quantitative_modeling.result_qualification import qualify_simulation_result

    checked = qualify_simulation_result({**execution, "scenario_results": result["scenario_results"]},
        hypothesis_relation=qualification["hypothesis_relation"], required_validation_checks=plan["qualification_requirements"])
    if checked != qualification:
        raise FigureError("quantitative_figure_qualification_differs_from_execution")
    source = FigureSource(root, {**plan["model_identity"], "version": int(plan["model_identity"]["version"]), "branch": "quantitative", "execution_id": execution_id,
        "plan_identity": plan["plan_identity"]}, qualification["result_quality"], "NUMERICAL_SIMULATION", [])
    for path, role in ((directory / "simulation_result.json", "result"), (directory / "result_qualification.json", "qualification"),
                       (directory / "execution_record.json", "execution"), (version_dir / "simulation_run_plan.json", "plan"),
                       (version_dir / "quantitative_model_spec.json", "model")):
        _reference(source, path, role)
    for scenario in result["scenario_results"]:
        _solver_data(source, scenario["scenario_id"], scenario["result"], _units(model), directory)
    from .convergence import collect_saved_convergence

    collect_saved_convergence(source, version_dir, plan, frozen_refs=convergence_refs)
    return source


def computational_source(root: Path, plan: dict, result: dict) -> FigureSource:
    from src.agents.computational_experiment_agent.capability_registry import get_backend

    if not result["lineage"]:
        raise FigureError("result_figures_require_execution_lineage")
    lineage = result["lineage"][-1]
    execution_path = Path(lineage["execution_path"]).resolve()
    execution_path.relative_to((root / "computation").resolve())
    execution = read_json(execution_path)
    if any(execution[key] != plan[key] or result[key] != plan[key] for key in ("source_binding", "experiment_id", "protocol_version")) or execution["execution_id"] != lineage["execution_id"]:
        raise FigureError("computational_figure_source_identity_mismatch")
    observations = get_backend(plan["backend_id"]).parse(execution)
    from src.agents.computational_experiment_agent.analysis import analyze

    checked = analyze(plan, execution, observations)
    for field in ("metrics", "checks", "uncertainty", "error_analysis", "validation_status", "hypothesis_relation",
            "execution_status", "result_kind", "claim_scope", "lineage"):
        if checked[field] != result[field]:
            raise FigureError("computational_figure_qualification_differs_from_execution:" + field)
    source = FigureSource(root.resolve(), {**plan["source_binding"], "branch": "computation",
        "experiment_id": plan["experiment_id"], "protocol_version": plan["protocol_version"],
        "implementation_version": execution["implementation_version"], "execution_id": execution["execution_id"]},
        result["validation_status"], result["result_kind"], [])
    plan_dir = execution_path.parent.parent.parent
    qualification_path = execution_path.parent / "qualification.json"
    for path, role in ((execution_path, "execution"), (execution_path.parent / "raw/observations.json", "observations"),
                       (qualification_path if qualification_path.is_file() else plan_dir / "result.json", "qualification"), (plan_dir / "plan.json", "plan"),
                       (plan_dir / "result.json", "result")):
        _reference(source, path, role)
    source.metrics = result["metrics"]
    units = _units(plan["model_spec"])
    for endpoint in plan["endpoints"]:
        binding = endpoint.get("observation_binding", {})
        if binding.get("state_id") and binding.get("statistic") in {"final_value", "mean", "min", "max"}:
            units[binding["state_id"]] = endpoint["unit"]
    for trace in observations.get("traces", []):
        state = trace.get("state_id", "state")
        unit = trace.get("unit", units.get(state, "unit not declared"))
        candidates = [endpoint for endpoint in plan["endpoints"] if endpoint.get("observation_binding", {}).get("source_key") == "traces"
            and endpoint["observation_binding"].get("statistic") in {"final_value", "mean", "min", "max"}
            and endpoint.get("observation_binding", {}).get("state_id", state) == state]
        if len(candidates) == 1:
            unit = candidates[0]["unit"]
        source.traces.append({**trace, "state_id": state, "unit": unit})
    for row in observations.get("solver_results", []):
        extra = FigureSource(source.root, source.identity, source.quality, source.result_kind, source.source_refs)
        _solver_data(extra, row["condition_id"], row["result"], units, execution_path.parent)
        source.fields.extend(extra.fields)
        source.samples.extend(extra.samples)
        source.notes.extend(extra.notes)
    for endpoint in plan["endpoints"]:
        binding = endpoint.get("observation_binding", {})
        if binding.get("statistic") in {"mean", "min", "max"}:
            for row in observations.get(binding.get("source_key", ""), []):
                if isinstance(row, dict) and isinstance(row.get(binding["value_key"]), list):
                    source.samples.append({"condition_id": row["condition_id"], "state_id": endpoint["metric_id"],
                        "unit": endpoint["unit"], "values": row[binding["value_key"]]})
    _collect_reference_convergence(source, plan)
    return source


def _collect_reference_convergence(source, plan):
    for diagnostic in [*plan["validation_plan"], *plan["error_analysis_plan"]]:
        settings = diagnostic["settings"]
        if "reference_expression" not in settings:
            continue
        from src.agents.quantitative_modeling.mathir import evaluate_expression

        parameters = {row["name"]: float(row["value"]) for row in plan["parameters"]}
        for trace in source.traces:
            if settings.get("condition_id", trace["condition_id"]) != trace["condition_id"] or settings.get("state_id", trace["state_id"]) != trace["state_id"]:
                continue
            condition = next(row for row in plan["comparisons"] if row["condition_id"] == trace["condition_id"])
            step = condition["overrides"].get("max_step") or condition["overrides"].get("solver_options", {}).get("max_step")
            if step is not None:
                fixed = {key: value for key, value in condition["overrides"].items() if key not in {"max_step", "solver_options"}}
                options = {key: value for key, value in condition["overrides"].get("solver_options", {}).items() if key != "max_step"}
                if options:
                    fixed["solver_options"] = options
                fixed["time_span"] = [trace["times"][0], trace["times"][-1]]
                error = max(abs(value - evaluate_expression(settings["reference_expression"], {**parameters, "t": at_time}))
                    for at_time, value in zip(trace["times"], trace["values"], strict=True))
                if math.isfinite(error):
                    source.convergence.append({"condition_id": trace["condition_id"], "state_id": trace["state_id"],
                        "step": step, "error": error, "unit": trace["unit"],
                        "check_id": diagnostic["check_id"] + ":" + digest(fixed)[:12]})
