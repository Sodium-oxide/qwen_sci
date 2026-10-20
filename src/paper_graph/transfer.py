"""Semantic transfer review after domain and score eligibility checks."""
from __future__ import annotations

from typing import Any

from src.paper_graph.repository import json_text


def transfer_prompt(target: dict[str, Any], hits: tuple[dict[str, Any], ...]) -> str:
    return """Assess whether each retrieved contribution can be transferred to the target idea.
Different discipline and high similarity are only retrieval conditions. Inspect the source structure,
source assumptions and boundary conditions against the target. Do not invent source conditions.
An unstated or unassessed source condition must be unknown, with decision uncertain.
Use evidence_id values from supplied source evidence_records. In every check include source_quote,
an exact contiguous substring of that evidence record supporting the source relation/condition.
A compatible proposal remains a
hypothesis: state concrete validation_obligations. Do not claim the target has been experimentally verified.
Return STRICT JSON {"reviews": [{"node_id": "retrieved node ID", "decision": "compatible|incompatible|uncertain",
"rationale": "reason", "structure_mapping": [{"source": "source relation", "target": "target relation",
"rationale": "why the relation transfers", "evidence_id": "source evidence ID", "source_quote": "exact supporting source text"}],
"assumption_checks": [{"source_assumption": "condition stated in source", "target_condition": "target condition",
"assessment": "satisfied|violated|unknown", "rationale": "reason", "evidence_id": "source evidence ID", "source_quote": "exact source assumption text"}],
"boundary_checks": [{"source_boundary": "source applicability limit", "target_condition": "target condition",
"assessment": "satisfied|violated|unknown", "rationale": "reason", "evidence_id": "source evidence ID", "source_quote": "exact source boundary text"}],
"validation_obligations": ["a discriminating observation or proof obligation"]}]}.
Return one review per retrieved node. Only a compatible decision with all three checks grounded
and no unknown/violated condition qualifies for this operator.
TARGET:\n""" + json_text(target) + "\nSOURCES:\n" + json_text(hits)


def qualify_transfer(hits: tuple[dict[str, Any], ...], payload: Any) -> tuple[tuple[dict[str, Any], ...], list[dict[str, Any]]]:
    reviews = payload.get("reviews") if isinstance(payload, dict) else None
    if not isinstance(reviews, list):
        raise ValueError("Transfer review requires a reviews array.")
    by_id = {}
    for review in reviews:
        if not isinstance(review, dict) or not review.get("node_id") or review["node_id"] in by_id:
            raise ValueError("Transfer review contains a missing or duplicate node ID.")
        by_id[review["node_id"]] = review
    expected = {str(h.get("node_id")) for h in hits}
    if set(by_id) != expected:
        raise ValueError("Transfer review IDs must exactly match retrieved nodes.")
    qualified, audits = [], []
    for hit in hits:
        review = by_id[str(hit["node_id"])]
        if review.get("decision") not in {"compatible", "incompatible", "uncertain"}:
            raise ValueError("Transfer review contains an invalid decision.")
        core = hit.get("core_node") or {}
        source_records = [*(core.get("evidence_records") or [])]
        for component in core.get("components") or []:
            source_records.extend(component.get("evidence_records") or [])
        evidence_by_id = {r.get("evidence_id"): r for r in source_records if isinstance(r, dict)
                          and r.get("quote") and r.get("locator")}
        reasons = []
        if not isinstance(review.get("rationale"), str) or not review["rationale"].strip():
            reasons.append("missing_rationale")
        for key, fields in (("structure_mapping", ("source", "target", "rationale")),
                            ("assumption_checks", ("source_assumption", "target_condition", "rationale")),
                            ("boundary_checks", ("source_boundary", "target_condition", "rationale"))):
            checks = review.get(key)
            if not isinstance(checks, list) or not checks:
                reasons.append("missing_" + key)
                continue
            for check in checks:
                if not isinstance(check, dict) or not all(isinstance(check.get(f), str) and check[f].strip() for f in fields):
                    reasons.append("incomplete_" + key)
                    continue
                cited = evidence_by_id.get(check.get("evidence_id"))
                quote = check.get("source_quote")
                if not cited or not isinstance(quote, str) or not quote.strip() or quote not in cited["quote"]:
                    reasons.append("ungrounded_" + key)
                if key != "structure_mapping" and check.get("assessment") != "satisfied":
                    reasons.append("unmet_" + key)
        obligations = review.get("validation_obligations")
        if not isinstance(obligations, list) or not obligations or any(not isinstance(v, str) or not v.strip() for v in obligations):
            reasons.append("missing_validation_obligations")
        accepted = review["decision"] == "compatible" and not reasons
        audits.append({**review, "qualified": accepted, "contract_issues": sorted(set(reasons))})
        if accepted:
            qualified.append({**hit, "transfer_review": review})
    return tuple(qualified), audits
