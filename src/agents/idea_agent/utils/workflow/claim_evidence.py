"""Claim provenance checks. Source availability never proves entailment."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import Any

from src.agents.idea_agent.utils.mcts.review_contracts import ReviewIssue, candidate_path, content_hash, snapshot_value


CLAIM_KINDS = {"user_premise", "literature_fact", "design_choice", "hypothesis", "prediction", "observation", "formal_derivation"}


def normalize_claims(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise TypeError("claims must be a list of objects.")
    result = []
    claim_ids: set[str] = set()
    for raw in value:
        if not isinstance(raw, Mapping):
            raise TypeError("Each claim must be an object.")
        if not isinstance(raw.get("text"), str) or not raw["text"].strip():
            raise ValueError("Each claim must contain non-empty text.")
        claim = deepcopy(dict(raw))
        claim["kind"] = raw.get("kind") if raw.get("kind") in CLAIM_KINDS else "unclassified"
        claim["claim_id"] = str(raw.get("claim_id") or "claim:" + content_hash([claim["kind"], raw["text"]])[:20])
        if claim["claim_id"] in claim_ids:
            raise ValueError(f"Duplicate claim_id: {claim['claim_id']}")
        claim_ids.add(claim["claim_id"])
        refs = raw.get("support_refs", [])
        claim["support_refs"] = [str(ref) for ref in refs if isinstance(ref, str)] if isinstance(refs, list) else []
        # A generation response cannot certify its own evidence or support.
        for key in ("verified", "source_exists", "quote_matches", "readable", "supported"):
            claim.pop(key, None)
        result.append(claim)
    return result


def normalize_evidence_records(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list) or any(not isinstance(record, Mapping) for record in value):
        raise TypeError("evidence_records must be a list of objects.")
    return [deepcopy(dict(record)) for record in value]


def evidence_catalog(*contexts: Any) -> dict[str, dict[str, Any]]:
    """Only use source objects supplied by the run, never candidate assertions."""
    result: dict[str, dict[str, Any]] = {}
    def visit(value: Any) -> None:
        if isinstance(value, Mapping):
            sid = value.get("source_id") or value.get("anchor_id") or value.get("paper_id") or value.get("paperId") or value.get("node_id") or value.get("doi")
            if sid:
                if value.get("evidence_id") and value.get("source_sha256") and value.get("quote") and value.get("locator"):
                    # Graph hits retain verified spans rather than full papers.
                    # Several spans can share one source_id; keep all of them
                    # available to the downstream claim audit.
                    previous = result.get(str(sid), {})
                    quotes = list(dict.fromkeys([*previous.get("verified_quotes", []), value["quote"]]))
                    result[str(sid)] = {**dict(value), "text": "\n\n".join(quotes), "verified_quotes": quotes}
                    result[str(value["evidence_id"])] = {**dict(value), "text": value["quote"], "verified_quotes": [value["quote"]]}
                else:
                    result[str(sid)] = dict(value)
            for item in value.values():
                visit(item)
        elif isinstance(value, (list, tuple)):
            for item in value:
                visit(item)
    for context in contexts:
        visit(context)
    return result


def audit_claims(claims: list[dict[str, Any]], records: list[dict[str, Any]], sources: Mapping[str, Any],
                 *, semantic_reviews: list[dict[str, Any]] | None = None,
                 original_request: str = "") -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    audits, issues = [], []
    semantic = {r.get("claim_id"): r for r in semantic_reviews or [] if isinstance(r, Mapping)}
    evidence = {str(r.get("evidence_id") or r.get("source_id")): r for r in records if isinstance(r, Mapping)}
    for index, claim in enumerate(claims):
        issue_start = len(issues)
        path = f"claims[{index}]"
        refs = []
        for ref in claim.get("support_refs", []):
            record = evidence.get(ref, {"source_id": ref})
            source = sources.get(ref) or sources.get(str(record.get("source_id") or ref))
            source = source if isinstance(source, Mapping) else None
            text = str((source or {}).get("text") or (source or {}).get("text_excerpt") or (source or {}).get("full_text") or (source or {}).get("summary") or (source or {}).get("abstract") or "")
            quote = str(record.get("quote") or "")
            refs.append({"evidence_id": ref, "source_exists": source is not None,
                         "locator": record.get("locator"), "locator_supplied": bool(record.get("locator")), "readable": bool(text),
                         "quote_matches": bool(quote and text and (any(quote in q for q in source["verified_quotes"])
                            if source and "verified_quotes" in source else quote in text))})
        review = semantic.get(claim["claim_id"], {})
        support = review.get("support_assessment", "unassessed")
        if support not in {"supported", "unsupported", "unassessed"}:
            support = "unassessed"
        valid_source_ids = set(claim.get("support_refs", [])) | {str(evidence.get(r, {}).get("source_id") or r) for r in claim.get("support_refs", [])}
        def valid_candidate_ref(ref: str) -> bool:
            try:
                return candidate_path(ref).startswith(path + ".") and bool(snapshot_value({"claims": claims}, ref))
            except (KeyError, IndexError, TypeError, ValueError):
                return False
        reviewed_refs = [candidate_path(r) for r in (review.get("evidence_refs") or []) if isinstance(r, str)]
        formal_paths = (path + ".assumptions", path + ".derivation", path + ".proof_obligations")
        formal_support = (claim["kind"] == "formal_derivation" and review.get("rationale")
                          and path + ".derivation" in reviewed_refs
                          and all(valid_candidate_ref(r) and any(r == p or r.startswith(p + "[") for p in formal_paths)
                                  for r in reviewed_refs))
        premise_quote = str(claim.get("source_quote") or "")
        premise_exists = bool(premise_quote and premise_quote in original_request)
        premise_support = premise_exists and (claim["text"] == premise_quote or (
            review.get("rationale") and "task_contract.original_request" in (review.get("evidence_refs") or [])))
        if support == "supported" and not (formal_support or (review.get("rationale") and review.get("evidence_refs")
                and all(r in valid_source_ids for r in review.get("evidence_refs", []))
                and all(r["source_exists"] and r["readable"] and r["quote_matches"] and r["locator_supplied"] for r in refs)
                and refs) or (claim["kind"] == "user_premise" and premise_support)):
            support = "unassessed"
        if support == "unsupported" and not (review.get("rationale") and review.get("evidence_refs")):
            support = "unassessed"
        audits.append({"claim_id": claim["claim_id"], "kind": claim["kind"], "sources": refs,
                       "support_assessment": support, "rationale": review.get("rationale", "")})
        kind, origin, reason, hint = "", "candidate", "", ""
        if claim["kind"] in {"literature_fact", "observation"} and not any(r["source_exists"] and r["readable"] for r in refs):
            kind, origin = "source_unavailable", "dependency"
            reason, hint = "An asserted factual claim has no readable supplied source.", "Acquire the source or accurately scope/reclassify the claim."
        elif claim["kind"] in {"hypothesis", "prediction"} and not claim.get("validation_plan"):
            kind, reason, hint = "validation_gap", "A proposed claim has no validation path.", "State a discriminating observation, test, or proof obligation."
        elif claim["kind"] == "formal_derivation" and not (claim.get("assumptions") and claim.get("derivation") and claim.get("proof_obligations")):
            kind, reason, hint = "proof_gap", "Formal support is incomplete.", "Specify assumptions, derivation and proof obligations."
        elif claim["kind"] == "unclassified":
            kind, reason, hint = "claim_overreach", "The claim's epistemic type is unclassified.", "Classify the claim without promoting a proposal to an observed fact."
        elif claim["kind"] == "user_premise" and not premise_exists:
            kind, reason, hint = "premise_provenance_gap", "The claimed user premise has no exact passage in the original request.", "Supply the original user passage or classify this as a proposed assumption."
        elif claim["kind"] == "user_premise" and not premise_support:
            kind, origin, reason, hint = "premise_support_unassessed", "context", "The premise passage exists; its relation to this claim needs review.", "Review the claim against the original task passage."
        if kind:
            issues.append(ReviewIssue.from_payload({"kind": kind, "origin": origin, "target_path": path,
                "rationale": reason, "repair_hint": hint, "evidence_refs": claim.get("support_refs", [])}).to_dict())
        if claim["kind"] == "formal_derivation" and not kind and support != "supported":
            issues.append(ReviewIssue.from_payload({"kind": "proof_support_unassessed" if support == "unassessed" else "proof_gap",
                "origin": "context" if support == "unassessed" else "candidate", "target_path": path,
                "rationale": str(review.get("rationale") or "Derivation structure is present; validity still requires semantic review."),
                "repair_hint": "Check each proof obligation against the assumptions and derivation."}).to_dict())
        if claim["kind"] in {"literature_fact", "observation"} and any(r["readable"] for r in refs):
            if not any(r["quote_matches"] for r in refs):
                issues.append(ReviewIssue.from_payload({"kind": "quote_mismatch", "target_path": path,
                    "rationale": "The supplied quotation does not match the readable source text.",
                    "repair_hint": "Provide an exact source passage with a locator."}).to_dict())
            if refs and not all(r["locator_supplied"] for r in refs):
                issues.append(ReviewIssue.from_payload({"kind": "source_locator_missing", "target_path": path,
                    "rationale": "The source passage has no location reference.",
                    "repair_hint": "Provide a section, page, paragraph, or other source location."}).to_dict())
            if support != "supported":
                issues.append(ReviewIssue.from_payload({"kind": "unsupported_claim" if support == "unsupported" else "claim_support_unassessed",
                    "origin": "candidate" if support == "unsupported" else "context", "target_path": path,
                    "status": "open" if support == "unsupported" else "unassessed",
                    "rationale": str(review.get("rationale") or "Source exists; semantic support has not been assessed."),
                    "repair_hint": "Review the claim against the cited passage and its applicability."}).to_dict())
        link = claim.get("measurement_link")
        if claim.get("relation_type") in {"causal", "measurement"}:
            if not isinstance(link, Mapping) or not all(link.get(k) for k in ("construct", "observable", "linking_argument", "conditions")):
                issues.append(ReviewIssue.from_payload({"kind": "unsupported_causal_link" if claim.get("relation_type") == "causal" else "measurement_construct_mismatch", "target_path": path,
                    "rationale": "The construct/observable link or its conditions are unspecified.",
                    "repair_hint": "Specify construct, observable, linking argument, and validity conditions."}).to_dict())
            elif (review.get("link_assessment") != "supported" or not review.get("link_rationale")
                  or not review.get("evidence_refs")
                  or not all(r in valid_source_ids or valid_candidate_ref(str(r)) for r in review["evidence_refs"])):
                rejected = review.get("link_assessment") == "unsupported"
                issues.append(ReviewIssue.from_payload({"kind": "unsupported_causal_link" if rejected and claim.get("relation_type") == "causal" else "measurement_construct_mismatch" if rejected else "link_support_unassessed",
                    "origin": "candidate" if rejected else "context", "target_path": path,
                    "rationale": str(review.get("link_rationale") or "The proposed construct/observable link has not been semantically reviewed."),
                    "repair_hint": "Assess the link and its conditions, separately from source availability."}).to_dict())
        for issue_index in range(issue_start, len(issues)):
            issue = {**issues[issue_index], "checker": "claim_contract_v2", "claim_id": claim["claim_id"]}
            # List positions locate the current text; the ID follows a claim across reordering.
            issue.pop("issue_id", None)
            issues[issue_index] = ReviewIssue.from_payload(issue).to_dict()
    return audits, issues


def claim_instructions() -> str:
    return """
Return claims as [{claim_id, kind: user_premise|literature_fact|design_choice|hypothesis|prediction|observation|formal_derivation,
text, support_refs: [evidence IDs], source_quote (for user premises), validation_plan, applicability, assumptions, derivation, proof_obligations}].
For causal/measurement claims include relation_type and measurement_link with construct, observable,
linking_argument, conditions. Return evidence_records as [{evidence_id, source_id, locator, quote}].
Use only source IDs supplied in the context; source existence and semantic support are separate.
Do not mark sources or claims verified. Unperformed tests remain proposals/predictions.
"""
