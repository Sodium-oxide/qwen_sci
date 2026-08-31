from __future__ import annotations

import copy
import json
import os
import socket
from pathlib import Path

import pytest
from omegaconf import OmegaConf

from src import cli
from src.config import REPO_ROOT
from src.pipeline import science_run
from src.pipeline.science_workflow import ScienceWorkflowOutcome


def _write_config(tmp_path: Path, *, model: str = "test-model") -> Path:
    config_path = tmp_path / "science.yaml"
    OmegaConf.save(
        OmegaConf.create({"research": {"model": model, "enabled": True}}),
        config_path,
    )
    return config_path


def _initialize_run(tmp_path: Path) -> tuple[Path, Path]:
    config_path = _write_config(tmp_path)
    output_root = tmp_path / "science-runs"
    paths, _metadata, _state = science_run.initialize_science_run(
        output_root=output_root,
        topic="verified research topic",
        config_path=config_path,
        immutable_options={"discipline_ids": ["25"]},
        run_id="demo-run",
    )
    return config_path, paths.run_dir


def test_science_parser_exposes_the_four_stage_contract() -> None:
    parser = cli._build_root_parser()

    args = parser.parse_args(
        [
            "science",
            "--topic",
            "topic",
            "--discipline-id",
            "25",
            "--discipline-id",
            "26",
            "--selected-direction",
            "direction-1",
            "--exp-design-model",
            "design-model",
            "--author-model",
            "author-model",
            "--until",
            "exp_design",
            "--survey-appendix",
            "full-text",
        ]
    )

    assert args.command == "science"
    assert args.discipline_id == ["25", "26"]
    assert args.selected_direction == "direction-1"
    assert args.exp_design_model == "design-model"
    assert args.author_model == "author-model"
    assert args.until == "exp_design"
    assert args.survey_appendix == "full-text"


def test_science_parser_exposes_required_rendering() -> None:
    args = cli._build_root_parser().parse_args(
        ["science", "--topic", "topic", "--render-required"]
    )

    assert args.render_required is True


def test_science_parser_exposes_the_seven_page_report_policy() -> None:
    args = cli._build_root_parser().parse_args(
        ["science", "--topic", "topic", "--minimum-pages", "8"]
    )

    assert args.minimum_pages == 8
    assert science_run.normalize_immutable_options({"minimum_pages": args.minimum_pages})[
        "author_rendering"
    ]["minimum_pages"] == 7


