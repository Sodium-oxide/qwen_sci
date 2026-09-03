from __future__ import annotations

import re
from typing import Any, Callable, Dict, Iterable, List

import sympy as sp

from .power_b_equation_ir import CandidateModel, EquationIR, EquationNode
from .power_b_ontology import DEFAULT_VARIABLE_REGISTRY

_ALLOWED_LOCALS: Dict[str, Any] = {
    'sin': sp.sin,
    'cos': sp.cos,
    'tan': sp.tan,
    'asin': sp.asin,
    'acos': sp.acos,
    'atan': sp.atan,
    'sqrt': sp.sqrt,
    'exp': sp.exp,
    'log': sp.log,
    'Abs': sp.Abs,
    'pi': sp.pi,
}

_DERIVATIVE_PATTERN = re.compile(r'd\((?P<name>[A-Za-z_][A-Za-z0-9_]*)\)/dt')


def normalize_derivative_symbols(expr: str) -> str:
    return _DERIVATIVE_PATTERN.sub(lambda match: f'd_{match.group("name")}_dt', expr)


def _build_symbol_table(names: Iterable[str]) -> Dict[str, sp.Symbol]:
    return {name: sp.symbols(name, real=True) for name in names}


def _expression_symbol_names(ir: EquationIR) -> set[str]:
    names = set(DEFAULT_VARIABLE_REGISTRY)
    names.update(ref.name for ref in ir.variables)
    names.update(ref.name for ref in ir.parameters)
    for node in ir.equations:
        text = ' '.join([node.lhs, node.rhs, node.expression or ''])
        normalized = normalize_derivative_symbols(text)
        names.update(re.findall(r'[A-Za-z_][A-Za-z0-9_]*', normalized))
    names.difference_update(_ALLOWED_LOCALS)
    return names


def compile_equation_node(node: EquationNode, symbol_table: Dict[str, sp.Symbol]) -> sp.Expr:
    namespace = dict(_ALLOWED_LOCALS)
    namespace.update(symbol_table)
    lhs = normalize_derivative_symbols(node.lhs)
    rhs = normalize_derivative_symbols(node.rhs)
    expression = normalize_derivative_symbols(node.expression or f'({lhs}) - ({rhs})')
    if node.kind == 'residual':
        return sp.sympify(expression, locals=namespace)
    return sp.simplify(sp.sympify(expression, locals=namespace))


def compile_equation_ir(ir: EquationIR) -> tuple[Dict[str, sp.Symbol], List[sp.Expr], Callable[..., List[float]]]:
    symbol_table = _build_symbol_table(_expression_symbol_names(ir))
    residuals = [compile_equation_node(eq, symbol_table) for eq in ir.equations]

    ordered_names = sorted(symbol_table)
    ordered_symbols = [symbol_table[name] for name in ordered_names]
    residual_fn = sp.lambdify(ordered_symbols, residuals, modules='numpy')

    def evaluate(**values: float) -> List[float]:
        ordered_values = [values.get(name, 0.0) for name in ordered_names]
        out = residual_fn(*ordered_values)
        if isinstance(out, (list, tuple)):
            return [float(v) for v in out]
        return [float(out)]

    return symbol_table, residuals, evaluate


def compile_candidate_model(candidate: CandidateModel) -> tuple[EquationIR, Dict[str, sp.Symbol], List[sp.Expr], Callable[..., List[float]]]:
    ir = EquationIR(
        model_name=candidate.model_name,
        variables=list(candidate.variables),
        parameters=list(candidate.parameters),
        equations=list(candidate.equations),
        metadata=dict(candidate.metadata),
    )
    symbols, residuals, evaluate = compile_equation_ir(ir)
    return ir, symbols, residuals, evaluate
