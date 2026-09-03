"""Strict, small Author-facing contract for qualified numerical simulations."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from copy import deepcopy
from typing import Any


QUANTITATIVE_AUTHOR_HANDOFF_SCHEMA_VERSION = "quantitative_author_handoff_v1"


class QuantitativeEvidenceContractError(ValueError):
    """Raised when raw models or non-qualified simulation records reach Author."""


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _text(value: object) -> str:
    return str(value or "").strip()


def _text_list(value: object, *, field: str) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise QuantitativeEvidenceContractError(f"{field} must be a list")
    normalized = [_text(item) for item in value]
    if any(not item for item in normalized):
        raise QuantitativeEvidenceContractError(f"{field} cannot contain empty values")
    return list(dict.fromkeys(normalized))


def _normalize_numerical_quality(value: object) -> dict[str, Any]:
    quality = _mapping(value)
    status = _text(quality.get("status")) or "NOT_REPORTED"
    if status not in {"NUMERICALLY_VERIFIED", "NUMERICALLY_UNVERIFIED", "NOT_REPORTED"}:
        raise QuantitativeEvidenceContractError("quantitative numerical quality status is unsupported")
    raw_statuses = quality.get("scenario_statuses", [])
    if not isinstance(raw_statuses, list):
        raise QuantitativeEvidenceContractError("quantitative numerical quality scenario_statuses must be a list")
    scenario_statuses = [_text(item) for item in raw_statuses]
    if any(not item for item in scenario_statuses):
        raise QuantitativeEvidenceContractError("quantitative numerical quality scenario statuses cannot be empty")
    return {"status": status, "scenario_statuses": list(dict.fromkeys(scenario_statuses))}


def _identity(value: object) -> dict[str, str]:
    payload = _mapping(value)
    fields = (
        "science_run_id",
        "survey_run_id",
        "project_id",
        "project_context_fingerprint",
        "selected_direction_id",
    )
    normalized = {field: _text(payload.get(field)) for field in fields}
    if any(not value for value in normalized.values()):
        raise QuantitativeEvidenceContractError("quantitative Author handoff has incomplete source_identity")
    return normalized


def _normalize_parameter_provenance(value: object) -> dict[str, Any]:
    """Allow Author to receive a compact, explicit parameter-source boundary."""

    provenance = _mapping(value)
    if not provenance:
        return {"mode": "LEGACY_INLINE_ASSUMPTIONS", "parameter_set_identity": "", "entries": []}
    mode = _text(provenance.get("mode"))
    if mode == "LEGACY_INLINE_ASSUMPTIONS":
        if provenance != {"mode": "LEGACY_INLINE_ASSUMPTIONS", "parameter_set_identity": "", "entries": []}:
            raise QuantitativeEvidenceContractError("legacy parameter provenance cannot carry source fields")
        return dict(provenance)
    if mode != "APPROVED_PARAMETER_SET":
        raise QuantitativeEvidenceContractError("quantitative parameter provenance mode is unsupported")
    parameter_set_identity = _text(provenance.get("parameter_set_identity"))
    if not re.fullmatch(r"[0-9a-f]{64}", parameter_set_identity):
        raise QuantitativeEvidenceContractError("approved parameter provenance requires a SHA-256 identity")
    raw_entries = provenance.get("entries")
    if not isinstance(raw_entries, list) or not raw_entries:
        raise QuantitativeEvidenceContractError("approved parameter provenance requires non-empty entries")
    entries: list[dict[str, Any]] = []
    for raw_entry in raw_entries:
        entry = _mapping(raw_entry)
        provenance_status = _text(entry.get("provenance_status"))
        if provenance_status not in {
            "APPROVED_LITERATURE_SINGLE_SOURCE",
            "APPROVED_USER_INPUT",
            "APPROVED_MODEL_ASSUMPTION",
        }:
            raise QuantitativeEvidenceContractError("parameter provenance status is unsupported")
        entries.append(
            {
                "parameter_id": _text(entry.get("parameter_id")),
                "mathir_symbol": _text(entry.get("mathir_symbol")),
                "selected_value": entry.get("selected_value"),
                "unit": _text(entry.get("unit")),
                "role": _text(entry.get("role")),
                "provenance_status": provenance_status,
                "source": _mapping(entry.get("source")),
                "evidence_locator": _mapping(entry.get("evidence_locator")),
                "conditions": _mapping(entry.get("conditions")),
                "uncertainty": _mapping(entry.get("uncertainty")),
                "transformation": _mapping(entry.get("transformation")),
                "selection_rationale": _text(entry.get("selection_rationale")),
            }
        )
    if any(not entry["parameter_id"] or not entry["mathir_symbol"] or not entry["unit"] for entry in entries):
        raise QuantitativeEvidenceContractError("parameter provenance entries have incomplete identities")
    return {
        "mode": "APPROVED_PARAMETER_SET",
        "parameter_set_identity": parameter_set_identity,
        "entries": entries,
    }


def _normalize_evidence(value: object) -> dict[str, Any]:
    evidence = _mapping(value)
    idea_id = _text(evidence.get("quantitative_idea_id"))
    if idea_id not in {"Q1", "Q2"}:
        raise QuantitativeEvidenceContractError("quantitative evidence must identify Q1 or Q2")
    version_raw = evidence.get("final_version")
    if isinstance(version_raw, bool):
        raise QuantitativeEvidenceContractError("quantitative evidence final_version must be an integer")
    try:
        version = int(version_raw)
    except (TypeError, ValueError) as exc:
        raise QuantitativeEvidenceContractError("quantitative evidence final_version must be an integer") from exc
    if version < 0 or version > 2:
        raise QuantitativeEvidenceContractError("quantitative evidence final_version must be v0, v1, or v2")
    labels = {
        "execution_mode": "NUMERICAL_SIMULATION",
        "result_kind": "SIMULATED",
        "empirical_claim_status": "NOT_EMPIRICAL",
        "result_quality": "QUALIFIED",
    }
    for field, expected in labels.items():
        if _text(evidence.get(field)) != expected:
            raise QuantitativeEvidenceContractError(f"quantitative evidence {field} must be {expected}")
    relation = _text(evidence.get("hypothesis_relation"))
    if relation not in {
        "SUPPORTED_WITHIN_MODEL",
        "CONSTRAINED",
        "REFUTED_WITHIN_MODEL",
        "INCONCLUSIVE",
    }:
        raise QuantitativeEvidenceContractError("quantitative evidence hypothesis_relation is unsupported")
    lineage: list[dict[str, Any]] = []
    for raw in evidence.get("lineage_summary") or []:
        entry = _mapping(raw)
        try:
            lineage_version = int(entry.get("version"))
        except (TypeError, ValueError) as exc:
            raise QuantitativeEvidenceContractError("lineage_summary version must be an integer") from exc
        lineage_relation = _text(entry.get("relation"))
        if lineage_relation not in {
            "SUPPORTED_WITHIN_MODEL",
            "CONSTRAINED",
            "REFUTED_WITHIN_MODEL",
            "INCONCLUSIVE",
        }:
            raise QuantitativeEvidenceContractError("lineage_summary relation is unsupported")
        lineage.append({"version": lineage_version, "relation": lineage_relation, "reason": _text(entry.get("reason"))})
    if not lineage:
        raise QuantitativeEvidenceContractError("quantitative evidence must include its iteration lineage")
    reference = _text(evidence.get("supplement_pdf_reference"))
    if reference != f"quantitative_mathematical_models.pdf#{idea_id}":
        raise QuantitativeEvidenceContractError("quantitative evidence has an invalid supplementary PDF reference")
    return {
        "quantitative_idea_id": idea_id,
        "final_version": version,
        "question": _text(evidence.get("question")),
        "model_family": _text(evidence.get("model_family")),
        **labels,
        "hypothesis_relation": relation,
        "result_summary": _text(evidence.get("result_summary")),
        "applicability_conditions": _text_list(evidence.get("applicability_conditions"), field="applicability_conditions"),
        "limitations": _text_list(evidence.get("limitations"), field="limitations"),
        "lineage_summary": lineage,
        "numerical_quality": _normalize_numerical_quality(evidence.get("numerical_quality")),
        "supplement_pdf_reference": reference,
        "parameter_provenance": _normalize_parameter_provenance(evidence.get("parameter_provenance")),
    }


def validate_quantitative_author_handoff(value: object) -> dict[str, Any]:
    payload = _mapping(value)
    if _text(payload.get("schema_version")) != QUANTITATIVE_AUTHOR_HANDOFF_SCHEMA_VERSION:
        raise QuantitativeEvidenceContractError("unsupported quantitative Author handoff schema")
    evidence = [_normalize_evidence(item) for item in payload.get("evidence") or []]
    if not evidence:
        raise QuantitativeEvidenceContractError("quantitative Author handoff needs qualified evidence")
    return {
        "schema_version": QUANTITATIVE_AUTHOR_HANDOFF_SCHEMA_VERSION,
        "source_identity": _identity(payload.get("source_identity")),
        "evidence": evidence,
    }


def quantitative_evidence_capsule(handoff: Mapping[str, object]) -> dict[str, Any]:
    """Copy only allowed, reviewed fields into an Author-consumable capsule."""

    normalized = validate_quantitative_author_handoff(handoff)
    return deepcopy(normalized)


__all__ = [
    "QUANTITATIVE_AUTHOR_HANDOFF_SCHEMA_VERSION",
    "QuantitativeEvidenceContractError",
    "quantitative_evidence_capsule",
    "validate_quantitative_author_handoff",
]
