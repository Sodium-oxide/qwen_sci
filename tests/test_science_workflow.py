from __future__ import annotations

import json
import os
import socket
from pathlib import Path
from typing import Any

import pytest
from omegaconf import OmegaConf

from src import cli
from src.pipeline import science_run, science_stages, science_workflow
from src.pipeline.science_manifests import (
    ScienceManifestError,
    verify_author_manifest,
    verify_experiment_design_manifest,
    verify_idea_manifest,
    verify_survey_manifest,
    write_author_manifest,
    write_experiment_design_manifest,
    write_idea_manifest,
)
from src.pipeline.science_stages import (
    AuthorStageRequest,
    ExperimentDesignStageRequest,
    IdeaStageRequest,
    ScienceStageError,
    ScienceStageResult,
    ScienceStageServices,
    SurveyStageRequest,
)
from src.pipeline.science_workflow import ScienceWorkflowError, run_science_workflow
from src.pipeline.survey_handoff_persistence import publish_survey_run_artifacts


def _write_config(tmp_path: Path) -> Path:
    config_path = tmp_path / "science.yaml"
    OmegaConf.save(OmegaConf.create({"research": {"model": "test-model"}}), config_path)
    return config_path


def _new_run(
    tmp_path: Path,
    *,
    survey_appendix: str = "source-link",
    render_required: bool = False,
) -> tuple[science_run.ScienceRunPaths, dict[str, Any]]:
    config_path = _write_config(tmp_path)
    paths, metadata, _state = science_run.initialize_science_run(
        output_root=tmp_path / "science-runs",
        topic="exact handoff topic",
        config_path=config_path,
        immutable_options={
            "discipline_ids": ["25"],
            "survey_appendix": survey_appendix,
            "render_required": render_required,
        },
        run_id="closed-loop",
    )
    return paths, metadata


def _publish_json(request: object, filename: str, payload: dict[str, Any]) -> Path:
    attempt_dir = getattr(request, "attempt_dir")
    attempt_dir.mkdir(parents=True, exist_ok=True)
    path = attempt_dir / filename
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _survey_evidence_plan() -> dict[str, Any]:
    return {
        "schema_version": "survey_sh_evidence_plan_v1",
        "project_id": "science-workflow",
        "project_context_fingerprint": "science-workflow-context",
        "evidence_bounded_writing": True,
        "subhypotheses": [
            {
                "sub_hypothesis_id": "SH1",
                "summary": "A bounded question.",
                "required_slots": ["direct_observation"],
                "covered_slots": [],
                "background_only_slots": [],
                "missing_slots": ["direct_observation"],
                "slot_support": {
                    "direct_observation": {
                        "expected_evidence_role": "DIRECT_OBSERVATION",
                        "evidence_paper_ids": [],
                        "background_paper_ids": [],
                        "qualified_paper_ids": [],
                        "qualified_paper_constraints": {},
                    }
                },
                "relevant_clusters": [],
                "conclusion_admissibility": {"blockers": []},
                "limitations": {"blockers": []},
                "allowed_claim_modes": ["EVIDENCE_GAP_REPORT"],
                "forbidden_paper_ids": [],
                "direct_writing_blocked_paper_ids": [],
            }
        ],
    }


def _publish_completed_survey(request: SurveyStageRequest) -> tuple[Path, dict[str, str]]:
    published = publish_survey_run_artifacts(
        base_dir=request.attempt_dir,
        topic=request.topic,
        survey_run_id=request.survey_run_id,
        final_survey="Survey body",
        survey_payload={"topic": request.topic},
        project_context={
            "input_fingerprint": "science-workflow-context",
            "domain": "Materials Science",
        },
        evidence_plan=_survey_evidence_plan(),
        claim_traceability={"claims": []},
    )
    manifest = Path(published["manifest_path"])
    return manifest, dict(verify_survey_manifest(manifest).identity)


