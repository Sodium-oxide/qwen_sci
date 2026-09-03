from __future__ import annotations

from pathlib import Path

import pytest
from omegaconf import OmegaConf

from src import cli


def test_cli_rejects_remote_consent_without_explicit_multimodal_input(capsys) -> None:
    assert cli.main(["survey", "--allow-remote-perception"]) == 2
    assert "requires --multimodal-file or --multimodal-evidence-manifest" in capsys.readouterr().err


def test_cli_rejects_file_and_manifest_together(tmp_path) -> None:
    with pytest.raises(SystemExit) as exc_info:
        cli.main(
            [
                "survey",
                "--multimodal-file",
                str(tmp_path / "file.png"),
                "--multimodal-evidence-manifest",
                str(tmp_path / "manifest.json"),
            ]
        )
    assert exc_info.value.code == 2


def test_cli_passes_explicit_input_as_local_only_temporary_configuration(monkeypatch, tmp_path) -> None:
    Image = pytest.importorskip("PIL.Image")
    image_path = tmp_path / "sample.png"
    Image.new("RGB", (2, 2), "white").save(image_path)
    captured: dict[str, object] = {}

    def fake_run(command, *, env):
        config_directory = Path(command[command.index("--config-path") + 1])
        config_name = command[command.index("--config-name") + 1]
        captured["config"] = OmegaConf.to_container(
            OmegaConf.load(config_directory / f"{config_name}.yaml"),
            resolve=False,
        )
        captured["env"] = env
        return 0

    monkeypatch.setattr(cli, "_run_command", fake_run)
    monkeypatch.setattr(
        cli,
        "build_multimodal_evidence",
        lambda **_kwargs: {
            "schema_version": "multimodal_evidence_v1",
            "perception": {"mode": "remote_perception", "provider": "qwen", "model": "qwen3-vl-plus"},
            "native_findings": [],
            "observations": [],
            "claims": [],
            "limitations": [],
        },
    )

    assert (
        cli.main(
            [
                "survey",
                "--multimodal-file",
                str(image_path),
                "--allow-remote-perception",
            ]
        )
        == 0
    )

    config = captured["config"]
    multimodal = config["survey"]["multimodal_evidence"]
    assert multimodal["enabled"] is True
    assert multimodal["allow_remote_perception"] is True
    assert "source_path" not in str(multimodal["input_spec"])
    assert multimodal["input_spec"]["records"][0]["source_name"] == image_path.name
    assert "source_path" not in str(multimodal["local_input_context"])
    assert multimodal["local_input_context"]["mode"] == "local_only"
    assert multimodal["local_input_context"]["remote_perception_authorized"] is True
    assert multimodal["runtime_evidence"]["perception"]["model"] == "qwen3-vl-plus"


def test_cli_forces_default_closed_without_multimodal_input(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_run(command, *, env):
        config_directory = Path(command[command.index("--config-path") + 1])
        config_name = command[command.index("--config-name") + 1]
        captured["config"] = OmegaConf.to_container(
            OmegaConf.load(config_directory / f"{config_name}.yaml"),
            resolve=False,
        )
        return 0

    def unexpected(*_args, **_kwargs):
        raise AssertionError("local analysis must not start without an explicit multimodal input")

    monkeypatch.setattr(cli, "_run_command", fake_run)
    monkeypatch.setattr(cli, "build_local_multimodal_input_context", unexpected)
    monkeypatch.setattr(cli, "build_multimodal_evidence", unexpected)
    monkeypatch.setattr(cli, "preflight_multimodal_capabilities", unexpected)

    assert cli.main(["survey"]) == 0

    multimodal = captured["config"]["survey"]["multimodal_evidence"]
    assert multimodal["enabled"] is False
    assert multimodal["allow_remote_perception"] is False
    assert multimodal["input_spec"] == {}
    assert multimodal["local_input_context"] == {}
    assert multimodal["runtime_evidence"] == {}


def test_cli_ignores_invalid_legacy_multimodal_settings_without_explicit_input(
    monkeypatch,
    tmp_path,
) -> None:
    config_path = tmp_path / "survey-config.yaml"
    config = OmegaConf.load(cli.DEFAULT_CONFIG_PATH)
    config.survey.multimodal_evidence.max_records_per_modality = 0
    OmegaConf.save(config, config_path)

    monkeypatch.setattr(cli, "_run_command", lambda _command, *, env: 0)

    assert cli.main(["survey", "--config", str(config_path)]) == 0


def test_cli_reports_capability_preflight_errors_before_native_analysis(monkeypatch, tmp_path, capsys) -> None:
    image_path = tmp_path / "sample.png"
    image_path.write_bytes(b"not read before preflight")

    def unavailable(*_args, **_kwargs):
        raise cli.MultimodalInputError(
            "Multimodal capability unavailable for explicit image analysis: missing Pillow. "
            "Install it with: uv sync --group multimodal"
        )

    def unexpected(*_args, **_kwargs):
        raise AssertionError("native analysis must not start after a failed capability preflight")

    monkeypatch.setattr(cli, "preflight_multimodal_capabilities", unavailable)
    monkeypatch.setattr(cli, "build_local_multimodal_input_context", unexpected)

    assert cli.main(["survey", "--multimodal-file", str(image_path)]) == 2

    error = capsys.readouterr().err
    assert "Multimodal input error" in error
    assert "uv sync --group multimodal" in error


def test_cli_help_describes_explicit_multimodal_installation_and_remote_model() -> None:
    parser = cli._build_root_parser()
    survey_parser = next(
        choices["survey"]
        for action in parser._actions
        if isinstance((choices := getattr(action, "choices", None)), dict) and "survey" in choices
    )
    help_text = survey_parser.format_help()
    normalized_help = " ".join(help_text.split())

    assert "uv sync --group multimodal" in normalized_help
    assert "qwen3-vl-plus" in normalized_help


def test_cli_rejects_positional_overrides_of_multimodal_runtime_state(capsys) -> None:
    assert cli.main(["survey", "survey.multimodal_evidence.enabled=true"]) == 2
    assert "cannot be overridden positionally" in capsys.readouterr().err


def test_cli_resets_a_manually_enabled_multimodal_config_without_explicit_input(
    monkeypatch,
    tmp_path,
) -> None:
    config_path = tmp_path / "survey-config.yaml"
    config = OmegaConf.load(cli.DEFAULT_CONFIG_PATH)
    config.survey.multimodal_evidence.enabled = True
    config.survey.multimodal_evidence.allow_remote_perception = True
    config.survey.multimodal_evidence.input_spec = {"stale": True}
    config.survey.multimodal_evidence.local_input_context = {"stale": True}
    config.survey.multimodal_evidence.runtime_evidence = {"stale": True}
    OmegaConf.save(config, config_path)
    captured: dict[str, object] = {}

    def fake_run(command, *, env):
        config_directory = Path(command[command.index("--config-path") + 1])
        config_name = command[command.index("--config-name") + 1]
        captured["config"] = OmegaConf.to_container(
            OmegaConf.load(config_directory / f"{config_name}.yaml"),
            resolve=False,
        )
        return 0

    monkeypatch.setattr(cli, "_run_command", fake_run)

    assert cli.main(["survey", "--config", str(config_path)]) == 0

    multimodal = captured["config"]["survey"]["multimodal_evidence"]
    assert multimodal["enabled"] is False
    assert multimodal["allow_remote_perception"] is False
    assert multimodal["input_spec"] == {}
    assert multimodal["local_input_context"] == {}
    assert multimodal["runtime_evidence"] == {}
