"""Separate code failures, numerical refinement and scientific revisions."""

from dataclasses import dataclass

from .capability_registry import get_backend


@dataclass(frozen=True)
class IterationDecision:
    kind: str
    reason: str


def next_decision(plan: dict, execution: dict | None, result: dict, *, repairs: int, revisions: int,
                  remaining_seconds: float) -> IterationDecision:
    if plan["status"] == "NEEDS_INPUT":
        return IterationDecision("REQUEST_INPUT", "indispensable_inputs_missing")
    if execution and execution["status"] == "ENVIRONMENT_UNAVAILABLE":
        return IterationDecision("REQUEST_INPUT", "runtime_or_software_unavailable")
    if execution and execution["status"] == "CANCELLED":
        return IterationDecision("STOP_CANCELLED", "user_cancelled")
    if result["validation_status"] == "QUALIFIED":
        return IterationDecision("ACCEPT_RESULT", "all_checks_passed_including_negative_results")
    if remaining_seconds <= 0:
        return IterationDecision("STOP_BUDGET", "wall_budget_exhausted")
    if execution is None or execution["status"] != "COMPLETED" or not result["metrics"]:
        if repairs < plan["resource_budget"]["max_code_repairs"] and get_backend(plan["backend_id"]).uses_generated_code(plan):
            return IterationDecision("REPAIR_IMPLEMENTATION", "engineering_or_output_contract_failure")
        return IterationDecision("STOP_PARTIAL", "implementation_repair_limit_or_fixed_backend_failure")
    if revisions < plan["resource_budget"]["max_protocol_revisions"]:
        return IterationDecision("REFINE_NUMERICS", "numerical_checks_incomplete")
    return IterationDecision("STOP_PARTIAL", "numerical_refinement_limit")
