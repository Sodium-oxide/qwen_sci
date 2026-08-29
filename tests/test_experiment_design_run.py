from __future__ import annotations

from io import StringIO
import json
from typing import Any

import pytest

from src.agents.experiment_design_agent import (
    ExperimentDesignOrchestrator,
    FormalReasoningPlanContractError,
)
from src.agents.experiment_design_agent.contracts import RESEARCH_BRIEF_SCHEMA_VERSION
from src.agents.experiment_design_agent.run import (
    ExperimentDesignRunError,
    run_experiment_design,
)
from src.agents.experiment_design_agent.run_logging import ExperimentDesignRunLogger
import src.agents.experiment_design_agent.run as run_module
import src.agents.experiment_design_agent.orchestrator as orchestrator_module


def _brief() -> dict[str, Any]:
    return {
        "schema_version": RESEARCH_BRIEF_SCHEMA_VERSION,
        "brief_id": "brief-materials",
        "topic": "Material interface stability",
        "discipline_ids": ["25"],
        "selected_direction": {
            "id": "selected",
            "title": "Material interface stability",
            "central_hypothesis": "The declared intervention changes the declared observable under the stated conditions.",
            "mechanism_or_relation": "The proposed interface mechanism requires a discriminating measurement.",
        },
        "research_object": {"description": "A declared material system."},
        "intervention_or_transformation": "A declared material transformation.",
        "discriminating_observations": ["A predeclared interface observable."],
        "boundary_conditions": ["A declared operating regime."],
        "alternative_explanations": ["A plausible measurement artifact."],
        "known_unknowns": ["Calibration requirements remain unresolved."],
        "evidence_status": "PROPOSED",
        "source": {
            "idea_result_schema": "idea_result_v5",
            "direction_id": "selected",
            "upstream_source_paths": {"idea_result": "/tmp/idea_result.json"},
            "missing_audit_sources": [],
        },
    }


def test_run_uses_one_preparation_plan_for_evidence_and_does_not_reprepare(
    monkeypatch,
    tmp_path,
) -> None:
    idea_path = tmp_path / "idea_result.json"
    idea_path.write_text("{}", encoding="utf-8")
    brief = _brief()
    orchestrator = ExperimentDesignOrchestrator(llm_call=lambda *_args, **_kwargs: {})
    planner_calls: list[object] = []
    evidence_calls: list[dict[str, object]] = []
    composition_calls: list[dict[str, object]] = []

    monkeypatch.setattr(
        orchestrator.idea_adapter,
        "adapt_path",
        lambda *_args, **_kwargs: brief,
    )

    def plan(_brief: object, _routing: object, *, llm_call: object) -> dict[str, object]:
        planner_calls.append(llm_call)
        return {
            "planning_status": "READY_FOR_RETRIEVAL",
            "queries": [{"task_id": "EDQ1", "slot": "mechanism", "query": "interface mechanism"}],
            "warnings": [],
        }

    monkeypatch.setattr(orchestrator.evidence_planner, "plan", plan)

    class EvidenceAdapter:
        def collect_and_extract(self, **kwargs: object) -> dict[str, object]:
            evidence_calls.append(dict(kwargs))
            return {"evidence_bundle": {"brief_id": "brief-materials", "evidence_cards": []}}

    def compose(_brief: object, **kwargs: object) -> dict[str, object]:
        composition_calls.append(dict(kwargs))
        return {"design_id": "design-1", "observed_results": []}

    monkeypatch.setattr(orchestrator, "compose_design", compose)
    monkeypatch.setattr(run_module, "validate_experiment_design", lambda _design: [])
    monkeypatch.setattr(
        orchestrator,
        "collect_survey_evidence",
        lambda *_args, **_kwargs: pytest.fail("run.py must not re-enter collect_survey_evidence"),
    )
    log_path = tmp_path / "run.jsonl"
    logger = ExperimentDesignRunLogger(
        "run-test",
        jsonl_path=log_path,
        console_stream=StringIO(),
    )

    result = run_experiment_design(
        idea_path,
        discipline_ids=["25"],
        orchestrator=orchestrator,
        survey_evidence_adapter=EvidenceAdapter(),
        logger=logger,
    )
    logger.close()

    assert result["status"] == "COMPLETED"
    assert len(planner_calls) == 1
    assert len(evidence_calls) == 1
    assert evidence_calls[0]["evidence_plan"]["planning_status"] == "READY_FOR_RETRIEVAL"
    assert len(composition_calls) == 1
    assert composition_calls[0]["evidence_bundle"] == {
        "brief_id": "brief-materials",
        "evidence_cards": [],
    }
    assert result["validation"]["status"] == "VALID"
    records = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    assert [record["stage"] for record in records] == [
        "run",
        "intake",
        "intake",
        "prepare",
        "prepare",
        "evidence",
        "evidence",
        "compose",
        "compose",
        "validation",
        "validation",
        "run",
    ]
    assert records[0]["event"] == "started"
    assert records[-1]["event"] == "completed"


