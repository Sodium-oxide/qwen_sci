from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.agents.quantitative_modeling.parameter_contracts import (
    PARAMETER_EVIDENCE_COLLECTION_SCHEMA_VERSION,
    ParameterContractError,
    approve_parameter_resolution_proposal,
    build_parameter_resolution_proposal,
    model_blueprint_identity,
    normalize_approved_parameter_set,
    normalize_model_blueprint,
)
from src.agents.quantitative_modeling.parameter_evidence.discovery import discover_parameter_literature
from src.agents.quantitative_modeling.parameter_evidence.extraction import (
    extract_parameter_evidence_candidates,
)
from src.agents.quantitative_modeling.parameter_evidence.fulltext import fetch_open_access_fulltexts
from src.agents.quantitative_modeling.parameter_evidence.providers import (
    AcademicMetadataProviders,
    ParameterEvidenceSettings,
)
from src.agents.quantitative_modeling.model_blueprint import (
    QuantitativeModelBlueprintError,
    build_quantitative_model_blueprint_repair_prompt,
    build_quantitative_model_blueprint_prompt,
    parse_quantitative_model_blueprint_response,
    synthesize_quantitative_model_blueprint,
)
from src.agents.quantitative_modeling.run_plan import (
    SimulationRunPlanError,
    build_simulation_run_plan,
)


def _lineage() -> dict[str, object]:
    return {
        "science_run_id": "run-parameter",
        "survey_run_id": "survey-parameter",
        "project_id": "project-parameter",
        "project_context_fingerprint": "context-parameter",
        "selected_direction_id": "direction-parameter",
        "quantitative_idea_id": "Q1",
        "version": 0,
        "parent_version": None,
        "created_from_artifact": "quantitative_ideas_manifest.json",
    }


def _blueprint(*, scenario_role: bool = False) -> dict[str, object]:
    requests = [
        {
            "parameter_id": "k",
            "mathir_symbol": "k",
            "meaning": "decay coefficient",
            "unit": "s^-1",
            "dimension": "T^-1",
            "role": "MATERIAL_PROPERTY",
            "value_kind": "SCALAR",
            "evidence_requirement": "LITERATURE_REQUIRED",
            "required_conditions": ["temperature_K"],
            "retrieval_queries": ["decay coefficient measured temperature"],
        }
    ]
    if scenario_role:
        requests.append(
            {
                "parameter_id": "forcing",
                "mathir_symbol": "forcing",
                "meaning": "controlled forcing",
                "unit": "s^-1",
                "dimension": "T^-1",
                "role": "SCENARIO_INPUT",
                "value_kind": "SCALAR",
                "evidence_requirement": "MODEL_ASSUMPTION_ALLOWED",
                "required_conditions": [],
                "retrieval_queries": [],
            }
        )
    return {
        "schema_version": "quantitative_model_blueprint_v1",
        "lineage": _lineage(),
        "title": "Decay parameter blueprint",
        "scientific_question": "How does a bounded state respond to a documented coefficient?",
        "model_scope": "One-state local model.",
        "symbolic_model_intent": "dx/dt=-k*x+forcing",
        "permitted_system_types": ["ODE_IVP"],
        "parameter_requests": requests,
        "symbolic_constraints": ["k > 0"],
        "revision_context": {},
    }


def _candidate(*, value: float = 2.0) -> dict[str, object]:
    return {
        "candidate_id": "PEC-Q1-k-001",
        "parameter_id": "k",
        "mathir_symbol": "k",
        "raw_value": f"k = {value} s^-1 at 300 K",
        "normalized_value": value,
        "normalized_unit": "s^-1",
        "source_kind": "PRIMARY_MEASUREMENT",
        "evidence_status": "EXTRACTED_FULLTEXT",
        "source": {
            "doi": "10.1000/example",
            "document_id": "PFD-001",
            "title": "Measured coefficient",
            "year": 2025,
            "discovery_sources": ["openalex", "semantic_scholar"],
            "cross_validated": True,
        },
        "evidence_locator": {
            "document_type": "PDF",
            "section": "Results",
            "table_or_figure": "Table 1",
            "page": 3,
            "quoted_text": f"k = {value} s^-1 at 300 K",
        },
        "conditions": {"temperature_K": 300.0},
        "uncertainty": {"absolute": 0.1},
        "transformation": {"applied": False, "formula": ""},
    }


