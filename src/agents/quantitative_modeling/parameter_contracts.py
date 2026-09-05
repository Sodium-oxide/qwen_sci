"""Validated provenance contracts for quantitative-model parameter evidence."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping, Sequence
from typing import Any

from src.agents.quantitative_modeling.pde_capability_registry import PDE_CAPABILITIES


MODEL_BLUEPRINT_SCHEMA_VERSION = "quantitative_model_blueprint_v1"
PARAMETER_QUERY_PLAN_SCHEMA_VERSION = "quantitative_parameter_query_plan_v1"
PARAMETER_DISCOVERY_SCHEMA_VERSION = "quantitative_parameter_discovery_v1"
PARAMETER_EVIDENCE_COLLECTION_SCHEMA_VERSION = "quantitative_parameter_evidence_collection_v1"
PARAMETER_RESOLUTION_PROPOSAL_SCHEMA_VERSION = "quantitative_parameter_resolution_proposal_v1"
APPROVED_PARAMETER_SET_SCHEMA_VERSION = "quantitative_approved_parameter_set_v1"

_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,63}")
_QUANTITATIVE_ID = re.compile(r"Q[1-2]")
_CANDIDATE_ID = re.compile(r"PEC-Q[1-2]-[A-Za-z_][A-Za-z0-9_]{0,63}-\d{3}")
_REQUEST_ROLES = frozenset(
    {"MATERIAL_PROPERTY", "SCENARIO_INPUT", "BOUNDARY_CONDITION", "MODEL_ASSUMPTION"}
)
_VALUE_KINDS = frozenset({"SCALAR"})
_PERMITTED_SYSTEM_TYPES = frozenset(
    {
        "ODE_IVP",
        "LINEAR_OPTIMIZATION",
        "MONTE_CARLO",
    }
) | frozenset(PDE_CAPABILITIES)
SUPPORTED_MODEL_FORMS = ("PDE", "ODE", "OPTIMIZATION", "MONTE_CARLO", "UNSPECIFIED")
_EVIDENCE_REQUIREMENTS = frozenset(
    {"LITERATURE_REQUIRED", "LITERATURE_PREFERRED", "USER_OR_LITERATURE", "MODEL_ASSUMPTION_ALLOWED"}
)
_CANDIDATE_STATUSES = frozenset({"EXTRACTED_FULLTEXT", "USER_PROVIDED"})
_SOURCE_KINDS = frozenset(
    {"PRIMARY_MEASUREMENT", "REFERENCE_DATABASE", "REVIEW_REPORTED", "USER_PROVIDED"}
)
_PROVENANCE_STATUSES = frozenset(
    {
        "APPROVED_LITERATURE_SINGLE_SOURCE",
        "APPROVED_COMPATIBLE_CONSENSUS",
        "APPROVED_USER_INPUT",
        "APPROVED_MODEL_ASSUMPTION",
    }
)


class ParameterContractError(ValueError):
    """Raised when a parameter provenance record is incomplete or unsafe."""


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _text(value: object) -> str:
    return str(value or "").strip()


def _required_text(payload: Mapping[str, object], field: str) -> str:
    result = _text(payload.get(field))
    if not result:
        raise ParameterContractError(f"{field} is required")
    return result


def _number(value: object, *, field: str) -> float:
    if isinstance(value, bool):
        raise ParameterContractError(f"{field} must be numeric")
    try:
        result = float(value)
    except (TypeError, ValueError) as error:
        raise ParameterContractError(f"{field} must be numeric") from error
    if not math.isfinite(result):
        raise ParameterContractError(f"{field} must be finite")
    return result


def _optional_int(value: object, *, field: str, minimum: int = 0) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise ParameterContractError(f"{field} must be an integer or null")
    try:
        result = int(value)
    except (TypeError, ValueError) as error:
        raise ParameterContractError(f"{field} must be an integer or null") from error
    if result < minimum:
        raise ParameterContractError(f"{field} must be at least {minimum}")
    return result


def _text_list(value: object, *, field: str, allow_empty: bool = False) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise ParameterContractError(f"{field} must be a list")
    result = [_text(item) for item in value]
    if any(not item for item in result):
        raise ParameterContractError(f"{field} cannot contain empty text")
    if not allow_empty and not result:
        raise ParameterContractError(f"{field} must not be empty")
    return list(dict.fromkeys(result))


def _identifier(value: object, *, field: str) -> str:
    result = _text(value)
    if not _IDENTIFIER.fullmatch(result):
        raise ParameterContractError(f"{field} must be a safe identifier")
    return result


def _json_identity(value: Mapping[str, object]) -> str:
    serialized = json.dumps(dict(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _normalize_lineage(value: object) -> dict[str, Any]:
    lineage = _mapping(value)
    required = (
        "science_run_id",
        "survey_run_id",
        "project_id",
        "project_context_fingerprint",
        "selected_direction_id",
        "quantitative_idea_id",
        "created_from_artifact",
    )
    normalized = {field: _required_text(lineage, field) for field in required}
    if not _QUANTITATIVE_ID.fullmatch(normalized["quantitative_idea_id"]):
        raise ParameterContractError("lineage.quantitative_idea_id must be Q1 or Q2")
    version_raw = lineage.get("version")
    if isinstance(version_raw, bool):
        raise ParameterContractError("lineage.version must be an integer")
    try:
        version = int(version_raw)
    except (TypeError, ValueError) as error:
        raise ParameterContractError("lineage.version must be an integer") from error
    if version not in {0, 1, 2}:
        raise ParameterContractError("lineage.version must be v0, v1, or v2")
    parent_raw = lineage.get("parent_version")
    if parent_raw is None:
        parent_version: int | None = None
    else:
        if isinstance(parent_raw, bool):
            raise ParameterContractError("lineage.parent_version must be an integer or null")
        try:
            parent_version = int(parent_raw)
        except (TypeError, ValueError) as error:
            raise ParameterContractError("lineage.parent_version must be an integer or null") from error
    if version == 0 and parent_version is not None:
        raise ParameterContractError("v0 must not have a parent version")
    if version > 0 and parent_version != version - 1:
        raise ParameterContractError("each parameter revision must directly descend from its prior version")
    return {**normalized, "version": version, "parent_version": parent_version}


def _normalize_conditions(value: object, *, field: str) -> dict[str, str | float | bool | None]:
    payload = _mapping(value)
    conditions: dict[str, str | float | bool | None] = {}
    for raw_key, raw_value in payload.items():
        key = _identifier(raw_key, field=f"{field} key")
        if isinstance(raw_value, bool) or raw_value is None:
            conditions[key] = raw_value
        elif isinstance(raw_value, (int, float)):
            conditions[key] = _number(raw_value, field=f"{field}.{key}")
        else:
            text_value = _text(raw_value)
            if not text_value:
                raise ParameterContractError(f"{field}.{key} must be non-empty when text")
            conditions[key] = text_value
    return conditions


def _normalize_parameter_request(value: object, *, index: int) -> dict[str, Any]:
    payload = _mapping(value)
    parameter_id = _identifier(payload.get("parameter_id"), field=f"parameter_requests[{index}].parameter_id")
    mathir_symbol = _identifier(payload.get("mathir_symbol"), field=f"parameter_requests[{index}].mathir_symbol")
    role = _required_text(payload, "role")
    if role not in _REQUEST_ROLES:
        raise ParameterContractError("parameter request role is unsupported")
    value_kind = _required_text(payload, "value_kind")
    if value_kind not in _VALUE_KINDS:
        raise ParameterContractError("parameter request value_kind is unsupported")
    evidence_requirement = _required_text(payload, "evidence_requirement")
    if evidence_requirement not in _EVIDENCE_REQUIREMENTS:
        raise ParameterContractError("parameter request evidence_requirement is unsupported")
    queries = _text_list(payload.get("retrieval_queries", []), field=f"{parameter_id}.retrieval_queries", allow_empty=True)
    if role == "MATERIAL_PROPERTY" and evidence_requirement != "MODEL_ASSUMPTION_ALLOWED" and not queries:
        raise ParameterContractError("literature-oriented material parameters require at least one retrieval query")
    return {
        "parameter_id": parameter_id,
        "mathir_symbol": mathir_symbol,
        "meaning": _required_text(payload, "meaning"),
        "unit": _required_text(payload, "unit"),
        "dimension": _required_text(payload, "dimension"),
        "role": role,
        "value_kind": value_kind,
        "evidence_requirement": evidence_requirement,
        "required_conditions": _text_list(
            payload.get("required_conditions", []), field=f"{parameter_id}.required_conditions", allow_empty=True
        ),
        "retrieval_queries": queries,
    }


def normalize_model_blueprint(value: object) -> dict[str, Any]:
    """Validate the non-executable parameter contract emitted before model materialization."""

    payload = _mapping(value)
    if _text(payload.get("schema_version")) != MODEL_BLUEPRINT_SCHEMA_VERSION:
        raise ParameterContractError("unsupported quantitative model blueprint schema")
    lineage = _normalize_lineage(payload.get("lineage"))
    raw_requests = payload.get("parameter_requests")
    if not isinstance(raw_requests, Sequence) or isinstance(raw_requests, (str, bytes, bytearray)):
        raise ParameterContractError("parameter_requests must be a list")
    requests = [_normalize_parameter_request(item, index=index) for index, item in enumerate(raw_requests)]
    if not requests:
        raise ParameterContractError("parameter_requests must not be empty")
    parameter_ids = [item["parameter_id"] for item in requests]
    mathir_symbols = [item["mathir_symbol"] for item in requests]
    if len(parameter_ids) != len(set(parameter_ids)):
        raise ParameterContractError("parameter request IDs must be unique")
    if len(mathir_symbols) != len(set(mathir_symbols)):
        raise ParameterContractError("parameter request MathIR symbols must be unique")
    permitted_system_types = _text_list(
        payload.get("permitted_system_types"), field="permitted_system_types"
    )
    if set(permitted_system_types) - _PERMITTED_SYSTEM_TYPES:
        raise ParameterContractError("model blueprint includes an unsupported system type")
    model_form = _text(payload.get("model_form")) or "UNSPECIFIED"
    if model_form not in SUPPORTED_MODEL_FORMS:
        raise ParameterContractError("model blueprint model_form is unsupported")
    pde_family = _text(payload.get("pde_family"))
    if pde_family and pde_family not in PDE_CAPABILITIES:
        raise ParameterContractError("model blueprint includes an unsupported pde_family")
    spatial_dimension = payload.get("spatial_dimension")
    if spatial_dimension is not None:
        spatial_dimension = _optional_int(spatial_dimension, field="spatial_dimension", minimum=1)
        if spatial_dimension > 3:
            raise ParameterContractError("spatial_dimension must not exceed 3")
    revision_context = _mapping(payload.get("revision_context"))
    return {
        "schema_version": MODEL_BLUEPRINT_SCHEMA_VERSION,
        "lineage": lineage,
        "title": _required_text(payload, "title"),
        "scientific_question": _required_text(payload, "scientific_question"),
        "model_scope": _required_text(payload, "model_scope"),
        "symbolic_model_intent": _required_text(payload, "symbolic_model_intent"),
        "model_form": model_form,
        "pde_family": pde_family,
        "spatial_dimension": spatial_dimension,
        "required_operators": _text_list(
            payload.get("required_operators", []), field="required_operators", allow_empty=True
        ),
        "required_boundary_types": _text_list(
            payload.get("required_boundary_types", []), field="required_boundary_types", allow_empty=True
        ),
        "required_solver_features": _text_list(
            payload.get("required_solver_features", []), field="required_solver_features", allow_empty=True
        ),
        "permitted_system_types": permitted_system_types,
        "parameter_requests": requests,
        "symbolic_constraints": _text_list(payload.get("symbolic_constraints"), field="symbolic_constraints"),
        "revision_context": revision_context,
    }


def model_blueprint_identity(blueprint: Mapping[str, object]) -> str:
    return _json_identity(normalize_model_blueprint(blueprint))


def build_parameter_query_plan(*, blueprint: Mapping[str, object]) -> dict[str, Any]:
    """Render bounded provider-neutral discovery queries from a validated blueprint."""

    normalized = normalize_model_blueprint(blueprint)
    return {
        "schema_version": PARAMETER_QUERY_PLAN_SCHEMA_VERSION,
        "blueprint_identity": model_blueprint_identity(normalized),
        "lineage": normalized["lineage"],
        "requests": [
            {
                "parameter_id": request["parameter_id"],
                "mathir_symbol": request["mathir_symbol"],
                "queries": request["retrieval_queries"],
                "required_conditions": request["required_conditions"],
            }
            for request in normalized["parameter_requests"]
        ],
    }


def normalize_parameter_evidence_candidate(value: object) -> dict[str, Any]:
    """Validate one scalar evidence candidate with a source locator and conditions."""

    payload = _mapping(value)
    candidate_id = _required_text(payload, "candidate_id")
    if not _CANDIDATE_ID.fullmatch(candidate_id):
        raise ParameterContractError("candidate_id must be a stable PEC-Qx-parameter-### identifier")
    evidence_status = _required_text(payload, "evidence_status")
    if evidence_status not in _CANDIDATE_STATUSES:
        raise ParameterContractError("candidate evidence_status is unsupported")
    source_kind = _required_text(payload, "source_kind")
    if source_kind not in _SOURCE_KINDS:
        raise ParameterContractError("candidate source_kind is unsupported")
    source = _mapping(payload.get("source"))
    title = _required_text(source, "title")
    doi = _text(source.get("doi"))
    document_id = _text(source.get("document_id"))
    if not doi and not document_id:
        raise ParameterContractError("candidate source requires a DOI or a stable document_id")
    locator = _mapping(payload.get("evidence_locator"))
    quoted_text = _required_text(locator, "quoted_text")
    return {
        "candidate_id": candidate_id,
        "parameter_id": _identifier(payload.get("parameter_id"), field="candidate.parameter_id"),
        "mathir_symbol": _identifier(payload.get("mathir_symbol"), field="candidate.mathir_symbol"),
        "raw_value": _required_text(payload, "raw_value"),
        "normalized_value": _number(payload.get("normalized_value"), field="candidate.normalized_value"),
        "normalized_unit": _required_text(payload, "normalized_unit"),
        "value_form": "SCALAR",
        "source_kind": source_kind,
        "evidence_status": evidence_status,
        "source": {
            "doi": doi,
            "document_id": document_id,
            "title": title,
            "year": _optional_int(source.get("year"), field="candidate.source.year", minimum=1),
            "discovery_sources": _text_list(source.get("discovery_sources", []), field="candidate.source.discovery_sources", allow_empty=True),
            "cross_validated": bool(source.get("cross_validated", False)),
        },
        "evidence_locator": {
            "document_type": _required_text(locator, "document_type"),
            "section": _text(locator.get("section")),
            "table_or_figure": _text(locator.get("table_or_figure")),
            "page": _optional_int(locator.get("page"), field="candidate.evidence_locator.page", minimum=1),
            "quoted_text": quoted_text,
        },
        "conditions": _normalize_conditions(payload.get("conditions"), field="candidate.conditions"),
        "uncertainty": _normalize_conditions(payload.get("uncertainty"), field="candidate.uncertainty"),
        "transformation": {
            "applied": bool(_mapping(payload.get("transformation")).get("applied", False)),
            "formula": _text(_mapping(payload.get("transformation")).get("formula")),
        },
    }


def normalize_parameter_evidence_collection(value: object) -> dict[str, Any]:
    payload = _mapping(value)
    if _text(payload.get("schema_version")) != PARAMETER_EVIDENCE_COLLECTION_SCHEMA_VERSION:
        raise ParameterContractError("unsupported parameter evidence collection schema")
    raw_candidates = payload.get("candidates")
    if not isinstance(raw_candidates, Sequence) or isinstance(raw_candidates, (str, bytes, bytearray)):
        raise ParameterContractError("parameter evidence candidates must be a list")
    candidates = [normalize_parameter_evidence_candidate(candidate) for candidate in raw_candidates]
    candidate_ids = [candidate["candidate_id"] for candidate in candidates]
    if len(candidate_ids) != len(set(candidate_ids)):
        raise ParameterContractError("parameter evidence candidate IDs must be unique")
    normalized = {
        "schema_version": PARAMETER_EVIDENCE_COLLECTION_SCHEMA_VERSION,
        "blueprint_identity": _required_text(payload, "blueprint_identity"),
        "lineage": _normalize_lineage(payload.get("lineage")),
        "source_document": _mapping(payload.get("source_document")),
        "candidates": candidates,
    }
    extraction = payload.get("extraction")
    if isinstance(extraction, Mapping):
        normalized["extraction"] = dict(extraction)
    return normalized


def _selection_list(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise ParameterContractError("selections must be a list")
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, raw_selection in enumerate(value):
        selection = _mapping(raw_selection)
        parameter_id = _identifier(selection.get("parameter_id"), field=f"selections[{index}].parameter_id")
        if parameter_id in seen:
            raise ParameterContractError("each parameter may be selected only once")
        seen.add(parameter_id)
        candidate_id = _text(selection.get("candidate_id"))
        provenance_status = _text(selection.get("provenance_status"))
        if candidate_id:
            result.append(
                {
                    "parameter_id": parameter_id,
                    "candidate_id": candidate_id,
                    "provenance_status": provenance_status,
                    "selected_value": selection.get("selected_value"),
                    "selection_rationale": _required_text(selection, "selection_rationale"),
                }
            )
            continue
        if provenance_status != "APPROVED_MODEL_ASSUMPTION":
            raise ParameterContractError("a selection without a candidate must be an approved model assumption")
        result.append(
            {
                "parameter_id": parameter_id,
                "candidate_id": "",
                "provenance_status": provenance_status,
                "selected_value": _number(selection.get("selected_value"), field=f"{parameter_id}.selected_value"),
                "selection_rationale": _required_text(selection, "selection_rationale"),
            }
        )
    return result


def _normalize_resolution_entry(value: object, *, index: int) -> dict[str, Any]:
    """Normalize a frozen selection without trusting a hand-authored proposal."""

    entry = _mapping(value)
    parameter_id = _identifier(entry.get("parameter_id"), field=f"entries[{index}].parameter_id")
    mathir_symbol = _identifier(entry.get("mathir_symbol"), field=f"entries[{index}].mathir_symbol")
    role = _required_text(entry, "role")
    if role not in _REQUEST_ROLES:
        raise ParameterContractError("resolution entry role is unsupported")
    provenance_status = _required_text(entry, "provenance_status")
    if provenance_status not in _PROVENANCE_STATUSES:
        raise ParameterContractError("resolution entry provenance_status is unsupported")
    if provenance_status == "APPROVED_COMPATIBLE_CONSENSUS":
        raise ParameterContractError(
            "compatible-consensus selections are not supported until multi-source compatibility is implemented"
        )
    candidate_id = _text(entry.get("candidate_id"))
    source = _mapping(entry.get("source"))
    evidence_locator = _mapping(entry.get("evidence_locator"))
    if provenance_status == "APPROVED_MODEL_ASSUMPTION":
        if candidate_id or source or evidence_locator:
            raise ParameterContractError("model-assumption entries cannot claim an evidence candidate")
    else:
        if not _CANDIDATE_ID.fullmatch(candidate_id):
            raise ParameterContractError("candidate-backed resolution entries require a stable candidate_id")
        if not (_text(source.get("doi")) or _text(source.get("document_id"))):
            raise ParameterContractError("candidate-backed resolution entries require a DOI or document_id")
        _required_text(source, "title")
        _required_text(evidence_locator, "document_type")
        _required_text(evidence_locator, "quoted_text")
        _optional_int(evidence_locator.get("page"), field=f"{parameter_id}.evidence_locator.page", minimum=1)
    return {
        "parameter_id": parameter_id,
        "mathir_symbol": mathir_symbol,
        "selected_value": _number(entry.get("selected_value"), field=f"{parameter_id}.selected_value"),
        "unit": _required_text(entry, "unit"),
        "dimension": _required_text(entry, "dimension"),
        "role": role,
        "provenance_status": provenance_status,
        "candidate_id": candidate_id,
        "source": source,
        "evidence_locator": evidence_locator,
        "conditions": _normalize_conditions(entry.get("conditions"), field=f"{parameter_id}.conditions"),
        "uncertainty": _normalize_conditions(entry.get("uncertainty"), field=f"{parameter_id}.uncertainty"),
        "transformation": {
            "applied": bool(_mapping(entry.get("transformation")).get("applied", False)),
            "formula": _text(_mapping(entry.get("transformation")).get("formula")),
        },
        "selection_rationale": _required_text(entry, "selection_rationale"),
    }


def build_parameter_resolution_proposal(
    *,
    blueprint: Mapping[str, object],
    evidence_collections: Sequence[Mapping[str, object]],
    selections: object,
) -> dict[str, Any]:
    """Build a human-reviewable proposal without silently selecting literature values."""

    normalized_blueprint = normalize_model_blueprint(blueprint)
    blueprint_identity = model_blueprint_identity(normalized_blueprint)
    candidates: dict[str, dict[str, Any]] = {}
    for collection in evidence_collections:
        normalized_collection = normalize_parameter_evidence_collection(collection)
        if normalized_collection["blueprint_identity"] != blueprint_identity:
            raise ParameterContractError("parameter evidence collection is bound to another blueprint")
        if normalized_collection["lineage"] != normalized_blueprint["lineage"]:
            raise ParameterContractError("parameter evidence collection lineage differs from blueprint")
        for candidate in normalized_collection["candidates"]:
            if candidate["candidate_id"] in candidates:
                raise ParameterContractError("duplicate candidate ID across evidence collections")
            candidates[candidate["candidate_id"]] = candidate
    selections_by_parameter = {selection["parameter_id"]: selection for selection in _selection_list(selections)}
    entries: list[dict[str, Any]] = []
    unresolved: list[str] = []
    for request in normalized_blueprint["parameter_requests"]:
        parameter_id = request["parameter_id"]
        selection = selections_by_parameter.get(parameter_id)
        if selection is None:
            unresolved.append(parameter_id)
            continue
        if selection["candidate_id"]:
            candidate = candidates.get(selection["candidate_id"])
            if candidate is None:
                raise ParameterContractError(f"selection references an unknown candidate: {selection['candidate_id']}")
            if candidate["parameter_id"] != parameter_id or candidate["mathir_symbol"] != request["mathir_symbol"]:
                raise ParameterContractError("selected candidate does not match its parameter request")
            if candidate["normalized_unit"] != request["unit"]:
                raise ParameterContractError("selected candidate unit differs from the requested execution unit")
            identifier_conditions = {
                condition
                for condition in request["required_conditions"]
                if _IDENTIFIER.fullmatch(condition)
            }
            missing_conditions = identifier_conditions - set(candidate["conditions"])
            if missing_conditions:
                raise ParameterContractError(
                    "selected candidate is missing required applicability conditions: "
                    + ", ".join(sorted(missing_conditions))
                )
            status = selection["provenance_status"] or (
                "APPROVED_USER_INPUT" if candidate["evidence_status"] == "USER_PROVIDED" else "APPROVED_LITERATURE_SINGLE_SOURCE"
            )
            if status not in _PROVENANCE_STATUSES - {"APPROVED_MODEL_ASSUMPTION"}:
                raise ParameterContractError("candidate-backed selection has an invalid provenance_status")
            if selection["selected_value"] is not None and _number(
                selection["selected_value"], field=f"{parameter_id}.selected_value"
            ) != candidate["normalized_value"]:
                raise ParameterContractError(
                    "a candidate-backed selection must use its extracted normalized_value exactly"
                )
            chosen_value = candidate["normalized_value"]
            if status == "APPROVED_COMPATIBLE_CONSENSUS":
                raise ParameterContractError(
                    "compatible-consensus selections are not supported until multi-source compatibility is implemented"
                )
            entries.append(
                {
                    "parameter_id": parameter_id,
                    "mathir_symbol": request["mathir_symbol"],
                    "selected_value": chosen_value,
                    "unit": request["unit"],
                    "dimension": request["dimension"],
                    "role": request["role"],
                    "provenance_status": status,
                    "candidate_id": candidate["candidate_id"],
                    "source": candidate["source"],
                    "evidence_locator": candidate["evidence_locator"],
                    "conditions": {
                        **candidate["conditions"],
                        **{
                            f"required_condition_{index}": condition
                            for index, condition in enumerate(request["required_conditions"], start=1)
                        },
                    },
                    "uncertainty": candidate["uncertainty"],
                    "transformation": candidate["transformation"],
                    "selection_rationale": selection["selection_rationale"],
                }
            )
            continue
        if request["evidence_requirement"] not in {
            "LITERATURE_PREFERRED",
            "MODEL_ASSUMPTION_ALLOWED",
        }:
            raise ParameterContractError("this parameter request does not allow a model-assumption fallback")
        entries.append(
            {
                "parameter_id": parameter_id,
                "mathir_symbol": request["mathir_symbol"],
                "selected_value": selection["selected_value"],
                "unit": request["unit"],
                "dimension": request["dimension"],
                "role": request["role"],
                "provenance_status": "APPROVED_MODEL_ASSUMPTION",
                "candidate_id": "",
                "source": {},
                "evidence_locator": {},
                "conditions": {
                    f"required_condition_{index}": condition
                    for index, condition in enumerate(request["required_conditions"], start=1)
                },
                "uncertainty": {},
                "transformation": {"applied": False, "formula": ""},
                "selection_rationale": selection["selection_rationale"],
            }
        )
    extra_selections = set(selections_by_parameter) - {request["parameter_id"] for request in normalized_blueprint["parameter_requests"]}
    if extra_selections:
        raise ParameterContractError("selections include a parameter that is not requested by the blueprint")
    proposal_without_identity = {
        "schema_version": PARAMETER_RESOLUTION_PROPOSAL_SCHEMA_VERSION,
        "approval_status": "READY_FOR_APPROVAL" if not unresolved else "REVIEW_REQUIRED",
        "blueprint_identity": blueprint_identity,
        "lineage": normalized_blueprint["lineage"],
        "entries": entries,
        "unresolved_parameter_ids": unresolved,
    }
    return {**proposal_without_identity, "proposal_identity": _json_identity(proposal_without_identity)}


def normalize_parameter_resolution_proposal(value: object) -> dict[str, Any]:
    payload = _mapping(value)
    if _text(payload.get("schema_version")) != PARAMETER_RESOLUTION_PROPOSAL_SCHEMA_VERSION:
        raise ParameterContractError("unsupported parameter resolution proposal schema")
    status = _required_text(payload, "approval_status")
    if status not in {"READY_FOR_APPROVAL", "REVIEW_REQUIRED"}:
        raise ParameterContractError("parameter resolution proposal approval_status is unsupported")
    raw_entries = payload.get("entries")
    if not isinstance(raw_entries, Sequence) or isinstance(raw_entries, (str, bytes, bytearray)):
        raise ParameterContractError("parameter resolution proposal entries must be a list")
    entries = [_normalize_resolution_entry(entry, index=index) for index, entry in enumerate(raw_entries)]
    parameter_ids = [entry["parameter_id"] for entry in entries]
    if len(parameter_ids) != len(set(parameter_ids)):
        raise ParameterContractError("parameter resolution proposal entries must be unique")
    unresolved = _text_list(
        payload.get("unresolved_parameter_ids", []),
        field="unresolved_parameter_ids",
        allow_empty=True,
    )
    if set(parameter_ids).intersection(unresolved):
        raise ParameterContractError("a resolved parameter cannot also be unresolved")
    if status == "READY_FOR_APPROVAL" and (not entries or unresolved):
        raise ParameterContractError("READY_FOR_APPROVAL proposals must be complete")
    normalized = {
        "schema_version": PARAMETER_RESOLUTION_PROPOSAL_SCHEMA_VERSION,
        "approval_status": status,
        "blueprint_identity": _required_text(payload, "blueprint_identity"),
        "lineage": _normalize_lineage(payload.get("lineage")),
        "entries": entries,
        "unresolved_parameter_ids": unresolved,
    }
    expected_identity = _json_identity(normalized)
    if _required_text(payload, "proposal_identity") != expected_identity:
        raise ParameterContractError("parameter resolution proposal identity does not match its content")
    return {**normalized, "proposal_identity": expected_identity}


def approve_parameter_resolution_proposal(
    proposal: Mapping[str, object], *, approve: bool
) -> dict[str, Any]:
    """Freeze an explicit human approval; this operation never launches a simulation."""

    normalized = normalize_parameter_resolution_proposal(proposal)
    if not approve:
        raise ParameterContractError("parameter resolution proposal was not approved")
    if normalized["approval_status"] != "READY_FOR_APPROVAL" or normalized["unresolved_parameter_ids"]:
        raise ParameterContractError("only a complete parameter resolution proposal can be approved")
    entries = normalized["entries"]
    if not entries:
        raise ParameterContractError("approved parameter set requires entries")
    parameter_ids = [entry["parameter_id"] for entry in entries]
    if len(parameter_ids) != len(set(parameter_ids)):
        raise ParameterContractError("approved parameter entries must be unique")
    approved_without_identity = {
        "schema_version": APPROVED_PARAMETER_SET_SCHEMA_VERSION,
        "approval_status": "APPROVED",
        "blueprint_identity": normalized["blueprint_identity"],
        "proposal_identity": normalized["proposal_identity"],
        "lineage": normalized["lineage"],
        "entries": entries,
    }
    return {**approved_without_identity, "parameter_set_identity": _json_identity(approved_without_identity)}


def normalize_approved_parameter_set(value: object) -> dict[str, Any]:
    payload = _mapping(value)
    if _text(payload.get("schema_version")) != APPROVED_PARAMETER_SET_SCHEMA_VERSION:
        raise ParameterContractError("unsupported approved parameter set schema")
    if _required_text(payload, "approval_status") != "APPROVED":
        raise ParameterContractError("approved parameter set must have APPROVED status")
    raw_entries = payload.get("entries")
    if not isinstance(raw_entries, Sequence) or isinstance(raw_entries, (str, bytes, bytearray)) or not raw_entries:
        raise ParameterContractError("approved parameter set entries must be a non-empty list")
    entries: list[dict[str, Any]] = []
    parameter_ids: set[str] = set()
    mathir_symbols: set[str] = set()
    for index, raw_entry in enumerate(raw_entries):
        entry = _mapping(raw_entry)
        parameter_id = _identifier(entry.get("parameter_id"), field=f"approved entries[{index}].parameter_id")
        mathir_symbol = _identifier(entry.get("mathir_symbol"), field=f"approved entries[{index}].mathir_symbol")
        if parameter_id in parameter_ids or mathir_symbol in mathir_symbols:
            raise ParameterContractError("approved parameter IDs and MathIR symbols must be unique")
        parameter_ids.add(parameter_id)
        mathir_symbols.add(mathir_symbol)
        normalized_entry = _normalize_resolution_entry(entry, index=index)
        if normalized_entry["parameter_id"] != parameter_id or normalized_entry["mathir_symbol"] != mathir_symbol:
            raise ParameterContractError("approved parameter entry identity changed during normalization")
        entries.append(normalized_entry)
    normalized = {
        "schema_version": APPROVED_PARAMETER_SET_SCHEMA_VERSION,
        "approval_status": "APPROVED",
        "blueprint_identity": _required_text(payload, "blueprint_identity"),
        "proposal_identity": _required_text(payload, "proposal_identity"),
        "lineage": _normalize_lineage(payload.get("lineage")),
        "entries": entries,
    }
    identity = _json_identity(normalized)
    if _required_text(payload, "parameter_set_identity") != identity:
        raise ParameterContractError("approved parameter set identity does not match its content")
    return {**normalized, "parameter_set_identity": identity}


def approved_mathir_parameters(parameter_set: Mapping[str, object]) -> dict[str, float]:
    normalized = normalize_approved_parameter_set(parameter_set)
    return {entry["mathir_symbol"]: entry["selected_value"] for entry in normalized["entries"]}


def parameter_evidence_summary(parameter_set: Mapping[str, object]) -> list[dict[str, Any]]:
    normalized = normalize_approved_parameter_set(parameter_set)
    return [
        {
            "parameter_id": entry["parameter_id"],
            "mathir_symbol": entry["mathir_symbol"],
            "selected_value": entry["selected_value"],
            "unit": entry["unit"],
            "role": entry["role"],
            "provenance_status": entry["provenance_status"],
            "source": entry["source"],
            "evidence_locator": entry["evidence_locator"],
            "conditions": entry["conditions"],
            "uncertainty": entry["uncertainty"],
            "transformation": entry["transformation"],
            "selection_rationale": entry["selection_rationale"],
        }
        for entry in normalized["entries"]
    ]


__all__ = [
    "APPROVED_PARAMETER_SET_SCHEMA_VERSION",
    "MODEL_BLUEPRINT_SCHEMA_VERSION",
    "PARAMETER_DISCOVERY_SCHEMA_VERSION",
    "PARAMETER_EVIDENCE_COLLECTION_SCHEMA_VERSION",
    "PARAMETER_QUERY_PLAN_SCHEMA_VERSION",
    "PARAMETER_RESOLUTION_PROPOSAL_SCHEMA_VERSION",
    "ParameterContractError",
    "approve_parameter_resolution_proposal",
    "approved_mathir_parameters",
    "build_parameter_query_plan",
    "build_parameter_resolution_proposal",
    "model_blueprint_identity",
    "normalize_approved_parameter_set",
    "normalize_model_blueprint",
    "normalize_parameter_evidence_candidate",
    "normalize_parameter_evidence_collection",
    "normalize_parameter_resolution_proposal",
    "parameter_evidence_summary",
]
