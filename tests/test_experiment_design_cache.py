"""Focused regression tests for reproducible ExperimentDesign cache behavior."""

from __future__ import annotations

from pathlib import Path

from src.agents.experiment_design_agent.cache import ExperimentDesignCache
from src.agents.experiment_design_agent.evidence_planner import EvidenceRetrievalPlanner
from src.agents.experiment_design_agent.fulltext_acquisition import (
    SurveyCompatibleFulltextAcquirer,
)
from src.agents.experiment_design_agent.survey_evidence import (
    SurveyEvidenceAdapter,
    SurveyEvidenceCollector,
)


def _cache(tmp_path: Path, *, mode: str = "read_write") -> ExperimentDesignCache:
    return ExperimentDesignCache(
        {"enabled": True, "mode": mode, "root": str(tmp_path / "experiment-design-cache")}
    )


def _brief(brief_id: str = "brief-cache") -> dict[str, object]:
    return {
        "brief_id": brief_id,
        "topic": "Surface measurement calibration",
        "selected_direction": {
            "title": "Surface measurement calibration",
            "central_hypothesis": "A declared transformation changes a declared observable.",
            "mechanism_or_relation": "Calibration distinguishes the proposed interface mechanism.",
        },
        "research_object": {"description": "A declared material interface."},
        "intervention_or_transformation": "A declared material transformation.",
        "discriminating_observations": ["A calibrated interface measurement."],
        "boundary_conditions": ["A declared operating regime."],
    }


def _routing() -> dict[str, object]:
    return {"primary_template": "measurement_study"}


def _planner_payload(brief: dict[str, object], routing: dict[str, object]) -> dict[str, object]:
    baseline = EvidenceRetrievalPlanner().degraded_plan(brief, routing)
    return {
        "queries": [
            {
                key: task[key]
                for key in ("slot", "objective", "keywords", "query_variants", "evidence_needed")
            }
            for task in baseline["queries"]
        ]
    }


def _collection_plan() -> dict[str, object]:
    return {
        "queries": [
            {
                "task_id": "EDQ1",
                "slot": "measurement_calibration",
                "query": "surface calibration",
            }
        ]
    }


def _paper(identifier: str = "W-cache") -> dict[str, object]:
    return {
        "canonical_paper_id": identifier,
        "title": "Traceable calibration of an interface measurement",
        "abstract": "The supplied abstract describes a calibration procedure for an interface measurement.",
        "authors": ["Ada Analyst"],
        "year": 2025,
        "venue": "Journal of Traceable Measurement",
        "url": "https://doi.org/10.1000/cache",
        "provider_ids": {"openalex": identifier},
        "providers": ["openalex"],
        "query_task_ids": ["EDQ1"],
        "query_slots": ["measurement_calibration"],
        "abstract_source_location": "abstract:openalex",
        "fulltext_candidates": [],
        "content_availability": "abstract",
    }


class _OpenAlex:
    def __init__(self, papers: list[dict[str, object]] | None = None) -> None:
        self.papers = papers or [_paper()]
        self.calls = 0

    def search(self, _task: object, *, limit: int) -> list[dict[str, object]]:
        self.calls += 1
        assert limit > 0
        return [dict(paper) for paper in self.papers]


class _FailingOpenAlex:
    def __init__(self) -> None:
        self.calls = 0

    def search(self, _task: object, *, limit: int) -> list[dict[str, object]]:
        self.calls += 1
        raise AssertionError("a cache hit must not contact OpenAlex")


class _NoCardsExtractor:
    def __init__(self, *, fail: bool = False) -> None:
        self.calls = 0
        self.fail = fail

    def extract(self, _paper: object, **_kwargs: object) -> tuple[list[dict[str, object]], list[str]]:
        self.calls += 1
        if self.fail:
            raise AssertionError("an evidence-card cache hit must not call the extractor")
        return [], ["no_card_needed_for_cache_test"]


class _PdfResponse:
    def __init__(self, content: bytes, url: str) -> None:
        self.status_code = 200
        self.content = content
        self.url = url
        self.headers = {"Content-Type": "application/pdf"}

    def iter_content(self, *, chunk_size: int) -> list[bytes]:
        del chunk_size
        return [self.content]

    def close(self) -> None:
        return None


class _PdfSession:
    def __init__(self, responses: dict[str, _PdfResponse]) -> None:
        self.responses = responses
        self.calls: list[str] = []

    def get(self, url: str, **_kwargs: object) -> _PdfResponse:
        self.calls.append(url)
        return self.responses[url]