def _collection(blueprint: dict[str, object], *candidates: dict[str, object]) -> dict[str, object]:
    return {
        "schema_version": PARAMETER_EVIDENCE_COLLECTION_SCHEMA_VERSION,
        "blueprint_identity": model_blueprint_identity(blueprint),
        "lineage": _lineage(),
        "source_document": {"document_id": "PFD-001"},
        "candidates": list(candidates),
    }


def _approved_set(*, scenario_role: bool = False) -> dict[str, object]:
    blueprint = _blueprint(scenario_role=scenario_role)
    selections: list[dict[str, object]] = [
        {
            "parameter_id": "k",
            "candidate_id": "PEC-Q1-k-001",
            "provenance_status": "APPROVED_LITERATURE_SINGLE_SOURCE",
            "selection_rationale": "The conditions match the model baseline.",
        }
    ]
    candidates = [_candidate()]
    if scenario_role:
        selections.append(
            {
                "parameter_id": "forcing",
                "candidate_id": "",
                "provenance_status": "APPROVED_MODEL_ASSUMPTION",
                "selected_value": 0.0,
                "selection_rationale": "The baseline has no externally imposed forcing.",
            }
        )
    proposal = build_parameter_resolution_proposal(
        blueprint=blueprint,
        evidence_collections=[_collection(blueprint, *candidates)],
        selections=selections,
    )
    return approve_parameter_resolution_proposal(proposal, approve=True)


def test_candidate_backed_selection_cannot_silently_change_documented_value() -> None:
    blueprint = _blueprint()

    with pytest.raises(ParameterContractError, match="normalized_value exactly"):
        build_parameter_resolution_proposal(
            blueprint=blueprint,
            evidence_collections=[_collection(blueprint, _candidate())],
            selections=[
                {
                    "parameter_id": "k",
                    "candidate_id": "PEC-Q1-k-001",
                    "selected_value": 9.0,
                    "selection_rationale": "This must be rejected.",
                }
            ],
        )


def test_candidate_must_supply_every_blueprint_applicability_condition() -> None:
    blueprint = _blueprint()
    candidate = _candidate()
    candidate["conditions"] = {}

    with pytest.raises(ParameterContractError, match="required applicability conditions"):
        build_parameter_resolution_proposal(
            blueprint=blueprint,
            evidence_collections=[_collection(blueprint, candidate)],
            selections=[
                {
                    "parameter_id": "k",
                    "candidate_id": "PEC-Q1-k-001",
                    "selection_rationale": "This source lacks its required condition.",
                }
            ],
        )


def test_literature_preferred_parameter_allows_explicit_model_assumption_fallback() -> None:
    blueprint = _blueprint()
    blueprint["parameter_requests"][0]["evidence_requirement"] = "LITERATURE_PREFERRED"

    proposal = build_parameter_resolution_proposal(
        blueprint=blueprint,
        evidence_collections=[],
        selections=[
                {
                    "parameter_id": "k",
                    "candidate_id": "",
                    "provenance_status": "APPROVED_MODEL_ASSUMPTION",
                    "selected_value": 2.0,
                    "selection_rationale": "No compatible scalar was found; use a declared sensitivity baseline.",
                }
        ],
    )

    assert proposal["approval_status"] == "READY_FOR_APPROVAL"
    assert proposal["entries"][0]["provenance_status"] == "APPROVED_MODEL_ASSUMPTION"


