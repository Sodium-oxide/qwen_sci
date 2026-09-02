"""Bounded verification of whether a source-derived causal gap still exists.

This stage belongs to TanXi/ZhiZhi, not Socrates.  It asks one exact,
source-grounded question before an inferred absence is treated as a scientific
gap.  Search results may verify that the gap is open, show contradictory
evidence, or show that the relation has already been resolved; they never fill
the theory/experiment slots of a primary hypothesis bundle.
"""
from __future__ import annotations

from typing import Any, Callable
import json
import re
import time


RESOLVED_IN_LITERATURE = "RESOLVED_IN_LITERATURE"
CORPUS_BOUNDED_UNRESOLVED = "CORPUS_BOUNDED_UNRESOLVED"
AUTHOR_STATED_OPEN_GAP = "AUTHOR_STATED_OPEN_GAP"
CONTRADICTORY_EVIDENCE = "CONTRADICTORY_EVIDENCE"
INSUFFICIENT_RETRIEVAL = "INSUFFICIENT_RETRIEVAL"

CONTINUABLE_GAP_EXISTENCE_VERDICTS = frozenset({
    CORPUS_BOUNDED_UNRESOLVED,
    AUTHOR_STATED_OPEN_GAP,
    CONTRADICTORY_EVIDENCE,
})

_OPEN_MARKERS = (
    "remain unknown", "remains unknown", "remain unclear", "remains unclear",
    "not established", "not been established", "not tested", "not evaluated",
    "open question", "open problem", "unresolved", "poorly understood",
    "insufficient evidence", "lack of evidence",
)
_RESOLUTION_MARKERS = (
    "demonstrate that", "demonstrated that", "establish that", "established that",
    "show that", "showed that", "confirms that", "confirmed that",
    "necessary for", "sufficient for", "mediates the", "causally mediates",
    "resolves the", "resolved the",
)
_CONTRADICTION_MARKERS = (
    "contradictory", "conflicting evidence", "conflicting results", "inconsistent",
    "opposing results", "mixed evidence", "discrepancy", "mismatch",
)

DEFAULT_GAP_EXISTENCE_PROVIDERS = ("openalex", "semantic_scholar")
DEFAULT_GAP_EXISTENCE_MAX_QUERIES = 3
DEFAULT_GAP_EXISTENCE_RESULTS_PER_QUERY = 8


def _compact(value: Any, limit: int = 180) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def _quoted(value: Any, *, max_words: int = 10) -> str:
    words = _compact(value, 240).split()
    phrase = " ".join(words[:max_words]).strip(' "')
    return f'"{phrase}"' if phrase else ""


def _subhypothesis(project: dict[str, Any], branch: str) -> dict[str, Any]:
    return next(
        (
            item for item in (project.get("sub_hypotheses") or [])
            if isinstance(item, dict) and str(item.get("id") or "").split(":", 1)[0] == branch
        ),
        {},
    )


def _query_plan(
    scientific_object: str,
    input_value: str,
    mediator: str,
    outcome: str,
) -> list[dict[str, Any]]:
    """Build small complementary query families for one scoped relation.

    These queries do not attempt a systematic review.  Their purpose is to
    make the verification boundary explicit and materially stronger than a
    single wording of the causal chain.
    """
    if not (scientific_object and input_value and mediator and outcome):
        return []
    object_phrase = _quoted(scientific_object, max_words=12)
    input_phrase = _quoted(input_value)
    mediator_phrase = _quoted(mediator)
    outcome_phrase = _quoted(outcome)
    anchors = " ".join(part for part in (object_phrase, input_phrase, mediator_phrase, outcome_phrase) if part)
    relation_terms = "mediation necessity sufficiency boundary comparison"
    return [
        {
            "query_id": "exact_causal_relation",
            "query": " ".join(part for part in (anchors, f"({relation_terms.replace(' ', ' OR ')})") if part),
            "purpose": "Search for direct resolution, mediation, necessity, or sufficiency claims about the exact source-bound chain.",
            "query_family": "exact_relation",
        },
        {
            "query_id": "open_problem_or_limitation",
            "query": " ".join(part for part in (
                anchors,
                '("open question" OR unresolved OR "remain unclear" OR "not established" OR limitation)',
            ) if part),
            "purpose": "Look for recent sources that explicitly characterize the scoped relation as open, limited, or unresolved.",
            "query_family": "open_problem",
        },
        {
            "query_id": "review_or_synthesis",
            "query": " ".join(part for part in (
                object_phrase,
                mediator_phrase,
                outcome_phrase,
                '(review OR "systematic review" OR meta-analysis OR synthesis)',
            ) if part),
            "purpose": "Look for synthesis literature that may establish whether the scoped relation has already been resolved or remains contested.",
            "query_family": "review_synthesis",
        },
    ]


