"""LLM synthesis of declarative quantitative models, never executable code."""

from __future__ import annotations

import json
import logging
import os
import re
import sys
import time
from collections.abc import Callable, Mapping
from threading import local
from typing import Any

from src.agents.quantitative_modeling.model_format import (
    QuantitativeModelFormatError,
    model_spec_identity,
    normalize_quantitative_model_spec,
)
from src.agents.quantitative_modeling.pde_capability_registry import executable_pde_catalog
from src.agents.quantitative_modeling.parameter_contracts import (
    ParameterContractError,
    approved_mathir_parameters,
    model_blueprint_identity,
    normalize_approved_parameter_set,
    normalize_model_blueprint,
    parameter_evidence_summary,
)
from src.agents.quantitative_modeling.publisher.json_markdown_consistency import (
    JsonMarkdownConsistencyError,
    validate_json_markdown_consistency,
)
from src.llm.provider_registry import resolve_model


_DUAL_BLOCK_RESPONSE = re.compile(
    r"\A\s*<QUANTITATIVE_MODEL_JSON>\s*(?P<json>\{.*?\})\s*"
    r"</QUANTITATIVE_MODEL_JSON>\s*<QUANTITATIVE_MODEL_MARKDOWN>\s*"
    r"(?P<markdown>.*?)\s*</QUANTITATIVE_MODEL_MARKDOWN>\s*\Z",
    re.DOTALL,
)
_JSON_BLOCK_RESPONSE = re.compile(
    r"\A\s*<QUANTITATIVE_MODEL_JSON>\s*(?P<json>\{.*?\})\s*</QUANTITATIVE_MODEL_JSON>\s*\Z",
    re.DOTALL,
)
_LOGGER = logging.getLogger(__name__)

