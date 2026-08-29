"""Tests for grounded ExperimentDesign paper screening and full-text selection."""

from __future__ import annotations

import json
from collections.abc import Mapping
from io import StringIO
from threading import Barrier

import pytest

from src.agents.experiment_design_agent import (
    DesignEvidencePaperScreener,
    DesignEvidencePaperScreeningError,
    SurveyEvidenceCollector,
)
from src.agents.experiment_design_agent.llm_json import RequiredJsonLLMError
from src.agents.experiment_design_agent.run_logging import ExperimentDesignRunLogger


SLOTS = ["mechanism", "measurement_calibration"]


def _paper(identifier: str, title: str, abstract: str = "") -> dict[str, object]:
    return {
        "canonical_paper_id": identifier,
        "title": title,
        "abstract": abstract,
        "abstract_source_location": "abstract:openalex",
        "provider_ids": {"openalex": identifier},
        "providers": ["openalex"],
        "query_task_ids": ["EDQ1"],
        "fulltext_candidates": [],
        "content_availability": "abstract" if abstract else "metadata",
    }


def _prompt_payload(prompt: str) -> dict[str, object]:
    return json.loads(prompt.split("INPUT_JSON:\n", 1)[1])


def _classification_llm(prompt: str, **kwargs: object) -> dict[str, object]:
    assert kwargs["response_format"] == {"type": "json_object"}
    payload = _prompt_payload(prompt)
    title = str(payload["TITLE"])
    abstract = str(payload["ABSTRACT"])
    assessments: list[dict[str, object]] = []
    for slot in payload["requested_slots"]:
        if slot == "mechanism" and "Mechanism" in title:
            relation = "direct_support"
            anchors = [{"source": "title", "text": "Mechanism"}]
        elif slot == "measurement_calibration" and "Calibration" in abstract:
            relation = "counterexample_or_boundary"
            anchors = [{"source": "abstract", "text": "Calibration boundary"}]
        elif slot == "measurement_calibration" and "Measurement" in title:
            relation = "limited_support"
            anchors = [{"source": "title", "text": "Measurement"}]
        else:
            relation = "not_relevant"
            anchors = []
        assessments.append(
            {
                "slot": slot,
                "relation": relation,
                "evidence_anchors": anchors,
                "rationale": "Screening classification based only on the supplied text.",
            }
        )
    return {"slot_assessments": assessments}


def test_screener_requires_json_llm_and_returns_grounded_slot_assessments() -> None:
    screener = DesignEvidencePaperScreener(fulltext_budget=15)
    paper = _paper(
        "W123",
        "Mechanism evidence",
        "Calibration boundary limits the measurement claim.",
    )

    screen = screener.screen(paper, requested_slots=SLOTS, llm_call=_classification_llm)

    assert screen["source_level"] == "title_abstract_screening_only"
    assert [item["relation"] for item in screen["slot_assessments"]] == [
        "direct_support",
        "counterexample_or_boundary",
    ]
    assert screen["fulltext_priority"]["score"] == 79
    with pytest.raises(RequiredJsonLLMError, match="LLM callback is required"):
        screener.screen(paper, requested_slots=SLOTS, llm_call=None)


def test_screener_rejects_unsupported_relation_without_exact_source_anchor() -> None:
    screener = DesignEvidencePaperScreener()

    def ungrounded_llm(_: str, **__: object) -> dict[str, object]:
        return {
            "slot_assessments": [
                {
                    "slot": "mechanism",
                    "relation": "direct_support",
                    "evidence_anchors": [{"source": "abstract", "text": "invented support"}],
                    "rationale": "The paper seems relevant.",
                },
                {
                    "slot": "measurement_calibration",
                    "relation": "not_relevant",
                    "evidence_anchors": [],
                    "rationale": "No stated calibration contribution.",
                },
            ]
        }

    with pytest.raises(DesignEvidencePaperScreeningError, match="anchor is not grounded"):
        screener.screen(
            _paper("W123", "Mechanism evidence", "No supporting phrase."),
            requested_slots=SLOTS,
            llm_call=ungrounded_llm,
        )


def test_slot_diverse_selection_precedes_priority_fill() -> None:
    screener = DesignEvidencePaperScreener(fulltext_budget=2)
    papers = [
        _paper("W-mechanism", "Mechanism evidence"),
        _paper("W-measurement", "Measurement evidence"),
        _paper("W-mechanism-secondary", "Mechanism evidence"),
    ]

    screened, audit = screener.screen_and_select(
        papers,
        requested_slots=SLOTS,
        llm_call=_classification_llm,
        max_fulltext_papers=2,
    )

    assert audit["selected_paper_ids"] == ["W-mechanism", "W-measurement"]
    assert audit["selected_by_slot"] == {
        "mechanism": "W-mechanism",
        "measurement_calibration": "W-measurement",
    }
    priorities = {
        paper["canonical_paper_id"]: paper["design_evidence_screening"]["fulltext_priority"]
        for paper in screened
    }
    assert priorities["W-mechanism"]["selection_reason"] == "slot_coverage"
    assert priorities["W-measurement"]["selected_for_fulltext"] is True
    assert priorities["W-mechanism-secondary"]["selection_reason"] == "fulltext_budget_exhausted"


