"""Bounded multimodal-data routing for Gap and Idea workflows.

This module consumes only the path-free projection produced by the Survey
handoff loader.  It never reads a media sidecar, original record, preview, or
provider response.  Its purpose is to keep data-anchored observations useful
without promoting them to literature evidence or universal mechanism claims.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from copy import deepcopy
from math import floor
from typing import Any


DATA_ANCHORED_PRIORITY = "DATA_ANCHORED_PRIMARY"
DATA_ANCHORED_CLAIM_SCOPE = "dataset_local_hypothesis_pending_external_validation"
DEFAULT_DATA_SH_MCTS_DEPTH_MULTIPLIER = 1.75
DEFAULT_DATA_SH_MCTS_BUDGET_CAP = 0.50

DATA_ANCHORED_COVERAGE_BRANCHES = (
    {
        "branch_id": "candidate_mechanism",
        "label": "candidate mechanism",
        "instruction": "Test the tentative mechanism that is compatible with the supplied local observation.",
    },
    {
        "branch_id": "alternative_explanation",
        "label": "alternative explanation",
        "instruction": "Develop a competing mechanism that could generate the same observed pattern.",
    },
    {
        "branch_id": "measurement_artifact",
        "label": "measurement or preprocessing artifact",
        "instruction": "Treat calibration, preparation, proxy validity, or preprocessing as a competing explanation.",
    },
)

_RECONCILIATION_RANK = {
    "measurement_at_risk": 0,
    "challenged": 1,
    "mixed": 2,
    "supported_within_scope": 3,
    "unresolved": 4,
}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _texts(value: Any) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    pending = list(value) if isinstance(value, (list, tuple, set, frozenset)) else [value]
    while pending:
        value_item = pending.pop(0)
        if isinstance(value_item, (list, tuple, set, frozenset)):
            pending[0:0] = list(value_item)
            continue
        item = _text(value_item)
        if item and item not in seen:
            seen.add(item)
            result.append(item)
    return result


def _first_text(values: Iterable[Any]) -> str:
    for value in values:
        text = _text(value)
        if text:
            return text
    return ""


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _records(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, Mapping):
        return [dict(value)]
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [dict(item) for item in value if isinstance(item, Mapping)]
    return []


def _unique_records(values: Iterable[Mapping[str, Any]], key: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for value in values:
        item = dict(value)
        identifier = _text(item.get(key))
        fallback = repr(sorted(item.items()))
        unique_key = identifier or fallback
        if unique_key in seen:
            continue
        seen.add(unique_key)
        records.append(item)
    return records


def _data_rows(projection: Mapping[str, Any] | None) -> dict[str, dict[str, Any]]:
    payload = _mapping(projection)
    rows: dict[str, dict[str, Any]] = {}
    for row in _records(payload.get("data_anchored_subhypotheses")):
        subhypothesis_id = _text(row.get("sub_hypothesis_id"))
        if subhypothesis_id and row.get("analysis_priority") == DATA_ANCHORED_PRIORITY:
            rows[subhypothesis_id] = row
    return rows


def _reconciliation_status(claims: Sequence[Mapping[str, Any]]) -> str:
    statuses = [
        _text(_mapping(claim.get("literature_reconciliation")).get("status"))
        for claim in claims
    ]
    valid = [status for status in statuses if status in _RECONCILIATION_RANK]
    if not valid:
        return "unresolved"
    return min(valid, key=lambda status: _RECONCILIATION_RANK[status])


def build_data_anchored_seed_context(
    survey_idea_handoff: Mapping[str, Any] | None,
    gap: Mapping[str, Any],
    *,
    multimodal_evidence_projection: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Resolve one Gap's bounded observation context from handoff anchors."""

    handoff = _mapping(survey_idea_handoff)
    subhypothesis_id = _text(gap.get("subhypothesis_id"))
    data_row = _data_rows(multimodal_evidence_projection).get(subhypothesis_id)
    if not data_row:
        return {}

    requested_anchor_ids = set(_texts(gap.get("anchor_ids")))
    gap_id = _text(gap.get("gap_id"))
    anchors = [
        anchor
        for anchor in _records(handoff.get("anchors"))
        if _text(anchor.get("anchor_type")) == "multimodal_observation"
        and _text(anchor.get("subhypothesis_id")) == subhypothesis_id
        and (
            _text(anchor.get("anchor_id")) in requested_anchor_ids
            or gap_id in set(_texts(anchor.get("supports_gap_ids")))
        )
    ]
    anchors = _unique_records(anchors, "anchor_id")
    observation_ids = _texts(
        [anchor.get("source_id") for anchor in anchors]
        + [item.get("observation_id") for item in _records(data_row.get("observations"))]
    )
    if not anchors or not observation_ids:
        return {}

    observation_ids = [
        observation_id
        for observation_id in observation_ids
        if observation_id in set(_texts(data_row.get("observation_ids")))
    ]
    if not observation_ids:
        return {}
    claims = [
        claim
        for claim in _records(data_row.get("claims"))
        if _text(claim.get("observation_id")) in observation_ids
    ]
    observations = [
        observation
        for observation in _records(data_row.get("observations"))
        if _text(observation.get("observation_id")) in observation_ids
    ]
    if not claims or not observations:
        return {}

    alternatives = _texts(
        [
            *[claim.get("alternative_explanations") for claim in claims],
            *[observation.get("alternative_explanations") for observation in observations],
        ]
    )
    claim_limits = _texts(
        [
            *[claim.get("claim_limits") for claim in claims],
            *[observation.get("claim_limits") for observation in observations],
        ]
    )
    measurement_needs = _texts(
        [
            *[claim.get("discriminating_prediction") for claim in claims],
            *[claim.get("falsifier") for claim in claims],
        ]
    )
    candidate_explanations = _texts(
        [
            *[claim.get("candidate_explanation") for claim in claims],
            *[observation.get("candidate_explanation") for observation in observations],
        ]
    )
    paper_assessments = _unique_records(
        [
            assessment
            for claim in claims
            for assessment in _records(
                _mapping(claim.get("literature_reconciliation")).get(
                    "paper_assessments"
                )
            )
            if _text(assessment.get("paper_id"))
        ],
        "paper_id",
    )
    return {
        "analysis_priority": DATA_ANCHORED_PRIORITY,
        "subhypothesis_id": subhypothesis_id,
        "data_anchor_refs": observation_ids,
        "source_anchor_ids": _texts([anchor.get("anchor_id") for anchor in anchors]),
        "source_anchors": anchors,
        "literature_reconciliation_status": _reconciliation_status(claims),
        "candidate_explanations": candidate_explanations,
        "competing_explanations": alternatives,
        "measurement_needs": measurement_needs,
        "claim_limits": claim_limits,
        "paper_assessments": paper_assessments,
        "coverage_branches": [dict(branch) for branch in DATA_ANCHORED_COVERAGE_BRANCHES],
        "mcts_depth_multiplier": DEFAULT_DATA_SH_MCTS_DEPTH_MULTIPLIER,
    }


