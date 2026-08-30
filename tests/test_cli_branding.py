from __future__ import annotations

from pathlib import Path
import tomllib

import pytest

from src import cli


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_supported_qwensci_entrypoints_are_packaged() -> None:
    payload = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    project = payload["project"]
    scripts = project["scripts"]

    assert project["name"] == "qwen-sci"
    assert project["version"] == "0.2.0"
    assert scripts["qwensci"] == "src.cli:main"
    assert scripts["qwensci-survey"] == "src.cli:survey_main"
    assert scripts["qwensci-idea"] == "src.cli:idea_main"
    assert scripts["qwensci-doctor"] == "src.cli:doctor_main"
    assert scripts["qwensci-install-mcp-wrappers"] == "src.cli:install_mcp_wrappers_main"
    assert "qwensci-experiment" not in scripts
    assert "qwensci-blog" not in scripts
    assert "qwensci-pipeline" not in scripts
    assert not any(name.startswith("xcientist") for name in scripts)


@pytest.mark.parametrize("command", ("experiment", "blog", "pipeline"))
def test_removed_cli_subcommands_are_not_accepted(command: str) -> None:
    with pytest.raises(SystemExit) as exc_info:
        cli.main([command])

    assert exc_info.value.code == 2


def test_shell_wrappers_use_qwensci_without_xcientist_fallbacks() -> None:
    wrappers = {
        "run_survey.sh": "survey",
        "run_idea.sh": "idea",
    }

    for filename, subcommand in wrappers.items():
        content = (REPO_ROOT / filename).read_text(encoding="utf-8")
        assert f"exec qwensci {subcommand}" in content
        assert f".venv/bin/qwensci\" {subcommand}" in content

    for filename in (
        "run_survey.sh",
        "run_idea.sh",
        "run_experiment.sh",
        "run_blog.sh",
        "run_pipeline.sh",
    ):
        assert "xcientist" not in (REPO_ROOT / filename).read_text(encoding="utf-8")


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
