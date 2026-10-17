from __future__ import annotations

import json
from pathlib import Path

import pytest

import src.webapp.parameter_search_service as parameter_search_service
from src.pipeline.science_run import atomic_write_json, initialize_science_run
from src.webapp.jobs import JobCancelled


JOB_ID = "psearch-0123456789abcdef0123"


def _search_fixture(tmp_path: Path) -> tuple[Path, Path, dict[str, object]]:
    config_path = Path(__file__).resolve().parents[1] / "src" / "config" / "default.yaml"
    paths, _metadata, _state = initialize_science_run(
        output_root=tmp_path / "science-runs",
        topic="parameter search cancellation",
        config_path=config_path,
        immutable_options={"discipline_ids": ["25"]},
        run_id="run-parameter-search",
    )
    job_path = paths.run_dir / "quantitative" / "Q1" / "parameter_evidence" / "v0" / "interactive_search" / f"{JOB_ID}.json"
    atomic_write_json(
        job_path,
        {
            "schema_version": "parameter_search_job_v1",
            "job_id": JOB_ID,
            "run_id": "run-parameter-search",
            "idea_id": "Q1",
            "version": 0,
            "parameter_id": "velocity",
            "query": "kilonova velocity",
            "providers": ["openalex"],
            "limit": 10,
            "status": "QUEUED",
            "provider_runs": [],
            "papers": [],
        },
    )
    descriptor = {
        "type": "parameter_search",
        "job_id": JOB_ID,
        "idea_id": "Q1",
        "version": 0,
        "parameter_id": "velocity",
        "query": "kilonova velocity",
        "providers": ["openalex"],
        "limit": 10,
    }
    return paths.run_dir, job_path, descriptor


def test_parameter_search_cancellation_is_not_provider_failure(tmp_path, monkeypatch) -> None:
    run_dir, job_path, descriptor = _search_fixture(tmp_path)

    class FakeProviders:
        def __init__(self, _settings) -> None:
            pass

        def search_openalex(self, _query):
            return []

        def search_anysearch(self, _query):
            return []

    monkeypatch.setattr(parameter_search_service, "AcademicMetadataProviders", FakeProviders)

    def checkpoint() -> None:
        raise JobCancelled("cancel requested")

    service = parameter_search_service.ParameterSearchService(
        config_path=Path(__file__).resolve().parents[1] / "src" / "config" / "default.yaml",
        submit_task=lambda **_kwargs: None,
    )
    with pytest.raises(JobCancelled):
        service._execute(
            run_dir=run_dir,
            path=job_path,
            checkpoint=checkpoint,
            **{key: value for key, value in descriptor.items() if key != "type"},
        )

    payload = json.loads(job_path.read_text(encoding="utf-8"))
    assert payload["status"] == "CANCELLED"
    events = run_dir.joinpath("events.jsonl").read_text(encoding="utf-8")
    assert "PARAMETER_SEARCH_CANCELLED" in events
    assert "PARAMETER_SEARCH_FAILED" not in events


def test_post_completion_cancellation_does_not_rewrite_search(tmp_path, monkeypatch) -> None:
    run_dir, job_path, descriptor = _search_fixture(tmp_path)

    class FakeProviders:
        def __init__(self, _settings) -> None:
            pass

        def search_openalex(self, _query):
            return [{"provider": "openalex", "provider_paper_id": "W1", "title": "A paper"}]

        def search_anysearch(self, _query):
            return []

    monkeypatch.setattr(parameter_search_service, "AcademicMetadataProviders", FakeProviders)
    calls = 0

    def checkpoint() -> None:
        nonlocal calls
        calls += 1
        if calls >= 3:
            raise JobCancelled("cancel requested after completion")

    service = parameter_search_service.ParameterSearchService(
        config_path=Path(__file__).resolve().parents[1] / "src" / "config" / "default.yaml",
        submit_task=lambda **_kwargs: None,
    )
    with pytest.raises(JobCancelled):
        service.execute_descriptor(run_dir=run_dir, descriptor=descriptor, checkpoint=checkpoint)

    payload = json.loads(job_path.read_text(encoding="utf-8"))
    assert payload["status"] == "COMPLETED"
    events = run_dir.joinpath("events.jsonl").read_text(encoding="utf-8")
    assert "PARAMETER_SEARCH_COMPLETED" in events
    assert "PARAMETER_SEARCH_CANCELLED" not in events
