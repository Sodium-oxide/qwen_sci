"""Legal open-access full-text candidate resolution.

This module deliberately plans bounded, provenance-rich download candidates; it
does not decide whether a paper is relevant to a project or sub-hypothesis, and
it does not attempt to bypass publisher access controls.
"""

from __future__ import annotations

from html.parser import HTMLParser
from typing import Any, Iterable, Mapping
from urllib.parse import quote, urljoin, urlsplit, urlunsplit
import time

import requests


OA_PRIORITY_UNPAYWALL_BEST = 0
OA_PRIORITY_UNPAYWALL_OTHER = 10
OA_PRIORITY_OPENALEX_BEST = 30
OA_PRIORITY_OPENALEX_OTHER = 40
OA_PRIORITY_IDENTIFIER_REPOSITORY = 100
OA_PRIORITY_METADATA_REPOSITORY = 120
OA_PRIORITY_GENERIC_METADATA = 130
OA_PRIORITY_PROVIDER_URL = 140
# DOI recovery runs immediately after Unpaywall candidates (0/1/10/11),
# before generic metadata and provider routes.  It remains deliberately
# conditional on an OA declaration.
OA_PRIORITY_DOI_LANDING = 20


_GENERIC_METADATA_URL_FIELDS = (
    # A source that explicitly calls a value a PDF is safe to try as a direct
    # candidate.  The downloader still verifies its bytes before retaining it.
    ("pdf_url", "metadata.pdf_url", "pdf"),
    ("url_for_pdf", "metadata.url_for_pdf", "pdf"),
    ("full_text_pdf_url", "metadata.full_text_pdf_url", "pdf"),
    ("fulltext_pdf_url", "metadata.fulltext_pdf_url", "pdf"),
    ("oa_pdf_url", "metadata.oa_pdf_url", "pdf"),
    # These URLs are common interchange fields.  A URL with a PDF-shaped path
    # is a direct candidate; a non-PDF landing page must also carry an explicit
    # OA signal before the resolver is allowed to fetch and inspect it.
    ("full_text_url", "metadata.full_text_url", "auto"),
    ("fulltext_url", "metadata.fulltext_url", "auto"),
    ("full_text", "metadata.full_text", "auto"),
    ("landing_page_url", "metadata.landing_page_url", "landing_page"),
    ("url_for_landing_page", "metadata.url_for_landing_page", "landing_page"),
)


def normalize_http_url(value: Any) -> str:
    """Return an HTTP(S) URL without a fragment, or an empty string.

    HTTP scheme and host are case-insensitive.  A repository path and query
    string are not: notably, signed URL parameters commonly encode case.
    """
    raw = str(value or "").strip()
    if not raw:
        return ""
    parsed = urlsplit(raw)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        return ""
    return urlunsplit(
        (parsed.scheme.lower(), parsed.netloc.lower(), parsed.path, parsed.query, "")
    )


def _external_ids(paper: Mapping[str, Any]) -> Mapping[str, Any]:
    external_ids = paper.get("externalIds") or paper.get("external_ids")
    return external_ids if isinstance(external_ids, Mapping) else {}


def _paper_doi(paper: Mapping[str, Any], unpaywall_api: Any) -> str:
    external_ids = _external_ids(paper)
    value = (
        external_ids.get("DOI")
        or external_ids.get("doi")
        or paper.get("doi")
        or ""
    )
    normalize_doi = getattr(unpaywall_api, "normalize_doi", None)
    return str(normalize_doi(value) if callable(normalize_doi) else value or "").strip()


