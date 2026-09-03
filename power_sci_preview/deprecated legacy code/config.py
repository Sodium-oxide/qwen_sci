from __future__ import annotations

import os
import hashlib
from datetime import date
from pathlib import Path


def _load_dotenv() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv()


_load_dotenv()

PACKAGE_DIR = Path(__file__).resolve().parent
WORKDIR = Path(os.environ.get("AGENT_WORKDIR", Path.cwd())).resolve()
SKILLS_DIR = Path(os.environ.get("SKILLS_DIR", PACKAGE_DIR / "skills")).resolve()
LOG_PATH = Path(os.environ.get("AGENT_LOG_PATH", PACKAGE_DIR / "agent.log")).resolve()
TOOL_RESULTS_DIR = Path(
    os.environ.get("TOOL_RESULTS_DIR", PACKAGE_DIR / "tool_results")
).resolve()
TRANSCRIPTS_DIR = Path(
    os.environ.get("TRANSCRIPTS_DIR", PACKAGE_DIR / "transcripts")
).resolve()
MEMORY_DIR = Path(os.environ.get("MEMORY_DIR", PACKAGE_DIR / ".memory")).resolve()
MEMORY_INDEX = MEMORY_DIR / "MEMORY.md"
TASKS_DIR = Path(os.environ.get("TASKS_DIR", PACKAGE_DIR / ".tasks")).resolve()
TEAM_DIR = Path(os.environ.get("TEAM_DIR", PACKAGE_DIR / ".team")).resolve()
TEAM_INBOX_DIR = TEAM_DIR / "inboxes"
SCHEDULED_TASKS_PATH = Path(
    os.environ.get("SCHEDULED_TASKS_PATH", PACKAGE_DIR / ".scheduled_tasks.json")
).resolve()
SCIENCE_DIR = Path(os.environ.get("SCIENCE_DIR", PACKAGE_DIR / ".science")).resolve()
SEMANTIC_SCHOLAR_API_KEY = (
    os.environ.get("SEMANTIC_SCHOLAR_API_KEY")
    or os.environ.get("SEMANTIC_SCHOLAR_KEY")
    or os.environ.get("S2_API_KEY")
)
SCIENCE_UNPAYWALL_EMAIL = (
    os.environ.get("SCIENCE_UNPAYWALL_EMAIL")
    or os.environ.get("UNPAYWALL_EMAIL")
    or ""
).strip()
SEMANTIC_SCHOLAR_RATE_SCOPE = hashlib.sha256(
    (SEMANTIC_SCHOLAR_API_KEY or "anonymous").encode("utf-8")
).hexdigest()[:16]
_SEMANTIC_SCHOLAR_HAS_API_KEY = bool(str(SEMANTIC_SCHOLAR_API_KEY or "").strip())
SCIENCE_PROVIDER_RATE_DIR = Path(
    os.environ.get(
        "SCIENCE_PROVIDER_RATE_DIR",
        Path(os.environ.get("LOCALAPPDATA", PACKAGE_DIR / ".science"))
        / "qwen_ai_scientist"
        / "provider_rate_limits",
    )
).resolve()
# OpenAlex is the broad-coverage discovery provider.  The ceiling is applied
# even when the environment contains a larger value: a single desktop user or
# several migrated workspaces must never collectively exceed six requests per
# second with the same credential.
OPENALEX_API_KEY = (
    os.environ.get("OPENALEX_API_KEY")
    or os.environ.get("OPEN_ALEX_API_KEY")
    or ""
).strip()
SCIENCE_OPENALEX_ENABLED = os.environ.get("SCIENCE_OPENALEX_ENABLED", "1").lower() not in {
    "0",
    "false",
    "no",
}
SCIENCE_OPENALEX_API_URL = os.environ.get(
    "SCIENCE_OPENALEX_API_URL", "https://api.openalex.org/works"
).strip().rstrip("/")
SCIENCE_OPENALEX_MAILTO = os.environ.get("SCIENCE_OPENALEX_MAILTO", "").strip()
SCIENCE_OPENALEX_MAX_QPS = min(
    6.0,
    max(0.1, float(os.environ.get("SCIENCE_OPENALEX_MAX_QPS", "6"))),
)
SCIENCE_OPENALEX_MIN_INTERVAL_SECONDS = 1.0 / SCIENCE_OPENALEX_MAX_QPS
# This is a per research-run traffic budget, not a QPS increase.  A larger
# serial SH workflow may need several deficit-driven rounds while the global
# credential-scoped limiter below still enforces at most six requests/second.
SCIENCE_OPENALEX_RUN_REQUEST_LIMIT = max(
    1,
    int(os.environ.get("SCIENCE_OPENALEX_RUN_REQUEST_LIMIT", "150")),
)
SCIENCE_RETRIEVAL_ADAPTIVE_EXPANSION_ENABLED = os.environ.get(
    "SCIENCE_RETRIEVAL_ADAPTIVE_EXPANSION_ENABLED",
    "1",
).lower() not in {"0", "false", "no"}
SCIENCE_RETRIEVAL_EXHAUSTIVE_MODE = os.environ.get(
    "SCIENCE_RETRIEVAL_EXHAUSTIVE_MODE",
    "0",
).lower() in {"1", "true", "yes"}
SCIENCE_MAX_METADATA_RESULTS_PER_SH = max(
    100,
    min(
        5000,
        int(
            os.environ.get(
                "SCIENCE_MAX_METADATA_RESULTS_PER_SH",
                "2000" if SCIENCE_RETRIEVAL_EXHAUSTIVE_MODE else "600",
            )
        ),
    ),
)
SCIENCE_MAX_METADATA_RESULTS_PER_EVIDENCE_PATH = max(
    50,
    min(
        SCIENCE_MAX_METADATA_RESULTS_PER_SH,
        int(
            os.environ.get(
                "SCIENCE_MAX_METADATA_RESULTS_PER_EVIDENCE_PATH",
                "500" if SCIENCE_RETRIEVAL_EXHAUSTIVE_MODE else "150",
            )
        ),
    ),
)
SCIENCE_MAX_FULLTEXT_ATTEMPTS_PER_SH = max(
    20,
    min(
        1000,
        int(
            os.environ.get(
                "SCIENCE_MAX_FULLTEXT_ATTEMPTS_PER_SH",
                "300" if SCIENCE_RETRIEVAL_EXHAUSTIVE_MODE else "120",
            )
        ),
    ),
)
SCIENCE_DEEP_ALIGNMENT_CANDIDATE_LIMIT_MAX = max(
    60,
    min(
        SCIENCE_MAX_METADATA_RESULTS_PER_SH,
        int(
            os.environ.get(
                "SCIENCE_DEEP_ALIGNMENT_CANDIDATE_LIMIT_MAX",
                "600" if SCIENCE_RETRIEVAL_EXHAUSTIVE_MODE else "240",
            )
        ),
    ),
)
SCIENCE_PROVIDER_PAGE_SIZE_OPENALEX = max(
    5,
    min(100, int(os.environ.get("SCIENCE_PROVIDER_PAGE_SIZE_OPENALEX", "50"))),
)
SCIENCE_PROVIDER_PAGE_SIZE_PUBMED = max(
    10,
    min(200, int(os.environ.get("SCIENCE_PROVIDER_PAGE_SIZE_PUBMED", "50"))),
)
SCIENCE_PUBMED_SPECIALIZED_SEARCH_ENABLED = os.environ.get(
    "SCIENCE_PUBMED_SPECIALIZED_SEARCH_ENABLED",
    "0",
).lower() in {"1", "true", "yes"}
SCIENCE_PROVIDER_PAGE_SIZE_SEMANTIC_SCHOLAR = max(
    10,
    min(100, int(os.environ.get("SCIENCE_PROVIDER_PAGE_SIZE_SEMANTIC_SCHOLAR", "25"))),
)
SCIENCE_STOP_AFTER_NO_NEW_UNIQUE_PAGES = max(
    1,
    min(10, int(os.environ.get("SCIENCE_STOP_AFTER_NO_NEW_UNIQUE_PAGES", "2"))),
)
SCIENCE_STOP_AFTER_NO_NEW_ALIGNED_PAGES = max(
    1,
    min(10, int(os.environ.get("SCIENCE_STOP_AFTER_NO_NEW_ALIGNED_PAGES", "2"))),
)
SCIENCE_OPENALEX_MAX_PAGES_PER_BRANCH = max(
    1,
    min(
        50,
        int(
            os.environ.get(
                "SCIENCE_OPENALEX_MAX_PAGES_PER_BRANCH",
                "10" if SCIENCE_RETRIEVAL_EXHAUSTIVE_MODE else "5",
            )
        ),
    ),
)
SCIENCE_OPENALEX_PER_PAGE = max(
    1,
    min(100, int(os.environ.get("SCIENCE_OPENALEX_PER_PAGE", str(SCIENCE_PROVIDER_PAGE_SIZE_OPENALEX)))),
)
SCIENCE_OPENALEX_RETRY_LIMIT = max(
    1,
    min(
        3,
        int(
            os.environ.get(
                "SCIENCE_OPENALEX_RETRY_LIMIT",
                "2" if SCIENCE_RETRIEVAL_EXHAUSTIVE_MODE else "1",
            )
        ),
    ),
)
SCIENCE_OPENALEX_L2_TOP_LATEST_MAX_RESULTS = max(
    4,
    min(
        50,
        int(os.environ.get("SCIENCE_OPENALEX_L2_TOP_LATEST_MAX_RESULTS", "24")),
    ),
)
SCIENCE_OPENALEX_FOUNDATION_MAX_RESULTS = max(
    4,
    min(
        30,
        int(os.environ.get("SCIENCE_OPENALEX_FOUNDATION_MAX_RESULTS", "12")),
    ),
)
SCIENCE_OPENALEX_VENUE_ENRICHMENT_PER_SEARCH = max(
    0,
    min(5, int(os.environ.get("SCIENCE_OPENALEX_VENUE_ENRICHMENT_PER_SEARCH", "1"))),
)
SCIENCE_OPENALEX_CACHE_TTL_SECONDS = max(
    0.0,
    float(os.environ.get("SCIENCE_OPENALEX_CACHE_TTL_SECONDS", "604800")),
)
SCIENCE_OPENALEX_CACHE_DIR = Path(
    os.environ.get(
        "SCIENCE_OPENALEX_CACHE_DIR",
        SCIENCE_DIR / "provider_cache" / "openalex_works",
    )
).resolve()
# ScienceDirect is a credentialed metadata-discovery supplement.  It never
# asserts that a publisher landing URL is an accessible full-text source; the
# normal OA resolver and full-text gate make that decision later.  Keep it
# disabled by default: unauthorized Elsevier traffic is slow, noisy, and
# should not be reintroduced merely because an API key-like environment
# variable exists.  Set SCIENCE_SCIENCEDIRECT_ENABLED=1 only for explicit
# provider smoke tests or deliberately licensed runs.
SCIENCEDIRECT_API_KEY = (
    os.environ.get("SCIENCEDIRECT_API_KEY")
    or os.environ.get("ELSEVIER_API_KEY")
    or ""
).strip()
SCIENCE_SCIENCEDIRECT_ENABLED = os.environ.get(
    "SCIENCE_SCIENCEDIRECT_ENABLED", "0"
).lower() not in {"0", "false", "no"}
SCIENCE_SCIENCEDIRECT_API_URL = os.environ.get(
    "SCIENCE_SCIENCEDIRECT_API_URL",
    "https://api.elsevier.com/content/search/sciencedirect",
).strip().rstrip("/")
# Keep a conservative default for the paid endpoint.  The process-scoped
# limiter below applies this policy even when several projects share a key.
SCIENCE_SCIENCEDIRECT_MAX_QPS = min(
    2.0,
    max(0.1, float(os.environ.get("SCIENCE_SCIENCEDIRECT_MAX_QPS", "1"))),
)
SCIENCE_SCIENCEDIRECT_MIN_INTERVAL_SECONDS = 1.0 / SCIENCE_SCIENCEDIRECT_MAX_QPS
SCIENCE_SCIENCEDIRECT_RUN_REQUEST_LIMIT = max(
    1,
    int(os.environ.get("SCIENCE_SCIENCEDIRECT_RUN_REQUEST_LIMIT", "36")),
)
SCIENCE_SCIENCEDIRECT_CACHE_TTL_SECONDS = max(
    0.0,
    float(os.environ.get("SCIENCE_SCIENCEDIRECT_CACHE_TTL_SECONDS", "86400")),
)
SCIENCE_SCIENCEDIRECT_CACHE_DIR = Path(
    os.environ.get(
        "SCIENCE_SCIENCEDIRECT_CACHE_DIR",
        SCIENCE_DIR / "provider_cache" / "sciencedirect_search",
    )
).resolve()
SCIENCE_SCIENCEDIRECT_RETRY_LIMIT = max(
    0,
    min(3, int(os.environ.get("SCIENCE_SCIENCEDIRECT_RETRY_LIMIT", "2"))),
)
SCIENCE_SCIENCEDIRECT_TIMEOUT_SECONDS = max(
    5.0,
    min(60.0, float(os.environ.get("SCIENCE_SCIENCEDIRECT_TIMEOUT_SECONDS", "30"))),
)
# Academic MCP OA fallback is retired from the production retrieval path.
# These flags are deliberately not environment-controlled: stale shell
# variables and CORE credentials must not silently re-enable the adapter.
SCIENCE_ACADEMIC_MCP_OA_HARD_DISABLED = True
SCIENCE_ACADEMIC_MCP_OA_ENABLED = False
SCIENCE_ACADEMIC_MCP_OA_CORE_ENABLED = False
CORE_API_KEY = os.environ.get("CORE_API_KEY", "").strip()
SCIENCE_ACADEMIC_MCP_OA_CORE_API_URL = os.environ.get(
    "SCIENCE_ACADEMIC_MCP_OA_CORE_API_URL",
    "https://api.core.ac.uk/v3",
).strip().rstrip("/")
SCIENCE_ACADEMIC_MCP_OA_TIMEOUT_SECONDS = max(
    5.0,
    min(
        30.0,
        float(os.environ.get("SCIENCE_ACADEMIC_MCP_OA_TIMEOUT_SECONDS", "12")),
    ),
)
SCIENCE_ACADEMIC_MCP_OA_CACHE_TTL_SECONDS = max(
    0.0,
    float(os.environ.get("SCIENCE_ACADEMIC_MCP_OA_CACHE_TTL_SECONDS", "604800")),
)
SCIENCE_LLM_EXTRACTOR = os.environ.get("SCIENCE_LLM_EXTRACTOR", "qwen").strip().lower()
SCIENCE_LLM_PAPER_CONTEXT_UNITS = max(
    3_000,
    min(16_000, int(os.environ.get("SCIENCE_LLM_PAPER_CONTEXT_UNITS", "12000"))),
)
SCIENCE_INSECURE_SSL = os.environ.get("SCIENCE_INSECURE_SSL", "").lower() in {"1", "true", "yes"}
SCIENCE_DOMAIN_EMBEDDINGS_ENABLED = os.environ.get(
    "SCIENCE_DOMAIN_EMBEDDINGS_ENABLED", "0"
).lower() in {"1", "true", "yes"}
SCIENCE_DOMAIN_EMBEDDING_MODEL_PATH = os.environ.get(
    "SCIENCE_DOMAIN_EMBEDDING_MODEL_PATH", ""
).strip()
SCIENCE_DOMAIN_EMBEDDING_REVIEW_THRESHOLD = float(
    os.environ.get("SCIENCE_DOMAIN_EMBEDDING_REVIEW_THRESHOLD", "0.18")
)
SCIENCE_DOMAIN_EMBEDDING_REJECT_THRESHOLD = float(
    os.environ.get("SCIENCE_DOMAIN_EMBEDDING_REJECT_THRESHOLD", "0.1")
)
SCIENCE_REGULAR_PAPER_YEAR_MIN = int(os.environ.get("SCIENCE_REGULAR_PAPER_YEAR_MIN", "2010"))
SCIENCE_REGULAR_PAPER_YEAR_MAX = int(os.environ.get("SCIENCE_REGULAR_PAPER_YEAR_MAX", str(date.today().year)))
SCIENCE_L2_TOP_LATEST_YEAR_MIN = int(
    os.environ.get("SCIENCE_L2_TOP_LATEST_YEAR_MIN", "2020")
)
SCIENCE_MILESTONE_PAPER_YEAR_MIN = int(os.environ.get("SCIENCE_MILESTONE_PAPER_YEAR_MIN", "1900"))
SCIENCE_MILESTONE_PAPER_YEAR_MAX = int(os.environ.get("SCIENCE_MILESTONE_PAPER_YEAR_MAX", str(date.today().year)))
# L1 is a deliberately small historical-mechanism retrieval lane.  It is
# separate from review retrieval and from the normal recent/core corpus.  A
# small, role-compatible set of historical primary foundations may be retained
# for one SH; they remain rationale/context evidence and never substitute for
# its local causal-edge evidence.
SCIENCE_FOUNDATION_RETRIEVAL_ENABLED = os.environ.get(
    "SCIENCE_FOUNDATION_RETRIEVAL_ENABLED", "1"
).lower() not in {"0", "false", "no"}
SCIENCE_FOUNDATION_PER_SUBHYPOTHESIS_QUERY_LIMIT = max(
    0,
    int(os.environ.get("SCIENCE_FOUNDATION_PER_SUBHYPOTHESIS_QUERY_LIMIT", "1")),
)
SCIENCE_FOUNDATION_MAX_SELECTED_PER_SUBHYPOTHESIS = max(
    1,
    min(6, int(os.environ.get("SCIENCE_FOUNDATION_MAX_SELECTED_PER_SUBHYPOTHESIS", "3"))),
)
SCIENCE_FOUNDATION_PER_RUN_QUERY_LIMIT = max(
    0,
    int(os.environ.get("SCIENCE_FOUNDATION_PER_RUN_QUERY_LIMIT", "6")),
)
# The L1 lane is exactly one request per *valid unique* sub-hypothesis query,
# not a race in which the first six branches starve the rest.  The base limit
# remains an operator control, while auto expansion covers ordinary objective
# decompositions (up to the hard cap) and query/result reuse avoids spending a
# request twice.
SCIENCE_FOUNDATION_AUTO_EXPAND_RUN_BUDGET = os.environ.get(
    "SCIENCE_FOUNDATION_AUTO_EXPAND_RUN_BUDGET", "1"
).lower() not in {"0", "false", "no"}
SCIENCE_FOUNDATION_RUN_QUERY_HARD_CAP = max(
    SCIENCE_FOUNDATION_PER_RUN_QUERY_LIMIT,
    min(24, int(os.environ.get("SCIENCE_FOUNDATION_RUN_QUERY_HARD_CAP", "12"))),
)
SCIENCE_FOUNDATION_MAX_RESULTS = max(
    20,
    min(30, int(os.environ.get("SCIENCE_FOUNDATION_MAX_RESULTS", "24"))),
)
SCIENCE_FOUNDATION_PREFERRED_YEAR_MIN = int(
    os.environ.get("SCIENCE_FOUNDATION_PREFERRED_YEAR_MIN", "1900")
)
SCIENCE_FOUNDATION_PREFERRED_YEAR_MAX = int(
    os.environ.get("SCIENCE_FOUNDATION_PREFERRED_YEAR_MAX", "2010")
)
SCIENCE_FOUNDATION_ALLOW_NEWER_FALLBACK = os.environ.get(
    "SCIENCE_FOUNDATION_ALLOW_NEWER_FALLBACK", "1"
).lower() not in {"0", "false", "no"}
SCIENCE_FOUNDATION_RETRY_LIMIT = max(
    0,
    min(1, int(os.environ.get("SCIENCE_FOUNDATION_RETRY_LIMIT", "1"))),
)
SCIENCE_FOUNDATION_PAGINATION_ENABLED = False
SCIENCE_FOUNDATION_GRAPH_EXPANSION_ENABLED = False
SCIENCE_SEMANTIC_SCHOLAR_MIN_INTERVAL_SECONDS = float(
    os.environ.get("SCIENCE_SEMANTIC_SCHOLAR_MIN_INTERVAL_SECONDS", "1.5")
)
SCIENCE_SEMANTIC_SCHOLAR_429_BACKOFF_SECONDS = float(
    os.environ.get("SCIENCE_SEMANTIC_SCHOLAR_429_BACKOFF_SECONDS", "1.5")
)
_SEMANTIC_SCHOLAR_DEFAULT_RETRY_LIMIT = "2" if _SEMANTIC_SCHOLAR_HAS_API_KEY else "0"
_SEMANTIC_SCHOLAR_DEFAULT_SEARCH_RETRY_LIMIT = "4" if _SEMANTIC_SCHOLAR_HAS_API_KEY else "0"
_SEMANTIC_SCHOLAR_DEFAULT_FAIL_FAST_ON_429 = "1"
SCIENCE_SEMANTIC_SCHOLAR_RETRY_LIMIT = int(
    os.environ.get(
        "SCIENCE_SEMANTIC_SCHOLAR_RETRY_LIMIT",
        _SEMANTIC_SCHOLAR_DEFAULT_RETRY_LIMIT,
    )
)
SCIENCE_SEMANTIC_SCHOLAR_SEARCH_RETRY_LIMIT = max(
    0,
    int(
        os.environ.get(
            "SCIENCE_SEMANTIC_SCHOLAR_SEARCH_RETRY_LIMIT",
            _SEMANTIC_SCHOLAR_DEFAULT_SEARCH_RETRY_LIMIT,
        )
    ),
)
SCIENCE_SEMANTIC_SCHOLAR_GRAPH_MAX_429 = max(
    1,
    int(os.environ.get("SCIENCE_SEMANTIC_SCHOLAR_GRAPH_MAX_429", "2")),
)
SCIENCE_SEMANTIC_SCHOLAR_GRAPH_FAIL_FAST_ON_429 = os.environ.get(
    "SCIENCE_SEMANTIC_SCHOLAR_GRAPH_FAIL_FAST_ON_429", "0"
).lower() in {"1", "true", "yes"}
SCIENCE_SEMANTIC_SCHOLAR_GRAPH_WAIT_ON_429 = os.environ.get(
    "SCIENCE_SEMANTIC_SCHOLAR_GRAPH_WAIT_ON_429", "1"
).lower() in {"1", "true", "yes"}
SCIENCE_SEMANTIC_SCHOLAR_GRAPH_MAX_WAIT_SECONDS = max(
    0,
    min(180, int(os.environ.get("SCIENCE_SEMANTIC_SCHOLAR_GRAPH_MAX_WAIT_SECONDS", "60"))),
)
SCIENCE_SEMANTIC_SCHOLAR_RUN_REQUEST_LIMIT = max(
    1,
    int(os.environ.get("SCIENCE_SEMANTIC_SCHOLAR_RUN_REQUEST_LIMIT", "150")),
)
SCIENCE_SEMANTIC_SCHOLAR_GRAPH_REQUEST_LIMIT = max(
    1,
    int(os.environ.get("SCIENCE_SEMANTIC_SCHOLAR_GRAPH_REQUEST_LIMIT", "36")),
)
SCIENCE_SEMANTIC_SCHOLAR_GRAPH_REQUESTS_PER_SUBHYPOTHESIS = max(
    1,
    int(os.environ.get("SCIENCE_SEMANTIC_SCHOLAR_GRAPH_REQUESTS_PER_SUBHYPOTHESIS", "10")),
)
SCIENCE_SEMANTIC_SCHOLAR_SUCCESS_RESET_THRESHOLD = max(
    1,
    int(os.environ.get("SCIENCE_SEMANTIC_SCHOLAR_SUCCESS_RESET_THRESHOLD", "3")),
)
SCIENCE_SEMANTIC_SCHOLAR_FAIL_FAST_ON_429 = os.environ.get(
    "SCIENCE_SEMANTIC_SCHOLAR_FAIL_FAST_ON_429",
    _SEMANTIC_SCHOLAR_DEFAULT_FAIL_FAST_ON_429,
).lower() not in {"0", "false", "no"}
SCIENCE_SEMANTIC_SCHOLAR_CIRCUIT_SECONDS = float(
    os.environ.get("SCIENCE_SEMANTIC_SCHOLAR_CIRCUIT_SECONDS", "60")
)
# A 429 is a provider-wide signal, but it must not turn one optional graph
# edge into a multi-minute stall.  Keep the recovery policy explicit and
# bounded: the first response waits 60 seconds; every consecutive response
# waits at most 120 seconds.  These limits intentionally cap even a stale
# persisted rate-state written by an earlier workspace/process.
SCIENCE_SEMANTIC_SCHOLAR_429_FIRST_COOLDOWN_SECONDS = 60.0
SCIENCE_SEMANTIC_SCHOLAR_429_MAX_COOLDOWN_SECONDS = 120.0
SCIENCE_SEMANTIC_SCHOLAR_PROBE_VARIANTS = int(
    os.environ.get("SCIENCE_SEMANTIC_SCHOLAR_PROBE_VARIANTS", "2")
)
SCIENCE_SEMANTIC_SCHOLAR_CACHE_TTL_SECONDS = float(
    os.environ.get("SCIENCE_SEMANTIC_SCHOLAR_CACHE_TTL_SECONDS", "86400")
)
SCIENCE_SEMANTIC_SCHOLAR_EDGE_LIMIT = int(
    os.environ.get("SCIENCE_SEMANTIC_SCHOLAR_EDGE_LIMIT", "10")
)
SCIENCE_SEMANTIC_SCHOLAR_EDGE_CACHE_TTL_SECONDS = max(
    0.0,
    float(os.environ.get("SCIENCE_SEMANTIC_SCHOLAR_EDGE_CACHE_TTL_SECONDS", "1209600")),
)
SCIENCE_SEMANTIC_SCHOLAR_GRAPH_BATCH_ENABLED = os.environ.get(
    "SCIENCE_SEMANTIC_SCHOLAR_GRAPH_BATCH_ENABLED", "1"
).lower() not in {"0", "false", "no"}
SCIENCE_SEMANTIC_SCHOLAR_GRAPH_BATCH_MAX_IDS = max(
    1,
    min(2, int(os.environ.get("SCIENCE_SEMANTIC_SCHOLAR_GRAPH_BATCH_MAX_IDS", "2"))),
)
SCIENCE_SEMANTIC_SCHOLAR_EDGE_CACHE_DIR = Path(
    os.environ.get(
        "SCIENCE_SEMANTIC_SCHOLAR_EDGE_CACHE_DIR",
        SCIENCE_DIR / "provider_cache" / "semantic_scholar_edges",
    )
).resolve()
SCIENCE_COMMUNITY_AWARE_SEED_SELECTION = os.environ.get(
    "SCIENCE_COMMUNITY_AWARE_SEED_SELECTION", "1"
).lower() not in {"0", "false", "no"}
SCIENCE_MIN_CROSS_COMMUNITY_SEEDS = int(
    os.environ.get("SCIENCE_MIN_CROSS_COMMUNITY_SEEDS", "2")
)
SCIENCE_CROSS_COMMUNITY_EDGE_BONUS = float(
    os.environ.get("SCIENCE_CROSS_COMMUNITY_EDGE_BONUS", "0.25")
)
SCIENCE_BRIDGE_SEARCH_ENABLED = os.environ.get(
    "SCIENCE_BRIDGE_SEARCH_ENABLED", "1"
).lower() not in {"0", "false", "no"}
SCIENCE_BRIDGE_SEARCH_MAX_RESULTS = int(
    os.environ.get("SCIENCE_BRIDGE_SEARCH_MAX_RESULTS", "12")
)
SCIENCE_BRIDGE_SEARCH_QUERY_LIMIT = int(
    os.environ.get("SCIENCE_BRIDGE_SEARCH_QUERY_LIMIT", "2")
)
SCIENCE_SPARSE_GRAPH_THRESHOLD = float(
    os.environ.get("SCIENCE_SPARSE_GRAPH_THRESHOLD", "0.3")
)
SCIENCE_LOUVAIN_ENABLED = os.environ.get(
    "SCIENCE_LOUVAIN_ENABLED", "1"
).lower() not in {"0", "false", "no"}
SCIENCE_LOUVAIN_RESOLUTION = float(
    os.environ.get("SCIENCE_LOUVAIN_RESOLUTION", "1.0")
)
SCIENCE_LOUVAIN_BRIDGE_THRESHOLD = float(
    os.environ.get("SCIENCE_LOUVAIN_BRIDGE_THRESHOLD", "0.3")
)
SCIENCE_LOUVAIN_MAX_NODES = int(
    os.environ.get("SCIENCE_LOUVAIN_MAX_NODES", "500")
)
SCIENCE_LOUVAIN_INCLUDE_ARTIFICIAL_EDGES = os.environ.get(
    "SCIENCE_LOUVAIN_INCLUDE_ARTIFICIAL_EDGES", "0"
).lower() in {"1", "true", "yes"}
SCIENCE_LOUVAIN_MIN_COMMUNITY_RECORDS = int(
    os.environ.get("SCIENCE_LOUVAIN_MIN_COMMUNITY_RECORDS", "2")
)
SCIENCE_ARXIV_MIN_INTERVAL_SECONDS = float(
    os.environ.get("SCIENCE_ARXIV_MIN_INTERVAL_SECONDS", "3.5")
)
SCIENCE_ARXIV_CIRCUIT_SECONDS = float(
    os.environ.get("SCIENCE_ARXIV_CIRCUIT_SECONDS", "30")
)
SCIENCE_SUBSPACE_PROBE_MAX_CALLS_PER_PROVIDER = int(
    os.environ.get("SCIENCE_SUBSPACE_PROBE_MAX_CALLS_PER_PROVIDER", "4")
)
SCIENCE_STRATIFIED_MAX_BRANCHES_PER_LAYER = int(
    os.environ.get("SCIENCE_STRATIFIED_MAX_BRANCHES_PER_LAYER", "8" if SCIENCE_RETRIEVAL_EXHAUSTIVE_MODE else "6")
)
SCIENCE_STRATIFIED_SINGLE_PAPER_INTERVAL_SECONDS = max(
    2.0,
    float(os.environ.get("SCIENCE_STRATIFIED_SINGLE_PAPER_INTERVAL_SECONDS", "2.0")),
)
SCIENCE_PREPRINT_ZERO_RESULT_TTL_SECONDS = float(
    os.environ.get("SCIENCE_PREPRINT_ZERO_RESULT_TTL_SECONDS", "900")
)
SCIENCE_PREPRINT_ZERO_MATCH_EARLY_STOP_PAGES = max(
    1,
    int(os.environ.get("SCIENCE_PREPRINT_ZERO_MATCH_EARLY_STOP_PAGES", "1")),
)
SCIENCE_SOCRATES_PREPRINT_SCAN_LIMIT = int(
    os.environ.get("SCIENCE_SOCRATES_PREPRINT_SCAN_LIMIT", "180")
)
SCIENCE_SOCRATES_PREPRINT_PROVIDER_RESULT_TARGET = int(
    os.environ.get("SCIENCE_SOCRATES_PREPRINT_PROVIDER_RESULT_TARGET", "3")
)
SCIENCE_ZHIZHI_MAX_IMPORT_TOP_K = int(
    os.environ.get(
        "SCIENCE_ZHIZHI_MAX_IMPORT_TOP_K",
        str(SCIENCE_MAX_FULLTEXT_ATTEMPTS_PER_SH),
    )
)
# Metadata recall may be broad, but PDF/full-text acquisition is the expensive,
# failure-prone step.  These caps apply to each retrieval/import run and do
# not relax the downstream scientific readiness gate.
SCIENCE_MAX_PDF_FULLTEXT_IMPORTS_PER_RETRIEVAL = max(
    1,
    min(
        100,
        int(os.environ.get("SCIENCE_MAX_PDF_FULLTEXT_IMPORTS_PER_RETRIEVAL", "25")),
    ),
)
_SCIENCE_REVIEW_IMPORT_CAP_DEFAULT = os.environ.get(
    "SCIENCE_MAX_REVIEW_IMPORTS_PER_RETRIEVAL",
    os.environ.get("SCIENCE_MAX_REVIEW_FULLTEXT_PER_RETRIEVAL", "5"),
)
SCIENCE_MAX_REVIEW_IMPORTS_PER_RETRIEVAL = max(
    0,
    min(
        25,
        int(_SCIENCE_REVIEW_IMPORT_CAP_DEFAULT),
    ),
)
SCIENCE_MAX_REVIEW_FULLTEXT_PER_RETRIEVAL = SCIENCE_MAX_REVIEW_IMPORTS_PER_RETRIEVAL
SCIENCE_SUBHYPOTHESIS_AUXILIARY_PRE_FULLTEXT_LIMIT = max(
    0,
    min(20, int(os.environ.get("SCIENCE_SUBHYPOTHESIS_AUXILIARY_PRE_FULLTEXT_LIMIT", "16"))),
)
# Legacy safety valve for AUXILIARY_PENDING_FULLTEXT candidates.  This used to
# enforce a per-layer cap (notably L2_top_latest <= 4), which reduced import
# throughput before the newer SH-local/off-topic/policy preflight gates had a
# chance to decide.  Keep the switch for debugging/regression reproduction, but
# default to unbounded so valid pending-fulltext candidates are not silently
# dropped at selection time.
SCIENCE_SUBHYPOTHESIS_AUXILIARY_PRE_FULLTEXT_LAYER_LIMIT_ENABLED = os.environ.get(
    "SCIENCE_SUBHYPOTHESIS_AUXILIARY_PRE_FULLTEXT_LAYER_LIMIT_ENABLED",
    "0",
).lower() in {"1", "true", "yes"}
SCIENCE_RESERVE_PROMOTION_CONSECUTIVE_FULLTEXT_FAILURE_STOP = max(
    0,
    min(
        20,
        int(
            os.environ.get(
                "SCIENCE_RESERVE_PROMOTION_CONSECUTIVE_FULLTEXT_FAILURE_STOP",
                "3",
            )
        ),
    ),
)
SCIENCE_ZHIZHI_IMPORT_LLM_LIMIT = int(
    os.environ.get("SCIENCE_ZHIZHI_IMPORT_LLM_LIMIT", "2")
)
# A sub-hypothesis is ready for TanXi only after this many unique,
# non-preprint, full-text, alignment-admitted papers have been persisted.
# Preprints remain useful horizon-scanning evidence but are counted on a
# separate axis and never reduce this target.
SCIENCE_SUBHYPOTHESIS_PEER_REVIEWED_FULLTEXT_TARGET = max(
    1,
    min(
        10,
        int(
            os.environ.get(
                "SCIENCE_SUBHYPOTHESIS_PEER_REVIEWED_FULLTEXT_TARGET",
                "10",
            )
        ),
    ),
)
SCIENCE_SUBHYPOTHESIS_DIRECT_CORE_FULLTEXT_TARGET = max(
    1,
    min(
        SCIENCE_SUBHYPOTHESIS_PEER_REVIEWED_FULLTEXT_TARGET,
        int(os.environ.get("SCIENCE_SUBHYPOTHESIS_DIRECT_CORE_FULLTEXT_TARGET", "1")),
    ),
)
# Discovery is still bounded, but no longer constrained to the old 12--20
# micro-window.  Adaptive expansion lets each evidence path expose enough
# metadata for object/causal-role screening while full-text import remains
# protected by SCIENCE_MAX_FULLTEXT_ATTEMPTS_PER_SH and fail-stop policies.
SCIENCE_SUBHYPOTHESIS_RETRIEVAL_BATCH_SIZE = max(
    12,
    min(
        SCIENCE_MAX_METADATA_RESULTS_PER_EVIDENCE_PATH,
        int(os.environ.get("SCIENCE_SUBHYPOTHESIS_RETRIEVAL_BATCH_SIZE", "60")),
    ),
)
SCIENCE_SUBHYPOTHESIS_RETRIEVAL_MAX_ROUNDS = max(
    1,
    min(8, int(os.environ.get("SCIENCE_SUBHYPOTHESIS_RETRIEVAL_MAX_ROUNDS", "4"))),
)
SCIENCE_SUBHYPOTHESIS_NO_YIELD_STOP_ROUNDS = max(
    1,
    min(3, int(os.environ.get("SCIENCE_SUBHYPOTHESIS_NO_YIELD_STOP_ROUNDS", "2"))),
)
# Full-text preparation is split into network-bound acquisition and CPU-bound
# parsing.  These limits deliberately do not apply to the Semantic Scholar
# dispatcher, which retains its own process-wide serialized traffic control.
FULLTEXT_NETWORK_WORKERS = max(
    1,
    min(16, int(os.environ.get("FULLTEXT_NETWORK_WORKERS", "16"))),
)
FULLTEXT_PARSE_WORKERS = max(
    1,
    min(16, int(os.environ.get("FULLTEXT_PARSE_WORKERS", "16"))),
)
FULLTEXT_PER_HOST_LIMIT = max(
    1,
    min(8, int(os.environ.get("FULLTEXT_PER_HOST_LIMIT", "2"))),
)
FULLTEXT_PREPARE_BATCH_SIZE = max(
    1,
    min(32, int(os.environ.get("FULLTEXT_PREPARE_BATCH_SIZE", "16"))),
)
FULLTEXT_COMMIT_BATCH_SIZE = max(
    1,
    min(
        3,
        FULLTEXT_PREPARE_BATCH_SIZE,
        int(os.environ.get("FULLTEXT_COMMIT_BATCH_SIZE", "2")),
    ),
)
# V3 retrieval keeps document preparation independent from the single-writer
# evidence transaction.  These conservative defaults let network/PDF work
# overlap without multiplying provider traffic or concurrent large LLM prompts.
V3_RETRIEVAL_PREPARATION_WORKERS = max(
    1,
    min(
        FULLTEXT_NETWORK_WORKERS,
        int(os.environ.get("V3_RETRIEVAL_PREPARATION_WORKERS", "16")),
    ),
)
V3_RETRIEVAL_LLM_STRUCTURING_INFLIGHT = max(
    1,
    min(4, int(os.environ.get("V3_RETRIEVAL_LLM_STRUCTURING_INFLIGHT", "2"))),
)
SCIENCE_PROPOSITION_LLM_MAX_INFLIGHT = max(
    1,
    min(16, int(os.environ.get("SCIENCE_PROPOSITION_LLM_MAX_INFLIGHT", "16"))),
)
SCIENCE_PROPOSITION_LLM_MAX_PER_DOCUMENT = max(
    1,
    min(
        SCIENCE_PROPOSITION_LLM_MAX_INFLIGHT,
        int(os.environ.get("SCIENCE_PROPOSITION_LLM_MAX_PER_DOCUMENT", "8")),
    ),
)
SCIENCE_ALIGNMENT_LLM_MAX_PER_DOCUMENT = max(
    1,
    min(
        SCIENCE_PROPOSITION_LLM_MAX_INFLIGHT,
        int(os.environ.get("SCIENCE_ALIGNMENT_LLM_MAX_PER_DOCUMENT", "8")),
    ),
)
FULLTEXT_CACHE_ENABLED = os.environ.get(
    "FULLTEXT_CACHE_ENABLED", "1"
).lower() not in {"0", "false", "no"}
FULLTEXT_CACHE_DIR = Path(
    os.environ.get(
        "FULLTEXT_CACHE_DIR",
        SCIENCE_DIR / "provider_cache" / "fulltext",
    )
).resolve()
FULLTEXT_CONTENT_DIR = Path(
    os.environ.get("FULLTEXT_CONTENT_DIR", SCIENCE_DIR / "fulltext")
).resolve()
FULLTEXT_OA_CACHE_TTL_SECONDS = max(
    0.0,
    float(os.environ.get("FULLTEXT_OA_CACHE_TTL_SECONDS", "604800")),
)
FULLTEXT_LANDING_CACHE_TTL_SECONDS = max(
    0.0,
    float(os.environ.get("FULLTEXT_LANDING_CACHE_TTL_SECONDS", "604800")),
)
FULLTEXT_PDF_CACHE_TTL_SECONDS = max(
    0.0,
    float(os.environ.get("FULLTEXT_PDF_CACHE_TTL_SECONDS", "2592000")),
)
FULLTEXT_FAILURE_404_TTL_SECONDS = max(
    0.0,
    float(os.environ.get("FULLTEXT_FAILURE_404_TTL_SECONDS", "604800")),
)
FULLTEXT_FAILURE_AUTH_TTL_SECONDS = max(
    0.0,
    float(os.environ.get("FULLTEXT_FAILURE_AUTH_TTL_SECONDS", "604800")),
)
FULLTEXT_FAILURE_TRANSIENT_FIRST_TTL_SECONDS = max(
    0.0,
    float(
        os.environ.get(
            "FULLTEXT_FAILURE_TRANSIENT_FIRST_TTL_SECONDS",
            "60",
        )
    ),
)
FULLTEXT_FAILURE_TRANSIENT_TTL_SECONDS = max(
    0.0,
    float(os.environ.get("FULLTEXT_FAILURE_TRANSIENT_TTL_SECONDS", "120")),
)
FULLTEXT_FAILURE_NON_PDF_TTL_SECONDS = max(
    0.0,
    float(os.environ.get("FULLTEXT_FAILURE_NON_PDF_TTL_SECONDS", "604800")),
)
FULLTEXT_EXTERNALIZE_PROJECT_TEXT = os.environ.get(
    "FULLTEXT_EXTERNALIZE_PROJECT_TEXT", "1"
).lower() not in {"0", "false", "no"}
FULLTEXT_AUTO_NORMALIZE_BATCH_PROJECT = os.environ.get(
    "FULLTEXT_AUTO_NORMALIZE_BATCH_PROJECT", "1"
).lower() not in {"0", "false", "no"}
SCIENCE_QUERY_OPTIMIZER_MAX_QUERIES = max(
    1,
    min(5, int(os.environ.get("SCIENCE_QUERY_OPTIMIZER_MAX_QUERIES", "5"))),
)
# A low number of newly admitted PaperGraph records can indicate that a
# persisted sub-hypothesis causal contract is too broad or poorly
# operationalized. The serial retrieval controller uses this threshold to
# request one constrained LLM reassessment before continuing query
# optimization.
SCIENCE_SUBHYPOTHESIS_LOW_ADMISSION_REASSESSMENT_THRESHOLD = max(
    0,
    min(
        5,
        int(os.environ.get("SCIENCE_SUBHYPOTHESIS_LOW_ADMISSION_REASSESSMENT_THRESHOLD", "2")),
    ),
)
QWEN_MODEL_ID = os.environ.get("QWEN_MODEL_ID", "qwen-plus")
QWEN_API_KEY = os.environ.get("QWEN_API_KEY") or os.environ.get("DASHSCOPE_API_KEY")
QWEN_API_BASE = os.environ.get("QWEN_API_BASE") or os.environ.get("DASHSCOPE_API_BASE")

