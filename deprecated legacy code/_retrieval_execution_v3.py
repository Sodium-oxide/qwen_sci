"""V3 retrieval query compilation, provider outcomes, and recovery control.

This module is the execution boundary for the current retrieval contract.  It
does not interpret a provider miss as a scientific conclusion and it does not
adapt an earlier retrieval schema.  Every cache and continuation decision is
bound to a V3 work item, its contract revision, and the exact query variant.
"""

from __future__ import annotations

from enum import Enum
from hashlib import sha256
import json
from threading import Lock
import time
from typing import Any, Callable, Iterable, Mapping

try:
    from ._research_question_contract import (
        PROVIDER_OUTCOME_VERSION,
        RETRIEVAL_TASK_SPEC_VERSION,
        ProviderOutcomeKind,
        RetrievalWorkItemKind,
        build_provider_outcome_v3,
        validate_retrieval_work_item_v3,
    )
except ImportError:
    from _research_question_contract import (
        PROVIDER_OUTCOME_VERSION,
        RETRIEVAL_TASK_SPEC_VERSION,
        ProviderOutcomeKind,
        RetrievalWorkItemKind,
        build_provider_outcome_v3,
        validate_retrieval_work_item_v3,
    )


RETRIEVAL_QUERY_VARIANT_VERSION = "retrieval_query_variant_v3"
RETRIEVAL_QUERY_COMPILATION_VERSION = "retrieval_query_compilation_v3"
RETRIEVAL_ZERO_RESULT_CACHE_VERSION = "retrieval_zero_result_cache_v3"
COMPARISON_RETRIEVAL_PHASE_VERSION = "comparison_retrieval_phase_v4"


class QueryIntentV3(str, Enum):
    """The scientific purpose of a provider query, never an inferred result."""

    DIRECT_SLOT_EVIDENCE = "DIRECT_SLOT_EVIDENCE"
    OPEN_GAP_EVIDENCE = "OPEN_GAP_EVIDENCE"
    RESOLUTION_OR_DISQUALIFICATION = "RESOLUTION_OR_DISQUALIFICATION"


class ComparisonEvidenceRoleV3(str, Enum):
    """The non-interchangeable retrieval roles of a V3 comparison task."""

    DIRECT_PAIR_COMPARISON = "DIRECT_PAIR_COMPARISON"
    ARM_COMPONENT_DISCOVERY = "ARM_COMPONENT_DISCOVERY"
    COMPARABILITY_BRIDGE = "COMPARABILITY_BRIDGE"


class ComparisonRetrievalPhaseV3(str, Enum):
    """The ordered execution phases of a current comparison contract."""

    ARM_FIRST_PHASE = "ARM_FIRST_PHASE"
    COMPARABILITY_FOLLOWUP_PHASE = "COMPARABILITY_FOLLOWUP_PHASE"


class RetrievalQueryCompilationError(ValueError):
    """A local V3 contract error.  It must never be retried at a provider."""


def _text(value: Any) -> str:
    return " ".join(str(value or "").split())


def _strings(value: Any) -> list[str]:
    source = value if isinstance(value, (list, tuple, set)) else [value]
    output: list[str] = []
    seen: set[str] = set()
    for item in source:
        text = _text(item)
        key = text.casefold()
        if text and key not in seen:
            seen.add(key)
            output.append(text)
    return output


