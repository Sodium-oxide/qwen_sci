"""Resolve declared mathematical dependencies without inferring facts from prose."""

from __future__ import annotations

from collections.abc import Mapping
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


def dependency_ids(record: Mapping[str, Any], plan: Mapping[str, Any]) -> set[str]:
    references = {
        str(reference)
        for field in ("premises", "depends_on", "assumption_ids")
        for reference in record.get(field, [])
    }
    symbols = set(record.get("symbol_references", [])) | expression_symbols(record)
    symbols.update(item.get("symbol") for item in record.get("quantifiers", []) if isinstance(item, Mapping))
    variables = set(record.get("variable_references", []))
    references.update(
        str(definition["definition_id"])
        for definition in plan.get("definitions", [])
        if definition.get("definition_id") != record.get("definition_id")
        and (definition.get("symbol") in symbols or (
            plan.get("schema_version") != "formal_reasoning_plan_v2"
            and "definition_id" not in record
            and variables.intersection(definition.get("variable_references", []))
        ))
    )
    return references


def target_dependencies(plan: Mapping[str, Any], target_id: str) -> set[str]:
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
            raise ValueError(f"unknown_formal_dependency:{identifier}")
        visited.add(identifier)
        if identifier != target_id and ("lemma_id" in records[identifier] or "proposition_id" in records[identifier]):
            continue
        pending.extend(dependency_ids(records[identifier], plan) - visited)
    return visited - {target_id}


def build_counterexample_target(plan: Mapping[str, Any], target_id: str) -> dict[str, Any]:
    records = formal_records(plan)
    dependencies = target_dependencies(plan, target_id)
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
