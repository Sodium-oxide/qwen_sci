"""Resolve declared mathematical dependencies without inferring facts from prose."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
import re
from typing import Any


COLLECTION_IDS = {
    "definitions": "definition_id",
    "model_relations": "relation_id",
    "assumptions": "assumption_id",
    "propositions": "proposition_id",
    "lemmas": "lemma_id",
    "proof_obligations": "obligation_id",
}


def expression_symbols(value: Any) -> set[str]:
    if isinstance(value, Mapping):
        symbols = {value["symbol"]} if set(value) == {"symbol"} and isinstance(value["symbol"], str) else set()
        for item in value.values():
            symbols.update(expression_symbols(item))
        return symbols
    if isinstance(value, list):
        return set().union(*(expression_symbols(item) for item in value)) if value else set()
    return set()


def expression_variable_ids(value):
    if isinstance(value, Mapping):
        references = {value["variable_id"]} if value.get("op") == "variable_ref" and isinstance(value.get("variable_id"), str) else set()
        if isinstance(value.get("variable_ref"), str):
            references.add(value["variable_ref"])
        for item in value.values():
            references.update(expression_variable_ids(item))
        return references
    if isinstance(value, list):
        return set().union(*(expression_variable_ids(item) for item in value)) if value else set()
    return set()


def symbol_reference_diagnostics(plan: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Return no diagnostics for notation/catalog differences.

    Symbol references remain available to dependency and verification code, while
    notation normalization and exact catalog membership are intentionally advisory
    responsibilities of downstream mathematical tooling.
    """
    return []


def log_symbol_diagnostics(plan, *, logger=None, brief_id="", stage="formal_reasoning_planner"):
    plan["symbol_diagnostics"] = []
    return []


def formal_records(plan: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    records = {
        str(record[identifier]): record
        for collection, identifier in COLLECTION_IDS.items()
        for record in plan.get(collection, [])
        if isinstance(record, Mapping) and record.get(identifier)
    }
    derivation = plan.get("forward_derivation") or {}
    for record in derivation.get("steps", []):
        if isinstance(record, Mapping) and record.get("step_id"):
            records[str(record["step_id"])] = record
    return records


def bound_symbols(record):
    declarations = record.get("quantifiers", []) if isinstance(record, Mapping) else []
    symbols = {item["symbol"] for item in declarations if isinstance(item, Mapping)
               and isinstance(item.get("symbol"), str)} if isinstance(declarations, list) else set()
    bindings = record.get("local_bindings", {}) if isinstance(record, Mapping) else {}
    if isinstance(bindings, Mapping):
        symbols.update(bindings)
    return symbols


def free_expression_symbols(value, bound=()):
    if isinstance(value, Mapping):
        local = set(bound) | bound_symbols(value)
        if value.get("op") in {"forall", "exists", "lambda"}:
            if isinstance(value.get("symbol"), str):
                local.add(value["symbol"])
            symbols = value.get("symbols", [])
            if isinstance(symbols, list):
                local.update(item for item in symbols if isinstance(item, str))
        symbols = {value["symbol"]} - local if set(value) == {"symbol"} and isinstance(value["symbol"], str) else set()
        for field, item in value.items():
            if field not in {"quantifiers", "local_bindings", "object_registry", "construction_archive"}:
                symbols.update(free_expression_symbols(item, local))
        return symbols
    if isinstance(value, list):
        return set().union(*(free_expression_symbols(item, bound) for item in value)) if value else set()
    return set()


def partition_relation_premises(value, *, known_ids=()):
    references, conditions, uninterpreted = [], [], []
    candidates = value if isinstance(value, list) else [value] if value is not None else []
    known = set(known_ids)
    for candidate in candidates:
        if isinstance(candidate, str) and candidate.strip():
            text = candidate.strip()
            if text in known or re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.:/-]*", text):
                references.append(text)
            else:
                conditions.append({"text": text})
        elif isinstance(candidate, Mapping):
            identifiers = [candidate[field] for field in (
                "ref", "object_id", "definition_id", "relation_id", "assumption_id", "lemma_id", "premise_ref", "id",
            ) if field in candidate]
            valid_reference = (bool(identifiers) and isinstance(identifiers[0], str)
                               and bool(identifiers[0].strip()) and all(identifier == identifiers[0] for identifier in identifiers))
            if valid_reference:
                references.append(identifiers[0].strip())
            text = candidate.get("text", candidate.get("condition", candidate.get("statement")))
            expression = candidate.get("formal_expression", candidate.get("expression"))
            has_condition = isinstance(text, str) and bool(text.strip()) or expression is not None
            if has_condition:
                condition = {"text": text.strip() if isinstance(text, str) and text.strip() else "Formal condition supplied by the resolver."}
                if expression is not None:
                    condition["formal_expression"] = deepcopy(expression)
                conditions.append(condition)
            if identifiers and not valid_reference or not identifiers and not has_condition:
                uninterpreted.append(deepcopy(candidate))
        else:
            uninterpreted.append(deepcopy(candidate))
    return list(dict.fromkeys(references)), conditions, uninterpreted


