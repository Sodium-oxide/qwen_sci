"""Publish compact protocols and complete typed results with artifact lineage."""

from pathlib import Path

from .artifacts import record
from .contracts import require_contract


def build_handoff(root: Path, context: dict, plans: list, results: list, status: str, unresolved: list) -> dict:
    artifacts = [record(root, path) for path in sorted(root.rglob("*")) if path.is_file()
        and path.name not in {"manifest.json", "author_handoff.json", "branch_state.json", "events.jsonl", "authorization.json", "controller.log", "supervisor.log"}
        and not path.name.startswith(".") and "__pycache__" not in path.parts]
    return require_contract({"schema_version": "computational_author_handoff_v1", "source_binding": context["source_binding"],
        "branch_status": status, "plans": plans, "results": results,
        "unresolved_items": list(dict.fromkeys(unresolved)), "artifact_refs": artifacts})