# Document conversion remains local and plugin-free by default.  OCR is an
# explicit, bounded escalation: it requires a separately installed
# ``markitdown-ocr`` package plus an OpenAI-compatible vision client.
SCIENCE_DOCUMENT_MAX_BYTES = max(
    1_000_000,
    min(250_000_000, int(os.environ.get("SCIENCE_DOCUMENT_MAX_BYTES", "60000000"))),
)
SCIENCE_DOCUMENT_MAX_PDF_PAGES = max(
    1,
    min(1_000, int(os.environ.get("SCIENCE_DOCUMENT_MAX_PDF_PAGES", "500"))),
)
SCIENCE_DOCUMENT_MAX_ARCHIVE_MEMBERS = max(
    10,
    min(20_000, int(os.environ.get("SCIENCE_DOCUMENT_MAX_ARCHIVE_MEMBERS", "2000"))),
)
SCIENCE_DOCUMENT_MAX_EXPANDED_BYTES = max(
    SCIENCE_DOCUMENT_MAX_BYTES,
    min(
        1_000_000_000,
        int(os.environ.get("SCIENCE_DOCUMENT_MAX_EXPANDED_BYTES", "180000000")),
    ),
)
SCIENCE_DOCUMENT_SOFT_RUNTIME_SECONDS = max(
    5,
    min(600, int(os.environ.get("SCIENCE_DOCUMENT_SOFT_RUNTIME_SECONDS", "90"))),
)
SCIENCE_DOCUMENT_OCR_ENABLED = os.environ.get(
    "SCIENCE_DOCUMENT_OCR_ENABLED", "0"
).lower() in {"1", "true", "yes"}
SCIENCE_DOCUMENT_OCR_MODEL = os.environ.get("SCIENCE_DOCUMENT_OCR_MODEL", "").strip()
SCIENCE_DOCUMENT_OCR_API_KEY = os.environ.get("SCIENCE_DOCUMENT_OCR_API_KEY", "").strip()
SCIENCE_DOCUMENT_OCR_API_BASE = os.environ.get("SCIENCE_DOCUMENT_OCR_API_BASE", "").strip()
SCIENCE_DOCUMENT_OCR_MAX_PAGES = max(
    1,
    min(24, int(os.environ.get("SCIENCE_DOCUMENT_OCR_MAX_PAGES", "8"))),
)
SCIENCE_DOCUMENT_OCR_MAX_IMAGES = max(
    1,
    min(48, int(os.environ.get("SCIENCE_DOCUMENT_OCR_MAX_IMAGES", "12"))),
)

