from __future__ import annotations

from pathlib import Path
import tomllib

from src import cli


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_qwensci_entrypoints_and_legacy_aliases_are_packaged() -> None:
    payload = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    project = payload["project"]
    scripts = project["scripts"]

    assert project["name"] == "qwen-sci"
    assert project["version"] == "0.2.0"
    assert scripts["qwensci"] == "src.cli:main"
    assert scripts["qwensci-survey"] == "src.cli:survey_main"
    assert scripts["qwensci-idea"] == "src.cli:idea_main"
    assert scripts["qwensci-experiment"] == "src.cli:experiment_main"
    assert scripts["qwensci-blog"] == "src.cli:blog_main"
    assert scripts["qwensci-pipeline"] == "src.cli:pipeline_main"
    assert scripts["qwensci-doctor"] == "src.cli:doctor_main"
    assert scripts["xcientist"] == "src.cli:legacy_main"
    assert scripts["xcientist-survey"] == "src.cli:legacy_survey_main"


def test_legacy_main_warns_on_stderr_and_delegates_to_the_root_cli(monkeypatch, capsys) -> None:
    captured: list[object] = []

    def fake_main(argv=None) -> int:
        captured.append(argv)
        return 17

    monkeypatch.setattr(cli, "main", fake_main)

    assert cli.legacy_main() == 17
    assert captured == [None]
    assert capsys.readouterr().err == (
        "DeprecationWarning: `xcientist` will be removed in a future release.\n"
        "Use `qwensci` instead.\n"
    )


def test_legacy_survey_warns_on_stderr_and_delegates_to_the_new_shortcut(monkeypatch, capsys) -> None:
    captured: list[object] = []

    def fake_main(argv=None) -> int:
        captured.append(argv)
        return 23

    monkeypatch.setattr(cli, "main", fake_main)
    monkeypatch.setattr(cli.sys, "argv", ["xcientist-survey", "--topic", "legacy smoke test"])

    assert cli.legacy_survey_main() == 23
    assert captured == [["survey", "--topic", "legacy smoke test"]]
    assert capsys.readouterr().err == (
        "DeprecationWarning: `xcientist-survey` will be removed in a future release.\n"
        "Use `qwensci-survey` instead.\n"
    )


def test_shell_wrappers_prefer_qwensci_before_legacy_commands() -> None:
    wrappers = {
        "run_survey.sh": "survey",
        "run_idea.sh": "idea",
        "run_experiment.sh": "experiment",
        "run_blog.sh": "blog",
        "run_pipeline.sh": "pipeline",
    }

    for filename, subcommand in wrappers.items():
        content = (REPO_ROOT / filename).read_text(encoding="utf-8")
        assert f"exec qwensci {subcommand}" in content
        assert f".venv/bin/qwensci\" {subcommand}" in content
        assert content.index("command -v qwensci") < content.index("command -v xcientist")


def test_runtime_environment_variables_use_the_qwensci_namespace() -> None:
    relevant_files = [
        REPO_ROOT / ".env.example",
        REPO_ROOT / "README.md",
        REPO_ROOT / "README_CN.md",
        REPO_ROOT / "src" / "config" / "default.yaml",
        REPO_ROOT / "src" / "config" / "__init__.py",
        REPO_ROOT / "src" / "cli.py",
        REPO_ROOT / "src" / "llm" / "provider_registry.py",
        REPO_ROOT / "src" / "llm" / "runtime_env.py",
        REPO_ROOT / "src" / "agents" / "experiment_agent" / "main.py",
        REPO_ROOT / "src" / "agents" / "experiment_agent" / "config.py",
        REPO_ROOT / "src" / "agents" / "experiment_agent" / "runtime" / "artifacts.py",
        REPO_ROOT / "src" / "agents" / "experiment_agent" / "runtime" / "finalization_hooks.py",
        REPO_ROOT / "src" / "agents" / "experiment_agent" / "runtime" / "openharness_runner.py",
        REPO_ROOT / "src" / "agents" / "idea_agent" / "agent" / "base.py",
        REPO_ROOT / "src" / "agents" / "blog_agent" / "README.md",
        REPO_ROOT / "src" / "pipeline" / "run_loop.py",
    ]

    for path in relevant_files:
        assert "XCIENTIST_" not in path.read_text(encoding="utf-8"), path

    assert "QWENSCI_LLM_PROVIDER" in (REPO_ROOT / ".env.example").read_text(encoding="utf-8")
    assert "QWENSCI_CONFIG" in (REPO_ROOT / "src" / "cli.py").read_text(encoding="utf-8")
    assert "QWENSCI_ARTIFACT_PATH" in (
        REPO_ROOT / "src" / "agents" / "experiment_agent" / "runtime" / "artifacts.py"
    ).read_text(encoding="utf-8")
