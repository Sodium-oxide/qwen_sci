from __future__ import annotations

from src.pipeline.evidence_coverage_ledger import (
    associate_papers_with_subhypotheses,
    build_evidence_coverage_ledger,
)
from src.pipeline.evidence_refinement import (
    build_evidence_refinement_plan,
    refinement_execution_summary,
)
from src.pipeline.research_identity import build_project_research_context
from src.pipeline.retrieval_lanes import build_subhypothesis_retrieval_plan


def _project_context() -> dict:
    return build_project_research_context(
        original_topic="Comparative durability of adaptive materials under thermal cycling",
        declared_domain="materials science",
        objective="Compare adaptive materials with reference alloys under thermal cycling.",
        use_llm=False,
    )


def _definition(meaning: str, concept: str) -> dict:
    return {
        "meaning": meaning,
        "retrieval_concepts": [concept],
        "minimum_evidence": "reported empirical evidence",
        "admission_rule": "reports evidence for the declared slot",
    }


def _comparative_contract(
    project: dict,
    *,
    identifier: str = "adaptive_materials",
    excluded_contexts: list[str] | None = None,
) -> dict:
    contract = {
        "schema_version": "science_subhypothesis_v2",
        "sub_hypothesis_id": identifier,
        "title": "Adaptive material durability comparison",
        "question": "Do adaptive materials improve durability relative to reference alloys under thermal cycling?",
        "question_kind": "COMPARATIVE_EVALUATION",
        "scientific_scope": {
            "research_object": ["adaptive materials"],
            "comparison_frame": ["reference alloys"],
            "condition_or_regime": ["thermal cycling"],
            "outcome_or_construct": ["durability"],
        },
        "required_slots": [
            "candidate",
            "comparator",
            "comparison_condition",
            "comparable_endpoint",
        ],
        "slot_definitions": {
            "candidate": _definition("material under evaluation", "adaptive material"),
            "comparator": _definition("reference material", "reference alloy"),
            "comparison_condition": _definition("shared regime", "thermal cycling"),
            "comparable_endpoint": _definition("common endpoint", "durability"),
        },
        "research_role": "PRIMARY_QUESTION",
        "challenge_target": "the claim that adaptive materials are always more durable",
        "design_basis_ids": [
            item["id"]
            for item in project["research_design_inventory"]["design_basis"][:3]
        ],
    }
    if excluded_contexts:
        contract["excluded_evidence_scope"] = {"contexts": excluded_contexts}
    return contract


def _measurement_contract(project: dict) -> dict:
    return {
        "schema_version": "science_subhypothesis_v2",
        "sub_hypothesis_id": "durability_measurement",
        "title": "Durability measurement validity",
        "question": "Does the accelerated durability proxy validly measure long-term material durability?",
        "question_kind": "MEASUREMENT_VALIDITY",
        "scientific_scope": {
            "research_object": ["adaptive materials"],
            "outcome_or_construct": ["long-term durability"],
            "measurement_or_endpoint": ["accelerated durability proxy"],
        },
        "required_slots": [
            "construct",
            "proxy_or_measure",
            "reference_or_target_measure",
            "mapping_or_calibration",
        ],
        "slot_definitions": {
            "construct": _definition("target construct", "long-term durability"),
            "proxy_or_measure": _definition("proxy", "accelerated durability proxy"),
            "reference_or_target_measure": _definition("reference", "service lifetime measurement"),
            "mapping_or_calibration": _definition("calibration", "calibration curve"),
        },
        "research_role": "PRIMARY_QUESTION",
        "challenge_target": "the claim that the accelerated proxy is an unbiased durability measure",
        "design_basis_ids": [
            item["id"]
            for item in project["research_design_inventory"]["design_basis"][:3]
        ],
    }