def _fingerprint(value: Mapping[str, Any]) -> str:
    return "sha256:" + sha256(
        json.dumps(dict(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()


def _spec_blueprint(spec: Mapping[str, Any]) -> dict[str, Any]:
    blueprint = spec.get("query_blueprint_v3")
    if not isinstance(blueprint, Mapping) or blueprint.get("schema_version") != "retrieval_query_blueprint_v3":
        raise RetrievalQueryCompilationError("V3 retrieval spec requires retrieval_query_blueprint_v3")
    return dict(blueprint)


def _scope_terms_from_spec(spec: Mapping[str, Any], blueprint: Mapping[str, Any]) -> tuple[list[str], list[str], list[str]]:
    required = blueprint.get("required_anchor_groups")
    topic = blueprint.get("topic_anchor_groups")
    method = blueprint.get("method_anchor_groups")
    required = required if isinstance(required, Mapping) else {}
    topic = topic if isinstance(topic, Mapping) else {}
    method = method if isinstance(method, Mapping) else {}
    research_object = _strings(required.get("research_object"))
    scoped_target = _strings([
        *(topic.get("target_construct") or []),
        *(topic.get("measurement_or_outcome") or []),
        *(method.get("measurement_method") or []),
        *(blueprint.get("slot_evidence_terms") or []),
    ])
    materialization = blueprint.get("provider_query_materialization_v3")
    if not isinstance(materialization, Mapping):
        materialization = spec.get("provider_query_materialization_v3")
    materialization = materialization if isinstance(materialization, Mapping) else {}
    provider_terms = _strings(materialization.get("provider_terms"))
    if not research_object:
        raise RetrievalQueryCompilationError("V3 retrieval query lacks a declared research_object anchor")
    if not scoped_target:
        raise RetrievalQueryCompilationError(
            "V3 retrieval query lacks a declared target, outcome, method, or slot requirement; generic topic search is prohibited"
        )
    if not provider_terms or not any(term.casefold() in {item.casefold() for item in provider_terms} for term in research_object):
        raise RetrievalQueryCompilationError("V3 provider materialization does not preserve the required research_object anchor")
    if not any(term.casefold() in {item.casefold() for item in provider_terms} for term in scoped_target):
        raise RetrievalQueryCompilationError(
            "V3 provider materialization does not preserve a scoped target, outcome, method, or slot requirement"
        )
    return research_object, scoped_target, provider_terms


def _validate_slot_binding(
    retrieval_spec: Mapping[str, Any],
    retrieval_work_item: Mapping[str, Any],
    *,
    plan_revision: str,
) -> dict[str, Any]:
    if retrieval_spec.get("schema_version") != RETRIEVAL_TASK_SPEC_VERSION:
        raise RetrievalQueryCompilationError("Only retrieval_task_spec_v3 can be compiled for provider dispatch")
    work_item = validate_retrieval_work_item_v3(retrieval_work_item)
    if work_item["work_item_kind"] != RetrievalWorkItemKind.SLOT_RECOVERY.value:
        raise RetrievalQueryCompilationError("Slot query compilation requires a SLOT_RECOVERY work item")
    semantic_fingerprint = _text(retrieval_spec.get("semantic_fingerprint"))
    if not semantic_fingerprint or semantic_fingerprint != _text(work_item.get("plan_fingerprint")):
        raise RetrievalQueryCompilationError("V3 work item and retrieval spec have different plan fingerprints")
    if not _text(plan_revision):
        raise RetrievalQueryCompilationError("V3 provider execution requires the active retrieval plan revision")
    return work_item


def _variant(
    *,
    provider: str,
    intent: QueryIntentV3,
    variant_id: str,
    query: str,
    work_item: Mapping[str, Any],
    plan_revision: str,
    retained_anchor_groups: Iterable[str],
    semantic_fingerprint: str,
    trigger: str,
    comparison_binding: Mapping[str, Any] | None = None,
    target_slot_ids: Iterable[str] = (),
    fixed_scope_groups: Iterable[str] = (),
) -> dict[str, Any]:
    query = _text(query)
    if not query:
        raise RetrievalQueryCompilationError("V3 provider query cannot be empty")
    binding = {
        "work_item_kind": _text(work_item.get("work_item_kind")),
        "research_question_contract_id": _text(work_item.get("research_question_contract_id")),
        "research_question_contract_revision": _text(work_item.get("research_question_contract_revision")),
        "plan_revision": _text(plan_revision),
        "plan_fingerprint": _text(work_item.get("plan_fingerprint")),
        "gap_candidate_id": _text(work_item.get("gap_candidate_id")),
        "gap_candidate_fingerprint": _text(work_item.get("gap_candidate_fingerprint")),
        "gap_type": _text(work_item.get("gap_type")),
        "provider": _text(provider).casefold(),
        "query_intent": intent.value,
        "variant_id": variant_id,
        "query": query,
    }
    comparison = (
        dict(comparison_binding)
        if isinstance(comparison_binding, Mapping)
        else {}
    )
    if comparison:
        binding.update({
            "comparison_contract_id": _text(comparison.get("comparison_contract_id")),
            "comparison_contract_fingerprint": _text(
                comparison.get("comparison_contract_fingerprint")
            ),
            "comparison_evidence_role": _text(comparison.get("comparison_evidence_role")),
            "primary_arm_id": _text(comparison.get("primary_arm_id")),
            "comparator_arm_id": _text(comparison.get("comparator_arm_id")),
            "comparability_axes": _strings(
                comparison.get("comparability_axes")
            ),
            "can_satisfy_comparison_conclusion": bool(
                comparison.get("can_satisfy_comparison_conclusion")
            ),
        })
    fingerprint = _fingerprint(binding)
    return {
        "schema_version": RETRIEVAL_QUERY_VARIANT_VERSION,
        "variant_id": variant_id,
        "query_intent": intent.value,
        "trigger": trigger,
        "query": query,
        "provider_expression": query,
        "provider_safe_expression": query,
        "dispatch_allowed": True,
        "skip_reason": "",
        "semantic_fingerprint": semantic_fingerprint,
        "variant_fingerprint": fingerprint,
        "query_fingerprint": fingerprint,
        "retained_anchor_groups": _strings(retained_anchor_groups),
        "fixed_scope_groups": _strings(fixed_scope_groups),
        "target_slot_ids": _strings(target_slot_ids),
        **({
            "comparison_evidence_role": binding["comparison_evidence_role"],
            "comparison_contract_id": binding["comparison_contract_id"],
            "primary_arm_id": binding["primary_arm_id"],
            "comparator_arm_id": binding["comparator_arm_id"],
            "comparability_axes": list(binding["comparability_axes"]),
            "can_satisfy_comparison_conclusion": binding["can_satisfy_comparison_conclusion"],
        } if comparison else {}),
        "work_item_binding": binding,
    }


def _comparison_contract_from_spec(retrieval_spec: Mapping[str, Any]) -> dict[str, Any]:
    """Return the active explicit arm-first comparison contract carried by a spec."""

    contract = retrieval_spec.get("comparison_contract_v4")
    if not isinstance(contract, Mapping):
        blueprint = _spec_blueprint(retrieval_spec)
        contract = blueprint.get("comparison_contract_v4")
    contract = dict(contract) if isinstance(contract, Mapping) else {}
    required = (
        "comparison_contract_id",
        "comparison_contract_fingerprint",
        "comparison_kind",
        "primary_arm",
        "comparator_arms",
        "target_comparison_pairs",
        "required_metric_families",
        "comparability_axes",
    )
    if contract.get("schema_version") != "comparison_contract_v4" or not all(
        contract.get(field) for field in required
    ):
        raise RetrievalQueryCompilationError(
            "BENCHMARK_COMPARISON query compilation requires an explicit comparison_contract_v4"
        )
    return contract


def _comparison_arm_terms(arm: Mapping[str, Any]) -> list[str]:
    return _strings([
        arm.get("canonical_label"),
        *(arm.get("accepted_surface_forms") or []),
    ])


def _comparison_query_terms(
    provider_terms: Iterable[Any],
    arms: Iterable[Mapping[str, Any]],
) -> list[str]:
    """Keep V3 scope anchors while replacing generic arm terms by named arms."""

    declared_arm_terms = {
        _text(surface).casefold()
        for arm in arms
        for surface in _comparison_arm_terms(arm)
    }
    return [
        term for term in _strings(provider_terms)
        if term.casefold() not in declared_arm_terms
    ]


def _comparison_variants_v4(
    *,
    provider: str,
    spec: Mapping[str, Any],
    work_item: Mapping[str, Any],
    blueprint: Mapping[str, Any],
    provider_terms: list[str],
    plan_revision: str,
) -> list[dict[str, Any]]:
    """Compile pair, component, and bridge queries from declared comparison arms."""

    comparison = _comparison_contract_from_spec(spec)
    primary = comparison.get("primary_arm")
    comparators = comparison.get("comparator_arms")
    if not isinstance(primary, Mapping) or not isinstance(comparators, list):
        raise RetrievalQueryCompilationError("comparison_contract_v4 has invalid arm declarations")
    arms_by_id = {
        _text(item.get("arm_id")): dict(item)
        for item in [primary, *comparators]
        if isinstance(item, Mapping) and _text(item.get("arm_id"))
    }
    primary_id = _text(primary.get("arm_id"))
    pairs = [
        tuple(_strings(pair))
        for pair in comparison.get("target_comparison_pairs") or []
        if len(_strings(pair)) == 2
    ]
    if not primary_id or not pairs or any(
        primary_id not in pair or any(arm_id not in arms_by_id for arm_id in pair)
        for pair in pairs
    ):
        raise RetrievalQueryCompilationError("comparison_contract_v4 lacks valid target pairs")
    required_slots = _strings(
        (spec.get("target_slot_ids") or [])
        or (spec.get("evidence_contract") or [])
        or [spec.get("slot_identity")]
    )
    fixed_scope_groups = [
        "research_object", "measurement_or_outcome", "comparison_frame",
    ]
    retained_scope = _strings(
        (blueprint.get("provider_query_materialization_v3") or {}).get(
            "retained_anchor_groups"
        ) or fixed_scope_groups
    )
    common_terms = _comparison_query_terms(provider_terms, arms_by_id.values())
    semantic_fingerprint = _text(spec.get("semantic_fingerprint"))
    variants: list[dict[str, Any]] = []

    def append_variant(
        *,
        role: ComparisonEvidenceRoleV3,
        variant_id: str,
        terms: Iterable[Any],
        comparator_arm_id: str = "",
        can_satisfy_bundle: bool,
        phase: str,
    ) -> None:
        variants.append(_variant(
            provider=provider,
            intent=QueryIntentV3.DIRECT_SLOT_EVIDENCE,
            variant_id=variant_id,
            query=" ".join(_strings(terms)),
            work_item=work_item,
            plan_revision=plan_revision,
            retained_anchor_groups=retained_scope,
            fixed_scope_groups=fixed_scope_groups,
            target_slot_ids=required_slots,
            semantic_fingerprint=semantic_fingerprint,
            trigger=phase,
            comparison_binding={
                "comparison_contract_id": comparison["comparison_contract_id"],
                "comparison_contract_fingerprint": comparison["comparison_contract_fingerprint"],
                "comparison_evidence_role": role.value,
                "primary_arm_id": primary_id,
                "comparator_arm_id": comparator_arm_id,
                "comparability_axes": comparison["comparability_axes"],
                "can_satisfy_comparison_conclusion": can_satisfy_bundle,
            },
        ))

    for pair in pairs:
        comparator_id = pair[1] if pair[0] == primary_id else pair[0]
        append_variant(
            role=ComparisonEvidenceRoleV3.DIRECT_PAIR_COMPARISON,
            variant_id=f"direct_pair__{primary_id}__{comparator_id}",
            terms=[
                *common_terms,
                *_comparison_arm_terms(arms_by_id[primary_id]),
                *_comparison_arm_terms(arms_by_id[comparator_id]),
                "comparison", "versus", "benchmark", "validation",
            ],
            comparator_arm_id=comparator_id,
            can_satisfy_bundle=True,
            phase="ARM_FIRST_PHASE",
        )
    for arm_id, arm in arms_by_id.items():
        append_variant(
            role=ComparisonEvidenceRoleV3.ARM_COMPONENT_DISCOVERY,
            variant_id=f"arm_component__{arm_id}",
            terms=[*common_terms, *_comparison_arm_terms(arm)],
            comparator_arm_id="",
            can_satisfy_bundle=False,
            phase="ARM_FIRST_PHASE",
        )
    for pair in pairs:
        comparator_id = pair[1] if pair[0] == primary_id else pair[0]
        append_variant(
            role=ComparisonEvidenceRoleV3.COMPARABILITY_BRIDGE,
            variant_id=f"comparability_bridge__{primary_id}__{comparator_id}",
            terms=[
                *common_terms,
                *_comparison_arm_terms(arms_by_id[primary_id]),
                *_comparison_arm_terms(arms_by_id[comparator_id]),
                "common metric", "calibration", "benchmark", "protocol",
            ],
            comparator_arm_id=comparator_id,
            can_satisfy_bundle=False,
            phase=ComparisonRetrievalPhaseV3.COMPARABILITY_FOLLOWUP_PHASE.value,
        )
    return variants


def select_comparison_query_variants_for_phase_v4(
    variants: Iterable[Mapping[str, Any]],
    phase_payload: Mapping[str, Any] | None,
) -> list[dict[str, Any]]:
    """Select one comparison phase without changing any variant's contract."""

    phase_source = dict(phase_payload) if isinstance(phase_payload, Mapping) else {}
    phase = _text(phase_source.get("phase")) or ComparisonRetrievalPhaseV3.ARM_FIRST_PHASE.value
    if phase not in {
        item.value for item in ComparisonRetrievalPhaseV3
    }:
        raise RetrievalQueryCompilationError(
            "comparison_retrieval_phase_v4.phase is not supported by the arm-first comparison workflow"
        )
    required_role = (
        {
            ComparisonEvidenceRoleV3.DIRECT_PAIR_COMPARISON.value,
            ComparisonEvidenceRoleV3.ARM_COMPONENT_DISCOVERY.value,
        }
        if phase == ComparisonRetrievalPhaseV3.ARM_FIRST_PHASE.value
        else {
            ComparisonEvidenceRoleV3.COMPARABILITY_BRIDGE.value,
        }
    )
    selected: list[dict[str, Any]] = []
    for raw_variant in variants:
        if not isinstance(raw_variant, Mapping):
            continue
        variant = dict(raw_variant)
        if _text(variant.get("comparison_evidence_role")) not in required_role:
            continue
        variant["comparison_retrieval_phase_v4"] = {
            "schema_version": COMPARISON_RETRIEVAL_PHASE_VERSION,
            "phase": phase,
        }
        selected.append(variant)
    if not selected:
        raise RetrievalQueryCompilationError(
            "comparison_retrieval_phase_v4 selects no arm-first comparison query variants"
        )
    return selected


def compile_slot_query_variants_v3(
    provider: str,
    retrieval_spec: Mapping[str, Any],
    retrieval_work_item: Mapping[str, Any],
    *,
    plan_revision: str,
) -> list[dict[str, Any]]:
    """Compile scope-preserving direct evidence queries from a V3 slot task.

    A slot work item has one scientific intent.  This compiler intentionally
    does not generate a topic-only relaxation when the provider returns zero
    candidates; recovery must retain the same declared scope.
    """

    spec = dict(retrieval_spec) if isinstance(retrieval_spec, Mapping) else {}
    work_item = _validate_slot_binding(spec, retrieval_work_item, plan_revision=plan_revision)
    blueprint = _spec_blueprint(spec)
    _research_object, _scoped_target, provider_terms = _scope_terms_from_spec(spec, blueprint)
    if isinstance(spec.get("comparison_contract_v4"), Mapping) or isinstance(
        blueprint.get("comparison_contract_v4"), Mapping
    ):
        return _comparison_variants_v4(
            provider=provider,
            spec=spec,
            work_item=work_item,
            blueprint=blueprint,
            provider_terms=provider_terms,
            plan_revision=plan_revision,
        )
    return [
        _variant(
            provider=provider,
            intent=QueryIntentV3.DIRECT_SLOT_EVIDENCE,
            variant_id="direct_slot_evidence",
            query=" ".join(provider_terms),
            work_item=work_item,
            plan_revision=plan_revision,
            retained_anchor_groups=(
                (blueprint.get("provider_query_materialization_v3") or {}).get("retained_anchor_groups")
                or ["research_object", "slot_requirement"]
            ),
            semantic_fingerprint=_text(spec.get("semantic_fingerprint")),
            trigger="initial",
        )
    ]


def compile_gap_query_variants_v3(
    provider: str,
    gap_search_plan: Mapping[str, Any],
    retrieval_work_item: Mapping[str, Any],
    *,
    plan_revision: str,
) -> list[dict[str, Any]]:
    """Compile the required two-sided V3 gap search without topic fallback."""

    plan = dict(gap_search_plan) if isinstance(gap_search_plan, Mapping) else {}
    if plan.get("schema_version") != "gap_search_plan_v3":
        raise RetrievalQueryCompilationError("Gap provider execution requires gap_search_plan_v3")
    work_item = validate_retrieval_work_item_v3(retrieval_work_item)
    if work_item["work_item_kind"] != RetrievalWorkItemKind.GAP_RESOLUTION.value:
        raise RetrievalQueryCompilationError("Gap query compilation requires a GAP_RESOLUTION work item")
    if _text(plan.get("candidate_identity")) != _text(work_item.get("gap_candidate_id")):
        raise RetrievalQueryCompilationError("Gap plan and work item candidate identities do not match")
    if _text(plan.get("gap_type")) != _text(work_item.get("gap_type")):
        raise RetrievalQueryCompilationError("Gap plan and work item gap types do not match")
    if not _text(plan_revision) or not _text(work_item.get("plan_fingerprint")):
        raise RetrievalQueryCompilationError("Gap provider execution requires active V3 plan binding")
    open_queries = _strings([*(plan.get("positive_queries") or []), *(plan.get("primary_source_queries") or [])])
    resolution_queries = _strings([*(plan.get("negative_queries") or []), *(plan.get("review_queries") or [])])
    if not open_queries or not resolution_queries:
        raise RetrievalQueryCompilationError("V3 gap plan requires both open-gap and resolution/disqualification queries")
    required_terms = _strings(plan.get("missing_axes"))
    if not required_terms:
        raise RetrievalQueryCompilationError("V3 gap plan lacks typed evidence obligations and cannot issue a generic topic query")
    semantic_fingerprint = _fingerprint({
        "gap_search_plan_v3": plan,
        "plan_revision": plan_revision,
        "work_item_plan_fingerprint": work_item.get("plan_fingerprint"),
    })
    return [
        _variant(
            provider=provider,
            intent=QueryIntentV3.OPEN_GAP_EVIDENCE,
            variant_id="open_gap_evidence",
            query=open_queries[0],
            work_item=work_item,
            plan_revision=plan_revision,
            retained_anchor_groups=["gap_type", *required_terms],
            semantic_fingerprint=semantic_fingerprint,
            trigger="initial",
        ),
        _variant(
            provider=provider,
            intent=QueryIntentV3.RESOLUTION_OR_DISQUALIFICATION,
            variant_id="resolution_or_disqualification",
            query=resolution_queries[0],
            work_item=work_item,
            plan_revision=plan_revision,
            retained_anchor_groups=["gap_type", *required_terms],
            semantic_fingerprint=semantic_fingerprint,
            trigger="paired_resolution_search",
        ),
    ]


def retrieval_zero_result_cache_key_v3(
    provider: str,
    variant: Mapping[str, Any],
) -> str:
    """Return a zero-result key scoped to V3 contract and query identity."""

    binding = variant.get("work_item_binding") if isinstance(variant.get("work_item_binding"), Mapping) else {}
    required = (
        "research_question_contract_id",
        "research_question_contract_revision",
        "plan_revision",
        "plan_fingerprint",
        "query_intent",
    )
    if not all(_text(binding.get(field)) for field in required):
        raise RetrievalQueryCompilationError("V3 zero-result cache requires complete contract-revision and plan binding")
    return _fingerprint({
        "schema_version": RETRIEVAL_ZERO_RESULT_CACHE_VERSION,
        "provider": _text(provider).casefold(),
        "variant_fingerprint": _text(variant.get("variant_fingerprint")),
        "query_fingerprint": _text(variant.get("query_fingerprint")),
        "provider_safe_expression": _text(
            variant.get("provider_safe_expression")
            or variant.get("provider_expression")
            or variant.get("query")
        ),
        "work_item_binding": dict(binding),
    })


class V3ZeroResultCache:
    """In-memory cache for definitive V3 empty responses only."""

    def __init__(self) -> None:
        self._entries: dict[str, dict[str, Any]] = {}
        self._lock = Lock()

    def get(self, provider: str, variant: Mapping[str, Any]) -> dict[str, Any] | None:
        key = retrieval_zero_result_cache_key_v3(provider, variant)
        with self._lock:
            entry = self._entries.get(key)
            return dict(entry) if isinstance(entry, dict) else None

    def put(self, provider: str, variant: Mapping[str, Any], outcome: Mapping[str, Any]) -> None:
        if outcome.get("schema_version") != PROVIDER_OUTCOME_VERSION:
            raise RetrievalQueryCompilationError("Only ProviderOutcomeV3 may populate the V3 zero-result cache")
        if outcome.get("outcome") != ProviderOutcomeKind.SUCCESS_EMPTY.value:
            return
        key = retrieval_zero_result_cache_key_v3(provider, variant)
        with self._lock:
            self._entries[key] = {"provider_outcome_v3": dict(outcome)}


DEFAULT_V3_ZERO_RESULT_CACHE = V3ZeroResultCache()


_V3_LOCAL_PRE_SUBMISSION_STATUSES = frozenset({
    "skipped",
    "invalid_query",
    "query_plan_contract_error",
    "provider_query_compilation_error",
    "provider_query_syntax_error",
})
_V3_LOCAL_PRE_SUBMISSION_STAGES = frozenset({
    "query_compilation",
    "provider_query_compilation",
    "query_plan_contract",
})


def normalize_provider_dispatch_block_v3(
    provider: str,
    query: str,
    block: Mapping[str, Any],
) -> dict[str, Any]:
    """Establish V3 submission provenance before outcome classification.

    A fresh dispatch response is not allowed to leave submission provenance
    implicit.  Explicit local pre-submission rejections remain unsubmitted;
    all other blocks returned from the invoked provider dispatch represent an
    attempted provider request, including empty and transport-error responses.
    """

    payload = dict(block) if isinstance(block, Mapping) else {}
    payload.setdefault("provider", provider)
    payload.setdefault("query", query)
    if "submitted_to_provider" in payload:
        payload["submitted_to_provider"] = bool(payload["submitted_to_provider"])
        return payload

    status = _text(payload.get("status")).casefold()
    failure_stage = _text(payload.get("failure_stage")).casefold()
    failure_kind = _text(payload.get("failure_kind")).casefold()
    payload["submitted_to_provider"] = not (
        status in _V3_LOCAL_PRE_SUBMISSION_STATUSES
        or failure_stage in _V3_LOCAL_PRE_SUBMISSION_STAGES
        or failure_kind in _V3_LOCAL_PRE_SUBMISSION_STATUSES
    )
    return payload


def _provider_error_text(block: Mapping[str, Any]) -> str:
    return " ".join(
        _text(block.get(field))
        for field in ("status", "error", "failure_kind", "skipped_provider_reason", "note")
    ).casefold()


def provider_outcome_from_block_v3(
    provider: str,
    variant: Mapping[str, Any],
    block: Mapping[str, Any],
    *,
    attempt: int,
) -> dict[str, Any]:
    """Classify one provider response without conflating errors and empties."""

    payload = dict(block) if isinstance(block, Mapping) else {}
    raw_result_count = len(payload.get("results") or [])
    text = _provider_error_text(payload)
    submitted = bool(payload.get("submitted_to_provider"))
    if not submitted or any(marker in text for marker in (
        "invalid_query", "query_plan_contract", "query_compilation", "query_syntax", "anchor_validation",
    )):
        kind = ProviderOutcomeKind.INVALID_QUERY
    elif any(marker in text for marker in ("timeout", "timed out", "read operation timed out", "time out")):
        kind = ProviderOutcomeKind.TIMEOUT
    elif any(marker in text for marker in ("429", "rate limit", "rate_limit", "cooldown", "circuit")):
        kind = ProviderOutcomeKind.RATE_LIMITED if "circuit" not in text else ProviderOutcomeKind.CIRCUIT_OPEN
    elif any(marker in text for marker in ("401", "403", "unauthorized", "forbidden", "api key", "authentication")):
        kind = ProviderOutcomeKind.AUTH_ERROR
    elif any(marker in text for marker in ("parse", "decode", "malformed json", "non-object response")):
        kind = ProviderOutcomeKind.PARSE_ERROR
    elif "error" in text or any(marker in text for marker in ("network", "connection", "dns", "unreachable", "reset by peer")):
        kind = ProviderOutcomeKind.NETWORK_ERROR
    elif raw_result_count:
        kind = ProviderOutcomeKind.SUCCESS_WITH_CANDIDATES
    else:
        kind = ProviderOutcomeKind.SUCCESS_EMPTY
    retry_after_seconds = payload.get("retry_after_seconds")
    if retry_after_seconds is None and payload.get("next_eligible_at") is not None:
        try:
            retry_after_seconds = max(0.0, float(payload.get("next_eligible_at")) - time.time())
        except (TypeError, ValueError):
            retry_after_seconds = None
    return build_provider_outcome_v3(
        provider=provider,
        query_variant_id=_text(variant.get("variant_id")),
        outcome=kind,
        attempt=attempt,
        raw_result_count=raw_result_count,
        query_fingerprint=_text(variant.get("query_fingerprint")),
        diagnostic_code=_text(payload.get("failure_kind") or payload.get("status") or kind.value),
        retry_after_seconds=retry_after_seconds,
    )


def execute_provider_variant_with_recovery_v3(
    provider: str,
    variant: Mapping[str, Any],
    dispatch: Callable[[str, Mapping[str, Any]], Any],
    *,
    max_attempts: int = 2,
    zero_result_cache: V3ZeroResultCache | None = DEFAULT_V3_ZERO_RESULT_CACHE,
) -> list[dict[str, Any]]:
    """Execute a V3 query with bounded recovery for typed transient outcomes.

    `INVALID_QUERY` is local and is never submitted or retried.  Transient
    provider outcomes may be retried up to ``max_attempts``.  Only a real,
    definitive successful empty response is stored in the scoped zero cache.
    """

    current = dict(variant) if isinstance(variant, Mapping) else {}
    provider_query = _text(
        current.get("provider_safe_expression")
        or current.get("provider_expression")
        or current.get("query")
    )
    if current.get("schema_version") != RETRIEVAL_QUERY_VARIANT_VERSION or not current.get("dispatch_allowed"):
        outcome = build_provider_outcome_v3(
            provider=provider,
            query_variant_id=_text(current.get("variant_id")) or "invalid_variant",
            outcome=ProviderOutcomeKind.INVALID_QUERY,
            query_fingerprint=_text(current.get("query_fingerprint")),
            diagnostic_code=_text(current.get("skip_reason")) or "INVALID_V3_QUERY_VARIANT",
        )
        return [{
            "provider": provider,
            "query": provider_query,
            "status": "invalid_query",
            "results": [],
            "submitted_to_provider": False,
            "failure_stage": "query_compilation",
            "query_variant_v3": current,
            "provider_outcome_v3": outcome,
        }]
    if zero_result_cache is not None:
        cached = zero_result_cache.get(provider, current)
        if cached:
            outcome = dict(cached.get("provider_outcome_v3") or {})
            return [{
                "provider": provider,
                "query": provider_query,
                "status": "ok",
                "results": [],
                "submitted_to_provider": False,
                "zero_result_cache_hit": True,
                "query_variant_v3": current,
                "provider_outcome_v3": outcome,
            }]
    outputs: list[dict[str, Any]] = []
    for attempt in range(1, max(1, int(max_attempts)) + 1):
        try:
            raw = dispatch(provider_query, current)
            blocks = raw if isinstance(raw, list) else [raw]
        except Exception as exc:  # provider adapter boundary
            blocks = [{
                "provider": provider,
                "query": provider_query,
                "status": "error",
                "error": f"{type(exc).__name__}: {exc}",
                "results": [],
                "submitted_to_provider": True,
            }]
        current_blocks = [
            normalize_provider_dispatch_block_v3(
                provider,
                provider_query,
                block,
            )
            for block in blocks
            if isinstance(block, Mapping)
        ]
        if not current_blocks:
            current_blocks = [{
                "provider": provider,
                "query": provider_query,
                "status": "error",
                "error": "provider returned no result block",
                "results": [],
                "submitted_to_provider": True,
            }]
        outcomes: list[dict[str, Any]] = []
        for block in current_blocks:
            block["query_variant_v3"] = current
            outcome = provider_outcome_from_block_v3(provider, current, block, attempt=attempt)
            block["provider_outcome_v3"] = outcome
            outcomes.append(outcome)
            outputs.append(block)
        if any(outcome["outcome"] in {
            ProviderOutcomeKind.SUCCESS_WITH_CANDIDATES.value,
            ProviderOutcomeKind.SUCCESS_EMPTY.value,
            ProviderOutcomeKind.INVALID_QUERY.value,
            ProviderOutcomeKind.AUTH_ERROR.value,
        } for outcome in outcomes):
            if (
                zero_result_cache is not None
                and outcomes
                and all(outcome["outcome"] == ProviderOutcomeKind.SUCCESS_EMPTY.value for outcome in outcomes)
            ):
                zero_result_cache.put(provider, current, outcomes[0])
            break
        if not outcomes or not all(bool(outcome.get("retryable")) for outcome in outcomes):
            break
    return outputs


def provider_outcome_summary_v3(blocks: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Summarize V3 provider outcomes while retaining retry/error distinction."""

    outcomes = [
        dict(block.get("provider_outcome_v3"))
        for block in blocks
        if isinstance(block, Mapping) and isinstance(block.get("provider_outcome_v3"), Mapping)
    ]
    kinds = [str(outcome.get("outcome") or "") for outcome in outcomes]
    if any(kind == ProviderOutcomeKind.SUCCESS_WITH_CANDIDATES.value for kind in kinds):
        terminal = "RAW_PROVIDER_RESULTS_FOUND"
    elif any(kind in {ProviderOutcomeKind.TIMEOUT.value, ProviderOutcomeKind.RATE_LIMITED.value, ProviderOutcomeKind.NETWORK_ERROR.value, ProviderOutcomeKind.CIRCUIT_OPEN.value, ProviderOutcomeKind.PARSE_ERROR.value} for kind in kinds):
        terminal = "SEARCH_ERROR"
    elif any(kind == ProviderOutcomeKind.INVALID_QUERY.value for kind in kinds):
        terminal = "INVALID_QUERY"
    elif outcomes and all(kind == ProviderOutcomeKind.SUCCESS_EMPTY.value for kind in kinds):
        terminal = "PROVIDER_COVERAGE_COMPLETE_NO_RESULTS"
    else:
        terminal = "NO_PROVIDER_SUBMISSION"
    return {
        "schema_version": "provider_variant_execution_v3",
        "terminal_outcome": terminal,
        "provider_outcomes": outcomes,
        "raw_provider_result_count": sum(int(outcome.get("raw_result_count") or 0) for outcome in outcomes),
        "timeout_count": sum(kind == ProviderOutcomeKind.TIMEOUT.value for kind in kinds),
        "rate_limited_count": sum(kind == ProviderOutcomeKind.RATE_LIMITED.value for kind in kinds),
        "network_error_count": sum(kind == ProviderOutcomeKind.NETWORK_ERROR.value for kind in kinds),
        "invalid_query_count": sum(kind == ProviderOutcomeKind.INVALID_QUERY.value for kind in kinds),
        "provider_coverage_complete": bool(outcomes) and all(
            kind in {
                ProviderOutcomeKind.SUCCESS_EMPTY.value,
                ProviderOutcomeKind.SUCCESS_WITH_CANDIDATES.value,
            }
            for kind in kinds
        ),
        "scientific_evidence_coverage": "NOT_INFERRED_FROM_PROVIDER_OUTCOME",
    }
