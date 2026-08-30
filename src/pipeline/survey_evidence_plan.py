"""Compile SH evidence accounting into bounded, auditable survey-writing input.

The compiler is intentionally deterministic.  It does not decide whether a
scientific claim is true; it turns the final coverage ledger, project-scoped
graph provenance, and cluster projection into the only evidence boundary that
the Survey Generator may use for SH-specific writing.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from src.pipeline.evidence_coverage_ledger import (
    EVIDENCE_COVERAGE_LEDGER_SCHEMA_VERSION,
)
from src.pipeline.sh_cluster_projection import SH_CLUSTER_COVERAGE_SCHEMA_VERSION
from src.pipeline.sh_graph_provenance import (
    BACKGROUND_CONTEXT as PROVENANCE_BACKGROUND_CONTEXT,
    DIRECT_LEDGER_EVIDENCE,
    FULLTEXT_PROMOTION_STAGE,
    GRAPH_EXPANDED_CANDIDATE,
    GRAPH_EXPANDED_CANDIDATE_ONLY,
    LEDGER_CONFIRMED_EVIDENCE,
    QUALIFIED_SH_CONTRIBUTION,
    SH_GRAPH_PROVENANCE_SCHEMA_VERSION,
)
from src.pipeline.paper_identity import canonical_paper_id, canonical_paper_ids
from src.pipeline.multimodal_evidence.survey_integration import (
    LOCAL_DATA_OBSERVATION,
    build_multimodal_survey_projection,
)


SURVEY_EVIDENCE_PLAN_SCHEMA_VERSION = "survey_sh_evidence_plan_v1"

EVIDENCE_BACKED_SYNTHESIS = "EVIDENCE_BACKED_SYNTHESIS"
QUALIFIED_SYNTHESIS = "QUALIFIED_SYNTHESIS"
BACKGROUND_ONLY = "BACKGROUND_ONLY"
EVIDENCE_GAP_REPORT = "EVIDENCE_GAP_REPORT"
OUT_OF_SCOPE_OR_REJECTED = "OUT_OF_SCOPE_OR_REJECTED"


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _texts(value: Any) -> list[str]:
    values = value if isinstance(value, (list, tuple, set)) else [value]
    result: list[str] = []
    seen: set[str] = set()
    for raw in values:
        text = str(raw or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _records(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return [_mapping(item) for item in value if isinstance(item, Mapping)]


def _report_index(coverage_ledger: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    reports: dict[str, dict[str, Any]] = {}
    for raw_report in _records(coverage_ledger.get("subhypotheses")):
        identifier = str(raw_report.get("sub_hypothesis_id") or "").strip()
        if not identifier:
            raise ValueError("Evidence coverage ledger contains a report without sub_hypothesis_id.")
        if identifier in reports:
            raise ValueError(f"Evidence coverage ledger contains duplicate SH '{identifier}'.")
        reports[identifier] = raw_report
    if not reports:
        raise ValueError("Evidence coverage ledger contains no SH reports for survey writing.")
    return reports


def _contract_index(
    subhypothesis_contracts: Sequence[Mapping[str, Any]] | None,
) -> dict[str, dict[str, Any]]:
    contracts: dict[str, dict[str, Any]] = {}
    for raw_contract in subhypothesis_contracts or []:
        contract = _mapping(raw_contract)
        identifier = str(contract.get("sub_hypothesis_id") or "").strip()
        if identifier:
            if identifier in contracts:
                raise ValueError(
                    f"Survey evidence plan received duplicate SH contract '{identifier}'."
                )
            contracts[identifier] = contract
    if not contracts:
        raise ValueError("Survey evidence plan requires compiled SH contracts.")
    return contracts


def _validate_inputs(
    provenance_artifact: Mapping[str, Any] | None,
    coverage_ledger: Mapping[str, Any] | None,
    cluster_coverage_artifact: Mapping[str, Any] | None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    provenance = _mapping(provenance_artifact)
    ledger = _mapping(coverage_ledger)
    cluster_coverage = _mapping(cluster_coverage_artifact)
    if provenance.get("schema_version") != SH_GRAPH_PROVENANCE_SCHEMA_VERSION:
        raise ValueError("Survey evidence plan requires sh_graph_provenance_v1.")
    if ledger.get("schema_version") != EVIDENCE_COVERAGE_LEDGER_SCHEMA_VERSION:
        raise ValueError("Survey evidence plan requires evidence_coverage_ledger_v1.")
    if cluster_coverage.get("schema_version") != SH_CLUSTER_COVERAGE_SCHEMA_VERSION:
        raise ValueError("Survey evidence plan requires sh_cluster_coverage_projection_v1.")

    project_id = str(provenance.get("project_id") or "").strip()
    fingerprint = str(provenance.get("project_context_fingerprint") or "").strip()
    if not project_id or not fingerprint:
        raise ValueError("Survey evidence plan requires project-scoped SH provenance.")
    if (
        str(ledger.get("project_id") or "").strip() != project_id
        or str(ledger.get("project_context_fingerprint") or "").strip()
        != fingerprint
    ):
        raise ValueError("Evidence coverage ledger belongs to a different project.")
    if (
        str(cluster_coverage.get("project_id") or "").strip() != project_id
        or str(cluster_coverage.get("project_context_fingerprint") or "").strip()
        != fingerprint
    ):
        raise ValueError("SH cluster coverage artifact belongs to a different project.")
    return provenance, ledger, cluster_coverage


def _paper_ids(records: Sequence[Mapping[str, Any]]) -> list[str]:
    return canonical_paper_ids([_mapping(record).get("paper_id") for record in records])


def _annotation_evidence_use_mode(annotation: Mapping[str, Any]) -> str:
    """Read an explicit A--E role, with safe v1 defaults for old artifacts."""

    mode = str(annotation.get("evidence_use_mode") or "").strip()
    if mode:
        return mode
    status = str(annotation.get("association_status") or "").strip()
    if status == LEDGER_CONFIRMED_EVIDENCE:
        return DIRECT_LEDGER_EVIDENCE
    if status == PROVENANCE_BACKGROUND_CONTEXT:
        return "BACKGROUND_CONTEXT"
    if status == GRAPH_EXPANDED_CANDIDATE:
        return GRAPH_EXPANDED_CANDIDATE_ONLY
    return "SEED_CANDIDATE_ONLY"


def _provenance_role_index(
    provenance: Mapping[str, Any],
) -> dict[str, dict[str, list[dict[str, Any]]]]:
    """Index project-scoped provenance by SH then paper without interpreting it.

    The survey plan deliberately consumes a graph node's own role.  ``root_*``
    fields carried by graph-expanded nodes are lineage context only and never
    create a writing permission for the expanded paper.
    """

    output: dict[str, dict[str, list[dict[str, Any]]]] = {}
    project_id = str(provenance.get("project_id") or "").strip()
    fingerprint = str(provenance.get("project_context_fingerprint") or "").strip()
    acquisition_by_paper = {
        canonical_paper_id(paper_id): _mapping(acquisition)
        for paper_id, acquisition in _mapping(
            provenance.get("fulltext_acquisition_by_paper")
        ).items()
        if canonical_paper_id(paper_id)
    }
    for paper_id, raw_annotations in _mapping(provenance.get("paper_annotations")).items():
        if not isinstance(raw_annotations, Sequence) or isinstance(
            raw_annotations, (str, bytes)
        ):
            continue
        for raw_annotation in raw_annotations:
            annotation = _mapping(raw_annotation)
            if (
                annotation.get("project_id") != project_id
                or annotation.get("project_context_fingerprint") != fingerprint
            ):
                continue
            subhypothesis_id = str(annotation.get("sub_hypothesis_id") or "").strip()
            identifier = canonical_paper_id(paper_id)
            if not subhypothesis_id or not identifier:
                continue
            # Acquisition is a distinct operational state.  It can prohibit an
            # otherwise direct role from being used as direct *writing*
            # evidence, but it never edits the SH semantic assessment or graph
            # provenance annotation itself.
            annotated = dict(annotation)
            acquisition = _mapping(acquisition_by_paper.get(identifier))
            if acquisition:
                annotated["fulltext_acquisition"] = acquisition
            output.setdefault(subhypothesis_id, {}).setdefault(identifier, []).append(
                annotated
            )
    return output


def _role_constraint(annotation: Mapping[str, Any]) -> dict[str, Any]:
    """Expose a paper's permissible writing use without upgrading its role."""

    mode = _annotation_evidence_use_mode(annotation)
    allowed_support_kinds = {
        DIRECT_LEDGER_EVIDENCE: [DIRECT_LEDGER_EVIDENCE],
        "BACKGROUND_CONTEXT": ["BACKGROUND_CONTEXT"],
        QUALIFIED_SH_CONTRIBUTION: [QUALIFIED_SH_CONTRIBUTION],
    }.get(mode, [])
    acquisition = _mapping(annotation.get("fulltext_acquisition"))
    fulltext_unavailable = bool(acquisition) and not bool(
        acquisition.get("fulltext_available")
    )
    if fulltext_unavailable:
        # Do not rewrite `evidence_use_mode`: that is scientific/graph
        # provenance.  Only remove direct-writing permission until an
        # independently verifiable full-text route is available.
        allowed_support_kinds = [
            support_kind
            for support_kind in allowed_support_kinds
            if support_kind != DIRECT_LEDGER_EVIDENCE
        ]
    return {
        "association_status": str(annotation.get("association_status") or ""),
        "association_stage": str(annotation.get("association_stage") or ""),
        "evidence_use_mode": mode,
        "admission_status": str(annotation.get("admission_status") or ""),
        "graph_value_status": str(annotation.get("graph_value_status") or ""),
        "seed_kind": str(annotation.get("seed_kind") or ""),
        "graph_expansion_mode": str(annotation.get("graph_expansion_mode") or ""),
        "semantic_overall_relation": str(
            annotation.get("semantic_overall_relation") or ""
        ),
        "semantic_contribution_types": _texts(
            annotation.get("semantic_contribution_types")
        ),
        "semantic_claim_limits": _texts(annotation.get("semantic_claim_limits")),
        "allowed_support_kinds": allowed_support_kinds,
        "fulltext_acquisition_status": str(acquisition.get("status") or ""),
        "fulltext_available": (
            bool(acquisition.get("fulltext_available")) if acquisition else None
        ),
        "writing_direct_evidence_allowed": not fulltext_unavailable,
        "forbidden_as_direct_evidence": DIRECT_LEDGER_EVIDENCE not in allowed_support_kinds,
    }


