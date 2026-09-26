"""Resolve declared mathematical dependencies without inferring facts from prose."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
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


def target_subgraph(plan: Mapping[str, Any], target_id: str) -> dict[str, Any]:
    """Return the smallest canonical plan slice needed by one target."""

    required = target_dependencies(plan, target_id) | {target_id}
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
        required.update(target_dependencies(plan, obligation_id))
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
