from __future__ import annotations

import copy
import json
from pathlib import Path

from src.pipeline.survey_gap_ledger import (
    build_deterministic_gap_ledger,
    extract_deterministic_gaps,
)
from src.pipeline.survey_idea_handoff import validate_gap_ledger_payload


FIXTURE_DIR = Path(__file__).resolve().parents[1] / "src" / "agents" / "survey_agent" / "outputs" / "20260826-002857-396164"


def _fixture(name: str) -> dict:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


def test_existing_survey_fixture_builds_valid_initial_ledger() -> None:
    payload = build_deterministic_gap_ledger(
        evidence_plan=FIXTURE_DIR / "survey_evidence_plan.json",
        claim_traceability=FIXTURE_DIR / "survey_claim_traceability.json",
        project_context=FIXTURE_DIR / "project_context.json",
        survey_json=FIXTURE_DIR / "survey.json",
    )

    assert payload["schema_version"] == "survey_gap_ledger_v1"
    assert payload["project_id"] == "sci_20260826_002857_396164"
    assert payload["survey_run_id"] == "20260826-002857-396164"
    assert payload["profile_resolution"]["status"] == "unresolved"
    assert payload["profile_resolution"]["profile_id_hint"] == ""
    assert payload["gaps"]
    assert validate_gap_ledger_payload(payload, verify_fingerprint=True) == []


def test_missing_slots_map_to_domain_native_gap_kinds() -> None:
    gaps = extract_deterministic_gaps(evidence_plan=FIXTURE_DIR / "survey_evidence_plan.json")
    by_key = {(gap.subhypothesis_id, gap.target_slot): gap for gap in gaps}

    assert by_key[("SH3", "formal_claim")].gap_kind == "missing_assumption"
    assert by_key[("SH3", "validity_domain")].gap_kind == "missing_boundary_condition"
    assert by_key[("SH5", "mapping_or_calibration")].gap_kind == "measurement_construct_mismatch"
    assert by_key[("SH6", "comparator")].gap_kind == "missing_comparator"


def test_uncovered_slots_are_added_without_duplicate_slot_gaps() -> None:
    gaps = extract_deterministic_gaps(evidence_plan=FIXTURE_DIR / "survey_evidence_plan.json")
    keys = [(gap.subhypothesis_id, gap.gap_kind, gap.target_slot) for gap in gaps]

    assert len(keys) == len(set(keys))
    assert any(
        gap.source_kind == "uncovered_required_slot"
        for gap in gaps
    )
    assert not any(
        gap.subhypothesis_id == "SH3"
        and gap.target_slot == "formal_claim"
        and gap.source_kind == "uncovered_required_slot"
        for gap in gaps
    )


def test_background_or_qualified_only_evidence_creates_role_deficit() -> None:
    plan = {
        "project_id": "project-1",
        "project_context_fingerprint": "context-1",
        "subhypotheses": [
            {
                "sub_hypothesis_id": "SH1",
                "summary": "A direct observation is required.",
                "allowed_claim_modes": ["EVIDENCE_GAP_REPORT"],
                "forbidden_paper_ids": ["W2"],
                "direct_writing_blocked_paper_ids": [],
                "required_slots": ["direct_observation"],
                "missing_slots": [],
                "covered_slots": [],
                "background_only_slots": ["direct_observation"],
                "slot_support": {
                    "direct_observation": {
                        "expected_evidence_role": "DIRECT_OBSERVATION",
                        "evidence_paper_ids": [],
                        "qualified_paper_ids": ["W2"],
                        "background_paper_ids": ["W3"],
                        "qualified_paper_constraints": {
                            "W2": [{"forbidden_as_direct_evidence": True}]
                        },
                    }
                },
                "relevant_clusters": [],
                "conclusion_admissibility": {"blockers": []},
                "limitations": {"blockers": []},
            }
        ],
    }
    gaps = extract_deterministic_gaps(evidence_plan=plan)
    role_gap = next(gap for gap in gaps if gap.gap_kind == "evidence_role_deficit")

    assert role_gap.priority == "medium"
    assert role_gap.evidence_eligibility.required_roles == ["DIRECT_OBSERVATION"]
    assert role_gap.evidence_eligibility.forbidden_paper_ids == ["W2"]


def test_claim_blockers_are_structured_and_unknown_values_stay_unmapped() -> None:
    plan = {
        "project_id": "project-1",
        "project_context_fingerprint": "context-1",
        "subhypotheses": [
            {
                "sub_hypothesis_id": "SH1",
                "required_slots": ["phenomenon"],
                "missing_slots": [],
                "slot_support": {},
                "relevant_clusters": [],
                "conclusion_admissibility": {
                    "blockers": ["unsupported causal interpretation"]
                },
                "limitations": {
                    "blockers": ["unusual blocker code"]
                },
            }
        ],
    }
    gaps = extract_deterministic_gaps(evidence_plan=plan)
    kinds = {gap.gap_kind for gap in gaps}

    assert "unsupported_causal_link" in kinds
    assert "unmapped_gap:limitations" not in kinds
    assert any(kind.startswith("unmapped_gap:") for kind in kinds)


def test_extraction_is_stable_and_does_not_mutate_input() -> None:
    plan = _fixture("survey_evidence_plan.json")
    original = copy.deepcopy(plan)
    first = [gap.to_payload() for gap in extract_deterministic_gaps(evidence_plan=plan)]
    second = [gap.to_payload() for gap in extract_deterministic_gaps(evidence_plan=plan)]

    assert first == second
    assert plan == original