# Multimodal visual evidence is deliberately separate from OCR.  OCR can
# transcribe visible text; this branch renders PDF pages/figure-table assets
# and asks a vision-capable LLM to extract structured, SH-local visual evidence
# candidates.  The first version is enabled by default but remains safe: missing
# credentials or unsupported image input defer extraction, and visual evidence
# is candidate-only unless a future human-review workflow explicitly upgrades it.
SCIENCE_MULTIMODAL_ENABLED = os.environ.get(
    "SCIENCE_MULTIMODAL_ENABLED", "1"
).lower() in {"1", "true", "yes"}
SCIENCE_MULTIMODAL_PROVIDER = os.environ.get(
    "SCIENCE_MULTIMODAL_PROVIDER", "dashscope"
).strip().lower()
SCIENCE_MULTIMODAL_MODEL = os.environ.get(
    "SCIENCE_MULTIMODAL_MODEL", "qwen3.8-max"
).strip()
SCIENCE_MULTIMODAL_FALLBACK_MODEL = os.environ.get(
    "SCIENCE_MULTIMODAL_FALLBACK_MODEL", "qwen-plus"
).strip()
SCIENCE_MULTIMODAL_API_KEY = (
    os.environ.get("SCIENCE_MULTIMODAL_API_KEY")
    or os.environ.get("DASHSCOPE_API_KEY")
    or os.environ.get("QWEN_API_KEY")
    or ""
).strip()
SCIENCE_MULTIMODAL_API_BASE = (
    os.environ.get("SCIENCE_MULTIMODAL_API_BASE")
    or os.environ.get("DASHSCOPE_API_BASE")
    or os.environ.get("QWEN_API_BASE")
    or "https://dashscope.aliyuncs.com/compatible-mode/v1"
).strip()
SCIENCE_MULTIMODAL_MAX_PAGES = max(
    1,
    min(24, int(os.environ.get("SCIENCE_MULTIMODAL_MAX_PAGES", "8"))),
)
SCIENCE_MULTIMODAL_MAX_ASSETS_PER_PAPER = max(
    1,
    min(64, int(os.environ.get("SCIENCE_MULTIMODAL_MAX_ASSETS_PER_PAPER", "12"))),
)
SCIENCE_MULTIMODAL_MAX_RENDER_DPI = max(
    100,
    min(300, int(os.environ.get("SCIENCE_MULTIMODAL_MAX_RENDER_DPI", "180"))),
)
SCIENCE_MULTIMODAL_REQUIRE_HUMAN_REVIEW = os.environ.get(
    "SCIENCE_MULTIMODAL_REQUIRE_HUMAN_REVIEW", "1"
).lower() not in {"0", "false", "no"}
SCIENCE_MULTIMODAL_COUNTS_TOWARD_GATE = os.environ.get(
    "SCIENCE_MULTIMODAL_COUNTS_TOWARD_GATE", "0"
).lower() in {"1", "true", "yes"}
SCIENCE_MULTIMODAL_TIMEOUT_SECONDS = max(
    10,
    min(180, int(os.environ.get("SCIENCE_MULTIMODAL_TIMEOUT_SECONDS", "60"))),
)
SCIENCE_MULTIMODAL_CAPABILITY_PROBE_CACHE_SECONDS = max(
    0,
    min(86400, int(os.environ.get("SCIENCE_MULTIMODAL_CAPABILITY_PROBE_CACHE_SECONDS", "3600"))),
)
SCIENCE_MULTIMODAL_DEFER_UNTIL_IMPORT_GATE_READY = os.environ.get(
    "SCIENCE_MULTIMODAL_DEFER_UNTIL_IMPORT_GATE_READY", "1"
).lower() in {"1", "true", "yes"}
SCIENCE_MULTIMODAL_RUN_INLINE_DURING_IMPORT = os.environ.get(
    "SCIENCE_MULTIMODAL_RUN_INLINE_DURING_IMPORT", "0"
).lower() in {"1", "true", "yes"}
SCIENCE_IMPORT_POLICY_ECONOMIC_FULLTEXT_ENABLED = os.environ.get(
    "SCIENCE_IMPORT_POLICY_ECONOMIC_FULLTEXT_ENABLED", "0"
).lower() in {"1", "true", "yes"}
SCIENCE_IMPORT_BACKGROUND_FULLTEXT_ENABLED = os.environ.get(
    "SCIENCE_IMPORT_BACKGROUND_FULLTEXT_ENABLED", "0"
).lower() in {"1", "true", "yes"}
SCIENCE_IMPORT_BACKGROUND_METADATA_BUDGET = max(
    0,
    min(20, int(os.environ.get("SCIENCE_IMPORT_BACKGROUND_METADATA_BUDGET", "1"))),
)
SCIENCE_IMPORT_POLICY_ECONOMIC_METADATA_BUDGET = max(
    0,
    min(20, int(os.environ.get("SCIENCE_IMPORT_POLICY_ECONOMIC_METADATA_BUDGET", "0"))),
)
SCIENCE_IMPORT_REVIEW_CONTEXT_BUDGET = max(
    0,
    min(20, int(os.environ.get("SCIENCE_IMPORT_REVIEW_CONTEXT_BUDGET", "2"))),
)
DEFAULT_LLM_PROVIDER = "qwen"
LLM_PROVIDER = os.environ.get("LLM_PROVIDER", DEFAULT_LLM_PROVIDER).strip().lower()
if LLM_PROVIDER not in {"qwen", "dashscope"}:
    LLM_PROVIDER = DEFAULT_LLM_PROVIDER