_MODEL_JSON_SHAPE_GUIDE = """Required JSON container shapes and one-pass validation rules:
- assumptions is an array of objects with assumption_id, statement, and effect_if_violated.
- symbols is an array, never an object. Every symbol item has symbol_id, latex, meaning, unit, dimension, and role.
- equations is an array of objects with equation_id, role, latex, and where_symbol_ids (a non-empty array of declared symbol_id values).
- initial_conditions, boundary_conditions, parameterization, scenarios, objective_and_constraints, validation_plan, limitations, and references are arrays.
- algorithm is an object with input, output, and steps arrays. numerical_plan is an object with solver_family, discretization, and convergence_checks.
- All scalar numeric values must be finite JSON numbers: do not use strings such as \"0.01 s\", unit-bearing text, arrays, or {\"value\": ...} wrappers for scalar fields. Lists are allowed only where the contract explicitly requires a coordinate interval, time span, grid-sample array, or AST args array.
- Treat these validator paths as exact canonical paths during the preflight: solver_options.time_step, solver_options.time_integrator, spatial_domain.x, spatial_domain.y, spatial_domain.z, grid.nx, grid.ny, grid.nz, initial_condition.type, initial_condition.profile/value/center/sigma/expression, initial_velocity.profile/value/center/sigma/expression, and boundary_conditions.<side>.type/value. Never change a numeric path into a string, object, or nested array.
- v1 models use a valid MathIR object with the exact nested key-value \"schema_version\": \"mathir_v1\". v2 PDE models use an execution_ir object with kind PDE and schema_version execution_ir_v1 containing pdeir_v1. Do not put ieee_math_model_v1 inside an execution document.
- A PDE execution_ir must have exactly this outer shape: {\"kind\":\"PDE\",\"schema_version\":\"execution_ir_v1\",\"document\":{\"schema_version\":\"pdeir_v1\",...}}. The document must use the canonical keys below; do not rely on aliases such as pde_family, axes, shape, sizes, grid_points, equation_terms, or putting time_step inside discretization.
- The PDE document system_type must be one exact registered EXECUTABLE key from the catalog below, with one spatial_dimension matching that family. Never emit a design-only family, an array of family names, a hybrid ODE/PDE, or an unregistered solver name.
- Every PDE document must contain exactly one field in fields. The field object must contain a safe identifier id matching every field AST leaf name, and may contain string symbol/unit plus numeric bounds. Every parameter name must match [A-Za-z_][A-Za-z0-9_]{0,63}; parameters is an object whose values are finite JSON numbers.
- PDE spatial_domain is a direct object of coordinate-to-two-number-interval mappings. For 1D use exactly {\"x\":[lower,upper]}; for 2D use x and y; for 3D use x, y, and z. Every lower value is strictly less than its upper value. Even SPHERICAL_RADIAL_THERMAL uses canonical JSON coordinate x; in equations and Markdown state that x is the physical radial coordinate r. Never emit {\"r\":...}, an axes list, or nested {\"lower\":...,\"upper\":...} objects.
- PDE grid is a direct object of integer sizes: 1D {\"nx\":N} with 3<=N<=4096, 2D {\"nx\":Nx,\"ny\":Ny} with each size 3..1024, and 3D {\"nx\":Nx,\"ny\":Ny,\"nz\":Nz} with each size 3..128. The initial sample count is exactly nx*ny*nz, treating omitted dimensions as 1. Prefer small first-run grids such as 33, 17x17, or 9x9x9 unless the idea explicitly requires refinement.
- PDE discretization must be {\"method\": registered_method, \"grid_type\":\"UNIFORM\", \"space_order\":1_or_2}. The method and time integrator must be selected from the exact family entry in the catalog; uniform grids are the only executable option.
- A temporal PDE must contain time_span:[start,end] with two finite numbers and end>start, solver_options:{\"time_step\":positive_finite_number,\"time_integrator\":registered_integrator}, and a compact initial_condition. Use {\"type\":\"ANALYTIC_PROFILE\",\"profile\":\"UNIFORM\",\"value\":number}, {\"type\":\"ANALYTIC_PROFILE\",\"profile\":\"GAUSSIAN\",\"amplitude\":number,\"offset\":number,\"center\":coordinate_map,\"sigma\":positive_coordinate_map}, or {\"type\":\"ANALYTIC_PROFILE\",\"profile\":\"ANALYTIC_EXPRESSION\",\"expression\":safe_AST}. For 1D, center and sigma may be numbers or {\"x\":number}; for 2D/3D they must map exactly to x/y[/z]. The trusted solver expands this definition on the uniform grid. Do not output initial sample arrays, nested arrays, ellipses, repetition instructions, formula strings, Python, or code.
- A wave PDE also requires initial_velocity using the same compact ANALYTIC_PROFILE forms. Existing SAMPLED_VALUES documents are accepted only for backward compatibility and must not be generated for a new model. A steady elliptic/Poisson/Helmholtz PDE must not contain time_span, solver_options, initial_condition, or initial_velocity.
- mathir.system_type is exactly one string, never an array and never a hybrid.
- Boundary conditions are required on every side: 1D left/right; 2D left/right/bottom/top; 3D left/right/bottom/top/front/back. Each is an object with a family-approved type. DIRICHLET and NEUMANN require value as an AST; NEUMANN_ZERO, PERIODIC, and SPHERICAL_ORIGIN_REGULARITY do not require value. PERIODIC must be used on complete opposing pairs left/right, bottom/top, or front/back. Spherical radial models require SPHERICAL_ORIGIN_REGULARITY on left and DIRICHLET, NEUMANN, or NEUMANN_ZERO on right.
- PDE expression values are AST objects, never equation strings, Python, code, derivatives, Laplacian names, or function calls. Leaves are {\"op\":\"constant\",\"value\":number}, {\"op\":\"variable\",\"name\":\"t|x|y|z|declared_parameter\"}, or {\"op\":\"field\",\"name\":\"the_one_field_id\"}. Binary add, sub, mul, div, pow, min, max, lt, le, gt, ge, eq, ne require exactly two args; unary neg, abs, exp, log, sin, cos require exactly one; conditional and if_else require exactly three. Boundary ASTs cannot reference the field. Do not reference an undeclared symbol or emit an unsupported PDE operator.
- Family-required PDE AST fields are: diffusion/reaction families require diffusion_coefficient and reaction; ADVECTION_DIFFUSION_REACTION_1D, BURGERS_1D, and LINEAR_ADVECTION_1D additionally require advection_velocity; SPHERICAL_RADIAL_THERMAL requires diffusion_coefficient, heat_capacity, and source; ELLIPTIC_DIFFUSION, POISSON, and HELMHOLTZ families require diffusion_coefficient, reaction_coefficient, and source; WAVE_1D/WAVE_2D require wave_speed and source. Include every required field explicitly even when its value is zero.
- Runtime preflight is part of model validity: parabolic diffusion coefficients must remain non-negative; spherical heat_capacity must remain positive and conductivity non-negative; elliptic diffusion must remain positive; wave_speed must remain positive; every expression and resulting field must remain finite. For explicit parabolic solvers choose time_step with margin: in 1D diffusion use D*dt/dx^2 <= 0.5, in 1D advection-diffusion use D*dt/dx^2 + abs(v)*dt/dx <= 1.0, in 2D/3D diffusion use D*dt*sum(1/dx_i^2) <= 0.5, and in spherical radial thermal use (D/heat_capacity)*dt/dr^2 <= 1/6. For waves use c*dt/dx <= 1 in 1D and c*dt*sqrt(1/dx^2+1/dy^2) <= 1 in 2D. Use a smaller margin rather than a borderline value.
- Keep temporal step count ceil((end-start)/time_step) <= 20000 (the solver's max_time_steps budget) and grid cells <= 100000; keep elliptic matrix nonzeros within the trusted solver budget. Do not describe Monte Carlo, adaptive mesh, event stopping, external code, or solver capabilities not present in the selected family.
- Registered executable PDE families and their exact numerical contract are: """ + json.dumps(executable_pde_catalog(), sort_keys=True) + """. Design-only families must not be emitted as executable execution_ir.
- SPHERICAL_RADIAL_THERMAL is a radial thermal adapter, not Cartesian diffusion: use x:[0,radius], left SPHERICAL_ORIGIN_REGULARITY, explicit heat_capacity and source ASTs, and the dedicated FINITE_DIFFERENCE_SPHERICAL_RADIAL method.
- An ODE_IVP mathir has exactly this container pattern: {\"schema_version\":\"mathir_v1\",\"system_type\":\"ODE_IVP\",\"states\":[{\"id\":\"state_name\",\"initial\":1.0}],\"parameters\":{\"parameter_name\":1.0},\"derivatives\":{\"state_name\":{\"op\":\"constant\",\"value\":0.0}},\"time_span\":[0.0,1.0],\"solver_options\":{\"max_step\":0.01}}. Choose max_step so ceil((time_span[1]-time_span[0])/max_step)+1 is at most 2000; never copy a unit-time example step into a years-long horizon.
- MathIR expressions are AST objects rather than formula strings and may use only the registered operators and declared state or parameter names. ODE_IVP exposes read-only t but no event engine; encode a finite phase with conditional or if_else over t. Represent every modeled scenario difference through approved SCENARIO_INPUT values used by dynamics or state initialization; do not leave compared scenarios mathematically identical.
- Before emitting the JSON block, perform one complete local audit of every PDE path above, including analytic-profile fields, boundary pairs, family-required keys, AST arities and names, positivity, stability, and resource limits. Do not wait for a validator to reveal the next missing field."""


