"""Bounded review calls with explicit coverage and a separate consistency pass."""

from __future__ import annotations

from typing import Any, Mapping

from src.agents.idea_agent.utils.core.response_parsing import parse_json_response
from src.agents.idea_agent.utils.mcts.review_contracts import (
    ReviewIssue, candidate_path, canonical_json, content_hash, path_present, scientific_content, normalize_requirement_reviews,
)
from src.agents.idea_agent.utils.prompting.review_packets import (
    _leaves, aggregate_review_payloads, build_review_packets, token_bound,
)


def _ground_assessment(result: dict, visible: list[str], envelope_paths: tuple[str, ...],
                       snapshot: dict, context: Mapping[str, Any], complete: bool) -> dict:
    """Bind each semantic judgment to fields actually present in this call."""
    sources = context.get("trusted_sources", {})
    records = {str(r.get("evidence_id") or r.get("source_id")): (i, r)
               for i, r in enumerate(snapshot.get("evidence_records", [])) if isinstance(r, Mapping)}
    paths = {p for p, _ in _leaves(snapshot)}

    def ref_visible(ref: str) -> bool:
        ref = candidate_path(ref)
        if ref == "task_contract.original_request":
            return path_present("context.task_contract.original_request", envelope_paths)
        if ref in records:
            index, record = records[ref]
            sid = str(record.get("source_id") or "")
            return (path_present(f"evidence_records[{index}]", visible) and sid in sources
                    and path_present("context.trusted_sources." + sid, envelope_paths))
        if ref in sources:
            return path_present("context.trusted_sources." + ref, envelope_paths)
        exists = ref == "$" or ref in paths or any(p.startswith(ref + ".") or p.startswith(ref + "[") for p in paths)
        return exists and path_present(ref, visible)

    issues = []
    for raw in result.get("review_issues", []):
        if not isinstance(raw, Mapping):
            continue
        issue = ReviewIssue.from_payload(raw).to_dict()
        if not path_present(issue["target_path"], visible):
            issue.update(origin="context", status="unassessed", rechecked=False)
        if issue["status"] == "resolved" and not (ref_visible(issue["target_path"])
                and issue["evidence_refs"] and all(ref_visible(r) for r in issue["evidence_refs"])):
            # A failed closure must not overwrite a previous open issue later.
            continue
        issues.append(issue)
    result["review_issues"] = issues
    result["requirement_reviews"] = normalize_requirement_reviews(
        result.get("requirement_reviews", []), context.get("task_contract", {}), included_paths=visible, complete=complete)
    for review in result["requirement_reviews"]:
        if review["status"] == "satisfied" and not (
            path_present("context.task_contract", envelope_paths)
            and all(ref_visible(p) for p in review["candidate_paths"])
        ):
            review["status"] = "unassessed"
    claims = {str(c.get("claim_id")): i for i, c in enumerate(snapshot.get("claims", [])) if isinstance(c, Mapping)}
    reviewed_claims = []
    for raw in result.get("claim_reviews", []):
        if not isinstance(raw, Mapping) or raw.get("claim_id") not in claims:
            continue
        review = dict(raw)
        review["evidence_refs"] = [candidate_path(r) for r in (raw.get("evidence_refs") or []) if isinstance(r, str)]
        examined = (path_present(f"claims[{claims[raw['claim_id']]}]", visible)
                    and bool(review["evidence_refs"]) and all(ref_visible(r) for r in review["evidence_refs"])
                    and all(ref_visible(r) for r in snapshot["claims"][claims[raw["claim_id"]]].get("support_refs", [])))
        if not examined:
            review.update(support_assessment="unassessed", link_assessment="unassessed")
        reviewed_claims.append(review)
    result["claim_reviews"] = reviewed_claims
    contribution = result.get("contribution_review", {})
    if not (path_present("core_contribution", visible) and path_present("context.task_contract.original_request", envelope_paths)):
        contribution = {}
    result["contribution_review"] = contribution
    return result


