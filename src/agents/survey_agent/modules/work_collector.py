from copy import deepcopy
from typing import Any, Dict, List
import hashlib
import json
from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
import os
import re
import sys
import threading
import time
from pathlib import Path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from utils.api_call import ChatAgent
from utils.config_utils import merge_with_default_survey_config
from utils.rich_logger import get_logger
from modules.paper_graph_retriever import PaperGraphRetriever
from modules.data_manager import DataManager
import pickle
import networkx as nx
from sentence_transformers import SentenceTransformer, util
import torch
import gc
from modules.pe import (
    PAPER_RELATEDNESS_BASED_ON_TITLE_AND_ABSTRACT,
    SEED_PAPER_SELECTION,
    SH_FULLTEXT_EXPANDED_PROMOTION_ASSESSMENT,
    SH_PAPER_SEMANTIC_ASSESSMENT,
)
import diskcache as dc
from utils.utils import get_hash, extract_json
from utils.gpu_utils import load_sentence_transformer_auto
import hydra
from src.pipeline.research_identity import (
    PROJECT_RESEARCH_CONTEXT_SCHEMA_VERSION,
    load_or_build_project_research_context,
    project_research_context_fingerprint,
    relatedness_cache_key,
    relevance_context_payload,
)
from src.pipeline.science_events import emit_science_event
from src.pipeline.retrieval_lanes import (
    build_project_query_lanes,
    build_subhypothesis_retrieval_plan,
)
from src.pipeline.evidence_coverage_ledger import (
    associate_papers_with_subhypotheses,
    build_evidence_coverage_ledger,
    ensure_deterministic_project_relevance,
    select_sh_seed_candidates,
)
from src.pipeline.sh_graph_provenance import (
    FULLTEXT_PROMOTION_STAGE,
    FULLTEXT_PROMOTED_EXPANDED,
    SH_GRAPH_PROVENANCE_SCHEMA_VERSION,
    SH_NODE_ANNOTATION_SCHEMA_VERSION,
    append_annotation_index,
    build_fulltext_promotion_annotations,
    build_graph_expansion_annotations,
    build_seed_annotation_index,
    current_project_node_annotations,
    merge_node_annotations,
    paper_identity,
)
from src.pipeline.paper_identity import canonical_paper_id
from src.pipeline.subhypothesis_decomposition import (
    SUBHYPOTHESIS_DECOMPOSITION_MAX_COUNT,
    SUBHYPOTHESIS_DECOMPOSITION_MIN_COUNT,
    SUBHYPOTHESIS_DECOMPOSITION_MODEL,
    SUBHYPOTHESIS_DECOMPOSITION_PROVIDER,
    load_or_build_subhypothesis_decomposition,
    subhypothesis_decomposition_fingerprint,
)
from src.pipeline.multimodal_evidence.contract import validate_multimodal_evidence
from src.pipeline.multimodal_evidence.data_sh_compiler import (
    compile_data_anchored_subhypotheses,
)
from src.pipeline.multimodal_evidence.retrieval_profile import (
    RETRIEVAL_PROFILE_VERSION,
)

