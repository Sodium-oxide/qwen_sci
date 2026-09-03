from __future__ import annotations

from types import SimpleNamespace

from src.agents.survey_agent.modules.work_collector import WorkCollector
from src.pipeline.multimodal_evidence.retrieval_profile import (
    RETRIEVAL_PROFILE_VERSION,
    build_profile_query_variants,
    build_retrieval_profile,
)
from src.pipeline.retrieval_lanes import build_query_lanes
from src.pipeline.retrieval_lanes import _slot_query_variants


def _claim_and_context(modality: str) -> tuple[dict, dict]:
    claims = {
        "climate": {
            "candidate_explanation": "persistent radiative forcing",
            "alternative_explanations": ["seasonal sampling artifact"],
            "local_data_statement": "The map shows a regional trend in surface temperature.",
            "discriminating_prediction": "The trend remains in an independent reanalysis.",
            "falsifier": "The trend disappears with an alternate sampling window.",
        },
        "microscopy": {
            "candidate_explanation": "cellular stress response",
            "alternative_explanations": ["illumination artifact"],
            "local_data_statement": "The microscopy image shows a red fluorescence gradient.",
            "discriminating_prediction": "The gradient persists after calibrated imaging.",
            "falsifier": "The gradient disappears under matched illumination.",
        },
        "materials": {
            "candidate_explanation": "strain hardening response",
            "alternative_explanations": ["grip compliance artifact"],
            "local_data_statement": "The stress-strain curve bends after plastic onset.",
            "discriminating_prediction": "The bend repeats across independent specimens.",
            "falsifier": "The bend vanishes after machine compliance correction.",
        },
        "chemistry": {
            "candidate_explanation": "catalytic conversion pathway",
            "alternative_explanations": ["assay interference"],
            "local_data_statement": "The assay plot shows concentration-dependent conversion.",
            "discriminating_prediction": "The conversion agrees with an orthogonal assay.",
            "falsifier": "The signal disappears after blank subtraction.",
        },
    }[modality]
    claim = {
        "claim_id": f"claim-{modality}",
        "observation_id": f"observation-{modality}",
        "claim_limits": "A supplied preview is local evidence and cannot establish universality.",
        **claims,
    }
    context = {
        "original_topic": {
            "climate": "surface temperature trends",
            "microscopy": "fluorescence microscopy",
            "materials": "mechanical response of alloys",
            "chemistry": "catalytic assay kinetics",
        }[modality],
        "original_objective": "compare competing explanations using independent measurements",
        "declared_domain": modality,
        "core_entities": ["CHFD", "NHFD", "GPP", "SIF"],
        "domain_context": {"retrieval_terms": []},
        "retrieval_synonyms": [],
        "research_brief": (
            "The user supplied three figures as multimodal evidence. "
            "Figure 2 shows GPP and SIF panels for a separate outcome."
        ),
    }
    return claim, context


def test_profile_is_domain_independent_and_drops_workflow_labels() -> None:
    for modality in ("climate", "microscopy", "materials", "chemistry"):
        claim, context = _claim_and_context(modality)
        profile = build_retrieval_profile(claim, context)
        assert profile["profile_version"] == RETRIEVAL_PROFILE_VERSION
        assert profile["phenomenon_terms"]
        assert profile["outcome_terms"]
        assert all(
            label not in " ".join(profile["all_anchor_terms"]).casefold()
            for label in ("observed data pattern", "mechanism evidence", "multimodal measurement")
        )
        if modality == "climate":
            profile_text = " ".join(profile["all_anchor_terms"]).casefold()
            assert "gpp" not in profile_text
            assert "sif" not in profile_text
        variants = build_profile_query_variants(profile, role="mechanism")
        assert variants
        for variant in variants:
            query = " ".join(variant["query_terms"])
            assert len(query) <= 240
            assert len(query.split()) <= 12
            assert "evidence" not in query.casefold()
            assert not any(
                token in query.casefold().split()
                for token in ("preview", "contains", "figure", "figures", "panel", "multimodal")
            )


