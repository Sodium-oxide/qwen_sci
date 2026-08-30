from __future__ import annotations

import json
import os
import sys
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SURVEY_AGENT_ROOT = os.path.join(PROJECT_ROOT, "src", "agents", "survey_agent")
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, SURVEY_AGENT_ROOT)

from modules.survey_generator import SurveyGenerator
from src.pipeline.multimodal_evidence.survey_integration import (
    LOCAL_DATA_OBSERVATION,
    build_multimodal_survey_projection,
    enrich_multimodal_evidence,
)
from src.pipeline.survey_evidence_plan import (
    EVIDENCE_BACKED_SYNTHESIS,
    SURVEY_EVIDENCE_PLAN_SCHEMA_VERSION,
    build_survey_evidence_plan,
)
from src.pipeline.survey_handoff_persistence import publish_survey_run_artifacts
from src.pipeline.survey_idea_loader import SurveyIdeaLoadError, load_survey_idea_context


def _runtime_evidence() -> dict:
    return {
        "schema_version": "multimodal_evidence_v1",
        "dataset_id": "dataset-A",
        "perception": {
            "mode": "remote_perception",
            "provider": "qwen",
            "model": "qwen3-vl-plus",
        },
        "input_summary": {
            "validated_record_count": 2,
            "selected_record_count": 1,
            "successful_local_analysis_count": 1,
            "available_by_modality": {"image": 2},
            "selected_by_modality": {"image": 1},
        },
        "native_findings": [{"record_id": "record-1", "status": "success", "metrics": {"width": 20}}],
        "observations": [{
            "observation_id": "mme:obs:001",
            "record_ids": ["record-1"],
            "modality": "image",
            "finding": "A bounded local pattern is visible in the selected supplied-data preview.",
            "candidate_explanation": "a tentative interface-related explanation",
            "alternative_explanations": ["a measurement or preparation artifact"],
            "discriminating_prediction": "An independent calibrated measurement should separate the explanations.",
            "falsifier": "The pattern disappears in an independently calibrated comparison.",
            "claim_limits": "The observation is restricted to the selected supplied-data sample.",
            "confidence": "low",
            "focus": "measurement",
        }],
        "claims": [{
            "claim_id": "mme:claim:001",
            "observation_id": "mme:obs:001",
            "record_ids": ["record-1"],
            "local_data_statement": "In the representative preview of provided data record record-1, a bounded local pattern was observed.",
            "candidate_explanation": "a tentative interface-related explanation",
            "alternative_explanations": ["a measurement or preparation artifact"],
            "discriminating_prediction": "An independent calibrated measurement should separate the explanations.",
            "falsifier": "The pattern disappears in an independently calibrated comparison.",
            "claim_limits": "The observation is restricted to the selected supplied-data sample and cannot distinguish competing explanations.",
            "confidence": "low",
            "focus": "measurement",
        }],
        "limitations": ["The evidence is a bounded local observation."],
    }


def _enriched_evidence() -> dict:
    return enrich_multimodal_evidence(
        _runtime_evidence(),
        data_anchored_subhypothesis_artifact={
            "metadata_by_subhypothesis": {
                "MM_SH_01": {
                    "analysis_priority": "DATA_ANCHORED_PRIMARY",
                    "claim_ids": ["mme:claim:001"],
                    "observation_ids": ["mme:obs:001"],
                    "question_kind": "MEASUREMENT_VALIDITY",
                }
            },
            "query_variant_bindings": [
                {
                    "sub_hypothesis_id": "MM_SH_01",
                    "slot_name": "construct",
                    "query_variant_id": "support_01",
                    "epistemic_role": "support",
                    "evidence_mode": "benchmark",
                    "required_result": "A comparable validation result.",
                    "claim_id": "mme:claim:001",
                },
                {
                    "sub_hypothesis_id": "MM_SH_01",
                    "slot_name": "construct",
                    "query_variant_id": "counter_01",
                    "epistemic_role": "measurement_confound",
                    "evidence_mode": "benchmark",
                    "required_result": "A calibration-related alternative.",
                    "claim_id": "mme:claim:001",
                },
            ],
        },
    )


def _project_context() -> dict:
    return {
        "input_fingerprint": "context-1",
        "domain": "Materials Science",
        "research_identity": {"core_entities": ["sample"]},
        "discovery_taxonomy": {"status": "unresolved", "requires_human_confirmation": True},
    }


def _evidence_plan() -> dict:
    return {
        "schema_version": SURVEY_EVIDENCE_PLAN_SCHEMA_VERSION,
        "project_id": "sci_run_1",
        "project_context_fingerprint": "context-1",
        "evidence_bounded_writing": True,
        "subhypotheses": [{
            "sub_hypothesis_id": "SH1",
            "summary": "A bounded question.",
            "required_slots": ["direct_observation"],
            "covered_slots": [],
            "background_only_slots": [],
            "missing_slots": ["direct_observation"],
            "slot_support": {"direct_observation": {
                "expected_evidence_role": "DIRECT_OBSERVATION",
                "evidence_paper_ids": [],
                "background_paper_ids": [],
                "qualified_paper_ids": [],
                "qualified_paper_constraints": {},
            }},
            "relevant_clusters": [],
            "conclusion_admissibility": {"blockers": []},
            "limitations": {"blockers": []},
            "allowed_claim_modes": ["EVIDENCE_GAP_REPORT"],
            "forbidden_paper_ids": [],
            "direct_writing_blocked_paper_ids": [],
        }],
    }


