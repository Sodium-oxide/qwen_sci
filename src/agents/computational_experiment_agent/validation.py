"""Compute qualification from observations and predetermined host checks."""

import math
import operator
import statistics

from src.agents.quantitative_modeling.mathir import evaluate_expression, validate_expression

from .contracts import ValidationReport
from .capability_registry import get_backend
from .domain_registry import get_domain_profile

OPERATORS = {"lt": operator.lt, "le": operator.le, "gt": operator.gt, "ge": operator.ge}


def threshold(value: float, settings: dict) -> bool:
    chosen = settings.get("operator")
    limit = settings.get("threshold")
    if chosen not in OPERATORS or isinstance(limit, bool) or not isinstance(limit, (int, float)) or not math.isfinite(limit):
        raise ValueError("missing_or_invalid_predetermined_threshold")
    return OPERATORS[chosen](value, limit)


def validate_implementation(plan: dict, implementation: dict, project) -> ValidationReport:
    from .artifacts import read_json, safe_path
    from .contracts import validate_contract
    from src.pipeline.science_run import file_sha256
    errors = validate_contract(implementation)
    for key in ("source_binding", "experiment_id", "protocol_version", "backend_id"):
        if implementation.get(key) != plan.get(key):
            errors.append("implementation_mismatch:" + key)
    for record in implementation.get("files", []):
        try:
            path = safe_path(project, record["path"])
            if file_sha256(path) != record["sha256"]:
                errors.append("implementation_file_modified:" + record["path"])
        except (ValueError, OSError):
            errors.append("implementation_file_unavailable")
    if {path.relative_to(project).as_posix() for path in project.rglob("*") if path.is_file()} != {row["path"] for row in implementation.get("files", [])}:
        errors.append("implementation_contains_unregistered_files")
    if read_json(safe_path(project, "configs/experiment.json")) != plan:
        errors.append("implementation_config_mismatch")
    return ValidationReport(tuple(errors))


def normalize_metrics(plan: dict, observations: dict, source_ref: str) -> list[dict]:
    endpoints = {row["metric_id"]: row for row in plan["endpoints"]}
    conditions = {row["condition_id"] for row in plan["comparisons"]}
    metrics, seen = [], set()
    for row in observations.get("metrics", []):
        key = (row["metric_id"], row["condition_id"])
        value = row["value"]
        if key in seen or key[0] not in endpoints or key[1] not in conditions:
            raise ValueError("unknown_or_duplicate_metric")
        if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
            raise ValueError("nonfinite_metric")
        if row["unit"] != endpoints[key[0]]["unit"]:
            raise ValueError("metric_unit_mismatch")
        endpoint = endpoints[key[0]]
        derived = value
        if get_backend(plan["backend_id"]).uses_generated_code(plan):
            if not endpoint.get("observation_binding"):
                raise ValueError("endpoint_requires_host_observation_binding")
            binding = endpoint["observation_binding"]
            if binding["source_key"] in {"metrics", "checks", "validation_status", "hypothesis_relation", "execution_status"}:
                raise ValueError("endpoint_cannot_bind_to_derived_metrics_or_status")
            candidates = observations[binding["source_key"]]
            if not isinstance(candidates, list):
                raise ValueError("observation_source_requires_condition_records")
            matches = [record for record in candidates if record.get("condition_id") == key[1]
                and (not binding.get("state_id") or record.get("state_id") == binding["state_id"])]
            if len(matches) != 1:
                raise ValueError("missing_or_ambiguous_bound_observation")
            record = matches[0]
            raw = record[binding["value_key"]]
            statistic = binding["statistic"]
            samples = [raw] if statistic == "value" else raw
            if not isinstance(samples, list) or not samples or any(isinstance(item, bool)
                or not isinstance(item, (int, float)) or not math.isfinite(item) for item in samples):
                raise ValueError("invalid_bound_observation")
            if statistic in {"value", "final_value"}:
                derived = samples[-1]
            elif statistic == "mean":
                derived = statistics.mean(samples)
            elif statistic in {"min", "max"}:
                derived = min(samples) if statistic == "min" else max(samples)
            else:
                times = record["times"]
                if len(times) != len(samples) or len(times) < 2 or any(not math.isfinite(item) for item in times) or any(
                    later <= earlier for earlier, later in zip(times, times[1:])):
                    raise ValueError("invalid_integral_times")
                derived = math.fsum((later - earlier) * (left + right) / 2
                    for earlier, later, left, right in zip(times, times[1:], samples, samples[1:]))
        elif plan["backend_id"] in {"pyscf", "mathir"}:
            source_key = "energies" if plan["backend_id"] == "pyscf" else "solver_results"
            matches = [record for record in observations[source_key] if record["condition_id"] == key[1]]
            if len(matches) != 1:
                raise ValueError("missing_or_duplicate_backend_condition")
            derived = matches[0]["value"] if plan["backend_id"] == "pyscf" else matches[0]["result"]
            if plan["backend_id"] == "mathir":
                for part in endpoint["estimator"].split("."):
                    derived = derived[int(part)] if isinstance(derived, list) else derived[part]
        if isinstance(derived, bool) or not isinstance(derived, (int, float)) or not math.isfinite(derived) or not math.isclose(
            value, derived, rel_tol=1e-10, abs_tol=1e-12):
            raise ValueError("metric_differs_from_bound_observation")
        seen.add(key)
        metrics.append({**{field: row[field] for field in ("metric_id", "condition_id", "unit")}, "value": derived, "source_ref": source_ref})
    expected = {(metric_id, condition_id) for metric_id in endpoints for condition_id in conditions}
    if seen != expected:
        raise ValueError("missing_condition_endpoint_observations")
    return metrics


