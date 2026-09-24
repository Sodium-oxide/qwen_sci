"""Build verification tasks from canonical dependencies and record local evidence."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

from .formal_dependency import formal_records, target_dependencies


REPORT_VERSION = "formal_verification_report_v1"


def semantic_snapshot(plan, target_id):
    records = formal_records(plan)
    identifiers = target_dependencies(plan, target_id) | {target_id}
    pending = list(identifiers)
    while pending:
        identifier = pending.pop()
        extra = target_dependencies(plan, identifier) - identifiers
        identifiers.update(extra)
        pending.extend(extra)
    snapshot = {identifier: {key: deepcopy(value) for key, value in records[identifier].items() if key not in {"statement", "selection_reason", "source_path", "source_refs"}} for identifier in sorted(identifiers)}
    snapshot["$diagnostics"] = deepcopy([item for item in plan.get("semantic_diagnostics", []) if item.get("target_id") in identifiers])
    snapshot["$unknown_items"] = deepcopy(plan.get("unknown_items", []))
    snapshot["$definition_bindings"] = {record.get("symbol"): record.get("definition_id") for record in plan.get("definitions", [])}
    if "obligation_id" in records[target_id]:
        snapshot["$parent"] = deepcopy(records.get(records[target_id].get("target_id"), {}))
    return snapshot


def build_verification_task(plan, target_id, backend, timeout_seconds=60, verified_results=()):
    records = formal_records(plan)
    target = deepcopy(records[target_id])
    if "obligation_id" in target:
        parent = records[target["target_id"]]
        for field in ("quantifiers", "scope", "domain_expression"):
            target.setdefault(field, parent.get(field))
    dependencies = target_dependencies(plan, target_id)
    blockers = []
    constraints = []
    if not target.get("quantifiers") or any(item.get("quantifier") != "forall" or item.get("sort") not in {"real", "integer", "boolean"} for item in target.get("quantifiers", [])):
        blockers.append("missing_or_unsupported_quantifiers")
    if target.get("domain_expression") is None:
        blockers.append("missing_domain_encoding")
    else:
        constraints.append(target["domain_expression"])
    if target.get("conclusion_expression") is None:
        blockers.append("missing_conclusion_encoding")
    if target.get("conclusion_expression") == {"bool": True}:
        blockers.append("vacuous_conclusion")
    if target.get("conditions") and len(target["conditions"]) != len(target.get("condition_expressions", [])):
        blockers.append("missing_target_condition_encoding")
    constraints.extend(target.get("condition_expressions", []))
    for identifier in sorted(dependencies):
        record = records[identifier]
        if "definition_id" in record:
            if record.get("definition_status") != "specified":
                blockers.append(f"undefined:{identifier}")
            if record.get("object_kind") != "primitive":
                if record.get("formal_expression") is None:
                    blockers.append(f"missing_definition_encoding:{identifier}")
                else:
                    constraints.append({"op": "eq", "args": [{"symbol": record["symbol"]}, record["formal_expression"]]})
        elif "assumption_id" in record:
            if record.get("predicate_expression") is None:
                blockers.append(f"missing_assumption_encoding:{identifier}")
            else:
                constraints.append(record["predicate_expression"])
        elif "relation_id" in record:
            if record.get("formal_expression") is None or record.get("status") == "unresolved":
                blockers.append(f"missing_model_encoding:{identifier}")
            else:
                constraints.append(record["formal_expression"])
        elif "proposition_id" in record or "lemma_id" in record:
            evidence = next((result for result in verified_results if result.get("target_id") == identifier and result.get("result") == "passed" and result.get("evidence_kind") in {"smt_unsat", "symbolic_identity"} and result.get("input_snapshot") == semantic_snapshot(plan, identifier)), None)
            if evidence is None or any(obligation not in {result.get("target_id") for result in verified_results if result.get("result") == "passed"} for obligation in record.get("required_obligation_ids", [])):
                blockers.append(f"requires_verified_dependency:{identifier}")
            elif record.get("conclusion_expression") is not None:
                if record.get("quantifiers") != target.get("quantifiers"):
                    blockers.append(f"unsupported_lemma_instantiation:{identifier}")
                else:
                    constraints.append({"op": "or", "args": [
                        {"op": "not", "args": [{"op": "and", "args": evidence["constraints"]}]},
                        record["conclusion_expression"],
                    ]})
            else:
                blockers.append(f"missing_lemma_encoding:{identifier}")
            continue
        if record.get("conditions") and len(record.get("conditions", [])) != len(record.get("condition_expressions", [])):
            blockers.append(f"missing_condition_encoding:{identifier}")
        constraints.extend(record.get("condition_expressions", []))
    for diagnostic in plan.get("semantic_diagnostics", []):
        if diagnostic.get("target_id") in dependencies | {target_id} and not diagnostic.get("resolved", False):
            blockers.append("semantic_diagnostic_requires_review")
    for unknown in plan.get("unknown_items", []):
        affected = set(str(unknown.get("field_path", "")).split(".")) & (dependencies | {target_id})
        if affected or not unknown.get("field_path") or str(unknown.get("field_path")).startswith("variables."):
            blockers.append("unresolved_scientific_input")
    symbol_names = [item.get("symbol") for item in target.get("quantifiers", [])]
    declared_symbols = {definition.get("symbol") for definition in plan.get("definitions", [])}
    if set(symbol_names) - declared_symbols:
        blockers.append("quantified_symbol_without_definition")
    if len(symbol_names) != len(set(symbol_names)):
        blockers.append("duplicate_quantified_symbol")
    return {
        "task_kind": "counterexample_search" if backend == "z3" else "symbolic_identity" if backend == "sympy" else "candidate_check",
        "backend": backend, "target_id": target_id, "target_revision": plan.get("revision", 1),
        "quantifiers": deepcopy(target.get("quantifiers", [])), "constraints": deepcopy(constraints),
        "conclusion_expression": deepcopy(target.get("conclusion_expression")),
        "encoding_scope": target.get("scope", ""), "timeout_seconds": timeout_seconds,
        "assumptions_used": sorted(identifier for identifier in dependencies if "assumption_id" in records[identifier]),
        "candidate_points": deepcopy(target.get("candidate_points", [])),
        "candidate_ids": deepcopy(target.get("candidate_ids", [])),
        "remaining_obligations": list(target.get("required_obligation_ids", [])),
        "blockers": blockers, "input_snapshot": semantic_snapshot(plan, target_id),
    }


def run_verification_task(task, *, enabled=True):
    record = deepcopy(task)
    record.update(result="not_run", evidence_kind="none", artifact_refs=[], limitations=[], executed=False)
    if not enabled:
        record["limitations"] = ["Mathematical verification is disabled."]
        return record
    if task["blockers"]:
        record.update(result="unsupported", limitations=list(task["blockers"]))
        return record
    if task["backend"] not in {"sympy", "z3", "numerical"}:
        record.update(result="unsupported", limitations=["Proof assistant backend is not configured."])
        return record
    try:
        process = subprocess.run(
            [sys.executable, str(Path(__file__).with_name("formal_verification_worker.py"))],
            input=json.dumps(task, allow_nan=False), text=True, capture_output=True,
            timeout=max(0.01, float(task["timeout_seconds"])),
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        record["executed"] = True
        if process.returncode != 0:
            record.update(result="unknown", limitations=[f"Backend exit code {process.returncode}"])
        else:
            result = json.loads(process.stdout)
            for field in ("result", "evidence_kind", "limitations", "witness", "counterexample_id", "backend_version", "residual"):
                if field in result:
                    record[field] = result[field]
    except subprocess.TimeoutExpired:
        record.update(result="timeout", executed=True, limitations=["Backend exceeded the wall-clock limit."])
    except (OSError, ValueError) as error:
        record.update(result="unknown", limitations=[f"{type(error).__name__}: {error}"])
    return record


def _task_result(task, previous, enabled):
    cached = next((
        record for record in previous
        if enabled and not task["blockers"]
        and record.get("target_id") == task["target_id"]
        and record.get("backend") == task["backend"]
        and record.get("input_snapshot") == task["input_snapshot"]
        and record.get("constraints") == task["constraints"]
        and record.get("result") in {"passed", "failed"}
    ), None)
    result = deepcopy(cached) if cached else run_verification_task(task, enabled=enabled)
    result["reused"] = cached is not None
    return result


def summarize_targets(plan, results):
    summaries = []
    records = formal_records(plan)
    for target in [*plan.get("propositions", []), *plan.get("lemmas", [])]:
        target_id = target.get("proposition_id", target.get("lemma_id"))
        snapshot = semantic_snapshot(plan, target_id)
        current = [record for record in results if record["target_id"] == target_id and record.get("input_snapshot") == snapshot]
        remaining = sorted(set(target.get("required_obligation_ids", [])) | {record["obligation_id"] for record in plan.get("proof_obligations", []) if record.get("target_id") == target_id})
        discharged = {record["target_id"] for record in results if record.get("result") == "passed" and record.get("evidence_kind") in {"smt_unsat", "symbolic_identity"} and record.get("input_snapshot") == semantic_snapshot(plan, record["target_id"])}
        remaining = [identifier for identifier in remaining if identifier not in discharged]
        dependencies = target_dependencies(plan, target_id)
        missing = [identifier for identifier in dependencies if (
            "definition_id" in records[identifier] and records[identifier].get("definition_status") != "specified"
        ) or ("relation_id" in records[identifier] and records[identifier].get("status") == "unresolved")]
        diagnostics = [item for item in plan.get("semantic_diagnostics", []) if item.get("target_id") in dependencies | {target_id} and not item.get("resolved", False)]
        if missing:
            status = "blocked_by_definition"
        elif diagnostics:
            status = "unresolved"
        elif any(record["result"] == "failed" and record["evidence_kind"] == "smt_witness" for record in current):
            status = "refuted_in_declared_scope"
        elif any(record["result"] == "passed" and record["evidence_kind"] in {"smt_unsat", "symbolic_identity"} for record in current):
            status = "partially_verified" if remaining else "verified_in_declared_scope"
        elif any(attempt.get("target_id") == target_id and attempt.get("steps") for attempt in plan.get("proof_attempts", [])):
            status = "proof_draft_available"
        else:
            status = "unresolved"
        summaries.append({"target_id": target_id, "status": status, "revision": plan.get("revision", 1), "remaining_obligations": remaining, "missing_dependencies": missing, "scope": target.get("scope", "")})
    return summaries


def verify_formal_plan(plan, settings, *, previous_report=None):
    results = []
    previous = (previous_report or {}).get("results", [])
    enabled = bool(settings.get("enabled", False))
    targets = [*plan.get("proof_obligations", []), *plan.get("lemmas", []), *plan.get("propositions", [])]
    ordered = [
        (target.get("obligation_id", target.get("proposition_id", target.get("lemma_id"))), target)
        for target in targets
    ]
    max_workers = max(1, int(settings.get("max_parallel_tasks", 1)))
    with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="formal-verify") as executor:
        while ordered:
            ready = []
            remaining = []
            pending_ids = {identifier for identifier, _target in ordered}
            for target_id, target in ordered:
                dependencies = target_dependencies(plan, target_id) | set(target.get("required_obligation_ids", []))
                if dependencies & (pending_ids - {target_id}):
                    remaining.append((target_id, target))
                else:
                    ready.append((target_id, target))
            if not ready:
                ready = [remaining.pop(0)]
            wave_tasks = []
            for target_id, target in ready:
                backends = list(settings.get("backends", ["sympy", "z3"]))
                if target.get("candidate_points") and "numerical" not in backends:
                    backends.append("numerical")
                for backend in backends:
                    wave_tasks.append(build_verification_task(plan, target_id, backend, settings.get("timeout_seconds", 60), results))
            wave_results = list(executor.map(lambda task: _task_result(task, previous, enabled), wave_tasks))
            results.extend(wave_results)
            ordered = remaining
    summaries = summarize_targets(plan, results)
    return {
        "schema_version": REPORT_VERSION,
        "policy": {
            "enabled": enabled,
            "experiment_execution": False,
            "max_parallel_tasks": max(1, int(settings.get("max_parallel_tasks", 1))),
        },
        "results": results,
        "target_summaries": summaries,
        "task_summary": {
            "task_count": len(results),
            "reused_count": sum(bool(item.get("reused")) for item in results),
            "executed_count": sum(bool(item.get("executed")) for item in results),
            "unsupported_count": sum(item.get("result") == "unsupported" for item in results),
            "timeout_count": sum(item.get("result") == "timeout" for item in results),
        },
    }


def validate_verification_report(plan, report):
    errors = []
    if not isinstance(report, Mapping) or report.get("schema_version") != REPORT_VERSION:
        return ["invalid_formal_verification_report"]
    if not isinstance(report.get("results"), list) or not isinstance(report.get("policy"), Mapping):
        return ["invalid_formal_verification_report_shape"]
    policy = report["policy"]
    if type(policy.get("enabled")) is not bool or policy.get("experiment_execution") is not False:
        errors.append("invalid_mathematical_verification_policy")
    accepted = []
    seen = set()
    for result in report["results"]:
        if not isinstance(result, Mapping):
            errors.append("verification_result_not_object")
            continue
        target_id = result.get("target_id")
        backend = result.get("backend")
        identity = (target_id, backend)
        if identity in seen:
            errors.append("duplicate_verification_result")
        seen.add(identity)
        try:
            expected = build_verification_task(plan, target_id, backend, result.get("timeout_seconds", 60), accepted)
        except (ValueError, KeyError, TypeError):
            errors.append("verification_result_unknown_target")
            continue
        for field in ("input_snapshot", "constraints", "conclusion_expression", "quantifiers", "encoding_scope", "assumptions_used"):
            if result.get(field) != expected[field]:
                errors.append(f"verification_result_stale_or_mismatched:{target_id}:{field}")
        if result.get("result") not in {"passed", "failed", "unknown", "timeout", "unsupported", "not_run"}:
            errors.append("invalid_verification_result_status")
        if result.get("result") in {"passed", "failed"}:
            kinds = {"z3": {"passed": "smt_unsat", "failed": "smt_witness"}, "sympy": {"passed": "symbolic_identity"}, "numerical": {"failed": "numerical_candidate"}}
            if result.get("evidence_kind") != kinds.get(backend, {}).get(result["result"]):
                errors.append("verification_evidence_backend_mismatch")
            if not policy.get("enabled") or result.get("executed") is not True or not result.get("backend_version") or expected["blockers"]:
                errors.append("verification_success_without_valid_execution")
        accepted.append(result)
    if not errors:
        if report.get("target_summaries") != summarize_targets(plan, accepted):
            errors.append("verification_target_summary_mismatch")
    return errors
