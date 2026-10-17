from __future__ import annotations

from pathlib import Path
import time
import json

import pytest

from src.webapp.api import create_app
from src.webapp.feature_schemas import FigureJobCreate, PolishJobCreate, TranslationJobCreate
from src.webapp.jobs.models import JobExecutionResult
from fastapi.testclient import TestClient


def test_feature_request_schemas_enforce_route_authorization() -> None:
    with pytest.raises(ValueError, match="exactly one"):
        PolishJobCreate(text="draft", input_file_id="file-abc")
    with pytest.raises(ValueError, match="image_generation_authorized"):
        FigureJobCreate(
            input_file_ids=["file-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"],
            figure_claim="A supported scientific comparison",
            variable_mapping={"x": "condition", "y": "response"},
            use_ai_schematic=True,
            prompt_profile="figure-ai-schematic",
        )
    with pytest.raises(ValueError, match="page_start"):
        TranslationJobCreate(
            input_file_id="file-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            page_start=3,
            page_end=1,
        )


def test_feature_job_creation_freezes_file_and_prompt_manifests(tmp_path: Path) -> None:
    app = create_app(run_root=tmp_path / "science-runs", serve_frontend=False)
    app.state.job_runner.submit = lambda _job_id: None
    client = TestClient(app)
    uploaded = client.post(
        "/api/files",
        files={"file": ("data.csv", b"condition,response\na,1\nb,2\n", "text/csv")},
    )
    assert uploaded.status_code == 201, uploaded.text
    file_id = uploaded.json()["file_id"]

    created = client.post(
        "/api/figure/jobs",
        json={
            "input_file_ids": [file_id],
            "figure_claim": "Response changes across the supplied conditions",
            "chart_type": "line",
            "variable_mapping": {"x": "condition", "y": "response"},
            "model_name": "qwen3.8-flash",
            "idempotency_key": "figure-once",
        },
    )
    assert created.status_code == 202, created.text
    job_id = created.json()["job_id"]
    manifest = app.state.job_store.job_directory(job_id) / "input.json"
    payload = manifest.read_text(encoding="utf-8")
    assert file_id in payload
    assert "figure-python-default" in payload
    assert "qwen3.8-flash" in payload

    same = client.post(
        "/api/figure/jobs",
        json={
            "input_file_ids": [file_id],
            "figure_claim": "Response changes across the supplied conditions",
            "chart_type": "line",
            "variable_mapping": {"x": "condition", "y": "response"},
            "model_name": "qwen3.8-flash",
            "idempotency_key": "figure-once",
        },
    )
    assert same.status_code == 202
    assert same.json()["job_id"] == job_id


def test_review_endpoint_accepts_waiting_job(tmp_path: Path) -> None:
    app = create_app(run_root=tmp_path / "science-runs", serve_frontend=False)
    store = app.state.job_store
    job = store.create(
        kind="polish",
        input_manifest_id="manifest-1",
        input_manifest_sha256="a" * 64,
        request_hash="b" * 64,
    )
    claimed = store.claim(job.job_id, lease_owner="test-worker")
    assert claimed is not None
    store.transition(job.job_id, "WAITING_FOR_REVIEW", lease_owner="test-worker", progress=100)

    response = TestClient(app).post(f"/api/jobs/{job.job_id}/review", json={"accepted": True})
    assert response.status_code == 202
    assert response.json()["status"] == "SUCCEEDED"


def test_python_figure_worker_renders_deterministic_source(tmp_path: Path) -> None:
    app = create_app(run_root=tmp_path / "science-runs", serve_frontend=False)
    client = TestClient(app)
    uploaded = client.post(
        "/api/files",
        files={"file": ("data.csv", b"condition,response\na,1\nb,2\n", "text/csv")},
    )
    file_id = uploaded.json()["file_id"]
    created = client.post(
        "/api/figure/jobs",
        json={
            "input_file_ids": [file_id],
            "figure_claim": "Response changes across the supplied conditions",
            "chart_type": "line",
            "variable_mapping": {"x": "condition", "y": "response"},
            "output_formats": ["png", "pdf", "source", "qa"],
        },
    )
    assert created.status_code == 202, created.text
    job_id = created.json()["job_id"]
    deadline = time.time() + 20
    status = "QUEUED"
    while time.time() < deadline:
        status = app.state.job_store.get(job_id).status
        if status in {"WAITING_FOR_REVIEW", "FAILED"}:
            break
        time.sleep(0.05)
    assert status == "WAITING_FOR_REVIEW", app.state.job_store.get(job_id).error_message
    artifacts = client.get(f"/api/jobs/{job_id}/artifacts")
    assert artifacts.status_code == 200
    assert {item["role"] for item in artifacts.json()} >= {"figure_png", "figure_pdf", "figure_source", "figure_qa"}


