import requests
import time
import re
import threading
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from collections.abc import Mapping
from concurrent.futures import (
    FIRST_COMPLETED,
    ThreadPoolExecutor,
    TimeoutError,
    as_completed,
    wait,
)
import os
import sys
from urllib.parse import quote, urlencode

from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)
from tqdm import tqdm
from pathlib import Path
from utils.rich_logger import get_logger
import tiktoken
import xml.etree.ElementTree as ET
from utils.utils import extract_json

_PROJECT_ROOT = Path(__file__).resolve().parents[4]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.config import load_config
from src.llm.provider_registry import (
    build_chat_completions_url,
    require_model_capabilities,
    resolve_model,
    resolve_provider,
    resolve_role_model,
)

import requests
import json
import time
import diskcache as dc

try:
    from pyalex import Works as PyAlexWorks
    from pyalex import config as pyalex_config
except ImportError:  # pragma: no cover - exercised by installation validation
    PyAlexWorks = None
    pyalex_config = None


# OpenAlex applies the service limit to the client/IP, not to one DataManager.
# Several Survey components may create their own adapter, so all adapters in
# this process must reserve from the same paced request stream.
_OPENALEX_REQUEST_RATE_LOCK = threading.Lock()
_OPENALEX_NEXT_REQUEST_NOT_BEFORE = 0.0


class _TimeoutSession(requests.Session):
    """Requests session that supplies a timeout when a library omits one."""

    def __init__(self, timeout: tuple[float, float]):
        super().__init__()
        self.request_timeout = timeout
        self.last_response = None

    def request(self, method, url, **kwargs):
        if kwargs.get("timeout") is None:
            kwargs["timeout"] = self.request_timeout
        response = super().request(method, url, **kwargs)
        self.last_response = response
        return response


class _Utf8ByteEncoding:
    def encode(self, text: str) -> list[int]:
        return list(text.encode("utf-8"))

    def decode(self, tokens: list[int]) -> str:
        return bytes(tokens).decode("utf-8", errors="ignore")


class ArxivAPI:
    def __init__(self, config):
        self.base_url = "http://export.arxiv.org/api/query"
        self.logger = get_logger("ArxivAPI")
        self.config = config

    def get_paper_details(self, paper_id: str):
        arxiv_url = f"https://export.arxiv.org/api/query?id_list={paper_id}"
        paper = {}
        
        for retry_count in range(self.config.APIInfo.arxiv_api_max_retry):
            response = requests.get(arxiv_url, timeout=120)
            if response.status_code == 200:
                break
            else:
                self.logger.warning(f"arXiv API request failed for {paper_id}: {response.status_code}. Retrying {retry_count + 1}/3...")
                if response.status_code == 429:
                    time.sleep(60)

            if response.status_code == 429:
                self.logger.info("arxiv get_paper_details Rate limit exceeded. Waiting 60 seconds before retrying...")
                time.sleep(60*(retry_count+1))

        if response.status_code == 200:
            root = ET.fromstring(response.content)
            ns = {'atom': 'http://www.w3.org/2005/Atom'}
            entry = root.find('.//atom:entry', ns)
            if entry is not None:
                paper["title"] = entry.find('atom:title', ns).text.strip() if entry.find('atom:title', ns) is not None else ""
                paper["authors"] = [author.find('atom:name', ns).text for author in entry.findall('atom:author', ns) if author.find('atom:name', ns) is not None]
                published = entry.find('atom:published', ns).text[:4] if entry.find('atom:published', ns) is not None else ""  # Extract year
                paper["venue"] = "arXiv"  # Default venue for arXiv
                paper["year"] = published
                summary_el = entry.find('atom:summary', ns)
                paper["abstract"] = summary_el.text.strip() if summary_el is not None else ""
                self.logger.info(f"Fetched details from arXiv for {paper_id}")
            else:
                self.logger.warning(f"No entry found in arXiv response for {paper_id}")
                raise ValueError("No entry found in arXiv response in mla generation")
        else:
            self.logger.warning(f"arXiv API request failed for {paper_id}: {response.status_code}")
            raise ValueError("No entry found in arXiv response in mla generation")
        
        return paper

    def search_papers_by_title(self, title: str):
        """通过标题搜索arXiv论文"""
        import urllib.parse
        # 标题搜索使用 ti: 前缀
        search_query = f"ti:{urllib.parse.quote(title)}"
        arxiv_url = f"{self.base_url}?search_query={search_query}&start=0&max_results=10"
        
        papers = []
        for retry_count in range(self.config.APIInfo.arxiv_api_max_retry):
            response = requests.get(arxiv_url, timeout=120)
            if response.status_code == 200:
                break
            else:
                self.logger.warning(f"arXiv search request failed for command{title}: {response.status_code}. Retrying {retry_count + 1}/3...")

            if response.status_code == 429:
                self.logger.info("arxiv search_papers_by_title Rate limit exceeded. Waiting 60 seconds before retrying...")
                time.sleep(60*(retry_count+1))
        
        if response.status_code == 200:
            root = ET.fromstring(response.content)
            ns = {'atom': 'http://www.w3.org/2005/Atom'}
            
            for entry in root.findall('.//atom:entry', ns):
                paper = {}
                # 提取 arXiv ID (从链接中提取)
                id_link = entry.find('atom:id', ns)
                if id_link is not None:
                    # 从 URL 中提取 arXiv ID，如 http://arxiv.org/abs/2301.00001v1
                    paper_id = id_link.text.split('/')[-1]
                    # 移除版本号
                    paper['paper_id'] = paper_id.split('v')[0] if 'v' in paper_id else paper_id
                paper["api_platform"] = "arxiv"
                paper["title"] = entry.find('atom:title', ns).text.strip() if entry.find('atom:title', ns) is not None else ""
                paper["authors"] = [author.find('atom:name', ns).text for author in entry.findall('atom:author', ns) if author.find('atom:name', ns) is not None]
                paper["year"] = entry.find('atom:published', ns).text[:4] if entry.find('atom:published', ns) is not None else ""
                paper["venue"] = "arXiv"
                summary_el = entry.find('atom:summary', ns)
                paper["abstract"] = summary_el.text.strip() if summary_el is not None else ""
                papers.append(paper)
            
            self.logger.info(f"Found {len(papers)} papers from arXiv for title: {title}")
        else:
            self.logger.warning(f"arXiv search request failed: {response.status_code}")
        
        return papers

    @staticmethod
    def _exact_category_expression(provider_filter):
        payload = dict(provider_filter) if isinstance(provider_filter, Mapping) else {}
        if not (
            payload.get("applied")
            and payload.get("coverage") == "exact"
            and payload.get("policy") == "hard_filter"
        ):
            return ""
        return str(payload.get("category_expression") or "").strip()

    @staticmethod
    def _paper_from_atom_entry(entry, namespace):
        paper_id = ""
        id_link = entry.find("atom:id", namespace)
        if id_link is not None and id_link.text:
            paper_id = id_link.text.split("/")[-1].split("v")[0]
        title_element = entry.find("atom:title", namespace)
        summary_element = entry.find("atom:summary", namespace)
        published_element = entry.find("atom:published", namespace)
        paper = {
            "paperId": paper_id,
            "paper_id": paper_id,
            "api_platform": "arxiv",
            "title": title_element.text.strip() if title_element is not None and title_element.text else "",
            "authors": [
                author.find("atom:name", namespace).text
                for author in entry.findall("atom:author", namespace)
                if author.find("atom:name", namespace) is not None
                and author.find("atom:name", namespace).text
            ],
            "year": published_element.text[:4]
            if published_element is not None and published_element.text
            else "",
            "venue": "arXiv",
            "abstract": summary_element.text.strip()
            if summary_element is not None and summary_element.text
            else "",
        }
        if paper_id:
            paper["externalIds"] = {"ArXiv": paper_id}
        return paper

    def search_papers(self, query: str, provider_filter=None, max_results=None):
        """Discover arXiv papers only when an exact category filter is supplied.

        The caller is expected to keep OpenAlex as the primary broad source.  This
        method intentionally returns no results for missing, parent-only, or
        unresolved taxonomy metadata rather than turning arXiv into a broad
        fallback provider.
        """

        category_expression = self._exact_category_expression(provider_filter)
        query_text = str(query or "").strip()
        if not category_expression or not query_text:
            return []
        try:
            result_limit = max(1, min(100, int(max_results or 10)))
        except (TypeError, ValueError):
            result_limit = 10
        search_query = f"{category_expression} AND all:{query_text}"
        arxiv_url = (
            f"{self.base_url}?"
            f"{urlencode({'search_query': search_query, 'start': 0, 'max_results': result_limit})}"
        )
        response = None
        retry_count = 0
        max_retries = max(1, int(getattr(self.config.APIInfo, "arxiv_api_max_retry", 3) or 3))
        while retry_count < max_retries:
            try:
                response = requests.get(arxiv_url, timeout=120)
            except requests.RequestException as exc:
                self.logger.warning("arXiv discovery request failed for %s: %s", query_text, exc)
                retry_count += 1
                continue
            if response.status_code == 200:
                break
            retry_count += 1
            self.logger.warning(
                "arXiv discovery request failed for %s: %s. Retrying %s/%s...",
                query_text,
                response.status_code,
                retry_count,
                max_retries,
            )
            if response.status_code == 429 and retry_count < max_retries:
                time.sleep(60 * retry_count)
        if response is None or response.status_code != 200:
            return []
        try:
            root = ET.fromstring(response.content)
        except ET.ParseError as exc:
            self.logger.warning("arXiv returned invalid Atom XML for %s: %s", query_text, exc)
            return []
        namespace = {"atom": "http://www.w3.org/2005/Atom"}
        papers = [
            self._paper_from_atom_entry(entry, namespace)
            for entry in root.findall(".//atom:entry", namespace)
        ]
        papers = [paper for paper in papers if paper.get("paperId") or paper.get("title")]
        self.logger.info(
            "Found %s papers from exact arXiv category lane for query: %s",
            len(papers),
            query_text,
        )
        return papers

