"""Focused tests for Batch C survey-style evidence adaptation."""

from __future__ import annotations

from collections.abc import Mapping
from io import StringIO
import threading
import time

from src.agents.experiment_design_agent import (
    CompletenessValidator,
    EvidenceCardExtractor,
    OpenAlexWorksClient,
    ProviderUnavailable,
    SemanticScholarWorksClient,
    SurveyEvidenceAdapter,
    SurveyEvidenceCollector,
    build_traceable_evidence_bundle,
)
from src.agents.experiment_design_agent.run_logging import ExperimentDesignRunLogger


def _task(*, slot: str = "measurement_calibration", task_id: str = "EDQ5") -> dict:
    return {
        "task_id": task_id,
        "slot": slot,
        "objective": "A neutral evidence need.",
        "keywords": ["material interface", "calibration"],
        "query": '"material interface" AND "calibration"',
        "evidence_needed": "Traceable support or an explicit unresolved field.",
        "openalex_field_filter": ["primary_topic.field.id:25"],
    }


def _plan(*tasks: dict) -> dict:
    return {"queries": list(tasks)}


def _paper(*, level: str = "abstract") -> dict:
    paper = {
        "canonical_paper_id": "W123",
        "title": "Calibration of an interface measurement",
        "doi": "10.1000/example",
        "year": 2025,
        "authors": ["Ada Analyst", "Blaise Builder"],
        "venue": "Journal of Interface Measurement",
        "url": "https://doi.org/10.1000/example",
        "provider_ids": {"openalex": "https://api.openalex.org/works/W123", "doi": "10.1000/example"},
        "providers": ["openalex"],
        "query_task_ids": ["EDQ5"],
        "abstract": "The abstract identifies an interface measurement problem.",
        "abstract_source_location": "abstract:openalex",
        "fulltext_candidates": [],
        "fulltext_source_location": "",
        "content_availability": level,
    }
    if level == "metadata":
        paper["abstract"] = ""
        paper["content_availability"] = "metadata"
    return paper


class _Response:
    def __init__(self, status_code: int, payload: Mapping[str, object]) -> None:
        self.status_code = status_code
        self._payload = dict(payload)

    def json(self) -> dict:
        return dict(self._payload)


class _Session:
    def __init__(self, response: _Response) -> None:
        self.response = response
        self.calls: list[dict] = []

    def get(self, url: str, **kwargs: object) -> _Response:
        self.calls.append({"url": url, **kwargs})
        return self.response


def test_openalex_client_ignores_legacy_native_field_filter() -> None:
    session = _Session(
        _Response(
            200,
            {
                "results": [
                    {
                        "id": "https://api.openalex.org/works/W123",
                        "title": "A material measurement study",
                        "doi": "https://doi.org/10.1000/example",
                        "publication_year": 2025,
                        "authorships": [{"author": {"display_name": "Ada Analyst"}}],
                        "primary_location": {
                            "landing_page_url": "https://doi.org/10.1000/example",
                            "source": {"display_name": "Journal of Interface Measurement"},
                        },
                        "abstract_inverted_index": {"Calibration": [0], "matters": [1]},
                        "open_access": {"is_oa": False},
                    }
                ]
            },
        )
    )

    papers = OpenAlexWorksClient(session=session).search(_task(), limit=7)

    assert "filter" not in session.calls[0]["params"]
    assert session.calls[0]["params"]["per-page"] == 7
    assert papers[0]["canonical_paper_id"] == "W123"
    assert papers[0]["abstract"] == "Calibration matters"
    assert papers[0]["authors"] == ["Ada Analyst"]
    assert papers[0]["venue"] == "Journal of Interface Measurement"
    assert papers[0]["url"] == "https://doi.org/10.1000/example"


def test_semantic_scholar_client_preserves_bibliographic_metadata() -> None:
    session = _Session(
        _Response(
            200,
            {
                "data": [
                    {
                        "paperId": "S2-123",
                        "title": "A material measurement study",
                        "abstract": "Calibration matters.",
                        "year": 2025,
                        "authors": [{"name": "Ada Analyst"}, {"name": "Blaise Builder"}],
                        "venue": "Journal of Interface Measurement",
                        "url": "https://example.test/paper/S2-123",
                        "externalIds": {"DOI": "10.1000/example"},
                    }
                ]
            },
        )
    )

    papers = SemanticScholarWorksClient(session=session).search(_task(), limit=7)

    assert papers[0]["authors"] == ["Ada Analyst", "Blaise Builder"]
    assert papers[0]["venue"] == "Journal of Interface Measurement"
    assert papers[0]["url"] == "https://doi.org/10.1000/example"
    assert "authors" in session.calls[0]["params"]["fields"]


