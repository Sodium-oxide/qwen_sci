"""Accept a new configuration snapshot and restart downstream science stages."""

import argparse
from copy import deepcopy
import json
from pathlib import Path
import shutil
import sys
import uuid


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from src.pipeline.science_run import (
    SCIENCE_STAGE_NAMES,
    ScienceRunConflictError,
    ScienceRunStateError,
    _resolved_config_yaml,
    _validate_science_state,
    append_science_event,
    atomic_write_json,
    atomic_write_text,
    file_sha256,
    invalidate_stages_from,
    is_stage_execution_active,
    load_science_run,
    locked_science_run,
    mark_stage_failed,
    save_science_state,
    science_run_paths,
    text_sha256,
    utc_now,
)


def rebase_config(run_dir, config_path, restart_from):
    paths = science_run_paths(run_dir)
    source = Path(config_path).expanduser().resolve()
    with locked_science_run(paths):
        metadata = json.loads(paths.run_metadata.read_text(encoding="utf-8"))
        state = json.loads(paths.state.read_text(encoding="utf-8"))
        _validate_science_state(state)
        if metadata.get("schema_version") != "science_run_v1" or metadata.get("science_run_id") != state["science_run_id"]:
            raise ScienceRunStateError("Run metadata and state do not identify the same supported science run")
        recorded_config = metadata.get("immutable_inputs", {}).get("config")
        if not isinstance(recorded_config, dict) or recorded_config.get("snapshot_path") != paths.config_snapshot.name:
            raise ScienceRunStateError("Run metadata has no valid configuration snapshot identity")
        if not paths.config_snapshot.is_file() or not source.is_file():
            raise ScienceRunStateError("Both the existing snapshot and replacement source must exist")
        if source == paths.config_snapshot:
            raise ScienceRunStateError("Provide the source configuration, not the existing snapshot")
        running = [name for name in SCIENCE_STAGE_NAMES if state["stages"][name]["status"] == "RUNNING"]
        active = [name for name in running if is_stage_execution_active(state["stages"][name])]
        if active:
            raise ScienceRunConflictError(
                "Stop the existing process before rebasing. Active or unverified stage owners: " + ", ".join(active)
            )
        old_config = deepcopy(recorded_config)
        actual_old_hash = file_sha256(paths.config_snapshot)
        source_hash = file_sha256(source)
        resolved = _resolved_config_yaml(source)
        if source_hash != file_sha256(source):
            raise ScienceRunConflictError("Source configuration changed while generating the replacement snapshot")
        timestamp = utc_now()
        backup_dir = paths.run_dir / "config_backups" / (timestamp.replace(":", "-") + "-" + uuid.uuid4().hex[:8])
        backup_dir.mkdir(parents=True, exist_ok=False)
        originals = (paths.config_snapshot, paths.run_metadata, paths.state, paths.events)
        for original in originals:
            if original.exists():
                shutil.copy2(original, backup_dir / original.name)
        recorded_config.update(
            source_path=str(source), source_sha256=source_hash,
            snapshot_sha256=text_sha256(resolved),
        )
        change = {
            "timestamp": timestamp, "reason": "User intentionally changed configuration and requested a new snapshot",
            "restart_from": restart_from, "previous_config": old_config,
            "previous_actual_snapshot_sha256": actual_old_hash,
            "new_config": deepcopy(recorded_config),
            "backup_directory": str(backup_dir.relative_to(paths.run_dir)),
        }
        metadata.setdefault("config_change_history", []).append(change)
        for name in running:
            mark_stage_failed(state, name, exit_code=1,
                              message="Execution owner no longer exists; accepting new configuration before restart",
                              error_type="InterruptedForConfigRebase")
        invalidate_stages_from(state, restart_from)
        try:
            atomic_write_text(paths.config_snapshot, resolved)
            atomic_write_json(paths.run_metadata, metadata)
            save_science_state(paths, state)
            load_science_run(paths)
            append_science_event(paths, event_type="CONFIG_SNAPSHOT_REBASED", **change)
            append_science_event(paths, event_type="STAGES_INVALIDATED", restart_from=restart_from)
        except Exception:
            for original in originals:
                backup = backup_dir / original.name
                if backup.exists():
                    atomic_write_text(original, backup.read_text(encoding="utf-8"))
            raise
    return backup_dir


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--config", default=str(REPO_ROOT / "src/config/default.yaml"))
    parser.add_argument("--restart-from", choices=SCIENCE_STAGE_NAMES, default="idea")
    args = parser.parse_args()
    try:
        backup_dir = rebase_config(args.run_dir, args.config, args.restart_from)
    except Exception as error:
        print(f"Configuration rebase failed: {error}", file=sys.stderr)
        return 1
    print(f"Configuration snapshot rebuilt and verified. Backup: {backup_dir}")
    print(f"Stages from {args.restart_from} are pending. Resume the run to execute them.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
