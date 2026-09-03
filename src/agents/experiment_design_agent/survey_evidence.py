"""Survey-style retrieval, full-text acquisition, and traceable evidence adaptation."""

from __future__ import annotations

from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor, as_completed
import re
from collections.abc import Callable, Mapping, Sequence
from typing import Any

import requests

from src.pipeline.paper_identity import canonical_paper_id

from .cache import ExperimentDesignCache, content_digest, text_digest
from .design_evidence_paper_screener import (
    DESIGN_EVIDENCE_PAPER_SCREENER_PROMPT,
    DesignEvidencePaperScreener,
)
from .evidence_cards import (
    EVIDENCE_CARD_EXTRACTOR_PROMPT,
    EvidenceCardExtractor,
    build_traceable_evidence_bundle,
)
from .fulltext_acquisition import SurveyCompatibleFulltextAcquirer


SURVEY_EVIDENCE_COLLECTION_SCHEMA_VERSION = "experiment_design_survey_evidence_collection_v1"
SURVEY_EVIDENCE_ADAPTATION_SCHEMA_VERSION = "experiment_design_survey_evidence_adaptation_v1"
SURVEY_EVIDENCE_COLLECTION_CACHE_VERSION = "experiment_design_survey_evidence_cache_v1"
DEFAULT_MAX_SCREENING_CANDIDATES = 18
DEFAULT_EVIDENCE_CARD_PARALLEL_WORKERS = 3


class ProviderUnavailable(RuntimeError):
    """Signal an unavailable discovery provider that may trigger its configured fallback."""


class ProviderQueryError(RuntimeError):
    """Signal a query or authorization error that must not silently broaden retrieval."""


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _setting(value: object, key: str, default: object = "") -> object:
    if isinstance(value, Mapping):
        return value.get(key, default)
    return getattr(value, key, default)


def _cache_config(config: object | None) -> object:
    experiment_design = _setting(config, "experiment_design", config)
    retrieval = _setting(experiment_design, "retrieval", {})
    return _setting(retrieval, "cache", {"enabled": False})


def _llm_cache_context(config: object | None) -> dict[str, str]:
    experiment_design = _setting(config, "experiment_design", config)
    return {
        "provider": _text(_setting(experiment_design, "provider", ""), limit=160),
        "model": _text(_setting(experiment_design, "model", ""), limit=160),
    }


def _text(value: object, *, limit: int = 1200) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def _provider_endpoint(client: object, suffix: str) -> str:
    base_url = _text(getattr(client, "base_url", ""), limit=2000).rstrip("/")
    return f"{base_url}{suffix}" if base_url else ""


def _paper_log_records(papers: Sequence[Mapping[str, Any]], *, limit: int = 50) -> list[dict[str, Any]]:
    """Return traceable result metadata without logging abstracts or full text."""

    records: list[dict[str, Any]] = []
    for paper in papers[: max(0, limit)]:
        records.append(
            {
                "canonical_paper_id": _text(paper.get("canonical_paper_id"), limit=200),
                "title": _text(paper.get("title"), limit=500),
                "doi": _text(paper.get("doi"), limit=300),
                "year": _text(paper.get("year"), limit=20),
                "content_availability": _text(paper.get("content_availability"), limit=40),
                "fulltext_candidate_count": len(paper.get("fulltext_candidates") or []),
            }
        )
    return records


def _emit_retrieval_log(
    logger: Any | None,
    event: str,
    *,
    level: str = "INFO",
    status: str,
    **fields: object,
) -> None:
    if logger is not None:
        logger.event("evidence_retrieval", event, level=level, status=status, **fields)


def _texts(value: object, *, limit: int = 100) -> list[str]:
    values = value if isinstance(value, Sequence) and not isinstance(value, (str, bytes)) else [value]
    output: list[str] = []
    for value in values:
        item = _text(value, limit=600)
        if item and item not in output:
            output.append(item)
        if len(output) >= limit:
            break
    return output


def _normalize_doi(value: object) -> str:
    doi = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", _text(value, limit=500), flags=re.IGNORECASE)
    return doi.rstrip("/.,;:").casefold()


def _title_key(title: object, year: object) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "", _text(title, limit=1200).casefold())
    return f"title:{normalized}:{_text(year, limit=12)}" if normalized else ""


def _reconstruct_abstract(value: object) -> str:
    if isinstance(value, str):
        return _text(value, limit=100000)
    inverted = _mapping(value)
    if not inverted:
        return ""
    positions: list[tuple[int, str]] = []
    for term, raw_positions in inverted.items():
        for position in raw_positions if isinstance(raw_positions, list) else []:
            if isinstance(position, int):
                positions.append((position, str(term)))
    return " ".join(term for _, term in sorted(positions))


def _author_names(value: object) -> list[str]:
    records = value if isinstance(value, Sequence) and not isinstance(value, (str, bytes)) else [value]
    names: list[str] = []
    for record in records:
        item = _mapping(record)
        author = _mapping(item.get("author"))
        name = _text(
            item.get("display_name")
            or item.get("name")
            or author.get("display_name")
            or author.get("name")
            or (record if isinstance(record, str) else ""),
            limit=500,
        )
        if name and name not in names:
            names.append(name)
    return names


def _bibliographic_url(*values: object) -> str:
    for value in values:
        text = _text(value, limit=2000)
        if not text:
            continue
        if text.startswith(("https://", "http://")):
            if re.match(r"^https?://(?:dx\.)?doi\.org/", text, flags=re.IGNORECASE):
                normalized_doi = _normalize_doi(text)
                return f"https://doi.org/{normalized_doi}" if normalized_doi else ""
            return text
        normalized_doi = _normalize_doi(text)
        if normalized_doi and "/" in normalized_doi:
            return f"https://doi.org/{normalized_doi}"
    return ""


def _openalex_venue(work: Mapping[str, Any]) -> str:
    primary_location = _mapping(work.get("primary_location"))
    source = _mapping(primary_location.get("source"))
    host_venue = _mapping(work.get("host_venue"))
    return _text(source.get("display_name") or host_venue.get("display_name"), limit=1000)


def _semantic_venue(work: Mapping[str, Any]) -> str:
    publication_venue = _mapping(work.get("publicationVenue"))
    return _text(work.get("venue") or publication_venue.get("name"), limit=1000)


def _content_rank(value: object) -> int:
    return {"unavailable": 0, "metadata": 1, "abstract": 2, "user_supplied": 3, "fulltext": 4}.get(
        _text(value, limit=40),
        0,
    )


