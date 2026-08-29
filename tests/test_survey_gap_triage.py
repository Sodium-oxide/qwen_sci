from __future__ import annotations

from src.pipeline.survey_gap_triage import (
    TARGETED_VERIFICATION_TOP_K,
    build_gap_triage_artifact,
)


def _ledger(*gaps: dict) -> dict:
    return {
        "schema_version": "survey_gap_ledger_v1",
        "project_id": "project-1",
        "survey_run_id": "run-1",
        "project_context_fingerprint": "fingerprint",
        "profile_resolution": {"profile_id_hint": "generic_scientific"},
        "gaps": list(gaps),
        "candidate_gaps": [],
    }


def _gap(index: int, **overrides: object) -> dict:
    payload = {
        "gap_id": f"gap-{index}",
        "subhypothesis_id": "SH1",
        "gap_kind": "mechanism_explanation_gap",
        "target_slot": "candidate_mechanism",
        "statement": "The causal mechanism remains unresolved.",
        "priority": "high",
        "status": "open",
        "source_pointer": {"artifact": "survey.md", "json_pointer": f"/sections/{index}"},
    }
    payload.update(overrides)
    return payload


def test_routes_keep_plausible_and_future_work_gaps() -> None:
    payload = build_gap_triage_artifact(
        gap_ledger=_ledger(
            _gap(1, confidence=0.9),
            _gap(2, gap_kind="future_work", statement="Future work should test an unexamined regime."),
            _gap(3, gap_kind="benchmark_only", target_slot="evaluation", statement="Only the benchmark protocol is missing."),
        )
    )
    by_id = {item["gap_id"]: item for item in payload["gaps"]}
    assert by_id["gap-1"]["eligibility_route"] == "core_hypothesis"
    assert by_id["gap-2"]["eligibility_route"] == "future_work_seed"
    assert by_id["gap-3"]["eligibility_route"] == "verification_only"


def test_targeted_verification_is_bounded_at_fifteen_and_keeps_unchecked_rows() -> None:
    payload = build_gap_triage_artifact(
        gap_ledger=_ledger(*[_gap(index, confidence=0.8) for index in range(20)])
    )
    assert payload["top_k"] == TARGETED_VERIFICATION_TOP_K == 15
    checked = [item for item in payload["gaps"] if item["verification_status"] != "not_checked"]
    unchecked = [item for item in payload["gaps"] if item["verification_status"] == "not_checked"]
    assert len(checked) == 15
    assert len(unchecked) == 5
    assert all(not item["verification_required"] for item in unchecked)


def test_triage_does_not_revive_explicitly_excluded_rows() -> None:
    payload = build_gap_triage_artifact(
        gap_ledger=_ledger(_gap(1, status="rejected"), _gap(2, status="out_of_scope"))
    )
    assert payload["excluded_gap_ids"]
    assert not any(item["eligibility_route"] == "exploratory_frontier" for item in payload["gaps"])


def test_targeted_verification_can_promote_a_plausible_mechanism_gap() -> None:
    payload = build_gap_triage_artifact(
        gap_ledger=_ledger(_gap(1, confidence=0.5)),
        llm_call=lambda _prompt: {"status": "verified"},
    )
    gap = payload["gaps"][0]
    assert gap["audit_status"] == "verified"
    assert gap["verification_status"] == "verified"
    assert gap["eligibility_route"] == "core_hypothesis"
    assert gap["novelty_role"] == "primary"
    assert not gap["verification_required"]


def test_accepted_llm_gap_keeps_low_confidence_instead_of_defaulting_verified() -> None:
    payload = build_gap_triage_artifact(
        gap_ledger=_ledger(
            _gap(
                1,
                source_kind="accepted_llm_gap_candidate",
                gap_audit={"candidate_id": "candidate-1", "existence_confidence": 0.2},
            )
        )
    )
    gap = payload["gaps"][0]
    assert gap["existence_confidence"] == 0.2
    assert gap["audit_status"] == "weakly_supported"
    assert gap["eligibility_route"] == "exploratory_frontier"


def test_verification_failure_falls_back_without_rejecting_gap() -> None:
    payload = build_gap_triage_artifact(
        gap_ledger=_ledger(_gap(1, confidence=0.5)),
        llm_call=lambda _prompt: (_ for _ in ()).throw(RuntimeError("offline")),
    )
    gap = payload["gaps"][0]
    assert gap["audit_status"] == "plausible"
    assert gap["eligibility_route"] == "provisional_hypothesis"
    assert gap["verification_status"] == "plausible"
