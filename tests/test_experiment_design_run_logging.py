from __future__ import annotations

from io import StringIO
import json
from pathlib import Path

import pytest

from src.agents.experiment_design_agent.run_logging import (
    LOGGING_SCHEMA_VERSION,
    ExperimentDesignRunLogger,
    RunLoggingError,
)
from src.agents.experiment_design_agent.llm_json import validation_summary


def test_logger_writes_structured_events_to_console_and_jsonl(tmp_path: Path) -> None:
    console = StringIO()
    log_path = tmp_path / "logs" / "experiment_design.jsonl"
    logger = ExperimentDesignRunLogger(
        "run-1",
        jsonl_path=log_path,
        console_stream=console,
        console_level="INFO",
    )

    logger.event("intake", "loaded", status="COMPLETED", artifact_count=3)
    with logger.stage("prepare", discipline_ids=["25"]):
        pass
    logger.close()

    records = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    assert [record["event"] for record in records] == ["loaded", "started", "completed"]
    assert all(record["schema_version"] == LOGGING_SCHEMA_VERSION for record in records)
    assert all(record["run_id"] == "run-1" for record in records)
    assert records[0]["stage"] == "intake"
    assert records[1]["status"] == "RUNNING"
    assert records[2]["status"] == "COMPLETED"
    assert records[2]["elapsed_ms"] >= 0
    assert "stage=prepare" in console.getvalue()


def test_logger_records_exception_and_elapsed_time_then_reraises(tmp_path: Path) -> None:
    logger = ExperimentDesignRunLogger(
        "run-2",
        jsonl_path=tmp_path / "run.jsonl",
        console_enabled=False,
    )

    with pytest.raises(RuntimeError, match="broken stage"):
        with logger.stage("compose", design_id="design-1"):
            raise RuntimeError("broken stage")
    logger.close()

    record = json.loads((tmp_path / "run.jsonl").read_text(encoding="utf-8").splitlines()[-1])
    assert record["stage"] == "compose"
    assert record["event"] == "failed"
    assert record["status"] == "FAILED"
    assert record["level"] == "ERROR"
    assert record["error_code"] == "RuntimeError"
    assert record["exception_type"] == "RuntimeError"
    assert record["error"] == "broken stage"
    assert record["elapsed_ms"] >= 0


def test_logger_redacts_sensitive_fields_and_filters_console_level(tmp_path: Path) -> None:
    console = StringIO()
    logger = ExperimentDesignRunLogger(
        "run-3",
        jsonl_path=tmp_path / "run.jsonl",
        console_stream=console,
        console_level="WARNING",
    )
    logger.event("llm", "started", level="INFO", prompt="do not persist this prompt")
    logger.event(
        "llm",
        "failed",
        level="ERROR",
        status="FAILED",
        raw_response="private response",
        api_key="secret-value",
        nested={"patient_data": "private patient record"},
    )
    logger.close()

    records = [json.loads(line) for line in (tmp_path / "run.jsonl").read_text(encoding="utf-8").splitlines()]
    assert records[0]["prompt"] == "[REDACTED]"
    assert records[1]["raw_response"] == "[REDACTED]"
    assert records[1]["api_key"] == "[REDACTED]"
    assert records[1]["nested"]["patient_data"] == "[REDACTED]"
    console_text = console.getvalue()
    assert "event=started" not in console_text
    assert "event=failed" in console_text
    assert "private response" not in console_text
    assert "secret-value" not in console_text


def test_logger_rejects_conflicting_file_arguments(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="only one"):
        ExperimentDesignRunLogger(
            "run-4",
            jsonl_path=tmp_path / "a.jsonl",
            log_file=tmp_path / "b.jsonl",
        )


def test_logger_raises_explicit_error_when_file_sink_is_directory(tmp_path: Path) -> None:
    directory = tmp_path / "directory"
    directory.mkdir()

    with pytest.raises(RunLoggingError, match="Cannot open log file"):
        ExperimentDesignRunLogger("run-5", jsonl_path=directory)


def test_validation_summary_keeps_schema_path_and_type_without_value() -> None:
    summary = validation_summary(
        ["$/sampling_and_eligibility/eligibility_criteria: 123 is not of type 'object'"]
    )

    assert summary["validation_errors"] == ["$/sampling_and_eligibility/eligibility_criteria:type_mismatch"]
    assert "123" not in str(summary)


def test_validation_summary_keeps_safe_additional_property_names_without_values() -> None:
    secret_key = "SECRET123"
    unsafe_key = "do-not-log-this-key"
    summary = validation_summary([
        "$/analysis_plan: Additional properties are not allowed "
        f"('proof_strategy', '{secret_key}', '{unsafe_key}' were unexpected)"
    ])

    assert summary["validation_errors"] == [
        "$/analysis_plan:additional_property:safe_unexpected_keys=proof_strategy"
    ]
    assert secret_key not in str(summary)
    assert unsafe_key not in str(summary)


def test_validation_summary_removes_dynamic_contract_error_values() -> None:
    secret_symbol = "SECRET123"
    summary = validation_summary(
        [f"formal_reasoning_plan.propositions[0]_undefined_symbol:{secret_symbol}"]
    )

    assert summary["validation_errors"] == ["formal_reasoning_plan.propositions[0]_undefined_symbol"]
    assert secret_symbol not in str(summary)


def test_validation_summary_keeps_fixed_contract_field_identifier() -> None:
    summary = validation_summary(
        ["formal_theory_sampling_must_be_not_applicable:eligibility_criteria"]
    )

    assert summary["validation_errors"] == [
        "formal_theory_sampling_must_be_not_applicable:eligibility_criteria"
    ]


def test_validation_summary_keeps_safe_structural_contract_paths() -> None:
    summary = validation_summary(
        [
            "formal_reasoning_plan.propositions[1]_missing:symbol_references",
            "field_status_evidence_not_qualified:analysis_plan.statistical_analysis",
            "formal_reasoning_plan.propositions[1]_undefined_symbol:do_not_log_this",
        ]
    )

    assert summary["validation_errors"] == [
        "formal_reasoning_plan.propositions[1]_missing:symbol_references",
        "field_status_evidence_not_qualified:analysis_plan.statistical_analysis",
        "formal_reasoning_plan.propositions[1]_undefined_symbol",
    ]