def _fake_services(calls: list[tuple[str, object]]) -> ScienceStageServices:
    def survey(request: SurveyStageRequest) -> ScienceStageResult:
        calls.append(("survey", request))
        manifest, identity = _publish_completed_survey(request)
        return ScienceStageResult(
            stage="survey",
            result_path=manifest,
            outputs={"survey_manifest": str(manifest)},
            identity=identity,
            metadata={"topic": request.topic},
        )

    def idea(request: IdeaStageRequest) -> ScienceStageResult:
        calls.append(("idea", request))
        idea_result = _publish_json(
            request,
            "idea_result.json",
            {
                "schema_version": "idea_result_v5",
                "topic": request.topic,
                "survey_binding": dict(request.survey_identity),
                "primary_direction": "direction-primary",
            },
        )
        identity = {**request.survey_identity, "selected_direction_id": "direction-primary"}
        manifest = write_idea_manifest(
            attempt_dir=request.attempt_dir,
            topic=request.topic,
            idea_result_path=idea_result,
            survey_manifest_path=request.survey_manifest_path,
            identity=identity,
            selected_direction_id="direction-primary",
        )
        return ScienceStageResult(
            stage="idea",
            result_path=manifest,
            outputs={"idea_manifest": str(manifest), "idea_result": str(idea_result)},
            identity=identity,
            metadata={"selected_direction_id": "direction-primary"},
        )

    def exp_design(request: ExperimentDesignStageRequest) -> ScienceStageResult:
        calls.append(("exp_design", request))
        design_json = _publish_json(
            request,
            "experiment_design.json",
            {
                "execution_policy": {"mode": "DESIGN_ONLY"},
                "research_brief": {"discipline_ids": list(request.discipline_ids)},
                "design_id": "design-001",
            },
        )
        design_markdown = _publish_json(request, "experiment_design.md", {"format": "markdown"})
        author_handoff = _publish_json(
            request,
            "experiment_design_author.json",
            {
                "schema_version": "research_plan_author_input_v3",
                "provenance": {
                    "survey_binding": dict(request.idea_identity),
                    "selected_direction_id": request.selected_direction,
                    "idea_result_path": str(request.idea_result_path),
                },
            },
        )
        identity = {**request.idea_identity, "selected_direction_id": request.selected_direction}
        manifest = write_experiment_design_manifest(
            attempt_dir=request.attempt_dir,
            topic=request.topic,
            idea_manifest_path=request.idea_manifest_path,
            idea_result_path=request.idea_result_path,
            artifact_paths={
                "experiment_design_json": design_json,
                "experiment_design_markdown": design_markdown,
                "author_json": author_handoff,
            },
            identity=identity,
            design_id="design-001",
            selected_direction_id=request.selected_direction,
            discipline_ids=list(request.discipline_ids),
        )
        return ScienceStageResult(
            stage="exp_design",
            result_path=manifest,
            outputs={
                "experiment_design_manifest": str(manifest),
                "experiment_design_json": str(design_json),
                "experiment_design_markdown": str(design_markdown),
                "author_json": str(author_handoff),
            },
            identity=identity,
            metadata={"design_id": "design-001", "execution_mode": "DESIGN_ONLY"},
        )

    def author(request: AuthorStageRequest) -> ScienceStageResult:
        calls.append(("author", request))
        preparation = _publish_json(request, "research_plan_preparation.json", {"status": "ready"})
        context = _publish_json(request, "author_context.json", {"status": "ready"})
        document = _publish_json(
            request,
            "research_plan_document.json",
            {
                "source_design_id": "design-001",
                "source_manifest": {
                    "survey_binding": dict(request.survey_identity),
                    "selected_direction_id": "direction-primary",
                },
            },
        )
        evolution = _publish_json(request, "idea_evolution.json", {"status": "ready"})
        render_status = {
            "status": "COMPLETED" if request.render_required else "SKIPPED",
            "required": request.render_required,
            "error": "",
        }
        render_status_path = _publish_json(
            request,
            "author_render_status.json",
            {"schema_version": "science_author_render_status_v1", **render_status},
        )
        render_artifacts: dict[str, Path] = {}
        if request.render_required:
            render_artifacts["render_pdf"] = _publish_json(
                request,
                "rendered_research_plan.pdf",
                {"format": "test-pdf"},
            )
        selected_direction = "direction-primary"
        identity = {**request.survey_identity, "selected_direction_id": selected_direction}
        manifest = write_author_manifest(
            attempt_dir=request.attempt_dir,
            topic=request.topic,
            survey_manifest_path=request.survey_manifest_path,
            idea_manifest_path=request.idea_manifest_path,
            experiment_design_manifest_path=request.experiment_design_manifest_path,
            author_input_path=request.author_input_path,
            artifact_paths={
                "preparation_json": preparation,
                "author_context_json": context,
                "document_json": document,
                "idea_evolution_json": evolution,
                "render_status": render_status_path,
                **render_artifacts,
            },
            identity=identity,
            source_design_id="design-001",
            selected_direction_id=selected_direction,
            rendering=render_status,
        )
        return ScienceStageResult(
            stage="author",
            result_path=manifest,
            outputs={
                "author_manifest": str(manifest),
                "preparation_json": str(preparation),
                "author_context_json": str(context),
                "document_json": str(document),
                "idea_evolution_json": str(evolution),
                "render_status": str(render_status_path),
                **{name: str(path) for name, path in render_artifacts.items()},
            },
            identity=identity,
            metadata={
                "source_design_id": "design-001",
                "selected_direction_id": selected_direction,
                "rendering": render_status,
            },
        )

    return ScienceStageServices(
        survey=survey,
        idea=idea,
        exp_design=exp_design,
        author=author,
    )


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def _refresh_manifest_record(manifest_path: Path, section: str, name: str) -> None:
    manifest = _read_json(manifest_path)
    record = manifest[section][name]
    record["sha256"] = science_run.file_sha256(Path(record["path"]))
    _write_json(manifest_path, manifest)