def test_model_figure_plan_is_validated_before_trusted_rendering(tmp_path: Path, monkeypatch):
    from src.webapp.figure_contracts import FigureSpec

    calls = []

    def build(**settings):
        def invoke(messages, **_kwargs):
            calls.append(settings)
            message = json.loads(messages[1]["content"])
            data = message["input_manifest"]
            assert data["table"]["row_count"] == 2
            assert "source_code" not in data
            assert message["task_context"]["figure_style"] == {"width_mm": 200.0}
            return FigureSpec(chart_type="bar", variable_mapping={"x": "condition", "y": "response"},
                              x_label="Condition", y_label="Response (mg)").model_dump()
        return invoke

    monkeypatch.setattr("src.webapp.figure_planner.build_web_json_llm_call", build)
    app = create_app(run_root=tmp_path / "science-runs", serve_frontend=False)
    app.state.job_runner.submit = lambda _job_id: None
    client = TestClient(app)
    uploaded = client.post("/api/files", files={"file": ("data.csv", b"condition,response\na,1\nb,2\n", "text/csv")})
    created = client.post("/api/figure/jobs", json={
        "input_file_ids": [uploaded.json()["file_id"]], "figure_claim": "Compare measured responses.",
        "variable_mapping": {"x": "condition", "y": "response"}, "model_name": "qwen3.8-max",
        "figure_style": {"width_mm": 200},
        "output_formats": ["png", "source", "qa"],
    })
    job_id = created.json()["job_id"]
    app.state.job_runner._execute(job_id)
    result = app.state.job_store.get(job_id)
    assert result.status == "WAITING_FOR_REVIEW", result.error_message
    assert len(calls) == 1 and calls[0]["model"] == "qwen3.8-max"
    artifacts = client.get(f"/api/jobs/{job_id}/artifacts").json()
    specification = next(item for item in artifacts if item["role"] == "figure_spec")
    downloaded = client.get(f"/api/figure/jobs/{job_id}/artifacts/{specification['artifact_id']}")
    assert downloaded.json()["chart_type"] == "bar"
    assert downloaded.json()["y_label"] == "Response (mg)"
    assert downloaded.json()["width_mm"] == 200
    app.state.job_runner.shutdown()


def test_figure_planner_cannot_invent_or_rebind_columns(tmp_path: Path, monkeypatch):
    from src.webapp.figure_contracts import FigureSpec

    monkeypatch.setattr("src.webapp.figure_planner.build_web_json_llm_call", lambda **_settings: lambda *_args, **_kwargs:
                        FigureSpec(chart_type="line", variable_mapping={"x": "condition", "y": "invented"}).model_dump())
    app = create_app(run_root=tmp_path / "science-runs", serve_frontend=False)
    app.state.job_runner.submit = lambda _job_id: None
    client = TestClient(app)
    uploaded = client.post("/api/files", files={"file": ("data.csv", b"condition,response\na,1\nb,2\n", "text/csv")})
    created = client.post("/api/figure/jobs", json={
        "input_file_ids": [uploaded.json()["file_id"]], "figure_claim": "Compare measured responses.",
        "variable_mapping": {"x": "condition", "y": "response"},
    })
    job_id = created.json()["job_id"]
    app.state.job_runner._execute(job_id)
    assert app.state.job_store.get(job_id).status == "FAILED"
    assert client.get(f"/api/jobs/{job_id}/artifacts").json() == []
    assert not list((app.state.job_store.job_directory(job_id) / "checkpoints").glob("*.json"))
    app.state.job_runner.shutdown()


