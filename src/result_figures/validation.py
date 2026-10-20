"""Verify output files and their exact experimental data dependencies."""

import json
from pathlib import Path
import xml.etree.ElementTree as ElementTree

from src.agents.computational_experiment_agent.artifacts import read_json, safe_path
from src.pipeline.science_run import file_sha256

from .contracts import FigureError


def check_reference(root, reference):
    path = safe_path(root, reference["path"])
    if not path.is_file() or file_sha256(path) != reference["sha256"]:
        raise FigureError("result_figure_artifact_modified:" + reference["path"])
    return path


def audit_outputs(directory, formats, *, max_bytes):
    checks = {}
    for output_format in formats:
        if output_format not in {"png", "pdf", "svg"}:
            raise FigureError("unsupported_figure_format")
        path = directory / ("figure." + output_format)
        if not path.is_file() or not 0 < path.stat().st_size <= max_bytes:
            raise FigureError("missing_or_oversized_figure_output")
        if output_format == "png":
            from PIL import Image

            with Image.open(path) as image:
                image.verify()
        elif output_format == "pdf":
            with path.open("rb") as handle:
                if handle.read(5) != b"%PDF-":
                    raise FigureError("invalid_figure_pdf")
        elif ElementTree.parse(path).getroot().tag != "{http://www.w3.org/2000/svg}svg":
            raise FigureError("invalid_figure_svg")
        checks[output_format] = {"status": "PASS", "size_bytes": path.stat().st_size}
    return checks


def audit_pdf(path):
    """Inspect exported text geometry without executing plotting code."""
    if not path.is_file():
        return {"status": "NOT_APPLICABLE", "reason": "PDF output was not requested."}
    try:
        import fitz
    except ImportError:
        return {"status": "NOT_AUDITABLE", "reason": "PyMuPDF is unavailable."}
    with fitz.open(path) as document:
        outside = overlaps = 0
        for page in document:
            spans = [span for block in page.get_text("dict")["blocks"] if block.get("type") == 0
                for line in block.get("lines", []) for span in line.get("spans", []) if span.get("text", "").strip()]
            rectangles = [fitz.Rect(span["bbox"]) for span in spans]
            outside += sum(not page.rect.contains(box) for box in rectangles)
            overlaps += sum((box & other).get_area() > 1
                for index, box in enumerate(rectangles) for other in rectangles[index + 1:])
        return {"status": "WARN" if outside or overlaps else "PASS", "backend": "pymupdf",
            "page_count": len(document), "overlap_count": overlaps, "out_of_bounds": outside}


def verify_figure_manifest(path, *, root, expected_identity=None, recompute=True):
    root, path = Path(root).resolve(), Path(path).resolve()
    path.relative_to(root)
    manifest = read_json(path)
    if manifest.get("schema_version") != "result_figures_manifest_v1" or manifest.get("status") not in {"SUCCEEDED", "PARTIAL", "SKIPPED", "FAILED"}:
        raise FigureError("unsupported_result_figures_manifest")
    identity = manifest["source_identity"]
    for key, value in (expected_identity or {}).items():
        if identity.get(key) != value:
            raise FigureError("result_figure_source_identity_mismatch:" + key)
    for reference in manifest["source_refs"]:
        check_reference(root, reference)
    recipes = None
    if recompute and any(item["status"] == "SUCCEEDED" for item in manifest["figures"]):
        from .adapters import computational_source, quantitative_source
        from .recipes import build_recipes

        references = {item["role"]: check_reference(root, item) for item in manifest["source_refs"]}
        if identity["branch"] == "quantitative":
            source = quantitative_source(root, references["plan"].parent, identity["execution_id"],
                convergence_refs=[item for item in manifest["source_refs"] if item["role"].startswith("convergence_")])
        elif identity["branch"] == "computation":
            source = computational_source(root, read_json(references["plan"]), read_json(references["result"]))
        else:
            raise FigureError("unsupported_result_figure_branch")
        if source.identity != identity or source.source_refs != manifest["source_refs"]:
            raise FigureError("result_figure_dependency_binding_mismatch")
        if source.quality != manifest["validation_status"] or source.result_kind != manifest["result_kind"]:
            raise FigureError("result_figure_result_semantics_mismatch")
        selected, unused_notes = build_recipes(source)
        recipes = {item["figure_id"]: item for item in selected}
    ids = set()
    for figure in manifest["figures"]:
        if figure["figure_id"] in ids:
            raise FigureError("duplicate_result_figure_id")
        ids.add(figure["figure_id"])
        if figure["status"] not in {"SUCCEEDED", "FAILED"}:
            raise FigureError("invalid_result_figure_status")
        if figure["status"] != "SUCCEEDED":
            continue
        for reference in figure["artifacts"]:
            check_reference(root, reference)
        if not figure["outputs"]:
            raise FigureError("result_figure_has_no_output")
        for reference in figure["outputs"]:
            output = check_reference(root, reference)
            if output.stat().st_size != reference["size_bytes"] or output.suffix != "." + reference["format"]:
                raise FigureError("result_figure_output_metadata_mismatch")
        paths = {item["role"]: check_reference(root, item) for item in figure["artifacts"]}
        spec = read_json(paths["figure_spec"])
        if set(spec["formats"]) != {item["format"] for item in figure["outputs"]} or spec["formats"] != manifest["settings"]["formats"]:
            raise FigureError("result_figure_formats_mismatch")
        if read_json(paths["qa"]) != figure["qa"]:
            raise FigureError("result_figure_qa_mismatch")
        if recompute:
            recipe = recipes.get(figure["figure_id"])
            if recipe is None or read_json(paths["plot_data"], max_bytes=64_000_000) != recipe["data"]:
                raise FigureError("result_figure_data_differs_from_execution")
            if {key: value for key, value in spec.items() if key != "formats"} != {key: value for key, value in recipe.items() if key != "data"}:
                raise FigureError("result_figure_spec_differs_from_execution")
            if figure["caption"] != recipe["caption"] or figure["data_binding"] != recipe["data_binding"]:
                raise FigureError("result_figure_caption_or_binding_mismatch")
    successes = sum(item["status"] == "SUCCEEDED" for item in manifest["figures"])
    if (manifest["status"] == "SUCCEEDED" and (not successes or successes != len(manifest["figures"]))) or (
        manifest["status"] == "SKIPPED" and manifest["figures"]) or (
        manifest["status"] == "FAILED" and successes) or (
        manifest["status"] == "PARTIAL" and not successes):
        raise FigureError("result_figure_manifest_status_mismatch")
    return manifest