def test_literature_required_parameter_rejects_model_assumption_fallback() -> None:
    blueprint = _blueprint()

    with pytest.raises(ParameterContractError, match="does not allow a model-assumption fallback"):
        build_parameter_resolution_proposal(
            blueprint=blueprint,
            evidence_collections=[],
            selections=[
                {
                    "parameter_id": "k",
                    "candidate_id": "",
                    "provenance_status": "APPROVED_MODEL_ASSUMPTION",
                    "selected_value": 2.0,
                    "selection_rationale": "This fallback must remain forbidden.",
                }
            ],
        )


def test_v1_blueprint_receives_and_freezes_accepted_refinement_context() -> None:
    lineage = _lineage()
    lineage.update({"version": 1, "parent_version": 0, "created_from_artifact": "revision_acceptance.json"})
    revision_context = {
        "hypothesis_delta": "Restrict the rate regime.",
        "model_delta": ["Use a revised boundary."],
        "parameter_or_boundary_delta": ["Re-evidence k at the revised temperature."],
        "expected_discriminating_result": "The trajectories separate.",
        "falsification_condition": "They remain identical.",
        "accepted_proposal_path": "hypothesis_refinement_proposal.json",
        "accepted_proposal_sha256": "b" * 64,
    }
    blueprint = _blueprint()
    blueprint["lineage"] = lineage
    blueprint["revision_context"] = revision_context
    captured: list[str] = []

    result = synthesize_quantitative_model_blueprint(
        quantitative_idea={"quantitative_idea_id": "Q1", "title": "revised decay"},
        lineage=lineage,
        revision_context=revision_context,
        llm_call=lambda prompt: captured.append(prompt)
        or "<QUANTITATIVE_MODEL_BLUEPRINT_JSON>"
        + json.dumps(blueprint)
        + "</QUANTITATIVE_MODEL_BLUEPRINT_JSON>",
    )

    assert result["revision_context"] == revision_context
    assert "Re-evidence k at the revised temperature." in captured[0]
    assert "no more than 12 parameter_requests" in captured[0]


def test_blueprint_prompt_declares_supported_model_forms() -> None:
    prompt = build_quantitative_model_blueprint_prompt(
        quantitative_idea={"quantitative_idea_id": "Q1", "title": "test"},
        lineage=_lineage(),
    )
    repair_prompt = build_quantitative_model_blueprint_repair_prompt(
        original_response="{}",
        validation_error="model blueprint model_form is unsupported",
    )

    expected_forms = "PDE, ODE, OPTIMIZATION, MONTE_CARLO, or UNSPECIFIED"
    assert expected_forms in prompt
    assert expected_forms in repair_prompt
    assert "spatial_dimension must be null or omitted" in prompt
    assert "zero spatial_dimension placeholder to null" in repair_prompt


def test_blueprint_parser_rejects_unsupported_model_form() -> None:
    blueprint = _blueprint()
    blueprint["model_form"] = "DYNAMICAL_SYSTEM"
    response = (
        "<QUANTITATIVE_MODEL_BLUEPRINT_JSON>"
        + json.dumps(blueprint)
        + "</QUANTITATIVE_MODEL_BLUEPRINT_JSON>"
    )

    with pytest.raises(QuantitativeModelBlueprintError, match="model_form is unsupported"):
        parse_quantitative_model_blueprint_response(response)


def test_blueprint_parser_normalizes_zero_dimension_for_non_pde() -> None:
    blueprint = _blueprint()
    blueprint.update({"model_form": "ODE", "spatial_dimension": 0})
    response = (
        "<QUANTITATIVE_MODEL_BLUEPRINT_JSON>"
        + json.dumps(blueprint)
        + "</QUANTITATIVE_MODEL_BLUEPRINT_JSON>"
    )

    parsed = parse_quantitative_model_blueprint_response(response)

    assert parsed["model_form"] == "ODE"
    assert parsed["spatial_dimension"] is None


