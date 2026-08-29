from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from src.agents.survey_agent.modules.work_collector import WorkCollector
from src.pipeline.evidence_coverage_ledger import (
    associate_papers_with_subhypotheses,
    build_evidence_coverage_ledger,
    select_sh_seed_candidates,
)
from src.pipeline.research_identity import build_project_research_context


class _Logger:
    def info(self, *_args, **_kwargs):
        pass

    def warning(self, *_args, **_kwargs):
        pass


class _CapturingLogger(_Logger):
    def __init__(self):
        self.messages: list[str] = []

    def info(self, message, *args, **_kwargs):
        self.messages.append(message % args if args else message)


class _FakeChatAgent:
    def __init__(self, responses: list[str]):
        self.responses = responses
        self.prompts: list[str] = []
        self.calls = 0

    def batch_remote_chat(self, prompts, **_kwargs):
        self.calls += 1
        self.prompts.extend(prompts)
        assert len(self.responses) >= len(prompts)
        return self.responses[: len(prompts)]


def _semantic_response(
    *,
    relation: str = "partial",
    score: int = 4,
    graph_role: str = "exploration_seed",
    span: str = "CYP2D6 phenotype stratifies exposure patterns and symptom benefit",
) -> str:
    return json.dumps(
        {
            "semantic_relevance_score": score,
            "overall_relation": relation,
            "contribution_types": ["PARTIAL_EVIDENCE", "MECHANISTIC_EVIDENCE"],
            "candidate_slot_contributions": [
                {
                    "slot_name": "pharmacogenomic_relation",
                    "support_level": "partial",
                    "reason": "The reported phenotype-response relation is useful but incomplete.",
                }
            ],
            "supported_minimal_claims": [
                "CYP2D6 phenotype is associated with antidepressant exposure patterns and symptom benefit.",
            ],
            "claim_limits": [
                "The supplied abstract does not establish every treatment pathway or population.",
            ],
            "evidence_spans": [
                {
                    "source": "abstract",
                    "text": span,
                    "interpretation": "It provides a pharmacogenomic response relation.",
                }
            ],
            "scope_conflicts": [],
            "explicit_exclusion_matches": [],
            "recommended_graph_role": graph_role,
            "confidence": "high",
            "reason": "The paper contributes a pharmacogenomic response relation without claiming a complete causal chain.",
        }
    )


def _project_relevance_response(score: int) -> str:
    return json.dumps(
        {
            "relevance_score": score,
            "project_fit": "test project fit",
            "matched_anchors": ["pharmacogenomic variation"],
            "violated_exclusions": [],
            "reason": f"test relevance score {score}",
        }
    )


def _context() -> dict:
    return build_project_research_context(
        original_topic="pharmacogenomic tailoring of antidepressant treatment",
        declared_domain="clinical pharmacology",
        objective="Study how pharmacogenomic variation can inform antidepressant treatment.",
        use_llm=False,
    )


def _subhypothesis() -> dict:
    return {
        "sub_hypothesis_id": "SH_PGx",
        "question": "How can pharmacogenomic variation inform antidepressant treatment response?",
        "question_kind": "MECHANISM_EXPLANATION",
        "research_role": "PRIMARY_QUESTION",
        "scientific_scope": {
            "research_object": ["pharmacogenomic variation"],
            "outcome_or_construct": ["antidepressant treatment response"],
        },
        "exclusion_terms": [],
        "retrieval_strategy": "slot_driven_required_slot_recovery",
        "required_slots": ["pharmacogenomic_relation"],
        "slot_recovery_tasks": [
            {
                "task_id": "SH_PGx.pharmacogenomic_relation",
                "slot_name": "pharmacogenomic_relation",
                "slot_definition": {
                    "meaning": "genetic or metabolic factor related to treatment response",
                    "retrieval_concepts": ["pharmacogenetic dosing"],
                },
                "expected_evidence_role": "MECHANISTIC_EVIDENCE",
                "minimum_evidence": "a relevant relation",
                "admission_rule": "can contribute partial evidence",
                "allowed_evidence_scope": {},
                "excluded_evidence_scope": {},
            }
        ],
    }


