"""
DataManager: 负责数据读写、缓存管理和API调用
从WorkCollector中分离出来，供其他模块（如PaperGraphRetriever）复用
"""
from typing import Any, Dict, List, Mapping, Optional
import os
import sys
import json
from urllib.parse import urlsplit, urlunsplit
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from utils.api_call import ArxivAPI, OpenAlexAPI, SemanticScholarAPI, UnpaywallAPI
from utils.rich_logger import get_logger
from utils.mineru_utils import parse_doc
from utils.utils import get_hash, is_valid_pdf
from modules.fulltext_resolution import (
    resolve_declared_pdf_links,
    resolve_fulltext_candidates,
)
from modules.fulltext_download_cache import FulltextDownloadCoordinator
from modules.fulltext_http import FulltextHttpClient
import requests
from contextlib import closing
import diskcache as dc
import torch
import gc
import time
from sentence_transformers import SentenceTransformer, util
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading
from utils.gpu_utils import load_sentence_transformer_auto


class DataManager:
    """数据管理类：负责paper的下载、解析、缓存和API查询"""
    
    def __init__(self, config):
        self.config = config
        self.cache_path = self.config.BasicInfo.cache_path
        self.logger = get_logger("DataManager")
        
        # 初始化APIs
        self.openalex_api = OpenAlexAPI(config)
        self.semantic_scholar_api = SemanticScholarAPI(config)
        self.arxiv_api = ArxivAPI(config)
        self.unpaywall_api = UnpaywallAPI(config)
        self.fulltext_download_coordinator = FulltextDownloadCoordinator(
            self.cache_path,
            self.config.ModuleInfo.WorkCollector,
            logger=self.logger,
        )
        self.fulltext_http_client = FulltextHttpClient(
            self.config.ModuleInfo.WorkCollector,
            contact_email=getattr(self.unpaywall_api, "email", ""),
            logger=self.logger,
        )
        self._fulltext_artifact_lock = threading.RLock()
        
        # 初始化缓存
        self.paper_abstract_cache = dc.Cache(
            os.path.join(self.cache_path, "paper_abstracts")
        )
        
        # title to paper_id lookup cache (for filter_papers_local_paper_graph)
        self.title_lookup_cache = dc.Cache(
            os.path.join(self.cache_path, "title_lookup_cache")
        )
        
        # embedding model (lazy loading)
        self.embedding_model = None
        self._model_device = None

    def _get_embedding_model(self):
        """Lazy load and cache the embedding model."""
        if self.embedding_model is not None:
            return self.embedding_model
        
        model_name = self.config.ModuleInfo.WorkCollector.sentence_transformer_model
        try:
            self.embedding_model, self._model_device = load_sentence_transformer_auto(
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
                self.embedding_model, self._model_device = load_sentence_transformer_auto(
                    model_name,
                    logger=self.logger,
                )
            else:
                try:
                    self.embedding_model, self._model_device = load_sentence_transformer_auto(
                        model_name,
                        logger=self.logger,
                    )
                except Exception as e2:
                    self.logger.error(f"Failed to load SentenceTransformer model: {e2}")
                    raise e2
        
        return self.embedding_model

    @staticmethod
    def _resolve_paper_reference_id(paper_ref: Any) -> str:
        """Normalize a paper lookup result into the cache/download paper id."""
        if isinstance(paper_ref, str):
            return paper_ref.strip()

        if not isinstance(paper_ref, dict):
            return ""

        openalex_id = OpenAlexAPI.normalize_work_id(
            paper_ref.get("openalex_id") or paper_ref.get("id")
        )
        if openalex_id:
            return openalex_id

        external_ids = paper_ref.get("externalIds")
        if isinstance(external_ids, dict):
            for key in ("ArXiv", "arXiv", "ARXIV"):
                value = external_ids.get(key)
                if value is not None and str(value).strip():
                    return str(value).strip()

        for key in ("paperId", "paper_id", "id", "corpusId"):
            value = paper_ref.get(key)
            if value is not None and str(value).strip():
                return str(value).strip()

        return ""

    def is_valid_abstract(self, abstract: str) -> bool:
        if not isinstance(abstract, str):
            return False
        if not abstract or abstract.strip() == "" or abstract == "abstract not found" or len(abstract) < 50:
            return False
        if len(abstract) < 300 and len(abstract) > 50:
            self.logger.warning(f"abstract too short, deug for safety: {abstract}")
        return True

    def add_papers_abstracts_in_cache(self, papers: List[str], retry: int = 1):
        """获取并缓存paper的摘要信息"""
        err_papers = []
        for pid in papers:
            hash_id = get_hash(pid)
            # already cached
            if hash_id in self.paper_abstract_cache:
                if self.is_valid_abstract(self.paper_abstract_cache[hash_id]["abstract"]):
                    continue

            abstract = ""
            title = ""
            
            # fetch minimal metadata including abstract
            for attempt in range(retry):
                paper = None
                if OpenAlexAPI.is_openalex_work_id(pid):
                    try:
                        paper = self.openalex_api.get_paper_details(pid)
                    except Exception as e:
                        self.logger.warning(
                            f"Error fetching paper {pid} details from OpenAlex: {e}. "
                            f"Retrying {attempt + 1}/{retry}..."
                        )
                        paper = None
                else:
                    query_id = f"ARXIV:{pid}" if "." in pid else pid
                    try:
                        if "." in pid and "v" in pid:
                            raise ValueError(
                                f"arxiv id with version that semantic scholar cannot read: {pid}"
                            )
                        paper = self.semantic_scholar_api.get_paper_details(
                            query_id, fields="abstract,title,externalIds"
                        )
                        abstract = paper.get("abstract", "") or ""
                        if not abstract:
                            raise ValueError(
                                f"Failed to get abstract for {query_id} in semantic scholar, turn to arxiv"
                            )
                    except Exception as e:
                        self.logger.warning(
                            f"Error fetching paper {pid} details from Semantic Scholar: {e}. "
                            f"Retrying {attempt + 1}/{retry}..."
                        )
                        paper = None
                    if not paper and "." in pid:
                        try:
                            self.logger.info(f"Trying arXiv API for paper {pid} as fallback.")
                            paper = self.arxiv_api.get_paper_details(pid)
                        except Exception as e:
                            self.logger.warning(
                                f"Error fetching from arXiv for {pid}: {e}. "
                                f"Retrying {attempt + 1}/{retry}..."
                            )
                            paper = None

                if not paper:
                    continue
                    
                abstract = paper.get("abstract", "") or ""
                title = paper.get("title", "") or ""

                if not self.is_valid_abstract(abstract):
                    self.logger.warning(f"No abstract found for {pid}. or abstract too short, len: {len(abstract)}.")
                    err_papers.append(pid)
                    continue

                if self.config.BasicInfo.debug:
                    self.logger.info(f"Add abstract for {pid}: {len(abstract)} chars.")
                break
            
            if self.is_valid_abstract(abstract):
                self.paper_abstract_cache[hash_id] = {
                    "paper_id": pid,
                    "abstract": abstract,
                    "title": title,
                }
                
                if self.config.BasicInfo.debug:
                    self.logger.info(f"Cached abstract for {pid}: {len(abstract)} chars.")
            else:
                err_papers.append(pid)
                
        return err_papers

    def get_paper_title_abstract(self, paper_id: str, retry: int = 1):
        """获取paper的title和abstract"""
        hash_id = get_hash(paper_id)
        # already cached
        if hash_id in self.paper_abstract_cache and self.is_valid_abstract(self.paper_abstract_cache[hash_id]['abstract']):
            # if self.config.BasicInfo.debug:
            #     self.logger.info(f"Cache hit for paper {paper_id} abstract, len: {len(self.paper_abstract_cache[hash_id]['abstract'])}")
            return self.paper_abstract_cache[hash_id]['title'], self.paper_abstract_cache[hash_id]['abstract']

        self.add_papers_abstracts_in_cache([paper_id], retry=retry)
        if hash_id in self.paper_abstract_cache and self.is_valid_abstract(self.paper_abstract_cache[hash_id]['abstract']):
            if self.config.BasicInfo.debug:
                self.logger.info(f"Fetched and cached abstract for paper {paper_id}, len: {len(self.paper_abstract_cache[hash_id]['abstract'])}")
            return self.paper_abstract_cache[hash_id]['title'], self.paper_abstract_cache[hash_id]['abstract']
        else:
            raise ValueError(f"Failed to get valid abstract for paper ID {paper_id} after {retry} retries.")

    def get_paper_title(self, paper_id: str, retry: int = 3):
        """获取paper的title"""
        hash_id = get_hash(paper_id)
        # already cached
        if hash_id in self.paper_abstract_cache:
            # if self.config.BasicInfo.debug:
            #     self.logger.info(f"Cache hit for paper {paper_id} title, title: {self.paper_abstract_cache[hash_id]['title']}")
            return self.paper_abstract_cache[hash_id]['title']

        self.add_papers_abstracts_in_cache([paper_id], retry=retry)
        if hash_id in self.paper_abstract_cache:
            if self.config.BasicInfo.debug:
                self.logger.info(f"Fetched and cached title for paper {paper_id}, len: {len(self.paper_abstract_cache[hash_id]['title'])}")
            return self.paper_abstract_cache[hash_id]['title']
        else:
            raise ValueError(f"Failed to get valid abstract for paper ID {paper_id} after {retry} retries.")

    @staticmethod
    def _deduplicate_urls(urls):
        seen = set()
        unique_urls = []
        for url in urls:
            normalized = str(url or "").strip()
            if normalized and normalized not in seen:
                seen.add(normalized)
                unique_urls.append(normalized)
        return unique_urls

    def _fulltext_setting(self, name, default):
        module_info = getattr(getattr(self, "config", None), "ModuleInfo", None)
        work_collector = getattr(module_info, "WorkCollector", None)
        return getattr(work_collector, name, default)

    @staticmethod
    def _fulltext_enabled(value):
        return str(value).strip().casefold() not in {"0", "false", "no", "off"}

    def _fulltext_download_enabled(self):
        return self._fulltext_enabled(
            self._fulltext_setting("fulltext_download_enabled", True)
        )

    @staticmethod
    def _safe_provenance_url(url):
        """Keep URL provenance useful without persisting signed query parameters."""
        raw = str(url or "").strip()
        if not raw:
            return ""
        parsed = urlsplit(raw)
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
            return ""
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))

    def _fulltext_provenance_path(self, paper_id):
        return os.path.join(
            self.cache_path,
            "fulltext_provenance",
            f"{paper_id}.json",
        )

    def _write_fulltext_provenance(self, paper_id, payload):
        """Atomically persist non-sensitive acquisition provenance for one paper."""
        if not self._fulltext_enabled(self._fulltext_setting("fulltext_provenance_enabled", True)):
            return
        path = self._fulltext_provenance_path(paper_id)
        directory = os.path.dirname(path)
        os.makedirs(directory, exist_ok=True)
        temporary_path = f"{path}.tmp"
        try:
            with open(temporary_path, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            os.replace(temporary_path, path)
        except OSError as exc:
            self.logger.warning(
                "Could not write full-text provenance for %s: %s", paper_id, exc
            )
            try:
                if os.path.exists(temporary_path):
                    os.remove(temporary_path)
            except OSError:
                pass

    @staticmethod
    def _fulltext_summary_from_provenance(paper_id, provenance, provenance_path):
        """Produce acquisition metadata without making a scientific claim.

        A downloaded PDF makes a paper available for subsequent parsing.  It is
        deliberately insufficient to enable direct writing: that also requires
        evidence localization and the existing writing-consumer checks.
        """

        outcome = dict(provenance.get("outcome") or {})
        status = str(outcome.get("status") or "fulltext_fetch_failed")
        resolution = dict(provenance.get("resolution") or {})
        return {
            "schema_version": "fulltext_acquisition_summary_v1",
            "paper_id": str(paper_id or ""),
            "status": status,
            "fulltext_available": status in {"downloaded", "cache_hit"},
            # Full-text acquisition is a prerequisite, never an automatic
            # upgrade to direct scientific evidence or a writing assertion.
            "writing_direct_evidence_allowed": False,
            "candidate_count": int(resolution.get("candidate_count") or 0),
            "attempt_count": len(provenance.get("attempts") or []),
            "selected_source": str(outcome.get("selected_source") or ""),
            "provenance_path": str(provenance_path or ""),
        }

    @classmethod
    def _attach_fulltext_summary_to_paper_records(
        cls,
        value,
        paper_id,
        summary,
        _visited=None,
    ):
        """Attach an acquisition summary without touching semantic fields."""

        visited = _visited if isinstance(_visited, set) else set()
        if isinstance(value, list):
            if id(value) in visited:
                return
            visited.add(id(value))
            for item in value:
                cls._attach_fulltext_summary_to_paper_records(
                    item, paper_id, summary, visited
                )
            return
        if not isinstance(value, dict):
            return
        if id(value) in visited:
            return
        visited.add(id(value))
        identifiers = {
            str(value.get(key) or "").strip()
            for key in ("paperId", "paper_id", "openalex_id", "id")
        }
        external_ids = value.get("externalIds")
        if isinstance(external_ids, dict):
            identifiers.update(
                str(external_ids.get(key) or "").strip()
                for key in ("OpenAlex", "ArXiv", "arXiv")
            )
        if str(paper_id or "") in identifiers:
            value["fulltext_acquisition"] = dict(summary)
        for key, child in value.items():
            if key in {"fulltext_acquisition", "fulltext_acquisition_by_paper"}:
                continue
            if isinstance(child, (dict, list)):
                cls._attach_fulltext_summary_to_paper_records(
                    child, paper_id, summary, visited
                )

    def _persist_sh_graph_fulltext_summary(self, graph_artifact):
        basic_info = self.config.BasicInfo
        artifact_path = str(
            getattr(basic_info, "sh_graph_provenance_artifact_path", "") or ""
        ).strip()
        if not artifact_path:
            base_dir = str(getattr(basic_info, "base_dir", "") or "").strip()
            if base_dir:
                artifact_path = os.path.join(base_dir, "sh_graph_provenance.json")
        if not artifact_path:
            return
        directory = os.path.dirname(artifact_path)
        temporary_path = f"{artifact_path}.tmp"
        try:
            os.makedirs(directory, exist_ok=True)
            with open(temporary_path, "w", encoding="utf-8") as handle:
                json.dump(graph_artifact, handle, ensure_ascii=False, indent=2)
            os.replace(temporary_path, artifact_path)
        except OSError as exc:
            self.logger.warning("Could not persist SH graph full-text summary: %s", exc)
            self._remove_incomplete_pdf(temporary_path)

    def _publish_fulltext_acquisition_summary(self, paper_id, provenance):
        """Write acquisition state to artifacts while preserving SH semantics.

        This method only adds a separate `fulltext_acquisition` namespace.  It
        must not clear or reinterpret `sh_semantic_assessments`, `sh_matches`,
        seed tiers, graph modes, or direct-evidence annotations.
        """

        if not self._fulltext_enabled(self._fulltext_setting("fulltext_provenance_enabled", True)):
            return
        summary = self._fulltext_summary_from_provenance(
            paper_id,
            provenance,
            self._fulltext_provenance_path(paper_id),
        )
        with self._fulltext_artifact_lock:
            basic_info = self.config.BasicInfo
            fulltext_by_paper = getattr(basic_info, "fulltext_acquisition_by_paper", {})
            fulltext_by_paper = (
                dict(fulltext_by_paper) if isinstance(fulltext_by_paper, Mapping) else {}
            )
            fulltext_by_paper[str(paper_id)] = dict(summary)
            try:
                basic_info.fulltext_acquisition_by_paper = fulltext_by_paper
            except Exception:
                pass

            sh_artifact = getattr(basic_info, "subhypothesis_retrieval", None)
            if isinstance(sh_artifact, dict):
                sh_artifact.setdefault("fulltext_acquisition_by_paper", {})[str(paper_id)] = dict(summary)
                self._attach_fulltext_summary_to_paper_records(sh_artifact, paper_id, summary)

            graph_artifact = getattr(basic_info, "sh_graph_provenance", None)
            if isinstance(graph_artifact, dict):
                graph_artifact.setdefault("fulltext_acquisition_by_paper", {})[str(paper_id)] = dict(summary)
                self._persist_sh_graph_fulltext_summary(graph_artifact)

    @classmethod
    def _safe_candidate_for_provenance(cls, candidate):
        if not isinstance(candidate, dict):
            return {}
        safe = {
            key: value
            for key, value in candidate.items()
            if key
            in {
                "kind",
                "source",
                "sources",
                "priority",
                "version",
                "license",
                "host_type",
                "evidence",
                "metadata_field",
                "oa_evidence",
                "doi",
                "status",
            }
            and value not in (None, "", [], {})
        }
        safe["url"] = cls._safe_provenance_url(candidate.get("url"))
        return safe

    @classmethod
    def _download_status_for_http_status(cls, status_code):
        if status_code == 404:
            return "not_found"
        if status_code == 401:
            return "authentication_required"
        if status_code == 403:
            return "access_denied"
        if status_code == 429:
            return "rate_limited"
        if isinstance(status_code, int) and status_code >= 500:
            return "transient_failure"
        return "http_error"

    @staticmethod
    def _remove_incomplete_pdf(filename):
        for path in (filename, f"{filename}.part"):
            try:
                if os.path.exists(path):
                    os.remove(path)
            except OSError:
                pass

    @staticmethod
    def _paper_doi(paper):
        if not isinstance(paper, dict):
            return ""
        external_ids = paper.get("externalIds")
        if isinstance(external_ids, dict):
            doi = external_ids.get("DOI") or external_ids.get("doi")
            if str(doi or "").strip():
                return UnpaywallAPI.normalize_doi(doi)
        return UnpaywallAPI.normalize_doi(paper.get("doi"))

    @staticmethod
    def _paper_download_id(paper):
        if isinstance(paper, str):
            return paper.strip()
        if not isinstance(paper, dict):
            return ""
        if str(paper.get("api_platform") or "").lower() == "openalex":
            openalex_id = OpenAlexAPI.normalize_work_id(
                paper.get("openalex_id") or paper.get("paperId")
            )
            if openalex_id:
                return openalex_id
        external_ids = paper.get("externalIds")
        if isinstance(external_ids, dict):
            arxiv_id = external_ids.get("ArXiv") or external_ids.get("arXiv")
            if str(arxiv_id or "").strip():
                return str(arxiv_id).strip()
        return str(paper.get("paperId") or paper.get("paper_id") or "").strip()

    def _has_pdf_download_candidate(self, paper):
        if isinstance(paper, str):
            return "." in paper or OpenAlexAPI.is_openalex_work_id(paper)
        if not isinstance(paper, dict):
            return False
        external_ids = paper.get("externalIds")
        if isinstance(external_ids, dict) and any(
            str(external_ids.get(key) or "").strip() for key in ("ArXiv", "arXiv")
        ):
            return True
        open_access_pdf = paper.get("openAccessPdf")
        if isinstance(open_access_pdf, dict) and str(open_access_pdf.get("url") or "").strip():
            return True
        openalex_oa_locations = paper.get("openalex_oa_locations")
        if isinstance(openalex_oa_locations, (list, tuple)) and any(
            isinstance(location, Mapping)
            and any(
                str(location.get(key) or "").strip()
                for key in ("pdf_url", "url_for_pdf", "landing_page_url", "url")
            )
            for location in openalex_oa_locations
        ):
            return True
        if any(
            str(paper.get(key) or "").strip()
            for key in (
                "repository_pdf",
                "repository_url",
                "accepted_manuscript_url",
                "author_manuscript_url",
                "open_repository_url",
                "pmcid",
            )
        ):
            return True
        if isinstance(external_ids, dict) and any(
            str(external_ids.get(key) or "").strip()
            for key in ("PMCID", "pmcid", "PMC")
        ):
            return True
        generic_direct_fields = (
            "pdf_url",
            "url_for_pdf",
            "full_text_pdf_url",
            "fulltext_pdf_url",
            "oa_pdf_url",
        )
        if any(str(paper.get(key) or "").strip() for key in generic_direct_fields):
            return True
        for key in ("full_text_url", "fulltext_url"):
            value = str(paper.get(key) or "").strip()
            if urlsplit(value).path.lower().endswith(".pdf"):
                return True
        # Let resolution record a generic landing URL as disabled when it lacks
        # OA evidence; the resolver itself will not make an HTTP request in
        # that case.  This keeps the provenance explainable instead of
        # silently discarding incoming metadata.
        if any(
            str(paper.get(key) or "").strip()
            for key in (
                "full_text_url",
                "fulltext_url",
                "landing_page_url",
                "url_for_landing_page",
            )
        ):
            return True
        for container_key in ("fulltext", "full_text"):
            container = paper.get(container_key)
            if isinstance(container, Mapping) and any(
                str(container.get(key) or "").strip()
                for key in (
                    "pdf_url",
                    "url_for_pdf",
                    "full_text_pdf_url",
                    "fulltext_pdf_url",
                    "oa_pdf_url",
                    "full_text_url",
                    "fulltext_url",
                    "landing_page_url",
                    "url_for_landing_page",
                )
            ):
                return True
        return bool(self._paper_doi(paper) and self.unpaywall_api.enabled)

    def _prepare_download_info(self, paper, reference_graph=None):
        """Build ordered, provenance-rich legal full-text candidates for one paper."""
        del reference_graph
        if isinstance(paper, str) and OpenAlexAPI.is_openalex_work_id(paper):
            resolved_paper = self.openalex_api.get_paper_details(paper)
            if not resolved_paper:
                return None
            return self._prepare_download_info(resolved_paper)

        resolution = {}
        download_candidates = []
        paper_id = ""
        paper_title = ""

        if isinstance(paper, dict):
            paper_id = self._paper_download_id(paper)
            if not paper_id:
                return None
            resolution = resolve_fulltext_candidates(
                paper,
                unpaywall_api=(
                    self.unpaywall_api
                    if self._fulltext_enabled(
                        self._fulltext_setting("fulltext_resolution_enabled", True)
                    )
                    else None
                ),
                include_all_unpaywall_locations=self._fulltext_enabled(
                    self._fulltext_setting(
                        "fulltext_unpaywall_all_locations_enabled", True
                    )
                ),
                include_generic_metadata_urls=self._fulltext_enabled(
                    self._fulltext_setting("fulltext_generic_metadata_urls_enabled", True)
                ),
                include_doi_landing_fallback=self._fulltext_enabled(
                    self._fulltext_setting("fulltext_doi_landing_fallback_enabled", True)
                ),
            )
            download_candidates = list(resolution.get("candidates") or [])
            paper_title = str(paper.get("title") or paper_id)
        elif isinstance(paper, str) and "." in paper:
            paper_id = paper.strip()
            download_candidates.extend(
                [
                    {
                        "url": f"https://arxiv.org/pdf/{paper_id}.pdf",
                        "kind": "pdf",
                        "source": "identifier.arxiv",
                        "priority": 100,
                        "version": "preprint",
                    },
                    {
                        "url": f"https://export.arxiv.org/pdf/{paper_id}.pdf",
                        "kind": "pdf",
                        "source": "identifier.arxiv_mirror",
                        "priority": 101,
                        "version": "preprint",
                    },
                ]
            )
            resolution = {
                "schema_version": "fulltext_resolution_v2",
                "paper_id": paper_id,
                "doi": "",
                "candidates": list(download_candidates),
                "deferred_candidates": [],
                "disabled_candidates": [],
                "unpaywall": {"status": "not_requested"},
            }
            paper_title = paper_id
        else:
            return None

        pdf_path = os.path.join(
            self.cache_path,
            "pdf_papers",
            paper_id,
            f"{paper_id}.pdf",
        )
        return (paper_id, download_candidates, pdf_path, paper_title, resolution)

    def _record_no_fulltext_candidate(self, paper, resolution=None):
        paper_id = self._paper_download_id(paper)
        if not paper_id:
            return
        resolution = dict(resolution or {})
        provenance = {
            "schema_version": "fulltext_acquisition_v1",
            "paper_id": paper_id,
            "doi": self._paper_doi(paper) if isinstance(paper, dict) else "",
            "resolution": {
                "unpaywall": dict(
                    resolution.get("unpaywall") or {"status": "not_requested"}
                ),
                "candidate_count": 0,
                "candidates": [],
                "access_context_generation": self.fulltext_download_coordinator.access_context_generation,
            },
            "attempts": [],
            "outcome": {"status": "no_open_access_candidate", "attempted_candidate_count": 0},
        }
        self._write_fulltext_provenance(paper_id, provenance)
        self._publish_fulltext_acquisition_summary(paper_id, provenance)

    def _download_pdf_candidate(self, candidate, *, pdf_path, paper_title, index, total):
        """Acquire one PDF route under URL/host coordination and validate it."""

        url = str(candidate.get("url") or "")
        source = str(candidate.get("source") or "")

        def perform_network_download():
            attempt = self._download_pdf_with_resume(
                url=url,
                filename=pdf_path,
                title=f"{paper_title} ({index}/{total})",
                is_arxiv=source.startswith("identifier.arxiv"),
                return_attempt=True,
            )
            if attempt.get("downloaded") and not is_valid_pdf(pdf_path):
                attempt["downloaded"] = False
                attempt["status"] = "non_pdf"
                self._remove_incomplete_pdf(pdf_path)
            return attempt

        return self.fulltext_download_coordinator.execute(
            url=url,
            kind="pdf",
            destination_path=pdf_path,
            validator=is_valid_pdf,
            operation=perform_network_download,
        )

    def _resolve_landing_candidate(self, candidate):
        """Resolve a declared OA landing page through the same URL/host guard."""

        def resolve_landing():
            return resolve_declared_pdf_links(
                candidate,
                http_client=getattr(self, "fulltext_http_client", None),
                timeout_seconds=float(
                    self._fulltext_setting("fulltext_landing_page_timeout_seconds", 20)
                ),
                max_html_bytes=int(
                    self._fulltext_setting("fulltext_landing_page_max_bytes", 1_500_000)
                ),
                max_pdf_links=int(
                    self._fulltext_setting("fulltext_max_declared_pdf_links_per_landing_page", 8)
                ),
                max_redirects=int(
                    self._fulltext_setting("fulltext_landing_page_max_redirects", 5)
                ),
            )

        return self.fulltext_download_coordinator.execute(
            url=str(candidate.get("url") or ""),
            kind="landing_page",
            operation=resolve_landing,
            is_success=lambda result: str(result.get("status") or "")
            in {"resolved_to_pdf", "pdf_links_found"},
        )

    def _has_parsed_markdown(self, paper_id: str) -> bool:
        markdown_path = os.path.join(
            self.cache_path,
            "parsed_papers",
            str(paper_id),
            "auto",
            f"{paper_id}.md",
        )
        return os.path.exists(markdown_path)

    def _download_single_paper(self, paper, index, total, reference_graph=None):
        """下载单个paper，返回(paper_id, pdf_path)或(None, None)"""
        # 准备下载信息
        info = self._prepare_download_info(paper, reference_graph)
        if info is None:
            self._record_no_fulltext_candidate(paper)
            return (None, None)
        
        paper_id, download_candidates, pdf_path, paper_title, resolution = info
        provenance = {
            "schema_version": "fulltext_acquisition_v1",
            "paper_id": paper_id,
            "doi": str(resolution.get("doi") or ""),
            "resolution": {
                "unpaywall": dict(resolution.get("unpaywall") or {}),
                "candidate_count": len(download_candidates),
                "candidates": [
                    self._safe_candidate_for_provenance(candidate)
                    for candidate in download_candidates
                    if isinstance(candidate, dict)
                ],
                "deferred_candidates": [
                    self._safe_candidate_for_provenance(candidate)
                    for candidate in resolution.get("deferred_candidates") or []
                    if isinstance(candidate, dict)
                ],
                "disabled_candidates": [
                    self._safe_candidate_for_provenance(candidate)
                    for candidate in resolution.get("disabled_candidates") or []
                    if isinstance(candidate, dict)
                ],
                "access_context_generation": self.fulltext_download_coordinator.access_context_generation,
            },
            "attempts": [],
            "outcome": {},
        }
        
        # 检查缓存
        if (
            not self.config.ModuleInfo.WorkCollector.download_safe_mode
            and os.path.exists(pdf_path)
        ):
            if is_valid_pdf(pdf_path):
                if self.config.BasicInfo.debug:
                    self.logger.info(f"Cache Hit! Existing PDF at {pdf_path} is valid, skipping download.")
                provenance["outcome"] = {
                    "status": "cache_hit",
                    "pdf_path": pdf_path,
                }
                self._write_fulltext_provenance(paper_id, provenance)
                self._publish_fulltext_acquisition_summary(paper_id, provenance)
                return (paper_id, pdf_path)
            else:
                try:
                    os.remove(pdf_path)
                except OSError as e:
                    self.logger.error(f"Failed to delete invalid PDF {pdf_path}: {e}")
                self.logger.warning(f"Existing PDF at {pdf_path} is invalid, re-downloading.")
        
        os.makedirs(os.path.dirname(pdf_path), exist_ok=True)
        
        # A candidate describes one alternative legal acquisition route.  A
        # failure must not change the paper's SH/project relevance decision.
        downloaded = False
        selected_candidate = {}
        candidate_queue = list(download_candidates)
        candidate_index = 0
        max_candidates = max(
            1,
            int(self._fulltext_setting("fulltext_max_candidates_per_paper", 12) or 12),
        )
        while candidate_index < len(candidate_queue) and candidate_index < max_candidates:
            candidate = candidate_queue[candidate_index]
            candidate_index += 1
            if not isinstance(candidate, dict):
                continue
            source = str(candidate.get("source") or "unknown")
            kind = str(candidate.get("kind") or "pdf")
            download_url = str(candidate.get("url") or "")
            if not download_url:
                continue
            if kind == "landing_page":
                landing = self._resolve_landing_candidate(candidate)
                landing_attempt = {
                    **self._safe_candidate_for_provenance(candidate),
                    "status": str(landing.get("status") or "fetch_failed"),
                    "http_status": landing.get("http_status"),
                    "final_url": self._safe_provenance_url(landing.get("final_url")),
                    "requested_host": str(urlsplit(download_url).netloc or "").lower(),
                    "final_host": str(
                        urlsplit(str(landing.get("final_url") or "")).netloc or ""
                    ).lower(),
                    "content_type": str(landing.get("content_type") or ""),
                    "elapsed_seconds": landing.get("elapsed_seconds"),
                    "redirect_count": landing.get("redirect_count"),
                    "declared_pdf_count": len(landing.get("pdf_candidates") or []),
                }
                provenance["attempts"].append(landing_attempt)
                if source == "doi.landing_fallback":
                    self.logger.info(
                        "Full-text DOI fallback paper=%s doi=%s status=%s http_status=%s "
                        "redirect_count=%s declared_pdf_count=%s.",
                        paper_id,
                        provenance.get("doi") or "",
                        landing_attempt["status"],
                        landing_attempt["http_status"],
                        landing_attempt["redirect_count"],
                        landing_attempt["declared_pdf_count"],
                    )
                else:
                    self.logger.info(
                        "Full-text landing resolution paper=%s source=%s status=%s "
                        "http_status=%s declared_pdf_count=%s.",
                        paper_id,
                        source,
                        landing_attempt["status"],
                        landing_attempt["http_status"],
                        landing_attempt["declared_pdf_count"],
                    )
                declared = [
                    item
                    for item in landing.get("pdf_candidates") or []
                    if isinstance(item, dict)
                ]
                max_declared_pdf_attempts = max(
                    1,
                    int(
                        self._fulltext_setting(
                            "fulltext_max_doi_landing_recovery_pdf_attempts", 4
                        )
                        or 4
                    ),
                )
                candidate_queue[candidate_index:candidate_index] = declared[
                    :max_declared_pdf_attempts
                ]
                continue

            attempt = self._download_pdf_candidate(
                candidate,
                pdf_path=pdf_path,
                paper_title=paper_title,
                index=index,
                total=total,
            )
            attempt_record = {
                **self._safe_candidate_for_provenance(candidate),
                **{
                    key: value
                    for key, value in attempt.items()
                    if key not in {"requested_url", "final_url"}
                },
                "final_url": self._safe_provenance_url(attempt.get("final_url")),
                "requested_host": str(urlsplit(download_url).netloc or "").lower(),
                "final_host": str(
                    urlsplit(str(attempt.get("final_url") or "")).netloc or ""
                ).lower(),
            }
            downloaded = bool(attempt.get("downloaded"))
            if downloaded and not is_valid_pdf(pdf_path):
                attempt_record["status"] = "non_pdf"
                downloaded = False
                self.fulltext_download_coordinator.invalidate_url(download_url)
            provenance["attempts"].append(attempt_record)
            if not downloaded:
                self.logger.warning(
                    "Full-text attempt failed paper=%s source=%s status=%s "
                    "http_status=%s content_type=%s; trying next candidate if available.",
                    paper_id,
                    source,
                    attempt_record.get("status"),
                    attempt_record.get("http_status"),
                    attempt_record.get("content_type"),
                )
                self._remove_incomplete_pdf(pdf_path)
                continue
            selected_candidate = candidate
            break

        if not downloaded or not is_valid_pdf(pdf_path):
            statuses = {
                str(attempt.get("status") or "")
                for attempt in provenance["attempts"]
                if isinstance(attempt, dict)
            }
            outcome_status = (
                "authentication_required"
                if "authentication_required" in statuses
                else "open_access_access_denied"
                if "access_denied" in statuses
                else "rate_limited"
                if "rate_limited" in statuses
                else "no_open_access_candidate"
                if not provenance["attempts"]
                else "fulltext_fetch_failed"
            )
            provenance["outcome"] = {
                "status": outcome_status,
                "attempted_candidate_count": len(provenance["attempts"]),
            }
            self._write_fulltext_provenance(paper_id, provenance)
            self._publish_fulltext_acquisition_summary(paper_id, provenance)
            self.logger.warning(
                "Full-text resolution failed paper=%s doi=%s outcome=%s attempts=%s.",
                paper_id,
                provenance.get("doi") or "",
                outcome_status,
                len(provenance["attempts"]),
            )
            self._remove_incomplete_pdf(pdf_path)
            return (None, None)
        provenance["outcome"] = {
            "status": "downloaded",
            "selected_source": str(selected_candidate.get("source") or ""),
            "selected_url": self._safe_provenance_url(selected_candidate.get("url")),
            "pdf_path": pdf_path,
        }
        self._write_fulltext_provenance(paper_id, provenance)
        self._publish_fulltext_acquisition_summary(paper_id, provenance)
        self.logger.info(
            "Full-text resolution completed paper=%s doi=%s source=%s attempts=%s.",
            paper_id,
            provenance.get("doi") or "",
            provenance["outcome"]["selected_source"],
            len(provenance["attempts"]),
        )
        return (paper_id, pdf_path)

    def _download_papers_serial(self, papers: list, limit: int = -1):
        """串行下载papers"""
        valid_paper_ids = []
        valid_paper_paths = []
        valid_paper_paths_ids = []
        
        reference_graph = self._get_reference_graph()
        
        index = 0
        total = min(len(papers), limit) if limit > 0 else len(papers)
        
        while index < len(papers) and (limit < 0 or len(valid_paper_ids) < limit):
            paper = papers[index]
            index += 1
            
            # 处理abstract_when_full_text_fail的情况
            if isinstance(paper, dict):
                paper_id = self._paper_download_id(paper)
                if not self._has_pdf_download_candidate(paper):
                    self._record_no_fulltext_candidate(paper)
                    if self.config.ModuleInfo.WorkAnalyzer.abstract_when_full_text_fail:
                        self.logger.info(f"No full text PDF found for paper {paper_id}, skipping download but keeping abstract.")
                        err = self.add_papers_abstracts_in_cache([paper_id])
                        if not err:
                            valid_paper_ids.append(paper_id)
                        continue
                    else:
                        continue
            
            paper_id, pdf_path = self._download_single_paper(paper, index, total, reference_graph)
            
            if paper_id and pdf_path:
                valid_paper_ids.append(paper_id)
                if not self._has_parsed_markdown(paper_id):
                    valid_paper_paths.append(pdf_path)
                    valid_paper_paths_ids.append(paper_id)
        
        return valid_paper_ids, valid_paper_paths, valid_paper_paths_ids

    def _download_papers_parallel(self, papers: list, limit: int = -1):
        """并行下载papers"""
        valid_paper_ids = []
        valid_paper_paths = []
        valid_paper_paths_ids = []
        
        reference_graph = self._get_reference_graph()
        
        # 过滤需要下载的papers
        download_tasks = []
        limit = limit if limit > 0 else len(papers)
        
        for idx, paper in enumerate(papers[:limit]):
            # 处理特殊情况
            if isinstance(paper, dict):
                paper_id = self._paper_download_id(paper)
                if not self._has_pdf_download_candidate(paper):
                    self._record_no_fulltext_candidate(paper)
                    if self.config.ModuleInfo.WorkAnalyzer.abstract_when_full_text_fail:
                        self.logger.info(f"No full text PDF found for paper {paper_id}, skipping download but keeping abstract.")
                        err = self.add_papers_abstracts_in_cache([paper_id])
                        if not err:
                            valid_paper_ids.append(paper_id)
                        continue
                    else:
                        continue
            elif isinstance(paper, str) and not self._has_pdf_download_candidate(paper):
                continue
            
            download_tasks.append((idx + 1, paper))
        
        if not download_tasks:
            return valid_paper_ids, valid_paper_paths, valid_paper_paths_ids
        
        total = len(download_tasks)
        max_workers = getattr(self.config.ModuleInfo.WorkCollector, 'download_parallel_workers', 4)
        
        self.logger.info(f"Starting parallel download with {max_workers} workers for {len(download_tasks)} papers...")
        
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(self._download_single_paper, paper, idx, total, reference_graph): idx
                for idx, paper in download_tasks
            }
            
            for future in as_completed(futures):
                try:
                    paper_id, pdf_path = future.result()
                    if paper_id and pdf_path:
                        valid_paper_ids.append(paper_id)
                        if not self._has_parsed_markdown(paper_id):
                            valid_paper_paths.append(pdf_path)
                            valid_paper_paths_ids.append(paper_id)
                except Exception as e:
                    self.logger.error(f"Error in parallel download: {e}")
        
        return valid_paper_ids, valid_paper_paths, valid_paper_paths_ids

    def _download_pdf_with_resume(self, url: str, filename: str, title: str, is_arxiv: bool = False, chunk_size: int = 1024 * 1024, return_attempt: bool = False):
        """下载PDF文件，支持断点续传"""
        started_at = time.monotonic()
        attempt = {
            "downloaded": False,
            "status": "fetch_failed",
            "requested_url": str(url or ""),
            "final_url": str(url or ""),
            "http_status": None,
            "content_type": "",
            "bytes_written": 0,
            "requested_host": str(urlsplit(str(url or "")).netloc or "").lower(),
            "final_host": str(urlsplit(str(url or "")).netloc or "").lower(),
        }

        def finish(downloaded):
            attempt["downloaded"] = bool(downloaded)
            attempt["elapsed_seconds"] = round(time.monotonic() - started_at, 3)
            return attempt if return_attempt else bool(downloaded)

        partial_filename = f"{filename}.part"
        temp_size = os.path.getsize(partial_filename) if os.path.exists(partial_filename) else 0
            
        headers = {"Range": f"bytes={temp_size}-"}
        if is_arxiv:
            headers = {
                "User-Agent": "Xcientist/0.8 (academic PDF downloader)",
                "Range": f"bytes={temp_size}-"
            }

        if self.config.BasicInfo.debug:
            self.logger.info(
                "[%s] Resuming download from byte %s from %s",
                title,
                temp_size,
                self._safe_provenance_url(url),
            )

        http_client = getattr(self, "fulltext_http_client", None)
        request_get = http_client.get if http_client is not None else requests.get
        request_timeout = None if http_client is not None else self.config.ModuleInfo.WorkCollector.download_timeout
        try:
            with closing(
                request_get(
                    url,
                    headers=headers,
                    stream=True,
                    timeout=request_timeout,
                    allow_redirects=True,
                )
            ) as resp:
                attempt["http_status"] = int(resp.status_code)
                attempt["final_url"] = str(getattr(resp, "url", "") or url)
                attempt["final_host"] = str(
                    urlsplit(attempt["final_url"]).netloc or ""
                ).lower()
                attempt["content_type"] = str(resp.headers.get("Content-Type") or "").lower()

                if resp.status_code not in (200, 206, 416):
                    attempt["status"] = self._download_status_for_http_status(resp.status_code)
                    self.logger.error(f"[{title}] Could not download file: {resp.status_code}")
                    return finish(False)

                if resp.status_code == 416:
                    if not os.path.exists(partial_filename):
                        attempt["status"] = "range_not_satisfiable"
                        return finish(False)
                    try:
                        os.replace(partial_filename, filename)
                    except OSError:
                        attempt["status"] = "finalize_failed"
                        return finish(False)
                    self.logger.info(f"[{title}] File already fully downloaded.")
                    attempt["status"] = "downloaded_response"
                    return finish(True)
                if resp.status_code == 200 and temp_size:
                    # Servers are allowed to ignore Range.  In that case the
                    # body is a complete representation, so appending it to a
                    # partial file would corrupt the PDF.
                    self.logger.info(
                        "[%s] Server ignored Range; restarting the PDF download from byte 0.",
                        title,
                    )
                    temp_size = 0
                if resp.status_code == 206:
                    content_range = str(resp.headers.get("Content-Range") or "")
                    try:
                        range_start = int(content_range.split(" ", 1)[1].split("-", 1)[0])
                    except (IndexError, ValueError):
                        attempt["status"] = "invalid_range_response"
                        return finish(False)
                    if range_start != temp_size:
                        attempt["status"] = "invalid_range_response"
                        return finish(False)
                self.logger.info(f"[{title}] Resuming download from byte {temp_size}")

                total_size = None
                if "Content-Range" in resp.headers:
                    total_size = int(resp.headers["Content-Range"].split("/")[-1])
                elif "Content-Length" in resp.headers:
                    total_size = int(resp.headers["Content-Length"]) + temp_size

                if total_size:
                    self.logger.info(f"[{title}] Total file size: {total_size} bytes")
                else:
                    self.logger.warning(f"[{title}] Total file size unknown. Progress may not be shown.")

                max_pdf_bytes = max(
                    1,
                    int(self._fulltext_setting("fulltext_pdf_max_bytes", 50_000_000) or 50_000_000),
                )
                if total_size is not None and total_size > max_pdf_bytes:
                    attempt["status"] = "too_large"
                    self.logger.warning(
                        "[%s] Full-text response exceeds configured PDF limit: %s > %s bytes.",
                        title,
                        total_size,
                        max_pdf_bytes,
                    )
                    return finish(False)

                write_mode = "ab" if resp.status_code == 206 and temp_size else "wb"
                with open(partial_filename, write_mode) as f:
                    downloaded = temp_size

                    last_time = time.time()
                    last_downloaded = downloaded

                    for chunk in resp.iter_content(chunk_size=chunk_size):
                        if chunk:
                            if downloaded + len(chunk) > max_pdf_bytes:
                                attempt["status"] = "too_large"
                                self.logger.warning(
                                    "[%s] Full-text response exceeded configured PDF limit of %s bytes.",
                                    title,
                                    max_pdf_bytes,
                                )
                                return finish(False)
                            f.write(chunk)
                            downloaded += len(chunk)
                            attempt["bytes_written"] += len(chunk)

                            now = time.time()
                            elapsed = now - last_time
                            if elapsed > 0:
                                delta_bytes = downloaded - last_downloaded
                                speed_mb_s = delta_bytes / elapsed / 1024 / 1024
                            else:
                                speed_mb_s = 0.0

                            last_time = now
                            last_downloaded = downloaded

                            if total_size:
                                percent = downloaded * 100 / total_size
                                self.logger.info(
                                    f"[{title}] {percent:.2f}% "
                                    f"({downloaded}/{total_size} bytes) "
                                    f"Speed: {speed_mb_s:.2f} MB/s"
                                )
                            else:
                                self.logger.info(
                                    f"[{title}] Downloaded {downloaded} bytes "
                                    f"Speed: {speed_mb_s:.2f} MB/s"
                                )

        except requests.Timeout as e:
            attempt["status"] = "timeout"
            self.logger.error("[%s] Download timed out (%s).", title, type(e).__name__)
            return finish(False)
        except requests.RequestException as e:
            attempt["status"] = "network_error"
            self.logger.error("[%s] Download request failed (%s).", title, type(e).__name__)
            return finish(False)
        except Exception as e:
            attempt["status"] = "fetch_failed"
            self.logger.error("[%s] Download failed (%s).", title, type(e).__name__)
            return finish(False)

        try:
            os.replace(partial_filename, filename)
        except OSError:
            attempt["status"] = "finalize_failed"
            return finish(False)
        self.logger.info(f"[{title}] Download completed → {filename}")
        attempt["status"] = "downloaded_response"
        return finish(True)

    def download_and_parse_papers(self, papers: list, limit: int = -1):
        """下载并解析papers"""
        if not self._fulltext_download_enabled():
            selected_papers = papers if limit <= 0 else papers[:limit]
            return [
                paper_id
                for paper in selected_papers
                if (paper_id := self._paper_download_id(paper))
            ]

        # 检查是否启用并行下载
        use_parallel = getattr(self.config.ModuleInfo.WorkCollector, 'download_in_parallel', False)
        
        if use_parallel:
            self.logger.info("Using parallel download mode")
            valid_paper_ids, valid_paper_paths, valid_paper_paths_ids = self._download_papers_parallel(papers, limit)
        else:
            self.logger.info("Using serial download mode")
            valid_paper_ids, valid_paper_paths, valid_paper_paths_ids = self._download_papers_serial(papers, limit)

        # step 2: parse the downloaded PDFs in bounded batches to limit memory use
        self.logger.info(f"Parsing {len(valid_paper_paths)} downloaded papers...")
        if valid_paper_paths:
            parse_batch_size = getattr(
                self.config.ModuleInfo.WorkCollector,
                "pdf_parse_batch_size",
                1,
            )
            try:
                parse_batch_size = min(4, max(1, int(parse_batch_size)))
            except (TypeError, ValueError):
                parse_batch_size = 1

            parsed_output_dir = os.path.join(self.cache_path, "parsed_papers")
            failed_paper_ids = set()

            for batch_start in range(0, len(valid_paper_paths), parse_batch_size):
                batch_paths = valid_paper_paths[batch_start : batch_start + parse_batch_size]
                batch_ids = valid_paper_paths_ids[batch_start : batch_start + parse_batch_size]
                batch_number = batch_start // parse_batch_size + 1
                batch_total = (
                    len(valid_paper_paths) + parse_batch_size - 1
                ) // parse_batch_size
                self.logger.info(
                    f"Parsing PDF batch {batch_number}/{batch_total} "
                    f"({len(batch_paths)} papers)..."
                )

                parse_doc(batch_paths, output_dir=parsed_output_dir, lang="en")

                missing_paths = []
                missing_ids = []
                for paper_path, paper_id in zip(batch_paths, batch_ids):
                    if not self._has_parsed_markdown(paper_id):
                        missing_paths.append(paper_path)
                        missing_ids.append(paper_id)

                for paper_path, paper_id in zip(missing_paths, missing_ids):
                    self.logger.warning(
                        f"Batch parsing did not produce Markdown for {paper_id}; "
                        "retrying this paper individually."
                    )
                    parse_doc([paper_path], output_dir=parsed_output_dir, lang="en")
                    if not self._has_parsed_markdown(paper_id):
                        failed_paper_ids.add(paper_id)
                        self.logger.error(f"Failed to parse paper at {paper_path}")

                gc.collect()
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()

            if failed_paper_ids:
                valid_paper_ids = [
                    paper_id for paper_id in valid_paper_ids if paper_id not in failed_paper_ids
                ]

        return valid_paper_ids

    def get_paper_raw_markdown(self, paper_id: Any) -> str:
        resolved_paper_id = self._resolve_paper_reference_id(paper_id)
        if not resolved_paper_id:
             raise ValueError("Paper id is empty or none when get_paper_raw_markdown")
        md_path = os.path.join(
            f"{self.cache_path}/parsed_papers",
            resolved_paper_id,
            "auto",
            f"{resolved_paper_id}.md",
        )
        if not os.path.exists(md_path):
            if self.config.BasicInfo.debug:
                self.logger.info(
                    f"Paper {resolved_paper_id} markdown not found in cache, re-downloading and parsing..."
                )
            try:
                self.download_and_parse_papers([paper_id if isinstance(paper_id, dict) else resolved_paper_id])
            except Exception as e:
                self.logger.error(f"Failed to parse paper {resolved_paper_id}: {e}")
                raise e
        if not os.path.exists(md_path):
            self.logger.warning(f"Markdown still missing after parse: {md_path}")
            raise ValueError("Markdown file missing in getting paper markdown")
        with open(md_path, "r", encoding="utf-8") as fr:
            paper_markdown_text = fr.read()
        return paper_markdown_text

    def get_paper_with_title_semantic(self, title: str):
        """通过Semantic Scholar API根据title搜索paper"""
        self.logger.info(f"Searching for paper with title: {title}")
        fields = "title,externalIds,openAccessPdf,abstract,authors,year,venue"
        search_results = []
        
        try:
            response = self.semantic_scholar_api.search_papers(query=title, fields=fields)
            if response and response.get("data"):
                search_results.extend(response["data"][:3])
                self.logger.info(f"Found {len(response['data'])} papers from Semantic Scholar")
        except Exception as e:
            self.logger.warning(f"Error searching Semantic Scholar for '{title}': {e}")
        
        if not search_results:
            self.logger.warning(f"No papers found for title: {title}")
            return None
        
        return self._select_best_paper_by_similarity(title, search_results)

    def get_paper_with_title_openalex(self, title: str):
        """Search OpenAlex first because it is the primary Survey discovery provider."""
        self.logger.info(f"Searching for paper with title through OpenAlex: {title}")
        try:
            search_results = self.openalex_api.search_papers(title, per_page=5)
            if search_results:
                self.logger.info(f"Found {len(search_results)} papers from OpenAlex for title: {title}")
                return self._select_best_paper_by_similarity(title, search_results)
        except Exception as e:
            self.logger.warning(f"Error searching OpenAlex for '{title}': {e}")
        self.logger.warning(f"No papers found through OpenAlex for title: {title}")
        return None

    def get_paper_with_title_arxiv(self, title: str):
        """通过ArXiv API根据title搜索paper"""
        self.logger.info(f"Searching for paper with title: {title}")
        
        try:
            search_results = self.arxiv_api.search_papers_by_title(title)
            if search_results:
                self.logger.info(f"Found {len(search_results)} papers from arXiv for title: {title}")
                return self._select_best_paper_by_similarity(title, search_results)
        except Exception as e:
            self.logger.warning(f"Error searching arXiv for '{title}': {e}")
        
        self.logger.warning(f"No papers found for title: {title}")
        return None

    def get_paper_with_title(self, title: str):
        """Search OpenAlex first, then use Semantic Scholar and arXiv as fallbacks."""
        normalized = title.strip().lower()
        if normalized in self.title_lookup_cache:
            cached = self.title_lookup_cache[normalized]
            self.logger.info(f"Cache hit for title: {title[:50]}...")
            if cached["found"]:
                return cached["paper_info"]
            
        result = self.get_paper_with_title_openalex(title)
        if result:
            result["api_platform"] = "openalex"
        if not result:
            self.logger.info("OpenAlex did not resolve the title; trying Semantic Scholar.")
            result = self.get_paper_with_title_semantic(title)
            if result:
                result["api_platform"] = "semantic"
        if not result:
            self.logger.info("Semantic Scholar did not resolve the title; trying arXiv.")
            result = self.get_paper_with_title_arxiv(title)
            if result:
                result["api_platform"] = "arxiv"

        if result:
            self.title_lookup_cache[normalized] = {"found": True, "paper_info": result}
        return result

    def get_paper_with_title_batch(self, titles: List[str]):
        """
        批量根据title搜索paper，优先使用Semantic Scholar，失败则用ArXiv
        统一计算embedding和相似度，显著提升性能
        
        使用 title_lookup_cache 缓存查询结果，避免重复API调用。
        缓存格式：title (lowercase, stripped) -> {"found": bool, "paper_info": dict or None}
        
        Args:
            titles: 论文标题列表
            
        Returns:
            Dict[str, dict]: title -> paper_info 的映射，未找到的title对应None
        """
        if not titles:
            return {}
        
        self.logger.info(f"Batch searching for {len(titles)} papers...")
        
        # Normalize titles for cache lookup
        normalized_titles = {title: title.strip().lower() for title in titles}
        
        # Separate titles into cache hits and misses
        titles_to_query = []
        results = {}
        cache_misses = []
        
        for title in titles:
            normalized = normalized_titles[title]
            if normalized in self.title_lookup_cache:
                cached = self.title_lookup_cache[normalized]
                self.logger.info(f"Cache hit for title: {title[:50]}...")
                if cached["found"]:
                    results[title] = cached["paper_info"]
                # else:
                #     results[title] = None
            else:
                titles_to_query.append(title)
                cache_misses.append(normalized)
        
        self.logger.info(f"Cache hits: {len(titles) - len(titles_to_query)}, Cache misses: {len(titles_to_query)}")
        
        if not titles_to_query:
            return results
        
        # OpenAlex is the primary discovery provider. Semantic Scholar is only
        # queried for titles that OpenAlex did not resolve.
        openalex_results = {}  # title -> list of search results
        for title in titles_to_query:
            try:
                openalex_results[title] = self.openalex_api.search_papers(title, per_page=5)[:5]
            except Exception as e:
                self.logger.warning(f"Error searching OpenAlex for '{title}': {e}")
                openalex_results[title] = []

        semantic_results = {}  # title -> list of search results
        for title in titles_to_query:
            if openalex_results.get(title):
                semantic_results[title] = []
                continue
            try:
                fields = "title,externalIds,openAccessPdf,abstract,authors,year,venue"
                response = self.semantic_scholar_api.search_papers(query=title, fields=fields)
                if response and response.get("data"):
                    semantic_results[title] = response["data"][:5]
                else:
                    semantic_results[title] = []
            except Exception as e:
                self.logger.warning(f"Error searching Semantic Scholar for '{title}': {e}")
                semantic_results[title] = []
        
        # 批量搜索ArXiv作为fallback
        arxiv_results = {}  # title -> list of search results

        for title in titles_to_query:
            if openalex_results.get(title) or semantic_results.get(title):
                arxiv_results[title] = []
                continue
            try:
                search_results = self.arxiv_api.search_papers_by_title(title)
                arxiv_results[title] = search_results[:3] if search_results else []
            except Exception as e:
                self.logger.warning(f"Error searching arXiv for '{title}': {e}")
                arxiv_results[title] = []
        
        # 批量计算embedding和相似度
        model = self._get_embedding_model()
        
        # 收集所有需要计算相似度的title
        all_titles_to_encode = []
        title_to_results = {}  # query_title -> [(paper_info, source), ...]
        
        for title in titles_to_query:
            title_to_results[title] = []

            for paper in openalex_results.get(title, [])[:3]:
                title_to_results[title].append((paper, "openalex"))

            for paper in semantic_results.get(title, [])[:3]:
                title_to_results[title].append((paper, "semantic"))

            for paper in arxiv_results.get(title, [])[:2]:
                title_to_results[title].append((paper, "arxiv"))
            
            # 收集所有需要encode的title
            all_titles_to_encode.append(title)
            for paper, _ in title_to_results[title]:
                all_titles_to_encode.append(paper.get("title", ""))
        
        # 批量编码所有title
        self.logger.info(f"Batch encoding {len(all_titles_to_encode)} titles...")
        all_embeddings = model.encode(
            all_titles_to_encode,
            convert_to_tensor=True,
            batch_size=32,
            show_progress_bar=True
        )
        
        # 解析embeddings
        embeddings_dict = {}
        idx = 0
        for title in all_titles_to_encode:
            embeddings_dict[title] = all_embeddings[idx]
            idx += 1
        
        # 批量计算相似度并选择最佳匹配，同时更新缓存
        for title in titles_to_query:
            normalized = normalized_titles[title]
            query_embedding = embeddings_dict[title]
            best_paper = None
            best_similarity = 0.0
            best_source = None
            
            for paper, source in title_to_results[title]:
                paper_title = paper.get("title", "")
                if not paper_title or paper_title not in embeddings_dict:
                    continue
                
                paper_embedding = embeddings_dict[paper_title]
                similarity = util.pytorch_cos_sim(query_embedding, paper_embedding).item()
                
                if similarity > best_similarity:
                    best_similarity = similarity
                    best_paper = paper
                    best_source = source
                
                if similarity > 0.95:
                    self.logger.info(f"Paper: {paper_title[:50]}... Similarity: {similarity:.4f}")
                
                if similarity == 1.0:
                    break
            
            if best_paper and best_similarity > 0.95:
                self.logger.info(f"Found matching paper for '{title}' with similarity {best_similarity:.4f}: {best_paper.get('title', 'N/A')}")
                best_paper["api_platform"] = best_source
                results[title] = best_paper
                # Cache the found result
                self.title_lookup_cache[normalized] = {"found": True, "paper_info": best_paper}
            else:
                self.logger.warning(f"No paper found with similarity > 0.95 for title: {title}")
                results[title] = None
                # Cache the "not found" result to avoid repeated lookups
                # self.title_lookup_cache[normalized] = {"found": False, "paper_info": None}
        
        return results

    def _select_best_paper_by_similarity(self, query_title: str, search_results: List[dict]):
        """根据embedding相似度选择最佳匹配的paper"""
        model = self._get_embedding_model()
        query_embedding = model.encode(query_title, convert_to_tensor=True)
        
        best_paper = None
        best_similarity = 0.0
        
        for paper in search_results[:3]:
            paper_title = paper.get("title", "")
            if not paper_title:
                continue
            
            paper_embedding = model.encode(paper_title, convert_to_tensor=True)
            similarity = util.pytorch_cos_sim(query_embedding, paper_embedding).item()
            self.logger.info(f"Paper: {paper_title[:50]}... Similarity: {similarity:.4f}")

            if similarity > 0.95 and similarity > best_similarity:
                best_similarity = similarity
                best_paper = paper
            if similarity == 1.0:
                best_paper = paper
                break
        
        if best_paper:
            self.logger.info(f"Found matching paper with similarity {best_similarity:.4f}: {best_paper.get('title', 'N/A')}")
            return best_paper
        else:
            self.logger.warning(f"No paper found with similarity > 0.95 for title: {query_title}")
            return None

    def _get_reference_graph(self):
        """获取reference graph（如果存在）"""
        import pickle
        ref_graph_path = os.path.join(self.cache_path, "reference_graph.pkl")
        if os.path.exists(ref_graph_path):
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
                graph_metadata.get("provider") == "openalex"
                and graph_metadata.get("schema_version") == expected_schema
            ):
                return reference_graph
        return None

    def clear_title_lookup_cache(self):
        """清除title lookup缓存"""
        self.title_lookup_cache.clear()
        self.logger.info("Title lookup cache cleared.")
        
    def get_title_lookup_cache_stats(self):
        """获取title lookup缓存的统计信息"""
        return {
            "size": len(self.title_lookup_cache),
            "cache_path": os.path.join(self.cache_path, "title_lookup_cache")
        }
