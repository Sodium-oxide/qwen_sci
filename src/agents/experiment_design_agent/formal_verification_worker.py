"""Isolated, bounded mathematical backends using a restricted expression tree."""

from __future__ import annotations

from fractions import Fraction
import json
import sys

try:  # The worker is also executed as a standalone script.
    from .formal_capabilities import result_metadata
    from .proof_assistant_backend import run_lean_task
    from .formal_expression import evaluate, declared_symbols, domain_requirements
    from .formal_runtime import prepare_runtime
except ImportError:  # pragma: no cover - exercised by subprocess execution.
    from formal_capabilities import result_metadata
    from proof_assistant_backend import run_lean_task
    from formal_expression import evaluate, declared_symbols, domain_requirements
    from formal_runtime import prepare_runtime


class UnsupportedExpression(ValueError):
    pass


def expression(node, symbols, backend, depth=0):
    return evaluate(node, symbols, backend, depth)


def _metadata(backend, **coverage):
    return result_metadata(backend, coverage=coverage or None)


def _z3_result(task):
    import z3

    symbols = declared_symbols(task, "z3")
    constraints = [expression(item, symbols, "z3") for item in task["constraints"]]
    conclusion = expression(task["conclusion_expression"], symbols, "z3")
    if not z3.is_bool(conclusion) or any(not z3.is_bool(item) for item in constraints):
        raise UnsupportedExpression("expected_predicates")
    solver = z3.Solver()
    solver.set(timeout=max(1, int(task["timeout_seconds"] * 1000)))
    solver.add(*constraints)
    domain_result = solver.check()
    if domain_result != z3.sat:
        return {
            "result": "unknown",
            "limitations": ["inconsistent_domain" if domain_result == z3.unsat else solver.reason_unknown()],
            "backend_version": z3.get_version_string(),
            **_metadata("z3", domain="declared_encoded_domain"),
        }
    requirements = domain_requirements([*task["constraints"], task["conclusion_expression"], task.get("calculation_steps", [])], symbols, "z3")
    if requirements:
        solver.push()
        solver.add(z3.Not(z3.And(*requirements)))
        domain_complete = solver.check() == z3.unsat
        solver.pop()
        if not domain_complete:
            return {"result": "unknown", "evidence_kind": "none", "backend_version": z3.get_version_string(),
                    "limitations": ["Additional domain conditions require justification: " + str(requirements)],
                    **_metadata("z3", domain="requires_domain_conditions")}
    solver.add(z3.Not(conclusion))
    quantified = task.get("quantifiers", [])
    if any(item.get("quantifier") == "exists" for item in quantified):
        if not all(item.get("quantifier") == "exists" for item in quantified):
            raise UnsupportedExpression("mixed_quantifiers_require_explicit_ForAll_Exists_expression")
        formula = z3.Exists([symbols[item["symbol"]] for item in quantified], z3.And(*constraints, conclusion))
        solver = z3.Solver()
        solver.set(timeout=max(1, int(task["timeout_seconds"] * 1000)))
        solver.add(z3.Not(formula))
    result = solver.check()
    if result == z3.unsat:
        return {
            "result": "passed",
            "evidence_kind": "smt_unsat",
            "backend_version": z3.get_version_string(),
            "limitations": ["Applies only to the encoded model and declared domain."],
            **_metadata("z3", domain="declared_encoded_domain"),
        }
    if result == z3.sat:
        if any(item.get("quantifier") == "exists" for item in quantified):
            return {"result": "unknown", "evidence_kind": "none", "backend_version": z3.get_version_string(),
                    "limitations": ["Existential proposition was not established; no scalar witness certificate."],
                    **_metadata("z3", domain="declared_encoded_domain")}
        model = solver.model()
        checked = all(
            z3.is_true(model.eval(item, model_completion=True))
            for item in [*constraints, z3.Not(conclusion)]
        )
        return {
            "result": "failed" if checked else "unknown",
            "evidence_kind": "smt_witness",
            "witness": {name: str(model.eval(symbol, model_completion=True)) for name, symbol in symbols.items()},
            "backend_version": z3.get_version_string(),
            "limitations": ["Formal witness within the encoded model; physical applicability is separate."],
            **_metadata("z3", domain="declared_encoded_domain"),
        }
    return {
        "result": "unknown",
        "limitations": [solver.reason_unknown()],
        "backend_version": z3.get_version_string(),
        **_metadata("z3", domain="declared_encoded_domain"),
    }


