"""Persistent state primitives for the design-only science workflow."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import socket
import tempfile
import uuid
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from filelock import FileLock, Timeout
from omegaconf import OmegaConf
import psutil

from src.config import load_config
from src.agents.research_plan_author.page_policy import PagePolicyError, normalize_minimum_pages
from src.research_run_ids import create_research_run_id


SCIENCE_RUN_SCHEMA_VERSION = "science_run_v1"
SCIENCE_STATE_SCHEMA_VERSION = "science_state_v1"
SCIENCE_RESULT_SCHEMA_VERSION = "science_run_result_v1"
SCIENCE_STAGE_NAMES = ("survey", "idea", "exp_design", "author")
SURVEY_APPENDIX_MODES = ("source-link", "full-text")
_RUN_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}")


class ScienceRunError(RuntimeError):
    """Base error for science run persistence."""


class ScienceRunInputError(ScienceRunError):
    """Raised when a new science run cannot be initialized."""


class ScienceRunConflictError(ScienceRunError):
    """Raised when an existing run cannot safely be reused."""


class ScienceRunLockError(ScienceRunError):
    """Raised when another process owns a science run lock."""


class ScienceRunStateError(ScienceRunError):
    """Raised when persisted science run metadata is malformed."""


@dataclass(frozen=True)
class ScienceRunPaths:
    """Filesystem locations belonging to one science run."""

    run_dir: Path
    run_metadata: Path
    state: Path
    result: Path
    config_snapshot: Path
    events: Path
    lock: Path
    lock_guard: Path


def utc_now() -> str:
    """Return an RFC 3339 timestamp with a UTC suffix."""

    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def file_sha256(path: Path) -> str:
    """Return the SHA-256 digest of a file without loading it all at once."""

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def text_sha256(value: str) -> str:
    """Return the SHA-256 digest of UTF-8 text."""

    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def science_run_paths(run_dir: str | Path) -> ScienceRunPaths:
    """Build the canonical path set for an existing or future run directory."""

    root = Path(run_dir).expanduser().resolve()
    return ScienceRunPaths(
        run_dir=root,
        run_metadata=root / "science_run.json",
        state=root / "science_state.json",
        result=root / "science_result.json",
        config_snapshot=root / "config.resolved.yaml",
        events=root / "events.jsonl",
        lock=root / "lock",
        lock_guard=root / ".science_run.guard",
    )


def _sync_directory(directory: Path) -> None:
    if os.name == "nt":
        return
    try:
        descriptor = os.open(str(directory), os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def atomic_write_text(path: Path, content: str) -> None:
    """Durably replace a UTF-8 file so readers never observe partial content."""

    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
        text=True,
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
        _sync_directory(path.parent)
    finally:
        temporary_path.unlink(missing_ok=True)


def atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    """Atomically publish a JSON object with deterministic formatting."""

    content = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
    atomic_write_text(path, f"{content}\n")


def _load_json_object(path: Path, *, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ScienceRunStateError(f"Missing {label}: {path}") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise ScienceRunStateError(f"Cannot read {label}: {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ScienceRunStateError(f"{label} must contain a JSON object: {path}")
    return payload


def _validate_run_id(run_id: str) -> str:
    normalized = str(run_id).strip()
    if not _RUN_ID_PATTERN.fullmatch(normalized):
        raise ScienceRunInputError(
            "run_id must contain 1-128 letters, digits, underscores, or hyphens and start with a letter or digit"
        )
    return normalized


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    return str(value).strip()


def normalize_immutable_options(options: Mapping[str, object]) -> dict[str, Any]:
    """Normalize user-controlled inputs that must not drift across resume."""

    discipline_ids = options.get("discipline_ids")
    if discipline_ids is None:
        normalized_disciplines: list[str] = []
    elif isinstance(discipline_ids, str):
        normalized_disciplines = [discipline_ids.strip()]
    else:
        normalized_disciplines = [str(value).strip() for value in discipline_ids]
    if not all(normalized_disciplines):
        raise ScienceRunInputError("discipline_ids cannot contain empty values")

    survey_appendix = _optional_text(options.get("survey_appendix")) or "source-link"
    if survey_appendix not in SURVEY_APPENDIX_MODES:
        raise ScienceRunInputError(
            f"survey_appendix must be one of: {', '.join(SURVEY_APPENDIX_MODES)}"
        )
    try:
        minimum_pages = normalize_minimum_pages(options.get("minimum_pages"))
    except PagePolicyError as error:
        raise ScienceRunInputError(str(error)) from error

    quantitative_mode = _optional_text(options.get("quantitative_mode"))
    if quantitative_mode is None:
        quantitative_mode = _optional_text(
            options.get("quantitative", {}).get("mode")
            if isinstance(options.get("quantitative"), Mapping)
            else None
        )
    quantitative_mode = (quantitative_mode or "off").casefold()
    if quantitative_mode not in {"off", "optional", "required"}:
        raise ScienceRunInputError("quantitative_mode must be off, optional, or required")

    return {
        "discipline_ids": normalized_disciplines,
        "selected_direction": _optional_text(options.get("selected_direction")) or "",
        "models": {
            "experiment_design": _optional_text(options.get("exp_design_model")),
            "author": _optional_text(options.get("author_model")),
            "quantitative": _optional_text(options.get("quantitative_model")),
        },
        "quantitative": {"mode": quantitative_mode},
        "author_rendering": {
            "template_dir": _optional_text(options.get("template_dir")),
            "template_profile": _optional_text(options.get("template_profile")),
            "template_main": _optional_text(options.get("template_main")),
            "latex_engine": _optional_text(options.get("latex_engine")),
            "bibtex": _optional_text(options.get("bibtex")),
            "pdf_renderer": _optional_text(options.get("pdf_renderer")),
            "minimum_pages": minimum_pages,
            "compile_timeout_seconds": options.get("compile_timeout_seconds"),
            "author_name": _optional_text(options.get("author_name")) or "Anonymous Research Plan Author",
            "required": bool(options.get("render_required", False)),
        },
        "survey_appendix": survey_appendix,
    }


def _resolved_config_yaml(config_path: Path) -> str:
    try:
        config = load_config(str(config_path))
        return OmegaConf.to_yaml(config, resolve=True)
    except Exception as exc:
        raise ScienceRunInputError(f"Cannot resolve config {config_path}: {exc}") from exc


def _new_stage_state() -> dict[str, Any]:
    return {
        "status": "PENDING",
        "attempt": 0,
        "started_at": None,
        "finished_at": None,
        "input_identity": {},
        "result_identity": {},
        "result_manifest_path": None,
        "outputs": {},
        "failure": None,
        "execution_owner": None,
        "invalidated_attempts": [],
    }


def _new_science_state(run_id: str) -> dict[str, Any]:
    timestamp = utc_now()
    return {
        "schema_version": SCIENCE_STATE_SCHEMA_VERSION,
        "science_run_id": run_id,
        "status": "PENDING",
        "created_at": timestamp,
        "last_updated_at": timestamp,
        "revision": 0,
        "restart_history": [],
        "stages": {stage_name: _new_stage_state() for stage_name in SCIENCE_STAGE_NAMES},
    }


def _validate_science_state(state: Mapping[str, Any]) -> None:
    if state.get("schema_version") != SCIENCE_STATE_SCHEMA_VERSION:
        raise ScienceRunStateError(
            f"Unsupported science state schema: {state.get('schema_version')!r}"
        )
    if not isinstance(state.get("science_run_id"), str) or not state["science_run_id"]:
        raise ScienceRunStateError("science_state.json has no science_run_id")
    if state.get("status") not in {"PENDING", "RUNNING", "COMPLETED", "FAILED", "PARTIAL"}:
        raise ScienceRunStateError("science_state.json has an invalid run status")
    revision = state.get("revision")
    if revision is not None and (
        not isinstance(revision, int) or isinstance(revision, bool) or revision < 0
    ):
        raise ScienceRunStateError("science_state.json has an invalid revision")
    if not isinstance(state.get("restart_history"), list):
        raise ScienceRunStateError("science_state.json has no restart_history list")
    stages = state.get("stages")
    if not isinstance(stages, Mapping):
        raise ScienceRunStateError("science_state.json has no stages object")
    missing = [stage_name for stage_name in SCIENCE_STAGE_NAMES if stage_name not in stages]
    if missing:
        raise ScienceRunStateError(f"science_state.json is missing stages: {', '.join(missing)}")
    for stage_name in SCIENCE_STAGE_NAMES:
        stage = stages[stage_name]
        if not isinstance(stage, Mapping) or stage.get("status") not in {
            "PENDING",
            "RUNNING",
            "COMPLETED",
            "FAILED",
        }:
            raise ScienceRunStateError(f"science_state.json has an invalid {stage_name} state")
        if not isinstance(stage.get("attempt"), int) or stage["attempt"] < 0:
            raise ScienceRunStateError(f"science_state.json has an invalid {stage_name} attempt")
        for field_name in ("started_at", "finished_at", "result_manifest_path"):
            if stage.get(field_name) is not None and not isinstance(stage.get(field_name), str):
                raise ScienceRunStateError(
                    f"science_state.json has an invalid {stage_name} {field_name}"
                )
        if not isinstance(stage.get("input_identity"), Mapping):
            raise ScienceRunStateError(f"science_state.json has no {stage_name} input_identity object")
        if "result_identity" in stage and not isinstance(stage.get("result_identity"), Mapping):
            raise ScienceRunStateError(f"science_state.json has an invalid {stage_name} result_identity")
        if not isinstance(stage.get("outputs"), Mapping):
            raise ScienceRunStateError(f"science_state.json has no {stage_name} outputs object")
        if stage.get("failure") is not None and not isinstance(stage.get("failure"), Mapping):
            raise ScienceRunStateError(f"science_state.json has an invalid {stage_name} failure")
        if "execution_owner" in stage and stage.get("execution_owner") is not None:
            owner = stage.get("execution_owner")
            if not isinstance(owner, Mapping):
                raise ScienceRunStateError(
                    f"science_state.json has an invalid {stage_name} execution_owner"
                )
            if not isinstance(owner.get("pid"), int) or owner["pid"] < 1:
                raise ScienceRunStateError(
                    f"science_state.json has an invalid {stage_name} execution_owner pid"
                )
            if not isinstance(owner.get("hostname"), str) or not owner["hostname"]:
                raise ScienceRunStateError(
                    f"science_state.json has an invalid {stage_name} execution_owner hostname"
                )
            if "process_started_at" in owner and not isinstance(
                owner.get("process_started_at"), (int, float)
            ):
                raise ScienceRunStateError(
                    f"science_state.json has an invalid {stage_name} execution_owner process_started_at"
                )
            if "service_pid" in owner and (
                not isinstance(owner.get("service_pid"), int) or owner["service_pid"] < 1
            ):
                raise ScienceRunStateError(
                    f"science_state.json has an invalid {stage_name} execution_owner service_pid"
                )
            if "service_process_started_at" in owner and not isinstance(
                owner.get("service_process_started_at"), (int, float)
            ):
                raise ScienceRunStateError(
                    f"science_state.json has an invalid {stage_name} execution_owner service_process_started_at"
                )
        if not isinstance(stage.get("invalidated_attempts"), list):
            raise ScienceRunStateError(f"science_state.json has no {stage_name} invalidated_attempts list")


class ScienceRunLock:
    """An exclusive, stale-aware lock for one local science run directory."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.guard = FileLock(str(path.with_name(".science_run.guard")))
        self.owner_id = uuid.uuid4().hex
        self._acquired = False

    def __enter__(self) -> ScienceRunLock:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.guard.acquire(timeout=0)
        except Timeout as exc:
            raise ScienceRunLockError(f"Science run lock operation is already in progress: {self.path}") from exc
        try:
            try:
                descriptor = os.open(
                    self.path,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                    0o600,
                )
            except FileExistsError:
                owner = _read_lock_owner(self.path)
                if owner is None or not _is_stale_local_lock(owner):
                    raise ScienceRunLockError(_locked_message(self.path, owner))
                try:
                    self.path.unlink()
                except FileNotFoundError:
                    pass
                try:
                    descriptor = os.open(
                        self.path,
                        os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                        0o600,
                    )
                except FileExistsError as exc:
                    raise ScienceRunLockError(_locked_message(self.path, _read_lock_owner(self.path))) from exc
            try:
                payload = {
                    "schema_version": "science_run_lock_v1",
                    "owner_id": self.owner_id,
                    "pid": os.getpid(),
                    "hostname": socket.gethostname(),
                    "acquired_at": utc_now(),
                }
                with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
                    json.dump(payload, handle, ensure_ascii=False, sort_keys=True)
                    handle.write("\n")
                    handle.flush()
                    os.fsync(handle.fileno())
                self._acquired = True
                return self
            except Exception:
                self.path.unlink(missing_ok=True)
                raise
        finally:
            self.guard.release()

    def __exit__(self, _exc_type: object, _exc: object, _traceback: object) -> None:
        if not self._acquired:
            return
        try:
            self.guard.acquire(timeout=1)
        except Timeout as exc:
            raise ScienceRunLockError(f"Cannot release science run lock: {self.path}") from exc
        try:
            owner = _read_lock_owner(self.path)
            if owner is not None and owner.get("owner_id") == self.owner_id:
                self.path.unlink(missing_ok=True)
        finally:
            self.guard.release()
            self._acquired = False


