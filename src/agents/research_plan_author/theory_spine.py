"""Compile frozen theory artifacts into a deterministic audit registry.

The compiler deliberately creates only document-local labels.  It never adds
scientific content, bibliography records, or upstream identifiers; every
compiled unit retains reverse references to the frozen Author handoff.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
import json
import re
from typing import Any

from jsonschema import Draft202012Validator


THEORY_SPINE_SCHEMA_VERSION = "research_plan_theory_spine_v1"

_NONEMPTY = {"type": "string", "minLength": 1}
_STRING_LIST = {"type": "array", "items": _NONEMPTY, "uniqueItems": True}
_LOCAL_LEMMA_ID = re.compile(r"^TS-L-[1-9][0-9]*$")
_LOCAL_PROOF_OBLIGATION_ID = re.compile(r"^TS-PO-[1-9][0-9]*$")
_LOCAL_FALSIFIER_ID = re.compile(r"^TS-F-[1-9][0-9]*$")
_LOCAL_BRANCH_ID = re.compile(r"^TS-BR-[A-Z0-9][A-Z0-9_-]*$")
_VISIBLE_LOCAL_ID = re.compile(r"(?<![A-Za-z0-9_-])TS-(?:L|PO|F|BR)-[A-Za-z0-9_-]+(?![A-Za-z0-9_-])")
_UNRESOLVED_STATUSES = {
    "missing",
    "needs_human_input",
    "requires_human_review",
    "review_required",
    "unresolved",
}


THEORY_SPINE_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "Research Plan Theory Spine v1",
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema_version",
        "template_family",
        "enabled",
        "compiler_status",
        "lemma_units",
        "proof_obligations",
        "falsifiers",
        "decision_branches",
    ],
    "properties": {
        "schema_version": {"const": THEORY_SPINE_SCHEMA_VERSION},
        "template_family": _NONEMPTY,
        "enabled": {"type": "boolean"},
        "compiler_status": {"enum": ["ready", "no_auditable_lemma_input", "not_applicable"]},
        "lemma_units": {"type": "array", "items": {"type": "object"}},
        "proof_obligations": {"type": "array", "items": {"type": "object"}},
        "falsifiers": {"type": "array", "items": {"type": "object"}},
        "decision_branches": {"type": "array", "items": {"type": "object"}},
    },
}


class TheorySpineError(ValueError):
    """Raised when a deterministic theory registry cannot be source-bounded."""


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _text(value: object) -> str:
    return str(value or "").strip()


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _text_list(value: object) -> list[str]:
    if isinstance(value, str):
        return [_text(value)] if _text(value) else []
    if not isinstance(value, Sequence) or isinstance(value, (bytes, bytearray)):
        return []
    return sorted({_text(item) for item in value if _text(item)})


def _record_references(record: Mapping[str, Any], *field_names: str) -> set[str]:
    references: set[str] = set()
    for field_name in field_names:
        references.update(_text_list(record.get(field_name)))
    return references


def _reference_tokens(record: Mapping[str, Any]) -> set[str]:
    return {
        *(_record_references(record, "symbol_references", "symbols")),
        *(_record_references(record, "variable_references", "variables")),
    }


def _stable_records(records: object, *, identifier_field: str) -> list[dict[str, Any]]:
    if not isinstance(records, list):
        return []
    values = [dict(record) for record in records if isinstance(record, Mapping) and _text(record.get(identifier_field))]
    return sorted(values, key=lambda record: (_text(record.get(identifier_field)), _canonical_json(record)))


def _formal_records(author_context: Mapping[str, Any]) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    formal_reasoning = _mapping(author_context.get("formal_reasoning"))
    records: dict[str, dict[str, Any]] = {}
    kinds: dict[str, str] = {}
    collections = (
        ("definitions", "definition_id", "definition"),
        ("assumptions", "assumption_id", "assumption"),
        ("propositions", "proposition_id", "proposition"),
        ("proof_obligations", "obligation_id", "proof_obligation"),
    )
    for collection, identifier_field, kind in collections:
        for record in _stable_records(formal_reasoning.get(collection), identifier_field=identifier_field):
            identifier = _text(record.get(identifier_field))
            records.setdefault(identifier, record)
            kinds.setdefault(identifier, kind)
    derivation = _mapping(formal_reasoning.get("forward_derivation"))
    for record in _stable_records(derivation.get("steps"), identifier_field="step_id"):
        identifier = _text(record.get("step_id"))
        records.setdefault(identifier, record)
        kinds.setdefault(identifier, "forward_derivation_step")
    return records, kinds


def _unknown_records(
    preparation: Mapping[str, Any],
    source_registry: Mapping[str, Any] | None,
) -> list[dict[str, Any]]:
    """Return source-registry unknown IDs plus their frozen records.

    ``source_registry`` is available in Author preparation.  Direct library
    callers receive the same canonical ``unknown-N`` IDs by constructing the
    frozen registry from the supplied preparation rather than minting a local
    unknown-item identifier.
    """

    resolved_registry = source_registry
    if not isinstance(resolved_registry, Mapping):
        from .source_registry import build_frozen_source_registry

        resolved_registry = build_frozen_source_registry(preparation)
    records = [
        {
            "source_item_id": _text(record.get("source_item_id")),
            "original_item": deepcopy(_mapping(record.get("original_item"))),
        }
        for record in resolved_registry.get("unknown_items") or []
        if isinstance(record, Mapping) and _text(record.get("source_item_id"))
    ]
    return sorted(records, key=lambda record: (_text(_mapping(record["original_item"]).get("field_path")), record["source_item_id"]))


def _formal_reference_for_unknown(record: Mapping[str, Any], formal_ids: set[str]) -> str:
    field_path = _text(record.get("field_path"))
    match = re.search(r"(?:definitions|assumptions|propositions|proof_obligations|forward_derivation(?:\.steps)?)\.([A-Za-z][A-Za-z0-9_-]*)", field_path)
    if match and match.group(1) in formal_ids:
        return match.group(1)
    return ""


def _status(value: object) -> str:
    raw = _text(value).casefold()
    if raw in {"candidate_formalization", "proposed", "user_declared"}:
        return "candidate"
    return "unverified"


def _local_branch_token(identifier: str) -> str:
    token = re.sub(r"[^A-Z0-9]+", "-", identifier.upper()).strip("-")
    return token or "UPSTREAM"


def _outcome_branch_id(outcome_ids: set[str], *candidates: str) -> list[str]:
    return [candidate for candidate in candidates if candidate in outcome_ids][:1]


def _explicit_formal_references(record: Mapping[str, Any], formal_ids: set[str]) -> set[str]:
    references = _record_references(
        record,
        "premises",
        "depends_on",
        "assumption_ids",
        "formal_reference_ids",
        "required_formal_reference_ids",
    )
    return references & formal_ids


def _matching_formal_ids(
    record: Mapping[str, Any],
    *,
    candidates: Mapping[str, Mapping[str, Any]],
) -> set[str]:
    tokens = _reference_tokens(record)
    if not tokens:
        return set()
    return {
        identifier
        for identifier, candidate in candidates.items()
        if tokens & _reference_tokens(candidate)
    }


def _counterexample_classification(record: Mapping[str, Any]) -> str:
    validity = _text(record.get("validity")).casefold()
    conclusion = _mapping(record.get("conclusion_check"))
    conclusion_result = _text(conclusion.get("result")).casefold()
    if validity in {"valid_counterexample", "valid", "all_assumptions_satisfied"} and conclusion_result in {
        "counterexample",
        "contradicted",
        "refuted",
        "violated",
    }:
        return "would_falsify"
    if validity == "boundary_case":
        return "scope_delimiter"
    if validity == "assumptions_not_satisfied":
        return "assumptions_not_satisfied"
    return "no_information"


def build_theory_spine(
    preparation: Mapping[str, Any],
    *,
    routing: Mapping[str, Any],
    source_registry: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Compile frozen mathematical-theory records into local audit units.

    Internal IDs such as ``TS-L-1`` and ``TS-BR-PO1-NO_INFORMATION`` are
    document-local.  Their reader-facing ``display_label`` values retain the
    conventional ``L1``/``PO1``/``F1`` notation, while source-reference fields
    contain exclusively IDs supplied by the frozen handoff records.
    """

    template_family = _text(routing.get("template_family"))
    empty_spine = {
        "schema_version": THEORY_SPINE_SCHEMA_VERSION,
        "template_family": template_family,
        "enabled": False,
        "compiler_status": "not_applicable",
        "lemma_units": [],
        "proof_obligations": [],
        "falsifiers": [],
        "decision_branches": [],
    }
    if template_family != "mathematics_theory":
        return empty_spine

    author_context = _mapping(_mapping(preparation.get("source_bundle")).get("author_context"))
    formal_reasoning = _mapping(author_context.get("formal_reasoning"))
    formal_by_id, formal_kinds = _formal_records(author_context)
    formal_ids = set(formal_by_id)
    assumption_records = {
        identifier: record
        for identifier, record in formal_by_id.items()
        if formal_kinds.get(identifier) == "assumption"
    }
    proof_records = {
        identifier: record
        for identifier, record in formal_by_id.items()
        if formal_kinds.get(identifier) == "proof_obligation"
    }
    unknown_records = _unknown_records(preparation, source_registry)
    unknown_ids_by_formal_id: dict[str, list[str]] = {}
    for unknown in unknown_records:
        original_item = _mapping(unknown.get("original_item"))
        formal_reference_id = _formal_reference_for_unknown(original_item, formal_ids)
        if formal_reference_id:
            unknown_ids_by_formal_id.setdefault(formal_reference_id, []).append(_text(unknown.get("source_item_id")))
    for unknown_ids in unknown_ids_by_formal_id.values():
        unknown_ids.sort()

    outcomes = _stable_records(author_context.get("outcome_branches"), identifier_field="branch_id")
    outcome_ids = {_text(record.get("branch_id")) for record in outcomes}

    lemma_sources = [
        (identifier, record)
        for identifier, record in formal_by_id.items()
        if formal_kinds.get(identifier) in {"proposition", "forward_derivation_step"}
    ]
    lemma_sources.sort(key=lambda item: (0 if formal_kinds[item[0]] == "proposition" else 1, item[0], _canonical_json(item[1])))
    lemma_units: list[dict[str, Any]] = []
    lemma_id_by_source_id: dict[str, str] = {}
    for index, (source_id, record) in enumerate(lemma_sources, start=1):
        lemma_id = f"TS-L-{index}"
        lemma_id_by_source_id[source_id] = lemma_id
        premise_ids = _explicit_formal_references(record, formal_ids)
        premise_ids.update(_matching_formal_ids(record, candidates=assumption_records))
        related_proof_ids = _matching_formal_ids(record, candidates=proof_records)
        lemma_units.append(
            {
                "lemma_id": lemma_id,
                "display_label": f"L{index}",
                "source_kind": formal_kinds[source_id],
                "source_formal_reference_ids": [source_id],
                "premise_ids": sorted(premise_ids),
                "status": _status(record.get("status")),
                "source_status": _text(record.get("status")),
                "proof_obligation_ids": sorted(related_proof_ids),
                "falsifier_ids": [],
                "decision_branch_ids": [],
            }
        )

    no_information_reference_ids = {
        identifier
        for identifier, record in formal_by_id.items()
        if _text(record.get("status")).casefold() in _UNRESOLVED_STATUSES
    }
    no_information_reference_ids.update(unknown_ids_by_formal_id)
    decision_branches: list[dict[str, Any]] = []
    for outcome in outcomes:
        outcome_id = _text(outcome.get("branch_id"))
        decision_branches.append(
            {
                "branch_id": f"TS-BR-OUTCOME-{_local_branch_token(outcome_id)}",
                "display_label": f"Branch {outcome_id}",
                "branch_kind": "upstream_outcome_branch",
                "source_formal_reference_ids": [],
                "source_counterexample_ids": [],
                "source_outcome_branch_ids": [outcome_id],
                "source_unknown_item_ids": [],
                "status": "expected_not_observed",
                "conclusion_policy": "defer_to_upstream_outcome_branch",
            }
        )
    no_information_branch_by_formal_id: dict[str, str] = {}
    for source_id in sorted(no_information_reference_ids):
        branch_id = f"TS-BR-{_local_branch_token(source_id)}-NO_INFORMATION"
        no_information_branch_by_formal_id[source_id] = branch_id
        decision_branches.append(
            {
                "branch_id": branch_id,
                "display_label": f"No-information: {source_id}",
                "branch_kind": "no_information",
                "source_formal_reference_ids": [source_id] if source_id in formal_ids else [],
                "source_counterexample_ids": [],
                "source_outcome_branch_ids": _outcome_branch_id(outcome_ids, "uninformative_or_invalid"),
                "source_unknown_item_ids": sorted(unknown_ids_by_formal_id.get(source_id) or []),
                "status": "no_information",
                "conclusion_policy": "withhold_theorem_status_update",
                "next_action": "resolve_or_review_upstream_input",
            }
        )

    proof_obligations: list[dict[str, Any]] = []
    for index, (source_id, record) in enumerate(sorted(proof_records.items()), start=1):
        local_id = f"TS-PO-{index}"
        matching_dependencies = _matching_formal_ids(record, candidates={
            identifier: candidate
            for identifier, candidate in formal_by_id.items()
            if formal_kinds.get(identifier) in {"definition", "assumption", "proposition", "forward_derivation_step"}
        })
        matching_dependencies.update(_explicit_formal_references(record, formal_ids))
        related_lemma_ids = sorted(
            lemma_id
            for lemma_source_id, lemma_id in lemma_id_by_source_id.items()
            if lemma_source_id in matching_dependencies
            or source_id in set(next(
                unit["proof_obligation_ids"]
                for unit in lemma_units
                if unit["lemma_id"] == lemma_id
            ))
        )
        proof_obligations.append(
            {
                "proof_obligation_id": local_id,
                "display_label": f"PO{index}",
                "source_formal_reference_ids": [source_id],
                "required_formal_reference_ids": sorted(matching_dependencies),
                "related_lemma_ids": related_lemma_ids,
                "source_unknown_item_ids": sorted(unknown_ids_by_formal_id.get(source_id) or []),
                "status": _status(record.get("status")),
                "source_status": _text(record.get("status")),
                "if_unavailable_branch_id": no_information_branch_by_formal_id.get(source_id, ""),
            }
        )

    local_proof_id_by_source_id = {
        source_id: proof_obligation["proof_obligation_id"]
        for source_id, proof_obligation in zip(sorted(proof_records), proof_obligations, strict=True)
    }
    for unit in lemma_units:
        unit["proof_obligation_ids"] = [
            local_proof_id_by_source_id[source_id]
            for source_id in unit["proof_obligation_ids"]
            if source_id in local_proof_id_by_source_id
        ]
        related_source_ids = set(unit["source_formal_reference_ids"]) | set(unit["premise_ids"])
        unit["decision_branch_ids"] = sorted(
            branch_id
            for source_id, branch_id in no_information_branch_by_formal_id.items()
            if source_id in related_source_ids
            or source_id in {
                proof_obligation["source_formal_reference_ids"][0]
                for proof_obligation in proof_obligations
                if set(proof_obligation["related_lemma_ids"]) & {unit["lemma_id"]}
            }
        )

    counterexample_analysis = _mapping(author_context.get("counterexample_analysis"))
    counterexamples = _stable_records(counterexample_analysis.get("candidate_counterexamples"), identifier_field="counterexample_id")
    counterexample_target_id = _text(counterexample_analysis.get("target_claim_id"))
    target_lemma_ids = [lemma_id_by_source_id[counterexample_target_id]] if counterexample_target_id in lemma_id_by_source_id else []
    falsifiers: list[dict[str, Any]] = []
    outcome_candidates_by_classification = {
        "would_falsify": ("null_or_contradictory",),
        "scope_delimiter": ("partial_or_heterogeneous",),
        "assumptions_not_satisfied": ("uninformative_or_invalid",),
        "no_information": ("uninformative_or_invalid",),
    }
    for index, record in enumerate(counterexamples, start=1):
        counterexample_id = _text(record.get("counterexample_id"))
        classification = _counterexample_classification(record)
        falsifier_id = f"TS-F-{index}"
        falsifiers.append(
            {
                "falsifier_id": falsifier_id,
                "display_label": f"F{index}",
                "source_counterexample_ids": [counterexample_id],
                "target_formal_reference_ids": [counterexample_target_id] if counterexample_target_id in formal_ids else [],
                "target_lemma_ids": target_lemma_ids,
                "classification": classification,
                "source_outcome_branch_ids": _outcome_branch_id(
                    outcome_ids,
                    *outcome_candidates_by_classification[classification],
                ),
            }
        )
    for falsifier in falsifiers:
        for lemma_id in falsifier["target_lemma_ids"]:
            for unit in lemma_units:
                if unit["lemma_id"] == lemma_id:
                    unit["falsifier_ids"].append(falsifier["falsifier_id"])

    if not lemma_units:
        decision_branches.append(
            {
                "branch_id": "TS-BR-MISSING-DERIVATION-INPUT-NO_INFORMATION",
                "display_label": "No-information: derivation input",
                "branch_kind": "compiler_no_information",
                "source_formal_reference_ids": [],
                "source_counterexample_ids": [],
                "source_outcome_branch_ids": _outcome_branch_id(outcome_ids, "uninformative_or_invalid"),
                "source_unknown_item_ids": [],
                "status": "no_information",
                "conclusion_policy": "withhold_theorem_status_update",
                "next_action": "supply_upstream_proposition_or_derivation_input",
                "reason_code": "missing_upstream_derivation_input",
            }
        )
    spine = {
        "schema_version": THEORY_SPINE_SCHEMA_VERSION,
        "template_family": template_family,
        "enabled": True,
        "compiler_status": "ready" if lemma_units else "no_auditable_lemma_input",
        "lemma_units": lemma_units,
        "proof_obligations": proof_obligations,
        "falsifiers": falsifiers,
        "decision_branches": decision_branches,
    }
    errors = validate_theory_spine(spine, preparation=preparation, source_registry=source_registry)
    if errors:
        raise TheorySpineError("theory spine compilation failed: " + "; ".join(errors))
    return spine


