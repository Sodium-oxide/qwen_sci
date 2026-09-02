from __future__ import annotations

import json
from pathlib import Path

from omegaconf import OmegaConf

from src.agents.quantitative_modeling.author_handoff import (
    build_quantitative_author_handoff,
    finalize_quantitative_idea,
)
from src.agents.quantitative_modeling.contracts import build_quantitative_idea_set
from src.agents.quantitative_modeling.publisher.run import publish_quantitative_models_pdf
from src.agents.research_plan_author.quantitative_evidence_adapter import (
    load_quantitative_evidence_capsule,
)
from src.pipeline.quantitative_manifests import write_quantitative_ideas_manifest
from src.pipeline.quantitative_workflow import (
    approve_quantitative_parameter_resolution,
    extract_quantitative_parameter_candidates,
    execute_quantitative_plan,
    materialize_quantitative_model_version,
    prepare_quantitative_model_blueprint,
    propose_quantitative_parameter_resolution,
    qualify_quantitative_execution,
    register_quantitative_parameter_document,
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
        "project_id": "quantitative-parameter-project",
        "project_context_fingerprint": "quantitative-parameter-context",
        "evidence_bounded_writing": True,
        "subhypotheses": [
            {
                "sub_hypothesis_id": "SH1",
                "summary": "A bounded parameter question.",
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


def _idea() -> dict[str, object]:
    return {
        "quantitative_idea_id": "Q1",
        "title": "Evidence-bound decay",
        "domain": "MATH_PHYS_ASTRONOMY",
        "base_hypothesis_reference": "directions[0].hypothesis",
        "quantitative_question": "Does the bounded state decay under an evidenced rate?",
        "model_intent": "Simulate one-state decay with an evidence-bound coefficient.",
        "candidate_model_strategy": {
            "mode": "OUTSIDE_CATALOG",
            "catalog_model_ids": [],
            "rationale": "A controlled local approximation.",
        },
        "state_variables": ["x"],
        "parameters_and_sources": ["rate coefficient k"],
        "initial_boundary_requirements": ["x(0)"],
        "scenarios": ["baseline"],
        "observables": ["x(t)"],
        "comparator": "initial state",
        "falsification_condition": "The trajectory does not decay for an evidenced positive rate.",
        "provisional_solver_family": "ODE_IVP",
        "execution_readiness": "EXECUTABLE_CANDIDATE",
        "known_limitations": ["constant-rate approximation"],
    }


def _blueprint_response(lineage: dict[str, object]) -> str:
    blueprint = {
        "schema_version": "quantitative_model_blueprint_v1",
        "lineage": lineage,
        "title": "Evidence-bound decay blueprint",
        "scientific_question": "Does x decay under an evidenced positive k?",
        "model_scope": "A local one-state ODE.",
        "symbolic_model_intent": "dx/dt=-k*x",
        "permitted_system_types": ["ODE_IVP"],
        "parameter_requests": [
            {
                "parameter_id": "k",
                "mathir_symbol": "k",
                "meaning": "constant decay rate",
                "unit": "s^-1",
                "dimension": "T^-1",
                "role": "MATERIAL_PROPERTY",
                "value_kind": "SCALAR",
                "evidence_requirement": "USER_OR_LITERATURE",
                "required_conditions": ["temperature_K"],
                "retrieval_queries": ["measured decay rate temperature"],
            }
        ],
        "symbolic_constraints": ["k > 0"],
        "revision_context": {},
    }
    return "<QUANTITATIVE_MODEL_BLUEPRINT_JSON>" + json.dumps(blueprint) + "</QUANTITATIVE_MODEL_BLUEPRINT_JSON>"


def _model_response(lineage: dict[str, object]) -> str:
    specification = {
        "schema_version": "ieee_math_model_v1",
        "lineage": lineage,
        "title": "Evidence-bound decay model",
        "abstract": "A one-state numerical model with an approved measured rate.",
        "scientific_question": "Does x decay under the approved positive k?",
        "model_scope": "A local one-state approximation.",
        "assumptions": [
            {
                "assumption_id": "A-001",
                "statement": "k remains constant over the modeled interval.",
                "effect_if_violated": "The rate law must be revised.",
            }
        ],
        "symbols": [
            {"symbol_id": "S-001", "latex": "x", "meaning": "state", "unit": "1", "dimension": "1", "role": "STATE_VARIABLE"},
            {"symbol_id": "S-002", "latex": "k", "meaning": "rate", "unit": "s^{-1}", "dimension": "T^{-1}", "role": "PARAMETER"},
        ],
        "equations": [
            {
                "equation_id": "Q1-EQ-001",
                "role": "GOVERNING_EQUATION",
                "latex": "\\frac{dx}{dt}=-kx",
                "where_symbol_ids": ["S-001", "S-002"],
            }
        ],
        "initial_conditions": ["x(0)=1"],
        "boundary_conditions": ["Initial-value condition."],
        "parameterization": ["k=2 s^-1 from the approved parameter set."],
        "scenarios": ["baseline"],
        "objective_and_constraints": ["Compute a bounded finite trajectory."],
        "algorithm": {"input": ["k", "x0"], "output": ["x(t)"], "steps": ["Use the fixed ODE adapter."]},
        "numerical_plan": {"solver_family": "ODE_IVP", "discretization": "adaptive ODE", "convergence_checks": ["solver_converged"]},
        "validation_plan": ["Confirm solver convergence."],
        "limitations": ["The result is not empirical."],
        "references": [],
        "mathir": {
            "schema_version": "mathir_v1",
            "system_type": "ODE_IVP",
            "states": [{"id": "x", "initial": 1.0}],
            "parameters": {"k": 2.0},
            "derivatives": {
                "x": {
                    "op": "mul",
                    "args": [
                        {"op": "neg", "args": [{"op": "variable", "name": "k"}]},
                        {"op": "variable", "name": "x"},
                    ],
                }
            },
            "time_span": [0.0, 1.0],
            "solver_options": {"max_step": 0.1},
        },
    }
    markdown = """Abstract— Evidence-bound bounded model.
# Assumptions
A-001.
# Symbols
S-001 and S-002.
# Equations
Q1-EQ-001, where S-001 is x and S-002 is k.
# Algorithm
Input: k. Output: x(t). Steps: integrate.
# Parameters and Scenarios
Parameters include the approved k; scenarios include baseline.
# Numerical Validation
Validation checks convergence.
# Limitations
Non-empirical.
# References
Controlled parameter source is described in the supplementary provenance section.
"""
    return "<QUANTITATIVE_MODEL_JSON>\n" + json.dumps(specification) + "\n</QUANTITATIVE_MODEL_JSON>\n<QUANTITATIVE_MODEL_MARKDOWN>\n" + markdown + "</QUANTITATIVE_MODEL_MARKDOWN>"


def _seed_run(tmp_path: Path) -> tuple[Path, Path, dict[str, object], dict[str, str]]:
    config_path = tmp_path / "science.yaml"
    OmegaConf.save(OmegaConf.create({"research": {"model": "test-model"}}), config_path)
    paths, metadata, _state = initialize_science_run(
        output_root=tmp_path / "runs",
        topic="evidence-bound decay",
        config_path=config_path,
        immutable_options={"discipline_ids": ["25"]},
        run_id="qpf",
    )
    attempt_dir = paths.run_dir / "idea" / "attempt-001"
    published = publish_survey_run_artifacts(
        base_dir=paths.run_dir / "survey" / "attempt-001",
        topic="evidence-bound decay",
        survey_run_id="survey-quantitative-parameter",
        final_survey="Survey body",
        survey_payload={"topic": "evidence-bound decay"},
        project_context={"input_fingerprint": "quantitative-parameter-context", "domain": "Physics"},
        evidence_plan=_evidence_plan(),
        claim_traceability={"claims": []},
    )
    survey_manifest = Path(published["manifest_path"])
    survey_identity = dict(verify_survey_manifest(survey_manifest).identity)
    attempt_dir.mkdir(parents=True)
    idea_result = attempt_dir / "idea_result.json"
    idea_result.write_text(
        json.dumps(
            {
                "schema_version": "idea_result_v5",
                "topic": "evidence-bound decay",
                "survey_binding": survey_identity,
                "primary_direction": "direction-1",
            }
        ),
        encoding="utf-8",
    )
    identity = {**survey_identity, "selected_direction_id": "direction-1"}
    idea_manifest = write_idea_manifest(
        attempt_dir=attempt_dir,
        topic="evidence-bound decay",
        idea_result_path=idea_result,
        survey_manifest_path=survey_manifest,
        identity=identity,
        selected_direction_id="direction-1",
    )
    sidecar = build_quantitative_idea_set(
        topic="evidence-bound decay",
        source_identity={**identity, "science_run_id": metadata["science_run_id"], "idea_result_path": str(idea_result)},
        generation_status="READY",
        ideas=[_idea()],
    )
    sidecar_path = attempt_dir / "quantitative_ideas.json"
    sidecar_path.write_text(json.dumps(sidecar), encoding="utf-8")
    sidecar_manifest = write_quantitative_ideas_manifest(
        attempt_dir=attempt_dir,
        topic="evidence-bound decay",
        idea_manifest_path=idea_manifest,
        ideas_path=sidecar_path,
        identity=identity,
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
                    "survey_binding": identity,
                    "selected_direction_id": "direction-1",
                    "idea_result_path": str(idea_result),
                },
            }
        ),
        encoding="utf-8",
    )
    design_manifest = write_experiment_design_manifest(
        attempt_dir=design_attempt,
        topic="evidence-bound decay",
        idea_manifest_path=idea_manifest,
        idea_result_path=idea_result,
        artifact_paths={
            "experiment_design_json": design_json,
            "experiment_design_markdown": design_markdown,
            "author_json": author_json,
        },
        identity=identity,
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
    lineage = {
        "science_run_id": metadata["science_run_id"],
        "survey_run_id": survey_identity["survey_run_id"],
        "project_id": survey_identity["project_id"],
        "project_context_fingerprint": survey_identity["project_context_fingerprint"],
        "selected_direction_id": "direction-1",
        "quantitative_idea_id": "Q1",
        "version": 0,
        "parent_version": None,
        "created_from_artifact": str(sidecar_manifest),
    }
    return paths.run_dir, sidecar_manifest, lineage, identity


def test_evidence_bound_parameter_workflow_reaches_pdf_and_author(tmp_path: Path) -> None:
    run_dir, sidecar_manifest, lineage, identity = _seed_run(tmp_path)
    blueprint_paths = prepare_quantitative_model_blueprint(
        run_dir=run_dir,
        quantitative_ideas_manifest_path=sidecar_manifest,
        quantitative_idea_id="Q1",
        version=0,
        llm_call=lambda _prompt: _blueprint_response(lineage),
    )
    assert Path(blueprint_paths["query_plan"]).is_file()

    user_document = tmp_path / "measurement.txt"
    quote = "At 300 K, the measured decay coefficient was k = 2.0 s^-1."
    user_document.write_text(quote, encoding="utf-8")
    register_quantitative_parameter_document(
        run_dir=run_dir,
        quantitative_idea_id="Q1",
        version=0,
        document_path=user_document,
        document_id="UPD-001",
        title="Controlled measurement note",
        year=2025,
    )
    extraction_response = {
        "candidates": [
            {
                "parameter_id": "k",
                "mathir_symbol": "k",
                "raw_value": "k = 2.0 s^-1",
                "normalized_value": 2.0,
                "normalized_unit": "s^-1",
                "source_kind": "USER_PROVIDED",
                "evidence_locator": {
                    "document_type": "TXT",
                    "section": "",
                    "table_or_figure": "",
                    "page": None,
                    "quoted_text": quote,
                },
                "conditions": {"temperature_K": 300.0},
                "uncertainty": {},
                "transformation": {"applied": False, "formula": ""},
            }
        ]
    }
    extract_quantitative_parameter_candidates(
        run_dir=run_dir,
        quantitative_idea_id="Q1",
        version=0,
        document_id="UPD-001",
        llm_call=lambda _prompt: "<QUANTITATIVE_PARAMETER_EVIDENCE_JSON>"
        + json.dumps(extraction_response)
        + "</QUANTITATIVE_PARAMETER_EVIDENCE_JSON>",
    )
    propose_quantitative_parameter_resolution(
        run_dir=run_dir,
        quantitative_idea_id="Q1",
        version=0,
        selections=[
            {
                "parameter_id": "k",
                "candidate_id": "PEC-Q1-k-001",
                "selection_rationale": "The user-provided measured condition is the modeled baseline.",
            }
        ],
    )
    approved = approve_quantitative_parameter_resolution(
        run_dir=run_dir,
        quantitative_idea_id="Q1",
        version=0,
        approve=True,
    )
    assert Path(approved["manifest"]).is_file()

    artifacts = materialize_quantitative_model_version(
        run_dir=run_dir,
        quantitative_ideas_manifest_path=sidecar_manifest,
        quantitative_idea_id="Q1",
        version=0,
        llm_call=lambda _prompt: _model_response(lineage),
    )
    plan = json.loads(Path(artifacts["plan"]).read_text(encoding="utf-8"))
    assert plan["parameter_provenance"]["mode"] == "APPROVED_PARAMETER_SET"
    assert plan["mathir"]["parameters"] == {"k": 2.0}

    execution = execute_quantitative_plan(
        run_dir=run_dir,
        quantitative_idea_id="Q1",
        version=0,
        execute=True,
        confirmed_plan_identity=plan["plan_identity"],
    )
    execution_id = json.loads(Path(execution["execution_record"]).read_text(encoding="utf-8"))["execution_id"]
    qualify_quantitative_execution(
        run_dir=run_dir,
        quantitative_idea_id="Q1",
        version=0,
        execution_id=execution_id,
        hypothesis_relation="REFUTED_WITHIN_MODEL",
        result_summary="The evidence-bound numerical trajectory decays under the approved parameter set.",
    )
    finalize_quantitative_idea(run_dir=run_dir, quantitative_idea_id="Q1", version=0)
    publication = publish_quantitative_models_pdf(run_dir=run_dir)
    assert "Parameter Provenance and Applicability" in Path(publication["tex"]).read_text(encoding="utf-8")
    _handoff, handoff_manifest = build_quantitative_author_handoff(
        run_dir=run_dir,
        quantitative_models_pdf_path=publication["pdf"],
    )
    capsule = load_quantitative_evidence_capsule(handoff_manifest, expected_identity=identity)
    assert capsule["evidence"][0]["parameter_provenance"]["mode"] == "APPROVED_PARAMETER_SET"
    assert (
        capsule["evidence"][0]["parameter_provenance"]["entries"][0]["evidence_locator"]["document_type"]
        == "TXT"
    )