def _paper(*, abstract: str | None = None) -> dict:
    return {
        "paperId": "W-PGx-1",
        "title": "CYP2D6 phenotypes and individualized antidepressant response",
        "abstract": abstract
        if abstract is not None
        else "CYP2D6 phenotype stratifies exposure patterns and symptom benefit.",
        "venue": "Clinical Pharmacology Journal",
        "retrieval_provenance": [
            {
                "sub_hypothesis_id": "SH_PGx",
                "slot_recovery_task_id": "SH_PGx.pharmacogenomic_relation",
            }
        ],
    }


def _assessment(
    *,
    relation: str,
    contribution_type: str,
    support_level: str,
    graph_role: str = "exploration_seed",
    score: int = 4,
    exclusions: list[str] | None = None,
) -> dict:
    return {
        "assessment_status": "assessed",
        "sub_hypothesis_id": "SH_PGx",
        "semantic_relevance_score": score,
        "overall_relation": relation,
        "contribution_types": [contribution_type],
        "candidate_slot_contributions": [
            {
                "slot_name": "pharmacogenomic_relation",
                "support_level": support_level,
                "reason": "Semantic contribution independently of the literal retrieval phrase.",
            }
        ],
        "evidence_spans": [
            {
                "source": "abstract",
                "text": "CYP2D6 phenotype stratifies exposure patterns and symptom benefit",
                "interpretation": "A narrow pharmacogenomic relation.",
            }
        ],
        "claim_limits": ["Does not establish the full causal chain."],
        "explicit_exclusion_matches": exclusions or [],
        "recommended_graph_role": graph_role,
    }


def _collector(fake_chat: _FakeChatAgent) -> WorkCollector:
    collector = object.__new__(WorkCollector)
    collector.config = SimpleNamespace(
        BasicInfo=SimpleNamespace(debug=False),
        ModuleInfo=SimpleNamespace(
            WorkCollector=SimpleNamespace(
                enable_sh_paper_semantic_assessment=True,
                sh_paper_semantic_assessment_cache_enabled=True,
                use_seed_filter_LLM=False,
                LLM_seed_threshold=4,
                max_seed_paper_num=5,
                subhypothesis_relevance_threshold=3,
                subhypothesis_max_unique_papers=6,
                subhypothesis_max_slots_per_paper=2,
                subhypothesis_max_supplement_rounds=1,
                subhypothesis_no_yield_stop_rounds=1,
                enable_evidence_refinement_retrieval=False,
            )
        ),
    )
    collector.logger = _Logger()
    collector.chat_agent = fake_chat
    collector.sh_paper_semantic_assessment_cache = {}
    return collector


def test_sh_semantic_assessment_parses_grounded_json_and_uses_cache() -> None:
    context = _context()
    fake_chat = _FakeChatAgent([_semantic_response()])
    collector = _collector(fake_chat)

    first = collector.assess_papers_against_subhypotheses(
        [_paper()],
        [_subhypothesis()],
        context,
    )
    second = collector.assess_papers_against_subhypotheses(
        [_paper()],
        [_subhypothesis()],
        context,
    )

    assessment = first[0]["sh_semantic_assessments"][0]
    assert assessment["assessment_status"] == "assessed"
    assert assessment["semantic_relevance_score"] == 4
    assert assessment["overall_relation"] == "partial"
    assert assessment["recommended_graph_role"] == "exploration_seed"
    assert assessment["evidence_spans"] == [
        {
            "source": "abstract",
            "text": "CYP2D6 phenotype stratifies exposure patterns and symptom benefit",
            "interpretation": "It provides a pharmacogenomic response relation.",
        }
    ]
    assert assessment["ungrounded_evidence_span_count"] == 0
    assert fake_chat.calls == 1
    assert second[0]["sh_semantic_assessments"][0]["cache_status"] == "hit"
    assert "does NOT need to cover every slot" in fake_chat.prompts[0]


