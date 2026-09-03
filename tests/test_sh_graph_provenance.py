from pathlib import Path
from types import SimpleNamespace

import networkx as nx

from src.agents.survey_agent.modules.work_collector import WorkCollector
from src.pipeline.sh_graph_provenance import (
    BACKGROUND_CONTEXT,
    DIRECT_LEDGER_EVIDENCE,
    FULLTEXT_PROMOTED_EXPANDED,
    FULLTEXT_PROMOTION_STAGE,
    GRAPH_EXPANDED_CANDIDATE,
    GRAPH_EXPANDED_CANDIDATE_ONLY,
    LEDGER_CONFIRMED_EVIDENCE,
    build_fulltext_promotion_annotations,
    build_graph_expansion_annotations,
    build_seed_annotation_index,
    merge_node_annotations,
)


class _Logger:
    def info(self, *_args, **_kwargs):
        pass

    def warning(self, *_args, **_kwargs):
        pass

    def error(self, *_args, **_kwargs):
        pass


def _ledger() -> dict:
    return {
        "schema_version": "evidence_coverage_ledger_v1",
        "subhypotheses": [
            {
                "sub_hypothesis_id": "SH1",
                "slot_ledger": {
                    "candidate": {
                        "task_id": "SH1.candidate",
                        "slot_name": "candidate",
                        "expected_evidence_role": "DIRECT_OBSERVATION",
                        "covered_by": [{"paper_id": "seed-paper"}],
                    },
                    "background_framework": {
                        "task_id": "SH1.background_framework",
                        "slot_name": "background_framework",
                        "expected_evidence_role": "BACKGROUND_CONTEXT",
                        "covered_by": [{"paper_id": "context-paper"}],
                    },
                },
                "missing_slots": ["comparator"],
                "background_only_slots": [],
                "conclusion_admissibility": {"admissible": False},
            }
        ],
    }


def _selected_papers() -> list[dict]:
    return [
        {
            "paperId": "seed-paper",
            "title": "Direct experiment",
            "seed_selection": {
                "selected": True,
                "seed_kind": "evidence_seed",
                "selected_slots": [
                    {
                        "sub_hypothesis_id": "SH1",
                        "slot": "candidate",
                        "task_id": "SH1.candidate",
                    }
                ],
            },
        },
        {
            "paperId": "context-paper",
            "title": "Field review",
            "seed_selection": {
                "selected": True,
                "seed_kind": "context_seed",
                "selected_slots": [
                    {
                        "sub_hypothesis_id": "SH1",
                        "slot": "background_framework",
                        "task_id": "SH1.background_framework",
                    }
                ],
            },
        },
    ]


def test_seed_annotations_distinguish_ledger_evidence_from_background() -> None:
    annotations = build_seed_annotation_index(
        _selected_papers(),
        _ledger(),
        project_id="sci_project",
        project_context_fingerprint="context-A",
    )

    direct = annotations["seed-paper"][0]
    background = annotations["context-paper"][0]
    assert direct["association_status"] == LEDGER_CONFIRMED_EVIDENCE
    assert direct["covered_slots"] == ["candidate"]
    assert direct["slot_recovery_task_ids"] == ["SH1.candidate"]
    assert direct["association_stage"] == "SEED_SELECTION"
    assert background["association_status"] == BACKGROUND_CONTEXT
    assert background["covered_slots"] == ["background_framework"]


def test_graph_expansion_keeps_lineage_but_never_inherits_coverage() -> None:
    direct = build_seed_annotation_index(
        _selected_papers()[:1],
        _ledger(),
        project_id="sci_project",
        project_context_fingerprint="context-A",
    )["seed-paper"]

    expanded = build_graph_expansion_annotations(
        direct,
        parent_paper_id="W1",
        root_seed_paper_id="W1",
        lineage_depth=1,
        citation_direction="out",
    )
    assert len(expanded) == 1
    assert expanded[0]["association_status"] == GRAPH_EXPANDED_CANDIDATE
    assert expanded[0]["root_seed_paper_ids"] == ["W1"]
    assert expanded[0]["parent_paper_ids"] == ["W1"]
    assert expanded[0]["covered_slots"] == []
    assert expanded[0]["slot_recovery_task_ids"] == []
    assert expanded[0]["expected_evidence_roles"] == []
    assert expanded[0]["root_evidence_roles"] == ["DIRECT_OBSERVATION"]
    assert merge_node_annotations(expanded, expanded) == expanded


