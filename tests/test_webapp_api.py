"""Focused integration tests for the browser-facing science control plane."""

from __future__ import annotations

import json
from pathlib import Path
from threading import Event
from urllib.parse import quote

from fastapi.testclient import TestClient

from src.pipeline.quantitative_state import new_quantitative_state, save_quantitative_state
from src.pipeline.science_run import append_science_event, atomic_write_json, locked_science_run, load_science_run, mark_stage_running, save_science_state
from src.webapp.api import create_app


_ONE_PIXEL_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDAT\x08\xd7c\xf8\xcf\xc0\xf0\x1f\x00\x05\x00\x01\xff\x89\x99=\x1d"
    b"\x00\x00\x00\x00IEND\xaeB`\x82"
)


class RecordingSupervisor:
    """Avoid starting LLM-backed services while asserting action routing."""

    def __init__(self) -> None:
        self.submissions: list[tuple[str, str]] = []

    def is_active(self, _run_id: str) -> bool:
        return False

    def submit(self, *, paths, metadata, until: str) -> None:
        self.submissions.append((str(metadata["science_run_id"]), until))


class ImmediateSupervisor(RecordingSupervisor):
    """Run controlled callbacks synchronously for quantitative action tests."""

    def __init__(self) -> None:
        super().__init__()
        self.quantitative_submissions: list[str] = []

    def submit_task(self, *, run_id: str, task) -> None:
        self.quantitative_submissions.append(run_id)
        task()


def _client(tmp_path: Path) -> tuple[TestClient, RecordingSupervisor]:
    app = create_app(run_root=tmp_path / "science-runs", serve_frontend=False)
    supervisor = RecordingSupervisor()
    app.state.run_service.supervisor = supervisor
    return TestClient(app), supervisor


def _create_run(
    client: TestClient,
    *,
    run_id: str = "web-test-run",
    quantitative_mode: str = "optional",
) -> dict[str, object]:
    response = client.post(
        "/api/runs",
        json={
            "run_id": run_id,
            "topic": "How can controlled image evidence improve battery electrode stability research?",
            "discipline_ids": ["Materials Science", "Chemistry"],
            "language": "en",
            "minimum_pages": 7,
            "quantitative_mode": quantitative_mode,
        },
    )
    assert response.status_code == 202, response.text
    return response.json()


def _quantitative_client(tmp_path: Path) -> tuple[TestClient, ImmediateSupervisor]:
    app = create_app(run_root=tmp_path / "science-runs", serve_frontend=False)
    supervisor = ImmediateSupervisor()
    app.state.run_service.supervisor = supervisor
    return TestClient(app), supervisor


def _set_quantitative_state(
    client: TestClient,
    *,
    run_id: str,
    status: str,
    plan_identity: str = "p" * 64,
) -> Path:
    service = client.app.state.run_service
    paths = service.paths_for(run_id)
    with locked_science_run(paths):
        _metadata, science_state = load_science_run(paths)
        science_state["status"] = "PARTIAL"
        for stage_name in ("survey", "idea", "exp_design"):
            science_state["stages"][stage_name]["status"] = "COMPLETED"
        science_state["stages"]["author"]["status"] = "PENDING"
        save_science_state(paths, science_state)
    quantitative = new_quantitative_state(science_run_id=run_id, status=status)
    quantitative["ideas"] = {
        "Q1": {
            "quantitative_idea_id": "Q1",
            "title": "Controlled quantitative question",
            "status": status,
            "current_version": 0,
            "versions": {
                "v0": {
                    "version": 0,
                    "parent_version": None,
                    "status": status,
                    "plan_identity": plan_identity,
                    "execution_ids": [],
                    "qualification_status": "PENDING",
                },
                "v1": {"version": 1, "parent_version": 0, "status": "WAITING_FOR_BLUEPRINT"},
                "v2": {"version": 2, "parent_version": 1, "status": "WAITING_FOR_BLUEPRINT"},
            },
        }
    }
    save_quantitative_state(paths.run_dir, quantitative)
    return paths.run_dir


