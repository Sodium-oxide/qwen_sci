from copy import deepcopy
import json

import pytest

from test_formal_contracts_v2 import formal_plan
from test_experiment_design_artifacts import _design
from test_experiment_design_reasoning import _counterexample_plan
from src.agents.experiment_design_agent import formal_verification as verification
from src.agents.experiment_design_agent.artifacts import write_experiment_design_artifacts
from src.agents.experiment_design_agent.contracts import validate_experiment_design
from src.agents.experiment_design_agent.formal_revision import run_formal_revision_loop
from src.agents.experiment_design_agent.formal_storage import (
    archive_report, archived_report, compact_report, expand_report, report_summary,
    resolve_report_reference,
)
from src.agents.research_plan_author.input_loader import AuthorInputLoadError, load_author_input


def plan_without_proof():
    plan = formal_plan()
    plan["proof_attempts"] = []
    return plan


def test_shared_snapshots_keep_scoped_diagnostics_without_raw_copies():
    plan = plan_without_proof()
    plan["unknown_items"] = [
        {"record_id": "P1", "reason": "encoding gap", "raw_excerpt": "raw" * 100000},
        {"record_id": "P2", "reason": "unrelated gap"},
        {"reason": "global gap", "scope": "global"},
    ]
    report = verification.verify_formal_plan(plan, {"enabled": False, "backends": ["sympy", "z3"]})
    assert report["schema_version"] == "formal_verification_report_v2"
    assert len(report["snapshots"]) == 1
    assert len(report["diagnostics"]) == 2
    assert report["results"][0]["snapshot_ref"] == report["results"][1]["snapshot_ref"]
    assert "raw_excerpt" not in json.dumps(report)
    assert len(json.dumps(report)) < 15000
    assert verification.validate_verification_report(plan, report) == []


def test_legacy_reports_roundtrip_and_missing_references_are_rejected():
    plan = plan_without_proof()
    report = verification.verify_formal_plan(plan, {"enabled": False})
    legacy = expand_report(report)
    legacy["schema_version"] = "formal_verification_report_v1"
    legacy = {key: value for key, value in legacy.items() if key not in {"snapshots", "records", "diagnostics"}}
    assert verification.validate_verification_report(plan, legacy) == []
    packed = compact_report(legacy)
    assert report_summary(packed) == report_summary(legacy)
    broken = deepcopy(packed)
    broken["snapshots"].clear()
    assert any("reference_missing" in error for error in verification.validate_verification_report(plan, broken))
    plan["propositions"][0]["conclusion_expression"] = {"bool": False}
    assert any("stale_or_mismatched" in error for error in verification.validate_verification_report(plan, packed))


def test_diagnostic_change_reuses_backend_but_updates_status(monkeypatch):
    calls = []
    def backend(task, *, enabled):
        calls.append(task["target_id"])
        return {**task, "result": "passed", "evidence_kind": "smt_unsat", "executed": True,
                "backend_version": "test", "limitations": []}
    monkeypatch.setattr(verification, "run_verification_task", backend)
    plan = plan_without_proof()
    settings = {"enabled": True, "backends": ["z3"]}
    first = verification.verify_formal_plan(plan, settings)
    plan["semantic_diagnostics"] = [{"target_id": "P1", "reason": "Scope requires review", "resolved": False}]
    second = verification.verify_formal_plan(plan, settings, previous_report=first)
    assert calls == ["P1"]
    assert first["target_summaries"][0]["status"] == "verified_in_declared_scope"
    assert second["target_summaries"][0]["status"] == "unresolved"
    assert verification.validate_verification_report(plan, second) == []
    plan["propositions"][0]["conclusion_expression"] = {"bool": False}
    verification.verify_formal_plan(plan, settings, previous_report=second)
    assert calls == ["P1", "P1"]


def test_only_affected_targets_execute_again(monkeypatch):
    calls = []
    def backend(task, *, enabled):
        calls.append(task["target_id"])
        return {**task, "result": "passed", "evidence_kind": "smt_unsat", "executed": True,
                "backend_version": "test", "limitations": []}
    monkeypatch.setattr(verification, "run_verification_task", backend)
    plan = plan_without_proof()
    second_target = deepcopy(plan["propositions"][0])
    second_target["proposition_id"] = "P2"
    plan["propositions"].append(second_target)
    settings = {"enabled": True, "backends": ["z3"]}
    previous = verification.verify_formal_plan(plan, settings)
    plan["propositions"][0]["conclusion_expression"] = {"bool": False}
    verification.verify_formal_plan(plan, settings, previous_report=previous)
    assert calls.count("P1") == 2
    assert calls.count("P2") == 1


