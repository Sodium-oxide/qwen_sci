"""A small, non-executable mathematical intermediate representation (MathIR)."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from typing import Any


MATHIR_SCHEMA_VERSION = "mathir_v1"
SUPPORTED_MATHIR_SYSTEMS = frozenset(
    {"ODE_IVP", "LINEAR_OPTIMIZATION", "MONTE_CARLO", "DIFFUSION_REACTION_1D"}
)
_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,63}")
_BINARY_OPERATORS = frozenset({"add", "sub", "mul", "div", "pow", "min", "max"})
_COMPARISON_OPERATORS = frozenset({"lt", "le", "gt", "ge", "eq", "ne"})
_UNARY_OPERATORS = frozenset({"neg", "abs", "exp", "log", "sin", "cos"})
_TERNARY_OPERATORS = frozenset({"conditional", "if_else"})


class MathIRValidationError(ValueError):
    """Raised when a numerical plan contains unsupported mathematical syntax."""


class MathIREvaluationError(ValueError):
    """Raised when a validated mathematical expression cannot be evaluated."""


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _text(value: object) -> str:
    return str(value or "").strip()


def _number(value: object, *, field: str) -> float:
    if isinstance(value, bool):
        raise MathIRValidationError(f"{field} must be numeric")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise MathIRValidationError(f"{field} must be numeric") from exc
    if not math.isfinite(result):
        raise MathIRValidationError(f"{field} must be finite")
    return result


def _identifier(value: object, *, field: str) -> str:
    text = _text(value)
    if not _IDENTIFIER.fullmatch(text):
        raise MathIRValidationError(f"{field} must be a safe identifier")
    return text


def _number_list(value: object, *, field: str, count: int | None = None) -> list[float]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise MathIRValidationError(f"{field} must be a list")
    if count is not None and len(value) != count:
        raise MathIRValidationError(f"{field} must contain {count} entries")
    return [_number(item, field=f"{field}[{index}]") for index, item in enumerate(value)]


def validate_expression(value: object, *, allowed_symbols: set[str]) -> dict[str, Any]:
    """Validate a closed expression tree with no dynamic calls or source text."""

    payload = _mapping(value)
    if not payload:
        raise MathIRValidationError("expression must be an object")
    operator = _text(payload.get("op"))
    if operator == "constant":
        return {"op": operator, "value": _number(payload.get("value"), field="constant.value")}
    if operator == "variable":
        name = _identifier(payload.get("name"), field="variable.name")
        if name not in allowed_symbols:
            raise MathIRValidationError(f"variable {name} is not declared")
        return {"op": operator, "name": name}
    raw_args = payload.get("args")
    if not isinstance(raw_args, Sequence) or isinstance(raw_args, (str, bytes, bytearray)):
        raise MathIRValidationError(f"{operator or 'expression'}.args must be a list")
    if operator in _BINARY_OPERATORS | _COMPARISON_OPERATORS and len(raw_args) != 2:
        raise MathIRValidationError(f"{operator}.args must contain two expressions")
    if operator in _UNARY_OPERATORS and len(raw_args) != 1:
        raise MathIRValidationError(f"{operator}.args must contain one expression")
    if operator in _TERNARY_OPERATORS and len(raw_args) != 3:
        raise MathIRValidationError(f"{operator}.args must contain condition, true, and false expressions")
    if operator not in _BINARY_OPERATORS | _COMPARISON_OPERATORS | _UNARY_OPERATORS | _TERNARY_OPERATORS:
        raise MathIRValidationError(f"unsupported MathIR operator: {operator or '<missing>'}")
    return {
        "op": operator,
        "args": [validate_expression(item, allowed_symbols=allowed_symbols) for item in raw_args],
    }


def evaluate_expression(expression: Mapping[str, object], environment: Mapping[str, float]) -> float:
    """Evaluate only a previously validated MathIR expression tree."""

    operator = _text(expression.get("op"))
    if operator == "constant":
        return _number(expression.get("value"), field="constant.value")
    if operator == "variable":
        name = _text(expression.get("name"))
        if name not in environment:
            raise MathIREvaluationError(f"MathIR variable {name} has no runtime value")
        value = float(environment[name])
        if not math.isfinite(value):
            raise MathIREvaluationError(f"MathIR variable {name} is not finite")
        return value
    args = expression.get("args")
    if not isinstance(args, Sequence):
        raise MathIREvaluationError(f"MathIR {operator} has no arguments")
    if operator in _TERNARY_OPERATORS:
        condition = evaluate_expression(_mapping(args[0]), environment)
        selected = args[1] if condition != 0.0 else args[2]
        return evaluate_expression(_mapping(selected), environment)
    values = [evaluate_expression(_mapping(item), environment) for item in args]
    try:
        if operator == "add":
            result = values[0] + values[1]
        elif operator == "sub":
            result = values[0] - values[1]
        elif operator == "mul":
            result = values[0] * values[1]
        elif operator == "div":
            result = values[0] / values[1]
        elif operator == "pow":
            result = values[0] ** values[1]
        elif operator == "min":
            result = min(values[0], values[1])
        elif operator == "max":
            result = max(values[0], values[1])
        elif operator == "lt":
            result = float(values[0] < values[1])
        elif operator == "le":
            result = float(values[0] <= values[1])
        elif operator == "gt":
            result = float(values[0] > values[1])
        elif operator == "ge":
            result = float(values[0] >= values[1])
        elif operator == "eq":
            result = float(values[0] == values[1])
        elif operator == "ne":
            result = float(values[0] != values[1])
        elif operator == "neg":
            result = -values[0]
        elif operator == "abs":
            result = abs(values[0])
        elif operator == "exp":
            result = math.exp(values[0])
        elif operator == "log":
            result = math.log(values[0])
        elif operator == "sin":
            result = math.sin(values[0])
        elif operator == "cos":
            result = math.cos(values[0])
        else:
            raise MathIREvaluationError(f"unsupported MathIR operator: {operator}")
    except (ArithmeticError, ValueError, OverflowError, ZeroDivisionError) as exc:
        raise MathIREvaluationError(f"MathIR {operator} evaluation failed") from exc
    if not math.isfinite(result):
        raise MathIREvaluationError(f"MathIR {operator} produced a non-finite result")
    return float(result)


def _validate_parameters(value: object) -> dict[str, float]:
    payload = _mapping(value)
    parameters: dict[str, float] = {}
    for name, raw_value in payload.items():
        identifier = _identifier(name, field="parameters key")
        parameters[identifier] = _number(raw_value, field=f"parameters.{identifier}")
    return parameters


def _validate_ode(payload: Mapping[str, object]) -> dict[str, Any]:
    raw_states = payload.get("states")
    if not isinstance(raw_states, Sequence) or isinstance(raw_states, (str, bytes, bytearray)):
        raise MathIRValidationError("states must be a list")
    states: list[dict[str, Any]] = []
    for index, raw_state in enumerate(raw_states):
        state = _mapping(raw_state)
        states.append(
            {
                "id": _identifier(state.get("id"), field=f"states[{index}].id"),
                "initial": _number(state.get("initial"), field=f"states[{index}].initial"),
            }
        )
    if not states:
        raise MathIRValidationError("states must not be empty")
    state_ids = [state["id"] for state in states]
    if len(state_ids) != len(set(state_ids)):
        raise MathIRValidationError("state identifiers must be unique")
    parameters = _validate_parameters(payload.get("parameters", {}))
    allowed = {"t", *state_ids, *parameters}
    derivatives_payload = _mapping(payload.get("derivatives"))
    if set(derivatives_payload) != set(state_ids):
        raise MathIRValidationError("derivatives must define exactly one expression per state")
    derivatives = {
        state_id: validate_expression(derivatives_payload[state_id], allowed_symbols=allowed)
        for state_id in state_ids
    }
    time_span = _number_list(payload.get("time_span"), field="time_span", count=2)
    if time_span[1] <= time_span[0]:
        raise MathIRValidationError("time_span must have increasing bounds")
    options = _mapping(payload.get("solver_options"))
    max_step = _number(options.get("max_step", (time_span[1] - time_span[0]) / 100), field="solver_options.max_step")
    if max_step <= 0:
        raise MathIRValidationError("solver_options.max_step must be positive")
    return {
        "schema_version": MATHIR_SCHEMA_VERSION,
        "system_type": "ODE_IVP",
        "states": states,
        "parameters": parameters,
        "derivatives": derivatives,
        "time_span": time_span,
        "solver_options": {"max_step": max_step},
    }


def _validate_linear_optimization(payload: Mapping[str, object]) -> dict[str, Any]:
    raw_variables = payload.get("variables")
    if not isinstance(raw_variables, Sequence) or isinstance(raw_variables, (str, bytes, bytearray)):
        raise MathIRValidationError("variables must be a list")
    variables: list[dict[str, float | str]] = []
    for index, raw_variable in enumerate(raw_variables):
        variable = _mapping(raw_variable)
        lower = _number(variable.get("lower", 0), field=f"variables[{index}].lower")
        upper = _number(variable.get("upper"), field=f"variables[{index}].upper")
        if upper < lower:
            raise MathIRValidationError(f"variables[{index}] upper must be at least lower")
        variables.append(
            {
                "id": _identifier(variable.get("id"), field=f"variables[{index}].id"),
                "lower": lower,
                "upper": upper,
                "objective_coefficient": _number(
                    variable.get("objective_coefficient"),
                    field=f"variables[{index}].objective_coefficient",
                ),
            }
        )
    variable_ids = [str(item["id"]) for item in variables]
    if not variables or len(variable_ids) != len(set(variable_ids)):
        raise MathIRValidationError("optimization variables must be non-empty and unique")
    raw_constraints = payload.get("constraints", [])
    if not isinstance(raw_constraints, Sequence) or isinstance(raw_constraints, (str, bytes, bytearray)):
        raise MathIRValidationError("constraints must be a list")
    constraints: list[dict[str, Any]] = []
    for index, raw_constraint in enumerate(raw_constraints):
        constraint = _mapping(raw_constraint)
        sense = _text(constraint.get("sense"))
        if sense not in {"<=", ">=", "=="}:
            raise MathIRValidationError(f"constraints[{index}].sense is unsupported")
        coefficients = _mapping(constraint.get("coefficients"))
        if set(coefficients) - set(variable_ids):
            raise MathIRValidationError(f"constraints[{index}] references an undeclared variable")
        constraints.append(
            {
                "coefficients": {
                    name: _number(raw_value, field=f"constraints[{index}].coefficients.{name}")
                    for name, raw_value in coefficients.items()
                },
                "sense": sense,
                "rhs": _number(constraint.get("rhs"), field=f"constraints[{index}].rhs"),
            }
        )
    objective_sense = _text(payload.get("objective_sense", "minimize"))
    if objective_sense not in {"minimize", "maximize"}:
        raise MathIRValidationError("objective_sense must be minimize or maximize")
    return {
        "schema_version": MATHIR_SCHEMA_VERSION,
        "system_type": "LINEAR_OPTIMIZATION",
        "variables": variables,
        "constraints": constraints,
        "objective_sense": objective_sense,
    }


def _validate_monte_carlo(payload: Mapping[str, object]) -> dict[str, Any]:
    samples_raw = payload.get("samples")
    if isinstance(samples_raw, bool):
        raise MathIRValidationError("samples must be an integer")
    try:
        samples = int(samples_raw)
    except (TypeError, ValueError) as exc:
        raise MathIRValidationError("samples must be an integer") from exc
    if samples < 1 or samples > 100_000:
        raise MathIRValidationError("samples must be between 1 and 100000")
    raw_variables = payload.get("random_variables")
    if not isinstance(raw_variables, Sequence) or isinstance(raw_variables, (str, bytes, bytearray)):
        raise MathIRValidationError("random_variables must be a list")
    random_variables: list[dict[str, Any]] = []
    names: list[str] = []
    for index, raw_variable in enumerate(raw_variables):
        variable = _mapping(raw_variable)
        name = _identifier(variable.get("id"), field=f"random_variables[{index}].id")
        distribution = _text(variable.get("distribution"))
        parameters = _mapping(variable.get("parameters"))
        if distribution == "uniform":
            low = _number(parameters.get("low"), field=f"random_variables[{index}].parameters.low")
            high = _number(parameters.get("high"), field=f"random_variables[{index}].parameters.high")
            if high <= low:
                raise MathIRValidationError(f"random_variables[{index}] uniform high must exceed low")
            normalized_parameters = {"low": low, "high": high}
        elif distribution == "normal":
            mean = _number(parameters.get("mean"), field=f"random_variables[{index}].parameters.mean")
            stddev = _number(parameters.get("stddev"), field=f"random_variables[{index}].parameters.stddev")
            if stddev <= 0:
                raise MathIRValidationError(f"random_variables[{index}] normal stddev must be positive")
            normalized_parameters = {"mean": mean, "stddev": stddev}
        else:
            raise MathIRValidationError(f"random_variables[{index}].distribution is unsupported")
        names.append(name)
        random_variables.append({"id": name, "distribution": distribution, "parameters": normalized_parameters})
    if not random_variables or len(names) != len(set(names)):
        raise MathIRValidationError("random_variables must be non-empty and unique")
    seed_raw = payload.get("seed", 0)
    if isinstance(seed_raw, bool):
        raise MathIRValidationError("seed must be an integer")
    try:
        seed = int(seed_raw)
    except (TypeError, ValueError) as exc:
        raise MathIRValidationError("seed must be an integer") from exc
    return {
        "schema_version": MATHIR_SCHEMA_VERSION,
        "system_type": "MONTE_CARLO",
        "samples": samples,
        "seed": seed,
        "random_variables": random_variables,
        "observable": validate_expression(payload.get("observable"), allowed_symbols=set(names)),
    }


def _validate_diffusion_reaction_1d(payload: Mapping[str, object]) -> dict[str, Any]:
    """Validate a bounded, explicit one-dimensional diffusion--reaction model.

    The IR deliberately accepts sampled initial fields rather than arbitrary
    source expressions.  A model compiler may discretize an analytic initial
    condition before it reaches this boundary, but the execution layer only
    receives finite values and a restricted AST for the governing terms.
    """

    state = _mapping(payload.get("state"))
    state_id = _identifier(state.get("id"), field="state.id")
    spatial_domain = _number_list(payload.get("spatial_domain"), field="spatial_domain", count=2)
    if spatial_domain[1] <= spatial_domain[0]:
        raise MathIRValidationError("spatial_domain must have increasing bounds")
    grid_raw = payload.get("grid_points")
    if isinstance(grid_raw, bool):
        raise MathIRValidationError("grid_points must be an integer")
    try:
        grid_points = int(grid_raw)
    except (TypeError, ValueError) as exc:
        raise MathIRValidationError("grid_points must be an integer") from exc
    if grid_points < 3 or grid_points > 4_096:
        raise MathIRValidationError("grid_points must be between 3 and 4096")
    initial_values = _number_list(
        payload.get("initial_values"),
        field="initial_values",
        count=grid_points,
    )
    parameters = _validate_parameters(payload.get("parameters", {}))
    time_span = _number_list(payload.get("time_span"), field="time_span", count=2)
    if time_span[1] <= time_span[0]:
        raise MathIRValidationError("time_span must have increasing bounds")
    options = _mapping(payload.get("solver_options"))
    time_step = _number(
        options.get("time_step", (time_span[1] - time_span[0]) / 100),
        field="solver_options.time_step",
    )
    if time_step <= 0:
        raise MathIRValidationError("solver_options.time_step must be positive")
    term_symbols = {"t", "x", *parameters}
    diffusion_coefficient = validate_expression(
        payload.get("diffusion_coefficient"),
        allowed_symbols=term_symbols,
    )
    reaction = validate_expression(
        payload.get("reaction"),
        allowed_symbols={*term_symbols, state_id},
    )
    boundaries = _mapping(payload.get("boundary_conditions"))
    normalized_boundaries: dict[str, dict[str, Any]] = {}
    for side in ("left", "right"):
        boundary = _mapping(boundaries.get(side))
        boundary_type = _text(boundary.get("type"))
        if boundary_type == "NEUMANN_ZERO":
            normalized_boundaries[side] = {"type": boundary_type}
        elif boundary_type == "DIRICHLET":
            normalized_boundaries[side] = {
                "type": boundary_type,
                "value": validate_expression(boundary.get("value"), allowed_symbols=term_symbols),
            }
        else:
            raise MathIRValidationError(
                f"boundary_conditions.{side}.type must be DIRICHLET or NEUMANN_ZERO"
            )
    return {
        "schema_version": MATHIR_SCHEMA_VERSION,
        "system_type": "DIFFUSION_REACTION_1D",
        "state": {"id": state_id},
        "spatial_domain": spatial_domain,
        "grid_points": grid_points,
        "initial_values": initial_values,
        "parameters": parameters,
        "time_span": time_span,
        "solver_options": {"time_step": time_step},
        "diffusion_coefficient": diffusion_coefficient,
        "reaction": reaction,
        "boundary_conditions": normalized_boundaries,
    }


def validate_mathir_document(value: object) -> dict[str, Any]:
    """Validate and normalize a model's solver-ready mathematical representation."""

    payload = _mapping(value)
    if _text(payload.get("schema_version")) != MATHIR_SCHEMA_VERSION:
        raise MathIRValidationError(
            f"unsupported MathIR schema: expected {MATHIR_SCHEMA_VERSION}, got {_text(payload.get('schema_version')) or '<missing>'}"
        )
    system_type = _text(payload.get("system_type"))
    if system_type == "ODE_IVP":
        return _validate_ode(payload)
    if system_type == "LINEAR_OPTIMIZATION":
        return _validate_linear_optimization(payload)
    if system_type == "MONTE_CARLO":
        return _validate_monte_carlo(payload)
    if system_type == "DIFFUSION_REACTION_1D":
        return _validate_diffusion_reaction_1d(payload)
    raise MathIRValidationError(f"unsupported MathIR system type: {system_type or '<missing>'}")


__all__ = [
    "MATHIR_SCHEMA_VERSION",
    "SUPPORTED_MATHIR_SYSTEMS",
    "MathIREvaluationError",
    "MathIRValidationError",
    "evaluate_expression",
    "validate_expression",
    "validate_mathir_document",
]
