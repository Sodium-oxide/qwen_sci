"""Shared structural contract and open mathematical backend dispatch."""

from collections.abc import Mapping
from fractions import Fraction
import importlib
import math
import operator
from types import ModuleType


EXPRESSION_CONTRACT = {
    "version": "formal_expression_v2",
    "leaves": [{"symbol": "x"}, {"number": "1/3"}, {"bool": True}, {"literal": "x"}],
    "call": {"call": "Matrix", "args": [{"list": [{"list": [{"number": "1"}]}]}]},
    "method": {"method": "rank", "object": {"ref": "matrix"}, "args": []},
    "operation": {"op": "backend mathematical function or arithmetic alias", "args": []},
    "steps": [{"name": "matrix", "backend": "sympy", "expression": {"call": "eye", "args": [{"number": "2"}]}}],
    "declaration": {"symbol": "A", "sort": "matrix", "quantifier": "forall",
                    "declaration": {"call": "MatrixSymbol", "args": [{"literal": "A"}, {"number": "2"}, {"number": "2"}]}},
    "structure_rules": {
        "number": "Use a numeric string such as \"0\", \"0.5\" or \"1/3\", not a JSON number.",
        "symbol": "A symbol leaf contains only symbol; declare sort and quantifier separately.",
        "args": "Each argument is an expression object, not formula text or a bare number.",
        "unencoded": "Use null with an encoding-gap explanation; do not use op unknown.",
    },
    "predicate": {"op": "predicate", "predicate": "admissible", "args": [{"symbol": "computer"}]},
    "notes": "Calls use the selected backend's public mathematical API; no mathematical operator whitelist. "
             "Use explicit definitions for named predicates. No Python source evaluation or filesystem/network APIs. "
             "variable_ref requires an explicit variable_bindings entry; calculation steps are candidates, not proofs.",
}


def expression_diagnostics(node, depth=0, *, path="$", reject_unknown=False):
    def error(code, expected, value=node, node_path=path):
        return [{"node_path": node_path, "error_code": code,
                 "actual_type": type(value).__name__, "expected": expected}]

    if depth > 100:
        return error("expression_depth_exceeded", "At most 100 nested expression levels.")
    if not isinstance(node, Mapping):
        return error("expression_requires_object", "An expression object; put formula text in the text field.")
    if reject_unknown and node.get("op") == "unknown":
        return error("unknown_expression", "A symbolic expression or null with an encoding-gap explanation.")
    if set(node) & {"symbol", "ref", "constant", "variable_ref"}:
        if len(node) != 1:
            return error("leaf_has_extra_keys", "A single-key leaf; declarations belong outside the expression.")
        name = next(iter(node.values()))
        return [] if isinstance(name, str) and name.strip() else error("invalid_leaf_name", "A nonempty string.")
    if set(node) == {"number"}:
        if not isinstance(node["number"], str):
            return error("number_requires_string", 'A numeric string such as "0" or "1/3".',
                         node["number"], f"{path}.number")
        try:
            Fraction(node["number"])
            return []
        except (TypeError, ValueError, ZeroDivisionError):
            return error("invalid_number", "A finite rational numeric string.", node["number"], f"{path}.number")
    if set(node) == {"bool"}:
        return [] if type(node["bool"]) is bool else error("invalid_bool", "A JSON boolean.", node["bool"], f"{path}.bool")
    if set(node) == {"literal"}:
        return [] if isinstance(node["literal"], (str, int, float, bool)) or node["literal"] is None else error("invalid_literal", "A scalar literal.")
    if set(node) == {"list"}:
        if not isinstance(node["list"], list):
            return error("list_requires_array", "An array of expression nodes.", node["list"], f"{path}.list")
        return [issue for index, item in enumerate(node["list"])
                for issue in expression_diagnostics(item, depth + 1, path=f"{path}.list[{index}]", reject_unknown=reject_unknown)]
    if node.get("op") == "variable_ref":
        return [] if isinstance(node.get("variable_id"), str) else error("invalid_variable_reference", "A string variable_id.")
    if node.get("op") == "predicate":
        if not isinstance(node.get("predicate"), str):
            return error("invalid_predicate_name", "A string predicate name.")
        if "args" not in node:
            return error("predicate_requires_args", "An explicit args array.")
    name = node.get("op", node.get("call", node.get("method")))
    if not isinstance(name, str) or not name.strip():
        return error("missing_expression_operator", "A nonempty op, call or method name.")
    if not isinstance(node.get("args", []), list):
        return error("args_requires_array", "An array of expression objects.", node["args"], f"{path}.args")
    if not isinstance(node.get("kwargs", {}), Mapping):
        return error("kwargs_requires_object", "An object of named expression arguments.", node["kwargs"], f"{path}.kwargs")
    issues = [issue for index, item in enumerate(node.get("args", []))
              for issue in expression_diagnostics(item, depth + 1, path=f"{path}.args[{index}]", reject_unknown=reject_unknown)]
    issues.extend(issue for key, item in node.get("kwargs", {}).items()
                  for issue in expression_diagnostics(item, depth + 1, path=f"{path}.kwargs.{key}", reject_unknown=reject_unknown))
    if "method" in node:
        issues.extend(expression_diagnostics(node.get("object"), depth + 1, path=f"{path}.object", reject_unknown=reject_unknown))
    return issues