def check_observations(plan: dict, observations: dict, metrics: list[dict]) -> tuple[list, list, list]:
    profile = get_domain_profile(plan["method_family"])
    required = set(profile.required_checks(plan))
    condition_requirements = profile.check_conditions(plan) if hasattr(profile, "check_conditions") else {}
    declared = {row["check_id"]: row for row in [*plan["validation_plan"], *plan["error_analysis_plan"]]}
    checks, errors, uncertainty = [], [], []
    metric_map = {(row["metric_id"], row["condition_id"]): row["value"] for row in metrics}
    for check_id in sorted(required | set(declared)):
        specification = declared.get(check_id)
        settings = specification.get("settings", {}) if specification else {}
        passed, value, reason = False, None, "missing_check_specification"
        try:
            if check_id == "finite_outputs":
                passed = bool(metrics) and all(math.isfinite(row["value"]) for row in metrics)
                reason = "host_finite_numeric_check"
            elif specification is None:
                pass
            elif check_id == "scf_convergence" and plan["backend_id"] == "pyscf":
                source = "electronic_states" if get_backend(plan["backend_id"]).uses_generated_code(plan) else "energies"
                states = observations.get(source, [])
                all_conditions = {row["condition_id"] for row in plan["comparisons"]}
                expected = condition_requirements.get(check_id, all_conditions)
                passed = len(states) == len(all_conditions) and {row["condition_id"] for row in states} == all_conditions and all(
                    row.get("converged") is True for row in states if row["condition_id"] in expected)
                reason = "host_scf_convergence_check"
            elif check_id == "electronic_state" and plan["backend_id"] == "pyscf":
                source = "electronic_states" if get_backend(plan["backend_id"]).uses_generated_code(plan) else "energies"
                states = observations.get(source, [])
                conditions = {row["condition_id"]: row for row in plan["comparisons"]}
                passed = len(states) == len(conditions) and {row["condition_id"] for row in states} == set(conditions)
                for row in states:
                    options = {**plan["model_spec"], **conditions[row["condition_id"]]["overrides"]}
                    spin, charge = options["spin"], options["charge"]
                    passed = passed and all(isinstance(row[field], int) and not isinstance(row[field], bool)
                        for field in ("spin", "charge", "nelectron")) and row["spin"] == spin and row["charge"] == charge
                    passed = passed and row["nelectron"] >= spin and (row["nelectron"] - spin) % 2 == 0
                reason = "electron_count_charge_spin_consistency"
            elif check_id in condition_requirements and check_id not in {"finite_outputs", "electronic_state", "method_sensitivity", "scf_convergence"}:
                expected = condition_requirements[check_id]
                declared_conditions = {settings["condition_id"]} if settings.get("condition_id") else set(settings.get("condition_ids", expected))
                if not expected.issubset(declared_conditions):
                    raise ValueError("task_diagnostic_missing_conditions")
                values = [metric_map[settings["metric_id"], condition_id] for condition_id in sorted(expected)]
                passed = all(threshold(item, settings) for item in values)
                value, reason = max(values), "host_per_condition_task_diagnostic"
            elif "reference_expression" in settings:
                expression = settings["reference_expression"]
                variables = {"t", *[row["name"] for row in plan["parameters"]]}
                validate_expression(expression, allowed_symbols=variables)
                parameters = {row["name"]: float(row["value"]) for row in plan["parameters"]}
                differences = []
                covered = set()
                seen_traces = set()
                for trace in observations.get("traces", []):
                    if settings.get("condition_id") and trace["condition_id"] != settings["condition_id"]:
                        continue
                    if settings.get("state_id") and trace.get("state_id") != settings["state_id"]:
                        continue
                    identity = (trace["condition_id"], trace.get("state_id"))
                    if identity in seen_traces:
                        raise ValueError("duplicate_reference_trace")
                    seen_traces.add(identity)
                    if len(trace["times"]) != len(trace["values"]) or len(trace["times"]) < 2:
                        raise ValueError("invalid_reference_trace")
                    if any(isinstance(item, bool) or not isinstance(item, (int, float)) or not math.isfinite(item)
                        for item in [*trace["times"], *trace["values"]]) or any(
                        later <= earlier for earlier, later in zip(trace["times"], trace["times"][1:])):
                        raise ValueError("nonfinite_or_unordered_reference_trace")
                    span = plan["model_spec"].get("time_span") or plan["model_spec"].get("mathir", {}).get("time_span")
                    if span and not (math.isclose(trace["times"][0], span[0]) and math.isclose(trace["times"][-1], span[1])):
                        raise ValueError("reference_trace_domain_mismatch")
                    differences.extend(abs(float(observed) - evaluate_expression(expression, {**parameters, "t": float(at_time)}))
                        for at_time, observed in zip(trace["times"], trace["values"], strict=True))
                    covered.add(trace["condition_id"])
                expected = {settings["condition_id"]} if settings.get("condition_id") else {row["condition_id"] for row in plan["comparisons"]}
                if covered != expected or not differences or not all(math.isfinite(item) for item in differences):
                    raise ValueError("missing_reference_trace")
                value = max(differences)
                passed, reason = threshold(value, settings), "host_reference_max_absolute_error"
            elif "compare_conditions" in settings:
                left, right = settings["compare_conditions"]
                value = abs(metric_map[settings["metric_id"], left] - metric_map[settings["metric_id"], right])
                passed, reason = threshold(value, settings), "host_condition_difference"
            elif "samples_key" in settings:
                samples = observations[settings["samples_key"]]
                if len(samples) < settings.get("min_replicates", 6) or not all(math.isfinite(item) for item in samples):
                    raise ValueError("insufficient_replicate_samples")
                mean, sem = statistics.mean(samples), statistics.stdev(samples) / math.sqrt(len(samples))
                value = sem
                passed, reason = threshold(value, settings), "host_standard_error"
                uncertainty.append({"check_id": check_id, "n": len(samples), "mean": mean, "standard_error": sem,
                    "assumption": "independent_replicates"})
            elif "metric_id" in settings:
                value = metric_map[settings["metric_id"], settings["condition_id"]]
                passed, reason = threshold(value, settings), "host_predetermined_metric_threshold"
            else:
                reason = "unsupported_check_requires_explicit_diagnostic"
        except (ValueError, KeyError, TypeError, IndexError) as error:
            reason = "check_failed:" + str(error)
        checks.append({"check_id": check_id, "passed": bool(passed), "value": value, "reason": reason})
        if check_id in {row["check_id"] for row in plan["error_analysis_plan"]} or value is not None:
            errors.append({"check_id": check_id, "value": value, "method": reason,
                "interpretation": "predetermined diagnostic; method differences are not ground-truth error"})
    return checks, errors, uncertainty