def _publish(tmp_path: Path, *, multimodal_evidence: dict | None = None) -> dict:
    return publish_survey_run_artifacts(
        base_dir=tmp_path,
        topic="A bounded materials question",
        survey_run_id="20260830-130000-000001",
        final_survey="Survey body",
        survey_payload={"topic": "A bounded materials question"},
        project_context=_project_context(),
        evidence_plan=_evidence_plan(),
        claim_traceability={"claims": []},
        multimodal_evidence=multimodal_evidence,
    )


def test_survey_plan_keeps_legacy_shape_without_evidence_and_prioritizes_data_sh() -> None:
    provenance = {
        "schema_version": "sh_graph_provenance_v1",
        "project_id": "sci_project",
        "project_context_fingerprint": "context-A",
        "paper_annotations": {},
        "graph_expansion_records": [],
    }
    ledger = {
        "schema_version": "evidence_coverage_ledger_v1",
        "project_id": "sci_project",
        "project_context_fingerprint": "context-A",
        "subhypotheses": [{
            "sub_hypothesis_id": "MM_SH_01",
            "question": "Does the provided measurement require independent validation?",
            "question_kind": "MEASUREMENT_VALIDITY",
            "required_slots": ["construct"],
            "slot_ledger": {"construct": {
                "task_id": "task.construct",
                "expected_evidence_role": "METHOD_OR_MEASUREMENT",
                "minimum_evidence": "A validation study.",
                "admission_rule": "The study validates the measurement.",
                "covered_by": [], "background_only_by": [], "scope_rejections": [],
            }},
            "covered_slots": [], "background_only_slots": [], "missing_slots": ["construct"],
            "conclusion_admissibility": {"admissible": False, "blockers": ["missing"]},
        }],
    }
    clusters = {
        "schema_version": "sh_cluster_coverage_projection_v1",
        "project_id": "sci_project",
        "project_context_fingerprint": "context-A",
        "clusters": [],
    }
    contracts = [{
        "sub_hypothesis_id": "MM_SH_01",
        "question_kind": "MEASUREMENT_VALIDITY",
        "required_slots": ["construct"],
        "research_role": "BASELINE_ENABLER",
        "challenge_target": "the supplied local measurement",
    }]
    legacy = build_survey_evidence_plan(
        provenance_artifact=provenance,
        coverage_ledger=ledger,
        cluster_coverage_artifact=clusters,
        subhypothesis_contracts=contracts,
    )
    enriched = build_survey_evidence_plan(
        provenance_artifact=provenance,
        coverage_ledger=ledger,
        cluster_coverage_artifact=clusters,
        subhypothesis_contracts=contracts,
        multimodal_evidence=_enriched_evidence(),
    )

    assert "multimodal_evidence_projection" not in legacy
    assert "must_cover" not in legacy["subhypotheses"][0]
    entry = enriched["subhypotheses"][0]
    assert entry["must_cover"] is True
    assert entry["analysis_priority"] == "DATA_ANCHORED_PRIMARY"
    assert LOCAL_DATA_OBSERVATION in entry["allowed_claim_modes"]
    assert entry["multimodal_projection"]["claims"][0]["literature_reconciliation"]["status"] == "unresolved"

    mismatched_ledger = deepcopy(ledger)
    mismatched_contracts = deepcopy(contracts)
    mismatched_ledger["subhypotheses"][0]["sub_hypothesis_id"] = "SH1"
    mismatched_contracts[0]["sub_hypothesis_id"] = "SH1"
    with pytest.raises(ValueError, match="absent from the final coverage ledger"):
        build_survey_evidence_plan(
            provenance_artifact=provenance,
            coverage_ledger=mismatched_ledger,
            cluster_coverage_artifact=clusters,
            subhypothesis_contracts=mismatched_contracts,
            multimodal_evidence=_enriched_evidence(),
        )


def test_sidecar_publication_handoff_and_loader_are_bounded_and_verified(tmp_path: Path) -> None:
    published = _publish(tmp_path, multimodal_evidence=_enriched_evidence())
    manifest = json.loads(Path(published["manifest_path"]).read_text(encoding="utf-8"))
    handoff = json.loads(Path(published["idea_handoff_path"]).read_text(encoding="utf-8"))

    assert manifest["artifacts"]["multimodal_evidence"]["path"] == "multimodal_evidence.json"
    assert Path(published["artifacts"]["multimodal_evidence"]).is_file()
    assert handoff["source_artifacts"]["multimodal_evidence"] == "multimodal_evidence.json"
    anchor = next(item for item in handoff["anchors"] if item["anchor_type"] == "multimodal_observation")
    assert anchor["source_pointer"] == {
        "artifact": "multimodal_evidence.json",
        "json_pointer": "/observations/0",
    }
    assert {role["expected_role"] for role in handoff["evidence_roles"]}.issuperset(
        {"DIRECT_OBSERVATION", "METHOD_OR_MEASUREMENT"}
    )

    context = load_survey_idea_context(published["manifest_path"])
    payload = context.to_payload()
    assert payload["multimodal_evidence_projection"]["data_anchored_subhypotheses"][0]["must_cover"] is True
    assert "source_path" not in json.dumps(payload["multimodal_evidence_projection"])
    assert "base64" not in json.dumps(payload["multimodal_evidence_projection"])

    Path(published["artifacts"]["multimodal_evidence"]).write_text("{}", encoding="utf-8")
    with pytest.raises(SurveyIdeaLoadError, match="verification failed"):
        load_survey_idea_context(published["manifest_path"])


