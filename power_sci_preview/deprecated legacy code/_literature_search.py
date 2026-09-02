from __future__ import annotations

from copy import deepcopy
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from html.parser import HTMLParser
from io import BytesIO
from pathlib import Path
from threading import BoundedSemaphore, Lock
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, quote, urlencode, urljoin, urlsplit
from urllib.request import Request, urlopen
import ast
import hashlib
import json
import re
import ssl
import time
import xml.etree.ElementTree as ET

try:
    from .config import (
        SCIENCE_ARXIV_CIRCUIT_SECONDS,
        SCIENCE_ARXIV_MIN_INTERVAL_SECONDS,
        SCIENCE_DIR,
        SCIENCE_FOUNDATION_MAX_RESULTS,
        SCIENCE_FOUNDATION_MAX_SELECTED_PER_SUBHYPOTHESIS,
        SCIENCE_FOUNDATION_PAGINATION_ENABLED,
        SCIENCE_FOUNDATION_RETRY_LIMIT,
        FULLTEXT_PARSE_WORKERS,
        FULLTEXT_PER_HOST_LIMIT,
        SCIENCE_INSECURE_SSL,
        SCIENCE_DEEP_ALIGNMENT_CANDIDATE_LIMIT_MAX,
        SCIENCE_MILESTONE_PAPER_YEAR_MAX,
        SCIENCE_MILESTONE_PAPER_YEAR_MIN,
        SCIENCE_L2_TOP_LATEST_YEAR_MIN,
        SCIENCE_MAX_METADATA_RESULTS_PER_EVIDENCE_PATH,
        SCIENCE_MAX_METADATA_RESULTS_PER_SH,
        SCIENCE_MAX_REVIEW_FULLTEXT_PER_RETRIEVAL,
        SCIENCE_ACADEMIC_MCP_OA_CORE_ENABLED,
        SCIENCE_ACADEMIC_MCP_OA_HARD_DISABLED,
        SCIENCE_OPENALEX_FOUNDATION_MAX_RESULTS,
        SCIENCE_OPENALEX_L2_TOP_LATEST_MAX_RESULTS,
        SCIENCE_OPENALEX_VENUE_ENRICHMENT_PER_SEARCH,
        SCIENCE_PUBMED_SPECIALIZED_SEARCH_ENABLED,
        SCIENCE_PROVIDER_PAGE_SIZE_PUBMED,
        SCIENCE_PROVIDER_PAGE_SIZE_SEMANTIC_SCHOLAR,
        SCIENCE_REGULAR_PAPER_YEAR_MAX,
        SCIENCE_REGULAR_PAPER_YEAR_MIN,
        SCIENCE_SEMANTIC_SCHOLAR_429_BACKOFF_SECONDS,
        SCIENCE_SEMANTIC_SCHOLAR_CACHE_TTL_SECONDS,
        SCIENCE_SEMANTIC_SCHOLAR_429_FIRST_COOLDOWN_SECONDS,
        SCIENCE_SEMANTIC_SCHOLAR_429_MAX_COOLDOWN_SECONDS,
        SCIENCE_SEMANTIC_SCHOLAR_CIRCUIT_SECONDS,
        SCIENCE_SEMANTIC_SCHOLAR_FAIL_FAST_ON_429,
        SCIENCE_SEMANTIC_SCHOLAR_GRAPH_FAIL_FAST_ON_429,
        SCIENCE_SEMANTIC_SCHOLAR_GRAPH_MAX_WAIT_SECONDS,
        SCIENCE_SEMANTIC_SCHOLAR_GRAPH_WAIT_ON_429,
        SCIENCE_SEMANTIC_SCHOLAR_MIN_INTERVAL_SECONDS,
        SCIENCE_SEMANTIC_SCHOLAR_RETRY_LIMIT,
        SCIENCE_SEMANTIC_SCHOLAR_SEARCH_RETRY_LIMIT,
        SCIENCE_SEMANTIC_SCHOLAR_RUN_REQUEST_LIMIT,
        SCIENCE_SEMANTIC_SCHOLAR_GRAPH_REQUEST_LIMIT,
        SCIENCE_SEMANTIC_SCHOLAR_SUCCESS_RESET_THRESHOLD,
        SCIENCE_SCIENCEDIRECT_ENABLED,
        SCIENCE_PREPRINT_ZERO_RESULT_TTL_SECONDS,
        SCIENCE_PREPRINT_ZERO_MATCH_EARLY_STOP_PAGES,
        SCIENCE_SUBHYPOTHESIS_AUXILIARY_PRE_FULLTEXT_LIMIT,
        SCIENCE_SUBHYPOTHESIS_AUXILIARY_PRE_FULLTEXT_LAYER_LIMIT_ENABLED,
        SCIENCE_STRATIFIED_MAX_BRANCHES_PER_LAYER,
        SCIENCE_STRATIFIED_SINGLE_PAPER_INTERVAL_SECONDS,
        SCIENCE_UNPAYWALL_EMAIL,
        CORE_API_KEY,
        SEMANTIC_SCHOLAR_API_KEY,
        SEMANTIC_SCHOLAR_RATE_SCOPE,
    )
    from .log import log_event
    from ._models import filter_literature_providers_for_research_domain
    from ._utils import normalize_space
except ImportError:
    from config import (
        SCIENCE_ARXIV_CIRCUIT_SECONDS,
        SCIENCE_ARXIV_MIN_INTERVAL_SECONDS,
        SCIENCE_DIR,
        SCIENCE_FOUNDATION_MAX_RESULTS,
        SCIENCE_FOUNDATION_MAX_SELECTED_PER_SUBHYPOTHESIS,
        SCIENCE_FOUNDATION_PAGINATION_ENABLED,
        SCIENCE_FOUNDATION_RETRY_LIMIT,
        FULLTEXT_PARSE_WORKERS,
        FULLTEXT_PER_HOST_LIMIT,
        SCIENCE_INSECURE_SSL,
        SCIENCE_DEEP_ALIGNMENT_CANDIDATE_LIMIT_MAX,
        SCIENCE_MILESTONE_PAPER_YEAR_MAX,
        SCIENCE_MILESTONE_PAPER_YEAR_MIN,
        SCIENCE_L2_TOP_LATEST_YEAR_MIN,
        SCIENCE_MAX_METADATA_RESULTS_PER_EVIDENCE_PATH,
        SCIENCE_MAX_METADATA_RESULTS_PER_SH,
        SCIENCE_MAX_REVIEW_FULLTEXT_PER_RETRIEVAL,
        SCIENCE_ACADEMIC_MCP_OA_CORE_ENABLED,
        SCIENCE_ACADEMIC_MCP_OA_HARD_DISABLED,
        SCIENCE_OPENALEX_FOUNDATION_MAX_RESULTS,
        SCIENCE_OPENALEX_L2_TOP_LATEST_MAX_RESULTS,
        SCIENCE_OPENALEX_VENUE_ENRICHMENT_PER_SEARCH,
        SCIENCE_PUBMED_SPECIALIZED_SEARCH_ENABLED,
        SCIENCE_PROVIDER_PAGE_SIZE_PUBMED,
        SCIENCE_PROVIDER_PAGE_SIZE_SEMANTIC_SCHOLAR,
        SCIENCE_REGULAR_PAPER_YEAR_MAX,
        SCIENCE_REGULAR_PAPER_YEAR_MIN,
        SCIENCE_SEMANTIC_SCHOLAR_429_BACKOFF_SECONDS,
        SCIENCE_SEMANTIC_SCHOLAR_CACHE_TTL_SECONDS,
        SCIENCE_SEMANTIC_SCHOLAR_429_FIRST_COOLDOWN_SECONDS,
        SCIENCE_SEMANTIC_SCHOLAR_429_MAX_COOLDOWN_SECONDS,
        SCIENCE_SEMANTIC_SCHOLAR_CIRCUIT_SECONDS,
        SCIENCE_SEMANTIC_SCHOLAR_FAIL_FAST_ON_429,
        SCIENCE_SEMANTIC_SCHOLAR_GRAPH_FAIL_FAST_ON_429,
        SCIENCE_SEMANTIC_SCHOLAR_GRAPH_MAX_WAIT_SECONDS,
        SCIENCE_SEMANTIC_SCHOLAR_GRAPH_WAIT_ON_429,
        SCIENCE_SEMANTIC_SCHOLAR_MIN_INTERVAL_SECONDS,
        SCIENCE_SEMANTIC_SCHOLAR_RETRY_LIMIT,
        SCIENCE_SEMANTIC_SCHOLAR_SEARCH_RETRY_LIMIT,
        SCIENCE_SEMANTIC_SCHOLAR_RUN_REQUEST_LIMIT,
        SCIENCE_SEMANTIC_SCHOLAR_GRAPH_REQUEST_LIMIT,
        SCIENCE_SEMANTIC_SCHOLAR_SUCCESS_RESET_THRESHOLD,
        SCIENCE_SCIENCEDIRECT_ENABLED,
        SCIENCE_PREPRINT_ZERO_RESULT_TTL_SECONDS,
        SCIENCE_PREPRINT_ZERO_MATCH_EARLY_STOP_PAGES,
        SCIENCE_SUBHYPOTHESIS_AUXILIARY_PRE_FULLTEXT_LIMIT,
        SCIENCE_SUBHYPOTHESIS_AUXILIARY_PRE_FULLTEXT_LAYER_LIMIT_ENABLED,
        SCIENCE_STRATIFIED_MAX_BRANCHES_PER_LAYER,
        SCIENCE_STRATIFIED_SINGLE_PAPER_INTERVAL_SECONDS,
        SCIENCE_UNPAYWALL_EMAIL,
        CORE_API_KEY,
        SEMANTIC_SCHOLAR_API_KEY,
        SEMANTIC_SCHOLAR_RATE_SCOPE,
    )
    from log import log_event
    from _models import filter_literature_providers_for_research_domain
    from _utils import normalize_space



SEMANTIC_SCHOLAR_LAST_REQUEST_AT = 0.0

SEMANTIC_SCHOLAR_COOLDOWN_UNTIL = 0.0

SEMANTIC_SCHOLAR_429_COUNT = 0

SEMANTIC_SCHOLAR_CONSECUTIVE_429_COUNT = 0

SEMANTIC_SCHOLAR_KEY_STATUS_LOGGED = False

SEMANTIC_SCHOLAR_RESPONSE_CACHE: dict[str, tuple[float, str]] = {}

PROVIDER_CIRCUIT_SKIP_COUNTS: dict[tuple[str, str], int] = {}

PROVIDER_CIRCUIT_LAST_LOGGED_AT: dict[tuple[str, str], float] = {}

ALIGNMENT_ADMISSION_MEMO: dict[str, dict[str, Any]] = {}

COARSE_PREFILTER_MEMO: dict[str, dict[str, Any]] = {}

ALIGNMENT_ADMISSION_MEMO_LOCK = Lock()

COARSE_PREFILTER_MEMO_LOCK = Lock()

ALIGNMENT_ADMISSION_MEMO_MAX = 20000

COARSE_PREFILTER_MEMO_MAX = 20000

ARXIV_LAST_REQUEST_AT = 0.0

FULLTEXT_HOST_SEMAPHORES: dict[str, BoundedSemaphore] = {}
FULLTEXT_HOST_SEMAPHORES_LOCK = Lock()
FULLTEXT_PARSE_SEMAPHORE = BoundedSemaphore(FULLTEXT_PARSE_WORKERS)


def _log_provider_circuit_active_compact(
    *,
    provider: str,
    reason: str,
    retry_after_seconds: float = 0.0,
    traffic_class: str = "",
) -> None:
    """Log provider circuit skips as compact run noise, not per-candidate errors.

    Optional metadata/detail probes are allowed to disappear behind an active
    provider circuit.  Emitting a full failure event for every candidate was
    both slow and misleading; this helper records a visible summary on the
    first skip and then every 25 skipped probes or 60 seconds.
    """

    normalized_provider = str(provider or "unknown").strip().lower() or "unknown"
    normalized_reason = str(reason or "circuit_active").strip() or "circuit_active"
    key = (normalized_provider, normalized_reason)
    count = int(PROVIDER_CIRCUIT_SKIP_COUNTS.get(key) or 0) + 1
    PROVIDER_CIRCUIT_SKIP_COUNTS[key] = count
    now = time.monotonic()
    last_logged = float(PROVIDER_CIRCUIT_LAST_LOGGED_AT.get(key) or 0.0)
    if count == 1 or count % 25 == 0 or now - last_logged >= 60.0:
        PROVIDER_CIRCUIT_LAST_LOGGED_AT[key] = now
        log_event(
            "SCIENCE",
            "provider_circuit_active",
            provider=normalized_provider,
            reason=normalized_reason,
            skipped_requests=count,
            retry_after_seconds=round(max(0.0, float(retry_after_seconds or 0.0)), 2),
            traffic_class=str(traffic_class or "optional_detail_probe"),
        )


def _semantic_scholar_optional_probe_skip_decision(
    *,
    fast_fail: bool,
) -> tuple[bool, str, float]:
    """Return whether optional Semantic Scholar detail work should be skipped."""

    recent_suppression = semantic_scholar_recent_429_suppression_status()
    if bool(recent_suppression.get("suppressed")):
        return (
            True,
            str(recent_suppression.get("reason") or "recent_429_suppression_active"),
            float(recent_suppression.get("remaining_seconds") or 0.0),
        )
    circuit_open, retry_after = semantic_scholar_circuit_open()
    if circuit_open and (fast_fail or SCIENCE_SEMANTIC_SCHOLAR_FAIL_FAST_ON_429):
        return True, "active_circuit_open", float(retry_after or 0.0)
    return False, "", 0.0


def _literature_provider_disabled_reason(provider: str) -> str:
    """Return a runtime policy reason when a registered provider is disabled."""

    normalized = str(provider or "").strip().lower()
    if normalized == "pubmed" and not SCIENCE_PUBMED_SPECIALIZED_SEARCH_ENABLED:
        return (
            "SCIENCE_PUBMED_SPECIALIZED_SEARCH_ENABLED is off; PubMed specialized retrieval "
            "is disabled because OpenAlex is the broad discovery source and PubMed keyword "
            "indexing can contaminate non-biomedical sub-hypothesis retrieval."
        )
    if normalized == "sciencedirect" and not SCIENCE_SCIENCEDIRECT_ENABLED:
        return "SCIENCE_SCIENCEDIRECT_ENABLED is off; ScienceDirect is disabled by default to avoid unauthorized/noisy provider traffic."
    return ""


def _filter_runtime_enabled_literature_providers(
    providers: list[str],
    *,
    requested_providers: list[str] | None = None,
    context: str = "",
) -> list[str]:
    """Drop providers disabled by runtime policy while logging the decision."""

    retained: list[str] = []
    disabled: list[dict[str, str]] = []
    seen: set[str] = set()
    for provider in providers:
        normalized = str(provider or "").strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        reason = _literature_provider_disabled_reason(normalized)
        if reason:
            disabled.append({"provider": normalized, "reason": reason})
            continue
        retained.append(normalized)
    if disabled:
        log_event(
            "SCIENCE",
            "literature_providers_disabled_by_policy",
            context=context,
            disabled=disabled,
            requested_providers=list(requested_providers or []),
            retained=retained,
            blocking=False,
        )
    return retained


def _fulltext_host_semaphore(url: str) -> BoundedSemaphore:
    host = str(urlsplit(str(url or "")).hostname or "unknown").lower()
    with FULLTEXT_HOST_SEMAPHORES_LOCK:
        semaphore = FULLTEXT_HOST_SEMAPHORES.get(host)
        if semaphore is None:
            semaphore = BoundedSemaphore(FULLTEXT_PER_HOST_LIMIT)
            FULLTEXT_HOST_SEMAPHORES[host] = semaphore
        return semaphore


@contextmanager
def fulltext_host_slot(url: str):
    """Bound concurrent OA landing-page/PDF traffic independently per host."""

    semaphore = _fulltext_host_semaphore(url)
    semaphore.acquire()
    try:
        yield
    finally:
        semaphore.release()

ARXIV_COOLDOWN_UNTIL = 0.0

ARXIV_429_COUNT = 0

ARXIV_TIMEOUT_COUNT = 0
PREPRINT_API_PAGE_SIZE = 30
PREPRINT_API_MAX_SCAN_RECORDS = 600
MAX_CONTROLLED_L4_BACKFILL = 3
PREPRINT_ZERO_RESULT_CACHE: dict[tuple[str, str, str, str], tuple[float, dict[str, Any]]] = {}
PREPRINT_ZERO_RESULT_CACHE_LOCK = Lock()
STRATIFIED_SINGLE_PAPER_LAST_COMPLETED_AT = 0.0
STRATIFIED_SINGLE_PAPER_LOCK = Lock()
SEMANTIC_SCHOLAR_RUN_BUDGET_LOCK = Lock()


@dataclass
class SemanticScholarRetryBudget:
    """A retry budget shared by every HTTP request in one provider batch job."""

    limit: int
    job_id: str = ""
    retries_used: int = 0
    request_kind: str = ""
    max_rate_limit_responses: int = 0
    rate_limit_responses: int = 0

    @property
    def remaining(self) -> int:
        return max(0, int(self.limit) - int(self.retries_used))


@dataclass
class SemanticScholarRunBudget:
    """One process-level research-run budget with low-priority graph isolation."""

    run_id: str
    total_limit: int
    graph_limit: int
    total_used: int = 0
    search_used: int = 0
    detail_used: int = 0
    graph_used: int = 0
    graph_suspended: bool = False
    graph_suspend_reason: str = ""

    def snapshot(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "total_limit": self.total_limit,
            "graph_limit": self.graph_limit,
            "total_used": self.total_used,
            "search_used": self.search_used,
            "detail_used": self.detail_used,
            "graph_used": self.graph_used,
            "remaining": max(0, self.total_limit - self.total_used),
            "graph_remaining": max(0, self.graph_limit - self.graph_used),
            "graph_suspended": self.graph_suspended,
            "graph_suspend_reason": self.graph_suspend_reason,
        }


SEMANTIC_SCHOLAR_RUN_BUDGET: SemanticScholarRunBudget | None = None


def start_semantic_scholar_run_budget(run_id: str = "") -> dict[str, Any]:
    global SEMANTIC_SCHOLAR_RUN_BUDGET
    with SEMANTIC_SCHOLAR_RUN_BUDGET_LOCK:
        SEMANTIC_SCHOLAR_RUN_BUDGET = SemanticScholarRunBudget(
            run_id=str(run_id or f"science_run_{int(time.time())}"),
            total_limit=max(1, int(SCIENCE_SEMANTIC_SCHOLAR_RUN_REQUEST_LIMIT)),
            graph_limit=min(
                max(1, int(SCIENCE_SEMANTIC_SCHOLAR_GRAPH_REQUEST_LIMIT)),
                max(1, int(SCIENCE_SEMANTIC_SCHOLAR_RUN_REQUEST_LIMIT)),
            ),
        )
        snapshot = SEMANTIC_SCHOLAR_RUN_BUDGET.snapshot()
    log_event("SCIENCE", "semantic_scholar_run_budget_started", **snapshot)
    return snapshot


def semantic_scholar_run_budget_status() -> dict[str, Any]:
    with SEMANTIC_SCHOLAR_RUN_BUDGET_LOCK:
        budget = SEMANTIC_SCHOLAR_RUN_BUDGET
        return budget.snapshot() if budget is not None else {"active": False}


def suspend_semantic_scholar_graph_traffic(reason: str) -> dict[str, Any]:
    with SEMANTIC_SCHOLAR_RUN_BUDGET_LOCK:
        budget = SEMANTIC_SCHOLAR_RUN_BUDGET
        if budget is None:
            return {"active": False, "graph_suspended": True, "graph_suspend_reason": reason}
        budget.graph_suspended = True
        budget.graph_suspend_reason = str(reason or "graph traffic suspended")[:240]
        snapshot = budget.snapshot()
    log_event("SCIENCE", "semantic_scholar_graph_traffic_suspended", **snapshot)
    return snapshot


def reserve_semantic_scholar_run_request(traffic_class: str) -> dict[str, Any]:
    selected = str(traffic_class or "detail").strip().lower()
    if selected not in {"search", "detail", "graph"}:
        selected = "detail"
    with SEMANTIC_SCHOLAR_RUN_BUDGET_LOCK:
        budget = SEMANTIC_SCHOLAR_RUN_BUDGET
        if budget is None:
            return {"active": False, "traffic_class": selected}
        if budget.total_used >= budget.total_limit:
            raise RuntimeError(
                f"semantic_scholar_run_budget_exhausted: total={budget.total_used}/{budget.total_limit}"
            )
        if selected == "graph":
            if budget.graph_suspended:
                raise RuntimeError(
                    f"semantic_scholar_graph_suspended: {budget.graph_suspend_reason or 'rate limited'}"
                )
            if budget.graph_used >= budget.graph_limit:
                budget.graph_suspended = True
                budget.graph_suspend_reason = "run graph request budget exhausted"
                raise RuntimeError(
                    f"semantic_scholar_graph_budget_exhausted: graph={budget.graph_used}/{budget.graph_limit}"
                )
        budget.total_used += 1
        if selected == "graph":
            budget.graph_used += 1
        elif selected == "search":
            budget.search_used += 1
        else:
            budget.detail_used += 1
        snapshot = budget.snapshot()
    return {**snapshot, "traffic_class": selected}


def semantic_scholar_graph_traffic_suspension_error() -> str:
    """Return a local graph-stop reason without treating it as HTTP 429.

    The run-level graph circuit is deliberately lower priority than literature
    search.  It is suspended only after the run-level graph request budget is
    exhausted; a per-subhypothesis 429 ceiling must not set this state.
    """
    status = semantic_scholar_run_budget_status()
    if not bool(status.get("graph_suspended")):
        return ""
    reason = str(status.get("graph_suspend_reason") or "graph traffic suspended")
    return f"semantic_scholar_graph_suspended: {reason}"

_CJK_QUERY_PATTERN = re.compile(r"[\u3400-\u9fff\uf900-\ufaff]")
_ENGLISH_QUERY_CACHE: dict[tuple[str, str], dict[str, str]] = {}

_SCIENTIFIC_QUERY_TRANSLATIONS = {
    "药物代谢酶活性": "drug metabolizing enzyme activity",
    "药代动力学参数": "pharmacokinetic parameters",
    "药物代谢酶": "drug metabolizing enzyme",
    "遗传变异": "genetic variation",
    "药物基因组学": "pharmacogenomics",
    "个体化医疗": "personalized medicine",
    "精准医疗": "precision medicine",
    "剂量反应": "dose response",
    "不良反应": "adverse drug reaction",
    "临床疗效": "clinical efficacy",
    "肿瘤分子分型": "tumor molecular profiling",
    "免疫治疗": "immunotherapy",
    "细胞治疗": "cell therapy",
    "基因治疗": "gene therapy",
    "生物标志物": "biomarker",
    "电极材料": "electrode material",
    "电解液": "electrolyte",
    "离子迁移": "ion transport",
    "循环寿命": "cycle life",
    "容量衰减": "capacity degradation",
    "阳离子混排": "cation mixing",
    "氧气析出": "oxygen evolution",
    "固态电解质": "solid electrolyte",
    "界面阻抗": "interfacial impedance",
}


def contains_cjk_query_text(value: str) -> bool:
    return bool(_CJK_QUERY_PATTERN.search(str(value or "")))


def is_english_provider_query(value: str) -> bool:
    text = normalize_space(str(value or ""))
    return bool(text and not contains_cjk_query_text(text) and re.search(r"[A-Za-z]{2,}", text))


def heuristic_english_scientific_query(query: str) -> str:
    translated = str(query or "")
    for chinese, english in sorted(_SCIENTIFIC_QUERY_TRANSLATIONS.items(), key=lambda item: len(item[0]), reverse=True):
        translated = translated.replace(chinese, english)
    if contains_cjk_query_text(translated):
        return ""
    translated = re.sub(r"\b(?:AND|OR|NOT)\b", " ", translated, flags=re.IGNORECASE)
    translated = re.sub(r"[^A-Za-z0-9+_.\-/ ]+", " ", translated)
    return normalize_space(translated)


def english_provider_query(query: str, domain: str = "", *, allow_llm: bool = True) -> dict[str, str]:
    source_query = normalize_space(str(query or ""))
    source_domain = normalize_space(str(domain or ""))
    if is_english_provider_query(source_query):
        return {
            "query": source_query,
            "source_query": source_query,
            "translation_method": "already_english",
        }
    cache_key = (source_query, source_domain)
    cached = _ENGLISH_QUERY_CACHE.get(cache_key)
    if cached:
        return dict(cached)

    translated = heuristic_english_scientific_query(source_query)
    method = "glossary"
    if not is_english_provider_query(translated) and allow_llm:
        try:
            try:
                from ._llm import translate_scientific_query_to_english
            except ImportError:
                from _llm import translate_scientific_query_to_english
            translated = translate_scientific_query_to_english(source_query, domain=source_domain)
            method = "llm_translation"
        except Exception as exc:
            log_event("WARN", "scientific_query_translation_failed", query=source_query[:160], error=str(exc)[:200])

    if not is_english_provider_query(translated):
        translated = heuristic_english_scientific_query(source_domain)
        method = "english_domain_fallback"
    result = {
        "query": translated if is_english_provider_query(translated) else "",
        "source_query": source_query,
        "translation_method": method if is_english_provider_query(translated) else "unresolved",
    }
    _ENGLISH_QUERY_CACHE[cache_key] = dict(result)
    return result


def require_english_provider_query(query: str, provider: str, domain: str = "") -> tuple[str, dict[str, str] | None]:
    resolution = english_provider_query(query, domain=domain)
    resolved = resolution.get("query", "")
    if resolved:
        return resolved, None
    return "", {
        "provider": provider,
        "query": str(query or ""),
        "status": "query_language_error",
        "results": [],
        "warning": "External literature providers require an English retrieval query. Translation could not derive a safe English query.",
        "next_step": "Provide English scientific keywords or rerun with a configured science LLM so the query can be translated before retrieval.",
    }


def normalize_english_query_plan(
    query_plan: list[dict[str, Any]],
    *,
    domain: str = "",
    allow_llm: bool = True,
) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for item in query_plan:
        if not isinstance(item, dict):
            continue
        source_query = str(item.get("query") or "").strip()
        if not source_query:
            continue
        resolution = english_provider_query(source_query, domain=domain, allow_llm=allow_llm)
        if not resolution.get("query"):
            log_event("WARN", "provider_query_skipped_non_english", query=source_query[:160])
            continue
        prepared = dict(item)
        prepared["query"] = resolution["query"]
        if resolution["query"] != resolution["source_query"]:
            prepared["source_query"] = resolution["source_query"]
            prepared["query_language"] = resolution
        normalized.append(prepared)
    return normalized


def query_execution_fingerprint(query: Any) -> str:
    """Stable lexical fingerprint for plan-to-provider execution auditing."""

    normalized = normalize_space(str(query or "").lower())
    normalized = re.sub(r"\s*([()])\s*", r"\1", normalized)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:20] if normalized else ""


def _query_execution_content_tokens(query: Any) -> set[str]:
    """Compare semantic anchor tokens across provider query lowerings."""

    text = str(query or "").lower()
    text = re.sub(r"\[[^\]]*\]", " ", text)
    tokens = set(re.findall(r"[a-z][a-z0-9+_-]*", text))
    return {
        token for token in tokens
        if token not in {
            "and", "or", "not", "title", "abstract", "all", "search",
            "filter", "publication", "type", "systematic", "sb",
            # Providers commonly compile phrase-oriented plans into keyword
            # queries. These connectors do not identify a scientific object.
            "a", "an", "the", "of", "with",
        }
    }


def _normalize_retrieval_anchor_contract(
    value: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Normalize the current typed V3 retrieval anchor contract.

    The V3 contract carries named semantic groups.  No causal edge is inferred
    here: every accepted form must already have been emitted by the current
    research-question contract.
    """

    contract = dict(value) if isinstance(value, Mapping) else {}
    if str(contract.get("schema_version") or "") != "retrieval_anchor_contract_v3":
        return contract
    raw_groups = contract.get("required_anchor_groups")
    groups: list[dict[str, Any]] = []
    seen: set[tuple[str, tuple[str, ...]]] = set()
    if isinstance(raw_groups, (list, tuple, set)):
        for raw_group in raw_groups:
            if not isinstance(raw_group, Mapping):
                continue
            group_id = normalize_space(str(raw_group.get("group_id") or ""))
            raw_forms = raw_group.get("accepted_forms")
            if not group_id or not isinstance(raw_forms, (list, tuple, set)):
                continue
            normalized = [
                normalize_space(str(item))
                for item in raw_forms
                if normalize_space(str(item))
            ]
            key = (group_id.casefold(), tuple(item.casefold() for item in normalized))
            if normalized and key not in seen:
                seen.add(key)
                groups.append({
                    "group_id": group_id,
                    "accepted_forms": normalized[:12],
                    "required": bool(raw_group.get("required", True)),
                    "match_policy": str(
                        raw_group.get("match_policy")
                        or "provider_normalized_token_sequence_v1"
                    ),
                })
    contract["required_anchor_groups"] = groups
    contract["valid"] = bool(contract.get("valid")) and any(
        bool(group.get("required")) for group in groups
    )
    return contract


def retrieval_anchor_group_forms(
    anchor_contract: Mapping[str, Any] | None,
    *,
    required_only: bool = True,
) -> list[list[str]]:
    """Return the approved forms of named V2 groups for lexical consumers."""

    contract = _normalize_retrieval_anchor_contract(anchor_contract)
    if str(contract.get("schema_version") or "") != "retrieval_anchor_contract_v3":
        return []
    groups: list[list[str]] = []
    for group in contract.get("required_anchor_groups") or []:
        if not isinstance(group, Mapping):
            continue
        if required_only and group.get("required") is False:
            continue
        forms = [
            normalize_space(str(value))
            for value in (group.get("accepted_forms") or [])
            if normalize_space(str(value))
        ]
        if forms:
            groups.append(forms)
    return groups


def _strict_query_plan_required_anchor_groups(plan: Mapping[str, Any]) -> list[list[str]]:
    """Return the *branch-local* anchors that must survive provider lowering.

    Provider-query auditing must preserve the evidence role requested by this
    branch, not reconstruct the entire sub-hypothesis from every available
    object/input/mechanism/outcome field.  A paper can later contribute one
    source-bound fragment to a cross-paper bundle, so requiring every causal
    axis here creates an impossible single-paper retrieval contract.

    Query planners can declare exact branch requirements in
    ``required_anchor_groups``.  When they do not, retain only a declared
    object group as a conservative discovery anchor.  We deliberately do not
    infer mandatory mediator, outcome, comparison, or validation groups from a
    whole-hypothesis contract at this stage.
    """

    groups: list[list[str]] = []
    abstract_plan = (
        plan.get("abstract_edge_query_plan")
        if isinstance(plan.get("abstract_edge_query_plan"), Mapping)
        else {}
    )
    abstract_anchor_contract = _normalize_retrieval_anchor_contract(abstract_plan)
    for raw_group in retrieval_anchor_group_forms(abstract_anchor_contract):
        normalized = [normalize_space(str(value)) for value in raw_group if normalize_space(str(value))]
        if normalized:
            groups.append(normalized[:12])
    contract = plan.get("retrieval_anchor_contract")
    if not isinstance(contract, Mapping):
        contract = plan.get("anchor_contract") if isinstance(plan.get("anchor_contract"), Mapping) else {}
    contract = _normalize_retrieval_anchor_contract(contract)
    for raw_group in retrieval_anchor_group_forms(contract):
        normalized = [normalize_space(str(value)) for value in raw_group if normalize_space(str(value))]
        if normalized:
            groups.append(normalized[:12])
    # Older planners may not yet emit ``required_anchor_groups``.  Preserve a
    # single declared object group in that case.  Treat all values as
    # alternatives: the goal is topical continuity for discovery, not proof of
    # every component of the final claim.
    if not groups:
        for key in (
            "scientific_object_anchor_group",
            "required_object_group",
            "object_anchor_group",
            "component_anchor_group",
        ):
            raw_values = plan.get(key)
            if isinstance(raw_values, str):
                raw_values = [raw_values]
            if not isinstance(raw_values, (list, tuple, set)):
                continue
            normalized = [
                normalize_space(str(value))
                for value in raw_values
                if normalize_space(str(value))
            ]
            if normalized:
                groups.append(normalized[:12])
                break
    unique: list[list[str]] = []
    seen: set[tuple[str, ...]] = set()
    for group in groups:
        key = tuple(sorted(_query_execution_content_tokens(" ".join(group))))
        if key and key not in seen:
            seen.add(key)
            unique.append(group)
    return unique[:8]


def _strict_query_anchor_coverage(
    required_groups: list[list[str]], actual_query: str,
) -> tuple[list[list[str]], list[list[str]]]:
    actual_tokens = _query_execution_content_tokens(actual_query)
    preserved: list[list[str]] = []
    missing: list[list[str]] = []
    for group in required_groups:
        alternative_matches = False
        for phrase in group:
            phrase_tokens = _query_execution_content_tokens(phrase)
            if phrase_tokens and phrase_tokens.issubset(actual_tokens):
                alternative_matches = True
                break
        (preserved if alternative_matches else missing).append(group)
    return preserved, missing


def is_contract_lexical_calibration_plan(plan: Mapping[str, Any] | None) -> bool:
    return bool(
        isinstance(plan, Mapping)
        and (
            plan.get("lexical_calibration") is True
            or str(plan.get("evidence_path_role") or "").strip().lower()
            == "contract_lexical_calibration"
        )
    )


def audit_strict_query_plan_execution(
    plan: Mapping[str, Any],
    block: Mapping[str, Any],
) -> dict[str, Any]:
    """Require calibration dispatch to preserve every planned topical token.

    Provider syntax lowering is permitted only when it removes Boolean or
    field syntax. It cannot add a new topical term, recompile from generic
    modules, or silently substitute a base-query branch.
    """

    planned_query = normalize_space(str(plan.get("query") or ""))
    attempted = block.get("attempted_queries") if isinstance(block, Mapping) else []
    attempted = attempted if isinstance(attempted, list) else []
    actual_query = normalize_space(
        str(attempted[-1] if attempted else block.get("query") if isinstance(block, Mapping) else "")
    )
    planned_fingerprint = str(plan.get("query_fingerprint") or query_execution_fingerprint(planned_query))
    actual_fingerprint = query_execution_fingerprint(actual_query)
    provider = str(block.get("provider") or "") if isinstance(block, Mapping) else ""
    status = str(block.get("status") or "") if isinstance(block, Mapping) else ""
    compilation = (
        block.get("query_compilation")
        if isinstance(block, Mapping) and isinstance(block.get("query_compilation"), Mapping)
        else {}
    )
    transforms = [
        str(item) for item in (compilation.get("syntax_transforms") or [])
        if str(item).strip()
    ]
    planned_tokens = _query_execution_content_tokens(planned_query)
    actual_tokens = _query_execution_content_tokens(actual_query)
    unexpected_tokens = sorted(actual_tokens - planned_tokens)
    missing_tokens = sorted(planned_tokens - actual_tokens)
    required_anchor_groups = _strict_query_plan_required_anchor_groups(plan)
    preserved_anchor_groups, missing_anchor_groups = _strict_query_anchor_coverage(
        required_anchor_groups, actual_query
    )
    dispatched = bool(
        isinstance(block, Mapping)
        and block.get("submitted_to_provider") is True
        and actual_query
    )
    exact = bool(planned_fingerprint and planned_fingerprint == actual_fingerprint)
    allowed_provider_lowering = bool(
        dispatched
        and not missing_anchor_groups
        and actual_tokens
        and set(transforms).issubset({
            "normalized_whitespace",
            "openalex_boolean_expression_to_search_text",
            "openalex_search_terms_limited",
            "removed_unsupported_square_bracket_field_tags",
        })
    )
    execution_status = (
        "EXACT_FINGERPRINT"
        if exact and dispatched
        else "ALLOWED_PROVIDER_SYNTAX_TRANSFORM"
        if allowed_provider_lowering
        else "NOT_DISPATCHED"
        if not dispatched
        else "PLAN_UNEXECUTABLE"
        if missing_anchor_groups
        else "PLAN_PROVIDER_QUERY_MISMATCH"
    )
    receipt = {
        "schema_version": "provider_execution_receipt_v1",
        "branch": str(plan.get("branch") or block.get("query_branch") or ""),
        "provider": provider,
        "planned_query_fingerprint": planned_fingerprint,
        "actual_query_fingerprint": actual_fingerprint,
        "provider_status": status,
        "provider_syntax_transforms": transforms,
        "required_anchor_groups": required_anchor_groups,
        "preserved_required_anchor_groups": preserved_anchor_groups,
        "missing_required_anchor_groups": missing_anchor_groups,
        "execution_status": execution_status,
        "semantic_conformant": execution_status in {
            "EXACT_FINGERPRINT", "ALLOWED_PROVIDER_SYNTAX_TRANSFORM",
        },
        "policy": "required_anchor_groups_must_survive_provider_lowering",
    }
    audit = {
        "schema_version": "strict_query_plan_execution_audit_v2",
        "planned_query": planned_query,
        "actual_provider_query": actual_query,
        "planned_content_tokens": sorted(planned_tokens)[:32],
        "actual_content_tokens": sorted(actual_tokens)[:32],
        "unexpected_provider_tokens": unexpected_tokens[:24],
        "missing_planned_tokens": missing_tokens[:24],
        "allowed": bool(receipt["semantic_conformant"]),
        "provider_execution_receipt": receipt,
        **receipt,
    }
    return audit


_QUERY_PLAN_PROVENANCE_FIELDS = (
    "groupchat_id",
    "run_id",
    "retrieval_wave_id",
    "sub_hypothesis_id",
    "research_question_contract_id",
    "research_question_contract_hash",
    "research_question_task_id",
    "evidence_slot",
    "query_branch_id",
    "query_branch_role",
    "plan_revision",
    "query_mode",
    "query_fingerprint",
    "discovery_fingerprint",
    "evidence_kind",
    "evidence_path_role",
    "evidence_path_polarity",
    "target_lane",
    "target_layer",
    "query_family",
    "path_composition_policy",
    "panel_evidence_tier",
    "panel_component_path",
    "component_anchor_group",
    "multi_entity_panel",
    "panel_object_anchor_group",
    "preferred_retrieval_layers",
    "preprint_signal_layers",
    "retrieval_layer_role",
    "core_evidence_capable",
    "panel_core_path",
    "component_evidence_counts_as_core",
    "component_evidence_counts_as_panel_core",
    "main_retrieval_query",
    "failure_scope",
    "can_independently_falsify_sh",
    "missing_path_blocks_sh",
    "negative_evidence_interpretation",
    "query_pool",
    "candidate_budget_share",
    "target_evidence_edge_id",
    "target_evidence_edge",
    "corpus_import_eligible_after_fulltext",
    "query_pool_policy",
    "query_modules",
    "l2_query_modules",
    "query_module_compile",
    "query_boolean_expression",
    "abstract_edge_query_plan",
    "provider_compiled_plan",
    "retrieval_anchor_contract",
    "retrieval_spec_v3",
    "query_blueprint_v3",
)


def research_question_task_provenance(
    query_plan: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    """Return compact task provenance for a persisted retrieval run.

    V2.1 dispatches one provider plan for each scheduled evidence task.  Keep
    that task identity at the search-record root as well as in the query plan,
    so acquisition and forensic logs do not need to infer an SH from query
    text.  Multi-branch discovery remains representable without pretending it
    refers to one evidence slot.
    """

    entries: list[dict[str, str]] = []
    for raw_plan in query_plan or []:
        if not isinstance(raw_plan, dict):
            continue
        task_id = str(raw_plan.get("research_question_task_id") or "").strip()
        if not task_id:
            continue
        entries.append(
            {
                "groupchat_id": str(raw_plan.get("groupchat_id") or "").strip(),
                "run_id": str(raw_plan.get("run_id") or "").strip(),
                "retrieval_wave_id": str(raw_plan.get("retrieval_wave_id") or "").strip(),
                "sub_hypothesis_id": str(raw_plan.get("sub_hypothesis_id") or "").strip(),
                "research_question_contract_id": str(raw_plan.get("research_question_contract_id") or "").strip(),
                "research_question_contract_hash": str(
                    raw_plan.get("research_question_contract_hash")
                    or raw_plan.get("alignment_contract_hash")
                    or ""
                ).strip(),
                "research_question_task_id": task_id,
                "evidence_slot": str(raw_plan.get("evidence_slot") or "").strip(),
                "query_branch_id": str(
                    raw_plan.get("query_branch_id")
                    or raw_plan.get("branch")
                    or raw_plan.get("query_branch")
                    or ""
                ).strip(),
                "query_branch_role": str(raw_plan.get("query_branch_role") or "").strip(),
                "plan_revision": str(raw_plan.get("plan_revision") or "").strip(),
                "query_mode": str(raw_plan.get("query_mode") or "").strip(),
                "work_item_kind": str(
                    (raw_plan.get("retrieval_work_item_v3") or {}).get("work_item_kind")
                ).strip(),
                "retrieval_work_item_schema": str(
                    (raw_plan.get("retrieval_work_item_v3") or {}).get("schema_version")
                ).strip(),
                "query_branch": str(
                    raw_plan.get("branch") or raw_plan.get("query_branch") or ""
                ).strip(),
                "semantic_fingerprint": str(
                    raw_plan.get("semantic_fingerprint")
                    or raw_plan.get("query_fingerprint")
                    or ""
                ).strip(),
                "query_fingerprint": str(
                    raw_plan.get("query_fingerprint")
                    or raw_plan.get("semantic_fingerprint")
                    or ""
                ).strip(),
                "discovery_fingerprint": str(
                    raw_plan.get("discovery_fingerprint") or ""
                ).strip(),
            }
        )
    if len(entries) == 1:
        return entries[0]
    if entries:
        return {
            "task_count": len(entries),
            "tasks": entries,
        }
    return {}


def attach_query_plan_provenance(
    block: dict[str, Any],
    plan: dict[str, Any] | None,
) -> dict[str, Any]:
    """Carry semantic-path metadata from dispatch through result flattening."""

    annotated = dict(block)
    if not isinstance(plan, dict):
        return annotated
    for field in _QUERY_PLAN_PROVENANCE_FIELDS:
        value = plan.get(field)
        if value not in (None, "", [], {}):
            annotated[field] = list(value) if isinstance(value, tuple) else value
    return annotated


def attach_query_plan_provenance_to_blocks(
    blocks: list[dict[str, Any]],
    query_plan: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    """Attach branch metadata without changing provider response payloads."""

    plan_by_branch = {
        str(plan.get("branch") or "primary"): plan
        for plan in (query_plan or [])
        if isinstance(plan, dict)
    }
    return [
        attach_query_plan_provenance(
            block,
            plan_by_branch.get(str(block.get("query_branch") or "primary")),
        )
        for block in blocks
        if isinstance(block, dict)
    ]


def _v3_variant_event_context(plan: Mapping[str, Any] | None) -> dict[str, Any]:
    """Return current V3 task fields required on semantic-variant logs."""

    payload = plan if isinstance(plan, Mapping) else {}
    spec = payload.get("retrieval_spec_v3") if isinstance(payload.get("retrieval_spec_v3"), Mapping) else payload
    anchor_contract = (
        spec.get("retrieval_anchor_contract")
        if isinstance(spec.get("retrieval_anchor_contract"), Mapping)
        else {}
    )
    return {
        "project_id": str(payload.get("project_id") or ""),
        "sub_hypothesis_id": str(payload.get("sub_hypothesis_id") or ""),
        "research_question_task_id": str(payload.get("research_question_task_id") or ""),
        "evidence_slot": str(payload.get("evidence_slot") or ""),
        "query_branch": str(payload.get("query_branch") or payload.get("branch") or ""),
        "plan_revision": str(payload.get("plan_revision") or ""),
        "semantic_fingerprint": str(
            payload.get("semantic_fingerprint")
            or spec.get("semantic_fingerprint")
            or ""
        ),
        "anchor_contract_schema_version": str(anchor_contract.get("schema_version") or ""),
        "anchor_match_policy_version": str(
            anchor_contract.get("anchor_match_policy_version") or ""
        ),
        "provider_query_compilation_policy_version": str(
            anchor_contract.get("provider_query_compilation_policy_version") or ""
        ),
    }


def _query_plan_for_retrieval_layer(
    query_plan: list[dict[str, Any]] | None,
    layer_name: str,
) -> list[dict[str, Any]]:
    """Prefer evidence-path branches that are meant for this retrieval layer.

    Older query plans lack layer metadata, so they keep the previous behavior.
    Panel/integrative SHs can now route core validation, component support, and
    context/boundary branches independently without turning L1 back on.
    """

    plans = [dict(plan) for plan in (query_plan or []) if isinstance(plan, dict)]
    if not plans:
        return []
    layer = str(layer_name or "").strip()

    def layers_from(plan: dict[str, Any], field: str) -> list[str]:
        value = plan.get(field)
        values = value if isinstance(value, (list, tuple, set)) else [value]
        return [
            str(item or "").strip()
            for item in values
            if str(item or "").strip()
        ]

    def matches(plan: dict[str, Any]) -> bool:
        preferred = layers_from(plan, "preferred_retrieval_layers")
        signals = layers_from(plan, "preprint_signal_layers")
        if not preferred and not signals:
            return True
        if layer == "L3_preprint":
            return layer in signals or layer in preferred
        return layer in preferred

    def layer_sort_key(plan: dict[str, Any]) -> tuple[int, int, int, str]:
        tier = str(plan.get("panel_evidence_tier") or "").strip().lower()
        role = str(plan.get("evidence_path_role") or plan.get("query_family") or "").strip().lower()
        target_lane = str(plan.get("target_lane") or "").strip().upper()
        polarity = str(plan.get("evidence_path_polarity") or "").strip().lower()
        core_capable = bool(plan.get("core_evidence_capable") or plan.get("panel_core_path"))
        component = bool(plan.get("panel_component_path") or tier in {"support", "context"})
        context = bool(tier == "context" or any(marker in role for marker in ("background", "framework", "review", "boundary")))
        if layer == "L0_review":
            primary = 0 if context else 1 if component else 2
        elif layer == "L2_top_latest":
            primary = 0 if core_capable or tier == "core" else 1 if context else 2
        elif layer == "L4_regular":
            primary = 0 if core_capable or tier == "core" else 1 if component else 2
        elif layer == "L3_preprint":
            primary = 0 if core_capable or tier == "core" else 1 if component else 2
        else:
            primary = 0
        lane_priority = (
            0
            if target_lane in {"CAUSAL_VALIDATION", "PREDICTIVE_VALIDATION"} and polarity != "opposing"
            else 1
            if target_lane == "ADVERSE_OR_REVERSAL_EVIDENCE" or polarity == "opposing"
            else 2
            if target_lane == "BOUNDARY_OR_NEGATIVE_EVIDENCE" or polarity == "boundary"
            else 3
        )
        secondary = 0 if str(plan.get("preferred_retrieval_layers") or "") else 1
        return (primary, lane_priority, secondary, str(plan.get("branch") or ""))

    matched = [plan for plan in plans if matches(plan)]
    if not matched:
        return plans
    return sorted(matched, key=layer_sort_key)


def _candidate_budget_allocations(
    plans: list[dict[str, Any]],
    total_budget: int,
) -> list[int]:
    """Allocate an actual provider candidate budget from query-plan shares.

    Query-plan shares are normalized again after layer filtering.  This keeps
    the core/corpus split operative even when, for example, L0 contains only a
    review branch.  Every active branch gets one request slot when the budget
    permits; the remainder follows largest-remainder weighted allocation.
    """

    if not plans:
        return []
    total = max(0, int(total_budget or 0))
    if total <= 0:
        return [0] * len(plans)
    raw_weights = [
        max(0.0, float(plan.get("candidate_budget_share") or 0.0))
        for plan in plans
    ]
    if not any(raw_weights):
        raw_weights = [1.0] * len(plans)
    weight_total = sum(raw_weights)
    weights = [weight / weight_total for weight in raw_weights]
    allocations = [0] * len(plans)
    remaining = total
    if total >= len(plans):
        allocations = [1] * len(plans)
        remaining -= len(plans)
    exact = [remaining * weight for weight in weights]
    floors = [int(value) for value in exact]
    allocations = [
        allocated + floor
        for allocated, floor in zip(allocations, floors)
    ]
    leftover = remaining - sum(floors)
    remainder_order = sorted(
        range(len(plans)),
        key=lambda index: (
            exact[index] - floors[index],
            weights[index],
            -index,
        ),
        reverse=True,
    )
    for index in remainder_order[:leftover]:
        allocations[index] += 1
    return allocations


def _weighted_candidate_plan_schedule(
    plans: list[dict[str, Any]],
    total_budget: int,
) -> list[dict[str, Any]]:
    """Return an interleaved per-candidate schedule honoring pool shares."""

    allocations = _candidate_budget_allocations(plans, total_budget)
    scheduled: list[tuple[float, int, dict[str, Any]]] = []
    for plan_index, (plan, allocation) in enumerate(zip(plans, allocations)):
        for ordinal in range(allocation):
            scheduled.append(
                (
                    (ordinal + 0.5) / max(1, allocation),
                    plan_index,
                    plan,
                )
            )
    scheduled.sort(key=lambda item: (item[0], item[1]))
    return [plan for _, _, plan in scheduled]


def search_papers(
    query: str,
    databases: list[str] | None = None,
    max_results: int = 50,
    years: str = "",
) -> str:
    try:
        from ._project import default_literature_providers
        from ._utils import unique_preserve_order
    except ImportError:
        from _project import default_literature_providers
        from _utils import unique_preserve_order
    providers = [database_to_provider(item) for item in (databases or default_literature_providers(query=query))]
    providers = unique_preserve_order([item for item in providers if item])
    providers = _filter_runtime_enabled_literature_providers(
        providers,
        requested_providers=[database_to_provider(item) for item in (databases or [])],
        context="search_papers",
    )
    result = json.loads(search_literature(query, providers=providers, max_results=max_results))
    result["zhizhi_action"] = "search_papers"
    result["databases_requested"] = databases or providers
    result["years"] = years
    return json.dumps(result, ensure_ascii=False, indent=2)


def normalize_deep_alignment_candidate_limit(value: Any = None) -> int:
    """Bound the targeted-alignment audit window without the old 60-paper cap.

    The 60-candidate default is still a good cheap first pass for broad
    retrieval.  Sub-hypothesis retrieval, however, may already know that L2 or
    core-evidence lanes are undersupplied.  In that case the caller can request
    a wider deterministic audit window; this helper prevents unbounded scans
    while allowing enough headroom to rescue aligned reserve candidates.
    """

    try:
        requested = int(value or 60)
    except (TypeError, ValueError):
        requested = 60
    return max(40, min(int(SCIENCE_DEEP_ALIGNMENT_CANDIDATE_LIMIT_MAX), requested))


def search_papers_stratified(
    query: str,
    databases: list[str] | None = None,
    max_results: int = 50,
    years: str = "",
    domain: str = "",
    focus_branches: list[str] | None = None,
    use_llm: bool | None = None,
    explicit_query_plan: list[dict[str, Any]] | None = None,
    layer_quotas: dict[str, int] | None = None,
    research_question_card: dict[str, Any] | None = None,
    single_paper_serial: bool = False,
    project_id: str = "",
    sub_hypothesis_id: str = "",
    retrieval_scope_kind: str = "",
    alignment_contract_hash: str = "",
    candidate_alignment_contract: dict[str, Any] | None = None,
    retrieval_anchor_contract: dict[str, Any] | None = None,
    deep_alignment_candidate_limit: int = 60,
    exclude_candidate_keys: list[str] | set[str] | tuple[str, ...] | None = None,
    previously_imported_source_count: int = 0,
    project_discipline_taxonomy: Mapping[str, Any] | None = None,
    v3_provider_allowlist: list[str] | set[str] | tuple[str, ...] | None = None,
    v3_prior_provider_execution: Mapping[str, Any] | None = None,
    shared_raw_candidate_pool: list[dict[str, Any]] | None = None,
    shared_raw_candidate_pool_only: bool = False,
) -> str:
    try:
        from ._project import default_literature_providers
        from ._utils import unique_preserve_order
    except ImportError:
        from _project import default_literature_providers
        from _utils import unique_preserve_order
    providers = [database_to_provider(item) for item in (databases or default_literature_providers(domain=domain, query=query))]
    providers = unique_preserve_order([item for item in providers if item])
    providers = _filter_runtime_enabled_literature_providers(
        providers,
        requested_providers=[database_to_provider(item) for item in (databases or [])],
        context="search_papers_stratified",
    )
    result = json.loads(
        search_literature_stratified(
            query,
            providers=providers,
            max_results=max_results,
            domain=domain,
            focus_branches=focus_branches,
            use_llm=use_llm,
            explicit_query_plan=explicit_query_plan,
            layer_quotas=layer_quotas,
            project_discipline_taxonomy=project_discipline_taxonomy,
            research_question_card=research_question_card,
            single_paper_serial=single_paper_serial,
            project_id=project_id,
            sub_hypothesis_id=sub_hypothesis_id,
            retrieval_scope_kind=retrieval_scope_kind,
            alignment_contract_hash=alignment_contract_hash,
            candidate_alignment_contract=candidate_alignment_contract,
            retrieval_anchor_contract=retrieval_anchor_contract,
            deep_alignment_candidate_limit=deep_alignment_candidate_limit,
            exclude_candidate_keys=exclude_candidate_keys,
            previously_imported_source_count=previously_imported_source_count,
            v3_provider_allowlist=v3_provider_allowlist,
            v3_prior_provider_execution=v3_prior_provider_execution,
            shared_raw_candidate_pool=shared_raw_candidate_pool,
            shared_raw_candidate_pool_only=shared_raw_candidate_pool_only,
        )
    )
    result["zhizhi_action"] = "search_papers_stratified"
    result["databases_requested"] = databases or providers
    result["years"] = years
    result["domain"] = domain
    result["focus_branches"] = focus_branches or []
    return json.dumps(result, ensure_ascii=False, indent=2)

def database_to_provider(name: str) -> str:
    try:
        from ._models import STABLE_LITERATURE_PROVIDERS
        from ._utils import normalize_key
    except ImportError:
        from _models import STABLE_LITERATURE_PROVIDERS
        from _utils import normalize_key
    key = normalize_key(name)
    mapping = {
        "semantic_scholar": "semantic_scholar",
        "semanticscholar": "semantic_scholar",
        "s2": "semantic_scholar",
        "openalex": "openalex",
        "open_alex": "openalex",
        "sciencedirect": "sciencedirect",
        "science_direct": "sciencedirect",
        "elsevier": "sciencedirect",
        "arxiv": "arxiv",
        "bio_rxiv": "biorxiv",
        "biorxiv": "biorxiv",
        "bioarchive": "biorxiv",
        "med_rxiv": "medrxiv",
        "medrxiv": "medrxiv",
        "chem_rxiv": "chemrxiv",
        "chemrxiv": "chemrxiv",
        "pub_med": "pubmed",
        "pubmed": "pubmed",
        "ncbi": "pubmed",
        "medline": "pubmed",
    }
    provider = mapping.get(key, "")
    return provider if provider in STABLE_LITERATURE_PROVIDERS else ""

def extract_structured_info(
    paper_content: str,
    fields: list[str] | None = None,
    use_llm: bool | None = None,
) -> str:
    try:
        from ._literature_import import extract_paper_structure
        from ._pipeline import classify_evidence_claims
    except ImportError:
        from _literature_import import extract_paper_structure
        from _pipeline import classify_evidence_claims
    parsed = extract_paper_structure(paper_content, use_llm=use_llm)
    result = {
        "zhizhi_action": "extract_structured_info",
        "requested_fields": fields
        or ["research method", "application scenario", "test benchmark", "core contribution", "limitation"],
        "structured_info": {
            "research_method": parsed.get("method", ""),
            "application_scenario": parsed.get("scenario", ""),
            "test_benchmark": parsed.get("benchmark", ""),
            "core_contribution": parsed.get("contribution", ""),
            "core_conclusion": parsed.get("conclusion", ""),
            "limitation": parsed.get("limitation", ""),
        },
        "evidence_type_annotations": classify_evidence_claims(paper_content, parsed),
        "extractor": parsed.get("extractor", ""),
    }
    return json.dumps(result, ensure_ascii=False, indent=2)

def search_literature_provider_block(
    provider: str,
    query: str,
    max_results: int,
    *,
    discipline_filter: dict[str, Any] | None = None,
) -> dict[str, Any]:
    try:
        from ._literature_import import import_literature_text, import_papergraph_record
        from ._models import LITERATURE_PROVIDERS
    except ImportError:
        from _literature_import import import_literature_text, import_papergraph_record
        from _models import LITERATURE_PROVIDERS
    spec = LITERATURE_PROVIDERS.get(provider)
    if spec is None:
        return {
            "provider": provider,
            "query": query,
            "status": "unknown_provider",
            "results": [],
        }
    disabled_reason = _literature_provider_disabled_reason(provider)
    if disabled_reason:
        return {
            "provider": provider,
            "query": query,
            "status": "disabled_by_policy",
            "results": [],
            "reason": disabled_reason,
        }
    taxonomy_filter = dict(discipline_filter or {})
    if provider == "arxiv":
        block = search_arxiv(
            query,
            max_results=max_results,
            categories=taxonomy_filter.get("categories") if taxonomy_filter.get("applied") else None,
        )
        block["discipline_filter_audit"] = taxonomy_filter
        return block
    if provider == "openalex":
        try:
            from ._openalex import search_openalex_works
        except ImportError:
            from _openalex import search_openalex_works
        openalex_options: dict[str, Any] = {"max_results": max_results}
        if taxonomy_filter.get("applied"):
            openalex_options["filters"] = str(taxonomy_filter.get("filter") or "")
        block = search_openalex_works(query, **openalex_options)
        block["discipline_filter_audit"] = taxonomy_filter
        return block
    if provider == "sciencedirect":
        try:
            from ._sciencedirect import search_sciencedirect
        except ImportError:
            from _sciencedirect import search_sciencedirect
        block = search_sciencedirect(query, max_results=max_results)
        block["discipline_filter_audit"] = taxonomy_filter
        return block
    if provider == "semantic_scholar":
        block = search_semantic_scholar(query, max_results=max_results)
        block["discipline_filter_audit"] = taxonomy_filter
        return block
    if provider == "pubmed":
        block = search_pubmed(
            query,
            max_results=max_results,
            mesh_terms=taxonomy_filter.get("mesh_terms") if taxonomy_filter.get("applied") else None,
        )
        block["discipline_filter_audit"] = taxonomy_filter
        return block
    if provider in {"biorxiv", "medrxiv", "chemrxiv"}:
        block = search_preprint_api(provider, query, max_results=max_results)
        block["discipline_filter_audit"] = taxonomy_filter
        return block
    block = {
        "provider": provider,
        "query": query,
        "status": spec["status"],
        "note": spec["note"],
        "results": [],
        "next_step": "Use a compliant external connector, or import_literature_text/import_papergraph_record manually only if the user provides the paper text.",
    }
    block["discipline_filter_audit"] = taxonomy_filter
    return block

def search_literature(
    query: str,
    providers: list[str] | None = None,
    max_results: int = 50,
    anchor_contract: dict[str, Any] | None = None,
    approved_synonyms: list[str] | None = None,
    domain: str = "",
) -> str:
    try:
        from ._literature_import import import_literature_search_result
        from ._literature_retrieval_foundation import (
            compile_provider_query,
            create_retrieval_run,
            fuse_literature_candidates,
            repair_provider_query,
        )
        from ._discipline_taxonomy import compile_provider_discipline_filter, resolve_discipline_taxonomy
        from ._project import default_literature_providers, live_literature_provider_names, save_search
        from ._utils import new_id, unique_preserve_order
    except ImportError:
        from _literature_import import import_literature_search_result
        from _literature_retrieval_foundation import (
            compile_provider_query,
            create_retrieval_run,
            fuse_literature_candidates,
            repair_provider_query,
        )
        from _discipline_taxonomy import compile_provider_discipline_filter, resolve_discipline_taxonomy
        from _project import default_literature_providers, live_literature_provider_names, save_search
        from _utils import new_id, unique_preserve_order
    query_language = english_provider_query(query)
    source_query = query_language["source_query"]
    query = query_language["query"]
    if not query:
        raise ValueError(
            "External literature retrieval requires an English query. "
            "Automatic translation could not derive safe English scientific keywords."
        )
    discipline_taxonomy = resolve_discipline_taxonomy(domain, query=query)
    search_id = new_id("search")
    selected = [database_to_provider(provider) for provider in (providers or default_literature_providers(query=query))]
    selected = unique_preserve_order([provider for provider in selected if provider in live_literature_provider_names()])
    selected = _filter_runtime_enabled_literature_providers(
        selected,
        requested_providers=[database_to_provider(provider) for provider in (providers or [])],
        context="search_literature",
    )
    if not selected:
        selected = _filter_runtime_enabled_literature_providers(
            default_literature_providers(query=query),
            requested_providers=[database_to_provider(provider) for provider in (providers or [])],
            context="search_literature_fallback",
        ) or ["openalex"]
    provider_discipline_filters = {
        provider: compile_provider_discipline_filter(provider, discipline_taxonomy)
        for provider in selected
    }
    synonym_allowlist = list(approved_synonyms or [])
    provider_compilations = {
        provider: compile_provider_query(
            provider,
            query,
            anchor_contract=anchor_contract,
            approved_synonyms=synonym_allowlist,
        )
        for provider in selected
    }

    def dispatch_provider_block(provider: str, provider_query: str) -> dict[str, Any]:
        discipline_filter = provider_discipline_filters.get(provider) or {}
        if discipline_filter.get("applied"):
            block = search_literature_provider_block(
                provider,
                provider_query,
                max_results,
                discipline_filter=discipline_filter,
            )
        else:
            # Preserve the public/provider mock call shape when no native
            # filter exists.  The audit still records that filtering was
            # intentionally withheld rather than silently omitted.
            block = search_literature_provider_block(provider, provider_query, max_results)
        if isinstance(block, dict):
            block.setdefault("discipline_filter_audit", dict(discipline_filter))
        return block

    def retrieve_provider(provider: str) -> dict[str, Any]:
        compilation = provider_compilations[provider]
        if not compilation.get("valid"):
            static_repair = repair_provider_query(
                provider,
                str(compilation.get("compiled_query") or query),
                "; ".join((compilation.get("syntax_validation") or {}).get("errors") or ["anchor_validation_failed"]),
                anchor_contract=anchor_contract,
                prior_queries=[str(compilation.get("source_query") or query)],
                approved_synonyms=synonym_allowlist,
            )
            if static_repair.get("accepted"):
                repaired_query = str(static_repair["repaired_query"])
                repaired_compilation = compile_provider_query(
                    provider,
                    repaired_query,
                    anchor_contract=anchor_contract,
                    approved_synonyms=synonym_allowlist,
                )
                repaired_compilation["static_repair"] = static_repair
                provider_compilations[provider] = repaired_compilation
                if repaired_compilation.get("valid"):
                    block = dispatch_provider_block(provider, repaired_query)
                    block["query_compilation"] = repaired_compilation
                    block["query_revisions"] = [static_repair]
                    block["attempted_queries"] = [str(compilation.get("source_query") or query), repaired_query]
                    block["submitted_to_provider"] = True
                    return block
            return {
                "provider": provider,
                "query": compilation.get("compiled_query", query),
                "status": str(compilation.get("failure_kind") or "provider_query_compilation_error"),
                "error": "Provider query compilation rejected this request before network submission.",
                "results": [],
                "submitted_to_provider": False,
                "failure_stage": "provider_query_compilation",
                "failure_kind": str(compilation.get("failure_kind") or "provider_query_compilation_error"),
                "query_compilation": compilation,
                "query_revisions": [static_repair],
            }
        attempted_queries = [str(compilation.get("compiled_query") or query)]
        revisions: list[dict[str, Any]] = []
        block = dispatch_provider_block(provider, attempted_queries[-1])
        # One repair is intentional: only source syntax is corrected, and a
        # network/API failure never turns into an unbounded query retry loop.
        if str(block.get("status") or "") == "error":
            repair = repair_provider_query(
                provider,
                attempted_queries[-1],
                block.get("error") or "provider_error",
                anchor_contract=anchor_contract,
                prior_queries=attempted_queries,
                approved_synonyms=synonym_allowlist,
            )
            revisions.append(repair)
            if repair.get("accepted"):
                attempted_queries.append(str(repair["repaired_query"]))
                block = dispatch_provider_block(provider, attempted_queries[-1])
        block["query_compilation"] = compilation
        block["query_revisions"] = revisions
        block["attempted_queries"] = attempted_queries
        block["submitted_to_provider"] = True
        return block

    provider_blocks: list[dict[str, Any]] = []
    if selected:
        indexed_blocks: dict[int, dict[str, Any]] = {}
        with ThreadPoolExecutor(max_workers=min(6, len(selected))) as executor:
            future_map = {
                executor.submit(retrieve_provider, provider): (index, provider)
                for index, provider in enumerate(selected)
            }
            for future in as_completed(future_map):
                index, provider = future_map[future]
                try:
                    indexed_blocks[index] = future.result()
                except Exception as exc:
                    indexed_blocks[index] = provider_error_result(provider, query, exc)
                    indexed_blocks[index]["query_compilation"] = provider_compilations.get(provider, {})
                    indexed_blocks[index]["query_revisions"] = []
                    log_event("SCIENCE", "literature_search_failed", provider=provider, error=str(exc))
        provider_blocks = [indexed_blocks[index] for index in sorted(indexed_blocks)]
    candidate_pool = dedupe_literature_results(flatten_literature_results(provider_blocks))
    discovery_ranked = rank_literature_results(query, candidate_pool) if candidate_pool else []

    def discovery_year(item: dict[str, Any]) -> int:
        match = re.search(r"\b(19|20)\d{2}\b", str(item.get("year") or ""))
        return int(match.group(0)) if match else 0

    def discovery_impact(item: dict[str, Any]) -> float:
        metrics = item.get("citation_metrics") if isinstance(item.get("citation_metrics"), dict) else {}
        openalex_metrics = metrics.get("openalex") if isinstance(metrics.get("openalex"), dict) else {}
        semantic_scholar_metrics = metrics.get("semantic_scholar") if isinstance(metrics.get("semantic_scholar"), dict) else {}
        for value in (
            item.get("citation_count"),
            openalex_metrics.get("cited_by_count"),
            semantic_scholar_metrics.get("citation_count"),
        ):
            try:
                return float(value or 0.0)
            except (TypeError, ValueError):
                continue
        return 0.0

    candidate_fusion = fuse_literature_candidates(
        query,
        {
            "direct_relevance": discovery_ranked,
            "impact": sorted(discovery_ranked, key=discovery_impact, reverse=True),
            "recent_direct_evidence": sorted(discovery_ranked, key=discovery_year, reverse=True),
            "local_quality": sorted(
                discovery_ranked,
                key=lambda item: float(item.get("publication_quality_score") or 0.0),
                reverse=True,
            ),
        },
    )
    flattened = rank_literature_results(query, candidate_fusion["documents"]) if candidate_fusion["documents"] else []
    for index, item in enumerate(flattened):
        item["result_index"] = index
        item["search_id"] = search_id
    provider_attempts = [
        {
            "provider": block.get("provider"),
            "status": block.get("status"),
            "query": block.get("query"),
            "attempted_queries": block.get("attempted_queries", []),
            "result_count": len(block.get("results") or []),
            "cache_hit": block.get("cache_hit"),
            "zero_result_cache_hit": block.get("zero_result_cache_hit"),
            "submitted_to_provider": bool(block.get("submitted_to_provider")),
            "failure_stage": block.get("failure_stage", ""),
            "failure_kind": block.get("failure_kind", ""),
            "compilation_fingerprint": (
                (block.get("query_compilation") or {}).get("compilation_fingerprint")
                if isinstance(block.get("query_compilation"), Mapping)
                else ""
            ),
            "discipline_filter_audit": block.get("discipline_filter_audit", {}),
            "error": block.get("error", ""),
        }
        for block in provider_blocks
    ]
    retrieval_run = create_retrieval_run(
        search_id=search_id,
        query=query,
        source_query=source_query,
        providers=selected,
        anchor_contract=anchor_contract,
        provider_attempts=provider_attempts,
        query_compilations=[
            {
                **provider_compilations.get(str(block.get("provider") or ""), {}),
                "repair_attempts": block.get("query_revisions", []),
            }
            for block in provider_blocks
        ],
        candidate_fusion={
            key: value
            for key, value in candidate_fusion.items()
            if key != "documents"
        },
        discipline_taxonomy=discipline_taxonomy,
        strategy="multi_lane_candidate_discovery",
    )
    search_record = {
        "search_id": search_id,
        "query": query,
        "source_query": source_query,
        "query_language": query_language,
        "providers": selected,
        "discipline_taxonomy": discipline_taxonomy,
        "createdAt": time.time(),
        "total_results": len(flattened),
        "results": flattened,
        "provider_blocks": provider_blocks,
        "retrieval_run": retrieval_run,
    }
    save_search(search_record)
    response = {
        "search_id": search_id,
        "query": query,
        "source_query": source_query,
        "query_language": query_language,
        "providers": selected,
        "discipline_taxonomy": discipline_taxonomy,
        "total_results": len(flattened),
        "results": summarize_literature_results(flattened),
        "provider_blocks": summarize_provider_blocks(provider_blocks),
        "retrieval_run": retrieval_run,
        "full_results_cached": True,
        "next_step": (
            "Use select_literature_result(search_id) to inspect the top-ranked paper, then "
            "use import_literature_search_result(project_id, search_id, result_index) to import a real retrieved paper. "
            "If total_results is 0, stop and report retrieval failure; do not invent or substitute papers."
        ),
    }
    log_event("SCIENCE", "literature_search", query=query, providers=",".join(selected), max_results=max_results)
    return json.dumps(response, ensure_ascii=False, indent=2)


_SYNONYM_MAP: dict[str, list[str]] = {
    # Nuclear / superheavy
    "superheavy": ["superheavy", "transactinide", "transuranium", "super-heavy"],
    "elements": ["elements", "nuclei", "atoms", "nuclides"],
    "shell": ["shell", "shell closure", "magic number", "shell gap"],
    "fusion": ["fusion", "fusion-evaporation", "compound nucleus"],
    "detection": ["detection", "spectroscopy", "spectrometry", "recoil separator"],
    "IUPAC": ["IUPAC", "discovery criteria", "element verification"],
    "decay": ["decay", "alpha decay", "spontaneous fission", "half-life"],
    # Materials / energy
    "battery": ["battery", "cell", "accumulator"],
    "electrolyte": ["electrolyte", "ionic conductor", "solid conductor"],
    "cathode": ["cathode", "positive electrode", "cathode material"],
    "dendrite": ["dendrite", "lithium dendrite", "metal dendrite"],
    "conductivity": ["conductivity", "ionic conductivity", "ion transport"],
    # Catalysis
    "catalyst": ["catalyst", "electrocatalyst", "cocatalyst"],
    "overpotential": ["overpotential", "eta10", "activation overpotential"],
    "stability": ["stability", "durability", "long-term performance"],
    # Climate
    "drought": ["drought", "dry spell", "moisture deficit", "aridity"],
    "regime": ["regime", "regime shift", "climate regime", "climate state"],
    # AI / CS
    "agent": ["agent", "autonomous agent", "AI agent", "LLM agent"],
    "hypothesis": ["hypothesis", "research idea", "scientific hypothesis"],
}


def expand_query_with_synonyms(query: str, max_extra: int = 3) -> str:
    """Append OR-expanded synonym terms when the initial search yields too
    few results.  Returns the original query plus up to *max_extra* synonym
    phrases joined by spaces (not strict boolean OR, since most provider
    APIs treat spaces as soft-AND/semantic match).
    """
    words = query.lower().split()
    expansions: list[str] = []
    seen: set[str] = set(words)
    for word in words:
        if word in _SYNONYM_MAP:
            for syn in _SYNONYM_MAP[word]:
                if syn.lower() not in seen and syn.lower() != word:
                    expansions.append(syn)
                    seen.add(syn.lower())
                    if len(expansions) >= max_extra:
                        break
        if len(expansions) >= max_extra:
            break
    if expansions:
        log_event("SCIENCE", "query_expanded_synonyms", original=query[:80], additions=expansions)
    return query if not expansions else f"{query} {' '.join(expansions)}"


SEMANTIC_SCHOLAR_PEER_REVIEWED_LAYERS = (
    "L0_review",
    "L2_top_latest",
    "L4_regular",
)

# OpenAlex remains the broad-coverage discovery layer.  L2 is a protected
# recent/high-impact *selection role*, not a mandatory pair of additional
# provider queries.  Candidates already found by broad OpenAlex/PubMed search
# are always considered first.  Only an evidence shortage can trigger one
# bounded OpenAlex supplement and, if that still leaves a shortage, one
# best-effort Semantic Scholar supplement.  The compatibility batch below
# keeps the old explicit-Semantic-Scholar behaviour for the other
# peer-reviewed layers without allowing it to duplicate or displace the L2
# source of record.
SEMANTIC_SCHOLAR_COMPATIBILITY_LAYERS = (
    "L0_review",
    "L4_regular",
)
SEMANTIC_SCHOLAR_L2_TOP_LATEST_LAYER = "L2_top_latest"


def semantic_scholar_stratified_batch_required(
    providers: list[str],
    quotas: dict[str, int],
) -> bool:
    """Whether an explicitly selected SS compatibility batch is needed.

    L2 has its own dedicated Semantic Scholar path; this predicate preserves
    the generic, explicitly requested batch only for L0/L4.  L1 is owned by
    the dedicated foundational-mechanism workflow and cannot schedule a broad
    Semantic Scholar request.
    """
    peer_reviewed_target = sum(
        max(0, int(quotas.get(layer, 0)))
        for layer in SEMANTIC_SCHOLAR_COMPATIBILITY_LAYERS
    )
    return "semantic_scholar" in providers and peer_reviewed_target > 0


def semantic_scholar_l2_top_latest_batch_required(quotas: dict[str, int]) -> bool:
    """Whether L2 has a target that could justify an SS *supplement*.

    This deliberately does not mean that a Semantic Scholar request will be
    issued.  The orchestrator first evaluates the unified broad candidate
    pool, then OpenAlex, and calls SS only if a real L2 shortfall remains.
    """
    return max(0, int(quotas.get(SEMANTIC_SCHOLAR_L2_TOP_LATEST_LAYER, 0))) > 0


def restrict_stratified_candidates_to_layers(
    candidates_by_layer: dict[str, list[dict[str, Any]]],
    allowed_layers: set[str] | tuple[str, ...],
    *,
    demote_l2_to_l4: bool = False,
) -> dict[str, list[dict[str, Any]]]:
    """Keep provider provenance honest when a provider owns only some layers."""
    allowed = {str(layer) for layer in allowed_layers}
    restricted = {
        str(layer): list(items) if str(layer) in allowed else []
        for layer, items in candidates_by_layer.items()
    }
    # A caller can intentionally set the L2 quota to zero while still asking
    # for L4 primary evidence.  In that case a recent high-quality primary
    # paper must not disappear merely because it *would* otherwise qualify for
    # L2; record the demotion rather than duplicating it across the two slots.
    if demote_l2_to_l4 and "L4_regular" in allowed:
        for candidate in candidates_by_layer.get(SEMANTIC_SCHOLAR_L2_TOP_LATEST_LAYER, []):
            item = dict(candidate)
            item["provider_local_layer"] = "L4_regular"
            item["provider_local_l2_demoted"] = "L2 quota is zero; retained as formal primary L4 evidence"
            restricted.setdefault("L4_regular", []).append(item)
    return restricted


def openalex_stratified_batch_required(
    providers: list[str],
    quotas: dict[str, int],
) -> bool:
    """Whether OpenAlex broad discovery is needed outside dedicated L1/L2."""
    peer_reviewed_target = sum(
        max(0, int(quotas.get(layer, 0)))
        for layer in SEMANTIC_SCHOLAR_COMPATIBILITY_LAYERS
    )
    return "openalex" in providers and peer_reviewed_target > 0


def openalex_l2_top_latest_batch_required(quotas: dict[str, int]) -> bool:
    """Whether L2 has a target that could justify an OpenAlex supplement."""
    return max(0, int(quotas.get(SEMANTIC_SCHOLAR_L2_TOP_LATEST_LAYER, 0))) > 0


def sciencedirect_stratified_batch_required(
    providers: list[str],
    quotas: dict[str, int],
) -> bool:
    """Whether credentialed ScienceDirect metadata can supplement broad discovery.

    The source has no L1 writer and no PDF entitlement.  Its records join the
    same L0/L2/L4 candidate pool as other bibliographic discovery sources.
    """
    peer_reviewed_target = sum(
        max(0, int(quotas.get(layer, 0)))
        for layer in SEMANTIC_SCHOLAR_COMPATIBILITY_LAYERS
    ) + max(0, int(quotas.get(SEMANTIC_SCHOLAR_L2_TOP_LATEST_LAYER, 0)))
    return (
        "sciencedirect" in providers
        and not _literature_provider_disabled_reason("sciencedirect")
        and peer_reviewed_target > 0
    )


def broad_peer_reviewed_candidate_layers(quotas: dict[str, int]) -> set[str]:
    """Return peer-reviewed layers retained from broad provider discovery.

    Before this policy, OpenAlex/PubMed candidates locally classified as L2
    were discarded from their protected slot and the system re-queried both
    OpenAlex and Semantic Scholar unconditionally.  Retaining L2 here lets
    the selector use already-retrieved, already-ranked evidence first.  L1
    is deliberately absent: only the foundational-mechanism contract and
    bridge assessment may populate that layer.
    """
    layers = set(SEMANTIC_SCHOLAR_COMPATIBILITY_LAYERS)
    if max(0, int(quotas.get(SEMANTIC_SCHOLAR_L2_TOP_LATEST_LAYER, 0))) > 0:
        layers.add(SEMANTIC_SCHOLAR_L2_TOP_LATEST_LAYER)
    return layers


def is_dedicated_foundation_query_branch(item: dict[str, Any]) -> bool:
    """Identify query-plan entries that belong to the independent L1 lane."""

    branch = str(item.get("branch") or item.get("query_branch") or "").strip().lower()
    query_family = str(item.get("query_family") or item.get("topic_type") or "").strip().lower()
    return bool(
        branch in {
            "milestone_foundations",
            "historical_foundations",
            "foundational_literature",
            "foundational_mechanism_bridge",
        }
        or branch.endswith(":foundational_mechanism_bridge")
        or branch.startswith("milestone_foundation")
        or query_family in {
            "foundational_retrieval",
            "historical_foundation",
            "milestone_retrieval",
        }
    )


def pubmed_stratified_batch_required(
    providers: list[str],
    quotas: dict[str, int],
) -> bool:
    if not SCIENCE_PUBMED_SPECIALIZED_SEARCH_ENABLED:
        return False
    peer_reviewed_target = sum(
        max(0, int(quotas.get(layer, 0)))
        for layer in SEMANTIC_SCHOLAR_COMPATIBILITY_LAYERS
    )
    return "pubmed" in providers and peer_reviewed_target > 0


def stratified_candidate_selection_log_fields(
    item: dict[str, Any],
    *,
    layer: str,
) -> dict[str, Any]:
    """Describe search selection without implying final import admission."""

    targeted_admission = (
        item.get("targeted_alignment_admission")
        if isinstance(item.get("targeted_alignment_admission"), dict)
        else {}
    )
    prefulltext_assessment = (
        targeted_admission.get("prefulltext_import_assessment")
        if isinstance(
            targeted_admission.get("prefulltext_import_assessment"),
            dict,
        )
        else {}
    )
    research_role = str(item.get("research_role") or "UNCLASSIFIED").upper()
    candidate_research_role = (
        research_role
        if research_role.endswith("_CANDIDATE")
        else f"{research_role}_CANDIDATE"
    )
    targeted_admission_tier = str(
        item.get("targeted_admission_tier")
        or targeted_admission.get("admission_tier")
        or ""
    )
    provisional_evidence_lane = str(
        item.get("provisional_evidence_lane")
        or targeted_admission.get("prefulltext_provisional_evidence_lane")
        or prefulltext_assessment.get("provisional_evidence_lane")
        or item.get("evidence_lane")
        or (
            "PENDING_FULLTEXT_TYPE_DIRECTED_EVIDENCE"
            if targeted_admission_tier == "AUXILIARY_PENDING_FULLTEXT"
            else ""
        )
    )
    detail_revalidation_required = bool(
        item.get("pending_full_text_verification")
        or item.get("detail_revalidation_required")
        or targeted_admission_tier == "AUXILIARY_PENDING_FULLTEXT"
    )
    return {
        "provider": str(item.get("provider") or "unknown"),
        "layer": str(layer or item.get("stratified_layer") or ""),
        "title": str(item.get("title") or "")[:240],
        "year": str(item.get("year") or ""),
        "venue": str(item.get("venue") or "")[:160],
        "citation_count": item.get("citation_count"),
        "relevance_score": item.get("relevance_score"),
        "publication_quality_score": item.get("publication_quality_score"),
        "venue_tier": venue_tier_label(item),
        "research_role": str(item.get("research_role") or ""),
        "selection_stage": "pre_import",
        "candidate_research_role": candidate_research_role,
        "targeted_admission_tier": targeted_admission_tier,
        "provisional_evidence_lane": provisional_evidence_lane,
        "detail_revalidation_required": detail_revalidation_required,
        "selection_source": "local_provider_pool_or_layer_retrieval",
    }


def search_literature_stratified(
    query: str,
    providers: list[str] | None = None,
    max_results: int = 50,
    domain: str = "",
    focus_branches: list[str] | None = None,
    use_llm: bool | None = None,
    explicit_query_plan: list[dict[str, Any]] | None = None,
    layer_quotas: dict[str, int] | None = None,
    research_question_card: dict[str, Any] | None = None,
    candidate_alignment_contract: dict[str, Any] | None = None,
    requested_evidence_kind: str = "",
    retrieval_anchor_contract: dict[str, Any] | None = None,
    retrieval_mode: str = "broad_discovery",
    direct_evidence_mode: bool = False,
    preprint_layers: list[str] | set[str] | tuple[str, ...] | None = None,
    preprint_scan_limit: int | None = None,
    preprint_provider_result_target: int = 0,
    preprint_recovery_windows: tuple[int, ...] | None = None,
    preprint_recovery_max_variants: int | None = None,
    preprint_max_branches: int | None = None,
    single_paper_serial: bool = False,
    project_id: str = "",
    sub_hypothesis_id: str = "",
    retrieval_scope_kind: str = "",
    alignment_contract_hash: str = "",
    deep_alignment_candidate_limit: int = 60,
    exclude_candidate_keys: list[str] | set[str] | tuple[str, ...] | None = None,
    previously_imported_source_count: int = 0,
    project_discipline_taxonomy: Mapping[str, Any] | None = None,
    v3_provider_allowlist: list[str] | set[str] | tuple[str, ...] | None = None,
    v3_prior_provider_execution: Mapping[str, Any] | None = None,
    shared_raw_candidate_pool: list[dict[str, Any]] | None = None,
    shared_raw_candidate_pool_only: bool = False,
) -> str:
    try:
        from ._literature_import import import_literature_search_result
        from ._literature_retrieval_foundation import (
            compile_provider_query,
            create_retrieval_run,
            fuse_literature_candidates,
        )
        from ._literature_scoring import build_research_domain_profile_artifact
        from ._discipline_taxonomy import compile_provider_discipline_filter, resolve_discipline_taxonomy
        from ._project import default_literature_providers, live_literature_provider_names, save_search
        from ._retrieval_strategy import (
            build_purposeful_query_plan,
            build_research_question_card,
            paper_domain_assessment_cache_key,
            prioritize_candidates_for_question_card,
            warm_paper_domain_assessment_cache,
            with_retrieval_query,
        )
        from ._utils import new_id, unique_preserve_order
        from ._research_alignment import (
            audit_subhypothesis_query_contamination,
            summarize_query_contamination_audits,
        )
        from ._research_question_contract import (
            ProviderOutcomeKind,
            build_provider_outcome_v3,
        )
        from ._science_execution_policy import resolve_science_execution_policy
    except ImportError:
        from _literature_import import import_literature_search_result
        from _literature_retrieval_foundation import (
            compile_provider_query,
            create_retrieval_run,
            fuse_literature_candidates,
        )
        from _literature_scoring import build_research_domain_profile_artifact
        from _discipline_taxonomy import compile_provider_discipline_filter, resolve_discipline_taxonomy
        from _project import default_literature_providers, live_literature_provider_names, save_search
        from _retrieval_strategy import (
            build_purposeful_query_plan,
            build_research_question_card,
            paper_domain_assessment_cache_key,
            prioritize_candidates_for_question_card,
            warm_paper_domain_assessment_cache,
            with_retrieval_query,
        )
        from _utils import new_id, unique_preserve_order
        from _research_alignment import (
            audit_subhypothesis_query_contamination,
            summarize_query_contamination_audits,
        )
        from _research_question_contract import (
            ProviderOutcomeKind,
            build_provider_outcome_v3,
        )
        from _science_execution_policy import resolve_science_execution_policy
    execution_policy = resolve_science_execution_policy({}, use_llm=use_llm)
    use_llm = execution_policy.use_llm
    query_language = english_provider_query(query, domain=domain, allow_llm=use_llm)
    source_query = query_language["source_query"]
    query = query_language["query"]
    if not query:
        raise ValueError(
            "External literature retrieval requires an English query. "
            "Automatic translation could not derive safe English scientific keywords."
        )
    search_id = new_id("search")
    requested_providers = [database_to_provider(provider) for provider in (providers or [])]
    domain_defaults = default_literature_providers(domain=domain, query=query)
    unfiltered_providers = unique_preserve_order(requested_providers + domain_defaults)
    provider_domain_context = {
        "domain": domain,
        "query": query,
        "scientific_object": str((candidate_alignment_contract or {}).get("scientific_object") or ""),
        "focus": str((candidate_alignment_contract or {}).get("focus") or ""),
        "input_terms": list(
            (
                (candidate_alignment_contract or {}).get("core_axis_policy")
                if isinstance((candidate_alignment_contract or {}).get("core_axis_policy"), dict)
                else {}
            ).get("focal_variable_terms")
            or []
        ),
        "outcome_terms": list(
            (
                (candidate_alignment_contract or {}).get("core_axis_policy")
                if isinstance((candidate_alignment_contract or {}).get("core_axis_policy"), dict)
                else {}
            ).get("outcome_terms")
            or []
        ),
        "moderator_terms": list((candidate_alignment_contract or {}).get("moderator_terms") or []),
        "project_context": list((candidate_alignment_contract or {}).get("project_context_anchor_terms") or []),
    }
    v3_allowed_providers = list(dict.fromkeys(
        database_to_provider(str(provider))
        for provider in (v3_provider_allowlist or [])
        if database_to_provider(str(provider))
    ))
    selected = filter_literature_providers_for_research_domain(
        unfiltered_providers,
        provider_domain_context,
    )
    pubmed_disabled_by_policy = (
        "pubmed" in unfiltered_providers
        and not SCIENCE_PUBMED_SPECIALIZED_SEARCH_ENABLED
    )
    pubmed_excluded_by_domain = (
        "pubmed" in unfiltered_providers
        and "pubmed" not in selected
        and not pubmed_disabled_by_policy
    )
    selected = [provider for provider in selected if provider in live_literature_provider_names()]
    selected = _filter_runtime_enabled_literature_providers(
        selected,
        requested_providers=requested_providers,
        context="search_literature_stratified",
    )
    if v3_allowed_providers:
        selected = [provider for provider in selected if provider in v3_allowed_providers]
        if not selected:
            selected = [
                provider for provider in v3_allowed_providers
                if provider in live_literature_provider_names()
            ]
    if not selected and not v3_allowed_providers:
        selected = _filter_runtime_enabled_literature_providers(
            default_literature_providers(domain=domain, query=query),
            requested_providers=requested_providers,
            context="search_literature_stratified_fallback",
        ) or ["openalex"]
    persisted_taxonomy = (
        project_discipline_taxonomy
        if isinstance(project_discipline_taxonomy, Mapping)
        else {}
    )
    if (
        persisted_taxonomy.get("schema_version") == "natural_science_discipline_taxonomy_v1"
        and isinstance(persisted_taxonomy.get("provider_filters"), Mapping)
    ):
        # Project creation resolves identity from the complete brief. V3 slot
        # queries reuse that stable discovery policy instead of trying to
        # infer a discipline again from a short, role-specific query.
        discipline_taxonomy = deepcopy(dict(persisted_taxonomy))
        taxonomy_source = "project_persisted"
    else:
        discipline_taxonomy = resolve_discipline_taxonomy(domain, query=query)
        taxonomy_source = "ad_hoc_query_resolution"
    provider_discipline_filters = {
        provider: compile_provider_discipline_filter(provider, discipline_taxonomy)
        for provider in selected
    }
    log_event(
        "SCIENCE",
        "discipline_taxonomy_resolved",
        primary=(discipline_taxonomy.get("primary") or {}).get("key", ""),
        coverage=discipline_taxonomy.get("coverage", "unsupported"),
        taxonomy_source=taxonomy_source,
        openalex_policy=provider_discipline_filters.get("openalex", {}).get("policy", "post_filter_only"),
        arxiv_policy=provider_discipline_filters.get("arxiv", {}).get("policy", "post_filter_only"),
        pubmed_policy=provider_discipline_filters.get("pubmed", {}).get("policy", "post_filter_only"),
    )
    if (
        isinstance(research_question_card, Mapping)
        and research_question_card.get("schema_version")
        == "research_question_contract_v3"
    ):
        question_payload = (
            research_question_card.get("research_question")
            if isinstance(research_question_card.get("research_question"), Mapping)
            else {}
        )
        base_question_card = build_research_question_card(
            domain=domain,
            objective=str(question_payload.get("question_text") or query),
            query=query,
            research_question_contract=research_question_card,
        )
    else:
        base_question_card = dict(research_question_card or {})
    normalized_question_card = with_retrieval_query(base_question_card, query)
    response_query_plan_override = (
        [dict(item) for item in explicit_query_plan if isinstance(item, dict)]
        if explicit_query_plan
        and not candidate_alignment_contract
        and not retrieval_anchor_contract
        and not project_id
        and not sub_hypothesis_id
        else None
    )
    query_plan = explicit_query_plan or (
        build_purposeful_query_plan(
            query,
            question_card=normalized_question_card,
            focus_branches=focus_branches,
            max_branches=5,
        )
        if research_question_card
        else build_domain_query_plan(
            query,
            domain=domain,
            focus_branches=focus_branches,
            use_llm=use_llm,
        )
    )
    query_plan = normalize_english_query_plan(query_plan, domain=domain, allow_llm=use_llm)
    runtime_query_context = {
        "project_id": str(project_id or ""),
        "sub_hypothesis_id": str(sub_hypothesis_id or ""),
    }
    if any(runtime_query_context.values()):
        query_plan = [
            {
                **plan,
                **{
                    field: value
                    for field, value in runtime_query_context.items()
                    if value
                },
            }
            if isinstance(plan, dict)
            else plan
            for plan in query_plan
        ]
    if isinstance(v3_prior_provider_execution, Mapping) and v3_prior_provider_execution:
        query_plan = [
            {
                **plan,
                "v3_prior_provider_execution": dict(v3_prior_provider_execution),
            }
            if isinstance(plan, dict)
            else plan
            for plan in query_plan
        ]
    if not isinstance(candidate_alignment_contract, dict) or not candidate_alignment_contract:
        alignment_contract_from_plan = next(
            (
                dict(plan.get("candidate_alignment_contract"))
                for plan in query_plan
                if isinstance(plan, dict)
                and isinstance(plan.get("candidate_alignment_contract"), Mapping)
                and plan.get("candidate_alignment_contract")
            ),
            {},
        )
        if alignment_contract_from_plan:
            candidate_alignment_contract = alignment_contract_from_plan
    if not isinstance(retrieval_anchor_contract, dict) or not retrieval_anchor_contract:
        anchor_contract_from_plan = next(
            (
                dict(plan.get("retrieval_anchor_contract"))
                for plan in query_plan
                if isinstance(plan, dict)
                and isinstance(plan.get("retrieval_anchor_contract"), Mapping)
                and plan.get("retrieval_anchor_contract")
            ),
            {},
        )
        if anchor_contract_from_plan:
            retrieval_anchor_contract = anchor_contract_from_plan
    retrieval_anchor_contract = _normalize_retrieval_anchor_contract(
        retrieval_anchor_contract
    )
    contract_lexical_calibration_active = any(
        is_contract_lexical_calibration_plan(item)
        for item in query_plan
        if isinstance(item, dict)
    )
    suppressed_foundation_branches = [
        item for item in query_plan if is_dedicated_foundation_query_branch(item)
    ]
    if suppressed_foundation_branches:
        query_plan = [
            item for item in query_plan if not is_dedicated_foundation_query_branch(item)
        ]
        log_event(
            "SCIENCE",
            "broad_pool_foundation_query_branches_suppressed",
            count=len(suppressed_foundation_branches),
            branches=[
                str(item.get("branch") or item.get("query_branch") or "")
                for item in suppressed_foundation_branches
            ],
            reason="Historical L1 retrieval requires a sub-hypothesis foundation contract.",
        )
    if not query_plan:
        query_plan = [{"branch": "primary", "query": query}]
    current_v3_work_item_plan = any(
        isinstance(plan, Mapping)
        and isinstance(plan.get("retrieval_work_item_v3"), Mapping)
        and (
            str(plan.get("schema_version") or "") == "retrieval_task_spec_v3"
            or str(
                (plan.get("retrieval_spec_v3") or {}).get("schema_version")
                if isinstance(plan.get("retrieval_spec_v3"), Mapping)
                else ""
            ) == "retrieval_task_spec_v3"
        )
        for plan in query_plan
    )
    if current_v3_work_item_plan:
        # Every provider that executes an active V3 work item must return a
        # ProviderOutcomeV3 through the scope-preserving V3 dispatcher.  Do
        # not send the same plan through legacy/generic provider branches and
        # infer their semantics afterwards.
        v3_outcome_providers = {"openalex", "semantic_scholar"}
        excluded_untyped_providers = [
            provider for provider in selected if provider not in v3_outcome_providers
        ]
        selected = [
            provider for provider in selected if provider in v3_outcome_providers
        ]
        if excluded_untyped_providers:
            log_event(
                "SCIENCE",
                "v3_untyped_provider_route_not_selected",
                excluded_providers=excluded_untyped_providers,
                reason="current_v3_work_item_requires_typed_provider_outcomes",
            )
    query_contamination_audits = [
        audit_subhypothesis_query_contamination(
            item.get("query") or query,
            candidate_alignment_contract,
            plan=item,
            branch=str(item.get("branch") or item.get("query_branch") or ""),
        )
        for item in query_plan
        if isinstance(item, dict)
    ]
    if not query_contamination_audits:
        query_contamination_audits = [
            audit_subhypothesis_query_contamination(
                query,
                candidate_alignment_contract,
                branch="primary",
            )
        ]
    query_audit_execution_summary: dict[str, Any] = {
        "raw_provider_queries_blocked_by_audit": 0,
        "high_risk_declared_input_missing_queries": 0,
        "same_round_repair_attempted": 0,
        "same_round_repair_applied": 0,
        "same_round_repair_failed": 0,
        "project_background_demoted_query_branches": 0,
        "raw_blocked_samples": [],
        "same_round_repair_samples": [],
        "same_round_repair_failure_samples": [],
    }

    def audit_missing_declared_input(audit: dict[str, Any]) -> bool:
        return bool(
            audit.get("declared_input_required_for_branch")
            and not audit.get(
                "declared_input_or_non_baseline_comparison_terms_present_in_query"
            )
        )

    def append_query_audit_sample(field: str, payload: dict[str, Any]) -> None:
        samples = query_audit_execution_summary.get(field)
        if isinstance(samples, list) and len(samples) < 4:
            samples.append(payload)

    if query_plan and query_contamination_audits:
        audited_query_plan: list[dict[str, Any]] = []
        for index, item in enumerate(query_plan):
            if not isinstance(item, dict):
                continue
            plan = dict(item)
            audit = (
                query_contamination_audits[index]
                if index < len(query_contamination_audits)
                and isinstance(query_contamination_audits[index], dict)
                else {}
            )
            if audit:
                plan["query_contamination_audit"] = dict(audit)
                if is_contract_lexical_calibration_plan(plan):
                    # Calibration is intentionally a small object-plus-axis
                    # probe. Recompiling it from every structured contract
                    # module is exactly how a planned calibration previously
                    # turned into a base-query/generic branch. The axis gate
                    # has already approved this contract; only provider
                    # syntax lowering is allowed below dispatch.
                    planned_query = normalize_space(str(plan.get("query") or ""))
                    plan["planned_query"] = planned_query
                    plan["query_fingerprint"] = str(
                        plan.get("query_fingerprint")
                        or query_execution_fingerprint(planned_query)
                    )
                    plan["strict_query_plan_execution"] = True
                    plan["query_execution_consistency_policy"] = (
                        "exact_fingerprint_or_provider_syntax_lowering_without_topical_token_change"
                    )
                    plan["provider_query_executed"] = True
                    plan["query_audit_recompile_suppressed"] = True
                    audited_query_plan.append(plan)
                    continue
                missing_required_input = audit_missing_declared_input(audit)
                high_risk_declared_input_missing = bool(
                    missing_required_input
                    and audit.get("query_contamination_risk") == "high"
                )
                repaired_query = normalize_space(str(audit.get("recompiled_query") or ""))
                repair_valid = bool(audit.get("recompiled_query_valid_for_sh"))
                repair_validation_audit: dict[str, Any] = {}
                if high_risk_declared_input_missing:
                    query_audit_execution_summary[
                        "high_risk_declared_input_missing_queries"
                    ] = (
                        int(
                            query_audit_execution_summary.get(
                                "high_risk_declared_input_missing_queries"
                            )
                            or 0
                        )
                        + 1
                    )
                    query_audit_execution_summary[
                        "raw_provider_queries_blocked_by_audit"
                    ] = (
                        int(
                            query_audit_execution_summary.get(
                                "raw_provider_queries_blocked_by_audit"
                            )
                            or 0
                        )
                        + 1
                    )
                    plan["provider_raw_query_executed"] = False
                    plan["query_audit_blocked_raw_provider_execution"] = True
                    plan["provider_raw_query_blocked_reason"] = (
                        "high_risk_declared_input_missing"
                    )
                    append_query_audit_sample(
                        "raw_blocked_samples",
                        {
                            "branch": plan.get("branch") or plan.get("query_branch"),
                            "raw_query": str(plan.get("query") or query)[:180],
                            "missing_declared_input_terms": list(
                                audit.get("missing_declared_input_terms") or []
                            )[:8],
                        },
                    )
                if missing_required_input and repaired_query and repair_valid:
                    query_audit_execution_summary["same_round_repair_attempted"] = (
                        int(query_audit_execution_summary.get("same_round_repair_attempted") or 0)
                        + 1
                    )
                    repair_plan = dict(plan)
                    repair_plan["query"] = repaired_query
                    repair_validation_audit = audit_subhypothesis_query_contamination(
                        repaired_query,
                        candidate_alignment_contract,
                        plan=repair_plan,
                        branch=str(plan.get("branch") or plan.get("query_branch") or ""),
                    )
                    repair_second_pass_valid = bool(
                        repair_validation_audit.get("query_valid_for_sh") is not False
                        and repair_validation_audit.get("provider_query_executed") is not False
                    )
                    plan["query_repair_validation_audit"] = dict(repair_validation_audit)
                else:
                    repair_second_pass_valid = False
                if missing_required_input and repaired_query and repair_valid and repair_second_pass_valid:
                    plan["source_query_before_declared_input_repair"] = str(
                        plan.get("query") or query
                    )
                    plan["query"] = repaired_query
                    plan["declared_input_query_repair_applied"] = True
                    plan["same_round_query_repair_applied"] = True
                    plan["provider_query_repaired_before_dispatch"] = True
                    plan["provider_query_executed"] = True
                    query_audit_execution_summary["same_round_repair_applied"] = (
                        int(query_audit_execution_summary.get("same_round_repair_applied") or 0)
                        + 1
                    )
                    append_query_audit_sample(
                        "same_round_repair_samples",
                        {
                            "branch": plan.get("branch") or plan.get("query_branch"),
                            "repaired_query": repaired_query[:180],
                            "declared_input_terms_present": list(
                                repair_validation_audit.get(
                                    "declared_input_or_non_baseline_comparison_terms_present_in_query"
                                )
                                or []
                            )[:8],
                        },
                    )
                elif missing_required_input and (not repaired_query or not repair_valid or not repair_second_pass_valid):
                    plan["provider_query_executed"] = False
                    plan["query_execution_blocked_reason"] = (
                        str(
                            (repair_validation_audit or {}).get("provider_suppressed_reason")
                            or audit.get("provider_suppressed_reason")
                            or "repair_failed_declared_input_scientific_edge_validation"
                        )
                    )
                    plan["query_execution_policy"] = (
                        "high_risk_missing_declared_input_raw_query_blocked_until_repair_validates"
                        if high_risk_declared_input_missing
                        else "declared_input_terms_must_survive_non_background_query_branch"
                    )
                    query_audit_execution_summary["same_round_repair_failed"] = (
                        int(query_audit_execution_summary.get("same_round_repair_failed") or 0)
                        + 1
                    )
                    append_query_audit_sample(
                        "same_round_repair_failure_samples",
                        {
                            "branch": plan.get("branch") or plan.get("query_branch"),
                            "raw_query": str(plan.get("query") or query)[:180],
                            "recompiled_query": repaired_query[:180],
                            "reason": plan["query_execution_blocked_reason"],
                        },
                    )
                elif audit.get("provider_query_executed") is False:
                    plan["provider_query_executed"] = False
                    plan["query_execution_blocked_reason"] = str(
                        audit.get("provider_suppressed_reason")
                        or "missing_declared_input_after_query_repair"
                    )
                    plan["query_execution_policy"] = (
                        "declared_input_terms_must_survive_non_background_query_branch"
                    )
                if audit.get("branch_demoted_to_project_background_query"):
                    plan["admission_scope"] = "project_background_only"
                    plan["counts_toward_gate"] = False
                    plan["counts_toward_corpus_target"] = False
                    plan["excluded_from_sh_gap_synthesis"] = True
                    query_audit_execution_summary[
                        "project_background_demoted_query_branches"
                    ] = (
                        int(
                            query_audit_execution_summary.get(
                                "project_background_demoted_query_branches"
                            )
                            or 0
                        )
                        + 1
                    )
            audited_query_plan.append(plan)
        if audited_query_plan:
            query_plan = audited_query_plan
    query_contamination_summary = summarize_query_contamination_audits(
        query_contamination_audits
    )
    for audit in query_contamination_audits:
        if not isinstance(audit, dict):
            continue
        log_event(
            "SCIENCE",
            "subhypothesis_query_contamination_audit",
            project_id=project_id or audit.get("project_id"),
            sub_hypothesis_id=sub_hypothesis_id or audit.get("sub_hypothesis_id"),
            branch=audit.get("branch"),
            raw_query=str(audit.get("raw_query") or "")[:260],
            protected_phrase_count=audit.get("protected_phrase_count"),
            standalone_low_signal_terms=list(audit.get("standalone_low_signal_terms") or [])[:24],
            required_object_anchor_hits_in_query=list(
                audit.get("required_object_anchor_hits_in_query") or []
            )[:16],
            raw_query_scientific_edge_valid=bool(
                audit.get("raw_query_scientific_edge_valid")
            ),
            recompiled_query_scientific_edge_valid=bool(
                audit.get("recompiled_query_scientific_edge_valid")
            ),
            object_edge_required=bool(audit.get("object_edge_required")),
            method_or_readout_object_anchor_demotions=list(
                audit.get("method_or_readout_object_anchor_demotions") or []
            )[:16],
            object_edge_exhausted_by_method_or_readout_demotions=bool(
                audit.get("object_edge_exhausted_by_method_or_readout_demotions")
            ),
            optimizer_query_scientific_edge_required=bool(
                audit.get("optimizer_query_scientific_edge_required")
            ),
            optimizer_scientific_edge_blocked=bool(
                audit.get("optimizer_scientific_edge_blocked")
            ),
            modifier_only_or_method_only_query=bool(
                audit.get("modifier_only_or_method_only_query")
            ),
            scientific_edge_blocked_reason=str(
                audit.get("scientific_edge_blocked_reason") or ""
            ),
            declared_input_required=bool(audit.get("declared_input_required_for_branch")),
            declared_input_terms=list(audit.get("declared_input_terms") or [])[:16],
            declared_input_terms_present=list(
                audit.get("declared_input_terms_present_in_query") or []
            )[:16],
            non_baseline_comparison_terms_present=list(
                audit.get("non_baseline_comparison_terms_present_in_query") or []
            )[:16],
            baseline_or_comparator_terms_present=list(
                audit.get("baseline_or_comparator_terms_present_in_query") or []
            )[:16],
            baseline_only_declared_input_match=bool(
                audit.get("baseline_only_declared_input_match")
            ),
            query_valid_for_sh=bool(audit.get("query_valid_for_sh")),
            recompiled_query_valid_for_sh=bool(audit.get("recompiled_query_valid_for_sh")),
            template_modifier_terms=list(audit.get("template_modifier_terms") or [])[:24],
            excluded_scope_terms_present=list(audit.get("excluded_scope_terms_present") or [])[:24],
            sibling_scope_terms_present=list(audit.get("sibling_scope_terms_present") or [])[:24],
            query_contamination_risk=audit.get("query_contamination_risk"),
            repair_action=audit.get("repair_action"),
            recompiled_query=str(audit.get("recompiled_query") or "")[:260],
            provider_query_executed=bool(audit.get("provider_query_executed") is not False),
            provider_suppressed_reason=str(audit.get("provider_suppressed_reason") or ""),
            branch_demoted_to_project_background_query=bool(
                audit.get("branch_demoted_to_project_background_query")
            ),
        )
    audit_by_branch = {
        str(item.get("branch") or ""): item
        for item in query_contamination_audits
        if isinstance(item, dict)
    }
    repaired_or_executable_query_plan: list[dict[str, Any]] = []
    suppressed_query_branches: list[dict[str, Any]] = []
    for plan in query_plan:
        if not isinstance(plan, dict):
            continue
        branch = str(plan.get("branch") or plan.get("query_branch") or "")
        repair_validation_audit = (
            plan.get("query_repair_validation_audit")
            if isinstance(plan.get("query_repair_validation_audit"), dict)
            else {}
        )
        audit = repair_validation_audit or audit_by_branch.get(branch)
        if not audit:
            audit = audit_subhypothesis_query_contamination(
                plan.get("query") or query,
                candidate_alignment_contract,
                plan=plan,
                branch=branch,
            )
        if audit.get("provider_query_executed") is False:
            suppressed_query_branches.append({
                "branch": branch,
                "query": str(plan.get("query") or "")[:260],
                "reason": str(audit.get("provider_suppressed_reason") or "query_invalid_for_sh"),
                "scientific_edge_blocked_reason": str(
                    audit.get("scientific_edge_blocked_reason") or ""
                ),
                "optimizer_query_scientific_edge_required": bool(
                    audit.get("optimizer_query_scientific_edge_required")
                ),
                "method_or_readout_object_anchor_demotions": list(
                    audit.get("method_or_readout_object_anchor_demotions") or []
                )[:8],
                "missing_declared_input_terms": list(audit.get("missing_declared_input_terms") or [])[:16],
            })
            continue
        repaired = dict(plan)
        repaired["query_valid_for_sh"] = bool(audit.get("query_valid_for_sh") is not False)
        repaired["declared_input_required_for_branch"] = bool(
            audit.get("declared_input_required_for_branch")
        )
        repaired["declared_input_terms"] = list(audit.get("declared_input_terms") or [])[:16]
        if audit.get("branch_demoted_to_project_background_query") is True:
            repaired["query_scope"] = "project_background_only"
            repaired["query_requires_declared_input"] = False
        if (
            audit.get("repair_action") == "recompile_from_structured_anchor_groups"
            and str(audit.get("recompiled_query") or "").strip()
            and audit.get("recompiled_query_valid_for_sh") is not False
        ):
            repaired["source_query_before_repair"] = str(plan.get("query") or "")
            repaired["query"] = str(audit.get("recompiled_query") or "")
            repaired["query_repair_applied"] = True
            repaired["query_repair_action"] = "recompile_from_structured_anchor_groups"
        repaired_or_executable_query_plan.append(repaired)
    if suppressed_query_branches:
        log_event(
            "SCIENCE",
            "subhypothesis_provider_query_branches_suppressed",
            project_id=project_id,
            sub_hypothesis_id=sub_hypothesis_id,
            suppressed=len(suppressed_query_branches),
            branches=suppressed_query_branches[:12],
            reason="provider_query_audit_scientific_edge_or_declared_input_block",
        )
    query_plan = repaired_or_executable_query_plan
    provider_query_dispatch_suppressed = bool(not query_plan)
    query_contamination_summary.update(
        {
            "raw_provider_queries_blocked_by_audit": int(
                query_audit_execution_summary.get("raw_provider_queries_blocked_by_audit") or 0
            ),
            "high_risk_declared_input_missing_queries": int(
                query_audit_execution_summary.get("high_risk_declared_input_missing_queries") or 0
            ),
            "same_round_repair_attempted": int(
                query_audit_execution_summary.get("same_round_repair_attempted") or 0
            ),
            "same_round_repair_applied": int(
                query_audit_execution_summary.get("same_round_repair_applied") or 0
            ),
            "same_round_repair_failed": int(
                query_audit_execution_summary.get("same_round_repair_failed") or 0
            ),
            "project_background_demoted_query_branches": int(
                query_audit_execution_summary.get(
                    "project_background_demoted_query_branches"
                )
                or 0
            ),
            "provider_suppressed_query_branches": len(suppressed_query_branches),
            "provider_executable_query_branches": len(query_plan),
            "provider_query_dispatch_suppressed": provider_query_dispatch_suppressed,
        }
    )
    log_event(
        "SCIENCE",
        "subhypothesis_query_audit_summary",
        project_id=project_id,
        sub_hypothesis_id=sub_hypothesis_id,
        audited_queries=int(query_contamination_summary.get("audited_queries") or 0),
        query_contamination_risk=query_contamination_summary.get("query_contamination_risk"),
        high_risk_queries=int(query_contamination_summary.get("high_risk_queries") or 0),
        scientific_edge_invalid_queries=int(
            query_contamination_summary.get("scientific_edge_invalid_queries") or 0
        ),
        optimizer_scientific_edge_blocked_queries=int(
            query_contamination_summary.get("optimizer_scientific_edge_blocked_queries") or 0
        ),
        modifier_or_method_only_blocked_queries=int(
            query_contamination_summary.get("modifier_or_method_only_blocked_queries") or 0
        ),
        method_or_readout_object_anchor_demotions=list(
            query_contamination_summary.get("method_or_readout_object_anchor_demotions")
            or []
        )[:16],
        scientific_edge_blocked_reasons=list(
            query_contamination_summary.get("scientific_edge_blocked_reasons") or []
        )[:8],
        declared_input_missing_queries=int(
            query_contamination_summary.get("declared_input_missing_queries") or 0
        ),
        high_risk_declared_input_missing_queries=int(
            query_contamination_summary.get("high_risk_declared_input_missing_queries") or 0
        ),
        raw_provider_queries_blocked_by_audit=int(
            query_contamination_summary.get("raw_provider_queries_blocked_by_audit") or 0
        ),
        same_round_repair_attempted=int(
            query_contamination_summary.get("same_round_repair_attempted") or 0
        ),
        same_round_repair_applied=int(
            query_contamination_summary.get("same_round_repair_applied") or 0
        ),
        same_round_repair_failed=int(
            query_contamination_summary.get("same_round_repair_failed") or 0
        ),
        provider_executable_query_branches=len(query_plan),
        provider_suppressed_query_branches=len(suppressed_query_branches),
        provider_query_dispatch_suppressed=provider_query_dispatch_suppressed,
        raw_blocked_samples=list(
            query_audit_execution_summary.get("raw_blocked_samples") or []
        )[:3],
        same_round_repair_samples=list(
            query_audit_execution_summary.get("same_round_repair_samples") or []
        )[:3],
        same_round_repair_failure_samples=list(
            query_audit_execution_summary.get("same_round_repair_failure_samples")
            or []
        )[:3],
    )
    ranking_query = expanded_ranking_query(query, domain, query_plan)
    quotas = normalize_stratified_layer_quotas(layer_quotas, max_results=max_results)
    allowed_preprint_layers = normalize_preprint_source_layers(preprint_layers)
    # Preprints are an explicitly requested horizon-scanning lane.  They do
    # not receive an implicit quota and never displace peer-reviewed evidence.
    preprint_exploration_buffer_active = bool(
        allowed_preprint_layers and int(quotas.get("L3_preprint") or 0) > 0
    )
    preprint_exploration_buffer_limit = int(quotas.get("L3_preprint") or 0)
    required_preprint_anchor_groups = retrieval_anchor_group_forms(
        retrieval_anchor_contract
    )
    normalized_retrieval_mode = str(retrieval_mode or "broad_discovery").strip().lower()
    if normalized_retrieval_mode not in {
        "broad_discovery",
        "l1_foundational_bridge",
        "l2_top_latest",
        "socrates_targeted_evidence",
    }:
        normalized_retrieval_mode = "broad_discovery"
    effective_anchor_contract = (
        retrieval_anchor_contract
        if isinstance(retrieval_anchor_contract, dict) and retrieval_anchor_contract
        else (candidate_alignment_contract if isinstance(candidate_alignment_contract, dict) else None)
    )
    if (
        isinstance(effective_anchor_contract, dict)
        and isinstance(candidate_alignment_contract, dict)
        and candidate_alignment_contract
        and effective_anchor_contract is not candidate_alignment_contract
    ):
        effective_anchor_contract = {
            **candidate_alignment_contract,
            **effective_anchor_contract,
            "explicit_exclusion_terms": list(
                candidate_alignment_contract.get("explicit_exclusion_terms") or []
            ),
            "excluded_nearby_objects": list(
                candidate_alignment_contract.get("excluded_nearby_objects") or []
            ),
            "query_forbidden_terms": list(
                candidate_alignment_contract.get("query_forbidden_terms") or []
            ),
            "subhypothesis_scope_policy": dict(
                candidate_alignment_contract.get("subhypothesis_scope_policy") or {}
            ),
            "query_forbidden_term_variants": dict(
                candidate_alignment_contract.get("query_forbidden_term_variants") or {}
            ),
            "provider_not_exclusion_variants": dict(
                candidate_alignment_contract.get("provider_not_exclusion_variants") or {}
            ),
        }
    preprint_anchor_policy = build_preprint_anchor_policy(
        query=query,
        research_question_card=normalized_question_card,
        candidate_alignment_contract=candidate_alignment_contract,
        retrieval_anchor_contract=retrieval_anchor_contract,
    )
    targeted_admission: dict[str, Any] = {
        "enabled": bool(candidate_alignment_contract) or bool(retrieval_anchor_contract),
        "requested_evidence_kind": str(requested_evidence_kind or ""),
        "auxiliary_pre_fulltext_limit": (
            int(SCIENCE_SUBHYPOTHESIS_AUXILIARY_PRE_FULLTEXT_LIMIT)
            if SCIENCE_SUBHYPOTHESIS_AUXILIARY_PRE_FULLTEXT_LAYER_LIMIT_ENABLED
            else 0
        ),
        "auxiliary_pre_fulltext_limit_enabled": bool(
            SCIENCE_SUBHYPOTHESIS_AUXILIARY_PRE_FULLTEXT_LAYER_LIMIT_ENABLED
        ),
        "auxiliary_pre_fulltext_layer_policy": (
            "per_layer_l2_reserved_l4_not_starved"
            if SCIENCE_SUBHYPOTHESIS_AUXILIARY_PRE_FULLTEXT_LAYER_LIMIT_ENABLED
            else "disabled_unbounded"
        ),
        "auxiliary_pending_fulltext_admitted": 0,
        "auxiliary_pending_fulltext_retained": 0,
        "auxiliary_pending_fulltext_excluded_by_limit": 0,
        "auxiliary_pending_fulltext_admitted_by_layer": {},
        "auxiliary_pending_fulltext_retained_by_layer": {},
        "auxiliary_pending_fulltext_excluded_by_limit_by_layer": {},
        "auxiliary_pending_fulltext_layer_limits": {},
        "coarse_prefilter_evaluated": 0,
        "coarse_prefilter_accepted": 0,
        "coarse_prefilter_rejected": 0,
        "deep_alignment_candidate_limit": (
            normalize_deep_alignment_candidate_limit(deep_alignment_candidate_limit)
            if candidate_alignment_contract
            else 0
        ),
        "deep_pool_selected": 0,
        "deep_pool_by_layer": {},
        "evaluated": 0,
        "accepted": 0,
        "rejected": 0,
        "fragment_anchor_evaluated": 0,
        "fragment_anchor_rejected": 0,
        "rejection_reasons": {},
        "coarse_prefilter_rejection_reasons": {},
        "strict_admission_rejection_reasons": {},
        "coarse_prefilter_rejection_samples": [],
        "strict_admission_rejection_samples": [],
        "coarse_prefilter_object_anchor_policy_mode_counts": {},
        "coarse_prefilter_strong_object_anchors": [],
        "coarse_prefilter_strong_object_hits": [],
        "coarse_prefilter_semantic_equivalent_object_hits": [],
        "coarse_prefilter_related_context_object_hits": [],
        "coarse_prefilter_auxiliary_object_hits": [],
        "coarse_prefilter_matched_axis_counts": {},
        "coarse_prefilter_matched_axes": [],
        "coarse_prefilter_component_bridge_modifier_only_matches": 0,
        "coarse_prefilter_component_bridge_support_missing": 0,
        "coarse_prefilter_scope_forbidden_expanded_hits": 0,
        "coarse_prefilter_memo_hits": 0,
        "coarse_prefilter_local_cache_hits": 0,
        "strict_admission_memo_hits": 0,
        "strict_admission_local_cache_hits": 0,
        "query_pollution_diagnostics": dict(query_contamination_summary),
        "cross_round_duplicates_excluded": 0,
    }
    excluded_candidate_key_set = {
        str(item).strip() for item in (exclude_candidate_keys or []) if str(item).strip()
    }
    cross_round_duplicate_keys: set[str] = set()
    coarse_prefilter_cache: dict[str, dict[str, Any]] = {}
    auxiliary_pending_candidate_keys_by_layer: dict[str, set[str]] = {}

    def auxiliary_pending_limit_for_layer(layer_name: str) -> int:
        if not SCIENCE_SUBHYPOTHESIS_AUXILIARY_PRE_FULLTEXT_LAYER_LIMIT_ENABLED:
            return 0
        configured_limit = int(SCIENCE_SUBHYPOTHESIS_AUXILIARY_PRE_FULLTEXT_LIMIT)
        if configured_limit <= 0:
            return 0
        normalized_layer = str(layer_name or "").strip()
        # L2 is a protected frontier/top-latest lane, but it should not
        # consume the entire auxiliary full-text audit pool before L4 gets a
        # chance to retain regular/contextual experimental papers.  L4 keeps
        # the configured cap; L2 receives a smaller per-layer reserve.
        if normalized_layer == SEMANTIC_SCHOLAR_L2_TOP_LATEST_LAYER:
            return min(configured_limit, 4)
        return configured_limit

    def increment_layer_count(container: dict[str, Any], layer_name: str) -> None:
        normalized_layer = str(layer_name or "unassigned")
        layer_counts = container
        layer_counts[normalized_layer] = int(layer_counts.get(normalized_layer) or 0) + 1

    def top_count_items(container: Any, *, limit: int = 8) -> dict[str, int]:
        if not isinstance(container, dict):
            return {}
        pairs = sorted(
            (
                (str(key), int(value or 0))
                for key, value in container.items()
            ),
            key=lambda item: (-item[1], item[0]),
        )
        return {key: value for key, value in pairs[:limit]}

    def record_targeted_rejection(
        reason: str,
        *,
        stage: str,
        candidate: dict[str, Any] | None = None,
        assessment: dict[str, Any] | None = None,
    ) -> None:
        normalized_reason = str(reason or "alignment_rejected")
        reasons = targeted_admission["rejection_reasons"]
        reasons[normalized_reason] = int(reasons.get(normalized_reason) or 0) + 1
        stage_reasons = targeted_admission[
            "coarse_prefilter_rejection_reasons"
            if stage == "coarse"
            else "strict_admission_rejection_reasons"
        ]
        stage_reasons[normalized_reason] = int(
            stage_reasons.get(normalized_reason) or 0
        ) + 1
        sample_key = (
            "coarse_prefilter_rejection_samples"
            if stage == "coarse"
            else "strict_admission_rejection_samples"
        )
        samples = targeted_admission.get(sample_key)
        if isinstance(candidate, dict) and isinstance(samples, list) and len(samples) < 8:
            assessment_payload = assessment if isinstance(assessment, dict) else {}
            samples.append(
                {
                    "result_index": candidate.get("result_index"),
                    "title": str(candidate.get("title") or "")[:180],
                    "reason": normalized_reason[:300],
                    "layer": candidate.get("stratified_layer"),
                    "query_branch": candidate.get("query_branch"),
                    "object_anchor_policy_mode": assessment_payload.get("object_anchor_policy_mode"),
                    "strong_object_anchors": list(assessment_payload.get("strong_object_anchors") or [])[:8],
                    "strong_object_hits": list(assessment_payload.get("strong_object_hits") or [])[:8],
                    "semantic_equivalent_object_hits": list(assessment_payload.get("semantic_equivalent_object_hits") or [])[:8],
                    "related_context_object_hits": list(assessment_payload.get("related_context_object_hits") or [])[:8],
                    "auxiliary_object_hits": list(assessment_payload.get("auxiliary_object_hits") or [])[:8],
                    "component_bridge_object_hits": list(assessment_payload.get("component_bridge_object_hits") or [])[:8],
                    "component_bridge_support_hits": list(assessment_payload.get("component_bridge_support_hits") or [])[:8],
                    "component_bridge_modifier_only_hits": list(assessment_payload.get("component_bridge_modifier_only_hits") or [])[:8],
                    "expanded_exclusion_hits": list(assessment_payload.get("expanded_exclusion_hits") or [])[:8],
                    "effective_expanded_exclusion_hits": list(assessment_payload.get("effective_expanded_exclusion_hits") or [])[:8],
                    "scope_conflict_with_positive_anchor_hits": list(assessment_payload.get("scope_conflict_with_positive_anchor_hits") or [])[:8],
                    "matched_axes": list(assessment_payload.get("matched_axes") or [])[:8],
                }
            )

    def record_coarse_prefilter_anchor_diagnostic(assessment: dict[str, Any]) -> None:
        if not isinstance(assessment, dict):
            return
        mode = str(assessment.get("object_anchor_policy_mode") or "").strip()
        if mode:
            modes = targeted_admission["coarse_prefilter_object_anchor_policy_mode_counts"]
            modes[mode] = int(modes.get(mode) or 0) + 1

        def append_unique_limited(field: str, values: Any, *, limit: int = 16) -> None:
            target = targeted_admission[field]
            if not isinstance(target, list):
                return
            seen = {str(item).lower() for item in target}
            for raw in values or []:
                value = str(raw or "").strip()
                if not value or value.lower() in seen:
                    continue
                target.append(value)
                seen.add(value.lower())
                if len(target) >= limit:
                    break

        append_unique_limited(
            "coarse_prefilter_strong_object_anchors",
            assessment.get("strong_object_anchors"),
        )
        append_unique_limited(
            "coarse_prefilter_strong_object_hits",
            assessment.get("strong_object_hits"),
        )
        append_unique_limited(
            "coarse_prefilter_semantic_equivalent_object_hits",
            assessment.get("semantic_equivalent_object_hits"),
        )
        append_unique_limited(
            "coarse_prefilter_related_context_object_hits",
            assessment.get("related_context_object_hits"),
        )
        append_unique_limited(
            "coarse_prefilter_auxiliary_object_hits",
            assessment.get("auxiliary_object_hits"),
        )
        append_unique_limited(
            "coarse_prefilter_matched_axes",
            assessment.get("matched_axes"),
            limit=8,
        )
        if assessment.get("component_bridge_modifier_only_hits"):
            targeted_admission["coarse_prefilter_component_bridge_modifier_only_matches"] = (
                int(targeted_admission.get("coarse_prefilter_component_bridge_modifier_only_matches") or 0)
                + 1
            )
        if (
            str(assessment.get("reason_code") or "")
            == "COARSE_PREFILTER_COMPONENT_BRIDGE_SUPPORT_MISSING"
        ):
            targeted_admission["coarse_prefilter_component_bridge_support_missing"] = (
                int(targeted_admission.get("coarse_prefilter_component_bridge_support_missing") or 0)
                + 1
            )
        if assessment.get("effective_expanded_exclusion_hits"):
            targeted_admission["coarse_prefilter_scope_forbidden_expanded_hits"] = (
                int(targeted_admission.get("coarse_prefilter_scope_forbidden_expanded_hits") or 0)
                + 1
            )
        axis_counts = targeted_admission["coarse_prefilter_matched_axis_counts"]
        for axis in assessment.get("matched_axes") or []:
            axis_name = str(axis or "").strip()
            if axis_name:
                axis_counts[axis_name] = int(axis_counts.get(axis_name) or 0) + 1

    def admits_coarse_candidate(candidate: dict[str, Any]) -> bool:
        candidate_key = literature_result_unique_key(candidate)
        if candidate_key and candidate_key in excluded_candidate_key_set:
            if candidate_key not in cross_round_duplicate_keys:
                cross_round_duplicate_keys.add(candidate_key)
                targeted_admission["cross_round_duplicates_excluded"] = len(cross_round_duplicate_keys)
            return False
        if not isinstance(candidate_alignment_contract, dict) or not candidate_alignment_contract:
            if project_id and sub_hypothesis_id:
                targeted_admission["coarse_prefilter_rejected"] += 1
                record_targeted_rejection(
                    "V3_SLOT_CANDIDATE_SCOPE_REQUIRED",
                    stage="coarse",
                    candidate=candidate,
                    assessment=_v3_slot_scope_required_assessment({}),
                )
                return False
            return True
        cache_key = _coarse_prefilter_memo_key(candidate, candidate_alignment_contract)
        assessment = coarse_prefilter_cache.get(cache_key)
        computed_now = False
        if isinstance(assessment, dict):
            targeted_admission["coarse_prefilter_local_cache_hits"] = (
                int(targeted_admission.get("coarse_prefilter_local_cache_hits") or 0)
                + 1
            )
        else:
            memo_assessment = _bounded_memo_get(
                COARSE_PREFILTER_MEMO,
                COARSE_PREFILTER_MEMO_LOCK,
                cache_key,
            )
            if isinstance(memo_assessment, dict):
                assessment = dict(memo_assessment)
                assessment["coarse_prefilter_memo_hit"] = True
                assessment["coarse_prefilter_memo_scope"] = "paper_sh_contract"
                coarse_prefilter_cache[cache_key] = dict(assessment)
                targeted_admission["coarse_prefilter_memo_hits"] = (
                    int(targeted_admission.get("coarse_prefilter_memo_hits") or 0)
                    + 1
                )
            else:
                computed_now = True
        if computed_now:
            assessment = coarse_subhypothesis_candidate_prefilter(
                candidate,
                candidate_alignment_contract,
            )
            assessment = dict(assessment)
            assessment["coarse_prefilter_memo_hit"] = False
            assessment["coarse_prefilter_memo_scope"] = "computed"
            coarse_prefilter_cache[cache_key] = dict(assessment)
            _bounded_memo_put(
                COARSE_PREFILTER_MEMO,
                COARSE_PREFILTER_MEMO_LOCK,
                cache_key,
                assessment,
                max_size=COARSE_PREFILTER_MEMO_MAX,
            )
            targeted_admission["coarse_prefilter_evaluated"] += 1
            record_coarse_prefilter_anchor_diagnostic(assessment)
        if assessment.get("passes"):
            if computed_now:
                targeted_admission["coarse_prefilter_accepted"] += 1
            return True
        if computed_now:
            targeted_admission["coarse_prefilter_rejected"] += 1
            reason = str(assessment.get("reason_code") or "coarse_prefilter_rejected")
            record_targeted_rejection(reason, stage="coarse", candidate=candidate, assessment=assessment)
        return False

    def admits_targeted_candidate(
        candidate: dict[str, Any],
        *,
        record_metrics: bool = True,
        allow_aligned_background: bool = False,
        admission_level: str = "import",
        requested_evidence_kinds_override: list[str] | tuple[str, ...] | None = None,
    ) -> bool:
        """Reject off-branch candidates before layer selection/import work."""
        if not isinstance(candidate_alignment_contract, dict) or not candidate_alignment_contract:
            if project_id and sub_hypothesis_id:
                if record_metrics:
                    targeted_admission["evaluated"] += 1
                    targeted_admission["rejected"] += 1
                    record_targeted_rejection(
                        "V3_SLOT_CANDIDATE_SCOPE_REQUIRED",
                        stage="strict",
                        candidate=candidate,
                        assessment=_v3_slot_scope_required_assessment({}),
                    )
                return False
            if (
                normalized_retrieval_mode == "socrates_targeted_evidence"
                and isinstance(retrieval_anchor_contract, dict)
                and retrieval_anchor_contract.get("valid")
            ):
                if record_metrics:
                    targeted_admission["evaluated"] += 1
                    targeted_admission["rejected"] += 1
                    record_targeted_rejection(
                        "missing_candidate_alignment_contract",
                        stage="strict",
                        candidate=candidate,
                    )
                return False
            return True
        admitted, assessment, _cached = evaluate_candidate_targeted_alignment_gate(
            candidate,
            alignment_contract=candidate_alignment_contract,
            requested_evidence_kind=(
                "" if admission_level == "import" else requested_evidence_kind
            ),
            requested_evidence_kinds=requested_evidence_kinds_override,
            admission_level=admission_level,
        )
        if record_metrics and _cached:
            memo_scope = str(
                assessment.get("alignment_admission_memo_scope") or ""
            ).strip()
            if memo_scope == "paper_sh_contract":
                targeted_admission["strict_admission_memo_hits"] = (
                    int(targeted_admission.get("strict_admission_memo_hits") or 0)
                    + 1
                )
            elif memo_scope == "candidate_record":
                targeted_admission["strict_admission_local_cache_hits"] = (
                    int(targeted_admission.get("strict_admission_local_cache_hits") or 0)
                    + 1
                )
        # L0 is an explicitly background/review lane.  Its aligned papers are
        # intentionally import-eligible but never CORE, so a core-only gate
        # would make the L0 minimum impossible to satisfy.  This exception is
        # layer-scoped by the caller and is never used for L2/L4 or Socrates
        # direct-evidence retrieval.
        if not admitted and allow_aligned_background:
            corpus = (
                assessment.get("corpus_admission")
                if isinstance(assessment.get("corpus_admission"), dict)
                else {}
            )
            paper_genre = (
                assessment.get("paper_genre")
                if isinstance(assessment.get("paper_genre"), dict)
                else {}
            )
            evidence_role = str(assessment.get("evidence_role") or "").strip().lower()
            evidence_lane = str(assessment.get("evidence_lane") or "").strip()
            verdict = str(assessment.get("verdict") or "").strip().upper()
            corpus_reason = str(
                assessment.get("corpus_admission_reason")
                or corpus.get("corpus_admission_reason")
                or ""
            ).strip()
            corpus_admitted = bool(
                (
                    assessment.get("corpus_admitted") is True
                    or corpus.get("corpus_admitted") is True
                )
                and assessment.get("off_topic") is not True
                and corpus.get("off_topic") is not True
            )
            background_context_admitted = bool(
                (
                    assessment.get("import_eligible") is True
                    and evidence_lane == "BACKGROUND_REVIEW"
                )
                or (
                    corpus_admitted
                    and (
                        evidence_role == "background_review"
                        or evidence_lane == "BACKGROUND_REVIEW"
                        or verdict
                        in {
                            "BACKGROUND_OR_REVIEW_ADMITTED",
                            "CONTEXT_RELATED_NONCOUNTING",
                            "AUXILIARY_BACKGROUND_EVIDENCE",
                            "RELATED_NONCORE_ADMITTED",
                        }
                        or corpus_reason
                        in {
                            "context_review_or_boundary_background",
                            "strong_scientific_object_or_semantic_alias",
                            "evidence_path_partial_anchor",
                            "method_platform_context",
                        }
                        or paper_genre.get("is_review") is True
                    )
                )
            )
            if background_context_admitted:
                admitted = True
                assessment = {
                    **assessment,
                    "admission_tier": "BACKGROUND_CONTEXT",
                    "background_context_eligible": True,
                    "evidence_lane": evidence_lane or "BACKGROUND_REVIEW",
                    "evidence_role": evidence_role or "background_review",
                    "core_eligible": False,
                    "gate_counting_evidence": False,
                    "context_only_evidence": True,
                    "reason": (
                        assessment.get("reason")
                        or "Layer-A corpus/background review admission retained this L0 paper as non-core context."
                    ),
                }
                candidate["targeted_alignment_admission"] = dict(assessment)
        if record_metrics:
            targeted_admission["evaluated"] += 1
        if admitted:
            admission_tier = str(assessment.get("admission_tier") or "AUXILIARY_PENDING_FULLTEXT")
            candidate["targeted_admission_tier"] = admission_tier
            candidate["pending_full_text_verification"] = (
                admission_tier == "AUXILIARY_PENDING_FULLTEXT"
                or assessment.get("pending_full_text_verification") is True
            )
            candidate["selection_stage"] = "pre_import"
            candidate["direct_edge_candidate"] = bool(
                assessment.get("direct_edge_candidate")
            )
            candidate["direct_edge_confirmed"] = False
            if candidate["pending_full_text_verification"]:
                prefulltext_import_assessment = (
                    assessment.get("prefulltext_import_assessment")
                    if isinstance(
                        assessment.get("prefulltext_import_assessment"),
                        dict,
                    )
                    else {}
                )
                candidate["provisional_evidence_lane"] = str(
                    assessment.get("prefulltext_provisional_evidence_lane")
                    or prefulltext_import_assessment.get(
                        "provisional_evidence_lane"
                    )
                    or assessment.get("provisional_evidence_lane")
                    or assessment.get("evidence_lane")
                    or "PENDING_FULLTEXT_TYPE_DIRECTED_EVIDENCE"
                )
                candidate["detail_revalidation_required"] = True
            # Candidate-level alignment protects project/subhypothesis scope.
            # In Socrates direct-evidence mode, require an additional local
            # anchor-compatible text window before the candidate can consume a
            # slot/import.  This mirrors the source-bound query contract and
            # avoids using a broad paper-level match to repair a precise chain.
            if (
                normalized_retrieval_mode == "socrates_targeted_evidence"
                and isinstance(retrieval_anchor_contract, dict)
                and retrieval_anchor_contract.get("valid")
            ):
                compatible, fragment_assessment, _cached = evaluate_candidate_fragment_anchor_gate(
                    candidate,
                    retrieval_anchor_contract=retrieval_anchor_contract,
                )
                if record_metrics:
                    targeted_admission["fragment_anchor_evaluated"] += 1
                if not compatible:
                    if record_metrics:
                        targeted_admission["rejected"] += 1
                        targeted_admission["fragment_anchor_rejected"] += 1
                        reason = str(fragment_assessment.get("reason") or "fragment_anchor_rejected")
                        record_targeted_rejection(reason, stage="strict", candidate=candidate)
                    return False
            if record_metrics:
                targeted_admission["accepted"] += 1
                if admission_tier == "AUXILIARY_PENDING_FULLTEXT":
                    targeted_admission["auxiliary_pending_fulltext_admitted"] += 1
                    increment_layer_count(
                        targeted_admission["auxiliary_pending_fulltext_admitted_by_layer"],
                        str(candidate.get("stratified_layer") or candidate.get("target_layer") or "unassigned"),
                    )
            return True
        if record_metrics:
            targeted_admission["rejected"] += 1
        reason = str(assessment.get("reason") or "alignment_rejected")
        if record_metrics:
            record_targeted_rejection(reason, stage="strict", candidate=candidate, assessment=assessment)
        return False

    def retains_auxiliary_pending_candidate(candidate: dict[str, Any]) -> bool:
        if str(candidate.get("targeted_admission_tier") or "") != "AUXILIARY_PENDING_FULLTEXT":
            return True
        key = literature_result_unique_key(candidate)
        layer_name = str(
            candidate.get("stratified_layer")
            or candidate.get("target_layer")
            or "unassigned"
        )
        layer_limit = auxiliary_pending_limit_for_layer(layer_name)
        layer_keys = auxiliary_pending_candidate_keys_by_layer.setdefault(layer_name, set())
        if key in layer_keys:
            return True
        if (
            SCIENCE_SUBHYPOTHESIS_AUXILIARY_PRE_FULLTEXT_LAYER_LIMIT_ENABLED
            and layer_limit > 0
        ):
            targeted_admission["auxiliary_pending_fulltext_layer_limits"][layer_name] = (
                layer_limit
            )
        if (
            SCIENCE_SUBHYPOTHESIS_AUXILIARY_PRE_FULLTEXT_LAYER_LIMIT_ENABLED
            and layer_limit > 0
            and len(layer_keys) >= layer_limit
        ):
            targeted_admission["auxiliary_pending_fulltext_excluded_by_limit"] += 1
            increment_layer_count(
                targeted_admission["auxiliary_pending_fulltext_excluded_by_limit_by_layer"],
                layer_name,
            )
            record_targeted_rejection(
                "AUXILIARY_PENDING_FULLTEXT_POOL_LIMIT",
                stage="strict",
                candidate=candidate,
            )
            return False
        layer_keys.add(key)
        targeted_admission["auxiliary_pending_fulltext_retained"] = sum(
            len(keys) for keys in auxiliary_pending_candidate_keys_by_layer.values()
        )
        targeted_admission["auxiliary_pending_fulltext_retained_by_layer"] = {
            layer: len(keys)
            for layer, keys in sorted(auxiliary_pending_candidate_keys_by_layer.items())
        }
        return True

    provider_blocks: list[dict[str, Any]] = []
    selected_results: list[dict[str, Any]] = []
    aligned_reserve_candidates: list[dict[str, Any]] = []
    seen: set[str] = set()
    strata_reports: list[dict[str, Any]] = []
    layers = stratified_literature_layers(
        quotas,
        direct_evidence_mode=direct_evidence_mode,
    )
    active_targeted_layers = [
        str(layer.get("layer") or "")
        for layer in layers
        if int(layer.get("quota") or 0) > 0
        and str(layer.get("layer") or "") != "L1_milestone"
    ]
    deep_limit = int(targeted_admission.get("deep_alignment_candidate_limit") or 0)
    deep_layer_limits: dict[str, int] = {}
    if deep_limit and active_targeted_layers:
        base_per_layer = min(10, deep_limit // len(active_targeted_layers))
        remaining_deep = max(0, deep_limit - base_per_layer * len(active_targeted_layers))
        quota_total = sum(
            int(layer.get("quota") or 0)
            for layer in layers
            if str(layer.get("layer") or "") in active_targeted_layers
        )
        allocated = 0
        for position, layer_name in enumerate(active_targeted_layers):
            layer_quota = int(quotas.get(layer_name, 0))
            if position == len(active_targeted_layers) - 1:
                extra = max(0, remaining_deep - allocated)
            else:
                extra = (
                    remaining_deep * layer_quota // max(1, quota_total)
                )
                allocated += extra
            deep_layer_limits[layer_name] = base_per_layer + extra
        targeted_admission["deep_pool_limits_by_layer"] = dict(deep_layer_limits)
        log_event(
            "SCIENCE",
            "targeted_deep_alignment_budget",
            search_id=search_id,
            project_id=project_id,
            sub_hypothesis_id=sub_hypothesis_id,
            deep_alignment_candidate_limit=deep_limit,
            deep_pool_limits_by_layer=dict(deep_layer_limits),
            active_layers=list(active_targeted_layers),
            policy="audit_pool_expansion_only_alignment_and_claim_gates_unchanged",
        )

    # OpenAlex supplies broad peer-reviewed discovery for L0/L4.  PubMed
    # specialized retrieval is disabled by runtime policy because OpenAlex
    # already covers PubMed-indexed work while avoiding PubMed keyword-index
    # drift in non-biomedical sub-hypotheses.  L1 is supplied only by the
    # independent foundational-mechanism workflow.  L2 is a separate protected
    # layer: OpenAlex and Semantic Scholar each contribute
    # one bounded causal-topic pool, then one shared cross-domain qualifier
    # selects recent, primary, high-quality work.
    openalex_broad_enabled = (
        openalex_stratified_batch_required(selected, quotas)
        and normalized_retrieval_mode != "socrates_targeted_evidence"
        and not provider_query_dispatch_suppressed
    )
    sciencedirect_broad_enabled = (
        sciencedirect_stratified_batch_required(selected, quotas)
        and normalized_retrieval_mode != "socrates_targeted_evidence"
        and not provider_query_dispatch_suppressed
    )
    openalex_l2_enabled = (
        openalex_l2_top_latest_batch_required(quotas)
        and "openalex" in selected
        and not provider_query_dispatch_suppressed
    )
    semantic_scholar_compatibility_enabled = (
        semantic_scholar_stratified_batch_required(selected, quotas)
        and not provider_query_dispatch_suppressed
    )
    semantic_scholar_l2_enabled = (
        semantic_scholar_l2_top_latest_batch_required(quotas)
        and "semantic_scholar" in selected
        and not provider_query_dispatch_suppressed
    )
    semantic_scholar_provider_not_scheduled_reason = "no_L0_or_L4_compatibility_quota"
    semantic_scholar_active_circuit_skip = False
    semantic_scholar_active_circuit_retry_after = 0.0
    if "semantic_scholar" in selected and (
        semantic_scholar_compatibility_enabled or semantic_scholar_l2_enabled
    ):
        circuit_open, retry_after = semantic_scholar_circuit_open()
        if circuit_open:
            semantic_scholar_active_circuit_skip = True
            semantic_scholar_active_circuit_retry_after = retry_after
            semantic_scholar_compatibility_enabled = False
            semantic_scholar_l2_enabled = False
            semantic_scholar_provider_not_scheduled_reason = (
                "skip_semantic_scholar_due_to_active_circuit"
            )
            log_event(
                "SCIENCE",
                "semantic_scholar_skipped_due_to_active_circuit",
                project_id=project_id,
                sub_hypothesis_id=sub_hypothesis_id,
                search_id=search_id,
                retry_after_seconds=round(float(retry_after or 0.0), 2),
                skip_scope="current_process_run_provider_health",
                compatibility_batch_skipped=True,
                l2_supplement_skipped=True,
                reason="skip_semantic_scholar_due_to_active_circuit",
            )
    pubmed_enabled = (
        pubmed_stratified_batch_required(selected, quotas)
        and not provider_query_dispatch_suppressed
    )
    if shared_raw_candidate_pool_only:
        openalex_broad_enabled = False
        sciencedirect_broad_enabled = False
        openalex_l2_enabled = False
        semantic_scholar_compatibility_enabled = False
        semantic_scholar_l2_enabled = False
        pubmed_enabled = False
        layer_providers = []
        log_event(
            "SCIENCE",
            "sh_shared_candidate_pool_only",
            search_id=search_id,
            project_id=project_id,
            sub_hypothesis_id=sub_hypothesis_id,
            candidate_count=len(shared_raw_candidate_pool or []),
            reason="reuse_one_sh_discovery_batch_without_provider_dispatch",
        )
        provider_blocks.append({
            "provider": "sh_discovery_pool",
            "query": query,
            "status": "shared_candidate_pool_reused",
            "failure_stage": "local_candidate_pool_reuse",
            "submitted_to_provider": False,
            "results": [],
            "query_variant_v3": {
                "schema_version": "retrieval_query_variant_v3",
                "variant_id": "sh_discovery_pool_reuse",
                "query": query,
                "query_fingerprint": "",
                "dispatch_allowed": False,
                "skip_reason": "reuse_one_sh_discovery_batch_without_provider_dispatch",
            },
            "provider_outcome_v3": build_provider_outcome_v3(
                provider="sh_discovery_pool",
                query_variant_id="sh_discovery_pool_reuse",
                outcome=ProviderOutcomeKind.SUCCESS_EMPTY,
                raw_result_count=0,
                diagnostic_code="SH_DISCOVERY_POOL_REUSED",
            ),
        })
    broad_peer_reviewed_layers = broad_peer_reviewed_candidate_layers(quotas)
    if not shared_raw_candidate_pool_only:
        layer_providers = [
            provider
            for provider in selected
            if provider not in {"openalex", "semantic_scholar", "sciencedirect"}
            and not (provider == "pubmed" and pubmed_enabled)
        ]
    if provider_query_dispatch_suppressed:
        layer_providers = []
        log_event(
            "SCIENCE",
            "subhypothesis_provider_dispatch_suppressed",
            project_id=project_id,
            sub_hypothesis_id=sub_hypothesis_id,
            reason="no_query_branch_preserved_declared_input_after_repair",
            query_contamination_summary=query_contamination_summary,
        )
    if "semantic_scholar" in selected and not semantic_scholar_compatibility_enabled:
        log_event(
            "SCIENCE",
            "semantic_scholar_provider_batch_not_scheduled",
            reason=semantic_scholar_provider_not_scheduled_reason,
            peer_reviewed_target=0,
            L3_preprint=int(quotas.get("L3_preprint", 0)),
            L2_top_latest=int(quotas.get("L2_top_latest", 0)),
            dedicated_l2_scheduled=semantic_scholar_l2_enabled or openalex_l2_enabled,
            requested_providers=requested_providers,
        )
    configured_providers = list(selected)
    skipped_providers: list[dict[str, Any]] = []
    if "arxiv" in configured_providers and int(quotas.get("L3_preprint") or 0) <= 0:
        skipped_providers.append({"provider": "arxiv", "reason": "L3_preprint_quota_zero"})
    if "semantic_scholar" in configured_providers and semantic_scholar_active_circuit_skip:
        skipped_providers.append({
            "provider": "semantic_scholar",
            "reason": "recent_429_suppressed",
            "next_eligible_at": time.time() + max(0.0, semantic_scholar_active_circuit_retry_after),
        })
    prefetched_blocks: dict[str, list[dict[str, Any]]] = {}
    layer_fusion_reports: list[dict[str, Any]] = []

    def execute_stratified_provider_batches_in_parallel(
        jobs: list[tuple[str, Any]],
    ) -> dict[str, list[dict[str, Any]]]:
        """Dispatch independent broad provider batches concurrently.

        OpenAlex, PubMed, ScienceDirect, and Semantic Scholar compatibility
        batches do not depend on one another.  They can start together, while
        the downstream merge remains deterministic because callers consume the
        returned mapping in a fixed provider order.  Conditional L2 supplement
        traffic is intentionally excluded and still runs after broad-pool
        qualification.
        """

        if not jobs:
            return {}
        provider_names = [name for name, _runner in jobs]
        log_event(
            "SCIENCE",
            "stratified_provider_parallel_batch_start",
            search_id=search_id,
            providers=provider_names,
            job_count=len(jobs),
            max_workers=min(4, len(jobs)),
            policy="parallel_broad_batches_deterministic_merge",
        )
        started_at = time.perf_counter()
        completed: dict[str, list[dict[str, Any]]] = {}
        with ThreadPoolExecutor(max_workers=min(4, len(jobs))) as executor:
            future_map = {
                executor.submit(runner): provider
                for provider, runner in jobs
            }
            for future in as_completed(future_map):
                provider = future_map[future]
                try:
                    blocks = future.result()
                except Exception as exc:
                    block = provider_error_result(provider, query, exc)
                    block["retrieval_strategy"] = "parallel_stratified_provider_batch"
                    block["provider_batch_job_id"] = search_id or f"{provider}_parallel_batch"
                    blocks = [block]
                    log_event(
                        "SCIENCE",
                        "stratified_provider_parallel_batch_failed",
                        search_id=search_id,
                        provider=provider,
                        error=str(exc)[:240],
                    )
                if not isinstance(blocks, list):
                    blocks = []
                completed[provider] = [
                    block for block in blocks if isinstance(block, dict)
                ]
                log_event(
                    "SCIENCE",
                    "stratified_provider_parallel_batch_provider_complete",
                    search_id=search_id,
                    provider=provider,
                    request_count=len(completed[provider]),
                    result_count=sum(len(block.get("results") or []) for block in completed[provider]),
                )
        log_event(
            "SCIENCE",
            "stratified_provider_parallel_batch_complete",
            search_id=search_id,
            providers=provider_names,
            completed_providers=sorted(completed),
            elapsed_ms=round((time.perf_counter() - started_at) * 1000.0, 1),
        )
        return completed

    def stratified_discovery_impact(item: dict[str, Any]) -> float:
        metrics = item.get("citation_metrics") if isinstance(item.get("citation_metrics"), dict) else {}
        openalex_metrics = metrics.get("openalex") if isinstance(metrics.get("openalex"), dict) else {}
        semantic_scholar_metrics = metrics.get("semantic_scholar") if isinstance(metrics.get("semantic_scholar"), dict) else {}
        for value in (
            item.get("citation_count"),
            openalex_metrics.get("cited_by_count"),
            semantic_scholar_metrics.get("citation_count"),
        ):
            try:
                return float(value or 0.0)
            except (TypeError, ValueError):
                continue
        return 0.0

    def stratified_discovery_year(item: dict[str, Any]) -> int:
        match = re.search(r"\b(19|20)\d{2}\b", str(item.get("year") or ""))
        return int(match.group(0)) if match else 0

    for layer in layers:
        target = int(layer.get("quota") or 0)
        layer_name = str(layer.get("layer") or "")
        if layer_name == "L1_milestone":
            prefetched_blocks[layer_name] = []
            if target > 0:
                log_event(
                    "SCIENCE",
                    "broad_pool_L1_retrieval_suppressed",
                    target=target,
                    reason="L1 is populated only by the dedicated foundational-mechanism workflow.",
                    L1_from_broad_pool=0,
                )
            continue
        if target <= 0:
            prefetched_blocks[layer_name] = []
            continue
        blocks = fetch_stratified_layer_blocks(
            query,
            layer_providers,
            layer,
            query_plan=query_plan,
            domain=domain,
            preprint_layers=allowed_preprint_layers,
            preprint_required_anchor_groups=required_preprint_anchor_groups,
            preprint_anchor_policy=preprint_anchor_policy,
            preprint_scan_limit=preprint_scan_limit,
            preprint_provider_result_target=preprint_provider_result_target,
            preprint_max_branches=preprint_max_branches,
            single_paper_serial=single_paper_serial,
            anchor_contract=effective_anchor_contract,
            discipline_taxonomy=discipline_taxonomy,
        )
        prefetched_blocks[layer_name] = blocks
        provider_blocks.extend(blocks)

    pubmed_candidates_by_layer: dict[str, list[dict[str, Any]]] = {
        str(layer.get("layer") or ""): [] for layer in layers
    }
    openalex_candidates_by_layer: dict[str, list[dict[str, Any]]] = {
        str(layer.get("layer") or ""): [] for layer in layers
    }
    sciencedirect_candidates_by_layer: dict[str, list[dict[str, Any]]] = {
        str(layer.get("layer") or ""): [] for layer in layers
    }
    if (
        normalized_retrieval_mode == "socrates_targeted_evidence"
        and openalex_stratified_batch_required(selected, quotas)
    ):
        log_event(
            "SCIENCE",
            "openalex_broad_discovery_suppressed",
            retrieval_mode=normalized_retrieval_mode,
            reason="Socrates targeted evidence uses only the bounded dedicated L2 OpenAlex query.",
            query_branch_count=len(query_plan),
        )
    semantic_scholar_compatibility_blocks: list[dict[str, Any]] = []
    compatibility_quotas = dict(quotas)
    compatibility_quotas[SEMANTIC_SCHOLAR_L2_TOP_LATEST_LAYER] = 0
    broad_provider_jobs: list[tuple[str, Any]] = []
    if openalex_broad_enabled:
        broad_provider_jobs.append(
            (
                "openalex",
                lambda: fetch_openalex_stratified_batch(
                    query_plan,
                    search_id=search_id,
                    anchor_contract=effective_anchor_contract,
                    discipline_taxonomy=discipline_taxonomy,
                ),
            )
        )
    if sciencedirect_broad_enabled:
        broad_provider_jobs.append(
            (
                "sciencedirect",
                lambda: fetch_sciencedirect_stratified_batch(
                    query_plan,
                    max_results=max_results,
                    search_id=search_id,
                    anchor_contract=effective_anchor_contract,
                    discipline_taxonomy=discipline_taxonomy,
                ),
            )
        )
    if pubmed_enabled:
        broad_provider_jobs.append(
            (
                "pubmed",
                lambda: fetch_pubmed_stratified_batch(
                    query,
                    max_results=max_results,
                    quotas=quotas,
                    search_id=search_id,
                    query_plan=query_plan,
                    anchor_contract=effective_anchor_contract,
                    discipline_taxonomy=discipline_taxonomy,
                ),
            )
        )
    if semantic_scholar_compatibility_enabled:
        log_event(
            "SCIENCE",
            "semantic_scholar_compatibility_batch_scheduled_with_broad_providers",
            search_id=search_id,
            reason="compatibility batch is independent of conditional L2 supplement",
            completed_provider_blocks=len(provider_blocks),
            provider_order=layer_providers,
        )
        broad_provider_jobs.append(
            (
                "semantic_scholar",
                lambda: fetch_semantic_scholar_stratified_batch(
                    query,
                    max_results=max_results,
                    quotas=compatibility_quotas,
                    search_id=search_id,
                    query_plan=query_plan,
                    anchor_contract=effective_anchor_contract,
                ),
            )
        )
    broad_provider_results = execute_stratified_provider_batches_in_parallel(broad_provider_jobs)
    if openalex_broad_enabled:
        openalex_blocks = broad_provider_results.get("openalex", [])
        provider_blocks.extend(openalex_blocks)
        openalex_pool = rank_literature_results(
            ranking_query,
            dedupe_literature_results(flatten_literature_results(openalex_blocks)),
        )
        openalex_candidates_by_layer = stratify_peer_reviewed_candidates_locally(
            openalex_pool,
            provider="openalex",
            direct_evidence_mode=direct_evidence_mode,
        )
        openalex_candidates_by_layer = restrict_stratified_candidates_to_layers(
            openalex_candidates_by_layer,
            broad_peer_reviewed_layers,
            demote_l2_to_l4=int(quotas.get(SEMANTIC_SCHOLAR_L2_TOP_LATEST_LAYER, 0)) <= 0,
        )
    if sciencedirect_broad_enabled:
        sciencedirect_blocks = broad_provider_results.get("sciencedirect", [])
        provider_blocks.extend(sciencedirect_blocks)
        sciencedirect_pool = rank_literature_results(
            ranking_query,
            dedupe_literature_results(flatten_literature_results(sciencedirect_blocks)),
        )
        sciencedirect_candidates_by_layer = restrict_stratified_candidates_to_layers(
            stratify_peer_reviewed_candidates_locally(
                sciencedirect_pool,
                provider="sciencedirect",
                direct_evidence_mode=direct_evidence_mode,
            ),
            broad_peer_reviewed_layers,
            demote_l2_to_l4=int(quotas.get(SEMANTIC_SCHOLAR_L2_TOP_LATEST_LAYER, 0)) <= 0,
        )
    if pubmed_enabled:
        pubmed_blocks = broad_provider_results.get("pubmed", [])
        provider_blocks.extend(pubmed_blocks)
        pubmed_pool = rank_literature_results(
            ranking_query,
            dedupe_literature_results(flatten_literature_results(pubmed_blocks)),
        )
        pubmed_candidates_by_layer = stratify_pubmed_candidates_locally(
            pubmed_pool,
            direct_evidence_mode=direct_evidence_mode,
        )
        pubmed_candidates_by_layer = restrict_stratified_candidates_to_layers(
            pubmed_candidates_by_layer,
            broad_peer_reviewed_layers,
            demote_l2_to_l4=int(quotas.get(SEMANTIC_SCHOLAR_L2_TOP_LATEST_LAYER, 0)) <= 0,
        )
    if semantic_scholar_compatibility_enabled:
        semantic_scholar_compatibility_blocks = broad_provider_results.get("semantic_scholar", [])

    semantic_scholar_candidates_by_layer: dict[str, list[dict[str, Any]]] = {
        str(layer.get("layer") or ""): [] for layer in layers
    }
    dedicated_l2_candidates_by_layer: dict[str, list[dict[str, Any]]] = {
        str(layer.get("layer") or ""): [] for layer in layers
    }
    shared_candidates_by_layer: dict[str, list[dict[str, Any]]] = {
        str(layer.get("layer") or ""): [] for layer in layers
    }
    shared_raw_candidates = [
        dict(candidate)
        for candidate in (shared_raw_candidate_pool or [])
        if isinstance(candidate, dict)
    ]
    shared_raw_candidate_pool_available_count = len(shared_raw_candidates)
    shared_raw_preprint_excluded = 0
    shared_raw_candidate_keys: set[str] = set()
    if shared_raw_candidates:
        current_plan = next(
            (item for item in query_plan if isinstance(item, dict)),
            {},
        )
        provenance_fields = {
            field: current_plan.get(field)
            for field in _QUERY_PLAN_PROVENANCE_FIELDS
            if current_plan.get(field) not in (None, "", [], {})
        }
        by_provider: dict[str, list[dict[str, Any]]] = {}
        for candidate in shared_raw_candidates:
            if is_preprint_literature_result(candidate):
                # L3 stays an exploratory lane and must not be silently
                # recast as peer-reviewed support by a shared discovery pool.
                shared_raw_preprint_excluded += 1
                continue
            item = dict(candidate)
            source_provenance = (
                item.get("candidate_discovery_provenance")
                if isinstance(item.get("candidate_discovery_provenance"), dict)
                else {}
            )
            for field in (
                "targeted_alignment_admission",
                "targeted_admission_tier",
                "pending_full_text_verification",
                "prefulltext_import_eligible",
                "selection_stage",
                "direct_edge_candidate",
                "direct_edge_confirmed",
                "provisional_evidence_lane",
            ):
                item.pop(field, None)
            item.update(provenance_fields)
            item["query_branch"] = str(
                current_plan.get("query_branch")
                or current_plan.get("branch")
                or item.get("query_branch")
                or ""
            )
            item["candidate_discovery_provenance"] = {
                "mode": "shared_candidate_discovery",
                "source": dict(source_provenance),
                "current_slot_requires_independent_admission": True,
                "slot_completion_inferred": False,
            }
            candidate_key = str(literature_result_unique_key(item) or "").strip()
            if candidate_key:
                shared_raw_candidate_keys.add(candidate_key)
            provider = str(item.get("provider") or "shared_candidate_discovery")
            by_provider.setdefault(provider, []).append(item)
        for provider, candidates in by_provider.items():
            stratified = restrict_stratified_candidates_to_layers(
                stratify_peer_reviewed_candidates_locally(
                    candidates,
                    provider=provider,
                    direct_evidence_mode=direct_evidence_mode,
                ),
                broad_peer_reviewed_layers,
                demote_l2_to_l4=int(
                    quotas.get(SEMANTIC_SCHOLAR_L2_TOP_LATEST_LAYER, 0)
                ) <= 0,
            )
            for layer_name, items in stratified.items():
                shared_candidates_by_layer.setdefault(layer_name, []).extend(items)
        log_event(
            "SCIENCE",
            "v3_raw_candidate_pool_applied_to_current_slot",
            search_id=search_id,
            project_id=project_id,
            sub_hypothesis_id=sub_hypothesis_id,
            query_branch=str(current_plan.get("query_branch") or current_plan.get("branch") or ""),
            raw_candidate_count=len(shared_raw_candidates),
            preprint_excluded_count=shared_raw_preprint_excluded,
            candidates_by_layer={
                layer: len(items)
                for layer, items in shared_candidates_by_layer.items()
                if items
            },
            policy="shared_raw_metadata_reenters_current_slot_layer_domain_and_fulltext_gates",
        )
    domain_profile_artifact = build_research_domain_profile_artifact(
        domain=domain,
        query=query,
        use_llm=use_llm,
    )
    domain_profile = dict(domain_profile_artifact.get("profile") or {})
    domain_profile_revision = str(
        domain_profile_artifact.get("profile_revision") or ""
    )
    shared_domain_gate_cache: dict[str, dict[str, Any]] = {}
    paper_domain_assessment_cache: dict[str, dict[str, Any]] = {}
    paper_domain_batch_diagnostics: dict[str, Any] = {
        "schema_version": "paper_domain_assessment_batch_diagnostics_v1",
        "candidate_count": 0,
        "uncached_candidate_count": 0,
        "cache_hits": 0,
        "batch_count": 0,
        "batch_sizes": [],
        "max_workers": 0,
        "elapsed_ms": 0.0,
    }
    log_event(
        "SCIENCE",
        "research_domain_profile_resolved",
        search_id=search_id,
        project_id=project_id,
        sub_hypothesis_id=sub_hypothesis_id,
        profile_revision=domain_profile_revision,
        profile_source=str(domain_profile_artifact.get("profile_source") or ""),
        llm_call_count=int(use_llm),
        elapsed_ms=domain_profile_artifact.get("elapsed_ms"),
    )
    openalex_l2_blocks: list[dict[str, Any]] = []
    semantic_scholar_l2_blocks: list[dict[str, Any]] = []
    l2_provider_details: dict[str, dict[str, Any]] = {
        "openalex": {"status": "not_requested", "result_count": 0, "request_count": 0},
        "semantic_scholar": {"status": "not_requested", "result_count": 0, "request_count": 0},
    }
    l2_qualification: dict[str, Any] = {
        "candidate_count": 0,
        "eligible_count": 0,
        "recent_count": 0,
        "review_background_count": 0,
        "venue_status_counts": {},
        "rejection_reason_counts": {},
    }
    l2_provider_result_count = 0
    l2_provider_retrieval_status = "not_requested"
    l2_retrieval_decision: dict[str, Any] = {
        "policy": "reuse_broad_pool_then_conditional_openalex_then_conditional_semantic_scholar",
        "target": int(quotas.get(SEMANTIC_SCHOLAR_L2_TOP_LATEST_LAYER, 0)),
        "broad_candidate_count": 0,
        "broad_eligible_after_alignment_count": 0,
        "openalex_supplement_triggered": False,
        "semantic_scholar_supplement_triggered": False,
        "semantic_scholar_supplement_reason": "not_evaluated",
        "final_eligible_after_alignment_count": 0,
    }
    l2_alignment_rejection_samples: list[dict[str, Any]] = []
    l2_prequalification_domain_metrics: dict[str, Any] = {
        "evaluated": 0,
        "computed": 0,
        "cache_hits": 0,
        "elapsed_ms": 0.0,
    }

    def l2_alignment_evidence_kinds() -> list[str]:
        if not isinstance(candidate_alignment_contract, dict):
            return []
        roles: list[str] = []
        for path in candidate_alignment_contract.get("evidence_paths") or []:
            if not isinstance(path, dict):
                continue
            for value in (path.get("role"), path.get("id")):
                role = str(value or "").strip().lower()
                if role and role not in roles:
                    roles.append(role)
        for value in candidate_alignment_contract.get("required_evidence_roles") or []:
            role = str(value or "").strip().lower()
            if role and role not in roles:
                roles.append(role)
        preferred = [
            role
            for role in L2_DIRECT_EVIDENCE_KIND_ORDER
            if role in roles
        ]
        if preferred:
            return preferred
        evidence_mode = str(candidate_alignment_contract.get("evidence_mode") or "")
        if evidence_mode == "predictive_generalization":
            return ["predictive_validation"]
        return ["causal_validation", "mechanism_discovery", "experimental_evidence", "association"]

    l2_requested_evidence_kinds = l2_alignment_evidence_kinds()

    def record_l2_alignment_rejection(
        candidate: dict[str, Any],
        *,
        reason: str,
        assessment: dict[str, Any] | None = None,
    ) -> None:
        if len(l2_alignment_rejection_samples) >= 8:
            return
        alignment = assessment if isinstance(assessment, dict) else (
            candidate.get("targeted_alignment_admission")
            if isinstance(candidate.get("targeted_alignment_admission"), dict)
            else {}
        )
        l2_assessment = l2_candidate_qualification(candidate)
        venue_evidence = l2_assessment.get("venue_evidence") if isinstance(l2_assessment.get("venue_evidence"), dict) else {}

        def axis_hits(name: str) -> list[str]:
            axis = alignment.get(name) if isinstance(alignment.get(name), dict) else {}
            return [
                str(item)
                for item in (axis.get("hits") or [])
                if str(item).strip()
            ][:8]

        l2_alignment_rejection_samples.append({
            "title": str(candidate.get("title") or "")[:180],
            "year": candidate.get("year"),
            "venue": str(candidate.get("venue") or "")[:120],
            "provider": str(candidate.get("provider") or ""),
            "query_branch": str(candidate.get("query_branch") or candidate.get("primary_query_branch") or ""),
            "evidence_kind": str(candidate.get("evidence_kind") or alignment.get("evidence_kind") or ""),
            "evidence_path_role": str(candidate.get("evidence_path_role") or ""),
            "reason": reason,
            "alignment_reason": str(alignment.get("reason") or ""),
            "requested_l2_evidence_kinds": list(l2_requested_evidence_kinds),
            "l2_qualification": {
                "eligible": bool(l2_assessment.get("eligible")),
                "recent": bool(l2_assessment.get("recent")),
                "review_background": bool(l2_assessment.get("review_background")),
                "venue_status": str(venue_evidence.get("status") or ""),
                "reasons": list(l2_assessment.get("reasons") or [])[:8],
            },
            "evidence_lane": str(alignment.get("evidence_lane") or ""),
            "standard_evidence_lane": str(alignment.get("standard_evidence_lane") or ""),
            "standard_research_design": str(alignment.get("standard_research_design") or ""),
            "project_context_hits": axis_hits("project_context"),
            "input_hits": axis_hits("subhypothesis_input"),
            "mechanism_hits": axis_hits("mechanism_or_focus"),
            "outcome_hits": axis_hits("functional_outcome"),
        })

    def l2_provider_detail(
        blocks: list[dict[str, Any]],
        *,
        not_requested_status: str,
    ) -> dict[str, Any]:
        valid_blocks = [block for block in blocks if isinstance(block, dict)]
        result_count = sum(len(block.get("results") or []) for block in valid_blocks)
        if result_count:
            status = "provider_candidates_returned"
        elif valid_blocks and all(str(block.get("status") or "") == "ok" for block in valid_blocks):
            status = "provider_zero_results"
        elif valid_blocks:
            status = "provider_error"
        else:
            status = not_requested_status
        return {
            "status": status,
            "result_count": result_count,
            "request_count": len(valid_blocks),
        }

    def prequalify_l2_pool(candidates: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, int]]:
        """Apply the same strict gates used by L2 selection before spending a supplement.

        This is intentionally a read-ahead, not an early selection: it does
        not consume a result slot or mutate the public targeted-admission
        counters.  Its cached gate assessments are reused by the later normal
        layer selector, so the conditional traffic policy adds no duplicate
        LLM/domain scoring work.
        """
        accepted: list[dict[str, Any]] = []
        rejection_counts: dict[str, int] = {}
        local_seen: set[str] = set()
        l2_deep_candidates: list[dict[str, Any]] = []
        for candidate in candidates:
            if not stratified_candidate_matches(SEMANTIC_SCHOLAR_L2_TOP_LATEST_LAYER, candidate):
                for reason in l2_candidate_qualification(candidate).get("reasons") or ["not_l2_qualified"]:
                    rejection_counts[str(reason)] = rejection_counts.get(str(reason), 0) + 1
                continue
            if not admits_coarse_candidate(candidate):
                rejection_counts["coarse_subhypothesis_prefilter_rejected"] = (
                    rejection_counts.get("coarse_subhypothesis_prefilter_rejected", 0) + 1
                )
                continue
            l2_deep_candidates.append(candidate)
        l2_scan_limit = max(
            l2_target,
            int(deep_layer_limits.get(SEMANTIC_SCHOLAR_L2_TOP_LATEST_LAYER) or 0),
        )
        if candidate_alignment_contract and l2_scan_limit:
            l2_deep_candidates = l2_deep_candidates[:l2_scan_limit]
        for candidate in l2_deep_candidates:
            if not admits_targeted_candidate(
                candidate,
                record_metrics=False,
                requested_evidence_kinds_override=l2_requested_evidence_kinds,
            ):
                record_l2_alignment_rejection(
                    candidate,
                    reason="targeted_alignment_rejected",
                )
                rejection_counts["targeted_alignment_rejected"] = (
                    rejection_counts.get("targeted_alignment_rejected", 0) + 1
                )
                continue
            rejected, cached, elapsed_ms = evaluate_candidate_domain_gate(
                candidate,
                domain=domain,
                query=query,
                domain_profile=domain_profile,
                domain_profile_revision=domain_profile_revision,
                assessment_cache=shared_domain_gate_cache,
            )
            l2_prequalification_domain_metrics["evaluated"] += 1
            l2_prequalification_domain_metrics["cache_hits"] += int(cached)
            l2_prequalification_domain_metrics["computed"] += int(not cached)
            l2_prequalification_domain_metrics["elapsed_ms"] += elapsed_ms
            if rejected:
                record_l2_alignment_rejection(
                    candidate,
                    reason="domain_or_mechanism_gate_rejected",
                )
                rejection_counts["domain_or_mechanism_gate_rejected"] = (
                    rejection_counts.get("domain_or_mechanism_gate_rejected", 0) + 1
                )
                continue
            if candidate.get("research_role_auto_selectable") is False:
                rejection_counts["research_role_not_auto_selectable"] = (
                    rejection_counts.get("research_role_not_auto_selectable", 0) + 1
                )
                continue
            key = literature_result_unique_key(candidate)
            if key in local_seen:
                rejection_counts["duplicate"] = rejection_counts.get("duplicate", 0) + 1
                continue
            local_seen.add(key)
            accepted.append(candidate)
        return accepted, rejection_counts

    l2_target = max(0, int(quotas.get(SEMANTIC_SCHOLAR_L2_TOP_LATEST_LAYER, 0)))
    current_v3_work_item_execution = current_v3_work_item_plan
    # All broad providers participate in the initial L2 decision.  The
    # normal layer selector below still owns final ranking/selection, but it
    # must not trigger a duplicate provider request merely because these
    # candidates were originally retrieved for theory, experiment, or review
    # discovery.
    broad_l2_results = (
        flatten_literature_results(prefetched_blocks.get(SEMANTIC_SCHOLAR_L2_TOP_LATEST_LAYER, []))
        + openalex_candidates_by_layer.get(SEMANTIC_SCHOLAR_L2_TOP_LATEST_LAYER, [])
        + sciencedirect_candidates_by_layer.get(SEMANTIC_SCHOLAR_L2_TOP_LATEST_LAYER, [])
        + pubmed_candidates_by_layer.get(SEMANTIC_SCHOLAR_L2_TOP_LATEST_LAYER, [])
        + semantic_scholar_candidates_by_layer.get(SEMANTIC_SCHOLAR_L2_TOP_LATEST_LAYER, [])
        + shared_candidates_by_layer.get(SEMANTIC_SCHOLAR_L2_TOP_LATEST_LAYER, [])
    )
    broad_l2_pool = rank_literature_results(
        ranking_query,
        dedupe_literature_results(broad_l2_results),
    ) if broad_l2_results else []
    broad_l2_eligible, broad_l2_rejections = prequalify_l2_pool(broad_l2_pool)
    l2_retrieval_decision.update(
        {
            "broad_candidate_count": len(broad_l2_pool),
            "broad_eligible_after_alignment_count": len(broad_l2_eligible),
            "broad_rejection_reason_counts": broad_l2_rejections,
            "prequalification_domain_metrics": {
                **l2_prequalification_domain_metrics,
                "elapsed_ms": round(
                    float(l2_prequalification_domain_metrics["elapsed_ms"]),
                    3,
                ),
            },
        }
    )

    if l2_target > 0 and current_v3_work_item_execution:
        # A V3 slot work item already has one exact, scope-preserving provider
        # query and its own typed recovery/cache boundary.  The historic L2
        # supplementation lane would materialize a separate topic-oriented
        # sequence, so it is intentionally unavailable here rather than used
        # as an implicit zero-result fallback.
        combined_l2_pool = list(broad_l2_pool)
        final_l2_eligible = list(broad_l2_eligible)
        final_l2_rejections = dict(broad_l2_rejections)
        l2_provider_details["openalex"]["status"] = "not_applicable_v3_scope_bound_execution"
        l2_provider_details["semantic_scholar"]["status"] = "not_applicable_v3_scope_bound_execution"
        l2_retrieval_decision.update(
            {
                "policy": "v3_scope_bound_provider_execution_without_l2_fallback",
                "openalex_supplement_reason": "current_v3_work_item_forbids_topic_supplement",
                "semantic_scholar_supplement_reason": "current_v3_work_item_forbids_topic_supplement",
                "final_candidate_count": len(combined_l2_pool),
                "final_eligible_after_alignment_count": len(final_l2_eligible),
                "final_rejection_reason_counts": final_l2_rejections,
            }
        )
        l2_qualification = summarize_l2_candidate_qualification(combined_l2_pool)
        l2_qualification["eligible_after_alignment_count"] = len(final_l2_eligible)
        l2_qualification["alignment_rejection_reason_counts"] = final_l2_rejections
        l2_qualification["alignment_rejection_samples"] = list(l2_alignment_rejection_samples)
        l2_provider_retrieval_status = "not_applicable_v3_scope_bound_execution"
        log_event(
            "SCIENCE",
            "v3_l2_topic_supplement_not_applicable",
            retrieval_status=l2_provider_retrieval_status,
            **l2_retrieval_decision,
        )
    elif l2_target > 0:
        log_event(
            "SCIENCE",
            "l2_conditional_retrieval_evaluated",
            completed_provider_blocks=len(provider_blocks),
            target=l2_target,
            broad_candidate_count=len(broad_l2_pool),
            broad_eligible_after_alignment_count=len(broad_l2_eligible),
            openalex_supplement_required=len(broad_l2_eligible) < l2_target,
        )
        combined_l2_pool = list(broad_l2_pool)
        final_l2_eligible = list(broad_l2_eligible)
        final_l2_rejections = dict(broad_l2_rejections)
        if len(final_l2_eligible) < l2_target and openalex_l2_enabled:
            l2_retrieval_decision["openalex_supplement_triggered"] = True
            openalex_l2_blocks = fetch_openalex_l2_top_latest_batch(
                query,
                l2_quota=l2_target,
                search_id=search_id,
                query_plan=query_plan,
                anchor_contract=effective_anchor_contract,
                discipline_taxonomy=discipline_taxonomy,
            )
            provider_blocks.extend(openalex_l2_blocks)
            l2_provider_details["openalex"] = l2_provider_detail(
                openalex_l2_blocks,
                not_requested_status="not_requested",
            )
            combined_l2_pool = rank_literature_results(
                ranking_query,
                dedupe_literature_results(
                    broad_l2_pool + flatten_literature_results(openalex_l2_blocks)
                ),
            )
            final_l2_eligible, final_l2_rejections = prequalify_l2_pool(combined_l2_pool)
        elif len(final_l2_eligible) >= l2_target:
            l2_provider_details["openalex"]["status"] = "not_needed_existing_broad_pool"

        if direct_evidence_mode:
            # Socrates direct-evidence retrieval can use one focused OpenAlex
            # query when its broad fan-out is suppressed, but L2's optional
            # Semantic Scholar supplement is never allowed to consume the
            # scarce graph/search rate budget in that mode.
            l2_retrieval_decision["semantic_scholar_supplement_reason"] = "direct_evidence_mode_openalex_only"
            l2_provider_details["semantic_scholar"]["status"] = "not_applicable_direct_evidence_mode"
        elif len(final_l2_eligible) >= l2_target:
            l2_retrieval_decision["semantic_scholar_supplement_reason"] = "not_needed_openalex_or_broad_pool_satisfied_target"
            l2_provider_details["semantic_scholar"]["status"] = "not_needed_existing_pool"
        elif semantic_scholar_active_circuit_skip:
            l2_retrieval_decision["semantic_scholar_supplement_reason"] = (
                "skip_semantic_scholar_due_to_active_circuit"
            )
            l2_retrieval_decision["semantic_scholar_active_circuit_retry_after_seconds"] = round(
                float(semantic_scholar_active_circuit_retry_after or 0.0),
                2,
            )
            l2_provider_details["semantic_scholar"]["status"] = "skipped_active_circuit"
            l2_provider_details["semantic_scholar"]["reason"] = (
                "skip_semantic_scholar_due_to_active_circuit"
            )
        elif semantic_scholar_l2_enabled:
            healthy, health_reason = semantic_scholar_l2_supplement_health()
            l2_retrieval_decision["semantic_scholar_supplement_reason"] = health_reason
            if healthy:
                l2_retrieval_decision["semantic_scholar_supplement_triggered"] = True
                semantic_scholar_l2_blocks = fetch_semantic_scholar_l2_top_latest_batch(
                    query,
                    l2_quota=l2_target,
                    search_id=search_id,
                    query_plan=query_plan,
                    allow_zero_result_recovery=False,
                    anchor_contract=effective_anchor_contract,
                )
                provider_blocks.extend(semantic_scholar_l2_blocks)
                l2_provider_details["semantic_scholar"] = l2_provider_detail(
                    semantic_scholar_l2_blocks,
                    not_requested_status="not_requested",
                )
                combined_l2_pool = rank_literature_results(
                    ranking_query,
                    dedupe_literature_results(
                        combined_l2_pool + flatten_literature_results(semantic_scholar_l2_blocks)
                    ),
                )
                final_l2_eligible, final_l2_rejections = prequalify_l2_pool(combined_l2_pool)
            else:
                l2_provider_details["semantic_scholar"]["status"] = f"skipped_{health_reason}"
        else:
            l2_retrieval_decision["semantic_scholar_supplement_reason"] = "semantic_scholar_l2_not_enabled"
            l2_provider_details["semantic_scholar"]["status"] = "not_requested"

        l2_retrieval_decision.update(
            {
                "final_candidate_count": len(combined_l2_pool),
                "final_eligible_after_alignment_count": len(final_l2_eligible),
                "final_rejection_reason_counts": final_l2_rejections,
            }
        )
        l2_provider_result_count = sum(
            int(detail.get("result_count") or 0)
            for detail in l2_provider_details.values()
        )
        l2_qualification = summarize_l2_candidate_qualification(combined_l2_pool)
        l2_qualification["eligible_after_alignment_count"] = len(final_l2_eligible)
        l2_qualification["alignment_rejection_reason_counts"] = final_l2_rejections
        l2_qualification["alignment_rejection_samples"] = list(l2_alignment_rejection_samples)
        if len(broad_l2_eligible) >= l2_target:
            l2_provider_retrieval_status = "satisfied_by_existing_broad_pool"
        elif any(detail.get("status") == "provider_candidates_returned" for detail in l2_provider_details.values()):
            l2_provider_retrieval_status = "provider_candidates_returned"
        elif any(
            detail.get("status") == "v2_query_compilation_blocked_before_provider_submission"
            for detail in l2_provider_details.values()
        ):
            l2_provider_retrieval_status = "v2_query_compilation_blocked"
        elif any(detail.get("status") == "provider_error" for detail in l2_provider_details.values()):
            l2_provider_retrieval_status = "l2_provider_error"
        elif len(final_l2_eligible) < l2_target:
            l2_provider_retrieval_status = "l2_evidence_shortage"
        else:
            l2_provider_retrieval_status = "not_requested"
        log_event(
            "SCIENCE",
            "l2_conditional_retrieval_complete",
            retrieval_status=l2_provider_retrieval_status,
            provider_details=l2_provider_details,
            **l2_retrieval_decision,
            **l2_qualification,
        )
        if l2_alignment_rejection_samples:
            log_event(
                "SCIENCE",
                "l2_alignment_rejection_diagnostic",
                search_id=search_id,
                project_id=project_id,
                sub_hypothesis_id=sub_hypothesis_id,
                target=l2_target,
                requested_l2_evidence_kinds=list(l2_requested_evidence_kinds),
                sample_count=len(l2_alignment_rejection_samples),
                samples=list(l2_alignment_rejection_samples),
            )
        dedicated_l2_blocks = openalex_l2_blocks + semantic_scholar_l2_blocks
        dedicated_l2_pool = rank_literature_results(
            ranking_query,
            dedupe_literature_results(flatten_literature_results(dedicated_l2_blocks)),
        ) if dedicated_l2_blocks else []
        dedicated_l2_candidates = restrict_stratified_candidates_to_layers(
            stratify_peer_reviewed_candidates_locally(
                dedicated_l2_pool,
                provider="l2_conditional_supplement",
                direct_evidence_mode=direct_evidence_mode,
            ),
            {SEMANTIC_SCHOLAR_L2_TOP_LATEST_LAYER},
        ) if dedicated_l2_pool else {}
        dedicated_l2_candidates_by_layer[SEMANTIC_SCHOLAR_L2_TOP_LATEST_LAYER] = list(
            dedicated_l2_candidates.get(SEMANTIC_SCHOLAR_L2_TOP_LATEST_LAYER, [])
        )
    else:
        l2_retrieval_decision["semantic_scholar_supplement_reason"] = "l2_quota_zero"

    if semantic_scholar_compatibility_enabled:
        log_event(
            "SCIENCE",
            "semantic_scholar_compatibility_batch_collected_from_parallel_broad_providers",
            completed_provider_blocks=len(provider_blocks),
            request_count=len(semantic_scholar_compatibility_blocks),
            result_count=sum(len(block.get("results") or []) for block in semantic_scholar_compatibility_blocks),
            provider_order=layer_providers,
        )
        semantic_scholar_blocks = semantic_scholar_compatibility_blocks
        provider_blocks.extend(semantic_scholar_blocks)
        semantic_scholar_pool = rank_literature_results(
            ranking_query,
            dedupe_literature_results(flatten_literature_results(semantic_scholar_blocks)),
        )
        semantic_scholar_compatibility_candidates = restrict_stratified_candidates_to_layers(
            stratify_semantic_scholar_candidates_locally(
                semantic_scholar_pool,
                direct_evidence_mode=direct_evidence_mode,
            ),
            set(SEMANTIC_SCHOLAR_COMPATIBILITY_LAYERS),
            demote_l2_to_l4=int(quotas.get(SEMANTIC_SCHOLAR_L2_TOP_LATEST_LAYER, 0)) <= 0,
        )
        for layer_name, items in semantic_scholar_compatibility_candidates.items():
            semantic_scholar_candidates_by_layer[layer_name].extend(items)

    paper_domain_prewarm_by_key: dict[str, dict[str, Any]] = {}
    for layer in layers:
        layer_name = str(layer.get("layer") or "")
        target = int(layer.get("quota") or 0)
        if target <= 0:
            continue
        local_provider_candidates = (
            openalex_candidates_by_layer.get(layer_name, [])
            + sciencedirect_candidates_by_layer.get(layer_name, [])
            + pubmed_candidates_by_layer.get(layer_name, [])
            + semantic_scholar_candidates_by_layer.get(layer_name, [])
            + dedicated_l2_candidates_by_layer.get(layer_name, [])
            + shared_candidates_by_layer.get(layer_name, [])
        )
        prewarm_candidates = [
            item
            for item in rank_literature_results(
                ranking_query,
                dedupe_literature_results(
                    flatten_literature_results(
                        prefetched_blocks.get(layer_name, [])
                    )
                    + local_provider_candidates
                ),
            )
            if stratified_candidate_matches(
                layer_name,
                item,
                allow_historical_direct_evidence=direct_evidence_mode,
            )
        ]
        if candidate_alignment_contract:
            prewarm_candidates = [
                candidate
                for candidate in prewarm_candidates
                if admits_coarse_candidate(candidate)
            ]
        prewarm_limit = max(
            target,
            int(deep_layer_limits.get(layer_name) or 0),
        )
        for candidate in prewarm_candidates[:prewarm_limit]:
            paper_domain_prewarm_by_key.setdefault(
                paper_domain_assessment_cache_key(candidate),
                candidate,
            )
    paper_domain_batch_diagnostics = warm_paper_domain_assessment_cache(
        list(paper_domain_prewarm_by_key.values()),
        execution_policy,
        paper_domain_assessment_cache,
    )
    log_event(
        "SCIENCE",
        "paper_domain_assessment_batches_completed",
        search_id=search_id,
        project_id=project_id,
        sub_hypothesis_id=sub_hypothesis_id,
        **paper_domain_batch_diagnostics,
    )

    for layer in layers:
        target = layer["quota"]
        layer_name = str(layer["layer"])
        year_policy = direct_evidence_year_policy() if direct_evidence_mode and layer_name == "L4_regular" else stratified_year_policy(layer["layer"])
        local_provider_candidates = (
            openalex_candidates_by_layer.get(layer_name, [])
            +
            sciencedirect_candidates_by_layer.get(layer_name, [])
            +
            pubmed_candidates_by_layer.get(layer_name, [])
            + semantic_scholar_candidates_by_layer.get(layer_name, [])
            + dedicated_l2_candidates_by_layer.get(layer_name, [])
            + shared_candidates_by_layer.get(layer_name, [])
        )
        if target <= 0:
            available_by_provider: dict[str, int] = {}
            for item in local_provider_candidates:
                provider = str(item.get("provider") or "unknown")
                available_by_provider[provider] = available_by_provider.get(provider, 0) + 1
            log_event(
                "SCIENCE",
                "stratified_layer_selection_complete",
                layer=layer_name,
                target=0,
                available=len(local_provider_candidates),
                selected=0,
                available_by_provider=available_by_provider,
                selected_by_provider={},
                reason="layer_quota_zero",
            )
            strata_reports.append(
                {
                    **layer,
                    "year_policy": year_policy,
                    "target": target,
                    "candidate_count": len(local_provider_candidates),
                    "selected": 0,
                    "carried_to_next": 0,
                }
            )
            continue
        blocks = prefetched_blocks.get(layer_name, [])
        pooled_results = (
            flatten_literature_results(blocks)
            + local_provider_candidates
        )
        raw_candidates = rank_literature_results(
            ranking_query,
            dedupe_literature_results(pooled_results),
        )
        layer_lanes = {
            "direct_relevance": raw_candidates,
            "impact": sorted(raw_candidates, key=stratified_discovery_impact, reverse=True),
            "recent_direct_evidence": sorted(raw_candidates, key=stratified_discovery_year, reverse=True),
            "local_quality": sorted(
                raw_candidates,
                key=lambda item: float(item.get("publication_quality_score") or 0.0),
                reverse=True,
            ),
        }
        if layer_name == "L0_review":
            layer_lanes["review_map"] = list(raw_candidates)
        if direct_evidence_mode:
            layer_lanes["mechanism_intervention"] = list(raw_candidates)
        layer_fusion = fuse_literature_candidates(ranking_query, layer_lanes)
        raw_candidates = list(layer_fusion["documents"])
        layer_fusion_reports.append(
            {
                "layer": layer_name,
                **{key: value for key, value in layer_fusion.items() if key != "documents"},
            }
        )
        candidate_pool = [
            item
            for item in raw_candidates
            if stratified_candidate_matches(
                layer["layer"],
                item,
                allow_historical_direct_evidence=direct_evidence_mode,
            )
        ]
        if candidate_alignment_contract:
            candidate_pool = [
                candidate
                for candidate in candidate_pool
                if admits_coarse_candidate(candidate)
            ]
            layer_deep_limit = max(
                int(target or 0),
                int(deep_layer_limits.get(layer_name) or 0),
            )
            candidate_pool = candidate_pool[:layer_deep_limit]
            targeted_admission["deep_pool_selected"] += len(candidate_pool)
            targeted_admission["deep_pool_by_layer"][layer_name] = len(
                candidate_pool
            )
        select_started = time.perf_counter()
        layer_paper_domain_cache_hits = sum(
            paper_domain_assessment_cache_key(candidate)
            in paper_domain_assessment_cache
            for candidate in candidate_pool
        )
        candidates = prioritize_candidates_for_question_card(
            candidate_pool,
            normalized_question_card,
            use_llm=use_llm,
            domain_assessment_cache=paper_domain_assessment_cache,
        )
        candidates.sort(
            key=lambda item: (
                -int(item.get("research_role_priority") or 0),
                -float((item.get("research_role_assessment") or {}).get("score") or 0.0),
                -float(item.get("discovery_rrf_score") or 0.0),
                -float(item.get("relevance_score") or 0.0),
                str(item.get("title") or ""),
            )
        )
        recovery_used = ""
        preprint_recovery: dict[str, Any] = {}
        if not candidates and layer["layer"] == "L3_preprint" and "L3_preprint" in allowed_preprint_layers:
            recovery_options: dict[str, Any] = {}
            if preprint_scan_limit is not None:
                recovery_options["scan_limit"] = preprint_scan_limit
            if preprint_recovery_windows is not None:
                recovery_options["windows_months"] = preprint_recovery_windows
            if preprint_recovery_max_variants is not None:
                recovery_options["max_variants"] = preprint_recovery_max_variants
            recovery_blocks, preprint_recovery = recover_preprint_layer_candidates(
                query=query,
                query_plan=query_plan,
                domain=domain,
                max_results=max(4, target),
                providers=selected,
                required_anchor_groups=required_preprint_anchor_groups,
                anchor_policy=preprint_anchor_policy,
                **recovery_options,
            )
            provider_blocks.extend(recovery_blocks)
            retry_candidates = rank_literature_results(
                ranking_query,
                dedupe_literature_results(flatten_literature_results(recovery_blocks)),
            )
            candidates = prioritize_candidates_for_question_card(
                [
                    item
                    for item in retry_candidates
                    if stratified_candidate_matches(
                        layer["layer"],
                        item,
                        allow_historical_direct_evidence=direct_evidence_mode,
                    )
                ],
                normalized_question_card,
                use_llm=use_llm,
                domain_assessment_cache=paper_domain_assessment_cache,
            )
            if candidates:
                recovery_used = "preprint_query_and_provider_retry"
        if not candidates and layer["layer"] in {"L1_milestone", "L2_top_latest"}:
            candidates, recovery_used = recover_stratified_layer_candidates(layer["layer"], raw_candidates)
            candidates = prioritize_candidates_for_question_card(
                candidates,
                normalized_question_card,
                use_llm=use_llm,
                domain_assessment_cache=paper_domain_assessment_cache,
            )
        domain_elapsed_ms = 0.0
        domain_cache_hits = 0
        picked: list[dict[str, Any]] = []
        aligned_layer_candidates: list[dict[str, Any]] = []
        aligned_layer_seen: set[str] = set()
        targeted_alignment_rejected = 0
        domain_gate_rejected = 0
        research_role_rejected = 0
        auxiliary_pending_pool_rejected = 0
        rejected_as_duplicate = 0
        post_targeted_candidate_count = 0
        post_domain_candidate_count = 0
        post_role_candidate_count = 0
        for candidate in candidates:
            if not admits_targeted_candidate(
                candidate,
                allow_aligned_background=layer_name == "L0_review",
                # Candidate selection is an import/full-text queue.  Even in
                # a direct-evidence run, metadata cannot establish every
                # causal-edge fragment, so it must not be used as a core
                # evidence verdict here.
                admission_level="import",
                requested_evidence_kinds_override=(
                    l2_requested_evidence_kinds
                    if layer_name == SEMANTIC_SCHOLAR_L2_TOP_LATEST_LAYER
                    else None
                ),
            ):
                if layer_name == SEMANTIC_SCHOLAR_L2_TOP_LATEST_LAYER:
                    record_l2_alignment_rejection(
                        candidate,
                        reason="targeted_alignment_rejected_at_layer_selection",
                    )
                targeted_alignment_rejected += 1
                continue
            post_targeted_candidate_count += 1
            rejected, domain_cache_hit, candidate_domain_ms = evaluate_candidate_domain_gate(
                candidate,
                domain=domain,
                query=query,
                domain_profile=domain_profile,
                domain_profile_revision=domain_profile_revision,
                assessment_cache=shared_domain_gate_cache,
            )
            domain_elapsed_ms += candidate_domain_ms
            domain_cache_hits += int(domain_cache_hit)
            if rejected:
                if layer_name == SEMANTIC_SCHOLAR_L2_TOP_LATEST_LAYER:
                    record_l2_alignment_rejection(
                        candidate,
                        reason="domain_or_mechanism_gate_rejected_at_layer_selection",
                    )
                domain_gate_rejected += 1
                continue
            post_domain_candidate_count += 1
            if (
                candidate.get("research_role_auto_selectable") is False
                and not candidate.get("pending_full_text_verification")
            ):
                research_role_rejected += 1
                continue
            post_role_candidate_count += 1
            key = literature_result_unique_key(candidate)
            if key in seen or key in aligned_layer_seen:
                rejected_as_duplicate += 1
                continue
            aligned_layer_seen.add(key)
            item = dict(candidate)
            item["stratified_layer"] = layer["layer"]
            item["retrieval_layer"] = neutral_retrieval_layer(layer["layer"])
            item["stratified_label"] = layer["label"]
            item["year_policy"] = year_policy
            if recovery_used:
                item["stratified_recovery"] = recovery_used
            item["_why_selected"] = stratified_selection_reason(layer["layer"], item)
            aligned_layer_candidates.append(item)
        # Deep alignment is deliberately completed over the bounded layer
        # pool before top-k truncation.  Only after every candidate has an
        # admission verdict do direct-core likelihood and full-text discovery
        # signals influence which 12--20 records consume this round's import
        # attempts.
        lane_priority = {
            "DIRECT_TRIADIC_EVIDENCE": 5,
            "ADVERSE_OR_REVERSAL_EVIDENCE": 5,
            "MECHANISM_LINK_EVIDENCE": 4,
            "INPUT_OR_CONDITION_EVIDENCE": 3,
            "OUTCOME_EVIDENCE": 3,
            "BOUNDARY_OR_NEGATIVE_EVIDENCE": 2,
            "BACKGROUND_REVIEW": 1,
        }

        def aligned_candidate_priority(item: dict[str, Any]) -> tuple[Any, ...]:
            admission = (
                item.get("targeted_alignment_admission")
                if isinstance(item.get("targeted_alignment_admission"), dict)
                else {}
            )
            payload = (
                item.get("papergraph_input")
                if isinstance(item.get("papergraph_input"), dict)
                else {}
            )
            best_oa = (
                item.get("best_oa_location")
                if isinstance(item.get("best_oa_location"), dict)
                else {}
            )
            full_text_signal = bool(
                item.get("open_access_pdf")
                or item.get("full_text_url")
                or item.get("pmc_id")
                or payload.get("open_access_pdf")
                or payload.get("full_text_url")
                or payload.get("pmc_id")
                or best_oa.get("pdf_url")
            )
            return (
                -int(admission.get("direct_edge_candidate") is True),
                -int(
                    lane_priority.get(
                        str(admission.get("evidence_lane") or ""),
                        0,
                    )
                ),
                -int(full_text_signal),
                -int(item.get("research_role_priority") or 0),
                -float(
                    (item.get("research_role_assessment") or {}).get("score")
                    or 0.0
                ),
                -float(item.get("discovery_rrf_score") or 0.0),
                -float(item.get("relevance_score") or 0.0),
                str(item.get("title") or ""),
            )

        aligned_layer_candidates.sort(key=aligned_candidate_priority)
        retained_layer_candidates: list[dict[str, Any]] = []
        for item in aligned_layer_candidates:
            if retains_auxiliary_pending_candidate(item):
                retained_layer_candidates.append(item)
            else:
                auxiliary_pending_pool_rejected += 1
        aligned_layer_candidates = retained_layer_candidates
        picked = aligned_layer_candidates[:target]
        aligned_reserve_candidates.extend(aligned_layer_candidates[target:])
        for item in picked:
            seen.add(literature_result_unique_key(item))
        selected_results.extend(picked)
        available_by_provider: dict[str, int] = {}
        for item in candidates:
            provider = str(item.get("provider") or "unknown")
            available_by_provider[provider] = available_by_provider.get(provider, 0) + 1
        selected_by_provider: dict[str, int] = {}
        selected_samples: list[dict[str, Any]] = []
        for item in picked:
            provider = str(item.get("provider") or "unknown")
            selected_by_provider[provider] = selected_by_provider.get(provider, 0) + 1
            selection_log_fields = stratified_candidate_selection_log_fields(
                item,
                layer=layer_name,
            )
            candidate_research_role = str(
                selection_log_fields.get("candidate_research_role") or ""
            )
            item["selection_stage"] = "pre_import"
            item["candidate_research_role"] = candidate_research_role
            if len(selected_samples) < 3:
                selected_samples.append(
                    {
                        "result_index": item.get("result_index"),
                        "title": str(item.get("title") or "")[:140],
                        "provider": provider,
                        "year": item.get("year"),
                        "query_branch": item.get("query_branch"),
                        "candidate_research_role": candidate_research_role,
                        "targeted_admission_tier": item.get("targeted_admission_tier"),
                        "provisional_evidence_lane": item.get("provisional_evidence_lane"),
                    }
                )
            log_event(
                "SCIENCE",
                "stratified_candidate_selected",
                **selection_log_fields,
            )
        log_event(
            "SCIENCE",
            "stratified_layer_selection_complete",
            layer=layer_name,
            target=target,
            available=len(candidates),
            selected=len(picked),
            available_by_provider=available_by_provider,
            selected_by_provider=selected_by_provider,
            selected_samples=selected_samples,
            # Historical compatibility: keep ``domain_rejected`` but make it
            # mean the actual domain/mechanism gate again.  Other rejection
            # stages are logged separately so L0/L4 do not appear to have
            # failed a domain gate they never reached.
            domain_rejected=domain_gate_rejected,
            targeted_alignment_rejected=targeted_alignment_rejected,
            domain_gate_rejected=domain_gate_rejected,
            research_role_rejected=research_role_rejected,
            auxiliary_pending_pool_rejected=auxiliary_pending_pool_rejected,
            legacy_total_rejected=(
                targeted_alignment_rejected
                + domain_gate_rejected
                + research_role_rejected
                + auxiliary_pending_pool_rejected
            ),
            duplicate_rejected=rejected_as_duplicate,
            post_targeted_candidate_count=post_targeted_candidate_count,
            post_domain_candidate_count=post_domain_candidate_count,
            post_role_candidate_count=post_role_candidate_count,
            post_auxiliary_pool_candidate_count=len(aligned_layer_candidates),
            auxiliary_pending_fulltext_retained_by_layer=dict(
                targeted_admission.get("auxiliary_pending_fulltext_retained_by_layer") or {}
            ),
            auxiliary_pending_fulltext_excluded_by_limit_by_layer=dict(
                targeted_admission.get("auxiliary_pending_fulltext_excluded_by_limit_by_layer") or {}
            ),
            auxiliary_pending_fulltext_layer_limits=dict(
                targeted_admission.get("auxiliary_pending_fulltext_layer_limits") or {}
            ),
            auxiliary_pre_fulltext_limit_enabled=bool(
                targeted_admission.get("auxiliary_pre_fulltext_limit_enabled")
            ),
            auxiliary_pre_fulltext_layer_policy=str(
                targeted_admission.get("auxiliary_pre_fulltext_layer_policy") or ""
            ),
            strict_admission_rejection_top_reasons=top_count_items(
                targeted_admission.get("strict_admission_rejection_reasons")
            ),
            coarse_prefilter_rejection_top_reasons=top_count_items(
                targeted_admission.get("coarse_prefilter_rejection_reasons")
            ),
            coarse_prefilter_rejection_samples=list(
                targeted_admission.get("coarse_prefilter_rejection_samples") or []
            )[:5],
            strict_admission_rejection_samples=list(
                targeted_admission.get("strict_admission_rejection_samples") or []
            )[:5],
            recovery_used=recovery_used,
            select_elapsed_ms=round((time.perf_counter() - select_started) * 1000.0, 3),
            domain_elapsed_ms=round(domain_elapsed_ms, 3),
            domain_cache_hits=domain_cache_hits,
            paper_domain_cache_hits=layer_paper_domain_cache_hits,
            domain_profile_revision=domain_profile_revision,
            l2_provider_retrieval_status=(
                l2_provider_retrieval_status if layer_name == SEMANTIC_SCHOLAR_L2_TOP_LATEST_LAYER else ""
            ),
            l2_provider_result_count=(
                l2_provider_result_count if layer_name == SEMANTIC_SCHOLAR_L2_TOP_LATEST_LAYER else 0
            ),
            l2_qualification=(
                l2_qualification if layer_name == SEMANTIC_SCHOLAR_L2_TOP_LATEST_LAYER else {}
            ),
            l2_retrieval_decision=(
                l2_retrieval_decision if layer_name == SEMANTIC_SCHOLAR_L2_TOP_LATEST_LAYER else {}
            ),
            l2_requested_evidence_kinds=(
                list(l2_requested_evidence_kinds)
                if layer_name == SEMANTIC_SCHOLAR_L2_TOP_LATEST_LAYER
                else []
            ),
            l2_alignment_rejection_samples=(
                list(l2_alignment_rejection_samples)
                if layer_name == SEMANTIC_SCHOLAR_L2_TOP_LATEST_LAYER
                else []
            ),
        )
        log_event(
            "SCIENCE",
            "literature_search_stage_timing",
            stage="select",
            layer=layer_name,
            candidates=len(candidates),
            selected=len(picked),
            elapsed_ms=round((time.perf_counter() - select_started) * 1000.0, 3),
            domain_elapsed_ms=round(domain_elapsed_ms, 3),
            domain_cache_hits=domain_cache_hits,
            paper_domain_cache_hits=layer_paper_domain_cache_hits,
            domain_profile_revision=domain_profile_revision,
        )
        unfilled_reserved_quota = max(0, target - len(picked))
        strata_reports.append(
            {
                **layer,
                "year_policy": year_policy,
                "target": target,
                "candidate_count": len(candidates),
                "raw_candidate_count": len(raw_candidates),
                "l2_provider_retrieval_status": (
                    l2_provider_retrieval_status if layer_name == SEMANTIC_SCHOLAR_L2_TOP_LATEST_LAYER else ""
                ),
                "l2_provider_result_count": (
                    l2_provider_result_count if layer_name == SEMANTIC_SCHOLAR_L2_TOP_LATEST_LAYER else 0
                ),
                "l2_qualification": (
                    l2_qualification if layer_name == SEMANTIC_SCHOLAR_L2_TOP_LATEST_LAYER else {}
                ),
                "l2_retrieval_decision": (
                    l2_retrieval_decision if layer_name == SEMANTIC_SCHOLAR_L2_TOP_LATEST_LAYER else {}
                ),
                "selected": len(picked),
                "domain_rejected": domain_gate_rejected,
                "targeted_alignment_rejected": targeted_alignment_rejected,
                "domain_gate_rejected": domain_gate_rejected,
                "research_role_rejected": research_role_rejected,
                "auxiliary_pending_pool_rejected": auxiliary_pending_pool_rejected,
                "legacy_total_rejected": (
                    targeted_alignment_rejected
                    + domain_gate_rejected
                    + research_role_rejected
                    + auxiliary_pending_pool_rejected
                ),
                "recovery_used": recovery_used,
                "preprint_recovery": preprint_recovery,
                "carried_to_next": 0,
                "unfilled_reserved_quota": unfilled_reserved_quota,
            }
        )
        if len(selected_results) >= max_results:
            break

    review_promotions = promote_high_impact_l4_reviews(selected_results, strata_reports, quotas)
    if review_promotions:
        log_event(
            "SCIENCE",
            "high_impact_review_reclassified_from_l4",
            count=len(review_promotions),
            titles=[str(item.get("title") or "")[:100] for item in review_promotions],
        )
    selected_regular = sum(1 for item in selected_results if item.get("stratified_layer") == "L4_regular")
    regular_needed = max(0, int(quotas.get("L4_regular", 0)) - selected_regular)
    if regular_needed:
        blocks = fetch_regular_backfill_blocks(
            query,
            layer_providers,
            regular_needed,
            query_plan=query_plan,
            domain=domain,
            preprint_layers=allowed_preprint_layers,
            preprint_required_anchor_groups=required_preprint_anchor_groups,
            single_paper_serial=single_paper_serial,
            anchor_contract=effective_anchor_contract,
            discipline_taxonomy=discipline_taxonomy,
        )
        provider_blocks.extend(blocks)
        select_started = time.perf_counter()
        candidates = prioritize_candidates_for_question_card(
            [
                item
                for item in rank_literature_results(ranking_query, dedupe_literature_results(flatten_literature_results(blocks)))
                if stratified_candidate_matches(
                    "L4_regular",
                    item,
                    allow_historical_direct_evidence=direct_evidence_mode,
                )
            ],
            normalized_question_card,
            use_llm=use_llm,
            domain_assessment_cache=paper_domain_assessment_cache,
        )
        domain_elapsed_ms = 0.0
        domain_cache_hits = 0
        picked = []
        rejected_for_domain = 0
        for candidate in candidates:
            if not admits_targeted_candidate(
                candidate,
                admission_level="import",
            ):
                rejected_for_domain += 1
                continue
            rejected, domain_cache_hit, candidate_domain_ms = evaluate_candidate_domain_gate(
                candidate,
                domain=domain,
                query=query,
                domain_profile=domain_profile,
                domain_profile_revision=domain_profile_revision,
                assessment_cache=shared_domain_gate_cache,
            )
            domain_elapsed_ms += candidate_domain_ms
            domain_cache_hits += int(domain_cache_hit)
            if rejected:
                rejected_for_domain += 1
                continue
            if (
                candidate.get("research_role_auto_selectable") is False
                and not candidate.get("pending_full_text_verification")
            ):
                rejected_for_domain += 1
                continue
            key = literature_result_unique_key(candidate)
            if key in seen:
                continue
            seen.add(key)
            item = dict(candidate)
            item["stratified_layer"] = "L4_regular"
            item["stratified_label"] = "other formal published source pending evidence classification"
            item["retrieval_layer"] = "L4_other_formal_source"
            item["year_policy"] = direct_evidence_year_policy() if direct_evidence_mode else stratified_year_policy("L4_regular")
            item["_why_selected"] = stratified_selection_reason("L4_regular", item)
            if not retains_auxiliary_pending_candidate(item):
                continue
            picked.append(item)
            if len(picked) >= regular_needed:
                break
        selected_results.extend(picked)
        strata_reports.append(
            {
                "layer": "L4_regular_backfill",
                "label": "regular journal / quota backfill",
                "year_policy": direct_evidence_year_policy() if direct_evidence_mode else stratified_year_policy("L4_regular"),
                "quota": regular_needed,
                "target": regular_needed,
                "candidate_count": len(candidates),
                "selected": len(picked),
                "domain_rejected": rejected_for_domain,
                "carried_to_next": 0,
                "unfilled_reserved_quota": max(0, regular_needed - len(picked)),
            }
        )
        log_event(
            "SCIENCE",
            "literature_search_stage_timing",
            stage="select",
            layer="L4_regular_backfill",
            candidates=len(candidates),
            selected=len(picked),
            elapsed_ms=round((time.perf_counter() - select_started) * 1000.0, 3),
            domain_elapsed_ms=round(domain_elapsed_ms, 3),
            domain_cache_hits=domain_cache_hits,
        )

    controlled_backfill = controlled_l4_backfill_budget(strata_reports)
    controlled_needed = int(controlled_backfill["quota"])
    if controlled_needed:
        blocks = fetch_regular_backfill_blocks(
            query,
            layer_providers,
            controlled_needed,
            query_plan=query_plan,
            domain=domain,
            preprint_layers=allowed_preprint_layers,
            preprint_required_anchor_groups=required_preprint_anchor_groups,
            single_paper_serial=single_paper_serial,
            anchor_contract=effective_anchor_contract,
            discipline_taxonomy=discipline_taxonomy,
        )
        provider_blocks.extend(blocks)
        select_started = time.perf_counter()
        candidates = prioritize_candidates_for_question_card(
            [
                item
                for item in rank_literature_results(ranking_query, dedupe_literature_results(flatten_literature_results(blocks)))
                if stratified_candidate_matches(
                    "L4_regular",
                    item,
                    allow_historical_direct_evidence=direct_evidence_mode,
                )
            ],
            normalized_question_card,
            use_llm=use_llm,
            domain_assessment_cache=paper_domain_assessment_cache,
        )
        domain_elapsed_ms = 0.0
        domain_cache_hits = 0
        picked = []
        rejected_for_domain = 0
        for candidate in candidates:
            if not admits_targeted_candidate(
                candidate,
                admission_level="import",
            ):
                rejected_for_domain += 1
                continue
            rejected, domain_cache_hit, candidate_domain_ms = evaluate_candidate_domain_gate(
                candidate,
                domain=domain,
                query=query,
                domain_profile=domain_profile,
                domain_profile_revision=domain_profile_revision,
                assessment_cache=shared_domain_gate_cache,
            )
            domain_elapsed_ms += candidate_domain_ms
            domain_cache_hits += int(domain_cache_hit)
            if rejected:
                rejected_for_domain += 1
                continue
            if (
                candidate.get("research_role_auto_selectable") is False
                and not candidate.get("pending_full_text_verification")
            ):
                rejected_for_domain += 1
                continue
            key = literature_result_unique_key(candidate)
            if key in seen:
                continue
            seen.add(key)
            item = dict(candidate)
            item["stratified_layer"] = "L4_regular"
            item["stratified_label"] = "other formal published source pending evidence classification"
            item["retrieval_layer"] = "L4_other_formal_source"
            item["year_policy"] = direct_evidence_year_policy() if direct_evidence_mode else stratified_year_policy("L4_regular")
            item["stratified_recovery"] = "controlled_l4_backfill"
            item["backfilled_reserved_layers"] = controlled_backfill["source_layers"]
            item["_why_selected"] = "controlled_l4_backfill_for_missing_special_evidence"
            if not retains_auxiliary_pending_candidate(item):
                continue
            picked.append(item)
            if len(picked) >= controlled_needed:
                break
        selected_results.extend(picked)
        strata_reports.append(
            {
                "layer": "L4_controlled_backfill",
                "label": "capped regular-evidence replacement for unfilled special layers",
                "year_policy": direct_evidence_year_policy() if direct_evidence_mode else stratified_year_policy("L4_regular"),
                "quota": controlled_needed,
                "target": controlled_needed,
                "candidate_count": len(candidates),
                "selected": len(picked),
                "domain_rejected": rejected_for_domain,
                "source_layers": controlled_backfill["source_layers"],
                "carried_to_next": 0,
                "unfilled_reserved_quota": max(0, controlled_needed - len(picked)),
            }
        )
        log_event(
            "SCIENCE",
            "literature_search_stage_timing",
            stage="select",
            layer="L4_controlled_backfill",
            candidates=len(candidates),
            selected=len(picked),
            elapsed_ms=round((time.perf_counter() - select_started) * 1000.0, 3),
            domain_elapsed_ms=round(domain_elapsed_ms, 3),
            domain_cache_hits=domain_cache_hits,
        )

    # ---- Low-result fallback: synonym expansion ----
    # If we still have fewer than 25 % of the requested results after the
    # full stratified cascade + regular backfill, try one more pass with an
    # expanded query that includes synonyms.  This helps when the original
    # domain tags are too specific for the provider's semantic index.
    low_result_threshold = max(3, max_results // 4)
    synonym_expansion_used = False
    selected_regular = sum(1 for item in selected_results if item.get("stratified_layer") == "L4_regular")
    regular_remaining = max(0, int(quotas.get("L4_regular", 0)) - selected_regular)
    if (
        not single_paper_serial
        and not contract_lexical_calibration_active
        and len(selected_results) < low_result_threshold
        and regular_remaining
    ):
        expanded = expand_query_with_synonyms(query)
        if expanded != query:
            synonym_expansion_used = True
            log_event("SCIENCE", "synonym_expansion_fallback", original_results=len(selected_results), expanded_query=expanded[:120])
            try:
                expanded_blocks: list[dict[str, Any]] = []
                for provider in layer_providers:
                    exp_q = expanded
                    try:
                        block = search_literature_provider_block(provider, exp_q, max_results=max(8, max_results // len(selected)))
                    except Exception:
                        continue
                    expanded_blocks.append(block)
                for candidate in prioritize_candidates_for_question_card(
                    [
                        item
                        for item in rank_literature_results(expanded, dedupe_literature_results(flatten_literature_results(expanded_blocks)))
                        if stratified_candidate_matches(
                            "L4_regular",
                            item,
                            allow_historical_direct_evidence=direct_evidence_mode,
                        )
                    ],
                    normalized_question_card,
                    use_llm=use_llm,
                    domain_assessment_cache=paper_domain_assessment_cache,
                ):
                    if not admits_targeted_candidate(
                        candidate,
                        admission_level="import",
                    ):
                        continue
                    rejected, _, _ = evaluate_candidate_domain_gate(
                        candidate,
                        domain=domain,
                        query=query,
                        domain_profile=domain_profile,
                        domain_profile_revision=domain_profile_revision,
                        assessment_cache=shared_domain_gate_cache,
                    )
                    if rejected:
                        continue
                    if (
                        candidate.get("research_role_auto_selectable") is False
                        and not candidate.get("pending_full_text_verification")
                    ):
                        continue
                    key = literature_result_unique_key(candidate)
                    if key in seen:
                        continue
                    seen.add(key)
                    item = dict(candidate)
                    item["stratified_layer"] = "L4_regular"
                    item["stratified_label"] = "other formal published source pending evidence classification"
                    item["retrieval_layer"] = "L4_other_formal_source"
                    item["year_policy"] = direct_evidence_year_policy() if direct_evidence_mode else stratified_year_policy("L4_regular")
                    item["_why_selected"] = "synonym_expansion_fallback"
                    if not retains_auxiliary_pending_candidate(item):
                        continue
                    selected_results.append(item)
                    if sum(1 for item in selected_results if item.get("stratified_layer") == "L4_regular") >= int(quotas.get("L4_regular", 0)):
                        break
                provider_blocks.extend(expanded_blocks)
                strata_reports.append(
                    {
                        "layer": "synonym_expansion",
                        "label": "synonym-expanded backfill",
                        "year_policy": direct_evidence_year_policy() if direct_evidence_mode else stratified_year_policy("L4_regular"),
                        "quota": regular_remaining,
                        "target": regular_remaining,
                        "selected": min(regular_remaining, sum(1 for item in selected_results if item.get("stratified_label") == "synonym-expanded backfill")),
                        "expanded_query": expanded[:200],
                    }
                )
            except Exception as exc:
                log_event("WARN", "synonym_expansion_failed", error=str(exc)[:200])

    # Enforce controller-owned candidate exclusions after every optional
    # supplement/backfill path, before both the returned result set and its
    # aligned reserve are materialised.
    if excluded_candidate_key_set:
        retained_selected_results: list[dict[str, Any]] = []
        for item in selected_results:
            candidate_key = literature_result_unique_key(item)
            if candidate_key and candidate_key in excluded_candidate_key_set:
                cross_round_duplicate_keys.add(candidate_key)
                continue
            retained_selected_results.append(item)
        selected_results = retained_selected_results
        targeted_admission["cross_round_duplicates_excluded"] = len(cross_round_duplicate_keys)

    preprint_exploration_buffer = [
        {
            **dict(item),
            "preprint_exploration_buffer": True,
            "evidence_admission_state": "PREPRINT_PENDING_FULLTEXT_AND_SOURCE_AUDIT",
            "direct_core_evidence_allowed": False,
        }
        for item in selected_results
        if str(item.get("stratified_layer") or "") == "L3_preprint"
    ][:preprint_exploration_buffer_limit or int(quotas.get("L3_preprint") or 0)]
    evidence_selected_results = [
        item for item in selected_results
        if str(item.get("stratified_layer") or "") != "L3_preprint"
    ]
    final_results = diverse_rerank_literature_results(evidence_selected_results, max_results=max_results)
    # ``exclude_candidate_keys`` is a controller-level identity boundary. It
    # must hold even when a candidate bypassed optional alignment prefilters
    # or was introduced by an L2 supplement/backfill path.
    if excluded_candidate_key_set:
        retained_results: list[dict[str, Any]] = []
        for item in final_results:
            candidate_key = literature_result_unique_key(item)
            if candidate_key and candidate_key in excluded_candidate_key_set:
                cross_round_duplicate_keys.add(candidate_key)
                continue
            retained_results.append(item)
        final_results = retained_results
        targeted_admission["cross_round_duplicates_excluded"] = len(cross_round_duplicate_keys)
    final_keys = {literature_result_unique_key(item) for item in final_results}
    # Preserve every strictly aligned overflow candidate as a non-authoritative
    # import/backfill reserve.  It is not counted in total_results and cannot
    # satisfy the gate until normal import acquires full text and reruns the
    # alignment/genre audit.
    aligned_reserve_results = dedupe_literature_results(
        [
            item
            for item in evidence_selected_results + aligned_reserve_candidates
            if literature_result_unique_key(item) not in final_keys
        ]
    )
    aligned_reserve_results.sort(
        key=lambda item: (
            0
            if (
                item.get("open_access_pdf")
                or item.get("full_text_url")
                or item.get("pmc_id")
            )
            else 1,
            -float(item.get("relevance_score") or 0.0),
            str(item.get("title") or ""),
        )
    )
    if candidate_alignment_contract:
        aligned_reserve_results = aligned_reserve_results[
            : max(0, deep_limit - len(final_results))
        ]
    else:
        aligned_reserve_results = []
    final_results, venue_metadata_enrichment = enrich_selected_venue_metadata_with_openalex(final_results)
    for item in final_results:
        if str(item.get("_why_selected") or "").startswith("Selected as"):
            item["_why_selected"] = stratified_selection_reason(
                str(item.get("stratified_layer") or "L4_regular"),
                item,
            )
    for index, item in enumerate(final_results):
        item["result_index"] = index
        item["search_id"] = search_id
    for offset, item in enumerate(aligned_reserve_results, start=len(final_results)):
        item["result_index"] = offset
        item["search_id"] = search_id
        item["candidate_pool_role"] = "STRICTLY_ALIGNED_IMPORT_BACKFILL_RESERVE"
        item["may_fill_primary_evidence_slots"] = False
    targeted_admission["aligned_reserve_count"] = len(aligned_reserve_results)
    knowledge_pyramid = build_knowledge_pyramid(query, final_results, strata_reports)
    # L3 is exploratory only.  Its absence must not block an evidence slot or
    # make a sub-hypothesis appear deficient.
    evidence_window_alerts: list[dict[str, Any]] = []
    l2_report = next(
        (
            report
            for report in strata_reports
            if str(report.get("layer") or "") == SEMANTIC_SCHOLAR_L2_TOP_LATEST_LAYER
        ),
        {},
    )
    l2_selected_count = int(l2_report.get("selected") or 0)
    l2_target_count = max(0, int(quotas.get(SEMANTIC_SCHOLAR_L2_TOP_LATEST_LAYER, 0)))
    if l2_target_count <= 0:
        l2_evidence_shortage = {
            "status": "not_requested",
            "target": 0,
            "selected": 0,
            "reason": "L2 quota is zero for this retrieval.",
        }
    elif l2_selected_count >= l2_target_count:
        l2_evidence_shortage = {
            "status": "satisfied",
            "target": l2_target_count,
            "selected": l2_selected_count,
            "reason": "Enough recent, primary, aligned L2 evidence was selected without L4 substitution.",
        }
    else:
        eligible_after_alignment = int(
            l2_retrieval_decision.get("final_eligible_after_alignment_count") or 0
        )
        if eligible_after_alignment < l2_target_count:
            reason = (
                "No sufficient recent, primary, venue-verified, project-aligned L2 evidence remained "
                "after broad-pool reuse and conditional supplements."
            )
        else:
            reason = (
                "Qualifying L2 candidates existed but fewer than the protected quota survived final "
                "cross-layer de-duplication or selection; no L4 evidence was substituted."
            )
        l2_evidence_shortage = {
            "status": "evidence_shortage",
            "target": l2_target_count,
            "selected": l2_selected_count,
            "eligible_after_alignment_count": eligible_after_alignment,
            "reason": reason,
            "retrieval_status": l2_provider_retrieval_status,
        }
    l2_provider_retrieval = {
        "providers": {
            "openalex": {
                **dict(l2_provider_details.get("openalex") or {"status": "not_requested", "result_count": 0, "request_count": 0}),
                "zero_result_recovery_max_attempts": 0,
            },
            "semantic_scholar": {
                **dict(l2_provider_details.get("semantic_scholar") or {"status": "not_requested", "result_count": 0, "request_count": 0}),
                "zero_result_recovery_max_attempts": 0,
            },
        },
        "status": l2_provider_retrieval_status,
        "result_count": l2_provider_result_count,
        "request_count": sum(int(detail.get("request_count") or 0) for detail in l2_provider_details.values()),
        "qualification": l2_qualification,
        "decision": l2_retrieval_decision,
        "evidence_shortage": l2_evidence_shortage,
    }
    provider_layer_strategy = {
        "L0_review": "OpenAlex/PubMed broad discovery; explicit Semantic Scholar compatibility batch when requested.",
        "L1_milestone": "OpenAlex/PubMed broad discovery plus the separate historical-foundation workflow.",
        "L2_top_latest": "Reuse unified broad OpenAlex/PubMed candidates first; only a strict aligned shortfall triggers one focused OpenAlex supplement, then at most one bounded-retry Semantic Scholar supplement; no L4 backfill.",
        "L3_preprint": "Specialist preprint providers.",
        "L4_regular": "OpenAlex/PubMed broad discovery; explicit Semantic Scholar compatibility batch when requested.",
    }
    # This cascade intentionally keeps L0-L4 pools separate. Every branch
    # carrying an abstract edge plan receives a provider execution receipt.
    # A provider may lower Boolean/field syntax, but must retain the planned
    # object and edge anchor groups; byte-identical query fingerprints are not
    # required.
    strict_plan_by_branch = {
        str(plan.get("branch") or "primary"): dict(plan)
        for plan in query_plan
        if isinstance(plan, dict)
        and (
            isinstance(plan.get("abstract_edge_query_plan"), dict)
            or is_contract_lexical_calibration_plan(plan)
        )
    }
    strict_query_plan_execution_audits: list[dict[str, Any]] = []
    if strict_plan_by_branch:
        for block in provider_blocks:
            if not isinstance(block, dict):
                continue
            branches = [str(block.get("query_branch") or "primary")]
            branches.extend(
                str(value)
                for value in (block.get("matched_query_branches") or [])
                if str(value).strip()
            )
            for branch in dict.fromkeys(branches):
                plan = strict_plan_by_branch.get(branch)
                if not plan:
                    continue
                audit = audit_strict_query_plan_execution(plan, block)
                strict_query_plan_execution_audits.append(audit)
                block.setdefault("strict_query_plan_execution_audits", []).append(audit)
                block.setdefault("provider_execution_receipts", []).append(
                    dict(audit.get("provider_execution_receipt") or {})
                )
        expected_fingerprints = {
            str(plan.get("query_fingerprint") or query_execution_fingerprint(plan.get("query")))
            for plan in strict_plan_by_branch.values()
            if str(plan.get("query") or "").strip()
        }
        allowed_fingerprints = {
            str(audit.get("planned_query_fingerprint") or "")
            for audit in strict_query_plan_execution_audits
            if audit.get("allowed") is True
        }
        execution_violations = [
            audit for audit in strict_query_plan_execution_audits
            if audit.get("execution_status") in {
                "PLAN_PROVIDER_QUERY_MISMATCH", "PLAN_UNEXECUTABLE",
            }
        ]
        strict_query_plan_execution_summary = {
            "schema_version": "strict_query_plan_execution_summary_v1",
            "active": True,
            "planned_branch_count": len(expected_fingerprints),
            "planned_query_fingerprints": sorted(expected_fingerprints),
            "allowed_executed_query_fingerprints": sorted(allowed_fingerprints),
            "all_planned_branches_executed": expected_fingerprints.issubset(allowed_fingerprints),
            "all_provider_dispatches_conform": not execution_violations,
            "violation_count": len(execution_violations),
            "violation_status_counts": dict(Counter(
                str(audit.get("execution_status") or "UNKNOWN")
                for audit in execution_violations
            )),
            "policy": "provider_lowering_requires_required_anchor_group_retention",
        }
    else:
        strict_query_plan_execution_summary = {
            "schema_version": "strict_query_plan_execution_summary_v1",
            "active": False,
            "planned_branch_count": 0,
            "planned_query_fingerprints": [],
            "allowed_executed_query_fingerprints": [],
            "all_planned_branches_executed": True,
            "all_provider_dispatches_conform": True,
            "violation_count": 0,
            "violation_status_counts": {},
        }
    # The audit below records every actual provider query, but never globally
    # RRF-fuses layers or allows discovery ordering to replace the layer quotas
    # and evidence gates that follow.
    local_non_submission_statuses = {
        "skipped",
        "shared_candidate_pool_reused",
        "query_plan_contract_error",
        "provider_query_compilation_error",
        "provider_query_syntax_error",
    }
    for block in provider_blocks:
        if not isinstance(block, dict) or "submitted_to_provider" in block:
            continue
        status = str(block.get("status") or "")
        block["submitted_to_provider"] = status not in local_non_submission_statuses
    retrieval_query_audits: list[dict[str, Any]] = []
    provider_attempts: list[dict[str, Any]] = []
    for block in provider_blocks:
        if not isinstance(block, dict):
            continue
        provider = str(block.get("provider") or "")
        provider_query = str(block.get("query") or "")
        if provider and provider_query:
            existing_audit = block.get("query_compilation")
            if isinstance(existing_audit, dict):
                audit = dict(existing_audit)
                audit["audit_timing"] = "pre_dispatch"
            else:
                audit = compile_provider_query(
                    provider,
                    provider_query,
                    anchor_contract=effective_anchor_contract,
                )
                audit["audit_timing"] = "captured_after_dispatch_legacy_path"
                block["query_compilation"] = audit
            retrieval_query_audits.append(audit)
        provider_attempts.append(
            {
                "provider": provider,
                "status": block.get("status"),
                "query": provider_query,
                "attempted_queries": block.get("attempted_queries", []),
                "query_revisions": block.get("query_revisions", []),
                "query_branch": block.get("query_branch", ""),
                "stratified_layer": block.get("stratified_layer", ""),
                "result_count": len(block.get("results") or []),
                "cache_hit": block.get("cache_hit"),
                "zero_result_cache_hit": block.get("zero_result_cache_hit"),
                "submitted_to_provider": bool(block.get("submitted_to_provider")),
                "failure_stage": block.get("failure_stage", ""),
                "failure_kind": block.get("failure_kind", ""),
                "compilation_fingerprint": (
                    (block.get("query_compilation") or {}).get("compilation_fingerprint")
                    if isinstance(block.get("query_compilation"), Mapping)
                    else ""
                ),
                "discipline_filter_audit": block.get("discipline_filter_audit", {}),
                "error": block.get("error", ""),
            }
        )
    retrieval_run = create_retrieval_run(
        search_id=search_id,
        query=query,
        source_query=source_query,
        providers=selected,
        anchor_contract=effective_anchor_contract,
        provider_attempts=provider_attempts,
        query_compilations=retrieval_query_audits,
        candidate_fusion={
            "method": "layer_constrained_weighted_rrf_v1",
            "global_rrf_applied": False,
            "reason": "RRF orders candidates only inside each L0-L4 pool; quotas, source roles, and evidence gates remain protected.",
            "provider_block_count": len(provider_blocks),
            "selected_candidate_count": len(final_results),
            "layer_fusions": layer_fusion_reports,
        },
        discipline_taxonomy=discipline_taxonomy,
        strategy="stratified_layer_constrained_candidate_discovery",
    )
    provider_raw = sum(
        len(block.get("results") or [])
        for block in provider_blocks
        if isinstance(block, dict)
    )
    provider_deduplicated = len(
        dedupe_literature_results(
            flatten_literature_results(
                [block for block in provider_blocks if isinstance(block, dict)]
            )
        )
    )
    provider_candidates = flatten_literature_results(
        [block for block in provider_blocks if isinstance(block, dict)]
    )
    query_variant_execution_v3 = summarize_query_variant_execution_v3(provider_blocks)
    if query_variant_execution_v3.get("provider_outcomes"):
        if not current_v3_work_item_plan:
            configured_providers = list(
                dict.fromkeys([*configured_providers, *requested_providers])
            )
        query_variant_execution_v3["configured_providers"] = configured_providers
        query_variant_execution_v3["skipped_providers"] = list(skipped_providers)
        query_variant_execution_v3["dispatched_providers"] = list(
            dict.fromkeys(query_variant_execution_v3.get("dispatched_providers") or [])
        )
        deferred_skips = [
            dict(item)
            for item in skipped_providers
            if isinstance(item, dict)
            and any(
                marker in str(item.get("reason") or "").casefold()
                for marker in ("429", "rate", "circuit", "cooldown", "deferred")
            )
        ]
        if deferred_skips and not int(query_variant_execution_v3.get("raw_provider_result_count") or 0):
            query_variant_execution_v3["deferred_providers"] = list(
                query_variant_execution_v3.get("deferred_providers") or []
            ) + deferred_skips
            query_variant_execution_v3["terminal_outcome"] = "PROVIDER_DEFERRED"
    elif v3_allowed_providers and skipped_providers:
        deferred_skips = [
            dict(item)
            for item in skipped_providers
            if isinstance(item, dict)
            and str(item.get("provider") or "") in v3_allowed_providers
            and any(
                marker in str(item.get("reason") or "").casefold()
                for marker in ("429", "rate", "circuit", "cooldown", "deferred")
            )
        ]
        if deferred_skips:
            query_variant_execution_v3 = {
                "schema_version": "provider_variant_execution_v3",
                "policy": "typed_provider_execution_v3",
                "semantic_fingerprint": str(
                    next(
                        (
                            plan.get("semantic_fingerprint")
                            or (plan.get("retrieval_spec_v3") or {}).get("semantic_fingerprint")
                            for plan in query_plan
                            if isinstance(plan, dict)
                        ),
                        "",
                    )
                    or ""
                ),
                "terminal_outcome": "PROVIDER_DEFERRED",
                "raw_provider_result_count": 0,
                "attempts": [],
                "configured_providers": configured_providers,
                "dispatched_providers": [],
                "skipped_providers": list(skipped_providers),
                "deferred_providers": deferred_skips,
                "provider_error_count": 0,
                "provider_submission_count": 0,
                "provider_terminal_response_count": 0,
                "local_compilation_rejection_count": 0,
                "remote_provider_error_count": 0,
                "provider_outcomes": [],
                "scientific_evidence_coverage": "NOT_INFERRED_FROM_PROVIDER_OUTCOME",
            }
    def candidate_contains_any(candidate: dict[str, Any], markers: tuple[str, ...]) -> bool:
        text = normalize_space(
            " ".join(
                str(candidate.get(key) or "")
                for key in ("title", "abstract", "venue", "publication_type")
            )
        ).lower()
        return any(marker in text for marker in markers)

    ai_drift_detected = sum(
        1
        for candidate in provider_candidates
        if isinstance(candidate, dict)
        and candidate_contains_any(
            candidate,
            (
                "artificial intelligence", "machine learning", "deep learning",
                "large language model", "language model", "chatgpt", " ai ",
            ),
        )
    )
    generic_neuroscience_drift_detected = sum(
        1
        for candidate in provider_candidates
        if isinstance(candidate, dict)
        and candidate_contains_any(
            candidate,
            (
                "neural", "neuronal", "brain", "cognitive", "memory",
                "hippocampus", "reward", "addiction",
            ),
        )
    )
    query_pollution_diagnostics = {
        **dict(query_contamination_summary),
        "provider_candidates_from_low_signal_query": (
            provider_raw
            if query_contamination_summary.get("query_contamination_risk")
            in {"medium", "high"}
            else 0
        ),
        "imported_from_modifier_only_match": int(
            targeted_admission.get("coarse_prefilter_component_bridge_modifier_only_matches")
            or 0
        ),
        "modifier_only_match_candidates": int(
            targeted_admission.get("coarse_prefilter_component_bridge_modifier_only_matches")
            or 0
        ),
        "component_bridge_support_missing_candidates": int(
            targeted_admission.get("coarse_prefilter_component_bridge_support_missing")
            or 0
        ),
        "expanded_exclusion_fast_reject_candidates": int(
            targeted_admission.get("coarse_prefilter_scope_forbidden_expanded_hits")
            or 0
        ),
        "ai_drift_detected": ai_drift_detected,
        "generic_neuroscience_drift_detected": generic_neuroscience_drift_detected,
    }
    targeted_admission["query_pollution_diagnostics"] = dict(
        query_pollution_diagnostics
    )
    candidate_pool_diagnostics = {
        "schema_version": "subhypothesis_candidate_pool_v3",
        "provider_raw": provider_raw,
        "provider_deduplicated": provider_deduplicated,
        "coarse_prefilter_evaluated": int(targeted_admission.get("coarse_prefilter_evaluated") or 0),
        "coarse_prefilter_accepted": int(targeted_admission.get("coarse_prefilter_accepted") or 0),
        "coarse_prefilter_rejected": int(targeted_admission.get("coarse_prefilter_rejected") or 0),
        "coarse_prefilter_memo_hits": int(
            targeted_admission.get("coarse_prefilter_memo_hits") or 0
        ),
        "coarse_prefilter_local_cache_hits": int(
            targeted_admission.get("coarse_prefilter_local_cache_hits") or 0
        ),
        "cross_round_duplicates_excluded": len(cross_round_duplicate_keys),
        "provider_candidates_before_cross_task_dedup": provider_raw,
        "removed_as_previously_seen": len(cross_round_duplicate_keys),
        "new_candidate_count": len(final_results),
        "previously_imported_source_count": max(0, int(previously_imported_source_count or 0)),
        "shared_raw_candidate_pool_available_count": shared_raw_candidate_pool_available_count,
        "shared_raw_candidate_pool_preprint_excluded_count": shared_raw_preprint_excluded,
        "shared_raw_candidate_pool_selected_count": sum(
            1
            for candidate in final_results
            if isinstance(candidate, dict)
            and str(literature_result_unique_key(candidate) or "").strip()
            in shared_raw_candidate_keys
        ),
        "shared_raw_candidate_pool_policy": (
            "raw_metadata_reenters_current_slot_layer_domain_and_fulltext_gates"
        ),
        "deep_alignment_pool": int(targeted_admission.get("deep_pool_selected") or 0),
        "deep_alignment_candidate_limit": int(targeted_admission.get("deep_alignment_candidate_limit") or 0),
        "deep_alignment_pool_limits_by_layer": dict(targeted_admission.get("deep_pool_limits_by_layer") or {}),
        "deep_alignment_pool_by_layer": dict(targeted_admission.get("deep_pool_by_layer") or {}),
        "strict_alignment_evaluated": int(targeted_admission.get("evaluated") or 0),
        "strict_alignment_accepted": int(targeted_admission.get("accepted") or 0),
        "strict_alignment_rejected": int(targeted_admission.get("rejected") or 0),
        "strict_admission_memo_hits": int(
            targeted_admission.get("strict_admission_memo_hits") or 0
        ),
        "strict_admission_local_cache_hits": int(
            targeted_admission.get("strict_admission_local_cache_hits") or 0
        ),
        "coarse_prefilter_rejection_reason_counts": dict(
            targeted_admission.get("coarse_prefilter_rejection_reasons") or {}
        ),
        "strict_admission_rejection_reason_counts": dict(
            targeted_admission.get("strict_admission_rejection_reasons") or {}
        ),
        "coarse_prefilter_rejection_samples": list(
            targeted_admission.get("coarse_prefilter_rejection_samples") or []
        )[:8],
        "strict_admission_rejection_samples": list(
            targeted_admission.get("strict_admission_rejection_samples") or []
        )[:8],
        "object_anchor_policy_mode": next(
            iter(
                sorted(
                    dict(
                        targeted_admission.get(
                            "coarse_prefilter_object_anchor_policy_mode_counts"
                        )
                        or {}
                    ).items(),
                    key=lambda item: (-int(item[1] or 0), str(item[0])),
                )
            ),
            ("", 0),
        )[0],
        "object_anchor_policy_mode_counts": dict(
            targeted_admission.get("coarse_prefilter_object_anchor_policy_mode_counts") or {}
        ),
        "strong_object_anchors": list(
            targeted_admission.get("coarse_prefilter_strong_object_anchors") or []
        )[:16],
        "strong_object_hits": list(
            targeted_admission.get("coarse_prefilter_strong_object_hits") or []
        )[:16],
        "semantic_equivalent_object_hits": list(
            targeted_admission.get("coarse_prefilter_semantic_equivalent_object_hits") or []
        )[:16],
        "related_context_object_hits": list(
            targeted_admission.get("coarse_prefilter_related_context_object_hits") or []
        )[:16],
        "auxiliary_object_hits": list(
            targeted_admission.get("coarse_prefilter_auxiliary_object_hits") or []
        )[:16],
        "matched_axes": list(
            targeted_admission.get("coarse_prefilter_matched_axes") or []
        )[:8],
        "matched_axis_counts": dict(
            targeted_admission.get("coarse_prefilter_matched_axis_counts") or {}
        ),
        "auxiliary_pre_fulltext_limit": int(
            targeted_admission.get("auxiliary_pre_fulltext_limit") or 0
        ),
        "auxiliary_pre_fulltext_limit_enabled": bool(
            targeted_admission.get("auxiliary_pre_fulltext_limit_enabled")
        ),
        "auxiliary_pre_fulltext_layer_policy": str(
            targeted_admission.get("auxiliary_pre_fulltext_layer_policy") or ""
        ),
        "auxiliary_pending_fulltext_layer_limits": dict(
            targeted_admission.get("auxiliary_pending_fulltext_layer_limits") or {}
        ),
        "auxiliary_pending_fulltext_admitted": int(
            targeted_admission.get("auxiliary_pending_fulltext_admitted") or 0
        ),
        "auxiliary_pending_fulltext_admitted_by_layer": dict(
            targeted_admission.get("auxiliary_pending_fulltext_admitted_by_layer") or {}
        ),
        "auxiliary_pending_fulltext_retained": int(
            targeted_admission.get("auxiliary_pending_fulltext_retained") or 0
        ),
        "auxiliary_pending_fulltext_retained_by_layer": dict(
            targeted_admission.get("auxiliary_pending_fulltext_retained_by_layer") or {}
        ),
        "auxiliary_pending_fulltext_excluded_by_limit": int(
            targeted_admission.get("auxiliary_pending_fulltext_excluded_by_limit") or 0
        ),
        "auxiliary_pending_fulltext_excluded_by_limit_by_layer": dict(
            targeted_admission.get("auxiliary_pending_fulltext_excluded_by_limit_by_layer") or {}
        ),
        "stratified_returned": len(final_results),
        "strictly_aligned_reserve": len(aligned_reserve_results),
        "alignment_before_final_stratified_truncation": bool(candidate_alignment_contract),
        "query_contamination_audits": query_contamination_audits[:12],
        "query_contamination_summary": dict(query_contamination_summary),
        "query_pollution_diagnostics": query_pollution_diagnostics,
        "research_domain_profile": {
            "schema_version": str(
                domain_profile_artifact.get("schema_version") or ""
            ),
            "profile_revision": domain_profile_revision,
            "profile_source": str(
                domain_profile_artifact.get("profile_source") or ""
            ),
            "llm_call_count": int(use_llm),
            "elapsed_ms": domain_profile_artifact.get("elapsed_ms"),
        },
        "paper_domain_assessment_batches": dict(
            paper_domain_batch_diagnostics
        ),
        "paper_domain_assessment_cache_entries": len(
            paper_domain_assessment_cache
        ),
        "domain_gate_shared_cache_entries": len(shared_domain_gate_cache),
    }
    log_event(
        "SCIENCE",
        "alignment_admission_memoization_summary",
        project_id=project_id,
        sub_hypothesis_id=sub_hypothesis_id,
        search_id=search_id,
        coarse_prefilter_computed=int(
            targeted_admission.get("coarse_prefilter_evaluated") or 0
        ),
        coarse_prefilter_memo_hits=int(
            targeted_admission.get("coarse_prefilter_memo_hits") or 0
        ),
        coarse_prefilter_local_cache_hits=int(
            targeted_admission.get("coarse_prefilter_local_cache_hits") or 0
        ),
        strict_alignment_applied=int(targeted_admission.get("evaluated") or 0),
        strict_admission_memo_hits=int(
            targeted_admission.get("strict_admission_memo_hits") or 0
        ),
        strict_admission_local_cache_hits=int(
            targeted_admission.get("strict_admission_local_cache_hits") or 0
        ),
        memo_key_policy="paper_key_plus_sh_contract_hash_with_admission_level_and_evidence_kind_guard",
    )
    provider_parallelization = {
        "schema_version": "stratified_provider_parallelization_v1",
        "mode": (
            "parallel_broad_batches_deterministic_merge"
            if broad_provider_jobs
            else "no_parallel_broad_provider_batches"
        ),
        "providers": [name for name, _runner in broad_provider_jobs],
        "completed_providers": [
            name
            for name, _runner in broad_provider_jobs
            if name in broad_provider_results
        ],
        "deterministic_merge_order": [
            name
            for name in ("openalex", "sciencedirect", "pubmed", "semantic_scholar")
            if name in broad_provider_results
        ],
        "conditional_l2_supplement_excluded": True,
        "reason": (
            "Initial broad discovery/compatibility provider batches are independent and may start "
            "together; conditional L2 supplement remains gated by broad-pool qualification."
        ),
    }
    resolved_scope_kind = str(retrieval_scope_kind or "").strip()
    resolved_project_id = str(project_id or "").strip()
    resolved_sub_hypothesis_id = str(sub_hypothesis_id or "").strip()
    resolved_contract_hash = str(
        alignment_contract_hash
        or (candidate_alignment_contract or {}).get("contract_hash")
        or (retrieval_anchor_contract or {}).get("contract_hash")
        or ""
    ).strip()
    retrieval_scope = {
        "kind": (
            resolved_scope_kind
            or ("subhypothesis" if resolved_project_id and resolved_sub_hypothesis_id else "standalone")
        ),
        "project_id": resolved_project_id,
        "sub_hypothesis_id": resolved_sub_hypothesis_id,
        "alignment_contract_hash": resolved_contract_hash,
        "direct_evidence_eligible": bool(
            resolved_project_id
            and resolved_sub_hypothesis_id
            and resolved_contract_hash
            and (resolved_scope_kind or "subhypothesis") == "subhypothesis"
        ),
    }
    task_provenance = research_question_task_provenance(query_plan)
    search_record = {
        "search_id": search_id,
        "query": query,
        "source_query": source_query,
        "query_language": query_language,
        "synonym_expansion_used": synonym_expansion_used,
        "domain": domain,
        "discipline_taxonomy": discipline_taxonomy,
        "retrieval_scope": retrieval_scope,
        "research_question_task_provenance": task_provenance,
        "research_question_card": normalized_question_card,
        "candidate_alignment_contract": (
            dict(candidate_alignment_contract)
            if isinstance(candidate_alignment_contract, dict)
            else {}
        ),
        "targeted_admission": targeted_admission,
        "incoming_excluded_candidate_key_count": len(excluded_candidate_key_set),
        "cross_task_duplicates_excluded": len(cross_round_duplicate_keys),
        "provider_candidates_before_cross_task_dedup": provider_raw,
        "removed_as_previously_seen": len(cross_round_duplicate_keys),
        "new_candidate_count": len(final_results),
        "previously_imported_source_count": max(0, int(previously_imported_source_count or 0)),
        "candidate_pool_diagnostics": candidate_pool_diagnostics,
        "query_contamination_audits": query_contamination_audits,
        "query_contamination_summary": query_contamination_summary,
        "strict_query_plan_execution_audits": strict_query_plan_execution_audits,
        "strict_query_plan_execution_summary": strict_query_plan_execution_summary,
        "retrieval_anchor_contract": retrieval_anchor_contract if isinstance(retrieval_anchor_contract, dict) else {},
        "retrieval_mode": normalized_retrieval_mode,
        "direct_evidence_mode": bool(direct_evidence_mode),
        "focus_branches": focus_branches or [],
        "providers": selected,
        "configured_providers": configured_providers,
        "dispatched_providers": (
            list(query_variant_execution_v3.get("dispatched_providers") or [])
            if query_variant_execution_v3.get("provider_outcomes") else sorted({
                str(block.get("provider") or "")
                for block in provider_blocks
                if isinstance(block, dict)
                and bool(block.get("submitted_to_provider"))
                and str(block.get("provider") or "")
            })
        ),
        "skipped_providers": skipped_providers,
        "requested_providers": requested_providers,
        "provider_layer_strategy": provider_layer_strategy,
        "provider_parallelization": provider_parallelization,
        "l2_provider_retrieval": l2_provider_retrieval,
        "l2_evidence_shortage": l2_evidence_shortage,
        "pubmed_disabled_by_policy": pubmed_disabled_by_policy,
        "pubmed_excluded_by_domain": pubmed_excluded_by_domain,
        "preprint_layers": sorted(allowed_preprint_layers),
        "preprint_exploration_buffer_active": preprint_exploration_buffer_active,
        "preprint_exploration_buffer_limit": preprint_exploration_buffer_limit,
        "preprint_exploration_buffer": preprint_exploration_buffer,
        "preprint_scan_limit": preprint_scan_limit,
        "preprint_provider_result_target": preprint_provider_result_target,
        "createdAt": time.time(),
        "strategy": "stratified_cascade",
        "single_paper_serial": single_paper_serial,
        "query_plan": query_plan,
        "strata": strata_reports,
        "knowledge_pyramid": knowledge_pyramid,
        "evidence_window_alerts": evidence_window_alerts,
        "venue_metadata_enrichment": venue_metadata_enrichment,
        "total_results": len(final_results),
        "results": final_results,
        "aligned_reserve_count": len(aligned_reserve_results),
        "aligned_reserve_results": aligned_reserve_results,
        "provider_blocks": provider_blocks,
        "query_variant_execution_v3": query_variant_execution_v3,
        "retrieval_run": retrieval_run,
    }
    save_search(search_record)
    response = {
        "search_id": search_id,
        "query": query,
        "source_query": source_query,
        "query_language": query_language,
        "synonym_expansion_used": synonym_expansion_used,
        "domain": domain,
        "discipline_taxonomy": discipline_taxonomy,
        "retrieval_scope": retrieval_scope,
        "research_question_task_provenance": task_provenance,
        "research_question_card": normalized_question_card,
        "targeted_admission": targeted_admission,
        "incoming_excluded_candidate_key_count": len(excluded_candidate_key_set),
        "cross_task_duplicates_excluded": len(cross_round_duplicate_keys),
        "provider_candidates_before_cross_task_dedup": provider_raw,
        "removed_as_previously_seen": len(cross_round_duplicate_keys),
        "new_candidate_count": len(final_results),
        "previously_imported_source_count": max(0, int(previously_imported_source_count or 0)),
        "candidate_pool_diagnostics": candidate_pool_diagnostics,
        "query_contamination_audits": query_contamination_audits,
        "query_contamination_summary": query_contamination_summary,
        "strict_query_plan_execution_audits": strict_query_plan_execution_audits,
        "strict_query_plan_execution_summary": strict_query_plan_execution_summary,
        "retrieval_anchor_contract": retrieval_anchor_contract if isinstance(retrieval_anchor_contract, dict) else {},
        "retrieval_mode": normalized_retrieval_mode,
        "direct_evidence_mode": bool(direct_evidence_mode),
        "focus_branches": focus_branches or [],
        "providers": selected,
        "configured_providers": configured_providers,
        "dispatched_providers": (
            list(query_variant_execution_v3.get("dispatched_providers") or [])
            if query_variant_execution_v3.get("provider_outcomes") else sorted({
                str(block.get("provider") or "")
                for block in provider_blocks
                if isinstance(block, dict)
                and bool(block.get("submitted_to_provider"))
                and str(block.get("provider") or "")
            })
        ),
        "skipped_providers": skipped_providers,
        "requested_providers": requested_providers,
        "provider_layer_strategy": provider_layer_strategy,
        "provider_parallelization": provider_parallelization,
        "l2_provider_retrieval": l2_provider_retrieval,
        "l2_evidence_shortage": l2_evidence_shortage,
        "pubmed_disabled_by_policy": pubmed_disabled_by_policy,
        "pubmed_excluded_by_domain": pubmed_excluded_by_domain,
        "preprint_layers": sorted(allowed_preprint_layers),
        "preprint_exploration_buffer_active": preprint_exploration_buffer_active,
        "preprint_exploration_buffer_limit": preprint_exploration_buffer_limit,
        "preprint_exploration_buffer": summarize_literature_results(preprint_exploration_buffer),
        "preprint_scan_limit": preprint_scan_limit,
        "preprint_provider_result_target": preprint_provider_result_target,
        "strategy": "stratified_cascade",
        "single_paper_serial": single_paper_serial,
        "aligned_reserve_count": len(aligned_reserve_results),
        "aligned_reserve_results": summarize_literature_results(aligned_reserve_results),
        "year_policies": {
            "L0_review": stratified_year_policy("L0_review"),
            "L1_milestone": stratified_year_policy("L1_milestone"),
            "L2_top_latest": stratified_year_policy("L2_top_latest"),
            "L3_preprint": stratified_year_policy("L3_preprint"),
            "L4_regular": stratified_year_policy("L4_regular"),
        },
        "query_plan": (
            response_query_plan_override
            if response_query_plan_override is not None
            else query_plan
        ),
        "strata": strata_reports,
        "knowledge_pyramid": knowledge_pyramid,
        "evidence_window_alerts": evidence_window_alerts,
        "venue_metadata_enrichment": venue_metadata_enrichment,
        "root_result_index": knowledge_pyramid.get("root_result_index"),
        "root_policy": knowledge_pyramid.get("root_policy"),
        "total_results": len(final_results),
        "results": summarize_literature_results(final_results),
        "provider_blocks": summarize_provider_blocks(provider_blocks),
        "query_variant_execution_v3": query_variant_execution_v3,
        "retrieval_run": retrieval_run,
        "full_results_cached": True,
        "next_step": (
            "Import selected stratified results with import_literature_search_result(project_id, search_id, result_index). "
            "Each result has stratified_layer and _why_selected explaining its role in the literature map."
        ),
    }
    log_event(
        "SCIENCE",
        "literature_search_stratified",
        query=query,
        providers=",".join(selected),
        configured_providers=configured_providers,
        dispatched_providers=(
            list(query_variant_execution_v3.get("dispatched_providers") or [])
            if query_variant_execution_v3.get("provider_outcomes") else sorted({
                str(block.get("provider") or "")
                for block in provider_blocks
                if isinstance(block, dict)
                and bool(block.get("submitted_to_provider"))
                and str(block.get("provider") or "")
            })
        ),
        skipped_providers=skipped_providers,
        requested_providers=",".join(requested_providers),
        quotas=quotas,
        retrieval_mode=normalized_retrieval_mode,
        max_results=max_results,
        results=len(final_results),
        strictly_aligned_reserve=len(aligned_reserve_results),
        venue_metadata_enriched=venue_metadata_enrichment.get("enriched", 0),
        single_paper_serial=single_paper_serial,
        incoming_excluded_candidate_key_count=len(excluded_candidate_key_set),
        cross_task_duplicates_excluded=len(cross_round_duplicate_keys),
        provider_candidates_before_cross_task_dedup=provider_raw,
        removed_as_previously_seen=len(cross_round_duplicate_keys),
        new_candidate_count=len(final_results),
        previously_imported_source_count=max(0, int(previously_imported_source_count or 0)),
        project_id=resolved_project_id,
        sub_hypothesis_id=resolved_sub_hypothesis_id,
        retrieval_scope_kind=retrieval_scope["kind"],
        research_question_task_id=str(
            task_provenance.get("research_question_task_id") or ""
        ),
        evidence_slot=str(task_provenance.get("evidence_slot") or ""),
        plan_revision=str(task_provenance.get("plan_revision") or ""),
        query_mode=str(task_provenance.get("query_mode") or ""),
        semantic_fingerprint=str(
            task_provenance.get("semantic_fingerprint")
            or task_provenance.get("query_fingerprint")
            or ""
        ),
        query_branches=[
            str(item.get("branch") or item.get("query_branch") or "")
            for item in query_plan
            if isinstance(item, dict)
            and str(item.get("branch") or item.get("query_branch") or "")
        ],
    )
    return json.dumps(response, ensure_ascii=False, indent=2)

def recover_preprint_layer_candidates(
    *,
    query: str,
    query_plan: list[dict[str, Any]],
    domain: str,
    max_results: int,
    providers: list[str] | None = None,
    scan_limit: int | None = None,
    windows_months: tuple[int, ...] | None = None,
    max_variants: int | None = None,
    required_anchor_groups: list[list[str]] | None = None,
    anchor_policy: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    try:
        from ._utils import clamp_int
    except ImportError:
        from _utils import clamp_int
    base_plans = [dict(item) for item in query_plan if isinstance(item, dict)] or [{"branch": "primary", "query": query}]
    variants: list[dict[str, Any]] = []
    variant_limit = clamp_int(max_variants, 1, 3) if max_variants is not None else 3
    policy = anchor_policy or build_preprint_anchor_policy(query=query)
    for plan in base_plans[:variant_limit]:
        base_query = str(plan.get("query") or query)
        branch = str(plan.get("branch") or "primary")
        requirement = preprint_branch_anchor_requirement(
            branch,
            anchor_policy=policy,
            inherited_anchor_groups=required_anchor_groups,
            planned_query=base_query,
        )
        compact = compact_preprint_retrieval_query(
            base_query,
            domain=domain,
            required_anchor_groups=requirement["required_anchor_groups"],
        )
        expanded = compact_preprint_retrieval_query(
            expand_query_with_synonyms(base_query),
            domain=domain,
            required_anchor_groups=requirement["required_anchor_groups"],
        )
        for candidate in (compact, expanded):
            if candidate and not any(candidate == item["query"] for item in variants):
                variants.append(
                    {
                        "query": candidate,
                        "source_query": base_query,
                        "branch": branch,
                        "requirement": requirement,
                    }
                )
    blocks: list[dict[str, Any]] = []
    attempts: list[dict[str, Any]] = []
    selected = {database_to_provider(provider) for provider in (providers or ["arxiv"])}
    recovery_providers = [provider for provider in ("medrxiv", "biorxiv", "arxiv") if provider in selected]
    recovery_windows = tuple(months for months in (windows_months or (6, 12, 24)) if int(months) > 0)
    for months in recovery_windows:
        for variant_info in variants[:variant_limit]:
            variant = str(variant_info["query"])
            requirement = variant_info["requirement"]
            for provider in recovery_providers:
                anchor_audit = preprint_query_anchor_audit(
                    str(variant_info["source_query"]),
                    variant,
                    required_anchor_groups=requirement["required_anchor_groups"],
                    require_object_anchor=True,
                    object_anchor_group=requirement["object_anchor_group"],
                    branch=str(variant_info["branch"]),
                    prerequisite_failure=str(requirement.get("block_reason") or ""),
                )
                if not anchor_audit["dispatch_allowed"]:
                    block = {
                        "provider": provider,
                        "query": variant,
                        "status": "skipped",
                        "results": [],
                        "skipped_provider_reason": str(anchor_audit.get("block_reason") or "preprint_anchor_contract_blocked"),
                    }
                elif provider == "arxiv":
                    block = dispatch_compiled_provider_query(
                        provider,
                        variant,
                        lambda provider_query: search_arxiv(
                            provider_query,
                            max_results=max_results,
                            sort_by="submittedDate",
                        ),
                    )
                else:
                    block = dispatch_compiled_provider_query(
                        provider,
                        variant,
                        lambda provider_query: _search_preprint_with_controls(
                            provider,
                            provider_query,
                            max_results=max_results,
                            days_back=months * 31,
                            scan_limit=scan_limit,
                        ),
                    )
                block["preprint_anchor_audit"] = anchor_audit
                block["retrieval_strategy"] = "preprint_recovery"
                block["preprint_recovery_window_months"] = months
                block["preprint_recovery_query"] = variant
                blocks.append(block)
                count = len(block.get("results") or []) if isinstance(block, dict) else 0
                attempts.append({"query": variant, "window_months": months, "provider": provider, "results": count, "branch": variant_info["branch"]})
                log_event(
                    "SCIENCE",
                    "preprint_recovery_attempt",
                    provider=provider,
                    query=variant[:180],
                    query_variant_reason="l3_preprint_recovery",
                    window_months=months,
                    result_count=count,
                    scan_budget=block.get("scan_budget"),
                    zero_result_cache_hit=bool(block.get("zero_result_cache_hit")),
                )
                if count:
                    return blocks, {"attempted": True, "attempts": attempts, "outcome": "recovered"}
    return blocks, {
        "attempted": bool(attempts),
        "attempts": attempts,
        "outcome": "no_preprint_evidence",
        "next_step": "Mark the affected sub-hypothesis as evidence-insufficient or supply a narrower retrieval query; do not substitute older papers for P0.",
    }


def diverse_rerank_literature_results(results: list[dict[str, Any]], max_results: int) -> list[dict[str, Any]]:
    try:
        from ._literature_scoring import literature_result_text_similarity, literature_selection_base_score
        from ._utils import clamp_int
    except ImportError:
        from _literature_scoring import literature_result_text_similarity, literature_selection_base_score
        from _utils import clamp_int
    limit = clamp_int(max_results, 1, 200)
    remaining = [
        dict(item)
        for item in results
        if isinstance(item, dict) and not is_retracted_literature_result(item)
    ]
    if len(remaining) <= limit:
        if any(item.get("research_role") for item in remaining):
            remaining.sort(
                key=lambda item: (
                    -{
                        "CORE_DIRECT": 6, "BOUNDARY": 5, "ADVERSE": 5,
                        "COMPONENT_SUPPORT": 4, "BACKGROUND": 3,
                        "METHOD": 2, "PENDING": 1, "OFF_TOPIC": 0,
                    }.get(str(item.get("research_role") or "PENDING").upper(), 1),
                    -float((item.get("research_role_assessment") or {}).get("score") or 0.0),
                    -float(item.get("relevance_score") or 0.0),
                )
            )
        return remaining[:limit]
    selected: list[dict[str, Any]] = []
    used_branches: set[str] = set()
    used_layers: set[str] = set()
    while remaining and len(selected) < limit:
        best_index = 0
        best_score = -999.0
        for index, item in enumerate(remaining):
            score = literature_selection_base_score(item)
            score += {
                "CORE_DIRECT": 0.18, "BOUNDARY": 0.12, "ADVERSE": 0.12,
                "COMPONENT_SUPPORT": 0.06, "BACKGROUND": 0.0,
                "METHOD": -0.2, "PENDING": -0.05, "OFF_TOPIC": -1.0,
            }.get(
                str(item.get("research_role") or "PENDING").upper(),
                0.0,
            )
            branch = str(item.get("query_branch") or item.get("stratified_label") or "")
            layer = str(item.get("stratified_layer") or "")
            if branch and branch in used_branches:
                score -= 0.18
            if layer and layer in used_layers and layer in {"L3_preprint", "L4_regular"}:
                score -= 0.08
            similarity = max((literature_result_text_similarity(item, chosen) for chosen in selected), default=0.0)
            score -= 0.28 * similarity
            if score > best_score:
                best_score = score
                best_index = index
        chosen = remaining.pop(best_index)
        chosen["diversity_rank_score"] = round(best_score, 4)
        selected.append(chosen)
        branch = str(chosen.get("query_branch") or chosen.get("stratified_label") or "")
        layer = str(chosen.get("stratified_layer") or "")
        if branch:
            used_branches.add(branch)
        if layer:
            used_layers.add(layer)
    return selected

def stratified_literature_quotas(max_results: int) -> dict[str, int]:
    try:
        from ._utils import clamp_int
    except ImportError:
        from _utils import clamp_int
    total = clamp_int(max_results, 1, int(SCIENCE_MAX_METADATA_RESULTS_PER_SH))
    # A preprint scan is optional horizon scanning, never a default evidence
    # requirement.  Callers that need it must allocate L3 explicitly.
    preprint = 0
    remaining = total - preprint
    latest = max(1, round(total * 0.22)) if remaining else 0
    latest = min(latest, remaining)
    remaining -= latest
    review = max(1, round(total * 0.08)) if remaining else 0
    review = min(review, int(SCIENCE_MAX_REVIEW_FULLTEXT_PER_RETRIEVAL))
    review = min(review, remaining)
    remaining -= review
    milestone = min(max(0, round(total * 0.04)), remaining)
    remaining -= milestone
    return {
        "L3_preprint": preprint,
        "L2_top_latest": latest,
        "L0_review": review,
        "L1_milestone": milestone,
        "L4_regular": remaining,
    }


def normalize_stratified_layer_quotas(
    requested: dict[str, int] | None,
    *,
    max_results: int,
) -> dict[str, int]:
    """Normalize user quotas without the old 3-paper evidence-layer ceilings."""
    try:
        from ._utils import clamp_int
    except ImportError:
        from _utils import clamp_int
    defaults = stratified_literature_quotas(max_results)
    if not isinstance(requested, dict):
        return defaults
    names = ("L3_preprint", "L2_top_latest", "L4_regular", "L0_review", "L1_milestone")
    raw = {name: max(0, int(requested.get(name, 0) or 0)) for name in names}
    if sum(raw.values()) <= 0:
        return defaults
    total = clamp_int(max_results, 1, int(SCIENCE_MAX_METADATA_RESULTS_PER_SH))
    preprint_cap = min(10, max(3, total // 20))
    preprint = min(preprint_cap, raw["L3_preprint"], total)
    remaining = total - preprint
    latest = min(raw["L2_top_latest"], remaining)
    remaining -= latest
    review_cap = max(0, min(25, int(SCIENCE_MAX_REVIEW_FULLTEXT_PER_RETRIEVAL)))
    review = min(review_cap, raw["L0_review"], remaining)
    remaining -= review
    milestone_cap = max(0, min(20, max(1, total // 20)))
    milestone = min(milestone_cap, raw["L1_milestone"], remaining)
    remaining -= milestone
    return {
        "L3_preprint": preprint,
        "L2_top_latest": latest,
        "L0_review": review,
        "L1_milestone": milestone,
        "L4_regular": remaining,
    }


def controlled_l4_backfill_budget(
    strata_reports: list[dict[str, Any]],
    max_backfill: int = MAX_CONTROLLED_L4_BACKFILL,
) -> dict[str, Any]:
    # L1 is a historical-foundation claim, and L3 is an optional preprint
    # signal.  Neither participates in required peer-reviewed evidence
    # coverage or regular-paper backfill accounting.
    special_layers = {"L2_top_latest", "L0_review"}
    source_layers = [
        str(report.get("layer"))
        for report in strata_reports
        if str(report.get("layer")) in special_layers and int(report.get("unfilled_reserved_quota") or 0) > 0
    ]
    missing = sum(
        int(report.get("unfilled_reserved_quota") or 0)
        for report in strata_reports
        if str(report.get("layer")) in special_layers
    )
    return {
        "quota": min(max(0, int(max_backfill)), max(0, missing)),
        "source_layers": source_layers,
        "missing_special_quota": missing,
    }


def promote_high_impact_l4_reviews(
    selected_results: list[dict[str, Any]],
    strata_reports: list[dict[str, Any]],
    quotas: dict[str, int],
) -> list[dict[str, Any]]:
    review_limit = max(0, int(quotas.get("L0_review", 0)))
    already_selected = sum(1 for item in selected_results if item.get("stratified_layer") == "L0_review")
    remaining = max(0, review_limit - already_selected)
    if not remaining:
        return []
    candidates = [
        item
        for item in selected_results
        if item.get("stratified_layer") == "L4_regular"
        and is_review_like_paper(item)
        and is_top_venue_result(item)
    ]
    candidates.sort(
        key=lambda item: (
            -float(item.get("publication_quality_score") or 0.0),
            -float(item.get("relevance_score") or 0.0),
            -float(item.get("citation_count") or 0.0),
        )
    )
    promoted = candidates[:remaining]
    for item in promoted:
        item["retrieved_as_layer"] = "L4_regular"
        item["stratified_layer"] = "L0_review"
        item["stratified_label"] = "context synthesis retrieval source pending evidence classification"
        item["retrieval_layer"] = "L0_context_synthesis"
        item["stratified_recovery"] = "high_impact_review_reclassified_from_l4"
        item["_why_selected"] = stratified_selection_reason("L0_review", item)
    if promoted:
        report = next((item for item in strata_reports if item.get("layer") == "L0_review"), None)
        if report is not None:
            report["selected"] = int(report.get("selected") or 0) + len(promoted)
            report["reclassified_from_l4"] = len(promoted)
            report["unfilled_reserved_quota"] = max(
                0,
                int(report.get("target") or 0) - int(report["selected"]),
            )
        l4_report = next((item for item in strata_reports if item.get("layer") == "L4_regular"), None)
        if l4_report is not None:
            l4_report["selected"] = max(0, int(l4_report.get("selected") or 0) - len(promoted))
            l4_report["reclassified_to_l0_review"] = len(promoted)
            l4_report["unfilled_reserved_quota"] = max(
                0,
                int(l4_report.get("target") or 0) - int(l4_report["selected"]),
            )
    return promoted

def stratified_literature_layers(
    quotas: dict[str, int],
    *,
    direct_evidence_mode: bool = False,
) -> list[dict[str, Any]]:
    return [
        {
            "layer": "L3_preprint",
            "priority": "P5",
            "label": "preprint retrieval source pending evidence classification",
            "quota": int(quotas.get("L3_preprint", 0)),
            "query_suffix": "",
        },
        {
            "layer": "L2_top_latest",
            "priority": "P1",
            "label": "recent high-quality retrieval source pending evidence classification",
            "quota": int(quotas.get("L2_top_latest", 0)),
            # L2 is intentionally retrieved through its dedicated Semantic
            # Scholar path.  Its recency/venue/impact qualifiers are local
            # selection criteria, not topical API search terms.
            "query_suffix": "",
        },
        {
            "layer": "L0_review",
            "priority": "P3",
            "label": "context synthesis retrieval source pending evidence classification",
            "quota": int(quotas.get("L0_review", 0)),
            "query_suffix": "review survey progress perspective tutorial systematic review meta-analysis",
        },
        {
            "layer": "L1_milestone",
            "priority": "P4",
            "label": "foundational context retrieval source pending evidence classification",
            "quota": int(quotas.get("L1_milestone", 0)),
            "query_suffix": "",
            "retrieval_owner": "dedicated_foundational_mechanism_workflow",
        },
        {
            "layer": "L4_regular",
            "priority": "P2",
            "label": "other formal published source pending evidence classification",
            "quota": int(quotas.get("L4_regular", 0)),
            # Direct-lane queries already declare their required evidence
            # type.  Non-review layers should not carry framework/review bait;
            # those context terms are reserved for L0_review.
            "query_suffix": "" if direct_evidence_mode else "experimental assay measurement validation controlled study cohort",
        },
    ]


def neutral_retrieval_layer(layer: str) -> str:
    return {
        "L0_review": "L0_context_synthesis",
        "L1_milestone": "L1_foundational_context",
        "L2_top_latest": "L2_recent_high_quality",
        "L3_preprint": "L3_preprint",
        "L4_regular": "L4_other_formal_source",
    }.get(str(layer or ""), "")

def build_domain_query_plan(
    query: str,
    domain: str = "",
    max_branches: int = 8,
    focus_branches: list[str] | None = None,
    use_llm: bool | None = None,
) -> list[dict[str, str]]:
    try:
        from ._literature_scoring import domain_topic_profile, slug_label
        from ._utils import normalize_space
    except ImportError:
        from _literature_scoring import domain_topic_profile, slug_label
        from _utils import normalize_space
    primary = normalize_space(query)
    plan: list[dict[str, str]] = [{"branch": "primary", "query": primary}]
    profile = domain_topic_profile(domain or query, query=query, use_llm=use_llm)
    focus_branches = [normalize_space(item) for item in (focus_branches or []) if normalize_space(item)]
    for focus in focus_branches:
        branch_query = normalize_space(f"{primary} {focus}")
        plan.append({"branch": slug_label(focus), "query": branch_query})
    topics = list(profile.get("core_topics", [])) + list(profile.get("retrieval_facets", []))
    for topic in topics[: max(0, max_branches)]:
        branch = str(topic.get("branch") or "subfield")
        normalized_branch = branch.strip().lower()
        topic_type = str(topic.get("topic_type") or "subfield").strip().lower()
        if is_dedicated_foundation_query_branch(
            {"branch": normalized_branch, "query_family": topic_type}
        ):
            # Historical-foundation discovery needs the current SH's
            # input/mediator/outcome contract.  A domain-wide branch cannot
            # provide that contract and would recreate the retired broad L1
            # pool.
            continue
        terms = str(topic.get("query") or "")
        if not terms:
            continue
        branch_query = normalize_space(terms if primary.lower() in terms.lower() else f"{primary} {terms}")
        plan.append({"branch": branch, "query": branch_query, "topic_type": str(topic.get("topic_type") or "subfield")})
    deduped: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in plan:
        key = normalize_space(item["query"]).lower()
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped[: max(1, max_branches + 1)]

def expanded_ranking_query(query: str, domain: str, query_plan: list[dict[str, str]]) -> str:
    try:
        from ._utils import normalize_space, unique_preserve_order
    except ImportError:
        from _utils import normalize_space, unique_preserve_order
    topic_terms: list[str] = []
    for item in query_plan:
        topic_terms.extend(query_terms(str(item.get("query") or ""))[:4])
    return normalize_space(" ".join([query, domain, " ".join(unique_preserve_order(topic_terms)[:24])]))

def live_probe_literature_branch(query: str, providers: list[str] | None = None) -> dict[str, Any]:
    try:
        from ._project import default_literature_providers, live_literature_provider_names
        from ._utils import trim_text, unique_preserve_order
    except ImportError:
        from _project import default_literature_providers, live_literature_provider_names
        from _utils import trim_text, unique_preserve_order
    if not query:
        return {"query": query, "status": "skipped", "total_results": 0, "reason": "empty query"}
    selected = [database_to_provider(provider) for provider in (providers or default_literature_providers(query=query))]
    selected = unique_preserve_order([item for item in selected if item in live_literature_provider_names()])
    if not selected:
        selected = default_literature_providers(query=query) or ["semantic_scholar"]
    reports: list[dict[str, Any]] = []
    total = 0
    for provider in selected:
        try:
            if provider == "semantic_scholar":
                block = search_semantic_scholar(query, max_results=3)
            elif provider == "pubmed":
                block = search_pubmed(query, max_results=3)
            elif provider in {"biorxiv", "medrxiv", "chemrxiv"}:
                block = search_preprint_api(provider, query, max_results=3)
            else:
                block = search_arxiv(query, max_results=3)
            count = len(block.get("results") or []) if block.get("status") == "ok" else 0
            total += count
            reports.append(
                {
                    "provider": provider,
                    "status": block.get("status"),
                    "result_count": count,
                    "top_titles": [trim_text(str(item.get("title") or ""), 120) for item in (block.get("results") or [])[:3]],
                    "error": block.get("error", ""),
                }
            )
        except Exception as exc:
            reports.append({"provider": provider, "status": "error", "result_count": 0, "error": str(exc)})
    return {
        "query": query,
        "status": "ok" if total > 0 else "empty_or_error",
        "total_results": total,
        "providers": reports,
    }

def build_branch_user_interaction(coverage_diagnostic: dict[str, Any]) -> dict[str, Any]:
    blind_spots = coverage_diagnostic.get("blind_spots", [])
    options: list[dict[str, Any]] = []
    for spot in blind_spots[:6]:
        options.append(
            {
                "label": str(spot.get("topic") or "missing branch"),
                "suggested_query": str(spot.get("suggested_query") or ""),
                "live_evidence_count": int((spot.get("live_probe") or {}).get("total_results") or 0)
                if isinstance(spot.get("live_probe"), dict)
                else 0,
                "false_negative_risk": bool(spot.get("false_negative_risk")),
            }
        )
    if not options:
        return {"needed": False}
    return {
        "needed": True,
        "type": "research_branch_confirmation",
        "question": "Some major sub-branches appear missing from the current retrieval. Which should be prioritized for a supplemental search before treating gaps as real?",
        "options": options,
        "default_action": "Run supplemental stratified search for options with false_negative_risk=true, or ask the user to pick 2-3 priority branches.",
        "continue_with": "Revise the V3 research-question contract or its slot query, then resume run_autogen_groupchat.",
    }

def _search_preprint_with_controls(
    provider: str,
    query: str,
    max_results: int,
    *,
    days_back: int = 365,
    scan_limit: int | None = None,
) -> dict[str, Any]:
    options: dict[str, Any] = {"max_results": max_results, "days_back": days_back}
    if scan_limit is not None:
        options["scan_limit"] = scan_limit
    return search_preprint_api(provider, query, **options)


def _provider_not_terms_for_anchor_contract(
    anchor_contract: dict[str, Any] | None,
    *,
    domain: str = "",
) -> list[str]:
    if not isinstance(anchor_contract, dict) or not anchor_contract:
        return []
    try:
        from ._research_alignment import expanded_exclusion_terms_for_contract
    except ImportError:
        from _research_alignment import expanded_exclusion_terms_for_contract
    return expanded_exclusion_terms_for_contract(
        anchor_contract,
        domain=domain or anchor_contract.get("primary_field") or "",
        provider_not_only=True,
    )


def _pubmed_title_abstract_clause(term: str) -> str:
    normalized = normalize_space(str(term or "")).strip().strip('"')
    normalized = normalized.replace('"', "")
    if not normalized:
        return ""
    return f'"{normalized}"[Title/Abstract]'


def _append_provider_exclusions_to_query(
    provider: str,
    query: str,
    *,
    anchor_contract: dict[str, Any] | None = None,
) -> tuple[str, dict[str, Any]]:
    """Prepend SH-local exclusions where the provider syntax is reliable."""

    normalized_provider = normalize_space(str(provider or "")).lower()
    source_query = normalize_space(str(query or ""))
    audit = {
        "schema_version": "provider_query_exclusion_compilation_v1",
        "provider": normalized_provider,
        "applied": False,
        "policy": "pubmed_not_clause_else_post_provider_hard_reject_only",
        "provider_not_terms": [],
        # Kept as an empty compatibility field for stored search artifacts
        # and downstream dashboards from before sibling terms were demoted.
        "post_provider_fast_reject_terms": [],
        "post_provider_hard_reject_terms": [],
    }
    terms = _provider_not_terms_for_anchor_contract(anchor_contract)
    audit["provider_not_terms"] = terms[:24]
    if normalized_provider != "pubmed" or not terms or not source_query:
        # Non-PubMed connectors do not support reliable NOT syntax.  The
        # terms recorded here are only high-precision explicit exclusions;
        # sibling-object terms have already been demoted to an auditable soft
        # role conflict by the alignment contract.
        audit["post_provider_hard_reject_terms"] = terms[:24]
        return source_query, audit
    # PubMed accepts Boolean NOT and Title/Abstract field tags.  Keep only a
    # short, high-precision SH-local list so a sibling exclusion cannot become
    # a broad project-level blacklist.
    clauses = [
        _pubmed_title_abstract_clause(term)
        for term in terms
        if normalize_space(term)
    ][:16]
    clauses = [clause for clause in clauses if clause]
    if not clauses:
        return source_query, audit
    if re.search(r"\bNOT\s*\(", source_query, flags=re.IGNORECASE):
        audit["applied"] = False
        audit["reason"] = "query_already_contains_not_clause"
        return source_query, audit
    compiled = normalize_space(f"({source_query}) NOT ({' OR '.join(clauses)})")
    audit["applied"] = compiled != source_query
    audit["compiled_query"] = compiled
    return compiled, audit


STRUCTURED_QUERY_MODULE_KEYS = (
    "object",
    "causal_input",
    "method_or_assessment",
    "readout_or_endpoint",
    "boundary_or_cost_or_comparison",
    "model_system",
)


def _query_module_values(value: Any) -> list[str]:
    if isinstance(value, dict):
        raw_values = list(value.values())
    elif isinstance(value, (list, tuple, set)):
        raw_values = list(value)
    else:
        raw_values = [value]
    values: list[str] = []
    for raw in raw_values:
        if isinstance(raw, (list, tuple, set)):
            values.extend(_query_module_values(raw))
            continue
        normalized = normalize_space(str(raw or "").strip().strip("\"'"))
        if not normalized:
            continue
        normalized = re.sub(r"\s+", " ", normalized)
        values.append(normalized)
    return values


def _query_phrase_dedupe_key(value: str) -> str:
    normalized = normalize_space(str(value or "").lower())
    normalized = normalized.replace("’", "'")
    normalized = re.sub(r"\s*\(([a-z0-9&+./ -]{1,16})\)\s*", " ", normalized)
    normalized = re.sub(r"[-_/]+", " ", normalized)
    normalized = re.sub(r"[^a-z0-9+]+", " ", normalized)
    return normalize_space(normalized)


def _query_phrase_acronym(value: str) -> str:
    words = [
        word
        for word in re.findall(r"[A-Za-z][A-Za-z0-9]*", str(value or ""))
        if word
    ]
    if len(words) < 2:
        return ""
    return "".join(word[0].lower() for word in words if word[0].isalpha())


_PROVIDER_QUERY_SYNTAX_ONLY_ANCHORS = frozenset({
    "a",
    "an",
    "the",
    "as",
    "to",
    "do",
    "does",
    "than",
    "when",
    "then",
    "where",
    "which",
    "what",
    "whether",
    "if",
    "vs",
    "vs.",
    "versus",
    "compare",
    "compared",
    "comparison",
    "comparative",
    "compared a",
    "compared an",
    "compared the",
    "compared with",
    "compared to",
    "when compared",
    "when compared with",
    "when compared to",
    "relative",
    "relative to",
    "extent",
    "to what extent",
    "what extent",
    "baseline when",
})
_PROVIDER_QUESTION_PREFIX_RE = re.compile(
    r"^\s*(?:"
    r"to\s+what\s+extent\s+(?:do|does|can|could|will|would|is|are)?\s*"
    r"|whether\s+"
    r"|if\s+"
    r"|how\s+(?:do|does|can|could|will|would|is|are)\s+"
    r")",
    flags=re.IGNORECASE,
)
_PROVIDER_COMPARISON_TAIL_RE = re.compile(
    r"\b(?:when\s+)?(?:compared(?:\s+(?:with|to))?|relative\s+to)\b.*$",
    flags=re.IGNORECASE,
)
_PROVIDER_BASELINE_EXACT_ANCHORS = frozenset({
    "baseline",
    "baselines",
    "control",
    "controls",
    "control group",
    "control arm",
    "control condition",
    "comparison group",
    "comparator",
    "comparators",
    "reference",
    "reference case",
    "reference scenario",
    "status quo",
    "counterfactual",
    "counterfactual baseline",
    "placebo",
    "placebo control",
    "usual care",
    "standard care",
    "standard-of-care",
    "business as usual",
    "business-as-usual",
    "bau",
    "no intervention",
    "no-intervention",
    "no-intervention baseline",
    "no intervention baseline",
    "no treatment",
    "no-treatment",
    "untreated",
    "untreated control",
    "null intervention",
    "null treatment",
    "no mitigation",
    "no-mitigation",
})
_PROVIDER_BASELINE_PHRASE_RE = re.compile(
    r"(?<![a-z0-9])(?:"
    r"no[-\s]?intervention|no[-\s]?treatment|no[-\s]?mitigation|"
    r"untreated(?:\s+control)?|placebo(?:\s+control)?|usual\s+care|"
    r"standard[-\s]?of[-\s]?care|standard\s+care|business[-\s]+as[-\s]+usual|"
    r"counterfactual(?:\s+baseline)?|status\s+quo|"
    r"reference\s+(?:case|scenario)|"
    r"control\s+(?:group|arm|condition)|"
    r"(?:comparison\s+)?baseline(?:s)?"
    r")(?![a-z0-9])",
    flags=re.IGNORECASE,
)


def _provider_strip_question_and_comparison_tail(value: Any) -> str:
    text = normalize_space(str(value or "").strip().strip("\"'"))
    if not text:
        return ""
    text = _PROVIDER_QUESTION_PREFIX_RE.sub("", text)
    text = _PROVIDER_COMPARISON_TAIL_RE.sub("", text)
    text = re.sub(r"\bwhen\s*$", "", text, flags=re.IGNORECASE)
    text = re.sub(r"(?<![A-Za-z0-9])vs\.?(?![A-Za-z0-9])", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"(?<![A-Za-z0-9])versus(?![A-Za-z0-9])", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\bcompared\s+(?:with|to)\b", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\brelative\s+to\b", " ", text, flags=re.IGNORECASE)
    return normalize_space(text.strip(" .,:;\"'()[]{}"))


def _provider_is_syntax_only_anchor(value: Any) -> bool:
    text = normalize_space(str(value or "").strip(" .,:;\"'()[]{}")).lower()
    if not text:
        return True
    if text in _PROVIDER_QUERY_SYNTAX_ONLY_ANCHORS:
        return True
    if text.startswith("to what extent"):
        return True
    if re.fullmatch(
        r"(?:when\s+)?compared(?:\s+(?:with|to|a|an|the))?",
        text,
        flags=re.IGNORECASE,
    ):
        return True
    if re.fullmatch(
        r"(?:baseline|control|comparator)\s+when",
        text,
        flags=re.IGNORECASE,
    ):
        return True
    return False


def _provider_is_baseline_or_comparator_anchor(value: Any) -> bool:
    text = normalize_space(str(value or "").strip(" .,:;\"'()[]{}")).lower()
    if not text or _provider_is_syntax_only_anchor(text):
        return False
    if text in _PROVIDER_BASELINE_EXACT_ANCHORS:
        return True
    token_count = len(re.findall(r"[a-z0-9]+", text))
    return bool(token_count <= 6 and _PROVIDER_BASELINE_PHRASE_RE.search(text))


def _provider_anchor_matches_baseline_terms(
    value: Any,
    baseline_terms: Any,
) -> bool:
    text = _query_phrase_dedupe_key(str(value or ""))
    if not text:
        return False
    for term in _query_module_values(baseline_terms):
        key = _query_phrase_dedupe_key(term)
        if not key:
            continue
        if text == key:
            return True
        if len(key.split()) >= 2 and (
            f" {key} " in f" {text} " or f" {text} " in f" {key} "
        ):
            return True
    return False


def _provider_clean_module_anchor(
    value: Any,
    *,
    module_key: str,
    baseline_terms: Any = (),
) -> str:
    text = _provider_strip_question_and_comparison_tail(value)
    if not text or _provider_is_syntax_only_anchor(text):
        return ""
    # Provider discovery queries should start from an object plus declared
    # causal variable(s), not from generic methods/readouts/reporting words.
    # Keep meaningful outcomes (e.g. a named physical or biological endpoint)
    # but remove measurement modes and statistical templates inherited from a
    # stale or over-broad query plan.
    if module_key in {"method_or_assessment", "readout_or_endpoint"}:
        normalized = normalize_space(text).lower().replace("-", " ")
        template_phrases = {
            "effect size", "effect sizes", "statistical significance",
            "controlled experiment", "controlled experiments", "controlled study",
            "controlled studies", "theoretical model", "theoretical models",
            "computational simulation", "computational simulations", "data analysis",
            "statistical analysis", "tc measurement",
        }
        tokens = re.findall(r"[a-z0-9]+", normalized)
        method_tails = {
            "analysis", "analyses", "assay", "assays", "measurement", "measurements",
            "microscopy", "simulation", "simulations", "spectroscopy", "study",
            "studies", "survey", "surveys", "model", "models",
        }
        if normalized in template_phrases or (tokens and tokens[-1] in method_tails):
            return ""
    baseline_allowed = module_key in {
        "boundary_or_cost_or_comparison",
        "project_background",
    }
    if not baseline_allowed:
        if _provider_is_baseline_or_comparator_anchor(text):
            return ""
        if _provider_anchor_matches_baseline_terms(text, baseline_terms):
            return ""
    return text


def _provider_sanitize_source_query(value: Any) -> str:
    terms = [
        term
        for term in query_terms(str(value or ""))
        if not _provider_is_syntax_only_anchor(term)
        and not _provider_is_baseline_or_comparator_anchor(term)
    ]
    return normalize_space(" ".join(terms))


def _dedupe_query_phrases(values: Any) -> list[str]:
    raw_values = _query_module_values(values)
    long_phrase_acronyms = {
        acronym
        for acronym in (_query_phrase_acronym(value) for value in raw_values)
        if len(acronym) >= 2
    }
    output: list[str] = []
    seen: set[str] = set()
    for value in raw_values:
        key = _query_phrase_dedupe_key(value)
        if not key:
            continue
        compact = re.sub(r"[^a-z0-9]+", "", key)
        if compact in long_phrase_acronyms and len(compact) <= 6:
            continue
        if key in seen:
            continue
        seen.add(key)
        output.append(value)
    return output


def _structured_query_modules_from_plan(
    plan: dict[str, Any],
    *,
    prefer_l2: bool = False,
) -> dict[str, list[str]]:
    raw_modules = (
        plan.get("l2_query_modules")
        if prefer_l2 and isinstance(plan.get("l2_query_modules"), dict)
        else plan.get("query_modules")
    )
    modules: dict[str, list[str]] = {}
    if isinstance(raw_modules, dict):
        for key in STRUCTURED_QUERY_MODULE_KEYS + ("exclusion",):
            modules[key] = _dedupe_query_phrases(raw_modules.get(key))
    else:
        modules = {
            "object": _dedupe_query_phrases(
                plan.get("required_object_group")
                or plan.get("scientific_object_anchor_group")
            ),
            "causal_input": _dedupe_query_phrases(
                plan.get("required_causal_input_group")
                or plan.get("causal_input_anchor_group")
            ),
            "method_or_assessment": _dedupe_query_phrases(
                plan.get("required_method_or_mechanism_group")
                or plan.get("causal_edge_anchors")
            ),
            "readout_or_endpoint": _dedupe_query_phrases(plan.get("optional_readout_group")),
            "boundary_or_cost_or_comparison": _dedupe_query_phrases(
                plan.get("boundary_or_cost_or_comparison_group")
            ),
            "model_system": _dedupe_query_phrases(plan.get("optional_model_group")),
            "exclusion": _dedupe_query_phrases(
                list(plan.get("query_forbidden_terms") or [])
                + list(plan.get("excluded_nearby_objects") or [])
            ),
        }
    positive_non_baseline_terms = _dedupe_query_phrases(
        _query_module_values(plan.get("non_baseline_comparison_level_terms"))
        + (
            _query_module_values(plan.get("comparison_level_terms"))
            if bool(plan.get("comparison_levels_as_declared_input"))
            else []
        )
    )
    raw_baseline_terms = _dedupe_query_phrases(
        _query_module_values(plan.get("baseline_or_comparator_terms"))
        + _query_module_values(plan.get("baseline_or_comparator_group"))
        + _query_module_values(plan.get("baseline_or_comparator"))
        + list(modules.get("boundary_or_cost_or_comparison") or [])
    )
    baseline_terms = _dedupe_query_phrases([
        term
        for term in raw_baseline_terms
        if not _provider_anchor_matches_baseline_terms(term, positive_non_baseline_terms)
    ])
    filtered_modules: dict[str, list[str]] = {}
    for key, values in modules.items():
        if not isinstance(values, list) or not values:
            continue
        if key == "exclusion":
            cleaned_values = [
                _provider_strip_question_and_comparison_tail(value)
                for value in values
                if _provider_strip_question_and_comparison_tail(value)
                and not _provider_is_syntax_only_anchor(value)
            ]
        else:
            cleaned_values = [
                cleaned
                for value in values
                for cleaned in [
                    _provider_clean_module_anchor(
                        value,
                        module_key=key,
                        baseline_terms=baseline_terms,
                    )
                ]
                if cleaned
            ]
        cleaned_values = _dedupe_query_phrases(cleaned_values)
        if cleaned_values:
            filtered_modules[key] = cleaned_values
    modules = filtered_modules
    return {
        key: list(values)
        for key, values in modules.items()
        if isinstance(values, list) and values
    }


def _structured_query_boolean_expression(
    modules: dict[str, list[str]],
    *,
    provider: str = "",
) -> str:
    clauses: list[str] = []
    normalized_provider = database_to_provider(provider)
    for key in STRUCTURED_QUERY_MODULE_KEYS:
        values = modules.get(key) or []
        if not values:
            continue
        if normalized_provider == "pubmed":
            terms = [
                _pubmed_title_abstract_clause(value)
                for value in values[:6]
                if normalize_space(value)
            ]
        else:
            terms = [
                f"\"{value}\"" if " " in value else value
                for value in values[:6]
                if normalize_space(value)
            ]
        terms = [term for term in terms if term]
        if terms:
            clauses.append("(" + " OR ".join(terms) + ")")
    exclusions = modules.get("exclusion") or []
    if exclusions:
        if normalized_provider == "pubmed":
            terms = [
                _pubmed_title_abstract_clause(value)
                for value in exclusions[:16]
                if normalize_space(value)
            ]
        else:
            terms = [
                f"\"{value}\"" if " " in value else value
                for value in exclusions[:16]
                if normalize_space(value)
            ]
        terms = [term for term in terms if term]
        if terms:
            clauses.append("NOT (" + " OR ".join(terms) + ")")
    return normalize_space(" AND ".join(clauses))


def _structured_query_compact_text(
    modules: dict[str, list[str]],
    *,
    fallback_query: str,
    max_terms: int = 12,
) -> str:
    module_order = (
        "object",
        "causal_input",
        "method_or_assessment",
        "readout_or_endpoint",
        "boundary_or_cost_or_comparison",
        "model_system",
    )
    per_module_cap = {
        "object": 1,
        "causal_input": 2,
        "method_or_assessment": 1,
        "readout_or_endpoint": 1,
        "boundary_or_cost_or_comparison": 1,
        "model_system": 1,
    }
    token_limit = 16
    item_limit = max(2, min(int(max_terms), 10))
    values: list[str] = []
    token_count = 0

    def phrase_token_count(value: str) -> int:
        return max(1, len(query_terms(value)))

    def try_add(value: str) -> bool:
        nonlocal token_count
        normalized = normalize_space(value)
        if not normalized:
            return False
        if normalized in values:
            return False
        count = phrase_token_count(normalized)
        if len(values) >= item_limit or token_count + count > token_limit:
            return False
        values.append(normalized)
        token_count += count
        return True

    # First preserve module coverage: object + method/assessment + readout +
    # optional boundary/cost/comparison should survive provider token caps.
    for key in module_order:
        candidates = _dedupe_query_phrases(modules.get(key) or [])
        if candidates:
            try_add(candidates[0])
    for key in module_order:
        candidates = _dedupe_query_phrases(modules.get(key) or [])
        for value in candidates[1 : per_module_cap.get(key, 1)]:
            try_add(value)
    values = _dedupe_query_phrases(values)
    if len(values) < 3:
        fallback_terms = [
            term
            for term in query_terms(fallback_query)
            if term not in SEMANTIC_SCHOLAR_QUERY_MODIFIERS
            and term not in L2_PROVIDER_QUERY_MODIFIERS
        ]
        for term in fallback_terms:
            if len(values) >= 4:
                break
            try_add(term)
        values = _dedupe_query_phrases(values)
    return normalize_space(" ".join(values[:item_limit]))[:180].rstrip()


def compile_structured_provider_query_from_plan(
    plan: dict[str, Any],
    provider: str,
    *,
    fallback_query: str = "",
    prefer_l2: bool = False,
    max_terms: int = 12,
) -> dict[str, Any]:
    """Compile a module-balanced provider query when typed modules exist."""

    if not isinstance(plan, dict):
        return {"used_modules": False, "compiled_query": normalize_space(fallback_query)}
    if is_contract_lexical_calibration_plan(plan):
        source_query = _provider_sanitize_source_query(
            str(
                plan.get("l2_query")
                if prefer_l2 and plan.get("l2_query")
                else plan.get("query") or fallback_query or ""
            )
        ) or normalize_space(str(plan.get("query") or fallback_query or ""))
        return {
            "used_modules": False,
            "compiled_query": source_query,
            "source_query": source_query,
            "query_modules": {},
            "compile_mode": "strict_calibration_plan_passthrough",
            "reason": "contract_lexical_calibration_may_not_be_recompiled_from_structured_modules",
        }
    modules = _structured_query_modules_from_plan(plan, prefer_l2=prefer_l2)
    has_object = bool(modules.get("object"))
    has_support = any(
        modules.get(key)
        for key in (
            "method_or_assessment",
            "readout_or_endpoint",
            "boundary_or_cost_or_comparison",
            "model_system",
        )
    )
    requires_declared_input = bool(plan.get("query_requires_declared_input"))
    has_declared_input = bool(modules.get("causal_input"))
    raw_source_query = str(
        plan.get("l2_query")
        if prefer_l2 and plan.get("l2_query")
        else plan.get("query")
        or fallback_query
        or ""
    )
    source_query = _provider_sanitize_source_query(raw_source_query) or normalize_space(
        raw_source_query
    )
    if requires_declared_input and not has_declared_input:
        return {
            "used_modules": False,
            "compiled_query": source_query,
            "source_query": source_query,
            "query_modules": modules,
            "reason": "structured_modules_missing_required_causal_input",
            "query_requires_declared_input": True,
        }
    if not has_object or not has_support:
        return {
            "used_modules": False,
            "compiled_query": source_query,
            "source_query": source_query,
            "query_modules": modules,
            "reason": "structured_modules_missing_object_or_support",
        }
    normalized_provider = database_to_provider(provider)
    boolean_expression = _structured_query_boolean_expression(
        modules,
        provider=normalized_provider,
    )
    if normalized_provider == "pubmed" and boolean_expression:
        compiled = boolean_expression
        mode = "boolean_modules"
    else:
        compiled = _structured_query_compact_text(
            modules,
            fallback_query=source_query,
            max_terms=max_terms,
        )
        mode = "balanced_compact_modules"
    return {
        "used_modules": bool(compiled),
        "compiled_query": compiled or source_query,
        "source_query": source_query,
        "query_modules": modules,
        "boolean_expression": boolean_expression,
        "compile_mode": mode,
        "module_counts": {
            key: len(values)
            for key, values in modules.items()
            if isinstance(values, list)
        },
        "query_requires_declared_input": requires_declared_input,
        "provider_not_exclusion_terms": list(modules.get("exclusion") or [])[:24],
    }


def _branch_plan_is_background_context(plan: dict[str, Any] | None) -> bool:
    payload = plan if isinstance(plan, dict) else {}
    lane = str(payload.get("target_lane") or "").strip().upper()
    if lane in {"THEORETICAL_FRAMEWORK", "BACKGROUND_REVIEW"}:
        return True
    role_text = " ".join(
        str(payload.get(key) or "")
        for key in (
            "branch",
            "query_family",
            "evidence_path_role",
            "retrieval_layer_role",
            "purpose",
        )
    ).lower()
    return any(
        marker in role_text
        for marker in (
            "background",
            "context_review",
            "context review",
            "framework",
            "theoretical_framework",
            "review",
        )
    )


def _branch_required_semantic_anchor_group(
    plan: dict[str, Any] | None,
    anchor_contract: dict[str, Any] | None,
) -> list[str]:
    """Return an explicitly declared branch-local anchor group.

    Provider dispatch must not infer a causal input from a project-wide graph.
    A current V3 plan may add a bounded local requirement, but only when it is
    explicitly supplied as one named semantic group.
    """

    payload = plan if isinstance(plan, dict) else {}
    raw_values: list[Any] = []
    for key in ("required_branch_anchor_group", "branch_local_anchor_group"):
        value = payload.get(key)
        if isinstance(value, (list, tuple, set)):
            raw_values.extend(value)
        elif value:
            raw_values.append(value)
    output: list[str] = []
    seen: set[str] = set()
    for raw in raw_values:
        normalized = normalize_space(str(raw or ""))
        if not normalized:
            continue
        lowered = normalized.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        output.append(normalized)
    return output[:16]


def _branch_query_requires_local_anchor(
    plan: dict[str, Any] | None,
    anchor_contract: dict[str, Any] | None,
) -> bool:
    payload = plan if isinstance(plan, dict) else {}
    if payload.get("query_requires_local_anchor") is True:
        return bool(_branch_required_semantic_anchor_group(payload, anchor_contract))
    if payload.get("query_requires_local_anchor") is False:
        return False
    return bool(
        _branch_required_semantic_anchor_group(payload, anchor_contract)
        and not _branch_plan_is_background_context(payload)
    )


def branch_anchor_contract_for_query_plan(
    anchor_contract: dict[str, Any] | None,
    plan: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Add an explicitly declared local semantic group to a V2 contract."""

    if not isinstance(anchor_contract, dict) or not anchor_contract:
        base: dict[str, Any] = {}
    else:
        base = dict(anchor_contract)
    if not _branch_query_requires_local_anchor(plan, base):
        return base or None
    group = _branch_required_semantic_anchor_group(plan, base)
    if not group:
        return base or None
    if str(base.get("schema_version") or "") != "retrieval_anchor_contract_v3":
        return base or None
    required_groups = [
        dict(item)
        for item in (base.get("required_anchor_groups") or [])
        if isinstance(item, Mapping)
    ]
    group_key = tuple(normalize_space(str(item)).casefold() for item in group)
    existing_keys = {
        tuple(
            normalize_space(str(item)).casefold()
            for item in (existing.get("accepted_forms") or [])
        )
        for existing in required_groups
    }
    if group_key not in existing_keys:
        required_groups.append({
            "group_id": "branch_local_requirement",
            "accepted_forms": group,
            "required": True,
            "match_policy": "provider_normalized_token_sequence_v1",
        })
    base["required_anchor_groups"] = required_groups
    base["branch_required_semantic_anchor_group"] = group
    base["branch_requires_local_anchor"] = True
    return base


def prepare_provider_query_for_dispatch(
    provider: str,
    query: str,
    *,
    anchor_contract: dict[str, Any] | None = None,
    require_current_anchor_contract: bool = False,
) -> tuple[str, dict[str, Any], list[dict[str, Any]], list[str]]:
    """Compile one final provider query before any request is dispatched.

    This is deliberately a discovery-layer guard.  It can normalize provider
    syntax and make one syntax-only repair, but it cannot alter a required
    semantic anchor to make a request succeed.  Callers retain the resulting
    audit so local rejection and executed provider requests stay distinct.
    """
    try:
        from ._literature_retrieval_foundation import compile_provider_query, repair_provider_query
    except ImportError:
        from _literature_retrieval_foundation import compile_provider_query, repair_provider_query

    query, exclusion_compilation = _append_provider_exclusions_to_query(
        provider,
        query,
        anchor_contract=anchor_contract,
    )
    compilation = compile_provider_query(
        provider,
        query,
        anchor_contract=anchor_contract,
        require_current_anchor_contract=require_current_anchor_contract,
    )
    compilation["provider_exclusion_compilation"] = exclusion_compilation
    attempted_queries = [str(compilation.get("compiled_query") or query)]
    revisions: list[dict[str, Any]] = []
    if compilation.get("valid"):
        return attempted_queries[-1], compilation, revisions, attempted_queries

    repair = repair_provider_query(
        provider,
        attempted_queries[-1],
        "; ".join((compilation.get("syntax_validation") or {}).get("errors") or ["anchor_validation_failed"]),
        anchor_contract=anchor_contract,
        prior_queries=[str(compilation.get("source_query") or query)],
    )
    revisions.append(repair)
    if not repair.get("accepted"):
        return "", compilation, revisions, attempted_queries

    repaired_query = str(repair.get("repaired_query") or "")
    attempted_queries.append(repaired_query)
    repaired_compilation = compile_provider_query(
        provider,
        repaired_query,
        anchor_contract=anchor_contract,
        require_current_anchor_contract=require_current_anchor_contract,
    )
    repaired_compilation["static_repair"] = repair
    repaired_compilation["provider_exclusion_compilation"] = exclusion_compilation
    if not repaired_compilation.get("valid"):
        return "", repaired_compilation, revisions, attempted_queries
    return repaired_query, repaired_compilation, revisions, attempted_queries


def dispatch_compiled_provider_query(
    provider: str,
    query: str,
    dispatch: Any,
    *,
    anchor_contract: dict[str, Any] | None = None,
    require_current_anchor_contract: bool = False,
) -> dict[str, Any]:
    """Run a provider request only after bounded query compilation/repair.

    A provider error is eligible for the same one-off repair, but the repair
    helper rejects every change except syntax correction.  Consequently an
    upstream error cannot trigger broadening, anchor removal, or an
    unbounded retry loop.
    """
    try:
        from ._literature_retrieval_foundation import compile_provider_query, repair_provider_query
    except ImportError:
        from _literature_retrieval_foundation import compile_provider_query, repair_provider_query

    compiled_query, compilation, revisions, attempted_queries = prepare_provider_query_for_dispatch(
        provider,
        query,
        anchor_contract=anchor_contract,
        require_current_anchor_contract=require_current_anchor_contract,
    )
    if not compiled_query:
        failure_kind = str(compilation.get("failure_kind") or "provider_query_compilation_error")
        return {
            "provider": provider,
            "query": str(compilation.get("compiled_query") or query),
            "status": failure_kind,
            "error": "Provider query compilation rejected this request before network submission.",
            "results": [],
            "submitted_to_provider": False,
            "failure_stage": "query_plan_contract" if failure_kind == "query_plan_contract_error" else "provider_query_compilation",
            "failure_kind": failure_kind,
            "query_compilation": compilation,
            "query_revisions": revisions,
            "attempted_queries": attempted_queries,
        }

    try:
        response = dispatch(compiled_query)
        block = dict(response) if isinstance(response, dict) else provider_error_result(
            provider,
            compiled_query,
            RuntimeError("provider returned a non-object response"),
        )
    except Exception as exc:
        block = provider_error_result(provider, compiled_query, exc)

    # Static and provider-error repairs share one budget.  A request that was
    # already syntax-repaired is recorded as failed rather than being revised
    # a second time under a different provider error message.
    if str(block.get("status") or "") == "error" and not revisions:
        repair = repair_provider_query(
            provider,
            compiled_query,
            block.get("error") or "provider_error",
            anchor_contract=anchor_contract,
            prior_queries=attempted_queries,
        )
        revisions.append(repair)
        if repair.get("accepted"):
            repaired_query = str(repair.get("repaired_query") or "")
            attempted_queries.append(repaired_query)
            repaired_compilation = compile_provider_query(
                provider,
                repaired_query,
                anchor_contract=anchor_contract,
                require_current_anchor_contract=require_current_anchor_contract,
            )
            repaired_compilation["provider_exclusion_compilation"] = (
                compilation.get("provider_exclusion_compilation")
                if isinstance(compilation, dict)
                else {}
            )
            if repaired_compilation.get("valid"):
                repaired_compilation["provider_error_repair"] = repair
                compilation = repaired_compilation
                try:
                    response = dispatch(repaired_query)
                    block = dict(response) if isinstance(response, dict) else provider_error_result(
                        provider,
                        repaired_query,
                        RuntimeError("provider returned a non-object response"),
                    )
                except Exception as exc:
                    block = provider_error_result(provider, repaired_query, exc)

    block["query_compilation"] = compilation
    block["query_revisions"] = revisions
    block["attempted_queries"] = attempted_queries
    block["submitted_to_provider"] = True
    block.setdefault("failure_stage", "provider_response" if str(block.get("status") or "") == "error" else "")
    return block


V2_QUERY_VARIANT_POLICY = "v3_typed_provider_query_variants_v1"


def _comparison_variant_anchor_contract_v4(
    anchor_contract: Mapping[str, Any],
    retrieval_spec: Mapping[str, Any],
    variant: Mapping[str, Any],
) -> dict[str, Any]:
    """Bind each comparison query to the named arms it must retain."""

    contract = dict(anchor_contract)
    if contract.get("schema_version") != "retrieval_anchor_contract_v3":
        return contract
    comparison = retrieval_spec.get("comparison_contract_v4")
    if not isinstance(comparison, Mapping):
        blueprint = retrieval_spec.get("query_blueprint_v3")
        comparison = (
            blueprint.get("comparison_contract_v4")
            if isinstance(blueprint, Mapping)
            else {}
        )
    if not isinstance(comparison, Mapping):
        return contract
    primary = comparison.get("primary_arm")
    comparators = comparison.get("comparator_arms")
    all_arms = [primary, *(comparators if isinstance(comparators, list) else [])]
    arms_by_id = {
        str(arm.get("arm_id") or "").strip(): arm
        for arm in all_arms
        if isinstance(arm, Mapping) and str(arm.get("arm_id") or "").strip()
    }
    role = str(variant.get("comparison_evidence_role") or "")
    arm_ids: list[str] = []
    if role in {"DIRECT_PAIR_COMPARISON", "COMPARABILITY_BRIDGE"}:
        arm_ids = [
            str(variant.get("primary_arm_id") or "").strip(),
            str(variant.get("comparator_arm_id") or "").strip(),
        ]
    elif role == "ARM_COMPONENT_DISCOVERY":
        variant_id = str(variant.get("variant_id") or "")
        arm_ids = [variant_id.removeprefix("arm_component__")]
    arm_ids = list(dict.fromkeys(arm_id for arm_id in arm_ids if arm_id))
    if role and (not arm_ids or any(arm_id not in arms_by_id for arm_id in arm_ids)):
        raise ValueError(
            "comparison query variant must bind every queried arm to comparison_contract_v4"
        )
    groups = [
        dict(group)
        for group in contract.get("required_anchor_groups") or []
        if isinstance(group, Mapping)
    ]
    existing_ids = {
        str(group.get("group_id") or "").strip()
        for group in groups
    }
    for arm_id in arm_ids:
        arm = arms_by_id[arm_id]
        group_id = f"comparison_arm:{arm_id}"
        if group_id in existing_ids:
            continue
        canonical_label = str(arm.get("canonical_label") or "").strip()
        if not canonical_label:
            raise ValueError(
                "comparison_contract_v4 arm must provide a canonical_label for provider binding"
            )
        groups.append({
            "group_id": group_id,
            "accepted_forms": [canonical_label],
            "required": True,
            "match_policy": "provider_normalized_token_sequence_v1",
        })
    contract["required_anchor_groups"] = groups
    return contract


def materialize_query_variants_v3(
    provider: str,
    plan: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Compile a provider query only from a current V3 slot work item.

    This is the active query-compiler entry point for research-question
    retrieval.  A plan without ``retrieval_work_item_v3`` is not an
    incomplete version of this contract: it is rejected before it can fall
    through to broad topic discovery.
    """

    try:
        from ._retrieval_execution_v3 import (
            compile_slot_query_variants_v3,
            select_comparison_query_variants_for_phase_v4,
        )
    except ImportError:
        from _retrieval_execution_v3 import (
            compile_slot_query_variants_v3,
            select_comparison_query_variants_for_phase_v4,
        )
    payload = dict(plan) if isinstance(plan, Mapping) else {}
    spec = (
        payload.get("retrieval_spec_v3")
        if isinstance(payload.get("retrieval_spec_v3"), Mapping)
        else payload
        if payload.get("schema_version") == "retrieval_task_spec_v3"
        else {}
    )
    work_item = (
        payload.get("retrieval_work_item_v3")
        if isinstance(payload.get("retrieval_work_item_v3"), Mapping)
        else {}
    )
    variants = compile_slot_query_variants_v3(
        provider,
        spec,
        work_item,
        plan_revision=str(payload.get("plan_revision") or ""),
    )
    if isinstance(spec.get("comparison_contract_v4"), Mapping) or isinstance(
        (spec.get("query_blueprint_v3") or {}).get("comparison_contract_v4"),
        Mapping,
    ):
        variants = select_comparison_query_variants_for_phase_v4(
            variants,
            spec.get("comparison_retrieval_phase_v4"),
        )
    anchor_contract = (
        spec.get("retrieval_anchor_contract")
        if isinstance(spec.get("retrieval_anchor_contract"), Mapping)
        else {}
    )
    for variant in variants:
        variant["retrieval_anchor_contract"] = _comparison_variant_anchor_contract_v4(
            anchor_contract,
            spec,
            variant,
        )
        variant["slot_focus_axes"] = list(spec.get("slot_focus_axes") or [])
        variant["slot_evidence_terms"] = list(spec.get("evidence_design_terms") or [])
        variant["query_branch"] = str(spec.get("query_branch") or payload.get("branch") or "")
        variant["work_item_kind"] = str(work_item.get("work_item_kind") or "")
    return variants


def dispatch_query_variant_sequence_v3(
    provider: str,
    variants: list[dict[str, Any]],
    dispatch: Any,
    *,
    event_context: Mapping[str, Any] | None = None,
    max_attempts: int = 2,
) -> list[dict[str, Any]]:
    """Dispatch V3 variants with typed outcomes and bounded recovery.

    The provider adapter remains responsible for provider-specific syntax and
    transport.  This wrapper owns the scientific contract: invalid local
    queries are never retried, transient typed failures have a bounded retry,
    and zero-result reuse is scoped to the V3 work-item binding.
    """

    try:
        from ._literature_retrieval_foundation import compile_provider_query
        from ._retrieval_execution_v3 import execute_provider_variant_with_recovery_v3
    except ImportError:
        from _literature_retrieval_foundation import compile_provider_query
        from _retrieval_execution_v3 import execute_provider_variant_with_recovery_v3

    context = dict(event_context or {})
    blocks: list[dict[str, Any]] = []
    has_comparison_obligation = any(
        str(item.get("comparison_evidence_role") or "")
        in {
            "DIRECT_PAIR_COMPARISON",
            "ARM_COMPONENT_DISCOVERY",
            "COMPARABILITY_BRIDGE",
        }
        for item in variants
        if isinstance(item, Mapping)
    )
    for position, raw_variant in enumerate(variants):
        variant = dict(raw_variant) if isinstance(raw_variant, Mapping) else {}
        variant_id = str(variant.get("variant_id") or "")
        common = {
            **context,
            "provider": provider,
            "variant_id": variant_id,
            "query_intent": str(variant.get("query_intent") or ""),
            "variant_fingerprint": str(variant.get("variant_fingerprint") or ""),
            "query_fingerprint": str(variant.get("query_fingerprint") or ""),
            "semantic_source_query": str(variant.get("query") or ""),
            "comparison_evidence_role": str(
                variant.get("comparison_evidence_role") or ""
            ),
            "comparison_contract_id": str(variant.get("comparison_contract_id") or ""),
            "primary_arm_id": str(variant.get("primary_arm_id") or ""),
            "comparator_arm_id": str(variant.get("comparator_arm_id") or ""),
        }
        compilation = compile_provider_query(
            provider,
            str(variant.get("query") or ""),
            anchor_contract=(
                variant.get("retrieval_anchor_contract")
                if isinstance(variant.get("retrieval_anchor_contract"), Mapping)
                else None
            ),
            require_current_anchor_contract=True,
        )
        variant["provider_expression"] = str(
            compilation.get("semantic_source_query") or variant.get("query") or ""
        )
        variant["provider_safe_expression"] = str(
            compilation.get("provider_compiled_query")
            or variant.get("provider_expression")
            or ""
        )
        if not compilation.get("valid"):
            variant["dispatch_allowed"] = False
            variant["skip_reason"] = str(
                compilation.get("failure_kind") or "provider_query_compilation_error"
            )
        log_event("SCIENCE", "v3_query_variant_dispatch_started", **common)
        execution_blocks = execute_provider_variant_with_recovery_v3(
            provider,
            variant,
            lambda compiled_query, prepared_variant: dispatch(compiled_query, prepared_variant),
            max_attempts=max_attempts,
        )
        for block in execution_blocks:
            block["query_compilation"] = compilation
            block["query_variant_v3_position"] = position
            if (
                str((block.get("provider_outcome_v3") or {}).get("outcome") or "")
                == "INVALID_QUERY"
            ):
                block["variant_execution_status"] = "COMPILATION_REPAIR_REQUIRED"
        blocks.extend(execution_blocks)
        outcomes = [
            str((block.get("provider_outcome_v3") or {}).get("outcome") or "")
            for block in execution_blocks
            if isinstance(block, Mapping)
        ]
        log_event(
            "SCIENCE",
            "v3_query_variant_dispatch_completed",
            provider_outcomes=outcomes,
            raw_result_count=sum(len(block.get("results") or []) for block in execution_blocks),
            **common,
        )
        # A provider candidate is not scientific completion.  Every named
        # direct-pair comparison variant must receive its own provider outcome;
        # component/bridge variants are kept as separately auditable evidence
        # roles.  An INVALID_QUERY only diagnoses that one variant and must
        # never suppress an independent pair or arm search.
        if not has_comparison_obligation and any(
            str((block.get("provider_outcome_v3") or {}).get("outcome") or "")
            == "SUCCESS_WITH_CANDIDATES"
            for block in execution_blocks
        ):
            break
    return blocks


def summarize_query_variant_execution_v3(blocks: list[dict[str, Any]]) -> dict[str, Any]:
    """Project typed V3 outcomes into the retrieval-run operational ledger."""

    try:
        from ._retrieval_execution_v3 import provider_outcome_summary_v3
    except ImportError:
        from _retrieval_execution_v3 import provider_outcome_summary_v3
    summary = provider_outcome_summary_v3(blocks)
    outcomes = list(summary.get("provider_outcomes") or [])
    providers = list(dict.fromkeys(
        str(block.get("provider") or "")
        for block in blocks if isinstance(block, Mapping) and str(block.get("provider") or "")
    ))
    summary.update({
        "policy": "typed_provider_execution_v3",
        "attempts": [
            {
                "provider": str(outcome.get("provider") or ""),
                "variant_id": str(outcome.get("query_variant_id") or ""),
                "query_fingerprint": str(outcome.get("query_fingerprint") or ""),
                "provider_outcome_v3": dict(outcome),
                "status": str(outcome.get("outcome") or ""),
                "raw_result_count": int(outcome.get("raw_result_count") or 0),
            }
            for outcome in outcomes
            if isinstance(outcome, Mapping)
        ],
        "dispatched_providers": [
            provider for provider in providers
            if any(bool(block.get("submitted_to_provider")) and str(block.get("provider") or "") == provider for block in blocks)
        ],
        "provider_submission_count": sum(
            bool(block.get("submitted_to_provider")) for block in blocks if isinstance(block, Mapping)
        ),
        "provider_terminal_response_count": sum(
            bool(block.get("submitted_to_provider")) for block in blocks if isinstance(block, Mapping)
        ),
        "provider_error_count": sum(
            str(outcome.get("outcome") or "") in {
                "TIMEOUT", "RATE_LIMITED", "NETWORK_ERROR", "AUTH_ERROR", "PARSE_ERROR", "CIRCUIT_OPEN",
            }
            for outcome in outcomes if isinstance(outcome, Mapping)
        ),
        "local_compilation_rejection_count": sum(
            str(outcome.get("outcome") or "") == "INVALID_QUERY"
            for outcome in outcomes if isinstance(outcome, Mapping)
        ),
        "deferred_providers": [],
        "local_compilation_rejections": [],
    })
    compilation_repair_variant_ids = sorted({
        str((block.get("query_variant_v3") or {}).get("variant_id") or "")
        for block in blocks
        if isinstance(block, Mapping)
        and str((block.get("provider_outcome_v3") or {}).get("outcome") or "")
        == "INVALID_QUERY"
        and str((block.get("query_variant_v3") or {}).get("variant_id") or "")
    })
    if compilation_repair_variant_ids:
        summary["compilation_repair_required_variant_ids"] = (
            compilation_repair_variant_ids
        )
        summary["terminal_outcome"] = "QUERY_COMPILATION_REPAIR_REQUIRED"
    comparison_variants = [
        block.get("query_variant_v3")
        for block in blocks
        if isinstance(block, Mapping)
        and isinstance(block.get("query_variant_v3"), Mapping)
        and str((block.get("query_variant_v3") or {}).get("comparison_evidence_role") or "")
    ]
    if comparison_variants:
        phases = {
            str((variant.get("comparison_retrieval_phase_v4") or {}).get("phase") or "")
            for variant in comparison_variants
            if isinstance((variant.get("comparison_retrieval_phase_v4") or {}), Mapping)
        }
        roles = {
            str(variant.get("comparison_evidence_role") or "")
            for variant in comparison_variants
        }
        outcome_by_variant = {
            str(outcome.get("query_variant_id") or ""): str(outcome.get("outcome") or "")
            for outcome in outcomes
            if isinstance(outcome, Mapping)
        }
        arm_first_variant_ids = {
            str(variant.get("variant_id") or "")
            for variant in comparison_variants
            if str(variant.get("comparison_evidence_role") or "") in {
                "DIRECT_PAIR_COMPARISON", "ARM_COMPONENT_DISCOVERY"
            }
        }
        comparability_followup_variant_ids = {
            str(variant.get("variant_id") or "")
            for variant in comparison_variants
            if str(variant.get("comparison_evidence_role") or "")
            == "COMPARABILITY_BRIDGE"
        }
        phase = next(iter(phases)) if len(phases) == 1 else ""
        terminal_outcomes = {"SUCCESS_WITH_CANDIDATES", "SUCCESS_EMPTY"}
        summary["comparison_retrieval_phase_v4"] = {
            "schema_version": "comparison_retrieval_phase_v4",
            "phase": phase,
            "executed_variant_ids": sorted({
                str(variant.get("variant_id") or "")
                for variant in comparison_variants
                if str(variant.get("variant_id") or "")
            }),
            "executed_evidence_roles": sorted(role for role in roles if role),
            "arm_first_provider_execution_complete": bool(arm_first_variant_ids) and all(
                outcome_by_variant.get(variant_id) in terminal_outcomes
                for variant_id in arm_first_variant_ids
            ),
            "comparability_followup_provider_execution_complete": bool(
                comparability_followup_variant_ids
            ) and all(
                outcome_by_variant.get(variant_id) in terminal_outcomes
                for variant_id in comparability_followup_variant_ids
            ),
        }
    return summary


def _v3_query_blueprint_from_plan(plan: Mapping[str, Any] | None) -> dict[str, Any]:
    """Return a valid V3 semantic blueprint carried by an explicit task plan."""

    if not isinstance(plan, Mapping):
        return {}
    spec = plan.get("retrieval_spec_v3")
    if not isinstance(spec, Mapping):
        spec = plan
    blueprint = spec.get("query_blueprint_v3")
    if not isinstance(blueprint, Mapping):
        return {}
    if str(blueprint.get("schema_version") or "") != "retrieval_query_blueprint_v3":
        return {}
    typed_anchor_contract = _normalize_retrieval_anchor_contract(
        spec.get("retrieval_anchor_contract")
        if isinstance(spec.get("retrieval_anchor_contract"), Mapping)
        else {}
    )
    if (
        str(typed_anchor_contract.get("schema_version") or "")
        != "retrieval_anchor_contract_v3"
        or not bool(typed_anchor_contract.get("valid"))
    ):
        return {}
    required = blueprint.get("required_anchor_groups")
    research_object = required.get("research_object") if isinstance(required, Mapping) else []
    if not any(str(item).strip() for item in research_object if isinstance(research_object, list)):
        return {}
    return dict(blueprint)


def _is_declared_v3_retrieval_plan(plan: Mapping[str, Any] | None) -> bool:
    """Return whether a plan declares the current V3 task protocol at all.

    This deliberately recognizes malformed and superseded V3 payloads.  Such
    payloads must be rejected locally, rather than silently entering the
    untyped discovery path as though they were ordinary branch plans.
    """

    if not isinstance(plan, Mapping):
        return False
    if "retrieval_spec_v3" in plan:
        return True
    schema_version = str(plan.get("schema_version") or "")
    return (
        schema_version.startswith("retrieval_task_spec_v3")
        or "query_blueprint_v3" in plan
        or "provider_query_materialization_v3" in plan
    )


def _is_legacy_retrieval_plan(plan: Mapping[str, Any] | None) -> bool:
    """Detect a V1/V2 retrieval artifact before it can enter generic search."""

    if not isinstance(plan, Mapping):
        return False
    schema_version = str(plan.get("schema_version") or "").lower()
    legacy_keys = {
        "retrieval_spec_v1", "retrieval_spec_v2", "query_blueprint_v1",
        "query_blueprint_v2", "provider_query_materialization_v1",
        "provider_query_materialization_v2", "declared_causal_edge",
        "missing_core_axes",
    }
    return (
        "_v1" in schema_version
        or "_v2" in schema_version
        or any(key in plan for key in legacy_keys)
    )


def partition_retrieval_plans_v3(
    plans: list[dict[str, Any]] | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Split plans into current V3, rejected legacy/malformed, and generic plans.

    The third partition can use the ordinary retrieval path.  The rejected
    partition cannot: its semantic task was explicitly V2, but its persisted
    contract is no longer current and must be recompiled from the RQC.
    """

    current: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    non_contract: list[dict[str, Any]] = []
    for raw_plan in plans or []:
        if not isinstance(raw_plan, Mapping):
            continue
        plan = dict(raw_plan)
        if _is_legacy_retrieval_plan(plan):
            rejected.append(plan)
        elif _is_declared_v3_retrieval_plan(plan):
            if _v3_query_blueprint_from_plan(plan):
                current.append(plan)
            else:
                rejected.append(plan)
        else:
            non_contract.append(plan)
    return current, rejected, non_contract


def _legacy_plan_contract_rejection_block(
    provider: str,
    plan: Mapping[str, Any],
    *,
    request_kind: str,
) -> dict[str, Any]:
    """Report a stale V2 plan without issuing a provider request."""

    spec = (
        plan.get("retrieval_spec_v3")
        if isinstance(plan.get("retrieval_spec_v3"), Mapping)
        else plan
    )
    spec = spec if isinstance(spec, Mapping) else {}
    source_query = normalize_space(
        str(spec.get("provider_query") or plan.get("query") or "")
    )
    anchor_contract = _normalize_retrieval_anchor_contract(
        spec.get("retrieval_anchor_contract")
        if isinstance(spec.get("retrieval_anchor_contract"), Mapping)
        else {}
    )
    semantic_fingerprint = str(spec.get("semantic_fingerprint") or "")
    variant = {
        "variant_id": "plan_contract_schema",
        "trigger": "plan_schema_validation",
        "query": source_query,
        "semantic_fingerprint": semantic_fingerprint,
        "dispatch_allowed": False,
        "skip_reason": "query_plan_contract_schema_required",
        "retrieval_anchor_contract": dict(anchor_contract),
        "provider_query_compilation_policy_version": "provider_query_compilation_v3",
        "anchor_match_policy_version": "provider_normalized_token_sequence_v1",
    }
    return {
        "provider": provider,
        "query": source_query,
        "semantic_source_query": source_query,
        "status": "query_plan_contract_error",
        "results": [],
        "error": (
            "V1/V2 or malformed retrieval plan does not satisfy the current V3 typed provider "
            "contract; recompile it from the research-question contract."
        ),
        "failure_stage": "query_plan_contract",
        "failure_kind": "query_plan_contract_error",
        "submitted_to_provider": False,
        "provider_submission_count": 0,
        "provider_terminal_response_count": 0,
        "query_branch": str(
            spec.get("query_branch") or plan.get("branch") or "primary"
        ),
        "provider_batch_request_kind": request_kind,
        "query_compilation": {
            "valid": False,
            "submission_allowed": False,
            "submitted_to_provider": False,
            "failure_kind": "query_plan_contract_error",
            "failure_stage": "query_plan_contract",
            "source_anchor_validation": {
                "status": "invalid_anchor_contract_schema",
                "schema_version": str(anchor_contract.get("schema_version") or ""),
            },
        },
        "query_variant_v3": variant,
    }


def _legacy_plan_contract_rejection_blocks(
    provider: str,
    plans: list[dict[str, Any]],
    *,
    request_kind: str,
) -> list[dict[str, Any]]:
    """Emit deterministic local rejections for stale V1/V2 task plans."""

    blocks: list[dict[str, Any]] = []
    for plan in plans:
        block = _legacy_plan_contract_rejection_block(
            provider,
            plan,
            request_kind=request_kind,
        )
        log_event(
            "SCIENCE",
            "legacy_query_plan_contract_rejected",
            provider=provider,
            request_kind=request_kind,
            **_v3_variant_event_context(plan),
            semantic_source_query=str(block.get("semantic_source_query") or "")[:240],
            failure_kind="query_plan_contract_error",
            submitted_to_provider=False,
        )
        blocks.append(block)
    return blocks


def _skipped_preprint_provider_block(
    provider: str,
    query: str,
    reason: str,
    *,
    query_branch: str,
    retrieval_strategy: str,
    source_query: str,
) -> dict[str, Any]:
    log_event(
        "SCIENCE",
        "preprint_provider_skipped",
        provider=provider,
        query=query[:180],
        reason=reason,
        query_variant_reason=retrieval_strategy,
    )
    return {
        "provider": provider,
        "query": query,
        "status": "skipped",
        "results": [],
        "skipped_provider_reason": reason,
        "query_branch": query_branch,
        "retrieval_strategy": retrieval_strategy,
        "source_query": source_query,
        "query_variant_reason": retrieval_strategy,
    }


def _annotate_preprint_layer_block(
    block: dict[str, Any],
    *,
    query_branch: str,
    retrieval_strategy: str,
    source_query: str,
) -> dict[str, Any]:
    block["query_branch"] = query_branch
    block["retrieval_strategy"] = retrieval_strategy
    block["source_query"] = source_query
    block["query_variant_reason"] = retrieval_strategy
    log_event(
        "SCIENCE",
        "preprint_layer_query",
        provider=block.get("provider"),
        query=str(block.get("query") or "")[:180],
        query_variant_reason=retrieval_strategy,
        query_branch=query_branch,
        result_count=len(block.get("results") or []),
        scan_budget=block.get("scan_budget"),
        scanned=block.get("scanned_result_count"),
        zero_result_cache_hit=bool(block.get("zero_result_cache_hit")),
    )
    return block


def stratified_single_paper_interval_seconds() -> float:
    return max(2.0, float(SCIENCE_STRATIFIED_SINGLE_PAPER_INTERVAL_SECONDS))


def search_stratified_single_paper(
    provider: str,
    query: str,
    *,
    offset: int,
    layer: str,
    ordinal: int,
) -> dict[str, Any]:
    """Retrieve exactly one candidate and wait two seconds after every response.

    The lock is intentionally held through the HTTP request and the response
    timestamp is recorded only after it completes. This prevents a parallel
    retrieval branch from bypassing the one-paper cadence.
    """
    global STRATIFIED_SINGLE_PAPER_LAST_COMPLETED_AT
    interval = stratified_single_paper_interval_seconds()
    with STRATIFIED_SINGLE_PAPER_LOCK:
        remaining = STRATIFIED_SINGLE_PAPER_LAST_COMPLETED_AT + interval - time.monotonic()
        if remaining > 0:
            log_event(
                "SCIENCE",
                "stratified_single_paper_wait",
                provider=provider,
                layer=layer,
                wait_seconds=round(remaining, 3),
                interval_seconds=interval,
            )
            time.sleep(remaining)
        log_event(
            "SCIENCE",
            "stratified_single_paper_request_dispatch",
            provider=provider,
            layer=layer,
            ordinal=ordinal,
            offset=offset,
            max_results=1,
            interval_seconds=interval,
            serialized=True,
        )
        try:
            if provider == "semantic_scholar":
                block = search_semantic_scholar(query, max_results=1, offset=offset)
            elif provider == "pubmed":
                block = search_pubmed(query, max_results=1, offset=offset)
            elif provider == "arxiv":
                block = search_arxiv(query, max_results=1, sort_by="relevance", offset=offset)
            elif provider in {"biorxiv", "medrxiv", "chemrxiv"}:
                block = search_preprint_api(provider, query, max_results=1, offset=offset)
            else:
                return provider_error_result(provider, query, ValueError("single-paper stratified retrieval is unsupported"))
        finally:
            STRATIFIED_SINGLE_PAPER_LAST_COMPLETED_AT = time.monotonic()
    block["single_paper_serial"] = True
    block["single_paper_ordinal"] = ordinal
    block["single_paper_offset"] = offset
    results = block.get("results") if isinstance(block.get("results"), list) else []
    first_result = results[0] if results and isinstance(results[0], dict) else {}
    title = str(first_result.get("title") or "").strip()
    if title:
        log_event(
            "SCIENCE",
            "stratified_candidate_slot",
            provider=provider,
            layer=layer,
            ordinal=ordinal,
            provider_status=str(block.get("status") or "unknown"),
            candidate_present=True,
            title=title[:240],
            year=str(first_result.get("year") or ""),
        )
    return block


def fetch_stratified_layer_blocks_one_paper_at_a_time(
    query: str,
    providers: list[str],
    layer: dict[str, Any],
    *,
    query_plan: list[dict[str, str]] | None = None,
    domain: str = "",
    preprint_layers: set[str] | None = None,
    preprint_required_anchor_groups: list[list[str]] | None = None,
    preprint_anchor_policy: dict[str, Any] | None = None,
    anchor_contract: dict[str, Any] | None = None,
    discipline_taxonomy: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Build a bounded layer pool while batching provider HTTP requests.

    ``single_paper_serial`` originally issued ``limit=1`` requests with
    increasing offsets.  That multiplied a three-paper layer into three API
    calls and made a 1-RPS Semantic Scholar key unnecessarily fragile.  Keep
    the downstream one-paper-per-block contract, but fetch all records needed
    for the same provider/query in one request and split them locally.
    """
    try:
        from ._utils import clamp_int
        from ._discipline_taxonomy import compile_provider_discipline_filter
    except ImportError:
        from _utils import clamp_int
        from _discipline_taxonomy import compile_provider_discipline_filter
    provider_taxonomy_filters = {
        provider: compile_provider_discipline_filter(provider, discipline_taxonomy)
        for provider in providers
    }
    layer_name = str(layer.get("layer") or "")
    quota = max(0, int(layer.get("quota") or 0))
    if quota <= 0:
        return []
    if layer_name == "L1_milestone":
        log_event(
            "SCIENCE",
            "broad_pool_L1_retrieval_suppressed",
            target=quota,
            reason="Use search_foundational_mechanism_bridges for L1.",
            L1_from_broad_pool=0,
        )
        return []
    if (
        layer_name == "L3_preprint"
        and layer_name not in normalize_preprint_source_layers(preprint_layers)
    ):
        return []
    supported_names = (
        {"arxiv", "biorxiv", "medrxiv", "chemrxiv"}
        if layer_name == "L3_preprint"
        else {"semantic_scholar", "pubmed"}
    )
    supported_providers = [provider for provider in providers if provider in supported_names]
    if not supported_providers:
        return []
    suffix = str(layer.get("query_suffix") or "").strip()
    plans = _query_plan_for_retrieval_layer(query_plan, layer_name) or [{"branch": "primary", "query": query}]
    plans = plans[: clamp_int(SCIENCE_STRATIFIED_MAX_BRANCHES_PER_LAYER, 1, 20)]
    if not plans:
        plans = [{"branch": "primary", "query": query}]
    scheduled_plans = _weighted_candidate_plan_schedule(plans, quota)
    assignments: list[dict[str, Any]] = []
    skipped_assignments: list[dict[str, Any]] = []
    effective_preprint_anchor_policy = (
        preprint_anchor_policy
        if isinstance(preprint_anchor_policy, dict)
        else build_preprint_anchor_policy(query=query)
    )
    for ordinal, plan in enumerate(scheduled_plans):
        provider = supported_providers[ordinal % len(supported_providers)]
        branch = str(plan.get("branch") or "primary")
        planned_query = str(plan.get("query") or query)
        layer_query = stratified_layer_retrieval_query(layer_name, planned_query, suffix)
        retrieval_strategy = stratified_layer_retrieval_strategy(layer_name)
        anchor_audit: dict[str, Any] | None = None
        if layer_name == "L3_preprint":
            requirement = preprint_branch_anchor_requirement(
                branch,
                anchor_policy=effective_preprint_anchor_policy,
                inherited_anchor_groups=preprint_required_anchor_groups,
                planned_query=planned_query,
            )
            layer_query = compact_preprint_retrieval_query(
                planned_query,
                domain=domain,
                required_anchor_groups=requirement["required_anchor_groups"],
            )
            anchor_audit = preprint_query_anchor_audit(
                planned_query,
                layer_query,
                required_anchor_groups=requirement["required_anchor_groups"],
                require_object_anchor=True,
                object_anchor_group=requirement["object_anchor_group"],
                branch=branch,
                prerequisite_failure=str(requirement.get("block_reason") or ""),
            )
            retrieval_strategy = "latest_preprint_query"
            log_event(
                "SCIENCE",
                "preprint_query_anchor_audit",
                provider=provider,
                query_branch=branch,
                preserved_groups=anchor_audit["preserved_group_count"],
                required_groups=anchor_audit["required_group_count"],
                dropped_groups=anchor_audit["dropped_groups"],
                object_anchor_required=anchor_audit["object_anchor_required"],
                object_anchor_preserved=anchor_audit["object_anchor_preserved"],
                block_reason=anchor_audit["block_reason"],
                dispatch_allowed=anchor_audit["dispatch_allowed"],
            )
            if not anchor_audit["dispatch_allowed"]:
                skipped_assignments.append(
                    {
                        "ordinal": ordinal + 1,
                        "provider": provider,
                        "query": layer_query,
                        "query_branch": branch,
                        "retrieval_strategy": retrieval_strategy,
                        "source_query": planned_query,
                        "preprint_anchor_audit": anchor_audit,
                        "plan": dict(plan),
                    }
                )
                continue
        assignments.append(
            {
                "ordinal": ordinal + 1,
                "provider": provider,
                "query": layer_query,
                "query_branch": branch,
                "retrieval_strategy": retrieval_strategy,
                "source_query": planned_query,
                "preprint_anchor_audit": anchor_audit,
                "branch_anchor_contract": branch_anchor_contract_for_query_plan(
                    anchor_contract,
                    plan,
                ),
                "plan": dict(plan),
            }
        )

    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for assignment in assignments:
        assignment_contract = (
            assignment.get("branch_anchor_contract")
            if isinstance(assignment.get("branch_anchor_contract"), dict)
            else {}
        )
        required_group_key = json.dumps(
            list(assignment_contract.get("branch_required_semantic_anchor_group") or []),
            ensure_ascii=False,
            sort_keys=True,
        )
        key = (
            str(assignment["provider"]),
            str(assignment["query"]),
            required_group_key,
        )
        grouped.setdefault(key, []).append(assignment)

    blocks_by_ordinal: dict[int, dict[str, Any]] = {}
    for assignment in skipped_assignments:
        reason = str(
            (assignment.get("preprint_anchor_audit") or {}).get("block_reason")
            or "preprint_anchor_contract_blocked"
        )
        block = _skipped_preprint_provider_block(
            str(assignment["provider"]),
            str(assignment["query"]),
            reason,
            query_branch=str(assignment["query_branch"]),
            retrieval_strategy=str(assignment["retrieval_strategy"]),
            source_query=str(assignment["source_query"]),
        )
        block["preprint_anchor_audit"] = dict(assignment["preprint_anchor_audit"])
        block["single_paper_serial"] = True
        block["single_paper_ordinal"] = int(assignment["ordinal"])
        block = attach_query_plan_provenance(
            block,
            assignment.get("plan") if isinstance(assignment.get("plan"), dict) else {},
        )
        blocks_by_ordinal[int(assignment["ordinal"])] = block
    for (provider, layer_query, _required_group_key), group in grouped.items():
        batch_size = len(group)
        group_anchor_contract = (
            group[0].get("branch_anchor_contract")
            if group and isinstance(group[0].get("branch_anchor_contract"), dict)
            else anchor_contract
        )
        log_event(
            "SCIENCE",
            "stratified_provider_batch_dispatch",
            provider=provider,
            layer=layer_name,
            batch_size=batch_size,
            query=layer_query[:180],
            branch_required_semantic_anchor_group=list(
                (group_anchor_contract or {}).get("branch_required_semantic_anchor_group") or []
            )[:16],
        )
        if provider == "semantic_scholar":
            batch_block = dispatch_compiled_provider_query(
                provider,
                layer_query,
                lambda provider_query: semantic_scholar_skip_block(provider_query) or search_semantic_scholar(
                    provider_query,
                    max_results=batch_size,
                    offset=0,
                ),
                anchor_contract=group_anchor_contract,
            )
        elif provider == "pubmed":
            batch_block = dispatch_compiled_provider_query(
                provider,
                layer_query,
                lambda provider_query: search_pubmed(
                    provider_query,
                    max_results=batch_size,
                    offset=0,
                    mesh_terms=provider_taxonomy_filters.get("pubmed", {}).get("mesh_terms")
                    if provider_taxonomy_filters.get("pubmed", {}).get("applied")
                    else None,
                ),
                anchor_contract=group_anchor_contract,
            )
        elif provider == "arxiv":
            batch_block = dispatch_compiled_provider_query(
                provider,
                layer_query,
                lambda provider_query: search_arxiv(
                    provider_query,
                    max_results=batch_size,
                    sort_by="submittedDate" if layer_name == "L3_preprint" else "relevance",
                    offset=0,
                    categories=provider_taxonomy_filters.get("arxiv", {}).get("categories")
                    if provider_taxonomy_filters.get("arxiv", {}).get("applied")
                    else None,
                ),
            )
        elif provider in {"biorxiv", "medrxiv", "chemrxiv"}:
            batch_block = dispatch_compiled_provider_query(
                provider,
                layer_query,
                lambda provider_query: search_preprint_api(
                    provider,
                    provider_query,
                    max_results=batch_size,
                    offset=0,
                ),
            )
        else:
            batch_block = provider_error_result(
                provider,
                layer_query,
                ValueError("batched stratified retrieval is unsupported"),
            )

        batch_results = (
            batch_block.get("results")
            if isinstance(batch_block.get("results"), list)
            else []
        )
        completion_fields = {
            "provider": provider,
            "layer": layer_name,
            "batch_size": batch_size,
            "provider_status": str(batch_block.get("status") or "unknown"),
            "result_count": len(batch_results),
        }
        if block_error := str(batch_block.get("error") or "")[:200]:
            completion_fields["provider_error"] = block_error
        log_event("SCIENCE", "stratified_provider_batch_complete", **completion_fields)
        for index, assignment in enumerate(group):
            result = batch_results[index] if index < len(batch_results) and isinstance(batch_results[index], dict) else None
            block = dict(batch_block)
            block["discipline_filter_audit"] = dict(provider_taxonomy_filters.get(provider) or {})
            block["results"] = [result] if result is not None else []
            block["single_paper_serial"] = True
            block["provider_request_batched"] = True
            block["provider_batch_size"] = batch_size
            block["provider_batch_index"] = index
            block["single_paper_ordinal"] = int(assignment["ordinal"])
            block["single_paper_offset"] = index
            block["query_branch"] = str(assignment["query_branch"])
            block["retrieval_strategy"] = str(assignment["retrieval_strategy"])
            if layer_name == "L3_preprint":
                block["preprint_anchor_audit"] = dict(assignment["preprint_anchor_audit"] or {})
                block = _annotate_preprint_layer_block(
                    block,
                    query_branch=str(assignment["query_branch"]),
                    retrieval_strategy=str(assignment["retrieval_strategy"]),
                    source_query=str(assignment["source_query"]),
                )
            block = attach_query_plan_provenance(
                block,
                assignment.get("plan") if isinstance(assignment.get("plan"), dict) else {},
            )
            blocks_by_ordinal[int(assignment["ordinal"])] = block
            if result is not None and str(result.get("title") or "").strip():
                log_event(
                    "SCIENCE",
                    "stratified_candidate_slot",
                    provider=provider,
                    layer=layer_name,
                    ordinal=int(assignment["ordinal"]),
                    provider_status=str(batch_block.get("status") or "unknown"),
                    candidate_present=True,
                    title=str(result.get("title") or "")[:240],
                    year=str(result.get("year") or ""),
                    provider_request_batched=True,
                    provider_batch_size=batch_size,
                )

    return [blocks_by_ordinal[index] for index in sorted(blocks_by_ordinal)]


def fetch_stratified_layer_blocks(
    query: str,
    providers: list[str],
    layer: dict[str, Any],
    query_plan: list[dict[str, str]] | None = None,
    domain: str = "",
    preprint_layers: set[str] | None = None,
    preprint_required_anchor_groups: list[list[str]] | None = None,
    preprint_anchor_policy: dict[str, Any] | None = None,
    preprint_scan_limit: int | None = None,
    preprint_provider_result_target: int = 0,
    preprint_max_branches: int | None = None,
    single_paper_serial: bool = False,
    anchor_contract: dict[str, Any] | None = None,
    discipline_taxonomy: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    try:
        from ._utils import clamp_int
        from ._discipline_taxonomy import compile_provider_discipline_filter
    except ImportError:
        from _utils import clamp_int
        from _discipline_taxonomy import compile_provider_discipline_filter
    provider_taxonomy_filters = {
        provider: compile_provider_discipline_filter(provider, discipline_taxonomy)
        for provider in providers
    }
    layer_name = str(layer.get("layer", ""))
    if layer_name == "L1_milestone":
        log_event(
            "SCIENCE",
            "broad_pool_L1_retrieval_suppressed",
            target=max(0, int(layer.get("quota") or 0)),
            reason="Use search_foundational_mechanism_bridges for L1.",
            L1_from_broad_pool=0,
        )
        return []
    if single_paper_serial:
        return attach_query_plan_provenance_to_blocks(
            fetch_stratified_layer_blocks_one_paper_at_a_time(
                query,
                providers,
                layer,
                query_plan=query_plan,
                domain=domain,
                preprint_layers=preprint_layers,
                preprint_required_anchor_groups=preprint_required_anchor_groups,
                preprint_anchor_policy=preprint_anchor_policy,
                anchor_contract=anchor_contract,
                discipline_taxonomy=discipline_taxonomy,
            ),
            query_plan,
        )
    suffix = str(layer.get("query_suffix", "")).strip()
    fetch_limit = max(12, int(layer.get("quota", 1)) * 8)
    blocks: list[dict[str, Any]] = []
    plans = _query_plan_for_retrieval_layer(query_plan, layer_name) or [{"branch": "primary", "query": query}]
    plans = plans[: clamp_int(SCIENCE_STRATIFIED_MAX_BRANCHES_PER_LAYER, 1, 20)]
    if layer_name == "L3_preprint" and preprint_max_branches is not None:
        plans = plans[: clamp_int(preprint_max_branches, 1, len(plans))]
    plan_candidate_limits = _candidate_budget_allocations(plans, fetch_limit)
    # Preprint records are never review or regular-paper backfill.  Normalize
    # at the dispatch boundary too, so a legacy caller cannot bypass the L3
    # source-role contract by passing L0/L4 explicitly.
    allowed_preprint_layers = normalize_preprint_source_layers(preprint_layers)
    effective_preprint_anchor_policy = (
        preprint_anchor_policy
        if isinstance(preprint_anchor_policy, dict)
        else build_preprint_anchor_policy(query=query)
    )
    for plan, plan_candidate_limit in zip(plans, plan_candidate_limits):
        if plan_candidate_limit <= 0:
            continue
        branch = str(plan.get("branch") or "primary")
        planned_query = str(plan.get("query") or query)
        layer_query = stratified_layer_retrieval_query(layer_name, planned_query, suffix)
        if layer_name == "L3_preprint":
            if layer_name not in allowed_preprint_layers:
                continue
            requirement = preprint_branch_anchor_requirement(
                branch,
                anchor_policy=effective_preprint_anchor_policy,
                inherited_anchor_groups=preprint_required_anchor_groups,
                planned_query=planned_query,
            )
            # Preprint endpoints do not perform the same semantic expansion as
            # Semantic Scholar. Passing an entire user objective or every
            # sub-branch token into arXiv makes it silently return unrelated
            # newest papers. Use a compact, provider-safe query instead.
            preprint_query = compact_preprint_retrieval_query(
                planned_query,
                domain=domain,
                required_anchor_groups=requirement["required_anchor_groups"],
            )
            anchor_audit = preprint_query_anchor_audit(
                planned_query,
                preprint_query,
                required_anchor_groups=requirement["required_anchor_groups"],
                require_object_anchor=True,
                object_anchor_group=requirement["object_anchor_group"],
                branch=branch,
                prerequisite_failure=str(requirement.get("block_reason") or ""),
            )
            log_event(
                "SCIENCE",
                "preprint_query_anchor_audit",
                provider="arxiv",
                query_branch=branch,
                preserved_groups=anchor_audit["preserved_group_count"],
                required_groups=anchor_audit["required_group_count"],
                dropped_groups=anchor_audit["dropped_groups"],
                object_anchor_required=anchor_audit["object_anchor_required"],
                object_anchor_preserved=anchor_audit["object_anchor_preserved"],
                block_reason=anchor_audit["block_reason"],
                dispatch_allowed=anchor_audit["dispatch_allowed"],
            )
            preprint_result_count = 0
            if "arxiv" in providers:
                if not anchor_audit["dispatch_allowed"]:
                    block = arxiv_skip_block(preprint_query) or {
                        "provider": "arxiv",
                        "query": preprint_query,
                        "status": "skipped",
                        "results": [],
                    }
                    block.update({
                        "status": "skipped",
                        "skipped_provider_reason": str(
                            anchor_audit.get("block_reason")
                            or "preprint_anchor_contract_blocked"
                        ),
                        "results": [],
                    })
                else:
                    block = dispatch_compiled_provider_query(
                        "arxiv",
                        preprint_query,
                        lambda provider_query: arxiv_skip_block(provider_query) or search_arxiv(
                            provider_query,
                            max_results=plan_candidate_limit,
                            sort_by="submittedDate",
                            categories=provider_taxonomy_filters.get("arxiv", {}).get("categories")
                            if provider_taxonomy_filters.get("arxiv", {}).get("applied")
                            else None,
                        ),
                    )
                block["discipline_filter_audit"] = dict(provider_taxonomy_filters.get("arxiv") or {})
                block["preprint_anchor_audit"] = anchor_audit
                blocks.append(_annotate_preprint_layer_block(
                    block,
                    query_branch=branch,
                    retrieval_strategy="latest_preprint_query",
                    source_query=planned_query,
                ))
                preprint_result_count += len(block.get("results") or [])
            for provider in ("biorxiv", "medrxiv", "chemrxiv"):
                if provider in providers:
                    if preprint_provider_result_target and preprint_result_count >= preprint_provider_result_target:
                        blocks.append(_skipped_preprint_provider_block(
                            provider,
                            preprint_query,
                            f"sufficient_preprint_candidates={preprint_result_count}; target={preprint_provider_result_target}",
                            query_branch=branch,
                            retrieval_strategy="latest_preprint_query",
                            source_query=planned_query,
                        ))
                        continue
                    block = (
                        dispatch_compiled_provider_query(
                            provider,
                            preprint_query,
                            lambda provider_query: _search_preprint_with_controls(
                                provider,
                                provider_query,
                                max_results=min(plan_candidate_limit, 20),
                                scan_limit=preprint_scan_limit,
                            ),
                        )
                        if anchor_audit["dispatch_allowed"]
                        else _skipped_preprint_provider_block(
                            provider,
                            preprint_query,
                            str(
                                anchor_audit.get("block_reason")
                                or "preprint_anchor_contract_blocked"
                            ),
                            query_branch=branch,
                            retrieval_strategy="latest_preprint_query",
                            source_query=planned_query,
                        )
                    )
                    block["discipline_filter_audit"] = dict(provider_taxonomy_filters.get(provider) or {})
                    block["preprint_anchor_audit"] = anchor_audit
                    blocks.append(_annotate_preprint_layer_block(
                        block,
                        query_branch=branch,
                        retrieval_strategy="latest_preprint_query",
                        source_query=planned_query,
                    ))
                    preprint_result_count += len(block.get("results") or [])
            # L3 is intentionally sourced only from preprint servers. A
            # Semantic Scholar record with an arXiv id may already represent a
            # published journal article, so it belongs to L4/L2 rather than
            # being used as a preprint fallback.
            continue
        if "semantic_scholar" in providers:
            branch_anchor_contract = branch_anchor_contract_for_query_plan(
                anchor_contract,
                plan,
            )
            block = dispatch_compiled_provider_query(
                "semantic_scholar",
                layer_query,
                lambda provider_query: search_semantic_scholar(
                    provider_query,
                    max_results=plan_candidate_limit,
                ),
                anchor_contract=branch_anchor_contract,
            )
            block["query_branch"] = branch
            if branch_anchor_contract:
                block["branch_required_semantic_anchor_group"] = list(
                    branch_anchor_contract.get("branch_required_semantic_anchor_group") or []
                )[:16]
            block["retrieval_strategy"] = stratified_layer_retrieval_strategy(layer_name)
            block["discipline_filter_audit"] = dict(provider_taxonomy_filters.get("semantic_scholar") or {})
            blocks.append(block)
        if "pubmed" in providers:
            branch_anchor_contract = branch_anchor_contract_for_query_plan(
                anchor_contract,
                plan,
            )
            block = dispatch_compiled_provider_query(
                "pubmed",
                layer_query,
                lambda provider_query: search_pubmed(
                    provider_query,
                    max_results=plan_candidate_limit,
                    mesh_terms=provider_taxonomy_filters.get("pubmed", {}).get("mesh_terms")
                    if provider_taxonomy_filters.get("pubmed", {}).get("applied")
                    else None,
                ),
                anchor_contract=branch_anchor_contract,
            )
            block["query_branch"] = branch
            if branch_anchor_contract:
                block["branch_required_semantic_anchor_group"] = list(
                    branch_anchor_contract.get("branch_required_semantic_anchor_group") or []
                )[:16]
            block["retrieval_strategy"] = stratified_layer_retrieval_strategy(layer_name)
            block["discipline_filter_audit"] = dict(provider_taxonomy_filters.get("pubmed") or {})
            blocks.append(block)
        if layer_name == "L0_review" and layer_name in allowed_preprint_layers and "arxiv" in providers:
            arxiv_q = compact_preprint_retrieval_query(
                layer_query,
                domain=domain,
                required_anchor_groups=preprint_required_anchor_groups,
            )
            block = dispatch_compiled_provider_query(
                "arxiv",
                arxiv_q,
                lambda provider_query: arxiv_skip_block(provider_query) or search_arxiv(
                    provider_query,
                    max_results=min(plan_candidate_limit, 20),
                    categories=provider_taxonomy_filters.get("arxiv", {}).get("categories")
                    if provider_taxonomy_filters.get("arxiv", {}).get("applied")
                    else None,
                ),
            )
            block["query_branch"] = branch
            block["retrieval_strategy"] = "review_query"
            block["discipline_filter_audit"] = dict(provider_taxonomy_filters.get("arxiv") or {})
            blocks.append(block)
        if layer_name == "L0_review" and layer_name in allowed_preprint_layers:
            for provider in ("biorxiv", "medrxiv", "chemrxiv"):
                if provider in providers:
                    pre_q = compact_preprint_retrieval_query(
                        layer_query,
                        domain=domain,
                        required_anchor_groups=preprint_required_anchor_groups,
                    )
                    block = dispatch_compiled_provider_query(
                        provider,
                        pre_q,
                        lambda provider_query: _search_preprint_with_controls(
                            provider,
                            provider_query,
                            max_results=min(plan_candidate_limit, 20),
                            scan_limit=preprint_scan_limit,
                        ),
                    )
                    blocks.append(_annotate_preprint_layer_block(
                        block,
                        query_branch=branch,
                        retrieval_strategy="review_query",
                        source_query=layer_query,
                    ))
        if layer_name == "L4_regular" and layer_name in allowed_preprint_layers and "arxiv" in providers:
            arxiv_q = compact_preprint_retrieval_query(
                planned_query,
                domain=domain,
                required_anchor_groups=preprint_required_anchor_groups,
            )
            block = dispatch_compiled_provider_query(
                "arxiv",
                arxiv_q,
                lambda provider_query: arxiv_skip_block(provider_query) or search_arxiv(
                    provider_query,
                    max_results=min(plan_candidate_limit, 20),
                    categories=provider_taxonomy_filters.get("arxiv", {}).get("categories")
                    if provider_taxonomy_filters.get("arxiv", {}).get("applied")
                    else None,
                ),
            )
            block["query_branch"] = branch
            block["retrieval_strategy"] = "regular_backfill_query"
            block["discipline_filter_audit"] = dict(provider_taxonomy_filters.get("arxiv") or {})
            blocks.append(block)
        if layer_name == "L4_regular" and layer_name in allowed_preprint_layers:
            for provider in ("biorxiv", "medrxiv", "chemrxiv"):
                if provider in providers:
                    pre_q = compact_preprint_retrieval_query(
                        planned_query,
                        domain=domain,
                        required_anchor_groups=preprint_required_anchor_groups,
                    )
                    block = dispatch_compiled_provider_query(
                        provider,
                        pre_q,
                        lambda provider_query: _search_preprint_with_controls(
                            provider,
                            provider_query,
                            max_results=min(plan_candidate_limit, 20),
                            scan_limit=preprint_scan_limit,
                        ),
                    )
                    blocks.append(_annotate_preprint_layer_block(
                        block,
                        query_branch=branch,
                        retrieval_strategy="regular_backfill_query",
                        source_query=planned_query,
                    ))
    return attach_query_plan_provenance_to_blocks(blocks, query_plan)

def stratified_layer_retrieval_query(layer_name: str, planned_query: str, suffix: str) -> str:
    try:
        from ._utils import normalize_space
    except ImportError:
        from _utils import normalize_space
    base = normalize_space(planned_query)
    return normalize_space(f"{base} {suffix}".strip())


PREPRINT_LOW_SIGNAL_TERMS = {
    "agent", "analysis", "approach", "benchmark", "case", "collaboration",
    "dataset", "evaluation", "experiment", "framework", "hypothesis", "latest",
    "literature", "method", "model", "paper", "preprint", "prediction", "recent",
    "research", "review", "science", "search", "study", "survey", "system",
    "testing", "validation", "workflow",
}

PREPRINT_BROAD_DOMAIN_TERMS = {
    "biostatistics", "clinical", "gene", "genes", "manufacturing", "medicine",
    "medical", "model", "models", "multiomics", "omics", "patient", "patients",
    "patient-derived", "personalized", "pharmacology", "precision", "regulatory",
    "science", "therapy", "therapies",
}

PREPRINT_MATCH_LOW_SIGNAL_TERMS = PREPRINT_LOW_SIGNAL_TERMS | {
    "associated", "association", "background", "data", "effect", "effects",
    "evidence", "health", "human", "humans", "impact", "impacts", "result",
    "results", "risk", "risks", "studies", "using",
}

PREPRINT_GENERIC_SCIENCE_TERMS = {
    "balance", "cell", "cells", "clinical", "concentration", "differentiation",
    "disease", "diseases", "expression", "function", "functions", "gene", "genes",
    "genetic", "genetics", "genome", "genomes", "genomic", "homeostasis",
    "immune", "inflammation", "medical", "medicine", "molecular", "patient", "patients",
    "proliferation", "protein", "proteins", "regulation", "regulatory", "response",
    "responses", "signaling", "causal", "failure", "inhibition", "interaction",
    "interactions", "limitation", "mechanism", "mechanisms", "overexpression",
    "perturbation", "resistance", "validated",
}
PREPRINT_SOURCE_LAYERS = frozenset({"L3_preprint"})


def normalize_preprint_source_layers(
    layers: list[str] | set[str] | tuple[str, ...] | None,
) -> set[str]:
    """Keep unpublished-provider discovery confined to the dedicated L3 lane."""
    requested = (
        {str(layer).strip() for layer in layers if str(layer).strip()}
        if layers is not None
        else set(PREPRINT_SOURCE_LAYERS)
    )
    return requested & PREPRINT_SOURCE_LAYERS


def _preprint_anchor_terms(values: list[Any] | tuple[Any, ...], *, limit: int = 12) -> list[str]:
    terms: list[str] = []
    seen: set[str] = set()
    for value in values:
        for token in preprint_query_tokens(str(value or "")):
            if token not in seen:
                seen.add(token)
                terms.append(token)
                if len(terms) >= limit:
                    return terms
    return terms


def _preprint_anchor_values(value: Any) -> list[Any]:
    """Normalize one contract field without splitting a phrase into characters."""
    if isinstance(value, (list, tuple, set)):
        return list(value)
    return [value] if str(value or "").strip() else []


def _preprint_anchor_variants(value: Any, *, limit: int = 12) -> list[str]:
    """Keep each declared phrase or identifier as an alternative anchor."""
    variants: list[str] = []
    seen: set[tuple[str, ...]] = set()
    for raw_value in _preprint_anchor_values(value):
        tokens = preprint_query_tokens(str(raw_value or ""))
        signature = tuple(tokens)
        if not signature or signature in seen:
            continue
        seen.add(signature)
        variants.append(" ".join(tokens))
        if len(variants) >= limit:
            break
    return variants


def _preprint_object_anchor_variants(value: Any, *, limit: int = 12) -> list[str]:
    """Keep named object phrases while rejecting their generic component words."""
    candidates: list[tuple[str, list[str], bool]] = []
    for raw_value in _preprint_anchor_values(value):
        raw_text = str(raw_value or "").strip()
        tokens = preprint_query_tokens(raw_text)
        if not tokens:
            continue
        compact_raw = re.sub(r"[^A-Za-z0-9]", "", raw_text)
        atomic_identifier = bool(
            re.fullmatch(r"[A-Z]{2,}[a-z]?", compact_raw)
            or any(char.isdigit() for char in compact_raw)
        )
        candidates.append((" ".join(tokens), tokens, atomic_identifier))
    has_phrase = any(len(tokens) > 1 for _, tokens, _ in candidates)
    filtered = [
        value
        for value, tokens, atomic_identifier in candidates
        if len(tokens) > 1 or atomic_identifier or not has_phrase
    ]
    return _preprint_anchor_variants(filtered, limit=limit)


def build_preprint_anchor_policy(
    *,
    query: str,
    research_question_card: dict[str, Any] | None = None,
    candidate_alignment_contract: dict[str, Any] | None = None,
    retrieval_anchor_contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Derive only the source-bound anchors needed for L3 query dispatch."""
    alignment = candidate_alignment_contract if isinstance(candidate_alignment_contract, dict) else {}
    object_policy = (
        alignment.get("scientific_object_anchor_policy")
        if isinstance(alignment.get("scientific_object_anchor_policy"), dict)
        else {}
    )
    core_axis_policy = (
        alignment.get("core_axis_policy")
        if isinstance(alignment.get("core_axis_policy"), dict)
        else {}
    )
    object_values = (
        _preprint_anchor_values(object_policy.get("strong_anchor_phrases"))
        + _preprint_anchor_values(object_policy.get("strong_anchor_terms"))
        + _preprint_anchor_values(object_policy.get("object_group"))
    )
    object_variants = _preprint_object_anchor_variants(object_values)
    object_source = "scientific_object_anchor_policy" if object_variants else "missing_scientific_object_anchor_policy"

    input_variants = _preprint_anchor_variants(
        _preprint_anchor_values(core_axis_policy.get("focal_variable_phrases"))
        + _preprint_anchor_values(core_axis_policy.get("focal_variable_terms"))
    )
    mechanism_variants = _preprint_anchor_variants(
        _preprint_anchor_values(core_axis_policy.get("mechanism_phrases"))
        + _preprint_anchor_values(core_axis_policy.get("mechanism_terms"))
    )
    outcome_variants = _preprint_anchor_variants(
        _preprint_anchor_values(core_axis_policy.get("outcome_phrases"))
        + _preprint_anchor_values(core_axis_policy.get("outcome_terms"))
    )
    return {
        "version": "preprint_anchor_policy_v2",
        "object_anchor_group": object_variants,
        "intervention_anchor_group": input_variants,
        "mechanism_anchor_group": mechanism_variants,
        "outcome_anchor_group": outcome_variants,
        "object_anchor_source": object_source,
    }


def preprint_branch_anchor_requirement(
    branch: str,
    *,
    anchor_policy: dict[str, Any] | None,
    inherited_anchor_groups: list[list[str]] | None = None,
    planned_query: str = "",
) -> dict[str, Any]:
    """Require the scientific object plus one branch-local L3 anchor."""
    policy = anchor_policy if isinstance(anchor_policy, dict) else {}
    object_group = _preprint_object_anchor_variants(policy.get("object_anchor_group"))
    intervention_group = _preprint_anchor_variants(policy.get("intervention_anchor_group"))
    mechanism_group = _preprint_anchor_variants(policy.get("mechanism_anchor_group"))
    outcome_group = _preprint_anchor_variants(policy.get("outcome_anchor_group"))
    inherited = [
        _preprint_anchor_variants(group)
        for group in (inherited_anchor_groups or [])
        if isinstance(group, (list, tuple, set))
    ]
    inherited = [group for group in inherited if group]
    if not object_group and inherited:
        object_group = list(inherited[0])
    if not object_group:
        return {
            "dispatch_allowed": False,
            "block_reason": "missing_research_object_anchor",
            "object_anchor_group": [],
            "required_anchor_groups": [],
        }

    object_tokens = {
        token
        for variant in object_group
        for token in preprint_query_tokens(variant)
    }
    branch_local_group = [
        token
        for token in preprint_query_tokens(planned_query)
        if token not in object_tokens
    ]
    normalized_branch = str(branch or "primary").lower().replace("-", "_").replace(" ", "_")
    required_groups: list[list[str]] = [object_group]
    if "direct_mechanism" in normalized_branch:
        intervention_or_mechanism = intervention_group or mechanism_group or (inherited[1] if len(inherited) >= 2 else [])
        direct_outcome = outcome_group or (inherited[2] if len(inherited) >= 3 else [])
        if not intervention_or_mechanism:
            return {
                "dispatch_allowed": False,
                "block_reason": "missing_direct_intervention_or_mechanism_anchor",
                "object_anchor_group": object_group,
                "required_anchor_groups": required_groups,
            }
        if not direct_outcome:
            return {
                "dispatch_allowed": False,
                "block_reason": "missing_direct_outcome_anchor",
                "object_anchor_group": object_group,
                "required_anchor_groups": required_groups + [intervention_or_mechanism],
            }
        required_groups.extend([intervention_or_mechanism, direct_outcome])
    elif "barrier_failure" in normalized_branch:
        barrier_mechanism = mechanism_group or (inherited[1] if len(inherited) >= 2 else [])
        if not barrier_mechanism:
            return {
                "dispatch_allowed": False,
                "block_reason": "missing_barrier_mechanism_anchor",
                "object_anchor_group": object_group,
                "required_anchor_groups": required_groups,
            }
        required_groups.append(barrier_mechanism)
    elif not branch_local_group:
        return {
            "dispatch_allowed": False,
            "block_reason": "missing_branch_local_anchor",
            "object_anchor_group": object_group,
            "required_anchor_groups": required_groups,
        }
    else:
        required_groups.append(branch_local_group)
    return {
        "dispatch_allowed": True,
        "block_reason": "",
        "object_anchor_group": object_group,
        "required_anchor_groups": required_groups,
    }


def preprint_query_tokens(text: str) -> list[str]:
    """Extract provider-safe Latin/scientific tokens from a free-form query."""
    raw = re.findall(r"[A-Za-z][A-Za-z0-9_-]{1,}|\d+(?:\.\d+)?[A-Za-z]+", str(text or ""))
    tokens: list[str] = []
    seen: set[str] = set()
    for value in raw:
        normalized = value.lower().strip("_-")
        if len(normalized) < 3 and not any(char.isdigit() for char in normalized):
            continue
        if normalized in PREPRINT_LOW_SIGNAL_TERMS or normalized in seen:
            continue
        seen.add(normalized)
        tokens.append(normalized)
    return tokens


def _normalized_preprint_anchor_groups(
    required_anchor_groups: list[list[str]] | None,
) -> list[list[list[str]]]:
    """Return phrase/identifier alternatives as token sequences per group."""
    groups: list[list[list[str]]] = []
    for raw_group in required_anchor_groups or []:
        if not isinstance(raw_group, (list, tuple, set)):
            continue
        variants = [
            preprint_query_tokens(str(item))
            for item in raw_group
            if preprint_query_tokens(str(item))
        ]
        if variants:
            groups.append(variants)
    return groups


def _preprint_anchor_group_matches_tokens(
    variants: list[list[str]],
    query_tokens: set[str],
) -> bool:
    return any(set(variant).issubset(query_tokens) for variant in variants)


def preprint_query_anchor_audit(
    planned_query: str,
    compact_query: str,
    *,
    required_anchor_groups: list[list[str]] | None = None,
    require_object_anchor: bool = False,
    object_anchor_group: list[str] | None = None,
    branch: str = "",
    prerequisite_failure: str = "",
) -> dict[str, Any]:
    """Record whether provider compaction preserved the local branch anchor."""
    compact_tokens = set(preprint_query_tokens(compact_query))
    groups = _normalized_preprint_anchor_groups(required_anchor_groups)
    object_group = _preprint_object_anchor_variants(object_anchor_group)
    object_variants = [preprint_query_tokens(item) for item in object_group]
    object_preserved = _preprint_anchor_group_matches_tokens(
        object_variants,
        compact_tokens,
    )
    dropped = [
        index
        for index, group in enumerate(groups)
        if not _preprint_anchor_group_matches_tokens(group, compact_tokens)
    ]
    block_reason = ""
    if prerequisite_failure:
        block_reason = str(prerequisite_failure)
    elif require_object_anchor and not object_group:
        # An empty required-anchor list is not an approval to search a broad
        # latest-preprint feed when the project itself has a research object.
        block_reason = "missing_research_object_anchor"
    elif require_object_anchor and not object_preserved:
        block_reason = "research_object_anchor_lost_during_preprint_compaction"
    elif dropped:
        block_reason = "required_anchor_lost_during_preprint_compaction"
    return {
        "planned_query": str(planned_query or ""),
        "compact_query": str(compact_query or ""),
        "branch": str(branch or "primary"),
        "required_group_count": len(groups),
        "preserved_group_count": len(groups) - len(dropped),
        "dropped_groups": dropped,
        "object_anchor_required": bool(require_object_anchor),
        "object_anchor_group": object_group,
        "object_anchor_preserved": object_preserved,
        "block_reason": block_reason,
        "dispatch_allowed": not block_reason,
    }


def compact_preprint_retrieval_query(
    planned_query: str,
    domain: str = "",
    max_terms: int = 6,
    required_anchor_groups: list[list[str]] | None = None,
) -> str:
    """Reduce a broad research instruction to stable preprint search anchors.

    The function is domain-general: it prefers specific scientific tokens and
    uses the declared domain as an anchor, while excluding orchestration words
    such as ``agent`` or ``hypothesis``. It deliberately preserves only a
    small number of terms because preprint APIs rank lexical queries, not a
    full natural-language research brief.
    """
    domain_tokens = preprint_query_tokens(domain)
    query_tokens = preprint_query_tokens(planned_query)
    domain_set = set(domain_tokens)
    query_positions = {token: index for index, token in enumerate(query_tokens)}
    candidates = list(dict.fromkeys(query_tokens + domain_tokens))
    specific_candidates = [token for token in candidates if token not in PREPRINT_BROAD_DOMAIN_TERMS]
    if len(specific_candidates) >= 2:
        candidates = specific_candidates
    elif specific_candidates:
        fallback_candidates = [
            token
            for token in candidates
            if token in {"manufacturing", "patient-derived", "pharmacology", "clinical"}
        ]
        candidates = specific_candidates + fallback_candidates

    def score(token: str) -> tuple[float, int, int]:
        value = float(min(len(token), 14)) / 6.0
        if any(char.isdigit() for char in token):
            value += 1.2
        if token in domain_set and token not in PREPRINT_BROAD_DOMAIN_TERMS:
            value += 0.35
        # Subspace plans append the concrete focus terms at the end. Favoring
        # those terms prevents a long project objective from drowning out the
        # actual scientific branch being searched.
        if token in query_positions:
            value += 0.9 * (query_positions[token] / max(1, len(query_tokens)))
        # Prefer concrete scientific words over extremely generic prose, but
        # retain source order as a deterministic final tiebreaker.
        return value, int(token in domain_set), -query_positions.get(token, 10_000)

    ranked = sorted(candidates, key=score, reverse=True)
    forced: list[str] = []
    candidate_set = set(candidates)
    for group in _normalized_preprint_anchor_groups(required_anchor_groups):
        matches = [
            variant for variant in group
            if set(variant).issubset(candidate_set)
        ]
        if matches:
            # A required group is a list of semantic alternatives. Preserve
            # a whole phrase or atomic identifier, never one arbitrary word
            # from a multi-word scientific object.
            for token in matches[0]:
                if token not in forced:
                    forced.append(token)
    # The usual compact query may contain four tokens.  A direct causal
    # contract has three mandatory axes, however, so it may reserve up to six
    # positions rather than silently deleting the outcome or mediator anchor.
    limit = max(len(forced), max(2, min(int(max_terms), 6)))
    chosen = (forced + [token for token in ranked if token not in forced])[:limit]
    return " ".join(chosen)


def arxiv_search_query_expression(
    query: str,
    *,
    categories: list[str] | tuple[str, ...] | None = None,
) -> str:
    """Build a valid arXiv API expression from lexical anchors and categories.

    Category restrictions are supplied by the discovery taxonomy after the
    human/agent query has been compiled.  They are conjunctive additions, so
    they cannot erase the query's object, mechanism, intervention, or outcome
    anchors.
    """
    tokens = preprint_query_tokens(query)
    if not tokens:
        return ""
    # The L3 compactor may exceed its ordinary size target when preserving all
    # mandatory object and branch anchors. Do not drop an audited anchor here.
    anchors = tokens
    lexical_expression = " AND ".join(f"all:{token}" for token in anchors)
    valid_categories = [
        category
        for category in (str(item).strip() for item in (categories or []))
        if re.fullmatch(r"[a-z-]+(?:\.[A-Za-z0-9-]+)?", category)
    ]
    valid_categories = list(dict.fromkeys(valid_categories))[:3]
    if not valid_categories:
        return lexical_expression
    category_expression = " OR ".join(f"cat:{category}" for category in valid_categories)
    return f"({lexical_expression}) AND ({category_expression})"


def preprint_result_matches_query(result: dict[str, Any], query: str) -> bool:
    """Defend L3 against broad newest-feed matches from preprint providers."""
    tokens = preprint_query_tokens(query)
    if not tokens:
        return False
    text = " ".join(str(result.get(key) or "") for key in ("title", "abstract")).lower()
    normalized_text = re.sub(r"[-_/]", " ", text)
    match_tokens = [token for token in tokens if token not in PREPRINT_MATCH_LOW_SIGNAL_TERMS]
    if not match_tokens:
        return False
    matched_tokens = {
        token
        for token in match_tokens
        if re.sub(r"[-_/]", " ", token) in normalized_text
    }
    specific_anchors = [token for token in match_tokens if token not in PREPRINT_GENERIC_SCIENCE_TERMS]
    required_specific_hits = 2 if len(specific_anchors) >= 2 else 1
    if specific_anchors and sum(token in matched_tokens for token in specific_anchors) < required_specific_hits:
        return False
    required = 2 if len(match_tokens) >= 4 else 1
    return len(matched_tokens) >= required

def stratified_layer_retrieval_strategy(layer_name: str) -> str:
    if layer_name == "L1_milestone":
        return "broad_recall_then_citation_rerank"
    if layer_name == "L2_top_latest":
        return "broad_recall_then_recent_top_venue_rerank"
    if layer_name == "L0_review":
        return "review_query"
    if layer_name == "L4_regular":
        return "regular_backfill_query"
    return "layer_query"


SEMANTIC_SCHOLAR_QUERY_MODIFIERS = {
    "advance",
    "barrier",
    "barriers",
    "breakthrough",
    "causal",
    "classic",
    "experimental",
    "failure",
    "foundational",
    "frontier",
    "high",
    "impact",
    "incomplete",
    "inefficiency",
    "influential",
    "journal",
    "landmark",
    "latest",
    "limitation",
    "limitations",
    "measurement",
    "mechanism",
    "mechanisms",
    "mediation",
    "meta-analysis",
    "perspective",
    "perturbation",
    "progress",
    "recent",
    "resistance",
    "review",
    "seminal",
    "survey",
    "systematic",
    "theoretical",
    "top",
    "tutorial",
    "validation",
    "necessary",
    "sufficient",
}


def compact_semantic_scholar_retrieval_query(query: str, max_terms: int = 16) -> str:
    """Return a compact topical query; quality and recency are ranked locally."""
    terms = [term for term in query_terms(query) if term not in SEMANTIC_SCHOLAR_QUERY_MODIFIERS]
    compact = " ".join(terms[: max(4, min(int(max_terms), 20))])
    return compact or normalize_space(str(query or ""))


def semantic_scholar_stratified_batch_limits(
    max_results: int,
    quotas: dict[str, int],
) -> tuple[int, int]:
    """Return bounded Semantic Scholar broad/review request sizes."""
    base_limit = max(
        int(SCIENCE_PROVIDER_PAGE_SIZE_SEMANTIC_SCHOLAR),
        min(
            int(SCIENCE_MAX_METADATA_RESULTS_PER_EVIDENCE_PATH),
            max(int(max_results or 0), int(SCIENCE_PROVIDER_PAGE_SIZE_SEMANTIC_SCHOLAR)),
        ),
    )
    review_target = max(1, int(quotas.get("L0_review", 0)))
    review_limit = max(
        5,
        min(
            max(10, int(SCIENCE_PROVIDER_PAGE_SIZE_SEMANTIC_SCHOLAR)),
            review_target * 2,
        ),
    )
    return base_limit, review_limit


def compact_pubmed_retrieval_query(query: str, max_terms: int = 10) -> str:
    """Build two broad Title/Abstract concept groups for PubMed.

    PubMed should retrieve a provider-sized topical pool.  Recency, venue,
    impact and evidence-layer labels are evaluated locally instead of being
    appended as untagged natural-language requirements.
    """
    terms = [
        term
        for term in query_terms(query)
        if term not in SEMANTIC_SCHOLAR_QUERY_MODIFIERS
    ][: max(2, min(int(max_terms), 12))]
    if not terms:
        return normalize_space(str(query or ""))

    def group(values: list[str]) -> str:
        clauses = [f'{value}[Title/Abstract]' for value in values]
        clauses.extend(
            f'"{values[index]} {values[index + 1]}"[Title/Abstract]'
            for index in range(len(values) - 1)
        )
        return "(" + " OR ".join(clauses) + ")"

    if len(terms) == 1:
        return f"{terms[0]}[Title/Abstract]"
    midpoint = max(1, len(terms) // 2)
    left = terms[:midpoint]
    right = terms[midpoint:]
    if not right:
        return group(left)
    return f"{group(left)} AND {group(right)}"


def pubmed_stratified_batch_limits(
    max_results: int,
    quotas: dict[str, int],
) -> tuple[int, int]:
    base_limit = max(
        int(SCIENCE_PROVIDER_PAGE_SIZE_PUBMED),
        min(
            int(SCIENCE_MAX_METADATA_RESULTS_PER_EVIDENCE_PATH),
            max(int(max_results or 0), int(SCIENCE_PROVIDER_PAGE_SIZE_PUBMED)),
        ),
    )
    review_target = max(1, int(quotas.get("L0_review", 0)))
    review_limit = max(
        5,
        min(max(10, int(SCIENCE_PROVIDER_PAGE_SIZE_PUBMED)), review_target * 2),
    )
    return base_limit, review_limit


def _query_plan_dispatch_allowed(plan: Mapping[str, Any] | None) -> bool:
    """Return whether a provider should submit this query-plan branch.

    Legacy query plans do not carry dispatch metadata, so the default is
    intentionally permissive.  The declared-input guard writes explicit block
    signals only after query repair fails; providers use this helper to avoid
    executing a scientifically invalid non-background branch.
    """

    if not isinstance(plan, Mapping):
        return False
    if plan.get("provider_query_executed") is False:
        return False
    if plan.get("query_execution_blocked") is True:
        return False
    if plan.get("provider_query_dispatch_suppressed") is True:
        return False
    if str(plan.get("query_execution_blocked_reason") or "").strip():
        return False
    return True


def _provider_branch_query_plans(
    query: str,
    query_plan: list[dict[str, Any]] | None,
    *,
    layer_name: str,
    max_plans: int = 3,
) -> list[dict[str, Any]]:
    """Return a small unique branch plan for providers that used to take one query."""

    candidates = _query_plan_for_retrieval_layer(query_plan, layer_name) or [
        dict(plan)
        for plan in (query_plan or [])
        if isinstance(plan, dict) and _query_plan_dispatch_allowed(plan)
    ]
    if not candidates:
        if query_plan:
            return []
        candidates = [{"branch": "primary", "query": query}]
    output: list[dict[str, Any]] = []
    seen: set[str] = set()
    limit = max(1, int(max_plans or 1))
    # A retrieval-object profile is intentionally a separate corpus query,
    # not a modifier to splice into the primary query.  Keep one normal SH
    # branch plus every non-primary OBJ branch even when the historic provider
    # cap is only three; otherwise OBJ2/OBJ3 are appended to the plan but can
    # never actually be dispatched behind the first three default branches.
    primary_candidates = [
        raw for raw in candidates
        if str(raw.get("retrieval_object_profile_role") or "primary_system")
        == "primary_system"
    ]
    profile_candidates = [
        raw for raw in candidates
        if str(raw.get("retrieval_object_profile_role") or "primary_system")
        != "primary_system"
    ]
    dispatch_order = [
        *primary_candidates[:1],
        *profile_candidates,
        *primary_candidates[1:],
    ]
    required_profile_slots = len({
        str(raw.get("retrieval_object_profile_id") or "")
        for raw in profile_candidates
        if str(raw.get("retrieval_object_profile_id") or "").strip()
    })
    limit = max(limit, min(3, 1 + required_profile_slots))
    for raw in dispatch_order:
        branch_query = str(raw.get("query") or query).strip()
        if not branch_query:
            continue
        fingerprint = normalize_space(branch_query.lower())
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        plan = dict(raw)
        plan.setdefault("branch", "primary")
        plan["query"] = branch_query
        output.append(plan)
        if len(output) >= limit:
            break
    if output:
        return output
    return [] if query_plan else [{"branch": "primary", "query": query}]


def fetch_pubmed_stratified_batch(
    query: str,
    *,
    max_results: int,
    quotas: dict[str, int],
    search_id: str = "",
    query_plan: list[dict[str, Any]] | None = None,
    anchor_contract: dict[str, Any] | None = None,
    discipline_taxonomy: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Fetch PubMed pools for the active evidence-path query branches."""
    disabled_reason = _literature_provider_disabled_reason("pubmed")
    if disabled_reason:
        log_event(
            "SCIENCE",
            "pubmed_provider_batch_disabled_by_policy",
            search_id=search_id,
            query=query[:240],
            reason=disabled_reason,
            query_branch_count=len(query_plan or []),
        )
        return [
            {
                "provider": "pubmed",
                "query": query,
                "status": "disabled_by_policy",
                "results": [],
                "reason": disabled_reason,
                "provider_batch_job_id": search_id or "pubmed_batch_disabled_by_policy",
                "retrieval_strategy": "pubmed_specialized_retrieval_disabled",
            }
        ]
    try:
        from ._discipline_taxonomy import compile_provider_discipline_filter
    except ImportError:
        from _discipline_taxonomy import compile_provider_discipline_filter
    discipline_filter = compile_provider_discipline_filter("pubmed", discipline_taxonomy)
    base_limit, review_limit = pubmed_stratified_batch_limits(max_results, quotas)
    base_plans = _provider_branch_query_plans(
        query,
        query_plan,
        layer_name="L4_regular",
        max_plans=SCIENCE_STRATIFIED_MAX_BRANCHES_PER_LAYER,
    )
    review_plans = _provider_branch_query_plans(
        query,
        query_plan,
        layer_name="L0_review",
        max_plans=max(2, SCIENCE_STRATIFIED_MAX_BRANCHES_PER_LAYER // 2),
    )
    base_query = compact_pubmed_retrieval_query(
        str(base_plans[0].get("query") or query) if base_plans else query
    )
    job_id = search_id or f"pubmed_batch_{abs(hash(base_query))}"
    requests: list[tuple[str, str, int, dict[str, Any]]] = []
    if base_limit > 0:
        base_plan_limits = _candidate_budget_allocations(base_plans, base_limit)
        for plan, plan_limit in zip(base_plans, base_plan_limits):
            if plan_limit <= 0:
                continue
            branch_query = compact_pubmed_retrieval_query(str(plan.get("query") or query))
            requests.append(("base", branch_query, plan_limit, plan))
    if review_limit > 0:
        review_plan_limits = _candidate_budget_allocations(
            review_plans,
            review_limit,
        )
        for plan, plan_limit in zip(review_plans, review_plan_limits):
            if plan_limit <= 0:
                continue
            branch_query = compact_pubmed_retrieval_query(str(plan.get("query") or query))
            review_query = (
                f"({branch_query}) AND "
                "(review[Publication Type] OR systematic[sb] OR meta-analysis[Publication Type])"
            )
            requests.append(("review", review_query, plan_limit, plan))
    blocks: list[dict[str, Any]] = []
    log_event(
        "SCIENCE",
        "pubmed_provider_batch_started",
        job_id=job_id,
        request_count=len(requests),
        base_limit=base_limit,
        review_limit=review_limit,
        query_branch_count=len({str(item[3].get("branch") or "primary") for item in requests}),
        query=base_query[:240],
    )
    for request_index, (request_kind, provider_query, limit, plan) in enumerate(requests, start=1):
        block = dispatch_compiled_provider_query(
            "pubmed",
            provider_query,
            lambda compiled_query: search_pubmed(
                compiled_query,
                max_results=limit,
                offset=0,
                mesh_terms=discipline_filter.get("mesh_terms") if discipline_filter.get("applied") else None,
            ),
            anchor_contract=anchor_contract,
        )
        branch = str(plan.get("branch") or "primary")
        block = attach_query_plan_provenance(block, plan)
        block["query_branch"] = branch
        block["discipline_filter_audit"] = discipline_filter
        block["provider_batch_job_id"] = job_id
        block["provider_batch_request_kind"] = request_kind
        block["provider_batch_request_index"] = request_index
        block["provider_batch_request_count"] = len(requests)
        blocks.append(block)
        results = block.get("results") if isinstance(block.get("results"), list) else []
        completion_fields = {
            "job_id": job_id,
            "request_kind": request_kind,
            "request_index": request_index,
            "query_branch": branch,
            "query": provider_query[:240],
            "limit": limit,
            "status": str(block.get("status") or "unknown"),
            "result_count": len(results),
        }
        if block_error := str(block.get("error") or "")[:200]:
            completion_fields["provider_failure"] = block_error
        log_event("SCIENCE", "pubmed_provider_batch_request_complete", **completion_fields)
    log_event(
        "SCIENCE",
        "pubmed_provider_batch_complete",
        job_id=job_id,
        requests_completed=len(blocks),
        result_count=sum(len(block.get("results") or []) for block in blocks),
    )
    return blocks


def fetch_semantic_scholar_stratified_batch(
    query: str,
    *,
    max_results: int,
    quotas: dict[str, int],
    search_id: str = "",
    query_plan: list[dict[str, Any]] | None = None,
    anchor_contract: dict[str, Any] | None = None,
    v3_variant_execution: bool = False,
) -> list[dict[str, Any]]:
    """Fetch Semantic Scholar pools for the active evidence-path query branches."""
    current_v3_plans, rejected_legacy_plans, non_contract_plans = partition_retrieval_plans_v3(
        query_plan
    )
    contract_rejection_blocks = _legacy_plan_contract_rejection_blocks(
        "semantic_scholar",
        rejected_legacy_plans,
        request_kind="L4_regular",
    )
    if current_v3_plans and not v3_variant_execution:
        blocks: list[dict[str, Any]] = []
        for plan in current_v3_plans:
            variants = materialize_query_variants_v3("semantic_scholar", plan)
            event_context = _v3_variant_event_context(plan)
            log_event(
                "SCIENCE",
                "v3_query_variant_plan_compiled",
                provider="semantic_scholar",
                variant_count=len(variants),
                **event_context,
            )
            blocks.extend(dispatch_query_variant_sequence_v3(
                "semantic_scholar",
                variants,
                lambda variant_query, _variant: fetch_semantic_scholar_stratified_batch(
                    variant_query,
                    max_results=max_results,
                    quotas=quotas,
                    search_id=search_id,
                    query_plan=[{**plan, "query": variant_query}],
                    anchor_contract=anchor_contract,
                    v3_variant_execution=True,
                ),
                event_context=event_context,
            ))
        return [*contract_rejection_blocks, *blocks]
    if rejected_legacy_plans:
        if not non_contract_plans:
            return contract_rejection_blocks
        # Explicitly non-contract discovery plans remain a separate workflow;
        # rejected legacy work items are never adapted into it.
        query_plan = non_contract_plans
    base_plans = _provider_branch_query_plans(
        query,
        query_plan,
        layer_name="L4_regular",
        max_plans=SCIENCE_STRATIFIED_MAX_BRANCHES_PER_LAYER,
    )
    review_plans = _provider_branch_query_plans(
        query,
        query_plan,
        layer_name="L0_review",
        max_plans=max(2, SCIENCE_STRATIFIED_MAX_BRANCHES_PER_LAYER // 2),
    )
    first_base_compilation = compile_structured_provider_query_from_plan(
        base_plans[0] if base_plans else {},
        "semantic_scholar",
        fallback_query=str(base_plans[0].get("query") or query) if base_plans else query,
        max_terms=12,
    )
    compact_query = (
        str(first_base_compilation.get("compiled_query") or "")
        if first_base_compilation.get("used_modules")
        else compact_semantic_scholar_retrieval_query(
            str(first_base_compilation.get("compiled_query") or base_plans[0].get("query") or query)
        )
    )
    base_limit, review_limit = semantic_scholar_stratified_batch_limits(max_results, quotas)
    job_id = search_id or f"semantic_scholar_batch_{abs(hash(compact_query))}"
    retry_budget = SemanticScholarRetryBudget(
        limit=semantic_scholar_search_retry_limit(),
        job_id=job_id,
        max_rate_limit_responses=3,
    )
    requests: list[tuple[str, str, int, dict[str, Any]]] = []
    if base_limit > 0:
        base_plan_limits = _candidate_budget_allocations(base_plans, base_limit)
        for plan, plan_limit in zip(base_plans, base_plan_limits):
            if plan_limit <= 0:
                continue
            module_compilation = compile_structured_provider_query_from_plan(
                plan,
                "semantic_scholar",
                fallback_query=str(plan.get("query") or query),
                max_terms=12,
            )
            branch_query = (
                str(module_compilation.get("compiled_query") or "")
                if module_compilation.get("used_modules")
                else compact_semantic_scholar_retrieval_query(
                    str(module_compilation.get("compiled_query") or plan.get("query") or query)
                )
            )
            if module_compilation.get("used_modules"):
                plan = {**plan, "query_module_compile": module_compilation}
            requests.append(("base", branch_query, plan_limit, plan))
    if review_limit > 0:
        review_plan_limits = _candidate_budget_allocations(
            review_plans,
            review_limit,
        )
        for plan, plan_limit in zip(review_plans, review_plan_limits):
            if plan_limit <= 0:
                continue
            module_compilation = compile_structured_provider_query_from_plan(
                plan,
                "semantic_scholar",
                fallback_query=str(plan.get("query") or query),
                max_terms=12,
            )
            branch_query = (
                str(module_compilation.get("compiled_query") or "")
                if module_compilation.get("used_modules")
                else compact_semantic_scholar_retrieval_query(
                    str(module_compilation.get("compiled_query") or plan.get("query") or query)
                )
            )
            if module_compilation.get("used_modules"):
                plan = {**plan, "query_module_compile": module_compilation}
            requests.append(
                ("review", normalize_space(f"{branch_query} review"), plan_limit, plan)
            )
    blocks: list[dict[str, Any]] = []
    log_event(
        "SCIENCE",
        "semantic_scholar_provider_batch_started",
        job_id=job_id,
        request_count=len(requests),
        retry_limit=retry_budget.limit,
        base_limit=base_limit,
        review_limit=review_limit,
        query_branch_count=len({str(item[3].get("branch") or "primary") for item in requests}),
        query=compact_query[:180],
    )
    for request_index, (request_kind, provider_query, limit, plan) in enumerate(requests, start=1):
        retry_budget.request_kind = request_kind
        branch_anchor_contract = branch_anchor_contract_for_query_plan(
            anchor_contract,
            plan,
        )
        block = dispatch_compiled_provider_query(
            "semantic_scholar",
            provider_query,
            lambda compiled_query: search_semantic_scholar(
                compiled_query,
                max_results=limit,
                offset=0,
                retry_budget=retry_budget,
            ),
            anchor_contract=branch_anchor_contract,
        )
        branch = str(plan.get("branch") or "primary")
        block = attach_query_plan_provenance(block, plan)
        block["query_branch"] = branch
        if branch_anchor_contract:
            block["branch_required_semantic_anchor_group"] = list(
                branch_anchor_contract.get("branch_required_semantic_anchor_group") or []
            )[:16]
        block["provider_batch_job_id"] = job_id
        block["provider_batch_request_kind"] = request_kind
        block["provider_batch_request_index"] = request_index
        block["provider_batch_request_count"] = len(requests)
        block["provider_batch_retry_limit"] = retry_budget.limit
        block["provider_batch_retries_used"] = retry_budget.retries_used
        blocks.append(block)
        results = block.get("results") if isinstance(block.get("results"), list) else []
        completion_fields = {
            "job_id": job_id,
            "request_kind": request_kind,
            "request_index": request_index,
            "query_branch": branch,
            "query": provider_query[:180],
            "limit": limit,
            "status": str(block.get("status") or "unknown"),
            "result_count": len(results),
            "retries_used": retry_budget.retries_used,
            "retry_budget_remaining": retry_budget.remaining,
            "branch_required_semantic_anchor_group": list(
                (branch_anchor_contract or {}).get("branch_required_semantic_anchor_group") or []
            )[:16],
        }
        if block_error := str(block.get("error") or "")[:200]:
            completion_fields["provider_error"] = block_error
        log_event("SCIENCE", "semantic_scholar_provider_batch_request_complete", **completion_fields)
        if (
            str(block.get("status") or "") != "ok"
            and is_semantic_scholar_rate_limit_error(str(block.get("error") or ""))
            and retry_budget.remaining <= 0
        ):
            break
    log_event(
        "SCIENCE",
        "semantic_scholar_provider_batch_complete",
        job_id=job_id,
        requests_completed=len(blocks),
        result_count=sum(len(block.get("results") or []) for block in blocks),
        retries_used=retry_budget.retries_used,
        retry_limit=retry_budget.limit,
    )
    return blocks


def semantic_scholar_l2_top_latest_retrieval_limit(l2_quota: int) -> int:
    """Return a bounded L2 candidate pool without the old 12--16 hard window."""

    return max(
        12,
        min(
            int(SCIENCE_MAX_METADATA_RESULTS_PER_EVIDENCE_PATH),
            max(1, int(l2_quota)) * 8,
        ),
    )


def semantic_scholar_l2_zero_result_recovery_query(compact_query: str) -> str:
    """Return one weaker same-provider query without adding ranking language.

    Semantic Scholar's ``paper/search`` query is a topical retrieval input,
    not a structured ``top journal`` or recency filter.  When a complete
    topical query produces zero results, retain its leading object/mechanism
    anchors and drop only its final modifier concept.  This is a single,
    explicit recovery attempt; L2 is never backfilled by OpenAlex or L4.
    """
    terms = query_terms(compact_query)
    if len(terms) > 2:
        return " ".join(terms[:-1])
    return ""


def fetch_semantic_scholar_l2_top_latest_batch(
    query: str,
    *,
    l2_quota: int,
    search_id: str = "",
    query_plan: list[dict[str, Any]] | None = None,
    retry_limit: int | None = None,
    allow_zero_result_recovery: bool = False,
    anchor_contract: dict[str, Any] | None = None,
    v3_variant_execution: bool = False,
) -> list[dict[str, Any]]:
    """Fetch one best-effort Semantic Scholar L2 supplement.

    The normal L2 path invokes this only after broad discovery and a focused
    OpenAlex supplement still leave a strict evidence shortfall.  It therefore
    makes one provider query with the same small, shared retry budget used by
    other Semantic Scholar search batches, but performs no zero-result query
    relaxation.  Recency, venue impact, and top-journal status remain in the
    local L2 classifier rather than being sent as ordinary search terms.
    """
    current_v3_plans, rejected_legacy_plans, non_contract_plans = partition_retrieval_plans_v3(
        query_plan
    )
    contract_rejection_blocks = _legacy_plan_contract_rejection_blocks(
        "semantic_scholar",
        rejected_legacy_plans,
        request_kind="L2_top_latest",
    )
    if current_v3_plans and not v3_variant_execution:
        blocks: list[dict[str, Any]] = []
        for plan in current_v3_plans:
            event_context = _v3_variant_event_context(plan)
            variants = materialize_query_variants_v3("semantic_scholar", plan)
            event_context["provider_request_kind"] = "L2_top_latest"
            log_event(
                "SCIENCE",
                "v3_query_variant_plan_compiled",
                provider="semantic_scholar",
                variant_count=len(variants),
                **event_context,
            )
            blocks.extend(dispatch_query_variant_sequence_v3(
                "semantic_scholar",
                variants,
                lambda variant_query, _variant: fetch_semantic_scholar_l2_top_latest_batch(
                    variant_query,
                    l2_quota=l2_quota,
                    search_id=search_id,
                    query_plan=[{**plan, "query": variant_query, "l2_query": variant_query}],
                    retry_limit=retry_limit,
                    allow_zero_result_recovery=False,
                    anchor_contract=anchor_contract,
                    v3_variant_execution=True,
                ),
                event_context=event_context,
            ))
        return [*contract_rejection_blocks, *blocks]
    if rejected_legacy_plans:
        if not non_contract_plans:
            return contract_rejection_blocks
        query_plan = non_contract_plans
    specs = compile_l2_provider_query_specs(
        query,
        query_plan,
        max_specs=max(2, SCIENCE_STRATIFIED_MAX_BRANCHES_PER_LAYER),
    )
    if not specs:
        return [
            {
                "provider": "semantic_scholar",
                "query": query,
                "status": "skipped",
                "results": [],
                "query_branch": "L2_top_latest",
                "provider_batch_job_id": f"{search_id}:L2_top_latest" if search_id else "semantic_scholar_l2_query_plan_blocked",
                "provider_batch_request_kind": "l2_top_latest",
                "skipped_provider_reason": "all_l2_query_plan_branches_blocked",
            }
        ]
    compact_query = str(specs[0].get("query") or compact_l2_provider_query(query, query_plan))
    semantic_limit = semantic_scholar_l2_top_latest_retrieval_limit(l2_quota)
    limit = semantic_limit
    job_id = f"{search_id}:L2_top_latest" if search_id else f"semantic_scholar_l2_{abs(hash(compact_query))}"
    effective_retry_limit = (
        semantic_scholar_search_retry_limit()
        if retry_limit is None
        else min(4, max(0, int(retry_limit)))
    )
    retry_budget = SemanticScholarRetryBudget(
        limit=effective_retry_limit,
        job_id=job_id,
        max_rate_limit_responses=3,
    )
    log_event(
        "SCIENCE",
        "semantic_scholar_l2_provider_batch_started",
        job_id=job_id,
        request_count=len(specs),
        retry_limit=retry_budget.limit,
        l2_quota=int(l2_quota),
        limit=limit,
        query_family="topical_primary_by_evidence_path",
        zero_result_recovery_max_attempts=int(bool(allow_zero_result_recovery)),
        queries=[str(spec.get("query") or "")[:180] for spec in specs],
        branches=[str(spec.get("query_branch") or "") for spec in specs],
    )
    blocks: list[dict[str, Any]] = []

    def dispatch(
        spec: dict[str, Any],
        *,
        request_kind: str,
        query_family: str,
        request_index: int,
    ) -> dict[str, Any]:
        retry_budget.request_kind = request_kind
        provider_query = str(spec.get("query") or "")
        plan_for_contract = (
            spec.get("plan") if isinstance(spec.get("plan"), dict) else spec
        )
        branch_anchor_contract = branch_anchor_contract_for_query_plan(
            anchor_contract,
            plan_for_contract,
        )
        raw_block = dispatch_compiled_provider_query(
            "semantic_scholar",
            provider_query,
            lambda compiled_query: search_semantic_scholar(
                compiled_query,
                max_results=limit,
                offset=0,
                retry_budget=retry_budget,
            ),
            anchor_contract=branch_anchor_contract,
        )
        # Providers normally return a fresh mapping for each request.  Copy it
        # nevertheless so a cache or a test double cannot make the recovery
        # metadata overwrite the primary request's record.
        block = dict(raw_block) if isinstance(raw_block, dict) else {
            "provider": "semantic_scholar",
            "status": "error",
            "error": "semantic_scholar_invalid_provider_response",
            "results": [],
        }
        block["provider_batch_job_id"] = job_id
        block["provider_batch_request_kind"] = request_kind
        block["provider_batch_query_family"] = query_family
        block["provider_batch_request_index"] = request_index
        block["provider_batch_request_count"] = len(specs)
        block["provider_batch_retry_limit"] = retry_budget.limit
        block["provider_batch_retries_used"] = retry_budget.retries_used
        block = attach_query_plan_provenance(block, spec.get("plan") if isinstance(spec.get("plan"), dict) else {})
        block["query_branch"] = str(spec.get("query_branch") or "")
        if branch_anchor_contract:
            block["branch_required_semantic_anchor_group"] = list(
                branch_anchor_contract.get("branch_required_semantic_anchor_group") or []
            )[:16]
        merged_branches = [
            str(value or "")
            for value in (spec.get("merged_query_branches") or [])
            if str(value or "")
        ]
        merged_kinds = [
            str(value or "")
            for value in (spec.get("merged_evidence_kinds") or [])
            if str(value or "")
        ]
        merged_roles = [
            str(value or "")
            for value in (spec.get("merged_evidence_path_roles") or [])
            if str(value or "")
        ]
        if merged_branches:
            block["matched_query_branches"] = merged_branches
            block["merged_query_branches"] = merged_branches
        if merged_kinds:
            block["matched_evidence_kinds"] = merged_kinds
        if merged_roles:
            block["matched_evidence_path_roles"] = merged_roles
        block["l2_query_branch_binding"] = {
            "query_branch": str(spec.get("query_branch") or ""),
            "evidence_kind": str(spec.get("evidence_kind") or ""),
            "evidence_path_role": str(spec.get("evidence_path_role") or ""),
            "source_query": str(spec.get("source_query") or "")[:240],
            "merged_branch_bindings": [
                dict(item)
                for item in (spec.get("merged_branch_bindings") or [])
                if isinstance(item, dict)
            ],
        }
        results = block.get("results") if isinstance(block.get("results"), list) else []
        completion_fields = {
            "job_id": job_id,
            "request_kind": request_kind,
            "query_family": query_family,
            "request_index": request_index,
            "query_branch": str(spec.get("query_branch") or ""),
            "evidence_kind": str(spec.get("evidence_kind") or ""),
            "evidence_path_role": str(spec.get("evidence_path_role") or ""),
            "query": provider_query[:180],
            "limit": limit,
            "merged_branches": merged_branches,
            "status": str(block.get("status") or "unknown"),
            "result_count": len(results),
            "retries_used": retry_budget.retries_used,
            "retry_budget_remaining": retry_budget.remaining,
            "branch_required_semantic_anchor_group": list(
                (branch_anchor_contract or {}).get("branch_required_semantic_anchor_group") or []
            )[:16],
        }
        if block_error := str(block.get("error") or "")[:200]:
            completion_fields["provider_error"] = block_error
        log_event("SCIENCE", "semantic_scholar_l2_provider_batch_complete", **completion_fields)
        return block

    primary_statuses: list[str] = []
    primary_results: list[dict[str, Any]] = []
    for request_index, spec in enumerate(specs, start=1):
        primary = dispatch(
            spec,
            request_kind="l2_top_latest",
            query_family="topical_primary_by_evidence_path",
            request_index=request_index,
        )
        blocks.append(primary)
        primary_statuses.append(str(primary.get("status") or ""))
        if isinstance(primary.get("results"), list):
            primary_results.extend(primary.get("results") or [])
    recovery_query = ""
    if allow_zero_result_recovery and primary_statuses and all(status == "ok" for status in primary_statuses) and not primary_results:
        recovery_query = semantic_scholar_l2_zero_result_recovery_query(compact_query)
        if recovery_query and recovery_query != compact_query:
            log_event(
                "SCIENCE",
                "semantic_scholar_l2_zero_result_recovery_scheduled",
                job_id=job_id,
                primary_query=compact_query[:180],
                recovery_query=recovery_query[:180],
                reason="provider_returned_zero_before_local_l2_filtering",
            )
            recovery_spec = dict(specs[0])
            recovery_spec["query"] = recovery_query
            recovery_spec["query_family"] = "anchor_relaxation"
            recovery = dispatch(
                recovery_spec,
                request_kind="l2_top_latest_zero_result_recovery",
                query_family="anchor_relaxation",
                request_index=len(specs) + 1,
            )
            blocks.append(recovery)

    total_results = sum(
        len(block.get("results") or [])
        for block in blocks
        if isinstance(block, dict)
    )
    for block in blocks:
        if isinstance(block, dict):
            block["provider_batch_request_count"] = len(blocks)
    if total_results == 0 and all(str(block.get("status") or "") == "ok" for block in blocks):
        log_event(
            "SCIENCE",
            "semantic_scholar_l2_provider_zero_results",
            job_id=job_id,
            query=compact_query[:180],
            recovery_query=recovery_query[:180],
            requests_completed=len(blocks),
            reason="semantic_scholar_returned_no_records_before_local_l2_filtering",
        )
    return blocks


L2_PROVIDER_QUERY_MODIFIERS = {
    "advance", "breakthrough", "experimental", "experiment", "feasibility",
    "framework", "high", "impact", "journal", "latest", "measurement",
    "model", "recent", "review", "theoretical", "theory", "top",
}

L2_DIRECT_EVIDENCE_KIND_ORDER = (
    "causal_validation",
    "causal_identification",
    "mechanism_discovery",
    "experimental_evidence",
    "association",
    "predictive_validation",
)


def compact_l2_provider_query_text(
    source: str,
    *,
    max_terms: int = 14,
) -> str:
    terms = [term for term in query_terms(source) if term not in L2_PROVIDER_QUERY_MODIFIERS]
    compact = " ".join(terms[: max(4, min(int(max_terms), 18))])
    return compact or compact_semantic_scholar_retrieval_query(source, max_terms=max_terms)


def compact_l2_provider_query(
    query: str,
    query_plan: list[dict[str, Any]] | None = None,
    *,
    max_terms: int = 14,
) -> str:
    """Choose one causal/topic query shared by the two L2 discovery sources."""
    planned_l2 = next(
        (
            str(plan.get("l2_query") or "").strip()
            for plan in (query_plan or [])
            if isinstance(plan, dict) and str(plan.get("l2_query") or "").strip()
        ),
        "",
    )
    return compact_l2_provider_query_text(planned_l2 or query, max_terms=max_terms)


def compile_l2_provider_query_specs(
    query: str,
    query_plan: list[dict[str, Any]] | None = None,
    *,
    max_terms: int = 14,
    max_specs: int = 2,
) -> list[dict[str, Any]]:
    """Build bounded L2 provider queries while preserving evidence-path roles."""

    raw_plans = [dict(plan) for plan in (query_plan or []) if isinstance(plan, dict)]
    all_plans_blocked = bool(raw_plans) and not any(
        _query_plan_dispatch_allowed(plan) for plan in raw_plans
    )
    plans = _query_plan_for_retrieval_layer(query_plan, "L2_top_latest")
    if all_plans_blocked and not plans:
        return []
    effective_max_specs = max(1, int(max_specs))
    if any(
        bool(plan.get("multi_entity_panel"))
        or str(plan.get("path_composition_policy") or "") == "multi_entity_panel_paths_independent_or"
        for plan in plans
    ):
        effective_max_specs = max(
            effective_max_specs,
            min(
                4,
                sum(
                    1
                    for plan in plans
                    if str(plan.get("evidence_kind") or "").strip().lower()
                    in L2_DIRECT_EVIDENCE_KIND_ORDER
                )
                or len(plans)
                or effective_max_specs,
            ),
        )
    direct_plans: list[dict[str, Any]] = []
    fallback_plans: list[dict[str, Any]] = []
    for plan in plans:
        l2_query = str(plan.get("l2_query") or plan.get("query") or "").strip()
        if not l2_query:
            continue
        evidence_kind = str(plan.get("evidence_kind") or "").strip().lower()
        evidence_path_role = str(plan.get("evidence_path_role") or "").strip().lower()
        if evidence_kind in L2_DIRECT_EVIDENCE_KIND_ORDER or evidence_path_role in L2_DIRECT_EVIDENCE_KIND_ORDER:
            direct_plans.append(plan)
        else:
            fallback_plans.append(plan)
    ordered_plans = sorted(
        direct_plans,
        key=lambda plan: (
            0 if str(plan.get("panel_evidence_tier") or "").strip().lower() == "core" else 1,
            min(
                [
                    L2_DIRECT_EVIDENCE_KIND_ORDER.index(value)
                    for value in (
                        str(plan.get("evidence_kind") or "").strip().lower(),
                        str(plan.get("evidence_path_role") or "").strip().lower(),
                    )
                    if value in L2_DIRECT_EVIDENCE_KIND_ORDER
                ]
                or [len(L2_DIRECT_EVIDENCE_KIND_ORDER)]
            ),
        ),
    ) + fallback_plans
    if not ordered_plans:
        ordered_plans = [{"branch": "L2_top_latest", "l2_query": query, "query": query}]

    specs: list[dict[str, Any]] = []
    seen_query_index: dict[str, int] = {}
    for plan in ordered_plans:
        source = str(plan.get("l2_query") or plan.get("query") or query).strip()
        module_compilation = compile_structured_provider_query_from_plan(
            plan,
            "semantic_scholar",
            fallback_query=source,
            prefer_l2=True,
            max_terms=max_terms,
        )
        if is_contract_lexical_calibration_plan(plan):
            # A lexical-calibration query is already deliberately small and
            # contract-bounded. L2 compaction must not delete one of its axes
            # or turn its execution fingerprint into a different plan.
            provider_query = str(module_compilation.get("compiled_query") or source)
        else:
            provider_query = (
                str(module_compilation.get("compiled_query") or "")
                if module_compilation.get("used_modules")
                else compact_l2_provider_query_text(
                    str(module_compilation.get("compiled_query") or source),
                    max_terms=max_terms,
                )
            )
        if not provider_query:
            continue
        branch = str(plan.get("branch") or plan.get("query_branch") or "L2_top_latest").strip()
        evidence_kind = str(plan.get("evidence_kind") or "").strip()
        evidence_path_role = str(plan.get("evidence_path_role") or "").strip()
        binding = {
            "query_branch": branch,
            "evidence_kind": evidence_kind,
            "evidence_path_role": evidence_path_role,
            "source_query": source[:240],
        }
        key = provider_query.lower()
        if key in seen_query_index:
            existing = specs[seen_query_index[key]]
            bindings = existing.setdefault("merged_branch_bindings", [])
            if not any(
                str(item.get("query_branch") or "") == branch
                and str(item.get("evidence_kind") or "") == evidence_kind
                and str(item.get("evidence_path_role") or "") == evidence_path_role
                for item in bindings
                if isinstance(item, dict)
            ):
                bindings.append(binding)
            branches = existing.setdefault("merged_query_branches", [])
            if branch and branch not in branches:
                branches.append(branch)
            kinds = existing.setdefault("merged_evidence_kinds", [])
            if evidence_kind and evidence_kind not in kinds:
                kinds.append(evidence_kind)
            roles = existing.setdefault("merged_evidence_path_roles", [])
            if evidence_path_role and evidence_path_role not in roles:
                roles.append(evidence_path_role)
            continue
        seen_query_index[key] = len(specs)
        provenance_plan = dict(plan)
        if module_compilation.get("used_modules"):
            provenance_plan["query_module_compile"] = module_compilation
            provenance_plan["query_boolean_expression"] = str(
                module_compilation.get("boolean_expression") or ""
            )
        specs.append({
            "query": provider_query,
            "source_query": source,
            "branch": branch,
            "query_branch": branch,
            "evidence_kind": evidence_kind,
            "evidence_path_role": evidence_path_role,
            "query_family": str(plan.get("query_family") or "l2_top_latest_direct_evidence"),
            "plan": provenance_plan,
            "query_module_compile": module_compilation,
            "query_boolean_expression": str(module_compilation.get("boolean_expression") or ""),
            "merged_branch_bindings": [binding],
            "merged_query_branches": [branch] if branch else [],
            "merged_evidence_kinds": [evidence_kind] if evidence_kind else [],
            "merged_evidence_path_roles": [evidence_path_role] if evidence_path_role else [],
        })
        if len(specs) >= effective_max_specs:
            break
    if not specs and not all_plans_blocked:
        specs.append({
            "query": compact_l2_provider_query_text(query, max_terms=max_terms),
            "source_query": query,
            "branch": "L2_top_latest",
            "query_branch": "L2_top_latest",
            "evidence_kind": "",
            "evidence_path_role": "",
            "query_family": "l2_top_latest_fallback",
            "plan": {},
            "merged_branch_bindings": [
                {
                    "query_branch": "L2_top_latest",
                    "evidence_kind": "",
                    "evidence_path_role": "",
                    "source_query": query[:240],
                }
            ],
            "merged_query_branches": ["L2_top_latest"],
            "merged_evidence_kinds": [],
            "merged_evidence_path_roles": [],
        })
    return specs


def fetch_openalex_l2_top_latest_batch(
    query: str,
    *,
    l2_quota: int,
    search_id: str = "",
    query_plan: list[dict[str, Any]] | None = None,
    anchor_contract: dict[str, Any] | None = None,
    discipline_taxonomy: dict[str, Any] | None = None,
    v3_variant_execution: bool = False,
) -> list[dict[str, Any]]:
    """Fetch one bounded, causal OpenAlex pool for the shared L2 layer.

    OpenAlex remains the broad-coverage source, but L2 needs a small topical
    pool that can be assessed alongside Semantic Scholar rather than a hundred
    review-heavy records from each theory/experiment branch.
    """
    try:
        from ._openalex import search_openalex_works
        from ._discipline_taxonomy import compile_provider_discipline_filter
    except ImportError:
        from _openalex import search_openalex_works
        from _discipline_taxonomy import compile_provider_discipline_filter
    current_v3_plans, rejected_legacy_plans, non_contract_plans = partition_retrieval_plans_v3(
        query_plan
    )
    contract_rejection_blocks = _legacy_plan_contract_rejection_blocks(
        "openalex",
        rejected_legacy_plans,
        request_kind="L2_top_latest",
    )
    if current_v3_plans and not v3_variant_execution:
        blocks: list[dict[str, Any]] = []
        for plan in current_v3_plans:
            event_context = _v3_variant_event_context(plan)
            variants = materialize_query_variants_v3("openalex", plan)
            event_context["provider_request_kind"] = "L2_top_latest"
            log_event(
                "SCIENCE",
                "v3_query_variant_plan_compiled",
                provider="openalex",
                variant_count=len(variants),
                **event_context,
            )
            blocks.extend(dispatch_query_variant_sequence_v3(
                "openalex",
                variants,
                lambda variant_query, _variant: fetch_openalex_l2_top_latest_batch(
                    variant_query,
                    l2_quota=l2_quota,
                    search_id=search_id,
                    query_plan=[{**plan, "query": variant_query, "l2_query": variant_query}],
                    anchor_contract=anchor_contract,
                    discipline_taxonomy=discipline_taxonomy,
                    v3_variant_execution=True,
                ),
                event_context=event_context,
            ))
        return [*contract_rejection_blocks, *blocks]
    if rejected_legacy_plans:
        if not non_contract_plans:
            return contract_rejection_blocks
        query_plan = non_contract_plans
    discipline_filter = compile_provider_discipline_filter("openalex", discipline_taxonomy)
    specs = compile_l2_provider_query_specs(
        query,
        query_plan,
        max_specs=max(2, SCIENCE_STRATIFIED_MAX_BRANCHES_PER_LAYER),
    )
    if not specs:
        return [
            {
                "provider": "openalex",
                "query": query,
                "status": "skipped",
                "results": [],
                "query_branch": "L2_top_latest",
                "provider_batch_job_id": f"{search_id}:L2_top_latest_openalex" if search_id else "openalex_l2_query_plan_blocked",
                "provider_batch_request_kind": "l2_top_latest",
                "skipped_provider_reason": "all_l2_query_plan_branches_blocked",
                "discipline_filter_audit": discipline_filter,
            }
        ]
    semantic_limit = semantic_scholar_l2_top_latest_retrieval_limit(l2_quota)
    limit = max(
        1,
        min(int(semantic_limit), int(SCIENCE_OPENALEX_L2_TOP_LATEST_MAX_RESULTS)),
    )
    parent_job_id = f"{search_id}:L2_top_latest_openalex" if search_id else f"openalex_l2_{abs(hash(specs[0]['query']))}"
    log_event(
        "SCIENCE",
        "openalex_l2_provider_batch_started",
        job_id=parent_job_id,
        request_count=len(specs),
        l2_quota=int(l2_quota),
        limit=limit,
        semantic_scholar_equivalent_limit=semantic_limit,
        openalex_l2_max_results=int(SCIENCE_OPENALEX_L2_TOP_LATEST_MAX_RESULTS),
        query_family="causal_topic_primary_by_evidence_path",
        queries=[spec["query"][:180] for spec in specs],
        branches=[spec.get("query_branch", "") for spec in specs],
    )
    blocks: list[dict[str, Any]] = []
    for request_index, spec in enumerate(specs, start=1):
        provider_query = str(spec.get("query") or "")
        spec_plan = spec.get("plan") if isinstance(spec.get("plan"), dict) else {}
        branch_anchor_contract = branch_anchor_contract_for_query_plan(
            anchor_contract,
            spec_plan,
        )
        openalex_options: dict[str, Any] = {
            "max_results": limit,
            "per_page": limit,
        }
        if discipline_filter.get("applied"):
            openalex_options["filters"] = str(discipline_filter.get("filter") or "")
        raw_block = dispatch_compiled_provider_query(
            "openalex",
            provider_query,
            lambda compiled_query: search_openalex_works(compiled_query, **openalex_options),
            anchor_contract=branch_anchor_contract,
        )
        block = dict(raw_block) if isinstance(raw_block, dict) else {
            "provider": "openalex",
            "status": "error",
            "error": "openalex_invalid_provider_response",
            "results": [],
        }
        block = attach_query_plan_provenance(block, spec.get("plan") if isinstance(spec.get("plan"), dict) else {})
        if branch_anchor_contract:
            block["branch_required_semantic_anchor_group"] = list(
                branch_anchor_contract.get("branch_required_semantic_anchor_group") or []
            )[:16]
        block["query_branch"] = str(spec.get("query_branch") or "")
        merged_branches = [
            str(value or "")
            for value in (spec.get("merged_query_branches") or [])
            if str(value or "")
        ]
        merged_kinds = [
            str(value or "")
            for value in (spec.get("merged_evidence_kinds") or [])
            if str(value or "")
        ]
        merged_roles = [
            str(value or "")
            for value in (spec.get("merged_evidence_path_roles") or [])
            if str(value or "")
        ]
        if merged_branches:
            block["matched_query_branches"] = merged_branches
            block["merged_query_branches"] = merged_branches
        if merged_kinds:
            block["matched_evidence_kinds"] = merged_kinds
        if merged_roles:
            block["matched_evidence_path_roles"] = merged_roles
        block["provider_batch_job_id"] = parent_job_id
        block["provider_batch_request_kind"] = "l2_top_latest"
        block["provider_batch_query_family"] = "causal_topic_primary_by_evidence_path"
        block["provider_batch_request_index"] = request_index
        block["provider_batch_request_count"] = len(specs)
        block["retrieval_strategy"] = "openalex_l2_causal_topic"
        block["discipline_filter_audit"] = discipline_filter
        block["l2_query_branch_binding"] = {
            "query_branch": str(spec.get("query_branch") or ""),
            "evidence_kind": str(spec.get("evidence_kind") or ""),
            "evidence_path_role": str(spec.get("evidence_path_role") or ""),
            "source_query": str(spec.get("source_query") or "")[:240],
            "merged_branch_bindings": [
                dict(item)
                for item in (spec.get("merged_branch_bindings") or [])
                if isinstance(item, dict)
            ],
        }
        results = block.get("results") if isinstance(block.get("results"), list) else []
        completion = {
            "job_id": parent_job_id,
            "request_kind": "l2_top_latest",
            "query_family": "causal_topic_primary_by_evidence_path",
            "request_index": request_index,
            "query_branch": str(spec.get("query_branch") or ""),
            "evidence_kind": str(spec.get("evidence_kind") or ""),
            "evidence_path_role": str(spec.get("evidence_path_role") or ""),
            "query": provider_query[:180],
            "limit": limit,
            "merged_branches": merged_branches,
            "status": str(block.get("status") or "unknown"),
            "result_count": len(results),
        }
        if error := str(block.get("error") or "")[:200]:
            completion["provider_error"] = error
        log_event("SCIENCE", "openalex_l2_provider_batch_complete", **completion)
        blocks.append(block)
    return blocks


def fetch_openalex_stratified_batch(
    query_plan: list[dict[str, Any]],
    *,
    search_id: str = "",
    anchor_contract: dict[str, Any] | None = None,
    discipline_taxonomy: dict[str, Any] | None = None,
    v3_variant_execution: bool = False,
) -> list[dict[str, Any]]:
    """Fetch OpenAlex once per semantic query branch for all peer-reviewed layers."""
    try:
        from ._openalex import search_openalex_discovery_batch
        from ._discipline_taxonomy import compile_provider_discipline_filter
    except ImportError:
        from _openalex import search_openalex_discovery_batch
        from _discipline_taxonomy import compile_provider_discipline_filter
    current_v3_plans, rejected_legacy_plans, non_contract_plans = partition_retrieval_plans_v3(
        query_plan
    )
    contract_rejection_blocks = _legacy_plan_contract_rejection_blocks(
        "openalex",
        rejected_legacy_plans,
        request_kind="L4_regular",
    )
    if current_v3_plans and not v3_variant_execution:
        blocks: list[dict[str, Any]] = []
        for plan in current_v3_plans:
            variants = materialize_query_variants_v3("openalex", plan)
            event_context = _v3_variant_event_context(plan)
            log_event(
                "SCIENCE",
                "v3_query_variant_plan_compiled",
                provider="openalex",
                variant_count=len(variants),
                **event_context,
            )
            blocks.extend(dispatch_query_variant_sequence_v3(
                "openalex",
                variants,
                lambda variant_query, _variant: fetch_openalex_stratified_batch(
                    [{**plan, "query": variant_query}],
                    search_id=search_id,
                    anchor_contract=anchor_contract,
                    discipline_taxonomy=discipline_taxonomy,
                    v3_variant_execution=True,
                ),
                event_context=event_context,
            ))
        return [*contract_rejection_blocks, *blocks]
    if rejected_legacy_plans:
        if not non_contract_plans:
            return contract_rejection_blocks
        query_plan = non_contract_plans
    discipline_filter = compile_provider_discipline_filter("openalex", discipline_taxonomy)
    prepared_plan: list[dict[str, Any]] = []
    invalid_blocks: list[dict[str, Any]] = []
    dispatch_audits: list[tuple[dict[str, Any], list[dict[str, Any]], list[str]]] = []
    dispatch_audit_by_branch: dict[str, tuple[dict[str, Any], list[dict[str, Any]], list[str]]] = {}
    for plan in query_plan:
        if not isinstance(plan, dict):
            continue
        branch = str(plan.get("branch") or "primary")
        if not _query_plan_dispatch_allowed(plan):
            invalid_blocks.append(
                {
                    "provider": "openalex",
                    "query": str(plan.get("query") or ""),
                    "status": "skipped",
                    "results": [],
                    "query_branch": branch,
                    "skipped_provider_reason": str(
                        plan.get("query_execution_blocked_reason")
                        or "query_plan_dispatch_blocked"
                    ),
                    "query_contamination_audit": (
                        dict(plan.get("query_contamination_audit"))
                        if isinstance(plan.get("query_contamination_audit"), dict)
                        else {}
                    ),
                    "discipline_filter_audit": discipline_filter,
                }
            )
            continue
        branch_anchor_contract = branch_anchor_contract_for_query_plan(
            anchor_contract,
            plan,
        )
        if v3_variant_execution:
            # The outer V3 dispatcher already compiled and verified this exact
            # provider expression. Re-lowering it here can delete mandatory
            # anchor tokens and turn a valid V3 work item into a false local
            # contract rejection before OpenAlex is contacted.
            dispatch_source_query = str(plan.get("query") or "").strip()
            compiled_query = dispatch_source_query
            compilation = {
                "schema_version": "prevalidated_v3_provider_dispatch_v1",
                "provider": "openalex",
                "source_query": dispatch_source_query,
                "compiled_query": compiled_query,
                "provider_compiled_query": compiled_query,
                "valid": bool(compiled_query),
                "submission_allowed": bool(compiled_query),
                "failure_kind": (
                    "query_plan_contract_error" if not compiled_query else ""
                ),
                "dispatch_mode": "PREVALIDATED_V3_QUERY_VARIANT",
            }
            revisions: list[dict[str, Any]] = []
            attempted_queries = [dispatch_source_query] if dispatch_source_query else []
            module_compilation: dict[str, Any] = {}
        else:
            module_compilation = compile_structured_provider_query_from_plan(
                plan,
                "openalex",
                fallback_query=str(plan.get("query") or ""),
                max_terms=10,
            )
            dispatch_source_query = str(
                module_compilation.get("compiled_query")
                if module_compilation.get("used_modules")
                else module_compilation.get("compiled_query")
                or plan.get("query")
                or ""
            )
            if module_compilation.get("used_modules"):
                log_event(
                    "SCIENCE",
                    "structured_query_module_compile",
                    provider="openalex",
                    query_branch=str(plan.get("branch") or "primary"),
                    source_query=str(module_compilation.get("source_query") or "")[:260],
                    compiled_query=str(module_compilation.get("compiled_query") or "")[:260],
                    compile_mode=str(module_compilation.get("compile_mode") or ""),
                    module_counts=dict(module_compilation.get("module_counts") or {}),
                    query_requires_declared_input=bool(
                        module_compilation.get("query_requires_declared_input")
                    ),
                    causal_input_terms=list(
                        (
                            (module_compilation.get("query_modules") or {}).get("causal_input")
                            if isinstance(module_compilation.get("query_modules"), dict)
                            else []
                        )
                        or []
                    )[:16],
                    provider_not_exclusion_terms=list(
                        module_compilation.get("provider_not_exclusion_terms") or []
                    )[:16],
                    boolean_expression=str(module_compilation.get("boolean_expression") or "")[:320],
                )
            compiled_query, compilation, revisions, attempted_queries = prepare_provider_query_for_dispatch(
                "openalex",
                dispatch_source_query,
                anchor_contract=branch_anchor_contract,
            )
        if not compiled_query:
            invalid_blocks.append(
                {
                    "provider": "openalex",
                    "query": str(compilation.get("compiled_query") or plan.get("query") or ""),
                    "status": str(compilation.get("failure_kind") or "provider_query_compilation_error"),
                    "error": "Provider query compilation rejected this request before network submission.",
                    "results": [],
                    "submitted_to_provider": False,
                    "failure_stage": "provider_query_compilation",
                    "failure_kind": str(compilation.get("failure_kind") or "provider_query_compilation_error"),
                    "query_branch": branch,
                    "query_compilation": compilation,
                    "query_revisions": revisions,
                    "attempted_queries": attempted_queries,
                    "discipline_filter_audit": discipline_filter,
                    "branch_required_semantic_anchor_group": list(
                        (branch_anchor_contract or {}).get("branch_required_semantic_anchor_group") or []
                    )[:16],
                }
            )
            continue
        prepared = dict(plan)
        source_query_text = str(plan.get("query") or "")
        if compiled_query != source_query_text:
            prepared["source_query"] = source_query_text
            prepared["query"] = compiled_query
        if module_compilation.get("used_modules"):
            prepared["source_query"] = source_query_text
            prepared["query"] = compiled_query
            prepared["query_module_compile"] = module_compilation
        if module_compilation.get("used_modules") and module_compilation.get("boolean_expression"):
            prepared["query_boolean_expression"] = str(module_compilation.get("boolean_expression") or "")
        if branch_anchor_contract:
            prepared["branch_required_semantic_anchor_group"] = list(
                branch_anchor_contract.get("branch_required_semantic_anchor_group") or []
            )[:16]
        prepared_plan.append(prepared)
        audit = (compilation, revisions, attempted_queries)
        dispatch_audits.append(audit)
        dispatch_audit_by_branch[branch] = audit

    if prepared_plan and discipline_filter.get("applied"):
        blocks = search_openalex_discovery_batch(
            prepared_plan,
            filters=str(discipline_filter.get("filter") or ""),
            discipline_filter_audit=discipline_filter,
        )
    else:
        blocks = search_openalex_discovery_batch(prepared_plan) if prepared_plan else []
    if len(blocks) > len(dispatch_audits) and dispatch_audits:
        log_event(
            "SCIENCE",
            "openalex_paginated_batch_provenance_reconciled",
            search_id=search_id,
            query_branch_count=len(dispatch_audit_by_branch),
            block_count=len(blocks),
            reason="OpenAlex broad discovery may return multiple cursor pages per evidence-path branch; provenance is bound by query_branch instead of block index.",
        )
    for index, block in enumerate(blocks, start=1):
        if v3_variant_execution:
            # These blocks came from the network batch just invoked above.
            # V3 outcome classification requires this fact before it runs.
            block.setdefault("submitted_to_provider", True)
            block["provider_dispatch_mode"] = "PREVALIDATED_V3_QUERY_VARIANT"
        block["provider_batch_job_id"] = search_id or f"openalex_discovery_{index}"
        block["provider_batch_request_index"] = index
        block["provider_batch_request_count"] = len(blocks)
        branch = str(block.get("query_branch") or "primary")
        fallback_index = min(max(index - 1, 0), max(len(dispatch_audits) - 1, 0))
        fallback_audit = dispatch_audits[fallback_index] if dispatch_audits else ({}, [], [])
        compilation, revisions, attempted_queries = dispatch_audit_by_branch.get(branch, fallback_audit)
        block["query_compilation"] = compilation
        block["query_revisions"] = revisions
        block["attempted_queries"] = attempted_queries
        block["discipline_filter_audit"] = dict(block.get("discipline_filter_audit") or discipline_filter)
    return attach_query_plan_provenance_to_blocks(
        blocks + invalid_blocks,
        prepared_plan or query_plan,
    )


def fetch_sciencedirect_stratified_batch(
    query_plan: list[dict[str, Any]],
    *,
    max_results: int,
    search_id: str = "",
    anchor_contract: dict[str, Any] | None = None,
    discipline_taxonomy: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Fetch one ScienceDirect metadata pool per semantic query branch.

    This mirrors OpenAlex's broad-pool behavior rather than issuing one
    request for every target layer.  L1 remains absent, and every returned
    publisher URL stays subject to the existing OA/full-text pipeline.
    """
    try:
        from ._sciencedirect import search_sciencedirect
        from ._discipline_taxonomy import compile_provider_discipline_filter
    except ImportError:
        from _sciencedirect import search_sciencedirect
        from _discipline_taxonomy import compile_provider_discipline_filter
    discipline_filter = compile_provider_discipline_filter("sciencedirect", discipline_taxonomy)
    per_branch_limit = max(
        12,
        min(int(SCIENCE_MAX_METADATA_RESULTS_PER_EVIDENCE_PATH), int(max_results)),
    )
    blocks: list[dict[str, Any]] = []
    for request_index, plan in enumerate(query_plan, start=1):
        if not isinstance(plan, dict):
            continue
        source_query = str(plan.get("query") or "")
        branch = str(plan.get("branch") or "primary")
        if not _query_plan_dispatch_allowed(plan):
            block = {
                "provider": "sciencedirect",
                "query": source_query,
                "status": "skipped",
                "results": [],
                "query_branch": branch,
                "skipped_provider_reason": str(
                    plan.get("query_execution_blocked_reason")
                    or "query_plan_dispatch_blocked"
                ),
                "query_contamination_audit": (
                    dict(plan.get("query_contamination_audit"))
                    if isinstance(plan.get("query_contamination_audit"), dict)
                    else {}
                ),
                "discipline_filter_audit": discipline_filter,
                "fulltext_entitlement": "unverified_metadata_only",
            }
            blocks.append(attach_query_plan_provenance(block, plan))
            continue
        branch_anchor_contract = branch_anchor_contract_for_query_plan(
            anchor_contract,
            plan,
        )
        compiled_query, compilation, revisions, attempted_queries = prepare_provider_query_for_dispatch(
            "sciencedirect",
            source_query,
            anchor_contract=branch_anchor_contract,
        )
        if not compiled_query:
            block = {
                "provider": "sciencedirect",
                "query": str(compilation.get("compiled_query") or source_query),
                "status": str(compilation.get("failure_kind") or "provider_query_compilation_error"),
                "error": "Provider query compilation rejected this request before network submission.",
                "results": [],
                "submitted_to_provider": False,
                "failure_stage": "provider_query_compilation",
                "failure_kind": str(compilation.get("failure_kind") or "provider_query_compilation_error"),
            }
        else:
            block = search_sciencedirect(compiled_query, max_results=per_branch_limit)
        block["query_branch"] = branch
        if branch_anchor_contract:
            block["branch_required_semantic_anchor_group"] = list(
                branch_anchor_contract.get("branch_required_semantic_anchor_group") or []
            )[:16]
        block["retrieval_strategy"] = "sciencedirect_broad_metadata_discovery"
        block["provider_batch_job_id"] = search_id or f"sciencedirect_discovery_{request_index}"
        block["provider_batch_request_kind"] = "broad_metadata_discovery"
        block["provider_batch_request_index"] = request_index
        block["provider_batch_request_count"] = len(query_plan)
        block["query_compilation"] = compilation
        block["query_revisions"] = revisions
        block["attempted_queries"] = attempted_queries
        block["discipline_filter_audit"] = discipline_filter
        block["fulltext_entitlement"] = "unverified_metadata_only"
        blocks.append(block)
        completion: dict[str, Any] = {
            "job_id": block["provider_batch_job_id"],
            "request_kind": block["provider_batch_request_kind"],
            "query_branch": branch,
            "query": str(block.get("query") or source_query)[:180],
            "limit": per_branch_limit,
            "status": str(block.get("status") or "unknown"),
            "result_count": len(block.get("results") or []),
        }
        if error := str(block.get("error") or "")[:200]:
            completion["provider_error"] = error
        log_event("SCIENCE", "sciencedirect_provider_batch_complete", **completion)
    return attach_query_plan_provenance_to_blocks(blocks, query_plan)


def search_foundational_context_v3(
    foundation_context_contract: dict[str, Any],
    *,
    project_id: str = "",
    project_discipline_taxonomy: Mapping[str, Any] | None = None,
    exclude_candidate_keys: list[str] | set[str] | tuple[str, ...] | None = None,
    sub_hypothesis_id: str = "",
    query_branch: str = "",
    plan_revision: str = "",
    research_question_task_id: str = "",
    evidence_slot: str = "",
    query_fingerprint: str = "",
    groupchat_id: str = "",
    run_id: str = "",
    retrieval_wave_id: str = "",
    research_question_contract_id: str = "",
    research_question_contract_hash: str = "",
    query_branch_id: str = "",
    query_branch_role: str = "",
) -> dict[str, Any]:
    """Retrieve a bounded V2 foundational-context candidate set.

    This is deliberately separate from the historic mechanism-bridge lane.
    It only consumes the declared V2 object/construct/regime anchors and
    creates rationale candidates; no result is promoted to L1 until a later
    V2 source-bound admission process explicitly accepts it.
    """

    try:
        from ._project import save_search
        from ._openalex import search_openalex_works
        from ._discipline_taxonomy import compile_provider_discipline_filter, resolve_discipline_taxonomy
        from ._literature_retrieval_foundation import create_retrieval_run
        from ._utils import new_id
    except ImportError:
        from _project import save_search
        from _openalex import search_openalex_works
        from _discipline_taxonomy import compile_provider_discipline_filter, resolve_discipline_taxonomy
        from _literature_retrieval_foundation import create_retrieval_run
        from _utils import new_id

    context = foundation_context_contract if isinstance(foundation_context_contract, dict) else {}
    object_anchors = [str(item).strip() for item in context.get("research_object_anchors", []) if str(item).strip()]
    construct_anchors = [str(item).strip() for item in context.get("target_construct_anchors", []) if str(item).strip()]
    condition_anchors = [str(item).strip() for item in context.get("condition_or_regime_anchors", []) if str(item).strip()]
    candidates_target = max(1, min(4, int(context.get("candidate_target") or 2)))
    max_attempts = max(candidates_target, min(12, int(context.get("maximum_import_attempts") or 6)))
    resolved_sub_hypothesis_id = str(sub_hypothesis_id or context.get("sub_hypothesis_id") or "").strip()
    resolved_task_id = str(research_question_task_id or "").strip()
    resolved_evidence_slot = str(evidence_slot or "foundational_context").strip()
    branch = str(query_branch or f"{resolved_sub_hypothesis_id or 'subhypothesis'}:foundational_context").strip()
    search_id = new_id("search")
    foundation_kind_terms = str(
        context.get("foundation_kind") or "CANONICAL_THEORY_OR_MEASUREMENT_BASIS"
    ).replace("_", " ").lower()
    provider_query = " ".join(
        dict.fromkeys(
            [
                *object_anchors[:1],
                *construct_anchors[:1],
                foundation_kind_terms,
            ]
        )
    )
    status = "FOUNDATIONAL_CONTEXT_NOT_APPLICABLE"
    reason = str(context.get("not_applicable_reason") or "")
    raw_results: list[dict[str, Any]] = []
    provider_block: dict[str, Any] = {
        "provider": "openalex",
        "query": provider_query,
        "query_branch": branch,
        "status": "not_run",
        "results": [],
    }
    if str(context.get("status") or "") == "FOUNDATIONAL_CONTEXT_RETRIEVAL_REQUIRED" and object_anchors and construct_anchors:
        persisted_taxonomy = project_discipline_taxonomy if isinstance(project_discipline_taxonomy, Mapping) else {}
        if (
            persisted_taxonomy.get("schema_version") == "natural_science_discipline_taxonomy_v1"
            and isinstance(persisted_taxonomy.get("provider_filters"), Mapping)
        ):
            discipline_taxonomy = deepcopy(dict(persisted_taxonomy))
            taxonomy_source = "project_persisted"
        else:
            discipline_taxonomy = resolve_discipline_taxonomy(" ".join([*object_anchors, *construct_anchors]))
            taxonomy_source = "declared_v2_context"
        discipline_filter = compile_provider_discipline_filter("openalex", discipline_taxonomy)
        provider_block = search_openalex_works(
            provider_query,
            max_results=max_attempts,
            per_page=max_attempts,
            filters=str(discipline_filter.get("filter") or "") if discipline_filter.get("applied") else "",
        )
        provider_block = dict(provider_block) if isinstance(provider_block, dict) else provider_block
        provider_block["query_branch"] = branch
        provider_block["retrieval_strategy"] = "v3_foundational_context"
        provider_block["discipline_filter_audit"] = discipline_filter
        provider_block["taxonomy_source"] = taxonomy_source
        raw_results = [dict(item) for item in provider_block.get("results", []) if isinstance(item, dict)]
        status = "FOUNDATIONAL_CONTEXT_CANDIDATES_RETRIEVED" if raw_results else "FOUNDATIONAL_CONTEXT_SHORTAGE"
        reason = (
            "V2 foundational-context candidates require source-bound context admission."
            if raw_results else "No V2 foundational-context candidates were returned by the bounded provider request."
        )
    else:
        discipline_taxonomy = dict(project_discipline_taxonomy or {})
        discipline_filter = {}

    excluded_keys = {str(item).strip() for item in (exclude_candidate_keys or []) if str(item).strip()}
    results: list[dict[str, Any]] = []
    excluded_count = 0
    for item in rank_literature_results(provider_query, raw_results):
        candidate_key = literature_result_unique_key(item)
        if candidate_key and candidate_key in excluded_keys:
            excluded_count += 1
            continue
        candidate = dict(item)
        candidate["result_index"] = len(results)
        candidate["search_id"] = search_id
        candidate["query_branch"] = branch
        candidate["foundation_candidate_layer"] = "L1_milestone"
        candidate["foundation_context_status"] = "PENDING_V3_CONTEXT_ADMISSION"
        candidate["research_role"] = "FOUNDATIONAL_CONTEXT"
        candidate["stratified_label"] = "candidate V3 foundational context pending source-bound admission"
        candidate["_why_selected"] = "candidate_for_v3_foundational_context_admission"
        results.append(candidate)
        if len(results) >= candidates_target:
            break

    provider_attempts = [{
        "provider": provider_block.get("provider"),
        "status": provider_block.get("status"),
        "query": provider_block.get("query"),
        "result_count": len(provider_block.get("results") or []),
        "error": provider_block.get("error", ""),
    }]
    retrieval_run = create_retrieval_run(
        search_id=search_id,
        query=provider_query,
        source_query=provider_query,
        providers=["openalex"],
        provider_attempts=provider_attempts,
        discipline_taxonomy=discipline_taxonomy,
        strategy="v3_foundational_context",
    )
    search_record = {
        "search_id": search_id,
        "query": provider_query,
        "source_query": provider_query,
        "providers": ["openalex"],
        "requested_providers": ["openalex"],
        "createdAt": time.time(),
        "strategy": "v3_foundational_context",
        "sub_hypothesis_id": resolved_sub_hypothesis_id,
        "retrieval_scope": {
            "kind": "subhypothesis_foundational_context",
            "project_id": str(project_id or "").strip(),
            "sub_hypothesis_id": resolved_sub_hypothesis_id,
            "alignment_contract_hash": str(context.get("contract_revision") or plan_revision or "").strip(),
            "plan_revision": str(plan_revision or "").strip(),
            "direct_evidence_eligible": False,
        },
        "research_question_task_provenance": {
            "groupchat_id": str(groupchat_id or context.get("groupchat_id") or ""),
            "run_id": str(run_id or context.get("run_id") or ""),
            "retrieval_wave_id": str(retrieval_wave_id or context.get("retrieval_wave_id") or ""),
            "sub_hypothesis_id": resolved_sub_hypothesis_id,
            "research_question_contract_id": str(
                research_question_contract_id
                or context.get("research_question_contract_id")
                or ""
            ),
            "research_question_contract_hash": str(
                research_question_contract_hash
                or context.get("research_question_contract_hash")
                or context.get("contract_revision")
                or plan_revision
                or ""
            ),
            "research_question_task_id": resolved_task_id,
            "evidence_slot": resolved_evidence_slot,
            "query_branch_id": str(query_branch_id or branch),
            "query_branch_role": str(
                query_branch_role or "FOUNDATIONAL_CONTEXT"
            ),
            "plan_revision": str(plan_revision or "").strip(),
            "query_mode": "FOUNDATIONAL_CONTEXT",
            "query_branch": branch,
            "semantic_fingerprint": str(query_fingerprint or "").strip(),
            "query_fingerprint": str(query_fingerprint or "").strip(),
        },
        "query_branch": branch,
        "plan_revision": str(plan_revision or "").strip(),
        "discipline_taxonomy": discipline_taxonomy,
        "foundation_context_contract": dict(context),
        "provider_query_materialization": {
            "schema_version": "foundational_context_query_materialization_v3",
            "policy": "bounded_object_construct_foundation_kind",
            "retained_anchor_groups": [
                group
                for group, values in (
                    ("research_object", object_anchors[:1]),
                    ("target_construct", construct_anchors[:1]),
                    ("foundation_kind", [foundation_kind_terms]),
                )
                if values
            ],
            "dropped_context_groups": [
                "condition_or_regime"
                for _ in [None]
                if condition_anchors
            ],
            "provider_terms": [
                *object_anchors[:1],
                *construct_anchors[:1],
                foundation_kind_terms,
            ],
        },
        "foundation_retrieval": {
            "layer": "L1_milestone",
            "status": status,
            "candidate_count": len(results),
            "candidate_target": candidates_target,
            "reason": reason,
            "l1_admitted_count": 0,
            "direct_primary_evidence_eligible": False,
        },
        "incoming_excluded_candidate_key_count": len(excluded_keys),
        "cross_task_duplicates_excluded": excluded_count,
        "total_results": len(results),
        "results": results,
        "provider_blocks": [provider_block],
        "retrieval_run": retrieval_run,
    }
    save_search(search_record)
    log_event(
        "SCIENCE",
        "v3_foundational_context_retrieval_complete",
        project_id=str(project_id or ""),
        search_id=search_id,
        sub_hypothesis_id=resolved_sub_hypothesis_id,
        query_branch=branch,
        research_question_task_id=resolved_task_id,
        evidence_slot=resolved_evidence_slot,
        plan_revision=str(plan_revision or "").strip(),
        semantic_fingerprint=str(query_fingerprint or "").strip(),
        status=status,
        candidates=len(results),
        candidate_target=candidates_target,
        cross_task_duplicates_excluded=excluded_count,
        L1_from_broad_pool=0,
        L1_admitted=0,
    )
    return {
        "search_id": search_id,
        "query": provider_query,
        "status": status,
        "reason": reason,
        "candidate_count": len(results),
        "results": results,
        "provider_blocks": [provider_block],
        "foundation_retrieval": search_record["foundation_retrieval"],
        "research_question_task_provenance": search_record[
            "research_question_task_provenance"
        ],
        "incoming_excluded_candidate_key_count": len(excluded_keys),
        "cross_task_duplicates_excluded": excluded_count,
    }


def search_foundational_mechanism_bridges(
    foundation_contract: dict[str, Any],
    *,
    max_results: int | None = None,
    project_id: str = "",
    include_search_record: bool = False,
) -> dict[str, Any]:
    """Run the single-request L1 historical mechanism-foundation retrieval.

    L1 is intentionally not a third variation of the ordinary base/review
    search.  One direct OpenAlex discovery request is persisted per
    sub-hypothesis, with no pagination, review query, citation-edge expansion,
    or fallback to L4.  Selection is performed by the causal bridge gate in
    the pipeline rather than by the normal relevance/recency ordering.
    """
    try:
        from ._project import save_search
        from ._research_alignment import build_foundational_mechanism_query
        from ._utils import new_id
        from ._literature_retrieval_foundation import create_retrieval_run
        from ._discipline_taxonomy import compile_provider_discipline_filter, resolve_discipline_taxonomy
    except ImportError:
        from _project import save_search
        from _research_alignment import build_foundational_mechanism_query
        from _utils import new_id
        from _literature_retrieval_foundation import create_retrieval_run
        from _discipline_taxonomy import compile_provider_discipline_filter, resolve_discipline_taxonomy
    search_id = new_id("search")
    query = build_foundational_mechanism_query(foundation_contract)
    discipline_taxonomy = resolve_discipline_taxonomy(query)
    discipline_filter = compile_provider_discipline_filter("openalex", discipline_taxonomy)
    selected_limit = max(
        1,
        min(
            int(SCIENCE_OPENALEX_FOUNDATION_MAX_RESULTS),
            int(max_results if max_results is not None else SCIENCE_FOUNDATION_MAX_RESULTS),
        ),
    )
    branch = f"{str(foundation_contract.get('sub_hypothesis_id') or 'subhypothesis')}:foundational_mechanism_bridge"
    provider_blocks: list[dict[str, Any]] = []
    foundation_anchor_contract = {
        "required_anchor_groups": [
            list(foundation_contract.get("input_anchors") or []),
            list(foundation_contract.get("mediator_anchors") or []),
            list(foundation_contract.get("outcome_anchors") or []),
        ],
    }
    status = "historical_foundation_missing"
    reason = "No dedicated historical mechanism query has yielded a qualifying foundation paper."
    results: list[dict[str, Any]] = []
    if not foundation_contract.get("valid") or not query:
        reason = "The sub-hypothesis lacks a concrete input, mediator, or outcome anchor for historical-foundation retrieval."
    else:
        try:
            from ._openalex import search_openalex_works
        except ImportError:
            from _openalex import search_openalex_works
        openalex_options: dict[str, Any] = {
            "max_results": selected_limit,
            "per_page": selected_limit,
        }
        if discipline_filter.get("applied"):
            openalex_options["filters"] = str(discipline_filter.get("filter") or "")
        block = dispatch_compiled_provider_query(
            "openalex",
            query,
            lambda provider_query: search_openalex_works(provider_query, **openalex_options),
            anchor_contract=foundation_anchor_contract,
        )
        block["query_branch"] = branch
        block["retrieval_strategy"] = "dedicated_historical_mechanism_foundation"
        block["discipline_filter_audit"] = discipline_filter
        block["pagination_enabled"] = bool(SCIENCE_FOUNDATION_PAGINATION_ENABLED)
        block["provider_batch_job_id"] = f"{search_id}:foundational_mechanism_bridge"
        block["provider_batch_retry_limit"] = 2
        block["provider_batch_retries_used"] = 0
        provider_blocks.append(block)
        raw_results = block.get("results") if isinstance(block.get("results"), list) else []
        # This computes the cached quality record once.  The resulting normal
        # relevance score is diagnostic only; bridge selection below never
        # reads its recency component.
        results = rank_literature_results(query, [dict(item) for item in raw_results if isinstance(item, dict)])
        for index, item in enumerate(results):
            item["result_index"] = index
            item["search_id"] = search_id
            item["query_branch"] = branch
            # Retrieval only creates candidates for the L1 lane.  The actual
            # layer is written later, and only to the single candidate that
            # passes the foundational bridge gate.
            item.pop("stratified_layer", None)
            item["foundation_candidate_layer"] = "L1_milestone"
            item["foundation_gate_status"] = "PENDING_BRIDGE_ASSESSMENT"
            item["stratified_label"] = "candidate historical mechanism foundation pending bridge assessment"
            item["research_role"] = "FOUNDATIONAL_MECHANISM_BRIDGE"
            item["_why_selected"] = "candidate_for_dedicated_foundational_mechanism_bridge_gate"
        if results:
            status = "candidates_retrieved_pending_bridge_gate"
            reason = "Dedicated historical mechanism candidates were retrieved; only a non-review causal bridge may occupy L1."
        elif str(block.get("status") or "") not in {"", "ok"}:
            reason = "Historical foundation retrieval did not complete: " + str(block.get("error") or block.get("status") or "provider failure")[:240]

    provider_attempts = [
        {
            "provider": block.get("provider"),
            "status": block.get("status"),
            "query": block.get("query"),
            "attempted_queries": block.get("attempted_queries", []),
            "result_count": len(block.get("results") or []),
            "error": block.get("error", ""),
        }
        for block in provider_blocks
        if isinstance(block, dict)
    ]
    retrieval_run = create_retrieval_run(
        search_id=search_id,
        query=query,
        source_query=query,
        providers=["openalex"],
        anchor_contract=foundation_anchor_contract,
        provider_attempts=provider_attempts,
        query_compilations=[
            block.get("query_compilation", {})
            for block in provider_blocks
            if isinstance(block, dict)
        ],
        candidate_fusion={
            "method": "none_dedicated_l1_foundation_query",
            "global_rrf_applied": False,
            "reason": "Dedicated L1 bridge retrieval keeps one causal mechanism query and does not perform candidate fusion.",
        },
        discipline_taxonomy=discipline_taxonomy,
        strategy="dedicated_historical_mechanism_foundation",
    )
    resolved_project_id = str(project_id or foundation_contract.get("project_id") or "").strip()
    foundation_scope = {
        "kind": "foundational_mechanism_bridge",
        "project_id": resolved_project_id,
        "sub_hypothesis_id": str(foundation_contract.get("sub_hypothesis_id") or "").strip(),
        "alignment_contract_hash": str(foundation_contract.get("alignment_contract_hash") or "").strip(),
        "direct_evidence_eligible": False,
    }
    search_record = {
        "search_id": search_id,
        "query": query,
        "source_query": query,
        "providers": ["openalex"],
        "requested_providers": ["openalex"],
        "createdAt": time.time(),
        "strategy": "dedicated_historical_mechanism_foundation",
        "sub_hypothesis_id": str(foundation_contract.get("sub_hypothesis_id") or ""),
        "retrieval_scope": foundation_scope,
        "foundational_mechanism_contract": dict(foundation_contract),
        "discipline_taxonomy": discipline_taxonomy,
        "pagination_enabled": bool(SCIENCE_FOUNDATION_PAGINATION_ENABLED),
        "graph_expansion_enabled": False,
        "total_results": len(results),
        "results": results,
        "provider_blocks": provider_blocks,
        "retrieval_run": retrieval_run,
        "foundation_retrieval": {
            "layer": "L1_milestone",
            "status": status,
            "candidate_count": len(results),
            "query_attempts": [query] if query else [],
            "reason": reason,
            "l4_backfill_allowed": False,
            "review_eligible": False,
            "max_selected": int(SCIENCE_FOUNDATION_MAX_SELECTED_PER_SUBHYPOTHESIS),
        },
    }
    save_search(search_record)
    log_event(
        "SCIENCE",
        "foundational_mechanism_retrieval_complete",
        search_id=search_id,
        sub_hypothesis_id=foundation_contract.get("sub_hypothesis_id"),
        status=status,
        candidates=len(results),
        query=query[:220],
        max_results=selected_limit,
        provider="openalex",
        retry_limit=2,
        pagination_enabled=SCIENCE_FOUNDATION_PAGINATION_ENABLED,
        foundation_contract_passed=int(bool(foundation_contract.get("valid"))),
        foundation_contract_failed=int(not bool(foundation_contract.get("valid"))),
        L1_from_dedicated_foundation_branch=0,
        L1_from_broad_pool=0,
        candidate_gate_status="PENDING_BRIDGE_ASSESSMENT" if results else "NO_CANDIDATES",
    )
    response = {
        "search_id": search_id,
        "query": query,
        "status": status,
        "reason": reason,
        "candidate_count": len(results),
        "results": results,
        "provider_blocks": provider_blocks,
        "foundation_retrieval": search_record["foundation_retrieval"],
    }
    if include_search_record:
        # The batched pipeline can hand the exact persisted artifact to the
        # preparation stage without another search-store read.  Other callers
        # keep the existing compact response shape.
        response["_search_record"] = search_record
    return response


def peer_reviewed_local_stratified_layer(
    item: dict[str, Any],
    *,
    direct_evidence_mode: bool = False,
) -> str:
    """Assign one broad peer-reviewed candidate to L0, L2, or L4.

    L1 is intentionally not a local metadata class.  Citation count,
    normalized impact, or an old publication year can describe influence,
    but none establishes that a paper is the historical causal bridge
    required by the current sub-hypothesis.  The only L1 writer is the
    dedicated foundational-mechanism workflow.
    """
    if direct_evidence_mode:
        # Direct theory or direct empirical evidence may be older than the
        # ordinary L4 recency window.  It remains distinct from L1: it must be
        # non-review, target-aligned primary evidence, not a rationale-only
        # historical bridge.
        return (
            "L4_regular"
            if stratified_candidate_matches(
                "L4_regular",
                item,
                allow_historical_direct_evidence=True,
            )
            else ""
        )
    if stratified_candidate_matches("L0_review", item):
        return "L0_review"
    if stratified_candidate_matches("L2_top_latest", item):
        return "L2_top_latest"
    if stratified_candidate_matches("L4_regular", item):
        return "L4_regular"
    return ""


def semantic_scholar_local_stratified_layer(item: dict[str, Any]) -> str:
    """Backward-compatible SS-specific alias for the shared classifier."""
    return peer_reviewed_local_stratified_layer(item)


def candidate_query_branches(item: dict[str, Any]) -> list[str]:
    """Return every semantic query branch that matched this paper."""

    raw = item.get("matched_query_branches")
    values = raw if isinstance(raw, (list, tuple, set)) else [raw]
    branches: list[str] = []
    for value in (*values, item.get("primary_query_branch"), item.get("query_branch")):
        branch = str(value or "").strip()
        if branch and branch != "unassigned_branch" and branch not in branches:
            branches.append(branch)
    return branches or ["unassigned_branch"]


def candidate_primary_query_branch(item: dict[str, Any]) -> str:
    for value in (item.get("primary_query_branch"), item.get("query_branch")):
        branch = str(value or "").strip()
        if branch and branch != "unassigned_branch":
            return branch
    return ""


def candidate_branch_assignment_source(item: dict[str, Any]) -> str:
    """Explain whether a branch is explicit or absent from a provider batch."""

    source = str(item.get("branch_assignment_source") or "").strip()
    if source and source != "provider_batch_unassigned":
        return source
    if candidate_primary_query_branch(item):
        return "candidate_query_branch"
    raw = item.get("matched_query_branches")
    values = raw if isinstance(raw, (list, tuple, set)) else [raw]
    if any(str(value or "").strip() not in {"", "unassigned_branch"} for value in values):
        return "matched_query_branches"
    return "provider_batch_unassigned"


def candidate_branch_raw_hit_count(item: dict[str, Any], branch: str) -> int:
    counts = item.get("branch_raw_hit_counts") if isinstance(item.get("branch_raw_hit_counts"), dict) else {}
    try:
        return max(0, int(counts.get(branch) or 0))
    except (TypeError, ValueError):
        return 0


def candidate_is_experimental_after_genre_gate(item: dict[str, Any]) -> bool:
    """Apply the domain-neutral genre gate used for experimental evidence."""

    genre, _responsibility = candidate_design_and_causal_role(item)
    return bool(
        genre.get("direct_experimental_evidence")
        and not genre.get("is_review")
    )


def candidate_design_and_causal_role(item: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Classify a candidate on the independent design and causal-role axes."""

    try:
        from ._research_alignment import classify_causal_role
    except ImportError:
        from _research_alignment import classify_causal_role
    genre = item.get("paper_genre") if isinstance(item.get("paper_genre"), dict) else {}
    if not genre:
        classification = (
            item.get("paper_classification")
            if isinstance(item.get("paper_classification"), dict)
            else {}
        )
        evidence_genre = str(classification.get("evidence_genre") or "unknown")
        genre = {
            "schema_version": "paper_genre_assessment_v2",
            "genre": evidence_genre,
            "evidence_genre": evidence_genre,
            "research_design": str(classification.get("research_design") or "unknown"),
            "publication_form": str(classification.get("publication_form") or "unknown"),
            "is_review": evidence_genre in {"systematic_review", "narrative_review", "contextual_synthesis"},
            "status": str(classification.get("status") or "CLASSIFICATION_PENDING"),
            "reason_codes": list(classification.get("reason_codes") or ["PAPER_CLASSIFICATION_REQUIRED"]),
            "direct_experimental_evidence": evidence_genre in {"primary_empirical", "primary_measurement", "primary_validation"},
        }
    return genre, classify_causal_role(item, paper_genre=genre)


def dedicated_foundational_bridge_candidate(item: dict[str, Any]) -> bool:
    """Return whether the strict foundation workflow admitted this L1 item."""

    assessment = (
        item.get("foundational_bridge_assessment")
        if isinstance(item.get("foundational_bridge_assessment"), dict)
        else {}
    )
    return bool(
        assessment.get("bridge_eligible")
        and str(item.get("research_role") or "").strip().upper()
        == "FOUNDATIONAL_MECHANISM_BRIDGE"
        and str(item.get("evidence_kind") or "").strip().lower()
        == "foundational_mechanism_bridge"
    )


def legacy_broad_milestone_citation_match(item: dict[str, Any]) -> bool:
    """Diagnose the retired citation-only broad-pool L1 heuristic.

    This predicate is deliberately diagnostic-only.  A true result here says
    that the old first-match classifier *would* have captured the paper as
    L1; it never grants the paper an L1 assignment.
    """

    try:
        from ._utils import numeric_value
    except ImportError:
        from _utils import numeric_value
    return bool(
        is_within_stratified_year_window("L1_milestone", item)
        and not is_review_like_paper(item)
        and numeric_value(item.get("citation_count")) >= milestone_citation_threshold(item)
        and not is_low_quality_literature_result(item)
    )


def candidate_citation_percentile(item: dict[str, Any]) -> float | None:
    """Return a normalized 0..1 OpenAlex citation percentile when available."""

    payload = item.get("papergraph_input") if isinstance(item.get("papergraph_input"), dict) else {}
    metrics = item.get("citation_metrics") if isinstance(item.get("citation_metrics"), dict) else {}
    if not metrics and isinstance(payload.get("citation_metrics"), dict):
        metrics = payload["citation_metrics"]
    openalex_metrics = metrics.get("openalex") if isinstance(metrics.get("openalex"), dict) else {}
    normalized = (
        openalex_metrics.get("citation_normalized_percentile")
        if isinstance(openalex_metrics.get("citation_normalized_percentile"), dict)
        else {}
    )
    try:
        value = float(normalized.get("value"))
    except (TypeError, ValueError):
        value = -1.0
    if 0.0 <= value <= 1.0:
        return round(value, 6)
    year_percentile = (
        openalex_metrics.get("cited_by_percentile_year")
        if isinstance(openalex_metrics.get("cited_by_percentile_year"), dict)
        else {}
    )
    for key in ("max", "min"):
        try:
            value = float(year_percentile.get(key))
        except (TypeError, ValueError):
            continue
        if 0.0 <= value <= 100.0:
            return round(value / 100.0, 6)
    return None


def citation_count_quantiles(candidates: list[dict[str, Any]]) -> dict[str, float]:
    """Return compact citation-count diagnostics without a numeric dependency."""

    try:
        from ._utils import numeric_value
    except ImportError:
        from _utils import numeric_value
    values = sorted(max(0.0, numeric_value(item.get("citation_count"))) for item in candidates)
    if not values:
        return {}

    def quantile(fraction: float) -> float:
        if len(values) == 1:
            return round(values[0], 3)
        position = (len(values) - 1) * fraction
        lower = int(position)
        upper = min(len(values) - 1, lower + 1)
        weight = position - lower
        return round(values[lower] * (1.0 - weight) + values[upper] * weight, 3)

    return {
        "min": quantile(0.0),
        "p25": quantile(0.25),
        "p50": quantile(0.5),
        "p75": quantile(0.75),
        "p90": quantile(0.9),
        "max": quantile(1.0),
    }


def broad_pool_stratification_diagnostic(
    item: dict[str, Any],
    assigned_layer: str,
    *,
    direct_evidence_mode: bool = False,
) -> dict[str, Any]:
    """Explain how the retired L1 first-match rule would have behaved."""

    try:
        from ._literature_scoring import infer_research_field
        from ._utils import numeric_value
    except ImportError:
        from _literature_scoring import infer_research_field
        from _utils import numeric_value
    legacy_l1 = legacy_broad_milestone_citation_match(item)
    l0 = stratified_candidate_matches("L0_review", item)
    l2_assessment = l2_candidate_qualification(item)
    l2 = bool(l2_assessment.get("eligible"))
    l4 = stratified_candidate_matches(
        "L4_regular",
        item,
        allow_historical_direct_evidence=direct_evidence_mode,
    )
    research_field = infer_research_field(item)
    matches = [
        layer
        for layer, matched in (
            ("L0_review", l0),
            ("legacy_L1_citation_heuristic", legacy_l1),
            ("L2_top_latest", l2),
            ("L4_regular", l4),
        )
        if matched
    ]
    return {
        "title": str(item.get("title") or "untitled")[:200],
        "year": item.get("year"),
        "citation_count": numeric_value(item.get("citation_count")),
        "inferred_field": research_field,
        "milestone_threshold": round(milestone_citation_threshold(item), 3),
        "milestone_threshold_role": "retired_broad_L1_heuristic_diagnostic_only",
        "citation_percentile": candidate_citation_percentile(item),
        "query_branch": candidate_primary_query_branch(item)
        or candidate_query_branches(item)[0],
        "foundation_contract_status": "NOT_APPLICABLE_BROAD_POOL",
        "assigned_layer": assigned_layer or "unassigned",
        "other_layers_also_matched": matches,
        "legacy_L1_match": legacy_l1,
        "would_match_L2_but_captured_by_L1": bool(legacy_l1 and l2),
        "would_match_L4_but_captured_by_L1": bool(legacy_l1 and l4),
        "recent_candidates_captured_by_L1": bool(
            legacy_l1 and l2_assessment.get("recent")
        ),
    }


def stratify_peer_reviewed_candidates_locally(
    candidates: list[dict[str, Any]],
    *,
    provider: str,
    direct_evidence_mode: bool = False,
) -> dict[str, list[dict[str, Any]]]:
    """Partition a broad provider pool into L0/L2/L4, never L1."""
    stage_started = time.perf_counter()
    layers = {name: [] for name in ("L0_review", "L1_milestone", "L2_top_latest", "L3_preprint", "L4_regular")}
    branch_composition: dict[str, dict[str, Any]] = {}
    branch_assignment_source_counts: dict[str, int] = {}
    diagnostic_records: list[dict[str, Any]] = []
    unassigned = 0
    for candidate in candidates:
        item = dict(candidate)
        review_assessment = assess_review_like_paper(item)
        review_like = bool(review_assessment["is_review_like"])
        layer = peer_reviewed_local_stratified_layer(
            item,
            direct_evidence_mode=direct_evidence_mode,
        )
        diagnostic = broad_pool_stratification_diagnostic(
            item,
            layer,
            direct_evidence_mode=direct_evidence_mode,
        )
        diagnostic_records.append(diagnostic)
        branches = candidate_query_branches(item)
        primary_branch = candidate_primary_query_branch(item)
        branch_assignment_source = candidate_branch_assignment_source(item)
        branch_assignment_source_counts[branch_assignment_source] = (
            branch_assignment_source_counts.get(branch_assignment_source, 0) + 1
        )
        genre, responsibility = candidate_design_and_causal_role(item)
        experimental_genre_eligible = bool(
            genre.get("direct_experimental_evidence")
            and not genre.get("is_review")
        )
        research_design = str(
            responsibility.get("research_design")
            or genre.get("research_design")
            or "unclassified"
        )
        causal_role = str(responsibility.get("causal_role") or "unclassified")
        supports_mechanism_discovery = causal_role in {
            "association",
            "mechanism_discovery",
            "causal_identification",
            "causal_validation",
        }
        for branch in branches:
            composition = branch_composition.setdefault(
                branch,
                {
                    # ``raw`` remains for backward-compatible log consumers;
                    # the new fields remove its historical ambiguity.
                    "raw": 0,
                    "provider_raw": 0,
                    "deduplicated_unique": 0,
                    "cross_lane_overlap": 0,
                    "primary_branch_assigned": 0,
                    "unassigned_provider_batch": 0,
                    "experimental_eligible_after_genre_gate": 0,
                    "mechanism_discovery_eligible_after_design_gate": 0,
                    "causal_validation_eligible_after_design_gate": 0,
                    "causal_identification_eligible_after_design_gate": 0,
                    "observational_multiomics_candidates": 0,
                    "review_like": 0,
                    "review_like_metadata_confirmed": 0,
                    "review_like_title_confirmed": 0,
                    "review_like_abstract_confirmed": 0,
                    "formal_primary": 0,
                    "formal_nonreview_nonpreprint": 0,
                    "L0_review": 0,
                    "L1_milestone": 0,
                    "L2_top_latest": 0,
                    "L4_regular": 0,
                    "unassigned": 0,
                    "legacy_L1_matches": 0,
                    "L1_from_dedicated_foundation_branch": 0,
                    "L1_from_broad_pool": 0,
                    "would_match_L2_but_captured_by_L1": 0,
                    "would_match_L4_but_captured_by_L1": 0,
                    "recent_candidates_captured_by_L1": 0,
                    "foundation_contract_passed": 0,
                    "foundation_contract_failed": 0,
                },
            )
            raw_hits = candidate_branch_raw_hit_count(item, branch) or 1
            composition["provider_raw"] += raw_hits
            composition["deduplicated_unique"] += 1
            composition["raw"] = composition["deduplicated_unique"]
            composition["cross_lane_overlap"] += int(len(branches) > 1)
            composition["primary_branch_assigned"] += int(bool(primary_branch) and primary_branch == branch)
            composition["unassigned_provider_batch"] += int(
                branch_assignment_source == "provider_batch_unassigned"
            )
            if "experimental_evidence" in branch.lower():
                composition["experimental_eligible_after_genre_gate"] += int(experimental_genre_eligible)
            if "mechanism_discovery" in branch.lower():
                composition["mechanism_discovery_eligible_after_design_gate"] += int(
                    supports_mechanism_discovery
                )
            if "causal_validation" in branch.lower():
                composition["causal_validation_eligible_after_design_gate"] += int(
                    causal_role == "causal_validation"
                )
                composition["causal_identification_eligible_after_design_gate"] += int(
                    causal_role == "causal_identification"
                )
            composition["observational_multiomics_candidates"] += int(
                research_design in {
                    "observational_multiomics",
                    "observational_human_multiomics",
                }
            )
            composition["review_like"] += int(review_like)
            if review_assessment["reason"] == "publication_type":
                composition["review_like_metadata_confirmed"] += int(review_like)
            elif review_assessment["reason"] == "title":
                composition["review_like_title_confirmed"] += int(review_like)
            elif review_assessment["reason"] == "abstract_opening":
                composition["review_like_abstract_confirmed"] += int(review_like)
            formal_nonreview = int(not review_like and not is_preprint_literature_result(item))
            # Retain ``formal_primary`` for log consumers, but expose the
            # precise meaning: genre/design gates, not this metadata shortcut,
            # decide whether a paper is actually primary evidence.
            composition["formal_primary"] += formal_nonreview
            composition["formal_nonreview_nonpreprint"] += formal_nonreview
            composition["legacy_L1_matches"] += int(diagnostic["legacy_L1_match"])
            composition["would_match_L2_but_captured_by_L1"] += int(
                diagnostic["would_match_L2_but_captured_by_L1"]
            )
            composition["would_match_L4_but_captured_by_L1"] += int(
                diagnostic["would_match_L4_but_captured_by_L1"]
            )
            composition["recent_candidates_captured_by_L1"] += int(
                diagnostic["recent_candidates_captured_by_L1"]
            )
            if not layer:
                composition["unassigned"] += 1

        if not layer:
            unassigned += 1
            continue
        item["provider_local_layer"] = layer
        item["branch_assignment_source"] = branch_assignment_source
        item["provider_local_stratification"] = {
            "provider": provider,
            "year": item.get("year"),
            "venue": item.get("venue"),
            "citation_count": item.get("citation_count"),
            "publication_types": item.get("publication_types", []),
            "review_like": review_like,
            "review_like_reason": review_assessment["reason"],
            "review_like_signals": review_assessment["signals"],
            "branch_assignment_source": branch_assignment_source,
            "direct_evidence_mode": bool(direct_evidence_mode),
            "relevance_score": item.get("relevance_score"),
            "publication_quality_score": item.get("publication_quality_score"),
            "legacy_L1_diagnostic": {
                key: diagnostic[key]
                for key in (
                    "legacy_L1_match",
                    "would_match_L2_but_captured_by_L1",
                    "would_match_L4_but_captured_by_L1",
                    "recent_candidates_captured_by_L1",
                )
            },
        }
        if provider == "semantic_scholar":
            item["semantic_scholar_local_layer"] = layer
            item["semantic_scholar_local_stratification"] = dict(item["provider_local_stratification"])
        layers[layer].append(item)
        for branch in branches:
            composition = branch_composition[branch]
            if layer in composition:
                composition[layer] += 1
    legacy_l1_matches = sum(int(item["legacy_L1_match"]) for item in diagnostic_records)
    would_have_captured_l2 = sum(
        int(item["would_match_L2_but_captured_by_L1"])
        for item in diagnostic_records
    )
    would_have_captured_l4 = sum(
        int(item["would_match_L4_but_captured_by_L1"])
        for item in diagnostic_records
    )
    recent_captured = sum(
        int(item["recent_candidates_captured_by_L1"])
        for item in diagnostic_records
    )
    field_thresholds: dict[str, dict[str, Any]] = {}
    for item in diagnostic_records:
        research_field = str(item["inferred_field"] or "general")
        report = field_thresholds.setdefault(
            research_field,
            {
                "milestone_threshold": item["milestone_threshold"],
                "candidate_count": 0,
                "legacy_L1_matches": 0,
            },
        )
        report["candidate_count"] += 1
        report["legacy_L1_matches"] += int(item["legacy_L1_match"])
    log_event(
        "SCIENCE",
        f"{provider}_candidates_locally_stratified",
        total_candidates=len(candidates),
        L0_review=len(layers["L0_review"]),
        L1_milestone=len(layers["L1_milestone"]),
        L2_top_latest=len(layers["L2_top_latest"]),
        L4_regular=len(layers["L4_regular"]),
        unassigned=unassigned,
        branch_assignment_source_counts=branch_assignment_source_counts,
        L1_policy="dedicated_foundational_mechanism_workflow_only",
        L1_from_dedicated_foundation_branch=0,
        L1_from_broad_pool=0,
        legacy_L1_matches=legacy_l1_matches,
        would_match_L2_but_captured_by_L1=would_have_captured_l2,
        would_match_L4_but_captured_by_L1=would_have_captured_l4,
        recent_candidates_captured_by_L1=recent_captured,
        foundation_contract_passed=0,
        foundation_contract_failed=0,
        foundation_contract_status="NOT_APPLICABLE_BROAD_POOL",
        L1_threshold_by_field=field_thresholds,
        L1_threshold_role="retired_broad_L1_heuristic_diagnostic_only",
        citation_quantiles=citation_count_quantiles(candidates),
        elapsed_ms=round((time.perf_counter() - stage_started) * 1000.0, 3),
    )
    diagnostic_samples = sorted(
        diagnostic_records,
        key=lambda item: (
            not bool(item["legacy_L1_match"]),
            -float(item["citation_count"] or 0.0),
            str(item["title"]).lower(),
        ),
    )[:5]
    if diagnostic_samples:
        log_event(
            "SCIENCE",
            "provider_local_stratification_diagnostic_sample",
            provider=provider,
            sample_count=len(diagnostic_samples),
            L1_policy="dedicated_foundational_mechanism_workflow_only",
            samples=diagnostic_samples,
        )
    for branch, composition in branch_composition.items():
        log_event(
            "SCIENCE",
            "provider_candidate_branch_composition",
            provider=provider,
            branch=branch,
            **composition,
        )
    return layers


def stratify_semantic_scholar_candidates_locally(
    candidates: list[dict[str, Any]],
    *,
    direct_evidence_mode: bool = False,
) -> dict[str, list[dict[str, Any]]]:
    return stratify_peer_reviewed_candidates_locally(
        candidates,
        provider="semantic_scholar",
        direct_evidence_mode=direct_evidence_mode,
    )


def stratify_pubmed_candidates_locally(
    candidates: list[dict[str, Any]],
    *,
    direct_evidence_mode: bool = False,
) -> dict[str, list[dict[str, Any]]]:
    return stratify_peer_reviewed_candidates_locally(
        candidates,
        provider="pubmed",
        direct_evidence_mode=direct_evidence_mode,
    )


def fetch_regular_backfill_blocks(
    query: str,
    providers: list[str],
    needed: int,
    query_plan: list[dict[str, str]] | None = None,
    domain: str = "",
    preprint_layers: set[str] | None = None,
    preprint_required_anchor_groups: list[list[str]] | None = None,
    single_paper_serial: bool = False,
    anchor_contract: dict[str, Any] | None = None,
    discipline_taxonomy: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    # L4 backfill is peer-reviewed literature only.  Keep this explicit even
    # though the shared dispatcher independently normalizes preprint layers.
    _ = preprint_layers
    layer = {"layer": "L4_regular", "quota": max(needed, 1), "query_suffix": ""}
    return fetch_stratified_layer_blocks(
        query,
        providers,
        layer,
        query_plan=query_plan,
        domain=domain,
        preprint_layers=set(),
        preprint_required_anchor_groups=preprint_required_anchor_groups,
        single_paper_serial=single_paper_serial,
        anchor_contract=anchor_contract,
        discipline_taxonomy=discipline_taxonomy,
    )

def build_knowledge_pyramid(
    query: str,
    results: list[dict[str, Any]],
    strata_reports: list[dict[str, Any]],
) -> dict[str, Any]:
    root = choose_pyramid_review_root(results)
    layer_nodes: dict[str, list[dict[str, Any]]] = {}
    for item in results:
        layer = str(item.get("stratified_layer") or "unlayered")
        layer_nodes.setdefault(layer, []).append(summarize_literature_result(item))

    edges: list[dict[str, Any]] = []
    root_index = root.get("result_index") if root else None
    if root_index is not None:
        for item in results:
            child_index = item.get("result_index")
            if child_index == root_index:
                continue
            edges.append(
                {
                    "source": root_index,
                    "target": child_index,
                    "relation": pyramid_relation_for_layer(str(item.get("stratified_layer") or "")),
                    "evidence": "stratified retrieval layer",
                    "confidence": 0.65,
                }
            )

    return {
        "query": query,
        "root_result_index": root_index,
        "root_node": summarize_literature_result(root) if root else None,
        "root_policy": (
            "Prefer a high-impact review as the knowledge-map root. Only a clearly superior "
            "Nature/Science/Cell/PNAS-level paper should override it as the seed."
        ),
        "layers": {
            "L0_review": layer_nodes.get("L0_review", []),
            "L1A_milestone": layer_nodes.get("L1_milestone", []),
            "L1B_top_latest": layer_nodes.get("L2_top_latest", []),
            "L1C_preprint": layer_nodes.get("L3_preprint", []),
            "L2_regular": layer_nodes.get("L4_regular", []),
        },
        "edges": edges,
        "strata": strata_reports,
    }

def choose_pyramid_review_root(results: list[dict[str, Any]]) -> dict[str, Any] | None:
    reviews = [
        item
        for item in results
        if str(item.get("stratified_layer") or "") == "L0_review" or is_review_like_paper(item)
    ]
    candidates = reviews or results
    if not candidates:
        return None
    return max(candidates, key=pyramid_root_score)

def pyramid_root_score(item: dict[str, Any]) -> float:
    try:
        from ._literature_scoring import literature_impact_score
    except ImportError:
        from _literature_scoring import literature_impact_score
    score = float(item.get("relevance_score") or 0.0)
    score += 0.35 if is_review_like_paper(item) else 0.0
    score += 0.2 * float(item.get("publication_quality_score") or 0.0)
    score += 0.15 * literature_impact_score(item)
    if is_top_venue_result(item):
        score += 0.08
    return round(score, 4)

def pyramid_relation_for_layer(layer: str) -> str:
    return {
        "L1_milestone": "field foundation / canonical evidence",
        "L2_top_latest": "frontier extension from field map",
        "L3_preprint": "emerging preprint signal",
        "L4_regular": "supplemental validation detail",
    }.get(layer, "pyramid child")

def literature_publication_year(item: dict[str, Any]) -> int | None:
    match = re.search(r"\b(19|20)\d{2}\b", str(item.get("year") or ""))
    return int(match.group(0)) if match else None


def stratified_layer_year_window(layer: str) -> tuple[int | None, int]:
    regular_minimum = min(SCIENCE_REGULAR_PAPER_YEAR_MIN, SCIENCE_REGULAR_PAPER_YEAR_MAX)
    regular_maximum = max(SCIENCE_REGULAR_PAPER_YEAR_MIN, SCIENCE_REGULAR_PAPER_YEAR_MAX)
    milestone_minimum = min(SCIENCE_MILESTONE_PAPER_YEAR_MIN, SCIENCE_MILESTONE_PAPER_YEAR_MAX)
    milestone_maximum = max(SCIENCE_MILESTONE_PAPER_YEAR_MIN, SCIENCE_MILESTONE_PAPER_YEAR_MAX)
    l2_minimum = min(SCIENCE_L2_TOP_LATEST_YEAR_MIN, regular_maximum)
    if layer == "L1_milestone":
        return milestone_minimum, milestone_maximum
    if layer == "L2_top_latest":
        return max(regular_minimum, l2_minimum), regular_maximum
    if layer in {"L0_review", "L4_regular"}:
        return regular_minimum, regular_maximum
    return None, regular_maximum


def stratified_year_policy(layer: str) -> dict[str, Any]:
    minimum, maximum = stratified_layer_year_window(layer)
    if layer == "L1_milestone":
        purpose = "historical and conceptual foundations"
    elif layer in {"L0_review", "L4_regular"}:
        purpose = "modern review and regular evidence window"
    elif layer == "L2_top_latest":
        purpose = f"top-venue primary evidence from {minimum} onward"
    else:
        purpose = "upper-bound guard; recency rules provide the lower bound"
    return {"min_year": minimum, "max_year": maximum, "purpose": purpose}


def direct_evidence_year_policy() -> dict[str, Any]:
    """Time-neutral policy for a missing direct theory or empirical record.

    The evidence lane remains strict about project/sub-hypothesis alignment,
    primary genre, and non-review status.  It is deliberately not restricted
    to a modern L4 window because a valid direct model or measurement can be
    historically important in any natural-science discipline.
    """
    return {
        "min_year": SCIENCE_MILESTONE_PAPER_YEAR_MIN,
        "max_year": SCIENCE_MILESTONE_PAPER_YEAR_MAX,
        "purpose": "time-neutral direct theory or empirical evidence; not an L1 rationale bridge",
    }


def is_within_stratified_year_window(layer: str, item: dict[str, Any]) -> bool:
    year = literature_publication_year(item)
    minimum, maximum = stratified_layer_year_window(layer)
    if year is None:
        return False
    return (minimum is None or year >= minimum) and year <= maximum


def l2_candidate_qualification(item: dict[str, Any]) -> dict[str, Any]:
    """Explain whether one formal paper can occupy the protected L2 slot."""
    try:
        from ._literature_scoring import venue_evidence_assessment
    except ImportError:
        from _literature_scoring import venue_evidence_assessment
    venue_evidence = item.get("venue_evidence")
    if not isinstance(venue_evidence, dict) or "eligible_for_l2" not in venue_evidence:
        venue_evidence = venue_evidence_assessment(
            item,
            quartile=str(item.get("journal_quartile") or ""),
            flags=list(item.get("quality_flags") or []),
        )
    recent = is_within_stratified_year_window("L2_top_latest", item)
    review_background = is_review_like_paper(item)
    low_quality = is_low_quality_literature_result(item)
    role_assessment = item.get("research_role_assessment")
    if not isinstance(role_assessment, dict):
        role_assessment = {}
    research_role = str(item.get("research_role") or role_assessment.get("role") or "").strip().upper()
    reasons: list[str] = []
    if not recent:
        reasons.append("outside_l2_recency_window")
    if review_background:
        reasons.append("review_background_not_primary_l2_evidence")
    if low_quality:
        reasons.append("low_quality_or_suspicious")
    # L2 is a protected slot for *direct* recent frontier evidence.  A paper
    # from a top publication channel can still be a BOUNDARY, CONTEXT, or
    # mechanism-bridge record for this particular sub-hypothesis.  Do not let
    # channel prestige turn such a record into primary evidence.
    if research_role and research_role != "CORE_DIRECT":
        reasons.append("noncore_research_role_not_primary_l2_evidence")
    if not bool(venue_evidence.get("eligible_for_l2")):
        reasons.append(str(venue_evidence.get("status") or "venue_unverified"))
    return {
        "eligible": not reasons,
        "recent": recent,
        "review_background": review_background,
        "low_quality": low_quality,
        "research_role": research_role,
        "venue_evidence": dict(venue_evidence),
        "reasons": reasons,
    }


def summarize_l2_candidate_qualification(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    """Expose why a dual-provider L2 pool did or did not yield a candidate."""
    reason_counts: dict[str, int] = {}
    venue_status_counts: dict[str, int] = {}
    eligible = 0
    review_background = 0
    recent = 0
    for item in candidates:
        assessment = l2_candidate_qualification(item)
        eligible += int(bool(assessment["eligible"]))
        review_background += int(bool(assessment["review_background"]))
        recent += int(bool(assessment["recent"]))
        venue_status = str((assessment.get("venue_evidence") or {}).get("status") or "venue_unverified")
        venue_status_counts[venue_status] = venue_status_counts.get(venue_status, 0) + 1
        for reason in assessment.get("reasons") or []:
            reason_counts[str(reason)] = reason_counts.get(str(reason), 0) + 1
    return {
        "candidate_count": len(candidates),
        "eligible_count": eligible,
        "recent_count": recent,
        "review_background_count": review_background,
        "venue_status_counts": venue_status_counts,
        "rejection_reason_counts": reason_counts,
    }


def stratified_candidate_matches(
    layer: str,
    item: dict[str, Any],
    *,
    allow_historical_direct_evidence: bool = False,
) -> bool:
    try:
        from ._literature_scoring import is_recent_paper
    except ImportError:
        from _literature_scoring import is_recent_paper
    if is_retracted_literature_result(item):
        return False
    direct_l4 = bool(allow_historical_direct_evidence and layer == "L4_regular")
    if not direct_l4 and not is_within_stratified_year_window(layer, item):
        return False
    if layer == "L0_review":
        return is_review_like_paper(item) and not is_low_quality_literature_result(item)
    if layer == "L1_milestone":
        return dedicated_foundational_bridge_candidate(item)
    if layer == "L2_top_latest":
        return bool(l2_candidate_qualification(item).get("eligible"))
    if layer == "L3_preprint":
        return (
            is_preprint_literature_result(item)
            and is_recent_paper(item, max_age=2)
            and not has_suspicious_literature_flags(item)
        )
    if layer == "L4_regular":
        return (
            not is_preprint_literature_result(item)
            and not is_low_quality_literature_result(item)
            and (not direct_l4 or not is_review_like_paper(item))
        )
    return True

def preprint_publication_status(item: dict[str, Any]) -> str:
    """Classify whether a record is an unpublished preprint or a published work.

    Repository presence alone is not publication status: authors commonly keep
    an arXiv copy after journal publication. Only direct preprint-server
    metadata without a journal/linked-publication signal qualifies for L3.
    """
    try:
        from ._models import PREPRINT_API_PROVIDERS
        from ._utils import normalize_space
    except ImportError:
        from _models import PREPRINT_API_PROVIDERS
        from _utils import normalize_space
    provider = normalize_space(str(item.get("provider") or "")).lower()
    venue = normalize_space(str(item.get("venue") or "")).lower()
    payload = item.get("papergraph_input") if isinstance(item.get("papergraph_input"), dict) else {}
    payload_provider = normalize_space(str(payload.get("provider") or "")).lower()
    payload_venue = normalize_space(str(payload.get("venue") or "")).lower()
    doi = normalize_space(str(item.get("doi") or payload.get("doi") or "")).lower()
    journal_reference = normalize_space(
        str(item.get("journal_reference") or item.get("published_venue") or payload.get("journal_reference") or "")
    ).lower()
    direct_provider = provider if provider in PREPRINT_API_PROVIDERS else payload_provider
    direct_venue = venue if venue in PREPRINT_API_PROVIDERS else payload_venue
    preprint_doi = (
        doi.startswith("10.1101/")
        or doi.startswith("10.26434/")
        or doi.startswith("10.48550/arxiv.")
    )
    formal_venue = next(
        (
            value
            for value in (venue, payload_venue)
            if value and value not in PREPRINT_API_PROVIDERS and "preprint" not in value
        ),
        "",
    )
    if not direct_provider and not direct_venue:
        return "not_preprint"
    if formal_venue or journal_reference:
        return "published"
    # arXiv records expose arxiv:doi when a journal DOI is linked. Conversely,
    # bio/med/ChemRxiv DOI prefixes identify the repository deposition itself.
    if doi and not preprint_doi:
        return "published"
    return "unpublished_preprint"


def is_preprint_literature_result(item: dict[str, Any]) -> bool:
    return preprint_publication_status(item) == "unpublished_preprint"

def has_suspicious_literature_flags(item: dict[str, Any]) -> bool:
    flags = set(item.get("quality_flags") or [])
    return "suspicious_venue_or_publisher" in flags or "journal_quartile_suspicious" in flags

def recover_stratified_layer_candidates(layer: str, raw_candidates: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], str]:
    try:
        from ._literature_scoring import literature_recency_score
        from ._utils import numeric_value
    except ImportError:
        from _literature_scoring import literature_recency_score
        from _utils import numeric_value
    usable = [
        item
        for item in raw_candidates
        if (
            not is_low_quality_literature_result(item)
            and is_within_stratified_year_window(layer, item)
            and (layer != "L1_milestone" or not is_review_like_paper(item))
        )
    ]
    if not usable:
        return [], ""
    if layer == "L1_milestone":
        # A failed foundation contract cannot be repaired by relaxing citation
        # or venue thresholds.  Keep the reserved slot empty and report the
        # dedicated foundation shortage to the caller.
        return (
            [item for item in usable if dedicated_foundational_bridge_candidate(item)],
            "dedicated_foundation_bridge_only",
        )
    if layer == "L2_top_latest":
        recent = [
            item
            for item in usable
            if is_within_stratified_year_window("L2_top_latest", item)
        ]
        topish = [item for item in usable if is_top_venue_result(item)]
        pool = [item for item in recent if is_top_venue_result(item)] or recent or topish or usable
        ranked = sorted(
            pool,
            key=lambda item: (
                -literature_recency_score(item),
                -float(item.get("publication_quality_score") or 0.0),
                -float(item.get("relevance_score") or 0.0),
                -numeric_value(item.get("citation_count")),
            ),
        )
        return ranked[:20], "relaxed_top_latest_recent_or_high_quality_available"
    return [], ""

def assess_review_like_paper(item: dict[str, Any]) -> dict[str, Any]:
    """Classify review evidence from reliable metadata or explicit review language."""
    try:
        from ._utils import normalize_space
    except ImportError:
        from _utils import normalize_space
    title = normalize_space(str(item.get("title") or "")).lower()
    abstract = normalize_space(str(item.get("abstract") or "")).lower()
    publication_types = [
        normalize_space(str(value or "")).lower()
        for value in (item.get("publication_types") or [])
        if normalize_space(str(value or ""))
    ]
    publication_type_text = " ".join(publication_types)
    metadata_pattern = re.compile(
        r"\b(?:systematic\s+review|scoping\s+review|review|meta[ -]?analysis)\b"
    )
    title_patterns = (
        r"\b(?:systematic|scoping|narrative|literature)\s+review\b",
        r"\bmeta[ -]?analysis\b",
        r"\b(?:review|survey|perspective|tutorial|roadmap)\s+of\b",
        r"\ban?\s+(?:overview|perspective|tutorial|roadmap)\b",
        r"\bstate[- ]of[- ]the[- ]art\b",
        r"\brecent advances?\b",
        r"\bprogress in\b",
    )
    abstract_opening = abstract[:600]
    abstract_patterns = (
        r"\b(?:this|the present|our)\s+(?:systematic\s+|scoping\s+)?(?:review|meta[ -]?analysis)\b",
        r"\bwe\s+(?:systematically\s+)?(?:review|synthesi[sz]e)\b",
    )
    primary_design_patterns = (
        r"\brandomi[sz]ed\b",
        r"\b(?:prospective|retrospective)\s+cohort\b",
        r"\bcase[- ]control\b",
        r"\bwe\s+(?:enrolled|recruited|measured|sequenced|randomi[sz]ed)\b",
        r"\bparticipants?\b",
        r"\bn\s*=\s*\d+\b",
    )
    signals: list[str] = []
    reason = ""
    if metadata_pattern.search(publication_type_text):
        signals.append("publication_type")
        reason = "publication_type"
    elif any(re.search(pattern, title) for pattern in title_patterns):
        signals.append("title")
        reason = "title"
    elif any(re.search(pattern, abstract_opening) for pattern in abstract_patterns):
        signals.append("abstract_opening")
        reason = "abstract_opening"
    primary_design_signals = [
        pattern
        for pattern in primary_design_patterns
        if re.search(pattern, abstract)
    ]
    return {
        "is_review_like": bool(reason),
        "reason": reason or "none",
        "signals": signals,
        "primary_design_signals": primary_design_signals,
    }


def is_review_like_paper(item: dict[str, Any]) -> bool:
    return bool(assess_review_like_paper(item)["is_review_like"])

def milestone_citation_threshold(item: dict[str, Any]) -> float:
    try:
        from ._literature_scoring import field_citation_baseline, infer_research_field
    except ImportError:
        from _literature_scoring import field_citation_baseline, infer_research_field
    field = infer_research_field(item)
    return max(30.0, field_citation_baseline(field) * 0.15)

def is_top_venue_result(item: dict[str, Any]) -> bool:
    try:
        from ._literature_scoring import venue_evidence_assessment
    except ImportError:
        from _literature_scoring import venue_evidence_assessment
    evidence = item.get("venue_evidence")
    if not isinstance(evidence, dict) or "eligible_for_l2" not in evidence:
        evidence = venue_evidence_assessment(
            item,
            quartile=str(item.get("journal_quartile") or ""),
            flags=list(item.get("quality_flags") or []),
        )
    return bool(evidence.get("eligible_for_l2"))

def is_low_quality_literature_result(item: dict[str, Any]) -> bool:
    flags = set(item.get("quality_flags") or [])
    if "suspicious_venue_or_publisher" in flags or "journal_quartile_suspicious" in flags:
        return True
    return float(item.get("publication_quality_score") or 0.0) < 0.45


def is_retracted_literature_result(item: dict[str, Any]) -> bool:
    """Hard reject provider records explicitly labelled as retracted articles."""

    title = normalize_space(str(item.get("title") or ""))
    payload = item.get("papergraph_input") if isinstance(item.get("papergraph_input"), dict) else {}
    payload_title = normalize_space(str(payload.get("title") or ""))
    return "RETRACTED ARTICLE" in f"{title} {payload_title}".upper()


def stratified_selection_reason(layer: str, item: dict[str, Any]) -> str:
    try:
        from ._utils import numeric_value, trim_text
    except ImportError:
        from _utils import numeric_value, trim_text
    title = trim_text(str(item.get("title") or ""), 120)
    citations = int(numeric_value(item.get("citation_count")))
    year = str(item.get("year") or "")
    venue = str(item.get("venue") or item.get("provider") or "")
    quality = item.get("publication_quality_score")
    relevance = item.get("relevance_score")
    venue_tier = venue_tier_label(item)
    research_role = str(item.get("research_role") or "").strip().upper()
    evidence_role = research_role or "UNCLASSIFIED"
    if layer == "L0_review":
        return f"Selected as field-map review/survey candidate: {title}; venue={venue}; venue_tier={venue_tier}; citations={citations}; quality={quality}; relevance={relevance}."
    if layer == "L1_milestone":
        return f"Selected as a contract-validated foundational mechanism bridge: {title}; citations={citations}; year={year}; venue={venue}; venue_tier={venue_tier}; quality={quality}."
    if layer == "L2_top_latest":
        return f"Selected as recent direct frontier paper: {title}; role={evidence_role}; year={year}; venue={venue}; venue_tier={venue_tier}; quality={quality}; relevance={relevance}."
    if layer == "L3_preprint":
        return f"Selected as latest preprint/frontier signal: {title}; year={year}; provider={item.get('provider')}; relevance={relevance}."
    return f"Selected as supplemental evidence for the current map: {title}; role={evidence_role}; year={year}; venue={venue}; venue_tier={venue_tier}; quality={quality}; relevance={relevance}."


def venue_tier_label(item: dict[str, Any]) -> str:
    """Return a compact, display-safe publication-channel tier label."""
    value = item.get("venue_tier")
    if isinstance(value, dict):
        return str(value.get("tier") or "VENUE_UNVERIFIED")
    text = str(value or "").strip()
    return text or "VENUE_UNVERIFIED"

def flatten_literature_results(provider_blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    try:
        from ._literature_retrieval_foundation import annotate_candidate_query_provenance
    except ImportError:
        from _literature_retrieval_foundation import annotate_candidate_query_provenance
    flattened: list[dict[str, Any]] = []
    for block in provider_blocks:
        provider = str(block.get("provider", ""))
        if block.get("status") != "ok":
            continue
        for result in block.get("results", []):
            if not isinstance(result, dict):
                continue
            item = dict(result)
            item["provider"] = provider
            if is_retracted_literature_result(item):
                log_event(
                    "SCIENCE",
                    "retracted_literature_result_rejected",
                    provider=provider,
                    title=str(item.get("title") or "")[:240],
                    reason="title_contains_RETRACTED_ARTICLE",
                    blocking=False,
                )
                continue
            if block.get("query_branch"):
                item["query_branch"] = block.get("query_branch")
                item["branch_assignment_source"] = "provider_query_branch"
            elif not item.get("query_branch") and not item.get("primary_query_branch"):
                item["branch_assignment_source"] = "provider_batch_unassigned"
            for field in (
                "matched_query_branches",
                "matched_evidence_kinds",
                "matched_evidence_path_roles",
            ):
                if block.get(field) not in (None, "", [], {}):
                    item[field] = list(block[field]) if isinstance(block[field], tuple) else block[field]
            for field in _QUERY_PLAN_PROVENANCE_FIELDS:
                if block.get(field) not in (None, "", [], {}):
                    item[field] = block.get(field)
            if item.get("evidence_path_role"):
                item["matched_evidence_path_roles"] = [item["evidence_path_role"]]
            if block.get("query"):
                item["retrieval_query"] = block.get("query")
            if isinstance(block.get("query_compilation"), dict):
                item["provider_query_compilation"] = dict(block["query_compilation"])
            if isinstance(block.get("query_revisions"), list):
                item["provider_query_revisions"] = list(block["query_revisions"])
            flattened.append(
                annotate_candidate_query_provenance(
                    item,
                    query_branch=str(block.get("query_branch") or ""),
                    evidence_kind=str(block.get("evidence_kind") or ""),
                    provider=provider,
                    raw_hit_count=1,
                )
            )
    return flattened


def _candidate_paper_fingerprint(item: dict[str, Any]) -> str:
    payload = item.get("papergraph_input") if isinstance(item.get("papergraph_input"), dict) else {}
    material = {
        key: item.get(key)
        for key in (
            "title", "abstract", "venue", "year", "provider", "doi", "url", "open_access_pdf",
            "citation", "citation_count", "influential_citation_count", "reference_count",
            "publication_types", "arxiv_categories", "venue_metadata", "citation_metrics",
        )
    }
    material["payload_arxiv_categories"] = payload.get("arxiv_categories")
    encoded = json.dumps(material, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:24]


def _scoring_context_key(*parts: str) -> str:
    encoded = "\x00".join(normalize_space(str(part or "")).lower() for part in parts).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:24]


def _candidate_score_record(item: dict[str, Any]) -> dict[str, Any]:
    fingerprint = _candidate_paper_fingerprint(item)
    existing = item.get("candidate_score_record")
    if (
        isinstance(existing, dict)
        and existing.get("version") == 1
        and existing.get("paper_fingerprint") == fingerprint
    ):
        record = dict(existing)
        record["domain_assessments"] = dict(existing.get("domain_assessments") or {})
        return record
    return {
        "version": 1,
        "paper_fingerprint": fingerprint,
        "quality": {},
        "ranking_assessments": {},
        "domain_assessments": {},
    }


def _candidate_alignment_memo_paper_key(item: dict[str, Any]) -> str:
    """Stable paper identity for SH-local alignment/admission memoization.

    Candidate objects from L0/L2/L4 can be separate dictionaries even when
    they refer to the same paper.  The score-record fingerprint is too local
    for that case, so this helper prefers canonical provider-independent
    identity and falls back to a normalized title/year key.
    """

    if not isinstance(item, dict):
        return ""
    try:
        key = str(literature_result_unique_key(item) or "").strip()
        if key:
            return key
    except Exception:
        pass
    payload = item.get("papergraph_input") if isinstance(item.get("papergraph_input"), dict) else {}
    for field in (
        "doi",
        "normalized_doi",
        "openalex_id",
        "openalex",
        "semantic_scholar_id",
        "semanticScholarId",
        "corpus_id",
        "corpusId",
        "arxiv_id",
        "pmid",
    ):
        value = str(item.get(field) or payload.get(field) or "").strip().lower()
        if value:
            return f"{field}:{value}"
    title = normalize_space(str(item.get("title") or payload.get("title") or "")).lower()
    year = str(item.get("year") or payload.get("year") or "").strip()
    venue = normalize_space(str(item.get("venue") or payload.get("venue") or "")).lower()
    if title:
        encoded = hashlib.sha256(f"{title}\x00{year}\x00{venue}".encode("utf-8")).hexdigest()[:24]
        return f"title:{encoded}"
    return _candidate_paper_fingerprint(item)


def _alignment_contract_memo_hash(alignment_contract: dict[str, Any] | None) -> str:
    if not isinstance(alignment_contract, dict) or not alignment_contract:
        return "no_contract"
    contract_hash = str(alignment_contract.get("contract_hash") or "").strip()
    if contract_hash:
        return contract_hash
    encoded = json.dumps(
        alignment_contract,
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:24]


def _alignment_requested_kinds_memo_key(kinds: list[str] | tuple[str, ...] | None) -> str:
    normalized = sorted({
        normalize_space(str(kind or "")).lower()
        for kind in (kinds or [])
        if normalize_space(str(kind or ""))
    })
    return "|".join(normalized) if normalized else "unspecified"


def _alignment_admission_memo_key(
    candidate: dict[str, Any],
    alignment_contract: dict[str, Any] | None,
    *,
    requested_evidence_kinds: list[str] | tuple[str, ...] | None = None,
    admission_level: str = "core",
) -> str:
    return "\x1f".join(
        [
            _candidate_alignment_memo_paper_key(candidate),
            _alignment_contract_memo_hash(alignment_contract),
            _alignment_requested_kinds_memo_key(requested_evidence_kinds),
            normalize_space(str(admission_level or "core")).lower() or "core",
        ]
    )


def _coarse_prefilter_memo_key(
    candidate: dict[str, Any],
    alignment_contract: dict[str, Any] | None,
) -> str:
    return "\x1f".join(
        [
            _candidate_alignment_memo_paper_key(candidate),
            _alignment_contract_memo_hash(alignment_contract),
            "coarse_prefilter",
        ]
    )


def _bounded_memo_get(
    memo: dict[str, dict[str, Any]],
    lock: Lock,
    key: str,
) -> dict[str, Any] | None:
    if not key:
        return None
    with lock:
        cached = memo.get(key)
        return dict(cached) if isinstance(cached, dict) else None


def _bounded_memo_put(
    memo: dict[str, dict[str, Any]],
    lock: Lock,
    key: str,
    value: dict[str, Any],
    *,
    max_size: int,
) -> None:
    if not key or not isinstance(value, dict):
        return
    with lock:
        if len(memo) >= max_size:
            # Dict insertion order gives us a cheap FIFO eviction policy.
            for old_key in list(memo.keys())[: max(1, max_size // 10)]:
                memo.pop(old_key, None)
        memo[key] = dict(value)


def _alignment_memo_content_summary(assessment: dict[str, Any]) -> dict[str, Any]:
    """Small, auditable summary of the expensive SH admission result."""

    if not isinstance(assessment, dict):
        return {}
    coarse = (
        assessment.get("coarse_prefilter")
        if isinstance(assessment.get("coarse_prefilter"), dict)
        else {}
    )
    prefulltext = (
        assessment.get("prefulltext_import_assessment")
        if isinstance(assessment.get("prefulltext_import_assessment"), dict)
        else {}
    )
    policy_hits = (
        assessment.get("policy_economic_context_hits")
        or prefulltext.get("policy_economic_context_hits")
        or coarse.get("policy_economic_context_hits")
        or []
    )
    return {
        "coarse_prefilter_passes": coarse.get("passes"),
        "coarse_prefilter_reason_code": coarse.get("reason_code"),
        "object_hits": list(
            assessment.get("strong_object_hits")
            or coarse.get("strong_object_hits")
            or assessment.get("object_hits")
            or []
        )[:12],
        "declared_input_hits": list(
            assessment.get("declared_input_hits")
            or assessment.get("causal_input_hits")
            or coarse.get("declared_input_hits")
            or []
        )[:12],
        "mechanism_outcome_hits": list(
            assessment.get("mechanism_hits")
            or assessment.get("outcome_hits")
            or assessment.get("mechanism_or_endpoint_hits")
            or coarse.get("component_bridge_support_hits")
            or []
        )[:12],
        "comparison_hit": bool(
            assessment.get("comparison_present")
            or assessment.get("comparison_hit")
            or coarse.get("comparison_present")
        ),
        "policy_economic_flag": bool(
            assessment.get("policy_economic_context")
            or prefulltext.get("policy_economic_context")
            or coarse.get("policy_economic_context")
            or policy_hits
        ),
        "policy_economic_hits": list(policy_hits)[:8],
        "admission_scope_precheck": (
            assessment.get("admission_scope")
            or prefulltext.get("admission_scope")
            or assessment.get("admission_tier")
            or ""
        ),
        "layer_eligibility": {
            "core_eligible": bool(assessment.get("core_eligible")),
            "import_eligible": bool(assessment.get("import_eligible")),
            "prefulltext_import_eligible": bool(
                assessment.get("prefulltext_import_eligible")
            ),
            "admission_tier": str(assessment.get("admission_tier") or ""),
        },
    }


def _apply_quality_assessment(item: dict[str, Any], quality: dict[str, Any]) -> None:
    item["publication_quality_score"] = quality["quality_score"]
    item["venue_quality"] = quality["venue_quality"]
    item["journal_quartile"] = quality["journal_quartile"]
    item["journal_metric_source"] = quality["journal_metric_source"]
    item["inferred_field"] = quality["inferred_field"]
    item["quality_flags"] = list(quality["flags"])
    item["quality_criteria"] = list(quality["criteria"])
    item["suspicion_type"] = quality["suspicion_type"]
    item["quality_reason"] = quality["reason"]
    item["venue_evidence"] = dict(quality.get("venue_evidence") or {})
    item["venue_tier"] = dict(quality.get("venue_tier") or {})


def selected_candidate_needs_openalex_venue_enrichment(item: dict[str, Any]) -> bool:
    """Whether a selected formal paper warrants one bounded DOI detail lookup.

    This is intentionally *post-selection*: it must never fan a keyword
    search into repeated metadata queries.  A DOI lookup is useful only when
    a retained formal paper has no OpenAlex source/normalized-impact record;
    preprints and records already carrying that provenance are left alone.
    """
    if not str(item.get("doi") or "").strip():
        return False
    if str(item.get("stratified_layer") or "") not in {"L1_milestone", "L2_top_latest", "L4_regular"}:
        return False
    # Evidence-role classification is the final guard that tells us this is a
    # retained scientific record rather than an unexamined provider hit.
    # Keeping it mandatory also keeps test/dry-run retrieval entirely local
    # unless it explicitly supplies a classified candidate.
    if not str(item.get("research_role") or "").strip():
        return False
    if is_preprint_literature_result(item) or has_suspicious_literature_flags(item):
        return False
    venue_metadata = item.get("venue_metadata") if isinstance(item.get("venue_metadata"), dict) else {}
    citation_metrics = item.get("citation_metrics") if isinstance(item.get("citation_metrics"), dict) else {}
    openalex_metrics = citation_metrics.get("openalex") if isinstance(citation_metrics.get("openalex"), dict) else {}
    has_openalex_source = str(venue_metadata.get("provider") or "").lower() == "openalex"
    has_openalex_metrics = bool(openalex_metrics) or bool(str(item.get("openalex_id") or "").strip())
    if has_openalex_source and has_openalex_metrics:
        return False
    return bool(str(item.get("venue") or "").strip() or item.get("publication_types"))


def _selected_venue_enrichment_priority(item: dict[str, Any]) -> tuple[Any, ...]:
    tier_priority = {
        "TOP_VENUE": 0,
        "STRONG_FORMAL_VENUE": 1,
        "FORMAL_VENUE_UNVERIFIED": 2,
        "VENUE_UNVERIFIED": 3,
    }
    layer_priority = {"L2_top_latest": 0, "L1_milestone": 1, "L4_regular": 2}
    role = str(item.get("research_role") or "").strip().upper()
    role_priority = {
        "CORE_DIRECT": 0,
        "": 1,
        "PENDING": 2,
        "COMPONENT_SUPPORT": 3,
        "BOUNDARY": 4,
    }.get(role, 5)
    return (
        tier_priority.get(venue_tier_label(item), 9),
        layer_priority.get(str(item.get("stratified_layer") or ""), 9),
        role_priority,
        -float(item.get("relevance_score") or 0.0),
        str(item.get("title") or "").lower(),
    )


def _merge_selected_openalex_venue_metadata(
    item: dict[str, Any],
    openalex_result: dict[str, Any],
) -> dict[str, Any]:
    """Merge DOI detail metadata without changing the discovery record's role.

    ``provider`` and all query/sub-hypothesis evidence assessments stay with
    the originating result.  OpenAlex contributes only durable bibliographic
    identifiers, venue metadata, and normalized citation metrics.  Therefore
    a PubMed BOUNDARY paper remains a PubMed BOUNDARY paper after enrichment.
    """
    try:
        from ._literature_scoring import publication_quality_assessment
        from ._utils import numeric_value
    except ImportError:
        from _literature_scoring import publication_quality_assessment
        from _utils import numeric_value

    merged = dict(item)
    incoming_metadata = (
        dict(openalex_result.get("venue_metadata") or {})
        if isinstance(openalex_result.get("venue_metadata"), dict)
        else {}
    )
    if incoming_metadata:
        merged["venue_metadata"] = incoming_metadata
    existing_metrics = dict(merged.get("citation_metrics") or {}) if isinstance(merged.get("citation_metrics"), dict) else {}
    incoming_metrics = (
        dict(openalex_result.get("citation_metrics") or {})
        if isinstance(openalex_result.get("citation_metrics"), dict)
        else {}
    )
    if incoming_metrics.get("openalex"):
        existing_metrics["openalex"] = dict(incoming_metrics["openalex"])
    if existing_metrics:
        merged["citation_metrics"] = existing_metrics
    existing_ids = dict(merged.get("external_ids") or {}) if isinstance(merged.get("external_ids"), dict) else {}
    incoming_ids = dict(openalex_result.get("external_ids") or {}) if isinstance(openalex_result.get("external_ids"), dict) else {}
    for key, value in incoming_ids.items():
        if value:
            existing_ids[str(key)] = value
    if existing_ids:
        merged["external_ids"] = existing_ids
    if openalex_result.get("openalex_id"):
        merged["openalex_id"] = openalex_result["openalex_id"]
    if numeric_value(merged.get("citation_count")) <= 0 and numeric_value(openalex_result.get("citation_count")) > 0:
        merged["citation_count"] = openalex_result.get("citation_count")
    if numeric_value(merged.get("reference_count")) <= 0 and numeric_value(openalex_result.get("reference_count")) > 0:
        merged["reference_count"] = openalex_result.get("reference_count")
    for field_name in ("url", "open_access_pdf", "year"):
        if not str(merged.get(field_name) or "").strip() and openalex_result.get(field_name):
            merged[field_name] = openalex_result[field_name]
    if not str(merged.get("venue") or "").strip() and openalex_result.get("venue"):
        merged["venue"] = openalex_result["venue"]
    existing_types = [str(value) for value in (merged.get("publication_types") or []) if str(value)]
    for value in openalex_result.get("publication_types") or []:
        value = str(value)
        if value and value not in existing_types:
            existing_types.append(value)
    if existing_types:
        merged["publication_types"] = existing_types
    providers = [str(value) for value in (merged.get("discovery_providers") or []) if str(value)]
    for provider in (merged.get("provider"), "openalex"):
        normalized_provider = str(provider or "").strip()
        if normalized_provider and normalized_provider not in providers:
            providers.append(normalized_provider)
    merged["discovery_providers"] = providers
    merged["venue_metadata_enrichment"] = {
        "provider": "openalex",
        "mode": "bounded_selected_doi_lookup",
        "preserved_discovery_provider": str(item.get("provider") or ""),
    }

    payload = dict(merged.get("papergraph_input") or {}) if isinstance(merged.get("papergraph_input"), dict) else {}
    payload["venue_metadata"] = dict(merged.get("venue_metadata") or {})
    payload["citation_metrics"] = dict(merged.get("citation_metrics") or {})
    payload["external_ids"] = dict(merged.get("external_ids") or {})
    payload["openalex_id"] = str(merged.get("openalex_id") or "")
    payload["provider_provenance"] = {
        **(dict(payload.get("provider_provenance") or {}) if isinstance(payload.get("provider_provenance"), dict) else {}),
        "metadata_enrichment_provider": "openalex",
        "openalex_id": str(merged.get("openalex_id") or ""),
    }
    merged["papergraph_input"] = payload

    quality = publication_quality_assessment(merged)
    _apply_quality_assessment(merged, quality)
    record = _candidate_score_record(merged)
    record["quality"] = dict(quality)
    merged["candidate_score_record"] = record
    return merged


def enrich_selected_venue_metadata_with_openalex(
    results: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Bound selected-result DOI metadata enrichment to a tiny per-search cap."""
    limit = max(0, int(SCIENCE_OPENALEX_VENUE_ENRICHMENT_PER_SEARCH))
    report: dict[str, Any] = {
        "enabled": bool(limit),
        "limit": limit,
        "eligible_count": 0,
        "attempted": 0,
        "enriched": 0,
        "cache_hits": 0,
        "statuses": {},
    }
    copied = [dict(item) for item in results if isinstance(item, dict)]
    if not limit or not copied:
        return copied, report
    candidates = [
        (index, item)
        for index, item in enumerate(copied)
        if selected_candidate_needs_openalex_venue_enrichment(item)
    ]
    report["eligible_count"] = len(candidates)
    if not candidates:
        return copied, report
    try:
        from ._openalex import fetch_openalex_work_by_doi
    except ImportError:
        from _openalex import fetch_openalex_work_by_doi
    for index, item in sorted(candidates, key=lambda pair: _selected_venue_enrichment_priority(pair[1]))[:limit]:
        report["attempted"] += 1
        outcome = fetch_openalex_work_by_doi(str(item.get("doi") or ""))
        status = str(outcome.get("status") or "error")
        report["statuses"][status] = int(report["statuses"].get(status) or 0) + 1
        report["cache_hits"] += int(bool(outcome.get("cache_hit")))
        openalex_result = outcome.get("result") if isinstance(outcome.get("result"), dict) else None
        if status == "ok" and openalex_result:
            copied[index] = _merge_selected_openalex_venue_metadata(item, openalex_result)
            report["enriched"] += 1
    log_event(
        "SCIENCE",
        "openalex_selected_venue_enrichment_complete",
        **report,
    )
    return copied, report


def _apply_ranking_assessment(item: dict[str, Any], assessment: dict[str, Any]) -> None:
    item["relevance_score"] = assessment["score"]
    item["relevance_components"] = dict(assessment["components"])
    item["matched_query_terms"] = list(assessment["matched_terms"])
    item["relevance_reason"] = assessment["reason"]


def evaluate_candidate_domain_gate(
    candidate: dict[str, Any],
    *,
    domain: str,
    query: str,
    domain_profile: Mapping[str, Any] | None = None,
    domain_profile_revision: str = "",
    assessment_cache: dict[str, dict[str, Any]] | None = None,
) -> tuple[bool, bool, float]:
    """Evaluate a candidate locally against one pre-resolved domain profile."""
    try:
        from ._literature_scoring import domain_relevance_assessment, should_reject_for_domain
    except ImportError:
        from _literature_scoring import domain_relevance_assessment, should_reject_for_domain
    started = time.perf_counter()
    record = _candidate_score_record(candidate)
    context_key = _scoring_context_key(
        domain,
        query,
        domain_profile_revision or "local_structured_profile_v1",
    )
    shared_cache_key = _scoring_context_key(
        _candidate_paper_fingerprint(candidate),
        context_key,
    )
    assessments = record["domain_assessments"]
    shared_cached = (
        assessment_cache.get(shared_cache_key)
        if isinstance(assessment_cache, dict)
        else None
    )
    if isinstance(shared_cached, dict):
        cached = deepcopy(shared_cached)
        candidate["domain_relevance"] = dict(
            cached.get("domain_relevance") or {}
        )
        if isinstance(cached.get("domain_review"), dict):
            candidate["domain_review"] = dict(cached["domain_review"])
        if isinstance(cached.get("domain_gate"), dict):
            candidate["domain_gate"] = dict(cached["domain_gate"])
        assessments[context_key] = deepcopy(cached)
        record["domain_assessments"] = assessments
        candidate["candidate_score_record"] = record
        return bool(cached.get("rejected")), True, (time.perf_counter() - started) * 1000.0
    cached = assessments.get(context_key)
    if isinstance(cached, dict):
        candidate["domain_relevance"] = dict(cached.get("domain_relevance") or {})
        if isinstance(cached.get("domain_review"), dict):
            candidate["domain_review"] = dict(cached["domain_review"])
        if isinstance(cached.get("domain_gate"), dict):
            candidate["domain_gate"] = dict(cached["domain_gate"])
        candidate["candidate_score_record"] = record
        if isinstance(assessment_cache, dict):
            assessment_cache[shared_cache_key] = deepcopy(cached)
        return bool(cached.get("rejected")), True, (time.perf_counter() - started) * 1000.0

    relevance = domain_relevance_assessment(
        candidate,
        domain=domain,
        query=query,
        **(
            {"domain_profile": domain_profile}
            if isinstance(domain_profile, Mapping)
            else {}
        ),
    )
    candidate["domain_relevance"] = relevance
    rejected = should_reject_for_domain(candidate, domain=domain, query=query)
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    assessments[context_key] = {
        "domain": normalize_space(domain),
        "query": normalize_space(query),
        "domain_relevance": dict(relevance),
        "domain_review": dict(candidate.get("domain_review") or {}),
        "domain_gate": dict(candidate.get("domain_gate") or {}),
        "object_mechanism": dict(relevance.get("domain_mechanism_evidence") or {}),
        "rejected": bool(rejected),
        "domain_profile_revision": (
            domain_profile_revision or "local_structured_profile_v1"
        ),
        "elapsed_ms": round(elapsed_ms, 3),
    }
    record["domain_assessments"] = assessments
    candidate["candidate_score_record"] = record
    if isinstance(assessment_cache, dict):
        assessment_cache[shared_cache_key] = deepcopy(assessments[context_key])
    return bool(rejected), False, elapsed_ms


def coarse_subhypothesis_candidate_prefilter(
    candidate: dict[str, Any],
    alignment_contract: dict[str, Any],
) -> dict[str, Any]:
    """Apply the V3 task-local metadata scope gate.

    Project retrieval may only be admitted through an explicit
    ``slot_candidate_scope_v3``.  In particular, this boundary no longer
    reconstructs a project-context/object/causal-edge contract from a V1
    alignment payload.  Full-text extraction and typed-slot admission decide
    whether an imported paper becomes evidence.
    """

    if _is_v3_slot_candidate_scope(alignment_contract):
        return _v3_slot_candidate_scope_assessment(candidate, alignment_contract)

    return _v3_slot_scope_required_assessment(alignment_contract)

    text = _fragment_anchor_candidate_text(candidate)
    if not text:
        return {
            "passes": False,
            "reason_code": "COARSE_PREFILTER_MISSING_TEXT",
            "object_hits": [],
            "strong_object_hits": [],
            "auxiliary_object_hits": [],
            "causal_axis_hits": {},
        }

    def normalized_unique(values: list[Any]) -> list[str]:
        output: list[str] = []
        seen: set[str] = set()
        for value in values:
            normalized = normalize_space(str(value or "")).lower()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            output.append(normalized)
        return output

    try:
        from ._research_alignment import (
            declared_input_anchor_group_for_contract,
            exclusion_terms_by_confidence_for_contract,
            expanded_exclusion_terms_for_contract,
            is_component_bridge_modifier_only_anchor,
            is_specific_object_anchor,
        )
    except ImportError:
        from _research_alignment import (
            declared_input_anchor_group_for_contract,
            exclusion_terms_by_confidence_for_contract,
            expanded_exclusion_terms_for_contract,
            is_component_bridge_modifier_only_anchor,
            is_specific_object_anchor,
        )
    object_policy = (
        alignment_contract.get("scientific_object_anchor_policy")
        if isinstance(alignment_contract.get("scientific_object_anchor_policy"), dict)
        else {}
    )
    scope_policy = (
        alignment_contract.get("subhypothesis_scope_policy")
        if isinstance(alignment_contract.get("subhypothesis_scope_policy"), dict)
        else {}
    )
    panel_policy = (
        alignment_contract.get("multi_entity_panel_policy")
        if isinstance(alignment_contract.get("multi_entity_panel_policy"), dict)
        else {}
    )
    candidate_evidence_roles = normalized_unique(
        [
            candidate.get("evidence_path_role"),
            candidate.get("query_family"),
            candidate.get("query_branch"),
            candidate.get("target_lane"),
            candidate.get("evidence_lane"),
            candidate.get("retrieval_object_profile_role"),
            *(candidate.get("matched_evidence_path_roles") or []),
        ]
    )
    role_text_for_scope = " ".join(candidate_evidence_roles).lower()
    # Retrieval plans name evidence *roles* (for example a mechanism,
    # benchmark, boundary, or component path).  They do not promise that a
    # single paper contains the whole input -> mechanism -> outcome chain.
    # Keep the vocabulary methodological and domain-neutral so this remains a
    # general literature-admission rule rather than a field-specific patch.
    evidence_role_markers = (
        "background", "benchmark", "boundary", "bridge", "comparison",
        "component", "condition", "constraint", "context", "effect",
        "evaluation", "experiment", "framework", "implementation",
        "mechanism", "method", "model", "observation", "outcome",
        "parameter", "platform", "readout", "replication", "safety",
        "sensitivity", "simulation", "theoretical", "translation",
        "validation", "verification",
    )
    evidence_role_signal = bool(
        any(
            marker in role
            for role in candidate_evidence_roles
            for marker in evidence_role_markers
        )
    )
    is_background_context_path = bool(
        str(candidate.get("target_lane") or "").strip().upper()
        in {"THEORETICAL_FRAMEWORK", "BACKGROUND_REVIEW"}
        or any(
            marker in role_text_for_scope
            for marker in (
                "background",
                "context_review",
                "context review",
                "framework",
                "theoretical_framework",
                "review",
            )
        )
    )
    panel_evidence_tier = normalize_space(str(candidate.get("panel_evidence_tier") or "")).lower()
    is_panel_component_path = bool(
        panel_policy.get("is_multi_entity_panel")
        and (
            candidate.get("panel_component_path") is True
            or panel_evidence_tier in {"support", "context"}
            or any(
                marker in role
                for role in candidate_evidence_roles
                for marker in ("support", "component", "constraint", "deployment")
            )
        )
    )
    declared_strong_policy_anchors = normalized_unique(
        list(object_policy.get("strong_anchor_phrases") or [])
        + list(object_policy.get("strong_anchor_terms") or [])
    )
    semantic_equivalent_object_anchors = normalized_unique(
        list(object_policy.get("semantic_equivalent_anchor_phrases") or [])
        + list(object_policy.get("semantic_equivalent_anchor_terms") or [])
    )
    strong_policy_anchors = normalized_unique(
        declared_strong_policy_anchors
        + semantic_equivalent_object_anchors
        + list(object_policy.get("object_group") or [])
    )
    related_context_object_anchors = normalized_unique(
        list(object_policy.get("related_context_anchor_phrases") or [])
        + list(object_policy.get("related_context_anchor_terms") or [])
    )
    auxiliary_object_anchors = normalized_unique(
        list(object_policy.get("auxiliary_terms") or [])
        + list(object_policy.get("single_terms_not_sufficient") or [])
        + list(alignment_contract.get("object_auxiliary_terms") or [])
    )
    retrieval_object_profiles = [
        dict(profile)
        for profile in (alignment_contract.get("retrieval_object_profiles") or [])
        if isinstance(profile, dict)
    ][:3]
    active_profile_id = normalize_space(
        str(candidate.get("retrieval_object_profile_id") or "")
    ).upper()
    active_retrieval_object_profile = next(
        (
            profile for profile in retrieval_object_profiles
            if normalize_space(str(profile.get("id") or "")).upper() == active_profile_id
        ),
        {},
    )
    active_profile_role = normalize_space(
        str(active_retrieval_object_profile.get("role") or "")
    ).lower()
    active_profile_anchors = normalized_unique(
        [
            active_retrieval_object_profile.get("query_anchor"),
            active_retrieval_object_profile.get("object"),
            *(active_retrieval_object_profile.get("aliases") or []),
        ]
    )
    panel_component_anchors = normalized_unique(
        list(panel_policy.get("component_anchor_group") or [])
        + list(candidate.get("component_anchor_group") or [])
    )
    direct_core_allowed_by_maturity = object_policy.get("direct_core_object_allowed") is not False
    typed_component_bridge_object_anchors = normalized_unique(
        list(object_policy.get("component_bridge_object_anchor_phrases") or [])
        + list(
            (
                alignment_contract.get("object_maturity_audit")
                if isinstance(alignment_contract.get("object_maturity_audit"), dict)
                else {}
            ).get("object_anchors")
            or []
        )
    )
    component_bridge_method_or_platform_anchors = normalized_unique(
        list(object_policy.get("component_bridge_method_or_platform_anchor_phrases") or [])
        + list(
            (
                alignment_contract.get("object_maturity_audit")
                if isinstance(alignment_contract.get("object_maturity_audit"), dict)
                else {}
            ).get("method_or_platform_anchors")
            or []
        )
    )
    component_bridge_readout_anchors = normalized_unique(
        list(object_policy.get("component_bridge_readout_anchor_phrases") or [])
        + list(
            (
                alignment_contract.get("object_maturity_audit")
                if isinstance(alignment_contract.get("object_maturity_audit"), dict)
                else {}
            ).get("readout_anchors")
            or []
        )
    )
    component_bridge_model_system_anchors = normalized_unique(
        list(object_policy.get("component_bridge_model_system_anchor_phrases") or [])
        + list(
            (
                alignment_contract.get("object_maturity_audit")
                if isinstance(alignment_contract.get("object_maturity_audit"), dict)
                else {}
            ).get("model_system_anchors")
            or []
        )
    )
    component_bridge_support_anchors = normalized_unique(
        component_bridge_method_or_platform_anchors
        + component_bridge_readout_anchors
        + component_bridge_model_system_anchors
    )
    typed_component_bridge_groups_declared = bool(
        object_policy.get("component_bridge_anchor_groups_typed")
        or (
            isinstance(alignment_contract.get("object_maturity_audit"), dict)
            and (
                (alignment_contract.get("object_maturity_audit") or {}).get("typed_component_bridge_anchors")
                or (alignment_contract.get("object_maturity_audit") or {}).get("component_bridge_anchor_quality")
            )
        )
    )
    typed_component_bridge_groups_available = bool(
        typed_component_bridge_groups_declared
        and (
            typed_component_bridge_object_anchors
            or component_bridge_support_anchors
            or (
                isinstance(
                    (
                        alignment_contract.get("object_maturity_audit")
                        if isinstance(alignment_contract.get("object_maturity_audit"), dict)
                        else {}
                    ).get("component_bridge_anchor_quality"),
                    dict,
                )
            )
        )
    )
    component_bridge_anchors = normalized_unique(
        typed_component_bridge_object_anchors
        if typed_component_bridge_groups_available
        else []
    )
    is_maturity_component_bridge_path = bool(
        not direct_core_allowed_by_maturity
        and any(
            marker in role
            for role in candidate_evidence_roles
            for marker in (
                "component", "bridge", "translation", "translational",
                "boundary", "safety", "adverse", "reversal", "failure",
                "toxicity", "instability", "heterogeneity", "context", "framework",
            )
        )
    )
    # Some persisted contracts predate the explicit anchor-policy block.  Use
    # only their independently specific object aliases as a compatibility
    # input to this generic prefilter; do not infer missing causal fragments
    # from generic project vocabulary.
    raw_object_anchors = normalized_unique(
        list(alignment_contract.get("scientific_object_phrases") or [])
        + list(alignment_contract.get("scientific_object_terms") or [])
    )
    legacy_specific_object_anchors = [
        anchor for anchor in raw_object_anchors
        if is_specific_object_anchor(anchor)
    ]
    if strong_policy_anchors:
        object_anchors = strong_policy_anchors
        anchor_policy_mode = "strong_object_anchor_policy"
    else:
        object_anchors = legacy_specific_object_anchors
        anchor_policy_mode = (
            "legacy_specific_object_anchor_recall"
            if object_anchors
            else "missing_strong_object_anchor_policy"
        )
    requires_specific_object_anchor = bool(
        object_policy.get("requires_specific_anchor")
        or alignment_contract.get("scientific_object")
        or strong_policy_anchors
    )
    core_axis_policy = (
        alignment_contract.get("core_axis_policy")
        if isinstance(alignment_contract.get("core_axis_policy"), dict)
        else {}
    )
    def policy_axis(axis: str) -> list[str]:
        key = {
            "input": "focal_variable",
            "mechanism": "mechanism",
            "outcome": "outcome",
        }[axis]
        return normalized_unique(
            list(core_axis_policy.get(f"{key}_phrases") or [])
            + list(core_axis_policy.get(f"{key}_terms") or [])
        )
    axis_anchors = {
        "input": policy_axis("input"),
        "mechanism": policy_axis("mechanism"),
        "outcome": policy_axis("outcome"),
    }
    explicit_exclusions = normalized_unique(
        list(alignment_contract.get("explicit_exclusion_terms") or [])
        + list(alignment_contract.get("excluded_nearby_objects") or [])
    )
    exclusion_confidence = exclusion_terms_by_confidence_for_contract(
        alignment_contract,
        domain=str(alignment_contract.get("primary_field") or ""),
    )
    protected_positive_terms = normalized_unique(
        list(exclusion_confidence.get("protected_positive_terms") or [])
        + list(alignment_contract.get("protected_positive_terms") or [])
    )
    legacy_sibling_scope_terms = normalized_unique(
        list(scope_policy.get("sibling_scope_terms") or [])
    )
    direct_contract_query_forbidden = normalized_unique([
        term
        for term in (alignment_contract.get("query_forbidden_terms") or [])
        if normalize_space(str(term or "")).lower()
        not in legacy_sibling_scope_terms
    ])
    hard_scope_exclusions = normalized_unique(
        list(exclusion_confidence.get("hard_exclusion_terms") or [])
        + list(exclusion_confidence.get("query_forbidden_terms") or [])
        + direct_contract_query_forbidden
    )
    fast_scope_exclusions = normalized_unique(
        list(exclusion_confidence.get("fast_reject_terms") or [])
    )
    soft_scope_exclusions = normalized_unique(
        list(exclusion_confidence.get("soft_exclusion_terms") or [])
    )
    scope_conflict_soft_terms = normalized_unique(
        list(exclusion_confidence.get("scope_conflict_soft_terms") or [])
        + list(alignment_contract.get("scope_conflict_soft_terms") or [])
    )
    exclusions = normalized_unique(
        explicit_exclusions + hard_scope_exclusions + fast_scope_exclusions
    )
    def exclusion_anchor_matches_candidate(anchor: str, candidate_text: str) -> bool:
        normalized_anchor = normalize_space(str(anchor or "")).lower()
        if not normalized_anchor:
            return False
        comparable_text = normalize_space(
            re.sub(r"[\u2010-\u2015\u2212]", "-", str(candidate_text or "").lower())
        )
        comparable_space_text = normalize_space(comparable_text.replace("-", " "))
        comparable_anchor = normalize_space(
            re.sub(r"[\u2010-\u2015\u2212]", "-", normalized_anchor)
        )
        variants = {
            comparable_anchor,
            normalize_space(comparable_anchor.replace("-", " ")),
            normalize_space(comparable_anchor.replace("'", "")),
            normalize_space(comparable_anchor.replace("\u2019", "'")),
        }
        return any(
            variant
            and (
                re.search(rf"(?<![a-z0-9]){re.escape(variant)}(?![a-z0-9])", comparable_text)
                or re.search(rf"(?<![a-z0-9]){re.escape(variant)}(?![a-z0-9])", comparable_space_text)
            )
            for variant in variants
        )
    sibling_object_role_conflict_candidates = [
        {
            "term": normalize_space(str(item.get("term") or "")).lower(),
            "source_sh_id": normalize_space(str(item.get("source_sh_id") or "")),
            "source_field": normalize_space(str(item.get("source_field") or "")),
            "enforcement": "post_retrieval_object_role_conflict_only",
        }
        for item in (
            scope_policy.get("sibling_object_role_conflict_candidates") or []
        )
        if isinstance(item, dict) and normalize_space(str(item.get("term") or ""))
    ][:32]
    protected_positive_hits = [
        anchor for anchor in protected_positive_terms
        if exclusion_anchor_matches_candidate(anchor, text)
    ]
    explicit_exclusion_hits = [
        anchor for anchor in explicit_exclusions
        if anchor in hard_scope_exclusions
        and exclusion_anchor_matches_candidate(anchor, text)
    ]
    hard_scope_forbidden_hits = [
        anchor for anchor in hard_scope_exclusions
        if exclusion_anchor_matches_candidate(anchor, text)
    ]
    fast_scope_forbidden_hits = [
        anchor for anchor in fast_scope_exclusions
        if exclusion_anchor_matches_candidate(anchor, text)
    ]
    soft_exclusion_hits = [
        anchor for anchor in soft_scope_exclusions
        if exclusion_anchor_matches_candidate(anchor, text)
    ]
    scope_conflict_soft_hits = [
        anchor for anchor in scope_conflict_soft_terms
        if exclusion_anchor_matches_candidate(anchor, text)
    ]
    exclusion_hits = normalized_unique(
        explicit_exclusion_hits + hard_scope_forbidden_hits + fast_scope_forbidden_hits
    )
    scope_forbidden_hits = normalized_unique(
        hard_scope_forbidden_hits + fast_scope_forbidden_hits
    )
    expanded_exclusion_hits = scope_forbidden_hits
    def scope_forbidden_hit_overlaps_positive_anchor(hit: str) -> bool:
        normalized_hit = normalize_space(str(hit or "").lower())
        if not normalized_hit:
            return False
        for anchor in protected_positive_hits:
            normalized_anchor = normalize_space(str(anchor or "").lower())
            if not normalized_anchor:
                continue
            if (
                normalized_hit == normalized_anchor
                or normalized_hit in normalized_anchor
                or normalized_anchor in normalized_hit
            ):
                return True
        return False

    scope_conflict_with_positive_anchor_hits = normalized_unique([
        hit for hit in scope_forbidden_hits
        if scope_forbidden_hit_overlaps_positive_anchor(hit)
    ])
    scope_forbidden_overridden_by_positive_anchor = bool(
        scope_conflict_with_positive_anchor_hits
    )
    effective_explicit_exclusion_hits = (
        []
        if scope_forbidden_overridden_by_positive_anchor
        else explicit_exclusion_hits
    )
    effective_scope_forbidden_hits = (
        []
        if scope_forbidden_overridden_by_positive_anchor
        else scope_forbidden_hits
    )
    effective_expanded_exclusion_hits = effective_scope_forbidden_hits
    effective_exclusion_hits = normalized_unique(
        effective_explicit_exclusion_hits + effective_scope_forbidden_hits
    )
    object_matcher = (
        _strong_object_anchor_matches_candidate
        if strong_policy_anchors
        else _anchor_phrase_matches_candidate
    )
    object_hits = [
        anchor for anchor in object_anchors
        if object_matcher(anchor, text)
    ]
    legacy_recall_object_hits = [
        anchor for anchor in legacy_specific_object_anchors
        if anchor not in object_anchors
        and _anchor_phrase_matches_candidate(anchor, text)
    ]
    legacy_recall_object_pass = bool(legacy_recall_object_hits)
    declared_strong_object_hits = [
        anchor for anchor in declared_strong_policy_anchors
        if _strong_object_anchor_matches_candidate(anchor, text)
    ]
    semantic_equivalent_object_hits = [
        anchor for anchor in semantic_equivalent_object_anchors
        if _strong_object_anchor_matches_candidate(anchor, text)
    ]
    related_context_object_hits = [
        anchor for anchor in related_context_object_anchors
        if _strong_object_anchor_matches_candidate(anchor, text)
    ]
    auxiliary_object_hits = [
        anchor for anchor in auxiliary_object_anchors
        if _anchor_phrase_matches_candidate(anchor, text)
    ]
    active_profile_hits = [
        anchor for anchor in active_profile_anchors
        if _strong_object_anchor_matches_candidate(anchor, text)
        or _anchor_phrase_matches_candidate(anchor, text)
    ]
    nonprimary_profile_path = bool(
        active_retrieval_object_profile
        and active_profile_role != "primary_system"
    )
    panel_component_hits = [
        anchor for anchor in panel_component_anchors
        if _anchor_phrase_matches_candidate(anchor, text)
    ]
    component_bridge_hits = [
        anchor for anchor in component_bridge_anchors
        if _strong_object_anchor_matches_candidate(anchor, text)
        or _anchor_phrase_matches_candidate(anchor, text)
    ]
    component_bridge_concrete_hits = [
        anchor for anchor in component_bridge_hits
        if not is_component_bridge_modifier_only_anchor(anchor)
    ]
    component_bridge_modifier_only_hits = [
        anchor for anchor in component_bridge_hits
        if is_component_bridge_modifier_only_anchor(anchor)
    ]
    component_bridge_support_hits = [
        anchor for anchor in component_bridge_support_anchors
        if _strong_object_anchor_matches_candidate(anchor, text)
        or _anchor_phrase_matches_candidate(anchor, text)
    ]
    component_bridge_method_or_platform_hits = [
        anchor for anchor in component_bridge_method_or_platform_anchors
        if _strong_object_anchor_matches_candidate(anchor, text)
        or _anchor_phrase_matches_candidate(anchor, text)
    ]
    component_bridge_readout_hits = [
        anchor for anchor in component_bridge_readout_anchors
        if _strong_object_anchor_matches_candidate(anchor, text)
        or _anchor_phrase_matches_candidate(anchor, text)
    ]
    component_bridge_model_system_hits = [
        anchor for anchor in component_bridge_model_system_anchors
        if _strong_object_anchor_matches_candidate(anchor, text)
        or _anchor_phrase_matches_candidate(anchor, text)
    ]
    sibling_object_role_conflict_hits = [
        item
        for item in sibling_object_role_conflict_candidates
        if exclusion_anchor_matches_candidate(str(item.get("term") or ""), text)
    ]
    current_sh_object_evidence = bool(
        object_hits
        or legacy_recall_object_hits
        or declared_strong_object_hits
        or semantic_equivalent_object_hits
        or related_context_object_hits
        or component_bridge_concrete_hits
        or (active_profile_role == "primary_system" and active_profile_hits)
    )
    sibling_object_role_conflict_state = (
        "sibling_primary_object_risk"
        if sibling_object_role_conflict_hits and not current_sh_object_evidence
        else "shared_or_comparative_context"
        if sibling_object_role_conflict_hits
        else "none"
    )
    causal_axis_hits = {
        axis: [
            anchor for anchor in anchors
            if _anchor_phrase_matches_candidate(anchor, text)
        ]
        for axis, anchors in axis_anchors.items()
    }
    populated_axes = [axis for axis, anchors in axis_anchors.items() if anchors]
    matched_axes = [axis for axis, hits in causal_axis_hits.items() if hits]
    declared_input_required = bool(axis_anchors.get("input"))
    declared_input_hits = list(causal_axis_hits.get("input") or [])
    declared_input_supported = bool(declared_input_hits) or not declared_input_required
    declared_input_missing_for_sh_local_path = bool(
        declared_input_required
        and not declared_input_hits
        and not is_background_context_path
        and not (nonprimary_profile_path and active_profile_role == "input_or_parameter")
    )
    # Metadata often omits an experimental condition that is stated precisely
    # in the methods/full text.  Absence of a literal input term therefore is
    # not itself an off-topic finding.  Only a candidate that also lacks the
    # object and all non-input causal/design support is rejected before full
    # text; a plausible candidate remains an explicitly quarantined buffer.
    non_input_axis_hits = [
        axis for axis in ("mechanism", "outcome")
        if causal_axis_hits.get(axis)
    ]
    input_plausible_for_fulltext = bool(
        declared_input_missing_for_sh_local_path
        and (
            object_hits
            or declared_strong_object_hits
            or semantic_equivalent_object_hits
            or related_context_object_hits
            or component_bridge_support_hits
        )
        and non_input_axis_hits
    )
    declared_input_state = (
        "INPUT_EXPLICITLY_SUPPORTED"
        if declared_input_supported
        else "INPUT_PLAUSIBLE_BUT_NEEDS_FULLTEXT"
        if input_plausible_for_fulltext
        else "INPUT_UNSUPPORTED"
    )
    positive_scope_conflict_hits = normalized_unique([
        hit
        for hit in soft_exclusion_hits + scope_conflict_soft_hits
        if hit not in protected_positive_hits
    ])
    # One multi-token object phrase or two independently derived object terms
    # are enough for the recall-oriented prefilter.  A single technical object
    # term also survives when the candidate matches two causal axes.
    phrase_hit = any(" " in hit for hit in object_hits)
    declared_object_context_for_component_bridge = bool(
        object_hits
        or legacy_recall_object_hits
        or declared_strong_object_hits
        or semantic_equivalent_object_hits
        or related_context_object_hits
    )
    component_bridge_pass = bool(
        is_maturity_component_bridge_path
        and (
            (
                component_bridge_concrete_hits
                and (
                    component_bridge_method_or_platform_hits
                    or component_bridge_readout_hits
                    or component_bridge_model_system_hits
                    or (
                        (matched_axes or evidence_role_signal)
                        and not typed_component_bridge_groups_available
                    )
                )
            )
            or (
                declared_object_context_for_component_bridge
                and component_bridge_method_or_platform_hits
                and (
                    component_bridge_readout_hits
                    or component_bridge_model_system_hits
                )
            )
        )
    )
    if strong_policy_anchors:
        maturity_component_bridge_requires_support = bool(
            is_maturity_component_bridge_path
            and not direct_core_allowed_by_maturity
        )
        object_pass = bool(
            (not requires_specific_object_anchor and not object_anchors)
            or (phrase_hit and not maturity_component_bridge_requires_support)
            or (len(object_hits) >= 2 and not maturity_component_bridge_requires_support)
            or (len(object_hits) == 1 and not maturity_component_bridge_requires_support)
            or (legacy_recall_object_pass and not maturity_component_bridge_requires_support)
            or (nonprimary_profile_path and bool(active_profile_hits))
            or (
                related_context_object_hits
                and (matched_axes or evidence_role_signal)
                and not maturity_component_bridge_requires_support
            )
            or (is_panel_component_path and panel_component_hits)
            or component_bridge_pass
        )
    else:
        object_pass = bool(
            (not requires_specific_object_anchor and not object_anchors)
            or phrase_hit
            or len(object_hits) >= 2
            or bool(object_hits)
            or legacy_recall_object_pass
            or (nonprimary_profile_path and bool(active_profile_hits))
        )
    # A candidate must still be locally relevant, but it may supply just one
    # role in an evidence bundle.  The remaining axes must be verified only
    # after the paper text is available.
    causal_pass = bool(
        not populated_axes
        or matched_axes
        or evidence_role_signal
        or panel_component_hits
        or component_bridge_pass
    )
    passes = bool(
        object_pass
        and causal_pass
        and not effective_exclusion_hits
    )
    if effective_scope_forbidden_hits or effective_expanded_exclusion_hits:
        reason = "COARSE_PREFILTER_SCOPE_FORBIDDEN_TERM"
    elif effective_explicit_exclusion_hits:
        reason = "COARSE_PREFILTER_EXPLICIT_EXCLUSION"
    elif (
        is_maturity_component_bridge_path
        and component_bridge_hits
        and not component_bridge_concrete_hits
        and not object_pass
    ):
        reason = "COARSE_PREFILTER_COMPONENT_BRIDGE_MODIFIER_ONLY"
    elif (
        is_maturity_component_bridge_path
        and component_bridge_concrete_hits
        and not component_bridge_pass
        and not object_pass
    ):
        reason = "COARSE_PREFILTER_COMPONENT_BRIDGE_SUPPORT_MISSING"
    elif (
        declared_input_state
        in {"INPUT_PLAUSIBLE_BUT_NEEDS_FULLTEXT", "INPUT_UNSUPPORTED"}
        and passes
    ):
        reason = "COARSE_PREFILTER_INPUT_PLAUSIBLE_NEEDS_FULLTEXT"
    elif requires_specific_object_anchor and not object_anchors:
        reason = "COARSE_PREFILTER_OBJECT_ANCHOR_UNDERSPECIFIED"
    elif not object_pass:
        reason = "COARSE_PREFILTER_OBJECT_MISMATCH"
    elif not causal_pass:
        reason = "COARSE_PREFILTER_EVIDENCE_ROLE_MISSING"
    elif scope_forbidden_overridden_by_positive_anchor and passes:
        reason = "COARSE_PREFILTER_SCOPE_CONFLICT_WITH_POSITIVE_ANCHOR"
    else:
        reason = "COARSE_PREFILTER_PASSED"
    return {
        "passes": passes,
        "reason_code": reason,
        "specific_object_anchor_required": requires_specific_object_anchor,
        "specific_object_anchors": object_anchors[:12],
        "object_hits": object_hits[:12],
        "strong_object_anchors": object_anchors[:12],
        "strong_object_hits": object_hits[:12],
        "legacy_recall_object_anchors": legacy_specific_object_anchors[:12],
        "legacy_recall_object_hits": legacy_recall_object_hits[:12],
        "legacy_recall_object_pass": legacy_recall_object_pass,
        "declared_strong_object_hits": declared_strong_object_hits[:12],
        "semantic_equivalent_object_anchors": semantic_equivalent_object_anchors[:12],
        "semantic_equivalent_object_hits": semantic_equivalent_object_hits[:12],
        "related_context_object_anchors": related_context_object_anchors[:12],
        "related_context_object_hits": related_context_object_hits[:12],
        "auxiliary_object_anchors": auxiliary_object_anchors[:12],
        "auxiliary_object_hits": auxiliary_object_hits[:12],
        "retrieval_object_profile_id": active_profile_id,
        "retrieval_object_profile_role": active_profile_role,
        "retrieval_object_profile_anchors": active_profile_anchors[:12],
        "retrieval_object_profile_hits": active_profile_hits[:12],
        "retrieval_object_profile_pass": bool(
            nonprimary_profile_path and active_profile_hits
        ),
        "panel_component_path": is_panel_component_path,
        "panel_evidence_tier": panel_evidence_tier,
        "panel_component_anchors": panel_component_anchors[:16],
        "panel_component_hits": panel_component_hits[:16],
        "component_bridge_object_anchors": component_bridge_anchors[:16],
        "component_bridge_object_hits": component_bridge_concrete_hits[:16],
        "component_bridge_support_anchors": component_bridge_support_anchors[:16],
        "component_bridge_support_hits": component_bridge_support_hits[:16],
        "component_bridge_method_or_platform_hits": component_bridge_method_or_platform_hits[:16],
        "component_bridge_readout_hits": component_bridge_readout_hits[:16],
        "component_bridge_model_system_hits": component_bridge_model_system_hits[:16],
        "component_bridge_pass": component_bridge_pass,
        "component_bridge_raw_object_hits": component_bridge_hits[:16],
        "component_bridge_modifier_only_hits": component_bridge_modifier_only_hits[:16],
        "object_maturity_component_bridge_path": is_maturity_component_bridge_path,
        "panel_component_support_only": bool(
            is_panel_component_path and panel_component_hits and not object_hits
        ),
        "component_bridge_support_only": bool(
            is_maturity_component_bridge_path
            and component_bridge_pass
            and not object_hits
        ),
        "object_anchor_strength": (
            "strong" if declared_strong_object_hits
            else "semantic_equivalent" if semantic_equivalent_object_hits
            else "legacy_specific_alias" if legacy_recall_object_pass
            else "component_bridge_object_plus_support" if component_bridge_pass
            else "component_bridge_object_without_support" if is_maturity_component_bridge_path and component_bridge_concrete_hits
            else "component_support_only" if is_panel_component_path and panel_component_hits
            else "related_context_auxiliary" if related_context_object_hits
            else "auxiliary_only" if auxiliary_object_hits
            else "missing"
        ),
        "object_anchor_policy_mode": anchor_policy_mode,
        "causal_axis_hits": {
            axis: hits[:8] for axis, hits in causal_axis_hits.items()
        },
        "matched_axes": matched_axes,
        "candidate_evidence_roles": candidate_evidence_roles[:16],
        "evidence_role_signal": evidence_role_signal,
        "declared_input_required": declared_input_required,
        "declared_input_hits": declared_input_hits[:8],
        "declared_input_supported": declared_input_supported,
        "declared_input_missing_for_sh_local_path": declared_input_missing_for_sh_local_path,
        "input_support_state": declared_input_state,
        "input_plausible_but_needs_fulltext": input_plausible_for_fulltext,
        "background_context_path": is_background_context_path,
        "exclusion_hits": exclusion_hits[:8],
        "effective_exclusion_hits": effective_exclusion_hits[:8],
        "explicit_exclusion_hits": explicit_exclusion_hits[:8],
        "effective_explicit_exclusion_hits": effective_explicit_exclusion_hits[:8],
        "scope_forbidden_hits": scope_forbidden_hits[:8],
        "effective_scope_forbidden_hits": effective_scope_forbidden_hits[:8],
        "expanded_exclusion_hits": expanded_exclusion_hits[:8],
        "effective_expanded_exclusion_hits": effective_expanded_exclusion_hits[:8],
        "scope_forbidden_overridden_by_positive_anchor": scope_forbidden_overridden_by_positive_anchor,
        "scope_conflict_with_positive_anchor_hits": scope_conflict_with_positive_anchor_hits[:8],
        "hard_exclusion_terms": hard_scope_exclusions[:24],
        "fast_reject_terms": fast_scope_exclusions[:24],
        "soft_exclusion_terms": soft_scope_exclusions[:24],
        "protected_positive_hits": protected_positive_hits[:12],
        "soft_exclusion_hits": soft_exclusion_hits[:12],
        "scope_conflict_soft_hits": scope_conflict_soft_hits[:12],
        "positive_scope_conflict_hits": positive_scope_conflict_hits[:12],
        "scope_conflict_soft_terms": scope_conflict_soft_terms[:24],
        "sibling_object_role_conflict_hits": sibling_object_role_conflict_hits[:12],
        "sibling_object_role_conflict_state": sibling_object_role_conflict_state,
        "sibling_primary_object_risk": bool(
            sibling_object_role_conflict_state == "sibling_primary_object_risk"
        ),
        "expanded_exclusion_terms": exclusions[:24],
    }


_PREFULLTEXT_IMPORT_DESIGN_OR_CAUSAL_MARKERS = (
    "ablation", "assay", "case-control", "cell culture", "cohort", "controlled",
    "dose", "experiment", "experimental", "imaging", "in situ", "in vivo",
    "in vitro", "intervention", "knockout", "laboratory", "longitudinal",
    "manipulated", "measured", "measurement", "microscopy", "model system",
    "mutant", "perturb", "quantified", "randomized", "sequencing",
    "spectroscopy", "tomography", "trial", "treated", "untreated",
    "validated", "validation", "varied", "variation",
)


def prefulltext_import_candidate_assessment(
    candidate: dict[str, Any],
    alignment_contract: dict[str, Any],
    *,
    strict_assessment: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """High-recall, scope-safe admission for capped full-text verification.

    This deliberately does *not* declare import/core eligibility.  It only
    says that a non-review primary-looking candidate has enough object and
    local evidence-role signal to justify spending a bounded full-text
    attempt.  It does not require the title/abstract to enumerate every
    causal-edge fragment.
    The post-fulltext source-bound causal-edge assessment remains the only
    authority for `import_eligible`, `core_eligible`, and standard-core quotas.
    """

    text = _fragment_anchor_candidate_text(candidate)
    coarse = coarse_subhypothesis_candidate_prefilter(candidate, alignment_contract)
    assessment = strict_assessment if isinstance(strict_assessment, dict) else {}
    genre = assessment.get("paper_genre") if isinstance(assessment.get("paper_genre"), dict) else {}
    if not genre:
        classification = (
            candidate.get("paper_classification")
            if isinstance(candidate.get("paper_classification"), dict)
            else {}
        )
        evidence_genre = str(classification.get("evidence_genre") or "unknown")
        genre = {
            "schema_version": "paper_genre_assessment_v2",
            "genre": evidence_genre,
            "evidence_genre": evidence_genre,
            "is_review": evidence_genre in {"systematic_review", "narrative_review", "contextual_synthesis"},
            "status": str(classification.get("status") or "CLASSIFICATION_PENDING"),
            "reason_codes": list(classification.get("reason_codes") or ["PAPER_CLASSIFICATION_REQUIRED"]),
        }
    publication_types = " ".join(str(item or "") for item in (candidate.get("publication_types") or []))
    publication_text = normalize_space(
        " ".join(
            str(candidate.get(key) or "")
            for key in ("publication_type", "type", "venue", "title")
        )
        + " "
        + publication_types
    ).lower()
    review_like = bool(genre.get("is_review")) or any(
        marker in publication_text
        for marker in ("review", "meta-analysis", "systematic review", "scoping review", "perspective", "editorial")
    )
    causal_axis_hits = coarse.get("causal_axis_hits") if isinstance(coarse.get("causal_axis_hits"), dict) else {}
    matched_axes = [
        str(axis)
        for axis, hits in causal_axis_hits.items()
        if isinstance(hits, list) and hits
    ]
    design_hits = [
        marker
        for marker in _PREFULLTEXT_IMPORT_DESIGN_OR_CAUSAL_MARKERS
        if marker in text
    ][:12]
    candidate_evidence_roles = [
        str(item)
        for item in (coarse.get("candidate_evidence_roles") or [])
        if str(item).strip()
    ][:16]
    evidence_role_signal = bool(coarse.get("evidence_role_signal"))
    strong_object_hits = [
        str(item)
        for item in (coarse.get("strong_object_hits") or coarse.get("object_hits") or [])
        if str(item).strip()
    ][:12]
    semantic_equivalent_object_hits = [
        str(item)
        for item in (coarse.get("semantic_equivalent_object_hits") or [])
        if str(item).strip()
    ][:12]
    legacy_recall_object_hits = [
        str(item)
        for item in (coarse.get("legacy_recall_object_hits") or [])
        if str(item).strip()
    ][:12]
    related_context_object_hits = [
        str(item)
        for item in (coarse.get("related_context_object_hits") or [])
        if str(item).strip()
    ][:12]
    panel_component_hits = [
        str(item)
        for item in (coarse.get("panel_component_hits") or [])
        if str(item).strip()
    ][:16]
    panel_component_support_only = bool(
        coarse.get("panel_component_support_only")
        or (coarse.get("panel_component_path") and panel_component_hits and not strong_object_hits)
    )
    component_bridge_hits = [
        str(item)
        for item in (coarse.get("component_bridge_object_hits") or [])
        if str(item).strip()
    ][:16]
    component_bridge_support_only = bool(
        coarse.get("component_bridge_support_only")
        or (
            coarse.get("object_maturity_component_bridge_path")
            and component_bridge_hits
            and not strong_object_hits
            and not semantic_equivalent_object_hits
        )
    )
    auxiliary_object_hits = [
        str(item)
        for item in (coarse.get("auxiliary_object_hits") or [])
        if str(item).strip()
    ][:12]
    exclusion_hits = [
        str(item)
        for item in (coarse.get("exclusion_hits") or [])
        if str(item).strip()
    ][:8]
    scope_forbidden_hits = [
        str(item)
        for item in (coarse.get("scope_forbidden_hits") or [])
        if str(item).strip()
    ][:8]
    missing: list[str] = []
    if not text:
        missing.append("missing_title_or_abstract_text")
    if review_like:
        missing.append("review_or_background_candidate")
    related_context_auxiliary_only = bool(
        related_context_object_hits
        and not strong_object_hits
        and not semantic_equivalent_object_hits
        and not panel_component_support_only
        and not component_bridge_support_only
    )
    if (
        not strong_object_hits
        and not semantic_equivalent_object_hits
        and not legacy_recall_object_hits
        and not related_context_object_hits
        and not panel_component_support_only
        and not component_bridge_support_only
    ):
        missing.append("strong_scientific_object_anchor_missing")
    if related_context_auxiliary_only and not (
        matched_axes or design_hits or evidence_role_signal
    ):
        missing.append("related_context_auxiliary_requires_local_evidence_role")
    if component_bridge_support_only and not (
        matched_axes or design_hits or evidence_role_signal
    ):
        missing.append("component_bridge_requires_local_evidence_role")
    input_support_state = str(coarse.get("input_support_state") or "")
    if not matched_axes and not design_hits and not evidence_role_signal:
        missing.append("local_evidence_role_or_design_signal_missing")
    if exclusion_hits:
        missing.append(
            "scope_forbidden_term_matched"
            if scope_forbidden_hits and not coarse.get("explicit_exclusion_hits")
            else "explicit_exclusion_matched"
        )
    eligible = bool(not missing)
    axis_set = set(matched_axes)
    provisional_lane = "PENDING_FULLTEXT_ROLE_EVIDENCE"
    if {"input", "mechanism"}.issubset(axis_set):
        provisional_lane = "INPUT_OR_CONDITION_EVIDENCE"
    elif {"mechanism", "outcome"}.issubset(axis_set):
        provisional_lane = "MECHANISM_LINK_EVIDENCE"
    elif {"input", "outcome"}.issubset(axis_set) or "outcome" in axis_set:
        provisional_lane = "OUTCOME_EVIDENCE"
    elif "mechanism" in axis_set:
        provisional_lane = "MECHANISM_LINK_EVIDENCE"
    elif "input" in axis_set:
        provisional_lane = "INPUT_OR_CONDITION_EVIDENCE"
    return {
        "schema_version": "prefulltext_import_candidate_gate_v1",
        "eligible": eligible,
        "admission_tier": "AUXILIARY_PENDING_FULLTEXT" if eligible else "REJECTED",
        "reason": (
            (
                "the candidate is object-aligned but its declared input is not visible in metadata; "
                "it is quarantined pending full-text confirmation and cannot support direct evidence claims yet"
            )
            if eligible and input_support_state != "INPUT_EXPLICITLY_SUPPORTED"
            else (
            (
                "component-level support with a local evidence role; full text may establish its precise "
                "role, but this metadata-only result cannot count as direct evidence"
            )
            if eligible and panel_component_support_only
            else (
                "component, bridge, or boundary support with a local evidence role; full text may establish "
                "its precise contribution, but this metadata-only result cannot count as direct evidence"
            )
            if eligible and component_bridge_support_only
            else (
                "related project-context object plus a local evidence role; full text may establish the "
                "contribution, but this metadata-only result cannot count as direct evidence"
            )
            if eligible and related_context_auxiliary_only
            else (
                "scientific-object anchor plus a local evidence role; full causal-edge and direct-evidence "
                "requirements are deferred to full text"
            )
            if eligible
            else "; ".join(missing)
            )
        ),
        "missing_requirements": missing,
        "non_review_primary_candidate": not review_like,
        "strong_object_hits": strong_object_hits,
        "semantic_equivalent_object_hits": semantic_equivalent_object_hits,
        "legacy_recall_object_hits": legacy_recall_object_hits,
        "related_context_object_hits": related_context_object_hits,
        "auxiliary_object_hits": auxiliary_object_hits,
        "related_context_auxiliary_only": related_context_auxiliary_only,
        "panel_component_hits": panel_component_hits,
        "panel_component_support_only": panel_component_support_only,
        "component_bridge_object_hits": component_bridge_hits,
        "component_bridge_support_only": component_bridge_support_only,
        "object_maturity_component_bridge_path": bool(coarse.get("object_maturity_component_bridge_path")),
        "panel_component_path": bool(coarse.get("panel_component_path")),
        "panel_evidence_tier": str(coarse.get("panel_evidence_tier") or ""),
        "matched_axes": matched_axes,
        "candidate_evidence_roles": candidate_evidence_roles,
        "evidence_role_signal": evidence_role_signal,
        "causal_axis_hits": {
            axis: list(hits)[:8]
            for axis, hits in causal_axis_hits.items()
            if isinstance(hits, list)
        },
        "design_or_causal_signal_hits": design_hits,
        "exclusion_hits": exclusion_hits,
        "scope_forbidden_hits": scope_forbidden_hits,
        "input_support_state": input_support_state or "INPUT_EXPLICITLY_SUPPORTED",
        "requires_fulltext_input_confirmation": bool(
            input_support_state != "INPUT_EXPLICITLY_SUPPORTED"
        ),
        "direct_edge_candidate": False,
        "direct_edge_confirmed": False,
        "evidence_admission_state": "PENDING_FULLTEXT_ROLE_VERIFICATION" if eligible else "REJECTED",
        "provisional_evidence_role": (
            "panel_component_support"
            if panel_component_support_only
            else "component_or_boundary_support"
            if component_bridge_support_only
            else "related_context_support"
            if related_context_auxiliary_only
            else "unverified_local_role"
        ),
        "provisional_evidence_lane": (
            "PANEL_COMPONENT_SUPPORT_EVIDENCE"
            if panel_component_support_only
            else "OBJECT_MATURITY_COMPONENT_BRIDGE_EVIDENCE"
            if component_bridge_support_only
            else "TOPIC_ALIGNED_EXPERIMENTAL_AUXILIARY_EVIDENCE"
            if related_context_auxiliary_only
            else provisional_lane
        ),
        "source_bound_hard_gate_deferred": True,
        "fulltext_review_required_for_import_or_core": True,
        "component_evidence_counts_as_panel_core": False if panel_component_support_only else None,
        "direct_core_disallowed_by_object_maturity": True if component_bridge_support_only else None,
        "coarse_prefilter": coarse,
    }


def evaluate_candidate_targeted_alignment_gate(
    candidate: dict[str, Any],
    *,
    alignment_contract: dict[str, Any] | None,
    requested_evidence_kind: str = "",
    requested_evidence_kinds: list[str] | tuple[str, ...] | None = None,
    admission_level: str = "import",
) -> tuple[bool, dict[str, Any], bool]:
    """Admit a scope-aligned candidate for import/full-text verification.

    This is deliberately an admission gate, not a direct-evidence verdict.
    Abstract-level alignment may identify a promising direct-edge *candidate*,
    but it cannot confirm all fragments of an edge.  Confirmation remains a
    full-text, source-bound decision after import.
    """
    if not isinstance(alignment_contract, dict) or not alignment_contract:
        return True, {}, True
    normalized_admission_level = str(admission_level or "import").strip().lower()
    if normalized_admission_level not in {"core", "import"}:
        normalized_admission_level = "import"
    if _is_v3_slot_candidate_scope(alignment_contract):
        assessment = _v3_slot_candidate_scope_assessment(candidate, alignment_contract)
        record = _candidate_score_record(candidate)
        assessments = record.setdefault("targeted_alignment_assessments", {})
        scope_key = _v3_slot_candidate_scope_key(alignment_contract)
        assessments[scope_key] = dict(assessment)
        record["targeted_alignment_assessments"] = assessments
        candidate["targeted_alignment_admission"] = dict(assessment)
        candidate["candidate_score_record"] = record
        return (
            bool(assessment.get("passes")) and normalized_admission_level != "core",
            assessment,
            False,
        )

    # V3 retrieval deliberately has no compatibility path to the historical
    # project-context -> object -> causal-edge assessor.  A caller that has a
    # research contract must compile its declared slot into a task-local scope
    # before discovery; silently interpreting that contract as V1 created the
    # blanket metadata rejection observed in the GroupChat run.
    return False, _v3_slot_scope_required_assessment(alignment_contract), False

    try:
        from ._research_alignment import assess_candidate_alignment_across_matched_evidence_lanes
    except ImportError:
        from _research_alignment import assess_candidate_alignment_across_matched_evidence_lanes
    record = _candidate_score_record(candidate)
    assessments = record.setdefault("targeted_alignment_assessments", {})
    contract_hash = str(alignment_contract.get("contract_hash") or "unversioned_contract")
    forced_kinds = [
        str(kind or "").strip().lower()
        for kind in (requested_evidence_kinds or [])
        if str(kind or "").strip()
    ]
    if not forced_kinds and requested_evidence_kind:
        forced_kinds = [str(requested_evidence_kind or "").strip().lower()]
    def normalize_pending_import_assessment(
        raw_assessment: dict[str, Any],
    ) -> tuple[bool, dict[str, Any]]:
        """Convert every pre-import candidate into a full-text pending state.

        `core_eligible` from the semantic assessor is retained separately as
        an abstract-level ranking signal.  It must never be presented as an
        already-confirmed direct edge before source passages are inspected.
        """
        normalized_assessment = dict(raw_assessment)
        strict_core_eligible = bool(
            normalized_assessment.get(
                "strict_core_eligible",
                normalized_assessment.get("core_eligible"),
            )
        )
        strict_import_eligible = bool(
            normalized_assessment.get(
                "strict_import_eligible",
                normalized_assessment.get("import_eligible"),
            )
        ) and str(normalized_assessment.get("evidence_lane") or "") != "BACKGROUND_REVIEW"
        prefulltext_eligible = bool(
            normalized_assessment.get("prefulltext_import_eligible")
        )
        admitted_for_fulltext = bool(
            strict_core_eligible
            or strict_import_eligible
            or prefulltext_eligible
        )
        if admitted_for_fulltext:
            normalized_assessment.update(
                {
                    "strict_core_eligible": strict_core_eligible,
                    "strict_import_eligible": strict_import_eligible,
                    "abstract_direct_edge_candidate": strict_core_eligible,
                    "direct_edge_candidate": strict_core_eligible,
                    "direct_edge_confirmed": False,
                    # The full-text pipeline will re-assess this field from
                    # source passages.  Prevent metadata-only eligibility
                    # from consuming a direct-evidence/core quota.
                    "core_eligible": False,
                    "admission_tier": "AUXILIARY_PENDING_FULLTEXT",
                    "pending_full_text_verification": True,
                    "detail_revalidation_required": True,
                    "evidence_admission_state": "PENDING_FULLTEXT_ROLE_VERIFICATION",
                }
            )
        return admitted_for_fulltext, normalized_assessment
    cache_key = (
        f"{contract_hash}:{'|'.join(forced_kinds) if forced_kinds else 'unspecified'}:"
        f"{normalized_admission_level}"
    )
    cached = assessments.get(cache_key)
    if isinstance(cached, dict):
        assessment = dict(cached)
        assessment["alignment_admission_memo_hit"] = True
        assessment["alignment_admission_memo_scope"] = "candidate_record"
        if normalized_admission_level == "import":
            admitted, assessment = normalize_pending_import_assessment(assessment)
            assessments[cache_key] = dict(assessment)
            record["targeted_alignment_assessments"] = assessments
        else:
            admitted = bool(assessment.get("core_eligible"))
        candidate["targeted_alignment_admission"] = assessment
        candidate["candidate_score_record"] = record
        return admitted, assessment, True
    memo_key = _alignment_admission_memo_key(
        candidate,
        alignment_contract,
        requested_evidence_kinds=forced_kinds,
        admission_level=normalized_admission_level,
    )
    memo_cached = _bounded_memo_get(
        ALIGNMENT_ADMISSION_MEMO,
        ALIGNMENT_ADMISSION_MEMO_LOCK,
        memo_key,
    )
    if isinstance(memo_cached, dict):
        assessment = dict(memo_cached)
        assessment["alignment_admission_memo_hit"] = True
        assessment["alignment_admission_memo_scope"] = "paper_sh_contract"
        assessment["alignment_admission_memo_key_hash"] = hashlib.sha256(
            memo_key.encode("utf-8")
        ).hexdigest()[:16]
        if normalized_admission_level == "import":
            admitted, assessment = normalize_pending_import_assessment(assessment)
        else:
            admitted = bool(assessment.get("core_eligible"))
        assessments[cache_key] = dict(assessment)
        record["targeted_alignment_assessments"] = assessments
        candidate["targeted_alignment_admission"] = assessment
        candidate["candidate_score_record"] = record
        return admitted, assessment, True
    assessment = assess_candidate_alignment_across_matched_evidence_lanes(
        candidate,
        alignment_contract,
        requested_evidence_kinds=forced_kinds or None,
    )
    assessment = dict(assessment)
    is_core = bool(assessment.get("core_eligible"))
    is_strict_import_auxiliary = bool(
        assessment.get("import_eligible")
        and str(assessment.get("evidence_lane") or "") != "BACKGROUND_REVIEW"
    )
    prefulltext_import_assessment: dict[str, Any] = {}
    prefulltext_import_eligible = False
    if normalized_admission_level == "import" and not is_core and not is_strict_import_auxiliary:
        prefulltext_import_assessment = prefulltext_import_candidate_assessment(
            candidate,
            alignment_contract,
            strict_assessment=assessment,
        )
        prefulltext_import_eligible = bool(prefulltext_import_assessment.get("eligible"))
    assessment["admission_level"] = normalized_admission_level
    assessment["strict_core_eligible"] = is_core
    assessment["strict_import_eligible"] = bool(assessment.get("import_eligible"))
    assessment["prefulltext_import_eligible"] = prefulltext_import_eligible
    if prefulltext_import_assessment:
        assessment["prefulltext_import_assessment"] = prefulltext_import_assessment
        assessment["pending_fulltext_reason"] = str(prefulltext_import_assessment.get("reason") or "")
        if prefulltext_import_eligible:
            assessment["prefulltext_provisional_evidence_lane"] = str(
                prefulltext_import_assessment.get("provisional_evidence_lane") or ""
            )
            assessment["reason"] = str(prefulltext_import_assessment.get("reason") or assessment.get("reason") or "")
    if normalized_admission_level == "import":
        admitted, assessment = normalize_pending_import_assessment(assessment)
    else:
        assessment["admission_tier"] = (
            "CORE"
            if is_core
            else "BACKGROUND"
            if assessment.get("import_eligible")
            else "REJECTED"
        )
        assessment["direct_edge_candidate"] = is_core
        assessment["direct_edge_confirmed"] = False
        admitted = is_core
    assessment["alignment_admission_memo_hit"] = False
    assessment["alignment_admission_memo_scope"] = "computed"
    assessment["alignment_admission_memo_summary"] = _alignment_memo_content_summary(
        assessment
    )
    assessments[cache_key] = dict(assessment)
    record["targeted_alignment_assessments"] = assessments
    candidate["targeted_alignment_admission"] = dict(assessment)
    candidate["candidate_score_record"] = record
    _bounded_memo_put(
        ALIGNMENT_ADMISSION_MEMO,
        ALIGNMENT_ADMISSION_MEMO_LOCK,
        memo_key,
        assessment,
        max_size=ALIGNMENT_ADMISSION_MEMO_MAX,
    )
    return admitted, assessment, False


def _is_v3_slot_candidate_scope(value: Any) -> bool:
    return bool(
        isinstance(value, dict)
        and str(value.get("schema_version") or "") == "slot_candidate_scope_v3"
    )


def _v3_slot_scope_required_assessment(value: Any) -> dict[str, Any]:
    """Return a V3 contract-compilation diagnostic, never a legacy fallback."""
    contract = value if isinstance(value, dict) else {}
    return {
        "schema_version": "slot_candidate_scope_assessment_v3",
        "passes": False,
        "reason_code": "V3_SLOT_CANDIDATE_SCOPE_REQUIRED",
        "reason": (
            "Project sub-hypothesis retrieval requires an explicit V3 slot candidate "
            "scope compiled from its ResearchQuestionContractV3 task."
        ),
        "admission_tier": "REJECTED",
        "pending_full_text_verification": False,
        "detail_revalidation_required": False,
        "evidence_admission_state": "REJECTED",
        "core_eligible": False,
        "import_eligible": False,
        "direct_edge_candidate": False,
        "direct_edge_confirmed": False,
        "source_bound_hard_gate_deferred": True,
        "fulltext_review_required_for_import_or_core": True,
        "v1_causal_alignment_applied": False,
        "research_question_contract_id": str(
            contract.get("research_question_contract_id") or contract.get("contract_id") or ""
        ),
        "research_question_contract_hash": str(
            contract.get("research_question_contract_hash")
            or contract.get("contract_hash")
            or ""
        ),
    }


def _v3_slot_candidate_scope_key(scope: dict[str, Any]) -> str:
    payload = {
        "contract": str(scope.get("research_question_contract_hash") or ""),
        "sub_hypothesis_id": str(scope.get("sub_hypothesis_id") or ""),
        "evidence_slot": str(scope.get("evidence_slot") or ""),
        "query_branch": str(scope.get("query_branch") or ""),
    }
    return "v3_slot:" + hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()[:24]


def _v3_slot_candidate_scope_assessment(
    candidate: dict[str, Any],
    scope: dict[str, Any],
) -> dict[str, Any]:
    """Apply the V3 metadata-only scope gate for one retrieval slot.

    This gate deliberately consumes only task-local query anchors.  It does
    not read project context, a causal model, object-maturity metadata, or a
    legacy evidence lane.  A pass admits a paper to full-text inspection; the
    assertion pipeline remains the sole authority for direct typed evidence.
    """

    text = _fragment_anchor_candidate_text(candidate)
    groups = (
        scope.get("scope_anchor_groups")
        if isinstance(scope.get("scope_anchor_groups"), dict)
        else {}
    )
    blueprint = (
        scope.get("query_blueprint_v3")
        if isinstance(scope.get("query_blueprint_v3"), dict)
        else {}
    )
    query_ast = (
        blueprint.get("query_ast_v3")
        if isinstance(blueprint.get("query_ast_v3"), dict)
        else {}
    )

    def values(value: Any) -> list[str]:
        raw = value if isinstance(value, (list, tuple, set)) else [value]
        return list(dict.fromkeys(
            normalize_space(str(item or ""))
            for item in raw
            if normalize_space(str(item or ""))
        ))

    object_anchors = values(groups.get("research_object"))
    slot_anchors = values(scope.get("slot_anchors"))
    topic_anchors = values(
        [
            *values(groups.get("target_construct")),
            *values(groups.get("measurement_or_outcome")),
        ]
    )
    measurement_method_anchors = values(groups.get("measurement_method"))
    context_anchors = values(
        [
            *values(groups.get("population_or_system")),
            *values(groups.get("condition_or_regime")),
            *values(groups.get("sample_or_model")),
        ]
    )
    required_slot_terms = values([
        term
        for item in query_ast.get("all_of", [])
        if isinstance(item, dict) and str(item.get("role") or "") == "slot_requirement"
        for term in values(item.get("terms"))
    ])
    slot_anchors = values([*slot_anchors, *required_slot_terms])
    explicit_exclusions = values(
        [
            *values(scope.get("explicit_exclusion_terms")),
            *values(query_ast.get("exclusions")),
        ]
    )

    def matched(anchors: list[str]) -> list[str]:
        return [anchor for anchor in anchors if _anchor_phrase_matches_candidate(anchor, text)]

    object_hits = matched(object_anchors)
    slot_hits = matched(slot_anchors)
    topic_hits = matched(topic_anchors)
    measurement_method_hits = matched(measurement_method_anchors)
    context_hits = matched(context_anchors)
    exclusion_hits = matched(explicit_exclusions)
    declared_anchors = values([
        *object_anchors,
        *slot_anchors,
        *topic_anchors,
        *measurement_method_anchors,
        *context_anchors,
    ])
    anchor_hits = values([
        *object_hits,
        *slot_hits,
        *topic_hits,
        *measurement_method_hits,
        *context_hits,
    ])
    passes = bool(text) and not exclusion_hits and (
        not declared_anchors or bool(anchor_hits)
    )
    reason = (
        "V2_SLOT_SCOPE_TEXT_MISSING"
        if not text
        else "V2_SLOT_SCOPE_EXPLICIT_EXCLUSION"
        if exclusion_hits
        else "V2_SLOT_SCOPE_ANCHOR_MISSING"
        if declared_anchors and not anchor_hits
        else "V2_SLOT_SCOPE_METADATA_ADMITTED"
    )
    return {
        "schema_version": "slot_candidate_scope_assessment_v3",
        "passes": passes,
        "reason_code": reason,
        "reason": (
            "Current V3 slot has metadata anchor support; full-text, source-span, "
            "explicit-assertion, and typed-slot admission remain required."
            if passes
            else "Current V3 slot lacks the declared metadata scope signal."
        ),
        "admission_tier": "AUXILIARY_PENDING_FULLTEXT" if passes else "REJECTED",
        "pending_full_text_verification": bool(passes),
        "detail_revalidation_required": bool(passes),
        "evidence_admission_state": (
            "PENDING_FULLTEXT_ROLE_VERIFICATION" if passes else "REJECTED"
        ),
        "core_eligible": False,
        "import_eligible": bool(passes),
        "direct_edge_candidate": False,
        "direct_edge_confirmed": False,
        "source_bound_hard_gate_deferred": True,
        "fulltext_review_required_for_import_or_core": True,
        "v1_causal_alignment_applied": False,
        "v2_scope_anchor_hits": anchor_hits,
        "strong_object_hits": object_hits,
        "semantic_equivalent_object_hits": [],
        "related_context_object_hits": [],
        "auxiliary_object_hits": [],
        "matched_axes": list(scope.get("slot_focus_axes") or []),
        "slot_anchor_hits": slot_hits,
        "topic_anchor_hits": topic_hits,
        "measurement_method_hits": measurement_method_hits,
        "context_anchor_hits": context_hits,
        "exclusion_hits": exclusion_hits,
        "scope_forbidden_hits": exclusion_hits,
        "evidence_slot": str(scope.get("evidence_slot") or ""),
        "query_branch": str(scope.get("query_branch") or ""),
        "research_question_contract_id": str(
            scope.get("research_question_contract_id") or ""
        ),
        "research_question_contract_hash": str(
            scope.get("research_question_contract_hash") or ""
        ),
    }


def _fragment_anchor_candidate_text(candidate: dict[str, Any]) -> str:
    """Return bounded candidate text for pre-import retrieval admission."""
    values: list[Any] = []
    payload = candidate.get("papergraph_input") if isinstance(candidate.get("papergraph_input"), dict) else {}
    for key in ("title", "abstract", "conclusion", "method", "results", "full_text_excerpt"):
        values.append(candidate.get(key) or payload.get(key) or "")
    return normalize_space(" ".join(str(item or "") for item in values)).lower()


def _anchor_phrase_matches_candidate(phrase: str, text: str) -> bool:
    normalized = normalize_space(phrase).lower()
    if not normalized:
        return False
    if normalized in text:
        return True
    tokens = [token for token in re.findall(r"[a-z0-9_+\-./]+", normalized) if len(token) > 2]
    if not tokens:
        return False
    # Preserve the distinction between an anchor phrase and one generic word:
    # a multi-token anchor needs two matching informative tokens, while a
    # genuinely atomic technical identifier may match by itself.
    required = 1 if len(tokens) == 1 else min(2, len(tokens))
    return sum(1 for token in tokens if token in text) >= required


def _strong_object_anchor_matches_candidate(phrase: str, text: str) -> bool:
    """Match object identity anchors without bag-of-words leakage.

    Causal-axis anchors can be fuzzy because they only provide a recall
    signal.  Strong object anchors are different: component words appearing
    far apart must not prove the declared multi-word object.  Multi-token
    object anchors therefore require an exact normalized phrase (with
    dash/spacing variants); only true atomic anchors use the legacy
    single-token matcher.
    """

    normalized = normalize_space(phrase).lower()
    if not normalized:
        return False
    if " " not in normalized:
        return _anchor_phrase_matches_candidate(normalized, text)
    comparable_text = normalize_space(
        re.sub(r"[\u2010-\u2015\u2212]", "-", str(text or "").lower())
    )
    comparable_space_text = normalize_space(comparable_text.replace("-", " "))
    comparable_anchor = normalize_space(
        re.sub(r"[\u2010-\u2015\u2212]", "-", normalized)
    )
    variants = {
        comparable_anchor,
        normalize_space(comparable_anchor.replace("-", " ")),
    }
    if "-based" in comparable_anchor:
        variants.add(normalize_space(comparable_anchor.replace("-based", " based")))
    if " based " in comparable_anchor:
        variants.add(normalize_space(comparable_anchor.replace(" based ", "-based ")))
    def bounded_phrase_present(variant: str, haystack: str) -> bool:
        if not variant:
            return False
        return re.search(
            rf"(?<![a-z0-9]){re.escape(variant)}(?![a-z0-9])",
            haystack,
        ) is not None

    return any(
        bounded_phrase_present(variant, comparable_text)
        or bounded_phrase_present(variant, comparable_space_text)
        for variant in variants
    )


def evaluate_candidate_fragment_anchor_gate(
    candidate: dict[str, Any],
    *,
    retrieval_anchor_contract: dict[str, Any] | None,
) -> tuple[bool, dict[str, Any], bool]:
    """Require one candidate-local anchor group from the retrieval branch.

    This does not claim that an imported candidate is final direct evidence;
    the post-import fragment audit remains stricter.  A retrieval branch can
    intentionally seek one fragment of an edge, so requiring every declared
    group here would turn a multi-paper evidence bundle into an impossible
    one-paper prerequisite.
    """
    anchors = retrieval_anchor_contract if isinstance(retrieval_anchor_contract, dict) else {}
    if not anchors.get("valid"):
        return False, {"reason": "invalid_retrieval_anchor_contract", "passes": False}, True
    record = _candidate_score_record(candidate)
    assessments = record.setdefault("fragment_anchor_assessments", {})
    contract_key = hashlib.sha256(
        json.dumps(
            {
                "groups": anchors.get("required_anchor_groups"),
                "terms": anchors.get("allowed_query_terms"),
            },
            sort_keys=True,
            default=str,
        ).encode("utf-8")
    ).hexdigest()[:20]
    cached = assessments.get(contract_key)
    if isinstance(cached, dict):
        candidate["fragment_anchor_admission"] = dict(cached)
        candidate["candidate_score_record"] = record
        return bool(cached.get("passes")), dict(cached), True
    text = _fragment_anchor_candidate_text(candidate)
    group_results: list[dict[str, Any]] = []
    for group in retrieval_anchor_group_forms(anchors):
        phrases = [str(value) for value in group if str(value).strip()]
        hits = [phrase for phrase in phrases if _anchor_phrase_matches_candidate(phrase, text)]
        group_results.append({"anchors": phrases, "hits": hits, "passes": bool(hits)})
    matched_group_count = sum(1 for item in group_results if item["passes"])
    passed = bool(group_results) and bool(matched_group_count)
    assessment = {
        "version": "fragment_compatible_retrieval_anchor_v2",
        "passes": passed,
        "group_results": group_results,
        "matched_group_count": matched_group_count,
        "missing_group_count": max(0, len(group_results) - matched_group_count),
        "fragment_role_status": (
            "LOCAL_BRANCH_FRAGMENT_FOUND"
            if passed
            else "NO_LOCAL_BRANCH_FRAGMENT_FOUND"
        ),
        "direct_edge_confirmed": False,
        "reason": (
            "Candidate contains at least one local anchor group compatible with this retrieval branch; "
            "remaining edge fragments require full-text evidence assembly."
            if passed else
            "Candidate lacks any source-compatible local anchor group for this retrieval branch."
        ),
    }
    assessments[contract_key] = dict(assessment)
    record["fragment_anchor_assessments"] = assessments
    candidate["fragment_anchor_admission"] = dict(assessment)
    candidate["candidate_score_record"] = record
    return passed, assessment, False


def rank_literature_results(query: str, results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    try:
        from ._literature_scoring import literature_relevance_score, publication_quality_assessment
    except ImportError:
        from _literature_scoring import literature_relevance_score, publication_quality_assessment
    stage_started = time.perf_counter()
    quality_elapsed_ms = 0.0
    relevance_elapsed_ms = 0.0
    quality_cache_hits = 0
    ranking_cache_hits = 0
    scored: list[dict[str, Any]] = []
    ranking_context = _scoring_context_key(query)
    for original_index, item in enumerate(results):
        ranked = dict(item)
        record = _candidate_score_record(ranked)
        quality = record.get("quality")
        if isinstance(quality, dict) and quality.get("quality_score") is not None:
            quality_cache_hits += 1
        else:
            quality_started = time.perf_counter()
            quality = publication_quality_assessment(ranked)
            quality_elapsed_ms += (time.perf_counter() - quality_started) * 1000.0
            record["quality"] = dict(quality)
        _apply_quality_assessment(ranked, quality)

        ranking_assessments = dict(record.get("ranking_assessments") or {})
        assessment = ranking_assessments.get(ranking_context)
        if isinstance(assessment, dict):
            ranking_cache_hits += 1
        else:
            relevance_started = time.perf_counter()
            score, matched, reason, components = literature_relevance_score(
                query,
                ranked,
                quality_assessment=quality,
            )
            relevance_elapsed_ms += (time.perf_counter() - relevance_started) * 1000.0
            assessment = {
                "query": normalize_space(query),
                "score": score,
                "matched_terms": list(matched),
                "reason": reason,
                "components": dict(components),
            }
            ranking_assessments[ranking_context] = assessment
            record["ranking_assessments"] = ranking_assessments
        _apply_ranking_assessment(ranked, assessment)
        ranked["candidate_score_record"] = record
        ranked["_original_index"] = original_index
        scored.append(ranked)
    scored.sort(key=lambda item: (-float(item.get("relevance_score", 0.0)), int(item.get("_original_index", 0))))
    for item in scored:
        item.pop("_original_index", None)
    log_event(
        "SCIENCE",
        "literature_search_stage_timing",
        stage="rank_quality",
        candidates=len(results),
        elapsed_ms=round((time.perf_counter() - stage_started) * 1000.0, 3),
        quality_elapsed_ms=round(quality_elapsed_ms, 3),
        relevance_elapsed_ms=round(relevance_elapsed_ms, 3),
        quality_cache_hits=quality_cache_hits,
        ranking_cache_hits=ranking_cache_hits,
    )
    return scored

def select_literature_result(
    search_id: str,
    query: str = "",
    top_k: int = 5,
    use_llm: bool | None = None,
) -> str:
    try:
        from ._literature_import import import_literature_search_result
        from ._project import load_search, save_search
        from ._utils import clamp_int, find_by_id
    except ImportError:
        from _literature_import import import_literature_search_result
        from _project import load_search, save_search
        from _utils import clamp_int, find_by_id
    search_record = load_search(search_id)
    results = search_record.get("results", [])
    if query:
        # Keep result_index stable. Pipelines hold these indexes while they
        # import their stratified candidates; rewriting the cached ordering
        # here can turn an L3 preprint import into an unrelated L0/L4 record.
        results = rank_literature_results(query, [result for result in results if isinstance(result, dict)])
    ranked = [result for result in results if isinstance(result, dict)]
    if not ranked:
        return json.dumps(
            {
                "search_id": search_id,
                "selected": None,
                "top_results": [],
                "next_step": "No retrieved papers are available. Stop and report retrieval failure.",
            },
            ensure_ascii=False,
            indent=2,
        )
    limit = clamp_int(top_k, 1, 20)
    selected, root_selection_policy = choose_seed_with_review_root_policy(search_record, ranked)
    llm_judgement: dict[str, Any] | None = None
    if use_llm:
        llm_judgement = judge_literature_candidates_with_llm(
            query or str(search_record.get("query", "")),
            ranked[:limit],
        )
        chosen_index = llm_judgement.get("selected_result_index")
        chosen = find_by_id(ranked, "result_index", chosen_index) if chosen_index is not None else None
        if chosen is not None:
            root_candidate = pyramid_root_from_search_record(search_record, ranked)
            if root_candidate is None or chosen_is_allowed_seed_override(chosen, root_candidate):
                selected = chosen
                root_selection_policy = "LLM selected a candidate allowed by the review-root override policy."
            else:
                root_selection_policy = (
                    "LLM selected a non-review candidate, but the review-root policy kept the high-impact "
                    "review as seed because the candidate was not a clearly superior flagship override."
                )
    summary = {
        "search_id": search_id,
        "selected": summarize_literature_result(selected),
        "root_selection_policy": root_selection_policy,
        "knowledge_pyramid": search_record.get("knowledge_pyramid"),
        "top_results": [summarize_literature_result(result) for result in ranked[:limit]],
        "llm_judgement": llm_judgement,
        "next_step": "Import selected.result_index with import_literature_search_result, or choose another top_results item.",
    }
    return json.dumps(summary, ensure_ascii=False, indent=2)

def choose_seed_with_review_root_policy(
    search_record: dict[str, Any],
    ranked: list[dict[str, Any]],
) -> tuple[dict[str, Any], str]:
    root = pyramid_root_from_search_record(search_record, ranked)
    if root is None:
        return ranked[0], "No review root was available; selected the rule-ranked top result."
    challenger = ranked[0]
    if result_identity(challenger) != result_identity(root) and chosen_is_allowed_seed_override(challenger, root):
        return (
            challenger,
            "Selected the rule-ranked top result because it clearly overrides the review root "
            "under the Nature/Science/Cell/PNAS flagship-impact exception.",
        )
    return (
        root,
        "Selected the high-impact review as the seed/root for knowledge-graph expansion.",
    )

def pyramid_root_from_search_record(
    search_record: dict[str, Any],
    ranked: list[dict[str, Any]],
) -> dict[str, Any] | None:
    try:
        from ._utils import find_by_id
    except ImportError:
        from _utils import find_by_id
    pyramid = search_record.get("knowledge_pyramid") if isinstance(search_record, dict) else None
    root_index = pyramid.get("root_result_index") if isinstance(pyramid, dict) else None
    root = find_by_id(ranked, "result_index", root_index) if root_index is not None else None
    if root is not None:
        return root
    return choose_pyramid_review_root(ranked)

def chosen_is_allowed_seed_override(chosen: dict[str, Any], review_root: dict[str, Any]) -> bool:
    try:
        from ._literature_scoring import literature_impact_score
        from ._utils import numeric_value
    except ImportError:
        from _literature_scoring import literature_impact_score
        from _utils import numeric_value
    if result_identity(chosen) == result_identity(review_root):
        return True
    if is_review_like_paper(chosen):
        return pyramid_root_score(chosen) >= pyramid_root_score(review_root)
    if not is_flagship_root_override_candidate(chosen):
        return False
    chosen_impact = literature_impact_score(chosen)
    root_impact = literature_impact_score(review_root)
    chosen_quality = float(chosen.get("publication_quality_score") or 0.0)
    root_quality = float(review_root.get("publication_quality_score") or 0.0)
    chosen_citations = numeric_value(chosen.get("citation_count"))
    root_citations = numeric_value(review_root.get("citation_count"))
    return (
        chosen_quality >= root_quality + 0.08
        and chosen_impact >= max(0.85, root_impact + 0.18)
        and chosen_citations >= max(100.0, root_citations * 1.5)
    )

def is_flagship_root_override_candidate(item: dict[str, Any]) -> bool:
    try:
        from ._models import FLAGSHIP_ROOT_OVERRIDE_VENUES
        from ._utils import normalize_space
    except ImportError:
        from _models import FLAGSHIP_ROOT_OVERRIDE_VENUES
        from _utils import normalize_space
    venue = normalize_space(item.get("venue", "")).lower()
    if venue in FLAGSHIP_ROOT_OVERRIDE_VENUES:
        return True
    return any(venue.startswith(f"{name} ") for name in FLAGSHIP_ROOT_OVERRIDE_VENUES)

def result_identity(item: dict[str, Any]) -> Any:
    try:
        from ._utils import normalize_space
    except ImportError:
        from _utils import normalize_space
    return (
        item.get("result_index"),
        normalize_space(item.get("doi", "")).lower(),
        normalize_space(item.get("arxiv_id", "")).lower(),
        normalize_space(item.get("openalex_id", "")).lower(),
        normalize_space(item.get("title", "")).lower(),
    )

def summarize_literature_results(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [summarize_literature_result(result) for result in results if isinstance(result, dict)]

def summarize_provider_blocks(provider_blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    for block in provider_blocks:
        results = block.get("results", [])
        summaries.append(
            {
                "provider": block.get("provider"),
                "query": block.get("query"),
                "status": block.get("status"),
                "note": block.get("note"),
                "error": block.get("error"),
                "result_count": len(results) if isinstance(results, list) else 0,
                "scanned_result_count": block.get("scanned_result_count"),
                "scan_budget": block.get("scan_budget"),
                "zero_result_cache_hit": bool(block.get("zero_result_cache_hit")),
                "query_branch": block.get("query_branch", ""),
                "query_variant_reason": block.get("query_variant_reason", ""),
                "skipped_provider_reason": block.get("skipped_provider_reason", ""),
            }
        )
    return summaries

def summarize_literature_result(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "result_index": result.get("result_index"),
        "stratified_layer": result.get("stratified_layer", ""),
        "stratified_label": result.get("stratified_label", ""),
        "query_branch": result.get("query_branch", ""),
        "primary_query_branch": result.get("primary_query_branch", result.get("query_branch", "")),
        "matched_query_branches": result.get("matched_query_branches", []),
        "matched_evidence_kinds": result.get("matched_evidence_kinds", []),
        "branch_raw_hit_counts": result.get("branch_raw_hit_counts", {}),
        "retrieval_query": result.get("retrieval_query", ""),
        "_why_selected": result.get("_why_selected", ""),
        "targeted_admission_tier": result.get("targeted_admission_tier", ""),
        "pending_full_text_verification": bool(
            result.get("pending_full_text_verification")
        ),
        "targeted_alignment_admission": result.get("targeted_alignment_admission", {}),
        "prefulltext_import_eligible": bool(
            (
                result.get("targeted_alignment_admission")
                if isinstance(result.get("targeted_alignment_admission"), dict)
                else {}
            ).get("prefulltext_import_eligible")
        ),
        "research_role": result.get("research_role", ""),
        "research_role_assessment": result.get("research_role_assessment", {}),
        "domain_relevance": result.get("domain_relevance", {}),
        "relevance_score": result.get("relevance_score"),
        "relevance_components": result.get("relevance_components", {}),
        "publication_quality_score": result.get("publication_quality_score"),
        "venue_quality": result.get("venue_quality"),
        "journal_quartile": result.get("journal_quartile", ""),
        "journal_metric_source": result.get("journal_metric_source", ""),
        "venue_evidence": result.get("venue_evidence", {}),
        "venue_tier": result.get("venue_tier", {}),
        "venue_metadata_enrichment": result.get("venue_metadata_enrichment", {}),
        "inferred_field": result.get("inferred_field", ""),
        "quality_flags": result.get("quality_flags", []),
        "quality_criteria": result.get("quality_criteria", []),
        "suspicion_type": result.get("suspicion_type", ""),
        "is_review_like": is_review_like_paper(result),
        "pyramid_root_score": pyramid_root_score(result),
        "matched_query_terms": result.get("matched_query_terms", []),
        "title": result.get("title"),
        "citation": result.get("citation"),
        "provider": result.get("provider"),
        "discovery_providers": result.get("discovery_providers", []),
        "year": result.get("year"),
        "venue": result.get("venue"),
        "venue_metadata": result.get("venue_metadata", {}),
        "publication_types": result.get("publication_types", []),
        "citation_count": result.get("citation_count"),
        "influential_citation_count": result.get("influential_citation_count"),
        "doi": result.get("doi"),
        "arxiv_id": result.get("arxiv_id"),
        "openalex_id": result.get("openalex_id"),
        "url": result.get("url"),
        "external_ids": result.get("external_ids", {}),
        "citation_metrics": result.get("citation_metrics", {}),
        "semantic_scholar_local_layer": result.get("semantic_scholar_local_layer", ""),
        "semantic_scholar_local_stratification": result.get("semantic_scholar_local_stratification", {}),
        "relevance_reason": result.get("relevance_reason"),
        "quality_reason": result.get("quality_reason"),
    }

def judge_literature_candidates_with_llm(query: str, candidates: list[dict[str, Any]]) -> dict[str, Any]:
    try:
        from ._llm import call_llm_json
        from ._utils import scalar
    except ImportError:
        from _llm import call_llm_json
        from _utils import scalar
    if not candidates:
        return {"status": "empty", "selected_result_index": None, "reason": "No candidates."}
    try:
        raw = call_llm_json(
            system="You are a strict scientific literature selection judge. Select only from the provided result_index values.",
            prompt=(
                "Choose the best paper for the research query. Prefer direct topical fit, peer-reviewed/reputable venue, "
                "non-suspicious publication channel, citation impact, and recentness. Penalize tangential keyword matches.\n"
                "Return JSON only with: selected_result_index, reason, rejected_indices, quality_warnings.\n\n"
                f"Query: {query}\n\nCandidates:\n"
                + json.dumps([summarize_literature_result(item) for item in candidates], ensure_ascii=False, indent=2)
            ),
            max_tokens=1200,
        )
    except Exception as exc:
        return {
            "status": "fallback",
            "selected_result_index": candidates[0].get("result_index"),
            "reason": f"LLM judge failed: {exc}; used rule-ranked top result.",
            "quality_warnings": [],
        }
    allowed = {item.get("result_index") for item in candidates}
    selected = raw.get("selected_result_index")
    if selected not in allowed:
        selected = candidates[0].get("result_index")
        raw["reason"] = f"Invalid LLM selection; used rule-ranked top result. Original reason: {raw.get('reason', '')}"
    return {
        "status": "ok",
        "selected_result_index": selected,
        "reason": scalar(raw.get("reason")),
        "rejected_indices": raw.get("rejected_indices", []),
        "quality_warnings": raw.get("quality_warnings", []),
    }

def query_terms(query: str) -> list[str]:
    try:
        from ._utils import unique_preserve_order
    except ImportError:
        from _utils import unique_preserve_order
    stopwords = {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "by",
        "for",
        "from",
        "in",
        "into",
        "of",
        "on",
        "or",
        "the",
        "to",
        "with",
    }
    terms = [term.lower() for term in re.findall(r"[A-Za-z0-9][A-Za-z0-9_-]{2,}", query)]
    return unique_preserve_order([term for term in terms if term not in stopwords])

def search_arxiv(
    query: str,
    max_results: int = 10,
    sort_by: str = "relevance",
    offset: int = 0,
    categories: list[str] | tuple[str, ...] | None = None,
) -> dict[str, Any]:
    try:
        from ._literature_import import import_literature_text, import_papergraph_record
        from ._utils import clamp_int
    except ImportError:
        from _literature_import import import_literature_text, import_papergraph_record
        from _utils import clamp_int
    query, language_error = require_english_provider_query(query, "arxiv")
    if language_error:
        return language_error
    skipped = arxiv_skip_block(query)
    if skipped:
        return skipped
    selected_sort = sort_by if sort_by in {"relevance", "lastUpdatedDate", "submittedDate"} else "relevance"
    compact_query = compact_preprint_retrieval_query(query)
    api_query = arxiv_search_query_expression(compact_query, categories=categories)
    if not api_query:
        return {
            "provider": "arxiv",
            "query": query,
            "compact_query": compact_query,
            "status": "ok",
            "results": [],
            "warning": "No provider-safe lexical anchors could be derived from the query.",
            "next_step": "Use a domain or focus branch containing concrete scientific terms before retrying arXiv.",
        }
    params = urlencode(
        {
            "search_query": api_query,
            "start": max(0, int(offset or 0)),
            "max_results": clamp_int(max_results, 1, 50),
            "sortBy": selected_sort,
            "sortOrder": "descending",
        }
    )
    url = f"https://export.arxiv.org/api/query?{params}"
    try:
        raw = arxiv_get_text(url, headers={"User-Agent": "qwen-zhikan-papergraph/0.1"})
        root = ET.fromstring(raw)
        ns = {"atom": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}
        raw_papers = [arxiv_entry_to_result(entry, ns) for entry in root.findall("atom:entry", ns)]
        papers = [paper for paper in raw_papers if preprint_result_matches_query(paper, compact_query)]
        return {
            "provider": "arxiv",
            "query": query,
            "compact_query": compact_query,
            "api_query": api_query,
            "arxiv_categories": list(categories or []),
            "status": "ok",
            "results": papers,
            "raw_result_count": len(raw_papers),
            "local_rejected_count": max(0, len(raw_papers) - len(papers)),
            "next_step": "Pass a result's papergraph_input fields into import_papergraph_record, or paste abstract into import_literature_text.",
        }
    except Exception as exc:
        log_event("SCIENCE", "literature_search_failed", provider="arxiv", error=str(exc))
        return provider_error_result("arxiv", query, exc)

def search_semantic_scholar(
    query: str,
    max_results: int = 10,
    offset: int = 0,
    retry_budget: SemanticScholarRetryBudget | None = None,
) -> dict[str, Any]:
    try:
        from ._literature_import import import_literature_text, import_papergraph_record
        from ._utils import clamp_int
    except ImportError:
        from _literature_import import import_literature_text, import_papergraph_record
        from _utils import clamp_int
    query, language_error = require_english_provider_query(query, "semantic_scholar")
    if language_error:
        return language_error
    skipped = semantic_scholar_skip_block(query)
    if skipped is not None:
        return skipped
    fields = ",".join(
        [
            "title",
            "abstract",
            "year",
            "authors",
            "venue",
            "url",
            "externalIds",
            "citationCount",
            "influentialCitationCount",
            "referenceCount",
            "isOpenAccess",
            "publicationTypes",
        ]
    )
    params = urlencode(
        {
            "query": query,
            "limit": clamp_int(max_results, 1, 100),
            "offset": max(0, int(offset or 0)),
            "fields": fields,
        }
    )
    url = f"https://api.semanticscholar.org/graph/v1/paper/search?{params}"
    headers = {"User-Agent": "qwen-zhikan-papergraph/0.1"}
    if SEMANTIC_SCHOLAR_API_KEY:
        headers["x-api-key"] = SEMANTIC_SCHOLAR_API_KEY
    try:
        if retry_budget is None:
            payload = semantic_scholar_get_json(
                url,
                headers=headers,
                retry_budget=SemanticScholarRetryBudget(
                    limit=semantic_scholar_search_retry_limit(),
                    job_id="single_semantic_scholar_search",
                    max_rate_limit_responses=3,
                ),
                traffic_class="search",
            )
        else:
            payload = semantic_scholar_get_json(
                url,
                headers=headers,
                retry_budget=retry_budget,
                traffic_class="search",
            )
        papers = [semantic_scholar_item_to_result(item) for item in (payload.get("data") or []) if isinstance(item, dict)]
        return {
            "provider": "semantic_scholar",
            "query": query,
            "status": "ok",
            "total": payload.get("total"),
            "results": papers,
            "next_step": "Pass a result's papergraph_input fields into import_papergraph_record, or use import_literature_text with use_llm=true.",
        }
    except Exception as exc:
        log_event("SCIENCE", "literature_search_failed", provider="semantic_scholar", error=str(exc))
        return provider_error_result("semantic_scholar", query, exc)

def search_pubmed(
    query: str,
    max_results: int = 10,
    offset: int = 0,
    mesh_terms: list[str] | tuple[str, ...] | None = None,
) -> dict[str, Any]:
    try:
        from ._literature_import import import_literature_search_result, import_papergraph_record
        from ._utils import clamp_int, unique_preserve_order
    except ImportError:
        from _literature_import import import_literature_search_result, import_papergraph_record
        from _utils import clamp_int, unique_preserve_order
    query, language_error = require_english_provider_query(query, "pubmed")
    if language_error:
        return language_error
    source_query = query
    controlled_mesh_terms = [
        term
        for term in (str(item).strip() for item in (mesh_terms or []))
        if term and re.fullmatch(r"[A-Za-z][A-Za-z0-9 ,&()'/-]{0,120}", term)
    ]
    controlled_mesh_terms = unique_preserve_order(controlled_mesh_terms)
    disabled_reason = _literature_provider_disabled_reason("pubmed")
    if disabled_reason:
        log_event(
            "SCIENCE",
            "pubmed_specialized_search_disabled",
            query=source_query[:240],
            max_results=max_results,
            offset=offset,
            mesh_terms=controlled_mesh_terms,
            reason=disabled_reason,
        )
        return {
            "provider": "pubmed",
            "query": source_query,
            "source_query": source_query,
            "mesh_terms": controlled_mesh_terms,
            "status": "disabled_by_policy",
            "total": 0,
            "results": [],
            "reason": disabled_reason,
            "next_step": "Use OpenAlex broad discovery; PubMed specialized retrieval is disabled by policy.",
        }
    if controlled_mesh_terms:
        mesh_clause = "(" + " OR ".join(f'\"{term}\"[MeSH Terms]' for term in controlled_mesh_terms) + ")"
        query = f"({query}) AND {mesh_clause}"
    retmax = clamp_int(max_results, 1, 50)
    search_params = urlencode(
        {
            "db": "pubmed",
            "term": query,
            "retmax": retmax,
            "retstart": max(0, int(offset or 0)),
            "retmode": "json",
            "sort": "relevance",
            "tool": "qwen_zhikan",
        }
    )
    search_url = f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?{search_params}"
    try:
        search_payload = http_get_json(search_url, headers={"User-Agent": "qwen-zhikan-papergraph/0.1"}, timeout=30.0)
        id_list = (
            search_payload.get("esearchresult", {}).get("idlist", [])
            if isinstance(search_payload.get("esearchresult"), dict)
            else []
        )
        ids = [str(item).strip() for item in id_list if str(item).strip()]
        if not ids:
            return {
                "provider": "pubmed",
                "query": query,
                "source_query": source_query,
                "mesh_terms": controlled_mesh_terms,
                "status": "ok",
                "total": int((search_payload.get("esearchresult") or {}).get("count") or 0)
                if isinstance(search_payload.get("esearchresult"), dict)
                else 0,
                "results": [],
                "next_step": "No PubMed records matched; try broader biomedical terms or Semantic Scholar.",
            }
        fetch_params = urlencode(
            {
                "db": "pubmed",
                "id": ",".join(ids),
                "retmode": "xml",
                "tool": "qwen_zhikan",
            }
        )
        fetch_url = f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?{fetch_params}"
        raw = http_get_text(fetch_url, headers={"User-Agent": "qwen-zhikan-papergraph/0.1"}, timeout=30.0)
        root = ET.fromstring(raw)
        papers = [pubmed_article_to_result(article) for article in root.findall(".//PubmedArticle")]
        papers = [paper for paper in papers if paper.get("title")]
        return {
            "provider": "pubmed",
            "query": query,
            "source_query": source_query,
            "mesh_terms": controlled_mesh_terms,
            "status": "ok",
            "total": int((search_payload.get("esearchresult") or {}).get("count") or len(papers))
            if isinstance(search_payload.get("esearchresult"), dict)
            else len(papers),
            "results": papers,
            "next_step": "Pass a result's papergraph_input fields into import_papergraph_record, or use import_literature_search_result.",
        }
    except Exception as exc:
        log_event("SCIENCE", "literature_search_failed", provider="pubmed", error=str(exc))
        return provider_error_result("pubmed", query, exc)

def search_preprint_api(
    provider: str,
    query: str,
    max_results: int = 10,
    days_back: int = 365,
    scan_limit: int | None = None,
    offset: int = 0,
) -> dict[str, Any]:
    selected = database_to_provider(provider)
    query, language_error = require_english_provider_query(query, selected)
    if language_error:
        return language_error
    if selected in {"biorxiv", "medrxiv"}:
        return search_biorxiv_or_medrxiv(
            selected,
            query,
            max_results=max_results,
            days_back=days_back,
            scan_limit=scan_limit,
            result_offset=offset,
        )
    if selected == "chemrxiv":
        return search_chemrxiv(query, max_results=max_results, offset=offset)
    return {
        "provider": selected,
        "query": query,
        "status": "unknown_provider",
        "results": [],
    }

def _preprint_zero_result_cache_key(
    server: str,
    query: str,
    start: date,
    end: date,
) -> tuple[str, str, str, str]:
    return (
        normalize_space(server).lower(),
        normalize_space(query).lower(),
        start.isoformat(),
        end.isoformat(),
    )


def _cached_preprint_zero_result(
    cache_key: tuple[str, str, str, str],
    *,
    required_scan_budget: int,
) -> dict[str, Any] | None:
    if SCIENCE_PREPRINT_ZERO_RESULT_TTL_SECONDS <= 0:
        return None
    now = time.monotonic()
    with PREPRINT_ZERO_RESULT_CACHE_LOCK:
        cached = PREPRINT_ZERO_RESULT_CACHE.get(cache_key)
        if not cached:
            return None
        expires_at, metadata = cached
        if expires_at <= now:
            PREPRINT_ZERO_RESULT_CACHE.pop(cache_key, None)
            return None
        prior_scanned = int(metadata.get("prior_scanned") or 0)
        reusable = (
            bool(metadata.get("provider_exhausted"))
            or bool(metadata.get("confident_zero_signal_early_stop"))
            or prior_scanned >= int(required_scan_budget)
        )
        return dict(metadata) if reusable else None


def _cache_preprint_zero_result(
    cache_key: tuple[str, str, str, str],
    metadata: dict[str, Any],
) -> None:
    if SCIENCE_PREPRINT_ZERO_RESULT_TTL_SECONDS <= 0:
        return
    with PREPRINT_ZERO_RESULT_CACHE_LOCK:
        PREPRINT_ZERO_RESULT_CACHE[cache_key] = (
            time.monotonic() + SCIENCE_PREPRINT_ZERO_RESULT_TTL_SECONDS,
            dict(metadata),
        )


def _preprint_result_has_weak_query_signal(result: dict[str, Any], query: str) -> bool:
    tokens = [
        token
        for token in preprint_query_tokens(query)
        if token not in PREPRINT_MATCH_LOW_SIGNAL_TERMS and token not in PREPRINT_GENERIC_SCIENCE_TERMS
    ]
    if not tokens:
        return False
    text = re.sub(
        r"[-_/]",
        " ",
        " ".join(str(result.get(key) or "") for key in ("title", "abstract")).lower(),
    )
    return any(re.sub(r"[-_/]", " ", token) in text for token in tokens)


def search_biorxiv_or_medrxiv(
    server: str,
    query: str,
    max_results: int = 10,
    days_back: int = 365,
    scan_limit: int | None = None,
    result_offset: int = 0,
) -> dict[str, Any]:
    try:
        from ._literature_import import import_literature_search_result
        from ._utils import clamp_int, normalize_space
    except ImportError:
        from _literature_import import import_literature_search_result
        from _utils import clamp_int, normalize_space
    today = date.today()
    start = today - timedelta(days=clamp_int(days_back, 30, 1825))
    try:
        max_items = max(PREPRINT_API_PAGE_SIZE, min(PREPRINT_API_MAX_SCAN_RECORDS, clamp_int(max_results, 1, 50) * 40))
        if scan_limit is not None:
            max_items = min(max_items, clamp_int(scan_limit, PREPRINT_API_PAGE_SIZE, PREPRINT_API_MAX_SCAN_RECORDS))
        cache_key = _preprint_zero_result_cache_key(server, query, start, today)
        cached = _cached_preprint_zero_result(cache_key, required_scan_budget=max_items)
        if cached:
            log_event(
                "SCIENCE",
                "preprint_zero_result_cache_hit",
                provider=server,
                query=query[:180],
                days_back=clamp_int(days_back, 30, 1825),
                scan_budget=max_items,
                prior_scanned=int(cached.get("prior_scanned") or 0),
            )
            return {
                "provider": server,
                "query": query,
                "status": "ok",
                "api": f"api.biorxiv.org/details/{server}",
                "date_window": {"from": start.isoformat(), "to": today.isoformat()},
                "pages_scanned": 0,
                "scanned_result_count": 0,
                "matched_result_count": 0,
                "total_available": int(cached.get("total_available") or 0),
                "scan_budget": max_items,
                "zero_result_cache_hit": True,
                "prior_scanned_result_count": int(cached.get("prior_scanned") or 0),
                "early_stop_reason": str(cached.get("early_stop_reason") or ""),
                "results": [],
                "next_step": "Reused a recent zero-result preprint search; no provider scan was required.",
            }
        cursor = 0
        total_available = 0
        pages_scanned = 0
        scanned_items: list[dict[str, Any]] = []
        matched_candidates: list[dict[str, Any]] = []
        weak_signal_found = False
        early_stop_reason = ""
        provider_exhausted = False
        while len(scanned_items) < max_items:
            params = f"{server}/{start.isoformat()}/{today.isoformat()}/{cursor}"
            url = f"https://api.biorxiv.org/details/{params}"
            payload = http_get_json(url, headers={"User-Agent": "qwen-zhikan-papergraph/0.1"}, timeout=30.0)
            items = payload.get("collection") if isinstance(payload, dict) else []
            if not isinstance(items, list) or not items:
                provider_exhausted = True
                break
            page_items = [item for item in items if isinstance(item, dict)]
            remaining = max(0, max_items - len(scanned_items))
            page_items = page_items[:remaining]
            scanned_items.extend(page_items)
            pages_scanned += 1
            messages = payload.get("messages") if isinstance(payload, dict) else []
            if isinstance(messages, list) and messages and isinstance(messages[0], dict):
                try:
                    total_available = int(messages[0].get("total") or 0)
                except (TypeError, ValueError):
                    total_available = 0
            page_candidates = [biorxiv_item_to_result(item, server) for item in page_items]
            weak_signal_found = weak_signal_found or any(
                _preprint_result_has_weak_query_signal(item, query)
                for item in page_candidates
            )
            matched_candidates.extend(
                item for item in page_candidates if preprint_result_matches_query(item, query)
            )
            needed_matches = max(1, int(result_offset or 0) + clamp_int(max_results, 1, 50))
            if len(matched_candidates) >= needed_matches:
                early_stop_reason = "requested_match_target_reached"
                break
            cursor += len(page_items)
            if not page_items or (total_available and cursor >= total_available):
                provider_exhausted = True
                break
            if (
                pages_scanned >= SCIENCE_PREPRINT_ZERO_MATCH_EARLY_STOP_PAGES
                and not matched_candidates
                and not weak_signal_found
                and len(page_items) <= PREPRINT_API_PAGE_SIZE
            ):
                early_stop_reason = "zero_specific_query_signal_in_recent_page"
                log_event(
                    "SCIENCE",
                    "preprint_zero_match_early_stop",
                    provider=server,
                    query=query[:180],
                    pages=pages_scanned,
                    scanned=len(scanned_items),
                    scan_budget=max_items,
                    reason=early_stop_reason,
                )
                break

        # Only strict lexical matches enter the comparatively expensive quality
        # and field scoring pipeline. Unrelated provider-feed records have
        # already served their purpose in the cheap early-stop check.
        filtered = rank_literature_results(query, matched_candidates)
        papers = filtered[
            max(0, int(result_offset or 0)):
            max(0, int(result_offset or 0)) + clamp_int(max_results, 1, 50)
        ]
        log_event(
            "SCIENCE",
            "preprint_search_complete",
            provider=server,
            query=query[:180],
            pages=pages_scanned,
            scanned=len(scanned_items),
            scan_budget=max_items,
            matched=len(filtered),
            returned=len(papers),
            total_available=total_available,
            zero_result_cache_hit=False,
            early_stop_reason=early_stop_reason,
        )
        response = {
            "provider": server,
            "query": query,
            "status": "ok",
            "api": f"api.biorxiv.org/details/{server}",
            "date_window": {"from": start.isoformat(), "to": today.isoformat()},
            "pages_scanned": pages_scanned,
            "scanned_result_count": len(scanned_items),
            "matched_result_count": len(filtered),
            "result_offset": max(0, int(result_offset or 0)),
            "total_available": total_available,
            "scan_budget": max_items,
            "zero_result_cache_hit": False,
            "early_stop_reason": early_stop_reason,
            "results": papers,
            "next_step": "Import a result with import_literature_search_result; these are preprint metadata records filtered locally by query.",
        }
        if not filtered:
            _cache_preprint_zero_result(
                cache_key,
                {
                    "prior_scanned": len(scanned_items),
                    "total_available": total_available,
                    "provider_exhausted": provider_exhausted,
                    "confident_zero_signal_early_stop": early_stop_reason == "zero_specific_query_signal_in_recent_page",
                    "early_stop_reason": early_stop_reason,
                },
            )
        return response
    except Exception as exc:
        log_event("SCIENCE", "literature_search_failed", provider=server, error=str(exc))
        return provider_error_result(server, query, exc)

def search_chemrxiv(query: str, max_results: int = 10, offset: int = 0) -> dict[str, Any]:
    try:
        from ._literature_import import import_literature_search_result
        from ._utils import clamp_int
    except ImportError:
        from _literature_import import import_literature_search_result
        from _utils import clamp_int
    params = urlencode(
        {
            "query.bibliographic": query,
            "filter": "prefix:10.26434,type:posted-content",
            "rows": clamp_int(max_results, 1, 50),
            "offset": max(0, int(offset or 0)),
        }
    )
    url = f"https://api.crossref.org/works?{params}"
    try:
        payload = http_get_json(url, headers={"User-Agent": "qwen-zhikan-papergraph/0.1"}, timeout=30.0)
        message = payload.get("message") if isinstance(payload, dict) else {}
        items = message.get("items") if isinstance(message, dict) else []
        if not isinstance(items, list):
            items = []
        papers = [crossref_chemrxiv_item_to_result(item) for item in items if isinstance(item, dict)]
        papers = rank_literature_results(query, papers)[: clamp_int(max_results, 1, 50)]
        return {
            "provider": "chemrxiv",
            "query": query,
            "status": "ok",
            "api": "api.crossref.org/works?filter=prefix:10.26434,type:posted-content",
            "results": papers,
            "next_step": "Import a result with import_literature_search_result; ChemRxiv metadata is retrieved via Crossref posted-content records.",
        }
    except Exception as exc:
        log_event("SCIENCE", "literature_search_failed", provider="chemrxiv", error=str(exc))
        return provider_error_result("chemrxiv", query, exc)

def dedupe_literature_results(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    try:
        from ._literature_retrieval_foundation import (
            annotate_candidate_query_provenance,
            dedupe_candidates_by_identity,
        )
    except ImportError:
        from _literature_retrieval_foundation import (
            annotate_candidate_query_provenance,
            dedupe_candidates_by_identity,
        )
    results = dedupe_candidates_by_identity(results)
    index_by_key: dict[str, int] = {}
    deduped: list[dict[str, Any]] = []
    for result in results:
        key = literature_result_unique_key(result)
        if key in index_by_key:
            existing = deduped[index_by_key[key]]
            existing_providers = [str(value) for value in (existing.get("discovery_providers") or []) if str(value)]
            incoming_providers = [str(value) for value in (result.get("discovery_providers") or []) if str(value)]
            for provider in (*incoming_providers, existing.get("provider"), result.get("provider")):
                normalized = str(provider or "").strip()
                if normalized and normalized not in existing_providers:
                    existing_providers.append(normalized)
            existing["discovery_providers"] = existing_providers
            existing_metadata = existing.get("venue_metadata") if isinstance(existing.get("venue_metadata"), dict) else {}
            incoming_metadata = result.get("venue_metadata") if isinstance(result.get("venue_metadata"), dict) else {}
            if not existing_metadata and incoming_metadata:
                existing["venue_metadata"] = dict(incoming_metadata)
            existing_metrics = existing.get("citation_metrics") if isinstance(existing.get("citation_metrics"), dict) else {}
            incoming_metrics = result.get("citation_metrics") if isinstance(result.get("citation_metrics"), dict) else {}
            for metric_provider, values in incoming_metrics.items():
                if metric_provider not in existing_metrics and isinstance(values, dict):
                    existing_metrics[metric_provider] = dict(values)
            if existing_metrics:
                existing["citation_metrics"] = existing_metrics
            existing_ids = existing.get("external_ids") if isinstance(existing.get("external_ids"), dict) else {}
            incoming_ids = result.get("external_ids") if isinstance(result.get("external_ids"), dict) else {}
            for name, value in incoming_ids.items():
                if value and not existing_ids.get(name):
                    existing_ids[name] = value
            if existing_ids:
                existing["external_ids"] = existing_ids
            for field in ("matched_query_branches", "matched_evidence_kinds"):
                values = [str(value) for value in (existing.get(field) or []) if str(value).strip()]
                for value in (result.get(field) or []):
                    normalized = str(value or "").strip()
                    if normalized and normalized not in values:
                        values.append(normalized)
                if values:
                    existing[field] = values
            for field in ("branch_raw_hit_counts", "provider_raw_hit_counts"):
                counts = dict(existing.get(field) or {}) if isinstance(existing.get(field), dict) else {}
                for raw_key, raw_count in (result.get(field) or {}).items() if isinstance(result.get(field), dict) else ():
                    try:
                        count = max(0, int(raw_count or 0))
                    except (TypeError, ValueError):
                        continue
                    if count:
                        key_text = str(raw_key or "").strip()
                        if key_text:
                            counts[key_text] = int(counts.get(key_text) or 0) + count
                if counts:
                    existing[field] = counts
            deduped[index_by_key[key]] = annotate_candidate_query_provenance(existing)
            continue
        item = annotate_candidate_query_provenance(result)
        provider = str(item.get("provider") or "").strip()
        discovery_providers = [str(value) for value in (item.get("discovery_providers") or []) if str(value)]
        if provider and provider not in discovery_providers:
            discovery_providers.append(provider)
        item["discovery_providers"] = discovery_providers
        index_by_key[key] = len(deduped)
        deduped.append(item)
    return deduped

def literature_result_unique_key(result: dict[str, Any]) -> str:
    try:
        from ._literature_retrieval_foundation import canonical_paper_identity
    except ImportError:
        from _literature_retrieval_foundation import canonical_paper_identity
    return str(canonical_paper_identity(result)["canonical_key"])

def arxiv_entry_to_result(entry: ET.Element, ns: dict[str, str]) -> dict[str, Any]:
    try:
        from ._literature_import import build_citation, normalize_doi
        from ._utils import normalize_space, xml_text
    except ImportError:
        from _literature_import import build_citation, normalize_doi
        from _utils import normalize_space, xml_text
    title = normalize_space(xml_text(entry, "atom:title", ns))
    abstract = normalize_space(xml_text(entry, "atom:summary", ns))
    published = xml_text(entry, "atom:published", ns)
    year_match = re.search(r"\b(19|20)\d{2}\b", published)
    year = year_match.group(0) if year_match else ""
    authors = [normalize_space(author.findtext("atom:name", default="", namespaces=ns)) for author in entry.findall("atom:author", ns)]
    authors = [author for author in authors if author]
    url = xml_text(entry, "atom:id", ns)
    arxiv_id = url.rstrip("/").split("/")[-1] if url else ""
    doi = normalize_doi(xml_text(entry, "arxiv:doi", ns))
    categories = arxiv_categories(entry, ns)
    pdf_url = ""
    for link in entry.findall("atom:link", ns):
        if link.attrib.get("title") == "pdf" or link.attrib.get("type") == "application/pdf":
            pdf_url = link.attrib.get("href", "")
            break
    citation = build_citation(title=title, authors=authors, year=year, doi=doi, arxiv_id=arxiv_id)
    input_payload = {
        "title": title,
        "citation": citation,
        "authors": authors,
        "year": year,
        "venue": "arXiv",
        "provider": "arxiv",
        "source_type": "api",
        "doi": doi,
        "arxiv_id": arxiv_id,
        "arxiv_categories": categories,
        "url": url,
        "abstract": abstract,
        "conclusion": "",
    }
    return {
        "title": title,
        "citation": citation,
        "authors": authors,
        "year": year,
        "doi": doi,
        "arxiv_id": arxiv_id,
        "arxiv_categories": categories,
        "url": url,
        "pdf_url": pdf_url,
        "open_access_pdf": pdf_url,
        "abstract": abstract,
        "papergraph_input": input_payload,
    }

def arxiv_categories(entry: ET.Element, ns: dict[str, str]) -> list[str]:
    try:
        from ._utils import normalize_space, unique_preserve_order
    except ImportError:
        from _utils import normalize_space, unique_preserve_order
    categories: list[str] = []
    for category in entry.findall("atom:category", ns) + entry.findall("category"):
        term = normalize_space(category.attrib.get("term", ""))
        if term:
            categories.append(term)
    return unique_preserve_order(categories)

def semantic_scholar_item_to_result(item: dict[str, Any]) -> dict[str, Any]:
    try:
        from ._literature_import import build_citation, normalize_doi
        from ._utils import normalize_space
    except ImportError:
        from _literature_import import build_citation, normalize_doi
        from _utils import normalize_space
    external = item.get("externalIds") if isinstance(item.get("externalIds"), dict) else {}
    title = normalize_space(item.get("title", ""))
    abstract = normalize_space(item.get("abstract", ""))
    authors = [normalize_space(author.get("name", "")) for author in (item.get("authors") or []) if isinstance(author, dict)]
    authors = [author for author in authors if author]
    year = str(item.get("year") or "")
    doi = normalize_doi(str(external.get("DOI") or ""))
    arxiv_id = str(external.get("ArXiv") or "")
    semantic_scholar_id = str(item.get("paperId") or external.get("CorpusId") or "")
    url = str(item.get("url") or "")
    citation = build_citation(title=title, authors=authors, year=year, doi=doi, arxiv_id=arxiv_id)
    input_payload = {
        "title": title,
        "citation": citation,
        "authors": authors,
        "year": year,
        "venue": str(item.get("venue") or ""),
        "provider": "semantic_scholar",
        "source_type": "api",
        "doi": doi,
        "arxiv_id": arxiv_id,
        "semantic_scholar_id": semantic_scholar_id,
        "url": url,
        "abstract": abstract,
        "conclusion": "",
        "publication_types": [str(value) for value in (item.get("publicationTypes") or []) if value],
    }
    return {
        "title": title,
        "citation": citation,
        "authors": authors,
        "year": year,
        "venue": item.get("venue"),
        "doi": doi,
        "arxiv_id": arxiv_id,
        "semantic_scholar_id": semantic_scholar_id,
        "url": url,
        "citation_count": item.get("citationCount"),
        "influential_citation_count": item.get("influentialCitationCount"),
        "reference_count": item.get("referenceCount"),
        "is_open_access": item.get("isOpenAccess"),
        "publication_types": [str(value) for value in (item.get("publicationTypes") or []) if value],
        "abstract": abstract,
        "papergraph_input": input_payload,
    }

def pubmed_article_to_result(article: ET.Element) -> dict[str, Any]:
    try:
        from ._literature_import import build_citation, normalize_doi
        from ._literature_scoring import strip_markup
        from ._utils import normalize_space
    except ImportError:
        from _literature_import import build_citation, normalize_doi
        from _literature_scoring import strip_markup
        from _utils import normalize_space
    medline = article.find("MedlineCitation")
    pubmed_data = article.find("PubmedData")
    article_node = medline.find("Article") if medline is not None else None
    title = strip_markup(normalize_space(article_node.findtext("ArticleTitle", default="") if article_node is not None else ""))
    abstract_parts: list[str] = []
    if article_node is not None:
        for abstract_text in article_node.findall(".//Abstract/AbstractText"):
            label = normalize_space(str(abstract_text.attrib.get("Label") or ""))
            text = strip_markup(normalize_space("".join(abstract_text.itertext())))
            if not text:
                continue
            abstract_parts.append(f"{label}: {text}" if label else text)
    abstract = normalize_space("\n".join(abstract_parts))
    authors: list[str] = []
    if article_node is not None:
        for author in article_node.findall(".//AuthorList/Author"):
            collective = normalize_space(author.findtext("CollectiveName", default=""))
            if collective:
                authors.append(collective)
                continue
            given = normalize_space(author.findtext("ForeName", default=""))
            last = normalize_space(author.findtext("LastName", default=""))
            name = normalize_space(f"{given} {last}".strip())
            if name:
                authors.append(name)
    authors = authors[:30]
    publication_types = [
        normalize_space("".join(node.itertext()))
        for node in (article_node.findall(".//PublicationTypeList/PublicationType") if article_node is not None else [])
    ]
    publication_types = [value for value in publication_types if value]
    journal = article_node.find("Journal") if article_node is not None else None
    venue = normalize_space(journal.findtext("Title", default="") if journal is not None else "")
    pub_date = journal.find(".//PubDate") if journal is not None else None
    year = ""
    if pub_date is not None:
        year = normalize_space(pub_date.findtext("Year", default="")) or first_year(pub_date.findtext("MedlineDate", default=""))
    pmid = normalize_space(medline.findtext("PMID", default="") if medline is not None else "")
    doi = ""
    if pubmed_data is not None:
        for article_id in pubmed_data.findall(".//ArticleIdList/ArticleId"):
            if str(article_id.attrib.get("IdType") or "").lower() == "doi":
                doi = normalize_doi("".join(article_id.itertext()))
                break
    url = f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/" if pmid else ""
    citation = build_citation(title=title, authors=authors, year=year, doi=doi, arxiv_id="")
    input_payload = {
        "title": title,
        "citation": citation,
        "authors": authors,
        "year": year,
        "venue": venue,
        "provider": "pubmed",
        "source_type": "pubmed_eutils",
        "doi": doi,
        "url": url,
        "abstract": abstract,
        "conclusion": "",
        "publication_types": publication_types,
    }
    return {
        "title": title,
        "citation": citation,
        "authors": authors,
        "year": year,
        "venue": venue,
        "doi": doi,
        "pmid": pmid,
        "url": url,
        "publication_types": publication_types,
        "abstract": abstract,
        "papergraph_input": input_payload,
    }

def biorxiv_item_to_result(item: dict[str, Any], server: str) -> dict[str, Any]:
    try:
        from ._literature_import import build_citation, normalize_doi
        from ._utils import normalize_space
    except ImportError:
        from _literature_import import build_citation, normalize_doi
        from _utils import normalize_space
    title = normalize_space(str(item.get("title") or ""))
    abstract = normalize_space(str(item.get("abstract") or ""))
    authors = split_author_string(str(item.get("authors") or ""))
    year = first_year(str(item.get("date") or item.get("published") or item.get("version") or ""))
    doi = normalize_doi(str(item.get("doi") or ""))
    category = normalize_space(str(item.get("category") or ""))
    version = normalize_space(str(item.get("version") or ""))
    url = f"https://www.{server}.org/content/{doi}" if doi else str(item.get("url") or "")
    pdf_url = ""
    if doi:
        version_suffix = f"v{version}" if version and re.fullmatch(r"\d+", version) else ""
        pdf_url = f"https://www.{server}.org/content/{doi}{version_suffix}.full.pdf"
    citation = build_citation(title=title, authors=authors, year=year, doi=doi, arxiv_id="")
    input_payload = {
        "title": title,
        "citation": citation,
        "authors": authors,
        "year": year,
        "venue": server,
        "provider": server,
        "source_type": "api",
        "doi": doi,
        "url": url,
        "open_access_pdf": pdf_url,
        "abstract": abstract,
        "conclusion": "",
    }
    return {
        "title": title,
        "citation": citation,
        "authors": authors,
        "year": year,
        "venue": server,
        "doi": doi,
        "url": url,
        "abstract": abstract,
        "category": category,
        "papergraph_input": input_payload,
    }

def crossref_chemrxiv_item_to_result(item: dict[str, Any]) -> dict[str, Any]:
    try:
        from ._literature_import import build_citation, normalize_doi
        from ._literature_scoring import strip_markup
        from ._utils import normalize_space
    except ImportError:
        from _literature_import import build_citation, normalize_doi
        from _literature_scoring import strip_markup
        from _utils import normalize_space
    title = normalize_space(" ".join(str(part) for part in (item.get("title") or []) if part))
    abstract = strip_markup(normalize_space(str(item.get("abstract") or "")))
    authors = [
        normalize_space(" ".join(str(author.get(key) or "") for key in ("given", "family")).strip())
        for author in (item.get("author") or [])
        if isinstance(author, dict)
    ]
    authors = [author for author in authors if author]
    year = crossref_year(item)
    doi = normalize_doi(str(item.get("DOI") or ""))
    containers = item.get("container-title") if isinstance(item.get("container-title"), list) else []
    venue = normalize_space(str(containers[0] if containers else "ChemRxiv")) or "ChemRxiv"
    url = str(item.get("URL") or (f"https://doi.org/{doi}" if doi else ""))
    citation = build_citation(title=title, authors=authors, year=year, doi=doi, arxiv_id="")
    input_payload = {
        "title": title,
        "citation": citation,
        "authors": authors,
        "year": year,
        "venue": "ChemRxiv",
        "provider": "chemrxiv",
        "source_type": "crossref_api",
        "doi": doi,
        "url": url,
        "abstract": abstract,
        "conclusion": "",
    }
    return {
        "title": title,
        "citation": citation,
        "authors": authors,
        "year": year,
        "venue": venue or "ChemRxiv",
        "doi": doi,
        "url": url,
        "abstract": abstract,
        "papergraph_input": input_payload,
    }

def split_author_string(text: str) -> list[str]:
    try:
        from ._utils import normalize_space
    except ImportError:
        from _utils import normalize_space
    parts = re.split(r"\s*;\s*|\s*,\s+(?=[A-Z][A-Za-z.-]+(?:\s|$))", normalize_space(text))
    return [part.strip() for part in parts if part.strip()][:30]

def first_year(text: str) -> str:
    match = re.search(r"\b(19|20)\d{2}\b", text)
    return match.group(0) if match else ""

def crossref_year(item: dict[str, Any]) -> str:
    for key in ("published-print", "published-online", "published", "created"):
        value = item.get(key)
        if not isinstance(value, dict):
            continue
        date_parts = value.get("date-parts")
        if isinstance(date_parts, list) and date_parts and isinstance(date_parts[0], list) and date_parts[0]:
            year = str(date_parts[0][0])
            if re.fullmatch(r"(19|20)\d{2}", year):
                return year
    return ""

def provider_error_result(provider: str, query: str, exc: Exception) -> dict[str, Any]:
    try:
        from ._literature_import import import_literature_text
    except ImportError:
        from _literature_import import import_literature_text
    return {
        "provider": provider,
        "query": query,
        "status": "error",
        "error": str(exc),
        "results": [],
        "next_step": "Network/API failed. Retry later, configure API keys, or use manual import_literature_text.",
    }


class _OpenAccessPdfLinkParser(HTMLParser):
    """Collect publisher/repository-declared PDF links from a landing page."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.pdf_links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {str(key or "").lower(): str(value or "").strip() for key, value in attrs}
        candidate = ""
        if tag.lower() == "meta":
            marker = (values.get("name") or values.get("property") or "").lower()
            if marker in {"citation_pdf_url", "eprints.document_url", "wkhealth_pdf_url"}:
                candidate = values.get("content", "")
        elif tag.lower() == "link" and "application/pdf" in values.get("type", "").lower():
            candidate = values.get("href", "")
        elif tag.lower() == "a":
            href = values.get("href", "")
            if re.search(r"\.pdf(?:$|[?#])", href, flags=re.IGNORECASE):
                candidate = href
        if candidate:
            self.pdf_links.append(candidate)


def _normalized_http_url(value: Any) -> str:
    url = str(value or "").strip()
    if not url or urlsplit(url).scheme.lower() not in {"http", "https"}:
        return ""
    parsed = urlsplit(url)
    return parsed._replace(fragment="").geturl()


def _pdf_candidate_request_headers(candidate: dict[str, Any]) -> dict[str, str] | None:
    """Return transient download headers for authenticated OA provider URLs.

    Headers are deliberately derived at download time instead of being stored
    inside the candidate record, so API keys never become part of persisted
    PaperGraph/full-text audit payloads.
    """
    if (
        SCIENCE_ACADEMIC_MCP_OA_HARD_DISABLED
        or not SCIENCE_ACADEMIC_MCP_OA_CORE_ENABLED
        or not CORE_API_KEY
        or not isinstance(candidate, dict)
    ):
        return None
    source = str(candidate.get("source") or "")
    url = _normalized_http_url(candidate.get("url"))
    if not source.startswith("academic_mcp.core.") or not url:
        return None
    parsed = urlsplit(url)
    if parsed.netloc.lower() != "api.core.ac.uk" or "/outputs/" not in parsed.path or not parsed.path.endswith("/download"):
        return None
    return {
        "Authorization": f"Bearer {CORE_API_KEY}",
        "Accept": "application/pdf,*/*;q=0.2",
    }


def _open_access_candidate_disabled_reason(candidate: dict[str, Any]) -> str:
    if not isinstance(candidate, dict):
        return ""
    source = str(candidate.get("source") or "").lower()
    url = _normalized_http_url(candidate.get("url")).lower()
    if SCIENCE_ACADEMIC_MCP_OA_HARD_DISABLED and (
        source.startswith("academic_mcp.")
        or "api.core.ac.uk/" in url
        or "core.ac.uk/" in url
    ):
        return "Academic MCP OA candidate rejected because the adapter is hard-disabled"
    if not SCIENCE_ACADEMIC_MCP_OA_CORE_ENABLED and (
        source.startswith("academic_mcp.core.")
        or "api.core.ac.uk/" in url
        or "core.ac.uk/" in url
    ):
        return "CORE OA candidate disabled by SCIENCE_ACADEMIC_MCP_OA_CORE_ENABLED=0"
    return ""


def _looks_like_open_repository_url(url: str) -> bool:
    lowered = str(url or "").lower()
    return any(
        marker in lowered
        for marker in (
            "arxiv.org/",
            "biorxiv.org/",
            "medrxiv.org/",
            "pmc.ncbi.nlm.nih.gov/",
            "europepmc.org/",
            "/repository/",
            "repository.",
            "/eprints/",
            "eprints.",
            "/handle/",
        )
    )


def fetch_unpaywall_record(doi: str, email: str = "", timeout: float = 8.0) -> dict[str, Any]:
    """Fetch one DOI record from Unpaywall without persisting the contact email."""
    contact = str(email or SCIENCE_UNPAYWALL_EMAIL or "").strip()
    if not contact or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", contact):
        raise ValueError(
            "Unpaywall requires a valid contact email. Set SCIENCE_UNPAYWALL_EMAIL or UNPAYWALL_EMAIL."
        )
    clean_doi = str(doi or "").strip()
    if not clean_doi:
        raise ValueError("A DOI is required for Unpaywall lookup")
    url = f"https://api.unpaywall.org/v2/{quote(clean_doi, safe='/()}')}?{urlencode({'email': contact})}"
    with fulltext_host_slot(url):
        return http_get_json(
            url,
            headers={"User-Agent": f"qwen-zhikan-papergraph/0.1 (mailto:{contact})"},
            timeout=max(1.0, min(float(timeout or 8.0), 20.0)),
        )


# PDF acquisition uses non-overlapping source bands so URL kind cannot reorder
# a later provider ahead of Unpaywall.  In particular, an Unpaywall landing
# page must remain ahead of an arXiv/PMC direct PDF; the landing resolver may
# expose the current repository PDF when url_for_pdf is absent or stale.
OA_PRIORITY_UNPAYWALL_BEST = 0
OA_PRIORITY_UNPAYWALL_OTHER = 10
OA_PRIORITY_IDENTIFIER_REPOSITORY = 100
OA_PRIORITY_METADATA_REPOSITORY = 120
OA_PRIORITY_PROVIDER_URL = 140
OA_PRIORITY_OPEN_REPOSITORY_URL = 150


def _unpaywall_location_candidates(
    location: dict[str, Any],
    *,
    source: str,
    priority: int,
) -> list[dict[str, Any]]:
    if not isinstance(location, dict):
        return []
    common = {
        "source": source,
        "host_type": str(location.get("host_type") or ""),
        "version": str(location.get("version") or ""),
        "license": str(location.get("license") or ""),
        "evidence": str(location.get("evidence") or ""),
    }
    candidates: list[dict[str, Any]] = []
    pdf_url = _normalized_http_url(location.get("url_for_pdf"))
    landing_url = _normalized_http_url(location.get("url_for_landing_page") or location.get("url"))
    if pdf_url:
        candidates.append({**common, "url": pdf_url, "kind": "pdf", "priority": priority})
    if landing_url and landing_url != pdf_url:
        candidates.append(
            {
                **common,
                "url": landing_url,
                "kind": "landing_page",
                "priority": priority + 1,
            }
        )
    return candidates


def _first_external_identifier_for_oa(
    external_ids: dict[str, Any],
    *keys: str,
) -> str:
    lookup = {
        str(key or "").strip().lower(): value
        for key, value in (external_ids or {}).items()
    }
    for key in keys:
        raw = lookup.get(str(key or "").strip().lower())
        if isinstance(raw, (list, tuple, set)):
            for value in raw:
                text = str(value or "").strip()
                if text:
                    return text
            continue
        text = str(raw or "").strip()
        if text:
            return text
    return ""


def _doi_from_identifier_text_for_oa(value: Any) -> str:
    try:
        from ._literature_import import normalize_doi
    except ImportError:
        from _literature_import import normalize_doi
    text = str(value or "").strip()
    if not text:
        return ""
    normalized = normalize_doi(text)
    if re.match(r"(?i)^10\.\d{4,9}/", normalized):
        return normalized
    match = re.search(r"(?i)\b10\.\d{4,9}/[-._;()/:A-Z0-9]+\b", text)
    return normalize_doi(match.group(0)) if match else ""


def resolve_open_access_candidates(
    payload: dict[str, Any],
    result: dict[str, Any] | None = None,
    *,
    lookup_unpaywall: bool = True,
) -> dict[str, Any]:
    """Resolve ordered, provenance-rich legal OA candidates before PDF fetch.

    Unpaywall's best location is intentionally ordered before provider-supplied
    direct URLs because cached provider URLs are frequently stale.  Known
    repository and preprint identifiers remain available when Unpaywall is
    unconfigured or temporarily unavailable; a failed PDF later triggers the
    bounded DOI landing-page recovery path.
    """
    try:
        from ._literature_import import normalize_doi
    except ImportError:
        from _literature_import import normalize_doi
    result = result or {}
    external_ids: dict[str, Any] = {}
    for container in (payload, result):
        nested = container.get("external_ids") or container.get("externalIds")
        if isinstance(nested, dict):
            external_ids.update(nested)
    doi = normalize_doi(
        str(
            payload.get("doi")
            or result.get("doi")
            or _first_external_identifier_for_oa(external_ids, "doi", "DOI")
            or _doi_from_identifier_text_for_oa(payload.get("url"))
            or _doi_from_identifier_text_for_oa(result.get("url"))
            or ""
        )
    )
    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()
    disabled_candidates: list[dict[str, Any]] = []

    def add(candidate: dict[str, Any]) -> None:
        disabled_reason = _open_access_candidate_disabled_reason(candidate)
        if disabled_reason:
            disabled_candidates.append(
                {
                    "source": str(candidate.get("source") or ""),
                    "url": _normalized_http_url(candidate.get("url")),
                    "reason": disabled_reason,
                }
            )
            return
        url = _normalized_http_url(candidate.get("url"))
        key = url.lower()
        if not url or key in seen:
            return
        seen.add(key)
        candidates.append({**candidate, "url": url})

    unpaywall_audit: dict[str, Any] = {
        "status": "not_requested",
        "configured": bool(SCIENCE_UNPAYWALL_EMAIL),
        "is_oa": None,
        "oa_status": "",
        "locations_considered": 0,
    }
    if lookup_unpaywall and doi and not SCIENCE_UNPAYWALL_EMAIL:
        unpaywall_audit["status"] = "not_configured"
    elif lookup_unpaywall and doi:
        try:
            from ._fulltext_cache import get_oa_resolution, put_oa_failure, put_oa_resolution
        except ImportError:
            from _fulltext_cache import get_oa_resolution, put_oa_failure, put_oa_resolution
        cached_oa = get_oa_resolution(doi)
        if cached_oa and cached_oa.get("status") == "ok":
            cached_payload = cached_oa.get("payload") if isinstance(cached_oa.get("payload"), dict) else {}
            cached_audit = cached_payload.get("unpaywall") if isinstance(cached_payload.get("unpaywall"), dict) else {}
            unpaywall_audit.update(cached_audit)
            unpaywall_audit["cache_hit"] = True
            for candidate in cached_payload.get("candidates", []):
                if isinstance(candidate, dict):
                    add(candidate)
        elif cached_oa and cached_oa.get("status") == "failure":
            unpaywall_audit.update(
                {
                    "status": "lookup_failed",
                    "error": str(cached_oa.get("error") or "cached Unpaywall lookup failure"),
                    "failure_class": str(cached_oa.get("failure_class") or ""),
                    "http_status": cached_oa.get("http_status"),
                    "cache_hit": True,
                }
            )
        else:
            try:
                record = fetch_unpaywall_record(doi)
                best = record.get("best_oa_location") if isinstance(record.get("best_oa_location"), dict) else {}
                locations = [item for item in record.get("oa_locations", []) if isinstance(item, dict)]
                unpaywall_audit.update(
                    {
                        "status": "resolved",
                        "is_oa": bool(record.get("is_oa")),
                        "oa_status": str(record.get("oa_status") or ""),
                        "locations_considered": len(locations),
                    }
                )
                unpaywall_candidates = _unpaywall_location_candidates(
                    best,
                    source="unpaywall.best_oa_location",
                    priority=OA_PRIORITY_UNPAYWALL_BEST,
                )
                for location in locations:
                    unpaywall_candidates.extend(
                        _unpaywall_location_candidates(
                            location,
                            source="unpaywall.oa_locations",
                            priority=OA_PRIORITY_UNPAYWALL_OTHER,
                        )
                    )
                for candidate in unpaywall_candidates:
                    add(candidate)
                put_oa_resolution(
                    doi,
                    {
                        "unpaywall": unpaywall_audit,
                        "candidates": unpaywall_candidates,
                    },
                )
            except Exception as exc:
                put_oa_failure(doi, exc)
                unpaywall_audit.update({"status": "lookup_failed", "error": str(exc)})

    arxiv_id = str(payload.get("arxiv_id") or result.get("arxiv_id") or "").strip()
    if arxiv_id:
        add(
            {
                "url": f"https://arxiv.org/pdf/{quote(arxiv_id, safe='/.')}",
                "kind": "pdf",
                "source": "identifier.arxiv",
                "priority": OA_PRIORITY_IDENTIFIER_REPOSITORY,
            }
        )
    pmc_id = str(
        payload.get("pmcid")
        or payload.get("pmc_id")
        or result.get("pmcid")
        or result.get("pmc_id")
        or _first_external_identifier_for_oa(
            external_ids,
            "pmcid",
            "pmc_id",
            "pmc",
        )
        or external_ids.get("PubMedCentral")
        or external_ids.get("PMC")
        or ""
    ).strip()
    if pmc_id:
        normalized_pmc_id = pmc_id if pmc_id.upper().startswith("PMC") else f"PMC{pmc_id}"
        add(
            {
                "url": f"https://pmc.ncbi.nlm.nih.gov/articles/{quote(normalized_pmc_id, safe='')}/pdf/",
                "kind": "pdf",
                "source": "identifier.pmc",
                "priority": OA_PRIORITY_IDENTIFIER_REPOSITORY,
            }
        )
    preprint_context = " ".join(
        str(value or "")
        for value in (
            payload.get("provider"),
            result.get("provider"),
            payload.get("url"),
            result.get("url"),
            payload.get("venue"),
            result.get("venue"),
        )
    ).lower()
    if doi.startswith("10.1101/"):
        server = "medrxiv" if "medrxiv" in preprint_context else "biorxiv" if "biorxiv" in preprint_context else ""
        if server:
            add(
                {
                    "url": f"https://www.{server}.org/content/{quote(doi, safe='/')}",
                    "kind": "landing_page",
                    "source": f"identifier.{server}",
                    "priority": OA_PRIORITY_IDENTIFIER_REPOSITORY,
                }
            )
    for key, source in (
        ("repository_pdf", "metadata.repository"),
        ("repository_url", "metadata.repository"),
        ("accepted_manuscript_url", "metadata.accepted_manuscript"),
        ("author_manuscript_url", "metadata.author_manuscript"),
    ):
        url = payload.get(key) or result.get(key)
        if url:
            add(
                {
                    "url": url,
                    "kind": "pdf" if re.search(r"\.pdf(?:$|[?#])", str(url), re.IGNORECASE) else "landing_page",
                    "source": source,
                    "priority": OA_PRIORITY_METADATA_REPOSITORY,
                }
            )
    for container in (result, payload):
        container_provider = normalize_space(str(container.get("provider") or "")).lower()
        for key in ("open_access_pdf", "pdf_url", "full_text_url"):
            if container.get(key):
                if container_provider == "semantic_scholar":
                    disabled_candidates.append(
                        {
                            "source": f"existing.{key}",
                            "url": _normalized_http_url(container.get(key)),
                            "reason": "Semantic Scholar OA PDF candidates are disabled for full-text acquisition",
                        }
                    )
                    continue
                add(
                    {
                        "url": container.get(key),
                        "kind": "pdf",
                        "source": f"existing.{key}",
                        "priority": OA_PRIORITY_PROVIDER_URL,
                    }
                )
        page_url = _normalized_http_url(container.get("url"))
        if page_url and _looks_like_open_repository_url(page_url):
            add(
                {
                    "url": page_url,
                    "kind": "pdf" if re.search(r"\.pdf(?:$|[?#])", page_url, re.IGNORECASE) else "landing_page",
                    "source": "existing.open_repository_url",
                    "priority": OA_PRIORITY_OPEN_REPOSITORY_URL,
                }
            )
    candidates.sort(key=lambda item: (int(item.get("priority") or 0), 0 if item.get("kind") == "pdf" else 1))
    status = "candidates_available" if candidates else "no_open_access_candidate"
    if unpaywall_audit.get("status") == "lookup_failed" and not candidates:
        status = "lookup_failed"
    return {
        "status": status,
        "doi": doi,
        "doi_landing_page": f"https://doi.org/{quote(doi, safe='/()}')}" if doi else "",
        "unpaywall": unpaywall_audit,
        "candidates": candidates,
        "disabled_candidates": disabled_candidates,
        "attempts": [],
        "selected_url": "",
        "selected_source": "",
    }


def fetch_landing_page_pdf_candidates(
    url: str,
    *,
    timeout_seconds: float = 10.0,
    max_bytes: int = 1_500_000,
) -> dict[str, Any]:
    """Resolve a DOI/repository landing page and discover declared PDF links."""
    try:
        from ._fulltext_cache import (
            CachedFullTextFailure,
            get_landing_resolution,
            put_landing_failure,
            put_landing_resolution,
        )
    except ImportError:
        from _fulltext_cache import (
            CachedFullTextFailure,
            get_landing_resolution,
            put_landing_failure,
            put_landing_resolution,
        )
    cached = get_landing_resolution(url)
    if cached and cached.get("status") == "failure":
        raise CachedFullTextFailure(cached)
    if cached and cached.get("status") == "ok":
        payload = cached.get("payload") if isinstance(cached.get("payload"), dict) else {}
        return {**payload, "cache_hit": True}
    request = Request(
        url,
        headers={
            "User-Agent": "qwen-zhikan-papergraph/0.1",
            "Accept": "text/html,application/xhtml+xml,application/pdf;q=0.8,*/*;q=0.2",
        },
    )
    try:
        with fulltext_host_slot(url):
            with urlopen(
                request,
                timeout=max(1.0, min(float(timeout_seconds or 10.0), 20.0)),
                context=ssl_context(),
            ) as response:
                final_url = _normalized_http_url(response.geturl()) or _normalized_http_url(url)
                content_type = str(response.headers.get("Content-Type") or "").lower()
                data = response.read(max_bytes + 1)
        if len(data) > max_bytes:
            raise RuntimeError(f"Landing page exceeds {max_bytes} byte safety limit")
        if "application/pdf" in content_type or data.lstrip().startswith(b"%PDF-"):
            resolved_payload = {
                "status": "resolved_to_pdf",
                "landing_page_url": url,
                "final_url": final_url,
                "pdf_urls": [final_url],
            }
        else:
            parser = _OpenAccessPdfLinkParser()
            parser.feed(data.decode("utf-8", errors="replace"))
            pdf_urls: list[str] = []
            seen: set[str] = set()
            for candidate in parser.pdf_links:
                resolved = _normalized_http_url(urljoin(final_url, candidate))
                if resolved and resolved.lower() not in seen:
                    seen.add(resolved.lower())
                    pdf_urls.append(resolved)
            resolved_payload = {
                "status": "pdf_links_found" if pdf_urls else "landing_page_only",
                "landing_page_url": url,
                "final_url": final_url,
                "pdf_urls": pdf_urls[:8],
            }
        put_landing_resolution(url, resolved_payload)
        return resolved_payload
    except HTTPError as exc:
        error = RuntimeError(f"HTTP {exc.code}: landing page fetch failed")
        setattr(error, "http_status", int(exc.code))
        setattr(
            error,
            "final_url",
            _normalized_http_url(getattr(exc, "url", "") or "") or "",
        )
        put_landing_failure(url, error)
        raise error from exc
    except URLError as exc:
        error = RuntimeError(f"URL error: {exc.reason}")
        put_landing_failure(url, error)
        raise error from exc
    except Exception as exc:
        if not isinstance(exc, CachedFullTextFailure):
            put_landing_failure(url, exc)
        raise


def enrich_papergraph_payload(
    payload: dict[str, Any],
    result: dict[str, Any] | None = None,
    *,
    include_full_text: bool = True,
) -> tuple[dict[str, Any], list[str]]:
    try:
        from ._literature_import import extraction_quality_report, normalize_doi
        from ._utils import normalize_space, unique_preserve_order
    except ImportError:
        from _literature_import import extraction_quality_report, normalize_doi
        from _utils import normalize_space, unique_preserve_order
    """Best-effort metadata and legal open-access enrichment.

    DOI records go through Unpaywall and known repositories before any
    provider-supplied direct PDF is fetched.  Candidate failures are audited and
    rotated; a publisher denial or HTML response triggers legal OA fallback
    discovery before any DOI landing-page recovery.
    """
    enriched = dict(payload)
    result = result or {}
    sources: list[str] = []
    errors: list[str] = []
    metadata_lookup_attempted = False
    s2_probe_status = "not_requested"
    openalex_doi_status = "not_requested"
    initial_quality = extraction_quality_report(enriched)
    has_full_text_excerpt = bool(normalize_space(str(enriched.get("full_text_excerpt") or "")))
    needs_metadata_enrichment = bool(initial_quality.get("needs_enrichment"))
    needs_full_text_enrichment = bool(include_full_text and not has_full_text_excerpt)
    oa_resolution = resolve_open_access_candidates(
        enriched,
        result,
        lookup_unpaywall=needs_full_text_enrichment,
    )
    unpaywall_audit = oa_resolution.get("unpaywall") if isinstance(oa_resolution.get("unpaywall"), dict) else {}
    if unpaywall_audit.get("status") in {"resolved", "lookup_failed"}:
        metadata_lookup_attempted = True
    if unpaywall_audit.get("status") == "lookup_failed":
        errors.append(f"unpaywall: {unpaywall_audit.get('error') or 'lookup failed'}")
    direct_pdf_url = next(
        (
            str(candidate.get("url") or "")
            for candidate in oa_resolution.get("candidates", [])
            if isinstance(candidate, dict) and candidate.get("kind") == "pdf"
        ),
        "",
    )

    semantic_id = str(
        enriched.get("semantic_scholar_id")
        or result.get("semantic_scholar_id")
        or ""
    ).strip()
    doi = normalize_doi(str(enriched.get("doi") or result.get("doi") or ""))
    s2_identifier = semantic_id or (f"DOI:{doi}" if doi else "")
    source_provider = normalize_space(str(result.get("provider") or enriched.get("provider") or "")).lower()
    def merge_oa_candidates(candidates: list[dict[str, Any]]) -> None:
        known_candidate_urls = {
            str(candidate.get("url") or "").lower()
            for candidate in oa_resolution.get("candidates", [])
            if isinstance(candidate, dict)
        }
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            disabled_reason = _open_access_candidate_disabled_reason(candidate)
            if disabled_reason:
                oa_resolution.setdefault("disabled_candidates", []).append(
                    {
                        "source": str(candidate.get("source") or ""),
                        "url": _normalized_http_url(candidate.get("url")),
                        "reason": disabled_reason,
                    }
                )
                continue
            url_key = _normalized_http_url(candidate.get("url")).lower()
            if url_key and url_key not in known_candidate_urls:
                oa_resolution.setdefault("candidates", []).append(candidate)
                known_candidate_urls.add(url_key)
        oa_resolution["candidates"] = sorted(
            oa_resolution.get("candidates", []),
            key=lambda item: (int(item.get("priority") or 0), 0 if item.get("kind") == "pdf" else 1),
        )

    if (
        needs_full_text_enrichment
        and not direct_pdf_url
        and doi
        and source_provider == "openalex"
    ):
        metadata_lookup_attempted = True
        try:
            try:
                from ._openalex import fetch_openalex_work_by_doi
            except ImportError:
                from _openalex import fetch_openalex_work_by_doi
            outcome = fetch_openalex_work_by_doi(doi)
            openalex_doi_status = str(outcome.get("status") or "error")
            openalex_result = outcome.get("result") if isinstance(outcome.get("result"), dict) else {}
            before_len = len(str(enriched.get("abstract") or ""))
            before_pdf_url = str(enriched.get("open_access_pdf") or "")
            if openalex_doi_status == "ok" and openalex_result:
                detail_payload = (
                    openalex_result.get("papergraph_input")
                    if isinstance(openalex_result.get("papergraph_input"), dict)
                    else {}
                )
                enriched = merge_nonempty(enriched, detail_payload)
                if openalex_result.get("open_access_pdf"):
                    enriched["open_access_pdf"] = openalex_result.get("open_access_pdf")
                if openalex_result.get("url") and not enriched.get("url"):
                    enriched["url"] = openalex_result.get("url")
                after_len = len(str(enriched.get("abstract") or ""))
                after_pdf_url = str(enriched.get("open_access_pdf") or "")
                if after_len > before_len or after_pdf_url != before_pdf_url:
                    sources.append("openalex_doi_metadata")
            log_event(
                "SCIENCE",
                "openalex_doi_oa_fallback_complete",
                doi=doi,
                status=openalex_doi_status,
                cache_hit=bool(outcome.get("cache_hit")),
                open_access_pdf_found=bool(enriched.get("open_access_pdf")),
            )
        except Exception as exc:
            openalex_doi_status = "error"
            error = str(exc)
            errors.append(f"openalex_doi: {error}")
            log_event(
                "SCIENCE",
                "openalex_doi_oa_fallback_failed",
                doi=doi,
                error=error[:300],
            )
        direct_pdf_url = str(enriched.get("open_access_pdf") or direct_pdf_url or "")
    if s2_identifier and needs_metadata_enrichment and not needs_full_text_enrichment:
        skip_s2_probe, skip_reason, skip_retry_after = (
            _semantic_scholar_optional_probe_skip_decision(fast_fail=False)
        )
        if skip_s2_probe:
            s2_probe_status = (
                "skipped_semantic_scholar_due_to_recent_429_suppression"
                if "429" in skip_reason
                else "skipped_semantic_scholar_due_to_active_circuit"
            )
            _log_provider_circuit_active_compact(
                provider="semantic_scholar",
                reason=skip_reason,
                retry_after_seconds=skip_retry_after,
                traffic_class="optional_detail_probe",
            )
        else:
            metadata_lookup_attempted = True
            try:
                detail = fetch_semantic_scholar_paper_detail(s2_identifier)
                before_len = len(str(enriched.get("abstract") or ""))
                enriched = merge_semantic_scholar_detail(enriched, detail)
                after_len = len(str(enriched.get("abstract") or ""))
                s2_probe_status = (
                    "metadata_resolved" if after_len > before_len else "no_new_metadata"
                )
                if after_len > before_len:
                    sources.append("semantic_scholar_detail")
            except Exception as exc:
                error = str(exc)
                if bool(getattr(exc, "semantic_scholar_recent_429_suppressed", False)):
                    s2_probe_status = "skipped_recent_429_suppression"
                elif is_semantic_scholar_rate_limit_error(error):
                    s2_probe_status = "rate_limited"
                elif is_semantic_scholar_transient_error(exc):
                    s2_probe_status = "transient_failure"
                else:
                    s2_probe_status = "failed"
                errors.append(f"semantic_scholar: {error}")
                log_event(
                    "SCIENCE",
                    "metadata_enrichment_failed",
                    provider="semantic_scholar",
                    error=error,
                    s2_probe_status=s2_probe_status,
                )
        if s2_probe_status not in {
            "skipped_semantic_scholar_due_to_recent_429_suppression",
            "skipped_semantic_scholar_due_to_active_circuit",
            "skipped_recent_429_suppression",
        }:
            log_event(
                "SCIENCE",
                "semantic_scholar_detail_enrichment_complete",
                identifier=s2_identifier[:180],
                status=s2_probe_status,
            )

    arxiv_id = str(enriched.get("arxiv_id") or result.get("arxiv_id") or "").strip()
    existing_pdf_url = str(result.get("open_access_pdf") or enriched.get("open_access_pdf") or "").strip()
    if arxiv_id and (needs_metadata_enrichment or (needs_full_text_enrichment and not existing_pdf_url)):
        metadata_lookup_attempted = True
        try:
            arxiv_payload = fetch_arxiv_by_id(
                arxiv_id,
                fast_fail=needs_full_text_enrichment,
            )
            before_len = len(str(enriched.get("abstract") or ""))
            before_pdf_url = str(enriched.get("open_access_pdf") or "")
            enriched = merge_nonempty(enriched, arxiv_payload)
            after_len = len(str(enriched.get("abstract") or ""))
            if after_len > before_len or str(enriched.get("open_access_pdf") or "") != before_pdf_url:
                sources.append("arxiv_detail")
        except Exception as exc:
            error = str(exc)
            errors.append(f"arxiv: {error}")
            log_event("SCIENCE", "metadata_enrichment_failed", provider="arxiv", error=error)

    # arXiv enrichment may have supplied an additional OA URL.
    supplemental_resolution = resolve_open_access_candidates(
        enriched,
        result,
        lookup_unpaywall=False,
    )
    merge_oa_candidates([dict(item) for item in supplemental_resolution.get("candidates", []) if isinstance(item, dict)])

    selected_excerpt = ""
    selected_report: dict[str, Any] = {}
    selected_candidate: dict[str, Any] = {}
    saw_not_found = False
    landing_pages: list[dict[str, Any]] = []
    extraction_cache_context = (
        dict(result.get("_fulltext_extraction_context"))
        if isinstance(result.get("_fulltext_extraction_context"), dict)
        else {}
    )
    retrieval_branch = str(
        result.get("query_branch")
        or result.get("retrieval_branch")
        or enriched.get("query_branch")
        or enriched.get("retrieval_branch")
        or ""
    ).strip()
    if retrieval_branch:
        extraction_cache_context.setdefault("retrieval_branch", retrieval_branch)
    if not extraction_cache_context.get("sub_hypothesis_id"):
        match = re.search(r"(?<![A-Za-z0-9])SH\d+(?![A-Za-z0-9])", retrieval_branch, flags=re.IGNORECASE)
        if match:
            extraction_cache_context["sub_hypothesis_id"] = match.group(0).upper()
    candidate_queue = [dict(item) for item in oa_resolution.get("candidates", []) if isinstance(item, dict)]
    attempted_urls: set[str] = set()
    index = 0

    while needs_full_text_enrichment and index < len(candidate_queue) and len(attempted_urls) < 12:
        candidate = candidate_queue[index]
        index += 1
        candidate_url = _normalized_http_url(candidate.get("url"))
        candidate_key = candidate_url.lower()
        if not candidate_url or candidate_key in attempted_urls:
            continue
        attempted_urls.add(candidate_key)
        source = str(candidate.get("source") or "open_access_candidate")
        if candidate.get("kind") == "landing_page":
            try:
                landing = fetch_landing_page_pdf_candidates(candidate_url)
                landing_pages.append(landing)
                oa_resolution.setdefault("attempts", []).append(
                    {
                        "url": candidate_url,
                        "source": source,
                        "kind": "landing_page",
                        "status": str(landing.get("status") or "resolved"),
                        "final_url": str(landing.get("final_url") or ""),
                        "pdf_links_found": len(landing.get("pdf_urls", [])),
                    }
                )
                discovered = [
                    {
                        "url": pdf_link,
                        "kind": "pdf",
                        "source": f"{source}.declared_pdf",
                        "priority": int(candidate.get("priority") or 0),
                    }
                    for pdf_link in landing.get("pdf_urls", [])
                ]
                candidate_queue[index:index] = discovered
            except Exception as exc:
                status = int(getattr(exc, "http_status", 0) or 0)
                saw_not_found = saw_not_found or status == 404
                error = str(exc)
                errors.append(f"{source}: {error}")
                oa_resolution.setdefault("attempts", []).append(
                    {
                        "url": candidate_url,
                        "source": source,
                        "kind": "landing_page",
                        "status": "not_found" if status == 404 else "fetch_failed",
                        "http_status": status or None,
                        "error": error,
                    }
                )
            continue
        try:
            excerpt_payload = fetch_pdf_text_excerpt(
                candidate_url,
                paper_metadata=enriched,
                sub_hypothesis=str(result.get("retrieval_branch") or enriched.get("retrieval_branch") or ""),
                extraction_cache_context=extraction_cache_context,
                request_headers=_pdf_candidate_request_headers(candidate),
            )
            excerpt = str(excerpt_payload or "")
            if not excerpt:
                oa_resolution.setdefault("attempts", []).append(
                    {
                        "url": candidate_url,
                        "source": source,
                        "kind": "pdf",
                        "status": "no_extractable_text",
                    }
                )
                continue
            selected_excerpt = excerpt
            selected_report = dict(getattr(excerpt_payload, "report", {}) or {})
            selected_candidate = candidate
            oa_resolution.setdefault("attempts", []).append(
                {"url": candidate_url, "source": source, "kind": "pdf", "status": "extracted"}
            )
            break
        except Exception as exc:
            status = int(getattr(exc, "http_status", 0) or 0)
            saw_not_found = saw_not_found or status == 404
            error = str(exc)
            non_pdf_response = status == 200 and "non-pdf" in error.lower()
            errors.append(f"{source}: {error}")
            oa_resolution.setdefault("attempts", []).append(
                {
                    "url": candidate_url,
                    "source": source,
                    "kind": "pdf",
                    "status": (
                        "not_found" if status == 404
                        else "access_denied" if status in {401, 403}
                        else "non_pdf" if non_pdf_response
                        else "fetch_failed"
                    ),
                    "http_status": status or None,
                    "error": error,
                }
            )
    # A stale direct PDF must not be retried. Resolve the DOI once and discover
    # the publisher's current declared PDF link for a final bounded attempt.
    doi_landing_url = str(oa_resolution.get("doi_landing_page") or "")
    if (
        needs_full_text_enrichment
        and not selected_excerpt
        and doi_landing_url
        and (saw_not_found or not candidate_queue)
        and doi_landing_url.lower() not in attempted_urls
    ):
        attempted_urls.add(doi_landing_url.lower())
        log_event(
            "SCIENCE",
            "doi_landing_page_recovery_start",
            doi=doi,
            landing_url=doi_landing_url,
            title=str(enriched.get("title") or result.get("title") or "")[:240],
            provider=source_provider,
            reason="no_open_access_candidate" if not candidate_queue else "prior_candidate_not_found",
        )
        try:
            landing = fetch_landing_page_pdf_candidates(doi_landing_url)
            landing_pages.append(landing)
            oa_resolution["doi_landing_page_resolution"] = landing
            oa_resolution.setdefault("attempts", []).append(
                {
                    "url": doi_landing_url,
                    "source": "doi.landing_page_recovery",
                    "kind": "landing_page",
                    "status": str(landing.get("status") or "resolved"),
                    "final_url": str(landing.get("final_url") or ""),
                    "pdf_links_found": len(landing.get("pdf_urls", [])),
                }
            )
            recovered_pdf_attempts = 0
            recovered_pdf_extracted = False
            for recovered_url in landing.get("pdf_urls", [])[:4]:
                recovered_url = _normalized_http_url(recovered_url)
                if not recovered_url or recovered_url.lower() in attempted_urls:
                    continue
                attempted_urls.add(recovered_url.lower())
                recovered_pdf_attempts += 1
                try:
                    excerpt_payload = fetch_pdf_text_excerpt(
                        recovered_url,
                        paper_metadata=enriched,
                        sub_hypothesis=str(result.get("retrieval_branch") or enriched.get("retrieval_branch") or ""),
                        extraction_cache_context=extraction_cache_context,
                    )
                    excerpt = str(excerpt_payload or "")
                    if not excerpt:
                        continue
                    selected_excerpt = excerpt
                    selected_report = dict(getattr(excerpt_payload, "report", {}) or {})
                    selected_candidate = {
                        "url": recovered_url,
                        "source": "doi.landing_page_recovery.declared_pdf",
                        "kind": "pdf",
                    }
                    oa_resolution.setdefault("attempts", []).append(
                        {
                            "url": recovered_url,
                            "source": selected_candidate["source"],
                            "kind": "pdf",
                            "status": "extracted",
                        }
                    )
                    break
                except Exception as exc:
                    status = int(getattr(exc, "http_status", 0) or 0)
                    error = str(exc)
                    errors.append(f"doi.landing_page_recovery: {error}")
                    oa_resolution.setdefault("attempts", []).append(
                        {
                            "url": recovered_url,
                            "source": "doi.landing_page_recovery.declared_pdf",
                            "kind": "pdf",
                            "status": "access_denied" if status in {401, 403} else "fetch_failed",
                            "http_status": status or None,
                            "error": error,
                        }
                    )
            recovered_pdf_extracted = bool(selected_excerpt)
            log_event(
                "SCIENCE",
                "doi_landing_page_recovery_complete",
                doi=doi,
                landing_url=doi_landing_url,
                status=str(landing.get("status") or "resolved"),
                final_url=str(landing.get("final_url") or ""),
                pdf_links_found=len(landing.get("pdf_urls", [])),
                attempted_pdf_downloads=recovered_pdf_attempts,
                extracted=recovered_pdf_extracted,
            )
        except Exception as exc:
            status = int(getattr(exc, "http_status", 0) or 0)
            error = str(exc)
            cache_hit = bool(getattr(exc, "cache_hit", False))
            failure_class = str(getattr(exc, "failure_class", "") or "")
            if status == 404 or failure_class == "NOT_FOUND":
                landing_failure_status = "cached_not_found" if cache_hit else "not_found"
                attempt_failure_status = "not_found"
            elif status in {401, 403} or failure_class == "AUTH_OR_ACCESS_DENIED":
                landing_failure_status = "cached_access_denied" if cache_hit else "access_denied"
                attempt_failure_status = "access_denied"
            else:
                landing_failure_status = "cached_fetch_failed" if cache_hit else "fetch_failed"
                attempt_failure_status = "fetch_failed"
            errors.append(f"doi.landing_page_recovery: {error}")
            oa_resolution["doi_landing_page_resolution"] = {
                "status": landing_failure_status,
                "http_status": status or None,
                "cache_hit": cache_hit,
                "failure_class": failure_class,
                "retry_after_seconds": getattr(exc, "retry_after_seconds", None),
                "error": error,
            }
            oa_resolution.setdefault("attempts", []).append(
                {
                    "url": doi_landing_url,
                    "source": "doi.landing_page_recovery",
                    "kind": "landing_page",
                    "status": attempt_failure_status,
                    "http_status": status or None,
                    "cache_hit": cache_hit,
                    "failure_class": failure_class,
                    "error": error,
                }
            )
            log_event(
                "SCIENCE",
                "doi_landing_page_recovery_complete",
                doi=doi,
                landing_url=doi_landing_url,
                status=landing_failure_status,
                http_status=status or None,
                cache_hit=cache_hit,
                failure_class=failure_class,
                retry_after_seconds=getattr(exc, "retry_after_seconds", None),
                pdf_links_found=0,
                attempted_pdf_downloads=0,
                extracted=False,
                error=error[:300],
            )

    if landing_pages:
        oa_resolution["landing_pages"] = landing_pages
    pdf_url = _normalized_http_url(selected_candidate.get("url"))
    if pdf_url:
        oa_resolution["status"] = "full_text_resolved"
        oa_resolution["selected_url"] = pdf_url
        oa_resolution["selected_source"] = str(selected_candidate.get("source") or "")
        enriched["open_access_pdf"] = pdf_url
        enriched["open_access_source"] = oa_resolution["selected_source"]
        enriched["full_text_excerpt"] = selected_excerpt
        sources.extend(["open_access_pdf_available", "open_access_pdf_text", oa_resolution["selected_source"]])
    if needs_full_text_enrichment and not selected_excerpt and not oa_resolution.get("candidates") and not oa_resolution.get("fallback_candidates"):
        doi_landing = (
            oa_resolution.get("doi_landing_page_resolution")
            if isinstance(oa_resolution.get("doi_landing_page_resolution"), dict)
            else {}
        )
        log_event(
            "SCIENCE",
            "paper_pdf_fetch_skipped_no_open_access_candidate",
            doi=doi,
            title=str(enriched.get("title") or result.get("title") or "")[:240],
            provider=source_provider,
            unpaywall_status=str(unpaywall_audit.get("status") or "not_requested"),
            s2_probe_status=s2_probe_status,
            openalex_doi_status=openalex_doi_status,
            doi_landing_status=str(doi_landing.get("status") or "not_attempted"),
            next_step="configure a native OA provider or provide a local PDF",
        )

    full_text_report: dict[str, Any] | None = None
    if pdf_url and selected_excerpt:
        full_text_report = dict(selected_report)
        full_text_report.update(
            {
                "status": "extracted",
                "attempted": True,
                "attempted_at": time.time(),
                "source_url": pdf_url,
                "source": oa_resolution.get("selected_source"),
                "excerpt_chars": len(selected_excerpt),
            }
        )
        log_event(
            "SCIENCE",
            "paper_full_text_excerpt_extracted",
            url=pdf_url,
            source=oa_resolution.get("selected_source"),
            chars=len(selected_excerpt),
            # A URL alone is not enough to associate PDF extraction with a
            # candidate.  These fields are optional for standalone callers,
            # but the import pipeline supplies them for every prepared paper.
            project_id=str(extraction_cache_context.get("project_id") or ""),
            search_id=str(extraction_cache_context.get("search_id") or ""),
            result_index=extraction_cache_context.get("result_index"),
            sub_hypothesis_id=str(
                extraction_cache_context.get("sub_hypothesis_id") or ""
            ),
            retrieval_branch=str(extraction_cache_context.get("retrieval_branch") or ""),
            research_question_task_id=str(
                extraction_cache_context.get("research_question_task_id") or ""
            ),
            evidence_slot=str(extraction_cache_context.get("evidence_slot") or ""),
            plan_revision=str(extraction_cache_context.get("plan_revision") or ""),
            paper_identity=str(extraction_cache_context.get("paper_identity") or ""),
            include_full_text=bool(extraction_cache_context.get("include_full_text")),
            acquisition_intent=str(
                extraction_cache_context.get("acquisition_intent") or "unspecified"
            ),
        )
    elif has_full_text_excerpt:
        full_text_report = {
            "status": "already_present",
            "attempted": False,
            "source_url": "",
            "excerpt_chars": len(str(enriched.get("full_text_excerpt") or "")),
        }
    elif needs_full_text_enrichment and oa_resolution.get("attempts"):
        statuses = {
            str(attempt.get("status") or "")
            for attempt in oa_resolution.get("attempts", [])
            if isinstance(attempt, dict)
        }
        if "access_denied" in statuses:
            failure_status = "institution_auth_required"
        elif "non_pdf" in statuses:
            failure_status = "open_access_non_pdf_response"
        elif "not_found" in statuses and oa_resolution.get("doi_landing_page_resolution"):
            failure_status = "broken_or_moved_url"
        else:
            failure_status = "open_access_fetch_failed"
        full_text_report = {
            "status": failure_status,
            "attempted": True,
            "attempted_at": time.time(),
            "source_url": "",
            "excerpt_chars": 0,
            "error": "; ".join(errors[-6:]),
            "next_step": (
                "Use institutional browser access or a publisher TDM API."
                if failure_status == "institution_auth_required"
                else "Inspect the freshly resolved DOI landing page or import a local PDF."
            ),
        }
    elif needs_full_text_enrichment and metadata_lookup_attempted and errors:
        full_text_report = {
            "status": "metadata_lookup_failed",
            "attempted": True,
            "attempted_at": time.time(),
            "retry_after_seconds": 900,
            "source_url": "",
            "excerpt_chars": 0,
            "error": "; ".join(errors),
        }
    elif needs_full_text_enrichment:
        full_text_report = {
            "status": "no_open_access_pdf",
            "attempted": False,
            "source_url": "",
            "excerpt_chars": 0,
        }
    enriched["_open_access_resolution"] = oa_resolution
    if full_text_report is not None:
        full_text_report["open_access_resolution"] = oa_resolution
        enriched["_full_text_enrichment"] = full_text_report
    if errors:
        enriched["_enrichment_errors"] = errors
    return enriched, unique_preserve_order(sources)

def fetch_semantic_scholar_paper_detail(identifier: str, *, fast_fail: bool = False) -> dict[str, Any]:
    fields = ",".join(
        [
            "title",
            "abstract",
            "year",
            "authors",
            "venue",
            "url",
            "externalIds",
            "citationCount",
            "influentialCitationCount",
            "referenceCount",
            "isOpenAccess",
            "tldr",
        ]
    )
    url = f"https://api.semanticscholar.org/graph/v1/paper/{quote(identifier, safe=':')}?{urlencode({'fields': fields})}"
    headers = {"User-Agent": "qwen-zhikan-papergraph/0.1"}
    if SEMANTIC_SCHOLAR_API_KEY:
        headers["x-api-key"] = SEMANTIC_SCHOLAR_API_KEY
    return semantic_scholar_get_json(
        url,
        headers=headers,
        timeout=8.0 if fast_fail else 10.0,
        retry_budget=SemanticScholarRetryBudget(
            limit=0,
            job_id=(
                "optional_semantic_scholar_detail_probe"
                if fast_fail
                else "semantic_scholar_detail_metadata_probe"
            ),
            max_rate_limit_responses=1,
        ),
        traffic_class="detail",
        fast_fail_circuit=True,
    )

def merge_semantic_scholar_detail(payload: dict[str, Any], detail: dict[str, Any]) -> dict[str, Any]:
    try:
        from ._utils import normalize_space
    except ImportError:
        from _utils import normalize_space
    result = semantic_scholar_item_to_result(detail)
    detail_payload = result.get("papergraph_input") if isinstance(result.get("papergraph_input"), dict) else {}
    tldr = detail.get("tldr") if isinstance(detail.get("tldr"), dict) else {}
    if not detail_payload.get("abstract") and tldr.get("text"):
        detail_payload["abstract"] = normalize_space(str(tldr.get("text") or ""))
    merged = merge_nonempty(payload, detail_payload)
    return merged

def fetch_arxiv_by_id(arxiv_id: str, *, fast_fail: bool = False) -> dict[str, Any]:
    clean_id = arxiv_id.strip()
    if not clean_id:
        return {}
    url = f"https://export.arxiv.org/api/query?{urlencode({'id_list': clean_id})}"
    headers = {"User-Agent": "qwen-zhikan-papergraph/0.1"}
    raw = (
        http_get_text(url, headers=headers, timeout=8.0)
        if fast_fail
        else arxiv_get_text(url, headers=headers)
    )
    root = ET.fromstring(raw)
    ns = {"atom": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}
    entry = root.find("atom:entry", ns)
    if entry is None:
        return {}
    result = arxiv_entry_to_result(entry, ns)
    payload = result.get("papergraph_input", {}) if isinstance(result.get("papergraph_input"), dict) else {}
    payload = dict(payload)
    if result.get("pdf_url"):
        payload["open_access_pdf"] = result.get("pdf_url")
    return payload

def fetch_pdf_content(
    url: str,
    paper_metadata: dict[str, Any] | None = None,
    sub_hypothesis: str | dict[str, Any] | None = None,
    max_bytes: int = 20_000_000,
    max_output_chars: int = 120_000,
    timeout_seconds: float = 12.0,
    extraction_cache_context: dict[str, Any] | None = None,
    request_headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    try:
        from ._fulltext_cache import (
            fulltext_cache_singleflight,
            get_excerpt,
            get_pdf_by_url,
            put_excerpt,
            put_pdf_by_url,
            put_pdf_failure,
        )
        from ._pdf_extraction import (
            PDF_EXCERPT_EXTRACTOR_VERSION,
            extract_pdf_content,
            extraction_keywords,
        )
    except ImportError:
        from _fulltext_cache import (
            fulltext_cache_singleflight,
            get_excerpt,
            get_pdf_by_url,
            put_excerpt,
            put_pdf_by_url,
            put_pdf_failure,
        )
        from _pdf_extraction import (
            PDF_EXCERPT_EXTRACTOR_VERSION,
            extract_pdf_content,
            extraction_keywords,
        )
    try:
        from ._utils import normalize_space
    except ImportError:
        from _utils import normalize_space
    # The URL lock covers only cache population and network I/O.  Parsing and
    # SH-specific excerpt selection run after release, so unrelated papers and
    # distinct alignment contracts retain their configured concurrency.
    with fulltext_cache_singleflight("pdf_download", url):
        cached_pdf = get_pdf_by_url(url)
        pdf_cache_hit = bool(cached_pdf)
        if cached_pdf:
            data = bytes(cached_pdf.get("data") or b"")
            final_url = _normalized_http_url(cached_pdf.get("final_url")) or _normalized_http_url(url)
            content_type = str(cached_pdf.get("content_type") or "application/pdf").lower()
            etag = str(cached_pdf.get("etag") or "")
            last_modified = str(cached_pdf.get("last_modified") or "")
        else:
            headers = {"User-Agent": "qwen-zhikan-papergraph/0.1"}
            headers.update({str(key): str(value) for key, value in (request_headers or {}).items() if str(key)})
            request = Request(url, headers=headers)
            context = ssl_context()
            try:
                with fulltext_host_slot(url):
                    with urlopen(
                        request,
                        timeout=max(1.0, min(float(timeout_seconds or 12.0), 30.0)),
                        context=context,
                    ) as response:
                        final_url = _normalized_http_url(response.geturl()) or _normalized_http_url(url)
                        content_type = str(response.headers.get("Content-Type") or "").lower()
                        etag = str(response.headers.get("ETag") or "")
                        last_modified = str(response.headers.get("Last-Modified") or "")
                        data = response.read(max_bytes + 1)
            except HTTPError as exc:
                error = RuntimeError(f"HTTP {exc.code}: PDF fetch failed")
                setattr(error, "http_status", int(exc.code))
                put_pdf_failure(url, error)
                raise error from exc
            except URLError as exc:
                error = RuntimeError(f"URL error: {exc.reason}")
                put_pdf_failure(url, error)
                raise error from exc
            except TimeoutError as exc:
                error = RuntimeError(f"PDF fetch timed out: {exc}")
                put_pdf_failure(url, error)
                raise error from exc
            except Exception as exc:
                put_pdf_failure(url, exc)
                raise
        if len(data) > max_bytes:
            raise RuntimeError(f"PDF exceeds {max_bytes} byte safety limit")
        if not data.lstrip().startswith(b"%PDF-"):
            error = RuntimeError(
                "PDF fetch returned non-PDF content"
                + (f" (content_type={content_type})" if content_type else "")
            )
            setattr(error, "http_status", 200)
            setattr(error, "content_type", content_type)
            put_pdf_failure(url, error, non_pdf=True)
            raise error
        if not cached_pdf:
            put_pdf_by_url(
                url,
                data,
                final_url=final_url,
                content_type=content_type,
                etag=etag,
                last_modified=last_modified,
            )
    metadata = dict(paper_metadata or {})
    metadata.setdefault("source_url", normalize_space(final_url))
    content_hash = hashlib.sha256(data).hexdigest()
    selected_keywords = extraction_keywords(metadata, sub_hypothesis)
    extraction_keywords_hash = hashlib.sha256(
        json.dumps(selected_keywords, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    cache_context = extraction_cache_context or {}
    excerpt_key_fields = {
        "content_hash": content_hash,
        "extractor_version": PDF_EXCERPT_EXTRACTOR_VERSION,
        "alignment_contract_hash": str(cache_context.get("alignment_contract_hash") or ""),
        "extraction_keywords_hash": extraction_keywords_hash,
        "max_output_chars": int(max_output_chars),
    }
    cached_excerpt = get_excerpt(**excerpt_key_fields)
    excerpt_cache_hit = bool(cached_excerpt)
    markdown_cache_hit = False
    if cached_excerpt:
        cached_result = cached_excerpt.get("result")
        extracted = dict(cached_result) if isinstance(cached_result, dict) else {}
    else:
        excerpt_lock_key = json.dumps(excerpt_key_fields, sort_keys=True, separators=(",", ":"))
        with fulltext_cache_singleflight("excerpt", excerpt_lock_key):
            cached_excerpt = get_excerpt(**excerpt_key_fields)
            if cached_excerpt:
                cached_result = cached_excerpt.get("result")
                extracted = dict(cached_result) if isinstance(cached_result, dict) else {}
                excerpt_cache_hit = True
            else:
                with FULLTEXT_PARSE_SEMAPHORE:
                    extracted = extract_pdf_content(
                        data,
                        paper_metadata=metadata,
                        sub_hypothesis=sub_hypothesis,
                        max_output_chars=max_output_chars,
                    )
                put_excerpt(extracted, **excerpt_key_fields)
    report = extracted.get("report") if isinstance(extracted.get("report"), dict) else {}
    report["source_url"] = normalize_space(final_url)
    report["requested_url"] = normalize_space(url)
    report["content_type"] = content_type
    report["content_hash"] = content_hash
    report["pdf_cache_hit"] = pdf_cache_hit
    report["markdown_cache_hit"] = markdown_cache_hit
    report["excerpt_cache_hit"] = excerpt_cache_hit
    report["pdf_response_validators"] = {
        "etag": etag,
        "last_modified": last_modified,
    }
    extracted["report"] = report
    return extracted


class PdfTextExcerpt(str):
    def __new__(cls, text: str, report: dict[str, Any] | None = None):
        value = super().__new__(cls, text)
        value.report = dict(report or {})
        return value


def fetch_pdf_text_excerpt(
    url: str,
    max_bytes: int = 20_000_000,
    max_pages: int | None = None,
    timeout_seconds: float = 12.0,
    paper_metadata: dict[str, Any] | None = None,
    sub_hypothesis: str | dict[str, Any] | None = None,
    extraction_cache_context: dict[str, Any] | None = None,
    request_headers: dict[str, str] | None = None,
) -> PdfTextExcerpt:
    output_limit = 120_000
    if max_pages is not None:
        output_limit = max(8_000, min(160_000, int(max_pages) * 20_000))
    extracted = fetch_pdf_content(
        url,
        paper_metadata=paper_metadata,
        sub_hypothesis=sub_hypothesis,
        max_bytes=max_bytes,
        max_output_chars=output_limit,
        timeout_seconds=timeout_seconds,
        extraction_cache_context=extraction_cache_context,
        request_headers=request_headers,
    )
    return PdfTextExcerpt(
        str(extracted.get("text") or ""),
        extracted.get("report") if isinstance(extracted.get("report"), dict) else {},
    )

def merge_nonempty(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    try:
        from ._utils import normalize_space
    except ImportError:
        from _utils import normalize_space
    merged = dict(base)
    for key, value in overlay.items():
        if isinstance(value, list):
            if value and not merged.get(key):
                merged[key] = value
            continue
        text = normalize_space(str(value or ""))
        if not text:
            continue
        existing = normalize_space(str(merged.get(key) or ""))
        if not existing or (key in {"abstract", "conclusion"} and len(text) > len(existing)):
            merged[key] = value
    return merged

def http_get_text(url: str, headers: dict[str, str] | None = None, timeout: float = 20.0) -> str:
    try:
        from ._utils import trim_text
    except ImportError:
        from _utils import trim_text
    request = Request(url, headers=headers or {})
    context = ssl_context()
    try:
        with urlopen(request, timeout=timeout, context=context) as response:
            encoding = response.headers.get_content_charset() or "utf-8"
            return response.read().decode(encoding, errors="replace")
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace") if hasattr(exc, "read") else ""
        retry_after = exc.headers.get("Retry-After") if getattr(exc, "headers", None) else ""
        retry_hint = f" retry_after={retry_after}" if retry_after else ""
        error = RuntimeError(f"HTTP {exc.code}:{retry_hint} {trim_text(body, 500)}")
        setattr(error, "http_status", int(exc.code))
        if retry_after:
            parsed_retry_after = retry_after_header_seconds(retry_after)
            if parsed_retry_after is not None:
                setattr(error, "retry_after_seconds", parsed_retry_after)
        raise error from exc
    except URLError as exc:
        raise RuntimeError(f"URL error: {exc.reason}") from exc

def http_get_json(url: str, headers: dict[str, str] | None = None, timeout: float = 20.0) -> dict[str, Any]:
    text = http_get_text(url, headers=headers, timeout=timeout)
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"JSON parse failed: {exc}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("JSON response is not an object")
    return payload


def http_post_json_text(
    url: str,
    payload: dict[str, Any],
    headers: dict[str, str] | None = None,
    timeout: float = 20.0,
) -> str:
    try:
        from ._utils import trim_text
    except ImportError:
        from _utils import trim_text
    request_headers = {"Content-Type": "application/json", **(headers or {})}
    request = Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers=request_headers,
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout, context=ssl_context()) as response:
            encoding = response.headers.get_content_charset() or "utf-8"
            return response.read().decode(encoding, errors="replace")
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace") if hasattr(exc, "read") else ""
        retry_after = exc.headers.get("Retry-After") if getattr(exc, "headers", None) else ""
        retry_hint = f" retry_after={retry_after}" if retry_after else ""
        error = RuntimeError(f"HTTP {exc.code}:{retry_hint} {trim_text(body, 500)}")
        setattr(error, "http_status", int(exc.code))
        if retry_after:
            parsed_retry_after = retry_after_header_seconds(retry_after)
            if parsed_retry_after is not None:
                setattr(error, "retry_after_seconds", parsed_retry_after)
        raise error from exc
    except URLError as exc:
        raise RuntimeError(f"URL error: {exc.reason}") from exc


def semantic_scholar_safe_request_diagnostics(url: str) -> dict[str, Any]:
    """Describe an SS request without exposing credentials or full field data."""
    parsed = urlsplit(str(url or ""))
    params = parse_qs(parsed.query)
    return {
        "endpoint": parsed.path,
        "query": str((params.get("query") or [""])[0])[:180],
        "limit": str((params.get("limit") or [""])[0]),
        "offset": str((params.get("offset") or [""])[0]),
        "field_count": len(str((params.get("fields") or [""])[0]).split(","))
        if params.get("fields")
        else 0,
    }


def semantic_scholar_get_json(
    url: str,
    headers: dict[str, str] | None = None,
    timeout: float = 20.0,
    retry_budget: SemanticScholarRetryBudget | None = None,
    traffic_class: str = "detail",
    request_payload: dict[str, Any] | None = None,
    fast_fail_circuit: bool = False,
) -> dict[str, Any]:
    cache_key = url
    if request_payload is not None:
        body_hash = hashlib.sha256(
            json.dumps(request_payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
        ).hexdigest()[:24]
        cache_key = f"{url}#post={body_hash}"
    cached = semantic_scholar_cache_get(cache_key)
    if cached is not None:
        log_event("SCIENCE", "semantic_scholar_cache_hit")
        return json.loads(cached)
    normalized_traffic_class = str(traffic_class or "").strip().lower()
    is_graph = normalized_traffic_class == "graph"
    effective_fail_fast = (
        bool(SCIENCE_SEMANTIC_SCHOLAR_GRAPH_FAIL_FAST_ON_429)
        if is_graph
        else bool(SCIENCE_SEMANTIC_SCHOLAR_FAIL_FAST_ON_429)
    )
    if is_graph:
        # Graph expansion is optional enrichment, but it has its own retry and
        # partial-result policy.  Do not let the global search/detail
        # fail-fast policy erase already loaded graph context.
        if suspended := semantic_scholar_graph_traffic_suspension_error():
            raise RuntimeError(suspended)
        recent_suppression = semantic_scholar_recent_429_suppression_status()
        if bool(recent_suppression.get("suppressed")) and (
            effective_fail_fast or not SCIENCE_SEMANTIC_SCHOLAR_GRAPH_WAIT_ON_429
        ):
            error = RuntimeError(
                "semantic_scholar_recent_429_suppressed: optional graph traffic skipped; "
                f"reason={recent_suppression.get('reason')}"
            )
            setattr(error, "semantic_scholar_recent_429_suppressed", True)
            setattr(error, "retry_after_seconds", float(recent_suppression.get("remaining_seconds") or 0.0))
            raise error
    # A cached response is safe even while the live provider circuit is open.
    # Optional probes, however, must not wait through a provider-wide cooldown:
    # they are used only to discover an extra OA URL and should yield quickly
    # so DOI/OpenAlex/CORE/landing-page resolvers can continue.
    if fast_fail_circuit:
        recent_suppression = semantic_scholar_recent_429_suppression_status()
        if bool(recent_suppression.get("suppressed")):
            error = RuntimeError(
                "Semantic Scholar detail probe skipped: recent 429 suppression active; "
                f"reason={recent_suppression.get('reason')}"
            )
            setattr(error, "semantic_scholar_fast_fail_skipped", True)
            setattr(error, "semantic_scholar_recent_429_suppressed", True)
            setattr(error, "retry_after_seconds", float(recent_suppression.get("remaining_seconds") or 0.0))
            raise error
        circuit_open, retry_after = semantic_scholar_circuit_open()
        if circuit_open:
            error = RuntimeError(
                "Semantic Scholar optional detail probe skipped: "
                f"circuit open; retry_after_seconds={retry_after:.1f}"
            )
            setattr(error, "semantic_scholar_fast_fail_skipped", True)
            setattr(error, "retry_after_seconds", retry_after)
            raise error
    if effective_fail_fast:
        circuit_open, retry_after = semantic_scholar_circuit_open()
        if circuit_open:
            log_event(
                "SCIENCE",
                "semantic_scholar_429_fail_fast_circuit_skip",
                reason="circuit_open_before_uncached_request",
                retry_after_seconds=round(retry_after, 2),
                traffic_class=str(traffic_class or ""),
                **semantic_scholar_safe_request_diagnostics(url),
            )
            error = RuntimeError(
                "Semantic Scholar fail-fast skip: "
                f"circuit open; retry_after_seconds={retry_after:.1f}"
            )
            setattr(error, "semantic_scholar_fast_fail_skipped", True)
            setattr(error, "retry_after_seconds", retry_after)
            raise error
    if is_graph:
        if SCIENCE_SEMANTIC_SCHOLAR_GRAPH_WAIT_ON_429:
            waited = wait_for_semantic_scholar_circuit_if_needed(
                "graph_pre_request",
                max_total_wait_seconds=float(SCIENCE_SEMANTIC_SCHOLAR_GRAPH_MAX_WAIT_SECONDS),
            )
            if waited is False:
                circuit_open, retry_after = semantic_scholar_circuit_open()
                error = RuntimeError(
                    "semantic_scholar_graph_deferred_by_active_circuit: "
                    f"retry_after_seconds={retry_after:.1f}; "
                    f"max_wait_seconds={float(SCIENCE_SEMANTIC_SCHOLAR_GRAPH_MAX_WAIT_SECONDS):.1f}"
                )
                setattr(error, "semantic_scholar_graph_deferred_by_active_circuit", True)
                setattr(error, "retry_after_seconds", retry_after if circuit_open else 0.0)
                raise error
        else:
            circuit_open, retry_after = semantic_scholar_circuit_open()
            if circuit_open:
                error = RuntimeError(
                    "semantic_scholar_graph_deferred_by_active_circuit: "
                    f"graph_wait_on_429_disabled; retry_after_seconds={retry_after:.1f}"
                )
                setattr(error, "semantic_scholar_graph_deferred_by_active_circuit", True)
                setattr(error, "retry_after_seconds", retry_after)
                raise error
    else:
        wait_for_semantic_scholar_circuit_if_needed("pre_request")
    budget = retry_budget or SemanticScholarRetryBudget(
        limit=semantic_scholar_retry_limit(),
        job_id="single_semantic_scholar_request",
    )
    request_attempt = 0
    while True:
        try:
            text = semantic_scholar_get_text(
                url,
                headers=headers,
                timeout=timeout,
                retry_attempt=request_attempt,
                circuit_checked=True,
                traffic_class=traffic_class,
                request_payload=request_payload,
            )
            semantic_scholar_cache_put(cache_key, text)
            return json.loads(text)
        except (RuntimeError, TimeoutError) as exc:
            if is_semantic_scholar_graph_unavailable_error(str(exc)):
                raise
            rate_limited = is_semantic_scholar_rate_limit_error(str(exc))
            transient_failure = is_semantic_scholar_transient_error(exc)
            if not rate_limited and not transient_failure:
                raise
            if transient_failure and not rate_limited:
                if budget.remaining <= 0:
                    log_event(
                        "SCIENCE",
                        "semantic_scholar_transient_retries_exhausted",
                        attempt=request_attempt + 1,
                        retry_limit=budget.limit,
                        retries_used=budget.retries_used,
                        retry_scope="provider_batch" if retry_budget is not None else "single_request",
                        job_id=budget.job_id,
                        error=str(exc)[:300],
                        **semantic_scholar_safe_request_diagnostics(url),
                    )
                    raise RuntimeError(
                        f"Semantic Scholar transient failure after {request_attempt + 1} request attempts; "
                        f"provider_batch_retries={budget.retries_used}/{budget.limit}: {exc}"
                    ) from exc
                budget.retries_used += 1
                request_attempt += 1
                retry_wait = semantic_scholar_transient_retry_wait_seconds(request_attempt)
                log_event(
                    "SCIENCE",
                    "semantic_scholar_transient_retry_scheduled",
                    attempt=request_attempt,
                    max_attempts=budget.limit + 1,
                    retries_used=budget.retries_used,
                    retry_budget_remaining=budget.remaining,
                    retry_scope="provider_batch" if retry_budget is not None else "single_request",
                    job_id=budget.job_id,
                    wait_seconds=round(retry_wait, 2),
                    error=str(exc)[:300],
                    **semantic_scholar_safe_request_diagnostics(url),
                )
                time.sleep(retry_wait)
                continue

            budget.rate_limit_responses += 1
            request_diagnostics = semantic_scholar_safe_request_diagnostics(url)
            log_event(
                "SCIENCE",
                "semantic_scholar_429_response_received",
                job_id=budget.job_id,
                request_kind=budget.request_kind or "standalone",
                request_attempt=request_attempt + 1,
                http_status=int(getattr(exc, "http_status", 429) or 429),
                retry_after_seconds=getattr(exc, "retry_after_seconds", None),
                response_summary=str(exc)[:300],
                **request_diagnostics,
            )
            delay = semantic_scholar_backoff_seconds(request_attempt, exc)
            cooldown = float(getattr(exc, "semantic_scholar_cooldown_seconds", 0.0) or 0.0)
            if not bool(getattr(exc, "semantic_scholar_429_registered", False)):
                register_semantic_scholar_429(delay)
            if cooldown <= 0:
                cooldown = semantic_scholar_circuit_seconds(delay)
            response_ceiling_reached = (
                budget.max_rate_limit_responses > 0
                and budget.rate_limit_responses >= budget.max_rate_limit_responses
            )
            if (
                effective_fail_fast
                or budget.remaining <= 0
                or response_ceiling_reached
            ):
                _, retry_after = semantic_scholar_circuit_open()
                log_event(
                    "SCIENCE",
                    "semantic_scholar_429_retries_exhausted",
                    attempt=request_attempt + 1,
                    retry_limit=budget.limit,
                    retries_used=budget.retries_used,
                    rate_limit_responses=budget.rate_limit_responses,
                    max_rate_limit_responses=budget.max_rate_limit_responses,
                    retry_scope="provider_batch" if retry_budget is not None else "single_request",
                    job_id=budget.job_id,
                    retry_after_seconds=round(retry_after, 2),
                    fail_fast=bool(effective_fail_fast),
                    traffic_class=normalized_traffic_class or "detail",
                )
                raise RuntimeError(
                    f"Semantic Scholar rate limited after {request_attempt + 1} request attempts; "
                    f"provider_batch_retries={budget.retries_used}/{budget.limit}; "
                    f"circuit_retry_after_seconds={retry_after:.1f}: {exc}"
                ) from exc
            budget.retries_used += 1
            request_attempt += 1
            retry_wait = max(cooldown, semantic_scholar_retry_wait_seconds(delay))
            log_event(
                "SCIENCE",
                "semantic_scholar_429_retry_scheduled",
                attempt=request_attempt,
                max_attempts=budget.limit + 1,
                retries_used=budget.retries_used,
                retry_budget_remaining=budget.remaining,
                retry_scope="provider_batch" if retry_budget is not None else "single_request",
                job_id=budget.job_id,
                wait_seconds=round(retry_wait, 2),
                fail_fast=False,
                traffic_class=normalized_traffic_class or "detail",
            )
            if is_graph:
                if not SCIENCE_SEMANTIC_SCHOLAR_GRAPH_WAIT_ON_429:
                    raise RuntimeError(
                        "semantic_scholar_graph_deferred_by_active_circuit: "
                        "graph_wait_on_429_disabled after provider 429"
                    ) from exc
                waited = wait_for_semantic_scholar_circuit_if_needed(
                    "graph_retry",
                    max_total_wait_seconds=float(SCIENCE_SEMANTIC_SCHOLAR_GRAPH_MAX_WAIT_SECONDS),
                )
                if waited is False:
                    _, retry_after = semantic_scholar_circuit_open()
                    raise RuntimeError(
                        "semantic_scholar_graph_deferred_by_active_circuit: "
                        f"max_wait_seconds={float(SCIENCE_SEMANTIC_SCHOLAR_GRAPH_MAX_WAIT_SECONDS):.1f}; "
                        f"retry_after_seconds={retry_after:.1f}"
                    ) from exc
            else:
                wait_for_semantic_scholar_circuit_if_needed("retry")

def wait_for_semantic_scholar_circuit_if_needed(
    reason: str = "request",
    *,
    max_total_wait_seconds: float | None = None,
) -> bool:
    started_at = time.time()
    while True:
        circuit_open, retry_after = semantic_scholar_circuit_open()
        if not circuit_open:
            return True
        wait_seconds = min(max(float(retry_after), 0.01), 60.0)
        if max_total_wait_seconds is not None:
            remaining_budget = max(0.0, float(max_total_wait_seconds) - (time.time() - started_at))
            if remaining_budget <= 0.0:
                log_event(
                    "SCIENCE",
                    "semantic_scholar_circuit_wait_budget_exhausted",
                    reason=reason,
                    retry_after_seconds=round(retry_after, 2),
                    max_total_wait_seconds=round(float(max_total_wait_seconds), 2),
                )
                return False
            wait_seconds = min(wait_seconds, remaining_budget)
        log_event(
            "SCIENCE",
            "semantic_scholar_circuit_wait",
            reason=reason,
            retry_after_seconds=round(retry_after, 2),
            wait_seconds=round(wait_seconds, 2),
        )
        time.sleep(wait_seconds)


def semantic_scholar_retry_limit() -> int:
    # Keep the provider available through transient throttling, while still
    # bounding one query so a persistent outage can be reported to the caller.
    return min(10, max(0, int(SCIENCE_SEMANTIC_SCHOLAR_RETRY_LIMIT)))


def semantic_scholar_search_retry_limit() -> int:
    """Shared retry ceiling for one base/review provider batch."""
    return min(4, max(0, int(SCIENCE_SEMANTIC_SCHOLAR_SEARCH_RETRY_LIMIT)))

def semantic_scholar_retry_wait_seconds(delay: float) -> float:
    """Return actual wait time for retry, respecting the computed delay.

    Floor: strict_interval (1.5s) to avoid hammering.
    Cap: 60s to avoid excessive waits.
    """
    floor = semantic_scholar_strict_interval_seconds()
    return max(floor, min(float(delay), 60.0))


def semantic_scholar_transient_retry_wait_seconds(attempt: int) -> float:
    """Short bounded backoff for timeouts and provider-side 5xx responses."""
    return min(15.0, 2.0 * (2 ** max(0, int(attempt) - 1)))

def semantic_scholar_strict_interval_seconds() -> float:
    return max(1.5, float(SCIENCE_SEMANTIC_SCHOLAR_MIN_INTERVAL_SECONDS))

def semantic_scholar_retry_buffer_seconds() -> float:
    return 0.0

def semantic_scholar_circuit_open() -> tuple[bool, float]:
    try:
        from ._models import SEMANTIC_SCHOLAR_CIRCUIT_LOCK
    except ImportError:
        from _models import SEMANTIC_SCHOLAR_CIRCUIT_LOCK
    global SEMANTIC_SCHOLAR_COOLDOWN_UNTIL
    maximum = semantic_scholar_429_max_cooldown_seconds()
    with SEMANTIC_SCHOLAR_CIRCUIT_LOCK:
        memory_remaining = SEMANTIC_SCHOLAR_COOLDOWN_UNTIL - time.monotonic()
        if memory_remaining > maximum:
            SEMANTIC_SCHOLAR_COOLDOWN_UNTIL = time.monotonic() + maximum
            memory_remaining = maximum
    state = read_semantic_scholar_rate_state()
    persisted_until = float(state.get("cooldown_until_wall_time") or 0.0)
    persisted_remaining = persisted_until - time.time()
    # A rate-state can survive a code upgrade or another workspace.  Do not
    # let an old 300-second value keep this process stalled after the bounded
    # 60/120-second policy has taken effect.  Persist the normalization so a
    # wait loop cannot reapply the cap three times (120 + 120 + 60 seconds).
    if persisted_remaining > maximum:
        state["cooldown_until_wall_time"] = time.time() + maximum
        write_semantic_scholar_rate_state(state)
        persisted_remaining = maximum
    remaining = max(memory_remaining, persisted_remaining)
    return remaining > 0, max(0.0, remaining)


def semantic_scholar_recent_429_suppression_status(
    *,
    suppression_seconds: float = 900.0,
) -> dict[str, Any]:
    """Return a non-blocking suppression decision for optional S2 traffic.

    The short circuit cooldown protects the provider immediately after a 429.
    A separate recent-429 suppression protects the pipeline from re-probing
    optional Semantic Scholar lanes every 120 seconds when the keyed or
    anonymous quota is plainly saturated.  Callers should skip optional work
    and continue with OpenAlex/PubMed/CORE/DOI landing-page resolvers instead
    of sleeping through this window.
    """

    state = read_semantic_scholar_rate_state()
    try:
        consecutive = int(state.get("consecutive_429_count") or 0)
    except (TypeError, ValueError):
        consecutive = 0
    threshold = 3 if SEMANTIC_SCHOLAR_API_KEY else 2
    if consecutive < threshold:
        return {
            "suppressed": False,
            "consecutive_429_count": consecutive,
            "threshold": threshold,
            "remaining_seconds": 0.0,
            "reason": "below_recent_429_suppression_threshold",
        }
    try:
        last_429 = float(state.get("last_429_wall_time") or 0.0)
    except (TypeError, ValueError):
        last_429 = 0.0
    if last_429 <= 0:
        try:
            cooldown_until = float(state.get("cooldown_until_wall_time") or 0.0)
        except (TypeError, ValueError):
            cooldown_until = 0.0
        if cooldown_until > 0:
            last_429 = cooldown_until - semantic_scholar_429_max_cooldown_seconds()
    if last_429 <= 0:
        return {
            "suppressed": False,
            "consecutive_429_count": consecutive,
            "threshold": threshold,
            "remaining_seconds": 0.0,
            "reason": "recent_429_timestamp_missing",
        }
    remaining = max(0.0, last_429 + max(0.0, float(suppression_seconds)) - time.time())
    if remaining <= 0:
        return {
            "suppressed": False,
            "consecutive_429_count": consecutive,
            "threshold": threshold,
            "remaining_seconds": 0.0,
            "reason": "recent_429_suppression_window_expired",
        }
    return {
        "suppressed": True,
        "auth_mode": "api_key" if SEMANTIC_SCHOLAR_API_KEY else "anonymous",
        "consecutive_429_count": consecutive,
        "threshold": threshold,
        "remaining_seconds": remaining,
        "reason": f"recent_429_suppressed_{consecutive}_{round(remaining, 1)}s",
    }


def semantic_scholar_l2_supplement_health() -> tuple[bool, str]:
    """Return whether an optional L2 SS request may use shared traffic.

    L2 supplementation is deliberately lower priority than broad discovery,
    paper detail resolution, and citation-graph construction.  It must never
    wait through an existing provider cooldown or consume the final run-budget
    slot just to chase a protected quota.
    """
    recent_suppression = semantic_scholar_recent_429_suppression_status()
    if bool(recent_suppression.get("suppressed")):
        return False, str(recent_suppression.get("reason") or "recent_429_suppressed")
    circuit_open, cooldown_seconds = semantic_scholar_circuit_open()
    if circuit_open:
        return False, f"rate_limited_circuit_open_{round(cooldown_seconds, 2)}s"
    status = semantic_scholar_run_budget_status()
    if bool(status.get("active")) and int(status.get("remaining") or 0) < 1:
        return False, "run_budget_exhausted"
    if bool(status.get("graph_suspended")):
        return False, "graph_traffic_suspended"
    return True, "healthy"


def semantic_scholar_429_first_cooldown_seconds() -> float:
    """The fixed wait after the first consecutive Semantic Scholar 429."""
    return max(1.0, min(float(SCIENCE_SEMANTIC_SCHOLAR_429_FIRST_COOLDOWN_SECONDS), 60.0))


def semantic_scholar_429_max_cooldown_seconds() -> float:
    """Hard upper bound for any Semantic Scholar 429 recovery wait."""
    return max(
        semantic_scholar_429_first_cooldown_seconds(),
        min(float(SCIENCE_SEMANTIC_SCHOLAR_429_MAX_COOLDOWN_SECONDS), 120.0),
    )


def semantic_scholar_circuit_seconds(delay: float) -> float:
    """Return the first-429 circuit wait, bounded independently of backoff."""
    _ = delay
    return semantic_scholar_429_first_cooldown_seconds()


def semantic_scholar_adaptive_circuit_seconds(delay: float, consecutive_429_count: int) -> float:
    # Keep later consecutive responses in a fixed 120s recovery state rather
    # than doubling 60 -> 120 -> 240 -> 300.  The latter was the source of the
    # unexpected five-minute waits in graph expansion.
    if max(1, int(consecutive_429_count)) <= 1:
        return semantic_scholar_circuit_seconds(delay)
    return semantic_scholar_429_max_cooldown_seconds()

def register_semantic_scholar_429(delay: float, process_lock_held: bool = False) -> float:
    if process_lock_held:
        return register_semantic_scholar_429_locked(delay)
    try:
        from ._models import SEMANTIC_SCHOLAR_RATE_LOCK
    except ImportError:
        from _models import SEMANTIC_SCHOLAR_RATE_LOCK
    with SEMANTIC_SCHOLAR_RATE_LOCK:
        release = acquire_semantic_scholar_process_lock()
        try:
            return register_semantic_scholar_429_locked(delay)
        finally:
            release()


def register_semantic_scholar_429_locked(delay: float) -> float:
    try:
        from ._models import SEMANTIC_SCHOLAR_CIRCUIT_LOCK
    except ImportError:
        from _models import SEMANTIC_SCHOLAR_CIRCUIT_LOCK
    global SEMANTIC_SCHOLAR_429_COUNT, SEMANTIC_SCHOLAR_CONSECUTIVE_429_COUNT, SEMANTIC_SCHOLAR_COOLDOWN_UNTIL
    state = read_semantic_scholar_rate_state()
    consecutive_429_count = int(state.get("consecutive_429_count") or 0) + 1
    cooldown = semantic_scholar_adaptive_circuit_seconds(delay, consecutive_429_count)
    with SEMANTIC_SCHOLAR_CIRCUIT_LOCK:
        SEMANTIC_SCHOLAR_429_COUNT += 1
        SEMANTIC_SCHOLAR_CONSECUTIVE_429_COUNT += 1
        if cooldown > 0:
            SEMANTIC_SCHOLAR_COOLDOWN_UNTIL = time.monotonic() + cooldown
    # Replace, rather than extend, an older cooldown.  This clamps stale
    # shared-state values produced before the 120-second maximum existed.
    state["cooldown_until_wall_time"] = time.time() + cooldown
    state["last_429_wall_time"] = time.time()
    state["last_429_cooldown_seconds"] = cooldown
    state["consecutive_429_count"] = consecutive_429_count
    state["consecutive_success_count"] = 0
    write_semantic_scholar_rate_state(state)
    log_event(
        "SCIENCE",
        "semantic_scholar_429_registered",
        cooldown_seconds=round(cooldown, 2),
        count=SEMANTIC_SCHOLAR_429_COUNT,
        consecutive_count=consecutive_429_count,
    )
    return cooldown


def reset_semantic_scholar_consecutive_429_locked() -> None:
    try:
        from ._models import SEMANTIC_SCHOLAR_CIRCUIT_LOCK
    except ImportError:
        from _models import SEMANTIC_SCHOLAR_CIRCUIT_LOCK
    global SEMANTIC_SCHOLAR_CONSECUTIVE_429_COUNT
    state = read_semantic_scholar_rate_state()
    success_count = int(state.get("consecutive_success_count") or 0) + 1
    state["consecutive_success_count"] = success_count
    state["last_success_wall_time"] = time.time()
    threshold = max(1, int(SCIENCE_SEMANTIC_SCHOLAR_SUCCESS_RESET_THRESHOLD))
    if success_count >= threshold:
        with SEMANTIC_SCHOLAR_CIRCUIT_LOCK:
            SEMANTIC_SCHOLAR_CONSECUTIVE_429_COUNT = 0
        state["consecutive_429_count"] = 0
        state["consecutive_success_count"] = 0
        state["cooldown_until_wall_time"] = 0.0
    write_semantic_scholar_rate_state(state)

def semantic_scholar_skip_block(query: str, provider: str = "semantic_scholar") -> dict[str, Any] | None:
    if not SCIENCE_SEMANTIC_SCHOLAR_FAIL_FAST_ON_429:
        return None
    circuit_open, retry_after = semantic_scholar_circuit_open()
    if not circuit_open:
        return None
    return {
        "provider": provider,
        "query": query,
        "status": "rate_limited_skipped",
        "error": f"Semantic Scholar circuit open; retry_after_seconds={retry_after:.1f}",
        "rate_limited": True,
        "results": [],
    }

def arxiv_circuit_open() -> tuple[bool, float]:
    try:
        from ._models import ARXIV_CIRCUIT_LOCK
    except ImportError:
        from _models import ARXIV_CIRCUIT_LOCK
    with ARXIV_CIRCUIT_LOCK:
        remaining = ARXIV_COOLDOWN_UNTIL - time.monotonic()
    return remaining > 0, max(0.0, remaining)

def arxiv_circuit_seconds() -> float:
    configured = max(0.0, float(SCIENCE_ARXIV_CIRCUIT_SECONDS))
    floor = max(15.0, float(SCIENCE_ARXIV_MIN_INTERVAL_SECONDS) * 4)
    return min(max(configured, floor), 300.0)

def register_arxiv_429(error: str = "") -> None:
    try:
        from ._models import ARXIV_CIRCUIT_LOCK
        from ._utils import trim_text
    except ImportError:
        from _models import ARXIV_CIRCUIT_LOCK
        from _utils import trim_text
    global ARXIV_429_COUNT, ARXIV_COOLDOWN_UNTIL
    cooldown = arxiv_circuit_seconds()
    with ARXIV_CIRCUIT_LOCK:
        ARXIV_429_COUNT += 1
        ARXIV_COOLDOWN_UNTIL = max(ARXIV_COOLDOWN_UNTIL, time.monotonic() + cooldown)
    log_event(
        "SCIENCE",
        "arxiv_circuit_open",
        cooldown_seconds=round(cooldown, 2),
        count=ARXIV_429_COUNT,
        error=trim_text(error, 180),
    )

def arxiv_skip_block(query: str) -> dict[str, Any] | None:
    circuit_open, retry_after = arxiv_circuit_open()
    if not circuit_open:
        return None
    return {
        "provider": "arxiv",
        "query": query,
        "status": "rate_limited_skipped",
        "error": f"arXiv circuit open; retry_after_seconds={retry_after:.1f}",
        "rate_limited": True,
        "results": [],
    }

def semantic_scholar_backoff_seconds(attempt: int, error: Any = "") -> float:
    """Compute backoff delay for a 429 retry.

    Priority:
    1. Retry-After supplied by Semantic Scholar (bounded to 120s).
    2. Exponential backoff from a conservative four-interval floor.
    3. Configured SCIENCE_SEMANTIC_SCHOLAR_429_BACKOFF_SECONDS as floor.
    """
    floor = semantic_scholar_strict_interval_seconds()
    configured = max(floor * 4.0, float(SCIENCE_SEMANTIC_SCHOLAR_429_BACKOFF_SECONDS))
    retry_after = semantic_scholar_retry_after_seconds(error) if error else None
    if retry_after is not None and retry_after > 0:
        return max(floor, min(retry_after, semantic_scholar_429_max_cooldown_seconds()))
    exp_delay = configured * (2 ** min(max(0, int(attempt)), 3))
    return min(exp_delay, semantic_scholar_429_max_cooldown_seconds())

def semantic_scholar_get_text(
    url: str,
    headers: dict[str, str] | None = None,
    timeout: float = 20.0,
    retry_attempt: int = 0,
    circuit_checked: bool = False,
    traffic_class: str = "detail",
    request_payload: dict[str, Any] | None = None,
) -> str:
    try:
        from ._models import SEMANTIC_SCHOLAR_RATE_LOCK
    except ImportError:
        from _models import SEMANTIC_SCHOLAR_RATE_LOCK
    log_semantic_scholar_key_status()
    if not circuit_checked:
        if str(traffic_class or "").strip().lower() == "graph":
            if SCIENCE_SEMANTIC_SCHOLAR_GRAPH_WAIT_ON_429:
                waited = wait_for_semantic_scholar_circuit_if_needed(
                    "graph_direct_request",
                    max_total_wait_seconds=float(SCIENCE_SEMANTIC_SCHOLAR_GRAPH_MAX_WAIT_SECONDS),
                )
                if waited is False:
                    raise RuntimeError(
                        "semantic_scholar_graph_deferred_by_active_circuit: "
                        f"max_wait_seconds={float(SCIENCE_SEMANTIC_SCHOLAR_GRAPH_MAX_WAIT_SECONDS):.1f}"
                    )
            else:
                circuit_open, retry_after = semantic_scholar_circuit_open()
                if circuit_open:
                    raise RuntimeError(
                        "semantic_scholar_graph_deferred_by_active_circuit: "
                        f"graph_wait_on_429_disabled; retry_after_seconds={retry_after:.1f}"
                    )
        else:
            wait_for_semantic_scholar_circuit_if_needed("direct_request")
    with SEMANTIC_SCHOLAR_RATE_LOCK:
        release = acquire_semantic_scholar_process_lock()
        try:
            if str(traffic_class or "").strip().lower() == "graph":
                if suspended := semantic_scholar_graph_traffic_suspension_error():
                    raise RuntimeError(suspended)
            reserve_semantic_scholar_run_request(traffic_class)
            reserve_semantic_scholar_request_slot()
            try:
                text = (
                    http_post_json_text(url, request_payload, headers=headers, timeout=timeout)
                    if request_payload is not None
                    else http_get_text(url, headers=headers, timeout=timeout)
                )
                reset_semantic_scholar_consecutive_429_locked()
                return text
            except RuntimeError as exc:
                # A run-level graph suspension may include the words "HTTP
                # 429" in its explanatory reason. It is not an HTTP response,
                # must not increment 429 counters, and must not schedule a
                # retry/cooldown.
                if is_semantic_scholar_rate_limit_error(str(exc)):
                    delay = semantic_scholar_backoff_seconds(retry_attempt, str(exc))
                    cooldown = register_semantic_scholar_429(delay, process_lock_held=True)
                    setattr(exc, "semantic_scholar_429_registered", True)
                    setattr(exc, "semantic_scholar_cooldown_seconds", cooldown)
                raise
        finally:
            release()

def arxiv_get_text(url: str, headers: dict[str, str] | None = None) -> str:
    wait_for_arxiv_rate_limit()
    global ARXIV_429_COUNT, ARXIV_TIMEOUT_COUNT
    # Circuit breaker: skip arxiv after too many consecutive timeouts
    if ARXIV_TIMEOUT_COUNT >= 15:
        log_event("SCIENCE", "arxiv_circuit_breaker_open",
                  timeout_count=ARXIV_TIMEOUT_COUNT, url=url[:80])
        raise RuntimeError(f"arxiv circuit breaker: {ARXIV_TIMEOUT_COUNT} consecutive timeouts, skipping")
    max_attempts = 3
    last_exc: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            result = http_get_text(url, headers=headers, timeout=45.0)
            # Success — reset consecutive timeout counter
            ARXIV_TIMEOUT_COUNT = 0
            return result
        except RuntimeError as exc:
            last_exc = exc
            error_text = str(exc)
            if is_rate_limit_error(error_text):
                register_arxiv_429(error_text)
                raise  # 429 propagates immediately
            # Timeout or connection error — retry with exponential backoff
            if attempt < max_attempts and is_arxiv_timeout(error_text):
                ARXIV_TIMEOUT_COUNT += 1
                delay = 2.0 * (2 ** (attempt - 1))  # 2s, 4s
                log_event("SCIENCE", "arxiv_timeout_retry", attempt=attempt,
                          max_attempts=max_attempts, delay_seconds=delay,
                          consecutive_timeouts=ARXIV_TIMEOUT_COUNT,
                          url=url[:80])
                import time as _time
                _time.sleep(delay)
                continue
            # Non-retryable error
            ARXIV_TIMEOUT_COUNT += 1
            raise
    # Should not reach here, but just in case
    ARXIV_TIMEOUT_COUNT += 1
    if last_exc:
        raise last_exc
    raise RuntimeError("arxiv_get_text: unexpected fallthrough")


def is_arxiv_timeout(error: str) -> bool:
    """Check if an error message indicates an arxiv timeout."""
    lower = error.lower()
    return any(term in lower for term in ("timed out", "timeout", "read operation", "connection"))


def retry_after_header_seconds(value: Any) -> float | None:
    """Parse Retry-After delta-seconds or an HTTP-date without discarding it."""
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return max(0.0, float(text))
    except ValueError:
        pass
    try:
        from email.utils import parsedate_to_datetime

        retry_at = parsedate_to_datetime(text)
        if retry_at.tzinfo is None:
            from datetime import timezone

            retry_at = retry_at.replace(tzinfo=timezone.utc)
        return max(0.0, retry_at.timestamp() - time.time())
    except (TypeError, ValueError, OverflowError):
        return None

def semantic_scholar_retry_after_seconds(error: Any) -> float | None:
    attached = getattr(error, "retry_after_seconds", None)
    if attached is not None:
        try:
            return max(0.0, float(attached))
        except (TypeError, ValueError):
            pass
    match = re.search(
        r"retry_after(?:_seconds)?=([0-9]+(?:\.[0-9]+)?)",
        str(error),
        flags=re.IGNORECASE,
    )
    if not match:
        return None
    try:
        return float(match.group(1))
    except ValueError:
        return None

def semantic_scholar_cache_get(url: str) -> str | None:
    try:
        from ._models import SEMANTIC_SCHOLAR_CACHE_LOCK
    except ImportError:
        from _models import SEMANTIC_SCHOLAR_CACHE_LOCK
    ttl = max(0.0, float(SCIENCE_SEMANTIC_SCHOLAR_CACHE_TTL_SECONDS))
    if ttl <= 0:
        return None
    with SEMANTIC_SCHOLAR_CACHE_LOCK:
        cached = SEMANTIC_SCHOLAR_RESPONSE_CACHE.get(url)
        if not cached:
            return None
        created_at, text = cached
        if time.time() - created_at > ttl:
            SEMANTIC_SCHOLAR_RESPONSE_CACHE.pop(url, None)
            return None
        return text

def semantic_scholar_cache_put(url: str, text: str) -> None:
    try:
        from ._models import SEMANTIC_SCHOLAR_CACHE_LOCK
    except ImportError:
        from _models import SEMANTIC_SCHOLAR_CACHE_LOCK
    ttl = max(0.0, float(SCIENCE_SEMANTIC_SCHOLAR_CACHE_TTL_SECONDS))
    if ttl <= 0:
        return
    with SEMANTIC_SCHOLAR_CACHE_LOCK:
        if len(SEMANTIC_SCHOLAR_RESPONSE_CACHE) > 512:
            oldest = sorted(SEMANTIC_SCHOLAR_RESPONSE_CACHE.items(), key=lambda item: item[1][0])[:64]
            for key, _ in oldest:
                SEMANTIC_SCHOLAR_RESPONSE_CACHE.pop(key, None)
        SEMANTIC_SCHOLAR_RESPONSE_CACHE[url] = (time.time(), text)

def log_semantic_scholar_key_status() -> None:
    global SEMANTIC_SCHOLAR_KEY_STATUS_LOGGED
    if SEMANTIC_SCHOLAR_KEY_STATUS_LOGGED:
        return
    SEMANTIC_SCHOLAR_KEY_STATUS_LOGGED = True
    try:
        from ._models import SEMANTIC_SCHOLAR_RATE_STATE_FILE
    except ImportError:
        from _models import SEMANTIC_SCHOLAR_RATE_STATE_FILE
    log_event(
        "SCIENCE",
        "semantic_scholar_key_status",
        configured=bool(SEMANTIC_SCHOLAR_API_KEY),
        auth_mode="api_key" if SEMANTIC_SCHOLAR_API_KEY else "anonymous",
        rate_scope=SEMANTIC_SCHOLAR_RATE_SCOPE,
        min_interval_seconds=semantic_scholar_strict_interval_seconds(),
        search_retry_limit=semantic_scholar_search_retry_limit(),
        standalone_retry_limit=semantic_scholar_retry_limit(),
        fail_fast_on_429=bool(SCIENCE_SEMANTIC_SCHOLAR_FAIL_FAST_ON_429),
        graph_fail_fast_on_429=bool(SCIENCE_SEMANTIC_SCHOLAR_GRAPH_FAIL_FAST_ON_429),
        graph_wait_on_429=bool(SCIENCE_SEMANTIC_SCHOLAR_GRAPH_WAIT_ON_429),
        graph_max_wait_seconds=float(SCIENCE_SEMANTIC_SCHOLAR_GRAPH_MAX_WAIT_SECONDS),
        shared_rate_state=str(SEMANTIC_SCHOLAR_RATE_STATE_FILE),
    )

def is_semantic_scholar_rate_limit_error(error: str) -> bool:
    if is_semantic_scholar_graph_unavailable_error(error):
        return False
    return is_rate_limit_error(error)


def is_semantic_scholar_transient_error(error: Any) -> bool:
    """Return whether a failed request is safe to retry within its batch budget."""
    if isinstance(error, TimeoutError):
        return True
    status = getattr(error, "http_status", None)
    try:
        if status is not None and 500 <= int(status) <= 599:
            return True
    except (TypeError, ValueError):
        pass
    text = str(error or "").lower()
    if re.search(r"\bhttp\s+5\d\d\b", text):
        return True
    return any(
        marker in text
        for marker in (
            "timed out",
            "timeout",
            "read operation timed out",
        )
    )


def is_semantic_scholar_graph_unavailable_error(error: str) -> bool:
    """Identify local graph-stop states, distinct from a provider HTTP 429."""
    text = str(error or "").lower()
    return any(
        marker in text
        for marker in (
            "semantic_scholar_graph_suspended",
            "semantic_scholar_graph_budget_exhausted",
            "semantic_scholar_graph_subhypothesis_budget_exhausted",
            "semantic_scholar_graph_stopped",
            "semantic_scholar_graph_deferred_by_active_circuit",
        )
    )

def is_rate_limit_error(error: str) -> bool:
    text = str(error).lower()
    return "429" in text or "too many requests" in text or "rate limit" in text

def is_semantic_scholar_not_found_error(error: str) -> bool:
    text = str(error).lower()
    return "http 404" in text or "paper with id" in text and "not found" in text

def wait_for_semantic_scholar_rate_limit() -> None:
    try:
        from ._models import SEMANTIC_SCHOLAR_RATE_LOCK
    except ImportError:
        from _models import SEMANTIC_SCHOLAR_RATE_LOCK
    global SEMANTIC_SCHOLAR_LAST_REQUEST_AT
    interval = semantic_scholar_strict_interval_seconds()
    if interval <= 0:
        return
    with SEMANTIC_SCHOLAR_RATE_LOCK:
        release = acquire_semantic_scholar_process_lock()
        try:
            reserve_semantic_scholar_request_slot()
        finally:
            release()


def reserve_semantic_scholar_request_slot() -> None:
    global SEMANTIC_SCHOLAR_LAST_REQUEST_AT
    interval = semantic_scholar_strict_interval_seconds()
    now_wall = time.time()
    persisted_at = read_semantic_scholar_rate_timestamp()
    if persisted_at > now_wall + interval:
        log_event(
            "SCIENCE",
            "semantic_scholar_rate_state_future_ignored",
            future_seconds=round(persisted_at - now_wall, 2),
            strict_interval_seconds=round(interval, 2),
        )
        persisted_at = 0.0
    last_wall = max(persisted_at, wall_time_from_monotonic(SEMANTIC_SCHOLAR_LAST_REQUEST_AT))
    wait_seconds = last_wall + interval - now_wall
    if wait_seconds > 0:
        log_event(
            "SCIENCE",
            "semantic_scholar_rate_limit",
            wait_ms=int(wait_seconds * 1000),
            scope="process_file_inflight",
        )
        time.sleep(wait_seconds)
    current_wall = time.time()
    SEMANTIC_SCHOLAR_LAST_REQUEST_AT = time.monotonic()
    write_semantic_scholar_rate_timestamp(current_wall)
    log_event(
        "SCIENCE",
        "semantic_scholar_request_dispatch",
        interval_seconds=round(interval, 2),
        scope="process_file_inflight",
        serialized=True,
    )

def wait_for_arxiv_rate_limit() -> None:
    try:
        from ._models import ARXIV_PROCESS_LOCK_DIR, ARXIV_RATE_LOCK, ARXIV_RATE_STATE_FILE
    except ImportError:
        from _models import ARXIV_PROCESS_LOCK_DIR, ARXIV_RATE_LOCK, ARXIV_RATE_STATE_FILE
    global ARXIV_LAST_REQUEST_AT
    interval = max(0.0, float(SCIENCE_ARXIV_MIN_INTERVAL_SECONDS))
    if interval <= 0:
        return
    with ARXIV_RATE_LOCK:
        release = acquire_provider_process_lock(ARXIV_PROCESS_LOCK_DIR, interval)
        try:
            now_wall = time.time()
            persisted_at = read_provider_rate_timestamp(ARXIV_RATE_STATE_FILE)
            last_wall = max(persisted_at, wall_time_from_monotonic(ARXIV_LAST_REQUEST_AT))
            wait_seconds = last_wall + interval - now_wall
            if wait_seconds > 0:
                log_event(
                    "SCIENCE",
                    "arxiv_rate_limit",
                    wait_ms=int(wait_seconds * 1000),
                    scope="process_file",
                )
                time.sleep(wait_seconds)
            current_wall = time.time()
            ARXIV_LAST_REQUEST_AT = time.monotonic()
            write_provider_rate_timestamp(
                ARXIV_RATE_STATE_FILE,
                current_wall,
                min_interval_seconds=SCIENCE_ARXIV_MIN_INTERVAL_SECONDS,
            )
        finally:
            release()

def wall_time_from_monotonic(monotonic_timestamp: float) -> float:
    if monotonic_timestamp <= 0:
        return 0.0
    return time.time() - max(0.0, time.monotonic() - monotonic_timestamp)

def read_semantic_scholar_rate_timestamp() -> float:
    return float(read_semantic_scholar_rate_state().get("last_request_wall_time") or 0.0)


def read_semantic_scholar_rate_state() -> dict[str, Any]:
    try:
        from ._models import SEMANTIC_SCHOLAR_RATE_STATE_FILE
    except ImportError:
        from _models import SEMANTIC_SCHOLAR_RATE_STATE_FILE
    try:
        raw = json.loads(SEMANTIC_SCHOLAR_RATE_STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return raw if isinstance(raw, dict) else {}

def write_semantic_scholar_rate_timestamp(timestamp: float) -> None:
    state = read_semantic_scholar_rate_state()
    state["last_request_wall_time"] = timestamp
    state["min_interval_seconds"] = semantic_scholar_strict_interval_seconds()
    write_semantic_scholar_rate_state(state)


def write_semantic_scholar_rate_state(state: dict[str, Any]) -> None:
    try:
        from ._models import SEMANTIC_SCHOLAR_RATE_STATE_FILE
    except ImportError:
        from _models import SEMANTIC_SCHOLAR_RATE_STATE_FILE
    try:
        SEMANTIC_SCHOLAR_RATE_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            **state,
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(time.time())),
        }
        SEMANTIC_SCHOLAR_RATE_STATE_FILE.write_text(
            json.dumps(payload, ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception as exc:
        log_event("SCIENCE", "provider_rate_state_write_failed", path=str(SEMANTIC_SCHOLAR_RATE_STATE_FILE), error=str(exc))

def read_provider_rate_timestamp(path: Path) -> float:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return float(raw.get("last_request_wall_time") or 0.0)
    except Exception:
        return 0.0

def write_provider_rate_timestamp(path: Path, timestamp: float, min_interval_seconds: float) -> None:
    try:
        SCIENCE_DIR.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "last_request_wall_time": timestamp,
                    "min_interval_seconds": min_interval_seconds,
                    "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(timestamp)),
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
    except Exception as exc:
        log_event("SCIENCE", "provider_rate_state_write_failed", path=str(path), error=str(exc))

def acquire_semantic_scholar_process_lock():
    try:
        from ._models import SEMANTIC_SCHOLAR_PROCESS_LOCK_DIR
    except ImportError:
        from _models import SEMANTIC_SCHOLAR_PROCESS_LOCK_DIR
    return acquire_provider_process_lock(
        SEMANTIC_SCHOLAR_PROCESS_LOCK_DIR,
        semantic_scholar_strict_interval_seconds(),
    )

def acquire_provider_process_lock(lock_dir: Path, min_interval_seconds: float):
    lock_dir.parent.mkdir(parents=True, exist_ok=True)
    stale_after = max(120.0, float(min_interval_seconds) * 80)
    while True:
        try:
            lock_dir.mkdir()
            return lambda: release_provider_process_lock(lock_dir)
        except FileExistsError:
            try:
                age = time.time() - lock_dir.stat().st_mtime
                if age > stale_after:
                    lock_dir.rmdir()
                    log_event("SCIENCE", "provider_rate_lock_stale_removed", path=str(lock_dir), age_seconds=round(age, 2))
                    continue
            except FileNotFoundError:
                continue
            except OSError:
                pass
            time.sleep(0.05)

def release_semantic_scholar_process_lock() -> None:
    try:
        from ._models import SEMANTIC_SCHOLAR_PROCESS_LOCK_DIR
    except ImportError:
        from _models import SEMANTIC_SCHOLAR_PROCESS_LOCK_DIR
    release_provider_process_lock(SEMANTIC_SCHOLAR_PROCESS_LOCK_DIR)

def release_provider_process_lock(lock_dir: Path) -> None:
    try:
        lock_dir.rmdir()
    except FileNotFoundError:
        return
    except OSError as exc:
        log_event("SCIENCE", "provider_rate_lock_release_failed", path=str(lock_dir), error=str(exc))

def ssl_context() -> ssl.SSLContext:
    if SCIENCE_INSECURE_SSL:
        return ssl._create_unverified_context()
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()

