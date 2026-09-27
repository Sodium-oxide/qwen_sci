from copy import deepcopy

import pytest

from test_formal_contracts_v2 import formal_plan
from src.agents.experiment_design_agent.formal_contracts import _valid_restricted_expression, validate_formal_plan_v2
from src.agents.experiment_design_agent.formal_encoding import repair_verification_encodings
from src.agents.experiment_design_agent.formal_expression import evaluate
from src.agents.experiment_design_agent.formal_verification import verify_formal_plan, validate_verification_report, scoped_diagnostics


def scalar_plan():
    plan = formal_plan()
    plan["proof_attempts"] = []
    plan["propositions"][0]["premises"] = []
    return plan


def number(value):
    return {"number": str(value)}


def call(name, *args):
    return {"call": name, "args": list(args)}


def verify(plan, backend):
    report = verify_formal_plan(plan, {"enabled": True, "backends": [backend], "timeout_seconds": 15})
    assert validate_verification_report(plan, report) == []
    return report


def test_sympy_trigonometric_identity_uses_native_api():
    plan = scalar_plan()
    symbol = {"symbol": "x"}
    plan["propositions"][0]["conclusion_expression"] = {
        "op": "eq", "args": [{"op": "add", "args": [
            {"op": "pow", "args": [call("sin", symbol), number(2)]},
            {"op": "pow", "args": [call("cos", symbol), number(2)]},
        ]}, number(1)],
    }
    assert _valid_restricted_expression(plan["propositions"][0]["conclusion_expression"])
    assert verify(plan, "sympy")["results"][0]["result"] == "passed"


def test_native_matrix_steps_and_rank_do_not_require_fake_scalar_quantifiers():
    plan = scalar_plan()
    target = plan["propositions"][0]
    target.update(quantifiers=[], symbol_references=[], calculation_steps=[
        {"name": "matrix", "backend": "sympy", "expression": call("eye", {"literal": 3})},
        {"name": "rank", "backend": "sympy", "expression": {"method": "rank", "object": {"ref": "matrix"}, "args": []}},
    ], conclusion_expression={"op": "eq", "args": [{"ref": "rank"}, number(3)]})
    report = verify(plan, "sympy")
    assert report["results"][0]["result"] == "passed"
    target["calculation_steps"][0]["expression"] = call("eye", {"literal": 4})
    assert any("stale_or_mismatched" in item for item in validate_verification_report(plan, report))


def test_symbolic_matrix_declaration_survives_contract_and_verification():
    plan = scalar_plan()
    target = plan["propositions"][0]
    target.update(symbol_references=[], quantifiers=[{
        "symbol": "A", "sort": "matrix", "quantifier": "forall",
        "declaration": call("MatrixSymbol", {"literal": "A"}, {"literal": 2}, {"literal": 2}),
    }], conclusion_expression={"op": "eq", "args": [
        {"op": "mul", "args": [{"symbol": "A"}, call("Identity", {"literal": 2})]}, {"symbol": "A"},
    ]})
    assert validate_formal_plan_v2(plan) == []
    assert verify(plan, "sympy")["results"][0]["result"] == "passed"


def test_z3_bitvectors_use_native_constructors():
    plan = scalar_plan()
    target = plan["propositions"][0]
    target.update(symbol_references=[], quantifiers=[{
        "symbol": "bits", "sort": "bitvector", "quantifier": "forall",
        "declaration": call("BitVec", {"literal": "bits"}, {"literal": 8}),
    }], conclusion_expression={"op": "eq", "args": [
        {"op": "add", "args": [{"symbol": "bits"}, call("BitVecVal", {"literal": 0}, {"literal": 8})]}, {"symbol": "bits"},
    ]})
    assert verify(plan, "z3")["results"][0]["result"] == "passed"


def test_z3_existential_target_is_not_treated_as_universal():
    plan = scalar_plan()
    target = plan["propositions"][0]
    target["quantifiers"][0]["quantifier"] = "exists"
    target["conclusion_expression"] = {"op": "gt", "args": [{"symbol": "x"}, number(100)]}
    assert verify(plan, "z3")["results"][0]["result"] == "passed"


def test_old_power_limit_is_removed():
    import sympy
    symbol = sympy.Symbol("x")
    assert evaluate({"op": "pow", "args": [{"symbol": "x"}, number(30)]}, {"x": symbol}, "sympy") == symbol ** 30
    assert evaluate({"op": "div", "args": [number(1), {"symbol": "x"}]}, {"x": symbol}, "sympy") == 1 / symbol


@pytest.mark.parametrize("node", [
    call("__import__", {"literal": "os"}),
    call("sympify", {"literal": "x"}),
    call("Symbol", {"literal": "__import__('os').system('echo bad')"}),
    {"constant": "__builtins__"},
])
def test_open_math_api_does_not_enable_source_evaluation(node):
    with pytest.raises(ValueError):
        evaluate(node, {}, "sympy")


