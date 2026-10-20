"""Domain-independent state, review, and delivery contracts for idea search.

Scientific content and operational observations have separate identities.  None
of the helpers infer scientific truth from a tool status or a defect label.
"""

from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from dataclasses import asdict, dataclass
from typing import Any, Iterable, Mapping


REVIEW_CONTRACT_VERSION = "2"
MAX_SNAPSHOT_BYTES = 4 * 1024 * 1024
CONTENT_FIELDS = (
    "title", "abstract", "core_contribution", "method", "risks", "components",
    "component_explanations", "root_domains", "discipline_resolution",
    "scientific_intervention", "paper_graph_context", "claims", "evidence_records",
)
DIAGNOSTIC_FIELDS = {
    "profile_drift", "review_issues", "review_coverage", "retrieval_events",
    "dependency_rechecks", "changed_paths", "parent_content_hash",
    "route_contract_incomplete_fields", "route_contract_noop_fields", "route_contract_parent_values",
}
DEPENDENT_FIELDS = {
    "central_hypothesis": ("evidence_basis", "discriminating_observation", "boundary_or_failure_condition", "claims"),
    "mechanism_or_relation": ("evidence_basis", "discriminating_observation", "boundary_or_failure_condition", "claims"),
    "expected_mechanism": ("evidence_basis", "discriminating_observation", "boundary_or_failure_condition", "claims"),
    "scientific_object": ("evidence_basis", "discriminating_observation", "claim_scope", "claims"),
    "intervention_or_transformation": ("discriminating_observation", "boundary_or_failure_condition", "claims"),
}


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def content_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _without_diagnostics(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(k): _without_diagnostics(v) for k, v in value.items() if k not in DIAGNOSTIC_FIELDS}
    if isinstance(value, (list, tuple)):
        return [_without_diagnostics(v) for v in value]
    return value


