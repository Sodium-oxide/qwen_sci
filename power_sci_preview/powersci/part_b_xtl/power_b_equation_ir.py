from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional, Sequence

EquationKind = Literal['ode', 'algebraic', 'residual']


@dataclass(frozen=True)
class VariableRef:
    name: str
    alias: str | None = None
    unit: str | None = None
    coordinate: str | None = None
    reference_mode: str | None = None
    nominal_value: float | int | None = None


@dataclass(frozen=True)
class ParameterRef:
    name: str
    value: float | int | str | None = None
    unit: str | None = None


@dataclass(frozen=True)
class EquationNode:
    kind: EquationKind
    lhs: str
    rhs: str
    unit: str | None = None
    expression: str | None = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    equation_id: str | None = None


@dataclass(frozen=True)
class EquationIR:
    model_name: str
    variables: List[VariableRef]
    parameters: List[ParameterRef]
    equations: List[EquationNode]
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CandidateModel:
    candidate_id: str
    model_name: str
    equations: Sequence[EquationNode]
    variables: Sequence[VariableRef] = ()
    parameters: Sequence[ParameterRef] = ()
    source: str | None = None
    fit_metadata: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ValidationError:
    code: str
    message: str
    target: str | None = None
    details: Dict[str, Any] = field(default_factory=dict)
    severity: str = 'ERROR'
    field_path: str = ''
    recoverable: bool = False
    origin_module: str = 'M12'
    diagnostics: List[Dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class ValidationReport:
    model_name: str
    passed: bool
    stage: str
    errors: List[ValidationError] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    metrics: Dict[str, float] = field(default_factory=dict)
    stage_checks: List[Dict[str, Any]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def with_error(self, error: ValidationError) -> 'ValidationReport':
        return ValidationReport(
            model_name=self.model_name,
            passed=False,
            stage=self.stage,
            errors=[*self.errors, error],
            warnings=list(self.warnings),
            metrics=dict(self.metrics),
            stage_checks=list(self.stage_checks),
            metadata=dict(self.metadata),
        )