def run_review(mcts: Any, node: Any, prompt: str, context: Mapping[str, Any]) -> tuple[dict, dict]:
    """Transmit every field, or report partial coverage; never silently clip.

    Context (including the original task and readable sources) is partitioned
    under the same budget as candidate content. Intermediate findings remain
    available to the ledger even when the consistency pass fails.
    """
    budget = int(getattr(mcts.config, "review_prompt_token_budget", 48000))
    limit = int(getattr(mcts.config, "max_review_packets", 32))
    snapshot = scientific_content(node.state.to_payload())
    packet_context = dict(context)
    shared_paths = ()
    task = packet_context.get("task_contract", {})
    shared = "\n== Task contract for every review packet ==\n" + canonical_json({"task_contract": task}) + "\n"
    # Keep small tasks beside the candidate fields they govern. Large tasks remain
    # budgeted context; positive judgments without a joint view stay unassessed.
    if task and token_bound(shared) <= budget // 5 and token_bound(prompt + shared) < budget // 2:
        prompt += shared
        packet_context.pop("task_contract", None)
        shared_paths = ("context.task_contract",)
    envelope = {"candidate": snapshot, "context": packet_context}
    all_paths = [p for p, _ in _leaves(snapshot)]
    errors, responses, notes, included = [], [], [], set()
    completed = 0

    def call(text: str) -> dict:
        raw = mcts.chat_fn(text, model=mcts.config.evaluation_model,
                           temperature=mcts.config.evaluation_temperature,
                           max_output_tokens=mcts.config.evaluation_max_tokens)
        result = parse_json_response(raw)
        if isinstance(result, list) and result:
            result = result[0]
        if not isinstance(result, dict) or not result:
            raise ValueError("Reviewer returned no assessment object.")
        for field in ("review_issues", "requirement_reviews", "claim_reviews"):
            if not isinstance(result.get(field), list):
                raise ValueError(f"Reviewer omitted structured field: {field}")
        if not isinstance(result.get("contribution_review"), dict):
            raise ValueError("Reviewer omitted contribution_review.")
        for issue in result["review_issues"]:
            if isinstance(issue, dict):
                issue.pop("checker", None)
        return result

    try:
        packets = build_review_packets(envelope, prompt_prefix=prompt, token_budget=budget, scientific_only=False)
    except ValueError as exc:
        return {}, {"complete": False, "included_paths": [], "omitted_paths": all_paths,
                    "errors": [str(exc)], "content_hash": node.state.signature}
    for packet in packets[:limit]:
        try:
            result = call(prompt + packet.text)
            visible = [p.removeprefix("candidate.") for p in packet.included_paths if p.startswith("candidate.")]
            result = _ground_assessment(result, ["$"] if len(packets) == 1 else visible,
                                       (*packet.included_paths, *shared_paths), snapshot, context, len(packets) == 1)
            responses.append(result)
            notes.append({"coverage": packet.coverage(), "assessment": result})
            included.update(visible)
            completed += 1
        except Exception as exc:
            errors.append(f"packet {completed + 1}: {type(exc).__name__}: {exc}")
    if len(packets) > limit:
        errors.append(f"Review packet budget exhausted ({limit}/{len(packets)} packets).")
    all_read = completed == len(packets)
    consistent = len(packets) == 1 and all_read
    if len(packets) > 1 and notes:
        prefix = (
            "Audit consistency across the following complete packet findings. Return the same scoring JSON, "
            "review_issues, requirement_reviews, claim_reviews, contribution_review and review_notes. "
            "Candidate paths start at title/method/claims/scientific_intervention, without the candidate prefix. "
            "Only explicitly rechecked issues may close. Unseen content remains unassessed. "
            "Reconcile requirements across findings and distinguish missing content from unseen context.\n"
        )
        # Reduce *all* findings, never the first N. A bounded failure remains partial.
        for depth in range(4):
            try:
                # Keep each finding together: flattening every scalar creates
                # more metadata than findings and can prevent bounded reduction.
                groups = build_review_packets({"findings": [canonical_json(note) for note in notes]}, prompt_prefix=prefix,
                                              token_budget=budget, scientific_only=False)
                if len(groups) > limit:
                    raise ValueError("Consistency packet budget exhausted.")
                reduced = [call(prefix + group.text) for group in groups]
                if len(groups) == 1:
                    consistency = reduced[0]
                    # A synthesis sees findings, not the original sources. It may
                    # reject support, but cannot invent a new positive source review.
                    assessed_claims = [r for response in responses for r in response.get("claim_reviews", [])]

                    def inherits_positive(review: Mapping[str, Any], field: str) -> bool:
                        refs = {candidate_path(p) for p in review.get("evidence_refs", []) if isinstance(p, str)}
                        return bool(refs) and any(
                            previous.get("claim_id") == review.get("claim_id") and previous.get(field) == "supported"
                            and refs <= set(previous.get("evidence_refs", []))
                            for previous in assessed_claims
                        )

                    consistency["claim_reviews"] = [r for r in consistency.get("claim_reviews", [])
                        if isinstance(r, Mapping) and (r.get("support_assessment") != "supported"
                            or inherits_positive(r, "support_assessment"))]
                    consistency["review_issues"] = [r for r in consistency.get("review_issues", [])
                        if isinstance(r, Mapping) and r.get("status") != "resolved"]
                    supported_requirements = {r["requirement_id"]: r for response in responses
                        for r in response.get("requirement_reviews", []) if r.get("status") == "satisfied"}
                    consistency["requirement_reviews"] = [r for r in consistency.get("requirement_reviews", [])
                        if isinstance(r, Mapping) and (r.get("status") != "satisfied" or (
                            r.get("requirement_id") in supported_requirements
                            and set(candidate_path(p) for p in r.get("candidate_paths", []))
                            <= set(supported_requirements[r["requirement_id"]]["candidate_paths"])))]
                    for review in consistency["claim_reviews"]:
                        if review.get("link_assessment") == "supported" and not inherits_positive(review, "link_assessment"):
                            review["link_assessment"] = "unassessed"
                    contributions = [response.get("contribution_review") for response in responses if response.get("contribution_review")]
                    if consistency.get("contribution_review") not in contributions:
                        consistency["contribution_review"] = {}
                    responses.append(consistency)
                    consistent = all_read
                    break
                notes = reduced
            except Exception as exc:
                errors.append(f"consistency: {type(exc).__name__}: {exc}")
                break
        else:
            errors.append("Consistency reduction did not converge within four passes.")
    complete = all_read and consistent
    if complete:
        included.update(all_paths)
    coverage = {"complete": complete, "included_paths": ["$", *all_paths] if complete else sorted(included),
                "omitted_paths": [] if complete else [p for p in all_paths if p not in included],
                "packets_total": len(packets), "packets_reviewed": completed,
                "consistency_reviewed": consistent, "errors": errors,
                "content_hash": node.state.signature, "context_hash": content_hash(context)}
    merged = aggregate_review_payloads(responses)
    merged["requirement_reviews"] = normalize_requirement_reviews(
        merged.get("requirement_reviews", []), context.get("task_contract", {}),
        included_paths=coverage["included_paths"], complete=complete,
    )
    return merged, coverage