class SemanticScholarAPI:
    def __init__(self, config):
        self.headers = {"x-api-key": config.APIInfo.semantic_scholar_api_key}
        self.base_url = "https://api.semanticscholar.org/graph/v1"
        self.logger = get_logger("SemanticScholarAPI")
        self.config = config

    def search_papers(self, query: str, fields: str, retry_time: int = 0):
        """Search papers with bounded retries; log every attempt."""
        max_retry = self.config.APIInfo.semantic_scholar_api_max_retry
        url = f"{self.base_url}/paper/search"
        params = {"query": query, "fields": fields}

        resp = requests.get(url, headers=self.headers, params=params, timeout=60)
        if resp.status_code == 200:
            return resp.json()

        if retry_time >= max_retry:
            self.logger.error(
                f"Error occurs in search_papers. Status code: {resp.status_code}, reached max retry {max_retry}."
            )
            return None

        self.logger.error(
            f"Error occurs in search_papers. Status code: {resp.status_code}, retrying {retry_time + 1}/{max_retry}..."
        )
        if resp.status_code == 429:
            self.logger.info("Rate limit exceeded. Waiting 60 seconds before retrying...")
            time.sleep(60)
            return self.search_papers(query, fields, retry_time + 1)
        else:
            time.sleep(min(5, 1 + retry_time))

        return self.search_papers(query, fields, retry_time+1)

    def get_paper_details(self, paper_id: str, fields: str, retry_time: int = 0):
        """Fetch paper details with bounded retries; raises on final failure."""
        max_retry = self.config.APIInfo.semantic_scholar_api_max_retry
        url = f"{self.base_url}/paper/{paper_id}?fields={fields}"
        resp = requests.get(url, headers=self.headers, timeout=60)

        if resp.status_code == 200:
            return resp.json()

        if retry_time >= max_retry:
            self.logger.error(
                f"Failed to fetch paper details for {paper_id} after {max_retry} retries. Status code: {resp.status_code}"
            )
            raise ValueError(f"Failed to fetch paper details for {paper_id} from Semantic Scholar")

        self.logger.error(
            f"Error occurs in get_paper_details. Status code: {resp.status_code}, retrying {retry_time + 1}/{max_retry}..."
        )
        if resp.status_code == 429:
            self.logger.info("Rate limit exceeded. Waiting 60 seconds before retrying...")
            time.sleep(60)
            return self.get_paper_details(paper_id, fields, retry_time + 1)
        else:
            time.sleep(min(5, 1 + retry_time))

        return self.get_paper_details(paper_id, fields, retry_time+1)