def test_fulltext_budget_uses_grounded_priority_score_not_discovery_order() -> None:
    screener = DesignEvidencePaperScreener(fulltext_budget=1)

    def ranked_llm(prompt: str, **kwargs: object) -> dict[str, object]:
        del kwargs
        payload = _prompt_payload(prompt)
        is_direct = "Direct" in str(payload["TITLE"])
        return {
            "slot_assessments": [
                {
                    "slot": "mechanism",
                    "relation": "direct_support" if is_direct else "limited_support",
                    "evidence_anchors": [
                        {"source": "title", "text": "Direct" if is_direct else "Limited"}
                    ],
                    "rationale": "Classification is limited to the supplied title anchor.",
                }
            ]
        }

    screened, audit = screener.screen_and_select(
        [
            _paper("W-returned-first", "Limited mechanism evidence"),
            _paper("W-returned-second", "Direct mechanism evidence"),
        ],
        requested_slots=["mechanism"],
        llm_call=ranked_llm,
    )

    scores = {
        paper["canonical_paper_id"]: paper["design_evidence_screening"]["fulltext_priority"]["score"]
        for paper in screened
    }
    assert scores["W-returned-second"] > scores["W-returned-first"]
    assert audit["selected_paper_ids"] == ["W-returned-second"]


def test_background_screening_never_consumes_the_fulltext_budget() -> None:
    screener = DesignEvidencePaperScreener(fulltext_budget=2)

    def background_llm(prompt: str, **kwargs: object) -> dict[str, object]:
        del kwargs
        payload = _prompt_payload(prompt)
        return {
            "slot_assessments": [
                {
                    "slot": slot,
                    "relation": "background",
                    "evidence_anchors": [{"source": "title", "text": "Background"}],
                    "rationale": "The paper provides context but no substantive design support.",
                }
                for slot in payload["requested_slots"]
            ]
        }

    screened, audit = screener.screen_and_select(
        [_paper("W-background", "Background context")],
        requested_slots=SLOTS,
        llm_call=background_llm,
    )

    assert audit["eligible_for_fulltext_count"] == 0
    assert audit["selected_paper_ids"] == []
    assert screened[0]["design_evidence_screening"]["fulltext_priority"]["selection_reason"] == (
        "background_or_no_grounded_design_relevance"
    )


def test_screening_logs_paper_lifecycle_and_budget_without_source_text() -> None:
    logger = ExperimentDesignRunLogger("paper-screening-test", console_stream=StringIO())
    screener = DesignEvidencePaperScreener(fulltext_budget=1)
    paper = _paper("W-log", "Mechanism evidence", "Sensitive abstract evidence.")

    _, audit = screener.screen_and_select(
        [paper],
        requested_slots=SLOTS,
        llm_call=_classification_llm,
        logger=logger,
    )

    events = [record for record in logger.records if record["stage"] == "evidence_screening"]
    assert [event["event"] for event in events] == [
        "paper_screening_started",
        "paper_screening_completed",
        "fulltext_budget_selected",
    ]
    assert events[1]["fulltext_priority_score"] > 0
    assert events[2]["selected_paper_ids"] == audit["selected_paper_ids"]
    assert "Sensitive abstract evidence." not in json.dumps(events, ensure_ascii=False)


def test_screening_uses_bounded_parallel_workers_and_restores_input_order() -> None:
    screener = DesignEvidencePaperScreener(fulltext_budget=2, parallel_workers=2)
    barrier = Barrier(2)
    calls: list[str] = []

    def concurrent_llm(prompt: str, **kwargs: object) -> dict[str, object]:
        assert kwargs["response_format"] == {"type": "json_object"}
        payload = _prompt_payload(prompt)
        calls.append(str(payload["canonical_paper_id"]))
        barrier.wait(timeout=2)
        return {
            "slot_assessments": [
                {
                    "slot": "mechanism",
                    "relation": "direct_support",
                    "evidence_anchors": [{"source": "title", "text": "Mechanism"}],
                    "rationale": "Classification is grounded in the supplied title.",
                }
            ]
        }

    logger = ExperimentDesignRunLogger("parallel-screening-test", console_stream=StringIO())
    screened, audit = screener.screen_and_select(
        [
            _paper("W-first", "Mechanism first"),
            _paper("W-second", "Mechanism second"),
        ],
        requested_slots=["mechanism"],
        llm_call=concurrent_llm,
        logger=logger,
    )

    assert sorted(calls) == ["W-first", "W-second"]
    assert [paper["canonical_paper_id"] for paper in screened] == ["W-first", "W-second"]
    lifecycle = [
        record["event"]
        for record in logger.records
        if record["stage"] == "evidence_screening"
    ]
    assert lifecycle[:2] == ["paper_screening_started", "paper_screening_started"]
    assert lifecycle.count("paper_screening_completed") == 2
    assert audit["selected_paper_ids"] == ["W-first", "W-second"]