def _generalization_contract(project: dict) -> dict:
    return {
        "schema_version": "science_subhypothesis_v2",
        "sub_hypothesis_id": "adaptive_materials_transport",
        "title": "Adaptive material transportability",
        "question": "Do durability findings for adaptive materials generalize from laboratory specimens to industrial components?",
        "question_kind": "GENERALIZATION_TRANSPORT",
        "scientific_scope": {
            "research_object": ["adaptive materials"],
            "population_or_system": ["laboratory specimens", "industrial components"],
            "condition_or_regime": ["thermal cycling"],
            "outcome_or_construct": ["durability"],
        },
        "required_slots": [
            "source_system",
            "target_system",
            "shift_or_variation",
            "external_validation",
        ],
        "slot_definitions": {
            "source_system": _definition("source system", "laboratory specimens"),
            "target_system": _definition("target system", "industrial components"),
            "shift_or_variation": _definition("system change", "manufacturing variation"),
            "external_validation": _definition("external test", "field validation"),
        },
        "research_role": "PRIMARY_QUESTION",
        "challenge_target": "the claim that laboratory durability transfers without loss to industrial components",
        "design_basis_ids": [
            item["id"]
            for item in project["research_design_inventory"]["design_basis"][:3]
        ],
    }


def _compiled(contract: dict, project: dict) -> dict:
    subhypothesis = build_subhypothesis_retrieval_plan(project, [contract])["subhypotheses"][0]
    assert subhypothesis["validation"]["valid"] is True
    return subhypothesis


def _paper(
    paper_id: str,
    text: str,
    task_ids: list[str],
) -> dict:
    return {
        "paperId": paper_id,
        "title": text,
        "abstract": text,
        "api_platform": "openalex",
        "retrieval_provenance": [
            {
                "sub_hypothesis_id": task_id.split(".", 1)[0],
                "slot_recovery_task_id": task_id,
            }
            for task_id in task_ids
        ],
    }


def _ledger(papers: list[dict], subhypothesis: dict) -> dict:
    associated = associate_papers_with_subhypotheses(
        papers,
        [subhypothesis],
        project_fingerprint="test-project",
    )
    return build_evidence_coverage_ledger(associated, [subhypothesis])


def test_slot_ledger_records_evidence_role_and_allows_comparable_synthesis() -> None:
    project = _project_context()
    subhypothesis = _compiled(_comparative_contract(project), project)
    task_ids = [task["task_id"] for task in subhypothesis["slot_recovery_tasks"]]
    ledger = _ledger(
        [
            _paper(
                "W1",
                "A comparative benchmark evaluation measures adaptive material and reference alloy durability under thermal cycling.",
                task_ids,
            )
        ],
        subhypothesis,
    )

    report = ledger["subhypotheses"][0]
    assert ledger["schema_version"] == "evidence_coverage_ledger_v1"
    assert report["covered_slots"] == subhypothesis["required_slots"]
    assert report["background_only_slots"] == []
    assert report["missing_slots"] == []
    assert report["evidence_by_role"]["COMPARATIVE_OR_MEASUREMENT_EVIDENCE"]
    assert report["conclusion_admissibility"] == {
        "status": "ADMISSIBLE_FOR_SYNTHESIS",
        "admissible": True,
        "blockers": [],
        "comparability": {
            "required": True,
            "sufficient": True,
            "required_slots": [
                "candidate",
                "comparator",
                "comparison_condition",
                "comparable_endpoint",
            ],
            "supporting_paper_ids": ["W1"],
        },
        "measurement": {
            "required": False,
            "sufficient": True,
            "required_slots": [],
            "supporting_paper_ids": [],
        },
        "scope": {"sufficient": True, "rejections_or_unverified": []},
    }


def test_background_only_evidence_remains_visible_but_does_not_cover_a_slot() -> None:
    project = _project_context()
    subhypothesis = _compiled(_comparative_contract(project), project)
    candidate_task = subhypothesis["slot_recovery_tasks"][0]["task_id"]
    ledger = _ledger(
        [
            _paper(
                "W-review",
                "A systematic review surveys adaptive material durability research and its conceptual framework.",
                [candidate_task],
            )
        ],
        subhypothesis,
    )

    report = ledger["subhypotheses"][0]
    candidate = report["slot_ledger"]["candidate"]
    assert candidate["covered_by"] == []
    assert candidate["background_only_by"][0]["paper_id"] == "W-review"
    assert candidate["missing_reason"] == "background_evidence_only"
    assert "candidate" in report["background_only_slots"]
    assert "background_only_slot:candidate" in report["conclusion_admissibility"]["blockers"]


