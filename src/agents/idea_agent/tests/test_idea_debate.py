from __future__ import annotations

from threading import Lock
from time import sleep

from src.agents.idea_agent.utils.workflow.idea_debate import (
    DEBATE_PROMPT_CHAR_LIMIT,
    _apply_revision,
    _debate_prompt,
    cross_seed_debate,
    debate_direction_set,
    effective_scientific_contract,
)
from src.agents.idea_agent.utils.core.chat_errors import is_non_retryable_chat_error
from src.agents.idea_agent.utils.mcts.scientific_intervention_ontology import (
    detect_profile_drift,
    get_scientific_intervention_profile,
)


def _direction() -> dict:
    return {
        "direction_mode": "evidence_first",
        "direction_summary": "Prefer a cleanly identifiable mechanism.",
        "title": "Mechanism hypothesis",
        "abstract": "A bounded scientific hypothesis.",
        "core_contribution": "Relate the intervention to the target mechanism.",
        "method": "Use profile-native observations.",
        "central_hypothesis": "The intervention changes the target relation.",
        "mechanism_or_relation": "The intervention changes a mediator.",
        "claim_scope": "Within the stated operating regime.",
        "target_gap_ids": ["gap-1"],
        "boundary_or_failure_condition": "The relation may fail outside the operating regime.",
        "scientific_intervention": {"profile_id": "physical_materials_chemical"},
        "experiment_design": "must never be created by debate",
    }


def test_debate_keeps_direction_and_gap_ids_and_runs_two_rounds_without_llm() -> None:
    result = debate_direction_set([_direction()], topic="electrochemical mechanism")
    candidate = result["directions"][0]

    assert result["round_count"] == 2
    assert len(candidate["debate_trace"]) == 2
    assert candidate["direction_mode"] == "evidence_first"
    assert candidate["target_gap_ids"] == ["gap-1"]
    assert "experiment_design" not in candidate
    assert candidate["debate_status"] in {
        "SCIENTIFICALLY_QUALIFIED",
        "SCIENTIFICALLY_QUALIFIED_WITH_UNCERTAINTY",
    }


class _ChangingDebateRuntime:
    def llm_json(self, **kwargs):
        return {
            "question_type": "scientific_consistency",
            "scientific_concern": "The causal wording is too strong.",
            "severity": "major",
            "revision_applied": True,
            "changed_field": ["central_hypothesis", "claim_scope"],
            "final_status": "SCIENTIFICALLY_QUALIFIED_WITH_UNCERTAINTY",
            "revised_candidate": {
                "central_hypothesis": "The intervention may alter the target relation.",
                "claim_scope": "Only within the stated operating regime.",
                "target_gap_ids": ["invented-gap"],
                "experiment_design": "forbidden",
            },
        }


def test_debate_restores_immutable_gap_mapping_and_marks_scope_reduction() -> None:
    result = debate_direction_set(
        [_direction()],
        topic="electrochemical mechanism",
        runtime=_ChangingDebateRuntime(),
        model="mock",
    )
    candidate = result["directions"][0]

    assert candidate["direction_mode"] == "evidence_first"
    assert candidate["target_gap_ids"] == ["gap-1"]
    assert candidate["debate_status"] == "NEEDS_SCOPE_REDUCTION"
    assert candidate["debate_trace"][-1]["changed_field"]
    assert "experiment_design" not in candidate


class _RepairingDebateRuntime:
    def __init__(self) -> None:
        self.calls = 0

    def llm_json(self, **kwargs):
        self.calls += 1
        if self.calls == 1:
            return {
                "final_status": "NEEDS_SCOPE_REDUCTION",
                "revision_applied": True,
                "revised_candidate": {
                    "central_hypothesis": "Under the bounded condition, the intervention may alter the target relation.",
                    "mechanism_or_relation": "A profile-native mediator links the intervention to the observation.",
                    "assumptions": ["The operating regime remains stable during observation."],
                    "claim_scope": "Only the stated bounded operating regime.",
                },
            }
        return {
            "final_status": "SCIENTIFICALLY_QUALIFIED_WITH_UNCERTAINTY",
            "revised_candidate": {
                "boundary_or_failure_condition": "The conclusion does not extend outside the operating regime.",
                "alternative_explanations": ["A competing mediator could produce the same observation."],
            },
        }