def test_unrelated_definition_does_not_invalidate_target(monkeypatch):
    calls = []
    def backend(task, *, enabled):
        calls.append(task["target_id"])
        return {**task, "result": "passed", "evidence_kind": "smt_unsat", "executed": True,
                "backend_version": "test", "limitations": []}
    monkeypatch.setattr(verification, "run_verification_task", backend)
    plan = plan_without_proof()
    settings = {"enabled": True, "backends": ["z3"]}
    first = verification.verify_formal_plan(plan, settings)
    unrelated = {**plan["definitions"][0], "definition_id": "D2", "symbol": "y"}
    plan["definitions"].append(unrelated)
    second = verification.verify_formal_plan(plan, settings, previous_report=first)
    unrelated["symbol"] = "z"
    third = verification.verify_formal_plan(plan, settings, previous_report=second)
    assert calls == ["P1"]
    assert verification.validate_verification_report(plan, third) == []
    plan["definitions"][0]["domain"] = "positive reals"
    verification.verify_formal_plan(plan, settings, previous_report=third)
    assert calls == ["P1", "P1"]


@pytest.mark.parametrize("status", ["unknown", "unsupported", "timeout"])
def test_inconclusive_results_retry_except_diagnostic_only_refresh(monkeypatch, status):
    calls = []
    def backend(task, *, enabled):
        calls.append(task["target_id"])
        return {**task, "result": status, "evidence_kind": "none", "executed": True}
    monkeypatch.setattr(verification, "run_verification_task", backend)
    plan = plan_without_proof()
    settings = {"enabled": True, "backends": ["z3"]}
    first = verification.verify_formal_plan(plan, settings)
    plan["semantic_diagnostics"] = [{"target_id": "P1", "reason": "Review scope", "resolved": False}]
    second = verification.verify_formal_plan(plan, settings, previous_report=first, refresh_diagnostics_only=True)
    assert calls == ["P1"]
    assert verification.validate_verification_report(plan, second) == []
    verification.verify_formal_plan(plan, settings, previous_report=second)
    assert calls == ["P1", "P1"]


@pytest.mark.parametrize("field,value", [
    ("proof_assistant_enabled", True), ("executable", "other-lean"),
    ("timeout_seconds", 120), ("capabilities", {"version": "changed"}),
])
def test_execution_configuration_change_invalidates_cached_result(monkeypatch, field, value):
    task = verification.build_verification_task(plan_without_proof(), "P1", "z3")
    cached = {**task, "result": "passed", "evidence_kind": "smt_unsat", "executed": True}
    changed = {**task, field: value}
    calls = []
    def backend(current, *, enabled):
        calls.append(current)
        return {**current, "result": "unknown"}
    monkeypatch.setattr(verification, "run_verification_task", backend)
    assert verification._task_result(changed, [cached], True)["reused"] is False
    assert len(calls) == 1


def test_roundtrip_preserves_witness_certificate_and_obligations():
    report = expand_report(verification.verify_formal_plan(plan_without_proof(), {"enabled": False}))
    result = report["results"][0]
    result.pop("snapshot_ref", None)
    result.update(witness={"x": "-1/3"}, certificate=True, certificate_ref="proof.lean",
                  certificate_source="theorem sample : True := by trivial", remaining_obligations=["O1"])
    report["schema_version"] = "formal_verification_report_v1"
    packed = compact_report(report)
    restored = expand_report(packed)["results"][0]
    assert {key: value for key, value in restored.items() if key != "snapshot_ref"} == result
    summary = report_summary(packed)["results"][0]
    for field in ("witness", "certificate", "certificate_ref", "remaining_obligations"):
        assert summary[field] == result[field]


def test_raw_only_revision_does_not_repeat_verification_or_revision_round(monkeypatch):
    import src.agents.experiment_design_agent.formal_revision as revision
    plan = plan_without_proof()
    diagnostic = {"record_id": "P1", "field_path": "propositions.P1.scope", "reason": "Input needed",
                  "status": "needs_human_input", "raw_excerpt": "old"}
    plan["unknown_items"] = [diagnostic]
    calls = []
    verify = revision.verify_formal_plan
    def tracked(*args, **kwargs):
        calls.append("verify")
        return verify(*args, **kwargs)
    monkeypatch.setattr(revision, "verify_formal_plan", tracked)
    def callback(*args, **kwargs):
        calls.append("llm")
        return {"schema_version": "formal_revision_patch_v1", "reason": "Update audit excerpt",
                "unknown_items": [{**diagnostic, "raw_excerpt": "new"}]}
    current, report, audit = run_formal_revision_loop(
        plan, {"verification": {"enabled": False}, "max_semantic_revisions": 3}, llm_call=callback,
    )
    assert calls == ["verify", "llm"]
    assert current["unknown_items"][0]["raw_excerpt"] == "new"
    assert verification.validate_verification_report(current, report) == []
    assert "previous_verification_report" not in audit["iterations"][0]
    assert archived_report(audit, audit["iterations"][0]["previous_report_ref"])


