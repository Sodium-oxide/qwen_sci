"""Domain-neutral, lightweight contracts for scientific sub-hypotheses.

This module is intentionally limited to declaring an evidence-searchable
research question.  It does not model a full evidence graph or attempt to
repair an underspecified question.  Invalid contracts stay invalid and must be
regenerated or corrected by their producer.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

from src.pipeline.research_design_inventory import (
    RESEARCH_DESIGN_INVENTORY_SCHEMA_VERSION,
    validate_research_design_inventory,
)
from src.pipeline.discipline_taxonomy import canonicalize_discipline_key


SCIENCE_SUBHYPOTHESIS_SCHEMA_VERSION = "science_subhypothesis_v2"
MAX_RETRIEVAL_QUERY_VARIANTS_PER_SLOT = 5
MIN_RETRIEVAL_QUERY_TERMS_PER_VARIANT = 2
MAX_RETRIEVAL_QUERY_TERMS_PER_VARIANT = 6

SUPPORTED_QUESTION_KINDS = frozenset(
    {
        "EMPIRICAL_COVERAGE",
        "COMPARATIVE_EVALUATION",
        "MECHANISM_EXPLANATION",
        "BOUNDARY_HETEROGENEITY",
        "REPLICATION_CONTRADICTION",
        "MEASUREMENT_VALIDITY",
        "GENERALIZATION_TRANSPORT",
        "METHOD_DESIGN",
        "DATA_COVERAGE",
        "THEORY_MODEL_VALIDITY",
    }
)
SUPPORTED_RESEARCH_ROLES = frozenset(
    {
        "PRIMARY_QUESTION",
        "BASELINE_ENABLER",
        "BOUNDARY_TEST",
        "FALSIFICATION_RULE",
        "FOUNDATIONAL_CONTEXT",
    }
)
_RESEARCH_ROLE_ALIASES = {
    "PRIMARY": "PRIMARY_QUESTION",
    "CORE_QUESTION": "PRIMARY_QUESTION",
    "COMPARATIVE_ANALYSIS": "PRIMARY_QUESTION",
    "EVALUATION": "PRIMARY_QUESTION",
    "BASELINE": "BASELINE_ENABLER",
    "ENABLER": "BASELINE_ENABLER",
    "MECHANISTIC_ENABLER": "BASELINE_ENABLER",
    "METHOD_ENABLER": "BASELINE_ENABLER",
    "BOUNDARY": "BOUNDARY_TEST",
    "LIMITATION_TEST": "BOUNDARY_TEST",
    "SAFETY_BOUNDARY": "BOUNDARY_TEST",
    "COUNTEREVIDENCE": "FALSIFICATION_RULE",
    "COUNTEREVIDENCE_TEST": "FALSIFICATION_RULE",
    "CONTRADICTION_TEST": "FALSIFICATION_RULE",
    "BACKGROUND": "FOUNDATIONAL_CONTEXT",
    "CONTEXT": "FOUNDATIONAL_CONTEXT",
    "EVIDENCE_LANDSCAPE": "FOUNDATIONAL_CONTEXT",
}
_RESEARCH_ROLE_FALLBACKS = {
    "BOUNDARY_HETEROGENEITY": "BOUNDARY_TEST",
    "REPLICATION_CONTRADICTION": "FALSIFICATION_RULE",
    "GENERALIZATION_TRANSPORT": "BOUNDARY_TEST",
    "MECHANISM_EXPLANATION": "BASELINE_ENABLER",
    "MEASUREMENT_VALIDITY": "BASELINE_ENABLER",
    "METHOD_DESIGN": "BASELINE_ENABLER",
    "THEORY_MODEL_VALIDITY": "BASELINE_ENABLER",
    "DATA_COVERAGE": "FOUNDATIONAL_CONTEXT",
}
SCIENTIFIC_SCOPE_KEYS = frozenset(
    {
        "research_object",
        "population_or_system",
        "condition_or_regime",
        "intervention_or_input",
        "comparison_frame",
        "outcome_or_construct",
        "measurement_or_endpoint",
        "method_or_design",
        "dataset_or_corpus",
        "time_or_scale",
        "theoretical_assumptions",
        "deployment_context",
    }
)
QUESTION_KIND_SPECS: dict[str, dict[str, tuple[str, ...]]] = {
    "EMPIRICAL_COVERAGE": {
        "required_slots": (
            "phenomenon",
            "target_object",
            "target_condition",
            "direct_observation",
        ),
        "required_scope": (
            "research_object",
            "condition_or_regime",
            "outcome_or_construct",
        ),
    },
    "COMPARATIVE_EVALUATION": {
        "required_slots": (
            "candidate",
            "comparator",
            "comparison_condition",
            "comparable_endpoint",
        ),
        "required_scope": (
            "research_object",
            "comparison_frame",
            "outcome_or_construct",
        ),
    },
    "MECHANISM_EXPLANATION": {
        "required_slots": (
            "input_or_condition",
            "common_outcome",
            "candidate_mechanism",
            "discriminating_observation",
        ),
        "required_scope": (
            "research_object",
            "intervention_or_input",
            "outcome_or_construct",
        ),
    },
    "BOUNDARY_HETEROGENEITY": {
        "required_slots": (
            "base_relation",
            "boundary_variable",
            "condition_a",
            "condition_b",
            "comparable_endpoint",
        ),
        "required_scope": (
            "research_object",
            "condition_or_regime",
            "outcome_or_construct",
        ),
    },
    "REPLICATION_CONTRADICTION": {
        "required_slots": (
            "shared_claim",
            "result_a",
            "result_b",
            "comparability_axes",
        ),
        "required_scope": ("research_object", "outcome_or_construct"),
    },
    "MEASUREMENT_VALIDITY": {
        "required_slots": (
            "construct",
            "proxy_or_measure",
            "reference_or_target_measure",
            "mapping_or_calibration",
        ),
        "required_scope": (
            "research_object",
            "outcome_or_construct",
            "measurement_or_endpoint",
        ),
    },
    "GENERALIZATION_TRANSPORT": {
        "required_slots": (
            "source_system",
            "target_system",
            "shift_or_variation",
            "external_validation",
        ),
        "required_scope": (
            "research_object",
            "population_or_system",
            "condition_or_regime",
            "outcome_or_construct",
        ),
    },
    "METHOD_DESIGN": {
        "required_slots": (
            "current_method_or_design",
            "failure_or_bias",
            "alternative_design",
            "evaluation_criterion",
        ),
        "required_scope": (
            "research_object",
            "method_or_design",
            "outcome_or_construct",
        ),
    },
    "DATA_COVERAGE": {
        "required_slots": (
            "required_variable",
            "coverage_range",
            "missing_range",
            "impact_on_claim",
        ),
        "required_scope": (
            "research_object",
            "dataset_or_corpus",
            "outcome_or_construct",
        ),
    },
    "THEORY_MODEL_VALIDITY": {
        "required_slots": (
            "formal_claim",
            "assumption",
            "validity_domain",
            "falsification_or_counterexample",
        ),
        "required_scope": (
            "research_object",
            "theoretical_assumptions",
            "outcome_or_construct",
        ),
    },
}

_ALLOWED_FIELDS = frozenset(
    {
        "schema_version",
        "sub_hypothesis_id",
        "title",
        "question",
        "question_kind",
        "scientific_scope",
        "required_slots",
        "slot_definitions",
        "research_role",
        "challenge_target",
        "design_basis_ids",
        "allowed_evidence_scope",
        "excluded_evidence_scope",
        "exclusion_terms",
    }
)
_SLOT_DEFINITION_FIELDS = frozenset(
    {
        "meaning",
        "retrieval_concepts",
        "retrieval_query_variants",
        "minimum_evidence",
        "admission_rule",
    }
)
_RETRIEVAL_QUERY_VARIANT_FIELDS = frozenset(
    {"variant_id", "purpose", "query_terms", "preferred_disciplines"}
)


def _text(value: Any, *, limit: int = 1000) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())[:limit]


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _texts(value: Any, *, limit: int = 12) -> list[str]:
    values = value if isinstance(value, Sequence) and not isinstance(value, (str, bytes)) else [value]
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = _text(value, limit=240)
        key = item.casefold()
        if not item or key in seen:
            continue
        seen.add(key)
        result.append(item)
        if len(result) >= limit:
            break
    return result


def _variant_id(value: Any, *, fallback: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", _text(value, limit=100).casefold()).strip("_")
    return normalized[:80] or fallback


def _retrieval_query_variants(
    value: Any,
    *,
    slot: str,
    errors: list[str],
    warnings: list[str],
) -> list[dict[str, Any]]:
    """Normalize optional, alternative retrieval paths for one SH slot.

    Variants are candidate-discovery entry points.  They must remain short and
    independently meaningful, so they never encode an all-concepts evidence
    requirement for a paper.
    """

    if value is None:
        return []
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        errors.append(f"retrieval_query_variants_must_be_a_list:{slot}")
        return []
    if len(value) > MAX_RETRIEVAL_QUERY_VARIANTS_PER_SLOT:
        errors.append(f"too_many_retrieval_query_variants:{slot}")

    variants: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for index, raw_variant in enumerate(value[:MAX_RETRIEVAL_QUERY_VARIANTS_PER_SLOT], start=1):
        if not isinstance(raw_variant, Mapping):
            errors.append(f"retrieval_query_variant_must_be_an_object:{slot}:{index}")
            continue
        unknown_fields = sorted(
            key for key in raw_variant if key not in _RETRIEVAL_QUERY_VARIANT_FIELDS
        )
        errors.extend(
            f"unsupported_retrieval_query_variant_field:{slot}:{field}"
            for field in unknown_fields
        )
        variant_id = _variant_id(
            raw_variant.get("variant_id"),
            fallback=f"variant_{index}",
        )
        if variant_id in seen_ids:
            errors.append(f"duplicate_retrieval_query_variant_id:{slot}:{variant_id}")
        seen_ids.add(variant_id)
        purpose = _text(raw_variant.get("purpose"), limit=240)
        raw_terms = raw_variant.get("query_terms")
        if not isinstance(raw_terms, Sequence) or isinstance(raw_terms, (str, bytes)):
            errors.append(f"retrieval_query_variant_terms_must_be_a_list:{slot}:{variant_id}")
            query_terms: list[str] = []
        else:
            query_terms = _texts(raw_terms, limit=MAX_RETRIEVAL_QUERY_TERMS_PER_VARIANT)
            supplied_term_count = len(
                [item for item in raw_terms if _text(item, limit=240)]
            )
            if not (
                MIN_RETRIEVAL_QUERY_TERMS_PER_VARIANT
                <= supplied_term_count
                <= MAX_RETRIEVAL_QUERY_TERMS_PER_VARIANT
            ):
                errors.append(f"invalid_retrieval_query_variant_term_count:{slot}:{variant_id}")

        raw_disciplines = raw_variant.get("preferred_disciplines", [])
        if isinstance(raw_disciplines, (str, bytes)):
            # This is an optional precision hint.  A scalar model output must not
            # invalidate an otherwise usable SH or suppress its broad lane.
            raw_disciplines = [raw_disciplines]
            warnings.append(
                f"coerced_retrieval_query_variant_discipline_to_list:{slot}:{variant_id}"
            )
        elif not isinstance(raw_disciplines, Sequence):
            raw_disciplines = []
            warnings.append(
                f"dropped_malformed_retrieval_query_variant_disciplines:{slot}:{variant_id}"
            )
        preferred_disciplines: list[str] = []
        for discipline in _texts(raw_disciplines, limit=3):
            canonical = canonicalize_discipline_key(discipline)
            if not canonical:
                # preferred_disciplines only narrows an optional precision lane.
                # Keep discovery viable by dropping an unrecognised suggestion;
                # the unfiltered broad lane is still generated for this variant.
                warnings.append(
                    f"dropped_unsupported_retrieval_query_variant_discipline:{slot}:{discipline}"
                )
                continue
            if canonical not in preferred_disciplines:
                preferred_disciplines.append(canonical)

        if not purpose:
            errors.append(f"missing_retrieval_query_variant_purpose:{slot}:{variant_id}")
        if not query_terms:
            errors.append(f"missing_retrieval_query_variant_terms:{slot}:{variant_id}")
        variants.append(
            {
                "variant_id": variant_id,
                "purpose": purpose,
                "query_terms": query_terms,
                "preferred_disciplines": preferred_disciplines,
            }
        )
    return variants


def _normalized_research_role(
    value: Any,
    *,
    question_kind: str,
    warnings: list[str],
) -> str:
    """Return a supported reporting role without making LLM wording a hard gate."""

    supplied = _text(value, limit=80).upper()
    normalized = re.sub(r"[^A-Z0-9]+", "_", supplied).strip("_")
    resolved = _RESEARCH_ROLE_ALIASES.get(normalized, normalized)
    if resolved in SUPPORTED_RESEARCH_ROLES:
        if supplied and resolved != supplied:
            warnings.append(f"normalized_research_role:{supplied}:{resolved}")
        return resolved

    fallback = _RESEARCH_ROLE_FALLBACKS.get(question_kind, "PRIMARY_QUESTION")
    warnings.append(
        f"fallback_research_role:{supplied or '<missing>'}:{fallback}"
    )
    return fallback


def _scope(value: Any) -> tuple[dict[str, list[str]], list[str]]:
    raw = _mapping(value)
    unknown = sorted(key for key in raw if key not in SCIENTIFIC_SCOPE_KEYS)
    return (
        {key: _texts(raw.get(key), limit=8) for key in SCIENTIFIC_SCOPE_KEYS if _texts(raw.get(key), limit=8)},
        unknown,
    )


def _evidence_scope(value: Any) -> dict[str, Any]:
    raw = _mapping(value)
    result: dict[str, Any] = {}
    for key in (
        "date_range",
        "languages",
        "publication_types",
        "providers",
        "source_types",
        "study_designs",
        "contexts",
        "notes",
    ):
        item = raw.get(key)
        if isinstance(item, Sequence) and not isinstance(item, (str, bytes)):
            values = _texts(item, limit=8)
            if values:
                result[key] = values
        elif _text(item, limit=240):
            result[key] = _text(item, limit=240)
    return result


def _question_errors(question: str) -> list[str]:
    normalized = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", " ", question.casefold()).strip()
    if not normalized:
        return ["missing_question"]
    if len(normalized) < 12:
        return ["question_not_independently_answerable"]
    return []


def normalize_science_subhypothesis_v2(
    value: Any,
    *,
    design_inventory: Mapping[str, Any] | None,
    project_context: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate and normalize only the v2 SH contract; no legacy conversion."""

    raw = _mapping(value)
    errors: list[str] = []
    warnings: list[str] = []
    if not isinstance(value, Mapping):
        errors.append("subhypothesis_must_be_an_object")
    unknown_fields = sorted(key for key in raw if key not in _ALLOWED_FIELDS)
    errors.extend(f"unsupported_field:{field}" for field in unknown_fields)
    if raw.get("schema_version") != SCIENCE_SUBHYPOTHESIS_SCHEMA_VERSION:
        errors.append("invalid_schema_version")

    identifier = _text(raw.get("sub_hypothesis_id"), limit=120)
    if not identifier:
        errors.append("missing_sub_hypothesis_id")
    question = _text(raw.get("question"), limit=1800)
    errors.extend(_question_errors(question))
    title = _text(raw.get("title"), limit=180)

    question_kind = _text(raw.get("question_kind"), limit=80).upper()
    if question_kind not in SUPPORTED_QUESTION_KINDS:
        errors.append("unsupported_question_kind")
    specification = QUESTION_KIND_SPECS.get(question_kind, {})

    scientific_scope, unknown_scope_fields = _scope(raw.get("scientific_scope"))
    errors.extend(f"unsupported_scope_field:{field}" for field in unknown_scope_fields)
    if not isinstance(raw.get("scientific_scope"), Mapping):
        errors.append("scientific_scope_must_be_an_object")
    for field in specification.get("required_scope", ()):
        if not scientific_scope.get(field):
            errors.append(f"missing_required_scope:{field}")

    raw_required_slots = raw.get("required_slots")
    required_slot_values = (
        [_text(item, limit=240) for item in raw_required_slots]
        if isinstance(raw_required_slots, Sequence) and not isinstance(raw_required_slots, (str, bytes))
        else []
    )
    required_slots = _texts(required_slot_values, limit=16)
    if not isinstance(raw_required_slots, Sequence) or isinstance(raw_required_slots, (str, bytes)):
        errors.append("required_slots_must_be_a_list")
    nonempty_raw_slots = [item for item in required_slot_values if item]
    if len(nonempty_raw_slots) != len({item.casefold() for item in nonempty_raw_slots}):
        errors.append("duplicate_required_slot")
    for slot in specification.get("required_slots", ()):
        if slot not in required_slots:
            errors.append(f"missing_required_slot:{slot}")

    raw_definitions = _mapping(raw.get("slot_definitions"))
    if not isinstance(raw.get("slot_definitions"), Mapping):
        errors.append("slot_definitions_must_be_an_object")
    slot_definitions: dict[str, dict[str, Any]] = {}
    for slot in required_slots:
        definition = _mapping(raw_definitions.get(slot))
        if not definition:
            errors.append(f"missing_slot_definition:{slot}")
            continue
        unknown_definition_fields = sorted(
            key for key in definition if key not in _SLOT_DEFINITION_FIELDS
        )
        errors.extend(
            f"unsupported_slot_definition_field:{slot}:{field}"
            for field in unknown_definition_fields
        )
        normalized_definition = {
            "meaning": _text(definition.get("meaning"), limit=700),
            "retrieval_concepts": _texts(definition.get("retrieval_concepts"), limit=10),
            "retrieval_query_variants": _retrieval_query_variants(
                definition.get("retrieval_query_variants"),
                slot=slot,
                errors=errors,
                warnings=warnings,
            ),
            "minimum_evidence": _text(definition.get("minimum_evidence"), limit=700),
            "admission_rule": _text(definition.get("admission_rule"), limit=700),
        }
        for field in ("meaning", "retrieval_concepts", "minimum_evidence", "admission_rule"):
            item = normalized_definition[field]
            if not item:
                errors.append(f"missing_slot_definition_value:{slot}:{field}")
        slot_definitions[slot] = normalized_definition
    for extra_slot in sorted(key for key in raw_definitions if key not in required_slots):
        errors.append(f"unexpected_slot_definition:{extra_slot}")

    research_role = _normalized_research_role(
        raw.get("research_role"),
        question_kind=question_kind,
        warnings=warnings,
    )
    challenge_target = _text(raw.get("challenge_target"), limit=1200)
    if not challenge_target:
        errors.append("missing_challenge_target")

    raw_design_basis_ids = raw.get("design_basis_ids")
    raw_basis_id_values = (
        [_text(item, limit=80) for item in raw_design_basis_ids]
        if isinstance(raw_design_basis_ids, Sequence) and not isinstance(raw_design_basis_ids, (str, bytes))
        else []
    )
    design_basis_ids = _texts(raw_basis_id_values, limit=10)
    if not isinstance(raw_design_basis_ids, Sequence) or isinstance(raw_design_basis_ids, (str, bytes)):
        errors.append("design_basis_ids_must_be_a_list")
    nonempty_raw_basis_ids = [item for item in raw_basis_id_values if item]
    if len(nonempty_raw_basis_ids) != len({item.casefold() for item in nonempty_raw_basis_ids}):
        errors.append("duplicate_design_basis_id")
    if not design_basis_ids:
        errors.append("missing_design_basis_ids")
    inventory_ids: set[str] = set()
    try:
        inventory = validate_research_design_inventory(
            design_inventory,
            project_context=project_context,
        )
        inventory_ids = {
            _text(item.get("id"), limit=80)
            for item in inventory.get("design_basis", [])
            if isinstance(item, Mapping)
        }
    except ValueError as exc:
        errors.append(f"invalid_design_inventory:{str(exc)}")
        inventory = {}
    unknown_basis_ids = [identifier for identifier in design_basis_ids if identifier not in inventory_ids]
    errors.extend(f"unknown_design_basis_id:{identifier}" for identifier in unknown_basis_ids)

    return {
        "schema_version": SCIENCE_SUBHYPOTHESIS_SCHEMA_VERSION,
        "sub_hypothesis_id": identifier,
        "title": title,
        "question": question,
        "question_kind": question_kind,
        "scientific_scope": scientific_scope,
        "required_slots": required_slots,
        "slot_definitions": slot_definitions,
        "research_role": research_role,
        "challenge_target": challenge_target,
        "design_basis_ids": design_basis_ids,
        "allowed_evidence_scope": _evidence_scope(raw.get("allowed_evidence_scope")),
        "excluded_evidence_scope": _evidence_scope(raw.get("excluded_evidence_scope")),
        "exclusion_terms": _texts(raw.get("exclusion_terms"), limit=10),
        "validation": {
            "valid": not errors,
            "errors": errors,
            "warnings": warnings,
            "unknown_fields": unknown_fields,
            "inventory_schema_version": _text(
                _mapping(design_inventory).get("schema_version"), limit=80
            ),
            "required_inventory_schema_version": RESEARCH_DESIGN_INVENTORY_SCHEMA_VERSION,
        },
    }


