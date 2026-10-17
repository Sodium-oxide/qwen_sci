from __future__ import annotations

import io
import time
import zipfile
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.webapp.api import create_app
from src.webapp.job_artifacts import _write_artifact
from src.webapp.jobs import JobLeaseLost, JobRegistry, JobRunner, JobStore
from src.webapp.jobs.models import JobExecutionResult


def test_shared_file_reference_blocks_delete_and_feature_aliases_work(tmp_path: Path) -> None:
    app = create_app(run_root=tmp_path / "science-runs", serve_frontend=False)
    app.state.job_runner.submit = lambda _job_id: None
    client = TestClient(app)
    uploaded = client.post(
        "/api/files",
        files={"file": ("data.csv", b"condition,response\na,1\nb,2\n", "text/csv")},
    )
    assert uploaded.status_code == 201
    file_id = uploaded.json()["file_id"]
    created = client.post(
        "/api/figure/jobs",
        json={
            "input_file_ids": [file_id],
            "figure_claim": "The response changes across conditions",
            "variable_mapping": {"x": "condition", "y": "response"},
        },
    )
    assert created.status_code == 202, created.text
    job_id = created.json()["job_id"]
    assert client.get("/api/figure/jobs").json()[0]["job_id"] == job_id
    assert client.delete(f"/api/files/{file_id}").status_code == 409


def test_upload_rejects_mismatched_mime_and_zip_traversal(tmp_path: Path) -> None:
    app = create_app(run_root=tmp_path / "science-runs", serve_frontend=False)
    client = TestClient(app)
    mismatch = client.post(
        "/api/files",
        files={"file": ("data.pdf", b"not a pdf", "application/pdf")},
    )
    assert mismatch.status_code == 422
    pdf_bytes = b"%PDF-1.7\nnot a complete document"
    mismatch_pdf = client.post(
        "/api/files",
        files={"file": ("data.txt", pdf_bytes, "text/plain")},
    )
    assert mismatch_pdf.status_code == 422

    archive_buffer = io.BytesIO()
    with zipfile.ZipFile(archive_buffer, "w") as archive:
        archive.writestr("../escape.txt", "bad")
    traversal = client.post(
        "/api/files",
        files={"file": ("archive.zip", archive_buffer.getvalue(), "application/zip")},
    )
    assert traversal.status_code == 422


def test_lease_fencing_prevents_stale_worker_completion(tmp_path: Path) -> None:
    store = JobStore(tmp_path / "control.db", job_root=tmp_path / "jobs")
    job = store.create(
        kind="polish",
        input_manifest_id="manifest",
        input_manifest_sha256="a" * 64,
        request_hash="b" * 64,
    )
    claimed = store.claim(job.job_id, lease_owner="worker-a", lease_seconds=1)
    assert claimed is not None
    time.sleep(1.05)
    assert store.reclaim_stale_jobs(stale_after_seconds=1)
    reclaimed = store.claim(job.job_id, lease_owner="worker-b", lease_seconds=10)
    assert reclaimed is not None
    with pytest.raises(JobLeaseLost):
        store.transition(job.job_id, "SUCCEEDED", lease_owner="worker-a")
    store.transition(job.job_id, "SUCCEEDED", lease_owner="worker-b", progress=100)


def test_preferences_are_versioned_and_light_research_is_exposed(tmp_path: Path) -> None:
    app = create_app(run_root=tmp_path / "science-runs", serve_frontend=False)
    client = TestClient(app)
    current = client.get("/api/preferences").json()["preferences"]
    updated = {**current, "target_journal": "Nature", "version": current["version"]}
    response = client.put("/api/preferences", json=updated)
    assert response.status_code == 200
    assert response.json()["preferences"]["version"] == current["version"] + 1
    stale = client.put("/api/preferences", json=updated)
    assert stale.status_code == 409

    created = client.post(
        "/api/runs",
        json={
            "topic": "A light research topic",
            "discipline_ids": ["Materials Science"],
            "research_depth": "light",
        },
    )
    assert created.status_code == 202, created.text
    payload = created.json()
    assert payload["research_depth"] == "light"
    assert payload["workflow_profile"] == "light_research"
    assert payload["prompt_profile"] == "research-light"


def test_computation_mode_is_independent_from_quantitative_branch(tmp_path: Path) -> None:
    client = TestClient(create_app(run_root=tmp_path / "science-runs", serve_frontend=False))
    created = client.post(
        "/api/runs",
        json={
            "run_id": "computation-control-run",
            "topic": "A full research topic with a numerical experiment",
            "discipline_ids": ["Materials Science"],
            "quantitative_mode": "off",
            "computation_mode": "plan",
            "computation_model": "qwen3.6-flash",
        },
    )
    assert created.status_code == 202, created.text
    payload = created.json()
    assert payload["quantitative_mode"] == "off"
    assert payload["computation_mode"] == "plan"

    metadata = json.loads((tmp_path / "science-runs" / "computation-control-run" / "science_run.json").read_text())
    options = metadata["immutable_inputs"]["options"]
    assert options["quantitative"]["mode"] == "off"
    assert options["computation"]["mode"] == "plan"
    assert options["computation"]["model"] == "qwen3.6-flash"

    light = client.post(
        "/api/runs",
        json={
            "run_id": "light-computation-control-run",
            "topic": "A light research topic with computation",
            "discipline_ids": ["Materials Science"],
            "research_depth": "light",
            "computation_mode": "run",
        },
    )
    assert light.status_code == 422, light.text