def _qualified_slot_contributions(
    annotations_by_paper: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    valid_slots: Sequence[str],
) -> tuple[dict[str, list[str]], dict[str, dict[str, list[dict[str, Any]]]]]:
    """Return only root-level, explicit LLM partial/indirect paths by slot.

    A graph-expanded work intentionally has empty ``semantic_slot_contributions``
    and an empty support permission.  Therefore root lineage cannot manufacture
    a qualified, much less a direct, evidence path for its descendants.
    """

    by_slot: dict[str, list[str]] = {slot: [] for slot in valid_slots}
    constraints: dict[str, dict[str, list[dict[str, Any]]]] = {
        slot: {} for slot in valid_slots
    }
    valid = set(valid_slots)
    for paper_id, annotations in annotations_by_paper.items():
        for raw_annotation in annotations:
            annotation = _mapping(raw_annotation)
            if _annotation_evidence_use_mode(annotation) != QUALIFIED_SH_CONTRIBUTION:
                continue
            if str(annotation.get("association_stage") or "") not in {
                "SEED_SELECTION",
                FULLTEXT_PROMOTION_STAGE,
            }:
                continue
            constraint = _role_constraint(annotation)
            for raw_contribution in annotation.get("semantic_slot_contributions", []):
                contribution = _mapping(raw_contribution)
                slot_name = str(contribution.get("slot_name") or "").strip()
                support_level = str(
                    contribution.get("support_level") or ""
                ).strip().casefold()
                if slot_name not in valid or support_level not in {
                    "direct",
                    "partial",
                    "indirect",
                }:
                    continue
                by_slot[slot_name] = _texts([*by_slot[slot_name], paper_id])
                record = {
                    **constraint,
                    "semantic_support_level": support_level,
                    "semantic_contribution_reason": str(
                        contribution.get("reason") or ""
                    ),
                }
                existing = constraints[slot_name].setdefault(paper_id, [])
                if record not in existing:
                    existing.append(record)
    return by_slot, constraints