def _canonical_identifier(*, openalex_id: object = "", doi: object = "", semantic_id: object = "") -> str:
    openalex = canonical_paper_id(openalex_id)
    if re.fullmatch(r"W\d+", openalex, flags=re.IGNORECASE):
        return openalex
    normalized_doi = _normalize_doi(doi)
    if normalized_doi:
        return f"doi:{normalized_doi}"
    semantic = _text(semantic_id, limit=200)
    return f"S2:{semantic}" if semantic else ""


def _openalex_locations(work: Mapping[str, Any]) -> list[dict[str, str]]:
    open_access = _mapping(work.get("open_access"))
    locations = [_mapping(work.get("best_oa_location"))]
    locations.extend(_mapping(item) for item in work.get("locations") or [] if isinstance(item, Mapping))
    candidates: list[dict[str, str]] = []
    for index, location in enumerate(locations, start=1):
        if not location:
            continue
        is_oa = bool(location.get("is_oa")) or bool(open_access.get("is_oa"))
        if not is_oa:
            continue
        pdf_url = _text(location.get("pdf_url"), limit=2000)
        landing_url = _text(location.get("landing_page_url"), limit=2000)
        source = "openalex.best_oa_location" if index == 1 else "openalex.oa_location"
        for kind, url in (("pdf", pdf_url), ("landing", landing_url)):
            if url and not any(existing["url"] == url for existing in candidates):
                candidates.append({"kind": kind, "url": url, "source": source})
    return candidates


def _normalize_openalex_work(work: Mapping[str, Any], task_id: str, slot: str = "") -> dict[str, Any]:
    ids = _mapping(work.get("ids"))
    openalex_id = _text(work.get("id") or ids.get("openalex"), limit=300)
    doi = _normalize_doi(work.get("doi") or ids.get("doi"))
    canonical_id = _canonical_identifier(openalex_id=openalex_id, doi=doi)
    abstract = _reconstruct_abstract(work.get("abstract_inverted_index") or work.get("abstract"))
    authors = _author_names(work.get("authorships"))
    venue = _openalex_venue(work)
    url = _bibliographic_url(work.get("doi"), _mapping(work.get("primary_location")).get("landing_page_url"))
    return {
        "canonical_paper_id": canonical_id,
        "title": _text(work.get("title"), limit=1200),
        "doi": doi,
        "year": work.get("publication_year") or work.get("year") or "",
        **({"authors": authors} if authors else {}),
        **({"venue": venue} if venue else {}),
        **({"url": url} if url else {}),
        "provider_ids": {"openalex": openalex_id or canonical_id, **({"doi": doi} if doi else {})},
        "providers": ["openalex"],
        "query_task_ids": [task_id],
        "query_slots": [slot] if slot else [],
        "abstract": abstract,
        "abstract_source_location": "abstract:openalex",
        "fulltext_candidates": _openalex_locations(work),
        "fulltext_source_location": "",
        "content_availability": "abstract" if abstract else "metadata",
    }


def _normalize_semantic_work(work: Mapping[str, Any], task_id: str, slot: str = "") -> dict[str, Any]:
    external_ids = _mapping(work.get("externalIds"))
    semantic_id = _text(work.get("paperId") or work.get("paper_id"), limit=300)
    openalex_id = _text(external_ids.get("OpenAlex") or external_ids.get("openalex"), limit=300)
    doi = _normalize_doi(external_ids.get("DOI") or external_ids.get("doi") or work.get("doi"))
    canonical_id = _canonical_identifier(openalex_id=openalex_id, doi=doi, semantic_id=semantic_id)
    open_pdf = _mapping(work.get("openAccessPdf"))
    pdf_url = _text(open_pdf.get("url"), limit=2000)
    candidates = [{"kind": "pdf", "url": pdf_url, "source": "semantic_scholar.open_access_pdf"}] if pdf_url else []
    authors = _author_names(work.get("authors"))
    venue = _semantic_venue(work)
    url = _bibliographic_url(doi, work.get("url"))
    return {
        "canonical_paper_id": canonical_id,
        "title": _text(work.get("title"), limit=1200),
        "doi": doi,
        "year": work.get("year") or "",
        **({"authors": authors} if authors else {}),
        **({"venue": venue} if venue else {}),
        **({"url": url} if url else {}),
        "provider_ids": {"semantic_scholar": semantic_id or canonical_id, **({"openalex": openalex_id} if openalex_id else {}), **({"doi": doi} if doi else {})},
        "providers": ["semantic_scholar"],
        "query_task_ids": [task_id],
        "query_slots": [slot] if slot else [],
        "abstract": _text(work.get("abstract"), limit=100000),
        "abstract_source_location": "abstract:semantic_scholar",
        "fulltext_candidates": candidates,
        "fulltext_source_location": "",
        "content_availability": "abstract" if _text(work.get("abstract"), limit=10) else "metadata",
    }


class OpenAlexWorksClient:
    """Direct OpenAlex Works client without a hard discipline filter."""

    def __init__(
        self,
        *,
        api_key: str = "",
        email: str = "",
        session: requests.Session | None = None,
        timeout_seconds: float = 30.0,
        base_url: str = "https://api.openalex.org",
    ) -> None:
        self.api_key = _text(api_key, limit=300)
        self.email = _text(email, limit=300)
        self.session = session or requests.Session()
        self.timeout_seconds = max(1.0, float(timeout_seconds))
        self.base_url = base_url.rstrip("/")

    def search(self, query_task: Mapping[str, Any], *, limit: int) -> list[dict[str, Any]]:
        task = _mapping(query_task)
        params: dict[str, Any] = {
            "search": _text(task.get("query"), limit=2000),
            "per-page": max(1, min(200, int(limit))),
        }
        if self.api_key:
            params["api_key"] = self.api_key
        if self.email:
            params["mailto"] = self.email
        try:
            response = self.session.get(f"{self.base_url}/works", params=params, timeout=self.timeout_seconds)
        except requests.RequestException as exc:
            raise ProviderUnavailable("OpenAlex request failed") from exc
        if response.status_code in {408, 425, 429} or response.status_code >= 500:
            raise ProviderUnavailable(f"OpenAlex unavailable: HTTP {response.status_code}")
        if response.status_code != 200:
            raise ProviderQueryError(f"OpenAlex rejected query: HTTP {response.status_code}")
        payload = _mapping(response.json())
        task_id = _text(task.get("task_id"), limit=120)
        slot = _text(task.get("slot"), limit=120)
        return [
            _normalize_openalex_work(work, task_id, slot)
            for work in payload.get("results") or []
            if isinstance(work, Mapping)
        ]