def _fulltext_config(tmp_path: Path) -> dict[str, object]:
    return {
        "enabled": True,
        "cache_dir": str(tmp_path / "download-cache"),
        "max_candidates_per_paper": 2,
        "max_pdf_bytes": 50_000,
        "timeout_seconds": 5,
        "per_host_concurrency": 1,
        "parser_backend": "survey_mineru",
        "parser_batch_size": 1,
    }


def _pdf_paper(identifier: str, url: str) -> dict[str, object]:
    return {
        "canonical_paper_id": identifier,
        "title": f"PDF cache paper {identifier}",
        "abstract": "An abstract is available until parsing completes.",
        "fulltext_candidates": [
            {"kind": "pdf", "url": url, "source": "openalex.best_oa_location"}
        ],
    }


def _valid_pdf(path: str) -> bool:
    return Path(path).read_bytes().startswith(b"%PDF-")


def test_content_addressed_snapshots_keep_history_and_read_only_does_not_write(tmp_path: Path) -> None:
    cache = _cache(tmp_path)
    identity = {"paper": "W1"}
    run_id = cache.begin_run("brief-cache")

    first_snapshot = cache.write("evidence_cards", identity, {"value": "first"}, run_id=run_id)
    second_snapshot = cache.write("evidence_cards", identity, {"value": "second"}, run_id=run_id)

    assert first_snapshot and second_snapshot and first_snapshot != second_snapshot
    assert cache.read("evidence_cards", identity, run_id=run_id) == {"value": "second"}
    assert (cache.root / "objects" / "evidence_cards" / f"{first_snapshot}.json").is_file()
    assert (cache.root / "objects" / "evidence_cards" / f"{second_snapshot}.json").is_file()
    assert {record["action"] for record in cache.run_manifest(run_id)["records"]} >= {
        "written",
        "hit",
    }

    offline_root = tmp_path / "offline-cache"
    read_only = ExperimentDesignCache(
        {"enabled": True, "mode": "read_only", "root": str(offline_root)}
    )
    offline_run = read_only.begin_run("brief-offline")

    assert offline_run
    assert read_only.read("query_plans", {"brief": "missing"}, run_id=offline_run) is None
    assert read_only.write("query_plans", {"brief": "missing"}, {"queries": []}, run_id=offline_run) == ""
    assert not offline_root.exists()


def test_query_plan_cache_replays_without_calling_the_llm_and_degrades_offline(tmp_path: Path) -> None:
    cache = _cache(tmp_path)
    brief = _brief()
    routing = _routing()
    llm_calls = 0

    def planner_llm(_prompt: str, **_kwargs: object) -> dict[str, object]:
        nonlocal llm_calls
        llm_calls += 1
        return _planner_payload(brief, routing)

    first = EvidenceRetrievalPlanner(cache=cache).plan(
        brief,
        routing,
        llm_call=planner_llm,
        cache_run_id=cache.begin_run(brief["brief_id"]),
    )
    second = EvidenceRetrievalPlanner(cache=cache).plan(
        brief,
        routing,
        llm_call=lambda _prompt, **_kwargs: (_ for _ in ()).throw(AssertionError("cache miss")),
    )

    assert llm_calls == 1
    assert second == first
    assert second["llm_used"] is True

    offline = ExperimentDesignCache(
        {"enabled": True, "mode": "read_only", "root": str(cache.root)}
    )
    replayed = EvidenceRetrievalPlanner(cache=offline).plan(
        brief,
        routing,
        llm_call=lambda _prompt, **_kwargs: (_ for _ in ()).throw(AssertionError("cache miss")),
    )
    missing = EvidenceRetrievalPlanner(cache=offline).plan(
        _brief("brief-missing"),
        routing,
        llm_call=lambda _prompt, **_kwargs: (_ for _ in ()).throw(AssertionError("offline must not call LLM")),
    )

    assert replayed == first
    assert missing["llm_used"] is False
    assert "read-only cache mode" in missing["warnings"][0]


def test_retrieval_collection_cache_replays_and_read_only_skips_provider(tmp_path: Path) -> None:
    cache = _cache(tmp_path)
    source = _OpenAlex()
    first = SurveyEvidenceCollector(
        openalex_client=source,
        semantic_scholar_client=object(),
        cache=cache,
    ).collect(_collection_plan(), max_fulltext_papers=0, cache_run_id=cache.begin_run("brief-cache"))
    blocked = _FailingOpenAlex()
    replayed = SurveyEvidenceCollector(
        openalex_client=blocked,
        semantic_scholar_client=object(),
        cache=ExperimentDesignCache({"enabled": True, "root": str(cache.root)}),
    ).collect(_collection_plan(), max_fulltext_papers=0)

    assert source.calls == 1
    assert blocked.calls == 0
    assert replayed == first

    offline = _cache(tmp_path / "offline", mode="read_only")
    offline_provider = _FailingOpenAlex()
    degraded = SurveyEvidenceCollector(
        openalex_client=offline_provider,
        semantic_scholar_client=object(),
        cache=offline,
    ).collect(_collection_plan(), max_fulltext_papers=0, cache_run_id=offline.begin_run("brief-offline"))

    assert offline_provider.calls == 0
    assert degraded["papers"] == []
    assert degraded["provider_runs"][0]["status"] == "CACHE_MISS"


