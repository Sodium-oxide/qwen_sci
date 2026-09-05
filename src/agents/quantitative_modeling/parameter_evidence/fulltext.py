"""Lawful, bounded acquisition of declared open-access parameter documents."""

from __future__ import annotations

import hashlib
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
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
    try:
        per_host_limit = max(1, int(getattr(settings, "fulltext_per_host_concurrency", 2) or 2))
    except (TypeError, ValueError):
        per_host_limit = 2
    host_semaphores: dict[str, threading.BoundedSemaphore] = {}
    host_semaphore_lock = threading.Lock()

    def host_semaphore(url: str) -> threading.BoundedSemaphore:
        host = urlparse(url).netloc.casefold() or "unknown"
        with host_semaphore_lock:
            semaphore = host_semaphores.get(host)
            if semaphore is None:
                semaphore = threading.BoundedSemaphore(per_host_limit)
                host_semaphores[host] = semaphore
            return semaphore

    tasks: list[tuple[int, dict[str, Any], list[dict[str, str]], list[str]]] = []
    deferred_tasks: list[tuple[int, dict[str, Any], list[dict[str, str]], list[str]]] = []
    reserved_counts: dict[str, int] = {}
    for raw_paper in discovery.get("papers") or []:
        paper = _mapping(raw_paper)
        parameter_ids = [_text(item) for item in paper.get("parameter_request_ids") or [] if _text(item)]
        if not parameter_ids:
            continue
        raw_candidates = list(paper.get("oa_candidates") or [])
        candidates: list[dict[str, str]] = []
        for raw_candidate in raw_candidates[: settings.max_oa_pdf_candidates_per_paper]:
            candidate = _mapping(raw_candidate)
            pdf_url = _safe_public_url(candidate.get("pdf_url"))
            if not pdf_url or pdf_url in seen_urls:
                continue
            seen_urls.add(pdf_url)
            candidates.append({"url": pdf_url, "source": _text(candidate.get("source"))})
        if not candidates:
            continue
        eligible_parameters = [
            parameter_id
            for parameter_id in parameter_ids
            if reserved_counts.get(parameter_id, 0) < settings.max_fulltext_documents_per_parameter
        ]
        task = (len(tasks) + len(deferred_tasks), paper, candidates, eligible_parameters or parameter_ids)
        if eligible_parameters:
            for parameter_id in eligible_parameters:
                reserved_counts[parameter_id] = reserved_counts.get(parameter_id, 0) + 1
            tasks.append(task)
        else:
            deferred_tasks.append(task)

    def fetch_one(task: tuple[int, dict[str, Any], list[dict[str, str]], list[str]]) -> dict[str, Any]:
        task_index, paper, candidates, parameter_ids = task
        local_failures: list[dict[str, str]] = []
        for candidate in candidates:
            pdf_url = candidate["url"]
            response: object | None = None
            semaphore = host_semaphore(pdf_url)
            semaphore.acquire()
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
                return {
                    "task_index": task_index,
                    "paper": paper,
                    "parameter_ids": parameter_ids,
                    "content": content,
                    "url": pdf_url,
                    "source": candidate["source"],
                    "failures": local_failures,
                }
            except Exception as error:
                local_failures.append(
                    {"paper_id": _text(paper.get("paper_id")), "url": pdf_url, "reason": str(error)}
                )
            finally:
                close = getattr(response, "close", None)
                if callable(close):
                    close()
                semaphore.release()
        return {"task_index": task_index, "failures": local_failures}

    worker_count = max(1, min(int(getattr(settings, "fulltext_workers", 4) or 4), len(tasks) or 1))
    successful_results: list[dict[str, Any]] = []
    pending = tasks
    fallback = deferred_tasks
    while pending:
        fetched: list[dict[str, Any]] = []
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            future_map = {executor.submit(fetch_one, task): task[0] for task in pending}
            for future in as_completed(future_map):
                fetched.append(dict(future.result()))
        for result in sorted(fetched, key=lambda item: int(item.get("task_index", 0))):
            failures.extend(list(result.get("failures") or []))
            parameter_ids = [_text(item) for item in result.get("parameter_ids") or [] if _text(item)]
            for parameter_id in parameter_ids:
                reserved_counts[parameter_id] = max(0, reserved_counts.get(parameter_id, 0) - 1)
            content = result.get("content")
            if not isinstance(content, bytes):
                continue
            successful_results.append(result)
            for parameter_id in parameter_ids:
                per_request_count[parameter_id] = per_request_count.get(parameter_id, 0) + 1
        pending = []
        remaining_fallback: list[tuple[int, dict[str, Any], list[dict[str, str]], list[str]]] = []
        for task in fallback:
            eligible_parameters = [
                parameter_id
                for parameter_id in task[3]
                if (
                    per_request_count.get(parameter_id, 0) + reserved_counts.get(parameter_id, 0)
                    < settings.max_fulltext_documents_per_parameter
                )
            ]
            if eligible_parameters:
                for parameter_id in eligible_parameters:
                    reserved_counts[parameter_id] = reserved_counts.get(parameter_id, 0) + 1
                pending.append((task[0], task[1], task[2], eligible_parameters))
            else:
                remaining_fallback.append(task)
        fallback = remaining_fallback
    for result in sorted(successful_results, key=lambda item: int(item.get("task_index", 0))):
        content = result["content"]
        paper = _mapping(result.get("paper"))
        parameter_ids = [_text(item) for item in result.get("parameter_ids") or [] if _text(item)]
        if not parameter_ids:
            continue
        document_id = f"PFD-{len(documents) + 1:03d}"
        path = root / f"{document_id}.pdf"
        path.write_bytes(content)
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
                "retrieval_source": _text(result.get("source")),
                "source_url": _text(result.get("url")),
            }
        )
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