def test_blueprint_parser_rejects_zero_dimension_for_pde() -> None:
    blueprint = _blueprint()
    blueprint.update(
        {
            "model_form": "PDE",
            "pde_family": "DIFFUSION_REACTION_1D",
            "spatial_dimension": 0,
        }
    )
    response = (
        "<QUANTITATIVE_MODEL_BLUEPRINT_JSON>"
        + json.dumps(blueprint)
        + "</QUANTITATIVE_MODEL_BLUEPRINT_JSON>"
    )

    with pytest.raises(QuantitativeModelBlueprintError, match="spatial_dimension must be at least 1"):
        parse_quantitative_model_blueprint_response(response)


def test_blueprint_repairs_scalar_condition_lists_once() -> None:
    blueprint = _blueprint()
    malformed = json.loads(json.dumps(blueprint))
    malformed["parameter_requests"][0]["required_conditions"] = "temperature_K"
    responses = [
        "<QUANTITATIVE_MODEL_BLUEPRINT_JSON>"
        + json.dumps(malformed)
        + "</QUANTITATIVE_MODEL_BLUEPRINT_JSON>",
        "<QUANTITATIVE_MODEL_BLUEPRINT_JSON>"
        + json.dumps(blueprint)
        + "</QUANTITATIVE_MODEL_BLUEPRINT_JSON>",
    ]

    result = synthesize_quantitative_model_blueprint(
        quantitative_idea={"quantitative_idea_id": "Q1", "title": "repair test"},
        lineage=_lineage(),
        revision_context={},
        llm_call=lambda _prompt: responses.pop(0),
    )

    assert result["parameter_requests"][0]["required_conditions"] == ["temperature_K"]
    assert len(responses) == 0


def test_blueprint_repair_prompt_preserves_tagged_string_response() -> None:
    rejected = '<QUANTITATIVE_MODEL_BLUEPRINT_JSON>{"schema_version":"wrong"}</QUANTITATIVE_MODEL_BLUEPRINT_JSON>'

    prompt = build_quantitative_model_blueprint_repair_prompt(
        original_response=rejected,
        validation_error="unsupported quantitative model blueprint schema",
    )

    assert rejected in prompt


def test_parameter_set_identity_changes_with_evidenced_value() -> None:
    blueprint = _blueprint()
    set_a = _approved_set()
    proposal_b = build_parameter_resolution_proposal(
        blueprint=blueprint,
        evidence_collections=[_collection(blueprint, _candidate(value=3.0))],
        selections=[
            {
                "parameter_id": "k",
                "candidate_id": "PEC-Q1-k-001",
                "selection_rationale": "Use the separately documented measurement.",
            }
        ],
    )
    set_b = approve_parameter_resolution_proposal(proposal_b, approve=True)

    assert set_a["parameter_set_identity"] != set_b["parameter_set_identity"]
    assert normalize_approved_parameter_set(set_b)["entries"][0]["selected_value"] == 3.0


def test_evidence_bound_plan_rejects_material_property_override() -> None:
    parameter_set = _approved_set(scenario_role=True)
    mathir = {
        "schema_version": "mathir_v1",
        "system_type": "ODE_IVP",
        "states": [{"id": "x", "initial": 1.0}],
        "parameters": {"k": 2.0, "forcing": 0.0},
        "derivatives": {
            "x": {
                "op": "add",
                "args": [
                    {
                        "op": "mul",
                        "args": [
                            {"op": "neg", "args": [{"op": "variable", "name": "k"}]},
                            {"op": "variable", "name": "x"},
                        ],
                    },
                    {"op": "variable", "name": "forcing"},
                ],
            }
        },
        "time_span": [0.0, 1.0],
        "solver_options": {"max_step": 0.1},
    }
    identity = {
        "science_run_id": "run-parameter",
        "quantitative_idea_id": "Q1",
        "version": 0,
        "parameter_set_identity": parameter_set["parameter_set_identity"],
    }
    manifest = {"path": "approved_parameter_set_manifest.json", "sha256": "a" * 64}

    with pytest.raises(SimulationRunPlanError, match="SCENARIO_INPUT"):
        build_simulation_run_plan(
            model_identity=identity,
            mathir=mathir,
            scenarios=[{"scenario_id": "invalid", "parameter_overrides": {"k": 1.5}}],
            parameter_set=parameter_set,
            parameter_set_manifest=manifest,
        )

    plan = build_simulation_run_plan(
        model_identity=identity,
        mathir=mathir,
        scenarios=[{"scenario_id": "forcing", "parameter_overrides": {"forcing": 0.25}}],
        parameter_set=parameter_set,
        parameter_set_manifest=manifest,
    )
    assert plan["parameter_provenance"]["parameter_set_identity"] == parameter_set["parameter_set_identity"]


