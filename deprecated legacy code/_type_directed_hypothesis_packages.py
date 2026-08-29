"""V2/V3 hypothesis-package construction without a universal causal path.

Every qualified research gap is packaged against the active research-question
contract that produced it.  The package is ready only when that contract's
declared evidence slots have V3 source-bound lineage.  Consequently, a
measurement, boundary, theory, data, or implementation question is never
asked to supply an invented input--mediator--outcome--comparison chain.
"""

from __future__ import annotations

from hashlib import sha1
from typing import Any, Mapping

try:
    from ._gap_types import is_primary_research_candidate, package_kind_for
    from ._research_question_contract import (
        RESEARCH_QUESTION_CONTRACT_VERSION,
        validate_research_question_contract,
    )
    from ._type_directed_evidence import evidence_profile_for_contract
except ImportError:
    from _gap_types import is_primary_research_candidate, package_kind_for
    from _research_question_contract import (
        RESEARCH_QUESTION_CONTRACT_VERSION,
        validate_research_question_contract,
    )
    from _type_directed_evidence import evidence_profile_for_contract


TYPE_DIRECTED_HYPOTHESIS_PACKAGE_VERSION = "hypothesis_package_v2_type_directed"


def _text(value: Any) -> str:
    return " ".join(str(value or "").split())


