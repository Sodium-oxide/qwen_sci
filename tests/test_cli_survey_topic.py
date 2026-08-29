from pathlib import Path
import re

from omegaconf import OmegaConf

from src import cli


def test_survey_topic_with_hydra_sensitive_characters_uses_temporary_config(
    monkeypatch,
    tmp_path,
) -> None:
    config_path = tmp_path / "survey_config.yaml"
    OmegaConf.save(
        OmegaConf.create(
            {
                "survey": {
                    "output": {"root_dir": str(tmp_path / "outputs")},
                    "BasicInfo": {
                        "topic": "default topic",
                        "base_dir": "",
                        "save_path": "",
                        "save_json_path": "",
                        "evaluation_save_path": "",
                    },
                }
            }
        ),
        config_path,
    )
    topic = (
        "Can we design medicines (with customized doses)? "
        "Evidence: risk=benefit [precision medicine]\nSecond line."
    )
    parser = cli._build_root_parser()
    args = parser.parse_args(["survey", "--config", str(config_path), "--topic", topic])
    captured: dict[str, object] = {}

    def fake_run(command, *, env=None):
        captured["command"] = list(command)
        captured["env"] = dict(env or {})
        captured["runtime_config"] = OmegaConf.load(env["QWENSCI_CONFIG"])
        return 0

    monkeypatch.setattr(cli, "_run_command", fake_run)

    assert args.func(args) == 0

    command = captured["command"]
    assert isinstance(command, list)
    assert not any("BasicInfo.topic=" in item for item in command)
    config_path_index = command.index("--config-path")
    config_name_index = command.index("--config-name")
    runtime_directory = Path(command[config_path_index + 1])
    runtime_name = command[config_name_index + 1]
    runtime_config_path = runtime_directory / f"{runtime_name}.yaml"
    assert not runtime_config_path.exists()

    runtime_env = captured["env"]
    assert isinstance(runtime_env, dict)
    runtime_config = Path(runtime_env["QWENSCI_CONFIG"])
    assert runtime_config == runtime_config_path
    assert runtime_env["QWENSCI_CONFIG_PATH"] == str(runtime_config_path)
    runtime_config_payload = captured["runtime_config"]
    assert runtime_config_payload.survey.BasicInfo.topic == topic
    assert re.fullmatch(
        r"\d{8}-\d{6}-\d{6}",
        runtime_config_payload.survey.BasicInfo.survey_run_id,
    )
    assert runtime_config_payload.survey.BasicInfo.base_dir.endswith(
        runtime_config_payload.survey.BasicInfo.survey_run_id
    )


def test_temporary_config_round_trips_hydra_sensitive_topic_text(tmp_path) -> None:
    config_path = tmp_path / "base.yaml"
    OmegaConf.save(
        OmegaConf.create({"survey": {"BasicInfo": {"topic": "default"}}}),
        config_path,
    )
    topic = "A (B): C=1, D=[x]\n\"quoted\""

    runtime_path = cli._temporary_config(
        config_path,
        [("survey.BasicInfo.topic", topic)],
    )
    assert runtime_path is not None
    try:
        payload = OmegaConf.load(runtime_path)
        assert payload.survey.BasicInfo.topic == topic
    finally:
        Path(runtime_path).unlink(missing_ok=True)