def test_visual_narrative_and_panel_noise_are_removed_from_provider_query() -> None:
    claim, context = _claim_and_context("climate")
    claim["local_data_statement"] = (
        "The preview contains a regional temperature gradient."
    )
    profile = build_retrieval_profile(claim, context)
    variants = build_profile_query_variants(profile, role="construct")
    query = " ".join(variants[0]["query_terms"])
    assert "preview" not in query.casefold()
    assert "contains" not in query.casefold()
    assert "gpp" not in query.casefold()
    assert "sif" not in query.casefold()

    lanes = build_query_lanes(
        {"original_topic": "surface temperature trends", "core_entities": []},
        query="The preview shows panel b) regional temperature gradients",
        evidence_mode="empirical",
        include_arxiv=False,
    )
    lane_query = lanes["query_lanes"][0]["query"]
    assert "preview" not in lane_query.casefold()
    assert "panel" not in lane_query.casefold()
    assert "b)" not in lane_query.casefold()


def test_compiler_preserves_scientific_compound_phrases() -> None:
    claim, context = _claim_and_context("materials")
    profile = build_retrieval_profile(claim, context)
    variants = build_profile_query_variants(profile, role="construct")
    query = " ".join(variants[0]["query_terms"])
    assert "stress-strain" in query
    assert "strain hardening" in query
    assert "stress-strain curve" not in query or "stress-strain" in query


def test_evidence_mode_is_metadata_not_a_query_suffix() -> None:
    lanes = build_query_lanes(
        {"original_topic": "fluorescence microscopy", "core_entities": []},
        query="cellular stress response red fluorescence",
        evidence_mode="mechanism",
        include_arxiv=False,
    )
    assert all(item["query"] == "cellular stress response red fluorescence" for item in lanes["query_lanes"])
    assert all(item["evidence_mode"] == "mechanism" for item in lanes["query_lanes"])
    assert not any(item["lane"] == "evidence_mode" for item in lanes["query_lanes"])


def test_legacy_long_explanation_is_compacted_before_provider_submission() -> None:
    variants = _slot_query_variants(
        {
            "retrieval_concepts": [],
            "retrieval_query_variants": [
                {
                    "variant_id": "baseline",
                    "purpose": "legacy recovery",
                    "query_terms": [
                        "The observed pattern may reflect a complex explanation involving several interacting variables and untested assumptions",
                        "stress-strain curve",
                    ],
                }
            ],
        },
        {"research_object": ["mechanical response"]},
        evidence_role="MECHANISTIC_EVIDENCE",
        question="Which published evidence supports the explanation?",
    )
    query = variants[0]["query"]
    assert len(query.split()) <= 12
    assert "observed pattern" not in query.casefold()
    assert "stress-strain curve" in query


def test_semantic_scholar_fallback_uses_short_variant_terms() -> None:
    collector = object.__new__(WorkCollector)
    collector.data_manager = SimpleNamespace(semantic_scholar_api=object())
    captured: list[dict] = []
    collector._execute_slot_recovery_lane = lambda lane: (captured.append(dict(lane)) or (lane, []))
    result = collector._execute_slot_semantic_scholar_fallback(
        [
            {
                "lane": "broad_anchor",
                "lane_id": "slot.broad",
                "query": "a very long model-generated explanation that should never be sent to a provider",
                "query_variant_terms": ["stress-strain curve", "strain hardening", "independent specimens"],
            }
        ]
    )
    assert result is not None
    assert captured[0]["query"] == "stress-strain curve strain hardening independent specimens"
    assert captured[0]["fallback_query_source"] == "query_variant_terms"


def test_provider_rate_limit_is_not_a_valid_empty_result() -> None:
    class RateLimitedAPI:
        def search_papers(self, **_kwargs):
            raise RuntimeError("HTTP 429 too many requests")

    collector = object.__new__(WorkCollector)
    collector.data_manager = SimpleNamespace(semantic_scholar_api=RateLimitedAPI())
    collector.logger = SimpleNamespace(warning=lambda *_args, **_kwargs: None)
    papers, successful, status = collector._execute_query_lane_with_status(
        {"provider": "semantic_scholar", "query": "cellular stress response"}
    )
    assert papers == []
    assert successful is False
    assert status == "rate_limited"