def test_sh_semantic_assessment_logs_the_candidate_pair_funnel() -> None:
    context = _context()
    fake_chat = _FakeChatAgent([_semantic_response()])
    collector = _collector(fake_chat)
    logger = _CapturingLogger()
    collector.logger = logger

    collector.assess_papers_against_subhypotheses(
        [_paper()],
        [_subhypothesis()],
        context,
    )

    assert logger.messages == [
        "Preparing SH semantic assessment: candidate_papers=1 "
        "candidate_subhypotheses=1 paper_SH_pairs=1 remote_LLM_pairs=1 "
        "cache_hits=0 pairs_by_SH=SH_PGx:1."
    ]


def test_project_screen_rejects_deferred_candidates_when_accepted_pool_is_sufficient() -> None:
    context = _context()
    collector = _collector(
        _FakeChatAgent(
            [
                _project_relevance_response(5),
                _project_relevance_response(4),
                _project_relevance_response(3),
            ]
        )
    )
    logger = _CapturingLogger()
    collector.logger = logger
    papers = [
        {**_paper(), "paperId": "W1", "title": "Accepted one"},
        {**_paper(), "paperId": "W2", "title": "Accepted two"},
        {**_paper(), "paperId": "W3", "title": "Deferred paper"},
    ]

    retained = collector.filter_seed_papers(
        context["original_topic"],
        papers,
        research_context=context,
        retain_all=True,
        retain_deferred_if_accepted_below=2,
    )

    assert [paper["paperId"] for paper in retained] == ["W1", "W2"]
    assert all("project_relevance" in paper for paper in papers)
    assert any(
        "accepted_candidates=2 required_seed_budget=2 "
        "deferred_candidates=1 policy=reject_before_SH_assessment." in message
        for message in logger.messages
    )
    assert any(
        message.startswith("❌ Rejected Deferred SH Candidate: [3] Deferred paper")
        for message in logger.messages
    )


def test_project_screen_retains_deferred_candidates_when_accepted_pool_is_insufficient() -> None:
    context = _context()
    collector = _collector(
        _FakeChatAgent(
            [
                _project_relevance_response(5),
                _project_relevance_response(3),
            ]
        )
    )
    logger = _CapturingLogger()
    collector.logger = logger
    papers = [
        {**_paper(), "paperId": "W1", "title": "Accepted one"},
        {**_paper(), "paperId": "W2", "title": "Deferred paper"},
    ]

    retained = collector.filter_seed_papers(
        context["original_topic"],
        papers,
        research_context=context,
        retain_all=True,
        retain_deferred_if_accepted_below=2,
    )

    assert [paper["paperId"] for paper in retained] == ["W1", "W2"]
    assert any(
        "accepted_candidates=1 required_seed_budget=2 "
        "deferred_candidates=1 policy=retain_for_SH_assessment." in message
        for message in logger.messages
    )
    assert any(
        message.startswith("⏳ Deferred SH Candidate: [3] Deferred paper")
        for message in logger.messages
    )


def test_sh_semantic_parse_failure_keeps_candidate_as_uncertain() -> None:
    context = _context()
    fake_chat = _FakeChatAgent(["not valid JSON"])
    collector = _collector(fake_chat)

    assessed = collector.assess_papers_against_subhypotheses(
        [_paper()],
        [_subhypothesis()],
        context,
    )

    assert len(assessed) == 1
    assessment = assessed[0]["sh_semantic_assessments"][0]
    assert assessment["assessment_status"] == "unavailable"
    assert assessment["overall_relation"] == "uncertain"
    assert assessment["recommended_graph_role"] == "do_not_expand"


def test_missing_abstract_is_assessed_without_being_rejected() -> None:
    context = _context()
    fake_chat = _FakeChatAgent(
        [
            _semantic_response(
                relation="uncertain",
                score=3,
                graph_role="exploration_seed",
                span="",
            )
        ]
    )
    collector = _collector(fake_chat)

    assessed = collector.assess_papers_against_subhypotheses(
        [_paper(abstract="")],
        [_subhypothesis()],
        context,
    )

    assert len(assessed) == 1
    assessment = assessed[0]["sh_semantic_assessments"][0]
    assert assessment["assessment_status"] == "assessed"
    assert assessment["overall_relation"] == "uncertain"
    assert assessment["evidence_spans"] == []
    assert "Abstract: Abstract not available." in fake_chat.prompts[0]


