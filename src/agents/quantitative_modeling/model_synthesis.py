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
from src.agents.quantitative_modeling.parameter_evidence.extraction import (
    PARAMETER_EVIDENCE_RESPONSE_SCHEMA,
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
_FENCED_JSON_BLOCK_RESPONSE = re.compile(
    r"\A\s*```(?:json)?\s*<QUANTITATIVE_MODEL_JSON>\s*(?P<json>\{.*?\})\s*"
    r"</QUANTITATIVE_MODEL_JSON>\s*```\s*\Z",
    re.DOTALL | re.IGNORECASE,
)
_LOGGER = logging.getLogger(__name__)

_MODEL_JSON_COMMON_GUIDE = """Common JSON contract for every executable model:
- assumptions is a non-empty array of objects with assumption_id, statement, and effect_if_violated.
- symbols is an array, never an object, and it must be non-empty. Every symbol item has symbol_id, latex, meaning, unit, dimension, and role.
- equations is a non-empty array of objects with equation_id, role, latex, and where_symbol_ids (a non-empty array of declared symbol_id values).
- parameterization, validation_plan, and limitations are non-empty arrays of strings; references is an array and may be empty when no external source is declared. The family section below controls whether initial_conditions, boundary_conditions, scenarios, and objective_and_constraints may be empty.
- algorithm is an object with non-empty input, output, and steps arrays. numerical_plan is an object with solver_family, discretization, and non-empty convergence_checks.
- All scalar numeric values must be finite JSON numbers. Do not use unit-bearing strings, symbolic placeholders, arrays, or {\"value\": ...} wrappers for scalar fields.
- IDs and AST variable names must be safe ASCII identifiers matching [A-Za-z_][A-Za-z0-9_]{0,63}. mathir.system_type is exactly one string, never an array or hybrid.
- v1 models use a valid MathIR object with the exact nested key-value \"schema_version\": \"mathir_v1\". v2 models use an execution_ir object with schema_version \"execution_ir_v1\". Keep the selected model family in its own section below; do not emit fields from another family.
- Before emitting JSON, audit required fields, AST arities and names, finite values, resource limits, and the family-specific rules below."""

_MODEL_FAMILY_GUIDES = {
    "ODE": """Selected family: ODE (legacy MathIR v1).
- mathir.system_type must be exactly \"ODE_IVP\" (for example, {\"system_type\":\"ODE_IVP\"}). states must be a non-empty list of unique safe IDs with finite initial values; derivatives must define exactly one AST per state; parameters is a finite numeric object; time_span must increase.
- solver_options.max_step must be positive and ceil((time_span[1]-time_span[0])/max_step)+1 must be at most 2000. MathIR expressions may reference only t, declared states, and declared parameters.
- initial_conditions must describe the state initialization. boundary_conditions may be an empty list because ODE_IVP has no spatial boundary. scenarios must be non-empty when external scenario comparison is requested; scenario overrides must affect a derivative or state initialization, and narrative-only scenario differences are forbidden. do not leave compared scenarios mathematically identical.
- Do not emit PDE grids, fields, spatial domains, PDE boundary maps, Monte Carlo samples, or optimization variables.""",
    "OPTIMIZATION": """Selected family: linear optimization (legacy MathIR v1).
- mathir.system_type must be exactly \"LINEAR_OPTIMIZATION\". variables must be a non-empty list of unique safe IDs with finite objective_coefficient, lower, and upper values and upper >= lower; constraints is a list that may be empty, with declared-variable coefficients and sense <=, >=, or ==; objective_sense is minimize or maximize. An optional finite parameters object may carry evidence-bound values, but executable objective/bound/constraint values must still be numeric literals.
- initial_conditions and boundary_conditions may be empty lists because a linear program has no time or spatial state. scenarios may be empty for a single baseline optimization; do not invent derivative, trajectory, or spatial-boundary requirements.
- Do not emit ODE states/time_span, PDE fields/grids, or Monte Carlo random_variables/samples. Scenario differences must be represented through objective coefficients, bounds, or constraints; the current runner does not apply parameter overrides to optimization variables.""",
    "MONTE_CARLO": """Selected family: Monte Carlo sampling (legacy MathIR v1).
- mathir.system_type must be exactly \"MONTE_CARLO\"; mathir.samples must be a JSON integer from 1 through 100000, mathir.seed must be an integer, mathir.random_variables must be a non-empty list, and mathir.observable must be a valid AST over those variables.
- Every random_variables[].id and every AST variable.name must be an ASCII identifier matching [A-Za-z_][A-Za-z0-9_]{0,63}; use names such as \"tau_f\" rather than Greek letters, spaces, hyphens, subscripts, or unit-bearing labels. Uniform variables require finite low < high; normal variables require finite mean and positive stddev.
- initial_conditions, boundary_conditions, and objective_and_constraints may be empty lists because this is a zero-dimensional sampler. scenarios may be empty for a single baseline sample; do not require ODE derivatives, state initialization, PDE boundaries, or spatial grids. If explanatory text is supplied, state that no spatial boundary conditions apply to the zero-dimensional sampler. The execution document may carry a finite parameters object for evidence binding; scenario overrides may target those parameters only when the observable uses them, never a derivative or state.
- Do not emit ODE states/time_span, PDE execution_ir, or optimization variables/constraints.""",
    "PDE": """Selected family: registered PDE execution (execution_ir v1).
- execution_ir must have exactly {\"kind\":\"PDE\",\"schema_version\":\"execution_ir_v1\",\"document\":{\"schema_version\":\"pdeir_v1\",...}}. document.system_type must be one exact registered EXECUTABLE key from the catalog below with matching spatial_dimension; never emit a design-only family, a hybrid, or an unregistered solver.
- fields must contain exactly one field with a safe id matching every field AST leaf. parameters is a finite numeric object with safe names. spatial_domain is direct coordinate-to-two-number intervals: x for 1D, x/y for 2D, x/y/z for 3D, with increasing bounds. grid is direct integer sizes: 1D nx 3..4096, 2D nx/ny 3..1024, and 3D nx/ny/nz 3..128; total cells must remain within the authorized resource limit.
- discretization must use a registered method, grid_type UNIFORM, and space_order 1 or 2. Temporal PDEs require increasing time_span, positive time_step, a registered integrator, and initial_condition. Initial conditions may use SAMPLED_VALUES with exactly one finite value per grid cell or a compact ANALYTIC_PROFILE (UNIFORM, GAUSSIAN, or ANALYTIC_EXPRESSION); do not use nested arrays, ellipses, repetition instructions, formula strings, Python, or code.
- Wave PDEs also require initial_velocity. Steady elliptic/Poisson/Helmholtz PDEs must not contain temporal fields or initial conditions. Boundary conditions are required on every registered side and must use family-approved types; periodic conditions must form complete opposing pairs. PDE AST values use only registered operators and may not contain equation strings, derivatives, Laplacian calls, Python, or dynamic functions.
- Respect family-required PDE fields, positivity, finite-field checks, explicit stability margins, time steps <= 20000, and total cells <= 100000. The executable PDE catalog is: """ + json.dumps(executable_pde_catalog(), sort_keys=True) + """.
- initial_conditions must describe the temporal PDE setup and may be empty for a steady elliptic/Poisson/Helmholtz solve. boundary_conditions must describe the PDE setup; scenarios may be empty for a single baseline solve. Scenario overrides must affect PDE parameters, initial-condition expressions, or boundary values; do not require ODE derivative/state wording.""",
}


def _model_family_from_context(
    quantitative_idea: Mapping[str, object],
    model_blueprint: Mapping[str, object] | None,
) -> str | None:
    candidates: list[object] = []
    if model_blueprint is not None:
        candidates.extend(
            [
                model_blueprint.get("model_form"),
                model_blueprint.get("pde_family"),
                model_blueprint.get("system_type"),
                model_blueprint.get("model_family"),
            ]
        )
        permitted = model_blueprint.get("permitted_system_types")
        if isinstance(permitted, (list, tuple, set)) and len(permitted) == 1:
            candidates.append(next(iter(permitted)))
    candidates.extend(
        [
            quantitative_idea.get("model_form"),
            quantitative_idea.get("model_family"),
            quantitative_idea.get("system_type"),
            quantitative_idea.get("pde_family"),
            quantitative_idea.get("provisional_solver_family"),
        ]
    )
    pde_system_types = {item["system_type"] for item in executable_pde_catalog()}
    for candidate in candidates:
        value = _text(candidate).upper()
        if value in {"ODE", "ODE_IVP"}:
            return "ODE"
        if value in {"OPTIMIZATION", "LINEAR_OPTIMIZATION"}:
            return "OPTIMIZATION"
        if value in {"MONTE_CARLO", "MONTE CARLO"}:
            return "MONTE_CARLO"
        if value == "PDE" or value in pde_system_types:
            return "PDE"
        if "MONTE_CARLO" in value or "MONTE CARLO" in value:
            return "MONTE_CARLO"
        if "OPTIM" in value or "LINPROG" in value:
            return "OPTIMIZATION"
        if "ODE" in value or "SOLVE_IVP" in value:
            return "ODE"
        if value.startswith(("FINITE_DIFFERENCE", "FDM")) or "DIFFUSION" in value:
            return "PDE"
    return None


def _model_family_guidance(
    quantitative_idea: Mapping[str, object],
    model_blueprint: Mapping[str, object] | None,
) -> str:
    family = _model_family_from_context(quantitative_idea, model_blueprint)
    if family is not None:
        return _MODEL_FAMILY_GUIDES[family]
    return "\n\n".join(
        [
            "Model-family routing: select exactly one executable family from ODE, OPTIMIZATION, MONTE_CARLO, or PDE, then follow only its corresponding section below.",
            *_MODEL_FAMILY_GUIDES.values(),
        ]
    )


def _scenario_guidance(
    quantitative_idea: Mapping[str, object],
    model_blueprint: Mapping[str, object] | None,
) -> str:
    family = _model_family_from_context(quantitative_idea, model_blueprint)
    if family == "ODE":
        return "Every scenario override must affect an ODE derivative or state initialization; narrative-only scenario differences are forbidden."
    if family == "PDE":
        return "Every scenario override must affect a PDE parameter, initial-condition expression, or boundary value; narrative-only scenario differences are forbidden."
    if family == "OPTIMIZATION":
        return "Use a single baseline scenario with no parameter_overrides unless the optimization variables are materialized separately; do not claim trajectory effects."
    if family == "MONTE_CARLO":
        return "Monte Carlo scenario overrides may target declared parameters when the observable uses them; do not claim derivative or state effects, and do not use narrative-only overrides."
    return "Every scenario override must affect the selected execution document; narrative-only scenario differences are forbidden."


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
            "and either a safe MathIR object or a safe execution_ir object. Select exactly one executable family and follow only that family's rules below.",
            _MODEL_JSON_COMMON_GUIDE,
            _model_family_guidance(quantitative_idea, model_blueprint),
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
        model_family = _model_family_from_context(quantitative_idea, normalized_blueprint)
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
        if pulsar_recycling_parameters <= parameter_ids and model_family in {None, "ODE"}:
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
        if pulsar_thermal_parameters <= parameter_ids and model_family in {None, "ODE"}:
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
                _scenario_guidance(quantitative_idea, model_blueprint),
                "Preserve the blueprint's physical sign conventions and mechanism directions in the executable representation.",
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
            match = _FENCED_JSON_BLOCK_RESPONSE.fullmatch(value)
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


def _response_format_unsupported(error: Exception) -> bool:
    message = str(error or "").casefold()
    return (
        ("response_format" in message or "json_schema" in message)
        and any(
            marker in message
            for marker in (
                "not supported",
                "unsupported",
                "unknown parameter",
                "unrecognized parameter",
                "invalid parameter",
                "only support",
                "must be json_object",
            )
        )
    )


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
    for repair_index in range(4):
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
            if repair_index >= 3:
                raise QuantitativeModelSynthesisError(
                    f"quantitative model contract repair exhausted after three attempts: {contract_error}"
                ) from contract_error
            current_error = contract_error
            _report_synthesis_stage(
                llm_call,
                "quantitative model repair started attempt=%d error=%s",
                repair_index + 1,
                current_error,
            )
        except JsonMarkdownConsistencyError as contract_error:
            if repair_index >= 3:
                raise QuantitativeModelSynthesisError(
                    f"quantitative model contract repair exhausted after three attempts: {contract_error}"
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
                "Do not repair only this path. Treat it as a complete contract failure and audit every nested field in the model specification and its execution document in one pass.",
                "Rebuild the execution document and the complete quantitative model specification against the canonical schema and the full preflight checklist below. Preserve valid scientific content, lineage, approved parameters, and accepted revision intent, and preserve the selected executable model family whether it is PDE, ODE, OPTIMIZATION, or MONTE_CARLO. Correct every likely structural, semantic, stability, and resource-budget error you find.",
                "Return exactly one <QUANTITATIVE_MODEL_JSON> block and no commentary. Do not return Markdown, a patch, partial JSON, explanation, or code.",
                _MODEL_JSON_COMMON_GUIDE,
                _model_family_guidance(quantitative_idea, model_blueprint),
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
                _scenario_guidance(quantitative_idea, model_blueprint),
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

    def call(
        prompt: str,
        *,
        phase: str = "draft",
        parameter_count: int | None = None,
    ) -> object:
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
        call.agent = agent
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
        if phase == "parameter_extraction":
            token_key = "parameter_evidence.extraction_max_output_tokens"
            default_tokens = 1_200
        else:
            token_key = "repair_max_output_tokens" if phase == "repair" else "max_output_tokens"
            default_tokens = 16_000 if phase == "repair" else 24_000
        if "." in token_key:
            section_name, nested_key = token_key.split(".", 1)
            token_value = setting(setting(quantitative_config, section_name, {}), nested_key, default_tokens)
        else:
            token_value = setting(quantitative_config, token_key, default_tokens)
        try:
            max_output_tokens = max(256, int(token_value))
        except (TypeError, ValueError):
            max_output_tokens = default_tokens
        if phase == "parameter_extraction" and parameter_count is not None:
            dynamic_limit = min(2_048, 512 + 256 * max(1, int(parameter_count)))
            max_output_tokens = min(max_output_tokens, dynamic_limit)
        max_output_tokens = min(max_output_tokens, int(model_spec.max_output_tokens))
        try:
            max_synthesis_grid_cells = max(
                1, int(setting(quantitative_config, "synthesis_max_grid_cells", 100_000))
            )
        except (TypeError, ValueError):
            max_synthesis_grid_cells = 4096
        call.max_synthesis_grid_cells = max_synthesis_grid_cells
        stream_override = os.getenv("QUANTITATIVE_MODELING_STREAM")
        if phase == "parameter_extraction":
            extraction_config = setting(quantitative_config, "parameter_evidence", {})
            requested_stream = bool(setting(extraction_config, "extraction_stream", False))
        elif stream_override is None:
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
        if phase == "parameter_extraction":
            extraction_config = setting(quantitative_config, "parameter_evidence", {})
            try:
                temperature = float(setting(extraction_config, "extraction_temperature", 0.0))
            except (TypeError, ValueError):
                temperature = 0.0
        else:
            temperature = 0.2
        request_kwargs: dict[str, object] = {
            "model": configured_model,
            "temperature": max(0.0, min(2.0, temperature)),
            "timeout": timeout_seconds,
            "max_output_tokens": max_output_tokens,
            "stream": use_stream,
            "stream_callback": on_delta if use_stream else None,
        }
        native_json_schema = False
        if phase == "parameter_extraction":
            capabilities = model_spec.capabilities
            if bool(getattr(capabilities, "json_schema", False)):
                request_kwargs["response_format"] = {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "quantitative_parameter_evidence",
                        "strict": True,
                        "schema": PARAMETER_EVIDENCE_RESPONSE_SCHEMA,
                    },
                }
                native_json_schema = True
            elif bool(getattr(capabilities, "json_object", False)):
                request_kwargs["response_format"] = {"type": "json_object"}
            call.supports_plain_json_response = "response_format" in request_kwargs
        try:
            response = agent.chat(prompt, **request_kwargs)
        except Exception as error:
            if not (native_json_schema and _response_format_unsupported(error)):
                raise
            request_kwargs["response_format"] = {"type": "json_object"}
            call.supports_plain_json_response = True
            response = agent.chat(prompt, **request_kwargs)
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
    configured_quantitative = setting(config, "quantitative_modeling", {})
    call.cache_identity = _text(model or setting(configured_quantitative, "model")) or "configured-default"
    return call


__all__ = [
    "QuantitativeModelSynthesisError",
    "build_quantitative_model_llm_call",
    "build_quantitative_model_prompt",
    "parse_quantitative_model_response",
    "synthesize_quantitative_model",
]
