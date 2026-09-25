"""Small trusted rule set for checking AST proof steps locally.

The checker intentionally handles only rules whose soundness can be expressed
without invoking an LLM.  Text-only proof steps remain unverified drafts.
"""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
import json
from typing import Any


RULE_ENGINE_VERSION = "formal_rule_engine_v1"


def _canonical(node: Any) -> Any:
    if not isinstance(node, Mapping):
        return node
    if set(node) == {"symbol"} or set(node) == {"number"} or set(node) == {"bool"}:
        return dict(node)
    if set(node) != {"op", "args"} or not isinstance(node.get("args"), list):
        return deepcopy(node)
    operator = node["op"]
    args = [_canonical(item) for item in node["args"]]
    if operator in {"add", "mul", "and", "or", "xor", "iff"}:
        args.sort(key=lambda item: json.dumps(item, sort_keys=True, separators=(",", ":")))
    if operator in {"eq", "ne"}:
        args.sort(key=lambda item: json.dumps(item, sort_keys=True, separators=(",", ":")))
    return {"op": operator, "args": args}


def expressions_equal(left: Any, right: Any) -> bool:
    return _canonical(left) == _canonical(right)


def record_expression(record: Mapping[str, Any]) -> dict[str, Any] | None:
    for field in ("predicate_expression", "conclusion_expression", "derived_expression"):
        value = record.get(field)
        if isinstance(value, Mapping):
            return deepcopy(dict(value))
    return None


def _relation(node: Any) -> tuple[str, list[Any]] | None:
    if not isinstance(node, Mapping) or node.get("op") not in {"eq", "ne", "lt", "le", "gt", "ge"}:
        return None
    args = node.get("args")
    return (str(node["op"]), list(args)) if isinstance(args, list) and len(args) == 2 else None


def _normalized_rule(rule: object) -> str:
    text = str(rule or "").strip().casefold().replace("-", "_").replace(" ", "_")
    aliases = {
        "direct": "assumption_reuse",
        "assumption": "assumption_reuse",
        "assumption_reuse": "assumption_reuse",
        "definition": "definition_unfolding",
        "definition_unfolding": "definition_unfolding",
        "strict_order_implies_weak_order": "order_weakening",
        "order_weakening": "order_weakening",
        "transitivity": "transitivity",
        "contradiction": "contradiction",
        "algebraic_normalization": "algebraic_normalization",
    }
    return aliases.get(text, text)


def _check_order_weakening(premises: list[Any], derived: Any) -> bool:
    if len(premises) != 1:
        return False
    source = _relation(premises[0])
    target = _relation(derived)
    if source is None or target is None:
        return False
    source_op, source_args = source
    target_op, target_args = target
    return (
        (source_op == "gt" and target_op == "ge" or source_op == "lt" and target_op == "le")
        and all(expressions_equal(left, right) for left, right in zip(source_args, target_args))
    )


def _check_transitivity(premises: list[Any], derived: Any) -> bool:
    if len(premises) != 2:
        return False
    first = _relation(premises[0])
    second = _relation(premises[1])
    target = _relation(derived)
    if first is None or second is None or target is None:
        return False
    first_op, first_args = first
    second_op, second_args = second
    target_op, target_args = target
    if not expressions_equal(first_args[1], second_args[0]):
        return False
    if not expressions_equal(first_args[0], target_args[0]) or not expressions_equal(second_args[1], target_args[1]):
        return False
    if first_op == second_op == target_op and target_op in {"eq", "ge", "le"}:
        return True
    if first_op in {"gt", "ge"} and second_op in {"gt", "ge"} and target_op in {"gt", "ge"}:
        return target_op == "gt" if "gt" in {first_op, second_op} else target_op == "ge"
    if first_op in {"lt", "le"} and second_op in {"lt", "le"} and target_op in {"lt", "le"}:
        return target_op == "lt" if "lt" in {first_op, second_op} else target_op == "le"
    return False


def _check_step(rule: str, premises: list[Any], derived: Any, premise_records: list[Mapping[str, Any]]) -> bool:
    if not isinstance(derived, Mapping):
        return False
    normalized = _normalized_rule(rule)
    if normalized == "assumption_reuse":
        return len(premises) == 1 and expressions_equal(premises[0], derived)
    if normalized == "definition_unfolding":
        if len(premise_records) != 1:
            return False
        record = premise_records[0]
        if "definition_id" not in record or not isinstance(record.get("formal_expression"), Mapping):
            return False
        expected = {"op": "eq", "args": [
            {"symbol": record.get("symbol")}, deepcopy(record["formal_expression"])
        ]}
        reverse = {"op": "eq", "args": [expected["args"][1], expected["args"][0]]}
        return expressions_equal(derived, expected) or expressions_equal(derived, reverse)
    if normalized == "order_weakening":
        return _check_order_weakening(premises, derived)
    if normalized == "transitivity":
        return _check_transitivity(premises, derived)
    if normalized == "contradiction":
        if len(premises) != 2:
            return False
        first = {"op": "not", "args": [premises[0]]}
        second = {"op": "not", "args": [premises[1]]}
        return (
            expressions_equal(derived, {"bool": False})
            and (expressions_equal(premises[1], first) or expressions_equal(premises[0], second))
        )
    if normalized == "algebraic_normalization":
        return len(premises) == 1 and expressions_equal(premises[0], derived)
    return False


