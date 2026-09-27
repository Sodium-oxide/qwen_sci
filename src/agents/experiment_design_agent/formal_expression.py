"""Shared structural contract and open mathematical backend dispatch."""

from collections.abc import Mapping
from fractions import Fraction
import importlib
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
    "notes": "Calls use the selected backend's public mathematical API; no mathematical operator whitelist. "
             "Use explicit definitions for named predicates. No Python source evaluation or filesystem/network APIs. "
             "variable_ref requires an explicit variable_bindings entry; calculation steps are candidates, not proofs.",
}


def valid_expression(node, depth=0):
    if depth > 100 or not isinstance(node, Mapping):
        return False
    if set(node) & {"symbol", "ref", "constant", "variable_ref"}:
        return len(node) == 1 and isinstance(next(iter(node.values())), str) and bool(next(iter(node.values())).strip())
    if set(node) == {"number"}:
        try:
            Fraction(node["number"])
            return isinstance(node["number"], str)
        except (TypeError, ValueError, ZeroDivisionError):
            return False
    if set(node) == {"bool"}:
        return type(node["bool"]) is bool
    if set(node) == {"literal"}:
        return isinstance(node["literal"], (str, int, float, bool)) or node["literal"] is None
    if set(node) == {"list"}:
        return isinstance(node["list"], list) and all(valid_expression(item, depth + 1) for item in node["list"])
    if node.get("op") == "variable_ref":
        return isinstance(node.get("variable_id"), str)
    if node.get("op") == "predicate":
        return isinstance(node.get("predicate"), str) and isinstance(node.get("args"), list) and all(valid_expression(item, depth + 1) for item in node["args"])
    name = node.get("op", node.get("call", node.get("method")))
    return (isinstance(name, str) and bool(name.strip()) and isinstance(node.get("args", []), list)
            and all(valid_expression(item, depth + 1) for item in node.get("args", []))
            and isinstance(node.get("kwargs", {}), Mapping)
            and all(valid_expression(item, depth + 1) for item in node.get("kwargs", {}).values())
            and ("method" not in node or valid_expression(node.get("object"), depth + 1)))


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