def _read_lock_owner(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _is_stale_local_lock(owner: Mapping[str, Any]) -> bool:
    if owner.get("hostname") != socket.gethostname():
        return False
    pid = owner.get("pid")
    if not isinstance(pid, int) or pid <= 0:
        return False
    try:
        return not psutil.pid_exists(pid)
    except Exception:
        return False


def _locked_message(path: Path, owner: Mapping[str, Any] | None) -> str:
    if owner is None:
        return f"Science run lock already exists and cannot be verified: {path}"
    details = ", ".join(
        f"{key}={owner[key]}" for key in ("pid", "hostname", "acquired_at") if key in owner
    )
    return f"Science run is locked: {path}" + (f" ({details})" if details else "")


@contextmanager
def locked_science_run(paths: ScienceRunPaths) -> Iterator[None]:
    """Hold the exclusive lock for a run while its state is read or written."""

    with ScienceRunLock(paths.lock):
        yield


def _is_uncommitted_initialization(paths: ScienceRunPaths) -> bool:
    if paths.state.exists() or not paths.run_dir.is_dir():
        return False
    allowed_names = {
        paths.run_metadata.name,
        paths.state.name,
        paths.config_snapshot.name,
        paths.events.name,
        paths.lock.name,
        paths.lock_guard.name,
    }
    try:
        return all(child.is_file() and child.name in allowed_names for child in paths.run_dir.iterdir())
    except OSError:
        return False


def _discard_uncommitted_initialization(paths: ScienceRunPaths) -> None:
    for path in (paths.config_snapshot, paths.run_metadata, paths.state, paths.events):
        path.unlink(missing_ok=True)


def initialize_science_run(
    *,
    output_root: str | Path,
    topic: str,
    config_path: str | Path,
    immutable_options: Mapping[str, object],
    run_id: str | None = None,
) -> tuple[ScienceRunPaths, dict[str, Any], dict[str, Any]]:
    """Create a new run directory containing immutable metadata and pending state."""

    normalized_topic = str(topic).strip()
    if not normalized_topic:
        raise ScienceRunInputError("topic is required when creating a science run")
    source_config = Path(config_path).expanduser().resolve()
    if not source_config.is_file():
        raise ScienceRunInputError(f"Config file not found: {source_config}")

    normalized_run_id = _validate_run_id(run_id or create_research_run_id())
    root = Path(output_root).expanduser().resolve()
    paths = science_run_paths(root / normalized_run_id)
    normalized_options = normalize_immutable_options(immutable_options)
    resolved_config = _resolved_config_yaml(source_config)
    state = _new_science_state(normalized_run_id)
    metadata = {
        "schema_version": SCIENCE_RUN_SCHEMA_VERSION,
        "science_run_id": normalized_run_id,
        "created_at": state["created_at"],
        "execution_mode": "DESIGN_ONLY",
        "immutable_inputs": {
            "topic": normalized_topic,
            "topic_fingerprint": text_sha256(normalized_topic),
            "config": {
                "source_path": str(source_config),
                "source_sha256": file_sha256(source_config),
                "snapshot_path": paths.config_snapshot.name,
                "snapshot_sha256": text_sha256(resolved_config),
            },
            "options": normalized_options,
        },
    }
    reuse_uncommitted_directory = False
    try:
        paths.run_dir.mkdir(parents=True, exist_ok=False)
    except FileExistsError as exc:
        if not _is_uncommitted_initialization(paths):
            raise ScienceRunConflictError(f"Science run directory already exists: {paths.run_dir}") from exc
        reuse_uncommitted_directory = True
    except OSError as exc:
        raise ScienceRunInputError(f"Cannot create science run directory {paths.run_dir}: {exc}") from exc

    initialization_started = False
    try:
        with locked_science_run(paths):
            if reuse_uncommitted_directory:
                if not _is_uncommitted_initialization(paths):
                    raise ScienceRunConflictError(
                        f"Science run directory was committed while waiting for its lock: {paths.run_dir}"
                    )
                _discard_uncommitted_initialization(paths)
            initialization_started = True
            atomic_write_text(paths.config_snapshot, resolved_config)
            atomic_write_json(paths.run_metadata, metadata)
            save_science_state(paths, state)
            append_science_event(
                paths,
                event_type="RUN_INITIALIZED",
                science_run_id=normalized_run_id,
                execution_mode="DESIGN_ONLY",
            )
    except Exception:
        if initialization_started:
            _discard_uncommitted_initialization(paths)
        raise
    return paths, metadata, state


def load_science_run(paths: ScienceRunPaths) -> tuple[dict[str, Any], dict[str, Any]]:
    """Load and cross-check immutable metadata and resumable state."""

    metadata = _load_json_object(paths.run_metadata, label="science_run.json")
    state = _load_json_object(paths.state, label="science_state.json")
    if metadata.get("schema_version") != SCIENCE_RUN_SCHEMA_VERSION:
        raise ScienceRunStateError(
            f"Unsupported science run schema: {metadata.get('schema_version')!r}"
        )
    run_id = metadata.get("science_run_id")
    if not isinstance(run_id, str) or not run_id:
        raise ScienceRunStateError("science_run.json has no science_run_id")
    if state.get("science_run_id") != run_id:
        raise ScienceRunStateError("science_run.json and science_state.json have different science_run_id values")
    immutable_inputs = metadata.get("immutable_inputs")
    if not isinstance(immutable_inputs, Mapping):
        raise ScienceRunStateError("science_run.json has no immutable_inputs object")
    config = immutable_inputs.get("config")
    if not isinstance(config, Mapping):
        raise ScienceRunStateError("science_run.json has no immutable config input")
    if config.get("snapshot_path") != paths.config_snapshot.name or not paths.config_snapshot.is_file():
        raise ScienceRunStateError("Science run config snapshot is missing or points outside the run directory")
    if config.get("snapshot_sha256") != file_sha256(paths.config_snapshot):
        raise ScienceRunStateError("Science run config snapshot no longer matches its recorded fingerprint")
    _validate_science_state(state)
    return metadata, state


def save_science_state(paths: ScienceRunPaths, state: dict[str, Any]) -> None:
    """Validate and atomically publish the mutable state document."""

    _validate_science_state(state)
    state["revision"] = int(state.get("revision", 0)) + 1
    atomic_write_json(paths.state, state)


def mark_stage_running(
    state: dict[str, Any],
    stage_name: str,
    *,
    input_identity: Mapping[str, object],
) -> dict[str, Any]:
    """Start one pending or failed stage and allocate its next immutable attempt."""

    if stage_name not in SCIENCE_STAGE_NAMES:
        raise ScienceRunInputError(f"Unknown science stage: {stage_name}")
    _validate_science_state(state)
    stage = state["stages"][stage_name]
    if stage["status"] not in {"PENDING", "FAILED"}:
        raise ScienceRunStateError(
            f"Cannot start {stage_name} while it is {stage['status']}"
        )
    timestamp = utc_now()
    stage.update(
        {
            "status": "RUNNING",
            "attempt": stage["attempt"] + 1,
            "started_at": timestamp,
            "finished_at": None,
            "input_identity": copy.deepcopy(dict(input_identity)),
            "result_identity": {},
            "result_manifest_path": None,
            "outputs": {},
            "failure": None,
            "execution_owner": {
                "pid": os.getpid(),
                "hostname": socket.gethostname(),
                "process_started_at": psutil.Process(os.getpid()).create_time(),
                "started_at": timestamp,
            },
        }
    )
    state["status"] = "RUNNING"
    state["last_updated_at"] = timestamp
    return state


def record_stage_service_process(
    state: dict[str, Any],
    stage_name: str,
    *,
    attempt: int,
    process_id: int,
) -> dict[str, Any]:
    """Record a spawned service process while its owning stage remains running."""

    if stage_name not in SCIENCE_STAGE_NAMES:
        raise ScienceRunInputError(f"Unknown science stage: {stage_name}")
    if not isinstance(process_id, int) or process_id < 1:
        raise ScienceRunStateError(f"Cannot record an invalid {stage_name} service process")
    _validate_science_state(state)
    stage = state["stages"][stage_name]
    if stage["status"] != "RUNNING" or stage["attempt"] != attempt:
        raise ScienceRunStateError(
            f"Cannot record {stage_name} service process for a non-running attempt"
        )
    owner = stage.get("execution_owner")
    if not isinstance(owner, dict):
        raise ScienceRunStateError(f"Running {stage_name} has no execution owner")
    owner["service_pid"] = process_id
    try:
        owner["service_process_started_at"] = psutil.Process(process_id).create_time()
    except psutil.Error:
        owner.pop("service_process_started_at", None)
    return state


def mark_stage_completed(
    state: dict[str, Any],
    stage_name: str,
    *,
    result_manifest_path: str,
    outputs: Mapping[str, object],
    result_identity: Mapping[str, object],
) -> dict[str, Any]:
    """Record one published stage result after its service returns successfully."""

    if stage_name not in SCIENCE_STAGE_NAMES:
        raise ScienceRunInputError(f"Unknown science stage: {stage_name}")
    _validate_science_state(state)
    stage = state["stages"][stage_name]
    if stage["status"] != "RUNNING":
        raise ScienceRunStateError(
            f"Cannot complete {stage_name} while it is {stage['status']}"
        )
    normalized_path = str(result_manifest_path).strip()
    if not normalized_path:
        raise ScienceRunStateError(f"Cannot complete {stage_name} without a result path")
    timestamp = utc_now()
    stage.update(
        {
            "status": "COMPLETED",
            "finished_at": timestamp,
            "result_identity": copy.deepcopy(dict(result_identity)),
            "result_manifest_path": normalized_path,
            "outputs": copy.deepcopy(dict(outputs)),
            "failure": None,
            "execution_owner": None,
        }
    )
    state["last_updated_at"] = timestamp
    return state


def recover_stage_completed(
    state: dict[str, Any],
    stage_name: str,
    *,
    attempt: int,
    result_manifest_path: str,
    outputs: Mapping[str, object],
    result_identity: Mapping[str, object],
) -> dict[str, Any]:
    """Promote a verified artifact from a failed attempt without allocating a new one."""

    if stage_name not in SCIENCE_STAGE_NAMES:
        raise ScienceRunInputError(f"Unknown science stage: {stage_name}")
    if not isinstance(attempt, int) or isinstance(attempt, bool) or attempt < 1:
        raise ScienceRunStateError(f"Cannot recover {stage_name} with an invalid attempt")
    _validate_science_state(state)
    stage = state["stages"][stage_name]
    if stage["status"] != "FAILED":
        raise ScienceRunStateError(
            f"Cannot recover {stage_name} while it is {stage['status']}"
        )
    if stage["attempt"] != attempt:
        raise ScienceRunStateError(
            f"Cannot recover {stage_name} attempt {attempt}; current attempt is {stage['attempt']}"
        )
    normalized_path = str(result_manifest_path).strip()
    if not normalized_path:
        raise ScienceRunStateError(f"Cannot recover {stage_name} without a result path")
    timestamp = utc_now()
    stage.update(
        {
            "status": "COMPLETED",
            "finished_at": timestamp,
            "result_identity": copy.deepcopy(dict(result_identity)),
            "result_manifest_path": normalized_path,
            "outputs": copy.deepcopy(dict(outputs)),
            "failure": None,
            "execution_owner": None,
        }
    )
    state["status"] = "RUNNING"
    state["last_updated_at"] = timestamp
    return state


def mark_stage_failed(
    state: dict[str, Any],
    stage_name: str,
    *,
    exit_code: int,
    message: str,
    error_type: str = "ScienceWorkflowError",
) -> dict[str, Any]:
    """Persist a stable stage failure without discarding its attempt directory."""

    if stage_name not in SCIENCE_STAGE_NAMES:
        raise ScienceRunInputError(f"Unknown science stage: {stage_name}")
    _validate_science_state(state)
    stage = state["stages"][stage_name]
    if stage["status"] != "RUNNING":
        raise ScienceRunStateError(
            f"Cannot fail {stage_name} while it is {stage['status']}"
        )
    timestamp = utc_now()
    stage.update(
        {
            "status": "FAILED",
            "finished_at": timestamp,
            "result_identity": {},
            "result_manifest_path": None,
            "outputs": {},
            "failure": {
                "exit_code": int(exit_code),
                "message": str(message),
                "error_type": str(error_type),
                "failed_at": timestamp,
            },
            "execution_owner": None,
        }
    )
    state["status"] = "FAILED"
    state["last_updated_at"] = timestamp
    return state


def append_science_event(paths: ScienceRunPaths, *, event_type: str, **fields: Any) -> None:
    """Append one durable event while the caller owns the run lock."""

    payload = {"timestamp": utc_now(), "event_type": event_type, **fields}
    paths.events.parent.mkdir(parents=True, exist_ok=True)
    with paths.events.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True, allow_nan=False))
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())


