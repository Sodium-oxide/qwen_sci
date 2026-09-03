"""Proposal-centric V3 report model and Markdown export.

Unlike the historical hypothesis report, this model can faithfully report any
of the fourteen research-package kinds.  It is intentionally a separate
artifact, so the old causal report does not acquire a hidden compatibility
adapter.
"""

from __future__ import annotations

import json
from pathlib import Path
import time
from typing import Any


TRACEABILITY_REPORT_SCHEMA_VERSION = "traceability_report_v3"
PROPOSAL_REPORT_SCHEMA_VERSION = "research_proposal_report_v3"


def _text(value: Any) -> str:
    return " ".join(str(value or "").split())


def build_proposal_report_model(project: dict[str, Any]) -> dict[str, Any]:
    packages = [item for item in project.get("research_packages", []) if isinstance(item, dict) and item.get("schema_version") == "research_package_v2"]
    briefs = [item for item in project.get("proposal_briefs", []) if isinstance(item, dict) and item.get("schema_version") == "proposal_brief_v2"]
    proposals = [item for item in project.get("research_proposals", []) if isinstance(item, dict) and item.get("schema_version") == "research_proposal_v2"]
    graph_ref = project.get("active_research_evidence_graph_ref") if isinstance(project.get("active_research_evidence_graph_ref"), dict) else {}
    task_graph_ref = project.get("active_research_task_graph_ref") if isinstance(project.get("active_research_task_graph_ref"), dict) else {}
    try:
        from ._project import science_state_manager
    except ImportError:
        from _project import science_state_manager
    try:
        graph_snapshot = science_state_manager().get_research_evidence_graph(
            _text(project.get("project_id")),
            graph_ref,
        ) if graph_ref else None
    except (FileNotFoundError, RuntimeError, ValueError):
        graph_snapshot = None
    return {
        "schema_version": PROPOSAL_REPORT_SCHEMA_VERSION,
        "project": {
            "project_id": _text(project.get("project_id")),
            "title": _text(project.get("title") or project.get("objective")),
            "objective": _text(project.get("objective")),
            "state_version": project.get("state_version"),
        },
        "research_evidence_graph_ref": dict(graph_ref),
        "research_task_graph_ref": dict(task_graph_ref),
        "graph_quality_audit": dict((graph_snapshot or {}).get("quality_audit") or {}),
        "research_packages": [
            {
                "research_package_id": item.get("research_package_id"),
                "package_version": item.get("package_version"),
                "gap_id": item.get("gap_id"),
                "gap_type": item.get("gap_type"),
                "package_kind": item.get("package_kind"),
                "lifecycle_status": item.get("lifecycle_status"),
                "graph_snapshot_ref": item.get("graph_snapshot_ref"),
            }
            for item in packages
        ],
        "proposal_briefs": [
            {
                "proposal_brief_id": item.get("proposal_brief_id"),
                "proposal_kind": item.get("proposal_kind"),
                "research_package_ref": item.get("research_package_ref"),
                "lifecycle_status": item.get("lifecycle_status"),
            }
            for item in briefs
        ],
        "proposals": [
            {
                "proposal_id": item.get("proposal_id"),
                "proposal_kind": item.get("proposal_kind"),
                "title": item.get("title"),
                "research_package_ref": item.get("research_package_ref"),
                "graph_snapshot_ref": item.get("graph_snapshot_ref"),
                "lifecycle_status": item.get("lifecycle_status"),
                "audit": item.get("audit"),
                "scope_contract": item.get("scope_contract"),
            }
            for item in proposals
        ],
        "socrates_type_reviews": dict(project.get("socrates_type_reviews") or {}),
        "retrieval_coverage": [
            {
                "gap_id": item.get("gap_id"),
                "candidate_identity": item.get("candidate_identity"),
                "route": (item.get("gap_assessment") or {}).get("route") if isinstance(item.get("gap_assessment"), dict) else "",
                "retrieval_assessment": item.get("retrieval_assessment"),
            }
            for item in ((project.get("tanxi_gap_analysis") or {}).get("ranked_gaps", []) if isinstance(project.get("tanxi_gap_analysis"), dict) else [])
            if isinstance(item, dict)
        ],
        "limitations_and_nonclaims": [
            "A graph relation is a source-bound assertion, not an automatically established scientific fact.",
            "Derived inferences and retrieval coverage records are diagnostic-only and cannot by themselves support a primary candidate or proposal fact claim.",
            "Every proposal remains a type-specific, scope-bounded research plan until its proposed work is independently completed and evaluated.",
        ],
        "generated_at": time.time(),
    }


