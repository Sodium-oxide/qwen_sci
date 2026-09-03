"""Application service layer for durable browser-controlled science runs."""

from __future__ import annotations

import json
import re
import threading
from collections.abc import Mapping
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable

from src.agents.quantitative_modeling.author_handoff import (
    build_quantitative_author_handoff,
    finalize_quantitative_idea,
)
from src.agents.quantitative_modeling.model_synthesis import build_quantitative_model_llm_call
from src.agents.quantitative_modeling.publisher.run import publish_quantitative_models_pdf
from src.agents.experiment_design_agent.discipline_catalog import (
    get_discipline_entries,
    resolve_design_scope,
)
from src.config import load_config
from src.pipeline.quantitative_orchestrator import (
    refresh_quantitative_state,
    resume_quantitative_from_existing_idea,
)
from src.pipeline.quantitative_state import QuantitativeStateError, load_quantitative_state
from src.pipeline.quantitative_workflow import (
    accept_quantitative_refinement,
    approve_quantitative_parameter_resolution,
    discover_quantitative_parameter_evidence,
    execute_quantitative_plan,
    extract_quantitative_parameter_candidates,
    fetch_quantitative_parameter_fulltext,
    materialize_quantitative_model_version,
    prepare_quantitative_model_blueprint,
    propose_quantitative_parameter_resolution,
    propose_quantitative_refinement,
    qualify_quantitative_execution,
    register_quantitative_parameter_document,
)
from src.pipeline.science_run import (
    SCIENCE_STAGE_NAMES,
    ScienceRunInputError,
    ScienceRunPaths,
    append_science_event,
    atomic_write_json,
    clear_science_cancellation,
    file_sha256,
    initialize_science_run,
    is_science_cancellation_requested,
    load_science_run,
    locked_science_run,
    request_science_cancellation,
    save_science_state,
    science_run_paths,
)
from src.pipeline.science_workflow import run_science_workflow

from .artifact_service import list_artifacts
from .schemas import CreateRunRequest, RunActionRequest, RunActionType, RunView


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = REPO_ROOT / "src" / "config" / "default.yaml"
_RUN_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}")


class WebRunError(RuntimeError):
    """Base class for user-facing web-control-plane errors."""


class RunNotFoundError(WebRunError):
    """Raised when a requested run is outside the configured run root."""


class RunActionError(WebRunError):
    """Raised when the state machine does not permit an action."""


class RunActionConflictError(RunActionError):
    """Raised when another web-supervised action already owns a run."""


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _text(value: object) -> str:
    return str(value or "").strip()


def _safe_message(value: object) -> str:
    """Keep operational errors useful without exposing local filesystem paths."""

    message = _text(value)
    message = re.sub(r"[A-Za-z]:[\\/][^\s'\"]+", "[local path]", message)
    message = re.sub(r"(?<![A-Za-z0-9_.-])/(?:[^\s'\"]+/)+[^\s'\"]*", "[local path]", message)
    return message[:1_000]


class WorkflowSupervisor:
    """Ensure this web process submits at most one task per run at a time."""

    def __init__(self) -> None:
        self._executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="qwensci-web")
        self._futures: dict[str, Future[object]] = {}
        self._lock = threading.Lock()

    def submit(self, *, paths: ScienceRunPaths, metadata: Mapping[str, Any], until: str) -> None:
        """Submit a science-stage continuation without starting a subprocess."""

        run_id = _text(metadata.get("science_run_id"))
        if not run_id:
            raise RunActionError("The stored research run has no run ID.")
        self.submit_task(
            run_id=run_id,
            task=lambda: run_science_workflow(
                paths=paths,
                metadata=metadata,
                until=until,
                quiet=True,
            ),
        )

    def submit_task(self, *, run_id: str, task: Callable[[], object]) -> None:
        """Submit one bounded server-side task for a run.

        The browser never supplies a callable, command, path, or configuration;
        callers construct the trusted task from a typed action after checking the
        durable workflow state.
        """

        if not _text(run_id):
            raise RunActionError("The stored research run has no run ID.")
        with self._lock:
            active = self._futures.get(run_id)
            if active is not None and not active.done():
                raise RunActionConflictError("This research run is already executing.")
            future = self._executor.submit(task)
            self._futures[run_id] = future
            future.add_done_callback(lambda completed, active_run_id=run_id: self._finish(active_run_id, completed))

    def _finish(self, run_id: str, future: Future[object]) -> None:
        with self._lock:
            if self._futures.get(run_id) is future:
                self._futures.pop(run_id, None)

    def is_active(self, run_id: str) -> bool:
        with self._lock:
            future = self._futures.get(run_id)
            return future is not None and not future.done()


