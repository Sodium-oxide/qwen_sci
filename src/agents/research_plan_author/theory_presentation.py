"""Deterministic public presentation for compiled mathematics-theory units."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .theory_spine import replace_theory_spine_internal_ids, theory_spine_internal_ids_in_text


_STATUS_LABELS = {
    "proposed": "Candidate",
    "candidate": "Candidate",
    "unverified": "Unverified",
    "expected_not_observed": "Expected---Not Observed",
    "no_information": "No-information",
    "needs_human_input": "Review-required",
    "review_required": "Review-required",
}


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _text(value: object) -> str:
    return str(value or "").strip()


def theory_spine_for_document(document: Mapping[str, Any]) -> dict[str, Any]:
    """Resolve the private spine registry retained with a composed document."""

    direct = _mapping(document.get("theory_spine"))
    if direct:
        return direct
    return _mapping(_mapping(document.get("authoring_blueprint")).get("theory_spine"))


def visible_theory_text(document: Mapping[str, Any], value: object) -> str:
    """Use public display labels if a private theory ID reaches a renderer."""

    visible = replace_theory_spine_internal_ids(value, theory_spine_for_document(document))
    for private_identifier in theory_spine_internal_ids_in_text(visible):
        visible = visible.replace(private_identifier, "an internal theory reference")
    return visible


def theory_unit_registry(document: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """Index compiled units by private ID for deterministic public labels."""

    spine = theory_spine_for_document(document)
    registry: dict[str, dict[str, Any]] = {}
    for collection, identifier_field, unit_kind in (
        ("lemma_units", "lemma_id", "lemma"),
        ("proof_obligations", "proof_obligation_id", "proof_obligation"),
        ("falsifiers", "falsifier_id", "falsifier"),
        ("decision_branches", "branch_id", "decision_branch"),
    ):
        for raw_record in spine.get(collection) or []:
            record = _mapping(raw_record)
            identifier = _text(record.get(identifier_field))
            if identifier:
                registry[identifier] = {"unit_kind": unit_kind, **record}
    return registry


def _status_label(
    block: Mapping[str, Any],
    claims: Mapping[str, Mapping[str, Any]],
    units: list[Mapping[str, Any]],
) -> str:
    if any(_text(unit.get("branch_kind")) in {"no_information", "compiler_no_information"} for unit in units):
        return "No-information"
    statuses = {_text(unit.get("status")) for unit in units if _text(unit.get("status"))}
    for status in ("no_information", "expected_not_observed", "candidate", "unverified"):
        if status in statuses:
            return _STATUS_LABELS[status]
    qualifications = {
        _text(_mapping(claims.get(_text(claim_id))).get("qualification"))
        for claim_id in block.get("claim_ids") or []
        if _text(claim_id)
    }
    for qualification in (
        "expected_not_observed",
        "needs_human_input",
        "review_required",
        "proposed",
        "unverified",
    ):
        if qualification in qualifications:
            return _STATUS_LABELS[qualification]
    return ""


def theory_block_presentation(
    block: Mapping[str, Any],
    *,
    claims: Mapping[str, Mapping[str, Any]],
    registry: Mapping[str, Mapping[str, Any]],
) -> tuple[str, str]:
    """Return the public prefix and status label for one structured block."""

    units = [
        _mapping(registry.get(_text(unit_id)))
        for unit_id in block.get("theory_unit_ids") or []
        if _mapping(registry.get(_text(unit_id)))
    ]
    status = _status_label(block, claims, units)
    unit_kinds = {_text(unit.get("unit_kind")) for unit in units}
    labels = [_text(unit.get("display_label")) for unit in units if _text(unit.get("display_label"))]
    label_text = ", ".join(dict.fromkeys(labels))
    kind = _text(block.get("kind"))
    if kind == "lemma":
        noun = "Lemma" if len(labels) == 1 else "Lemma Registry"
        return f"{noun}{(' ' + label_text) if label_text else ''}{(' (' + status + ')') if status else ''}.", status
    if "proof_obligation" in unit_kinds:
        noun = "Proof Obligation" if len(labels) == 1 else "Proof Obligation Registry"
        return f"{noun}{(' ' + label_text) if label_text else ''}{(' (' + (status or 'Unverified') + ')')}.", status or "Unverified"
    if kind == "outcome_branch" or "decision_branch" in unit_kinds:
        branch_status = status or "Expected---Not Observed"
        if branch_status == "No-information":
            return "Decision Status: No-information.", branch_status
        return f"Pre-registered Branch ({branch_status}).", branch_status
    if kind == "proposition":
        return f"Proposition ({status or 'Candidate'}).", status or "Candidate"
    return "", status


__all__ = [
    "theory_block_presentation",
    "theory_spine_for_document",
    "theory_unit_registry",
    "visible_theory_text",
]