def test_collect_sh_candidates_selects_semantic_synonym_without_literal_slot_match() -> None:
    context = _context()
    fake_chat = _FakeChatAgent([_semantic_response(score=5)])
    collector = _collector(fake_chat)
    subhypothesis = _subhypothesis()
    collector._discover_subhypothesis_candidates = lambda _subhypotheses, **kwargs: (
        [_paper()] if not kwargs.get("retrieval_round") else []
    )
    collector._store_subhypothesis_retrieval_artifact = lambda artifact: setattr(
        collector,
        "subhypothesis_retrieval_artifact",
        dict(artifact),
    )

    selected, selection = collector._collect_sh_seed_candidates(
        context["original_topic"],
        context,
        {"subhypotheses": [subhypothesis]},
        [subhypothesis],
    )

    assert [paper["paperId"] for paper in selected] == ["W-PGx-1"]
    assert selection["exploration_seed_papers"][0]["paperId"] == "W-PGx-1"
    selected_paper = selected[0]
    match = selected_paper["sh_matches"][0]
    assert "relevance_score" not in match
    assert match["slot_assessments"][0]["matched_concepts"] == []
    assert match["semantic_assessment"]["semantic_relevance_score"] == 5
    selection_record = selected_paper["seed_selection"]
    assert selection_record["seed_kind"] == "exploration_seed"
    assert selection_record["graph_expansion_eligible"] is True
    assert selection_record["graph_expansion_mode"] == "bounded_exploration"
    assert selection_record["selection_basis"] == "llm_sh_semantic_assessment"
    assert selection_record["semantic_assessment_ids"] == ["SH_PGx"]


@pytest.mark.parametrize(
    ("relation", "contribution_type", "support_level"),
    [
        ("partial", "PARTIAL_EVIDENCE", "partial"),
        ("indirect", "INDIRECT_EVIDENCE", "indirect"),
        ("counterevidence", "COUNTEREVIDENCE", "partial"),
        ("boundary", "BOUNDARY_EVIDENCE", "partial"),
        ("method", "METHOD_OR_MEASUREMENT", "indirect"),
    ],
)
def test_association_keeps_heuristics_and_classifies_llm_contribution_modes(
    relation: str,
    contribution_type: str,
    support_level: str,
) -> None:
    paper = _paper()
    paper["sh_semantic_assessments"] = [
        _assessment(
            relation=relation,
            contribution_type=contribution_type,
            support_level=support_level,
        )
    ]

    associated = associate_papers_with_subhypotheses(
        [paper],
        [_subhypothesis()],
        project_fingerprint="test-project",
    )

    match = associated[0]["sh_matches"][0]
    slot = match["slot_assessments"][0]
    assert "relevance_score" not in match
    assert slot["heuristic_slot_match_score"] == 1
    assert slot["heuristic_signals"] == ["retrieved_for_slot"]
    assert slot["keyword_inferred_evidence_roles"] == []
    assert slot["llm_semantic_support_level"] == support_level
    assert slot["llm_contribution_types"] == [contribution_type]
    assert slot["admission_status"] == "PARTIAL_OR_INDIRECT_ONLY"
    assert slot["graph_value_status"] == "EXPAND"
    assert slot["coverage_status"] == "PARTIAL_OR_INDIRECT_EVIDENCE"


