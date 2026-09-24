from copy import deepcopy
import subprocess
from threading import Lock
from time import sleep
import json

from test_formal_contracts_v2 import formal_plan
from src.agents.experiment_design_agent.formal_verification import build_verification_task, verify_formal_plan
from src.agents.experiment_design_agent.formal_revision import apply_semantic_revision, run_formal_revision_loop


SETTINGS = {"enabled": True, "backends": ["z3"], "timeout_seconds": 10}


def test_smt_proves_and_refutes_with_actual_witness():
    plan = formal_plan()
    report = verify_formal_plan(plan, SETTINGS)
    assert report["results"][0]["result"] == "passed"
    assert report["target_summaries"][0]["status"] == "verified_in_declared_scope"
    plan["propositions"][0]["conclusion_expression"]["args"][1] = {"number": "1"}
    report = verify_formal_plan(plan, SETTINGS)
    assert report["results"][0]["result"] == "failed"
    assert report["results"][0]["witness"]
    assert report["target_summaries"][0]["status"] == "refuted_in_declared_scope"


def test_negated_premise_is_not_a_witness_and_unsat_domain_is_not_proof():
    plan = formal_plan()
    plan["propositions"][0]["candidate_points"] = [{"x": "-1"}]
    report = verify_formal_plan(plan, {**SETTINGS, "backends": ["numerical"]})
    assert report["results"][0]["result"] == "unknown"
    plan["propositions"][0]["domain_expression"] = {"op": "lt", "args": [{"symbol": "x"}, {"number": "0"}]}
    report = verify_formal_plan(plan, SETTINGS)
    assert report["results"][0]["result"] == "unknown"
    assert "inconsistent_domain" in report["results"][0]["limitations"]


def test_ast_dependencies_cannot_bypass_missing_definition():
    plan = formal_plan()
    plan["propositions"][0]["symbol_references"] = []
    plan["assumptions"][0]["symbol_references"] = []
    plan["definitions"][0]["definition_status"] = "unresolved"
    report = verify_formal_plan(plan, SETTINGS)
    assert report["results"][0]["result"] == "unsupported"
    assert report["target_summaries"][0]["status"] == "blocked_by_definition"


def test_sympy_polynomial_identity_and_no_arbitrary_expression():
    plan = formal_plan()
    target = plan["propositions"][0]
    target["premises"] = []
    target["conclusion_expression"] = {"op": "eq", "args": [{"op": "add", "args": [{"symbol": "x"}, {"number": "0"}]}, {"symbol": "x"}]}
    report = verify_formal_plan(plan, {**SETTINGS, "backends": ["sympy"]})
    assert report["results"][0]["result"] == "passed"
    target["conclusion_expression"]["args"][0] = {"op": "__import__", "args": []}
    report = verify_formal_plan(plan, {**SETTINGS, "backends": ["sympy"]})
    assert report["results"][0]["result"] == "unsupported"


def test_disabled_missing_encoding_and_unconfigured_assistant_never_prove():
    for settings in ({"enabled": False}, {**SETTINGS, "backends": ["lean"]}):
        report = verify_formal_plan(formal_plan(), settings)
        assert report["target_summaries"][0]["status"] != "verified_in_declared_scope"
    plan = formal_plan()
    plan["propositions"][0]["conclusion_expression"] = None
    assert verify_formal_plan(plan, SETTINGS)["results"][0]["result"] == "unsupported"


def test_timeout_is_not_a_proof(monkeypatch):
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired("backend", 0.01)

    monkeypatch.setattr(subprocess, "run", timeout)
    report = verify_formal_plan(formal_plan(), SETTINGS)
    assert report["results"][0]["result"] == "timeout"
    assert report["target_summaries"][0]["status"] != "verified_in_declared_scope"


def test_semantic_change_invalidates_success_but_prose_does_not():
    plan = formal_plan()
    first = verify_formal_plan(plan, SETTINGS)
    plan["propositions"][0]["statement"] = "Rephrased prose"
    second = verify_formal_plan(plan, SETTINGS, previous_report=first)
    assert second["results"][0]["reused"]
    plan["semantic_diagnostics"] = [{"target_id": "P1", "reason": "Circular premise requires review"}]
    third = verify_formal_plan(plan, SETTINGS, previous_report=second)
    assert not third["results"][0]["reused"]
    assert third["target_summaries"][0]["status"] == "unresolved"


