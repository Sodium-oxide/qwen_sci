"""Manifest support for the optional quantitative modeling sidecar."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.agents.quantitative_modeling.contracts import (
    QUANTITATIVE_IDEA_MANIFEST_SCHEMA_VERSION,
    QuantitativeContractError,
    validate_quantitative_idea_set,
)
from src.pipeline.science_manifests import ScienceManifestError, verify_idea_manifest
from src.pipeline.science_run import atomic_write_json, file_sha256


class QuantitativeManifestError(ValueError):
    """Raised when an optional quantitative sidecar is not locally trustworthy."""


@dataclass(frozen=True)
class VerifiedQuantitativeIdeasManifest:
    manifest_path: Path
    ideas_path: Path
    identity: Mapping[str, str]
    payload: Mapping[str, Any]


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _text(value: object) -> str:
    return str(value or "").strip()


def _record(path: str | Path) -> dict[str, str]:
    resolved = Path(path).expanduser().resolve()
    if not resolved.is_file():
        raise QuantitativeManifestError(f"Quantitative artifact does not exist: {resolved}")
    return {"path": str(resolved), "sha256": file_sha256(resolved)}


def _verify_record(record: object, *, manifest_path: Path, label: str, local: bool) -> Path:
    payload = _mapping(record)
    raw_path = _text(payload.get("path"))
    expected_hash = _text(payload.get("sha256"))
    if not raw_path or not expected_hash:
        raise QuantitativeManifestError(f"{label} has no path or SHA-256")
    path = Path(raw_path).expanduser()
    if not path.is_absolute():
        raise QuantitativeManifestError(f"{label} path is not absolute")
    path = path.resolve()
    if local:
        try:
            path.relative_to(manifest_path.parent)
        except ValueError as exc:
            raise QuantitativeManifestError(f"{label} escapes its Idea attempt directory") from exc
    if not path.is_file():
        raise QuantitativeManifestError(f"{label} is missing: {path}")
    if file_sha256(path) != expected_hash:
        raise QuantitativeManifestError(f"{label} SHA-256 does not match its manifest")
    return path


def _identity(value: Mapping[str, object]) -> dict[str, str]:
    return {str(key): _text(item) for key, item in value.items() if _text(item)}


def _require_identity(identity: Mapping[str, object]) -> dict[str, str]:
    normalized = _identity(identity)
    for field in (
        "survey_run_id",
        "project_id",
        "project_context_fingerprint",
        "selected_direction_id",
    ):
        if not normalized.get(field):
            raise QuantitativeManifestError(f"Quantitative manifest identity is missing {field}")
    return normalized


def write_quantitative_ideas_manifest(
    *,
    attempt_dir: str | Path,
    topic: str,
    idea_manifest_path: str | Path,
    ideas_path: str | Path,
    identity: Mapping[str, object],
) -> Path:
    """Publish a verified Q idea manifest after the canonical Idea manifest exists."""

    attempt = Path(attempt_dir).expanduser().resolve()
    manifest_path = attempt / "quantitative_ideas_manifest.json"
    verified_identity = _require_identity(identity)
    try:
        idea_manifest = verify_idea_manifest(
            idea_manifest_path,
            expected_survey_identity=verified_identity,
            expected_topic=topic,
        )
    except ScienceManifestError as exc:
        raise QuantitativeManifestError(f"Canonical Idea manifest is invalid: {exc}") from exc
    ideas_record = _record(ideas_path)
    ideas_resolved = Path(ideas_record["path"])
    try:
        ideas_resolved.relative_to(attempt)
    except ValueError as exc:
        raise QuantitativeManifestError("quantitative ideas must be in the Idea attempt directory") from exc
    try:
        payload = json.loads(ideas_resolved.read_text(encoding="utf-8"))
        validate_quantitative_idea_set(
            payload,
            expected_identity=verified_identity,
            expected_topic=topic,
        )
        source_identity = _mapping(_mapping(payload).get("source_identity"))
        if Path(_text(source_identity.get("idea_result_path"))).expanduser().resolve() != idea_manifest.canonical_path:
            raise QuantitativeContractError(
                "source_identity.idea_result_path differs from the canonical Idea artifact"
            )
    except (OSError, json.JSONDecodeError, QuantitativeContractError) as exc:
        raise QuantitativeManifestError(f"Quantitative ideas are invalid: {exc}") from exc
    manifest = {
        "schema_version": QUANTITATIVE_IDEA_MANIFEST_SCHEMA_VERSION,
        "status": "COMPLETED",
        "topic": _text(topic),
        "identity": verified_identity,
        "inputs": {"idea_manifest": _record(idea_manifest.manifest_path)},
        "artifacts": {"quantitative_ideas": ideas_record},
        "metadata": {
            "generation_status": _text(_mapping(payload).get("generation_status")),
            "idea_count": len(_mapping(payload).get("ideas") or []),
        },
    }
    atomic_write_json(manifest_path, manifest)
    return manifest_path


def verify_quantitative_ideas_manifest(
    manifest_path: str | Path,
    *,
    expected_identity: Mapping[str, object] | None = None,
    expected_topic: str | None = None,
) -> VerifiedQuantitativeIdeasManifest:
    """Verify sidecar provenance before any quantitative workflow consumes it."""

    path = Path(manifest_path).expanduser().resolve()
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise QuantitativeManifestError(f"Cannot read quantitative ideas manifest: {exc}") from exc
    if not isinstance(manifest, Mapping):
        raise QuantitativeManifestError("Quantitative ideas manifest must be an object")
    if _text(manifest.get("schema_version")) != QUANTITATIVE_IDEA_MANIFEST_SCHEMA_VERSION:
        raise QuantitativeManifestError("Unsupported quantitative ideas manifest schema")
    if _text(manifest.get("status")) != "COMPLETED":
        raise QuantitativeManifestError("Quantitative ideas manifest is not completed")
    topic = _text(manifest.get("topic"))
    if not topic:
        raise QuantitativeManifestError("Quantitative ideas manifest has no topic")
    if expected_topic and topic.casefold() != _text(expected_topic).casefold():
        raise QuantitativeManifestError("Quantitative ideas manifest topic differs from expected topic")
    identity = _require_identity(_mapping(manifest.get("identity")))
    if expected_identity:
        for field, expected in _require_identity(expected_identity).items():
            if identity.get(field) != expected:
                raise QuantitativeManifestError(f"Quantitative ideas manifest identity differs for {field}")
    inputs = _mapping(manifest.get("inputs"))
    idea_manifest_path = _verify_record(
        inputs.get("idea_manifest"),
        manifest_path=path,
        label="Quantitative ideas input Idea manifest",
        local=False,
    )
    try:
        idea = verify_idea_manifest(
            idea_manifest_path,
            expected_survey_identity=identity,
            expected_topic=topic,
        )
    except ScienceManifestError as exc:
        raise QuantitativeManifestError(f"Quantitative ideas input Idea manifest is invalid: {exc}") from exc
    if _text(idea.identity.get("selected_direction_id")) != identity["selected_direction_id"]:
        raise QuantitativeManifestError("Quantitative ideas selected direction differs from Idea manifest")
    ideas_path = _verify_record(
        _mapping(manifest.get("artifacts")).get("quantitative_ideas"),
        manifest_path=path,
        label="Quantitative ideas artifact",
        local=True,
    )
    try:
        ideas_payload = json.loads(ideas_path.read_text(encoding="utf-8"))
        validated = validate_quantitative_idea_set(
            ideas_payload,
            expected_identity=identity,
            expected_topic=topic,
        )
        source_identity = _mapping(validated.get("source_identity"))
        if Path(_text(source_identity.get("idea_result_path"))).expanduser().resolve() != idea.canonical_path:
            raise QuantitativeContractError(
                "source_identity.idea_result_path differs from the canonical Idea artifact"
            )
    except (OSError, json.JSONDecodeError, QuantitativeContractError) as exc:
        raise QuantitativeManifestError(f"Quantitative ideas artifact is invalid: {exc}") from exc
    metadata = _mapping(manifest.get("metadata"))
    if _text(metadata.get("generation_status")) != _text(validated.get("generation_status")):
        raise QuantitativeManifestError("Quantitative ideas generation status differs from manifest")
    if metadata.get("idea_count") != len(validated["ideas"]):
        raise QuantitativeManifestError("Quantitative ideas count differs from manifest")
    return VerifiedQuantitativeIdeasManifest(
        manifest_path=path,
        ideas_path=ideas_path,
        identity=identity,
        payload=validated,
    )


__all__ = [
    "QuantitativeManifestError",
    "VerifiedQuantitativeIdeasManifest",
    "verify_quantitative_ideas_manifest",
    "write_quantitative_ideas_manifest",
]
