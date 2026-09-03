"""Source-constrained hierarchical scientific-hypothesis search.

The hierarchy in this module is deliberately discipline-neutral.  It refines
an already admitted TanXi -> Socrates handoff; it never discovers a new gap
and never grants evidence status to LLM output.  Upstream project, gap,
sub-hypothesis, causal-role, evidence, and conclusion-scope fields are frozen
in a signed contract.  Each search step edits exactly one of five layers and
must pass deterministic gates before it may survive.

The external LLM is therefore a bounded proposal engine, not an epistemic
authority.  Unsupported exact parameter values are replaced with
``TO_BE_OPTIMIZED`` rather than being presented as scientific facts.
"""
from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
from typing import Any, Callable
import json
import re
import time

try:
    from ._input_ontology import classify_input_candidate
    from ._intervention_ontology import (
        classify_mediator_candidate,
    )
    from ._outcome_ontology import classify_outcome_candidate
    from ._research_mode import resolve_research_mode
except ImportError:
    from _input_ontology import classify_input_candidate
    from _intervention_ontology import (
        classify_mediator_candidate,
    )
    from _outcome_ontology import classify_outcome_candidate
    from _research_mode import resolve_research_mode


HIERARCHY_VERSION = "source_constrained_scientific_hypothesis_hierarchy.v1"
FROZEN_CONTRACT_VERSION = "mingli_frozen_scientific_contract.v1"
TO_BE_OPTIMIZED = "TO_BE_OPTIMIZED"
UNRESOLVED_ENTITY = "NOT_IDENTIFIED"

HIERARCHY_LEVELS: tuple[dict[str, Any], ...] = (
    {
        "level": 1,
        "level_id": "SCIENTIFIC_CLAIM_TOPOLOGY",
        "required_fields": (
            "primary_mechanism",
            "competing_mechanisms",
            "boundary_conditions",
            "scientific_distinction",
        ),
    },
    {
        "level": 2,
        "level_id": "ENTITY_AND_CAUSAL_ROLE_SPECIFICATION",
        "required_fields": (
            "input_or_intervention",
            "target_object",
            "mediator",
            "outcome",
            "common_causes",
            "alternative_paths",
        ),
    },
    {
        "level": 3,
        "level_id": "OPERATIONALIZATION_AND_DISCRIMINATION",
        "required_fields": (
            "measurement_variables",
            "control_or_comparator",
            "counterfactual",
            "identification_strategy",
            "decisive_prediction",
            "minimal_falsification_condition",
        ),
    },
    {
        "level": 4,
        "level_id": "IMPLEMENTATION_AND_PARAMETER_SPACE",
        "required_fields": (
            "materials_or_inputs",
            "model_or_system",
            "instruments_or_software",
            "algorithm_or_procedure_configuration",
            "parameter_space",
            "precise_value_policy",
        ),
    },
    {
        "level": 5,
        "level_id": "VALIDATION_SAFETY_AND_REPRODUCIBILITY",
        "required_fields": (
            "temporal_order",
            "sample_and_replication",
            "statistical_or_formal_analysis",
            "reproducibility_artifacts",
            "negative_controls",
            "alternative_mechanism_tests",
            "safety_and_risk_controls",
            "stopping_conditions",
        ),
    },
)

_PLACEHOLDERS = {
    "",
    "unknown",
    "unresolved",
    "none",
    "n/a",
    "not applicable",
    "generic_placeholder",
    "requires_direct_intervention_evidence",
}
_NUMBER_RE = re.compile(
    r"(?<![A-Za-z0-9])"
    r"(?:[<>]=?\s*)?"
    r"(?:\d+(?:\.\d+)?|\.\d+)"
    r"(?:\s*(?:-|–|to)\s*(?:\d+(?:\.\d+)?|\.\d+))?"
    r"\s*(?:%|°?[CFK]|Pa|kPa|MPa|GPa|Hz|kHz|MHz|GHz|s|ms|us|ns|"
    r"m|cm|mm|um|µm|nm|kg|g|mg|ug|µg|mol|mmol|umol|µmol|M|mM|uM|µM|"
    r"eV|keV|MeV|J|W|V|mV|A|mA|rpm|cycles?|samples?|replicates?)\b",
    re.IGNORECASE,
)
_EXACT_ASSIGNMENT_RE = re.compile(
    r"(?<![A-Za-z0-9])"
    r"(?:n|N|p|q|alpha|beta|gamma|α|β|γ|seed|epochs?|iterations?|folds?)"
    r"\s*(?:=|<=|>=|<|>)\s*"
    r"(?:\d+(?:\.\d+)?|\.\d+)",
    re.IGNORECASE,
)
_CAUSAL_RELATION_RE = re.compile(
    r"\b(?:cause|causal|mediate|through|path|route|direct|indirect|confound|"
    r"common cause|competing|alternative|binding|coupling|transport|transfer|"
    r"diffusion|feedback|transition|interaction|modulat|regulat|propagat)\w*\b",
    re.IGNORECASE,
)
_GENERIC_ENTITY_WORDS = {
    "analysis", "approach", "data", "effect", "experiment", "factor", "method",
    "model", "object", "process", "research", "result", "study", "system",
    "thing", "variable",
}