def _process_matches_owner(process_id: object, expected_started_at: object) -> bool:
    if not isinstance(process_id, int) or process_id < 1 or not psutil.pid_exists(process_id):
        return False
    if not isinstance(expected_started_at, (int, float)):
        return True
    try:
        actual_started_at = psutil.Process(process_id).create_time()
    except psutil.Error:
        return False
    return abs(actual_started_at - float(expected_started_at)) < 0.1


def is_stage_execution_active(stage: Mapping[str, object]) -> bool:
    """Return whether a running stage may still be executing.

    Unknown remote owners are conservatively treated as live so a resumed local
    process never takes over work that might still be running elsewhere.
    """

    owner = stage.get("execution_owner")
    if not isinstance(owner, Mapping):
        return False
    if str(owner.get("hostname") or "") != socket.gethostname():
        return True
    return _process_matches_owner(owner.get("pid"), owner.get("process_started_at")) or _process_matches_owner(
        owner.get("service_pid"), owner.get("service_process_started_at")
    )


def validate_resume_inputs(
    metadata: Mapping[str, Any],
    *,
    config_path: Path | None,
    explicit_options: Mapping[str, object],
) -> None:
    """Reject explicit resume inputs that conflict with immutable run identity."""

    immutable_inputs = metadata.get("immutable_inputs")
    if not isinstance(immutable_inputs, Mapping):
        raise ScienceRunStateError("science_run.json has no immutable_inputs object")
    expected_config = immutable_inputs.get("config")
    expected_options = immutable_inputs.get("options")
    if not isinstance(expected_config, Mapping) or not isinstance(expected_options, Mapping):
        raise ScienceRunStateError("science_run.json has incomplete immutable inputs")

    if config_path is not None:
        if not config_path.is_file():
            raise ScienceRunInputError(f"Config file not found: {config_path}")
        if file_sha256(config_path) != expected_config.get("source_sha256"):
            raise ScienceRunConflictError(
                "Resume config differs from the config snapshot recorded for this science run"
            )

    explicit_disciplines = explicit_options.get("discipline_ids")
    if explicit_disciplines is not None:
        provided = normalize_immutable_options({"discipline_ids": explicit_disciplines})[
            "discipline_ids"
        ]
        if provided != expected_options.get("discipline_ids"):
            raise ScienceRunConflictError("Resume discipline_ids differ from the science run")

    scalar_fields = ("selected_direction", "survey_appendix", "quantitative_mode")
    for field_name in scalar_fields:
        provided = explicit_options.get(field_name)
        if provided is None:
            continue
        normalized_options = normalize_immutable_options({field_name: provided})
        normalized = (
            normalized_options.get("quantitative", {}).get("mode")
            if field_name == "quantitative_mode"
            else normalized_options.get(field_name)
        )
        if field_name == "quantitative_mode":
            expected_quantitative = (
                expected_options.get("quantitative", {}).get("mode")
                if isinstance(expected_options.get("quantitative"), Mapping)
                else "off"
            )
            expected = expected_quantitative or "off"
        else:
            expected = expected_options.get(field_name)
        if normalized != expected:
            raise ScienceRunConflictError(f"Resume {field_name} differs from the science run")

    model_fields = {
        "exp_design_model": "experiment_design",
        "author_model": "author",
        "quantitative_model": "quantitative",
    }
    expected_models = expected_options.get("models")
    if not isinstance(expected_models, Mapping):
        raise ScienceRunStateError("science_run.json has incomplete model inputs")
    for option_name, model_name in model_fields.items():
        provided = explicit_options.get(option_name)
        if provided is not None and _optional_text(provided) != expected_models.get(model_name):
            raise ScienceRunConflictError(f"Resume {option_name} differs from the science run")

    expected_rendering = expected_options.get("author_rendering")
    if not isinstance(expected_rendering, Mapping):
        raise ScienceRunStateError("science_run.json has incomplete Author rendering inputs")
    rendering_fields = (
        "template_dir",
        "template_profile",
        "template_main",
        "latex_engine",
        "bibtex",
        "pdf_renderer",
        "minimum_pages",
        "compile_timeout_seconds",
        "author_name",
        "render_required",
    )
    for field_name in rendering_fields:
        provided = explicit_options.get(field_name)
        if provided is None:
            continue
        if field_name == "render_required":
            normalized = bool(provided)
        elif field_name == "compile_timeout_seconds":
            normalized = provided
        elif field_name == "minimum_pages":
            try:
                normalized = normalize_minimum_pages(provided)
            except PagePolicyError as error:
                raise ScienceRunInputError(str(error)) from error
        else:
            normalized = _optional_text(provided)
        persisted_field = "required" if field_name == "render_required" else field_name
        if normalized != expected_rendering.get(persisted_field):
            raise ScienceRunConflictError(f"Resume {field_name} differs from the science run")


