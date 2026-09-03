"""Cross-field invariants that JSON Schema cannot express clearly."""

from __future__ import annotations

from typing import Any, Callable, Iterable

from .errors import ContractValidationError


def _fail(name: str, message: str, field_path: str, **context: Any) -> None:
    raise ContractValidationError(
        f"{name} semantic validation failed at {field_path}: {message}",
        field_path=field_path,
        context={"schema": name, **context},
    )


def _unique(name: str, values: Iterable[str], field_path: str) -> None:
    rows = list(values)
    if len(rows) != len(set(rows)):
        _fail(name, "values must be unique", field_path)


def _walk_expression(expression: dict[str, Any]) -> Iterable[dict[str, Any]]:
    yield expression
    for argument in expression.get("arguments", []):
        yield from _walk_expression(argument)


def validate_equation_ir(value: dict[str, Any]) -> None:
    variables = value["variables"]
    equations = value["equations"]
    variable_ids = [row["variable_id"] for row in variables]
    symbols = [row["symbol"] for row in variables]
    equation_ids = [row["equation_id"] for row in equations]
    _unique("EquationIR", variable_ids, "/variables/*/variable_id")
    _unique("EquationIR", symbols, "/variables/*/symbol")
    _unique("EquationIR", equation_ids, "/equations/*/equation_id")
    known = set(variable_ids)
    roles = {row["variable_id"]: row["role"] for row in variables}
    axis_symbol = value["independent_variable"]["symbol"]
    for index, variable in enumerate(variables):
        per_unit = variable["per_unit"]
        required_bases = {"base_quantity", "base_value", "base_unit"}
        if per_unit["enabled"] and not required_bases.issubset(per_unit):
            _fail("EquationIR", "enabled per-unit metadata requires quantity, value, and unit", f"/variables/{index}/per_unit")
    for index, equation in enumerate(equations):
        derivative_nodes = []
        for node in _walk_expression(equation["residual"]):
            variable_id = node.get("variable_id")
            if variable_id and variable_id not in known:
                _fail("EquationIR", f"unknown variable_id {variable_id}", f"/equations/{index}/residual")
            if node.get("node") == "derivative":
                derivative_nodes.append(node)
                if node["with_respect_to"] != axis_symbol:
                    _fail("EquationIR", "derivative axis differs from independent variable", f"/equations/{index}/residual")
            if node.get("node") == "operator":
                arity = len(node["arguments"])
                operator = node["operator"]
                if operator == "negate" and arity != 1:
                    _fail("EquationIR", "negate requires exactly one argument", f"/equations/{index}/residual")
                if operator in {"subtract", "divide", "power"} and arity != 2:
                    _fail("EquationIR", f"{operator} requires exactly two arguments", f"/equations/{index}/residual")
                if operator in {"add", "multiply"} and arity < 2:
                    _fail("EquationIR", f"{operator} requires at least two arguments", f"/equations/{index}/residual")
            if node.get("node") == "function" and len(node["arguments"]) != 1:
                _fail("EquationIR", "supported scalar functions require exactly one argument", f"/equations/{index}/residual")
        if equation["kind"] == "differential":
            target = equation.get("derivative_of")
            if not target or roles.get(target) != "state":
                _fail("EquationIR", "differential equation must target a declared state", f"/equations/{index}/derivative_of")
            if not any(node["variable_id"] == target for node in derivative_nodes):
                _fail("EquationIR", "residual does not contain the declared state derivative", f"/equations/{index}/residual")
        elif equation.get("derivative_of") is not None or derivative_nodes:
            _fail("EquationIR", "algebraic equation cannot contain derivatives", f"/equations/{index}")
    state_ids = {row["variable_id"] for row in variables if row["role"] == "state"}
    derivative_targets = [row["derivative_of"] for row in equations if row["kind"] == "differential"]
    _unique("EquationIR", derivative_targets, "/equations/*/derivative_of")
    if set(derivative_targets) != state_ids:
        _fail("EquationIR", "every state must have exactly one differential equation", "/equations")


def validate_equation_ir_v2(value: dict[str, Any]) -> None:
    validate_equation_ir(value)
    for index, variable in enumerate(value["variables"]):
        if variable["reference_mode"] == "ABSOLUTE" and "nominal_value" not in variable:
            _fail("EquationIRV2", "absolute variables require nominal_value", f"/variables/{index}/nominal_value")


