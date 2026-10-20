"""Branch adapters, sealed-run backfills and publication references."""

from pathlib import Path

from loguru import logger

from src.agents.computational_experiment_agent.artifacts import read_json, record, safe_path
from src.pipeline.science_run import atomic_write_json

from .adapters import computational_source, quantitative_source
from .contracts import FigureSource
from .service import append_figure_markdown, ensure_result_figures, visual_figures
from .validation import check_reference, verify_figure_manifest


def ensure_quantitative_figures(root, version_dir, execution_id, *, settings=None, deadline=None, cancel_check=None):
    root, version_dir = Path(root).resolve(), Path(version_dir).resolve()
    sealed = (version_dir.parent / "finalization.json").is_file()
    output = version_dir / "executions" / execution_id / "figures"
    if sealed:
        existing = output / "figures_manifest.json"
        if existing.is_file():
            try:
                manifest = verify_figure_manifest(existing, root=root)
                if manifest["status"] == "SUCCEEDED":
                    return {**manifest, "manifest_path": str(safe_path(root, manifest["committed_manifest"]))}
            except (ValueError, OSError, KeyError):
                pass
        output = root / "figure_deliveries" / "quantitative" / version_dir.parent.name / version_dir.name / execution_id / "figures"
    try:
        source = quantitative_source(root, version_dir, execution_id)
    except Exception as error:
        source = FigureSource(root, {"branch": "quantitative", "quantitative_idea_id": version_dir.parent.name,
            "version": int(version_dir.name[1:]), "execution_id": execution_id}, "UNAVAILABLE", "NUMERICAL_SIMULATION", [],
            error=f"source_adapter_failed:{type(error).__name__}:{error}")
    manifest = ensure_result_figures(source=source, output_dir=output, settings=settings,
        deadline=deadline, cancel_check=cancel_check)
    if not sealed:
        append_figure_markdown(output.parent / "figures.md", manifest, root=root)
    return manifest


def ensure_computational_figures(root, plan, result, *, settings=None, deadline=None, cancel_check=None):
    root = Path(root).resolve()
    if not result.get("lineage") or result["execution_status"] != "COMPLETED":
        return None
    execution_dir = Path(result["lineage"][-1]["execution_path"]).resolve().parent
    execution_dir.relative_to(root / "computation")
    try:
        source = computational_source(root, plan, result)
    except Exception as error:
        source = FigureSource(root, {**plan["source_binding"], "branch": "computation", "experiment_id": plan["experiment_id"],
            "protocol_version": plan["protocol_version"], "execution_id": result["lineage"][-1]["execution_id"]},
            result["validation_status"], result["result_kind"], [], error=f"source_adapter_failed:{type(error).__name__}:{error}")
    output = execution_dir / "figures"
    sealed = (root / "computation/manifest.json").is_file()
    if sealed:
        existing = output / "figures_manifest.json"
        if existing.is_file():
            try:
                manifest = verify_figure_manifest(existing, root=root, expected_identity=source.identity)
                if manifest["status"] == "SUCCEEDED":
                    return {**manifest, "manifest_path": str(safe_path(root, manifest["committed_manifest"]))}
            except (ValueError, OSError, KeyError):
                pass
        output = root / "figure_deliveries/computation" / plan["experiment_id"] / f"protocol-v{plan['protocol_version']:03d}" / source.identity["execution_id"] / "figures"
    manifest = ensure_result_figures(source=source, output_dir=output, settings=settings,
        deadline=deadline, cancel_check=cancel_check)
    if not sealed:
        append_figure_markdown(execution_dir.parent.parent / "analysis.md", manifest, root=root)
    return manifest


def optional_figures(function, *args, **kwargs):
    """Keep a plotting failure separate from the scientific result status."""
    try:
        manifest = function(*args, **kwargs)
        if manifest and manifest["status"] in {"PARTIAL", "FAILED"}:
            logger.warning("Result figures {}: {}", manifest["status"], manifest["manifest_path"])
        return manifest
    except Exception as error:
        logger.warning("Optional result figures failed: {}: {}", type(error).__name__, error)
        return None


def quantitative_figure_index(root, version_dir, execution_ids):
    root, version_dir = Path(root).resolve(), Path(version_dir).resolve()
    references, unavailable = [], []
    for execution_id in execution_ids:
        manifest = optional_figures(ensure_quantitative_figures, root, version_dir, execution_id)
        if manifest:
            references.append(record(root, Path(manifest["manifest_path"])))
        else:
            unavailable.append({"execution_id": execution_id, "reason": "result_figure_generation_unavailable"})
    index = version_dir / "result_figures_index.json"
    atomic_write_json(index, {"schema_version": "result_figures_index_v1", "execution_ids": list(execution_ids),
        "manifests": references, "unavailable": unavailable})
    return {"path": str(index), "sha256": record(root, index)["sha256"]}


def verify_figure_index(reference, *, root, expected_identity=None, execution_ids=None):
    path = Path(reference["path"])
    if path.is_absolute():
        path = path.resolve()
        path.relative_to(Path(root).resolve())
        reference = {**reference, "path": path.relative_to(Path(root).resolve()).as_posix()}
    path = check_reference(Path(root), reference)
    index = read_json(path)
    if index.get("schema_version") != "result_figures_index_v1":
        raise ValueError("unsupported_result_figure_index")
    actual_ids = []
    for item in index["manifests"]:
        candidate = check_reference(Path(root), item)
        manifest = verify_figure_manifest(candidate, root=root, expected_identity=expected_identity)
        actual_ids.append(manifest["source_identity"]["execution_id"])
    for item in index.get("unavailable", []):
        if not isinstance(item.get("reason"), str) or not item["reason"].strip():
            raise ValueError("result_figure_unavailable_reason_missing")
        actual_ids.append(item["execution_id"])
    if sorted(actual_ids) != sorted(index["execution_ids"]) or len(set(actual_ids)) != len(actual_ids) or (
        execution_ids is not None and sorted(actual_ids) != sorted(execution_ids)):
        raise ValueError("result_figure_execution_index_mismatch")
    return index


def index_visual_figures(reference, *, root, section_title, expected_identity=None):
    index = verify_figure_index(reference, root=root, expected_identity=expected_identity)
    return [figure for item in index["manifests"]
        for figure in visual_figures(safe_path(Path(root), item["path"]), root=root, section_title=section_title)]