def science_subhypothesis_v2_prompt_contract() -> dict[str, Any]:
    """Return the literal shape emitted by automatic SH decomposition prompts."""

    return {
        "schema_version": SCIENCE_SUBHYPOTHESIS_SCHEMA_VERSION,
        "sub_hypothesis_id": "SH1",
        "title": "short evidence-focused title",
        "question": "an independently answerable scientific evidence question",
        "question_kind": "one supported question kind",
        "scientific_scope": {"research_object": ["source-grounded scope value"]},
        "required_slots": ["all slots required by question_kind"],
        "slot_definitions": {
            "one_required_slot": {
                "meaning": "what the slot denotes for this question",
                "retrieval_concepts": ["concise searchable terms"],
                "retrieval_query_variants": [
                    {
                        "variant_id": "baseline_observation",
                        "purpose": "broad candidate recall for this slot",
                        "query_terms": [
                            "canonical system phrase",
                            "canonical outcome phrase",
                        ],
                        "preferred_disciplines": ["materials_science"],
                    }
                ],
                "minimum_evidence": "minimum evidence needed for this slot",
                "admission_rule": "what makes a retrieved work admissible",
            }
        },
        "research_role": "one supported role",
        "challenge_target": "the claim, assumption, or relation this question can challenge",
        "design_basis_ids": ["DB1"],
        "allowed_evidence_scope": {},
        "excluded_evidence_scope": {},
        "exclusion_terms": [],
    }