def test_workflow_runs_four_services_with_exact_paths_and_identity(tmp_path) -> None:
    paths, metadata = _new_run(tmp_path)
    calls: list[tuple[str, object]] = []

    outcome = run_science_workflow(
        paths=paths,
        metadata=metadata,
        services=_fake_services(calls),
    )

    assert [name for name, _request in calls] == ["survey", "idea", "exp_design", "author"]
    survey_request = calls[0][1]
    idea_request = calls[1][1]
    design_request = calls[2][1]
    author_request = calls[3][1]
    assert isinstance(survey_request, SurveyStageRequest)
    assert isinstance(idea_request, IdeaStageRequest)
    assert isinstance(design_request, ExperimentDesignStageRequest)
    assert isinstance(author_request, AuthorStageRequest)
    assert survey_request.attempt_dir == paths.run_dir / "survey" / "attempt-001"
    assert idea_request.survey_manifest_path == survey_request.attempt_dir / "survey_manifest.json"
    assert design_request.idea_manifest_path == idea_request.attempt_dir / "idea_manifest.json"
    assert design_request.idea_result_path == idea_request.attempt_dir / "idea_result.json"
    assert author_request.author_input_path == design_request.attempt_dir / "experiment_design_author.json"
    assert author_request.idea_result_path == design_request.idea_result_path
    assert author_request.idea_manifest_path == design_request.idea_manifest_path
    assert author_request.experiment_design_manifest_path == (
        design_request.attempt_dir / "experiment_design_manifest.json"
    )
    assert author_request.survey_manifest_path == idea_request.survey_manifest_path
    assert idea_request.survey_identity["survey_manifest_path"] == str(idea_request.survey_manifest_path)
    assert design_request.idea_identity["selected_direction_id"] == "direction-primary"
    assert author_request.survey_identity["survey_manifest_path"] == str(author_request.survey_manifest_path)
    assert design_request.selected_direction == "direction-primary"
    assert outcome.state["status"] == "COMPLETED"
    assert all(
        outcome.state["stages"][stage_name]["status"] == "COMPLETED"
        for stage_name in science_run.SCIENCE_STAGE_NAMES
    )
    assert outcome.state["stages"]["idea"]["result_manifest_path"] == str(
        idea_request.attempt_dir / "idea_manifest.json"
    )
    assert outcome.state["stages"]["exp_design"]["result_manifest_path"] == str(
        design_request.attempt_dir / "experiment_design_manifest.json"
    )
    assert outcome.state["stages"]["exp_design"]["outputs"]["author_json"] == str(
        design_request.attempt_dir / "experiment_design_author.json"
    )
    author_identity = outcome.state["stages"]["author"]["result_identity"]
    assert author_identity["survey_run_id"] == idea_request.survey_identity["survey_run_id"]
    assert author_identity["result_sha256"]


