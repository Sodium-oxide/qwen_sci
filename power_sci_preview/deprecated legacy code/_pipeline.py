from __future__ import annotations

from collections import Counter, defaultdict
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any
import ast
import json
import re
import time

try:
    from .config import (
        SCIENCE_DIR,
        SCIENCE_FOUNDATION_ALLOW_NEWER_FALLBACK,
        SCIENCE_FOUNDATION_AUTO_EXPAND_RUN_BUDGET,
        SCIENCE_FOUNDATION_MAX_RESULTS,
        SCIENCE_FOUNDATION_MAX_SELECTED_PER_SUBHYPOTHESIS,
        SCIENCE_FOUNDATION_RUN_QUERY_HARD_CAP,
        SCIENCE_FOUNDATION_PER_RUN_QUERY_LIMIT,
        SCIENCE_FOUNDATION_PER_SUBHYPOTHESIS_QUERY_LIMIT,
        SCIENCE_FOUNDATION_PREFERRED_YEAR_MAX,
        SCIENCE_FOUNDATION_PREFERRED_YEAR_MIN,
        SCIENCE_FOUNDATION_RETRIEVAL_ENABLED,
        FULLTEXT_AUTO_NORMALIZE_BATCH_PROJECT,
        FULLTEXT_COMMIT_BATCH_SIZE,
        FULLTEXT_NETWORK_WORKERS,
        FULLTEXT_PREPARE_BATCH_SIZE,
        SCIENCE_QUERY_OPTIMIZER_MAX_QUERIES,
        SCIENCE_DEEP_ALIGNMENT_CANDIDATE_LIMIT_MAX,
        SCIENCE_MAX_FULLTEXT_ATTEMPTS_PER_SH,
        SCIENCE_MAX_METADATA_RESULTS_PER_EVIDENCE_PATH,
        SCIENCE_MAX_METADATA_RESULTS_PER_SH,
        SCIENCE_MAX_PDF_FULLTEXT_IMPORTS_PER_RETRIEVAL,
        SCIENCE_MAX_REVIEW_FULLTEXT_PER_RETRIEVAL,
        SCIENCE_RESERVE_PROMOTION_CONSECUTIVE_FULLTEXT_FAILURE_STOP,
        SCIENCE_RETRIEVAL_ADAPTIVE_EXPANSION_ENABLED,
        SCIENCE_RETRIEVAL_EXHAUSTIVE_MODE,
        SCIENCE_SUBHYPOTHESIS_LOW_ADMISSION_REASSESSMENT_THRESHOLD,
        SCIENCE_SUBHYPOTHESIS_DIRECT_CORE_FULLTEXT_TARGET,
        SCIENCE_SUBHYPOTHESIS_NO_YIELD_STOP_ROUNDS,
        SCIENCE_SUBHYPOTHESIS_PEER_REVIEWED_FULLTEXT_TARGET,
        SCIENCE_SUBHYPOTHESIS_RETRIEVAL_BATCH_SIZE,
        SCIENCE_SUBHYPOTHESIS_RETRIEVAL_MAX_ROUNDS,
        SCIENCE_ZHIZHI_IMPORT_LLM_LIMIT,
        SCIENCE_ZHIZHI_MAX_IMPORT_TOP_K,
        SCIENCE_IMPORT_BACKGROUND_FULLTEXT_ENABLED,
        SCIENCE_IMPORT_BACKGROUND_METADATA_BUDGET,
        SCIENCE_IMPORT_POLICY_ECONOMIC_FULLTEXT_ENABLED,
        SCIENCE_IMPORT_POLICY_ECONOMIC_METADATA_BUDGET,
        SCIENCE_IMPORT_REVIEW_CONTEXT_BUDGET,
        SCIENCE_MULTIMODAL_DEFER_UNTIL_IMPORT_GATE_READY,
        SCIENCE_MULTIMODAL_RUN_INLINE_DURING_IMPORT,
    )
    from .log import log_event
except ImportError:
    from config import (
        SCIENCE_DIR,
        SCIENCE_FOUNDATION_ALLOW_NEWER_FALLBACK,
        SCIENCE_FOUNDATION_AUTO_EXPAND_RUN_BUDGET,
        SCIENCE_FOUNDATION_MAX_RESULTS,
        SCIENCE_FOUNDATION_MAX_SELECTED_PER_SUBHYPOTHESIS,
        SCIENCE_FOUNDATION_RUN_QUERY_HARD_CAP,
        SCIENCE_FOUNDATION_PER_RUN_QUERY_LIMIT,
        SCIENCE_FOUNDATION_PER_SUBHYPOTHESIS_QUERY_LIMIT,
        SCIENCE_FOUNDATION_PREFERRED_YEAR_MAX,
        SCIENCE_FOUNDATION_PREFERRED_YEAR_MIN,
        SCIENCE_FOUNDATION_RETRIEVAL_ENABLED,
        FULLTEXT_AUTO_NORMALIZE_BATCH_PROJECT,
        FULLTEXT_COMMIT_BATCH_SIZE,
        FULLTEXT_NETWORK_WORKERS,
        FULLTEXT_PREPARE_BATCH_SIZE,
        SCIENCE_QUERY_OPTIMIZER_MAX_QUERIES,
        SCIENCE_DEEP_ALIGNMENT_CANDIDATE_LIMIT_MAX,
        SCIENCE_MAX_FULLTEXT_ATTEMPTS_PER_SH,
        SCIENCE_MAX_METADATA_RESULTS_PER_EVIDENCE_PATH,
        SCIENCE_MAX_METADATA_RESULTS_PER_SH,
        SCIENCE_MAX_PDF_FULLTEXT_IMPORTS_PER_RETRIEVAL,
        SCIENCE_MAX_REVIEW_FULLTEXT_PER_RETRIEVAL,
        SCIENCE_RESERVE_PROMOTION_CONSECUTIVE_FULLTEXT_FAILURE_STOP,
        SCIENCE_RETRIEVAL_ADAPTIVE_EXPANSION_ENABLED,
        SCIENCE_RETRIEVAL_EXHAUSTIVE_MODE,
        SCIENCE_SUBHYPOTHESIS_LOW_ADMISSION_REASSESSMENT_THRESHOLD,
        SCIENCE_SUBHYPOTHESIS_DIRECT_CORE_FULLTEXT_TARGET,
        SCIENCE_SUBHYPOTHESIS_NO_YIELD_STOP_ROUNDS,
        SCIENCE_SUBHYPOTHESIS_PEER_REVIEWED_FULLTEXT_TARGET,
        SCIENCE_SUBHYPOTHESIS_RETRIEVAL_BATCH_SIZE,
        SCIENCE_SUBHYPOTHESIS_RETRIEVAL_MAX_ROUNDS,
        SCIENCE_ZHIZHI_IMPORT_LLM_LIMIT,
        SCIENCE_ZHIZHI_MAX_IMPORT_TOP_K,
        SCIENCE_IMPORT_BACKGROUND_FULLTEXT_ENABLED,
        SCIENCE_IMPORT_BACKGROUND_METADATA_BUDGET,
        SCIENCE_IMPORT_POLICY_ECONOMIC_FULLTEXT_ENABLED,
        SCIENCE_IMPORT_POLICY_ECONOMIC_METADATA_BUDGET,
        SCIENCE_IMPORT_REVIEW_CONTEXT_BUDGET,
        SCIENCE_MULTIMODAL_DEFER_UNTIL_IMPORT_GATE_READY,
        SCIENCE_MULTIMODAL_RUN_INLINE_DURING_IMPORT,
    )
    from log import log_event


def _compact_reason_key(reason: Any) -> str:
    text = str(reason or "").strip()
    if not text:
        return "UNKNOWN"
    lowered = text.lower()
    if "object" in lowered or "project-context" in lowered:
        return "OFF_OBJECT"
    if "causal edge" in lowered or "declared causal" in lowered:
        return "CAUSAL_EDGE_MISSING"
    if "evidence design" in lowered or "eligible evidence" in lowered:
        return "EVIDENCE_DESIGN_MISMATCH"
    if "layer " in lowered and "cannot carry evidence lane" in lowered:
        return "LAYER_LANE_MISMATCH"
    if "duplicate" in lowered:
        return "DUPLICATE"
    if "full text" in lowered or "fulltext" in lowered or "pdf" in lowered:
        return "FULLTEXT_NOT_ADMITTED"
    if "review" in lowered and "primary" in lowered:
        return "REVIEW_NOT_PRIMARY"
    normalized = re.sub(r"[^A-Za-z0-9_]+", "_", text.upper()).strip("_")
    return normalized[:80] or "OTHER"


def _split_reason_terms(reason: Any) -> list[str]:
    text = str(reason or "").strip()
    if not text:
        return ["UNKNOWN"]
    if ":" in text:
        text = text.split(":", 1)[1]
    parts = [
        item.strip(" .")
        for chunk in re.split(r"[;|]", text)
        for item in chunk.split(",")
        if item.strip(" .")
    ]
    return [_compact_reason_key(item) for item in parts[:12]] or [_compact_reason_key(reason)]


def _query_plan_role_priority(item: dict[str, Any]) -> int:
    target_lane = str(item.get("target_lane") or "").lower()
    role = str(item.get("evidence_path_role") or "").lower()
    query_family = str(item.get("query_family") or "").lower()
    if (
        "theoretical_framework" in target_lane
        or role in {"background_or_framework", "context_review"}
        or "background" in query_family
    ):
        return 4
    text = " ".join(
        str(item.get(key) or "").lower()
        for key in (
            "evidence_path_id",
            "evidence_path_role",
            "retrieval_layer_role",
            "target_lane",
            "query_family",
            "branch",
        )
    )
    if any(marker in text for marker in ("core_effect_path", "core_validation", "causal_validation", "predictive_validation")):
        return 0
    if any(marker in text for marker in ("adverse_or_reversal", "opposing", "rebound", "burden", "failure")):
        return 1
    if any(marker in text for marker in ("boundary_or_generalization", "boundary", "heterogeneity", "external_validation")):
        return 2
    if any(marker in text for marker in ("mechanism_discovery", "supporting_mechanism")):
        return 3
    if any(marker in text for marker in ("theoretical_framework", "background", "context_review")):
        return 4
    return 5


