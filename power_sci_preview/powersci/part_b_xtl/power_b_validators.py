from __future__ import annotations

from dataclasses import dataclass
from typing import List, Sequence

import numpy as np

from .power_b_equation_ir import CandidateModel, EquationIR, ValidationError, ValidationReport
from .power_b_ontology import DEFAULT_VARIABLE_REGISTRY
from .power_b_sympy_compiler import compile_candidate_model


STRUCTURE_ERROR_UNKNOWN_VARIABLE = 'UNKNOWN_VARIABLE'
STRUCTURE_ERROR_EMPTY_EQUATIONS = 'EMPTY_EQUATION_SET'
STRUCTURE_ERROR_MISSING_DERIVATIVE = 'MISSING_DERIVATIVE_EQUATION'
STRUCTURE_ERROR_UNIT_MISMATCH = 'UNIT_MISMATCH'
NUMERICAL_ERROR_DIVERGENCE = 'NUMERICAL_DIVERGENCE'
NUMERICAL_ERROR_NONFINITE = 'NONFINITE_RESIDUAL'
PHYSICAL_ERROR_POWER_BALANCE = 'POWER_BALANCE_VIOLATION'
PHYSICAL_ERROR_ALGEBRAIC_CLOSURE = 'ALGEBRAIC_CLOSURE_MISSING'
PHYSICAL_ERROR_UNSTABLE_EIGENVALUE = 'EIGENVALUE_UNSTABLE'

_ALLOWED_SYMBOLS = {'sin', 'cos', 'tan', 'sqrt', 'exp', 'log', 'Abs', 'pi', 'd', 'dt'}


@dataclass(frozen=True)
class ValidationContext:
    tolerance: float = 1e-6
    residual_threshold: float = 1e-5
    power_balance_threshold: float = 1e-4


def _report(model_name: str, stage: str, passed: bool, errors: List[ValidationError] | None = None, warnings: List[str] | None = None, metrics: dict | None = None) -> ValidationReport:
    return ValidationReport(
        model_name=model_name,
        passed=passed,
        stage=stage,
        errors=errors or [],
        warnings=warnings or [],
        metrics=metrics or {},
        stage_checks=[{"stage": stage, "status": "PASS" if passed else "FAIL"}],
    )


def validate_equation_ir(ir: EquationIR, context: ValidationContext | None = None) -> ValidationReport:
    context = context or ValidationContext()
    errors: List[ValidationError] = []
    if not ir.equations:
        errors.append(ValidationError(code=STRUCTURE_ERROR_EMPTY_EQUATIONS, message='No equations provided'))
        return _report(ir.model_name, 'structure', False, errors)

    known = set(DEFAULT_VARIABLE_REGISTRY)
    declared = {ref.name for ref in ir.variables} | {ref.name for ref in ir.parameters}
    for node in ir.equations:
        tokens = _extract_tokens(node.lhs) | _extract_tokens(node.rhs) | _extract_tokens(node.expression or '')
        for token in sorted(tokens):
            if token.isidentifier() and token not in known and token not in declared and token not in _ALLOWED_SYMBOLS:
                errors.append(ValidationError(code=STRUCTURE_ERROR_UNKNOWN_VARIABLE, message=f'Unknown variable {token}', target=token))
        if node.kind == 'ode' and 'd(' not in node.lhs:
            errors.append(ValidationError(code=STRUCTURE_ERROR_MISSING_DERIVATIVE, message=f'ODE missing derivative lhs: {node.lhs}', target=node.lhs))

        lhs_unit = node.unit or _infer_unit_from_lhs(node.lhs)
        rhs_unit = node.unit or _infer_unit_from_rhs(node.rhs)
        if lhs_unit and rhs_unit and lhs_unit != rhs_unit:
            errors.append(ValidationError(code=STRUCTURE_ERROR_UNIT_MISMATCH, message=f'Unit mismatch: {lhs_unit} != {rhs_unit}', target=node.lhs))

    return _report(ir.model_name, 'structure', not errors, errors)


