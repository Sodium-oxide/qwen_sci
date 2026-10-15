"""Host-computed evidence and bounded optional scientific interpretation."""

import json
import re

from src.agents.experiment_design_agent.llm_json import call_required_json

from .contracts import require_contract
from .domain_registry import validate_scientific_plan
from .validation import check_observations, normalize_metrics, threshold


def analyze(plan: dict, execution: dict | None, observations: dict, *, llm_call=None) -> dict:
    completed = execution is not None and execution["status"] == "COMPLETED"
    metrics, checks, errors, uncertainty, unresolved = [], [], [], [], []
    if completed:
        try:
            if protocol_errors := validate_scientific_plan(plan).errors:
                raise ValueError("invalid_scientific_protocol:" + ";".join(protocol_errors))
            metrics = normalize_metrics(plan, observations, str(execution["output_dir"]) + "/raw/observations.json")
            checks, errors, uncertainty = check_observations(plan, observations, metrics)
        except (ValueError, KeyError, TypeError) as error:
            unresolved.append(str(error))
    else:
        unresolved.append("not_executed" if execution is None else execution["status"])
    qualified = completed and bool(metrics) and bool(checks) and all(row["passed"] for row in checks) and not unresolved
    unresolved.extend(row["check_id"] + ":" + row["reason"] for row in checks if not row["passed"])
    relation = "INCONCLUSIVE"
    decision = plan["decision_rule"]
    if qualified and decision.get("metric_id"):
        try:
            selected = next(row for row in metrics if (row["metric_id"], row["condition_id"]) ==
                (decision["metric_id"], decision["condition_id"]))
            relation = "SUPPORTED" if threshold(selected["value"], decision) else "REFUTED"
        except (StopIteration, ValueError, KeyError):
            unresolved.append("hypothesis_decision_not_evaluable")
    result = {"schema_version": "computational_result_v1", "experiment_id": plan["experiment_id"],
        "source_binding": plan["source_binding"], "protocol_version": plan["protocol_version"],
        "execution_status": "COMPLETED" if completed else "NOT_EXECUTED" if execution is None else "FAILED",
        "result_kind": plan["result_kind"],
        "validation_status": "QUALIFIED" if qualified else "PARTIAL" if metrics else "UNQUALIFIED" if execution else "NOT_EXECUTED",
        "metrics": metrics, "checks": checks, "uncertainty": uncertainty, "error_analysis": errors,
        "hypothesis_relation": relation, "claim_scope": plan["claim_scope"], "interpretation": {},
        "unresolved_items": list(dict.fromkeys(unresolved)), "lineage": [] if execution is None else [{
            "execution_id": execution["execution_id"], "protocol_version": execution["protocol_version"],
            "implementation_version": execution["implementation_version"], "execution_path": str(execution["output_dir"]) + "/execution.json"}]}
    if llm_call and qualified:
        response = call_required_json(llm_call, "Interpret these fixed computational metrics within claim_scope. "
            "Return {discussion: string, metric_ids: [existing IDs]}. Refer to metrics by ID; do not include numerical literals. "
            "Do not claim physical experimental observations from simulated outputs or alter trusted statuses.\n" +
            json.dumps({"question": plan["research_question"], "result": result}), stage="computational_analysis")
        if set(response) != {"discussion", "metric_ids"} or not isinstance(response["discussion"], str) or not isinstance(response["metric_ids"], list):
            raise ValueError("invalid_interpretation")
        if not set(response["metric_ids"]).issubset({row["metric_id"] for row in metrics}):
            raise ValueError("unknown_interpretation_metric")
        prose = response["discussion"]
        for metric_id in response["metric_ids"]:
            prose = prose.replace(metric_id, "")
        if re.search(r"(?<![A-Za-z_])[-+]?\d+(?:\.\d+)?", prose):
            raise ValueError("interpretation_must_reference_frozen_metrics_without_numeric_literals")
        if plan["result_kind"] == "NUMERICAL_SIMULATION":
            from src.agents.research_plan_author.latex_safety import contains_observed_result_language
            if contains_observed_result_language(prose):
                raise ValueError("simulation_interpretation_claims_empirical_observations")
        result["interpretation"] = response
    return require_contract(result)


def render_analysis(plan: dict, result: dict) -> str:
    lines = ["# " + plan["title"], "", plan["research_question"], "",
        "Execution: " + result["execution_status"] + "; qualification: " + result["validation_status"] +
        "; hypothesis relation: " + result["hypothesis_relation"], "", "Scope: " + result["claim_scope"], "",
        "| Metric | Condition | Value | Unit |", "|---|---|---:|---|"]
    lines.extend(f"| {row['metric_id']} | {row['condition_id']} | {row['value']:.12g} | {row['unit']} |" for row in result["metrics"])
    lines.extend(["", "## Numerical and method diagnostics", ""])
    lines.extend(f"- {row['check_id']}: {row['value']} ({row['method']})" for row in result["error_analysis"])
    lines.extend(["", result["interpretation"].get("discussion", ""), "", "## Unresolved", ""])
    lines.extend("- " + item for item in result["unresolved_items"])
    return "\n".join(lines) + "\n"