def test_catalog_exposes_full_supported_scientific_scope(tmp_path: Path) -> None:
    client, _supervisor = _client(tmp_path)

    response = client.get("/api/disciplines")

    assert response.status_code == 200
    catalog = response.json()["disciplines"]
    assert len(catalog) == 20
    assert all(entry["allowed"] for entry in catalog)
    assert {entry["label"] for entry in catalog} >= {"Materials Science", "Medicine", "Computer Science"}

    resolution = client.post(
        "/api/disciplines/resolve",
        json={"topic": "Machine learning methods for analysing scientific image datasets"},
    )
    assert resolution.status_code == 200
    assert "17" in resolution.json()["suggested_catalog_ids"]


def test_same_origin_frontend_uses_real_api_controls(tmp_path: Path) -> None:
    app = create_app(run_root=tmp_path / "science-runs", serve_frontend=True)
    client = TestClient(app)

    response = client.get("/")

    assert response.status_code == 200
    assert 'id="root"' in response.text
    assert 'type="module"' in response.text
    assert "app.js" not in response.text
    assert "demoSessions" not in response.text


def test_create_and_upload_materials_are_run_scoped_and_path_free(tmp_path: Path) -> None:
    client, _supervisor = _client(tmp_path)
    created = _create_run(client)
    run_id = created["run_id"]
    assert created["discipline_ids"] == ["Materials Science", "Chemistry"]
    assert created["allowed_actions"] == ["start_workflow"]
    assert str(tmp_path) not in json.dumps(created)

    upload = client.post(
        f"/api/runs/{run_id}/materials",
        files=[("files", ("microscopy.png", _ONE_PIXEL_PNG, "image/png"))],
        data={
            "metadata": json.dumps(
                [
                    {
                        "label": "electrode microscopy",
                        "scope": "survey_evidence",
                        "contains_sensitive_data": False,
                    }
                ]
            )
        },
    )
    assert upload.status_code == 200, upload.text
    body = upload.json()
    record = body["materials"][0]
    assert body["run"]["run_id"] == run_id
    assert body["run"]["materials"][0]["material_id"] == record["material_id"]
    assert record["modality"] == "image"
    assert str(tmp_path) not in json.dumps(body)

    stored_only = client.post(
        f"/api/runs/{run_id}/materials",
        files=[("files", ("private-reference.png", _ONE_PIXEL_PNG, "image/png"))],
        data={
            "metadata": json.dumps(
                [
                    {
                        "label": "private background reference",
                        "scope": "context_only",
                        "contains_sensitive_data": True,
                    }
                ]
            )
        },
    )
    assert stored_only.status_code == 200, stored_only.text

    run_dir = tmp_path / "science-runs" / str(run_id)
    stored_files = list((run_dir / "inputs" / "files").iterdir())
    assert len(stored_files) == 2
    assert all(path.suffix == ".png" for path in stored_files)
    materials_manifest = json.loads((run_dir / "inputs" / "materials_manifest.json").read_text(encoding="utf-8"))
    multimodal_manifest = json.loads((run_dir / "inputs" / "multimodal_input_manifest.json").read_text(encoding="utf-8"))
    assert str(tmp_path) not in json.dumps(materials_manifest)
    assert str(tmp_path) not in json.dumps(multimodal_manifest)
    assert len(materials_manifest["materials"]) == 2
    assert len(multimodal_manifest["records"]) == 1
    assert multimodal_manifest["records"][0]["file"].startswith("files/")

    listed = client.get("/api/runs", params={"query": "microscopy"})
    assert listed.status_code == 200
    assert [entry["run_id"] for entry in listed.json()] == [run_id]

    material = client.get(f"/api/runs/{run_id}/materials/{record['material_id']}")
    assert material.status_code == 200
    assert material.content == _ONE_PIXEL_PNG
    removed = client.delete(f"/api/runs/{run_id}/materials/{record['material_id']}")
    assert removed.status_code == 200, removed.text
    assert len(removed.json()["materials"]) == 1
    assert client.get(f"/api/runs/{run_id}/materials/{record['material_id']}").status_code == 404

    paths = client.app.state.run_service.paths_for(run_id)
    with locked_science_run(paths):
        append_science_event(
            paths,
            event_type="STAGE_FAILED",
            stage="survey",
            message=f"Private local failure at {tmp_path / 'science-runs' / str(run_id)}",
        )

    events = client.get(f"/api/runs/{run_id}/events?follow=false")
    assert events.status_code == 200
    assert "RUN_INITIALIZED" in events.text
    assert "MATERIALS_REGISTERED" in events.text
    assert "[local path]" in events.text
    assert str(tmp_path) not in events.text
    assert events.text.index("RUN_INITIALIZED") < events.text.index("MATERIALS_REGISTERED") < events.text.index("STAGE_FAILED")