def test_validation_errors_are_field_scoped_and_request_ids_are_safe(tmp_path: Path) -> None:
    client = TestClient(create_app(run_root=tmp_path / "science-runs", serve_frontend=False))
    response = client.post(
        "/api/polish/jobs",
        headers={"x-request-id": "contains spaces"},
        json={"text": ""},
    )

    assert response.status_code == 422
    payload = response.json()["error"]
    assert payload["code"] == "REQUEST_VALIDATION_FAILED"
    assert payload["details"]
    assert " " not in payload["request_id"]
    assert response.headers["x-request-id"] == payload["request_id"]
    assert "tmp_path" not in response.text


def test_capabilities_distinguish_disabled_routes_and_configured_models(tmp_path: Path, monkeypatch) -> None:
    from types import SimpleNamespace

    monkeypatch.setattr("src.webapp.capability_service.resolve_provider", lambda *_args: SimpleNamespace(api_key="test-key", base_url="https://example.test"))
    client = TestClient(create_app(run_root=tmp_path / "science-runs", serve_frontend=False))
    payload = client.get("/api/capabilities").json()

    assert payload["text_model_choices"] == [
        "qwen3.6-flash",
        "qwen3.7-plus",
        "qwen3.8-flash",
        "qwen3.8-max",
    ]
    assert payload["figure"]["r"]["status"] == "unavailable"
    assert "disabled" in payload["figure"]["r"]["reason"]
    assert payload["text_models"]["qwen3.6-flash"]["configured"] is True
    assert payload["text_models"]["qwen3.6-flash"]["verified"] is False


def test_missing_credentials_are_not_reported_as_configured(tmp_path: Path, monkeypatch):
    from types import SimpleNamespace

    monkeypatch.setattr("src.webapp.capability_service.resolve_provider", lambda *_args: SimpleNamespace(api_key="", base_url="https://example.test"))
    monkeypatch.setattr("src.webapp.capability_service.resolve_image_generation_settings", lambda *_args, **_kwargs: {
        "provider": "qwen", "model": "qwen-image-3.0-pro", "api_key": "", "base_url": "https://example.test",
    })
    payload = TestClient(create_app(run_root=tmp_path / "science-runs", serve_frontend=False)).get("/api/capabilities").json()
    assert payload["text_models"]["qwen3.6-flash"]["configured"] is False
    assert payload["figure"]["image_generation"]["status"] == "unavailable"
    assert "test-key" not in json.dumps(payload)


def test_run_details_and_download_include_committed_job_artifacts(tmp_path: Path) -> None:
    app = create_app(run_root=tmp_path / "science-runs", serve_frontend=False)
    client = TestClient(app)
    created_run = client.post(
        "/api/runs",
        json={"topic": "A durable artifact integration topic", "discipline_ids": ["Materials Science"]},
    )
    assert created_run.status_code == 202, created_run.text
    run_id = created_run.json()["run_id"]

    job = app.state.job_store.create(
        kind="science",
        run_id=run_id,
        input_manifest_id="manifest",
        input_manifest_sha256="a" * 64,
        request_hash="b" * 64,
    )
    claimed = app.state.job_store.claim(job.job_id, lease_owner="artifact-test")
    assert claimed is not None
    artifact_id = _write_artifact(
        app.state.job_store.job_directory(job.job_id),
        claimed,
        role="science_note",
        filename="note.md",
        content=b"job artifact",
        media_type="text/markdown",
        provenance={"test": True},
        validator_status="PASS",
        source_file_ids=(),
        max_bytes=1024,
    )
    app.state.job_store.transition(
        job.job_id,
        "SUCCEEDED",
        lease_owner="artifact-test",
        output_artifact_ids=(artifact_id,),
    )

    detail = client.get(f"/api/runs/{run_id}")
    assert detail.status_code == 200
    assert any(item["artifact_id"] == artifact_id for item in detail.json()["artifacts"])
    download = client.get(f"/api/runs/{run_id}/artifacts/{artifact_id}")
    assert download.status_code == 200
    assert download.content == b"job artifact"