def verify_proof_attempt(plan: Mapping[str, Any], attempt: Mapping[str, Any]) -> dict[str, Any]:
    """Check one AST-bearing proof attempt and return an auditable result."""

    target_id = str(attempt.get("target_id") or "")
    targets = {
        str(record.get("proposition_id") or record.get("lemma_id")): record
        for collection in ("propositions", "lemmas")
        for record in plan.get(collection, [])
        if isinstance(record, Mapping) and (record.get("proposition_id") or record.get("lemma_id"))
    }
    target = targets.get(target_id)
    if target is None:
        return {"result": "unknown", "limitations": ["unknown_proof_target"]}
    if target.get("required_obligation_ids"):
        return {"result": "unknown", "limitations": ["unresolved_target_obligations"]}
    steps = attempt.get("steps")
    if not isinstance(steps, list) or not steps:
        return {"result": "unknown", "limitations": ["proof_attempt_has_no_steps"]}
    records: dict[str, Mapping[str, Any]] = {}
    for collection, identifier in (
        ("definitions", "definition_id"),
        ("assumptions", "assumption_id"),
        ("propositions", "proposition_id"),
        ("lemmas", "lemma_id"),
        ("proof_obligations", "obligation_id"),
    ):
        records.update({str(item[identifier]): item for item in plan.get(collection, []) if isinstance(item, Mapping) and item.get(identifier)})
    derived_by_id: dict[str, dict[str, Any]] = {}
    step_audits = []
    for step in steps:
        if not isinstance(step, Mapping) or not step.get("step_id"):
            return {"result": "unknown", "limitations": ["invalid_proof_step"]}
        step_id = str(step["step_id"])
        derived = step.get("derived_expression")
        if not isinstance(derived, Mapping):
            step_audits.append({"step_id": step_id, "status": "unverified", "reason": "missing_derived_expression"})
            return {"result": "unknown", "limitations": ["text_only_proof_step"], "step_audits": step_audits}
        premise_ids = [str(item) for item in step.get("premises", [])]
        premise_values: list[Any] = []
        premise_records: list[Mapping[str, Any]] = []
        for premise_id in premise_ids:
            if premise_id in derived_by_id:
                premise_values.append(derived_by_id[premise_id])
            elif premise_id in records:
                value = record_expression(records[premise_id])
                if value is None and "definition_id" not in records[premise_id]:
                    return {"result": "unknown", "limitations": [f"premise_without_expression:{premise_id}"], "step_audits": step_audits}
                if value is not None:
                    premise_values.append(value)
                premise_records.append(records[premise_id])
            else:
                return {"result": "unknown", "limitations": [f"unknown_proof_premise:{premise_id}"], "step_audits": step_audits}
        valid = _check_step(str(step.get("rule_or_lemma") or ""), premise_values, derived, premise_records)
        step_audits.append({"step_id": step_id, "status": "verified" if valid else "unverified", "rule": _normalized_rule(step.get("rule_or_lemma"))})
        if not valid:
            return {"result": "unknown", "limitations": [f"rule_not_verified:{step_id}"], "step_audits": step_audits}
        derived_by_id[step_id] = deepcopy(dict(derived))
    final_id = str(attempt.get("final_step_id") or "")
    final_expression = derived_by_id.get(final_id)
    target_expression = target.get("conclusion_expression")
    if final_expression is None or not isinstance(target_expression, Mapping) or not expressions_equal(final_expression, target_expression):
        return {"result": "unknown", "limitations": ["final_step_does_not_match_target"], "step_audits": step_audits}
    return {
        "result": "passed",
        "evidence_kind": "rule_derivation",
        "step_audits": step_audits,
        "limitations": ["Derived by the bounded local rule set; no proof-assistant certificate."],
    }


def verify_target_proof(plan: Mapping[str, Any], target_id: str) -> dict[str, Any] | None:
    attempts = [
        item for item in plan.get("proof_attempts", [])
        if isinstance(item, Mapping) and str(item.get("target_id") or "") == str(target_id)
    ]
    if not any(any(isinstance(step, Mapping) and isinstance(step.get("derived_expression"), Mapping) for step in attempt.get("steps", [])) for attempt in attempts):
        return None
    results = [verify_proof_attempt(plan, attempt) for attempt in attempts]
    passed = next((item for item in results if item.get("result") == "passed"), None)
    return passed or results[0]


__all__ = ["RULE_ENGINE_VERSION", "expressions_equal", "record_expression", "verify_proof_attempt", "verify_target_proof"]
