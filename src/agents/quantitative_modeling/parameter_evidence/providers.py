"""Bounded academic-metadata providers for parameter evidence discovery.

Providers only discover citable works and declared open-access locations.  They
never convert abstracts, snippets, or provider metadata into numerical
parameter evidence.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import requests


class ParameterEvidenceProviderError(RuntimeError):
    """Raised when a bounded academic metadata request cannot be completed."""


JsonGet = Callable[..., object]


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _text(value: object) -> str:
    return str(value or "").strip()


def _setting(value: object, name: str, default: Any = "") -> Any:
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


def _positive_int(value: object, *, default: int, minimum: int = 1) -> int:
    try:
        return max(minimum, int(value))
    except (TypeError, ValueError):
        return default


def _bounded_float(value: object, *, default: float, minimum: float, maximum: float) -> float:
    try:
        return max(minimum, min(maximum, float(value)))
    except (TypeError, ValueError):
        return default


def _safe_url(value: object) -> str:
    url = _text(value)
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    return url


def _normalize_doi(value: object) -> str:
    doi = _text(value)
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        if doi.casefold().startswith(prefix):
            doi = doi[len(prefix) :]
            break
    return doi.strip().rstrip("/.,;")


def _default_json_get(
    url: str,
    *,
    params: Mapping[str, object] | None = None,
    headers: Mapping[str, str] | None = None,
    timeout: float = 30.0,
) -> object:
    try:
        response = requests.get(url, params=dict(params or {}), headers=dict(headers or {}), timeout=timeout)
    except requests.RequestException as error:
        raise ParameterEvidenceProviderError(f"academic metadata request failed: {type(error).__name__}") from error
    if response.status_code >= 400:
        raise ParameterEvidenceProviderError(f"academic metadata request returned HTTP {response.status_code}")
    try:
        return response.json()
    except ValueError as error:
        raise ParameterEvidenceProviderError("academic metadata provider returned invalid JSON") from error


@dataclass(frozen=True)
class ParameterEvidenceSettings:
    """Non-secret runtime settings; API secrets remain in environment variables."""

    openalex_base_url: str = "https://api.openalex.org"
    semantic_scholar_base_url: str = "https://api.semanticscholar.org/graph/v1"
    unpaywall_base_url: str = "https://api.unpaywall.org/v2"
    openalex_api_key: str = ""
    semantic_scholar_api_key: str = ""
    unpaywall_email: str = ""
    enabled: bool = True
    discovery_providers: tuple[str, ...] = ("openalex", "unpaywall")
    max_papers_per_parameter: int = 12
    max_fulltext_documents_per_parameter: int = 5
    fulltext_max_bytes: int = 20 * 1024 * 1024
    max_document_chars_for_extraction: int = 40_000
    request_timeout_seconds: int = 30
    max_oa_pdf_candidates_per_paper: int = 2
    fulltext_http_max_retries: int = 1
    fulltext_connect_timeout_seconds: int = 5
    fulltext_read_timeout_seconds: int = 30
    extraction_max_output_tokens: int = 1200
    extraction_temperature: float = 0.0
    extraction_stream: bool = False
    extraction_workers: int = 3
    fulltext_workers: int = 4
    fulltext_per_host_concurrency: int = 2
    max_snippets_per_parameter: int = 3
    context_pages_before: int = 1
    context_pages_after: int = 1
    max_snippet_characters: int = 6000
    minimum_keyword_hits: int = 2
    cache_enabled: bool = True
    stop_when_required_parameters_covered: bool = True

    @classmethod
    def from_runtime_config(cls, config: object) -> "ParameterEvidenceSettings":
        quantitative = _setting(config, "quantitative_modeling", {})
        evidence = _setting(quantitative, "parameter_evidence", {})
        api = _setting(config, "api", {})
        semantic = _setting(api, "semantic_scholar", {})
        configured_providers = _setting(
            evidence,
            "discovery_providers",
            ["openalex", "unpaywall"],
        )
        if not isinstance(configured_providers, (list, tuple)):
            configured_providers = ["openalex", "unpaywall"]
        discovery_providers = tuple(
            dict.fromkeys(
                provider
                for provider in (_text(value).casefold() for value in configured_providers)
                if provider in {"openalex", "semantic_scholar", "unpaywall"}
            )
        )
        return cls(
            openalex_base_url=_text(_setting(evidence, "openalex_base_url", "https://api.openalex.org"))
            or "https://api.openalex.org",
            semantic_scholar_base_url=_text(
                _setting(evidence, "semantic_scholar_base_url", "https://api.semanticscholar.org/graph/v1")
            )
            or "https://api.semanticscholar.org/graph/v1",
            unpaywall_base_url=_text(_setting(evidence, "unpaywall_base_url", "https://api.unpaywall.org/v2"))
            or "https://api.unpaywall.org/v2",
            openalex_api_key=_text(os.environ.get("OPENALEX_API_KEY")),
            semantic_scholar_api_key=_text(
                os.environ.get("SEMANTIC_SCHOLAR_API_KEY") or _setting(semantic, "api_key", "")
            ),
            unpaywall_email=_text(os.environ.get("UNPAYWALL_EMAIL")),
            enabled=bool(_setting(evidence, "enabled", True)),
            discovery_providers=discovery_providers,
            max_papers_per_parameter=_positive_int(
                _setting(evidence, "max_papers_per_parameter", 12), default=12
            ),
            max_fulltext_documents_per_parameter=_positive_int(
                _setting(evidence, "max_fulltext_documents_per_parameter", 5), default=5
            ),
            fulltext_max_bytes=_positive_int(
                _setting(evidence, "fulltext_max_bytes", 20 * 1024 * 1024), default=20 * 1024 * 1024
            ),
            max_document_chars_for_extraction=_positive_int(
                _setting(evidence, "max_document_chars_for_extraction", 40_000), default=40_000
            ),
            request_timeout_seconds=_positive_int(
                _setting(evidence, "request_timeout_seconds", 30), default=30
            ),
            max_oa_pdf_candidates_per_paper=_positive_int(
                _setting(evidence, "max_oa_pdf_candidates_per_paper", 2), default=2
            ),
            fulltext_http_max_retries=max(
                0, int(_setting(evidence, "fulltext_http_max_retries", 1) or 1)
            ),
            fulltext_connect_timeout_seconds=_positive_int(
                _setting(evidence, "fulltext_connect_timeout_seconds", 5), default=5
            ),
            fulltext_read_timeout_seconds=_positive_int(
                _setting(evidence, "fulltext_read_timeout_seconds", 30), default=30
            ),
            extraction_max_output_tokens=_positive_int(
                _setting(evidence, "extraction_max_output_tokens", 1200), default=1200
            ),
            extraction_temperature=_bounded_float(
                _setting(evidence, "extraction_temperature", 0.0),
                default=0.0,
                minimum=0.0,
                maximum=2.0,
            ),
            extraction_stream=bool(_setting(evidence, "extraction_stream", False)),
            extraction_workers=_positive_int(_setting(evidence, "extraction_workers", 3), default=3),
            fulltext_workers=_positive_int(_setting(evidence, "fulltext_workers", 4), default=4),
            fulltext_per_host_concurrency=_positive_int(
                _setting(evidence, "fulltext_per_host_concurrency", 2), default=2
            ),
            max_snippets_per_parameter=_positive_int(
                _setting(evidence, "max_snippets_per_parameter", 3), default=3
            ),
            context_pages_before=max(
                0, int(_setting(evidence, "context_pages_before", 1) or 0)
            ),
            context_pages_after=max(
                0, int(_setting(evidence, "context_pages_after", 1) or 0)
            ),
            max_snippet_characters=_positive_int(
                _setting(evidence, "max_snippet_characters", 6000), default=6000
            ),
            minimum_keyword_hits=_positive_int(
                _setting(evidence, "minimum_keyword_hits", 2), default=2
            ),
            cache_enabled=bool(_setting(evidence, "cache_enabled", True)),
            stop_when_required_parameters_covered=bool(
                _setting(evidence, "stop_when_required_parameters_covered", True)
            ),
        )


class AcademicMetadataProviders:
    """Small provider adapters with a test-injectable JSON transport."""

    def __init__(self, settings: ParameterEvidenceSettings, *, json_get: JsonGet | None = None) -> None:
        self.settings = settings
        self._json_get = json_get or _default_json_get

    def _get_json(
        self,
        url: str,
        *,
        params: Mapping[str, object] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> dict[str, Any]:
        value = self._json_get(
            url,
            params=params,
            headers=headers,
            timeout=float(self.settings.request_timeout_seconds),
        )
        if not isinstance(value, Mapping):
            raise ParameterEvidenceProviderError("academic metadata provider response must be an object")
        return dict(value)

    @staticmethod
    def _openalex_locations(work: Mapping[str, object]) -> list[dict[str, str]]:
        locations: list[dict[str, str]] = []
        raw_locations = [work.get("best_oa_location"), work.get("primary_location")]
        raw_locations.extend(list(work.get("locations") or []))
        for raw_location in raw_locations:
            location = _mapping(raw_location)
            if location and location.get("is_oa") is False:
                continue
            pdf_url = _safe_url(location.get("pdf_url"))
            landing_url = _safe_url(location.get("landing_page_url"))
            if not pdf_url and not landing_url:
                continue
            candidate = {
                "source": "openalex.oa_location",
                "pdf_url": pdf_url,
                "landing_url": landing_url,
            }
            if candidate not in locations:
                locations.append(candidate)
        return locations

    def search_openalex(self, query: str) -> list[dict[str, Any]]:
        if not self.settings.openalex_api_key:
            return []
        base = self.settings.openalex_base_url.rstrip("/")
        response = self._get_json(
            f"{base}/works",
            params={"search": query, "per-page": self.settings.max_papers_per_parameter},
            headers={"Authorization": f"Bearer {self.settings.openalex_api_key}"},
        )
        records: list[dict[str, Any]] = []
        for raw in response.get("results") or []:
            work = _mapping(raw)
            title = _text(work.get("title"))
            if not title:
                continue
            records.append(
                {
                    "provider": "openalex",
                    "provider_paper_id": _text(work.get("id")),
                    "title": title,
                    "doi": _normalize_doi(work.get("doi")),
                    "year": work.get("publication_year"),
                    "oa_locations": self._openalex_locations(work),
                }
            )
        return records

    def search_semantic_scholar(self, query: str) -> list[dict[str, Any]]:
        base = self.settings.semantic_scholar_base_url.rstrip("/")
        headers = (
            {"x-api-key": self.settings.semantic_scholar_api_key}
            if self.settings.semantic_scholar_api_key
            else {}
        )
        response = self._get_json(
            f"{base}/paper/search",
            params={
                "query": query,
                "limit": self.settings.max_papers_per_parameter,
                "fields": "paperId,title,externalIds,year,openAccessPdf,url",
            },
            headers=headers,
        )
        records: list[dict[str, Any]] = []
        for raw in response.get("data") or []:
            work = _mapping(raw)
            title = _text(work.get("title"))
            if not title:
                continue
            external_ids = _mapping(work.get("externalIds"))
            oa_pdf = _mapping(work.get("openAccessPdf"))
            pdf_url = _safe_url(oa_pdf.get("url"))
            records.append(
                {
                    "provider": "semantic_scholar",
                    "provider_paper_id": _text(work.get("paperId")),
                    "title": title,
                    "doi": _normalize_doi(external_ids.get("DOI")),
                    "year": work.get("year"),
                    "oa_locations": [
                        {
                            "source": "semantic_scholar.open_access_pdf",
                            "pdf_url": pdf_url,
                            "landing_url": _safe_url(work.get("url")),
                        }
                    ]
                    if pdf_url
                    else [],
                }
            )
        return records

    def resolve_unpaywall(self, doi: str) -> list[dict[str, str]]:
        normalized_doi = _normalize_doi(doi)
        if not normalized_doi or not self.settings.unpaywall_email:
            return []
        base = self.settings.unpaywall_base_url.rstrip("/")
        response = self._get_json(
            f"{base}/{normalized_doi}",
            params={"email": self.settings.unpaywall_email},
        )
        locations: list[dict[str, str]] = []
        raw_locations = [response.get("best_oa_location")]
        raw_locations.extend(list(response.get("oa_locations") or []))
        for raw_location in raw_locations:
            location = _mapping(raw_location)
            pdf_url = _safe_url(location.get("url_for_pdf"))
            landing_url = _safe_url(location.get("url"))
            if not pdf_url and not landing_url:
                continue
            candidate = {
                "source": "unpaywall.oa_location",
                "pdf_url": pdf_url,
                "landing_url": landing_url,
            }
            if candidate not in locations:
                locations.append(candidate)
        return locations


__all__ = [
    "AcademicMetadataProviders",
    "JsonGet",
    "ParameterEvidenceProviderError",
    "ParameterEvidenceSettings",
]
