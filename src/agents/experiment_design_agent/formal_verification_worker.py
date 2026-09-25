"""Isolated, bounded mathematical backends using a restricted expression tree."""

from __future__ import annotations

from fractions import Fraction
import json
import sys

try:  # The worker is also executed as a standalone script.
    from .formal_capabilities import result_metadata
    from .proof_assistant_backend import run_lean_task
except ImportError:  # pragma: no cover - exercised by subprocess execution.
    from formal_capabilities import result_metadata
    from proof_assistant_backend import run_lean_task


class UnsupportedExpression(ValueError):
    pass


def expression(node, symbols, backend, depth=0):
    if depth > 40 or not isinstance(node, dict):
        raise UnsupportedExpression("invalid_or_deep_expression")
    if set(node) == {"symbol"}:
        if node["symbol"] not in symbols:
            raise UnsupportedExpression("undeclared_symbol")
        return symbols[node["symbol"]]
    if set(node) == {"number"}:
        value = node["number"]
        if not isinstance(value, str) or len(value) > 100:
            raise UnsupportedExpression("invalid_number")
        rational = Fraction(value)
        if backend == "z3":
            import z3

            return z3.RealVal(f"{rational.numerator}/{rational.denominator}")
        import sympy

        return sympy.Rational(rational.numerator, rational.denominator)
    if set(node) == {"bool"} and type(node["bool"]) is bool:
        if backend == "z3":
            import z3

            return z3.BoolVal(node["bool"])
        import sympy

        return sympy.true if node["bool"] else sympy.false
    if set(node) != {"op", "args"} or not isinstance(node["args"], list):
        raise UnsupportedExpression("invalid_expression_shape")
    operator = node["op"]
    arity = {
        "add": 2, "sub": 2, "mul": 2, "div": 2, "pow": 2,
        "eq": 2, "ne": 2, "lt": 2, "le": 2, "gt": 2, "ge": 2,
        "not": 1, "implies": 2, "iff": 2, "xor": 2, "ite": 3,
    }
    if operator in {"and", "or"}:
        if not node["args"]:
            raise UnsupportedExpression("empty_boolean_expression")
    elif operator not in arity or len(node["args"]) != arity[operator]:
        raise UnsupportedExpression("unsupported_operator_or_arity")
    if operator == "div":
        denominator = node["args"][1]
        if set(denominator) != {"number"} or Fraction(denominator["number"]) == 0:
            raise UnsupportedExpression("division_requires_nonzero_constant")
    if operator == "pow":
        exponent = node["args"][1]
        if set(exponent) != {"number"}:
            raise UnsupportedExpression("power_requires_integer_constant")
        value = Fraction(exponent["number"])
        if value.denominator != 1 or not 0 <= value <= 12:
            raise UnsupportedExpression("unsupported_exponent")
    arguments = [expression(item, symbols, backend, depth + 1) for item in node["args"]]
    if backend == "z3":
        import z3

        boolean_ops = {
            "and": z3.And,
            "or": z3.Or,
            "not": z3.Not,
            "implies": z3.Implies,
            "iff": lambda left, right: left == right,
            "xor": z3.Xor,
        }
        comparisons = {"eq": lambda left, right: left == right, "ne": lambda left, right: left != right}
    else:
        import sympy

        boolean_ops = {
            "and": sympy.And,
            "or": sympy.Or,
            "not": sympy.Not,
            "implies": sympy.Implies,
            "iff": sympy.Equivalent,
            "xor": sympy.Xor,
        }
        comparisons = {"eq": sympy.Eq, "ne": sympy.Ne}
    if operator in boolean_ops:
        return boolean_ops[operator](*arguments)
    if operator in comparisons:
        return comparisons[operator](*arguments)
    if operator == "ite":
        condition, when_true, when_false = arguments
        if backend == "z3":
            import z3

            return z3.If(condition, when_true, when_false)
        import sympy

        return sympy.Piecewise((when_true, condition), (when_false, True))
    left, right = arguments
    return {
        "add": lambda: left + right,
        "sub": lambda: left - right,
        "mul": lambda: left * right,
        "div": lambda: left / right,
        "pow": lambda: left ** int(Fraction(node["args"][1]["number"])),
        "lt": lambda: left < right,
        "le": lambda: left <= right,
        "gt": lambda: left > right,
        "ge": lambda: left >= right,
    }[operator]()


def _metadata(backend, **coverage):
    return result_metadata(backend, coverage=coverage or None)


def _z3_result(task):
    import z3

    constructors = {"real": z3.Real, "integer": z3.Int, "boolean": z3.Bool}
    symbols = {item["symbol"]: constructors[item["sort"]](item["symbol"]) for item in task["quantifiers"]}
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
    solver.add(z3.Not(conclusion))
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

    symbols = {
        item["symbol"]: sympy.Symbol(item["symbol"], real=True, integer=item["sort"] == "integer")
        for item in task["quantifiers"]
        if item["sort"] != "boolean"
    }
    conclusion_ast = task["conclusion_expression"]
    if conclusion_ast.get("op") != "eq" or len(conclusion_ast.get("args", [])) != 2:
        raise UnsupportedExpression("sympy_requires_identity")
    left, right = [expression(item, symbols, "sympy") for item in conclusion_ast["args"]]
    difference = sympy.expand(left - right)
    if difference == 0:
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
        "limitations": ["Polynomial identity over the declared scalar domain."],
        **_metadata(
            "sympy",
            domain="declared_scalar_domain",
            conditional=bool(task["constraints"] != [{"bool": True}]),
        ),
    }


def _numerical_result(task):
    import sympy

    symbols = {item["symbol"]: sympy.Symbol(item["symbol"], real=True) for item in task["quantifiers"]}
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


def main():
    try:
        task = json.loads(sys.stdin.read(1000000))
        result = solve(task)
    except ImportError as error:
        result = {"result": "unsupported", "limitations": [f"Missing backend: {error.name}"]}
    except Exception as error:
        result = {"result": "unsupported", "limitations": [f"{type(error).__name__}: {error}"]}
    print(json.dumps(result, allow_nan=False))


if __name__ == "__main__":
    main()
