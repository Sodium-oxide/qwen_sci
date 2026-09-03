import json
import os
import sys
from types import SimpleNamespace

import networkx as nx

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SURVEY_AGENT_ROOT = os.path.join(PROJECT_ROOT, "src", "agents", "survey_agent")
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, SURVEY_AGENT_ROOT)

from src.agents.survey_agent.modules.work_analyzer import WorkAnalyzer
from src.agents.survey_agent.modules.work_collector import WorkCollector
from src.pipeline.sh_graph_provenance import build_graph_expansion_annotations
from utils.utils import get_hash


class _Logger:
    def info(self, *_args, **_kwargs):
        pass

    def warning(self, *_args, **_kwargs):
        pass

    def error(self, *_args, **_kwargs):
        pass


class _PromotionChatAgent:
    def supports_response_format(self, response_format: str) -> bool:
        return response_format == "json_object"

    def batch_remote_chat(self, prompts, **kwargs):
        assert kwargs["response_format"] == "json_object"
        assert len(prompts) == 1
        return [
            json.dumps(
                {
                    "semantic_relevance_score": 5,
                    "overall_relation": "direct",
                    "contribution_types": ["DIRECT_EVIDENCE"],
                    "candidate_slot_contributions": [
                        {
                            "slot_name": "observation",
                            "support_level": "direct",
                            "reason": "reports the observed relation",
                        }
                    ],
                    "supported_minimal_claims": ["The observed relation is reported."],
                    "claim_limits": ["Only the named observation is covered."],
                    "evidence_spans": [
                        {
                            "source": "complete_section_keynote",
                            "text": "reports the observed relation",
                            "interpretation": "direct observation",
                        }
                    ],
                    "scope_conflicts": [],
                    "explicit_exclusion_matches": [],
                    "recommended_graph_role": "evidence_seed",
                    "confidence": "high",
                    "reason": "The complete-section keynote is explicit.",
                }
            )
        ]


def _graph_candidate() -> dict:
    return build_graph_expansion_annotations(
        [
            {
                "schema_version": "sh_node_annotation_v1",
                "project_id": "project-1",
                "project_context_fingerprint": "context-1",
                "sub_hypothesis_id": "SH1",
                "expected_evidence_roles": ["DIRECT_OBSERVATION"],
                "evidence_use_mode": "DIRECT_LEDGER_EVIDENCE",
                "admission_status": "DIRECT_EVIDENCE",
                "graph_value_status": "EXPAND",
            }
        ],
        parent_paper_id="W-parent",
        root_seed_paper_id="W-root",
        lineage_depth=1,
        citation_direction="out",
    )[0]


def _contract() -> dict:
    return {
        "sub_hypothesis_id": "SH1",
        "question": "Does the observation hold?",
        "question_kind": "EMPIRICAL_COVERAGE",
        "research_role": "PRIMARY_QUESTION",
        "scientific_scope": {},
        "exclusion_terms": [],
        "slot_recovery_tasks": [
            {
                "slot_name": "observation",
                "expected_evidence_role": "DIRECT_OBSERVATION",
                "slot_definition": {
                    "meaning": "the requested observation",
                    "retrieval_concepts": ["observation"],
                },
            }
        ],
        "validation": {"valid": True},
    }