def test_complete_section_assessment_can_promote_an_expanded_candidate() -> None:
    """Promotion must be independently grounded, not inherited from the root."""

    direct = build_seed_annotation_index(
        _selected_papers()[:1],
        _ledger(),
        project_id="sci_project",
        project_context_fingerprint="context-A",
    )["seed-paper"]
    candidate = build_graph_expansion_annotations(
        direct,
        parent_paper_id="W-parent",
        root_seed_paper_id="W-root",
        lineage_depth=2,
        citation_direction="in",
    )
    assessment = {
        "sub_hypothesis_id": "SH1",
        "overall_relation": "direct",
        "semantic_relevance_score": 5,
        "candidate_slot_contributions": [
            {
                "slot_name": "candidate",
                "support_level": "direct",
                "reason": "The independently read paper reports the required result.",
            }
        ],
        "contribution_types": ["DIRECT_EVIDENCE"],
        "claim_limits": ["Only covers the named slot."],
        "evidence_spans": [
            {
                "source": "complete_section_keynote",
                "text": "reports the required result",
            }
        ],
    }

    promoted = build_fulltext_promotion_annotations(
        candidate,
        assessment,
        fulltext_reading_source="complete_section_packet_synthesis",
        promotion_relatedness_score=4.5,
    )

    assert candidate[0]["evidence_use_mode"] == GRAPH_EXPANDED_CANDIDATE_ONLY
    assert promoted[0]["association_stage"] == FULLTEXT_PROMOTION_STAGE
    assert promoted[0]["association_status"] == FULLTEXT_PROMOTED_EXPANDED
    assert promoted[0]["evidence_use_mode"] == DIRECT_LEDGER_EVIDENCE
    assert promoted[0]["covered_slots"] == ["candidate"]
    assert promoted[0]["root_seed_paper_ids"] == ["W-root"]
    assert promoted[0]["parent_paper_ids"] == ["W-parent"]
    assert promoted[0]["fulltext_evidence_spans"] == assessment["evidence_spans"]


def test_openalex_graph_keeps_direct_seed_evidence_and_candidate_only_neighbors(tmp_path) -> None:
    seed = {
        "paperId": "W1",
        "openalex_id": "https://api.openalex.org/W1",
        "title": "Seed",
        "abstract": "A direct experimental paper.",
        "authors": [{"name": "Ada"}],
        "year": 2025,
        "venue": "Journal",
    }
    reference = {
        "paperId": "W2",
        "openalex_id": "https://api.openalex.org/W2",
        "title": "Reference",
        "abstract": "A cited paper.",
        "authors": [{"name": "Grace"}],
        "year": 2024,
        "venue": "Journal",
    }
    citation = {
        "paperId": "W3",
        "openalex_id": "https://api.openalex.org/W3",
        "title": "Citation",
        "abstract": "A citing paper.",
        "authors": [{"name": "Lin"}],
        "year": 2026,
        "venue": "Journal",
    }

    class _OpenAlexGraph:
        def resolve_work_id(self, paper_id):
            return "W1" if paper_id == "seed-paper" else paper_id

        def get_paper_details(self, paper_id):
            return {"W1": seed, "W2": reference, "W3": citation}[paper_id]

        def get_related_papers(self, paper_id, direction, _limit):
            assert paper_id == "W1"
            return [reference] if direction == "out" else [citation]

    collector = object.__new__(WorkCollector)
    collector.config = SimpleNamespace(
        BasicInfo=SimpleNamespace(survey_run_id="graph_audit", base_dir=str(tmp_path)),
        APIInfo=SimpleNamespace(openalex_graph_cache_schema_version=2),
        ModuleInfo=SimpleNamespace(
            WorkCollector=SimpleNamespace(
                related_work_top_k=30,
                reference_graph_depth=1,
                RAG_source_use_embedding_filter=True,
                RAG_source_use_LLM_filter=False,
            )
        ),
    )
    collector.cache_path = str(tmp_path)
    collector.reference_graph_path = str(tmp_path / "reference_graph.pkl")
    collector.reference_graph = None
    collector._openalex_id_aliases = {}
    collector.data_manager = SimpleNamespace(
        openalex_api=_OpenAlexGraph(),
        _resolve_paper_reference_id=lambda paper: paper.get("paperId"),
    )
    collector.logger = _Logger()
    collector.graph_paper_ids = set()

    context = {"input_fingerprint": "context-A"}
    selection = {"selected_papers": _selected_papers()[:1]}
    collector._initialize_sh_graph_provenance(context, selection, _ledger())
    assert Path(tmp_path / "sh_graph_provenance.json").exists()

    assert collector.update_reference_graph(["seed-paper"]) == ["W1"]

    seed_annotations = collector.reference_graph.nodes["W1"]["sh_annotations"]
    reference_annotations = collector.reference_graph.nodes["W2"]["sh_annotations"]
    citation_annotations = collector.reference_graph.nodes["W3"]["sh_annotations"]
    assert seed_annotations[0]["association_status"] == LEDGER_CONFIRMED_EVIDENCE
    assert seed_annotations[0]["covered_slots"] == ["candidate"]
    assert {item["association_status"] for item in reference_annotations} == {
        GRAPH_EXPANDED_CANDIDATE
    }
    assert {item["association_status"] for item in citation_annotations} == {
        GRAPH_EXPANDED_CANDIDATE
    }
    assert all(not item["covered_slots"] for item in reference_annotations + citation_annotations)
    assert collector.reference_graph.edges["W1", "W2"]["sh_expansion_lineage"]
    assert collector.reference_graph.edges["W3", "W1"]["sh_expansion_lineage"]

    artifact = collector.sh_graph_provenance_artifact
    assert artifact["paper_annotations"]["W1"][0]["covered_slots"] == ["candidate"]
    assert len(artifact["graph_expansion_records"]) == 2


