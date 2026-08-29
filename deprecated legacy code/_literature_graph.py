from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from pathlib import Path
from threading import Lock
from typing import Any
from urllib.parse import quote, urlencode
import ast
import hashlib
import json
import math
import re
import time

try:
    from .config import (
        SCIENCE_BRIDGE_SEARCH_ENABLED,
        SCIENCE_BRIDGE_SEARCH_MAX_RESULTS,
        SCIENCE_BRIDGE_SEARCH_QUERY_LIMIT,
        SCIENCE_COMMUNITY_AWARE_SEED_SELECTION,
        SCIENCE_CROSS_COMMUNITY_EDGE_BONUS,
        SCIENCE_LOUVAIN_BRIDGE_THRESHOLD,
        SCIENCE_LOUVAIN_ENABLED,
        SCIENCE_LOUVAIN_INCLUDE_ARTIFICIAL_EDGES,
        SCIENCE_LOUVAIN_MAX_NODES,
        SCIENCE_LOUVAIN_MIN_COMMUNITY_RECORDS,
        SCIENCE_LOUVAIN_RESOLUTION,
        SCIENCE_MIN_CROSS_COMMUNITY_SEEDS,
        SCIENCE_SEMANTIC_SCHOLAR_EDGE_LIMIT,
        SCIENCE_SEMANTIC_SCHOLAR_EDGE_CACHE_DIR,
        SCIENCE_SEMANTIC_SCHOLAR_EDGE_CACHE_TTL_SECONDS,
        SCIENCE_SEMANTIC_SCHOLAR_GRAPH_MAX_429,
        SCIENCE_SEMANTIC_SCHOLAR_GRAPH_BATCH_ENABLED,
        SCIENCE_SEMANTIC_SCHOLAR_GRAPH_BATCH_MAX_IDS,
        SCIENCE_SEMANTIC_SCHOLAR_GRAPH_REQUESTS_PER_SUBHYPOTHESIS,
        SCIENCE_SPARSE_GRAPH_THRESHOLD,
        SEMANTIC_SCHOLAR_API_KEY,
        SEMANTIC_SCHOLAR_RATE_SCOPE,
    )
    from .log import log_event
except ImportError:
    from config import (
        SCIENCE_BRIDGE_SEARCH_ENABLED,
        SCIENCE_BRIDGE_SEARCH_MAX_RESULTS,
        SCIENCE_BRIDGE_SEARCH_QUERY_LIMIT,
        SCIENCE_COMMUNITY_AWARE_SEED_SELECTION,
        SCIENCE_CROSS_COMMUNITY_EDGE_BONUS,
        SCIENCE_LOUVAIN_BRIDGE_THRESHOLD,
        SCIENCE_LOUVAIN_ENABLED,
        SCIENCE_LOUVAIN_INCLUDE_ARTIFICIAL_EDGES,
        SCIENCE_LOUVAIN_MAX_NODES,
        SCIENCE_LOUVAIN_MIN_COMMUNITY_RECORDS,
        SCIENCE_LOUVAIN_RESOLUTION,
        SCIENCE_MIN_CROSS_COMMUNITY_SEEDS,
        SCIENCE_SEMANTIC_SCHOLAR_EDGE_LIMIT,
        SCIENCE_SEMANTIC_SCHOLAR_EDGE_CACHE_DIR,
        SCIENCE_SEMANTIC_SCHOLAR_EDGE_CACHE_TTL_SECONDS,
        SCIENCE_SEMANTIC_SCHOLAR_GRAPH_MAX_429,
        SCIENCE_SEMANTIC_SCHOLAR_GRAPH_BATCH_ENABLED,
        SCIENCE_SEMANTIC_SCHOLAR_GRAPH_BATCH_MAX_IDS,
        SCIENCE_SEMANTIC_SCHOLAR_GRAPH_REQUESTS_PER_SUBHYPOTHESIS,
        SCIENCE_SPARSE_GRAPH_THRESHOLD,
        SEMANTIC_SCHOLAR_API_KEY,
        SEMANTIC_SCHOLAR_RATE_SCOPE,
    )
    from log import log_event

try:
    import networkx as nx
except ImportError:
    nx = None

LOUVAIN_AVAILABLE = bool(nx is not None and hasattr(nx.algorithms.community, "louvain_communities"))

SUBHYPOTHESIS_GRAPH_SEEDS_PER_BRANCH = 2
SUBHYPOTHESIS_GRAPH_SECOND_LAYER_TOP_K = 3
SUBHYPOTHESIS_GRAPH_MAX_SEED_ATTEMPTS = 6
OPTIONAL_GRAPH_SEED_INSUFFICIENT_STATUS = "optional_graph_seed_insufficient"
LEGACY_GRAPH_SEED_INSUFFICIENT_STATUS = "graph_seed_insufficient"
GRAPH_SEED_INSUFFICIENT_NEXT_PHASE = "gap_detection_without_louvain"
SEMANTIC_SCHOLAR_EDGE_CACHE_LOCK = Lock()