def test_report_archive_shares_diagnostics_across_history():
    plan = plan_without_proof()
    plan["unknown_items"] = [{"record_id": "P1", "reason": "gap", "raw_json": "large" * 10000}]
    report = verification.verify_formal_plan(plan, {"enabled": False})
    archive = {}
    for revision in range(10):
        changed = {**report, "target_summaries": [{**item, "revision": revision} for item in report["target_summaries"]]}
        archive_report(archive, changed)
    assert len(archive["reports"]) == 10
    assert len(archive["snapshots"]) == 1
    assert len(archive["diagnostics"]) == 1
    assert len(json.dumps(archive)) < 45000


def test_artifacts_externalize_audit_and_author_checks_references(tmp_path):
    plan = plan_without_proof()
    plan["definitions"][0]["variable_references"] = []
    plan["unknown_items"] = [{"record_id": "P1", "field_path": "propositions.P1.scope",
                              "reason": "Scope gap", "status": "needs_human_input", "raw_excerpt": "ORIGINAL" * 10000}]
    design = _design()
    design["formal_reasoning_plan"] = plan
    design["counterexample_analysis"] = _counterexample_plan()
    design["formal_verification_report"] = verification.verify_formal_plan(plan, {"enabled": False})
    design["mathematical_verification_policy"] = design["formal_verification_report"]["policy"]
    design["formal_revision_audit"] = {"iterations": [], "budget": 2}
    paths = write_experiment_design_artifacts(design, tmp_path)
    published = json.loads(paths.experiment_design_json.read_text(encoding="utf-8"))
    assert validate_experiment_design(published) == []
    _, author = load_author_input(paths.author_json)
    assert author["formal_verification_report"]["schema_version"] == "formal_verification_summary_v1"
    assert "ORIGINAL" not in paths.author_json.read_text(encoding="utf-8")
    archive = json.loads(paths.formal_audit_json.read_text(encoding="utf-8"))
    assert "ORIGINAL" * 10000 in archive["raw_payloads"].values()
    assert paths.experiment_design_markdown.stat().st_size < 50000
    assert paths.author_json.stat().st_size < 50000
    summary = published["formal_verification_report"]
    full = resolve_report_reference(summary)
    assert report_summary(full)["target_summaries"] == design["formal_verification_report"]["target_summaries"]
    paths.formal_audit_json.write_text("{}", encoding="utf-8")
    with pytest.raises(AuthorInputLoadError, match="fingerprint_mismatch"):
        load_author_input(paths.author_json)
    paths.formal_audit_json.unlink()
    with pytest.raises(AuthorInputLoadError, match="archive_unavailable"):
        load_author_input(paths.author_json)


def test_audit_without_verification_report_keeps_checked_summary(tmp_path):
    design = _design()
    design["formal_revision_audit"] = {"budget": 2, "iterations": [
        {"status": "no_change", "reason": "No additional evidence", "changes": [], "raw_patch_json": "original"},
    ]}
    paths = write_experiment_design_artifacts(design, tmp_path)
    published = json.loads(paths.experiment_design_json.read_text(encoding="utf-8"))
    _, author = load_author_input(paths.author_json)
    assert published["formal_revision_audit"] == author["formal_revision_audit"]
    assert author["formal_revision_audit"]["iterations"][0]["reason"] == "No additional evidence"
    paths.formal_audit_json.unlink()
    with pytest.raises(AuthorInputLoadError, match="archive_unavailable"):
        load_author_input(paths.author_json)


def test_archive_collision_preserves_existing_file_and_publishes_companions(tmp_path):
    timestamp = "20260927-000000-000002"
    existing = tmp_path / f"experiment_design_{timestamp}.audit.json"
    existing.write_text("existing archive", encoding="utf-8")
    paths = write_experiment_design_artifacts(_design(), tmp_path, timestamp=timestamp)
    assert paths.collision_index == 1
    assert existing.read_text(encoding="utf-8") == "existing archive"
    assert all(path.exists() for path in (
        paths.experiment_design_json, paths.author_json, paths.formal_audit_json, paths.experiment_design_markdown,
    ))
