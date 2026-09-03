from typing import List
import json
import os
import pickle
from pathlib import Path
from typing import Any, Dict, List
from collections.abc import Mapping, Sequence
import networkx as nx
from utils.api_call import ArxivAPI, ChatAgent, OpenAlexAPI, SemanticScholarAPI
from utils.utils import get_hash, extract_json
import diskcache as dc
import time
from modules.pe import (
    PAPER_DEEP_READING,
    PAPER_SECTION_READING,
    PAPER_KEYNOTE_SYNTHESIS,
    PAPER_KEYNOTE_COMPACTION,
    PAPER_CLUSTERING,
    PROPOSE_QUESTIONS_FOR_CLUSTER,
    ANSWER_QUESTION_FOR_PAPERS,
    INTER_CLUSTER_ANALYSIS,
    PAPER_CLUSTERING_CREATING,
    PAPER_CLUSTERING_ASSIGNING,
    ERROR_FEEDBACK_PROMPT,
    PAPER_RELATIONSHIP_ANALYSIS,
    CLUSTER_TABLE_GENERATION
)
from modules.paper_graph_retriever import PaperGraphRetriever
from utils.mineru_section_packer import (
    DEFAULT_EXCLUDED_SECTION_PATTERNS,
    derive_effective_body_budget,
    pack_mineru_markdown_by_complete_sections,
    render_packet_outline,
)
from src.pipeline.evidence_coverage_ledger import (
    EVIDENCE_COVERAGE_LEDGER_SCHEMA_VERSION,
)
from src.pipeline.sh_cluster_projection import (
    SH_CLUSTER_COVERAGE_SCHEMA_VERSION,
    build_cluster_sh_coverage_projection,
)
from src.pipeline.sh_graph_provenance import SH_GRAPH_PROVENANCE_SCHEMA_VERSION
from src.pipeline.paper_identity import canonical_paper_id
import hdbscan
from sentence_transformers import SentenceTransformer
from utils.rich_logger import get_logger
import math
import requests
import xml.etree.ElementTree as ET
import copy
import re


# A full-text packet can cost several minutes at the configured 512k limit.
# One malformed/empty response is a paper-level readability failure, not a
# reason to spend another complete long-context request on the same packet.
SECTION_PACKET_MAX_INVALID_RESPONSES = 1
PAPER_KEYNOTE_FAILURE_SCHEMA_VERSION = "paper_keynote_failure_v1"
# These are intentionally paper-specific exceptions. Their full-text payloads
# make deep-reading requests disproportionately expensive, so retain them
# through abstracts without submitting those requests.
FULLTEXT_READING_BYPASS_PAPER_IDS = frozenset({"W2074305322", "W4225610241"})
COMPLETE_SECTION_READING_SOURCES = frozenset(
    {"complete_sections_single_packet", "complete_section_packet_synthesis"}
)


