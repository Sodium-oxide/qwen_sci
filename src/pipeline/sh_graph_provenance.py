"""Auditable SH provenance for seed papers and citation-graph expansion.

The annotations in this module deliberately distinguish *where a paper came
from* from *what it evidences*.  Citation expansion may propagate a root-seed
lineage and its retrieval purpose, but it never propagates covered slots,
evidence roles, or direct-claim admissibility from the seed to a cited/citing
work.  In particular, an exploration root remains an exploration root: it is
not silently promoted to direct evidence merely because it entered the graph.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

from src.pipeline.evidence_coverage_ledger import paper_identity


SH_GRAPH_PROVENANCE_SCHEMA_VERSION = "sh_graph_provenance_v1"
SH_NODE_ANNOTATION_SCHEMA_VERSION = "sh_node_annotation_v1"

LEDGER_CONFIRMED_EVIDENCE = "LEDGER_CONFIRMED_EVIDENCE"
BACKGROUND_CONTEXT = "BACKGROUND_CONTEXT"
SEED_CANDIDATE = "SEED_CANDIDATE"
GRAPH_EXPANDED_CANDIDATE = "GRAPH_EXPANDED_CANDIDATE"
FULLTEXT_PROMOTED_EXPANDED = "FULLTEXT_PROMOTED_EXPANDED"

DIRECT_LEDGER_EVIDENCE = "DIRECT_LEDGER_EVIDENCE"
QUALIFIED_SH_CONTRIBUTION = "QUALIFIED_SH_CONTRIBUTION"
SEED_CANDIDATE_ONLY = "SEED_CANDIDATE_ONLY"
GRAPH_EXPANDED_CANDIDATE_ONLY = "GRAPH_EXPANDED_CANDIDATE_ONLY"
FULLTEXT_PROMOTION_STAGE = "FULLTEXT_PROMOTION"


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _texts(value: Any) -> list[str]:
    values = value if isinstance(value, (list, tuple, set)) else [value]
    result: list[str] = []
    seen: set[str] = set()
    for raw in values:
        text = re.sub(r"\s+", " ", str(raw or "")).strip()
        key = text.casefold()
        if not text or key in seen:
            continue
        seen.add(key)
        result.append(text)
    return result


def _unique_records(records: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    for raw_record in records:
        record = _mapping(raw_record)
        if record.get("schema_version") != SH_NODE_ANNOTATION_SCHEMA_VERSION:
            continue
        key = (
            str(record.get("project_id") or ""),
            str(record.get("project_context_fingerprint") or ""),
            str(record.get("sub_hypothesis_id") or ""),
            str(record.get("association_stage") or ""),
            str(record.get("association_status") or ""),
            tuple(sorted(_texts(record.get("root_seed_paper_ids")))),
            tuple(sorted(_texts(record.get("parent_paper_ids")))),
            int(record.get("lineage_depth") or 0),
            str(record.get("citation_direction") or ""),
            tuple(sorted(_texts(record.get("covered_slots")))),
            tuple(sorted(_texts(record.get("slot_recovery_task_ids")))),
            str(record.get("evidence_use_mode") or ""),
            str(record.get("admission_status") or ""),
            str(record.get("semantic_overall_relation") or ""),
            str(record.get("graph_expansion_mode") or ""),
            str(record.get("graph_lineage_source") or ""),
            str(record.get("local_graph_node_id") or ""),
            str(record.get("local_graph_parent_node_id") or ""),
        )
        if key in seen:
            continue
        seen.add(key)
        normalized = dict(record)
        for list_key in (
            "root_seed_paper_ids",
            "parent_paper_ids",
            "covered_slots",
            "slot_recovery_task_ids",
            "expected_evidence_roles",
            "root_evidence_roles",
            "selected_for_slots",
            "semantic_contribution_types",
            "semantic_claim_limits",
        ):
            normalized[list_key] = _texts(normalized.get(list_key))
        semantic_slots: list[dict[str, str]] = []
        for raw_slot in normalized.get("semantic_slot_contributions") or []:
            slot = _mapping(raw_slot)
            slot_name = str(slot.get("slot_name") or "").strip()
            support_level = str(slot.get("support_level") or "").strip().casefold()
            if not slot_name or support_level not in {"direct", "partial", "indirect"}:
                continue
            semantic_slots.append(
                {
                    "slot_name": slot_name,
                    "support_level": support_level,
                    "reason": str(slot.get("reason") or "").strip(),
                }
            )
        normalized["semantic_slot_contributions"] = semantic_slots
        output.append(normalized)
    return output


def merge_node_annotations(
    existing: Sequence[Mapping[str, Any]] | None,
    incoming: Sequence[Mapping[str, Any]] | None,
) -> list[dict[str, Any]]:
    """Merge v1 annotations without interpreting or upgrading legacy records."""

    return _unique_records([*(existing or []), *(incoming or [])])


def current_project_node_annotations(
    records: Sequence[Mapping[str, Any]] | None,
    *,
    project_id: str,
    project_context_fingerprint: str,
) -> list[dict[str, Any]]:
    """Keep only annotations owned by one concrete project execution.

    A research-context fingerprint describes the input contract, not one run's
    evidence decisions. It is therefore insufficient for reusing a graph
    overlay: two project executions may share a fingerprint while having
    different seed selections or ledger outcomes.
    """

    expected_project_id = str(project_id or "").strip()
    expected_fingerprint = str(project_context_fingerprint or "").strip()
    if not expected_project_id or not expected_fingerprint:
        return []
    return merge_node_annotations(
        [],
        [
            record
            for record in records or []
            if _mapping(record).get("project_id") == expected_project_id
            and _mapping(record).get("project_context_fingerprint")
            == expected_fingerprint
        ],
    )


def ledger_coverage_by_paper(
    coverage_ledger: Mapping[str, Any] | None,
) -> dict[str, dict[str, dict[str, Any]]]:
    """Index only ledger-confirmed slot coverage by paper and SH."""

    output: dict[str, dict[str, dict[str, Any]]] = {}
    ledger = _mapping(coverage_ledger)
    for raw_report in ledger.get("subhypotheses", []):
        report = _mapping(raw_report)
        subhypothesis_id = str(report.get("sub_hypothesis_id") or "").strip()
        if not subhypothesis_id:
            continue
        for raw_slot in _mapping(report.get("slot_ledger")).values():
            slot = _mapping(raw_slot)
            slot_name = str(slot.get("slot_name") or "").strip()
            task_id = str(slot.get("task_id") or "").strip()
            expected_role = str(slot.get("expected_evidence_role") or "").strip()
            for raw_paper in slot.get("covered_by", []):
                paper = _mapping(raw_paper)
                paper_id = str(paper.get("paper_id") or "").strip()
                if not paper_id:
                    continue
                item = output.setdefault(paper_id, {}).setdefault(
                    subhypothesis_id,
                    {
                        "covered_slots": [],
                        "slot_recovery_task_ids": [],
                        "expected_evidence_roles": [],
                    },
                )
                item["covered_slots"] = _texts([*item["covered_slots"], slot_name])
                item["slot_recovery_task_ids"] = _texts(
                    [*item["slot_recovery_task_ids"], task_id]
                )
                item["expected_evidence_roles"] = _texts(
                    [*item["expected_evidence_roles"], expected_role]
                )
    return output


def _sh_match_for_paper(
    paper: Mapping[str, Any],
    subhypothesis_id: str,
) -> dict[str, Any]:
    for raw_match in paper.get("sh_matches", []):
        match = _mapping(raw_match)
        if match.get("sub_hypothesis_id") == subhypothesis_id:
            return match
    return {}


def _semantic_assessment_for_paper(
    paper: Mapping[str, Any],
    subhypothesis_id: str,
    sh_match: Mapping[str, Any],
) -> dict[str, Any]:
    """Read the semantic assessment from either current A--D representation."""

    assessment = _mapping(sh_match.get("semantic_assessment"))
    if assessment:
        return assessment
    for raw_assessment in paper.get("sh_semantic_assessments", []):
        candidate = _mapping(raw_assessment)
        if candidate.get("sub_hypothesis_id") == subhypothesis_id:
            return candidate
    return {}


def _semantic_slot_contributions(
    assessment: Mapping[str, Any],
) -> list[dict[str, str]]:
    """Keep only explicit, slot-addressable LLM contributions for writing."""

    output: list[dict[str, str]] = []
    for raw_contribution in assessment.get("candidate_slot_contributions", []):
        contribution = _mapping(raw_contribution)
        slot_name = str(contribution.get("slot_name") or "").strip()
        support_level = str(contribution.get("support_level") or "").strip().casefold()
        if not slot_name or support_level not in {"direct", "partial", "indirect"}:
            continue
        output.append(
            {
                "slot_name": slot_name,
                "support_level": support_level,
                "reason": str(contribution.get("reason") or "").strip(),
            }
        )
    return output


def _root_evidence_use_mode(
    *,
    association_status: str,
    admission_status: str,
    semantic_assessment: Mapping[str, Any],
) -> str:
    """Classify what writing may do with a selected root, never infer directness."""

    if association_status == LEDGER_CONFIRMED_EVIDENCE:
        return DIRECT_LEDGER_EVIDENCE
    if association_status == BACKGROUND_CONTEXT:
        return BACKGROUND_CONTEXT
    relation = str(semantic_assessment.get("overall_relation") or "").casefold()
    if admission_status == "PARTIAL_OR_INDIRECT_ONLY" or relation in {
        "partial",
        "indirect",
        "boundary",
        "counterevidence",
        "method",
        "hypothesis_generating",
    }:
        return QUALIFIED_SH_CONTRIBUTION
    return SEED_CANDIDATE_ONLY


def _root_admission_summary(
    sh_match: Mapping[str, Any],
    semantic_assessment: Mapping[str, Any],
    association_status: str,
) -> tuple[str, str]:
    """Summarize ledger admission without making a seed-selection shortcut a claim."""

    statuses = {
        str(_mapping(item).get("admission_status") or "")
        for item in sh_match.get("slot_assessments", [])
    }
    graph_statuses = {
        str(_mapping(item).get("graph_value_status") or "")
        for item in sh_match.get("slot_assessments", [])
    }
    if association_status == LEDGER_CONFIRMED_EVIDENCE:
        return "DIRECT_EVIDENCE", "EXPAND"
    if association_status == BACKGROUND_CONTEXT:
        return "BACKGROUND_CONTEXT_ONLY", "CONTEXT"
    if "BLOCKED_BY_EXCLUSION" in statuses:
        return "BLOCKED_BY_EXCLUSION", "REJECTED"
    if "PARTIAL_OR_INDIRECT_ONLY" in statuses:
        return "PARTIAL_OR_INDIRECT_ONLY", "EXPAND" if "EXPAND" in graph_statuses else "HOLDOUT"
    relation = str(semantic_assessment.get("overall_relation") or "").casefold()
    if relation in {
        "partial",
        "indirect",
        "boundary",
        "counterevidence",
        "method",
        "hypothesis_generating",
    }:
        return "PARTIAL_OR_INDIRECT_ONLY", "EXPAND"
    if relation == "background":
        return "BACKGROUND_CONTEXT_ONLY", "CONTEXT"
    return "NOT_EVALUATED_AS_DIRECT_EVIDENCE", "UNASSESSED"


def build_seed_annotation_index(
    selected_papers: Sequence[Mapping[str, Any]] | None,
    coverage_ledger: Mapping[str, Any] | None,
    *,
    project_id: str,
    project_context_fingerprint: str,
) -> dict[str, list[dict[str, Any]]]:
    """Build direct, ledger-backed annotations for the selected SH seed set.

    The output is keyed by the candidate's stable retrieval identity.  Callers
    may remap that identity to the graph's provider-canonical work ID before
    attaching the records to a graph node.
    """

    coverage_index = ledger_coverage_by_paper(coverage_ledger)
    output: dict[str, list[dict[str, Any]]] = {}
    for raw_paper in selected_papers or []:
        if not isinstance(raw_paper, Mapping):
            continue
        paper = dict(raw_paper)
        selection = _mapping(paper.get("seed_selection"))
        if not selection.get("selected"):
            continue
        paper_id = paper_identity(paper)
        by_sh = coverage_index.get(paper_id, {})
        selected_slots_by_sh: dict[str, list[str]] = {}
        for raw_selected_slot in selection.get("selected_slots", []):
            selected_slot = _mapping(raw_selected_slot)
            subhypothesis_id = str(selected_slot.get("sub_hypothesis_id") or "").strip()
            slot_name = str(selected_slot.get("slot") or "").strip()
            if subhypothesis_id:
                selected_slots_by_sh[subhypothesis_id] = _texts(
                    [*selected_slots_by_sh.get(subhypothesis_id, []), slot_name]
                )

        semantic_assessment_ids = _texts(selection.get("semantic_assessment_ids"))
        subhypothesis_ids = _texts(
            [*by_sh.keys(), *selected_slots_by_sh.keys(), *semantic_assessment_ids]
        )
        for subhypothesis_id in subhypothesis_ids:
            coverage = _mapping(by_sh.get(subhypothesis_id))
            roles = _texts(coverage.get("expected_evidence_roles"))
            covered_slots = _texts(coverage.get("covered_slots"))
            sh_match = _sh_match_for_paper(paper, subhypothesis_id)
            semantic_assessment = _semantic_assessment_for_paper(
                paper,
                subhypothesis_id,
                sh_match,
            )
            seed_kind = str(selection.get("seed_kind") or "").strip()
            is_background = bool(roles) and set(roles) <= {BACKGROUND_CONTEXT}
            if covered_slots:
                status = BACKGROUND_CONTEXT if is_background else LEDGER_CONFIRMED_EVIDENCE
                scope_status = "VERIFIED_BY_LEDGER"
            else:
                status = SEED_CANDIDATE
                scope_status = "NOT_EVALUATED_AS_DIRECT_EVIDENCE"
            admission_status, graph_value_status = _root_admission_summary(
                sh_match,
                semantic_assessment,
                status,
            )
            evidence_use_mode = _root_evidence_use_mode(
                association_status=status,
                admission_status=admission_status,
                semantic_assessment=semantic_assessment,
            )
            annotation = {
                "schema_version": SH_NODE_ANNOTATION_SCHEMA_VERSION,
                "project_id": str(project_id or ""),
                "project_context_fingerprint": str(project_context_fingerprint or ""),
                "sub_hypothesis_id": subhypothesis_id,
                "association_stage": "SEED_SELECTION",
                "association_status": status,
                "evidence_assessment_source": "evidence_coverage_ledger_v1",
                "root_seed_paper_ids": [paper_id],
                "parent_paper_ids": [],
                "lineage_depth": 0,
                "citation_direction": "",
                "covered_slots": covered_slots,
                "slot_recovery_task_ids": _texts(coverage.get("slot_recovery_task_ids")),
                "expected_evidence_roles": roles,
                "root_evidence_roles": [],
                "selected_for_slots": selected_slots_by_sh.get(subhypothesis_id, []),
                "seed_kind": seed_kind,
                "graph_expansion_mode": str(
                    selection.get("graph_expansion_mode") or ""
                ).strip(),
                "seed_selection_basis": str(selection.get("selection_basis") or "").strip(),
                "evidence_use_mode": evidence_use_mode,
                "admission_status": admission_status,
                "graph_value_status": graph_value_status,
                "semantic_relevance_score": semantic_assessment.get(
                    "semantic_relevance_score"
                ),
                "semantic_overall_relation": str(
                    semantic_assessment.get("overall_relation") or ""
                ).strip(),
                "semantic_contribution_types": _texts(
                    semantic_assessment.get("contribution_types")
                ),
                "semantic_slot_contributions": _semantic_slot_contributions(
                    semantic_assessment
                ),
                "semantic_claim_limits": _texts(
                    semantic_assessment.get("claim_limits")
                ),
                "scope_status": scope_status,
            }
            output[paper_id] = merge_node_annotations(output.get(paper_id), [annotation])
    return output


def build_graph_expansion_annotations(
    root_annotations: Sequence[Mapping[str, Any]] | None,
    *,
    parent_paper_id: str,
    root_seed_paper_id: str,
    lineage_depth: int,
    citation_direction: str,
) -> list[dict[str, Any]]:
    """Create candidate-only annotations for one citation-graph expansion step.

    ``covered_slots`` and ``expected_evidence_roles`` are intentionally empty.
    A cited or citing paper has lineage to a seed but has not been assessed as
    evidence for that seed's SH.  The root's role is retained only as a
    ``root_*`` retrieval-context field, never as this node's evidence role.
    """

    output: list[dict[str, Any]] = []
    for raw_annotation in root_annotations or []:
        root = _mapping(raw_annotation)
        if root.get("schema_version") != SH_NODE_ANNOTATION_SCHEMA_VERSION:
            continue
        subhypothesis_id = str(root.get("sub_hypothesis_id") or "").strip()
        if not subhypothesis_id:
            continue
        output.append(
            {
                "schema_version": SH_NODE_ANNOTATION_SCHEMA_VERSION,
                "project_id": str(root.get("project_id") or ""),
                "project_context_fingerprint": str(
                    root.get("project_context_fingerprint") or ""
                ),
                "sub_hypothesis_id": subhypothesis_id,
                "association_stage": "GRAPH_EXPANSION",
                "association_status": GRAPH_EXPANDED_CANDIDATE,
                "evidence_assessment_source": "citation_graph_lineage_only",
                "root_seed_paper_ids": [str(root_seed_paper_id or "")],
                "parent_paper_ids": [str(parent_paper_id or "")],
                "lineage_depth": max(1, int(lineage_depth or 1)),
                "citation_direction": str(citation_direction or ""),
                "covered_slots": [],
                "slot_recovery_task_ids": [],
                "expected_evidence_roles": [],
                "root_evidence_roles": _texts(root.get("expected_evidence_roles")),
                "selected_for_slots": [],
                "seed_kind": "",
                "graph_expansion_mode": "",
                "seed_selection_basis": "",
                "evidence_use_mode": GRAPH_EXPANDED_CANDIDATE_ONLY,
                "admission_status": "NOT_EVALUATED_AS_DIRECT_EVIDENCE",
                "graph_value_status": "RETRIEVAL_CANDIDATE",
                "semantic_relevance_score": None,
                "semantic_overall_relation": "",
                "semantic_contribution_types": [],
                "semantic_slot_contributions": [],
                "semantic_claim_limits": [],
                "root_seed_kind": str(root.get("seed_kind") or ""),
                "root_graph_expansion_mode": str(
                    root.get("graph_expansion_mode") or ""
                ),
                "root_evidence_use_mode": str(root.get("evidence_use_mode") or ""),
                "root_admission_status": str(root.get("admission_status") or ""),
                "root_graph_value_status": str(root.get("graph_value_status") or ""),
                "root_semantic_overall_relation": str(
                    root.get("semantic_overall_relation") or ""
                ),
                "root_semantic_contribution_types": _texts(
                    root.get("semantic_contribution_types")
                ),
                "root_semantic_claim_limits": _texts(root.get("semantic_claim_limits")),
                "scope_status": "NOT_EVALUATED_AS_DIRECT_EVIDENCE",
            }
        )
    return merge_node_annotations([], output)


def build_fulltext_promotion_annotations(
    candidate_annotations: Sequence[Mapping[str, Any]] | None,
    semantic_assessment: Mapping[str, Any] | None,
    *,
    fulltext_reading_source: str,
    promotion_relatedness_score: float = 0.0,
) -> list[dict[str, Any]]:
    """Promote a read citation-graph candidate only from its own SH assessment.

    Citation lineage remains in the original ``GRAPH_EXPANDED_CANDIDATE``
    records.  This produces a separate, auditable annotation only when the
    candidate's complete-section keynote identifies an explicit SH slot and a
    support level.  It therefore cannot inherit evidence status from its root.
    """

    assessment = _mapping(semantic_assessment)
    subhypothesis_id = str(assessment.get("sub_hypothesis_id") or "").strip()
    if not subhypothesis_id:
        return []
    if assessment.get("explicit_exclusion_matches"):
        return []

    supporting_slots = _semantic_slot_contributions(assessment)
    if not supporting_slots:
        return []
    relation = str(assessment.get("overall_relation") or "").strip().casefold()
    direct_slots = [
        item["slot_name"]
        for item in supporting_slots
        if item.get("support_level") == "direct"
    ]
    has_grounded_fulltext_evidence = bool(assessment.get("evidence_spans"))
    if direct_slots and has_grounded_fulltext_evidence:
        evidence_use_mode = DIRECT_LEDGER_EVIDENCE
        admission_status = "DIRECT_EVIDENCE"
        association_status = FULLTEXT_PROMOTED_EXPANDED
        covered_slots = direct_slots
    elif relation == "background":
        evidence_use_mode = BACKGROUND_CONTEXT
        admission_status = "BACKGROUND_CONTEXT_ONLY"
        association_status = FULLTEXT_PROMOTED_EXPANDED
        covered_slots = []
    elif relation in {
        "direct",
        "partial",
        "indirect",
        "boundary",
        "counterevidence",
        "method",
        "hypothesis_generating",
    }:
        evidence_use_mode = QUALIFIED_SH_CONTRIBUTION
        admission_status = "PARTIAL_OR_INDIRECT_ONLY"
        association_status = FULLTEXT_PROMOTED_EXPANDED
        covered_slots = []
    else:
        return []

    candidates = [
        _mapping(record)
        for record in candidate_annotations or []
        if _mapping(record).get("schema_version") == SH_NODE_ANNOTATION_SCHEMA_VERSION
        and _mapping(record).get("sub_hypothesis_id") == subhypothesis_id
        and _mapping(record).get("association_status") == GRAPH_EXPANDED_CANDIDATE
    ]
    if not candidates:
        return []

    roots = _texts(
        [
            root_id
            for candidate in candidates
            for root_id in candidate.get("root_seed_paper_ids") or []
        ]
    )
    parents = _texts(
        [
            parent_id
            for candidate in candidates
            for parent_id in candidate.get("parent_paper_ids") or []
        ]
    )
    directions = _texts([candidate.get("citation_direction") for candidate in candidates])
    sources = _texts([candidate.get("graph_lineage_source") for candidate in candidates])
    try:
        relatedness_score = float(promotion_relatedness_score or 0.0)
    except (TypeError, ValueError):
        relatedness_score = 0.0

    annotation = {
        "schema_version": SH_NODE_ANNOTATION_SCHEMA_VERSION,
        "project_id": str(candidates[0].get("project_id") or ""),
        "project_context_fingerprint": str(
            candidates[0].get("project_context_fingerprint") or ""
        ),
        "sub_hypothesis_id": subhypothesis_id,
        "association_stage": FULLTEXT_PROMOTION_STAGE,
        "association_status": association_status,
        "evidence_assessment_source": "complete_section_keynote_sh_assessment",
        "fulltext_reading_source": str(fulltext_reading_source or ""),
        "root_seed_paper_ids": roots,
        "parent_paper_ids": parents,
        "lineage_depth": min(
            max(1, int(candidate.get("lineage_depth") or 1))
            for candidate in candidates
        ),
        "citation_direction": "|".join(directions),
        "graph_lineage_source": "|".join(sources),
        "covered_slots": _texts(covered_slots),
        "slot_recovery_task_ids": [],
        "expected_evidence_roles": [],
        "root_evidence_roles": _texts(
            [
                role
                for candidate in candidates
                for role in candidate.get("root_evidence_roles") or []
            ]
        ),
        "selected_for_slots": [],
        "seed_kind": "",
        "graph_expansion_mode": "",
        "seed_selection_basis": "",
        "evidence_use_mode": evidence_use_mode,
        "admission_status": admission_status,
        "graph_value_status": "FULLTEXT_PROMOTED",
        "semantic_relevance_score": assessment.get("semantic_relevance_score"),
        "promotion_relatedness_score": relatedness_score,
        "semantic_overall_relation": relation,
        "semantic_contribution_types": _texts(assessment.get("contribution_types")),
        "semantic_slot_contributions": supporting_slots,
        "semantic_claim_limits": _texts(assessment.get("claim_limits")),
        "fulltext_evidence_spans": list(assessment.get("evidence_spans") or []),
        "scope_status": "ASSESSED_FROM_COMPLETE_SECTION_KEYNOTE",
    }
    return merge_node_annotations([], [annotation])


def append_annotation_index(
    index: Mapping[str, Sequence[Mapping[str, Any]]] | None,
    paper_id: str,
    annotations: Sequence[Mapping[str, Any]] | None,
) -> dict[str, list[dict[str, Any]]]:
    """Return an annotation index with one paper's v1 records merged in."""

    output = {
        str(key): merge_node_annotations([], value)
        for key, value in _mapping(index).items()
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes))
    }
    identifier = str(paper_id or "").strip()
    if identifier:
        output[identifier] = merge_node_annotations(output.get(identifier), annotations)
    return output
