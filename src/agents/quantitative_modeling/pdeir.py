"""Safe, family-specific PDE intermediate representation."""

from __future__ import annotations

import math
import re
import copy
from collections.abc import Mapping, Sequence
from typing import Any

from src.agents.quantitative_modeling.pde_capability_registry import PDE_CAPABILITIES


PDEIR_SCHEMA_VERSION = "pdeir_v1"
SUPPORTED_PDE_SYSTEMS = frozenset(PDE_CAPABILITIES)
_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,63}")
_BINARY = frozenset({"add", "sub", "mul", "div", "pow", "min", "max"})
_UNARY = frozenset({"neg", "abs", "exp", "log", "sin", "cos"})
_COMPARISONS = frozenset({"lt", "le", "gt", "ge", "eq", "ne"})
_TERNARY = frozenset({"conditional", "if_else"})
_ANALYTIC_PROFILES = frozenset({"UNIFORM", "GAUSSIAN", "ANALYTIC_EXPRESSION"})


class PDEIRValidationError(ValueError):
    """Raised when a PDE document is not a bounded declarative model."""


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _text(value: object) -> str:
    return str(value or "").strip()


def _number(value: object, *, field: str) -> float:
    if isinstance(value, bool):
        raise PDEIRValidationError(f"{field} must be numeric")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise PDEIRValidationError(f"{field} must be numeric") from exc
    if not math.isfinite(result):
        raise PDEIRValidationError(f"{field} must be finite")
    return result


def _identifier(value: object, *, field: str) -> str:
    identifier = _text(value)
    if not _IDENTIFIER.fullmatch(identifier):
        raise PDEIRValidationError(f"{field} must be a safe identifier")
    return identifier


def _number_list(value: object, *, field: str, count: int | None = None) -> list[float]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise PDEIRValidationError(f"{field} must be a list")
    if count is not None and len(value) != count:
        raise PDEIRValidationError(f"{field} must contain {count} entries")
    return [_number(item, field=f"{field}[{index}]") for index, item in enumerate(value)]


