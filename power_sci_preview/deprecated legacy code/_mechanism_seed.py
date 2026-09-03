"""Build a source-bound mechanism seed from V2/V3 evidence only.

Mechanism seeding is meaningful only for a research-question contract that
explicitly declares a causal or competing-mechanism knowledge need.  This
module deliberately consumes the V2 ``causal_model`` declaration and V3
``gap_source_admission_v3`` records.  It does not reconstruct a mechanism
from historical causal chains, SH prose, or a generic fragment classifier.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping


_V3_ADMISSION_SCHEMA = "gap_source_admission_v3"


def _text(value: Any) -> str:
    return " ".join(str(value or "").split())


def _text_list(value: Any) -> list[str]:
    values = value if isinstance(value, (list, tuple, set)) else [value]
    output: list[str] = []
    for item in values:
        normalized = _text(item)
        if normalized and normalized not in output:
            output.append(normalized)
    return output


def _record_branch(record: Mapping[str, Any]) -> str:
    assessment = (
        record.get("alignment_assessment")
        if isinstance(record.get("alignment_assessment"), Mapping)
        else {}
    )
    return _text(
        record.get("sub_hypothesis_id")
        or record.get("retrieval_branch")
        or assessment.get("sub_hypothesis_id")
    ).split(":", 1)[0]


def _declared_roles(contract: Mapping[str, Any]) -> dict[str, str]:
    """Read role values exclusively from the V2 causal-model declaration."""

    model = (
        contract.get("causal_model")
        if isinstance(contract.get("causal_model"), Mapping)
        else {}
    )
    exposure = _text(model.get("exposure"))
    mediators = _text_list(model.get("mediators"))
    alternatives = _text_list(model.get("alternative_explanations"))
    outcome = _text(model.get("outcome"))
    # Mechanism-competition contracts can name competing candidates instead
    # of a causal mediator.  This remains an authored V2 declaration, not an
    # inferred chain bridge.
    mediator = mediators[0] if mediators else alternatives[0] if alternatives else ""
    return {"input": exposure, "mediator": mediator, "outcome": outcome}


def _source_admission(
    record: Mapping[str, Any], contract_id: str,
) -> dict[str, Any]:
    admissions = record.get("gap_source_admissions_v4")
    if not isinstance(admissions, Mapping) or not contract_id:
        return {}
    admission = admissions.get(contract_id)
    if not isinstance(admission, Mapping):
        return {}
    if _text(admission.get("schema_version")) != "gap_source_admission_v4":
        return {}
    if (
        admission.get("direct_evidence_eligible") is not True
        or admission.get("eligible_for_gap_synthesis") is not True
        or admission.get("counts_toward_gate") is not True
        or _text(admission.get("admission_level")).upper() != "DIRECT_EVIDENCE"
    ):
        return {}
    return dict(admission)


def _support_refs(supports: Iterable[Mapping[str, Any]]) -> list[str]:
    refs: list[str] = []
    for support in supports:
        for field in ("source_span_ids", "source_unit_ids"):
            for value in _text_list(support.get(field)):
                if value not in refs:
                    refs.append(value)
        for field in ("assertion_id", "source_span_id", "source_unit_id"):
            value = _text(support.get(field))
            if value and value not in refs:
                refs.append(value)
    return refs


def _required_role_slots(contract: Mapping[str, Any]) -> dict[str, tuple[str, ...]]:
    # These are the actual V2 CAUSAL_IDENTIFICATION contract slot names, not
    # an ontology-level shorthand such as ``causal_relation``.  A mediation
    # seed is available only if the author made ``mediator`` an explicit
    # evidence slot in addition to the base causal-identification contract.
    return {
        "input": ("exposure",),
        "mediator": ("mediator",),
        "outcome": ("outcome",),
    }


def _empty_seed(
    *,
    contract: Mapping[str, Any],
    gap: Mapping[str, Any],
    reason: str,
    status: str = "INCOMPLETE_MECHANISM_SEED",
) -> dict[str, Any]:
    return {
        "version": "mechanism_seed_v3",
        "research_question_contract_id": _text(contract.get("contract_id")),
        "sub_hypothesis_id": _text(
            gap.get("sub_hypothesis_id") or contract.get("sub_hypothesis_id")
        ).split(":", 1)[0],
        "mechanism_seed": {
            "input": {"value": "", "fragment_refs": [], "source_slot_ids": []},
            "mediator": {"value": "", "fragment_refs": [], "source_slot_ids": []},
            "outcome": {"value": "", "fragment_refs": [], "source_slot_ids": []},
        },
        "seed_context_contract": {
            "same_sub_hypothesis": False,
            "compatible_object": False,
            "compatible_system": False,
            "compatible_regime": False,
            "admission_authority": _V3_ADMISSION_SCHEMA,
        },
        "status": status,
        "missing_roles": ["input", "mediator", "outcome"],
        "supporting_fragment_refs": [],
        "research_design_evidence": {
            "status": "UNSUPPORTED",
            "fragment_alignments": [],
            "supporting_fragment_refs": [],
            "reason": reason,
        },
        "original_source_role_mutated": False,
        "reason": reason,
    }


def build_mechanism_seed(
    project: dict[str, Any],
    gap: dict[str, Any],
    contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compose a mechanism seed from declared V2 roles and V3 slot evidence.

    A gap can be considered a mechanism seed only when every declared role is
    source-bound through the active contract.  The function intentionally
    returns an explicit incomplete state instead of consulting legacy causal
    fields when the declaration or V3 evidence is absent.
    """

    try:
        from ._type_directed_evidence import is_mechanism_contract
    except ImportError:
        from _type_directed_evidence import is_mechanism_contract

    source_project = project if isinstance(project, Mapping) else {}
    source_gap = gap if isinstance(gap, Mapping) else {}
    branch = _text(source_gap.get("sub_hypothesis_id")).split(":", 1)[0]
    contracts = (
        source_project.get("subhypothesis_alignment_contracts")
        if isinstance(source_project.get("subhypothesis_alignment_contracts"), Mapping)
        else {}
    )
    active_contract = dict(
        contract
        or (
            contracts.get(branch)
            if isinstance(contracts.get(branch), Mapping)
            else {}
        )
        or {}
    )
    if not active_contract or not branch:
        return _empty_seed(
            contract=active_contract,
            gap=source_gap,
            reason="A V2 research-question contract and sub-hypothesis identifier are required.",
        )
    if not is_mechanism_contract(active_contract):
        return _empty_seed(
            contract=active_contract,
            gap=source_gap,
            status="NOT_APPLICABLE_FOR_NON_MECHANISM_GAP",
            reason="Mechanism seeds are defined only for explicitly causal or competing-mechanism V2 contracts.",
        )
    question = (
        active_contract.get("research_question")
        if isinstance(active_contract.get("research_question"), Mapping)
        else {}
    )
    if _text(question.get("question_kind")) != "CAUSAL_IDENTIFICATION":
        return _empty_seed(
            contract=active_contract,
            gap=source_gap,
            status="NOT_APPLICABLE_FOR_NON_MEDIATION_CONTRACT",
            reason="Mechanism-competition questions use their own V2 discriminating-test slots and are not recast as a mediation seed.",
        )
    contract_id = _text(active_contract.get("contract_id"))
    declared = _declared_roles(active_contract)
    undeclared_roles = [role for role, value in declared.items() if not value]
    if not contract_id or undeclared_roles:
        result = _empty_seed(
            contract=active_contract,
            gap=source_gap,
            status="REQUIRES_DECLARED_V2_CAUSAL_MODEL",
            reason="The active V2 causal model must explicitly declare exposure, mechanism candidate, and outcome; no legacy chain is reconstructed.",
        )
        result["missing_roles"] = undeclared_roles
        return result

    role_slots = _required_role_slots(active_contract)
    supports_by_slot: dict[str, list[dict[str, Any]]] = {}
    source_ids: set[str] = set()
    for collection_name in ("papergraph", "evidence"):
        for record in source_project.get(collection_name) or []:
            if not isinstance(record, Mapping) or _record_branch(record) != branch:
                continue
            admission = _source_admission(record, contract_id)
            if not admission:
                continue
            source_id = _text(record.get("paper_id") or record.get("doi") or record.get("url"))
            if source_id:
                source_ids.add(source_id)
            admitted_supports = admission.get("admitted_slot_supports")
            if not isinstance(admitted_supports, Mapping):
                continue
            for slot, values in admitted_supports.items():
                slot_id = _text(slot)
                if not slot_id or not isinstance(values, list):
                    continue
                bucket = supports_by_slot.setdefault(slot_id, [])
                bucket.extend(item for item in values if isinstance(item, Mapping))

    selected: dict[str, dict[str, Any]] = {}
    supporting_refs: list[str] = []
    missing_roles: list[str] = []
    for role, value in declared.items():
        supporting_slots = [
            slot for slot in role_slots[role]
            if supports_by_slot.get(slot)
        ]
        refs = _support_refs(
            support
            for slot in supporting_slots
            for support in supports_by_slot[slot]
        )
        selected[role] = {
            "value": value,
            "fragment_refs": refs,
            "source_slot_ids": supporting_slots,
        }
        if not refs:
            missing_roles.append(role)
        for ref in refs:
            if ref not in supporting_refs:
                supporting_refs.append(ref)

    design_supports = supports_by_slot.get("identification_strategy", [])
    design_refs = _support_refs(design_supports)
    design_required = _text(
        (active_contract.get("research_question") or {}).get("question_kind")
    ) == "CAUSAL_IDENTIFICATION"
    if design_required and not design_refs:
        missing_roles.append("identification_design")
    context_passes = bool(source_ids and supporting_refs)
    complete = bool(not missing_roles and context_passes)
    return {
        "version": "mechanism_seed_v3",
        "research_question_contract_id": contract_id,
        "sub_hypothesis_id": branch,
        "mechanism_seed": selected,
        "seed_context_contract": {
            "same_sub_hypothesis": context_passes,
            "compatible_object": context_passes,
            "compatible_system": context_passes,
            "compatible_regime": context_passes,
            "source_ids": sorted(source_ids),
            "admission_authority": _V3_ADMISSION_SCHEMA,
        },
        "status": "COMPLETE_COMPOSITE_MECHANISM_SEED" if complete else "INCOMPLETE_MECHANISM_SEED",
        "missing_roles": missing_roles,
        "supporting_fragment_refs": supporting_refs,
        "research_design_evidence": {
            "status": "SOURCE_BOUND" if design_refs else "UNSUPPORTED",
            "fragment_alignments": [],
            "supporting_fragment_refs": design_refs,
            "source_slot_ids": ["identification_strategy"] if design_refs else [],
            "reason": (
                "A V3 source admission supports the declared identification-strategy slot."
                if design_refs else "No V3 source admission supports the declared identification-strategy slot."
            ),
        },
        "original_source_role_mutated": False,
        "reason": (
            "All declared V2 mechanism roles have V3 source-bound slot support."
            if complete else "One or more declared V2 mechanism roles lack V3 source-bound slot support."
        ),
    }