def test_seed_selection_retains_incomplete_value_as_exploration_and_keeps_holdout() -> None:
    papers = []
    for paper_id, relation, contribution_type, support_level, graph_role in [
        ("W-evidence", "direct", "DIRECT_EVIDENCE", "direct", "evidence_seed"),
        ("W-explore", "partial", "PARTIAL_EVIDENCE", "partial", "exploration_seed"),
        ("W-context", "background", "BACKGROUND_CONTEXT", "none", "context_seed"),
        ("W-holdout", "uncertain", "HYPOTHESIS_GENERATING", "none", "do_not_expand"),
    ]:
        paper = _paper()
        paper["paperId"] = paper_id
        paper["sh_semantic_assessments"] = [
            _assessment(
                relation=relation,
                contribution_type=contribution_type,
                support_level=support_level,
                graph_role=graph_role,
            )
        ]
        papers.append(paper)

    associated = associate_papers_with_subhypotheses(papers, [_subhypothesis()])
    selection = select_sh_seed_candidates(
        associated,
        [_subhypothesis()],
        max_seed_papers=3,
        semantic_relevance_threshold=3,
    )

    assert [paper["paperId"] for paper in selection["evidence_seed_papers"]] == ["W-evidence"]
    assert [paper["paperId"] for paper in selection["exploration_seed_papers"]] == ["W-explore"]
    assert [paper["paperId"] for paper in selection["context_seed_papers"]] == ["W-context"]
    assert [paper["paperId"] for paper in selection["holdout_candidates"]] == ["W-holdout"]
    exploration = selection["exploration_seed_papers"][0]["seed_selection"]
    assert exploration["graph_expansion_eligible"] is True
    assert exploration["graph_expansion_mode"] == "bounded_exploration"
    holdout = selection["holdout_candidates"][0]["seed_selection"]
    assert holdout["graph_expansion_eligible"] is False
    assert holdout["graph_expansion_mode"] == "holdout"


def test_explicit_exclusion_is_rejected_and_cannot_enter_graph() -> None:
    paper = _paper()
    paper["sh_semantic_assessments"] = [
        _assessment(
            relation="partial",
            contribution_type="PARTIAL_EVIDENCE",
            support_level="partial",
            exclusions=["outside the declared clinical scope"],
        )
    ]
    associated = associate_papers_with_subhypotheses([paper], [_subhypothesis()])

    selection = select_sh_seed_candidates(
        associated,
        [_subhypothesis()],
        max_seed_papers=5,
        semantic_relevance_threshold=3,
    )

    assert selection["selected_papers"] == []
    assert [paper["paperId"] for paper in selection["rejected_papers"]] == ["W-PGx-1"]
    decision = selection["rejected_papers"][0]["seed_selection"]
    assert decision["seed_kind"] == "rejected"
    assert decision["decision_reason"] == "explicit_sh_exclusion"
    assert decision["graph_expansion_eligible"] is False
    assert decision["graph_expansion_mode"] == "do_not_expand"


def test_collect_seed_papers_passes_only_expandable_modes_to_graph_roots() -> None:
    context = _context()
    collector = _collector(_FakeChatAgent([]))
    evidence = {
        **_paper(),
        "paperId": "W-evidence",
        "seed_selection": {
            "seed_kind": "evidence_seed",
            "graph_expansion_eligible": True,
            "graph_expansion_mode": "evidence_normal",
        },
    }
    exploration = {
        **_paper(),
        "paperId": "W-explore",
        "seed_selection": {
            "seed_kind": "exploration_seed",
            "graph_expansion_eligible": True,
            "graph_expansion_mode": "bounded_exploration",
        },
    }
    context_seed = {
        **_paper(),
        "paperId": "W-context",
        "seed_selection": {
            "seed_kind": "context_seed",
            "graph_expansion_eligible": False,
            "graph_expansion_mode": "context_only",
        },
    }

    class _OpenAlex:
        @staticmethod
        def resolve_work_id(paper):
            return paper["paperId"]

    class _DataManager:
        def __init__(self):
            self.openalex_api = _OpenAlex()
            self.downloaded = []

        @staticmethod
        def _resolve_paper_reference_id(paper):
            return paper["paperId"]

        def download_and_parse_papers(self, papers, limit):
            self.downloaded.append((list(papers), limit))
            return [paper["paperId"] for paper in papers]

    collector.data_manager = _DataManager()
    collector.expand_in_local_paper_graph = False
    collector.graph_paper_ids = set()
    collector.ignore_paper = set()
    collector._openalex_id_aliases = {}
    collector.context_seed_paper_ids = set()
    collector.get_project_research_context = lambda _topic: context
    collector._build_configured_subhypothesis_plan = lambda _topic, _context: (
        {"subhypotheses": [_subhypothesis()]},
        [_subhypothesis()],
    )
    collector._subhypothesis_retrieval_enabled = lambda: True
    collector._collect_sh_seed_candidates = lambda *_args: (
        [evidence, exploration, context_seed],
        {"context_seed_papers": [context_seed]},
    )

    seed_ids = collector.collect_seed_papers(context["original_topic"])

    assert seed_ids == ["W-evidence", "W-explore", "W-context"]
    assert collector.graph_seed_expansion_modes == {
        "W-evidence": "evidence_normal",
        "W-explore": "bounded_exploration",
    }
    assert collector.context_seed_paper_ids == {"W-context"}


