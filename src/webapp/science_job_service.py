"""Durable descriptors adapting the existing science state machine to Jobs."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping

from filelock import FileLock
from pydantic import TypeAdapter

from src.pipeline.science_run import load_science_run
from src.config import load_config

from .feature_service_base import FeatureJobService
from .jobs import JobConflictError, JobExecutionResult, JobContext
from .run_service import RunActionConflictError, RunService, WorkflowSupervisor
from .schemas import RunActionRequest
from .prompts.registry import resolve_text_model


class ScienceJobService(FeatureJobService):
    kind = "science"

    def bind(self, service: RunService) -> None:
        self.service = service

    def enqueue(self, *, run_id: str, descriptor: dict[str, object]) -> None:
        paths = self.service.paths_for(run_id)
        with FileLock(str(paths.run_dir / ".job-submit.guard"), timeout=10):
            metadata, _state = load_science_run(paths)
            options = metadata["immutable_inputs"]["options"]
            research = options.get("research", {})
            snapshot = research.get("prompt_snapshot", {})
            prompt = self.resolve_prompt(
                str(research.get("prompt_profile") or "research-default"),
                prompt_version=snapshot.get("prompt_version"), prompt_hash=snapshot.get("prompt_hash"),
            )
            resolved = resolve_text_model(load_config(str(paths.config_snapshot)), prompt, model_name=research.get("model_name"))
            model, provider = resolved.name, resolved.provider
            input_data = {
                "run_id": run_id,
                "descriptor": descriptor,
                "metadata_sha256": hashlib.sha256(paths.run_metadata.read_bytes()).hexdigest(),
                "preferences_snapshot": metadata["immutable_inputs"].get("web", {}).get("preferences_snapshot"),
            }
            try:
                self.create_job(
                    request_payload={"run_id": run_id, "descriptor": descriptor},
                    input_manifest=input_data, prompt=prompt, model_name=model,
                    provider_name=provider, run_id=run_id,
                    project_id=research.get("project_id"),
                )
            except JobConflictError as exc:
                raise RunActionConflictError("This research run is already executing.") from exc

    def run_job(self, context: JobContext) -> JobExecutionResult:
        manifest = self.read_manifest(context)
        data = manifest["input"]
        run_id = str(data.get("run_id") or "")
        paths = self.service.paths_for(run_id)
        if hashlib.sha256(paths.run_metadata.read_bytes()).hexdigest() != data.get("metadata_sha256"):
            raise ValueError("Science inputs changed after the durable task was queued.")
        metadata, _state = load_science_run(paths)
        descriptor = data.get("descriptor")
        if not isinstance(descriptor, Mapping):
            raise ValueError("Science task descriptor is missing.")
        context.checkpoint(progress=5, current_step="resuming_science_state")
        if descriptor.get("type") == "workflow":
            from . import run_service

            outcome = run_service.run_science_workflow(
                paths=paths, metadata=metadata, until=str(descriptor["until"]), quiet=True,
                execution_checkpoint=context.check_cancelled,
            )
            if outcome is not None and outcome.state.get("status") == "FAILED":
                raise RuntimeError("Science workflow failed; inspect the run stage status.")
        elif descriptor.get("type") == "quantitative_action":
            action = TypeAdapter(RunActionRequest).validate_python(descriptor.get("action"))
            self.service._perform_quantitative_action(paths=paths, action=action)
            from src.pipeline.quantitative_orchestrator import refresh_quantitative_state

            refresh_quantitative_state(paths.run_dir)
        elif descriptor.get("type") == "parameter_search":
            self.service.parameter_search.execute_descriptor(
                run_dir=paths.run_dir, descriptor=dict(descriptor), checkpoint=context.check_cancelled,
            )
        else:
            raise ValueError("Unsupported durable science task descriptor.")
        context.check_cancelled()
        return JobExecutionResult(current_step="science_action_completed")


class DurableWorkflowSupervisor(WorkflowSupervisor):
    def __init__(self, science: ScienceJobService) -> None:
        super().__init__()
        self.science = science

    def submit(self, *, paths, metadata, until: str) -> None:
        self.science.enqueue(run_id=str(metadata["science_run_id"]), descriptor={"type": "workflow", "until": until})

    def submit_action(self, *, run_id: str, action: RunActionRequest) -> None:
        self.science.enqueue(run_id=run_id, descriptor={"type": "quantitative_action", "action": action.model_dump(mode="json")})

    def submit_search(self, *, run_id: str, descriptor: dict[str, object]) -> None:
        self.science.enqueue(run_id=run_id, descriptor={"type": "parameter_search", **descriptor})

    def is_active(self, run_id: str) -> bool:
        return super().is_active(run_id) or bool(self.science.store.list(
            run_id=run_id, kind="science", statuses=("QUEUED", "RUNNING", "CANCEL_REQUESTED"), limit=1,
        ))

    def cancel_jobs(self, run_id: str) -> None:
        for job in self.science.store.list(run_id=run_id, kind="science", statuses=("QUEUED", "RUNNING")):
            self.science.runner.request_cancel(job.job_id)

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)