def declared_dependencies(record, *, known_ids=()):
    fields = ("depends_on", "assumption_ids") if "relation_id" in record else ("premises", "depends_on", "assumption_ids")
    references = {reference for field in fields
                  for reference in (record.get(field, []) if isinstance(record.get(field, []), list) else [])
                  if isinstance(reference, str)}
    if "relation_id" in record:
        premise_ids, _, _ = partition_relation_premises(record.get("premises"), known_ids=set(known_ids) | references)
        references.update(premise_ids)
    bindings = record.get("object_bindings", {})
    if isinstance(bindings, Mapping):
        references.update(identifier for identifier in bindings.values() if isinstance(identifier, str))
    steps = record.get("calculation_steps", [])
    local_names = {step["name"] for step in (steps if isinstance(steps, list) else [])
                   if isinstance(step, Mapping) and isinstance(step.get("name"), str)}
    def collect(value):
        if isinstance(value, Mapping):
            for field in ("ref", "object_id", "definition_ref", "lemma_id", "lemma_ref", "assumption_ref", "premise_ref"):
                if isinstance(value.get(field), str) and not (field == "ref" and value[field] in local_names):
                    references.add(value[field])
            for item in value.values():
                collect(item)
        elif isinstance(value, list):
            for item in value:
                collect(item)
    for field in ("formal_expression", "condition_expressions", "predicate_expression", "conclusion_expression",
                  "domain_expression", "derived_expression", "variable_bindings", "lemma_instantiations"):
        collect(record.get(field))
    return references


def resolved_alias_dependencies(record, plan):
    aliases = plan.get("object_registry", {}).get("aliases", {})
    result = set()
    for reference in declared_dependencies(record):
        visited = set()
        while reference in aliases and reference not in visited:
            visited.add(reference)
            reference = aliases[reference]
        result.add(reference)
    return result


def related_context_ids(record, plan):
    explicit_symbols = record.get("symbol_references", [])
    symbols = {symbol for symbol in explicit_symbols if isinstance(symbol, str)} if isinstance(explicit_symbols, list) else set()
    symbols.update(free_expression_symbols(record))
    variables = expression_variable_ids(record)
    if "definition_id" not in record:
        variables.update(reference for reference in record.get("variable_references", []) if isinstance(reference, str))
    explicit_related = record.get("inferred_related_objects", [])
    related = {identifier for identifier in explicit_related if isinstance(identifier, str)} if isinstance(explicit_related, list) else set()
    return related | {str(definition["definition_id"]) for definition in plan.get("definitions", [])
            if isinstance(definition, Mapping) and definition.get("definition_id")
            and definition.get("definition_id") != record.get("definition_id")
            and (definition.get("symbol") in symbols or variables.intersection(definition.get("variable_references", [])))}


def context_dependency_ids(record, plan):
    return dependency_ids(record, plan) | related_context_ids(record, plan)


def dependency_ids(record: Mapping[str, Any], plan: Mapping[str, Any]) -> set[str]:
    if plan.get("schema_version") == "formal_reasoning_plan_v2" or plan.get("object_registry"):
        return resolved_alias_dependencies(record, plan)
    references = {
        str(reference)
        for field in ("premises", "depends_on", "assumption_ids")
        for reference in record.get(field, [])
    }
    symbols = set(record.get("symbol_references", [])) | expression_symbols(record)
    symbols.update(item.get("symbol") for item in record.get("quantifiers", []) if isinstance(item, Mapping))
    variables = set(record.get("variable_references", []))
    encoded_variables = expression_variable_ids(record)
    references.update(
        str(definition["definition_id"])
        for definition in plan.get("definitions", [])
        if definition.get("definition_id") != record.get("definition_id")
        and (definition.get("symbol") in symbols or encoded_variables.intersection(definition.get("variable_references", [])) or (
            plan.get("schema_version") != "formal_reasoning_plan_v2"
            and "definition_id" not in record
            and variables.intersection(definition.get("variable_references", []))
        ))
    )
    return references


def target_dependencies(plan: Mapping[str, Any], target_id: str, *, allow_missing=False) -> set[str]:
    records = formal_records(plan)
    if target_id not in records:
        raise ValueError(f"unknown_formal_target:{target_id}")
    pending = [target_id, *plan.get("global_assumption_ids", [])]
    if "obligation_id" in records[target_id]:
        parent = records.get(records[target_id].get("target_id"), {})
        pending.extend(dependency_ids(parent, plan))
    pending.extend(
        str(record["assumption_id"])
        for record in plan.get("assumptions", [])
        if record.get("is_global") is True
    )
    visited: set[str] = set()
    while pending:
        identifier = pending.pop()
        if identifier in visited:
            continue
        if identifier not in records:
            if allow_missing:
                continue
            raise ValueError(f"unknown_formal_dependency:{identifier}")
        visited.add(identifier)
        if identifier != target_id and ("lemma_id" in records[identifier] or "proposition_id" in records[identifier]):
            continue
        pending.extend(dependency_ids(records[identifier], plan) - visited)
    return visited - {target_id}