def build_gap_existence_verification_task(
    project: dict[str, Any],
    gap: dict[str, Any],
) -> dict[str, Any]:
    """Build a bounded, multi-query verification task for one causal chain."""
    branch = str(gap.get("sub_hypothesis_id") or "").split(":", 1)[0]
    subhypothesis = _subhypothesis(project, branch)
    seed_contract = gap.get("mechanism_seed_contract") if isinstance(gap.get("mechanism_seed_contract"), dict) else {}
    seed = seed_contract.get("mechanism_seed") if isinstance(seed_contract.get("mechanism_seed"), dict) else {}

    def role_value(role: str) -> str:
        payload = seed.get(role) if isinstance(seed.get(role), dict) else {}
        rendered = _compact(payload.get("value"), 220)
        if rendered and rendered.lower() not in {"unknown", "unresolved", "none", "n/a"}:
            return rendered
        return ""

    scientific_object = _compact(
        subhypothesis.get("scientific_object"),
        220,
    )
    input_value = role_value("input")
    mediator = role_value("mediator")
    outcome = role_value("outcome")
    query_plan = _query_plan(scientific_object, input_value, mediator, outcome)
    query = str(query_plan[0]["query"] if query_plan else "")
    identity_payload = "\0".join((branch, scientific_object, input_value, mediator, outcome))
    try:
        from hashlib import sha256
        verification_id = "gapverify_" + sha256(identity_payload.encode("utf-8")).hexdigest()[:18]
    except Exception:  # pragma: no cover - hashlib is always available
        verification_id = "gapverify_unknown"
    return {
        "schema_version": "gap_existence_verification_task_v2",
        "verification_id": verification_id,
        "owner": "TanXi/ZhiZhi",
        "stage": "GAP_EXISTENCE_VERIFICATION",
        "project_id": str(project.get("project_id") or ""),
        "gap_id": str(gap.get("gap_id") or ""),
        "sub_hypothesis_id": branch,
        "scientific_object": scientific_object,
        "input": input_value,
        "mediator": mediator,
        "outcome": outcome,
        "query": query,
        "query_plan": query_plan,
        "provider_preference": list(DEFAULT_GAP_EXISTENCE_PROVIDERS),
        "max_results_per_query": DEFAULT_GAP_EXISTENCE_RESULTS_PER_QUERY,
        "max_searches": DEFAULT_GAP_EXISTENCE_MAX_QUERIES,
        "searches_used": 0,
        "may_fill_primary_evidence_slots": False,
        "verification_scope": {
            "scope_kind": "multi_query_source_bounded_literature_check",
            "provider_preference": list(DEFAULT_GAP_EXISTENCE_PROVIDERS),
            "planned_query_ids": [str(item["query_id"]) for item in query_plan],
            "max_searches": DEFAULT_GAP_EXISTENCE_MAX_QUERIES,
            "field_wide_absence_not_established": True,
            "statement_boundary": (
                "A non-resolution result means only that the bounded multi-query retrieval did not identify a direct resolution claim; "
                "it does not establish that no such literature exists."
            ),
        },
    }


