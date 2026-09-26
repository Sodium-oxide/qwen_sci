from copy import deepcopy
import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from scripts import rebase_science_run_config as recovery
from src.pipeline.science_run import _new_science_state


def recovery_context(monkeypatch):
    state = _new_science_state("config-rebase-test")
    metadata = {
        "schema_version": "science_run_v1", "science_run_id": state["science_run_id"],
        "immutable_inputs": {"config": {"snapshot_path": "config.resolved.yaml",
                                       "snapshot_sha256": "original", "source_path": "old.yaml"}},
    }
    paths = SimpleNamespace(**{name: MagicMock() for name in
                             ("run_dir", "run_metadata", "state", "config_snapshot", "events")})
    paths.config_snapshot.name = "config.resolved.yaml"
    paths.run_metadata.read_text.side_effect = lambda **kwargs: json.dumps(metadata)
    paths.state.read_text.side_effect = lambda **kwargs: json.dumps(state)
    source = MagicMock()
    source.expanduser.return_value.resolve.return_value = source
    monkeypatch.setattr(recovery, "Path", lambda value: source)
    monkeypatch.setattr(recovery, "science_run_paths", lambda value: paths)
    monkeypatch.setattr(recovery, "locked_science_run", MagicMock())
    monkeypatch.setattr(recovery, "file_sha256", lambda path: "source-hash" if path is source else "changed-snapshot")
    monkeypatch.setattr(recovery, "_resolved_config_yaml", lambda path: "setting: new\n")
    helpers = {}
    for name in ("atomic_write_text", "atomic_write_json", "save_science_state", "load_science_run", "append_science_event"):
        helpers[name] = MagicMock()
        monkeypatch.setattr(recovery, name, helpers[name])
    copier = MagicMock()
    monkeypatch.setattr(recovery.shutil, "copy2", copier)
    return state, metadata, paths, helpers, copier


def test_rebase_backs_up_config_records_history_and_restarts_idea(monkeypatch):
    state, metadata, paths, helpers, copier = recovery_context(monkeypatch)
    state["stages"]["survey"]["status"] = "FAILED"
    state["stages"]["idea"]["status"] = "FAILED"
    state["stages"]["idea"]["attempt"] = 1
    original_survey = deepcopy(state["stages"]["survey"])
    recovery.rebase_config("run", "config", "idea")
    assert copier.call_count == 4
    assert helpers["atomic_write_text"].call_args.args == (paths.config_snapshot, "setting: new\n")
    new_metadata = helpers["atomic_write_json"].call_args.args[1]
    assert new_metadata["immutable_inputs"]["config"]["snapshot_sha256"] == recovery.text_sha256("setting: new\n")
    history = new_metadata["config_change_history"][0]
    assert history["previous_config"] == metadata["immutable_inputs"]["config"]
    assert history["previous_actual_snapshot_sha256"] == "changed-snapshot"
    new_state = helpers["save_science_state"].call_args.args[1]
    assert new_state["stages"]["survey"] == original_survey
    assert new_state["stages"]["idea"]["status"] == "PENDING"
    assert new_state["stages"]["idea"]["invalidated_attempts"][0]["attempt"] == 1
    assert helpers["load_science_run"].call_count == 1
    assert [call.kwargs["event_type"] for call in helpers["append_science_event"].call_args_list] == [
        "CONFIG_SNAPSHOT_REBASED", "STAGES_INVALIDATED",
    ]


@pytest.mark.parametrize("active", [True, False])
def test_running_stage_requires_confirmed_dead_execution_owner(monkeypatch, active):
    state, metadata, paths, helpers, copier = recovery_context(monkeypatch)
    state["stages"]["exp_design"].update(status="RUNNING", attempt=9)
    monkeypatch.setattr(recovery, "is_stage_execution_active", lambda stage: active)
    if active:
        with pytest.raises(recovery.ScienceRunConflictError, match="Stop the existing process"):
            recovery.rebase_config("run", "config", "idea")
        assert not copier.called
        assert not helpers["atomic_write_text"].called
    else:
        recovery.rebase_config("run", "config", "idea")
        stage = helpers["save_science_state"].call_args.args[1]["stages"]["exp_design"]
        assert stage["status"] == "PENDING"
        old = stage["invalidated_attempts"][0]
        assert old["attempt"] == 9
        assert old["failure"]["error_type"] == "InterruptedForConfigRebase"


def test_failed_validation_restores_backed_up_files(monkeypatch):
    state, metadata, paths, helpers, copier = recovery_context(monkeypatch)
    helpers["load_science_run"].side_effect = ValueError("validation failed")
    with pytest.raises(ValueError, match="validation failed"):
        recovery.rebase_config("run", "config", "idea")
    assert helpers["atomic_write_text"].call_count == 5
    assert not helpers["append_science_event"].called