def _items(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _candidate_contract(candidate: Mapping[str, Any]) -> dict[str, Any]:
    """Accept only an explicitly attached current RQ contract.

    Project-level SH lookup is intentionally not used as a compatibility
    fallback: a candidate without its own contract lineage cannot enter a
    V2/V3 primary package.
    """

    contract = candidate.get("research_question_contract")
    if not isinstance(contract, Mapping):
        return {}
    if _text(contract.get("schema_version")) != RESEARCH_QUESTION_CONTRACT_VERSION:
        return {}
    try:
        return validate_research_question_contract(dict(contract))
    except ValueError:
        return {}


def is_v2_v3_project(project: Mapping[str, Any] | None) -> bool:
    """Whether a project must use V2/V3 package construction.

    The presence of a current V2 SH declaration is authoritative.  A project
    in that state is never handed to the historic causal-package builder.
    """

    source = project if isinstance(project, Mapping) else {}
    for sub_hypothesis in _items(source.get("sub_hypotheses")):
        if not isinstance(sub_hypothesis, Mapping):
            continue
        contract = sub_hypothesis.get("research_question_contract")
        if (
            isinstance(contract, Mapping)
            and _text(contract.get("schema_version"))
            == RESEARCH_QUESTION_CONTRACT_VERSION
        ):
            return True
    for candidate in _items(source.get("knowledge_gaps")):
        if isinstance(candidate, Mapping) and _text(candidate.get("schema_version")) == "gap_candidate_v2":
            return True
    return False


def _bundle_from_mapping(value: Any, contract_id: str) -> dict[str, Any]:
    bundle = value if isinstance(value, Mapping) else {}
    if _text(bundle.get("research_question_contract_id")) != contract_id:
        return {}
    if _text(bundle.get("schema_version")) != "type_directed_evidence_bundle_v3":
        return {}
    return dict(bundle)


def _candidate_bundle(
    project: Mapping[str, Any], candidate: Mapping[str, Any], contract: Mapping[str, Any],
) -> dict[str, Any]:
    """Locate only V3 contract-slot evidence associated with this candidate."""

    contract_id = _text(contract.get("contract_id"))
    direct = _bundle_from_mapping(candidate.get("type_directed_evidence_bundle"), contract_id)
    if direct:
        return direct
    sub_id = _text(candidate.get("sub_hypothesis_id") or contract.get("sub_hypothesis_id"))
    for sub_hypothesis in _items(project.get("sub_hypotheses")):
        if not isinstance(sub_hypothesis, Mapping) or _text(sub_hypothesis.get("id")) != sub_id:
            continue
        retrieval = sub_hypothesis.get("retrieval") if isinstance(sub_hypothesis.get("retrieval"), Mapping) else {}
        for value in (
            retrieval.get("type_directed_evidence_bundle"),
            (retrieval.get("cumulative_full_text_coverage") or {}).get("type_directed_evidence_bundle")
            if isinstance(retrieval.get("cumulative_full_text_coverage"), Mapping)
            else {},
        ):
            bundle = _bundle_from_mapping(value, contract_id)
            if bundle:
                return bundle
    return {}


def _primary_candidates(
    candidates: list[dict[str, Any]],
) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    output: list[tuple[dict[str, Any], dict[str, Any]]] = []
    seen: set[str] = set()
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        identity = _text(candidate.get("gap_id") or candidate.get("id"))
        if not identity or identity in seen:
            continue
        seen.add(identity)
        if _text(candidate.get("schema_version")) != "gap_candidate_v2":
            continue
        try:
            qualified = is_primary_research_candidate(candidate)
        except ValueError:
            qualified = False
        contract = _candidate_contract(candidate)
        if qualified and contract:
            output.append((candidate, contract))
    output.sort(
        key=lambda item: (
            -float(item[0].get("exploration_value_score") or 0.0),
            _text(item[0].get("gap_id") or item[0].get("id")),
        )
    )
    return output


def _coverage_audit(
    candidate: Mapping[str, Any], contract: Mapping[str, Any], bundle: Mapping[str, Any],
) -> dict[str, Any]:
    profile = evidence_profile_for_contract(contract)
    required_slots = list(profile.get("required_slots") or [])
    supported_slots = [
        _text(item) for item in bundle.get("supported_slot_ids", [])
        if _text(item) in required_slots
    ] if bundle else []
    missing_slots = [slot for slot in required_slots if slot not in supported_slots]
    candidate_gate = candidate.get("primary_source_span_gate")
    candidate_qualified = isinstance(candidate_gate, Mapping) and candidate_gate.get("status") == "PASSED"
    missing_required = [f"required_slot:{slot}" for slot in missing_slots]
    if not candidate_qualified:
        missing_required.append("candidate_primary_source_span_gate")
    return {
        "schema_version": "type_directed_package_coverage_v2",
        "research_question_contract_id": _text(contract.get("contract_id")),
        "gap_types": list(profile.get("gap_types") or []),
        "required_contract_slots": required_slots,
        "supported_contract_slots": supported_slots,
        "missing_contract_slots": missing_slots,
        "candidate_primary_source_span_gate_passed": candidate_qualified,
        "missing_required": missing_required,
        "type_directed_evidence_bundle_status": _text(bundle.get("status")) or "NO_SOURCE_BOUND_CONTRACT_EVIDENCE",
        "type_directed_evidence_bundle": dict(bundle),
        "research_question_evidence_ready": bool(
            bundle.get("research_question_ready") is True
            or bundle.get("core_contract_evidence_ready") is True
        ),
        "dimensions": {
            "research_question": {
                "status": "COVERED",
                "values": [_text((contract.get("research_question") or {}).get("question_text"))],
            },
            "contract_slot_evidence": {
                "status": "COVERED" if not missing_slots else "MISSING",
                "values": supported_slots,
            },
            "source_lineage": {
                "status": "COVERED" if bool(bundle.get("slot_source_lineage")) and not missing_slots else "MISSING",
                "values": [],
            },
        },
    }


def _package_for_candidate(
    project: Mapping[str, Any], candidate: Mapping[str, Any], contract: Mapping[str, Any],
) -> dict[str, Any]:
    bundle = _candidate_bundle(project, candidate, contract)
    coverage = _coverage_audit(candidate, contract, bundle)
    try:
        package_kind = package_kind_for(dict(candidate)).value
    except ValueError:
        package_kind = "TYPE_DIRECTED_RESEARCH_PACKAGE"
    gap_id = _text(candidate.get("gap_id") or candidate.get("id"))
    lineage = (
        bundle.get("slot_source_lineage")
        if isinstance(bundle.get("slot_source_lineage"), Mapping)
        else {}
    )
    missing_lineage = [
        slot for slot in coverage["required_contract_slots"]
        if not isinstance(lineage.get(slot), list) or not lineage.get(slot)
    ]
    ready = bool(
        not coverage["missing_required"]
        and not missing_lineage
        and coverage["research_question_evidence_ready"]
    )
    question = contract.get("research_question") if isinstance(contract.get("research_question"), Mapping) else {}
    scientific_scope = contract.get("scientific_scope") if isinstance(contract.get("scientific_scope"), Mapping) else {}
    seed = "|".join((_text(project.get("project_id")), _text(contract.get("contract_id")), gap_id))
    return {
        "schema_version": TYPE_DIRECTED_HYPOTHESIS_PACKAGE_VERSION,
        "hypothesis_package_id": "hpv2_" + sha1(seed.encode("utf-8")).hexdigest()[:16],
        "project_id": _text(project.get("project_id")),
        "package_type": package_kind,
        "hypothesis_package_type": package_kind,
        "status": "READY_FOR_MINGLI" if ready else "TYPE_DIRECTED_COVERAGE_INCOMPLETE",
        "v2_v3_admission_authority": "research_question_contract_v2+gap_source_admission_v3",
        "primary_gap_ids": [gap_id],
        "primary_gap_id": gap_id,
        "primary_research_gap_count": 1,
        "research_question_contract": dict(contract),
        "research_question_contract_id": _text(contract.get("contract_id")),
        "gap_type": _text(candidate.get("gap_type")),
        "slots": {
            "research_question": _text(question.get("question_text")),
            "scientific_scope": dict(scientific_scope),
            "required_evidence_slots": list(coverage["required_contract_slots"]),
            "supported_evidence_slots": list(coverage["supported_contract_slots"]),
        },
        "slot_source_lineage": dict(lineage),
        "hypothesis_source_lineage": {
            "schema_version": "type_directed_source_lineage_v2",
            "status": "SOURCE_TEXT_LINEAGE_COMPLETE" if not missing_lineage else "SOURCE_TEXT_LINEAGE_INCOMPLETE",
            "required_slots": list(coverage["required_contract_slots"]),
            "missing_slots": missing_lineage,
            "slots": dict(lineage),
            "source_gap_ids": [gap_id],
        },
        "missing_source_lineage_slots": missing_lineage,
        "coverage_audit": coverage,
        "compatibility_audit": {
            "schema_version": "type_directed_contract_compatibility_v2",
            "compatible": True,
            "edges": [],
            "reason": "A V2 package represents one declared research question; no synthetic causal-path edge is required.",
        },
        "conclusion_scope": {
            "allowed": (
                ["descriptive_scope_bound_claim", "type_directed_research_hypothesis"]
                if ready else ["descriptive_scope_bound_claim"]
            ),
            "forbidden": (
                [] if ready else ["evidence_complete_or_mechanism_complete_claim"]
            ),
        },
        "blocked_reasons": (
            [] if ready else [
                "Missing V3 source-bound support for declared contract slots: "
                + ", ".join(coverage["missing_contract_slots"])
                if coverage["missing_contract_slots"] else "Candidate or source-lineage qualification is incomplete."
            ]
        ),
    }


def build_type_directed_hypothesis_packages(
    project: Mapping[str, Any],
    candidate_gaps: list[dict[str, Any]],
    *,
    all_gaps: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Build current packages from only qualified V2 candidates."""

    source = project if isinstance(project, Mapping) else {}
    supplied = [item for item in candidate_gaps if isinstance(item, dict)]
    if all_gaps is not None:
        supplied.extend(item for item in all_gaps if isinstance(item, dict))
    packages = [
        _package_for_candidate(source, candidate, contract)
        for candidate, contract in _primary_candidates(supplied)
    ]
    return packages


def build_blocked_type_directed_package(project: Mapping[str, Any]) -> dict[str, Any]:
    """Report the absence of a V2-qualified primary research candidate."""

    return {
        "schema_version": TYPE_DIRECTED_HYPOTHESIS_PACKAGE_VERSION,
        "hypothesis_package_id": "",
        "project_id": _text(project.get("project_id")),
        "package_type": "TYPE_DIRECTED_RESEARCH_PACKAGE",
        "status": "TYPE_DIRECTED_COVERAGE_INCOMPLETE",
        "v2_v3_admission_authority": "research_question_contract_v2+gap_source_admission_v3",
        "primary_gap_ids": [],
        "primary_research_gap_count": 0,
        "coverage_audit": {
            "schema_version": "type_directed_package_coverage_v2",
            "missing_required": ["qualified_primary_research_gap"],
            "missing_contract_slots": [],
            "dimensions": {},
        },
        "compatibility_audit": {
            "schema_version": "type_directed_contract_compatibility_v2",
            "compatible": False,
            "edges": [],
        },
        "slot_source_lineage": {},
        "hypothesis_source_lineage": {
            "schema_version": "type_directed_source_lineage_v2",
            "status": "SOURCE_TEXT_LINEAGE_INCOMPLETE",
            "required_slots": [],
            "missing_slots": [],
            "slots": {},
        },
        "missing_source_lineage_slots": [],
        "conclusion_scope": {
            "allowed": ["descriptive_scope_bound_claim"],
            "forbidden": ["evidence_complete_or_mechanism_complete_claim"],
        },
        "blocked_reasons": [
            "No V2-qualified primary research gap with current contract lineage is available."
        ],
    }


def build_type_directed_research_coverage_map(
    project: Mapping[str, Any], gaps: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Report coverage in declared V2 evidence slots, not causal dimensions."""

    source = project if isinstance(project, Mapping) else {}
    candidates = [
        item for item in (gaps if gaps is not None else _items(source.get("knowledge_gaps")))
        if isinstance(item, dict)
    ]
    entries: list[dict[str, Any]] = []
    missing_required: list[str] = []
    for candidate, contract in _primary_candidates(candidates):
        bundle = _candidate_bundle(source, candidate, contract)
        coverage = _coverage_audit(candidate, contract, bundle)
        entries.append({
            "gap_id": _text(candidate.get("gap_id") or candidate.get("id")),
            "research_question_contract_id": _text(contract.get("contract_id")),
            "gap_types": list(coverage.get("gap_types") or []),
            "required_contract_slots": list(coverage.get("required_contract_slots") or []),
            "supported_contract_slots": list(coverage.get("supported_contract_slots") or []),
            "missing_contract_slots": list(coverage.get("missing_contract_slots") or []),
            "source_lineage": dict(bundle.get("slot_source_lineage") or {}),
        })
        for requirement in coverage.get("missing_required") or []:
            qualified = (
                f"{_text(contract.get('contract_id'))}:{_text(requirement)}"
            )
            if qualified and qualified not in missing_required:
                missing_required.append(qualified)
    return {
        "schema_version": "research_coverage_map_v2_type_directed",
        "scope": "research_question_contracts",
        "contract_coverage": entries,
        "missing_required": missing_required,
        "primary_research_gap_ids": [item["gap_id"] for item in entries],
        "dimensions": {
            "research_question_contract": {
                "status": "COVERED" if entries else "MISSING",
                "values": [item["research_question_contract_id"] for item in entries],
            },
            "declared_contract_slots": {
                "status": "COVERED" if entries and not missing_required else "MISSING",
                "values": [
                    slot
                    for item in entries
                    for slot in item["supported_contract_slots"]
                ],
            },
        },
    }


def type_directed_coverage_gate(package: Mapping[str, Any]) -> dict[str, Any]:
    """Evaluate a V2/V3 package solely by its declared contract slots."""

    source = package if isinstance(package, Mapping) else {}
    coverage = source.get("coverage_audit") if isinstance(source.get("coverage_audit"), Mapping) else {}
    missing = [_text(item) for item in coverage.get("missing_required", []) if _text(item)]
    missing_lineage = [
        _text(item) for item in source.get("missing_source_lineage_slots", []) if _text(item)
    ]
    primary_ids = [_text(item) for item in source.get("primary_gap_ids", []) if _text(item)]
    compatible = bool(
        (source.get("compatibility_audit") or {}).get("compatible") is not False
    )
    ready = bool(primary_ids and not missing and not missing_lineage and compatible)
    reasons: list[str] = []
    if not primary_ids:
        reasons.append("No qualified primary research gap is available.")
    if missing:
        reasons.append("Missing declared contract coverage: " + ", ".join(missing))
    if missing_lineage:
        reasons.append("Missing V3 source lineage for contract slots: " + ", ".join(missing_lineage))
    if not compatible:
        reasons.append("The type-directed package is not contract-compatible.")
    return {
        "schema_version": "type_directed_coverage_gate_v2",
        "hypothesis_package_id": _text(source.get("hypothesis_package_id")),
        "package_type": _text(source.get("package_type")),
        "status": "READY_FOR_MINGLI" if ready else "TYPE_DIRECTED_COVERAGE_INCOMPLETE",
        "ready": ready,
        "missing_required_coverage": missing,
        "missing_source_lineage_slots": missing_lineage,
        "source_text_lineage_status": (
            "SOURCE_TEXT_LINEAGE_COMPLETE" if not missing_lineage else "SOURCE_TEXT_LINEAGE_INCOMPLETE"
        ),
        "incompatible_edges": [],
        "primary_gap_ids": primary_ids,
        "allowed_conclusion_strength": list(
            (source.get("conclusion_scope") or {}).get("allowed") or []
        ),
        "forbidden_conclusions": list(
            (source.get("conclusion_scope") or {}).get("forbidden") or []
        ),
        "reasons": reasons,
    }