def validate_theory_spine(
    payload: object,
    *,
    preparation: Mapping[str, Any],
    source_registry: Mapping[str, Any] | None = None,
) -> list[str]:
    """Validate local labels and their reverse references to frozen records."""

    errors: list[str] = []
    for error in Draft202012Validator(THEORY_SPINE_SCHEMA).iter_errors(payload):
        path = "/".join(str(part) for part in error.absolute_path) or "$"
        errors.append(f"{path}: {error.message}")
    if not isinstance(payload, Mapping):
        return sorted(set(errors))
    spine = dict(payload)
    author_context = _mapping(_mapping(preparation.get("source_bundle")).get("author_context"))
    resolved_source_registry = source_registry
    if not isinstance(resolved_source_registry, Mapping):
        from .source_registry import build_frozen_source_registry

        resolved_source_registry = build_frozen_source_registry(preparation)
    formal_by_id, _formal_kinds = _formal_records(author_context)
    formal_ids = set(formal_by_id)
    counterexample_ids = {
        _text(record.get("counterexample_id"))
        for record in _mapping(author_context.get("counterexample_analysis")).get("candidate_counterexamples") or []
        if isinstance(record, Mapping) and _text(record.get("counterexample_id"))
    }
    outcome_ids = {
        _text(record.get("branch_id"))
        for record in author_context.get("outcome_branches") or []
        if isinstance(record, Mapping) and _text(record.get("branch_id"))
    }
    unknown_ids = {
        _text(record.get("source_item_id"))
        for record in _mapping(resolved_source_registry).get("unknown_items") or []
        if isinstance(record, Mapping) and _text(record.get("source_item_id"))
    }
    collection_specs = (
        ("lemma_units", "lemma_id", _LOCAL_LEMMA_ID),
        ("proof_obligations", "proof_obligation_id", _LOCAL_PROOF_OBLIGATION_ID),
        ("falsifiers", "falsifier_id", _LOCAL_FALSIFIER_ID),
        ("decision_branches", "branch_id", _LOCAL_BRANCH_ID),
    )
    records_by_collection = {
        collection: [record for record in spine.get(collection) or [] if isinstance(record, Mapping)]
        for collection, _identifier_field, _pattern in collection_specs
    }
    local_ids: set[str] = set()
    for collection, identifier_field, pattern in collection_specs:
        seen_ids: set[str] = set()
        for index, record in enumerate(spine.get(collection) or []):
            if not isinstance(record, Mapping):
                errors.append(f"{collection}/{index} must be an object")
                continue
            identifier = _text(record.get(identifier_field))
            if not pattern.fullmatch(identifier):
                errors.append(f"{collection}/{index}/{identifier_field} is not a valid local audit label")
            if identifier in seen_ids or identifier in local_ids:
                errors.append(f"{collection}/{index}/{identifier_field} duplicates a local audit label")
            seen_ids.add(identifier)
            local_ids.add(identifier)
    upstream_ids = {
        *formal_ids,
        *counterexample_ids,
        *outcome_ids,
        *unknown_ids,
        *{
            _text(value)
            for value in _mapping(resolved_source_registry).get("allowed_source_ids") or []
            if _text(value)
        },
        *{
            _text(_mapping(record).get("citation_key"))
            for record in _mapping(resolved_source_registry).get("citation_registry") or []
            if _text(_mapping(record).get("citation_key"))
        },
    }
    if local_ids & upstream_ids:
        errors.append("local theory audit labels collide with frozen upstream identifiers")

    lemma_ids = {
        _text(record.get("lemma_id")) for record in records_by_collection["lemma_units"] if _text(record.get("lemma_id"))
    }
    proof_obligation_ids = {
        _text(record.get("proof_obligation_id"))
        for record in records_by_collection["proof_obligations"]
        if _text(record.get("proof_obligation_id"))
    }
    falsifier_ids = {
        _text(record.get("falsifier_id")) for record in records_by_collection["falsifiers"] if _text(record.get("falsifier_id"))
    }
    decision_branch_ids = {
        _text(record.get("branch_id"))
        for record in records_by_collection["decision_branches"]
        if _text(record.get("branch_id"))
    }
    for collection, records in records_by_collection.items():
        for index, record in enumerate(records):
            for field, allowed in (
                ("source_formal_reference_ids", formal_ids),
                ("required_formal_reference_ids", formal_ids),
                ("target_formal_reference_ids", formal_ids),
                ("source_counterexample_ids", counterexample_ids),
                ("source_outcome_branch_ids", outcome_ids),
            ):
                values = _text_list(record.get(field))
                if set(values) - allowed:
                    errors.append(f"{collection}/{index}/{field} contains an unknown upstream ID")
            unknown_references = _text_list(record.get("source_unknown_item_ids"))
            if set(unknown_references) - unknown_ids:
                errors.append(f"{collection}/{index}/source_unknown_item_ids contains an unknown source item")
            if collection == "lemma_units":
                if set(_text_list(record.get("premise_ids"))) - formal_ids:
                    errors.append(f"lemma_units/{index}/premise_ids contains an unknown formal reference")
                if set(_text_list(record.get("proof_obligation_ids"))) - proof_obligation_ids:
                    errors.append(f"lemma_units/{index}/proof_obligation_ids contains an unknown local proof obligation")
                if set(_text_list(record.get("falsifier_ids"))) - falsifier_ids:
                    errors.append(f"lemma_units/{index}/falsifier_ids contains an unknown local falsifier")
                if set(_text_list(record.get("decision_branch_ids"))) - decision_branch_ids:
                    errors.append(f"lemma_units/{index}/decision_branch_ids contains an unknown local decision branch")
            elif collection == "proof_obligations":
                if set(_text_list(record.get("related_lemma_ids"))) - lemma_ids:
                    errors.append(f"proof_obligations/{index}/related_lemma_ids contains an unknown local lemma")
                branch_id = _text(record.get("if_unavailable_branch_id"))
                if branch_id and branch_id not in decision_branch_ids:
                    errors.append(f"proof_obligations/{index}/if_unavailable_branch_id contains an unknown local decision branch")
            elif collection == "falsifiers" and set(_text_list(record.get("target_lemma_ids"))) - lemma_ids:
                errors.append(f"falsifiers/{index}/target_lemma_ids contains an unknown local lemma")
    return sorted(set(errors))


