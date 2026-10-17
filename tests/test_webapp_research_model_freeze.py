from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from omegaconf import OmegaConf

from src.webapp.api import create_app
from src.webapp.prompts import build_default_prompt_registry


TEXT_MODELS = (
    "qwen3.6-flash",
    "qwen3.7-plus",
    "qwen3.8-flash",
    "qwen3.8-max",
)


def _config_value(config, path: str):
    value = OmegaConf.select(config, path, default=None)
    return OmegaConf.to_container(value, resolve=True) if OmegaConf.is_config(value) else value


@pytest.mark.parametrize("model_name", TEXT_MODELS)
def test_create_run_freezes_selected_model_and_prompt(model_name: str, tmp_path: Path) -> None:
    app = create_app(run_root=tmp_path / "science-runs", serve_frontend=False)
    client = TestClient(app)
    response = client.post(
        "/api/runs",
        json={
            "run_id": f"freeze-{model_name.replace('.', '-')}",
            "topic": "A model freeze contract for a scientific workflow",
            "discipline_ids": ["Materials Science"],
            "language": "en",
            "model_name": model_name,
        },
    )
    assert response.status_code == 202, response.text
    view = response.json()
    run_dir = tmp_path / "science-runs" / view["run_id"]
    metadata = json.loads((run_dir / "science_run.json").read_text(encoding="utf-8"))
    research = metadata["immutable_inputs"]["options"]["research"]
    prompt_snapshot = research["prompt_snapshot"]
    config = OmegaConf.load(run_dir / "config.resolved.yaml")

    assert view["model_name"] == model_name
    assert view["prompt_profile"] == "research-default"
    assert view["prompt_version"] == prompt_snapshot["prompt_version"]
    assert view["prompt_hash"] == prompt_snapshot["prompt_hash"]
    assert research["model_name"] == model_name
    assert prompt_snapshot["prompt_id"] == "research-default"
    assert build_default_prompt_registry().get(
        "research-default", prompt_version=prompt_snapshot["prompt_version"]
    ).prompt_hash == prompt_snapshot["prompt_hash"]

    expected_model_paths = (
        "research_policy.model_name",
        "survey.APIInfo.llm_model_name",
        "survey.ModuleInfo.Judge.model",
        "idea.agent.model",
        "idea.mcts.generation_model",
        "idea.mcts.evaluation_model",
        "experiment_design.model",
        "research_plan_author.model",
        "quantitative_modeling.model",
        "quantitative_modeling.repair_model",
    )
    assert {path: _config_value(config, path) for path in expected_model_paths} == {
        path: model_name for path in expected_model_paths
    }


def test_research_job_enqueue_reads_frozen_config_after_service_config_changes(tmp_path: Path) -> None:
    app = create_app(run_root=tmp_path / "science-runs", serve_frontend=False)
    client = TestClient(app)
    created = client.post(
        "/api/runs",
        json={
            "run_id": "frozen-restart-run",
            "topic": "A restart must preserve the selected research model",
            "discipline_ids": ["Materials Science"],
            "model_name": "qwen3.8-max",
        },
    )
    assert created.status_code == 202, created.text

    science_service = app.state.science_service
    science_service.config_path = tmp_path / "current-default-that-must-not-be-read.yaml"
    science_service.runner.submit = lambda _job_id: False
    science_service.enqueue(
        run_id="frozen-restart-run",
        descriptor={"type": "workflow", "until": "survey"},
    )

    jobs = app.state.job_store.list(run_id="frozen-restart-run", kind="science")
    assert len(jobs) == 1
    assert jobs[0].model_name == "qwen3.8-max"
    assert jobs[0].prompt_id == "research-default"