def classify_gap_existence_results(
    task: dict[str, Any],
    results: list[dict[str, Any]],
    *,
    search_count: int = 1,
    retrieval_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Classify search summaries without treating them as direct evidence."""
    rows = [item for item in results if isinstance(item, dict)]
    anchors = [
        _compact(task.get(key), 160).lower()
        for key in ("scientific_object", "input", "mediator", "outcome")
        if _compact(task.get(key), 160)
    ]
    relevant: list[dict[str, Any]] = []
    for row in rows:
        text = _compact(" ".join(str(row.get(key) or "") for key in ("title", "abstract", "summary", "tldr")), 4000).lower()
        if not text:
            continue
        matched = sum(
            1 for anchor in anchors
            if anchor in text or len(set(anchor.split()) & set(text.split())) >= min(2, len(set(anchor.split())))
        )
        if matched >= min(2, max(1, len(anchors))):
            relevant.append({**row, "_gap_verification_text": text, "_anchor_match_count": matched})
    combined = " ".join(str(item.get("_gap_verification_text") or "") for item in relevant)
    if not relevant:
        verdict = INSUFFICIENT_RETRIEVAL
        reason = "The one bounded search returned no result aligned to the exact object and causal chain."
    elif any(marker in combined for marker in _CONTRADICTION_MARKERS):
        verdict = CONTRADICTORY_EVIDENCE
        reason = "Aligned retrieval results report incompatible or conflicting evidence for the exact causal chain."
    elif any(marker in combined for marker in _RESOLUTION_MARKERS):
        verdict = RESOLVED_IN_LITERATURE
        reason = "Aligned retrieval results contain a direct resolution claim for the proposed relation."
    elif any(marker in combined for marker in _OPEN_MARKERS):
        verdict = AUTHOR_STATED_OPEN_GAP
        reason = "An aligned source explicitly describes the exact causal relation as open, unresolved, or untested."
    else:
        verdict = CORPUS_BOUNDED_UNRESOLVED
        reason = "Aligned literature was found, but the bounded retrieval did not identify a direct resolution claim."
    metadata = retrieval_metadata if isinstance(retrieval_metadata, dict) else {}
    task_scope = task.get("verification_scope") if isinstance(task.get("verification_scope"), dict) else {}
    return {
        "schema_version": "gap_existence_verification_result_v2",
        "verification_id": str(task.get("verification_id") or ""),
        "gap_id": str(task.get("gap_id") or ""),
        "verdict": verdict,
        "continuable": verdict in CONTINUABLE_GAP_EXISTENCE_VERDICTS,
        "search_count": max(0, int(search_count or 0)),
        "retrieved_count": len(rows),
        "aligned_result_count": len(relevant),
        "result_refs": [
            str(
                item.get("paper_id") or item.get("doi") or item.get("openalex_id")
                or item.get("arxiv_id") or item.get("url") or item.get("title") or ""
            )
            for item in relevant[:5]
        ],
        "verification_evidence": [
            {
                "result_index": item.get("result_index"),
                "paper_ref": str(
                    item.get("paper_id") or item.get("doi") or item.get("openalex_id")
                    or item.get("arxiv_id") or item.get("url") or item.get("title") or ""
                ),
                "title": _compact(item.get("title"), 300),
                "matched_excerpt": _compact(
                    item.get("abstract") or item.get("summary") or item.get("tldr"), 700
                ),
                "anchor_match_count": int(item.get("_anchor_match_count") or 0),
                "primary_evidence_admissible": False,
            }
            for item in relevant[:3]
        ],
        "reason": reason,
        "may_fill_primary_evidence_slots": False,
        "verification_scope": {
            **task_scope,
            **metadata,
            "field_wide_absence_not_established": True,
        },
    }


def _verification_query_plan(task: dict[str, Any]) -> list[dict[str, Any]]:
    planned = task.get("query_plan") if isinstance(task.get("query_plan"), list) else []
    plan = [dict(item) for item in planned if isinstance(item, dict) and _compact(item.get("query"), 1)]
    if plan:
        return plan[: max(1, int(task.get("max_searches") or len(plan)))]
    return []


def _result_identity(result: dict[str, Any], position: int) -> str:
    for key in ("paper_id", "doi", "openalex_id", "semantic_scholar_id", "arxiv_id", "url"):
        value = _compact(result.get(key), 300).lower()
        if value:
            return f"{key}:{value}"
    title = _compact(result.get("title"), 500).lower()
    return f"title:{title}" if title else f"anonymous:{position}"


def _full_search_results(payload: dict[str, Any]) -> tuple[str, list[dict[str, Any]]]:
    search_id = str(payload.get("search_id") or "")
    full_results = list(payload.get("results") or [])
    if search_id:
        try:
            try:
                from ._project import load_search
            except ImportError:
                from _project import load_search
            persisted_search = load_search(search_id)
            if isinstance(persisted_search.get("results"), list):
                full_results = persisted_search["results"]
        except Exception:
            # The compact response is a conservative fallback.  Missing
            # abstracts will tend toward INSUFFICIENT rather than inventing an
            # open/resolved verdict.
            pass
    return search_id, [item for item in full_results if isinstance(item, dict)]


def execute_gap_existence_verification(
    task: dict[str, Any],
    *,
    search_callable: Callable[..., str] | None = None,
    domain: str = "",
) -> dict[str, Any]:
    """Execute the bounded multi-query verification protocol.

    Results remain verification-only evidence.  Even an explicit open-problem
    result cannot fill direct theory/experiment evidence slots for a primary
    hypothesis.
    """
    if search_callable is None:
        try:
            from ._literature_search import search_papers_stratified
        except ImportError:
            from _literature_search import search_papers_stratified
        search_callable = search_papers_stratified
    plan = _verification_query_plan(task)
    provider_preference = [
        str(value) for value in (task.get("provider_preference") or DEFAULT_GAP_EXISTENCE_PROVIDERS)
        if str(value)
    ] or list(DEFAULT_GAP_EXISTENCE_PROVIDERS)
    max_results = max(1, int(task.get("max_results_per_query") or DEFAULT_GAP_EXISTENCE_RESULTS_PER_QUERY))
    all_results: list[dict[str, Any]] = []
    search_ids: list[str] = []
    executed_queries: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for item in plan:
        query = str(item.get("query") or "")
        query_id = str(item.get("query_id") or "gap_existence_verification")
        if not query:
            continue
        try:
            payload = json.loads(search_callable(
                query=query,
                databases=provider_preference,
                max_results=max_results,
                domain=domain,
                focus_branches=[str(task.get("sub_hypothesis_id") or "")],
                use_llm=False,
                explicit_query_plan=[{
                    "branch": "gap_existence_verification",
                    "query": query,
                    "purpose": str(item.get("purpose") or "verify whether the source-bound causal gap is already resolved"),
                    "query_family": str(item.get("query_family") or "gap_existence_verification"),
                    "evidence_kind": "gap_existence_verification",
                }],
                layer_quotas={
                    "L0_review": 0, "L1_milestone": 0, "L2_top_latest": 0,
                    "L3_preprint": 0, "L4_regular": max_results,
                },
                single_paper_serial=True,
            ))
            search_id, full_results = _full_search_results(payload if isinstance(payload, dict) else {})
            if search_id:
                search_ids.append(search_id)
            executed_queries.append({
                "query_id": query_id,
                "query": query,
                "query_family": str(item.get("query_family") or ""),
                "search_id": search_id,
                "retrieved_count": len(full_results),
                "status": "completed",
            })
            for result in full_results:
                all_results.append({
                    **result,
                    "_gap_verification_query_id": query_id,
                    "_gap_verification_query_family": str(item.get("query_family") or ""),
                })
        except Exception as exc:
            errors.append({
                "query_id": query_id,
                "query": query,
                "error": f"{type(exc).__name__}: {_compact(exc, 300)}",
            })

    deduplicated_results: list[dict[str, Any]] = []
    seen_result_ids: set[str] = set()
    for position, row in enumerate(all_results):
        identity = _result_identity(row, position)
        if identity in seen_result_ids:
            continue
        seen_result_ids.add(identity)
        deduplicated_results.append(row)
    now = time.time()
    retrieval_metadata = {
        "provider_preference": provider_preference,
        "planned_query_ids": [str(item.get("query_id") or "") for item in plan],
        "executed_queries": executed_queries,
        "failed_queries": errors,
        "successful_query_count": len(executed_queries),
        "planned_query_count": len(plan),
        "query_coverage_complete": bool(plan) and len(executed_queries) == len(plan),
        "deduplicated_retrieved_count": len(deduplicated_results),
        "field_wide_absence_not_established": True,
    }
    result = classify_gap_existence_results(
        task,
        deduplicated_results,
        search_count=len(executed_queries) + len(errors),
        retrieval_metadata=retrieval_metadata,
    )
    result["search_id"] = search_ids[0] if search_ids else ""
    result["search_ids"] = search_ids
    result["query"] = str(task.get("query") or "")
    result["queries_executed"] = executed_queries
    result["verified_at"] = now
    result["executed_at"] = now
    if not executed_queries:
        result["verdict"] = INSUFFICIENT_RETRIEVAL
        result["continuable"] = False
        failure_text = "; ".join(str(item.get("error") or "") for item in errors[:3])
        result["reason"] = (
            "The bounded multi-query verification protocol did not complete any retrieval query. "
            + failure_text
        ).strip()
    return result
