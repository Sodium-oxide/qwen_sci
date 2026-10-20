from __future__ import annotations

import json
import hashlib
from collections.abc import Mapping
from copy import deepcopy
from typing import Any


_TASK_MODES = {"idea_generation", "idea_refinement", "protocol_design"}
_EXPLICIT_SCOPE_SOURCES = {"config_explicit", "input_explicit", "user_explicit", "explicit"}
_TASK_MARKER = "== Original user task contract =="


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def refinement_scope_context(
    scope: Any,
    source: Any,
    proposed_scope: Any = "",
) -> dict[str, str]:
    scope_text = _text(scope)
    scope_source = _text(source)
    explicit = scope_source in _EXPLICIT_SCOPE_SOURCES
    return {
        "refinement_scope": scope_text if explicit else "",
        "refinement_scope_source": scope_source or "empty",
        "proposed_scope": _text(proposed_scope) or (scope_text if not explicit else ""),
    }


def _quoted_requirements(value: Any, original_request: str, kind: str = "deliverable") -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    requirements: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in value:
        quote = _text(item.get("source_quote")) if isinstance(item, Mapping) else _text(item)
        if not quote or quote not in original_request or quote in seen:
            continue
        seen.add(quote)
        requirements.append({
            "requirement_id": "req:" + hashlib.sha256((kind + "\n" + quote).encode()).hexdigest()[:20],
            "requirement_kind": kind, "text": quote, "source_quote": quote, "source": "user_input",
            "acceptance_description": (_text(item.get("acceptance_description")) or quote) if isinstance(item, Mapping) else quote,
        })
    return requirements


def build_task_contract(
    *,
    original_request: str = "",
    topic: str = "",
    interpretation: Any = None,
    refinement_scope: str = "",
    refinement_scope_source: str = "",
) -> dict[str, Any]:
    request = _text(original_request) or _text(topic)
    extracted = interpretation if isinstance(interpretation, Mapping) else {}
    scope_context = refinement_scope_context(refinement_scope, refinement_scope_source)
    mode = _text(extracted.get("task_mode"))
    mode_quote = _text(extracted.get("task_mode_source_quote"))
    if mode_quote not in request:
        mode_quote = ""
    if mode == "idea_refinement" and not mode_quote and not scope_context["refinement_scope"]:
        mode = "idea_generation"
    if mode not in _TASK_MODES:
        mode = "idea_refinement" if scope_context["refinement_scope"] else "idea_generation"
    constraints = _quoted_requirements(extracted.get("user_constraints"), request, "constraint")
    if scope_context["refinement_scope"]:
        constraints = [item for item in constraints if item["text"] != scope_context["refinement_scope"]]
        constraints.append({
            "requirement_id": "req:" + hashlib.sha256(("constraint\n" + scope_context["refinement_scope"]).encode()).hexdigest()[:20],
            "requirement_kind": "constraint",
            "acceptance_description": scope_context["refinement_scope"],
            "text": scope_context["refinement_scope"],
            "source_quote": scope_context["refinement_scope"],
            "source": scope_context["refinement_scope_source"],
        })
    status = _text(extracted.get("extraction_status"))
    if status not in {"complete", "partial", "failed"}:
        status = "partial"
    lists_valid = all(isinstance(extracted.get(key), list) for key in ("required_deliverables", "user_constraints", "problem_premises"))
    quotes_valid = all(
        isinstance(item, Mapping) and bool(_text(item.get("source_quote")))
        and (_text(item.get("source_quote")) in request or (
            key == "user_constraints" and bool(scope_context["refinement_scope"])
            and _text(item.get("source_quote")) == scope_context["refinement_scope"]
            and _text(item.get("source")) == scope_context["refinement_scope_source"]
        ))
        for key in ("required_deliverables", "user_constraints", "problem_premises")
        for item in (extracted.get(key) if isinstance(extracted.get(key), list) else [])
    )
    if status == "complete" and not (lists_valid and quotes_valid):
        status = "partial"
    return {
        "schema_version": 2,
        "original_request": request,
        "task_mode": mode,
        "task_mode_source_quote": mode_quote,
        "extraction_status": status,
        "extraction_errors": list(extracted.get("extraction_errors") or []),
        "required_deliverables": _quoted_requirements(extracted.get("required_deliverables"), request, "deliverable"),
        "user_constraints": constraints,
        "problem_premises": _quoted_requirements(extracted.get("problem_premises"), request, "premise"),
    }


def with_task_contract(
    prompt: str,
    contract: Any,
    *,
    scope: Any = "",
    scope_source: Any = "",
    proposed_scope: Any = "",
) -> str:
    if prompt.startswith(_TASK_MARKER):
        return prompt
    task = contract if isinstance(contract, Mapping) else {}
    if not task.get("original_request"):
        return prompt
    task = build_task_contract(
        original_request=_text(task.get("original_request")),
        interpretation=task,
        refinement_scope=_text(scope),
        refinement_scope_source=_text(scope_source),
    )
    scope_context = refinement_scope_context(scope, scope_source, proposed_scope)
    return (
        _TASK_MARKER + "\n"
        + json.dumps(dict(task), ensure_ascii=False, default=str)
        + "\n== Scope provenance ==\n"
        + json.dumps(scope_context, ensure_ascii=False)
        + "\nTask policy:\n"
        "- The original user request defines the research object, objective, explicit constraints, and deliverables. "
        "The extracted lists are aids; preserve requirements in the original request even if extraction missed them.\n"
        "- Explore mechanisms, hypotheses, alternatives, and methods within that task. Only explicit user/config "
        "refinement constraints are hard edit boundaries. Model-proposed scopes remain revisable.\n"
        "- Survey gaps, review notes, and evidence limits inform reasoning; they do not add user prohibitions or "
        "remove requested decisions. Do not replace a requested design or prediction with repeated disclaimers.\n"
        "- Distinguish literature facts, user premises, proposed design choices, hypotheses, predictions, and observed results. "
        "Give concrete choices and rationale; label predictions and proposed values and state how to test them. "
        "Never fabricate sources, reported values, or observed results.\n"
        "- A missing source is a retrieval need, not proof of a scientific gap. Localize unresolved details and "
        "continue the supported parts. Do not invent problems, consensus, counterexamples, or gap IDs to fill a list.\n"
        "- Perform the current stage and keep its requested output schema. For idea generation or revision, "
        "include task-required decisions and testable predictions in the existing method/hypothesis fields. "
        "Detailed execution can be handed to Experiment Agent, but explicitly requested scientific decisions "
        "must remain concrete. Respect the original request when a default workflow preference conflicts with it.\n\n"
        + prompt
    )


def survey_evidence_for_prompt(handoff: Any) -> dict[str, Any]:
    if not isinstance(handoff, Mapping):
        return {}
    evidence = {
        key: deepcopy(value)
        for key, value in handoff.items()
        if key not in {"constraints", "scope"}
    }
    if isinstance(handoff.get("scope"), Mapping):
        evidence["survey_coverage"] = deepcopy(handoff["scope"])
    return evidence
