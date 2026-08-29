"""Deterministic scientific-scope and human-review gate for design preparation."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from typing import Any

from .discipline_catalog import (
    DESIGN_ONLY,
    get_discipline_entries,
    resolve_design_scope,
    resolve_execution_policy,
)


SCOPE_GATE_SCHEMA_VERSION = "experiment_design_scope_gate_v1"

_RISK_ORDER = {"low": 0, "medium": 1, "high": 2, "critical": 3}
_CONSTRAINT_SIGNALS = {
    "human_participants": "HUMAN_PARTICIPANT_REVIEW",
    "animal_subjects": "ANIMAL_USE_REVIEW",
    "pathogen": "PATHOGEN_OR_RESTRICTED_BIOLOGICAL_REVIEW",
    "restricted_biological_material": "PATHOGEN_OR_RESTRICTED_BIOLOGICAL_REVIEW",
    "genetic_modification": "GENETIC_MODIFICATION_REVIEW",
    "hazardous_materials": "HAZARDOUS_MATERIAL_REVIEW",
    "high_pressure": "HIGH_ENERGY_OR_PRESSURE_REVIEW",
    "high_temperature": "HIGH_ENERGY_OR_PRESSURE_REVIEW",
    "high_energy": "HIGH_ENERGY_OR_PRESSURE_REVIEW",
    "field_permit": "FIELD_OR_SITE_PERMISSION_REVIEW",
    "ecological_intervention": "FIELD_OR_SITE_PERMISSION_REVIEW",
    "sensitive_geospatial_data": "SENSITIVE_DATA_REVIEW",
    "privacy_sensitive_data": "SENSITIVE_DATA_REVIEW",
    "personal_data": "SENSITIVE_DATA_REVIEW",
}
_TEXT_SIGNALS = {
    "human participant": "HUMAN_PARTICIPANT_REVIEW",
    "patient": "HUMAN_PARTICIPANT_REVIEW",
    "clinical trial": "HUMAN_PARTICIPANT_REVIEW",
    "animal": "ANIMAL_USE_REVIEW",
    "pathogen": "PATHOGEN_OR_RESTRICTED_BIOLOGICAL_REVIEW",
    "biosafety": "PATHOGEN_OR_RESTRICTED_BIOLOGICAL_REVIEW",
    "genetic modification": "GENETIC_MODIFICATION_REVIEW",
    "gene editing": "GENETIC_MODIFICATION_REVIEW",
    "hazardous": "HAZARDOUS_MATERIAL_REVIEW",
    "high pressure": "HIGH_ENERGY_OR_PRESSURE_REVIEW",
    "high temperature": "HIGH_ENERGY_OR_PRESSURE_REVIEW",
    "high energy": "HIGH_ENERGY_OR_PRESSURE_REVIEW",
    "sensitive geospatial": "SENSITIVE_DATA_REVIEW",
    "personal data": "SENSITIVE_DATA_REVIEW",
}
_CLINICAL_DISCIPLINES = frozenset({"27", "29", "35", "36"})
_LIFE_VETERINARY_DISCIPLINES = frozenset({"13", "24", "28", "30", "34"})
_CHEMISTRY_SAFETY_DISCIPLINES = frozenset({"15", "16"})


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _text(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _truthy(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().casefold() not in {"", "0", "false", "no", "none", "not_applicable"}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return bool(value)
    return bool(value)


def _payload_text(*values: object) -> str:
    serialized: list[str] = []
    for value in values:
        try:
            serialized.append(json.dumps(value, ensure_ascii=False, sort_keys=True))
        except (TypeError, ValueError):
            serialized.append(str(value))
    return " ".join(serialized).casefold()


def _maximum_risk(levels: Sequence[str]) -> str:
    return max(levels or ["low"], key=lambda level: _RISK_ORDER.get(level, -1))


def _review_requirements(
    discipline_ids: Sequence[str],
    research_brief: Mapping[str, Any],
    user_constraints: Mapping[str, Any],
) -> dict[str, Any]:
    triggers: set[str] = set()
    constraints = _mapping(user_constraints)
    for key, trigger in _CONSTRAINT_SIGNALS.items():
        if _truthy(constraints.get(key)):
            triggers.add(trigger)
    source_text = _payload_text(research_brief.get("research_object"), research_brief, constraints)
    for phrase, trigger in _TEXT_SIGNALS.items():
        if phrase in source_text:
            triggers.add(trigger)
    if set(discipline_ids) & _CLINICAL_DISCIPLINES:
        triggers.update({"CLINICAL_OR_HEALTH_EXPERT_REVIEW", "ETHICS_AND_DATA_APPROVAL"})
    if set(discipline_ids) & _LIFE_VETERINARY_DISCIPLINES:
        triggers.add("LIFE_SCIENCE_OR_VETERINARY_REVIEW")
    if "34" in discipline_ids:
        triggers.add("ANIMAL_USE_REVIEW")
    if set(discipline_ids) & _CHEMISTRY_SAFETY_DISCIPLINES:
        triggers.add("CHEMISTRY_OR_CHEMICAL_ENGINEERING_SAFETY_REVIEW")
    required = bool(triggers)
    approval_dependencies: list[str] = []
    if "HUMAN_PARTICIPANT_REVIEW" in triggers or "CLINICAL_OR_HEALTH_EXPERT_REVIEW" in triggers:
        approval_dependencies.extend(["domain_expert_confirmation", "ethics_or_data_governance_confirmation"])
    if "ANIMAL_USE_REVIEW" in triggers:
        approval_dependencies.append("animal_use_or_veterinary_oversight_confirmation")
    if "LIFE_SCIENCE_OR_VETERINARY_REVIEW" in triggers:
        approval_dependencies.extend(["life_science_methodology_confirmation", "biosafety_and_facility_confirmation"])
    if "PATHOGEN_OR_RESTRICTED_BIOLOGICAL_REVIEW" in triggers or "GENETIC_MODIFICATION_REVIEW" in triggers:
        approval_dependencies.append("biosafety_and_facility_confirmation")
    if "HAZARDOUS_MATERIAL_REVIEW" in triggers or "HIGH_ENERGY_OR_PRESSURE_REVIEW" in triggers:
        approval_dependencies.append("laboratory_safety_and_equipment_confirmation")
    if "CHEMISTRY_OR_CHEMICAL_ENGINEERING_SAFETY_REVIEW" in triggers:
        approval_dependencies.append("chemical_safety_and_facility_confirmation")
    if "FIELD_OR_SITE_PERMISSION_REVIEW" in triggers:
        approval_dependencies.append("site_or_field_permission_confirmation")
    if "SENSITIVE_DATA_REVIEW" in triggers:
        approval_dependencies.append("data_stewardship_confirmation")
    return {
        "risk_level": (
            "critical"
            if set(discipline_ids) & _CLINICAL_DISCIPLINES
            else "high"
            if set(discipline_ids) & _LIFE_VETERINARY_DISCIPLINES
            else "medium"
        ),
        "human_review_required": required,
        "review_triggers": sorted(triggers),
        "approval_dependencies": list(dict.fromkeys(approval_dependencies)),
        "execution_prohibited": True,
        "restricted_content": [
            "No dangerous operational parameters, clinical recruitment instructions, animal SOPs, or restricted biological protocols are emitted.",
        ]
        if required
        else [],
    }


class ScopeAndSafetyGate:
    """Apply scope, execution, risk, and human-review policies before planning."""

    def evaluate(
        self,
        research_brief: Mapping[str, Any],
        *,
        user_constraints: Mapping[str, Any] | None = None,
        allow_digital_execution: bool = False,
    ) -> dict[str, Any]:
        brief = _mapping(research_brief)
        constraints = _mapping(user_constraints)
        scope = resolve_design_scope(brief.get("discipline_ids"))
        discipline_ids = list(scope["discipline_ids"])
        baseline_risk = _maximum_risk([entry.baseline_risk for entry in get_discipline_entries(discipline_ids)])
        review = _review_requirements(discipline_ids, brief, constraints)
        review["risk_level"] = _maximum_risk([baseline_risk, review["risk_level"]])
        eligibility = resolve_execution_policy(
            discipline_ids,
            allow_digital_execution=allow_digital_execution,
        )
        if scope["status"] == "IN_SCOPE":
            decision = "PROCEED_DESIGN_ONLY"
        elif scope["status"] == "BLOCKED_BY_SCOPE":
            decision = "OUT_OF_SCOPE"
        else:
            decision = "REQUIRES_SCOPE_CLARIFICATION"
        return {
            "schema_version": SCOPE_GATE_SCHEMA_VERSION,
            "status": scope["status"],
            "decision": decision,
            "reason": scope["reason"],
            "catalog": {
                "schema_version": scope["catalog_schema_version"],
                "source": scope["catalog_source"],
                "discipline_ids": discipline_ids,
                "allowed_discipline_ids": scope["allowed_discipline_ids"],
                "excluded_discipline_ids": scope["excluded_discipline_ids"],
                "unresolved_disciplines": scope["unresolved_disciplines"],
            },
            "execution": {
                "mode": DESIGN_ONLY,
                "execution_prohibited": True,
                "allow_digital_execution": bool(allow_digital_execution),
                "future_digital_execution_eligibility": eligibility["mode"],
                "reason": "ExperimentDesign preparation is design-only and never invokes an executor.",
            },
            "risk_and_human_review": review,
        }