def test_evidence_bundle_marks_incomplete_bibliography_for_human_completion() -> None:
    paper = _paper()
    paper.pop("authors")
    paper.pop("venue")

    bundle = build_traceable_evidence_bundle(
        brief_id="brief-materials",
        planned_slots=[],
        papers=[paper],
        evidence_cards=[],
    )

    record = bundle["paper_registry"][0]
    assert record["citation_rendering_status"] == "NOT_RENDERABLE_NEEDS_HUMAN_METADATA"
    assert record["citation_missing_fields"] == ["authors", "venue"]


def test_valid_openalex_empty_result_does_not_trigger_semantic_scholar() -> None:
    class OpenAlexEmpty:
        def search(self, query_task: Mapping[str, object], *, limit: int) -> list[dict]:
            return []

    class SemanticUnexpected:
        def __init__(self) -> None:
            self.called = False

        def search(self, query_task: Mapping[str, object], *, limit: int) -> list[dict]:
            self.called = True
            return [_paper()]

    semantic = SemanticUnexpected()
    collector = SurveyEvidenceCollector(
        openalex_client=OpenAlexEmpty(),
        semantic_scholar_client=semantic,
        fulltext_fetcher=lambda _: {},
    )

    collection = collector.collect(_plan(_task()), max_fulltext_papers=0)

    assert semantic.called is False
    assert collection["papers"] == []
    assert collection["provider_runs"][0]["status"] == "EMPTY"


def test_semantic_scholar_is_used_only_when_openalex_is_unavailable() -> None:
    class OpenAlexUnavailable:
        def search(self, query_task: Mapping[str, object], *, limit: int) -> list[dict]:
            raise ProviderUnavailable("maintenance")

    class SemanticFallback:
        def __init__(self) -> None:
            self.called = False

        def search(self, query_task: Mapping[str, object], *, limit: int) -> list[dict]:
            self.called = True
            paper = _paper()
            paper["providers"] = ["semantic_scholar"]
            paper["provider_ids"] = {"semantic_scholar": "S2-paper", "openalex": "W123"}
            return [paper]

    semantic = SemanticFallback()
    collection = SurveyEvidenceCollector(
        openalex_client=OpenAlexUnavailable(),
        semantic_scholar_client=semantic,
        fulltext_fetcher=lambda _: {},
    ).collect(_plan(_task()), max_fulltext_papers=0)

    assert semantic.called is True
    assert [run["status"] for run in collection["provider_runs"]] == ["UNAVAILABLE", "FALLBACK_SUCCESS"]
    assert collection["provider_runs"][1]["native_field_filter_applied"] is False
    assert collection["papers"][0]["canonical_paper_id"] == "W123"


def test_collector_logs_openalex_query_and_traceable_result_metadata() -> None:
    class OpenAlexPapers:
        base_url = "https://api.openalex.test"

        def search(self, query_task: Mapping[str, object], *, limit: int) -> list[dict]:
            assert query_task["query"] == '"material interface" AND "calibration"'
            assert limit == 3
            return [_paper()]

    logger = ExperimentDesignRunLogger(
        "evidence-retrieval-test",
        console_stream=StringIO(),
    )
    SurveyEvidenceCollector(
        openalex_client=OpenAlexPapers(),
        semantic_scholar_client=object(),
        fulltext_fetcher=lambda _: {},
    ).collect(
        _plan(_task()),
        max_results_per_query=3,
        max_fulltext_papers=0,
        logger=logger,
    )

    events = [record for record in logger.records if record["stage"] == "evidence_retrieval"]
    assert events[0]["event"] == "openalex_query"
    assert events[0]["status"] == "RUNNING"
    assert events[0]["query"] == '"material interface" AND "calibration"'
    assert events[0]["native_field_filter"] == []
    assert events[0]["endpoint"] == "https://api.openalex.test/works"
    assert events[1]["event"] == "openalex_results"
    assert events[1]["status"] == "SUCCESS"
    assert events[1]["paper_count"] == 1
    assert events[1]["papers"] == [
        {
            "canonical_paper_id": "W123",
            "title": "Calibration of an interface measurement",
            "doi": "10.1000/example",
            "year": "2025",
            "content_availability": "abstract",
            "fulltext_candidate_count": 0,
        }
    ]


