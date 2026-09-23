"""Versioned scientific contracts shared by planning, verification and Author."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import Any

from .formal_dependency import COLLECTION_IDS, dependency_ids, expression_symbols, formal_records, target_dependencies


FORMAL_PLAN_V2 = "formal_reasoning_plan_v2"
DEFINITION_RESOLUTION_V1 = "formal_definition_resolution_v1"
PROPOSAL_STATUSES = {"candidate_formalization", "proposed", "unverified", "unresolved", "needs_human_input", "user_declared"}
DEFINITION_FIELDS = (
    "definition_id", "symbol", "statement", "expression_latex", "formal_expression",
    "domain", "codomain", "unit", "conditions", "condition_expressions", "depends_on",
    "origin", "source_refs", "selection_reason", "definition_status", "verification_readiness",
    "variable_references", "symbol_references", "object_kind",
)


def adapt_legacy_plan(plan: Mapping[str, Any]) -> dict[str, Any]:
    adapted = deepcopy(dict(plan))
    if adapted.get("schema_version") == FORMAL_PLAN_V2:
        return adapted
    adapted["schema_version"] = FORMAL_PLAN_V2
    adapted["adapted_from"] = plan.get("schema_version")
    adapted["revision"] = 1
    for collection in ("lemmas", "model_relations", "proof_attempts", "global_assumption_ids", "semantic_diagnostics"):
        adapted.setdefault(collection, [])
    for definition in adapted.get("definitions", []):
        for field in DEFINITION_FIELDS:
            if field not in definition:
                definition[field] = [] if field in {"conditions", "condition_expressions", "depends_on", "source_refs", "variable_references", "symbol_references"} else None
        definition.update(origin="unresolved", definition_status="unresolved", verification_readiness="requires_encoding")
    for proposition in adapted.get("propositions", []):
        proposition.setdefault("quantifiers", [])
        proposition.setdefault("domain_expression", None)
        proposition.setdefault("conclusion_expression", None)
        proposition.setdefault("required_obligation_ids", [])
    for obligation in adapted.get("proof_obligations", []):
        obligation.setdefault("target_id", None)
        obligation.setdefault("premises", [])
    return adapted


def validate_definition(definition: Any) -> list[str]:
    if not isinstance(definition, Mapping):
        return ["definition_not_object"]
    identifier = str(definition.get("definition_id") or "?")
    errors = [f"{identifier}_missing:{field}" for field in DEFINITION_FIELDS if field not in definition]
    if definition.get("origin") not in {"source_grounded", "modeling_convention", "unresolved"}:
        errors.append(f"{identifier}_invalid_origin")
    if definition.get("definition_status") not in {"specified", "unresolved"}:
        errors.append(f"{identifier}_invalid_definition_status")
    if definition.get("verification_readiness") not in {"encoded", "requires_encoding", "blocked"}:
        errors.append(f"{identifier}_invalid_verification_readiness")
    for field in ("conditions", "condition_expressions", "depends_on", "source_refs", "variable_references", "symbol_references"):
        if not isinstance(definition.get(field), list):
            errors.append(f"{identifier}_{field}_not_array")
    if definition.get("definition_status") == "specified":
        for field in ("symbol", "statement", "domain", "codomain", "unit", "selection_reason"):
            if not isinstance(definition.get(field), str) or not definition[field].strip():
                errors.append(f"{identifier}_specified_requires:{field}")
        if definition.get("object_kind") not in {"primitive", "derived"}:
            errors.append(f"{identifier}_invalid_object_kind")
        if definition.get("object_kind") == "derived" and not definition.get("expression_latex") and not definition.get("formal_expression"):
            errors.append(f"{identifier}_derived_requires_expression")
        if definition.get("origin") == "unresolved":
            errors.append(f"{identifier}_specified_origin_unresolved")
        if definition.get("origin") == "source_grounded" and not definition.get("source_refs"):
            errors.append(f"{identifier}_source_grounded_requires_source")
    return errors


def validate_formal_plan_v2(plan: Any, variable_claim_model: Mapping[str, Any] | None = None) -> list[str]:
    if not isinstance(plan, Mapping):
        return ["formal_plan_not_object"]
    errors: list[str] = []
    for field in (*COLLECTION_IDS, "proof_attempts", "global_assumption_ids", "unknown_items", "semantic_diagnostics"):
        if not isinstance(plan.get(field), list):
            errors.append(f"formal_plan_{field}_not_array")
    if errors:
        return errors
    if plan.get("schema_version") != FORMAL_PLAN_V2:
        errors.append("formal_plan_invalid_version")
    if type(plan.get("revision")) is not int or plan["revision"] < 1:
        errors.append("formal_plan_invalid_revision")
    if plan.get("status") not in {"unverified", "requires_human_review", "not_applicable"}:
        errors.append("formal_plan_invalid_status")
    identifiers: set[str] = set()
    for collection, identifier_field in COLLECTION_IDS.items():
        for record in plan[collection]:
            if not isinstance(record, Mapping):
                errors.append(f"{collection}_record_not_object")
                continue
            identifier = record.get(identifier_field)
            if not isinstance(identifier, str) or not identifier.strip() or identifier in identifiers:
                errors.append(f"{collection}_invalid_or_duplicate_id:{identifier}")
            identifiers.add(str(identifier))
            if collection == "definitions":
                errors.extend(validate_definition(record))
            elif record.get("status") not in PROPOSAL_STATUSES:
                errors.append(f"{identifier}_invalid_proposal_status")
            if collection == "model_relations":
                for field in ("statement", "formal_expression", "scope", "origin", "source_refs", "conditions", "condition_expressions", "selection_reason"):
                    if field not in record:
                        errors.append(f"{identifier}_missing:{field}")
            for field in ("premises", "depends_on", "symbol_references", "variable_references"):
                if field in record and (not isinstance(record[field], list) or not all(isinstance(item, str) for item in record[field])):
                    errors.append(f"{identifier}_{field}_invalid_references")
    if errors:
        return errors
    records = formal_records(plan)
    definitions = {record["symbol"]: record for record in plan["definitions"] if record.get("symbol")}
    if len(definitions) != len(plan["definitions"]):
        errors.append("definitions_missing_or_duplicate_symbol")
    variable_ids = {record["variable_id"] for record in (variable_claim_model or {}).get("variables", [])}
    for identifier, record in records.items():
        for symbol in set(record.get("symbol_references", [])) | expression_symbols(record):
            if symbol not in definitions:
                errors.append(f"{identifier}_undefined_symbol:{symbol}")
        if variable_claim_model is not None:
            for variable in record.get("variable_references", []):
                if variable not in variable_ids:
                    errors.append(f"{identifier}_unknown_variable:{variable}")
        for dependency in dependency_ids(record, plan):
            if dependency not in records:
                errors.append(f"{identifier}_unknown_dependency:{dependency}")
            elif "obligation_id" in records[dependency]:
                errors.append(f"{identifier}_cannot_use_unresolved_obligation:{dependency}")
    visited: set[str] = set()
    active: set[str] = set()

    def visit(identifier: str) -> None:
        if identifier in active:
            errors.append(f"formal_dependency_cycle:{identifier}")
            return
        if identifier in visited or identifier not in records:
            return
        active.add(identifier)
        for dependency in dependency_ids(records[identifier], plan):
            visit(dependency)
        active.remove(identifier)
        visited.add(identifier)

    for identifier in records:
        visit(identifier)
    if errors:
        return sorted(set(errors))
    for identifier in plan["global_assumption_ids"]:
        if identifier not in records or "assumption_id" not in records[identifier]:
            errors.append(f"invalid_global_assumption:{identifier}")
    targets = {record.get("proposition_id", record.get("lemma_id")): record for record in [*plan["propositions"], *plan["lemmas"]]}
    for identifier, target in targets.items():
        for field in ("statement", "scope", "premises", "conclusion", "quantifiers", "domain_expression", "conclusion_expression", "required_obligation_ids"):
            if field not in target:
                errors.append(f"{identifier}_missing:{field}")
        quantifiers = target.get("quantifiers")
        if not isinstance(quantifiers, list) or any(
            not isinstance(item, Mapping) or not isinstance(item.get("symbol"), str)
            or item.get("sort") not in {"real", "integer", "boolean"}
            or item.get("quantifier") != "forall" for item in quantifiers
        ):
            errors.append(f"{identifier}_invalid_quantifiers")
        obligations = target.get("required_obligation_ids")
        if not isinstance(obligations, list) or not all(isinstance(item, str) for item in obligations):
            errors.append(f"{identifier}_invalid_required_obligation_ids")
            continue
        for obligation_id in target.get("required_obligation_ids", []):
            if obligation_id not in records or records[obligation_id].get("target_id") != identifier:
                errors.append(f"{identifier}_invalid_obligation:{obligation_id}")
    if errors:
        return sorted(set(errors))
    for obligation in plan["proof_obligations"]:
        if obligation.get("target_id") not in targets:
            errors.append(f"{obligation['obligation_id']}_unknown_target")
        elif obligation["obligation_id"] not in targets[obligation["target_id"]].get("required_obligation_ids", []):
            errors.append(f"{obligation['obligation_id']}_not_registered_by_target")
    attempt_ids: set[str] = set()
    for attempt in plan["proof_attempts"]:
        if not isinstance(attempt, Mapping) or not isinstance(attempt.get("steps"), list):
            errors.append("proof_attempt_invalid_shape")
            continue
        target_id = attempt.get("target_id")
        if target_id not in targets:
            errors.append(f"proof_attempt_unknown_target:{target_id}")
            continue
        attempt_id = attempt.get("attempt_id")
        if not attempt_id or attempt_id in attempt_ids:
            errors.append("proof_attempt_invalid_id")
        attempt_ids.add(attempt_id)
        prior: set[str] = set()
        for step in attempt["steps"]:
            if not isinstance(step, Mapping):
                errors.append("proof_step_not_object")
                continue
            step_id = step.get("step_id")
            if not step_id or step_id in prior or step_id in records:
                errors.append(f"proof_step_invalid_id:{step_id}")
            if step.get("status") not in {"proposed", "unverified", "needs_human_input"}:
                errors.append(f"{step_id}_invalid_status")
            for field in ("derived_statement", "rule_or_lemma", "premises"):
                if not step.get(field):
                    errors.append(f"{step_id}_missing:{field}")
            for symbol in set(step.get("symbol_references", [])) | expression_symbols(step):
                if symbol not in definitions:
                    errors.append(f"{step_id}_undefined_symbol:{symbol}")
            for premise in step.get("premises", []):
                if premise not in records and premise not in prior:
                    errors.append(f"{step_id}_unknown_or_future_premise:{premise}")
                elif premise in records:
                    if premise == target_id or target_id in target_dependencies(plan, premise):
                        errors.append(f"{step_id}_circular_proof:{target_id}")
                    if "obligation_id" in records[premise]:
                        errors.append(f"{step_id}_cannot_use_unresolved_obligation:{premise}")
            prior.add(step_id)
        if attempt.get("final_step_id") not in prior:
            errors.append(f"{attempt_id}_unknown_final_step")
    return sorted(set(errors))


def retain_independent_targets(plan, variable_claim_model=None):
    accepted = deepcopy(plan)
    failures = []
    original_targets = [*plan.get("propositions", []), *plan.get("lemmas", [])]
    if not all(isinstance(target, Mapping) for target in original_targets):
        return accepted, validate_formal_plan_v2(accepted, variable_claim_model)
    targets_by_id = {target.get("proposition_id", target.get("lemma_id")): target for target in original_targets}
    for target_id in targets_by_id:
        trial = deepcopy(plan)
        try:
            required = target_dependencies(plan, target_id) | {target_id}
            pending = list(required)
            while pending:
                identifier = pending.pop()
                extra = target_dependencies(plan, identifier) - required
                required.update(extra)
                pending.extend(extra)
        except (ValueError, TypeError, KeyError):
            required = {target_id}
        trial["propositions"] = [target for target in plan["propositions"] if target.get("proposition_id") in required]
        trial["lemmas"] = [target for target in plan["lemmas"] if target.get("lemma_id") in required]
        trial["proof_obligations"] = [record for record in plan["proof_obligations"] if record.get("target_id") in required]
        trial["proof_attempts"] = [record for record in plan["proof_attempts"] if record.get("target_id") in required]
        errors = validate_formal_plan_v2(trial, variable_claim_model)
        if errors:
            failures.append((target_id, errors))
    rejected = {identifier for identifier, _errors in failures}
    if not rejected:
        return accepted, validate_formal_plan_v2(accepted, variable_claim_model)
    accepted["propositions"] = [target for target in accepted["propositions"] if target.get("proposition_id") not in rejected]
    accepted["lemmas"] = [target for target in accepted["lemmas"] if target.get("lemma_id") not in rejected]
    accepted["proof_obligations"] = [record for record in accepted["proof_obligations"] if record.get("target_id") not in rejected]
    accepted["proof_attempts"] = [record for record in accepted["proof_attempts"] if record.get("target_id") not in rejected]
    accepted["status"] = "requires_human_review"
    for identifier, errors in failures:
        accepted["unknown_items"].append({"field_path": f"rejected_targets.{identifier}", "reason": "Target construction was rejected: " + "; ".join(errors), "status": "needs_human_input"})
    return accepted, validate_formal_plan_v2(accepted, variable_claim_model)


def author_formal_payload(plan: Mapping[str, Any]) -> dict[str, Any]:
    return deepcopy({key: value for key, value in plan.items() if key not in {"repair_audit", "raw_response", "request_log"}})


def unresolved_plan_from_definitions(resolution, reason):
    return {
        "schema_version": FORMAL_PLAN_V2, "revision": 1, "applicability": "formal_theory",
        "status": "requires_human_review", "definitions": deepcopy(resolution.get("definitions", [])),
        "model_relations": deepcopy(resolution.get("model_relations", [])), "assumptions": [],
        "propositions": [], "lemmas": [], "proof_obligations": [], "proof_attempts": [],
        "global_assumption_ids": [], "semantic_diagnostics": [],
        "unknown_items": [*deepcopy(resolution.get("unknown_items", [])), {"field_path": "proof_attempts", "reason": reason, "status": "needs_human_input"}],
    }
