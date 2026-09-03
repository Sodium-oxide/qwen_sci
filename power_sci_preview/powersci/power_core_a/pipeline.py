"""No-LLM B0 control-plane slice and Result Bundle verification."""

from __future__ import annotations

from pathlib import Path
from typing import Any
import json
import platform
import subprocess
import sys

from .approval import require_protocol_approval
from .artifact_store import ArtifactStore
from .canonical import canonical_json_bytes, sha256_bytes
from .errors import ArtifactIntegrityError, ContractValidationError
from .router import route_next_task
from .schema_registry import SchemaRegistry
from .state_machine import ResearchState, StateJournal
from .semantic_validation import validate_case_against_equation_ir


POWER_CORE_VERSION = "0.1.0"


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractValidationError(f"Cannot load fixture {path.name}: {exc}") from exc
    if not isinstance(value, dict):
        raise ContractValidationError(f"Fixture {path.name} must contain one JSON object")
    return value


def _hash(value: dict[str, Any]) -> str:
    return sha256_bytes(canonical_json_bytes(value))


def _event_hashes(journal: StateJournal) -> list[str]:
    return [sha256_bytes(canonical_json_bytes(event)) for event in journal.events()]


def _source_revision() -> str:
    workspace = Path(__file__).resolve().parents[1]
    try:
        completed = subprocess.run(
            ["git", "-C", str(workspace), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        return "unversioned-workspace"
    revision = completed.stdout.strip()
    return revision if revision else "unversioned-workspace"


def _persist_task(
    store: ArtifactStore,
    task: dict[str, Any],
    *,
    created_at: str,
) -> dict[str, Any]:
    return store.put_json(
        artifact_id=task["task_id"],
        artifact_type="task_envelope",
        contract_schema="TaskEnvelope",
        payload=task,
        producer="M01",
        created_at=created_at,
        lineage_hashes=[row["content_hash"] for row in task["input_artifacts"]],
        idempotency_key=f"artifact:{task['run_id']}:task:{task['required_state']}",
    )


def run_offline_b0_slice(
    *,
    store_root: Path | str,
    fixture_dir: Path | str,
    run_id: str = "run_b0_offline_001",
    actor: str = "role_a_offline_runner",
    approval_record: dict[str, Any] | None = None,
    auto_approve_fixture: bool = True,
) -> dict[str, Any]:
    """Run A's deterministic slice with supplied B0 contract fixtures.

    The function does not simulate a swing equation. It verifies and packages
    the B/C-facing fixtures so the control plane can be accepted before the
    real cross-role integration.
    """

    fixture_dir = Path(fixture_dir)
    registry = SchemaRegistry()
    registry.validate_schema_catalog()
    brief = registry.validate("ResearchBrief", _load_json(fixture_dir / "research_brief.json"))
    equation_ir = registry.validate("EquationIR", _load_json(fixture_dir / "equation_ir.json"))
    case = registry.validate("CaseManifest", _load_json(fixture_dir / "case_manifest.json"))
    lens = registry.validate("LensSpec", _load_json(fixture_dir / "lens_spec.json"))
    validation = registry.validate("ValidationReport", _load_json(fixture_dir / "validation_report.json"))
    validate_case_against_equation_ir(case, equation_ir)

    brief_hash, equation_hash, case_hash, lens_hash = map(_hash, (brief, equation_ir, case, lens))
    if case["equation_ir_ref"]["content_hash"] != equation_hash:
        raise ContractValidationError("CaseManifest equation_ir_ref does not match EquationIR content")
    if case["benchmark_level"] != "B0":
        raise ContractValidationError("Offline role-A acceptance fixture must be benchmark level B0")
    if not brief["constraints"]["deterministic_required"] or brief["constraints"]["llm_allowed"]:
        raise ContractValidationError("Offline role-A acceptance requires deterministic_required=true and llm_allowed=false")
    allowed_cases = brief["constraints"].get("allowed_case_ids", [])
    if allowed_cases and case["case_id"] not in allowed_cases:
        raise ContractValidationError("CaseManifest is outside ResearchBrief allowed_case_ids")
    if validation["run_id"] != run_id:
        raise ContractValidationError("ValidationReport run_id does not match requested run")
    if validation["candidate_model_hash"] != equation_hash or validation["case_manifest_hash"] != case_hash or validation["lens_spec_hash"] != lens_hash:
        raise ContractValidationError("ValidationReport input hashes do not match the supplied contracts")

    store = ArtifactStore(store_root, registry)
    journal = StateJournal(store_root, run_id, registry)
    init = journal.initialize(
        actor=actor, input_hashes=[brief_hash], idempotency_key=f"state:{run_id}:initialize"
    )
    started_at = init["occurred_at"]

    brief_ref = store.put_json(
        artifact_id=brief["brief_id"], artifact_type="research_brief", contract_schema="ResearchBrief",
        payload=brief, producer="M00", created_at=started_at, idempotency_key=f"artifact:{run_id}:brief",
    )
    task_refs: list[dict[str, Any]] = []
    task_refs.append(_persist_task(store, route_next_task(
        run_id=run_id, state=ResearchState.BRIEF_DRAFT, input_artifacts=[brief_ref],
        created_at=started_at, registry=registry,
    ), created_at=started_at))
    journal.transition(
        ResearchState.BRIEF_VALIDATED, trigger="RESEARCH_BRIEF_VALID", actor=actor,
        input_hashes=[brief_hash], idempotency_key=f"state:{run_id}:brief_validated",
    )

    equation_ref = store.put_json(
        artifact_id=equation_ir["model_id"], artifact_type="equation_ir", contract_schema="EquationIR",
        payload=equation_ir, producer="M00_CONTRACT_FIXTURE", created_at=started_at,
        idempotency_key=f"artifact:{run_id}:equation_ir",
    )
    case_ref = store.put_json(
        artifact_id=case["case_id"], artifact_type="case_manifest", contract_schema="CaseManifest",
        payload=case, producer="M00_CONTRACT_FIXTURE", created_at=started_at, lineage_hashes=[equation_hash],
        idempotency_key=f"artifact:{run_id}:case_manifest",
    )
    lens_ref = store.put_json(
        artifact_id=lens["lens_id"], artifact_type="lens_spec", contract_schema="LensSpec",
        payload=lens, producer="M00_CONTRACT_FIXTURE", created_at=started_at,
        idempotency_key=f"artifact:{run_id}:lens_spec",
    )
    bound_inputs = [brief_ref, equation_ref, case_ref, lens_ref]
    task_refs.append(_persist_task(store, route_next_task(
        run_id=run_id, state=ResearchState.BRIEF_VALIDATED, input_artifacts=bound_inputs,
        created_at=started_at, registry=registry,
    ), created_at=started_at))
    journal.transition(
        ResearchState.CASE_BOUND, trigger="CASE_CONTRACTS_BOUND", actor=actor,
        input_hashes=[brief_hash, equation_hash, case_hash, lens_hash], idempotency_key=f"state:{run_id}:case_bound",
    )

    protocol_draft = {
        "schema_version": "experiment_protocol_v1",
        "protocol_id": f"protocol_{run_id}",
        "protocol_version": "1.0.0",
        "brief_hash": brief_hash,
        "case_manifest_hash": case_hash,
        "equation_ir_hash": equation_hash,
        "lens_spec_hash": lens_hash,
        "split_policy": {"train": 0.6, "validation": 0.2, "ood": 0.2, "ordered": True},
        "budget": {"max_candidates": 1, "max_runtime_seconds": brief["constraints"]["max_runtime_seconds"], "max_cpu_threads": 1, "llm_calls": 0},
        "acceptance_criteria": [{"metric": "max_abs_residual", "operator": "LE", "threshold": 1e-9, "unit": "pu"}],
        "random_seed": case["random_seed"],
        "status": "DRAFT",
        "created_at": started_at,
    }
    protocol_draft_ref = store.put_json(
        artifact_id=protocol_draft["protocol_id"], artifact_type="experiment_protocol", contract_schema="ExperimentProtocol",
        payload=protocol_draft, producer="M01", created_at=started_at,
        lineage_hashes=[brief_hash, case_hash, equation_hash, lens_hash], idempotency_key=f"artifact:{run_id}:protocol_draft",
    )
    task_refs.append(_persist_task(store, route_next_task(
        run_id=run_id, state=ResearchState.CASE_BOUND, input_artifacts=bound_inputs,
        created_at=started_at, registry=registry,
    ), created_at=started_at))
    journal.transition(
        ResearchState.PROTOCOL_DRAFT, trigger="PROTOCOL_DRAFTED", actor=actor,
        input_hashes=[protocol_draft_ref["content_hash"]], idempotency_key=f"state:{run_id}:protocol_draft",
    )
    task_refs.append(_persist_task(store, route_next_task(
        run_id=run_id, state=ResearchState.PROTOCOL_DRAFT, input_artifacts=[protocol_draft_ref],
        created_at=started_at, registry=registry,
    ), created_at=started_at))
    journal.transition(
        ResearchState.APPROVAL_PENDING, trigger="PROTOCOL_APPROVAL_REQUESTED", actor=actor,
        input_hashes=[protocol_draft_ref["content_hash"]], idempotency_key=f"state:{run_id}:approval_pending",
    )

    approval_template = {
        "schema_version": "approval_record_v1",
        "approval_id": f"approval_{run_id}_replace_me",
        "run_id": run_id,
        "approval_type": "PROTOCOL_FREEZE",
        "decision": "APPROVED",
        "subject_artifact_hash": protocol_draft_ref["content_hash"],
        "approver_id": "replace_with_approver_id",
        "decided_at": started_at,
        "reason": "Replace with the human review decision and rationale.",
    }
    if approval_record is None and not auto_approve_fixture:
        return {
            "run_id": run_id,
            "state": journal.current_state().value,
            "protocol_draft": protocol_draft_ref,
            "approval_template": approval_template,
        }

    approval = approval_record or {
        "schema_version": "approval_record_v1",
        "approval_id": f"approval_{run_id}_protocol_v1",
        "run_id": run_id,
        "approval_type": "PROTOCOL_FREEZE",
        "decision": "APPROVED",
        "subject_artifact_hash": protocol_draft_ref["content_hash"],
        "approver_id": "offline_fixture_approver",
        "decided_at": started_at,
        "reason": "Deterministic no-LLM B0 role-A acceptance fixture.",
    }
    registry.validate("ApprovalRecord", approval)
    approval_ref = store.put_json(
        artifact_id=approval["approval_id"], artifact_type="approval_record", contract_schema="ApprovalRecord",
        payload=approval, producer="M17", created_at=started_at, lineage_hashes=[protocol_draft_ref["content_hash"]],
        idempotency_key=f"artifact:{run_id}:approval:{approval['approval_id']}",
    )
    require_protocol_approval(
        approval, run_id=run_id, protocol_hash=protocol_draft_ref["content_hash"], registry=registry
    )
    protocol_frozen = {**protocol_draft, "status": "FROZEN"}
    protocol_frozen_ref = store.put_json(
        artifact_id=protocol_draft["protocol_id"], artifact_type="experiment_protocol", contract_schema="ExperimentProtocol",
        payload=protocol_frozen, producer="M17", created_at=started_at,
        lineage_hashes=[protocol_draft_ref["content_hash"], approval_ref["content_hash"]],
        idempotency_key=f"artifact:{run_id}:protocol_frozen",
    )
    task_refs.append(_persist_task(store, route_next_task(
        run_id=run_id, state=ResearchState.APPROVAL_PENDING,
        input_artifacts=[protocol_draft_ref, approval_ref], created_at=started_at, registry=registry,
    ), created_at=started_at))
    final_event = journal.transition(
        ResearchState.PROTOCOL_FROZEN, trigger="HASH_BOUND_APPROVAL_ACCEPTED", actor=actor,
        input_hashes=[protocol_frozen_ref["content_hash"], approval_ref["content_hash"]],
        idempotency_key=f"state:{run_id}:protocol_frozen",
    )

    validation_ref = store.put_json(
        artifact_id=validation["report_id"], artifact_type="validation_report", contract_schema="ValidationReport",
        payload=validation, producer="M00_CONTRACT_FIXTURE", created_at=started_at,
        lineage_hashes=[equation_hash, case_hash, lens_hash], idempotency_key=f"artifact:{run_id}:validation_report",
    )
    input_refs = [brief_ref, equation_ref, case_ref, lens_ref]
    approval_refs = [
        descriptor for descriptor in store.list_descriptors(artifact_type="approval_record")
        if store.read_json(descriptor)["run_id"] == run_id
    ]
    core_output_refs = [protocol_draft_ref, *approval_refs, protocol_frozen_ref, validation_ref]
    task_refs.append(_persist_task(store, route_next_task(
        run_id=run_id, state=ResearchState.PROTOCOL_FROZEN,
        input_artifacts=input_refs + core_output_refs, created_at=started_at, registry=registry,
    ), created_at=started_at))
    output_refs = core_output_refs + task_refs
    run_manifest = {
        "schema_version": "run_manifest_v1",
        "run_id": run_id,
        "run_kind": "OFFLINE_B0",
        "state": "PROTOCOL_FROZEN",
        "started_at": started_at,
        "completed_at": final_event["occurred_at"],
        "random_seed": case["random_seed"],
        "protocol_hash": protocol_frozen_ref["content_hash"],
        "input_artifacts": input_refs,
        "output_artifacts": output_refs,
        "state_event_hashes": _event_hashes(journal),
        "environment": {
            "python": platform.python_version(), "platform": platform.platform(),
            "power_core_version": POWER_CORE_VERSION, "source_revision": _source_revision(), "llm_used": False,
        },
        "reproduction": {
            "entrypoint": "python -m power_core_a.cli run-b0",
            "arguments": ["--store", str(Path(store_root).resolve()), "--fixtures", str(fixture_dir.resolve()), "--run-id", run_id],
            "network_required": False,
        },
    }
    run_ref = store.put_json(
        artifact_id=run_id, artifact_type="run_manifest", contract_schema="RunManifest", payload=run_manifest,
        producer="M15", created_at=started_at, lineage_hashes=[item["content_hash"] for item in input_refs + output_refs],
        idempotency_key=f"artifact:{run_id}:run_manifest",
    )
    bundle = {
        "schema_version": "result_bundle_manifest_v1",
        "bundle_id": f"bundle_{run_id}",
        "run_id": run_id,
        "bundle_version": 1,
        "created_at": final_event["occurred_at"],
        "final_state": "PROTOCOL_FROZEN",
        "run_manifest": run_ref,
        "artifacts": input_refs + output_refs,
        "integrity_algorithm": "sha256",
        "recomputable": True,
        "reproduction_command": [
            sys.executable, "-m", "power_core_a.cli", "verify-bundle",
            "--store", str(Path(store_root).resolve()), "--bundle-id", f"bundle_{run_id}",
        ],
    }
    bundle_ref = store.put_json(
        artifact_id=bundle["bundle_id"], artifact_type="result_bundle", contract_schema="ResultBundleManifest",
        payload=bundle, producer="M15", created_at=started_at,
        lineage_hashes=[run_ref["content_hash"]], idempotency_key=f"artifact:{run_id}:result_bundle",
    )
    verification = verify_result_bundle(store_root=store_root, bundle_descriptor=bundle_ref)
    return {"run_id": run_id, "state": journal.current_state().value, "bundle": bundle_ref, "verification": verification}


def verify_result_bundle(*, store_root: Path | str, bundle_descriptor: dict[str, Any]) -> dict[str, Any]:
    registry = SchemaRegistry()
    store = ArtifactStore(store_root, registry)
    bundle_descriptor = store.verify_descriptor(bundle_descriptor)
    if bundle_descriptor["contract_schema"] != "ResultBundleManifest":
        raise ArtifactIntegrityError("Descriptor is not a ResultBundleManifest")
    bundle = store.read_json(bundle_descriptor)
    registry.validate("ResultBundleManifest", bundle)
    descriptors = [bundle["run_manifest"], *bundle["artifacts"]]
    hashes: set[str] = set()
    for descriptor in descriptors:
        verified = store.verify_descriptor(descriptor)
        if verified["content_hash"] in hashes:
            raise ArtifactIntegrityError("Result Bundle contains a duplicate artifact hash")
        hashes.add(verified["content_hash"])
    run_manifest = store.read_json(bundle["run_manifest"])
    if run_manifest["run_id"] != bundle["run_id"] or run_manifest["state"] != bundle["final_state"]:
        raise ArtifactIntegrityError("Result Bundle and RunManifest identities disagree")
    return {
        "valid": True,
        "bundle_id": bundle["bundle_id"],
        "run_id": bundle["run_id"],
        "artifact_count": len(descriptors),
        "verified_hashes": sorted(hashes),
    }


def verify_result_bundle_by_id(*, store_root: Path | str, bundle_id: str) -> dict[str, Any]:
    store = ArtifactStore(store_root, SchemaRegistry())
    descriptor = store.latest_descriptor(artifact_type="result_bundle", artifact_id=bundle_id)
    return verify_result_bundle(store_root=store_root, bundle_descriptor=descriptor)