def test_measurement_admissibility_requires_a_common_evidence_record() -> None:
    project = _project_context()
    subhypothesis = _compiled(_measurement_contract(project), project)
    tasks = subhypothesis["slot_recovery_tasks"]
    papers = [
        _paper(
            f"W{index}",
            f"A benchmark evaluation reports {task['slot_definition']['retrieval_concepts'][0]} for adaptive materials.",
            [task["task_id"]],
        )
        for index, task in enumerate(tasks, start=1)
    ]
    ledger = _ledger(papers, subhypothesis)

    report = ledger["subhypotheses"][0]
    admissibility = report["conclusion_admissibility"]
    assert report["missing_slots"] == []
    assert admissibility["measurement"] == {
        "required": True,
        "sufficient": False,
        "required_slots": [
            "construct",
            "proxy_or_measure",
            "reference_or_target_measure",
            "mapping_or_calibration",
        ],
        "supporting_paper_ids": [],
    }
    assert "measurement_insufficient" in admissibility["blockers"]
    assert admissibility["admissible"] is False


def test_scope_violations_are_explicit_admissibility_blockers() -> None:
    project = _project_context()
    subhypothesis = _compiled(
        _comparative_contract(project, excluded_contexts=["clinical deployment"]),
        project,
    )
    ledger = _ledger(
        [
            _paper(
                "W-clinical",
                "A comparative benchmark evaluation measures adaptive material and reference alloy durability under thermal cycling in clinical deployment.",
                [task["task_id"] for task in subhypothesis["slot_recovery_tasks"]],
            )
        ],
        subhypothesis,
    )

    report = ledger["subhypotheses"][0]
    admissibility = report["conclusion_admissibility"]
    assert report["missing_slots"] == subhypothesis["required_slots"]
    assert all(
        record["scope_assessment"]["violations"] == [
            "excluded_contexts:clinical deployment"
        ]
        for slot in report["slot_ledger"].values()
        for record in slot["scope_rejections"]
    )
    assert "scope_or_admission_insufficient" in admissibility["blockers"]
    assert admissibility["scope"]["sufficient"] is False


def test_second_stage_refinement_stays_idle_without_evidence_conflict_or_missing_slot() -> None:
    project = _project_context()
    subhypothesis = _compiled(_comparative_contract(project), project)
    ledger = _ledger(
        [
            _paper(
                "W-complete",
                "A comparative benchmark evaluation measures adaptive material and reference alloy durability under thermal cycling.",
                [task["task_id"] for task in subhypothesis["slot_recovery_tasks"]],
            )
        ],
        subhypothesis,
    )

    refinement_plan = build_evidence_refinement_plan(
        project,
        [subhypothesis],
        ledger,
    )

    assert refinement_plan["execution_policy"] == "conditional_second_stage_retrieval"
    assert refinement_plan["active_tasks"] == []
    assert all(decision["active"] is False for decision in refinement_plan["decisions"])


def test_second_stage_refinement_uses_conflict_signals_and_explicit_slot_recovery_targets() -> None:
    project = _project_context()
    contract = _comparative_contract(project)
    contract["required_slots"].append("boundary_case")
    contract["slot_definitions"]["boundary_case"] = _definition(
        "limiting regime",
        "thermal shock",
    )
    subhypothesis = _compiled(contract, project)
    tasks = {task["slot_name"]: task for task in subhypothesis["slot_recovery_tasks"]}
    ledger = _ledger(
        [
            _paper(
                "W-main",
                "A comparative benchmark evaluation measures adaptive material and reference alloy durability under thermal cycling.",
                [
                    tasks["candidate"]["task_id"],
                    tasks["comparator"]["task_id"],
                    tasks["comparison_condition"]["task_id"],
                    tasks["comparable_endpoint"]["task_id"],
                ],
            ),
            _paper(
                "W-conflict",
                "A thermal shock failure analysis reports a negative result for adaptive material durability.",
                [tasks["boundary_case"]["task_id"]],
            ),
        ],
        subhypothesis,
    )

    refinement_plan = build_evidence_refinement_plan(
        project,
        [subhypothesis],
        ledger,
    )
    active_kinds = {
        task["refinement_kind"] for task in refinement_plan["active_tasks"]
    }

    assert active_kinds == {
        "BOUNDARY_REFINEMENT",
        "REPLICATION_CONTRADICTION_RESOLUTION",
    }
    assert all(
        task["target_slot_recovery_task_ids"] == []
        for task in refinement_plan["active_tasks"]
    )
    assert all(
        "conflict_signal" in task["activation_reasons"]
        for task in refinement_plan["active_tasks"]
    )
    replication_task = next(
        task
        for task in refinement_plan["active_tasks"]
        if task["refinement_kind"] == "REPLICATION_CONTRADICTION_RESOLUTION"
    )
    assert replication_task["resolution_slot_task_ids"] == [
        task["task_id"] for task in subhypothesis["slot_recovery_tasks"]
    ]
    resolution_summary = refinement_execution_summary(
        [
            {
                **_paper(
                    "W-resolution",
                    "An independent replication examines contradictory durability findings for adaptive materials.",
                    [],
                ),
                "retrieval_provenance": [
                    {
                        "sub_hypothesis_id": "adaptive_materials",
                        "refinement_task_id": replication_task["task_id"],
                        "resolution_slot_task_ids": replication_task[
                            "resolution_slot_task_ids"
                        ],
                    }
                ],
            }
        ],
        refinement_plan,
        ledger,
        ledger,
    )
    resolution_record = next(
        record
        for record in resolution_summary["refinement_resolution"]
        if record["task_id"] == replication_task["task_id"]
    )
    assert resolution_record["resolution_target"] == "conflict_or_comparability"
    assert resolution_record["candidate_paper_ids"] == ["W-resolution"]
    assert (
        resolution_record["resolution_status"]
        == "CANDIDATES_RETRIEVED_PENDING_EVALUATION"
    )


