import re
from datetime import datetime
from pathlib import Path

from omegaconf import OmegaConf

from src.pipeline import run_loop
from src.research_run_ids import create_research_run_id


def test_research_run_id_is_compact_start_timestamp() -> None:
    run_id = create_research_run_id(datetime(2026, 8, 22, 10, 11, 12, 123456))

    assert run_id == "20260822-101112-123456"
    assert re.fullmatch(r"\d{8}-\d{6}-\d{6}", run_id)


def test_pipeline_automatic_directories_use_time_ids_and_keep_titles_in_metadata(monkeypatch) -> None:
    run_id = "20260822-101112-123456"
    monkeypatch.setattr(run_loop, "create_research_run_id", lambda: run_id)

    assert run_loop._generate_pipeline_name() == run_id
    assert run_loop._build_experiment_id(3, "A title that must not become a directory") == "iter_3_20260822-101112-123456"
    assert run_loop._build_experiment_id(3, "Another title", branch="replan") == "iter_3_replan_20260822-101112-123456"

    state = run_loop._init_pipeline_state(
        "workspace/pipeline_runs/20260822-101112-123456",
        "Original research topic",
        "",
        5,
        run_id,
    )
    assert state["research_run_id"] == run_id
    assert state["topic"] == "Original research topic"


def test_pipeline_survey_uses_runtime_config_for_hydra_sensitive_topic(tmp_path, monkeypatch) -> None:
    config_path = tmp_path / "pipeline.yaml"
    OmegaConf.save(
        OmegaConf.create(
            {
                "survey": {
                    "BasicInfo": {
                        "topic": "default",
                        "survey_run_id": "",
                        "base_dir": "",
                        "save_path": "",
                        "save_json_path": "",
                        "evaluation_save_path": "",
                    }
                }
            }
        ),
        config_path,
    )
    topic = "Can we design medicines (with customized doses)? risk=benefit [precision medicine]"
    captured: dict[str, object] = {}

    monkeypatch.setattr(run_loop, "_get_subprocess_env", lambda: {})

    def fake_run_command(command, env=None):
        captured["command"] = list(command)
        captured["env"] = dict(env or {})
        captured["runtime_config"] = OmegaConf.load(env["QWENSCI_CONFIG"])
        return 0

    monkeypatch.setattr(run_loop, "run_command", fake_run_command)

    assert run_loop.run_survey(topic, str(tmp_path / "survey-output"), str(config_path)) is True

    command = captured["command"]
    assert isinstance(command, list)
    assert not any("BasicInfo.topic=" in item for item in command)
    runtime_config = captured["runtime_config"]
    assert runtime_config.survey.BasicInfo.topic == topic
    assert re.fullmatch(r"\d{8}-\d{6}-\d{6}", runtime_config.survey.BasicInfo.survey_run_id)
    runtime_config_path = Path(captured["env"]["QWENSCI_CONFIG"])
    assert not runtime_config_path.exists()
