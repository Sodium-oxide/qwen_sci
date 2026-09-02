"""Domain-neutral research-coverage and hypothesis-package construction.

This module deliberately works with *roles* and evidence contracts rather
than a catalogue of subject-specific keywords.  A project may be physics,
chemistry, life science, climate science, materials science, neuroscience, or
another natural-science domain; it still needs an object in scope, an input,
a mechanism/discriminator, an observable outcome, a comparison, and a way to
be wrong.  The same mechanism budget must not silently erase those other
structural requirements.
"""
from __future__ import annotations

from hashlib import sha1
from typing import Any


ANALYSIS_ROLES = (
    "OBJECT_SCOPE",
    "INPUT_OR_PREMISE",
    "MECHANISM_GAP",
    "BOUNDARY_CONSTRAINT",
    "SPACETIME_OR_RESOURCE",
    "MEASUREMENT_VALIDITY",
    "BENCHMARK_VALIDITY",
    "THEORY_ASSUMPTION",
    "COUNTEREXAMPLE_OR_ALTERNATIVE",
    "TRANSLATION_OR_SCALING",
    "REPLICATION_OR_ROBUSTNESS",
    "BACKGROUND_OR_FOUNDATION",
)

COVERAGE_DIMENSIONS = (
    "scope",
    "mode",
    "input",
    "mechanism",
    "outcome",
    "resource_boundary",
    "comparison",
    "falsification",
    "measurement",
    "transferability",
    "evidence_status",
)

_ROLE_ALIASES = {
    "scope": "OBJECT_SCOPE",
    "object": "OBJECT_SCOPE",
    "object_scope": "OBJECT_SCOPE",
    "input": "INPUT_OR_PREMISE",
    "premise": "INPUT_OR_PREMISE",
    "mechanism": "MECHANISM_GAP",
    "mechanism_gap": "MECHANISM_GAP",
    "boundary": "BOUNDARY_CONSTRAINT",
    "constraint": "BOUNDARY_CONSTRAINT",
    "resource": "SPACETIME_OR_RESOURCE",
    "measurement": "MEASUREMENT_VALIDITY",
    "benchmark": "BENCHMARK_VALIDITY",
    "theory": "THEORY_ASSUMPTION",
    "alternative": "COUNTEREXAMPLE_OR_ALTERNATIVE",
    "counterexample": "COUNTEREXAMPLE_OR_ALTERNATIVE",
    "translation": "TRANSLATION_OR_SCALING",
    "scaling": "TRANSLATION_OR_SCALING",
    "replication": "REPLICATION_OR_ROBUSTNESS",
    "robustness": "REPLICATION_OR_ROBUSTNESS",
    "background": "BACKGROUND_OR_FOUNDATION",
    "foundation": "BACKGROUND_OR_FOUNDATION",
}

# These are structural research-language clues, not domain rules.  They are
# used only when TanXi/LLM has not supplied an explicit role or a structured
# evidence bundle.  The evidence bundle always has precedence.
_STRUCTURAL_ROLE_CUES = (
    ("MEASUREMENT_VALIDITY", ("measurement", "calibration", "uncertainty", "detection", "resolution", "error", "observable", "readout")),
    ("BENCHMARK_VALIDITY", ("benchmark", "baseline", "metric", "evaluation", "comparison", "criterion")),
    ("THEORY_ASSUMPTION", ("assumption", "axiom", "theorem", "derivation", "formal", "premise")),
    ("COUNTEREXAMPLE_OR_ALTERNATIVE", ("counterexample", "alternative", "competing", "confound", "discriminator", "rival")),
    ("TRANSLATION_OR_SCALING", ("translation", "scaling", "scale-up", "generaliz", "external validity", "deployment")),
    ("REPLICATION_OR_ROBUSTNESS", ("replication", "reproduc", "robust", "cross-platform", "cross condition")),
    ("SPACETIME_OR_RESOURCE", ("resource", "bandwidth", "latency", "storage", "throughput", "density", "cost", "sample")),
    ("BOUNDARY_CONSTRAINT", ("boundary", "constraint", "limit", "regime", "threshold", "condition", "temperature", "pressure", "noise")),
)


def _text(value: Any) -> str:
    return " ".join(str(value or "").split())


_RESTRICTED_BRIDGE_REQUIRED_ROLES = ("input", "mechanism", "outcome", "comparison")


def _slot_text(value: Any) -> str:
    if isinstance(value, dict):
        for key in ("value", "normalized_value", "candidate", "text", "label", "name"):
            text = _slot_text(value.get(key))
            if text:
                return text
        return ""
    if isinstance(value, (list, tuple, set)):
        return "; ".join(text for text in (_slot_text(item) for item in value) if text)
    text = _text(value)
    if not text:
        return ""
    lowered = text.lower()
    if lowered in {"unresolved", "unknown", "none", "n/a", "generic_placeholder"}:
        return ""
    if lowered.startswith("requires_") or lowered.startswith("requires-"):
        return ""
    if "fragment_refs" in lowered and ("'value': ''" in lowered or '"value": ""' in lowered):
        return ""
    return text


