"""FastAPI control plane and same-origin host for the V2 research workspace."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from sse_starlette.sse import EventSourceResponse

from src.agents.experiment_design_agent.discipline_catalog import list_discipline_catalog
from src.pipeline.discipline_taxonomy import get_discipline_entry, resolve_discipline_taxonomy
from src.pipeline.science_run import (
    ScienceRunConflictError,
    ScienceRunInputError,
    ScienceRunLockError,
    load_science_run,
)

from .artifact_service import artifact_index
from .event_stream import stream_events
from .log_service import MAX_LOG_CHUNK_BYTES, RunLogError, list_run_logs, read_run_log
from .representative_service import default_representative_root, list_representative_projects, representative_file
from .material_service import MaterialUploadError, parse_material_metadata, read_material, remove_material, store_materials
from .run_service import (
    DEFAULT_CONFIG_PATH,
    REPO_ROOT,
    RunActionConflictError,
    RunActionError,
    RunNotFoundError,
    RunService,
)
from .schemas import CreateRunRequest, MaterialUploadResponse, RepresentativeProjectView, ResolveDisciplineRequest, RunActionRequest, RunLogChunkView, RunLogView, RunView


def _http_error(status_code: int, detail: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail=detail)


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
) -> FastAPI:
    resolved_run_root = Path(run_root).expanduser().resolve() if run_root is not None else REPO_ROOT / "workspace" / "science-runs"
    service = RunService(run_root=resolved_run_root, config_path=config_path)
    resolved_representative_root = Path(representative_root).expanduser().resolve() if representative_root is not None else default_representative_root()
    app = FastAPI(title="Qwen-Sci Web Control Plane", version="1.0")
    app.state.run_service = service

    @app.get("/api/health")
    def health() -> dict[str, object]:
        return {"status": "ok", "runs_detected": len(service.list_runs())}

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
            stored = await store_materials(paths=paths, uploads=files, metadata=parse_material_metadata(metadata))
            return MaterialUploadResponse(materials=stored, run=service.get_run(run_id))
        except RunNotFoundError as exc:
            raise _http_error(404, str(exc)) from exc
        except MaterialUploadError as exc:
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
            remove_material(paths, material_id)
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
            raise _http_error(404, "Unknown research artifact.")
        return FileResponse(path, filename=path.name, content_disposition_type="inline")

    if serve_frontend:
        frontend_root = REPO_ROOT / "WebApp-V2" / "dist"
        if frontend_root.is_dir() and (frontend_root / "index.html").is_file():
            app.mount("/", StaticFiles(directory=frontend_root, html=True), name="webapp")
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