class QuantitativeModelSynthesisError(RuntimeError):
    """Raised when the required quantitative model response is malformed or unsafe."""


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _bounded_json(value: Mapping[str, object], *, maximum: int = 16_000) -> str:
    encoded = json.dumps(dict(value), ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
    return encoded[:maximum]


def _text(value: object) -> str:
    return str(value or "").strip()


def _execution_document(specification: Mapping[str, object]) -> Mapping[str, object]:
    """Return the normalized legacy MathIR or PDE document."""

    if specification.get("schema_version") == "ieee_math_model_v1":
        return specification["mathir"]
    return _mapping(_mapping(specification.get("execution_ir")).get("document"))


def _normalize_markdown_abstract_prefix(markdown: str) -> str:
    text = markdown.strip()
    if re.match(r"\AAbstract—", text, re.IGNORECASE):
        return text
    heading = re.match(r"\A#{1,6}\s*Abstract\s*\r?\n+", text, re.IGNORECASE)
    if heading is not None:
        return "Abstract— " + text[heading.end() :].lstrip()
    label = re.match(r"\AAbstract\s*:\s*", text, re.IGNORECASE)
    if label is not None:
        return "Abstract— " + text[label.end() :].lstrip()
    return text


def _execution_condition_lines(specification: Mapping[str, object]) -> list[str]:
    document = _execution_document(specification)
    lines: list[str] = []
    for field_name in ("initial_condition", "initial_velocity"):
        definition = _mapping(document.get(field_name))
        if not definition:
            continue
        if _text(definition.get("type")) == "SAMPLED_VALUES":
            detail = f"sampled on the trusted grid ({len(definition.get('values') or [])} values)"
        else:
            detail = json.dumps(definition, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        lines.append(f"- Executable {field_name}: {detail}.")
    return lines


def _render_markdown_from_specification(specification: Mapping[str, object]) -> str:
    symbols = [dict(item) for item in specification["symbols"]]
    symbol_meanings = {str(item["symbol_id"]): str(item["meaning"]) for item in symbols}
    assumptions = [
        f"- {item['assumption_id']}: {item['statement']} Effect if violated: {item['effect_if_violated']}"
        for item in specification["assumptions"]
    ]
    symbol_lines = [
        f"- {item['symbol_id']}: ${item['latex']}$ — {item['meaning']} ({item['unit']}; {item['dimension']}; {item['role']})"
        for item in symbols
    ]
    equation_lines = []
    for item in specification["equations"]:
        where_ids = [str(identifier) for identifier in item["where_symbol_ids"]]
        where_text = "; ".join(f"{identifier}: {symbol_meanings[identifier]}" for identifier in where_ids)
        equation_lines.append(
            f"- {item['equation_id']} ({item['role']}): ${item['latex']}$. Where {where_text}."
        )
    algorithm = dict(specification["algorithm"])
    numerical_plan = dict(specification["numerical_plan"])
    references = list(specification["references"]) or ["No external reference was declared in the model specification."]
    sections = [
        f"Abstract— {specification['abstract']}",
        "# Assumptions",
        *assumptions,
        "# Symbols",
        *symbol_lines,
        "# Equations",
        *equation_lines,
        "# Initial and Boundary Conditions",
        *[f"- {item}" for item in specification["initial_conditions"]],
        *[f"- {item}" for item in specification["boundary_conditions"]],
        *_execution_condition_lines(specification),
        "# Algorithm",
        "Input: " + "; ".join(algorithm["input"]),
        "Output: " + "; ".join(algorithm["output"]),
        "Steps: " + "; ".join(algorithm["steps"]),
        "# Parameters and Scenarios",
        *[f"- Parameter: {item}" for item in specification["parameterization"]],
        *[f"- Scenario: {item}" for item in specification["scenarios"]],
        "# Objective and Constraints",
        *[f"- {item}" for item in specification["objective_and_constraints"]],
        "# Numerical Validation",
        f"Solver: {numerical_plan['solver_family']}. Discretization: {numerical_plan['discretization']}.",
        *[f"- Convergence check: {item}" for item in numerical_plan["convergence_checks"]],
        *[f"- Validation: {item}" for item in specification["validation_plan"]],
        "# Limitations",
        *[f"- {item}" for item in specification["limitations"]],
        "# References",
        *[f"- {item}" for item in references],
    ]
    return "\n\n".join(str(item) for item in sections)


def build_quantitative_model_prompt(
    *,
    quantitative_idea: Mapping[str, object],
    lineage: Mapping[str, object],
    model_blueprint: Mapping[str, object] | None = None,
    approved_parameter_set: Mapping[str, object] | None = None,
    revision_context: Mapping[str, object] | None = None,
    execution_scenarios: object = None,
) -> str:
    """Build one rigid declarative-model request from one eligible Q idea."""

    sections = [
            "You are specifying a scientific mathematical model for a controlled numerical-simulation branch.",
            "Return exactly one block and no text before or after it:",
            "<QUANTITATIVE_MODEL_JSON>",
            "{...}",
            "</QUANTITATIVE_MODEL_JSON>",
            "The pipeline deterministically renders the Markdown report locally from this JSON; do not generate Markdown.",
            "Do not return Python, shell commands, notebooks, URLs, file paths, dynamic function names, Markdown, or code fences.",
            "The JSON is the only fact source. Use schema_version ieee_math_model_v1 for legacy MathIR models or ieee_math_model_v2 for PDE execution_ir models, and exactly preserve",
            "the supplied lineage. Include title, abstract, scientific_question, model_scope, assumptions, symbols,",
            "equations with stable IDs Q1-EQ-001 style, initial_conditions, boundary_conditions, parameterization,",
            "scenarios, objective_and_constraints, algorithm, numerical_plan, validation_plan, limitations, references,",
            "and either a safe MathIR object or a safe execution_ir object. MathIR supports the legacy registered system types; PDE execution_ir supports only registered PDE families and uses expression AST nodes, never formula strings.",
            _MODEL_JSON_SHAPE_GUIDE,
            "Do not claim numerical results because no simulation has been authorized yet.",
        "Quantitative idea:",
        _bounded_json(quantitative_idea),
        "Immutable lineage to copy exactly:",
        _bounded_json(lineage),
    ]
    if model_blueprint is not None or approved_parameter_set is not None:
        if model_blueprint is None or approved_parameter_set is None:
            raise QuantitativeModelSynthesisError(
                "evidence-bound model materialization requires both a blueprint and an approved parameter set"
            )
        normalized_blueprint = normalize_model_blueprint(model_blueprint)
        normalized_parameter_set = normalize_approved_parameter_set(approved_parameter_set)
        sections.extend(
            (
                "This is evidence-bound model materialization, not free-form parameterization.",
                "The execution document parameters object must contain exactly the approved MathIR symbols with exactly the approved values.",
                "Do not add a parameter value, omit an approved parameter, or override a selected value. The system, not you, will attach",
                "the parameter provenance field after validating the execution values.",
                "Validated non-numeric model blueprint:",
                _bounded_json(normalized_blueprint),
                "Approved parameter set (copy its values exactly):",
                _bounded_json(normalized_parameter_set),
            )
        )
        parameter_ids = {entry["parameter_id"] for entry in normalized_parameter_set["entries"]}
        pulsar_recycling_parameters = {
            "initial_period",
            "initial_inclination",
            "initial_surface_magnetic_field",
            "vacuum_dipole_braking_constant",
            "wind_braking_efficiency",
            "inclination_decay_timescale",
            "accretion_rate",
            "accretion_braking_constant",
            "accretion_duration",
            "maximum_simulated_age",
        }
        if pulsar_recycling_parameters <= parameter_ids:
            sections.extend(
                (
                    "Pulsar recycling executable constraints for this parameter contract:",
                    "Use P(0)=P0 and alpha(0)=alpha0. Positive dP/dt means isolated spin-down; negative dP/dt means accretion spin-up.",
                    "For t < t_acc with nonzero Mdot and K_acc, use the accretion branch -K_acc*Mdot/max(P, 0.01).",
                    "Otherwise use the isolated branch +K_dipole*B0^2*sin(alpha)^2*(1+eta)/max(P, 0.01).",
                    "Use dalpha/dt=-alpha/tau_alpha. Do not use P^-3, and do not apply both torque branches simultaneously.",
                    "Represent only the executable ODE in MathIR; N_mc and catalogue-level population aggregation remain documented outer-loop controls.",
                )
            )
        pulsar_thermal_parameters = {
            "neutron_star_mass",
            "initial_core_temperature",
            "initial_spin_frequency",
            "initial_central_density",
            "initial_spin_period_derivative",
            "phase_transition_critical_density",
            "effective_latent_heat_temperature_release",
            "scenario_selector",
            "braking_index",
            "effective_cooling_timescale",
            "core_surface_conversion_coefficient",
            "rotational_compression_coefficient",
        }
        if pulsar_thermal_parameters <= parameter_ids:
            sections.extend(
                (
                    "Pulsar thermal-transition executable constraints for this parameter contract:",
                    "Use ODE states Omega, rho_c, T_core, phase_fraction, and T_surface initialized from Omega0, rho_c0, T_c0, 0, and alpha_cs*T_c0.",
                    "Use magnetic-braking evolution dOmega/dt=-(Pdot0/(2*pi))*Omega0^(2-n)*Omega^n.",
                    "Use spin-down compression drho_c/dt=-kappa_rot*Omega*(dOmega/dt)*(M_NS/1.42), expanded as an AST without derivative references.",
                    "For scenario >= 1 and rho_c >= rho_crit, evolve phase_fraction toward 1 on 0.01*tau_cool; otherwise its derivative is zero.",
                    "Use dT_core/dt=-cooling_factor*T_core/tau_cool + L_latent*d(phase_fraction)/dt, with cooling_factor=1 for scenario 0 or 1 and 0.5 for scenario >= 2.",
                    "Use dT_surface/dt=alpha_cs*dT_core/dt, expanded as an AST. All scenarios must remain finite and temperatures, density, and phase fraction must stay non-negative.",
                    "Integrate from 0 to 3*tau_cool with no more than 2000 output points. Do not claim resolved EOS or neutrino microphysics.",
                )
            )
    if revision_context:
        sections.extend(
            (
                "Accepted revision context:",
                _bounded_json(dict(revision_context)),
                "Implement the accepted model delta in this revision. Do not default to the parent model family when the accepted context requests a different registered executable family.",
            )
        )
    if execution_scenarios is not None:
        sections.extend(
            (
                "The external audited run plan will execute these exact scenarios:",
                json.dumps(execution_scenarios, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False),
                "Every parameter overridden by these scenarios must operationally affect a MathIR derivative or state initialization.",
                "Verify that changing each override changes at least one computed trajectory; narrative-only scenario differences are forbidden.",
                "Preserve the blueprint's physical sign conventions and mechanism directions in the executable AST.",
            )
        )
    return "\n".join(sections)


def parse_quantitative_model_response(value: object) -> tuple[dict[str, Any], str]:
    """Parse the compact JSON protocol, with legacy dual-block compatibility."""

    if not isinstance(value, str):
        raise QuantitativeModelSynthesisError("quantitative model response must be text")
    match = _DUAL_BLOCK_RESPONSE.fullmatch(value)
    if match is None:
        match = _JSON_BLOCK_RESPONSE.fullmatch(value)
        if match is None:
            raise QuantitativeModelSynthesisError(
                "response must contain exactly one quantitative model JSON block"
            )
        markdown = ""
    else:
        markdown = match.group("markdown").strip()
    try:
        raw_specification = json.loads(match.group("json"))
    except json.JSONDecodeError as exc:
        raise QuantitativeModelSynthesisError("quantitative model JSON block is invalid") from exc
    if not isinstance(raw_specification, Mapping):
        raise QuantitativeModelSynthesisError("quantitative model JSON block must be an object")
    try:
        return normalize_quantitative_model_spec(raw_specification), markdown
    except QuantitativeModelFormatError as exc:
        raise QuantitativeModelSynthesisError(f"quantitative model JSON is invalid: {exc}") from exc


def _invoke_model_llm(llm_call: Callable[..., object], prompt: str, *, phase: str) -> object:
    if bool(getattr(llm_call, "supports_phase", False)):
        return llm_call(prompt, phase=phase)
    return llm_call(prompt)


def _report_synthesis_stage(llm_call: Callable[..., object], message: str, *args: object) -> None:
    reporter = getattr(llm_call, "report_stage", None)
    if callable(reporter):
        reporter(message, *args)
    else:
        _LOGGER.info(message, *args)


def _preflight_synthesis_context(
    *,
    lineage: Mapping[str, object],
    model_blueprint: Mapping[str, object] | None,
    approved_parameter_set: Mapping[str, object] | None,
    revision_context: Mapping[str, object] | None,
    execution_scenarios: object,
) -> None:
    if (model_blueprint is None) != (approved_parameter_set is None):
        raise QuantitativeModelSynthesisError(
            "evidence-bound model materialization requires both a blueprint and an approved parameter set"
        )
    if model_blueprint is not None and approved_parameter_set is not None:
        blueprint = normalize_model_blueprint(model_blueprint)
        parameter_set = normalize_approved_parameter_set(approved_parameter_set)
        expected_lineage = {key: lineage.get(key) for key in blueprint["lineage"]}
        if blueprint["lineage"] != expected_lineage or parameter_set["lineage"] != expected_lineage:
            raise QuantitativeModelSynthesisError(
                "evidence-bound model inputs do not match the requested lineage"
            )
        if parameter_set["blueprint_identity"] != model_blueprint_identity(blueprint):
            raise QuantitativeModelSynthesisError(
                "approved parameter set belongs to a different model blueprint"
            )
    if revision_context is not None:
        json.dumps(dict(revision_context), ensure_ascii=False, sort_keys=True, allow_nan=False)
    if execution_scenarios is not None:
        json.dumps(execution_scenarios, ensure_ascii=False, sort_keys=True, allow_nan=False)


def _preflight_generated_specification(
    specification: Mapping[str, object],
    *,
    llm_call: Callable[..., object],
) -> None:
    if specification.get("schema_version") != "ieee_math_model_v2":
        return
    document = _execution_document(specification)
    grid = _mapping(document.get("grid"))
    cell_count = int(grid.get("nx", 0)) * int(grid.get("ny", 1)) * int(grid.get("nz", 1))
    configured_limit = getattr(llm_call, "max_synthesis_grid_cells", None)
    if configured_limit is not None and cell_count > int(configured_limit):
        raise QuantitativeModelSynthesisError(
            f"PDE synthesis grid has {cell_count} cells; the first-run limit is {configured_limit}"
        )
    for field_name in ("initial_condition", "initial_velocity"):
        definition = _mapping(document.get(field_name))
        if definition and _text(definition.get("type")) == "SAMPLED_VALUES":
            raise QuantitativeModelSynthesisError(
                f"new PDE models must use a compact {field_name} analytic profile"
            )


def synthesize_quantitative_model(
    *,
    quantitative_idea: Mapping[str, object],
    lineage: Mapping[str, object],
    llm_call: Callable[[str], object],
    model_blueprint: Mapping[str, object] | None = None,
    approved_parameter_set: Mapping[str, object] | None = None,
    revision_context: Mapping[str, object] | None = None,
    execution_scenarios: object = None,
) -> dict[str, Any]:
    """Request, parse, and identify one non-executable mathematical-model draft."""

    if llm_call is None:
        raise QuantitativeModelSynthesisError("a quantitative model LLM callback is required")
    _preflight_synthesis_context(
        lineage=lineage,
        model_blueprint=model_blueprint,
        approved_parameter_set=approved_parameter_set,
        revision_context=revision_context,
        execution_scenarios=execution_scenarios,
    )
    prompt = build_quantitative_model_prompt(
        quantitative_idea=quantitative_idea,
        lineage=lineage,
        model_blueprint=model_blueprint,
        approved_parameter_set=approved_parameter_set,
        revision_context=revision_context,
        execution_scenarios=execution_scenarios,
    )
    _report_synthesis_stage(
        llm_call,
        "quantitative model request started phase=draft prompt_chars=%d idea_id=%s",
        len(prompt),
        _text(lineage.get("quantitative_idea_id")),
    )
    try:
        response = _invoke_model_llm(llm_call, prompt, phase="draft")
    except Exception as exc:
        raise QuantitativeModelSynthesisError(
            f"quantitative model LLM call failed: {type(exc).__name__}: {exc}"
        ) from exc
    _report_synthesis_stage(
        llm_call,
        "quantitative model request completed phase=draft response_chars=%d",
        len(str(response or "")),
    )
    for repair_index in range(3):
        try:
            _report_synthesis_stage(llm_call, "quantitative model parse started attempt=%d", repair_index + 1)
            specification, markdown = parse_quantitative_model_response(response)
            _report_synthesis_stage(
                llm_call,
                "quantitative model contract validation started attempt=%d",
                repair_index + 1,
            )
            _preflight_generated_specification(specification, llm_call=llm_call)
            markdown = _render_markdown_from_specification(specification)
            markdown = _normalize_markdown_abstract_prefix(markdown)
            consistent = validate_json_markdown_consistency(specification, markdown)
            specification = consistent["model_spec"]
            markdown = consistent["markdown"]
            expected_lineage = {key: lineage.get(key) for key in specification["lineage"]}
            if specification["lineage"] != expected_lineage:
                raise QuantitativeModelSynthesisError(
                    "quantitative model lineage differs from the requested version"
                )
            if approved_parameter_set is not None:
                parameter_set_for_check = normalize_approved_parameter_set(approved_parameter_set)
                expected_parameters_for_check = approved_mathir_parameters(parameter_set_for_check)
                actual_parameters_for_check = _execution_document(specification).get("parameters")
                if (
                    not isinstance(actual_parameters_for_check, Mapping)
                    or dict(actual_parameters_for_check) != expected_parameters_for_check
                ):
                    raise QuantitativeModelSynthesisError(
                        "evidence-bound execution parameters must exactly equal the approved parameter set"
                    )
            break
        except QuantitativeModelSynthesisError as contract_error:
            if repair_index >= 2:
                raise QuantitativeModelSynthesisError(
                    f"quantitative model contract repair exhausted after two attempts: {contract_error}"
                ) from contract_error
            current_error = contract_error
            _report_synthesis_stage(
                llm_call,
                "quantitative model repair started attempt=%d error=%s",
                repair_index + 1,
                current_error,
            )
        except JsonMarkdownConsistencyError as contract_error:
            if repair_index >= 2:
                raise QuantitativeModelSynthesisError(
                    f"quantitative model contract repair exhausted after two attempts: {contract_error}"
                ) from contract_error
            current_error = contract_error
            _report_synthesis_stage(
                llm_call,
                "quantitative model repair started attempt=%d error=%s",
                repair_index + 1,
                current_error,
            )
        repair_prompt = "\n".join(
            (
                "Repair a quantitative-model response that failed deterministic contract validation.",
                f"The validator reported this first error: {current_error}",
                "Do not repair only this path. Treat it as a complete contract failure and audit every nested field in the entire execution_ir in one pass.",
                "Rebuild the PDE document against the canonical schema and the full preflight checklist below. Preserve valid scientific content, lineage, approved parameters, and accepted revision intent, but correct every likely structural, semantic, stability, and resource-budget error you find.",
                "Return exactly one <QUANTITATIVE_MODEL_JSON> block and no commentary. Do not return Markdown, a patch, partial JSON, explanation, or code.",
                _MODEL_JSON_SHAPE_GUIDE,
                "Immutable lineage:",
                json.dumps(dict(lineage), ensure_ascii=False, sort_keys=True, allow_nan=False),
                "Exact approved execution parameters:",
                json.dumps(
                    approved_mathir_parameters(normalize_approved_parameter_set(approved_parameter_set))
                    if approved_parameter_set is not None
                    else {},
                    ensure_ascii=False,
                    sort_keys=True,
                    allow_nan=False,
                ),
                "Exact external execution scenarios:",
                json.dumps(execution_scenarios, ensure_ascii=False, sort_keys=True, allow_nan=False),
                "Invalid response to repair:",
                str(response)[:64_000],
            )
        )
        _report_synthesis_stage(
            llm_call,
            "quantitative model request started phase=repair prompt_chars=%d attempt=%d",
            len(repair_prompt),
            repair_index + 1,
        )
        try:
            response = _invoke_model_llm(llm_call, repair_prompt, phase="repair")
        except Exception as repair_call_error:
            raise QuantitativeModelSynthesisError(
                f"quantitative model repair call failed after {current_error}: {type(repair_call_error).__name__}: {repair_call_error}"
            ) from repair_call_error
        _report_synthesis_stage(
            llm_call,
            "quantitative model request completed phase=repair response_chars=%d attempt=%d",
            len(str(response or "")),
            repair_index + 1,
        )
    if model_blueprint is not None or approved_parameter_set is not None:
        try:
            blueprint = normalize_model_blueprint(model_blueprint)
            parameter_set = normalize_approved_parameter_set(approved_parameter_set)
        except ParameterContractError as error:
            raise QuantitativeModelSynthesisError(f"evidence-bound model inputs are invalid: {error}") from error
        if blueprint["lineage"] != specification["lineage"]:
            raise QuantitativeModelSynthesisError("model blueprint lineage differs from the model version")
        if parameter_set["lineage"] != specification["lineage"]:
            raise QuantitativeModelSynthesisError("approved parameter set lineage differs from the model version")
        if parameter_set["blueprint_identity"] != model_blueprint_identity(blueprint):
            raise QuantitativeModelSynthesisError("approved parameter set belongs to a different model blueprint")
        expected_parameters = approved_mathir_parameters(parameter_set)
        actual_parameters = _execution_document(specification).get("parameters")
        if not isinstance(actual_parameters, Mapping) or dict(actual_parameters) != expected_parameters:
            raise QuantitativeModelSynthesisError(
                "evidence-bound execution parameters must exactly equal the approved parameter set"
            )
        specification = normalize_quantitative_model_spec(
            {
                **specification,
                "parameter_provenance": {
                    "mode": "APPROVED_PARAMETER_SET",
                    "parameter_set_identity": parameter_set["parameter_set_identity"],
                    "entries": parameter_evidence_summary(parameter_set),
                },
            }
        )
    return {
        "model_spec": specification,
        "model_spec_identity": model_spec_identity(specification),
        "markdown": markdown,
    }


def build_quantitative_model_llm_call(*, config: Any, model: str | None = None) -> Callable[[str], object]:
    """Create a raw-text LLM transport for the compact JSON model protocol."""

    holder = local()

    def setting(value: Any, key: str, default: Any = "") -> Any:
        if isinstance(value, Mapping):
            return value.get(key, default)
        return getattr(value, key, default)

    def report_stage(message: str, *args: object) -> None:
        formatted = message % args if args else message
        _LOGGER.info(formatted)
        quantitative_config = setting(config, "quantitative_modeling", {})
        if bool(setting(quantitative_config, "progress_to_stderr", True)):
            print(f"[quantitative-model] {formatted}", file=sys.stderr, flush=True)

    def call(prompt: str, *, phase: str = "draft") -> object:
        runtime_config = config
        quantitative_config = setting(runtime_config, "quantitative_modeling", {})
        configured_model = _text(model or setting(quantitative_config, "model"))
        if phase == "repair":
            configured_model = _text(
                setting(quantitative_config, "repair_model", "")
            ) or configured_model
        provider_name = _text(setting(quantitative_config, "provider"))
        if configured_model:
            provider_name = resolve_model(runtime_config, configured_model).provider
        agent = getattr(holder, "agent", None)
        if agent is None:
            from src.agents.idea_agent.agent.base import AgentBase

            agent = AgentBase(config=runtime_config, provider_name=provider_name or None)
            holder.agent = agent
        if not configured_model:
            configured_model = _text(agent.provider.default_models.get("idea_generation"))
        if not configured_model:
            raise QuantitativeModelSynthesisError("no quantitative model LLM is configured")
        model_spec = resolve_model(runtime_config, configured_model, agent.provider.name)
        timeout_value = setting(quantitative_config, "llm_timeout_seconds", 1800)
        try:
            timeout_seconds = max(1.0, float(timeout_value))
        except (TypeError, ValueError):
            timeout_seconds = 1800.0
        token_key = "repair_max_output_tokens" if phase == "repair" else "max_output_tokens"
        default_tokens = 16_000 if phase == "repair" else 24_000
        token_value = setting(quantitative_config, token_key, default_tokens)
        try:
            max_output_tokens = max(256, int(token_value))
        except (TypeError, ValueError):
            max_output_tokens = default_tokens
        max_output_tokens = min(max_output_tokens, int(model_spec.max_output_tokens))
        try:
            max_synthesis_grid_cells = max(
                1, int(setting(quantitative_config, "synthesis_max_grid_cells", 4096))
            )
        except (TypeError, ValueError):
            max_synthesis_grid_cells = 4096
        call.max_synthesis_grid_cells = max_synthesis_grid_cells
        stream_override = os.getenv("QUANTITATIVE_MODELING_STREAM")
        if stream_override is None:
            requested_stream = bool(setting(quantitative_config, "stream", True))
        else:
            requested_stream = stream_override.strip().lower() in {"1", "true", "yes", "on"}
        use_stream = requested_stream and bool(model_spec.capabilities.streaming)
        progress_to_stderr = bool(setting(quantitative_config, "progress_to_stderr", True))
        try:
            progress_interval = max(
                64, int(setting(quantitative_config, "progress_interval_tokens", 256) or 256)
            )
        except (TypeError, ValueError):
            progress_interval = 256
        started = time.monotonic()
        received_chars = 0
        received_tokens = 0
        next_progress = progress_interval

        def progress(message: str, *args: object) -> None:
            formatted = message % args if args else message
            _LOGGER.info(formatted)
            if progress_to_stderr:
                print(f"[quantitative-model] {formatted}", file=sys.stderr, flush=True)

        def on_delta(fragment: str) -> None:
            nonlocal received_chars, received_tokens, next_progress
            received_chars += len(fragment)
            received_tokens += max(1, len(fragment) // 4)
            if received_tokens >= next_progress:
                progress(
                    "phase=%s received_tokens~%d response_chars=%d elapsed=%.1fs",
                    phase,
                    received_tokens,
                    received_chars,
                    time.monotonic() - started,
                )
                next_progress += progress_interval

        progress(
            "request started phase=%s model=%s prompt_chars=%d max_output_tokens=%d stream=%s",
            phase,
            configured_model,
            len(prompt),
            max_output_tokens,
            use_stream,
        )
        response = agent.chat(
            prompt,
            model=configured_model,
            temperature=0.2,
            timeout=timeout_seconds,
            max_output_tokens=max_output_tokens,
            stream=use_stream,
            stream_callback=on_delta if use_stream else None,
        )
        progress(
            "request completed phase=%s model=%s response_chars=%d elapsed=%.1fs",
            phase,
            configured_model,
            len(str(response or "")),
            time.monotonic() - started,
        )
        return response

    call.supports_phase = True
    call.report_stage = report_stage
    return call


__all__ = [
    "QuantitativeModelSynthesisError",
    "build_quantitative_model_llm_call",
    "build_quantitative_model_prompt",
    "parse_quantitative_model_response",
    "synthesize_quantitative_model",
]
