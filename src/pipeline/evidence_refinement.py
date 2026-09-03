"""Conditional, second-stage retrieval for unresolved scientific evidence.

The first retrieval stage is driven strictly by the declared SH slots.  This
module does not add a second unconditional search fan-out: it emits a bounded
refinement task only when the evidence ledger reports an admissible candidate,
a conservative conflict signal, or an unresolved required slot.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

from src.pipeline.evidence_coverage_ledger import paper_identity
from src.pipeline.retrieval_lanes import build_query_lanes


EVIDENCE_REFINEMENT_SCHEMA_VERSION = "evidence_refinement_v1"
EVIDENCE_REFINEMENT_EXECUTION_SCHEMA_VERSION = "evidence_refinement_execution_v1"

_REFINEMENT_SPECS: dict[str, dict[str, Any]] = {
    "BOUNDARY_REFINEMENT": {
        "evidence_mode": "boundary",
        "query_terms": (
            "boundary condition",
            "heterogeneity",
            "failure mode",
            "limitation",
        ),
    },
    "REPLICATION_CONTRADICTION_RESOLUTION": {
        "evidence_mode": "empirical",
        "query_terms": (
            "independent replication",
            "contradictory result",
            "reproducibility",
            "conflicting finding",
        ),
    },
    "MEASUREMENT_VALIDATION": {
        "evidence_mode": "benchmark",
        "query_terms": (
            "measurement validation",
            "calibration",
            "reference measurement",
            "measurement error",
        ),
    },
    "GENERALIZATION_TEST": {
        "evidence_mode": "empirical",
        "query_terms": (
            "external validation",
            "out-of-sample",
            "generalization",
            "transferability",
        ),
    },
}

_BOUNDARY_TERMS = (
    "boundary",
    "failure",
    "bias",
    "counterexample",
    "heterogeneity",
    "limitation",
)
_MEASUREMENT_TERMS = (
    "measure",
    "measurement",
    "metric",
    "endpoint",
    "proxy",
    "calibration",
    "mapping",
    "validation",
)
_GENERALIZATION_TERMS = (
    "source_system",
    "target_system",
    "shift",
    "variation",
    "external_validation",
    "population",
    "deployment",
    "scale",
    "transport",
    "generalization",
)
_REFINEMENT_EXPLICIT_SLOT_TARGETS = {
    "BOUNDARY_REFINEMENT": frozenset(
        {
            "base_relation",
            "boundary_variable",
            "condition_a",
            "condition_b",
            "boundary_case",
            "failure_or_bias",
            "falsification_or_counterexample",
            "comparable_endpoint",
        }
    ),
    "REPLICATION_CONTRADICTION_RESOLUTION": frozenset(
        {
            "shared_claim",
            "result_a",
            "result_b",
            "comparability_axes",
        }
    ),
    "MEASUREMENT_VALIDATION": frozenset(
        {
            "construct",
            "proxy_or_measure",
            "reference_or_target_measure",
            "mapping_or_calibration",
            "comparable_endpoint",
            "evaluation_criterion",
        }
    ),
    "GENERALIZATION_TEST": frozenset(
        {
            "source_system",
            "target_system",
            "shift_or_variation",
            "external_validation",
        }
    ),
}
_RESOLUTION_TARGETS = {
    "BOUNDARY_REFINEMENT": "boundary_or_failure_mode",
    "REPLICATION_CONTRADICTION_RESOLUTION": "conflict_or_comparability",
    "MEASUREMENT_VALIDATION": "measurement_validity",
    "GENERALIZATION_TEST": "transportability",
}
_SCOPE_QUERY_KEYS = (
    "research_object",
    "population_or_system",
    "condition_or_regime",
    "intervention_or_input",
    "comparison_frame",
    "outcome_or_construct",
    "measurement_or_endpoint",
    "method_or_design",
    "dataset_or_corpus",
    "time_or_scale",
    "theoretical_assumptions",
    "deployment_context",
)


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _texts(value: Any, *, limit: int = 12) -> list[str]:
    values = value if isinstance(value, (list, tuple, set)) else [value]
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = re.sub(r"\s+", " ", str(value or "").strip())[:300]
        key = text.casefold()
        if not text or key in seen:
            continue
        seen.add(key)
        result.append(text)
        if len(result) >= limit:
            break
    return result


def _unique(values: Sequence[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


def _contains_any(value: Any, terms: Sequence[str]) -> bool:
    text = re.sub(r"[^\w]+", " ", str(value or "").casefold())
    return any(term.casefold() in text for term in terms)


def _scope_terms(scientific_scope: Mapping[str, Any]) -> list[str]:
    values: list[str] = []
    for key in _SCOPE_QUERY_KEYS:
        values.extend(_texts(scientific_scope.get(key), limit=4))
    return _unique(values)


def _reports_by_subhypothesis(coverage_ledger: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    reports: dict[str, dict[str, Any]] = {}
    for raw_report in _mapping(coverage_ledger).get("subhypotheses", []):
        report = _mapping(raw_report)
        identifier = str(report.get("sub_hypothesis_id") or "")
        if identifier:
            reports[identifier] = report
    return reports


def _trigger_summary(report: Mapping[str, Any]) -> dict[str, Any]:
    slot_ledger = _mapping(report.get("slot_ledger"))
    evidence_ids: list[str] = []
    background_ids: list[str] = []
    conflict_ids: list[str] = []
    missing_slot_task_ids: list[str] = []
    missing_slot_names: list[str] = []
    for slot_name, raw_slot in slot_ledger.items():
        slot = _mapping(raw_slot)
        if slot.get("missing"):
            missing_slot_names.append(str(slot_name))
            task_id = str(slot.get("task_id") or "")
            if task_id:
                missing_slot_task_ids.append(task_id)
        for raw_record in slot.get("covered_by", []):
            record = _mapping(raw_record)
            paper_id = str(record.get("paper_id") or "")
            evidence_role = str(record.get("evidence_role") or "")
            if paper_id and evidence_role != "BACKGROUND_CONTEXT":
                evidence_ids.append(paper_id)
            elif paper_id:
                background_ids.append(paper_id)
            evidence_types = set(_texts(record.get("confirmed_evidence_types"), limit=12))
            if evidence_types & {"negative_result", "failure_analysis"} and paper_id:
                conflict_ids.append(paper_id)
    admissibility = _mapping(report.get("conclusion_admissibility"))
    scope = _mapping(admissibility.get("scope"))
    question_kind = str(report.get("question_kind") or "")
    if question_kind == "REPLICATION_CONTRADICTION" and evidence_ids:
        conflict_ids.extend(evidence_ids)
    return {
        "real_evidence_candidate_ids": _unique(evidence_ids),
        "background_candidate_ids": _unique(background_ids),
        "conflict_candidate_ids": _unique(conflict_ids),
        "missing_slot_task_ids": _unique(missing_slot_task_ids),
        "missing_slot_names": _unique(missing_slot_names),
        "scope_insufficient": not bool(scope.get("sufficient")),
    }


def _task_terms(
    subhypothesis: Mapping[str, Any],
    *,
    target_slot_names: Sequence[str],
    refinement_kind: str,
) -> list[str]:
    definitions = _mapping(subhypothesis.get("slot_definitions"))
    slot_terms: list[str] = []
    for slot_name in target_slot_names:
        definition = _mapping(definitions.get(slot_name))
        slot_terms.extend(_texts(definition.get("retrieval_concepts"), limit=4))
    specification = _REFINEMENT_SPECS[refinement_kind]
    return _unique(
        [
            str(subhypothesis.get("question") or "").strip(),
            *_scope_terms(_mapping(subhypothesis.get("scientific_scope"))),
            *slot_terms,
            *specification["query_terms"],
        ]
    )[:18]


def _slot_is_refinement_target(slot_name: str, refinement_kind: str) -> bool:
    normalized_slot = str(slot_name or "").casefold()
    if normalized_slot in _REFINEMENT_EXPLICIT_SLOT_TARGETS[refinement_kind]:
        return True
    if refinement_kind == "BOUNDARY_REFINEMENT":
        return _contains_any(normalized_slot, _BOUNDARY_TERMS)
    if refinement_kind == "REPLICATION_CONTRADICTION_RESOLUTION":
        return _contains_any(
            normalized_slot,
            ("replication", "contradiction", "claim", "result", "comparability"),
        )
    if refinement_kind == "MEASUREMENT_VALIDATION":
        return _contains_any(normalized_slot, _MEASUREMENT_TERMS)
    return _contains_any(normalized_slot, _GENERALIZATION_TERMS)


def _refinement_slot_targets(
    subhypothesis: Mapping[str, Any],
    signals: Mapping[str, Any],
    refinement_kind: str,
) -> tuple[list[str], list[str], list[str], list[str]]:
    """Return all relevant slots, then missing slots and their task IDs.

    A second-stage task may only recover a missing slot in its own explicit
    scientific role.  ``resolution_slot_task_ids`` is intentionally separate:
    it keeps conflict/comparability review auditable without presenting that
    review as automatic coverage of an already declared slot.
    """

    tasks_by_slot = {
        str(task.get("slot_name") or ""): _mapping(task)
        for task in subhypothesis.get("slot_recovery_tasks", [])
        if isinstance(task, Mapping) and str(task.get("slot_name") or "")
    }
    missing_slots = set(_texts(signals.get("missing_slot_names"), limit=20))
    all_target_slots = [
        slot_name
        for slot_name in tasks_by_slot
        if _slot_is_refinement_target(slot_name, refinement_kind)
    ]
    missing_target_slots = [
        slot_name for slot_name in all_target_slots if slot_name in missing_slots
    ]
    missing_target_task_ids = [
        str(tasks_by_slot[slot_name].get("task_id") or "")
        for slot_name in missing_target_slots
        if str(tasks_by_slot[slot_name].get("task_id") or "")
    ]
    resolution_target_slots = (
        list(tasks_by_slot)
        if refinement_kind == "REPLICATION_CONTRADICTION_RESOLUTION"
        and not all_target_slots
        else all_target_slots
    )
    resolution_task_ids = [
        str(tasks_by_slot[slot_name].get("task_id") or "")
        for slot_name in resolution_target_slots
        if str(tasks_by_slot[slot_name].get("task_id") or "")
    ]
    return (
        all_target_slots,
        missing_target_slots,
        _unique(missing_target_task_ids),
        _unique(resolution_task_ids),
    )


def _activation_reasons(
    subhypothesis: Mapping[str, Any],
    signals: Mapping[str, Any],
    refinement_kind: str,
) -> list[str]:
    question_kind = str(subhypothesis.get("question_kind") or "")
    scope = _mapping(subhypothesis.get("scientific_scope"))
    missing_names = _texts(signals.get("missing_slot_names"), limit=16)
    has_evidence = bool(signals.get("real_evidence_candidate_ids"))
    has_conflict = bool(signals.get("conflict_candidate_ids"))
    has_missing = bool(missing_names)
    scope_insufficient = bool(signals.get("scope_insufficient"))
    missing_text = " ".join(missing_names)
    scope_text = " ".join(
        _scope_terms(scope)
        + [key for key, value in scope.items() if _texts(value, limit=1)]
    )

    if refinement_kind == "BOUNDARY_REFINEMENT":
        boundary_signal = (
            question_kind == "BOUNDARY_HETEROGENEITY"
            or has_conflict
            or _contains_any(missing_text, _BOUNDARY_TERMS)
        )
        return _unique(
            [
                "conflict_signal" if has_conflict else "",
                "boundary_question" if question_kind == "BOUNDARY_HETEROGENEITY" else "",
                "boundary_related_missing_slot"
                if _contains_any(missing_text, _BOUNDARY_TERMS)
                else "",
            ]
            if boundary_signal and (has_evidence or has_conflict or has_missing)
            else []
        )
    if refinement_kind == "REPLICATION_CONTRADICTION_RESOLUTION":
        replication_signal = question_kind == "REPLICATION_CONTRADICTION" or has_conflict
        return _unique(
            [
                "conflict_signal" if has_conflict else "",
                "replication_contradiction_question"
                if question_kind == "REPLICATION_CONTRADICTION"
                else "",
            ]
            if replication_signal and (has_evidence or has_conflict or has_missing)
            else []
        )
    if refinement_kind == "MEASUREMENT_VALIDATION":
        measurement_signal = (
            question_kind == "MEASUREMENT_VALIDITY"
            or _contains_any(missing_text, _MEASUREMENT_TERMS)
            or _contains_any(scope_text, _MEASUREMENT_TERMS)
        )
        return _unique(
            [
                "measurement_question" if question_kind == "MEASUREMENT_VALIDITY" else "",
                "measurement_related_missing_slot"
                if _contains_any(missing_text, _MEASUREMENT_TERMS)
                else "",
                "measurement_scope" if _contains_any(scope_text, _MEASUREMENT_TERMS) else "",
            ]
            if measurement_signal and (has_evidence or has_missing)
            else []
        )
    generalization_signal = (
        question_kind == "GENERALIZATION_TRANSPORT"
        or _contains_any(missing_text, _GENERALIZATION_TERMS)
        or _contains_any(scope_text, _GENERALIZATION_TERMS)
    )
    return _unique(
        [
            "generalization_question"
            if question_kind == "GENERALIZATION_TRANSPORT"
            else "",
            "generalization_related_missing_slot"
            if _contains_any(missing_text, _GENERALIZATION_TERMS)
            else "",
            "generalization_scope" if _contains_any(scope_text, _GENERALIZATION_TERMS) else "",
            "scope_insufficient" if scope_insufficient else "",
        ]
        if generalization_signal and (has_evidence or has_missing)
        else []
    )


def build_evidence_refinement_plan(
    project_context: Mapping[str, Any] | None,
    subhypotheses: Sequence[Mapping[str, Any]] | None,
    coverage_ledger: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Compile bounded second-stage retrieval only for ledger-backed triggers."""

    project = _mapping(project_context)
    reports = _reports_by_subhypothesis(_mapping(coverage_ledger))
    decisions: list[dict[str, Any]] = []
    tasks: list[dict[str, Any]] = []
    for raw_subhypothesis in subhypotheses or []:
        subhypothesis = _mapping(raw_subhypothesis)
        identifier = str(subhypothesis.get("sub_hypothesis_id") or "")
        report = reports.get(identifier)
        if (
            not identifier
            or not report
            or subhypothesis.get("retrieval_strategy")
            != "slot_driven_required_slot_recovery"
        ):
            continue
        signals = _trigger_summary(report)
        for refinement_kind, specification in _REFINEMENT_SPECS.items():
            activation_reasons = _activation_reasons(
                subhypothesis,
                signals,
                refinement_kind,
            )
            (
                target_slot_names,
                missing_target_slot_names,
                target_slot_task_ids,
                resolution_slot_task_ids,
            ) = _refinement_slot_targets(
                subhypothesis,
                signals,
                refinement_kind,
            )
            task_id = f"{identifier}.refinement.{refinement_kind.casefold()}"
            decision = {
                "sub_hypothesis_id": identifier,
                "refinement_kind": refinement_kind,
                "task_id": task_id,
                "active": bool(activation_reasons),
                "activation_reasons": activation_reasons,
                "trigger_summary": signals,
                "target_slot_names": target_slot_names,
                "target_slot_recovery_task_ids": target_slot_task_ids,
                "resolution_slot_task_ids": resolution_slot_task_ids,
            }
            decisions.append(decision)
            if not activation_reasons:
                continue
            query_terms = _task_terms(
                subhypothesis,
                target_slot_names=missing_target_slot_names or target_slot_names,
                refinement_kind=refinement_kind,
            )
            query = " ".join(query_terms)[:1800]
            route_context = {
                **project,
                "exclusion_terms": _unique(
                    [
                        *_texts(project.get("exclusion_terms"), limit=10),
                        *_texts(subhypothesis.get("exclusion_terms"), limit=10),
                    ]
                ),
            }
            retrieval_plan = build_query_lanes(
                route_context,
                query=query,
                taxonomy_resolution=_mapping(project.get("taxonomy_resolution")),
                evidence_mode=specification["evidence_mode"],
                lane_prefix=task_id,
            )
            lanes = [
                {
                    **lane,
                    "sub_hypothesis_id": identifier,
                    "refinement_task_id": task_id,
                    "refinement_kind": refinement_kind,
                    "refinement_activation_reasons": activation_reasons,
                    "recovered_slot_task_ids": target_slot_task_ids,
                    "resolution_slot_task_ids": resolution_slot_task_ids,
                    "resolution_target": _RESOLUTION_TARGETS[refinement_kind],
                    "retrieval_stage": "evidence_refinement",
                }
                for lane in retrieval_plan.get("query_lanes", [])
                if isinstance(lane, Mapping)
            ]
            retrieval_plan["query_lanes"] = lanes
            tasks.append(
                {
                    "schema_version": EVIDENCE_REFINEMENT_SCHEMA_VERSION,
                    "task_id": task_id,
                    "sub_hypothesis_id": identifier,
                    "question_kind": str(subhypothesis.get("question_kind") or ""),
                    "refinement_kind": refinement_kind,
                    "activation_reasons": activation_reasons,
                    "trigger_summary": signals,
                    "target_slot_names": target_slot_names,
                    "target_slot_recovery_task_ids": target_slot_task_ids,
                    "resolution_slot_task_ids": resolution_slot_task_ids,
                    "resolution_target": _RESOLUTION_TARGETS[refinement_kind],
                    "scientific_scope": _mapping(subhypothesis.get("scientific_scope")),
                    "query": query,
                    "query_terms": query_terms,
                    "retrieval_plan": retrieval_plan,
                }
            )
    return {
        "schema_version": EVIDENCE_REFINEMENT_SCHEMA_VERSION,
        "execution_policy": "conditional_second_stage_retrieval",
        "decisions": decisions,
        "active_tasks": tasks,
    }