def _integer(value: object, *, field: str) -> int:
    if isinstance(value, bool):
        raise PDEIRValidationError(f"{field} must be an integer")
    try:
        numeric = float(value)
        result = int(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise PDEIRValidationError(f"{field} must be an integer") from exc
    if not math.isfinite(numeric) or numeric != result:
        raise PDEIRValidationError(f"{field} must be an integer")
    return result


def _expression_value(value: object) -> object:
    if isinstance(value, Mapping):
        return dict(value)
    return {"op": "constant", "value": value}


def _normalize_expression_aliases(value: object) -> object:
    if not isinstance(value, Mapping):
        return value
    payload = dict(value)
    if _text(payload.get("op")) == "field" and "name" not in payload and "field_id" in payload:
        payload["name"] = payload["field_id"]
    if "args" in payload and isinstance(payload["args"], Sequence) and not isinstance(
        payload["args"], (str, bytes, bytearray)
    ):
        payload["args"] = [_normalize_expression_aliases(item) for item in payload["args"]]
    return payload


def _normalize_external_pde_shape(value: Mapping[str, object]) -> dict[str, Any]:
    """Translate the documented PDE contract aliases into the v1 canonical shape."""

    payload = dict(value)
    if not _text(payload.get("system_type")) and _text(payload.get("pde_family")):
        payload["system_type"] = _text(payload.get("pde_family"))

    spatial_domain = _mapping(payload.get("spatial_domain"))
    axes = spatial_domain.get("axes")
    if isinstance(axes, Sequence) and not isinstance(axes, (str, bytes, bytearray)):
        converted: dict[str, list[float]] = {}
        for axis in axes:
            axis_payload = _mapping(axis)
            symbol = _text(axis_payload.get("symbol"))
            if not symbol:
                continue
            coordinate_symbol = "x" if symbol == "r" else symbol
            converted[coordinate_symbol] = [axis_payload.get("lower"), axis_payload.get("upper")]
        if converted:
            payload["spatial_domain"] = converted

    fields = payload.get("fields")
    if isinstance(fields, Sequence) and not isinstance(fields, (str, bytes, bytearray)):
        converted_fields: list[dict[str, Any]] = []
        for field_payload in fields:
            field = _mapping(field_payload)
            if "id" not in field and "field_id" in field:
                field["id"] = field["field_id"]
            converted_fields.append(field)
        payload["fields"] = converted_fields

    discretization = _mapping(payload.get("discretization"))
    grid = _mapping(payload.get("grid"))
    if not grid:
        grid_points = discretization.get("grid_points", payload.get("grid_points"))
        if isinstance(grid_points, Sequence) and not isinstance(grid_points, (str, bytes, bytearray)):
            if len(grid_points) in (2, 3):
                grid = {name: grid_points[index] for index, name in enumerate(("nx", "ny", "nz")[:len(grid_points)])}
        elif grid_points is not None:
            grid = {"nx": grid_points}
    if grid:
        shape = grid.get("shape", grid.get("sizes"))
        if isinstance(shape, Sequence) and not isinstance(shape, (str, bytes, bytearray)) and len(shape) in (1, 2, 3):
            grid = {
                **grid,
                **{name: shape[index] for index, name in enumerate(("nx", "ny", "nz")[:len(shape)])},
            }
        payload["grid"] = grid

    solver_options = _mapping(payload.get("solver_options"))
    if discretization:
        solver_options = {
            **solver_options,
            **({"time_integrator": discretization["time_integrator"]} if "time_integrator" in discretization else {}),
            **({"time_step": discretization["time_step"]} if "time_step" in discretization else {}),
        }
        payload["discretization"] = dict(discretization)
    if solver_options:
        payload["solver_options"] = solver_options

    equation_terms = _mapping(payload.get("equation_terms"))
    for name in (
        "diffusion_coefficient",
        "advection_velocity",
        "reaction",
        "reaction_coefficient",
        "source",
        "wave_speed",
    ):
        if name not in payload and name in equation_terms:
            payload[name] = equation_terms[name]
    for name in (
        "diffusion_coefficient",
        "advection_velocity",
        "reaction",
        "reaction_coefficient",
        "source",
        "wave_speed",
    ):
        if name in payload:
            payload[name] = _normalize_expression_aliases(payload[name])

    boundaries = _mapping(payload.get("boundary_conditions"))
    if boundaries:
        normalized_boundaries: dict[str, Any] = {}
        for side, boundary_value in boundaries.items():
            boundary = _mapping(boundary_value)
            if "value" in boundary:
                boundary["value"] = _expression_value(_normalize_expression_aliases(boundary["value"]))
            normalized_boundaries[str(side)] = boundary
        payload["boundary_conditions"] = normalized_boundaries

    for name in ("initial_condition", "initial_velocity"):
        initial = _mapping(payload.get(name))
        if initial:
            payload[name] = dict(initial)

    return payload


def validate_pde_expression(
    value: object,
    *,
    allowed_symbols: set[str],
    allowed_fields: set[str],
) -> dict[str, Any]:
    """Validate an expression tree with coordinates and local field leaves."""

    payload = _mapping(value)
    if not payload:
        raise PDEIRValidationError("PDE expression must be an object")
    operator = _text(payload.get("op"))
    if operator == "constant":
        return {"op": operator, "value": _number(payload.get("value"), field="constant.value")}
    if operator == "variable":
        name = _identifier(payload.get("name"), field="variable.name")
        if name not in allowed_symbols:
            raise PDEIRValidationError(f"PDE variable {name} is not declared")
        return {"op": operator, "name": name}
    if operator == "field":
        name = _identifier(payload.get("name"), field="field.name")
        if name not in allowed_fields:
            raise PDEIRValidationError(f"PDE field {name} is not declared")
        return {"op": operator, "name": name}
    if operator in _BINARY:
        raw_args = payload.get("args")
        if not isinstance(raw_args, Sequence) or isinstance(raw_args, (str, bytes, bytearray)) or len(raw_args) != 2:
            raise PDEIRValidationError(f"PDE operator {operator} requires two arguments")
        return {
            "op": operator,
            "args": [
                validate_pde_expression(item, allowed_symbols=allowed_symbols, allowed_fields=allowed_fields)
                for item in raw_args
            ],
        }
    if operator in _UNARY:
        raw_args = payload.get("args")
        if not isinstance(raw_args, Sequence) or isinstance(raw_args, (str, bytes, bytearray)) or len(raw_args) != 1:
            raise PDEIRValidationError(f"PDE operator {operator} requires one argument")
        return {
            "op": operator,
            "args": [
                validate_pde_expression(raw_args[0], allowed_symbols=allowed_symbols, allowed_fields=allowed_fields)
            ],
        }
    if operator in _COMPARISONS:
        raw_args = payload.get("args")
        if not isinstance(raw_args, Sequence) or isinstance(raw_args, (str, bytes, bytearray)) or len(raw_args) != 2:
            raise PDEIRValidationError(f"PDE operator {operator} requires two arguments")
        return {
            "op": operator,
            "args": [
                validate_pde_expression(item, allowed_symbols=allowed_symbols, allowed_fields=allowed_fields)
                for item in raw_args
            ],
        }
    if operator in _TERNARY:
        raw_args = payload.get("args")
        if not isinstance(raw_args, Sequence) or isinstance(raw_args, (str, bytes, bytearray)) or len(raw_args) != 3:
            raise PDEIRValidationError(f"PDE operator {operator} requires three arguments")
        return {
            "op": operator,
            "args": [
                validate_pde_expression(item, allowed_symbols=allowed_symbols, allowed_fields=allowed_fields)
                for item in raw_args
            ],
        }
    raise PDEIRValidationError(f"unsupported PDE expression operator: {operator or '<missing>'}")


def _coordinate_names(dimension: int) -> tuple[str, ...]:
    return ("x",) if dimension == 1 else ("x", "y") if dimension == 2 else ("x", "y", "z")


def _normalize_coordinate_parameters(
    value: object,
    *,
    field: str,
    dimension: int,
    positive: bool = False,
) -> dict[str, float]:
    names = _coordinate_names(dimension)
    if dimension == 1 and not isinstance(value, Mapping):
        raw_values: dict[str, object] = {"x": value}
    else:
        payload = _mapping(value)
        if set(payload) != set(names):
            raise PDEIRValidationError(f"{field} must contain exactly {', '.join(names)}")
        raw_values = payload
    normalized = {
        name: _number(raw_values[name], field=f"{field}.{name}")
        for name in names
    }
    if positive and any(item <= 0 for item in normalized.values()):
        raise PDEIRValidationError(f"{field} values must be positive")
    return normalized


def _validate_initial_definition(
    value: object,
    *,
    field: str,
    dimension: int,
    allowed_symbols: set[str],
    expected_values: int,
) -> dict[str, Any]:
    payload = _mapping(value)
    initial_type = _text(payload.get("type")) or "SAMPLED_VALUES"
    if initial_type == "SAMPLED_VALUES":
        values = _number_list(payload.get("values"), field=f"{field}.values", count=expected_values)
        return {"type": initial_type, "values": values}
    if initial_type != "ANALYTIC_PROFILE":
        raise PDEIRValidationError(
            f"{field}.type must be SAMPLED_VALUES or ANALYTIC_PROFILE"
        )
    profile = _text(payload.get("profile")).upper()
    if profile not in _ANALYTIC_PROFILES:
        raise PDEIRValidationError(f"{field}.profile is unsupported")
    if profile == "UNIFORM":
        return {
            "type": "ANALYTIC_PROFILE",
            "profile": profile,
            "value": _number(payload.get("value"), field=f"{field}.value"),
        }
    if profile == "GAUSSIAN":
        return {
            "type": "ANALYTIC_PROFILE",
            "profile": profile,
            "amplitude": _number(payload.get("amplitude", 1.0), field=f"{field}.amplitude"),
            "offset": _number(payload.get("offset", 0.0), field=f"{field}.offset"),
            "center": _normalize_coordinate_parameters(
                payload.get("center"), field=f"{field}.center", dimension=dimension
            ),
            "sigma": _normalize_coordinate_parameters(
                payload.get("sigma"), field=f"{field}.sigma", dimension=dimension, positive=True
            ),
        }
    expression = validate_pde_expression(
        payload.get("expression"),
        allowed_symbols=allowed_symbols,
        allowed_fields=set(),
    )
    return {
        "type": "ANALYTIC_PROFILE",
        "profile": profile,
        "expression": expression,
    }


def _grid_coordinates(document: Mapping[str, object]) -> list[dict[str, float]]:
    grid = _mapping(document["grid"])
    domain = _mapping(document["spatial_domain"])
    dimensions = _coordinate_names(len([name for name in ("x", "y", "z") if name in grid or name in domain]))
    sizes = {name: int(grid[f"n{name}"]) for name in dimensions}
    coordinates: list[dict[str, float]] = []
    axes: dict[str, list[float]] = {}
    for name in dimensions:
        lower, upper = (float(item) for item in domain[name])
        count = sizes[name]
        spacing = (upper - lower) / (count - 1)
        axes[name] = [lower + index * spacing for index in range(count)]
    if dimensions == ("x",):
        return [{"x": value} for value in axes["x"]]
    if dimensions == ("x", "y"):
        return [{"x": x_value, "y": y_value} for y_value in axes["y"] for x_value in axes["x"]]
    return [
        {"x": x_value, "y": y_value, "z": z_value}
        for z_value in axes["z"]
        for y_value in axes["y"]
        for x_value in axes["x"]
    ]


def _materialize_initial_definition(
    definition: Mapping[str, object],
    *,
    coordinates: Sequence[Mapping[str, float]],
    parameters: Mapping[str, float],
    time_value: float,
    field: str,
) -> list[float]:
    if _text(definition.get("type")) == "SAMPLED_VALUES":
        return [float(item) for item in definition["values"]]
    profile = _text(definition.get("profile")).upper()
    values: list[float] = []
    for coordinate in coordinates:
        environment = {"t": time_value, **parameters, **dict(coordinate)}
        if profile == "UNIFORM":
            value = _number(definition.get("value"), field=f"{field}.value")
        elif profile == "GAUSSIAN":
            center = _mapping(definition.get("center"))
            sigma = _mapping(definition.get("sigma"))
            exponent = sum(
                ((float(coordinate[name]) - float(center[name])) / float(sigma[name])) ** 2
                for name in coordinate
            )
            value = float(definition.get("offset", 0.0)) + float(definition.get("amplitude", 1.0)) * math.exp(-0.5 * exponent)
        elif profile == "ANALYTIC_EXPRESSION":
            value = evaluate_pde_expression(_mapping(definition.get("expression")), environment)
        else:
            raise PDEIRValidationError(f"{field}.profile is unsupported")
        if not math.isfinite(float(value)):
            raise PDEIRValidationError(f"{field} produced a non-finite value")
        values.append(float(value))
    return values


def evaluate_pde_expression(value: Mapping[str, object], environment: Mapping[str, float]) -> float:
    """Evaluate a previously validated PDE expression without dynamic calls."""

    operator = _text(value.get("op"))
    if operator == "constant":
        return float(value["value"])
    if operator == "variable":
        return float(environment[str(value["name"])])
    if operator == "field":
        return float(environment[f"field:{value['name']}"])
    args = [_mapping(item) for item in value.get("args", [])]
    if operator in _BINARY:
        left = evaluate_pde_expression(args[0], environment)
        right = evaluate_pde_expression(args[1], environment)
        if operator == "add":
            return left + right
        if operator == "sub":
            return left - right
        if operator == "mul":
            return left * right
        if operator == "div":
            if right == 0:
                raise PDEIRValidationError("PDE expression division by zero")
            return left / right
        if operator == "pow":
            return left**right
        if operator == "min":
            return min(left, right)
        return max(left, right)
    if operator in _UNARY:
        operand = evaluate_pde_expression(args[0], environment)
        if operator == "neg":
            return -operand
        if operator == "abs":
            return abs(operand)
        if operator == "exp":
            return math.exp(operand)
        if operator == "log":
            if operand <= 0:
                raise PDEIRValidationError("PDE expression log domain error")
            return math.log(operand)
        if operator == "sin":
            return math.sin(operand)
        return math.cos(operand)
    if operator in _COMPARISONS:
        left = evaluate_pde_expression(args[0], environment)
        right = evaluate_pde_expression(args[1], environment)
        values = {
            "lt": left < right,
            "le": left <= right,
            "gt": left > right,
            "ge": left >= right,
            "eq": left == right,
            "ne": left != right,
        }
        return 1.0 if values[operator] else 0.0
    if operator in _TERNARY:
        condition = evaluate_pde_expression(args[0], environment)
        return evaluate_pde_expression(args[1] if condition else args[2], environment)
    raise PDEIRValidationError(f"unsupported PDE expression operator: {operator}")


def _validate_field(payload: object, *, field: str) -> dict[str, Any]:
    value = _mapping(payload)
    identifier = _identifier(value.get("id"), field=f"{field}.id")
    result = {"id": identifier, "symbol": _text(value.get("symbol")) or identifier}
    result["unit"] = _text(value.get("unit"))
    bounds = _mapping(value.get("bounds"))
    normalized_bounds: dict[str, float] = {}
    if "lower" in bounds:
        normalized_bounds["lower"] = _number(bounds["lower"], field=f"{field}.bounds.lower")
    if "upper" in bounds:
        normalized_bounds["upper"] = _number(bounds["upper"], field=f"{field}.bounds.upper")
    if "lower" in normalized_bounds and "upper" in normalized_bounds:
        if normalized_bounds["lower"] > normalized_bounds["upper"]:
            raise PDEIRValidationError(f"{field}.bounds.lower must not exceed upper")
    result["bounds"] = normalized_bounds
    return result


def _validate_boundary(
    value: object,
    *,
    field: str,
    allowed_symbols: set[str],
    allowed_fields: set[str],
    allowed_types: set[str] | None = None,
) -> dict[str, Any]:
    payload = _mapping(value)
    boundary_type = _text(payload.get("type"))
    if boundary_type not in {
        "DIRICHLET",
        "NEUMANN_ZERO",
        "NEUMANN",
        "PERIODIC",
        "SPHERICAL_ORIGIN_REGULARITY",
    }:
        raise PDEIRValidationError(f"{field}.type is unsupported")
    if allowed_types is not None and boundary_type not in allowed_types:
        raise PDEIRValidationError(f"{field}.type is unsupported for this PDE family")
    result = {"type": boundary_type}
    if boundary_type in {"DIRICHLET", "NEUMANN"}:
        result["value"] = validate_pde_expression(
            payload.get("value"), allowed_symbols=allowed_symbols, allowed_fields=allowed_fields
        )
    return result


def _validate_common(payload: Mapping[str, object], *, system_type: str) -> dict[str, Any]:
    capability = PDE_CAPABILITIES[system_type]
    fields_raw = payload.get("fields")
    if not isinstance(fields_raw, Sequence) or isinstance(fields_raw, (str, bytes, bytearray)) or len(fields_raw) != 1:
        raise PDEIRValidationError("PDE v1 requires exactly one field")
    fields = [_validate_field(fields_raw[0], field="fields[0]")]
    field_ids = {item["id"] for item in fields}
    parameters_raw = _mapping(payload.get("parameters"))
    parameters = {str(name): _number(value, field=f"parameters.{name}") for name, value in parameters_raw.items()}
    if any(not _IDENTIFIER.fullmatch(name) for name in parameters):
        raise PDEIRValidationError("PDE parameter names must be safe identifiers")
    spatial_domain = _mapping(payload.get("spatial_domain"))
    dimension = int(capability["dimensions"][0])
    declared_dimension = payload.get("spatial_dimension")
    if declared_dimension is not None and _integer(declared_dimension, field="spatial_dimension") != dimension:
        raise PDEIRValidationError("spatial_dimension does not match the registered PDE family")
    if dimension == 1:
        domain = _number_list(spatial_domain.get("x", payload.get("spatial_domain")), field="spatial_domain.x", count=2)
        if domain[1] <= domain[0]:
            raise PDEIRValidationError("spatial_domain.x must be increasing")
        grid_raw = payload.get("grid") or {"nx": payload.get("grid_points")}
        grid = _mapping(grid_raw)
        nx = _integer(grid.get("nx"), field="grid.nx")
        if nx < 3 or nx > 4096:
            raise PDEIRValidationError("grid.nx must be between 3 and 4096")
        spatial = {"x": domain}
        grid_normalized = {"nx": nx}
    elif dimension == 2:
        x_domain = _number_list(spatial_domain.get("x"), field="spatial_domain.x", count=2)
        y_domain = _number_list(spatial_domain.get("y"), field="spatial_domain.y", count=2)
        if x_domain[1] <= x_domain[0] or y_domain[1] <= y_domain[0]:
            raise PDEIRValidationError("two-dimensional spatial domains must be increasing")
        grid = _mapping(payload.get("grid"))
        nx = _integer(grid.get("nx"), field="grid.nx")
        ny = _integer(grid.get("ny"), field="grid.ny")
        if nx < 3 or nx > 1024 or ny < 3 or ny > 1024:
            raise PDEIRValidationError("2D grid dimensions must be between 3 and 1024")
        spatial = {"x": x_domain, "y": y_domain}
        grid_normalized = {"nx": nx, "ny": ny}
    else:
        x_domain = _number_list(spatial_domain.get("x"), field="spatial_domain.x", count=2)
        y_domain = _number_list(spatial_domain.get("y"), field="spatial_domain.y", count=2)
        z_domain = _number_list(spatial_domain.get("z"), field="spatial_domain.z", count=2)
        if any(upper <= lower for lower, upper in (x_domain, y_domain, z_domain)):
            raise PDEIRValidationError("three-dimensional spatial domains must be increasing")
        grid = _mapping(payload.get("grid"))
        nx = _integer(grid.get("nx"), field="grid.nx")
        ny = _integer(grid.get("ny"), field="grid.ny")
        nz = _integer(grid.get("nz"), field="grid.nz")
        if any(size < 3 or size > 128 for size in (nx, ny, nz)):
            raise PDEIRValidationError("3D grid dimensions must be between 3 and 128")
        spatial = {"x": x_domain, "y": y_domain, "z": z_domain}
        grid_normalized = {"nx": nx, "ny": ny, "nz": nz}
    allowed_symbols = {"t", "x", "y", "z", *parameters}
    discretization = _mapping(payload.get("discretization"))
    method = _text(discretization.get("method")) or str(capability["discretizations"][0])
    if method not in set(capability["discretizations"]):
        raise PDEIRValidationError(f"discretization.method is unsupported for {system_type}")
    grid_type = _text(discretization.get("grid_type")) or "UNIFORM"
    if grid_type != "UNIFORM":
        raise PDEIRValidationError("PDE v1 currently supports only uniform grids")
    space_order = _integer(discretization.get("space_order", 2), field="discretization.space_order")
    if space_order not in {1, 2}:
        raise PDEIRValidationError("discretization.space_order must be 1 or 2")
    result: dict[str, Any] = {
        "schema_version": PDEIR_SCHEMA_VERSION,
        "system_type": system_type,
        "spatial_dimension": dimension,
        "spatial_domain": spatial,
        "grid": grid_normalized,
        "fields": fields,
        "parameters": parameters,
        "discretization": {
            "method": method,
            "grid_type": grid_type,
            "space_order": space_order,
        },
    }
    observables = payload.get("observables")
    if observables is not None:
        if not isinstance(observables, Sequence) or isinstance(observables, (str, bytes, bytearray)):
            raise PDEIRValidationError("observables must be a list")
        normalized_observables = [_text(item) for item in observables]
        if any(not item for item in normalized_observables):
            raise PDEIRValidationError("observables cannot contain empty values")
        result["observables"] = list(dict.fromkeys(normalized_observables))
    verification_plan = payload.get("verification_plan")
    if verification_plan is not None:
        raw_verification_plan = _mapping(verification_plan)
        supported_checks = {
            "grid_refinement",
            "time_step_refinement",
            "boundary_residual",
            "conservation_check",
            "manufactured_solution",
            "energy_check",
        }
        unknown_checks = set(raw_verification_plan) - supported_checks
        if unknown_checks:
            raise PDEIRValidationError("verification_plan contains unsupported checks")
        normalized_verification_plan: dict[str, bool] = {}
        for check_name, enabled in raw_verification_plan.items():
            if not isinstance(enabled, bool):
                raise PDEIRValidationError(f"verification_plan.{check_name} must be boolean")
            normalized_verification_plan[str(check_name)] = enabled
        result["verification_plan"] = normalized_verification_plan
    if capability["temporal"]:
        time_span = _number_list(payload.get("time_span"), field="time_span", count=2)
        if time_span[1] <= time_span[0]:
            raise PDEIRValidationError("time_span must be increasing")
        options = _mapping(payload.get("solver_options"))
        time_step = _number(options.get("time_step"), field="solver_options.time_step")
        if time_step <= 0:
            raise PDEIRValidationError("solver_options.time_step must be positive")
        integrator = _text(options.get("time_integrator")) or str(capability["time_integrators"][0])
        if integrator not in set(capability["time_integrators"]):
            raise PDEIRValidationError(f"solver_options.time_integrator is unsupported for {system_type}")
        result["time_span"] = time_span
        result["solver_options"] = {"time_step": time_step, "time_integrator": integrator}
    if capability["temporal"]:
        expected_values = (
            grid_normalized["nx"]
            * grid_normalized.get("ny", 1)
            * grid_normalized.get("nz", 1)
        )
        result["initial_condition"] = _validate_initial_definition(
            payload.get("initial_condition"),
            field="initial_condition",
            dimension=dimension,
            allowed_symbols=allowed_symbols,
            expected_values=expected_values,
        )
    return result


def validate_pdeir_document(value: object) -> dict[str, Any]:
    """Validate and normalize a PDEIR document."""

    payload = _normalize_external_pde_shape(_mapping(value))
    if _text(payload.get("schema_version")) != PDEIR_SCHEMA_VERSION:
        raise PDEIRValidationError(f"unsupported PDEIR schema: {_text(payload.get('schema_version')) or '<missing>'}")
    system_type = _text(payload.get("system_type"))
    if system_type not in SUPPORTED_PDE_SYSTEMS:
        raise PDEIRValidationError(f"unsupported PDE system type: {system_type or '<missing>'}")
    capability = PDE_CAPABILITIES[system_type]
    if capability["execution_status"] != "EXECUTABLE":
        raise PDEIRValidationError(f"PDE system type is design-only: {system_type}")
    normalized = _validate_common(payload, system_type=system_type)
    state_id = normalized["fields"][0]["id"]
    parameters = set(normalized["parameters"])
    allowed_symbols = {"t", "x", "y", "z", *parameters}
    allowed_fields = {state_id}
    if system_type in {
        "DIFFUSION_REACTION_1D",
        "ADVECTION_DIFFUSION_REACTION_1D",
        "BURGERS_1D",
        "DIFFUSION_REACTION_2D",
        "DIFFUSION_REACTION_3D",
        "HEAT_DIFFUSION_1D",
        "HEAT_DIFFUSION_2D",
        "HEAT_DIFFUSION_3D",
        "LINEAR_ADVECTION_1D",
    }:
        normalized["diffusion_coefficient"] = validate_pde_expression(
            payload.get("diffusion_coefficient", {"op": "constant", "value": 0.0})
            if system_type == "LINEAR_ADVECTION_1D"
            else payload.get("diffusion_coefficient"),
            allowed_symbols=allowed_symbols,
            allowed_fields=allowed_fields,
        )
        normalized["reaction"] = validate_pde_expression(
            payload.get("reaction", {"op": "constant", "value": 0.0})
            if system_type in {"HEAT_DIFFUSION_1D", "HEAT_DIFFUSION_2D", "HEAT_DIFFUSION_3D", "LINEAR_ADVECTION_1D"}
            else payload.get("reaction"),
            allowed_symbols=allowed_symbols,
            allowed_fields=allowed_fields,
        )
    if system_type in {"ADVECTION_DIFFUSION_REACTION_1D", "BURGERS_1D", "LINEAR_ADVECTION_1D"}:
        normalized["advection_velocity"] = validate_pde_expression(
            payload.get("advection_velocity"), allowed_symbols=allowed_symbols, allowed_fields=allowed_fields
        )
    if system_type == "SPHERICAL_RADIAL_THERMAL":
        normalized["diffusion_coefficient"] = validate_pde_expression(
            payload.get("diffusion_coefficient"),
            allowed_symbols=allowed_symbols,
            allowed_fields=allowed_fields,
        )
        normalized["heat_capacity"] = validate_pde_expression(
            payload.get("heat_capacity", {"op": "constant", "value": 1.0}),
            allowed_symbols=allowed_symbols,
            allowed_fields=allowed_fields,
        )
        normalized["source"] = validate_pde_expression(
            payload.get("source", {"op": "constant", "value": 0.0}),
            allowed_symbols=allowed_symbols,
            allowed_fields=allowed_fields,
        )
    if capability["temporal"]:
        raw_boundaries = _mapping(payload.get("boundary_conditions"))
        names = (
            ("left", "right")
            if normalized["spatial_dimension"] == 1
            else ("left", "right", "bottom", "top")
            if normalized["spatial_dimension"] == 2
            else ("left", "right", "bottom", "top", "front", "back")
        )
        normalized["boundary_conditions"] = {
            name: _validate_boundary(
                raw_boundaries.get(name),
                field=f"boundary_conditions.{name}",
                allowed_symbols=allowed_symbols,
                allowed_fields=set(),
                allowed_types=set(capability["boundary_conditions"]),
            )
            for name in names
        }
        periodic_sides = [name for name, boundary in normalized["boundary_conditions"].items() if boundary["type"] == "PERIODIC"]
        if periodic_sides:
            periodic_pairs = ({"left", "right"}, {"bottom", "top"}, {"front", "back"})
            periodic_set = set(periodic_sides)
            if not all(not (periodic_set & pair) or pair <= periodic_set for pair in periodic_pairs):
                raise PDEIRValidationError("PERIODIC boundaries must be supplied as a complete opposing pair")
    if system_type in {
        "ELLIPTIC_DIFFUSION_1D",
        "ELLIPTIC_DIFFUSION_2D",
        "POISSON_1D",
        "POISSON_2D",
        "HELMHOLTZ_1D",
        "HELMHOLTZ_2D",
    }:
        normalized["diffusion_coefficient"] = validate_pde_expression(
            payload.get("diffusion_coefficient", {"op": "constant", "value": 1.0})
            if system_type.startswith(("POISSON", "HELMHOLTZ"))
            else payload.get("diffusion_coefficient"),
            allowed_symbols=allowed_symbols,
            allowed_fields=allowed_fields,
        )
        normalized["reaction_coefficient"] = validate_pde_expression(
            payload.get("reaction_coefficient", {"op": "constant", "value": 0.0})
            if system_type.startswith("POISSON")
            else payload.get("reaction_coefficient"),
            allowed_symbols=allowed_symbols,
            allowed_fields=allowed_fields,
        )
        normalized["source"] = validate_pde_expression(
            payload.get("source", {"op": "constant", "value": 0.0}),
            allowed_symbols=allowed_symbols,
            allowed_fields=allowed_fields,
        )
        raw_boundaries = _mapping(payload.get("boundary_conditions"))
        normalized["boundary_conditions"] = {
            name: _validate_boundary(
                raw_boundaries.get(name),
                field=f"boundary_conditions.{name}",
                allowed_symbols=allowed_symbols,
                allowed_fields=set(),
                allowed_types=set(capability["boundary_conditions"]),
            )
            for name in ("left", "right")
        }
        if normalized["spatial_dimension"] == 2:
            raw_boundaries = _mapping(payload.get("boundary_conditions"))
            normalized["boundary_conditions"] = {
                name: _validate_boundary(
                    raw_boundaries.get(name),
                    field=f"boundary_conditions.{name}",
                    allowed_symbols=allowed_symbols,
                    allowed_fields=set(),
                    allowed_types=set(capability["boundary_conditions"]),
                )
                for name in ("left", "right", "bottom", "top")
            }
    if system_type in {"WAVE_1D", "WAVE_2D"}:
        normalized["wave_speed"] = validate_pde_expression(
            payload.get("wave_speed"), allowed_symbols=allowed_symbols, allowed_fields=allowed_fields
        )
        normalized["source"] = validate_pde_expression(
            payload.get("source", {"op": "constant", "value": 0.0}),
            allowed_symbols=allowed_symbols,
            allowed_fields=allowed_fields,
        )
        velocities = _validate_initial_definition(
            payload.get("initial_velocity"),
            field="initial_velocity",
            dimension=normalized["spatial_dimension"],
            allowed_symbols=allowed_symbols,
            expected_values=normalized["grid"]["nx"] * normalized["grid"].get("ny", 1),
        )
        normalized["initial_velocity"] = velocities
        raw_boundaries = _mapping(payload.get("boundary_conditions"))
        normalized["boundary_conditions"] = {
            name: _validate_boundary(
                raw_boundaries.get(name),
                field=f"boundary_conditions.{name}",
                allowed_symbols=allowed_symbols,
                allowed_fields=set(),
                allowed_types=set(capability["boundary_conditions"]),
            )
            for name in (("left", "right") if normalized["spatial_dimension"] == 1 else ("left", "right", "bottom", "top"))
        }
    return normalized


def materialize_pdeir_document(value: Mapping[str, object]) -> dict[str, Any]:
    """Expand compact analytic initial conditions immediately before trusted execution."""

    normalized = validate_pdeir_document(value)
    if not normalized.get("time_span"):
        return normalized
    coordinates = _grid_coordinates(normalized)
    parameters = {
        str(name): float(item) for name, item in _mapping(normalized.get("parameters")).items()
    }
    time_value = float(normalized["time_span"][0])
    materialized = copy.deepcopy(normalized)
    for field in ("initial_condition", "initial_velocity"):
        definition = _mapping(normalized.get(field))
        if not definition:
            continue
        materialized[field] = {
            "type": "SAMPLED_VALUES",
            "values": _materialize_initial_definition(
                definition,
                coordinates=coordinates,
                parameters=parameters,
                time_value=time_value,
                field=field,
            ),
        }
    return validate_pdeir_document(materialized)


__all__ = [
    "PDEIR_SCHEMA_VERSION",
    "PDEIRValidationError",
    "SUPPORTED_PDE_SYSTEMS",
    "evaluate_pde_expression",
    "materialize_pdeir_document",
    "validate_pde_expression",
    "validate_pdeir_document",
]