def test_conflict_resolution_candidate_does_not_expand_slot_coverage_or_admissibility() -> None:
    project = _project_context()
    contract = _comparative_contract(project)
    contract["required_slots"].append("boundary_case")
    contract["slot_definitions"]["boundary_case"] = _definition(
        "limiting regime",
        "thermal shock",
    )
    subhypothesis = _compiled(contract, project)
    tasks = {task["slot_name"]: task for task in subhypothesis["slot_recovery_tasks"]}
    base_papers = associate_papers_with_subhypotheses(
        [
            _paper(
                "W-main",
                "A comparative benchmark evaluation measures adaptive material and reference alloy durability under thermal cycling.",
                [
                    tasks["candidate"]["task_id"],
                    tasks["comparator"]["task_id"],
                    tasks["comparison_condition"]["task_id"],
                    tasks["comparable_endpoint"]["task_id"],
                ],
            ),
            _paper(
                "W-conflict",
                "A thermal shock failure analysis reports a negative result for adaptive material durability.",
                [tasks["boundary_case"]["task_id"]],
            ),
        ],
        [subhypothesis],
    )
    ledger_before = build_evidence_coverage_ledger(base_papers, [subhypothesis])
    refinement_plan = build_evidence_refinement_plan(
        project,
        [subhypothesis],
        ledger_before,
    )
    replication_task = next(
        task
        for task in refinement_plan["active_tasks"]
        if task["refinement_kind"] == "REPLICATION_CONTRADICTION_RESOLUTION"
    )
    resolution_candidate = {
        **_paper(
            "W-resolution",
            "An independent replication examines contradictory durability findings for adaptive materials.",
            [],
        ),
        "retrieval_provenance": [
            {
                "sub_hypothesis_id": "adaptive_materials",
                "refinement_task_id": replication_task["task_id"],
                "resolution_slot_task_ids": replication_task["resolution_slot_task_ids"],
                "resolution_target": "conflict_or_comparability",
            }
        ],
    }
    final_papers = associate_papers_with_subhypotheses(
        [*base_papers, resolution_candidate],
        [subhypothesis],
    )
    ledger_after = build_evidence_coverage_ledger(final_papers, [subhypothesis])
    resolution_summary = refinement_execution_summary(
        final_papers,
        refinement_plan,
        ledger_before,
        ledger_after,
    )
    ledger_after["refinement_resolution"] = resolution_summary[
        "refinement_resolution"
    ]

    before_report = ledger_before["subhypotheses"][0]
    after_report = ledger_after["subhypotheses"][0]
    assert after_report["covered_slots"] == before_report["covered_slots"]
    assert (
        after_report["conclusion_admissibility"]
        == before_report["conclusion_admissibility"]
    )
    assert ledger_after["refinement_resolution"] == [
        record
        for record in resolution_summary["refinement_resolution"]
    ]
    assert any(
        record["task_id"] == replication_task["task_id"]
        and record["resolution_status"]
        == "CANDIDATES_RETRIEVED_PENDING_EVALUATION"
        for record in ledger_after["refinement_resolution"]
    )