def _fulltext_promoted_slot_contributions(
    annotations_by_paper: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    valid_slots: Sequence[str],
) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    """Return direct/background slot support earned by a read graph candidate.

    The only accepted records here have the explicit ``FULLTEXT_PROMOTION``
    stage.  This keeps the original graph-expansion annotation non-evidentiary
    even when it shares a paper and an SH with a later promotion record.
    """

    direct_by_slot = {slot: [] for slot in valid_slots}
    background_by_slot = {slot: [] for slot in valid_slots}
    valid = set(valid_slots)
    for paper_id, annotations in annotations_by_paper.items():
        for raw_annotation in annotations:
            annotation = _mapping(raw_annotation)
            if str(annotation.get("association_stage") or "") != FULLTEXT_PROMOTION_STAGE:
                continue
            mode = _annotation_evidence_use_mode(annotation)
            if mode not in {DIRECT_LEDGER_EVIDENCE, "BACKGROUND_CONTEXT"}:
                continue
            for raw_contribution in annotation.get("semantic_slot_contributions", []):
                contribution = _mapping(raw_contribution)
                slot_name = str(contribution.get("slot_name") or "").strip()
                support_level = str(
                    contribution.get("support_level") or ""
                ).strip().casefold()
                if slot_name not in valid or support_level not in {
                    "direct",
                    "partial",
                    "indirect",
                }:
                    continue
                if mode == DIRECT_LEDGER_EVIDENCE and support_level == "direct":
                    direct_by_slot[slot_name] = _texts(
                        [*direct_by_slot[slot_name], paper_id]
                    )
                elif mode == "BACKGROUND_CONTEXT":
                    background_by_slot[slot_name] = _texts(
                        [*background_by_slot[slot_name], paper_id]
                    )
    return direct_by_slot, background_by_slot