def test_read_complete_section_candidate_is_assessed_then_promoted(tmp_path) -> None:
    """The collector creates a separate role only after its own SH assessment."""

    collector = object.__new__(WorkCollector)
    collector.config = SimpleNamespace(
        BasicInfo=SimpleNamespace(base_dir=str(tmp_path)),
        ModuleInfo=SimpleNamespace(
            WorkCollector=SimpleNamespace(
                enable_fulltext_expanded_promotion=True,
                expanded_fulltext_promotion_candidate_multiplier=2,
                expanded_fulltext_promotion_max_candidates_per_sh=40,
                sh_paper_semantic_assessment_cache_enabled=True,
            ),
            SurveyGenerator=SimpleNamespace(writing_max_papers_per_sh=20),
        ),
    )
    collector.logger = _Logger()
    collector.chat_agent = _PromotionChatAgent()
    collector.sh_paper_semantic_assessment_cache = {}
    collector.reference_graph = nx.DiGraph()
    collector.reference_graph.add_node(
        "W-expanded", title="Expanded work", venue="Journal", year=2026
    )
    collector._last_fulltext_candidate_records = [
        {
            "paper_id": "W-expanded",
            "max_llm_relevance_score": 5,
            "max_embedding_relatedness": 0.9,
        }
    ]
    candidate = _graph_candidate()
    collector.sh_graph_provenance_artifact = {
        "schema_version": "sh_graph_provenance_v1",
        "project_id": "project-1",
        "project_context_fingerprint": "context-1",
        "paper_annotations": {"W-expanded": [candidate]},
        "graph_expansion_records": [],
    }
    collector.subhypothesis_retrieval_artifact = {
        "plan": {
            "project_context": {"input_fingerprint": "context-1"},
            "subhypotheses": [_contract()],
        },
        "evidence_coverage_ledger_final": {
            "subhypotheses": [
                {
                    "sub_hypothesis_id": "SH1",
                    "slot_ledger": {
                        "observation": {
                            "covered_by": [],
                            "background_only_by": [],
                        }
                    },
                }
            ]
        },
    }

    result = collector.promote_complete_section_read_graph_candidates(
        {
            "W-expanded": {
                "claims": ["The paper reports the observed relation under test."],
                "results": ["It reports the observed relation."],
            }
        }
    )

    annotations = collector.sh_graph_provenance_artifact["paper_annotations"][
        "W-expanded"
    ]
    promoted = [
        annotation
        for annotation in annotations
        if annotation["association_stage"] == "FULLTEXT_PROMOTION"
    ]
    assert result["assessed_pairs"] == 1
    assert result["promoted_pairs"] == 1
    assert promoted[0]["evidence_use_mode"] == "DIRECT_LEDGER_EVIDENCE"
    assert promoted[0]["covered_slots"] == ["observation"]
    assert candidate["evidence_use_mode"] == "GRAPH_EXPANDED_CANDIDATE_ONLY"
    assert collector.reference_graph.nodes["W-expanded"]["sh_annotations"][-1][
        "association_stage"
    ] == "FULLTEXT_PROMOTION"


def test_upgrade_selector_uses_only_current_fulltext_budget_and_sh_deficit() -> None:
    """Legacy rereads never expand the graph scope beyond the selected corpus."""

    collector = object.__new__(WorkCollector)
    collector.config = SimpleNamespace(
        ModuleInfo=SimpleNamespace(
            WorkCollector=SimpleNamespace(
                enable_fulltext_expanded_promotion=True,
                expanded_fulltext_promotion_candidate_multiplier=2,
                expanded_fulltext_promotion_max_candidates_per_sh=40,
            ),
            SurveyGenerator=SimpleNamespace(writing_max_papers_per_sh=20),
        )
    )
    collector.selected_fulltext_paper_ids = {"W-selected"}
    collector.fulltext_budget_plan = {}
    collector._last_fulltext_candidate_records = [
        {
            "paper_id": "W-selected",
            "max_llm_relevance_score": 5,
            "max_embedding_relatedness": 0.9,
        },
        {
            "paper_id": "W-not-selected",
            "max_llm_relevance_score": 5,
            "max_embedding_relatedness": 0.99,
        },
    ]
    selected_candidate = _graph_candidate()
    unselected_candidate = _graph_candidate()
    collector.sh_graph_provenance_artifact = {
        "schema_version": "sh_graph_provenance_v1",
        "project_id": "project-1",
        "project_context_fingerprint": "context-1",
        "paper_annotations": {
            "W-selected": [selected_candidate],
            "W-not-selected": [unselected_candidate],
        },
        "graph_expansion_records": [],
    }
    collector.subhypothesis_retrieval_artifact = {
        "plan": {"subhypotheses": [_contract()]},
        "evidence_coverage_ledger_final": {
            "subhypotheses": [
                {
                    "sub_hypothesis_id": "SH1",
                    "slot_ledger": {
                        "observation": {"covered_by": [], "background_only_by": []}
                    },
                }
            ]
        },
    }

    result = collector.select_complete_section_upgrade_candidates(
        ["W-selected", "W-not-selected"]
    )

    assert result["selected_fulltext_paper_count"] == 1
    assert result["deficit_by_sh"] == {"SH1": 20}
    assert result["eligible_candidate_pairs"] == 1
    assert result["candidate_pairs"] == [
        {
            "paper_id": "W-selected",
            "canonical_paper_id": "W-selected",
            "sub_hypothesis_id": "SH1",
            "relatedness_score": 5.0,
        }
    ]