def test_run_degrades_required_llm_failure_without_aborting(monkeypatch, tmp_path) -> None:
    idea_path = tmp_path / "idea_result.json"
    idea_path.write_text("{}", encoding="utf-8")
    orchestrator = ExperimentDesignOrchestrator(llm_call=lambda *_args, **_kwargs: "not-json")
    monkeypatch.setattr(
        orchestrator.idea_adapter,
        "adapt_path",
        lambda *_args, **_kwargs: _brief(),
    )

    result = run_experiment_design(
        idea_path,
        discipline_ids=["25"],
        orchestrator=orchestrator,
    )

    assert result["status"] == "COMPLETED"
    assert result["preparation"]["evidence_retrieval_plan"]["llm_used"] is False
    assert result["experiment_design"]["risk_and_human_review"]["human_review_required"] is True
    assert "LLM_OR_WORKFLOW_DEGRADATION_REVIEW" in result["experiment_design"]["risk_and_human_review"]["review_triggers"]


def test_run_preserves_and_logs_rejected_formal_reasoning_repair_audit(tmp_path) -> None:
    audit_record = {
        "schema_version": "formal_reasoning_repair_audit_v1",
        "repair_status": "REJECTED",
        "initial_candidate": {"schema_version": "formal_reasoning_plan_v1"},
        "initial_validation_errors": ["undefined_symbol:V1"],
        "repair_validation_errors": ["undefined_symbol:V1"],
    }
    logger = ExperimentDesignRunLogger(
        "reasoning-repair-failure",
        jsonl_path=tmp_path / "run.jsonl",
        console_enabled=False,
    )

    def fail() -> None:
        raise FormalReasoningPlanContractError(
            "repair rejected",
            audit_record=audit_record,
        )

    with pytest.raises(ExperimentDesignRunError) as error:
        run_module._run_stage("compose", fail, logger=logger)
    logger.close()

    assert error.value.exit_code == 6
    assert error.value.audit_record == audit_record
    records = [json.loads(line) for line in (tmp_path / "run.jsonl").read_text(encoding="utf-8").splitlines()]
    audit_events = [record for record in records if record["event"] == "formal_reasoning_contract_repair_audit"]
    assert audit_events[0]["status"] == "REJECTED"
    assert audit_events[0]["repair_status"] == "REJECTED"
    assert audit_events[0]["initial_validation_error_count"] == 1
    assert audit_events[0]["repair_validation_error_count"] == 1
    assert audit_events[0]["repaired_candidate_returned"] is False
    assert "repair_audit" not in audit_events[0]
    assert "initial_candidate" not in audit_events[0]


