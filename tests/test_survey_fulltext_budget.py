import json
import os
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import networkx as nx


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SURVEY_AGENT_ROOT = os.path.join(PROJECT_ROOT, "src", "agents", "survey_agent")
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, SURVEY_AGENT_ROOT)

# This module is outside the scope of the budget feature and currently has an
# unrelated syntax error in the workspace.  The budget tests only exercise
# WorkCollector's pure selection and scheduling behavior, so use the same
# minimal process-local parser seam as the affected survey tests.
mineru_utils = types.ModuleType("utils.mineru_utils")
mineru_utils.parse_doc = lambda *_args, **_kwargs: None
sys.modules.setdefault("utils.mineru_utils", mineru_utils)

from modules.work_collector import WorkCollector
from src.pipeline.research_identity import relatedness_cache_key


class _Logger:
    def info(self, *_args, **_kwargs):
        pass

    def warning(self, *_args, **_kwargs):
        pass


def _collector(tmp_path: Path, *, budget: int = 2):
    collector = object.__new__(WorkCollector)
    collector.config = SimpleNamespace(
        BasicInfo=SimpleNamespace(),
        ModuleInfo=SimpleNamespace(
            WorkCollector=SimpleNamespace(
                fulltext_download_max_papers=budget,
                log_related_work_num=-1,
            )
        ),
    )
    collector.cache_path = str(tmp_path)
    collector.logger = _Logger()
    collector.relatedness_cache = {}
    collector.graph_paper_ids = set()
    collector.selected_fulltext_paper_ids = set()
    collector.metadata_only_expanded_paper_ids = set()
    collector.fulltext_budget_plan = {}
    collector._last_fulltext_candidate_records = []
    collector._last_graph_expansion_pre_llm_candidate_ids = set()
    return collector


def test_budget_uses_global_max_embedding_score_and_preserves_metadata_status(tmp_path):
    collector = _collector(tmp_path, budget=2)
    context = {"input_fingerprint": "budget-test"}
    saved_papers = {
        "S1": {"W-shared", "W-alpha", "W-beta"},
        "S2": {"W-shared"},
    }
    embedding_scores = {
        ("S1", "W-shared"): 0.51,
        ("S2", "W-shared"): 0.93,
        ("S1", "W-alpha"): 0.80,
        ("S1", "W-beta"): 0.80,
    }
    for seed_id, paper_id, llm_score in (
        ("S1", "W-shared", 4),
        ("S2", "W-shared", 5),
        ("S1", "W-alpha", 5),
        ("S1", "W-beta", 5),
    ):
        collector.relatedness_cache[
            relatedness_cache_key(context, seed_id, paper_id)
        ] = {"relevance_score": llm_score}

    records = collector._build_fulltext_candidate_records(
        saved_papers,
        embedding_scores,
        context,
    )
    selected_ids = collector._select_fulltext_budget_candidates(records)

    # W-shared wins via its strongest relation across all seeds; W-alpha and
    # W-beta tie completely, so the stable paper-id tie-breaker chooses alpha.
    assert selected_ids == ["W-shared", "W-alpha"]
    assert collector.metadata_only_expanded_paper_ids == {"W-beta"}
    assert collector.config.BasicInfo.fulltext_acquisition_by_paper["W-beta"] == {
        "schema_version": "fulltext_acquisition_summary_v1",
        "paper_id": "W-beta",
        "status": "metadata_only_by_fulltext_budget",
        "fulltext_available": False,
        "writing_direct_evidence_allowed": False,
        "evidence_mode": "METADATA_ONLY",
        "budget_rank": 3,
        "budget_limit": 2,
        "reason": "outside_global_fulltext_budget",
        "candidate_count": 0,
        "attempt_count": 0,
        "selected_source": "",
        "provenance_path": "",
    }

    plan_path = Path(collector.fulltext_budget_plan["artifact_path"])
    persisted_plan = json.loads(plan_path.read_text(encoding="utf-8"))
    assert persisted_plan["eligible_after_llm_filter"] == 3
    assert persisted_plan["selected_for_fulltext_count"] == 2
    assert persisted_plan["metadata_only_count"] == 1
    assert [record["paper_id"] for record in persisted_plan["selected_for_fulltext"]] == selected_ids