def test_debate_enters_round_two_when_round_one_repairs_major_contract_gaps() -> None:
    runtime = _RepairingDebateRuntime()
    source = _direction()
    source.pop("central_hypothesis")
    source.pop("mechanism_or_relation")
    source.pop("claim_scope")
    source.pop("target_gap_ids")
    source["target_gap_ids"] = ["gap-1"]
    source["assumptions"] = []
    source["scientific_intervention"] = {
        **source["scientific_intervention"],
        "route_id": "mechanism_replacement",
        "route_contract_incomplete_fields": ["mechanism_or_relation"],
    }

    result = debate_direction_set(
        [source],
        topic="electrochemical mechanism",
        runtime=runtime,
        model="mock",
        run_cross_seed=False,
    )
    candidate = result["directions"][0]

    assert runtime.calls == 2
    assert len(candidate["debate_trace"]) == 2
    assert candidate["debate_trace"][0]["preflight_severity"] == "major"
    assert candidate["debate_trace"][0]["postflight_severity"] != "major"
    assert candidate["debate_trace"][0]["next_round"] is True
    assert "route_contract_incomplete_fields" not in candidate["scientific_intervention"]
    assert result["statistics"]["repaired_after_round_1_count"] == 1


def test_debate_reads_nested_hypothesis_contract_as_an_effective_candidate() -> None:
    source = _direction()
    nested_contract = {
        "central_hypothesis": source.pop("central_hypothesis"),
        "mechanism_or_relation": source.pop("mechanism_or_relation"),
        "claim_scope": source.pop("claim_scope"),
        "target_gap_ids": source.pop("target_gap_ids"),
        "assumptions": ["The observation is measured inside the target regime."],
    }
    source["scientific_intervention"] = {
        **source["scientific_intervention"],
        "hypothesis_contract": nested_contract,
    }

    effective = effective_scientific_contract(source)
    result = debate_direction_set([source], topic="electrochemical mechanism", run_cross_seed=False)

    assert effective["central_hypothesis"] == nested_contract["central_hypothesis"]
    assert effective["mechanism_or_relation"] == nested_contract["mechanism_or_relation"]
    assert result["directions"][0]["debate_trace"][0]["preflight_severity"] != "major"


class _ObjectRepairDebateRuntime:
    def __init__(self) -> None:
        self.calls = 0

    def llm_json(self, **kwargs):
        self.calls += 1
        if self.calls == 1:
            return {
                "revised_candidate": {
                    "scientific_object": {"object_type": "substituted_object"},
                    "assumptions": ["The substituted object remains measurable."],
                }
            }
        return {
            "revised_candidate": {
                "boundary_or_failure_condition": "The substitution fails outside the stated scale.",
                "alternative_explanations": ["The parent object could still explain the observation."],
            }
        }


def test_object_substitution_revision_updates_candidate_before_clearing_route_marker() -> None:
    runtime = _ObjectRepairDebateRuntime()
    source = _direction()
    source["assumptions"] = []
    source["scientific_object"] = {"object_type": "parent_object"}
    source["scientific_intervention"] = {
        **source["scientific_intervention"],
        "route_id": "object_substitution",
        "route_contract_incomplete_fields": ["scientific_object"],
        "route_contract_parent_values": {"scientific_object": {"object_type": "parent_object"}},
    }

    result = debate_direction_set(
        [source],
        topic="electrochemical mechanism",
        runtime=runtime,
        model="mock",
        run_cross_seed=False,
    )
    candidate = result["directions"][0]

    assert runtime.calls == 2
    assert candidate["scientific_object"] == {"object_type": "substituted_object"}
    assert "route_contract_incomplete_fields" not in candidate["scientific_intervention"]
    assert candidate["debate_trace"][0]["postflight_severity"] != "major"


