from __future__ import annotations

from types import SimpleNamespace

from src.agents.survey_agent.modules.work_collector import WorkCollector
from src.pipeline.multimodal_evidence.data_sh_compiler import (
    DATA_ANCHORED_PRIORITY,
    compile_data_anchored_subhypotheses,
)
from src.pipeline.research_identity import build_project_research_context
from src.pipeline.retrieval_lanes import build_subhypothesis_retrieval_plan
from src.pipeline.subhypothesis_decomposition import subhypothesis_decomposition_fingerprint


def _context() -> dict:
    return build_project_research_context(
        original_topic="machine learning for crop disease diagnosis",
        declared_domain="agriculture",
        objective="Compare image models for crop disease diagnosis under field conditions",
        use_llm=False,
    )


def _claim() -> dict:
    return {
        "claim_id": "mme:claim:001",
        "observation_id": "mme:obs:001",
        "record_ids": ["image-1"],
        "local_data_statement": "In the representative preview of the provided data record(s) image-1, the bounded observation was: a color gradient is visible. This is a local data statement, not an established scientific result.",
        "candidate_explanation": "disease severity variation",
        "alternative_explanations": ["illumination variation"],
        "discriminating_prediction": "The pattern persists after calibrated imaging under matched conditions.",
        "falsifier": "The pattern disappears after calibrated imaging under matched conditions.",
        "claim_limits": "One representative preview cannot establish a general relation.",
        "confidence": "low",
        "focus": "mechanism",
    }


def _runtime_evidence() -> dict:
    return {
        "schema_version": "multimodal_evidence_v1",
        "dataset_id": "demo",
        "perception": {"mode": "remote_perception", "provider": "qwen", "model": "qwen3-vl-plus"},
        "native_findings": [{"record_id": "image-1", "modality": "image", "status": "success", "metrics": {}}],
        "observations": [],
        "claims": [_claim()],
        "limitations": [],
    }


def test_data_anchored_claim_compiles_to_valid_sh_with_support_and_counter_bindings() -> None:
    context = _context()
    artifact = compile_data_anchored_subhypotheses([_claim()], context)

    assert [item["sub_hypothesis_id"] for item in artifact["subhypotheses"]] == ["MM_SH_01"]
    assert artifact["metadata_by_subhypothesis"]["MM_SH_01"]["analysis_priority"] == DATA_ANCHORED_PRIORITY
    roles = {item["epistemic_role"] for item in artifact["query_variant_bindings"]}
    assert "support" in roles
    assert roles & {"counter", "alternative_explanation", "measurement_confound"}

    plan = build_subhypothesis_retrieval_plan(
        context,
        artifact["subhypotheses"],
        query_variant_bindings=artifact["query_variant_bindings"],
        subhypothesis_metadata=artifact["metadata_by_subhypothesis"],
    )
    compiled = plan["subhypotheses"][0]
    assert compiled["validation"]["valid"] is True
    bound_lanes = [lane for lane in compiled["slot_query_lanes"] if "epistemic_role" in lane]
    assert {lane["epistemic_role"] for lane in bound_lanes} >= {"support", "alternative_explanation"}
    assert plan["subhypothesis_metadata"]["MM_SH_01"]["claim_ids"] == ["mme:claim:001"]


def test_data_sh_question_kind_follows_observation_focus() -> None:
    context = _context()
    expected_kinds = {
        "mechanism": "MECHANISM_EXPLANATION",
        "measurement": "MEASUREMENT_VALIDITY",
        "boundary": "BOUNDARY_HETEROGENEITY",
        "contradiction": "REPLICATION_CONTRADICTION",
        "theory": "THEORY_MODEL_VALIDITY",
    }

    for focus, expected_kind in expected_kinds.items():
        claim = {**_claim(), "focus": focus}
        artifact = compile_data_anchored_subhypotheses([claim], context)
        plan = build_subhypothesis_retrieval_plan(
            context,
            artifact["subhypotheses"],
            query_variant_bindings=artifact["query_variant_bindings"],
        )
        assert artifact["subhypotheses"][0]["question_kind"] == expected_kind
        assert plan["subhypotheses"][0]["validation"]["valid"] is True


def test_unbound_retrieval_plan_keeps_legacy_lane_shape() -> None:
    context = _context()
    artifact = compile_data_anchored_subhypotheses([_claim()], context)
    plan = build_subhypothesis_retrieval_plan(context, artifact["subhypotheses"])

    assert "query_variant_bindings" not in plan
    assert all(
        "epistemic_role" not in lane
        for lane in plan["subhypotheses"][0]["slot_query_lanes"]
    )


def test_work_collector_places_data_sh_before_manual_and_auto_generation() -> None:
    context = _context()
    collector = object.__new__(WorkCollector)
    collector.config = SimpleNamespace(
        multimodal_evidence={
            "enabled": True,
            "allow_remote_perception": True,
            "input_spec": {"records": [{"record_id": "image-1"}]},
            "runtime_evidence": _runtime_evidence(),
            "max_data_anchored_sh": 3,
        },
        BasicInfo=SimpleNamespace(subhypotheses=[], subhypothesis_decomposition={}),
        ModuleInfo=SimpleNamespace(WorkCollector=SimpleNamespace(auto_decompose_subhypotheses=False, enable_arxiv_discovery=False)),
    )
    collector.logger = SimpleNamespace(info=lambda *_args, **_kwargs: None)

    plan, valid = collector._build_configured_subhypothesis_plan(context["original_topic"], context)

    assert [item["sub_hypothesis_id"] for item in valid] == ["MM_SH_01"]
    assert plan["subhypothesis_metadata"]["MM_SH_01"]["analysis_priority"] == DATA_ANCHORED_PRIORITY
    assert any(
        lane.get("epistemic_role") == "support"
        for lane in valid[0]["slot_query_lanes"]
    )


def test_work_collector_ignores_runtime_evidence_without_explicit_input_gate() -> None:
    context = _context()
    collector = object.__new__(WorkCollector)
    collector.config = SimpleNamespace(
        multimodal_evidence={"enabled": False, "runtime_evidence": _runtime_evidence()},
        BasicInfo=SimpleNamespace(subhypotheses=[], subhypothesis_decomposition={}),
        ModuleInfo=SimpleNamespace(WorkCollector=SimpleNamespace(auto_decompose_subhypotheses=False)),
    )

    assert collector._load_data_anchored_subhypotheses(context)["subhypotheses"] == []


def test_automatic_decomposition_fingerprint_changes_with_safe_observation_projection() -> None:
    context = _context()
    artifact = compile_data_anchored_subhypotheses([_claim()], context)
    evidence = _runtime_evidence()
    first = subhypothesis_decomposition_fingerprint(
        context,
        reserved_subhypotheses=artifact["subhypotheses"],
        observation_projection=evidence,
    )
    evidence["claims"][0]["candidate_explanation"] = "measurement artifact"
    second = subhypothesis_decomposition_fingerprint(
        context,
        reserved_subhypotheses=artifact["subhypotheses"],
        observation_projection=evidence,
    )

    assert first != second
