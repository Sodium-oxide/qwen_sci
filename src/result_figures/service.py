"""Idempotent figure generation with atomic, independently verifiable bundles."""

import importlib.metadata
import json
import os
import shutil
import tempfile
import time
from pathlib import Path

from filelock import FileLock

from src.agents.computational_experiment_agent.artifacts import read_json, record
from src.pipeline.science_run import atomic_write_json, file_sha256

from .contracts import RENDERER_VERSION, FigureError, digest, settings_for_run
from .recipes import build_recipes
from .renderer import render_recipe
from .validation import audit_outputs, audit_pdf, check_reference, verify_figure_manifest


def ensure_result_figures(*, source, output_dir, settings=None, deadline=None, cancel_check=None):
    root, output_dir = source.root.resolve(), Path(output_dir).resolve()
    output_dir.relative_to(root)
    output_dir.mkdir(parents=True, exist_ok=True)
    with FileLock(str(output_dir / ".figures.lock"), timeout=30):
        return _ensure(source, output_dir, settings, deadline, cancel_check)


def _ensure(source, output_dir, settings, deadline, cancel_check):
    root = source.root.resolve()
    settings = settings_for_run(root, settings)
    dependencies = {}
    for name in ("matplotlib", "numpy", "pillow", "pymupdf"):
        try:
            dependencies[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            dependencies[name] = "unavailable"
    renderer_hash = digest({path.name: file_sha256(path) for path in Path(__file__).parent.glob("*.py")})
    fingerprint = digest({"identity": source.identity, "refs": source.source_refs, "settings": settings,
        "renderer": RENDERER_VERSION, "renderer_hash": renderer_hash, "dependencies": dependencies})
    pointer = output_dir / "figures_manifest.json"
    previous = None
    if pointer.is_file():
        try:
            candidate = read_json(pointer)
            if candidate.get("source_identity") != source.identity:
                raise FigureError("result_figure_source_identity_mismatch")
            if candidate["fingerprint"] == fingerprint:
                previous = candidate
                if candidate["status"] in {"SUCCEEDED", "SKIPPED"}:
                    verify_figure_manifest(pointer, root=root, recompute=False)
                    committed = root / candidate["committed_manifest"]
                    if read_json(committed) != candidate:
                        raise FigureError("result_figure_pointer_mismatch")
                    return {**candidate, "manifest_path": str(committed)}
        except (ValueError, OSError, KeyError):
            pass
    manifest = {"schema_version": "result_figures_manifest_v1", "source_identity": source.identity,
        "validation_status": source.quality, "result_kind": source.result_kind, "source_refs": source.source_refs,
        "fingerprint": fingerprint, "renderer_version": RENDERER_VERSION, "renderer_sha256": renderer_hash,
        "dependency_versions": dependencies, "settings": settings,
        "status": "SKIPPED", "reason": "", "notes": [], "figures": []}
    recipes = []
    try:
        if source.error:
            raise FigureError(source.error)
        for reference in source.source_refs:
            check_reference(root, reference)
        if not settings["enabled"]:
            manifest["reason"] = "result_figures_disabled"
        elif settings["qualified_only"] and source.quality != "QUALIFIED":
            manifest["reason"] = "result_not_qualified"
        else:
            recipes, manifest["notes"] = build_recipes(source)
            maximum = int(settings["max_figures_per_execution"])
            if len(recipes) > maximum:
                manifest["notes"].append("figure_limit:omitted=" + ",".join(item["figure_id"] for item in recipes[maximum:]))
            recipes = recipes[:maximum]
            if not recipes:
                manifest["reason"] = "no_supported_saved_data"
    except Exception as error:
        manifest.update(status="FAILED", reason=f"{type(error).__name__}:{error}")
    total_deadline = time.monotonic() + float(settings["max_total_seconds_per_execution"])
    if deadline is not None:
        total_deadline = min(total_deadline, deadline)
    generation_root = output_dir / ("set-" + fingerprint[:20])
    generation_root.mkdir(exist_ok=True)
    attempt = 1
    while (generation_root / f"attempt-{attempt:03d}").exists():
        attempt += 1
    destination = generation_root / f"attempt-{attempt:03d}"
    manifest["committed_manifest"] = (destination / "figures_manifest.json").relative_to(root).as_posix()
    staging = Path(tempfile.mkdtemp(prefix=".staging-", dir=generation_root))
    try:
        for recipe in recipes:
            entry = {key: recipe[key] for key in ("figure_id", "chart_type", "caption", "data_binding")}
            entry.update(status="FAILED", reason="", outputs=[], artifacts=[])
            reused = next((item for item in (previous or {}).get("figures", [])
                if item["figure_id"] == recipe["figure_id"] and item["status"] == "SUCCEEDED"), None)
            if reused:
                try:
                    for reference in [*reused["artifacts"], *reused["outputs"]]:
                        check_reference(root, reference)
                    manifest["figures"].append(reused)
                    continue
                except (ValueError, OSError, KeyError):
                    pass
            try:
                if cancel_check and cancel_check():
                    raise FigureError("figure_render_cancelled")
                if time.monotonic() >= total_deadline:
                    raise FigureError("figure_budget_exhausted")
                if "unavailable" in dependencies.values():
                    raise FigureError("figure_dependencies_unavailable:" + ",".join(name for name, version in dependencies.items() if version == "unavailable"))
                directory = staging / recipe["figure_id"]
                qa = render_recipe(recipe, directory, settings, deadline=total_deadline, cancel_check=cancel_check)
                qa["output_validation"] = audit_outputs(directory, settings["formats"], max_bytes=settings["max_output_bytes"])
                qa["pdf_text_geometry"] = audit_pdf(directory / "figure.pdf")
                if qa.get("out_of_bounds") or qa["pdf_text_geometry"].get("out_of_bounds"):
                    raise FigureError("figure_text_outside_canvas")
                if qa["pdf_text_geometry"].get("overlap_count"):
                    raise FigureError("figure_text_overlap")
                qa.update(dependency_versions=dependencies, data_binding=recipe["data_binding"], source_refs=source.source_refs)
                atomic_write_json(directory / "qa.json", qa)
                for filename, role in (("figure_spec.json", "figure_spec"), ("plot_data.json", "plot_data"),
                        ("plot_data.csv", "plot_data_csv"), ("qa.json", "qa"), ("figure.py", "source")):
                    target = destination / recipe["figure_id"] / filename
                    entry["artifacts"].append({"path": target.relative_to(root).as_posix(),
                        "sha256": file_sha256(directory / filename), "role": role})
                for output_format in settings["formats"]:
                    filename = "figure." + output_format
                    entry["outputs"].append({"path": (destination / recipe["figure_id"] / filename).relative_to(root).as_posix(),
                        "sha256": file_sha256(directory / filename), "format": output_format,
                        "size_bytes": (directory / filename).stat().st_size})
                entry.update(status="SUCCEEDED", qa=qa)
            except Exception as error:
                entry["reason"] = f"{type(error).__name__}:{error}"
            manifest["figures"].append(entry)
        if recipes:
            successful = sum(item["status"] == "SUCCEEDED" for item in manifest["figures"])
            invalid = any(note.startswith("invalid_plot_data:") for note in manifest["notes"])
            manifest["status"] = "SUCCEEDED" if successful == len(recipes) and not invalid else "PARTIAL" if successful else "FAILED"
        elif any(note.startswith("invalid_plot_data:") for note in manifest["notes"]):
            manifest.update(status="FAILED", reason="invalid_saved_plot_data")
        try:
            for reference in source.source_refs:
                check_reference(root, reference)
        except (ValueError, OSError) as error:
            manifest.update(status="FAILED", reason=f"source_changed_during_plotting:{error}")
            for entry in manifest["figures"]:
                entry.update(status="FAILED", reason=manifest["reason"], outputs=[], artifacts=[])
        atomic_write_json(staging / "figures_manifest.json", manifest)
        os.replace(staging, destination)
        atomic_write_json(pointer, manifest)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    return {**manifest, "manifest_path": str(destination / "figures_manifest.json")}


def figure_reference(root, manifest):
    return record(Path(root), Path(manifest["manifest_path"]))


def visual_figures(path, *, root, section_title):
    manifest = verify_figure_manifest(path, root=root)
    figures = []
    for item in manifest["figures"]:
        if item["status"] != "SUCCEEDED":
            continue
        selected = next((row for extension in ("pdf", "png") for row in item["outputs"] if row["format"] == extension), None)
        if selected:
            prefix = digest(manifest["source_identity"])[:12]
            figures.append({"figure_id": prefix + "-" + item["figure_id"],
                "file": prefix + "-" + item["figure_id"] + "." + selected["format"],
                "source_path": str(check_reference(Path(root), selected)), "caption_en": item["caption"],
                "source_sha256": selected["sha256"],
                "alt_text_en": item["caption"], "source_section_title": section_title})
    return figures


def append_figure_markdown(path, manifest, *, root):
    path = Path(path)
    marker = "\n<!-- result-figures -->\n"
    text = path.read_text(encoding="utf-8").split(marker)[0] if path.is_file() else ""
    lines = [marker, "## Result figures", "", "Figure status: " + manifest["status"], ""]
    for item in manifest["figures"]:
        preview = next((row for row in item["outputs"] if row["format"] == "png"), None)
        if preview:
            relative = os.path.relpath(Path(root) / preview["path"], path.parent).replace(os.sep, "/")
            lines.extend([f"![{item['figure_id']}]({relative})", "", item["caption"], ""])
        elif item["reason"]:
            lines.append(item["figure_id"] + ": " + item["reason"])
    lines.extend(manifest["notes"])
    if manifest["reason"]:
        lines.append(manifest["reason"])
    from src.pipeline.science_run import atomic_write_text

    atomic_write_text(path, text + "\n".join(lines) + "\n")
