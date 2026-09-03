"""Append-only result ledgers that retain both favorable and unfavorable outcomes."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from typing import Any

from src.agents.quantitative_modeling.result_qualification import RELATION_VALUES


RESULT_LEDGER_SCHEMA_VERSION = "quantitative_result_ledger_v1"


class ResultLedgerError(ValueError):
    """Raised when a result ledger would lose provenance or overwrite a run."""


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _text(value: object) -> str:
    return str(value or "").strip()


def _identity(value: object) -> dict[str, Any]:
    raw = _mapping(value)
    required = ("science_run_id", "quantitative_idea_id", "version")
    result = {key: raw.get(key) for key in required}
    if not _text(result["science_run_id"]):
        raise ResultLedgerError("model_identity.science_run_id is required")
    if result["quantitative_idea_id"] not in {"Q1", "Q2"}:
        raise ResultLedgerError("model_identity.quantitative_idea_id must be Q1 or Q2")
    try:
        version = int(result["version"])
    except (TypeError, ValueError) as exc:
        raise ResultLedgerError("model_identity.version must be an integer") from exc
    if version < 0 or version > 2:
        raise ResultLedgerError("model_identity.version must be between 0 and 2")
    return {"science_run_id": _text(result["science_run_id"]), "quantitative_idea_id": result["quantitative_idea_id"], "version": version}


def create_result_ledger(*, model_identity: Mapping[str, object]) -> dict[str, Any]:
    return {
        "schema_version": RESULT_LEDGER_SCHEMA_VERSION,
        "model_identity": _identity(model_identity),
        "entries": [],
    }


def validate_result_ledger(value: object) -> dict[str, Any]:
    payload = _mapping(value)
    if payload.get("schema_version") != RESULT_LEDGER_SCHEMA_VERSION:
        raise ResultLedgerError("unsupported result ledger schema")
    identity = _identity(payload.get("model_identity"))
    raw_entries = payload.get("entries")
    if not isinstance(raw_entries, Sequence) or isinstance(raw_entries, (str, bytes, bytearray)):
        raise ResultLedgerError("result ledger entries must be a list")
    entries: list[dict[str, Any]] = []
    execution_ids: set[str] = set()
    for raw_entry in raw_entries:
        entry = _mapping(raw_entry)
        execution_id = _text(entry.get("execution_id"))
        if not execution_id or execution_id in execution_ids:
            raise ResultLedgerError("result ledger execution_id values must be non-empty and unique")
        execution_ids.add(execution_id)
        entry_identity = _identity(entry.get("model_identity"))
        if entry_identity != identity:
            raise ResultLedgerError("result ledger entry has a different model identity")
        quality = _text(entry.get("result_quality"))
        if quality not in {"QUALIFIED", "UNQUALIFIED"}:
            raise ResultLedgerError("result ledger entry has an unsupported result quality")
        relation = _text(entry.get("hypothesis_relation"))
        if relation not in RELATION_VALUES:
            raise ResultLedgerError("result ledger entry has an unsupported hypothesis relation")
        if quality != "QUALIFIED" and relation != "INCONCLUSIVE":
            raise ResultLedgerError("unqualified entries must not assert a hypothesis relation")
        entries.append(
            {
                "execution_id": execution_id,
                "plan_identity": _text(entry.get("plan_identity")),
                "model_identity": entry_identity,
                "result_quality": quality,
                "hypothesis_relation": relation,
                "result_summary": _text(entry.get("result_summary")),
                "execution_record_path": _text(entry.get("execution_record_path")),
                "qualification_path": _text(entry.get("qualification_path")),
                "reason": _text(entry.get("reason")),
            }
        )
    return {"schema_version": RESULT_LEDGER_SCHEMA_VERSION, "model_identity": identity, "entries": entries}


def append_result_ledger_entry(
    ledger: Mapping[str, object] | None,
    *,
    execution: Mapping[str, object],
    qualification: Mapping[str, object],
    result_summary: str,
    execution_record_path: str,
    qualification_path: str,
) -> dict[str, Any]:
    """Return a new ledger with one immutable result reference appended."""

    normalized = (
        validate_result_ledger(ledger)
        if ledger is not None
        else create_result_ledger(model_identity=_mapping(execution.get("model_identity")))
    )
    execution_id = _text(execution.get("execution_id"))
    if not execution_id:
        raise ResultLedgerError("execution record has no execution_id")
    if any(entry["execution_id"] == execution_id for entry in normalized["entries"]):
        raise ResultLedgerError("an execution may be appended to a ledger only once")
    model_identity = _identity(execution.get("model_identity"))
    if model_identity != normalized["model_identity"]:
        raise ResultLedgerError("execution record does not match the ledger model identity")
    qualification_identity = _identity(qualification.get("model_identity"))
    if qualification_identity != model_identity:
        raise ResultLedgerError("qualification does not match the execution model identity")
    if _text(qualification.get("execution_id")) != execution_id:
        raise ResultLedgerError("qualification does not match the execution ID")
    entry = {
        "execution_id": execution_id,
        "plan_identity": _text(execution.get("plan_identity")),
        "model_identity": model_identity,
        "result_quality": _text(qualification.get("result_quality")),
        "hypothesis_relation": _text(qualification.get("hypothesis_relation")),
        "result_summary": _text(result_summary),
        "execution_record_path": _text(execution_record_path),
        "qualification_path": _text(qualification_path),
        "reason": _text(qualification.get("reason")),
    }
    return validate_result_ledger({**deepcopy(normalized), "entries": [*normalized["entries"], entry]})


def qualified_ledger_entries(ledger: Mapping[str, object]) -> list[dict[str, Any]]:
    """Return every qualified entry, including constrained and refuting outcomes."""

    normalized = validate_result_ledger(ledger)
    return [deepcopy(entry) for entry in normalized["entries"] if entry["result_quality"] == "QUALIFIED"]


__all__ = [
    "RESULT_LEDGER_SCHEMA_VERSION",
    "ResultLedgerError",
    "append_result_ledger_entry",
    "create_result_ledger",
    "qualified_ledger_entries",
    "validate_result_ledger",
]