def test_string_object_revision_is_preserved_as_structured_scientific_object() -> None:
    original = {
        **_direction(),
        "scientific_object": {"description": "parent object"},
        "scientific_intervention": {
            "route_id": "object_substitution",
            "route_contract_incomplete_fields": ["scientific_object"],
            "route_contract_parent_values": {"scientific_object": {"description": "parent object"}},
        },
    }

    revised, _, _, _ = _apply_revision(
        original,
        {"scientific_object": "substituted object"},
        direction_mode="evidence_first",
        original_gap_ids=["gap-1"],
    )

    assert revised["scientific_object"] == {"description": "substituted object"}
    assert "route_contract_incomplete_fields" not in revised["scientific_intervention"]


class _CountingGapViolationRuntime:
    def __init__(self) -> None:
        self.calls = 0

    def llm_json(self, **kwargs):
        self.calls += 1
        return {
            "revised_candidate": {
                "target_gap_ids": ["invented-gap"],
                "central_hypothesis": "A revised but incompatible claim.",
            }
        }


def test_gap_mapping_violation_terminates_before_round_two() -> None:
    runtime = _CountingGapViolationRuntime()

    result = debate_direction_set(
        [_direction()],
        topic="electrochemical mechanism",
        runtime=runtime,
        model="mock",
        run_cross_seed=False,
    )

    event = result["directions"][0]["debate_trace"][0]
    assert runtime.calls == 1
    assert event["termination_reason"] == "immutable_gap_mapping_violation"
    assert result["statistics"]["immutable_violation_count"] == 1


class _FailingDebateRuntime:
    def llm_json(self, **kwargs):
        raise RuntimeError("debate unavailable")


def test_debate_failure_preserves_candidate_and_marks_review() -> None:
    source = _direction()
    result = debate_direction_set([source], runtime=_FailingDebateRuntime(), model="mock")
    candidate = result["directions"][0]

    assert candidate["debate_status"] == "REQUIRES_REVIEW"
    assert candidate["debate_failure_reason"] == "debate unavailable"
    assert candidate["central_hypothesis"] == source["central_hypothesis"]
    assert candidate["target_gap_ids"] == source["target_gap_ids"]


class _ConcurrentDebateRuntime:
    def __init__(self) -> None:
        self._lock = Lock()
        self.active_calls = 0
        self.max_active_calls = 0

    def llm_json(self, **kwargs):
        with self._lock:
            self.active_calls += 1
            self.max_active_calls = max(self.max_active_calls, self.active_calls)
        sleep(0.05)
        with self._lock:
            self.active_calls -= 1
        return {"final_status": "SCIENTIFICALLY_QUALIFIED"}


class _CollectingLogger:
    def __init__(self) -> None:
        self.messages: list[str] = []

    def info(self, message: str, *args) -> None:
        self.messages.append(message % args if args else message)

    def warning(self, message: str, *args) -> None:
        self.messages.append(message % args if args else message)


def test_debate_parallelizes_independent_candidates_and_preserves_order() -> None:
    runtime = _ConcurrentDebateRuntime()
    directions = []
    for index in range(4):
        directions.append(
            {
                **_direction(),
                "title": f"Mechanism hypothesis {index}",
                "idea_id": f"idea-{index}",
                "seed_id": f"seed-{index}",
            }
        )

    result = debate_direction_set(
        directions,
        runtime=runtime,
        model="mock",
        max_rounds=1,
        max_parallel_internal=4,
        run_cross_seed=False,
    )

    assert runtime.max_active_calls >= 2
    assert [item["idea_id"] for item in result["directions"]] == ["idea-0", "idea-1", "idea-2", "idea-3"]
    assert all(len(item["debate_trace"]) == 1 for item in result["directions"])


def test_cross_seed_debate_parallelizes_pairs_and_preserves_pair_order() -> None:
    runtime = _ConcurrentDebateRuntime()
    logger = _CollectingLogger()
    directions = [
        {
            **_direction(),
            "title": f"Mechanism hypothesis {index}",
            "idea_id": f"idea-{index}",
            "seed_id": f"seed-{index}",
            "search_score": index,
        }
        for index in range(4)
    ]

    result = cross_seed_debate(
        directions,
        runtime=runtime,
        model="mock",
        logger=logger,
        max_parallel_cross_seed=6,
    )

    assert runtime.max_active_calls >= 2
    assert result["representative_count"] == 4
    assert [
        (item["left_seed_id"], item["right_seed_id"])
        for item in result["pairs"]
    ] == [
        ("seed-0", "seed-1"),
        ("seed-0", "seed-2"),
        ("seed-0", "seed-3"),
        ("seed-1", "seed-2"),
        ("seed-1", "seed-3"),
        ("seed-2", "seed-3"),
    ]
    assert sum("started" in message for message in logger.messages) == 6
    assert sum("completed" in message for message in logger.messages) == 6
    assert any("pair 1/6" in message for message in logger.messages)


