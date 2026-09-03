from __future__ import annotations

import json
from pathlib import Path

from src.pipeline.survey_gap_candidates import (
    SURVEY_GAP_CANDIDATE_SCHEMA,
    build_section_aware_paper_input,
    extract_paper_limitation_candidates,
    extract_survey_gap_candidates,
    validate_gap_candidate_payload,
)
from src.pipeline.survey_gap_adjudication import (
    adjudicate_gap_candidates,
    build_coverage_matrix,
    build_gap_coverage_artifact,
    deduplicate_gap_candidates,
    detect_gap_contradictions,
)
from src.pipeline.survey_idea_handoff import canonical_fingerprint


FIXTURE_DIR = Path(__file__).resolve().parents[1] / "src" / "agents" / "survey_agent" / "outputs" / "20260826-002857-396164"


def _ledger() -> dict:
    return {
        "project_id": "project-1",
        "survey_run_id": "run-1",
        "project_context_fingerprint": "context-1",
        "gaps": [
            {
                "gap_id": "gap:1",
                "subhypothesis_id": "SH1",
                "gap_kind": "missing_boundary_condition",
                "target_slot": "validity_domain",
                "statement": "The validity domain is not specified.",
            }
        ],
        "profile_resolution": {"status": "unresolved", "profile_id_hint": ""},
    }


def test_survey_prose_extractor_normalizes_mock_llm_candidate() -> None:
    calls: list[str] = []

    def mock_llm(prompt: str) -> dict:
        calls.append(prompt)
        return {
            "candidates": [
                {
                    "subhypothesis_id": "SH1",
                    "gap_kind": "missing_boundary_condition",
                    "target_slot": "validity_domain",
                    "statement": "The validity regime for the observed relation is not established.",
                    "rationale": "The survey identifies conflicting regimes.",
                    "confidence": 0.81,
                    "source_pointers": [
                        {"artifact": "survey.md", "json_pointer": "/sections/2", "section": "Limitations"}
                    ],
                }
            ]
        }

    candidates = extract_survey_gap_candidates(
        llm_call=mock_llm,
        survey_markdown="# Findings\nA result.\n## Limitations\nThe regime is unknown.",
        deterministic_ledger=_ledger(),
    )

    assert len(candidates) == 1
    payload = {"schema_version": "survey_gap_candidate_v1", **candidates[0].to_payload()}
    assert validate_gap_candidate_payload(payload) == []
    assert candidates[0].source_pointers[0].section == "Limitations"
    assert "Do not invent" in calls[0]


def test_section_aware_paper_input_preserves_headings_and_paper_provenance() -> None:
    paper = build_section_aware_paper_input(
        {
            "paper_id": "W1",
            "title": "A mechanistic study",
            "abstract": "We observe a relation.",
            "sections": {
                "Methods": "The intervention was measured.",
                "Limitations": "The comparison condition was not tested.",
            },
        }
    )

    assert paper.paper_id == "W1"
    assert [section["heading"] for section in paper.sections] == ["Methods", "Limitations"]

    candidates = extract_paper_limitation_candidates(
        papers=[paper.to_payload()],
        llm_call=lambda prompt: {
            "limitations": [
                {
                    "gap_kind": "missing_comparator",
                    "target_slot": "comparator",
                    "statement": "The comparison condition was not tested.",
                    "section": "Limitations",
                    "confidence": 0.72,
                }
            ]
        },
    )
    assert len(candidates) == 1
    assert candidates[0].paper_ids == ["W1"]
    assert candidates[0].source_pointers[0].paper_id == "W1"
    assert candidates[0].source_pointers[0].section == "Limitations"


def test_duplicate_candidates_merge_and_retain_all_sources() -> None:
    candidates = [
        {
            "candidate_id": "c1",
            "subhypothesis_id": "SH1",
            "gap_kind": "missing_comparator",
            "target_slot": "comparator",
            "statement": "No comparator is defined for the intervention.",
            "confidence": 0.6,
            "source_pointers": [{"artifact": "survey.md", "json_pointer": "/a"}],
            "paper_ids": ["W1"],
        },
        {
            "candidate_id": "c2",
            "subhypothesis_id": "SH1",
            "gap_kind": "missing_comparator",
            "target_slot": "comparator",
            "statement": "The intervention has no defined comparison condition.",
            "confidence": 0.8,
            "source_pointers": [{"artifact": "paper", "json_pointer": "/sections/1", "paper_id": "W2"}],
            "paper_ids": ["W2"],
        },
    ]
    report = deduplicate_gap_candidates(candidates)
    assert report["duplicate_group_count"] == 1
    assert report["groups"][0]["candidate_ids"] == ["c1", "c2"]
    assert report["candidates"][0]["paper_ids"] == ["W1", "W2"]
    assert report["candidates"][0]["support_level"] == "cross_source"


def test_contradiction_detection_requires_explicit_opposing_stance() -> None:
    candidates = [
        {
            "candidate_id": "c1",
            "subhypothesis_id": "SH1",
            "gap_kind": "missing_boundary_condition",
            "target_slot": "validity_domain",
            "statement": "The findings support validity in the high-field regime.",
            "stance": "supports",
            "paper_ids": ["W1"],
            "source_pointers": [{"artifact": "paper", "json_pointer": "/1"}],
        },
        {
            "candidate_id": "c2",
            "subhypothesis_id": "SH1",
            "gap_kind": "missing_boundary_condition",
            "target_slot": "validity_domain",
            "statement": "A second analysis challenges validity in the high-field regime.",
            "stance": "challenges",
            "paper_ids": ["W2"],
            "source_pointers": [{"artifact": "paper", "json_pointer": "/2"}],
        },
    ]
    contradictions = detect_gap_contradictions(candidates)
    assert len(contradictions) == 1
    assert contradictions[0]["paper_ids"] == ["W1", "W2"]


def test_coverage_and_adjudication_marks_conflict_pending_verification() -> None:
    candidates = [
        {
            "candidate_id": "c1",
            "subhypothesis_id": "SH1",
            "gap_kind": "missing_boundary_condition",
            "target_slot": "validity_domain",
            "statement": "The findings support validity in the high-field regime.",
            "stance": "supports",
            "confidence": 0.9,
            "paper_ids": ["W1"],
            "source_pointers": [{"artifact": "paper", "json_pointer": "/1"}],
        },
        {
            "candidate_id": "c2",
            "subhypothesis_id": "SH1",
            "gap_kind": "missing_boundary_condition",
            "target_slot": "validity_domain",
            "statement": "A second analysis challenges validity in the high-field regime.",
            "stance": "challenges",
            "confidence": 0.9,
            "paper_ids": ["W2"],
            "source_pointers": [{"artifact": "paper", "json_pointer": "/2"}],
        },
    ]
    coverage = build_coverage_matrix(gap_ledger=_ledger(), candidates=candidates)
    assert coverage["rows"][0]["status"] == "candidate_pending"
    adjudication = adjudicate_gap_candidates(candidates)
    assert adjudication["decisions"][0]["decision"] == "pending_verification"
    artifact = build_gap_coverage_artifact(gap_ledger=_ledger(), candidates=candidates)
    assert artifact["artifact_fingerprint"] == canonical_fingerprint(artifact, exclude_fields={"artifact_fingerprint"})
    assert artifact["coverage"]["rows"][0]["status"] == "contradicted"
