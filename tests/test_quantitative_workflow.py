from __future__ import annotations

import json
from pathlib import Path

import pytest
from omegaconf import OmegaConf

from src.agents.quantitative_modeling.author_handoff import (
    QuantitativeAuthorHandoffError,
    build_quantitative_author_handoff,
    expected_quantitative_idea_ids,
    finalize_quantitative_idea,
    load_finalized_quantitative_record,
)
from src.agents.quantitative_modeling.contracts import build_quantitative_idea_set
from src.agents.quantitative_modeling.publisher.run import publish_quantitative_models_pdf
from src.agents.quantitative_modeling.publication_bundle import (
    PublicationBundleError,
    build_publication_bundle,
)
from src.agents.research_plan_author.quantitative_evidence_adapter import (
    QuantitativeEvidenceLoadError,
    load_quantitative_evidence_capsule,
)
from src.pipeline.quantitative_manifests import write_quantitative_ideas_manifest
from src.pipeline.quantitative_orchestrator import (
    QuantitativeOrchestratorError,
    continue_quantitative_until_author_ready,
    refresh_quantitative_state,
    resume_quantitative_from_existing_idea,
)
from src.pipeline.quantitative_workflow import (
    QuantitativeWorkflowError,
    accept_quantitative_refinement,
    build_main_hypothesis_feedback_packet,
    execute_quantitative_plan,
    prepare_quantitative_model_version,
    propose_quantitative_refinement,
    qualify_quantitative_execution,
)
from src.pipeline.science_manifests import (
    verify_survey_manifest,
    write_experiment_design_manifest,
    write_idea_manifest,
)
from src.pipeline.science_run import (
    file_sha256,
    initialize_science_run,
    load_science_run,
    save_science_state,
)
from src.pipeline.survey_handoff_persistence import publish_survey_run_artifacts


def _evidence_plan() -> dict[str, object]:
    return {
        "schema_version": "survey_sh_evidence_plan_v1",
        "project_id": "quantitative-workflow-project",
        "project_context_fingerprint": "quantitative-workflow-context",
        "evidence_bounded_writing": True,
        "subhypotheses": [
            {
                "sub_hypothesis_id": "SH1",
                "summary": "A bounded quantitative question.",
                "required_slots": ["direct_observation"],
                "covered_slots": [],
                "background_only_slots": [],
                "missing_slots": ["direct_observation"],
                "slot_support": {"direct_observation": {"expected_evidence_role": "DIRECT_OBSERVATION", "evidence_paper_ids": [], "background_paper_ids": [], "qualified_paper_ids": [], "qualified_paper_constraints": {}}},
                "relevant_clusters": [],
                "conclusion_admissibility": {"blockers": []},
                "limitations": {"blockers": []},
                "allowed_claim_modes": ["EVIDENCE_GAP_REPORT"],
                "forbidden_paper_ids": [],
                "direct_writing_blocked_paper_ids": [],
            }
        ],
    }


def _q_idea() -> dict[str, object]:
    return {
        "quantitative_idea_id": "Q1",
        "title": "Bounded decay",
        "domain": "MATH_PHYS_ASTRONOMY",
        "base_hypothesis_reference": "directions[0].hypothesis",
        "quantitative_question": "Does the bounded state decay under a constant rate?",
        "model_intent": "Simulate one-state decay scenarios.",
        "candidate_model_strategy": {"mode": "OUTSIDE_CATALOG", "catalog_model_ids": [], "rationale": "A task-specific local approximation."},
        "state_variables": ["x"],
        "parameters_and_sources": ["bounded rate k"],
        "initial_boundary_requirements": ["x(0)"],
        "scenarios": ["baseline"],
        "observables": ["x(t)"],
        "comparator": "initial state",
        "falsification_condition": "The trajectory does not decay under positive k.",
        "provisional_solver_family": "ODE_IVP",
        "execution_readiness": "EXECUTABLE_CANDIDATE",
        "known_limitations": ["constant-rate approximation"],
    }