def test_collector_expands_bounded_variants_then_limits_llm_candidates() -> None:
    def paper(identifier: str, *, slot: str) -> dict:
        result = _paper()
        result["canonical_paper_id"] = identifier
        result["title"] = f"Paper {identifier}"
        result["doi"] = f"10.1000/{identifier.casefold()}"
        result["provider_ids"] = {"openalex": identifier, "doi": result["doi"]}
        result["query_slots"] = [slot]
        return result

    class OpenAlexVariants:
        def __init__(self) -> None:
            self.calls: list[dict] = []

        def search(self, query_task: Mapping[str, object], *, limit: int) -> list[dict]:
            self.calls.append(dict(query_task))
            if query_task["query_variant_id"] == "core":
                return [paper(f"W-core-{index}", slot="mechanism") for index in range(1, 4)]
            return [paper(f"W-method-{index}", slot="mechanism") for index in range(1, 4)]

    openalex = OpenAlexVariants()
    logger = ExperimentDesignRunLogger("bounded-retrieval-test", console_stream=StringIO())
    collection = SurveyEvidenceCollector(
        openalex_client=openalex,
        semantic_scholar_client=object(),
        fulltext_fetcher=lambda _: {},
        max_screening_candidates=3,
    ).collect(
        _plan(
            {
                "task_id": "EDQ1",
                "slot": "mechanism",
                "query_variants": [
                    {"variant_id": "core", "query": "material interface mechanism", "purpose": "Mechanism evidence."},
                    {"variant_id": "method", "query": "material interface theory", "purpose": "Theory evidence."},
                ],
            }
        ),
        max_fulltext_papers=0,
        logger=logger,
    )

    assert [call["task_id"] for call in openalex.calls] == ["EDQ1.core", "EDQ1.method"]
    assert all("openalex_field_filter" not in call for call in openalex.calls)
    assert collection["paper_count"] == 3
    screening = collection["paper_screening"]
    assert screening["discovered_unique_paper_count"] == 6
    assert screening["screening_candidate_budget"] == 3
    assert screening["omitted_before_screening_count"] == 3
    assert [record["event"] for record in logger.records if record["stage"] == "evidence_retrieval"][-1] == (
        "screening_candidates_bounded"
    )


def test_evidence_cards_bind_fulltext_identity_location_and_field_ledger() -> None:
    class OpenAlexPapers:
        def search(self, query_task: Mapping[str, object], *, limit: int) -> list[dict]:
            return [_paper()]

    fulltext = "The instrument was calibrated against a certified reference before each measurement session."

    def card_llm(_: str, **kwargs: object) -> dict:
        assert kwargs["response_format"] == {"type": "json_object"}
        return {
            "cards": [
                {
                    "claim_slot": "measurement_calibration",
                    "statement": "The paper reports calibration against a certified reference before measurement.",
                    "design_implication": "If this measurement approach is adopted, a comparable calibration reference should be justified and confirmed.",
                    "source_id": "W123",
                    "source_location": "fulltext:survey_artifact",
                    "evidence_level": "fulltext",
                    "evidence_excerpt": fulltext,
                    "limitations": ["The excerpt does not establish suitability for every material system."],
                    "does_not_establish": ["It does not provide the user's instrument settings."],
                }
            ]
        }

    adapter = SurveyEvidenceAdapter(
        collector=SurveyEvidenceCollector(
            openalex_client=OpenAlexPapers(),
            semantic_scholar_client=object(),
            fulltext_fetcher=lambda _: {},
        ),
        card_extractor=EvidenceCardExtractor(),
        card_llm_call=card_llm,
    )
    result = adapter.collect_and_extract(
        brief_id="brief-materials",
        evidence_plan=_plan(_task()),
        survey_artifacts={
            "papers": [
                {
                    "paper_id": "W123",
                    "fulltext": fulltext,
                    "source_location": "fulltext:survey_artifact",
                    "keynote": "Existing Survey keynote is retained as an artifact reference.",
                }
            ]
        },
        max_fulltext_papers=0,
    )

    bundle = result["evidence_bundle"]
    card = bundle["evidence_cards"][0]
    assert card["source_id"] == "W123"
    assert card["source_location"] == "fulltext:survey_artifact"
    assert card["evidence_level"] == "fulltext"
    paper_record = bundle["paper_registry"][0]
    assert paper_record["canonical_paper_id"] == "W123"
    assert paper_record["authors"] == ["Ada Analyst", "Blaise Builder"]
    assert paper_record["year"] == "2025"
    assert paper_record["venue"] == "Journal of Interface Measurement"
    assert paper_record["url"] == "https://doi.org/10.1000/example"
    assert paper_record["citation_rendering_status"] == "RENDERABLE"
    assert paper_record["citation_missing_fields"] == []
    ledger = {record["field_path"]: record for record in bundle["field_evidence_ledger"]}
    assert ledger["measurement_and_calibration"]["status"] == "evidence_backed"
    assert ledger["measurement_and_calibration"]["source_ids"] == ["W123"]