def test_idea_manifest_rejects_tampered_survey_artifact(tmp_path) -> None:
    paths, metadata = _new_run(tmp_path)
    calls: list[tuple[str, object]] = []

    run_science_workflow(
        paths=paths,
        metadata=metadata,
        until="idea",
        services=_fake_services(calls),
    )
    idea_manifest = paths.run_dir / "idea" / "attempt-001" / "idea_manifest.json"
    survey_markdown = paths.run_dir / "survey" / "attempt-001" / "survey.md"
    survey_markdown.write_text("tampered survey", encoding="utf-8")

    with pytest.raises(ScienceManifestError, match="Survey manifest is invalid"):
        verify_idea_manifest(idea_manifest)


def test_experiment_design_manifest_rejects_idea_survey_binding_mismatch(tmp_path) -> None:
    paths, metadata = _new_run(tmp_path)
    calls: list[tuple[str, object]] = []

    run_science_workflow(
        paths=paths,
        metadata=metadata,
        until="exp_design",
        services=_fake_services(calls),
    )
    idea_manifest = paths.run_dir / "idea" / "attempt-001" / "idea_manifest.json"
    idea_result = paths.run_dir / "idea" / "attempt-001" / "idea_result.json"
    design_manifest = paths.run_dir / "experiment_design" / "attempt-001" / "experiment_design_manifest.json"
    payload = _read_json(idea_result)
    payload["survey_binding"]["project_id"] = "wrong-project"
    _write_json(idea_result, payload)
    _refresh_manifest_record(idea_manifest, "artifacts", "idea_result")
    _refresh_manifest_record(design_manifest, "inputs", "idea_manifest")

    with pytest.raises(ScienceManifestError, match="differs for project_id"):
        verify_experiment_design_manifest(design_manifest)


def test_experiment_design_manifest_requires_verified_disciplines(tmp_path) -> None:
    paths, metadata = _new_run(tmp_path)
    calls: list[tuple[str, object]] = []

    run_science_workflow(
        paths=paths,
        metadata=metadata,
        until="exp_design",
        services=_fake_services(calls),
    )
    manifest_path = paths.run_dir / "experiment_design" / "attempt-001" / "experiment_design_manifest.json"
    manifest = _read_json(manifest_path)
    manifest["metadata"]["discipline_ids"] = []
    _write_json(manifest_path, manifest)

    with pytest.raises(ScienceManifestError, match="no verified discipline_ids"):
        verify_experiment_design_manifest(manifest_path)


def test_author_manifest_rejects_noncanonical_experiment_design_handoff(tmp_path) -> None:
    paths, metadata = _new_run(tmp_path)
    calls: list[tuple[str, object]] = []

    run_science_workflow(paths=paths, metadata=metadata, services=_fake_services(calls))
    author_manifest = paths.run_dir / "author" / "attempt-001" / "author_manifest.json"
    design_json = paths.run_dir / "experiment_design" / "attempt-001" / "experiment_design.json"
    manifest = _read_json(author_manifest)
    manifest["inputs"]["author_input"] = {
        "path": str(design_json),
        "sha256": science_run.file_sha256(design_json),
    }
    _write_json(author_manifest, manifest)

    with pytest.raises(ScienceManifestError, match="not the ExperimentDesign manifest canonical handoff"):
        verify_author_manifest(author_manifest)