class RunService:
    """Use the existing science state machine as the sole source of truth."""

    def __init__(
        self,
        *,
        run_root: str | Path,
        config_path: str | Path = DEFAULT_CONFIG_PATH,
        supervisor: WorkflowSupervisor | None = None,
    ) -> None:
        self.run_root = Path(run_root).expanduser().resolve()
        self.config_path = Path(config_path).expanduser().resolve()
        self.supervisor = supervisor or WorkflowSupervisor()

    def create_run(self, request: CreateRunRequest) -> RunView:
        scope = resolve_design_scope(request.discipline_ids)
        if scope["status"] != "IN_SCOPE":
            raise ScienceRunInputError(str(scope["reason"]))
        discipline_ids = list(scope["discipline_ids"])
        if len(discipline_ids) > 2:
            raise ScienceRunInputError("Choose no more than two scientific disciplines.")
        paths, metadata, state = initialize_science_run(
            output_root=self.run_root,
            topic=request.topic,
            config_path=self.config_path,
            run_id=request.run_id,
            immutable_options={
                "discipline_ids": discipline_ids,
                "quantitative_mode": request.quantitative_mode,
                "minimum_pages": request.minimum_pages,
            },
        )
        with locked_science_run(paths):
            metadata, state = load_science_run(paths)
            immutable_inputs = metadata.get("immutable_inputs")
            if not isinstance(immutable_inputs, dict):
                raise ScienceRunInputError("New run has invalid immutable inputs.")
            materials_manifest = {
                "schema_version": "web_materials_manifest_v1",
                "materials": [],
            }
            atomic_write_json(paths.materials_manifest, materials_manifest)
            immutable_inputs["materials"] = {
                "records": [],
                "manifest_path": paths.materials_manifest.relative_to(paths.run_dir).as_posix(),
                "manifest_sha256": file_sha256(paths.materials_manifest),
                "multimodal_manifest_path": paths.multimodal_input_manifest.relative_to(paths.run_dir).as_posix(),
                "multimodal_manifest_sha256": None,
                "remote_perception_authorized": request.allow_remote_perception,
            }
            immutable_inputs["web"] = {"language": request.language}
            atomic_write_json(paths.run_metadata, metadata)
        return self._view(paths, metadata, state)

    def list_runs(self, *, query: str = "") -> list[RunView]:
        if not self.run_root.exists():
            return []
        normalized_query = query.casefold().strip()
        views: list[RunView] = []
        root = self.run_root.resolve()
        for candidate in self.run_root.iterdir():
            try:
                if not candidate.is_dir() or candidate.resolve().parent != root:
                    continue
            except OSError:
                continue
            paths = science_run_paths(candidate)
            if not paths.run_metadata.is_file() or not paths.state.is_file():
                continue
            try:
                metadata, state = load_science_run(paths)
                view = self._view(paths, metadata, state)
            except Exception:
                continue
            searchable_materials = [
                _text(record.get("original_name"))
                + " "
                + _text(_mapping(record.get("metadata")).get("label"))
                for record in view.materials
                if isinstance(record, Mapping)
            ]
            searchable = " ".join(
                (view.run_id, view.topic, view.status, *view.discipline_ids, *searchable_materials)
            ).casefold()
            if not normalized_query or normalized_query in searchable:
                views.append(view)
        return sorted(views, key=lambda view: (view.last_updated_at, view.created_at, view.run_id), reverse=True)

    def get_run(self, run_id: str) -> RunView:
        paths = self.paths_for(run_id)
        try:
            metadata, state = load_science_run(paths)
        except Exception as exc:
            raise RunNotFoundError("Research run is unavailable.") from exc
        return self._view(paths, metadata, state)

    def paths_for(self, run_id: str) -> ScienceRunPaths:
        normalized = _text(run_id)
        if not _RUN_ID_PATTERN.fullmatch(normalized):
            raise RunNotFoundError("Unknown research run.")
        paths = science_run_paths(self.run_root / normalized)
        try:
            paths.run_dir.relative_to(self.run_root)
        except ValueError as exc:
            raise RunNotFoundError("Unknown research run.") from exc
        if not paths.run_metadata.is_file() or not paths.state.is_file():
            raise RunNotFoundError("Unknown research run.")
        return paths

    def start_or_resume(self, *, run_id: str, action: RunActionType, until: str) -> RunView:
        paths = self.paths_for(run_id)
        metadata, state = load_science_run(paths)
        if self.supervisor.is_active(_text(metadata.get("science_run_id"))):
            raise RunActionConflictError("This research run is already executing.")
        allowed_actions = self._allowed_actions(paths, metadata, state)
        if action not in allowed_actions:
            raise RunActionError("This action is not available for the current research state.")
        if is_science_cancellation_requested(state):
            with locked_science_run(paths):
                metadata, state = load_science_run(paths)
                if is_science_cancellation_requested(state):
                    clear_science_cancellation(state)
                    save_science_state(paths, state)
                    append_science_event(paths, event_type="RUN_RESUMED", until=until)
        quantitative_mode = self._quantitative_mode(metadata)
        if quantitative_mode == "required" and until == "author":
            until = "exp_design"
        self.supervisor.submit(paths=paths, metadata=metadata, until=until)
        return self.get_run(run_id)

    def cancel_science(self, *, run_id: str) -> RunView:
        """Persist a safe-boundary cancellation for the currently running science stage."""

        paths = self.paths_for(run_id)
        with locked_science_run(paths):
            _metadata, state = load_science_run(paths)
            stage_name = self._running_science_stage(state)
            if stage_name is None:
                raise RunActionError("No science stage is currently running.")
            if not is_science_cancellation_requested(state):
                request_science_cancellation(state, requested_stage=stage_name)
                save_science_state(paths, state)
                append_science_event(
                    paths,
                    event_type="RUN_CANCELLATION_REQUESTED",
                    stage=stage_name,
                )
        return self.get_run(run_id)

    def run_action(self, *, run_id: str, action: RunActionRequest) -> RunView:
        """Validate one typed browser action and submit only a trusted task."""

        if action.type in {"start_workflow", "resume_science"}:
            return self.start_or_resume(run_id=run_id, action=action.type, until=action.until)
        if action.type == "cancel_science":
            return self.cancel_science(run_id=run_id)

        paths = self.paths_for(run_id)
        metadata, state = load_science_run(paths)
        if self.supervisor.is_active(_text(metadata.get("science_run_id"))):
            raise RunActionConflictError("This research run is already executing.")
        allowed_actions = self._allowed_actions(paths, metadata, state)
        if action.type not in allowed_actions:
            raise RunActionError("This action is not available for the current quantitative workflow state.")
        if action.type == "continue_author":
            self._validate_quantitative_handoff(paths)
        if action.type == "execute_plan":
            self._validate_execution_request(paths, action.idea_id, action.version, action.plan_identity)
        self._validate_quantitative_action_inputs(paths, action)
        self._submit_quantitative_task(paths=paths, metadata=metadata, action=action)
        return self.get_run(run_id)

    def _allowed_actions(
        self,
        paths: ScienceRunPaths,
        metadata: Mapping[str, Any],
        state: Mapping[str, Any],
    ) -> list[RunActionType]:
        run_id = _text(metadata.get("science_run_id"))
        stages = _mapping(state.get("stages"))
        statuses = [_text(_mapping(stages.get(name)).get("status")) for name in SCIENCE_STAGE_NAMES]
        if "RUNNING" in statuses:
            return [] if is_science_cancellation_requested(state) else ["cancel_science"]
        if self.supervisor.is_active(run_id):
            return []
        quantitative_mode = self._quantitative_mode(metadata)
        quantitative_state = self._load_quantitative_state(paths)
        quantitative_actions = self._quantitative_actions(
            paths=paths,
            state=state,
            quantitative_mode=quantitative_mode,
            quantitative_state=quantitative_state,
        )
        if state.get("status") in {"PENDING", "CANCELLED"} and all(status == "PENDING" for status in statuses):
            return ["start_workflow"]
        science_actions: list[RunActionType] = []
        if state.get("status") in {"FAILED", "PARTIAL", "CANCELLED"} or "FAILED" in statuses:
            author_status = _text(_mapping(stages.get("author")).get("status"))
            if not (quantitative_mode == "required" and author_status in {"PENDING", "FAILED"}):
                science_actions.append("resume_science")
        return list(dict.fromkeys([*science_actions, *quantitative_actions]))

    @staticmethod
    def _quantitative_mode(metadata: Mapping[str, Any]) -> str:
        immutable_inputs = _mapping(metadata.get("immutable_inputs"))
        options = _mapping(immutable_inputs.get("options"))
        mode = _text(_mapping(options.get("quantitative")).get("mode")) or "off"
        return mode if mode in {"off", "optional", "required"} else "off"

    @staticmethod
    def _load_quantitative_state(paths: ScienceRunPaths) -> dict[str, Any] | None:
        try:
            return load_quantitative_state(paths.run_dir)
        except QuantitativeStateError:
            return None

    @staticmethod
    def _stage_status(state: Mapping[str, Any], stage_name: str) -> str:
        return _text(_mapping(_mapping(state.get("stages")).get(stage_name)).get("status"))

    @staticmethod
    def _running_science_stage(state: Mapping[str, Any]) -> str | None:
        for stage_name in SCIENCE_STAGE_NAMES:
            if RunService._stage_status(state, stage_name) == "RUNNING":
                return stage_name
        return None

    def _quantitative_actions(
        self,
        *,
        paths: ScienceRunPaths,
        state: Mapping[str, Any],
        quantitative_mode: str,
        quantitative_state: Mapping[str, Any] | None,
    ) -> list[RunActionType]:
        if quantitative_mode == "off":
            return []
        if quantitative_state is None:
            if all(self._stage_status(state, stage) == "COMPLETED" for stage in ("survey", "idea", "exp_design")):
                return ["resume_quantitative"]
            return []
        status = _text(quantitative_state.get("status"))
        if status == "WAITING_FOR_EXPERIMENT_DESIGN":
            return ["resume_science"]
        if status == "NO_QUANTITATIVE_IDEAS":
            return ["resume_quantitative"]
        if status == "READY_TO_PUBLISH":
            return ["publish_quantitative_models"]
        if status == "PUBLISHED":
            return ["build_quantitative_author_handoff"]
        if status == "HANDED_OFF":
            return ["continue_author"]

        active = self._active_quantitative_idea(quantitative_state)
        if active is None:
            return []
        idea_id, version, active_status = active
        if active_status == "WAITING_FOR_BLUEPRINT":
            return ["prepare_quantitative_blueprint"]
        if active_status == "WAITING_FOR_PARAMETER_EVIDENCE":
            actions: list[RunActionType] = []
            evidence_dir = self._parameter_evidence_dir(paths, idea_id, version)
            if not (evidence_dir / "discovery" / "parameter_discovery.json").is_file():
                actions.append("discover_parameters")
            elif not (evidence_dir / "fulltext" / "fulltext_manifest.json").is_file():
                actions.append("fetch_open_access_fulltext")
            if self._parameter_materials(paths):
                actions.append("register_parameter_material")
            if self._parameter_documents(paths, idea_id, version, include_extracted=False):
                actions.append("extract_parameters")
            return actions
        if active_status == "WAITING_FOR_PARAMETER_REVIEW":
            if self._parameter_documents(paths, idea_id, version, include_extracted=False):
                return ["extract_parameters"]
            return ["propose_parameters"] if self._parameter_candidates(paths, idea_id, version) else []
        if active_status == "WAITING_FOR_PARAMETER_APPROVAL":
            return ["approve_parameters"]
        if active_status == "PARAMETERS_APPROVED":
            return ["materialize_plan"]
        if active_status == "WAITING_FOR_EXECUTION_AUTHORIZATION":
            return ["execute_plan"]
        if active_status == "WAITING_FOR_QUALIFICATION":
            return ["qualify_result"]
        if active_status == "QUALIFIED_WAITING_FOR_REVISION_DECISION":
            return ["finalize_quantitative_idea", "propose_refinement"]
        if active_status == "WAITING_FOR_REVISION_APPROVAL":
            return ["finalize_quantitative_idea", "accept_refinement"]
        return []

    @staticmethod
    def _active_quantitative_idea(state: Mapping[str, Any]) -> tuple[str, int, str] | None:
        ideas = _mapping(state.get("ideas"))
        for idea_id in ("Q1", "Q2"):
            idea = _mapping(ideas.get(idea_id))
            status = _text(idea.get("status"))
            version = idea.get("current_version")
            if status and status != "FINALIZED" and isinstance(version, int) and 0 <= version <= 2:
                return idea_id, version, status
        return None

    @staticmethod
    def _parameter_evidence_dir(paths: ScienceRunPaths, idea_id: str, version: int) -> Path:
        if idea_id not in {"Q1", "Q2"} or version not in {0, 1, 2}:
            raise RunActionError("Quantitative idea or version is invalid.")
        return paths.run_dir / "quantitative" / idea_id / "parameter_evidence" / f"v{version}"

    @staticmethod
    def _version_dir(paths: ScienceRunPaths, idea_id: str, version: int) -> Path:
        if idea_id not in {"Q1", "Q2"} or version not in {0, 1, 2}:
            raise RunActionError("Quantitative idea or version is invalid.")
        return paths.run_dir / "quantitative" / idea_id / f"v{version}"

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any]:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return _mapping(value)

    def _parameter_materials(self, paths: ScienceRunPaths) -> list[dict[str, Any]]:
        try:
            metadata, _state = load_science_run(paths)
        except Exception:
            return []
        inputs = _mapping(metadata.get("immutable_inputs"))
        records = _mapping(inputs.get("materials")).get("records")
        if not isinstance(records, list):
            return []
        supported = {".pdf", ".txt", ".md", ".csv"}
        materials: list[dict[str, Any]] = []
        for raw_record in records:
            record = _mapping(raw_record)
            material_id = _text(record.get("material_id"))
            stored_name = _text(record.get("stored_name"))
            if (
                record.get("scope") != "parameter_source"
                or not re.fullmatch(r"mat-[a-f0-9]{32}", material_id)
                or Path(stored_name).suffix.casefold() not in supported
            ):
                continue
            source = (paths.inputs / "files" / stored_name).resolve()
            try:
                source.relative_to((paths.inputs / "files").resolve())
            except ValueError:
                continue
            if not source.is_file() or file_sha256(source) != _text(record.get("sha256")):
                continue
            materials.append(
                {
                    "material_id": material_id,
                    "title": _text(_mapping(record.get("metadata")).get("label")) or _text(record.get("original_name")),
                    "original_name": _text(record.get("original_name")),
                }
            )
        return materials

    def _parameter_documents(
        self,
        paths: ScienceRunPaths,
        idea_id: str,
        version: int,
        *,
        include_extracted: bool,
    ) -> list[dict[str, Any]]:
        evidence_dir = self._parameter_evidence_dir(paths, idea_id, version)
        extracted_ids = self._extracted_document_ids(paths, idea_id, version)
        documents: list[dict[str, Any]] = []
        manifest = self._read_json(evidence_dir / "fulltext" / "fulltext_manifest.json")
        for raw_document in manifest.get("documents", []):
            document = _mapping(raw_document)
            document_id = _text(document.get("document_id"))
            if document_id and (include_extracted or document_id not in extracted_ids):
                documents.append(
                    {
                        "document_id": document_id,
                        "title": _text(document.get("title")),
                        "year": document.get("year") if isinstance(document.get("year"), int) else None,
                        "source": "open_access",
                    }
                )
        user_documents = evidence_dir / "user_documents"
        if user_documents.is_dir():
            for path in sorted(user_documents.glob("*.json")):
                document = self._read_json(path)
                document_id = _text(document.get("document_id"))
                if document_id and (include_extracted or document_id not in extracted_ids):
                    documents.append(
                        {
                            "document_id": document_id,
                            "title": _text(document.get("title")),
                            "year": document.get("year") if isinstance(document.get("year"), int) else None,
                            "source": "uploaded_material",
                        }
                    )
        return documents[:64]

    def _extracted_document_ids(self, paths: ScienceRunPaths, idea_id: str, version: int) -> set[str]:
        extraction_dir = self._parameter_evidence_dir(paths, idea_id, version) / "extractions"
        if not extraction_dir.is_dir():
            return set()
        document_ids: set[str] = set()
        for path in extraction_dir.glob("extract-*.json"):
            collection = self._read_json(path)
            document_id = _text(_mapping(collection.get("source_document")).get("document_id"))
            if document_id:
                document_ids.add(document_id)
        return document_ids

    def _parameter_candidates(self, paths: ScienceRunPaths, idea_id: str, version: int) -> list[dict[str, Any]]:
        evidence_dir = self._parameter_evidence_dir(paths, idea_id, version)
        extraction_dir = evidence_dir / "extractions"
        candidates: list[dict[str, Any]] = []
        if not extraction_dir.is_dir():
            return candidates
        for path in sorted(extraction_dir.glob("extract-*.json")):
            collection = self._read_json(path)
            for raw_candidate in collection.get("candidates", []):
                candidate = _mapping(raw_candidate)
                candidate_id = _text(candidate.get("candidate_id"))
                parameter_id = _text(candidate.get("parameter_id"))
                if not candidate_id or not parameter_id:
                    continue
                source = _mapping(candidate.get("source"))
                candidates.append(
                    {
                        "candidate_id": candidate_id,
                        "parameter_id": parameter_id,
                        "mathir_symbol": _text(candidate.get("mathir_symbol")),
                        "normalized_value": candidate.get("normalized_value"),
                        "normalized_unit": _text(candidate.get("normalized_unit")),
                        "evidence_status": _text(candidate.get("evidence_status")),
                        "source": {
                            "document_id": _text(source.get("document_id")),
                            "title": _text(source.get("title")),
                            "year": source.get("year") if isinstance(source.get("year"), int) else None,
                        },
                    }
                )
        return candidates[:256]

    def _quantitative_manifest_path(self, paths: ScienceRunPaths, state: Mapping[str, Any]) -> Path:
        record = _mapping(state.get("quantitative_ideas_manifest"))
        path = Path(_text(record.get("path"))).expanduser().resolve()
        try:
            path.relative_to((paths.run_dir / "idea").resolve())
        except ValueError as exc:
            raise RunActionError("Quantitative idea manifest is not bound to this research run.") from exc
        if not path.is_file():
            raise RunActionError("Quantitative idea manifest is unavailable.")
        return path

    def _validate_quantitative_target(
        self,
        paths: ScienceRunPaths,
        *,
        idea_id: str,
        version: int,
        expected_statuses: set[str],
    ) -> dict[str, Any]:
        quantitative_state = self._load_quantitative_state(paths)
        if quantitative_state is None:
            raise RunActionError("Quantitative workflow has not been initialized for this run.")
        ideas = _mapping(quantitative_state.get("ideas"))
        idea = _mapping(ideas.get(idea_id))
        if idea.get("current_version") != version or _text(idea.get("status")) not in expected_statuses:
            raise RunActionError("The requested Q version is not ready for this action.")
        return quantitative_state

    def _validate_execution_request(self, paths: ScienceRunPaths, idea_id: str, version: int, plan_identity: str) -> None:
        quantitative_state = self._validate_quantitative_target(
            paths,
            idea_id=idea_id,
            version=version,
            expected_statuses={"WAITING_FOR_EXECUTION_AUTHORIZATION"},
        )
        version_state = _mapping(
            _mapping(_mapping(quantitative_state.get("ideas")).get(idea_id)).get("versions")
        ).get(f"v{version}")
        version_state = _mapping(version_state)
        if _text(version_state.get("plan_identity")) != plan_identity:
            raise RunActionError("The confirmed plan identity does not match the current materialized plan.")
        version_dir = self._version_dir(paths, idea_id, version)
        plan = self._read_json(version_dir / "simulation_run_plan.json")
        if _text(plan.get("plan_identity")) != plan_identity:
            raise RunActionError("The materialized simulation plan is missing or no longer matches its displayed identity.")
        evidence_dir = self._parameter_evidence_dir(paths, idea_id, version)
        if not (evidence_dir / "approved_parameter_set.json").is_file() or not (
            evidence_dir / "approved_parameter_set_manifest.json"
        ).is_file():
            raise RunActionError("Execution requires the immutable approved parameter set for this Q version.")

    def _validate_quantitative_action_inputs(self, paths: ScienceRunPaths, action: RunActionRequest) -> None:
        """Reject stale or invented browser IDs before a background task is queued."""

        if action.type in {"resume_quantitative", "continue_author", "publish_quantitative_models", "build_quantitative_author_handoff"}:
            return
        state = self._load_quantitative_state(paths)
        if state is None:
            raise RunActionError("Quantitative workflow has not been initialized for this run.")
        if action.type in {"prepare_quantitative_blueprint", "materialize_plan"}:
            self._quantitative_manifest_path(paths, state)
        if action.type == "register_parameter_material":
            if action.material_id not in {item["material_id"] for item in self._parameter_materials(paths)}:
                raise RunActionError("The selected parameter material is not a verified source file for this run.")
            return
        if action.type == "extract_parameters":
            documents = self._parameter_documents(paths, action.idea_id, action.version, include_extracted=False)
            if action.document_id not in {item["document_id"] for item in documents}:
                raise RunActionError("The selected evidence document is not ready for extraction in this Q version.")
            return
        if action.type == "propose_parameters":
            evidence_dir = self._parameter_evidence_dir(paths, action.idea_id, action.version)
            blueprint = self._read_json(evidence_dir / "model_blueprint.json")
            requests = {
                _text(request.get("parameter_id")): request
                for raw_request in blueprint.get("parameter_requests", [])
                if (request := _mapping(raw_request)) and _text(request.get("parameter_id"))
            }
            selections = {selection.parameter_id: selection for selection in action.selections}
            if not requests or set(selections) != set(requests):
                raise RunActionError("Parameter selections must cover exactly the current model blueprint requests.")
            candidates = {candidate["candidate_id"]: candidate for candidate in self._parameter_candidates(paths, action.idea_id, action.version)}
            for parameter_id, selection in selections.items():
                if selection.candidate_id:
                    candidate = candidates.get(selection.candidate_id)
                    if candidate is None or candidate["parameter_id"] != parameter_id:
                        raise RunActionError("A selected parameter candidate is not registered for this blueprint request.")
                    if selection.selected_value is not None and selection.selected_value != candidate["normalized_value"]:
                        raise RunActionError("A candidate-backed selection must retain its extracted normalized value exactly.")
                    continue
                if requests[parameter_id].get("evidence_requirement") not in {
                    "LITERATURE_PREFERRED",
                    "MODEL_ASSUMPTION_ALLOWED",
                }:
                    raise RunActionError("This parameter requires an evidence-backed candidate and cannot use a model assumption.")
                if selection.selected_value is None:
                    raise RunActionError("A model-assumption selection requires an explicit finite numeric value.")
            return
        if action.type == "approve_parameters":
            proposal = self._read_json(
                self._parameter_evidence_dir(paths, action.idea_id, action.version)
                / "parameter_resolution_proposal.json"
            )
            if proposal.get("approval_status") != "READY_FOR_APPROVAL" or proposal.get("unresolved_parameter_ids"):
                raise RunActionError("Only a complete parameter proposal can be approved.")
            return
        if action.type == "qualify_result":
            version_state = _mapping(
                _mapping(_mapping(state.get("ideas")).get(action.idea_id)).get("versions")
            ).get(f"v{action.version}")
            available = _mapping(version_state).get("unqualified_execution_ids")
            if not isinstance(available, list) or action.execution_id not in available:
                raise RunActionError("The requested execution is not awaiting qualification in this Q version.")

    def _validate_quantitative_handoff(self, paths: ScienceRunPaths) -> Path:
        handoff = paths.run_dir / "quantitative" / "author" / "quantitative_author_handoff_manifest.json"
        try:
            handoff.resolve().relative_to((paths.run_dir / "quantitative").resolve())
        except ValueError as exc:
            raise RunActionError("Quantitative Author handoff is outside the current research run.") from exc
        if not handoff.is_file():
            raise RunActionError("A verified quantitative Author handoff is required before continuing Author.")
        return handoff

    def _submit_quantitative_task(
        self,
        *,
        paths: ScienceRunPaths,
        metadata: Mapping[str, Any],
        action: RunActionRequest,
    ) -> None:
        run_id = _text(metadata.get("science_run_id"))

        def task() -> None:
            append_science_event(paths, event_type="QUANTITATIVE_ACTION_STARTED", action=action.type)
            try:
                self._perform_quantitative_action(paths=paths, action=action)
                refreshed = refresh_quantitative_state(paths.run_dir)
            except Exception as exc:
                append_science_event(
                    paths,
                    event_type="QUANTITATIVE_ACTION_FAILED",
                    action=action.type,
                    message=_safe_message(f"{type(exc).__name__}: {exc}"),
                )
                return
            append_science_event(
                paths,
                event_type="QUANTITATIVE_ACTION_COMPLETED",
                action=action.type,
                quantitative_status=_text(refreshed.get("status")),
            )

        try:
            self.supervisor.submit_task(run_id=run_id, task=task)
        except RunActionConflictError:
            raise
        except RunActionError:
            raise
        except Exception as exc:
            raise RunActionConflictError(
                f"The quantitative action could not be queued: {type(exc).__name__}: {_safe_message(exc)}"
            ) from exc

    def _perform_quantitative_action(self, *, paths: ScienceRunPaths, action: RunActionRequest) -> None:
        runtime_config = load_config(str(self.config_path))
        if action.type == "resume_quantitative":
            resume_quantitative_from_existing_idea(
                run_dir=paths.run_dir,
                llm_call=build_quantitative_model_llm_call(config=runtime_config),
            )
            return
        if action.type == "continue_author":
            metadata, _state = load_science_run(paths)
            run_science_workflow(
                paths=paths,
                metadata=metadata,
                until="author",
                quiet=True,
                quantitative_handoff_manifest_path=self._validate_quantitative_handoff(paths),
            )
            return
        if action.type == "publish_quantitative_models":
            publish_quantitative_models_pdf(run_dir=paths.run_dir)
            return
        if action.type == "build_quantitative_author_handoff":
            build_quantitative_author_handoff(
                run_dir=paths.run_dir,
                quantitative_models_pdf_path=paths.run_dir / "quantitative" / "publication" / "quantitative_mathematical_models.pdf",
            )
            return

        idea_id = action.idea_id
        version = action.version
        if action.type == "prepare_quantitative_blueprint":
            state = self._validate_quantitative_target(paths, idea_id=idea_id, version=version, expected_statuses={"WAITING_FOR_BLUEPRINT"})
            prepare_quantitative_model_blueprint(
                run_dir=paths.run_dir,
                quantitative_ideas_manifest_path=self._quantitative_manifest_path(paths, state),
                quantitative_idea_id=idea_id,
                version=version,
                llm_call=build_quantitative_model_llm_call(config=runtime_config),
            )
            return
        if action.type == "discover_parameters":
            self._validate_quantitative_target(paths, idea_id=idea_id, version=version, expected_statuses={"WAITING_FOR_PARAMETER_EVIDENCE"})
            discover_quantitative_parameter_evidence(
                run_dir=paths.run_dir,
                quantitative_idea_id=idea_id,
                version=version,
                fetch=True,
                runtime_config=runtime_config,
            )
            return
        if action.type == "fetch_open_access_fulltext":
            self._validate_quantitative_target(paths, idea_id=idea_id, version=version, expected_statuses={"WAITING_FOR_PARAMETER_EVIDENCE"})
            fetch_quantitative_parameter_fulltext(
                run_dir=paths.run_dir,
                quantitative_idea_id=idea_id,
                version=version,
                fetch=True,
                runtime_config=runtime_config,
            )
            return
        if action.type == "register_parameter_material":
            self._validate_quantitative_target(paths, idea_id=idea_id, version=version, expected_statuses={"WAITING_FOR_PARAMETER_EVIDENCE"})
            material = next((item for item in self._parameter_materials(paths) if item["material_id"] == action.material_id), None)
            if material is None:
                raise RunActionError("The selected parameter material is not a verified source file for this run.")
            records = _mapping(_mapping(load_science_run(paths)[0].get("immutable_inputs")).get("materials")).get("records")
            record = next((item for item in records if isinstance(item, Mapping) and item.get("material_id") == action.material_id), None) if isinstance(records, list) else None
            stored_name = _text(_mapping(record).get("stored_name"))
            source = (paths.inputs / "files" / stored_name).resolve()
            register_quantitative_parameter_document(
                run_dir=paths.run_dir,
                quantitative_idea_id=idea_id,
                version=version,
                document_path=source,
                document_id=f"USR-{action.material_id[4:]}",
                title=material["title"],
            )
            return
        if action.type == "extract_parameters":
            self._validate_quantitative_target(paths, idea_id=idea_id, version=version, expected_statuses={"WAITING_FOR_PARAMETER_EVIDENCE", "WAITING_FOR_PARAMETER_REVIEW"})
            if action.document_id not in {item["document_id"] for item in self._parameter_documents(paths, idea_id, version, include_extracted=False)}:
                raise RunActionError("The selected evidence document is not ready for extraction in this Q version.")
            extract_quantitative_parameter_candidates(
                run_dir=paths.run_dir,
                quantitative_idea_id=idea_id,
                version=version,
                document_id=action.document_id,
                llm_call=build_quantitative_model_llm_call(config=runtime_config),
            )
            return
        if action.type == "propose_parameters":
            self._validate_quantitative_target(paths, idea_id=idea_id, version=version, expected_statuses={"WAITING_FOR_PARAMETER_REVIEW"})
            propose_quantitative_parameter_resolution(
                run_dir=paths.run_dir,
                quantitative_idea_id=idea_id,
                version=version,
                selections=[selection.model_dump(exclude_none=True) for selection in action.selections],
            )
            return
        if action.type == "approve_parameters":
            self._validate_quantitative_target(paths, idea_id=idea_id, version=version, expected_statuses={"WAITING_FOR_PARAMETER_APPROVAL"})
            approve_quantitative_parameter_resolution(
                run_dir=paths.run_dir,
                quantitative_idea_id=idea_id,
                version=version,
                approve=True,
            )
            return
        if action.type == "materialize_plan":
            state = self._validate_quantitative_target(paths, idea_id=idea_id, version=version, expected_statuses={"PARAMETERS_APPROVED"})
            materialize_quantitative_model_version(
                run_dir=paths.run_dir,
                quantitative_ideas_manifest_path=self._quantitative_manifest_path(paths, state),
                quantitative_idea_id=idea_id,
                version=version,
                llm_call=build_quantitative_model_llm_call(config=runtime_config),
            )
            return
        if action.type == "execute_plan":
            self._validate_execution_request(paths, idea_id, version, action.plan_identity)
            execute_quantitative_plan(
                run_dir=paths.run_dir,
                quantitative_idea_id=idea_id,
                version=version,
                execute=True,
                confirmed_plan_identity=action.plan_identity,
            )
            return
        if action.type == "qualify_result":
            self._validate_quantitative_target(paths, idea_id=idea_id, version=version, expected_statuses={"WAITING_FOR_QUALIFICATION"})
            qualify_quantitative_execution(
                run_dir=paths.run_dir,
                quantitative_idea_id=idea_id,
                version=version,
                execution_id=action.execution_id,
                hypothesis_relation=action.hypothesis_relation,
                result_summary=action.result_summary,
            )
            return
        if action.type == "propose_refinement":
            self._validate_quantitative_target(paths, idea_id=idea_id, version=version, expected_statuses={"QUALIFIED_WAITING_FOR_REVISION_DECISION"})
            propose_quantitative_refinement(
                run_dir=paths.run_dir,
                quantitative_idea_id=idea_id,
                version=version,
                revision_reason=action.revision_reason,
                hypothesis_delta=action.hypothesis_delta,
                model_delta=action.model_delta,
                parameter_or_boundary_delta=action.parameter_or_boundary_delta,
                expected_discriminating_result=action.expected_discriminating_result,
                falsification_condition=action.falsification_condition,
            )
            return
        if action.type == "accept_refinement":
            self._validate_quantitative_target(paths, idea_id=idea_id, version=version, expected_statuses={"WAITING_FOR_REVISION_APPROVAL"})
            accept_quantitative_refinement(
                run_dir=paths.run_dir,
                quantitative_idea_id=idea_id,
                parent_version=version,
                accept=True,
            )
            return
        if action.type == "finalize_quantitative_idea":
            self._validate_quantitative_target(
                paths,
                idea_id=idea_id,
                version=version,
                expected_statuses={"QUALIFIED_WAITING_FOR_REVISION_DECISION", "WAITING_FOR_REVISION_APPROVAL"},
            )
            finalize_quantitative_idea(run_dir=paths.run_dir, quantitative_idea_id=idea_id, version=version)
            return
        raise RunActionError("Unsupported quantitative action.")

    def _view(self, paths: ScienceRunPaths, metadata: Mapping[str, Any], state: Mapping[str, Any]) -> RunView:
        immutable_inputs = _mapping(metadata.get("immutable_inputs"))
        options = _mapping(immutable_inputs.get("options"))
        materials = _mapping(immutable_inputs.get("materials"))
        web = _mapping(immutable_inputs.get("web"))
        stages = _mapping(state.get("stages"))
        view_stages: dict[str, dict[str, object]] = {}
        for stage_name in SCIENCE_STAGE_NAMES:
            stage = _mapping(stages.get(stage_name))
            failure = _mapping(stage.get("failure"))
            view_stages[stage_name] = {
                "status": _text(stage.get("status")) or "PENDING",
                "attempt": int(stage.get("attempt") or 0),
                "started_at": stage.get("started_at"),
                "finished_at": stage.get("finished_at"),
                "failure": (
                    {
                        "error_type": _text(failure.get("error_type")),
                        "exit_code": failure.get("exit_code"),
                        "message": _safe_message(failure.get("message")),
                    }
                    if failure
                    else None
                ),
            }
        quantitative_mode = self._quantitative_mode(metadata)
        stored_quantitative = self._load_quantitative_state(paths)
        quantitative = self._quantitative_view(
            paths=paths,
            state=state,
            quantitative_mode=quantitative_mode,
            quantitative_state=stored_quantitative,
        )
        raw_records = materials.get("records")
        safe_materials = [dict(record) for record in raw_records if isinstance(record, Mapping)] if isinstance(raw_records, list) else []
        raw_cancellation = _mapping(state.get("cancellation"))
        cancellation = (
            {
                key: raw_cancellation[key]
                for key in ("requested_at", "requested_stage", "acknowledged_at")
                if key in raw_cancellation
            }
            if raw_cancellation
            else None
        )
        return RunView(
            run_id=_text(metadata.get("science_run_id")),
            topic=_text(immutable_inputs.get("topic")),
            created_at=_text(metadata.get("created_at")),
            last_updated_at=_text(state.get("last_updated_at")),
            status=_text(state.get("status")) or "PENDING",
            execution_mode=_text(metadata.get("execution_mode")) or "DESIGN_ONLY",
            discipline_ids=[entry.label for entry in get_discipline_entries(options.get("discipline_ids"))],
            quantitative_mode=quantitative_mode,  # type: ignore[arg-type]
            language=_text(web.get("language")) or "zh-CN",
            remote_perception_authorized=bool(materials.get("remote_perception_authorized")),
            stages=view_stages,
            materials=safe_materials,
            allowed_actions=self._allowed_actions(paths, metadata, state),
            next_step=self._next_step(state),
            cancellation=cancellation,
            event_url=f"/api/runs/{_text(metadata.get('science_run_id'))}/events",
            artifacts=list_artifacts(paths, state),
            quantitative=quantitative,
        )

    def _quantitative_view(
        self,
        *,
        paths: ScienceRunPaths,
        state: Mapping[str, Any],
        quantitative_mode: str,
        quantitative_state: Mapping[str, Any] | None,
    ) -> dict[str, object] | None:
        if quantitative_mode == "off":
            return None
        if quantitative_state is None:
            return {
                "status": "NOT_INITIALIZED",
                "ideas": {},
                "available_parameter_materials": self._parameter_materials(paths),
                "allowed_actions": self._quantitative_actions(
                    paths=paths,
                    state=state,
                    quantitative_mode=quantitative_mode,
                    quantitative_state=None,
                ),
            }
        ideas = _mapping(quantitative_state.get("ideas"))
        safe_ideas: dict[str, object] = {}
        for idea_id in ("Q1", "Q2"):
            raw_idea = _mapping(ideas.get(idea_id))
            if not raw_idea:
                continue
            versions = _mapping(raw_idea.get("versions"))
            safe_versions: dict[str, object] = {}
            for version_name in ("v0", "v1", "v2"):
                raw_version = _mapping(versions.get(version_name))
                if not raw_version:
                    continue
                safe_versions[version_name] = {
                    key: raw_version[key]
                    for key in (
                        "version",
                        "parent_version",
                        "status",
                        "parameterization_mode",
                        "parameter_set_identity",
                        "model_spec_identity",
                        "plan_identity",
                        "execution_ids",
                        "unqualified_execution_ids",
                        "qualification_status",
                    )
                    if key in raw_version
                }
            safe_ideas[idea_id] = {
                "quantitative_idea_id": idea_id,
                "title": _text(raw_idea.get("title")),
                "status": _text(raw_idea.get("status")),
                "current_version": raw_idea.get("current_version"),
                "versions": safe_versions,
            }

        active = self._active_quantitative_idea(quantitative_state)
        context: dict[str, object] = {
            "documents": [],
            "parameter_requests": [],
            "candidates": [],
            "proposal": None,
        }
        if active is not None:
            idea_id, version, _status = active
            evidence_dir = self._parameter_evidence_dir(paths, idea_id, version)
            blueprint = self._read_json(evidence_dir / "model_blueprint.json")
            context = {
                "documents": self._parameter_documents(paths, idea_id, version, include_extracted=True),
                "parameter_requests": [
                    {
                        key: request[key]
                        for key in (
                            "parameter_id",
                            "mathir_symbol",
                            "meaning",
                            "unit",
                            "dimension",
                            "role",
                            "evidence_requirement",
                            "required_conditions",
                        )
                        if key in request
                    }
                    for raw_request in blueprint.get("parameter_requests", [])
                    if (request := _mapping(raw_request))
                ],
                "candidates": self._parameter_candidates(paths, idea_id, version),
                "proposal": self._safe_parameter_proposal(
                    self._read_json(evidence_dir / "parameter_resolution_proposal.json")
                ),
            }
        displayed_actions = [] if self.supervisor.is_active(_text(state.get("science_run_id"))) else self._quantitative_actions(
            paths=paths,
            state=state,
            quantitative_mode=quantitative_mode,
            quantitative_state=quantitative_state,
        )
        return {
            "status": _text(quantitative_state.get("status")),
            "ideas": safe_ideas,
            "active": (
                {"idea_id": active[0], "version": active[1], "status": active[2]}
                if active is not None
                else None
            ),
            "available_parameter_materials": self._parameter_materials(paths),
            "allowed_actions": displayed_actions,
            **context,
        }

    @staticmethod
    def _safe_parameter_proposal(proposal: Mapping[str, Any]) -> dict[str, object] | None:
        if not proposal:
            return None
        entries: list[dict[str, object]] = []
        for raw_entry in proposal.get("entries", []):
            entry = _mapping(raw_entry)
            if not entry:
                continue
            entries.append(
                {
                    key: entry[key]
                    for key in (
                        "parameter_id",
                        "mathir_symbol",
                        "selected_value",
                        "unit",
                        "provenance_status",
                        "candidate_id",
                        "selection_rationale",
                    )
                    if key in entry
                }
            )
        return {
            "approval_status": _text(proposal.get("approval_status")),
            "proposal_identity": _text(proposal.get("proposal_identity")),
            "unresolved_parameter_ids": [
                _text(value) for value in proposal.get("unresolved_parameter_ids", []) if _text(value)
            ],
            "entries": entries,
        }

    @staticmethod
    def _next_step(state: Mapping[str, Any]) -> str:
        stages = _mapping(state.get("stages"))
        cancellation = _mapping(state.get("cancellation"))
        if cancellation:
            requested_stage = _text(cancellation.get("requested_stage")) or "current stage"
            if _text(cancellation.get("acknowledged_at")):
                return f"Research was stopped after {requested_stage}; completed work is preserved and can be resumed."
            return f"Cancellation is pending for {requested_stage}; the current stage will finish safely before stopping."
        for stage_name in SCIENCE_STAGE_NAMES:
            stage = _mapping(stages.get(stage_name))
            status = _text(stage.get("status"))
            if status == "FAILED":
                return f"{stage_name} failed and can be resumed after reviewing the recorded error."
            if status == "PENDING":
                return f"{stage_name} is the next science stage."
            if status == "RUNNING":
                return f"{stage_name} is running. Progress is recorded in the event timeline."
        return "The requested science workflow is complete."


__all__ = [
    "DEFAULT_CONFIG_PATH",
    "REPO_ROOT",
    "RunActionError",
    "RunActionConflictError",
    "RunNotFoundError",
    "RunService",
    "WebRunError",
    "WorkflowSupervisor",
]