def validate_candidate_model(candidate: CandidateModel, context: ValidationContext | None = None, sample_points: Sequence[dict] | None = None) -> ValidationReport:
    context = context or ValidationContext()
    ir, _, _, evaluate = compile_candidate_model(candidate)
    structure = validate_equation_ir(ir, context)
    if not structure.passed:
        return structure

    stage_checks = [{"stage": "V1", "status": "PASS"}]
    physical_errors = _physical_checks(ir)
    if physical_errors:
        stage_checks.extend([{"stage": "V2", "status": "NOT_RUN"}, {"stage": "V3", "status": "FAIL"}])
        return ValidationReport(model_name=ir.model_name, passed=False, stage='physical', errors=physical_errors, metrics={}, stage_checks=stage_checks)

    sample_points = sample_points or [
        {'delta': 0.0, 'omega': 1.0, 'Pm': 1.0, 'Pe': 1.0, 'D': 0.0, 'H': 3.5, 'omega_b': 377.0, 'd_delta_dt': 0.0, 'd_omega_dt': 0.0},
        {'delta': 0.1, 'omega': 1.0, 'Pm': 0.8, 'Pe': 0.8, 'D': 0.1, 'H': 4.0, 'omega_b': 377.0, 'd_delta_dt': 0.0, 'd_omega_dt': 0.0},
    ]
    residual_norms: List[float] = []
    for point in sample_points:
        residuals = evaluate(**point)
        arr = np.asarray(residuals, dtype=float)
        if not np.all(np.isfinite(arr)):
            stage_checks.extend([{"stage": "V2", "status": "FAIL"}, {"stage": "V3", "status": "NOT_RUN"}])
            return ValidationReport(model_name=ir.model_name, passed=False, stage='numerical', errors=[ValidationError(code=NUMERICAL_ERROR_NONFINITE, message='Residual contains non-finite values')], metrics={}, stage_checks=stage_checks)
        residual_norms.append(float(np.linalg.norm(arr, ord=2)))
    mean_norm = float(np.mean(residual_norms))
    if mean_norm > context.residual_threshold:
        stage_checks.extend([{"stage": "V2", "status": "FAIL"}, {"stage": "V3", "status": "NOT_RUN"}])
        return ValidationReport(model_name=ir.model_name, passed=False, stage='numerical', errors=[ValidationError(code=NUMERICAL_ERROR_DIVERGENCE, message=f'Residual norm too large: {mean_norm:.3e}')], metrics={'residual_norm': mean_norm}, stage_checks=stage_checks)

    stage_checks.extend([{"stage": "V2", "status": "PASS"}, {"stage": "V3", "status": "PASS"}])
    return ValidationReport(model_name=ir.model_name, passed=True, stage='physical', metrics={'residual_norm': mean_norm}, stage_checks=stage_checks)


def _physical_checks(ir: EquationIR) -> List[ValidationError]:
    text = ' '.join(eq.lhs + ' ' + eq.rhs + ' ' + (eq.expression or '') for eq in ir.equations)
    errors: List[ValidationError] = []
    omega_equations = [eq for eq in ir.equations if eq.kind == 'ode' and 'omega' in eq.lhs]
    algebraic_text = ' '.join(eq.lhs + ' ' + eq.rhs + ' ' + (eq.expression or '') for eq in ir.equations if eq.kind in {'algebraic', 'residual'})

    if omega_equations and 'Pm' in text and 'Pe' not in ' '.join(eq.rhs + ' ' + (eq.expression or '') for eq in omega_equations):
        errors.append(ValidationError(code=PHYSICAL_ERROR_POWER_BALANCE, message='Swing equation has mechanical power but no electrical power counter-term'))
    if 'Pe' in text and 'Pe' not in algebraic_text:
        errors.append(ValidationError(code=PHYSICAL_ERROR_ALGEBRAIC_CLOSURE, message='Pe is used but has no algebraic closure equation'))
    if _has_unstable_linear_term(text):
        errors.append(ValidationError(code=PHYSICAL_ERROR_UNSTABLE_EIGENVALUE, message='Potentially unstable linear term detected'))
    return errors


def _extract_tokens(expr: str) -> set[str]:
    import re
    return set(re.findall(r'[A-Za-z_][A-Za-z0-9_]*', expr))


def _infer_unit_from_lhs(expr: str) -> str | None:
    if 'd(' in expr:
        return 'rate'
    if expr.strip().startswith('0'):
        return 'balance'
    return None


def _infer_unit_from_rhs(expr: str) -> str | None:
    if any(tok in expr for tok in ('omega', 'Pm', 'Pe', 'D', 'H', 'delta')):
        return 'rate' if 'omega_b' in expr or '/ (2*H)' in expr else 'balance'
    return None


def _has_unstable_linear_term(text: str) -> bool:
    suspicious = ('+ 100*', '- (-', 'exp(+', 'unstable')
    return any(flag in text for flag in suspicious)