def test_workflow_rejects_upstream_handoff_tampered_before_stage_commit(tmp_path) -> None:
    paths, metadata = _new_run(tmp_path)
    calls: list[tuple[str, object]] = []
    services = _fake_services(calls)
    original_author = services.author

    def tampering_author(request: AuthorStageRequest) -> ScienceStageResult:
        result = original_author(request)
        request.author_input_path.write_text('{"tampered": true}', encoding="utf-8")
        return result

    services = ScienceStageServices(
        survey=services.survey,
        idea=services.idea,
        exp_design=services.exp_design,
        author=tampering_author,
    )

    with pytest.raises(ScienceWorkflowError, match="published manifest validation failed") as error:
        run_science_workflow(paths=paths, metadata=metadata, services=services)

    _loaded_metadata, state = science_run.load_science_run(paths)
    assert error.value.stage == "author"
    assert state["stages"]["exp_design"]["status"] == "COMPLETED"
    assert state["stages"]["author"]["status"] == "FAILED"


def test_workflow_recovers_a_verified_manifest_from_an_interrupted_attempt(tmp_path) -> None:
    paths, metadata = _new_run(tmp_path)
    calls: list[tuple[str, object]] = []
    services = _fake_services(calls)

    run_science_workflow(paths=paths, metadata=metadata, until="survey", services=services)
    with science_run.locked_science_run(paths):
        _loaded_metadata, state = science_run.load_science_run(paths)
        state["status"] = "RUNNING"
        state["stages"]["survey"].update(
            {
                "status": "RUNNING",
                "finished_at": None,
                "result_identity": {},
                "result_manifest_path": None,
                "outputs": {},
                "failure": None,
                "execution_owner": {"pid": 999_999_999, "hostname": socket.gethostname()},
            }
        )
        science_run.save_science_state(paths, state)

    outcome = run_science_workflow(paths=paths, metadata=metadata, until="survey", services=services)

    assert [name for name, _request in calls] == ["survey"]
    assert outcome.state["stages"]["survey"]["status"] == "COMPLETED"
    assert outcome.state["stages"]["survey"]["attempt"] == 1
    events = [json.loads(line) for line in paths.events.read_text(encoding="utf-8").splitlines()]
    assert any(event["event_type"] == "STAGE_RECOVERED" for event in events)


def test_workflow_retries_an_interrupted_attempt_without_overwriting_it(tmp_path) -> None:
    paths, metadata = _new_run(tmp_path)
    calls: list[tuple[str, object]] = []
    interrupted_dir = paths.run_dir / "survey" / "attempt-001"
    interrupted_dir.mkdir(parents=True)
    marker = interrupted_dir / "interrupted.txt"
    marker.write_text("preserve me", encoding="utf-8")
    with science_run.locked_science_run(paths):
        _loaded_metadata, state = science_run.load_science_run(paths)
        science_run.mark_stage_running(state, "survey", input_identity={})
        state["stages"]["survey"]["execution_owner"] = {
            "pid": 999_999_999,
            "hostname": socket.gethostname(),
        }
        science_run.save_science_state(paths, state)

    outcome = run_science_workflow(
        paths=paths,
        metadata=metadata,
        until="survey",
        services=_fake_services(calls),
    )

    assert marker.read_text(encoding="utf-8") == "preserve me"
    assert calls[0][1].attempt_dir == paths.run_dir / "survey" / "attempt-002"
    assert outcome.state["stages"]["survey"]["status"] == "COMPLETED"
    assert outcome.state["stages"]["survey"]["attempt"] == 2


def test_workflow_refuses_to_recover_a_stage_owned_by_a_live_process(tmp_path) -> None:
    paths, metadata = _new_run(tmp_path)
    with science_run.locked_science_run(paths):
        _loaded_metadata, state = science_run.load_science_run(paths)
        science_run.mark_stage_running(state, "survey", input_identity={})
        science_run.save_science_state(paths, state)

    with pytest.raises(ScienceWorkflowError, match="still running under process") as error:
        run_science_workflow(paths=paths, metadata=metadata, until="survey", services=_fake_services([]))

    assert error.value.stage == "survey"
    assert error.value.observed_state_revision is not None


def test_running_survey_is_not_recovered_while_its_child_process_is_alive() -> None:
    stage = {
        "execution_owner": {
            "pid": 999_999_999,
            "hostname": socket.gethostname(),
            "service_pid": os.getpid(),
            "service_process_started_at": science_run.psutil.Process(os.getpid()).create_time(),
        }
    }

    assert science_run.is_stage_execution_active(stage) is True


