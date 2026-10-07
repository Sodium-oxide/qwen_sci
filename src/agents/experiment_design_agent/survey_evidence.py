"""Original Survey paper acquisition and reference evidence adaptation."""

from __future__ import annotations

from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor, as_completed
import re
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from .cache import ExperimentDesignCache, content_digest, text_digest
from .evidence_cards import (
    EVIDENCE_CARD_EXTRACTOR_PROMPT,
    EvidenceCardExtractor,
    build_traceable_evidence_bundle,
)
from .fulltext_acquisition import SurveyCompatibleFulltextAcquirer


SURVEY_EVIDENCE_COLLECTION_SCHEMA_VERSION = "experiment_design_survey_evidence_collection_v1"
SURVEY_EVIDENCE_ADAPTATION_SCHEMA_VERSION = "experiment_design_survey_evidence_adaptation_v1"
SURVEY_EVIDENCE_COLLECTION_CACHE_VERSION = "experiment_design_survey_evidence_cache_v1"
DEFAULT_EVIDENCE_CARD_PARALLEL_WORKERS = 3


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


class SurveyEvidenceCollector:
    """Load ranked original Survey papers; never discover papers independently."""

    def __init__(self, *, fulltext_fetcher=None, cache=None, cache_context=None,
                 max_papers=32, max_expansion_papers=12, min_graph_relevance_score=3, **legacy_clients):
        self.cache = cache or ExperimentDesignCache({"enabled": False})
        self.cache_context = _mapping(cache_context)
        self.fulltext_fetcher = fulltext_fetcher
        self.max_papers = min(32, max(0, int(max_papers)))
        self.max_expansion_papers = max(0, int(max_expansion_papers))
        self.min_graph_relevance_score = float(min_graph_relevance_score)

    @classmethod
    def from_config(cls, config=None):
        if config is None:
            from src.config import get_experiment_design_config
            config = get_experiment_design_config()
        settings = _setting(config, "experiment_design", config)
        papers = _setting(settings, "evidence_papers", {})
        retrieval = _setting(settings, "retrieval", {})
        cache = ExperimentDesignCache(_cache_config(config))
        return cls(
            fulltext_fetcher=SurveyCompatibleFulltextAcquirer(_setting(retrieval, "fulltext", {}), cache=cache),
            max_papers=_setting(papers, "max_count", 32),
            max_expansion_papers=_setting(papers, "max_graph_papers", 12),
            min_graph_relevance_score=_setting(papers, "min_graph_relevance_score", 3),
            cache=cache, cache_context=_llm_cache_context(config),
        )

    def collect(self, evidence_plan, *, survey_artifacts=None, max_fulltext_papers=32,
                max_results_per_query=0, screener_llm_call=None, logger=None, cache_run_id=""):
        from .survey_paper_pool import select_survey_papers
        pool = select_survey_papers(survey_artifacts, max_papers=self.max_papers,
                                   max_expansion_papers=self.max_expansion_papers,
                                   min_graph_relevance_score=self.min_graph_relevance_score)
        if logger is not None:
            for warning in pool["warnings"]:
                logger.event("survey_paper_pool", "source_warning", level="WARNING", status="WARNING", reason=warning)
            for event in ("survey_paper_pool_loaded", "survey_high_score_papers_selected",
                          "citation_graph_expansion_completed"):
                logger.event("survey_paper_pool", event, status="COMPLETED",
                             primary_paper_count=pool["primary_paper_count"],
                             expansion_paper_count=pool["expansion_paper_count"],
                             total_paper_count=pool["paper_count"])
        fetched = 0
        for paper in pool["papers"]:
            if paper.get("fulltext") or self.fulltext_fetcher is None or self.cache.offline:
                continue
            if fetched >= max(0, min(32, int(max_fulltext_papers))):
                break
            fetched += 1
            if logger is not None:
                logger.event("survey_paper_pool", "survey_selected_fulltext_acquisition",
                             status="RUNNING", canonical_paper_id=paper["canonical_paper_id"],
                             discovery_performed=False)
            acquire = getattr(self.fulltext_fetcher, "acquire", None)
            try:
                if callable(acquire):
                    acquired = acquire(paper, logger=logger, cache_run_id=cache_run_id)
                else:
                    acquired = getattr(self.fulltext_fetcher, "fetch", self.fulltext_fetcher)(paper)
                paper.update(_mapping(acquired))
            except Exception as error:
                paper["fulltext_acquisition"] = {"status": "acquisition_error", "error_type": type(error).__name__}
            paper["content_availability"] = "fulltext" if paper.get("fulltext") else "abstract" if paper.get("abstract") else "metadata"
        return {
            "schema_version": SURVEY_EVIDENCE_COLLECTION_SCHEMA_VERSION,
            "collection_policy": "survey_original_papers_only",
            "papers": pool["papers"], "paper_pool": pool, "provider_runs": [],
            "paper_screening": {"policy": "survey_scores_accepted", "llm_used": False},
            "fulltext_acquisition_by_paper": {
                paper["canonical_paper_id"]: paper.get("fulltext_acquisition", {})
                for paper in pool["papers"]
            },
        }


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
        methodology_detail_policy: Mapping[str, Any] | None,
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
            "methodology_detail_policy": _mapping(methodology_detail_policy),
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
                methodology_detail_policy=methodology_detail_policy,
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
        methodology_detail_policy: Mapping[str, Any] | None = None,
        survey_artifacts: Mapping[str, Any] | Sequence[Mapping[str, Any]] | None = None,
        max_results_per_query: int = 10,
        max_fulltext_papers: int = 32,
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
        from .survey_paper_pool import REFERENCE_SLOTS

        planned_slots = list(REFERENCE_SLOTS)
        cards: list[dict[str, Any]] = []
        warnings: list[str] = list(collection.get("paper_pool", {}).get("warnings", []))
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
                        methodology_detail_policy=methodology_detail_policy,
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
        for card in cards:
            card["evidence_role"] = "reference"
            card["usage"] = "variables_and_definitions"
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
            bundle["evidence_role"] = "reference"
            bundle["usage"] = "variables_and_definitions"
            bundle["paper_pool"] = {key: value for key, value in collection.get("paper_pool", {}).items() if key != "papers"}
            from .contracts import validate_evidence_bundle
            errors = validate_evidence_bundle(bundle)
            if errors:
                raise ValueError("; ".join(errors))
            if logger is not None:
                logger.event("survey_paper_pool", "survey_evidence_cards_extracted", status="COMPLETED",
                             total_paper_count=len(papers), evidence_card_count=len(cards))
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
