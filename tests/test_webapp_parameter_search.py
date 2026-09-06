from __future__ import annotations

from fastapi.testclient import TestClient

from src.webapp.api import create_app


def test_parameter_search_route_requires_explicit_network_consent(tmp_path) -> None:
    client = TestClient(create_app(run_root=tmp_path / "runs", serve_frontend=False))
    response = client.post(
        "/api/runs/run-1/quantitative/parameter-search",
        json={
            "idea_id": "Q1",
            "version": 0,
            "parameter_id": "velocity",
            "query": "kilonova velocity",
            "network_authorized": False,
        },
    )
    assert response.status_code == 422


def test_parameter_search_route_returns_queued_job(tmp_path, monkeypatch) -> None:
    app = create_app(run_root=tmp_path / "runs", serve_frontend=False)
    client = TestClient(app)
    monkeypatch.setattr(
        app.state.run_service,
        "start_parameter_search",
        lambda **_kwargs: {
            "job_id": "psearch-0123456789abcdef0123",
            "run_id": "run-1",
            "idea_id": "Q1",
            "version": 0,
            "parameter_id": "velocity",
            "status": "QUEUED",
        },
    )
    response = client.post(
        "/api/runs/run-1/quantitative/parameter-search",
        json={
            "idea_id": "Q1",
            "version": 0,
            "parameter_id": "velocity",
            "query": "kilonova velocity",
            "network_authorized": True,
        },
    )
    assert response.status_code == 202
    assert response.json()["job_id"] == "psearch-0123456789abcdef0123"