def test_one_failed_paper_does_not_abort_other_screening_tasks() -> None:
    screener = DesignEvidencePaperScreener(fulltext_budget=1, parallel_workers=2)

    def one_bad_llm(prompt: str, **kwargs: object) -> object:
        payload = _prompt_payload(prompt)
        if payload["canonical_paper_id"] == "W-bad":
            return "not a complete JSON object"
        return _classification_llm(prompt, **kwargs)

    logger = ExperimentDesignRunLogger("isolated-screening-failure", console_stream=StringIO())
    screened, audit = screener.screen_and_select(
        [_paper("W-bad", "Broken response"), _paper("W-good", "Mechanism evidence")],
        requested_slots=["mechanism"],
        llm_call=one_bad_llm,
        logger=logger,
    )

    assert [paper["canonical_paper_id"] for paper in screened] == ["W-good"]
    assert audit["selected_paper_ids"] == ["W-good"]
    assert audit["failed_screening_paper_count"] == 1
    assert audit["failed_screening_paper_ids"] == ["W-bad"]
    failure = audit["failed_screens_by_paper"]["W-bad"]
    assert failure["error_type"] == "RequiredJsonLLMError"
    assert any(
        record["event"] == "paper_screening_failed"
        and record["canonical_paper_id"] == "W-bad"
        and record["continue_on_failure"] is True
        for record in logger.records
    )
    assert any(
        record["event"] == "paper_screening_completed"
        and record["canonical_paper_id"] == "W-good"
        for record in logger.records
    )


def test_collector_from_config_routes_parallel_workers_to_paper_screener() -> None:
    collector = SurveyEvidenceCollector.from_config(
        {
            "experiment_design": {
                "retrieval": {
                    "paper_screening": {
                        "fulltext_budget": 15,
                        "max_candidates_before_llm": 32,
                        "parallel_workers": 3,
                    },
                    "fulltext": {},
                }
            }
        }
    )

    assert collector.paper_screener.parallel_workers == 3
    assert collector.max_screening_candidates == 32


def test_collector_screens_all_candidates_then_acquires_only_budgeted_fifteen() -> None:
    papers = [
        _paper(f"W{index:03}", "Mechanism evidence", "Abstract support.")
        for index in range(1, 17)
    ]

    class OpenAlex:
        def search(self, task: Mapping[str, object], *, limit: int) -> list[dict[str, object]]:
            assert task["task_id"] == "EDQ1"
            assert limit == 20
            return list(papers)

    class FulltextAcquirer:
        max_papers = 15

        def __init__(self) -> None:
            self.acquired: list[str] = []

        def acquire(self, paper: Mapping[str, object], *, logger: object | None = None) -> dict[str, object]:
            del logger
            paper_id = str(paper["canonical_paper_id"])
            self.acquired.append(paper_id)
            return {
                "fulltext": f"Parsed markdown for {paper_id}.",
                "fulltext_source_location": f"fulltext:survey_pdf:{paper_id}:markdown",
                "content_availability": "fulltext",
                "fulltext_acquisition": {"status": "parsed"},
            }

    acquirer = FulltextAcquirer()
    collector = SurveyEvidenceCollector(
        openalex_client=OpenAlex(),
        semantic_scholar_client=object(),
        fulltext_fetcher=acquirer,
        paper_screener=DesignEvidencePaperScreener(fulltext_budget=15),
    )

    collection = collector.collect(
        {
            "queries": [
                {
                    "task_id": "EDQ1",
                    "slot": "mechanism",
                    "query": "mechanism",
                    "openalex_field_filter": [],
                }
            ]
        },
        max_results_per_query=20,
        max_fulltext_papers=20,
        screener_llm_call=_classification_llm,
    )

    screening = collection["paper_screening"]
    assert screening["screened_paper_count"] == 16
    assert screening["fulltext_budget"] == 15
    assert len(screening["selected_paper_ids"]) == 15
    assert acquirer.acquired == screening["selected_paper_ids"]
    assert sum(paper["content_availability"] == "fulltext" for paper in collection["papers"]) == 15
    omitted = next(paper for paper in collection["papers"] if paper["canonical_paper_id"] == "W016")
    assert omitted["design_evidence_screening"]["fulltext_priority"]["selection_reason"] == "fulltext_budget_exhausted"