def invalidate_stages_from(state: dict[str, Any], restart_from: str) -> dict[str, Any]:
    """Mark one stage and its downstream stages pending without discarding history."""

    if restart_from not in SCIENCE_STAGE_NAMES:
        raise ScienceRunInputError(f"Unknown science stage: {restart_from}")
    _validate_science_state(state)
    running_stages = [
        stage_name
        for stage_name in SCIENCE_STAGE_NAMES
        if state["stages"][stage_name]["status"] == "RUNNING"
    ]
    if running_stages:
        raise ScienceRunConflictError(
            "Cannot restart a science run while stages are still running: "
            + ", ".join(running_stages)
        )
    timestamp = utc_now()
    start_index = SCIENCE_STAGE_NAMES.index(restart_from)
    invalidated_stages: list[str] = []
    for stage_name in SCIENCE_STAGE_NAMES[start_index:]:
        stage = state["stages"][stage_name]
        if stage["status"] != "PENDING" or stage["attempt"]:
            stage["invalidated_attempts"].append(
                {
                    "attempt": stage["attempt"],
                    "status": stage["status"],
                    "started_at": stage["started_at"],
                    "finished_at": stage["finished_at"],
                    "input_identity": copy.deepcopy(stage["input_identity"]),
                    "result_identity": copy.deepcopy(stage.get("result_identity", {})),
                    "result_manifest_path": stage["result_manifest_path"],
                    "outputs": copy.deepcopy(stage["outputs"]),
                    "failure": copy.deepcopy(stage["failure"]),
                    "execution_owner": copy.deepcopy(stage.get("execution_owner")),
                    "invalidated_at": timestamp,
                    "reason": f"restart-from:{restart_from}",
                }
            )
        stage.update(
            {
                "status": "PENDING",
                "started_at": None,
                "finished_at": None,
                "input_identity": {},
                "result_identity": {},
                "result_manifest_path": None,
                "outputs": {},
                "failure": None,
                "execution_owner": None,
            }
        )
        invalidated_stages.append(stage_name)
    state["status"] = "PENDING"
    state["last_updated_at"] = timestamp
    state["restart_history"].append(
        {
            "restart_from": restart_from,
            "invalidated_stages": invalidated_stages,
            "requested_at": timestamp,
        }
    )
    return state
