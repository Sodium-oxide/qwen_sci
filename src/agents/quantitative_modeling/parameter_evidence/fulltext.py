"""Lawful, bounded acquisition of declared open-access parameter documents."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from src.agents.quantitative_modeling.parameter_contracts import (
    PARAMETER_DISCOVERY_SCHEMA_VERSION,
    model_blueprint_identity,
    normalize_model_blueprint,
)
from src.agents.quantitative_modeling.parameter_evidence.providers import ParameterEvidenceSettings
from src.agents.survey_agent.modules.fulltext_http import FulltextHttpClient


PARAMETER_FULLTEXT_MANIFEST_SCHEMA_VERSION = "quantitative_parameter_fulltext_manifest_v1"


class ParameterFulltextError(RuntimeError):
    """Raised when a declared OA document cannot be safely acquired."""


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _text(value: object) -> str:
    return str(value or "").strip()


def _safe_public_url(value: object) -> str:
    url = _text(value)
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    return url


def _read_response_bytes(response: object, *, maximum: int) -> bytes:
    chunks = getattr(response, "iter_content", None)
    if not callable(chunks):
        content = getattr(response, "content", b"")
        if not isinstance(content, bytes):
            raise ParameterFulltextError("full-text response body must be bytes")
        if len(content) > maximum:
            raise ParameterFulltextError("full-text response exceeds configured maximum size")
        return content
    content = bytearray()
    for chunk in chunks(chunk_size=64 * 1024):
        if not chunk:
            continue
        if not isinstance(chunk, bytes):
            raise ParameterFulltextError("full-text response yielded non-byte content")
        content.extend(chunk)
        if len(content) > maximum:
            raise ParameterFulltextError("full-text response exceeds configured maximum size")
    return bytes(content)


def _verify_discovery(
    discovery: Mapping[str, object], *, blueprint: Mapping[str, object]
) -> dict[str, Any]:
    if _text(discovery.get("schema_version")) != PARAMETER_DISCOVERY_SCHEMA_VERSION:
        raise ParameterFulltextError("unsupported parameter discovery schema")
    normalized_blueprint = normalize_model_blueprint(blueprint)
    if _text(discovery.get("blueprint_identity")) != model_blueprint_identity(normalized_blueprint):
        raise ParameterFulltextError("parameter discovery belongs to a different model blueprint")
    if _mapping(discovery.get("lineage")) != normalized_blueprint["lineage"]:
        raise ParameterFulltextError("parameter discovery lineage differs from model blueprint")
    papers = discovery.get("papers")
    if not isinstance(papers, list):
        raise ParameterFulltextError("parameter discovery papers must be a list")
    return normalized_blueprint


def fetch_open_access_fulltexts(
    *,
    blueprint: Mapping[str, object],
    discovery: Mapping[str, object],
    output_directory: str | Path,
    settings: ParameterEvidenceSettings,
    http_client: FulltextHttpClient | None = None,
) -> dict[str, Any]:
    """Fetch only declared OA PDF URLs into an immutable evidence directory.

    Landing pages, authentication, browser state, subscription access, and HTML
    scraping are intentionally unsupported.  A document is usable only if it
    has a PDF signature or a PDF content type and passes the byte cap.
    """

    normalized_blueprint = _verify_discovery(discovery, blueprint=blueprint)
    root = Path(output_directory).expanduser().resolve()
    if root.exists() and any(root.iterdir()):
        raise ParameterFulltextError("parameter full-text output directory must be empty")
    root.mkdir(parents=True, exist_ok=True)
    client = http_client or FulltextHttpClient(settings, contact_email=settings.unpaywall_email)
    per_request_count: dict[str, int] = {}
    documents: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    seen_urls: set[str] = set()
    for raw_paper in discovery.get("papers") or []:
        paper = _mapping(raw_paper)
        parameter_ids = [_text(item) for item in paper.get("parameter_request_ids") or [] if _text(item)]
        if not parameter_ids:
            continue
        if all(
            per_request_count.get(parameter_id, 0) >= settings.max_fulltext_documents_per_parameter
            for parameter_id in parameter_ids
        ):
            continue
        raw_candidates = list(paper.get("oa_candidates") or [])
        for raw_candidate in raw_candidates[: settings.max_oa_pdf_candidates_per_paper]:
            candidate = _mapping(raw_candidate)
            pdf_url = _safe_public_url(candidate.get("pdf_url"))
            if not pdf_url or pdf_url in seen_urls:
                continue
            seen_urls.add(pdf_url)
            response: object | None = None
            try:
                response = client.get(pdf_url, stream=True, allow_redirects=True)
                if int(getattr(response, "status_code", 0)) not in {200, 206}:
                    raise ParameterFulltextError(f"OA PDF request returned HTTP {getattr(response, 'status_code', 0)}")
                content = _read_response_bytes(response, maximum=settings.fulltext_max_bytes)
                content_type = _text(_mapping(getattr(response, "headers", {})).get("Content-Type")).casefold()
                if not content.startswith(b"%PDF-") and "application/pdf" not in content_type:
                    raise ParameterFulltextError("declared OA URL did not return a PDF document")
                if not content.startswith(b"%PDF-"):
                    raise ParameterFulltextError("declared OA URL did not return a valid PDF signature")
            except Exception as error:
                failures.append(
                    {
                        "paper_id": _text(paper.get("paper_id")),
                        "url": pdf_url,
                        "reason": str(error),
                    }
                )
                continue
            finally:
                close = getattr(response, "close", None)
                if callable(close):
                    close()
            document_id = f"PFD-{len(documents) + 1:03d}"
            path = root / f"{document_id}.pdf"
            path.write_bytes(content)
            for parameter_id in parameter_ids:
                per_request_count[parameter_id] = per_request_count.get(parameter_id, 0) + 1
            documents.append(
                {
                    "document_id": document_id,
                    "path": str(path),
                    "sha256": hashlib.sha256(content).hexdigest(),
                    "title": _text(paper.get("title")),
                    "doi": _text(paper.get("doi")),
                    "year": paper.get("year"),
                    "discovery_sources": list(paper.get("discovery_sources") or []),
                    "cross_validated": bool(paper.get("cross_validated", False)),
                    "parameter_request_ids": parameter_ids,
                    "evidence_status": "EXTRACTED_FULLTEXT",
                    "retrieval_source": _text(candidate.get("source")),
                    "source_url": pdf_url,
                }
            )
            break
    return {
        "schema_version": PARAMETER_FULLTEXT_MANIFEST_SCHEMA_VERSION,
        "blueprint_identity": model_blueprint_identity(normalized_blueprint),
        "lineage": normalized_blueprint["lineage"],
        "documents": documents,
        "failures": failures,
        "access_boundary": "Only public OA PDF URLs declared by discovery providers are retrieved.",
    }


__all__ = [
    "PARAMETER_FULLTEXT_MANIFEST_SCHEMA_VERSION",
    "ParameterFulltextError",
    "fetch_open_access_fulltexts",
]