def _is_fulltext_promoted_expanded_paper(
    paper_id: str,
    role_annotations_by_paper: Mapping[str, Sequence[Mapping[str, Any]]],
) -> bool:
    """True only when a paper has no independently usable non-expanded role."""

    annotations = role_annotations_by_paper.get(paper_id, [])
    if not annotations:
        return False
    usable_annotations = [
        _mapping(annotation)
        for annotation in annotations
        if _annotation_evidence_use_mode(_mapping(annotation))
        in {
            DIRECT_LEDGER_EVIDENCE,
            QUALIFIED_SH_CONTRIBUTION,
            "BACKGROUND_CONTEXT",
        }
    ]
    return bool(usable_annotations) and all(
        str(annotation.get("association_stage") or "") == FULLTEXT_PROMOTION_STAGE
        for annotation in usable_annotations
    )


def _promotion_rank(
    paper_id: str,
    role_annotations_by_paper: Mapping[str, Sequence[Mapping[str, Any]]],
) -> tuple[int, float, float, str]:
    """Rank promoted papers by their independent SH assessment, deterministically."""

    role_priority = 3
    semantic_score = 0.0
    relatedness_score = 0.0
    for raw_annotation in role_annotations_by_paper.get(paper_id, []):
        annotation = _mapping(raw_annotation)
        if str(annotation.get("association_stage") or "") != FULLTEXT_PROMOTION_STAGE:
            continue
        role_priority = min(
            role_priority,
            {
                DIRECT_LEDGER_EVIDENCE: 0,
                QUALIFIED_SH_CONTRIBUTION: 1,
                "BACKGROUND_CONTEXT": 2,
            }.get(_annotation_evidence_use_mode(annotation), 3),
        )
        try:
            semantic_score = max(
                semantic_score, float(annotation.get("semantic_relevance_score") or 0.0)
            )
        except (TypeError, ValueError):
            pass
        try:
            relatedness_score = max(
                relatedness_score, float(annotation.get("promotion_relatedness_score") or 0.0)
            )
        except (TypeError, ValueError):
            pass
    return (role_priority, -semantic_score, -relatedness_score, paper_id)


