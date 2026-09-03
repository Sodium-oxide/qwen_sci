from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import ANY

import pytest
from omegaconf import OmegaConf

from src import cli


def _write_inputs(tmp_path: Path) -> tuple[Path, Path]:
    config_path = tmp_path / "config.yaml"
    OmegaConf.save(
        OmegaConf.create(
            {
                "experiment_design": {
                    "enabled": True,
                    "execution": {"allow_digital_execution": False},
                }
            }
        ),
        config_path,
    )
    idea_path = tmp_path / "idea_result.json"
    idea_path.write_text(
        json.dumps(
            {
                "schema_version": "idea_result_v5",
                "topic": "A test research topic",
                "primary_direction": "selected",
                "directions": [{"direction_mode": "selected", "title": "Selected direction"}],
            }
        ),
        encoding="utf-8",
    )
    return config_path, idea_path


def test_exp_design_parser_requires_idea_and_supports_repeated_disciplines() -> None:
    parser = cli._build_root_parser()

    args = parser.parse_args(
        [
            "exp_design",
            "--idea-json",
            "/mnt/c/project/run",
            "--discipline-id",
            "25",
            "--discipline-id",
            "26",
            "--selected-direction",
            "selected",
            "--brief-id",
            "brief-1",
            "--model",
            "test-model",
            "--output-dir",
            "/mnt/c/project/design-output",
            "--log-file",
            "/mnt/c/project/design-output/run.jsonl",
        ]
    )

    assert args.command == "exp_design"
    assert args.idea_json == "/mnt/c/project/run"
    assert args.discipline_id == ["25", "26"]
    assert args.selected_direction == "selected"
    assert args.brief_id == "brief-1"
    assert args.model == "test-model"
    assert args.output_dir == "/mnt/c/project/design-output"
    assert args.log_file == "/mnt/c/project/design-output/run.jsonl"


def test_exp_design_parser_requires_idea_json() -> None:
    parser = cli._build_root_parser()

    with pytest.raises(SystemExit) as error:
        parser.parse_args(["exp_design", "--discipline-id", "25"])

    assert error.value.code == 2


def test_exp_design_resolves_wsl_mount_paths() -> None:
    resolved = cli._resolve_cli_path("/mnt/c/Users/31390/research/idea_result.json")

    if os.name == "nt":
        assert resolved.drive.casefold() == "c:"
        assert resolved.as_posix().casefold().endswith("/users/31390/research/idea_result.json")
    else:
        assert resolved == Path("/mnt/c/Users/31390/research/idea_result.json").resolve()


def test_exp_design_accepts_run_directory_and_writes_full_design_artifacts(
    monkeypatch,
    tmp_path,
    capsys,
) -> None:
    config_path, idea_path = _write_inputs(tmp_path)
    run_directory = tmp_path / "idea-run"
    run_directory.mkdir()
    run_idea_path = run_directory / "idea_result.json"
    run_idea_path.write_bytes(idea_path.read_bytes())
    captured: dict[str, object] = {}

    class FakePaths:
        def __init__(self, timestamp: str) -> None:
            self.timestamp = timestamp

        def as_dict(self) -> dict[str, object]:
            return {
                "timestamp": self.timestamp,
                "experiment_design_json": "design.json",
                "experiment_design_markdown": "design.md",
                "author_json": "author.json",
            }

    def fake_run(path: str, **kwargs: object) -> dict[str, object]:
        captured["path"] = path
        captured["arguments"] = kwargs
        return {
            "status": "COMPLETED",
            "experiment_design": {
                "design_id": "design-1",
                "execution_policy": {"mode": "DESIGN_ONLY"},
                "observed_results": [],
            },
        }

    def fake_write(payload: object, output_dir: Path, **kwargs: object) -> FakePaths:
        captured["artifact_payload"] = payload
        captured["output_dir"] = output_dir
        captured["artifact_arguments"] = kwargs
        return FakePaths(str(kwargs["timestamp"]))

    import src.agents.experiment_design_agent.artifacts as artifacts_module
    import src.agents.experiment_design_agent.run as run_module

    monkeypatch.setattr(run_module, "run_experiment_design", fake_run)
    monkeypatch.setattr(artifacts_module, "write_experiment_design_artifacts", fake_write)
    parser = cli._build_root_parser()
    args = parser.parse_args(
        [
            "exp_design",
            "--config",
            str(config_path),
            "--idea-json",
            str(run_directory),
            "--discipline-id",
            "25",
        ]
    )

    assert cli._exp_design_command(args) == cli.EXP_DESIGN_EXIT_SUCCESS
    assert captured["path"] == str(run_idea_path.resolve())
    assert captured["arguments"] == {
        "discipline_ids": ["25"],
        "brief_id": None,
        "selected_direction": "",
        "config": ANY,
        "llm_model": None,
        "logger": ANY,
    }
    assert captured["output_dir"] == run_directory.resolve()
    artifact_arguments = captured["artifact_arguments"]
    assert isinstance(artifact_arguments, dict)
    assert artifact_arguments["idea_result_path"] == str(run_idea_path.resolve())
    stdout = json.loads(capsys.readouterr().out)
    assert stdout["execution_mode"] == "DESIGN_ONLY"
    assert stdout["observed_results_count"] == 0
    assert stdout["artifacts"]["timestamp"] == artifact_arguments["timestamp"]
    assert Path(stdout["log_file"]).is_file()