def theory_spine_context_for_section(
    theory_spine: Mapping[str, Any],
    *,
    section_id: str,
    unit_references: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return the compact, route-owned slice of a theory spine registry."""

    spine = _mapping(theory_spine)
    if not spine.get("enabled"):
        return {
            "schema_version": _text(spine.get("schema_version")) or THEORY_SPINE_SCHEMA_VERSION,
            "enabled": False,
            "section_id": section_id,
            "mode": "not_applicable",
            "lemma_units": [],
            "proof_obligations": [],
            "falsifiers": [],
            "decision_branches": [],
        }
    references = _mapping(unit_references)

    def selected(collection: str, identifier_field: str, reference_field: str) -> list[dict[str, Any]]:
        selected_ids = set(_text_list(references.get(reference_field)))
        return [
            deepcopy(dict(record))
            for record in spine.get(collection) or []
            if isinstance(record, Mapping) and _text(record.get(identifier_field)) in selected_ids
        ]

    return {
        "schema_version": _text(spine.get("schema_version")) or THEORY_SPINE_SCHEMA_VERSION,
        "enabled": True,
        "section_id": section_id,
        "mode": _text(references.get("mode")) or "reference_only",
        "lemma_units": selected("lemma_units", "lemma_id", "lemma_ids"),
        "proof_obligations": selected("proof_obligations", "proof_obligation_id", "proof_obligation_ids"),
        "falsifiers": selected("falsifiers", "falsifier_id", "falsifier_ids"),
        "decision_branches": selected("decision_branches", "branch_id", "decision_branch_ids"),
    }


def theory_spine_display_labels(theory_spine: Mapping[str, Any]) -> dict[str, str]:
    """Return the reader-facing labels for private local theory identifiers."""

    spine = _mapping(theory_spine)
    labels: dict[str, str] = {}
    for collection, identifier_field in (
        ("lemma_units", "lemma_id"),
        ("proof_obligations", "proof_obligation_id"),
        ("falsifiers", "falsifier_id"),
        ("decision_branches", "branch_id"),
    ):
        for record in spine.get(collection) or []:
            if not isinstance(record, Mapping):
                continue
            identifier = _text(record.get(identifier_field))
            display_label = _text(record.get("display_label"))
            if identifier and display_label:
                labels[identifier] = display_label
    return labels


def replace_theory_spine_internal_ids(text: object, theory_spine: Mapping[str, Any]) -> str:
    """Replace known private audit identifiers with their public labels."""

    value = str(text or "")
    labels = theory_spine_display_labels(theory_spine)
    if not labels:
        return value
    pattern = re.compile(
        r"(?<![A-Za-z0-9_-])(?:"
        + "|".join(re.escape(identifier) for identifier in sorted(labels, key=len, reverse=True))
        + r")(?![A-Za-z0-9_-])"
    )
    return pattern.sub(lambda match: labels[match.group(0)], value)


def theory_spine_internal_ids_in_text(text: object) -> list[str]:
    """Return local audit identifiers that must never appear in public prose."""

    return sorted(set(_VISIBLE_LOCAL_ID.findall(str(text or ""))))


__all__ = [
    "THEORY_SPINE_SCHEMA",
    "THEORY_SPINE_SCHEMA_VERSION",
    "TheorySpineError",
    "build_theory_spine",
    "replace_theory_spine_internal_ids",
    "theory_spine_display_labels",
    "theory_spine_context_for_section",
    "theory_spine_internal_ids_in_text",
    "validate_theory_spine",
]