def test_diagnostics_follow_target_needed_for_and_variable_paths():
    plan = scalar_plan()
    second = deepcopy(plan["propositions"][0])
    second.update(proposition_id="P2", quantifiers=[], symbol_references=[], variable_references=[],
                  conclusion_expression={"op": "eq", "args": [number(2), number(2)]})
    plan["propositions"].append(second)
    plan["unknown_items"] = [
        {"target_id": "P1", "path": "variables.V1.domain", "reason": "local gap"},
        {"needed_for": ["P1"], "reason": "local encoding"},
        {"field_path": "variables.V1.domain", "reason": "variable gap"},
        {"target_id": "P2", "reason": "already fixed", "resolved": True},
    ]
    assert len(scoped_diagnostics(plan, "P1")["unknown_items"]) == 3
    assert scoped_diagnostics(plan, "P2")["unknown_items"] == []
    report = verify(plan, "z3")
    assert all(item["executed"] for item in report["results"])
    assert report["target_summaries"][1]["status"] == "verified_in_declared_scope"


def test_missing_dependency_does_not_abort_independent_target():
    plan = scalar_plan()
    second = deepcopy(plan["propositions"][0])
    second.update(proposition_id="P2", premises=["DOES_NOT_EXIST"])
    plan["propositions"].append(second)
    report = verify(plan, "z3")
    assert {item["target_id"]: item["result"] for item in report["results"]} == {"P1": "failed", "P2": "dependency_missing"}


def test_encoding_repairs_only_target_and_archives_illegal_fields():
    plan = scalar_plan()
    target = plan["propositions"][0]
    expected = deepcopy(target["conclusion_expression"])
    target["conclusion_expression"] = None
    settings = {"enabled": True, "backends": ["z3"], "encoding": {"enabled": True, "max_rounds": 2}}
    calls = []
    def callback(prompt, **kwargs):
        calls.append(prompt)
        return {"patches": [
            {"record_id": "P1", "fields": {"conclusion_expression": expected, "statement": "illegal change"}},
            {"record_id": "P2", "fields": {"conclusion_expression": {"bool": True}}},
        ], "reasoning_steps": ["Encode the existing claim without changing its scope."]}
    report = verify_formal_plan(plan, settings)
    assert report["results"][0]["result"] == "not_encoded"
    report, audit = repair_verification_encodings(plan, settings, report, llm_call=callback)
    assert len(calls) == 1
    assert target["conclusion_expression"] == expected
    assert target["statement"] != "illegal change"
    assert len(audit[0]["rejected_operations"]) == 2
    assert report["results"][0]["result"] == "failed"
    assert validate_verification_report(plan, report) == []


def test_invalid_existing_encoding_is_retained_with_backend_candidate():
    plan = scalar_plan()
    target = plan["propositions"][0]
    original = {"call": "nonexistent_math_function", "args": [{"symbol": "x"}]}
    target["conclusion_expression"] = original
    settings = {"enabled": True, "backends": ["sympy"], "encoding": {"enabled": True, "max_rounds": 1}}
    report = verify_formal_plan(plan, settings)
    def callback(*args, **kwargs):
        return {"patches": [{"record_id": "P1", "backend": "sympy", "fields": {
            "conclusion_expression": {"op": "eq", "args": [{"symbol": "x"}, {"symbol": "x"}]},
        }}]}
    report, audit = repair_verification_encodings(plan, settings, report, llm_call=callback)
    assert target["conclusion_expression"] == original
    assert report["results"][0]["result"] == "passed"
    assert report["target_summaries"][0]["status"] == "encoding_requires_review"
    assert validate_verification_report(plan, report) == []


@pytest.mark.parametrize("backend", ["sympy", "z3"])
def test_variable_division_requires_nonzero_domain(backend):
    plan = scalar_plan()
    target = plan["propositions"][0]
    target["conclusion_expression"] = {"op": "eq", "args": [
        {"op": "div", "args": [{"symbol": "x"}, {"symbol": "x"}]}, number(1),
    ]}
    assert verify(plan, backend)["results"][0]["result"] == "unknown"
    target["domain_expression"] = {"op": "ne", "args": [{"symbol": "x"}, number(0)]}
    assert verify(plan, backend)["results"][0]["result"] == "passed"


def test_unscoped_diagnostic_is_advisory_but_explicit_global_applies():
    plan = scalar_plan()
    plan["unknown_items"] = [{"reason": "unassigned warning"}, {"field_path": "definitions[0].domain", "reason": "local"}]
    assert len(scoped_diagnostics(plan, "P1")["unknown_items"]) == 1
    plan["unknown_items"].append({"scope": "global", "reason": "global assumption pending"})
    assert len(scoped_diagnostics(plan, "P1")["unknown_items"]) == 2