def _prioritize_evidence_path_query_plan(plan: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    indexed = [
        (index, dict(item))
        for index, item in enumerate(plan or [])
        if isinstance(item, dict) and str(item.get("query") or "").strip()
    ]
    indexed.sort(key=lambda pair: (_query_plan_role_priority(pair[1]), pair[0]))
    return [item for _, item in indexed]


def _query_plan_log_sample(plan: list[dict[str, Any]] | None, *, limit: int = 5) -> list[dict[str, Any]]:
    sample: list[dict[str, Any]] = []
    for item in _prioritize_evidence_path_query_plan(plan)[: max(1, int(limit))]:
        sample.append({
            "branch": str(item.get("branch") or item.get("id") or "")[:120],
            "evidence_path_id": str(item.get("evidence_path_id") or "")[:120],
            "evidence_path_role": str(item.get("evidence_path_role") or "")[:120],
            "polarity": str(item.get("evidence_path_polarity") or "")[:80],
            "target_lane": str(item.get("target_lane") or "")[:120],
            "query_pool": str(item.get("query_pool") or "")[:40],
            "candidate_budget_share": item.get("candidate_budget_share"),
            "core_evidence_capable": item.get("core_evidence_capable"),
            "direct_core_disallowed_by_object_maturity": bool(
                item.get("direct_core_disallowed_by_object_maturity")
            ),
            "object_maturity_status": str(item.get("object_maturity_status") or "")[:80],
            "component_anchor_group": [
                str(anchor)
                for anchor in (item.get("component_anchor_group") or [])
                if str(anchor).strip()
            ][:5],
            "preferred_retrieval_layers": [
                str(layer)
                for layer in (item.get("preferred_retrieval_layers") or [])
                if str(layer).strip()
            ][:4],
            "query": str(item.get("query") or "")[:220],
        })
    return sample


def _provider_execution_replan_assessment(
    strict_execution_audits: list[dict[str, Any]] | None,
    *,
    pending_query_plan: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Classify strict provider receipts at the provider-and-branch level.

    A provider lowering failure is local to a ``provider × branch`` pair.  It
    must not discard another provider's semantically conformant execution of
    the same branch, nor should it freeze the whole SH when only one retrieval
    object profile needs a new query.  This function is deliberately about
    query executability, not scientific quality: query content remains bound
    to the immutable alignment contract and is revalidated before round N+1.
    """

    audits = [
        dict(item)
        for item in (strict_execution_audits or [])
        if isinstance(item, dict)
    ]
    planned_by_branch: dict[str, dict[str, Any]] = {}
    for item in pending_query_plan or []:
        if not isinstance(item, dict):
            continue
        branch = str(item.get("branch") or item.get("id") or "").strip()
        if branch and branch not in planned_by_branch:
            planned_by_branch[branch] = dict(item)

    by_branch: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for audit in audits:
        receipt = (
            audit.get("provider_execution_receipt")
            if isinstance(audit.get("provider_execution_receipt"), dict)
            else {}
        )
        branch = str(
            audit.get("branch")
            or receipt.get("branch")
            or ""
        ).strip()
        if branch:
            by_branch[branch].append(audit)

    branch_execution: list[dict[str, Any]] = []
    branch_replan_requests: list[dict[str, Any]] = []
    provider_quarantines: list[dict[str, Any]] = []
    conformant_receipt_count = 0
    nonconformant_receipt_count = 0

    for branch in sorted(by_branch):
        branch_audits = by_branch[branch]
        conformant_providers: set[str] = set()
        failed_by_provider: dict[str, list[dict[str, Any]]] = defaultdict(list)
        missing_groups: list[list[str]] = []
        unexpected_tokens: list[str] = []
        status_counts: Counter[str] = Counter()
        planned_query = str(planned_by_branch.get(branch, {}).get("query") or "")

        for audit in branch_audits:
            receipt = (
                audit.get("provider_execution_receipt")
                if isinstance(audit.get("provider_execution_receipt"), dict)
                else {}
            )
            provider = str(
                audit.get("provider")
                or receipt.get("provider")
                or "unknown_provider"
            ).strip() or "unknown_provider"
            execution_status = str(
                audit.get("execution_status")
                or receipt.get("execution_status")
                or "UNKNOWN"
            ).strip() or "UNKNOWN"
            semantic_conformant = audit.get("semantic_conformant")
            if semantic_conformant not in {True, False}:
                semantic_conformant = receipt.get("semantic_conformant") is True
            status_counts[execution_status] += 1
            if semantic_conformant is True:
                conformant_providers.add(provider)
                conformant_receipt_count += 1
                continue

            nonconformant_receipt_count += 1
            failure = {
                "provider": provider,
                "execution_status": execution_status,
                "provider_status": str(
                    audit.get("provider_status")
                    or receipt.get("provider_status")
                    or ""
                ),
                "missing_required_anchor_groups": [
                    list(group)
                    for group in (
                        audit.get("missing_required_anchor_groups")
                        or receipt.get("missing_required_anchor_groups")
                        or []
                    )
                    if isinstance(group, (list, tuple))
                ],
                "unexpected_provider_tokens": [
                    str(value)
                    for value in (audit.get("unexpected_provider_tokens") or [])
                    if str(value).strip()
                ],
                "planned_query": str(
                    audit.get("planned_query")
                    or planned_query
                    or ""
                ),
            }
            failed_by_provider[provider].append(failure)
            missing_groups.extend(failure["missing_required_anchor_groups"])
            unexpected_tokens.extend(failure["unexpected_provider_tokens"])

        failed_providers = sorted(failed_by_provider)
        for provider in failed_providers:
            provider_quarantines.append({
                "branch": branch,
                "provider": provider,
                "failure_statuses": sorted({
                    str(item.get("execution_status") or "UNKNOWN")
                    for item in failed_by_provider[provider]
                }),
                "reason": "provider_or_branch_execution_nonconformant",
            })

        normalized_missing_groups: list[list[str]] = []
        seen_missing_groups: set[tuple[str, ...]] = set()
        for group in missing_groups:
            normalized_group = tuple(
                str(value).strip()
                for value in group
                if str(value).strip()
            )
            if normalized_group and normalized_group not in seen_missing_groups:
                seen_missing_groups.add(normalized_group)
                normalized_missing_groups.append(list(normalized_group))
        normalized_unexpected_tokens = list(dict.fromkeys(
            token for token in unexpected_tokens if token
        ))
        branch_replan_needed = bool(branch_audits and not conformant_providers)
        execution = {
            "branch": branch,
            "planned_query": planned_query or str(
                branch_audits[0].get("planned_query") or ""
            ),
            "semantic_conformant_providers": sorted(conformant_providers),
            "failed_providers": failed_providers,
            "execution_status_counts": dict(sorted(status_counts.items())),
            "missing_required_anchor_groups": normalized_missing_groups,
            "unexpected_provider_tokens": normalized_unexpected_tokens,
            "status": (
                "EXECUTED_WITH_PROVIDER_QUARANTINE"
                if conformant_providers and failed_providers
                else "EXECUTED_SEMANTICALLY_CONFORMANT"
                if conformant_providers
                else "REPLAN_PENDING"
            ),
            "replan_required": branch_replan_needed,
        }
        branch_execution.append(execution)
        if branch_replan_needed:
            branch_replan_requests.append({
                **execution,
                "failed_receipts": [
                    failure
                    for provider in failed_providers
                    for failure in failed_by_provider[provider]
                ][:8],
                "replan_policy": (
                    "replace_only_this_branch_with_a_new_contract-valid query; "
                    "do_not_repeat_the_original_query_or_mutate_scientific_scope"
                ),
            })

    conformant_branches = [
        item["branch"]
        for item in branch_execution
        if item.get("semantic_conformant_providers")
    ]
    return {
        "schema_version": "provider_execution_branch_replan_v1",
        "strict_receipt_count": len(audits),
        "semantic_conformant_receipt_count": conformant_receipt_count,
        "nonconformant_receipt_count": nonconformant_receipt_count,
        "branch_execution": branch_execution,
        "branch_replan_requests": branch_replan_requests,
        "provider_quarantines": provider_quarantines,
        "has_branch_replan_requests": bool(branch_replan_requests),
        "conformant_branch_count": len(conformant_branches),
        "conformant_branches": conformant_branches,
        "continue_with_conformant_branches": bool(conformant_branches),
        "all_audited_branches_need_replan": bool(branch_execution) and not conformant_branches,
        "policy": (
            "provider execution failures are quarantined per provider and branch; "
            "only a branch without any conformant provider receipt enters autonomous replan"
        ),
    }


def _object_maturity_log_summary(
    alignment_contract: dict[str, Any] | None,
) -> dict[str, Any]:
    contract = alignment_contract if isinstance(alignment_contract, dict) else {}
    audit = (
        contract.get("object_maturity_audit")
        if isinstance(contract.get("object_maturity_audit"), dict)
        else {}
    )
    policy = (
        contract.get("scientific_object_anchor_policy")
        if isinstance(contract.get("scientific_object_anchor_policy"), dict)
        else {}
    )
    def values(*keys: str, limit: int = 8) -> list[str]:
        output: list[str] = []
        def iter_values(raw_values: Any) -> list[Any]:
            if isinstance(raw_values, (list, tuple, set)):
                return list(raw_values)
            if raw_values in (None, "", [], {}):
                return []
            return [raw_values]
        for key in keys:
            raw_values = (
                policy.get(key)
                if key in policy
                else audit.get(key)
                if key in audit
                else contract.get(key)
                if key in contract
                else []
            )
            for value in iter_values(raw_values):
                text = str(value or "").strip()
                if text and text not in output:
                    output.append(text)
                if len(output) >= limit:
                    return output
        return output
    return {
        "object_maturity_status": str(
            contract.get("object_maturity_status")
            or audit.get("object_status")
            or ""
        ),
        "object_maturity_retrieval_mode": str(
            contract.get("object_maturity_retrieval_mode")
            or audit.get("retrieval_mode")
            or ""
        ),
        "direct_core_evidence_allowed": contract.get("direct_core_evidence_allowed"),
        "direct_object_anchor_suppressed_by_maturity": bool(
            policy.get("direct_object_anchor_suppressed_by_maturity")
        ),
        "component_evidence_anchors": values(
            "component_bridge_object_anchor_phrases",
            "object_anchors",
        ),
        "translational_bridge_anchors": values(
            "component_bridge_method_or_platform_anchor_phrases",
            "method_or_platform_anchors",
            "component_bridge_model_system_anchor_phrases",
            "model_system_anchors",
            limit=6,
        ),
        "boundary_or_safety_anchors": [],
    }


def _query_plan_log_values(plan: list[dict[str, Any]] | None, key: str) -> list[str]:
    output: list[str] = []
    for item in _prioritize_evidence_path_query_plan(plan):
        value = str(item.get(key) or "").strip()
        if value and value not in output:
            output.append(value)
    return output


def _top_counter(counter: Counter, *, limit: int = 8) -> dict[str, int]:
    return {str(key): int(value) for key, value in counter.most_common(limit)}


def _candidate_log_sample(
    candidate: dict[str, Any],
    *,
    reason: Any = "",
    max_title_chars: int = 160,
) -> dict[str, Any]:
    return {
        "result_index": candidate.get("result_index"),
        "title": str(candidate.get("title") or "")[:max_title_chars],
        "reason": str(reason or "")[:260],
        "layer": candidate.get("stratified_layer") or candidate.get("layer"),
        "query_branch": candidate.get("query_branch"),
    }


def _pool_metric(
    pool: dict[str, Any],
    funnel: dict[str, Any],
    key: str,
    default: Any = 0,
) -> Any:
    if isinstance(pool, dict) and pool.get(key) is not None:
        return pool.get(key)
    if isinstance(funnel, dict) and funnel.get(key) is not None:
        return funnel.get(key)
    return default


def _coverage_imported_full_text_count(coverage: dict[str, Any]) -> int:
    """Return the cumulative imported-full-text count used by every display.

    Evidence admission and gate eligibility are deliberately stricter counters;
    they must never overwrite the number of full texts that were actually
    acquired and imported.
    """

    imported = coverage.get("imported_full_text_count")
    if imported is not None:
        return int(imported or 0)
    return int(
        coverage.get("raw_peer_reviewed_full_text_count")
        or coverage.get("peer_reviewed_full_text_count")
        or 0
    )


def _coverage_related_full_text_count(coverage: dict[str, Any]) -> int:
    """Return unique usable full texts admitted to the broad SH corpus."""

    for key in (
        "imported_related_full_text_count",
        "imported_related_full_text",
        "corpus_related_full_text_count",
    ):
        if coverage.get(key) is not None:
            return int(coverage.get(key) or 0)
    return _coverage_imported_full_text_count(coverage)


def _coverage_admitted_peer_reviewed_full_text_count(coverage: dict[str, Any]) -> int:
    """Return SH-admitted peer-reviewed full texts before review/context caps."""

    return int(coverage.get("peer_reviewed_full_text_count") or 0)


def _coverage_gate_counting_peer_reviewed_full_text_count(
    coverage: dict[str, Any],
) -> int:
    """Return the peer-reviewed full-text count that can satisfy the gate."""

    if coverage.get("gate_counting_peer_reviewed_full_text_count") is not None:
        return int(coverage.get("gate_counting_peer_reviewed_full_text_count") or 0)
    return _coverage_admitted_peer_reviewed_full_text_count(coverage)


def _coverage_related_full_text_shortfall(
    coverage: dict[str, Any],
    *,
    target: int = 10,
) -> int:
    """Return the sole paper-count deficit used by retrieval control."""

    if coverage.get("imported_related_full_text_shortfall") is not None:
        return max(
            0,
            int(coverage.get("imported_related_full_text_shortfall") or 0),
        )
    if coverage.get("peer_reviewed_full_text_shortfall") is not None:
        return max(
            0,
            int(coverage.get("peer_reviewed_full_text_shortfall") or 0),
        )
    return max(
        0,
        int(target or 10) - _coverage_related_full_text_count(coverage),
    )


def _coverage_direct_contract_shortfall(coverage: dict[str, Any]) -> int:
    """Return 0/1 for the V3 source-bound contract-slot invariant."""

    bundle = (
        coverage.get("type_directed_evidence_bundle")
        if isinstance(coverage.get("type_directed_evidence_bundle"), dict)
        else {}
    )
    if bundle:
        return int(bundle.get("research_question_ready") is not True)
    return 1


def _candidate_funnel_lane_mismatch_seen(
    diagnostics: dict[str, Any] | None,
) -> bool:
    source = diagnostics if isinstance(diagnostics, dict) else {}
    funnel = (
        source.get("candidate_funnel")
        if isinstance(source.get("candidate_funnel"), dict)
        else {}
    )
    if int(funnel.get("detail_revalidation_lane_mismatch") or 0) > 0:
        return True
    reason_counts = funnel.get("detail_alignment_rejection_reason_counts")
    if isinstance(reason_counts, dict) and any(
        "cannot carry evidence lane" in str(key).lower()
        for key in reason_counts
    ):
        return True
    for sample in funnel.get("detail_alignment_rejection_samples") or []:
        if isinstance(sample, dict) and "cannot carry evidence lane" in str(sample.get("reason") or "").lower():
            return True
    return False


def _terminal_state_from_retrieval_context(
    *,
    base_terminal_status: str,
    coverage: dict[str, Any],
    readiness: dict[str, Any],
    diagnostics: dict[str, Any] | None,
    no_fresh_query: bool,
) -> tuple[str, str]:
    """Return a precise terminal status plus concise human stop reason."""

    base = str(base_terminal_status or "").upper()
    source = diagnostics if isinstance(diagnostics, dict) else {}
    conversion = (
        source.get("conversion")
        if isinstance(source.get("conversion"), dict)
        else {}
    )
    provider_error_text = json.dumps(
        source.get("provider_errors") or [],
        ensure_ascii=False,
        default=str,
    ).lower()
    imported_total = _coverage_imported_full_text_count(coverage)
    related_total = _coverage_related_full_text_count(coverage)
    related_shortfall = _coverage_related_full_text_shortfall(coverage)
    noncore_total = int(coverage.get("noncore_evidence_total") or 0)
    raw_component_bridge_ready = bool(
        readiness.get("component_bridge_gap_synthesis_ready")
        or readiness.get("ready_for_component_bridge_gap_synthesis")
    )
    related_target = max(
        1,
        int(
            coverage.get("imported_related_full_text_target")
            or coverage.get("corpus_related_full_text_target")
            or coverage.get("imported_full_text_target")
            or coverage.get("peer_reviewed_full_text_target")
            or 10
        ),
    )
    component_bridge_ready = bool(
        raw_component_bridge_ready
        and (
            readiness.get("release_gate_pass") is True
            or readiness.get("corpus_ready") is True
            or related_total >= related_target
        )
    )
    lane_mismatch = _candidate_funnel_lane_mismatch_seen(source)
    if base == "CONTRACT_AXIS_DEGENERATE":
        return base, "contract_axis_degenerate_rebuild_required"
    if base == "REPLAN_REQUIRED":
        return base, "provider_execution_branch_replan_unavailable"
    if base == "CALIBRATION_PLAN_MISMATCH_REFINEMENT_UNAVAILABLE":
        return base, "calibration_plan_mismatch_requires_source_grounded_llm_refinement"
    if component_bridge_ready and readiness.get("core_ready") is not True:
        return (
            "COMPONENT_BRIDGE_GAP_SYNTHESIS_READY",
            "component_bridge_corpus_ready_without_direct_core_validation",
        )
    if readiness.get("passes") is True:
        if (
            readiness.get("testable_hypothesis_ready") is True
            and readiness.get("corpus_ready") is not True
        ):
            return (
                "TESTABLE_HYPOTHESIS_READY",
                "source_bound_cross_paper_testable_hypothesis_before_portfolio_saturation",
            )
        if readiness.get("core_ready") is not True:
            return "FULLTEXT_TARGET_MET", "fulltext_target_met_without_direct_core_claim"
        return "FULLTEXT_TARGET_MET", "fulltext_target_met"
    if base == "PROVIDER_RATE_LIMITED":
        return base, "provider_rate_limited"
    if base == "RETRIEVAL_EXCEPTION_BEFORE_PROVIDER":
        reason = "edge_lanes_uninitialized" if "edge_lanes" in provider_error_text else "retrieval_exception_before_provider"
        return base, reason
    if base == "NO_PROVIDER_RESULTS" and imported_total <= 0 and related_total <= 0:
        return base, "provider_returned_no_results"
    if base == "NO_DEDUPED_CANDIDATES" and imported_total <= 0 and related_total <= 0:
        return base, "provider_results_all_duplicate_or_filtered_before_alignment"
    if no_fresh_query:
        if component_bridge_ready:
            return (
                "COMPONENT_BRIDGE_GAP_SYNTHESIS_READY",
                "component_bridge_corpus_ready_without_direct_core_validation",
            )
        if lane_mismatch and (imported_total > 0 or related_total > 0):
            return (
                "FULLTEXT_SHORTFALL_NO_FRESH_QUERY",
                "lane_mismatch_then_query_exhausted",
            )
        if related_total > 0 and (noncore_total > 0 or str(readiness.get("gap_mode") or "") == "related_corpus_shortfall"):
            return (
                "PARTIAL_RELATED_CORPUS_NO_FRESH_QUERY",
                "related_fulltext_shortfall_after_successful_import",
            )
        if imported_total > 0 or related_total > 0:
            return (
                "FULLTEXT_SHORTFALL_NO_FRESH_QUERY",
                "lane_mismatch_then_query_exhausted" if lane_mismatch else "fulltext_shortfall_after_successful_import",
            )
        return "NO_FRESH_QUERY_BRANCHES", "no_pending_fresh_query_branches"
    if component_bridge_ready:
        return (
            "COMPONENT_BRIDGE_GAP_SYNTHESIS_READY",
            "component_bridge_corpus_ready_without_direct_core_validation",
        )
    if base == "NO_NET_NEW_FULLTEXT":
        return base, "fulltext_attempts_without_net_new_admitted_fulltext"
    if related_shortfall > 0 and related_total > 0:
        return (
            "PARTIAL_RELATED_CORPUS_NO_FRESH_QUERY"
            if noncore_total > 0
            else "FULLTEXT_SHORTFALL_NO_FRESH_QUERY",
            "related_fulltext_shortfall_after_successful_import"
            if noncore_total > 0
            else "fulltext_shortfall_after_successful_import",
        )
    provider_raw = int(conversion.get("provider_raw") or 0)
    provider_dedup = int(conversion.get("provider_deduplicated") or 0)
    if provider_raw <= 0:
        return "NO_PROVIDER_RESULTS", "provider_returned_no_results"
    if provider_dedup <= 0:
        return "NO_DEDUPED_CANDIDATES", "provider_results_all_duplicate_or_filtered_before_alignment"
    return base or "EVIDENCE_SATURATED_SHORTFALL", "evidence_saturated_shortfall"


def _workflow_ready_terminal_status(readiness: dict[str, Any]) -> str:
    """Name whether readiness came from portfolio saturation or edge closure."""

    if (
        readiness.get("testable_hypothesis_ready") is True
        and readiness.get("corpus_ready") is not True
    ):
        return "TESTABLE_HYPOTHESIS_READY"
    return "FULLTEXT_TARGET_MET"


def _terminal_status_to_retrieval_status(
    terminal_status: str,
) -> str:
    return {
        "FULLTEXT_TARGET_MET": "ready_for_causal_gap_detection",
        "TESTABLE_HYPOTHESIS_READY": "ready_for_causal_gap_detection",
        "REPLAN_REQUIRED": "replan_required",
        "COMPONENT_BRIDGE_GAP_SYNTHESIS_READY": "ready_for_component_bridge_gap_synthesis",
        "PROVIDER_ACCESS_BLOCKED": "provider_access_blocked",
        "FULLTEXT_ACCESS_BLOCKED": "fulltext_access_blocked",
        "PROVIDER_RATE_LIMITED": "provider_rate_limited",
        "RETRIEVAL_EXCEPTION_BEFORE_PROVIDER": "retrieval_exception_before_provider",
        "NO_PROVIDER_RESULTS": "no_provider_results",
        "NO_DEDUPED_CANDIDATES": "no_deduped_candidates",
        "NO_NET_NEW_FULLTEXT": "no_net_new_fulltext",
        "NO_FRESH_QUERY_BRANCHES": "no_fresh_query_branches",
        "FULLTEXT_SHORTFALL_NO_FRESH_QUERY": "fulltext_shortfall_no_fresh_query",
        "PARTIAL_RELATED_CORPUS_NO_FRESH_QUERY": "partial_related_corpus_no_fresh_query",
        "NO_NEW_UNIQUE_RESULTS": "no_new_unique_results",
        "QUERY_ALIGNMENT_FAILED": "query_alignment_failed",
        "CONTRACT_AXIS_DEGENERATE": "contract_axis_degenerate",
        "CALIBRATION_PLAN_MISMATCH_REFINEMENT_UNAVAILABLE": "calibration_plan_mismatch_refinement_unavailable",
        "EVIDENCE_SATURATED_SHORTFALL": "evidence_saturated_shortfall",
    }.get(str(terminal_status or "").upper(), "evidence_saturated_shortfall")


def _retrieval_imported_record_count(retrieval: dict[str, Any]) -> int:
    """Return every successfully imported record, independent of evidence role."""

    return (
        int(retrieval.get("p0_preprint_imported") or 0)
        + int(retrieval.get("peer_reviewed_imported_records") or 0)
        + int(retrieval.get("foundational_bridge_imported_records") or 0)
    )



def direct_evidence_chain_coverage(imported_records: list[dict[str, Any]]) -> dict[str, Any]:
    """Count only direct, CORE, lane-specific evidence.

    Reviews, L1 bridges, and a generic ``mixed_theory_and_experiment`` label
    may describe both sides of a field, but they cannot silently fill both
    legacy primary slots.  The design/causal-role coverage is reported on a
    separate axis: an observational discovery record remains visible, while
    only causal identification or validation can fill the validation role.
    """
    theory_ids: list[str] = []
    experimental_ids: list[str] = []
    mechanism_discovery_ids: list[str] = []
    causal_validation_or_identification_ids: list[str] = []
    observed_kinds: set[str] = set()
    observed_lanes: set[str] = set()
    for item in imported_records:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("evidence_kind") or "")
        lane = str(item.get("evidence_lane") or "")
        if kind:
            observed_kinds.add(kind)
        if lane:
            observed_lanes.add(lane)
        if item.get("core_eligible") is not True or str(item.get("layer") or "") == "L1_milestone":
            continue
        genre = item.get("paper_genre") if isinstance(item.get("paper_genre"), dict) else {}
        paper_id = str(item.get("paper_id") or item.get("title") or "")
        alignment = (
            item.get("alignment_assessment")
            if isinstance(item.get("alignment_assessment"), dict)
            else {}
        )
        causal_role = str(
            item.get("causal_role")
            or alignment.get("causal_role")
            or "unclassified"
        )
        if (
            kind == "theoretical_framework"
            and genre.get("direct_theoretical_evidence") is True
            and not genre.get("is_review")
        ):
            theory_ids.append(paper_id)
        if (
            kind == "experimental_evidence"
            and genre.get("direct_experimental_evidence") is True
            and not genre.get("is_review")
        ):
            experimental_ids.append(paper_id)
        if causal_role in {
            "association",
            "mechanism_discovery",
            "causal_identification",
            "causal_validation",
        }:
            mechanism_discovery_ids.append(paper_id)
        if causal_role in {"causal_identification", "causal_validation"}:
            causal_validation_or_identification_ids.append(paper_id)
    mechanism_discovery_ids = list(dict.fromkeys(mechanism_discovery_ids))
    causal_validation_or_identification_ids = list(dict.fromkeys(causal_validation_or_identification_ids))
    return {
        "theoretical_framework": bool(theory_ids),
        "experimental_evidence": bool(experimental_ids),
        "direct_theory_paper_ids": list(dict.fromkeys(theory_ids)),
        "direct_experimental_or_observational_paper_ids": list(dict.fromkeys(experimental_ids)),
        "mechanism_discovery": bool(mechanism_discovery_ids),
        "causal_validation_or_identification": bool(causal_validation_or_identification_ids),
        "mechanism_discovery_paper_ids": mechanism_discovery_ids,
        "causal_validation_or_identification_paper_ids": causal_validation_or_identification_ids,
        "independent_direct_evidence_paper_ids": list(dict.fromkeys(
            [*mechanism_discovery_ids, *causal_validation_or_identification_ids]
        )),
        "observed_evidence_kinds": sorted(observed_kinds),
        "observed_causal_edge_lanes": sorted(observed_lanes),
        "mixed_background_cannot_fill_both_slots": True,
        "foundational_bridge_cannot_fill_primary_slots": True,
    }


def create_science_pipeline_tasks(project_id: str) -> str:
    try:
        from ._models import PHASES
        from ._project import decompose_research_objective, load_project, save_project
        from ._utils import extract_task_id
    except ImportError:
        from _models import PHASES
        from _project import decompose_research_objective, load_project, save_project
        from _utils import extract_task_id
    project = load_project(project_id)
    if not project.get("sub_hypotheses"):
        decompose_research_objective(project_id, use_llm=False)
        project = load_project(project_id)
    try:
        from .task_system import create_task
    except ImportError:
        from task_system import create_task

    task_ids: list[str] = []
    previous: list[str] = []
    for index, phase in enumerate(PHASES):
        agents = agents_for_phase(phase)
        description = (
            f"Science project: {project['title']}\n"
            f"Domain: {project['domain']}\n"
            f"Objective: {project['objective']}\n"
            f"Phase: {phase}\n"
            f"Responsible science agents: {', '.join(agents)}\n"
            "Deliverable must be structured JSON and include evidence, acceptance criteria, and risks."
        )
        rendered = create_task(
            subject=f"Science phase {index + 1}: {phase}",
            description=description,
            blockedBy=previous,
        )
        task_id = extract_task_id(rendered)
        if task_id:
            task_ids.append(task_id)
            previous = [task_id]
    project["pipeline_tasks"] = task_ids
    project["updatedAt"] = time.time()
    save_project(project)
    log_event("SCIENCE", "pipeline_tasks_created", project_id=project_id, count=len(task_ids))
    return json.dumps({"project_id": project_id, "task_ids": task_ids}, ensure_ascii=False, indent=2)

def create_science_delegation_tasks(
    project_id: str,
    objective: str = "",
    subspace_map_id: str = "",
    selected_subfields: list[str] | None = None,
    focus_branches: list[str] | None = None,
    max_branch_tasks: int = 6,
) -> str:
    """Create a subagent-friendly DAG for long science workflows."""
    project = load_project(project_id)
    try:
        from .task_system import create_task
    except ImportError:
        from task_system import create_task
    plan_id = new_id("sdeleg")
    artifact_dir = SCIENCE_DIR / "delegation" / plan_id
    artifact_dir.mkdir(parents=True, exist_ok=True)
    branches = science_delegation_branch_plan(
        project,
        subspace_map_id=subspace_map_id,
        selected_subfields=selected_subfields,
        focus_branches=focus_branches,
        max_branch_tasks=max_branch_tasks,
    )
    if not branches:
        raise ValueError("No delegation branches could be built; provide focus_branches or a subspace_map_id.")
    providers = default_literature_providers(domain=str(project.get("domain", "")), query=str(project.get("objective", "")))
    branch_task_ids: list[str] = []
    branch_tasks: list[dict[str, Any]] = []
    for index, branch in enumerate(branches, 1):
        artifact_path = science_delegation_artifact_relpath(plan_id, index, str(branch.get("branch") or branch.get("name") or "branch"))
        description = science_branch_scout_description(project, objective=objective, branch=branch, artifact_path=artifact_path, providers=providers)
        rendered = create_task(subject=f"Science scout {index}: {branch.get('name') or branch.get('branch')}", description=description, blockedBy=[])
        task_id = extract_task_id(rendered)
        if task_id:
            branch_task_ids.append(task_id)
            branch_tasks.append({"task_id": task_id, "branch": branch.get("branch"), "name": branch.get("name"), "query": branch.get("query"), "artifact_path": artifact_path})
    synthesis_description = science_synthesis_gate_description(project, objective=objective, plan_id=plan_id, branch_tasks=branch_tasks)
    synthesis_rendered = create_task(subject=f"Science synthesis gate: {project.get('title', project_id)}", description=synthesis_description, blockedBy=branch_task_ids)
    synthesis_task_id = extract_task_id(synthesis_rendered)
    tanxi_rendered = create_task(
        subject=f"TanXi gap ranking after delegation: {project.get('title', project_id)}",
        description=(f"Science delegation plan: {plan_id}\nProject: {project.get('title', '')} ({project_id})\nDomain: {project.get('domain', '')}\nWait until the synthesis gate confirms lead-side PaperGraph imports are complete. Then run build_knowledge_map, run_tanxi_gap_exploration, and produce a compact ranked-gap report."),
        blockedBy=[synthesis_task_id] if synthesis_task_id else branch_task_ids,
    )
    tanxi_task_id = extract_task_id(tanxi_rendered)
    mingli_rendered = create_task(
        subject=f"MingLi hypothesis evolution after delegation: {project.get('title', project_id)}",
        description=(f"Science delegation plan: {plan_id}\nProject: {project.get('title', '')} ({project_id})\nAfter TanXi completes, run run_mingli_hypothesis_evolution on the validated top gaps."),
        blockedBy=[tanxi_task_id] if tanxi_task_id else [],
    )
    mingli_task_id = extract_task_id(mingli_rendered)
    plan = {
        "delegation_plan_id": plan_id, "project_id": project_id, "objective": objective, "createdAt": time.time(),
        "policy": {"parallel_work": "branch scouts retrieve and judge evidence independently", "shared_state": "lead/synthesis gate performs PaperGraph imports serially after reviewing artifacts"},
        "artifact_dir": str(artifact_dir), "providers": providers, "branch_tasks": branch_tasks,
        "synthesis_task_id": synthesis_task_id, "tanxi_task_id": tanxi_task_id, "mingli_task_id": mingli_task_id,
        "next_step": "Let scouts complete branch artifacts, then have the synthesis gate choose import candidates.",
    }
    project.setdefault("delegation_plans", []).append(plan)
    project.setdefault("pipeline_tasks", [])
    project["pipeline_tasks"] = unique_preserve_order(
        list(project.get("pipeline_tasks", [])) + branch_task_ids + [tid for tid in (synthesis_task_id, tanxi_task_id, mingli_task_id) if tid]
    )
    project["updatedAt"] = time.time()
    save_project(project)
    log_event("SCIENCE", "delegation_tasks_created", project_id=project_id, plan_id=plan_id, branches=len(branch_tasks))
    return json.dumps(plan, ensure_ascii=False, indent=2)

def science_delegation_branch_plan(
    project: dict[str, Any],
    *,
    subspace_map_id: str = "",
    selected_subfields: list[str] | None = None,
    focus_branches: list[str] | None = None,
    max_branch_tasks: int = 6,
) -> list[dict[str, Any]]:
    try:
        from ._literature_scoring import slug_label
        from ._project import load_subspace_map, query_plan_from_subspace_map
        from ._utils import clamp_int, normalize_space, string_list
    except ImportError:
        from _literature_scoring import slug_label
        from _project import load_subspace_map, query_plan_from_subspace_map
        from _utils import clamp_int, normalize_space, string_list
    limit = clamp_int(max_branch_tasks, 1, 20)
    if subspace_map_id:
        subspace_map = load_subspace_map(subspace_map_id)
        return query_plan_from_subspace_map(subspace_map, selected_subfields=selected_subfields or focus_branches)[:limit]
    branches: list[dict[str, Any]] = []
    for raw in focus_branches or []:
        label = normalize_space(str(raw))
        if not label:
            continue
        branches.append(
            {
                "branch": slug_label(label),
                "name": label,
                "query": label,
                "quota": 2,
                "estimated_density": "unknown",
                "strategic_importance": 7,
                "search_strategy": "user_focus_branch",
                "custom": True,
            }
        )
    if branches:
        return branches[:limit]
    knowledge_map = project.get("knowledge_map") if isinstance(project.get("knowledge_map"), dict) else {}
    scenarios = string_list(knowledge_map.get("main_scenarios"))[:limit]
    if scenarios:
        return [
            {
                "branch": slug_label(scenario),
                "name": scenario,
                "query": normalize_space(f"{project.get('domain', '')} {scenario}"),
                "quota": 2,
                "estimated_density": "project_known",
                "strategic_importance": 6,
                "search_strategy": "project_scenario",
            }
            for scenario in scenarios
            if scenario
        ][:limit]
    domain = normalize_space(str(project.get("domain") or project.get("title") or "science project"))
    objective = normalize_space(str(project.get("objective") or "knowledge gap discovery"))
    return [
        {
            "branch": slug_label(domain),
            "name": domain,
            "query": normalize_space(f"{domain} {objective}"),
            "quota": 3,
            "estimated_density": "unknown",
            "strategic_importance": 7,
            "search_strategy": "fallback_domain",
        }
    ]

def science_delegation_artifact_relpath(plan_id: str, index: int, branch: str) -> str:
    try:
        from ._literature_scoring import slug_label
    except ImportError:
        from _literature_scoring import slug_label
    safe_branch = slug_label(branch) or f"branch_{index}"
    return str(Path("qwen-ai-scientist") / "v8" / ".science" / "delegation" / plan_id / f"{index:02d}_{safe_branch}.json")

def science_branch_scout_description(
    project: dict[str, Any],
    *,
    objective: str,
    branch: dict[str, Any],
    artifact_path: str,
    providers: list[str],
) -> str:
    try:
        from ._gap_detection import build_knowledge_map, detect_knowledge_gaps
        from ._literature_graph import expand_literature_graph
        from ._literature_import import import_literature_search_result, import_papergraph_record
        from ._literature_search import search_literature_stratified, select_literature_result
    except ImportError:
        from _gap_detection import build_knowledge_map, detect_knowledge_gaps
        from _literature_graph import expand_literature_graph
        from _literature_import import import_literature_search_result, import_papergraph_record
        from _literature_search import search_literature_stratified, select_literature_result
    branch_name = str(branch.get("name") or branch.get("branch") or "")
    branch_query = str(branch.get("query") or branch_name)
    return (
        f"Role: ZhiZhi branch scout for a delegated AI-for-science workflow.\n"
        f"Project: {project.get('title', '')} ({project.get('project_id', '')})\n"
        f"Domain: {project.get('domain', '')}\n"
        f"Objective: {objective or project.get('objective', '')}\n"
        f"Branch: {branch_name}\n"
        f"Branch query: {branch_query}\n"
        f"Suggested providers: {', '.join(providers)}\n\n"
        "Important shared-state rule: do NOT call import_literature_search_result, import_papergraph_record, "
        "run_zhizhi_subhypothesis_analysis, run_autogen_groupchat, build_knowledge_map, or detect_knowledge_gaps. "
        "Those mutate the shared science project. "
        "Your job is retrieval scouting only.\n\n"
        "Steps:\n"
        "1. Run search_literature_stratified with this branch query, modest max_results (8-15), the suggested providers, "
        "and domain from above.\n"
        "2. Inspect/select the top 3-5 candidates using select_literature_result or cached result summaries.\n"
        "3. Optionally run expand_literature_graph only for the best seed if it has a Semantic Scholar/DOI/arXiv id.\n"
        f"4. Write a compact JSON artifact to `{artifact_path}` with keys: branch, query, search_ids, recommended_imports "
        "(search_id/result_index/title/why), coverage_blind_spots, quality_risks, and scout_summary.\n"
        "5. Complete the task with a short summary and artifact path.\n"
    )

def science_synthesis_gate_description(
    project: dict[str, Any],
    *,
    objective: str,
    plan_id: str,
    branch_tasks: list[dict[str, Any]],
) -> str:
    try:
        from ._gap_detection import build_knowledge_map
        from ._literature_import import import_literature_search_result
    except ImportError:
        from _gap_detection import build_knowledge_map
        from _literature_import import import_literature_search_result
    artifact_paths = [str(item.get("artifact_path", "")) for item in branch_tasks if item.get("artifact_path")]
    return (
        "Role: lead-side synthesis gate for delegated science retrieval.\n"
        f"Delegation plan: {plan_id}\n"
        f"Project: {project.get('title', '')} ({project.get('project_id', '')})\n"
        f"Domain: {project.get('domain', '')}\n"
        f"Objective: {objective or project.get('objective', '')}\n\n"
        "Read the branch scout artifacts:\n"
        + "\n".join(f"- {path}" for path in artifact_paths)
        + "\n\n"
        "Synthesize a deduplicated import plan. The final shared-state mutation should be done serially by the lead in the main workspace: "
        "for each approved candidate, call import_literature_search_result(project_id, search_id, result_index), then build_knowledge_map. "
        "If you are running in an isolated worktree, do not assume project JSON changes landed in the main workspace.\n\n"
        "Deliverable JSON keys: approved_imports, rejected_candidates, missing_branches, recommended_lead_commands, risks. "
        "Keep the output compact enough that downstream TanXi does not inherit giant raw retrieval dumps.\n"
    )

def export_research_plan(project_id: str) -> str:
    try:
        from ._project import load_project
    except ImportError:
        from _project import load_project
    project = load_project(project_id)
    gaps = project.get("knowledge_gaps", [])
    hypotheses = project.get("hypotheses", [])
    reports = project.get("mechanism_reports", [])
    lines = [
        f"Project: {project.get('title', '')}",
        f"Domain: {project.get('domain', '')}",
        f"Objective: {project.get('objective', '')}",
        f"Strategic Need: {project.get('strategic_need', '')}",
        "",
        "Knowledge Gaps:",
    ]
    for gap in gaps:
        lines.append(f"- {gap.get('gap_id')}: [{gap.get('gap_type')}] {gap.get('description')}")
    lines.extend(["", "Hypotheses:"])
    for hypothesis in hypotheses:
        lines.append(f"- {hypothesis.get('hypothesis_id')}: {hypothesis.get('statement')}")
        lines.append(f"  Mechanism: {hypothesis.get('mechanism')}")
        lines.append(f"  Test Plan: {hypothesis.get('test_plan')}")
    lines.extend(["", "Mechanism Fidelity Reports:"])
    for report in reports:
        lines.append(f"- {report.get('report_id')}: {report.get('overall_verdict')}")
    lines.extend(["", "Pipeline Tasks:"])
    for task_id in project.get("pipeline_tasks", []):
        lines.append(f"- {task_id}")
    return "\n".join(lines).strip() + "\n"

def assess_novelty(
    project_id: str,
    gap: dict[str, Any] | str,
    dimensions: list[str] | None = None,
) -> str:
    try:
        from ._gap_detection import assess_gap_dict, parse_gap_input
        from ._project import load_project, save_project
    except ImportError:
        from _gap_detection import assess_gap_dict, parse_gap_input
        from _project import load_project, save_project
    project = load_project(project_id)
    gap_dict = parse_gap_input(gap)
    assessment = assess_gap_dict(project, gap_dict, dimensions=dimensions)
    project.setdefault("novelty_assessments", []).append(assessment)
    project["updatedAt"] = time.time()
    save_project(project)
    return json.dumps(assessment, ensure_ascii=False, indent=2)

def verify_uniqueness(
    project_id: str,
    idea: str,
    precision: str = "high",
    live_search: bool = False,
    providers: list[str] | None = None,
    *,
    project_snapshot: dict[str, Any] | None = None,
    persist: bool = True,
) -> str:
    """Check novelty against one project snapshot.

    Standalone callers retain the persisted audit trail by default.  A MingLi
    finalization already owns a loaded project object, however, and must not
    allow this nested helper to save an intermediate state version.  Doing so
    makes the outer finalization stale by construction.
    """
    try:
        from ._gap_detection import local_idea_overlap, summarize_uniqueness_live_search
        from ._literature_search import search_literature
        from ._project import default_literature_providers, load_project, save_project
    except ImportError:
        from _gap_detection import local_idea_overlap, summarize_uniqueness_live_search
        from _literature_search import search_literature
        from _project import default_literature_providers, load_project, save_project
    project = project_snapshot if isinstance(project_snapshot, dict) else load_project(project_id)
    local_matches = local_idea_overlap(project, idea)
    live_result: dict[str, Any] = {}
    if live_search:
        try:
            live_result = json.loads(search_literature(idea, providers=providers or default_literature_providers(query=idea), max_results=5))
        except Exception as exc:
            live_result = {"status": "error", "error": str(exc)}
    threshold = 0.45 if precision == "high" else 0.6
    strongest = local_matches[0]["overlap_score"] if local_matches else 0.0
    verdict = "likely_unique" if strongest < threshold else "overlap_risk"
    result = {
        "idea": idea,
        "precision": precision,
        "verdict": verdict,
        "strongest_local_overlap": strongest,
        "local_matches": local_matches[:8],
        "live_search": summarize_uniqueness_live_search(live_result) if live_result else {"used": False},
        "next_step": "If verdict is overlap_risk, refine the idea or inspect matched papers before claiming novelty.",
    }
    if persist:
        project.setdefault("uniqueness_checks", []).append(result)
        project["updatedAt"] = time.time()
        save_project(project)
    return json.dumps(result, ensure_ascii=False, indent=2)


def _promote_subhypothesis_evidence_reserve(
    project_id: str,
    sub_hypothesis_id: str,
    *,
    alignment_contract: dict[str, Any],
    limit: int,
    min_retry_age_seconds: float = 0.0,
) -> dict[str, Any]:
    """Attempt existing aligned candidates before spending another search."""

    try:
        from ._literature_import import assess_full_text_acquisition, import_literature_search_result
        from ._project import load_project, save_project
        from ._research_alignment import evidence_kind_from_branch
    except ImportError:
        from _literature_import import assess_full_text_acquisition, import_literature_search_result
        from _project import load_project, save_project
        from _research_alignment import evidence_kind_from_branch
    project = load_project(project_id)
    reserve_root = project.get("subhypothesis_evidence_reserve")
    reserve_root = reserve_root if isinstance(reserve_root, dict) else {}
    reserve = reserve_root.get(sub_hypothesis_id)
    reserve = reserve if isinstance(reserve, dict) else {}
    explicit_candidate_pool = [
        dict(item)
        for item in (reserve.get("candidates") or [])
        if isinstance(item, dict)
        and str(item.get("reserve_status") or "")
        not in {
            "FULLTEXT_PROMOTED_AND_READMITTED",
            "POST_FULLTEXT_ALIGNMENT_REJECTED",
            "POST_FULLTEXT_DEMOTED_TO_AUXILIARY",
            "LEXICAL_ALIGNMENT_CALIBRATION_REQUIRED",
        }
    ]
    skipped_terminal_fulltext_failures = [
        dict(item)
        for item in explicit_candidate_pool
        if _terminal_fulltext_failure_class(item.get("full_text_failure_class"))
    ]
    explicit_candidates = [
        item
        for item in explicit_candidate_pool
        if not _terminal_fulltext_failure_class(item.get("full_text_failure_class"))
    ]
    explicit_candidate_keys = {
        key
        for item in explicit_candidates
        if (key := _reserve_candidate_identity_key(item))
    }
    project_metadata_candidates, project_metadata_audit = (
        _project_metadata_only_fulltext_retry_candidates(
            project,
            sub_hypothesis_id,
            existing_candidate_keys=explicit_candidate_keys,
        )
    )
    if project_metadata_candidates:
        log_event(
            "SCIENCE",
            "subhypothesis_project_metadata_fulltext_retry_candidates_collected",
            project_id=project_id,
            sub_hypothesis_id=sub_hypothesis_id,
            candidates=len(project_metadata_candidates),
            skipped=project_metadata_audit.get("skipped"),
        )
    candidates: list[dict[str, Any]] = []
    skipped_lexical_alignment_candidates: list[dict[str, Any]] = []
    explicit_lexical_blocks: dict[str, dict[str, Any]] = {}
    seen_candidate_keys: set[str] = set()
    for reserve_source, source_candidates in (
        ("explicit_reserve", explicit_candidates),
        ("project_papergraph_metadata_only", project_metadata_candidates),
    ):
        for source_candidate in source_candidates:
            lexical_status = reserve_candidate_lexical_alignment_status(
                source_candidate,
                alignment_contract,
            )
            key = _reserve_candidate_identity_key(source_candidate)
            if lexical_status.get("requires_calibration") is True:
                sample = {
                    "search_id": str(source_candidate.get("search_id") or ""),
                    "result_index": int(source_candidate.get("result_index") or 0),
                    "title": str(source_candidate.get("title") or "")[:200],
                    "reserve_source": reserve_source,
                    "lexical_alignment_status": str(lexical_status.get("status") or ""),
                    "reason": str(lexical_status.get("reason") or ""),
                }
                skipped_lexical_alignment_candidates.append(sample)
                if reserve_source == "explicit_reserve" and key:
                    explicit_lexical_blocks[key] = sample
                continue
            fallback_key = f"position:{len(candidates)}"
            dedupe_key = key or fallback_key
            if dedupe_key in seen_candidate_keys:
                continue
            seen_candidate_keys.add(dedupe_key)
            item = dict(source_candidate)
            item["_reserve_candidate_key"] = dedupe_key
            candidates.append(item)
    if explicit_lexical_blocks:
        updated_reserve_items: list[dict[str, Any]] = []
        reserve_changed = False
        for raw_candidate in reserve.get("candidates") or []:
            if not isinstance(raw_candidate, dict):
                continue
            current = dict(raw_candidate)
            block = explicit_lexical_blocks.get(_reserve_candidate_identity_key(current))
            if block is not None:
                current["reserve_status"] = "LEXICAL_ALIGNMENT_CALIBRATION_REQUIRED"
                current["lexical_alignment_status"] = block["lexical_alignment_status"]
                current["fulltext_promotion_blocked_reason"] = block["reason"]
                current["fulltext_promotion_blocked_at"] = time.time()
                reserve_changed = True
            updated_reserve_items.append(current)
        if reserve_changed:
            reserve["candidates"] = updated_reserve_items
            reserve["candidate_count"] = len(updated_reserve_items)
            reserve["updatedAt"] = time.time()
            reserve_root[sub_hypothesis_id] = reserve
            project["subhypothesis_evidence_reserve"] = reserve_root
            project["updatedAt"] = time.time()
            save_project(project)
    candidate_pool_total = len(candidates)
    skipped_recent_attempts: list[dict[str, Any]] = []
    if float(min_retry_age_seconds or 0.0) > 0:
        now = time.time()
        retry_age = max(0.0, float(min_retry_age_seconds or 0.0))
        filtered_candidates: list[dict[str, Any]] = []
        for candidate in candidates:
            last_attempt_at = float(candidate.get("last_promotion_at") or 0.0)
            if (
                last_attempt_at > 0
                and int(candidate.get("promotion_attempts") or 0) > 0
                and now - last_attempt_at < retry_age
            ):
                skipped_recent_attempts.append(
                    {
                        "search_id": str(candidate.get("search_id") or ""),
                        "result_index": int(candidate.get("result_index") or 0),
                        "title": str(candidate.get("title") or "")[:200],
                        "reserve_status": str(candidate.get("reserve_status") or ""),
                        "age_seconds": round(max(0.0, now - last_attempt_at), 3),
                        "min_retry_age_seconds": retry_age,
                    }
                )
                continue
            filtered_candidates.append(candidate)
        candidates = filtered_candidates
    # Prefer candidates for which a full-text discovery signal already exists,
    # followed by metadata-only records that can be retried through the normal
    # DOI/OpenAlex/S2/landing-page resolver.
    candidates.sort(
        key=lambda item: (
            0 if item.get("full_text_discovery_signal") else 1,
            0 if str(item.get("reserve_source") or "") == "project_papergraph_metadata_only" else 1,
            0 if item.get("paper_id") else 1,
            int(item.get("promotion_attempts") or 0),
            -safe_numeric_relevance(item.get("relevance_score")),
            str(item.get("title") or ""),
        )
    )
    promotion_limit = max(0, int(limit or 0))
    limited_candidates = candidates[:promotion_limit]
    fail_stop_threshold = _reserve_promotion_fail_stop_threshold()
    consecutive_no_oa_or_auth_failures = 0
    reserve_promotion_stopped_reason = ""
    attempts: list[dict[str, Any]] = []
    promoted = 0
    for candidate in limited_candidates:
        search_id = str(candidate.get("search_id") or "").strip()
        if not search_id:
            attempts.append({
                "title": str(candidate.get("title") or "")[:200],
                "status": "missing_search_provenance",
            })
            consecutive_no_oa_or_auth_failures = 0
            continue
        try:
            imported = json.loads(
                import_literature_search_result(
                    project_id,
                    search_id,
                    int(candidate.get("result_index") or 0),
                    use_llm=False,
                    stratified_layer_override=str(candidate.get("stratified_layer") or "L4_regular"),
                    query_branch_override=sub_hypothesis_id,
                    alignment_contract=alignment_contract,
                    evidence_kind_override=str(
                        candidate.get("evidence_kind")
                        or evidence_kind_from_branch(str(candidate.get("query_branch") or ""))
                    ),
                )
            )
            status = str(imported.get("status") or "")
            write_succeeded = bool(
                status == "imported"
                or (status == "duplicate" and imported.get("existing_record_updated") is True)
            )
            record = (
                imported.get("record")
                if isinstance(imported.get("record"), dict)
                else imported.get("existing_record")
                if isinstance(imported.get("existing_record"), dict)
                else {}
            )
            full_text = assess_full_text_acquisition(record)
            alignment = (
                record.get("alignment_assessment")
                if isinstance(record.get("alignment_assessment"), dict)
                else {}
            )
            bindings = (
                record.get("subhypothesis_bindings")
                if isinstance(record.get("subhypothesis_bindings"), list)
                else []
            )
            bound_alignment = next(
                (
                    item.get("alignment_assessment")
                    for item in bindings
                    if isinstance(item, dict)
                    and str(item.get("sub_hypothesis_id") or "").upper()
                    == str(sub_hypothesis_id or "").upper()
                    and isinstance(item.get("alignment_assessment"), dict)
                ),
                None,
            )
            if isinstance(bound_alignment, dict):
                alignment = bound_alignment
            full_text_resolution_status = str(full_text.get("full_text_resolution_status") or "")
            foundation = (
                record.get("foundational_bridge_assessment")
                if isinstance(record.get("foundational_bridge_assessment"), dict)
                else {}
            )
            aligned_after_fulltext = bool(
                alignment.get("import_eligible")
                or alignment.get("core_eligible")
                or foundation.get("bridge_eligible")
            )
            did_promote = bool(
                write_succeeded
                and full_text.get("full_text_available") is True
                and aligned_after_fulltext
            )
            promoted += int(did_promote)
            post_fulltext = (
                imported.get("post_fulltext_admission")
                if isinstance(imported.get("post_fulltext_admission"), dict)
                else {}
            )
            attempts.append({
                "search_id": search_id,
                "result_index": int(candidate.get("result_index") or 0),
                "title": str(candidate.get("title") or "")[:200],
                "reserve_source": str(candidate.get("reserve_source") or "explicit_reserve"),
                "full_text_failure_class_before": str(candidate.get("full_text_failure_class") or ""),
                "full_text_resolution_status_before": str(candidate.get("full_text_resolution_status") or ""),
                "full_text_retry_signal": str(candidate.get("full_text_retry_signal") or ""),
                "status": status,
                "promoted": did_promote,
                "existing_record_updated": bool(imported.get("existing_record_updated")),
                "full_text_available": bool(full_text.get("full_text_available")),
                "full_text_excerpt_chars": int(full_text.get("full_text_excerpt_chars") or 0),
                "full_text_failure_class_after": str(full_text.get("full_text_failure_class") or ""),
                "full_text_resolution_status_after": full_text_resolution_status,
                "aligned_after_fulltext": aligned_after_fulltext,
                "post_fulltext_status": str(post_fulltext.get("status") or ""),
                "assigned_layer": str(
                    post_fulltext.get("assigned_layer")
                    or candidate.get("stratified_layer")
                    or ""
                ),
            })
        except Exception as exc:
            attempts.append({
                "search_id": search_id,
                "result_index": int(candidate.get("result_index") or 0),
                "title": str(candidate.get("title") or "")[:200],
                "reserve_source": str(candidate.get("reserve_source") or "explicit_reserve"),
                "full_text_failure_class_before": str(candidate.get("full_text_failure_class") or ""),
                "full_text_resolution_status_before": str(candidate.get("full_text_resolution_status") or ""),
                "full_text_retry_signal": str(candidate.get("full_text_retry_signal") or ""),
                "status": "error",
                "error": str(exc)[:400],
            })
        latest_attempt = attempts[-1] if attempts else {}
        if _reserve_fulltext_failure_counts_toward_fail_stop(latest_attempt):
            consecutive_no_oa_or_auth_failures += 1
        else:
            consecutive_no_oa_or_auth_failures = 0
        if (
            fail_stop_threshold > 0
            and consecutive_no_oa_or_auth_failures >= fail_stop_threshold
        ):
            reserve_promotion_stopped_reason = _RESERVE_PROMOTION_FAIL_STOP_REASON
            break
    skipped_after_fail_stop = (
        max(0, len(limited_candidates) - len(attempts))
        if reserve_promotion_stopped_reason
        else 0
    )
    attempted_by_key = {
        (
            str(item.get("search_id") or ""),
            int(item.get("result_index") or 0),
        ): item
        for item in attempts
        if str(item.get("search_id") or "")
    }
    if attempted_by_key:
        latest_project = load_project(project_id)
        latest_root = latest_project.get("subhypothesis_evidence_reserve")
        latest_root = latest_root if isinstance(latest_root, dict) else {}
        latest_reserve = latest_root.get(sub_hypothesis_id)
        latest_reserve = latest_reserve if isinstance(latest_reserve, dict) else {}
        latest_items = [
            dict(item)
            for item in (latest_reserve.get("candidates") or [])
            if isinstance(item, dict)
        ]
        latest_item_keys = {
            key
            for item in latest_items
            if (key := _reserve_candidate_identity_key(item))
        }
        for candidate in candidates:
            key = _reserve_candidate_identity_key(candidate)
            if not key or key in latest_item_keys:
                continue
            persisted_candidate = {
                k: v
                for k, v in dict(candidate).items()
                if not str(k).startswith("_")
            }
            latest_items.append(persisted_candidate)
            latest_item_keys.add(key)
        updated_candidates: list[dict[str, Any]] = []
        for item in latest_items:
            if not isinstance(item, dict):
                continue
            current = dict(item)
            outcome = attempted_by_key.get(
                (
                    str(current.get("search_id") or ""),
                    int(current.get("result_index") or 0),
                )
            )
            if outcome is None:
                updated_candidates.append(current)
                continue
            current["promotion_attempts"] = int(current.get("promotion_attempts") or 0) + 1
            current["last_promotion_outcome"] = dict(outcome)
            current["last_promotion_at"] = time.time()
            if outcome.get("full_text_failure_class_after"):
                current["full_text_failure_class"] = str(
                    outcome.get("full_text_failure_class_after") or ""
                )
            if outcome.get("full_text_resolution_status_after"):
                current["full_text_resolution_status"] = str(
                    outcome.get("full_text_resolution_status_after") or ""
                )
            if outcome.get("promoted"):
                current["reserve_status"] = "FULLTEXT_PROMOTED_AND_READMITTED"
                continue
            if outcome.get("full_text_available") and not outcome.get("aligned_after_fulltext"):
                current["reserve_status"] = "POST_FULLTEXT_ALIGNMENT_REJECTED"
            elif outcome.get("post_fulltext_status") == "POST_FULLTEXT_AUXILIARY_RESERVE":
                current["reserve_status"] = "POST_FULLTEXT_DEMOTED_TO_AUXILIARY"
            else:
                current["reserve_status"] = "FULLTEXT_RESOLUTION_RETRYABLE"
            updated_candidates.append(current)
        latest_reserve["candidates"] = updated_candidates
        latest_reserve["candidate_count"] = len(updated_candidates)
        latest_reserve.setdefault("promotion_history", []).extend(attempts)
        latest_reserve["promotion_history"] = latest_reserve["promotion_history"][-100:]
        latest_reserve["updatedAt"] = time.time()
        latest_root[sub_hypothesis_id] = latest_reserve
        latest_project["subhypothesis_evidence_reserve"] = latest_root
        save_project(latest_project)
    return {
        "schema_version": "subhypothesis_reserve_promotion_v2",
        "sub_hypothesis_id": sub_hypothesis_id,
        "reserve_candidates": candidate_pool_total,
        "attemptable_candidates": len(candidates),
        "explicit_reserve_candidates": len(explicit_candidates),
        "project_metadata_candidates": len(project_metadata_candidates),
        "project_metadata_retry_audit": project_metadata_audit,
        "skipped_terminal_fulltext_failures": len(skipped_terminal_fulltext_failures),
        "skipped_lexical_alignment_candidates": len(
            skipped_lexical_alignment_candidates
        ),
        "lexical_alignment_skip_policy": {
            "status": "explicit_candidate_alignment_only",
            "samples": skipped_lexical_alignment_candidates[:8],
        },
        "skipped_recent_attempts": len(skipped_recent_attempts),
        "recent_attempt_skip_policy": {
            "min_retry_age_seconds": max(0.0, float(min_retry_age_seconds or 0.0)),
            "applied": bool(float(min_retry_age_seconds or 0.0) > 0),
            "samples": skipped_recent_attempts[:8],
        },
        "attempted": len(attempts),
        "promoted": promoted,
        "reserve_promotion_stopped_reason": reserve_promotion_stopped_reason,
        "stopped_after_attempts": len(attempts) if reserve_promotion_stopped_reason else 0,
        "consecutive_no_oa_or_auth_failures": consecutive_no_oa_or_auth_failures,
        "fail_stop_threshold": fail_stop_threshold,
        "skipped_after_fail_stop": skipped_after_fail_stop,
        "attempts": attempts,
    }


def _run_post_fulltext_gate_literature_graphs(
    project_id: str,
    gate_requests: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Batch optional citation analysis after all selected SH gates finalize.

    Batching preserves the cross-sub-hypothesis global Louvain graph and makes
    Semantic Scholar graph traffic incapable of delaying any selected SH's
    search, full-text acquisition, admission review, or reserve backfill.
    """

    try:
        from ._literature_graph import build_subhypothesis_louvain_graphs
        from ._project import load_project, save_project
    except ImportError:
        from _literature_graph import build_subhypothesis_louvain_graphs
        from _project import load_project, save_project

    project = load_project(project_id)
    subhypotheses = {
        str(item.get("id") or ""): item
        for item in project.get("sub_hypotheses", [])
        if isinstance(item, dict) and str(item.get("id") or "")
    }
    prior_runs = [
        item
        for item in project.get("sub_hypothesis_retrieval_runs", [])
        if isinstance(item, dict)
    ]
    completed_results: dict[str, dict[str, Any]] = {}
    build_branches: list[dict[str, Any]] = []
    build_contexts: dict[str, dict[str, Any]] = {}
    optional_seed_insufficient_status = "optional_graph_seed_insufficient"
    legacy_seed_insufficient_status = "graph_seed_insufficient"
    graph_without_louvain_next_phase = "gap_detection_without_louvain"

    def normalize_optional_graph_status(status: Any) -> str:
        raw = str(status or "")
        if raw == legacy_seed_insufficient_status:
            return optional_seed_insufficient_status
        return raw

    def graph_stage_next_phase(successful_count: int, status: str) -> str:
        if successful_count > 0:
            return "gap_detection_with_louvain_enrichment"
        if status in {
            optional_seed_insufficient_status,
            legacy_seed_insufficient_status,
            "error",
            "graph_build_failed",
            "graph_skipped_global_rate_limit",
            "rate_limited_partial",
        }:
            return graph_without_louvain_next_phase
        return graph_without_louvain_next_phase

    for request in gate_requests:
        if not isinstance(request, dict):
            continue
        sub_id = str(request.get("sub_hypothesis_id") or "")
        coverage = (
            request.get("coverage")
            if isinstance(request.get("coverage"), dict)
            else {}
        )
        readiness = (
            request.get("readiness")
            if isinstance(request.get("readiness"), dict)
            else {}
        )
        gate_contract = (
            coverage.get("gate_contract")
            if isinstance(coverage.get("gate_contract"), dict)
            else {}
        )
        maturity_audit = (
            gate_contract.get("object_maturity_audit")
            if isinstance(gate_contract.get("object_maturity_audit"), dict)
            else {}
        )
        maturity_status = str(
            gate_contract.get("object_maturity_status")
            or maturity_audit.get("object_status")
            or maturity_audit.get("status")
            or ""
        ).strip().lower()
        maturity_retrieval_mode = str(
            gate_contract.get("object_maturity_retrieval_mode")
            or maturity_audit.get("retrieval_mode")
            or ""
        ).strip().lower()
        direct_core_validation_allowed = not (
            readiness.get("direct_core_validation_allowed") is False
            or gate_contract.get("direct_core_evidence_allowed") is False
            or maturity_audit.get("direct_core_evidence_allowed") is False
            or maturity_retrieval_mode == "component_bridge_boundary"
            or maturity_status
            in {
                "component_evidence_only",
                "translational_bridge",
                "speculative_unanchored",
            }
        )
        core_ready = bool(
            readiness.get("core_ready") is True
            and direct_core_validation_allowed
        )
        gap_mode = str(readiness.get("gap_mode") or "")
        gate_snapshot = {
            "peer_reviewed_full_text_target": int(
                coverage.get("peer_reviewed_full_text_target") or 10
            ),
            "peer_reviewed_full_text_count": int(
                coverage.get("peer_reviewed_full_text_count") or 0
            ),
            "direct_core_full_text_target": int(
                coverage.get("direct_contract_core_target")
                or coverage.get("direct_core_full_text_target")
                or 1
            ),
            "direct_core_full_text_count": int(
                coverage.get("direct_core_full_text_count") or 0
            ),
            "layer_shortfalls": dict(coverage.get("layer_shortfalls") or {}),
            "layer_preferred_shortfalls": dict(
                coverage.get("layer_preferred_shortfalls") or {}
            ),
            "passes": readiness.get("passes") is True,
            "workflow_ready": (
                readiness.get("workflow_ready") is True
                or readiness.get("corpus_ready") is True
                or readiness.get("passes") is True
                or readiness.get("component_bridge_gap_synthesis_ready") is True
                or readiness.get("ready_for_component_bridge_gap_synthesis") is True
            ),
            "core_ready": core_ready,
            "direct_core_validation_allowed": direct_core_validation_allowed,
            "evidence_review_state": str(readiness.get("evidence_review_state") or ""),
            "gap_mode": gap_mode,
        }
        graph_gate_passed = bool(gate_snapshot["workflow_ready"])
        if not graph_gate_passed:
            completed_results[sub_id] = {
                "schema_version": "subhypothesis_post_fulltext_graph_v2",
                "sub_hypothesis_id": sub_id,
                "phase": "post_fulltext_gate",
                "status": "deferred_until_fulltext_gate",
                "reason": (
                    "The optional citation graph was not started because the "
                    "cumulative related full-text workflow gate did not pass."
                ),
                "gate": gate_snapshot,
                "branches": [],
            }
            log_event(
                "SCIENCE",
                "subhypothesis_louvain_stage_deferred_fulltext_gate",
                project_id=project_id,
                sub_hypothesis_id=sub_id,
                peer_reviewed_full_text=gate_snapshot[
                    "peer_reviewed_full_text_count"
                ],
                direct_core_full_text=gate_snapshot[
                    "direct_core_full_text_count"
                ],
                workflow_ready=gate_snapshot["workflow_ready"],
                core_ready=gate_snapshot["core_ready"],
                evidence_review_state=gate_snapshot["evidence_review_state"],
                gap_mode=gate_snapshot["gap_mode"],
                layer_shortfalls=gate_snapshot["layer_shortfalls"],
                layer_preferred_shortfalls=gate_snapshot["layer_preferred_shortfalls"],
            )
            continue

        subhypothesis = subhypotheses.get(sub_id, {})
        retrieval = (
            dict(subhypothesis.get("retrieval") or {})
            if isinstance(subhypothesis.get("retrieval"), dict)
            else {}
        )
        search_id = str(retrieval.get("search_id") or "").strip()
        query = str(
            retrieval.get("query")
            or subhypothesis.get("retrieval_query")
            or subhypothesis.get("focus")
            or ""
        ).strip()
        if not search_id:
            for prior_run in reversed(prior_runs):
                if str(prior_run.get("sub_hypothesis_id") or "") != sub_id:
                    continue
                search_id = str(prior_run.get("search_id") or "").strip()
                query = str(prior_run.get("query") or query).strip()
                if search_id:
                    break

        existing_graph = (
            retrieval.get("literature_graph")
            if isinstance(retrieval.get("literature_graph"), dict)
            else {}
        )
        if (
            retrieval.get("literature_graph_phase") == "post_fulltext_gate"
            and str(existing_graph.get("source_search_id") or "") == search_id
            and str(existing_graph.get("status") or "")
            in {
                "success",
                "rate_limited_partial",
                legacy_seed_insufficient_status,
                optional_seed_insufficient_status,
            }
        ):
            existing_status = normalize_optional_graph_status(
                existing_graph.get("status")
            )
            completed_results[sub_id] = {
                "schema_version": "subhypothesis_post_fulltext_graph_v2",
                "sub_hypothesis_id": sub_id,
                "phase": "post_fulltext_gate",
                "status": "already_built_post_fulltext_gate",
                "graph_stage_status": existing_status,
                "optional_enrichment": True,
                "blocking": False,
                "next_phase": graph_stage_next_phase(
                    1 if existing_status == "success" else 0,
                    existing_status,
                ),
                "source_search_id": search_id,
                "gate": gate_snapshot,
                "branches": [existing_graph],
            }
            continue

        if not search_id:
            completed_results[sub_id] = {
                "schema_version": "subhypothesis_post_fulltext_graph_v2",
                "sub_hypothesis_id": sub_id,
                "phase": "post_fulltext_gate",
                "status": optional_seed_insufficient_status,
                "legacy_status": legacy_seed_insufficient_status,
                "reason_code": "missing_frozen_search_id",
                "reason": (
                    "The full-text gate passed, but no frozen peer-reviewed "
                    "search was available as a citation-graph seed pool."
                ),
                "optional_enrichment": True,
                "blocking": False,
                "next_phase": graph_without_louvain_next_phase,
                "fallback_applied": "papergraph_only_gap_detection",
                "source_search_id": "",
                "gate": gate_snapshot,
                "branches": [],
            }
            log_event(
                "SCIENCE",
                "subhypothesis_post_gate_louvain_stage_skipped",
                project_id=project_id,
                sub_hypothesis_id=sub_id,
                reason="missing_frozen_search_id",
                status=optional_seed_insufficient_status,
                blocking=False,
                next_phase=graph_without_louvain_next_phase,
            )
            continue

        allow_noncore_graph_seeds = bool(
            not core_ready
            or not direct_core_validation_allowed
            or gap_mode == "component_bridge_gap_synthesis"
        )
        build_contexts[sub_id] = {
            "source_search_id": search_id,
            "gate": gate_snapshot,
        }
        build_branches.append(
            {
                "sub_hypothesis_id": sub_id,
                "search_id": search_id,
                "query": query,
                "alignment_contract": dict(
                    request.get("alignment_contract") or {}
                ),
                "allow_noncore_graph_seeds": allow_noncore_graph_seeds,
                "graph_seed_policy": (
                    "related_corpus_seed_fallback_without_direct_core"
                    if allow_noncore_graph_seeds
                    else "strict_core_seed"
                ),
            }
        )

    stage: dict[str, Any] = {"status": "not_run", "branches": []}
    if build_branches:
        log_event(
            "SCIENCE",
            "subhypothesis_post_gate_louvain_batch_start",
            project_id=project_id,
            ready_branches=len(build_branches),
            sub_hypothesis_ids=[
                item["sub_hypothesis_id"] for item in build_branches
            ],
            all_selected_fulltext_loops_completed=True,
        )
        try:
            stage = dict(
                build_subhypothesis_louvain_graphs(
                    project_id,
                    build_branches,
                )
                or {}
            )
        except Exception as exc:
            stage = {
                "status": "error",
                "reason": str(exc)[:500],
                "branches": [],
                "optional_enrichment": True,
                "blocking": False,
                "next_phase": graph_without_louvain_next_phase,
                "seed_policy": {
                    "seeds_per_subhypothesis": 2,
                    "direction": "both",
                    "depth": 2,
                    "second_layer_top_k": 3,
                    "allow_fallback": False,
                },
            }
            log_event(
                "SCIENCE",
                "subhypothesis_post_gate_louvain_batch_failed",
                project_id=project_id,
                branches=len(build_branches),
                error=str(exc)[:240],
                fulltext_gates_remain_passed=True,
                fulltext_gate_scope="requested_ready_branches_only",
                optional_enrichment=True,
                blocking=False,
                next_phase=graph_without_louvain_next_phase,
            )

    branch_reports = {
        str(item.get("sub_hypothesis_id") or ""): dict(item)
        for item in (stage.get("branches") or [])
        if isinstance(item, dict) and str(item.get("sub_hypothesis_id") or "")
    }
    for sub_id, context in build_contexts.items():
        branch_report = branch_reports.get(sub_id, {})
        raw_status = str(
            branch_report.get("status")
            or stage.get("status")
            or "not_run"
        )
        status = normalize_optional_graph_status(raw_status)
        successful_count = 1 if status == "success" else 0
        next_phase = str(
            branch_report.get("next_phase")
            or stage.get("next_phase")
            or graph_stage_next_phase(successful_count, status)
        )
        completed_results[sub_id] = {
            "schema_version": "subhypothesis_post_fulltext_graph_v2",
            "sub_hypothesis_id": sub_id,
            "phase": "post_fulltext_gate",
            "status": status,
            "legacy_status": str(
                branch_report.get("legacy_status")
                or stage.get("legacy_status")
                or (legacy_seed_insufficient_status if raw_status == legacy_seed_insufficient_status else "")
            ),
            "batch_status": normalize_optional_graph_status(stage.get("status")),
            "optional_enrichment": True,
            "blocking": False,
            "next_phase": next_phase,
            "fallback_applied": str(
                branch_report.get("fallback_applied")
                or stage.get("fallback_applied")
                or ("papergraph_only_gap_detection" if next_phase == graph_without_louvain_next_phase else "")
            ),
            "reason_code": str(
                branch_report.get("reason_code")
                or stage.get("reason_code")
                or ""
            ),
            "source_search_id": context["source_search_id"],
            "gate": context["gate"],
            "branches": [branch_report] if branch_report else [],
            "reason": str(
                branch_report.get("reason")
                or stage.get("reason")
                or ""
            ),
        }

    if build_contexts:
        # The graph builder saves top-level graph artifacts. Reload before
        # attaching branch summaries so a stale outer project cannot overwrite
        # those artifacts.
        latest_project = load_project(project_id)
        for current in latest_project.get("sub_hypotheses", []):
            if not isinstance(current, dict):
                continue
            sub_id = str(current.get("id") or "")
            if sub_id not in build_contexts:
                continue
            result = completed_results[sub_id]
            branch_report = branch_reports.get(sub_id, {})
            current_retrieval = dict(current.get("retrieval") or {})
            current_retrieval["literature_graph_phase"] = "post_fulltext_gate"
            current_retrieval["literature_graph_gate"] = result["gate"]
            current_retrieval["literature_graph_stage_status"] = result[
                "status"
            ]
            current_retrieval["literature_graph_optional_enrichment"] = True
            current_retrieval["literature_graph_blocking"] = False
            current_retrieval["literature_graph_next_phase"] = result.get(
                "next_phase"
            )
            if branch_report:
                current_retrieval["literature_graph"] = branch_report
            current["retrieval"] = current_retrieval
        save_project(latest_project)
        successful_count = sum(
            item.get("status") == "success"
            for item in branch_reports.values()
        )
        normalized_stage_status = normalize_optional_graph_status(stage.get("status"))
        log_event(
            "SCIENCE",
            "subhypothesis_post_gate_louvain_batch_complete",
            project_id=project_id,
            requested_branches=len(build_branches),
            returned_branches=len(branch_reports),
            status=normalized_stage_status,
            legacy_status=str(stage.get("legacy_status") or ""),
            successful=successful_count,
            fulltext_gates_remain_passed=True,
            fulltext_gate_scope="requested_ready_branches_only",
            optional_enrichment=True,
            blocking=False,
            next_phase=graph_stage_next_phase(
                successful_count,
                normalized_stage_status,
            ),
            reason_code=str(stage.get("reason_code") or ""),
        )

    return [
        completed_results[sub_id]
        for sub_id in [
            str(item.get("sub_hypothesis_id") or "")
            for item in gate_requests
            if isinstance(item, dict)
        ]
        if sub_id in completed_results
    ]


def run_zhizhi_subhypothesis_analysis(
    project_id: str,
    sub_hypothesis_ids: list[str] | None = None,
) -> str:
    """Execute source-bound V3 retrieval slots for the selected SHs.

    Any missing, legacy, or mixed SH set is regenerated as one V3
    decomposition before retrieval.  This public entry therefore never
    delegates to the former causal-chain/full-text controller.
    """

    try:
        from .autogen_collab import execute_research_question_retrieval_plans_v3
        from ._gap_detection import execute_research_question_retrieval_plan
        from ._literature_import import import_literature_search_result
        from ._literature_search import search_papers_stratified
        from ._project import (
            decompose_research_objective,
            default_literature_providers,
            load_project,
            project_research_domain_context,
            restart_project_from_subhypothesis_decomposition,
        )
        from ._science_execution_policy import resolve_science_execution_policy
    except ImportError:
        from autogen_collab import execute_research_question_retrieval_plans_v3
        from _gap_detection import execute_research_question_retrieval_plan
        from _literature_import import import_literature_search_result
        from _literature_search import search_papers_stratified
        from _project import (
            decompose_research_objective,
            default_literature_providers,
            load_project,
            project_research_domain_context,
            restart_project_from_subhypothesis_decomposition,
        )
        from _science_execution_policy import resolve_science_execution_policy

    project = load_project(project_id)
    use_llm = resolve_science_execution_policy(project).use_llm
    v3_redecomposition_applied = False
    sub_hypotheses = [
        item for item in (project.get("sub_hypotheses") or []) if isinstance(item, dict)
    ]
    v3_sub_hypotheses = [
        item
        for item in sub_hypotheses
        if isinstance(item.get("research_question"), dict)
            or item.get("evidence_pipeline_schema") == "research_question_evidence_v3"
        or (
            isinstance(item.get("research_question_contract"), dict)
            and item["research_question_contract"].get("schema_version")
            == "research_question_contract_v3"
        )
    ]
    requested_ids = {str(item) for item in (sub_hypothesis_ids or []) if str(item)}
    if len(v3_sub_hypotheses) != len(sub_hypotheses) or not sub_hypotheses:
        if sub_hypotheses:
            restart_project_from_subhypothesis_decomposition(
                project_id,
                reason="zhizhi_subhypothesis_v3_contract_cutover",
            )
        decompose_research_objective(project_id, use_llm=use_llm)
        project = load_project(project_id)
        sub_hypotheses = [
            item for item in (project.get("sub_hypotheses") or []) if isinstance(item, dict)
        ]
        v3_sub_hypotheses = [
            item
            for item in sub_hypotheses
            if isinstance(item.get("research_question"), dict)
            and item.get("evidence_pipeline_schema") == "research_question_evidence_v3"
            and isinstance(item.get("research_question_contract"), dict)
            and item["research_question_contract"].get("schema_version")
            == "research_question_contract_v3"
        ]
        if len(v3_sub_hypotheses) != len(sub_hypotheses) or not sub_hypotheses:
            raise ValueError(
                "V3 decomposition did not produce a complete ResearchQuestionContractV3 set."
            )
        v3_redecomposition_applied = True

    available_ids = {
        str(item.get("id") or item.get("sub_hypothesis_id") or "").strip()
        for item in sub_hypotheses
        if str(item.get("id") or item.get("sub_hypothesis_id") or "").strip()
    }
    selected_ids = requested_ids & available_ids if requested_ids else available_ids
    if requested_ids and not selected_ids:
        raise ValueError(
            "None of the requested sub_hypothesis_ids exist in the current V3 decomposition."
        )
    selected_providers = default_literature_providers(
        domain=project_research_domain_context(project),
        query=str(project.get("objective") or ""),
    )
    execution = execute_research_question_retrieval_plans_v3(
        project=project,
        project_id=project_id,
        sub_hypothesis_ids=selected_ids,
        providers=selected_providers,
        use_llm=use_llm,
        search_papers_stratified=search_papers_stratified,
        import_literature_search_result=import_literature_search_result,
        execute_research_question_retrieval_plan=execute_research_question_retrieval_plan,
    )
    execution.update(
        {
            "project_id": project_id,
            "agent": "zhizhi",
            "requested_sub_hypothesis_ids": sorted(requested_ids),
            "ready_sub_hypothesis_ids": sorted(selected_ids),
            "v3_redecomposition_applied": v3_redecomposition_applied,
        }
    )
    return json.dumps(execution, ensure_ascii=False, indent=2)


def run_zhizhi_near_pass_source_role_retrieval(
    project_id: str,
    *,
    candidate_identity: str = "",
    gap_id: str = "",
    retrieval_result: dict[str, Any] | None = None,
    providers: list[str] | None = None,
    use_llm: bool = False,
) -> str:
    """Run one bounded, provenance-preserving repair for a TanXi near-pass.

    With no ``retrieval_result`` this dispatches the candidate-specific
    Zhizhi query that TanXi planned and records that the returned papers still
    require source-unit/role extraction.  A caller may then submit the
    structured extraction result (verified source units plus A/M/Y and a
    comparator); only then is the repaired candidate stored for the next
    full TanXi re-audit.  Neither path sends a candidate to Socrates.
    """
    try:
        from ._gap_detection import (
            apply_near_pass_targeted_retrieval_result,
            build_near_pass_targeted_retrieval_task,
        )
        from ._project import load_project, save_project
        from ._research_alignment import ensure_all_subhypothesis_alignment_contracts
        from ._research_workflow import (
            NEAR_PASS_RETRIEVAL_STAGE,
            TANXI_TOOL,
            record_workflow_status,
            workflow_tool_gate,
        )
    except ImportError:
        from _gap_detection import (
            apply_near_pass_targeted_retrieval_result,
            build_near_pass_targeted_retrieval_task,
        )
        from _project import load_project, save_project
        from _research_alignment import ensure_all_subhypothesis_alignment_contracts
        from _research_workflow import (
            NEAR_PASS_RETRIEVAL_STAGE,
            TANXI_TOOL,
            record_workflow_status,
            workflow_tool_gate,
        )

    project = load_project(project_id)
    ensure_all_subhypothesis_alignment_contracts(project)
    gate = workflow_tool_gate(
        project,
        NEAR_PASS_RETRIEVAL_STAGE,
        {"candidate_identity": candidate_identity, "gap_id": gap_id},
    )
    if gate.get("allowed") is not True:
        return json.dumps(gate.get("result") or {}, ensure_ascii=False, indent=2)

    tanxi = project.get("tanxi_gap_analysis") if isinstance(project.get("tanxi_gap_analysis"), dict) else {}
    task_rows = [item for item in (tanxi.get("near_pass_targeted_retrieval_tasks") or []) if isinstance(item, dict)]
    task = next(
        (
            item
            for item in task_rows
            if item.get("eligible") is True
            and (
                (candidate_identity and str(item.get("candidate_identity") or "") == str(candidate_identity))
                or (gap_id and str(item.get("gap_id") or "") == str(gap_id))
            )
        ),
        {},
    )
    candidate_collections = (
        tanxi.get("ranked_gaps") or [],
        tanxi.get("evidence_extraction_shortages") or [],
        tanxi.get("secondary_research_opportunities") or [],
        tanxi.get("rejected_evidence_audit") or [],
        tanxi.get("rejected_candidates") or [],
        tanxi.get("rejected_scientific_candidates") or [],
        [
            item
            for values in (tanxi.get("candidate_pools") or {}).values()
            if isinstance(values, list)
            for item in values
        ] if isinstance(tanxi.get("candidate_pools"), dict) else [],
        project.get("knowledge_gaps") or [],
    )
    candidate = next(
        (
            item
            for collection in candidate_collections
            for item in collection
            if isinstance(item, dict)
            and (
                (candidate_identity and str(item.get("candidate_identity") or "") == str(candidate_identity))
                or (gap_id and str(item.get("gap_id") or "") == str(gap_id))
            )
        ),
        {},
    )
    if not candidate or not task:
        return json.dumps(
            {
                "status": "BLOCKED_INVALID_UPSTREAM_ARTIFACT",
                "reason_code": "NEAR_PASS_TASK_OR_CANDIDATE_NOT_PERSISTED",
                "candidate_identity": candidate_identity,
                "gap_id": gap_id,
            },
            ensure_ascii=False,
            indent=2,
        )

    if isinstance(retrieval_result, dict) and retrieval_result:
        reaudited = apply_near_pass_targeted_retrieval_result(project, candidate, retrieval_result)
        immutable_identity = str(reaudited.get("candidate_identity") or task.get("candidate_identity") or "")
        retrieval_status = str((reaudited.get("near_pass_targeted_retrieval") or {}).get("status") or "")
        repair_completed = retrieval_status == "RETRIEVAL_REAUDITED"
        if repair_completed:
            repairs = project.get("near_pass_retrieval_repairs")
            repairs = dict(repairs) if isinstance(repairs, dict) else {}
            repairs[immutable_identity] = reaudited
            project["near_pass_retrieval_repairs"] = repairs
        result = {
            "status": (
                "NEAR_PASS_RETRIEVAL_REAUDITED"
                if repair_completed else "RETRIEVAL_RESULT_NOT_REPAIRABLE"
            ),
            "terminal": False,
            "reason_code": (
                "STRUCTURED_SOURCE_ROLE_REPAIR_REQUIRES_TANXI_READMISSION"
                if repair_completed else "VERIFIED_SOURCE_UNIT_OR_CAUSAL_ROLE_BINDINGS_INCOMPLETE"
            ),
            "candidate_identity": immutable_identity,
            "gap_id": str(reaudited.get("gap_id") or task.get("gap_id") or ""),
            "scientific_state_after_reaudit": str(reaudited.get("scientific_state") or ""),
            "allowed_next_stages": [TANXI_TOOL] if repair_completed else [NEAR_PASS_RETRIEVAL_STAGE],
            "blocked_stages": ["run_socrates_mechanism_enrichment", "run_mingli_hypothesis_evolution"],
            "artifact_ids": [str(reaudited.get("gap_id") or task.get("gap_id") or "")],
            "remediation_plan": {
                "kind": "tanxi_scientific_readmission" if repair_completed else "structured_source_role_extraction",
                "instruction": (
                    "Re-run TanXi with the persisted structured repair; only that normal gate may upgrade the scientific level."
                    if repair_completed else
                    "The supplied result did not bind verified source units plus all input/mediator/outcome/comparison roles; repair it before TanXi."
                ),
            },
        }
        result.update(record_workflow_status(
            project,
            stage=NEAR_PASS_RETRIEVAL_STAGE,
            status=str(result["status"]),
            terminal=bool(result["terminal"]),
            allowed_next_stages=list(result["allowed_next_stages"]),
            blocked_stages=list(result["blocked_stages"]),
            reason_code=str(result["reason_code"]),
            artifact_ids=list(result["artifact_ids"]),
            remediation_plan=dict(result["remediation_plan"]),
        ))
        project["updatedAt"] = time.time()
        save_project(project)
        return json.dumps(result, ensure_ascii=False, indent=2)

    contracts = project.get("subhypothesis_alignment_contracts")
    contracts = contracts if isinstance(contracts, dict) else {}
    branch_id = str(task.get("sub_hypothesis_id") or "")
    contentful_contract_repair = str(task.get("task_type") or "") == "CONTENTFUL_CAUSAL_CONTRACT_REPAIR"
    zhizhi_output = run_zhizhi_subhypothesis_analysis(
        project_id,
        sub_hypothesis_ids=[branch_id] if branch_id else None,
    )
    project = load_project(project_id)
    ensure_all_subhypothesis_alignment_contracts(project)
    runs = project.get("near_pass_targeted_retrieval_runs")
    runs = list(runs) if isinstance(runs, list) else []
    runs.append({
        "candidate_identity": str(task.get("candidate_identity") or ""),
        "gap_id": str(task.get("gap_id") or ""),
        "task": task,
        "status": "SEARCH_COMPLETED_AWAITING_STRUCTURED_SOURCE_BINDING",
        "response_chars": len(str(zhizhi_output or "")),
        "executed_at": time.time(),
    })
    project["near_pass_targeted_retrieval_runs"] = runs[-60:]
    result = {
        "status": "SEARCH_COMPLETED_AWAITING_STRUCTURED_SOURCE_BINDING",
        "terminal": False,
        "reason_code": "RETRIEVAL_TEXT_MUST_BE_BOUND_TO_SOURCE_UNITS_AND_CAUSAL_ROLES",
        "candidate_identity": str(task.get("candidate_identity") or ""),
        "gap_id": str(task.get("gap_id") or ""),
        "missing_evidence_roles": list(task.get("missing_evidence_roles") or []),
        "allowed_next_stages": [NEAR_PASS_RETRIEVAL_STAGE],
        "blocked_stages": ["run_socrates_mechanism_enrichment", "run_mingli_hypothesis_evolution"],
        "artifact_ids": [str(task.get("gap_id") or "")],
        "remediation_plan": {
            "kind": "structured_source_role_extraction",
            "instruction": "Submit verified source_evidence_units, A/M/Y role bindings, and an explicit comparison before requesting TanXi re-audit.",
        },
    }
    result.update(record_workflow_status(
        project,
        stage=NEAR_PASS_RETRIEVAL_STAGE,
        status=str(result["status"]),
        terminal=bool(result["terminal"]),
        allowed_next_stages=list(result["allowed_next_stages"]),
        blocked_stages=list(result["blocked_stages"]),
        reason_code=str(result["reason_code"]),
        artifact_ids=list(result["artifact_ids"]),
        remediation_plan=dict(result["remediation_plan"]),
    ))
    project["updatedAt"] = time.time()
    save_project(project)
    return json.dumps(result, ensure_ascii=False, indent=2)


def agents_for_phase(phase: str) -> list[str]:
    try:
        from ._models import SCIENCE_AGENTS
    except ImportError:
        from _models import SCIENCE_AGENTS
    return [name for name, spec in SCIENCE_AGENTS.items() if spec.get("phase") in {phase, "all"}]

def supporting_references_for_method_or_scenario(project: dict[str, Any], method: str, scenario: str) -> list[str]:
    try:
        from ._utils import normalize_label
    except ImportError:
        from _utils import normalize_label
    refs: list[str] = []
    for evidence in project.get("evidence", []):
        if normalize_label(evidence.get("method", "")) == method or normalize_label(evidence.get("scenario", "")) == scenario:
            citation = str(evidence.get("citation", ""))
            if citation and citation not in refs:
                refs.append(citation)
    return refs[:5]

def project_records_for_mapping(project: dict[str, Any]) -> list[dict[str, Any]]:
    """Merge PaperGraph and Evidence projections without letting a projection overwrite its paper.

    ``Evidence`` is a compact projection and commonly lacks source text.  The
    canonical PaperGraph record is preferred whenever both share ``paper_id``
    (then other stable identities), so descriptor admission always sees the
    richer, source-grounded record.
    """
    def mapping_keys(record: dict[str, Any]) -> list[str]:
        keys: list[str] = []
        paper_id = str(record.get("paper_id") or "").strip()
        if paper_id:
            keys.append(f"paper:{paper_id}")
        for field in ("unique_key", "citation", "title"):
            value = str(record.get(field) or "").strip()
            if value:
                keys.append(f"{field}:{value.lower()}")
        return keys or [f"object:{id(record)}"]

    selected: list[dict[str, Any]] = []
    key_to_index: dict[str, int] = {}
    for collection_name in ("papergraph", "evidence"):
        collection = project.get(collection_name, [])
        if not isinstance(collection, list):
            continue
        for record in collection:
            if not isinstance(record, dict) or record.get("active", True) is False:
                continue
            keys = mapping_keys(record)
            existing_indexes = {key_to_index[key] for key in keys if key in key_to_index}
            if existing_indexes:
                canonical_index = min(existing_indexes)
                for key in keys:
                    key_to_index[key] = canonical_index
                continue
            canonical_index = len(selected)
            selected.append(record)
            for key in keys:
                key_to_index[key] = canonical_index
    return selected

def classify_record_evidence(record: dict[str, Any]) -> list[dict[str, str]]:
    text = "\n".join(
        str(record.get(key, ""))
        for key in ("abstract", "conclusion", "contribution", "limitation")
        if record.get(key)
    )
    return classify_evidence_claims(text, record)

def classify_evidence_claims(text: str, parsed: dict[str, Any] | None = None) -> list[dict[str, str]]:
    try:
        from ._utils import scalar, split_sentences, trim_text
    except ImportError:
        from _utils import scalar, split_sentences, trim_text
    parsed = parsed or {}
    claims: list[dict[str, str]] = []
    candidates = [
        ("methodological_description", parsed.get("method", "")),
        ("empirical_result", parsed.get("contribution", "")),
        ("author_opinion", parsed.get("limitation", "")),
        ("theoretical_claim", parsed.get("conclusion", "")),
    ]
    for claim_type, claim in candidates:
        rendered = scalar(claim)
        if rendered:
            claims.append({"claim_type": claim_type, "claim": trim_text(rendered, 300), "support": "structured_field"})
    for sentence in split_sentences(text)[:12]:
        lowered = sentence.lower()
        claim_type = ""
        if any(term in lowered for term in ("experiment", "result", "outperform", "accuracy", "measured", "observed")):
            claim_type = "empirical_result"
        elif any(term in lowered for term in ("theorem", "theory", "prove", "derive", "model predicts")):
            claim_type = "theoretical_claim"
        elif any(term in lowered for term in ("method", "algorithm", "framework", "approach", "we propose")):
            claim_type = "methodological_description"
        elif any(term in lowered for term in ("suggest", "may", "could", "indicate", "limitation", "future work")):
            claim_type = "author_opinion"
        if claim_type:
            claims.append({"claim_type": claim_type, "claim": trim_text(sentence, 300), "support": "source_sentence"})
    seen: set[tuple[str, str]] = set()
    unique: list[dict[str, str]] = []
    for item in claims:
        key = (item["claim_type"], item["claim"])
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return unique[:12]