def test_running_stage_on_another_host_is_not_taken_over() -> None:
    stage = {
        "execution_owner": {
            "pid": 999_999_999,
            "hostname": "other-science-host",
        }
    }

    assert science_run.is_stage_execution_active(stage) is True


def test_survey_service_process_is_recorded_before_the_service_runs(tmp_path) -> None:
    paths, metadata = _new_run(tmp_path)
    calls: list[tuple[str, object]] = []
    services = _fake_services(calls)

    def survey_with_owner(request: SurveyStageRequest) -> ScienceStageResult:
        assert request.on_service_process_started is not None
        request.on_service_process_started(os.getpid())
        _metadata, state = science_run.load_science_run(paths)
        owner = state["stages"]["survey"]["execution_owner"]
        assert owner["service_pid"] == os.getpid()
        assert "service_process_started_at" in owner
        return services.survey(request)

    run_science_workflow(
        paths=paths,
        metadata=metadata,
        until="survey",
        services=ScienceStageServices(
            survey=survey_with_owner,
            idea=services.idea,
            exp_design=services.exp_design,
            author=services.author,
        ),
    )


class _RenderLogger:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    def emit(self, _stage: str, _event: str, **fields: Any) -> None:
        self.events.append(fields)


def test_optional_author_render_failure_keeps_the_structured_author_result() -> None:
    logger = _RenderLogger()

    artifacts, status = science_stages._run_author_render(
        lambda: (_ for _ in ()).throw(RuntimeError("missing renderer")),
        required=False,
        logger=logger,
    )

    assert artifacts == {}
    assert status["status"] == "FAILED_OPTIONAL"
    assert status["required"] is False
    assert logger.events[0]["status"] == "FAILED_OPTIONAL"


def test_required_author_render_failure_uses_the_stable_publication_exit_code() -> None:
    with pytest.raises(ScienceStageError, match="Author rendering failed") as error:
        science_stages._run_author_render(
            lambda: (_ for _ in ()).throw(RuntimeError("missing renderer")),
            required=True,
            logger=_RenderLogger(),
        )

    assert error.value.exit_code == 41


def test_author_manifest_rejects_required_rendering_that_was_skipped(tmp_path) -> None:
    paths, metadata = _new_run(tmp_path)
    run_science_workflow(paths=paths, metadata=metadata, services=_fake_services([]))
    manifest_path = paths.run_dir / "author" / "attempt-001" / "author_manifest.json"
    manifest = _read_json(manifest_path)
    status_path = Path(manifest["artifacts"]["render_status"]["path"])
    status = _read_json(status_path)
    status.update({"status": "SKIPPED", "required": True})
    _write_json(status_path, status)
    _refresh_manifest_record(manifest_path, "artifacts", "render_status")
    manifest = _read_json(manifest_path)
    manifest["metadata"]["rendering"] = {
        "status": "SKIPPED",
        "required": True,
        "error": "",
    }
    _write_json(manifest_path, manifest)

    with pytest.raises(ScienceManifestError, match="Required Author rendering was not completed"):
        verify_author_manifest(manifest_path)


def test_author_manifest_requires_rendering_status_and_completed_pdf(tmp_path) -> None:
    paths, metadata = _new_run(tmp_path, render_required=True)
    run_science_workflow(paths=paths, metadata=metadata, services=_fake_services([]))
    manifest_path = paths.run_dir / "author" / "attempt-001" / "author_manifest.json"
    manifest = _read_json(manifest_path)
    del manifest["metadata"]["rendering"]
    _write_json(manifest_path, manifest)

    with pytest.raises(ScienceManifestError, match="has no rendering status"):
        verify_author_manifest(manifest_path)

    manifest = _read_json(manifest_path)
    manifest["metadata"]["rendering"] = {
        "status": "COMPLETED",
        "required": True,
        "error": "",
    }
    del manifest["artifacts"]["render_pdf"]
    _write_json(manifest_path, manifest)

    with pytest.raises(ScienceManifestError, match="has no render_pdf artifact"):
        verify_author_manifest(manifest_path)


