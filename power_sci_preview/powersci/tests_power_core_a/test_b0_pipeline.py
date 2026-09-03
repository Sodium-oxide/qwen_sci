from __future__ import annotations

from pathlib import Path
import json
import subprocess
import sys

import pytest

from power_core_a.errors import ApprovalRequired, ArtifactIntegrityError
from power_core_a.pipeline import (
    run_offline_b0_slice,
    verify_result_bundle,
    verify_result_bundle_by_id,
)


FIXTURES = Path(__file__).resolve().parents[1] / "examples_power_core_a" / "b0"


def test_offline_b0_pipeline_is_resumable_and_bundle_is_verifiable(tmp_path: Path) -> None:
    first = run_offline_b0_slice(store_root=tmp_path, fixture_dir=FIXTURES)
    second = run_offline_b0_slice(store_root=tmp_path, fixture_dir=FIXTURES)
    assert first == second
    assert first["state"] == "PROTOCOL_FROZEN"
    assert first["verification"]["valid"] is True
    assert first["verification"]["artifact_count"] == 15
    assert verify_result_bundle_by_id(
        store_root=tmp_path, bundle_id=first["verification"]["bundle_id"]
    ) == first["verification"]

    bundle = json.loads((tmp_path / first["bundle"]["relative_path"]).read_text(encoding="utf-8"))
    run_manifest = json.loads((tmp_path / bundle["run_manifest"]["relative_path"]).read_text(encoding="utf-8"))
    task_outputs = [
        row for row in run_manifest["output_artifacts"]
        if row["contract_schema"] == "TaskEnvelope"
    ]
    assert len(task_outputs) == 6
    assert "--store" in run_manifest["reproduction"]["arguments"]
    assert "--fixtures" in run_manifest["reproduction"]["arguments"]
    assert "--bundle-id" in bundle["reproduction_command"]
    verified_cli = subprocess.run(
        bundle["reproduction_command"],
        cwd=FIXTURES.parents[1],
        check=True,
        capture_output=True,
        text=True,
    )
    assert json.loads(verified_cli.stdout)["valid"] is True
    replayed_cli = subprocess.run(
        [sys.executable, "-m", "power_core_a.cli", "run-b0", *run_manifest["reproduction"]["arguments"]],
        cwd=FIXTURES.parents[1],
        check=True,
        capture_output=True,
        text=True,
    )
    assert json.loads(replayed_cli.stdout)["bundle"] == first["bundle"]


def test_bundle_verifier_detects_payload_tampering(tmp_path: Path) -> None:
    result = run_offline_b0_slice(store_root=tmp_path, fixture_dir=FIXTURES)
    descriptor = result["bundle"]
    bundle = json.loads((tmp_path / descriptor["relative_path"]).read_text(encoding="utf-8"))
    victim = bundle["artifacts"][0]
    victim_path = tmp_path / victim["relative_path"]
    victim_path.write_text('{"tampered":true}\n', encoding="utf-8")
    with pytest.raises(ArtifactIntegrityError, match="hash mismatch"):
        verify_result_bundle(store_root=tmp_path, bundle_descriptor=descriptor)


def test_external_approval_can_reject_then_resume_with_a_new_approval(tmp_path: Path) -> None:
    pending = run_offline_b0_slice(
        store_root=tmp_path,
        fixture_dir=FIXTURES,
        auto_approve_fixture=False,
    )
    assert pending["state"] == "APPROVAL_PENDING"
    rejected = {
        **pending["approval_template"],
        "approval_id": "approval_b0_rejected_001",
        "decision": "REJECTED",
        "approver_id": "teacher_test",
        "reason": "Protocol needs an explicit review before freezing.",
    }
    with pytest.raises(ApprovalRequired, match="not approved"):
        run_offline_b0_slice(
            store_root=tmp_path,
            fixture_dir=FIXTURES,
            approval_record=rejected,
            auto_approve_fixture=False,
        )

    approved = {
        **pending["approval_template"],
        "approval_id": "approval_b0_approved_002",
        "decision": "APPROVED",
        "approver_id": "teacher_test",
        "reason": "Reviewed and approved after the rejection was recorded.",
    }
    completed = run_offline_b0_slice(
        store_root=tmp_path,
        fixture_dir=FIXTURES,
        approval_record=approved,
        auto_approve_fixture=False,
    )
    assert completed["state"] == "PROTOCOL_FROZEN"
    bundle = json.loads((tmp_path / completed["bundle"]["relative_path"]).read_text(encoding="utf-8"))
    run_manifest = json.loads((tmp_path / bundle["run_manifest"]["relative_path"]).read_text(encoding="utf-8"))
    approvals = [row for row in run_manifest["output_artifacts"] if row["contract_schema"] == "ApprovalRecord"]
    assert len(approvals) == 2