def render_proposal_report_markdown(model: dict[str, Any]) -> str:
    project = model.get("project") if isinstance(model.get("project"), dict) else {}
    lines = [
        f"# Research Proposal Traceability Report: {_text(project.get('title'))}", "",
        "## Evidence graph", "",
        f"- Graph snapshot: `{_text((model.get('research_evidence_graph_ref') or {}).get('graph_id'))}` v{(model.get('research_evidence_graph_ref') or {}).get('graph_version', '')}",
        f"- Task graph: `{_text((model.get('research_task_graph_ref') or {}).get('task_graph_id'))}` v{(model.get('research_task_graph_ref') or {}).get('task_graph_version', '')}",
        f"- Graph quality: `{(model.get('graph_quality_audit') or {}).get('passes')}`", "",
        "## Type-specific research packages", "",
    ]
    for item in model.get("research_packages", []):
        if isinstance(item, dict):
            lines.append(f"- `{_text(item.get('research_package_id'))}` — {_text(item.get('gap_type'))} → {_text(item.get('package_kind'))}; status `{_text(item.get('lifecycle_status'))}`")
    lines.extend(["", "## Proposal artifacts", ""])
    for item in model.get("proposals", []):
        if not isinstance(item, dict):
            continue
        audit = item.get("audit") if isinstance(item.get("audit"), dict) else {}
        lines.append(f"- `{_text(item.get('proposal_id'))}` — {_text(item.get('proposal_kind'))}; audit `{_text(audit.get('status'))}`; status `{_text(item.get('lifecycle_status'))}`")
    lines.extend(["", "## Retrieval coverage", ""])
    for item in model.get("retrieval_coverage", []):
        if isinstance(item, dict):
            assessment = item.get("retrieval_assessment") if isinstance(item.get("retrieval_assessment"), dict) else {}
            lines.append(
                f"- `{_text(item.get('gap_id'))}`: route `{_text(item.get('route'))}`; "
                f"coverage `{_text(assessment.get('coverage_status') or assessment.get('novelty_verdict'))}`; "
                f"remaining axes `{', '.join(_text(axis) for axis in assessment.get('remaining_missing_axes', []) if _text(axis)) or 'none recorded'}`"
            )
    lines.extend(["", "## Limitations and nonclaims", ""])
    for item in model.get("limitations_and_nonclaims", []):
        lines.append(f"- {_text(item)}")
    return "\n".join(lines).strip() + "\n"


def build_traceability_report_model(project: dict[str, Any]) -> dict[str, Any]:
    """Return a report that is valid even when no package passed a gate."""
    model = build_proposal_report_model(project)
    return {
        **model,
        "schema_version": TRACEABILITY_REPORT_SCHEMA_VERSION,
        "typed_gap_landscape": [
            {
                "gap_id": item.get("gap_id"),
                "candidate_identity": item.get("candidate_identity"),
                "gap_type": item.get("gap_type") or (item.get("gap_assessment") or {}).get("gap_type"),
                "route": (item.get("gap_assessment") or {}).get("route"),
                "graph_snapshot_ref": item.get("graph_snapshot_ref"),
            }
            for item in ((project.get("tanxi_gap_analysis") or {}).get("ranked_gaps", []) if isinstance(project.get("tanxi_gap_analysis"), dict) else [])
            if isinstance(item, dict)
        ],
    }


def render_traceability_report_markdown(model: dict[str, Any]) -> str:
    base = render_proposal_report_markdown(model)
    gap_lines = ["", "## Typed gap landscape", ""]
    for item in model.get("typed_gap_landscape", []):
        if isinstance(item, dict):
            gap_lines.append(
                f"- `{_text(item.get('gap_id'))}`: `{_text(item.get('gap_type'))}`; route `{_text(item.get('route'))}`"
            )
    return base.rstrip() + "\n" + "\n".join(gap_lines).strip() + "\n"


def generate_proposal_traceability_report(project_id: str, output_dir: str = "") -> dict[str, Any]:
    try:
        from ._project import load_project
    except ImportError:
        from _project import load_project
    project = load_project(project_id)
    model = build_traceability_report_model(project)
    destination = Path(output_dir) if output_dir else Path.cwd() / ".science" / "proposal_reports" / str(project_id)
    destination.mkdir(parents=True, exist_ok=True)
    json_path = destination / "proposal_traceability_report_v3.json"
    markdown_path = destination / "proposal_traceability_report_v3.md"
    json_path.write_text(json.dumps(model, ensure_ascii=False, indent=2), encoding="utf-8")
    markdown_path.write_text(render_traceability_report_markdown(model), encoding="utf-8")
    return {
        "schema_version": TRACEABILITY_REPORT_SCHEMA_VERSION,
        "project_id": project_id,
        "status": "GENERATED",
        "json_path": str(json_path),
        "markdown_path": str(markdown_path),
        "research_evidence_graph_ref": model.get("research_evidence_graph_ref"),
        "proposal_count": len(model.get("proposals") or []),
    }


def generate_research_proposal_report(project_id: str, output_dir: str = "") -> dict[str, Any]:
    """Generate the proposal report only for current, audit-passing V2 plans."""
    try:
        from ._project import load_project
    except ImportError:
        from _project import load_project
    project = load_project(project_id)
    model = build_proposal_report_model(project)
    approved = [
        item for item in model.get("proposals", [])
        if isinstance(item, dict)
        and isinstance(item.get("audit"), dict)
        and item["audit"].get("passes") is True
        and item.get("lifecycle_status") == "CURRENT"
    ]
    if not approved:
        raise ValueError("research_proposal_report_v3 requires at least one current Proposal V2 with a passing audit")
    model["proposals"] = approved
    destination = Path(output_dir) if output_dir else Path.cwd() / ".science" / "proposal_reports" / str(project_id)
    destination.mkdir(parents=True, exist_ok=True)
    json_path = destination / "research_proposal_report_v3.json"
    markdown_path = destination / "research_proposal_report_v3.md"
    markdown_path.write_text(render_proposal_report_markdown(model), encoding="utf-8")
    json_path.write_text(json.dumps(model, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "schema_version": PROPOSAL_REPORT_SCHEMA_VERSION,
        "project_id": project_id,
        "status": "GENERATED",
        "json_path": str(json_path),
        "markdown_path": str(markdown_path),
        "research_evidence_graph_ref": model.get("research_evidence_graph_ref"),
        "proposal_count": len(approved),
    }