def scientific_content(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Preserve symbol case, all method text, and all claim/evidence content."""
    return deepcopy(_without_diagnostics({key: payload[key] for key in CONTENT_FIELDS if key in payload}))


def validate_snapshot(payload: Mapping[str, Any]) -> None:
    if len(canonical_json(payload).encode("utf-8")) > MAX_SNAPSHOT_BYTES:
        raise ValueError(f"Scientific snapshot exceeds {MAX_SNAPSHOT_BYTES} bytes; store large artifacts by reference.")


def path_present(path: str, included: Iterable[str]) -> bool:
    return any(p == "$" or path == p or path.startswith(p + ".") or path.startswith(p + "[") for p in included)


def candidate_path(value: Any) -> str:
    path = str(value or "$")
    return path.removeprefix("$.candidate.").removeprefix("candidate.")


def snapshot_value(snapshot: Any, path: str) -> Any:
    """Resolve a citation path without evaluating model-supplied expressions."""
    path = candidate_path(path)
    if path == "$":
        return snapshot
    if not re.fullmatch(r"[^.\[\]]+(?:\[\d+\]|\.[^.\[\]]+)*", path):
        raise KeyError(path)
    value = snapshot
    for token in re.findall(r"[^.\[\]]+", path):
        value = value[int(token)] if isinstance(value, list) and token.isdigit() else value[token]
    return value


def progress_hash(payload: Mapping[str, Any]) -> str:
    content = scientific_content(payload)
    content.pop("title", None)
    return content_hash(content)


@dataclass(frozen=True)
class ReviewIssue:
    issue_id: str
    kind: str
    origin: str
    target_path: str
    requirement_id: str | None = None
    status: str = "open"
    rationale: str = ""
    evidence_refs: tuple[str, ...] = ()
    repair_hint: str = ""
    severity: str = "material"
    rechecked: bool = False
    checker: str = ""
    claim_id: str | None = None

    @classmethod
    def from_payload(cls, raw: Mapping[str, Any]) -> "ReviewIssue":
        kind = str(raw.get("kind") or "validation_gap")
        origin = str(raw.get("origin") or "candidate")
        origin = origin if origin in {"candidate", "context", "dependency"} else "context"
        path = candidate_path(raw.get("target_path"))
        requirement = str(raw.get("requirement_id") or "") or None
        claim_id = str(raw.get("claim_id") or "") or None
        identity = [kind, origin, claim_id or path, requirement]
        status = str(raw.get("status") or "open")
        return cls(
            issue_id=str(raw.get("issue_id") or "issue:" + content_hash(identity)[:20]),
            kind=kind, origin=origin, target_path=path, requirement_id=requirement,
            status=status if status in {"open", "resolved", "unassessed"} else "unassessed",
            rationale=str(raw.get("rationale") or ""),
            evidence_refs=tuple(candidate_path(x) for x in (raw.get("evidence_refs") or []) if isinstance(x, str)),
            repair_hint=str(raw.get("repair_hint") or ""),
            severity=str(raw.get("severity") or "material"),
            rechecked=raw.get("rechecked") is True,
            checker=str(raw.get("checker") or ""),
            claim_id=claim_id,
        )

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "evidence_refs": list(self.evidence_refs)}


def reconcile_issues(
    previous: Iterable[Mapping[str, Any]], incoming: Iterable[Mapping[str, Any]],
    *, included_paths: Iterable[str], complete: bool,
    invalidated_paths: Iterable[str] = (),
    valid_evidence_refs: Iterable[str] | None = None,
) -> list[dict[str, Any]]:
    """Absence from a review is never evidence of resolution."""
    included_paths = tuple(included_paths)
    valid_refs = set(valid_evidence_refs) if valid_evidence_refs is not None else None
    ledger = {issue.issue_id: issue.to_dict() for raw in previous if isinstance(raw, Mapping) for issue in [ReviewIssue.from_payload(raw)]}
    for value in ledger.values():
        if value["status"] == "resolved" and any(
            path_present(value["target_path"], [p]) or path_present(p, [value["target_path"]])
            for p in invalidated_paths
        ):
            value.update(status="unassessed", rechecked=False)
    for raw in incoming:
        if not isinstance(raw, Mapping):
            continue
        issue = ReviewIssue.from_payload(raw)
        value = issue.to_dict()
        visible = complete if issue.target_path == "$" else path_present(issue.target_path, included_paths)
        if issue.status == "resolved" and not (
            visible and issue.rechecked and issue.rationale and issue.evidence_refs
            and all((ref in valid_refs) if valid_refs is not None else path_present(ref, included_paths)
                    for ref in issue.evidence_refs)
        ):
            # An unsupported closure must not overwrite a still-open issue.
            if issue.issue_id in ledger:
                continue
            value["status"] = "unassessed"
        if issue.origin == "candidate" and not visible:
            value.update(origin="context", status="unassessed")
            value["repair_hint"] = "Review the omitted candidate field before judging it."
            if issue.issue_id in ledger:
                # Preserve the old scientific issue; attach a separate coverage need.
                value["issue_id"] = "issue:" + content_hash([issue.kind, "context", issue.target_path, issue.requirement_id])[:20]
        ledger[value["issue_id"]] = value
    return list(ledger.values())


def active_defects(issues: Iterable[Mapping[str, Any]]) -> list[str]:
    return list(dict.fromkeys(
        str(issue["kind"]) for issue in issues
        if issue.get("origin") == "candidate" and issue.get("status") == "open"
    ))


def changed_paths(before: Any, after: Any, prefix: str = "") -> list[str]:
    if isinstance(before, Mapping) and isinstance(after, Mapping):
        paths: list[str] = []
        for key in sorted(set(before) | set(after)):
            path = f"{prefix}.{key}" if prefix else str(key)
            if key not in before or key not in after:
                paths.append(path)
            else:
                paths.extend(changed_paths(before[key], after[key], path))
        return paths
    return [] if before == after else [prefix or "$"]


def dependency_rechecks(paths: Iterable[str]) -> list[str]:
    result: list[str] = []
    for path in paths:
        field = path.rsplit(".", 1)[-1]
        prefix = path.rsplit(".", 1)[0] + "." if "." in path else ""
        result.extend(prefix + dep for dep in DEPENDENT_FIELDS.get(field, ()))
        if field in {"method", "core_contribution", "claims"}:
            result.extend(["claims", "scientific_intervention.hypothesis_contract.evidence_basis"])
    return list(dict.fromkeys(result))


def apply_field_updates(parent: Mapping[str, Any], delta: Mapping[str, Any], expected_hash: str) -> dict[str, Any]:
    """Apply explicit field updates against an exact parent, including clears."""
    if delta.get("parent_content_hash") != expected_hash:
        raise ValueError("Field update parent_content_hash does not match the parent snapshot.")
    result = deepcopy(dict(parent))
    updates = delta.get("field_updates")
    if not isinstance(updates, Mapping):
        raise ValueError("field_updates must be a mapping of candidate field paths to values.")
    for path, value in updates.items():
        parts = str(path).split(".")
        if parts[0] not in CONTENT_FIELDS or any(not p or p.startswith("_") for p in parts):
            raise ValueError(f"Unsupported scientific field update: {path}")
        if str(path) in {"scientific_intervention.hypothesis_contract.claims", "scientific_intervention.hypothesis_contract.evidence_records"}:
            raise ValueError("Update the canonical top-level claims/evidence_records fields.")
        target = result
        for part in parts[:-1]:
            if part not in target:
                target[part] = {}
            if not isinstance(target[part], dict):
                raise ValueError(f"Field update traverses a non-object: {path}")
            target = target[part]
        target[parts[-1]] = deepcopy(value)
    validate_snapshot(result)
    return result


def required_items(contract: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [dict(item) for key in ("required_deliverables", "user_constraints")
            for item in (contract.get(key) or []) if isinstance(item, Mapping)]


def normalize_requirement_reviews(
    reviews: Iterable[Mapping[str, Any]], contract: Mapping[str, Any],
    *, included_paths: Iterable[str], complete: bool,
) -> list[dict[str, Any]]:
    known = {str(r["requirement_id"]): r for r in required_items(contract) if r.get("requirement_id")}
    result: dict[str, dict[str, Any]] = {}
    for review in reviews or []:
        if not isinstance(review, Mapping):
            continue
        rid = str(review.get("requirement_id") or "")
        if rid not in known:
            continue
        status = review.get("status", "unassessed")
        refs = [candidate_path(p) for p in (review.get("candidate_paths") or []) if isinstance(p, str)]
        if status not in {"satisfied", "missing", "unassessed"}:
            status = "unassessed"
        if status == "satisfied" and not (review.get("rationale") and refs and all(path_present(p, included_paths) for p in refs)):
            status = "unassessed"
        if status == "missing" and not complete:
            status = "unassessed"
        result[rid] = {"requirement_id": rid, "status": status, "candidate_paths": refs,
                       "rationale": str(review.get("rationale") or "")}
    for rid in known:
        result.setdefault(rid, {"requirement_id": rid, "status": "unassessed", "candidate_paths": [], "rationale": "Not reviewed."})
    return list(result.values())


def delivery_assessment(evaluation: Any, contract: Mapping[str, Any], *, current_content_hash: str | None = None) -> dict[str, Any]:
    requirements = required_items(contract)
    reviews = {r.get("requirement_id"): r for r in getattr(evaluation, "requirement_reviews", [])}
    unresolved = [r for r in requirements if reviews.get(r.get("requirement_id"), {}).get("status") != "satisfied"]
    issues = [i for i in getattr(evaluation, "review_issues", [])
              if i.get("status") != "resolved" and i.get("severity") != "minor"]
    coverage = getattr(evaluation, "review_coverage", {})
    extraction = contract.get("extraction_status", "partial")
    reasons = []
    if contract.get("original_request") and extraction != "complete":
        reasons.append("Task requirements have not been completely extracted.")
    if not coverage.get("complete"):
        reasons.append("Candidate review is incomplete.")
    if current_content_hash is not None and coverage.get("content_hash") != current_content_hash:
        reasons.append("The current scientific content does not match the reviewed snapshot.")
    if unresolved:
        reasons.append("Explicit task requirements remain unsatisfied or unassessed.")
    if issues:
        reasons.append("Material review issues remain unresolved.")
    return {"delivery_ready": not reasons, "status": "ready" if not reasons else "partial",
            "unresolved_requirements": unresolved, "unresolved_issues": issues, "reasons": reasons,
            "reviewed_content_hash": coverage.get("content_hash"), "task_hash": content_hash(contract)}


def invalidate_delivery_on_rewrite(before: Mapping[str, Any], after: dict[str, Any], *, reason: str) -> None:
    """A downstream rewrite cannot inherit the reviewed candidate's acceptance."""
    if not isinstance(before, Mapping) or not before.get("delivery", {}).get("delivery_ready"):
        return
    hypothesis = before.get("scientific_intervention", {}).get("hypothesis_contract", {})
    changed = scientific_content(before) != scientific_content(after)
    changed = changed or any(before.get(k, hypothesis.get(k)) != after.get(k, hypothesis.get(k)) for k in hypothesis)
    changed = changed or any(before.get(k) != after.get(k) for k in ("scientific_spec", "algorithm", "introduction"))
    if changed:
        after["delivery"] = {**deepcopy(before["delivery"]), "delivery_ready": False, "status": "partial",
                             "reasons": [*before["delivery"].get("reasons", []), reason]}
        after["search_status"] = "partial"


def transition_reward(parent: Any, child: Any, *, action_cost: float = 0.0) -> float:
    """Skill credit measures improvement; tree backup retains node value."""
    if parent is None:
        return 0.0
    if not all(getattr(e, "review_coverage", {}).get("complete", True) for e in (parent, child)):
        return 0.0
    old = {i["issue_id"] for i in getattr(parent, "review_issues", []) if i.get("origin") == "candidate" and i.get("status") == "open"}
    resolved = {i["issue_id"] for i in getattr(child, "review_issues", []) if i.get("status") == "resolved" and i.get("rechecked")}
    new = {i["issue_id"] for i in getattr(child, "review_issues", []) if i.get("origin") == "candidate" and i.get("status") == "open"}
    before = {r["requirement_id"] for r in getattr(parent, "requirement_reviews", []) if r.get("status") == "satisfied"}
    after = {r["requirement_id"] for r in getattr(child, "requirement_reviews", []) if r.get("status") == "satisfied"}
    gain = max(-1.0, min(1.0, (child.composite - parent.composite) / 5.0))
    gain += 0.25 * len(old & resolved) + 0.2 * len(after - before)
    gain -= 0.25 * len(new - old) + 0.2 * len(before - after)
    supported_before = {r.get("claim_id") for r in getattr(parent, "claim_reviews", []) if r.get("support_assessment") == "supported"}
    supported_after = {r.get("claim_id") for r in getattr(child, "claim_reviews", []) if r.get("support_assessment") == "supported"}
    gain += 0.15 * len(supported_after - supported_before) - 0.15 * len(supported_before - supported_after)
    return max(0.0, min(1.0, gain - max(0.0, action_cost)))


def review_instructions() -> str:
    return """
Review contract (in addition to the existing scoring JSON):
- Return review_issues: [{issue_id, kind, origin: candidate|context|dependency,
  target_path, requirement_id, status: open|resolved|unassessed, rationale,
  evidence_refs: [candidate paths or source IDs], repair_hint, severity, rechecked}].
- Return requirement_reviews: [{requirement_id, status: satisfied|missing|unassessed,
  candidate_paths: [paths containing the requested content], rationale}].
- Return reviewed_issue_ids and reviewed_claim_ids for issues/claims actually rechecked.
- Return claim_reviews: [{claim_id, support_assessment: supported|unsupported|unassessed,
  evidence_refs: [source IDs or candidate paths], rationale,
  link_assessment: supported|unsupported|unassessed, link_rationale}].
- Return review_notes summarizing the content actually examined and cross-field consistency findings.
- Only resolve a previous issue after examining the affected content; cite it and set rechecked=true.
- Missing context is unassessed, not a candidate defect. A missing source is a dependency need.
- Judge scientific truth separately from source existence, quote matching, and readability.
- Review claims by type. Hypotheses/predictions need a discriminating validation path, not completed experiments.
- For causal/measurement claims inspect construct, observable, linking argument, and conditions;
  for formal claims inspect assumptions, derivation and proof obligations.
- Return contribution_review: {role: research_object|analysis_tool|primary_contribution,
  replaces_task_objective: bool, serves_task_objective: bool, triggering_text,
  task_boundary_quote, rationale}. Cross-domain tools that serve the task are allowed.
"""
