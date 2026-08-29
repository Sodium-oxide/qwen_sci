"""Explainable completeness checks for design-state artifacts."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


COMPLETENESS_REPORT_SCHEMA_VERSION = "experiment_design_completeness_report_v1"
FIELD_SOURCE_STATUSES = frozenset(
    {
        "evidence_backed",
        "user_declared",
        "design_assumption",
        "needs_human_input",
        "not_applicable",
    }
)


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _lookup(payload: Mapping[str, Any], path: str) -> tuple[bool, Any]:
    current: Any = payload
    for part in path.split("."):
        if not isinstance(current, Mapping) or part not in current:
            return False, None
        current = current[part]
    return True, current


def _field_statuses(candidate_design: Mapping[str, Any]) -> dict[str, str]:
    raw = _mapping(candidate_design.get("field_statuses"))
    return {
        str(path): str(status)
        for path, status in raw.items()
        if str(status) in FIELD_SOURCE_STATUSES
    }


def _qualified_evidence_fields(evidence_bundle: Mapping[str, Any]) -> set[str]:
    return {
        str(record.get("field_path") or "").strip()
        for record in evidence_bundle.get("field_evidence_ledger") or []
        if isinstance(record, Mapping)
        and record.get("status") == "evidence_backed"
        and str(record.get("field_path") or "").strip()
    }


class CompletenessValidator:
    """Report missing fields and provenance states without inventing their values."""

    def assess(
        self,
        research_brief: Mapping[str, Any],
        template_routing: Mapping[str, Any],
        *,
        candidate_design: Mapping[str, Any] | None = None,
        evidence_bundle: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        candidate = _mapping(candidate_design)
        routing = _mapping(template_routing)
        statuses = _field_statuses(candidate)
        evidence = _mapping(evidence_bundle)
        has_traceable_evidence = bool(evidence.get("evidence_cards"))
        qualified_evidence_fields = _qualified_evidence_fields(evidence)
        requirements = list(routing.get("required_design_fields") or [])
        assessments: list[dict[str, Any]] = []
        errors: list[str] = []
        for field_path in requirements:
            path = str(field_path)
            present, value = _lookup(candidate, path)
            status = statuses.get(path)
            issue = ""
            if not present or value in (None, "", [], {}):
                status = "needs_human_input"
                issue = "missing_required_field"
                errors.append(f"missing_required_field:{path}")
            elif not status:
                status = "design_assumption"
                issue = "missing_field_source_status"
                errors.append(f"missing_field_source_status:{path}")
            elif status == "evidence_backed" and (
                not has_traceable_evidence or path not in qualified_evidence_fields
            ):
                status = "design_assumption"
                issue = "downgraded_without_qualifying_field_evidence"
                errors.append(f"downgraded_without_qualifying_field_evidence:{path}")
            assessments.append(
                {
                    "field_path": path,
                    "status": status,
                    "present": present,
                    "issue": issue,
                }
            )
        unknown_items = [
            {
                "field_path": item["field_path"],
                "status": item["status"],
                "reason": item["issue"] or "Field remains an explicit design assumption.",
                "blocks_final_design": item["status"] == "needs_human_input",
            }
            for item in assessments
            if item["status"] in {"needs_human_input", "design_assumption"}
        ]
        for index, item in enumerate(research_brief.get("known_unknowns") or [], start=1):
            text = str(item).strip()
            if text:
                unknown_items.append(
                    {
                        "field_path": f"research_brief.known_unknowns[{index}]",
                        "status": "needs_human_input",
                        "reason": text,
                        "blocks_final_design": True,
                    }
                )
        status = "READY_FOR_HUMAN_REVIEW" if not errors and not unknown_items else "DRAFT_REQUIRES_INPUT"
        return {
            "schema_version": COMPLETENESS_REPORT_SCHEMA_VERSION,
            "status": status,
            "template_id": str(routing.get("primary_template") or ""),
            "field_assessments": assessments,
            "unknown_items": unknown_items,
            "errors": errors,
            "warnings": [],
        }