def refinement_execution_summary(
    papers: Sequence[Mapping[str, Any]] | None,
    refinement_plan: Mapping[str, Any] | None,
    ledger_before_refinement: Mapping[str, Any] | None,
    ledger_after_refinement: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Report what conditional tasks actually retrieved and recovered.

    Recovery means that a previously missing original slot becomes covered after
    a secondary task explicitly targeted it.  It is not a claim that the SH's
    substantive conclusion is true.
    """

    plan = _mapping(refinement_plan)
    before_reports = _reports_by_subhypothesis(_mapping(ledger_before_refinement))
    after_reports = _reports_by_subhypothesis(_mapping(ledger_after_refinement))
    reports: list[dict[str, Any]] = []
    resolution_reports: list[dict[str, Any]] = []
    for raw_task in plan.get("active_tasks", []):
        task = _mapping(raw_task)
        task_id = str(task.get("task_id") or "")
        subhypothesis_id = str(task.get("sub_hypothesis_id") or "")
        candidate_ids: list[str] = []
        for paper in papers or []:
            if not isinstance(paper, Mapping):
                continue
            provenance = paper.get("retrieval_provenance")
            if any(
                _mapping(record).get("refinement_task_id") == task_id
                for record in (provenance if isinstance(provenance, list) else [])
            ):
                candidate_ids.append(paper_identity(paper))
        before_slots = _mapping(_mapping(before_reports.get(subhypothesis_id)).get("slot_ledger"))
        after_slots = _mapping(_mapping(after_reports.get(subhypothesis_id)).get("slot_ledger"))
        recovered_slot_task_ids = [
            target_task_id
            for target_task_id in _texts(task.get("target_slot_recovery_task_ids"), limit=20)
            if any(
                str(_mapping(before_slot).get("task_id") or "") == target_task_id
                and _mapping(before_slot).get("missing")
                and not _mapping(after_slots.get(slot_name)).get("missing")
                and any(
                    str(_mapping(record).get("paper_id") or "") in candidate_ids
                    for record in _mapping(after_slots.get(slot_name)).get("covered_by", [])
                )
                for slot_name, before_slot in before_slots.items()
            )
        ]
        reports.append(
            {
                "task_id": task_id,
                "sub_hypothesis_id": subhypothesis_id,
                "refinement_kind": str(task.get("refinement_kind") or ""),
                "activation_reasons": _texts(task.get("activation_reasons"), limit=12),
                "candidate_paper_ids": _unique(candidate_ids),
                "recovered_slot_task_ids": _unique(recovered_slot_task_ids),
                "status": (
                    "RECOVERED_SLOT_COVERAGE"
                    if recovered_slot_task_ids
                    else "CANDIDATES_RETRIEVED_NO_SLOT_RECOVERY"
                    if candidate_ids
                    else "NO_CANDIDATES_RETRIEVED"
                ),
            }
        )
        resolution_reports.append(
            {
                "task_id": task_id,
                "sub_hypothesis_id": subhypothesis_id,
                "refinement_kind": str(task.get("refinement_kind") or ""),
                "resolution_target": str(task.get("resolution_target") or ""),
                "resolution_slot_task_ids": _texts(
                    task.get("resolution_slot_task_ids"),
                    limit=20,
                ),
                "candidate_paper_ids": _unique(candidate_ids),
                "resolution_status": (
                    "CANDIDATES_RETRIEVED_PENDING_EVALUATION"
                    if candidate_ids
                    else "NO_CANDIDATES_RETRIEVED"
                ),
            }
        )
    return {
        "schema_version": EVIDENCE_REFINEMENT_EXECUTION_SCHEMA_VERSION,
        "attempted": bool(plan.get("active_tasks")),
        "task_reports": reports,
        "refinement_resolution": resolution_reports,
    }
