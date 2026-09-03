"""Idempotent A→B candidate-validation workflow after protocol freeze."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from .artifact_store import ArtifactStore
from .canonical import canonical_json_bytes, sha256_bytes
from .errors import ArtifactIntegrityError, InvalidStateTransition
from .integrations.part_b_adapter import build_validation_report_v2, validate_contract_with_part_b
from .schema_registry import SchemaRegistry


def _schema_for(payload: Mapping[str, Any], allowed: Mapping[str, str]) -> str:
    version = str(payload.get("schema_version", ""))
    try:
        return allowed[version]
    except KeyError as exc:
        raise ValueError(f"Unsupported contract version at integration boundary: {version!r}") from exc


def _artifact_ref(descriptor: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "artifact_id": descriptor["artifact_id"], "artifact_type": descriptor["artifact_type"],
        "content_hash": descriptor["content_hash"], "relative_path": descriptor["relative_path"],
    }


def run_part_b_candidate_validation(
    *,
    store_root: Path | str,
    run_id: str,
    current_state: str,
    candidate_contract: Mapping[str, Any],
    case_manifest: Mapping[str, Any],
    lens_spec: Mapping[str, Any],
    part_b_api: Any,
    created_at: str,
    requested_by_module: str = "M01",
    context: Any = None,
    sample_points: Any = None,
) -> dict[str, Any]:
    """Persist inputs/task/report and resume without calling B twice.

    This is a per-candidate sub-workflow; B never changes A's global research
    state.  Validation is legal only after ``PROTOCOL_FROZEN``.
    """

    if current_state != "PROTOCOL_FROZEN":
        raise InvalidStateTransition(
            "Candidate validation requires PROTOCOL_FROZEN",
            context={"current_state": current_state, "required_state": "PROTOCOL_FROZEN"},
        )
    registry = SchemaRegistry()
    candidate = registry.validate("CandidateModelV1", dict(candidate_contract))
    case_schema = _schema_for(case_manifest, {"case_manifest_v1": "CaseManifest", "case_manifest_v2": "CaseManifestV2"})
    lens_schema = _schema_for(lens_spec, {"lens_spec_v1": "LensSpec", "lens_spec_v2": "LensSpecV2"})
    case = registry.validate(case_schema, dict(case_manifest))
    lens = registry.validate(lens_schema, dict(lens_spec))
    store = ArtifactStore(store_root, registry)

    candidate_descriptor = store.put_json(
        artifact_id=candidate["candidate_id"], artifact_type="candidate_model", contract_schema="CandidateModelV1",
        payload=candidate, producer=candidate["producer"], created_at=created_at,
        idempotency_key=f"{run_id}:candidate:{candidate['candidate_id']}",
    )
    case_descriptor = store.put_json(
        artifact_id=case["case_id"], artifact_type="case_manifest", contract_schema=case_schema,
        payload=case, producer="M05", created_at=created_at,
        idempotency_key=f"{run_id}:case:{case['case_id']}:{case_descriptor_hash(case)}",
    )
    lens_descriptor = store.put_json(
        artifact_id=lens["lens_id"], artifact_type="lens_spec", contract_schema=lens_schema,
        payload=lens, producer="M07", created_at=created_at,
        idempotency_key=f"{run_id}:lens:{lens['lens_id']}:{case_descriptor_hash(lens)}",
    )

    identity_hash = sha256_bytes(canonical_json_bytes({"run_id": run_id, "candidate_id": candidate["candidate_id"]})).split(":", 1)[1][:20]
    task = {
        "schema_version": "task_envelope_v2", "task_id": f"validate-{identity_hash}", "run_id": run_id,
        "task_type": "VALIDATE_CANDIDATE", "requested_by_module": requested_by_module, "target_module": "M12",
        "required_state": "PROTOCOL_FROZEN",
        "input_artifacts": [_artifact_ref(candidate_descriptor), _artifact_ref(case_descriptor), _artifact_ref(lens_descriptor)],
        "expected_output_schemas": ["ValidationReportV2"],
        "idempotency_key": f"{run_id}:validate:{candidate['candidate_id']}", "created_at": created_at,
    }
    task_descriptor = store.put_json(
        artifact_id=task["task_id"], artifact_type="task_envelope", contract_schema="TaskEnvelopeV2",
        payload=task, producer="M01", created_at=created_at,
        lineage_hashes=[row["content_hash"] for row in (candidate_descriptor, case_descriptor, lens_descriptor)],
        idempotency_key=task["idempotency_key"],
    )

    report_id = f"validation-{identity_hash}"
    try:
        existing_descriptor = store.latest_descriptor(artifact_type="validation_report", artifact_id=report_id)
        existing = store.read_json(existing_descriptor)
        expected_hashes = (
            candidate_descriptor["content_hash"], case_descriptor["content_hash"], lens_descriptor["content_hash"]
        )
        observed_hashes = (
            existing.get("candidate_model_hash"), existing.get("case_manifest_hash"), existing.get("lens_spec_hash")
        )
        if expected_hashes == observed_hashes:
            return {
                "resumed": True, "verdict": existing["verdict"], "candidate": candidate_descriptor,
                "case": case_descriptor, "lens": lens_descriptor, "task": task_descriptor,
                "validation_report": existing_descriptor,
            }
    except ArtifactIntegrityError:
        pass

    try:
        raw_report = validate_contract_with_part_b(
            candidate, part_b_api, context=context, sample_points=sample_points,
        )
    except Exception as exc:  # persist a structured BLOCKED result instead of losing traceability
        raw_report = {
            "passed": False, "stage": "structure", "metrics": {}, "warnings": [],
            "errors": [{"code": "INTERNAL_ERROR", "message": f"Part B invocation failed: {type(exc).__name__}: {exc}", "target": None, "details": {}}],
        }
    report = build_validation_report_v2(
        raw_report, run_id=run_id, candidate_contract=candidate, case_manifest=case, lens_spec=lens,
        created_at=created_at, validator_version=str(getattr(part_b_api, "__version__", "part_b_xtl-unversioned")),
        registry=registry,
    )
    report_descriptor = store.put_json(
        artifact_id=report["report_id"], artifact_type="validation_report", contract_schema="ValidationReportV2",
        payload=report, producer="M12", created_at=created_at,
        lineage_hashes=[task_descriptor["content_hash"], candidate_descriptor["content_hash"], case_descriptor["content_hash"], lens_descriptor["content_hash"]],
        idempotency_key=f"{run_id}:validation-report:{candidate['candidate_id']}",
    )
    return {
        "resumed": False, "verdict": report["verdict"], "candidate": candidate_descriptor,
        "case": case_descriptor, "lens": lens_descriptor, "task": task_descriptor,
        "validation_report": report_descriptor,
    }


def case_descriptor_hash(payload: Mapping[str, Any]) -> str:
    """Short content identity used only inside idempotency keys."""

    return sha256_bytes(canonical_json_bytes(dict(payload))).split(":", 1)[1][:16]
