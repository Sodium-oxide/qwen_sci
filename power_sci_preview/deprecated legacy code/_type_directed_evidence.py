"""Type-directed V3 evidence profiles and source admission.

This module is the only common admission vocabulary between candidate
retrieval and the Research Evidence Graph.  It deliberately does *not*
project every research question onto an input--mediator--outcome chain.
Instead, an RQ contract declares its likely gap types and evidence slots;
source-bound V3 admissions decide whether a document has satisfied a slot.

The module contains no migration adapter for historical causal-edge records.
Those records are not an admissible input to this interface.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping

try:
    from ._gap_types import GapType, ScopeStatus, normalize_gap_type
except ImportError:
    from _gap_types import GapType, ScopeStatus, normalize_gap_type


TYPE_DIRECTED_EVIDENCE_PROFILE_VERSION = "type_directed_evidence_profile_v3"
TYPE_DIRECTED_ADMISSION_VERSION = "type_directed_admission_v3"


# These obligations describe what a *kind of knowledge gap* needs.  The
# contract's explicit required_slots remain the operative source-admission
# slots; the ontology obligations are transparent diagnostics and retrieval
# guidance rather than hidden requirements.
TYPE_REQUIREMENTS: dict[GapType, tuple[str, ...]] = {
    GapType.EMPIRICAL_COVERAGE: ("direct_observation", "coverage_dimension"),
    GapType.AUTHOR_STATED_LIMITATION: ("author_limitation", "affected_claim"),
    GapType.CAUSAL_IDENTIFICATION: (
        "causal_relation",
        "identification_design",
        "alternative_explanation",
    ),
    GapType.MECHANISM_COMPETITION: (
        "candidate_mechanisms",
        "shared_endpoint",
        "discriminating_prediction",
    ),
    GapType.BOUNDARY_HETEROGENEITY: (
        "boundary_variable",
        "condition_difference",
        "comparability_assessment",
    ),
    GapType.CONTRADICTION_REPLICATION: (
        "independent_results",
        "result_disagreement",
        "comparability_assessment",
    ),
    GapType.MEASUREMENT_OPERATIONALIZATION: (
        "construct",
        "proxy_target_mapping",
        "validation_or_calibration",
    ),
    GapType.THEORY_MATHEMATICAL: (
        "formal_claim",
        "assumptions",
        "falsification_or_counterexample_path",
    ),
    GapType.GENERALIZATION_TRANSPORTABILITY: (
        "source_domain",
        "target_domain",
        "shift_or_transport_assessment",
    ),
    GapType.METHOD_DESIGN: (
        "method_failure_mode",
        "alternative_design",
        "evaluation_criterion",
    ),
    GapType.DATA_COVERAGE: (
        "coverage_descriptor",
        "impact_on_claim",
        "acquisition_path",
    ),
    GapType.SCALE_INTEGRATION: (
        "source_scale",
        "target_scale",
        "bridge_variable",
    ),
    GapType.BENCHMARK_COMPARISON: (
        "candidate_systems",
        "shared_task_or_metric",
        "comparison_protocol",
    ),
    GapType.TRANSLATION_IMPLEMENTATION: (
        "deployment_context",
        "implementation_barrier",
        "real_world_validation",
    ),
}

CAUSAL_GAP_TYPES = frozenset({
    GapType.CAUSAL_IDENTIFICATION,
    GapType.MECHANISM_COMPETITION,
})


def _text(value: Any) -> str:
    return " ".join(str(value or "").split())


def _unique(values: Iterable[Any]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = _text(value)
        if text and text not in seen:
            seen.add(text)
            output.append(text)
    return output


def expected_gap_types_for_contract(contract: Mapping[str, Any] | None) -> list[GapType]:
    """Read explicit V3 priors without inferring a fallback or adapting V2."""

    try:
        from ._research_question_contract import validate_research_question_contract
    except ImportError:
        from _research_question_contract import validate_research_question_contract
    source = validate_research_question_contract(dict(contract or {}))
    question = source.get("research_question") if isinstance(source.get("research_question"), Mapping) else {}
    raw = question.get("expected_gap_type_priors")
    values = raw if isinstance(raw, (list, tuple, set)) else [raw]
    result: list[GapType] = []
    for value in values:
        gap_type = normalize_gap_type(value)
        if gap_type is not None and gap_type not in result:
            result.append(gap_type)
    return result


def is_mechanism_contract(contract: Mapping[str, Any] | None) -> bool:
    """Whether mechanism seeding is meaningful for this declared RQ contract."""

    return bool(set(expected_gap_types_for_contract(contract)) & CAUSAL_GAP_TYPES)


def evidence_profile_for_contract(
    contract: Mapping[str, Any] | None,
    *,
    requested_evidence_kind: str = "",
) -> dict[str, Any]:
    """Compile the type-directed evidence profile for a single RQ contract."""

    try:
        from ._research_question_contract import (
            ResearchQuestionKind,
            build_retrieval_obligation_v3,
            source_role_for_contract_slot,
            validate_research_question_contract,
        )
    except ImportError:
        from _research_question_contract import (
            ResearchQuestionKind,
            build_retrieval_obligation_v3,
            source_role_for_contract_slot,
            validate_research_question_contract,
        )
    source = validate_research_question_contract(dict(contract or {}))
    evidence = source.get("evidence_contract") if isinstance(source.get("evidence_contract"), Mapping) else {}
    gap_types = expected_gap_types_for_contract(source)
    required_slots = _unique(evidence.get("required_slots") or [])
    optional_slots = _unique(evidence.get("optional_slots") or [])
    required_comparability_axes = _unique(evidence.get("required_comparability_axes") or [])
    type_requirements = {
        gap_type.value: list(TYPE_REQUIREMENTS[gap_type])
        for gap_type in gap_types
    }
    question_kind = ResearchQuestionKind(
        str((source.get("research_question") or {}).get("question_kind") or "")
    )
    retrieval_obligations = [
        build_retrieval_obligation_v3(
            source,
            slot_id=slot,
            evidence_role="DIRECT",
            required_source_role=source_role_for_contract_slot(source, question_kind, slot),
        )
        for slot in required_slots
    ]
    causal_requirement_active = bool(set(gap_types) & CAUSAL_GAP_TYPES)
    return {
        "schema_version": TYPE_DIRECTED_EVIDENCE_PROFILE_VERSION,
        "research_question_contract_id": _text(source.get("contract_id")),
        "research_question_contract_revision": _text(
            source.get("contract_revision") or source.get("declaration_hash")
        ),
        "gap_types": [item.value for item in gap_types],
        "required_slots": required_slots,
        "optional_slots": optional_slots,
        "required_comparability_axes": required_comparability_axes,
        "type_requirements": type_requirements,
        "retrieval_obligations": retrieval_obligations,
        "requested_evidence_kind": _text(requested_evidence_kind),
        "causal_requirement_active": causal_requirement_active,
        "admission_authority": "gap_source_admission_v4",
    }


def _admission_for_contract(
    record: Mapping[str, Any] | None,
    contract: Mapping[str, Any] | None,
) -> dict[str, Any]:
    source = record if isinstance(record, Mapping) else {}
    contract_source = contract if isinstance(contract, Mapping) else {}
    contract_id = _text(contract_source.get("contract_id"))
    admissions = source.get("gap_source_admissions_v4")
    if not isinstance(admissions, Mapping) or not contract_id:
        return {}
    admission = admissions.get(contract_id)
    if not isinstance(admission, Mapping):
        return {}
    if _text(admission.get("schema_version")) != "gap_source_admission_v4":
        return {}
    return dict(admission)


def _supported_source_span_ids(admission: Mapping[str, Any]) -> list[str]:
    values: list[str] = []
    supports = admission.get("admitted_slot_supports")
    if not isinstance(supports, Mapping):
        return values
    for slot_supports in supports.values():
        entries = slot_supports if isinstance(slot_supports, list) else []
        for entry in entries:
            if isinstance(entry, Mapping):
                span_ids = entry.get("source_span_ids")
                unit_ids = entry.get("source_unit_ids")
                if isinstance(span_ids, (list, tuple, set)):
                    values.extend(span_ids)
                elif entry.get("source_span_id"):
                    values.append(entry.get("source_span_id"))
                if isinstance(unit_ids, (list, tuple, set)):
                    values.extend(unit_ids)
                elif entry.get("source_unit_id"):
                    values.append(entry.get("source_unit_id"))
    return _unique(values)


def type_directed_admission(
    record: Mapping[str, Any] | None,
    contract: Mapping[str, Any] | None,
    *,
    context_admitted: bool = False,
    excluded: bool = False,
    panel_core_allowed: bool = True,
    requested_evidence_kind: str = "",
) -> dict[str, Any]:
    """Project a contract-keyed V4 source admission into retrieval semantics.

    A metadata candidate may be imported when it is context-admitted so that
    full text can be acquired.  It can never be direct/core evidence before a
    current ``gap_source_admission_v4`` explicitly supports one or more
    contract slots.  No historical causal-edge assessment is inspected.
    """

    profile = evidence_profile_for_contract(
        contract,
        requested_evidence_kind=requested_evidence_kind,
    )
    admission = _admission_for_contract(record, contract)
    required_slots = list(profile["required_slots"])
    admitted_slots = _unique(admission.get("eligible_slot_ids") or [])
    missing_slots = [slot for slot in required_slots if slot not in set(admitted_slots)]
    admission_level = _text(admission.get("admission_level")).upper()
    scope = (
        ScopeStatus.CORE.value if admission_level == "DIRECT_EVIDENCE"
        else ScopeStatus.OUT_OF_SCOPE.value if admission_level == "HARD_REJECT"
        else ScopeStatus.BACKGROUND.value
    )
    direct = bool(
        admission.get("direct_evidence_eligible") is True
        and admission.get("eligible_for_gap_synthesis") is True
        and admission.get("counts_toward_gate") is True
        and admission_level == "DIRECT_EVIDENCE"
    )
    component_bridge = False
    comparability = admission.get("scope_comparability")
    comparability = dict(comparability) if isinstance(comparability, Mapping) else {}
    missing_scope_axes = _unique(comparability.get("missing_axes") or [])
    has_current_source_admission = bool(admission)
    core_eligible = bool(direct and context_admitted and not excluded and panel_core_allowed)
    import_eligible = bool(
        context_admitted
        and not excluded
        and admission_level != "HARD_REJECT"
    )
    if core_eligible:
        lane = "TYPE_DIRECTED_PRIMARY_SOURCE_EVIDENCE"
        role = "direct_type_directed_evidence"
        status = "DIRECT_SLOT_ADMITTED"
    elif component_bridge and import_eligible:
        lane = "TYPE_DIRECTED_COMPONENT_BRIDGE_EVIDENCE"
        role = "component_bridge_evidence"
        status = "COMPONENT_BRIDGE_ADMITTED"
    elif has_current_source_admission and import_eligible:
        lane = "TYPE_DIRECTED_BACKGROUND_CONTEXT"
        role = "source_bound_background"
        status = "SOURCE_BOUND_NOT_DIRECT"
    elif import_eligible:
        lane = "PENDING_FULLTEXT_TYPE_DIRECTED_EVIDENCE"
        role = "pending_type_directed_evidence"
        status = "PENDING_SOURCE_ADMISSION"
    else:
        lane = "OUT_OF_SCOPE_TYPE_DIRECTED_EVIDENCE"
        role = "out_of_scope"
        status = "OUT_OF_SCOPE_OR_EXCLUDED"
    missing_requirements: list[str] = []
    if not has_current_source_admission and import_eligible:
        missing_requirements.append("source_admission_not_materialized")
    missing_requirements.extend(f"required_slot:{slot}" for slot in missing_slots)
    missing_requirements.extend(f"scope_axis:{axis}" for axis in missing_scope_axes)
    if not panel_core_allowed:
        missing_requirements.append("panel_core_path_not_allowed")
    if excluded:
        missing_requirements.append("explicit_exclusion")
    return {
        "schema_version": TYPE_DIRECTED_ADMISSION_VERSION,
        "evidence_profile": profile,
        "source_admission": admission,
        "source_admission_present": has_current_source_admission,
        "admission_status": status,
        "scope_status": scope or ScopeStatus.BACKGROUND.value,
        "admitted_slot_ids": admitted_slots,
        "missing_required_slots": missing_slots,
        "missing_scope_axes": missing_scope_axes,
        "missing_requirements": _unique(missing_requirements),
        "supporting_source_span_ids": _supported_source_span_ids(admission),
        "direct_evidence_eligible": core_eligible,
        "core_eligible": core_eligible,
        "import_eligible": import_eligible,
        "component_bridge_eligible": bool(component_bridge and import_eligible),
        "evidence_lane": lane,
        "evidence_role": role,
        "reason": (
            "current V3 source admission directly supports contract evidence slots"
            if core_eligible
            else "current V3 source admission supports a component bridge"
            if component_bridge and import_eligible
            else "source-bound evidence is available but does not directly admit a required slot"
            if has_current_source_admission and import_eligible
            else "candidate is scoped for full-text acquisition; contract-bound source admission is pending"
            if import_eligible
            else "candidate is excluded or outside the research-question evidence boundary"
        ),
    }


def type_directed_missing_axes(
    record: Mapping[str, Any] | None,
    alignment: Mapping[str, Any] | None,
) -> list[str]:
    """Return diagnostic gaps without reintroducing causal-chain requirements."""

    assessment = alignment if isinstance(alignment, Mapping) else {}
    admission = assessment.get("type_directed_evidence")
    admission = admission if isinstance(admission, Mapping) else {}
    missing = [
        f"required_slot:{item}"
        for item in admission.get("missing_required_slots", [])
        if _text(item)
    ]
    missing.extend(
        f"scope_axis:{item}"
        for item in admission.get("missing_scope_axes", [])
        if _text(item)
    )
    if not admission.get("source_admission_present"):
        missing.append("source_admission_not_materialized")
    return _unique(missing)