class OpenAlexAPI:
    """PyAlex-backed OpenAlex Works adapter with Survey-compatible records."""

    _WORK_ID_PATTERN = re.compile(
        r"(?:https?://(?:api\.)?openalex\.org/(?:works/)?|https?://openalex\.org/(?:works/)?)?(W\d+)$",
        re.IGNORECASE,
    )
    _DOI_PREFIX_PATTERN = re.compile(r"^https?://(?:dx\.)?doi\.org/", re.IGNORECASE)
    _ARXIV_PATTERN = re.compile(r"arxiv\.org/(?:abs|pdf)/([^/?#]+)", re.IGNORECASE)
    _ARXIV_ID_PATTERN = re.compile(r"^\d{4}\.\d{4,5}(?:v\d+)?$", re.IGNORECASE)

    def __init__(self, config):
        if PyAlexWorks is None or pyalex_config is None:
            raise RuntimeError(
                "PyAlex is required for the OpenAlex provider. Install the project dependencies first."
            )
        self.config = config
        api_info = config.APIInfo
        self.base_url = str(
            getattr(api_info, "openalex_base_url", "https://api.openalex.org")
            or "https://api.openalex.org"
        ).rstrip("/")
        self.api_key = str(
            getattr(api_info, "openalex_api_key", "")
            or os.environ.get("OPENALEX_API_KEY", "")
            or ""
        ).strip()
        self.email = str(getattr(api_info, "openalex_email", "") or "").strip()
        try:
            configured_requests_per_second = float(
                getattr(api_info, "openalex_requests_per_second", 8) or 8
            )
        except (TypeError, ValueError):
            configured_requests_per_second = 8.0
        # Keep local request starts conservative so retries and other local
        # callers retain headroom; a lower user setting remains valid.
        self.requests_per_second = max(0.1, min(8.0, configured_requests_per_second))
        self._request_interval_seconds = 1.0 / self.requests_per_second
        self.max_retry = max(0, int(getattr(api_info, "openalex_api_max_retry", 2) or 0))
        self.connect_timeout_seconds = self._positive_timeout_setting(
            getattr(api_info, "openalex_connect_timeout_seconds", 10),
            default=10.0,
        )
        self.read_timeout_seconds = self._positive_timeout_setting(
            getattr(api_info, "openalex_read_timeout_seconds", 30),
            default=30.0,
        )
        self.retry_base_delay_seconds = self._positive_timeout_setting(
            getattr(api_info, "openalex_retry_base_delay_seconds", 1),
            default=1.0,
        )
        self.retry_max_delay_seconds = self._positive_timeout_setting(
            getattr(api_info, "openalex_retry_max_delay_seconds", 60),
            default=60.0,
        )
        self.default_per_page = max(
            1,
            min(200, int(getattr(api_info, "openalex_search_per_page", 10) or 10)),
        )
        self.graph_candidate_per_page = max(
            1,
            min(
                200,
                int(getattr(api_info, "openalex_graph_candidate_per_page", 100) or 100),
            ),
        )
        self.graph_recent_quota = max(
            0, int(getattr(api_info, "openalex_graph_recent_quota", 15) or 0)
        )
        self.graph_high_impact_quota = max(
            0, int(getattr(api_info, "openalex_graph_high_impact_quota", 15) or 0)
        )
        self.logger = get_logger("OpenAlexAPI")
        self._configure_pyalex()

    def _configure_pyalex(self):
        """Configure PyAlex metadata, while retaining retries in this adapter."""
        # PyAlex 0.21 turns this setting into an Authorization: Bearer header
        # via OpenAlexAuth. Keeping the credential out of the URL prevents it
        # from appearing in request logs, cache keys, and exception text.
        pyalex_config.api_key = self.api_key or None
        pyalex_config.email = self.email or None
        pyalex_config.openalex_url = self.base_url
        pyalex_config.user_agent = "Xcientist/0.8 (literature discovery)"
        # PyAlex's internal retry uses a new requests.Session without a timeout
        # and bypasses our process-wide request pacer. Disable it and retry each
        # HTTP attempt explicitly in _call_pyalex instead.
        pyalex_config.max_retries = 0
        pyalex_config.retry_backoff_factor = 0
        pyalex_config.retry_http_codes = []

    @staticmethod
    def _positive_timeout_setting(value, *, default: float) -> float:
        try:
            return max(0.1, float(value))
        except (TypeError, ValueError):
            return default

    @property
    def _request_timeout(self) -> tuple[float, float]:
        return (self.connect_timeout_seconds, self.read_timeout_seconds)

    def _new_timeout_session(self) -> _TimeoutSession:
        return _TimeoutSession(self._request_timeout)

    def _wait_for_request_rate_slot(self) -> float:
        """Reserve one paced OpenAlex request start across concurrent callers."""

        global _OPENALEX_NEXT_REQUEST_NOT_BEFORE
        with _OPENALEX_REQUEST_RATE_LOCK:
            now = time.monotonic()
            scheduled = max(now, _OPENALEX_NEXT_REQUEST_NOT_BEFORE)
            _OPENALEX_NEXT_REQUEST_NOT_BEFORE = (
                scheduled + self._request_interval_seconds
            )
        delay = scheduled - now
        if delay > 0:
            time.sleep(delay)
        return delay

    @classmethod
    def normalize_work_id(cls, value):
        match = cls._WORK_ID_PATTERN.search(str(value or "").strip())
        return match.group(1).upper() if match else ""

    @classmethod
    def is_openalex_work_id(cls, value):
        return bool(cls.normalize_work_id(value))

    @classmethod
    def _clean_doi(cls, value):
        doi = cls._DOI_PREFIX_PATTERN.sub("", str(value or "").strip())
        return doi.strip().rstrip("/.,;")

    @classmethod
    def _identifier_to_openalex_lookup(cls, value):
        normalized_value = str(value or "").strip()
        if not normalized_value:
            return ""
        if cls.is_openalex_work_id(normalized_value):
            return cls.normalize_work_id(normalized_value)

        doi = cls._clean_doi(normalized_value)
        if doi.lower().startswith("10.") and "/" in doi:
            return f"https://doi.org/{doi}"

        arxiv_match = cls._ARXIV_PATTERN.search(normalized_value)
        if arxiv_match:
            return f"https://arxiv.org/abs/{arxiv_match.group(1).removesuffix('.pdf')}"
        if cls._ARXIV_ID_PATTERN.fullmatch(normalized_value):
            return f"https://arxiv.org/abs/{normalized_value}"
        return ""

    @staticmethod
    def _normalized_title(title):
        return re.sub(r"\W+", "", str(title or "").casefold())

    @classmethod
    def _titles_match(cls, expected_title, candidate_title):
        expected = cls._normalized_title(expected_title)
        candidate = cls._normalized_title(candidate_title)
        return bool(expected and candidate and expected == candidate)

    @staticmethod
    def _chunks(values, size):
        for index in range(0, len(values), size):
            yield values[index : index + size]

    @staticmethod
    def _status_code_from_exception(exc: Exception) -> int | None:
        response = getattr(exc, "response", None)
        try:
            return int(getattr(response, "status_code", None))
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _rate_limit_log_values(response) -> tuple[str, str, str, str]:
        """Return non-sensitive OpenAlex rate-limit response metadata."""

        headers = getattr(response, "headers", {}) or {}
        return (
            str(headers.get("X-RateLimit-Limit") or "unknown"),
            str(headers.get("X-RateLimit-Remaining") or "unknown"),
            str(headers.get("X-RateLimit-Credits-Used") or "unknown"),
            str(headers.get("X-RateLimit-Reset") or "unknown"),
        )

    def _is_retryable_openalex_exception(self, exc: Exception) -> bool:
        if isinstance(exc, (requests.Timeout, requests.ConnectionError)):
            return True
        if isinstance(exc, requests.HTTPError):
            return self._status_code_from_exception(exc) in {429, 500, 502, 503, 504}
        return False

    def _retry_delay_seconds(self, exc: Exception, *, retry_index: int) -> float:
        response = getattr(exc, "response", None)
        retry_after = ""
        if response is not None:
            headers = getattr(response, "headers", {}) or {}
            retry_after = str(headers.get("Retry-After") or "").strip()
        if retry_after:
            try:
                return min(self.retry_max_delay_seconds, max(0.0, float(retry_after)))
            except ValueError:
                try:
                    retry_at = parsedate_to_datetime(retry_after)
                    if retry_at.tzinfo is None:
                        retry_at = retry_at.replace(tzinfo=timezone.utc)
                    return min(
                        self.retry_max_delay_seconds,
                        max(0.0, (retry_at - datetime.now(timezone.utc)).total_seconds()),
                    )
                except (TypeError, ValueError, IndexError, OverflowError):
                    pass
        return min(
            self.retry_max_delay_seconds,
            self.retry_base_delay_seconds * (2 ** max(0, retry_index - 1)),
        )

    @staticmethod
    def _pyalex_get(works, session: requests.Session, *, per_page: int):
        """Use PyAlex parsing with the adapter-owned timeout session.

        The public PyAlex ``get`` method constructs an unbounded session itself.
        Version 0.21 exposes the same parsing path through ``_get_from_url``;
        retain a public-method fallback for lightweight test doubles.
        """

        private_get = getattr(works, "_get_from_url", None)
        add_params = getattr(works, "_add_params", None)
        url = getattr(works, "url", None)
        if callable(private_get) and callable(add_params) and isinstance(url, str):
            add_params("per-page", per_page)
            return private_get(url, session=session)
        if type(works).__module__.startswith("pyalex"):
            raise RuntimeError(
                "Installed PyAlex does not expose a session-injection path; "
                "refusing an unbounded HTTP request."
            )
        return works.get(per_page=per_page)

    def _call_pyalex(self, label, operation):
        if not self.api_key:
            self.logger.warning(
                "OpenAlex request skipped label=%s reason=missing_api_key. "
                "Configure APIInfo.openalex_api_key or OPENALEX_API_KEY.",
                label,
            )
            return None

        total_attempts = self.max_retry + 1
        for attempt in range(1, total_attempts + 1):
            rate_wait_seconds = self._wait_for_request_rate_slot()
            started_at = time.monotonic()
            self.logger.info(
                "OpenAlex request started label=%s attempt=%s/%s rate_wait_seconds=%.3f "
                "timeout_seconds=(%.1f, %.1f).",
                label,
                attempt,
                total_attempts,
                rate_wait_seconds,
                self.connect_timeout_seconds,
                self.read_timeout_seconds,
            )
            try:
                with self._new_timeout_session() as session:
                    result = operation(session)
                    rate_limit_values = self._rate_limit_log_values(session.last_response)
                self.logger.info(
                    "OpenAlex request completed label=%s attempt=%s/%s status=success "
                    "elapsed_seconds=%.2f rate_limit_limit=%s rate_limit_remaining=%s "
                    "rate_limit_credits_used=%s rate_limit_reset=%s.",
                    label,
                    attempt,
                    total_attempts,
                    time.monotonic() - started_at,
                    *rate_limit_values,
                )
                return result
            except Exception as exc:
                elapsed_seconds = time.monotonic() - started_at
                status_code = self._status_code_from_exception(exc)
                retryable = self._is_retryable_openalex_exception(exc)
                rate_limit_values = self._rate_limit_log_values(
                    getattr(exc, "response", None)
                )
                if not retryable or attempt >= total_attempts:
                    self.logger.warning(
                        "OpenAlex request failed label=%s attempt=%s/%s status=%s "
                        "retryable=%s elapsed_seconds=%.2f rate_limit_limit=%s "
                        "rate_limit_remaining=%s rate_limit_credits_used=%s "
                        "rate_limit_reset=%s error=%s.",
                        label,
                        attempt,
                        total_attempts,
                        status_code if status_code is not None else "none",
                        retryable,
                        elapsed_seconds,
                        *rate_limit_values,
                        exc,
                    )
                    return None
                retry_delay_seconds = self._retry_delay_seconds(
                    exc,
                    retry_index=attempt,
                )
                self.logger.warning(
                    "OpenAlex request retrying label=%s attempt=%s/%s status=%s "
                    "rate_wait_seconds=%.3f retry_delay_seconds=%.2f "
                    "elapsed_seconds=%.2f rate_limit_limit=%s rate_limit_remaining=%s "
                    "rate_limit_credits_used=%s rate_limit_reset=%s error=%s.",
                    label,
                    attempt,
                    total_attempts,
                    status_code if status_code is not None else "none",
                    rate_wait_seconds,
                    retry_delay_seconds,
                    elapsed_seconds,
                    *rate_limit_values,
                    exc,
                )
                if retry_delay_seconds > 0:
                    time.sleep(retry_delay_seconds)
        return None

    def _fetch_raw_work(self, identifier):
        if not str(identifier or "").strip():
            return None

        def fetch_work(session):
            works = PyAlexWorks()
            private_get = getattr(works, "_get_from_url", None)
            url = getattr(works, "url", None)
            if callable(private_get) and isinstance(url, str):
                works.params = str(identifier).strip()
                return private_get(works.url, session=session)
            if type(works).__module__.startswith("pyalex"):
                raise RuntimeError(
                    "Installed PyAlex does not expose a session-injection path; "
                    "refusing an unbounded HTTP request."
                )
            return works[str(identifier).strip()]

        return self._call_pyalex(
            f"work {identifier}",
            fetch_work,
        )

    def _fetch_raw_works(self, work_ids):
        normalized_ids = []
        seen_ids = set()
        for work_id in work_ids or []:
            normalized_id = self.normalize_work_id(work_id)
            if normalized_id and normalized_id not in seen_ids:
                normalized_ids.append(normalized_id)
                seen_ids.add(normalized_id)

        raw_works = []
        for work_id_chunk in self._chunks(normalized_ids, 100):
            def fetch_batch(session, chunk=work_id_chunk):
                works = PyAlexWorks()
                filter_or = getattr(works, "filter_or", None)
                if callable(filter_or):
                    return self._pyalex_get(
                        filter_or(openalex_id=chunk),
                        session,
                        per_page=len(chunk),
                    )
                if type(works).__module__.startswith("pyalex"):
                    raise RuntimeError(
                        "Installed PyAlex does not expose batch filtering; "
                        "refusing an unbounded HTTP request."
                    )
                # Compatibility path for lightweight test doubles that only
                # implement PyAlex's public batch-indexing behavior.
                return works[chunk]

            result = self._call_pyalex(
                f"work batch of {len(work_id_chunk)}",
                fetch_batch,
            )
            if result:
                raw_works.extend(result)
        return raw_works

    @staticmethod
    def _exact_field_filter_kwargs(provider_filter):
        payload = dict(provider_filter) if isinstance(provider_filter, Mapping) else {}
        if not (
            payload.get("applied")
            and payload.get("coverage") == "exact"
            and payload.get("policy") == "hard_filter"
        ):
            return {}
        field_ids = [str(value).strip() for value in payload.get("resolved_field_ids", []) if str(value).strip()]
        if not field_ids:
            return {}
        return {"primary_topic": {"field": {"id": "|".join(field_ids)}}}

    def _search_raw_works(
        self,
        query,
        per_page,
        provider_filter=None,
        sort=None,
        *,
        return_success: bool = False,
    ):
        filter_kwargs = self._exact_field_filter_kwargs(provider_filter)

        def search_works(session):
            works = PyAlexWorks()
            if filter_kwargs:
                works = works.filter(**filter_kwargs)
            if isinstance(sort, Mapping) and sort:
                works = works.sort(**dict(sort))
            return self._pyalex_get(
                works.search(str(query or "").strip()),
                session,
                per_page=per_page,
            )

        result = self._call_pyalex(
            f"search {query!r}" + (" with exact field filter" if filter_kwargs else ""),
            search_works,
        )
        if return_success:
            # _call_pyalex returns ``None`` only after a request failure or a
            # disabled/missing-key request. An empty list is a valid completed
            # search and is safe for a short-lived negative retrieval cache.
            return (result or []), result is not None
        return result or []

    @staticmethod
    def _abstract_from_inverted_index(inverted_index):
        if not isinstance(inverted_index, dict):
            return ""
        positioned_words = []
        for word, positions in inverted_index.items():
            if not isinstance(positions, list):
                continue
            for position in positions:
                if isinstance(position, int) and position >= 0:
                    positioned_words.append((position, str(word)))
        return " ".join(word for _, word in sorted(positioned_words))

    @classmethod
    def _arxiv_id_from_work(cls, work):
        if not isinstance(work, dict):
            return ""
        identifiers = work.get("ids") if isinstance(work.get("ids"), dict) else {}
        candidates = [identifiers.get("arxiv")]
        for location in work.get("locations") or []:
            if isinstance(location, dict):
                candidates.extend(
                    [location.get("landing_page_url"), location.get("pdf_url")]
                )
        for candidate in candidates:
            match = cls._ARXIV_PATTERN.search(str(candidate or ""))
            if match:
                return match.group(1).removesuffix(".pdf").split("v")[0]
        return ""

    @staticmethod
    def _open_access_pdf_url(work):
        if not isinstance(work, dict):
            return ""
        locations = [work.get("best_oa_location"), work.get("primary_location")]
        locations.extend(work.get("locations") or [])
        for location in locations:
            if isinstance(location, dict) and str(location.get("pdf_url") or "").strip():
                return str(location["pdf_url"]).strip()
        return ""

    @staticmethod
    def _open_access_landing_url(work):
        """Return an explicitly OA landing page, if OpenAlex declared one.

        This is metadata only.  The full-text resolver later applies its own
        bounded HTML/PDF validation; no OpenAlex Content API is involved.
        """
        if not isinstance(work, dict):
            return ""
        best_oa_location = work.get("best_oa_location")
        locations = [best_oa_location]
        locations.extend(work.get("locations") or [])
        for location in locations:
            if not isinstance(location, dict):
                continue
            is_explicit_oa_location = location is best_oa_location or bool(
                location.get("is_oa")
            )
            landing_url = str(location.get("landing_page_url") or "").strip()
            if is_explicit_oa_location and landing_url:
                return landing_url
        return ""

    @staticmethod
    def _open_access_locations(work):
        """Preserve every explicitly OA OpenAlex location for the resolver.

        OpenAlex exposes more than one valid full-text route.  Retaining the
        structured locations lets the resolver try a repository manuscript
        after a stale publisher URL without scraping arbitrary page metadata.
        """

        if not isinstance(work, dict):
            return []
        best_location = work.get("best_oa_location")
        primary_location = work.get("primary_location")
        raw_locations = [
            ("openalex.best_oa_location", best_location, True),
            ("openalex.primary_location", primary_location, False),
        ]
        raw_locations.extend(
            ("openalex.oa_locations", location, False)
            for location in (work.get("locations") or [])
        )
        candidates = []
        seen = set()
        for source, location, is_best in raw_locations:
            if not isinstance(location, dict):
                continue
            if not is_best and not bool(location.get("is_oa")):
                continue
            pdf_url = str(location.get("pdf_url") or "").strip()
            landing_url = str(location.get("landing_page_url") or "").strip()
            if not pdf_url and not landing_url:
                continue
            identity = (pdf_url, landing_url)
            if identity in seen:
                continue
            seen.add(identity)
            source_info = location.get("source") if isinstance(location.get("source"), dict) else {}
            candidates.append(
                {
                    "source": source,
                    "priority": 30 if is_best else 40,
                    "pdf_url": pdf_url,
                    "landing_page_url": landing_url,
                    "version": str(location.get("version") or ""),
                    "license": str(location.get("license") or ""),
                    "host_type": str(location.get("host_type") or source_info.get("type") or ""),
                    "evidence": "openalex.best_oa_location" if is_best else "openalex.location.is_oa",
                }
            )
        return candidates

    @classmethod
    def normalize_work(cls, work):
        if not isinstance(work, dict):
            return {}
        work_id = cls.normalize_work_id(work.get("id"))
        if not work_id:
            return {}

        identifiers = work.get("ids") if isinstance(work.get("ids"), dict) else {}
        doi = cls._clean_doi(work.get("doi") or identifiers.get("doi"))
        arxiv_id = cls._arxiv_id_from_work(work)
        external_ids = {}
        if doi:
            external_ids["DOI"] = doi
        if arxiv_id:
            external_ids["ArXiv"] = arxiv_id

        authors = []
        for authorship in work.get("authorships") or []:
            author = authorship.get("author") if isinstance(authorship, dict) else None
            name = author.get("display_name") if isinstance(author, dict) else ""
            if str(name or "").strip():
                authors.append({"name": str(name).strip()})

        primary_location = work.get("primary_location")
        source = primary_location.get("source") if isinstance(primary_location, dict) else None
        venue = source.get("display_name") if isinstance(source, dict) else ""
        pdf_url = cls._open_access_pdf_url(work)
        oa_landing_url = cls._open_access_landing_url(work)
        oa_locations = cls._open_access_locations(work)
        raw_open_access = work.get("open_access")
        open_access = raw_open_access if isinstance(raw_open_access, dict) else {}
        declared_oa = bool(open_access.get("is_oa")) or bool(work.get("best_oa_location"))
        paper = {
            "paperId": work_id,
            "openalex_id": f"https://api.openalex.org/{work_id}",
            "api_platform": "openalex",
            "title": str(work.get("title") or "").strip(),
            "abstract": str(work.get("abstract") or "").strip()
            or cls._abstract_from_inverted_index(work.get("abstract_inverted_index")),
            "authors": authors,
            "year": work.get("publication_year") or "",
            "venue": str(venue or "").strip(),
            "externalIds": external_ids,
            "doi": doi,
            "citedByCount": work.get("cited_by_count") or 0,
        }
        if declared_oa:
            paper["open_access"] = {
                "is_oa": True,
                "oa_status": str(open_access.get("oa_status") or ""),
            }
        if pdf_url:
            paper["openAccessPdf"] = {"url": pdf_url}
        if oa_landing_url:
            paper["full_text_url"] = oa_landing_url
        if oa_locations:
            paper["openalex_oa_locations"] = oa_locations
        return paper

    def search_papers(self, query, per_page=None, provider_filter=None, sort=None):
        requested_page_size = self.default_per_page if per_page is None else per_page
        try:
            requested_page_size = max(1, min(200, int(requested_page_size)))
        except (TypeError, ValueError):
            requested_page_size = self.default_per_page
        works = self._search_raw_works(
            query,
            requested_page_size,
            provider_filter=provider_filter,
            sort=sort,
        )
        return [
            paper
            for paper in (self.normalize_work(work) for work in works)
            if paper
        ]

    def search_papers_with_status(
        self,
        query,
        per_page=None,
        provider_filter=None,
        sort=None,
    ):
        """Return normalized works plus whether the provider completed the request.

        Callers that cache discovery results need to distinguish a valid empty
        result from an exhausted retry budget, timeout, or missing API key.
        The existing ``search_papers`` list-only interface remains unchanged.
        """

        requested_page_size = self.default_per_page if per_page is None else per_page
        try:
            requested_page_size = max(1, min(200, int(requested_page_size)))
        except (TypeError, ValueError):
            requested_page_size = self.default_per_page
        works, successful = self._search_raw_works(
            query,
            requested_page_size,
            provider_filter=provider_filter,
            sort=sort,
            return_success=True,
        )
        return (
            [
                paper
                for paper in (self.normalize_work(work) for work in works)
                if paper
            ],
            successful,
        )

    def get_paper_details(self, work_id):
        normalized_id = self.resolve_work_id(work_id)
        if not normalized_id:
            return None
        paper = self.normalize_work(self._fetch_raw_work(normalized_id))
        return paper or None

    def resolve_work_id(self, reference):
        """Resolve a known identifier or exact title match to a canonical Work ID."""
        if isinstance(reference, dict):
            direct_values = [
                reference.get("openalex_id"),
                reference.get("paperId"),
                reference.get("paper_id"),
                reference.get("id"),
            ]
            external_ids = reference.get("externalIds")
            if isinstance(external_ids, dict):
                direct_values.extend(
                    [
                        external_ids.get("DOI"),
                        external_ids.get("doi"),
                        external_ids.get("ArXiv"),
                        external_ids.get("arXiv"),
                    ]
                )
            direct_values.append(reference.get("doi"))
            title = reference.get("title")
            expected_year = reference.get("year")
        else:
            direct_values = [reference]
            title = ""
            expected_year = None

        for value in direct_values:
            normalized_id = self.normalize_work_id(value)
            if normalized_id:
                return normalized_id
            lookup_value = self._identifier_to_openalex_lookup(value)
            if not lookup_value:
                continue
            raw_work = self._fetch_raw_work(lookup_value)
            resolved_id = self.normalize_work_id(
                raw_work.get("id") if isinstance(raw_work, dict) else ""
            )
            if resolved_id:
                return resolved_id

        if not str(title or "").strip():
            return ""
        for candidate in self._search_raw_works(title, per_page=5):
            if not isinstance(candidate, dict) or not self._titles_match(
                title, candidate.get("title")
            ):
                continue
            candidate_year = candidate.get("publication_year")
            if expected_year and candidate_year and str(expected_year) != str(candidate_year):
                continue
            resolved_id = self.normalize_work_id(candidate.get("id"))
            if resolved_id:
                return resolved_id
        return ""

    def _select_balanced_works(self, works, limit):
        unique_works = {}
        for work in works or []:
            work_id = self.normalize_work_id(work.get("id") if isinstance(work, dict) else "")
            if work_id and work_id not in unique_works:
                unique_works[work_id] = work

        recent_works = sorted(
            unique_works.values(),
            key=lambda work: str(work.get("publication_date") or ""),
            reverse=True,
        )
        impact_works = sorted(
            unique_works.values(),
            key=lambda work: int(work.get("cited_by_count") or 0),
            reverse=True,
        )
        selected = []
        selected_ids = set()

        def add_from(source, quota):
            if quota <= 0:
                return
            added = 0
            for work in source:
                work_id = self.normalize_work_id(work.get("id"))
                if work_id and work_id not in selected_ids:
                    selected.append(work)
                    selected_ids.add(work_id)
                    added += 1
                if added >= quota or len(selected) >= limit:
                    return

        add_from(recent_works, min(self.graph_recent_quota, limit))
        add_from(impact_works, min(self.graph_high_impact_quota, limit - len(selected)))
        add_from(recent_works, limit - len(selected))
        return selected[:limit]

    def _get_citing_works(self, work_id):
        def citing_works(session, *, sort_field: str):
            works = PyAlexWorks().filter(cites=work_id).sort(**{sort_field: "desc"})
            return self._pyalex_get(
                works,
                session,
                per_page=self.graph_candidate_per_page,
            )

        recent_works = self._call_pyalex(
            f"recent citations for {work_id}",
            lambda session: citing_works(session, sort_field="publication_date"),
        ) or []
        if not self.graph_high_impact_quota:
            return recent_works
        impact_works = self._call_pyalex(
            f"high-impact citations for {work_id}",
            lambda session: citing_works(session, sort_field="cited_by_count"),
        ) or []
        return list(recent_works) + list(impact_works)

    def get_related_papers(self, work_id, direction, limit):
        normalized_id = self.normalize_work_id(work_id)
        if not normalized_id:
            return []
        try:
            limit = max(1, min(200, int(limit)))
        except (TypeError, ValueError):
            limit = 20
        if direction == "in":
            raw_works = self._get_citing_works(normalized_id)
        elif direction == "out":
            work = self._fetch_raw_work(normalized_id)
            reference_ids = work.get("referenced_works") if isinstance(work, dict) else []
            candidate_limit = max(limit, self.graph_candidate_per_page)
            raw_works = self._fetch_raw_works(reference_ids[:candidate_limit])
        else:
            raise ValueError(f"Unsupported citation direction: {direction}")

        return [
            paper
            for paper in (
                self.normalize_work(work)
                for work in self._select_balanced_works(raw_works, limit)
            )
            if paper
        ]