def _model_response(lineage: dict[str, object]) -> str:
    specification = {
        "schema_version": "ieee_math_model_v1",
        "lineage": lineage,
        "title": "Bounded decay model",
        "abstract": "A one-state model for a bounded numerical simulation.",
        "scientific_question": "Does x decay under positive k?",
        "model_scope": "A local one-state approximation.",
        "assumptions": [{"assumption_id": "A-001", "statement": "k remains constant.", "effect_if_violated": "The rate law must be revised."}],
        "symbols": [{"symbol_id": "S-001", "latex": "x", "meaning": "state", "unit": "1", "dimension": "1", "role": "STATE_VARIABLE"}, {"symbol_id": "S-002", "latex": "k", "meaning": "rate", "unit": "s^{-1}", "dimension": "T^{-1}", "role": "PARAMETER"}],
        "equations": [{"equation_id": "Q1-EQ-001", "role": "GOVERNING_EQUATION", "latex": "\\frac{dx}{dt}=-kx", "where_symbol_ids": ["S-001", "S-002"]}],
        "initial_conditions": ["x(0)=1"],
        "boundary_conditions": ["Initial-value condition."],
        "parameterization": ["k=1 in the baseline."],
        "scenarios": ["baseline"],
        "objective_and_constraints": ["Compute the finite trajectory."],
        "algorithm": {"input": ["k", "x0"], "output": ["x(t)"], "steps": ["Use the fixed ODE adapter."]},
        "numerical_plan": {"solver_family": "ODE_IVP", "discretization": "adaptive ODE", "convergence_checks": ["solver_converged"]},
        "validation_plan": ["Confirm solver convergence."],
        "limitations": ["The result is not empirical."],
        "references": [],
        "mathir": {"schema_version": "mathir_v1", "system_type": "ODE_IVP", "states": [{"id": "x", "initial": 1.0}], "parameters": {"k": 1.0}, "derivatives": {"x": {"op": "mul", "args": [{"op": "neg", "args": [{"op": "variable", "name": "k"}]}, {"op": "variable", "name": "x"}]}}, "time_span": [0.0, 1.0], "solver_options": {"max_step": 0.1}},
    }
    markdown = """Abstract— A bounded model.
# Assumptions
A-001.
# Symbols
S-001 and S-002.
# Equations
Q1-EQ-001, where S-001 is x and S-002 is k.
# Algorithm
Input: k. Output: x(t). Steps: integrate.
# Parameters and Scenarios
Parameters include k; scenarios include baseline.
# Numerical Validation
Validation checks convergence.
# Limitations
Non-empirical.
# References
None.
"""
    return "<QUANTITATIVE_MODEL_JSON>\n" + json.dumps(specification) + "\n</QUANTITATIVE_MODEL_JSON>\n<QUANTITATIVE_MODEL_MARKDOWN>\n" + markdown + "</QUANTITATIVE_MODEL_MARKDOWN>"


