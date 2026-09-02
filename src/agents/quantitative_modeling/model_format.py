"""Canonical, non-executable quantitative mathematical-model specifications."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping, Sequence
from typing import Any

from src.agents.quantitative_modeling.mathir import MathIRValidationError, validate_mathir_document


QUANTITATIVE_MODEL_SPEC_SCHEMA_VERSION = "ieee_math_model_v1"
QUANTITATIVE_MODEL_SPEC_SCHEMA_VERSION_V2 = "ieee_math_model_v2"
QUANTITATIVE_MODEL_SPEC_SCHEMA_VERSIONS = frozenset(
    {QUANTITATIVE_MODEL_SPEC_SCHEMA_VERSION, QUANTITATIVE_MODEL_SPEC_SCHEMA_VERSION_V2}
)
_QUANTITATIVE_ID = re.compile(r"Q[1-2]")
_EQUATION_ID = re.compile(r"Q[1-2]-EQ-\d{3}")
_SAFE_LATEX_FORBIDDEN = re.compile(
    r"\\(?:input|include|write|openout|read|usepackage|catcode|immediate|shellescape)\b",
    re.IGNORECASE,
)


class QuantitativeModelFormatError(ValueError):
    """Raised when the LLM model document is not a bounded declarative specification."""


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _text(value: object) -> str:
    return str(value or "").strip()


def _required_text(payload: Mapping[str, object], field: str) -> str:
    result = _text(payload.get(field))
    if not result:
        raise QuantitativeModelFormatError(f"{field} is required")
    return result


def _number(value: object, *, field: str) -> float:
    if isinstance(value, bool):
        raise QuantitativeModelFormatError(f"{field} must be numeric")
    try:
        result = float(value)
    except (TypeError, ValueError) as error:
        raise QuantitativeModelFormatError(f"{field} must be numeric") from error
    if not math.isfinite(result):
        raise QuantitativeModelFormatError(f"{field} must be finite")
    return result


def _text_list(value: object, *, field: str, allow_empty: bool = False) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise QuantitativeModelFormatError(f"{field} must be a list")
    normalized = [_text(item) for item in value]
    if any(not item for item in normalized):
        raise QuantitativeModelFormatError(f"{field} cannot contain empty text")
    if not allow_empty and not normalized:
        raise QuantitativeModelFormatError(f"{field} must not be empty")
    return list(dict.fromkeys(normalized))


def _safe_latex(value: object, *, field: str) -> str:
    latex = _required_text({field: value}, field)
    if _SAFE_LATEX_FORBIDDEN.search(latex):
        raise QuantitativeModelFormatError(f"{field} contains an unsafe TeX control sequence")
    if "\x00" in latex or len(latex) > 2_000:
        raise QuantitativeModelFormatError(f"{field} is not a bounded TeX expression")
    return latex


def _normalize_lineage(value: object) -> dict[str, Any]:
    lineage = _mapping(value)
    required = (
        "science_run_id",
        "survey_run_id",
        "project_id",
        "project_context_fingerprint",
        "selected_direction_id",
        "quantitative_idea_id",
        "created_from_artifact",
    )
    normalized = {field: _required_text(lineage, field) for field in required}
    quantitative_idea_id = normalized["quantitative_idea_id"]
    if not _QUANTITATIVE_ID.fullmatch(quantitative_idea_id):
        raise QuantitativeModelFormatError("lineage.quantitative_idea_id must be Q1 or Q2")
    version_raw = lineage.get("version")
    if isinstance(version_raw, bool):
        raise QuantitativeModelFormatError("lineage.version must be an integer")
    try:
        version = int(version_raw)
    except (TypeError, ValueError) as exc:
        raise QuantitativeModelFormatError("lineage.version must be an integer") from exc
    if version < 0 or version > 2:
        raise QuantitativeModelFormatError("lineage.version must be between 0 and 2")
    parent_raw = lineage.get("parent_version")
    if parent_raw is None:
        parent_version: int | None = None
    else:
        if isinstance(parent_raw, bool):
            raise QuantitativeModelFormatError("lineage.parent_version must be an integer or null")
        try:
            parent_version = int(parent_raw)
        except (TypeError, ValueError) as exc:
            raise QuantitativeModelFormatError(
                "lineage.parent_version must be an integer or null"
            ) from exc
        if parent_version < 0 or parent_version >= version:
            raise QuantitativeModelFormatError("lineage.parent_version must precede lineage.version")
    if version == 0 and parent_version is not None:
        raise QuantitativeModelFormatError("v0 must not have a parent version")
    if version > 0 and parent_version != version - 1:
        raise QuantitativeModelFormatError("each revision must directly descend from its prior version")
    return {**normalized, "version": version, "parent_version": parent_version}


def _normalize_assumptions(value: object) -> list[dict[str, str]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise QuantitativeModelFormatError("assumptions must be a list")
    assumptions: list[dict[str, str]] = []
    identifiers: set[str] = set()
    for index, raw in enumerate(value):
        item = _mapping(raw)
        assumption_id = _required_text(item, "assumption_id")
        if assumption_id in identifiers:
            raise QuantitativeModelFormatError("assumption_id values must be unique")
        identifiers.add(assumption_id)
        assumptions.append(
            {
                "assumption_id": assumption_id,
                "statement": _required_text(item, "statement"),
                "effect_if_violated": _required_text(item, "effect_if_violated"),
            }
        )
    if not assumptions:
        raise QuantitativeModelFormatError("assumptions must not be empty")
    return assumptions


def _normalize_symbols(value: object) -> list[dict[str, str]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise QuantitativeModelFormatError("symbols must be a list")
    symbols: list[dict[str, str]] = []
    identifiers: set[str] = set()
    for raw in value:
        item = _mapping(raw)
        symbol_id = _required_text(item, "symbol_id")
        if symbol_id in identifiers:
            raise QuantitativeModelFormatError("symbol_id values must be unique")
        identifiers.add(symbol_id)
        symbols.append(
            {
                "symbol_id": symbol_id,
                "latex": _safe_latex(item.get("latex"), field=f"symbols.{symbol_id}.latex"),
                "meaning": _required_text(item, "meaning"),
                "unit": _required_text(item, "unit"),
                "dimension": _required_text(item, "dimension"),
                "role": _required_text(item, "role"),
            }
        )
    if not symbols:
        raise QuantitativeModelFormatError("symbols must not be empty")
    return symbols


def _normalize_equations(value: object, *, quantitative_idea_id: str, symbol_ids: set[str]) -> list[dict[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise QuantitativeModelFormatError("equations must be a list")
    equations: list[dict[str, Any]] = []
    identifiers: set[str] = set()
    for raw in value:
        item = _mapping(raw)
        equation_id = _required_text(item, "equation_id")
        if not _EQUATION_ID.fullmatch(equation_id) or not equation_id.startswith(f"{quantitative_idea_id}-"):
            raise QuantitativeModelFormatError("equation_id must be a stable ID for this quantitative idea")
        if equation_id in identifiers:
            raise QuantitativeModelFormatError("equation_id values must be unique")
        identifiers.add(equation_id)
        where_symbol_ids = _text_list(item.get("where_symbol_ids"), field=f"{equation_id}.where_symbol_ids")
        unknown = set(where_symbol_ids) - symbol_ids
        if unknown:
            raise QuantitativeModelFormatError(f"{equation_id} references undefined symbols")
        equations.append(
            {
                "equation_id": equation_id,
                "role": _required_text(item, "role"),
                "latex": _safe_latex(item.get("latex"), field=f"{equation_id}.latex"),
                "where_symbol_ids": where_symbol_ids,
            }
        )
    if not equations:
        raise QuantitativeModelFormatError("equations must not be empty")
    return equations


def _normalize_algorithm(value: object) -> dict[str, list[str]]:
    algorithm = _mapping(value)
    return {
        "input": _text_list(algorithm.get("input"), field="algorithm.input"),
        "output": _text_list(algorithm.get("output"), field="algorithm.output"),
        "steps": _text_list(algorithm.get("steps"), field="algorithm.steps"),
    }


def _normalize_numerical_plan(value: object) -> dict[str, Any]:
    plan = _mapping(value)
    return {
        "solver_family": _required_text(plan, "solver_family"),
        "discretization": _required_text(plan, "discretization"),
        "convergence_checks": _text_list(plan.get("convergence_checks"), field="numerical_plan.convergence_checks"),
    }


def _normalize_parameter_provenance(value: object) -> dict[str, Any]:
    """Keep legacy models readable while identifying evidence-bound models."""

    provenance = _mapping(value)
    if not provenance:
        return {
            "mode": "LEGACY_INLINE_ASSUMPTIONS",
            "parameter_set_identity": "",
            "entries": [],
        }
    mode = _required_text(provenance, "mode")
    if mode == "LEGACY_INLINE_ASSUMPTIONS":
        if provenance != {
            "mode": "LEGACY_INLINE_ASSUMPTIONS",
            "parameter_set_identity": "",
            "entries": [],
        }:
            raise QuantitativeModelFormatError("legacy parameter_provenance cannot carry evidence-bound fields")
        return dict(provenance)
    if mode != "APPROVED_PARAMETER_SET":
        raise QuantitativeModelFormatError("parameter_provenance.mode is unsupported")
    identity = _required_text(provenance, "parameter_set_identity")
    if not re.fullmatch(r"[0-9a-f]{64}", identity):
        raise QuantitativeModelFormatError("parameter_provenance.parameter_set_identity must be a SHA-256 digest")
    raw_entries = provenance.get("entries")
    if not isinstance(raw_entries, Sequence) or isinstance(raw_entries, (str, bytes, bytearray)) or not raw_entries:
        raise QuantitativeModelFormatError("evidence-bound parameter_provenance.entries must be a non-empty list")
    entries: list[dict[str, Any]] = []
    symbols: set[str] = set()
    for index, raw_entry in enumerate(raw_entries):
        entry = _mapping(raw_entry)
        symbol = _required_text(entry, "mathir_symbol")
        if symbol in symbols:
            raise QuantitativeModelFormatError("parameter_provenance MathIR symbols must be unique")
        symbols.add(symbol)
        role = _required_text(entry, "role")
        if role not in {"MATERIAL_PROPERTY", "SCENARIO_INPUT", "BOUNDARY_CONDITION", "MODEL_ASSUMPTION"}:
            raise QuantitativeModelFormatError("parameter_provenance entry role is unsupported")
        entries.append(
            {
                "parameter_id": _required_text(entry, "parameter_id"),
                "mathir_symbol": symbol,
                "selected_value": _number(entry.get("selected_value"), field=f"parameter_provenance[{index}].selected_value"),
                "unit": _required_text(entry, "unit"),
                "role": role,
                "provenance_status": _required_text(entry, "provenance_status"),
                "source": _mapping(entry.get("source")),
                "evidence_locator": _mapping(entry.get("evidence_locator")),
                "conditions": _mapping(entry.get("conditions")),
                "uncertainty": _mapping(entry.get("uncertainty")),
                "transformation": _mapping(entry.get("transformation")),
                "selection_rationale": _required_text(entry, "selection_rationale"),
            }
        )
    return {"mode": mode, "parameter_set_identity": identity, "entries": entries}


def normalize_quantitative_model_spec(value: object) -> dict[str, Any]:
    """Validate the fact-source JSON for one Q version before static audit."""

    payload = _mapping(value)
    schema_version = _text(payload.get("schema_version"))
    if schema_version not in QUANTITATIVE_MODEL_SPEC_SCHEMA_VERSIONS:
        raise QuantitativeModelFormatError("unsupported quantitative model specification schema")
    lineage = _normalize_lineage(payload.get("lineage"))
    symbols = _normalize_symbols(payload.get("symbols"))
    equations = _normalize_equations(
        payload.get("equations"),
        quantitative_idea_id=lineage["quantitative_idea_id"],
        symbol_ids={symbol["symbol_id"] for symbol in symbols},
    )
    normalized_execution_ir: dict[str, Any] | None = None
    if schema_version == QUANTITATIVE_MODEL_SPEC_SCHEMA_VERSION:
        try:
            mathir = validate_mathir_document(_mapping(payload.get("mathir")))
        except MathIRValidationError as exc:
            raise QuantitativeModelFormatError(f"mathir is invalid: {exc}") from exc
    else:
        from src.agents.quantitative_modeling.execution_ir import (
            ExecutionIRValidationError,
            validate_execution_ir,
        )

        if payload.get("mathir") not in (None, {}):
            raise QuantitativeModelFormatError("ieee_math_model_v2 must not carry a legacy mathir document")
        try:
            normalized_execution_ir = validate_execution_ir(payload.get("execution_ir"))
        except ExecutionIRValidationError as exc:
            raise QuantitativeModelFormatError(f"execution_ir is invalid: {exc}") from exc
        mathir = None
    result = {
        "schema_version": schema_version,
        "lineage": lineage,
        "title": _required_text(payload, "title"),
        "abstract": _required_text(payload, "abstract"),
        "scientific_question": _required_text(payload, "scientific_question"),
        "model_scope": _required_text(payload, "model_scope"),
        "assumptions": _normalize_assumptions(payload.get("assumptions")),
        "symbols": symbols,
        "equations": equations,
        "initial_conditions": _text_list(payload.get("initial_conditions"), field="initial_conditions"),
        "boundary_conditions": _text_list(payload.get("boundary_conditions"), field="boundary_conditions"),
        "parameterization": _text_list(payload.get("parameterization"), field="parameterization"),
        "scenarios": _text_list(payload.get("scenarios"), field="scenarios"),
        "objective_and_constraints": _text_list(
            payload.get("objective_and_constraints"),
            field="objective_and_constraints",
        ),
        "algorithm": _normalize_algorithm(payload.get("algorithm")),
        "numerical_plan": _normalize_numerical_plan(payload.get("numerical_plan")),
        "validation_plan": _text_list(payload.get("validation_plan"), field="validation_plan"),
        "limitations": _text_list(payload.get("limitations"), field="limitations"),
        "references": _text_list(payload.get("references", []), field="references", allow_empty=True),
        "mathir": mathir,
        "parameter_provenance": _normalize_parameter_provenance(payload.get("parameter_provenance")),
    }
    if normalized_execution_ir is not None:
        result["execution_ir"] = normalized_execution_ir
    return result


def model_spec_identity(specification: Mapping[str, object]) -> str:
    """Return the stable digest of one normalized mathematical model specification."""

    normalized = normalize_quantitative_model_spec(specification)
    raw = json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


__all__ = [
    "QUANTITATIVE_MODEL_SPEC_SCHEMA_VERSION",
    "QUANTITATIVE_MODEL_SPEC_SCHEMA_VERSION_V2",
    "QUANTITATIVE_MODEL_SPEC_SCHEMA_VERSIONS",
    "QuantitativeModelFormatError",
    "model_spec_identity",
    "normalize_quantitative_model_spec",
]