def valid_expression(node, depth=0):
    return not expression_diagnostics(node, depth)


def normalize_expression(node, depth=0):
    if depth > 100:
        return node
    if isinstance(node, Mapping):
        if set(node) == {"number"} and (type(node["number"]) is int or
                                        type(node["number"]) is float and math.isfinite(node["number"])):
            return {"number": str(node["number"])}
        return {key: normalize_expression(value, depth + 1) for key, value in node.items()}
    if isinstance(node, list):
        return [normalize_expression(value, depth + 1) for value in node]
    return node


def valid_declarations(value):
    return isinstance(value, list) and all(
        isinstance(item, Mapping) and isinstance(item.get("symbol"), str) and bool(item["symbol"].strip())
        and isinstance(item.get("sort"), str) and bool(item["sort"].strip())
        and item.get("quantifier") in {"forall", "exists", "parameter"}
        and ("declaration" not in item or valid_expression(item["declaration"])) for item in value
    )


def _public_name(name):
    forbidden = {"sympify", "S", "parse_expr", "parse_smt2_file", "parse_smt2_string", "lambdify", "lambdastr",
                 "autowrap", "ufuncify", "preview", "source", "python", "exec", "eval", "compile", "open",
                 "print", "input", "test", "doctest", "init_session", "init_printing", "open_log", "append_log",
                 "from_file", "from_string", "load", "save", "dump", "dumps", "to_file"}
    if not isinstance(name, str) or not name.isidentifier() or name.startswith("_") or "__" in name or name in forbidden or name.startswith(("plot", "codegen", "Z3_")):
        raise ValueError(f"non_mathematical_api:{name}")
    return name


def evaluate(node, symbols, backend, depth=0):
    if depth > 100 or not isinstance(node, Mapping):
        raise ValueError("invalid_expression_shape")
    module = importlib.import_module(backend)
    if set(node) in ({"symbol"}, {"ref"}):
        name = next(iter(node.values()))
        if name not in symbols:
            raise ValueError(f"unbound_symbol:{name}")
        return symbols[name]
    if set(node) == {"number"}:
        value = Fraction(node["number"])
        if backend == "z3":
            return module.RealVal(str(value))
        return module.Rational(value.numerator, value.denominator)
    if set(node) == {"bool"}:
        return module.BoolVal(node["bool"]) if backend == "z3" else module.true if node["bool"] else module.false
    if set(node) == {"literal"}:
        value = node["literal"]
        if isinstance(value, str) and (not value.isidentifier() or "__" in value):
            try:
                Fraction(value)
            except (ValueError, ZeroDivisionError):
                raise ValueError("literal_text_must_be_a_name_or_number") from None
        return value
    if set(node) == {"constant"}:
        value = getattr(module, _public_name(node["constant"]))
        if isinstance(value, ModuleType):
            raise ValueError("backend_module_is_not_a_mathematical_value")
        return value
    if set(node) == {"list"}:
        return [evaluate(item, symbols, backend, depth + 1) for item in node["list"]]
    if node.get("op") == "variable_ref" or "variable_ref" in node:
        name = node.get("variable_id", node.get("variable_ref"))
        if name not in symbols:
            raise ValueError(f"unbound_variable_reference:{name}")
        return symbols[name]
    if node.get("op") == "predicate":
        name = node["predicate"]
        if name not in symbols:
            raise ValueError(f"undefined_predicate:{name}")
        return symbols[name](*[evaluate(item, symbols, backend, depth + 1) for item in node.get("args", [])])
    name = node.get("op", node.get("call", node.get("method")))
    arguments = [evaluate(item, symbols, backend, depth + 1) for item in node.get("args", [])]
    keywords = {_public_name(key): evaluate(value, symbols, backend, depth + 1) for key, value in node.get("kwargs", {}).items()}
    arithmetic = {"add": operator.add, "sub": operator.sub, "mul": operator.mul, "div": operator.truediv,
                  "pow": operator.pow, "lt": operator.lt, "le": operator.le, "gt": operator.gt, "ge": operator.ge}
    if name in arithmetic:
        return arithmetic[name](*arguments)
    aliases = {"eq": "Eq", "ne": "Ne", "and": "And", "or": "Or", "not": "Not", "implies": "Implies",
               "iff": "Equivalent", "xor": "Xor", "ite": "Piecewise"}
    if backend == "z3" and name in {"eq", "ne", "iff"}:
        return (operator.ne if name == "ne" else operator.eq)(*arguments)
    if name == "ite":
        return module.If(*arguments) if backend == "z3" else module.Piecewise((arguments[1], arguments[0]), (arguments[2], True))
    name = _public_name(aliases.get(name, name))
    owner = evaluate(node["object"], symbols, backend, depth + 1) if "method" in node else module
    function = getattr(owner, name, None)
    if not callable(function):
        raise ValueError(f"backend_api_unavailable:{backend}:{name}")
    origin = getattr(function, "__module__", None) or type(owner).__module__
    if not origin.startswith(("sympy.", "z3.")):
        raise ValueError(f"non_mathematical_callable:{name}")
    return function(*arguments, **keywords)