def test_discovery_and_extraction_keep_secrets_and_metadata_out_of_evidence(tmp_path: Path) -> None:
    blueprint = normalize_model_blueprint(_blueprint())
    secret = "super-secret-key"

    def fake_json_get(url: str, **_kwargs: object) -> object:
        if url.endswith("/works"):
            return {
                "results": [
                    {
                        "id": "W123",
                        "title": "Measured coefficient",
                        "doi": "https://doi.org/10.1000/example",
                        "publication_year": 2025,
                        "best_oa_location": {
                            "is_oa": True,
                            "pdf_url": "https://example.org/paper.pdf",
                        },
                    }
                ]
            }
        if url.endswith("/paper/search"):
            return {
                "data": [
                    {
                        "paperId": "S123",
                        "title": "Measured coefficient",
                        "externalIds": {"DOI": "10.1000/example"},
                        "year": 2025,
                    }
                ]
            }
        if "unpaywall" in url:
            return {"best_oa_location": {"url_for_pdf": "https://example.org/paper.pdf"}}
        raise AssertionError(url)

    settings = ParameterEvidenceSettings(
        openalex_api_key=secret,
        semantic_scholar_api_key=secret,
        unpaywall_email="researcher@example.org",
    )
    discovery = discover_parameter_literature(
        blueprint=blueprint,
        providers=AcademicMetadataProviders(settings, json_get=fake_json_get),
    )
    serialized_discovery = json.dumps(discovery)
    assert secret not in serialized_discovery
    assert "normalized_value" not in serialized_discovery
    assert discovery["papers"][0]["cross_validated"] is True

    class Response:
        status_code = 206
        headers = {"Content-Type": "application/pdf"}
        content = b"%PDF-parameter-evidence"

        def close(self) -> None:
            return None

    class Client:
        def get(self, *_args: object, **_kwargs: object) -> Response:
            return Response()

    fulltext = fetch_open_access_fulltexts(
        blueprint=blueprint,
        discovery=discovery,
        output_directory=tmp_path / "fulltext",
        settings=settings,
        http_client=Client(),
    )
    assert fulltext["documents"][0]["evidence_status"] == "EXTRACTED_FULLTEXT"

    source_path = tmp_path / "source.txt"
    source_path.write_text("At 300 K, k = 2.0 s^-1 was measured in Table 1.", encoding="utf-8")
    source_document = {
        "document_id": "UPD-001",
        "path": str(source_path),
        "title": "User measurement note",
        "doi": "",
        "year": 2025,
        "discovery_sources": ["user_provided"],
        "cross_validated": False,
        "evidence_status": "USER_PROVIDED",
    }
    response = {
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
                    "table_or_figure": "Table 1",
                    "page": None,
                    "quoted_text": "At 300 K, k = 2.0 s^-1 was measured in Table 1.",
                },
                "conditions": {"temperature_K": 300.0},
                "uncertainty": {},
                "transformation": {"applied": False, "formula": ""},
            }
        ]
    }
    collection = extract_parameter_evidence_candidates(
        blueprint=blueprint,
        source_document=source_document,
        llm_call=lambda _prompt: "<QUANTITATIVE_PARAMETER_EVIDENCE_JSON>"
        + json.dumps(response)
        + "</QUANTITATIVE_PARAMETER_EVIDENCE_JSON>",
    )
    assert collection["candidates"][0]["candidate_id"] == "PEC-Q1-k-001"
    assert collection["candidates"][0]["source"]["document_id"] == "UPD-001"