def optional_graph_seed_insufficient_report(
    *,
    sub_hypothesis_id: str,
    search_id: str = "",
    reason: str,
    reason_code: str = "fewer_than_two_graph_seeds",
    eligible_seed_candidate_count: int = 0,
    alignment_rejected_seed_candidate_count: int = 0,
    accepted_seed_count: int = 0,
    seed_papers: list[dict[str, Any]] | None = None,
    failed_seed_attempts: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Return a non-blocking citation-graph insufficiency report.

    Louvain expansion is an optional enrichment stage after the full-text gate.
    Fewer than two strict seeds is scientifically too weak for a community
    graph, but it must not revoke SH readiness or block papergraph-only gap
    detection.
    """

    report: dict[str, Any] = {
        "sub_hypothesis_id": sub_hypothesis_id,
        "search_id": search_id,
        "source_search_id": search_id,
        "status": OPTIONAL_GRAPH_SEED_INSUFFICIENT_STATUS,
        "legacy_status": LEGACY_GRAPH_SEED_INSUFFICIENT_STATUS,
        "reason": reason,
        "reason_code": reason_code,
        "eligible_seed_candidate_count": eligible_seed_candidate_count,
        "alignment_rejected_seed_candidate_count": alignment_rejected_seed_candidate_count,
        "accepted_seed_count": accepted_seed_count,
        "seed_papers": list(seed_papers or []),
        "failed_seed_attempts": list(failed_seed_attempts or []),
        "second_layer_top_k": SUBHYPOTHESIS_GRAPH_SECOND_LAYER_TOP_K,
        "allow_fallback": False,
        "optional_enrichment": True,
        "blocking": False,
        "next_phase": GRAPH_SEED_INSUFFICIENT_NEXT_PHASE,
        "fallback_applied": "papergraph_only_gap_detection",
    }
    if not search_id:
        report.pop("search_id", None)
        report.pop("source_search_id", None)
    return report


@dataclass
class SemanticScholarGraphRequestContext:
    """Shared low-priority request and 429 budget for one sub-hypothesis graph."""

    sub_hypothesis_id: str = ""
    request_limit: int = SCIENCE_SEMANTIC_SCHOLAR_GRAPH_REQUESTS_PER_SUBHYPOTHESIS
    requests_used: int = 0
    stopped: bool = False
    stop_reason: str = ""
    provider_circuit_deferred: bool = False
    provider_circuit_deferred_reason: str = ""
    batch_capacity_limited: bool = False
    batch_capacity_reason: str = ""
    retry_budget: Any = None

    def ensure_retry_budget(self) -> Any:
        if self.retry_budget is None:
            try:
                from ._literature_search import SemanticScholarRetryBudget
            except ImportError:
                from _literature_search import SemanticScholarRetryBudget
            self.retry_budget = SemanticScholarRetryBudget(
                limit=max(0, int(SCIENCE_SEMANTIC_SCHOLAR_GRAPH_MAX_429)),
                job_id=f"literature_graph:{self.sub_hypothesis_id or 'standalone'}",
                request_kind="graph_edge",
                max_rate_limit_responses=max(1, int(SCIENCE_SEMANTIC_SCHOLAR_GRAPH_MAX_429)),
            )
        return self.retry_budget

    def reserve_edge_request(self) -> None:
        if self.stopped:
            raise RuntimeError(f"semantic_scholar_graph_stopped: {self.stop_reason}")
        if self.requests_used >= max(1, int(self.request_limit)):
            self.stopped = True
            self.stop_reason = "sub-hypothesis graph request budget exhausted"
            raise RuntimeError(
                f"semantic_scholar_graph_subhypothesis_budget_exhausted: "
                f"{self.requests_used}/{self.request_limit}"
            )
        self.requests_used += 1

    def stop(self, reason: str) -> None:
        self.stopped = True
        self.stop_reason = str(reason or "graph expansion stopped")[:300]

    def defer_provider_circuit(self, reason: str) -> None:
        self.stopped = True
        self.provider_circuit_deferred = True
        self.provider_circuit_deferred_reason = str(reason or "provider circuit deferred graph expansion")[:300]
        self.stop_reason = self.provider_circuit_deferred_reason

    def note_batch_capacity_limit(self, reason: str) -> None:
        self.batch_capacity_limited = True
        self.batch_capacity_reason = str(reason or "Semantic Scholar batch response capacity limited")[:300]

    def snapshot(self) -> dict[str, Any]:
        retry_budget = self.ensure_retry_budget()
        return {
            "sub_hypothesis_id": self.sub_hypothesis_id,
            "request_limit": self.request_limit,
            "requests_used": self.requests_used,
            "requests_remaining": max(0, self.request_limit - self.requests_used),
            "rate_limit_responses": int(retry_budget.rate_limit_responses),
            "max_rate_limit_responses": int(retry_budget.max_rate_limit_responses),
            "retry_attempts_used": int(retry_budget.retries_used),
            "estimated_http_attempts_used": int(self.requests_used) + int(retry_budget.retries_used),
            "estimated_http_attempts_ceiling": int(self.request_limit) + int(retry_budget.limit),
            "batch_capacity_limited": self.batch_capacity_limited,
            "batch_capacity_reason": self.batch_capacity_reason,
            "provider_circuit_deferred": self.provider_circuit_deferred,
            "provider_circuit_deferred_reason": self.provider_circuit_deferred_reason,
            "stopped": self.stopped,
            "stop_reason": self.stop_reason,
        }


def ensure_semantic_scholar_graph_traffic_available(
    request_context: SemanticScholarGraphRequestContext | None = None,
) -> None:
    """Short-circuit uncached graph work after the run-level graph circuit opens."""
    try:
        from ._literature_search import semantic_scholar_graph_traffic_suspension_error
    except ImportError:
        from _literature_search import semantic_scholar_graph_traffic_suspension_error
    if not (reason := semantic_scholar_graph_traffic_suspension_error()):
        return
    if request_context is not None:
        request_context.stop(reason)
    raise RuntimeError(reason)



def expand_literature_graph(
    search_id: str,
    result_index: int = 0,
    query: str = "",
    direction: str = "both",
    max_results: int = 40,
    use_llm: bool = False,
    depth: int = 1,
    second_layer_top_k: int = 3,
    allow_fallback: bool = True,
    _request_context: SemanticScholarGraphRequestContext | None = None,
) -> str:
    try:
        from ._literature_import import import_literature_search_result
        from ._literature_search import dedupe_literature_results, flatten_literature_results, is_semantic_scholar_not_found_error, is_semantic_scholar_rate_limit_error, judge_literature_candidates_with_llm, literature_result_unique_key, rank_literature_results, search_semantic_scholar, select_literature_result, summarize_literature_result
        from ._project import load_search, save_search
        from ._utils import clamp_int, find_by_id, new_id, normalize_key
    except ImportError:
        from _literature_import import import_literature_search_result
        from _literature_search import dedupe_literature_results, flatten_literature_results, is_semantic_scholar_not_found_error, is_semantic_scholar_rate_limit_error, judge_literature_candidates_with_llm, literature_result_unique_key, rank_literature_results, search_semantic_scholar, select_literature_result, summarize_literature_result
        from _project import load_search, save_search
        from _utils import clamp_int, find_by_id, new_id, normalize_key
    seed_search = load_search(search_id)
    request_context = _request_context or SemanticScholarGraphRequestContext(sub_hypothesis_id="standalone")
    request_context.ensure_retry_budget()
    results = seed_search.get("results", [])
    if not results:
        raise ValueError(f"Search {search_id} has no seed results to expand.")
    try:
        seed = results[int(result_index)]
    except (IndexError, TypeError, ValueError) as exc:
        raise ValueError(f"Invalid seed result_index {result_index} for search {search_id}") from exc
    if not isinstance(seed, dict):
        raise ValueError(f"Seed result is not a paper object: {search_id}:{result_index}")

    lookup_ids = semantic_scholar_lookup_ids(seed)
    lookup_id = lookup_ids[0] if lookup_ids else ""
    if not lookup_ids:
        raise ValueError("Seed paper has no Semantic Scholar id, DOI, or arXiv id for graph expansion.")

    selected_direction = normalize_key(direction)
    edge_kinds = ["references", "citations"] if selected_direction == "both" else [selected_direction]
    raw_edges: list[dict[str, Any]] = []
    per_edge_limit = min(
        max(1, int(SCIENCE_SEMANTIC_SCHOLAR_EDGE_LIMIT)),
        max(1, clamp_int(max_results, 1, 200) // max(1, len(edge_kinds))),
    )
    errors: list[dict[str, str]] = []
    seed_not_indexed = False
    rate_limited_ids: list[str] = []
    for edge_kind in edge_kinds:
        if edge_kind not in {"references", "citations"}:
            errors.append({"edge": edge_kind, "error": "unknown direction"})
            continue
        edge_loaded = False
        not_found_errors: list[str] = []
        for candidate_lookup_id in lookup_ids:
            try:
                edges = fetch_semantic_scholar_edges(
                    candidate_lookup_id,
                    edge_kind,
                    limit=per_edge_limit,
                    request_context=request_context,
                )
                raw_edges.extend(edges)
                log_event("SCIENCE", "graph_expand_edges_loaded",
                          edge=edge_kind, count=len(edges), lookup_id=candidate_lookup_id[:60])
                lookup_id = candidate_lookup_id
                edge_loaded = True
                if candidate_lookup_id != lookup_ids[0]:
                    log_event(
                        "SCIENCE",
                        "graph_expand_lookup_alias_used",
                        original=lookup_ids[0],
                        used=candidate_lookup_id,
                    )
                break
            except Exception as exc:
                error_text = str(exc)
                if is_semantic_scholar_not_found_error(error_text):
                    not_found_errors.append(error_text)
                    continue
                errors.append(
                    {
                        "edge": edge_kind,
                        "lookup_id": candidate_lookup_id,
                        "error": error_text,
                        "rate_limited": is_semantic_scholar_rate_limit_error(error_text),
                    }
                )
                if is_semantic_scholar_rate_limit_error(error_text):
                    log_event("SCIENCE", "graph_expand_rate_limited", search_id=search_id, edge=edge_kind)
                    rate_limited_ids.append(f"{candidate_lookup_id}:{edge_kind}")
                    if raw_edges:
                        request_context.defer_provider_circuit(error_text)
                    else:
                        request_context.stop(error_text)
                    break
                if "semantic_scholar_graph_deferred_by_active_circuit" in error_text:
                    log_event(
                        "SCIENCE",
                        "graph_expand_deferred_by_provider_circuit",
                        search_id=search_id,
                        edge=edge_kind,
                    )
                    request_context.defer_provider_circuit(error_text)
                    break
                if "semantic_scholar_graph_" in error_text or "semantic_scholar_run_budget_exhausted" in error_text:
                    request_context.stop(error_text)
                    break
                else:
                    log_event("SCIENCE", "graph_expand_failed", search_id=search_id, edge=edge_kind, error=error_text)
                break
        if edge_loaded:
            continue
        if request_context.stopped:
            break
        if not_found_errors:
            seed_not_indexed = True
            error_text = not_found_errors[-1]
            errors.append(
                {
                    "edge": edge_kind,
                    "lookup_ids": lookup_ids,
                    "error": error_text,
                    "seed_not_indexed": True,
                }
            )
            log_event(
                "SCIENCE",
                "graph_expand_seed_not_indexed",
                search_id=search_id,
                edge=edge_kind,
                lookup_ids=",".join(lookup_ids),
            )
            break

    graph_results = dedupe_literature_results(
        [
            semantic_scholar_edge_to_result(edge)
            for edge in raw_edges
            if isinstance(edge, dict)
        ]
    )
    graph_query = query or str(seed_search.get("query", ""))
    ranked = rank_literature_results(graph_query, graph_results)[: clamp_int(max_results, 1, 200)]
    selected_depth = clamp_int(depth, 1, 2)
    second_layer_count = 0
    bridge_activation: dict[str, Any] = {"activated": False, "reason": "not_needed", "count": 0}
    if selected_depth >= 2 and ranked and not request_context.stopped:
        second_layer_results = (
            expand_second_layer_graph_results_with_community_awareness(
                ranked,
                graph_query,
                edge_kinds,
                max_results=max_results,
                top_k=second_layer_top_k,
                errors=errors,
                request_context=request_context,
            )
            if SCIENCE_COMMUNITY_AWARE_SEED_SELECTION
            else expand_second_layer_graph_results(
                ranked,
                graph_query,
                edge_kinds,
                max_results=max_results,
                top_k=second_layer_top_k,
                errors=errors,
                request_context=request_context,
            )
        )
        second_layer_count = len(second_layer_results)
        if second_layer_results:
            graph_results = dedupe_literature_results(graph_results + second_layer_results)
            ranked = rank_literature_results(graph_query, graph_results)[: clamp_int(max_results, 1, 200)]
        if allow_fallback and SCIENCE_BRIDGE_SEARCH_ENABLED and graph_needs_cross_community_bridge(ranked, max_results):
            before_summary = graph_community_summary(ranked)
            try:
                bridge_payload = json.loads(
                    search_cross_community_bridges(
                        search_id,
                        target_communities=before_summary["communities"],
                        max_results=max(1, min(int(SCIENCE_BRIDGE_SEARCH_MAX_RESULTS), clamp_int(max_results, 1, 200) // 2)),
                    )
                )
                bridge_search_id = str(bridge_payload.get("bridge_search_id") or "")
                bridge_record = load_search(bridge_search_id) if bridge_search_id else {}
                bridge_results = bridge_record.get("results", []) if isinstance(bridge_record.get("results"), list) else []
                seed_key = literature_result_unique_key(seed)
                seed_community = infer_literature_community(seed)
                prepared_bridges: list[dict[str, Any]] = []
                for item in bridge_results:
                    if not isinstance(item, dict):
                        continue
                    candidate = dict(item)
                    candidate["graph_relation"] = "cross_community_search"
                    candidate["graph_parent_key"] = seed_key
                    candidate["graph_parent_title"] = seed.get("title", "")
                    candidate["graph_parent_community"] = seed_community
                    candidate["graph_community"] = infer_literature_community(candidate)
                    candidate["graph_cross_community_bridge"] = True
                    candidate["graph_bridge_communities"] = f"{seed_community}->{candidate['graph_community']}"
                    candidate["expanded_depth"] = 2
                    prepared_bridges.append(candidate)
                if prepared_bridges:
                    graph_results = dedupe_literature_results(graph_results + prepared_bridges)
                    ranked = retain_community_bridge_candidates(
                        rank_literature_results(graph_query, graph_results),
                        prepared_bridges,
                        max_results=clamp_int(max_results, 1, 200),
                    )
                bridge_activation = {
                    "activated": True,
                    "reason": "sparse_graph",
                    "bridge_search_id": bridge_search_id,
                    "count": len(prepared_bridges),
                    "before": before_summary,
                    "after": graph_community_summary(ranked),
                }
                errors.append(
                    {
                        "edge": "cross_community_bridge_search",
                        "count": len(prepared_bridges),
                        "community_coverage_before": before_summary["coverage"],
                    }
                )
                log_event(
                    "SCIENCE",
                    "bridge_search_activated",
                    search_id=search_id,
                    bridge_search_id=bridge_search_id,
                    bridge_count=len(prepared_bridges),
                )
            except Exception as exc:
                bridge_activation = {"activated": True, "reason": "bridge_search_failed", "count": 0, "error": str(exc)[:240]}
                errors.append({"edge": "cross_community_bridge_search", "error": str(exc)[:240]})
                log_event("SCIENCE", "bridge_search_failed", source_search_id=search_id, error=str(exc)[:160])

    # --- Seed rotation: try alternative seeds if primary produced empty graph ---
    seed_rotation_used = False
    if not ranked and allow_fallback and len(results) > 1:
        max_alt_attempts = min(2, len(results) - 1)
        for alt_offset in range(1, max_alt_attempts + 1):
            alt_index = (result_index + alt_offset) % len(results)
            alt_seed = results[alt_index]
            if not isinstance(alt_seed, dict):
                continue
            alt_lookup_ids = semantic_scholar_lookup_ids(alt_seed)
            if not alt_lookup_ids:
                continue
            log_event("SCIENCE", "graph_expand_seed_rotation", search_id=search_id,
                      original_index=result_index, alt_index=alt_index,
                      alt_title=str(alt_seed.get("title", ""))[:120], attempt=alt_offset)
            alt_raw_edges: list[dict[str, Any]] = []
            alt_rate_limited: list[str] = []
            alt_not_indexed = False
            for alt_edge_kind in edge_kinds:
                for alt_candidate_id in alt_lookup_ids:
                    try:
                        alt_edges = fetch_semantic_scholar_edges(
                            alt_candidate_id,
                            alt_edge_kind,
                            limit=per_edge_limit,
                            request_context=request_context,
                        )
                        log_event("SCIENCE", "graph_expand_alt_edges_loaded",
                                  edge=alt_edge_kind, count=len(alt_edges), alt_index=alt_index)
                        alt_raw_edges.extend(alt_edges)
                        break
                    except Exception as alt_exc:
                        alt_err = str(alt_exc)
                        if is_semantic_scholar_not_found_error(alt_err):
                            alt_not_indexed = True
                            continue
                        if is_semantic_scholar_rate_limit_error(alt_err):
                            alt_rate_limited.append(f"{alt_candidate_id}:{alt_edge_kind}")
                            if alt_raw_edges:
                                request_context.defer_provider_circuit(alt_err)
                            else:
                                request_context.stop(alt_err)
                            break
                        if "semantic_scholar_graph_deferred_by_active_circuit" in alt_err:
                            request_context.defer_provider_circuit(alt_err)
                            break
                        break
            alt_graph_results = dedupe_literature_results(
                [semantic_scholar_edge_to_result(e) for e in alt_raw_edges if isinstance(e, dict)]
            )
            alt_ranked = rank_literature_results(graph_query, alt_graph_results)[:clamp_int(max_results, 1, 200)]
            if not alt_ranked:
                log_event("SCIENCE", "graph_expand_alt_empty", alt_index=alt_index, attempt=alt_offset)
                continue
            # Alternative seed succeeded — use its results
            seed_rotation_used = True
            ranked = alt_ranked
            graph_results = alt_graph_results
            seed = alt_seed
            lookup_id = alt_lookup_ids[0]
            lookup_ids = alt_lookup_ids
            result_index = alt_index
            seed_not_indexed = alt_not_indexed
            rate_limited_ids = alt_rate_limited
            errors.append({"edge": "seed_rotation", "alt_index": alt_index, "edges_found": len(alt_raw_edges)})
            log_event("SCIENCE", "graph_expand_seed_rotation_success",
                      search_id=search_id, alt_index=alt_index,
                      edges_found=len(alt_raw_edges), count=len(alt_ranked))
            break

    fallback_used = False
    if not ranked and allow_fallback:
        fallback_used = True
        fallback_max = min(max_results, 30)
        fallback_block = search_semantic_scholar(graph_query, max_results=fallback_max)
        fallback_results = flatten_literature_results([fallback_block])
        seed_key = literature_result_unique_key(seed)
        fallback_results = [item for item in fallback_results if literature_result_unique_key(item) != seed_key]
        for item in fallback_results:
            item["graph_relation"] = "keyword_fallback"
            item["expanded_from_search_id"] = search_id
            item["expanded_from_result_index"] = result_index
            item["seed_title"] = seed.get("title", "")
        ranked = rank_literature_results(graph_query, dedupe_literature_results(fallback_results))[: clamp_int(max_results, 1, 200)]
        errors.append(
            {
                "edge": "fallback_keyword_expansion",
                "error": "citation graph returned no usable neighbors; fell back to Semantic Scholar keyword search",
                "seed_not_indexed": seed_not_indexed,
                "rate_limited_empty": bool(rate_limited_ids),
            }
        )
        log_event(
            "SCIENCE",
            "graph_expand_fallback",
            seed_search_id=search_id,
            reason="rate_limited_empty" if rate_limited_ids else ("seed_not_indexed" if seed_not_indexed else "empty_graph"),
            count=len(ranked),
        )
    louvain_expansion_analysis = (
        annotate_expansion_results_with_louvain(seed, ranked, graph_query)
        if ranked
        else {"status": "not_run", "reason": "no ranked graph results", "community_map": {}, "bridge_nodes": []}
    )
    graph_search_id = new_id("graph")
    for index, item in enumerate(ranked):
        item.setdefault("graph_community", infer_literature_community(item))
        item["result_index"] = index
        item["search_id"] = graph_search_id
        item["expanded_from_search_id"] = search_id
        item["expanded_from_result_index"] = result_index
        item["seed_title"] = seed.get("title", "")

    louvain_expansion_seeds = [
        {
            "result_index": item.get("result_index"),
            "title": item.get("title", ""),
            "semantic_scholar_id": item.get("semantic_scholar_id"),
            "louvain_community": item.get("louvain_community"),
            "connected_communities": item.get("louvain_connected_communities", []),
            "bridge_score": item.get("louvain_bridge_score", 0.0),
            "publication_quality_score": item.get("publication_quality_score", 0.0),
            "relevance_score": item.get("relevance_score", 0.0),
        }
        for item in ranked
        if isinstance(item, dict) and float(item.get("louvain_bridge_score") or 0.0) > 0.0
    ]
    louvain_expansion_seeds.sort(
        key=lambda item: (
            -float(item.get("bridge_score") or 0.0),
            -float(item.get("publication_quality_score") or 0.0),
            -float(item.get("relevance_score") or 0.0),
            int(item.get("result_index") or 0),
        )
    )

    graph_budget = request_context.snapshot()
    stop_reason_lower = str(request_context.stop_reason or "").lower()
    if request_context.provider_circuit_deferred and ranked:
        graph_status = "partial_edges_loaded"
    elif request_context.provider_circuit_deferred:
        graph_status = "deferred_by_provider_circuit"
    elif request_context.stopped and ("429" in stop_reason_lower or "rate limit" in stop_reason_lower or "suspended" in stop_reason_lower):
        graph_status = "rate_limited_partial"
    elif request_context.stopped:
        graph_status = "budget_limited_partial"
    elif bool(graph_budget.get("batch_capacity_limited")):
        graph_status = "batch_capacity_limited_partial"
    elif ranked:
        graph_status = "complete"
    else:
        graph_status = "empty"
    record = {
        "search_id": graph_search_id,
        "kind": "citation_graph_expansion",
        "query": graph_query,
        "seed_search_id": search_id,
        "seed_result_index": result_index,
        "seed_title": seed.get("title", ""),
        "seed_lookup_id": lookup_id,
        "seed_lookup_ids": lookup_ids,
        "direction": selected_direction,
        "depth": selected_depth,
        "second_layer_count": second_layer_count,
        "community_summary": graph_community_summary(ranked),
        "louvain_analysis": louvain_expansion_analysis,
        "louvain_expansion_seeds": louvain_expansion_seeds[:10],
        "bridge_activation": bridge_activation,
        "createdAt": time.time(),
        "total_results": len(ranked),
        "results": ranked,
        "errors": errors,
        "fallback_used": fallback_used,
        "seed_not_indexed": seed_not_indexed,
        "graph_status": graph_status,
        "semantic_scholar_request_budget": graph_budget,
        "provider_blocks": [
            {
                "provider": "semantic_scholar_graph",
                "status": graph_status,
                "results": ranked,
                "errors": errors,
            }
        ],
    }
    save_search(record)
    selected = None
    llm_judgement = None
    if ranked:
        if use_llm:
            llm_judgement = judge_literature_candidates_with_llm(graph_query, ranked[: min(10, len(ranked))])
            chosen = find_by_id(ranked, "result_index", llm_judgement.get("selected_result_index"))
            selected = chosen or ranked[0]
        else:
            selected = ranked[0]
    response = {
        "graph_search_id": graph_search_id,
        "seed": summarize_literature_result(seed),
        "direction": selected_direction,
        "depth": selected_depth,
        "second_layer_count": second_layer_count,
        "community_summary": record["community_summary"],
        "louvain_analysis": {
            "status": louvain_expansion_analysis.get("status", "not_run"),
            "reason": louvain_expansion_analysis.get("reason", ""),
            "num_communities": louvain_expansion_analysis.get("num_communities", 0),
            "modularity": louvain_expansion_analysis.get("modularity"),
            "structural_node_count": louvain_expansion_analysis.get("structural_node_count", 0),
            "ignored_artificial_edge_count": louvain_expansion_analysis.get("ignored_artificial_edge_count", 0),
            "outlier_communities": [
                {
                    "community_id": item.get("community_id"),
                    "size": item.get("size"),
                    "disposition": item.get("disposition"),
                    "priority": item.get("priority"),
                }
                for item in louvain_expansion_analysis.get("outlier_communities", [])
                if isinstance(item, dict)
            ],
            "bridge_nodes": louvain_expansion_seeds[:5],
        },
        "bridge_activation": bridge_activation,
        "total_results": len(ranked),
        "selected": summarize_literature_result(selected) if selected else None,
        "top_results": [summarize_literature_result(item) for item in ranked[:10]],
        "llm_judgement": llm_judgement,
        "errors": errors,
        "fallback_used": fallback_used,
        "seed_not_indexed": seed_not_indexed,
        "graph_status": graph_status,
        "semantic_scholar_request_budget": graph_budget,
        "next_step": "Use louvain_analysis.bridge_nodes as cross-community seeds when present; otherwise use select_literature_result(graph_search_id) or import_literature_search_result(project_id, graph_search_id, result_index).",
    }
    log_event(
        "SCIENCE",
        "graph_expanded",
        seed_search_id=search_id,
        graph_search_id=graph_search_id,
        count=len(ranked),
        graph_status=graph_status,
        graph_requests_used=graph_budget["requests_used"],
        graph_429_responses=graph_budget["rate_limit_responses"],
    )
    return json.dumps(response, ensure_ascii=False, indent=2)


def rank_subhypothesis_graph_seed_candidates(
    results: list[dict[str, Any]],
    query: str,
) -> list[dict[str, Any]]:
    """Rank strict, peer-reviewed graph seeds with top venues as a hard tier.

    Top-venue candidates always precede regular-journal candidates.  Relevance
    is the primary ordering signal *within* each tier, so a merely prestigious
    but off-topic paper cannot outrank a more relevant paper in the same tier.
    Preprints, suspicious venues, missing venues, and papers without a
    Semantic Scholar-compatible identifier are deliberately excluded.
    """
    try:
        from ._literature_search import (
            has_suspicious_literature_flags,
            is_flagship_root_override_candidate,
            is_preprint_literature_result,
            is_top_venue_result,
            literature_result_unique_key,
            rank_literature_results,
        )
        from ._utils import numeric_value, normalize_space
    except ImportError:
        from _literature_search import (
            has_suspicious_literature_flags,
            is_flagship_root_override_candidate,
            is_preprint_literature_result,
            is_top_venue_result,
            literature_result_unique_key,
            rank_literature_results,
        )
        from _utils import numeric_value, normalize_space

    ranked = rank_literature_results(query, [item for item in results if isinstance(item, dict)])
    eligible: list[dict[str, Any]] = []
    seen: set[str] = set()
    for candidate in ranked:
        key = literature_result_unique_key(candidate)
        venue = normalize_space(candidate.get("venue", ""))
        relevance_components = candidate.get("relevance_components") if isinstance(candidate.get("relevance_components"), dict) else {}
        if (
            not key
            or key in seen
            or not venue
            or not semantic_scholar_lookup_id(candidate)
            or float(relevance_components.get("text_score") or 0.0) <= 0.0
            or is_preprint_literature_result(candidate)
            or has_suspicious_literature_flags(candidate)
            or float(candidate.get("publication_quality_score") or 0.0) < 0.45
        ):
            continue
        seen.add(key)
        item = dict(candidate)
        if is_flagship_root_override_candidate(item):
            venue_tier = "flagship"
            tier_rank = 0
        elif is_top_venue_result(item):
            venue_tier = "top_q1_or_reputable"
            tier_rank = 0
        else:
            venue_tier = "regular_peer_reviewed"
            tier_rank = 1
        lookup_ids = semantic_scholar_lookup_ids(item)
        graph_expandability = 1.0 if str(item.get("semantic_scholar_id") or "").strip() else (0.9 if any(value.startswith("DOI:") for value in lookup_ids) else 0.8)
        item["graph_seed_venue_tier"] = venue_tier
        item["graph_seed_tier_rank"] = tier_rank
        item["graph_expandability"] = graph_expandability
        item["graph_seed_selection_reason"] = (
            "eligible top-venue paper; ranked by sub-hypothesis relevance"
            if tier_rank == 0
            else "top-venue pool exhausted; highest-relevance eligible regular-journal paper"
        )
        item["graph_seed_sort_key"] = [
            tier_rank,
            round(float(item.get("relevance_score") or 0.0), 6),
            graph_expandability,
            round(float(item.get("publication_quality_score") or 0.0), 6),
            numeric_value(item.get("citation_count")),
        ]
        eligible.append(item)
    eligible.sort(
        key=lambda item: (
            int(item.get("graph_seed_tier_rank") or 0),
            -float(item.get("relevance_score") or 0.0),
            -float(item.get("graph_expandability") or 0.0),
            -float(item.get("publication_quality_score") or 0.0),
            -numeric_value(item.get("citation_count")),
            str(item.get("title") or ""),
        )
    )
    return eligible


def subhypothesis_graph_seed_attempt_plan(
    candidates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Bound graph calls while always reserving attempts for regular journals."""
    top = [item for item in candidates if int(item.get("graph_seed_tier_rank") or 0) == 0]
    regular = [item for item in candidates if int(item.get("graph_seed_tier_rank") or 0) > 0]
    planned = top[:4] + regular[:2]
    if len(planned) < SUBHYPOTHESIS_GRAPH_MAX_SEED_ATTEMPTS:
        planned.extend(top[4 : 4 + SUBHYPOTHESIS_GRAPH_MAX_SEED_ATTEMPTS - len(planned)])
    if len(planned) < SUBHYPOTHESIS_GRAPH_MAX_SEED_ATTEMPTS:
        planned.extend(regular[2 : 2 + SUBHYPOTHESIS_GRAPH_MAX_SEED_ATTEMPTS - len(planned)])
    return planned[:SUBHYPOTHESIS_GRAPH_MAX_SEED_ATTEMPTS]


def build_subhypothesis_louvain_graphs(
    project_id: str,
    branch_runs: list[dict[str, Any]],
    *,
    max_results_per_seed: int = 40,
) -> dict[str, Any]:
    """Build strict two-seed, depth-two Louvain graphs for sub-hypotheses.

    The second-layer fan-out is intentionally a code-level invariant of three.
    This orchestration never requests keyword fallback and excludes artificial
    bridge-search results from the merged structural graph.
    """
    try:
        from ._literature_search import literature_result_unique_key, semantic_scholar_run_budget_status
        from ._project import load_project, load_search, save_project, save_search
        from ._research_alignment import assess_candidate_alignment, evidence_kind_from_branch
        from ._utils import clamp_int, new_id
    except ImportError:
        from _literature_search import literature_result_unique_key, semantic_scholar_run_budget_status
        from _project import load_project, load_search, save_project, save_search
        from _research_alignment import assess_candidate_alignment, evidence_kind_from_branch
        from _utils import clamp_int, new_id

    project = load_project(project_id)
    source_state_version = int(project.get("state_version") or 0)
    subhypotheses = {
        str(item.get("id") or ""): item
        for item in project.get("sub_hypotheses", [])
        if isinstance(item, dict) and str(item.get("id") or "")
    }
    local_records: list[dict[str, Any]] = []
    branch_reports: list[dict[str, Any]] = []
    for branch_run in branch_runs:
        if not isinstance(branch_run, dict):
            continue
        sub_id = str(branch_run.get("sub_hypothesis_id") or "")
        search_id = str(branch_run.get("search_id") or "")
        subhypothesis = subhypotheses.get(sub_id, {})
        query = str(
            branch_run.get("query")
            or subhypothesis.get("retrieval_query")
            or subhypothesis.get("focus")
            or ""
        ).strip()
        if not sub_id or not search_id:
            branch_reports.append(
                optional_graph_seed_insufficient_report(
                    sub_hypothesis_id=sub_id,
                    search_id=search_id,
                    reason="missing sub-hypothesis id or frozen search id",
                    reason_code="missing_seed_identity_or_frozen_search",
                )
            )
            continue
        run_budget = semantic_scholar_run_budget_status()
        if bool(run_budget.get("graph_suspended")):
            reason = str(run_budget.get("graph_suspend_reason") or "graph traffic suspended")
            report = {
                "sub_hypothesis_id": sub_id,
                "search_id": search_id,
                "status": "graph_skipped_global_rate_limit",
                "reason": f"Semantic Scholar graph traffic was suspended before this sub-hypothesis: {reason}",
                "seed_papers": [],
                "semantic_scholar_request_budget": run_budget,
            }
            branch_reports.append(report)
            log_event(
                "SCIENCE",
                "subhypothesis_louvain_graph_skipped_global_rate_limit",
                project_id=project_id,
                sub_hypothesis_id=sub_id,
                **run_budget,
            )
            continue
        try:
            search = load_search(search_id)
        except Exception as exc:
            branch_reports.append(
                optional_graph_seed_insufficient_report(
                    sub_hypothesis_id=sub_id,
                    search_id=search_id,
                    reason=f"could not load frozen search: {str(exc)[:240]}",
                    reason_code="frozen_search_unavailable",
                )
            )
            continue
        candidates = rank_subhypothesis_graph_seed_candidates(search.get("results", []), query)
        alignment_contract = branch_run.get("alignment_contract") if isinstance(branch_run.get("alignment_contract"), dict) else {}
        allow_noncore_graph_seeds = bool(branch_run.get("allow_noncore_graph_seeds"))
        alignment_rejected = 0
        if alignment_contract:
            qualified_candidates: list[dict[str, Any]] = []
            for candidate in candidates:
                assessment = assess_candidate_alignment(
                    candidate,
                    alignment_contract,
                    requested_evidence_kind=evidence_kind_from_branch(str(candidate.get("query_branch") or "")),
                )
                noncore_seed_eligible = bool(
                    allow_noncore_graph_seeds
                    and assessment.get("corpus_admitted") is True
                    and not assessment.get("off_topic")
                    and not assessment.get("true_off_topic")
                    and not assessment.get("exclusion_hits")
                )
                if not assessment.get("core_eligible") and not noncore_seed_eligible:
                    alignment_rejected += 1
                    continue
                qualified_candidates.append({
                    **candidate,
                    "alignment_assessment": assessment,
                    "graph_seed_policy": (
                        "related_corpus_seed_fallback_without_direct_core"
                        if noncore_seed_eligible and not assessment.get("core_eligible")
                        else "strict_core_seed"
                    ),
                    "claim_strength_effect": (
                        "no_claim_strength_increase"
                        if noncore_seed_eligible and not assessment.get("core_eligible")
                        else str(candidate.get("claim_strength_effect") or "")
                    ),
                })
            candidates = qualified_candidates
            if alignment_rejected:
                log_event(
                    "SCIENCE",
                    "subhypothesis_graph_seed_rejected_alignment",
                    project_id=project_id,
                    sub_hypothesis_id=sub_id,
                    rejected=alignment_rejected,
                    eligible=len(candidates),
                    allow_noncore_graph_seeds=allow_noncore_graph_seeds,
                )
        graph_request_context = SemanticScholarGraphRequestContext(sub_hypothesis_id=sub_id)
        accepted: list[dict[str, Any]] = []
        failed_attempts: list[dict[str, Any]] = []
        for candidate in subhypothesis_graph_seed_attempt_plan(candidates):
            if graph_request_context.stopped:
                break
            if len(accepted) >= SUBHYPOTHESIS_GRAPH_SEEDS_PER_BRANCH:
                break
            try:
                result_index = int(candidate.get("result_index"))
            except (TypeError, ValueError):
                failed_attempts.append(
                    {"title": candidate.get("title", ""), "reason": "missing stable result_index"}
                )
                continue
            try:
                expansion = json.loads(
                    expand_literature_graph(
                        search_id,
                        result_index=result_index,
                        query=query,
                        direction="both",
                        max_results=clamp_int(max_results_per_seed, 1, 200),
                        use_llm=False,
                        depth=2,
                        second_layer_top_k=SUBHYPOTHESIS_GRAPH_SECOND_LAYER_TOP_K,
                        allow_fallback=False,
                        _request_context=graph_request_context,
                    )
                )
                graph_search_id = str(expansion.get("graph_search_id") or "")
                graph_search = load_search(graph_search_id) if graph_search_id else {}
                real_results = [
                    item
                    for item in graph_search.get("results", [])
                    if isinstance(item, dict) and citation_result_is_structural(item)
                ]
                if not graph_search_id or not real_results or expansion.get("fallback_used"):
                    failed_attempts.append(
                        {
                            "result_index": result_index,
                            "title": candidate.get("title", ""),
                            "venue_tier": candidate.get("graph_seed_venue_tier"),
                            "reason": "strict citation expansion returned no structural neighbors",
                        }
                    )
                    continue
                accepted.append(
                    {
                        "seed": candidate,
                        "seed_id": f"{sub_id}:S{len(accepted) + 1}",
                        "graph_search_id": graph_search_id,
                        "graph_search": graph_search,
                        "real_results": real_results,
                        "graph_status": str(expansion.get("graph_status") or "complete"),
                    }
                )
                if str(expansion.get("graph_status") or "") in {
                    "rate_limited_partial",
                    "budget_limited_partial",
                    "deferred_by_provider_circuit",
                }:
                    reason = str((expansion.get("semantic_scholar_request_budget") or {}).get("stop_reason") or expansion.get("graph_status"))
                    if str(expansion.get("graph_status") or "") == "deferred_by_provider_circuit":
                        graph_request_context.defer_provider_circuit(reason)
                    else:
                        graph_request_context.stop(reason)
                    break
            except Exception as exc:
                failed_attempts.append(
                    {
                        "result_index": result_index,
                        "title": candidate.get("title", ""),
                        "venue_tier": candidate.get("graph_seed_venue_tier"),
                        "reason": str(exc)[:240],
                    }
                )
        if graph_request_context.stopped:
            stopped_snapshot = graph_request_context.snapshot()
            stopped_status = (
                "partial_edges_loaded"
                if accepted and stopped_snapshot.get("provider_circuit_deferred")
                else "deferred_by_provider_circuit"
                if stopped_snapshot.get("provider_circuit_deferred")
                else "rate_limited_partial"
            )
            if accepted:
                record = merge_subhypothesis_seed_expansions(
                    project_id=project_id,
                    source_state_version=source_state_version,
                    sub_hypothesis_id=sub_id,
                    query=query,
                    source_search_id=search_id,
                    accepted=accepted,
                )
                record["graph_status"] = stopped_status
                record["semantic_scholar_request_budget"] = stopped_snapshot
                save_search(record)
                local_records.append(record)
                report = summarize_subhypothesis_louvain_record(record)
                report["status"] = stopped_status
                report["reason"] = graph_request_context.stop_reason
                report["failed_seed_attempts"] = failed_attempts
                report["semantic_scholar_request_budget"] = stopped_snapshot
            else:
                report = {
                    "sub_hypothesis_id": sub_id,
                    "search_id": search_id,
                    "status": stopped_status,
                    "reason": graph_request_context.stop_reason,
                    "seed_papers": [],
                    "failed_seed_attempts": failed_attempts,
                    "semantic_scholar_request_budget": stopped_snapshot,
                }
            branch_reports.append(report)
            log_event(
                "SCIENCE",
                (
                    "subhypothesis_louvain_graph_deferred_by_provider_circuit"
                    if stopped_status == "deferred_by_provider_circuit"
                    else "subhypothesis_louvain_graph_partial_edges_loaded"
                    if stopped_status == "partial_edges_loaded"
                    else "subhypothesis_louvain_graph_rate_limited_partial"
                ),
                project_id=project_id,
                accepted=len(accepted),
                **stopped_snapshot,
            )
            continue
        if len(accepted) < SUBHYPOTHESIS_GRAPH_SEEDS_PER_BRANCH:
            report = optional_graph_seed_insufficient_report(
                sub_hypothesis_id=sub_id,
                search_id=search_id,
                reason="fewer than two eligible seeds produced strict citation neighbors",
                reason_code="fewer_than_two_graph_seeds",
                eligible_seed_candidate_count=len(candidates),
                alignment_rejected_seed_candidate_count=alignment_rejected,
                accepted_seed_count=len(accepted),
                seed_papers=[
                    summarize_subhypothesis_graph_seed(item)
                    for item in accepted
                ],
                failed_seed_attempts=failed_attempts,
            )
            branch_reports.append(report)
            log_event(
                "SCIENCE",
                "subhypothesis_louvain_graph_seed_insufficient",
                project_id=project_id,
                sub_hypothesis_id=sub_id,
                eligible=len(candidates),
                accepted=len(accepted),
                status=OPTIONAL_GRAPH_SEED_INSUFFICIENT_STATUS,
                blocking=False,
                next_phase=GRAPH_SEED_INSUFFICIENT_NEXT_PHASE,
            )
            continue
        try:
            record = merge_subhypothesis_seed_expansions(
                project_id=project_id,
                source_state_version=source_state_version,
                sub_hypothesis_id=sub_id,
                query=query,
                source_search_id=search_id,
                accepted=accepted,
            )
            save_search(record)
            local_records.append(record)
            report = summarize_subhypothesis_louvain_record(record)
            report["failed_seed_attempts"] = failed_attempts
            branch_reports.append(report)
            log_event(
                "SCIENCE",
                "subhypothesis_louvain_graph_complete",
                project_id=project_id,
                sub_hypothesis_id=sub_id,
                graph_id=record["search_id"],
                nodes=record["node_count"],
                edges=record["edge_count"],
                communities=record["louvain_analysis"].get("num_communities", 0),
            )
        except Exception as exc:
            branch_reports.append(
                {
                    "sub_hypothesis_id": sub_id,
                    "search_id": search_id,
                    "status": "graph_build_failed",
                    "reason": str(exc)[:500],
                    "seed_papers": [summarize_subhypothesis_graph_seed(item) for item in accepted],
                    "failed_seed_attempts": failed_attempts,
                    "second_layer_top_k": SUBHYPOTHESIS_GRAPH_SECOND_LAYER_TOP_K,
                    "allow_fallback": False,
                }
            )
            log_event(
                "SCIENCE",
                "subhypothesis_louvain_graph_failed",
                project_id=project_id,
                sub_hypothesis_id=sub_id,
                error=str(exc)[:240],
            )

    global_record = merge_global_subhypothesis_louvain_graphs(
        project_id,
        source_state_version,
        local_records,
    )
    if global_record:
        save_search(global_record)

    has_rate_limited_partial = any(
        isinstance(item, dict) and item.get("status") in {"rate_limited_partial", "partial_edges_loaded"}
        for item in branch_reports
    )
    has_provider_circuit_deferred = any(
        isinstance(item, dict) and item.get("status") == "deferred_by_provider_circuit"
        for item in branch_reports
    )
    has_globally_skipped_graph = any(
        isinstance(item, dict) and item.get("status") == "graph_skipped_global_rate_limit"
        for item in branch_reports
    )
    has_seed_insufficient = any(
        isinstance(item, dict)
        and item.get("status") == OPTIONAL_GRAPH_SEED_INSUFFICIENT_STATUS
        for item in branch_reports
    )
    stage_status = (
        "rate_limited_partial"
        if has_rate_limited_partial
        else "deferred_by_provider_circuit"
        if has_provider_circuit_deferred
        else "graph_skipped_global_rate_limit"
        if has_globally_skipped_graph
        else "complete" if local_records else OPTIONAL_GRAPH_SEED_INSUFFICIENT_STATUS
    )
    next_phase = (
        "gap_detection_with_louvain_enrichment"
        if local_records
        else GRAPH_SEED_INSUFFICIENT_NEXT_PHASE
    )

    project = load_project(project_id)
    report_by_sub_id = {
        str(item.get("sub_hypothesis_id") or ""): item
        for item in branch_reports
        if str(item.get("sub_hypothesis_id") or "")
    }
    for subhypothesis in project.get("sub_hypotheses", []):
        if not isinstance(subhypothesis, dict):
            continue
        report = report_by_sub_id.get(str(subhypothesis.get("id") or ""))
        if report:
            subhypothesis["literature_graph"] = report
    stage_report = {
        "source_state_version": source_state_version,
        "seed_policy": {
            "seeds_per_subhypothesis": SUBHYPOTHESIS_GRAPH_SEEDS_PER_BRANCH,
            "direction": "both",
            "depth": 2,
            "second_layer_top_k": SUBHYPOTHESIS_GRAPH_SECOND_LAYER_TOP_K,
            "allow_fallback": False,
            "include_artificial_edges_in_louvain": False,
        },
        "branches": branch_reports,
        "global_graph": summarize_subhypothesis_louvain_record(global_record) if global_record else {},
        "semantic_scholar_request_budget": semantic_scholar_run_budget_status(),
        "status": stage_status,
        "legacy_status": (
            LEGACY_GRAPH_SEED_INSUFFICIENT_STATUS
            if has_seed_insufficient and not local_records
            else ""
        ),
        "optional_enrichment": True,
        "blocking": False,
        "next_phase": next_phase,
        "createdAt": time.time(),
    }
    project.setdefault("sub_hypothesis_graph_runs", []).append(stage_report)
    project["latest_sub_hypothesis_graph_run"] = stage_report
    save_project(project)
    return {
        "project_id": project_id,
        **stage_report,
    }


def citation_result_is_structural(result: dict[str, Any]) -> bool:
    try:
        from ._utils import normalize_key
    except ImportError:
        from _utils import normalize_key
    relation = normalize_key(result.get("graph_relation", ""))
    relation = relation.removeprefix("cross_community_bridge_").removeprefix("second_layer_")
    return relation in {"reference", "citation"}


def summarize_subhypothesis_graph_seed(accepted: dict[str, Any]) -> dict[str, Any]:
    seed = accepted.get("seed") if isinstance(accepted.get("seed"), dict) else {}
    return {
        "seed_id": accepted.get("seed_id"),
        "result_index": seed.get("result_index"),
        "title": seed.get("title", ""),
        "venue": seed.get("venue", ""),
        "venue_tier": seed.get("graph_seed_venue_tier", ""),
        "selection_reason": seed.get("graph_seed_selection_reason", ""),
        "relevance_score": seed.get("relevance_score", 0.0),
        "publication_quality_score": seed.get("publication_quality_score", 0.0),
        "graph_expandability": seed.get("graph_expandability", 0.0),
        "semantic_scholar_id": seed.get("semantic_scholar_id"),
        "doi": seed.get("doi"),
        "graph_search_id": accepted.get("graph_search_id"),
        "structural_neighbor_count": len(accepted.get("real_results") or []),
    }


def merge_subhypothesis_seed_expansions(
    *,
    project_id: str,
    source_state_version: int,
    sub_hypothesis_id: str,
    query: str,
    source_search_id: str,
    accepted: list[dict[str, Any]],
) -> dict[str, Any]:
    try:
        from ._literature_search import literature_result_unique_key
        from ._utils import new_id
    except ImportError:
        from _literature_search import literature_result_unique_key
        from _utils import new_id

    nodes: dict[str, dict[str, Any]] = {}
    result_node_ids: dict[str, str] = {}
    seed_node_ids: dict[str, str] = {}
    seed_key_by_id: dict[str, str] = {}
    for accepted_seed in accepted:
        seed = accepted_seed["seed"]
        seed_id = str(accepted_seed["seed_id"])
        seed_key = literature_result_unique_key(seed)
        seed_node = relation_graph_node(seed, query, role="seed")
        seed_node["seed_ids"] = [seed_id]
        seed_node["sub_hypothesis_ids"] = [sub_hypothesis_id]
        nodes[str(seed_node["node_id"])] = seed_node
        result_node_ids[seed_key] = str(seed_node["node_id"])
        seed_node_ids[seed_id] = str(seed_node["node_id"])
        seed_key_by_id[seed_id] = seed_key
    for accepted_seed in accepted:
        seed_id = str(accepted_seed["seed_id"])
        for result in accepted_seed.get("real_results", []):
            key = literature_result_unique_key(result)
            if not key:
                continue
            node = relation_graph_node(result, query, role="paper")
            node_id = str(node["node_id"])
            if node_id not in nodes:
                node["discovered_from_seed_ids"] = [seed_id]
                node["sub_hypothesis_ids"] = [sub_hypothesis_id]
                nodes[node_id] = node
            elif seed_id not in nodes[node_id].setdefault("discovered_from_seed_ids", []):
                nodes[node_id]["discovered_from_seed_ids"].append(seed_id)
            result_node_ids[key] = node_id

    edges: dict[tuple[str, str], dict[str, Any]] = {}
    for accepted_seed in accepted:
        seed_id = str(accepted_seed["seed_id"])
        seed_node_id = seed_node_ids[seed_id]
        seed_key = seed_key_by_id[seed_id]
        for result in accepted_seed.get("real_results", []):
            node_id = result_node_ids.get(literature_result_unique_key(result))
            if not node_id:
                continue
            parent_key = str(result.get("graph_parent_key") or seed_key)
            parent_id = result_node_ids.get(parent_key) or seed_node_id
            edge = relation_graph_edge(parent_id, node_id, str(result.get("graph_relation") or ""), result)
            if not edge or edge.get("edge_type") != "citation_graph":
                continue
            edge_key = (str(edge["source"]), str(edge["target"]))
            existing = edges.get(edge_key)
            if existing:
                if seed_id not in existing.setdefault("discovered_from_seed_ids", []):
                    existing["discovered_from_seed_ids"].append(seed_id)
                relation = str(edge.get("relation") or "")
                if relation and relation not in existing.setdefault("observed_relations", [existing.get("relation")]):
                    existing["observed_relations"].append(relation)
            else:
                edge["discovered_from_seed_ids"] = [seed_id]
                edge["observed_relations"] = [edge.get("relation")]
                edge["sub_hypothesis_ids"] = [sub_hypothesis_id]
                edges[edge_key] = edge
    node_list = list(nodes.values())
    edge_list = list(edges.values())
    louvain = run_louvain_community_analysis(node_list, edge_list, include_artificial_edges=False)
    annotate_nodes_with_louvain(node_list, louvain)
    add_graph_centrality(node_list, edge_list)
    research_branches = louvain_research_branches(sub_hypothesis_id, node_list, louvain)
    graph_id = new_id("shrelgraph")
    ranked_nodes = sorted(
        node_list,
        key=lambda item: (
            -float(item.get("centrality_score") or 0.0),
            -float(item.get("publication_quality_score") or 0.0),
            -float(item.get("relevance_score") or 0.0),
        ),
    )
    return {
        "search_id": graph_id,
        "kind": "subhypothesis_louvain_graph",
        "project_id": project_id,
        "source_state_version": source_state_version,
        "sub_hypothesis_id": sub_hypothesis_id,
        "source_search_id": source_search_id,
        "query": query,
        "createdAt": time.time(),
        "seed_policy": {
            "seeds_per_subhypothesis": SUBHYPOTHESIS_GRAPH_SEEDS_PER_BRANCH,
            "direction": "both",
            "depth": 2,
            "second_layer_top_k": SUBHYPOTHESIS_GRAPH_SECOND_LAYER_TOP_K,
            "allow_fallback": False,
        },
        "seed_papers": [summarize_subhypothesis_graph_seed(item) for item in accepted],
        "source_graph_search_ids": [str(item.get("graph_search_id") or "") for item in accepted],
        "node_count": len(ranked_nodes),
        "edge_count": len(edge_list),
        "fallback_used": False,
        "edge_summary": summarize_relation_edges(edge_list),
        "louvain_analysis": louvain,
        "research_branches": research_branches,
        "nodes": ranked_nodes,
        "edges": edge_list,
        "total_results": len(ranked_nodes),
        "results": ranked_nodes,
    }


def annotate_nodes_with_louvain(nodes: list[dict[str, Any]], louvain: dict[str, Any]) -> None:
    community_map = louvain.get("community_map") if isinstance(louvain.get("community_map"), dict) else {}
    bridge_map = {
        str(item.get("node_id") or ""): item
        for item in louvain.get("bridge_nodes", [])
        if isinstance(item, dict)
    }
    for node in nodes:
        node_id = str(node.get("node_id") or "")
        if node_id in community_map:
            node["louvain_community"] = community_map[node_id]
        bridge = bridge_map.get(node_id)
        if bridge:
            node["louvain_bridge_score"] = bridge.get("bridge_score", 0.0)
            node["louvain_connected_communities"] = bridge.get("connected_communities", [])


def add_graph_centrality(nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> None:
    node_ids = [str(item.get("node_id") or "") for item in nodes if str(item.get("node_id") or "")]
    pagerank = compute_pagerank(node_ids, edges)
    degree = compute_graph_degree(node_ids, edges)
    for node in nodes:
        node_id = str(node.get("node_id") or "")
        node["pagerank"] = round(float(pagerank.get(node_id) or 0.0), 6)
        node["degree_centrality"] = round(float(degree.get(node_id) or 0.0), 6)
        node["centrality_score"] = round(
            0.7 * float(pagerank.get(node_id) or 0.0)
            + 0.3 * float(degree.get(node_id) or 0.0),
            6,
        )


def louvain_research_branches(
    scope_id: str,
    nodes: list[dict[str, Any]],
    louvain: dict[str, Any],
) -> list[dict[str, Any]]:
    community_map = louvain.get("community_map") if isinstance(louvain.get("community_map"), dict) else {}
    grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for node in nodes:
        node_id = str(node.get("node_id") or "")
        if node_id in community_map:
            grouped[int(community_map[node_id])].append(node)
    branches: list[dict[str, Any]] = []
    for community_id, members in sorted(grouped.items()):
        terms = Counter(
            str(term)
            for member in members
            for term in (member.get("mechanism_terms") or [])
            if str(term).strip()
        )
        top_terms = [term for term, _ in terms.most_common(4)]
        ranked = sorted(
            members,
            key=lambda item: (
                -float(item.get("centrality_score") or 0.0),
                -float(item.get("publication_quality_score") or 0.0),
                -float(item.get("relevance_score") or 0.0),
            ),
        )
        branches.append(
            {
                "branch_id": f"{scope_id}:C{community_id}",
                "community_id": community_id,
                "label": " / ".join(top_terms[:3]) or str(ranked[0].get("field") or "research branch"),
                "size": len(members),
                "top_terms": top_terms,
                "seed_ids": sorted({seed_id for item in members for seed_id in (item.get("seed_ids") or item.get("discovered_from_seed_ids") or [])}),
                "representative_papers": [summarize_relation_node(item) for item in ranked[:5]],
            }
        )
    return branches


def merge_global_subhypothesis_louvain_graphs(
    project_id: str,
    source_state_version: int,
    local_records: list[dict[str, Any]],
) -> dict[str, Any]:
    if not local_records:
        return {}
    try:
        from ._utils import new_id
    except ImportError:
        from _utils import new_id
    nodes: dict[str, dict[str, Any]] = {}
    edges: dict[tuple[str, str], dict[str, Any]] = {}
    for record in local_records:
        sub_id = str(record.get("sub_hypothesis_id") or "")
        for raw_node in record.get("nodes", []):
            if not isinstance(raw_node, dict):
                continue
            node_id = str(raw_node.get("node_id") or "")
            if not node_id:
                continue
            if node_id not in nodes:
                nodes[node_id] = dict(raw_node)
                nodes[node_id]["sub_hypothesis_ids"] = [sub_id]
            elif sub_id not in nodes[node_id].setdefault("sub_hypothesis_ids", []):
                nodes[node_id]["sub_hypothesis_ids"].append(sub_id)
        for raw_edge in record.get("edges", []):
            if not isinstance(raw_edge, dict) or raw_edge.get("edge_type") != "citation_graph":
                continue
            key = (
                str(raw_edge.get("source") or ""),
                str(raw_edge.get("target") or ""),
            )
            if not all(key):
                continue
            if key not in edges:
                edges[key] = dict(raw_edge)
                edges[key]["sub_hypothesis_ids"] = [sub_id]
            elif sub_id not in edges[key].setdefault("sub_hypothesis_ids", []):
                edges[key]["sub_hypothesis_ids"].append(sub_id)
    node_list = list(nodes.values())
    edge_list = list(edges.values())
    louvain = run_louvain_community_analysis(node_list, edge_list, include_artificial_edges=False)
    annotate_nodes_with_louvain(node_list, louvain)
    add_graph_centrality(node_list, edge_list)
    branches = louvain_research_branches("GLOBAL", node_list, louvain)
    graph_id = new_id("globalshgraph")
    ranked_nodes = sorted(node_list, key=lambda item: -float(item.get("centrality_score") or 0.0))
    return {
        "search_id": graph_id,
        "kind": "global_subhypothesis_louvain_graph",
        "project_id": project_id,
        "source_state_version": source_state_version,
        "source_graph_ids": [str(item.get("search_id") or "") for item in local_records],
        "createdAt": time.time(),
        "node_count": len(ranked_nodes),
        "edge_count": len(edge_list),
        "fallback_used": False,
        "edge_summary": summarize_relation_edges(edge_list),
        "louvain_analysis": louvain,
        "research_branches": branches,
        "nodes": ranked_nodes,
        "edges": edge_list,
        "total_results": len(ranked_nodes),
        "results": ranked_nodes,
    }


def summarize_subhypothesis_louvain_record(record: dict[str, Any]) -> dict[str, Any]:
    if not record:
        return {}
    louvain = record.get("louvain_analysis") if isinstance(record.get("louvain_analysis"), dict) else {}
    return {
        "sub_hypothesis_id": record.get("sub_hypothesis_id", ""),
        "graph_id": record.get("search_id", ""),
        "kind": record.get("kind", ""),
        "status": "success" if louvain.get("status") == "success" else str(louvain.get("status") or "not_run"),
        "source_search_id": record.get("source_search_id", ""),
        "node_count": record.get("node_count", 0),
        "edge_count": record.get("edge_count", 0),
        "seed_papers": record.get("seed_papers", []),
        "second_layer_top_k": SUBHYPOTHESIS_GRAPH_SECOND_LAYER_TOP_K,
        "allow_fallback": False,
        "num_communities": louvain.get("num_communities", 0),
        "modularity": louvain.get("modularity"),
        "bridge_nodes": louvain_recommended_expansion_seeds(record.get("nodes", []), louvain),
        "research_branches": record.get("research_branches", []),
    }

def fetch_semantic_scholar_edges_batch(
    parents: list[dict[str, Any]],
    edge_kinds: list[str],
    *,
    per_edge_limit: int,
    request_context: SemanticScholarGraphRequestContext,
) -> dict[str, dict[str, list[dict[str, Any]]]]:
    """Fetch second-layer structural neighbors for several parents in one POST.

    The paper batch endpoint does not return edge contexts/intents, so this is
    deliberately used only for depth-two structural discovery. First-layer
    evidence continues to use the detailed references/citations endpoints.
    """
    try:
        from ._literature_search import semantic_scholar_get_json
    except ImportError:
        from _literature_search import semantic_scholar_get_json
    parent_requests: list[tuple[str, str]] = []
    seen_lookups: set[str] = set()
    for parent in parents:
        lookup_ids = semantic_scholar_lookup_ids(parent)
        if lookup_ids and lookup_ids[0] not in seen_lookups:
            seen_lookups.add(lookup_ids[0])
            parent_requests.append((str(parent.get("semantic_scholar_id") or lookup_ids[0]), lookup_ids[0]))
    if not parent_requests:
        return {}
    requested_nested_fields = [
        "paperId", "title", "abstract", "year", "authors", "venue", "url",
        "externalIds", "citationCount", "influentialCitationCount", "referenceCount",
        "isOpenAccess",
    ]
    selected_edge_kinds = [kind for kind in edge_kinds if kind in {"references", "citations"}]
    if not selected_edge_kinds:
        return {}
    nested: list[str] = []
    for edge_kind in selected_edge_kinds:
        nested.extend(f"{edge_kind}.{field}" for field in requested_nested_fields)
    fields = ",".join(["paperId", *nested])
    cache_fields = "paper_batch_nested:" + ",".join(requested_nested_fields)
    limit = max(1, int(per_edge_limit))
    results: dict[str, dict[str, list[dict[str, Any]]]] = {}
    uncached_requests: list[tuple[str, str]] = []
    for parent_key, lookup_id in parent_requests:
        by_edge: dict[str, list[dict[str, Any]]] = {}
        has_miss = False
        for edge_kind in selected_edge_kinds:
            cache_path = _semantic_scholar_edge_cache_path(lookup_id, edge_kind, cache_fields, limit)
            cached = _read_semantic_scholar_edge_cache(cache_path)
            if cached is None:
                has_miss = True
            else:
                by_edge[edge_kind] = cached
        results[parent_key] = by_edge
        if has_miss:
            uncached_requests.append((parent_key, lookup_id))
    if not uncached_requests:
        log_event(
            "SCIENCE",
            "semantic_scholar_graph_batch_disk_cache_hit",
            parents=len(parent_requests),
            edge_kinds=",".join(selected_edge_kinds),
        )
        return results
    url = f"https://api.semanticscholar.org/graph/v1/paper/batch?{urlencode({'fields': fields})}"
    headers = {"User-Agent": "qwen-zhikan-papergraph/0.1"}
    if SEMANTIC_SCHOLAR_API_KEY:
        headers["x-api-key"] = SEMANTIC_SCHOLAR_API_KEY
    batch_max_ids = max(1, min(2, int(SCIENCE_SEMANTIC_SCHOLAR_GRAPH_BATCH_MAX_IDS)))
    requests_before = request_context.requests_used

    def is_response_capacity_error(error: Exception) -> bool:
        normalized = str(error or "").lower()
        return (
            "response would exceed maximum size" in normalized
            or ("maximum size" in normalized and "fewer ids" in normalized)
        )

    def persist_chunk(chunk: list[tuple[str, str]], papers: list[Any]) -> None:
        for (parent_key, lookup_id), paper in zip(chunk, papers):
            if not isinstance(paper, dict):
                continue
            by_edge = results.setdefault(parent_key, {})
            for edge_kind in selected_edge_kinds:
                if edge_kind in by_edge:
                    continue
                nested_papers = paper.get(edge_kind)
                if not isinstance(nested_papers, list):
                    by_edge[edge_kind] = []
                else:
                    wrapper_key = "citedPaper" if edge_kind == "references" else "citingPaper"
                    by_edge[edge_kind] = [
                        {
                            wrapper_key: child,
                            "contexts": [],
                            "intents": [],
                            "isInfluential": None,
                            "edge_metadata_source": "paper_batch_nested_structural",
                        }
                        for child in nested_papers[:limit]
                        if isinstance(child, dict)
                    ]
                _write_semantic_scholar_edge_cache(
                    _semantic_scholar_edge_cache_path(lookup_id, edge_kind, cache_fields, limit),
                    by_edge[edge_kind],
                )

    def fetch_chunk(chunk: list[tuple[str, str]]) -> None:
        """Fetch a capacity-safe batch and preserve prior chunks on a 400 split."""
        if not chunk or request_context.stopped:
            return
        ensure_semantic_scholar_graph_traffic_available(request_context)
        request_context.reserve_edge_request()
        try:
            payload = semantic_scholar_get_json(
                url,
                headers=headers,
                retry_budget=request_context.ensure_retry_budget(),
                traffic_class="graph",
                request_payload={"ids": [lookup_id for _, lookup_id in chunk]},
            )
        except Exception as exc:
            if not is_response_capacity_error(exc):
                raise
            request_context.note_batch_capacity_limit(str(exc))
            if len(chunk) == 1:
                log_event(
                    "WARN",
                    "semantic_scholar_graph_batch_parent_capacity_limited",
                    parent_id=chunk[0][1],
                    error=str(exc)[:180],
                )
                return
            split_at = max(1, len(chunk) // 2)
            log_event(
                "SCIENCE",
                "semantic_scholar_graph_batch_capacity_split",
                requested_ids=len(chunk),
                split_sizes=f"{split_at},{len(chunk) - split_at}",
                error=str(exc)[:180],
            )
            fetch_chunk(chunk[:split_at])
            fetch_chunk(chunk[split_at:])
            return
        persist_chunk(chunk, payload if isinstance(payload, list) else [])

    for start in range(0, len(uncached_requests), batch_max_ids):
        fetch_chunk(uncached_requests[start:start + batch_max_ids])
    log_event(
        "SCIENCE",
        "semantic_scholar_graph_batch_complete",
        parents=len(parent_requests),
        edge_kinds=",".join(selected_edge_kinds),
        returned_parents=len(results),
        batch_max_ids=batch_max_ids,
        batch_requests=request_context.requests_used - requests_before,
        capacity_limited=request_context.batch_capacity_limited,
    )
    return results


def expand_second_layer_graph_results(
    first_layer_ranked: list[dict[str, Any]],
    query: str,
    edge_kinds: list[str],
    max_results: int,
    top_k: int,
    errors: list[dict[str, Any]],
    community_aware: bool = False,
    request_context: SemanticScholarGraphRequestContext | None = None,
) -> list[dict[str, Any]]:
    try:
        from ._literature_search import dedupe_literature_results, is_semantic_scholar_not_found_error, is_semantic_scholar_rate_limit_error, literature_result_unique_key, rank_literature_results
        from ._utils import clamp_int, normalize_key
    except ImportError:
        from _literature_search import dedupe_literature_results, is_semantic_scholar_not_found_error, is_semantic_scholar_rate_limit_error, literature_result_unique_key, rank_literature_results
        from _utils import clamp_int, normalize_key
    seeds = (
        select_second_layer_seeds_with_community_awareness(first_layer_ranked, top_k=top_k)
        if community_aware
        else select_second_layer_seeds(first_layer_ranked, top_k=top_k)
    )
    if not seeds:
        return []
    per_edge_limit = min(
        max(1, int(SCIENCE_SEMANTIC_SCHOLAR_EDGE_LIMIT)),
        max(1, clamp_int(max_results, 1, 200) // max(1, len(seeds) * max(1, len(edge_kinds)))),
    )
    expanded: list[dict[str, Any]] = []
    batched_edges: dict[str, dict[str, list[dict[str, Any]]]] | None = None
    if (
        SCIENCE_SEMANTIC_SCHOLAR_GRAPH_BATCH_ENABLED
        and request_context is not None
        and len(seeds) > 1
        and not request_context.stopped
    ):
        try:
            batched_edges = fetch_semantic_scholar_edges_batch(
                seeds,
                edge_kinds,
                per_edge_limit=per_edge_limit,
                request_context=request_context,
            )
        except Exception as exc:
            error_text = str(exc)
            errors.append(
                {
                    "edge": "second_layer_batch",
                    "error": error_text,
                    "rate_limited": is_semantic_scholar_rate_limit_error(error_text),
                }
            )
            if is_semantic_scholar_rate_limit_error(error_text) or "semantic_scholar_graph_" in error_text:
                if "semantic_scholar_graph_deferred_by_active_circuit" in error_text:
                    request_context.defer_provider_circuit(error_text)
                else:
                    request_context.stop(error_text)
                return []
            log_event("WARN", "semantic_scholar_graph_batch_fallback", error=error_text[:180])
            batched_edges = None
    for parent in seeds:
        if request_context is not None and request_context.stopped:
            break
        parent_community = infer_literature_community(parent)
        lookup_ids = semantic_scholar_lookup_ids(parent)
        if not lookup_ids:
            continue
        parent_key = literature_result_unique_key(parent)
        batch_parent_key = str(parent.get("semantic_scholar_id") or lookup_ids[0])
        for edge_kind in edge_kinds:
            if request_context is not None and request_context.stopped:
                break
            edges: list[dict[str, Any]] = []
            last_not_found = ""
            if batched_edges is not None:
                edges = list((batched_edges.get(batch_parent_key) or {}).get(edge_kind) or [])
                lookup_candidates: list[str] = []
            else:
                lookup_candidates = lookup_ids
            for lookup_id in lookup_candidates:
                try:
                    edges = fetch_semantic_scholar_edges(
                        lookup_id,
                        edge_kind,
                        limit=per_edge_limit,
                        request_context=request_context,
                    )
                    break
                except Exception as exc:
                    error_text = str(exc)
                    if is_semantic_scholar_not_found_error(error_text):
                        last_not_found = error_text
                        continue
                    errors.append(
                        {
                            "edge": f"second_layer_{edge_kind}",
                            "parent_title": str(parent.get("title") or ""),
                            "lookup_id": lookup_id,
                            "error": error_text,
                            "rate_limited": is_semantic_scholar_rate_limit_error(error_text),
                        }
                    )
                    if is_semantic_scholar_rate_limit_error(error_text):
                        log_event("SCIENCE", "graph_expand_rate_limited", search_id="second_layer", edge=edge_kind)
                        if request_context is not None:
                            if expanded:
                                request_context.defer_provider_circuit(error_text)
                            else:
                                request_context.stop(error_text)
                    elif "semantic_scholar_graph_deferred_by_active_circuit" in error_text:
                        if request_context is not None:
                            request_context.defer_provider_circuit(error_text)
                    elif "semantic_scholar_graph_" in error_text or "semantic_scholar_run_budget_exhausted" in error_text:
                        if request_context is not None:
                            request_context.stop(error_text)
                    else:
                        log_event("SCIENCE", "graph_expand_failed", search_id="second_layer", edge=edge_kind, error=error_text)
                    break
            if not edges and last_not_found:
                errors.append(
                    {
                        "edge": f"second_layer_{edge_kind}",
                        "parent_title": str(parent.get("title") or ""),
                        "lookup_ids": lookup_ids,
                        "error": last_not_found,
                        "seed_not_indexed": True,
                    }
                )
                continue
            for edge in edges:
                if not isinstance(edge, dict):
                    continue
                result = semantic_scholar_edge_to_result(edge)
                base_relation = str(result.get("graph_relation") or normalize_key(edge_kind))
                child_community = infer_literature_community(result)
                is_bridge = community_aware and communities_are_distinct(parent_community, child_community)
                result["graph_relation"] = (
                    f"cross_community_bridge_{base_relation}"
                    if is_bridge
                    else f"second_layer_{base_relation}"
                )
                result["graph_parent_key"] = parent_key
                result["graph_parent_title"] = parent.get("title", "")
                result["graph_parent_result_index"] = parent.get("result_index")
                result["graph_parent_community"] = parent_community
                result["graph_community"] = child_community
                result["graph_cross_community_bridge"] = is_bridge
                result["graph_bridge_communities"] = f"{parent_community}->{child_community}" if is_bridge else ""
                result["expanded_depth"] = 2
                expanded.append(result)
    seed_keys = {literature_result_unique_key(item) for item in first_layer_ranked}
    expanded = [item for item in expanded if literature_result_unique_key(item) not in seed_keys]
    ranked = rank_literature_results(query, dedupe_literature_results(expanded))
    return ranked


def expand_second_layer_graph_results_with_community_awareness(
    first_layer_ranked: list[dict[str, Any]],
    query: str,
    edge_kinds: list[str],
    max_results: int,
    top_k: int,
    errors: list[dict[str, Any]],
    request_context: SemanticScholarGraphRequestContext | None = None,
) -> list[dict[str, Any]]:
    return expand_second_layer_graph_results(
        first_layer_ranked,
        query,
        edge_kinds,
        max_results=max_results,
        top_k=top_k,
        errors=errors,
        community_aware=True,
        request_context=request_context,
    )


def graph_community_summary(results: list[dict[str, Any]]) -> dict[str, Any]:
    profiles = [literature_community_profile(item) for item in results if isinstance(item, dict)]
    communities = [str(profile.get("community") or "mixed") for profile in profiles]
    counts = Counter(communities)
    coverage_set: set[str] = set()
    for profile in profiles:
        coverage_set.update(str(community) for community in profile.get("active_communities", []) if community != "general")
    if not coverage_set:
        for community in counts:
            if community == "translational":
                coverage_set.update({"medicine", "biology"})
            elif community != "mixed":
                coverage_set.add(community)
    return {
        "counts": dict(sorted(counts.items())),
        "coverage": len(coverage_set),
        "communities": sorted(coverage_set),
    }


def graph_needs_cross_community_bridge(results: list[dict[str, Any]], max_results: int) -> bool:
    target = max(1, int(max_results or 1))
    threshold = max(0.05, min(1.0, float(SCIENCE_SPARSE_GRAPH_THRESHOLD)))
    sparse_by_count = len(results) < max(2, math.ceil(target * threshold))
    summary = graph_community_summary(results)
    required_coverage = max(1, int(SCIENCE_MIN_CROSS_COMMUNITY_SEEDS))
    sparse_by_coverage = bool(results) and int(summary["coverage"]) < required_coverage
    return sparse_by_count or sparse_by_coverage


def retain_community_bridge_candidates(
    ranked_results: list[dict[str, Any]],
    bridge_candidates: list[dict[str, Any]],
    max_results: int,
) -> list[dict[str, Any]]:
    try:
        from ._literature_search import literature_result_unique_key
        from ._utils import clamp_int
    except ImportError:
        from _literature_search import literature_result_unique_key
        from _utils import clamp_int
    limit = clamp_int(max_results, 1, 200)
    selected = [item for item in ranked_results[:limit] if isinstance(item, dict)]
    if any(item.get("graph_cross_community_bridge") for item in selected):
        return selected
    bridge_keys = {literature_result_unique_key(item) for item in bridge_candidates if isinstance(item, dict)}
    bridge = next(
        (item for item in ranked_results if isinstance(item, dict) and literature_result_unique_key(item) in bridge_keys),
        None,
    )
    if not bridge:
        return selected
    selected = [item for item in selected if literature_result_unique_key(item) != literature_result_unique_key(bridge)]
    if len(selected) >= limit:
        selected = selected[: limit - 1]
    selected.append(bridge)
    return selected


def bridge_query_plan(
    query: str,
    limit: int | None = None,
    target_communities: list[str] | None = None,
) -> list[str]:
    try:
        from ._models import infer_research_domain
    except ImportError:
        from _models import infer_research_domain
    core_terms = re.findall(r"[A-Za-z0-9-]{3,}", str(query or "").lower())
    generic = {"study", "analysis", "research", "effect", "using", "with", "from", "into", "between"}
    core = " ".join(term for term in core_terms if term not in generic)[:120].strip()
    if not core:
        core = "scientific research"
    inferred_domain = infer_research_domain(query)
    requested_domains = [str(item) for item in (target_communities or []) if str(item)]
    domain = requested_domains[0] if requested_domains else inferred_domain
    bridge_facets = {
        "physics": ("mathematical modeling", "experimental instrumentation", "data analysis"),
        "mathematics": ("physical modeling", "statistical inference", "computational application"),
        "computer_science": ("statistical learning", "scientific computing", "real-world systems"),
        "quantitative_biology": ("molecular mechanism", "statistical modeling", "clinical translation"),
        "quantitative_finance": ("econometric modeling", "statistical learning", "market mechanism"),
        "statistics": ("scientific application", "computational method", "causal inference"),
        "electrical_engineering": ("signal processing", "control system", "physical instrumentation"),
        "economics": ("econometric evidence", "statistical inference", "policy mechanism"),
        "medicine": ("molecular mechanism", "biomarker stratification", "clinical outcome"),
        "biology": ("molecular mechanism", "quantitative modeling", "translational outcome"),
        "chemistry": ("computational chemistry", "materials engineering", "reaction mechanism"),
    }
    facets = bridge_facets.get(domain, ("theoretical mechanism", "computational analysis", "experimental validation"))
    queries = [f"{core} {facet}" for facet in facets]
    configured_limit = max(1, int(limit if limit is not None else SCIENCE_BRIDGE_SEARCH_QUERY_LIMIT))
    return list(dict.fromkeys(queries))[:configured_limit]


def is_cross_community_candidate(result: dict[str, Any]) -> bool:
    profile = literature_community_profile(result)
    active_communities = [str(item) for item in profile.get("active_communities", []) if str(item) != "general"]
    return str(profile["community"]) == "translational" or len(set(active_communities)) >= 2


def search_cross_community_bridges(
    search_id: str,
    target_communities: list[str] | None = None,
    max_results: int | None = None,
) -> str:
    try:
        from ._literature_search import dedupe_literature_results, flatten_literature_results, rank_literature_results, search_semantic_scholar
        from ._project import load_search, save_search
        from ._utils import clamp_int, new_id
    except ImportError:
        from _literature_search import dedupe_literature_results, flatten_literature_results, rank_literature_results, search_semantic_scholar
        from _project import load_search, save_search
        from _utils import clamp_int, new_id
    source_search = load_search(search_id)
    source_query = str(source_search.get("query") or "")
    requested = SCIENCE_BRIDGE_SEARCH_MAX_RESULTS if max_results is None else max_results
    limit = clamp_int(requested, 1, min(40, max(1, int(SCIENCE_BRIDGE_SEARCH_MAX_RESULTS))))
    queries = bridge_query_plan(source_query, target_communities=target_communities)
    collected: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    per_query = max(1, math.ceil(limit / max(1, len(queries))))
    for bridge_query in queries:
        try:
            block = search_semantic_scholar(bridge_query, max_results=per_query)
            for item in flatten_literature_results([block]):
                if not isinstance(item, dict):
                    continue
                candidate = dict(item)
                candidate["bridge_query"] = bridge_query
                candidate["graph_relation"] = "cross_community_search"
                candidate["graph_cross_community_bridge"] = True
                candidate["graph_community"] = infer_literature_community(candidate)
                collected.append(candidate)
        except Exception as exc:
            errors.append({"query": bridge_query, "error": str(exc)[:240]})
            log_event("SCIENCE", "bridge_search_failed", source_search_id=search_id, query=bridge_query, error=str(exc)[:160])
    deduped = dedupe_literature_results(collected)
    filtered = [item for item in deduped if is_cross_community_candidate(item)]
    ranked = rank_literature_results(source_query, filtered)[:limit]
    bridge_search_id = new_id("bridge")
    record = {
        "search_id": bridge_search_id,
        "kind": "cross_community_bridge_search",
        "source_search_id": search_id,
        "query": source_query,
        "target_communities": list(target_communities or []),
        "bridge_queries": queries,
        "createdAt": time.time(),
        "total_results": len(ranked),
        "results": ranked,
        "errors": errors,
        "community_summary": graph_community_summary(ranked),
    }
    save_search(record)
    log_event(
        "SCIENCE",
        "bridge_search_completed",
        source_search_id=search_id,
        bridge_search_id=bridge_search_id,
        results=len(ranked),
        queries=len(queries),
    )
    return json.dumps(
        {
            "bridge_search_id": bridge_search_id,
            "source_search_id": search_id,
            "total_results": len(ranked),
            "bridge_queries_used": queries,
            "community_summary": record["community_summary"],
            "errors": errors,
            "next_step": "Review or import bridge candidates explicitly; bridge search never imports papers automatically.",
        },
        ensure_ascii=False,
        indent=2,
    )

def select_second_layer_seeds(results: list[dict[str, Any]], top_k: int = 3) -> list[dict[str, Any]]:
    try:
        from ._utils import clamp_int
    except ImportError:
        from _utils import clamp_int
    limit = clamp_int(top_k, 0, 10)
    if limit <= 0:
        return []
    candidates = [item for item in results if semantic_scholar_lookup_id(item)]
    candidates.sort(key=second_layer_seed_score, reverse=True)
    return candidates[:limit]


def infer_literature_community(result: dict[str, Any]) -> str:
    profile = literature_community_profile(result)
    return str(profile.get("community") or "mixed")


def literature_community_profile(result: dict[str, Any]) -> dict[str, Any]:
    try:
        from ._models import research_domain_profile
    except ImportError:
        from _models import research_domain_profile
    text = " ".join(
        str(result.get(key) or "")
        for key in ("title", "abstract", "venue", "fields_of_study", "publication_types")
    ).lower()
    catalog_profile = research_domain_profile(text)
    counts = {
        str(community): int(score)
        for community, score in dict(catalog_profile.get("scores") or {}).items()
        if int(score or 0) > 0
    }
    total = sum(counts.values())
    proportions = {
        community: round(count / total, 4) if total else 0.0
        for community, count in counts.items()
    }
    return {
        "counts": counts,
        "proportions": proportions,
        "community": infer_literature_community_from_counts(counts),
        "active_communities": list(catalog_profile.get("active_domains") or []),
        "matched_keywords": catalog_profile.get("matched_keywords") or {},
        "matched_subfields": catalog_profile.get("matched_subfields") or {},
    }


def infer_literature_community_from_counts(counts: dict[str, int]) -> str:
    medicine = int(counts.get("medicine") or 0)
    biology = int(counts.get("biology") or 0)
    total = max(1, sum(int(value or 0) for value in counts.values()))
    if medicine and biology and min(medicine, biology) / total >= 0.2:
        return "translational"
    ranked = sorted(
        ((str(community), int(score or 0)) for community, score in counts.items() if int(score or 0) > 0),
        key=lambda item: (-item[1], item[0]),
    )
    return ranked[0][0] if ranked else "mixed"


def communities_are_distinct(parent: str, child: str) -> bool:
    left = str(parent or "mixed")
    right = str(child or "mixed")
    if left == right or "mixed" in {left, right}:
        return False
    return True


def community_diversity_score(result: dict[str, Any]) -> float:
    proportions = literature_community_profile(result)["proportions"]
    active = [float(value) for value in proportions.values() if float(value) > 0]
    if len(active) <= 1:
        return 0.0
    entropy = -sum(value * math.log(value) for value in active)
    return round(min(1.0, entropy / math.log(len(active))), 4)


def select_second_layer_seeds_with_community_awareness(
    results: list[dict[str, Any]],
    top_k: int = 3,
    min_bridge_attempts: int | None = None,
) -> list[dict[str, Any]]:
    try:
        from ._utils import clamp_int
    except ImportError:
        from _utils import clamp_int
    limit = clamp_int(top_k, 0, 10)
    if limit <= 0:
        return []
    candidates = [dict(item) for item in results if isinstance(item, dict) and semantic_scholar_lookup_id(item)]
    if not candidates:
        return []
    def selection_community(item: dict[str, Any]) -> str:
        structural = item.get("louvain_community")
        if structural is not None and str(structural) != "":
            return f"louvain:{structural}"
        return infer_literature_community(item)

    community_counts = Counter(selection_community(item) for item in candidates)
    scored: list[tuple[float, float, str, dict[str, Any]]] = []
    for item in candidates:
        community = selection_community(item)
        base_score = second_layer_seed_score(item)
        rarity_bonus = 0.24 / max(1, community_counts[community])
        diversity_bonus = 0.14 * community_diversity_score(item)
        bridge_bonus = 0.16 * max(0.0, min(1.0, float(item.get("louvain_bridge_score") or 0.0)))
        drift_penalty = 0.12 if str(item.get("louvain_priority") or "") == "low" else 0.0
        score = base_score + rarity_bonus + diversity_bonus + bridge_bonus - drift_penalty
        item["graph_community"] = community
        item["community_seed_score"] = round(score, 5)
        scored.append((score, base_score, community, item))
    scored.sort(key=lambda entry: (-entry[0], -entry[1], str(entry[3].get("title") or "")))
    required_communities = min(
        limit,
        max(1, int(min_bridge_attempts if min_bridge_attempts is not None else SCIENCE_MIN_CROSS_COMMUNITY_SEEDS)),
        len(community_counts),
    )
    selected: list[dict[str, Any]] = []
    selected_communities: set[str] = set()
    for _, _, community, item in scored:
        if community in selected_communities:
            continue
        selected.append(item)
        selected_communities.add(community)
        if len(selected) >= required_communities:
            break
    for _, _, _, item in scored:
        if len(selected) >= limit:
            break
        if item not in selected:
            selected.append(item)
    return selected[:limit]

def second_layer_seed_score(result: dict[str, Any]) -> float:
    try:
        from ._literature_scoring import literature_impact_score, publication_quality_assessment
    except ImportError:
        from _literature_scoring import literature_impact_score, publication_quality_assessment
    quality = float(result.get("publication_quality_score") or publication_quality_assessment(result)["quality_score"])
    relevance = float(result.get("relevance_score") or 0.0)
    components = result.get("relevance_components") if isinstance(result.get("relevance_components"), dict) else {}
    impact = float(components.get("impact_score") or literature_impact_score(result))
    edge_bonus = 0.08 if result.get("graph_relation") in {"reference", "citation"} else 0.0
    return 0.42 * quality + 0.35 * relevance + 0.15 * impact + edge_bonus

def _semantic_scholar_edge_cache_path(
    lookup_id: str,
    edge_kind: str,
    fields: str,
    limit: int,
) -> Path:
    material = json.dumps(
        {
            "scope": SEMANTIC_SCHOLAR_RATE_SCOPE,
            "lookup_id": str(lookup_id or ""),
            "edge_kind": str(edge_kind or ""),
            "fields": str(fields or ""),
            "limit": int(limit),
        },
        sort_keys=True,
        ensure_ascii=False,
    ).encode("utf-8")
    return Path(SCIENCE_SEMANTIC_SCHOLAR_EDGE_CACHE_DIR) / f"{hashlib.sha256(material).hexdigest()}.json"


def _read_semantic_scholar_edge_cache(path: Path) -> list[dict[str, Any]] | None:
    ttl = max(0.0, float(SCIENCE_SEMANTIC_SCHOLAR_EDGE_CACHE_TTL_SECONDS))
    if ttl <= 0 or not path.is_file():
        return None
    try:
        if time.time() - path.stat().st_mtime > ttl:
            return None
        with SEMANTIC_SCHOLAR_EDGE_CACHE_LOCK:
            payload = json.loads(path.read_text(encoding="utf-8"))
        data = payload.get("data") if isinstance(payload, dict) else None
        return [item for item in data if isinstance(item, dict)] if isinstance(data, list) else None
    except (OSError, ValueError, TypeError):
        return None


def _write_semantic_scholar_edge_cache(path: Path, data: list[dict[str, Any]]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "created_at": time.time(),
            "ttl_seconds": float(SCIENCE_SEMANTIC_SCHOLAR_EDGE_CACHE_TTL_SECONDS),
            "data": data,
        }
        temporary = path.with_suffix(f".tmp-{int(time.time() * 1_000_000)}")
        with SEMANTIC_SCHOLAR_EDGE_CACHE_LOCK:
            temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            temporary.replace(path)
    except OSError as exc:
        log_event("WARN", "semantic_scholar_edge_cache_write_failed", error=str(exc)[:180])


def fetch_semantic_scholar_edges(
    lookup_id: str,
    edge_kind: str,
    limit: int = 20,
    request_context: SemanticScholarGraphRequestContext | None = None,
) -> list[dict[str, Any]]:
    try:
        from ._literature_search import semantic_scholar_get_json
        from ._utils import clamp_int
    except ImportError:
        from _literature_search import semantic_scholar_get_json
        from _utils import clamp_int
    fields = ",".join(
        [
            "contexts",
            "intents",
            "isInfluential",
            "paperId",
            "title",
            "abstract",
            "year",
            "authors",
            "venue",
            "url",
            "externalIds",
            "citationCount",
            "influentialCitationCount",
            "referenceCount",
            "isOpenAccess",
        ]
    )
    normalized_limit = clamp_int(limit, 1, 100)
    cache_path = _semantic_scholar_edge_cache_path(lookup_id, edge_kind, fields, normalized_limit)
    cached = _read_semantic_scholar_edge_cache(cache_path)
    if cached is not None:
        log_event(
            "SCIENCE",
            "semantic_scholar_edge_cache_hit",
            edge=edge_kind,
            lookup_id=str(lookup_id)[:80],
            count=len(cached),
        )
        return cached
    if request_context is not None:
        ensure_semantic_scholar_graph_traffic_available(request_context)
        request_context.reserve_edge_request()
        retry_budget = request_context.ensure_retry_budget()
    else:
        retry_budget = None
    params = urlencode({"limit": normalized_limit, "fields": fields})
    url = f"https://api.semanticscholar.org/graph/v1/paper/{quote(lookup_id, safe='')}/{edge_kind}?{params}"
    headers = {"User-Agent": "qwen-zhikan-papergraph/0.1"}
    if SEMANTIC_SCHOLAR_API_KEY:
        headers["x-api-key"] = SEMANTIC_SCHOLAR_API_KEY
    payload = semantic_scholar_get_json(
        url,
        headers=headers,
        retry_budget=retry_budget,
        traffic_class="graph",
    )
    data = payload.get("data") or []
    edges = [item for item in data if isinstance(item, dict)]
    _write_semantic_scholar_edge_cache(cache_path, edges)
    return edges

def semantic_scholar_edge_to_result(edge: dict[str, Any]) -> dict[str, Any]:
    try:
        from ._literature_search import semantic_scholar_item_to_result
    except ImportError:
        from _literature_search import semantic_scholar_item_to_result
    relation = "reference" if "citedPaper" in edge else "citation"
    paper = edge.get("citedPaper") if relation == "reference" else edge.get("citingPaper")
    if not isinstance(paper, dict):
        paper = {key: value for key, value in edge.items() if key not in {"contexts", "intents", "isInfluential"}}
    result = semantic_scholar_item_to_result(paper)
    result["graph_relation"] = relation
    result["citation_contexts"] = edge.get("contexts") or []
    result["citation_intents"] = edge.get("intents") or []
    result["edge_is_influential"] = edge.get("isInfluential")
    result["provider"] = "semantic_scholar_graph"
    result["papergraph_input"]["provider"] = "semantic_scholar_graph"
    return result

def semantic_scholar_lookup_id(result: dict[str, Any]) -> str:
    ids = semantic_scholar_lookup_ids(result)
    return ids[0] if ids else ""

def semantic_scholar_lookup_ids(result: dict[str, Any]) -> list[str]:
    try:
        from ._utils import unique_preserve_order
    except ImportError:
        from _utils import unique_preserve_order
    candidates: list[str] = []
    semantic_id = str(result.get("semantic_scholar_id") or "").strip()
    if semantic_id:
        candidates.append(semantic_id)
    payload = result.get("papergraph_input") if isinstance(result.get("papergraph_input"), dict) else {}
    semantic_id = str(payload.get("semantic_scholar_id") or "").strip()
    if semantic_id:
        candidates.append(semantic_id)
    doi = str(result.get("doi") or payload.get("doi") or "").strip()
    if doi:
        candidates.append(f"DOI:{doi}")
    arxiv_id = str(result.get("arxiv_id") or payload.get("arxiv_id") or "").strip()
    if arxiv_id:
        candidates.append(f"ARXIV:{arxiv_id}")
        unversioned = re.sub(r"v\d+$", "", arxiv_id, flags=re.IGNORECASE)
        if unversioned and unversioned != arxiv_id:
            candidates.append(f"ARXIV:{unversioned}")
    return unique_preserve_order([candidate for candidate in candidates if candidate])


def louvain_dependency_status() -> dict[str, Any]:
    if not SCIENCE_LOUVAIN_ENABLED:
        return {"available": False, "status": "disabled", "reason": "SCIENCE_LOUVAIN_ENABLED is disabled"}
    if not LOUVAIN_AVAILABLE:
        return {"available": False, "status": "unavailable", "reason": "networkx with louvain_communities is not installed"}
    return {"available": True, "status": "available", "reason": "networkx louvain_communities is available"}


def build_louvain_network(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    include_artificial_edges: bool | None = None,
) -> tuple[Any, dict[str, dict[str, Any]], dict[str, Any]]:
    if not LOUVAIN_AVAILABLE:
        return None, {}, {"reason": "networkx is unavailable", "eligible_node_count": 0, "structural_edge_count": 0}
    include_artificial = (
        SCIENCE_LOUVAIN_INCLUDE_ARTIFICIAL_EDGES
        if include_artificial_edges is None
        else bool(include_artificial_edges)
    )
    max_nodes = max(3, int(SCIENCE_LOUVAIN_MAX_NODES))
    selected_nodes = [item for item in nodes if isinstance(item, dict) and str(item.get("node_id") or "")]
    selected_nodes.sort(key=lambda item: str(item.get("node_id") or ""))
    selected_nodes = selected_nodes[:max_nodes]
    node_attrs = {str(item["node_id"]): item for item in selected_nodes}
    graph = nx.Graph()
    structural_edge_count = 0
    ignored_artificial_edges = 0
    ignored_missing_node_edges = 0
    for edge in edges:
        if not isinstance(edge, dict):
            continue
        if edge.get("edge_type") == "artificial" and not include_artificial:
            ignored_artificial_edges += 1
            continue
        source = str(edge.get("source") or "")
        target = str(edge.get("target") or "")
        if not source or not target or source == target or source not in node_attrs or target not in node_attrs:
            ignored_missing_node_edges += 1
            continue
        try:
            weight = float(edge.get("weight") or 0.0)
        except (TypeError, ValueError):
            weight = 0.0
        if weight <= 0:
            continue
        if graph.has_edge(source, target):
            graph[source][target]["weight"] += weight
            graph[source][target]["edge_count"] += 1
        else:
            graph.add_edge(source, target, weight=weight, edge_count=1)
        structural_edge_count += 1
    participating_nodes = set(graph.nodes())
    return graph, node_attrs, {
        "eligible_node_count": len(node_attrs),
        "structural_node_count": len(participating_nodes),
        "excluded_isolate_count": max(0, len(node_attrs) - len(participating_nodes)),
        "structural_edge_count": structural_edge_count,
        "unique_edge_count": graph.number_of_edges(),
        "ignored_artificial_edge_count": ignored_artificial_edges,
        "ignored_missing_node_edge_count": ignored_missing_node_edges,
        "include_artificial_edges": include_artificial,
    }


def identify_louvain_bridge_nodes(
    graph: Any,
    community_map: dict[str, int],
    threshold: float | None = None,
) -> list[dict[str, Any]]:
    if graph is None or not community_map:
        return []
    bridge_threshold = max(0.0, min(1.0, float(
        SCIENCE_LOUVAIN_BRIDGE_THRESHOLD if threshold is None else threshold
    )))
    try:
        betweenness = nx.betweenness_centrality(graph, normalized=True, weight=None)
    except Exception:
        betweenness = {node_id: 0.0 for node_id in graph.nodes()}
    bridges: list[dict[str, Any]] = []
    for node_id in graph.nodes():
        community = community_map.get(str(node_id))
        if community is None:
            continue
        total_weight = 0.0
        cross_weight = 0.0
        connected_communities: set[int] = set()
        for neighbor_id, attrs in graph[node_id].items():
            weight = max(0.0, float(attrs.get("weight") or 0.0))
            total_weight += weight
            neighbor_community = community_map.get(str(neighbor_id))
            if neighbor_community is not None and neighbor_community != community:
                cross_weight += weight
                connected_communities.add(neighbor_community)
        if total_weight <= 0 or not connected_communities:
            continue
        cross_ratio = cross_weight / total_weight
        diversity = len(connected_communities)
        bridge_score = min(
            1.0,
            0.65 * cross_ratio
            + 0.2 * min(1.0, diversity / 2.0)
            + 0.15 * float(betweenness.get(node_id) or 0.0),
        )
        if bridge_score < bridge_threshold:
            continue
        bridges.append(
            {
                "node_id": str(node_id),
                "community": community,
                "cross_edge_weight": round(cross_weight, 4),
                "total_edge_weight": round(total_weight, 4),
                "cross_ratio": round(cross_ratio, 4),
                "connected_communities": sorted(connected_communities),
                "community_diversity": diversity,
                "betweenness_centrality": round(float(betweenness.get(node_id) or 0.0), 4),
                "bridge_score": round(bridge_score, 4),
            }
        )
    bridges.sort(
        key=lambda item: (
            -float(item["bridge_score"]),
            -float(item["cross_edge_weight"]),
            str(item["node_id"]),
        )
    )
    return bridges


def summarize_louvain_communities(
    graph: Any,
    community_map: dict[str, int],
    node_attrs: dict[str, dict[str, Any]],
    bridge_nodes: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    grouped: dict[int, list[str]] = defaultdict(list)
    for node_id, community_id in community_map.items():
        grouped[int(community_id)].append(str(node_id))
    bridge_by_community: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for bridge in bridge_nodes:
        bridge_by_community[int(bridge["community"])].append(bridge)
    summaries: list[dict[str, Any]] = []
    for community_id, member_ids in grouped.items():
        fields = Counter(
            str(node_attrs.get(node_id, {}).get("field") or "unknown")
            for node_id in member_ids
        )
        internal_weight = 0.0
        external_weight = 0.0
        for source, target, attrs in graph.edges(member_ids, data=True):
            weight = max(0.0, float(attrs.get("weight") or 0.0))
            if community_map.get(str(source)) == community_map.get(str(target)) == community_id:
                internal_weight += weight
            elif community_map.get(str(source)) == community_id or community_map.get(str(target)) == community_id:
                external_weight += weight
        ranked_members = sorted(
            (node_attrs.get(node_id, {}) for node_id in member_ids),
            key=lambda item: (
                -float(item.get("publication_quality_score") or 0.0),
                -float(item.get("relevance_score") or 0.0),
                str(item.get("title") or ""),
            ),
        )
        summaries.append(
            {
                "community_id": community_id,
                "size": len(member_ids),
                "primary_field": fields.most_common(1)[0][0] if fields else "unknown",
                "field_distribution": dict(fields),
                "internal_edge_weight": round(internal_weight, 4),
                "external_edge_weight": round(external_weight, 4),
                "bridge_count": len(bridge_by_community.get(community_id, [])),
                "bridge_nodes": bridge_by_community.get(community_id, [])[:5],
                "top_nodes": [
                    {
                        "node_id": str(item.get("node_id") or ""),
                        "title": str(item.get("title") or ""),
                        "quality_score": round(float(item.get("publication_quality_score") or 0.0), 4),
                    }
                    for item in ranked_members[:5]
                ],
            }
        )
    summaries.sort(key=lambda item: (-int(item["size"]), int(item["community_id"])))
    return summaries


def assess_louvain_topic_drift(
    graph: Any,
    community_map: dict[str, int],
    node_attrs: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    if graph is None or not community_map:
        return []
    seed_node_ids = [
        str(node_id)
        for node_id, attrs in node_attrs.items()
        if str(attrs.get("role") or "") == "seed" and str(node_id) in graph
    ]
    seed_communities = {
        int(community_map[seed_node_id])
        for seed_node_id in seed_node_ids
        if seed_node_id in community_map
    }
    grouped: dict[int, list[str]] = defaultdict(list)
    for node_id, community_id in community_map.items():
        grouped[int(community_id)].append(str(node_id))
    assessments: list[dict[str, Any]] = []
    for community_id, member_ids in grouped.items():
        relevance_values = [
            float(node_attrs.get(node_id, {}).get("relevance_score") or 0.0)
            for node_id in member_ids
        ]
        quality_values = [
            float(node_attrs.get(node_id, {}).get("publication_quality_score") or 0.0)
            for node_id in member_ids
        ]
        has_seed = community_id in seed_communities
        connected_to_seed = bool(
            seed_node_ids
            and any(
                nx.has_path(graph, seed_node_id, node_id)
                for seed_node_id in seed_node_ids
                for node_id in member_ids
            )
        )
        external_weight = 0.0
        total_weight = 0.0
        for node_id in member_ids:
            for neighbor_id, edge_attrs in graph[node_id].items():
                weight = max(0.0, float(edge_attrs.get("weight") or 0.0))
                total_weight += weight
                if community_map.get(str(neighbor_id)) != community_id:
                    external_weight += weight
        external_ratio = external_weight / total_weight if total_weight else 0.0
        average_relevance = sum(relevance_values) / max(1, len(relevance_values))
        average_quality = sum(quality_values) / max(1, len(quality_values))
        if has_seed:
            disposition = "core"
            priority = "high"
        elif not connected_to_seed:
            disposition = "disconnected_review"
            priority = "review"
        elif len(member_ids) <= 2 and external_ratio <= 0.18 and average_relevance < 0.4:
            disposition = "weakly_attached_review"
            priority = "low"
        else:
            disposition = "connected"
            priority = "normal"
        assessments.append(
            {
                "community_id": community_id,
                "size": len(member_ids),
                "contains_seed": has_seed,
                "connected_to_seed": connected_to_seed,
                "external_edge_ratio": round(external_ratio, 4),
                "average_relevance": round(average_relevance, 4),
                "average_quality": round(average_quality, 4),
                "disposition": disposition,
                "priority": priority,
                "node_ids": sorted(member_ids),
            }
        )
    assessments.sort(key=lambda item: (0 if item["contains_seed"] else 1, int(item["community_id"])))
    return assessments


def run_louvain_community_analysis(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    resolution: float | None = None,
    include_artificial_edges: bool | None = None,
) -> dict[str, Any]:
    dependency = louvain_dependency_status()
    base = {
        "node_count": len(nodes),
        "edge_count": len(edges),
        "community_map": {},
        "communities": [],
        "bridge_nodes": [],
        "has_bridges": False,
    }
    if not dependency["available"]:
        return {**base, "status": dependency["status"], "reason": dependency["reason"]}
    graph, node_attrs, graph_report = build_louvain_network(
        nodes,
        edges,
        include_artificial_edges=include_artificial_edges,
    )
    base.update(graph_report)
    if graph is None or graph.number_of_nodes() < 3 or graph.number_of_edges() < 2:
        return {
            **base,
            "status": "insufficient_structure",
            "reason": "Louvain requires at least three structurally connected papers and two relation edges.",
        }
    used_resolution = max(0.1, min(5.0, float(
        SCIENCE_LOUVAIN_RESOLUTION if resolution is None else resolution
    )))
    try:
        raw_communities = nx.algorithms.community.louvain_communities(
            graph,
            weight="weight",
            resolution=used_resolution,
            seed=42,
        )
        ordered_communities = sorted(
            (sorted(str(node_id) for node_id in members) for members in raw_communities),
            key=lambda members: (-len(members), members[0] if members else ""),
        )
        community_map = {
            node_id: community_id
            for community_id, members in enumerate(ordered_communities)
            for node_id in members
        }
        modularity = float(nx.algorithms.community.modularity(
            graph,
            [set(members) for members in ordered_communities],
            weight="weight",
            resolution=used_resolution,
        ))
    except Exception as exc:
        components = [sorted(str(node_id) for node_id in members) for members in nx.connected_components(graph)]
        ordered_components = sorted(components, key=lambda members: (-len(members), members[0] if members else ""))
        community_map = {
            node_id: component_id
            for component_id, members in enumerate(ordered_components)
            for node_id in members
        }
        bridges = identify_louvain_bridge_nodes(graph, community_map)
        return {
            **base,
            "status": "fallback_components",
            "reason": f"Louvain failed: {str(exc)[:240]}",
            "resolution_used": used_resolution,
            "community_map": community_map,
            "num_communities": len(ordered_components),
            "communities": summarize_louvain_communities(graph, community_map, node_attrs, bridges),
            "bridge_nodes": bridges[:20],
            "has_bridges": bool(bridges),
        }
    bridges = identify_louvain_bridge_nodes(graph, community_map)
    summaries = summarize_louvain_communities(graph, community_map, node_attrs, bridges)
    drift_assessment = assess_louvain_topic_drift(graph, community_map, node_attrs)
    return {
        **base,
        "status": "success",
        "resolution_used": used_resolution,
        "modularity": round(modularity, 6),
        "num_communities": len(ordered_communities),
        "community_map": community_map,
        "communities": summaries,
        "topic_drift_assessment": drift_assessment,
        "outlier_communities": [
            item for item in drift_assessment
            if item.get("disposition") in {"disconnected_review", "weakly_attached_review"}
        ],
        "bridge_nodes": bridges[:20],
        "has_bridges": bool(bridges),
    }


def louvain_recommended_expansion_seeds(
    nodes: list[dict[str, Any]],
    louvain_analysis: dict[str, Any],
    limit: int = 5,
) -> list[dict[str, Any]]:
    by_node_id = {
        str(node.get("node_id") or ""): node
        for node in nodes
        if isinstance(node, dict) and str(node.get("node_id") or "")
    }
    recommendations: list[dict[str, Any]] = []
    for bridge in louvain_analysis.get("bridge_nodes", []):
        if not isinstance(bridge, dict):
            continue
        node = by_node_id.get(str(bridge.get("node_id") or ""))
        if not node:
            continue
        recommendations.append(
            {
                "node_id": str(node.get("node_id") or ""),
                "title": str(node.get("title") or ""),
                "community": bridge.get("community"),
                "connected_communities": bridge.get("connected_communities", []),
                "bridge_score": bridge.get("bridge_score", 0.0),
                "publication_quality_score": node.get("publication_quality_score", 0.0),
                "relevance_score": node.get("relevance_score", 0.0),
                "semantic_scholar_id": node.get("semantic_scholar_id"),
            }
        )
    recommendations.sort(
        key=lambda item: (
            -float(item.get("bridge_score") or 0.0),
            -float(item.get("publication_quality_score") or 0.0),
            -float(item.get("relevance_score") or 0.0),
            str(item.get("node_id") or ""),
        )
    )
    return recommendations[: max(0, int(limit))]


def annotate_expansion_results_with_louvain(
    seed: dict[str, Any],
    results: list[dict[str, Any]],
    query: str,
) -> dict[str, Any]:
    try:
        from ._literature_search import literature_result_unique_key
    except ImportError:
        from _literature_search import literature_result_unique_key
    seed_node = relation_graph_node(seed, query, role="seed")
    nodes = {str(seed_node["node_id"]): seed_node}
    result_node_ids: dict[str, str] = {}
    for result in results:
        if not isinstance(result, dict):
            continue
        node = relation_graph_node(result, query, role="paper")
        node_id = str(node["node_id"])
        nodes[node_id] = node
        result_node_ids[literature_result_unique_key(result)] = node_id
    edges: list[dict[str, Any]] = []
    for result in results:
        if not isinstance(result, dict):
            continue
        result_key = literature_result_unique_key(result)
        node_id = result_node_ids.get(result_key)
        if not node_id:
            continue
        parent_id = result_node_ids.get(str(result.get("graph_parent_key") or "")) or str(seed_node["node_id"])
        edge = relation_graph_edge(parent_id, node_id, str(result.get("graph_relation") or "search_result"), result)
        if edge:
            edges.append(edge)
    analysis = run_louvain_community_analysis(list(nodes.values()), edges)
    community_map = analysis.get("community_map") if isinstance(analysis.get("community_map"), dict) else {}
    bridge_scores = {
        str(bridge.get("node_id") or ""): bridge
        for bridge in analysis.get("bridge_nodes", [])
        if isinstance(bridge, dict)
    }
    drift_by_community = {
        int(item.get("community_id")): item
        for item in analysis.get("topic_drift_assessment", [])
        if isinstance(item, dict) and item.get("community_id") is not None
    }
    for result in results:
        if not isinstance(result, dict):
            continue
        node_id = result_node_ids.get(literature_result_unique_key(result))
        if not node_id:
            continue
        if node_id in community_map:
            result["louvain_community"] = community_map[node_id]
            drift = drift_by_community.get(int(community_map[node_id]))
            if drift:
                result["louvain_community_disposition"] = drift.get("disposition")
                result["louvain_priority"] = drift.get("priority")
        bridge = bridge_scores.get(node_id)
        if bridge:
            result["louvain_bridge_score"] = bridge.get("bridge_score", 0.0)
            result["louvain_connected_communities"] = bridge.get("connected_communities", [])
    return analysis

def build_literature_relation_graph(
    search_id: str,
    query: str = "",
    max_nodes: int = 80,
    min_quality: float = 0.0,
    max_clusters: int = 8,
    run_louvain: bool = True,
    louvain_resolution: float | None = None,
) -> str:
    try:
        from ._literature_scoring import publication_quality_assessment
        from ._literature_search import literature_result_unique_key
        from ._project import load_search, save_search
        from ._utils import clamp_int, new_id
    except ImportError:
        from _literature_scoring import publication_quality_assessment
        from _literature_search import literature_result_unique_key
        from _project import load_search, save_search
        from _utils import clamp_int, new_id
    search = load_search(search_id)
    raw_results = [item for item in search.get("results", []) if isinstance(item, dict)]
    limit = clamp_int(max_nodes, 1, 200)
    query_text = query or str(search.get("query", ""))
    filtered = [
        item
        for item in raw_results
        if float(item.get("publication_quality_score") or publication_quality_assessment(item)["quality_score"]) >= float(min_quality or 0.0)
    ][:limit]

    seed = relation_graph_seed(search)
    nodes: dict[str, dict[str, Any]] = {}
    if seed:
        seed_node = relation_graph_node(seed, query_text, role="seed")
        nodes[seed_node["node_id"]] = seed_node
        seed_id = seed_node["node_id"]
    else:
        seed_id = "seed"
        nodes[seed_id] = {
            "node_id": seed_id,
            "role": "seed",
            "title": search.get("seed_title") or "Seed paper",
            "year": "",
            "venue": "",
            "field": "general",
            "mechanism_terms": [],
            "relevance_score": 0.0,
            "publication_quality_score": 1.0,
            "venue_quality": "",
            "journal_quartile": "",
            "citation_count": 0,
            "quality_flags": [],
        }

    result_node_ids: dict[str, str] = {}
    for result in filtered:
        node = relation_graph_node(result, query_text, role="paper")
        nodes[node["node_id"]] = node
        result_node_ids[literature_result_unique_key(result)] = node["node_id"]

    edges: list[dict[str, Any]] = []
    for result in filtered:
        node_id = result_node_ids.get(literature_result_unique_key(result))
        if not node_id:
            continue
        parent_id = result_node_ids.get(str(result.get("graph_parent_key") or "")) or seed_id
        relation = str(result.get("graph_relation") or "search_result")
        edge = relation_graph_edge(parent_id, node_id, relation, result)
        if edge:
            edges.append(edge)

    louvain_analysis = (
        run_louvain_community_analysis(
            list(nodes.values()),
            edges,
            resolution=louvain_resolution,
        )
        if run_louvain
        else {"status": "not_run", "reason": "run_louvain=False", "community_map": {}, "bridge_nodes": []}
    )
    louvain_map = louvain_analysis.get("community_map") if isinstance(louvain_analysis.get("community_map"), dict) else {}
    louvain_bridges = {
        str(bridge.get("node_id") or ""): bridge
        for bridge in louvain_analysis.get("bridge_nodes", [])
        if isinstance(bridge, dict)
    }
    drift_by_community = {
        int(item.get("community_id")): item
        for item in louvain_analysis.get("topic_drift_assessment", [])
        if isinstance(item, dict) and item.get("community_id") is not None
    }
    for node_id, node in nodes.items():
        if node_id in louvain_map:
            node["louvain_community"] = louvain_map[node_id]
            drift = drift_by_community.get(int(louvain_map[node_id]))
            if drift:
                node["louvain_community_disposition"] = drift.get("disposition")
                node["louvain_priority"] = drift.get("priority")
        if node_id in louvain_bridges:
            node["louvain_bridge_score"] = louvain_bridges[node_id].get("bridge_score", 0.0)
            node["louvain_connected_communities"] = louvain_bridges[node_id].get("connected_communities", [])

    clusters = build_mechanism_clusters(list(nodes.values()), edges, max_clusters=max_clusters)
    edge_summary = summarize_relation_edges(edges)
    edge_summary["louvain"] = {
        "status": louvain_analysis.get("status", "not_run"),
        "structural_node_count": louvain_analysis.get("structural_node_count", 0),
        "unique_edge_count": louvain_analysis.get("unique_edge_count", 0),
        "ignored_artificial_edge_count": louvain_analysis.get("ignored_artificial_edge_count", 0),
        "num_communities": louvain_analysis.get("num_communities", 0),
        "modularity": louvain_analysis.get("modularity"),
        "bridge_count": len(louvain_analysis.get("bridge_nodes", [])),
        "outlier_community_count": len(louvain_analysis.get("outlier_communities", [])),
    }
    community_summary = graph_community_summary(filtered)
    fallback_used = bool(search.get("fallback_used")) or any(edge.get("edge_type") == "artificial" for edge in edges)
    analysis_confidence = 0.65 if fallback_used else 1.0
    pagerank = compute_pagerank(list(nodes), edges)
    degree = compute_graph_degree(list(nodes), edges)
    for node_id, node in nodes.items():
        node["pagerank"] = round(pagerank.get(node_id, 0.0), 6)
        node["degree_centrality"] = round(degree.get(node_id, 0.0), 6)
        node["centrality_score"] = round(0.7 * pagerank.get(node_id, 0.0) + 0.3 * degree.get(node_id, 0.0), 6)

    ranked_nodes = sorted(
        nodes.values(),
        key=lambda item: (
            -float(item.get("centrality_score", 0.0)),
            -float(item.get("publication_quality_score", 0.0)),
            -float(item.get("relevance_score", 0.0)),
        ),
    )
    louvain_seed_recommendations = louvain_recommended_expansion_seeds(ranked_nodes, louvain_analysis)
    graph_id = new_id("relgraph")
    record = {
        "search_id": graph_id,
        "kind": "paper_relation_graph",
        "source_search_id": search_id,
        "query": query_text,
        "createdAt": time.time(),
        "node_count": len(nodes),
        "edge_count": len(edges),
        "cluster_count": len(clusters),
        "max_clusters": clamp_int(max_clusters, 1, 30),
        "fallback_used": fallback_used,
        "analysis_confidence": analysis_confidence,
        "edge_summary": edge_summary,
        "community_summary": community_summary,
        "louvain_analysis": louvain_analysis,
        "louvain_seed_recommendations": louvain_seed_recommendations,
        "nodes": ranked_nodes,
        "edges": edges,
        "clusters": clusters,
        "central_papers": [summarize_relation_node(item) for item in ranked_nodes[:10]],
        "mechanism_lineage": summarize_mechanism_lineage(clusters),
    }
    save_search({"search_id": graph_id, **record, "total_results": len(ranked_nodes), "results": ranked_nodes})
    log_event(
        "SCIENCE",
        "relation_graph_built",
        source_search_id=search_id,
        graph_id=graph_id,
        nodes=len(nodes),
        edges=len(edges),
        clusters=len(clusters),
        louvain_status=louvain_analysis.get("status", "not_run"),
        louvain_communities=louvain_analysis.get("num_communities", 0),
        louvain_modularity=louvain_analysis.get("modularity"),
    )
    response = {
        "relation_graph_id": graph_id,
        "source_search_id": search_id,
        "node_count": len(nodes),
        "edge_count": len(edges),
        "cluster_count": len(clusters),
        "max_clusters": clamp_int(max_clusters, 1, 30),
        "fallback_used": fallback_used,
        "analysis_confidence": analysis_confidence,
        "edge_summary": edge_summary,
        "community_summary": community_summary,
        "louvain_analysis": {
            "status": louvain_analysis.get("status", "not_run"),
            "reason": louvain_analysis.get("reason", ""),
            "resolution_used": louvain_analysis.get("resolution_used"),
            "structural_node_count": louvain_analysis.get("structural_node_count", 0),
            "unique_edge_count": louvain_analysis.get("unique_edge_count", 0),
            "excluded_isolate_count": louvain_analysis.get("excluded_isolate_count", 0),
            "ignored_artificial_edge_count": louvain_analysis.get("ignored_artificial_edge_count", 0),
            "num_communities": louvain_analysis.get("num_communities", 0),
            "modularity": louvain_analysis.get("modularity"),
            "has_bridges": bool(louvain_analysis.get("has_bridges")),
            "outlier_communities": [
                {
                    "community_id": item.get("community_id"),
                    "size": item.get("size"),
                    "disposition": item.get("disposition"),
                    "priority": item.get("priority"),
                }
                for item in louvain_analysis.get("outlier_communities", [])
                if isinstance(item, dict)
            ],
            "communities": [
                {
                    "community_id": item.get("community_id"),
                    "size": item.get("size"),
                    "primary_field": item.get("primary_field"),
                    "bridge_count": item.get("bridge_count"),
                }
                for item in louvain_analysis.get("communities", [])
                if isinstance(item, dict)
            ],
            "bridge_nodes": louvain_seed_recommendations,
        },
        "central_papers": record["central_papers"],
        "clusters": clusters,
        "mechanism_lineage": record["mechanism_lineage"],
        "next_step": "Use central_papers for high-trust seeds, louvain_analysis.bridge_nodes for cross-community expansion, clusters for mechanism lineage, and edges/citation_contexts for claim-citation verification.",
    }
    return json.dumps(response, ensure_ascii=False, indent=2)

def relation_graph_seed(search: dict[str, Any]) -> dict[str, Any]:
    try:
        from ._project import load_search
        from ._utils import normalize_space
    except ImportError:
        from _project import load_search
        from _utils import normalize_space
    seed_search_id = str(search.get("seed_search_id") or "")
    if seed_search_id:
        try:
            seed_search = load_search(seed_search_id)
            seed_index = int(search.get("seed_result_index") or 0)
            seed = seed_search.get("results", [])[seed_index]
            if isinstance(seed, dict):
                return seed
        except Exception:
            pass
    seed_title = normalize_space(search.get("seed_title", ""))
    if seed_title:
        return {"title": seed_title, "venue": "", "year": "", "provider": "seed_metadata"}
    return {}

def relation_graph_node(result: dict[str, Any], query: str, role: str = "paper") -> dict[str, Any]:
    try:
        from ._literature_scoring import publication_quality_assessment
        from ._literature_search import literature_result_unique_key
        from ._utils import normalize_key, numeric_value
    except ImportError:
        from _literature_scoring import publication_quality_assessment
        from _literature_search import literature_result_unique_key
        from _utils import normalize_key, numeric_value
    quality = publication_quality_assessment(result)
    terms = mechanism_terms(result, query)
    node_key = literature_result_unique_key(result)
    node_id = normalize_key(node_key)[:80]
    return {
        "node_id": node_id,
        "role": role,
        "result_index": result.get("result_index"),
        "title": result.get("title"),
        "year": result.get("year"),
        "venue": result.get("venue"),
        "field": quality["inferred_field"],
        "community": infer_literature_community(result),
        "mechanism_terms": terms,
        "mechanism_cluster_key": mechanism_cluster_key(quality["inferred_field"], terms),
        "relevance_score": result.get("relevance_score", 0.0),
        "publication_quality_score": result.get("publication_quality_score", quality["quality_score"]),
        "venue_quality": result.get("venue_quality", quality["venue_quality"]),
        "journal_quartile": result.get("journal_quartile", quality["journal_quartile"]),
        "citation_count": numeric_value(result.get("citation_count")),
        "influential_citation_count": numeric_value(result.get("influential_citation_count")),
        "quality_flags": result.get("quality_flags", quality["flags"]),
        "doi": result.get("doi"),
        "arxiv_id": result.get("arxiv_id"),
        "semantic_scholar_id": result.get("semantic_scholar_id"),
        "url": result.get("url"),
    }

def relation_graph_edge(parent_id: str, node_id: str, relation: str, result: dict[str, Any]) -> dict[str, Any]:
    try:
        from ._utils import normalize_key, scalar, trim_text
    except ImportError:
        from _utils import normalize_key, scalar, trim_text
    if node_id == parent_id:
        return {}
    normalized = normalize_key(relation)
    is_bridge = bool(result.get("graph_cross_community_bridge")) or normalized.startswith("cross_community_bridge_")
    base_relation = normalized.removeprefix("cross_community_bridge_")
    is_second_layer = base_relation.startswith("second_layer_") or normalized.startswith("cross_community_bridge_")
    base_relation = base_relation.removeprefix("second_layer_")
    is_artificial = base_relation in {"keyword_fallback", "search_result", "cross_community_search"}
    weight = {
        "reference": 1.0,
        "citation": 1.0,
        "keyword_fallback": 0.08,
        "search_result": 0.06,
        "cross_community_search": 0.12,
    }.get(base_relation, 0.4)
    if is_second_layer and not is_artificial:
        weight *= 0.65
    if is_bridge and not is_artificial:
        weight = min(1.0, weight + max(0.0, float(SCIENCE_CROSS_COMMUNITY_EDGE_BONUS)))
    if base_relation == "reference":
        source, target = parent_id, node_id
    elif base_relation == "citation":
        source, target = node_id, parent_id
    else:
        source, target = parent_id, node_id
    contexts = [trim_text(scalar(item), 260) for item in (result.get("citation_contexts") or []) if scalar(item)]
    parent_community = str(result.get("graph_parent_community") or "")
    child_community = str(result.get("graph_community") or infer_literature_community(result))
    edge = {
        "source": source,
        "target": target,
        "relation": normalized,
        "base_relation": base_relation,
        "edge_type": "artificial" if is_artificial else "citation_graph",
        "expanded_depth": 2 if is_second_layer else int(result.get("expanded_depth") or 1),
        "weight": round(weight, 4),
        "citation_contexts": contexts[:3],
        "citation_intents": result.get("citation_intents") or [],
        "is_influential": bool(result.get("edge_is_influential")),
        "parent_title": result.get("graph_parent_title", ""),
        "manual_connection": is_artificial,
    }
    if is_bridge:
        edge["is_cross_community_bridge"] = True
        edge["bridge_communities"] = str(result.get("graph_bridge_communities") or f"{parent_community}->{child_community}")
        edge["parent_community"] = parent_community
        edge["child_community"] = child_community
    return edge

def mechanism_terms(result: dict[str, Any], query: str = "", limit: int = 6) -> list[str]:
    try:
        from ._literature_search import query_terms
        from ._utils import normalize_space, scalar, unique_preserve_order
    except ImportError:
        from _literature_search import query_terms
        from _utils import normalize_space, scalar, unique_preserve_order
    text = " ".join(
        normalize_space(result.get(key, "")).lower()
        for key in ("title", "abstract", "venue")
    )
    contexts = " ".join(scalar(item).lower() for item in (result.get("citation_contexts") or []))
    text = f"{text} {contexts}"
    vocab = [
        "adaptation",
        "analysis",
        "architecture",
        "attribution",
        "causality",
        "classification",
        "control",
        "coupling",
        "decomposition",
        "degradation",
        "discovery",
        "dynamics",
        "efficiency",
        "evaluation",
        "feedback",
        "generalization",
        "heterogeneity",
        "inference",
        "interaction",
        "interface",
        "measurement",
        "mechanism",
        "model",
        "optimization",
        "prediction",
        "reconstruction",
        "response",
        "robustness",
        "scalability",
        "screening",
        "sensitivity",
        "simulation",
        "stability",
        "structure",
        "transfer",
        "uncertainty",
        "validation",
        "planning",
        "workflow",
    ]
    hits = [term for term in vocab if term in text]
    query_hits = [term for term in query_terms(query) if term in text]
    if len(hits) + len(query_hits) < limit:
        words = [
            word
            for word in re.findall(r"[a-z][a-z0-9-]{3,}", text)
            if word not in set(query_terms("")) and word not in {"paper", "study", "using", "based", "with", "from", "this", "that"}
        ]
        common = [word for word, _ in Counter(words).most_common(limit * 2)]
    else:
        common = []
    return unique_preserve_order(hits + query_hits + common)[:limit]

def mechanism_cluster_key(field: str, terms: list[str]) -> str:
    if terms:
        return f"{field}:{terms[0]}"
    return f"{field}:general"

def build_mechanism_clusters(nodes: list[dict[str, Any]], edges: list[dict[str, Any]], max_clusters: int = 8) -> list[dict[str, Any]]:
    try:
        from ._utils import normalize_key
    except ImportError:
        from _utils import normalize_key
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for node in nodes:
        if node.get("role") == "seed":
            continue
        grouped[str(node.get("mechanism_cluster_key") or "general:unknown")].append(node)
    grouped = merge_sparse_mechanism_groups(grouped, max_clusters=max_clusters)
    incoming = Counter(edge["target"] for edge in edges)
    outgoing = Counter(edge["source"] for edge in edges)
    artificial_nodes = {
        edge["target"]
        for edge in edges
        if edge.get("edge_type") == "artificial"
    } | {
        edge["source"]
        for edge in edges
        if edge.get("edge_type") == "artificial"
    }
    clusters: list[dict[str, Any]] = []
    for key, members in grouped.items():
        field, _, mechanism = key.partition(":")
        central = sorted(
            members,
            key=lambda item: (
                -(incoming[item["node_id"]] + outgoing[item["node_id"]]),
                -float(item.get("publication_quality_score", 0.0)),
                -float(item.get("relevance_score", 0.0)),
            ),
        )[:5]
        flags = sorted({flag for item in members for flag in item.get("quality_flags", [])})
        artificial_count = sum(1 for item in members if item.get("node_id") in artificial_nodes)
        clusters.append(
            {
                "cluster_id": normalize_key(key),
                "field": field or "general",
                "mechanism": mechanism or "general",
                "size": len(members),
                "merged_singletons": any(bool(item.get("merged_from_singleton")) for item in members),
                "artificial_connection_count": artificial_count,
                "connection_confidence": round(1.0 - (artificial_count / max(1, len(members))) * 0.6, 4),
                "avg_quality": round(sum(float(item.get("publication_quality_score", 0.0)) for item in members) / max(1, len(members)), 4),
                "avg_relevance": round(sum(float(item.get("relevance_score", 0.0)) for item in members) / max(1, len(members)), 4),
                "quality_flags": flags[:8],
                "representative_papers": [summarize_relation_node(item) for item in central],
            }
        )
    clusters.sort(key=lambda item: (-int(item["size"]), -float(item["avg_quality"]), item["cluster_id"]))
    return clusters

def merge_sparse_mechanism_groups(
    grouped: dict[str, list[dict[str, Any]]],
    max_clusters: int = 8,
) -> dict[str, list[dict[str, Any]]]:
    try:
        from ._utils import clamp_int
    except ImportError:
        from _utils import clamp_int
    target = clamp_int(max_clusters, 1, 30)
    if len(grouped) <= target:
        return grouped
    merged: dict[str, list[dict[str, Any]]] = {key: list(value) for key, value in grouped.items()}
    singleton_keys = [key for key, members in merged.items() if len(members) == 1]
    for key in singleton_keys:
        if len(merged) <= target:
            break
        members = merged.pop(key, [])
        if not members:
            continue
        parent_key = nearest_mechanism_parent_key(key, members[0], merged)
        for member in members:
            member["merged_from_singleton"] = key
        merged[parent_key].extend(members)

    while len(merged) > target:
        smallest_key = min(merged, key=lambda item: (len(merged[item]), item))
        members = merged.pop(smallest_key)
        if not members:
            continue
        parent_key = nearest_mechanism_parent_key(smallest_key, members[0], merged)
        for member in members:
            member["merged_from_singleton"] = smallest_key
        merged[parent_key].extend(members)
    return merged

def nearest_mechanism_parent_key(
    source_key: str,
    node: dict[str, Any],
    grouped: dict[str, list[dict[str, Any]]],
) -> str:
    field, _, _ = source_key.partition(":")
    node_terms = set(node.get("mechanism_terms") or [])
    candidates: list[tuple[float, str]] = []
    for key, members in grouped.items():
        candidate_field, _, _ = key.partition(":")
        if candidate_field != field:
            continue
        term_sets = [set(item.get("mechanism_terms") or []) for item in members]
        overlap = max((len(node_terms & terms) for terms in term_sets), default=0)
        size_bonus = min(3, len(members)) * 0.1
        candidates.append((overlap + size_bonus, key))
    if candidates:
        candidates.sort(key=lambda item: (-item[0], item[1]))
        return candidates[0][1]
    parent_key = f"{field or 'general'}:mixed"
    grouped.setdefault(parent_key, [])
    return parent_key

def compute_pagerank(node_ids: list[str], edges: list[dict[str, Any]], damping: float = 0.85, iterations: int = 30) -> dict[str, float]:
    try:
        from ._utils import unique_preserve_order
    except ImportError:
        from _utils import unique_preserve_order
    ids = unique_preserve_order(node_ids)
    if not ids:
        return {}
    outgoing: dict[str, list[tuple[str, float]]] = {node_id: [] for node_id in ids}
    for edge in edges:
        source = str(edge.get("source") or "")
        target = str(edge.get("target") or "")
        if source in outgoing and target in outgoing:
            outgoing[source].append((target, max(0.01, float(edge.get("weight") or 1.0))))
    n = len(ids)
    rank = {node_id: 1.0 / n for node_id in ids}
    base = (1.0 - damping) / n
    for _ in range(iterations):
        new_rank = {node_id: base for node_id in ids}
        dangling = sum(rank[node_id] for node_id in ids if not outgoing[node_id])
        dangling_share = damping * dangling / n
        for node_id in ids:
            new_rank[node_id] += dangling_share
        for source, targets in outgoing.items():
            total_weight = sum(weight for _, weight in targets)
            if total_weight <= 0:
                continue
            for target, weight in targets:
                new_rank[target] += damping * rank[source] * (weight / total_weight)
        rank = new_rank
    total = sum(rank.values()) or 1.0
    return {node_id: value / total for node_id, value in rank.items()}

def compute_graph_degree(node_ids: list[str], edges: list[dict[str, Any]]) -> dict[str, float]:
    try:
        from ._utils import unique_preserve_order
    except ImportError:
        from _utils import unique_preserve_order
    ids = unique_preserve_order(node_ids)
    degree = {node_id: 0.0 for node_id in ids}
    for edge in edges:
        source = str(edge.get("source") or "")
        target = str(edge.get("target") or "")
        weight = max(0.01, float(edge.get("weight") or 1.0))
        if source in degree:
            degree[source] += weight
        if target in degree:
            degree[target] += weight
    max_degree = max(degree.values(), default=0.0)
    if max_degree <= 0:
        return degree
    return {node_id: value / max_degree for node_id, value in degree.items()}

def summarize_relation_node(node: dict[str, Any]) -> dict[str, Any]:
    return {
        "node_id": node.get("node_id"),
        "title": node.get("title"),
        "year": node.get("year"),
        "venue": node.get("venue"),
        "field": node.get("field"),
        "mechanism_terms": node.get("mechanism_terms", []),
        "pagerank": node.get("pagerank"),
        "degree_centrality": node.get("degree_centrality"),
        "centrality_score": node.get("centrality_score"),
        "publication_quality_score": node.get("publication_quality_score"),
        "relevance_score": node.get("relevance_score"),
        "quality_flags": node.get("quality_flags", []),
    }

def summarize_relation_edges(edges: list[dict[str, Any]]) -> dict[str, Any]:
    by_type = Counter(str(edge.get("edge_type") or "unknown") for edge in edges)
    by_relation = Counter(str(edge.get("relation") or "unknown") for edge in edges)
    depths = Counter(str(edge.get("expanded_depth") or 1) for edge in edges)
    return {
        "total_edges": len(edges),
        "citation_graph_edges": by_type.get("citation_graph", 0),
        "artificial_edges": by_type.get("artificial", 0),
        "cross_community_bridges": sum(1 for edge in edges if edge.get("is_cross_community_bridge")),
        "by_relation": dict(sorted(by_relation.items())),
        "by_depth": dict(sorted(depths.items())),
        "fallback_weight_policy": "keyword_fallback/search_result edges are artificial and use very low PageRank weight.",
    }

def summarize_mechanism_lineage(clusters: list[dict[str, Any]]) -> list[dict[str, Any]]:
    lineage: list[dict[str, Any]] = []
    for cluster in clusters[:12]:
        representatives = cluster.get("representative_papers", [])
        lineage.append(
            {
                "mechanism": cluster.get("mechanism"),
                "field": cluster.get("field"),
                "paper_count": cluster.get("size"),
                "avg_quality": cluster.get("avg_quality"),
                "representative_titles": [item.get("title") for item in representatives[:3]],
                "interpretation": (
                    f"{cluster.get('field')} lineage centered on {cluster.get('mechanism')} "
                    f"with {cluster.get('size')} papers; inspect representative_papers before importing claims."
                ),
            }
        )
    return lineage