def test_science_initialization_publishes_pending_state_and_config_snapshot(tmp_path) -> None:
    config_path, run_dir = _initialize_run(tmp_path)

    metadata = json.loads((run_dir / "science_run.json").read_text(encoding="utf-8"))
    state = json.loads((run_dir / "science_state.json").read_text(encoding="utf-8"))
    events = [
        json.loads(line)
        for line in (run_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()
    ]

    assert metadata["immutable_inputs"]["topic"] == "verified research topic"
    assert metadata["immutable_inputs"]["config"]["source_path"] == str(config_path.resolve())
    assert state["status"] == "PENDING"
    assert set(state["stages"]) == set(science_run.SCIENCE_STAGE_NAMES)
    assert all(stage["status"] == "PENDING" for stage in state["stages"].values())
    assert (run_dir / "config.resolved.yaml").is_file()
    assert not (run_dir / "lock").exists()
    assert events == [
        {
            "event_type": "RUN_INITIALIZED",
            "execution_mode": "DESIGN_ONLY",
            "science_run_id": "demo-run",
            "timestamp": events[0]["timestamp"],
        }
    ]


def test_science_initialization_resolves_project_path_placeholders(tmp_path) -> None:
    config_path = tmp_path / "science.yaml"
    config_path.write_text(
        "project:\n  root: ${repo_root}\nworkspace:\n  root: ${repo_root}/workspace\n",
        encoding="utf-8",
    )

    paths, _metadata, _state = science_run.initialize_science_run(
        output_root=tmp_path / "science-runs",
        topic="placeholder resolution",
        config_path=config_path,
        immutable_options={"discipline_ids": ["24"]},
        run_id="placeholder-resolution",
    )

    snapshot = OmegaConf.to_container(OmegaConf.load(paths.config_snapshot), resolve=True)
    assert snapshot["project"]["root"] == str(REPO_ROOT)
    assert Path(snapshot["workspace"]["root"]).resolve() == REPO_ROOT / "workspace"


def test_science_resume_rejects_a_changed_explicit_config(tmp_path, capsys) -> None:
    config_path, run_dir = _initialize_run(tmp_path)
    capsys.readouterr()
    OmegaConf.save(OmegaConf.create({"research": {"model": "changed"}}), config_path)

    assert (
        cli.main(
            [
                "science",
                "--resume",
                str(run_dir),
                "--config",
                str(config_path),
            ]
        )
        == cli.SCIENCE_EXIT_INPUT_ERROR
    )

    assert "Resume config differs" in capsys.readouterr().err


def test_science_resume_rejects_changed_required_rendering(tmp_path, capsys) -> None:
    _config_path, run_dir = _initialize_run(tmp_path)

    assert (
        cli.main(["science", "--resume", str(run_dir), "--render-required"])
        == cli.SCIENCE_EXIT_INPUT_ERROR
    )

    assert "Resume render_required differs" in capsys.readouterr().err


def test_science_resume_accepts_the_same_required_rendering_policy(tmp_path) -> None:
    config_path = _write_config(tmp_path)
    _paths, metadata, _state = science_run.initialize_science_run(
        output_root=tmp_path / "science-runs",
        topic="verified research topic",
        config_path=config_path,
        immutable_options={"discipline_ids": ["25"], "render_required": True},
        run_id="required-rendering",
    )

    science_run.validate_resume_inputs(
        metadata,
        config_path=None,
        explicit_options={"render_required": True},
    )


def test_science_resume_restart_keeps_attempt_history_and_invalidates_downstream(tmp_path, capsys, monkeypatch) -> None:
    _config_path, run_dir = _initialize_run(tmp_path)
    paths = science_run.science_run_paths(run_dir)
    metadata, state = science_run.load_science_run(paths)
    state["status"] = "FAILED"
    state["stages"]["idea"].update(
        {
            "status": "COMPLETED",
            "attempt": 2,
            "started_at": "2026-08-29T00:00:00Z",
            "finished_at": "2026-08-29T00:01:00Z",
            "input_identity": {"idea": "old"},
            "result_manifest_path": "idea/attempt-002/idea_manifest.json",
            "outputs": {"idea_result": "idea/attempt-002/idea_result.json"},
        }
    )
    with science_run.locked_science_run(paths):
        science_run.save_science_state(paths, state)

    def do_not_execute_services(*, paths, metadata, **_kwargs) -> ScienceWorkflowOutcome:
        _loaded_metadata, current_state = science_run.load_science_run(paths)
        return ScienceWorkflowOutcome(metadata=metadata, state=current_state)

    monkeypatch.setattr(cli, "run_science_workflow", do_not_execute_services)

    assert (
        cli.main(
            [
                "science",
                "--resume",
                str(run_dir),
                "--restart-from",
                "idea",
                "--force",
                "--json",
            ]
        )
        == cli.SCIENCE_EXIT_SUCCESS
    )

    result = json.loads(capsys.readouterr().out)
    _metadata, resumed_state = science_run.load_science_run(paths)
    invalidated = resumed_state["stages"]["idea"]["invalidated_attempts"]

    assert metadata["science_run_id"] == "demo-run"
    assert result["action"] == "RESTART_INVALIDATED"
    assert resumed_state["status"] == "PENDING"
    assert resumed_state["stages"]["survey"]["status"] == "PENDING"
    assert resumed_state["stages"]["idea"]["status"] == "PENDING"
    assert resumed_state["stages"]["idea"]["attempt"] == 2
    assert invalidated[0]["attempt"] == 2
    assert invalidated[0]["result_manifest_path"].endswith("idea_manifest.json")
    assert resumed_state["restart_history"][0]["invalidated_stages"] == [
        "idea",
        "exp_design",
        "author",
    ]


def test_science_restart_rejects_any_run_with_an_active_stage(tmp_path, capsys) -> None:
    _config_path, run_dir = _initialize_run(tmp_path)
    paths = science_run.science_run_paths(run_dir)
    with science_run.locked_science_run(paths):
        _metadata, state = science_run.load_science_run(paths)
        science_run.mark_stage_running(state, "survey", input_identity={})
        science_run.save_science_state(paths, state)

    assert (
        cli.main(
            [
                "science",
                "--resume",
                str(run_dir),
                "--restart-from",
                "survey",
                "--force",
            ]
        )
        == cli.SCIENCE_EXIT_INPUT_ERROR
    )

    assert "while stages are still running: survey" in capsys.readouterr().err


def test_science_rejects_restart_without_resume(tmp_path, capsys) -> None:
    config_path = _write_config(tmp_path)

    assert (
        cli.main(
            [
                "science",
                "--topic",
                "topic",
                "--config",
                str(config_path),
                "--restart-from",
                "idea",
                "--force",
            ]
        )
        == cli.SCIENCE_EXIT_INPUT_ERROR
    )

    assert "only valid with --resume --force" in capsys.readouterr().err


def test_science_state_write_is_atomic_when_replace_fails(tmp_path, monkeypatch) -> None:
    config_path = _write_config(tmp_path)
    paths, _metadata, state = science_run.initialize_science_run(
        output_root=tmp_path,
        topic="topic",
        config_path=config_path,
        immutable_options={},
        run_id="atomic-run",
    )
    before = paths.state.read_text(encoding="utf-8")
    updated_state = copy.deepcopy(state)
    updated_state["status"] = "RUNNING"

    def fail_replace(*_args: object, **_kwargs: object) -> None:
        raise OSError("simulated replace failure")

    monkeypatch.setattr(science_run.os, "replace", fail_replace)

    with pytest.raises(OSError, match="simulated replace failure"):
        science_run.save_science_state(paths, updated_state)

    assert paths.state.read_text(encoding="utf-8") == before
    assert not list(paths.run_dir.glob(".science_state.json.*.tmp"))


def test_science_initialization_failure_can_retry_the_same_run_id(tmp_path, monkeypatch) -> None:
    config_path = _write_config(tmp_path)
    output_root = tmp_path / "science-runs"

    def fail_event(*_args: object, **_kwargs: object) -> None:
        raise OSError("simulated event write failure")

    with monkeypatch.context() as scoped:
        scoped.setattr(science_run, "append_science_event", fail_event)
        with pytest.raises(OSError, match="simulated event write failure"):
            science_run.initialize_science_run(
                output_root=output_root,
                topic="topic",
                config_path=config_path,
                immutable_options={},
                run_id="retry-run",
            )

    paths, metadata, state = science_run.initialize_science_run(
        output_root=output_root,
        topic="topic",
        config_path=config_path,
        immutable_options={},
        run_id="retry-run",
    )

    assert paths.run_dir.is_dir()
    assert metadata["science_run_id"] == "retry-run"
    assert state["status"] == "PENDING"


def test_science_resume_reports_malformed_stage_state_as_a_runtime_error(tmp_path, capsys) -> None:
    _config_path, run_dir = _initialize_run(tmp_path)
    capsys.readouterr()
    paths = science_run.science_run_paths(run_dir)
    state = json.loads(paths.state.read_text(encoding="utf-8"))
    del state["stages"]["survey"]["attempt"]
    paths.state.write_text(json.dumps(state), encoding="utf-8")

    assert cli.main(["science", "--resume", str(run_dir)]) == cli.SCIENCE_EXIT_RUNTIME_ERROR

    assert "invalid survey attempt" in capsys.readouterr().err


def test_science_persists_result_summary_for_stage_failure(tmp_path, monkeypatch, capsys) -> None:
    config_path = _write_config(tmp_path)

    def fail_workflow(**_kwargs) -> ScienceWorkflowOutcome:
        from src.pipeline.science_workflow import ScienceWorkflowError

        raise ScienceWorkflowError("idea", 21, "simulated Idea failure")

    monkeypatch.setattr(cli, "run_science_workflow", fail_workflow)

    assert (
        cli.main(
            [
                "science",
                "--topic",
                "result topic",
                "--config",
                str(config_path),
                "--output-root",
                str(tmp_path / "science-runs"),
                "--run-id",
                "failed-result",
                "--json",
            ]
        )
        == 21
    )

    assert json.loads(capsys.readouterr().out)["error"]["stage"] == "idea"
    result = json.loads(
        (tmp_path / "science-runs" / "failed-result" / "science_result.json").read_text(
            encoding="utf-8"
        )
    )
    assert result["error"] == {
        "stage": "idea",
        "exit_code": 21,
        "message": "simulated Idea failure",
    }


def test_stale_resume_failure_does_not_overwrite_a_completed_run_result(tmp_path, monkeypatch, capsys) -> None:
    config_path = _write_config(tmp_path)

    def stale_resume_failure(**kwargs) -> ScienceWorkflowOutcome:
        paths = kwargs["paths"]
        metadata = kwargs["metadata"]
        with science_run.locked_science_run(paths):
            _persisted_metadata, state = science_run.load_science_run(paths)
            science_run.mark_stage_running(state, "survey", input_identity={})
            science_run.save_science_state(paths, state)
            observed_state = copy.deepcopy(state)
            del observed_state["revision"]
            state["status"] = "COMPLETED"
            state["stages"]["survey"].update(
                {"status": "COMPLETED", "execution_owner": None}
            )
            science_run.save_science_state(paths, state)
            completed_result = cli._science_result_payload(
                action="EXECUTED",
                paths=paths,
                metadata=metadata,
                state=state,
                until="author",
            )
            science_run.atomic_write_json(paths.result, completed_result)
        from src.pipeline.science_workflow import ScienceWorkflowError

        raise ScienceWorkflowError(
            "survey",
            10,
            "survey is still running under process 999",
            observed_state=observed_state,
        )

    monkeypatch.setattr(cli, "run_science_workflow", stale_resume_failure)

    assert (
        cli.main(
            [
                "science",
                "--topic",
                "result topic",
                "--config",
                str(config_path),
                "--output-root",
                str(tmp_path / "science-runs"),
                "--run-id",
                "stale-resume-result",
                "--json",
            ]
        )
        == 10
    )

    reported = json.loads(capsys.readouterr().out)
    persisted = json.loads(
        (tmp_path / "science-runs" / "stale-resume-result" / "science_result.json").read_text(
            encoding="utf-8"
        )
    )
    assert reported["status"] == "RUNNING"
    assert reported["error"]["stage"] == "survey"
    assert persisted["status"] == "COMPLETED"
    assert "error" not in persisted


def test_science_normalizes_wsl_and_windows_template_paths_equally() -> None:
    parser = cli._build_root_parser()
    windows_path = r"C:\Users\researcher\template"
    wsl_path = "/mnt/c/Users/researcher/template"

    windows_args = parser.parse_args(
        ["science", "--topic", "topic", "--template-dir", windows_path, "--latex-engine", r"C:\Tools\pdflatex.exe"]
    )
    wsl_args = parser.parse_args(
        ["science", "--topic", "topic", "--template-dir", wsl_path, "--latex-engine", "/mnt/c/Tools/pdflatex.exe"]
    )

    assert cli._science_immutable_options(windows_args) == cli._science_immutable_options(wsl_args)


def test_science_run_lock_rejects_a_second_live_owner(tmp_path) -> None:
    config_path = _write_config(tmp_path)
    paths, _metadata, _state = science_run.initialize_science_run(
        output_root=tmp_path,
        topic="topic",
        config_path=config_path,
        immutable_options={},
        run_id="lock-run",
    )

    with science_run.locked_science_run(paths):
        with pytest.raises(science_run.ScienceRunLockError, match="Science run is locked"):
            with science_run.locked_science_run(paths):
                pass


def test_science_run_lock_reclaims_a_stale_owner_while_holding_its_guard(tmp_path) -> None:
    config_path = _write_config(tmp_path)
    paths, _metadata, _state = science_run.initialize_science_run(
        output_root=tmp_path,
        topic="topic",
        config_path=config_path,
        immutable_options={},
        run_id="stale-lock-run",
    )
    paths.lock.write_text(
        json.dumps(
            {
                "schema_version": "science_run_lock_v1",
                "owner_id": "stale-owner",
                "pid": 999_999_999,
                "hostname": socket.gethostname(),
                "acquired_at": "2026-08-29T00:00:00Z",
            }
        ),
        encoding="utf-8",
    )

    with science_run.locked_science_run(paths):
        owner = json.loads(paths.lock.read_text(encoding="utf-8"))
        assert owner["owner_id"] != "stale-owner"
        assert owner["pid"] == os.getpid()