def test_explicit_figure_reject_applies_style_without_planner_call(tmp_path: Path, monkeypatch):
    planner_calls = []

    def unexpected_planner_call(**_settings):
        planner_calls.append(_settings)
        raise AssertionError("explicit figure revisions must not call the planner")

    monkeypatch.setattr("src.webapp.figure_planner.build_web_json_llm_call", unexpected_planner_call)
    app = create_app(run_root=tmp_path / "science-runs", serve_frontend=False)
    app.state.job_runner.submit = lambda _job_id: None
    client = TestClient(app)
    uploaded = client.post(
        "/api/files",
        files={"file": ("data.csv", b"condition,response\na,1\nb,2\n", "text/csv")},
    )
    created = client.post("/api/figure/jobs", json={
        "input_file_ids": [uploaded.json()["file_id"]], "figure_claim": "Compare measured responses.",
        "chart_type": "line", "planning_mode": "explicit",
        "variable_mapping": {"x": "condition", "y": "response"},
        "figure_style": {"palette": "blue", "width_mm": 190},
        "output_formats": ["png", "source", "qa"],
    })
    assert created.status_code == 202, created.text
    job_id = created.json()["job_id"]
    app.state.job_runner._execute(job_id)
    assert app.state.job_store.get(job_id).status == "WAITING_FOR_REVIEW"

    missing_style = client.post(f"/api/figure/jobs/{job_id}/actions", json={
        "type": "reject", "notes": "Use a neutral palette and a clearer x label.",
    })
    assert missing_style.status_code == 409
    assert app.state.job_store.get(job_id).revision == 1
    for unchanged_style in ({}, {"palette": "blue"}):
        response = client.post(f"/api/figure/jobs/{job_id}/actions", json={
            "type": "reject", "notes": "Use a different style.", "figure_style": unchanged_style,
        })
        assert response.status_code == 409
    assert not (app.state.job_store.job_directory(job_id) / "review.json").exists()

    revised = client.post(f"/api/figure/jobs/{job_id}/actions", json={
        "type": "reject", "notes": "Use a neutral palette and a clearer x label.",
        "figure_style": {"palette": "neutral", "x_label": "Condition"},
    })
    assert revised.status_code == 202, revised.text
    assert app.state.job_store.get(job_id).revision == 2
    app.state.job_runner._execute(job_id)
    current = app.state.job_store.get(job_id)
    assert current.status == "WAITING_FOR_REVIEW", current.error_message
    spec_manifest = next(
        item for item in client.get(f"/api/jobs/{job_id}/artifacts").json()
        if item["role"] == "figure_spec" and item["attempt"] == current.attempt
    )
    spec = client.get(f"/api/jobs/{job_id}/artifacts/{spec_manifest['artifact_id']}").json()
    assert spec["palette"] == "neutral"
    assert spec["x_label"] == "Condition"
    assert spec["width_mm"] == 190
    revised_again = client.post(f"/api/figure/jobs/{job_id}/actions", json={
        "type": "reject", "notes": "Add a title while keeping the revised palette and label.",
        "figure_style": {"title": "Measured responses"},
        "expected_attempt": current.attempt, "expected_review_version": 1,
    })
    assert revised_again.status_code == 202, revised_again.text
    app.state.job_runner._execute(job_id)
    latest = app.state.job_store.get(job_id)
    assert latest.status == "WAITING_FOR_REVIEW", latest.error_message
    latest_spec_manifest = next(
        item for item in client.get(f"/api/jobs/{job_id}/artifacts").json()
        if item["role"] == "figure_spec" and item["attempt"] == latest.attempt
    )
    latest_spec = client.get(f"/api/jobs/{job_id}/artifacts/{latest_spec_manifest['artifact_id']}").json()
    assert latest_spec["palette"] == "neutral"
    assert latest_spec["x_label"] == "Condition"
    assert latest_spec["title"] == "Measured responses"
    assert planner_calls == []
    app.state.job_runner.shutdown()


def test_plot_subprocess_blocks_network_access(tmp_path: Path):
    from src.webapp.feature_service_base import FeatureJobError
    from src.webapp.figure_renderer import execution_prelude, run_figure_template

    class Context:
        def check_cancelled(self):
            return None

        def remaining_seconds(self, maximum):
            return maximum

    script = execution_prelude(cpu_seconds=5, memory_bytes=536_870_912, output_bytes=1_048_576)
    (tmp_path / "figure.py").write_text(script + "import socket\nsocket.socket()\n", encoding="utf-8")
    with pytest.raises(FeatureJobError, match="Network access"):
        run_figure_template(Context(), tmp_path, timeout=10)