def test_evidence_card_and_bundle_steps_emit_progress_events() -> None:
    class OpenAlexPapers:
        def search(self, query_task: Mapping[str, object], *, limit: int) -> list[dict]:
            return [_paper()]

    fulltext = "The instrument was calibrated against a certified reference before each measurement session."

    def card_llm(_: str, **kwargs: object) -> dict:
        assert kwargs["response_format"] == {"type": "json_object"}
        return {
            "cards": [
                {
                    "claim_slot": "measurement_calibration",
                    "statement": "The paper reports calibration against a certified reference before measurement.",
                    "design_implication": "A comparable calibration reference should be confirmed.",
                    "source_id": "W123",
                    "source_location": "fulltext:survey_artifact",
                    "evidence_level": "fulltext",
                    "evidence_excerpt": fulltext,
                    "limitations": [],
                    "does_not_establish": [],
                }
            ]
        }

    logger = ExperimentDesignRunLogger("evidence-progress-test", console_stream=StringIO())
    adapter = SurveyEvidenceAdapter(
        collector=SurveyEvidenceCollector(
            openalex_client=OpenAlexPapers(),
            semantic_scholar_client=object(),
            fulltext_fetcher=lambda _: {},
        ),
        card_extractor=EvidenceCardExtractor(),
        card_llm_call=card_llm,
    )
    adapter.collect_and_extract(
        brief_id="brief-materials",
        evidence_plan=_plan(_task()),
        survey_artifacts={
            "papers": [
                {
                    "paper_id": "W123",
                    "fulltext": fulltext,
                    "source_location": "fulltext:survey_artifact",
                }
            ]
        },
        max_fulltext_papers=0,
        logger=logger,
    )

    assert [
        record["event"]
        for record in logger.records
        if record["stage"] == "evidence_card_extraction"
    ] == ["started", "validated", "completed"]
    assert [
        record["event"]
        for record in logger.records
        if record["stage"] == "evidence_bundle"
    ] == ["started", "completed"]


def test_evidence_card_extraction_uses_three_bounded_workers_and_preserves_order() -> None:
    papers = []
    for index in range(1, 5):
        paper = _paper()
        paper["canonical_paper_id"] = f"W{index}"
        papers.append(paper)

    class Collection:
        def collect(self, *_args: object, **_kwargs: object) -> dict[str, object]:
            return {
                "collection_policy": "test",
                "provider_runs": [],
                "papers": papers,
                "paper_screening": {},
                "fulltext_acquisition_by_paper": {},
            }

    class ParallelCardExtractor:
        def __init__(self) -> None:
            self._lock = threading.Lock()
            self.active = 0
            self.max_active = 0
            self.call_order: list[str] = []

        def extract(self, paper: Mapping[str, object], **_kwargs: object) -> tuple[list, list[str]]:
            paper_id = str(paper["canonical_paper_id"])
            with self._lock:
                self.active += 1
                self.max_active = max(self.max_active, self.active)
                self.call_order.append(paper_id)
            time.sleep(0.05)
            with self._lock:
                self.active -= 1
            return [], [f"warning:{paper_id}"]

    extractor = ParallelCardExtractor()
    result = SurveyEvidenceAdapter(
        collector=Collection(),
        card_extractor=extractor,
        card_parallel_workers=3,
    ).collect_and_extract(
        brief_id="parallel-cards",
        evidence_plan=_plan(_task()),
        max_fulltext_papers=0,
    )

    assert extractor.max_active == 3
    assert set(extractor.call_order) == {"W1", "W2", "W3", "W4"}
    assert result["warnings"] == [
        "warning:W1",
        "warning:W2",
        "warning:W3",
        "warning:W4",
    ]