def test_resume_rejects_an_author_manifest_with_a_different_rendering_policy(tmp_path) -> None:
    paths, metadata = _new_run(tmp_path, render_required=True)
    run_science_workflow(paths=paths, metadata=metadata, services=_fake_services([]))
    manifest_path = paths.run_dir / "author" / "attempt-001" / "author_manifest.json"
    manifest = _read_json(manifest_path)
    status_path = Path(manifest["artifacts"]["render_status"]["path"])
    status = _read_json(status_path)
    status.update({"status": "SKIPPED", "required": False})
    _write_json(status_path, status)
    _refresh_manifest_record(manifest_path, "artifacts", "render_status")
    manifest = _read_json(manifest_path)
    manifest["metadata"]["rendering"] = {
        "status": "SKIPPED",
        "required": False,
        "error": "",
    }
    _write_json(manifest_path, manifest)
    with science_run.locked_science_run(paths):
        _metadata, state = science_run.load_science_run(paths)
        state["stages"]["author"]["result_identity"]["result_sha256"] = science_run.file_sha256(
            manifest_path
        )
        science_run.save_science_state(paths, state)

    with pytest.raises(ScienceWorkflowError, match="rendering requirement differs") as error:
        run_science_workflow(paths=paths, metadata=metadata, services=_fake_services([]))

    assert error.value.stage == "author"


def test_workflow_until_exp_design_leaves_author_pending(tmp_path) -> None:
    paths, metadata = _new_run(tmp_path)
    calls: list[tuple[str, object]] = []

    outcome = run_science_workflow(
        paths=paths,
        metadata=metadata,
        until="exp_design",
        services=_fake_services(calls),
    )

    assert [name for name, _request in calls] == ["survey", "idea", "exp_design"]
    assert outcome.state["status"] == "PARTIAL"
    assert outcome.state["stages"]["author"]["status"] == "PENDING"


def test_workflow_passes_the_full_text_appendix_mode_to_author(tmp_path) -> None:
    paths, metadata = _new_run(tmp_path, survey_appendix="full-text")
    calls: list[tuple[str, object]] = []

    run_science_workflow(paths=paths, metadata=metadata, services=_fake_services(calls))

    author_request = calls[-1][1]
    assert isinstance(author_request, AuthorStageRequest)
    assert author_request.survey_appendix == "full-text"


def test_workflow_passes_immutable_required_rendering_to_author(tmp_path) -> None:
    paths, metadata = _new_run(tmp_path, render_required=True)
    calls: list[tuple[str, object]] = []

    run_science_workflow(paths=paths, metadata=metadata, services=_fake_services(calls))

    author_request = calls[-1][1]
    assert isinstance(author_request, AuthorStageRequest)
    assert author_request.render_required is True


def test_author_runtime_paths_normalize_wsl_and_windows_forms_equally() -> None:
    windows_path = science_stages._resolve_author_runtime_path(
        r"C:\Users\researcher\template",
        force_path=True,
    )
    wsl_path = science_stages._resolve_author_runtime_path(
        "/mnt/c/Users/researcher/template",
        force_path=True,
    )

    assert windows_path == wsl_path
    assert science_stages._resolve_author_runtime_path(r"C:\Tools\pdflatex.exe") == (
        science_stages._resolve_author_runtime_path("/mnt/c/Tools/pdflatex.exe")
    )


def test_workflow_rejects_a_completed_stage_path_outside_its_run(tmp_path) -> None:
    paths, metadata = _new_run(tmp_path)
    calls: list[tuple[str, object]] = []
    services = _fake_services(calls)
    run_science_workflow(paths=paths, metadata=metadata, until="survey", services=services)
    external_manifest = tmp_path / "other-run" / "survey_manifest.json"
    external_manifest.parent.mkdir()
    external_manifest.write_text("{}", encoding="utf-8")
    with science_run.locked_science_run(paths):
        _loaded_metadata, state = science_run.load_science_run(paths)
        state["stages"]["survey"]["result_manifest_path"] = str(external_manifest)
        science_run.save_science_state(paths, state)

    with pytest.raises(ScienceWorkflowError, match="escapes its science run stage directory") as error:
        run_science_workflow(paths=paths, metadata=metadata, until="idea", services=services)

    _loaded_metadata, state = science_run.load_science_run(paths)
    assert error.value.stage == "survey"
    assert [name for name, _request in calls] == ["survey"]
    assert state["stages"]["idea"]["status"] == "PENDING"