class SemanticScholarWorksClient:
    """Semantic Scholar fallback client without pretending to apply OpenAlex fields."""

    def __init__(
        self,
        *,
        api_key: str = "",
        session: requests.Session | None = None,
        timeout_seconds: float = 30.0,
        base_url: str = "https://api.semanticscholar.org/graph/v1",
    ) -> None:
        self.api_key = _text(api_key, limit=300)
        self.session = session or requests.Session()
        self.timeout_seconds = max(1.0, float(timeout_seconds))
        self.base_url = base_url.rstrip("/")

    def search(self, query_task: Mapping[str, Any], *, limit: int) -> list[dict[str, Any]]:
        task = _mapping(query_task)
        headers = {"x-api-key": self.api_key} if self.api_key else {}
        params = {
            "query": _text(task.get("query"), limit=2000),
            "limit": max(1, min(100, int(limit))),
            "fields": "paperId,title,abstract,year,authors,venue,publicationVenue,url,externalIds,openAccessPdf",
        }
        try:
            response = self.session.get(f"{self.base_url}/paper/search", params=params, headers=headers, timeout=self.timeout_seconds)
        except requests.RequestException as exc:
            raise ProviderUnavailable("Semantic Scholar request failed") from exc
        if response.status_code in {408, 425, 429} or response.status_code >= 500:
            raise ProviderUnavailable(f"Semantic Scholar unavailable: HTTP {response.status_code}")
        if response.status_code != 200:
            raise ProviderQueryError(f"Semantic Scholar rejected query: HTTP {response.status_code}")
        payload = _mapping(response.json())
        task_id = _text(task.get("task_id"), limit=120)
        slot = _text(task.get("slot"), limit=120)
        return [
            _normalize_semantic_work(work, task_id, slot)
            for work in payload.get("data") or []
            if isinstance(work, Mapping)
        ]


class SurveyArtifactAdapter:
    """Apply already-collected Survey fulltext and keynote artifacts to candidate papers."""

    def enrich(
        self,
        papers: Sequence[Mapping[str, Any]],
        survey_artifacts: Mapping[str, Any] | Sequence[Mapping[str, Any]] | None,
    ) -> list[dict[str, Any]]:
        if not survey_artifacts:
            return [deepcopy(_mapping(paper)) for paper in papers]
        raw_records: object = survey_artifacts
        if isinstance(survey_artifacts, Mapping):
            raw_records = survey_artifacts.get("papers") or survey_artifacts.get("paper_registry") or survey_artifacts
        artifact_index: dict[str, dict[str, Any]] = {}
        if isinstance(raw_records, Mapping):
            iterable = [
                {"canonical_paper_id": identifier, **_mapping(value)}
                for identifier, value in raw_records.items()
                if isinstance(value, Mapping)
            ]
        else:
            iterable = raw_records if isinstance(raw_records, Sequence) and not isinstance(raw_records, (str, bytes)) else []
        for raw in iterable:
            artifact = _mapping(raw)
            identifiers = [
                artifact.get("canonical_paper_id"),
                artifact.get("paper_id"),
                artifact.get("openalex_id"),
                _mapping(artifact.get("provider_ids")).get("openalex"),
            ]
            for identifier in identifiers:
                canonical = canonical_paper_id(identifier)
                if canonical:
                    artifact_index[canonical] = artifact
        enriched: list[dict[str, Any]] = []
        for raw_paper in papers:
            paper = deepcopy(_mapping(raw_paper))
            artifact = artifact_index.get(_text(paper.get("canonical_paper_id"), limit=160), {})
            fulltext = _text(artifact.get("fulltext") or artifact.get("full_text") or artifact.get("content"), limit=100000)
            abstract = _text(artifact.get("abstract"), limit=100000)
            if fulltext:
                paper["fulltext"] = fulltext
                paper["fulltext_source_location"] = _text(artifact.get("source_location"), limit=300) or "fulltext:survey_artifact"
                paper["content_availability"] = "fulltext"
            elif abstract and not _text(paper.get("abstract"), limit=100):
                paper["abstract"] = abstract
                paper["abstract_source_location"] = _text(artifact.get("source_location"), limit=300) or "abstract:survey_artifact"
                paper["content_availability"] = "abstract"
            if _text(artifact.get("keynote"), limit=100000):
                paper["survey_keynote"] = _text(artifact.get("keynote"), limit=100000)
            enriched.append(paper)
        return enriched


def _identity_keys(paper: Mapping[str, Any]) -> set[str]:
    provider_ids = _mapping(paper.get("provider_ids"))
    keys = {
        f"canonical:{_text(paper.get('canonical_paper_id'), limit=200)}",
        f"doi:{_normalize_doi(paper.get('doi') or provider_ids.get('doi'))}",
        _title_key(paper.get("title"), paper.get("year")),
    }
    return {key for key in keys if key and not key.endswith(":")}


