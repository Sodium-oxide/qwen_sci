from pathlib import Path
from types import SimpleNamespace

import networkx as nx
import pytest

from src.agents.survey_agent.modules.work_collector import WorkCollector  # noqa: F401
from src.agents.survey_agent.modules.work_analyzer import WorkAnalyzer
from src.pipeline.sh_cluster_projection import (
    SH_CLUSTER_COVERAGE_SCHEMA_VERSION,
    build_cluster_sh_coverage_projection,
)
from src.pipeline.sh_graph_provenance import (
    BACKGROUND_CONTEXT,
    GRAPH_EXPANDED_CANDIDATE,
    LEDGER_CONFIRMED_EVIDENCE,
    SH_GRAPH_PROVENANCE_SCHEMA_VERSION,
    SH_NODE_ANNOTATION_SCHEMA_VERSION,
)


class _Logger:
    def info(self, *_args, **_kwargs):
        pass


def _annotation(
    subhypothesis_id: str,
    status: str,
    *,
    covered_slots: list[str] | None = None,
) -> dict:
    return {
        "schema_version": SH_NODE_ANNOTATION_SCHEMA_VERSION,
        "project_id": "sci_project",
        "project_context_fingerprint": "context-A",
        "sub_hypothesis_id": subhypothesis_id,
        "association_stage": "SEED_SELECTION"
        if status != GRAPH_EXPANDED_CANDIDATE
        else "GRAPH_EXPANSION",
        "association_status": status,
        "root_seed_paper_ids": ["W1"],
        "parent_paper_ids": [],
        "lineage_depth": 0 if status != GRAPH_EXPANDED_CANDIDATE else 1,
        "citation_direction": "",
        "covered_slots": covered_slots or [],
        "slot_recovery_task_ids": [],
        "expected_evidence_roles": [],
        "root_evidence_roles": [],
        "selected_for_slots": [],
    }


def _provenance() -> dict:
    return {
        "schema_version": SH_GRAPH_PROVENANCE_SCHEMA_VERSION,
        "project_id": "sci_project",
        "project_context_fingerprint": "context-A",
        "paper_annotations": {
            "W1": [_annotation("SH1", LEDGER_CONFIRMED_EVIDENCE, covered_slots=["candidate"])],
            "W2": [_annotation("SH1", BACKGROUND_CONTEXT, covered_slots=["background_framework"])],
            "W3": [_annotation("SH1", GRAPH_EXPANDED_CANDIDATE)],
        },
        "graph_expansion_records": [],
    }


def _ledger() -> dict:
    return {
        "schema_version": "evidence_coverage_ledger_v1",
        "subhypotheses": [
            {
                "sub_hypothesis_id": "SH1",
                "required_slots": ["candidate", "comparator", "background_framework"],
                "covered_slots": ["candidate", "background_framework"],
                "background_only_slots": [],
                "missing_slots": ["comparator"],
                "conclusion_admissibility": {
                    "admissible": False,
                    "blockers": ["missing_required_slot:comparator"],
                },
            },
            {
                "sub_hypothesis_id": "SH2",
                "required_slots": ["direct_observation"],
                "covered_slots": [],
                "background_only_slots": [],
                "missing_slots": ["direct_observation"],
                "conclusion_admissibility": {
                    "admissible": False,
                    "blockers": ["missing_required_slot:direct_observation"],
                },
            },
        ],
    }


def _clusters() -> list[dict]:
    return [
        {
            "cluster_name": "evidence and context",
            "summary": "A global thematic cluster.",
            "papers": [
                {"id": "W1", "title": "Direct evidence", "tldr": ""},
                {"id": "W2", "title": "Background", "tldr": ""},
                {"id": "W3", "title": "Expansion candidate", "tldr": ""},
            ],
        },
        {
            "cluster_name": "unlinked theme",
            "summary": "A cluster with no current SH association.",
            "papers": [{"id": "W4", "title": "Unlinked", "tldr": ""}],
        },
    ]