def test_obligations_execute_and_lemma_domain_does_not_shrink_target():
    plan = formal_plan()
    plan["proof_obligations"] = [{"obligation_id": "PO1", "target_id": "P1", "target": "Order implication", "status": "unresolved", "premises": ["A1"], "conclusion_expression": deepcopy(plan["propositions"][0]["conclusion_expression"])}]
    plan["propositions"][0]["required_obligation_ids"] = ["PO1"]
    report = verify_formal_plan(plan, SETTINGS)
    assert {item["target_id"] for item in report["results"]} == {"PO1", "P1"}
    assert report["target_summaries"][0]["remaining_obligations"] == []
    plan = formal_plan()
    lemma = deepcopy(plan["propositions"][0])
    lemma["lemma_id"] = "L1"
    lemma.pop("proposition_id")
    lemma["premises"] = []
    lemma["domain_expression"] = deepcopy(lemma["conclusion_expression"])
    plan["lemmas"] = [lemma]
    plan["propositions"][0]["premises"] = ["L1"]
    report = verify_formal_plan(plan, SETTINGS)
    assert report["target_summaries"][0]["status"] == "refuted_in_declared_scope"
    lemma["domain_expression"] = {"bool": True}
    lemma["conditions"] = ["x >= 0"]
    lemma["condition_expressions"] = [deepcopy(lemma["conclusion_expression"])]
    report = verify_formal_plan(plan, SETTINGS)
    assert report["target_summaries"][0]["status"] == "refuted_in_declared_scope"


def test_unregistered_obligation_cannot_be_ignored():
    plan = formal_plan()
    plan["proof_obligations"] = [{"obligation_id": "PO1", "target_id": "P1", "target": "Unencoded essential step", "premises": [], "status": "unresolved", "conclusion_expression": None}]
    report = verify_formal_plan(plan, SETTINGS)
    assert report["target_summaries"][0]["status"] == "partially_verified"
    assert report["target_summaries"][0]["remaining_obligations"] == ["PO1"]


def test_revision_budget_and_preservation_of_unrelated_objects():
    plan = formal_plan()
    calls = []
    def no_change(*args, **kwargs):
        calls.append(1)
        return {"schema_version": "formal_revision_patch_v1", "reason": "Requires external model", "replacements": [], "additions": [], "proof_attempts": []}
    current, report, audit = run_formal_revision_loop(plan, {"verification": {"enabled": False}, "max_semantic_revisions": 2}, llm_call=no_change)
    assert len(calls) == 1
    assert audit["iterations"][0]["status"] == "no_progress"
    assert current == plan
    import pytest
    with pytest.raises(ValueError, match="outside_affected_scope"):
        apply_semantic_revision(plan, {"schema_version": "formal_revision_patch_v1", "reason": "change unrelated", "replacements": [{"collection": "definitions", "record": plan["definitions"][0]}]}, {"P1"})


def test_revision_sends_one_target_subgraph_per_request():
    plan = formal_plan()
    second = deepcopy(plan["propositions"][0])
    second["proposition_id"] = "P2"
    plan["propositions"].append(second)
    seen = []

    def no_change(prompt, **_kwargs):
        payload = json.loads(prompt.split("INPUT_JSON:\n", 1)[1])
        seen.append(payload["target_ids"])
        assert len(payload["plan"]["propositions"]) == 1
        return {"schema_version": "formal_revision_patch_v1", "reason": "No supported change", "replacements": [], "additions": [], "proof_attempts": []}

    _current, _report, audit = run_formal_revision_loop(
        plan, {"verification": {"enabled": False}, "max_semantic_revisions": 2},
        llm_call=no_change,
    )

    assert seen == [["P1"], ["P2"]]
    assert [item["status"] for item in audit["iterations"]] == ["no_progress", "no_progress"]


def test_verification_runs_independent_targets_concurrently(monkeypatch):
    import src.agents.experiment_design_agent.formal_verification as module

    plan = formal_plan()
    second = deepcopy(plan["propositions"][0])
    second["proposition_id"] = "P2"
    plan["propositions"].append(second)
    lock = Lock()
    active = 0
    peak = 0

    def execute(task, *, enabled=True):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        sleep(0.03)
        with lock:
            active -= 1
        return {**task, "result": "unsupported", "evidence_kind": "none", "executed": False}

    monkeypatch.setattr(module, "run_verification_task", execute)
    report = verify_formal_plan(plan, {"enabled": True, "backends": ["z3"], "max_parallel_tasks": 2})

    assert peak == 2
    assert report["task_summary"]["task_count"] == 2
    assert {item["target_id"] for item in report["results"]} == {"P1", "P2"}


def test_verification_caps_parallel_tasks_at_three(monkeypatch):
    import src.agents.experiment_design_agent.formal_verification as module

    plan = formal_plan()
    plan["propositions"] = [
        {**deepcopy(plan["propositions"][0]), "proposition_id": f"P{number}"}
        for number in range(1, 5)
    ]
    lock = Lock()
    active = 0
    peak = 0

    def execute(task, *, enabled=True):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        sleep(0.03)
        with lock:
            active -= 1
        return {**task, "result": "unsupported", "evidence_kind": "none", "executed": False}

    monkeypatch.setattr(module, "run_verification_task", execute)
    report = verify_formal_plan(plan, {"enabled": True, "backends": ["z3"], "max_parallel_tasks": 10})

    assert peak == 3
    assert report["policy"]["max_parallel_tasks"] == 3