def _merge_papers(papers: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    ordered = sorted(
        (_mapping(paper) for paper in papers),
        key=lambda paper: ("openalex" not in _texts(paper.get("providers")), _text(paper.get("canonical_paper_id"), limit=200)),
    )
    merged: list[dict[str, Any]] = []
    index: dict[str, int] = {}
    for incoming in ordered:
        matching_indexes = {index[key] for key in _identity_keys(incoming) if key in index}
        if not matching_indexes:
            record = deepcopy(incoming)
            merged.append(record)
            target_index = len(merged) - 1
        else:
            target_index = min(matching_indexes)
            record = merged[target_index]
            incoming_id = _text(incoming.get("canonical_paper_id"), limit=200)
            if re.fullmatch(r"W\d+", incoming_id, flags=re.IGNORECASE):
                record["canonical_paper_id"] = incoming_id
            for key in (
                "title",
                "doi",
                "year",
                "venue",
                "url",
                "abstract",
                "abstract_source_location",
                "fulltext",
                "fulltext_source_location",
                "survey_keynote",
            ):
                if not _text(record.get(key), limit=100) and _text(incoming.get(key), limit=100):
                    record[key] = incoming[key]
            if not _author_names(record.get("authors")) and _author_names(incoming.get("authors")):
                record["authors"] = _author_names(incoming.get("authors"))
            if _content_rank(incoming.get("content_availability")) > _content_rank(record.get("content_availability")):
                record["content_availability"] = incoming.get("content_availability")
            provider_ids = _mapping(record.get("provider_ids"))
            provider_ids.update(_mapping(incoming.get("provider_ids")))
            record["provider_ids"] = provider_ids
            record["providers"] = _texts([*record.get("providers", []), *incoming.get("providers", [])], limit=12)
            record["query_task_ids"] = _texts([*record.get("query_task_ids", []), *incoming.get("query_task_ids", [])], limit=200)
            record["query_slots"] = _texts([*record.get("query_slots", []), *incoming.get("query_slots", [])], limit=32)
            candidates = list(record.get("fulltext_candidates") or [])
            for candidate in incoming.get("fulltext_candidates") or []:
                normalized = _mapping(candidate)
                if normalized and not any(item.get("url") == normalized.get("url") for item in candidates if isinstance(item, Mapping)):
                    candidates.append(normalized)
            record["fulltext_candidates"] = candidates
        for key in _identity_keys(record):
            index[key] = target_index
    return merged


def _candidate_priority(paper: Mapping[str, Any]) -> tuple[int, int, int, str]:
    """Rank pre-screening records using only discovery metadata.

    This is deliberately not an evidence or relevance assessment.  It only
    bounds the required LLM screening work while preserving papers that match
    more design slots, provide an abstract, or already have traceable text.
    """

    slot_count = len(_texts(paper.get("query_slots"), limit=32))
    content_rank = _content_rank(paper.get("content_availability"))
    fulltext_candidate_count = len(paper.get("fulltext_candidates") or [])
    return (
        -slot_count,
        -content_rank,
        -min(fulltext_candidate_count, 20),
        _text(paper.get("canonical_paper_id"), limit=200),
    )


def _bound_screening_candidates(
    papers: Sequence[Mapping[str, Any]],
    *,
    maximum: int,
    planned_slots: Sequence[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, str]]:
    """Keep an explicit bounded candidate set before expensive LLM screening."""

    ordered = sorted((_mapping(paper) for paper in papers), key=_candidate_priority)
    limit = max(0, int(maximum))
    if len(ordered) <= limit:
        return ordered, [], {}
    selected: list[dict[str, Any]] = []
    selected_ids: set[str] = set()
    selected_by_slot: dict[str, str] = {}
    for slot in _texts(planned_slots, limit=32):
        if len(selected) >= limit:
            break
        candidate = next(
            (paper for paper in ordered if slot in _texts(paper.get("query_slots"), limit=32)
             and _text(paper.get("canonical_paper_id"), limit=200) not in selected_ids),
            None,
        )
        if candidate is not None:
            candidate_id = _text(candidate.get("canonical_paper_id"), limit=200)
            selected.append(candidate)
            selected_ids.add(candidate_id)
            selected_by_slot[slot] = candidate_id
    for paper in ordered:
        if len(selected) >= limit:
            break
        candidate_id = _text(paper.get("canonical_paper_id"), limit=200)
        if candidate_id not in selected_ids:
            selected.append(paper)
            selected_ids.add(candidate_id)
    omitted = [paper for paper in ordered if _text(paper.get("canonical_paper_id"), limit=200) not in selected_ids]
    return selected, omitted, selected_by_slot


def _expand_query_variants(evidence_plan: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Expand bounded planner variants into independent provider query tasks."""

    expanded: list[dict[str, Any]] = []
    for raw_task in _mapping(evidence_plan).get("queries") or []:
        task = _mapping(raw_task)
        parent_task_id = _text(task.get("task_id"), limit=120)
        slot = _text(task.get("slot"), limit=120)
        if not parent_task_id or not slot:
            continue
        raw_variants = task.get("query_variants")
        variants = (
            raw_variants
            if isinstance(raw_variants, Sequence) and not isinstance(raw_variants, (str, bytes))
            else [
                {
                    "variant_id": "legacy",
                    "query": task.get("query"),
                    "purpose": "Legacy single-query task supplied directly to the collector.",
                }
            ]
        )
        is_legacy = not isinstance(raw_variants, Sequence) or isinstance(raw_variants, (str, bytes))
        for position, raw_variant in enumerate(variants, start=1):
            variant = _mapping(raw_variant)
            query = _text(variant.get("query"), limit=2000)
            variant_id = _text(variant.get("variant_id"), limit=80) or f"q{position}"
            purpose = _text(variant.get("purpose"), limit=600)
            if not query:
                continue
            expanded.append(
                {
                    **task,
                    "task_id": parent_task_id if is_legacy else f"{parent_task_id}.{variant_id}",
                    "parent_task_id": parent_task_id,
                    "slot": slot,
                    "query": query,
                    "query_variant_id": variant_id,
                    "query_variant_purpose": purpose,
                }
            )
    return expanded


class SurveyEvidenceCollector:
    """Collect per-slot papers with OpenAlex-first, unavailable-only fallback semantics."""

    def __init__(
        self,
        *,
        openalex_client: Any | None = None,
        semantic_scholar_client: Any | None = None,
        fulltext_fetcher: Any | None = None,
        paper_screener: DesignEvidencePaperScreener | None = None,
        survey_artifact_adapter: SurveyArtifactAdapter | None = None,
        max_screening_candidates: int = DEFAULT_MAX_SCREENING_CANDIDATES,
        cache: ExperimentDesignCache | None = None,
        cache_context: Mapping[str, Any] | None = None,
    ) -> None:
        self.cache = cache or ExperimentDesignCache({"enabled": False})
        self.cache_context = _mapping(cache_context)
        self.openalex_client = openalex_client or OpenAlexWorksClient()
        self.semantic_scholar_client = semantic_scholar_client or SemanticScholarWorksClient()
        self.fulltext_fetcher = fulltext_fetcher or SurveyCompatibleFulltextAcquirer(cache=self.cache)
        self.paper_screener = paper_screener or DesignEvidencePaperScreener()
        self.survey_artifact_adapter = survey_artifact_adapter or SurveyArtifactAdapter()
        self.max_screening_candidates = max(1, int(max_screening_candidates))

    @classmethod
    def from_config(cls, config: object | None = None) -> "SurveyEvidenceCollector":
        """Build retrieval clients from the ExperimentDesign runtime configuration."""

        if config is None:
            from src.config import get_experiment_design_config

            config = get_experiment_design_config()
        experiment_design_config = _setting(config, "experiment_design", config)
        retrieval = _setting(experiment_design_config, "retrieval", {})
        openalex = _setting(retrieval, "openalex", {})
        semantic = _setting(retrieval, "semantic_scholar", {})
        fulltext = _setting(retrieval, "fulltext", {})
        screening = _setting(retrieval, "paper_screening", {})
        cache = ExperimentDesignCache(_cache_config(config))
        return cls(
            openalex_client=OpenAlexWorksClient(
                api_key=str(_setting(openalex, "api_key", "") or ""),
                email=str(_setting(openalex, "email", "") or ""),
                base_url=str(_setting(openalex, "base_url", "https://api.openalex.org") or "https://api.openalex.org"),
            ),
            semantic_scholar_client=SemanticScholarWorksClient(
                api_key=str(_setting(semantic, "api_key", "") or ""),
                base_url=str(_setting(semantic, "base_url", "https://api.semanticscholar.org/graph/v1") or "https://api.semanticscholar.org/graph/v1"),
            ),
            fulltext_fetcher=SurveyCompatibleFulltextAcquirer(fulltext, cache=cache),
            paper_screener=DesignEvidencePaperScreener(
                fulltext_budget=max(
                    0,
                    int(_setting(screening, "fulltext_budget", _setting(fulltext, "max_papers", 15)) or 0),
                ),
                parallel_workers=max(
                    1,
                    int(_setting(screening, "parallel_workers", 8) or 1),
                ),
            ),
            max_screening_candidates=max(
                1,
                int(_setting(screening, "max_candidates_before_llm", DEFAULT_MAX_SCREENING_CANDIDATES) or 1),
            ),
            cache=cache,
            cache_context=_llm_cache_context(config),
        )

    def _fetch_fulltext(
        self,
        paper: Mapping[str, Any],
        *,
        logger: Any | None = None,
        cache_run_id: str = "",
    ) -> dict[str, Any]:
        acquire = getattr(self.fulltext_fetcher, "acquire", None)
        fetch = acquire if callable(acquire) else getattr(self.fulltext_fetcher, "fetch", self.fulltext_fetcher)
        try:
            if callable(acquire):
                try:
                    result = fetch(paper, logger=logger, cache_run_id=cache_run_id)
                except TypeError:
                    result = fetch(paper, logger=logger)
            else:
                result = fetch(paper)
        except Exception as exc:
            return {
                "fulltext_acquisition": {
                    "schema_version": "experiment_design_fulltext_acquisition_v1",
                    "status": "acquisition_error",
                    "selected_candidate": {},
                    "attempts": [],
                    "parser": {"backend": "survey_mineru", "status": "not_started"},
                    "error_type": type(exc).__name__,
                }
            }
        return _mapping(result)

    def collect(
        self,
        evidence_plan: Mapping[str, Any],
        *,
        max_results_per_query: int = 10,
        max_fulltext_papers: int = 15,
        survey_artifacts: Mapping[str, Any] | Sequence[Mapping[str, Any]] | None = None,
        screener_llm_call: Callable[..., object] | None = None,
        logger: Any | None = None,
        cache_run_id: str = "",
    ) -> dict[str, Any]:
        plan = _mapping(evidence_plan)
        collection_cache_identity = {
            "evidence_plan": plan,
            "max_results_per_query": max(1, int(max_results_per_query)),
            "max_fulltext_papers": max(0, int(max_fulltext_papers)),
            "survey_artifacts_sha256": content_digest(survey_artifacts or {}),
            "collection_schema_version": SURVEY_EVIDENCE_COLLECTION_SCHEMA_VERSION,
            "collection_cache_version": SURVEY_EVIDENCE_COLLECTION_CACHE_VERSION,
            "paper_screener_prompt_sha256": text_digest(DESIGN_EVIDENCE_PAPER_SCREENER_PROMPT),
            "cache_context": self.cache_context,
        }
        cached_collection = self.cache.read(
            "retrieval_collections",
            collection_cache_identity,
            run_id=cache_run_id,
        )
        if cached_collection is not None:
            _emit_retrieval_log(
                logger,
                "collection_cache_hit",
                status="CACHED",
                paper_count=len(cached_collection.get("papers") or []),
            )
            return cached_collection
        expanded_tasks = _expand_query_variants(plan)
        if self.cache.offline:
            _emit_retrieval_log(
                logger,
                "collection_cache_miss",
                level="WARNING",
                status="OFFLINE_DEGRADED",
                query_variant_count=len(expanded_tasks),
            )
            return {
                "schema_version": SURVEY_EVIDENCE_COLLECTION_SCHEMA_VERSION,
                "collection_policy": "read_only_cache_miss_no_external_retrieval",
                "provider_runs": [
                    {
                        "task_id": _text(task.get("task_id"), limit=120),
                        "provider": "cache",
                        "status": "CACHE_MISS",
                        "native_field_filter": [],
                        "native_field_filter_applied": False,
                        "detail": "No matching retrieval snapshot is available; no provider was contacted.",
                    }
                    for task in expanded_tasks
                ],
                "papers": [],
                "paper_count": 0,
                "paper_screening": {
                    "schema_version": "experiment_design_paper_screening_audit_v1",
                    "screening_policy": "not_run_read_only_cache_miss",
                    "requested_slots": _texts([_mapping(task).get("slot") for task in expanded_tasks], limit=32),
                    "fulltext_budget": 0,
                    "screening_candidate_budget": self.max_screening_candidates,
                    "discovered_unique_paper_count": 0,
                    "screened_paper_count": 0,
                    "omitted_before_screening_count": 0,
                    "omitted_before_screening_paper_ids": [],
                    "pre_screen_selected_by_slot": {},
                    "eligible_for_fulltext_count": 0,
                    "selected_paper_ids": [],
                    "selected_by_slot": {},
                    "screens_by_paper": {},
                },
                "fulltext_acquisition_by_paper": {},
            }
        records: list[dict[str, Any]] = []
        provider_runs: list[dict[str, Any]] = []
        for task in expanded_tasks:
            task_id = _text(task.get("task_id"), limit=120)
            if not task_id:
                continue
            field_filter: list[str] = []
            query_fields = {
                "task_id": task_id,
                "parent_task_id": _text(task.get("parent_task_id"), limit=120),
                "query_variant_id": _text(task.get("query_variant_id"), limit=80),
                "slot": _text(task.get("slot"), limit=120),
                "query": _text(task.get("query"), limit=2000),
                "requested_limit": max(1, int(max_results_per_query)),
                "native_field_filter": field_filter,
                "endpoint": _provider_endpoint(self.openalex_client, "/works"),
            }
            _emit_retrieval_log(
                logger,
                "openalex_query",
                status="RUNNING",
                provider="openalex",
                **query_fields,
            )
            try:
                papers = self.openalex_client.search(task, limit=max_results_per_query)
            except ProviderUnavailable as exc:
                _emit_retrieval_log(
                    logger,
                    "openalex_query",
                    level="WARNING",
                    status="UNAVAILABLE",
                    provider="openalex",
                    error=_text(exc, limit=400),
                    **query_fields,
                )
                provider_runs.append(
                    {
                        "task_id": task_id,
                        "provider": "openalex",
                        "status": "UNAVAILABLE",
                        "native_field_filter": field_filter,
                        "native_field_filter_applied": False,
                        "detail": _text(exc, limit=400),
                    }
                )
                _emit_retrieval_log(
                    logger,
                    "semantic_scholar_query",
                    status="RUNNING",
                    provider="semantic_scholar",
                    fallback_reason="openalex_unavailable",
                    endpoint=_provider_endpoint(self.semantic_scholar_client, "/paper/search"),
                    **{key: value for key, value in query_fields.items() if key != "endpoint"},
                )
                try:
                    papers = self.semantic_scholar_client.search(task, limit=max_results_per_query)
                except (ProviderUnavailable, ProviderQueryError) as fallback_exc:
                    _emit_retrieval_log(
                        logger,
                        "semantic_scholar_query",
                        level="WARNING",
                        status="UNAVAILABLE",
                        provider="semantic_scholar",
                        fallback_reason="openalex_unavailable",
                        error=_text(fallback_exc, limit=400),
                        endpoint=_provider_endpoint(self.semantic_scholar_client, "/paper/search"),
                        **{key: value for key, value in query_fields.items() if key != "endpoint"},
                    )
                    provider_runs.append(
                        {
                            "task_id": task_id,
                            "provider": "semantic_scholar",
                            "status": "UNAVAILABLE",
                            "native_field_filter": field_filter,
                            "native_field_filter_applied": False,
                            "detail": _text(fallback_exc, limit=400),
                        }
                    )
                    continue
                _emit_retrieval_log(
                    logger,
                    "semantic_scholar_results",
                    status="FALLBACK_SUCCESS" if papers else "FALLBACK_EMPTY",
                    provider="semantic_scholar",
                    fallback_reason="openalex_unavailable",
                    paper_count=len(papers),
                    papers=_paper_log_records(papers),
                    endpoint=_provider_endpoint(self.semantic_scholar_client, "/paper/search"),
                    **{key: value for key, value in query_fields.items() if key != "endpoint"},
                )
                provider_runs.append(
                    {
                        "task_id": task_id,
                        "provider": "semantic_scholar",
                        "status": "FALLBACK_SUCCESS" if papers else "FALLBACK_EMPTY",
                        "native_field_filter": field_filter,
                        "native_field_filter_applied": False,
                        "detail": "Semantic Scholar was used only because OpenAlex was unavailable.",
                    }
                )
                records.extend(_mapping(paper) for paper in papers)
                continue
            except ProviderQueryError as exc:
                _emit_retrieval_log(
                    logger,
                    "openalex_query",
                    level="WARNING",
                    status="QUERY_ERROR",
                    provider="openalex",
                    error=_text(exc, limit=400),
                    **query_fields,
                )
                provider_runs.append(
                    {
                        "task_id": task_id,
                        "provider": "openalex",
                        "status": "QUERY_ERROR",
                        "native_field_filter": field_filter,
                        "native_field_filter_applied": False,
                        "detail": _text(exc, limit=400),
                    }
                )
                continue
            _emit_retrieval_log(
                logger,
                "openalex_results",
                status="SUCCESS" if papers else "EMPTY",
                provider="openalex",
                paper_count=len(papers),
                papers=_paper_log_records(papers),
                **query_fields,
            )
            provider_runs.append(
                {
                    "task_id": task_id,
                    "provider": "openalex",
                    "status": "SUCCESS" if papers else "EMPTY",
                    "native_field_filter": field_filter,
                    "native_field_filter_applied": bool(field_filter),
                    "detail": "OpenAlex returned a valid response; a valid empty result does not trigger fallback.",
                }
            )
            records.extend(_mapping(paper) for paper in papers)
        merged = _merge_papers(records)
        enriched = self.survey_artifact_adapter.enrich(merged, survey_artifacts)
        configured_fulltext_limit = getattr(self.fulltext_fetcher, "max_papers", max_fulltext_papers)
        fulltext_limit = min(
            max(0, int(max_fulltext_papers)),
            max(0, int(configured_fulltext_limit)),
            max(0, int(getattr(self.paper_screener, "fulltext_budget", 15))),
        )
        requested_slots = _texts(
            [_mapping(task).get("slot") for task in expanded_tasks],
            limit=32,
        )
        screening_candidates, omitted_candidates, pre_screen_selected_by_slot = _bound_screening_candidates(
            enriched,
            maximum=self.max_screening_candidates,
            planned_slots=requested_slots,
        )
        _emit_retrieval_log(
            logger,
            "screening_candidates_bounded",
            status="COMPLETED",
            discovered_unique_paper_count=len(enriched),
            screening_candidate_budget=self.max_screening_candidates,
            selected_candidate_count=len(screening_candidates),
            omitted_before_screening_count=len(omitted_candidates),
            pre_screen_selected_by_slot=pre_screen_selected_by_slot,
            selected_candidate_ids=[
                _text(paper.get("canonical_paper_id"), limit=200) for paper in screening_candidates
            ],
        )
        enriched = screening_candidates
        screening_audit: dict[str, Any] = {
            "schema_version": "experiment_design_paper_screening_audit_v1",
            "screening_policy": "bounded_candidate_set_before_required_json_llm_screening",
            "requested_slots": requested_slots,
            "fulltext_budget": fulltext_limit,
            "screening_candidate_budget": self.max_screening_candidates,
            "discovered_unique_paper_count": len(enriched) + len(omitted_candidates),
            "screened_paper_count": 0,
            "omitted_before_screening_count": len(omitted_candidates),
            "omitted_before_screening_paper_ids": [
                _text(paper.get("canonical_paper_id"), limit=200) for paper in omitted_candidates
            ],
            "pre_screen_selected_by_slot": pre_screen_selected_by_slot,
            "eligible_for_fulltext_count": 0,
            "selected_paper_ids": [],
            "selected_by_slot": {},
            "screens_by_paper": {},
        }
        if screening_candidates and fulltext_limit > 0:
            screened_candidates, screening_audit = self.paper_screener.screen_and_select(
                screening_candidates,
                requested_slots=requested_slots,
                llm_call=screener_llm_call,
                max_fulltext_papers=fulltext_limit,
                logger=logger,
            )
            screened_by_id = {
                _text(paper.get("canonical_paper_id"), limit=200): paper for paper in screened_candidates
            }
            enriched = [
                screened_by_id.get(_text(paper.get("canonical_paper_id"), limit=200), paper)
                for paper in enriched
            ]
            screening_audit["screening_candidate_budget"] = self.max_screening_candidates
            screening_audit["discovered_unique_paper_count"] = len(enriched) + len(omitted_candidates)
            screening_audit["omitted_before_screening_count"] = len(omitted_candidates)
            screening_audit["omitted_before_screening_paper_ids"] = [
                _text(paper.get("canonical_paper_id"), limit=200) for paper in omitted_candidates
            ]
            screening_audit["pre_screen_selected_by_slot"] = pre_screen_selected_by_slot
        selected_for_fulltext = set(screening_audit.get("selected_paper_ids") or [])
        for index, paper in enumerate(enriched):
            if _text(paper.get("fulltext"), limit=100):
                continue
            if _text(paper.get("canonical_paper_id"), limit=160) not in selected_for_fulltext:
                continue
            fetched = self._fetch_fulltext(paper, logger=logger, cache_run_id=cache_run_id)
            if fetched:
                enriched[index] = {**paper, **fetched}
        for paper in enriched:
            if _text(paper.get("fulltext"), limit=100):
                paper["content_availability"] = "fulltext"
            elif _text(paper.get("user_supplied_text"), limit=100):
                paper["content_availability"] = "user_supplied"
            elif _text(paper.get("abstract"), limit=100):
                paper["content_availability"] = "abstract"
            else:
                paper["content_availability"] = "metadata"
        collection = {
            "schema_version": SURVEY_EVIDENCE_COLLECTION_SCHEMA_VERSION,
            "collection_policy": "openalex_primary_semantic_scholar_fallback_only_when_openalex_unavailable",
            "provider_runs": provider_runs,
            "papers": enriched,
            "paper_count": len(enriched),
            "paper_screening": screening_audit,
            "fulltext_acquisition_by_paper": {
                _text(paper.get("canonical_paper_id"), limit=160): _mapping(paper.get("fulltext_acquisition"))
                for paper in enriched
                if _text(paper.get("canonical_paper_id"), limit=160)
                and _mapping(paper.get("fulltext_acquisition"))
            },
        }
        self.cache.write(
            "retrieval_collections",
            collection_cache_identity,
            collection,
            metadata={"paper_count": len(enriched)},
            run_id=cache_run_id,
        )
        return collection


class SurveyEvidenceAdapter:
    """Turn per-slot collection records into a validated EvidenceBundle v1."""

    def __init__(
        self,
        *,
        collector: SurveyEvidenceCollector | None = None,
        card_extractor: EvidenceCardExtractor | None = None,
        card_llm_call: Callable[[str], object] | None = None,
        screener_llm_call: Callable[..., object] | None = None,
        card_parallel_workers: int = DEFAULT_EVIDENCE_CARD_PARALLEL_WORKERS,
        cache: ExperimentDesignCache | None = None,
        cache_context: Mapping[str, Any] | None = None,
    ) -> None:
        self.collector = collector or SurveyEvidenceCollector()
        collector_cache = getattr(self.collector, "cache", None)
        self.cache = cache or collector_cache or ExperimentDesignCache({"enabled": False})
        self.cache_context = _mapping(cache_context) or _mapping(getattr(self.collector, "cache_context", {}))
        self.card_extractor = card_extractor or EvidenceCardExtractor()
        self.card_llm_call = card_llm_call
        self.screener_llm_call = screener_llm_call or card_llm_call
        self.card_parallel_workers = max(1, int(card_parallel_workers))

    @classmethod
    def from_config(
        cls,
        *,
        card_llm_call: Callable[[str], object] | None = None,
        screener_llm_call: Callable[..., object] | None = None,
        config: object | None = None,
    ) -> "SurveyEvidenceAdapter":
        """Build a Survey-style evidence adapter using the active agent configuration."""

        if config is None:
            from src.config import get_experiment_design_config

            config = get_experiment_design_config()
        experiment_design_config = _setting(config, "experiment_design", config)
        retrieval = _setting(experiment_design_config, "retrieval", {})
        card_extraction = _setting(retrieval, "evidence_card_extraction", {})
        collector = SurveyEvidenceCollector.from_config(config)

        return cls(
            collector=collector,
            card_llm_call=card_llm_call,
            screener_llm_call=screener_llm_call or card_llm_call,
            card_parallel_workers=max(
                1,
                int(
                    _setting(
                        card_extraction,
                        "parallel_workers",
                        DEFAULT_EVIDENCE_CARD_PARALLEL_WORKERS,
                    )
                    or 1
                ),
            ),
            cache=collector.cache,
            cache_context=_llm_cache_context(config),
        )

    def _extract_cards_for_paper(
        self,
        *,
        paper_index: int,
        paper: Mapping[str, Any],
        planned_slots: Sequence[str],
        logger: Any | None,
        cache_run_id: str,
    ) -> dict[str, Any]:
        paper_id = _text(paper.get("canonical_paper_id"), limit=160) or "<missing>"
        if _text(paper.get("fulltext"), limit=100):
            source_level = "fulltext"
            source_location = _text(paper.get("fulltext_source_location"), limit=300)
        elif _text(paper.get("user_supplied_text"), limit=100):
            source_level = "user_supplied"
            source_location = _text(paper.get("user_supplied_text_source_location"), limit=300)
        elif _text(paper.get("abstract"), limit=100):
            source_level = "abstract"
            source_location = _text(paper.get("abstract_source_location"), limit=300)
        else:
            source_level = "metadata"
            source_location = "metadata"
        source_text = (
            paper.get("fulltext")
            or paper.get("user_supplied_text")
            or paper.get("abstract")
            or ""
        )
        card_cache_identity = {
            "canonical_paper_id": paper_id,
            "source_level": source_level,
            "source_text_sha256": text_digest(source_text),
            "requested_slots": list(planned_slots),
            "card_prompt_sha256": text_digest(EVIDENCE_CARD_EXTRACTOR_PROMPT),
            "cache_context": self.cache_context,
        }
        if logger is not None:
            logger.event(
                "evidence_card_extraction",
                "started",
                status="RUNNING",
                canonical_paper_id=paper_id,
                evidence_level=source_level,
                source_location=source_location,
                requested_slot_count=len(planned_slots),
                parallel_workers=self.card_parallel_workers,
            )
        cached_cards = self.cache.read(
            "evidence_cards",
            card_cache_identity,
            run_id=cache_run_id,
        )
        if cached_cards is not None:
            extracted = list(cached_cards.get("cards") or [])
            extraction_warnings = _texts(cached_cards.get("warnings"), limit=1000)
            if logger is not None:
                logger.event(
                    "evidence_card_extraction",
                    "cache_hit",
                    status="CACHED",
                    canonical_paper_id=paper_id,
                    card_count=len(extracted),
                    parallel_workers=self.card_parallel_workers,
                )
            return {
                "paper_index": paper_index,
                "cards": extracted,
                "warnings": extraction_warnings,
            }
        if self.cache.offline:
            warning = f"evidence_card_cache_miss:{paper_id}:no_llm_call"
            if logger is not None:
                logger.event(
                    "evidence_card_extraction",
                    "cache_miss",
                    level="WARNING",
                    status="OFFLINE_DEGRADED",
                    canonical_paper_id=paper_id,
                    parallel_workers=self.card_parallel_workers,
                )
            return {"paper_index": paper_index, "cards": [], "warnings": [warning]}
        try:
            extracted, extraction_warnings = self.card_extractor.extract(
                paper,
                requested_slots=planned_slots,
                llm_call=self.card_llm_call,
            )
        except Exception as exc:
            if logger is not None:
                logger.exception(
                    "evidence_card_extraction",
                    exc,
                    canonical_paper_id=paper_id,
                    evidence_level=source_level,
                    source_location=source_location,
                    parallel_workers=self.card_parallel_workers,
                )
            return {
                "paper_index": paper_index,
                "error": exc,
                "failure": {
                    "canonical_paper_id": paper_id,
                    "status": "FAILED",
                    "error_type": type(exc).__name__,
                    "error": _text(str(exc), limit=1200),
                    "evidence_level": source_level,
                    "source_location": source_location,
                    "continue_on_failure": True,
                },
            }
        if logger is not None:
            for warning in extraction_warnings:
                logger.event(
                    "evidence_card_extraction",
                    "card_rejected",
                    level="WARNING",
                    status="SKIPPED",
                    canonical_paper_id=paper_id,
                    warning=_text(warning, limit=1200),
                    parallel_workers=self.card_parallel_workers,
                )
            for card in extracted:
                logger.event(
                    "evidence_card_extraction",
                    "validated",
                    status="COMPLETED",
                    canonical_paper_id=paper_id,
                    card_id=_text(card.get("card_id"), limit=200),
                    claim_slot=_text(card.get("claim_slot"), limit=120),
                    source_id=_text(card.get("source_id"), limit=160),
                    source_location=_text(card.get("source_location"), limit=300),
                    evidence_level=_text(card.get("evidence_level"), limit=40),
                    parallel_workers=self.card_parallel_workers,
                )
            logger.event(
                "evidence_card_extraction",
                "completed",
                status=(
                    "COMPLETED_WITH_WARNINGS"
                    if extracted and extraction_warnings
                    else "COMPLETED"
                    if extracted
                    else "SKIPPED"
                ),
                canonical_paper_id=paper_id,
                evidence_level=source_level,
                source_location=source_location,
                card_count=len(extracted),
                warning_count=len(extraction_warnings),
                parallel_workers=self.card_parallel_workers,
            )
        self.cache.write(
            "evidence_cards",
            card_cache_identity,
            {"cards": extracted, "warnings": extraction_warnings},
            metadata={"canonical_paper_id": paper_id, "source_level": source_level},
            run_id=cache_run_id,
        )
        return {
            "paper_index": paper_index,
            "cards": extracted,
            "warnings": extraction_warnings,
        }

    def collect_and_extract(
        self,
        *,
        brief_id: str,
        evidence_plan: Mapping[str, Any],
        survey_artifacts: Mapping[str, Any] | Sequence[Mapping[str, Any]] | None = None,
        max_results_per_query: int = 10,
        max_fulltext_papers: int = 15,
        logger: Any | None = None,
        cache_run_id: str = "",
    ) -> dict[str, Any]:
        cache_run_id = cache_run_id or self.cache.begin_run(brief_id)
        collection = self.collector.collect(
            evidence_plan,
            max_results_per_query=max_results_per_query,
            max_fulltext_papers=max_fulltext_papers,
            survey_artifacts=survey_artifacts,
            screener_llm_call=self.screener_llm_call,
            logger=logger,
            cache_run_id=cache_run_id,
        )
        planned_slots = _texts(
            [
                _mapping(task).get("slot")
                for task in _mapping(evidence_plan).get("queries") or []
            ],
            limit=32,
        )
        cards: list[dict[str, Any]] = []
        warnings: list[str] = []
        extraction_failures: list[dict[str, Any]] = []
        papers = list(collection["papers"])
        extraction_results: list[dict[str, Any] | None] = [None] * len(papers)
        if papers:
            worker_count = min(self.card_parallel_workers, len(papers))
            with ThreadPoolExecutor(max_workers=worker_count) as executor:
                futures = {
                    executor.submit(
                        self._extract_cards_for_paper,
                        paper_index=paper_index,
                        paper=paper,
                        planned_slots=planned_slots,
                        logger=logger,
                        cache_run_id=cache_run_id,
                    ): paper_index
                    for paper_index, paper in enumerate(papers)
                }
                for future in as_completed(futures):
                    result = future.result()
                    extraction_results[result["paper_index"]] = result

        for result in extraction_results:
            if result is None:
                continue
            error = result.get("error")
            if isinstance(error, Exception):
                failure = _mapping(result.get("failure"))
                if failure:
                    extraction_failures.append(failure)
                    warnings.append(
                        "evidence_card_extraction_failed:"
                        f"{_text(failure.get('canonical_paper_id'), limit=160)}:"
                        f"{_text(failure.get('error_type'), limit=80)}"
                    )
                continue
            cards.extend(result.get("cards") or [])
            warnings.extend(_texts(result.get("warnings"), limit=1000))
        retrieval_audit = {
            "collection_policy": collection["collection_policy"],
            "provider_runs": collection["provider_runs"],
            "paper_screening": collection.get("paper_screening", {}),
            "fulltext_acquisition_by_paper": collection.get("fulltext_acquisition_by_paper", {}),
            "card_extraction_warnings": warnings,
            "card_extraction_failures": extraction_failures,
            "failed_card_extraction_paper_count": len(extraction_failures),
            "failed_card_extraction_paper_ids": [
                _text(failure.get("canonical_paper_id"), limit=160)
                for failure in extraction_failures
            ],
        }
        if logger is not None:
            logger.event(
                "evidence_bundle",
                "started",
                status="RUNNING",
                brief_id=brief_id,
                paper_count=len(collection["papers"]),
                evidence_card_count=len(cards),
                planned_slot_count=len(planned_slots),
            )
        try:
            bundle = build_traceable_evidence_bundle(
                brief_id=brief_id,
                planned_slots=planned_slots,
                papers=collection["papers"],
                evidence_cards=cards,
                retrieval_audit=retrieval_audit,
            )
        except Exception as exc:
            if logger is not None:
                logger.exception(
                    "evidence_bundle",
                    exc,
                    brief_id=brief_id,
                    paper_count=len(collection["papers"]),
                    evidence_card_count=len(cards),
                )
            raise
        if logger is not None:
            coverage = _mapping(bundle.get("coverage"))
            logger.event(
                "evidence_bundle",
                "completed",
                status="COMPLETED",
                brief_id=brief_id,
                paper_count=len(bundle.get("paper_registry") or []),
                evidence_card_count=len(bundle.get("evidence_cards") or []),
                required_slot_count=len(coverage.get("required_slots") or []),
                covered_slot_count=len(coverage.get("covered_slots") or []),
                uncovered_slot_count=len(coverage.get("uncovered_slots") or []),
            )
        return {
            "schema_version": SURVEY_EVIDENCE_ADAPTATION_SCHEMA_VERSION,
            "collection": collection,
            "evidence_bundle": bundle,
            "warnings": warnings,
            "cache_manifest": self.cache.run_manifest(cache_run_id),
        }