def declared_symbols(task, backend):
    module = importlib.import_module(backend)
    symbols = {}
    for item in task.get("quantifiers", []):
        name, sort = item["symbol"], item["sort"]
        if item.get("declaration") is not None:
            symbols[name] = evaluate(item["declaration"], symbols, backend)
        elif backend == "z3":
            constructor = {"real": "Real", "integer": "Int", "boolean": "Bool", "string": "String"}.get(sort)
            if constructor is None:
                raise ValueError(f"missing_backend_declaration:{name}:{sort}")
            symbols[name] = getattr(module, constructor)(name)
        else:
            options = {"real": True} if sort == "real" else {"integer": True} if sort == "integer" else {}
            symbols[name] = module.Symbol(name, **options)
    for identifier, expression in task.get("variable_bindings", {}).items():
        symbols[identifier] = evaluate(expression, symbols, backend)
    for step in task.get("calculation_steps", []):
        if step.get("backend", backend) == backend:
            if step["name"] in symbols:
                raise ValueError(f"calculation_step_overwrites_symbol:{step['name']}")
            symbols[step["name"]] = evaluate(step["expression"], symbols, backend)
    return symbols


def domain_requirements(node, symbols, backend):
    module = importlib.import_module(backend)
    requirements = []
    if isinstance(node, list):
        return [condition for item in node for condition in domain_requirements(item, symbols, backend)]
    if not isinstance(node, Mapping):
        return requirements
    for item in node.values():
        requirements.extend(domain_requirements(item, symbols, backend))
    name = node.get("op", node.get("call", node.get("method")))
    args = node.get("args", [])
    def nonzero(value):
        return value != 0 if backend == "z3" else module.Ne(value, 0)
    if name == "div" and len(args) == 2:
        requirements.append(nonzero(evaluate(args[1], symbols, backend)))
    if name in {"pow", "Pow"} and len(args) == 2:
        base = evaluate(args[0], symbols, backend)
        try:
            exponent = Fraction(args[1]["number"])
        except (KeyError, TypeError, ValueError, ZeroDivisionError):
            requirements.append(base > 0)
        else:
            if exponent.denominator != 1:
                requirements.append(base > 0 if exponent < 0 else base >= 0)
            elif exponent < 0:
                requirements.append(nonzero(base))
    if name in {"log", "sqrt"} and args:
        argument = evaluate(args[0], symbols, backend)
        if backend == "sympy" and argument.is_real is True:
            requirements.append(argument > 0 if name == "log" else argument >= 0)
    if name == "inv" and "object" in node and backend == "sympy":
        matrix = evaluate(node["object"], symbols, backend)
        if hasattr(matrix, "det"):
            requirements.append(nonzero(matrix.det()))
    return requirements