def test_upgrade_preparation_rereads_only_legacy_candidates_with_parsed_markdown() -> None:
    """A legacy keynote is force-refreshed without touching complete notes."""

    requested = []
    analyzer = object.__new__(WorkAnalyzer)
    analyzer.config = SimpleNamespace(
        ModuleInfo=SimpleNamespace(WorkAnalyzer=SimpleNamespace(abstract_only_mode=False))
    )
    analyzer.logger = _Logger()
    analyzer.work_collector = SimpleNamespace(
        select_complete_section_upgrade_candidates=lambda papers: requested.append(
            list(papers)
        )
        or {
            "enabled": True,
            "candidate_pairs": [
                {"paper_id": "W-legacy", "canonical_paper_id": "W-legacy"},
                {"paper_id": "W-complete", "canonical_paper_id": "W-complete"},
                {"paper_id": "W-no-markdown", "canonical_paper_id": "W-no-markdown"},
            ],
        },
        data_manager=SimpleNamespace(
            _has_parsed_markdown=lambda paper_id: paper_id != "W-no-markdown"
        ),
    )
    analyzer.paper_keynote_cache = {
        get_hash("W-legacy"): {
            "paper_id": "W-legacy",
            "keynote": {"claims": ["old note"]},
        },
        get_hash("W-complete"): {
            "paper_id": "W-complete",
            "keynote": {"claims": ["new note"]},
            "fulltext_reading_source": "complete_section_packet_synthesis",
        },
    }
    analyzer._paper_keynote_negative_failures = lambda: {}

    result = analyzer.prepare_complete_section_upgrade_candidates(
        ["W-legacy", "W-complete", "W-no-markdown"]
    )

    assert requested == [["W-legacy", "W-complete", "W-no-markdown"]]
    assert result["force_complete_section_paper_ids"] == ["W-legacy"]
    assert result["upgrade_input_skipped"] == {
        "already_complete_section_read": 1,
        "missing_parsed_markdown": 1,
        "explicit_fulltext_bypass": 0,
        "terminal_read_failure": 0,
    }