def build_counterexample_target(plan: Mapping[str, Any], target_id: str) -> dict[str, Any]:
    records = formal_records(plan)
    dependencies = target_dependencies(plan, target_id, allow_missing=True)
    target = records[target_id]
    assumptions = sorted(identifier for identifier in dependencies if "assumption_id" in records[identifier])
    return {
        "target_claim_id": target_id,
        "scope": target.get("scope", ""),
        "required_assumption_ids": assumptions,
        "dependency_ids": sorted(dependencies),
        "counterexample_condition": {
            "operator": "and",
            "operands": [
                {"target_domain": target_id},
                *[{"assumption_ref": identifier} for identifier in assumptions],
                *[{"premise_ref": identifier} for identifier in target.get("premises", [])],
                {"operator": "not", "operand": {"conclusion_ref": target_id}},
            ],
        },
    }


def target_subgraph(plan: Mapping[str, Any], target_id: str) -> dict[str, Any]:
    """Return the smallest canonical plan slice needed by one target."""

    required = target_dependencies(plan, target_id, allow_missing=True) | {target_id}
    target = formal_records(plan)[target_id]
    required.update(target.get("required_obligation_ids", []))
    required.update(
        record.get("obligation_id") for record in plan.get("proof_obligations", [])
        if isinstance(record, Mapping) and record.get("target_id") == target_id
    )
    required.discard(None)
    obligation_ids = {
        record.get("obligation_id") for record in plan.get("proof_obligations", [])
        if isinstance(record, Mapping)
    }
    for obligation_id in required & obligation_ids:
        required.update(target_dependencies(plan, obligation_id, allow_missing=True))
    records = formal_records(plan)
    pending = list(required)
    while pending:
        identifier = pending.pop()
        record = records.get(identifier)
        if record is None:
            continue
        context_ids = related_context_ids(record, plan) | dependency_ids(record, plan)
        pending.extend(context_ids - required)
        required.update(context_ids)
    collections = {
        "definitions": "definition_id",
        "model_relations": "relation_id",
        "assumptions": "assumption_id",
        "propositions": "proposition_id",
        "lemmas": "lemma_id",
        "proof_obligations": "obligation_id",
    }
    local = {
        "schema_version": plan.get("schema_version"),
        "revision": plan.get("revision", 1),
        "applicability": plan.get("applicability", "formal_theory"),
        "status": plan.get("status", "unverified"),
        "global_assumption_ids": [item for item in plan.get("global_assumption_ids", []) if item in required],
        "proof_attempts": [],
        "semantic_diagnostics": [
            deepcopy(item) for item in plan.get("semantic_diagnostics", [])
            if isinstance(item, Mapping) and (item.get("target_id") in required or not item.get("target_id"))
        ],
        "unknown_items": [
            deepcopy(item) for item in plan.get("unknown_items", [])
            if isinstance(item, Mapping) and (
                not item.get("field_path")
                or str(item.get("field_path")).startswith("variables.")
                or set(str(item.get("field_path")).split(".")) & required
            )
        ],
    }
    for collection, identifier in collections.items():
        local[collection] = [
            deepcopy(record) for record in plan.get(collection, [])
            if isinstance(record, Mapping) and record.get(identifier) in required
        ]
    local["proof_attempts"] = [
        deepcopy(record) for record in plan.get("proof_attempts", [])
        if isinstance(record, Mapping) and record.get("target_id") in required
    ]
    steps = [
        deepcopy(step) for step in plan.get("forward_derivation", {}).get("steps", [])
        if isinstance(step, Mapping)
        and (
            target_id == plan.get("forward_derivation", {}).get("target_proposition_id")
            or step.get("target_id") == target_id
        )
    ]
    proposition_ids = {item.get("proposition_id") for item in local["propositions"]}
    local["forward_derivation"] = {
        "steps": steps,
        "target_proposition_id": target_id if target_id in proposition_ids else "",
        "final_conclusion_step": (
            plan.get("forward_derivation", {}).get("final_conclusion_step", "")
            if target_id == plan.get("forward_derivation", {}).get("target_proposition_id") else ""
        ),
        "final_conclusion": (
            plan.get("forward_derivation", {}).get("final_conclusion", "")
            if target_id == plan.get("forward_derivation", {}).get("target_proposition_id") else ""
        ),
        "status": (
            plan.get("forward_derivation", {}).get("status", "unresolved")
            if target_id == plan.get("forward_derivation", {}).get("target_proposition_id") else "unresolved"
        ),
    }
    return local
