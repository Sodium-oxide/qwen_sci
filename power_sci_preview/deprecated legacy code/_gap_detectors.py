"""Contract-scoped, source-bound detector plugins for scientific gaps.

The registry deliberately does not expose a generic assertion-to-gap
converter.  Each enabled detector owns a distinct structural rule and receives
only a ``DetectionContext`` for one ResearchQuestionContract.  This prevents
expected gap priors, global projections, and historical causal artifacts from
becoming hidden candidate factories.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from hashlib import sha256
import copy
import json
import time
from typing import Any, Protocol

try:
    from ._gap_evidence_graph import (
        _normalized_context_source_units,
        create_source_bound_gap_candidate,
    )
    from ._gap_types import GapSignalType, GapType, contract_for
    from ._research_graph import (
        DETECTION_CONTEXT_SCHEMA_VERSION,
        DetectionContext,
        RESEARCH_EVIDENCE_GRAPH_SCHEMA_VERSION,
        _prevalidated_detection_contexts_scope,
        _validated_detection_context_for_runtime,
        build_contract_detection_contexts_v3,
        detection_context_validation_scope,
        detection_context_ref,
        detector_input_fingerprint,
        detector_result_fingerprint,
        graph_snapshot_ref,
        validate_detection_context,
    )
except ImportError:
    from _gap_evidence_graph import (
        _normalized_context_source_units,
        create_source_bound_gap_candidate,
    )
    from _gap_types import GapSignalType, GapType, contract_for
    from _research_graph import (
        DETECTION_CONTEXT_SCHEMA_VERSION,
        DetectionContext,
        RESEARCH_EVIDENCE_GRAPH_SCHEMA_VERSION,
        _prevalidated_detection_contexts_scope,
        _validated_detection_context_for_runtime,
        build_contract_detection_contexts_v3,
        detection_context_validation_scope,
        detection_context_ref,
        detector_input_fingerprint,
        detector_result_fingerprint,
        graph_snapshot_ref,
        validate_detection_context,
    )


GAP_DETECTOR_RESULT_SCHEMA_VERSION = "gap_detector_result_v3"
GAP_DETECTOR_REGISTRY_RUN_SCHEMA_VERSION = "gap_detector_registry_run_v3"
REJECTION_SUMMARY_SCHEMA_VERSION = "detector_rejection_summary_v3"
REJECTION_EXAMPLE_LIMIT = 20
DEFAULT_DETECTOR_WORKERS = 12
MAX_AUDIT_CANDIDATES_PER_TYPE_CONTRACT = 6
DETECTOR_CANDIDATE_RETENTION_POLICY_VERSION = "detector_candidate_retention_v3"
DETECTOR_RESULT_REFERENCE_ARTIFACT_SCHEMA_VERSION = (
    "gap_detector_result_reference_artifact_v4"
)
DETECTOR_CANDIDATE_REFERENCE_MODE = "DETECTION_CONTEXT_REFERENCE_V3"
FAIR_AUDIT_FRONTIER_SCHEMA_VERSION = "fair_gap_audit_frontier_v3"
AUDIT_FRONTIER_CURSOR_SCHEMA_VERSION = "gap_audit_continuation_cursor_v3"


_DETECTOR_WORKER_CONTEXT_CACHE: dict[tuple[str, str, str], DetectionContext] = {}


def _text(value: Any) -> str:
    return " ".join(str(value or "").split())


def _key(value: Any) -> str:
    return _text(value).casefold()


def _ids(values: Any) -> list[str]:
    if not isinstance(values, (list, tuple, set)):
        return []
    return sorted({_text(item) for item in values if _text(item)})


class _BoundedRejectionPatterns:
    """Count every rejection while retaining only deterministic examples.

    A detector result needs auditable rejection reasons, not one materialized
    Python dictionary per rejected pair.  This collector keeps the complete
    reason counts and a bounded sample for diagnosis.  Its ``append`` surface
    intentionally mirrors ``list`` so detector rules cannot accidentally
    bypass the result-size policy.
    """

    def __init__(self, *, example_limit: int = REJECTION_EXAMPLE_LIMIT) -> None:
        self.example_limit = max(1, int(example_limit))
        self._counts: Counter[str] = Counter()
        self._examples: dict[str, list[dict[str, Any]]] = defaultdict(list)

    def append(self, item: dict[str, Any]) -> None:
        payload = dict(item) if isinstance(item, dict) else {
            "pattern_id": "UNSTRUCTURED_REJECTION",
            "reason": _text(item),
        }
        pattern_id = _text(payload.get("pattern_id")) or "UNSPECIFIED_REJECTION"
        self._counts[pattern_id] += 1
        examples = self._examples[pattern_id]
        if len(examples) < self.example_limit:
            examples.append(payload)

    def __iter__(self):
        for pattern_id in sorted(self._examples):
            yield from self._examples[pattern_id]

    def __len__(self) -> int:
        return sum(self._counts.values())

    def summary(self) -> dict[str, Any]:
        total = len(self)
        sample_count = sum(len(items) for items in self._examples.values())
        return {
            "schema_version": REJECTION_SUMMARY_SCHEMA_VERSION,
            "reason_counts": {
                pattern_id: int(count)
                for pattern_id, count in sorted(self._counts.items())
            },
            "total_rejection_count": total,
            "retained_example_count": sample_count,
            "truncated_rejection_record_count": max(0, total - sample_count),
            "example_limit_per_reason": self.example_limit,
            "interpretation": (
                "Counts describe screened detector patterns only; truncated "
                "rejections never establish absence of a scientific gap."
            ),
        }


def _compact_rejection_patterns(
    values: Any,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if isinstance(values, _BoundedRejectionPatterns):
        return list(values), values.summary()
    collector = _BoundedRejectionPatterns()
    for item in values if isinstance(values, list) else []:
        if isinstance(item, dict):
            collector.append(item)
    return list(collector), collector.summary()


def _merge_rejection_summaries(
    results: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    collector = _BoundedRejectionPatterns()
    for result in results:
        if not isinstance(result, dict):
            continue
        summary = result.get("rejection_summary")
        samples = result.get("rejected_patterns")
        if not isinstance(summary, dict):
            for item in samples if isinstance(samples, list) else []:
                if isinstance(item, dict):
                    collector.append(item)
            continue
        sample_by_pattern: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for item in samples if isinstance(samples, list) else []:
            if isinstance(item, dict):
                pattern_id = _text(item.get("pattern_id")) or "UNSPECIFIED_REJECTION"
                sample_by_pattern[pattern_id].append(dict(item))
        for pattern_id, count in (summary.get("reason_counts") or {}).items():
            normalized_pattern = _text(pattern_id) or "UNSPECIFIED_REJECTION"
            normalized_count = max(0, int(count or 0))
            collector._counts[normalized_pattern] += normalized_count
            examples = collector._examples[normalized_pattern]
            for item in sample_by_pattern.get(normalized_pattern, []):
                if len(examples) >= collector.example_limit:
                    break
                examples.append(item)
    return list(collector), collector.summary()


def _candidate_retention_key(candidate: dict[str, Any]) -> tuple[int, int, int, int, str]:
    """Return a deterministic evidence-first ranking for retained leads.

    This is a storage and downstream-work budget only.  It never reclassifies
    discarded source-bound candidates as scientifically absent; the result
    explicitly records a continuation state whenever the bound is reached.
    """

    units = [
        item
        for item in candidate.get("source_evidence_units", [])
        if isinstance(item, dict)
    ]
    explicit_unit_count = sum(
        1
        for item in units
        if _status(item.get("textual_explicitness")) == "EXPLICIT"
        and _status(item.get("assertion_origin")) in {"", "SOURCE_EXPLICIT"}
        and _status(item.get("derivation_status")) in {"", "NOT_DERIVED"}
    )
    primary_paper_count = len(
        {
            _text(item.get("paper_id"))
            for item in units
            if _text(item.get("paper_id"))
            and _key(item.get("evidence_role")) in {
                "primary_study",
                "primary",
                "primary_source",
            }
        }
    )
    distinct_paper_count = len(
        {_text(item.get("paper_id")) for item in units if _text(item.get("paper_id"))}
    )
    payload_completeness = sum(
        1
        for value in (candidate.get("type_payload") or {}).values()
        if (bool(value) if isinstance(value, (dict, list, tuple, set)) else bool(_text(value)))
    )
    return (
        -explicit_unit_count,
        -primary_paper_count,
        -distinct_paper_count,
        -payload_completeness,
        _text(candidate.get("candidate_identity")),
    )


def _retain_detector_candidates(
    candidates: list[dict[str, Any]],
    *,
    limit: int | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any], list[dict[str, Any]]]:
    """Retain the full deduplicated frontier for later type-scoped auditing."""

    deduped = _dedupe_candidates(candidates)
    ordered = sorted(deduped, key=_candidate_retention_key)
    normalized_limit = max(1, int(limit)) if limit is not None else None
    selected = ordered if normalized_limit is None else ordered[:normalized_limit]
    overflow_count = max(0, len(ordered) - len(selected))
    summary = {
        "schema_version": "detector_candidate_retention_v3",
        "policy_version": DETECTOR_CANDIDATE_RETENTION_POLICY_VERSION,
        "candidate_limit": normalized_limit,
        "total_candidate_count": len(ordered),
        "selected_candidate_count": len(selected),
        "overflow_candidate_count": overflow_count,
        "overflow_status": (
            "CANDIDATE_BUDGET_EXHAUSTED" if overflow_count else "NOT_EXHAUSTED"
        ),
        "continuation_cursor": (
            _text(selected[-1].get("candidate_identity")) if overflow_count else ""
        ),
        "scientific_conclusion_allowed": overflow_count == 0,
        "interpretation": (
            "An exhausted candidate budget preserves a deterministic frontier "
            "only; it never establishes that no additional scientific gap exists."
        ),
    }
    diagnostics: list[dict[str, Any]] = []
    if overflow_count:
        diagnostics.append(
            {
                "stage": "CANDIDATE_RETENTION",
                "reason": "CANDIDATE_BUDGET_EXHAUSTED",
                "candidate_limit": normalized_limit,
                "overflow_candidate_count": overflow_count,
                "continuation_cursor": summary["continuation_cursor"],
                "scientific_conclusion_allowed": False,
            }
        )
    return selected, summary, diagnostics


def _dedupe_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    seen: set[str] = set()
    for candidate in candidates:
        identity = _text(candidate.get("candidate_identity"))
        if not identity or identity in seen:
            continue
        seen.add(identity)
        output.append(candidate)
    return sorted(output, key=lambda item: _text(item.get("candidate_identity")))


def select_fair_audit_frontier_v3(
    candidates: list[dict[str, Any]],
    *,
    per_type_contract_budget: int = MAX_AUDIT_CANDIDATES_PER_TYPE_CONTRACT,
    resume_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Select the next bounded V3 audit frontier without dropping leads.

    A cursor is accepted only when it matches the exact current candidate
    ordering, contract revisions, graph snapshots, and per-bucket budget.
    This lets a later TanXi invocation continue after a completed batch while
    refusing to advance stale evidence or a changed contract.
    """

    budget = max(
        1,
        min(MAX_AUDIT_CANDIDATES_PER_TYPE_CONTRACT, int(per_type_contract_budget)),
    )
    buckets: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for candidate in _dedupe_candidates(candidates):
        assessment = (
            candidate.get("gap_assessment")
            if isinstance(candidate.get("gap_assessment"), dict)
            else {}
        )
        context_ref = (
            candidate.get("detection_context_ref")
            if isinstance(candidate.get("detection_context_ref"), dict)
            else {}
        )
        gap_type = _text(candidate.get("gap_type") or assessment.get("gap_type"))
        contract_id = _text(
            context_ref.get("research_question_contract_id")
            or (candidate.get("research_question_contract") or {}).get("contract_id")
        )
        if not gap_type or not contract_id:
            raise ValueError("FAIR_AUDIT_FRONTIER_REQUIRES_TYPE_AND_CONTRACT")
        buckets[(gap_type, contract_id)].append(candidate)

    frontier_input = {
        "schema_version": FAIR_AUDIT_FRONTIER_SCHEMA_VERSION,
        "per_type_contract_budget": budget,
        "buckets": [
            {
                "gap_type": gap_type,
                "research_question_contract_id": contract_id,
                "candidates": [
                    {
                        "candidate_identity": _text(
                            item.get("candidate_identity") or item.get("gap_id")
                        ),
                        "contract_revision": _text(
                            (item.get("detection_context_ref") or {}).get(
                                "contract_revision"
                            )
                            if isinstance(item.get("detection_context_ref"), dict)
                            else ""
                        ),
                        "graph_snapshot_id": _text(
                            (item.get("detection_context_ref") or {}).get(
                                "graph_snapshot_id"
                            )
                            if isinstance(item.get("detection_context_ref"), dict)
                            else ""
                        ),
                        "detector_input_fingerprint": _text(
                            (item.get("detection_context_ref") or {}).get(
                                "detector_input_fingerprint"
                            )
                            if isinstance(item.get("detection_context_ref"), dict)
                            else ""
                        ),
                    }
                    for item in sorted(
                        bucket,
                        key=lambda item: _text(
                            item.get("candidate_identity") or item.get("gap_id")
                        ),
                    )
                ],
            }
            for (gap_type, contract_id), bucket in sorted(buckets.items())
        ],
    }
    frontier_input_fingerprint = "sha256:" + sha256(
        json.dumps(
            frontier_input,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    supplied_resume_state = resume_state if isinstance(resume_state, dict) else {}
    resume_positions: dict[str, int] = {}
    resume_validation = {"status": "NOT_PROVIDED", "reason_code": ""}
    if supplied_resume_state:
        if (
            _text(supplied_resume_state.get("schema_version"))
            != AUDIT_FRONTIER_CURSOR_SCHEMA_VERSION
        ):
            resume_validation = {
                "status": "REJECTED",
                "reason_code": "AUDIT_FRONTIER_CURSOR_SCHEMA_V3_REQUIRED",
            }
        elif (
            _text(supplied_resume_state.get("frontier_input_fingerprint"))
            != frontier_input_fingerprint
        ):
            resume_validation = {
                "status": "REJECTED",
                "reason_code": "STALE_OR_CHANGED_AUDIT_FRONTIER_CURSOR",
            }
        else:
            raw_positions = supplied_resume_state.get("next_position_by_bucket")
            bucket_sizes = {
                gap_type + "|" + contract_id: len(bucket)
                for (gap_type, contract_id), bucket in buckets.items()
            }
            if not isinstance(raw_positions, dict):
                resume_validation = {
                    "status": "REJECTED",
                    "reason_code": "AUDIT_FRONTIER_CURSOR_POSITIONS_REQUIRED",
                }
            else:
                valid = True
                for bucket_key, raw_position in raw_positions.items():
                    if str(bucket_key) not in bucket_sizes:
                        valid = False
                        break
                    try:
                        position = int(raw_position)
                    except (TypeError, ValueError):
                        valid = False
                        break
                    if position < 0 or position > bucket_sizes[str(bucket_key)]:
                        valid = False
                        break
                    resume_positions[str(bucket_key)] = position
                resume_validation = (
                    {"status": "CURRENT", "reason_code": ""}
                    if valid
                    else {
                        "status": "REJECTED",
                        "reason_code": "INVALID_AUDIT_FRONTIER_CURSOR_POSITION",
                    }
                )
                if not valid:
                    resume_positions = {}

    selected: list[dict[str, Any]] = []
    continuation_frontier: list[dict[str, Any]] = []
    next_position_by_bucket: dict[str, int] = {}
    for (gap_type, contract_id), bucket in sorted(buckets.items()):
        bucket.sort(key=lambda item: _text(item.get("candidate_identity") or item.get("gap_id")))
        bucket_key = gap_type + "|" + contract_id
        prior_position = int(resume_positions.get(bucket_key) or 0)
        selected_until = min(len(bucket), prior_position + budget)
        next_position_by_bucket[bucket_key] = selected_until
        for position, candidate in enumerate(bucket, start=1):
            candidate_identity = _text(candidate.get("candidate_identity") or candidate.get("gap_id"))
            selected_for_audit = prior_position < position <= selected_until
            if selected_for_audit:
                selected.append(candidate)
            selection_status = (
                "ALREADY_AUDITED"
                if position <= prior_position
                else "SELECTED_FOR_SEMANTIC_AUDIT"
                if selected_for_audit
                else "DEFERRED_PENDING_AUDIT_BUDGET"
            )
            continuation_frontier.append(
                {
                    "schema_version": "gap_audit_continuation_frontier_v3",
                    "candidate_identity": candidate_identity,
                    "gap_type": gap_type,
                    "research_question_contract_id": contract_id,
                    "queue_position": position,
                    "selection_status": selection_status,
                    "resume_cursor": (
                        "audit_frontier:" + gap_type + ":" + contract_id + ":" + str(position)
                    ),
                }
            )
    return {
        "schema_version": FAIR_AUDIT_FRONTIER_SCHEMA_VERSION,
        "per_type_contract_budget": budget,
        "selected_candidates": selected,
        "continuation_frontier": continuation_frontier,
        "resume_validation": resume_validation,
        "resume_state_v3": {
            "schema_version": AUDIT_FRONTIER_CURSOR_SCHEMA_VERSION,
            "frontier_input_fingerprint": frontier_input_fingerprint,
            "next_position_by_bucket": next_position_by_bucket,
        },
        "candidate_count_by_bucket": {
            gap_type + "|" + contract_id: len(bucket)
            for (gap_type, contract_id), bucket in sorted(buckets.items())
        },
    }


def _assertion_kinds(assertion: dict[str, Any]) -> set[str]:
    return {_text(item).upper() for item in assertion.get("assertion_kinds", []) if _text(item)}


def _scope(context: DetectionContext, assertion: dict[str, Any]) -> dict[str, str]:
    declared = context.research_question_contract.get("scientific_scope")
    declared = declared if isinstance(declared, dict) else {}
    source_scope = assertion.get("scope_tuple")
    source_scope = source_scope if isinstance(source_scope, dict) else {}
    return {
        key: _text(source_scope.get(key) or declared.get(key))
        for key in set(declared) | set(source_scope)
        if _text(source_scope.get(key) or declared.get(key))
    }


def _first_text(*values: Any) -> str:
    for value in values:
        if _text(value):
            return _text(value)
    return ""


def _relation_paths(context: DetectionContext) -> list[dict[str, Any]]:
    """Read source-explicit relation paths without inferring absent endpoints."""

    paths: list[dict[str, Any]] = []
    for assertion in context.assertions:
        if not isinstance(assertion, dict):
            continue
        assertion_id = _text(assertion.get("assertion_id"))
        if not assertion_id:
            continue
        scope = _scope(context, assertion)
        for relation in context.relation_index.get(assertion_id, []):
            if not isinstance(relation, dict):
                continue
            subject = _first_text(
                relation.get("subject_label"),
                assertion.get("subject"),
                (assertion.get("normalization") or {}).get("subject")
                if isinstance(assertion.get("normalization"), dict) else "",
                scope.get("intervention_or_exposure"),
            )
            outcome = _first_text(
                relation.get("object_label"),
                assertion.get("object"),
                (assertion.get("normalization") or {}).get("object")
                if isinstance(assertion.get("normalization"), dict) else "",
                scope.get("outcome_definition"),
            )
            predicate = _first_text(relation.get("predicate"), assertion.get("predicate"), assertion.get("relation_kind"))
            if not subject or not outcome or not predicate:
                continue
            mechanism = _first_text(
                assertion.get("mechanism"),
                assertion.get("mechanism_role"),
                assertion.get("mediator"),
                assertion.get("mechanism_path"),
                relation.get("mechanism"),
            )
            paths.append(
                {
                    "assertion_id": assertion_id,
                    "relation_id": _text(relation.get("node_id")),
                    "paper_id": _text(assertion.get("paper_id")),
                    "input": subject,
                    "outcome": outcome,
                    "predicate": predicate,
                    "mechanism": mechanism,
                    "scope": scope,
                    "assertion": assertion,
                }
            )
    return paths


def _scope_signature(path: dict[str, Any]) -> tuple[tuple[str, str], ...]:
    return tuple(sorted((str(key), _key(value)) for key, value in (path.get("scope") or {}).items() if _text(value)))


def _comparability_ids(context: DetectionContext) -> list[str]:
    return sorted(context.comparability_index)


def _contexts_are_comparable(
    context: DetectionContext,
    left: dict[str, Any],
    right: dict[str, Any],
) -> bool:
    comparable, _ = _comparability_for_pair(context, left, right)
    return comparable


def _has_identification_design(assertion: dict[str, Any]) -> bool:
    design_fields = (
        "identification_design",
        "identification_strategy",
        "causal_design",
        "intervention_design",
        "experimental_design",
    )
    for field_name in design_fields:
        value = assertion.get(field_name)
        if isinstance(value, dict) and value:
            return True
        if _text(value):
            return True
    study_design = assertion.get("study_design")
    if isinstance(study_design, dict):
        return any(
            bool(study_design.get(field_name))
            for field_name in (
                "is_interventional",
                "intervention",
                "identification_strategy",
                "design_type",
            )
        )
    if _text(study_design):
        return True
    return bool(
        _assertion_kinds(assertion)
        & {"INTERVENTION_RESULT", "EXPERIMENTAL_DESIGN", "QUASI_EXPERIMENTAL_DESIGN"}
    )


def _is_association_or_unsupported_causal_claim(path: dict[str, Any]) -> bool:
    assertion = path["assertion"]
    predicate = _key(path.get("predicate"))
    kinds = _assertion_kinds(assertion)
    relation_tokens = (
        "associate",
        "correlat",
        "predict",
        "related",
        "affect",
        "effect",
        "cause",
        "influence",
    )
    if not any(token in predicate for token in relation_tokens) and "CAUSAL_CLAIM" not in kinds:
        return False
    temporal_only = {"PRECEDES", "FOLLOWS", "TEMPORAL_SEQUENCE", "TEMPORAL_ASSOCIATION"}
    return not (kinds & temporal_only) and "temporal" not in predicate


def _author_limitation_text(assertion: dict[str, Any]) -> str:
    return _first_text(
        assertion.get("limitation_statement"),
        assertion.get("author_stated_unknown"),
        assertion.get("object"),
        assertion.get("predicate"),
    )


def _has_direct_slot_support(assertion: dict[str, Any]) -> bool:
    coverage = assertion.get("slot_coverage")
    if isinstance(coverage, dict) and any(value is True for value in coverage.values()):
        return True
    return any(
        isinstance(item, dict)
        and _text(item.get("support_status")) == "VERIFIED_NONCOUNTING"
        and _text(item.get("slot_id")) in {
            _text(slot) for slot in assertion.get("admitted_slot_ids_v4") or []
        }
        for item in assertion.get("slot_support") or []
    )


_SOURCE_STRUCTURED_CONTAINERS = (
    "structured_fields",
    "structured_claim",
    "measurement",
    "formal_structure",
    "generalization",
    "method_assessment",
    "data_coverage",
    "scale_context",
    "comparison",
    "translation",
)


def _structured_value(assertion: dict[str, Any], *field_names: str) -> Any:
    """Read explicitly extracted fields, never text-derived substitutes.

    The assertion record is the source-bound extraction boundary. Supporting
    more than one structured container makes detector inputs stable as the
    extractor groups fields by semantic family; it does not adapt historic
    project state or infer a missing fact from free text.
    """

    for field_name in field_names:
        if field_name in assertion and assertion.get(field_name) is not None:
            value = assertion.get(field_name)
            if isinstance(value, (dict, list, tuple, set)) and not value:
                continue
            if not isinstance(value, (dict, list, tuple, set)) and not _text(value):
                continue
            return value
    for container_name in _SOURCE_STRUCTURED_CONTAINERS:
        container = assertion.get(container_name)
        if not isinstance(container, dict):
            continue
        for field_name in field_names:
            if field_name not in container or container.get(field_name) is None:
                continue
            value = container.get(field_name)
            if isinstance(value, (dict, list, tuple, set)) and not value:
                continue
            if not isinstance(value, (dict, list, tuple, set)) and not _text(value):
                continue
            return value
    return ""


def _structured_text(assertion: dict[str, Any], *field_names: str) -> str:
    value = _structured_value(assertion, *field_names)
    if isinstance(value, (list, tuple, set)):
        return "; ".join(_text(item) for item in value if _text(item))
    return _text(value)


def _structured_values(assertion: dict[str, Any], *field_names: str) -> list[str]:
    value = _structured_value(assertion, *field_names)
    if isinstance(value, dict):
        return _ids(value.values())
    if isinstance(value, (list, tuple, set)):
        return _ids(value)
    return [_text(value)] if _text(value) else []


def _status(value: Any) -> str:
    return _key(value).replace("-", "_").replace(" ", "_").upper()


def _is_explicitly_confirmed(value: Any) -> bool:
    return _status(value) in {
        "VALIDATED",
        "CONFIRMED",
        "CALIBRATED",
        "SUPPORTED",
        "PASS",
        "PASSES",
        "ESTABLISHED",
        "AVAILABLE",
        "YES",
        "TRUE",
    } or value is True


def _is_explicitly_unresolved(value: Any) -> bool:
    return _status(value) in {
        "UNKNOWN",
        "UNTESTED",
        "UNVALIDATED",
        "UNRESOLVED",
        "MISSING",
        "NOT_ESTABLISHED",
        "NOT_VALIDATED",
        "NOT_AVAILABLE",
        "UNAVAILABLE",
        "ABSENT",
        "FALSE",
        "NO",
    } or value is False


def _relation_family(path: dict[str, Any]) -> str:
    assertion = path["assertion"]
    return _first_text(
        _structured_text(assertion, "relation_family", "claim_family", "relation_class"),
        path.get("predicate"),
    )


def _same_relation_target(left: dict[str, Any], right: dict[str, Any]) -> bool:
    if _key(left.get("input")) != _key(right.get("input")):
        return False
    if _key(left.get("outcome")) != _key(right.get("outcome")):
        return False
    left_family = _relation_family(left)
    right_family = _relation_family(right)
    return not left_family or not right_family or _key(left_family) == _key(right_family)


def _comparison_reference_ids(item: dict[str, Any]) -> set[str]:
    values: list[Any] = []
    for field_name in (
        "compared_relation_assertion_ids",
        "relation_assertion_ids",
        "compared_assertion_ids",
        "assertion_ids",
    ):
        value = item.get(field_name)
        if isinstance(value, (list, tuple, set)):
            values.extend(value)
    for field_name in (
        "left_relation_assertion_id",
        "right_relation_assertion_id",
        "left_assertion_id",
        "right_assertion_id",
    ):
        values.append(item.get(field_name))
    return {_text(value) for value in values if _text(value)}


def _comparability_for_pair(
    context: DetectionContext,
    left: dict[str, Any],
    right: dict[str, Any],
) -> tuple[bool, list[str]]:
    """Return a pair-specific comparability verdict and its source node IDs."""

    if _scope_signature(left) == _scope_signature(right):
        return True, []
    required_ids = {
        _text(left.get("relation_id")),
        _text(right.get("relation_id")),
        _text(left.get("assertion_id")),
        _text(right.get("assertion_id")),
    }
    required_ids.discard("")
    accepted = {"COMPARABLE", "ALIGNED", "PASS", "SUPPORTED"}
    relation_ids = {_text(left.get("relation_id")), _text(right.get("relation_id"))}
    relation_ids.discard("")
    for assessment_id, item in context.comparability_index.items():
        if not isinstance(item, dict) or _status(item.get("verdict")) not in accepted:
            continue
        referenced = _comparison_reference_ids(item)
        if required_ids.issubset(referenced) or (relation_ids and relation_ids.issubset(referenced)):
            return True, [_text(assessment_id)]
    return False, []


def _indexed_relation_path_pairs(
    context: DetectionContext,
    paths: list[dict[str, Any]],
) -> list[tuple[dict[str, Any], dict[str, Any], list[str]]]:
    """Resolve only graph-planned, source-bound comparison pairs.

    Pair-oriented detectors must not rediscover an unbounded Cartesian product
    after ResearchGraph V3 has already selected its auditable comparability
    pairs.  The graph assessment is the authoritative pair admission record.
    """

    by_relation_id = {
        _text(item.get("relation_id")): item
        for item in paths
        if _text(item.get("relation_id"))
    }
    by_assertion_id = {
        _text(item.get("assertion_id")): item
        for item in paths
        if _text(item.get("assertion_id"))
    }
    accepted = {"COMPARABLE", "ALIGNED", "PASS", "SUPPORTED"}
    selected: list[tuple[dict[str, Any], dict[str, Any], list[str]]] = []
    seen: set[tuple[str, str]] = set()
    for assessment_id, assessment in sorted(context.comparability_index.items()):
        if not isinstance(assessment, dict) or _status(assessment.get("verdict")) not in accepted:
            continue
        matches: dict[str, dict[str, Any]] = {}
        for reference_id in _comparison_reference_ids(assessment):
            path = by_relation_id.get(reference_id) or by_assertion_id.get(reference_id)
            if isinstance(path, dict):
                matches[_text(path.get("assertion_id"))] = path
        if len(matches) != 2:
            continue
        left, right = sorted(
            matches.values(), key=lambda item: _text(item.get("assertion_id"))
        )
        identity = (_text(left.get("assertion_id")), _text(right.get("assertion_id")))
        if not all(identity) or identity in seen:
            continue
        seen.add(identity)
        selected.append((left, right, [_text(assessment_id)]))
    return selected


def _indexed_assertion_record_pairs(
    context: DetectionContext,
    records: list[dict[str, Any]],
) -> list[tuple[dict[str, Any], dict[str, Any], list[str]]]:
    """Resolve graph-planned comparable pairs for non-relation detector records."""

    by_assertion_id = {
        _text(item.get("assertion_id")): item
        for item in records
        if _text(item.get("assertion_id"))
    }
    by_reference_id = dict(by_assertion_id)
    for assertion_id, record in by_assertion_id.items():
        for relation in context.relation_index.get(assertion_id, []):
            if not isinstance(relation, dict):
                continue
            relation_id = _text(relation.get("node_id"))
            if relation_id:
                by_reference_id[relation_id] = record
    accepted = {"COMPARABLE", "ALIGNED", "PASS", "SUPPORTED"}
    selected: list[tuple[dict[str, Any], dict[str, Any], list[str]]] = []
    seen: set[tuple[str, str]] = set()
    for assessment_id, assessment in sorted(context.comparability_index.items()):
        if not isinstance(assessment, dict) or _status(assessment.get("verdict")) not in accepted:
            continue
        matches = {
            _text(by_reference_id[reference_id].get("assertion_id")): by_reference_id[reference_id]
            for reference_id in _comparison_reference_ids(assessment)
            if reference_id in by_reference_id
        }
        if len(matches) != 2:
            continue
        left, right = sorted(
            matches.values(), key=lambda item: _text(item.get("assertion_id"))
        )
        identity = (_text(left.get("assertion_id")), _text(right.get("assertion_id")))
        if not all(identity) or identity in seen:
            continue
        seen.add(identity)
        selected.append((left, right, [_text(assessment_id)]))
    return selected


def _first_same_relation_pair(
    paths: list[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    """Return one deterministic diagnostic pair without materializing all pairs."""

    buckets: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for path in paths:
        key = (
            _key(path.get("input")),
            _key(path.get("outcome")),
            _key(_relation_family(path)),
        )
        if all(key):
            buckets[key].append(path)
    for members in (buckets[key] for key in sorted(buckets)):
        ordered = sorted(members, key=lambda item: _text(item.get("assertion_id")))
        if len(ordered) >= 2:
            return ordered[0], ordered[1]
    return None


def _append_source_bound_candidate(
    candidates: list[dict[str, Any]],
    rejected: list[dict[str, Any]],
    *,
    context: DetectionContext,
    gap_type: GapType,
    gap_subtype: str,
    signal_type: GapSignalType,
    assertion_ids: list[str],
    type_payload: dict[str, Any],
    detection_witness: dict[str, Any],
    description: str,
    detector_id: str,
    detector_policy_version: str,
    rejection_pattern_id: str,
) -> None:
    """Use the V3 factory while retaining a detector-visible rejection cause."""

    try:
        candidates.append(
            create_source_bound_gap_candidate(
                context=context,
                gap_type=gap_type,
                gap_subtype=gap_subtype,
                signal_type=signal_type,
                assertion_ids=assertion_ids,
                type_payload=type_payload,
                detection_witness=detection_witness,
                description=description,
                detector_id=detector_id,
                detector_policy_version=detector_policy_version,
            )
        )
    except ValueError as exc:
        rejected.append(
            {
                "pattern_id": rejection_pattern_id,
                "reason": str(exc),
                "assertion_ids": sorted({_text(item) for item in assertion_ids if _text(item)}),
            }
        )


def _path_condition(path: dict[str, Any]) -> str:
    assertion = path["assertion"]
    return _first_text(
        _structured_text(assertion, "condition", "condition_or_regime", "regime"),
        (path.get("scope") or {}).get("condition_or_regime"),
    )


def _effect_direction(path: dict[str, Any]) -> str:
    assertion = path["assertion"]
    value = _structured_text(
        assertion,
        "effect_direction",
        "result_direction",
        "claim_polarity",
        "polarity",
        "evidence_polarity",
    )
    normalized = _key(value)
    if normalized in {"positive", "increase", "increases", "supportive", "up", "+"}:
        return "POSITIVE"
    if normalized in {"negative", "decrease", "decreases", "opposing", "down", "-"}:
        return "NEGATIVE"
    return ""


def _relation_description(path: dict[str, Any]) -> str:
    return " → ".join(
        value for value in (path.get("input"), path.get("predicate"), path.get("outcome")) if _text(value)
    )


class GapDetector(Protocol):
    gap_type: GapType
    detector_policy_version: str

    def preflight(self, context: DetectionContext) -> dict[str, Any]:
        ...

    def detect(self, context: DetectionContext) -> dict[str, Any]:
        ...


class EvidenceGraphGapDetector:
    """Base for real type-specific detectors, not an assertion-kind filter."""

    gap_type: GapType
    detector_policy_version = "detector_base_v1"
    implemented = False

    @property
    def detector_id(self) -> str:
        return self.gap_type.value

    def preflight(self, context: DetectionContext) -> dict[str, Any]:
        current = _validated_detection_context_for_runtime(context)
        contract = contract_for(self.gap_type)
        return {
            "schema_version": "gap_detector_preflight_v3",
            "passes": True,
            "detector_id": self.detector_id,
            "detector_policy_version": self.detector_policy_version,
            "research_question_contract_id": current.research_question_contract["contract_id"],
            "assertion_count_in_view": len(current.assertions),
            "relation_path_count": len(_relation_paths(current)),
            "minimum_source_units": contract.discovery_spec.minimum_source_units,
            "minimum_distinct_papers": contract.discovery_spec.minimum_distinct_papers,
        }

    def _scan(
        self,
        context: DetectionContext,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
        return [], [
            {
                "pattern_id": "DETECTOR_NOT_IMPLEMENTED",
                "reason": "TYPE_SPECIFIC_DETECTOR_NOT_IMPLEMENTED",
                "gap_type": self.gap_type.value,
            }
        ], []

    def _result(
        self,
        context: DetectionContext,
        *,
        candidates: list[dict[str, Any]],
        rejected_patterns: list[dict[str, Any]],
        diagnostics: list[dict[str, Any]],
        preflight: dict[str, Any],
    ) -> dict[str, Any]:
        retained_candidates, retention_summary, retention_diagnostics = (
            _retain_detector_candidates(candidates)
        )
        compact_rejections, rejection_summary = _compact_rejection_patterns(
            rejected_patterns
        )
        result_diagnostics = [
            item for item in diagnostics if isinstance(item, dict)
        ] + retention_diagnostics
        result = {
            "schema_version": GAP_DETECTOR_RESULT_SCHEMA_VERSION,
            "detector_id": self.detector_id,
            "detector_policy_version": self.detector_policy_version,
            "gap_type": self.gap_type.value,
            "detection_context_ref": detection_context_ref(context),
            "detector_input_fingerprint": detector_input_fingerprint(
                context,
                detector_id=self.detector_id,
                detector_policy_version=self.detector_policy_version,
            ),
            "preflight": preflight,
            "candidates": retained_candidates,
            "rejected_patterns": compact_rejections,
            "rejection_summary": rejection_summary,
            "candidate_retention": retention_summary,
            "coverage_summary": {
                "assertion_count_in_view": len(context.assertions),
                "relation_path_count": len(_relation_paths(context)),
                "candidate_count": len(retained_candidates),
                "total_candidate_count": int(
                    retention_summary.get("total_candidate_count") or 0
                ),
                "overflow_candidate_count": int(
                    retention_summary.get("overflow_candidate_count") or 0
                ),
                "rejected_pattern_count": int(
                    rejection_summary.get("total_rejection_count") or 0
                ),
                "retained_rejection_example_count": len(compact_rejections),
                "slot_coverage_ledger": context.slot_coverage_ledger,
            },
            "diagnostics": result_diagnostics,
        }
        result["detector_result_fingerprint"] = detector_result_fingerprint(
            context,
            detector_id=self.detector_id,
            detector_policy_version=self.detector_policy_version,
            candidate_identities=[
                item["candidate_identity"] for item in retained_candidates
            ],
            rejected_pattern_ids=[
                f"{pattern_id}:{count}"
                for pattern_id, count in (
                    rejection_summary.get("reason_counts") or {}
                ).items()
            ],
            diagnostic_ids=[
                DETECTOR_CANDIDATE_RETENTION_POLICY_VERSION,
                *[_text(item.get("reason")) for item in result_diagnostics],
            ],
        )
        return result

    def detect(self, context: DetectionContext) -> dict[str, Any]:
        with detection_context_validation_scope(context) as current:
            preflight = self.preflight(current)
            candidates, rejected_patterns, diagnostics = self._scan(current)
            return self._result(
                current,
                candidates=candidates,
                rejected_patterns=rejected_patterns,
                diagnostics=diagnostics,
                preflight=preflight,
            )


class AuthorStatedLimitationDetector(EvidenceGraphGapDetector):
    gap_type = GapType.AUTHOR_STATED_LIMITATION
    detector_policy_version = "author_stated_limitation_v3"
    implemented = True

    def _scan(self, context: DetectionContext) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
        candidates: list[dict[str, Any]] = []
        rejected: list[dict[str, Any]] = []
        diagnostics: list[dict[str, Any]] = []
        for assertion in context.assertions:
            if not isinstance(assertion, dict):
                continue
            assertion_id = _text(assertion.get("assertion_id"))
            kinds = _assertion_kinds(assertion)
            if "AUTHOR_LIMITATION" not in kinds:
                continue
            attribution = _text(assertion.get("attribution")).upper()
            epistemic_basis = _text(assertion.get("epistemic_basis")).upper()
            if not (
                attribution in {"AUTHOR_LIMITATION", "AUTHOR_STATED", "AUTHOR_ASSERTED"}
                or epistemic_basis in {"AUTHOR_STATED_UNKNOWN", "AUTHOR_ASSERTED"}
            ):
                rejected.append(
                    {
                        "pattern_id": "GENERIC_FUTURE_WORK_OR_UNATTRIBUTED_LIMITATION",
                        "reason": "AUTHOR_ATTRIBUTION_NOT_BOUND",
                        "assertion_id": assertion_id,
                    }
                )
                continue
            limitation_provenance = (
                assertion.get("author_limitation_provenance_v3")
                if isinstance(assertion.get("author_limitation_provenance_v3"), dict)
                else {}
            )
            source_span_ids = {
                _text(unit.get("source_span_id") or unit.get("source_unit_id"))
                for unit in context.source_units_by_assertion.get(assertion_id) or []
                if isinstance(unit, dict)
            }
            if (
                _text(limitation_provenance.get("schema_version"))
                != "author_limitation_provenance_v3"
                or _text(limitation_provenance.get("status")) != "VERIFIED"
                or not _text(limitation_provenance.get("author_attribution_phrase"))
                or not _text(limitation_provenance.get("affected_object_or_method"))
                or limitation_provenance.get("has_locatable_source_context") is not True
                or _text(limitation_provenance.get("source_span_id")) not in source_span_ids
            ):
                rejected.append(
                    {
                        "pattern_id": "AUTHOR_LIMITATION_PROVENANCE_INSUFFICIENT",
                        "reason": "AUTHOR_ATTRIBUTION_AFFECTED_OBJECT_AND_LOCATABLE_CONTEXT_REQUIRED",
                        "assertion_id": assertion_id,
                    }
                )
                continue
            limitation_text = _author_limitation_text(assertion)
            units = context.source_units_by_assertion.get(assertion_id) or []
            limitation_span_id = _text((units[0] if units else {}).get("source_span_id"))
            affected_claim = _first_text(
                assertion.get("affected_claim"),
                assertion.get("subject"),
                assertion.get("relation_kind"),
            )
            if not limitation_text or not affected_claim or not limitation_span_id:
                rejected.append(
                    {
                        "pattern_id": "AUTHOR_LIMITATION_PAYLOAD_UNBOUND",
                        "reason": "EXPLICIT_LIMITATION_NEEDS_CLAIM_AND_SOURCE_SPAN",
                        "assertion_id": assertion_id,
                    }
                )
                continue
            try:
                candidates.append(
                    create_source_bound_gap_candidate(
                        context=context,
                        gap_type=self.gap_type,
                        gap_subtype="UNTESTED_LIMITATION",
                        signal_type=GapSignalType.AUTHOR_STATED,
                        assertion_ids=[assertion_id],
                        type_payload={
                            "limitation_kind": "AUTHOR_STATED_UNKNOWN",
                            "author_stated_unknown": limitation_text,
                            "affected_claim": affected_claim,
                            "limitation_span_id": limitation_span_id,
                        },
                        detection_witness={
                            "pattern_id": "EXPLICIT_AUTHOR_STATED_LIMITATION",
                            "witness_assertion_ids": [assertion_id],
                        },
                        description="An author-attributed source span explicitly records an untested or unresolved claim.",
                        detector_id=self.detector_id,
                        detector_policy_version=self.detector_policy_version,
                    )
                )
            except ValueError as exc:
                rejected.append(
                    {
                        "pattern_id": "AUTHOR_LIMITATION_CANDIDATE_FACTORY_REJECTED",
                        "reason": str(exc),
                        "assertion_id": assertion_id,
                    }
                )
        return candidates, rejected, diagnostics


class EmpiricalCoverageDetector(EvidenceGraphGapDetector):
    gap_type = GapType.EMPIRICAL_COVERAGE
    detector_policy_version = "empirical_coverage_v1"
    implemented = True

    def _scan(self, context: DetectionContext) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
        candidates: list[dict[str, Any]] = []
        rejected: list[dict[str, Any]] = []
        diagnostics: list[dict[str, Any]] = []
        scope = context.research_question_contract.get("scientific_scope")
        scope = scope if isinstance(scope, dict) else {}
        target_object = _first_text(scope.get("research_object"), scope.get("population_or_system"))
        target_condition = _text(scope.get("condition_or_regime"))
        missing_slots = [
            slot_id
            for slot_id, entry in context.slot_coverage_ledger.items()
            if isinstance(entry, dict)
            and entry.get("required") is True
            and _text(entry.get("coverage_status")) == "MISSING"
        ]
        for assertion in context.assertions:
            if not isinstance(assertion, dict):
                continue
            assertion_id = _text(assertion.get("assertion_id"))
            if not (
                _assertion_kinds(assertion)
                & {"EMPIRICAL_RESULT", "DIRECT_OBSERVATION", "OBSERVATION", "MEASUREMENT_RESULT"}
            ) or not _has_direct_slot_support(assertion):
                continue
            phenomenon = _first_text(
                assertion.get("phenomenon"),
                assertion.get("object"),
                assertion.get("predicate"),
                assertion.get("relation_kind"),
            )
            if not target_object or not target_condition or not phenomenon:
                rejected.append(
                    {
                        "pattern_id": "EMPIRICAL_COVERAGE_CORE_SCOPE_UNDEFINED",
                        "reason": "OBJECT_PHENOMENON_AND_CONDITION_MUST_BE_DEFINED",
                        "assertion_id": assertion_id,
                        "missing": [
                            name
                            for name, value in (
                                ("target_object", target_object),
                                ("phenomenon", phenomenon),
                                ("target_condition", target_condition),
                            )
                            if not value
                        ],
                    }
                )
                continue
            coverage_dimension_missing = next(
                (
                    slot_id for slot_id in missing_slots
                    if slot_id not in {"phenomenon", "target_object", "target_condition"}
                ),
                "",
            )
            if not coverage_dimension_missing:
                continue
            try:
                candidates.append(
                    create_source_bound_gap_candidate(
                        context=context,
                        gap_type=self.gap_type,
                        gap_subtype="DIRECT_EVIDENCE_ABSENT",
                        signal_type=GapSignalType.CORPUS_COVERAGE,
                        assertion_ids=[assertion_id],
                        type_payload={
                            "phenomenon": phenomenon,
                            "target_object": target_object,
                            "target_condition": target_condition,
                            "coverage_dimension_missing": coverage_dimension_missing,
                        },
                        detection_witness={
                            "pattern_id": "DECLARED_SCOPE_WITH_MISSING_DIRECT_COVERAGE_DIMENSION",
                            "witness_assertion_ids": [assertion_id],
                            "coverage_ledger_refs": [coverage_dimension_missing],
                        },
                        description="A defined object, phenomenon, and condition have direct evidence, while one declared coverage dimension remains unsupported.",
                        detector_id=self.detector_id,
                        detector_policy_version=self.detector_policy_version,
                    )
                )
            except ValueError as exc:
                rejected.append(
                    {
                        "pattern_id": "EMPIRICAL_COVERAGE_CANDIDATE_FACTORY_REJECTED",
                        "reason": str(exc),
                        "assertion_id": assertion_id,
                    }
                )
        if not missing_slots:
            diagnostics.append(
                {
                    "reason": "COVERAGE_LEDGER_HAS_NO_MISSING_REQUIRED_DIMENSION",
                    "gap_type": self.gap_type.value,
                }
            )
        return candidates, rejected, diagnostics


class CausalIdentificationDetector(EvidenceGraphGapDetector):
    gap_type = GapType.CAUSAL_IDENTIFICATION
    detector_policy_version = "causal_identification_v1"
    implemented = True

    def _scan(self, context: DetectionContext) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
        candidates: list[dict[str, Any]] = []
        rejected: list[dict[str, Any]] = []
        diagnostics: list[dict[str, Any]] = []
        for path in _relation_paths(context):
            assertion = path["assertion"]
            assertion_id = path["assertion_id"]
            if not _is_association_or_unsupported_causal_claim(path):
                continue
            if _has_identification_design(assertion):
                rejected.append(
                    {
                        "pattern_id": "CAUSAL_IDENTIFICATION_ALREADY_HAS_SOURCE_BOUND_DESIGN",
                        "reason": "ASSOCIATION_OR_CLAIM_IS_BOUND_TO_AN_IDENTIFICATION_DESIGN",
                        "assertion_id": assertion_id,
                        "relation_id": path["relation_id"],
                    }
                )
                continue
            try:
                candidates.append(
                    create_source_bound_gap_candidate(
                        context=context,
                        gap_type=self.gap_type,
                        gap_subtype="IDENTIFICATION_DESIGN_MISSING",
                        signal_type=GapSignalType.INFERRED_FROM_EVIDENCE,
                        assertion_ids=[assertion_id],
                        type_payload={
                            "input": path["input"],
                            "outcome": path["outcome"],
                            "identification_missing": "The source-bound association has no bound intervention or identification design.",
                        },
                        detection_witness={
                            "pattern_id": "ASSOCIATION_WITHOUT_IDENTIFICATION_DESIGN",
                            "witness_assertion_ids": [assertion_id],
                            "witness_relation_ids": [path["relation_id"]] if path["relation_id"] else [],
                            "observed_predicate": path["predicate"],
                        },
                        description="A source-bound association or causal claim has named endpoints but no bound design capable of distinguishing causation from alternatives.",
                        detector_id=self.detector_id,
                        detector_policy_version=self.detector_policy_version,
                    )
                )
            except ValueError as exc:
                rejected.append(
                    {
                        "pattern_id": "CAUSAL_IDENTIFICATION_CANDIDATE_FACTORY_REJECTED",
                        "reason": str(exc),
                        "assertion_id": assertion_id,
                    }
                )
        return candidates, rejected, diagnostics


class MechanismCompetitionDetector(EvidenceGraphGapDetector):
    gap_type = GapType.MECHANISM_COMPETITION
    detector_policy_version = "mechanism_competition_v2"
    implemented = True

    def _scan(self, context: DetectionContext) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
        candidates: list[dict[str, Any]] = []
        rejected = _BoundedRejectionPatterns()
        diagnostics: list[dict[str, Any]] = []
        paths = [path for path in _relation_paths(context) if _text(path.get("mechanism"))]
        if len(paths) < 2:
            if context.assertions:
                rejected.append(
                    {
                        "pattern_id": "MECHANISM_PATH_PAIR_UNAVAILABLE",
                        "reason": "AT_LEAST_TWO_EXPLICIT_MECHANISM_PATHS_REQUIRED",
                        "assertion_count": len(context.assertions),
                    }
                )
            return candidates, rejected, diagnostics
        planned_pairs = _indexed_relation_path_pairs(context, paths)
        if not planned_pairs:
            diagnostic_pair = _first_same_relation_pair(paths)
            if diagnostic_pair is not None:
                left, right = diagnostic_pair
                rejected.append(
                    {
                        "pattern_id": "MECHANISM_PAIR_NOT_GRAPH_PLANNED",
                        "reason": "MECHANISM_COMPETITION_REQUIRES_A_GRAPH_PLANNED_COMPARABLE_PAIR",
                        "assertion_ids": [left["assertion_id"], right["assertion_id"]],
                    }
                )
            diagnostics.append(
                {
                    "reason": "NO_GRAPH_PLANNED_COMPARABLE_MECHANISM_PAIR",
                    "gap_type": self.gap_type.value,
                }
            )
            return candidates, rejected, diagnostics
        for left, right, comparison_ids in planned_pairs:
            if _key(left["mechanism"]) == _key(right["mechanism"]):
                rejected.append(
                    {
                        "pattern_id": "MECHANISM_PATHS_NOT_DISTINCT",
                        "reason": "TWO_ASSERTIONS_DO_NOT_ESTABLISH_TWO_MECHANISMS",
                        "assertion_ids": [left["assertion_id"], right["assertion_id"]],
                    }
                )
                continue
            if _key(left["input"]) != _key(right["input"]) or _key(left["outcome"]) != _key(right["outcome"]):
                rejected.append(
                    {
                        "pattern_id": "COMMON_ENDPOINT_OR_INPUT_MISSING",
                        "reason": "MECHANISM_PATHS_MUST_SHARE_A_COMPARABLE_INPUT_AND_ENDPOINT",
                        "assertion_ids": [left["assertion_id"], right["assertion_id"]],
                    }
                )
                continue
            if any(
                _text(path["assertion"].get(field_name))
                for path in (left, right)
                for field_name in ("discriminating_prediction", "discriminating_test", "mechanism_discriminator")
            ):
                rejected.append(
                    {
                        "pattern_id": "DISCRIMINATING_EVIDENCE_ALREADY_BOUND",
                        "reason": "SOURCE_BOUND_EVIDENCE_ALREADY_DECLARES_A_DISCRIMINATOR",
                        "assertion_ids": [left["assertion_id"], right["assertion_id"]],
                    }
                )
                continue
            assertion_ids = [left["assertion_id"], right["assertion_id"]]
            _append_source_bound_candidate(
                candidates,
                rejected,
                context=context,
                gap_type=self.gap_type,
                gap_subtype="DISCRIMINATING_TEST_MISSING",
                signal_type=GapSignalType.INFERRED_FROM_EVIDENCE,
                assertion_ids=assertion_ids,
                type_payload={
                    "common_input": left["input"],
                    "common_outcome": left["outcome"],
                    "candidate_mechanisms": [left["mechanism"], right["mechanism"]],
                },
                detection_witness={
                    "pattern_id": "TWO_DISTINCT_MECHANISM_PATHS_WITH_COMMON_ENDPOINT",
                    "witness_assertion_ids": assertion_ids,
                    "witness_relation_ids": [
                        relation_id
                        for relation_id in (left["relation_id"], right["relation_id"])
                        if relation_id
                    ],
                    "comparability_assessment_ids": comparison_ids,
                    "path_a": {
                        "mechanism": left["mechanism"],
                        "input": left["input"],
                        "outcome": left["outcome"],
                    },
                    "path_b": {
                        "mechanism": right["mechanism"],
                        "input": right["input"],
                        "outcome": right["outcome"],
                    },
                },
                description="Two distinct, source-explicit mechanism paths share a graph-planned comparable input and endpoint, but no source-bound discriminator is present.",
                detector_id=self.detector_id,
                detector_policy_version=self.detector_policy_version,
                rejection_pattern_id="MECHANISM_COMPETITION_CANDIDATE_FACTORY_REJECTED",
            )
        return candidates, rejected, diagnostics


class BoundaryHeterogeneityDetector(EvidenceGraphGapDetector):
    gap_type = GapType.BOUNDARY_HETEROGENEITY
    detector_policy_version = "boundary_heterogeneity_v2"
    implemented = True

    def _scan(self, context: DetectionContext) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
        candidates: list[dict[str, Any]] = []
        rejected = _BoundedRejectionPatterns()
        diagnostics: list[dict[str, Any]] = []
        paths = _relation_paths(context)
        if len(paths) < 2:
            if context.assertions:
                rejected.append({
                    "pattern_id": "BOUNDARY_RELATION_PAIR_UNAVAILABLE",
                    "reason": "TWO_SOURCE_BOUND_RELATION_OBSERVATIONS_REQUIRED",
                })
            return candidates, rejected, diagnostics
        planned_pairs = _indexed_relation_path_pairs(context, paths)
        if not planned_pairs:
            diagnostic_pair = _first_same_relation_pair(paths)
            if diagnostic_pair is not None:
                left, right = diagnostic_pair
                condition_a, condition_b = _path_condition(left), _path_condition(right)
                rejected.append({
                    "pattern_id": (
                        "BOUNDARY_CONDITIONS_NOT_DISTINCT"
                        if not condition_a or not condition_b or _key(condition_a) == _key(condition_b)
                        else "BOUNDARY_CONDITIONS_NOT_COMPARABLE"
                    ),
                    "reason": (
                        "SAME_RELATION_REQUIRES_TWO_EXPLICIT_DISTINCT_CONDITIONS"
                        if not condition_a or not condition_b or _key(condition_a) == _key(condition_b)
                        else "CONDITION_DIFFERENCE_WITHOUT_PAIR_SPECIFIC_COMPARABILITY_IS_NOT_A_BOUNDARY_GAP"
                    ),
                    "assertion_ids": [left["assertion_id"], right["assertion_id"]],
                })
            diagnostics.append({
                "reason": "NO_GRAPH_PLANNED_COMPARABLE_RELATION_PAIR",
                "gap_type": self.gap_type.value,
            })
            return candidates, rejected, diagnostics
        for left, right, comparison_ids in planned_pairs:
            if not _same_relation_target(left, right):
                continue
            condition_a = _path_condition(left)
            condition_b = _path_condition(right)
            if not condition_a or not condition_b or _key(condition_a) == _key(condition_b):
                rejected.append({
                    "pattern_id": "BOUNDARY_CONDITIONS_NOT_DISTINCT",
                    "reason": "SAME_RELATION_REQUIRES_TWO_EXPLICIT_DISTINCT_CONDITIONS",
                    "assertion_ids": [left["assertion_id"], right["assertion_id"]],
                })
                continue
            direction_a = _effect_direction(left)
            direction_b = _effect_direction(right)
            left_status = _structured_value(left["assertion"], "boundary_status", "threshold_status", "applicability_status")
            right_status = _structured_value(right["assertion"], "boundary_status", "threshold_status", "applicability_status")
            changed_effect = bool(direction_a and direction_b and direction_a != direction_b)
            unresolved_boundary = _is_explicitly_unresolved(left_status) or _is_explicitly_unresolved(right_status)
            if not changed_effect and not unresolved_boundary:
                rejected.append({
                    "pattern_id": "BOUNDARY_EFFECT_DIFFERENCE_UNBOUND",
                    "reason": "DISTINCT_CONDITIONS_ALONE_DO_NOT_ESTABLISH_HETEROGENEITY",
                    "assertion_ids": [left["assertion_id"], right["assertion_id"]],
                })
                continue
            assertion_ids = [left["assertion_id"], right["assertion_id"]]
            boundary_variable = _first_text(
                _structured_text(left["assertion"], "boundary_variable", "heterogeneity_axis"),
                _structured_text(right["assertion"], "boundary_variable", "heterogeneity_axis"),
                "condition_or_regime",
            )
            _append_source_bound_candidate(
                candidates,
                rejected,
                context=context,
                gap_type=self.gap_type,
                gap_subtype="CONTEXT_DEPENDENT_EFFECT" if changed_effect else "REGIME_BOUNDARY",
                signal_type=GapSignalType.INFERRED_FROM_EVIDENCE,
                assertion_ids=assertion_ids,
                type_payload={
                    "base_relation": _relation_description(left),
                    "boundary_variable": boundary_variable,
                    "condition_a": condition_a,
                    "condition_b": condition_b,
                },
                detection_witness={
                    "pattern_id": "COMPARABLE_RELATION_WITH_CONDITION_DEPENDENT_EFFECT",
                    "witness_assertion_ids": assertion_ids,
                    "witness_relation_ids": [item for item in (left["relation_id"], right["relation_id"]) if item],
                    "comparability_assessment_ids": comparison_ids,
                    "effect_difference": {
                        "condition_a_direction": direction_a,
                        "condition_b_direction": direction_b,
                        "threshold_or_applicability_unresolved": unresolved_boundary,
                    },
                },
                description="A source-bound relation has distinct conditions with pair-specific comparability and either an observed effect change or an explicit unresolved boundary.",
                detector_id=self.detector_id,
                detector_policy_version=self.detector_policy_version,
                rejection_pattern_id="BOUNDARY_HETEROGENEITY_CANDIDATE_FACTORY_REJECTED",
            )
        return candidates, rejected, diagnostics


class ContradictionReplicationDetector(EvidenceGraphGapDetector):
    gap_type = GapType.CONTRADICTION_REPLICATION
    detector_policy_version = "contradiction_replication_v2"
    implemented = True

    def _scan(self, context: DetectionContext) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
        candidates: list[dict[str, Any]] = []
        rejected = _BoundedRejectionPatterns()
        diagnostics: list[dict[str, Any]] = []
        paths = _relation_paths(context)
        if len(paths) < 2:
            if context.assertions:
                rejected.append({
                    "pattern_id": "CONTRADICTION_PAIR_UNAVAILABLE",
                    "reason": "TWO_SOURCE_BOUND_RELATION_RESULTS_REQUIRED",
                })
            return candidates, rejected, diagnostics
        planned_pairs = _indexed_relation_path_pairs(context, paths)
        if not planned_pairs:
            diagnostic_pair = _first_same_relation_pair(paths)
            if diagnostic_pair is not None:
                left, right = diagnostic_pair
                rejected.append({
                    "pattern_id": "CONTRADICTION_NOT_COMPARABLE",
                    "reason": "DIFFERENT_OR_UNALIGNED_CONDITIONS_CANNOT_BE_REPORTED_AS_A_CONTRADICTION",
                    "assertion_ids": [left["assertion_id"], right["assertion_id"]],
                })
            diagnostics.append({
                "reason": "NO_GRAPH_PLANNED_COMPARABLE_RELATION_PAIR",
                "gap_type": self.gap_type.value,
            })
            return candidates, rejected, diagnostics
        for left, right, comparison_ids in planned_pairs:
            if not _same_relation_target(left, right):
                continue
            assertion_ids = [left["assertion_id"], right["assertion_id"]]
            if not left["paper_id"] or not right["paper_id"] or _key(left["paper_id"]) == _key(right["paper_id"]):
                rejected.append({
                    "pattern_id": "CONTRADICTION_SOURCES_NOT_INDEPENDENT",
                    "reason": "CONTRADICTION_REQUIRES_TWO_DISTINCT_SOURCE_PAPERS",
                    "assertion_ids": assertion_ids,
                })
                continue
            direction_a = _effect_direction(left)
            direction_b = _effect_direction(right)
            if not direction_a or not direction_b or direction_a == direction_b:
                rejected.append({
                    "pattern_id": "CONTRADICTION_POLARITY_NOT_OPPOSED",
                    "reason": "INDEPENDENT_COMPARABLE_RESULTS_NEED_EXPLICIT_OPPOSITE_EFFECT_DIRECTIONS",
                    "assertion_ids": assertion_ids,
                })
                continue
            _append_source_bound_candidate(
                candidates,
                rejected,
                context=context,
                gap_type=self.gap_type,
                gap_subtype="OPPOSITE_POLARITY",
                signal_type=GapSignalType.LITERATURE_CONTRADICTION,
                assertion_ids=assertion_ids,
                type_payload={
                    "shared_claim": _relation_description(left),
                    "evidence_sets": [
                        {"paper_id": left["paper_id"], "assertion_id": left["assertion_id"], "effect_direction": direction_a},
                        {"paper_id": right["paper_id"], "assertion_id": right["assertion_id"], "effect_direction": direction_b},
                    ],
                    "comparability_verdict": "PAIR_SPECIFIC_SOURCE_BOUND_COMPARABLE",
                },
                detection_witness={
                    "pattern_id": "INDEPENDENT_COMPARABLE_OPPOSITE_RESULTS",
                    "witness_assertion_ids": assertion_ids,
                    "witness_relation_ids": [item for item in (left["relation_id"], right["relation_id"]) if item],
                    "comparability_assessment_ids": comparison_ids,
                    "opposite_effect_directions": [direction_a, direction_b],
                },
                description="Independent source-bound papers make comparable claims about the same relation with explicit opposite effect directions.",
                detector_id=self.detector_id,
                detector_policy_version=self.detector_policy_version,
                rejection_pattern_id="CONTRADICTION_REPLICATION_CANDIDATE_FACTORY_REJECTED",
            )
        return candidates, rejected, diagnostics


class MeasurementOperationalizationDetector(EvidenceGraphGapDetector):
    gap_type = GapType.MEASUREMENT_OPERATIONALIZATION
    detector_policy_version = "measurement_operationalization_v1"
    implemented = True

    def _scan(self, context: DetectionContext) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
        candidates: list[dict[str, Any]] = []
        rejected: list[dict[str, Any]] = []
        diagnostics: list[dict[str, Any]] = []
        for assertion in context.assertions:
            if not isinstance(assertion, dict):
                continue
            assertion_id = _text(assertion.get("assertion_id"))
            construct = _structured_text(assertion, "construct", "measured_construct", "latent_construct")
            proxy_measure = _structured_text(assertion, "proxy_measure", "proxy", "operational_measure")
            target_measure = _structured_text(assertion, "target_measure", "reference_measure", "gold_standard_measure")
            kinds = _assertion_kinds(assertion)
            if not construct or not proxy_measure or not target_measure:
                if kinds & {"MEASUREMENT_DEFINITION", "MEASUREMENT_RESULT", "MEASUREMENT_ASSERTION"}:
                    rejected.append({
                        "pattern_id": "MEASUREMENT_MAPPING_COMPONENT_UNDEFINED",
                        "reason": "CONSTRUCT_PROXY_AND_TARGET_MEASURE_MUST_ALL_BE_SOURCE_EXPLICIT",
                        "assertion_id": assertion_id,
                    })
                continue
            if _key(proxy_measure) == _key(target_measure):
                rejected.append({
                    "pattern_id": "DIRECT_TARGET_MEASURE_IS_NOT_PROXY_GAP",
                    "reason": "A_TARGET_MEASURE_CANNOT_ALSO_BE_TREATED_AS_AN_UNVALIDATED_PROXY",
                    "assertion_id": assertion_id,
                })
                continue
            mapping_status = _structured_value(
                assertion,
                "mapping_validation_status",
                "mapping_status",
                "proxy_target_mapping_status",
                "calibration_status",
            )
            validation_missing = _structured_text(
                assertion,
                "validation_missing",
                "mapping_validation_missing",
                "calibration_missing",
            )
            if _is_explicitly_confirmed(mapping_status) or _is_explicitly_confirmed(
                _structured_value(assertion, "mapping_validated", "calibrated", "externally_validated")
            ):
                rejected.append({
                    "pattern_id": "PROXY_TARGET_MAPPING_ALREADY_VALIDATED",
                    "reason": "SOURCE_BOUND_MAPPING_OR_CALIBRATION_IS_ALREADY_CONFIRMED",
                    "assertion_id": assertion_id,
                })
                continue
            mapping_state = (
                _text(mapping_status)
                if _text(mapping_status)
                else "VALIDATION_NOT_BOUND_IN_SOURCE_ASSERTION"
            )
            _append_source_bound_candidate(
                candidates,
                rejected,
                context=context,
                gap_type=self.gap_type,
                gap_subtype="PROXY_VALIDITY",
                signal_type=GapSignalType.INFERRED_FROM_EVIDENCE,
                assertion_ids=[assertion_id],
                type_payload={
                    "construct": construct,
                    "proxy_measure": proxy_measure,
                    "target_measure": target_measure,
                },
                detection_witness={
                    "pattern_id": "SOURCE_EXPLICIT_PROXY_TARGET_MAPPING_WITHOUT_VALIDATION",
                    "witness_assertion_ids": [assertion_id],
                    "mapping_status": mapping_state,
                    "validation_missing": validation_missing or "SOURCE_BOUND_VALIDATION_STATUS_NOT_PRESENT",
                },
                description="A source explicitly defines a construct, proxy, and target measure, but the proxy-to-target validation is unresolved or not source-bound.",
                detector_id=self.detector_id,
                detector_policy_version=self.detector_policy_version,
                rejection_pattern_id="MEASUREMENT_OPERATIONALIZATION_CANDIDATE_FACTORY_REJECTED",
            )
        return candidates, rejected, diagnostics


class TheoryMathematicalDetector(EvidenceGraphGapDetector):
    gap_type = GapType.THEORY_MATHEMATICAL
    detector_policy_version = "theory_mathematical_v1"
    implemented = True

    def _scan(self, context: DetectionContext) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
        candidates: list[dict[str, Any]] = []
        rejected: list[dict[str, Any]] = []
        diagnostics: list[dict[str, Any]] = []
        for assertion in context.assertions:
            if not isinstance(assertion, dict):
                continue
            assertion_id = _text(assertion.get("assertion_id"))
            kinds = _assertion_kinds(assertion)
            formal_claim = _structured_text(assertion, "formal_claim", "formal_statement", "theorem", "proposition")
            assumptions = _structured_values(assertion, "assumptions", "formal_assumptions", "identification_assumptions")
            if not formal_claim or not assumptions:
                if kinds & {"FORMAL_PROPOSITION", "FORMAL_ASSUMPTION", "THEORY_CLAIM"}:
                    rejected.append({
                        "pattern_id": "THEORY_FORMAL_STRUCTURE_INCOMPLETE",
                        "reason": "FORMAL_CLAIM_AND_EXPLICIT_ASSUMPTIONS_ARE_REQUIRED",
                        "assertion_id": assertion_id,
                    })
                continue
            uncertainty_fields = (
                ("assumption_status", "ASSUMPTION_UNTESTED"),
                ("identifiability_status", "IDENTIFIABILITY"),
                ("counterexample_status", "COUNTEREXAMPLE_UNKNOWN"),
                ("validity_domain_status", "THEOREM_EXTENSION"),
            )
            subtype = ""
            uncertainty_status = ""
            for field_name, candidate_subtype in uncertainty_fields:
                value = _structured_value(assertion, field_name)
                if _is_explicitly_unresolved(value):
                    subtype = candidate_subtype
                    uncertainty_status = _text(value)
                    break
            if not subtype:
                rejected.append({
                    "pattern_id": "THEORY_UNCERTAINTY_NOT_SOURCE_DECLARED",
                    "reason": "UNUSED_OR_UNAPPLIED_THEORY_WITHOUT_AN_UNTESTED_ASSUMPTION_OR_FORMAL_UNKNOWN_IS_NOT_A_THEORY_GAP",
                    "assertion_id": assertion_id,
                })
                continue
            _append_source_bound_candidate(
                candidates,
                rejected,
                context=context,
                gap_type=self.gap_type,
                gap_subtype=subtype,
                signal_type=GapSignalType.MODEL_OR_THEORY,
                assertion_ids=[assertion_id],
                type_payload={"formal_claim": formal_claim, "assumptions": assumptions},
                detection_witness={
                    "pattern_id": "FORMAL_CLAIM_WITH_EXPLICIT_UNRESOLVED_CONDITION",
                    "witness_assertion_ids": [assertion_id],
                    "formal_uncertainty_status": uncertainty_status,
                },
                description="A formal claim with explicit assumptions has a source-declared unresolved assumption, identifiability, counterexample, or validity-domain condition.",
                detector_id=self.detector_id,
                detector_policy_version=self.detector_policy_version,
                rejection_pattern_id="THEORY_MATHEMATICAL_CANDIDATE_FACTORY_REJECTED",
            )
        return candidates, rejected, diagnostics


class GeneralizationTransportabilityDetector(EvidenceGraphGapDetector):
    gap_type = GapType.GENERALIZATION_TRANSPORTABILITY
    detector_policy_version = "generalization_transportability_v1"
    implemented = True

    def _scan(self, context: DetectionContext) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
        candidates: list[dict[str, Any]] = []
        rejected: list[dict[str, Any]] = []
        diagnostics: list[dict[str, Any]] = []
        for assertion in context.assertions:
            if not isinstance(assertion, dict):
                continue
            assertion_id = _text(assertion.get("assertion_id"))
            source_domain = _structured_text(assertion, "source_domain", "training_domain", "origin_domain")
            target_domain = _structured_text(assertion, "target_domain", "deployment_domain", "evaluation_domain")
            model_or_claim = _structured_text(assertion, "model_or_claim", "generalization_claim", "model", "transport_claim")
            if not source_domain or not target_domain or not model_or_claim:
                if _assertion_kinds(assertion) & {"GENERALIZATION_CLAIM", "TRANSPORT_CLAIM", "EMPIRICAL_RESULT"}:
                    rejected.append({
                        "pattern_id": "GENERALIZATION_DOMAINS_UNDEFINED",
                        "reason": "SOURCE_DOMAIN_TARGET_DOMAIN_AND_SOURCE_BOUND_MODEL_OR_CLAIM_ARE_REQUIRED",
                        "assertion_id": assertion_id,
                    })
                continue
            if _key(source_domain) == _key(target_domain):
                rejected.append({
                    "pattern_id": "GENERALIZATION_DOMAIN_SHIFT_ABSENT",
                    "reason": "SOURCE_AND_TARGET_DOMAINS_MUST_BE_DISTINCT",
                    "assertion_id": assertion_id,
                })
                continue
            shift_type = _structured_text(assertion, "shift_type", "domain_shift", "distribution_shift")
            if not shift_type:
                rejected.append({
                    "pattern_id": "GENERALIZATION_SHIFT_UNDEFINED",
                    "reason": "A_DECLARED_SOURCE_TARGET_SHIFT_IS_REQUIRED_FOR_A_TRANSPORTABILITY_GAP",
                    "assertion_id": assertion_id,
                })
                continue
            validation_status = _structured_value(
                assertion,
                "external_validation_status",
                "target_domain_validation_status",
                "transport_validation_status",
            )
            if _is_explicitly_confirmed(validation_status):
                rejected.append({
                    "pattern_id": "GENERALIZATION_EXTERNAL_VALIDATION_ALREADY_BOUND",
                    "reason": "SOURCE_BOUND_EXTERNAL_VALIDATION_ALREADY_COVERS_THE_TARGET_DOMAIN",
                    "assertion_id": assertion_id,
                })
                continue
            subtype = next(
                (
                    item
                    for item in ("COVARIATE_SHIFT", "LABEL_SHIFT", "CONCEPT_SHIFT", "STRUCTURAL_SHIFT")
                    if item.replace("_", " ").casefold() in _key(shift_type)
                ),
                "EXTERNAL_VALIDATION_MISSING",
            )
            _append_source_bound_candidate(
                candidates,
                rejected,
                context=context,
                gap_type=self.gap_type,
                gap_subtype=subtype,
                signal_type=GapSignalType.INFERRED_FROM_EVIDENCE,
                assertion_ids=[assertion_id],
                type_payload={
                    "source_domain": source_domain,
                    "target_domain": target_domain,
                    "model_or_claim": model_or_claim,
                },
                detection_witness={
                    "pattern_id": "DECLARED_SOURCE_TARGET_SHIFT_WITHOUT_EXTERNAL_VALIDATION",
                    "witness_assertion_ids": [assertion_id],
                    "shift_type": shift_type,
                    "external_validation_status": _text(validation_status) or "NOT_SOURCE_BOUND",
                },
                description="A source-bound model or claim is explicitly transported from a source domain to a distinct target domain with a declared shift but no bound external validation.",
                detector_id=self.detector_id,
                detector_policy_version=self.detector_policy_version,
                rejection_pattern_id="GENERALIZATION_TRANSPORTABILITY_CANDIDATE_FACTORY_REJECTED",
            )
        return candidates, rejected, diagnostics


class MethodDesignDetector(EvidenceGraphGapDetector):
    gap_type = GapType.METHOD_DESIGN
    detector_policy_version = "method_design_v1"
    implemented = True

    def _scan(self, context: DetectionContext) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
        candidates: list[dict[str, Any]] = []
        rejected: list[dict[str, Any]] = []
        diagnostics: list[dict[str, Any]] = []
        for assertion in context.assertions:
            if not isinstance(assertion, dict):
                continue
            assertion_id = _text(assertion.get("assertion_id"))
            current_method = _structured_text(assertion, "current_method", "method", "study_method", "analysis_method")
            failure_mode = _structured_text(assertion, "failure_mode", "protocol_failure", "identification_failure", "computational_limit")
            bias_or_problem = _structured_text(
                assertion,
                "bias_or_identification_problem",
                "bias_source",
                "identification_problem",
                "protocol_problem",
            )
            impact = _structured_text(assertion, "impact_on_claim", "conclusion_impact", "claim_impact")
            if not current_method or not failure_mode:
                if _assertion_kinds(assertion) & {"METHOD_DESCRIPTION", "METHOD_EVALUATION", "METHOD_FAILURE"}:
                    rejected.append({
                        "pattern_id": "METHOD_FAILURE_STRUCTURE_INCOMPLETE",
                        "reason": "CURRENT_METHOD_AND_SOURCE_DECLARED_FAILURE_MODE_ARE_REQUIRED",
                        "assertion_id": assertion_id,
                    })
                continue
            if not bias_or_problem or not impact:
                rejected.append({
                    "pattern_id": "METHOD_FAILURE_CONCLUSION_IMPACT_UNBOUND",
                    "reason": "A_METHOD_IMPROVEMENT_SUGGESTION_IS_NOT_A_GAP_WITHOUT_A_SOURCE_BOUND_BIAS_OR_FAILURE_IMPACT_ON_A_CLAIM",
                    "assertion_id": assertion_id,
                })
                continue
            failure_key = _key(failure_mode)
            subtype = (
                "IDENTIFICATION_FAILURE" if "identif" in failure_key
                else "COMPUTATIONAL_LIMIT" if any(token in failure_key for token in ("comput", "scalab", "resource"))
                else "PROTOCOL_FAILURE" if "protocol" in failure_key
                else "BIAS_UNRESOLVED"
            )
            _append_source_bound_candidate(
                candidates,
                rejected,
                context=context,
                gap_type=self.gap_type,
                gap_subtype=subtype,
                signal_type=GapSignalType.INFERRED_FROM_EVIDENCE,
                assertion_ids=[assertion_id],
                type_payload={"current_method": current_method, "failure_mode": failure_mode},
                detection_witness={
                    "pattern_id": "SOURCE_BOUND_METHOD_FAILURE_WITH_CLAIM_IMPACT",
                    "witness_assertion_ids": [assertion_id],
                    "bias_or_identification_problem": bias_or_problem,
                    "impact_on_claim": impact,
                },
                description="A source-bound method has a declared failure mode or bias that affects a named scientific claim.",
                detector_id=self.detector_id,
                detector_policy_version=self.detector_policy_version,
                rejection_pattern_id="METHOD_DESIGN_CANDIDATE_FACTORY_REJECTED",
            )
        return candidates, rejected, diagnostics


class DataCoverageDetector(EvidenceGraphGapDetector):
    gap_type = GapType.DATA_COVERAGE
    detector_policy_version = "data_coverage_v1"
    implemented = True

    def _scan(self, context: DetectionContext) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
        candidates: list[dict[str, Any]] = []
        rejected: list[dict[str, Any]] = []
        diagnostics: list[dict[str, Any]] = []
        for assertion in context.assertions:
            if not isinstance(assertion, dict):
                continue
            assertion_id = _text(assertion.get("assertion_id"))
            missing_dimensions = {
                "missing_variables": _structured_values(assertion, "missing_variables", "missing_key_variables"),
                "missing_population_or_system": _structured_text(assertion, "missing_population_or_system", "missing_population", "missing_system"),
                "missing_regime": _structured_text(assertion, "missing_regime", "missing_condition", "missing_conditions"),
                "missing_time_horizon": _structured_text(assertion, "missing_time_horizon", "missing_time_window", "missing_longitudinal_window"),
            }
            declared_dimensions = [
                name for name, value in missing_dimensions.items()
                if bool(value)
            ]
            impact = _structured_text(assertion, "impact_on_claim", "coverage_impact", "conclusion_impact")
            quantification = _structured_value(
                assertion,
                "coverage_quantification",
                "coverage_measure",
                "coverage_fraction",
                "missing_rate",
                "coverage_gap_estimate",
            )
            kinds = _assertion_kinds(assertion)
            if not declared_dimensions:
                if kinds & {"DATASET_COVERAGE", "DATA_COVERAGE", "DATASET_DESCRIPTION"}:
                    rejected.append({
                        "pattern_id": "DATA_COVERAGE_DIMENSION_UNDECLARED",
                        "reason": "SMALL_DATASET_SIZE_ALONE_IS_NOT_A_DATA_COVERAGE_GAP",
                        "assertion_id": assertion_id,
                    })
                continue
            if not impact or quantification in (None, "", [], {}, ()):
                rejected.append({
                    "pattern_id": "DATA_COVERAGE_IMPACT_OR_QUANTIFICATION_UNBOUND",
                    "reason": "MISSING_DIMENSIONS_MUST_BE_SOURCE_QUANTIFIED_AND_LINKED_TO_A_CLAIM_IMPACT",
                    "assertion_id": assertion_id,
                })
                continue
            subtype = (
                "VARIABLE_MISSING" if "missing_variables" in declared_dimensions
                else "POPULATION_COVERAGE" if "missing_population_or_system" in declared_dimensions
                else "REGIME_COVERAGE" if "missing_regime" in declared_dimensions
                else "TIME_HORIZON_COVERAGE"
            )
            _append_source_bound_candidate(
                candidates,
                rejected,
                context=context,
                gap_type=self.gap_type,
                gap_subtype=subtype,
                signal_type=GapSignalType.CORPUS_COVERAGE,
                assertion_ids=[assertion_id],
                type_payload={
                    **missing_dimensions,
                    "impact_on_claim": impact,
                },
                detection_witness={
                    "pattern_id": "QUANTIFIED_MISSING_DATA_DIMENSION_WITH_CLAIM_IMPACT",
                    "witness_assertion_ids": [assertion_id],
                    "declared_missing_dimensions": declared_dimensions,
                    "coverage_quantification": quantification,
                },
                description="A source quantifies a missing data dimension and explicitly links that coverage deficit to a scientific claim's validity or scope.",
                detector_id=self.detector_id,
                detector_policy_version=self.detector_policy_version,
                rejection_pattern_id="DATA_COVERAGE_CANDIDATE_FACTORY_REJECTED",
            )
        return candidates, rejected, diagnostics


class ScaleIntegrationDetector(EvidenceGraphGapDetector):
    gap_type = GapType.SCALE_INTEGRATION
    detector_policy_version = "scale_integration_v2"
    implemented = True

    def _scan(self, context: DetectionContext) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
        candidates: list[dict[str, Any]] = []
        rejected = _BoundedRejectionPatterns()
        diagnostics: list[dict[str, Any]] = []
        records: list[dict[str, Any]] = []
        for assertion in context.assertions:
            if not isinstance(assertion, dict):
                continue
            scale = _structured_text(assertion, "scale", "analysis_scale", "source_scale", "observation_scale")
            anchor = _structured_text(assertion, "integration_target", "bridge_target", "cross_scale_construct", "construct")
            coupling_question = _structured_text(assertion, "coupling_question", "integration_question", "bridge_question")
            bridge_status = _structured_value(assertion, "bridge_status", "coupling_status", "bridge_validation_status")
            if scale:
                records.append({
                    "assertion": assertion,
                    "assertion_id": _text(assertion.get("assertion_id")),
                    "scale": scale,
                    "anchor": anchor,
                    "coupling_question": coupling_question,
                    "bridge_status": bridge_status,
                })
        if len(records) < 2:
            if context.assertions:
                rejected.append({
                    "pattern_id": "SCALE_PAIR_UNAVAILABLE",
                    "reason": "TWO_SOURCE_BOUND_SCALE_STATEMENTS_REQUIRED",
                })
            return candidates, rejected, diagnostics
        planned_pairs = _indexed_assertion_record_pairs(context, records)
        if not planned_pairs:
            ordered = sorted(records, key=lambda item: _text(item.get("assertion_id")))
            rejected.append({
                "pattern_id": "SCALE_PAIR_NOT_GRAPH_PLANNED",
                "reason": "SCALE_INTEGRATION_REQUIRES_A_GRAPH_PLANNED_COMPARABLE_PAIR",
                "assertion_ids": [
                    _text(ordered[0].get("assertion_id")),
                    _text(ordered[1].get("assertion_id")),
                ],
            })
            diagnostics.append({
                "reason": "NO_GRAPH_PLANNED_COMPARABLE_SCALE_PAIR",
                "gap_type": self.gap_type.value,
            })
            return candidates, rejected, diagnostics
        for left, right, comparison_ids in planned_pairs:
            if _key(left["scale"]) == _key(right["scale"]):
                rejected.append({
                    "pattern_id": "SCALE_LEVELS_NOT_DISTINCT",
                    "reason": "TWO_SOURCE_BOUND_SCALE_STATEMENTS_MUST_NAME_DISTINCT_SCALES",
                    "assertion_ids": [left["assertion_id"], right["assertion_id"]],
                })
                continue
            assertion_ids = [left["assertion_id"], right["assertion_id"]]
            if not left["anchor"] or not right["anchor"] or _key(left["anchor"]) != _key(right["anchor"]):
                rejected.append({
                    "pattern_id": "SCALE_INTEGRATION_ANCHOR_UNALIGNED",
                    "reason": "TWO_SCALES_MUST_ADDRESS_THE_SAME_EXPLICIT_INTEGRATION_TARGET",
                    "assertion_ids": assertion_ids,
                })
                continue
            coupling_question = _first_text(left["coupling_question"], right["coupling_question"])
            bridge_unresolved = _is_explicitly_unresolved(left["bridge_status"]) or _is_explicitly_unresolved(right["bridge_status"])
            if not coupling_question or not bridge_unresolved:
                rejected.append({
                    "pattern_id": "SCALE_BRIDGE_GAP_NOT_SOURCE_DECLARED",
                    "reason": "MULTIPLE_SCALES_ALONE_DO_NOT_ESTABLISH_A_MISSING_BRIDGE_OR_COUPLING_QUESTION",
                    "assertion_ids": assertion_ids,
                })
                continue
            _append_source_bound_candidate(
                candidates,
                rejected,
                context=context,
                gap_type=self.gap_type,
                gap_subtype="SCALE_BRIDGE_MISSING",
                signal_type=GapSignalType.INFERRED_FROM_EVIDENCE,
                assertion_ids=assertion_ids,
                type_payload={
                    "source_scale": left["scale"],
                    "target_scale": right["scale"],
                    "coupling_question": coupling_question,
                },
                detection_witness={
                    "pattern_id": "TWO_SCALES_WITH_EXPLICIT_UNRESOLVED_BRIDGE",
                    "witness_assertion_ids": assertion_ids,
                    "comparability_assessment_ids": comparison_ids,
                    "integration_target": left["anchor"],
                    "bridge_statuses": [_text(left["bridge_status"]), _text(right["bridge_status"])],
                },
                description="Two source-bound scale statements address the same construct, have a graph-planned comparability assessment, and explicitly leave their bridge or coupling unresolved.",
                detector_id=self.detector_id,
                detector_policy_version=self.detector_policy_version,
                rejection_pattern_id="SCALE_INTEGRATION_CANDIDATE_FACTORY_REJECTED",
            )
        return candidates, rejected, diagnostics


class BenchmarkComparisonDetector(EvidenceGraphGapDetector):
    gap_type = GapType.BENCHMARK_COMPARISON
    detector_policy_version = "benchmark_comparison_v1"
    implemented = True

    def _scan(self, context: DetectionContext) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
        candidates: list[dict[str, Any]] = []
        rejected: list[dict[str, Any]] = []
        diagnostics: list[dict[str, Any]] = []
        grouped: dict[str, dict[str, Any]] = {}
        for assertion in context.assertions:
            if not isinstance(assertion, dict):
                continue
            comparison_target = _structured_text(assertion, "comparison_target", "comparison_need", "evaluation_target")
            systems = _structured_values(assertion, "candidate_systems", "candidate_system", "comparison_systems")
            if not comparison_target:
                continue
            entry = grouped.setdefault(
                _key(comparison_target),
                {"comparison_target": comparison_target, "systems": set(), "assertion_ids": [], "missing": {}},
            )
            entry["systems"].update(systems)
            entry["assertion_ids"].append(_text(assertion.get("assertion_id")))
            for payload_field, status_names, missing_names in (
                ("common_task_missing", ("common_task_status",), ("common_task_missing",)),
                ("shared_metric_missing", ("shared_metric_status", "metric_status"), ("shared_metric_missing",)),
                ("protocol_missing", ("comparison_protocol_status", "protocol_status"), ("protocol_missing",)),
            ):
                status = _structured_value(assertion, *status_names)
                stated_missing = _structured_text(assertion, *missing_names)
                if _is_explicitly_unresolved(status) or stated_missing:
                    entry["missing"][payload_field] = stated_missing or _text(status)
        if not grouped and context.assertions:
            rejected.append({
                "pattern_id": "BENCHMARK_COMPARISON_TARGET_UNDEFINED",
                "reason": "A_SOURCE_BOUND_COMPARISON_TARGET_IS_REQUIRED",
            })
        for entry in grouped.values():
            assertion_ids = sorted({_text(item) for item in entry["assertion_ids"] if _text(item)})
            systems = sorted({_text(item) for item in entry["systems"] if _text(item)})
            if len(systems) < 2:
                rejected.append({
                    "pattern_id": "BENCHMARK_CANDIDATE_SYSTEMS_UNDEFINED",
                    "reason": "ABSENT_BENCHMARK_WITHOUT_AT_LEAST_TWO_EXPLICIT_CANDIDATE_SYSTEMS_IS_NOT_A_COMPARISON_GAP",
                    "assertion_ids": assertion_ids,
                })
                continue
            if not entry["missing"]:
                rejected.append({
                    "pattern_id": "BENCHMARK_SHARED_EVALUATION_GAP_UNDECLARED",
                    "reason": "CANDIDATE_SYSTEMS_NEED_A_SOURCE_DECLARED_MISSING_TASK_METRIC_OR_PROTOCOL",
                    "assertion_ids": assertion_ids,
                })
                continue
            _append_source_bound_candidate(
                candidates,
                rejected,
                context=context,
                gap_type=self.gap_type,
                gap_subtype=(
                    "COMMON_TASK_MISSING" if "common_task_missing" in entry["missing"]
                    else "SHARED_METRIC_MISSING" if "shared_metric_missing" in entry["missing"]
                    else "PROTOCOL_MISSING"
                ),
                signal_type=GapSignalType.INFERRED_FROM_EVIDENCE,
                assertion_ids=assertion_ids,
                type_payload={
                    "comparison_target": entry["comparison_target"],
                    "candidate_systems": systems,
                    **entry["missing"],
                },
                detection_witness={
                    "pattern_id": "DEFINED_SYSTEMS_WITH_SOURCE_DECLARED_SHARED_EVALUATION_GAP",
                    "witness_assertion_ids": assertion_ids,
                    "missing_comparison_coordinates": sorted(entry["missing"]),
                },
                description="At least two source-explicit candidate systems require comparison, while a common task, metric, or protocol is source-declared missing.",
                detector_id=self.detector_id,
                detector_policy_version=self.detector_policy_version,
                rejection_pattern_id="BENCHMARK_COMPARISON_CANDIDATE_FACTORY_REJECTED",
            )
        return candidates, rejected, diagnostics


class TranslationImplementationDetector(EvidenceGraphGapDetector):
    gap_type = GapType.TRANSLATION_IMPLEMENTATION
    detector_policy_version = "translation_implementation_v1"
    implemented = True

    def _scan(self, context: DetectionContext) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
        candidates: list[dict[str, Any]] = []
        rejected: list[dict[str, Any]] = []
        diagnostics: list[dict[str, Any]] = []
        for assertion in context.assertions:
            if not isinstance(assertion, dict):
                continue
            assertion_id = _text(assertion.get("assertion_id"))
            validated_claim = _structured_text(assertion, "validated_claim")
            validation_status = _structured_value(assertion, "validation_status", "claim_validation_status", "evidence_validation_status")
            if not validated_claim and _is_explicitly_confirmed(validation_status):
                validated_claim = _structured_text(assertion, "claim", "model_or_claim", "implementation_claim")
            deployment_context = _structured_text(assertion, "deployment_context", "implementation_context", "real_world_context")
            implementation_barrier = _structured_text(
                assertion,
                "implementation_barrier",
                "deployment_barrier",
                "implementation_constraint",
            )
            if not validated_claim:
                if implementation_barrier or _assertion_kinds(assertion) & {"IMPLEMENTATION_CONSTRAINT", "DEPLOYMENT_CONSTRAINT"}:
                    rejected.append({
                        "pattern_id": "TRANSLATION_VALIDATED_CLAIM_UNBOUND",
                        "reason": "NOT_YET_APPLIED_WITHOUT_A_SOURCE_BOUND_VALIDATED_CLAIM_IS_NOT_A_TRANSLATION_GAP",
                        "assertion_id": assertion_id,
                    })
                continue
            if not deployment_context or not implementation_barrier:
                rejected.append({
                    "pattern_id": "TRANSLATION_DEPLOYMENT_BARRIER_INCOMPLETE",
                    "reason": "VALIDATED_CLAIM_REQUIRES_AN_EXPLICIT_DEPLOYMENT_CONTEXT_AND_REAL_BARRIER",
                    "assertion_id": assertion_id,
                })
                continue
            _append_source_bound_candidate(
                candidates,
                rejected,
                context=context,
                gap_type=self.gap_type,
                gap_subtype="IMPLEMENTATION_BARRIER",
                signal_type=GapSignalType.INFERRED_FROM_EVIDENCE,
                assertion_ids=[assertion_id],
                type_payload={
                    "validated_claim": validated_claim,
                    "deployment_context": deployment_context,
                    "implementation_barrier": implementation_barrier,
                },
                detection_witness={
                    "pattern_id": "VALIDATED_CLAIM_WITH_SOURCE_DECLARED_DEPLOYMENT_BARRIER",
                    "witness_assertion_ids": [assertion_id],
                    "claim_validation_status": _text(validation_status) or "VALIDATED_CLAIM_SOURCE_FIELD",
                },
                description="A source-bound validated claim encounters a concrete barrier in a defined deployment context.",
                detector_id=self.detector_id,
                detector_policy_version=self.detector_policy_version,
                rejection_pattern_id="TRANSLATION_IMPLEMENTATION_CANDIDATE_FACTORY_REJECTED",
            )
        return candidates, rejected, diagnostics


# Every registry entry below has its own source-bound structural scan.  A type
# is never enabled merely because an assertion kind or an RQC prior happens to
# match it.
GAP_DETECTOR_REGISTRY: tuple[GapDetector, ...] = (
    AuthorStatedLimitationDetector(),
    EmpiricalCoverageDetector(),
    CausalIdentificationDetector(),
    MechanismCompetitionDetector(),
    BoundaryHeterogeneityDetector(),
    ContradictionReplicationDetector(),
    MeasurementOperationalizationDetector(),
    TheoryMathematicalDetector(),
    GeneralizationTransportabilityDetector(),
    MethodDesignDetector(),
    DataCoverageDetector(),
    ScaleIntegrationDetector(),
    BenchmarkComparisonDetector(),
    TranslationImplementationDetector(),
)
DEFERRED_GAP_TYPES = tuple(
    gap_type for gap_type in GapType
    if gap_type not in {detector.gap_type for detector in GAP_DETECTOR_REGISTRY}
)


def _run_detector_for_contract(
    detector: GapDetector,
    contract_id: str,
    context: DetectionContext,
) -> tuple[str, str, dict[str, Any] | None, list[dict[str, Any]], dict[str, Any]]:
    """Evaluate one detector against one compact contract context in a worker.

    The task deliberately receives neither a project nor a whole research
    graph.  Each worker holds just one detached contract closure while it
    computes, and it performs no persistence or callback work.
    """

    started_at = time.monotonic()
    errors: list[dict[str, Any]] = []
    result: dict[str, Any] | None = None
    try:
        if not isinstance(context, DetectionContext):
            raise ValueError("DETECTOR_WORKER_CONTEXT_REQUIRED")
        cache_key = (
            _text(context.research_question_contract.get("contract_id")),
            _text(context.detector_context_fingerprint),
            _text(
                (context.contract_scoped_projection or {}).get(
                    "projection_fingerprint"
                )
            ),
        )
        current = _DETECTOR_WORKER_CONTEXT_CACHE.get(cache_key)
        if not isinstance(current, DetectionContext):
            current = validate_detection_context(context)
            _DETECTOR_WORKER_CONTEXT_CACHE[cache_key] = current
        with _prevalidated_detection_contexts_scope((current,)):
            result = detector.detect(current)
    except Exception as exc:
        errors.append(
            {
                "stage": "DETECTION_CONTEXT",
                "reason": "DETECTOR_EXECUTION_FAILED",
                "detector_id": detector.gap_type.value,
                "research_question_contract_id": contract_id,
                "detail": str(exc),
            }
        )
    return detector.gap_type.value, contract_id, result, errors, {
        "execution_location": "WORKER_PROCESS",
        "contract_count": 1,
        "elapsed_ms": round((time.monotonic() - started_at) * 1000, 3),
    }


def _run_detector_locally(
    detector: GapDetector,
    contexts_by_contract: dict[str, DetectionContext],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    started_at = time.monotonic()
    per_contract: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for contract_id, context in contexts_by_contract.items():
        try:
            per_contract.append(detector.detect(context))
        except Exception as exc:
            errors.append(
                {
                    "stage": "DETECTION_CONTEXT",
                    "reason": "DETECTOR_EXECUTION_FAILED",
                    "detector_id": detector.gap_type.value,
                    "research_question_contract_id": contract_id,
                    "detail": str(exc),
                }
            )
    return per_contract, errors, {
        "execution_location": "COORDINATOR_PROCESS",
        "contract_count": len(contexts_by_contract),
        "elapsed_ms": round((time.monotonic() - started_at) * 1000, 3),
    }


def _aggregate_detector_results(
    detector: GapDetector,
    results: list[dict[str, Any]],
    *,
    execution_metrics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    candidates = _dedupe_candidates(
        [
            candidate
            for result in results
            for candidate in result.get("candidates", [])
            if isinstance(candidate, dict)
        ]
    )
    diagnostics = [
        diagnostic
        for result in results
        for diagnostic in result.get("diagnostics", [])
        if isinstance(diagnostic, dict)
    ]
    rejected_patterns, rejection_summary = _merge_rejection_summaries(results)
    contract_retention = [
        item.get("candidate_retention")
        for item in results
        if isinstance(item, dict) and isinstance(item.get("candidate_retention"), dict)
    ]
    total_candidate_count = sum(
        int(item.get("total_candidate_count") or 0)
        for item in contract_retention
    )
    overflow_candidate_count = sum(
        int(item.get("overflow_candidate_count") or 0)
        for item in contract_retention
    )
    aggregate = {
        "schema_version": GAP_DETECTOR_RESULT_SCHEMA_VERSION,
        "detector_id": detector.gap_type.value,
        "detector_policy_version": detector.detector_policy_version,
        "gap_type": detector.gap_type.value,
        "contract_results": results,
        "candidates": candidates,
        "diagnostics": diagnostics,
        "rejected_patterns": rejected_patterns,
        "rejection_summary": rejection_summary,
        "candidate_retention": {
            "schema_version": "detector_candidate_retention_v3",
            "policy_version": DETECTOR_CANDIDATE_RETENTION_POLICY_VERSION,
            "contract_retention": contract_retention,
            "total_candidate_count": total_candidate_count,
            "selected_candidate_count": len(candidates),
            "overflow_candidate_count": overflow_candidate_count,
            "overflow_status": (
                "CANDIDATE_BUDGET_EXHAUSTED"
                if overflow_candidate_count
                else "NOT_EXHAUSTED"
            ),
            "scientific_conclusion_allowed": overflow_candidate_count == 0,
        },
        "execution_metrics": dict(execution_metrics or {}),
        "coverage_summary": {
            "contract_count": len(results),
            "candidate_count": len(candidates),
            "total_candidate_count": total_candidate_count,
            "overflow_candidate_count": overflow_candidate_count,
            "rejected_pattern_count": int(
                rejection_summary.get("total_rejection_count") or 0
            ),
            "retained_rejection_example_count": len(rejected_patterns),
        },
    }
    aggregate["detector_result_fingerprint"] = "sha256:" + sha256(
        "|".join(
            [
                GAP_DETECTOR_RESULT_SCHEMA_VERSION,
                detector.gap_type.value,
                detector.detector_policy_version,
                DETECTOR_CANDIDATE_RETENTION_POLICY_VERSION,
                *sorted(
                    _text(item.get("detector_result_fingerprint"))
                    for item in results
                    if isinstance(item, dict)
                ),
                *sorted(
                    _text(item.get("candidate_identity"))
                    for item in candidates
                    if isinstance(item, dict)
                ),
            ]
        ).encode("utf-8")
    ).hexdigest()
    return aggregate


def _source_unit_reference(unit: dict[str, Any]) -> dict[str, str]:
    """Return the immutable identity needed to rebind one source unit."""

    return {
        key: _text(unit.get(key))
        for key in (
            "assertion_id",
            "paper_id",
            "document_version_hash",
            "source_unit_id",
            "source_span_id",
            "excerpt_hash",
        )
    }


def _source_unit_reference_key(unit: dict[str, Any]) -> tuple[str, ...]:
    reference = _source_unit_reference(unit)
    return tuple(reference[key] for key in sorted(reference))


def _compact_source_bound_candidate_reference_v4(
    candidate: dict[str, Any],
) -> dict[str, Any]:
    """Store candidate bindings as V3 references rather than graph copies."""

    source = candidate if isinstance(candidate, dict) else {}
    context_ref = (
        source.get("detection_context_ref")
        if isinstance(source.get("detection_context_ref"), dict)
        else {}
    )
    if (
        context_ref.get("schema_version") != DETECTION_CONTEXT_SCHEMA_VERSION
        or not _text(context_ref.get("research_question_contract_id"))
        or not _text(context_ref.get("contract_revision"))
        or not isinstance(context_ref.get("graph_snapshot_ref"), dict)
    ):
        raise ValueError("DETECTOR_CANDIDATE_V3_CONTEXT_REFERENCE_REQUIRED")
    assertion_ids = _ids(source.get("source_assertion_ids"))
    source_units = [
        item for item in source.get("source_evidence_units", [])
        if isinstance(item, dict)
    ]
    if not assertion_ids or not source_units:
        raise ValueError("DETECTOR_CANDIDATE_SOURCE_BINDINGS_REQUIRED")
    source_refs = sorted(
        (_source_unit_reference(item) for item in source_units),
        key=_source_unit_reference_key,
    )
    if any(
        not reference["assertion_id"]
        or not reference["source_unit_id"]
        or not reference["source_span_id"]
        or not reference["document_version_hash"]
        for reference in source_refs
    ):
        raise ValueError("DETECTOR_CANDIDATE_IMMUTABLE_SOURCE_REFERENCE_REQUIRED")
    if set(assertion_ids) != {
        reference["assertion_id"] for reference in source_refs
    }:
        raise ValueError("DETECTOR_CANDIDATE_ASSERTION_SOURCE_REFERENCE_MISMATCH")
    bundle = (
        source.get("evidence_bundle")
        if isinstance(source.get("evidence_bundle"), dict)
        else {}
    )
    if bundle.get("schema_version") != "source_bound_gap_evidence_bundle_v3":
        raise ValueError("DETECTOR_CANDIDATE_SOURCE_BOUND_BUNDLE_V3_REQUIRED")
    compact = {
        str(key): copy.deepcopy(value)
        for key, value in source.items()
        if key not in {
            "research_question",
            "research_question_contract",
            "source_evidence_units",
            "source_lineage",
            "evidence_bundle",
        }
    }
    compact["candidate_payload_mode"] = DETECTOR_CANDIDATE_REFERENCE_MODE
    compact["detection_context_ref"] = copy.deepcopy(context_ref)
    compact["source_unit_refs"] = source_refs
    compact["evidence_bundle"] = {
        str(key): copy.deepcopy(value)
        for key, value in bundle.items()
        if key != "source_units"
    }
    return compact


def compact_detector_result_for_persistence_v4(
    detector_result: dict[str, Any],
) -> dict[str, Any]:
    """Create the only durable detector-result representation accepted by V3.

    Runtime results retain source-bound units for the immediate semantic audit.
    The persisted V4 envelope retains one context reference plus immutable
    assertion/span/version tuples and is rehydrated only from the current V3
    context during exact checkpoint reuse.
    """

    source = detector_result if isinstance(detector_result, dict) else {}
    if source.get("schema_version") != GAP_DETECTOR_RESULT_SCHEMA_VERSION:
        raise ValueError("GAP_DETECTOR_RESULT_V3_REQUIRED_FOR_PERSISTENCE")
    contract_results = source.get("contract_results")
    if not isinstance(contract_results, list):
        raise ValueError("MULTI_CONTRACT_GAP_DETECTOR_RESULT_V3_REQUIRED")
    compact_contract_results: list[dict[str, Any]] = []
    for contract_result in contract_results:
        if (
            not isinstance(contract_result, dict)
            or contract_result.get("schema_version")
            != GAP_DETECTOR_RESULT_SCHEMA_VERSION
        ):
            raise ValueError("CONTRACT_GAP_DETECTOR_RESULT_V3_REQUIRED")
        compact_contract = {
            str(key): copy.deepcopy(value)
            for key, value in contract_result.items()
            if key != "candidates"
        }
        compact_contract["candidates"] = [
            _compact_source_bound_candidate_reference_v4(candidate)
            for candidate in contract_result.get("candidates", [])
            if isinstance(candidate, dict)
        ]
        compact_contract_results.append(compact_contract)
    aggregate = {
        str(key): copy.deepcopy(value)
        for key, value in source.items()
        if key not in {
            "schema_version",
            "contract_results",
            "candidates",
            "diagnostics",
            "rejected_patterns",
            "rejection_summary",
        }
    }
    return {
        "schema_version": DETECTOR_RESULT_REFERENCE_ARTIFACT_SCHEMA_VERSION,
        "source_result_schema_version": GAP_DETECTOR_RESULT_SCHEMA_VERSION,
        "candidate_payload_mode": DETECTOR_CANDIDATE_REFERENCE_MODE,
        "aggregate": aggregate,
        "contract_results": compact_contract_results,
    }


def _hydrate_source_bound_candidate_reference_v4(
    candidate: dict[str, Any],
    contexts_by_contract: dict[str, DetectionContext],
) -> dict[str, Any]:
    """Rebuild a candidate only from its exact validated V3 context."""

    source = candidate if isinstance(candidate, dict) else {}
    if source.get("candidate_payload_mode") != DETECTOR_CANDIDATE_REFERENCE_MODE:
        raise ValueError("DETECTOR_CANDIDATE_REFERENCE_PAYLOAD_V4_REQUIRED")
    if any(
        key in source
        for key in (
            "research_question",
            "research_question_contract",
            "source_evidence_units",
            "source_lineage",
        )
    ):
        raise ValueError("DETECTOR_CANDIDATE_REFERENCE_CONTAINS_DUPLICATED_GRAPH_DATA")
    context_ref = (
        source.get("detection_context_ref")
        if isinstance(source.get("detection_context_ref"), dict)
        else {}
    )
    contract_id = _text(context_ref.get("research_question_contract_id"))
    context = contexts_by_contract.get(contract_id)
    if not isinstance(context, DetectionContext):
        raise ValueError("DETECTOR_CANDIDATE_REFERENCE_CONTRACT_NOT_CURRENT")
    if detection_context_ref(context) != context_ref:
        raise ValueError("DETECTOR_CANDIDATE_REFERENCE_CONTEXT_MISMATCH")
    assertion_ids = _ids(source.get("source_assertion_ids"))
    source_refs = source.get("source_unit_refs")
    if not assertion_ids or not isinstance(source_refs, list):
        raise ValueError("DETECTOR_CANDIDATE_REFERENCE_SOURCE_BINDINGS_REQUIRED")
    normalized_refs = [
        _source_unit_reference(item)
        for item in source_refs
        if isinstance(item, dict)
    ]
    if len(normalized_refs) != len(source_refs) or any(
        not item["assertion_id"]
        or not item["source_unit_id"]
        or not item["source_span_id"]
        or not item["document_version_hash"]
        for item in normalized_refs
    ):
        raise ValueError("DETECTOR_CANDIDATE_REFERENCE_SOURCE_IDS_INVALID")
    units, _ = _normalized_context_source_units(context, assertion_ids)
    hydrated_refs = sorted(
        (_source_unit_reference(item) for item in units),
        key=_source_unit_reference_key,
    )
    if sorted(normalized_refs, key=_source_unit_reference_key) != hydrated_refs:
        raise ValueError("DETECTOR_CANDIDATE_REFERENCE_SOURCE_REBIND_MISMATCH")
    bundle = (
        source.get("evidence_bundle")
        if isinstance(source.get("evidence_bundle"), dict)
        else {}
    )
    if bundle.get("schema_version") != "source_bound_gap_evidence_bundle_v3":
        raise ValueError("DETECTOR_CANDIDATE_REFERENCE_BUNDLE_REBIND_MISMATCH")
    graph_contract = (
        source.get("evidence_graph_contract")
        if isinstance(source.get("evidence_graph_contract"), dict)
        else {}
    )
    if (
        _text(graph_contract.get("research_question_contract_id")) != contract_id
        or _text(graph_contract.get("research_question_contract_revision"))
        != _text(context.research_question_contract.get("contract_revision"))
        or _ids(graph_contract.get("assertion_ids")) != assertion_ids
        or _ids(graph_contract.get("source_span_ids"))
        != _ids([item.get("source_span_id") for item in units])
        or _ids(graph_contract.get("document_version_hashes"))
        != _ids([item.get("document_version_hash") for item in units])
    ):
        raise ValueError("DETECTOR_CANDIDATE_REFERENCE_GRAPH_BINDING_MISMATCH")
    hydrated = {
        str(key): copy.deepcopy(value)
        for key, value in source.items()
        if key not in {"candidate_payload_mode", "source_unit_refs"}
    }
    hydrated["research_question_contract"] = copy.deepcopy(
        context.research_question_contract
    )
    hydrated["research_question"] = copy.deepcopy(
        context.research_question_contract.get("research_question") or {}
    )
    hydrated["source_evidence_units"] = copy.deepcopy(units)
    hydrated["source_lineage"] = copy.deepcopy(units)
    hydrated_bundle = {
        str(key): copy.deepcopy(value)
        for key, value in bundle.items()
        if key != "source_units"
    }
    hydrated_bundle["source_units"] = copy.deepcopy(units)
    hydrated["evidence_bundle"] = hydrated_bundle
    return hydrated


def hydrate_detector_result_from_persistence_v4(
    persisted_result: dict[str, Any],
    contexts_by_contract: dict[str, DetectionContext],
) -> dict[str, Any]:
    """Rehydrate one V4 reference artifact into the current V3 result shape."""

    source = persisted_result if isinstance(persisted_result, dict) else {}
    if (
        source.get("schema_version")
        != DETECTOR_RESULT_REFERENCE_ARTIFACT_SCHEMA_VERSION
        or source.get("source_result_schema_version")
        != GAP_DETECTOR_RESULT_SCHEMA_VERSION
        or source.get("candidate_payload_mode")
        != DETECTOR_CANDIDATE_REFERENCE_MODE
    ):
        raise ValueError("DETECTOR_RESULT_REFERENCE_ARTIFACT_V4_REQUIRED")
    aggregate = source.get("aggregate") if isinstance(source.get("aggregate"), dict) else {}
    contract_results = source.get("contract_results")
    if not isinstance(contract_results, list):
        raise ValueError("DETECTOR_RESULT_REFERENCE_CONTRACT_RESULTS_REQUIRED")
    hydrated_contract_results: list[dict[str, Any]] = []
    for contract_result in contract_results:
        if (
            not isinstance(contract_result, dict)
            or contract_result.get("schema_version")
            != GAP_DETECTOR_RESULT_SCHEMA_VERSION
        ):
            raise ValueError("DETECTOR_RESULT_REFERENCE_CONTRACT_SCHEMA_MISMATCH")
        hydrated_contract = {
            str(key): copy.deepcopy(value)
            for key, value in contract_result.items()
            if key != "candidates"
        }
        hydrated_contract["candidates"] = [
            _hydrate_source_bound_candidate_reference_v4(candidate, contexts_by_contract)
            for candidate in contract_result.get("candidates", [])
            if isinstance(candidate, dict)
        ]
        hydrated_contract_results.append(hydrated_contract)
    candidates = _dedupe_candidates(
        [
            candidate
            for result in hydrated_contract_results
            for candidate in result.get("candidates", [])
            if isinstance(candidate, dict)
        ]
    )
    diagnostics = [
        diagnostic
        for result in hydrated_contract_results
        for diagnostic in result.get("diagnostics", [])
        if isinstance(diagnostic, dict)
    ]
    rejected_patterns, rejection_summary = _merge_rejection_summaries(
        hydrated_contract_results
    )
    hydrated = {
        "schema_version": GAP_DETECTOR_RESULT_SCHEMA_VERSION,
        **copy.deepcopy(aggregate),
        "contract_results": hydrated_contract_results,
        "candidates": candidates,
        "diagnostics": diagnostics,
        "rejected_patterns": rejected_patterns,
        "rejection_summary": rejection_summary,
    }
    if (
        hydrated.get("schema_version") != GAP_DETECTOR_RESULT_SCHEMA_VERSION
        or not _text(hydrated.get("detector_id"))
        or not _text(hydrated.get("detector_policy_version"))
        or not _text(hydrated.get("detector_result_fingerprint")).startswith("sha256:")
    ):
        raise ValueError("DETECTOR_RESULT_REFERENCE_AGGREGATE_METADATA_INVALID")
    return hydrated


def _current_detector_input_fingerprints(
    detector: GapDetector,
    contexts_by_contract: dict[str, DetectionContext],
) -> dict[str, str]:
    fingerprints: dict[str, str] = {}
    for contract_id, context in contexts_by_contract.items():
        with detection_context_validation_scope(context):
            fingerprints[contract_id] = detector_input_fingerprint(
                context,
                detector_id=detector.gap_type.value,
                detector_policy_version=detector.detector_policy_version,
            )
    return fingerprints


def _load_current_v3_detector_result(
    *,
    checkpoint: dict[str, Any],
    detector: GapDetector,
    graph_snapshot: dict[str, Any],
    contexts_by_contract: dict[str, DetectionContext],
    load_detector_result: Any,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Load only an exact current-V3 detector result, never an adapter.

    The validator deliberately rejects every V1/V2 checkpoint, stale graph,
    policy mismatch, and incomplete multi-contract result.  A valid result is
    already immutable and source-bound, so rerunning it would add cost without
    producing new scientific information.
    """

    if checkpoint.get("schema_version") != "tanxi_run_checkpoint_v3":
        return None, {
            "stage": "TANXI_DETECTOR_CHECKPOINT",
            "reason": "CHECKPOINT_SCHEMA_V3_REQUIRED",
        }
    snapshot_ref = graph_snapshot_ref(graph_snapshot)
    if _text(checkpoint.get("input_fingerprint")) != _text(
        snapshot_ref.get("input_fingerprint")
    ):
        return None, {
            "stage": "TANXI_DETECTOR_CHECKPOINT",
            "reason": "STALE_V3_DETECTOR_CHECKPOINT_INPUT_REJECTED",
            "detector_id": detector.gap_type.value,
        }
    result_refs = checkpoint.get("detector_result_refs")
    result_refs = result_refs if isinstance(result_refs, dict) else {}
    detector_id = detector.gap_type.value
    result_ref = result_refs.get(detector_id)
    if not isinstance(result_ref, dict):
        return None, None
    if not callable(load_detector_result):
        return None, {
            "stage": "TANXI_DETECTOR_CHECKPOINT",
            "reason": "V3_DETECTOR_RESULT_LOADER_REQUIRED",
            "detector_id": detector_id,
        }
    try:
        stored = load_detector_result(detector_id, result_ref)
    except Exception as exc:
        return None, {
            "stage": "TANXI_DETECTOR_CHECKPOINT",
            "reason": "V3_DETECTOR_RESULT_LOAD_FAILED",
            "detector_id": detector_id,
            "detail": str(exc),
        }
    if (
        isinstance(stored, dict)
        and stored.get("schema_version")
        == DETECTOR_RESULT_REFERENCE_ARTIFACT_SCHEMA_VERSION
    ):
        try:
            stored = hydrate_detector_result_from_persistence_v4(
                stored,
                contexts_by_contract,
            )
        except ValueError as exc:
            return None, {
                "stage": "TANXI_DETECTOR_CHECKPOINT",
                "reason": "STALE_OR_INVALID_V4_DETECTOR_REFERENCE_ARTIFACT_REJECTED",
                "detector_id": detector_id,
                "detail": str(exc),
            }
    if not isinstance(stored, dict) or stored.get("schema_version") != GAP_DETECTOR_RESULT_SCHEMA_VERSION:
        return None, {
            "stage": "TANXI_DETECTOR_CHECKPOINT",
            "reason": "V3_DETECTOR_RESULT_SCHEMA_REQUIRED",
            "detector_id": detector_id,
        }
    if (
        _text(stored.get("detector_id")) != detector_id
        or _text(stored.get("detector_policy_version"))
        != _text(detector.detector_policy_version)
        or not _text(stored.get("detector_result_fingerprint")).startswith("sha256:")
    ):
        return None, {
            "stage": "TANXI_DETECTOR_CHECKPOINT",
            "reason": "STALE_V3_DETECTOR_POLICY_OR_RESULT_REJECTED",
            "detector_id": detector_id,
        }
    retention = stored.get("candidate_retention")
    if (
        not isinstance(retention, dict)
        or _text(retention.get("policy_version"))
        != DETECTOR_CANDIDATE_RETENTION_POLICY_VERSION
    ):
        return None, {
            "stage": "TANXI_DETECTOR_CHECKPOINT",
            "reason": "STALE_V3_DETECTOR_CANDIDATE_RETENTION_POLICY_REJECTED",
            "detector_id": detector_id,
        }
    current_inputs = _current_detector_input_fingerprints(
        detector,
        contexts_by_contract,
    )
    contract_results = stored.get("contract_results")
    if not isinstance(contract_results, list):
        return None, {
            "stage": "TANXI_DETECTOR_CHECKPOINT",
            "reason": "V3_MULTI_CONTRACT_DETECTOR_RESULT_REQUIRED",
            "detector_id": detector_id,
        }
    stored_inputs: dict[str, str] = {}
    for item in contract_results:
        if not isinstance(item, dict):
            continue
        context_ref = item.get("detection_context_ref")
        if not isinstance(context_ref, dict):
            continue
        contract_id = _text(context_ref.get("research_question_contract_id"))
        if not contract_id or context_ref.get("graph_snapshot_ref") != snapshot_ref:
            continue
        context = contexts_by_contract.get(contract_id)
        if not isinstance(context, DetectionContext):
            continue
        if _text(context_ref.get("contract_revision")) != _text(
            context.research_question_contract.get("contract_revision")
        ):
            continue
        stored_inputs[contract_id] = _text(item.get("detector_input_fingerprint"))
    if stored_inputs != current_inputs:
        return None, {
            "stage": "TANXI_DETECTOR_CHECKPOINT",
            "reason": "STALE_V3_DETECTOR_INPUT_REJECTED",
            "detector_id": detector_id,
        }
    return stored, None


def run_registered_gap_detectors(
    project: dict[str, Any],
    graph_snapshot: dict[str, Any],
    corpus_summary: dict[str, Any] | None = None,
    *,
    checkpoint: dict[str, Any] | None = None,
    on_detector_complete: Any | None = None,
    load_detector_result: Any | None = None,
    max_workers: int = 1,
) -> dict[str, Any]:
    """Run real detectors on strict V3 DetectionContexts only.

    ``project`` and ``corpus_summary`` remain accepted at this orchestration
    boundary for caller compatibility, but no detector reads them.  Contexts
    are constructed once per current V3 contract and detector checkpoints are
    reused only after exact graph, revision, policy, and multi-context input
    verification.  V1/V2 artifacts have no adapter on this path.
    """

    del project, corpus_summary
    run_started_at = time.monotonic()
    if not isinstance(graph_snapshot, dict) or graph_snapshot.get("schema_version") != RESEARCH_EVIDENCE_GRAPH_SCHEMA_VERSION:
        return {
            "schema_version": GAP_DETECTOR_REGISTRY_RUN_SCHEMA_VERSION,
            "execution_mode": "REJECTED_NON_V3_RESEARCH_GRAPH",
            "candidates": [],
            "diagnostics": [
                {
                    "stage": "DETECTION_CONTEXT",
                    "reason": "RESEARCH_EVIDENCE_GRAPH_V3_REQUIRED",
                    "received_schema_version": _text(
                        graph_snapshot.get("schema_version") if isinstance(graph_snapshot, dict) else ""
                    ),
                }
            ],
            "candidate_count_by_detector_type": {item.value: 0 for item in GapType},
            "registered_gap_types": [item.gap_type.value for item in GAP_DETECTOR_REGISTRY],
            "deferred_gap_types": [item.value for item in DEFERRED_GAP_TYPES],
        }
    diagnostics: list[dict[str, Any]] = []
    normalized_checkpoint = checkpoint if isinstance(checkpoint, dict) else {}
    checkpoint_provided = isinstance(checkpoint, dict)
    context_build_started_at = time.monotonic()
    try:
        contexts_by_contract = build_contract_detection_contexts_v3(graph_snapshot)
    except ValueError as exc:
        return {
            "schema_version": GAP_DETECTOR_REGISTRY_RUN_SCHEMA_VERSION,
            "execution_mode": "CONTRACT_CONTEXT_BUILD_FAILED",
            "graph_snapshot_ref": graph_snapshot_ref(graph_snapshot),
            "candidates": [],
            "diagnostics": [{
                "stage": "DETECTION_CONTEXT",
                "reason": "DETECTION_CONTEXT_BUILD_OR_VALIDATION_FAILED",
                "detail": str(exc),
            }],
            "candidate_count_by_detector_type": {item.value: 0 for item in GapType},
            "registered_gap_types": [item.gap_type.value for item in GAP_DETECTOR_REGISTRY],
            "deferred_gap_types": [item.value for item in DEFERRED_GAP_TYPES],
            "detector_results": {},
            "completed_detector_ids": [],
        }
    context_build_elapsed_ms = round(
        (time.monotonic() - context_build_started_at) * 1000,
        3,
    )
    registry = tuple(GAP_DETECTOR_REGISTRY)
    reusable_results: dict[str, dict[str, Any]] = {}
    pending_detectors: list[GapDetector] = []
    with _prevalidated_detection_contexts_scope(
        tuple(contexts_by_contract.values())
    ):
        for detector in registry:
            aggregate: dict[str, Any] | None = None
            checkpoint_diagnostic: dict[str, Any] | None = None
            if checkpoint_provided:
                aggregate, checkpoint_diagnostic = _load_current_v3_detector_result(
                    checkpoint=normalized_checkpoint,
                    detector=detector,
                    graph_snapshot=graph_snapshot,
                    contexts_by_contract=contexts_by_contract,
                    load_detector_result=load_detector_result,
                )
            if checkpoint_diagnostic is not None:
                diagnostics.append(checkpoint_diagnostic)
            if aggregate is not None:
                reusable_results[detector.gap_type.value] = aggregate
                diagnostics.append({
                    "stage": "TANXI_DETECTOR_CHECKPOINT",
                    "reason": "REUSED_CURRENT_V3_DETECTOR_RESULT",
                    "detector_id": detector.gap_type.value,
                })
            else:
                pending_detectors.append(detector)

    computed_results: dict[str, dict[str, Any]] = {}
    worker_count = max(1, min(DEFAULT_DETECTOR_WORKERS, int(max_workers or 1)))
    contract_ids = tuple(contexts_by_contract)
    if worker_count > 1 and len(pending_detectors) > 1:
        with ProcessPoolExecutor(
            max_workers=min(worker_count, len(pending_detectors)),
        ) as executor:
            for batch_start in range(0, len(pending_detectors), worker_count):
                batch = pending_detectors[batch_start:batch_start + worker_count]
                futures = {
                    executor.submit(
                        _run_detector_for_contract,
                        detector,
                        contract_id,
                        contexts_by_contract[contract_id],
                    ): (detector, contract_id)
                    for detector in batch
                    for contract_id in contract_ids
                }
                batch_outputs: dict[
                    str,
                    dict[
                        str,
                        tuple[
                            dict[str, Any] | None,
                            list[dict[str, Any]],
                            dict[str, Any],
                        ],
                    ],
                ] = defaultdict(dict)
                for future, (detector, contract_id) in futures.items():
                    try:
                        (
                            detector_id,
                            completed_contract_id,
                            contract_result,
                            execution_errors,
                            execution_metrics,
                        ) = future.result()
                    except Exception as exc:
                        batch_outputs[detector.gap_type.value][contract_id] = (
                            None,
                            [
                                {
                                    "stage": "DETECTOR_EXECUTION",
                                    "reason": "DETECTOR_WORKER_FAILED",
                                    "detector_id": detector.gap_type.value,
                                    "research_question_contract_id": contract_id,
                                    "detail": str(exc),
                                }
                            ],
                            {
                                "execution_location": "WORKER_PROCESS",
                                "contract_count": 1,
                                "elapsed_ms": 0.0,
                                "status": "WORKER_FAILED",
                            },
                        )
                        continue
                    batch_outputs[detector_id][completed_contract_id] = (
                        contract_result,
                        execution_errors,
                        execution_metrics,
                    )
                for detector in batch:
                    per_contract: list[dict[str, Any]] = []
                    execution_errors: list[dict[str, Any]] = []
                    contract_elapsed_ms = 0.0
                    for contract_id in contract_ids:
                        contract_result, contract_errors, contract_metrics = (
                            batch_outputs[detector.gap_type.value].get(
                                contract_id,
                                (
                                    None,
                                    [
                                        {
                                            "stage": "DETECTOR_EXECUTION",
                                            "reason": "DETECTOR_WORKER_RESULT_MISSING",
                                            "detector_id": detector.gap_type.value,
                                            "research_question_contract_id": contract_id,
                                        }
                                    ],
                                    {
                                        "execution_location": "WORKER_PROCESS",
                                        "contract_count": 1,
                                        "elapsed_ms": 0.0,
                                        "status": "WORKER_RESULT_MISSING",
                                    },
                                ),
                            )
                        )
                        if isinstance(contract_result, dict):
                            per_contract.append(contract_result)
                        execution_errors.extend(contract_errors)
                        contract_elapsed_ms += float(
                            contract_metrics.get("elapsed_ms") or 0.0
                        )
                    diagnostics.extend(execution_errors)
                    computed_results[detector.gap_type.value] = (
                        _aggregate_detector_results(
                            detector,
                            per_contract,
                            execution_metrics={
                                "execution_location": "WORKER_PROCESS",
                                "contract_count": len(contract_ids),
                                "elapsed_ms": round(contract_elapsed_ms, 3),
                                "worker_count": min(worker_count, len(batch)),
                            },
                        )
                    )
    else:
        with _prevalidated_detection_contexts_scope(
            tuple(contexts_by_contract.values())
        ):
            for detector in pending_detectors:
                per_contract, execution_errors, execution_metrics = _run_detector_locally(
                    detector,
                    contexts_by_contract,
                )
                diagnostics.extend(execution_errors)
                computed_results[detector.gap_type.value] = _aggregate_detector_results(
                    detector,
                    per_contract,
                    execution_metrics=execution_metrics,
                )

    detector_results: dict[str, dict[str, Any]] = {}
    all_candidates: list[dict[str, Any]] = []
    for detector in registry:
        aggregate = reusable_results.get(detector.gap_type.value) or computed_results.get(
            detector.gap_type.value
        )
        if not isinstance(aggregate, dict):
            aggregate = _aggregate_detector_results(detector, [])
        detector_results[detector.gap_type.value] = aggregate
        all_candidates.extend(aggregate["candidates"])
        diagnostics.extend(aggregate["diagnostics"])
        diagnostics.extend(
            {
                "stage": "DETECTOR_PATTERN_REJECTED",
                "detector_id": detector.gap_type.value,
                **item,
            }
            for item in aggregate["rejected_patterns"]
        )
        if callable(on_detector_complete):
            on_detector_complete(
                detector.gap_type.value,
                {
                    "schema_version": GAP_DETECTOR_RESULT_SCHEMA_VERSION,
                    "graph_snapshot_ref": graph_snapshot_ref(graph_snapshot),
                    "detector_result": aggregate,
                    "completed_detector_ids": list(detector_results),
                },
            )
    deduped_candidates = _dedupe_candidates(all_candidates)
    counts = Counter(_text(item.get("gap_type")) for item in deduped_candidates)
    return {
        "schema_version": GAP_DETECTOR_REGISTRY_RUN_SCHEMA_VERSION,
        "execution_mode": "CONTRACT_SCOPED_DETECTION_CONTEXT_V3",
        "graph_snapshot_ref": graph_snapshot_ref(graph_snapshot),
        "candidates": deduped_candidates,
        "diagnostics": diagnostics,
        "candidate_count_by_detector_type": {
            item.value: int(counts.get(item.value, 0)) for item in GapType
        },
        "registered_gap_types": [item.gap_type.value for item in GAP_DETECTOR_REGISTRY],
        "deferred_gap_types": [item.value for item in DEFERRED_GAP_TYPES],
        "detector_results": detector_results,
        "completed_detector_ids": list(detector_results),
        "execution_metrics": {
            "context_build_elapsed_ms": context_build_elapsed_ms,
            "detector_execution_elapsed_ms": round(
                (time.monotonic() - run_started_at) * 1000,
                3,
            ),
            "worker_count": worker_count,
            "pending_detector_count": len(pending_detectors),
            "reused_detector_count": len(reusable_results),
            "execution_model": (
                "TWO_PROCESS_COMPUTE_SINGLE_COORDINATOR_PERSIST"
                if worker_count > 1 and len(pending_detectors) > 1
                else "SINGLE_PROCESS_COMPUTE_SINGLE_COORDINATOR_PERSIST"
            ),
        },
    }