def test_cluster_projection_preserves_clusters_and_exposes_evidence_background_and_gap() -> None:
    graph = nx.DiGraph()
    graph.add_node("W3", sh_annotations=_provenance()["paper_annotations"]["W3"])
    enriched, artifact = build_cluster_sh_coverage_projection(
        _clusters(),
        provenance_artifact=_provenance(),
        coverage_ledger=_ledger(),
        graph=graph,
        project_context_fingerprint="context-A",
    )

    assert [item["cluster_name"] for item in enriched] == [
        "evidence and context",
        "unlinked theme",
    ]
    assert [paper["id"] for paper in enriched[0]["papers"]] == ["W1", "W2", "W3"]
    projection = enriched[0]["sh_coverage_projection"]
    assert projection["schema_version"] == SH_CLUSTER_COVERAGE_SCHEMA_VERSION
    assert projection["primary_subhypothesis_ids"] == ["SH1"]
    sh1 = projection["subhypotheses"][0]
    assert sh1["cluster_evidence_state"] == "DIRECT_EVIDENCE"
    assert sh1["evidence_paper_ids"] == ["W1"]
    assert sh1["background_paper_ids"] == ["W2"]
    assert sh1["graph_expanded_candidate_paper_ids"] == ["W3"]
    assert sh1["cluster_covered_slots"] == ["candidate"]
    assert sh1["project_missing_slots"] == ["comparator"]
    assert sh1["project_conclusion_admissibility"]["admissible"] is False
    unlinked_reports = {
        item["sub_hypothesis_id"]
        for item in enriched[1]["sh_coverage_projection"]["subhypotheses"]
    }
    assert unlinked_reports == {"SH1", "SH2"}
    assert enriched[1]["sh_coverage_projection"]["gap_subhypothesis_ids"] == ["SH1", "SH2"]
    assert artifact["unrepresented_subhypothesis_ids"] == ["SH2"]


def test_cluster_projection_rejects_cross_project_provenance() -> None:
    with pytest.raises(ValueError, match="different project context"):
        build_cluster_sh_coverage_projection(
            _clusters(),
            provenance_artifact=_provenance(),
            coverage_ledger=_ledger(),
            project_context_fingerprint="other-project",
        )


def test_cluster_projection_ignores_same_fingerprint_annotations_from_another_project() -> None:
    graph = nx.DiGraph()
    stale = _annotation("SH1", LEDGER_CONFIRMED_EVIDENCE, covered_slots=["candidate"])
    stale["project_id"] = "sci_previous_run"
    graph.add_node("W4", sh_annotations=[stale])

    enriched, _artifact = build_cluster_sh_coverage_projection(
        _clusters(),
        provenance_artifact=_provenance(),
        coverage_ledger=_ledger(),
        graph=graph,
        project_context_fingerprint="context-A",
    )

    reports = enriched[1]["sh_coverage_projection"]["subhypotheses"]
    assert all(item["cluster_evidence_state"] == "NO_CLUSTER_ASSOCIATION" for item in reports)
    assert all(not item["evidence_paper_ids"] for item in reports)


def test_cluster_projection_rejects_non_v1_coverage_ledger() -> None:
    with pytest.raises(ValueError, match="evidence_coverage_ledger_v1"):
        build_cluster_sh_coverage_projection(
            _clusters(),
            provenance_artifact=_provenance(),
            coverage_ledger={"schema_version": "legacy_ledger", "subhypotheses": []},
            project_context_fingerprint="context-A",
        )


def test_work_analyzer_persists_the_project_scoped_cluster_projection(tmp_path) -> None:
    analyzer = object.__new__(WorkAnalyzer)
    analyzer.logger = _Logger()
    analyzer.config = SimpleNamespace(
        BasicInfo=SimpleNamespace(base_dir=str(tmp_path)),
    )
    analyzer.work_collector = SimpleNamespace(
        sh_graph_provenance_artifact=_provenance(),
        subhypothesis_retrieval_artifact={
            "plan": {"project_context": {"project_context_fingerprint": "context-A"}},
            "evidence_coverage_ledger_final": _ledger(),
        },
        reference_graph=nx.DiGraph(),
    )

    projected = analyzer._project_clusters_with_sh_coverage(_clusters())

    assert projected[0]["sh_coverage_projection"]["primary_subhypothesis_ids"] == ["SH1"]
    assert analyzer.sh_cluster_coverage_artifact["schema_version"] == (
        SH_CLUSTER_COVERAGE_SCHEMA_VERSION
    )
    assert analyzer.work_collector.sh_cluster_coverage_artifact == analyzer.sh_cluster_coverage_artifact
    assert Path(tmp_path / "sh_cluster_coverage.json").exists()


def test_sh_projection_cache_token_changes_with_project_provenance(tmp_path) -> None:
    analyzer = object.__new__(WorkAnalyzer)
    analyzer.config = SimpleNamespace(BasicInfo=SimpleNamespace(base_dir=str(tmp_path)))
    analyzer.cache_path = str(tmp_path)
    provenance = _provenance()
    analyzer.work_collector = SimpleNamespace(
        sh_graph_provenance_artifact=provenance,
        subhypothesis_retrieval_artifact={
            "plan": {"project_context": {"project_context_fingerprint": "context-A"}},
            "evidence_coverage_ledger_final": _ledger(),
        },
    )

    original_cluster_key = analyzer._cluster_cache_key(["W1"])
    original_relation_key = analyzer._relation_graph_cache_key(_clusters())
    provenance["paper_annotations"]["W3"][0]["root_seed_paper_ids"] = ["W9"]

    assert analyzer._cluster_cache_key(["W1"]) != original_cluster_key
    assert analyzer._relation_graph_cache_key(_clusters()) != original_relation_key