def test_evidence_card_cache_replays_per_paper_without_disabling_parallel_flow(tmp_path: Path) -> None:
    cache = _cache(tmp_path)
    source = _OpenAlex()
    extractor = _NoCardsExtractor()
    first_adapter = SurveyEvidenceAdapter(
        collector=SurveyEvidenceCollector(
            openalex_client=source,
            semantic_scholar_client=object(),
            cache=cache,
        ),
        card_extractor=extractor,
        cache=cache,
    )
    first = first_adapter.collect_and_extract(
        brief_id="brief-cache",
        evidence_plan=_collection_plan(),
        max_fulltext_papers=0,
    )
    manifest_namespaces = {
        record["namespace"] for record in first["cache_manifest"]["records"]
    }

    blocked = _FailingOpenAlex()
    replay_extractor = _NoCardsExtractor(fail=True)
    second = SurveyEvidenceAdapter(
        collector=SurveyEvidenceCollector(
            openalex_client=blocked,
            semantic_scholar_client=object(),
            cache=ExperimentDesignCache({"enabled": True, "root": str(cache.root)}),
        ),
        card_extractor=replay_extractor,
    ).collect_and_extract(
        brief_id="brief-cache",
        evidence_plan=_collection_plan(),
        max_fulltext_papers=0,
    )

    assert source.calls == 1
    assert extractor.calls == 1
    assert blocked.calls == 0
    assert replay_extractor.calls == 0
    assert second["warnings"] == ["no_card_needed_for_cache_test"]
    assert {"retrieval_collections", "evidence_cards"} <= manifest_namespaces


def test_pdf_markdown_cache_reuses_identical_pdf_and_read_only_blocks_download(tmp_path: Path) -> None:
    cache = _cache(tmp_path)
    first_url = "https://repository.example/first.pdf"
    second_url = "https://repository.example/second.pdf"
    pdf_bytes = b"%PDF-1.7\n" + b"cache" * 1024
    parser_calls = 0

    def parser(paths: list[Path], output_dir: Path) -> None:
        nonlocal parser_calls
        parser_calls += 1
        pdf_path = paths[0]
        markdown_path = output_dir / pdf_path.stem / "auto" / f"{pdf_path.stem}.md"
        markdown_path.parent.mkdir(parents=True, exist_ok=True)
        markdown_path.write_text("# Cached parsed PDF", encoding="utf-8")

    session = _PdfSession(
        {
            first_url: _PdfResponse(pdf_bytes, first_url),
            second_url: _PdfResponse(pdf_bytes, second_url),
        }
    )
    run_id = cache.begin_run("brief-pdf")
    first_acquirer = SurveyCompatibleFulltextAcquirer(
        _fulltext_config(tmp_path),
        session=session,
        pdf_validator=_valid_pdf,
        pdf_parser=parser,
        cache=cache,
    )
    first = first_acquirer.acquire(_pdf_paper("W-pdf-1", first_url), cache_run_id=run_id)
    second = SurveyCompatibleFulltextAcquirer(
        _fulltext_config(tmp_path),
        session=session,
        pdf_validator=_valid_pdf,
        pdf_parser=parser,
        cache=cache,
    ).acquire(_pdf_paper("W-pdf-2", second_url), cache_run_id=run_id)

    assert first["content_availability"] == "fulltext"
    assert second["content_availability"] == "fulltext"
    assert second["fulltext_acquisition"]["parser"]["status"] == "cache_hit"
    assert parser_calls == 1
    assert session.calls == [first_url, second_url]

    offline_session = _PdfSession({first_url: _PdfResponse(pdf_bytes, first_url)})
    offline = _cache(tmp_path / "offline", mode="read_only")
    offline_result = SurveyCompatibleFulltextAcquirer(
        _fulltext_config(tmp_path / "offline"),
        session=offline_session,
        pdf_validator=_valid_pdf,
        pdf_parser=parser,
        cache=offline,
    ).acquire(_pdf_paper("W-offline", first_url), cache_run_id=offline.begin_run("brief-offline"))

    assert offline_session.calls == []
    assert offline_result["fulltext_acquisition"]["status"] == "cache_miss_read_only"