def test_loader_omits_projection_without_sidecar_and_trace_accepts_only_bounded_observation() -> None:
    projection = build_multimodal_survey_projection(_enriched_evidence())
    assert projection is not None
    generator = object.__new__(SurveyGenerator)
    generator.use_title_in_draft = False
    generator.survey_evidence_plan = {
        "schema_version": SURVEY_EVIDENCE_PLAN_SCHEMA_VERSION,
        "evidence_bounded_writing": True,
        "subhypotheses": [
            {
                "sub_hypothesis_id": "MM_SH_01",
                "analysis_priority": "DATA_ANCHORED_PRIMARY",
                "must_cover": True,
                "allowed_claim_modes": [LOCAL_DATA_OBSERVATION],
                "slot_support": {},
                "missing_slots": [],
                "background_only_slots": [],
                "multimodal_projection": projection["data_anchored_subhypotheses"][0],
            },
            {
                "sub_hypothesis_id": "SH1",
                "allowed_claim_modes": [EVIDENCE_BACKED_SYNTHESIS],
                "slot_support": {"direct": {
                    "expected_evidence_role": "DIRECT_OBSERVATION",
                    "evidence_paper_ids": ["W1"],
                    "background_paper_ids": [],
                    "qualified_paper_ids": [],
                }},
                "missing_slots": [],
                "background_only_slots": [],
                "forbidden_paper_ids": [],
                "paper_role_constraints": {},
            },
        ],
    }
    outline_projection = generator._outline_evidence_plan_prompt_projection([])
    outline_data_sh = outline_projection["subhypotheses"][0]
    assert outline_data_sh["sub_hypothesis_id"] == "MM_SH_01"
    assert outline_data_sh["must_cover"] is True
    assert LOCAL_DATA_OBSERVATION in outline_data_sh["allowed_claim_modes"]
    assert outline_data_sh["multimodal_projection"]["observations"][0]["observation_id"] == "mme:obs:001"
    assert outline_projection["writing_rules"]["data_anchored_subhypotheses_must_cover"] is True
    bounded = (
        "In the provided data, this bounded local observation is compatible with a tentative "
        "explanation and cannot distinguish alternatives."
    )
    observation_claim = [{
        "claim_text": bounded,
        "sub_hypothesis_ids": ["MM_SH_01"],
        "claim_mode": LOCAL_DATA_OBSERVATION,
        "evidence_paths": [{
            "source_type": "multimodal_observation",
            "sub_hypothesis_id": "MM_SH_01",
            "observation_id": "mme:obs:001",
        }],
    }]
    assert generator._validate_claim_trace(bounded, observation_claim) == []

    causal = bounded.replace("is compatible with", "proves")
    assert any(
        "causal, universal, or overstrong" in error
        for error in generator._validate_claim_trace(causal, [{**observation_claim[0], "claim_text": causal}])
    )
    legacy_paper = "The direct result is reported <Paper ID: W1>."
    assert generator._validate_claim_trace(legacy_paper, [{
        "claim_text": legacy_paper,
        "sub_hypothesis_ids": ["SH1"],
        "claim_mode": EVIDENCE_BACKED_SYNTHESIS,
        "evidence_paths": [{
            "sub_hypothesis_id": "SH1",
            "slot_name": "direct",
            "paper_id": "W1",
            "support_kind": "DIRECT_LEDGER_EVIDENCE",
            "evidence_role": "DIRECT_OBSERVATION",
        }],
    }]) == []

    spoofed_path = {
        **observation_claim[0],
        "claim_text": bounded.replace(
            "cannot distinguish alternatives.", "cannot distinguish alternatives but applies to every sample."
        ),
        "evidence_paths": [{
            **observation_claim[0]["evidence_paths"][0],
            "paper_ids": ["W1"],
        }],
    }
    spoofed_errors = generator._validate_claim_trace(
        spoofed_path["claim_text"], [spoofed_path]
    )
    assert any("use only source_type, SH, and observation_id" in error for error in spoofed_errors)
    assert any("causal, universal, or overstrong" in error for error in spoofed_errors)

    generator.config = SimpleNamespace(multimodal_evidence={"enabled": False})
    generator.survey_multimodal_evidence = _enriched_evidence()
    assert generator._survey_runtime_multimodal_evidence(None) is None
    assert generator.survey_multimodal_evidence == {}