def test_analyzer_candidate_is_checked_and_remains_numerical_evidence():
    plan = formal_plan()
    plan["propositions"][0]["conclusion_expression"]["args"][1] = {"number": "1"}
    analysis = {"target_claim_id": "P1", "candidate_counterexamples": [{"counterexample_id": "CE2", "witness_assignment": {"x": "1/2"}}]}
    current, report, audit = run_formal_revision_loop(plan, {"verification": {"enabled": True, "backends": []}, "max_semantic_revisions": 0}, counterexample_analysis=analysis, llm_call=None)
    assert report["results"][0]["counterexample_id"] == "CE2"
    assert report["results"][0]["evidence_kind"] == "numerical_candidate"
    assert report["target_summaries"][0]["status"] == "proof_draft_available"


def test_missing_backend_is_unsupported(monkeypatch):
    import builtins
    from src.agents.experiment_design_agent.formal_verification_worker import main
    import io
    import json
    import sys

    original_import = builtins.__import__
    def without_z3(name, *args, **kwargs):
        if name == "z3":
            raise ModuleNotFoundError("missing", name="z3")
        return original_import(name, *args, **kwargs)
    output = io.StringIO()
    monkeypatch.setattr(builtins, "__import__", without_z3)
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(build_verification_task(formal_plan(), "P1", "z3"))))
    monkeypatch.setattr(sys, "stdout", output)
    main()
    assert json.loads(output.getvalue())["result"] == "unsupported"


def test_revision_verification_exception_keeps_original_plan_and_report(monkeypatch):
    import src.agents.experiment_design_agent.formal_revision as revision_module

    plan = formal_plan()
    original_report = verify_formal_plan(plan, {"enabled": False})
    calls = []
    def verify(*args, **kwargs):
        calls.append(1)
        if len(calls) > 1:
            raise RuntimeError("backend orchestration failure")
        return original_report
    monkeypatch.setattr(revision_module, "verify_formal_plan", verify)
    changed = deepcopy(plan["propositions"][0])
    changed["conclusion_expression"]["args"][1] = {"number": "1"}
    patch = {"schema_version": "formal_revision_patch_v1", "reason": "A substantive target refinement", "replacements": [{"collection": "propositions", "record": changed}]}
    current, report, audit = run_formal_revision_loop(plan, {"max_semantic_revisions": 2}, llm_call=lambda *args, **kwargs: patch)
    assert current == plan
    assert report == original_report
    assert audit["iterations"][-1]["status"] == "stopped"


def test_revision_target_preparation_failure_is_recorded(monkeypatch):
    import src.agents.experiment_design_agent.formal_revision as revision_module

    plan = formal_plan()
    original_report = verify_formal_plan(plan, {"enabled": False})

    def broken_target_subgraph(*_args):
        raise ValueError("broken target dependency")

    def unexpected_request(*_args, **_kwargs):
        raise AssertionError("request must not run")

    monkeypatch.setattr(revision_module, "target_subgraph", broken_target_subgraph)
    current, report, audit = run_formal_revision_loop(
        plan, {"verification": {"enabled": False}, "max_semantic_revisions": 2},
        llm_call=unexpected_request,
    )
    assert current == plan
    assert report == original_report
    assert audit["iterations"][0]["status"] == "stopped"
    assert "broken target dependency" in audit["iterations"][0]["reason"]


def test_counterexample_drives_a_versioned_repaired_proposition():
    plan = formal_plan()
    plan["propositions"][0]["conclusion_expression"]["args"][1] = {"number": "1"}
    original = verify_formal_plan(plan, SETTINGS)
    changed = deepcopy(plan["propositions"][0])
    changed["conclusion_expression"]["args"][1] = {"number": "0"}
    patch = {"schema_version": "formal_revision_patch_v1", "reason": "The witness refutes the threshold 1; retain the weaker nonnegative consequence.", "replacements": [{"collection": "propositions", "record": changed}]}
    current, report, audit = run_formal_revision_loop(plan, {"verification": SETTINGS, "max_semantic_revisions": 2}, llm_call=lambda *args, **kwargs: deepcopy(patch))
    assert original["target_summaries"][0]["status"] == "refuted_in_declared_scope"
    assert current["revision"] == 2
    assert report["target_summaries"][0]["status"] == "verified_in_declared_scope"
    assert not report["results"][0]["reused"]
    assert audit["iterations"][0]["invalidated_targets"] == ["P1"]
    assert audit["iterations"][0]["previous_verification_report"]["target_summaries"][0]["status"] == "refuted_in_declared_scope"
    assert current["definitions"] == plan["definitions"]


def test_valid_lemma_chain_is_usable():
    plan = formal_plan()
    lemma = deepcopy(plan["propositions"][0])
    lemma["lemma_id"] = "L1"
    lemma.pop("proposition_id")
    plan["lemmas"] = [lemma]
    plan["propositions"][0]["premises"] = ["A1", "L1"]
    report = verify_formal_plan(plan, SETTINGS)
    assert all(item["status"] == "verified_in_declared_scope" for item in report["target_summaries"])