def test_forced_complete_section_reread_replaces_a_legacy_keynote() -> None:
    """A selected old cache entry must not suppress the complete-section request."""

    requests = []
    analyzer = object.__new__(WorkAnalyzer)
    analyzer.config = SimpleNamespace(
        BasicInfo=SimpleNamespace(debug=False),
        APIInfo=SimpleNamespace(llm_max_context_length=100_000),
        ModuleInfo=SimpleNamespace(
            WorkAnalyzer=SimpleNamespace(
                abstract_only_mode=False,
                paper_reading_max_retry=1,
                use_local_paper_graph_keynotes=False,
                fulltext_section_packing_enabled=True,
                fulltext_section_max_output_tokens=512,
                fulltext_section_batch_worker=1,
                fulltext_section_max_in_flight_tokens=10_000,
                fulltext_section_max_tokens=10_000,
                fulltext_section_prompt_reserve_tokens=100,
                paper_reading_temperature=0.0,
            )
        ),
    )
    analyzer.logger = _Logger()
    analyzer.work_collector = SimpleNamespace(
        get_paper_raw_markdown=lambda _paper_id: "## Complete section\nFresh source text."
    )
    analyzer.chat_agent = SimpleNamespace(
        batch_remote_chat=lambda prompts, **_kwargs: requests.append(list(prompts))
        or [json.dumps({"claims": ["fresh complete-section note"]})]
    )
    analyzer.paper_keynote_cache = {
        get_hash("W-selected"): {
            "paper_id": "W-selected",
            "keynote": {"claims": ["legacy note"]},
        }
    }
    analyzer._section_packet_states = lambda: {}
    analyzer._paper_keynote_negative_failures = lambda: {}
    analyzer._json_object_response_format = lambda: "json_object"
    analyzer._build_safe_fulltext_tasks = lambda **kwargs: (
        SimpleNamespace(status="single_packet"),
        [
            {
                "kind": "paper",
                "paper_id": kwargs["pid"],
                "hash_id": kwargs["hash_id"],
                "packet_index": 0,
                "prompt": "complete-section prompt",
            }
        ],
        None,
    )

    errors = analyzer.read_papers_and_write_keynotes(
        ["W-selected"],
        force_complete_section_paper_ids=["W-selected"],
    )

    refreshed = analyzer.paper_keynote_cache[get_hash("W-selected")]
    assert errors == []
    assert requests == [["complete-section prompt"]]
    assert refreshed["keynote"] == {"claims": ["fresh complete-section note"]}
    assert refreshed["fulltext_reading_source"] == "complete_sections_single_packet"


def test_work_analyzer_excludes_abstract_and_unproven_keynotes_from_promotion() -> None:
    """Only cache entries marked as complete-section reading reach the collector."""

    received = {}
    analyzer = object.__new__(WorkAnalyzer)
    analyzer.logger = _Logger()
    analyzer.work_collector = SimpleNamespace(
        promote_complete_section_read_graph_candidates=lambda notes: received.update(
            notes
        )
        or {"enabled": True, "promoted_pairs": 0}
    )
    analyzer.paper_keynote_failure_records = {
        "W-abstract": {"fallback_status": "abstract_used"}
    }
    analyzer.paper_keynote_cache = {
        get_hash("W-complete"): {
            "paper_id": "W-complete",
            "keynote": {"claims": ["complete"]},
            "fulltext_reading_source": "complete_section_packet_synthesis",
        },
        get_hash("W-abstract"): {
            "paper_id": "W-abstract",
            "keynote": {"claims": ["abstract only"]},
            "fulltext_reading_source": "complete_section_packet_synthesis",
        },
        get_hash("W-legacy"): {
            "paper_id": "W-legacy",
            "keynote": {"claims": ["unknown source"]},
            "fulltext_reading_source": "legacy_or_unknown",
        },
    }

    result = analyzer.promote_complete_section_read_graph_candidates(
        ["W-complete", "W-abstract", "W-legacy", "W-missing"]
    )

    assert received == {"W-complete": {"claims": ["complete"]}}
    assert result["input_complete_section_keynotes"] == 1
    assert result["input_skipped"] == {
        "abstract_fallback": 1,
        "not_complete_section_read": 1,
        "missing_keynote": 1,
    }


def test_cluster_entry_gate_promotes_before_any_cached_or_new_clustering() -> None:
    """All batch/adapter launchers use WorkAnalyzer.cluster_papers()."""

    events = []
    analyzer = object.__new__(WorkAnalyzer)
    analyzer.logger = _Logger()
    analyzer.promote_complete_section_read_graph_candidates = lambda papers: events.append(
        ("promotion", list(papers))
    ) or {"promoted_pairs": 1}
    analyzer._load_cached_clusters = lambda papers: events.append(
        ("cache", list(papers))
    ) or []
    analyzer._project_clusters_with_sh_coverage = lambda clusters: events.append(
        ("projection", list(clusters))
    ) or clusters

    clusters = analyzer.cluster_papers(["W-expanded"])

    assert clusters == []
    assert events == [
        ("promotion", ["W-expanded"]),
        ("cache", ["W-expanded"]),
        ("projection", []),
    ]