def _slot_value_from_mapping(mapping: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = _slot_text(mapping.get(key))
        if value:
            return value
    return ""


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _items(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _gap_id(gap: dict[str, Any]) -> str:
    return _text(gap.get("gap_id") or gap.get("id"))


def _subhypothesis_annotation(sub_hypothesis: dict[str, Any]) -> dict[str, Any]:
    return (
        sub_hypothesis.get("annotation")
        if isinstance(sub_hypothesis.get("annotation"), dict)
        else sub_hypothesis.get("hypothesis_annotation")
        if isinstance(sub_hypothesis.get("hypothesis_annotation"), dict)
        else {}
    )


def _subhypothesis_ids_for_gap(gap: dict[str, Any]) -> list[str]:
    values: list[Any] = [
        gap.get("sub_hypothesis_id"),
        gap.get("subhypothesis_id"),
        gap.get("source_sub_hypothesis_id"),
        gap.get("original_sub_hypothesis_id"),
    ]
    parent_priority = (
        gap.get("parent_subhypothesis_priority")
        if isinstance(gap.get("parent_subhypothesis_priority"), dict)
        else {}
    )
    values.append(parent_priority.get("sub_hypothesis_id"))
    for key in (
        "mechanism_seed_contract",
        "gap_existence_verification",
        "original_source_role_audit",
        "original_source_role_assessment",
        "subhypothesis_context",
    ):
        nested = gap.get(key)
        if isinstance(nested, dict):
            values.extend([
                nested.get("sub_hypothesis_id"),
                nested.get("subhypothesis_id"),
                nested.get("source_sub_hypothesis_id"),
            ])
    return list(dict.fromkeys(_text(value) for value in values if _text(value)))


def _subhypothesis_context_by_id(project: dict[str, Any]) -> dict[str, dict[str, Any]]:
    contexts: dict[str, dict[str, Any]] = {}
    for sub_hypothesis in project.get("sub_hypotheses", []) if isinstance(project, dict) else []:
        if not isinstance(sub_hypothesis, dict):
            continue
        sub_id = _text(sub_hypothesis.get("id"))
        if not sub_id:
            continue
        annotation = _subhypothesis_annotation(sub_hypothesis)
        priority = annotation.get("priority") if isinstance(annotation.get("priority"), dict) else {}
        retrieval = (
            sub_hypothesis.get("retrieval")
            if isinstance(sub_hypothesis.get("retrieval"), dict)
            else {}
        )
        gate = (
            retrieval.get("full_text_gate_contract")
            if isinstance(retrieval.get("full_text_gate_contract"), dict)
            else {}
        )
        coverage = (
            retrieval.get("cumulative_full_text_coverage")
            if isinstance(retrieval.get("cumulative_full_text_coverage"), dict)
            else {}
        )
        policy = (
            annotation.get("retrieval_policy")
            if isinstance(annotation.get("retrieval_policy"), dict)
            else {}
        )
        standard_id = _text(annotation.get("evidence_standard_id") or gate.get("evidence_standard_id"))
        claim_cap = _text(
            coverage.get("claim_strength_cap")
            or gate.get("claim_strength_cap")
            or policy.get("claim_strength_cap")
        )
        accepted_core_designs = list(
            gate.get("standard_core_designs")
            or policy.get("accepted_core_designs")
            or []
        )
        support_designs = list(gate.get("support_designs") or policy.get("support_designs") or [])
        contexts[sub_id] = {
            "sub_hypothesis_id": sub_id,
            "tier": _text(priority.get("tier")),
            "priority_overall": float(priority.get("overall") or 0.0),
            "impact": int(priority.get("impact") or 0),
            "feasibility": int(priority.get("feasibility") or 0),
            "novelty": int(priority.get("novelty") or 0),
            "strategic_alignment": int(priority.get("strategic_alignment") or 0),
            "evidence_standard": standard_id,
            "hypothesis_type": _text(annotation.get("hypothesis_type") or gate.get("hypothesis_type")),
            "scale": _text(annotation.get("scale")),
            "research_mode_prior": _text(annotation.get("research_mode_prior")),
            "claim_strength_cap": claim_cap,
            "accepted_core_designs": accepted_core_designs,
            "support_designs": support_designs,
            "excluded_as_core": list(gate.get("excluded_as_core") or []),
            "standard_core_full_text_count": int(coverage.get("standard_core_full_text_count") or 0),
            "standard_core_full_text_target": int(coverage.get("standard_core_full_text_target") or 0),
            "standard_core_by_design": dict(coverage.get("standard_core_by_design") or {}),
            "direct_core_full_text_count": int(coverage.get("direct_core_full_text_count") or 0),
            "direct_core_full_text_target": int(coverage.get("direct_core_full_text_target") or 0),
            "direct_core_by_evidence_lane": dict(coverage.get("direct_core_by_evidence_lane") or {}),
            "type_directed_evidence_bundle_status": _text(
                coverage.get("type_directed_evidence_bundle_status")
            ),
            "research_question_evidence_ready": bool(coverage.get("research_question_evidence_ready")),
            "type_directed_bundle_core_ready": bool(
                coverage.get("type_directed_bundle_core_ready")
            ),
            "partial_contract_evidence_ready": bool(
                coverage.get("partial_contract_evidence_ready")
            ),
            "type_directed_evidence_bundle": dict(
                coverage.get("type_directed_evidence_bundle") or {}
            ),
            "peer_reviewed_full_text_count": int(coverage.get("peer_reviewed_full_text_count") or 0),
            "peer_reviewed_full_text_target": int(coverage.get("peer_reviewed_full_text_target") or 0),
            "imported_related_full_text_count": int(
                coverage.get("imported_related_full_text_count") or 0
            ),
            "imported_related_full_text_target": int(
                coverage.get("imported_related_full_text_target") or 0
            ),
            "direct_contract_core_count": int(
                coverage.get("direct_contract_core_count") or 0
            ),
            "noncore_related_full_text_count": int(
                coverage.get("noncore_related_full_text_count") or 0
            ),
            "imported_full_text_by_layer": dict(
                coverage.get("imported_full_text_by_layer") or {}
            ),
            "core_full_text_by_layer": dict(
                coverage.get("core_full_text_by_layer") or {}
            ),
            "noncore_full_text_by_role": dict(
                coverage.get("noncore_full_text_by_role") or {}
            ),
            "priority_rationale": (
                sub_hypothesis.get("priority_rationale")
                if isinstance(sub_hypothesis.get("priority_rationale"), dict)
                else {}
            ),
        }
    return contexts


def _subhypothesis_context_for_gaps(project: dict[str, Any], gaps: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    by_id = _subhypothesis_context_by_id(project)
    contexts: dict[str, dict[str, Any]] = {}
    for gap in gaps:
        if not isinstance(gap, dict):
            continue
        for sub_id in _subhypothesis_ids_for_gap(gap):
            if sub_id in by_id:
                contexts[sub_id] = by_id[sub_id]
    return contexts


def _package_claim_strength_cap(contexts: dict[str, dict[str, Any]]) -> str:
    caps = list(dict.fromkeys(
        _text(context.get("claim_strength_cap"))
        for context in contexts.values()
        if _text(context.get("claim_strength_cap"))
    ))
    if not caps:
        return ""
    if len(caps) == 1:
        return caps[0]
    return "package_claim_capped_by_component_standards: " + " | ".join(caps)


def _bundle(gap: dict[str, Any]) -> dict[str, Any]:
    bundle = _mapping(gap.get("mechanism_evidence_bundle"))
    if bundle:
        return bundle
    return _mapping(gap.get("mechanism_draft"))


def _role_text(gap: dict[str, Any]) -> str:
    bundle = _bundle(gap)
    ingredients = _mapping(gap.get("hypothesis_ingredients"))
    return " ".join(
        _text(value)
        for value in (
            gap.get("analysis_role"), gap.get("description"), gap.get("gap_description"),
            gap.get("gap_type"), gap.get("suggested_research_path"),
            bundle.get("intervention"), bundle.get("mediator"), bundle.get("outcome"),
            bundle.get("comparison"), bundle.get("falsification"),
            ingredients.get("input"), ingredients.get("mediator"), ingredients.get("outcome"),
        )
        if _text(value)
    ).lower()


def _explicit_role(gap: dict[str, Any]) -> str:
    raw = _text(gap.get("analysis_role") or gap.get("research_role")).upper()
    if raw in ANALYSIS_ROLES:
        return raw
    return _ROLE_ALIASES.get(raw.lower().replace("-", "_").replace(" ", "_"), "")


def _is_primary_mechanism_gap(gap: dict[str, Any]) -> bool:
    """Accept only a v2 causal candidate that passed its full qualification.

    Coverage construction must not reinterpret a graph label, a relevance
    score, or a historical readiness flag as a scientific-gap gate.
    """
    try:
        from ._gap_types import is_primary_mechanism_candidate
    except ImportError:
        from _gap_types import is_primary_mechanism_candidate
    try:
        return is_primary_mechanism_candidate(gap)
    except ValueError:
        return False


def is_primary_research_gap(gap: dict[str, Any]) -> bool:
    """Return v2 primary-research status without requiring a causal package."""
    try:
        from ._gap_types import is_primary_research_candidate
    except ImportError:
        from _gap_types import is_primary_research_candidate
    try:
        return is_primary_research_candidate(gap)
    except ValueError:
        return False


def is_primary_mechanism_gap(gap: dict[str, Any]) -> bool:
    """Public causal-only alias for callers outside coverage construction."""
    return _is_primary_mechanism_gap(gap)


def _is_restricted_component_bridge_gap(gap: dict[str, Any]) -> bool:
    return bool(
        _text(gap.get("gap_type")) == "component_bridge_gap_synthesis"
        or gap.get("component_bridge_gap_synthesis_ready") is True
        or gap.get("restricted_component_bridge_hypothesis_allowed") is True
        or _text(gap.get("gap_track")) == "COMPONENT_BRIDGE_GAP_SYNTHESIS"
        or _text(gap.get("hypothesis_package_type")) == "restricted_component_bridge"
    )


def _with_restricted_component_bridge_policy(gap: dict[str, Any]) -> dict[str, Any]:
    """Return a capped bridge-hypothesis copy without importing gap detection.

    ``_gap_detection`` imports this module, so the package layer keeps its own
    small policy normalizer instead of creating a circular import.  The fields
    mirror TanXi's restricted component-bridge contract and are intentionally
    conservative.
    """
    item = dict(gap) if isinstance(gap, dict) else {}
    item["gap_track"] = "COMPONENT_BRIDGE_GAP_SYNTHESIS"
    item["component_bridge_gap_synthesis_ready"] = True
    item["eligible_for_hypothesis_generation"] = False
    item["eligible_for_restricted_bridge_hypothesis"] = True
    item["restricted_component_bridge_hypothesis_allowed"] = True
    item["hypothesis_generation_track"] = "restricted_component_bridge"
    item["hypothesis_package_type"] = "restricted_component_bridge"
    item["primary_eligible"] = False
    item["core_eligible"] = False
    item["standard_core_eligible"] = False
    item["direct_core"] = False
    item["direct_core_evidence_allowed"] = False
    item["may_support_final_object_claim"] = False
    item["may_fill_primary_evidence_slots"] = False
    item["claim_strength_cap"] = "no_final_object_claim_validation"
    item["claim_strength_effect"] = "no_final_object_claim_validation"
    item["post_draft_socrates_enrichment_required"] = True
    item["final_object_claim_disclaimer"] = (
        "限制声明：该假设仅由组件/桥接证据支持，不得声称最终研究对象已经得到验证。"
    )
    item["requires_human_review"] = True
    qualification = _mapping(item.get("alignment_qualification"))
    qualification.update(
        {
            "primary_eligible": False,
            "component_bridge_gap_synthesis_ready": True,
            "restricted_component_bridge_hypothesis_allowed": True,
            "direct_core": False,
            "standard_core_eligible": False,
            "core_eligible": False,
            "may_support_final_object_claim": False,
            "claim_strength_cap": "no_final_object_claim_validation",
            "post_draft_socrates_enrichment_required": True,
            "final_object_claim_disclaimer": item["final_object_claim_disclaimer"],
        }
    )
    item["alignment_qualification"] = qualification
    readiness = _mapping(item.get("hypothesis_readiness"))
    readiness.update(
        {
            "status": "READY_FOR_RESTRICTED_BRIDGE_HYPOTHESIS",
            "ready_for_hypothesis_generation": True,
            "primary_eligible": False,
            "restricted_component_bridge": True,
            "claim_strength_cap": "no_final_object_claim_validation",
            "post_draft_socrates_enrichment_required": True,
            "final_object_claim_disclaimer": item["final_object_claim_disclaimer"],
        }
    )
    item["hypothesis_readiness"] = readiness
    return item


def _subhypothesis_for_gap(project: dict[str, Any], gap: dict[str, Any]) -> dict[str, Any]:
    sub_id = _text(gap.get("sub_hypothesis_id"))
    if not sub_id:
        return {}
    for item in _items(project.get("sub_hypotheses")):
        if isinstance(item, dict) and _text(item.get("id") or item.get("sub_hypothesis_id")) == sub_id:
            return item
    return {}


def _restricted_bridge_slots_from_gap(project: dict[str, Any], gap: dict[str, Any]) -> dict[str, str]:
    contract = _mapping(gap.get("restricted_bridge_role_contract"))
    roles = _mapping(contract.get("roles"))
    bundle = _bundle(gap)
    sub_hypothesis = _subhypothesis_for_gap(project, gap)
    causal_contract = _mapping(sub_hypothesis.get("causal_contract"))
    mediator_candidates = [
        _slot_text(_mapping(roles.get("mediator")).get("value")),
        _slot_value_from_mapping(bundle, "mediator", "proposed_mediator", "mechanism"),
        _slot_value_from_mapping(gap, "mediator", "proposed_mediator", "mechanism"),
        _slot_text(causal_contract.get("pivotal_mechanism")),
    ]
    mediator_candidates.extend(
        _slot_text(value)
        for value in _items(causal_contract.get("supporting_mediators"))
    )
    slots = {
        "input": (
            _slot_text(_mapping(roles.get("input")).get("value"))
            or _slot_value_from_mapping(bundle, "intervention", "input", "premise")
            or _slot_value_from_mapping(gap, "intervention", "input", "premise")
            or _slot_text(sub_hypothesis.get("independent_variable"))
        ),
        "mechanism": next((value for value in mediator_candidates if value), ""),
        "outcome": (
            _slot_text(_mapping(roles.get("outcome")).get("value"))
            or _slot_value_from_mapping(bundle, "outcome", "output", "observable_outcome")
            or _slot_value_from_mapping(gap, "outcome", "output", "observable_outcome")
            or _slot_text(causal_contract.get("outcome"))
            or _slot_text(sub_hypothesis.get("dependent_variables"))
        ),
        "comparison": (
            _slot_text(_mapping(roles.get("comparison")).get("value"))
            or _slot_value_from_mapping(bundle, "comparison", "control", "baseline")
            or _slot_value_from_mapping(gap, "comparison", "control", "baseline")
            or _slot_text(
                sub_hypothesis.get("baseline_or_comparator")
                or sub_hypothesis.get("comparison")
                or sub_hypothesis.get("comparison_conditions")
                or sub_hypothesis.get("controls")
            )
        ),
        "falsification": (
            _slot_text(_mapping(roles.get("falsification")).get("value"))
            or _slot_value_from_mapping(bundle, "falsification", "failure_criterion")
            or _slot_value_from_mapping(gap, "falsification", "failure_criterion")
            or _slot_text(sub_hypothesis.get("falsification_condition"))
        ),
    }
    return slots


def _audit_restricted_component_bridge_slots(slots: dict[str, Any]) -> dict[str, Any]:
    missing = [
        role
        for role in _RESTRICTED_BRIDGE_REQUIRED_ROLES
        if not _slot_text(slots.get(role))
    ]
    return {
        "schema_version": "restricted_component_bridge_slot_audit_v1",
        "ready": not missing,
        "missing_roles": missing,
        "required_roles": list(_RESTRICTED_BRIDGE_REQUIRED_ROLES),
        "status": "READY" if not missing else "ROLE_CONTRACT_INCOMPLETE",
        "reason": (
            "All restricted bridge slots are materialized."
            if not missing else
            "Restricted bridge package lacks one or more input/mechanism/outcome/comparison slots."
        ),
    }


def _select_restricted_component_bridge_gaps(
    project: dict[str, Any],
    gaps: list[dict[str, Any]],
    limit: int = 1,
) -> list[dict[str, Any]]:
    candidates = [
        _with_restricted_component_bridge_policy(gap)
        for gap in gaps
        if isinstance(gap, dict)
        and _is_restricted_component_bridge_gap(gap)
    ]
    candidates.sort(
        key=lambda item: (
            -float(item.get("exploration_value_score") or item.get("mechanistic_priority") or item.get("novelty_score") or 0.0),
            -int(bool(item.get("source_evidence_units") or item.get("supporting_references"))),
            _text(item.get("sub_hypothesis_id")),
            _gap_id(item),
        )
    )
    return candidates[: max(1, int(limit or 1))]


def classify_gap_analysis_role(project: dict[str, Any], gap: dict[str, Any]) -> dict[str, Any]:
    """Return one auditable structural role for a gap.

    An explicit upstream role is retained, but a primary evidence bundle wins
    because only it may occupy the scarce causal-mechanism budget.  Secondary
    material remains useful as a support slot; it is not discarded merely
    because it cannot itself seed MingLi.
    """
    explicit = _explicit_role(gap)
    if _is_restricted_component_bridge_gap(gap):
        return {
            "analysis_role": "BACKGROUND_OR_FOUNDATION",
            "source": "restricted_component_bridge_policy",
            "eligible_for_primary_mechanism_budget": False,
            "eligible_for_restricted_bridge_hypothesis": True,
            "primary_eligible": False,
        }
    if _is_primary_mechanism_gap(gap):
        return {
            "analysis_role": "MECHANISM_GAP",
            "source": "primary_mechanism_evidence_bundle",
            "eligible_for_primary_mechanism_budget": True,
        }
    if explicit:
        return {
            "analysis_role": explicit,
            "source": "explicit_upstream_role",
            "eligible_for_primary_mechanism_budget": False,
        }
    text = _role_text(gap)
    for role, cues in _STRUCTURAL_ROLE_CUES:
        if any(cue in text for cue in cues):
            return {
                "analysis_role": role,
                "source": "structural_fallback",
                "eligible_for_primary_mechanism_budget": False,
            }
    if _text(gap.get("sub_hypothesis_id")) or _text(gap.get("scope")):
        role = "OBJECT_SCOPE"
        source = "project_scope_context"
    else:
        role = "BACKGROUND_OR_FOUNDATION"
        source = "default_noncausal_context"
    return {
        "analysis_role": role,
        "source": source,
        "eligible_for_primary_mechanism_budget": False,
    }


def annotate_gap_analysis_roles(project: dict[str, Any], gaps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    annotated: list[dict[str, Any]] = []
    for source in gaps:
        if not isinstance(source, dict):
            continue
        item = dict(source)
        item["analysis_role_detail"] = classify_gap_analysis_role(project, item)
        item["analysis_role"] = item["analysis_role_detail"]["analysis_role"]
        annotated.append(item)
    return annotated


def _value_from_gap(gap: dict[str, Any], *keys: str) -> str:
    bundle = _bundle(gap)
    ingredients = _mapping(gap.get("hypothesis_ingredients"))
    for key in keys:
        for source in (bundle, ingredients, gap):
            value = _slot_text(source.get(key)) if isinstance(source, dict) else ""
            if value:
                return value
    return ""


def _evidence_ids(gap: dict[str, Any]) -> list[str]:
    bundle = _bundle(gap)
    values: list[Any] = []
    for field in ("theory_evidence_ids", "experimental_evidence_ids", "direct_evidence_ids", "evidence_ids", "supporting_references"):
        value = bundle.get(field) if field in bundle else gap.get(field)
        values.extend(_items(value))
    result: list[str] = []
    for value in values:
        text = _text(value)
        if text and text not in result:
            result.append(text)
    return result[:24]


def _lineage_item_key(item: dict[str, Any]) -> tuple[str, str, str]:
    return (
        _text(item.get("source_text_handoff_id")),
        _text(item.get("source_unit_id")),
        _text(item.get("slot")),
    )


def _lineage_entry(
    item: dict[str, Any],
    *,
    slot: str,
    value: str = "",
    source: str = "",
) -> dict[str, Any]:
    return {
        "schema_version": "hypothesis_slot_source_lineage_v1",
        "slot": slot,
        "value": _text(value or item.get("value") or item.get("supported_value")),
        "paper_id": _text(item.get("paper_id")),
        "source_unit_id": _text(item.get("source_unit_id")),
        "source_text_handoff_id": _text(item.get("source_text_handoff_id")),
        "excerpt_hash": _text(item.get("excerpt_hash")),
        "source_field": _text(item.get("source_field")),
        "source_origin": _text(item.get("source_origin") or source),
        "source_role": _text(item.get("source_role")),
        "acceptance_status": _text(item.get("acceptance_status") or "ACCEPTED_FOR_PACKAGE_SLOT"),
        "bounded_excerpt": _text(item.get("bounded_excerpt") or item.get("excerpt")),
        "support_terms": list(item.get("support_terms") or [])[:8],
    }


def _append_lineage_unique(target: list[dict[str, Any]], item: dict[str, Any]) -> None:
    if not _text(item.get("source_unit_id")):
        return
    key = _lineage_item_key(item)
    if key in {_lineage_item_key(existing) for existing in target}:
        return
    target.append(item)


def _slot_source_lineage_from_gap(gap: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    bundle = _bundle(gap)
    output: dict[str, list[dict[str, Any]]] = {
        "input": [],
        "mechanism": [],
        "outcome": [],
        "measurement": [],
    }
    declared = bundle.get("slot_source_lineage") if isinstance(bundle.get("slot_source_lineage"), dict) else {}
    for slot in output:
        for item in _items(declared.get(slot)):
            if isinstance(item, dict):
                _append_lineage_unique(
                    output[slot],
                    _lineage_entry(item, slot=slot, source="bundle_slot_source_lineage"),
                )
    for item in _items(bundle.get("accepted_source_text_handoffs")):
        if not isinstance(item, dict):
            continue
        if _text(item.get("acceptance_status")) != "ACCEPTED_FOR_PACKAGE_SLOT":
            continue
        slot = _text(item.get("package_slot"))
        if slot not in output:
            field = _text(item.get("accepted_causal_field") or item.get("source_role"))
            slot = "mechanism" if field == "mediator" else field
        if slot in output:
            _append_lineage_unique(
                output[slot],
                _lineage_entry(item, slot=slot, source="accepted_source_text_handoff"),
            )
    for span in _items(bundle.get("mechanism_source_spans")):
        if not isinstance(span, dict):
            continue
        field = _text(span.get("field"))
        slot = "mechanism" if field == "mediator" else field
        if slot not in output:
            continue
        _append_lineage_unique(
            output[slot],
            _lineage_entry(
                span,
                slot=slot,
                value=_value_from_gap(
                    gap,
                    "intervention" if field == "input" else "mediator" if field == "mediator" else "outcome",
                    field,
                ),
                source="mechanism_source_span",
            ),
        )
    if not output["measurement"] and output["outcome"]:
        for item in output["outcome"]:
            _append_lineage_unique(
                output["measurement"],
                {**item, "slot": "measurement", "source_origin": item.get("source_origin") or "outcome_lineage_reused_as_measurement"},
            )
    return output


def _package_slot_source_lineage(
    slots: dict[str, Any],
    package_gaps: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    output: dict[str, list[dict[str, Any]]] = {
        "input": [],
        "mechanism": [],
        "outcome": [],
        "measurement": [],
    }
    for gap in package_gaps:
        lineage = _slot_source_lineage_from_gap(gap)
        for slot, items in lineage.items():
            if slot not in output:
                continue
            for item in items:
                if isinstance(item, dict):
                    _append_lineage_unique(output[slot], item)
    if not output["measurement"] and output["outcome"] and _slot_text(slots.get("measurement")) == _slot_text(slots.get("outcome")):
        for item in output["outcome"]:
            _append_lineage_unique(output["measurement"], {**item, "slot": "measurement"})
    return output


def _missing_source_lineage_slots(
    slots: dict[str, Any],
    slot_source_lineage: dict[str, list[dict[str, Any]]],
    *,
    package_type: str,
) -> list[str]:
    if package_type == "restricted_component_bridge":
        return []
    required = ["input", "mechanism", "outcome"]
    if _slot_text(slots.get("measurement")):
        required.append("measurement")
    missing: list[str] = []
    for slot in required:
        if not _slot_text(slots.get(slot)) and slot != "measurement":
            continue
        if not any(
            _text(item.get("source_unit_id")) and _text(item.get("bounded_excerpt"))
            for item in slot_source_lineage.get(slot, [])
            if isinstance(item, dict)
        ):
            missing.append(slot)
    return list(dict.fromkeys(missing))


def _mode_for_gap(gap: dict[str, Any]) -> str:
    bundle = _bundle(gap)
    readiness = _mapping(gap.get("hypothesis_readiness"))
    contract = _mapping(gap.get("socrates_mechanism_contract"))
    design = _mapping(bundle.get("research_design_evidence"))
    resolution = _mapping(bundle.get("research_mode_resolution"))
    return _text(
        design.get("recommended_mode") or resolution.get("mode") or
        bundle.get("research_mode") or readiness.get("research_mode") or
        contract.get("research_mode") or gap.get("research_mode")
    )


def _scope_for_gap(project: dict[str, Any], gap: dict[str, Any]) -> str:
    sub_id = _text(gap.get("sub_hypothesis_id"))
    for item in _items(project.get("sub_hypotheses")):
        if isinstance(item, dict) and _text(item.get("id")) == sub_id:
            return _text(item.get("title") or item.get("description") or item.get("objective") or sub_id)
    return _text(gap.get("scope") or gap.get("target_system") or project.get("objective") or project.get("title") or project.get("domain"))


def _dimension_entry(name: str) -> dict[str, Any]:
    return {
        "dimension": name,
        "status": "MISSING",
        "supporting_gap_ids": [],
        "evidence_ids": [],
        "values": [],
        "reason": "No project-local, source-traceable support has been attached.",
    }


def _add_dimension(entry: dict[str, Any], gap: dict[str, Any], value: str, *, evidence: list[str] | None = None) -> None:
    if not _text(value):
        return
    entry["status"] = "COVERED"
    gap_id = _gap_id(gap)
    if gap_id and gap_id not in entry["supporting_gap_ids"]:
        entry["supporting_gap_ids"].append(gap_id)
    if value not in entry["values"]:
        entry["values"].append(value)
    for ref in evidence or _evidence_ids(gap):
        if ref not in entry["evidence_ids"]:
            entry["evidence_ids"].append(ref)
    entry["reason"] = "Covered by a project-local role-typed gap and its persisted evidence contract."


def build_research_coverage_map(project: dict[str, Any], gaps: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Build the project-level map; it is broader than any one hypothesis."""
    try:
        from ._type_directed_hypothesis_packages import (
            build_type_directed_research_coverage_map,
            is_v2_v3_project,
        )
    except ImportError:
        from _type_directed_hypothesis_packages import (
            build_type_directed_research_coverage_map,
            is_v2_v3_project,
        )
    if is_v2_v3_project(project):
        return build_type_directed_research_coverage_map(project, gaps)
    return {
        "schema_version": "research_coverage_map_v2_type_directed",
        "status": "RESEARCH_QUESTION_CONTRACT_V2_REQUIRED",
        "scope": "research_question_contracts",
        "contract_coverage": [],
        "missing_required": ["research_question_contract_v2"],
        "primary_research_gap_ids": [],
        "dimensions": {},
    }
    # Historical causal-dimension construction below is intentionally
    # unreachable.  New runs must be decomposed into V2 contracts first.
    source = gaps if gaps is not None else _items(project.get("knowledge_gaps"))
    annotated = annotate_gap_analysis_roles(project, [item for item in source if isinstance(item, dict)])
    dimensions = {name: _dimension_entry(name) for name in COVERAGE_DIMENSIONS}
    project_scope = _text(project.get("objective") or project.get("title") or project.get("domain"))
    if project_scope:
        dimensions["scope"]["status"] = "COVERED"
        dimensions["scope"]["values"] = [project_scope]
        dimensions["scope"]["reason"] = "Declared project scope; individual packages may narrow it further."
    for gap in annotated:
        role = str(gap.get("analysis_role") or "")
        evidence = _evidence_ids(gap)
        bundle = _bundle(gap)
        design_evidence = _mapping(bundle.get("research_design_evidence"))
        for fragment_id in _items(design_evidence.get("supporting_fragment_ids")):
            fragment_text = _text(fragment_id)
            if fragment_text and fragment_text not in evidence:
                evidence.append(fragment_text)
        scope = _scope_for_gap(project, gap)
        mode = _mode_for_gap(gap)
        if role == "OBJECT_SCOPE":
            _add_dimension(dimensions["scope"], gap, scope, evidence=evidence)
        _add_dimension(dimensions["mode"], gap, mode, evidence=evidence)
        _add_dimension(dimensions["input"], gap, _value_from_gap(gap, "intervention", "input", "premise"), evidence=evidence)
        _add_dimension(dimensions["mechanism"], gap, _value_from_gap(gap, "mediator", "proposed_mediator", "mechanism"), evidence=evidence)
        _add_dimension(dimensions["outcome"], gap, _value_from_gap(gap, "outcome", "output", "observable_outcome"), evidence=evidence)
        _add_dimension(dimensions["comparison"], gap, _value_from_gap(gap, "comparison", "control", "baseline"), evidence=evidence)
        _add_dimension(dimensions["falsification"], gap, _value_from_gap(gap, "falsification", "failure_criterion"), evidence=evidence)
        boundary = _value_from_gap(gap, "boundary", "boundary_condition", "constraint", "conditions", "threshold_to_test")
        if role in {"BOUNDARY_CONSTRAINT", "SPACETIME_OR_RESOURCE"}:
            boundary = boundary or _text(gap.get("description") or gap.get("gap_description"))
        _add_dimension(dimensions["resource_boundary"], gap, boundary, evidence=evidence)
        measurement = _value_from_gap(gap, "measurement", "metric", "observable", "readout")
        if role in {"MEASUREMENT_VALIDITY", "BENCHMARK_VALIDITY"}:
            measurement = measurement or _text(gap.get("description") or gap.get("gap_description"))
        # A source-linked outcome is a minimally usable measurement mapping.
        if not measurement and _value_from_gap(gap, "outcome", "output") and evidence:
            measurement = _value_from_gap(gap, "outcome", "output")
        _add_dimension(dimensions["measurement"], gap, measurement, evidence=evidence)
        transfer = _value_from_gap(gap, "transferability", "generalization", "scaling", "replication", "robustness")
        if role in {"TRANSLATION_OR_SCALING", "REPLICATION_OR_ROBUSTNESS"}:
            transfer = transfer or _text(gap.get("description") or gap.get("gap_description"))
        _add_dimension(dimensions["transferability"], gap, transfer, evidence=evidence)
        if evidence:
            _add_dimension(dimensions["evidence_status"], gap, "source-traceable evidence bundle", evidence=evidence)

    required_for_local = ("scope", "mode", "input", "mechanism", "outcome", "comparison", "falsification", "measurement", "evidence_status")
    missing = [name for name in required_for_local if dimensions[name]["status"] != "COVERED"]
    partial = [name for name, entry in dimensions.items() if entry["status"] != "COVERED" and name not in missing]
    return {
        "schema_version": "research_coverage_map.v1",
        "scope": "project_landscape",
        "dimensions": dimensions,
        "required_for_local_causal_hypothesis": list(required_for_local),
        "missing_required": missing,
        "partial_or_uncovered": partial,
        "gap_roles": { _gap_id(gap): gap.get("analysis_role") for gap in annotated if _gap_id(gap) },
        "research_design_evidence_by_gap": {
            _gap_id(gap): {
                "recommended_mode": _mapping(_bundle(gap).get("research_design_evidence")).get("recommended_mode"),
                "supporting_fragment_ids": list(
                    _mapping(_bundle(gap).get("research_design_evidence")).get("supporting_fragment_ids") or []
                ),
                "source": _mapping(_bundle(gap).get("research_design_evidence")).get("source"),
            }
            for gap in annotated if _gap_id(gap)
        },
        "mechanism_gap_ids": [_gap_id(gap) for gap in annotated if gap.get("analysis_role") == "MECHANISM_GAP" and _gap_id(gap)],
    }


def _scope_overlap(project: dict[str, Any], left: dict[str, Any], right: dict[str, Any]) -> bool:
    left_sub = _text(left.get("sub_hypothesis_id"))
    right_sub = _text(right.get("sub_hypothesis_id"))
    if left_sub and right_sub and left_sub == right_sub:
        return True
    shared_refs = set(_evidence_ids(left)) & set(_evidence_ids(right))
    if shared_refs:
        return True
    bridge_ids = {str(value) for value in _items(left.get("bridges_to_gap_ids")) + _items(right.get("bridges_to_gap_ids"))}
    if _gap_id(left) in bridge_ids or _gap_id(right) in bridge_ids:
        return True
    # A bridge must be explicit when two independently scoped hypotheses are
    # combined; shared project membership alone is not a scientific bridge.
    return bool(_text(left.get("explicit_scope_bridge")) and _text(right.get("explicit_scope_bridge")))


def _modes_compatible(left: str, right: str) -> bool:
    if not left or not right or left == right:
        return True
    intervention_modes = {
        "CONTROLLED_INTERVENTION", "COMPUTATIONAL_INTERVENTION",
        "NATURAL_EXPERIMENT_OR_QUASI_EXPERIMENT", "LABORATORY_CONSTRAINT",
    }
    observational_modes = {"OBSERVATIONAL_MODEL_DISCRIMINATION", "INSTRUMENTATION_OR_MEASUREMENT"}
    if left in intervention_modes and right in intervention_modes:
        return True
    if left in observational_modes and right in observational_modes:
        return True
    return False


def _value_terms(value: str) -> set[str]:
    ignored = {
        "the", "and", "with", "under", "from", "into", "that", "this", "does", "not", "for",
        "matched", "baseline", "control", "controlled", "variation", "change", "effect", "outcome", "result", "measure",
        "operation", "condition", "conditions", "system", "study", "test",
    }
    import re
    return {term.lower() for term in re.findall(r"\w{3,}", _text(value)) if term.lower() not in ignored}


def _values_compatible(left: str, right: str, *, explicit_bridge: bool) -> bool:
    if not left or not right or explicit_bridge:
        return True
    return bool(_value_terms(left) & _value_terms(right))


def build_gap_compatibility_graph(project: dict[str, Any], mechanism_gaps: list[dict[str, Any]]) -> dict[str, Any]:
    """Audit whether causal gaps form a valid path, not merely a high rank."""
    nodes = [gap for gap in mechanism_gaps if isinstance(gap, dict) and _gap_id(gap)]
    edges: list[dict[str, Any]] = []
    for index, left in enumerate(nodes):
        for right in nodes[index + 1:]:
            scope_ok = _scope_overlap(project, left, right)
            left_mode, right_mode = _mode_for_gap(left), _mode_for_gap(right)
            mode_ok = _modes_compatible(left_mode, right_mode)
            left_outcome = _value_from_gap(left, "outcome", "output", "observable_outcome")
            right_outcome = _value_from_gap(right, "outcome", "output", "observable_outcome")
            explicit_bridge = bool(
                (_text(left.get("explicit_scope_bridge")) and _text(right.get("explicit_scope_bridge")))
                or (_text(left.get("explicit_task_bridge")) and _text(right.get("explicit_task_bridge")))
                or (_text(left.get("explicit_scale_bridge")) and _text(right.get("explicit_scale_bridge")))
            )
            left_task = _value_from_gap(left, "intervention", "input", "premise")
            right_task = _value_from_gap(right, "intervention", "input", "premise")
            task_ok = _values_compatible(left_task, right_task, explicit_bridge=explicit_bridge)
            left_scale = _value_from_gap(left, "boundary", "boundary_condition", "constraint", "conditions", "resource_boundary")
            right_scale = _value_from_gap(right, "boundary", "boundary_condition", "constraint", "conditions", "resource_boundary")
            scale_ok = _values_compatible(left_scale, right_scale, explicit_bridge=explicit_bridge)
            outcome_ok = _values_compatible(left_outcome, right_outcome, explicit_bridge=explicit_bridge)
            left_measurement = _value_from_gap(left, "measurement", "metric", "observable", "readout") or left_outcome
            right_measurement = _value_from_gap(right, "measurement", "metric", "observable", "readout") or right_outcome
            measurement_ok = _values_compatible(left_measurement, right_measurement, explicit_bridge=explicit_bridge)
            conflict = bool(left.get("unresolved_scope_conflict") or right.get("unresolved_scope_conflict"))
            compatible = scope_ok and task_ok and scale_ok and mode_ok and outcome_ok and measurement_ok and not conflict
            edges.append(
                {
                    "from_gap_id": _gap_id(left),
                    "to_gap_id": _gap_id(right),
                    "compatible": compatible,
                    "scope_compatible": scope_ok,
                    "task_compatible": task_ok,
                    "scale_compatible": scale_ok,
                    "mode_compatible": mode_ok,
                    "outcome_compatible": outcome_ok,
                    "measurement_compatible": measurement_ok,
                    "unresolved_conflict": conflict,
                    "reason": "shared scientific object/explicit bridge with compatible research modes" if compatible else (
                        "No explicit object bridge between independently scoped gaps." if not scope_ok else
                        "Interventions/premises do not specify one compatible task without an explicit bridge." if not task_ok else
                        "Boundary or scale assumptions are incompatible without an explicit bridge." if not scale_ok else
                        "Research modes cannot support one joint causal claim." if not mode_ok else
                        "Primary outcomes or measurement definitions do not support one joint causal claim." if not (outcome_ok and measurement_ok) else
                        "An unresolved scope or interpretation conflict remains."
                    ),
                }
            )
    return {"schema_version": "gap_compatibility_graph.v1", "nodes": [_gap_id(gap) for gap in nodes], "edges": edges}


def coverage_and_compatibility_gate(package: dict[str, Any]) -> dict[str, Any]:
    """Single Socrates→MingLi gate for a complete hypothesis package.

    The gate is intentionally separate from package construction so callers
    can persist the exact decision, its missing roles, incompatible edges, and
    conclusion restrictions.  A non-empty-looking Package is not sufficient:
    all local causal slots must be covered and every selected mechanism edge
    must be compatible.
    """
    package = package if isinstance(package, dict) else {}
    if package.get("schema_version") == "hypothesis_package_v2_type_directed":
        try:
            from ._type_directed_hypothesis_packages import type_directed_coverage_gate
        except ImportError:
            from _type_directed_hypothesis_packages import type_directed_coverage_gate
        return type_directed_coverage_gate(package)
    return {
        "schema_version": "type_directed_coverage_gate_v2",
        "hypothesis_package_id": _text(package.get("hypothesis_package_id")),
        "package_type": _text(package.get("package_type")),
        "status": "RESEARCH_QUESTION_CONTRACT_V2_REQUIRED",
        "ready": False,
        "missing_required_coverage": ["hypothesis_package_v2_type_directed"],
        "missing_source_lineage_slots": [],
        "source_text_lineage_status": "SOURCE_TEXT_LINEAGE_INCOMPLETE",
        "incompatible_edges": [],
        "primary_gap_ids": [],
        "allowed_conclusion_strength": ["descriptive_scope_bound_claim"],
        "forbidden_conclusions": ["evidence_complete_or_mechanism_complete_claim"],
        "reasons": ["The historical hypothesis-package schema is not accepted by the V2/V3 gate."],
    }
    # Historical causal-package gate below is intentionally unreachable.
    coverage = _mapping(package.get("coverage_audit"))
    missing = [str(item) for item in coverage.get("missing_required", []) if str(item)]
    compatibility = _mapping(package.get("compatibility_audit"))
    incompatible_edges = [
        edge for edge in _items(compatibility.get("edges"))
        if isinstance(edge, dict) and edge.get("compatible") is False
    ]
    primary_ids = [str(item) for item in _items(package.get("primary_gap_ids")) if str(item)]
    restricted_ids = [str(item) for item in _items(package.get("restricted_component_bridge_gap_ids")) if str(item)]
    package_status = str(package.get("status") or "")
    package_type = str(package.get("package_type") or package.get("hypothesis_package_type") or "primary_mechanism")
    restricted = package_type == "restricted_component_bridge"
    missing_source_lineage_slots = [
        str(item)
        for item in _items(package.get("missing_source_lineage_slots"))
        if str(item)
    ]
    if not missing_source_lineage_slots and not restricted:
        lineage = _mapping(package.get("hypothesis_source_lineage"))
        missing_source_lineage_slots = [
            str(item)
            for item in _items(lineage.get("missing_slots"))
            if str(item)
        ]
        if not missing_source_lineage_slots:
            lineage_slots = _mapping(package.get("slot_source_lineage") or lineage.get("slots"))
            if not lineage_slots:
                missing_source_lineage_slots = ["input", "mechanism", "outcome", "measurement"]
            else:
                slots = _mapping(package.get("slots"))
                required_lineage_slots = ["input", "mechanism", "outcome"]
                if _slot_text(slots.get("measurement")):
                    required_lineage_slots.append("measurement")
                missing_source_lineage_slots = [
                    slot for slot in required_lineage_slots
                    if not _items(lineage_slots.get(slot))
                ]
    restricted_slot_audit = _mapping(package.get("restricted_component_bridge_slot_audit"))
    if restricted and not restricted_slot_audit:
        restricted_slot_audit = _audit_restricted_component_bridge_slots(
            _mapping(package.get("slots"))
        )
    claim_cap = str(package.get("claim_strength_cap") or "")
    may_support_final_object_claim = package.get("may_support_final_object_claim")
    restricted_policy_intact = bool(
        restricted
        and (restricted_ids or primary_ids)
        and claim_cap == "no_final_object_claim_validation"
        and may_support_final_object_claim is not True
        and package.get("post_draft_socrates_enrichment_required") is True
    )
    ready = (
        bool(primary_ids)
        and not missing
        and not missing_source_lineage_slots
        and not incompatible_edges
        and package_status == "READY_FOR_MINGLI"
    )
    if restricted:
        ready = bool(
            restricted_policy_intact
            and restricted_slot_audit.get("ready") is True
            and not incompatible_edges
            and package_status == "READY_FOR_RESTRICTED_MINGLI"
        )
    reasons: list[str] = []
    if restricted:
        if not (restricted_ids or primary_ids):
            reasons.append("No restricted component-bridge gap is available.")
        if not restricted_policy_intact:
            reasons.append("Restricted component-bridge claim cap or post-draft Socrates policy is missing.")
        if restricted_slot_audit.get("ready") is not True:
            reasons.append(
                "Restricted component-bridge role contract is incomplete: "
                + ", ".join(str(item) for item in (restricted_slot_audit.get("missing_roles") or []))
            )
    elif not primary_ids:
        reasons.append("No primary mechanism gap is available.")
    if missing and not restricted:
        reasons.append("Missing required coverage: " + ", ".join(missing))
    if missing_source_lineage_slots and not restricted:
        reasons.append(
            "Missing source-text lineage for required slots: "
            + ", ".join(missing_source_lineage_slots)
        )
    if incompatible_edges:
        reasons.append("Incompatible mechanism links: " + "; ".join(str(edge.get("reason") or "incompatible") for edge in incompatible_edges[:3]))
    expected_status = "READY_FOR_RESTRICTED_MINGLI" if restricted else "READY_FOR_MINGLI"
    if package_status and package_status != expected_status and not reasons:
        reasons.extend(str(item) for item in _items(package.get("blocked_reasons")) if str(item))
    lineage_blocked = bool(
        missing_source_lineage_slots
        and not restricted
        and primary_ids
        and not missing
        and not incompatible_edges
    )
    blocked_status = "SOURCE_TEXT_LINEAGE_INCOMPLETE" if lineage_blocked else "BLOCKED"
    return {
        "schema_version": "coverage_and_compatibility_gate.v1",
        "hypothesis_package_id": str(package.get("hypothesis_package_id") or ""),
        "package_type": package_type,
        "status": expected_status if ready else blocked_status,
        "ready": ready,
        "missing_required_coverage": missing,
        "missing_source_lineage_slots": missing_source_lineage_slots,
        "source_text_lineage_status": (
            "SOURCE_TEXT_LINEAGE_COMPLETE"
            if not missing_source_lineage_slots or restricted
            else "SOURCE_TEXT_LINEAGE_INCOMPLETE"
        ),
        "incompatible_edges": incompatible_edges,
        "primary_gap_ids": primary_ids,
        "restricted_component_bridge_gap_ids": restricted_ids,
        "restricted_component_bridge_policy_intact": restricted_policy_intact if restricted else False,
        "restricted_component_bridge_slot_audit": restricted_slot_audit if restricted else {},
        "claim_strength_cap": claim_cap,
        "may_support_final_object_claim": bool(may_support_final_object_claim),
        "post_draft_socrates_enrichment_required": bool(package.get("post_draft_socrates_enrichment_required")),
        "final_object_claim_disclaimer": str(package.get("final_object_claim_disclaimer") or ""),
        "allowed_conclusion_strength": list(_mapping(package.get("conclusion_scope")).get("allowed") or []),
        "forbidden_conclusions": list(_mapping(package.get("conclusion_scope")).get("forbidden") or []),
        "reasons": reasons,
    }


def select_compatible_mechanism_gaps(project: dict[str, Any], gaps: list[dict[str, Any]], limit: int = 3) -> list[dict[str, Any]]:
    """Greedily select at most ``limit`` mechanism gaps with a valid path."""
    candidates = [gap for gap in annotate_gap_analysis_roles(project, gaps) if gap.get("analysis_role") == "MECHANISM_GAP"]
    candidates.sort(
        key=lambda gap: (
            -float(gap.get("exploration_value_score") or gap.get("mechanistic_priority") or 0.0),
            -float(_mapping(gap.get("mechanism_relevance")).get("score") or 0.0),
            _gap_id(gap),
        )
    )
    selected: list[dict[str, Any]] = []
    maximum = max(1, min(3, int(limit or 3)))
    for candidate in candidates:
        if len(selected) >= maximum:
            break
        graph = build_gap_compatibility_graph(project, selected + [candidate])
        if all(edge.get("compatible") for edge in graph["edges"] if candidate.get("gap_id") in {edge.get("from_gap_id"), edge.get("to_gap_id")}):
            selected.append(candidate)
    return selected


def _supporting_roles(project: dict[str, Any], primary: list[dict[str, Any]], all_gaps: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    roles: dict[str, list[dict[str, Any]]] = {}
    anchor = primary[0] if primary else {}
    for gap in annotate_gap_analysis_roles(project, all_gaps):
        # A supporting boundary, metric, or alternative must belong to the
        # same scientific object (or carry an explicit bridge).  Otherwise a
        # strong measurement paper from a different sub-hypothesis could make
        # an unrelated mechanism package appear complete.
        if anchor and _gap_id(gap) != _gap_id(anchor) and not _scope_overlap(project, anchor, gap):
            continue
        role = str(gap.get("analysis_role") or "BACKGROUND_OR_FOUNDATION")
        roles.setdefault(role, []).append(gap)
    for gap in primary:
        if _is_restricted_component_bridge_gap(gap):
            continue
        roles.setdefault("MECHANISM_GAP", [])
        if _gap_id(gap) not in {_gap_id(item) for item in roles["MECHANISM_GAP"]}:
            roles["MECHANISM_GAP"].append(gap)
    return roles


def _slot_value(primary: list[dict[str, Any]], supporting: dict[str, list[dict[str, Any]]], names: tuple[str, ...], roles: tuple[str, ...] = ()) -> str:
    for gap in primary:
        value = _value_from_gap(gap, *names)
        if value:
            return value
    for role in roles:
        for gap in supporting.get(role, []):
            value = _value_from_gap(gap, *names) or _text(gap.get("description") or gap.get("gap_description"))
            if value:
                return value
    return ""


def _conclusion_scope(coverage: dict[str, Any], compatible: bool, primary_count: int) -> dict[str, Any]:
    dims = _mapping(coverage.get("dimensions"))
    covered = lambda name: _mapping(dims.get(name)).get("status") == "COVERED"
    allowed = ["descriptive_scope_bound_claim"]
    if compatible and not coverage.get("missing_required") and primary_count:
        allowed.append("local_causal_hypothesis")
    if covered("resource_boundary") and covered("transferability"):
        allowed.append("conditional_generalizable_mechanism")
    if covered("resource_boundary") and covered("transferability") and covered("measurement") and covered("evidence_status"):
        allowed.append("formal_or_scope_bound_theory")
    forbidden = ["universal_or_domain_unbounded_claim"]
    if not covered("measurement") or not covered("transferability"):
        forbidden.append("cross_platform_or_cross_context_performance_claim")
    if not covered("resource_boundary"):
        forbidden.append("claim_outside_declared_validity_regime")
    return {"allowed": allowed, "forbidden": forbidden}


def build_hypothesis_package(
    project: dict[str, Any],
    mechanism_gaps: list[dict[str, Any]],
    *,
    all_gaps: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Assemble one auditable package around a compatible causal path."""
    try:
        from ._type_directed_hypothesis_packages import (
            build_blocked_type_directed_package,
            build_type_directed_hypothesis_packages,
            is_v2_v3_project,
        )
    except ImportError:
        from _type_directed_hypothesis_packages import (
            build_blocked_type_directed_package,
            build_type_directed_hypothesis_packages,
            is_v2_v3_project,
        )
    if is_v2_v3_project(project):
        packages = build_type_directed_hypothesis_packages(
            project,
            mechanism_gaps,
            all_gaps=all_gaps,
        )
        return packages[0] if packages else build_blocked_type_directed_package(project)
    return build_blocked_type_directed_package(project)
    # Historical causal-package construction below is intentionally unreachable.
    all_gap_list = [item for item in (all_gaps if all_gaps is not None else project.get("knowledge_gaps", [])) if isinstance(item, dict)]
    primary = select_compatible_mechanism_gaps(project, mechanism_gaps, limit=3)
    restricted_bridge = [] if primary else _select_restricted_component_bridge_gaps(
        project,
        [item for item in mechanism_gaps if isinstance(item, dict)] + all_gap_list,
        limit=1,
    )
    package_type = "restricted_component_bridge" if restricted_bridge else "primary_mechanism"
    anchor_gaps = primary if primary else restricted_bridge
    compatibility = build_gap_compatibility_graph(project, anchor_gaps)
    compatible = all(edge.get("compatible") for edge in compatibility.get("edges", []))
    supporting = _supporting_roles(project, anchor_gaps, all_gap_list)
    package_gap_ids = {
        _gap_id(gap)
        for values in supporting.values()
        for gap in values
        if _gap_id(gap)
    }
    package_gaps = anchor_gaps + [
        gap for gap in all_gap_list
        if _gap_id(gap) in package_gap_ids and _gap_id(gap) not in {_gap_id(item) for item in anchor_gaps}
    ]
    subhypothesis_contexts = _subhypothesis_context_for_gaps(project, package_gaps)
    subhypothesis_priority_context = {
        sub_id: {
            "tier": _text(context.get("tier")),
            "overall": float(context.get("priority_overall") or 0.0),
            "impact": int(context.get("impact") or 0),
            "feasibility": int(context.get("feasibility") or 0),
            "novelty": int(context.get("novelty") or 0),
            "strategic_alignment": int(context.get("strategic_alignment") or 0),
            "evidence_standard": _text(context.get("evidence_standard")),
        }
        for sub_id, context in subhypothesis_contexts.items()
    }
    evidence_standard_audit = {
        sub_id: {
            "schema_version": "hypothesis_package_evidence_standard_audit_v1",
            "evidence_standard_id": _text(context.get("evidence_standard")),
            "hypothesis_type": _text(context.get("hypothesis_type")),
            "scale": _text(context.get("scale")),
            "research_mode_prior": _text(context.get("research_mode_prior")),
            "accepted_core_designs": list(context.get("accepted_core_designs") or []),
            "support_designs": list(context.get("support_designs") or []),
            "excluded_as_core": list(context.get("excluded_as_core") or []),
            "why_this_evidence_is_allowed": (
                "The package requires the related-full-text corpus target plus "
                "a source-bound, SH-local cross-paper contract-slot bundle. A "
                "single direct source can strengthen the conclusion, but is not "
                "a prerequisite for a partial contract assessment."
            ),
            "readiness_core_metric": "source_bound_cross_paper_contract_slot_bundle",
            "single_paper_direct_evidence_diagnostic": dict(
                context.get("direct_core_by_evidence_lane") or {}
            ),
            "type_directed_evidence_bundle_status": _text(
                context.get("type_directed_evidence_bundle_status")
            ),
            "type_directed_evidence_bundle": dict(
                context.get("type_directed_evidence_bundle") or {}
            ),
            "standard_core_full_text_count": int(context.get("standard_core_full_text_count") or 0),
            "standard_core_full_text_target": int(context.get("standard_core_full_text_target") or 0),
            "direct_core_full_text_count": int(context.get("direct_core_full_text_count") or 0),
            "direct_core_full_text_target": int(context.get("direct_core_full_text_target") or 0),
            "peer_reviewed_full_text_count": int(context.get("peer_reviewed_full_text_count") or 0),
            "peer_reviewed_full_text_target": int(context.get("peer_reviewed_full_text_target") or 0),
            "imported_related_full_text_count": int(
                context.get("imported_related_full_text_count") or 0
            ),
            "imported_related_full_text_target": int(
                context.get("imported_related_full_text_target") or 0
            ),
            "direct_contract_core_count": int(
                context.get("direct_contract_core_count") or 0
            ),
            "noncore_related_full_text_count": int(
                context.get("noncore_related_full_text_count") or 0
            ),
            "imported_full_text_by_layer": dict(
                context.get("imported_full_text_by_layer") or {}
            ),
            "core_full_text_by_layer": dict(
                context.get("core_full_text_by_layer") or {}
            ),
            "noncore_full_text_by_role": dict(
                context.get("noncore_full_text_by_role") or {}
            ),
            "claim_strength_cap": _text(context.get("claim_strength_cap")),
            "priority_tier": _text(context.get("tier")),
            "priority_rationale": (
                context.get("priority_rationale")
                if isinstance(context.get("priority_rationale"), dict)
                else {}
            ),
        }
        for sub_id, context in subhypothesis_contexts.items()
    }
    package_claim_cap = _package_claim_strength_cap(subhypothesis_contexts)
    coverage = build_research_coverage_map(project, package_gaps)
    primary_ids = [_gap_id(gap) for gap in primary]
    restricted_bridge_ids = [_gap_id(gap) for gap in restricted_bridge]
    anchor = primary[0] if primary else restricted_bridge[0] if restricted_bridge else {}
    slots = {
        "scope": _scope_for_gap(project, anchor) if anchor else _text(project.get("objective") or project.get("title") or project.get("domain")),
        "input": _slot_value(anchor_gaps, supporting, ("intervention", "input", "premise"), ("INPUT_OR_PREMISE",)),
        "mechanism": _slot_value(anchor_gaps, supporting, ("mediator", "proposed_mediator", "mechanism"), ("MECHANISM_GAP",)),
        "outcome": _slot_value(anchor_gaps, supporting, ("outcome", "output", "observable_outcome"), ()),
        "boundary": _slot_value(anchor_gaps, supporting, ("boundary", "boundary_condition", "constraint", "conditions"), ("BOUNDARY_CONSTRAINT", "SPACETIME_OR_RESOURCE")),
        "comparison": _slot_value(anchor_gaps, supporting, ("comparison", "control", "baseline"), ("BENCHMARK_VALIDITY",)),
        "falsification": _slot_value(anchor_gaps, supporting, ("falsification", "failure_criterion"), ("COUNTEREXAMPLE_OR_ALTERNATIVE",)),
        "measurement": _slot_value(anchor_gaps, supporting, ("measurement", "metric", "observable", "readout", "outcome"), ("MEASUREMENT_VALIDITY", "BENCHMARK_VALIDITY")),
    }
    restricted_slot_audit = {
        "schema_version": "restricted_component_bridge_slot_audit_v1",
        "ready": False,
        "missing_roles": [],
        "required_roles": list(_RESTRICTED_BRIDGE_REQUIRED_ROLES),
        "status": "NOT_APPLICABLE",
    }
    if package_type == "restricted_component_bridge" and anchor:
        bridge_slots = _restricted_bridge_slots_from_gap(project, anchor)
        for key, value in bridge_slots.items():
            if _slot_text(value):
                slots[key] = value
        restricted_slot_audit = _audit_restricted_component_bridge_slots(slots)
    slot_source_lineage = _package_slot_source_lineage(slots, package_gaps)
    missing_source_lineage_slots = _missing_source_lineage_slots(
        slots,
        slot_source_lineage,
        package_type=package_type,
    )
    hypothesis_source_lineage = {
        "schema_version": "hypothesis_source_lineage_v1",
        "status": (
            "SOURCE_TEXT_LINEAGE_COMPLETE"
            if not missing_source_lineage_slots
            else "SOURCE_TEXT_LINEAGE_INCOMPLETE"
        ),
        "required_slots": (
            []
            if package_type == "restricted_component_bridge"
            else ["input", "mechanism", "outcome", "measurement"]
        ),
        "missing_slots": missing_source_lineage_slots,
        "slots": slot_source_lineage,
        "source_gap_ids": [_gap_id(gap) for gap in package_gaps if _gap_id(gap)],
    }
    scope = _conclusion_scope(coverage, compatible, len(primary))
    required_missing = list(coverage.get("missing_required") or [])
    if package_type == "restricted_component_bridge":
        coverage["restricted_component_bridge_missing_not_blocking"] = list(required_missing)
        coverage["missing_required_for_primary_mechanism_package"] = list(required_missing)
        allowed = list(scope.get("allowed") or [])
        if "restricted_component_bridge_hypothesis" not in allowed:
            allowed.append("restricted_component_bridge_hypothesis")
        forbidden = list(scope.get("forbidden") or [])
        for item in (
            "final_object_direct_causal_claim",
            "direct_core_validated_claim",
            "standard_core_or_primary_scientific_gap_claim",
            "universal_or_domain_unbounded_claim",
        ):
            if item not in forbidden:
                forbidden.append(item)
        scope = {"allowed": allowed, "forbidden": forbidden}
    if (
        package_type == "restricted_component_bridge"
        and restricted_bridge
        and compatible
        and restricted_slot_audit.get("ready") is True
    ):
        status = "READY_FOR_RESTRICTED_MINGLI"
    elif primary and compatible and not required_missing and not missing_source_lineage_slots:
        status = "READY_FOR_MINGLI"
    elif primary and compatible and not required_missing and missing_source_lineage_slots:
        status = "SOURCE_TEXT_LINEAGE_INCOMPLETE"
    else:
        status = "COVERAGE_INCOMPLETE"
    blocked_reasons: list[str] = []
    if status not in {"READY_FOR_MINGLI", "READY_FOR_RESTRICTED_MINGLI"}:
        if package_type == "restricted_component_bridge" and not restricted_bridge:
            blocked_reasons.append("No restricted component-bridge gap is available.")
        elif not primary:
            blocked_reasons.append("No compatible primary mechanism gap is available.")
        if not compatible:
            blocked_reasons.append("Primary gaps do not form one explicit scientific-object path.")
        if package_type == "restricted_component_bridge" and restricted_slot_audit.get("ready") is not True:
            blocked_reasons.append(
                "Restricted component-bridge role contract is incomplete: "
                + ", ".join(str(item) for item in (restricted_slot_audit.get("missing_roles") or []))
            )
        if required_missing and package_type != "restricted_component_bridge":
            blocked_reasons.append(f"Missing required coverage: {', '.join(required_missing)}")
        if missing_source_lineage_slots and package_type != "restricted_component_bridge":
            blocked_reasons.append(
                "Missing source-text lineage for required slots: "
                + ", ".join(missing_source_lineage_slots)
            )
    package_primary_ids = primary_ids if primary else restricted_bridge_ids
    package_claim_cap = (
        "no_final_object_claim_validation"
        if package_type == "restricted_component_bridge"
        else package_claim_cap
    )
    seed = "|".join([str(project.get("project_id") or ""), package_type, *package_primary_ids, slots["scope"]])
    package_id = "hp_" + sha1(seed.encode("utf-8")).hexdigest()[:16]
    package = {
        "schema_version": "hypothesis_package.v1",
        "hypothesis_package_id": package_id,
        "project_id": str(project.get("project_id") or ""),
        "package_type": package_type,
        "hypothesis_package_type": package_type,
        "status": status,
        "primary_gap_ids": package_primary_ids,
        "primary_gap_id": _gap_id(anchor),
        "primary_mechanism_gap_count": len(primary_ids),
        "restricted_component_bridge_gap_ids": restricted_bridge_ids,
        "restricted_component_bridge_gap_count": len(restricted_bridge_ids),
        "mechanism_budget": {"max_primary_mechanism_gaps": 3, "used": len(primary_ids)},
        "slots": slots,
        "slot_source_lineage": slot_source_lineage,
        "hypothesis_source_lineage": hypothesis_source_lineage,
        "missing_source_lineage_slots": missing_source_lineage_slots,
        "restricted_component_bridge_slot_audit": restricted_slot_audit,
        "supporting_role_gap_ids": {
            role: [_gap_id(gap) for gap in values if _gap_id(gap)]
            for role, values in supporting.items()
            if role != "MECHANISM_GAP"
        },
        "subhypothesis_priority_context": subhypothesis_priority_context,
        "claim_strength_cap": package_claim_cap,
        "evidence_standard_audit": evidence_standard_audit,
        "competing_mechanism_gap_ids": [_gap_id(gap) for gap in supporting.get("COUNTEREXAMPLE_OR_ALTERNATIVE", []) if _gap_id(gap)],
        "coverage_audit": coverage,
        "compatibility_audit": compatibility,
        "conclusion_scope": scope,
        "blocked_reasons": blocked_reasons,
    }
    if package_type == "restricted_component_bridge":
        package.update(
            {
                "primary_eligible": False,
                "core_eligible": False,
                "standard_core_eligible": False,
                "direct_core": False,
                "direct_core_evidence_allowed": False,
                "may_support_final_object_claim": False,
                "may_fill_primary_evidence_slots": False,
                "claim_strength_cap": "no_final_object_claim_validation",
                "claim_strength_effect": "no_final_object_claim_validation",
                "post_draft_socrates_enrichment_required": True,
                "final_object_claim_disclaimer": "限制声明：该假设仅由组件/桥接证据支持，不得声称最终研究对象已经得到验证。",
                "requires_human_review": True,
                "package_restrictions": {
                    "schema_version": "restricted_component_bridge_package_policy.v1",
                    "primary_eligible": False,
                    "direct_core": False,
                    "may_support_final_object_claim": False,
                    "claim_strength_cap": "no_final_object_claim_validation",
                    "post_draft_socrates_enrichment_required": True,
                    "final_object_claim_disclaimer": "限制声明：该假设仅由组件/桥接证据支持，不得声称最终研究对象已经得到验证。",
                    "forbidden_claims": [
                        "final_object_direct_causal_claim",
                        "direct_core_validated_claim",
                        "standard_core_or_primary_scientific_gap_claim",
                        "universal_or_domain_unbounded_claim",
                    ],
                },
            }
        )
    return package


def build_hypothesis_packages(
    project: dict[str, Any],
    mechanism_gaps: list[dict[str, Any]],
    *,
    all_gaps: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Return one coherent package; extensible to multiple scoped paths later."""
    try:
        from ._type_directed_hypothesis_packages import (
            build_type_directed_hypothesis_packages,
            is_v2_v3_project,
        )
    except ImportError:
        from _type_directed_hypothesis_packages import (
            build_type_directed_hypothesis_packages,
            is_v2_v3_project,
        )
    if is_v2_v3_project(project):
        packages = build_type_directed_hypothesis_packages(
            project,
            mechanism_gaps,
            all_gaps=all_gaps,
        )
        if packages:
            return packages
        try:
            from ._type_directed_hypothesis_packages import build_blocked_type_directed_package
        except ImportError:
            from _type_directed_hypothesis_packages import build_blocked_type_directed_package
        return [build_blocked_type_directed_package(project)]
    try:
        from ._type_directed_hypothesis_packages import build_blocked_type_directed_package
    except ImportError:
        from _type_directed_hypothesis_packages import build_blocked_type_directed_package
    return [build_blocked_type_directed_package(project)]
    # Historical causal-package construction below is intentionally unreachable.
    package = build_hypothesis_package(project, mechanism_gaps, all_gaps=all_gaps)
    return [package]


def package_for_gap(project: dict[str, Any], gap_id: str) -> dict[str, Any]:
    """Find the active compatible package containing ``gap_id``."""
    wanted = _text(gap_id)
    candidates = [
        item for item in _items(project.get("hypothesis_packages"))
        if isinstance(item, dict) and wanted in {str(value) for value in _items(item.get("primary_gap_ids"))}
    ]
    candidates.sort(
        key=lambda item: (
            0 if item.get("status") in {"READY_FOR_MINGLI", "READY_FOR_RESTRICTED_MINGLI"} else 1,
            str(item.get("hypothesis_package_id") or ""),
        )
    )
    return dict(candidates[0]) if candidates else {}


def package_debate_questions(package: dict[str, Any]) -> list[dict[str, Any]]:
    """Produce role-specific adversarial questions from an auditable package."""
    if not isinstance(package, dict):
        return []
    coverage = _mapping(package.get("coverage_audit"))
    dimensions = _mapping(coverage.get("dimensions"))
    role_map = (
        ("scope", "Scope", "What exact object, regime, and conclusion boundary does this hypothesis cover?", "State the scoped object and prohibit extrapolation beyond it."),
        ("mechanism", "Mechanism", "Which causal connector separates the proposed mechanism from a correlation?", "Map the mediator to an intervention and an outcome with evidence."),
        ("resource_boundary", "Boundary", "Which resource, regime, or validity boundary would make the result fail?", "Add a declared boundary condition and a failure region."),
        ("comparison", "Alternative", "Which matched comparison or competing explanation could reproduce the endpoint?", "Name a control and a discriminating alternative-mechanism test."),
        ("measurement", "Measurement", "How is the claimed outcome observed, calibrated, and distinguished from measurement artefact?", "Specify the primary readout and its validity check."),
        ("transferability", "Transfer", "What evidence justifies—or limits—transfer across conditions, platforms, or scale?", "Restrict the claim or add a cross-context validation requirement."),
        ("falsification", "Falsification", "What observation would actually reject the mechanism rather than merely weaken it?", "State a preregisterable failure criterion."),
        ("evidence_status", "Evidence", "Which direct evidence sources support every causal connector?", "Attach source-traceable evidence or label the connector speculative."),
    )
    questions: list[dict[str, Any]] = []
    for dimension, role, question, revision in role_map:
        entry = _mapping(dimensions.get(dimension))
        if entry.get("status") != "COVERED":
            questions.append({
                "question_type": "coverage_" + dimension,
                "coverage_role": role,
                "question": question,
                "target_claim": _text(_mapping(package.get("slots")).get("scope")),
                "why_it_matters": f"The {dimension} coverage slot is not yet source-traceably covered.",
                "required_revision": revision,
                "severity": "high",
            })
    return questions