def _compact(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _items(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _first(*values: Any) -> str:
    for value in values:
        text = _compact(value)
        if text and text.lower() not in _PLACEHOLDERS:
            return text
    return ""


def _unique(values: list[Any]) -> list[str]:
    result: list[str] = []
    for value in values:
        text = _compact(value)
        if text and text not in result:
            result.append(text)
    return result


def _canonical_hash(value: Any) -> str:
    rendered = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return sha256(rendered.encode("utf-8")).hexdigest()


def hierarchy_level(level_id: str) -> dict[str, Any]:
    return next(
        (dict(item) for item in HIERARCHY_LEVELS if item["level_id"] == level_id),
        {},
    )


def _collect_source_ids(value: Any) -> list[str]:
    """Collect explicit evidence identifiers without treating prose as an id."""
    result: list[str] = []

    def visit(node: Any, source_field: bool = False) -> None:
        if isinstance(node, dict):
            for child_key, child in node.items():
                lowered = str(child_key).lower()
                is_source_field = (
                    lowered in {
                        "source_unit_ids", "source_ids", "evidence_ids",
                        "direct_evidence_ids", "theory_evidence_ids",
                        "experimental_evidence_ids", "supporting_references",
                        "sources", "reference_ids", "paper_ids",
                    }
                    or lowered.endswith("_evidence_ids")
                    or lowered.endswith("_source_ids")
                )
                if is_source_field:
                    visit(child, True)
                elif isinstance(child, (dict, list)):
                    visit(child, False)
        elif isinstance(node, list):
            for child in node:
                visit(child, source_field)
        elif source_field:
            text = _compact(node)
            if text and len(text) <= 500 and text not in result:
                result.append(text)

    visit(value)
    return result[:256]


def _source_record_ids(record: dict[str, Any]) -> list[str]:
    return _unique([
        record.get("source_unit_id"),
        record.get("fragment_id"),
        record.get("span_id"),
        record.get("paper_id"),
        record.get("record_id"),
        record.get("doi"),
        record.get("citation"),
        record.get("url"),
        record.get("source_url"),
    ])


def build_source_text_index(
    project: dict[str, Any],
    gap: dict[str, Any],
    contract: dict[str, Any] | None = None,
) -> dict[str, str]:
    """Index source text for literal parameter-provenance verification."""
    index: dict[str, str] = {}

    def append(identifier: str, text: Any) -> None:
        key = _compact(identifier)
        body = _compact(text)
        if not key or not body:
            return
        index[key] = _compact(f"{index.get(key, '')} {body}")[:60000]

    def visit(node: Any, inherited_id: str = "", depth: int = 0) -> None:
        if depth > 8:
            return
        if isinstance(node, dict):
            identifiers = _source_record_ids(node)
            identifier = (identifiers[0] if identifiers else "") or inherited_id
            text_parts = [
                node.get(key)
                for key in (
                    "text", "excerpt", "quote", "source_text", "title",
                    "abstract", "contribution", "limitation", "claim",
                )
                if isinstance(node.get(key), str)
            ]
            if text_parts:
                for alias in identifiers or [identifier]:
                    append(alias, " ".join(text_parts))
            for child in node.values():
                if isinstance(child, (dict, list)):
                    visit(child, identifier, depth + 1)
        elif isinstance(node, list):
            for child in node:
                visit(child, inherited_id, depth + 1)

    visit(gap)
    visit(contract or {})
    for record in _items(project.get("papergraph")):
        if isinstance(record, dict):
            visit(record)
    return index


def _role_source_ids(
    bundle: dict[str, Any],
    role: str,
    fallback_ids: list[str],
) -> list[str]:
    provenance = _mapping(bundle.get("causal_field_provenance"))
    role_map = _mapping(provenance.get(role))
    ids = _unique(
        _items(role_map.get("source_unit_ids"))
        + _items(role_map.get("source_ids"))
        + _items(role_map.get("evidence_ids"))
    )
    return ids or list(fallback_ids[:12])


def _contract_core_from_sources(
    project: dict[str, Any],
    gap: dict[str, Any],
    candidate: dict[str, Any],
    hypothesis_package: dict[str, Any],
) -> dict[str, Any]:
    bundle = _mapping(gap.get("mechanism_evidence_bundle")) or _mapping(
        gap.get("mechanism_draft")
    )
    socrates = _mapping(candidate.get("socrates_mechanism_contract"))
    if not socrates:
        contracts = _mapping(project.get("socrates_mechanism_contracts"))
        socrates = _mapping(contracts.get(_compact(gap.get("gap_id"))))
    readiness = _mapping(socrates.get("hypothesis_readiness"))
    normalized = _mapping(
        _mapping(readiness.get("mode_specific_contract")).get("normalized_core_chain")
    )
    slots = _mapping(hypothesis_package.get("slots"))
    sub_id = _first(
        candidate.get("sub_hypothesis_id"),
        gap.get("sub_hypothesis_id"),
        bundle.get("sub_hypothesis_id"),
    )
    subhypothesis = next(
        (
            item for item in _items(project.get("sub_hypotheses"))
            if isinstance(item, dict) and _compact(item.get("id")) == sub_id
        ),
        {},
    )
    dependent = _items(_mapping(subhypothesis).get("dependent_variables"))
    claim = _mapping(candidate.get("claim"))
    intervention_gate = _mapping(candidate.get("intervention_type_gate"))
    edges = [item for item in _items(candidate.get("mechanism_edges")) if isinstance(item, dict)]
    edge_mediator = ""
    if edges:
        edge_mediator = _first(edges[0].get("target"), edges[-1].get("source"))
    input_value = _first(
        bundle.get("intervention"), bundle.get("input"), bundle.get("exposure"),
        bundle.get("configuration"), bundle.get("assumptions"),
        normalized.get("input_or_intervention"),
        intervention_gate.get("selected_intervention"),
        slots.get("input"),
    )
    mediator = _first(
        bundle.get("mediator"), bundle.get("proposed_mediator"),
        normalized.get("mediator"), slots.get("mechanism"), edge_mediator,
    )
    outcome = _first(
        bundle.get("outcome"), bundle.get("output"),
        normalized.get("observable_outcome"), slots.get("outcome"),
        dependent[0] if dependent else "", claim.get("expected_result"),
    )
    target_object = _first(
        slots.get("scope"),
        claim.get("object"),
        gap.get("target_system"),
        subhypothesis.get("scientific_object"),
        subhypothesis.get("title"),
        project.get("objective"),
        project.get("domain"),
    )
    comparison = _first(
        bundle.get("comparison"), bundle.get("control"), bundle.get("baseline"),
        normalized.get("comparison"), slots.get("comparison"),
    )
    falsification = _first(
        bundle.get("falsification"), bundle.get("failure_condition"),
        normalized.get("falsification"), slots.get("falsification"),
        candidate.get("falsifier"),
    )
    fallback_ids = _unique(
        _collect_source_ids(bundle)
        + _collect_source_ids(socrates)
        + _collect_source_ids(gap)
        + _collect_source_ids(hypothesis_package)
    )
    mode_resolution = resolve_research_mode(project, gap, socrates, bundle)
    return {
        "research_mode": _compact(mode_resolution.get("mode")),
        "research_mode_resolution": mode_resolution,
        "roles": {
            "input_or_intervention": {
                "value": input_value,
                "source_unit_ids": _role_source_ids(bundle, "input", fallback_ids),
            },
            "target_object": {
                "value": target_object,
                "source_unit_ids": _role_source_ids(bundle, "object", fallback_ids),
            },
            "mediator": {
                "value": mediator,
                "source_unit_ids": _role_source_ids(bundle, "mediator", fallback_ids),
            },
            "outcome": {
                "value": outcome,
                "source_unit_ids": _role_source_ids(bundle, "outcome", fallback_ids),
            },
        },
        "comparison": comparison,
        "falsification": falsification,
        "source_evidence_ids": fallback_ids,
    }


def build_frozen_hypothesis_contract(
    project: dict[str, Any],
    gap: dict[str, Any],
    candidate: dict[str, Any],
    hypothesis_package: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Freeze the admissible search space before any hierarchical edit."""
    package = (
        hypothesis_package
        if isinstance(hypothesis_package, dict)
        else _mapping(candidate.get("hypothesis_package"))
    )
    core = _contract_core_from_sources(project, gap, candidate, package)
    conclusion_scope = _mapping(package.get("conclusion_scope"))
    frozen = {
        "contract_version": FROZEN_CONTRACT_VERSION,
        "project_id": _compact(project.get("project_id")),
        "state_store_id": _compact(project.get("state_store_id")),
        "gap_id": _compact(gap.get("gap_id")),
        "gap_revision": gap.get("gap_revision"),
        "gap_snapshot_hash": _first(
            gap.get("gap_snapshot_hash"),
            _mapping(candidate.get("science_state_handoff")).get("gap_snapshot_hash"),
        ),
        "sub_hypothesis_id": _first(
            candidate.get("sub_hypothesis_id"), gap.get("sub_hypothesis_id")
        ),
        "hypothesis_package_id": _compact(package.get("hypothesis_package_id")),
        "research_mode": core["research_mode"],
        "roles": core["roles"],
        "comparison": core["comparison"],
        "falsification": core["falsification"],
        "source_evidence_ids": core["source_evidence_ids"],
        "conclusion_scope": {
            "allowed": _items(conclusion_scope.get("allowed")),
            "forbidden": _items(conclusion_scope.get("forbidden")),
        },
    }
    frozen["contract_signature"] = _canonical_hash(frozen)
    return frozen


def verify_frozen_contract(contract: dict[str, Any]) -> dict[str, Any]:
    supplied = _compact(contract.get("contract_signature"))
    unsigned = {
        key: value for key, value in contract.items()
        if key != "contract_signature"
    }
    expected = _canonical_hash(unsigned)
    required = (
        "project_id", "gap_id", "sub_hypothesis_id", "research_mode", "roles",
    )
    missing = [name for name in required if not contract.get(name)]
    role_values = _mapping(contract.get("roles"))
    missing.extend(
        f"roles.{role}"
        for role in ("input_or_intervention", "target_object", "mediator", "outcome")
        if not _first(_mapping(role_values.get(role)).get("value"))
    )
    return {
        "valid": bool(supplied and supplied == expected and not missing),
        "signature_matches": bool(supplied and supplied == expected),
        "missing": missing,
        "expected_signature": expected,
    }


def _scientific_entity_assessment(
    value: Any,
    *,
    role: str,
    source_unit_ids: list[str],
    research_mode: str,
    target_outcome: str = "",
) -> dict[str, Any]:
    text = _compact(value)
    source_bound = bool(source_unit_ids)
    if role == "input_or_intervention":
        assessment = classify_input_candidate(
            text,
            research_mode=research_mode,
            source_unit_ids=source_unit_ids,
            require_source_bound=True,
        )
        return {
            **assessment,
            "role": role,
            "ontology_passed": bool(assessment.get("admissible_as_input")),
        }
    if role == "mediator":
        assessment = classify_mediator_candidate(text)
        return {
            **assessment,
            "role": role,
            "source_bound": source_bound,
            "source_unit_ids": source_unit_ids,
            "ontology_passed": bool(
                assessment.get("admissible_as_mediator") and source_bound
            ),
        }
    if role == "outcome":
        assessment = classify_outcome_candidate(
            text,
            research_mode=research_mode,
            target_outcome_terms=[target_outcome or text],
            source_unit_ids=source_unit_ids,
            require_target_alignment=True,
            require_source_bound=True,
        )
        return {
            **assessment,
            "role": role,
            "ontology_passed": bool(assessment.get("admissible_as_outcome")),
        }
    if text in {TO_BE_OPTIMIZED, UNRESOLVED_ENTITY}:
        return {
            "role": role,
            "candidate": text,
            "category": "explicitly_unresolved_optional_role",
            "source_bound": False,
            "ontology_passed": True,
            "reason": "The optional role is explicitly unresolved and is not asserted as an entity.",
        }
    tokens = [
        token.lower()
        for token in re.findall(r"[A-Za-z][A-Za-z0-9_+./-]*", text)
        if len(token) >= 2
    ]
    content = [token for token in tokens if token not in _GENERIC_ENTITY_WORDS]
    compact_phrase = bool(text and len(text.split()) <= 28 and len(text) <= 240)
    if role in {"common_cause", "alternative_path"}:
        structural = bool(
            compact_phrase and content and (
                len(content) >= 2 or _CAUSAL_RELATION_RE.search(text)
            )
        )
        category = "causal_entity_or_path"
    else:
        structural = bool(compact_phrase and content)
        category = "scientific_object_or_resource"
    passed = bool(structural and source_bound)
    return {
        "role": role,
        "candidate": text,
        "category": category if structural else "generic_or_narrative_entity",
        "source_bound": source_bound,
        "source_unit_ids": source_unit_ids,
        "ontology_passed": passed,
        "reason": (
            "The role is a compact, source-bound scientific entity or path."
            if passed
            else "The role must be a compact scientific entity/path with upstream evidence provenance."
        ),
    }


def _entity_record(
    contract: dict[str, Any],
    role: str,
    *,
    value: str | None = None,
    source_unit_ids: list[str] | None = None,
) -> dict[str, Any]:
    frozen = _mapping(_mapping(contract.get("roles")).get(role))
    selected_value = _first(value, frozen.get("value")) or UNRESOLVED_ENTITY
    ids = _unique(source_unit_ids or _items(frozen.get("source_unit_ids")))
    outcome = _first(
        _mapping(_mapping(contract.get("roles")).get("outcome")).get("value")
    )
    assessment = _scientific_entity_assessment(
        selected_value,
        role=role,
        source_unit_ids=ids,
        research_mode=_compact(contract.get("research_mode")),
        target_outcome=outcome,
    )
    return {
        "role": role,
        "value": selected_value,
        "source_unit_ids": ids,
        "ontology": assessment,
    }


def _candidate_primary_mechanism(candidate: dict[str, Any], contract: dict[str, Any]) -> str:
    return _first(
        candidate.get("mechanism"),
        _mapping(_mapping(contract.get("roles")).get("mediator")).get("value"),
    )


def deterministic_layer_proposal(
    level_id: str,
    candidate: dict[str, Any],
    contract: dict[str, Any],
    *,
    variant: int = 0,
) -> dict[str, Any]:
    """Produce a conservative source-bound proposal for one hierarchy level."""
    roles = _mapping(contract.get("roles"))
    input_value = _first(_mapping(roles.get("input_or_intervention")).get("value"))
    target = _first(_mapping(roles.get("target_object")).get("value"))
    mediator = _first(_mapping(roles.get("mediator")).get("value"))
    outcome = _first(_mapping(roles.get("outcome")).get("value"))
    comparison = _first(contract.get("comparison"), "matched comparator required")
    falsification = _first(
        contract.get("falsification"),
        candidate.get("falsifier"),
        f"Reject the mechanism if {input_value} does not change {mediator} before {outcome}.",
    )
    # Copy the list: proposals are mutable search objects and must never share
    # a reference with the signed frozen contract.
    source_ids = list(_items(contract.get("source_evidence_ids")))
    boundary = _first(
        candidate.get("boundary"),
        "the preregistered regime in which the primary and competing explanations diverge",
    )
    competitor = _first(
        candidate.get("competing_explanation"),
        f"A direct {input_value}-to-{outcome} path or a source-compatible common cause that bypasses {mediator}.",
    )
    if variant == 1:
        competitor = (
            f"An alternative path in which {input_value} changes {outcome} without "
            f"requiring {mediator}; distinguish it from the primary path."
        )
    if level_id == "SCIENTIFIC_CLAIM_TOPOLOGY":
        layer = {
            "primary_mechanism": (
                f"Frozen primary path: {input_value} changes {mediator}, which then changes {outcome}. "
                f"Evidence-bounded interpretation: {_candidate_primary_mechanism(candidate, contract)}"
            ),
            "competing_mechanisms": [competitor],
            "boundary_conditions": [boundary],
            "scientific_distinction": (
                f"Determine whether {mediator} is necessary for the effect of {input_value} on {outcome}, "
                "rather than merely associated with it. "
                + _compact(candidate.get("discriminating_prediction"))
            ),
            "source_evidence_ids": source_ids,
        }
    elif level_id == "ENTITY_AND_CAUSAL_ROLE_SPECIFICATION":
        layer = {
            "input_or_intervention": _entity_record(contract, "input_or_intervention"),
            "target_object": _entity_record(contract, "target_object"),
            "mediator": _entity_record(contract, "mediator"),
            "outcome": _entity_record(contract, "outcome"),
            "common_causes": [
                _entity_record(
                    contract,
                    "common_cause",
                    value=UNRESOLVED_ENTITY,
                    source_unit_ids=[],
                )
            ],
            "alternative_paths": [
                _entity_record(
                    contract,
                    "alternative_path",
                    value=competitor,
                    source_unit_ids=source_ids,
                )
            ],
        }
    elif level_id == "OPERATIONALIZATION_AND_DISCRIMINATION":
        layer = {
            "measurement_variables": [
                {
                    "construct": mediator,
                    "observable": f"source-supported observable for {mediator}",
                    "source_unit_ids": _items(_mapping(roles.get("mediator")).get("source_unit_ids")),
                },
                {
                    "construct": outcome,
                    "observable": outcome,
                    "source_unit_ids": _items(_mapping(roles.get("outcome")).get("source_unit_ids")),
                },
            ],
            "control_or_comparator": comparison,
            "counterfactual": (
                f"Under otherwise matched conditions, set or stratify {input_value} to its comparator "
                f"and test whether the predicted change in {mediator} and then {outcome} disappears."
            ),
            "identification_strategy": (
                f"Use the design appropriate to {_compact(contract.get('research_mode'))}: "
                "predeclare the comparison, confounder/assumption set, temporal ordering, and model discriminator."
            ),
            "decisive_prediction": _first(
                (
                    f"{mediator} changes before {outcome} after {input_value}, and the primary and competing paths "
                    f"make different predictions at {boundary}. "
                    + _compact(candidate.get("discriminating_prediction"))
                ),
            ),
            "minimal_falsification_condition": falsification,
        }
    elif level_id == "IMPLEMENTATION_AND_PARAMETER_SPACE":
        parameter = {
            "name": "boundary_or_operating_regime",
            "value": boundary,
            "source_unit_ids": source_ids,
            "status": "SOURCE_CONSTRAINED_QUALITATIVE_RANGE",
        }
        layer = {
            "materials_or_inputs": [
                _entity_record(
                    contract,
                    "material_or_input",
                    value=input_value,
                    source_unit_ids=_items(
                        _mapping(roles.get("input_or_intervention")).get("source_unit_ids")
                    ),
                )
            ],
            "model_or_system": _entity_record(
                contract,
                "model_or_system",
                value=target,
                source_unit_ids=_items(
                    _mapping(roles.get("target_object")).get("source_unit_ids")
                ),
            ),
            "instruments_or_software": [
                _entity_record(
                    contract,
                    "instrument_or_software",
                    value=TO_BE_OPTIMIZED,
                    source_unit_ids=[],
                )
            ],
            "algorithm_or_procedure_configuration": _entity_record(
                contract,
                "algorithm_or_procedure_configuration",
                value=TO_BE_OPTIMIZED,
                source_unit_ids=[],
            ),
            "parameter_space": [parameter],
            "precise_value_policy": (
                "An exact numeric value is retained only when the same literal occurs in a bound source unit; "
                f"otherwise its value is replaced by {TO_BE_OPTIMIZED}."
            ),
        }
    else:
        layer = {
            "temporal_order": (
                f"Verify that {input_value} occurs first, the change in {mediator} is observed next, "
                f"and {outcome} is assessed last within a preregistered observation window."
            ),
            "sample_and_replication": (
                "Define the experimental/observational unit, independent replication, technical replication where relevant, "
                f"and sample-size or proof-search budget as {TO_BE_OPTIMIZED} until justified."
            ),
            "statistical_or_formal_analysis": (
                "Predeclare effect/uncertainty estimates and multiplicity handling, or the corresponding formal proof, "
                "simulation-convergence, and error-bound obligations."
            ),
            "reproducibility_artifacts": (
                "Version the protocol, data or derivation inputs, code, environment, calibration state, random seeds, "
                "and complete analysis provenance."
            ),
            "negative_controls": [comparison, "measurement/process negative control appropriate to the declared mode"],
            "alternative_mechanism_tests": [
                f"Fit or test the primary {mediator} path and the declared alternative path under identical data and boundary conditions."
            ],
            "safety_and_risk_controls": (
                "Perform domain-appropriate hazard, ethics, environmental, numerical-stability, and equipment-limit review "
                "before any execution; this hierarchy does not authorize an experiment."
            ),
            "stopping_conditions": (
                "Stop or pause on a preregistered safety limit, invalid calibration/data-integrity check, "
                "failed negative control, unrecoverable assumption violation, or the minimal falsification condition."
            ),
        }
    return {
        "level_id": level_id,
        "proposal": layer,
        "proposal_source": f"deterministic_variant_{variant}",
        "self_critique": (
            "This proposal only operationalizes the frozen upstream roles. "
            "Unresolved implementation details remain explicit placeholders."
        ),
    }


def _llm_layer_proposal(
    level_id: str,
    candidate: dict[str, Any],
    contract: dict[str, Any],
    hierarchy: dict[str, Any],
    rejection_feedback: list[dict[str, Any]],
    llm_callable: Callable[..., dict[str, Any]] | None,
) -> dict[str, Any]:
    if llm_callable is None:
        try:
            from ._llm import call_llm_json
        except ImportError:
            from _llm import call_llm_json
        llm_callable = call_llm_json
    level = hierarchy_level(level_id)
    immutable_view = {
        "project_id": contract.get("project_id"),
        "gap_id": contract.get("gap_id"),
        "sub_hypothesis_id": contract.get("sub_hypothesis_id"),
        "research_mode": contract.get("research_mode"),
        "roles": contract.get("roles"),
        "comparison": contract.get("comparison"),
        "falsification": contract.get("falsification"),
        "source_evidence_ids": contract.get("source_evidence_ids"),
        "conclusion_scope": contract.get("conclusion_scope"),
        "contract_signature": contract.get("contract_signature"),
    }
    prompt_payload = {
        "immutable_contract": immutable_view,
        "current_candidate": {
            key: candidate.get(key)
            for key in (
                "statement", "mechanism", "competing_explanation",
                "discriminating_prediction", "boundary", "falsifier",
                "experiment_design",
            )
        },
        "accepted_hierarchy": hierarchy,
        "level_to_edit": level,
        "prior_rejection_feedback": rejection_feedback[-6:],
    }
    response = llm_callable(
        system=(
            "You refine one layer of a scientific hypothesis across any natural-science or engineering discipline. "
            "Return JSON only. The frozen contract is immutable and LLM output is not evidence. Do not change the "
            "project, gap, sub-hypothesis, research mode, causal roles, source ids, or conclusion scope. Do not invent "
            "a scientific entity, paper, source id, instrument, material, parameter value, sample size, threshold, "
            "dose, temperature, duration, model setting, or effect size. Exact numbers absent from a quoted bound source "
            f"must be represented as {TO_BE_OPTIMIZED}. Edit exactly the requested level. Make the primary and competing "
            "explanations discriminable and state how the proposal could fail."
        ),
        prompt=(
            f"Refine only {level_id}. Required fields are {list(level.get('required_fields') or [])}. "
            "Reuse source-bound entities verbatim. Preserve unresolved details as explicit placeholders. "
            "Self-critique ontology, provenance, causal order, confounding, alternative explanations, safety, "
            "and falsifiability.\n\n"
            f"INPUT_JSON:\n{json.dumps(prompt_payload, ensure_ascii=False, indent=2, default=str)[:24000]}\n\n"
            "Return exactly: "
            '{"level_id":"...", "proposal":{...}, "self_critique":"...", '
            '"hard_gate_risks":["..."], "claimed_contract_signature":"..."}'
        ),
        max_tokens=2200,
    )
    return response if isinstance(response, dict) else {}


_GENERIC_DRAFT_PATTERNS = (
    r"\bimprove (?:overall )?(?:performance|results|outcomes?)\b",
    r"\bbetter (?:overall )?(?:performance|results|outcomes?)\b",
    r"\badvanced (?:method|approach|model|technology)\b",
    r"\beffective (?:method|approach|solution)\b",
    r"\boptimi[sz]e (?:overall )?(?:performance|results|outcomes?)\b",
    r"(?:显著|有效|整体)?(?:提升|改善)(?:整体)?(?:性能|结果|效果)",
    r"(?:先进|有效)(?:方法|方案|模型|技术)",
)
MAX_FINAL_DRAFT_REFINEMENT_RETRIES = 2


def _llm_final_draft_refinement_proposal(
    candidate: dict[str, Any],
    contract: dict[str, Any],
    hierarchy: dict[str, Any],
    llm_callable: Callable[..., dict[str, Any]] | None,
    *,
    attempt: int = 1,
    prior_validation_feedback: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Ask the LLM to make the *rendered* draft precise without changing science.

    The five hierarchy layers make LLM proposals useful for scientific design, but
    they do not rewrite the user-facing hypothesis statement.  This final pass is
    deliberately narrow: it can only improve the wording of fields already bound
    by the frozen contract.  It is still a proposal and is accepted only after
    :func:`audit_llm_final_draft_refinement` succeeds.
    """
    if llm_callable is None:
        try:
            from ._llm import call_llm_json
        except ImportError:
            from _llm import call_llm_json
        llm_callable = call_llm_json
    immutable_view = {
        "project_id": contract.get("project_id"),
        "gap_id": contract.get("gap_id"),
        "sub_hypothesis_id": contract.get("sub_hypothesis_id"),
        "research_mode": contract.get("research_mode"),
        "roles": contract.get("roles"),
        "comparison": contract.get("comparison"),
        "falsification": contract.get("falsification"),
        "source_evidence_ids": contract.get("source_evidence_ids"),
        "conclusion_scope": contract.get("conclusion_scope"),
        "contract_signature": contract.get("contract_signature"),
    }
    draft_view = {
        key: candidate.get(key)
        for key in (
            "statement", "mechanism", "competing_explanation",
            "discriminating_prediction", "boundary", "falsifier",
            "final_object_claim_disclaimer",
        )
    }
    feedback = list(prior_validation_feedback or [])[-12:]
    response = llm_callable(
        system=(
            "You edit the final rendered wording of a scientific hypothesis in any natural-science or engineering "
            "discipline. Return JSON only. The frozen contract is immutable, and your wording is not evidence. "
            "Do not add a scientific entity, dataset, instrument, material, source, parameter, threshold, sample "
            "size, effect size, or causal fact. Reuse every frozen role and the comparison verbatim. Do not use "
            "generic claims such as 'improve performance', 'better results', 'advanced method', or 'effective "
            "solution'; name the exact contract-bound intervention, mediator, measurable outcome, comparison, "
            "boundary, and observable rejection condition instead. Preserve any conclusion-scope disclaimer exactly. "
            f"Use {TO_BE_OPTIMIZED} rather than inventing unsupported numeric settings."
        ),
        prompt=(
            f"This is final-draft refinement attempt {attempt}. Produce a concise, falsifiable final draft. The statement must contain the exact frozen intervention, "
            "mediator, outcome, and comparison. The mechanism and discriminating prediction must retain the same "
            "causal order. The falsifier must name the outcome and an explicit reject/fail/no-change condition. "
            "If the source contract does not resolve a detail, retain its existing explicit placeholder rather than "
            "guessing. If prior deterministic validation feedback is supplied, repair every listed violation; do not "
            "argue with or omit it.\n\n"
            f"INPUT_JSON:\n{json.dumps({
                'immutable_contract': immutable_view,
                'current_draft': draft_view,
                'accepted_hierarchy': hierarchy,
                'prior_validation_feedback': feedback,
            }, ensure_ascii=False, indent=2, default=str)[:24000]}\n\n"
            "Return exactly: "
            '{"statement":"...", "mechanism":"...", "competing_explanation":"...", '
            '"discriminating_prediction":"...", "boundary":"...", "falsifier":"...", '
            '"self_critique":"...", "claimed_contract_signature":"..."}'
        ),
        max_tokens=1800,
    )
    return response if isinstance(response, dict) else {}


