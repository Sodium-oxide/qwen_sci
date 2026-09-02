"""Verify a quantitative handoff manifest and render a fixed Author evidence block."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from copy import deepcopy
from pathlib import Path
from typing import Any

from .quantitative_evidence_contracts import (
    QuantitativeEvidenceContractError,
    quantitative_evidence_capsule,
)


QUANTITATIVE_AUTHOR_HANDOFF_MANIFEST_SCHEMA_VERSION = "quantitative_author_handoff_manifest_v1"


class QuantitativeEvidenceLoadError(ValueError):
    """Raised when an Author request references an incomplete or foreign Q handoff."""


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _text(value: object) -> str:
    return str(value or "").strip()


def _read_json(path: Path, *, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise QuantitativeEvidenceLoadError(f"Cannot read {label}: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise QuantitativeEvidenceLoadError(f"{label} must be a JSON object")
    return dict(payload)


def load_quantitative_evidence_capsule(
    manifest_path: str | Path,
    *,
    expected_identity: Mapping[str, object],
) -> dict[str, Any]:
    """Fail closed unless the exact qualified sidecar belongs to this Author run."""

    path = Path(manifest_path).expanduser().resolve()
    manifest = _read_json(path, label="quantitative Author handoff manifest")
    if _text(manifest.get("schema_version")) != QUANTITATIVE_AUTHOR_HANDOFF_MANIFEST_SCHEMA_VERSION:
        raise QuantitativeEvidenceLoadError("unsupported quantitative Author handoff manifest schema")
    if _text(manifest.get("status")) != "COMPLETED":
        raise QuantitativeEvidenceLoadError("quantitative Author handoff manifest is not completed")
    record = _mapping(_mapping(manifest.get("artifacts")).get("handoff"))
    handoff_path = Path(_text(record.get("path"))).expanduser().resolve()
    try:
        handoff_path.relative_to(path.parent)
    except ValueError as exc:
        raise QuantitativeEvidenceLoadError("quantitative Author handoff escapes its manifest directory") from exc
    if not handoff_path.is_file():
        raise QuantitativeEvidenceLoadError("quantitative Author handoff file is missing")
    digest = hashlib.sha256(handoff_path.read_bytes()).hexdigest()
    if digest != _text(record.get("sha256")):
        raise QuantitativeEvidenceLoadError("quantitative Author handoff hash does not match its manifest")
    try:
        capsule = quantitative_evidence_capsule(_read_json(handoff_path, label="quantitative Author handoff"))
    except QuantitativeEvidenceContractError as exc:
        raise QuantitativeEvidenceLoadError(str(exc)) from exc
    manifest_identity = _mapping(manifest.get("source_identity"))
    capsule_identity = _mapping(capsule.get("source_identity"))
    if manifest_identity != capsule_identity:
        raise QuantitativeEvidenceLoadError("quantitative Author handoff manifest identity differs from its handoff")
    for field in ("survey_run_id", "project_id", "project_context_fingerprint", "selected_direction_id"):
        expected = _text(expected_identity.get(field))
        actual = _text(_mapping(capsule.get("source_identity")).get(field))
        if expected and actual != expected:
            raise QuantitativeEvidenceLoadError(f"quantitative Author handoff identity differs for {field}")
    pdf_record = _mapping(_mapping(manifest.get("artifacts")).get("quantitative_models_pdf"))
    pdf_path = Path(_text(pdf_record.get("path"))).expanduser().resolve()
    expected_pdf_path = path.parent.parent / "publication" / "quantitative_mathematical_models.pdf"
    if pdf_path != expected_pdf_path:
        raise QuantitativeEvidenceLoadError("quantitative supplementary PDF differs from this handoff's formal publication")
    if not pdf_path.is_file() or hashlib.sha256(pdf_path.read_bytes()).hexdigest() != _text(pdf_record.get("sha256")):
        raise QuantitativeEvidenceLoadError("quantitative supplementary PDF is missing or modified")
    return capsule


def append_quantitative_evidence_section(
    document: Mapping[str, object], capsule: Mapping[str, object]
) -> dict[str, Any]:
    """Append immutable numerical-evidence disclosures after LLM composition."""

    result = deepcopy(dict(document))
    blocks: list[dict[str, Any]] = []
    for index, raw_evidence in enumerate(capsule.get("evidence") or [], start=1):
        evidence = _mapping(raw_evidence)
        conditions = "; ".join(evidence.get("applicability_conditions") or [])
        limitations = "; ".join(evidence.get("limitations") or [])
        lineage = "; ".join(
            f"v{entry.get('version')}: {entry.get('relation')} ({entry.get('reason')})"
            for entry in evidence.get("lineage_summary") or []
            if isinstance(entry, Mapping)
        )
        text = " ".join(
            fragment
            for fragment in (
                f"{evidence.get('quantitative_idea_id')} (final v{evidence.get('final_version')}) answers: {evidence.get('question')}",
                f"Model family: {evidence.get('model_family')}.",
                "Execution mode: NUMERICAL_SIMULATION.",
                "Result kind: SIMULATED.",
                "Empirical claim status: NOT_EMPIRICAL.",
                f"Model-internal hypothesis relation: {evidence.get('hypothesis_relation')}.",
                f"Model-internal result summary: {evidence.get('result_summary')}",
                f"Numerical quality: {_mapping(evidence.get('numerical_quality')).get('status') or 'NOT_REPORTED'}.",
                f"Applicability conditions: {conditions}.",
                f"Limitations: {limitations}.",
                f"Iteration lineage: {lineage}.",
                f"Supplementary mathematical-model PDF: {evidence.get('supplement_pdf_reference')}.",
            )
            if fragment
        )
        blocks.append(
            {
                "block_id": f"quantitative-evidence-{index:02d}",
                "kind": "quantitative_evidence",
                "text": text,
                "claim_ids": [],
            }
        )
    result["sections"] = [
        *list(result.get("sections") or []),
        {
            "section_id": "computational_evidence",
            "title": "Computational Evidence (Numerical Simulation; Non-empirical)",
            "applicability": "required",
            "blocks": blocks,
        },
    ]
    source_manifest = _mapping(result.get("source_manifest"))
    source_manifest["quantitative_evidence"] = {
        "schema_version": capsule.get("schema_version"),
        "evidence_count": len(blocks),
        "execution_mode": "NUMERICAL_SIMULATION",
        "result_kind": "SIMULATED",
        "empirical_claim_status": "NOT_EMPIRICAL",
    }
    result["source_manifest"] = source_manifest
    return result


__all__ = [
    "QUANTITATIVE_AUTHOR_HANDOFF_MANIFEST_SCHEMA_VERSION",
    "QuantitativeEvidenceLoadError",
    "append_quantitative_evidence_section",
    "load_quantitative_evidence_capsule",
]
