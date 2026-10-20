"""Publish compact protocols and complete typed results with artifact lineage."""

from pathlib import Path

from .artifacts import read_json, record, safe_path
from .contracts import require_contract


def build_handoff(root: Path, context: dict, plans: list, results: list, status: str, unresolved: list) -> dict:
    artifacts = [record(root, path) for path in sorted(root.rglob("*")) if path.is_file()
        and path.name not in {"manifest.json", "author_handoff.json", "branch_state.json", "events.jsonl", "authorization.json", "controller.log", "supervisor.log"}
        and not any(part.startswith(".") or part in {"__pycache__", "mplconfig"} for part in path.relative_to(root).parts)]
    figure_manifests = set()
    for pointer in root.glob("CE*/protocol-v*/implementation-v*/execution-*/figures/figures_manifest.json"):
        figure_manifests.add(safe_path(root.parent, read_json(pointer)["committed_manifest"]).relative_to(root).as_posix())
    for artifact in artifacts:
        if artifact["path"] in figure_manifests:
            artifact["role"] = "result_figures"
    return require_contract({"schema_version": "computational_author_handoff_v1", "source_binding": context["source_binding"],
        "branch_status": status, "plans": plans, "results": results,
        "unresolved_items": list(dict.fromkeys(unresolved)), "artifact_refs": artifacts})