def _apply_writing_paper_cap(
    *,
    evidence_paper_ids: Sequence[str],
    qualified_paper_ids: Sequence[str],
    context_paper_ids: Sequence[str],
    challenge_paper_ids: Sequence[str],
    slot_support: Mapping[str, Mapping[str, Any]],
    role_annotations_by_paper: Mapping[str, Sequence[Mapping[str, Any]]],
    max_writable_papers: int,
) -> tuple[
    list[str],
    list[str],
    list[str],
    list[str],
    dict[str, dict[str, Any]],
    dict[str, Any],
]:
    """Choose non-expanded evidence first, then promoted expansions up to a cap."""

    ordered_ids = canonical_paper_ids(
        [*evidence_paper_ids, *qualified_paper_ids, *context_paper_ids]
    )
    non_expanded = [
        paper_id
        for paper_id in ordered_ids
        if not _is_fulltext_promoted_expanded_paper(
            paper_id, role_annotations_by_paper
        )
    ]
    promoted_expanded = [
        paper_id
        for paper_id in ordered_ids
        if _is_fulltext_promoted_expanded_paper(
            paper_id, role_annotations_by_paper
        )
    ]
    selected_non_expanded = non_expanded[:max_writable_papers]
    remaining = max(0, max_writable_papers - len(selected_non_expanded))
    selected_promoted = sorted(
        promoted_expanded,
        key=lambda paper_id: _promotion_rank(paper_id, role_annotations_by_paper),
    )[:remaining]
    selected_ids = set([*selected_non_expanded, *selected_promoted])

    def keep(ids: Sequence[str]) -> list[str]:
        return [
            paper_id
            for paper_id in canonical_paper_ids(ids)
            if paper_id in selected_ids
        ]

    filtered_slot_support: dict[str, dict[str, Any]] = {}
    for slot_name, raw_support in slot_support.items():
        support = _mapping(raw_support)
        support["evidence_paper_ids"] = keep(support.get("evidence_paper_ids", []))
        support["qualified_paper_ids"] = keep(support.get("qualified_paper_ids", []))
        support["background_paper_ids"] = keep(
            support.get("background_paper_ids", [])
        )
        qualified_constraints = _mapping(
            support.get("qualified_paper_constraints")
        )
        support["qualified_paper_constraints"] = {
            paper_id: constraints
            for paper_id, constraints in qualified_constraints.items()
            if canonical_paper_id(paper_id) in selected_ids
        }
        filtered_slot_support[str(slot_name)] = support

    selection_audit = {
        "max_writable_papers": max_writable_papers,
        "non_expanded_available": len(non_expanded),
        "promoted_expanded_available": len(promoted_expanded),
        "selected_non_expanded_paper_ids": selected_non_expanded,
        "selected_promoted_expanded_paper_ids": selected_promoted,
        "excluded_by_writing_cap_paper_ids": [
            paper_id for paper_id in ordered_ids if paper_id not in selected_ids
        ],
        "selection_policy": "non_expanded_first_then_fulltext_promotion_role_and_sh_relevance_ranked_expansions",
    }
    return (
        keep(evidence_paper_ids),
        keep(qualified_paper_ids),
        keep(context_paper_ids),
        keep(challenge_paper_ids),
        filtered_slot_support,
        selection_audit,
    )


def _cluster_contributions(
    cluster_coverage: Mapping[str, Any],
    subhypothesis_id: str,
) -> list[dict[str, Any]]:
    contributions: list[dict[str, Any]] = []
    for raw_cluster in _records(cluster_coverage.get("clusters")):
        cluster = _mapping(raw_cluster)
        cluster_index = int(cluster.get("cluster_index") or 0)
        for raw_report in _records(cluster.get("subhypotheses")):
            report = _mapping(raw_report)
            if report.get("sub_hypothesis_id") != subhypothesis_id:
                continue
            state = str(report.get("cluster_evidence_state") or "NO_CLUSTER_ASSOCIATION")
            if state == "NO_CLUSTER_ASSOCIATION":
                continue
            contributions.append(
                {
                    "cluster_id": f"cluster_{cluster_index}",
                    "cluster_index": cluster_index,
                    "cluster_name": str(cluster.get("cluster_name") or f"cluster_{cluster_index}"),
                    "evidence_state": state,
                    "evidence_paper_ids": canonical_paper_ids(
                        report.get("evidence_paper_ids")
                    ),
                    "background_paper_ids": canonical_paper_ids(
                        report.get("background_paper_ids")
                    ),
                    "candidate_paper_ids": canonical_paper_ids(
                        [
                            *report.get("graph_expanded_candidate_paper_ids", []),
                            *report.get("seed_candidate_paper_ids", []),
                        ]
                    ),
                    "covered_slots": _texts(report.get("cluster_covered_slots")),
                    "background_slots": _texts(report.get("cluster_background_slots")),
                    "uncovered_required_slots": _texts(
                        report.get("cluster_uncovered_required_slots")
                    ),
                }
            )
    return contributions


