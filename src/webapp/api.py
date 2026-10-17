"""FastAPI control plane and same-origin host for the V2 research workspace."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timezone
import json
import hashlib
import re
import uuid
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from sse_starlette.sse import EventSourceResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from src.config import load_config
from src.llm.model_policy import TEXT_MODEL_CHOICES
from src.llm.json_call import RequiredJsonLLMError
from src.agents.experiment_design_agent.discipline_catalog import list_discipline_catalog
from src.pipeline.discipline_taxonomy import get_discipline_entry, resolve_discipline_taxonomy
from src.pipeline.science_run import (
    ScienceRunConflictError,
    ScienceRunInputError,
    ScienceRunLockError,
    load_science_run,
)

from .artifact_service import artifact_index
from .capability_service import CapabilityService
from .discipline_service import recognize_disciplines
from .event_stream import stream_events
from .export_service import ExportError, ExportUnavailable, export_feature
from .feature_review import apply_feature_review, read_feature_result, read_review
from .file_schemas import FileView
from .file_service import FileService, FileServiceError
from .feature_job_service import FeatureJobError
from .feature_schemas import (
    FeatureActionRequest,
    FeatureExportRequest,
    FigureJobCreate,
    PolishJobCreate,
    TranslationJobCreate,
    job_view,
)
from .figure_service import FigureService
from .job_artifacts import list_job_artifacts, resolve_job_artifact
from .log_service import MAX_LOG_CHUNK_BYTES, RunLogError, list_run_logs, read_run_log
from .representative_service import default_representative_root, list_representative_projects, representative_file
from .material_service import MaterialUploadError, parse_material_metadata, read_material, remove_material, store_materials
from .redaction import safe_text
from .run_service import (
    DEFAULT_CONFIG_PATH,
    REPO_ROOT,
    RunActionConflictError,
    RunActionError,
    RunNotFoundError,
    RunService,
)
from .jobs import JobRegistry, JobRunner, JobStore
from .jobs.errors import JobConflictError, JobNotFoundError, JobStateError
from .jobs.schemas import JobActionRequest, JobReviewRequest, JobReviewView, JobView
from .jobs.events import stream_job_events
from .polish_service import PolishService
from .preferences_schemas import PreferenceEnvelope, ResearchPreferences
from .preferences_service import PreferenceConflictError, PreferencesService
from .prompts import build_default_prompt_registry
from .translation_service import TranslationService
from .runtime_settings import WebRuntimeSettings
from .product_service import ProductService
from .schemas import CreateRunRequest, MaterialUploadResponse, ParameterSearchRequest, ParameterSearchSelectionRequest, ParameterSearchView, RepresentativeProjectView, ResolveDisciplineRequest, RunActionRequest, RunLogChunkView, RunLogView, RunView


class FrontendFiles(StaticFiles):
    client_route = re.compile(
        r"(?:products(?:/qwensci)?|app(?:/(?:preferences|(?:full-research|light-research|figure|polish|translate)(?:/[A-Za-z0-9_-]{1,128})?))?)/?"
    )

    async def get_response(self, path: str, scope: dict) -> Response:
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code != 404 or scope["method"] not in {"GET", "HEAD"}:
                raise
            if not self.client_route.fullmatch(path):
                raise
            return await super().get_response("index.html", scope)
from .science_job_service import DurableWorkflowSupervisor, ScienceJobService


_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")


class WebHTTPException(HTTPException):
    """HTTP error carrying a stable public error code."""

    def __init__(
        self,
        status_code: int,
        detail: str,
        *,
        code: str | None = None,
        retryable: bool | None = None,
    ) -> None:
        super().__init__(status_code=status_code, detail=detail)
        self.error_code = code
        self.retryable = retryable


def _http_error(
    status_code: int,
    detail: str,
    *,
    code: str | None = None,
    retryable: bool | None = None,
) -> WebHTTPException:
    return WebHTTPException(status_code, detail, code=code, retryable=retryable)


def _feature_http_error(exc: FeatureJobError) -> HTTPException:
    error_code = str(getattr(exc, "code", "FEATURE_INPUT_INVALID"))
    status = {
        "CAPABILITY_UNAVAILABLE": 503,
        "PROMPT_UNAVAILABLE": 503,
        "IDEMPOTENCY_CONFLICT": 409,
    }.get(error_code, 422)
    return _http_error(
        status,
        str(exc),
        code=error_code,
        retryable=bool(getattr(exc, "retryable", False)) or status in {409, 429, 503},
    )


def _atomic_json(path: Path, payload: dict[str, object]) -> None:
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _load_job_manifest(store: JobStore, record: object) -> dict[str, object]:
    if not hasattr(record, "job_id"):
        raise ExportError("Unknown Job.")
    path = store.job_directory(record.job_id) / "input.json"
    try:
        raw = path.read_bytes()
        payload = json.loads(raw)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ExportError("The frozen Job manifest is unavailable.") from exc
    if not isinstance(payload, dict) or hashlib.sha256(raw).hexdigest() != record.input_manifest_sha256:
        raise ExportError("The frozen Job manifest no longer matches its recorded hash.")
    return payload


def _export_feature_job(
    store: JobStore, file_service: FileService, kind: str, job_id: str, request: FeatureExportRequest,
) -> Response:
    try:
        record = store.get(job_id)
    except JobNotFoundError as exc:
        raise _http_error(404, str(exc)) from exc
    if record.kind != kind:
        raise _http_error(404, "Unknown feature Job.")
    if record.status != "SUCCEEDED":
        raise _http_error(409, "Accept the Job review before exporting its final document.")
    try:
        body, media_type, filename, artifact_id = export_feature(
            store, file_service, kind=kind, job_id=job_id, output_format=request.format,
            expected_review_version=request.expected_review_version,
        )
    except ExportUnavailable as exc:
        raise _http_error(503, str(exc)) from exc
    except (JobStateError, JobConflictError) as exc:
        raise _http_error(409, str(exc)) from exc
    except ExportError as exc:
        raise _http_error(422, str(exc)) from exc
    return Response(content=body, media_type=media_type, headers={
        "Content-Disposition": f'attachment; filename="{filename}"', "X-Artifact-ID": artifact_id,
    })


def _catalog_suggestions(resolution: dict[str, object]) -> list[str]:
    suggestions: list[str] = []
    raw_ids = resolution.get("discipline_ids")
    if not isinstance(raw_ids, list):
        return suggestions
    for discipline_key in raw_ids:
        entry = get_discipline_entry(discipline_key)
        if entry is None:
            continue
        for field_id in entry.openalex_field_ids:
            if field_id not in suggestions:
                suggestions.append(field_id)
    return suggestions[:2]


def create_app(
    *,
    run_root: str | Path | None = None,
    config_path: str | Path = DEFAULT_CONFIG_PATH,
    serve_frontend: bool = True,
    representative_root: str | Path | None = None,
    database_path: str | Path | None = None,
) -> FastAPI:
    runtime = WebRuntimeSettings.from_config(
        load_config(str(config_path)), repo_root=REPO_ROOT, run_root=run_root,
        database_path=database_path,
    )
    service = RunService(run_root=runtime.run_root, config_path=config_path)
    job_store = JobStore(runtime.database_path, job_root=runtime.job_root)
    service.bind_job_store(job_store)
    job_registry = JobRegistry()
    job_runner = JobRunner(
        job_store, job_registry, max_workers=runtime.max_workers,
        lease_seconds=max(runtime.stale_after_seconds, runtime.heartbeat_seconds * 3),
        stale_after_seconds=runtime.stale_after_seconds,
        heartbeat_seconds=runtime.heartbeat_seconds,
        default_timeout_seconds=runtime.default_timeout_seconds,
    )
    file_service = FileService(
        runtime.file_root, max_file_bytes=runtime.max_upload_bytes,
        max_project_bytes=runtime.max_project_bytes,
        max_uncompressed_bytes=runtime.max_uncompressed_bytes,
    )
    file_service.job_store = job_store
    figure_service = None
    polish_service = None
    translation_service = None
    capability_service = CapabilityService(config_path=config_path)
    preferences_service = PreferencesService(runtime.run_root.parent / "preferences.json")
    science_service = ScienceJobService(
        store=job_store, runner=job_runner, registry=job_registry,
        file_service=file_service, prompt_registry=build_default_prompt_registry(),
        config_path=config_path,
    )
    science_service.bind(service)
    science_service.register_handler()
    service.supervisor = DurableWorkflowSupervisor(science_service)
    service.parameter_search._submit_task = service.supervisor.submit_task
    service.parameter_search.submit_search = service.supervisor.submit_search
    service.preferences_service = preferences_service
    resolved_representative_root = Path(representative_root).expanduser().resolve() if representative_root is not None else default_representative_root()
    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        file_service.reconcile_job_references()
        job_runner.start()
        try:
            yield
        finally:
            job_runner.shutdown(wait=False)
            shutdown_supervisor = getattr(service.supervisor, "shutdown", None)
            if callable(shutdown_supervisor):
                shutdown_supervisor()

    app = FastAPI(title="Qwen-Sci Web Control Plane", version="1.0", lifespan=lifespan)

    def request_id(request: Request) -> str:
        candidate = request.headers.get("x-request-id", "").strip()
        if _REQUEST_ID_PATTERN.fullmatch(candidate):
            return candidate
        return f"req-{uuid.uuid4().hex[:16]}"

    async def http_error_handler(request: Request, exc: HTTPException) -> JSONResponse:
        correlation_id = request_id(request)
        status = int(exc.status_code)
        code = getattr(exc, "error_code", None) or {
            400: "BAD_REQUEST",
            403: "FORBIDDEN",
            404: "NOT_FOUND",
            409: "STATE_CONFLICT",
            413: "PAYLOAD_TOO_LARGE",
            422: "INPUT_INVALID",
            429: "RATE_LIMITED",
            503: "CAPABILITY_UNAVAILABLE",
        }.get(status, "HTTP_ERROR")
        retryable = getattr(exc, "retryable", None)
        if retryable is None:
            retryable = status in {409, 429, 503}
        return JSONResponse(
            status_code=status,
            content={
                "error": {
                    "code": str(code),
                    "message": safe_text(str(exc.detail)),
                    "retryable": bool(retryable),
                    "request_id": correlation_id,
                }
            },
            headers={"X-Request-ID": correlation_id},
        )

    async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        correlation_id = request_id(request)
        details: list[dict[str, object]] = []
        for error in exc.errors():
            location = [str(part) for part in error.get("loc", ()) if str(part) not in {"body", "query", "path"}]
            details.append({
                "loc": location or ["request"],
                "code": str(error.get("type") or "invalid_request"),
                "message": safe_text(str(error.get("msg") or "Invalid value.")),
            })
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "REQUEST_VALIDATION_FAILED",
                    "message": "Request validation failed.",
                    "retryable": False,
                    "request_id": correlation_id,
                    "details": details,
                }
            },
            headers={"X-Request-ID": correlation_id},
        )

    async def unexpected_error_handler(request: Request, _exc: Exception) -> JSONResponse:
        correlation_id = request_id(request)
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": "INTERNAL_ERROR",
                    "message": "The server could not complete the request.",
                    "retryable": True,
                    "request_id": correlation_id,
                }
            },
            headers={"X-Request-ID": correlation_id},
        )

    app.add_exception_handler(HTTPException, http_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(Exception, unexpected_error_handler)
    app.state.runtime_settings = runtime
    app.state.run_service = service
    app.state.job_store = job_store
    app.state.job_registry = job_registry
    app.state.job_runner = job_runner
    app.state.file_service = file_service
    app.state.figure_service = figure_service
    app.state.polish_service = polish_service
    app.state.translation_service = translation_service
    app.state.prompt_registry = build_default_prompt_registry()
    app.state.capability_service = capability_service
    app.state.preferences_service = preferences_service
    app.state.science_service = science_service

    if job_store is not None and job_runner is not None and file_service is not None:
        figure_service = FigureService(
            store=job_store,
            runner=job_runner,
            registry=job_registry,
            file_service=file_service,
            prompt_registry=app.state.prompt_registry,
            config_path=config_path,
        )
        polish_service = PolishService(
            store=job_store,
            runner=job_runner,
            registry=job_registry,
            file_service=file_service,
            prompt_registry=app.state.prompt_registry,
            config_path=config_path,
        )
        translation_service = TranslationService(
            store=job_store,
            runner=job_runner,
            registry=job_registry,
            file_service=file_service,
            prompt_registry=app.state.prompt_registry,
            config_path=config_path,
        )
        figure_service.register_handler()
        polish_service.register_handler()
        translation_service.register_handler()
        for feature_service in (figure_service, polish_service, translation_service):
            feature_service.preferences_service = preferences_service
            feature_service.run_service = service
        app.state.figure_service = figure_service
        app.state.polish_service = polish_service
        app.state.translation_service = translation_service

    @app.get("/api/health")
    def health() -> dict[str, object]:
        return {
            "status": "ok",
            "runs_detected": len(service.list_runs()),
            "jobs_detected": len(job_store.list(limit=1_000)) if job_store is not None else 0,
        }

    @app.get("/api/capabilities")
    def capabilities() -> dict[str, object]:
        return capability_service.snapshot()

    product_service = ProductService(capability_service, resolved_representative_root)

    @app.get("/api/product/modules")
    def product_modules() -> list[dict[str, object]]:
        return product_service.modules()

    @app.get("/api/product/capabilities")
    def product_capabilities() -> dict[str, object]:
        return capability_service.snapshot()

    @app.get("/api/product/preview/{module_id}")
    def product_preview(module_id: str) -> dict[str, object]:
        try:
            return product_service.preview(module_id)
        except KeyError as exc:
            raise _http_error(404, "Unknown product module.") from exc

    @app.get("/api/preferences/schema")
    def preferences_schema() -> dict[str, object]:
        return {
            "scope": "workspace",
            "auth_required": False,
            "fields": {
                "language": ["zh-CN", "en"],
                "model_profile": ["fast", "balanced", "quality"],
                "default_text_model": list(TEXT_MODEL_CHOICES),
                "default_research_depth": ["light", "full"],
                "default_output_format": ["markdown", "docx", "pdf"],
                "network_access": ["never", "ask", "allowed"],
                "privacy_mode": ["controlled-materials", "local-only"],
            },
        }

    @app.get("/api/preferences", response_model=PreferenceEnvelope)
    def get_preferences() -> PreferenceEnvelope:
        try:
            return preferences_service.get()
        except PreferenceConflictError as exc:
            raise _http_error(500, str(exc)) from exc

    @app.put("/api/preferences", response_model=PreferenceEnvelope)
    def update_preferences(request_body: ResearchPreferences) -> PreferenceEnvelope:
        try:
            return preferences_service.update(request_body)
        except PreferenceConflictError as exc:
            raise _http_error(409, str(exc)) from exc

    @app.post("/api/files", response_model=FileView, status_code=201)
    async def upload_shared_file(
        file: UploadFile = File(...),
        project_id: str | None = Form(default=None),
        sensitivity: str = Form(default="controlled"),
    ) -> FileView:
        if file_service is None:
            raise _http_error(503, "Shared file storage is unavailable for this app instance.")
        try:
            return file_service.register_upload(
                file,
                project_id=project_id,
                sensitivity=sensitivity,  # type: ignore[arg-type]
            )
        except FileServiceError as exc:
            raise _http_error(422, str(exc)) from exc

    @app.get("/api/files", response_model=list[FileView])
    def list_shared_files(
        project_id: str | None = Query(default=None, max_length=256),
        limit: int = Query(default=100, ge=1, le=1_000),
    ) -> list[FileView]:
        if file_service is None:
            return []
        return file_service.list(project_id=project_id, limit=limit)

    @app.get("/api/files/{file_id}", response_model=FileView)
    def get_shared_file(file_id: str) -> FileView:
        if file_service is None:
            raise _http_error(503, "Shared file storage is unavailable for this app instance.")
        try:
            return file_service.get(file_id)
        except FileServiceError as exc:
            raise _http_error(404, str(exc)) from exc

    @app.get("/api/files/{file_id}/content")
    def read_shared_file(file_id: str) -> FileResponse:
        if file_service is None:
            raise _http_error(503, "Shared file storage is unavailable for this app instance.")
        try:
            path = file_service.content_path(file_id)
            record = file_service.get(file_id)
            return FileResponse(path, filename=record.original_name, media_type=record.mime_type)
        except FileServiceError as exc:
            raise _http_error(404, str(exc)) from exc

    @app.delete("/api/files/{file_id}", status_code=204)
    def delete_shared_file(file_id: str) -> None:
        if file_service is None:
            raise _http_error(503, "Shared file storage is unavailable for this app instance.")
        try:
            file_service.delete(file_id)
        except FileServiceError as exc:
            status = 409 if "referenced" in str(exc).casefold() else 404
            raise _http_error(status, str(exc)) from exc

    @app.get("/api/jobs", response_model=list[JobView])
    def list_jobs(
        kind: str | None = Query(default=None, max_length=32),
        status: list[str] | None = Query(default=None),
        project_id: str | None = Query(default=None, max_length=256),
        run_id: str | None = Query(default=None, max_length=128),
        limit: int = Query(default=100, ge=1, le=1_000),
        offset: int = Query(default=0, ge=0),
    ) -> list[JobView]:
        if job_store is None:
            return []
        try:
            records = job_store.list(
                kind=kind,  # type: ignore[arg-type]
                statuses=tuple(status) if status else None,  # type: ignore[arg-type]
                limit=limit,
                project_id=project_id, run_id=run_id, offset=offset,
            )
            return [JobView.from_record(record) for record in records]
        except JobStateError as exc:
            raise _http_error(422, str(exc)) from exc

    @app.get("/api/jobs/{job_id}", response_model=JobView)
    def get_job(job_id: str) -> JobView:
        if job_store is None:
            raise _http_error(503, "Job storage is unavailable for this app instance.")
        try:
            return JobView.from_record(job_store.get(job_id))
        except JobNotFoundError as exc:
            raise _http_error(404, str(exc)) from exc

    @app.get("/api/jobs/{job_id}/artifacts")
    def list_job_artifact_records(job_id: str) -> list[dict[str, object]]:
        if job_store is None:
            raise _http_error(503, "Job storage is unavailable for this app instance.")
        try:
            record = job_store.get(job_id)
            artifacts = list_job_artifacts(job_store.job_directory(record.job_id))
            return [
                {
                    key: value
                    for key, value in artifact.items()
                    if key not in {"relative_path", "source_file_ids"}
                }
                for artifact in artifacts
                if artifact.get("artifact_id") in record.output_artifact_ids
            ]
        except JobNotFoundError as exc:
            raise _http_error(404, str(exc)) from exc

    @app.get("/api/jobs/{job_id}/artifacts/{artifact_id}")
    def read_job_artifact(job_id: str, artifact_id: str) -> FileResponse:
        if job_store is None:
            raise _http_error(503, "Job storage is unavailable for this app instance.")
        try:
            record = job_store.get(job_id)
            if artifact_id not in record.output_artifact_ids:
                raise _http_error(404, "Unknown Job artifact.")
            resolved = resolve_job_artifact(job_store.job_directory(record.job_id), artifact_id)
        except JobNotFoundError as exc:
            raise _http_error(404, str(exc)) from exc
        if resolved is None:
            raise _http_error(404, "Unknown Job artifact.")
        path, metadata = resolved
        return FileResponse(
            path,
            filename=str(metadata.get("label") or path.name),
            media_type=str(metadata.get("media_type") or "application/octet-stream"),
        )

    @app.post("/api/jobs/{job_id}/actions", response_model=JobView, status_code=202)
    def job_action(job_id: str, request_body: JobActionRequest) -> JobView:
        if job_store is None:
            raise _http_error(503, "Job storage is unavailable for this app instance.")
        try:
            if request_body.type == "cancel":
                record = job_runner.request_cancel(job_id) if job_runner is not None else job_store.request_cancel(job_id)
            else:
                record = job_store.retry(job_id)
                if job_runner is not None:
                    job_runner.submit(job_id)
            return JobView.from_record(record)
        except JobNotFoundError as exc:
            raise _http_error(404, str(exc)) from exc
        except (JobConflictError, JobStateError) as exc:
            raise _http_error(409, str(exc)) from exc

    @app.post("/api/jobs/{job_id}/artifacts/{artifact_id}/files", response_model=FileView, status_code=201)
    def reuse_job_artifact(job_id: str, artifact_id: str) -> FileView:
        try:
            record = job_store.get(job_id)
            if record.status != "SUCCEEDED":
                raise _http_error(409, "Accept the source Job before reusing its artifacts.")
            if artifact_id not in record.output_artifact_ids:
                raise JobNotFoundError("Unknown committed Job artifact.")
            resolved = resolve_job_artifact(job_store.job_directory(job_id), artifact_id)
            if resolved is None:
                raise JobNotFoundError("Unknown committed Job artifact.")
            return file_service.register_artifact(resolved[0], metadata=resolved[1], project_id=record.project_id)
        except JobNotFoundError as exc:
            raise _http_error(404, str(exc)) from exc
        except FileServiceError as exc:
            raise _http_error(422, str(exc)) from exc

    @app.get("/api/jobs/{job_id}/review", response_model=JobReviewView)
    def get_job_review(job_id: str) -> JobReviewView:
        if job_store is None:
            raise _http_error(503, "Job storage is unavailable for this app instance.")
        try:
            record = job_store.get(job_id)
            ledger = read_review(job_store, record)
            return JobReviewView(
                job_id=record.job_id,
                attempt=record.attempt,
                revision=record.revision,
                review_version=ledger["version"],
                decision=ledger.get("decision"),
                segments=ledger.get("segments", {}),
                pages=ledger.get("pages", {}),
            )
        except JobNotFoundError as exc:
            raise _http_error(404, str(exc)) from exc
        except JobStateError as exc:
            raise _http_error(409, str(exc)) from exc

    @app.post("/api/jobs/{job_id}/review", response_model=JobView, status_code=202)
    def review_job(job_id: str, request_body: JobReviewRequest) -> JobView:
        if job_store is None:
            raise _http_error(503, "Job storage is unavailable for this app instance.")
        try:
            record = job_store.get(job_id)
            updated = apply_feature_review(job_store, job_runner, record, FeatureActionRequest(
                type="accept" if request_body.accepted else "reject", notes=request_body.notes,
                expected_attempt=request_body.expected_attempt,
                expected_review_version=request_body.expected_review_version,
            ))
            return JobView.from_record(updated)
        except JobNotFoundError as exc:
            raise _http_error(404, str(exc)) from exc
        except (JobStateError, JobConflictError) as exc:
            raise _http_error(409, str(exc)) from exc

    @app.get("/api/jobs/{job_id}/events")
    async def job_events(
        job_id: str,
        request: Request,
        after: int = Query(default=0, ge=0),
        follow: bool = True,
    ) -> EventSourceResponse:
        if job_store is None:
            raise _http_error(503, "Job storage is unavailable for this app instance.")
        try:
            job_store.get(job_id)
        except JobNotFoundError as exc:
            raise _http_error(404, str(exc)) from exc

        last_event_id = request.headers.get("last-event-id", "")
        if last_event_id.isdigit():
            after = max(after, int(last_event_id))
        return EventSourceResponse(stream_job_events(request, store=job_store, job_id=job_id, after=after, follow=follow))

    @app.post("/api/figure/jobs", response_model=JobView, status_code=202)
    def create_figure_job(request_body: FigureJobCreate) -> JobView:
        if figure_service is None:
            raise _http_error(503, "Figure Jobs are unavailable for this app instance.")
        try:
            return job_view(figure_service.create(request_body))
        except FeatureJobError as exc:
            raise _feature_http_error(exc) from exc
        except JobConflictError as exc:
            raise _http_error(409, str(exc)) from exc

    @app.post("/api/polish/jobs", response_model=JobView, status_code=202)
    def create_polish_job(request_body: PolishJobCreate) -> JobView:
        if polish_service is None:
            raise _http_error(503, "Polish Jobs are unavailable for this app instance.")
        try:
            return job_view(polish_service.create(request_body))
        except FeatureJobError as exc:
            raise _feature_http_error(exc) from exc
        except JobConflictError as exc:
            raise _http_error(409, str(exc)) from exc

    @app.post("/api/translation/jobs", response_model=JobView, status_code=202)
    def create_translation_job(request_body: TranslationJobCreate) -> JobView:
        if translation_service is None:
            raise _http_error(503, "Translation Jobs are unavailable for this app instance.")
        try:
            return job_view(translation_service.create(request_body))
        except FeatureJobError as exc:
            raise _feature_http_error(exc) from exc
        except JobConflictError as exc:
            raise _http_error(409, str(exc)) from exc

    def _feature_job_list(kind: str, limit: int, **filters) -> list[JobView]:
        try:
            return [JobView.from_record(item) for item in job_store.list(kind=kind, limit=limit, **filters)]
        except JobStateError as exc:
            raise _http_error(422, str(exc)) from exc

    def _feature_job(kind: str, job_id: str) -> JobView:
        try:
            record = job_store.get(job_id)
        except JobNotFoundError as exc:
            raise _http_error(404, str(exc)) from exc
        if record.kind != kind:
            raise _http_error(404, "Unknown feature Job.")
        return JobView.from_record(record)

    def _record_feature_action(kind: str, job_id: str, request_body: FeatureActionRequest) -> JobView:
        if job_store is None:
            raise _http_error(503, "Job storage is unavailable for this app instance.")
        try:
            record = job_store.get(job_id)
            if record.kind != kind:
                raise JobNotFoundError("Unknown feature Job.")
            updated = apply_feature_review(job_store, job_runner, record, request_body)
            return JobView.from_record(updated)
        except JobNotFoundError as exc:
            raise _http_error(404, str(exc)) from exc
        except (JobConflictError, JobStateError) as exc:
            raise _http_error(409, str(exc)) from exc

    def _feature_artifacts(kind: str, job_id: str) -> list[dict[str, object]]:
        record = job_store.get(job_id)
        if record.kind != kind:
            raise JobNotFoundError("Unknown feature Job.")
        return [item for item in list_job_artifacts(job_store.job_directory(job_id)) if item.get("artifact_id") in record.output_artifact_ids]

    def _artifact_json(kind: str, job_id: str, role: str) -> dict[str, object]:
        record = job_store.get(job_id)
        if record.kind != kind:
            raise JobNotFoundError("Unknown feature Job.")
        return {**read_feature_result(job_store, record, role), "review": read_review(job_store, record)}

    def _make_feature_list_route(kind: str):
        def route(
            limit: int = Query(default=100, ge=1, le=1_000), offset: int = Query(default=0, ge=0),
            project_id: str | None = Query(default=None, max_length=256),
            run_id: str | None = Query(default=None, max_length=128),
            status: list[str] | None = Query(default=None),
        ) -> list[JobView]:
            return _feature_job_list(kind, limit, offset=offset, project_id=project_id, run_id=run_id, statuses=status)
        return route

    def _make_feature_get_route(kind: str):
        def route(job_id: str) -> JobView:
            return _feature_job(kind, job_id)
        return route

    def _make_feature_action_route(kind: str):
        def route(job_id: str, request_body: FeatureActionRequest) -> JobView:
            return _record_feature_action(kind, job_id, request_body)
        return route

    def _make_feature_artifact_route(kind: str):
        def route(job_id: str) -> list[dict[str, object]]:
            try:
                return _feature_artifacts(kind, job_id)
            except JobNotFoundError as exc:
                raise _http_error(404, str(exc)) from exc
        return route

    def _make_feature_event_route(kind: str):
        async def route(job_id: str, request: Request, after: int = Query(default=0, ge=0), follow: bool = True):
            _feature_job(kind, job_id)
            return await job_events(job_id, request, after=after, follow=follow)
        return route

    def _make_feature_download_route(kind: str):
        def route(job_id: str, artifact_id: str):
            _feature_job(kind, job_id)
            return read_job_artifact(job_id, artifact_id)
        return route

    for feature_kind, feature_prefix in (("figure", "figure"), ("polish", "polish"), ("translation", "translation")):
        app.add_api_route(
            f"/api/{feature_prefix}/jobs",
            _make_feature_list_route(feature_kind),
            methods=["GET"],
            response_model=list[JobView],
        )
        app.add_api_route(
            f"/api/{feature_prefix}/jobs/{{job_id}}",
            _make_feature_get_route(feature_kind),
            methods=["GET"],
            response_model=JobView,
        )
        app.add_api_route(
            f"/api/{feature_prefix}/jobs/{{job_id}}/actions",
            _make_feature_action_route(feature_kind),
            methods=["POST"],
            response_model=JobView,
            status_code=202,
        )
        app.add_api_route(
            f"/api/{feature_prefix}/jobs/{{job_id}}/artifacts",
            _make_feature_artifact_route(feature_kind),
            methods=["GET"],
        )
        app.add_api_route(f"/api/{feature_prefix}/jobs/{{job_id}}/events", _make_feature_event_route(feature_kind), methods=["GET"])
        app.add_api_route(f"/api/{feature_prefix}/jobs/{{job_id}}/artifacts/{{artifact_id}}", _make_feature_download_route(feature_kind), methods=["GET"])

    @app.get("/api/polish/jobs/{job_id}/revisions")
    def polish_revisions(job_id: str) -> dict[str, object]:
        try:
            return _artifact_json("polish", job_id, "polish_revision_set")
        except JobNotFoundError as exc:
            raise _http_error(404, str(exc)) from exc
        except JobStateError as exc:
            raise _http_error(409, str(exc)) from exc

    @app.get("/api/translation/jobs/{job_id}/pages/{page_number}")
    def translation_page(job_id: str, page_number: int) -> dict[str, object]:
        try:
            payload = _artifact_json("translation", job_id, "translation_pages")
            pages = payload.get("pages")
            if not isinstance(pages, list):
                raise JobStateError("Translation artifact has no pages.")
            for page in pages:
                if isinstance(page, dict) and int(page.get("page_number", -1)) == page_number:
                    decision = payload.get("review", {}).get("pages", {}).get(str(page_number), "pending")
                    return {**page, "review_status": decision, "review_version": payload.get("review", {}).get("version", 0)}
            raise JobNotFoundError("Unknown translation page.")
        except JobNotFoundError as exc:
            raise _http_error(404, str(exc)) from exc
        except (JobStateError, ValueError) as exc:
            raise _http_error(409, str(exc)) from exc

    @app.get("/api/translation/jobs/{job_id}/pages")
    def translation_pages(job_id: str) -> dict[str, object]:
        try:
            payload = _artifact_json("translation", job_id, "translation_pages")
            review = payload.get("review", {})
            return {"job_id": job_id, "review_version": review.get("version", 0), "pages": [
                {"page_number": page["page_number"], "block_count": len(page["source_blocks"]),
                 "parser_backend": page["parser_backend"], "ocr_used": page["ocr_used"],
                 "review_status": review.get("pages", {}).get(str(page["page_number"]), "pending"),
                 "unresolved_count": len(page.get("unresolved_items", [])),
                 "parser_diagnostics": page.get("parser_diagnostics", [])}
                for page in payload["pages"]
            ]}
        except JobNotFoundError as exc:
            raise _http_error(404, str(exc)) from exc
        except JobStateError as exc:
            raise _http_error(409, str(exc)) from exc

    @app.post("/api/polish/jobs/{job_id}/export")
    def export_polish(job_id: str, request_body: FeatureExportRequest) -> Response:
        return _export_feature_job(job_store, file_service, "polish", job_id, request_body)

    @app.post("/api/translation/jobs/{job_id}/export")
    def export_translation(job_id: str, request_body: FeatureExportRequest) -> Response:
        return _export_feature_job(job_store, file_service, "translation", job_id, request_body)

    @app.get("/api/disciplines")
    def disciplines(
        query: str = Query(default="", max_length=256),
        include_excluded: bool = False,
    ) -> dict[str, object]:
        normalized = query.casefold().strip()
        entries = list_discipline_catalog(include_excluded=include_excluded)
        if normalized:
            entries = [
                entry
                for entry in entries
                if normalized in " ".join(str(entry.get(key, "")) for key in ("id", "label", "domain", "template_family")).casefold()
            ]
        return {"disciplines": entries}

    @app.post("/api/disciplines/resolve")
    def resolve_disciplines(request_body: ResolveDisciplineRequest) -> dict[str, object]:
        if request_body.method == "model":
            preferences = preferences_service.get().preferences
            if preferences.privacy_mode == "local-only" or preferences.network_access == "never":
                raise _http_error(403, "当前工作区偏好禁止远程识别，请手动选择学科或修改隐私与网络设置。")
            try:
                return recognize_disciplines(request_body.topic, config=load_config(str(config_path)))
            except RequiredJsonLLMError as exc:
                raise _http_error(
                    503, "学科识别服务暂时不可用，请重试或手动选择学科。",
                    code="DISCIPLINE_MODEL_UNAVAILABLE",
                ) from exc
            except ValueError as exc:
                raise _http_error(
                    502, "学科识别结果未通过校验，请重试或手动选择学科。",
                    code="INVALID_DISCIPLINE_SUGGESTION", retryable=True,
                ) from exc
        resolution = resolve_discipline_taxonomy(request_body.topic)
        return {**resolution, "suggested_catalog_ids": _catalog_suggestions(resolution)}

    @app.get("/api/runs", response_model=list[RunView])
    def list_runs(query: str = Query(default="", max_length=512)) -> list[RunView]:
        return service.list_runs(query=query)

    @app.post("/api/runs", response_model=RunView, status_code=202)
    def create_run(request_body: CreateRunRequest) -> RunView:
        try:
            return service.create_run(request_body)
        except (ScienceRunInputError, ScienceRunConflictError) as exc:
            raise _http_error(422, str(exc)) from exc

    @app.get("/api/runs/{run_id}", response_model=RunView)
    def get_run(run_id: str) -> RunView:
        try:
            return service.get_run(run_id)
        except RunNotFoundError as exc:
            raise _http_error(404, str(exc)) from exc

    @app.post("/api/runs/{run_id}/materials", response_model=MaterialUploadResponse)
    async def upload_materials(
        run_id: str,
        files: list[UploadFile] = File(...),
        metadata: str = Form(...),
    ) -> MaterialUploadResponse:
        try:
            paths = service.paths_for(run_id)
            stored = await store_materials(paths=paths, uploads=files, metadata=parse_material_metadata(metadata), file_service=file_service)
            return MaterialUploadResponse(materials=stored, run=service.get_run(run_id))
        except RunNotFoundError as exc:
            raise _http_error(404, str(exc)) from exc
        except (MaterialUploadError, FileServiceError) as exc:
            raise _http_error(422, str(exc)) from exc
        except ScienceRunLockError as exc:
            raise _http_error(409, "This research run is busy. Retry the upload shortly.") from exc

    @app.get("/api/runs/{run_id}/materials/{material_id}")
    def read_material_file(run_id: str, material_id: str) -> FileResponse:
        try:
            path, original_name = read_material(service.paths_for(run_id), material_id)
            return FileResponse(path, filename=original_name, content_disposition_type="inline")
        except RunNotFoundError as exc:
            raise _http_error(404, str(exc)) from exc
        except MaterialUploadError as exc:
            raise _http_error(404, str(exc)) from exc

    @app.delete("/api/runs/{run_id}/materials/{material_id}", response_model=RunView)
    def delete_material_file(run_id: str, material_id: str) -> RunView:
        try:
            paths = service.paths_for(run_id)
            remove_material(paths, material_id, file_service=file_service)
            return service.get_run(run_id)
        except RunNotFoundError as exc:
            raise _http_error(404, str(exc)) from exc
        except MaterialUploadError as exc:
            status = 409 if "immutable" in str(exc).casefold() else 422
            raise _http_error(status, str(exc)) from exc
        except ScienceRunLockError as exc:
            raise _http_error(409, "This research run is busy. Retry the material change shortly.") from exc

    @app.post("/api/runs/{run_id}/actions", response_model=RunView, status_code=202)
    def run_action(run_id: str, request_body: RunActionRequest) -> RunView:
        try:
            return service.run_action(run_id=run_id, action=request_body)
        except RunNotFoundError as exc:
            raise _http_error(404, str(exc)) from exc
        except (RunActionConflictError, ScienceRunLockError) as exc:
            raise _http_error(409, str(exc)) from exc
        except RunActionError as exc:
            raise _http_error(422, str(exc)) from exc

    @app.post("/api/runs/{run_id}/quantitative/parameter-search", response_model=ParameterSearchView, status_code=202)
    def start_parameter_search(run_id: str, request_body: ParameterSearchRequest) -> ParameterSearchView:
        try:
            return ParameterSearchView.model_validate(
                service.start_parameter_search(
                    run_id=run_id,
                    idea_id=request_body.idea_id,
                    version=request_body.version,
                    parameter_id=request_body.parameter_id,
                    query=request_body.query,
                    providers=tuple(request_body.providers),
                    limit=request_body.limit,
                )
            )
        except RunNotFoundError as exc:
            raise _http_error(404, str(exc)) from exc
        except (RunActionConflictError, ScienceRunLockError) as exc:
            raise _http_error(409, str(exc)) from exc
        except RunActionError as exc:
            raise _http_error(422, str(exc)) from exc

    @app.get("/api/runs/{run_id}/quantitative/parameter-search/{idea_id}/{version}/{job_id}")
    def get_parameter_search(run_id: str, idea_id: str, version: int, job_id: str) -> dict[str, object]:
        try:
            return service.get_parameter_search(run_id=run_id, idea_id=idea_id, version=version, job_id=job_id)
        except RunNotFoundError as exc:
            raise _http_error(404, str(exc)) from exc
        except RunActionError as exc:
            raise _http_error(404, str(exc)) from exc

    @app.post("/api/runs/{run_id}/quantitative/parameter-search/{job_id}/select")
    def select_parameter_search_sources(run_id: str, job_id: str, request_body: ParameterSearchSelectionRequest) -> dict[str, object]:
        try:
            return service.select_parameter_search_sources(
                run_id=run_id,
                idea_id=request_body.idea_id,
                version=request_body.version,
                job_id=job_id,
                paper_ids=request_body.paper_ids,
            )
        except RunNotFoundError as exc:
            raise _http_error(404, str(exc)) from exc
        except (RunActionConflictError, ScienceRunLockError) as exc:
            raise _http_error(409, str(exc)) from exc
        except RunActionError as exc:
            raise _http_error(422, str(exc)) from exc

    @app.get("/api/runs/{run_id}/events")
    async def events(
        run_id: str,
        request: Request,
        after: int = Query(default=0, ge=0),
        follow: bool = True,
    ) -> EventSourceResponse:
        try:
            paths = service.paths_for(run_id)
        except RunNotFoundError as exc:
            raise _http_error(404, str(exc)) from exc
        last_event_id = request.headers.get("last-event-id")
        if last_event_id and last_event_id.isdigit():
            after = max(after, int(last_event_id))

        async def event_generator() -> AsyncIterator[dict[str, str]]:
            async for event in stream_events(request, events_path=paths.events, after=after, follow=follow):
                yield event

        return EventSourceResponse(event_generator())

    @app.get("/api/runs/{run_id}/logs", response_model=list[RunLogView])
    def list_logs(run_id: str) -> list[RunLogView]:
        try:
            return list_run_logs(service.paths_for(run_id))
        except RunNotFoundError as exc:
            raise _http_error(404, str(exc)) from exc

    @app.get("/api/runs/{run_id}/logs/{log_id:path}", response_model=RunLogChunkView)
    def read_log(
        run_id: str,
        log_id: str,
        offset: int = Query(default=0, ge=0),
        limit: int = Query(default=65_536, ge=4_096, le=MAX_LOG_CHUNK_BYTES),
    ) -> RunLogChunkView:
        try:
            return read_run_log(service.paths_for(run_id), log_id=log_id, offset=offset, limit=limit)
        except RunNotFoundError as exc:
            raise _http_error(404, str(exc)) from exc
        except RunLogError as exc:
            raise _http_error(404, str(exc)) from exc

    @app.get("/api/representative", response_model=list[RepresentativeProjectView])
    def representative_projects() -> list[RepresentativeProjectView]:
        return list_representative_projects(resolved_representative_root)

    @app.get("/api/representative/{project_id}/files/{file_id:path}")
    def representative_asset(project_id: str, file_id: str, download: bool = False) -> FileResponse:
        path = representative_file(resolved_representative_root, project_id, file_id)
        if path is None:
            raise _http_error(404, "Unknown representative research asset.")
        return FileResponse(path, filename=path.name, content_disposition_type="attachment" if download else "inline")

    @app.get("/api/runs/{run_id}/artifacts/{artifact_id:path}")
    def read_artifact(run_id: str, artifact_id: str) -> FileResponse:
        try:
            paths = service.paths_for(run_id)
            _metadata, state = load_science_run(paths)
        except RunNotFoundError as exc:
            raise _http_error(404, str(exc)) from exc
        indexed = artifact_index(paths, state)
        path = indexed.get(artifact_id)
        if path is None:
            resolved_job_artifact = service.resolve_run_job_artifact(run_id, artifact_id)
            if resolved_job_artifact is not None:
                path, metadata = resolved_job_artifact
                return FileResponse(
                    path,
                    filename=str(metadata.get("label") or path.name),
                    media_type=str(metadata.get("media_type") or "application/octet-stream"),
                    content_disposition_type="inline",
                )
        if path is None:
            raise _http_error(404, "Unknown research artifact.")
        return FileResponse(path, filename=path.name, content_disposition_type="inline")

    if serve_frontend:
        frontend_root = REPO_ROOT / "WebApp-V2" / "dist"
        if frontend_root.is_dir() and (frontend_root / "index.html").is_file():
            app.mount("/", FrontendFiles(directory=frontend_root, html=True), name="webapp")
        else:
            @app.get("/", include_in_schema=False)
            def frontend_build_required() -> HTMLResponse:
                return HTMLResponse(
                    "<h1>Web client has not been built</h1>"
                    "<p>Run <code>npm install</code> and <code>npm run build</code> in WebApp-V2.</p>",
                    status_code=503,
                )
    return app


app = create_app()


def main() -> None:
    import uvicorn

    uvicorn.run("src.webapp.api:app", host="127.0.0.1", port=8010, reload=False)


if __name__ == "__main__":
    main()