def test_second_stage_measurement_task_can_explicitly_recover_missing_slots() -> None:
    project = _project_context()
    subhypothesis = _compiled(_comparative_contract(project), project)
    tasks = {task["slot_name"]: task for task in subhypothesis["slot_recovery_tasks"]}
    initial_papers = associate_papers_with_subhypotheses(
        [
            _paper(
                "W-candidate",
                "A comparative benchmark evaluation tests an adaptive material under thermal cycling.",
                [tasks["candidate"]["task_id"]],
            )
        ],
        [subhypothesis],
    )
    initial_ledger = build_evidence_coverage_ledger(initial_papers, [subhypothesis])
    refinement_plan = build_evidence_refinement_plan(
        project,
        [subhypothesis],
        initial_ledger,
    )
    measurement_task = next(
        task
        for task in refinement_plan["active_tasks"]
        if task["refinement_kind"] == "MEASUREMENT_VALIDATION"
    )
    assert {
        task["refinement_kind"] for task in refinement_plan["active_tasks"]
    } == {"MEASUREMENT_VALIDATION"}
    assert measurement_task["target_slot_recovery_task_ids"] == [
        "adaptive_materials.comparable_endpoint"
    ]

    recovered_papers = associate_papers_with_subhypotheses(
        [
            *initial_papers,
            {
                **_paper(
                    "W-refined",
                    "A comparative benchmark evaluation measures adaptive material and reference alloy durability under thermal cycling.",
                    [],
                ),
                "retrieval_provenance": [
                    {
                        "sub_hypothesis_id": "adaptive_materials",
                        "refinement_task_id": measurement_task["task_id"],
                        "refinement_kind": "MEASUREMENT_VALIDATION",
                        "recovered_slot_task_ids": measurement_task[
                            "target_slot_recovery_task_ids"
                        ],
                    }
                ],
            },
        ],
        [subhypothesis],
    )
    final_ledger = build_evidence_coverage_ledger(recovered_papers, [subhypothesis])
    summary = refinement_execution_summary(
        recovered_papers,
        refinement_plan,
        initial_ledger,
        final_ledger,
    )

    assert final_ledger["subhypotheses"][0]["missing_slots"] == [
        "comparator",
        "comparison_condition",
    ]
    assert (
        final_ledger["subhypotheses"][0]["conclusion_admissibility"]["admissible"]
        is False
    )
    task_report = next(
        report
        for report in summary["task_reports"]
        if report["task_id"] == measurement_task["task_id"]
    )
    assert task_report["candidate_paper_ids"] == ["W-refined"]
    assert task_report["recovered_slot_task_ids"] == measurement_task[
        "target_slot_recovery_task_ids"
    ]
    assert task_report["status"] == "RECOVERED_SLOT_COVERAGE"


def test_second_stage_generalization_task_requires_a_transport_signal() -> None:
    project = _project_context()
    subhypothesis = _compiled(_generalization_contract(project), project)
    source_task = subhypothesis["slot_recovery_tasks"][0]["task_id"]
    ledger = _ledger(
        [
            _paper(
                "W-source",
                "A benchmark evaluation reports adaptive material durability for laboratory specimens under thermal cycling.",
                [source_task],
            )
        ],
        subhypothesis,
    )

    refinement_plan = build_evidence_refinement_plan(
        project,
        [subhypothesis],
        ledger,
    )
    generalization_task = next(
        task
        for task in refinement_plan["active_tasks"]
        if task["refinement_kind"] == "GENERALIZATION_TEST"
    )

    assert "generalization_question" in generalization_task["activation_reasons"]
    assert generalization_task["target_slot_recovery_task_ids"] == [
        "adaptive_materials_transport.target_system",
        "adaptive_materials_transport.shift_or_variation",
        "adaptive_materials_transport.external_validation",
    ]
    assert any(
        lane["lane"] == "broad_anchor" and not lane["hard_filter_applied"]
        for lane in generalization_task["retrieval_plan"]["query_lanes"]
    )