def validate_candidate_model(value: dict[str, Any]) -> None:
    variables = [row["name"] for row in value["variables"]]
    parameters = [row["name"] for row in value["parameters"]]
    equations = [row["equation_id"] for row in value["equations"]]
    _unique("CandidateModelV1", variables, "/variables/*/name")
    _unique("CandidateModelV1", parameters, "/parameters/*/name")
    _unique("CandidateModelV1", equations, "/equations/*/equation_id")
    overlap = sorted(set(variables).intersection(parameters))
    if overlap:
        _fail("CandidateModelV1", "variables and parameters must have distinct names", "/parameters", overlap=overlap)
    for index, variable in enumerate(value["variables"]):
        if variable["reference_mode"] == "ABSOLUTE" and "nominal_value" not in variable:
            _fail("CandidateModelV1", "absolute variables require nominal_value", f"/variables/{index}/nominal_value")
    for index, equation in enumerate(value["equations"]):
        has_derivative = equation["lhs"].startswith("d(") and equation["lhs"].endswith(")/dt")
        if equation["kind"] == "ode" and not has_derivative:
            _fail("CandidateModelV1", "ode lhs must use d(name)/dt", f"/equations/{index}/lhs")
        if equation["kind"] != "ode" and has_derivative:
            _fail("CandidateModelV1", "only ode equations may have a derivative lhs", f"/equations/{index}/lhs")


def validate_case_manifest(value: dict[str, Any]) -> None:
    domain = value["time_domain"]
    if domain["stop"] <= domain["start"]:
        _fail("CaseManifest", "stop must be greater than start", "/time_domain/stop")
    initial_ids = [row["variable_id"] for row in value["initial_conditions"]]
    parameter_ids = [row["variable_id"] for row in value["parameters"]]
    _unique("CaseManifest", initial_ids, "/initial_conditions/*/variable_id")
    _unique("CaseManifest", parameter_ids, "/parameters/*/variable_id")
    if value["equation_ir_ref"]["schema_name"] != "EquationIR":
        _fail("CaseManifest", "equation_ir_ref must name EquationIR", "/equation_ir_ref/schema_name")


def validate_case_manifest_v2(value: dict[str, Any]) -> None:
    domain = value["time_domain"]
    if domain["stop"] <= domain["start"]:
        _fail("CaseManifestV2", "stop must be greater than start", "/time_domain/stop")
    variable_ids = [row["variable_id"] for row in value["variables"]]
    _unique("CaseManifestV2", variable_ids, "/variables/*/variable_id")
    known = set(variable_ids)
    for group in ("initial_conditions", "parameters"):
        identifiers = [row["variable_id"] for row in value[group]]
        _unique("CaseManifestV2", identifiers, f"/{group}/*/variable_id")
        unknown = sorted(set(identifiers) - known)
        if unknown:
            _fail("CaseManifestV2", "values reference undeclared variables", f"/{group}", unknown=unknown)
    for index, event in enumerate(value["events"]):
        if not domain["start"] <= event["time"] <= domain["stop"]:
            _fail("CaseManifestV2", "event time lies outside time_domain", f"/events/{index}/time")


def validate_lens_spec(value: dict[str, Any]) -> None:
    transforms = value["transforms"]
    orders = [row["order"] for row in transforms]
    if orders != list(range(len(transforms))):
        _fail("LensSpec", "transform order must be contiguous and list-ordered from zero", "/transforms")
    required_by_type = {
        "RESAMPLE": {"sample_rate_hz", "anti_alias"},
        "ADD_GAUSSIAN_NOISE": {"noise_std", "seed"},
        "DROP_SAMPLES": {"missing_rate", "seed"},
        "AFFINE": {"scale", "offset"},
    }
    allowed_by_type = {
        "IDENTITY": set(),
        "RESAMPLE": {"sample_rate_hz", "anti_alias"},
        "ADD_GAUSSIAN_NOISE": {"noise_std", "seed"},
        "DROP_SAMPLES": {"missing_rate", "seed"},
        "AFFINE": {"scale", "offset"},
    }
    parameter_fields = {"sample_rate_hz", "anti_alias", "noise_std", "missing_rate", "scale", "offset", "seed"}
    for index, transform in enumerate(transforms):
        required = required_by_type.get(transform["type"], set())
        missing = sorted(required - transform.keys())
        if missing:
            _fail("LensSpec", f"{transform['type']} lacks {', '.join(missing)}", f"/transforms/{index}")
        unexpected = parameter_fields.intersection(transform) - allowed_by_type[transform["type"]]
        if unexpected:
            _fail("LensSpec", f"{transform['type']} has unrelated parameters: {', '.join(sorted(unexpected))}", f"/transforms/{index}")


def validate_lens_spec_v2(value: dict[str, Any]) -> None:
    orders = [row["order"] for row in value["transforms"]]
    if orders != list(range(len(orders))):
        _fail("LensSpecV2", "transform order must be contiguous and list-ordered from zero", "/transforms")
    required_by_type = {
        "RESAMPLE": {"sample_rate_hz", "anti_alias"},
        "ADD_GAUSSIAN_NOISE": {"noise_std", "noise_unit", "seed"},
        "DROP_SAMPLES": {"missing_rate", "seed"},
        "AFFINE": {"scale", "offset"},
    }
    for index, transform in enumerate(value["transforms"]):
        missing = sorted(required_by_type.get(transform["type"], set()) - transform.keys())
        if missing:
            _fail("LensSpecV2", f"{transform['type']} lacks {', '.join(missing)}", f"/transforms/{index}")


