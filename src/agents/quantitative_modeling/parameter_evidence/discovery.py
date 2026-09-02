"""Build provenance-rich literature discovery records for parameter requests."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from src.agents.quantitative_modeling.parameter_contracts import (
    PARAMETER_DISCOVERY_SCHEMA_VERSION,
    build_parameter_query_plan,
    model_blueprint_identity,
    normalize_model_blueprint,
)
from src.agents.quantitative_modeling.parameter_evidence.providers import (
    AcademicMetadataProviders,
    ParameterEvidenceProviderError,
)


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _text(value: object) -> str:
    return str(value or "").strip()


def _year(value: object) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        result = int(value)
    except (TypeError, ValueError):
        return None
    return result if result > 0 else None


def _paper_key(record: Mapping[str, object]) -> str:
    doi = _text(record.get("doi")).casefold()
    if doi:
        return f"doi:{doi}"
    provider = _text(record.get("provider"))
    provider_paper_id = _text(record.get("provider_paper_id"))
    if provider and provider_paper_id:
        return f"{provider}:{provider_paper_id}"
    return f"title:{_text(record.get('title')).casefold()}"


def _merge_paper(
    papers: dict[str, dict[str, Any]],
    *,
    record: Mapping[str, object],
    parameter_id: str,
    query: str,
) -> None:
    key = _paper_key(record)
    title = _text(record.get("title"))
    if not title:
        return
    provider = _text(record.get("provider"))
    existing = papers.get(key)
    if existing is None:
        existing = {
            "paper_id": f"PD-{len(papers) + 1:03d}",
            "title": title,
            "doi": _text(record.get("doi")),
            "year": _year(record.get("year")),
            "provider_records": [],
            "parameter_request_ids": [],
            "queries": [],
            "oa_candidates": [],
        }
        papers[key] = existing
    provider_record = {
        "provider": provider,
        "provider_paper_id": _text(record.get("provider_paper_id")),
    }
    if provider_record not in existing["provider_records"]:
        existing["provider_records"].append(provider_record)
    if parameter_id not in existing["parameter_request_ids"]:
        existing["parameter_request_ids"].append(parameter_id)
    if query not in existing["queries"]:
        existing["queries"].append(query)
    for raw_candidate in record.get("oa_locations") or []:
        candidate = _mapping(raw_candidate)
        normalized = {
            "source": _text(candidate.get("source")),
            "pdf_url": _text(candidate.get("pdf_url")),
            "landing_url": _text(candidate.get("landing_url")),
        }
        if normalized["pdf_url"] or normalized["landing_url"]:
            if normalized not in existing["oa_candidates"]:
                existing["oa_candidates"].append(normalized)


def discover_parameter_literature(
    *,
    blueprint: Mapping[str, object],
    providers: AcademicMetadataProviders,
) -> dict[str, Any]:
    """Discover papers and OA locations without treating metadata as evidence.

    Individual provider failures are recorded so an unavailable optional index
    cannot erase successful discoveries from other providers.
    """

    normalized_blueprint = normalize_model_blueprint(blueprint)
    if not providers.settings.enabled:
        raise ParameterEvidenceProviderError("quantitative parameter evidence is disabled by configuration")
    query_plan = build_parameter_query_plan(blueprint=normalized_blueprint)
    papers: dict[str, dict[str, Any]] = {}
    provider_runs: list[dict[str, Any]] = []
    for request in query_plan["requests"]:
        parameter_id = request["parameter_id"]
        for query in request["queries"]:
            available_searches = (
                ("openalex", providers.search_openalex),
                ("semantic_scholar", providers.search_semantic_scholar),
            )
            for provider_name, search in available_searches:
                if provider_name not in providers.settings.discovery_providers:
                    continue
                try:
                    records = search(query)
                except ParameterEvidenceProviderError as error:
                    provider_runs.append(
                        {
                            "provider": provider_name,
                            "parameter_id": parameter_id,
                            "query": query,
                            "status": "FAILED",
                            "error": str(error),
                            "record_count": 0,
                        }
                    )
                    continue
                for record in records:
                    _merge_paper(papers, record=record, parameter_id=parameter_id, query=query)
                provider_runs.append(
                    {
                        "provider": provider_name,
                        "parameter_id": parameter_id,
                        "query": query,
                        "status": "COMPLETED" if records else "NO_RESULTS",
                        "record_count": len(records),
                    }
                )
    for paper in papers.values():
        doi = _text(paper.get("doi"))
        if not doi:
            continue
        if "unpaywall" not in providers.settings.discovery_providers:
            paper["unpaywall_status"] = "DISABLED"
            continue
        try:
            locations = providers.resolve_unpaywall(doi)
        except ParameterEvidenceProviderError as error:
            paper["unpaywall_status"] = "FAILED"
            paper["unpaywall_error"] = str(error)
            continue
        for location in locations:
            if location not in paper["oa_candidates"]:
                paper["oa_candidates"].append(location)
        paper["unpaywall_status"] = "RESOLVED" if locations else "NO_OPEN_ACCESS_LOCATION"
    merged_papers: list[dict[str, Any]] = []
    for paper in papers.values():
        providers_seen = sorted(
            {record["provider"] for record in paper["provider_records"] if record.get("provider")}
        )
        merged_papers.append(
            {
                **paper,
                "discovery_sources": providers_seen,
                "cross_validated": len(providers_seen) >= 2,
            }
        )
    return {
        "schema_version": PARAMETER_DISCOVERY_SCHEMA_VERSION,
        "blueprint_identity": model_blueprint_identity(normalized_blueprint),
        "lineage": normalized_blueprint["lineage"],
        "query_plan": query_plan,
        "provider_runs": provider_runs,
        "papers": merged_papers,
        "evidence_boundary": (
            "Discovery metadata and abstracts are not parameter evidence. A numerical value requires a legal full-text "
            "or user-provided document with a quoted source locator."
        ),
    }


__all__ = ["discover_parameter_literature"]