def _prepare_qualified_q0_run(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    config_path = tmp_path / "science.yaml"
    OmegaConf.save(OmegaConf.create({"research": {"model": "test-model"}}), config_path)
    paths, metadata, _state = initialize_science_run(
        output_root=tmp_path / "runs",
        topic="bounded decay",
        config_path=config_path,
        immutable_options={"discipline_ids": ["25"]},
        run_id="quantitative-flow",
    )
    idea_attempt = paths.run_dir / "idea" / "attempt-001"
    survey_published = publish_survey_run_artifacts(
        base_dir=paths.run_dir / "survey" / "attempt-001",
        topic="bounded decay",
        survey_run_id="survey-quantitative-flow",
        final_survey="Survey body",
        survey_payload={"topic": "bounded decay"},
        project_context={"input_fingerprint": "quantitative-workflow-context", "domain": "Physics"},
        evidence_plan=_evidence_plan(),
        claim_traceability={"claims": []},
    )
    survey_manifest = Path(survey_published["manifest_path"])
    survey_identity = dict(verify_survey_manifest(survey_manifest).identity)
    idea_attempt.mkdir(parents=True)
    idea_result = idea_attempt / "idea_result.json"
    idea_result.write_text(json.dumps({"schema_version": "idea_result_v5", "topic": "bounded decay", "survey_binding": survey_identity, "primary_direction": "direction-1"}), encoding="utf-8")
    idea_identity = {**survey_identity, "selected_direction_id": "direction-1"}
    idea_manifest = write_idea_manifest(
        attempt_dir=idea_attempt,
        topic="bounded decay",
        idea_result_path=idea_result,
        survey_manifest_path=survey_manifest,
        identity=idea_identity,
        selected_direction_id="direction-1",
    )
    sidecar = build_quantitative_idea_set(
        topic="bounded decay",
        source_identity={**idea_identity, "science_run_id": metadata["science_run_id"], "idea_result_path": str(idea_result)},
        generation_status="READY",
        ideas=[_q_idea()],
    )
    sidecar_path = idea_attempt / "quantitative_ideas.json"
    sidecar_path.write_text(json.dumps(sidecar), encoding="utf-8")
    sidecar_manifest = write_quantitative_ideas_manifest(
        attempt_dir=idea_attempt,
        topic="bounded decay",
        idea_manifest_path=idea_manifest,
        ideas_path=sidecar_path,
        identity=idea_identity,
    )
    design_attempt = paths.run_dir / "experiment_design" / "attempt-001"
    design_attempt.mkdir(parents=True)
    design_json = design_attempt / "research_design.json"
    design_json.write_text(
        json.dumps(
            {
                "execution_policy": {"mode": "DESIGN_ONLY"},
                "research_brief": {"discipline_ids": ["25"]},
                "design_id": "design-001",
            }
        ),
        encoding="utf-8",
    )
    design_markdown = design_attempt / "research_design.md"
    design_markdown.write_text("# Design\n", encoding="utf-8")
    author_json = design_attempt / "author_handoff.json"
    author_json.write_text(
        json.dumps(
            {
                "schema_version": "research_plan_author_input_v3",
                "provenance": {
                    "survey_binding": idea_identity,
                    "selected_direction_id": "direction-1",
                    "idea_result_path": str(idea_result),
                },
            }
        ),
        encoding="utf-8",
    )
    design_manifest = write_experiment_design_manifest(
        attempt_dir=design_attempt,
        topic="bounded decay",
        idea_manifest_path=idea_manifest,
        idea_result_path=idea_result,
        artifact_paths={
            "experiment_design_json": design_json,
            "experiment_design_markdown": design_markdown,
            "author_json": author_json,
        },
        identity=idea_identity,
        design_id="design-001",
        selected_direction_id="direction-1",
        discipline_ids=["25"],
    )
    _metadata, science_state = load_science_run(paths)
    science_state["stages"]["survey"].update(
        {
            "status": "COMPLETED",
            "result_manifest_path": str(survey_manifest),
            "result_identity": {"result_sha256": file_sha256(survey_manifest)},
            "outputs": {"survey_manifest": str(survey_manifest)},
        }
    )
    science_state["stages"]["idea"].update(
        {
            "status": "COMPLETED",
            "result_manifest_path": str(idea_manifest),
            "result_identity": {"result_sha256": file_sha256(idea_manifest)},
            "outputs": {"idea_result": str(idea_result)},
        }
    )
    science_state["stages"]["exp_design"].update(
        {
            "status": "COMPLETED",
            "result_manifest_path": str(design_manifest),
            "result_identity": {"result_sha256": file_sha256(design_manifest)},
            "outputs": {"experiment_design_manifest": str(design_manifest)},
        }
    )
    save_science_state(paths, science_state)
    expected_lineage = {
        "science_run_id": "quantitative-flow",
        "survey_run_id": survey_identity["survey_run_id"],
        "project_id": survey_identity["project_id"],
        "project_context_fingerprint": survey_identity["project_context_fingerprint"],
        "selected_direction_id": "direction-1",
        "quantitative_idea_id": "Q1",
        "version": 0,
        "parent_version": None,
        "created_from_artifact": str(sidecar_manifest),
    }
    artifacts = prepare_quantitative_model_version(
        run_dir=paths.run_dir,
        quantitative_ideas_manifest_path=sidecar_manifest,
        quantitative_idea_id="Q1",
        version=0,
        llm_call=lambda _prompt: _model_response(expected_lineage),
    )
    plan = json.loads(Path(artifacts["plan"]).read_text(encoding="utf-8"))
    execution_paths = execute_quantitative_plan(
        run_dir=paths.run_dir,
        quantitative_idea_id="Q1",
        version=0,
        execute=True,
        confirmed_plan_identity=plan["plan_identity"],
    )
    execution_id = json.loads(Path(execution_paths["execution_record"]).read_text(encoding="utf-8"))["execution_id"]
    qualification = qualify_quantitative_execution(
        run_dir=paths.run_dir,
        quantitative_idea_id="Q1",
        version=0,
        execution_id=execution_id,
        hypothesis_relation="REFUTED_WITHIN_MODEL",
        result_summary="The model-internal baseline decays under the stated assumptions.",
    )
    assert Path(qualification["ledger"]).is_file()
    return paths.run_dir, idea_identity


def test_quantitative_resume_from_existing_idea_recreates_missing_sidecar(tmp_path: Path) -> None:
    run_dir, _identity = _prepare_qualified_q0_run(tmp_path)
    state_path = run_dir / "science_state.json"
    science_state = json.loads(state_path.read_text(encoding="utf-8"))
    idea_manifest = Path(science_state["stages"]["idea"]["result_manifest_path"])
    idea_result = idea_manifest.parent / "idea_result.json"
    sidecar_path = idea_manifest.parent / "quantitative_ideas.json"
    sidecar_manifest_path = idea_manifest.parent / "quantitative_ideas_manifest.json"
    original_idea_manifest = idea_manifest.read_bytes()
    original_idea_result = idea_result.read_bytes()
    sidecar_path.unlink()
    sidecar_manifest_path.unlink()

    calls: list[str] = []

    def fake_idea_llm(prompt: str, **_kwargs: object) -> dict[str, object]:
        calls.append(prompt)
        return {"ideas": [_q_idea()]}

    state = resume_quantitative_from_existing_idea(run_dir=run_dir, llm_call=fake_idea_llm)

    assert len(calls) == 1
    assert idea_manifest.read_bytes() == original_idea_manifest
    assert idea_result.read_bytes() == original_idea_result
    assert sidecar_path.is_file()
    assert sidecar_manifest_path.is_file()
    assert state["status"] == "QUALIFIED_WAITING_FOR_REVISION_DECISION"
    persisted_state = json.loads(state_path.read_text(encoding="utf-8"))
    assert persisted_state["stages"]["idea"]["outputs"]["quantitative_ideas"] == str(sidecar_path)
    assert refresh_quantitative_state(run_dir)["quantitative_ideas_manifest"]["path"] == str(
        sidecar_manifest_path.resolve()
    )


def test_quantitative_resume_from_existing_idea_reuses_verified_sidecar(tmp_path: Path) -> None:
    run_dir, _identity = _prepare_qualified_q0_run(tmp_path)
    state = resume_quantitative_from_existing_idea(
        run_dir=run_dir,
        llm_call=lambda *_args, **_kwargs: pytest.fail("verified sidecar should not invoke the LLM"),
    )

    assert state["status"] == "QUALIFIED_WAITING_FOR_REVISION_DECISION"


def test_quantitative_resume_rejects_an_idea_manifest_outside_the_current_run(
    tmp_path: Path,
) -> None:
    run_dir, _identity = _prepare_qualified_q0_run(tmp_path)
    state_path = run_dir / "science_state.json"
    science_state = json.loads(state_path.read_text(encoding="utf-8"))
    foreign_manifest = tmp_path / "foreign" / "idea_manifest.json"
    foreign_manifest.parent.mkdir(parents=True)
    foreign_manifest.write_text("{}", encoding="utf-8")
    science_state["stages"]["idea"]["result_manifest_path"] = str(foreign_manifest)
    science_state["stages"]["idea"]["result_identity"] = {
        "result_sha256": file_sha256(foreign_manifest),
    }
    state_path.write_text(json.dumps(science_state), encoding="utf-8")

    with pytest.raises(QuantitativeOrchestratorError, match="escapes the science run Idea directory"):
        resume_quantitative_from_existing_idea(
            run_dir=run_dir,
            llm_call=lambda *_args, **_kwargs: pytest.fail("foreign Idea must be rejected before the LLM call"),
        )


def test_quantitative_resume_from_existing_idea_only_resumes_pending_experiment_design(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_dir, _identity = _prepare_qualified_q0_run(tmp_path)
    state_path = run_dir / "science_state.json"
    science_state = json.loads(state_path.read_text(encoding="utf-8"))
    completed_design = dict(science_state["stages"]["exp_design"])
    science_state["stages"]["exp_design"] = {
        **science_state["stages"]["exp_design"],
        "status": "PENDING",
        "result_manifest_path": None,
        "result_identity": {},
        "outputs": {},
    }
    state_path.write_text(json.dumps(science_state), encoding="utf-8")
    idea_manifest = Path(science_state["stages"]["idea"]["result_manifest_path"])
    (idea_manifest.parent / "quantitative_ideas.json").unlink()
    (idea_manifest.parent / "quantitative_ideas_manifest.json").unlink()
    calls: list[str] = []

    def fake_science_workflow(*, paths: object, metadata: object, until: str, quiet: bool) -> None:
        assert str(paths.run_dir) == str(run_dir)
        assert metadata
        assert until == "exp_design"
        assert quiet is True
        calls.append(until)
        persisted = json.loads(state_path.read_text(encoding="utf-8"))
        persisted["stages"]["exp_design"] = completed_design
        state_path.write_text(json.dumps(persisted), encoding="utf-8")

    monkeypatch.setattr("src.pipeline.science_workflow.run_science_workflow", fake_science_workflow)
    state = resume_quantitative_from_existing_idea(
        run_dir=run_dir,
        llm_call=lambda _prompt, **_kwargs: {"ideas": [_q_idea()]},
    )

    assert calls == ["exp_design"]
    assert state["status"] == "QUALIFIED_WAITING_FOR_REVISION_DECISION"


def test_quantitative_high_level_continuation_stops_before_simulation_authorization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    initial_state = {
        "status": "WAITING_FOR_BLUEPRINT",
        "ideas": {"Q1": {"status": "WAITING_FOR_BLUEPRINT"}},
        "experiment_design": {"status": "COMPLETED"},
    }
    authorization_state = {
        "status": "WAITING_FOR_EXECUTION_AUTHORIZATION",
        "ideas": {"Q1": {"status": "WAITING_FOR_EXECUTION_AUTHORIZATION"}},
        "experiment_design": {"status": "COMPLETED"},
    }
    calls: list[str] = []

    monkeypatch.setattr(
        "src.pipeline.quantitative_orchestrator.resume_quantitative_from_existing_idea",
        lambda **_kwargs: initial_state,
    )

    def stop_at_authorization(**_kwargs: object) -> dict[str, object]:
        calls.append("continue")
        return authorization_state

    monkeypatch.setattr(
        "src.pipeline.quantitative_orchestrator.continue_quantitative_workflow",
        stop_at_authorization,
    )

    state = continue_quantitative_until_author_ready(
        run_dir="unused-run",
        idea_llm_call=lambda *_args, **_kwargs: None,
        model_llm_call=lambda *_args, **_kwargs: None,
    )

    assert state is authorization_state
    assert calls == ["continue"]


def test_quantitative_workflow_requires_new_authorization_for_each_materialized_version(tmp_path: Path) -> None:
    run_dir, _identity = _prepare_qualified_q0_run(tmp_path)
    proposal = propose_quantitative_refinement(
        run_dir=run_dir,
        quantitative_idea_id="Q1",
        version=0,
        revision_reason="The qualified model-internal refutation changes the local boundary.",
        hypothesis_delta="Restrict the local hypothesis to a different rate regime.",
        model_delta=["Update the rate parameterization."],
        parameter_or_boundary_delta=["Constrain k to the revised range."],
        expected_discriminating_result="The revised trajectory separates the two regimes.",
        falsification_condition="The revised range still decays identically.",
    )
    acceptance = accept_quantitative_refinement(
        run_dir=run_dir,
        quantitative_idea_id="Q1",
        parent_version=0,
        accept=True,
    )

    assert Path(proposal).is_file()
    assert Path(acceptance).is_file()
    assert Path(build_main_hypothesis_feedback_packet(run_dir=run_dir)).is_file()


def test_finalized_quantitative_result_is_hash_frozen_and_reaches_author(tmp_path: Path) -> None:
    run_dir, identity = _prepare_qualified_q0_run(tmp_path)
    finalization_path = finalize_quantitative_idea(
        run_dir=run_dir,
        quantitative_idea_id="Q1",
        version=0,
    )
    finalized = load_finalized_quantitative_record(root=run_dir, finalization_path=finalization_path)
    assert finalized["qualified_entries"][0]["hypothesis_relation"] == "REFUTED_WITHIN_MODEL"

    publication = publish_quantitative_models_pdf(run_dir=run_dir)
    publication_pdf = Path(publication["pdf"])
    assert publication_pdf.is_file()
    handoff_path, manifest_path = build_quantitative_author_handoff(
        run_dir=run_dir,
        quantitative_models_pdf_path=publication_pdf,
    )
    capsule = load_quantitative_evidence_capsule(
        manifest_path,
        expected_identity=identity,
    )
    assert capsule["evidence"][0]["hypothesis_relation"] == "REFUTED_WITHIN_MODEL"
    main_article_pdf = run_dir / "author" / "research_plan.pdf"
    main_article_pdf.parent.mkdir()
    main_article_pdf.write_bytes(publication_pdf.read_bytes())
    bundle_path = build_publication_bundle(
        run_dir=run_dir,
        main_article_pdf=main_article_pdf,
        quantitative_author_handoff_manifest=manifest_path,
    )
    assert json.loads(bundle_path.read_text(encoding="utf-8"))["formal_pdf_count"] == 2

    Path(handoff_path).write_text("{}", encoding="utf-8")
    with pytest.raises(QuantitativeEvidenceLoadError, match="hash"):
        load_quantitative_evidence_capsule(manifest_path, expected_identity=identity)

    markdown_path = run_dir / "quantitative" / "Q1" / "v0" / "mathematical_model.md"
    markdown_path.write_text(markdown_path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    with pytest.raises(QuantitativeAuthorHandoffError, match="hash"):
        load_finalized_quantitative_record(root=run_dir, finalization_path=finalization_path)
    with pytest.raises(QuantitativeWorkflowError, match="already been finalized"):
        propose_quantitative_refinement(
            run_dir=run_dir,
            quantitative_idea_id="Q1",
            version=0,
            revision_reason="A frozen result cannot start another revision.",
            hypothesis_delta="none",
            model_delta=["none"],
            parameter_or_boundary_delta=["none"],
            expected_discriminating_result="none",
            falsification_condition="none",
        )


def test_publication_bundle_requires_completed_experiment_design(tmp_path: Path) -> None:
    run_dir, _identity = _prepare_qualified_q0_run(tmp_path)
    finalize_quantitative_idea(
        run_dir=run_dir,
        quantitative_idea_id="Q1",
        version=0,
    )
    publication = publish_quantitative_models_pdf(run_dir=run_dir)
    _handoff_path, handoff_manifest = build_quantitative_author_handoff(
        run_dir=run_dir,
        quantitative_models_pdf_path=publication["pdf"],
    )
    main_article_pdf = run_dir / "author" / "research_plan.pdf"
    main_article_pdf.parent.mkdir()
    main_article_pdf.write_bytes(Path(publication["pdf"]).read_bytes())

    state_path = run_dir / "science_state.json"
    science_state = json.loads(state_path.read_text(encoding="utf-8"))
    science_state["stages"]["exp_design"]["status"] = "PENDING"
    state_path.write_text(json.dumps(science_state), encoding="utf-8")

    with pytest.raises(PublicationBundleError, match="ExperimentDesign"):
        build_publication_bundle(
            run_dir=run_dir,
            main_article_pdf=main_article_pdf,
            quantitative_author_handoff_manifest=handoff_manifest,
        )
    assert not (run_dir / "quantitative" / "publication" / "publication_bundle_manifest.json").exists()


def test_quantitative_handoff_rejects_workflow_manifest_from_another_run(tmp_path: Path) -> None:
    run_dir, _identity = _prepare_qualified_q0_run(tmp_path)
    workflow_manifest_path = run_dir / "quantitative" / "quantitative_workflow_manifest.json"
    workflow_manifest = json.loads(workflow_manifest_path.read_text(encoding="utf-8"))
    workflow_manifest["science_run_id"] = "different-science-run"
    workflow_manifest_path.write_text(json.dumps(workflow_manifest), encoding="utf-8")

    with pytest.raises(QuantitativeAuthorHandoffError, match="science_run_id"):
        expected_quantitative_idea_ids(root=run_dir)