def audit_llm_final_draft_refinement(
    proposal: dict[str, Any],
    contract: dict[str, Any],
    *,
    source_text_index: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Deterministically reject a fluent but non-specific final LLM draft."""
    normalized, precise_value_changes = normalize_unsupported_precise_values(
        proposal,
        source_text_index or {},
    )
    proposal = _mapping(normalized)
    failures: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    required_fields = (
        "statement", "mechanism", "competing_explanation",
        "discriminating_prediction", "boundary", "falsifier",
    )
    missing = [field for field in required_fields if not _compact(proposal.get(field))]
    if missing:
        failures.append({"code": "FINAL_DRAFT_REQUIRED_FIELDS_MISSING", "detail": missing})

    contract_audit = verify_frozen_contract(contract)
    if not contract_audit.get("valid"):
        failures.append({"code": "FROZEN_CONTRACT_INVALID", "detail": contract_audit})
    claimed_signature = _compact(proposal.get("claimed_contract_signature"))
    if claimed_signature != _compact(contract.get("contract_signature")):
        failures.append({
            "code": "FINAL_DRAFT_CONTRACT_SIGNATURE_MISMATCH",
            "detail": "The final wording proposal must echo the exact frozen contract signature.",
        })

    roles = _mapping(contract.get("roles"))
    anchors = {
        "input_or_intervention": _compact(
            _mapping(roles.get("input_or_intervention")).get("value")
        ),
        "mediator": _compact(_mapping(roles.get("mediator")).get("value")),
        "outcome": _compact(_mapping(roles.get("outcome")).get("value")),
        "comparison": _compact(contract.get("comparison")),
    }
    statement = _compact(proposal.get("statement"))
    mechanism = _compact(proposal.get("mechanism"))
    prediction = _compact(proposal.get("discriminating_prediction"))
    falsifier = _compact(proposal.get("falsifier"))
    for field, text, required_anchors in (
        (
            "statement",
            statement,
            ("input_or_intervention", "mediator", "outcome", "comparison"),
        ),
        ("mechanism", mechanism, ("input_or_intervention", "mediator", "outcome")),
        (
            "discriminating_prediction",
            prediction,
            ("input_or_intervention", "mediator", "outcome"),
        ),
        ("falsifier", falsifier, ("outcome",)),
    ):
        missing_anchors = [
            name for name in required_anchors
            if anchors.get(name) and not _contains_exact_anchor(text, anchors[name])
        ]
        if missing_anchors:
            failures.append({
                "code": "FINAL_DRAFT_NOT_BOUND_TO_FROZEN_PATH",
                "detail": {"field": field, "missing_anchors": missing_anchors},
            })

    if not re.search(
        r"\b(?:reject|falsif|fail|refut|unchanged|no change|does not)\w*\b|(?:拒绝|证伪|失败|不变|无变化)",
        falsifier,
        flags=re.IGNORECASE,
    ):
        failures.append({
            "code": "FINAL_DRAFT_FALSIFIER_NOT_OBSERVABLE",
            "detail": "The final falsifier needs an explicit reject/fail/no-change condition.",
        })

    rendered = json.dumps(
        {field: proposal.get(field) for field in required_fields},
        ensure_ascii=False,
        default=str,
    )
    generic_claims = [
        pattern for pattern in _GENERIC_DRAFT_PATTERNS
        if re.search(pattern, rendered, flags=re.IGNORECASE)
    ]
    if generic_claims:
        failures.append({
            "code": "FINAL_DRAFT_GENERIC_LANGUAGE",
            "detail": generic_claims,
        })
    if precise_value_changes:
        warnings.append({
            "code": "FINAL_DRAFT_UNSUPPORTED_PRECISE_VALUES_NORMALIZED",
            "detail": precise_value_changes,
        })

    return {
        "verdict": "PASS" if not failures else "REJECT",
        "hard_gate_passed": not failures,
        "failures": failures,
        "warnings": warnings,
        "normalized_proposal": proposal,
        "precise_value_changes": precise_value_changes,
        "contract_signature": contract.get("contract_signature"),
    }


def _numeric_literals(value: Any) -> list[str]:
    text = _compact(value)
    return _unique(
        [_compact(match.group(0)) for match in _NUMBER_RE.finditer(text)]
        + [_compact(match.group(0)) for match in _EXACT_ASSIGNMENT_RE.finditer(text)]
    )


def _number_in_bound_source(
    literal: str,
    source_ids: list[str],
    source_text_index: dict[str, str],
    source_quote: str = "",
) -> bool:
    normalized = re.sub(r"\s+", "", literal).lower()
    if source_quote and normalized in re.sub(r"\s+", "", source_quote).lower():
        return bool(source_ids)
    for source_id in source_ids:
        body = source_text_index.get(source_id, "")
        if body and normalized in re.sub(r"\s+", "", body).lower():
            return True
    return False


def _direct_source_ids(value: dict[str, Any]) -> list[str]:
    result: list[Any] = []
    for key in (
        "source_unit_ids", "source_ids", "evidence_ids",
        "source_evidence_ids", "reference_ids", "paper_ids",
    ):
        result.extend(_items(value.get(key)))
    return _unique(result)


def normalize_unsupported_precise_values(
    value: Any,
    source_text_index: dict[str, str],
) -> tuple[Any, list[dict[str, Any]]]:
    """Normalize unsupported exact values anywhere in a proposed layer.

    Parameter-space records are handled by ``normalize_parameter_space`` so
    their original value and optimization target can be retained in a richer
    audit record.  This pass catches numbers smuggled into prose fields such
    as sample size, stopping threshold, algorithm configuration, or safety
    limits.
    """
    changes: list[dict[str, Any]] = []

    def visit(
        node: Any,
        *,
        path: tuple[str, ...],
        inherited_ids: list[str],
        inherited_quote: str,
    ) -> Any:
        if isinstance(node, dict):
            local_ids = _direct_source_ids(node) or inherited_ids
            local_quote = _compact(node.get("source_quote")) or inherited_quote
            return {
                key: (
                    child
                    if key in {
                        "source_unit_ids", "source_ids", "evidence_ids",
                        "source_evidence_ids", "reference_ids", "paper_ids",
                        "source_quote",
                    }
                    else visit(
                        child,
                        path=path + (str(key),),
                        inherited_ids=local_ids,
                        inherited_quote=local_quote,
                    )
                )
                for key, child in node.items()
            }
        if isinstance(node, list):
            return [
                visit(
                    child,
                    path=path + (str(index),),
                    inherited_ids=inherited_ids,
                    inherited_quote=inherited_quote,
                )
                for index, child in enumerate(node)
            ]
        if not isinstance(node, str) or "parameter_space" in path:
            return node
        rendered = node
        unsupported = [
            literal for literal in _numeric_literals(rendered)
            if not _number_in_bound_source(
                literal, inherited_ids, source_text_index, inherited_quote
            )
        ]
        for literal in unsupported:
            rendered = rendered.replace(literal, TO_BE_OPTIMIZED)
        if unsupported:
            changes.append({
                "path": ".".join(path),
                "original_value": node,
                "unsupported_numeric_literals": unsupported,
                "replacement": TO_BE_OPTIMIZED,
            })
        return rendered

    normalized = visit(
        deepcopy(value),
        path=(),
        inherited_ids=[],
        inherited_quote="",
    )
    return normalized, changes


def normalize_parameter_space(
    layer: dict[str, Any],
    source_text_index: dict[str, str],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Replace unsupported exact parameter values with an honest placeholder."""
    normalized = deepcopy(layer)
    changes: list[dict[str, Any]] = []
    parameters = normalized.get("parameter_space")
    if not isinstance(parameters, list):
        return normalized, changes
    for index, raw in enumerate(parameters):
        if not isinstance(raw, dict):
            parameters[index] = {
                "name": f"parameter_{index + 1}",
                "value": TO_BE_OPTIMIZED,
                "status": "TO_BE_OPTIMIZED_UNSTRUCTURED_PARAMETER",
                "source_unit_ids": [],
                "original_value": _compact(raw),
            }
            changes.append({
                "index": index,
                "reason": "UNSTRUCTURED_PARAMETER",
                "replacement": TO_BE_OPTIMIZED,
            })
            continue
        value = _compact(raw.get("value") or raw.get("range"))
        literals = _numeric_literals(value)
        if not literals:
            raw.setdefault(
                "status",
                "TO_BE_OPTIMIZED" if value == TO_BE_OPTIMIZED else "QUALITATIVE_PARAMETER_SPACE",
            )
            continue
        source_ids = _unique(
            _items(raw.get("source_unit_ids"))
            + _items(raw.get("source_ids"))
            + _items(raw.get("evidence_ids"))
        )
        quote = _compact(raw.get("source_quote"))
        unsupported = [
            literal for literal in literals
            if not _number_in_bound_source(literal, source_ids, source_text_index, quote)
        ]
        if unsupported:
            raw["original_value"] = value
            raw["optimization_target"] = _first(raw.get("name"), value)
            raw["value"] = TO_BE_OPTIMIZED
            raw.pop("range", None)
            raw["status"] = "TO_BE_OPTIMIZED_UNSUPPORTED_PRECISE_VALUE"
            raw["unsupported_numeric_literals"] = unsupported
            changes.append({
                "index": index,
                "name": raw.get("name"),
                "unsupported_numeric_literals": unsupported,
                "replacement": TO_BE_OPTIMIZED,
            })
        else:
            raw["status"] = "SOURCE_LITERAL_VERIFIED"
            raw["verified_numeric_literals"] = literals
    return normalized, changes


def _field_present(value: Any) -> bool:
    if isinstance(value, str):
        return bool(_compact(value))
    if isinstance(value, dict):
        return bool(value)
    if isinstance(value, list):
        return bool(value)
    return value is not None


def _contains_exact_anchor(text: Any, anchor: Any) -> bool:
    rendered = _compact(text).lower()
    expected = _compact(anchor).lower()
    return bool(rendered and expected and expected in rendered)


def audit_hierarchy_layer(
    level_id: str,
    proposal: dict[str, Any],
    contract: dict[str, Any],
    *,
    source_text_index: dict[str, str] | None = None,
    claimed_contract_signature: str = "",
) -> dict[str, Any]:
    """Apply non-negotiable, deterministic checks to one proposed layer."""
    level = hierarchy_level(level_id)
    failures: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    normalized_proposal, global_parameter_changes = normalize_unsupported_precise_values(
        proposal,
        source_text_index or {},
    )
    proposal = _mapping(normalized_proposal)
    if global_parameter_changes:
        warnings.append({
            "code": "UNSUPPORTED_PRECISE_VALUES_NORMALIZED_OUTSIDE_PARAMETER_SPACE",
            "detail": global_parameter_changes,
        })
    contract_audit = verify_frozen_contract(contract)
    if not contract_audit["valid"]:
        failures.append({
            "code": "FROZEN_CONTRACT_INVALID",
            "detail": contract_audit,
        })
    if claimed_contract_signature and claimed_contract_signature != contract.get("contract_signature"):
        failures.append({
            "code": "FROZEN_CONTRACT_MUTATION_ATTEMPT",
            "detail": "The proposal did not return the exact frozen contract signature.",
        })
    if not level:
        failures.append({"code": "UNKNOWN_HIERARCHY_LEVEL", "detail": level_id})
    missing = [
        field for field in level.get("required_fields", ())
        if not _field_present(proposal.get(field))
    ]
    if missing:
        failures.append({"code": "REQUIRED_FIELDS_MISSING", "detail": missing})

    allowed_source_ids = set(
        _unique(
            _items(contract.get("source_evidence_ids"))
            + [
                source_id
                for role in _mapping(contract.get("roles")).values()
                if isinstance(role, dict)
                for source_id in _items(role.get("source_unit_ids"))
            ]
        )
    )
    proposed_source_ids = set(_collect_source_ids(proposal))
    foreign_source_ids = sorted(proposed_source_ids - allowed_source_ids)
    if foreign_source_ids:
        failures.append({
            "code": "FOREIGN_OR_INVENTED_SOURCE_ID",
            "detail": foreign_source_ids,
        })

    frozen_roles = _mapping(contract.get("roles"))
    frozen_input = _compact(
        _mapping(frozen_roles.get("input_or_intervention")).get("value")
    )
    frozen_mediator = _compact(
        _mapping(frozen_roles.get("mediator")).get("value")
    )
    frozen_outcome = _compact(
        _mapping(frozen_roles.get("outcome")).get("value")
    )
    if level_id == "SCIENTIFIC_CLAIM_TOPOLOGY":
        primary = _compact(proposal.get("primary_mechanism"))
        missing_anchors = [
            role for role, value in (
                ("input_or_intervention", frozen_input),
                ("mediator", frozen_mediator),
                ("outcome", frozen_outcome),
            )
            if not _contains_exact_anchor(primary, value)
        ]
        if missing_anchors:
            failures.append({
                "code": "PRIMARY_MECHANISM_CHANGED_FROZEN_CAUSAL_PATH",
                "detail": missing_anchors,
            })
        distinction = _compact(proposal.get("scientific_distinction"))
        if not (
            _contains_exact_anchor(distinction, frozen_mediator)
            and _contains_exact_anchor(distinction, frozen_outcome)
        ):
            failures.append({
                "code": "SCIENTIFIC_DISTINCTION_NOT_BOUND_TO_FROZEN_PATH",
                "detail": "The distinction must explicitly compare explanations for the frozen mediator and outcome.",
            })

    if level_id == "OPERATIONALIZATION_AND_DISCRIMINATION":
        decisive = _compact(proposal.get("decisive_prediction"))
        falsifier = _compact(proposal.get("minimal_falsification_condition"))
        if not (
            _contains_exact_anchor(decisive, frozen_input)
            and _contains_exact_anchor(decisive, frozen_mediator)
            and _contains_exact_anchor(decisive, frozen_outcome)
        ):
            failures.append({
                "code": "DECISIVE_PREDICTION_NOT_BOUND_TO_FROZEN_PATH",
                "detail": "The decisive prediction must retain the frozen input, mediator, and outcome.",
            })
        if not _contains_exact_anchor(falsifier, frozen_outcome) or not re.search(
            r"\b(?:reject|falsif|fail|refut|unchanged|no change|does not)\w*\b",
            falsifier,
            flags=re.IGNORECASE,
        ):
            failures.append({
                "code": "MINIMAL_FALSIFIER_NOT_OBSERVABLE",
                "detail": "The falsifier must name the frozen outcome and an explicit rejection condition.",
            })

    ontology_audits: dict[str, Any] = {}
    if level_id == "ENTITY_AND_CAUSAL_ROLE_SPECIFICATION":
        for role in ("input_or_intervention", "target_object", "mediator", "outcome"):
            record = _mapping(proposal.get(role))
            frozen = _mapping(_mapping(contract.get("roles")).get(role))
            if _compact(record.get("value")) != _compact(frozen.get("value")):
                failures.append({
                    "code": "FROZEN_CAUSAL_ROLE_MUTATION",
                    "detail": {
                        "role": role,
                        "expected": frozen.get("value"),
                        "received": record.get("value"),
                    },
                })
            assessment = _scientific_entity_assessment(
                record.get("value"),
                role=role,
                source_unit_ids=_items(record.get("source_unit_ids")),
                research_mode=_compact(contract.get("research_mode")),
                target_outcome=_compact(
                    _mapping(_mapping(contract.get("roles")).get("outcome")).get("value")
                ),
            )
            ontology_audits[role] = assessment
            if not assessment.get("ontology_passed"):
                failures.append({
                    "code": "ENTITY_ONTOLOGY_REJECTED",
                    "detail": {"role": role, "assessment": assessment},
                })
        for plural, singular in (
            ("common_causes", "common_cause"),
            ("alternative_paths", "alternative_path"),
        ):
            audits: list[dict[str, Any]] = []
            for item in _items(proposal.get(plural)):
                record = _mapping(item)
                assessment = _scientific_entity_assessment(
                    record.get("value"),
                    role=singular,
                    source_unit_ids=_items(record.get("source_unit_ids")),
                    research_mode=_compact(contract.get("research_mode")),
                )
                audits.append(assessment)
                if not assessment.get("ontology_passed"):
                    failures.append({
                        "code": "ENTITY_ONTOLOGY_REJECTED",
                        "detail": {"role": singular, "assessment": assessment},
                    })
            ontology_audits[plural] = audits

    if level_id == "IMPLEMENTATION_AND_PARAMETER_SPACE":
        implementation_roles = (
            ("materials_or_inputs", "material_or_input", True),
            ("model_or_system", "model_or_system", False),
            ("instruments_or_software", "instrument_or_software", True),
            (
                "algorithm_or_procedure_configuration",
                "algorithm_or_procedure_configuration",
                False,
            ),
        )
        for field, role, plural in implementation_roles:
            raw_items = _items(proposal.get(field)) if plural else [proposal.get(field)]
            audits: list[dict[str, Any]] = []
            for raw in raw_items:
                record = _mapping(raw)
                if not record:
                    assessment = {
                        "role": role,
                        "candidate": _compact(raw),
                        "ontology_passed": False,
                        "reason": "Implementation entities must be structured ontology records.",
                    }
                else:
                    assessment = _scientific_entity_assessment(
                        record.get("value"),
                        role=role,
                        source_unit_ids=_items(record.get("source_unit_ids")),
                        research_mode=_compact(contract.get("research_mode")),
                    )
                    if role == "material_or_input" and _compact(record.get("value")) != frozen_input:
                        assessment = {
                            **assessment,
                            "ontology_passed": False,
                            "reason": "Materials/inputs may refine implementation but cannot replace the frozen input role.",
                        }
                    if role == "model_or_system":
                        frozen_object = _compact(
                            _mapping(frozen_roles.get("target_object")).get("value")
                        )
                        if _compact(record.get("value")) != frozen_object:
                            assessment = {
                                **assessment,
                                "ontology_passed": False,
                                "reason": "The implementation model/system must preserve the frozen target object.",
                            }
                    if (
                        role in {
                            "instrument_or_software",
                            "algorithm_or_procedure_configuration",
                        }
                        and _compact(record.get("value"))
                        not in {TO_BE_OPTIMIZED, UNRESOLVED_ENTITY}
                    ):
                        ids = _items(record.get("source_unit_ids"))
                        literal_supported = bool(record.get("source_literal_verified"))
                        if not literal_supported:
                            literal_supported = any(
                                _compact(record.get("value")).lower()
                                in _compact((source_text_index or {}).get(source_id)).lower()
                                for source_id in ids
                                if _compact((source_text_index or {}).get(source_id))
                            )
                        if literal_supported:
                            record["source_literal_verified"] = True
                        else:
                            assessment = {
                                **assessment,
                                "ontology_passed": False,
                                "reason": (
                                    "A concrete instrument, software package, or configuration "
                                    "must occur literally in its bound source; otherwise use TO_BE_OPTIMIZED."
                                ),
                            }
                audits.append(assessment)
                if not assessment.get("ontology_passed"):
                    failures.append({
                        "code": "IMPLEMENTATION_ENTITY_ONTOLOGY_REJECTED",
                        "detail": {"field": field, "assessment": assessment},
                    })
            ontology_audits[field] = audits if plural else (audits[0] if audits else {})

    if level_id == "VALIDATION_SAFETY_AND_REPRODUCIBILITY":
        temporal = _compact(proposal.get("temporal_order"))
        if not all(
            _contains_exact_anchor(temporal, value)
            for value in (frozen_input, frozen_mediator, frozen_outcome)
        ):
            failures.append({
                "code": "TEMPORAL_ORDER_NOT_BOUND_TO_FROZEN_PATH",
                "detail": "Temporal validation must order the frozen input, mediator, and outcome.",
            })
        validation_text = json.dumps(proposal, ensure_ascii=False, default=str).lower()
        structural_markers = {
            "replication": ("replic", "independent"),
            "reproducibility": ("reproduc", "version"),
            "negative_control": ("negative control",),
            "safety": ("safety", "risk", "hazard"),
            "stopping_condition": ("stop", "pause", "terminate"),
        }
        missing_validation = [
            name for name, markers in structural_markers.items()
            if not any(marker in validation_text for marker in markers)
        ]
        if missing_validation:
            failures.append({
                "code": "VALIDATION_STRUCTURE_INCOMPLETE",
                "detail": missing_validation,
            })

    parameter_changes: list[dict[str, Any]] = []
    if level_id == "IMPLEMENTATION_AND_PARAMETER_SPACE":
        normalized_proposal, parameter_changes = normalize_parameter_space(
            proposal, source_text_index or {}
        )
        if parameter_changes:
            warnings.append({
                "code": "UNSUPPORTED_PRECISE_VALUES_NORMALIZED",
                "detail": parameter_changes,
            })
        unresolved_policy = _compact(normalized_proposal.get("precise_value_policy"))
        if TO_BE_OPTIMIZED not in unresolved_policy:
            failures.append({
                "code": "PRECISE_VALUE_POLICY_MISSING",
                "detail": f"The policy must explicitly use {TO_BE_OPTIMIZED}.",
            })

    return {
        "level_id": level_id,
        "verdict": "PASS" if not failures else "REJECT",
        "hard_gate_passed": not failures,
        "failures": failures,
        "warnings": warnings,
        "ontology_audits": ontology_audits,
        "normalized_proposal": normalized_proposal,
        "contract_signature": contract.get("contract_signature"),
    }


def _layer_quality_score(level_id: str, proposal: dict[str, Any], audit: dict[str, Any]) -> float:
    if not audit.get("hard_gate_passed"):
        return 0.0
    required = hierarchy_level(level_id).get("required_fields", ())
    completeness = sum(_field_present(proposal.get(field)) for field in required) / max(1, len(required))
    text = json.dumps(proposal, ensure_ascii=False, default=str).lower()
    criteria = {
        "SCIENTIFIC_CLAIM_TOPOLOGY": (
            "competing", "boundary", "distinguish",
        ),
        "ENTITY_AND_CAUSAL_ROLE_SPECIFICATION": (
            "ontology", "source_unit_ids", "alternative",
        ),
        "OPERATIONALIZATION_AND_DISCRIMINATION": (
            "control", "counterfactual", "decisive", "falsif",
        ),
        "IMPLEMENTATION_AND_PARAMETER_SPACE": (
            "parameter", "instrument", TO_BE_OPTIMIZED.lower(),
        ),
        "VALIDATION_SAFETY_AND_REPRODUCIBILITY": (
            "replic", "reproduc", "negative control", "stop", "safety",
        ),
    }.get(level_id, ())
    feature_score = sum(marker in text for marker in criteria) / max(1, len(criteria))
    provenance = min(
        1.0,
        text.count("source_unit_ids") / 4.0
        if level_id == "ENTITY_AND_CAUSAL_ROLE_SPECIFICATION"
        else 1.0,
    )
    penalty = min(0.2, 0.03 * len(audit.get("warnings") or []))
    return round(max(0.0, 0.55 * completeness + 0.3 * feature_score + 0.15 * provenance - penalty), 4)


def select_hierarchy_proposal(
    level_id: str,
    audited_proposals: list[dict[str, Any]],
) -> dict[str, Any]:
    """Hard gates dominate; soft scores only rank surviving proposals."""
    eligible = [
        item for item in audited_proposals
        if _mapping(item.get("audit")).get("hard_gate_passed")
    ]
    if not eligible:
        return {
            "status": "NO_PASSING_PROPOSAL",
            "level_id": level_id,
            "winner": {},
            "rejected": audited_proposals,
        }
    ordered = sorted(
        eligible,
        key=lambda item: (
            -float(item.get("quality_score") or 0.0),
            _compact(item.get("proposal_source")),
        ),
    )
    winner = ordered[0]
    return {
        "status": "SELECTED",
        "level_id": level_id,
        "winner": winner,
        "rejected": [item for item in audited_proposals if item is not winner],
        "selection_rule": "deterministic_hard_gate_then_pairwise_quality",
    }


def _apply_hierarchy_to_candidate(
    candidate: dict[str, Any],
    hierarchy: dict[str, Any],
) -> dict[str, Any]:
    refined = deepcopy(candidate)
    topology = _mapping(hierarchy.get("SCIENTIFIC_CLAIM_TOPOLOGY"))
    entities = _mapping(hierarchy.get("ENTITY_AND_CAUSAL_ROLE_SPECIFICATION"))
    operations = _mapping(hierarchy.get("OPERATIONALIZATION_AND_DISCRIMINATION"))
    validation = _mapping(hierarchy.get("VALIDATION_SAFETY_AND_REPRODUCIBILITY"))
    primary = _compact(topology.get("primary_mechanism"))
    if primary:
        refined["mechanism"] = primary
    competitors = _items(topology.get("competing_mechanisms"))
    if competitors:
        refined["competing_explanation"] = _compact(competitors[0])
    boundaries = _items(topology.get("boundary_conditions"))
    if boundaries:
        refined["boundary"] = _compact(boundaries[0])
    if operations:
        refined["discriminating_prediction"] = _compact(
            operations.get("decisive_prediction")
        )
        refined["falsifier"] = _compact(
            operations.get("minimal_falsification_condition")
        )
        refined["experiment_design"] = {
            **_mapping(refined.get("experiment_design")),
            "control": operations.get("control_or_comparator"),
            "counterfactual": operations.get("counterfactual"),
            "identification_strategy": operations.get("identification_strategy"),
            "readout": operations.get("measurement_variables"),
            "failure_criteria": operations.get("minimal_falsification_condition"),
            "time_course": validation.get("temporal_order"),
            "replicates": validation.get("sample_and_replication"),
            "statistical_test": validation.get("statistical_or_formal_analysis"),
            "negative_controls": validation.get("negative_controls"),
            "safety_and_stopping": {
                "safety": validation.get("safety_and_risk_controls"),
                "stopping_conditions": validation.get("stopping_conditions"),
            },
        }
    if entities:
        refined["claim"] = {
            **_mapping(refined.get("claim")),
            "object": _compact(_mapping(entities.get("target_object")).get("value")),
            "intervention": _compact(_mapping(entities.get("input_or_intervention")).get("value")),
            "mediator": _compact(_mapping(entities.get("mediator")).get("value")),
            "expected_result": _compact(_mapping(entities.get("outcome")).get("value")),
        }
    refined["scientific_hypothesis_hierarchy"] = hierarchy
    return refined


def run_hierarchical_hypothesis_search(
    project: dict[str, Any],
    gap: dict[str, Any],
    seed_candidate: dict[str, Any],
    *,
    hypothesis_package: dict[str, Any] | None = None,
    use_llm: bool = False,
    llm_callable: Callable[..., dict[str, Any]] | None = None,
    deterministic_variants: int = 2,
    max_final_draft_refinement_retries: int = MAX_FINAL_DRAFT_REFINEMENT_RETRIES,
) -> dict[str, Any]:
    """Run bounded, feedback-driven, one-layer-at-a-time hypothesis search."""
    started = time.time()
    contract = build_frozen_hypothesis_contract(
        project, gap, seed_candidate, hypothesis_package
    )
    source_index = build_source_text_index(project, gap, _mapping(
        seed_candidate.get("socrates_mechanism_contract")
    ))
    hierarchy: dict[str, Any] = {}
    accepted_steps: list[dict[str, Any]] = []
    rejected_steps: list[dict[str, Any]] = []
    rejection_feedback: list[dict[str, Any]] = []
    blocked_level = ""

    for level in HIERARCHY_LEVELS:
        level_id = str(level["level_id"])
        proposals: list[dict[str, Any]] = []
        for variant in range(max(1, min(3, int(deterministic_variants or 1)))):
            proposals.append(
                deterministic_layer_proposal(
                    level_id, seed_candidate, contract, variant=variant
                )
            )
        if use_llm:
            try:
                llm_proposal = _llm_layer_proposal(
                    level_id,
                    seed_candidate,
                    contract,
                    hierarchy,
                    rejection_feedback,
                    llm_callable,
                )
                if llm_proposal:
                    llm_proposal["proposal_source"] = "external_llm_single_level_edit"
                    proposals.append(llm_proposal)
            except Exception as exc:
                rejection_feedback.append({
                    "level_id": level_id,
                    "code": "LLM_PROPOSAL_FAILED",
                    "detail": f"{type(exc).__name__}: {exc}",
                })

        audited: list[dict[str, Any]] = []
        for proposal_record in proposals:
            proposal = _mapping(proposal_record.get("proposal"))
            audit = audit_hierarchy_layer(
                level_id,
                proposal,
                contract,
                source_text_index=source_index,
                claimed_contract_signature=_compact(
                    proposal_record.get("claimed_contract_signature")
                ),
            )
            normalized = _mapping(audit.get("normalized_proposal"))
            record = {
                "level_id": level_id,
                "proposal_source": _compact(
                    proposal_record.get("proposal_source")
                ) or "unknown",
                "proposal": normalized,
                "self_critique": _compact(proposal_record.get("self_critique")),
                "hard_gate_risks": _items(proposal_record.get("hard_gate_risks")),
                "audit": audit,
                "quality_score": _layer_quality_score(level_id, normalized, audit),
            }
            audited.append(record)
        selection = select_hierarchy_proposal(level_id, audited)
        rejected_steps.extend(selection.get("rejected") or [])
        for item in selection.get("rejected") or []:
            for failure in _items(_mapping(item.get("audit")).get("failures")):
                rejection_feedback.append({
                    "level_id": level_id,
                    "proposal_source": item.get("proposal_source"),
                    **_mapping(failure),
                })
        if selection.get("status") != "SELECTED":
            blocked_level = level_id
            break
        winner = _mapping(selection.get("winner"))
        hierarchy[level_id] = deepcopy(_mapping(winner.get("proposal")))
        accepted_steps.append({
            "level": level.get("level"),
            "level_id": level_id,
            "proposal_source": winner.get("proposal_source"),
            "quality_score": winner.get("quality_score"),
            "audit": winner.get("audit"),
        })

    status = "READY" if len(hierarchy) == len(HIERARCHY_LEVELS) else "BLOCKED"
    refined = _apply_hierarchy_to_candidate(seed_candidate, hierarchy)
    final_draft_refinement: dict[str, Any] = {
        "status": "NOT_REQUESTED",
        "selected": False,
        "reason": "use_llm=False" if not use_llm else "hierarchy_not_ready",
        "max_retries": 0,
        "attempts": [],
    }
    if use_llm and status == "READY":
        allowed_retries = max(
            0,
            min(MAX_FINAL_DRAFT_REFINEMENT_RETRIES, int(max_final_draft_refinement_retries or 0)),
        )
        attempts: list[dict[str, Any]] = []
        feedback: list[dict[str, Any]] = []
        selected_audit: dict[str, Any] = {}
        selected = False
        for attempt in range(1, allowed_retries + 2):
            try:
                final_proposal = _llm_final_draft_refinement_proposal(
                    refined,
                    contract,
                    hierarchy,
                    llm_callable,
                    attempt=attempt,
                    prior_validation_feedback=feedback,
                )
                final_audit = audit_llm_final_draft_refinement(
                    final_proposal,
                    contract,
                    source_text_index=source_index,
                )
                attempt_record = {
                    "attempt": attempt,
                    "status": "SELECTED" if final_audit.get("hard_gate_passed") else "REJECTED",
                    "proposal": final_audit.get("normalized_proposal"),
                    "audit": final_audit,
                }
                attempts.append(attempt_record)
                if final_audit.get("hard_gate_passed"):
                    selected = True
                    selected_audit = final_audit
                    break
                feedback = [
                    {"code": item.get("code"), "detail": item.get("detail")}
                    for item in _items(final_audit.get("failures"))
                    if isinstance(item, dict)
                ]
            except Exception as exc:
                failure = {
                    "code": "FINAL_DRAFT_LLM_CALL_FAILED",
                    "detail": f"{type(exc).__name__}: {exc}",
                }
                attempts.append({
                    "attempt": attempt,
                    "status": "FAILED",
                    "reason": failure["detail"],
                })
                feedback = [failure]
        final_draft_refinement = {
            "status": "SELECTED" if selected else ("FAILED" if not attempts or all(item.get("status") == "FAILED" for item in attempts) else "REJECTED"),
            "selected": selected,
            "max_retries": allowed_retries,
            "attempts": attempts,
            "retry_count": max(0, len(attempts) - 1),
            "fallback_to_deterministic_draft": not selected,
            "proposal": (
                selected_audit.get("normalized_proposal")
                if selected
                else (attempts[-1].get("proposal") if attempts else {})
            ),
            "audit": (
                selected_audit
                if selected
                else (attempts[-1].get("audit") if attempts else {})
            ),
        }
        if selected:
            for field in (
                "statement", "mechanism", "competing_explanation",
                "discriminating_prediction", "boundary", "falsifier",
            ):
                refined[field] = selected_audit["normalized_proposal"][field]
    candidate_value_payload = {
        "source_evidence_ids": _items(contract.get("source_evidence_ids")),
        **{
            key: refined.get(key)
            for key in (
                "statement", "mechanism", "boundary", "falsifier",
                "discriminating_prediction", "test_plan", "claim",
                "experiment_design", "verification_plan",
            )
            if key in refined
        },
    }
    normalized_candidate_values, candidate_value_changes = (
        normalize_unsupported_precise_values(
            candidate_value_payload,
            source_index,
        )
    )
    if isinstance(normalized_candidate_values, dict):
        for key, value in normalized_candidate_values.items():
            if key != "source_evidence_ids":
                refined[key] = value
    result = {
        "schema_version": HIERARCHY_VERSION,
        "status": status,
        "hard_gate_passed": status == "READY",
        "blocked_level": blocked_level,
        "frozen_contract": contract,
        "contract_signature": contract.get("contract_signature"),
        "hierarchy": hierarchy,
        "accepted_steps": accepted_steps,
        "rejected_steps": rejected_steps,
        "rejection_feedback": rejection_feedback,
        "candidate_precise_value_normalizations": candidate_value_changes,
        "search_policy": {
            "edit_granularity": "exactly_one_hierarchy_level_per_step",
            "llm_role": "bounded_layer_proposal_and_contract_bound_final_draft_refinement_with_repair_retries",
            "deterministic_gate_authority": True,
            "failed_proposals_retained_as_feedback": True,
            "final_draft_refinement_retries": max(0, min(
                MAX_FINAL_DRAFT_REFINEMENT_RETRIES,
                int(max_final_draft_refinement_retries or 0),
            )),
            "unsupported_precise_values": TO_BE_OPTIMIZED,
            "execution_authorized": False,
        },
        "final_draft_refinement": final_draft_refinement,
        "refined_candidate": refined,
        "elapsed_ms": round((time.time() - started) * 1000.0, 3),
    }
    refined["hierarchical_search"] = {
        key: value for key, value in result.items()
        if key != "refined_candidate"
    }
    refined["llm_final_draft_refinement"] = final_draft_refinement
    result["refined_candidate"] = refined
    return result


def audit_hierarchical_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    """Re-audit a candidate after mutation without trusting cached verdicts."""
    search = _mapping(candidate.get("hierarchical_search"))
    contract = _mapping(search.get("frozen_contract"))
    hierarchy = _mapping(candidate.get("scientific_hypothesis_hierarchy"))
    if not search or not contract or not hierarchy:
        return {
            "verdict": "NOT_PRESENT",
            "hard_gate_passed": False,
            "missing": ["hierarchical_search", "frozen_contract", "scientific_hypothesis_hierarchy"],
        }
    contract_audit = verify_frozen_contract(contract)
    level_audits: list[dict[str, Any]] = []
    for level in HIERARCHY_LEVELS:
        level_id = str(level["level_id"])
        proposal = _mapping(hierarchy.get(level_id))
        level_audits.append(audit_hierarchy_layer(level_id, proposal, contract))
    failures = [
        item for item in level_audits if not item.get("hard_gate_passed")
    ]
    cached_signature = _compact(search.get("contract_signature"))
    signature_matches = bool(
        cached_signature and cached_signature == contract.get("contract_signature")
    )
    passed = bool(contract_audit.get("valid") and signature_matches and not failures)
    return {
        "verdict": "PASS" if passed else "REJECT",
        "hard_gate_passed": passed,
        "contract_audit": contract_audit,
        "contract_signature_matches": signature_matches,
        "level_audits": level_audits,
        "failures": failures,
    }


def recombine_hierarchical_candidates(
    primary: dict[str, Any],
    secondary: dict[str, Any],
) -> dict[str, Any]:
    """Recombine only candidates governed by the exact same frozen contract."""
    first_search = _mapping(primary.get("hierarchical_search"))
    second_search = _mapping(secondary.get("hierarchical_search"))
    first_signature = _compact(first_search.get("contract_signature"))
    second_signature = _compact(second_search.get("contract_signature"))
    if not first_signature or first_signature != second_signature:
        return {
            "status": "REJECTED_CONTRACT_MISMATCH",
            "reason": "Cross-gap or cross-contract recombination cannot mutate the frozen scientific question.",
            "primary_contract_signature": first_signature,
            "secondary_contract_signature": second_signature,
        }
    first_hierarchy = _mapping(primary.get("scientific_hypothesis_hierarchy"))
    second_hierarchy = _mapping(secondary.get("scientific_hypothesis_hierarchy"))
    child = deepcopy(primary)
    child_hierarchy: dict[str, Any] = {}
    for level in HIERARCHY_LEVELS:
        level_id = str(level["level_id"])
        source = first_hierarchy if int(level["level"]) % 2 else second_hierarchy
        child_hierarchy[level_id] = deepcopy(_mapping(source.get(level_id)))
    child = _apply_hierarchy_to_candidate(child, child_hierarchy)
    child.setdefault("lineage", []).append({
        "operation": "same_contract_hierarchical_recombination",
        "primary_candidate_id": primary.get("candidate_id"),
        "secondary_candidate_id": secondary.get("candidate_id"),
        "contract_signature": first_signature,
    })
    audit = audit_hierarchical_candidate(child)
    if not audit.get("hard_gate_passed"):
        return {
            "status": "REJECTED_RECOMBINATION_AUDIT",
            "audit": audit,
        }
    return {"status": "READY", "candidate": child, "audit": audit}
