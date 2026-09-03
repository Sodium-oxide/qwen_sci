"""Export only current, audited Proposal V2 artifacts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


PROPOSAL_EXPORT_SCHEMA_VERSION = "research_proposal_export_v2"


def _text(value: Any) -> str:
    return " ".join(str(value or "").split())


def proposal_markdown(proposal: dict[str, Any]) -> str:
    question = proposal.get("research_question") if isinstance(proposal.get("research_question"), dict) else {}
    lines = [
        f"# {_text(proposal.get('title'))}", "", "## Research question", "",
        _text(question.get("question_text") or question.get("target_knowledge_need")), "", "## Gap motivation", "",
        _text(proposal.get("gap_motivation")), "", "## Proposed aims", "",
    ]
    for aim in proposal.get("aims", []):
        if isinstance(aim, dict):
            lines.extend([f"### {_text(aim.get('title'))}", "", _text(aim.get("statement")), ""])
    lines.extend(["## Type-specific design", ""])
    for row in proposal.get("type_specific_design", []):
        if isinstance(row, dict):
            lines.append(f"- **{_text(row.get('label'))}:** {_text(row.get('value'))}")
    lines.extend(["", "## Decision rules", ""])
    rules = proposal.get("analysis_and_decision_rules") if isinstance(proposal.get("analysis_and_decision_rules"), dict) else {}
    for criterion in rules.get("success_criteria", []):
        lines.append(f"- {_text(criterion)}")
    lines.extend(["", "## Scope and limitations", ""])
    for item in proposal.get("risks_and_limitations", []):
        lines.append(f"- {_text(item)}")
    lines.extend(["", "## Source-bound evidence ledger", ""])
    for claim in proposal.get("claim_ledger", []):
        if isinstance(claim, dict):
            refs = ", ".join(_text(item) for item in claim.get("evidence_refs", []) if _text(item)) or "proposal action (no factual evidence claim)"
            lines.append(f"- **{_text(claim.get('claim_id'))} / {_text(claim.get('claim_kind'))}:** {refs}")
    return "\n".join(lines).strip() + "\n"


def export_research_proposal(project_id: str, proposal_id: str, output_dir: str = "") -> dict[str, Any]:
    try:
        from ._project import load_project
    except ImportError:
        from _project import load_project
    project = load_project(project_id)
    proposal = next(
        (item for item in project.get("research_proposals", []) if isinstance(item, dict) and str(item.get("proposal_id") or "") == str(proposal_id)),
        None,
    )
    if not isinstance(proposal, dict):
        raise ValueError("No research_proposal_v2 exists for the supplied proposal_id")
    audit = proposal.get("audit") if isinstance(proposal.get("audit"), dict) else {}
    if proposal.get("lifecycle_status") != "CURRENT" or audit.get("passes") is not True:
        raise ValueError("Only a current Proposal V2 with a passing audit may be exported")
    destination = Path(output_dir) if output_dir else Path.cwd() / ".science" / "proposal_exports" / str(project_id)
    destination.mkdir(parents=True, exist_ok=True)
    markdown_path = destination / f"{proposal_id}.md"
    json_path = destination / f"{proposal_id}.json"
    markdown_path.write_text(proposal_markdown(proposal), encoding="utf-8")
    json_path.write_text(json.dumps(proposal, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "schema_version": PROPOSAL_EXPORT_SCHEMA_VERSION,
        "project_id": project_id,
        "proposal_id": proposal_id,
        "status": "EXPORTED",
        "markdown_path": str(markdown_path),
        "json_path": str(json_path),
        "graph_snapshot_ref": dict(proposal.get("graph_snapshot_ref") or {}),
    }