def test_invalid_card_is_skipped_without_discarding_valid_cards_from_same_paper() -> None:
    paper = _paper()
    excerpt = paper["abstract"]

    def card_llm(_: str, **_kwargs: object) -> dict[str, object]:
        base = {
            "claim_slot": "measurement_calibration",
            "statement": "The abstract identifies an interface measurement problem.",
            "design_implication": "A measurement plan should address the identified interface problem.",
            "source_id": "W123",
            "source_location": "abstract:openalex",
            "evidence_level": "abstract",
            "limitations": [],
            "does_not_establish": [],
        }
        return {
            "cards": [
                {**base, "evidence_excerpt": excerpt},
                {**base, "evidence_excerpt": "This text is not in the abstract."},
            ]
        }

    cards, warnings = EvidenceCardExtractor().extract(
        paper,
        requested_slots=["measurement_calibration"],
        llm_call=card_llm,
    )

    assert len(cards) == 1
    assert cards[0]["source_id"] == "W123"
    assert warnings == ["evidence_card_extractor:W123:2: excerpt not grounded"]


def test_one_paper_card_failure_does_not_abort_evidence_bundle() -> None:
    papers = []
    for index in range(1, 4):
        paper = _paper()
        paper["canonical_paper_id"] = f"W{index}"
        papers.append(paper)

    class Collection:
        def collect(self, *_args: object, **_kwargs: object) -> dict[str, object]:
            return {
                "collection_policy": "test",
                "provider_runs": [],
                "papers": papers,
                "paper_screening": {},
                "fulltext_acquisition_by_paper": {},
            }

    class PartiallyFailingExtractor:
        def extract(self, paper: Mapping[str, object], **_kwargs: object) -> tuple[list, list[str]]:
            if paper["canonical_paper_id"] == "W2":
                raise ValueError("excerpt not grounded")
            return [], []

    logger = ExperimentDesignRunLogger("card-failure-isolation", console_enabled=False)
    result = SurveyEvidenceAdapter(
        collector=Collection(),
        card_extractor=PartiallyFailingExtractor(),
        card_parallel_workers=3,
    ).collect_and_extract(
        brief_id="card-failure-isolation",
        evidence_plan=_plan(_task()),
        max_fulltext_papers=0,
        logger=logger,
    )

    bundle = result["evidence_bundle"]
    audit = bundle["retrieval_audit"]
    assert [paper["canonical_paper_id"] for paper in bundle["paper_registry"]] == ["W1", "W2", "W3"]
    assert audit["failed_card_extraction_paper_count"] == 1
    assert audit["failed_card_extraction_paper_ids"] == ["W2"]
    assert any("evidence_card_extraction_failed:W2:ValueError" in warning for warning in result["warnings"])
    assert any(
        record["event"] == "failed" and record["canonical_paper_id"] == "W2"
        for record in logger.records
        if record["stage"] == "evidence_card_extraction"
    )
    assert [
        record["event"]
        for record in logger.records
        if record["stage"] == "evidence_bundle"
    ] == ["started", "completed"]


def test_metadata_cannot_produce_cards_and_unqualified_field_is_downgraded() -> None:
    class OpenAlexMetadata:
        def search(self, query_task: Mapping[str, object], *, limit: int) -> list[dict]:
            return [_paper(level="metadata")]

    adapter = SurveyEvidenceAdapter(
        collector=SurveyEvidenceCollector(
            openalex_client=OpenAlexMetadata(),
            semantic_scholar_client=object(),
            fulltext_fetcher=lambda _: {},
        )
    )
    bundle = adapter.collect_and_extract(
        brief_id="brief-materials",
        evidence_plan=_plan(_task()),
        max_fulltext_papers=0,
    )["evidence_bundle"]
    ledger = {record["field_path"]: record for record in bundle["field_evidence_ledger"]}

    assert bundle["evidence_cards"] == []
    assert ledger["measurement_and_calibration"]["status"] == "design_assumption"
    report = CompletenessValidator().assess(
        {"known_unknowns": []},
        {"primary_template": "materials_chemical", "required_design_fields": ["measurement_and_calibration"]},
        candidate_design={
            "measurement_and_calibration": {"measurement_plan": "declared"},
            "field_statuses": {"measurement_and_calibration": "evidence_backed"},
        },
        evidence_bundle=bundle,
    )

    assessment = report["field_assessments"][0]
    assert assessment["status"] == "design_assumption"
    assert assessment["issue"] == "downgraded_without_qualifying_field_evidence"
