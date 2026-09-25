from copy import deepcopy
from types import SimpleNamespace

import sympy

from test_formal_contracts_v2 import formal_plan
from src.agents.experiment_design_agent.formal_contracts import validate_formal_plan_v2
from src.agents.experiment_design_agent.formal_verification import (
    build_verification_task,
    validate_verification_report,
    verify_formal_plan,
)
from src.agents.experiment_design_agent.formal_verification_worker import expression
from src.agents.experiment_design_agent.proof_assistant_backend import run_lean_task


def test_extended_boolean_and_conditional_ast_operators():
    symbols = {"x": sympy.Symbol("x", real=True)}
    for operator in ("implies", "iff", "xor"):
        node = {"op": operator, "args": [{"op": "gt", "args": [{"symbol": "x"}, {"number": "0"}]}, {"bool": True}]}
        assert expression(node, symbols, "sympy") is not None
    conditional = {"op": "ite", "args": [{"op": "gt", "args": [{"symbol": "x"}, {"number": "0"}]}, {"number": "1"}, {"number": "0"}]}
    assert expression(conditional, symbols, "sympy" ).subs(symbols["x"], 1) == 1


def test_capability_metadata_and_conditional_sympy_identity():
    plan = formal_plan()
    target = plan["propositions"][0]
    target["conclusion_expression"] = {
        "op": "eq",
        "args": [
            {"op": "ite", "args": [{"op": "gt", "args": [{"symbol": "x"}, {"number": "0"}]}, {"op": "add", "args": [{"symbol": "x"}, {"number": "1"}]}, {"symbol": "x"}]},
            {"op": "ite", "args": [{"op": "gt", "args": [{"symbol": "x"}, {"number": "0"}]}, {"op": "add", "args": [{"symbol": "x"}, {"number": "1"}]}, {"symbol": "x"}]},
        ],
    }
    task = build_verification_task(plan, "P1", "sympy")
    assert task["capabilities"]["verification_level"] == "solver_verified"
    report = verify_formal_plan(plan, {"enabled": True, "backends": ["sympy"]})
    assert report["results"][0]["result"] == "passed"
    assert report["results"][0]["verification_method"] == "symbolic_identity_or_conditional_identity"


def test_local_rule_derivation_and_report_validation():
    plan = formal_plan()
    step = plan["proof_attempts"][0]["steps"][0]
    step.update(
        derived_expression={"op": "ge", "args": [{"symbol": "x"}, {"number": "0"}]},
        rule_or_lemma="order_weakening",
    )
    report = verify_formal_plan(plan, {"enabled": True, "backends": []})
    assert report["results"][0]["backend"] == "rules"
    assert report["results"][0]["evidence_kind"] == "rule_derivation"
    assert report["results"][0]["result"] == "passed"
    assert validate_verification_report(plan, report) == []


def test_rule_checker_supports_transitivity_and_rejects_invalid_contradiction():
    plan = formal_plan()
    plan["assumptions"] = [
        {"assumption_id": "A1", "statement": "x >= 0", "predicate_expression": {"op": "ge", "args": [{"symbol": "x"}, {"number": "0"}]}, "status": "candidate_formalization", "symbol_references": ["x"]},
        {"assumption_id": "A2", "statement": "0 >= -1", "predicate_expression": {"op": "ge", "args": [{"number": "0"}, {"number": "-1"}]}, "status": "candidate_formalization", "symbol_references": []},
    ]
    plan["propositions"][0]["conclusion_expression"] = {"op": "ge", "args": [{"symbol": "x"}, {"number": "-1"}]}
    plan["proof_attempts"][0]["steps"] = [{
        "step_id": "S1", "premises": ["A1", "A2"], "derived_statement": "x >= -1",
        "derived_expression": plan["propositions"][0]["conclusion_expression"], "rule_or_lemma": "transitivity", "symbol_references": ["x"], "status": "proposed",
    }]
    report = verify_formal_plan(plan, {"enabled": True, "backends": []})
    assert report["results"][0]["result"] == "passed"

    invalid = deepcopy(plan)
    invalid["proof_attempts"][0]["steps"][0].update(
        premises=["A1", "A2"],
        derived_expression={"bool": False},
        rule_or_lemma="contradiction",
    )
    invalid_report = verify_formal_plan(invalid, {"enabled": True, "backends": []})
    assert invalid_report["results"][0]["result"] == "unknown"


def test_rule_checker_supports_definition_unfolding():
    plan = formal_plan()
    plan["definitions"][0].update(
        object_kind="derived",
        formal_expression={"op": "add", "args": [{"symbol": "x"}, {"number": "1"}]},
        symbol_references=["x"],
    )
    plan["propositions"][0].update(
        premises=[],
        conclusion_expression={"op": "eq", "args": [{"symbol": "x"}, {"op": "add", "args": [{"symbol": "x"}, {"number": "1"}]}]},
    )
    plan["proof_attempts"][0]["steps"] = [{
        "step_id": "S1", "premises": ["D1"], "derived_statement": "x = y + 1",
        "derived_expression": plan["propositions"][0]["conclusion_expression"], "rule_or_lemma": "definition_unfolding", "symbol_references": ["x"], "status": "proposed",
    }]
    report = verify_formal_plan(plan, {"enabled": True, "backends": []})
    assert report["results"][0]["result"] == "passed"