def validate_experiment_protocol(value: dict[str, Any]) -> None:
    split = value["split_policy"]
    total = float(split["train"]) + float(split["validation"]) + float(split["ood"])
    if abs(total - 1.0) > 1e-12:
        _fail("ExperimentProtocol", "train, validation, and ood fractions must sum to 1", "/split_policy")
def validate_validation_report(value: dict[str, Any]) -> None:
    check_ids = [check["check_id"] for check in value["checks"]]
    stages = [check["stage"] for check in value["checks"]]
    _unique("ValidationReport", check_ids, "/checks/*/check_id")
    if sorted(stages) != ["V1", "V2", "V3"]:
        _fail("ValidationReport", "report must contain exactly one V1, V2, and V3 check", "/checks")
    for index, check in enumerate(value["checks"]):
        _unique("ValidationReport", (row["name"] for row in check["metrics"]), f"/checks/{index}/metrics/*/name")
        metric_failed = any(row["status"] == "FAIL" for row in check["metrics"])
        if check["status"] == "PASS" and metric_failed:
            _fail("ValidationReport", "a passing check cannot contain a failed metric", f"/checks/{index}/status")
    failed = any(check["status"] == "FAIL" for check in value["checks"])
    not_run = any(check["status"] == "NOT_RUN" for check in value["checks"])
    if value["verdict"] == "PASS" and (failed or not_run or value["errors"]):
        _fail("ValidationReport", "PASS requires all checks to pass and no errors", "/verdict")
    if value["verdict"] == "HARD_REJECT" and not failed:
        _fail("ValidationReport", "HARD_REJECT requires at least one failed check", "/verdict")
    if value["verdict"] == "BLOCKED" and not not_run:
        _fail("ValidationReport", "BLOCKED requires at least one check not run", "/verdict")


def validate_run_manifest(value: dict[str, Any]) -> None:
    descriptors = [*value["input_artifacts"], *value["output_artifacts"]]
    identities = [(row["artifact_type"], row["artifact_id"], row["artifact_version"]) for row in descriptors]
    _unique("RunManifest", ("|".join(map(str, row)) for row in identities), "/input_artifacts|output_artifacts")
    protocol_hashes = {
        row["content_hash"] for row in value["output_artifacts"]
        if row["contract_schema"] == "ExperimentProtocol"
    }
    if value["protocol_hash"] not in protocol_hashes:
        _fail("RunManifest", "protocol_hash must identify an output ExperimentProtocol", "/protocol_hash")


def validate_case_against_equation_ir(case: dict[str, Any], equation_ir: dict[str, Any]) -> None:
    """Validate referential integrity without performing role-B physics checks."""

    variables = {row["variable_id"]: row for row in equation_ir["variables"]}
    state_ids = {key for key, row in variables.items() if row["role"] == "state"}
    initial_ids = {row["variable_id"] for row in case["initial_conditions"]}
    if initial_ids != state_ids:
        _fail(
            "CaseManifest", "initial conditions must cover every and only EquationIR state",
            "/initial_conditions", expected=sorted(state_ids), observed=sorted(initial_ids),
        )
    for group_name in ("initial_conditions", "parameters"):
        for index, item in enumerate(case[group_name]):
            variable = variables.get(item["variable_id"])
            if variable is None:
                _fail("CaseManifest", "value references an unknown EquationIR variable", f"/{group_name}/{index}/variable_id")
            if item["unit"] != variable["unit"]:
                _fail(
                    "CaseManifest", "value unit differs from EquationIR variable unit",
                    f"/{group_name}/{index}/unit", expected=variable["unit"], observed=item["unit"],
                )
            if group_name == "parameters" and variable["role"] not in {"parameter", "input"}:
                _fail("CaseManifest", "parameters can bind only parameter or input variables", f"/{group_name}/{index}/variable_id")
    if case["time_domain"]["unit"] != equation_ir["independent_variable"]["unit"]:
        _fail("CaseManifest", "time-domain unit differs from EquationIR independent-variable unit", "/time_domain/unit")


SEMANTIC_VALIDATORS: dict[str, Callable[[dict[str, Any]], None]] = {
    "EquationIR": validate_equation_ir,
    "CaseManifest": validate_case_manifest,
    "LensSpec": validate_lens_spec,
    "ExperimentProtocol": validate_experiment_protocol,
    "ValidationReport": validate_validation_report,
    "RunManifest": validate_run_manifest,
    "CandidateModelV1": validate_candidate_model,
    "EquationIRV2": validate_equation_ir_v2,
    "CaseManifestV2": validate_case_manifest_v2,
    "LensSpecV2": validate_lens_spec_v2,
    "ValidationReportV2": validate_validation_report,
}


def validate_semantics(name: str, value: Any) -> None:
    validator = SEMANTIC_VALIDATORS.get(name)
    if validator is not None:
        validator(value)