class WorkCollector:
    _OPENALEX_GRAPH_PROVIDER = "openalex"
    _SH_RETRIEVAL_LANE_CACHE_SCHEMA_VERSION = "sh_retrieval_lane_cache_v2"
    _FULLTEXT_BUDGET_PLAN_SCHEMA_VERSION = "fulltext_budget_plan_v1"

    def __init__(self, config, ignore_paper:List[str] = None, paper_graph_retriever = None, data_manager = None):
        self.config = config
        self.chat_agent = ChatAgent(config)
        self.logger = get_logger("WorkCollector")
        self.cache_path = self.config.BasicInfo.cache_path
        self.ignore_paper = set(ignore_paper) if ignore_paper is not None else set()
        self._openalex_id_aliases = {}
        self.project_research_context = None
        self._project_created_event_emitted = False
        self._subhypothesis_declared_event_keys = set()
        self.subhypothesis_retrieval_artifact = {}
        self.subhypothesis_decomposition_artifact = {}
        self.sh_graph_provenance_artifact = {}
        self._subhypothesis_decomposition_agent = None
        self.data_anchored_subhypothesis_artifact = {}
        self.context_seed_paper_ids = set()
        self.graph_seed_expansion_modes = {}
        # Roots in this set were semantically admitted for graph exploration,
        # but their PDF could not be acquired.  They remain metadata graph
        # roots; they are intentionally excluded from deep-reading inputs.
        self.metadata_only_graph_seed_ids = set()

        # 初始化 DataManager（处理下载、解析、缓存等）
        self.data_manager = DataManager(config) if data_manager is None else data_manager
        self.paper_abstract_cache = self.data_manager.paper_abstract_cache

        ## local paper graph parameter
        self.expand_in_local_paper_graph = self.config.ModuleInfo.WorkCollector.expand_in_local_paper_graph
        self.advanced_filter_in_local_paper_graph_expansion = self.config.ModuleInfo.WorkCollector.advanced_filter_in_local_paper_graph_expansion
        self.use_ds_when_graph_fail = self.config.ModuleInfo.WorkCollector.use_ds_when_graph_fail
        if not self.expand_in_local_paper_graph:
            self.paper_graph_retriever = paper_graph_retriever
        else:
            self.paper_graph_retriever = PaperGraphRetriever(config)

        os.makedirs(self.cache_path, exist_ok=True)
        self.reference_graph_path = os.path.join(self.cache_path, "reference_graph.pkl")
        self.reference_graph = self._load_openalex_reference_graph()

        # cache for paper relatedness
        self.relatedness_cache = dc.Cache(
            os.path.join(self.cache_path, "workcollector_relatedness_cache")
        )
        # Project/paper relatedness and paper/SH semantic assessment have
        # different inputs and schemas. Keep their persistent caches separate.
        self.sh_paper_semantic_assessment_cache = dc.Cache(
            os.path.join(self.cache_path, "sh_paper_semantic_assessment_cache")
        )
        # Cache provider-returned SH lane candidates separately from the
        # semantic assessment and seed selection.  A cache hit only avoids a
        # repeated network query; it never reuses a previous LLM judgement or
        # seed tier.
        try:
            self.sh_retrieval_lane_cache = dc.Cache(
                os.path.join(self.cache_path, "sh_retrieval_lane_cache")
            )
        except Exception as exc:
            self.sh_retrieval_lane_cache = None
            self.logger.warning("SH retrieval lane cache is unavailable: %s", exc)
        self._sh_retrieval_cache_lock_guard = threading.Lock()
        self._sh_retrieval_cache_locks: dict[str, threading.Lock] = {}
        self._sh_retrieval_cache_refreshed_keys: set[str] = set()
        if (
            self.sh_retrieval_lane_cache is not None
            and self._sh_retrieval_cache_invalidation_requested()
        ):
            self.sh_retrieval_lane_cache.clear()
            self.logger.info(
                "Cleared SH retrieval lane cache because invalidate_sh_retrieval_cache=true."
            )

        # embedding model for semantic similarity (lazy loading) - 委托给 data_manager
        self._embedding_model = None
        self._model_device = None
        self.graph_paper_ids = set()
        # Graph expansion can retain many metadata records, while the active
        # full-text corpus is deliberately bounded before PDF acquisition and
        # deep reading.  Keep these sets separate so a metadata-only paper is
        # never mistaken for a failed full-text download.
        self.selected_fulltext_paper_ids = set()
        self.metadata_only_expanded_paper_ids = set()
        self.fulltext_budget_plan = {}
        self._last_fulltext_candidate_records = []
        self._last_graph_expansion_pre_llm_candidate_ids = set()

    def _basic_info_value(self, key: str, default=""):
        basic_info = getattr(self.config, "BasicInfo", None)
        return getattr(basic_info, key, default)

    def _work_collector_setting(self, key: str, default):
        module_info = getattr(getattr(self, "config", None), "ModuleInfo", None)
        work_collector = getattr(module_info, "WorkCollector", None)
        return getattr(work_collector, key, default)

    def _fulltext_download_budget_limit(self) -> int:
        """Return a safe run-level cap for graph-expanded full-text papers."""

        configured = self._work_collector_setting(
            "fulltext_download_max_papers",
            70,
        )
        try:
            return max(0, int(configured))
        except (TypeError, ValueError):
            logger = getattr(self, "logger", None)
            if logger is not None:
                logger.warning(
                    "Invalid fulltext_download_max_papers=%r; using the default 70.",
                    configured,
                )
            return 70

    @staticmethod
    def _safe_score(value: Any) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    def _build_fulltext_candidate_records(
        self,
        saved_papers: Mapping[str, set[str]],
        embedding_scores: Mapping[tuple[str, str], float],
        research_context: Mapping[str, Any],
    ) -> list[Dict[str, Any]]:
        """Aggregate retained seed/paper pairs into globally rankable papers.

        ``related_work_top_k`` is intentionally a per-seed pre-filter.  This
        method restores the pair scores that would otherwise be lost in sets
        and produces one deterministic record per paper for the later global
        full-text budget decision.
        """

        cache = getattr(self, "relatedness_cache", {})
        by_paper: Dict[str, Dict[str, Dict[str, float]]] = {}
        for seed_pid, related_paper_ids in saved_papers.items():
            for related_pid in related_paper_ids:
                paper_id = str(related_pid or "").strip()
                seed_id = str(seed_pid or "").strip()
                if not paper_id or not seed_id:
                    continue
                relatedness_info = cache.get(
                    relatedness_cache_key(research_context, seed_id, paper_id),
                    {},
                )
                relatedness_info = (
                    relatedness_info
                    if isinstance(relatedness_info, Mapping)
                    else {}
                )
                pair = by_paper.setdefault(paper_id, {}).setdefault(seed_id, {})
                pair["embedding"] = max(
                    self._safe_score(pair.get("embedding")),
                    self._safe_score(embedding_scores.get((seed_id, paper_id))),
                )
                pair["llm"] = max(
                    self._safe_score(pair.get("llm")),
                    self._safe_score(relatedness_info.get("relevance_score")),
                )

        records = []
        for paper_id, pair_scores in by_paper.items():
            seed_embedding_scores = {
                seed_id: self._safe_score(values.get("embedding"))
                for seed_id, values in pair_scores.items()
            }
            seed_llm_scores = {
                seed_id: self._safe_score(values.get("llm"))
                for seed_id, values in pair_scores.items()
            }
            max_embedding_score = max(seed_embedding_scores.values(), default=0.0)
            best_seed_id = min(
                (
                    seed_id
                    for seed_id, score in seed_embedding_scores.items()
                    if score == max_embedding_score
                ),
                default="",
            )
            records.append(
                {
                    "paper_id": paper_id,
                    "max_embedding_relatedness": max_embedding_score,
                    "max_llm_relevance_score": max(seed_llm_scores.values(), default=0.0),
                    "best_seed_id": best_seed_id,
                    "matched_seed_ids": sorted(seed_embedding_scores),
                    # Keep per-seed data in the budget artifact so equal-score
                    # choices remain inspectable and mergeable across fallback
                    # graph routes.
                    "seed_embedding_relatedness": seed_embedding_scores,
                    "seed_llm_relevance_scores": seed_llm_scores,
                }
            )
        return records

    def _merge_fulltext_candidate_records(
        self,
        *candidate_record_groups: Sequence[Mapping[str, Any]],
    ) -> list[Dict[str, Any]]:
        """Merge local-graph and fallback candidates before one global cap."""

        pair_scores: Dict[str, Dict[str, Dict[str, float]]] = {}
        for group in candidate_record_groups:
            for raw_record in group or []:
                record = raw_record if isinstance(raw_record, Mapping) else {}
                paper_id = str(record.get("paper_id") or "").strip()
                if not paper_id:
                    continue
                embedding_by_seed = record.get("seed_embedding_relatedness")
                llm_by_seed = record.get("seed_llm_relevance_scores")
                embedding_by_seed = (
                    embedding_by_seed if isinstance(embedding_by_seed, Mapping) else {}
                )
                llm_by_seed = llm_by_seed if isinstance(llm_by_seed, Mapping) else {}
                seed_ids = set(embedding_by_seed) | set(llm_by_seed)
                if not seed_ids:
                    seed_ids = set(record.get("matched_seed_ids") or [])
                if not seed_ids:
                    # Advanced filtering can be deliberately disabled.  Retain
                    # that paper as a deterministic unscored candidate instead
                    # of silently dropping it from the full-text budget.
                    pair = pair_scores.setdefault(paper_id, {}).setdefault("", {})
                    pair["embedding"] = max(
                        self._safe_score(pair.get("embedding")),
                        self._safe_score(record.get("max_embedding_relatedness")),
                    )
                    pair["llm"] = max(
                        self._safe_score(pair.get("llm")),
                        self._safe_score(record.get("max_llm_relevance_score")),
                    )
                    continue
                for raw_seed_id in seed_ids:
                    seed_id = str(raw_seed_id or "").strip()
                    if not seed_id:
                        continue
                    pair = pair_scores.setdefault(paper_id, {}).setdefault(seed_id, {})
                    pair["embedding"] = max(
                        self._safe_score(pair.get("embedding")),
                        self._safe_score(embedding_by_seed.get(seed_id)),
                    )
                    pair["llm"] = max(
                        self._safe_score(pair.get("llm")),
                        self._safe_score(llm_by_seed.get(seed_id)),
                    )

        merged = []
        for paper_id, seed_values in pair_scores.items():
            embedding_by_seed = {
                seed_id: self._safe_score(values.get("embedding"))
                for seed_id, values in seed_values.items()
            }
            llm_by_seed = {
                seed_id: self._safe_score(values.get("llm"))
                for seed_id, values in seed_values.items()
            }
            max_embedding_score = max(embedding_by_seed.values(), default=0.0)
            best_seed_id = min(
                (
                    seed_id
                    for seed_id, score in embedding_by_seed.items()
                    if score == max_embedding_score
                ),
                default="",
            )
            merged.append(
                {
                    "paper_id": paper_id,
                    "max_embedding_relatedness": max_embedding_score,
                    "max_llm_relevance_score": max(llm_by_seed.values(), default=0.0),
                    "best_seed_id": best_seed_id,
                    "matched_seed_ids": sorted(
                        seed_id for seed_id in embedding_by_seed if seed_id
                    ),
                    "seed_embedding_relatedness": embedding_by_seed,
                    "seed_llm_relevance_scores": llm_by_seed,
                }
            )
        return merged

    def _write_fulltext_budget_plan(self, plan: Mapping[str, Any]) -> str:
        """Persist the active run's selection without deleting cached PDFs."""

        cache_path = str(getattr(self, "cache_path", "") or "").strip()
        if not cache_path:
            return ""
        target = Path(cache_path) / "fulltext_budget_plan.json"
        temporary = target.with_suffix(".json.tmp")
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary.write_text(
                json.dumps(dict(plan), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            os.replace(temporary, target)
            return str(target)
        except OSError as exc:
            logger = getattr(self, "logger", None)
            if logger is not None:
                logger.warning("Could not persist full-text budget plan: %s", exc)
            try:
                if temporary.exists():
                    temporary.unlink()
            except OSError:
                pass
            return ""

    @staticmethod
    def _metadata_only_budget_summary(record: Mapping[str, Any], limit: int) -> Dict[str, Any]:
        """Represent an intentional budget exclusion, never an acquisition error."""

        return {
            "schema_version": "fulltext_acquisition_summary_v1",
            "paper_id": str(record.get("paper_id") or ""),
            "status": "metadata_only_by_fulltext_budget",
            "fulltext_available": False,
            "writing_direct_evidence_allowed": False,
            "evidence_mode": "METADATA_ONLY",
            "budget_rank": int(record.get("rank") or 0),
            "budget_limit": int(limit),
            "reason": "outside_global_fulltext_budget",
            "candidate_count": 0,
            "attempt_count": 0,
            "selected_source": "",
            "provenance_path": "",
        }

    def _publish_fulltext_budget_plan(self, plan: Mapping[str, Any]) -> None:
        """Expose budget status to graph/evidence artifacts without parsing metadata-only papers."""

        selected_ids = {
            str(record.get("paper_id") or "").strip()
            for record in plan.get("selected_for_fulltext", [])
            if isinstance(record, Mapping)
        }
        selected_ids.discard("")
        metadata_records = [
            record
            for record in plan.get("metadata_only", [])
            if isinstance(record, Mapping)
        ]
        metadata_ids = {
            str(record.get("paper_id") or "").strip()
            for record in metadata_records
        }
        metadata_ids.discard("")
        self.selected_fulltext_paper_ids = selected_ids
        self.metadata_only_expanded_paper_ids = metadata_ids
        self.fulltext_budget_plan = dict(plan)
        # `graph_paper_ids` feeds both the abstract database and compatibility
        # writing paths.  Preserve every graph node and plan record as
        # metadata, but keep none of this expansion's non-selected candidates
        # in that *active* corpus: this includes both budget-excluded papers
        # and papers rejected by the later LLM filter.
        active_graph_paper_ids = getattr(self, "graph_paper_ids", None)
        if isinstance(active_graph_paper_ids, set):
            pre_llm_candidate_ids = set(
                getattr(self, "_last_graph_expansion_pre_llm_candidate_ids", set())
                or set()
            )
            active_graph_paper_ids.difference_update(
                pre_llm_candidate_ids.difference(selected_ids)
            )
            active_graph_paper_ids.difference_update(metadata_ids)
            active_graph_paper_ids.update(selected_ids)

        basic_info = getattr(getattr(self, "config", None), "BasicInfo", None)
        if basic_info is None:
            return
        acquisition_by_paper = getattr(basic_info, "fulltext_acquisition_by_paper", {})
        acquisition_by_paper = (
            dict(acquisition_by_paper)
            if isinstance(acquisition_by_paper, Mapping)
            else {}
        )
        for paper_id in selected_ids:
            current = acquisition_by_paper.get(paper_id)
            if (
                isinstance(current, Mapping)
                and current.get("status") == "metadata_only_by_fulltext_budget"
            ):
                acquisition_by_paper.pop(paper_id, None)
        for record in metadata_records:
            paper_id = str(record.get("paper_id") or "").strip()
            if paper_id:
                acquisition_by_paper[paper_id] = self._metadata_only_budget_summary(
                    record,
                    int(plan.get("fulltext_budget") or 0),
                )
        try:
            basic_info.fulltext_acquisition_by_paper = acquisition_by_paper
            basic_info.fulltext_budget_plan = dict(plan)
        except Exception:
            pass

        for artifact_name in ("subhypothesis_retrieval", "sh_graph_provenance"):
            artifact = getattr(basic_info, artifact_name, None)
            if not isinstance(artifact, dict):
                continue
            artifact["fulltext_budget_plan"] = dict(plan)
            artifact.setdefault("fulltext_acquisition_by_paper", {}).update(
                {
                    paper_id: acquisition_by_paper[paper_id]
                    for paper_id in metadata_ids
                    if paper_id in acquisition_by_paper
                }
            )

    def _select_fulltext_budget_candidates(
        self,
        candidate_records: Sequence[Mapping[str, Any]],
    ) -> list[str]:
        """Apply one deterministic, global full-text budget after LLM filtering."""

        merged_records = self._merge_fulltext_candidate_records(candidate_records)
        ranked_records = sorted(
            merged_records,
            key=lambda record: (
                -self._safe_score(record.get("max_embedding_relatedness")),
                -self._safe_score(record.get("max_llm_relevance_score")),
                -len(record.get("matched_seed_ids") or []),
                str(record.get("paper_id") or ""),
            ),
        )
        for rank, record in enumerate(ranked_records, start=1):
            record["rank"] = rank

        configured_limit = self._fulltext_download_budget_limit()
        selected_count = min(
            configured_limit,
            len(ranked_records),
        )
        selected_records = ranked_records[:selected_count]
        metadata_records = ranked_records[selected_count:]
        plan = {
            "schema_version": self._FULLTEXT_BUDGET_PLAN_SCHEMA_VERSION,
            "fulltext_budget": configured_limit,
            "rank_metric": "max_embedding_relatedness",
            "eligible_after_llm_filter": len(ranked_records),
            "selected_for_fulltext_count": len(selected_records),
            "metadata_only_count": len(metadata_records),
            "selected_for_fulltext": selected_records,
            "metadata_only": metadata_records,
        }
        plan["artifact_path"] = self._write_fulltext_budget_plan(plan)
        self._publish_fulltext_budget_plan(plan)

        logger = getattr(self, "logger", None)
        if logger is not None:
            logger.info(
                "Global full-text budget selected %s/%s papers for PDF download and parsing; "
                "%s remain metadata-only (limit=%s, metric=max_embedding_relatedness).",
                len(selected_records),
                len(ranked_records),
                len(metadata_records),
                configured_limit,
            )
        return [str(record["paper_id"]) for record in selected_records]

    def _sh_retrieval_cache_enabled(self) -> bool:
        configured = self._work_collector_setting("sh_retrieval_cache_enabled", True)
        return str(configured).strip().casefold() not in {"0", "false", "no", "off"}

    def _sh_retrieval_cache_refresh_requested(self) -> bool:
        configured = self._work_collector_setting("refresh_sh_retrieval_cache", False)
        return str(configured).strip().casefold() in {"1", "true", "yes", "on"}

    def _sh_retrieval_cache_invalidation_requested(self) -> bool:
        configured = self._work_collector_setting("invalidate_sh_retrieval_cache", False)
        return str(configured).strip().casefold() in {"1", "true", "yes", "on"}

    def _sh_retrieval_lane_cache(self):
        """Return the persistent cache, including for lightweight test collectors."""

        if hasattr(self, "sh_retrieval_lane_cache"):
            return getattr(self, "sh_retrieval_lane_cache")
        cache_path = str(getattr(self, "cache_path", "") or "").strip()
        if not cache_path:
            return None
        try:
            os.makedirs(cache_path, exist_ok=True)
            cache = dc.Cache(os.path.join(cache_path, "sh_retrieval_lane_cache"))
        except Exception as exc:
            logger = getattr(self, "logger", None)
            if logger is not None:
                logger.warning("SH retrieval lane cache is unavailable: %s", exc)
            return None
        self.sh_retrieval_lane_cache = cache
        return cache

    @staticmethod
    def _sh_retrieval_cache_json_value(value: Any) -> Any:
        """Convert lane settings into a stable, secret-free JSON cache payload."""

        if isinstance(value, Mapping):
            return {
                str(key): WorkCollector._sh_retrieval_cache_json_value(item)
                for key, item in sorted(value.items(), key=lambda item: str(item[0]))
            }
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
            return [WorkCollector._sh_retrieval_cache_json_value(item) for item in value]
        if value is None or isinstance(value, (bool, int, float, str)):
            return value
        return str(value)

    def _sh_retrieval_lane_cache_payload(self, lane: Mapping[str, Any]) -> dict[str, Any]:
        """Describe the external request, rather than the SH judgement using it."""

        provider = str(lane.get("provider") or "").strip().casefold()
        configured_limit = lane.get("per_page") or lane.get("result_limit")
        if configured_limit is None and provider == "openalex":
            configured_limit = getattr(
                getattr(getattr(self, "data_manager", None), "openalex_api", None),
                "default_per_page",
                None,
            )

        return {
            "schema_version": self._SH_RETRIEVAL_LANE_CACHE_SCHEMA_VERSION,
            "query_compiler_version": RETRIEVAL_PROFILE_VERSION,
            "provider": provider,
            "query": self._lane_query_for_log(lane),
            "provider_filter": self._sh_retrieval_cache_json_value(
                lane.get("provider_filter") if isinstance(lane.get("provider_filter"), Mapping) else {}
            ),
            "hard_filter_applied": bool(lane.get("hard_filter_applied")),
            "sort": self._sh_retrieval_cache_json_value(lane.get("sort") or {}),
            "result_limit": self._sh_retrieval_cache_json_value(configured_limit),
            "semantic_scholar_fields": str(lane.get("semantic_scholar_fields") or "").strip(),
        }

    def _sh_retrieval_lane_cache_key(self, lane: Mapping[str, Any]) -> str:
        encoded = json.dumps(
            self._sh_retrieval_lane_cache_payload(lane),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return "sh_retrieval_lane:" + hashlib.sha256(encoded).hexdigest()

    def _sh_retrieval_cache_lock(self, cache_key: str) -> threading.Lock:
        guard = getattr(self, "_sh_retrieval_cache_lock_guard", None)
        if guard is None:
            guard = threading.Lock()
            self._sh_retrieval_cache_lock_guard = guard
        with guard:
            locks = getattr(self, "_sh_retrieval_cache_locks", None)
            if not isinstance(locks, dict):
                locks = {}
                self._sh_retrieval_cache_locks = locks
            lock = locks.get(cache_key)
            if lock is None:
                lock = threading.Lock()
                locks[cache_key] = lock
            return lock

    def _sh_retrieval_cache_refresh_completed(self, cache_key: str) -> bool:
        completed_keys = getattr(self, "_sh_retrieval_cache_refreshed_keys", None)
        return isinstance(completed_keys, set) and cache_key in completed_keys

    def _mark_sh_retrieval_cache_refresh_completed(self, cache_key: str) -> None:
        completed_keys = getattr(self, "_sh_retrieval_cache_refreshed_keys", None)
        if not isinstance(completed_keys, set):
            completed_keys = set()
            self._sh_retrieval_cache_refreshed_keys = completed_keys
        completed_keys.add(cache_key)

    def _sh_retrieval_cache_ttl_seconds(self, papers: Sequence[Mapping[str, Any]]) -> int:
        setting = (
            "sh_retrieval_cache_success_ttl_seconds"
            if papers
            else "sh_retrieval_cache_empty_ttl_seconds"
        )
        default = 604800 if papers else 21600
        try:
            return max(0, int(self._work_collector_setting(setting, default) or 0))
        except (TypeError, ValueError):
            return default

    def _sh_retrieval_cache_get(self, cache, cache_key: str):
        try:
            return cache.get(cache_key, default=None)
        except Exception as exc:
            self.logger.warning("SH retrieval lane cache read failed; querying provider: %s", exc)
            return None

    def _sh_retrieval_cache_set(self, cache, cache_key: str, entry: Mapping[str, Any], *, ttl_seconds: int) -> bool:
        try:
            cache.set(cache_key, dict(entry), expire=ttl_seconds)
        except Exception as exc:
            self.logger.warning("SH retrieval lane cache write failed; retaining live provider result: %s", exc)
            return False
        return True

    @staticmethod
    def _sh_retrieval_cache_timestamp(epoch: Any) -> str:
        try:
            return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(float(epoch)))
        except (TypeError, ValueError, OverflowError):
            return ""

    def _configured_subhypotheses(self) -> list[Dict]:
        configured = self._basic_info_value("subhypotheses", [])
        if isinstance(configured, Mapping):
            configured = [configured]
        if not isinstance(configured, Sequence) or isinstance(configured, (str, bytes)):
            return []
        return [dict(item) for item in configured if isinstance(item, Mapping)]

    def _subhypothesis_retrieval_enabled(self) -> bool:
        configured = self._work_collector_setting("enable_subhypothesis_retrieval", True)
        return str(configured).strip().lower() not in {"0", "false", "no", "off"}

    def _arxiv_discovery_enabled(self) -> bool:
        configured = self._work_collector_setting("enable_arxiv_discovery", False)
        return str(configured).strip().lower() not in {"0", "false", "no", "off"}

    def _discovery_lane_enabled(self, lane: Mapping[str, Any]) -> bool:
        """Return whether a provider lane is enabled for active discovery."""

        provider = str(lane.get("provider") or "").strip().lower()
        return provider != "arxiv" or self._arxiv_discovery_enabled()

    def _automatic_subhypothesis_decomposition_enabled(self) -> bool:
        if getattr(self.config, "BasicInfo", None) is None:
            return False
        configured = self._work_collector_setting(
            "auto_decompose_subhypotheses",
            True,
        )
        return str(configured).strip().lower() not in {"0", "false", "no", "off"}

    def _store_subhypothesis_decomposition_artifact(
        self,
        artifact: Mapping[str, Any],
    ) -> None:
        self.subhypothesis_decomposition_artifact = dict(artifact)
        try:
            self.config.BasicInfo.subhypothesis_decomposition = (
                self.subhypothesis_decomposition_artifact
            )
        except Exception:
            pass

    def _subhypothesis_decomposition_cache_path(
        self,
        research_context: Mapping[str, Any],
        *,
        provider: str,
        model: str,
        reserved_subhypotheses: Sequence[Mapping[str, Any]] | None = None,
        observation_projection: Mapping[str, Any] | None = None,
    ) -> str:
        configured_path = str(
            self._basic_info_value("subhypothesis_decomposition_path", "") or ""
        ).strip()
        if configured_path:
            return configured_path
        fingerprint = subhypothesis_decomposition_fingerprint(
            research_context,
            provider=provider,
            model=model,
            reserved_subhypotheses=reserved_subhypotheses,
            observation_projection=observation_projection,
        )
        return os.path.join(
            self.cache_path,
            "subhypothesis_decompositions",
            f"{fingerprint}.json",
        )

    def _decomposition_chat_agent(self) -> ChatAgent:
        agent = getattr(self, "_subhypothesis_decomposition_agent", None)
        if agent is None:
            agent = ChatAgent(
                self.config,
                provider_override=SUBHYPOTHESIS_DECOMPOSITION_PROVIDER,
                model_override=SUBHYPOTHESIS_DECOMPOSITION_MODEL,
            )
            self._subhypothesis_decomposition_agent = agent
        return agent

    def _auto_decompose_subhypotheses(
        self,
        research_context: Mapping[str, Any],
        *,
        reserved_subhypotheses: Sequence[Mapping[str, Any]] | None = None,
        observation_projection: Mapping[str, Any] | None = None,
    ) -> list[Dict]:
        provider = str(
            self._work_collector_setting(
                "subhypothesis_decomposition_provider",
                SUBHYPOTHESIS_DECOMPOSITION_PROVIDER,
            )
            or ""
        ).strip()
        model = str(
            self._work_collector_setting(
                "subhypothesis_decomposition_model",
                SUBHYPOTHESIS_DECOMPOSITION_MODEL,
            )
            or ""
        ).strip()
        if (
            provider != SUBHYPOTHESIS_DECOMPOSITION_PROVIDER
            or model != SUBHYPOTHESIS_DECOMPOSITION_MODEL
        ):
            raise ValueError(
                "Automatic SH decomposition requires "
                f"{SUBHYPOTHESIS_DECOMPOSITION_PROVIDER}/"
                f"{SUBHYPOTHESIS_DECOMPOSITION_MODEL}; received {provider or '<missing>'}/"
                f"{model or '<missing>'}."
            )
        configured_minimum = int(
            self._work_collector_setting(
                "subhypothesis_decomposition_min_count",
                SUBHYPOTHESIS_DECOMPOSITION_MIN_COUNT,
            )
        )
        configured_maximum = int(
            self._work_collector_setting(
                "subhypothesis_decomposition_max_count",
                SUBHYPOTHESIS_DECOMPOSITION_MAX_COUNT,
            )
        )
        if (
            configured_minimum != SUBHYPOTHESIS_DECOMPOSITION_MIN_COUNT
            or configured_maximum != SUBHYPOTHESIS_DECOMPOSITION_MAX_COUNT
        ):
            raise ValueError(
                "Automatic SH decomposition is fixed at 3-6 sub-hypotheses; "
                f"received {configured_minimum}-{configured_maximum}."
            )
        if str(research_context.get("identity_status") or "").strip() == "out_of_scope":
            raise ValueError(
                "Automatic SH decomposition is unavailable because the project domain is out of scope "
                "for the natural science and engineering taxonomy."
            )
        temperature = float(
            self._work_collector_setting("subhypothesis_decomposition_temperature", 0.1)
        )
        max_output_tokens = int(
            self._work_collector_setting(
                "subhypothesis_decomposition_max_output_tokens",
                8000,
            )
        )

        def llm_call(prompt: str):
            return self._decomposition_chat_agent().remote_chat(
                prompt,
                temperature=temperature,
                max_output_tokens=max_output_tokens,
                response_format="json_object",
            )

        def log_raw_response(diagnostic: Mapping[str, str]) -> None:
            self.logger.info(
                "SH decomposition raw response type=%s preview=%s",
                diagnostic.get("response_type") or "unknown",
                diagnostic.get("preview") or "<empty>",
            )

        artifact = load_or_build_subhypothesis_decomposition(
            cache_path=(
                self._subhypothesis_decomposition_cache_path(
                    research_context,
                    provider=provider,
                    model=model,
                    reserved_subhypotheses=reserved_subhypotheses,
                    observation_projection=observation_projection,
                )
                if str(
                    self._work_collector_setting(
                        "subhypothesis_decomposition_cache_enabled",
                        True,
                    )
                ).strip().lower()
                not in {"0", "false", "no", "off"}
                else None
            ),
            project_context=research_context,
            llm_call=llm_call,
            raw_response_observer=log_raw_response,
            provider=provider,
            model=model,
            reserved_subhypotheses=reserved_subhypotheses,
            observation_projection=observation_projection,
        )
        artifact["source"] = "automatic_qwen"
        self._store_subhypothesis_decomposition_artifact(artifact)
        subhypotheses = [
            dict(item)
            for item in artifact.get("subhypotheses", [])
            if isinstance(item, Mapping)
        ]
        try:
            self.config.BasicInfo.subhypotheses = subhypotheses
        except Exception:
            pass
        self.logger.info(
            "Automatic SH decomposition [%s] generated %s validated sub-hypotheses using %s/%s.",
            artifact.get("cache_status"),
            len(subhypotheses),
            provider,
            model,
        )
        return subhypotheses

    def _multimodal_runtime_evidence(self) -> Mapping[str, Any] | None:
        multimodal = getattr(getattr(self, "config", None), "multimodal_evidence", None)
        if not hasattr(multimodal, "get"):
            return None
        if not bool(multimodal.get("enabled")):
            return None
        input_spec = multimodal.get("input_spec", {})
        if not isinstance(input_spec, Mapping) or not input_spec.get("records"):
            return None
        runtime_evidence = multimodal.get("runtime_evidence", {})
        if not isinstance(runtime_evidence, Mapping) or not runtime_evidence:
            return None
        try:
            evidence = validate_multimodal_evidence(runtime_evidence)
        except Exception as exc:
            raise ValueError("Invalid runtime multimodal evidence configuration.") from exc
        if evidence.get("perception", {}).get("mode") == "remote_perception" and not bool(
            multimodal.get("allow_remote_perception")
        ):
            raise ValueError(
                "Remote multimodal evidence requires the explicit allow_remote_perception gate."
            )
        return evidence

    def _load_data_anchored_subhypotheses(
        self,
        research_context: Mapping[str, Any],
    ) -> dict[str, Any]:
        evidence = self._multimodal_runtime_evidence()
        if evidence is None or not evidence.get("claims"):
            artifact = {
                "subhypotheses": [],
                "metadata_by_subhypothesis": {},
                "query_variant_bindings": [],
                "limitations": [],
            }
            self.data_anchored_subhypothesis_artifact = artifact
            return artifact
        multimodal = getattr(self.config, "multimodal_evidence", {})
        try:
            maximum = int(multimodal.get("max_data_anchored_sh", 3) or 3)
        except (AttributeError, TypeError, ValueError):
            maximum = 3
        if maximum < 1 or maximum > 3:
            raise ValueError("survey.multimodal_evidence.max_data_anchored_sh must be 1-3.")
        artifact = compile_data_anchored_subhypotheses(
            evidence.get("claims", []),
            research_context,
            max_count=maximum,
        )
        self.data_anchored_subhypothesis_artifact = dict(artifact)
        return dict(artifact)

    @staticmethod
    def _merge_data_anchored_subhypotheses(
        data_subhypotheses: Sequence[Mapping[str, Any]],
        other_subhypotheses: Sequence[Mapping[str, Any]],
    ) -> list[Dict]:
        merged = [
            dict(item)
            for item in [*data_subhypotheses, *other_subhypotheses]
            if isinstance(item, Mapping)
        ]
        identifiers = [str(item.get("sub_hypothesis_id") or "").strip() for item in merged]
        nonempty_identifiers = [identifier for identifier in identifiers if identifier]
        if len(nonempty_identifiers) != len(
            {identifier.casefold() for identifier in nonempty_identifiers}
        ):
            raise ValueError("Data-anchored and configured sub-hypotheses must not reuse an identifier.")
        if len(merged) > 12:
            raise ValueError(
                "Data-anchored, manual, and automatic sub-hypotheses exceed the retrieval limit of 12."
            )
        return merged

    def _resolved_subhypotheses(
        self,
        research_context: Mapping[str, Any],
    ) -> list[Dict]:
        data_anchored_artifact = self._load_data_anchored_subhypotheses(research_context)
        data_anchored_subhypotheses = list(
            data_anchored_artifact.get("subhypotheses") or []
        )
        observation_projection = self._multimodal_runtime_evidence() or {}
        configured_subhypotheses = self._configured_subhypotheses()
        existing_artifact = self._basic_info_value("subhypothesis_decomposition", {})
        automatic_artifact = (
            dict(existing_artifact)
            if isinstance(existing_artifact, Mapping)
            and existing_artifact.get("source") == "automatic_qwen"
            else {}
        )
        if automatic_artifact:
            expected_fingerprint = subhypothesis_decomposition_fingerprint(
                research_context,
                reserved_subhypotheses=data_anchored_subhypotheses,
                observation_projection=observation_projection,
            )
            if (
                automatic_artifact.get("project_context_fingerprint")
                == research_context.get("input_fingerprint")
                and automatic_artifact.get("input_fingerprint") == expected_fingerprint
            ):
                return self._merge_data_anchored_subhypotheses(
                    data_anchored_subhypotheses,
                    configured_subhypotheses,
                )
            configured_subhypotheses = []
        if configured_subhypotheses:
            self._store_subhypothesis_decomposition_artifact(
                {
                    "schema_version": "subhypothesis_decomposition_v2",
                    "source": "manual_configuration",
                    "project_context_fingerprint": str(
                        research_context.get("input_fingerprint") or ""
                    ),
                    "subhypotheses": configured_subhypotheses,
                    "validation": {"deferred_to_retrieval_contract": True},
                }
            )
            return self._merge_data_anchored_subhypotheses(
                data_anchored_subhypotheses,
                configured_subhypotheses,
            )
        if not self._automatic_subhypothesis_decomposition_enabled():
            return self._merge_data_anchored_subhypotheses(
                data_anchored_subhypotheses,
                [],
            )
        automatic_subhypotheses = self._auto_decompose_subhypotheses(
            research_context,
            reserved_subhypotheses=data_anchored_subhypotheses,
            observation_projection=observation_projection,
        )
        return self._merge_data_anchored_subhypotheses(
            data_anchored_subhypotheses,
            automatic_subhypotheses,
        )

    def _store_subhypothesis_retrieval_artifact(self, artifact: Mapping[str, Any]) -> None:
        self.subhypothesis_retrieval_artifact = dict(artifact)
        try:
            self.config.BasicInfo.subhypothesis_retrieval = self.subhypothesis_retrieval_artifact
        except Exception:
            pass

    @staticmethod
    def _remap_sh_annotation_root(
        annotation: Mapping[str, Any],
        graph_paper_id: str,
    ) -> Dict:
        """Bind a direct seed annotation to the graph's canonical paper ID."""

        record = dict(annotation)
        record["root_seed_paper_ids"] = [graph_paper_id]
        return record

    def _store_sh_graph_provenance_artifact(self, artifact: Mapping[str, Any]) -> None:
        """Persist the project-scoped SH graph audit without changing graph semantics."""

        artifact_to_store = dict(artifact)
        # DataManager publishes full-text acquisition independently after seed
        # selection.  Preserve that observational metadata when later graph
        # expansion rewrites the overlay; it must never be converted into a
        # node annotation or direct-evidence assertion.
        existing = self._basic_info_value("sh_graph_provenance", {})
        if (
            isinstance(existing, Mapping)
            and existing.get("project_id") == artifact_to_store.get("project_id")
            and existing.get("project_context_fingerprint")
            == artifact_to_store.get("project_context_fingerprint")
            and isinstance(
                existing.get("fulltext_acquisition_by_paper"), Mapping
            )
        ):
            artifact_to_store["fulltext_acquisition_by_paper"] = dict(
                existing["fulltext_acquisition_by_paper"]
            )
        self.sh_graph_provenance_artifact = artifact_to_store
        try:
            self.config.BasicInfo.sh_graph_provenance = self.sh_graph_provenance_artifact
        except Exception:
            pass
        base_dir = str(self._basic_info_value("base_dir", "") or "").strip()
        if not base_dir:
            return
        artifact_path = Path(base_dir) / "sh_graph_provenance.json"
        artifact_path.parent.mkdir(parents=True, exist_ok=True)
        artifact_path.write_text(
            json.dumps(self.sh_graph_provenance_artifact, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        try:
            self.config.BasicInfo.sh_graph_provenance_artifact_path = str(artifact_path)
        except Exception:
            pass

    def _initialize_sh_graph_provenance(
        self,
        research_context: Mapping[str, Any],
        selection: Mapping[str, Any],
        coverage_ledger: Mapping[str, Any],
    ) -> None:
        """Record direct SH seed evidence before any citation expansion begins."""

        selected_papers = [
            dict(paper)
            for paper in selection.get("selected_papers", [])
            if isinstance(paper, Mapping)
        ]
        direct_by_retrieval_id = build_seed_annotation_index(
            selected_papers,
            coverage_ledger,
            project_id=self._project_id(research_context),
            project_context_fingerprint=str(research_context.get("input_fingerprint") or ""),
        )
        annotations_by_paper: Dict[str, list[Dict]] = {}
        for paper in selected_papers:
            retrieval_id = paper_identity(paper)
            annotations = direct_by_retrieval_id.get(retrieval_id, [])
            if not annotations:
                continue
            data_manager = getattr(self, "data_manager", None)
            resolver = getattr(data_manager, "_resolve_paper_reference_id", None)
            source_id = str(
                resolver(paper) if callable(resolver) else paper_identity(paper)
            ).strip()
            aliases = getattr(self, "_openalex_id_aliases", {})
            graph_paper_id = aliases.get(source_id, source_id)
            if not graph_paper_id:
                continue
            remapped = [
                self._remap_sh_annotation_root(annotation, graph_paper_id)
                for annotation in annotations
            ]
            annotations_by_paper[graph_paper_id] = merge_node_annotations(
                annotations_by_paper.get(graph_paper_id),
                remapped,
            )
        artifact = {
            "schema_version": SH_GRAPH_PROVENANCE_SCHEMA_VERSION,
            "project_id": self._project_id(research_context),
            "project_context_fingerprint": str(
                research_context.get("input_fingerprint") or ""
            ),
            "paper_annotations": annotations_by_paper,
            "graph_expansion_records": [],
        }
        self._store_sh_graph_provenance_artifact(artifact)
        self.logger.info(
            "Initialized SH graph provenance: seed_papers=%s direct_annotations=%s.",
            len(annotations_by_paper),
            sum(len(records) for records in annotations_by_paper.values()),
        )

    def _sh_graph_annotation_index(self) -> Dict[str, list[Dict]]:
        artifact = getattr(self, "sh_graph_provenance_artifact", {})
        if not isinstance(artifact, Mapping):
            artifact = self._basic_info_value("sh_graph_provenance", {})
        records = artifact.get("paper_annotations", {}) if isinstance(artifact, Mapping) else {}
        return {
            str(paper_id): merge_node_annotations([], annotations)
            for paper_id, annotations in records.items()
            if isinstance(annotations, Sequence) and not isinstance(annotations, (str, bytes))
        }

    def _active_sh_graph_scope(self) -> tuple[str, str] | None:
        """Return the only project scope permitted to occupy graph SH fields."""

        artifact = getattr(self, "sh_graph_provenance_artifact", {})
        if not isinstance(artifact, Mapping):
            artifact = self._basic_info_value("sh_graph_provenance", {})
        if (
            not isinstance(artifact, Mapping)
            or artifact.get("schema_version") != SH_GRAPH_PROVENANCE_SCHEMA_VERSION
        ):
            return None
        project_id = str(artifact.get("project_id") or "").strip()
        fingerprint = str(artifact.get("project_context_fingerprint") or "").strip()
        return (project_id, fingerprint) if project_id and fingerprint else None

    def _reset_sh_graph_overlay_for_active_project(self) -> None:
        """Discard persisted SH overlays before rebuilding this project's overlay.

        Reference-graph topology is cacheable across projects; SH evidence is
        not. Rebuilding the project-scoped overlay prevents an old project with
        the same research-context fingerprint from contributing evidence.
        """

        if self.reference_graph is None or self._active_sh_graph_scope() is None:
            return
        for _paper_id, node in self.reference_graph.nodes(data=True):
            node.pop("sh_annotations", None)
            node.pop("sh_annotation_schema_version", None)
        for _source_id, _target_id, edge in self.reference_graph.edges(data=True):
            edge.pop("sh_expansion_lineage", None)

    def _attach_sh_graph_node_annotations(
        self,
        paper_id: str,
        annotations: Sequence[Mapping[str, Any]],
    ) -> None:
        if not annotations or self.reference_graph is None or paper_id not in self.reference_graph:
            return
        scope = self._active_sh_graph_scope()
        if scope is None:
            return
        project_id, fingerprint = scope
        current_annotations = current_project_node_annotations(
            annotations,
            project_id=project_id,
            project_context_fingerprint=fingerprint,
        )
        if not current_annotations:
            return
        node = self.reference_graph.nodes[paper_id]
        node["sh_annotations"] = merge_node_annotations(
            node.get("sh_annotations") if isinstance(node.get("sh_annotations"), list) else [],
            current_annotations,
        )
        if node["sh_annotations"]:
            node["sh_annotation_schema_version"] = SH_NODE_ANNOTATION_SCHEMA_VERSION

    def _record_graph_expansion_provenance(
        self,
        paper_id: str,
        annotations: Sequence[Mapping[str, Any]],
    ) -> None:
        if not annotations:
            return
        artifact = getattr(self, "sh_graph_provenance_artifact", {})
        if not isinstance(artifact, Mapping):
            return
        updated = dict(artifact)
        updated["paper_annotations"] = append_annotation_index(
            updated.get("paper_annotations"),
            paper_id,
            annotations,
        )
        expansion_records = list(updated.get("graph_expansion_records") or [])
        known = {
            (
                str(record.get("paper_id") or ""),
                str(record.get("sub_hypothesis_id") or ""),
                tuple(record.get("root_seed_paper_ids") or []),
                tuple(record.get("parent_paper_ids") or []),
                int(record.get("lineage_depth") or 0),
                str(record.get("citation_direction") or ""),
                str(record.get("graph_lineage_source") or ""),
                str(record.get("local_graph_node_id") or ""),
                str(record.get("local_graph_parent_node_id") or ""),
            )
            for record in expansion_records
            if isinstance(record, Mapping)
        }
        for annotation in annotations:
            record = {
                "paper_id": paper_id,
                "sub_hypothesis_id": annotation.get("sub_hypothesis_id", ""),
                "association_status": annotation.get("association_status", ""),
                "root_seed_paper_ids": list(annotation.get("root_seed_paper_ids") or []),
                "parent_paper_ids": list(annotation.get("parent_paper_ids") or []),
                "lineage_depth": int(annotation.get("lineage_depth") or 0),
                "citation_direction": annotation.get("citation_direction", ""),
                "graph_lineage_source": annotation.get("graph_lineage_source", ""),
                "local_graph_node_id": annotation.get("local_graph_node_id", ""),
                "local_graph_parent_node_id": annotation.get(
                    "local_graph_parent_node_id",
                    "",
                ),
            }
            key = (
                record["paper_id"],
                record["sub_hypothesis_id"],
                tuple(record["root_seed_paper_ids"]),
                tuple(record["parent_paper_ids"]),
                record["lineage_depth"],
                record["citation_direction"],
                record["graph_lineage_source"],
                record["local_graph_node_id"],
                record["local_graph_parent_node_id"],
            )
            if key not in known:
                known.add(key)
                expansion_records.append(record)
        updated["graph_expansion_records"] = expansion_records
        self.sh_graph_provenance_artifact = updated

    def _record_local_graph_expansion_provenance(
        self,
        local_node_to_paper_id: Mapping[str, str],
    ) -> None:
        """Persist local-paper-graph lineage as candidate-only SH provenance.

        Local graph traversal is a retrieval mechanism, not a scientific
        assessment.  Its resolved papers therefore receive the same
        ``GRAPH_EXPANDED_CANDIDATE_ONLY`` boundary as OpenAlex descendants.
        Parent IDs are emitted only when the local parent was also resolved to
        a provider paper ID; otherwise the exact local parent node is retained
        separately instead of fabricating an external-paper parent.
        """

        local_lineage = getattr(self, "_local_graph_expansion_lineage_by_node_id", {})
        if not isinstance(local_lineage, Mapping) or not local_lineage:
            return
        root_annotations_by_paper = self._sh_graph_annotation_index()
        wrote_annotations = False
        for local_node_id, raw_paths in local_lineage.items():
            resolved_paper_id = str(local_node_to_paper_id.get(local_node_id) or "").strip()
            if not resolved_paper_id:
                continue
            paths = raw_paths if isinstance(raw_paths, Sequence) and not isinstance(
                raw_paths, (str, bytes)
            ) else []
            for raw_path in paths:
                path = dict(raw_path) if isinstance(raw_path, Mapping) else {}
                root_seed_paper_id = str(path.get("root_seed_paper_id") or "").strip()
                if not root_seed_paper_id or resolved_paper_id == root_seed_paper_id:
                    continue
                root_annotations = root_annotations_by_paper.get(root_seed_paper_id, [])
                if not root_annotations:
                    continue
                parent_local_node_id = str(path.get("parent_node_id") or "").strip()
                parent_paper_id = str(
                    local_node_to_paper_id.get(parent_local_node_id) or ""
                ).strip()
                if not parent_paper_id and int(path.get("lineage_depth") or 0) == 1:
                    parent_paper_id = root_seed_paper_id
                annotations = build_graph_expansion_annotations(
                    root_annotations,
                    parent_paper_id=parent_paper_id,
                    root_seed_paper_id=root_seed_paper_id,
                    lineage_depth=max(1, int(path.get("lineage_depth") or 1)),
                    citation_direction="local_paper_graph",
                )
                for annotation in annotations:
                    annotation["graph_lineage_source"] = "local_paper_graph"
                    annotation["local_graph_node_id"] = str(local_node_id)
                    annotation["local_graph_parent_node_id"] = parent_local_node_id
                    annotation["lineage_precision"] = str(
                        path.get("lineage_precision") or "EXACT_LOCAL_GRAPH_PATH"
                    )
                self._record_graph_expansion_provenance(resolved_paper_id, annotations)
                self._attach_sh_graph_node_annotations(resolved_paper_id, annotations)
                wrote_annotations = wrote_annotations or bool(annotations)
        if wrote_annotations:
            self._store_sh_graph_provenance_artifact(self.sh_graph_provenance_artifact)

    def _attach_sh_expansion_edge_provenance(
        self,
        source_id: str,
        target_id: str,
        annotations: Sequence[Mapping[str, Any]],
    ) -> None:
        if not annotations or self.reference_graph is None:
            return
        if not self.reference_graph.has_edge(source_id, target_id):
            return
        edge = self.reference_graph.edges[source_id, target_id]
        scope = self._active_sh_graph_scope()
        if scope is None:
            return
        project_id, fingerprint = scope
        current_annotations = current_project_node_annotations(
            annotations,
            project_id=project_id,
            project_context_fingerprint=fingerprint,
        )
        if not current_annotations:
            return
        existing = edge.get("sh_expansion_lineage")
        records = existing if isinstance(existing, list) else []
        keys = {
            (
                str(record.get("project_id") or ""),
                str(record.get("project_context_fingerprint") or ""),
                str(record.get("sub_hypothesis_id") or ""),
                tuple(record.get("root_seed_paper_ids") or []),
                int(record.get("lineage_depth") or 0),
                str(record.get("citation_direction") or ""),
            )
            for record in records
            if isinstance(record, Mapping)
        }
        for annotation in current_annotations:
            record = {
                "schema_version": SH_NODE_ANNOTATION_SCHEMA_VERSION,
                "project_id": annotation.get("project_id", ""),
                "project_context_fingerprint": annotation.get(
                    "project_context_fingerprint", ""
                ),
                "sub_hypothesis_id": annotation.get("sub_hypothesis_id", ""),
                "root_seed_paper_ids": list(
                    annotation.get("root_seed_paper_ids") or []
                ),
                "lineage_depth": int(annotation.get("lineage_depth") or 0),
                "citation_direction": annotation.get("citation_direction", ""),
            }
            key = (
                str(record["project_id"] or ""),
                str(record["project_context_fingerprint"] or ""),
                str(record["sub_hypothesis_id"] or ""),
                tuple(record["root_seed_paper_ids"]),
                record["lineage_depth"],
                str(record["citation_direction"] or ""),
            )
            if key not in keys:
                keys.add(key)
                records.append(record)
        edge["sh_expansion_lineage"] = records

    def _research_context_cache_path(
        self,
        *,
        original_topic: str,
        title: str,
        declared_domain: str,
        objective: str,
        research_brief: str,
    ) -> str:
        configured_path = str(
            self._basic_info_value("research_context_path", "") or ""
        ).strip()
        if configured_path:
            return configured_path
        fingerprint = project_research_context_fingerprint(
            original_topic=original_topic,
            title=title,
            declared_domain=declared_domain,
            objective=objective,
            research_brief=research_brief,
        )
        return os.path.join(self.cache_path, "research_context", f"{fingerprint}.json")

    def _research_context_uses_llm(self) -> bool:
        configured_value = self._basic_info_value("research_context_use_llm", True)
        return str(configured_value).strip().lower() not in {"0", "false", "no", "off"}

    def _store_project_research_context(self, context: Dict) -> None:
        try:
            self.config.BasicInfo.research_context = context
            self.config.BasicInfo.research_design_inventory = dict(
                context.get("research_design_inventory") or {}
            )
        except Exception:
            pass

    def _project_id(self, context: Mapping[str, Any]) -> str:
        run_id = str(self._basic_info_value("survey_run_id", "") or "").strip()
        stable_id = re.sub(r"[^A-Za-z0-9_]+", "_", run_id).strip("_")
        if stable_id:
            return f"sci_{stable_id}"
        return f"sci_{str(context.get('input_fingerprint') or '')[:18]}"

    def _persist_project_context_artifact(self, context: Mapping[str, Any]) -> str:
        base_dir = str(self._basic_info_value("base_dir", "") or "").strip()
        if not base_dir:
            return ""
        artifact_path = Path(base_dir) / "project_context.json"
        artifact_path.parent.mkdir(parents=True, exist_ok=True)
        artifact = {
            "schema_version": "survey_project_context_artifact_v1",
            "event": "project_created",
            "project_id": self._project_id(context),
            "declared_domain": context.get("declared_domain", ""),
            "domain": context.get("domain", ""),
            "research_domains": context.get("research_domains", []),
            "domain_resolution_source": context.get("domain_resolution_source", ""),
            "requires_human_confirmation": bool(
                context.get("requires_human_confirmation")
            ),
            "research_context": dict(context),
        }
        artifact_path.write_text(
            json.dumps(artifact, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        try:
            self.config.BasicInfo.project_context_artifact_path = str(artifact_path)
        except Exception:
            pass
        return str(artifact_path)

    def _publish_project_context(self, context: Mapping[str, Any]) -> Dict:
        published = dict(context)
        self.project_research_context = published
        self._store_project_research_context(published)
        artifact_path = self._persist_project_context_artifact(published)
        if getattr(self, "_project_created_event_emitted", False):
            return published
        self._project_created_event_emitted = True
        research_domains = [
            str(item.get("label") or "")
            for item in published.get("research_domains", [])
            if isinstance(item, Mapping)
        ]
        event_fields = {
            "project_id": self._project_id(published),
            "declared_domain": published.get("declared_domain", ""),
            "domain": published.get("domain", ""),
            "research_domains": research_domains,
            "domain_resolution_source": published.get("domain_resolution_source", ""),
            "requires_human_confirmation": bool(
                published.get("requires_human_confirmation")
            ),
        }
        emit_science_event(self.logger, "project_created", **event_fields)
        self.logger.info(
            "Project domain context [%s]: declared=%s domain=%s research_domains=%s "
            "source=%s requires_human_confirmation=%s artifact=%s",
            published.get("cache_status", "memory"),
            event_fields["declared_domain"] or "Unspecified",
            event_fields["domain"] or "Unresolved Research Domain",
            "|".join(research_domains) or "Unspecified",
            event_fields["domain_resolution_source"] or "catalog",
            event_fields["requires_human_confirmation"],
            artifact_path or "not_configured",
        )
        inventory = published.get("research_design_inventory")
        if isinstance(inventory, Mapping):
            self.logger.info(
                "Project research design inventory [%s]: bases=%s source=%s llm=%s",
                published.get("cache_status", "memory"),
                len(inventory.get("design_basis") or []),
                inventory.get("inventory_source") or "unresolved",
                bool(inventory.get("llm_used")),
            )
        return published

    def get_project_research_context(self, topic: str = "") -> Dict:
        resolved_topic = str(topic or self._basic_info_value("topic", "") or "").strip()
        title = self._basic_info_value("research_title", "")
        declared_domain = self._basic_info_value("declared_domain", "")
        objective = self._basic_info_value("research_objective", "")
        research_brief = self._basic_info_value("research_brief", "")
        input_fingerprint = project_research_context_fingerprint(
            original_topic=resolved_topic,
            title=title,
            declared_domain=declared_domain,
            objective=objective,
            research_brief=research_brief,
        )
        existing_instance_context = getattr(self, "project_research_context", None)
        if (
            isinstance(existing_instance_context, dict)
            and existing_instance_context.get("schema_version")
            == PROJECT_RESEARCH_CONTEXT_SCHEMA_VERSION
            and existing_instance_context.get("input_fingerprint") == input_fingerprint
        ):
            return self._publish_project_context(existing_instance_context)

        existing_context = self._basic_info_value("research_context", {})
        if (
            isinstance(existing_context, Mapping)
            and existing_context.get("schema_version")
            == PROJECT_RESEARCH_CONTEXT_SCHEMA_VERSION
            and existing_context.get("input_fingerprint") == input_fingerprint
        ):
            return self._publish_project_context(existing_context)

        if getattr(self.config, "BasicInfo", None) is None:
            context = load_or_build_project_research_context(
                cache_path=None,
                original_topic=resolved_topic,
                use_llm=False,
            )
            return self._publish_project_context(context)

        self.logger.info(
            "Resolving project domain before retrieval: declared=%s title=%s llm=%s",
            str(declared_domain or "").strip() or "Unspecified",
            str(title or "").strip() or "Unspecified",
            self._research_context_uses_llm(),
        )

        def llm_call(prompt: str):
            return self.chat_agent.remote_chat(
                prompt,
                temperature=0.0,
                max_output_tokens=4000,
            )

        context = load_or_build_project_research_context(
            cache_path=self._research_context_cache_path(
                original_topic=resolved_topic,
                title=title,
                declared_domain=declared_domain,
                objective=objective,
                research_brief=research_brief,
            ),
            original_topic=resolved_topic,
            title=title,
            declared_domain=declared_domain,
            objective=objective,
            research_brief=research_brief,
            use_llm=self._research_context_uses_llm(),
            llm_call=llm_call,
        )
        return self._publish_project_context(context)

    @staticmethod
    def _is_exact_native_lane(lane: Mapping[str, Any]) -> bool:
        provider_filter = lane.get("provider_filter")
        return bool(
            lane.get("hard_filter_applied")
            and isinstance(provider_filter, Mapping)
            and provider_filter.get("applied")
            and provider_filter.get("coverage") == "exact"
            and provider_filter.get("policy") == "hard_filter"
        )

    def _project_query_plan(self, research_context: Mapping[str, Any]) -> Dict:
        plan = research_context.get("retrieval_plan")
        if (
            isinstance(plan, Mapping)
            and plan.get("execution_policy") == "limited_query_lanes"
            and isinstance(plan.get("query_lanes"), list)
        ):
            return dict(plan)
        # Cached v1 contexts were metadata-only. Upgrade their route in memory
        # without rebuilding the one-time project identity or invoking its LLM.
        return build_project_query_lanes(research_context)

    @staticmethod
    def _candidate_identity_keys(paper: Mapping[str, Any]) -> list[str]:
        keys: list[str] = []
        openalex_id = str(paper.get("openalex_id") or paper.get("paperId") or "").strip()
        openalex_match = re.search(r"(?:^|/)(W\d+)$", openalex_id, re.IGNORECASE)
        if openalex_match:
            keys.append(f"openalex:{openalex_match.group(1).upper()}")
        external_ids = paper.get("externalIds")
        external = external_ids if isinstance(external_ids, Mapping) else {}
        doi = str(paper.get("doi") or external.get("DOI") or external.get("doi") or "").strip()
        if doi:
            keys.append(re.sub(r"^https?://(?:dx\.)?doi\.org/", "", doi, flags=re.IGNORECASE).lower().rstrip("/.,;"))
        arxiv_id = str(
            external.get("ArXiv") or external.get("arXiv") or paper.get("paper_id") or ""
        ).strip()
        if arxiv_id:
            keys.append(f"arxiv:{arxiv_id.split('v')[0].lower()}")
        title = re.sub(r"\W+", "", str(paper.get("title") or "").casefold())
        if title:
            keys.append(f"title:{title}")
        return keys

    @staticmethod
    def _lane_provenance(lane: Mapping[str, Any]) -> Dict:
        provider_filter = lane.get("provider_filter")
        recovered_slot_task_ids = lane.get("recovered_slot_task_ids")
        resolution_slot_task_ids = lane.get("resolution_slot_task_ids")
        return {
            "lane_id": str(lane.get("lane_id") or lane.get("lane") or ""),
            "lane": str(lane.get("lane") or ""),
            "provider": str(lane.get("provider") or ""),
            "query": str(lane.get("query") or ""),
            "evidence_mode": str(lane.get("evidence_mode") or "overview"),
            "taxonomy_coverage": str(lane.get("taxonomy_coverage") or "broad"),
            "hard_filter_applied": bool(lane.get("hard_filter_applied")),
            "provider_filter": dict(provider_filter) if isinstance(provider_filter, Mapping) else {},
            "source_work_count": int(lane.get("source_work_count") or 0),
            "sub_hypothesis_id": str(lane.get("sub_hypothesis_id") or ""),
            "slot_recovery_task_id": str(lane.get("slot_recovery_task_id") or ""),
            "slot_name": str(lane.get("slot_name") or ""),
            "expected_evidence_role": str(lane.get("expected_evidence_role") or ""),
            "query_variant_id": str(lane.get("query_variant_id") or ""),
            "query_variant_index": int(lane.get("query_variant_index") or 0),
            "query_variant_purpose": str(lane.get("query_variant_purpose") or ""),
            "query_variant_terms": [
                str(item)
                for item in lane.get("query_variant_terms", [])
                if str(item).strip()
            ]
            if isinstance(lane.get("query_variant_terms"), list)
            else [],
            "query_variant_source": str(lane.get("query_variant_source") or ""),
            "query_quality_warnings": [
                str(item)
                for item in lane.get("query_quality_warnings", [])
                if str(item).strip()
            ]
            if isinstance(lane.get("query_quality_warnings"), list)
            else [],
            "discipline_filter_policy": str(
                lane.get("discipline_filter_policy") or "broad"
            ),
            "execution_phase": str(lane.get("execution_phase") or "initial"),
            "refinement_task_id": str(lane.get("refinement_task_id") or ""),
            "refinement_kind": str(lane.get("refinement_kind") or ""),
            "refinement_activation_reasons": [
                str(item)
                for item in lane.get("refinement_activation_reasons", [])
                if str(item).strip()
            ]
            if isinstance(lane.get("refinement_activation_reasons"), list)
            else [],
            "recovered_slot_task_ids": [
                str(item)
                for item in recovered_slot_task_ids
                if str(item).strip()
            ]
            if isinstance(recovered_slot_task_ids, list)
            else [],
            "resolution_slot_task_ids": [
                str(item)
                for item in resolution_slot_task_ids
                if str(item).strip()
            ]
            if isinstance(resolution_slot_task_ids, list)
            else [],
            "resolution_target": str(lane.get("resolution_target") or ""),
            "retrieval_stage": str(lane.get("retrieval_stage") or "primary_slot_recovery"),
            "retrieval_round": int(lane.get("retrieval_round") or 0),
            "retrieval_cache": (
                dict(lane.get("retrieval_cache"))
                if isinstance(lane.get("retrieval_cache"), Mapping)
                else {}
            ),
        }

    def _merge_retrieval_candidates(
        self,
        lane_results: list[tuple[Mapping[str, Any], list[Dict]]],
    ) -> list[Dict]:
        merged: list[Dict] = []
        key_to_index: Dict[str, int] = {}
        for lane, papers in lane_results:
            provenance = self._lane_provenance(lane)
            for paper in papers:
                if not isinstance(paper, dict):
                    continue
                identity_keys = self._candidate_identity_keys(paper)
                existing_index = next(
                    (key_to_index[key] for key in identity_keys if key in key_to_index),
                    None,
                )
                if existing_index is None:
                    existing_index = len(merged)
                    merged.append(paper)
                target = merged[existing_index]
                existing_provenance = target.get("retrieval_provenance")
                provenance_records = (
                    existing_provenance if isinstance(existing_provenance, list) else []
                )
                if not any(record.get("lane_id") == provenance["lane_id"] for record in provenance_records if isinstance(record, Mapping)):
                    provenance_records.append(provenance)
                target["retrieval_provenance"] = provenance_records
                for key in identity_keys:
                    key_to_index[key] = existing_index
        return merged

    def _merge_candidate_collections(self, collections: Sequence[Sequence[Mapping[str, Any]]]) -> list[Dict]:
        merged: list[Dict] = []
        key_to_index: Dict[str, int] = {}
        for collection in collections:
            for candidate in collection:
                if not isinstance(candidate, Mapping):
                    continue
                paper = dict(candidate)
                identity_keys = self._candidate_identity_keys(paper)
                existing_index = next(
                    (key_to_index[key] for key in identity_keys if key in key_to_index),
                    None,
                )
                if existing_index is None:
                    existing_index = len(merged)
                    merged.append(paper)
                else:
                    target = merged[existing_index]
                    for key, value in paper.items():
                        if key not in target or not target.get(key):
                            target[key] = value
                    target_provenance = target.get("retrieval_provenance")
                    candidate_provenance = paper.get("retrieval_provenance")
                    records = target_provenance if isinstance(target_provenance, list) else []
                    for record in candidate_provenance if isinstance(candidate_provenance, list) else []:
                        if isinstance(record, Mapping) and record not in records:
                            records.append(dict(record))
                    target["retrieval_provenance"] = records
                    existing_semantic = target.get("sh_semantic_assessments")
                    candidate_semantic = paper.get("sh_semantic_assessments")
                    semantic_by_sh = {
                        str(item.get("sub_hypothesis_id") or ""): dict(item)
                        for item in (existing_semantic if isinstance(existing_semantic, list) else [])
                        if isinstance(item, Mapping)
                        and item.get("sub_hypothesis_id")
                    }
                    for item in candidate_semantic if isinstance(candidate_semantic, list) else []:
                        if not isinstance(item, Mapping) or not item.get("sub_hypothesis_id"):
                            continue
                        semantic_by_sh.setdefault(
                            str(item.get("sub_hypothesis_id") or ""),
                            dict(item),
                        )
                    if semantic_by_sh:
                        target["sh_semantic_assessments"] = [
                            semantic_by_sh[sub_hypothesis_id]
                            for sub_hypothesis_id in sorted(semantic_by_sh)
                        ]
                for key in identity_keys:
                    key_to_index[key] = existing_index
        return merged

    @staticmethod
    def _candidate_lane_names(paper: Mapping[str, Any]) -> list[str]:
        provenance = paper.get("retrieval_provenance")
        records = provenance if isinstance(provenance, list) else []
        lane_names: list[str] = []
        for record in records:
            if not isinstance(record, Mapping):
                continue
            lane_name = str(record.get("lane") or "").strip()
            if lane_name and lane_name not in lane_names:
                lane_names.append(lane_name)
        return lane_names

    def _select_lane_balanced_seed_candidates(
        self,
        papers: List[Dict],
        limit: int,
    ) -> List[Dict]:
        """Reserve small, bounded slots for unique candidates from each lane.

        Without this step a five-paper download limit can be entirely consumed by
        the first broad OpenAlex response, making exact, arXiv, and evidence
        lanes observational only.  It does not change the broad lane or force
        duplicated candidates into the result.
        """

        if limit <= 0 or len(papers) <= limit:
            return papers
        lane_order = (
            "broad_anchor",
            "exact_primary_discipline",
            "adjacent_precision",
            "exact_discipline",
            "arxiv_frontier",
            "evidence_mode",
            "semantic_scholar_fallback",
        )
        selected_indices: list[int] = []
        selected = set()
        for lane_name in lane_order:
            if len(selected_indices) >= limit:
                break
            for index, paper in enumerate(papers):
                if index in selected or not isinstance(paper, Mapping):
                    continue
                if lane_name in self._candidate_lane_names(paper):
                    selected_indices.append(index)
                    selected.add(index)
                    break

        lane_rank = {lane_name: rank for rank, lane_name in enumerate(lane_order)}

        def remaining_priority(item):
            index, paper = item
            ranks = [
                lane_rank.get(lane_name, len(lane_rank))
                for lane_name in self._candidate_lane_names(paper)
            ]
            return (min(ranks) if ranks else len(lane_rank), index)

        for index, _paper in sorted(enumerate(papers), key=remaining_priority):
            if len(selected_indices) >= limit:
                break
            if index not in selected:
                selected_indices.append(index)
                selected.add(index)
        return [papers[index] for index in selected_indices]

    def _execute_query_lane_with_status(
        self,
        lane: Mapping[str, Any],
    ) -> tuple[list[Dict], bool, str]:
        """Execute one lane and report whether an empty result is trustworthy.

        Provider failures must not be cached as an apparent scientific absence.
        Tests and integrations which replace ``_execute_query_lane`` on an
        instance retain the historical list-only interface and are considered
        successful executions of their explicit test double.
        """

        provider = str(lane.get("provider") or "").strip().lower()
        overridden_executor = self.__dict__.get("_execute_query_lane")
        # Semantic Scholar fallback owns a different response shape and must
        # still call its dedicated provider when tests use a simple OpenAlex
        # lane double to make the primary lanes empty.
        if provider != "semantic_scholar" and callable(overridden_executor):
            result = overridden_executor(lane)
            papers = list(result) if isinstance(result, list) else []
            return papers, True, "success" if papers else "valid_empty"

        query = str(lane.get("query") or "").strip()
        if not query:
            return [], False, "provider_failure"
        if provider == "arxiv" and not self._arxiv_discovery_enabled():
            return [], False, "provider_failure"
        provider_filter = lane.get("provider_filter") if self._is_exact_native_lane(lane) else None
        try:
            if provider == "openalex":
                openalex_api = self.data_manager.openalex_api
                search_with_status = getattr(openalex_api, "search_papers_with_status", None)
                if callable(search_with_status):
                    result, successful = search_with_status(
                        query,
                        provider_filter=provider_filter,
                        sort=lane.get("sort"),
                    )
                    papers = list(result) if isinstance(result, list) else []
                    return papers, bool(successful), "success" if papers and successful else "valid_empty" if successful else "provider_failure"
                if provider_filter is None and not lane.get("sort"):
                    result = openalex_api.search_papers(query) or []
                    papers = list(result) if isinstance(result, list) else []
                    return papers, True, "success" if papers else "valid_empty"
                result = openalex_api.search_papers(
                    query,
                    provider_filter=provider_filter,
                    sort=lane.get("sort"),
                ) or []
                papers = list(result) if isinstance(result, list) else []
                return papers, True, "success" if papers else "valid_empty"
            if provider == "arxiv":
                arxiv_api = getattr(self.data_manager, "arxiv_api", None)
                if arxiv_api is None or provider_filter is None:
                    return [], False, "provider_failure"
                result = arxiv_api.search_papers(query, provider_filter=provider_filter) or []
                papers = list(result) if isinstance(result, list) else []
                return papers, True, "success" if papers else "valid_empty"
            if provider == "semantic_scholar":
                semantic_api = getattr(self.data_manager, "semantic_scholar_api", None)
                if semantic_api is None:
                    return [], False, "provider_failure"
                response = semantic_api.search_papers(
                    query=query,
                    fields=str(
                        lane.get("semantic_scholar_fields")
                        or "title,externalIds,openAccessPdf,abstract"
                    ),
                )
                if not isinstance(response, Mapping):
                    status_code = getattr(semantic_api, "last_status_code", None)
                    provider_status = (
                        "rate_limited"
                        if str(status_code) == "429"
                        else "provider_failure"
                    )
                    return [], False, provider_status
                if response.get("error") or response.get("message"):
                    status_code = getattr(semantic_api, "last_status_code", None)
                    provider_status = (
                        "rate_limited"
                        if str(status_code) == "429"
                        else "provider_failure"
                    )
                    return [], False, provider_status
                papers = response.get("data")
                if not isinstance(papers, list):
                    return [], False, "provider_failure"
                result = list(papers)
                return result, True, "success" if result else "valid_empty"
        except Exception as exc:
            error_text = str(exc).casefold()
            provider_status = "rate_limited" if "429" in error_text or "rate limit" in error_text or "too many requests" in error_text else "provider_failure"
            self.logger.warning(
                "Discovery lane %s (%s) failed without aborting the remaining lanes: %s",
                lane.get("lane_id") or lane.get("lane"),
                provider,
                exc,
            )
            return [], False, provider_status
        return [], False, "provider_failure"

    def _execute_query_lane(self, lane: Mapping[str, Any]) -> list[Dict]:
        """Backward-compatible list-only execution path for non-SH callers."""

        papers, _successful, _status = self._execute_query_lane_with_status(lane)
        return papers

    def _semantic_scholar_fallback(self, topic: str) -> list[Dict]:
        try:
            response = self.data_manager.semantic_scholar_api.search_papers(
                query=topic,
                fields="title,externalIds,openAccessPdf,abstract",
            )
        except Exception as exc:
            self.logger.warning("Semantic Scholar fallback failed: %s", exc)
            return []
        papers = response.get("data", []) if isinstance(response, Mapping) else []
        fallback_lane = {
            "lane_id": "semantic_scholar_fallback",
            "lane": "semantic_scholar_fallback",
            "provider": "semantic_scholar",
            "query": topic,
            "evidence_mode": "overview",
            "taxonomy_coverage": "broad",
            "hard_filter_applied": False,
            "provider_filter": {},
            "source_work_count": len(papers),
        }
        return self._merge_retrieval_candidates([(fallback_lane, papers)])

    def _discover_seed_candidates(
        self,
        topic: str,
        retrieval_plan: Mapping[str, Any],
        *,
        allow_semantic_fallback: bool = True,
    ) -> list[Dict]:
        lanes = retrieval_plan.get("query_lanes")
        lane_results: list[tuple[Mapping[str, Any], list[Dict]]] = []
        for lane in lanes if isinstance(lanes, list) else []:
            if not isinstance(lane, Mapping) or not self._discovery_lane_enabled(lane):
                continue
            papers = self._execute_query_lane(lane)
            executed_lane = {**lane, "source_work_count": len(papers)}
            lane_results.append((executed_lane, papers))
            self.logger.info(
                "Discovery lane %s returned %s candidates.",
                lane.get("lane_id") or lane.get("lane"),
                len(papers),
            )
        papers = self._merge_retrieval_candidates(lane_results)
        if papers or not allow_semantic_fallback:
            return papers
        self.logger.info(
            "All enabled discovery lanes were empty; using Semantic Scholar fallback."
        )
        return self._semantic_scholar_fallback(topic)

    def build_subhypothesis_retrieval_plan(self, subhypotheses, topic: str = "") -> Dict:
        """Expose the cached project identity to an SH planner without another LLM call."""
        research_context = self.get_project_research_context(topic)
        data_anchored_artifact = self._load_data_anchored_subhypotheses(research_context)
        return build_subhypothesis_retrieval_plan(
            research_context,
            subhypotheses,
            include_arxiv=self._arxiv_discovery_enabled(),
            query_variant_bindings=(
                data_anchored_artifact.get("query_variant_bindings")
                if data_anchored_artifact.get("query_variant_bindings")
                else None
            ),
            subhypothesis_metadata=(
                data_anchored_artifact.get("metadata_by_subhypothesis")
                if data_anchored_artifact.get("metadata_by_subhypothesis")
                else None
            ),
        )

    @staticmethod
    def _valid_subhypotheses(plan: Mapping[str, Any]) -> list[Dict]:
        valid_subhypotheses: list[Dict] = []
        for subhypothesis in plan.get("subhypotheses", []):
            if not isinstance(subhypothesis, Mapping) or not subhypothesis.get("sub_hypothesis_id"):
                continue
            validation = subhypothesis.get("validation")
            if isinstance(validation, Mapping) and validation.get("valid"):
                valid_subhypotheses.append(dict(subhypothesis))
        return valid_subhypotheses

    @staticmethod
    def _supplement_terms(expected_evidence_role: str) -> str:
        terms = {
            "DIRECT_OBSERVATION": "primary experiment observational study direct measurement",
            "COMPARATIVE_OR_MEASUREMENT_EVIDENCE": "comparative evaluation benchmark measurement validation",
            "MECHANISTIC_EVIDENCE": "mechanism ablation causal pathway",
            "LIMITING_OR_CHALLENGING_EVIDENCE": "failure limitation negative result boundary condition",
            "BACKGROUND_CONTEXT": "systematic review meta-analysis framework taxonomy",
        }
        return terms.get(expected_evidence_role, "")

    def _slot_recovery_task_lanes(
        self,
        subhypotheses: Sequence[Mapping[str, Any]],
        *,
        task_ids_by_subhypothesis: Mapping[str, Sequence[str]] | None = None,
        retrieval_round: int = 0,
    ) -> list[Dict]:
        lanes: list[Dict] = []
        selected_tasks = task_ids_by_subhypothesis or {}
        try:
            max_variants = max(
                1,
                min(
                    5,
                    int(self._work_collector_setting("max_query_variants_per_slot", 5) or 5),
                ),
            )
            max_terms = max(
                2,
                min(
                    6,
                    int(self._work_collector_setting("max_terms_per_query_variant", 6) or 6),
                ),
            )
            max_adjacent_fields = max(
                1,
                min(
                    3,
                    int(
                        self._work_collector_setting(
                            "max_adjacent_discipline_fields", 3
                        )
                        or 3
                    ),
                ),
            )
        except (TypeError, ValueError):
            max_variants, max_terms, max_adjacent_fields = 5, 6, 3
        adjacent_precision_enabled = str(
            self._work_collector_setting(
                "enable_adjacent_discipline_precision_lane", True
            )
        ).strip().lower() not in {"0", "false", "no", "off"}
        for subhypothesis in subhypotheses:
            subhypothesis_id = str(subhypothesis.get("sub_hypothesis_id") or "")
            requested_task_ids = set(selected_tasks.get(subhypothesis_id, []))
            for task in subhypothesis.get("slot_recovery_tasks", []):
                if not isinstance(task, Mapping):
                    continue
                task_id = str(task.get("task_id") or "")
                if requested_task_ids and task_id not in requested_task_ids:
                    continue
                task_plan = task.get("retrieval_plan")
                for lane in (task_plan or {}).get("query_lanes", []):
                    if not isinstance(lane, Mapping) or not self._discovery_lane_enabled(lane):
                        continue
                    try:
                        variant_index = int(lane.get("query_variant_index") or 0)
                    except (TypeError, ValueError):
                        variant_index = 0
                    if variant_index >= max_variants:
                        continue
                    if (
                        str(lane.get("discipline_filter_policy") or "").strip()
                        == "adjacent_precision"
                        and not adjacent_precision_enabled
                    ):
                        continue
                    prepared_lane = {
                        **lane,
                        "sub_hypothesis_id": subhypothesis_id,
                        "slot_recovery_task_id": task_id,
                        "slot_name": str(task.get("slot_name") or ""),
                        "expected_evidence_role": str(task.get("expected_evidence_role") or ""),
                        "retrieval_round": retrieval_round,
                        "purpose": "slot_recovery",
                    }
                    variant_terms = prepared_lane.get("query_variant_terms")
                    if isinstance(variant_terms, list) and variant_terms:
                        bounded_terms: list[str] = []
                        word_count = 0
                        for item in variant_terms[:max_terms]:
                            term = re.sub(r"\s+", " ", str(item).strip())
                            if not term or (bounded_terms and word_count + len(term.split()) > 12):
                                continue
                            bounded_terms.append(term)
                            word_count += len(term.split())
                        prepared_lane["query_variant_terms"] = bounded_terms
                        compiled_query = " ".join(bounded_terms)
                        prepared_lane["query"] = (
                            compiled_query
                            if len(compiled_query) <= 240
                            else compiled_query[:240].rsplit(" ", 1)[0]
                        )
                    if (
                        str(prepared_lane.get("discipline_filter_policy") or "")
                        == "adjacent_precision"
                    ):
                        provider_filter = prepared_lane.get("provider_filter")
                        if isinstance(provider_filter, Mapping):
                            fields = [
                                str(item).strip()
                                for item in provider_filter.get("resolved_field_ids", [])
                                if str(item).strip()
                            ][:max_adjacent_fields]
                            disciplines = list(
                                provider_filter.get("resolved_discipline_ids", [])
                            )[:max_adjacent_fields]
                            if fields:
                                prepared_lane["provider_filter"] = {
                                    **provider_filter,
                                    "resolved_field_ids": fields,
                                    "resolved_discipline_ids": disciplines,
                                    "filter": "primary_topic.field.id:" + "|".join(fields),
                                }
                    if retrieval_round:
                        supplement_terms = self._supplement_terms(
                            str(task.get("expected_evidence_role") or "")
                        )
                        prepared_lane["lane_id"] = (
                            f"{prepared_lane.get('lane_id')}.supplement_{retrieval_round}"
                        )
                        prepared_lane["supplement_terms"] = supplement_terms
                        if supplement_terms:
                            supplemental_query = " ".join(
                                value
                                for value in (
                                    str(prepared_lane.get("query") or "").strip(),
                                    supplement_terms,
                                )
                                if value
                            )
                            prepared_lane["query"] = (
                                supplemental_query
                                if len(supplemental_query) <= 240
                                else supplemental_query[:240].rsplit(" ", 1)[0]
                            )
                        prepared_lane["purpose"] = "coverage_supplement"
                    lanes.append(prepared_lane)
        return lanes

    def _discover_subhypothesis_candidates(
        self,
        subhypotheses: Sequence[Mapping[str, Any]],
        *,
        task_ids_by_subhypothesis: Mapping[str, Sequence[str]] | None = None,
        retrieval_round: int = 0,
    ) -> list[Dict]:
        lanes = self._slot_recovery_task_lanes(
            subhypotheses,
            task_ids_by_subhypothesis=task_ids_by_subhypothesis,
            retrieval_round=retrieval_round,
        )
        min_candidates_before_relaxation = max(
            1,
            int(
                self._work_collector_setting(
                    "min_slot_candidates_before_relaxation", 5
                )
                or 5
            ),
        )
        semantic_fallback_enabled = str(
            self._work_collector_setting(
                "enable_slot_semantic_scholar_fallback", True
            )
        ).strip().lower() not in {"0", "false", "no", "off"}
        lanes_by_task: dict[str, list[Dict]] = {}
        for lane in lanes:
            task_id = str(lane.get("slot_recovery_task_id") or "")
            if task_id:
                lanes_by_task.setdefault(task_id, []).append(lane)

        task_items = list(lanes_by_task.items())
        try:
            configured_workers = int(
                self._work_collector_setting("slot_retrieval_parallel_workers", 4)
                or 4
            )
        except (TypeError, ValueError):
            configured_workers = 4
        parallel_workers = max(1, min(8, configured_workers, len(task_items) or 1))

        def execute_task(
            task_id: str,
            task_lanes: list[Dict],
        ) -> tuple[list[tuple[Mapping[str, Any], list[Dict]]], dict[str, Any]]:
            initial_lanes = [
                lane
                for lane in task_lanes
                if str(lane.get("execution_phase") or "initial").casefold()
                != "relaxed"
            ]
            relaxed_lanes = [
                lane
                for lane in task_lanes
                if str(lane.get("execution_phase") or "initial").casefold()
                == "relaxed"
            ]
            task_results: list[tuple[Mapping[str, Any], list[Dict]]] = []
            for lane in initial_lanes:
                task_results.append(self._execute_slot_recovery_lane(lane))
            initial_merged = self._merge_retrieval_candidates(task_results)
            relaxation_used = False
            if len(initial_merged) < min_candidates_before_relaxation:
                relaxation_used = bool(relaxed_lanes)
                for lane in relaxed_lanes:
                    task_results.append(self._execute_slot_recovery_lane(lane))

            merged_task_candidates = self._merge_retrieval_candidates(task_results)
            fallback_used = False
            if not merged_task_candidates and semantic_fallback_enabled:
                fallback_result = self._execute_slot_semantic_scholar_fallback(task_lanes)
                if fallback_result is not None:
                    task_results.append(fallback_result)
                    fallback_used = True
                    merged_task_candidates = self._merge_retrieval_candidates(task_results)

            summary = self._slot_retrieval_summary(
                task_lanes,
                task_results,
                merged_task_candidates,
                min_candidates_before_relaxation=min_candidates_before_relaxation,
                relaxation_used=relaxation_used,
                fallback_used=fallback_used,
            )
            self.logger.info(
                "SH %s slot %s task %s retrieval summary: raw_candidates_by_lane=%s "
                "merged_unique_candidates=%s zero_result_lanes=%s fallback_used=%s next_action=%s.",
                summary["sub_hypothesis_id"] or "UNSPECIFIED",
                summary["slot_name"] or "UNSPECIFIED",
                task_id,
                summary["raw_candidates_by_lane"],
                summary["merged_unique_candidates"],
                summary["zero_result_lanes"],
                summary["fallback_used"],
                summary["next_action"],
            )

            return task_results, summary

        task_outcomes: list[
            tuple[list[tuple[Mapping[str, Any], list[Dict]]], dict[str, Any]] | None
        ] = [None] * len(task_items)
        if parallel_workers == 1:
            for index, (task_id, task_lanes) in enumerate(task_items):
                task_outcomes[index] = execute_task(task_id, task_lanes)
        else:
            self.logger.info(
                "Starting bounded SH slot retrieval pool: tasks=%s workers=%s.",
                len(task_items),
                parallel_workers,
            )
            with ThreadPoolExecutor(
                max_workers=parallel_workers,
                thread_name_prefix="sh-slot-retrieval",
            ) as executor:
                future_to_index = {
                    executor.submit(execute_task, task_id, task_lanes): index
                    for index, (task_id, task_lanes) in enumerate(task_items)
                }
                for future in as_completed(future_to_index):
                    index = future_to_index[future]
                    task_id, task_lanes = task_items[index]
                    try:
                        task_outcomes[index] = future.result()
                    except Exception as exc:
                        self.logger.warning(
                            "SH slot retrieval task %s failed without aborting other tasks: %s",
                            task_id,
                            exc,
                        )
                        empty_summary = self._slot_retrieval_summary(
                            task_lanes,
                            [],
                            [],
                            min_candidates_before_relaxation=min_candidates_before_relaxation,
                            relaxation_used=False,
                            fallback_used=False,
                        )
                        empty_summary["next_action"] = "task_failed"
                        task_outcomes[index] = ([], empty_summary)

        all_lane_results: list[tuple[Mapping[str, Any], list[Dict]]] = []
        summaries: list[dict[str, Any]] = []
        for outcome in task_outcomes:
            if outcome is None:
                continue
            task_results, summary = outcome
            all_lane_results.extend(task_results)
            summaries.append(summary)

        previous_summaries = getattr(self, "_slot_retrieval_summaries", [])
        history = previous_summaries if isinstance(previous_summaries, list) else []
        self._slot_retrieval_summaries = [
            *history,
            *[
                {**summary, "retrieval_round": retrieval_round}
                for summary in summaries
            ],
        ]
        return self._merge_retrieval_candidates(all_lane_results)

    def _execute_slot_recovery_lane(
        self,
        lane: Mapping[str, Any],
    ) -> tuple[Mapping[str, Any], list[Dict]]:
        cache_enabled = self._sh_retrieval_cache_enabled()
        cache = self._sh_retrieval_lane_cache() if cache_enabled else None
        cache_key = self._sh_retrieval_lane_cache_key(lane) if cache is not None else ""
        refresh_requested = self._sh_retrieval_cache_refresh_requested()

        def cache_hit_entry():
            if cache is None:
                return None
            # A refresh bypasses the pre-existing entry exactly once per key in
            # this collector.  Concurrent duplicate lanes wait for that fresh
            # request and then reuse its result instead of each refreshing it.
            if refresh_requested and not self._sh_retrieval_cache_refresh_completed(cache_key):
                return None
            entry = self._sh_retrieval_cache_get(cache, cache_key)
            if not isinstance(entry, Mapping):
                return None
            if entry.get("schema_version") != self._SH_RETRIEVAL_LANE_CACHE_SCHEMA_VERSION:
                return None
            papers = entry.get("papers")
            if not isinstance(papers, list):
                return None
            return entry

        def cache_metadata(
            *,
            status: str,
            cache_state: str = "",
            entry: Mapping[str, Any] | None = None,
            ttl_seconds: int = 0,
            network_request_made: bool,
        ) -> dict[str, Any]:
            cached_at_epoch = entry.get("cached_at_epoch") if isinstance(entry, Mapping) else None
            provider_status = (
                str(entry.get("provider_status") or "")
                if isinstance(entry, Mapping)
                else ""
            )
            return {
                "schema_version": self._SH_RETRIEVAL_LANE_CACHE_SCHEMA_VERSION,
                "status": status,
                "provider_status": provider_status,
                "state": cache_state,
                "key": cache_key.removeprefix("sh_retrieval_lane:"),
                "cached_at": self._sh_retrieval_cache_timestamp(cached_at_epoch),
                "ttl_seconds": int(ttl_seconds or 0),
                "network_request_made": network_request_made,
            }

        cached_entry = cache_hit_entry()
        if cached_entry is not None:
            papers = deepcopy(cached_entry["papers"])
            cache_info = cache_metadata(
                status="hit",
                cache_state=str(cached_entry.get("state") or "success"),
                entry=cached_entry,
                ttl_seconds=int(cached_entry.get("ttl_seconds") or 0),
                network_request_made=False,
            )
            executed_lane = {
                **lane,
                "source_work_count": len(papers),
                "retrieval_cache": cache_info,
            }
            self.logger.info(
                "SH %s slot %s task %s variant=%s lane %s provider=%s retrieval cache=hit "
                "state=%s cached_at=%s native_filter=%s query=%s returned %s candidates.",
                lane.get("sub_hypothesis_id"),
                lane.get("slot_name"),
                lane.get("slot_recovery_task_id"),
                lane.get("query_variant_id") or "legacy",
                lane.get("lane_id"),
                lane.get("provider") or "UNSPECIFIED",
                cache_info["state"],
                cache_info["cached_at"] or "UNSPECIFIED",
                self._lane_native_filter_for_log(lane),
                self._lane_query_for_log(lane),
                len(papers),
            )
            return executed_lane, papers

        self.logger.info(
            "SH %s slot %s task %s variant=%s lane %s provider=%s retrieval started "
            "discipline_filter_policy=%s native_filter=%s query=%s.",
            lane.get("sub_hypothesis_id"),
            lane.get("slot_name"),
            lane.get("slot_recovery_task_id"),
            lane.get("query_variant_id") or "legacy",
            lane.get("lane_id"),
            lane.get("provider") or "UNSPECIFIED",
            lane.get("discipline_filter_policy") or "broad",
            self._lane_native_filter_for_log(lane),
            self._lane_query_for_log(lane),
        )
        started_at = time.monotonic()

        def execute_and_record() -> tuple[list[Dict], bool, dict[str, Any]]:
            papers, successful, provider_status = self._execute_query_lane_with_status(lane)
            papers = list(papers) if isinstance(papers, list) else []
            if cache is None:
                return papers, successful, cache_metadata(
                    status="disabled" if not cache_enabled else "unavailable",
                    entry={"provider_status": provider_status},
                    network_request_made=True,
                )
            if not successful:
                # An API timeout, 429, or other provider failure is deliberately
                # not represented as a cached zero-result lane.
                return papers, False, cache_metadata(
                    status="not_cached_failure",
                    entry={"provider_status": provider_status},
                    network_request_made=True,
                )
            ttl_seconds = self._sh_retrieval_cache_ttl_seconds(papers)
            state = "success" if papers else "empty"
            entry = {
                "schema_version": self._SH_RETRIEVAL_LANE_CACHE_SCHEMA_VERSION,
                "state": state,
                "provider_status": provider_status,
                "cached_at_epoch": time.time(),
                "ttl_seconds": ttl_seconds,
                "request": self._sh_retrieval_lane_cache_payload(lane),
                # Persist an isolated snapshot because downstream merge attaches
                # SH-specific provenance directly to candidate dictionaries.
                "papers": deepcopy(papers),
            }
            if ttl_seconds > 0:
                if not self._sh_retrieval_cache_set(
                    cache,
                    cache_key,
                    entry,
                    ttl_seconds=ttl_seconds,
                ):
                    return papers, True, cache_metadata(
                        status="not_cached_write_failed",
                        entry=entry,
                        cache_state=state,
                        ttl_seconds=ttl_seconds,
                        network_request_made=True,
                    )
                if refresh_requested:
                    self._mark_sh_retrieval_cache_refresh_completed(cache_key)
                status = "refresh" if refresh_requested else "miss"
                return papers, True, cache_metadata(
                    status=status,
                    entry=entry,
                    cache_state=state,
                    ttl_seconds=ttl_seconds,
                    network_request_made=True,
                )
            return papers, True, cache_metadata(
                status="not_cached_ttl_disabled",
                entry=entry,
                cache_state=state,
                ttl_seconds=ttl_seconds,
                network_request_made=True,
            )

        if cache is None:
            papers, _successful, cache_info = execute_and_record()
        else:
            # Avoid duplicate OpenAlex requests if two independent SH slots
            # compile to the same provider/query/filter request concurrently.
            with self._sh_retrieval_cache_lock(cache_key):
                cached_entry = cache_hit_entry()
                if cached_entry is not None:
                    papers = deepcopy(cached_entry["papers"])
                    cache_info = cache_metadata(
                        status="hit",
                        cache_state=str(cached_entry.get("state") or "success"),
                        entry=cached_entry,
                        ttl_seconds=int(cached_entry.get("ttl_seconds") or 0),
                        network_request_made=False,
                    )
                else:
                    papers, _successful, cache_info = execute_and_record()

        elapsed_seconds = time.monotonic() - started_at
        executed_lane = {
            **lane,
            "source_work_count": len(papers),
            "retrieval_cache": cache_info,
        }
        self.logger.info(
            "SH %s slot %s task %s variant=%s lane %s provider=%s "
            "discipline_filter_policy=%s native_filter=%s query=%s returned %s candidates. "
            "cache=%s cache_state=%s elapsed_seconds=%.2f.",
            lane.get("sub_hypothesis_id"),
            lane.get("slot_name"),
            lane.get("slot_recovery_task_id"),
            lane.get("query_variant_id") or "legacy",
            lane.get("lane_id"),
            lane.get("provider") or "UNSPECIFIED",
            lane.get("discipline_filter_policy") or "broad",
            self._lane_native_filter_for_log(lane),
            self._lane_query_for_log(lane),
            len(papers),
            cache_info["status"],
            cache_info["state"] or "none",
            elapsed_seconds,
        )
        return executed_lane, papers

    def _execute_slot_semantic_scholar_fallback(
        self,
        task_lanes: Sequence[Mapping[str, Any]],
    ) -> tuple[Mapping[str, Any], list[Dict]] | None:
        """Use one short, provenance-bearing fallback only after a slot exhausts lanes."""

        source_lane = next(
            (
                lane
                for lane in task_lanes
                if str(lane.get("lane") or "") == "broad_anchor"
            ),
            task_lanes[0] if task_lanes else None,
        )
        if not isinstance(source_lane, Mapping):
            return None
        semantic_api = getattr(
            getattr(self, "data_manager", None),
            "semantic_scholar_api",
            None,
        )
        if semantic_api is None:
            return None
        query_terms = source_lane.get("query_variant_terms")
        bounded_terms: list[str] = []
        if isinstance(query_terms, Sequence) and not isinstance(query_terms, (str, bytes)):
            word_count = 0
            for raw_term in query_terms:
                term = re.sub(r"\s+", " ", str(raw_term or "").strip())
                if not term:
                    continue
                term_words = len(term.split())
                if bounded_terms and word_count + term_words > 12:
                    continue
                bounded_terms.append(term)
                word_count += term_words
            query = " ".join(bounded_terms)
        else:
            query = ""
        if not query:
            query = str(source_lane.get("query") or "").strip()
        query = query[:240].rsplit(" ", 1)[0] if len(query) > 240 else query
        if not query:
            return None
        fallback_lane = {
            **source_lane,
            "lane_id": f"{source_lane.get('lane_id')}.semantic_scholar_fallback",
            "lane": "semantic_scholar_fallback",
            "provider": "semantic_scholar",
            "query": query,
            "provider_filter": {},
            "hard_filter_applied": False,
            "taxonomy_coverage": "broad",
            "discipline_filter_policy": "broad",
            "execution_phase": "fallback",
            "retrieval_stage": "slot_semantic_scholar_fallback",
            "purpose": "all_slot_provider_lanes_empty_short_query_fallback",
            "fallback_query_source": "query_variant_terms" if bounded_terms else "compiled_lane_query",
            "semantic_scholar_fields": "title,externalIds,openAccessPdf,abstract",
        }
        return self._execute_slot_recovery_lane(fallback_lane)

    def _slot_retrieval_summary(
        self,
        task_lanes: Sequence[Mapping[str, Any]],
        task_results: Sequence[tuple[Mapping[str, Any], Sequence[Mapping[str, Any]]]],
        merged_candidates: Sequence[Mapping[str, Any]],
        *,
        min_candidates_before_relaxation: int,
        relaxation_used: bool,
        fallback_used: bool,
    ) -> dict[str, Any]:
        source_lane = task_lanes[0] if task_lanes else {}
        counts = {
            str(lane.get("lane_id") or lane.get("lane") or "UNSPECIFIED"): len(papers)
            for lane, papers in task_results
        }
        zero_lanes = [lane_id for lane_id, count in counts.items() if count == 0]
        exhausted_variants = self._unique_summary_values(
            [
                lane.get("query_variant_id")
                for lane, papers in task_results
                if not papers and lane.get("query_variant_id")
            ],
            limit=5,
        )
        exhausted_filters = self._unique_summary_values(
            [
                self._lane_native_filter_for_log(lane)
                for lane, papers in task_results
                if not papers and self._lane_native_filter_for_log(lane) != "none"
            ],
            limit=5,
        )
        return {
            "sub_hypothesis_id": str(source_lane.get("sub_hypothesis_id") or ""),
            "slot_name": str(source_lane.get("slot_name") or ""),
            "slot_recovery_task_id": str(source_lane.get("slot_recovery_task_id") or ""),
            "raw_candidates_by_lane": counts,
            "merged_unique_candidates": len(merged_candidates),
            "zero_result_lanes": zero_lanes,
            "exhausted_variants": exhausted_variants if not merged_candidates else [],
            "exhausted_filters": exhausted_filters if not merged_candidates else [],
            "min_candidates_before_relaxation": min_candidates_before_relaxation,
            "relaxation_used": relaxation_used,
            "fallback_used": fallback_used,
            "next_action": (
                "semantic_scholar_short_query_fallback_completed"
                if fallback_used and merged_candidates
                else "semantic_scholar_short_query_fallback_exhausted"
                if fallback_used
                else "none"
                if merged_candidates
                else "semantic_scholar_short_query_fallback_disabled_or_unavailable"
            ),
        }

    @staticmethod
    def _unique_summary_values(values: Sequence[Any], *, limit: int) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()
        for value in values:
            item = str(value or "").strip()
            key = item.casefold()
            if not item or key in seen:
                continue
            seen.add(key)
            result.append(item)
            if len(result) >= limit:
                break
        return result

    @staticmethod
    def _lane_query_for_log(lane: Mapping[str, Any]) -> str:
        """Return the exact one-line query submitted by one retrieval lane."""

        return re.sub(r"\s+", " ", str(lane.get("query") or "")).strip() or "UNSPECIFIED"

    @staticmethod
    def _lane_native_filter_for_log(lane: Mapping[str, Any]) -> str:
        """Expose a provider-native filter alongside its query for auditability."""

        provider_filter = lane.get("provider_filter")
        if not isinstance(provider_filter, Mapping):
            return "none"
        return re.sub(
            r"\s+",
            " ",
            str(provider_filter.get("filter") or provider_filter.get("category") or ""),
        ).strip() or "none"

    def _limit_subhypothesis_discovery_candidates(
        self,
        papers: Sequence[Mapping[str, Any]],
        subhypotheses: Sequence[Mapping[str, Any]],
    ) -> list[Dict]:
        max_unique_papers = int(
            self._work_collector_setting("subhypothesis_max_unique_papers", 6)
        )
        if max_unique_papers <= 0:
            return [dict(paper) for paper in papers if isinstance(paper, Mapping)]
        selected_indices: list[int] = []
        selected = set()
        for subhypothesis in subhypotheses:
            subhypothesis_id = str(subhypothesis.get("sub_hypothesis_id") or "")
            candidates = []
            for index, paper in enumerate(papers):
                if not isinstance(paper, Mapping):
                    continue
                records = paper.get("retrieval_provenance")
                task_ids = [
                    str(record.get("slot_recovery_task_id") or "")
                    for record in (records if isinstance(records, list) else [])
                    if isinstance(record, Mapping)
                    if str(record.get("sub_hypothesis_id") or "") == subhypothesis_id
                ]
                if task_ids:
                    candidates.append((index, task_ids))
            per_subhypothesis_selected: list[int] = []
            task_ids = [
                str(task.get("task_id") or "")
                for task in subhypothesis.get("slot_recovery_tasks", [])
                if isinstance(task, Mapping)
            ]
            for task_id in task_ids:
                if len(per_subhypothesis_selected) >= max_unique_papers:
                    break
                for index, candidate_task_ids in candidates:
                    if index not in per_subhypothesis_selected and task_id in candidate_task_ids:
                        per_subhypothesis_selected.append(index)
                        break
            for index, _task_ids in candidates:
                if len(per_subhypothesis_selected) >= max_unique_papers:
                    break
                if index not in per_subhypothesis_selected:
                    per_subhypothesis_selected.append(index)
            for index in per_subhypothesis_selected:
                if index not in selected:
                    selected.add(index)
                    selected_indices.append(index)
        return [dict(papers[index]) for index in selected_indices]

    def collect_subhypothesis_candidates(self, subhypotheses, topic: str = "") -> Dict[str, List[Dict]]:
        """Run slot-recovery task lanes and preserve task-level provenance."""

        plan = self.build_subhypothesis_retrieval_plan(subhypotheses, topic)
        valid_subhypotheses = self._valid_subhypotheses(plan)
        results: Dict[str, List[Dict]] = {}
        for subhypothesis in valid_subhypotheses:
            subhypothesis_id = str(subhypothesis.get("sub_hypothesis_id") or "")
            if subhypothesis_id:
                results[subhypothesis_id] = self._discover_subhypothesis_candidates(
                    [subhypothesis],
                )
        return results

    @property
    def _openalex_graph_schema_version(self):
        return int(
            getattr(self.config.APIInfo, "openalex_graph_cache_schema_version", 2) or 2
        )

    def _load_openalex_reference_graph(self):
        if not os.path.exists(self.reference_graph_path):
            return None
        try:
            with open(self.reference_graph_path, "rb") as reader:
                reference_graph = pickle.load(reader)
        except Exception as exc:
            self.logger.warning("Unable to load cached reference graph: %s", exc)
            return None

        graph_metadata = getattr(reference_graph, "graph", {})
        if (
            not isinstance(reference_graph, nx.DiGraph)
            or graph_metadata.get("provider") != self._OPENALEX_GRAPH_PROVIDER
            or graph_metadata.get("schema_version") != self._openalex_graph_schema_version
        ):
            self.logger.info(
                "Ignoring a legacy reference graph cache; rebuilding the OpenAlex graph."
            )
            return None
        return reference_graph

    def _get_embedding_model(self):
        """Lazy load and cache the embedding model - 委托给 data_manager"""
        if self._embedding_model is not None:
            return self._embedding_model
        
        model_name = self.config.ModuleInfo.WorkCollector.sentence_transformer_model
        try:
            self._embedding_model, self._model_device = load_sentence_transformer_auto(
                model_name,
                logger=self.logger,
            )
        except Exception as e:
            if "out of memory" in str(e).lower():
                self.logger.error("Out of memory error detected. Using CPU instead.")
                try:
                    torch.cuda.empty_cache()
                    gc.collect()
                except Exception:
                    self.logger.warning("Failed to clear GPU cache.")
                    pass
                self._embedding_model, self._model_device = load_sentence_transformer_auto(
                    model_name,
                    logger=self.logger,
                )
            else:
                try:
                    self._embedding_model, self._model_device = load_sentence_transformer_auto(
                        model_name,
                        logger=self.logger,
                    )
                except Exception as e2:
                    self.logger.error(f"Failed to load SentenceTransformer model: {e2}")
                    raise e2
        
        return self._embedding_model

    # ========== 委托给 DataManager 的函数 ==========
    
    def filter_seed_papers(
        self,
        topic: str,
        papers: List[Dict],
        threshold: int = 4,
        research_context: Dict = None,
        retain_all: bool = False,
        retain_deferred_if_accepted_below: int | None = None,
    ) -> List[Dict]:
        if not papers:
            return []

        research_context = research_context or self.get_project_research_context(topic)
        research_context_json = json.dumps(
            relevance_context_payload(research_context),
            ensure_ascii=False,
        )

        self.logger.info(f"Filtering {len(papers)} candidate seed papers using LLM (Threshold >= {threshold})...")
        
        tasks = []
        for paper in papers:
            title = paper.get("title", "N/A")
            abstract = paper.get("abstract", "")
            
            prompt = SEED_PAPER_SELECTION.format(
                topic=topic,
                research_context=research_context_json,
                title=title,
                abstract=abstract if abstract else "Abstract not available."
            )
            tasks.append(prompt)

        responses = self.chat_agent.batch_remote_chat(
            tasks,
            temperature=0.0, 
            desc="Filtering Seed Papers"
        )

        decisions: list[tuple[Dict, str, int | None, str]] = []
        accepted_count = 0
        for paper, response in zip(papers, responses):
            try:
                result = extract_json(response)
                score = int(result.get("relevance_score", 0))
                reason = result.get("reason", "No reason provided")
                paper["project_relevance"] = {
                    "relevance_score": score,
                    "project_fit": str(result.get("project_fit") or ""),
                    "matched_anchors": result.get("matched_anchors")
                    if isinstance(result.get("matched_anchors"), list)
                    else [],
                    "violated_exclusions": result.get("violated_exclusions")
                    if isinstance(result.get("violated_exclusions"), list)
                    else [],
                    "reason": str(reason),
                    "research_context_fingerprint": research_context.get("input_fingerprint", ""),
                }
                if score >= threshold:
                    decisions.append((paper, "accepted", score, str(reason)))
                    accepted_count += 1
                else:
                    decisions.append((paper, "deferred", score, str(reason)))
            except Exception as e:
                self.logger.warning(f"Error parsing LLM response for paper {paper.get('title')}: {e}")
                decisions.append((paper, "unavailable", None, str(e)))

        retain_deferred = retain_all
        accepted_capacity = max(0, int(retain_deferred_if_accepted_below or 0))
        if retain_all and accepted_capacity:
            retain_deferred = accepted_count < accepted_capacity
            self.logger.info(
                "Project relevance capacity decision: accepted_candidates=%s "
                "required_seed_budget=%s deferred_candidates=%s policy=%s.",
                accepted_count,
                accepted_capacity,
                sum(1 for _paper, decision, _score, _reason in decisions if decision == "deferred"),
                "retain_for_SH_assessment" if retain_deferred else "reject_before_SH_assessment",
            )

        valid_papers = []
        for paper, decision, score, reason in decisions:
            title = paper.get("title", "Unknown Title")
            if decision == "accepted":
                self.logger.info(f"✅ Accepted Seed Paper: [{score}] {title}")
                if self.config.BasicInfo.debug:
                    self.logger.info(f"   Reason: {reason}")
                valid_papers.append(paper)
                continue
            if decision == "deferred":
                if retain_deferred:
                    self.logger.info(f"⏳ Deferred SH Candidate: [{score}] {title} - {reason}")
                    valid_papers.append(paper)
                else:
                    self.logger.info(
                        "❌ Rejected Deferred SH Candidate: [%s] %s - %s "
                        "(accepted project-relevant pool already meets seed budget).",
                        score,
                        title,
                        reason,
                    )
                continue
            if retain_deferred:
                # When high-confidence candidates are still scarce, a transient
                # model/schema failure must not erase an SH-specific candidate.
                self.logger.info(
                    "⏳ Deferred Unassessed SH Candidate: %s - project relevance "
                    "response unavailable; retained because accepted capacity is insufficient.",
                    title,
                )
                valid_papers.append(paper)
            else:
                self.logger.info(
                    "❌ Rejected Unassessed SH Candidate: %s - project relevance "
                    "response unavailable and accepted pool already meets seed budget.",
                    title,
                )

        self.logger.info(f"Seed paper filtering complete. Retained {len(valid_papers)}/{len(papers)} papers.")
        return valid_papers

    _SH_SEMANTIC_ASSESSMENT_SCHEMA_VERSION = "sh_paper_semantic_assessment_v1"
    _SH_RELATION_TYPES = frozenset(
        {
            "direct",
            "partial",
            "indirect",
            "boundary",
            "counterevidence",
            "background",
            "method",
            "hypothesis_generating",
            "uncertain",
            "irrelevant",
        }
    )
    _SH_GRAPH_ROLES = frozenset(
        {"evidence_seed", "exploration_seed", "context_seed", "do_not_expand"}
    )
    _SH_CONTRIBUTION_TYPES = frozenset(
        {
            "DIRECT_EVIDENCE",
            "PARTIAL_EVIDENCE",
            "INDIRECT_EVIDENCE",
            "MECHANISTIC_EVIDENCE",
            "COMPARATIVE_EVIDENCE",
            "BOUNDARY_EVIDENCE",
            "COUNTEREVIDENCE",
            "BACKGROUND_CONTEXT",
            "METHOD_OR_MEASUREMENT",
            "HYPOTHESIS_GENERATING",
        }
    )

    def _sh_paper_semantic_assessment_enabled(self) -> bool:
        """Whether this collector can ask the LLM for paper-to-SH semantics."""

        configured = self._work_collector_setting(
            "enable_sh_paper_semantic_assessment",
            True,
        )
        enabled = str(configured).strip().casefold() not in {"0", "false", "no", "off"}
        # WorkCollector instances created through __init__ always have a ChatAgent.
        # The guard keeps lightweight, legacy unit fixtures deterministic.
        return enabled and getattr(self, "chat_agent", None) is not None

    def _sh_paper_semantic_cache_enabled(self) -> bool:
        configured = self._work_collector_setting(
            "sh_paper_semantic_assessment_cache_enabled",
            True,
        )
        return str(configured).strip().casefold() not in {"0", "false", "no", "off"}

    @staticmethod
    def _assessment_text_list(value: Any, *, limit: int = 12) -> list[str]:
        values = value if isinstance(value, (list, tuple, set)) else [value]
        result: list[str] = []
        seen: set[str] = set()
        for raw in values:
            text = re.sub(r"\s+", " ", str(raw or "").strip())[:500]
            key = text.casefold()
            if not text or key in seen:
                continue
            seen.add(key)
            result.append(text)
            if len(result) >= limit:
                break
        return result

    @staticmethod
    def _paper_semantic_identity(paper: Mapping[str, Any]) -> str:
        for key in ("openalex_id", "paperId", "paper_id", "doi"):
            value = str(paper.get(key) or "").strip()
            if value:
                return value
        external_ids = paper.get("externalIds")
        if isinstance(external_ids, Mapping):
            for key in ("DOI", "doi", "ArXiv", "arXiv"):
                value = str(external_ids.get(key) or "").strip()
                if value:
                    return value
        return re.sub(r"\W+", "", str(paper.get("title") or "").casefold()) or "unknown-paper"

    @staticmethod
    def _normalised_span_text(value: Any) -> str:
        return " ".join(str(value or "").casefold().split())

    def _semantic_assessment_cache_key(
        self,
        paper: Mapping[str, Any],
        subhypothesis: Mapping[str, Any],
        research_context: Mapping[str, Any],
    ) -> str:
        payload = {
            "schema_version": self._SH_SEMANTIC_ASSESSMENT_SCHEMA_VERSION,
            "project_context_fingerprint": str(research_context.get("input_fingerprint") or ""),
            "paper_identity": self._paper_semantic_identity(paper),
            "title": str(paper.get("title") or ""),
            "abstract": str(paper.get("abstract") or ""),
            "venue": str(paper.get("venue") or ""),
            "year": str(paper.get("year") or paper.get("publication_year") or ""),
            "sub_hypothesis_id": str(subhypothesis.get("sub_hypothesis_id") or ""),
            "question": str(subhypothesis.get("question") or ""),
            "slot_recovery_tasks": list(subhypothesis.get("slot_recovery_tasks") or []),
        }
        return get_hash(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str))

    @staticmethod
    def _subhypothesis_prompt_payload(subhypothesis: Mapping[str, Any]) -> dict[str, Any]:
        slots = []
        for task in subhypothesis.get("slot_recovery_tasks", []):
            if not isinstance(task, Mapping):
                continue
            definition = task.get("slot_definition")
            definition_data = dict(definition) if isinstance(definition, Mapping) else {}
            slots.append(
                {
                    "slot_name": str(task.get("slot_name") or ""),
                    "meaning": str(definition_data.get("meaning") or ""),
                    "retrieval_concepts": list(definition_data.get("retrieval_concepts") or []),
                    "expected_evidence_role": str(task.get("expected_evidence_role") or ""),
                }
            )
        return {
            "sub_hypothesis_id": str(subhypothesis.get("sub_hypothesis_id") or ""),
            "question": str(subhypothesis.get("question") or ""),
            "question_kind": str(subhypothesis.get("question_kind") or ""),
            "research_role": str(subhypothesis.get("research_role") or ""),
            "scientific_scope": dict(subhypothesis.get("scientific_scope") or {}),
            "exclusion_terms": list(subhypothesis.get("exclusion_terms") or []),
            "optional_candidate_slots": slots,
        }

    @staticmethod
    def _candidate_subhypotheses_for_paper(
        paper: Mapping[str, Any],
        subhypotheses: Sequence[Mapping[str, Any]],
    ) -> list[dict[str, Any]]:
        by_id = {
            str(item.get("sub_hypothesis_id") or ""): dict(item)
            for item in subhypotheses
            if isinstance(item, Mapping) and item.get("sub_hypothesis_id")
        }
        linked_ids: list[str] = []
        for record in paper.get("retrieval_provenance", []):
            if not isinstance(record, Mapping):
                continue
            subhypothesis_id = str(record.get("sub_hypothesis_id") or "")
            if subhypothesis_id in by_id and subhypothesis_id not in linked_ids:
                linked_ids.append(subhypothesis_id)
        # A fallback candidate may lack lane provenance. Assess it against the
        # configured SHs rather than losing a potentially useful semantic bridge.
        return [by_id[item] for item in linked_ids] if linked_ids else list(by_id.values())

    def _normalise_sh_semantic_assessment(
        self,
        raw: Any,
        *,
        paper: Mapping[str, Any],
        subhypothesis: Mapping[str, Any],
        research_context: Mapping[str, Any],
        cache_key: str,
        status: str = "assessed",
        assessment_source: str = "llm_sh_semantic",
        additional_evidence_sources: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        result = dict(raw) if isinstance(raw, Mapping) else {}
        try:
            score = max(0, min(5, int(result.get("semantic_relevance_score", 0))))
        except (TypeError, ValueError):
            score = 0
        relation = str(result.get("overall_relation") or "uncertain").strip().casefold()
        if relation not in self._SH_RELATION_TYPES:
            relation = "uncertain"
        graph_role = str(result.get("recommended_graph_role") or "do_not_expand").strip().casefold()
        if graph_role not in self._SH_GRAPH_ROLES:
            graph_role = "do_not_expand"
        confidence = str(result.get("confidence") or "low").strip().casefold()
        if confidence not in {"high", "medium", "low"}:
            confidence = "low"

        available_slots = {
            str(task.get("slot_name") or "")
            for task in subhypothesis.get("slot_recovery_tasks", [])
            if isinstance(task, Mapping) and task.get("slot_name")
        }
        slot_contributions: list[dict[str, str]] = []
        for raw_slot in result.get("candidate_slot_contributions", []):
            if not isinstance(raw_slot, Mapping):
                continue
            slot_name = str(raw_slot.get("slot_name") or "").strip()
            level = str(raw_slot.get("support_level") or "none").strip().casefold()
            if slot_name not in available_slots or level not in {"direct", "partial", "indirect", "none"}:
                continue
            slot_contributions.append(
                {
                    "slot_name": slot_name,
                    "support_level": level,
                    "reason": re.sub(r"\s+", " ", str(raw_slot.get("reason") or "").strip())[:500],
                }
            )

        source_texts = {
            "title": self._normalised_span_text(paper.get("title")),
            "abstract": self._normalised_span_text(paper.get("abstract")),
        }
        for raw_source, raw_text in (additional_evidence_sources or {}).items():
            source = str(raw_source or "").strip().casefold()
            text = self._normalised_span_text(raw_text)
            if source and text:
                source_texts[source] = text
        evidence_spans: list[dict[str, str]] = []
        ungrounded_span_count = 0
        for raw_span in result.get("evidence_spans", []):
            if not isinstance(raw_span, Mapping):
                continue
            source = str(raw_span.get("source") or "").strip().casefold()
            text = re.sub(r"\s+", " ", str(raw_span.get("text") or "").strip())[:700]
            source_text = source_texts.get(source, "")
            if not text or not source_text or self._normalised_span_text(text) not in source_text:
                ungrounded_span_count += 1
                continue
            evidence_spans.append(
                {
                    "source": source,
                    "text": text,
                    "interpretation": re.sub(
                        r"\s+", " ", str(raw_span.get("interpretation") or "").strip()
                    )[:500],
                }
            )

        contribution_types = [
            value
            for value in self._assessment_text_list(result.get("contribution_types"))
            if value in self._SH_CONTRIBUTION_TYPES
        ]
        return {
            "schema_version": self._SH_SEMANTIC_ASSESSMENT_SCHEMA_VERSION,
            "assessment_source": str(assessment_source or "llm_sh_semantic"),
            "assessment_status": status,
            "sub_hypothesis_id": str(subhypothesis.get("sub_hypothesis_id") or ""),
            "semantic_relevance_score": score,
            "overall_relation": relation,
            "contribution_types": list(dict.fromkeys(contribution_types)),
            "candidate_slot_contributions": slot_contributions,
            "supported_minimal_claims": self._assessment_text_list(
                result.get("supported_minimal_claims")
            ),
            "claim_limits": self._assessment_text_list(result.get("claim_limits")),
            "evidence_spans": evidence_spans,
            "ungrounded_evidence_span_count": ungrounded_span_count,
            "scope_conflicts": self._assessment_text_list(result.get("scope_conflicts")),
            "explicit_exclusion_matches": self._assessment_text_list(
                result.get("explicit_exclusion_matches")
            ),
            "recommended_graph_role": graph_role,
            "confidence": confidence,
            "reason": re.sub(r"\s+", " ", str(result.get("reason") or "").strip())[:800],
            "research_context_fingerprint": str(research_context.get("input_fingerprint") or ""),
            "cache_key": cache_key,
        }

    def assess_papers_against_subhypotheses(
        self,
        papers: Sequence[Mapping[str, Any]],
        subhypotheses: Sequence[Mapping[str, Any]],
        research_context: Mapping[str, Any],
    ) -> list[Dict]:
        """Attach grounded LLM semantic assessments without discarding candidates.

        This is intentionally a contribution classifier, not a causal-chain or
        all-slot contract validator. Scope/exclusion checks remain available to
        later consumers, while related partial and exploratory evidence survives.
        """

        output = [dict(paper) for paper in papers if isinstance(paper, Mapping)]
        if not output or not self._sh_paper_semantic_assessment_enabled():
            return output

        cache = getattr(self, "sh_paper_semantic_assessment_cache", None)
        cache_enabled = self._sh_paper_semantic_cache_enabled() and cache is not None
        pending: list[tuple[int, dict[str, Any], str]] = []
        assessment_maps: list[dict[str, dict[str, Any]]] = []
        pair_count_by_subhypothesis: dict[str, int] = {}
        cache_hit_count = 0
        context_payload = json.dumps(
            relevance_context_payload(research_context),
            ensure_ascii=False,
        )

        for paper_index, paper in enumerate(output):
            assessments = {
                str(item.get("sub_hypothesis_id") or ""): dict(item)
                for item in paper.get("sh_semantic_assessments", [])
                if isinstance(item, Mapping) and item.get("sub_hypothesis_id")
            }
            assessment_maps.append(assessments)
            for subhypothesis in self._candidate_subhypotheses_for_paper(paper, subhypotheses):
                subhypothesis_id = str(subhypothesis.get("sub_hypothesis_id") or "")
                if not subhypothesis_id:
                    continue
                pair_count_by_subhypothesis[subhypothesis_id] = (
                    pair_count_by_subhypothesis.get(subhypothesis_id, 0) + 1
                )
                cache_key = self._semantic_assessment_cache_key(
                    paper,
                    subhypothesis,
                    research_context,
                )
                cached = None
                if cache_enabled:
                    try:
                        cached = cache.get(cache_key)
                    except (AttributeError, OSError, ValueError):
                        cached = None
                if isinstance(cached, Mapping):
                    assessment = dict(cached)
                    assessment["cache_status"] = "hit"
                    assessments[subhypothesis_id] = assessment
                    cache_hit_count += 1
                    continue

                metadata = {
                    key: paper.get(key)
                    for key in ("venue", "year", "publication_year", "publication_type", "source_type")
                    if paper.get(key) not in (None, "")
                }
                replacements = {
                    "{research_context}": context_payload,
                    "{subhypothesis}": json.dumps(
                        self._subhypothesis_prompt_payload(subhypothesis),
                        ensure_ascii=False,
                    ),
                    "{title}": str(paper.get("title") or "Title not available."),
                    "{abstract}": str(paper.get("abstract") or "Abstract not available."),
                    "{metadata}": json.dumps(metadata, ensure_ascii=False),
                }
                prompt = SH_PAPER_SEMANTIC_ASSESSMENT
                for marker, replacement in replacements.items():
                    prompt = prompt.replace(marker, replacement)
                pending.append((paper_index, subhypothesis, cache_key, prompt))

        pair_distribution = "|".join(
            f"{subhypothesis_id}:{pair_count_by_subhypothesis[subhypothesis_id]}"
            for subhypothesis_id in sorted(pair_count_by_subhypothesis)
        ) or "none"
        self.logger.info(
            "Preparing SH semantic assessment: candidate_papers=%s "
            "candidate_subhypotheses=%s paper_SH_pairs=%s remote_LLM_pairs=%s "
            "cache_hits=%s pairs_by_SH=%s.",
            len(output),
            len(pair_count_by_subhypothesis),
            sum(pair_count_by_subhypothesis.values()),
            len(pending),
            cache_hit_count,
            pair_distribution,
        )
        if pending:
            responses = self.chat_agent.batch_remote_chat(
                [item[3] for item in pending],
                temperature=0.0,
                desc="Assessing Paper-SH Semantics",
            )
            for task_index, (paper_index, subhypothesis, cache_key, _prompt) in enumerate(pending):
                paper = output[paper_index]
                response = responses[task_index] if task_index < len(responses) else None
                try:
                    result = extract_json(response)
                    assessment = self._normalise_sh_semantic_assessment(
                        result,
                        paper=paper,
                        subhypothesis=subhypothesis,
                        research_context=research_context,
                        cache_key=cache_key,
                    )
                except Exception as exc:
                    self.logger.warning(
                        "Unable to parse SH semantic assessment for paper %s / %s: %s",
                        paper.get("title") or "Unknown Title",
                        subhypothesis.get("sub_hypothesis_id") or "Unknown SH",
                        exc,
                    )
                    assessment = self._normalise_sh_semantic_assessment(
                        {},
                        paper=paper,
                        subhypothesis=subhypothesis,
                        research_context=research_context,
                        cache_key=cache_key,
                        status="unavailable",
                    )
                assessment["cache_status"] = "miss"
                assessment_maps[paper_index][assessment["sub_hypothesis_id"]] = assessment
                if cache_enabled:
                    try:
                        cache[cache_key] = dict(assessment)
                    except (AttributeError, OSError, ValueError):
                        self.logger.warning("Unable to persist SH semantic assessment cache entry.")

        for paper, assessments in zip(output, assessment_maps):
            paper["sh_semantic_assessments"] = [
                assessments[subhypothesis_id]
                for subhypothesis_id in sorted(assessments)
            ]
        return output

    def _fulltext_expanded_promotion_enabled(self) -> bool:
        """Whether read citation-expanded papers may earn an independent role."""

        configured = self._work_collector_setting(
            "enable_fulltext_expanded_promotion",
            True,
        )
        return str(configured).strip().casefold() not in {"0", "false", "no", "off"}

    def _writing_paper_limit_per_sh(self) -> int:
        module_info = getattr(getattr(self, "config", None), "ModuleInfo", None)
        survey_generator = getattr(module_info, "SurveyGenerator", None)
        configured = getattr(survey_generator, "writing_max_papers_per_sh", None)
        if configured is None:
            # Compatibility fallback for existing external overrides that may
            # have placed this shared writing budget under WorkCollector.
            configured = self._work_collector_setting("writing_max_papers_per_sh", 20)
        try:
            return max(1, int(configured))
        except (TypeError, ValueError):
            return 20

    def _expanded_promotion_candidate_limit(self, deficit: int) -> int:
        """Bound assessment cost while trying more candidates than the SH deficit."""

        try:
            multiplier = max(
                1,
                int(
                    self._work_collector_setting(
                        "expanded_fulltext_promotion_candidate_multiplier",
                        2,
                    )
                ),
            )
        except (TypeError, ValueError):
            multiplier = 2
        try:
            per_sh_cap = max(
                1,
                int(
                    self._work_collector_setting(
                        "expanded_fulltext_promotion_max_candidates_per_sh",
                        40,
                    )
                ),
            )
        except (TypeError, ValueError):
            per_sh_cap = 40
        return min(per_sh_cap, max(0, deficit) * multiplier)

    def _fulltext_promotion_cache_key(
        self,
        *,
        paper_id: str,
        keynote: Any,
        subhypothesis: Mapping[str, Any],
        research_context: Mapping[str, Any],
    ) -> str:
        payload = {
            "schema_version": "fulltext_expanded_promotion_assessment_v1",
            "project_context_fingerprint": str(
                research_context.get("input_fingerprint") or ""
            ),
            "paper_id": canonical_paper_id(paper_id),
            "complete_section_keynote": keynote,
            "sub_hypothesis_id": str(subhypothesis.get("sub_hypothesis_id") or ""),
            "question": str(subhypothesis.get("question") or ""),
            "slot_recovery_tasks": list(subhypothesis.get("slot_recovery_tasks") or []),
        }
        return get_hash(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str))

    @staticmethod
    def _fulltext_promotion_metadata(
        paper_id: str,
        node: Mapping[str, Any] | None,
    ) -> dict[str, Any]:
        node_data = dict(node) if isinstance(node, Mapping) else {}
        return {
            "paper_id": str(paper_id or ""),
            "title": str(node_data.get("title") or ""),
            "year": node_data.get("year"),
            "venue": str(node_data.get("venue") or ""),
            "doi": str(node_data.get("doi") or ""),
            "provider": str(node_data.get("provider") or ""),
        }

    def _fulltext_promotion_baseline_ids(
        self,
        *,
        provenance: Mapping[str, Any],
        coverage_ledger: Mapping[str, Any],
        subhypothesis_ids: set[str],
    ) -> dict[str, set[str]]:
        """Count non-expanded papers already eligible for a bounded SH plan."""

        output = {subhypothesis_id: set() for subhypothesis_id in subhypothesis_ids}
        for raw_report in coverage_ledger.get("subhypotheses", []):
            report = dict(raw_report) if isinstance(raw_report, Mapping) else {}
            subhypothesis_id = str(report.get("sub_hypothesis_id") or "").strip()
            if subhypothesis_id not in output:
                continue
            slot_ledger = report.get("slot_ledger")
            for raw_slot in (
                slot_ledger.values() if isinstance(slot_ledger, Mapping) else []
            ):
                slot = dict(raw_slot) if isinstance(raw_slot, Mapping) else {}
                for key in ("covered_by", "background_only_by"):
                    for raw_paper in slot.get(key, []):
                        paper = dict(raw_paper) if isinstance(raw_paper, Mapping) else {}
                        identifier = canonical_paper_id(paper.get("paper_id"))
                        if identifier:
                            output[subhypothesis_id].add(identifier)

        project_id = str(provenance.get("project_id") or "").strip()
        fingerprint = str(provenance.get("project_context_fingerprint") or "").strip()
        for raw_paper_id, raw_annotations in (provenance.get("paper_annotations") or {}).items():
            identifier = canonical_paper_id(raw_paper_id)
            if not identifier or not isinstance(raw_annotations, Sequence) or isinstance(
                raw_annotations, (str, bytes)
            ):
                continue
            for raw_annotation in raw_annotations:
                annotation = (
                    dict(raw_annotation) if isinstance(raw_annotation, Mapping) else {}
                )
                if (
                    annotation.get("project_id") != project_id
                    or annotation.get("project_context_fingerprint") != fingerprint
                    or str(annotation.get("association_stage") or "")
                    == FULLTEXT_PROMOTION_STAGE
                ):
                    continue
                subhypothesis_id = str(annotation.get("sub_hypothesis_id") or "").strip()
                mode = str(annotation.get("evidence_use_mode") or "").strip()
                if subhypothesis_id in output and mode in {
                    "DIRECT_LEDGER_EVIDENCE",
                    "QUALIFIED_SH_CONTRIBUTION",
                    "BACKGROUND_CONTEXT",
                }:
                    output[subhypothesis_id].add(identifier)
        return output

    def select_complete_section_upgrade_candidates(
        self,
        selected_fulltext_paper_ids: Sequence[str] | None,
    ) -> dict[str, Any]:
        """Select the bounded graph-expansion papers that need a provenance upgrade.

        A citation-expanded paper may be promoted only after complete-section
        reading.  This selector deliberately starts with *this run's* global
        full-text selection, rather than all graph neighbours, and applies the
        same SH deficit and per-SH assessment bound used by promotion.  The
        caller is responsible for checking the keynote-cache provenance and
        parsed-Markdown availability before forcing a reread.
        """

        result: dict[str, Any] = {
            "enabled": self._fulltext_expanded_promotion_enabled(),
            "selected_fulltext_paper_count": 0,
            "eligible_candidate_pairs": 0,
            "eligible_unique_paper_ids": 0,
            "candidate_pairs": [],
            "deficit_by_sh": {},
            "skipped_reason": "",
        }
        if not result["enabled"]:
            result["skipped_reason"] = "disabled_by_configuration"
            return result

        raw_selected_ids = list(
            dict.fromkeys(
                str(paper_id).strip()
                for paper_id in (selected_fulltext_paper_ids or [])
                if str(paper_id).strip()
            )
        )
        selected_by_identity = {
            canonical_paper_id(paper_id): paper_id
            for paper_id in raw_selected_ids
            if canonical_paper_id(paper_id)
        }

        # The launcher passes `expanded_paper_ids`, which are the output of
        # the global full-text budget.  Intersecting with the collector's
        # runtime budget state protects against callers passing arbitrary
        # graph neighbours or stale paper lists.
        configured_selected = {
            canonical_paper_id(paper_id)
            for paper_id in getattr(self, "selected_fulltext_paper_ids", set()) or set()
            if canonical_paper_id(paper_id)
        }
        if not configured_selected:
            budget_plan = getattr(self, "fulltext_budget_plan", {})
            budget_records = (
                budget_plan.get("selected_for_fulltext", [])
                if isinstance(budget_plan, Mapping)
                else []
            )
            configured_selected = {
                canonical_paper_id(record.get("paper_id"))
                for record in budget_records
                if isinstance(record, Mapping)
                and canonical_paper_id(record.get("paper_id"))
            }
        # Lightweight callers constructed outside the normal launcher do not
        # have a runtime budget object.  Their explicit argument is already
        # the intended selected scope, so preserve that compatibility.
        if configured_selected:
            selected_by_identity = {
                identifier: paper_id
                for identifier, paper_id in selected_by_identity.items()
                if identifier in configured_selected
            }
        if not selected_by_identity:
            result["skipped_reason"] = "no_current_selected_fulltext_papers"
            return result
        result["selected_fulltext_paper_count"] = len(selected_by_identity)

        provenance = getattr(self, "sh_graph_provenance_artifact", {})
        retrieval = getattr(self, "subhypothesis_retrieval_artifact", {})
        if not isinstance(provenance, Mapping):
            provenance = self._basic_info_value("sh_graph_provenance", {})
        if not isinstance(retrieval, Mapping):
            retrieval = self._basic_info_value("subhypothesis_retrieval", {})
        provenance = dict(provenance) if isinstance(provenance, Mapping) else {}
        retrieval = dict(retrieval) if isinstance(retrieval, Mapping) else {}
        if provenance.get("schema_version") != SH_GRAPH_PROVENANCE_SCHEMA_VERSION:
            result["skipped_reason"] = "missing_sh_graph_provenance"
            return result

        plan = retrieval.get("plan")
        plan = dict(plan) if isinstance(plan, Mapping) else {}
        subhypotheses = self._valid_subhypotheses(plan)
        by_sh_contract = {
            str(subhypothesis.get("sub_hypothesis_id") or "").strip(): dict(subhypothesis)
            for subhypothesis in subhypotheses
            if str(subhypothesis.get("sub_hypothesis_id") or "").strip()
        }
        if not by_sh_contract:
            result["skipped_reason"] = "missing_valid_subhypothesis_contracts"
            return result

        coverage_ledger = retrieval.get("evidence_coverage_ledger_final")
        coverage_ledger = (
            dict(coverage_ledger) if isinstance(coverage_ledger, Mapping) else {}
        )
        baseline_by_sh = self._fulltext_promotion_baseline_ids(
            provenance=provenance,
            coverage_ledger=coverage_ledger,
            subhypothesis_ids=set(by_sh_contract),
        )
        existing_promoted_by_sh: dict[str, set[str]] = {
            subhypothesis_id: set() for subhypothesis_id in by_sh_contract
        }
        project_id = str(provenance.get("project_id") or "").strip()
        fingerprint = str(provenance.get("project_context_fingerprint") or "").strip()
        annotations_by_paper = provenance.get("paper_annotations") or {}
        for raw_paper_id, raw_annotations in annotations_by_paper.items():
            identifier = canonical_paper_id(raw_paper_id)
            if not identifier or not isinstance(raw_annotations, Sequence) or isinstance(
                raw_annotations, (str, bytes)
            ):
                continue
            for raw_annotation in raw_annotations:
                annotation = (
                    dict(raw_annotation) if isinstance(raw_annotation, Mapping) else {}
                )
                subhypothesis_id = str(annotation.get("sub_hypothesis_id") or "").strip()
                if (
                    subhypothesis_id in existing_promoted_by_sh
                    and annotation.get("project_id") == project_id
                    and annotation.get("project_context_fingerprint") == fingerprint
                    and str(annotation.get("association_stage") or "")
                    == FULLTEXT_PROMOTION_STAGE
                    and str(annotation.get("evidence_use_mode") or "")
                    in {
                        "DIRECT_LEDGER_EVIDENCE",
                        "QUALIFIED_SH_CONTRIBUTION",
                        "BACKGROUND_CONTEXT",
                    }
                ):
                    existing_promoted_by_sh[subhypothesis_id].add(identifier)

        candidates_by_sh: dict[str, dict[str, dict[str, Any]]] = {
            subhypothesis_id: {} for subhypothesis_id in by_sh_contract
        }
        for raw_paper_id, raw_annotations in annotations_by_paper.items():
            identifier = canonical_paper_id(raw_paper_id)
            if (
                identifier not in selected_by_identity
                or not isinstance(raw_annotations, Sequence)
                or isinstance(raw_annotations, (str, bytes))
            ):
                continue
            for raw_annotation in raw_annotations:
                annotation = (
                    dict(raw_annotation) if isinstance(raw_annotation, Mapping) else {}
                )
                subhypothesis_id = str(annotation.get("sub_hypothesis_id") or "").strip()
                if (
                    subhypothesis_id not in candidates_by_sh
                    or annotation.get("project_id") != project_id
                    or annotation.get("project_context_fingerprint") != fingerprint
                    or str(annotation.get("association_stage") or "") != "GRAPH_EXPANSION"
                    or str(annotation.get("association_status") or "")
                    != "GRAPH_EXPANDED_CANDIDATE"
                    or identifier in baseline_by_sh.get(subhypothesis_id, set())
                    or identifier in existing_promoted_by_sh.get(subhypothesis_id, set())
                ):
                    continue
                grouped = candidates_by_sh[subhypothesis_id].setdefault(
                    identifier,
                    {
                        "paper_id": selected_by_identity[identifier],
                        "annotations": [],
                    },
                )
                grouped["annotations"].append(annotation)

        score_by_identity = {
            canonical_paper_id(record.get("paper_id")): dict(record)
            for record in getattr(self, "_last_fulltext_candidate_records", []) or []
            if isinstance(record, Mapping) and canonical_paper_id(record.get("paper_id"))
        }
        candidate_pairs: list[dict[str, Any]] = []
        for subhypothesis_id, candidates in candidates_by_sh.items():
            deficit = max(
                0,
                self._writing_paper_limit_per_sh()
                - len(
                    baseline_by_sh.get(subhypothesis_id, set())
                    | existing_promoted_by_sh.get(subhypothesis_id, set())
                ),
            )
            result["deficit_by_sh"][subhypothesis_id] = deficit
            if not deficit:
                continue
            candidate_limit = self._expanded_promotion_candidate_limit(deficit)
            ranked = sorted(
                candidates.items(),
                key=lambda item: (
                    -self._safe_score(
                        score_by_identity.get(item[0], {}).get("max_llm_relevance_score")
                    ),
                    -self._safe_score(
                        score_by_identity.get(item[0], {}).get(
                            "max_embedding_relatedness"
                        )
                    ),
                    item[0],
                ),
            )[:candidate_limit]
            for identifier, candidate in ranked:
                candidate_pairs.append(
                    {
                        "paper_id": str(candidate.get("paper_id") or ""),
                        "canonical_paper_id": identifier,
                        "sub_hypothesis_id": subhypothesis_id,
                        "relatedness_score": max(
                            self._safe_score(
                                score_by_identity.get(identifier, {}).get(
                                    "max_llm_relevance_score"
                                )
                            ),
                            self._safe_score(
                                score_by_identity.get(identifier, {}).get(
                                    "max_embedding_relatedness"
                                )
                            ),
                        ),
                    }
                )

        result["candidate_pairs"] = candidate_pairs
        result["eligible_candidate_pairs"] = len(candidate_pairs)
        result["eligible_unique_paper_ids"] = len(
            {item["canonical_paper_id"] for item in candidate_pairs}
        )
        if not candidate_pairs:
            result["skipped_reason"] = "no_selected_graph_candidates_needed"
        return result

    def promote_complete_section_read_graph_candidates(
        self,
        complete_section_keynotes: Mapping[str, Any] | None,
    ) -> dict[str, Any]:
        """Independently assess readable citation-expanded papers for SH writing.

        The input must contain only keynotes synthesized from complete-section
        reading.  Abstract fallbacks are deliberately excluded by WorkAnalyzer,
        so this method can never use a citation edge or an abstract as the
        basis for promotion.
        """

        result: dict[str, Any] = {
            "enabled": self._fulltext_expanded_promotion_enabled(),
            "read_complete_section_papers": 0,
            "eligible_candidate_pairs": 0,
            "assessed_pairs": 0,
            "cache_hits": 0,
            "promoted_pairs": 0,
            "promoted_by_sh": {},
            "skipped_reason": "",
        }
        if not result["enabled"]:
            result["skipped_reason"] = "disabled_by_configuration"
            return result
        if not isinstance(complete_section_keynotes, Mapping):
            result["skipped_reason"] = "no_complete_section_keynotes"
            return result

        keynotes_by_identity: dict[str, tuple[str, Any]] = {}
        for raw_paper_id, keynote in complete_section_keynotes.items():
            identifier = canonical_paper_id(raw_paper_id)
            if identifier and keynote not in (None, "", [], {}):
                keynotes_by_identity.setdefault(identifier, (str(raw_paper_id), keynote))
        result["read_complete_section_papers"] = len(keynotes_by_identity)
        if not keynotes_by_identity:
            result["skipped_reason"] = "no_complete_section_keynotes"
            return result

        provenance = getattr(self, "sh_graph_provenance_artifact", {})
        retrieval = getattr(self, "subhypothesis_retrieval_artifact", {})
        if not isinstance(provenance, Mapping):
            provenance = self._basic_info_value("sh_graph_provenance", {})
        if not isinstance(retrieval, Mapping):
            retrieval = self._basic_info_value("subhypothesis_retrieval", {})
        provenance = dict(provenance) if isinstance(provenance, Mapping) else {}
        retrieval = dict(retrieval) if isinstance(retrieval, Mapping) else {}
        if provenance.get("schema_version") != SH_GRAPH_PROVENANCE_SCHEMA_VERSION:
            result["skipped_reason"] = "missing_sh_graph_provenance"
            return result
        plan = retrieval.get("plan")
        plan = dict(plan) if isinstance(plan, Mapping) else {}
        subhypotheses = self._valid_subhypotheses(plan)
        by_sh_contract = {
            str(subhypothesis.get("sub_hypothesis_id") or "").strip(): dict(subhypothesis)
            for subhypothesis in subhypotheses
            if str(subhypothesis.get("sub_hypothesis_id") or "").strip()
        }
        if not by_sh_contract:
            result["skipped_reason"] = "missing_valid_subhypothesis_contracts"
            return result
        research_context = plan.get("project_context")
        research_context = (
            dict(research_context)
            if isinstance(research_context, Mapping)
            else self.get_project_research_context()
        )
        if not isinstance(research_context, Mapping):
            result["skipped_reason"] = "missing_project_research_context"
            return result

        coverage_ledger = retrieval.get("evidence_coverage_ledger_final")
        coverage_ledger = (
            dict(coverage_ledger) if isinstance(coverage_ledger, Mapping) else {}
        )
        baseline_by_sh = self._fulltext_promotion_baseline_ids(
            provenance=provenance,
            coverage_ledger=coverage_ledger,
            subhypothesis_ids=set(by_sh_contract),
        )
        existing_promoted_by_sh: dict[str, set[str]] = {
            subhypothesis_id: set() for subhypothesis_id in by_sh_contract
        }
        for raw_paper_id, raw_annotations in (provenance.get("paper_annotations") or {}).items():
            identifier = canonical_paper_id(raw_paper_id)
            if not identifier or not isinstance(raw_annotations, Sequence) or isinstance(
                raw_annotations, (str, bytes)
            ):
                continue
            for raw_annotation in raw_annotations:
                annotation = (
                    dict(raw_annotation) if isinstance(raw_annotation, Mapping) else {}
                )
                subhypothesis_id = str(annotation.get("sub_hypothesis_id") or "").strip()
                if (
                    subhypothesis_id in existing_promoted_by_sh
                    and annotation.get("project_id") == str(provenance.get("project_id") or "").strip()
                    and annotation.get("project_context_fingerprint")
                    == str(provenance.get("project_context_fingerprint") or "").strip()
                    and str(annotation.get("association_stage") or "")
                    == FULLTEXT_PROMOTION_STAGE
                    and str(annotation.get("evidence_use_mode") or "")
                    in {
                        "DIRECT_LEDGER_EVIDENCE",
                        "QUALIFIED_SH_CONTRIBUTION",
                        "BACKGROUND_CONTEXT",
                    }
                ):
                    existing_promoted_by_sh[subhypothesis_id].add(identifier)
        candidates_by_sh: dict[str, dict[str, dict[str, Any]]] = {
            subhypothesis_id: {} for subhypothesis_id in by_sh_contract
        }
        project_id = str(provenance.get("project_id") or "").strip()
        fingerprint = str(provenance.get("project_context_fingerprint") or "").strip()
        for raw_paper_id, raw_annotations in (provenance.get("paper_annotations") or {}).items():
            identifier = canonical_paper_id(raw_paper_id)
            if identifier not in keynotes_by_identity or not isinstance(
                raw_annotations, Sequence
            ) or isinstance(raw_annotations, (str, bytes)):
                continue
            for raw_annotation in raw_annotations:
                annotation = (
                    dict(raw_annotation) if isinstance(raw_annotation, Mapping) else {}
                )
                subhypothesis_id = str(annotation.get("sub_hypothesis_id") or "").strip()
                if (
                    subhypothesis_id not in candidates_by_sh
                    or annotation.get("project_id") != project_id
                    or annotation.get("project_context_fingerprint") != fingerprint
                    or str(annotation.get("association_stage") or "") != "GRAPH_EXPANSION"
                    or str(annotation.get("association_status") or "")
                    != "GRAPH_EXPANDED_CANDIDATE"
                    or identifier in baseline_by_sh.get(subhypothesis_id, set())
                    or identifier in existing_promoted_by_sh.get(subhypothesis_id, set())
                ):
                    continue
                grouped = candidates_by_sh[subhypothesis_id].setdefault(
                    identifier,
                    {
                        "paper_id": str(raw_paper_id),
                        "annotations": [],
                    },
                )
                grouped["annotations"].append(annotation)

        score_by_identity = {
            canonical_paper_id(record.get("paper_id")): dict(record)
            for record in getattr(self, "_last_fulltext_candidate_records", []) or []
            if isinstance(record, Mapping) and canonical_paper_id(record.get("paper_id"))
        }
        pending: list[dict[str, Any]] = []
        for subhypothesis_id, candidates in candidates_by_sh.items():
            deficit = max(
                0,
                self._writing_paper_limit_per_sh()
                - len(
                    baseline_by_sh.get(subhypothesis_id, set())
                    | existing_promoted_by_sh.get(subhypothesis_id, set())
                ),
            )
            if not deficit:
                continue
            candidate_limit = self._expanded_promotion_candidate_limit(deficit)
            ranked = sorted(
                candidates.items(),
                key=lambda item: (
                    -self._safe_score(
                        score_by_identity.get(item[0], {}).get(
                            "max_llm_relevance_score"
                        )
                    ),
                    -self._safe_score(
                        score_by_identity.get(item[0], {}).get(
                            "max_embedding_relatedness"
                        )
                    ),
                    item[0],
                ),
            )[:candidate_limit]
            for identifier, candidate in ranked:
                keynote_paper_id, keynote = keynotes_by_identity[identifier]
                paper_id = str(candidate.get("paper_id") or keynote_paper_id)
                node = None
                graph = getattr(self, "reference_graph", None)
                if graph is not None and paper_id in graph:
                    node = graph.nodes[paper_id]
                metadata = self._fulltext_promotion_metadata(paper_id, node)
                subhypothesis = by_sh_contract[subhypothesis_id]
                cache_key = self._fulltext_promotion_cache_key(
                    paper_id=paper_id,
                    keynote=keynote,
                    subhypothesis=subhypothesis,
                    research_context=research_context,
                )
                pending.append(
                    {
                        "paper_id": paper_id,
                        "canonical_paper_id": identifier,
                        "annotations": list(candidate.get("annotations") or []),
                        "subhypothesis": subhypothesis,
                        "subhypothesis_id": subhypothesis_id,
                        "keynote": keynote,
                        "metadata": metadata,
                        "cache_key": cache_key,
                        "relatedness_score": max(
                            self._safe_score(
                                score_by_identity.get(identifier, {}).get(
                                    "max_llm_relevance_score"
                                )
                            ),
                            self._safe_score(
                                score_by_identity.get(identifier, {}).get(
                                    "max_embedding_relatedness"
                                )
                            ),
                        ),
                    }
                )
        result["eligible_candidate_pairs"] = len(pending)
        if not pending:
            result["skipped_reason"] = "no_readable_graph_candidates_needed"
            return result

        cache = getattr(self, "sh_paper_semantic_assessment_cache", None)
        cache_enabled = self._sh_paper_semantic_cache_enabled() and cache is not None
        assessments: list[tuple[dict[str, Any], dict[str, Any]]] = []
        remote_pending: list[dict[str, Any]] = []
        for item in pending:
            cached = None
            if cache_enabled:
                try:
                    cached = cache.get(item["cache_key"])
                except (AttributeError, OSError, ValueError):
                    cached = None
            if isinstance(cached, Mapping):
                assessment = dict(cached)
                assessment["cache_status"] = "hit"
                assessments.append((item, assessment))
                result["cache_hits"] += 1
            else:
                remote_pending.append(item)

        if remote_pending:
            context_payload = json.dumps(
                relevance_context_payload(research_context),
                ensure_ascii=False,
            )
            prompts: list[str] = []
            for item in remote_pending:
                prompt = SH_FULLTEXT_EXPANDED_PROMOTION_ASSESSMENT
                replacements = {
                    "{research_context}": context_payload,
                    "{subhypothesis}": json.dumps(
                        self._subhypothesis_prompt_payload(item["subhypothesis"]),
                        ensure_ascii=False,
                    ),
                    "{metadata}": json.dumps(item["metadata"], ensure_ascii=False),
                    "{complete_section_keynote}": json.dumps(
                        item["keynote"],
                        ensure_ascii=False,
                        default=str,
                    ),
                }
                for marker, replacement in replacements.items():
                    prompt = prompt.replace(marker, replacement)
                prompts.append(prompt)
            batch_kwargs: dict[str, Any] = {
                "temperature": 0.0,
                "desc": "Promoting complete-section citation-expanded papers",
            }
            supports_response_format = getattr(
                self.chat_agent, "supports_response_format", None
            )
            if callable(supports_response_format):
                try:
                    if supports_response_format("json_object"):
                        batch_kwargs["response_format"] = "json_object"
                except (TypeError, ValueError):
                    pass
            responses = self.chat_agent.batch_remote_chat(prompts, **batch_kwargs)
            for index, item in enumerate(remote_pending):
                response = responses[index] if index < len(responses) else None
                try:
                    parsed = extract_json(response)
                    assessment = self._normalise_sh_semantic_assessment(
                        parsed,
                        paper=item["metadata"],
                        subhypothesis=item["subhypothesis"],
                        research_context=research_context,
                        cache_key=item["cache_key"],
                        assessment_source="llm_complete_section_keynote_sh_semantic",
                        additional_evidence_sources={
                            "complete_section_keynote": json.dumps(
                                item["keynote"], ensure_ascii=False, default=str
                            )
                        },
                    )
                except Exception as exc:
                    self.logger.warning(
                        "Unable to assess complete-section expanded paper %s / %s: %s",
                        item["paper_id"],
                        item["subhypothesis_id"],
                        exc,
                    )
                    assessment = self._normalise_sh_semantic_assessment(
                        {},
                        paper=item["metadata"],
                        subhypothesis=item["subhypothesis"],
                        research_context=research_context,
                        cache_key=item["cache_key"],
                        status="unavailable",
                        assessment_source="llm_complete_section_keynote_sh_semantic",
                        additional_evidence_sources={
                            "complete_section_keynote": json.dumps(
                                item["keynote"], ensure_ascii=False, default=str
                            )
                        },
                    )
                assessment["cache_status"] = "miss"
                assessments.append((item, assessment))
                if cache_enabled:
                    try:
                        cache[item["cache_key"]] = dict(assessment)
                    except (AttributeError, OSError, ValueError):
                        self.logger.warning(
                            "Unable to persist full-text promotion assessment cache entry."
                        )

        updated = dict(provenance)
        annotation_index = updated.get("paper_annotations")
        promotion_audit: list[dict[str, Any]] = []
        for item, assessment in assessments:
            result["assessed_pairs"] += 1
            annotations = build_fulltext_promotion_annotations(
                item["annotations"],
                assessment,
                fulltext_reading_source="complete_section_keynote",
                promotion_relatedness_score=item["relatedness_score"],
            )
            if annotations:
                annotation_index = append_annotation_index(
                    annotation_index,
                    item["paper_id"],
                    annotations,
                )
                self._attach_sh_graph_node_annotations(item["paper_id"], annotations)
                result["promoted_pairs"] += 1
                subhypothesis_id = item["subhypothesis_id"]
                result["promoted_by_sh"][subhypothesis_id] = (
                    result["promoted_by_sh"].get(subhypothesis_id, 0) + 1
                )
            promotion_audit.append(
                {
                    "paper_id": item["paper_id"],
                    "sub_hypothesis_id": item["subhypothesis_id"],
                    "cache_status": assessment.get("cache_status"),
                    "promotion_status": (
                        FULLTEXT_PROMOTED_EXPANDED if annotations else "NOT_PROMOTED"
                    ),
                    "evidence_use_mode": (
                        annotations[0].get("evidence_use_mode") if annotations else ""
                    ),
                    "semantic_relevance_score": assessment.get(
                        "semantic_relevance_score"
                    ),
                    "overall_relation": assessment.get("overall_relation"),
                    "supported_slots": [
                        contribution.get("slot_name")
                        for contribution in assessment.get(
                            "candidate_slot_contributions", []
                        )
                        if isinstance(contribution, Mapping)
                        and contribution.get("support_level") != "none"
                    ],
                    "ungrounded_evidence_span_count": assessment.get(
                        "ungrounded_evidence_span_count", 0
                    ),
                }
            )
        updated["paper_annotations"] = annotation_index or {}
        updated["fulltext_expanded_promotion"] = {
            "schema_version": "fulltext_expanded_promotion_v1",
            "writing_max_papers_per_sh": self._writing_paper_limit_per_sh(),
            "summary": dict(result),
            "assessments": promotion_audit,
        }
        self._store_sh_graph_provenance_artifact(updated)
        self.logger.info(
            "Complete-section expansion promotion assessed %s candidate/SH pairs; "
            "promoted %s (%s).",
            result["assessed_pairs"],
            result["promoted_pairs"],
            "; ".join(
                f"{subhypothesis_id}={count}"
                for subhypothesis_id, count in sorted(
                    result["promoted_by_sh"].items()
                )
            )
            or "none",
        )
        return result

    def _build_configured_subhypothesis_plan(
        self,
        topic: str,
        research_context: Mapping[str, Any] | None = None,
    ) -> tuple[Dict, list[Dict]]:
        resolved_context = research_context or self.get_project_research_context(topic)
        configured_subhypotheses = self._resolved_subhypotheses(resolved_context)
        data_anchored_artifact = getattr(
            self,
            "data_anchored_subhypothesis_artifact",
            {},
        )
        plan = build_subhypothesis_retrieval_plan(
            resolved_context,
            configured_subhypotheses,
            include_arxiv=self._arxiv_discovery_enabled(),
            query_variant_bindings=(
                data_anchored_artifact.get("query_variant_bindings")
                if isinstance(data_anchored_artifact, Mapping)
                and data_anchored_artifact.get("query_variant_bindings")
                else None
            ),
            subhypothesis_metadata=(
                data_anchored_artifact.get("metadata_by_subhypothesis")
                if isinstance(data_anchored_artifact, Mapping)
                and data_anchored_artifact.get("metadata_by_subhypothesis")
                else None
            ),
        )
        self._emit_subhypothesis_declared_events(plan, resolved_context)
        valid_subhypotheses = self._valid_subhypotheses(plan)
        if configured_subhypotheses and not valid_subhypotheses:
            errors = [
                subhypothesis.get("validation", {}).get("errors", [])
                for subhypothesis in plan.get("subhypotheses", [])
                if isinstance(subhypothesis, Mapping)
            ]
            raise ValueError(
                "No valid sub-hypotheses are available for SH retrieval: "
                f"{errors}"
            )
        return plan, valid_subhypotheses

    def _filter_project_candidates_if_enabled(
        self,
        topic: str,
        papers: list[Dict],
        research_context: Mapping[str, Any],
        *,
        require_project_relevance: bool = False,
        retain_all: bool = False,
        retain_deferred_if_accepted_below: int | None = None,
    ) -> list[Dict]:
        if not papers:
            return papers
        threshold = int(self._work_collector_setting("LLM_seed_threshold", 4))
        if self._work_collector_setting("use_seed_filter_LLM", True):
            return self.filter_seed_papers(
                topic,
                papers,
                threshold=threshold,
                research_context=dict(research_context),
                retain_all=retain_all,
                retain_deferred_if_accepted_below=retain_deferred_if_accepted_below,
            )
        if require_project_relevance:
            return ensure_deterministic_project_relevance(
                papers,
                research_context,
                threshold=threshold,
            )
        return papers

    def _emit_subhypothesis_declared_events(
        self,
        plan: Mapping[str, Any],
        research_context: Mapping[str, Any],
    ) -> None:
        """Log each compiled SH once with a concise, human-readable summary."""

        emitted = getattr(self, "_subhypothesis_declared_event_keys", None)
        if not isinstance(emitted, set):
            emitted = set()
            self._subhypothesis_declared_event_keys = emitted
        project_id = self._project_id(research_context)
        context_fingerprint = str(research_context.get("input_fingerprint") or "")
        for raw_subhypothesis in plan.get("subhypotheses", []):
            if not isinstance(raw_subhypothesis, Mapping):
                continue
            subhypothesis = dict(raw_subhypothesis)
            subhypothesis_id = str(subhypothesis.get("sub_hypothesis_id") or "")
            if not subhypothesis_id:
                continue
            event_key = f"{context_fingerprint}:{subhypothesis_id}"
            if event_key in emitted:
                continue
            emitted.add(event_key)
            validation = subhypothesis.get("validation")
            validation_data = validation if isinstance(validation, Mapping) else {}
            valid = bool(validation_data.get("valid"))
            task_count = len(
                subhypothesis.get("slot_recovery_tasks")
                if isinstance(subhypothesis.get("slot_recovery_tasks"), list)
                else []
            )
            summary = self._subhypothesis_summary_for_log(subhypothesis)
            event_fields = {
                "project_id": project_id,
                "sub_hypothesis_id": subhypothesis_id,
                "summary": summary,
                "question_kind": subhypothesis.get("question_kind", ""),
                "research_role": subhypothesis.get("research_role", ""),
                "required_slots": subhypothesis.get("required_slots", []),
                "design_basis_ids": subhypothesis.get("design_basis_ids", []),
                "slot_recovery_task_count": task_count,
                "validation": "valid" if valid else "invalid",
            }
            emit_science_event(self.logger, "subhypothesis_declared", **event_fields)
            self.logger.info(
                "SH %s declared: summary=%s question_kind=%s role=%s required_slots=%s "
                "design_basis_ids=%s slot_recovery_tasks=%s validation=%s.",
                subhypothesis_id,
                summary,
                event_fields["question_kind"] or "UNSPECIFIED",
                event_fields["research_role"] or "UNSPECIFIED",
                "|".join(str(item) for item in event_fields["required_slots"]),
                "|".join(str(item) for item in event_fields["design_basis_ids"]),
                task_count,
                event_fields["validation"],
            )

    @staticmethod
    def _subhypothesis_summary_for_log(subhypothesis: Mapping[str, Any]) -> str:
        """Use the first complete SH-question sentence as its stable log summary."""

        question = re.sub(r"\s+", " ", str(subhypothesis.get("question") or "")).strip()
        if not question:
            return "No question supplied."
        first_sentence = re.split(r"(?<=[.!?。！？])\s+", question, maxsplit=1)[0]
        return first_sentence[:600].rstrip()

    def _build_sh_evidence_coverage_ledger(
        self,
        papers: Sequence[Mapping[str, Any]],
        subhypotheses: Sequence[Mapping[str, Any]],
        research_context: Mapping[str, Any],
    ) -> Dict:
        return build_evidence_coverage_ledger(
            papers,
            subhypotheses,
            max_unique_papers_per_sh=int(
                self._work_collector_setting("subhypothesis_max_unique_papers", 6)
            ),
            max_slots_per_paper=int(
                self._work_collector_setting("subhypothesis_max_slots_per_paper", 2)
            ),
            project_id=self._project_id(research_context),
            project_context_fingerprint=str(
                research_context.get("input_fingerprint") or ""
            ),
        )

    def _collect_sh_seed_candidates(
        self,
        topic: str,
        research_context: Mapping[str, Any],
        plan: Mapping[str, Any],
        subhypotheses: Sequence[Mapping[str, Any]],
    ) -> tuple[list[Dict], Dict]:
        self._slot_retrieval_summaries = []
        relevance_threshold = int(
            self._work_collector_setting("subhypothesis_relevance_threshold", 3)
        )
        max_slots_per_paper = int(
            self._work_collector_setting("subhypothesis_max_slots_per_paper", 2)
        )
        discovered_candidates = self._discover_subhypothesis_candidates(subhypotheses)
        initial_candidates = self._limit_subhypothesis_discovery_candidates(
            discovered_candidates,
            subhypotheses,
        )
        self.logger.info(
            "SH retrieval candidate funnel: merged_unique_candidates=%s "
            "discovery_budget_per_SH=%s candidates_sent_to_project_screen=%s "
            "subhypotheses=%s.",
            len(discovered_candidates),
            self._work_collector_setting("subhypothesis_max_unique_papers", 6),
            len(initial_candidates),
            len(subhypotheses),
        )
        # Slot-scoped Semantic Scholar fallback has already run only for slots
        # whose enabled OpenAlex/arXiv lanes were all empty.  Do not repeat the
        # topic-wide fallback here: it would hide which slot and query variant
        # exhausted recall, and could turn one precision-lane failure into an
        # unrelated project-level candidate set.
        candidates_before_project_screen = len(initial_candidates)
        initial_candidates = self._filter_project_candidates_if_enabled(
            topic,
            initial_candidates,
            research_context,
            require_project_relevance=True,
            retain_all=True,
            retain_deferred_if_accepted_below=int(
                self._work_collector_setting("max_seed_paper_num", 5)
            ),
        )
        self.logger.info(
            "SH semantic assessment input: candidate_papers=%s/%s after "
            "adaptive project screening; deferred candidates continue only "
            "when accepted project-relevant papers do not yet meet the seed budget.",
            len(initial_candidates),
            candidates_before_project_screen,
        )
        initial_candidates = self.assess_papers_against_subhypotheses(
            initial_candidates,
            subhypotheses,
            research_context,
        )
        papers = associate_papers_with_subhypotheses(
            initial_candidates,
            subhypotheses,
            project_fingerprint=str(research_context.get("input_fingerprint") or ""),
            relevance_threshold=relevance_threshold,
            max_slots_per_paper=max_slots_per_paper,
        )
        initial_ledger = self._build_sh_evidence_coverage_ledger(
            papers,
            subhypotheses,
            research_context,
        )
        # A paper's LLM-assessed contribution—not whether it can formally prove
        # one slot as direct evidence—governs candidate retention and graph
        # expansion.  Direct-slot coverage remains an audit-only writing fact;
        # it must never trigger another retrieval round or force a paper to
        # satisfy every SH contract/causal link.
        supplement_metadata = {
            "attempted": False,
            "round": 0,
            "requested_slot_recovery_tasks": {},
            "new_unique_papers": 0,
            "no_yield_stop": False,
            "disabled_reason": "formal_slot_coverage_does_not_trigger_retrieval",
        }
        self.logger.info(
            "SH semantic assessment completed; formal direct-slot coverage is "
            "recorded for provenance only, so no ledger-driven supplement or "
            "refinement retrieval will run."
        )
        # Retain the familiar artifact fields for readers that compare ledger
        # snapshots, but do not recompute or act on a formal-coverage gap.
        ledger_before_refinement = deepcopy(initial_ledger)
        final_ledger = deepcopy(initial_ledger)
        refinement_plan = {
            "schema_version": "evidence_refinement_v1",
            "active_tasks": [],
            "disabled_reason": "formal_slot_coverage_does_not_trigger_retrieval",
        }
        refinement_execution = {
            "schema_version": "evidence_refinement_execution_v1",
            "attempted": False,
            "task_reports": [],
            "refinement_resolution": [],
            "disabled_reason": "formal_slot_coverage_does_not_trigger_retrieval",
        }
        final_ledger["refinement_resolution"] = []
        selection = select_sh_seed_candidates(
            papers,
            subhypotheses,
            max_seed_papers=int(self._work_collector_setting("max_seed_paper_num", 5)),
            max_slots_per_paper=max_slots_per_paper,
            require_project_relevance=True,
            project_relevance_threshold=int(
                self._work_collector_setting("LLM_seed_threshold", 4)
            ),
            semantic_relevance_threshold=relevance_threshold,
            coverage_ledger=final_ledger,
        )
        artifact = {
            "schema_version": "subhypothesis_slot_retrieval_execution_v5",
            "project_id": self._project_id(research_context),
            "project_context_fingerprint": str(
                research_context.get("input_fingerprint") or ""
            ),
            "plan": dict(plan),
            "slot_retrieval_summaries": list(
                getattr(self, "_slot_retrieval_summaries", []) or []
            ),
            "candidate_papers": papers,
            "evidence_coverage_ledger_initial": initial_ledger,
            "evidence_coverage_ledger_pre_refinement": ledger_before_refinement,
            "evidence_coverage_ledger_final": final_ledger,
            "supplement": supplement_metadata,
            "evidence_refinement": {
                "enabled": False,
                "plan": refinement_plan,
                "new_unique_papers": 0,
                "execution": refinement_execution,
            },
            "seed_selection": selection,
        }
        self._store_subhypothesis_retrieval_artifact(artifact)
        self._initialize_sh_graph_provenance(
            research_context,
            selection,
            final_ledger,
        )
        return list(selection.get("selected_papers") or []), selection

    def collect_seed_papers(self, topic: str):
        """
        Collect related work based on the given topic.
        Returns a list of work items.
        """
        research_context = self.get_project_research_context(topic)
        self.logger.info(
            "Building sub-hypothesis retrieval plan from project domain=%s research_domains=%s.",
            research_context.get("domain") or "Unresolved Research Domain",
            "|".join(
                str(item.get("label") or "")
                for item in research_context.get("research_domains", [])
                if isinstance(item, Mapping)
            )
            or "Unspecified",
        )
        sh_plan, valid_subhypotheses = self._build_configured_subhypothesis_plan(
            topic,
            research_context,
        )
        sh_retrieval_active = bool(valid_subhypotheses) and self._subhypothesis_retrieval_enabled()
        sh_selection: Dict = {}
        if sh_retrieval_active:
            papers, sh_selection = self._collect_sh_seed_candidates(
                topic,
                research_context,
                sh_plan,
                valid_subhypotheses,
            )
            self.logger.info(
                "Selected %s SH-qualified seed candidates across %s sub-hypotheses.",
                len(papers),
                len(valid_subhypotheses),
            )
        else:
            retrieval_plan = self._project_query_plan(research_context)
            papers = self._discover_seed_candidates(topic, retrieval_plan)
            self.logger.info(
                "Found %s deduplicated seed candidates across limited discovery lanes for topic: %s",
                len(papers),
                topic,
            )
            papers = self._filter_project_candidates_if_enabled(
                topic,
                papers,
                research_context,
            )
            max_seed_papers = int(self._work_collector_setting("max_seed_paper_num", 5))
            selected_papers = self._select_lane_balanced_seed_candidates(
                papers,
                max_seed_papers,
            )
            if len(selected_papers) != len(papers):
                self.logger.info(
                    "Selected %s/%s seed candidates with bounded lane coverage before download.",
                    len(selected_papers),
                    len(papers),
                )
            papers = selected_papers

        max_seed_papers = int(self._work_collector_setting("max_seed_paper_num", 5))
        context_seed_papers = [
            paper
            for paper in sh_selection.get("context_seed_papers", [])
            if isinstance(paper, Mapping)
        ] if sh_retrieval_active else []
        context_source_ids = {
            self.data_manager._resolve_paper_reference_id(paper)
            for paper in context_seed_papers
        }
        graph_seed_papers = [
            paper
            for paper in papers
            if self.data_manager._resolve_paper_reference_id(paper) not in context_source_ids
            and (paper.get("seed_selection") or {}).get("graph_expansion_eligible", True)
        ]
        self.graph_seed_expansion_modes = {
            self.data_manager._resolve_paper_reference_id(paper): str(
                (paper.get("seed_selection") or {}).get(
                    "graph_expansion_mode",
                    "evidence_normal",
                )
            )
            for paper in graph_seed_papers
            if self.data_manager._resolve_paper_reference_id(paper)
        }
        
        if not papers:
            self.logger.warning("No seed papers remained after LLM filtering! Please increase the seed paper number")
            raise ValueError("No seed papers remained after LLM filtering")
            return []

        valid_graph_seed_paper_ids = []
        if self.expand_in_local_paper_graph:
            self.logger.info("local paper graph enabled. Validating seed papers in paper graph...")
            graph_fail_papers = []
            for seed_paper in graph_seed_papers:

                paper_id = self.data_manager._resolve_paper_reference_id(seed_paper)

                try:
                    title, abstract = self.data_manager.get_paper_title_abstract(paper_id)
                    results = self.paper_graph_retriever.search_by_paper_title(title)
                except Exception as e:
                    self.logger.error(f"Error occurs in seed paper validation in local paper graph mode: {e}")
                    graph_fail_papers.append(seed_paper)
                    continue
                if not results:
                    graph_fail_papers.append(seed_paper)
                    continue
                else:
                    valid_graph_seed_paper_ids.append(paper_id)
            
            if self.use_ds_when_graph_fail:
                self.logger.info(f"use ds papers when graph fail enabled. Revalidating {len(graph_fail_papers)} seed papers")
                fallback_valid_papers_ids = self.data_manager.download_and_parse_papers(
                    graph_fail_papers, limit=max_seed_papers
                )
                self.logger.info(f"{len(valid_graph_seed_paper_ids)} seed papers enabled through fallback")
                valid_graph_seed_paper_ids.extend(fallback_valid_papers_ids)
                self.graph_paper_ids.update(valid_graph_seed_paper_ids)

            valid_context_seed_paper_ids = []
            if context_seed_papers:
                valid_context_seed_paper_ids = self.data_manager.download_and_parse_papers(
                    context_seed_papers,
                    limit=len(context_seed_papers),
                )
                self.graph_paper_ids.update(valid_context_seed_paper_ids)
                for paper in context_seed_papers:
                    source_id = self.data_manager._resolve_paper_reference_id(paper)
                    openalex_id = self.data_manager.openalex_api.resolve_work_id(paper)
                    if source_id and openalex_id:
                        self._openalex_id_aliases[source_id] = openalex_id
                self.context_seed_paper_ids = {
                    self._openalex_id_aliases.get(paper_id, paper_id)
                    for paper_id in valid_context_seed_paper_ids
                    if paper_id
                }
            
            if len(valid_graph_seed_paper_ids) == 0 and not valid_context_seed_paper_ids:
                raise ValueError("collected seed papers not in paper graph")
            
            self.logger.info(
                "%s evidence seeds in the local paper graph and %s context seeds available for reading.",
                len(valid_graph_seed_paper_ids),
                len(valid_context_seed_paper_ids),
            )
            
            return valid_graph_seed_paper_ids + valid_context_seed_paper_ids

        self.logger.info(
            f"Downloading and parsing up to {len(papers)} papers..."
        )
        valid_seed_papers_ids = self.data_manager.download_and_parse_papers(
            papers, limit=max_seed_papers
        )
        for paper in papers:
            source_id = self.data_manager._resolve_paper_reference_id(paper)
            openalex_id = self.data_manager.openalex_api.resolve_work_id(paper)
            if source_id and openalex_id:
                self._openalex_id_aliases[source_id] = openalex_id
        valid_seed_papers_ids = [
            self._openalex_id_aliases.get(paper_id, paper_id)
            for paper_id in valid_seed_papers_ids
        ]
        self.graph_seed_expansion_modes = {
            self._openalex_id_aliases.get(paper_id, paper_id): mode
            for paper_id, mode in self.graph_seed_expansion_modes.items()
            if paper_id
        }
        valid_seed_papers_ids = [paper_id for paper_id in valid_seed_papers_ids if paper_id not in self.ignore_paper]
        # A failed legal OA acquisition is not a semantic rejection.  Keep an
        # exploration/context-capable selected paper as a metadata graph root,
        # while keeping it out of `valid_seed_papers_ids` so downstream deep
        # reading never mistakes unavailable full text for usable evidence.
        selected_graph_root_ids = {
            self._openalex_id_aliases.get(
                self.data_manager._resolve_paper_reference_id(paper),
                self.data_manager._resolve_paper_reference_id(paper),
            )
            for paper in graph_seed_papers
            if self.data_manager._resolve_paper_reference_id(paper)
        }
        self.metadata_only_graph_seed_ids = {
            paper_id
            for paper_id in selected_graph_root_ids
            if paper_id not in valid_seed_papers_ids and paper_id not in self.ignore_paper
        }
        if self.metadata_only_graph_seed_ids:
            self.logger.info(
                "Retaining %s SH-qualified metadata-only graph roots after full-text acquisition failure; "
                "they are excluded from direct reading and writing evidence.",
                len(self.metadata_only_graph_seed_ids),
            )
        self.graph_paper_ids.update(valid_seed_papers_ids)
        if not sh_retrieval_active:
            return valid_seed_papers_ids

        self.context_seed_paper_ids = {
            self._openalex_id_aliases.get(paper_id, paper_id)
            for paper_id in context_source_ids
            if paper_id
        }
        self.logger.info(
            "SH seed selection retained %s evidence seeds and %s context-only seeds.",
            len([paper for paper in sh_selection.get("evidence_seed_papers", []) if isinstance(paper, Mapping)]),
            len(self.context_seed_paper_ids),
        )
        return valid_seed_papers_ids

    # ========== 直接委托给 DataManager 的函数 ==========
    
    def download_and_parse_papers(self, papers: list, limit: int = -1):
        """Download and parse papers - 委托给 DataManager"""
        return self.data_manager.download_and_parse_papers(papers, limit)

    def add_papers_abstracts_in_cache(self, papers: List[str], retry: int = 1):
        """Add paper abstracts to cache - 委托给 DataManager"""
        return self.data_manager.add_papers_abstracts_in_cache(papers, retry)

    def get_paper_title_abstract(self, paper_id: str, retry: int = 1):
        """Get paper title and abstract - 委托给 DataManager"""
        return self.data_manager.get_paper_title_abstract(paper_id, retry)

    def get_paper_title(self, paper_id: str, retry: int = 3):
        """Get paper title - 委托给 DataManager"""
        return self.data_manager.get_paper_title(paper_id, retry)

    def get_paper_raw_markdown(self, paper_id: str) -> str:
        """Get paper raw markdown - 委托给 DataManager"""
        return self.data_manager.get_paper_raw_markdown(paper_id)

    def get_paper_with_title(self, title: str):
        """Get paper with title - 委托给 DataManager"""
        return self.data_manager.get_paper_with_title(title)

    def get_paper_with_title_arxiv(self, title: str):
        """Get paper with title via arxiv - 委托给 DataManager"""
        return self.data_manager.get_paper_with_title_arxiv(title)

    def get_paper_with_title_semantic(self, title: str):
        """Get paper with title via semantic scholar - 委托给 DataManager"""
        return self.data_manager.get_paper_with_title_semantic(title)

    def get_paper_with_title_batch(self, titles: List[str]):
        """Get papers with titles in batch - 委托给 DataManager"""
        return self.data_manager.get_paper_with_title_batch(titles)

    def is_valid_abstract(self, abstract: str) -> bool:
        """Check if abstract is valid - 委托给 DataManager"""
        return self.data_manager.is_valid_abstract(abstract)

    # ========== 不委托给 DataManager 的函数 ==========
    
    def update_reference_graph(self, seed_paper_ids: List[str]):
        """
        Update the OpenAlex-only reference graph with canonical Work IDs.

        Legacy identifiers are resolved through OpenAlex when possible. They
        are marked unresolved otherwise and never trigger a Semantic Scholar
        citation request.
        """
        self.logger.info("Updating reference graph...")
        if self.reference_graph is None:
            self.reference_graph = nx.DiGraph()
        self.reference_graph.graph.update(
            {
                "provider": self._OPENALEX_GRAPH_PROVIDER,
                "schema_version": self._openalex_graph_schema_version,
                "client": "pyalex",
            }
        )
        self._reset_sh_graph_overlay_for_active_project()

        annotation_index = self._sh_graph_annotation_index()
        root_annotations_by_paper: Dict[str, list[Dict]] = {}
        configured_seed_modes = dict(
            getattr(self, "graph_seed_expansion_modes", {}) or {}
        )
        root_expansion_modes: Dict[str, str] = {}
        resolved_seed_paper_ids = []
        for paper_id in seed_paper_ids:
            aliases = getattr(self, "_openalex_id_aliases", {})
            resolved_id = aliases.get(paper_id)
            if not resolved_id:
                resolved_id = self.data_manager.openalex_api.resolve_work_id(paper_id)
            if resolved_id:
                aliases[paper_id] = resolved_id
                self._openalex_id_aliases = aliases
                resolved_seed_paper_ids.append(resolved_id)
                root_expansion_modes[resolved_id] = str(
                    configured_seed_modes.get(paper_id)
                    or configured_seed_modes.get(resolved_id)
                    or "evidence_normal"
                )
                direct_annotations = annotation_index.get(resolved_id) or annotation_index.get(
                    paper_id, []
                )
                if direct_annotations:
                    remapped = [
                        self._remap_sh_annotation_root(annotation, resolved_id)
                        for annotation in direct_annotations
                    ]
                    root_annotations_by_paper[resolved_id] = merge_node_annotations(
                        root_annotations_by_paper.get(resolved_id),
                        remapped,
                    )
                    artifact = getattr(self, "sh_graph_provenance_artifact", {})
                    if isinstance(artifact, Mapping):
                        updated_artifact = dict(artifact)
                        updated_artifact["paper_annotations"] = append_annotation_index(
                            updated_artifact.get("paper_annotations"),
                            resolved_id,
                            remapped,
                        )
                        self.sh_graph_provenance_artifact = updated_artifact
            else:
                self.logger.warning(
                    "OpenAlex could not resolve graph seed %s; marking it unresolved.",
                    paper_id,
                )

        resolved_seed_paper_ids = list(dict.fromkeys(resolved_seed_paper_ids))
        if not resolved_seed_paper_ids:
            return []

        def add_openalex_node(paper_id, paper):
            self.reference_graph.add_node(
                paper_id,
                title=paper.get("title"),
                year=paper.get("year", None),
                authors=paper.get("authors", None),
                abstract=paper.get("abstract", ""),
                venue=paper.get("venue", ""),
                provider=self._OPENALEX_GRAPH_PROVIDER,
                openalex_id=paper.get("openalex_id"),
                doi=paper.get("doi", ""),
                cited_by_count=paper.get("citedByCount", 0),
            )

        def one_step(paper_id: str, visited, direction: str = "out"):
            if paper_id in visited:
                return
            visited.add(paper_id)

            related_papers = []
            if (
                paper_id not in self.reference_graph
                or (
                    direction == "out"
                    and self.reference_graph.out_degree(paper_id) == 0
                )
                or (direction == "in" and self.reference_graph.in_degree(paper_id) == 0)
            ):
                related_limit = self.config.ModuleInfo.WorkCollector.related_work_top_k
                try:
                    paper_detail = self.data_manager.openalex_api.get_paper_details(paper_id)
                    relateds = self.data_manager.openalex_api.get_related_papers(
                        paper_id,
                        direction,
                        related_limit,
                    )
                except Exception as exc:
                    self.logger.error(
                        "Error fetching OpenAlex relations for %s: %s. Skipping.",
                        paper_id,
                        exc,
                    )
                    paper_detail = None
                    relateds = []

                if not paper_detail:
                    return

                resolved_id = self.data_manager._resolve_paper_reference_id(paper_detail)
                if resolved_id and resolved_id != paper_id:
                    self.logger.warning(
                        f"Provider resolved {paper_id} as {resolved_id}; retaining the requested graph node ID."
                    )
                if paper_id not in self.reference_graph:
                    add_openalex_node(paper_id, paper_detail)
                self._attach_sh_graph_node_annotations(
                    paper_id,
                    root_annotations_by_paper.get(paper_id, []),
                )

                if not relateds:
                    relateds = []

                for related in relateds:
                    if not isinstance(related, dict):
                        continue
                    related_id = self.data_manager._resolve_paper_reference_id(related)
                    if not related_id:
                        continue
                    if related_id not in self.reference_graph:
                        add_openalex_node(related_id, related)

                    if direction == "out":
                        self.reference_graph.add_edge(paper_id, related_id)
                    else:
                        self.reference_graph.add_edge(related_id, paper_id)
                    related_papers.append(related_id)
            else:
                if direction == "out":
                    related_papers = list(self.reference_graph.successors(paper_id))
                else:
                    related_papers = list(self.reference_graph.predecessors(paper_id))
            self._attach_sh_graph_node_annotations(
                paper_id,
                root_annotations_by_paper.get(paper_id, []),
            )
            return related_papers

        from tqdm import tqdm

        configured_depth = max(
            0,
            int(self.config.ModuleInfo.WorkCollector.reference_graph_depth),
        )
        bounded_exploration_depth = min(
            configured_depth,
            max(
                0,
                int(
                    self._work_collector_setting(
                        "exploration_seed_reference_graph_depth",
                        1,
                    )
                ),
            ),
        )

        def root_depth_limit(root_seed_id: str) -> int:
            mode = root_expansion_modes.get(root_seed_id, "evidence_normal")
            if mode == "bounded_exploration":
                return bounded_exploration_depth
            if mode in {"context_only", "holdout", "do_not_expand"}:
                return 0
            return configured_depth

        def traverse(direction="out"):
            current_lineage = {
                paper_id: {paper_id} for paper_id in resolved_seed_paper_ids
            }
            for depth in range(configured_depth):
                next_lineage: Dict[str, set[str]] = {}
                visited = set()
                for paper_id in tqdm(list(current_lineage)):
                    active_root_seed_ids = {
                        root_seed_id
                        for root_seed_id in current_lineage.get(paper_id, set())
                        if depth < root_depth_limit(root_seed_id)
                    }
                    if not active_root_seed_ids:
                        continue
                    related_papers = one_step(paper_id, visited, direction)
                    if related_papers:
                        root_seed_ids = active_root_seed_ids
                        for related_paper_id in related_papers:
                            next_lineage.setdefault(related_paper_id, set()).update(
                                root_seed_ids
                            )
                            for root_seed_id in root_seed_ids:
                                candidate_annotations = build_graph_expansion_annotations(
                                    root_annotations_by_paper.get(root_seed_id, []),
                                    parent_paper_id=paper_id,
                                    root_seed_paper_id=root_seed_id,
                                    lineage_depth=depth + 1,
                                    citation_direction=direction,
                                )
                                self._attach_sh_graph_node_annotations(
                                    related_paper_id,
                                    candidate_annotations,
                                )
                                self._record_graph_expansion_provenance(
                                    related_paper_id,
                                    candidate_annotations,
                                )
                                edge_source, edge_target = (
                                    (paper_id, related_paper_id)
                                    if direction == "out"
                                    else (related_paper_id, paper_id)
                                )
                                self._attach_sh_expansion_edge_provenance(
                                    edge_source,
                                    edge_target,
                                    candidate_annotations,
                                )

                        if not self.config.ModuleInfo.WorkCollector.RAG_source_use_embedding_filter and \
                            not self.config.ModuleInfo.WorkCollector.RAG_source_use_LLM_filter:
                            self.graph_paper_ids.update(related_papers)
                current_lineage = next_lineage

        traverse(direction="out")
        traverse(direction="in")

        if (
            isinstance(getattr(self, "sh_graph_provenance_artifact", None), Mapping)
            and self.sh_graph_provenance_artifact.get("schema_version")
            == SH_GRAPH_PROVENANCE_SCHEMA_VERSION
        ):
            self._store_sh_graph_provenance_artifact(
                self.sh_graph_provenance_artifact
            )

        with open(self.reference_graph_path, "wb") as writer:
            pickle.dump(self.reference_graph, writer)

        self.logger.info(
            f"Reference graph updated. Nodes: {self.reference_graph.number_of_nodes()}, Edges: {self.reference_graph.number_of_edges()}"
        )
        return resolved_seed_paper_ids

    def compute_relatedness_scores_and_filter(
        self,
        seed_paper_ids: List[str],
    ) -> float:
        """Compute relatedness score between related papers and seed papers."""
        research_context = self.get_project_research_context()
        research_context_json = json.dumps(
            relevance_context_payload(research_context),
            ensure_ascii=False,
        )
        
        total = 0
        for seed_pid in seed_paper_ids:
            references = list(self.reference_graph.successors(seed_pid))
            citations = list(self.reference_graph.predecessors(seed_pid))
            total += len(references) + len(citations)

        self.logger.info(
            f"Total {total} related papers to compute relatedness scores for and filter."
        )

        def paper2text(paper_id: str) -> str:
            node_data = self.reference_graph.nodes[paper_id]
            title = node_data.get("title", "")
            abstract = node_data.get("abstract", "")
            return f"Title: {title}\nAbstract: {abstract}"

        model = self._get_embedding_model()

        seed_texts = [paper2text(pid) for pid in seed_paper_ids]
        seed_embeddings = model.encode(
            seed_texts,
            convert_to_tensor=True,
            batch_size=self.config.ModuleInfo.WorkCollector.sentence_transformer_batch_size,
            show_progress_bar=True,
        )
        saved_papers = dict()
        embedding_scores: Dict[tuple[str, str], float] = {}
        for seed_pid in seed_paper_ids:
            saved_papers[seed_pid] = set()
            references = list(self.reference_graph.successors(seed_pid))
            citations = list(self.reference_graph.predecessors(seed_pid))
            related_pids = references + citations
            related_pids = [paper_id for paper_id in related_pids if paper_id not in self.ignore_paper]
            if len(related_pids) == 0:
                self.logger.warning(f"No related papers found for seed paper {seed_pid}, skipping relatedness computation.")
                continue
            related_texts = [paper2text(pid) for pid in related_pids]
            related_embeddings = model.encode(
                related_texts,
                convert_to_tensor=True,
                batch_size=self.config.ModuleInfo.WorkCollector.sentence_transformer_batch_size,
                show_progress_bar=True,
            )
            cosine_scores = util.pytorch_cos_sim(
                seed_embeddings[seed_paper_ids.index(seed_pid)], related_embeddings
            )

            top_k = min(
                self.config.ModuleInfo.WorkCollector.related_work_top_k,
                len(related_pids),
            )
            top_results = torch.topk(cosine_scores, k=top_k)
            for score, idx in zip(top_results[0][0], top_results[1][0]):
                pid = related_pids[idx]
                sim_score = score.item()
                if (
                    sim_score
                    >= self.config.ModuleInfo.WorkCollector.related_work_threshold
                ):
                    saved_papers[seed_pid].add(pid)
                    embedding_scores[(str(seed_pid), str(pid))] = sim_score
                    if self.config.ModuleInfo.WorkCollector.RAG_source_use_embedding_filter and \
                        not self.config.ModuleInfo.WorkCollector.RAG_source_use_LLM_filter:
                        self.graph_paper_ids.add(pid)

            saved_papers[seed_pid].difference_update(seed_paper_ids)

        self.logger.info(
            f"Selected {len(set().union(*saved_papers.values()))} papers based on sentence-transformer relatedness scores with threshold {self.config.ModuleInfo.WorkCollector.related_work_threshold}, topk {self.config.ModuleInfo.WorkCollector.related_work_top_k}."
        )
        self._last_graph_expansion_pre_llm_candidate_ids = set().union(
            *saved_papers.values()
        )

        tasks = []
        for seed_pid in seed_paper_ids:
            related_pids = list(saved_papers[seed_pid])
            if not related_pids:
                continue

            seed_title = self.reference_graph.nodes[seed_pid].get("title", "")
            seed_abstract = self.reference_graph.nodes[seed_pid].get("abstract", "")

            for related_pid in related_pids:
                hash_key = relatedness_cache_key(
                    research_context,
                    seed_pid,
                    related_pid,
                )
                if hash_key in self.relatedness_cache and "relevance_score" in self.relatedness_cache.get(hash_key, {}).keys():
                    self.logger.info(
                        f"Relatedness cache hit for seed {seed_pid} and related {related_pid}."
                    )
                else:
                    related_title = self.reference_graph.nodes[related_pid].get("title", "")
                    related_abstract = self.reference_graph.nodes[related_pid].get("abstract", "")

                    prompt = PAPER_RELATEDNESS_BASED_ON_TITLE_AND_ABSTRACT.format(
                        research_context=research_context_json,
                        seed_title=seed_title,
                        seed_abstract=seed_abstract,
                        candidate_title=related_title,
                        candidate_abstract=related_abstract,
                    )
                    tasks.append((hash_key, seed_pid, related_pid, prompt))
        
        if tasks:
            prompts = [task[3] for task in tasks]
            responses = self.chat_agent.batch_remote_chat(
                prompts,
                temperature=self.config.ModuleInfo.WorkCollector.relatedness_temperature,
                desc="Computing relatedness scores",
            )
            for i, response in enumerate(responses):
                hash_key, seed_pid, related_pid, _ = tasks[i]
                try:
                    response = extract_json(response)
                    response["seed_paper_id"] = seed_pid
                    response["related_paper_id"] = related_pid
                    response["research_context_fingerprint"] = research_context.get(
                        "input_fingerprint",
                        "",
                    )
                    self.relatedness_cache[hash_key] = response
                except Exception as e:
                    self.logger.error(
                        f"Error processing relatedness response for seed {seed_pid} and related {related_pid}: {e}"
                    )
                    self.relatedness_cache[hash_key] = {
                        "relevance_score": 0.0,
                        "seed_paper_id": seed_pid,
                        "related_paper_id": related_pid,
                        "research_context_fingerprint": research_context.get(
                            "input_fingerprint",
                            "",
                        ),
                    }

        for seed_pid in seed_paper_ids:
            to_remove = set()
            for related_pid in saved_papers[seed_pid]:
                hash_key = relatedness_cache_key(
                    research_context,
                    seed_pid,
                    related_pid,
                )
                relatedness_info = self.relatedness_cache.get(hash_key, {})
                relatedness_score = relatedness_info.get("relevance_score", 0.0)
                if (
                    relatedness_score
                    < self.config.ModuleInfo.WorkCollector.related_work_threshold_for_llm
                ):
                    to_remove.add(related_pid)
            saved_papers[seed_pid].difference_update(to_remove)

        if self.config.ModuleInfo.WorkCollector.RAG_source_use_LLM_filter and \
            not self.config.ModuleInfo.WorkCollector.RAG_source_downloadable_only:
            self.graph_paper_ids.update(set().union(*saved_papers.values()))

        self.logger.info(
            f"After LLM-based filtering, {len(set().union(*saved_papers.values()))} papers remain with threshold {self.config.ModuleInfo.WorkCollector.related_work_threshold_for_llm}."
        )
        expanded_paper_ids = sorted(set().union(*saved_papers.values()))
        self._last_fulltext_candidate_records = self._build_fulltext_candidate_records(
            saved_papers,
            embedding_scores,
            research_context,
        )
        return expanded_paper_ids

    def expand_seed_papers_by_reference_and_citation(
        self,
        seed_paper_ids: List[str],
        graph_fallback: bool = False,
        _defer_fulltext_budget: bool = False,
    ):
        """Collect related papers based on the given seed paper IDs."""
        context_seed_paper_ids = set(getattr(self, "context_seed_paper_ids", set()) or set())
        metadata_only_roots = set(
            getattr(self, "metadata_only_graph_seed_ids", set()) or set()
        )
        graph_seed_paper_ids = [
            paper_id
            for paper_id in [*seed_paper_ids, *sorted(metadata_only_roots)]
            if paper_id not in context_seed_paper_ids
        ]
        graph_seed_paper_ids = list(dict.fromkeys(graph_seed_paper_ids))
        if metadata_only_roots:
            self.logger.info(
                "Including %s metadata-only SH graph roots in citation expansion; "
                "they remain ineligible for direct writing evidence.",
                len(metadata_only_roots),
            )
        if not graph_seed_paper_ids:
            self.logger.info(
                "Only context seeds were selected; skipping citation-graph expansion."
            )
            return []
        if self.expand_in_local_paper_graph and self.paper_graph_retriever and not graph_fallback:
            self.logger.info("Expanding seed papers by local paper graph...")
            expanded_paper_ids, failed_seed_papers = self.expand_and_filter_in_local_paper_graph(
                graph_seed_paper_ids
            )
            local_candidate_records = list(
                getattr(self, "_last_fulltext_candidate_records", []) or []
            )
            local_pre_llm_candidate_ids = set(
                getattr(self, "_last_graph_expansion_pre_llm_candidate_ids", set())
                or set()
            )
            fallback_candidate_records = []
            fallback_pre_llm_candidate_ids = set()
            if self.use_ds_when_graph_fail:
                self.logger.info(f"graph expansion fallback enabled. Expand {len(failed_seed_papers)} paper with citation")
                fallback_expansion = self.expand_seed_papers_by_reference_and_citation(
                    failed_seed_papers,
                    True,
                    _defer_fulltext_budget=True,
                )
                fallback_candidate_records = list(
                    getattr(self, "_last_fulltext_candidate_records", []) or []
                )
                fallback_pre_llm_candidate_ids = set(
                    getattr(self, "_last_graph_expansion_pre_llm_candidate_ids", set())
                    or set()
                )
                self.logger.info(f"graph expansion fallback enabled. get {len(fallback_expansion)} expanded paper")
                expanded_paper_ids = sorted(
                    set(expanded_paper_ids).union(set(fallback_expansion))
                )
            candidate_records = self._merge_fulltext_candidate_records(
                local_candidate_records,
                fallback_candidate_records,
            )
            self._last_fulltext_candidate_records = candidate_records
            self._last_graph_expansion_pre_llm_candidate_ids = (
                local_pre_llm_candidate_ids | fallback_pre_llm_candidate_ids
            )
            if _defer_fulltext_budget:
                return expanded_paper_ids
            selected_paper_ids = self._select_fulltext_budget_candidates(candidate_records)
            self.logger.info(f"valid RAG paper ids sources num: {len(self.graph_paper_ids)}")
            # Local graph keynotes can avoid a PDF round trip, while the
            # standard deep-reading fallback receives only the globally
            # selected papers through the caller's return value.
            return selected_paper_ids
        
        resolved_seed_paper_ids = self.update_reference_graph(graph_seed_paper_ids)
        if not resolved_seed_paper_ids:
            self.logger.warning("No seed papers resolved to OpenAlex Work IDs for graph expansion.")
            return []
        related_paper_ids = self.compute_relatedness_scores_and_filter(
            resolved_seed_paper_ids
        )
        candidate_records = list(
            getattr(self, "_last_fulltext_candidate_records", []) or []
        )

        if _defer_fulltext_budget:
            return related_paper_ids

        selected_paper_ids = self._select_fulltext_budget_candidates(candidate_records)
        
        for i in range(
            min(
                self.config.ModuleInfo.WorkCollector.log_related_work_num,
                len(selected_paper_ids),
            )
            if self.config.ModuleInfo.WorkCollector.log_related_work_num > 0
            else len(selected_paper_ids)
        ):
            pid = selected_paper_ids[i]
            self.logger.info(
                f"Related Paper ID: {pid}, Title: {self.reference_graph.nodes[pid].get('title', 'N/A')}"
            )

        valid_expanded_paper_ids = self.data_manager.download_and_parse_papers(
            selected_paper_ids
        )
        self.selected_fulltext_paper_ids = set(valid_expanded_paper_ids)
        self.graph_paper_ids.update(valid_expanded_paper_ids)
        self.logger.info(f"valid RAG paper ids sources num: {len(self.graph_paper_ids)}")
        return valid_expanded_paper_ids

    def expand_and_filter_in_local_paper_graph(self, seed_paper_ids: List[str]):
        expanded_papers, failed_seed_papers = self.expand_papers_by_local_paper_graph(seed_paper_ids)
        filtered_papers = self.filter_papers_local_paper_graph(expanded_papers, seed_paper_ids)
        return filtered_papers, failed_seed_papers

    def expand_papers_by_local_paper_graph(self, seed_paper_ids: List[str]):
        failed_seed_papers = []
        if not self.expand_in_local_paper_graph or not self.paper_graph_retriever:
            self.logger.error("Error: expand_in_local_paper_graph False or paper_graph_retriever not initialized")
            raise ValueError("expand_in_local_paper_graph False or paper_graph_retriever not initialized")
        
        seed_paper_paper_graph_ids = []
        local_seed_origins: Dict[str, list[str]] = {}
        local_seed_modes: Dict[str, str] = {}
        configured_modes = dict(getattr(self, "graph_seed_expansion_modes", {}) or {})
        for seed_paper in seed_paper_ids:
            try:
                title, abstract = self.data_manager.get_paper_title_abstract(seed_paper)
            except Exception as e:
                if self.use_ds_when_graph_fail:
                    self.logger.info(f" fallback paper: {seed_paper} fail to expand in graph")
                    failed_seed_papers.append(seed_paper)
                else:
                    self.logger.error(f"[Strange err: previous getting success] Error getting title and abstract for seed paper {seed_paper}: {e}. Skipping this seed paper for local graph expansion.")
                continue
            results = self.paper_graph_retriever.search_by_paper_title(title)
            if not results:
                if self.use_ds_when_graph_fail:
                    self.logger.info(f"paper {title} not in graph. fall back to original api method")
                    failed_seed_papers.append(seed_paper)
                    continue
                else:
                    self.logger.error(f"error out of expectation: fail to get seed paper {title} in paper graph (previous can)")
                    raise ValueError(f"fail to get seed paper {title} in paper graph (previous can)")
            local_paper_id = results[0]["id"]
            seed_paper_paper_graph_ids.append(local_paper_id)
            local_seed_origins.setdefault(local_paper_id, []).append(seed_paper)
            local_seed_modes[local_paper_id] = str(
                configured_modes.get(seed_paper) or "evidence_normal"
            )

        normal_seed_ids = [
            paper_id
            for paper_id in seed_paper_paper_graph_ids
            if local_seed_modes.get(paper_id) != "bounded_exploration"
        ]
        exploration_seed_ids = [
            paper_id
            for paper_id in seed_paper_paper_graph_ids
            if local_seed_modes.get(paper_id) == "bounded_exploration"
        ]
        normal_depth = max(
            0,
            int(self.config.ModuleInfo.WorkCollector.reference_graph_depth),
        )
        exploration_depth = min(
            normal_depth,
            max(
                0,
                int(
                    self._work_collector_setting(
                        "exploration_seed_reference_graph_depth",
                        1,
                    )
                ),
            ),
        )
        local_lineage_by_node_id: Dict[str, list[Dict]] = {}

        def expand_with_lineage(
            local_seed_ids: Sequence[str],
            depth: int,
        ) -> list[str]:
            if not local_seed_ids:
                return []
            lineage_expander = getattr(
                self.paper_graph_retriever,
                "expand_nodes_with_lineage",
                None,
            )
            if callable(lineage_expander):
                expanded, raw_lineage = lineage_expander(list(local_seed_ids), depth)
                if isinstance(raw_lineage, Mapping):
                    for local_node_id, raw_paths in raw_lineage.items():
                        paths = raw_paths if isinstance(raw_paths, Sequence) and not isinstance(
                            raw_paths, (str, bytes)
                        ) else []
                        for raw_path in paths:
                            path = dict(raw_path) if isinstance(raw_path, Mapping) else {}
                            root_local_node_id = str(path.get("root_node_id") or "").strip()
                            for root_seed_paper_id in local_seed_origins.get(
                                root_local_node_id,
                                [],
                            ):
                                record = {
                                    "root_seed_paper_id": root_seed_paper_id,
                                    "parent_node_id": str(
                                        path.get("parent_node_id") or ""
                                    ).strip(),
                                    "lineage_depth": max(
                                        1,
                                        int(path.get("lineage_depth") or 1),
                                    ),
                                    "lineage_precision": "EXACT_LOCAL_GRAPH_PATH",
                                }
                                existing = local_lineage_by_node_id.setdefault(
                                    str(local_node_id),
                                    [],
                                )
                                if record not in existing:
                                    existing.append(record)
                return list(expanded or [])

            # Third-party/local test retrievers may only implement the legacy
            # API. Preserve a conservative root-only retrieval record instead
            # of assigning an invented parent or direct-evidence role.
            expanded = self.paper_graph_retriever.expand_nodes(list(local_seed_ids), depth)
            for local_node_id in expanded or []:
                if local_node_id in local_seed_ids:
                    continue
                for local_seed_id in local_seed_ids:
                    for root_seed_paper_id in local_seed_origins.get(local_seed_id, []):
                        record = {
                            "root_seed_paper_id": root_seed_paper_id,
                            "parent_node_id": "",
                            "lineage_depth": 1,
                            "lineage_precision": "ROOT_ONLY_LEGACY_RETRIEVER",
                        }
                        existing = local_lineage_by_node_id.setdefault(
                            str(local_node_id),
                            [],
                        )
                        if record not in existing:
                            existing.append(record)
            return list(expanded or [])

        expanded_papers = []
        if normal_seed_ids:
            expanded_papers.extend(expand_with_lineage(normal_seed_ids, normal_depth))
        if exploration_seed_ids and exploration_depth:
            expanded_papers.extend(
                expand_with_lineage(exploration_seed_ids, exploration_depth)
            )
        self._local_graph_expansion_lineage_by_node_id = local_lineage_by_node_id
        self.logger.info(f"expansion finished")
        return list(set(expanded_papers) - set(seed_paper_paper_graph_ids)), failed_seed_papers

    def filter_papers_local_paper_graph(self, expanded_papers: List[str], seed_paper_ids: List[str]):
        self.logger.info(f"paper number: {len(expanded_papers)} before filter")
        expanded_papers_info = []
        for paper in expanded_papers:
            self.logger.info(f"retrieving paper_id_in_graph {paper} in graph...")
            paper_info = self.paper_graph_retriever.search_by_node_id(paper)
            if not paper_info:
                self.logger.info(f"fail to retrieve paper_id_in_graph {paper} in graph: return info None...")
                self.logger.info(f"return: {paper_info}")
                continue
            item = dict(paper_info[0])
            item["_local_graph_node_id"] = str(paper)
            expanded_papers_info.append(item)

        # Collect all titles that need to be queried
        valid_titles = []
        valid_paper_info_map = {}
        local_node_by_title = {}
        for paper_info in expanded_papers_info:
            paper_title = paper_info["paper_title"]
            if not paper_title:
                self.logger.warning(f"paper_title is empty")
                self.logger.warning(f"complete paper info: {paper_info}")
                continue
            valid_titles.append(paper_title)
            valid_paper_info_map[paper_title] = paper_info
            local_node_by_title[paper_title] = str(
                paper_info.get("_local_graph_node_id") or ""
            )

        # Batch query papers by title
        self.logger.info(f"Batch querying {len(valid_titles)} papers by title...")

        self.batch_retrieve_paper_id_for_nodes = True
        expanded_papers_ids = []
        local_node_to_paper_id: Dict[str, str] = {}
        if self.batch_retrieve_paper_id_for_nodes:
            batch_results = self.get_paper_with_title_batch(valid_titles)
            
            # Process batch results
            # get_paper_with_title_batch returns Dict[str, dict]: title -> paper_info
            for paper_title in valid_titles:
                api_paper_info = batch_results.get(paper_title)
                if api_paper_info is None or not api_paper_info:
                    self.logger.warning(f"{paper_title} cannot be retrieved from arxiv or semantic scholar")
                    continue

                paper_id = self.data_manager._resolve_paper_reference_id(api_paper_info)

                if paper_id is None or not paper_id:
                    self.logger.warning(f"{paper_title} cannot be retrieved from arxiv or semantic scholar")
                    continue
                expanded_papers_ids.append(paper_id)
                local_node_id = local_node_by_title.get(paper_title, "")
                if local_node_id:
                    local_node_to_paper_id[local_node_id] = str(paper_id)
        else:
            for paper_title in valid_titles:
                api_paper_info = self.get_paper_with_title(paper_title)
                if api_paper_info is None or not api_paper_info:
                    self.logger.warning(f"{paper_title} cannot be retrieved from arxiv or semantic scholar")
                    continue

                paper_id = self.data_manager._resolve_paper_reference_id(api_paper_info)

                if paper_id is None or not paper_id:
                    self.logger.warning(f"{paper_title} cannot be retrieved from arxiv or semantic scholar")
                    continue
                expanded_papers_ids.append(paper_id)
                local_node_id = local_node_by_title.get(paper_title, "")
                if local_node_id:
                    local_node_to_paper_id[local_node_id] = str(paper_id)

        self._record_local_graph_expansion_provenance(local_node_to_paper_id)
        self.graph_paper_ids.update(expanded_papers_ids)
        # The local graph historically admitted all resolvable candidates to
        # the active set before advanced filtering.  Remember that full scope
        # so the final full-text budget submission can remove both low-
        # embedding and LLM-rejected candidates, not only those that reached
        # the LLM stage.
        self._last_graph_expansion_pre_llm_candidate_ids = set(expanded_papers_ids)
        self.logger.info(f"expansion in graph find {len(expanded_papers_ids)} valid papers (can be found in arxiv/semantic scholar)")
        
        if self.advanced_filter_in_local_paper_graph_expansion:
            self.logger.info(f"seed papers: {seed_paper_ids}")
            self.logger.info(f"papers before filter: {expanded_papers_ids}")
            
            def paper2text(paper_id: str) -> str:
                try:
                    title, abstract = self.data_manager.get_paper_title_abstract(paper_id)
                except Exception as e:
                    self.logger.error(f"Error getting title and abstract for paper {paper_id}: {e}. Using empty title and abstract for relatedness computation.")
                    title, abstract = "", ""
                return f"Title: {title}\nAbstract: {abstract}"

            model = self._get_embedding_model()

            seed_texts = [paper2text(pid) for pid in seed_paper_ids]
            seed_embeddings = model.encode(
                seed_texts,
                convert_to_tensor=True,
                batch_size=self.config.ModuleInfo.WorkCollector.sentence_transformer_batch_size,
                show_progress_bar=True,
            )
            saved_papers = dict()
            embedding_scores: Dict[tuple[str, str], float] = {}
            for seed_pid in seed_paper_ids:
                saved_papers[seed_pid] = set()

                related_pids = [paper_id for paper_id in expanded_papers_ids if paper_id not in self.ignore_paper]
                if len(related_pids) == 0:
                    self.logger.warning(f"No related papers found for seed paper {seed_pid}, skipping relatedness computation.")
                    continue
                related_texts = [paper2text(pid) for pid in related_pids]
                related_embeddings = model.encode(
                    related_texts,
                    convert_to_tensor=True,
                    batch_size=self.config.ModuleInfo.WorkCollector.sentence_transformer_batch_size,
                    show_progress_bar=True,
                )
                cosine_scores = util.pytorch_cos_sim(
                    seed_embeddings[seed_paper_ids.index(seed_pid)], related_embeddings
                )

                top_k = min(
                    self.config.ModuleInfo.WorkCollector.related_work_top_k,
                    len(related_pids),
                )
                top_results = torch.topk(cosine_scores, k=top_k)
                for score, idx in zip(top_results[0][0], top_results[1][0]):
                    pid = related_pids[idx]
                    sim_score = score.item()
                    if (
                        sim_score
                        >= self.config.ModuleInfo.WorkCollector.related_work_threshold
                    ):
                        self.logger.info(f"{pid}: {seed_pid} embedding sim {sim_score} > {self.config.ModuleInfo.WorkCollector.related_work_threshold}")
                        saved_papers[seed_pid].add(pid)
                        embedding_scores[(str(seed_pid), str(pid))] = sim_score
                        if self.config.ModuleInfo.WorkCollector.RAG_source_use_embedding_filter and \
                            not self.config.ModuleInfo.WorkCollector.RAG_source_use_LLM_filter:
                            self.graph_paper_ids.add(pid)
                    else:
                        self.logger.info(f"{pid}: {seed_pid} embedding sim {sim_score} < {self.config.ModuleInfo.WorkCollector.related_work_threshold}")

                saved_papers[seed_pid].difference_update(seed_paper_ids)

            self.logger.info(
                f"Selected {len(set().union(*saved_papers.values()))} papers based on sentence-transformer relatedness scores with threshold {self.config.ModuleInfo.WorkCollector.related_work_threshold}, topk {self.config.ModuleInfo.WorkCollector.related_work_top_k}."
            )

            research_context = self.get_project_research_context()
            research_context_json = json.dumps(
                relevance_context_payload(research_context),
                ensure_ascii=False,
            )
            tasks = []
            for seed_pid in seed_paper_ids:
                related_pids = list(saved_papers[seed_pid])
                if not related_pids:
                    continue
                try:
                    seed_title, seed_abstract = self.data_manager.get_paper_title_abstract(seed_pid)
                except Exception as e:
                    self.logger.error(f"Error getting title and abstract for seed paper {seed_pid}: {e}. Skipping LLM-based relatedness computation for this seed.")
                    continue

                for related_pid in related_pids:
                    hash_key = relatedness_cache_key(
                        research_context,
                        seed_pid,
                        related_pid,
                    )
                    if hash_key in self.relatedness_cache and "relevance_score" in self.relatedness_cache.get(hash_key, {}).keys():
                        self.logger.info(
                            f"Relatedness cache hit for seed {seed_pid} and related {related_pid}."
                        )
                    else:
                        try:
                            related_title, related_abstract = self.data_manager.get_paper_title_abstract(related_pid)
                        except Exception as e:
                            self.logger.error(f"Error getting title and abstract for related paper {related_pid}: {e}. Skipping LLM-based relatedness computation for this pair.")
                            continue

                        prompt = PAPER_RELATEDNESS_BASED_ON_TITLE_AND_ABSTRACT.format(
                            research_context=research_context_json,
                            seed_title=seed_title,
                            seed_abstract=seed_abstract,
                            candidate_title=related_title,
                            candidate_abstract=related_abstract,
                        )
                        tasks.append((hash_key, seed_pid, related_pid, prompt))
            
            if tasks:
                prompts = [task[3] for task in tasks]
                responses = self.chat_agent.batch_remote_chat(
                    prompts,
                    temperature=self.config.ModuleInfo.WorkCollector.relatedness_temperature,
                    desc="Computing relatedness scores",
                )
                for i, response in enumerate(responses):
                    hash_key, seed_pid, related_pid, _ = tasks[i]
                    try:
                        response = extract_json(response)
                        response["seed_paper_id"] = seed_pid
                        response["related_paper_id"] = related_pid
                        response["research_context_fingerprint"] = research_context.get(
                            "input_fingerprint",
                            "",
                        )
                        self.relatedness_cache[hash_key] = response
                    except Exception as e:
                        self.logger.error(
                            f"Error processing relatedness response for seed {seed_pid} and related {related_pid}: {e}"
                        )
                        self.relatedness_cache[hash_key] = {
                            "relevance_score": 0.0,
                            "seed_paper_id": seed_pid,
                            "related_paper_id": related_pid,
                            "research_context_fingerprint": research_context.get(
                                "input_fingerprint",
                                "",
                            ),
                        }

            for seed_pid in seed_paper_ids:
                to_remove = set()
                for related_pid in saved_papers[seed_pid]:
                    hash_key = relatedness_cache_key(
                        research_context,
                        seed_pid,
                        related_pid,
                    )
                    relatedness_info = self.relatedness_cache.get(hash_key, {})
                    relatedness_score = relatedness_info.get("relevance_score", 0.0)
                    if (
                        relatedness_score
                        < self.config.ModuleInfo.WorkCollector.related_work_threshold_for_llm
                    ):
                        to_remove.add(related_pid)
                saved_papers[seed_pid].difference_update(to_remove)

            if self.config.ModuleInfo.WorkCollector.RAG_source_use_LLM_filter and \
                not self.config.ModuleInfo.WorkCollector.RAG_source_downloadable_only:
                self.graph_paper_ids.update(set().union(*saved_papers.values()))

            self.logger.info(
                f"After LLM-based filtering, {len(set().union(*saved_papers.values()))} papers remain with threshold {self.config.ModuleInfo.WorkCollector.related_work_threshold_for_llm}."
            )
            expanded_papers_ids = sorted(set().union(*saved_papers.values()))
            self.logger.info(f"expanded papers after filter: {expanded_papers_ids}")
            self._last_fulltext_candidate_records = self._build_fulltext_candidate_records(
                saved_papers,
                embedding_scores,
                research_context,
            )
        else:
            # A caller may disable the advanced ranker, but the downstream
            # full-text budget still needs one record per discovered paper.
            # These intentionally score zero because no embedding score was
            # computed in this mode; paper-id ordering remains deterministic.
            self._last_fulltext_candidate_records = [
                {
                    "paper_id": str(paper_id),
                    "max_embedding_relatedness": 0.0,
                    "max_llm_relevance_score": 0.0,
                    "best_seed_id": "",
                    "matched_seed_ids": [],
                    "seed_embedding_relatedness": {},
                    "seed_llm_relevance_scores": {},
                }
                for paper_id in sorted(set(expanded_papers_ids))
            ]
            self._last_graph_expansion_pre_llm_candidate_ids = set(
                expanded_papers_ids
            )

        return expanded_papers_ids


@hydra.main(config_path="../config", config_name="deep_survey_batch_xiaomi_fast", version_base=None)
def main(config):
    config = merge_with_default_survey_config(config)
    title = "Learning to Refine Source Representations for Neural Machine Translation"
    work_collector = WorkCollector(config)
    print(work_collector.get_paper_with_title(title))

if __name__ == "__main__":
    main()