def test_exp_design_uses_explicit_discipline_ids_from_idea_result_when_flag_is_omitted(
    monkeypatch,
    tmp_path,
    capsys,
) -> None:
    config_path, idea_path = _write_inputs(tmp_path)
    payload = json.loads(idea_path.read_text(encoding="utf-8"))
    payload["discipline_ids"] = ["26"]
    idea_path.write_text(json.dumps(payload), encoding="utf-8")
    captured: dict[str, object] = {}

    class FakePaths:
        def as_dict(self) -> dict[str, object]:
            return {}

    def fake_run(*_args: object, **kwargs: object) -> dict[str, object]:
        captured.update(kwargs)
        return {
            "experiment_design": {
                "design_id": "design-1",
                "execution_policy": {"mode": "DESIGN_ONLY"},
                "observed_results": [],
            }
        }

    import src.agents.experiment_design_agent.artifacts as artifacts_module
    import src.agents.experiment_design_agent.run as run_module

    monkeypatch.setattr(run_module, "run_experiment_design", fake_run)
    monkeypatch.setattr(artifacts_module, "write_experiment_design_artifacts", lambda *_args, **_kwargs: FakePaths())
    parser = cli._build_root_parser()
    args = parser.parse_args(
        [
            "exp_design",
            "--config",
            str(config_path),
            "--idea-json",
            str(idea_path),
        ]
    )

    assert cli._exp_design_command(args) == cli.EXP_DESIGN_EXIT_SUCCESS
    assert captured["discipline_ids"] == ["26"]
    assert "DESIGN_ONLY" in capsys.readouterr().out


def test_exp_design_rejects_missing_discipline_without_guessing(
    tmp_path,
    capsys,
) -> None:
    config_path, idea_path = _write_inputs(tmp_path)
    parser = cli._build_root_parser()
    args = parser.parse_args(
        [
            "exp_design",
            "--config",
            str(config_path),
            "--idea-json",
            str(idea_path),
        ]
    )

    assert cli._exp_design_command(args) == cli.EXP_DESIGN_EXIT_SCOPE_ERROR
    assert "no discipline_ids" in capsys.readouterr().err


def test_exp_design_returns_scope_error_without_calling_orchestrator(
    monkeypatch,
    tmp_path,
    capsys,
) -> None:
    config_path, idea_path = _write_inputs(tmp_path)
    called = False

    def fail_if_called(**_: object) -> None:
        nonlocal called
        called = True

    import src.agents.experiment_design_agent as experiment_design_agent

    monkeypatch.setattr(experiment_design_agent, "ExperimentDesignOrchestrator", fail_if_called)
    parser = cli._build_root_parser()
    args = parser.parse_args(
        [
            "exp_design",
            "--config",
            str(config_path),
            "--idea-json",
            str(idea_path),
            "--discipline-id",
            "32",
        ]
    )

    assert cli._exp_design_command(args) == cli.EXP_DESIGN_EXIT_SCOPE_ERROR
    assert called is False
    assert "BLOCKED_BY_SCOPE" in capsys.readouterr().err


def test_exp_design_maps_required_llm_failure_to_nonzero_exit(
    monkeypatch,
    tmp_path,
    capsys,
) -> None:
    config_path, idea_path = _write_inputs(tmp_path)

    from src.agents.experiment_design_agent.llm_json import RequiredJsonLLMError

    def fail_run(*_args: object, **_kwargs: object) -> dict[str, object]:
        raise RequiredJsonLLMError("composer: LLM response was not JSON")

    import src.agents.experiment_design_agent.run as run_module

    monkeypatch.setattr(run_module, "run_experiment_design", fail_run)
    parser = cli._build_root_parser()
    args = parser.parse_args(
        [
            "exp_design",
            "--config",
            str(config_path),
            "--idea-json",
            str(idea_path),
            "--discipline-id",
            "25",
        ]
    )

    assert cli._exp_design_command(args) == cli.EXP_DESIGN_EXIT_LLM_ERROR
    assert "exp_design failed at run" in capsys.readouterr().err