def test_expansion_downloads_only_globally_ranked_budget_candidates(tmp_path):
    collector = _collector(tmp_path, budget=2)
    collector.expand_in_local_paper_graph = False
    collector.paper_graph_retriever = None
    collector.context_seed_paper_ids = set()
    collector.metadata_only_graph_seed_ids = set()
    collector.reference_graph = nx.DiGraph()
    for paper_id in ("S1", "W-high", "W-middle", "W-low"):
        collector.reference_graph.add_node(paper_id, title=paper_id)

    collector.graph_paper_ids.update(
        {"S1", "W-high", "W-middle", "W-low", "W-llm-rejected"}
    )
    collector._last_graph_expansion_pre_llm_candidate_ids = {
        "W-high",
        "W-middle",
        "W-low",
        "W-llm-rejected",
    }

    class _DataManager:
        def __init__(self):
            self.download_requests = []

        def download_and_parse_papers(self, paper_ids):
            selected = list(paper_ids)
            self.download_requests.append(selected)
            return selected

    collector.data_manager = _DataManager()
    collector.update_reference_graph = lambda _seed_ids: ["S1"]

    records = [
        {
            "paper_id": "W-low",
            "max_embedding_relatedness": 0.60,
            "max_llm_relevance_score": 5,
            "best_seed_id": "S1",
            "matched_seed_ids": ["S1"],
            "seed_embedding_relatedness": {"S1": 0.60},
            "seed_llm_relevance_scores": {"S1": 5},
        },
        {
            "paper_id": "W-middle",
            "max_embedding_relatedness": 0.75,
            "max_llm_relevance_score": 4,
            "best_seed_id": "S1",
            "matched_seed_ids": ["S1"],
            "seed_embedding_relatedness": {"S1": 0.75},
            "seed_llm_relevance_scores": {"S1": 4},
        },
        {
            "paper_id": "W-high",
            "max_embedding_relatedness": 0.90,
            "max_llm_relevance_score": 4,
            "best_seed_id": "S1",
            "matched_seed_ids": ["S1"],
            "seed_embedding_relatedness": {"S1": 0.90},
            "seed_llm_relevance_scores": {"S1": 4},
        },
    ]

    def compute_relatedness(_seed_ids):
        collector._last_fulltext_candidate_records = records
        return ["W-low", "W-middle", "W-high"]

    collector.compute_relatedness_scores_and_filter = compute_relatedness

    result = collector.expand_seed_papers_by_reference_and_citation(["S1"])

    assert collector.data_manager.download_requests == [["W-high", "W-middle"]]
    assert result == ["W-high", "W-middle"]
    assert collector.graph_paper_ids == {"S1", "W-high", "W-middle"}
    assert collector.metadata_only_expanded_paper_ids == {"W-low"}
    assert collector.config.BasicInfo.fulltext_acquisition_by_paper["W-low"]["status"] == (
        "metadata_only_by_fulltext_budget"
    )


def test_local_graph_and_remote_fallback_share_one_global_budget(tmp_path):
    collector = _collector(tmp_path, budget=2)
    collector.expand_in_local_paper_graph = True
    collector.paper_graph_retriever = object()
    collector.use_ds_when_graph_fail = True
    collector.context_seed_paper_ids = set()
    collector.metadata_only_graph_seed_ids = set()
    collector.graph_paper_ids = set()

    local_records = [
        {
            "paper_id": "W-local",
            "max_embedding_relatedness": 0.80,
            "max_llm_relevance_score": 5,
            "best_seed_id": "S-local",
            "matched_seed_ids": ["S-local"],
            "seed_embedding_relatedness": {"S-local": 0.80},
            "seed_llm_relevance_scores": {"S-local": 5},
        },
        {
            "paper_id": "W-local-low",
            "max_embedding_relatedness": 0.60,
            "max_llm_relevance_score": 5,
            "best_seed_id": "S-local",
            "matched_seed_ids": ["S-local"],
            "seed_embedding_relatedness": {"S-local": 0.60},
            "seed_llm_relevance_scores": {"S-local": 5},
        },
    ]
    fallback_records = [
        {
            "paper_id": "W-fallback",
            "max_embedding_relatedness": 0.95,
            "max_llm_relevance_score": 4,
            "best_seed_id": "S-fallback",
            "matched_seed_ids": ["S-fallback"],
            "seed_embedding_relatedness": {"S-fallback": 0.95},
            "seed_llm_relevance_scores": {"S-fallback": 4},
        }
    ]

    def local_filter(_seed_ids):
        collector._last_fulltext_candidate_records = local_records
        collector._last_graph_expansion_pre_llm_candidate_ids = {
            "W-local",
            "W-local-low",
            "W-local-low-embedding",
        }
        collector.graph_paper_ids.update(
            collector._last_graph_expansion_pre_llm_candidate_ids
        )
        return ["W-local", "W-local-low"], ["S-fallback"]

    def remote_filter(_seed_ids):
        collector._last_fulltext_candidate_records = fallback_records
        return ["W-fallback"]

    collector.expand_and_filter_in_local_paper_graph = local_filter
    collector.update_reference_graph = lambda seed_ids: list(seed_ids)
    collector.compute_relatedness_scores_and_filter = remote_filter

    result = collector.expand_seed_papers_by_reference_and_citation(["S-local"])

    assert result == ["W-fallback", "W-local"]
    assert collector.graph_paper_ids == {"W-fallback", "W-local"}
    assert collector.metadata_only_expanded_paper_ids == {"W-local-low"}
    assert collector.fulltext_budget_plan["selected_for_fulltext_count"] == 2
    assert collector.fulltext_budget_plan["metadata_only_count"] == 1