def test_derived_expression_contract_is_optional_but_validated_when_present():
    plan = formal_plan()
    assert validate_formal_plan_v2(plan) == []
    plan["proof_attempts"][0]["steps"][0]["derived_expression"] = {"op": "unknown", "args": []}
    assert any("invalid_derived_expression" in item for item in validate_formal_plan_v2(plan))
    plan["proof_attempts"][0]["steps"][0]["derived_expression"] = {"op": "ge", "args": [{"symbol": "x"}, {"number": "0"}]}
    plan["proof_attempts"][0]["steps"][0]["rule_or_lemma"] = "an LLM invented rule"
    assert any("unsupported_derived_rule" in item for item in validate_formal_plan_v2(plan))


def test_lean_is_explicitly_opt_in_and_reports_kernel_outcomes(monkeypatch):
    import pathlib
    import shutil
    import src.agents.experiment_design_agent.proof_assistant_backend as backend

    class WorkspaceTemporaryDirectory:
        def __init__(self, *args, **kwargs):
            del args, kwargs

        def __enter__(self):
            self.path = pathlib.Path("tests/.lean-test-temp")
            self.path.mkdir(exist_ok=True)
            return str(self.path)

        def __exit__(self, *_args):
            shutil.rmtree(self.path, ignore_errors=True)

    monkeypatch.setattr(backend.tempfile, "TemporaryDirectory", WorkspaceTemporaryDirectory)
    task = {
        "proof_assistant_enabled": False,
        "theorem_statement": "True",
        "proof_script": "trivial",
    }
    disabled = run_lean_task(task)
    assert disabled["result"] == "unsupported"
    assert disabled["proof_assistant_status"] == "proof_assistant_unsupported"
    assert "disabled" in disabled["limitations"][0]

    monkeypatch.setattr("src.agents.experiment_design_agent.proof_assistant_backend.lean_executable", lambda _configured=None: "lean")
    monkeypatch.setattr(
        "src.agents.experiment_design_agent.proof_assistant_backend.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="", stderr=""),
    )
    passed = run_lean_task({**task, "proof_assistant_enabled": True})
    assert passed["result"] == "passed"
    assert passed["proof_assistant_status"] == "proof_assistant_verified"
    assert passed["evidence_kind"] == "lean_kernel_checked"
    assert passed["certificate"] is True

    monkeypatch.setattr(
        "src.agents.experiment_design_agent.proof_assistant_backend.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(returncode=1, stdout="", stderr="type mismatch"),
    )
    rejected = run_lean_task({**task, "proof_assistant_enabled": True})
    assert rejected["result"] == "failed"
    assert rejected["proof_assistant_status"] == "proof_assistant_failed"
    assert rejected["evidence_kind"] == "lean_kernel_rejected"


def test_lean_report_round_trip_validates_generated_source(monkeypatch):
    import src.agents.experiment_design_agent.formal_verification as verification
    from src.agents.experiment_design_agent.proof_assistant_backend import build_lean_source

    plan = formal_plan()
    target = plan["propositions"][0]
    target.update(lean_theorem_name="positive_is_nonnegative", lean_theorem_statement="True", proof_script="trivial")

    def fake_run(task, *, enabled=True):
        return {
            **task,
            "result": "passed",
            "evidence_kind": "lean_kernel_checked",
            "executed": True,
            "backend_version": "lean-adapter-v1",
            "verification_level": "kernel_verified",
            "verification_method": "lean_kernel",
            "certificate": True,
            "certificate_ref": "generated:FormalTarget.lean",
            "certificate_source": build_lean_source(task),
            "limitations": [],
        }

    monkeypatch.setattr(verification, "run_verification_task", fake_run)
    report = verification.verify_formal_plan(
        plan,
        {"enabled": True, "backends": ["lean"], "proof_assistant": {"enabled": True}},
    )
    assert verification.validate_verification_report(plan, report) == []


def test_lemma_instantiation_substitutes_symbols_and_checks_side_conditions():
    plan = formal_plan()
    lemma = deepcopy(plan["propositions"][0])
    lemma["lemma_id"] = "L1"
    lemma.pop("proposition_id")
    lemma["quantifiers"] = [{"symbol": "u", "sort": "real", "quantifier": "forall"}]
    lemma["premises"] = ["AL1"]
    lemma["conclusion_expression"] = {"op": "ge", "args": [{"symbol": "u"}, {"number": "0"}]}
    plan["lemmas"] = [lemma]
    plan["definitions"].append({
        **deepcopy(plan["definitions"][0]), "definition_id": "D2", "symbol": "u", "variable_references": ["V2"],
    })
    plan["assumptions"].append({
        "assumption_id": "AL1", "statement": "u > 0", "predicate_expression": {"op": "gt", "args": [{"symbol": "u"}, {"number": "0"}]},
        "status": "candidate_formalization", "symbol_references": ["u"],
    })
    plan["propositions"][0]["lemma_instantiations"] = [{
        "lemma_id": "L1", "instantiation": {"u": "x"},
        "side_conditions": [{"op": "gt", "args": [{"symbol": "x"}, {"number": "0"}]}],
    }]
    plan["propositions"][0]["premises"] = ["A1", "L1"]
    evidence = {
        "target_id": "L1", "result": "passed", "evidence_kind": "symbolic_identity",
        "input_snapshot": __import__("src.agents.experiment_design_agent.formal_verification", fromlist=["semantic_snapshot"]).semantic_snapshot(plan, "L1"),
        "constraints": [{"op": "gt", "args": [{"symbol": "u"}, {"number": "0"}]}],
    }
    task = build_verification_task(plan, "P1", "sympy", verified_results=[evidence])
    assert not any(item == "unsupported_lemma_instantiation:L1" for item in task["blockers"])
    assert task["constraints"][-1]["args"][1] == {"op": "ge", "args": [{"symbol": "x"}, {"number": "0"}]}
    assert any(item == {"op": "gt", "args": [{"symbol": "x"}, {"number": "0"}]} for item in task["constraints"])
