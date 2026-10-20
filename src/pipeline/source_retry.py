"""Source-level retry decisions shared by readers and acquisition scheduling."""
from __future__ import annotations

from collections.abc import Mapping
import hashlib
import json

from .anysearch import normalize_doi, source_identifiers


SOURCE_READER_REVISION = 2


def source_route_fingerprint(paper):
    fields = ("url", "openAccessPdf", "oa_locations", "openalex_oa_locations", "access_urls",
              "repository_url", "repository_pdf", "accepted_manuscript_url", "author_manuscript_url",
              "open_repository_url", "fulltext_url", "full_text_url", "pdf_url", "version", "abstract")
    identity = source_identifiers(paper)
    identity["doi"] = normalize_doi(paper.get("doi") or (paper.get("externalIds") or {}).get("DOI"))
    payload = {"revision": SOURCE_READER_REVISION, "identity": identity, "source_type": paper.get("source_type") or "paper",
               "routes": {key: paper[key] for key in fields if paper.get(key)}}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


def source_access_context(manager):
    coordinator = getattr(manager, "fulltext_download_coordinator", None)
    value = getattr(coordinator, "access_context_generation", "anonymous-v1")
    return value if isinstance(value, str) else "anonymous-v1"


def source_retry_allowed(paper, reference, access_context="anonymous-v1"):
    retry = reference.get("retry", {}) if isinstance(reference, Mapping) else {}
    if retry.get("policy") != "when_source_changes":
        return True
    return (retry.get("route_fingerprint") != source_route_fingerprint(paper)
            or retry.get("access_context_generation") != access_context
            or retry.get("reader_revision") != SOURCE_READER_REVISION)