def _writing_mode(
    *,
    admissibility: Mapping[str, Any],
    evidence_paper_ids: Sequence[str],
    qualified_paper_ids: Sequence[str],
    context_paper_ids: Sequence[str],
    scope_rejections: Sequence[Mapping[str, Any]],
) -> str:
    if bool(admissibility.get("admissible")):
        return EVIDENCE_BACKED_SYNTHESIS
    if evidence_paper_ids or qualified_paper_ids:
        return QUALIFIED_SYNTHESIS
    if context_paper_ids:
        return BACKGROUND_ONLY
    if scope_rejections:
        return OUT_OF_SCOPE_OR_REJECTED
    return EVIDENCE_GAP_REPORT


def _allowed_claim_modes(writing_mode: str) -> list[str]:
    return {
        EVIDENCE_BACKED_SYNTHESIS: [
            EVIDENCE_BACKED_SYNTHESIS,
            QUALIFIED_SYNTHESIS,
        ],
        QUALIFIED_SYNTHESIS: [QUALIFIED_SYNTHESIS],
        BACKGROUND_ONLY: [BACKGROUND_ONLY],
        EVIDENCE_GAP_REPORT: [EVIDENCE_GAP_REPORT],
        OUT_OF_SCOPE_OR_REJECTED: [OUT_OF_SCOPE_OR_REJECTED],
    }[writing_mode]