MODEL_ID = os.environ.get("MODEL_ID", QWEN_MODEL_ID)
MAX_TOKENS = int(os.environ.get("MAX_TOKENS", "8000"))
SUB_MAX_TOKENS = int(os.environ.get("SUB_MAX_TOKENS", "4000"))
SUB_MAX_TURNS = int(os.environ.get("SUB_MAX_TURNS", "30"))

BASH_TIMEOUT_SECONDS = int(os.environ.get("BASH_TIMEOUT_SECONDS", "120"))
MAX_OUTPUT_CHARS = int(os.environ.get("MAX_OUTPUT_CHARS", "200000"))
LARGE_OUTPUT_CHARS = int(os.environ.get("LARGE_OUTPUT_CHARS", "20000"))

L3_TOOL_RESULT_BUDGET = int(os.environ.get("L3_TOOL_RESULT_BUDGET", "16000"))
L3_SNIPPET_CHARS = int(os.environ.get("L3_SNIPPET_CHARS", "1500"))
L1_MAX_MESSAGES = int(os.environ.get("L1_MAX_MESSAGES", "60"))
L1_COOLDOWN_MESSAGES = int(os.environ.get("L1_COOLDOWN_MESSAGES", "8"))
L1_COMPACT_TRIGGER_MESSAGES = int(
    os.environ.get("L1_COMPACT_TRIGGER_MESSAGES", str(L1_MAX_MESSAGES + L1_COOLDOWN_MESSAGES))
)
L1_KEEP_HEAD = int(os.environ.get("L1_KEEP_HEAD", "15"))
L1_KEEP_TAIL = int(os.environ.get("L1_KEEP_TAIL", "44"))
L2_KEEP_TOOL_RESULTS = int(os.environ.get("L2_KEEP_TOOL_RESULTS", "8"))
L0_SERIALIZED_LIMIT = int(os.environ.get("L0_SERIALIZED_LIMIT", "80000"))
L0_SUMMARY_TOKENS = int(os.environ.get("L0_SUMMARY_TOKENS", "1200"))
EMERGENCY_KEEP_MESSAGES = int(os.environ.get("EMERGENCY_KEEP_MESSAGES", "5"))
MEMORY_RETRIEVAL_LIMIT = int(os.environ.get("MEMORY_RETRIEVAL_LIMIT", "5"))
MEMORY_MERGE_THRESHOLD = int(os.environ.get("MEMORY_MERGE_THRESHOLD", "10"))
MEMORY_EXTRACT_TOKENS = int(os.environ.get("MEMORY_EXTRACT_TOKENS", "1200"))
MEMORY_MERGE_TOKENS = int(os.environ.get("MEMORY_MERGE_TOKENS", "2000"))
RECOVERY_MAX_TOKENS_ESCALATED = int(os.environ.get("RECOVERY_MAX_TOKENS_ESCALATED", "64000"))
RECOVERY_CONTINUATION_LIMIT = int(os.environ.get("RECOVERY_CONTINUATION_LIMIT", "3"))
RECOVERY_RETRY_LIMIT = int(os.environ.get("RECOVERY_RETRY_LIMIT", "5"))
RECOVERY_BASE_DELAY_MS = int(os.environ.get("RECOVERY_BASE_DELAY_MS", "500"))
RECOVERY_MAX_DELAY_MS = int(os.environ.get("RECOVERY_MAX_DELAY_MS", "32000"))
FALLBACK_MODEL_ID = os.environ.get("FALLBACK_MODEL_ID", MODEL_ID)
BACKGROUND_ENABLED = os.environ.get("BACKGROUND_ENABLED", "1").lower() not in {"0", "false", "no"}
BACKGROUND_MAX_OUTPUT_CHARS = int(os.environ.get("BACKGROUND_MAX_OUTPUT_CHARS", "20000"))
CRON_ENABLED = os.environ.get("CRON_ENABLED", "1").lower() not in {"0", "false", "no"}
CRON_POLL_SECONDS = float(os.environ.get("CRON_POLL_SECONDS", "1.0"))
CRON_QUEUE_POLL_SECONDS = float(os.environ.get("CRON_QUEUE_POLL_SECONDS", "0.2"))
CRON_MAX_JOBS = int(os.environ.get("CRON_MAX_JOBS", "50"))

AUTO_APPROVE = os.environ.get("AGENT_AUTO_APPROVE", "").lower() in {"1", "true", "yes"}
DISABLE_CONTEXT_INJECTION = bool(os.environ.get("AGENT_DISABLE_CONTEXT_INJECTION"))
LOG_COLOR = os.environ.get("AGENT_LOG_COLOR", "1").lower() not in {"0", "false", "no"}