def test_orchestrator_run_from_preparation_reuses_plan_and_logs_stages(monkeypatch, tmp_path) -> None:
    orchestrator = ExperimentDesignOrchestrator(llm_call=lambda *_args, **_kwargs: {})
    evidence_plan = {
        "planning_status": "READY_FOR_RETRIEVAL",
        "queries": [{"task_id": "EDQ1", "slot": "mechanism", "query": "interface mechanism"}],
    }
    preparation = {
        "research_brief": _brief(),
        "scope_gate": {"status": "IN_SCOPE"},
        "evidence_retrieval_plan": evidence_plan,
    }
    evidence_calls: list[dict[str, object]] = []

    def fail_if_reprepared(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("run_from_preparation must not call prepare")

    monkeypatch.setattr(orchestrator, "prepare", fail_if_reprepared)

    class EvidenceAdapter:
        def collect_and_extract(self, **kwargs: object) -> dict[str, object]:
            evidence_calls.append(dict(kwargs))
            return {"evidence_bundle": {"brief_id": "brief-materials", "evidence_cards": []}}

    monkeypatch.setattr(
        orchestrator,
        "compose_design",
        lambda *_args, **_kwargs: {"design_id": "design-1", "observed_results": []},
    )
    monkeypatch.setattr(orchestrator_module, "validate_experiment_design", lambda _design: [])
    logger = ExperimentDesignRunLogger("orchestrator-run", jsonl_path=tmp_path / "run.jsonl")
    result = orchestrator.run_from_preparation(
        preparation,
        survey_evidence_adapter=EvidenceAdapter(),
        logger=logger,
    )
    logger.close()

    assert result["status"] == "COMPLETED"
    assert evidence_calls[0]["evidence_plan"] is evidence_plan
    assert [record["stage"] for record in logger.records] == [
        "run",
        "evidence",
        "evidence",
        "compose",
        "compose",
        "validation",
        "validation",
        "run",
    ]


def test_orchestrator_run_from_idea_path_prepares_once(monkeypatch) -> None:
    orchestrator = ExperimentDesignOrchestrator(llm_call=lambda *_args, **_kwargs: {})
    brief = _brief()
    preparation = {
        "research_brief": brief,
        "scope_gate": {"status": "IN_SCOPE"},
        "evidence_retrieval_plan": {
            "planning_status": "READY_FOR_RETRIEVAL",
            "queries": [],
        },
    }
    calls = {"adapt": 0, "prepare": 0}

    def adapt(*_args: object, **_kwargs: object) -> dict[str, object]:
        calls["adapt"] += 1
        return brief

    def prepare(*_args: object, **_kwargs: object) -> dict[str, object]:
        calls["prepare"] += 1
        return preparation

    monkeypatch.setattr(orchestrator.idea_adapter, "adapt_path", adapt)
    monkeypatch.setattr(orchestrator, "prepare", prepare)
    monkeypatch.setattr(
        orchestrator,
        "run_from_preparation",
        lambda received, **_kwargs: {
            "schema_version": "experiment_design_run_v1",
            "status": "COMPLETED",
            "preparation": received,
            "validation": {"observed_results_count": 0},
            "experiment_design": {"execution_policy": {"mode": "DESIGN_ONLY"}},
        },
    )

    result = orchestrator.run_from_idea_path("idea_result.json", discipline_ids=["25"])

    assert calls == {"adapt": 1, "prepare": 1}
    assert result["intake"]["status"] == "LOADED"
    assert result["preparation"] is preparation


def test_orchestrator_discards_an_invalid_final_candidate_and_continues(monkeypatch, tmp_path) -> None:
    orchestrator = ExperimentDesignOrchestrator(llm_call=lambda *_args, **_kwargs: {})
    preparation = {
        "research_brief": _brief(),
        "scope_gate": {"status": "IN_SCOPE"},
        "evidence_retrieval_plan": {"planning_status": "READY_FOR_RETRIEVAL", "queries": []},
    }

    class EvidenceAdapter:
        def collect_and_extract(self, **_kwargs: object) -> dict[str, object]:
            return {"evidence_bundle": {"brief_id": "brief-materials", "evidence_cards": []}}

    monkeypatch.setattr(
        orchestrator,
        "compose_design",
        lambda *_args, **_kwargs: {"design_id": "invalid-design", "observed_results": []},
    )
    monkeypatch.setattr(orchestrator_module, "validate_experiment_design", lambda _design: ["missing field"])
    logger = ExperimentDesignRunLogger("validation-failure", console_enabled=False)

    result = orchestrator.run_from_preparation(
        preparation,
        survey_evidence_adapter=EvidenceAdapter(),
        logger=logger,
    )

    validation_records = [record for record in logger.records if record["stage"] == "validation"]
    assert [record["event"] for record in validation_records] == ["started", "degraded", "completed"]
    assert result["experiment_design"]["template_composition"]["llm_used"] is False
    assert "LLM_OR_WORKFLOW_DEGRADATION_REVIEW" in result["experiment_design"]["risk_and_human_review"]["review_triggers"]
