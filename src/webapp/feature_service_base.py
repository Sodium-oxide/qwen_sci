"""Shared job creation helpers for figure, polish, and translation services."""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Mapping, Sequence
from pathlib import Path

from src.config import load_config

from .file_service import FileService, FileServiceError
from .job_artifacts import prepare_job_manifest, read_job_manifest
from .jobs import JobExecutionResult, JobRegistry, JobRunner, JobStore
from .jobs.models import JobRecord
from .jobs.runner import JobContext
from .jobs.store import canonical_hash
from .prompts import PromptRegistry, PromptSpec
from .prompts.registry import resolve_text_model


class FeatureJobError(ValueError):
    """Raised when a feature Job cannot be created from supplied inputs."""

    code = "FEATURE_INPUT_INVALID"
    retryable = False

    def __init__(self, message: str, *, code: str | None = None, retryable: bool | None = None) -> None:
        super().__init__(message)
        if code is not None:
            self.code = code
        if retryable is not None:
            self.retryable = retryable


class FeatureJobService:
    """Create immutable input manifests and register trusted worker handlers."""

    kind: str

    def __init__(
        self,
        *,
        store: JobStore,
        runner: JobRunner,
        registry: JobRegistry,
        file_service: FileService,
        prompt_registry: PromptRegistry,
        config_path: str | Path,
    ) -> None:
        self.store = store
        self.runner = runner
        self.registry = registry
        self.file_service = file_service
        self.prompt_registry = prompt_registry
        self.config_path = Path(config_path).expanduser().resolve()
        self.config = load_config(str(self.config_path))
        self.preferences_service = None
        self.run_service = None

    def prepare_request(self, request):
        if not bool(self.config.get(self.kind, {}).get("enabled", True)):
            raise FeatureJobError("This feature is disabled by the server.", code="CAPABILITY_UNAVAILABLE")
        if getattr(request, "run_id", None):
            from .run_service import RunNotFoundError

            if self.run_service is None:
                raise FeatureJobError("Research run association is unavailable.")
            try:
                run = self.run_service.get_run(request.run_id)
            except RunNotFoundError as exc:
                raise FeatureJobError("The associated research run is unavailable.") from exc
            if request.project_id and run.project_id != request.project_id:
                raise FeatureJobError("The associated run belongs to a different project.")
            if not request.project_id and run.project_id:
                request = request.model_copy(update={"project_id": run.project_id})
        if self.preferences_service is None:
            return request, None
        resolved, snapshot = self.preferences_service.resolve_request(request)
        if snapshot["values"]["privacy_mode"] == "local-only" and (
            self.kind in {"polish", "translation"} or getattr(resolved, "use_ai_schematic", False)
        ):
            raise FeatureJobError("This feature requires a remote model; workspace preferences allow local processing only.")
        return resolved, snapshot

    def register_handler(self) -> None:
        self.registry.register(self.kind, self._run_registered)

    def _run_registered(self, context: JobContext) -> JobExecutionResult:
        """Recheck deployment capability after a queued Job is claimed."""

        config = load_config(str(self.config_path))
        if not bool(config.get(self.kind, {}).get("enabled", True)):
            raise FeatureJobError(
                "This feature is disabled by the server.",
                code="CAPABILITY_UNAVAILABLE",
            )
        return self.run_job(context)

    def resolve_prompt(
        self, profile: str, *, axes: Mapping[str, str] | None = None,
        prompt_version: str | None = None, prompt_hash: str | None = None,
    ) -> PromptSpec:
        try:
            return self.prompt_registry.resolve(
                job_kind=self.kind, profile=profile, axes=axes,
                prompt_version=prompt_version, prompt_hash=prompt_hash,
            )
        except ValueError as exc:
            raise FeatureJobError(str(exc), code="PROMPT_UNAVAILABLE") from exc

    def resolve_model(self, spec: PromptSpec, selected_model: str | None) -> tuple[str, str]:
        try:
            model = resolve_text_model(self.config, spec, model_name=selected_model, provider_name="qwen")
        except ValueError as exc:
            raise FeatureJobError(str(exc), code="CAPABILITY_UNAVAILABLE") from exc
        return model.name, model.provider

    def validate_files(self, file_ids: Sequence[str], *, project_id: str | None = None) -> list[dict[str, object]]:
        records: list[dict[str, object]] = []
        for file_id in file_ids:
            try:
                view = self.file_service.get(file_id)
            except FileServiceError as exc:
                raise FeatureJobError(str(exc)) from exc
            if project_id and view.project_id not in {None, project_id}:
                raise FeatureJobError("An input file belongs to a different project.")
            if view.material_scope == "do_not_send" and self.kind in {"polish", "translation"}:
                raise FeatureJobError("This source material is restricted to local processing.")
            records.append(
                {
                    "file_id": view.file_id,
                    "original_name": view.original_name,
                    "mime_type": view.mime_type,
                    "detected_type": view.detected_type,
                    "size_bytes": view.size_bytes,
                    "sha256": view.sha256,
                    "material_scope": view.material_scope,
                }
            )
        return records

    def create_job(
        self,
        *,
        request_payload: Mapping[str, object],
        input_manifest: Mapping[str, object],
        prompt: PromptSpec,
        model_name: str,
        provider_name: str,
        project_id: str | None = None,
        run_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> JobRecord:
        with self.file_service.locked_files():
            return self._create_job(
                request_payload=request_payload, input_manifest=input_manifest, prompt=prompt,
                model_name=model_name, provider_name=provider_name, project_id=project_id,
                run_id=run_id, idempotency_key=idempotency_key,
            )

    def _create_job(
        self, *, request_payload: Mapping[str, object], input_manifest: Mapping[str, object],
        prompt: PromptSpec, model_name: str, provider_name: str, project_id: str | None,
        run_id: str | None, idempotency_key: str | None,
    ) -> JobRecord:
        self._verify_input_files(input_manifest)
        request_hash = canonical_hash({"kind": self.kind, "request": dict(request_payload)})
        scope = project_id or run_id or "workspace"
        if idempotency_key:
            existing = self.store.find_by_idempotency_key(scope, idempotency_key)
            if existing is not None:
                if existing.request_hash != request_hash:
                    from .jobs.errors import JobConflictError

                    raise JobConflictError("The idempotency key is already bound to a different request.")
                return existing
        job_id = f"job-{uuid.uuid4().hex}"
        generation = {"temperature": 0.2, "max_output_tokens": 16384, "response_format": "json_object"}
        if input_manifest.get("use_ai_schematic"):
            generation = {"size": input_manifest.get("image_size"), "n": 1}
        prompt_snapshot = prompt.snapshot()
        prompt_snapshot["output_schema_version"] = prompt_snapshot["output_schema"].get("properties", {}).get("schema_version", {}).get("const", prompt.prompt_version)
        prompt_snapshot["effective_prompt_hash"] = canonical_hash({
            "prompt_hash": prompt.prompt_hash, "rules": input_manifest.get("prompt_rules"),
            "generation": generation, "model": model_name, "provider": provider_name,
        })
        directory = self.store.job_directory(job_id)
        directory.mkdir(parents=True, exist_ok=False)
        try:
            manifest_path = prepare_job_manifest(directory, {
                "schema_version": "web_job_input_v2",
                "job_id": job_id,
                "kind": self.kind,
                "request": dict(request_payload),
                "input": dict(input_manifest),
                "prompt": prompt_snapshot,
                "model": {"name": model_name, "provider": provider_name, "generation": generation},
            })
        except BaseException:
            directory.rmdir()
            raise
        try:
            record = self.store.create(
                job_id=job_id,
                kind=self.kind,
                scope_key=scope,
                project_id=project_id,
                run_id=run_id,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
                input_manifest_id=f"manifest-{job_id}",
                input_manifest_sha256=hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
                prompt_id=prompt.prompt_id,
                prompt_version=prompt.prompt_version,
                prompt_hash=prompt.prompt_hash,
                model_name=model_name,
                provider_name=provider_name,
                max_attempts=int(self.config.get("web", {}).get("jobs", {}).get("max_retries", 2)) + 1,
                input_file_ids=[str(raw["file_id"]) for raw in input_manifest.get("files", [])],
            )
        except BaseException:
            manifest_path.unlink(missing_ok=True)
            directory.rmdir()
            raise
        if record.job_id != job_id:
            manifest_path.unlink(missing_ok=True)
            directory.rmdir()
            self._attach_input_references(input_manifest, record.job_id)
            return record
        self._attach_input_references(input_manifest, record.job_id)
        self.runner.submit(record.job_id)
        return record

    def _verify_input_files(self, input_data: Mapping[str, object]) -> None:
        for raw in input_data.get("files", []):
            if not isinstance(raw, Mapping):
                raise FeatureJobError("The frozen file list is invalid.")
            try:
                view = self.file_service.get(str(raw.get("file_id") or ""))
            except FileServiceError as exc:
                raise FeatureJobError("A frozen input file is unavailable or has changed.") from exc
            if view.sha256 != raw.get("sha256") or view.size_bytes != raw.get("size_bytes"):
                raise FeatureJobError("An input file no longer matches the frozen Job snapshot.")

    def read_manifest(self, context: JobContext) -> dict[str, object]:
        context.check_cancelled()
        manifest = read_job_manifest(context)
        input_data = manifest.get("input")
        if not isinstance(input_data, dict):
            raise FeatureJobError("The frozen Job input must be an object.")
        self._verify_input_files(input_data)
        return manifest

    def _attach_input_references(self, input_manifest: Mapping[str, object], job_id: str) -> None:
        files = input_manifest.get("files")
        if not isinstance(files, list):
            return
        for raw in files:
            if not isinstance(raw, Mapping):
                continue
            file_id = str(raw.get("file_id") or "").strip()
            if file_id:
                try:
                    self.file_service.attach_reference(file_id, job_id=job_id)
                except FileServiceError as exc:
                    raise FeatureJobError(f"Unable to freeze input file reference: {exc}") from exc

    def run_job(self, context: JobContext) -> JobExecutionResult:
        raise NotImplementedError