def _sympy_result(task):
    import sympy

    symbols = declared_symbols(task, "sympy")
    if any(item.get("quantifier") == "exists" for item in task.get("quantifiers", [])):
        raise UnsupportedExpression("existential_proof_requires_z3")
    conclusion_ast = task["conclusion_expression"]
    requirements = domain_requirements([*task["constraints"], conclusion_ast, task.get("calculation_steps", [])], symbols, "sympy")
    constraints = [expression(item, symbols, "sympy") for item in task["constraints"]]
    for requirement in requirements:
        if requirement is True or requirement is sympy.true or any(requirement == condition for condition in constraints):
            continue
        try:
            counterdomain = sympy.reduce_inequalities([*constraints, sympy.Not(requirement)], list(requirement.free_symbols))
        except (TypeError, ValueError, NotImplementedError):
            counterdomain = None
        if counterdomain is not sympy.false and counterdomain is not False:
            return {"result": "unknown", "evidence_kind": "none", "backend_version": sympy.__version__,
                    "limitations": ["Additional domain condition requires justification: " + str(requirement)],
                    **_metadata("sympy", domain="requires_domain_conditions")}
    if conclusion_ast.get("op", conclusion_ast.get("call")) not in {"eq", "Eq"} or len(conclusion_ast.get("args", [])) != 2:
        conclusion = sympy.simplify(expression(conclusion_ast, symbols, "sympy"))
        return {
            "result": "passed" if conclusion is sympy.true else "unknown",
            "evidence_kind": "symbolic_identity", "backend_version": sympy.__version__,
            "residual": str(conclusion), "limitations": ["Symbolic simplification of the encoded proposition."],
            **_metadata("sympy", domain="declared_symbolic_domain"),
        }
    left, right = [expression(item, symbols, "sympy") for item in conclusion_ast["args"]]
    difference = sympy.simplify(left - right)
    if difference == 0 or getattr(difference, "is_zero_matrix", False) is True or getattr(difference, "is_ZeroMatrix", False) is True:
        result = "passed"
    elif task["constraints"] == [{"bool": True}]:
        result = "unknown"
    else:
        try:
            constraints = [expression(item, symbols, "sympy") for item in task["constraints"]]
            contradiction = sympy.reduce_inequalities(
                [*constraints, sympy.Ne(left, right)], list(symbols.values())
            )
            result = "passed" if contradiction is sympy.false or contradiction is False else "unknown"
        except (TypeError, ValueError, NotImplementedError):
            result = "unknown"
    return {
        "result": result,
        "evidence_kind": "symbolic_identity",
        "backend_version": sympy.__version__,
        "residual": str(difference),
        "limitations": ["Symbolic identity within the declared mathematical model."],
        **_metadata(
            "sympy",
            domain="declared_scalar_domain",
            conditional=bool(task["constraints"] != [{"bool": True}]),
        ),
    }


def _numerical_result(task):
    import sympy

    symbols = declared_symbols(task, "sympy")
    constraints = [expression(item, symbols, "sympy") for item in task["constraints"]]
    conclusion = expression(task["conclusion_expression"], symbols, "sympy")
    for index, witness in enumerate(task.get("candidate_points", [])[:100]):
        if set(witness) != set(symbols):
            continue
        sorts = {item["symbol"]: item["sort"] for item in task["quantifiers"]}
        if any(
            sorts[name] == "boolean"
            or (sorts[name] == "integer" and Fraction(value).denominator != 1)
            for name, value in witness.items()
        ):
            continue
        substitutions = {
            symbols[name]: expression({"number": value}, {}, "sympy")
            for name, value in witness.items()
        }
        if all(item.subs(substitutions) == sympy.true for item in constraints) and conclusion.subs(substitutions) == sympy.false:
            candidate_ids = task.get("candidate_ids", [])
            return {
                "result": "failed",
                "evidence_kind": "numerical_candidate",
                "counterexample_id": candidate_ids[index] if index < len(candidate_ids) else None,
                "witness": witness,
                "backend_version": sympy.__version__,
                "limitations": ["Candidate-point check only; no general theorem status is awarded."],
                **_metadata("numerical", candidate_limit=100),
            }
    return {
        "result": "unknown",
        "evidence_kind": "numerical_candidate",
        "limitations": ["No witness found among supplied points; search is not exhaustive."],
        **_metadata("numerical", candidate_limit=100),
    }


def solve(task):
    backend = task["backend"]
    if backend == "z3":
        return _z3_result(task)
    if backend == "sympy":
        return _sympy_result(task)
    if backend == "numerical":
        return _numerical_result(task)
    if backend == "lean":
        return run_lean_task(task)
    return {
        "result": "unsupported",
        "limitations": ["Proof assistant backend is not configured."],
        **(_metadata(backend, available=False) if backend in {"lean", "rules"} else {}),
    }


def main(*, isolated=False):
    try:
        task = json.load(sys.stdin)
        if isolated:
            prepare_runtime(task)
        result = solve(task)
    except MemoryError:
        result = {"result": "unknown", "limitations": ["Mathematical worker memory budget exceeded."]}
    except ImportError as error:
        result = {"result": "backend_unavailable", "limitations": [f"Missing backend: {error.name}"]}
    except Exception as error:
        missing = str(error).startswith(("unbound_symbol:", "unbound_variable_reference:", "undefined_predicate:", "missing_backend_declaration:"))
        result = {"result": "not_encoded" if missing else "unsupported", "limitations": [f"{type(error).__name__}: {error}"]}
    print(json.dumps(result, allow_nan=False))


if __name__ == "__main__":
    main(isolated=True)