def annotate_data_anchored_mature_idea(
    idea: Mapping[str, Any],
    *,
    survey_idea_handoff: Mapping[str, Any] | None,
    multimodal_evidence_projection: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Attach data-SH metadata to a mature idea only through its target Gaps."""

    result = dict(idea)
    handoff = _mapping(survey_idea_handoff)
    gaps_by_id = {
        _text(gap.get("gap_id")): gap
        for gap in _records(handoff.get("gaps"))
        if _text(gap.get("gap_id"))
    }
    contexts = [
        build_data_anchored_seed_context(
            handoff,
            gaps_by_id[gap_id],
            multimodal_evidence_projection=multimodal_evidence_projection,
        )
        for gap_id in _texts(result.get("target_gap_ids"))
        if gap_id in gaps_by_id
    ]
    contexts = [context for context in contexts if context]
    if not contexts:
        return result

    data_anchor_refs = _texts(
        [context.get("data_anchor_refs") for context in contexts]
    )
    result.update(
        {
            "analysis_priority": DATA_ANCHORED_PRIORITY,
            "data_anchor_refs": data_anchor_refs,
            "literature_reconciliation_status": min(
                (_text(context.get("literature_reconciliation_status")) for context in contexts),
                key=lambda status: _RECONCILIATION_RANK.get(status, 99),
            ),
            "competing_explanations": _texts(
                [context.get("competing_explanations") for context in contexts]
            ),
            "measurement_needs": _texts(
                [context.get("measurement_needs") for context in contexts]
            ),
            "claim_limits": _texts(
                [context.get("claim_limits") for context in contexts]
            ),
            "paper_assessments": _unique_records(
                [
                    assessment
                    for context in contexts
                    for assessment in _records(context.get("paper_assessments"))
                ],
                "paper_id",
            ),
            "mcts_depth_multiplier": max(
                float(context.get("mcts_depth_multiplier") or 1.0)
                for context in contexts
            ),
            "data_anchored_contexts": contexts,
        }
    )
    return result


def is_data_anchored(value: Mapping[str, Any] | None) -> bool:
    return bool(
        isinstance(value, Mapping)
        and value.get("analysis_priority") == DATA_ANCHORED_PRIORITY
        and _texts(value.get("data_anchor_refs"))
    )


def build_data_anchored_coverage_schedule(
    seeds: Sequence[Mapping[str, Any]],
    *,
    ordinary_task_count: int,
    iterations_per_search: int,
    budget_cap: float = DEFAULT_DATA_SH_MCTS_BUDGET_CAP,
) -> dict[str, Any]:
    """Allocate a bounded first-pass MCTS budget for each unique data SH.

    Every data SH receives one coverage search whose root expansion is instructed
    to consider the three required branches.  The allocation is calculated from
    the ordinary searches that will actually execute: the data coverage budget
    can never exceed its configured share of the total executed expansions.

    The caller must schedule at least one ordinary search when data coverage is
    enabled.  With no ordinary expansion budget, this function intentionally
    assigns zero data expansions rather than inventing virtual non-data work.
    """

    unique: list[dict[str, Any]] = []
    seen_subhypotheses: set[str] = set()
    for raw_seed in seeds:
        seed = dict(raw_seed) if isinstance(raw_seed, Mapping) else {}
        if not is_data_anchored(seed):
            continue
        subhypothesis_id = _text(seed.get("subhypothesis_id"))
        if not subhypothesis_id or subhypothesis_id in seen_subhypotheses:
            continue
        seen_subhypotheses.add(subhypothesis_id)
        unique.append(seed)

    base_iterations = max(0, int(iterations_per_search or 0))
    normal_tasks = max(0, int(ordinary_task_count or 0))
    capped_share = min(
        max(float(budget_cap), 0.0),
        DEFAULT_DATA_SH_MCTS_BUDGET_CAP,
    )
    ordinary_expansion_budget = base_iterations * normal_tasks
    if capped_share <= 0.0:
        data_cap = 0
    else:
        data_cap = floor(
            ordinary_expansion_budget * capped_share / (1.0 - capped_share)
        )
    allocatable = min(data_cap, base_iterations * len(unique))
    quotient, remainder = divmod(allocatable, len(unique)) if unique else (0, 0)
    assignments = []
    deferred_subhypothesis_ids: list[str] = []
    for index, seed in enumerate(unique):
        iteration_budget = quotient + (1 if index < remainder else 0)
        if iteration_budget <= 0:
            deferred_subhypothesis_ids.append(_text(seed.get("subhypothesis_id")))
            continue
        assignment = {
            "seed_id": _text(seed.get("seed_id")),
            "gap_id": _text(seed.get("gap_id")),
            "subhypothesis_id": _text(seed.get("subhypothesis_id")),
            "data_anchor_refs": _texts(seed.get("data_anchor_refs")),
            "coverage_branches": [dict(branch) for branch in DATA_ANCHORED_COVERAGE_BRANCHES],
            "mcts_depth_multiplier": float(
                seed.get("mcts_depth_multiplier") or DEFAULT_DATA_SH_MCTS_DEPTH_MULTIPLIER
            ),
            "iteration_budget": iteration_budget,
        }
        assignments.append(assignment)
    return {
        "schema_version": "data_anchored_mcts_schedule_v1",
        "enabled": bool(assignments),
        "coverage_pass_order": "before_ordinary_mcts",
        "branching_requirement": "candidate_mechanism, alternative_explanation, measurement_artifact",
        "ordinary_task_count": normal_tasks,
        "ordinary_expansion_budget": ordinary_expansion_budget,
        "data_expansion_budget_cap": data_cap,
        "allocated_data_expansion_budget": sum(
            int(item["iteration_budget"]) for item in assignments
        ),
        "planned_total_expansion_budget": ordinary_expansion_budget + sum(
            int(item["iteration_budget"]) for item in assignments
        ),
        "data_expansion_budget_share_cap": capped_share,
        "deferred_subhypothesis_ids": deferred_subhypothesis_ids,
        "assignments": assignments,
    }


def scoped_multimodal_evidence_for_idea(
    idea: Mapping[str, Any],
    *,
    survey_idea_handoff: Mapping[str, Any] | None,
    multimodal_evidence_projection: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return only data anchors and roles relevant to an explicitly targeted idea."""

    annotated = annotate_data_anchored_mature_idea(
        idea,
        survey_idea_handoff=survey_idea_handoff,
        multimodal_evidence_projection=multimodal_evidence_projection,
    )
    if not is_data_anchored(annotated):
        return {}
    handoff = _mapping(survey_idea_handoff)
    target_gap_ids = set(_texts(annotated.get("target_gap_ids")))
    target_subhypotheses = {
        _text(gap.get("subhypothesis_id"))
        for gap in _records(handoff.get("gaps"))
        if _text(gap.get("gap_id")) in target_gap_ids
    }
    source_anchor_ids = set(
        _texts(
            [
                context.get("source_anchor_ids")
                for context in annotated.get("data_anchored_contexts", [])
                if isinstance(context, Mapping)
            ]
        )
    )
    anchors = [
        anchor
        for anchor in _records(handoff.get("anchors"))
        if _text(anchor.get("anchor_id")) in source_anchor_ids
        or (
            _text(anchor.get("anchor_type")) == "multimodal_observation"
            and _text(anchor.get("subhypothesis_id")) in target_subhypotheses
        )
    ]
    anchors = _unique_records(anchors, "anchor_id")
    anchor_ids = {_text(anchor.get("anchor_id")) for anchor in anchors}
    roles = [
        role
        for role in _records(handoff.get("evidence_roles"))
        if _text(role.get("subhypothesis_id")) in target_subhypotheses
        or bool(anchor_ids & set(_texts(role.get("anchor_ids"))))
    ]
    return {
        "analysis_priority": DATA_ANCHORED_PRIORITY,
        "data_anchor_refs": _texts(annotated.get("data_anchor_refs")),
        "literature_reconciliation_status": _text(
            annotated.get("literature_reconciliation_status")
        )
        or "unresolved",
        "competing_explanations": _texts(annotated.get("competing_explanations")),
        "measurement_needs": _texts(annotated.get("measurement_needs")),
        "claim_limits": _texts(annotated.get("claim_limits")),
        "paper_assessments": _unique_records(
            [
                assessment
                for context in annotated.get("data_anchored_contexts", [])
                if isinstance(context, Mapping)
                for assessment in _records(context.get("paper_assessments"))
            ],
            "paper_id",
        ),
        "source_anchors": anchors,
        "evidence_roles": _unique_records(roles, "evidence_role_id"),
    }


def apply_data_anchored_idea_constraints(
    candidate: Mapping[str, Any],
    *,
    seed: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Attach required bounded-data fields and mark incomplete candidates ineligible."""

    result = deepcopy(dict(candidate))
    source = _mapping(seed)
    if not is_data_anchored(source):
        source = _mapping(result.get("data_anchored_context"))
    if not is_data_anchored(source):
        return result

    scientific_intervention = _mapping(result.get("scientific_intervention"))
    hypothesis_contract = _mapping(scientific_intervention.get("hypothesis_contract"))
    target_gap_ids = _texts(result.get("target_gap_ids")) or _texts(
        hypothesis_contract.get("target_gap_ids")
    ) or _texts(source.get("gap_id"))
    candidate_mechanism = _text(
        result.get("candidate_mechanism")
        or result.get("expected_mechanism")
        or result.get("mechanism_or_relation")
        or hypothesis_contract.get("expected_mechanism")
        or hypothesis_contract.get("mechanism_or_relation")
    )
    discriminating_measurement_plan = _first_text(
        (
            result.get("discriminating_measurement_plan"),
            result.get("discriminating_observation"),
            result.get("evidence_requirement"),
            hypothesis_contract.get("discriminating_observation"),
            hypothesis_contract.get("evidence_requirement"),
            *_texts(source.get("measurement_needs")),
        )
    )
    falsifier = _first_text(
        (
            result.get("falsifier"),
            result.get("discriminating_observation"),
            hypothesis_contract.get("discriminating_observation"),
            *_texts(source.get("measurement_needs")),
        )
    )
    competing_explanations = _texts(
        result.get("competing_explanations") or source.get("competing_explanations")
    )
    confound_checks = _texts(
        result.get("confound_and_leakage_checks")
        or [
            *source.get("claim_limits", []),
            *source.get("measurement_needs", []),
        ]
    )
    result.update(
        {
            "analysis_priority": DATA_ANCHORED_PRIORITY,
            "target_gap_ids": target_gap_ids,
            "data_anchor_refs": _texts(source.get("data_anchor_refs")),
            "literature_reconciliation_status": _text(
                source.get("literature_reconciliation_status")
            )
            or "unresolved",
            "candidate_mechanism": candidate_mechanism,
            "competing_explanations": competing_explanations,
            "discriminating_measurement_plan": discriminating_measurement_plan,
            "falsifier": falsifier,
            "confound_and_leakage_checks": confound_checks,
            "claim_scope": DATA_ANCHORED_CLAIM_SCOPE,
        }
    )
    required = {
        "target_gap_ids": target_gap_ids,
        "data_anchor_refs": result["data_anchor_refs"],
        "candidate_mechanism": candidate_mechanism,
        "competing_explanations": competing_explanations,
        "discriminating_measurement_plan": discriminating_measurement_plan,
        "falsifier": falsifier,
        "confound_and_leakage_checks": confound_checks,
    }
    missing = [field_name for field_name, value in required.items() if not value]
    result["data_anchored_contract_status"] = "complete" if not missing else "incomplete"
    if missing:
        result["invariant_status"] = "violated"
        result["invariant_violations"] = _texts(
            [*result.get("invariant_violations", []), *[f"missing_data_anchored_{field_name}" for field_name in missing]]
        )
    data_contract = {
        "data_anchor_refs": list(result["data_anchor_refs"]),
        "literature_reconciliation_status": result["literature_reconciliation_status"],
        "competing_explanations": list(competing_explanations),
        "measurement_needs": _texts(source.get("measurement_needs")),
        "claim_limits": _texts(source.get("claim_limits")),
        "mcts_depth_multiplier": float(
            source.get("mcts_depth_multiplier") or DEFAULT_DATA_SH_MCTS_DEPTH_MULTIPLIER
        ),
    }
    scientific_intervention["data_anchored_contract"] = data_contract
    result["scientific_intervention"] = scientific_intervention
    return result


__all__ = [
    "DATA_ANCHORED_PRIORITY",
    "DATA_ANCHORED_CLAIM_SCOPE",
    "DATA_ANCHORED_COVERAGE_BRANCHES",
    "DEFAULT_DATA_SH_MCTS_DEPTH_MULTIPLIER",
    "DEFAULT_DATA_SH_MCTS_BUDGET_CAP",
    "annotate_data_anchored_mature_idea",
    "apply_data_anchored_idea_constraints",
    "build_data_anchored_coverage_schedule",
    "build_data_anchored_seed_context",
    "is_data_anchored",
    "scoped_multimodal_evidence_for_idea",
]
