"""Compile bounded, data-anchored observations into standard SH contracts."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

from src.pipeline.research_question_contract import (
    SCIENCE_SUBHYPOTHESIS_SCHEMA_VERSION,
    normalize_science_subhypothesis_v2,
)

from .query_binding import normalize_query_variant_bindings
from .retrieval_profile import (
    RETRIEVAL_PROFILE_VERSION,
    build_profile_query_variants,
    build_retrieval_profile,
)


DATA_ANCHORED_PRIORITY = "DATA_ANCHORED_PRIMARY"


def compile_data_anchored_subhypotheses(
    claims: Sequence[Mapping[str, Any]],
    project_context: Mapping[str, Any],
    *,
    max_count: int = 3,
) -> dict[str, Any]:
    """Build 1-3 valid SHs only when project design bases make them admissible."""

    if max_count < 1 or max_count > 3:
        raise ValueError("max_count for data-anchored SHs must be between 1 and 3.")
    context = dict(project_context) if isinstance(project_context, Mapping) else {}
    basis_ids = _design_basis_ids(context)
    if not basis_ids:
        return {
            "subhypotheses": [],
            "metadata_by_subhypothesis": {},
            "query_variant_bindings": [],
            "limitations": [
                "Multimodal claims were retained without SH conversion because the project has no valid research design basis."
            ],
        }
    subhypotheses: list[dict[str, Any]] = []
    metadata: dict[str, dict[str, Any]] = {}
    bindings: list[dict[str, str]] = []
    limitations: list[str] = []
    for claim in claims:
        if len(subhypotheses) >= max_count:
            break
        if not isinstance(claim, Mapping):
            continue
        candidate = _text(claim.get("candidate_explanation"), limit=500)
        statement = _text(claim.get("local_data_statement"), limit=700)
        claim_id = _text(claim.get("claim_id"), limit=120)
        observation_id = _text(claim.get("observation_id"), limit=120)
        if not all((candidate, statement, claim_id, observation_id)):
            limitations.append("An incomplete multimodal claim was not converted into a data-anchored SH.")
            continue
        identifier = f"MM_SH_{len(subhypotheses) + 1:02d}"
        retrieval_profile = build_retrieval_profile(claim, context)
        raw_contract, raw_bindings = _build_contract(
            identifier,
            claim,
            research_object=_research_object(context),
            design_basis_ids=basis_ids[:3],
            retrieval_profile=retrieval_profile,
        )
        normalized = normalize_science_subhypothesis_v2(
            raw_contract,
            design_inventory=context.get("research_design_inventory"),
            project_context=context,
        )
        if not normalized.get("validation", {}).get("valid"):
            limitations.append(
                f"Claim {claim_id} was not converted into {identifier} because it could not satisfy the project SH contract."
            )
            continue
        subhypotheses.append(raw_contract)
        bindings.extend(raw_bindings)
        metadata[identifier] = {
            "analysis_priority": DATA_ANCHORED_PRIORITY,
            "claim_ids": [claim_id],
            "observation_ids": [observation_id],
            "question_kind": raw_contract["question_kind"],
            "retrieval_profile": retrieval_profile,
        }
    normalized_bindings = normalize_query_variant_bindings(bindings)
    return {
        "subhypotheses": subhypotheses,
        "metadata_by_subhypothesis": metadata,
        "query_variant_bindings": normalized_bindings,
        "limitations": limitations,
    }


def _build_contract(
    identifier: str,
    claim: Mapping[str, Any],
    *,
    research_object: str,
    design_basis_ids: list[str],
    retrieval_profile: Mapping[str, Any],
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    focus = _text(claim.get("focus"), limit=40).casefold()
    if focus == "measurement":
        return _measurement_contract(identifier, claim, research_object, design_basis_ids, retrieval_profile)
    if focus == "boundary":
        return _boundary_contract(identifier, claim, research_object, design_basis_ids, retrieval_profile)
    if focus == "contradiction":
        return _contradiction_contract(identifier, claim, research_object, design_basis_ids, retrieval_profile)
    if focus == "theory":
        return _theory_contract(identifier, claim, research_object, design_basis_ids, retrieval_profile)
    return _mechanism_contract(identifier, claim, research_object, design_basis_ids, retrieval_profile)


def _mechanism_contract(
    identifier: str,
    claim: Mapping[str, Any],
    research_object: str,
    design_basis_ids: list[str],
    retrieval_profile: Mapping[str, Any],
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    candidate = _text(claim.get("candidate_explanation"), limit=240)
    finding = _text(claim.get("local_data_statement"), limit=400)
    alternative = _first_alternative(claim)
    slots = {
        "input_or_condition": _slot(
            "The local data condition that prompted a tentative explanation.",
            [research_object, "data-anchored observation"],
            variants=_support_and_counter_variants(research_object, candidate, alternative, retrieval_profile),
        ),
        "common_outcome": _slot(
            "The observable pattern to compare across published evidence.",
            [research_object, *retrieval_profile.get("outcome_terms", [])],
            profile=retrieval_profile,
            role="construct",
        ),
        "candidate_mechanism": _slot(
            "The tentative explanation compatible with the local observation.",
            [candidate, *retrieval_profile.get("variable_terms", [])],
            profile=retrieval_profile,
            role="mechanism",
        ),
        "discriminating_observation": _slot(
            "An observation that separates the candidate explanation from alternatives.",
            [_text(claim.get("discriminating_prediction"), limit=220), *retrieval_profile.get("condition_terms", [])],
            profile=retrieval_profile,
            role="boundary_condition",
        ),
    }
    contract = {
        "schema_version": SCIENCE_SUBHYPOTHESIS_SCHEMA_VERSION,
        "sub_hypothesis_id": identifier,
        "title": "Data-anchored mechanism assessment",
        "question": (
            f"Which published evidence supports, challenges, or distinguishes {candidate} as a tentative explanation "
            f"for the provided-data observation: {finding}?"
        ),
        "question_kind": "MECHANISM_EXPLANATION",
        "scientific_scope": {
            "research_object": [research_object],
            "intervention_or_input": ["provided multimodal data condition"],
            "outcome_or_construct": ["observed data pattern"],
        },
        "required_slots": list(slots),
        "slot_definitions": slots,
        "research_role": "FALSIFICATION_RULE" if claim.get("focus") == "contradiction" else "BASELINE_ENABLER",
        "challenge_target": (
            "the tentative interpretation of a bounded local observation; the claim must remain open to "
            "published counterevidence and alternative explanations"
        ),
        "design_basis_ids": design_basis_ids,
        "allowed_evidence_scope": {},
        "excluded_evidence_scope": {},
        "exclusion_terms": [],
    }
    return contract, _bindings(identifier, "input_or_condition", claim)


def _measurement_contract(
    identifier: str,
    claim: Mapping[str, Any],
    research_object: str,
    design_basis_ids: list[str],
    retrieval_profile: Mapping[str, Any],
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    candidate = _text(claim.get("candidate_explanation"), limit=240)
    alternative = _first_alternative(claim)
    slots = {
        "construct": _slot(
            "The scientific construct implicated by the provided-data observation.",
            [research_object, "measurement construct"],
            variants=_support_and_counter_variants(research_object, candidate, alternative, retrieval_profile),
        ),
        "proxy_or_measure": _slot(
            "The bounded multimodal proxy used in the local observation.",
            [*retrieval_profile.get("measurement_terms", []), *retrieval_profile.get("variable_terms", [])],
            profile=retrieval_profile,
            role="proxy_or_measure",
        ),
        "reference_or_target_measure": _slot(
            "An external reference measurement suitable for validation.",
            [*retrieval_profile.get("measurement_terms", []), *retrieval_profile.get("outcome_terms", [])],
            profile=retrieval_profile,
            role="reference_or_target_measure",
        ),
        "mapping_or_calibration": _slot(
            "Calibration or mapping evidence that tests the proxy interpretation.",
            [*retrieval_profile.get("measurement_terms", []), *retrieval_profile.get("condition_terms", [])],
            profile=retrieval_profile,
            role="mapping_or_calibration",
        ),
    }
    contract = {
        "schema_version": SCIENCE_SUBHYPOTHESIS_SCHEMA_VERSION,
        "sub_hypothesis_id": identifier,
        "title": "Data-anchored measurement validity assessment",
        "question": (
            f"Which published validation or counterevidence tests whether the provided multimodal measurement is "
            f"a reliable proxy for {candidate}?"
        ),
        "question_kind": "MEASUREMENT_VALIDITY",
        "scientific_scope": {
            "research_object": [research_object],
            "outcome_or_construct": ["observed data pattern"],
            "measurement_or_endpoint": ["provided multimodal measurement"],
        },
        "required_slots": list(slots),
        "slot_definitions": slots,
        "research_role": "BASELINE_ENABLER",
        "challenge_target": "the validity of the local multimodal proxy and its tentative interpretation",
        "design_basis_ids": design_basis_ids,
        "allowed_evidence_scope": {},
        "excluded_evidence_scope": {},
        "exclusion_terms": [],
    }
    return contract, _bindings(identifier, "construct", claim, measurement=True)


def _boundary_contract(
    identifier: str,
    claim: Mapping[str, Any],
    research_object: str,
    design_basis_ids: list[str],
    retrieval_profile: Mapping[str, Any],
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    candidate = _text(claim.get("candidate_explanation"), limit=240)
    alternative = _first_alternative(claim)
    slots = {
        "base_relation": _slot(
            "The tentative relation observed in the bounded local data.",
            [research_object, "data-anchored relation"],
            variants=_support_and_counter_variants(research_object, candidate, alternative, retrieval_profile),
        ),
        "boundary_variable": _slot(
            "A variable that may delimit the tentative relation.",
            [*retrieval_profile.get("condition_terms", []), *retrieval_profile.get("space_scale_terms", [])],
            profile=retrieval_profile,
            role="boundary_condition",
        ),
        "condition_a": _slot(
            "One condition in which the relation may hold.",
            [*retrieval_profile.get("condition_terms", []), research_object],
            profile=retrieval_profile,
            role="construct",
        ),
        "condition_b": _slot(
            "A contrasting condition that may challenge the relation.",
            [*retrieval_profile.get("comparison_terms", []), *retrieval_profile.get("condition_terms", []), research_object],
            profile=retrieval_profile,
            role="alternative_explanation",
        ),
        "comparable_endpoint": _slot(
            "A comparable endpoint across the boundary conditions.",
            [*retrieval_profile.get("outcome_terms", []), *retrieval_profile.get("measurement_terms", [])],
            profile=retrieval_profile,
            role="reference_or_target_measure",
        ),
    }
    contract = {
        "schema_version": SCIENCE_SUBHYPOTHESIS_SCHEMA_VERSION,
        "sub_hypothesis_id": identifier,
        "title": "Data-anchored boundary assessment",
        "question": (
            f"Under which published boundary conditions is the tentative interpretation {candidate} compatible "
            "with evidence, and under which conditions is it challenged?"
        ),
        "question_kind": "BOUNDARY_HETEROGENEITY",
        "scientific_scope": {
            "research_object": [research_object],
            "condition_or_regime": ["candidate boundary conditions"],
            "outcome_or_construct": ["observed data pattern"],
        },
        "required_slots": list(slots),
        "slot_definitions": slots,
        "research_role": "BOUNDARY_TEST",
        "challenge_target": "the transfer of a bounded local observation across conditions or regimes",
        "design_basis_ids": design_basis_ids,
        "allowed_evidence_scope": {},
        "excluded_evidence_scope": {},
        "exclusion_terms": [],
    }
    return contract, _bindings(identifier, "base_relation", claim, evidence_mode="boundary")


def _contradiction_contract(
    identifier: str,
    claim: Mapping[str, Any],
    research_object: str,
    design_basis_ids: list[str],
    retrieval_profile: Mapping[str, Any],
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    candidate = _text(claim.get("candidate_explanation"), limit=240)
    alternative = _first_alternative(claim)
    slots = {
        "shared_claim": _slot(
            "The tentative local interpretation requiring independent verification.",
            [research_object, "replication evidence"],
            variants=_support_and_counter_variants(research_object, candidate, alternative, retrieval_profile),
        ),
        "result_a": _slot(
            "Published evidence compatible with the tentative interpretation.",
            [candidate, *retrieval_profile.get("outcome_terms", [])],
            profile=retrieval_profile,
            role="replication",
        ),
        "result_b": _slot(
            "Published counterevidence or an alternative result.",
            [alternative, *retrieval_profile.get("comparison_terms", [])],
            profile=retrieval_profile,
            role="alternative_explanation",
        ),
        "comparability_axes": _slot(
            "Methods, systems, and endpoints that determine whether results are comparable.",
            [*retrieval_profile.get("method_terms", []), *retrieval_profile.get("measurement_terms", [])],
            profile=retrieval_profile,
            role="mapping_or_calibration",
        ),
    }
    contract = {
        "schema_version": SCIENCE_SUBHYPOTHESIS_SCHEMA_VERSION,
        "sub_hypothesis_id": identifier,
        "title": "Data-anchored replication and contradiction assessment",
        "question": (
            f"Which published results support or contradict the tentative interpretation {candidate}, and which "
            "comparability axes explain any disagreement?"
        ),
        "question_kind": "REPLICATION_CONTRADICTION",
        "scientific_scope": {
            "research_object": [research_object],
            "outcome_or_construct": ["observed data pattern"],
        },
        "required_slots": list(slots),
        "slot_definitions": slots,
        "research_role": "FALSIFICATION_RULE",
        "challenge_target": "whether the local observation is reproducible and compatible with independent results",
        "design_basis_ids": design_basis_ids,
        "allowed_evidence_scope": {},
        "excluded_evidence_scope": {},
        "exclusion_terms": [],
    }
    return contract, _bindings(identifier, "shared_claim", claim, evidence_mode="boundary")


def _theory_contract(
    identifier: str,
    claim: Mapping[str, Any],
    research_object: str,
    design_basis_ids: list[str],
    retrieval_profile: Mapping[str, Any],
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    candidate = _text(claim.get("candidate_explanation"), limit=240)
    alternative = _first_alternative(claim)
    slots = {
        "formal_claim": _slot(
            "The tentative theoretical interpretation compatible with the local data.",
            [research_object, "theory validation"],
            variants=_support_and_counter_variants(research_object, candidate, alternative, retrieval_profile),
        ),
        "assumption": _slot(
            "An assumption needed to connect the model to the local observation.",
            [*retrieval_profile.get("condition_terms", []), *retrieval_profile.get("method_terms", [])],
            profile=retrieval_profile,
            role="mechanism",
        ),
        "validity_domain": _slot(
            "The system or regime where the theory is expected to apply.",
            [*retrieval_profile.get("space_scale_terms", []), *retrieval_profile.get("condition_terms", []), research_object],
            profile=retrieval_profile,
            role="boundary_condition",
        ),
        "falsification_or_counterexample": _slot(
            "A falsifier or counterexample for the tentative theory interpretation.",
            [_text(claim.get("falsifier"), limit=220), *retrieval_profile.get("comparison_terms", [])],
            profile=retrieval_profile,
            role="alternative_explanation",
        ),
    }
    contract = {
        "schema_version": SCIENCE_SUBHYPOTHESIS_SCHEMA_VERSION,
        "sub_hypothesis_id": identifier,
        "title": "Data-anchored theory validity assessment",
        "question": (
            f"Which published theoretical and empirical evidence tests the validity domain and falsifiers of the "
            f"tentative interpretation {candidate}?"
        ),
        "question_kind": "THEORY_MODEL_VALIDITY",
        "scientific_scope": {
            "research_object": [research_object],
            "theoretical_assumptions": ["candidate theoretical assumptions"],
            "outcome_or_construct": ["observed data pattern"],
        },
        "required_slots": list(slots),
        "slot_definitions": slots,
        "research_role": "FALSIFICATION_RULE",
        "challenge_target": "the validity domain and assumptions of the tentative theory interpretation",
        "design_basis_ids": design_basis_ids,
        "allowed_evidence_scope": {},
        "excluded_evidence_scope": {},
        "exclusion_terms": [],
    }
    return contract, _bindings(identifier, "formal_claim", claim, evidence_mode="mechanism")


def _slot(
    meaning: str,
    concepts: list[str],
    *,
    variants: list[dict[str, Any]] | None = None,
    profile: Mapping[str, Any] | None = None,
    role: str = "construct",
) -> dict[str, Any]:
    if variants is None and profile:
        variants = build_profile_query_variants(profile, role=role)
    safe_variants = []
    for variant in variants or []:
        if not isinstance(variant, Mapping):
            continue
        safe_variants.append(
            {
                "variant_id": _text(variant.get("variant_id"), limit=80),
                "purpose": _text(variant.get("purpose"), limit=240),
                "query_terms": _nonempty_terms(
                    variant.get("query_terms") or [], fallback="scientific literature"
                ),
                "preferred_disciplines": list(variant.get("preferred_disciplines") or []),
            }
        )
    return {
        "meaning": meaning,
        "retrieval_concepts": _nonempty_terms(concepts, fallback="scientific evidence"),
        "retrieval_query_variants": safe_variants,
        "minimum_evidence": "A published study with methods and results relevant to this slot.",
        "admission_rule": "The work explicitly addresses this slot in the scoped scientific system.",
    }


def _support_and_counter_variants(
    research_object: str,
    candidate: str,
    alternative: str,
    profile: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    if profile:
        generated = build_profile_query_variants(profile, role="mechanism", support=True)
        support_terms = generated[0].get("query_terms", []) if generated else []
        counter_generated = build_profile_query_variants(profile, role="alternative_explanation", support=False)
        counter_terms = counter_generated[0].get("query_terms", []) if counter_generated else []
    else:
        support_terms = _nonempty_terms([research_object, candidate, "mechanism evidence"], fallback="candidate mechanism")
        counter_terms = _nonempty_terms([research_object, alternative, "contradictory evidence"], fallback="alternative mechanism")
    return [
        {
            "variant_id": "support_01",
            "purpose": "Find evidence compatible with the tentative candidate explanation.",
            "query_terms": support_terms,
            "epistemic_role": "support",
            "evidence_mode": "mechanism",
            "source": RETRIEVAL_PROFILE_VERSION,
            "profile_version": RETRIEVAL_PROFILE_VERSION,
            "preferred_disciplines": [],
        },
        {
            "variant_id": "counter_01",
            "purpose": "Find counterevidence or an alternative explanation for the local observation.",
            "query_terms": counter_terms,
            "epistemic_role": "alternative_explanation",
            "evidence_mode": "boundary",
            "source": RETRIEVAL_PROFILE_VERSION,
            "profile_version": RETRIEVAL_PROFILE_VERSION,
            "preferred_disciplines": [],
        },
    ]


def _bindings(
    identifier: str,
    slot_name: str,
    claim: Mapping[str, Any],
    *,
    measurement: bool = False,
    evidence_mode: str | None = None,
) -> list[dict[str, str]]:
    claim_id = _text(claim.get("claim_id"), limit=120)
    support = {
        "sub_hypothesis_id": identifier,
        "slot_name": slot_name,
        "query_variant_id": "support_01",
        "epistemic_role": "support",
        "evidence_mode": evidence_mode or ("benchmark" if measurement else "mechanism"),
        "required_result": "Evidence compatible with the tentative local interpretation, without treating it as established.",
        "claim_id": claim_id,
    }
    counter_role = "measurement_confound" if measurement else "alternative_explanation"
    counter = {
        "sub_hypothesis_id": identifier,
        "slot_name": slot_name,
        "query_variant_id": "counter_01",
        "epistemic_role": counter_role,
        "evidence_mode": "boundary" if not measurement else "benchmark",
        "required_result": _text(claim.get("falsifier"), limit=700),
        "claim_id": claim_id,
    }
    return [support, counter]


def _design_basis_ids(context: Mapping[str, Any]) -> list[str]:
    inventory = context.get("research_design_inventory")
    if not isinstance(inventory, Mapping):
        return []
    return [
        _text(item.get("id"), limit=80)
        for item in inventory.get("design_basis", [])
        if isinstance(item, Mapping) and _text(item.get("id"), limit=80)
    ]


def _research_object(context: Mapping[str, Any]) -> str:
    operationalization = context.get("academic_operationalization")
    if isinstance(operationalization, Mapping):
        value = _text(operationalization.get("research_object"), limit=240)
        if value:
            return value
    for value in context.get("core_entities", []) if isinstance(context.get("core_entities"), Sequence) else []:
        item = _text(value, limit=240)
        if item:
            return item
    return _text(context.get("original_topic"), limit=240) or "the project research system"


def _first_alternative(claim: Mapping[str, Any]) -> str:
    alternatives = claim.get("alternative_explanations")
    if isinstance(alternatives, Sequence) and not isinstance(alternatives, (str, bytes)):
        for value in alternatives:
            item = _text(value, limit=240)
            if item:
                return item
    return "alternative explanation"


def _nonempty_terms(values: Sequence[Any], *, fallback: str) -> list[str]:
    result: list[str] = []
    for value in values:
        item = _text(value, limit=180)
        if item and item.casefold() not in {existing.casefold() for existing in result}:
            result.append(item)
    fallback_terms = (fallback, "scientific evidence")
    for fallback_term in fallback_terms:
        if len(result) >= 2:
            break
        if fallback_term.casefold() not in {existing.casefold() for existing in result}:
            result.append(fallback_term)
    if len(result) < 2:
        result.append("published study")
    return result[:6]


def _text(value: Any, *, limit: int) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())[:limit]