def test_local_graph_expansion_applies_bounded_depth_to_exploration_seeds() -> None:
    collector = _collector(_FakeChatAgent([]))
    collector.config.ModuleInfo.WorkCollector.reference_graph_depth = 3
    collector.config.ModuleInfo.WorkCollector.exploration_seed_reference_graph_depth = 1
    collector.expand_in_local_paper_graph = True
    collector.use_ds_when_graph_fail = False
    collector.graph_seed_expansion_modes = {
        "W-evidence": "evidence_normal",
        "W-explore": "bounded_exploration",
    }

    class _DataManager:
        @staticmethod
        def get_paper_title_abstract(seed_paper):
            return seed_paper, "abstract"

    class _GraphRetriever:
        def __init__(self):
            self.expand_calls = []

        @staticmethod
        def search_by_paper_title(title):
            return [{"id": f"G-{title}"}]

        def expand_nodes_with_lineage(self, node_ids, depth):
            self.expand_calls.append((list(node_ids), depth))
            expanded = [*node_ids, *(f"expanded-{node_id}" for node_id in node_ids)]
            lineage = {
                f"expanded-{node_id}": [
                    {
                        "root_node_id": node_id,
                        "parent_node_id": node_id,
                        "lineage_depth": 1,
                    }
                ]
                for node_id in node_ids
            }
            return expanded, lineage

    collector.data_manager = _DataManager()
    graph_retriever = _GraphRetriever()
    collector.paper_graph_retriever = graph_retriever

    expanded, failed = collector.expand_papers_by_local_paper_graph(
        ["W-evidence", "W-explore"]
    )

    assert failed == []
    assert graph_retriever.expand_calls == [
        (["G-W-evidence"], 3),
        (["G-W-explore"], 1),
    ]
    assert set(expanded) == {"expanded-G-W-evidence", "expanded-G-W-explore"}
    assert collector._local_graph_expansion_lineage_by_node_id == {
        "expanded-G-W-evidence": [
            {
                "root_seed_paper_id": "W-evidence",
                "parent_node_id": "G-W-evidence",
                "lineage_depth": 1,
                "lineage_precision": "EXACT_LOCAL_GRAPH_PATH",
            }
        ],
        "expanded-G-W-explore": [
            {
                "root_seed_paper_id": "W-explore",
                "parent_node_id": "G-W-explore",
                "lineage_depth": 1,
                "lineage_precision": "EXACT_LOCAL_GRAPH_PATH",
            }
        ],
    }


def test_semantic_scope_rejection_is_retained_in_the_coverage_ledger() -> None:
    subhypothesis = _subhypothesis()
    subhypothesis["slot_recovery_tasks"][0]["allowed_evidence_scope"] = {
        "source_types": ["journal article"]
    }
    paper = {
        **_paper(),
        "source_type": "preprint",
        "sh_semantic_assessments": [
            _assessment(
                relation="partial",
                contribution_type="PARTIAL_EVIDENCE",
                support_level="partial",
            )
        ],
    }
    associated = associate_papers_with_subhypotheses(
        [paper],
        [subhypothesis],
    )

    ledger = build_evidence_coverage_ledger(associated, [subhypothesis])
    slot = ledger["subhypotheses"][0]["slot_ledger"]["pharmacogenomic_relation"]

    assert slot["covered_by"] == []
    assert slot["scope_rejections"][0]["coverage_status"] == "OUT_OF_SCOPE"
    assert slot["scope_rejections"][0]["scope_assessment"]["violations"] == [
        "allowed_source_types:preprint"
    ]