class UnpaywallAPI:
    """Resolve a DOI to provenance-rich open-access candidates through Unpaywall."""

    _DOI_PREFIX_PATTERN = re.compile(r"^https?://(?:dx\.)?doi\.org/", re.IGNORECASE)

    def __init__(self, config):
        api_info = config.APIInfo
        self.base_url = str(
            getattr(api_info, "unpaywall_base_url", "https://api.unpaywall.org/v2")
            or "https://api.unpaywall.org/v2"
        ).rstrip("/")
        self.email = str(getattr(api_info, "unpaywall_email", "") or "").strip()
        self.timeout = max(1, int(getattr(api_info, "unpaywall_timeout", 30) or 30))
        self.logger = get_logger("UnpaywallAPI")
        self._missing_email_logged = False
        work_collector = getattr(
            getattr(config, "ModuleInfo", None), "WorkCollector", None
        )
        self._resolution_cache_ttl_seconds = max(
            1,
            int(
                getattr(
                    work_collector,
                    "fulltext_oa_resolution_cache_ttl_seconds",
                    604800,
                )
                or 604800
            ),
        )
        cache_path = str(
            getattr(getattr(config, "BasicInfo", None), "cache_path", "") or ""
        ).strip()
        self._resolution_cache = (
            dc.Cache(os.path.join(cache_path, "fulltext_unpaywall_resolution_cache"))
            if cache_path
            else None
        )

    @property
    def enabled(self):
        return bool(self.email)

    @classmethod
    def normalize_doi(cls, value):
        doi = cls._DOI_PREFIX_PATTERN.sub("", str(value or "").strip())
        return doi.strip().rstrip("/.,;")

    @staticmethod
    def _pdf_url_from_location(location):
        if not isinstance(location, dict):
            return ""
        for key in ("url_for_pdf", "pdf_url"):
            url = str(location.get(key) or "").strip()
            if url:
                return url
        return ""

    @staticmethod
    def _location_candidates(location, *, source, priority):
        """Normalize both direct-PDF and landing-page routes for one OA location."""
        if not isinstance(location, dict):
            return []
        common = {
            "source": source,
            "priority": int(priority),
            "host_type": str(location.get("host_type") or ""),
            "version": str(location.get("version") or ""),
            "license": str(location.get("license") or ""),
            "evidence": str(location.get("evidence") or ""),
        }
        candidates = []
        pdf_url = UnpaywallAPI._pdf_url_from_location(location)
        landing_url = str(
            location.get("url_for_landing_page") or location.get("url") or ""
        ).strip()
        if pdf_url:
            candidates.append({**common, "url": pdf_url, "kind": "pdf"})
        if landing_url and landing_url != pdf_url:
            candidates.append(
                {
                    **common,
                    "url": landing_url,
                    "kind": "landing_page",
                    "priority": int(priority) + 1,
                }
            )
        return candidates

    def get_oa_candidates(self, doi):
        """Return every declared Unpaywall OA route, in stable source order.

        The contact email remains an HTTP request parameter only; it is not
        returned in a candidate and therefore never enters paper provenance.
        """
        normalized_doi = self.normalize_doi(doi)
        if not normalized_doi:
            return []
        cache_key = f"unpaywall_oa_candidates_v1:{normalized_doi.casefold()}"
        if self._resolution_cache is not None:
            cached = self._resolution_cache.get(cache_key)
            if isinstance(cached, list):
                return [dict(candidate) for candidate in cached if isinstance(candidate, dict)]
        if not self.enabled:
            if not self._missing_email_logged:
                self.logger.warning(
                    "Unpaywall is disabled: set UNPAYWALL_EMAIL to enable DOI-to-PDF resolution."
                )
                self._missing_email_logged = True
            return []
        try:
            response = requests.get(
                f"{self.base_url}/{quote(normalized_doi, safe='')}",
                params={"email": self.email},
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            self.logger.warning("Unpaywall request failed for DOI %s: %s", normalized_doi, exc)
            return []
        if response.status_code != 200:
            self.logger.info("Unpaywall did not resolve DOI %s: HTTP %s", normalized_doi, response.status_code)
            return []
        try:
            payload = response.json()
        except ValueError:
            self.logger.warning("Unpaywall returned invalid JSON for DOI %s", normalized_doi)
            return []

        candidates = []
        candidates.extend(
            self._location_candidates(
                payload.get("best_oa_location"),
                source="unpaywall.best_oa_location",
                priority=0,
            )
        )
        for location in payload.get("oa_locations") or []:
            candidates.extend(
                self._location_candidates(
                    location,
                    source="unpaywall.oa_locations",
                    priority=10,
                )
            )
        if self._resolution_cache is not None:
            self._resolution_cache.set(
                cache_key,
                [dict(candidate) for candidate in candidates],
                expire=self._resolution_cache_ttl_seconds,
            )
        return candidates

    def get_oa_pdf_url(self, doi):
        for candidate in self.get_oa_candidates(doi):
            if candidate.get("kind") == "pdf":
                return str(candidate.get("url") or "")
        return ""


class TransientHTTPError(requests.RequestException):
    """Raised for retryable HTTP status codes."""
    pass


class NonRetryableRequestError(RuntimeError):
    """A deterministic provider request failure that must not be retried."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        response_body: str = "",
    ) -> None:
        self.status_code = status_code
        # Keep the unmodified provider body available to callers and logs.  It
        # is especially useful for compatible endpoints that report a request
        # contract violation only in their JSON error payload.
        self.response_body = response_body
        super().__init__(message)


class PromptBudgetExceeded(ValueError):
    """A strict full-text request exceeded its prevalidated input budget."""
    pass

class ChatAgent:
    Record_splitter = "||"
    Record_show_length = 200

    def __init__(
        self,
        config,
        use_different_api_for_judge=False,
        *,
        provider_override: str = "",
        model_override: str = "",
    ) -> None:
        self.config = config
        self._project_config = load_config()
        api_info = config.APIInfo
        provider_override = str(provider_override or "").strip()
        model_override = str(model_override or "").strip()
        if use_different_api_for_judge and (provider_override or model_override):
            raise ValueError(
                "provider_override/model_override cannot be combined with the Judge API override."
            )
        provider_name = provider_override or str(
            getattr(api_info, "llm_provider", "") or ""
        ).strip()
        provider = resolve_provider(self._project_config, provider_name or None)
        self.provider_name = provider.name
        self.tokenizer_fallback = provider.tokenizer_fallback
        self.token_limit_parameter = provider.token_limit_parameter
        self.remote_url = build_chat_completions_url(
            str(
                provider.base_url
                if provider_override
                else getattr(api_info, "llm_api_base_url", "") or provider.base_url
            )
        )
        self.token = str(
            provider.api_key
            if provider_override
            else getattr(api_info, "llm_api_key", "") or provider.api_key
        )
        self.header = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.token}",
        }
        self.batch_workers = config.APIInfo.batch_chat_agent_worker
        model_spec = (
            resolve_model(self._project_config, model_override, provider.name)
            if model_override
            else resolve_role_model(
                self._project_config,
                "survey",
                provider.name,
                str(config.APIInfo.llm_model_name or "").strip(),
            )
        )
        required_capabilities = ["chat_completions"]
        if bool(config.APIInfo.use_stream_mode):
            required_capabilities.append("streaming")
        require_model_capabilities(model_spec, required_capabilities, "Survey ChatAgent")
        self.model_name = model_spec.name
        if not (provider_override or model_override):
            config.APIInfo.llm_model_name = self.model_name
        self.logger = get_logger("ChatAgent")
        
        # Exponential backoff settings
        self.exponential_backoff = getattr(config.APIInfo, 'exponential_backoff', False)
        self.exponential_backoff_time = getattr(config.APIInfo, 'exponential_backoff_time', 1)
        self.exponential_backoff_max_time = getattr(config.APIInfo, 'exponential_backoff_max_time', 60)
        
        # self.logger.info("Initializing...")
        # self.logger.info(f"{self.remote_url}")
        # self.logger.info(f"{self.token}")
        # self.logger.info(f"{self.model_name}")

        if use_different_api_for_judge:
            self.logger.info("Using different LLM API key and URL for Judge module.")
            judge_config = config.ModuleInfo.Judge
            judge_provider_name = str(getattr(judge_config, "provider", "") or provider.name).strip()
            judge_provider = resolve_provider(self._project_config, judge_provider_name)
            self.provider_name = judge_provider.name
            self.tokenizer_fallback = judge_provider.tokenizer_fallback
            self.token_limit_parameter = judge_provider.token_limit_parameter
            self.remote_url = build_chat_completions_url(
                str(getattr(judge_config, "judge_llm_api_base_url", "") or judge_provider.base_url)
            )
            self.token = str(getattr(judge_config, "judge_llm_api_key", "") or judge_provider.api_key)
            model_spec = resolve_role_model(
                self._project_config,
                "judge",
                judge_provider.name,
                str(config.ModuleInfo.Judge.model or "").strip(),
            )
            require_model_capabilities(
                model_spec,
                required_capabilities,
                "Survey Judge ChatAgent",
            )
            self.model_name = model_spec.name
            judge_config.model = self.model_name
            self.header = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.token}",
            }

        if not self.token:
            provider = resolve_provider(self._project_config, self.provider_name)
            raise ValueError(
                f"Survey ChatAgent requires {provider.api_key_env} for provider '{provider.name}'."
            )
        resolve_model(self._project_config, self.model_name, self.provider_name)

    @staticmethod
    def _mask_token(token: str) -> str:
        token = str(token or "").strip()
        if not token:
            return "<empty>"
        if len(token) <= 8:
            return "*" * len(token)
        return f"{token[:4]}...{token[-4:]}"

    def supports_response_format(
        self,
        response_format: str,
        *,
        model: str | None = None,
    ) -> bool:
        """Return whether the active configured model declares one response mode.

        Callers can request structured output opportunistically without turning
        a model that lacks the capability into a request-layer failure.
        ``remote_chat`` still enforces the capability whenever a format is
        actually requested.
        """
        capability = str(response_format or "").strip()
        if not capability:
            return False
        selected_model = str(model or self.model_name or "").strip()
        if not selected_model:
            return False
        try:
            model_spec = resolve_model(
                self._project_config,
                selected_model,
                self.provider_name,
            )
        except (TypeError, ValueError):
            return False
        return bool(getattr(model_spec.capabilities, capability, False))

    @staticmethod
    def _append_json_object_contract(
        text_content: str,
        response_format: str | None,
    ) -> str:
        """Make JSON-object mode self-contained for compatible providers.

        Some OpenAI-compatible endpoints reject ``response_format=json_object``
        unless the *message text* explicitly mentions json.  Keeping this at
        the transport boundary protects every structured-output call site,
        including ones added later, instead of relying on every prompt template
        to remember a provider-specific sentence.
        """
        if str(response_format or "").strip().lower() != "json_object":
            return text_content
        contract = (
            "Structured-output contract: return exactly one valid json object. "
            "Do not use Markdown fences, prose, or any text outside the json object."
        )
        content = str(text_content or "").rstrip()
        if contract in content:
            return content
        # The generic input limiter truncates from the end.  Put the provider
        # contract first so it remains present even when a very long prompt is
        # reduced to fit the context window.
        return f"{contract}\n\n{content}" if content else contract

    def _raise_for_unsuccessful_chat_response(
        self,
        response,
        *,
        model: str,
        response_format: str | None,
    ) -> None:
        """Classify HTTP failures before the retry machinery sees them."""
        status_code = int(getattr(response, "status_code", 0) or 0)
        if status_code == 200:
            return

        response_body = str(getattr(response, "text", "") or "")
        response_excerpt = response_body[:500].replace("\n", " ").strip()
        retryable_status = {408, 429, 500, 502, 503, 504, 529}
        if status_code in retryable_status:
            self.logger.error("chat response code: %s, retrying...", status_code)
            raise TransientHTTPError(f"Retryable status: {status_code}")

        self.logger.error(
            "chat response code: %s, model=%s, url=%s, token=%s, body=%s",
            status_code,
            model,
            self.remote_url,
            self._mask_token(self.token),
            response_excerpt or "<empty>",
        )

        # Bad request and the remaining client errors are request-contract or
        # credential/path problems.  Replaying an identical prompt cannot make
        # them succeed, so they must never enter the tenacity or batch retry
        # loops.
        if 400 <= status_code < 500:
            lower_body = response_body.lower()
            if (
                status_code == 400
                and str(response_format or "").strip().lower() == "json_object"
                and "must contain the word 'json'" in lower_body
            ):
                message = (
                    "Qwen rejected json_object mode because the provider reports "
                    "that the request messages lack a json instruction. "
                    f"HTTP {status_code}; provider response: {response_body}"
                )
            else:
                message = (
                    f"Non-retryable Chat Completions client error HTTP {status_code}; "
                    f"provider response: {response_body}"
                )
            raise NonRetryableRequestError(
                message,
                status_code=status_code,
                response_body=response_body,
            )

        # Preserve prior behavior for unexpected status classes.  They remain
        # request exceptions and are therefore governed by the existing retry
        # policy.
        response.raise_for_status()

    @retry(
        stop=stop_after_attempt(10),
        wait=wait_exponential(min=1, max=300),
        retry=retry_if_exception_type((requests.RequestException, TransientHTTPError)),
    )
    def remote_chat(
        self,
        text_content: str,
        image_urls: list[str] = None,
        local_images: list[Path] = None,
        temperature: float = 0.5,
        debug: bool = False,
        model=None,
        max_output_tokens: int = 16000,
        response_format: str | None = None,
        request_timeout: float | None = None,
        strict_input_budget: bool = False,
    ) -> str:
        """Chat with remote LLM, return result. Minimal logging; no file writes."""
        if model is None:
            model = self.model_name
        model = str(model or "").strip()
        if not model:
            raise ValueError("Survey ChatAgent requires a non-empty model name.")
        required_capabilities = ["chat_completions"]
        if bool(self.config.APIInfo.use_stream_mode):
            required_capabilities.append("streaming")
        if image_urls or local_images:
            required_capabilities.append("vision")
        if response_format:
            required_capabilities.append(response_format)
        require_model_capabilities(
            resolve_model(self._project_config, model, self.provider_name),
            required_capabilities,
            "Survey ChatAgent",
        )

        text_content = self._append_json_object_contract(
            text_content,
            response_format,
        )

        # Estimate input tokens and truncate if necessary to leave room for output.
        context_window = int(self.config.APIInfo.llm_max_context_length)
        if max_output_tokens <= 0 or max_output_tokens >= context_window:
            raise ValueError(
                "max_output_tokens must be positive and smaller than the configured context window."
            )
        input_tokens, enc = self.encode_with_fallback(text_content, model=model)
        input_token_count = len(input_tokens)

        # Reserve space for output tokens
        max_input_tokens = context_window - max_output_tokens

        if input_token_count > max_input_tokens:
            if strict_input_budget:
                raise PromptBudgetExceeded(
                    "Strict full-text prompt exceeds the request input budget: "
                    f"{input_token_count} > {max_input_tokens} tokens."
                )
            self.logger.warning(
                f"Input tokens ({input_token_count}) exceeds max allowed ({max_input_tokens}). "
                f"Truncating to fit context window."
            )
            truncated_tokens = input_tokens[:max_input_tokens]
            text_content = enc.decode(truncated_tokens)

        url = self.remote_url
        header = self.header
        messages = [{"role": "user", "content": text_content}]

        if image_urls:
            image_url_frame = [
                {"type": "image_url", "image_url": {"url": u}} for u in image_urls
            ]
            messages.append({"role": "user", "content": image_url_frame})

        # Determine if streaming is enabled
        use_stream = self.config.APIInfo.use_stream_mode
        
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "stream": use_stream,
        }
        if self.token_limit_parameter:
            payload[self.token_limit_parameter] = max_output_tokens
        if response_format:
            payload["response_format"] = {"type": response_format}
        
        # Enable stream=True in requests if streaming mode is on
        chat_timeout = getattr(self.config.APIInfo, "chat_timeout", 120)
        if request_timeout is not None:
            if request_timeout <= 0:
                raise ValueError("request_timeout must be positive when provided.")
            chat_timeout = min(chat_timeout, request_timeout)
        response = requests.post(url, headers=header, json=payload, timeout=chat_timeout, stream=use_stream)
        res = None
        if self.config.APIInfo.low_flow_mode:
            time.sleep(self.config.APIInfo.low_flow_latency)

        # Handle deterministic request failures before either streaming or
        # non-streaming code can turn them into generic retryable errors.
        if response.status_code != 200:
            self._raise_for_unsuccessful_chat_response(
                response,
                model=model,
                response_format=response_format,
            )

        # Handle Streaming Response
        if use_stream:
            response.raise_for_status()
            collected_content = []
            for line in response.iter_lines():
                if line:
                    decoded_line = line.decode('utf-8').strip()
                    if decoded_line.startswith("data:"):
                        json_str = decoded_line[5:].strip()
                        if json_str == "[DONE]":
                            break
                        try:
                            chunk = json.loads(json_str)
                            if chunk.get("error"):
                                raise requests.RequestException(
                                    f"Streaming API error: {chunk['error']}"
                                )
                            if "choices" in chunk and len(chunk["choices"]) > 0:
                                delta = chunk["choices"][0].get("delta", {})
                                content = delta.get("content", "")
                                if content:
                                    collected_content.append(content)
                        except json.JSONDecodeError:
                            continue
            
            res_text = "".join(collected_content)
            if not res_text:
                raise requests.RequestException(
                    "Streaming response completed without final content."
                )
            if debug:
                return res_text, response
            return res_text

        # Handle Normal (Non-Streaming) Response - Original Logic
        # Check for moderation blocks first using response.text
        response_text = response.text
        if "moderation block" in response_text.lower() or "moderation" in response_text.lower() or "Moderation Block" in response_text:
            self.logger.warning(f"Moderation blocked the prompt: {text_content}")
            raise ValueError("prompt blocked by moderation")

        try:
            res = response.json()
            # Check for API-level errors where choices is null
            if res.get("choices") is None:
                base_resp = res.get("base_resp", {})
                status_msg = base_resp.get("status_msg", "unknown error")
                status_code = base_resp.get("status_code", "unknown")
                self.logger.error(
                    f"API returned error: status_code={status_code}, status_msg={status_msg}"
                )
                # Treat this as a retryable error so the @retry decorator can handle it
                raise requests.RequestException(f"API error: {status_msg} (code: {status_code})")
            res_text = res["choices"][0]["message"]["content"]
            if not res_text:
                raise requests.RequestException(
                    "Chat Completions response did not contain final content."
                )
        except json.JSONDecodeError as e:
            self.logger.error(f"JSON decode error: {e}")
            self.logger.error(f"Raw response text (first 500 chars): {response_text[:500]}")
            raise e
        except requests.RequestException:
            # Re-raise RequestException to let @retry handle it
            raise
        except Exception as e:
            self.logger.error(f"There is an error in remote_chat: {e}")
            self.logger.error(f"Raw response text (first 500 chars): {response_text[:500] if 'response_text' in dir() else 'N/A'}")
            raise e

        if debug:
            return res_text, response
        return res_text

    def __remote_chat(
        self,
        index,
        content,
        temperature: float = 0.5,
        debug: bool = False,
        request_timeout: float | None = None,
        retry: bool = True,
        strict_input_budget: bool = False,
        max_output_tokens: int = 16000,
        response_format: str | None = None,
    ):
        model = self.model_name
        if retry:
            response = self.remote_chat(
                text_content=content,
                image_urls=None,
                local_images=None,
                temperature=temperature,
                debug=debug,
                model=model,
                request_timeout=request_timeout,
                strict_input_budget=strict_input_budget,
                max_output_tokens=max_output_tokens,
                response_format=response_format,
            )
        else:
            response = type(self).remote_chat.__wrapped__(
                self,
                text_content=content,
                image_urls=None,
                local_images=None,
                temperature=temperature,
                debug=debug,
                model=model,
                request_timeout=request_timeout,
                strict_input_budget=strict_input_budget,
                max_output_tokens=max_output_tokens,
                response_format=response_format,
            )
        return index, response

    def _configure_token_admission(self, max_in_flight_tokens: int) -> None:
        """Install a process-local, per-agent long-context admission budget.

        ``Future.cancel`` cannot stop a request that has already entered the
        HTTP stack.  This limiter is deliberately retained across request waves
        so a paper-level retry cannot begin another large prompt while a timed
        out prior wave is still physically in flight.
        """

        condition = getattr(self, "_token_admission_condition", None)
        if condition is None:
            condition = threading.Condition()
            self._token_admission_condition = condition
            self._token_admission_limit = int(max_in_flight_tokens)
            self._token_admission_used = 0
            return
        with condition:
            current_limit = int(
                getattr(self, "_token_admission_limit", max_in_flight_tokens)
            )
            # Multiple long-context call sites share one ChatAgent.  Taking
            # the smaller active setting remains safe when configurations are
            # mixed, while the default configuration uses the same value.
            self._token_admission_limit = min(current_limit, int(max_in_flight_tokens))

    def _token_admitted_remote_chat(
        self,
        *,
        index: int,
        prompt: str,
        temperature: float,
        future_timeout: float,
        strict_input_budget: bool,
        max_output_tokens: int,
        response_format: str | None,
    ):
        """Run one request only after it acquires the shared token budget."""

        condition = getattr(self, "_token_admission_condition", None)
        limit = getattr(self, "_token_admission_limit", None)
        if condition is None or not limit:
            return self.__remote_chat(
                index,
                prompt,
                temperature,
                False,
                future_timeout,
                False,
                strict_input_budget,
                max_output_tokens,
                response_format,
            )

        estimated_tokens = max(1, int(self.estimate_tokens(prompt)))
        admitted_tokens = min(estimated_tokens, int(limit))
        deadline = time.monotonic() + float(future_timeout)
        with condition:
            while (
                getattr(self, "_token_admission_used", 0)
                and getattr(self, "_token_admission_used", 0) + admitted_tokens > limit
            ):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError(
                        "Timed out waiting for the shared long-context token admission slot."
                    )
                condition.wait(timeout=remaining)
            self._token_admission_used = (
                getattr(self, "_token_admission_used", 0) + admitted_tokens
            )
        try:
            # retry=False intentionally bypasses remote_chat's tenacity loop;
            # callers already own bounded paper/packet retry policies.
            return self.__remote_chat(
                index,
                prompt,
                temperature,
                False,
                future_timeout,
                False,
                strict_input_budget,
                max_output_tokens,
                response_format,
            )
        finally:
            with condition:
                self._token_admission_used = max(
                    0, getattr(self, "_token_admission_used", 0) - admitted_tokens
                )
                condition.notify_all()

    def _default_validate_fn(self, result: str, info_dict: dict = None) -> bool:
        """Default validation function that checks if the result is a non-empty string."""
        if not result or len(result) == 0:
            raise ValueError("Validation failed: Result is empty or not a string.")
        return True, result

    def remote_chat_with_retry(
        self,
        prompt: str,
        validate_fn: callable = None,
        max_retry: int = 5,
        temperature: float = 0.5,
        debug: bool = False,
        model=None,
        info_dict: dict = {},
        response_format: str | None = None,
    ) -> str:
        """
        Chat with remote LLM with retry logic for failed validations.
        
        Args:
            prompt: The prompt to send to the LLM
            validate_fn: A function that takes a result string and returns True if valid, 
                        raises ValueError/Exception if invalid. If None, no validation.
            max_retry: Maximum number of retry attempts
            temperature: Temperature for LLM
            debug: If True, return (response, response) tuple
            model: Model to use (defaults to self.model_name)
            
        Returns:
            The validated response string
            
        Raises:
            ValueError: If validation fails after max_retry attempts
        """
        if model is None:
            model = self.model_name
        if validate_fn is None:
            validate_fn = self._default_validate_fn

        info_dict["max_retry"] = max_retry
        for retry in range(max_retry):
            info_dict["retry_time"] = retry
            result = None
            try:
                result = self.remote_chat(
                    text_content=prompt,
                    temperature=temperature,
                    debug=debug,
                    model=model,
                    response_format=response_format,
                )
                
                # If no validation function, return directly
                if validate_fn is None:
                    return result
                
                # Validate the result
                val, result = validate_fn(result, info_dict)
                if not val:
                    raise ValueError("Validation failed for remote chat")
                return result
                
            except Exception as e:
                if retry < max_retry - 1:
                    self.logger.warning(
                        f"remote_chat_with_retry attempt {retry + 1}/{max_retry} failed: {e}. Retrying..."
                    )
                    if self.config.BasicInfo.debug and result:
                        self.logger.warning(f"return text: {result}...")
                    # Exponential backoff wait time
                    if self.exponential_backoff:
                        wait_time = min(
                            self.exponential_backoff_max_time,
                            self.exponential_backoff_time * (2 ** retry)
                        )
                        self.logger.info(f"Exponential backoff: waiting {wait_time:.2f}s before retry...")
                        time.sleep(wait_time)
                    else:
                        time.sleep(min(5, 1 + retry))
                else:
                    self.logger.error(
                        f"remote_chat_with_retry failed after {max_retry} attempts: {e}"
                    )
                    if self.config.BasicInfo.debug:
                        self.logger.warning(f"return text: {result[:50]}...")
                    raise ValueError(
                        f"remote_chat_with_retry failed after {max_retry} attempts: {e}"
                    )
        
        # Should not reach here, but just in case
        raise ValueError(f"remote_chat_with_retry failed after {max_retry} retries")

    def batch_remote_chat(
        self,
        prompt_l: list[str],
        desc: str = "batch_chating...",
        workers: int = None,
        temperature: float = 0.5,
        future_timeout: float = None,
        strict_input_budget: bool = False,
        max_output_tokens: int = 16000,
        response_format: str | None = None,
        max_in_flight_tokens: int | None = None,
    ) -> list[str]:
        if workers is None:
            workers = self.batch_workers
        if future_timeout is None:
            future_timeout = getattr(self.config.APIInfo, "batch_chat_timeout", 600.0)
        if workers <= 0:
            raise ValueError("workers must be positive.")
        if future_timeout <= 0:
            raise ValueError("future_timeout must be positive.")
        if max_output_tokens <= 0:
            raise ValueError("max_output_tokens must be positive.")
        if max_in_flight_tokens is not None:
            max_in_flight_tokens = int(max_in_flight_tokens)
            if max_in_flight_tokens <= 0:
                raise ValueError("max_in_flight_tokens must be positive when set.")
            self._configure_token_admission(max_in_flight_tokens)

            # Keep the long-context token ceiling, but do not create static
            # waves. Static waves leave workers idle when one request in a
            # wave is slow: later admissible prompts cannot begin until that
            # entire wave ends. This rolling scheduler immediately backfills a
            # completed request with the earliest queued prompt that fits the
            # currently free local token budget. The shared token limiter in
            # ``_token_admitted_remote_chat`` remains the final cross-batch
            # safety guard, including after a timed-out request continues in
            # the provider HTTP stack.
            if not prompt_l:
                return []

            queued: list[tuple[int, str, int]] = [
                (
                    index,
                    prompt,
                    min(
                        max(1, int(self.estimate_tokens(prompt))),
                        max_in_flight_tokens,
                    ),
                )
                for index, prompt in enumerate(prompt_l)
            ]
            results: list[str | None] = [None] * len(prompt_l)
            executor = ThreadPoolExecutor(max_workers=workers)
            active: dict[object, tuple[int, int, float]] = {}
            local_admitted_tokens = 0
            deadline_reported: set[object] = set()
            terminal_error: NonRetryableRequestError | None = None

            self.logger.info(
                "Token-admitting %s batch requests with rolling scheduler: "
                "workers=%s, max_in_flight_tokens=%s, request_deadline_seconds=%.1f.",
                len(prompt_l),
                workers,
                max_in_flight_tokens,
                future_timeout,
            )

            def submit_available_requests() -> None:
                """Fill free worker/token capacity without a wave barrier."""

                nonlocal local_admitted_tokens
                while queued and len(active) < workers:
                    queue_position = next(
                        (
                            position
                            for position, (_, _, estimated_tokens) in enumerate(queued)
                            if local_admitted_tokens + estimated_tokens
                            <= max_in_flight_tokens
                        ),
                        None,
                    )
                    if queue_position is None:
                        return
                    index, prompt, estimated_tokens = queued.pop(queue_position)
                    future = executor.submit(
                        self._token_admitted_remote_chat,
                        index=index,
                        prompt=prompt,
                        temperature=temperature,
                        future_timeout=future_timeout,
                        strict_input_budget=strict_input_budget,
                        max_output_tokens=max_output_tokens,
                        response_format=response_format,
                    )
                    active[future] = (index, estimated_tokens, time.monotonic())
                    local_admitted_tokens += estimated_tokens

            try:
                with tqdm(
                    total=len(prompt_l),
                    desc=desc,
                    dynamic_ncols=True,
                ) as progress:
                    while queued or active:
                        submit_available_requests()
                        if not active:
                            # Every individual estimate is clamped to the
                            # budget, so this only protects against an
                            # unexpected scheduler invariant violation.
                            self.logger.warning(
                                "Rolling token scheduler could not admit any queued request. "
                                "Marking %s request(s) for retry.",
                                len(queued),
                            )
                            break

                        now = time.monotonic()
                        live_deadlines = [
                            started_at + future_timeout
                            for future, (_, _, started_at) in active.items()
                            if future not in deadline_reported
                        ]
                        if not live_deadlines:
                            # The underlying futures cannot reliably be
                            # cancelled after they enter requests.post. Leave
                            # their shared token reservations in place and
                            # return retry candidates instead of blocking the
                            # entire batch indefinitely.
                            break

                        done, _ = wait(
                            active,
                            timeout=max(0.0, min(live_deadlines) - now),
                            return_when=FIRST_COMPLETED,
                        )
                        if not done:
                            now = time.monotonic()
                            for future, (_, _, started_at) in active.items():
                                if (
                                    future not in deadline_reported
                                    and now >= started_at + future_timeout
                                ):
                                    deadline_reported.add(future)
                                    index = active[future][0]
                                    self.logger.warning(
                                        "Batch request %s exceeded the %.1fs request deadline; "
                                        "its in-flight token reservation remains held until the "
                                        "underlying request exits.",
                                        index,
                                        future_timeout,
                                    )
                            continue

                        for future in done:
                            index, estimated_tokens, _ = active.pop(future)
                            local_admitted_tokens = max(
                                0, local_admitted_tokens - estimated_tokens
                            )
                            progress.update(1)
                            try:
                                completed_index, response = future.result()
                            except NonRetryableRequestError as exc:
                                terminal_error = exc
                                self.logger.error(
                                    "Batch request %s received a non-retryable provider error; "
                                    "stopping without retry: %s",
                                    index,
                                    exc,
                                )
                                break
                            except Exception as exc:
                                self.logger.warning(
                                    "Batch request %s failed at the request layer: %s. "
                                    "Marking it for retry.",
                                    index,
                                    exc,
                                )
                                continue
                            results[completed_index] = response
                            self.logger.info(
                                "Batch request %s/%s completed.",
                                completed_index + 1,
                                len(prompt_l),
                            )
                            if self.config.APIInfo.low_flow_mode:
                                time.sleep(self.config.APIInfo.low_flow_latency)
                        if terminal_error is not None:
                            break
            finally:
                pending_indices = sorted(
                    [index for index, _, _ in queued]
                    + [index for index, _, _ in active.values()]
                )
                if pending_indices:
                    self.logger.warning(
                        "Batch request rolling scheduler exceeded or ended with "
                        f"{future_timeout:.1f}s; marking {len(pending_indices)} pending "
                        f"request(s) for retry: {pending_indices}."
                    )
                    for future in active:
                        future.cancel()
                if terminal_error is None and any(
                    response is None for response in results
                ):
                    self.logger.warning(
                        "Some batch_remote_chat tasks did not complete successfully."
                    )
                # Do not block a retry on a request that exceeded its deadline;
                # the shared token admission condition still prevents it from
                # overlapping another oversized request.
                executor.shutdown(
                    wait=not bool(active),
                    cancel_futures=bool(active),
                )
            if terminal_error is not None:
                raise terminal_error
            return results

        executor = ThreadPoolExecutor(max_workers=workers)
        future_to_index = {
            executor.submit(
                self._token_admitted_remote_chat,
                index=index,
                prompt=prompt,
                temperature=temperature,
                future_timeout=future_timeout,
                strict_input_budget=strict_input_budget,
                max_output_tokens=max_output_tokens,
                response_format=response_format,
            ): index
            for index, prompt in enumerate(prompt_l)
        }
        res_l = [None] * len(prompt_l)
        pending = set(future_to_index)
        timed_out = False
        terminal_error: NonRetryableRequestError | None = None
        try:
            for future in tqdm(
                as_completed(future_to_index, timeout=future_timeout),
                desc=desc,
                total=len(future_to_index),
                dynamic_ncols=True,
            ):
                pending.discard(future)
                try:
                    index, response = future.result()
                except NonRetryableRequestError as exc:
                    index = future_to_index[future]
                    terminal_error = exc
                    self.logger.error(
                        "Batch request %s received a non-retryable provider error; "
                        "stopping without retry: %s",
                        index,
                        exc,
                    )
                    break
                except Exception as e:
                    index = future_to_index[future]
                    self.logger.warning(
                        f"Batch request {index} failed at the request layer: {e}. Marking it for retry."
                    )
                    continue
                res_l[index] = response
                log_info = getattr(self.logger, "info", None)
                if callable(log_info):
                    log_info(
                        "Batch request %s/%s completed.",
                        index + 1,
                        len(future_to_index),
                    )
                if self.config.APIInfo.low_flow_mode:
                    time.sleep(self.config.APIInfo.low_flow_latency)
        except TimeoutError:
            timed_out = True
        finally:
            if pending:
                pending_indices = sorted(future_to_index[future] for future in pending)
                reason = "exceeded" if timed_out else "ended with"
                self.logger.warning(
                    f"Batch request wave {reason} {future_timeout:.1f}s; marking "
                    f"{len(pending_indices)} pending request(s) for retry: {pending_indices}."
                )
                for future in pending:
                    future.cancel()
            if terminal_error is None and any(response is None for response in res_l):
                self.logger.warning(
                    "Some batch_remote_chat tasks did not complete successfully."
                )
            executor.shutdown(wait=not pending, cancel_futures=bool(pending))
        if terminal_error is not None:
            raise terminal_error
        return res_l

    def batch_remote_chat_with_retry(
        self,
        prompts: list[str],
        validate_fn: callable,
        max_retry: int = 5,
        desc: str = "batch_chating with retry...",
        workers: int = None,
        temperature: float = 0.5,
        future_timeout: float = None,
        model: str = None,
        info_dict: dict = {},
        strict_input_budget: bool = False,
        max_output_tokens: int = 16000,
        response_format: str | None = None,
        max_in_flight_tokens: int | None = None,
    ) -> list[str]:
        if future_timeout is None:
            future_timeout = getattr(self.config.APIInfo, "batch_chat_timeout", 600.0)
        """
        Batch remote chat with retry logic for failed validations.
        
        Args:
            prompts: List of prompts to send to the LLM
            validate_fn: A function that takes a result string and returns True if valid, 
                        raises ValueError/Exception if invalid
            max_retry: Maximum number of retry attempts
            desc: Description for progress bar
            workers: Number of parallel workers (defaults to self.batch_workers)
            temperature: Temperature for LLM
            future_timeout: Timeout for each future
            
        Returns:
            List of results in the same order as input prompts
            
        Raises:
            ValueError: If not all results pass validation after max_retry attempts
        """
        if workers is None:
            workers = self.batch_workers
        if model is None:
            model = self.model_name
        if validate_fn is None:
            validate_fn = self._default_validate_fn

        input_prompts = prompts.copy()
        input_indices = list(range(len(prompts)))
        all_results = [None] * len(prompts)
        finished = False
        info_dict["max_retry"] = max_retry
        
        for retry in range(max_retry):
            info_dict["retry_time"] = retry
            error_prompts = []
            error_indices = []
            
            # Call batch_remote_chat for current batch of prompts
            results = self.batch_remote_chat(
                input_prompts, 
                desc=f"{desc} (retry {retry + 1}/{max_retry})",
                workers=workers,
                temperature=temperature,
                future_timeout=future_timeout,
                strict_input_budget=strict_input_budget,
                max_output_tokens=max_output_tokens,
                response_format=response_format,
                max_in_flight_tokens=max_in_flight_tokens,
            )
            if not results:
                self.logger.info(
                    f"return None "
                    f"retrying {retry + 1}/{max_retry}"
                )
                continue
            
            # Validate each result
            for i in range(len(results)):
                info_dict["idx"] = input_indices[i]
                try:
                    # Validate the result using the provided validation function
                    val, result = validate_fn(results[i], info_dict)
                    if not val:
                        raise ValueError("Validation failed")
                    # If validation passes, store the result
                    all_results[input_indices[i]] = result
                except Exception as e:
                    self.logger.warning(f"Validation failed for prompt {input_indices[i]}: {e}")
                    if self.config.BasicInfo.debug and results[i]:
                        self.logger.warning(f"return text: {results[i][:50]}...")
                    error_prompts.append(input_prompts[i])
                    error_indices.append(input_indices[i])
            
            # Check if all results are valid
            if len(error_indices) == 0 and len(error_prompts) == 0:
                finished = True
                break
            else:
                self.logger.info(
                    f"Validation failed for {len(error_prompts)}/{len(prompts)} prompts, "
                    f"retrying {retry + 1}/{max_retry}"
                )
                # Update for next retry - only process failed prompts
                input_prompts = error_prompts
                input_indices = error_indices
                
                # Exponential backoff wait time before next retry
                if self.exponential_backoff and retry < max_retry - 1:
                    wait_time = min(
                        self.exponential_backoff_max_time,
                        self.exponential_backoff_time * (2 ** retry)
                    )
                    self.logger.info(f"Exponential backoff: waiting {wait_time:.2f}s before retry...")
                    time.sleep(wait_time)
        
        if not finished:
            self.logger.error(
                f"batch_remote_chat_with_retry failed after {max_retry} retries. "
                f"Failed prompts: {len(error_prompts)}"
            )
            raise ValueError(
                f"batch_remote_chat_with_retry failed after {max_retry} retries. "
                f"{len(error_prompts)} prompts still failing validation."
            )
        
        return all_results

    def encode_with_fallback(self, text: str, model: str = "gpt-4o-mini"):
        try:
            enc = tiktoken.encoding_for_model(model)
        except Exception:
            fallback = self.tokenizer_fallback
            try:
                fallback = resolve_model(
                    self._project_config,
                    model,
                    self.provider_name,
                ).tokenizer_fallback
            except ValueError:
                pass
            enc = (
                _Utf8ByteEncoding()
                if fallback == "utf8_bytes"
                else tiktoken.get_encoding(fallback)
            )
        return enc.encode(text), enc

    def truncate_prompt(self, text: str, allowed: int, model: str = None) -> str:
        if model is None:
            model = self.model_name
        tokens, enc = self.encode_with_fallback(text, model=model)
        token_len = len(tokens)
        
        if token_len > allowed:
            self.logger.warning(f"Prompt tokens={token_len}, truncate to {allowed}")
            if allowed < 1000:
                self.logger.warning(f"Allowed tokens {allowed} too small, need to debug!")
            tokens = tokens[:allowed]
            truncate_text = enc.decode(tokens)

            if(truncate_text[:3000] != text[:3000]):
                self.logger.warning(f"Truncation error for prompt, fallback to approiximation.")
                approx_tokens = len(text) / 4  # 1 token ≈ 4 chars
                if approx_tokens > allowed:
                    new_char_len = int(allowed * 4)
                    self.logger.warning(
                        f"Paper {pid} markdown too long: ~{approx_tokens:.0f} tokens, "
                        f"truncating to ~{allowed}."
                    )
                    text = text[:new_char_len]
            else:
                text = truncate_text
        return text

    def truncate_text(self, pid:str, text: str, allowed: int) -> str:

        tokens, enc = self.encode_with_fallback(text, model=self.config.APIInfo.llm_model_name)
        token_len = len(tokens)
        
        if token_len > allowed:
            self.logger.warning(f"Paper {pid} tokens={token_len}, truncate to {allowed}")
            if allowed < 1000:
                self.logger.warning(f"Allowed tokens {allowed} too small, need to debug!")
            tokens = tokens[:allowed]
            truncate_text = enc.decode(tokens)

            if(truncate_text[:3000] != text[:3000]):
                self.logger.warning(f"Truncation error for paper {pid}, fallback to approiximation.")
                approx_tokens = len(text) / 4  # 1 token ≈ 4 chars
                if approx_tokens > allowed:
                    new_char_len = int(allowed * 4)
                    self.logger.warning(
                        f"Paper {pid} markdown too long: ~{approx_tokens:.0f} tokens, "
                        f"truncating to ~{allowed}."
                    )
                    text = text[:new_char_len]
            else:
                text = truncate_text
        return text

    def estimate_tokens(self, text: str) -> int:
        tokens, enc = self.encode_with_fallback(text, model=self.config.APIInfo.llm_model_name)
        token_len = len(tokens)
        return token_len


if __name__ == "__main__":
    # # test LLM API call
    # test_prompt = "Explain the theory of relativity in simple terms."
    # # load config
    # from omegaconf import OmegaConf

    # config = OmegaConf.load("config/deep_survey.yaml")
    # chat_agent = ChatAgent(config)
    # response = chat_agent.remote_chat(test_prompt, temperature=0.7, debug=True)
    # print("LLM API Response:")
    # print(response)

    # test Semantic Scholar API call
    from omegaconf import OmegaConf

    config = OmegaConf.load("config/deep_survey.yaml")
    semantic_scholar_api = SemanticScholarAPI(config)
    # query = '"auto survey"'
    # fields = "title,externalIds,openAccessPdf"
    # response = semantic_scholar_api.search_papers(query=query, fields=fields)
    # print("Semantic Scholar API Response:")
    # print(response["data"][:10])
    paper_id = "ARXIV:2505.11711"
    fields = "title,year,abstract,authors,externalIds,citations"
    response = semantic_scholar_api.get_paper_details(paper_id=paper_id, fields=fields)
    print("Semantic Scholar API Paper Details Response:")
    print(response)
