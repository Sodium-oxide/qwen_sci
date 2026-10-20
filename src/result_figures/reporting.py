"""Resolve report figures only from verified scientific handoff manifests."""

from pathlib import Path

from src.agents.computational_experiment_agent.artifacts import read_json, safe_path
from src.pipeline.science_run import file_sha256

from .contracts import FigureError
from .integration import index_visual_figures
from .service import visual_figures
from .validation import check_reference, verify_figure_manifest


QUANTITATIVE_SECTION = "Computational Evidence (Numerical Simulation; Non-empirical)"
COMPUTATIONAL_SECTION = "Computational Evidence"


def _quantitative_executions(root, manifest_path, evidence):
    from src.agents.quantitative_modeling.author_handoff import load_finalized_quantitative_record

    references = read_json(manifest_path).get("inputs", {}).get("finalizations", {})
    executions = set()
    for idea_id, version in {(item["quantitative_idea_id"], item["final_version"]) for item in evidence}:
        reference = references.get(idea_id)
        if not reference:
            raise FigureError("report_missing_quantitative_finalization")
        relative = Path(reference["path"]).resolve().relative_to(root).as_posix()
        finalization_path = check_reference(root, {**reference, "path": relative})
        finalization = load_finalized_quantitative_record(root=root, finalization_path=finalization_path)["finalization"]
        if finalization["quantitative_idea_id"] != idea_id or finalization["final_version"] != version:
            raise FigureError("report_quantitative_finalization_identity_mismatch")
        executions.update((idea_id, version, execution_id) for execution_id in finalization["qualified_execution_ids"])
    return executions


def report_result_figures(document):
    figures = []
    sections = {section["title"] for section in document.get("sections", [])}
    for branch in ("quantitative", "computational"):
        binding = document.get("source_manifest", {}).get(branch + "_evidence", {})
        if not binding.get("manifest_path"):
            continue
        manifest_path = Path(binding["manifest_path"]).resolve()
        if binding.get("manifest_sha256") != file_sha256(manifest_path):
            raise FigureError("report_evidence_manifest_modified")
        if branch == "quantitative":
            from src.agents.research_plan_author.quantitative_evidence_adapter import load_quantitative_evidence_capsule

            capsule = load_quantitative_evidence_capsule(manifest_path, expected_identity=binding["source_identity"])
            root = manifest_path.parents[2]
            if QUANTITATIVE_SECTION not in sections:
                raise FigureError("report_missing_quantitative_evidence_section")
            for reference in capsule["result_figure_indexes"]:
                figures.extend(index_visual_figures(reference, root=root, section_title=QUANTITATIVE_SECTION,
                    expected_identity=capsule["source_identity"]))
            executions = _quantitative_executions(root, manifest_path, capsule["evidence"])
        else:
            from src.agents.research_plan_author.computational_evidence_adapter import load_computational_evidence_capsule

            capsule = load_computational_evidence_capsule(manifest_path, expected_identity=binding["source_identity"])
            root = manifest_path.parents[1]
            if COMPUTATIONAL_SECTION not in sections:
                raise FigureError("report_missing_computational_evidence_section")
            for reference in capsule["result_figure_refs"]:
                figures.extend(visual_figures(safe_path(root / "computation", reference["path"]), root=root,
                    section_title=COMPUTATIONAL_SECTION))
            executions = {(item["experiment_id"], item["protocol_version"], row["execution_id"])
                for item in capsule["results"] for row in item["lineage"]}
        delivery_root = root / "figure_deliveries" / ("quantitative" if branch == "quantitative" else "computation")
        for pointer in sorted(delivery_root.glob("**/figures/figures_manifest.json")):
            manifest = verify_figure_manifest(pointer, root=root,
                expected_identity={**binding["source_identity"], "branch": "quantitative" if branch == "quantitative" else "computation"})
            identity = manifest["source_identity"]
            key = (identity["quantitative_idea_id"], identity["version"], identity["execution_id"]) if branch == "quantitative" else (
                identity["experiment_id"], identity["protocol_version"], identity["execution_id"])
            if key not in executions:
                raise FigureError("detached_figure_without_report_evidence")
            figures.extend(visual_figures(safe_path(root, manifest["committed_manifest"]), root=root,
                section_title=QUANTITATIVE_SECTION if branch == "quantitative" else COMPUTATIONAL_SECTION))
    return tuple({figure["figure_id"]: figure for figure in figures}.values())