class WorkAnalyzer:
    def __init__(self, config, work_collector, paper_graph_retriever = None):
        self.config = config
        self.chat_agent = ChatAgent(config)
        self.semantic_scholar_api = SemanticScholarAPI(config)
        self.arxiv_api = ArxivAPI(config)
        self.logger = get_logger("WorkAnalyzer")
        self.work_collector = work_collector
        self.openalex_api = getattr(
            getattr(work_collector, "data_manager", None), "openalex_api", None
        )
        if self.openalex_api is None:
            self.openalex_api = OpenAlexAPI(config)
        self.relation_analysis_graph = None
        self.relation_analysis_table = None
        self.sh_cluster_coverage_artifact = {}
        # These structures intentionally live only for the lifetime of one
        # WorkAnalyzer / survey run. They prevent a known-unrecoverable paper
        # from repeatedly calling metadata APIs or long-context LLM requests.
        self.paper_keynote_failure_records = {}
        self._paper_keynote_negative_cache = {}
        self._section_keynote_states = {}

        self.cluster_fast_mode = self.config.ModuleInfo.WorkAnalyzer.cluster_assign_fast_mode
        self.use_graph_keynotes = self.config.ModuleInfo.WorkAnalyzer.use_local_paper_graph_keynotes
        self.use_ds_keynotes_when_graph_fail = self.config.ModuleInfo.WorkAnalyzer.use_ds_keynotes_when_graph_fail
        if self.use_graph_keynotes:
            if not paper_graph_retriever:
                self.paper_graph_retriever = PaperGraphRetriever(config)
            else:
                self.paper_graph_retriever = paper_graph_retriever
        
        self.max_problems_per_cluster_proposed = 5
        self.max_words_num_in_inter_cluster_analysis = 800
        self.max_words_num_in_intra_cluster_answer = 200

        self.cache_path = self.config.BasicInfo.cache_path
        os.makedirs(self.cache_path, exist_ok=True)
        self.reference_graph = self._load_openalex_reference_graph()

        # cache for paper keynotes
        self.paper_keynote_cache = dc.Cache(
            os.path.join(self.cache_path, "paper_keynotes")
        )

        # caches for clustering and relationship graph/table
        self.cluster_cache = dc.Cache(
            os.path.join(self.cache_path, "cluster_cache")
        )
        self.relation_graph_cache = dc.Cache(
            os.path.join(self.cache_path, "relation_graph_cache")
        )

        self.paper_abstract_cache = self.work_collector.paper_abstract_cache

    def _load_openalex_reference_graph(self):
        reference_graph = getattr(self.work_collector, "reference_graph", None)
        if reference_graph is None:
            ref_graph_path = os.path.join(self.cache_path, "reference_graph.pkl")
            if not os.path.exists(ref_graph_path):
                return None
            try:
                with open(ref_graph_path, "rb") as reader:
                    reference_graph = pickle.load(reader)
            except Exception as exc:
                self.logger.warning(f"Unable to load reference graph cache: {exc}")
                return None

        expected_schema = int(
            getattr(
                self.config.APIInfo,
                "openalex_graph_cache_schema_version",
                2,
            )
            or 2
        )
        graph_metadata = getattr(reference_graph, "graph", {})
        if (
            graph_metadata.get("provider") != "openalex"
            or graph_metadata.get("schema_version") != expected_schema
        ):
            return None
        return reference_graph

    def read_papers_and_write_keynotes(
        self,
        papers: List[str],
        retry: int = 1,
        ds_keynotes_fallback: bool = False,
        force_complete_section_paper_ids: Sequence[str] | None = None,
    ):

        if self.config.ModuleInfo.WorkAnalyzer.abstract_only_mode:
            self.logger.info("Abstract-only mode enabled, fetching abstracts instead of deep reading and get keynotes.")
            return self.work_collector.add_papers_abstracts_in_cache(papers, retry=retry)

        # Keep alternate launchers on the same safe upgrade path as the deep
        # survey launcher.  Retries receive the resolved list explicitly, so
        # this bounded selector is evaluated only once for a read operation.
        if force_complete_section_paper_ids is None and retry == 1:
            upgrade_plan = self.prepare_complete_section_upgrade_candidates(papers)
            force_complete_section_paper_ids = list(
                upgrade_plan.get("force_complete_section_paper_ids", [])
                if isinstance(upgrade_plan, Mapping)
                else []
            )

        if retry > self.config.ModuleInfo.WorkAnalyzer.paper_reading_max_retry:
            self.logger.error("Exceeded maximum retries for reading papers.")
            self.logger.error(f"Papers failed to read: {papers}")
            return papers

        requested_papers = list(dict.fromkeys(papers))
        forced_complete_section_ids = {
            canonical_paper_id(paper_id)
            for paper_id in force_complete_section_paper_ids or []
            if canonical_paper_id(paper_id)
        }
        bypassed_papers = [
            paper_id
            for paper_id in requested_papers
            if canonical_paper_id(paper_id) in FULLTEXT_READING_BYPASS_PAPER_IDS
        ]
        for paper_id in bypassed_papers:
            # Do this before the graph/full-text branches so this exact paper
            # can never create a long-context deep-reading request.
            self.logger.info(
                "Skipping deep reading for explicit abstract-only exception: %s",
                paper_id,
            )
            self._try_abstract_keynote_fallback(
                pid=paper_id,
                hash_id=get_hash(paper_id),
                reason="explicit deep-reading bypass for oversized full text",
                failure_code="explicit_fulltext_reading_bypass",
            )

        negative_cache = self._paper_keynote_negative_failures()
        permanently_failed = [
            paper_id for paper_id in requested_papers if paper_id in negative_cache
        ]
        papers = [
            paper_id
            for paper_id in requested_papers
            if (
                canonical_paper_id(paper_id) not in FULLTEXT_READING_BYPASS_PAPER_IDS
                and paper_id not in negative_cache
            )
        ]
        if not papers:
            # A previous attempt in this run already established that neither
            # full text nor the configured abstract fallback can serve these
            # papers. Do not hit OpenAlex or the LLM again.
            return permanently_failed

        # 这里retry进来会有问题
        if self.config.ModuleInfo.WorkAnalyzer.use_local_paper_graph_keynotes and not ds_keynotes_fallback:
            # extract information for baselines and empty node and write back to graph
            self.logger.info(f"getting keynotes in graph...")
            error_ids =  self.paper_graph_retriever.read_papers_and_write_keynotes(papers)
            if self.use_ds_keynotes_when_graph_fail and error_ids:
                self.logger.info(f"some paper not in graph, number: {len(error_ids)}, use previous methods")
                error_ids =  self.read_papers_and_write_keynotes(
                    papers = error_ids, 
                    retry = retry, 
                    ds_keynotes_fallback = True,
                    force_complete_section_paper_ids=force_complete_section_paper_ids,
                )
            return list(dict.fromkeys([*permanently_failed, *(error_ids or [])]))
        
        tasks = []
        section_packet_states = self._section_packet_states()
        # Permanent failures are returned to the caller, but they must never
        # be placed back into an active LLM retry wave merely because another
        # paper in the same batch is transiently failing.
        err_papers = []
        work_config = self.config.ModuleInfo.WorkAnalyzer
        section_packing_enabled = bool(
            getattr(work_config, "fulltext_section_packing_enabled", True)
        )
        section_max_output_tokens = int(
            getattr(work_config, "fulltext_section_max_output_tokens", 16000) or 16000
        )
        section_workers = int(
            getattr(work_config, "fulltext_section_batch_worker", 1) or 1
        )
        section_max_in_flight_tokens = int(
            getattr(
                work_config,
                "fulltext_section_max_in_flight_tokens",
                800_000,
            )
            or 800_000
        )
        json_response_format = self._json_object_response_format()
        if section_packing_enabled:
            configured_body_limit = int(
                getattr(work_config, "fulltext_section_max_tokens", 512000) or 512000
            )
            prompt_reserve = int(
                getattr(work_config, "fulltext_section_prompt_reserve_tokens", 24000)
                or 24000
            )
            try:
                section_body_budget = derive_effective_body_budget(
                    configured_max_body_tokens=configured_body_limit,
                    context_window_tokens=int(self.config.APIInfo.llm_max_context_length),
                    max_output_tokens=section_max_output_tokens,
                    prompt_reserve_tokens=prompt_reserve,
                )
            except ValueError as exc:
                self.logger.error("Invalid full-text section budget: %s", exc)
                return papers

        for pid in papers:
            try:
                hash_id = get_hash(pid)
                # A legacy keynote is still useful for ordinary RAG, but it
                # cannot prove that the paper was read section-completely.
                # The upgrade selector passes only current-budget
                # citation-expanded candidates here, so bypass their stale
                # cache entry once and overwrite it with an auditable
                # complete-section keynote on success.
                if (
                    hash_id in self.paper_keynote_cache
                    and canonical_paper_id(pid) not in forced_complete_section_ids
                ):
                    continue

                existing_state = section_packet_states.get(pid)
                if existing_state is not None:
                    if existing_state.get("resolved"):
                        continue
                    if existing_state.get("terminal_failure"):
                        # The fallback is finalized after this request wave;
                        # never re-create or re-send a terminal packet.
                        continue
                    tasks.extend(
                        task
                        for packet_index, task in existing_state["packet_tasks"].items()
                        if packet_index not in existing_state["section_responses"]
                    )
                    continue
                try:
                    paper_markdown_text = self.work_collector.get_paper_raw_markdown(pid)

                except Exception as e:
                    self.logger.error(f"Failed to get content for paper ID: {pid}: {e} in PAPER COMPREHENDING. Skipping this paper or use abstract based on config.")
                    if self.config.ModuleInfo.WorkAnalyzer.abstract_when_full_text_fail:
                        if self._try_abstract_keynote_fallback(
                            pid=pid,
                            hash_id=hash_id,
                            reason=f"full-text retrieval failed: {e}",
                            failure_code="fulltext_retrieval_failed",
                        ):
                            continue
                    else:
                        self._record_paper_keynote_failure(
                            pid,
                            code="fulltext_retrieval_failed",
                            reason=f"full-text retrieval failed and abstract fallback is disabled: {e}",
                            permanent=True,
                            fallback_status="disabled",
                        )
                    err_papers.append(pid)
                    continue

                if not section_packing_enabled:
                    max_ctx = self.config.APIInfo.llm_max_context_length
                    overhead = work_config.llm_max_context_overhead_length_in_paper_reading
                    allowed = max_ctx - overhead
                    paper_markdown_text = self.chat_agent.truncate_text(
                        pid, paper_markdown_text, allowed
                    )
                    tasks.append(
                        {
                            "kind": "paper",
                            "paper_id": pid,
                            "hash_id": hash_id,
                            "prompt": PAPER_DEEP_READING.format(
                                paper_markdown_text=paper_markdown_text
                            ),
                        }
                    )
                    continue

                packing, paper_tasks, unsafe_section = self._build_safe_fulltext_tasks(
                    pid=pid,
                    hash_id=hash_id,
                    paper_markdown_text=paper_markdown_text,
                    body_budget=section_body_budget,
                    max_input_tokens=(
                        int(self.config.APIInfo.llm_max_context_length)
                        - section_max_output_tokens
                    ),
                )
                if not paper_tasks:
                    if self._fallback_from_unreadable_fulltext(
                        pid=pid,
                        hash_id=hash_id,
                        packing_status=(
                            packing.status
                            if packing.status in {"no_sections", "unsplittable_section"}
                            else "prompt_budget"
                        ),
                        section=unsafe_section or packing.unsplittable_section,
                    ):
                        continue
                    err_papers.append(pid)
                    continue

                if packing.status == "single_packet":
                    tasks.extend(paper_tasks)
                    continue

                section_packet_states[pid] = {
                    "hash_id": hash_id,
                    "packing": packing,
                    "packet_tasks": {
                        task["packet_index"]: task for task in paper_tasks
                    },
                    "section_responses": {},
                    "non_json_attempts": {},
                    "invalid_response_attempts": {},
                    "terminal_failure": None,
                    "resolved": False,
                }
                tasks.extend(paper_tasks)
            except Exception as e:
                self.logger.error(f"Error preparing paper {pid} for reading: {e} in PAPER COMPREHENDING")
                err_papers.append(pid)

        prompts = [task["prompt"] for task in tasks]
        if not prompts and not err_papers:
            return permanently_failed  # remaining papers were already processed
        elif not prompts:
            self.logger.error("Fail to get raw markdown .No prompt generated. Exit")
            return list(dict.fromkeys([*permanently_failed, *err_papers]))

        try:
            responses = self.chat_agent.batch_remote_chat(
                prompts,
                temperature=self.config.ModuleInfo.WorkAnalyzer.paper_reading_temperature,
                desc="Reading papers",
                workers=section_workers if section_packing_enabled else None,
                strict_input_budget=section_packing_enabled,
                max_output_tokens=section_max_output_tokens,
                response_format=json_response_format,
                max_in_flight_tokens=(
                    section_max_in_flight_tokens if section_packing_enabled else None
                ),
            )
            if not responses:
                self.logger.error("No responses received from LLM during paper reading.")
                raise ValueError("No responses received from LLM during paper reading.")
        except Exception as e:
            self.logger.error(f'Error: {e} , during comprehending papers in getting response from LLM, retrying all...')
            return self.read_papers_and_write_keynotes(
                papers,
                retry=retry + 1,
                ds_keynotes_fallback=ds_keynotes_fallback,
                force_complete_section_paper_ids=force_complete_section_paper_ids,
            )

        for task, response in zip(tasks, responses):
            if task["kind"] == "section":
                if not self._consume_section_packet_response(
                    task,
                    response,
                    section_packet_states,
                ):
                    err_papers.append(task["paper_id"])
                continue
            try:
                if not response:
                    self.logger.warning(
                        "Response is empty or None for paper %s. Marking as error.",
                        task["paper_id"],
                    )
                    err_papers.append(task["paper_id"])
                    continue
                if len(response.strip()) < 10:
                    self.logger.warning(
                        "Extracted keynote too short for paper %s. Marking as error.",
                        task["paper_id"],
                    )
                    err_papers.append(task["paper_id"])
                    continue

                self._cache_paper_keynote(
                    task["paper_id"],
                    task["hash_id"],
                    extract_json(response),
                    fulltext_reading_source=(
                        "complete_sections_single_packet"
                        if "packet_index" in task
                        else "legacy_or_unknown"
                    ),
                )
            except Exception as e:
                self.logger.warning(
                    "Error processing LLM response for paper %s: %s. First 500 chars: %s",
                    task["paper_id"],
                    e,
                    response[:500] if response else "",
                )
                err_papers.append(task["paper_id"])

        for pid in papers:
            state = section_packet_states.get(pid)
            if state is None or state.get("resolved"):
                continue
            packing = state["packing"]
            section_responses = state["section_responses"]
            terminal_failure = state.get("terminal_failure")
            if terminal_failure is not None:
                if self._fallback_after_terminal_section_failure(pid, state):
                    state["resolved"] = True
                    err_papers = [paper_id for paper_id in err_papers if paper_id != pid]
                else:
                    err_papers.append(pid)
                continue
            if len(section_responses) != len(packing.packets):
                self.logger.warning(
                    "Waiting to retry only missing complete-section notes for paper %s; "
                    "expected %s, got %s.",
                    pid,
                    len(packing.packets),
                    len(section_responses),
                )
                err_papers.append(pid)
                continue
            try:
                keynote = self._synthesize_complete_section_notes(
                    paper_title=packing.paper_title or pid,
                    section_notes=[
                        section_responses[index]
                        for index in range(len(packing.packets))
                    ],
                    temperature=self.config.ModuleInfo.WorkAnalyzer.paper_reading_temperature,
                    max_output_tokens=section_max_output_tokens,
                    workers=section_workers,
                    max_in_flight_tokens=section_max_in_flight_tokens,
                )
            except Exception as exc:
                failure_reason = f"complete-section keynote synthesis failed: {exc}"
                self.logger.warning(
                    "Failed to synthesize complete-section notes for paper %s: %s",
                    pid,
                    exc,
                )
                self._record_paper_keynote_failure(
                    pid,
                    code="paper_keynote_synthesis_failed",
                    reason=failure_reason,
                    fallback_status="pending",
                )
                if self._try_abstract_keynote_fallback(
                    pid=pid,
                    hash_id=state["hash_id"],
                    reason=failure_reason,
                    failure_code="paper_keynote_synthesis_failed",
                ):
                    state["resolved"] = True
                    err_papers = [paper_id for paper_id in err_papers if paper_id != pid]
                else:
                    err_papers.append(pid)
                continue
            self._cache_paper_keynote(
                pid,
                state["hash_id"],
                keynote,
                fulltext_reading_source="complete_section_packet_synthesis",
            )
            state["resolved"] = True

        if err_papers:
            retry_papers = list(dict.fromkeys(err_papers))
            negative_cache = self._paper_keynote_negative_failures()
            terminal_papers = [
                paper_id for paper_id in retry_papers if paper_id in negative_cache
            ]
            retryable_papers = [
                paper_id for paper_id in retry_papers if paper_id not in negative_cache
            ]
            if not retryable_papers:
                return list(
                    dict.fromkeys([*permanently_failed, *terminal_papers])
                )
            self.logger.info(
                "Retrying %s readable paper(s) due to previous errors in "
                "keynotes generation; excluding %s terminal failure(s).",
                len(retryable_papers),
                len(terminal_papers),
            )
            retried_failures = self.read_papers_and_write_keynotes(
                retryable_papers,
                retry=retry + 1,
                ds_keynotes_fallback=ds_keynotes_fallback,
                force_complete_section_paper_ids=force_complete_section_paper_ids,
            )
            return list(
                dict.fromkeys(
                    [*permanently_failed, *terminal_papers, *(retried_failures or [])]
                )
            )
        
        return permanently_failed

    def prepare_complete_section_upgrade_candidates(
        self,
        selected_fulltext_expanded_paper_ids: Sequence[str],
    ) -> dict[str, Any]:
        """Choose legacy keynotes that must be reread before SH promotion.

        The collector first constrains the scope to the current run's global
        full-text selection and the SH-level promotion budget.  This method
        then applies the local cache and parsed-Markdown predicates.  It never
        downloads, parses, or expands new papers.
        """

        collector = getattr(self, "work_collector", None)
        select_candidates = getattr(
            collector, "select_complete_section_upgrade_candidates", None
        )
        if not callable(select_candidates):
            return {
                "enabled": False,
                "skipped_reason": "collector_has_no_complete_section_upgrade_selector",
                "force_complete_section_paper_ids": [],
            }
        if bool(
            getattr(
                getattr(getattr(self, "config", None), "ModuleInfo", None),
                "WorkAnalyzer",
                None,
            )
            and getattr(self.config.ModuleInfo.WorkAnalyzer, "abstract_only_mode", False)
        ):
            return {
                "enabled": False,
                "skipped_reason": "abstract_only_mode",
                "force_complete_section_paper_ids": [],
            }
        if not bool(
            getattr(self.config.ModuleInfo.WorkAnalyzer, "fulltext_section_packing_enabled", True)
        ):
            return {
                "enabled": False,
                "skipped_reason": "complete_section_packing_disabled",
                "force_complete_section_paper_ids": [],
            }

        selection = select_candidates(selected_fulltext_expanded_paper_ids)
        selection = dict(selection) if isinstance(selection, Mapping) else {}
        candidate_pairs = selection.get("candidate_pairs") or []
        forced_ids: list[str] = []
        skipped = {
            "already_complete_section_read": 0,
            "missing_parsed_markdown": 0,
            "explicit_fulltext_bypass": 0,
            "terminal_read_failure": 0,
        }
        negative_by_identity = {
            canonical_paper_id(paper_id)
            for paper_id in self._paper_keynote_negative_failures()
            if canonical_paper_id(paper_id)
        }
        data_manager = getattr(collector, "data_manager", None)
        has_parsed_markdown = getattr(data_manager, "_has_parsed_markdown", None)

        for raw_pair in candidate_pairs:
            pair = dict(raw_pair) if isinstance(raw_pair, Mapping) else {}
            paper_id = str(pair.get("paper_id") or "").strip()
            identifier = canonical_paper_id(pair.get("canonical_paper_id") or paper_id)
            if not paper_id or not identifier:
                continue
            if identifier in FULLTEXT_READING_BYPASS_PAPER_IDS:
                skipped["explicit_fulltext_bypass"] += 1
                continue
            if identifier in negative_by_identity:
                skipped["terminal_read_failure"] += 1
                continue
            try:
                cached = self.paper_keynote_cache.get(get_hash(paper_id))
            except (AttributeError, OSError, ValueError):
                cached = None
            cached = dict(cached) if isinstance(cached, Mapping) else {}
            if str(cached.get("fulltext_reading_source") or "") in COMPLETE_SECTION_READING_SOURCES:
                skipped["already_complete_section_read"] += 1
                continue

            parsed_available = False
            if callable(has_parsed_markdown):
                try:
                    parsed_available = bool(has_parsed_markdown(paper_id))
                except (AttributeError, OSError, TypeError, ValueError):
                    parsed_available = False
            if not parsed_available:
                skipped["missing_parsed_markdown"] += 1
                continue
            if paper_id not in forced_ids:
                forced_ids.append(paper_id)

        selection["force_complete_section_paper_ids"] = forced_ids
        selection["upgrade_input_skipped"] = skipped
        self.logger.info(
            "Selected %s current-budget citation-expanded paper(s) for complete-section "
            "keynote upgrade across %s candidate/SH pair(s); already-complete=%s, "
            "missing-markdown=%s, bypassed=%s, terminal=%s.",
            len(forced_ids),
            len(candidate_pairs),
            skipped["already_complete_section_read"],
            skipped["missing_parsed_markdown"],
            skipped["explicit_fulltext_bypass"],
            skipped["terminal_read_failure"],
        )
        return selection

    def promote_complete_section_read_graph_candidates(
        self,
        papers: Sequence[str],
    ) -> dict[str, Any]:
        """Pass only proven complete-section keynotes to the SH promotion gate.

        Abstract fallbacks, legacy/truncated reading cache entries, and failed
        papers remain available to the existing non-evidentiary paths but are
        intentionally absent here.  The collector then performs an independent
        SH-slot assessment before allowing any citation-expanded paper into the
        writing evidence plan.
        """

        collector = getattr(self, "work_collector", None)
        promote = getattr(
            collector, "promote_complete_section_read_graph_candidates", None
        )
        if not callable(promote):
            return {
                "enabled": False,
                "skipped_reason": "collector_has_no_fulltext_promotion_channel",
            }
        fallback_by_identity = {
            canonical_paper_id(paper_id): dict(record)
            for paper_id, record in self._paper_keynote_failure_records().items()
            if isinstance(record, Mapping) and canonical_paper_id(paper_id)
        }
        complete_keynotes: dict[str, Any] = {}
        skipped = {
            "abstract_fallback": 0,
            "not_complete_section_read": 0,
            "missing_keynote": 0,
        }
        for raw_paper_id in dict.fromkeys(str(paper_id) for paper_id in papers):
            identifier = canonical_paper_id(raw_paper_id)
            if not identifier:
                continue
            failure = fallback_by_identity.get(identifier, {})
            if str(failure.get("fallback_status") or "") == "abstract_used":
                skipped["abstract_fallback"] += 1
                continue
            try:
                cached = self.paper_keynote_cache.get(get_hash(raw_paper_id))
            except (AttributeError, OSError, ValueError):
                cached = None
            cached = dict(cached) if isinstance(cached, Mapping) else {}
            keynote = cached.get("keynote")
            if keynote in (None, "", [], {}):
                skipped["missing_keynote"] += 1
                continue
            if str(cached.get("fulltext_reading_source") or "") not in COMPLETE_SECTION_READING_SOURCES:
                skipped["not_complete_section_read"] += 1
                continue
            complete_keynotes.setdefault(identifier, keynote)

        result = promote(complete_keynotes)
        result = dict(result) if isinstance(result, Mapping) else {"result": result}
        result["input_complete_section_keynotes"] = len(complete_keynotes)
        result["input_skipped"] = skipped
        self.logger.info(
            "Prepared %s complete-section keynotes for citation-expanded-paper "
            "promotion; skipped abstract=%s, unproven-reading=%s, missing=%s.",
            len(complete_keynotes),
            skipped["abstract_fallback"],
            skipped["not_complete_section_read"],
            skipped["missing_keynote"],
        )
        return result

    def _paper_keynote_negative_failures(self) -> dict[str, dict[str, Any]]:
        cache = getattr(self, "_paper_keynote_negative_cache", None)
        if not isinstance(cache, dict):
            cache = {}
            self._paper_keynote_negative_cache = cache
        return cache

    def _section_packet_states(self) -> dict[str, dict[str, Any]]:
        states = getattr(self, "_section_keynote_states", None)
        if not isinstance(states, dict):
            states = {}
            self._section_keynote_states = states
        return states

    def _paper_keynote_failure_records(self) -> dict[str, dict[str, Any]]:
        records = getattr(self, "paper_keynote_failure_records", None)
        if not isinstance(records, dict):
            records = {}
            self.paper_keynote_failure_records = records
        return records

    def _json_object_response_format(self) -> str | None:
        """Request JSON mode only when the selected provider declares support."""
        supports_format = getattr(self.chat_agent, "supports_response_format", None)
        if not callable(supports_format):
            return None
        try:
            return "json_object" if supports_format("json_object") else None
        except Exception as exc:
            self.logger.warning(
                "Unable to determine JSON-object support for keynote reading: %s",
                exc,
            )
            return None

    def _record_paper_keynote_failure(
        self,
        pid: str,
        *,
        code: str,
        reason: str,
        permanent: bool = False,
        fallback_status: str = "not_attempted",
        **details: Any,
    ) -> dict[str, Any]:
        """Record a structured, in-run keynote failure without changing evidence roles."""
        paper_id = str(pid or "").strip()
        records = self._paper_keynote_failure_records()
        record = dict(records.get(paper_id) or {})
        record.update(
            {
                "schema_version": PAPER_KEYNOTE_FAILURE_SCHEMA_VERSION,
                "paper_id": paper_id,
                "status": "permanent_failure" if permanent else "fallback_used",
                "code": str(code or "unknown_keynote_failure"),
                "reason": str(reason or ""),
                "fallback_status": str(fallback_status or "not_attempted"),
            }
        )
        record.update(details)
        records[paper_id] = record
        if permanent:
            self._paper_keynote_negative_failures()[paper_id] = dict(record)

        basic_info = getattr(getattr(self, "config", None), "BasicInfo", None)
        if basic_info is not None:
            try:
                basic_info.paper_keynote_failures = dict(records)
            except Exception:
                pass
        return record

    @staticmethod
    def _validate_section_note_payload(payload: Any) -> dict[str, Any]:
        """Validate and normalize the fixed JSON contract for one section packet."""
        if not isinstance(payload, Mapping):
            raise ValueError("Section note must be a JSON object.")
        required_keys = {
            "source_sections",
            "claims",
            "methods",
            "results",
            "limitations",
            "unknowns",
        }
        missing_keys = sorted(required_keys - set(payload))
        if missing_keys:
            raise ValueError(
                "Section note is missing required fields: " + ", ".join(missing_keys)
            )

        def text_list(name: str) -> list[str]:
            values = payload.get(name)
            if not isinstance(values, list):
                raise ValueError(f"Section note '{name}' must be a JSON list.")
            normalized = []
            for value in values:
                if not isinstance(value, str):
                    raise ValueError(f"Section note '{name}' values must be strings.")
                text = value.strip()
                if text:
                    normalized.append(text)
            return normalized

        source_sections = text_list("source_sections")
        if not source_sections:
            raise ValueError("Section note must name at least one source section.")
        claims = payload.get("claims")
        if not isinstance(claims, list):
            raise ValueError("Section note 'claims' must be a JSON list.")
        normalized_claims = []
        for index, claim in enumerate(claims):
            if not isinstance(claim, Mapping):
                raise ValueError(f"Section note claim {index} must be a JSON object.")
            normalized_claim = {}
            for key in ("claim", "evidence", "source_section"):
                value = claim.get(key)
                if not isinstance(value, str) or not value.strip():
                    raise ValueError(
                        f"Section note claim {index} requires a non-empty '{key}' string."
                    )
                normalized_claim[key] = value.strip()
            normalized_claims.append(normalized_claim)

        return {
            "source_sections": source_sections,
            "claims": normalized_claims,
            "methods": text_list("methods"),
            "results": text_list("results"),
            "limitations": text_list("limitations"),
            "unknowns": text_list("unknowns"),
        }

    @staticmethod
    def _extract_section_note_json_object(response: str) -> dict[str, Any]:
        """Parse only a top-level JSON object for the fixed section schema.

        The generic extractor accepts a JSON list and, after a truncated object,
        may accidentally recover a nested ``source_sections`` or ``claims``
        list.  That made a visibly object-shaped response look like a list in
        validation logs.  A section note has an object-only schema, so never
        treat a nested list as a viable recovery candidate.
        """

        text = re.sub(r"```[\w]*", "", str(response or "")).replace("```", "").strip()
        if not text:
            raise ValueError("Empty section-note response.")
        decoder = json.JSONDecoder()
        for start, character in enumerate(text):
            if character != "{":
                continue
            candidate = text[start:]
            try:
                payload, _end = decoder.raw_decode(candidate)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                return payload
        raise ValueError("No complete JSON object found for section note.")

    def _consume_section_packet_response(
        self,
        task: Mapping[str, Any],
        response: Any,
        section_packet_states: Mapping[str, dict[str, Any]],
    ) -> bool:
        """Store one valid note or immediately terminally fail the paper packet."""
        paper_id = str(task["paper_id"])
        packet_index = int(task["packet_index"])
        state = section_packet_states[paper_id]
        try:
            if not isinstance(response, str) or len(response.strip()) < 10:
                raise ValueError("Empty or too-short section-note response.")
            parsed = self._extract_section_note_json_object(response)
            state["section_responses"][packet_index] = self._validate_section_note_payload(
                parsed
            )
            return True
        except Exception as exc:
            message = str(exc)
            is_non_json = (
                "No JSON found" in message
                or "No complete JSON object found" in message
            )
            attempt_bucket = (
                state["non_json_attempts"]
                if is_non_json
                else state["invalid_response_attempts"]
            )
            attempts = int(attempt_bucket.get(packet_index, 0)) + 1
            attempt_bucket[packet_index] = attempts
            packet = state["packing"].packets[packet_index]
            failure_code = (
                "section_response_not_json"
                if is_non_json
                else "section_response_invalid_schema"
            )
            reason = (
                f"section packet {packet_index + 1}/{len(state['packing'].packets)} "
                f"({', '.join(packet.headings)}) failed validation: {message}"
            )
            state["terminal_failure"] = {
                "code": failure_code,
                "reason": reason,
                "packet_index": packet_index,
                "packet_headings": list(packet.headings),
                "attempts": attempts,
            }
            self._record_paper_keynote_failure(
                paper_id,
                code=failure_code,
                reason=reason,
                fallback_status="pending",
                section_packet_index=packet_index,
                section_headings=list(packet.headings),
                invalid_response_attempts=attempts,
            )
            self.logger.warning(
                "Stopping unreadable section packet %s for paper %s after its first "
                "invalid response; no full-text retry will be sent. Using the "
                "configured paper fallback instead. Reason: %s. First 500 chars: %s",
                packet_index + 1,
                paper_id,
                message,
                response[:500] if isinstance(response, str) else "",
            )
            return False

    def _try_abstract_keynote_fallback(
        self,
        *,
        pid: str,
        hash_id: str,
        reason: str,
        failure_code: str,
    ) -> bool:
        """Try one abstract fallback and negative-cache a confirmed unusable paper."""
        try:
            errors = self.work_collector.add_papers_abstracts_in_cache([pid])
        except Exception as exc:
            self._record_paper_keynote_failure(
                pid,
                code=failure_code,
                reason=f"{reason}; abstract fallback request failed: {exc}",
                permanent=True,
                fallback_status="abstract_request_failed",
            )
            self.logger.warning("Abstract fallback failed for paper %s: %s", pid, exc)
            return False
        if hash_id in self.paper_abstract_cache and not errors:
            self._record_paper_keynote_failure(
                pid,
                code=failure_code,
                reason=reason,
                fallback_status="abstract_used",
            )
            self.logger.info("Using abstract fallback for paper %s because %s.", pid, reason)
            return True
        self._record_paper_keynote_failure(
            pid,
            code=failure_code,
            reason=reason,
            permanent=True,
            fallback_status="abstract_unavailable",
        )
        self.logger.warning("Abstract fallback produced no usable keynote for paper %s.", pid)
        return False

    def _fallback_after_terminal_section_failure(
        self,
        pid: str,
        state: Mapping[str, Any],
    ) -> bool:
        failure = dict(state.get("terminal_failure") or {})
        return self._try_abstract_keynote_fallback(
            pid=pid,
            hash_id=str(state["hash_id"]),
            reason=str(failure.get("reason") or "section packet validation failed"),
            failure_code=str(failure.get("code") or "section_response_invalid"),
        )

    def _build_safe_fulltext_tasks(
        self,
        *,
        pid,
        hash_id,
        paper_markdown_text,
        body_budget: int,
        max_input_tokens: int,
    ):
        """Create only complete-section prompts that fit their final envelopes.

        ``fulltext_section_prompt_reserve_tokens`` keeps ordinary requests well
        below the context limit, but the final prompt also contains headings and
        instructions.  This method measures that exact final prompt.  If a
        multi-section packet overflows, it lowers the raw-body budget and packs
        again, thereby moving only whole ``##`` sections to the next packet.
        It never fixes an overflow by slicing raw Markdown.
        """
        dynamic_body_budget = int(body_budget)
        if max_input_tokens <= 0:
            raise ValueError("The full-text request has no input-token budget.")

        for _ in range(128):
            packing = pack_mineru_markdown_by_complete_sections(
                paper_markdown_text,
                max_body_tokens=dynamic_body_budget,
                count_tokens=self.chat_agent.estimate_tokens,
                excluded_heading_patterns=DEFAULT_EXCLUDED_SECTION_PATTERNS,
            )
            if packing.status in {"no_sections", "unsplittable_section"}:
                return packing, [], packing.unsplittable_section

            tasks = []
            if packing.status == "single_packet":
                packet = packing.packets[0]
                tasks.append(
                    {
                        "kind": "paper",
                        "paper_id": pid,
                        "hash_id": hash_id,
                        "packet_index": packet.index,
                        "prompt": PAPER_DEEP_READING.format(
                            paper_markdown_text=packet.markdown
                        ),
                    }
                )
            else:
                for packet in packing.packets:
                    included, omitted = render_packet_outline(packing, packet)
                    tasks.append(
                        {
                            "kind": "section",
                            "paper_id": pid,
                            "hash_id": hash_id,
                            "packet_index": packet.index,
                            "prompt": PAPER_SECTION_READING.format(
                                paper_title=packing.paper_title or pid,
                                packet_index=packet.index + 1,
                                packet_count=len(packing.packets),
                                included_headings=included,
                                omitted_headings=omitted,
                                packet_markdown=packet.markdown,
                            ),
                        }
                    )

            overflowing = []
            for task in tasks:
                prompt_token_count = int(self.chat_agent.estimate_tokens(task["prompt"]))
                if prompt_token_count > max_input_tokens:
                    overflowing.append((task, prompt_token_count))
            if not overflowing:
                return packing, tasks, None

            task, prompt_token_count = overflowing[0]
            packet = packing.packets[task["packet_index"]]
            if len(packet.section_indices) <= 1:
                section = next(
                    (
                        item
                        for item in packing.sections
                        if item.index == packet.section_indices[0]
                    ),
                    None,
                )
                self.logger.warning(
                    "Complete section for paper %s cannot fit its final prompt: "
                    "%s > %s input tokens.",
                    pid,
                    prompt_token_count,
                    max_input_tokens,
                )
                return packing, [], section

            overflow_tokens = prompt_token_count - max_input_tokens
            next_body_budget = min(
                dynamic_body_budget - 1,
                packet.body_token_count - max(1, overflow_tokens),
            )
            if next_body_budget <= 0 or next_body_budget >= dynamic_body_budget:
                self.logger.warning(
                    "Unable to repack complete sections for paper %s within the "
                    "final prompt budget.",
                    pid,
                )
                return packing, [], None
            dynamic_body_budget = next_body_budget

        self.logger.warning(
            "Stopped complete-section repacking for paper %s after 128 attempts.",
            pid,
        )
        return packing, [], None

    def _synthesize_complete_section_notes(
        self,
        *,
        paper_title: str,
        section_notes: list[Any],
        temperature: float,
        max_output_tokens: int,
        workers: int,
        max_in_flight_tokens: int | None = None,
    ):
        """Synthesize notes hierarchically, enforcing the final prompt limit.

        The raw paper text was already read as whole sections.  At this stage
        the values are structured LLM notes, so intermediate summaries can be
        recursively merged without ever cutting a source chapter.  Each level
        is exactly token-counted before it is sent.
        """
        max_input_tokens = (
            int(self.config.APIInfo.llm_max_context_length) - int(max_output_tokens)
        )
        if max_in_flight_tokens is None:
            work_config = getattr(
                getattr(self.config, "ModuleInfo", None), "WorkAnalyzer", None
            )
            max_in_flight_tokens = int(
                getattr(
                    work_config,
                    "fulltext_section_max_in_flight_tokens",
                    800_000,
                )
                or 800_000
            )
        if max_input_tokens <= 0:
            raise ValueError("The keynote synthesis request has no input-token budget.")

        current_notes = list(section_notes)
        if not current_notes:
            raise ValueError("No complete-section notes are available to synthesize.")
        json_response_format = self._json_object_response_format()

        for level in range(1, 9):
            final_prompt = self._format_keynote_synthesis_prompt(
                paper_title, current_notes
            )
            if int(self.chat_agent.estimate_tokens(final_prompt)) <= max_input_tokens:
                responses = self.chat_agent.batch_remote_chat(
                    [final_prompt],
                    temperature=temperature,
                    desc="Synthesizing whole-paper keynote",
                    workers=workers,
                    strict_input_budget=True,
                    max_output_tokens=max_output_tokens,
                    response_format=json_response_format,
                    max_in_flight_tokens=max_in_flight_tokens,
                )
                if len(responses) != 1 or not responses[0] or len(responses[0].strip()) < 10:
                    raise ValueError("empty final whole-paper synthesis response")
                return extract_json(responses[0])

            note_groups = self._partition_notes_for_compaction(
                paper_title=paper_title,
                notes=current_notes,
                max_input_tokens=max_input_tokens,
            )
            prompts = [
                self._format_keynote_compaction_prompt(
                    paper_title=paper_title,
                    notes=note_group,
                )
                for note_group in note_groups
            ]
            responses = self.chat_agent.batch_remote_chat(
                prompts,
                temperature=temperature,
                desc=f"Compacting complete-section notes (level {level})",
                workers=workers,
                strict_input_budget=True,
                max_output_tokens=max_output_tokens,
                response_format=json_response_format,
                max_in_flight_tokens=max_in_flight_tokens,
            )
            if len(responses) != len(prompts):
                raise ValueError("The synthesis response count did not match its requests.")

            summarized_notes = []
            for response in responses:
                if not response or len(response.strip()) < 10:
                    raise ValueError("empty synthesis response")
                summarized_notes.append(extract_json(response))

            current_notes = summarized_notes

        raise ValueError(
            "Complete-section notes could not be compacted into one budgeted keynote "
            "within eight hierarchy levels."
        )

    def _partition_notes_for_compaction(
        self,
        *,
        paper_title: str,
        notes: list[Any],
        max_input_tokens: int,
    ) -> list[list[Any]]:
        """Greedily group notes only when an exact compaction prompt fits."""
        groups: list[list[Any]] = []
        current_group: list[Any] = []
        for note in notes:
            candidate = [*current_group, note]
            candidate_prompt = self._format_keynote_compaction_prompt(
                paper_title=paper_title,
                notes=candidate,
            )
            if int(self.chat_agent.estimate_tokens(candidate_prompt)) <= max_input_tokens:
                current_group = candidate
                continue
            if not current_group:
                raise ValueError(
                    "One complete-section note exceeds the final keynote prompt budget."
                )
            groups.append(current_group)
            current_group = [note]
            single_note_prompt = self._format_keynote_compaction_prompt(
                paper_title=paper_title,
                notes=current_group,
            )
            if int(self.chat_agent.estimate_tokens(single_note_prompt)) > max_input_tokens:
                raise ValueError(
                    "One complete-section note exceeds the final keynote prompt budget."
                )
        if current_group:
            groups.append(current_group)
        return groups

    @staticmethod
    def _format_keynote_synthesis_prompt(paper_title: str, notes: list[Any]) -> str:
        return PAPER_KEYNOTE_SYNTHESIS.format(
            paper_title=paper_title,
            section_notes_json=json.dumps(notes, ensure_ascii=False),
        )

    @staticmethod
    def _format_keynote_compaction_prompt(
        *,
        paper_title: str,
        notes: list[Any],
    ) -> str:
        return PAPER_KEYNOTE_COMPACTION.format(
            paper_title=paper_title,
            section_notes_json=json.dumps(notes, ensure_ascii=False),
        )

    def _fallback_from_unreadable_fulltext(self, *, pid, hash_id, packing_status, section):
        """Use the configured abstract fallback without ever sending a partial chapter."""
        policy = str(
            getattr(
                self.config.ModuleInfo.WorkAnalyzer,
                "oversized_unsplittable_section_policy",
                "abstract",
            )
            or "abstract"
        ).lower()
        if packing_status == "unsplittable_section" and section is not None:
            reason = (
                f"complete section '{section.heading}' is {section.token_count} tokens "
                "and cannot be split safely"
            )
        elif packing_status == "prompt_budget" and section is not None:
            reason = (
                f"complete section '{section.heading}' cannot fit the final LLM "
                "prompt envelope without splitting"
            )
        elif packing_status == "prompt_budget":
            reason = "complete-section packets cannot fit the final LLM prompt envelope"
        else:
            reason = "MinerU Markdown has no safe ## body-section boundaries"
        if policy != "abstract" or not self.config.ModuleInfo.WorkAnalyzer.abstract_when_full_text_fail:
            self.logger.error("Cannot read paper %s without partial text: %s", pid, reason)
            self._record_paper_keynote_failure(
                pid,
                code="fulltext_packet_unsafe",
                reason=reason,
                permanent=True,
                fallback_status="disabled",
            )
            return False
        return self._try_abstract_keynote_fallback(
            pid=pid,
            hash_id=hash_id,
            reason=reason,
            failure_code="fulltext_packet_unsafe",
        )

    def _cache_paper_keynote(
        self,
        pid,
        hash_id,
        keynote,
        *,
        fulltext_reading_source: str = "legacy_or_unknown",
    ):
        self.paper_keynote_cache[hash_id] = {
            "paper_id": pid,
            "keynote": keynote,
            # The promotion channel may use only notes whose source proves
            # that every original Markdown body section was read intact.
            # Old cache entries have no such provenance and remain usable for
            # ordinary survey RAG, but cannot silently become SH evidence.
            "fulltext_reading_source": str(fulltext_reading_source or ""),
        }
        if self.config.BasicInfo.debug:
            self.logger.info(f"paper ID {pid} keynote: {keynote}")

    def generate_mla(self, paper_id: str):
        self.reference_graph = self._load_openalex_reference_graph()
        if (
            self.reference_graph is not None
            and paper_id in self.reference_graph
            and "authors" in self.reference_graph.nodes[paper_id]
            and "year" in self.reference_graph.nodes[paper_id]
            and "venue" in self.reference_graph.nodes[paper_id]
            and "title" in self.reference_graph.nodes[paper_id]
        ):
            authors = self.reference_graph.nodes[paper_id].get("authors", [])
            title = self.reference_graph.nodes[paper_id].get("title", "")
            venue = self.reference_graph.nodes[paper_id].get("venue", "")
            year = self.reference_graph.nodes[paper_id].get("year", "")
        else:
            paper = None
            if OpenAlexAPI.is_openalex_work_id(paper_id):
                try:
                    paper = self.openalex_api.get_paper_details(paper_id)
                except Exception as exc:
                    self.logger.warning(f"OpenAlex API failed for {paper_id}: {exc}")
                    paper = None
            elif "." in paper_id:  # arXiv IDs typically contain dots, e.g., "1706.03762"
                try:
                    paper = self.arxiv_api.get_paper_details(paper_id)
                except Exception as e:
                    self.logger.warning(f"arXiv API failed for {paper_id}: {e}. Trying Semantic Scholar.")
                    try:
                        query_id = "ARXIV:" + paper_id
                        paper = self.semantic_scholar_api.get_paper_details(
                            query_id, fields="title,year,venue,authors"
                        )
                    except Exception as e:
                        self.logger.error(f"Semantic Scholar also failed for arXiv paper {paper_id}: {e}")
                        paper = None
            else:
                # For non-arXiv papers, try Semantic Scholar directly
                try:
                    paper = self.semantic_scholar_api.get_paper_details(
                        paper_id, fields="title,year,venue,authors"
                    )
                except Exception as e:
                    self.logger.error(f"Semantic Scholar failed for paper {paper_id}: {e}")
                    paper = None

            if not paper:
                self.logger.warning(f"Warning: Unable to fetch details for paper ID {paper_id}")
                if getattr(self.config, 'AblationInfo', None) and getattr(self.config.AblationInfo, 'survey_generator_disabled', False):
                    self.logger.warning(f"Ablation mode: Returning paper_id as title for {paper_id}")
                    return f'Unknown Author. "{paper_id}" *Unknown*, Unknown'
                raise ValueError("Unable to fetch paper details in mla generation")
            
            authors = paper.get("authors", [])
            title = paper.get("title", "")
            venue = paper.get("venue", "")
            year = paper.get("year", "")

        if authors and isinstance(authors[0], dict):
            authors = [author.get("name", "") for author in authors]

        if len(authors) == 0:
            author_str = ""
        elif len(authors) == 1:
            author_str = authors[0]
        elif len(authors) == 2:
            author_str = f"{authors[0]} and {authors[1]}"
        else:
            author_str = ", ".join(authors[:-1]) + ", and " + authors[-1]

        citation = f'{author_str}. "{title}." *{venue}*, {year}'
        citation += "."
        return citation

    def get_paper_keynote(self, paper_id: str, ds_keynote_fallback: bool = False):
        """Get the keynote of a paper by its ID."""
        hash_id = get_hash(paper_id)

        if canonical_paper_id(paper_id) in FULLTEXT_READING_BYPASS_PAPER_IDS:
            # Keep the read-pipeline exception effective for all downstream
            # consumers, including callers that request a keynote directly.
            self.logger.info(
                "Using abstract keynote for explicit deep-reading exception: %s",
                paper_id,
            )
            try:
                _, abstract = self.work_collector.get_paper_title_abstract(paper_id)
            except Exception as exc:
                raise ValueError(
                    f"Failed to get abstract for paper ID {paper_id}: {exc}"
                ) from exc
            return abstract

        if self.use_graph_keynotes and not ds_keynote_fallback:
            results, errors = self.paper_graph_retriever.get_paper_keynote([paper_id])
            if errors or None in results:
                if self.use_ds_keynotes_when_graph_fail:
                    return self.get_paper_keynote(paper_id, True)
                else:
                    raise ValueError(f"Failed to get keynote for paper ID {paper_id} in paper graph")
            return results

        if self.config.ModuleInfo.WorkAnalyzer.abstract_only_mode:
            try:
                title, abstract =  self.work_collector.get_paper_title_abstract(paper_id)
            except Exception as e:
                raise ValueError(f"Failed to get abstract for paper ID {paper_id}: {e}")
            return abstract

        elif not self.config.ModuleInfo.WorkAnalyzer.abstract_only_mode or ds_keynote_fallback:
            err = []
            if hash_id not in self.paper_keynote_cache or not self.config.ModuleInfo.WorkAnalyzer.cache_enabled:
                err = self.read_papers_and_write_keynotes([paper_id], ds_keynote_fallback)

            if hash_id not in self.paper_keynote_cache or len(err) > 0:
                if self.config.ModuleInfo.WorkAnalyzer.abstract_when_full_text_fail:
                    self.logger.info(f"Using abstract for paper ID: {paper_id} as keynote due to full text failure.")
                    try:
                        title, abstract =  self.work_collector.get_paper_title_abstract(paper_id)
                    except Exception as e:
                        raise ValueError(f"Failed to get abstract for paper ID {paper_id}: {e}")
                    return abstract

            keynote_data = self.paper_keynote_cache[hash_id]["keynote"]
            return keynote_data

    def cluster_papers(self, papers: List[str]) -> List[Dict]:
        # Every survey-producing launcher reaches clustering after deep
        # reading.  Keep the citation-expanded promotion gate here rather
        # than in one launcher so batch and adapter entry points cannot omit
        # it.  The gate is a safe no-op for runs without SH provenance or
        # complete-section keynotes.
        try:
            promotion_result = self.promote_complete_section_read_graph_candidates(
                papers
            )
            if promotion_result.get("promoted_pairs"):
                self.logger.info(
                    "Promoted %s complete-section citation-expanded paper/SH pair(s) "
                    "before clustering.",
                    promotion_result["promoted_pairs"],
                )
        except Exception as exc:
            # Promotion is an additive writing path. A temporary assessment
            # failure must not erase independently admitted seed evidence or
            # prevent clustering; the unpromoted graph candidates remain
            # forbidden by the evidence plan.
            self.logger.warning(
                "Citation-expanded-paper promotion failed; proceeding without "
                "new expanded-paper evidence: %s",
                exc,
            )
        cached = self._load_cached_clusters(papers)
        if cached is not None:
            self.logger.info("Using cached clustering result.")
            return self._project_clusters_with_sh_coverage(cached)

        if self.config.ModuleInfo.WorkAnalyzer.clustering_in_steps:
            clusters = self.cluster_papers_in_steps(papers)
        else:
            clusters = self.cluster_papers_1_step(papers)

        clusters = self._project_clusters_with_sh_coverage(clusters)
        self._store_cached_clusters(papers, clusters)
        return clusters

    def _sh_cluster_projection_inputs(self) -> tuple[dict[str, Any], dict[str, Any], str] | None:
        """Load current-project SH artifacts; reject stale cross-project joins."""

        provenance = getattr(self.work_collector, "sh_graph_provenance_artifact", {})
        retrieval = getattr(self.work_collector, "subhypothesis_retrieval_artifact", {})
        basic_info = getattr(self.config, "BasicInfo", None)
        if (not isinstance(provenance, Mapping) or not provenance) and basic_info is not None:
            provenance = getattr(basic_info, "sh_graph_provenance", {})
        if (not isinstance(retrieval, Mapping) or not retrieval) and basic_info is not None:
            retrieval = getattr(basic_info, "subhypothesis_retrieval", {})
        if not provenance and not retrieval:
            return None
        if not isinstance(provenance, Mapping) or not isinstance(retrieval, Mapping):
            raise ValueError("SH cluster projection requires both provenance and retrieval artifacts.")
        if provenance.get("schema_version") != SH_GRAPH_PROVENANCE_SCHEMA_VERSION:
            raise ValueError("SH cluster projection received an unsupported provenance artifact.")
        final_ledger = retrieval.get("evidence_coverage_ledger_final")
        plan_context = (
            retrieval.get("plan", {}).get("project_context", {})
            if isinstance(retrieval.get("plan"), Mapping)
            else {}
        )
        fingerprint = str(provenance.get("project_context_fingerprint") or "")
        if not fingerprint or plan_context.get("project_context_fingerprint") != fingerprint:
            raise ValueError("SH provenance and retrieval artifacts belong to different project contexts.")
        if not isinstance(final_ledger, Mapping):
            raise ValueError("SH cluster projection requires the final evidence coverage ledger.")
        if final_ledger.get("schema_version") != EVIDENCE_COVERAGE_LEDGER_SCHEMA_VERSION:
            raise ValueError("SH cluster projection requires an evidence_coverage_ledger_v1 ledger.")
        if not isinstance(final_ledger.get("subhypotheses"), Sequence) or isinstance(
            final_ledger.get("subhypotheses"), (str, bytes)
        ):
            raise ValueError("SH coverage ledger must provide a subhypotheses sequence.")
        return dict(provenance), dict(final_ledger), fingerprint

    def _project_clusters_with_sh_coverage(self, clusters: List[Dict]) -> List[Dict]:
        """Add SH evidence/background/gap views without changing global clusters."""

        inputs = self._sh_cluster_projection_inputs()
        if inputs is None:
            return clusters
        provenance, final_ledger, fingerprint = inputs
        projected, artifact = build_cluster_sh_coverage_projection(
            clusters,
            provenance_artifact=provenance,
            coverage_ledger=final_ledger,
            graph=getattr(self.work_collector, "reference_graph", None),
            project_context_fingerprint=fingerprint,
        )
        self._store_sh_cluster_coverage_artifact(artifact)
        primary_links = sum(
            len(item.get("primary_subhypothesis_ids") or [])
            for item in artifact.get("clusters", [])
            if isinstance(item, Mapping)
        )
        self.logger.info(
            "Projected SH cluster coverage: clusters=%s direct_SH_links=%s unrepresented_SH=%s.",
            len(projected),
            primary_links,
            "|".join(artifact.get("unrepresented_subhypothesis_ids") or []) or "none",
        )
        return projected

    def _store_sh_cluster_coverage_artifact(self, artifact: Mapping[str, Any]) -> None:
        if artifact.get("schema_version") != SH_CLUSTER_COVERAGE_SCHEMA_VERSION:
            raise ValueError("Refusing to persist an unsupported SH cluster coverage artifact.")
        self.sh_cluster_coverage_artifact = dict(artifact)
        try:
            self.work_collector.sh_cluster_coverage_artifact = self.sh_cluster_coverage_artifact
        except Exception:
            pass
        basic_info = getattr(self.config, "BasicInfo", None)
        if basic_info is None:
            return
        try:
            basic_info.sh_cluster_coverage = self.sh_cluster_coverage_artifact
        except Exception:
            pass
        base_dir = str(getattr(basic_info, "base_dir", "") or "").strip()
        if not base_dir:
            return
        artifact_path = Path(base_dir) / "sh_cluster_coverage.json"
        artifact_path.parent.mkdir(parents=True, exist_ok=True)
        artifact_path.write_text(
            json.dumps(self.sh_cluster_coverage_artifact, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        try:
            basic_info.sh_cluster_coverage_artifact_path = str(artifact_path)
        except Exception:
            pass

    def cluster_papers_1_step(self, papers: List[str]) -> List[Dict]:
        clusters = []
        num_batches = math.ceil(
            len(papers) / self.config.ModuleInfo.WorkAnalyzer.clustering_batch_size
        )

        i = 0
        if self.config.BasicInfo.debug:
            self.logger.info(f'complete paper list for clustering: {papers}')
        while i < num_batches:
            valid = False
            for retry_time in range(
                self.config.ModuleInfo.WorkAnalyzer.paper_clustering_max_retry
            ):
                try:
                    self.logger.info(f"Clustering batch {i+1}/{num_batches}...")
                    batch = papers[
                        i
                        * self.config.ModuleInfo.WorkAnalyzer.clustering_batch_size : (
                            i + 1
                        )
                        * self.config.ModuleInfo.WorkAnalyzer.clustering_batch_size
                    ]
                    paper_keynotes = ""
                    for pid in batch:
                        keynote_json = self.get_paper_keynote(pid)
                        paper_keynotes += (
                            f"Paper ID: {pid}\nKeynote: {keynote_json}\n\n"
                        )

                    # self.logger.info(f"Clustering {len(batch)} papers...")
                    # self.logger.info(f'Clustering prompt: {PAPER_CLUSTERING.format(existing_clusters_json=clusters,new_batch_json=paper_keynotes,)}')
                    new_clusters = extract_json(
                        self.chat_agent.remote_chat(
                            PAPER_CLUSTERING.format(
                                existing_clusters_json=clusters,
                                new_batch_json=paper_keynotes,
                            ),
                            temperature=self.config.ModuleInfo.WorkAnalyzer.clustering_temperature,
                        )
                    )
                    self.validate_clusters(new_clusters, papers) #YZY MODIFY: from clusters
                    valid = True
                    break
                except Exception as e:
                    self.logger.warning(f"Error during clustering batch {i+1}: {e}. Retrying for {retry_time + 1}...")
            if not valid:
                raise ValueError("Clustering failed after maximum retries.")
            clusters = new_clusters
            if self.config.BasicInfo.debug:
                self.logger.info(f"CLUSTER after batch {i+1}: {new_clusters}")
            i += 1
        if self.config.BasicInfo.debug:
            self.logger.info(f"Final CLUSTER result: {clusters}")
        return clusters

    def cluster_papers_in_steps(self, papers: List[str]) -> List[Dict]:
        clusters = self._create_clusters(papers)
        clusters = self._assign_papers_to_clusters(papers, clusters)
        return clusters

    def _create_clusters(self, papers: List[str]) -> List[Dict]:
        clusters = []
        num_batches = math.ceil(
            len(papers) / self.config.ModuleInfo.WorkAnalyzer.clustering_batch_size_in_creation
        )

        # step 1: create clusters
        i = 0
        while i < num_batches:
            valid = False
            for retry_time in range(
                self.config.ModuleInfo.WorkAnalyzer.paper_clustering_creation_max_retry
            ):
                try:
                    self.logger.info(f"Clustering batch {i+1}/{num_batches}...")
                    batch = papers[
                        i
                        * self.config.ModuleInfo.WorkAnalyzer.clustering_batch_size_in_creation : (
                            i + 1
                        )
                        * self.config.ModuleInfo.WorkAnalyzer.clustering_batch_size_in_creation
                    ]
                    if self.config.BasicInfo.debug:
                        self.logger.info(f'complete paper list for clustering: {papers}')
                    paper_keynotes = ""
                    for pid in batch:
                        keynote_json = self.get_paper_keynote(pid)
                        paper_keynotes += (
                            f"Paper ID: {pid}\nKeynote: {keynote_json}\n\n"
                        )

                    new_clusters = extract_json(
                        self.chat_agent.remote_chat(
                            PAPER_CLUSTERING_CREATING.format(
                                existing_clusters_json=clusters,
                                new_batch_json=paper_keynotes,
                            ),
                            temperature=self.config.ModuleInfo.WorkAnalyzer.clustering_temperature,
                        )
                    )
                    valid = True
                    break
                except Exception as e:
                    self.logger.warning(f"Error during clustering batch creation {i+1}: {e}. Retrying for {retry_time + 1}...")
            if not valid:
                raise ValueError("Clustering failed after maximum retries.")
            clusters = new_clusters
            if self.config.BasicInfo.debug:
                self.logger.info(f"CLUSTER after batch {i+1}: {new_clusters}")
            i += 1
        if self.config.BasicInfo.debug:
            self.logger.info(f"Final CLUSTER result: {clusters}")
        return clusters

    def _validate_assignment(self, result, info_dict):
        # self.logger.info("outer validating....")
        error_conservatism_mode = info_dict.get("error_conservatism_mode", False)
        max_retry = info_dict.get("max_retry", 5)
        batches = info_dict.get("batches", [])
        papers = info_dict.get("papers", [])
        # Fixed: was "cluster" in info_dict but "clusters" in access - now using "cluster" which is what we pass
        clusters = info_dict.get("cluster", {})
        idx = info_dict.get("idx")
        retry_time = info_dict.get("retry_time", 0)


        omit_error = not error_conservatism_mode and retry_time >= max_retry - 1
        batch = batches[idx] if idx < len(batches) else []
        try:
            new_papers_dict = extract_json(result)
            if self._validate_new_papers_to_clusters(clusters, new_papers_dict, papers, batch, omit_error):
                return True, result
        except Exception as e:
            if omit_error:
                self.logger.warning(f"error in cluster assign: {e}, omit")
                # Fixed: return (val, result) format for retry
                return True, result
            else:
                self.logger.error(f"error in cluster assign: {e}")
                return False, result
        return True, result

    def _assign_papers_to_clusters(self, papers: List[str], clusters: List[dict]) -> List[Dict]:
        # step2: assign papers to clusters
        num_batches = math.ceil(
            len(papers) / self.config.ModuleInfo.WorkAnalyzer.clustering_batch_size_in_assignment
        )

        cluster_name_dict = {cluster["cluster_name"]: cluster for cluster in clusters}
        for cluster in cluster_name_dict.values():
            cluster["papers"] = []
        
        new_clusters = copy.deepcopy(cluster_name_dict)

        prompts = []
        batches = []
        # step 2: assign papers to clusters
        i = 0
        while i < num_batches:
            valid = False
            err_info = ""
            for retry_time in range(
                self.config.ModuleInfo.WorkAnalyzer.paper_clustering_assignment_max_retry
            ):
                try:
                    self.logger.info(f"Clustering batch {i+1}/{num_batches}...")
                    batch = papers[
                        i
                        * self.config.ModuleInfo.WorkAnalyzer.clustering_batch_size_in_assignment : (
                            i + 1
                        )
                        * self.config.ModuleInfo.WorkAnalyzer.clustering_batch_size_in_assignment
                    ]
                    if self.config.BasicInfo.debug:
                        self.logger.info(f'complete paper list for clustering: {papers}')
                    paper_keynotes = ""
                    for pid in batch:
                        keynote_json = self.get_paper_keynote(pid)
                        paper_keynotes += (
                            f"Paper ID: {pid}\nKeynote: {keynote_json}\n\n"
                        )

                    assign_prompt = PAPER_CLUSTERING_ASSIGNING.format(
                            clusters_json=cluster_name_dict,
                            batch_json=paper_keynotes,
                        ) + (ERROR_FEEDBACK_PROMPT.format(info = err_info) if err_info else "")


                    ### for fast mode, use batch chat out of he loop
                    if self.cluster_fast_mode:
                        self.logger.info(f"[CLUSTER FAST MODE DEBUG] use fast cluster")
                        valid = True
                        batches.append(batch)
                        prompts.append(assign_prompt)
                        break

                    new_papers_dict = extract_json(
                        self.chat_agent.remote_chat(
                            assign_prompt,
                            temperature=self.config.ModuleInfo.WorkAnalyzer.clustering_temperature,
                        )
                    )
                    if not self.config.BasicInfo.error_conservatism_mode and retry_time == self.config.ModuleInfo.WorkAnalyzer.paper_clustering_assignment_max_retry - 1:
                        self.logger.warning(f"max retry reached:{retry_time+1}/{self.config.ModuleInfo.WorkAnalyzer.paper_clustering_assignment_max_retry}, assigning papers directly to clusters and returning in PAPER CLUSTER PAPER ASSIGNING.")
                        new_clusters = self._validate_and_assign_new_papers_to_clusters(new_clusters, new_papers_dict, papers, batch, True)
                        
                    else:
                        new_clusters = self._validate_and_assign_new_papers_to_clusters(new_clusters, new_papers_dict, papers, batch, False)
                    valid = True
                    break
                except Exception as e:
                    self.logger.warning(f"Error during clustering batch assignment {i+1}: {e}. Retrying for {retry_time + 1}...")
                    err_info += f"Error during clustering batch {i+1}: {e}. \n"
            if not valid:
                raise ValueError("Clustering failed after maximum retries.")
            if self.config.BasicInfo.debug and not self.cluster_fast_mode:
                self.logger.info(f"CLUSTER after batch {i+1}: {new_clusters}")
            i += 1

        if self.cluster_fast_mode:
            info_dict = {
                "error_conservatism_mode": self.config.BasicInfo.error_conservatism_mode,
                "max_retry": self.config.ModuleInfo.WorkAnalyzer.paper_clustering_assignment_max_retry,
                "batches": batches,
                "papers": papers,
                "cluster": cluster_name_dict
            }

            results = self.chat_agent.batch_remote_chat_with_retry(prompts = prompts,
                                                                    validate_fn=self._validate_assignment,
                                                                    max_retry = self.config.ModuleInfo.WorkAnalyzer.paper_clustering_assignment_max_retry,
                                                                    desc = "assigning resultd in fast mode",
                                                                    temperature = self.config.ModuleInfo.WorkAnalyzer.clustering_temperature,
                                                                    info_dict = info_dict,
                                                                )
            
            for idx, result in enumerate(results):
                # self.logger.info(f"assigning result {idx}...")
                batch = batches[idx]
                new_papers_dict = extract_json(result)
                new_clusters = self._validate_and_assign_new_papers_to_clusters(new_clusters, new_papers_dict, papers, batch, True)

        if self.config.BasicInfo.debug:
            self.logger.info(f"Final CLUSTER result: {new_clusters}")

        new_clusters = list(new_clusters.values())
        return new_clusters

    def _validate_and_assign_new_papers_to_clusters(self, clusters: Dict[str, dict], new_papers: List[dict], valid_papers: List[str], necessary_papers: List[str], omit_err: bool = False) -> Dict[str, dict]:
        valid_papers = set(valid_papers)

        for paper in new_papers:
            if "clusters" not in paper or paper.get("clusters") is None:
                if omit_err:
                    self.logger.warning("Omitting this paper due to incomplete information in PAPER CLUSTER PAPER ASSIGNING: lack key clusters")
                    continue
                raise ValueError("Incomplete paper information in PAPER CLUSTER PAPER ASSIGNING: lack key clusters")

            assigned_clusters = paper.get("clusters")
            for assigned_cluster in assigned_clusters:
                if assigned_cluster in clusters:

                    if paper["id"] is None or paper["title"] is None or paper["tldr"] is None:
                        self.logger.error(f"Paper information incomplete for paper in cluster assignment: {paper}")
                        if omit_err:
                            self.logger.warning("Omitting this paper due to incomplete information in PAPER CLUSTER PAPER ASSIGNING.")
                            continue
                        raise ValueError("Incomplete paper information in PAPER CLUSTER PAPER ASSIGNING.")

                    if paper["id"] not in valid_papers:
                        self.logger.error(f"Paper ID {paper['id']} not in original paper list during cluster assignment.")
                        if omit_err:
                            self.logger.warning("Omitting this paper due to incomplete information in PAPER CLUSTER PAPER ASSIGNING.")
                            continue
                        raise ValueError("Invalid paper ID in PAPER CLUSTER PAPER ASSIGNING.")

                    clusters[assigned_cluster]["papers"].append({
                        "id": paper["id"],
                        "title": paper["title"],
                        "tldr": paper["tldr"]
                    })
                else:
                    self.logger.error(f"Assigned cluster {assigned_cluster} not found in existing clusters.")
                    if omit_err:
                        self.logger.warning(f"Omitting this fake cluster name:{assigned_cluster} due to incomplete information in PAPER CLUSTER PAPER ASSIGNING.")
                        continue
                    raise ValueError("Invalid clustering assignment in PAPER CLUSTER PAPER ASSIGNING.")
                
        assigned_paper_ids = set(paper["id"] for paper in new_papers)
        unassigned = set(necessary_papers) - assigned_paper_ids

        if unassigned:
            self.logger.error(f"Papers in batch not assigned num: {len(unassigned)}")
            if not omit_err:
                raise ValueError("Missing papers in batch assignment.")
            else:
                self.logger.warning(f"Omitting this not assigned papers:{len(unassigned)} due to incomplete information in PAPER CLUSTER PAPER ASSIGNING.")
        return clusters

    def _validate_new_papers_to_clusters(self, clusters: Dict[str, dict], new_papers: List[dict], valid_papers: List[str], necessary_papers: List[str], omit_err: bool = False) -> Dict[str, dict]:
        valid_papers = set(valid_papers)
        # self.logger.info("inner validating....")
        returned_papers = []

        for paper in new_papers:

            if "clusters" not in paper or paper.get("clusters") is None:
                self.logger.error("ERROR: incomplete information in PAPER CLUSTER PAPER ASSIGNING: lack key clusters or clusters empty")
                # self.logger.info(f"[CLUSTER FAST MODE DEBUG ERROR RESPONSE]: {new_papers}")
                if omit_err:
                    self.logger.warning("Omitting this paper due to incomplete information in PAPER CLUSTER PAPER ASSIGNING: lack key clusters or clusters empty")
                    continue
                raise ValueError("Incomplete paper information in PAPER CLUSTER PAPER ASSIGNING: lack key clusters")

            assigned_clusters = paper.get("clusters")
            
            for assigned_cluster in assigned_clusters:
                if assigned_cluster in clusters:

                    if paper["id"] is None or paper["title"] is None or paper["tldr"] is None:
                        self.logger.error(f"Paper information incomplete for paper in cluster assignment: {paper}")
                        # self.logger.info(f"[CLUSTER FAST MODE DEBUG ERROR RESPONSE]: {new_papers}")
                        if omit_err:
                            self.logger.warning("Omitting this paper due to incomplete information in PAPER CLUSTER PAPER ASSIGNING.")
                            continue
                        raise ValueError("Incomplete paper information in PAPER CLUSTER PAPER ASSIGNING.")

                    if paper["id"] not in valid_papers:
                        self.logger.error(f"Paper ID {paper['id']} not in original paper list during cluster assignment.")
                        # self.logger.info(f"[CLUSTER FAST MODE DEBUG ERROR RESPONSE]: {new_papers}")
                        if omit_err:
                            self.logger.warning("Omitting this paper due to incomplete information in PAPER CLUSTER PAPER ASSIGNING.")
                            continue
                        raise ValueError("Invalid paper ID in PAPER CLUSTER PAPER ASSIGNING.")
                else:
                    self.logger.error(f"Assigned cluster {assigned_cluster} not found in existing clusters.")
                    # self.logger.info(f"[CLUSTER FAST MODE DEBUG ERROR RESPONSE]: {new_papers}")
                    if omit_err:
                        self.logger.warning(f"Omitting this fake cluster name:{assigned_cluster} due to incomplete information in PAPER CLUSTER PAPER ASSIGNING.")
                        continue
                    raise ValueError("Invalid clustering assignment in PAPER CLUSTER PAPER ASSIGNING.")

        assigned_paper_ids = set(paper["id"] for paper in new_papers)
        unassigned = set(necessary_papers) - assigned_paper_ids

        if unassigned:
            self.logger.error(f"Papers in batch not assigned num: {len(unassigned)}")
            # self.logger.info(f"[CLUSTER FAST MODE DEBUG ERROR RESPONSE]: {new_papers}")
            if not omit_err:
                raise ValueError("Missing papers in batch assignment.")
            else:
                self.logger.warning(f"Omitting this not assigned papers:{len(unassigned)} due to incomplete information in PAPER CLUSTER PAPER ASSIGNING.")
        self.logger.info("inner validate finish")
        return True
        

    def log_clusters(self, clusters: List[Dict]):
        paper_id_set = set()
        log_str = "Clustering Results:\n"
        for i, cluster in enumerate(clusters):
            log_str += f"Cluster {i+1}:\n"
            log_str += f"  Cluster Name: {cluster['cluster_name']}\n"
            log_str += f"  Summary: {cluster['summary']}\n"
            log_str += f"  Papers:\n"
            for paper in cluster["papers"]:
                log_str += f"    - ID: {paper['id']}\n"
                log_str += f"      Title: {paper['title']}\n"
                log_str += f"      TL;DR: {paper['tldr']}\n"
                paper_id_set.add(paper["id"])
            log_str += "\n"
            log_str += "-" * 40 + "\n\n"
        self.logger.info(log_str)
        self.logger.info(f"Total unique papers in clusters: {len(paper_id_set)}")
        if self.config.BasicInfo.debug:
            self.logger.info(f"all ref set: {paper_id_set}")

    def validate_clusters(self, clusters: List[Dict], papers: List[str]) -> List[Dict]:
        paper_id_set = set(papers)
        for cluster in clusters:
            for paper in cluster["papers"]:
                if paper["id"] not in paper_id_set:
                    self.logger.warning(
                        f"Paper ID {paper['id']} in cluster {cluster['cluster_name']} not in original paper list."
                    )
                    raise ValueError("Invalid clustering result.")

    def prepare_prompt_for_proposing_questions_for_cluster(self, cluster: List[str]):
        cluster_content = f"Paper keynotes:\n"
        for paper in cluster["papers"]:
            pid = paper["id"]
            keynote_json = self.get_paper_keynote(pid)
            cluster_content += f"Paper ID: {pid}\nKeynote: {keynote_json}\n\n"
        return PROPOSE_QUESTIONS_FOR_CLUSTER.format(cluster_content=cluster_content)

    def prepare_prompt_for_answering_questions_for_cluster(self, questions: List[Dict]):
        prompts = []
        for q in questions:
            question_text = q["question"]
            related_papers = q["related_papers"]
            related_papers_content = ""
            for pid in related_papers:
                keynote_json = self.get_paper_keynote(pid)
                related_papers_content += (
                    f"Paper ID: {pid}\nKeynote: {keynote_json}\n\n"
                )
            prompt = ANSWER_QUESTION_FOR_PAPERS.format(
                question=question_text, related_papers_content=related_papers_content
            )
            prompts.append(prompt)
        return prompts

    def intra_cluster_analysis(self, clusters: List[Dict], retry=1):
        try:
            # step 1: propose questions for each cluster
            prompts = []
            for cluster in clusters:
                prompt = self.prepare_prompt_for_proposing_questions_for_cluster(
                    cluster
                )
                prompts.append(prompt)

            # use fixed-length list to keep correspondence turn with clusters
            questions = [None] * len(clusters)
            step_1_clusters = clusters  # to avoid changing clusters during retry

            # turn mapping for retry
            indices = list(range(len(clusters)))

            # start question proposing with retry
            for _ in range(
                self.config.ModuleInfo.WorkAnalyzer.intra_clustering_probelm_proposing_max_retry
            ):
                valid = True
                try:
                    responses = self.chat_agent.batch_remote_chat(
                        prompts,
                        temperature=self.config.ModuleInfo.WorkAnalyzer.propose_question_temperature,
                        desc="Proposing questions for clusters",
                    )
                except Exception as e:
                    self.logger.error(f'Error: {e} , during proposing questions for clusters in getting response from LLM, retrying all...')
                    continue

                # self.logger.info(f"intra cluster analysis responses:\nTYPE:{type(responses)} | {responses}")

                err_prompts = []
                err_clusters = []
                err_indices = []
                err_infos = []

                # use current batch indices to map results back to original positions
                for i, response in enumerate(responses):
                    original_index = indices[i]

                    try:
                        cur_questions = extract_json(response)
                    except Exception as e:
                        self.logger.warning(f"Error extracting questions for cluster {original_index+1}: {e}. Retrying...")
                        err_prompts.append(prompts[i])    
                        err_clusters.append(step_1_clusters[i])
                        err_indices.append(original_index)
                        err_infos.append(f"Error extracting questions from your answer for cluster {original_index+1}: {e}. \n")
                        valid = False
                        continue
                        
                    omit_error = not self.config.BasicInfo.error_conservatism_mode and (_ + 1 == self.config.ModuleInfo.WorkAnalyzer.intra_clustering_probelm_proposing_max_retry)

                    response_valid, invalid_pid = self.validate_questions(cur_questions, step_1_clusters[i], omit_err=omit_error)
                    if response_valid:
                        questions[original_index] = cur_questions[:self.max_problems_per_cluster_proposed]
                    else:
                        valid = False
                        self.logger.warning(f"Invalid questions proposed for cluster {original_index+1}. Retrying...")

                        err_prompts.append(prompts[i])    
                        err_clusters.append(step_1_clusters[i])
                        err_indices.append(original_index)
                        err_infos.append(f"Question related papers ID {invalid_pid} not valid. Make sure only cite provided paper.\n ")

                if valid:   # no error, break
                    break

                # next retry only for error cases
                prompts = err_prompts
                step_1_clusters = err_clusters
                indices = err_indices

                for i in range(len(prompts)):
                    prompts[i] += ERROR_FEEDBACK_PROMPT.format(info = err_infos[i])

            # if None occurs in questions after retries, raise error
            if any(q is None for q in questions):
                raise ValueError("Invalid question related papers after maximum retries.")

            # step 2: answer questions for each cluster
            prompts = self.prepare_prompt_for_answering_questions_for_cluster(
                [q for cluster_questions in questions for q in cluster_questions]
            )
            answers = self.chat_agent.batch_remote_chat(
                prompts,
                temperature=self.config.ModuleInfo.WorkAnalyzer.propose_question_temperature,
                desc="Answering questions for clusters",
            )

            # step 3: organize the Q&A
            for cluster_questions in questions:
                for q in cluster_questions:
                    q["answer"] = self._truncate_by_words(answers.pop(0), self.max_words_num_in_intra_cluster_answer)

            return questions
        except Exception as e:
            if (
                retry
                > self.config.ModuleInfo.WorkAnalyzer.intra_cluster_analysis_max_retry
            ):
                raise e
            return self.intra_cluster_analysis(clusters, retry=retry + 1)

    def validate_questions(self, questions: List[Dict], cluster: Dict, omit_err: bool = False):
        valid_paper_ids = {paper["id"] for paper in cluster["papers"]}
        err_id = []
        for q in questions:
            for pid in q["related_papers"]:
                if pid not in valid_paper_ids:
                    self.logger.warning(
                        f"Paper ID {pid} in question '{q['question']}' not in cluster papers."
                    )
                    if not omit_err:
                        return False, pid
                    else:
                        self.logger.warning(f"Omitting this invalid paper ID:{pid} in question due to omit_err mode.")
                        err_id.append(pid)
            if omit_err and err_id:
                q["related_papers"] = [pid for pid in q["related_papers"] if pid not in err_id]

        return True, ""

    def log_intra_cluster_analysis(self, analysis_results: List[List[Dict]]):
        log_str = "Intra-Cluster Analysis Results:\n"
        for i, cluster_results in enumerate(analysis_results):
            log_str += f"Cluster {i+1}:\n"
            for qa in cluster_results:
                log_str += f"  Question: {qa['question']}\n"
                log_str += f"  Related Papers: {', '.join(qa['related_papers'])}\n"
                log_str += f"  Answer: {qa['answer']}\n"
                log_str += "\n"
            log_str += "-" * 40 + "\n\n"
        self.logger.info(log_str)

    def _truncate_by_words(self, text: str, max_words: int, suffix: str = "(too long, truncated)...") -> str:
        """Truncate text to max_words, adding suffix if truncated."""
        if not text:
            return text
        words = text.split()
        if len(words) <= max_words:
            return text
        truncated = " ".join(words[:max_words - len(suffix.split())])
        return truncated + " " + suffix

    def inter_cluster_analysis(self, intra_analysis_results: List[List[Dict]]):
        cluster_analysis_content = ""
        for i, cluster_results in enumerate(intra_analysis_results):
            cluster_analysis_content += f"Group {i+1} Analysis:\n"
            for j, qa in enumerate(cluster_results):
                cluster_analysis_content += f"Question {j+1}: {qa['question']}\n"
                cluster_analysis_content += f"Answer: {j+1}: {qa['answer']}\n\n"
            cluster_analysis_content += "-" * 3 + "\n\n"

        prompt = INTER_CLUSTER_ANALYSIS.format(
            cluster_analysis_content=cluster_analysis_content
        )
        response = self.chat_agent.remote_chat(
            prompt,
            temperature=self.config.ModuleInfo.WorkAnalyzer.intra_cluster_analysis_temperature,
        )
        
        # Apply word limit if configured
        max_words = self.max_words_num_in_inter_cluster_analysis
        response = self._truncate_by_words(response, max_words)
        
        return response

    def log_inter_cluster_analysis(self, analysis_results):
        log_str = "Inter-Cluster Analysis Results:\n"
        log_str += analysis_results + "\n"
        self.logger.info(log_str)

    # ---------------------------- Relationship analysis ----------------------------
    def build_relationship_graphs(self, clusters: List[Dict]):
        """
        For each cluster, construct a directed graph over its papers and enrich edges with
        relation type/analysis from the LLM.

        Returns a dict: {cluster_name: nx.DiGraph}, where each edge has attributes
        {'type': str, 'analysis': str, 'raw': str}.
        """
        ref_graph: nx.DiGraph = self.work_collector.reference_graph
        if ref_graph is None:
            raise ValueError("Reference graph is not initialized; cannot build relationship graphs.")

        cached = self._load_cached_relation_graph(clusters)
        if cached is not None:
            self.logger.info("Using cached relationship graphs.")
            self.relation_analysis_graph = cached
            return cached

        results = {}
        pending_tasks = []  # collect all edge prompts for batched processing
        for cluster in clusters:
            cluster_name = cluster.get("cluster_name", "unknown_cluster")
            g = nx.DiGraph()

            # Collect node IDs in this cluster
            paper_ids = [p.get("id") for p in cluster.get("papers", []) if p.get("id")]
            g.add_nodes_from(
                (
                    paper_id,
                    dict(ref_graph.nodes[paper_id]) if paper_id in ref_graph else {},
                )
                for paper_id in paper_ids
            )

            for src in paper_ids:
                for dst in paper_ids:
                    if src == dst:
                        continue
                    if not ref_graph.has_edge(src, dst):
                        continue
                    if self.config.BasicInfo.debug:
                        self.logger.info(f"Analyzing relationship for edge {src}->{dst} in cluster {cluster_name}.")
                    # try:
                    src_title = ref_graph.nodes.get(src, {}).get("title", "")
                    dst_title = ref_graph.nodes.get(dst, {}).get("title", "")
                    src_keynote = self.get_paper_keynote(src)
                    dst_keynote = self.get_paper_keynote(dst)

                    prompt = PAPER_RELATIONSHIP_ANALYSIS.format(
                        src_title=src_title,
                        dist_title=dst_title,
                        src_keynote=src_keynote,
                        dist_keynote=dst_keynote,
                    )
                    pending_tasks.append({
                        "cluster_name": cluster_name,
                        "graph": g,
                        "src": src,
                        "dst": dst,
                        "prompt": prompt,
                    })
                    # except Exception as e:
                    #     self.logger.warning(f"Relation analysis failed for edge {src}->{dst}: {e}")
                    #     continue

            results[cluster_name] = g

        # Batch call LLM with retry
        temperature = getattr(
            self.config.ModuleInfo.WorkAnalyzer,
            "paper_relationship_temperature",
            0.3,
        )
        max_retry = getattr(
            self.config.ModuleInfo.WorkAnalyzer,
            "paper_relationship_max_retry",
            3,
        )

        tasks = pending_tasks
        for attempt in range(1, max_retry + 1):
            if not tasks:
                break
            prompts = [t["prompt"] for t in tasks]
            try:
                responses = self.chat_agent.batch_remote_chat(
                    prompts,
                    temperature=temperature,
                    desc=f"Relationship analysis attempt {attempt}/{max_retry}",
                )
            except Exception as e:
                self.logger.warning(f"batch_remote_chat failed on attempt {attempt}: {e}")
                continue

            next_tasks = []
            for task, resp in zip(tasks, responses or []):
                if resp is None:
                    next_tasks.append(task)
                    continue

                relation_type = "unspecified"
                analysis = resp
                try:
                    parsed = extract_json(resp)
                    if isinstance(parsed, dict):
                        relation_type = parsed.get("type") or parsed.get("relation") or relation_type
                        analysis = parsed.get("analysis") or parsed.get("description") or analysis
                except Exception:
                    pass

                try:
                    task["graph"].add_edge(
                        task["src"], task["dst"], type=relation_type, analysis=analysis, raw=resp
                    )
                    if self.config.BasicInfo.debug:
                        self.logger.info(f"GRAPH_DEBUG: Added edge {task['src']}->{task['dst']} with type '{relation_type}' in cluster {task['cluster_name']}.")
                except Exception as e:
                    self.logger.warning(f"Failed to add edge {task['src']}->{task['dst']}: {e}")
                    next_tasks.append(task)

            tasks = next_tasks

        # Drop edges that still failed after max retries
        for t in tasks:
            self.logger.warning(
                f"Dropping edge {t['src']}->{t['dst']} in cluster {t['cluster_name']} after {max_retry} retries."
            )
        self.relation_analysis_graph = results
        self._store_cached_relation_graph(clusters, results)
        self.logger.info(f"=====GRAPH_DEBUG=====")
        self.logger.info(f"{results}")
        self.logger.info(f"=====GRAPH END=====")
        return results

    def _get_relation_analysis_graph(self, relationship_graphs: Dict[str, nx.DiGraph] = None):
        """
        Convert relationship graphs to triples for downstream prompts.

        Returns a dict: {cluster_name: [ (src, relation, dst, analysis) ]}
        """
        if relationship_graphs is None:
            if self.relation_analysis_graph is None:
                raise ValueError("Relationship graphs not provided and not built yet.")
            relationship_graphs = self.relation_analysis_graph
        triples = {}
        for cluster_name, g in relationship_graphs.items():
            cluster_triples = []
            for u, v, data in g.edges(data=True):
                cluster_triples.append(
                    (
                        u,
                        data.get("type", "unspecified"),
                        v,
                        data.get("analysis", ""),
                    )
                )
            triples[cluster_name] = cluster_triples
        return triples

    def format_analysis_graph(self, relationship_graphs: Dict[str, nx.DiGraph] = None) -> str:
        """
        Call get_relation_analysis and format as a readable string per cluster.

        Output example:
        Cluster: C1
        - A --uses--> B | Because ...
        - ...
        """
        triples = self._get_relation_analysis_graph(relationship_graphs)
        parts: list[str] = []
        for cluster_name, items in triples.items():
            parts.append(f"Cluster: {cluster_name}")
            if not items:
                parts.append("  (no relations)")
                continue
            for src, rel, dst, analysis in items:
                rel_clean = rel or "unspecified"
                analysis_clean = analysis or ""
                parts.append(f"- {src} --{rel_clean}--> {dst} | {analysis_clean}")
        return "\n".join(parts)

    # ---------------------------- Cluster table generation ----------------------------
    @staticmethod
    def _normalize_cluster_table_payload(parsed: Any) -> Dict[str, Any]:
        """Return the one relation-table schema consumed by downstream writers.

        The requested LLM schema is an object with ``comparison_dimensions``
        and ``table_data``. Some providers nevertheless return a bare list of
        rows. That common, information-preserving variant is normalized here;
        any other malformed structure is rejected so the batch retry mechanism
        can request a new response instead of letting a list reach
        ``format_analysis_table``.
        """
        if isinstance(parsed, Mapping):
            dimensions = parsed.get("comparison_dimensions")
            table_data = parsed.get("table_data")
            if dimensions is None and table_data is None and len(parsed) == 1:
                # Compatibility with providers that wrap the intended object
                # in one named field, while still requiring the inner schema.
                only_value = next(iter(parsed.values()))
                if isinstance(only_value, Mapping):
                    dimensions = only_value.get("comparison_dimensions")
                    table_data = only_value.get("table_data")
        elif isinstance(parsed, list):
            # A top-level list is recoverable only when every item is a table
            # row; dimensions can be derived from its explicit ``columns``
            # mapping or from direct row fields.
            dimensions = None
            table_data = parsed
        else:
            raise ValueError(
                "Cluster table JSON must be an object or a list of row objects; "
                f"received {type(parsed).__name__}."
            )

        if not isinstance(table_data, list) or not table_data:
            raise ValueError("Cluster table 'table_data' must be a non-empty JSON list.")
        if not all(isinstance(row, Mapping) for row in table_data):
            raise ValueError("Every cluster-table row must be a JSON object.")

        normalized_dimensions: list[str] = []
        if dimensions is not None:
            if not isinstance(dimensions, list):
                raise ValueError("Cluster table 'comparison_dimensions' must be a JSON list.")
            for dimension in dimensions:
                text = str(dimension or "").strip()
                if not text:
                    raise ValueError("Cluster table dimensions must be non-empty strings.")
                if text not in normalized_dimensions:
                    normalized_dimensions.append(text)

        direct_row_reserved_keys = {"paper_id", "paper_title", "title", "columns"}
        for row in table_data:
            columns = row.get("columns")
            if columns is not None and not isinstance(columns, Mapping):
                raise ValueError("Each cluster-table row's 'columns' field must be an object.")
            candidate_columns = columns if isinstance(columns, Mapping) else {
                key: value
                for key, value in row.items()
                if key not in direct_row_reserved_keys
            }
            for dimension in candidate_columns:
                text = str(dimension or "").strip()
                if text and text not in normalized_dimensions:
                    normalized_dimensions.append(text)

        if not normalized_dimensions:
            raise ValueError(
                "Cluster table must provide at least one comparison dimension or row column."
            )

        normalized_rows = []
        for row in table_data:
            raw_columns = row.get("columns")
            if isinstance(raw_columns, Mapping):
                column_source = raw_columns
            else:
                column_source = {
                    key: value
                    for key, value in row.items()
                    if key not in direct_row_reserved_keys
                }
            paper_id = str(row.get("paper_id") or "").strip()
            paper_title = str(
                row.get("paper_title") or row.get("title") or paper_id or "Untitled paper"
            ).strip()
            normalized_rows.append(
                {
                    "paper_id": paper_id,
                    "paper_title": paper_title,
                    "columns": {
                        dimension: (
                            "N/A"
                            if column_source.get(dimension) is None
                            else str(column_source.get(dimension)).strip() or "N/A"
                        )
                        for dimension in normalized_dimensions
                    },
                }
            )

        return {
            "comparison_dimensions": normalized_dimensions,
            "table_data": normalized_rows,
        }

    @classmethod
    def _validate_cluster_table(cls, result: str, info_dict: dict) -> tuple[bool, dict]:
        """
        Validation function for cluster table generation.
        Extracts and validates JSON from the LLM response.
        
        Returns:
            (True, parsed_json) if successful
        Raises:
            ValueError if parsing fails
        """
        try:
            parsed = extract_json(result)
            return True, cls._normalize_cluster_table_payload(parsed)
        except Exception as e:
            raise ValueError(f"Invalid cluster table response: {e}")

    def generate_cluster_tables(self, clusters: List[Dict]):
        """
        Build comparison tables for all clusters using CLUSTER_TABLE_GENERATION in batch.

        clusters: list of cluster dicts with keys 'cluster_name', 'papers' (list of dict with id/title),
        and optionally 'summary'.

        Returns a dict {cluster_name: table_json} parsed from the LLM responses.
        Raises if any cluster still fails after retries.
        """
        pending_tasks = []

        for cluster in clusters:
            cluster_name = cluster.get("cluster_name", "unknown_cluster")
            description = cluster.get("summary", "")

            paper_blocks = []
            for p in cluster.get("papers", []):
                pid = p.get("id") or ""
                title = p.get("title") or ""
                try:
                    keynote = self.get_paper_keynote(pid)
                except Exception as e:
                    self.logger.warning(f"Failed to get keynote for paper {pid}: {e}. Using empty keynote.")
                    keynote = ""
                paper_blocks.append(
                    f"Paper ID: {pid}\nPaper Title: {title}\nKeynote: {keynote}\n"
                )

            paper_content = "\n".join(paper_blocks)
            prompt = CLUSTER_TABLE_GENERATION.format(
                cluster_name=cluster_name,
                cluster_description=description,
                paper_content=paper_content,
            )

            pending_tasks.append({
                "cluster_name": cluster_name,
                "prompt": prompt,
            })

        max_retry = getattr(self.config.ModuleInfo.WorkAnalyzer, "cluster_table_max_retry", 3)
        temperature = getattr(self.config.ModuleInfo.WorkAnalyzer, "cluster_table_temperature", 0.3)
        # The table validator is deliberately strict about row objects. Ask
        # capable providers for an actual JSON object so the retry path is
        # reserved for schema/content failures rather than avoidable Markdown
        # table formatting drift.
        json_response_format = self._json_object_response_format()

        prompts = [t["prompt"] for t in pending_tasks]
        cluster_names = [t["cluster_name"] for t in pending_tasks]

        # Use batch_remote_chat_with_retry for cleaner retry logic
        parsed_results = self.chat_agent.batch_remote_chat_with_retry(
            prompts=prompts,
            validate_fn=self._validate_cluster_table,
            max_retry=max_retry,
            desc="Cluster table generation",
            temperature=temperature,
            future_timeout=300.0,
            response_format=json_response_format,
        )

        # Map results back to cluster names
        results = {
            cluster_name: parsed_result
            for cluster_name, parsed_result in zip(cluster_names, parsed_results)
        }

        self.relation_analysis_table = results
        return results

    def format_analysis_table(self, cluster_tables: Dict[str, Dict] = None):
        """Render all cluster tables into a markdown string."""
        if cluster_tables is None:
            if self.relation_analysis_table is None:
                raise ValueError("Cluster tables not provided and not generated yet.")
            cluster_tables = self.relation_analysis_table
        parts = []
        for cluster_name, table_json in cluster_tables.items():
            table_json = self._normalize_cluster_table_payload(table_json)
            headers = ["Title"] + table_json.get("comparison_dimensions", [])
            md_table = "| " + " | ".join(headers) + " |\n"
            md_table += "| " + " | ".join(["---"] * len(headers)) + " |\n"

            for row in table_json.get("table_data", []):
                cols = [row.get("paper_title", "")]
                for dim in table_json.get("comparison_dimensions", []):
                    cols.append(row.get("columns", {}).get(dim, "N/A"))
                md_table += "| " + " | ".join(cols) + " |\n"

            parts.append(f"Cluster: {cluster_name}\n{md_table}")

        return "\n".join(parts)

    # ---------------------------- Cache helpers ----------------------------
    def _cache_task_key(self) -> str:
        topic = getattr(self.config.BasicInfo, "topic", "")
        cache_token = getattr(self.config.BasicInfo, "cache_token", "")
        return get_hash(f"{topic}|{cache_token}|{self.cache_path}")

    def _sh_projection_cache_token(self) -> str:
        inputs = self._sh_cluster_projection_inputs()
        if inputs is None:
            return "no_sh_projection"
        provenance, ledger, fingerprint = inputs
        reports = []
        for report in ledger.get("subhypotheses", []):
            if not isinstance(report, Mapping):
                continue
            reports.append(
                {
                    "sub_hypothesis_id": report.get("sub_hypothesis_id", ""),
                    "required_slots": report.get("required_slots", []),
                    "covered_slots": report.get("covered_slots", []),
                    "background_only_slots": report.get("background_only_slots", []),
                    "missing_slots": report.get("missing_slots", []),
                    "conclusion_admissibility": report.get(
                        "conclusion_admissibility", {}
                    ),
                }
            )
        return get_hash(
            json.dumps(
                {
                    "schema_version": SH_CLUSTER_COVERAGE_SCHEMA_VERSION,
                    "project_id": provenance.get("project_id", ""),
                    "project_context_fingerprint": fingerprint,
                    "ledger_reports": reports,
                    "paper_annotations": {
                        str(paper_id): records
                        for paper_id, records in sorted(
                            (provenance.get("paper_annotations") or {}).items()
                        )
                    },
                    "graph_expansion_records": sorted(
                        provenance.get("graph_expansion_records") or [],
                        key=lambda record: json.dumps(
                            record,
                            ensure_ascii=False,
                            sort_keys=True,
                        ),
                    ),
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )

    def _cluster_cache_key(self, papers: List[str]) -> str:
        sorted_ids = sorted(papers)
        return get_hash(
            f"clusters_v3|{self._cache_task_key()}|{self._sh_projection_cache_token()}|"
            f"{'|'.join(sorted_ids)}"
        )

    def _relation_graph_cache_key(self, clusters: List[Dict]) -> str:
        cluster_repr = []
        for c in clusters:
            name = c.get("cluster_name", "")
            ids = sorted([p.get("id", "") for p in c.get("papers", [])])
            cluster_repr.append(f"{name}:{'|'.join(ids)}")
        return get_hash(
            f"relation_graph_v3|{self._cache_task_key()}|{self._sh_projection_cache_token()}|"
            f"{'||'.join(sorted(cluster_repr))}"
        )

    def _prune_cache(self, cache: dc.Cache, max_entries: int):
        if max_entries is None or max_entries <= 0:
            return
        try:
            # exclude internal keys starting with '__'
            data_keys = [k for k in cache.iterkeys() if not (isinstance(k, str) and k.startswith("__"))]
            if len(data_keys) <= max_entries:
                return
            keyed = []
            for k in data_keys:
                try:
                    meta = cache.get(k, {}) or {}
                    ts = meta.get("ts", 0)
                except Exception:
                    ts = 0
                keyed.append((ts, k))
            keyed.sort()
            for _, k in keyed[: max(0, len(data_keys) - max_entries)]:
                try:
                    del cache[k]
                except Exception:
                    self.logger.warning(f"Failed to evict cache entry {k}")
        except Exception as e:
            self.logger.warning(f"Cache pruning skipped due to error: {e}")

    def _load_cached_clusters(self, papers: List[str]):
        if not getattr(self.config.ModuleInfo.WorkAnalyzer, "cluster_cache_enabled", True):
            return None
        key = self._cluster_cache_key(papers)
        if key in self.cluster_cache:
            try:
                payload = self.cluster_cache[key]
                return payload.get("data")
            except Exception as e:
                self.logger.warning(f"Failed to load cached clusters: {e}")
        return None

    def _store_cached_clusters(self, papers: List[str], clusters: List[Dict]):
        if not getattr(self.config.ModuleInfo.WorkAnalyzer, "cluster_cache_enabled", True):
            return
        key = self._cluster_cache_key(papers)
        self.cluster_cache[key] = {"data": clusters, "ts": time.time()}
        max_entries = getattr(self.config.ModuleInfo.WorkAnalyzer, "cluster_cache_max_entries", 5)
        self._prune_cache(self.cluster_cache, max_entries)

    def _load_cached_relation_graph(self, clusters: List[Dict]):
        if not getattr(self.config.ModuleInfo.WorkAnalyzer, "relation_graph_cache_enabled", True):
            return None
        key = self._relation_graph_cache_key(clusters)
        if key in self.relation_graph_cache:
            try:
                payload = self.relation_graph_cache[key]
                return payload.get("data")
            except Exception as e:
                self.logger.warning(f"Failed to load cached relationship graph: {e}")
        return None

    def _store_cached_relation_graph(self, clusters: List[Dict], graphs: Dict[str, nx.DiGraph]):
        if not getattr(self.config.ModuleInfo.WorkAnalyzer, "relation_graph_cache_enabled", True):
            return
        key = self._relation_graph_cache_key(clusters)
        self.relation_graph_cache[key] = {"data": graphs, "ts": time.time()}
        max_entries = getattr(self.config.ModuleInfo.WorkAnalyzer, "relation_graph_cache_max_entries", 5)
        self._prune_cache(self.relation_graph_cache, max_entries)


if __name__ == "__main__":
    root_ids = [
        # "arXiv:1706.03762",  # Transformer
        "fa72afa9b2cbc8f0d7b05d52548906610ffbb9c5"
    ]