def test_workflow_rejects_a_replaced_completed_handoff_before_resuming(tmp_path) -> None:
    paths, metadata = _new_run(tmp_path)
    calls: list[tuple[str, object]] = []
    services = _fake_services(calls)
    run_science_workflow(paths=paths, metadata=metadata, until="survey", services=services)
    survey_manifest = paths.run_dir / "survey" / "attempt-001" / "survey_manifest.json"
    survey_manifest.write_text('{"replaced": true}', encoding="utf-8")

    with pytest.raises(ScienceWorkflowError, match="fingerprint no longer matches") as error:
        run_science_workflow(paths=paths, metadata=metadata, until="idea", services=services)

    assert error.value.stage == "survey"
    assert [name for name, _request in calls] == ["survey"]


def test_workflow_records_a_stage_failure_without_running_downstream(tmp_path) -> None:
    paths, metadata = _new_run(tmp_path)
    calls: list[tuple[str, object]] = []
    services = _fake_services(calls)

    def failed_idea(request: IdeaStageRequest) -> ScienceStageResult:
        calls.append(("idea", request))
        raise ScienceStageError("idea", 21, "simulated Idea failure")

    services = ScienceStageServices(
        survey=services.survey,
        idea=failed_idea,
        exp_design=services.exp_design,
        author=services.author,
    )

    with pytest.raises(ScienceWorkflowError, match="simulated Idea failure") as error:
        run_science_workflow(paths=paths, metadata=metadata, services=services)

    _loaded_metadata, state = science_run.load_science_run(paths)
    assert error.value.stage == "idea"
    assert error.value.exit_code == 21
    assert [name for name, _request in calls] == ["survey", "idea"]
    assert state["status"] == "FAILED"
    assert state["stages"]["idea"]["status"] == "FAILED"
    assert state["stages"]["idea"]["failure"]["exit_code"] == 21
    assert state["stages"]["exp_design"]["status"] == "PENDING"
    assert state["stages"]["author"]["status"] == "PENDING"


def test_science_cli_executes_the_service_workflow(tmp_path, monkeypatch, capsys) -> None:
    config_path = _write_config(tmp_path)
    calls: list[tuple[str, object]] = []
    services = _fake_services(calls)

    def noisy_survey(request: SurveyStageRequest) -> ScienceStageResult:
        print("survey progress")
        return services.survey(request)

    monkeypatch.setattr(
        science_workflow,
        "default_science_stage_services",
        lambda: ScienceStageServices(
            survey=noisy_survey,
            idea=services.idea,
            exp_design=services.exp_design,
            author=services.author,
        ),
    )

    assert (
        cli.main(
            [
                "science",
                "--topic",
                "exact handoff topic",
                "--config",
                str(config_path),
                "--output-root",
                str(tmp_path / "science-runs"),
                "--run-id",
                "cli-closed-loop",
                "--discipline-id",
                "25",
                "--json",
            ]
        )
        == cli.SCIENCE_EXIT_SUCCESS
    )

    result = json.loads(capsys.readouterr().out)
    persisted_result = json.loads(
        (
            tmp_path / "science-runs" / "cli-closed-loop" / "science_result.json"
        ).read_text(encoding="utf-8")
    )
    assert [name for name, _request in calls] == ["survey", "idea", "exp_design", "author"]
    assert result["action"] == "EXECUTED"
    assert result["status"] == "COMPLETED"
    assert persisted_result == result
    state = json.loads((tmp_path / "science-runs" / "cli-closed-loop" / "science_state.json").read_text(encoding="utf-8"))
    assert result["state_revision"] == state["revision"]
    assert all(
        getattr(request, "quiet", True)
        for name, request in calls
        if name in {"survey", "idea"}
    )
