"""Project SH evidence/background/gap projections over existing global clusters.

This is intentionally a projection, not a second clustering algorithm.  A
paper can contribute to multiple SHs, and a cluster may remain globally useful
even when it contributes only background or exploration candidates to a given
SH.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from src.pipeline.evidence_coverage_ledger import (
    EVIDENCE_COVERAGE_LEDGER_SCHEMA_VERSION,
)
from src.pipeline.sh_graph_provenance import (
    BACKGROUND_CONTEXT,
    GRAPH_EXPANDED_CANDIDATE,
    LEDGER_CONFIRMED_EVIDENCE,
    SEED_CANDIDATE,
    SH_GRAPH_PROVENANCE_SCHEMA_VERSION,
    current_project_node_annotations,
    merge_node_annotations,
)


SH_CLUSTER_COVERAGE_SCHEMA_VERSION = "sh_cluster_coverage_projection_v1"


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


def _ledger_reports(coverage_ledger: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    reports: dict[str, dict[str, Any]] = {}
    for raw_report in _mapping(coverage_ledger).get("subhypotheses", []):
        report = _mapping(raw_report)
        subhypothesis_id = str(report.get("sub_hypothesis_id") or "").strip()
        if subhypothesis_id:
            reports[subhypothesis_id] = report
    return reports


def _validated_coverage_ledger(coverage_ledger: Mapping[str, Any] | None) -> dict[str, Any]:
    """Reject non-v1/partial ledgers rather than silently projecting no SHs."""

    ledger = _mapping(coverage_ledger)
    if ledger.get("schema_version") != EVIDENCE_COVERAGE_LEDGER_SCHEMA_VERSION:
        raise ValueError("SH cluster projection requires an evidence_coverage_ledger_v1 ledger.")
    raw_reports = ledger.get("subhypotheses")
    if not isinstance(raw_reports, Sequence) or isinstance(raw_reports, (str, bytes)):
        raise ValueError("SH coverage ledger must provide a subhypotheses sequence.")
    for raw_report in raw_reports:
        report = _mapping(raw_report)
        subhypothesis_id = str(report.get("sub_hypothesis_id") or "").strip()
        required_slots = report.get("required_slots")
        if (
            not subhypothesis_id
            or not isinstance(required_slots, Sequence)
            or isinstance(required_slots, (str, bytes))
        ):
            raise ValueError("SH coverage ledger contains an invalid subhypothesis report.")
    return ledger


def _paper_ids(cluster: Mapping[str, Any]) -> list[str]:
    return _texts(
        [
            _mapping(paper).get("id")
            for paper in cluster.get("papers", [])
            if isinstance(paper, Mapping)
        ]
    )


def annotation_index_from_provenance(
    provenance_artifact: Mapping[str, Any] | None,
    *,
    graph: Any = None,
    project_context_fingerprint: str,
) -> dict[str, list[dict[str, Any]]]:
    """Return only current-project v1 annotations from the artifact and graph."""

    artifact = _mapping(provenance_artifact)
    if artifact.get("schema_version") != SH_GRAPH_PROVENANCE_SCHEMA_VERSION:
        raise ValueError("SH graph provenance artifact is missing or has an unsupported schema.")
    if artifact.get("project_context_fingerprint") != project_context_fingerprint:
        raise ValueError("SH graph provenance belongs to a different project context.")
    project_id = str(artifact.get("project_id") or "").strip()
    if not project_id:
        raise ValueError("SH graph provenance is missing its project identifier.")

    output: dict[str, list[dict[str, Any]]] = {}
    sources: list[Mapping[str, Any]] = [_mapping(artifact.get("paper_annotations"))]
    if graph is not None and hasattr(graph, "nodes"):
        graph_records: dict[str, Any] = {}
        for paper_id, attrs in graph.nodes(data=True):
            record = _mapping(attrs)
            graph_records[str(paper_id)] = record.get("sh_annotations", [])
        sources.append(graph_records)
    for source in sources:
        for paper_id, raw_annotations in source.items():
            if not isinstance(raw_annotations, Sequence) or isinstance(
                raw_annotations, (str, bytes)
            ):
                continue
            current = current_project_node_annotations(
                raw_annotations,
                project_id=project_id,
                project_context_fingerprint=project_context_fingerprint,
            )
            if current:
                output[str(paper_id)] = merge_node_annotations(
                    output.get(str(paper_id)), current
                )
    return output


def _ordered_slots(required_slots: Sequence[str], slots: Sequence[str]) -> list[str]:
    wanted = _texts(slots)
    ordered = [slot for slot in _texts(required_slots) if slot in wanted]
    return _texts([*ordered, *(slot for slot in wanted if slot not in ordered)])


def _cluster_sh_report(
    subhypothesis_id: str,
    annotations: Sequence[tuple[str, Mapping[str, Any]]],
    ledger_report: Mapping[str, Any],
) -> dict[str, Any]:
    direct_paper_ids: list[str] = []
    background_paper_ids: list[str] = []
    graph_candidate_paper_ids: list[str] = []
    seed_candidate_paper_ids: list[str] = []
    covered_slots: list[str] = []
    background_slots: list[str] = []
    status_counts: dict[str, int] = {}

    for paper_id, raw_annotation in annotations:
        annotation = _mapping(raw_annotation)
        status = str(annotation.get("association_status") or "")
        status_counts[status] = status_counts.get(status, 0) + 1
        if status == LEDGER_CONFIRMED_EVIDENCE:
            direct_paper_ids = _texts([*direct_paper_ids, paper_id])
            covered_slots = _texts([*covered_slots, *annotation.get("covered_slots", [])])
        elif status == BACKGROUND_CONTEXT:
            background_paper_ids = _texts([*background_paper_ids, paper_id])
            background_slots = _texts(
                [*background_slots, *annotation.get("covered_slots", [])]
            )
        elif status == GRAPH_EXPANDED_CANDIDATE:
            graph_candidate_paper_ids = _texts([*graph_candidate_paper_ids, paper_id])
        elif status == SEED_CANDIDATE:
            seed_candidate_paper_ids = _texts([*seed_candidate_paper_ids, paper_id])

    ledger = _mapping(ledger_report)
    required_slots = _texts(ledger.get("required_slots"))
    project_missing_slots = _ordered_slots(required_slots, ledger.get("missing_slots"))
    project_background_only_slots = _ordered_slots(
        required_slots,
        ledger.get("background_only_slots"),
    )
    cluster_covered_slots = _ordered_slots(required_slots, covered_slots)
    return {
        "sub_hypothesis_id": subhypothesis_id,
        "cluster_evidence_state": (
            "DIRECT_EVIDENCE"
            if direct_paper_ids
            else "BACKGROUND_ONLY"
            if background_paper_ids
            else "EXPLORATION_ONLY"
            if graph_candidate_paper_ids or seed_candidate_paper_ids
            else "NO_CLUSTER_ASSOCIATION"
        ),
        "evidence_paper_ids": direct_paper_ids,
        "background_paper_ids": background_paper_ids,
        "graph_expanded_candidate_paper_ids": graph_candidate_paper_ids,
        "seed_candidate_paper_ids": seed_candidate_paper_ids,
        "cluster_covered_slots": cluster_covered_slots,
        "cluster_background_slots": _ordered_slots(required_slots, background_slots),
        "cluster_uncovered_required_slots": [
            slot for slot in required_slots if slot not in cluster_covered_slots
        ],
        "project_missing_slots": project_missing_slots,
        "project_background_only_slots": project_background_only_slots,
        "project_conclusion_admissibility": _mapping(
            ledger.get("conclusion_admissibility")
        ),
        "association_status_counts": status_counts,
    }


def build_cluster_sh_coverage_projection(
    clusters: Sequence[Mapping[str, Any]] | None,
    *,
    provenance_artifact: Mapping[str, Any] | None,
    coverage_ledger: Mapping[str, Any] | None,
    graph: Any = None,
    project_context_fingerprint: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Attach SH evidence/background/gap views without changing cluster membership."""

    ledger = _validated_coverage_ledger(coverage_ledger)
    reports_by_sh = _ledger_reports(ledger)
    annotation_index = annotation_index_from_provenance(
        provenance_artifact,
        graph=graph,
        project_context_fingerprint=project_context_fingerprint,
    )
    enriched_clusters: list[dict[str, Any]] = []
    projection_clusters: list[dict[str, Any]] = []
    represented_sh_ids: set[str] = set()

    for cluster_index, raw_cluster in enumerate(clusters or [], start=1):
        cluster = dict(raw_cluster) if isinstance(raw_cluster, Mapping) else {}
        paper_ids = _paper_ids(cluster)
        annotations_by_sh: dict[str, list[tuple[str, Mapping[str, Any]]]] = {}
        for paper_id in paper_ids:
            for annotation in annotation_index.get(paper_id, []):
                subhypothesis_id = str(annotation.get("sub_hypothesis_id") or "").strip()
                if subhypothesis_id:
                    annotations_by_sh.setdefault(subhypothesis_id, []).append(
                        (paper_id, annotation)
                    )

        sh_ids = _texts([*reports_by_sh.keys(), *annotations_by_sh.keys()])
        sh_reports = [
            _cluster_sh_report(
                subhypothesis_id,
                annotations_by_sh.get(subhypothesis_id, []),
                reports_by_sh.get(subhypothesis_id, {}),
            )
            for subhypothesis_id in sh_ids
        ]
        primary_sh_ids = [
            item["sub_hypothesis_id"]
            for item in sh_reports
            if item["cluster_evidence_state"] == "DIRECT_EVIDENCE"
        ]
        secondary_sh_ids = [
            item["sub_hypothesis_id"]
            for item in sh_reports
            if item["cluster_evidence_state"]
            in {"BACKGROUND_ONLY", "EXPLORATION_ONLY"}
        ]
        gap_sh_ids = [
            item["sub_hypothesis_id"]
            for item in sh_reports
            if item["cluster_evidence_state"] == "NO_CLUSTER_ASSOCIATION"
        ]
        represented_sh_ids.update(
            item["sub_hypothesis_id"]
            for item in sh_reports
            if item["cluster_evidence_state"] != "NO_CLUSTER_ASSOCIATION"
        )
        cluster_projection = {
            "schema_version": SH_CLUSTER_COVERAGE_SCHEMA_VERSION,
            "cluster_index": cluster_index,
            "cluster_name": str(cluster.get("cluster_name") or f"cluster_{cluster_index}"),
            "paper_ids": paper_ids,
            "primary_subhypothesis_ids": primary_sh_ids,
            "secondary_subhypothesis_ids": secondary_sh_ids,
            "gap_subhypothesis_ids": gap_sh_ids,
            "subhypotheses": sh_reports,
        }
        cluster["sh_coverage_projection"] = cluster_projection
        enriched_clusters.append(cluster)
        projection_clusters.append(cluster_projection)

    global_reports = [
        {
            "sub_hypothesis_id": subhypothesis_id,
            "required_slots": _texts(report.get("required_slots")),
            "covered_slots": _texts(report.get("covered_slots")),
            "background_only_slots": _texts(report.get("background_only_slots")),
            "missing_slots": _texts(report.get("missing_slots")),
            "conclusion_admissibility": _mapping(report.get("conclusion_admissibility")),
        }
        for subhypothesis_id, report in reports_by_sh.items()
    ]
    artifact = {
        "schema_version": SH_CLUSTER_COVERAGE_SCHEMA_VERSION,
        "project_id": str(_mapping(provenance_artifact).get("project_id") or ""),
        "project_context_fingerprint": project_context_fingerprint,
        "clusters": projection_clusters,
        "project_subhypotheses": global_reports,
        "unrepresented_subhypothesis_ids": [
            subhypothesis_id
            for subhypothesis_id in reports_by_sh
            if subhypothesis_id not in represented_sh_ids
        ],
    }
    return enriched_clusters, artifact