def _is_truthy_oa_value(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().casefold() in {"1", "true", "yes", "open", "oa"}


def _explicit_oa_evidence(paper: Mapping[str, Any]) -> str:
    """Return a non-secret OA declaration suitable for limited landing recovery.

    A generic landing-page URL alone is deliberately insufficient.  That
    avoids treating a publisher's ordinary metadata URL as permission to crawl
    its subscription route.  The accepted forms are provider-neutral metadata
    fields used by common scholarly APIs.
    """
    for key in ("is_oa", "isOpenAccess", "open_access", "openAccess"):
        value = paper.get(key)
        if _is_truthy_oa_value(value):
            return f"metadata.{key}"
        if isinstance(value, Mapping):
            if _is_truthy_oa_value(value.get("is_oa")) or _is_truthy_oa_value(
                value.get("isOpenAccess")
            ):
                return f"metadata.{key}.is_oa"
            oa_status = str(value.get("oa_status") or value.get("status") or "").strip()
            if oa_status.casefold() in {"gold", "green", "hybrid", "bronze", "open"}:
                return f"metadata.{key}.oa_status"
    return ""


def _generic_metadata_values(
    paper: Mapping[str, Any],
) -> Iterable[tuple[str, str, str, str]]:
    """Yield standardized generic full-text fields from top-level metadata.

    The pipeline deliberately does not scan arbitrary nested dictionaries for
    strings resembling URLs.  That would make an unrelated publisher URL look
    like a declared full-text route.  Only documented interchange field names
    are accepted, first at the top level and then in ``fulltext``/``full_text``
    containers used by external collectors.
    """
    containers: list[tuple[str, Mapping[str, Any]]] = [("", paper)]
    for container_name in ("fulltext", "full_text"):
        container = paper.get(container_name)
        if isinstance(container, Mapping):
            containers.append((f"{container_name}.", container))
    for prefix, container in containers:
        for key, source, route_type in _GENERIC_METADATA_URL_FIELDS:
            value = str(container.get(key) or "").strip()
            if value:
                # The field name is separately persisted so provenance can
                # explain how this route entered the candidate queue.
                yield f"{prefix}{key}", source, route_type, value


def _add_candidate(
    candidates_by_url: dict[str, dict[str, Any]],
    candidate: Mapping[str, Any],
) -> None:
    normalized_url = normalize_http_url(candidate.get("url"))
    if not normalized_url:
        return
    normalized = dict(candidate)
    normalized["url"] = normalized_url
    normalized["kind"] = "landing_page" if normalized.get("kind") == "landing_page" else "pdf"
    # A DOI resolver URL is a metadata/redirect route, never the PDF bytes
    # themselves.  Treat a provider-mislabelled DOI URL as a bounded landing
    # page so it is not requested with a PDF Range header.
    parsed = urlsplit(normalized_url)
    if normalized["kind"] == "pdf" and parsed.netloc.casefold() in {"doi.org", "dx.doi.org"}:
        normalized["kind"] = "landing_page"
    normalized["priority"] = int(normalized.get("priority") or 0)
    normalized["source"] = str(normalized.get("source") or "unknown")
    # `normalize_http_url()` lower-cases only scheme/host.  Never lowercase the
    # entire URL here: paths and signed query parameters may be case-sensitive.
    key = normalized_url
    existing = candidates_by_url.get(key)
    if existing is None:
        normalized["sources"] = [normalized["source"]]
        candidates_by_url[key] = normalized
        return

    existing_sources = list(existing.get("sources") or [existing.get("source")])
    if normalized["source"] not in existing_sources:
        existing_sources.append(normalized["source"])
    existing["sources"] = existing_sources
    if (normalized["priority"], normalized["kind"] != "pdf") < (
        int(existing.get("priority") or 0),
        existing.get("kind") != "pdf",
    ):
        existing.update(
            {
                key: value
                for key, value in normalized.items()
                if value not in (None, "", [], {})
            }
        )
        existing["sources"] = existing_sources


def resolve_fulltext_candidates(
    paper: Mapping[str, Any],
    *,
    unpaywall_api: Any,
    include_all_unpaywall_locations: bool = True,
    include_generic_metadata_urls: bool = True,
    include_doi_landing_fallback: bool = True,
) -> dict[str, Any]:
    """Build ordered, legal OA candidates without fetching PDF bytes.

    Candidate sources are alternative acquisition routes.  They are not a
    conjunctive relevance rule and a failed candidate must never change the
    paper's project/SH semantic assessment.
    """
    paper = paper if isinstance(paper, Mapping) else {}
    doi = _paper_doi(paper, unpaywall_api)
    candidates_by_url: dict[str, dict[str, Any]] = {}
    disabled_candidates: list[dict[str, Any]] = []
    unpaywall_status = "not_requested"
    unpaywall_candidate_count = 0

    if doi and unpaywall_api is not None:
        try:
            get_candidates = getattr(unpaywall_api, "get_oa_candidates", None)
            if callable(get_candidates):
                unpaywall_candidates = list(get_candidates(doi) or [])
            else:
                legacy_url = str(unpaywall_api.get_oa_pdf_url(doi) or "")
                unpaywall_candidates = (
                    [
                        {
                            "url": legacy_url,
                            "kind": "pdf",
                            "source": "unpaywall.legacy_best_pdf",
                            "priority": OA_PRIORITY_UNPAYWALL_BEST,
                        }
                    ]
                    if legacy_url
                    else []
                )
            unpaywall_status = "resolved" if unpaywall_candidates else "no_open_access_location"
            unpaywall_candidate_count = sum(
                1
                for candidate in unpaywall_candidates
                if str(candidate.get("source") or "").startswith("unpaywall.")
            )
            if not include_all_unpaywall_locations:
                unpaywall_candidates = [
                    candidate
                    for candidate in unpaywall_candidates
                    if str(candidate.get("source") or "")
                    in {"unpaywall.best_oa_location", "unpaywall.legacy_best_pdf"}
                ]
            for candidate in unpaywall_candidates:
                if isinstance(candidate, Mapping):
                    _add_candidate(candidates_by_url, candidate)
        except Exception as exc:  # provider failures should not block other OA sources
            unpaywall_status = "lookup_failed"
            unpaywall_error = type(exc).__name__
        else:
            unpaywall_error = ""
    else:
        unpaywall_error = ""

    openalex_locations = paper.get("openalex_oa_locations")
    if isinstance(openalex_locations, Iterable) and not isinstance(
        openalex_locations, (str, bytes, Mapping)
    ):
        for location in openalex_locations:
            if not isinstance(location, Mapping):
                continue
            source = str(location.get("source") or "openalex.oa_locations")
            default_priority = (
                OA_PRIORITY_OPENALEX_BEST
                if source == "openalex.best_oa_location"
                else OA_PRIORITY_OPENALEX_OTHER
            )
            try:
                priority = int(location.get("priority", default_priority) or default_priority)
            except (TypeError, ValueError):
                priority = default_priority
            common = {
                "source": source,
                "priority": priority,
                "version": str(location.get("version") or ""),
                "license": str(location.get("license") or ""),
                "host_type": str(location.get("host_type") or ""),
                "evidence": str(location.get("evidence") or "openalex.oa_location"),
                "oa_evidence": "openalex.oa_location",
            }
            pdf_url = location.get("pdf_url") or location.get("url_for_pdf")
            if pdf_url:
                _add_candidate(
                    candidates_by_url,
                    {**common, "url": pdf_url, "kind": "pdf"},
                )
            landing_url = location.get("landing_page_url") or location.get("url")
            if landing_url and str(landing_url).strip() != str(pdf_url or "").strip():
                _add_candidate(
                    candidates_by_url,
                    {**common, "url": landing_url, "kind": "landing_page"},
                )

    external_ids = _external_ids(paper)
    arxiv_id = str(external_ids.get("ArXiv") or external_ids.get("arXiv") or "").strip()
    if arxiv_id:
        _add_candidate(
            candidates_by_url,
            {
                "url": f"https://arxiv.org/pdf/{arxiv_id}.pdf",
                "kind": "pdf",
                "source": "identifier.arxiv",
                "priority": OA_PRIORITY_IDENTIFIER_REPOSITORY,
                "version": "preprint",
            },
        )
        _add_candidate(
            candidates_by_url,
            {
                "url": f"https://export.arxiv.org/pdf/{arxiv_id}.pdf",
                "kind": "pdf",
                "source": "identifier.arxiv_mirror",
                "priority": OA_PRIORITY_IDENTIFIER_REPOSITORY + 1,
                "version": "preprint",
            },
        )

    pmcid = str(
        paper.get("pmcid")
        or external_ids.get("PMCID")
        or external_ids.get("pmcid")
        or external_ids.get("PMC")
        or ""
    ).strip()
    if pmcid:
        canonical_pmcid = pmcid.upper()
        if not canonical_pmcid.startswith("PMC"):
            canonical_pmcid = f"PMC{canonical_pmcid}"
        _add_candidate(
            candidates_by_url,
            {
                "url": f"https://pmc.ncbi.nlm.nih.gov/articles/{canonical_pmcid}/pdf/",
                "kind": "pdf",
                "source": "identifier.pmc",
                "priority": OA_PRIORITY_IDENTIFIER_REPOSITORY,
                "version": "open_access_repository",
            },
        )

    for key, source in (
        ("repository_pdf", "metadata.repository"),
        ("repository_url", "metadata.repository"),
        ("accepted_manuscript_url", "metadata.accepted_manuscript"),
        ("author_manuscript_url", "metadata.author_manuscript"),
        ("open_repository_url", "metadata.open_repository"),
    ):
        value = paper.get(key)
        url = normalize_http_url(value)
        if not url:
            continue
        _add_candidate(
            candidates_by_url,
            {
                "url": url,
                "kind": "pdf" if urlsplit(url).path.lower().endswith(".pdf") else "landing_page",
                "source": source,
                "priority": OA_PRIORITY_METADATA_REPOSITORY,
            },
        )

    generic_metadata_oa_evidence = _explicit_oa_evidence(paper)
    if include_generic_metadata_urls:
        for field_name, source, route_type, raw_url in _generic_metadata_values(paper):
            url = normalize_http_url(raw_url)
            if not url:
                continue
            path_looks_like_pdf = urlsplit(url).path.lower().endswith(".pdf")
            is_direct_pdf = route_type == "pdf" or (
                route_type == "auto" and path_looks_like_pdf
            )
            if is_direct_pdf:
                _add_candidate(
                    candidates_by_url,
                    {
                        "url": url,
                        "kind": "pdf",
                        "source": source,
                        "priority": OA_PRIORITY_GENERIC_METADATA,
                        "metadata_field": field_name,
                        "oa_evidence": generic_metadata_oa_evidence or "declared_pdf_url",
                    },
                )
                continue
            if generic_metadata_oa_evidence:
                _add_candidate(
                    candidates_by_url,
                    {
                        "url": url,
                        "kind": "landing_page",
                        "source": source,
                        "priority": OA_PRIORITY_GENERIC_METADATA + 1,
                        "metadata_field": field_name,
                        "oa_evidence": generic_metadata_oa_evidence,
                    },
                )
                continue
            # Preserve the reason why a declared URL was not fetched.  It is
            # valuable provenance, and avoids quietly turning generic
            # publisher metadata into an unrestricted landing-page crawler.
            disabled_candidates.append(
                {
                    "url": url,
                    "kind": "landing_page",
                    "source": source,
                    "priority": OA_PRIORITY_GENERIC_METADATA + 1,
                    "metadata_field": field_name,
                    "status": "landing_recovery_requires_explicit_oa",
                }
            )

    open_access_pdf = paper.get("openAccessPdf")
    if isinstance(open_access_pdf, Mapping):
        _add_candidate(
            candidates_by_url,
            {
                "url": open_access_pdf.get("url"),
                "kind": "pdf",
                "source": "provider.open_access_pdf",
                "priority": OA_PRIORITY_PROVIDER_URL,
            },
        )

    # A DOI resolver is a bounded public metadata lookup, not a method for
    # probing subscription routes.  It is scheduled immediately after the
    # Unpaywall routes, then before generic/provider metadata alternatives.
    # It is activated only with a concrete OA declaration: either Unpaywall
    # returned an OA location or incoming metadata explicitly said the work is
    # OA.
    doi_oa_evidence = (
        "unpaywall.oa_location"
        if unpaywall_status == "resolved"
        else generic_metadata_oa_evidence
    )
    if doi and include_doi_landing_fallback and doi_oa_evidence:
        _add_candidate(
            candidates_by_url,
            {
                "url": f"https://doi.org/{quote(doi, safe='/')}",
                "kind": "landing_page",
                "source": "doi.landing_fallback",
                "priority": OA_PRIORITY_DOI_LANDING,
                "doi": doi,
                "oa_evidence": doi_oa_evidence,
            },
        )
    candidates = sorted(
        candidates_by_url.values(),
        key=lambda candidate: (
            int(candidate.get("priority") or 0),
            0 if candidate.get("kind") == "pdf" else 1,
            str(candidate.get("url") or ""),
        ),
    )
    return {
        "schema_version": "fulltext_resolution_v2",
        "paper_id": str(paper.get("paperId") or paper.get("paper_id") or ""),
        "doi": doi,
        "candidates": candidates,
        "deferred_candidates": [],
        "disabled_candidates": disabled_candidates,
        "unpaywall": {
            "status": unpaywall_status,
            "candidate_count": unpaywall_candidate_count,
            **({"error": unpaywall_error} if unpaywall_error else {}),
        },
    }


class _DeclaredPdfLinkParser(HTMLParser):
    """Extract bounded, article-shaped PDF links from an already approved OA page."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.pdf_links: list[str] = []

    def handle_starttag(self, tag: str, attrs: Iterable[tuple[str, str | None]]) -> None:
        attributes = {str(key).lower(): str(value or "") for key, value in attrs}
        tag = tag.lower()
        if tag == "meta":
            meta_name = (
                attributes.get("name", "")
                or attributes.get("property", "")
                or attributes.get("itemprop", "")
            ).lower()
            if meta_name in {
                "citation_pdf_url",
                "eprints.document_url",
                "bepress_citation_pdf_url",
            }:
                self.pdf_links.append(attributes.get("content", ""))
                return
        if tag == "link" and "application/pdf" in attributes.get("type", "").lower():
            self.pdf_links.append(attributes.get("href", ""))
            return
        if tag == "a":
            href = attributes.get("href", "")
            parsed = urlsplit(href)
            # Repository pages often expose a generic PDF anchor.  A
            # supplementary PDF, however, is not a substitute for the article.
            # Keep the fallback conservative and never promote it to full text.
            link_context = " ".join(
                (
                    href,
                    attributes.get("title", ""),
                    attributes.get("aria-label", ""),
                    attributes.get("class", ""),
                )
            ).lower()
            is_supplement = any(
                marker in link_context
                for marker in ("supplement", "supporting-information", "supporting_information")
            )
            is_pdf_path = parsed.path.lower().endswith(".pdf")
            is_pdf_type = "application/pdf" in attributes.get("type", "").lower()
            is_article_download = (
                "download" in attributes
                and any(marker in link_context for marker in ("pdf", "manuscript", "fulltext", "full-text"))
            )
            if not is_supplement and (is_pdf_path or is_pdf_type or is_article_download):
                self.pdf_links.append(href)


def _landing_recovery_permitted(candidate: Mapping[str, Any]) -> bool:
    """Allow recovery only from explicit, lawful OA/repository routes."""

    if str(candidate.get("kind") or "") != "landing_page":
        return False
    source = str(candidate.get("source") or "").casefold()
    # DOI resolution is deliberately more restrictive than a landing page
    # already supplied by Unpaywall: the caller must have retained a concrete
    # OA declaration in the candidate provenance.
    if source == "doi.landing_fallback":
        return bool(str(candidate.get("oa_evidence") or "").strip())
    if source.startswith(("metadata.full_text", "metadata.fulltext", "metadata.landing_page", "metadata.url_for_landing_page")):
        return bool(str(candidate.get("oa_evidence") or "").strip())
    allowed_prefixes = (
        "unpaywall.",
        "identifier.arxiv",
        "identifier.pmc",
        "metadata.repository",
        "metadata.accepted_manuscript",
        "metadata.author_manuscript",
        "metadata.open_repository",
        # OpenAlex has explicitly marked this URL as an OA full-text route.
        "provider.open_access_pdf",
        "openalex.",
    )
    return source.startswith(allowed_prefixes)


def _bounded_landing_get(
    url: str,
    *,
    headers: Mapping[str, str],
    timeout_seconds: float,
    max_redirects: int,
    http_client: Any = None,
) -> tuple[Any | None, dict[str, Any]]:
    """GET a public landing page with an explicit, small redirect budget.

    Requests' default redirect policy is intentionally not used here.  A DOI
    can redirect through several providers; constraining hops keeps a fallback
    from becoming an unbounded route explorer and records the actual terminal
    URL for provenance.
    """
    current_url = url
    redirects = 0
    while True:
        try:
            request_get = http_client.get if http_client is not None else requests.get
            response = request_get(
                current_url,
                headers=dict(headers),
                stream=True,
                timeout=max(1.0, min(float(timeout_seconds), 30.0)),
                allow_redirects=False,
            )
        except requests.Timeout as exc:
            return None, {
                "status": "timeout",
                "http_status": None,
                "final_url": current_url,
                "error": str(exc)[:300],
                "redirect_count": redirects,
            }
        except requests.RequestException as exc:
            return None, {
                "status": "network_error",
                "http_status": None,
                "final_url": current_url,
                "error": str(exc)[:300],
                "redirect_count": redirects,
            }

        status_code = int(getattr(response, "status_code", 0) or 0)
        if status_code not in {301, 302, 303, 307, 308}:
            return response, {
                "status": "response",
                "http_status": status_code,
                "final_url": normalize_http_url(getattr(response, "url", "") or current_url),
                "redirect_count": redirects,
            }

        location = str(getattr(response, "headers", {}).get("Location") or "").strip()
        next_url = normalize_http_url(urljoin(current_url, location)) if location else ""
        response.close()
        if not next_url:
            return None, {
                "status": "redirect_without_location",
                "http_status": status_code,
                "final_url": current_url,
                "redirect_count": redirects,
            }
        if redirects >= max(0, int(max_redirects)):
            return None, {
                "status": "redirect_limit_exceeded",
                "http_status": status_code,
                "final_url": current_url,
                "redirect_count": redirects,
            }
        current_url = next_url
        redirects += 1


def resolve_declared_pdf_links(
    candidate: Mapping[str, Any],
    *,
    timeout_seconds: float = 12.0,
    max_html_bytes: int = 1_500_000,
    max_pdf_links: int = 8,
    max_redirects: int = 3,
    http_client: Any = None,
) -> dict[str, Any]:
    """Resolve one declared OA/repository landing page to bounded PDF links."""
    if not _landing_recovery_permitted(candidate):
        return {"status": "landing_recovery_not_permitted", "pdf_candidates": []}
    url = normalize_http_url(candidate.get("url"))
    if not url:
        return {"status": "invalid_url", "pdf_candidates": []}
    headers = {
        "Accept": "text/html,application/xhtml+xml,application/pdf;q=0.8,*/*;q=0.2",
    }
    if http_client is None:
        headers["User-Agent"] = "Xcientist/0.8 (academic OA full-text resolver)"
    started_at = time.monotonic()
    response, request_result = _bounded_landing_get(
        url,
        headers=headers,
        timeout_seconds=timeout_seconds,
        max_redirects=max_redirects,
        http_client=http_client,
    )
    if response is None:
        return {
            **request_result,
            "elapsed_seconds": round(time.monotonic() - started_at, 3),
            "pdf_candidates": [],
        }

    final_url = str(request_result.get("final_url") or url)
    status_code = int(request_result.get("http_status") or 0)
    content_type = str(getattr(response, "headers", {}).get("Content-Type") or "").lower()
    elapsed_seconds = round(time.monotonic() - started_at, 3)
    if status_code == 404:
        response.close()
        return {
            "status": "not_found",
            "http_status": status_code,
            "final_url": final_url,
            "content_type": content_type,
            "elapsed_seconds": elapsed_seconds,
            "redirect_count": request_result.get("redirect_count", 0),
            "pdf_candidates": [],
        }
    if status_code in {401, 403}:
        response.close()
        return {
            "status": "access_denied",
            "http_status": status_code,
            "final_url": final_url,
            "content_type": content_type,
            "elapsed_seconds": elapsed_seconds,
            "redirect_count": request_result.get("redirect_count", 0),
            "pdf_candidates": [],
        }
    if status_code < 200 or status_code >= 300:
        response.close()
        return {
            "status": "http_error",
            "http_status": status_code,
            "final_url": final_url,
            "content_type": content_type,
            "elapsed_seconds": elapsed_seconds,
            "redirect_count": request_result.get("redirect_count", 0),
            "pdf_candidates": [],
        }

    data = bytearray()
    try:
        for chunk in response.iter_content(chunk_size=64 * 1024):
            if not chunk:
                continue
            data.extend(chunk)
            if len(data) > max_html_bytes:
                return {
                    "status": "landing_page_too_large",
                    "http_status": status_code,
                    "final_url": final_url,
                    "content_type": content_type,
                    "elapsed_seconds": elapsed_seconds,
                    "redirect_count": request_result.get("redirect_count", 0),
                    "pdf_candidates": [],
                }
    finally:
        response.close()

    raw = bytes(data)
    if "application/pdf" in content_type or raw.lstrip().startswith(b"%PDF-"):
        pdf_urls = [final_url]
        status = "resolved_to_pdf"
    else:
        parser = _DeclaredPdfLinkParser()
        parser.feed(raw.decode("utf-8", errors="replace"))
        pdf_urls = []
        seen: set[str] = set()
        for href in parser.pdf_links:
            resolved = normalize_http_url(urljoin(final_url, href))
            if resolved and resolved not in seen:
                seen.add(resolved)
                pdf_urls.append(resolved)
                if len(pdf_urls) >= max_pdf_links:
                    break
        status = "pdf_links_found" if pdf_urls else "no_declared_pdf"

    parent_source = str(candidate.get("source") or "landing_page")
    priority = int(candidate.get("priority") or 0)
    return {
        "status": status,
        "http_status": status_code,
        "final_url": final_url,
        "content_type": content_type,
        "elapsed_seconds": elapsed_seconds,
        "redirect_count": request_result.get("redirect_count", 0),
        "pdf_candidates": [
            {
                "url": pdf_url,
                "kind": "pdf",
                "source": f"{parent_source}.declared_pdf",
                "priority": priority,
                "version": candidate.get("version", ""),
                "license": candidate.get("license", ""),
                "host_type": candidate.get("host_type", ""),
            }
            for pdf_url in pdf_urls
        ],
    }