def test_sql_input_reference_protects_file_when_json_projection_is_missing(tmp_path: Path):
    app = create_app(run_root=tmp_path / "science-runs", serve_frontend=False)
    app.state.job_runner.submit = lambda _job_id: None
    client = TestClient(app)
    uploaded = client.post("/api/files", files={"file": ("draft.txt", b"A supported finding.", "text/plain")})
    file_id = uploaded.json()["file_id"]
    first = client.post("/api/polish/jobs", json={"input_file_id": file_id}).json()["job_id"]
    second = client.post("/api/polish/jobs", json={"input_file_id": file_id}).json()["job_id"]
    app.state.file_service.release_reference(file_id, job_id=first)
    assert app.state.file_service.get(file_id).job_id == second
    app.state.file_service.release_reference(file_id, job_id=second)
    assert client.delete(f"/api/files/{file_id}").status_code == 409
    app.state.file_service.reconcile_job_references()
    path = app.state.file_service._directory(file_id) / "file.json"
    references = json.loads(path.read_text())["references"]
    assert set(references) == {f"job:{first}", f"job:{second}"}


def test_job_filters_association_and_feature_sse_are_consistent(tmp_path: Path):
    app = create_app(run_root=tmp_path / "science-runs", serve_frontend=False)
    app.state.job_runner.submit = lambda _job_id: None
    client = TestClient(app)
    run = client.post("/api/runs", json={"topic": "Research project association", "discipline_ids": ["Materials Science"], "project_id": "project-a"}).json()
    created = []
    for ordinal in range(3):
        response = client.post("/api/polish/jobs", json={"text": f"Supported finding {ordinal}.", "run_id": run["run_id"]})
        assert response.status_code == 202, response.text
        created.append(response.json())
    assert {job["project_id"] for job in created} == {"project-a"}
    assert len(client.get("/api/jobs", params={"project_id": "project-a", "run_id": run["run_id"], "limit": 1, "offset": 1}).json()) == 1
    assert client.get("/api/polish/jobs", params={"project_id": "project-b"}).json() == []
    assert client.get("/api/polish/jobs", params={"status": "bogus"}).status_code == 422
    events = client.get(f"/api/polish/jobs/{created[0]['job_id']}/events", params={"follow": "false"}, headers={"Last-Event-ID": "1"})
    assert events.status_code == 200
    assert "JOB_QUEUED" in events.text and "JOB_CREATED" not in events.text
    assert client.get(f"/api/translation/jobs/{created[0]['job_id']}/events", params={"follow": "false"}).status_code == 404
    unknown = client.post("/api/polish/jobs", json={"text": "Supported finding.", "run_id": "missing"})
    assert unknown.status_code == 422


def test_product_previews_report_static_sources_and_unavailable_modes(tmp_path: Path):
    client = TestClient(create_app(run_root=tmp_path / "science-runs", representative_root=tmp_path / "empty", serve_frontend=False))
    modules = client.get("/api/product/modules").json()
    assert {module["id"] for module in modules} == {"full-research", "light-research", "figure", "polish", "translate", "preferences"}
    preview = client.get("/api/product/preview/translate").json()
    assert preview["data_source"] == "static_registry" and preview["is_live"] is False
    assert preview["last_verified_at"] is None
    assert "progress" not in preview
    assert client.get("/api/product/preview/missing").status_code == 404
    capabilities = client.get("/api/product/capabilities").json()
    assert capabilities["translation"]["modes"]["image_page_translation"]["status"] == "unavailable"
    assert capabilities["figure"]["reference_image_editing"]["status"] == "unavailable"


def test_reviewed_artifact_reuse_is_idempotent_and_project_scoped(tmp_path: Path):
    app = create_app(run_root=tmp_path / "science-runs", serve_frontend=False)
    client = TestClient(app)
    store = app.state.job_store
    record = store.create(kind="polish", input_manifest_id="manifest", input_manifest_sha256="a" * 64,
                          request_hash="b" * 64, project_id="project-a")
    claimed = store.claim(record.job_id, lease_owner="test")
    artifact_id = _write_artifact(store.job_directory(record.job_id), claimed, role="document", filename="draft.md",
                                  content=b"Reviewed scientific prose.", media_type="text/markdown", provenance={},
                                  validator_status="PASS", source_file_ids=(), max_bytes=1024)
    store.transition(record.job_id, "WAITING_FOR_REVIEW", lease_owner="test", output_artifact_ids=(artifact_id,))
    url = f"/api/jobs/{record.job_id}/artifacts/{artifact_id}/files"
    assert client.post(url).status_code == 409
    assert client.post(f"/api/jobs/{record.job_id}/review", json={"accepted": True}).status_code == 202
    reused = client.post(url)
    assert reused.status_code == 201, reused.text
    assert reused.json()["source_artifact_id"] == artifact_id
    assert reused.json()["project_id"] == "project-a"
    assert client.post(url).json()["file_id"] == reused.json()["file_id"]
    assert client.get(reused.json()["content_url"]).content == b"Reviewed scientific prose."