def test_local_graph_provenance_retains_root_but_never_upgrades_a_resolved_neighbor(tmp_path) -> None:
    collector = object.__new__(WorkCollector)
    collector.config = SimpleNamespace(
        BasicInfo=SimpleNamespace(survey_run_id="local_graph_audit", base_dir=str(tmp_path))
    )
    collector.logger = _Logger()
    collector.reference_graph = None
    collector._openalex_id_aliases = {}
    collector.data_manager = SimpleNamespace(
        _resolve_paper_reference_id=lambda paper: paper.get("paperId")
    )
    collector._initialize_sh_graph_provenance(
        {"input_fingerprint": "context-A"},
        {"selected_papers": _selected_papers()[:1]},
        _ledger(),
    )
    collector._local_graph_expansion_lineage_by_node_id = {
        "G-local-neighbor": [
            {
                "root_seed_paper_id": "seed-paper",
                "parent_node_id": "G-seed",
                "lineage_depth": 1,
                "lineage_precision": "EXACT_LOCAL_GRAPH_PATH",
            }
        ]
    }

    collector._record_local_graph_expansion_provenance(
        {
            "G-seed": "seed-paper",
            "G-local-neighbor": "W-local-neighbor",
        }
    )

    annotation = collector.sh_graph_provenance_artifact["paper_annotations"][
        "W-local-neighbor"
    ][0]
    assert annotation["association_status"] == GRAPH_EXPANDED_CANDIDATE
    assert annotation["evidence_use_mode"] == GRAPH_EXPANDED_CANDIDATE_ONLY
    assert annotation["admission_status"] == "NOT_EVALUATED_AS_DIRECT_EVIDENCE"
    assert annotation["covered_slots"] == []
    assert annotation["semantic_slot_contributions"] == []
    assert annotation["root_seed_paper_ids"] == ["seed-paper"]
    assert annotation["parent_paper_ids"] == ["seed-paper"]
    assert annotation["graph_lineage_source"] == "local_paper_graph"
    assert annotation["local_graph_parent_node_id"] == "G-seed"
    assert collector.sh_graph_provenance_artifact["graph_expansion_records"][0][
        "graph_lineage_source"
    ] == "local_paper_graph"


def test_project_scoped_graph_overlay_discards_prior_project_annotations(tmp_path) -> None:
    collector = object.__new__(WorkCollector)
    collector.config = SimpleNamespace(
        BasicInfo=SimpleNamespace(survey_run_id="current_run", base_dir=str(tmp_path)),
    )
    collector.logger = _Logger()
    collector.reference_graph = nx.DiGraph()
    collector.reference_graph.add_node(
        "W-stale",
        sh_annotations=[
            {
                "schema_version": "sh_node_annotation_v1",
                "project_id": "sci_previous_run",
                "project_context_fingerprint": "context-A",
                "sub_hypothesis_id": "SH1",
                "association_status": LEDGER_CONFIRMED_EVIDENCE,
            }
        ],
    )
    collector.reference_graph.add_edge(
        "W-stale",
        "W-stale",
        sh_expansion_lineage=[
            {
                "schema_version": "sh_node_annotation_v1",
                "project_id": "sci_previous_run",
                "project_context_fingerprint": "context-A",
            }
        ],
    )

    collector._initialize_sh_graph_provenance(
        {"input_fingerprint": "context-A"},
        {"selected_papers": _selected_papers()[:1]},
        _ledger(),
    )
    collector._reset_sh_graph_overlay_for_active_project()

    assert "sh_annotations" not in collector.reference_graph.nodes["W-stale"]
    assert "sh_expansion_lineage" not in collector.reference_graph.edges["W-stale", "W-stale"]
