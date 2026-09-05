"""LLM synthesis of a non-numeric quantitative model blueprint.

The blueprint deliberately precedes the executable model specification.  It
states which parameters a solver will need, why they are needed, and how they
must be evidenced, but cannot itself introduce numerical parameter values.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping
from typing import Any

from src.agents.quantitative_modeling.parameter_contracts import (
    ParameterContractError,
    SUPPORTED_MODEL_FORMS,
    normalize_model_blueprint,
)
from src.agents.quantitative_modeling.pde_capability_registry import PDE_CAPABILITIES, executable_pde_catalog


_BLUEPRINT_RESPONSE = re.compile(
    r"\A\s*<QUANTITATIVE_MODEL_BLUEPRINT_JSON>\s*(?P<json>\{.*?\})\s*"
    r"</QUANTITATIVE_MODEL_BLUEPRINT_JSON>\s*\Z",
    re.DOTALL,
)
_MODEL_FORM_ENUM_TEXT = ", ".join(SUPPORTED_MODEL_FORMS[:-1]) + ", or " + SUPPORTED_MODEL_FORMS[-1]
_NON_PDE_MODEL_FORMS = frozenset({"ODE", "OPTIMIZATION", "MONTE_CARLO", "UNSPECIFIED"})


class QuantitativeModelBlueprintError(RuntimeError):
    """Raised when a pre-materialization model blueprint is malformed."""


def _bounded_json(value: Mapping[str, object], *, maximum: int = 16_000) -> str:
    encoded = json.dumps(dict(value), ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
    return encoded[:maximum]


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _bounded_response_text(value: object, *, maximum: int = 40_000) -> str:
    if isinstance(value, Mapping):
        return _bounded_json(value, maximum=maximum)
    return str(value or "")[:maximum]


def build_quantitative_model_blueprint_prompt(
    *,
    quantitative_idea: Mapping[str, object],
    lineage: Mapping[str, object],
    revision_context: Mapping[str, object] | None = None,
) -> str:
    """Build the contract-first request for a Q1/Q2 model blueprint."""

    return "\n".join(
        (
            "You are designing the parameter contract for a scientific mathematical model.",
            "Return exactly one JSON block and no text before or after it:",
            "<QUANTITATIVE_MODEL_BLUEPRINT_JSON>",
            "{...}",
            "</QUANTITATIVE_MODEL_BLUEPRINT_JSON>",
            "Do not return Python, shell commands, notebooks, URLs, file paths, code fences, formulas encoded as executable strings,",
            "numerical parameter values, numerical ranges, or inferred literature facts.",
            "Use schema_version quantitative_model_blueprint_v1. Copy the supplied lineage exactly (excluding any topic helper field).",
            "Include title, scientific_question, model_scope, symbolic_model_intent, model_form, pde_family, spatial_dimension,",
            f"model_form must be exactly one of {_MODEL_FORM_ENUM_TEXT}. Use PDE for a registered PDE family,",
            "ODE for ODE_IVP, OPTIMIZATION for LINEAR_OPTIMIZATION, and MONTE_CARLO for MONTE_CARLO; use UNSPECIFIED only when no executable form is determined.",
            "For ODE, OPTIMIZATION, and MONTE_CARLO, spatial_dimension must be null or omitted; never use 0.",
            "For PDE, spatial_dimension must be exactly 1, 2, or 3 and must match the selected PDE family.",
            "required_operators, required_boundary_types, required_solver_features, permitted_system_types, parameter_requests,",
            "symbolic_constraints, and revision_context. Permitted system types may only be ODE_IVP, LINEAR_OPTIMIZATION, MONTE_CARLO,",
            "or DIFFUSION_REACTION_1D. PDE system types may additionally be selected from the registered PDE capability catalog: "
            + ", ".join(sorted(PDE_CAPABILITIES))
            + ". Each parameter_request needs parameter_id, mathir_symbol, meaning, unit, dimension, role,",
            "Executable PDE catalog (system_type, dimensions, boundary types, and integrators): "
            + json.dumps(executable_pde_catalog(), sort_keys=True)
            + ". A design-only catalog entry may be documented but cannot be materialized or executed.",
            "value_kind=SCALAR, evidence_requirement, required_conditions, and retrieval_queries. Roles are MATERIAL_PROPERTY,",
            "SCENARIO_INPUT, BOUNDARY_CONDITION, or MODEL_ASSUMPTION. Evidence requirements are LITERATURE_REQUIRED,",
            "LITERATURE_PREFERRED, USER_OR_LITERATURE, or MODEL_ASSUMPTION_ALLOWED.",
            "Use the retrieval queries to find measurement or reference-database evidence under the stated material, geometry, temperature,",
            "pressure, composition, and boundary conditions. A parameter required for numerical execution must be requested explicitly.",
            "Keep the first executable model parsimonious: use no more than 12 parameter_requests, and no more than 6 requests may require",
            "literature or user evidence. Do not request equivalent state descriptions or separately request a quantity that the declared",
            "symbolic model can derive from other requested inputs. Numerical controls and scenario switches should use",
            "MODEL_ASSUMPTION_ALLOWED when that classification is scientifically honest.",
            "For every parameter_request, unit must be a concrete source-compatible physical unit token such as s, K, T, rad_s^-1,",
            "kg_m^-3, solar_mass, or kg_m^2. Never use a semantic dimension name such as time, mass_length_squared,",
            "magnetic_flux_density, or time_inverse as the unit; put dimensional semantics in dimension instead.",
            "A model assumption must be explicit and must never be represented as a literature value.",
            "Quantitative idea:",
            _bounded_json(quantitative_idea),
            "Immutable lineage to copy exactly:",
            _bounded_json(lineage),
            "Accepted revision context to copy exactly (empty object for v0):",
            _bounded_json(_mapping(revision_context)),
        )
    )


def build_quantitative_model_blueprint_repair_prompt(
    *,
    original_response: object,
    validation_error: str,
) -> str:
    """Create one structural-only repair request for a rejected blueprint."""

    return "\n".join(
        (
            "Repair the JSON blueprint below so it satisfies the quantitative model blueprint contract.",
            "Return exactly one tagged JSON block and no prose, equations, code, commands, or new scientific claims:",
            "<QUANTITATIVE_MODEL_BLUEPRINT_JSON>{...}</QUANTITATIVE_MODEL_BLUEPRINT_JSON>",
            "Preserve every scientific statement, identifier, value, lineage field, and revision context.",
            f"Change structure only, except that an unsupported model_form may be normalized to exactly one of {_MODEL_FORM_ENUM_TEXT}.",
            "Use PDE for a registered PDE family, ODE for ODE_IVP, OPTIMIZATION for LINEAR_OPTIMIZATION, and MONTE_CARLO for MONTE_CARLO.",
            "For a non-PDE model with no pde_family, normalize a zero spatial_dimension placeholder to null; never use 0 for a PDE.",
            "For PDE, spatial_dimension must be exactly 1, 2, or 3 and match the selected PDE family.",
            "permitted_system_types and symbolic_constraints must be arrays of text values.",
            "parameter_requests must be an array of objects. Each request's required_conditions and retrieval_queries",
            "must be arrays of text values; if a value is a single string, wrap it in a one-element array.",
            "Do not add numerical values, sources, equations, parameters, requests, or system types.",
            f"Validator error: {validation_error}",
            "Rejected blueprint JSON:",
            _bounded_response_text(original_response),
        )
    )


def parse_quantitative_model_blueprint_response(value: object) -> dict[str, Any]:
    """Parse and validate the single non-executable blueprint JSON block."""

    if not isinstance(value, str):
        raise QuantitativeModelBlueprintError("quantitative model blueprint response must be text")
    match = _BLUEPRINT_RESPONSE.fullmatch(value)
    if match is None:
        raise QuantitativeModelBlueprintError("response must contain exactly one quantitative model blueprint JSON block")
    try:
        raw = json.loads(match.group("json"))
    except json.JSONDecodeError as error:
        raise QuantitativeModelBlueprintError("quantitative model blueprint JSON is invalid") from error
    if not isinstance(raw, Mapping):
        raise QuantitativeModelBlueprintError("quantitative model blueprint JSON must be an object")
    raw = dict(raw)
    model_form = str(raw.get("model_form") or "UNSPECIFIED").strip()
    pde_family = str(raw.get("pde_family") or "").strip()
    spatial_dimension = raw.get("spatial_dimension")
    zero_dimension_placeholder = (
        (isinstance(spatial_dimension, (int, float)) and not isinstance(spatial_dimension, bool) and spatial_dimension == 0)
        or (isinstance(spatial_dimension, str) and spatial_dimension.strip() in {"0", "0.0"})
    )
    if model_form in _NON_PDE_MODEL_FORMS and not pde_family and zero_dimension_placeholder:
        raw["spatial_dimension"] = None
    try:
        return normalize_model_blueprint(raw)
    except ParameterContractError as error:
        raise QuantitativeModelBlueprintError(f"quantitative model blueprint is invalid: {error}") from error


def synthesize_quantitative_model_blueprint(
    *,
    quantitative_idea: Mapping[str, object],
    lineage: Mapping[str, object],
    revision_context: Mapping[str, object] | None,
    llm_call: Callable[[str], object],
) -> dict[str, Any]:
    """Request a deterministic-shaped parameter contract before model materialization."""

    if llm_call is None:
        raise QuantitativeModelBlueprintError("a quantitative model blueprint LLM callback is required")
    expected_revision_context = _mapping(revision_context)
    try:
        response = llm_call(
            build_quantitative_model_blueprint_prompt(
                quantitative_idea=quantitative_idea,
                lineage=lineage,
                revision_context=expected_revision_context,
            )
        )
    except Exception as error:
        raise QuantitativeModelBlueprintError(
            f"quantitative model blueprint LLM call failed: {type(error).__name__}: {error}"
        ) from error
    try:
        blueprint = parse_quantitative_model_blueprint_response(response)
    except QuantitativeModelBlueprintError as error:
        try:
            repaired_response = llm_call(
                build_quantitative_model_blueprint_repair_prompt(
                    original_response=response,
                    validation_error=str(error),
                )
            )
            blueprint = parse_quantitative_model_blueprint_response(repaired_response)
        except Exception as repair_error:
            if isinstance(repair_error, QuantitativeModelBlueprintError):
                raise repair_error from error
            raise QuantitativeModelBlueprintError(
                f"quantitative model blueprint structural repair failed: {type(repair_error).__name__}: {repair_error}"
            ) from error
    expected_lineage = {field: lineage.get(field) for field in blueprint["lineage"]}
    if blueprint["lineage"] != expected_lineage:
        raise QuantitativeModelBlueprintError("quantitative model blueprint lineage differs from the requested version")
    if blueprint["revision_context"] != expected_revision_context:
        raise QuantitativeModelBlueprintError("quantitative model blueprint revision_context differs from acceptance")
    return blueprint


__all__ = [
    "QuantitativeModelBlueprintError",
    "build_quantitative_model_blueprint_prompt",
    "build_quantitative_model_blueprint_repair_prompt",
    "parse_quantitative_model_blueprint_response",
    "synthesize_quantitative_model_blueprint",
]