def build_survey_evidence_plan(
    *,
    provenance_artifact: Mapping[str, Any] | None,
    coverage_ledger: Mapping[str, Any] | None,
    cluster_coverage_artifact: Mapping[str, Any] | None,
    subhypothesis_contracts: Sequence[Mapping[str, Any]] | None,
    max_writable_papers_per_sh: int = 20,
    multimodal_evidence: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Compile every SH into its allowed writing mode and evidence boundary."""

    try:
        max_writable_papers_per_sh = int(max_writable_papers_per_sh)
    except (TypeError, ValueError) as exc:
        raise ValueError("max_writable_papers_per_sh must be a positive integer.") from exc
    if max_writable_papers_per_sh <= 0:
        raise ValueError("max_writable_papers_per_sh must be a positive integer.")

    provenance, ledger, cluster_coverage = _validate_inputs(
        provenance_artifact,
        coverage_ledger,
        cluster_coverage_artifact,
    )
    reports_by_sh = _report_index(ledger)
    contracts_by_sh = _contract_index(subhypothesis_contracts)
    provenance_roles_by_sh = _provenance_role_index(provenance)
    if set(reports_by_sh) != set(contracts_by_sh):
        missing_reports = sorted(set(contracts_by_sh) - set(reports_by_sh))
        unexpected_reports = sorted(set(reports_by_sh) - set(contracts_by_sh))
        details: list[str] = []
        if missing_reports:
            details.append("missing ledger reports=" + ",".join(missing_reports))
        if unexpected_reports:
            details.append("unexpected ledger reports=" + ",".join(unexpected_reports))
        raise ValueError(
            "Survey evidence plan requires an exact contract/ledger SH set: "
            + "; ".join(details)
        )
    entries: list[dict[str, Any]] = []

    for subhypothesis_id, report in reports_by_sh.items():
        contract = contracts_by_sh.get(subhypothesis_id)
        if contract is None:
            raise ValueError(
                f"Survey evidence plan has no compiled contract for SH '{subhypothesis_id}'."
            )
        if not str(contract.get("research_role") or "").strip():
            raise ValueError(
                f"Survey evidence plan requires research_role for SH '{subhypothesis_id}'."
            )
        contract_question_kind = str(contract.get("question_kind") or "").strip()
        report_question_kind = str(report.get("question_kind") or "").strip()
        if not contract_question_kind or contract_question_kind != report_question_kind:
            raise ValueError(
                f"Survey evidence plan received mismatched question_kind for SH '{subhypothesis_id}'."
            )
        contract_slots = _texts(contract.get("required_slots"))
        report_slots = _texts(report.get("required_slots"))
        if not contract_slots or set(contract_slots) != set(report_slots):
            raise ValueError(
                f"Survey evidence plan received mismatched required_slots for SH '{subhypothesis_id}'."
            )
        slot_ledger = _mapping(report.get("slot_ledger"))
        evidence_paper_ids: list[str] = []
        context_paper_ids: list[str] = []
        challenge_paper_ids: list[str] = []
        slot_support: dict[str, dict[str, Any]] = {}
        scope_rejections: list[dict[str, Any]] = []
        role_annotations_by_paper = provenance_roles_by_sh.get(subhypothesis_id, {})
        qualified_by_slot, qualified_constraints_by_slot = _qualified_slot_contributions(
            role_annotations_by_paper,
            valid_slots=_texts(report.get("required_slots")),
        )
        promoted_direct_by_slot, promoted_background_by_slot = (
            _fulltext_promoted_slot_contributions(
                role_annotations_by_paper,
                valid_slots=_texts(report.get("required_slots")),
            )
        )
        qualified_paper_ids: list[str] = []

        for slot_name, raw_slot in slot_ledger.items():
            slot = _mapping(raw_slot)
            evidence_role = str(slot.get("expected_evidence_role") or "")
            direct_ids = canonical_paper_ids(
                [
                    *_paper_ids(_records(slot.get("covered_by"))),
                    *promoted_direct_by_slot.get(str(slot_name), []),
                ]
            )
            background_ids = canonical_paper_ids(
                [
                    *_paper_ids(_records(slot.get("background_only_by"))),
                    *promoted_background_by_slot.get(str(slot_name), []),
                ]
            )
            qualified_ids = _texts(qualified_by_slot.get(str(slot_name), []))
            rejected = _records(slot.get("scope_rejections"))
            evidence_paper_ids = _texts([*evidence_paper_ids, *direct_ids])
            context_paper_ids = _texts([*context_paper_ids, *background_ids])
            qualified_paper_ids = _texts([*qualified_paper_ids, *qualified_ids])
            if evidence_role == "LIMITING_OR_CHALLENGING_EVIDENCE":
                challenge_paper_ids = _texts([*challenge_paper_ids, *direct_ids])
            scope_rejections.extend(rejected)
            slot_support[str(slot_name)] = {
                "task_id": str(slot.get("task_id") or ""),
                "expected_evidence_role": evidence_role,
                "evidence_paper_ids": direct_ids,
                "background_paper_ids": background_ids,
                "qualified_paper_ids": qualified_ids,
                "qualified_paper_constraints": qualified_constraints_by_slot.get(
                    str(slot_name), {}
                ),
                "minimum_evidence": str(slot.get("minimum_evidence") or ""),
                "admission_rule": str(slot.get("admission_rule") or ""),
            }

        admissibility = _mapping(report.get("conclusion_admissibility"))
        cluster_contributions = _cluster_contributions(
            cluster_coverage,
            subhypothesis_id,
        )
        role_constraints = {
            paper_id: [_role_constraint(annotation) for annotation in annotations]
            for paper_id, annotations in role_annotations_by_paper.items()
        }
        direct_writing_blocked_ids = canonical_paper_ids(
            [
                paper_id
                for paper_id, constraints in role_constraints.items()
                if any(
                    _mapping(constraint).get("evidence_use_mode")
                    == DIRECT_LEDGER_EVIDENCE
                    and bool(_mapping(constraint).get("fulltext_available")) is False
                    and str(
                        _mapping(constraint).get("fulltext_acquisition_status")
                        or ""
                    )
                    for constraint in constraints
                )
            ]
        )
        (
            evidence_paper_ids,
            qualified_paper_ids,
            context_paper_ids,
            challenge_paper_ids,
            slot_support,
            writing_paper_selection,
        ) = _apply_writing_paper_cap(
            evidence_paper_ids=evidence_paper_ids,
            qualified_paper_ids=qualified_paper_ids,
            context_paper_ids=context_paper_ids,
            challenge_paper_ids=challenge_paper_ids,
            slot_support=slot_support,
            role_annotations_by_paper=role_annotations_by_paper,
            max_writable_papers=max_writable_papers_per_sh,
        )
        mode = _writing_mode(
            admissibility=admissibility,
            evidence_paper_ids=evidence_paper_ids,
            qualified_paper_ids=qualified_paper_ids,
            context_paper_ids=context_paper_ids,
            scope_rejections=scope_rejections,
        )
        cluster_candidate_ids = canonical_paper_ids(
            [
                candidate
                for cluster in cluster_contributions
                for candidate in cluster["candidate_paper_ids"]
            ]
        )
        provenance_forbidden_ids = canonical_paper_ids(
            [
                paper_id
                for paper_id, annotations in role_annotations_by_paper.items()
                if any(
                    _annotation_evidence_use_mode(annotation)
                    == GRAPH_EXPANDED_CANDIDATE_ONLY
                    for annotation in annotations
                )
            ]
        )
        allowed_paper_ids = canonical_paper_ids(
            [*evidence_paper_ids, *context_paper_ids, *qualified_paper_ids]
        )
        entries.append(
            {
                "sub_hypothesis_id": subhypothesis_id,
                "summary": str(report.get("question") or ""),
                "question_kind": str(report.get("question_kind") or ""),
                "research_role": str(contract.get("research_role") or ""),
                "challenge_target": str(contract.get("challenge_target") or ""),
                "required_slots": _texts(report.get("required_slots")),
                "covered_slots": _texts(report.get("covered_slots")),
                "background_only_slots": _texts(report.get("background_only_slots")),
                "missing_slots": _texts(report.get("missing_slots")),
                "slot_support": slot_support,
                "writing_paper_selection": writing_paper_selection,
                "conclusion_admissibility": admissibility,
                "limitations": {
                    "blockers": _texts(admissibility.get("blockers")),
                    "scope_rejection_count": len(scope_rejections),
                    "scope_rejections": scope_rejections,
                },
                "evidence_paper_ids": evidence_paper_ids,
                "context_paper_ids": context_paper_ids,
                "qualified_paper_ids": qualified_paper_ids,
                "challenge_paper_ids": challenge_paper_ids,
                "paper_role_constraints": role_constraints,
                "direct_writing_blocked_paper_ids": direct_writing_blocked_ids,
                "relevant_clusters": cluster_contributions,
                "allowed_writing_mode": mode,
                "allowed_claim_modes": _allowed_claim_modes(mode),
                "forbidden_paper_ids": canonical_paper_ids(
                    [
                        candidate
                        for candidate in [
                            *cluster_candidate_ids,
                            *provenance_forbidden_ids,
                        ]
                        if candidate not in allowed_paper_ids
                    ]
                ),
            }
        )

    multimodal_projection = build_multimodal_survey_projection(multimodal_evidence)
    if multimodal_projection is not None:
        by_subhypothesis = {
            str(item.get("sub_hypothesis_id") or ""): item
            for item in multimodal_projection.get("data_anchored_subhypotheses", [])
            if isinstance(item, Mapping)
        }
        unresolved_data_sh = sorted(
            identifier
            for identifier in by_subhypothesis
            if identifier not in {
                str(entry.get("sub_hypothesis_id") or "") for entry in entries
            }
        )
        if unresolved_data_sh:
            raise ValueError(
                "Multimodal evidence references data-anchored SHs absent from the final coverage ledger: "
                + ", ".join(unresolved_data_sh)
            )
        for entry in entries:
            row = by_subhypothesis.get(str(entry.get("sub_hypothesis_id") or ""))
            if row is None:
                continue
            entry["analysis_priority"] = str(row.get("analysis_priority") or "")
            entry["must_cover"] = bool(row.get("must_cover"))
            entry["multimodal_projection"] = dict(row)
            entry["allowed_claim_modes"] = _texts(
                [LOCAL_DATA_OBSERVATION, *entry.get("allowed_claim_modes", [])]
            )

    payload = {
        "schema_version": SURVEY_EVIDENCE_PLAN_SCHEMA_VERSION,
        "project_id": str(provenance.get("project_id") or ""),
        "project_context_fingerprint": str(
            provenance.get("project_context_fingerprint") or ""
        ),
        "evidence_bounded_writing": True,
        "subhypotheses": entries,
        "writing_rules": {
            "all_subhypotheses_accounted_for": True,
            "graph_expanded_candidates_are_not_evidence": True,
            "complete_section_promoted_expanded_papers_may_be_used_only_by_their_own_sh_role": True,
            "max_writable_papers_per_sh": max_writable_papers_per_sh,
            "non_expanded_papers_are_selected_before_promoted_expanded_papers": True,
            "graph_root_role_does_not_upgrade_graph_expanded_nodes": True,
            "partial_or_indirect_seed_contributions_require_qualified_synthesis": True,
            "background_context_is_not_direct_evidence": True,
            "not_admissible_subhypotheses_cannot_receive_assertive_conclusions": True,
            "claims_require_sh_slot_paper_trace": True,
        },
    }
    if multimodal_projection is not None:
        payload["multimodal_evidence_projection"] = multimodal_projection
        payload["writing_rules"]["multimodal_observations_are_not_literature"] = True
        payload["writing_rules"]["data_anchored_subhypotheses_must_cover"] = True
    return payload