def test_debate_prompt_uses_compact_candidate_and_handoff_views() -> None:
    direction = {
        **_direction(),
        "search_trace": [{"payload": "x" * 200_000}],
        "pareto_candidates": {"novel": {"payload": "y" * 200_000}},
    }
    prompt = _debate_prompt(
        topic="electrochemical mechanism",
        round_number=1,
        direction=direction,
        profile_id="physical_materials_chemical",
        profile_context="native profile",
        survey_handoff={
            "topic": "electrochemical mechanism",
            "gaps": [{"gap_id": "gap-1", "statement": "The mechanism is unresolved."}],
            "irrelevant_history": "z" * 200_000,
        },
        profile_drift={},
        baseline={"question_type": "scientific_consistency"},
    )

    assert len(prompt) <= DEBATE_PROMPT_CHAR_LIMIT
    assert "search_trace" not in prompt
    assert "pareto_candidates" not in prompt
    assert "The mechanism is unresolved." in prompt


def test_invalid_input_length_error_is_not_retryable() -> None:
    error = RuntimeError(
        "BadRequestError; status=400; code=invalid_parameter_error; "
        "message=Range of input length should be [1, 983616]"
    )
    error.status_code = 400
    assert is_non_retryable_chat_error(error)


def test_profile_drift_allows_computational_profile_and_secondary_tools() -> None:
    computational = detect_profile_drift(
        "computational_algorithmic",
        {"core_contribution": "A neural architecture with a new loss function."},
    )
    auxiliary = detect_profile_drift(
        "physical_materials_chemical",
        {"method": "Use machine learning as an auxiliary tool for numerical simulation."},
    )

    assert computational["drift_severity"] == "none"
    assert computational["primary_drift"] is False
    assert auxiliary["drift_severity"] == "soft"
    assert auxiliary["primary_drift"] is False
    assert "machine_learning" not in auxiliary["forbidden_primary_terms"]


def test_profile_drift_marks_incompatible_primary_cs_contribution() -> None:
    drift = detect_profile_drift(
        "physical_materials_chemical",
        {"core_contribution": "The main novelty is a neural architecture and loss function."},
    )

    assert drift["primary_drift"] is True
    assert drift["drift_severity"] == "material"
    assert "neural_architecture" in drift["forbidden_primary_terms"]
    assert drift["rewrite_targets"]


def test_profile_drift_ignores_profile_rule_metadata() -> None:
    profile = get_scientific_intervention_profile("formal_theoretical")
    assert profile is not None

    drift = detect_profile_drift(
        "formal_theoretical",
        candidate={
            "mechanism_or_relation": "A formal scattering relation links the boundary condition to the observable.",
            "scientific_intervention": profile.to_payload(),
        },
    )

    assert drift["drift_severity"] == "none"
    assert drift["primary_drift"] is False
    assert drift["forbidden_primary_terms"] == []


def test_debate_separates_profile_drift_from_actual_missing_fields() -> None:
    source = _direction()
    source["core_contribution"] = "The primary contribution is a benchmark of competing predictions."
    source["assumptions"] = ["The stated operating regime holds."]
    source["scientific_intervention"] = {"profile_id": "formal_theoretical"}

    result = debate_direction_set(
        [source],
        topic="formal mechanism",
        profile_id="formal_theoretical",
        run_cross_seed=False,
    )
    event = result["directions"][0]["debate_trace"][0]

    assert "mechanism_or_relation" not in event["actual_missing_fields"]
    assert event["profile_drift_fields"] == ["mechanism_or_relation"]
    assert event["final_status"] == "PROFILE_DRIFT"
    assert event["postflight_missing"] == []
    assert event["postflight_profile_drift_fields"] == ["mechanism_or_relation"]
