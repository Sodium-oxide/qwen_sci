from __future__ import annotations

from src.pipeline.survey_gap_ledger import extract_deterministic_gaps


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