def test_browser_log_access_is_stage_scoped_paginated_and_redacted(tmp_path: Path) -> None:
    client, _supervisor = _client(tmp_path)
    created = _create_run(client, run_id="web-log-run")
    run_id = str(created["run_id"])
    paths = client.app.state.run_service.paths_for(run_id)
    author_log = paths.run_dir / "author" / "attempt-1" / "author_trace.jsonl"
    author_log.parent.mkdir(parents=True)
    author_log.write_text(
        json.dumps(
            {
                "event": "render",
                "api_key": "private-key-value",
                "path": str(paths.run_dir / "author"),
                "message": f"Created at {paths.run_dir / 'author' / 'report.tex'}",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    idea_log = paths.run_dir / "idea" / "attempt-2" / "logs" / "research.log"
    idea_log.parent.mkdir(parents=True)
    idea_log.write_text(
        "Authorization: Bearer private-bearer-token\n"
        + f"work dir: {paths.run_dir / 'idea'}\n"
        + "completed research step\n" * 800,
        encoding="utf-8",
    )
    ignored_input_log = paths.inputs / "private.log"
    ignored_input_log.write_text("must not be listed", encoding="utf-8")
    with locked_science_run(paths):
        append_science_event(paths, event_type="STAGE_STARTED", stage="author", api_key="event-secret")

    listed = client.get(f"/api/runs/{run_id}/logs")

    assert listed.status_code == 200, listed.text
    sources = listed.json()
    assert len(sources) == 2
    assert str(tmp_path) not in json.dumps(sources)
    assert all("inputs" not in source["log_id"] for source in sources)
    author_source = next(source for source in sources if source["format"] == "jsonl")
    author_chunk = client.get(f"/api/runs/{run_id}/logs/{quote(author_source['log_id'], safe='')}")
    assert author_chunk.status_code == 200, author_chunk.text
    assert "private-key-value" not in author_chunk.text
    assert "[redacted]" in author_chunk.text
    assert str(tmp_path) not in author_chunk.text

    text_source = next(source for source in sources if source["format"] == "text")
    first_text_chunk = client.get(f"/api/runs/{run_id}/logs/{quote(text_source['log_id'], safe='')}", params={"limit": 4096})
    assert first_text_chunk.status_code == 200, first_text_chunk.text
    first_payload = first_text_chunk.json()
    assert first_payload["has_more"] is True
    assert "private-bearer-token" not in first_payload["content"]
    assert str(tmp_path) not in first_payload["content"]
    next_text_chunk = client.get(
        f"/api/runs/{run_id}/logs/{quote(text_source['log_id'], safe='')}",
        params={"offset": first_payload["next_offset"], "limit": 4096},
    )
    assert next_text_chunk.status_code == 200, next_text_chunk.text
    assert next_text_chunk.json()["offset"] == first_payload["next_offset"]
    assert client.get(f"/api/runs/{run_id}/logs/not-a-real-log").status_code == 404

    events = client.get(f"/api/runs/{run_id}/events?follow=false")
    assert "event: run_event" in events.text
    assert "event-secret" not in events.text
    assert "[redacted]" in events.text


def test_representative_research_gallery_exposes_curated_assets_only(tmp_path: Path) -> None:
    representative_root = tmp_path / "representative"
    project_root = representative_root / "demo_project"
    project_root.mkdir(parents=True)
    (project_root / "cover.png").write_bytes(_ONE_PIXEL_PNG)
    (project_root / "research_plan.pdf").write_bytes(b"%PDF-demo")
    (project_root / "workflow.log").write_text("research step\n", encoding="utf-8")
    (project_root / "private.txt").write_text("not exposed", encoding="utf-8")
    app = create_app(run_root=tmp_path / "science-runs", representative_root=representative_root, serve_frontend=False)
    client = TestClient(app)

    listed = client.get("/api/representative")

    assert listed.status_code == 200
    projects = listed.json()
    assert len(projects) == 1
    project = projects[0]
    assert project["project_id"] == "demo_project"
    assert project["cover_url"].endswith("/cover.png")
    assert {file["kind"] for file in project["files"]} == {"image", "pdf", "log"}
    assert all("private.txt" not in file["file_id"] for file in project["files"])

    image = next(file for file in project["files"] if file["kind"] == "image")
    log = next(file for file in project["files"] if file["kind"] == "log")
    assert client.get(image["url"]).content == _ONE_PIXEL_PNG
    assert client.get(log["url"]).text.splitlines() == ["research step"]
    assert "attachment" in client.get(f"{log['url']}?download=1").headers.get("content-disposition", "")
    assert client.get("/api/representative/demo_project/files/../private.txt").status_code == 404


def test_materials_are_immutable_once_a_science_stage_starts(tmp_path: Path) -> None:
    client, _supervisor = _client(tmp_path)
    created = _create_run(client, run_id="immutable-material-run")
    run_id = str(created["run_id"])
    upload = client.post(
        f"/api/runs/{run_id}/materials",
        files=[("files", ("evidence.png", _ONE_PIXEL_PNG, "image/png"))],
        data={"metadata": json.dumps([{"scope": "survey_evidence"}])},
    )
    assert upload.status_code == 200, upload.text
    material_id = upload.json()["materials"][0]["material_id"]
    paths = client.app.state.run_service.paths_for(run_id)
    with locked_science_run(paths):
        _metadata, state = load_science_run(paths)
        state["stages"]["survey"]["status"] = "RUNNING"
        save_science_state(paths, state)

    rejected = client.delete(f"/api/runs/{run_id}/materials/{material_id}")

    assert rejected.status_code == 409
    assert client.get(f"/api/runs/{run_id}").json()["materials"][0]["material_id"] == material_id


def test_completed_runs_index_nested_stage_images_for_safe_preview(tmp_path: Path) -> None:
    client, _supervisor = _client(tmp_path)
    created = _create_run(client, run_id="completed-figure-run")
    run_id = str(created["run_id"])
    paths = client.app.state.run_service.paths_for(run_id)
    survey_figure = paths.run_dir / "survey" / "attempt-001" / "fig_mechanism.png"
    author_figure = paths.run_dir / "author" / "attempt-002" / "report_project" / "fig1.png"
    for figure in (survey_figure, author_figure):
        figure.parent.mkdir(parents=True, exist_ok=True)
        figure.write_bytes(_ONE_PIXEL_PNG)
    with locked_science_run(paths):
        _metadata, state = load_science_run(paths)
        state["status"] = "COMPLETED"
        for stage in state["stages"].values():
            stage["status"] = "COMPLETED"
        save_science_state(paths, state)

    response = client.get(f"/api/runs/{run_id}")

    assert response.status_code == 200, response.text
    figures = {artifact["artifact_id"]: artifact for artifact in response.json()["artifacts"] if artifact["media_type"].startswith("image/")}
    assert set(figures) >= {
        "survey:figure:attempt-001/fig_mechanism.png",
        "author:figure:attempt-002/report_project/fig1.png",
    }
    author_view = figures["author:figure:attempt-002/report_project/fig1.png"]
    assert author_view["label"] == "attempt-002/report_project/fig1.png"
    assert author_view["previewable"] is True

    preview = client.get(f"/api/runs/{run_id}/artifacts/{quote(author_view['artifact_id'], safe='')}")

    assert preview.status_code == 200, preview.text
    assert preview.content == _ONE_PIXEL_PNG


def test_web_launcher_sequence_creates_uploads_and_starts_a_supervised_run(tmp_path: Path) -> None:
    client, supervisor = _client(tmp_path)
    created = _create_run(client, run_id="web-launcher-sequence")
    run_id = str(created["run_id"])

    uploaded = client.post(
        f"/api/runs/{run_id}/materials",
        files=[("files", ("electrode.png", _ONE_PIXEL_PNG, "image/png"))],
        data={
            "metadata": json.dumps(
                [
                    {
                        "label": "electrode evidence",
                        "scope": "survey_evidence",
                        "contains_sensitive_data": False,
                    }
                ]
            )
        },
    )

    assert uploaded.status_code == 200, uploaded.text
    launcher_snapshot = uploaded.json()["run"]
    assert launcher_snapshot["run_id"] == run_id
    assert launcher_snapshot["materials"][0]["original_name"] == "electrode.png"

    started = client.post(
        f"/api/runs/{launcher_snapshot['run_id']}/actions",
        json={"type": "start_workflow", "until": "author"},
    )

    assert started.status_code == 202, started.text
    assert supervisor.submissions == [(run_id, "author")]


def test_web_workflow_accepts_each_safe_stage_endpoint(tmp_path: Path) -> None:
    client, supervisor = _client(tmp_path)

    for until in ("survey", "idea", "exp_design", "author"):
        created = _create_run(client, run_id=f"web-until-{until}")
        run_id = str(created["run_id"])
        started = client.post(
            f"/api/runs/{run_id}/actions",
            json={"type": "start_workflow", "until": until},
        )

        assert started.status_code == 202, started.text
        assert supervisor.submissions[-1] == (run_id, until)


def test_web_cancellation_is_durable_and_resume_requires_a_new_user_action(tmp_path: Path) -> None:
    client, supervisor = _client(tmp_path)
    created = _create_run(client, run_id="web-cancellation-run")
    run_id = str(created["run_id"])
    paths = client.app.state.run_service.paths_for(run_id)
    with locked_science_run(paths):
        _metadata, state = load_science_run(paths)
        mark_stage_running(state, "survey", input_identity={})
        save_science_state(paths, state)

    cancelled = client.post(f"/api/runs/{run_id}/actions", json={"type": "cancel_science"})

    assert cancelled.status_code == 202, cancelled.text
    cancellation = cancelled.json()["cancellation"]
    assert cancelled.json()["status"] == "CANCELLED"
    assert cancellation["requested_stage"] == "survey"
    assert cancelled.json()["allowed_actions"] == []

    with locked_science_run(paths):
        _metadata, state = load_science_run(paths)
        state["stages"]["survey"].update({"status": "COMPLETED", "execution_owner": None})
        save_science_state(paths, state)

    resumed = client.post(
        f"/api/runs/{run_id}/actions",
        json={"type": "resume_science", "until": "idea"},
    )

    assert resumed.status_code == 202, resumed.text
    assert resumed.json()["cancellation"] is None
    assert resumed.json()["status"] == "PARTIAL"
    assert supervisor.submissions[-1] == (run_id, "idea")
    events = client.get(f"/api/runs/{run_id}/events?follow=false")
    assert "RUN_CANCELLATION_REQUESTED" in events.text
    assert "RUN_RESUMED" in events.text


def test_actions_are_whitelisted_and_supervised_without_cli_execution(tmp_path: Path) -> None:
    client, supervisor = _client(tmp_path)
    created = _create_run(client)
    run_id = created["run_id"]

    rejected = client.post(f"/api/runs/{run_id}/actions", json={"type": "shell", "command": "anything"})
    assert rejected.status_code == 422

    started = client.post(f"/api/runs/{run_id}/actions", json={"type": "start_workflow", "until": "exp_design"})
    assert started.status_code == 202, started.text
    assert supervisor.submissions == [(run_id, "exp_design")]


def test_duplicate_science_submission_returns_conflict(tmp_path: Path, monkeypatch) -> None:
    app = create_app(run_root=tmp_path / "science-runs", serve_frontend=False)
    client = TestClient(app)
    created = _create_run(client, run_id="duplicate-web-action")
    run_id = str(created["run_id"])
    started = Event()
    release = Event()

    import src.webapp.run_service as run_service

    def block_workflow(**_kwargs: object) -> None:
        started.set()
        assert release.wait(timeout=5)

    monkeypatch.setattr(run_service, "run_science_workflow", block_workflow)
    try:
        first = client.post(f"/api/runs/{run_id}/actions", json={"type": "start_workflow", "until": "exp_design"})
        assert first.status_code == 202, first.text
        assert started.wait(timeout=2)
        duplicate = client.post(f"/api/runs/{run_id}/actions", json={"type": "start_workflow", "until": "exp_design"})
        assert duplicate.status_code == 409, duplicate.text
    finally:
        release.set()


def test_required_quantitative_mode_blocks_author_after_service_restart(tmp_path: Path) -> None:
    client, _supervisor = _client(tmp_path)
    created = _create_run(client, run_id="required-restart-run", quantitative_mode="required")
    run_id = str(created["run_id"])
    paths = client.app.state.run_service.paths_for(run_id)
    with locked_science_run(paths):
        _metadata, state = load_science_run(paths)
        state["status"] = "PARTIAL"
        for stage_name in ("survey", "idea", "exp_design"):
            state["stages"][stage_name]["status"] = "COMPLETED"
        state["stages"]["author"]["status"] = "PENDING"
        save_science_state(paths, state)

    restarted = TestClient(create_app(run_root=tmp_path / "science-runs", serve_frontend=False))
    after_restart = restarted.get(f"/api/runs/{run_id}")

    assert after_restart.status_code == 200
    assert "resume_science" not in after_restart.json()["allowed_actions"]
    assert after_restart.json()["quantitative"]["allowed_actions"] == ["resume_quantitative"]
    bypass = restarted.post(f"/api/runs/{run_id}/actions", json={"type": "resume_science", "until": "author"})
    assert bypass.status_code == 422


def test_rejects_excluded_scope_and_unknown_artifact_paths(tmp_path: Path) -> None:
    client, _supervisor = _client(tmp_path)
    excluded = client.post(
        "/api/runs",
        json={
            "run_id": "out-of-scope",
            "topic": "How can a business strategy optimize quarterly profit forecasts?",
            "discipline_ids": ["Business, Management and Accounting"],
        },
    )
    assert excluded.status_code == 422

    created = _create_run(client)
    unknown = client.get(f"/api/runs/{created['run_id']}/artifacts/not-a-real-artifact")
    assert unknown.status_code == 404
    traversal = client.get(f"/api/runs/{created['run_id']}/artifacts/%2E%2E%2Fscience_run.json")
    assert traversal.status_code == 404


def test_quantitative_network_actions_require_typed_explicit_consent(tmp_path: Path, monkeypatch) -> None:
    client, supervisor = _quantitative_client(tmp_path)
    created = _create_run(client)
    run_id = str(created["run_id"])
    _set_quantitative_state(client, run_id=run_id, status="WAITING_FOR_PARAMETER_EVIDENCE")

    import src.webapp.run_service as run_service

    calls: list[dict[str, object]] = []
    monkeypatch.setattr(run_service, "refresh_quantitative_state", lambda _run_dir: {"status": "WAITING_FOR_PARAMETER_EVIDENCE"})
    monkeypatch.setattr(
        run_service,
        "discover_quantitative_parameter_evidence",
        lambda **kwargs: calls.append(kwargs),
    )

    denied = client.post(
        f"/api/runs/{run_id}/actions",
        json={"type": "discover_parameters", "idea_id": "Q1", "version": 0, "network_authorized": False},
    )
    assert denied.status_code == 422
    assert not calls

    rejected_extra = client.post(
        f"/api/runs/{run_id}/actions",
        json={
            "type": "discover_parameters",
            "idea_id": "Q1",
            "version": 0,
            "network_authorized": True,
            "command": "ignored-before-this-change",
        },
    )
    assert rejected_extra.status_code == 422
    assert not calls

    authorized = client.post(
        f"/api/runs/{run_id}/actions",
        json={"type": "discover_parameters", "idea_id": "Q1", "version": 0, "network_authorized": True},
    )
    assert authorized.status_code == 202, authorized.text
    assert supervisor.quantitative_submissions == [run_id]
    assert len(calls) == 1
    assert calls[0]["fetch"] is True
    assert "runtime_config" in calls[0]


def test_quantitative_execution_rechecks_approval_and_exact_plan_identity(tmp_path: Path, monkeypatch) -> None:
    client, supervisor = _quantitative_client(tmp_path)
    created = _create_run(client)
    run_id = str(created["run_id"])
    plan_identity = "f" * 64
    run_dir = _set_quantitative_state(
        client,
        run_id=run_id,
        status="WAITING_FOR_EXECUTION_AUTHORIZATION",
        plan_identity=plan_identity,
    )

    import src.webapp.run_service as run_service

    calls: list[dict[str, object]] = []
    monkeypatch.setattr(run_service, "refresh_quantitative_state", lambda _run_dir: {"status": "WAITING_FOR_QUALIFICATION"})
    monkeypatch.setattr(run_service, "execute_quantitative_plan", lambda **kwargs: calls.append(kwargs))

    no_confirmation = client.post(
        f"/api/runs/{run_id}/actions",
        json={"type": "execute_plan", "idea_id": "Q1", "version": 0, "plan_identity": plan_identity},
    )
    assert no_confirmation.status_code == 422

    mismatch = client.post(
        f"/api/runs/{run_id}/actions",
        json={"type": "execute_plan", "idea_id": "Q1", "version": 0, "confirmed": True, "plan_identity": "e" * 64},
    )
    assert mismatch.status_code == 422
    assert not calls

    version_dir = run_dir / "quantitative" / "Q1" / "v0"
    atomic_write_json(version_dir / "simulation_run_plan.json", {"plan_identity": plan_identity})
    missing_approval = client.post(
        f"/api/runs/{run_id}/actions",
        json={"type": "execute_plan", "idea_id": "Q1", "version": 0, "confirmed": True, "plan_identity": plan_identity},
    )
    assert missing_approval.status_code == 422
    assert not calls

    evidence_dir = run_dir / "quantitative" / "Q1" / "parameter_evidence" / "v0"
    atomic_write_json(evidence_dir / "approved_parameter_set.json", {"approved": True})
    atomic_write_json(evidence_dir / "approved_parameter_set_manifest.json", {"approved": True})
    executed = client.post(
        f"/api/runs/{run_id}/actions",
        json={"type": "execute_plan", "idea_id": "Q1", "version": 0, "confirmed": True, "plan_identity": plan_identity},
    )
    assert executed.status_code == 202, executed.text
    assert supervisor.quantitative_submissions == [run_id]
    assert calls == [
        {
            "run_dir": run_dir,
            "quantitative_idea_id": "Q1",
            "version": 0,
            "execute": True,
            "confirmed_plan_identity": plan_identity,
        }
    ]


def test_quantitative_view_hides_raw_commands_and_required_mode_defers_author(tmp_path: Path) -> None:
    client, supervisor = _quantitative_client(tmp_path)
    response = client.post(
        "/api/runs",
        json={
            "run_id": "required-quantitative-run",
            "topic": "How can verified numerical parameter evidence constrain a materials research plan?",
            "discipline_ids": ["Materials Science"],
            "quantitative_mode": "required",
        },
    )
    assert response.status_code == 202, response.text
    run_id = response.json()["run_id"]
    _set_quantitative_state(client, run_id=run_id, status="WAITING_FOR_BLUEPRINT")

    detail = client.get(f"/api/runs/{run_id}")
    assert detail.status_code == 200
    quantitative = detail.json()["quantitative"]
    assert quantitative["allowed_actions"] == ["prepare_quantitative_blueprint"]
    assert "next_actions" not in quantitative
    assert "command" not in json.dumps(quantitative)
    assert str(tmp_path) not in json.dumps(quantitative)

    fresh = _create_run(client, run_id="required-start-run", quantitative_mode="required")
    started = client.post(
        f"/api/runs/{fresh['run_id']}/actions",
        json={"type": "start_workflow", "until": "author"},
    )
    assert started.status_code == 202, started.text
    assert supervisor.submissions[-1] == (fresh["run_id"], "exp_design")
