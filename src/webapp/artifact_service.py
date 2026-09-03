"""Safe artifact enumeration for browser previews and downloads."""

from __future__ import annotations

import mimetypes
from collections.abc import Mapping
from pathlib import Path

from src.pipeline.science_run import ScienceRunPaths

from .schemas import ArtifactView


_IMAGE_ARTIFACT_SUFFIXES = frozenset({".bmp", ".gif", ".jpeg", ".jpg", ".png", ".svg", ".tif", ".tiff", ".webp"})
_STAGE_ARTIFACT_DIRECTORIES = {
    "survey": "survey",
    "idea": "idea",
    "exp_design": "experiment_design",
    "author": "author",
}
_MAX_DISCOVERED_STAGE_IMAGES = 256


def _safe_path(paths: ScienceRunPaths, value: object) -> Path | None:
    if not isinstance(value, str) or not value.strip():
        return None
    path = Path(value).expanduser()
    try:
        resolved = path.resolve(strict=True)
        resolved.relative_to(paths.run_dir.resolve())
    except (OSError, ValueError):
        return None
    return resolved if resolved.is_file() else None


def artifact_index(paths: ScienceRunPaths, state: Mapping[str, object]) -> dict[str, Path]:
    indexed: dict[str, Path] = {}
    stages = state.get("stages")
    if isinstance(stages, Mapping):
        for stage_name, stage in stages.items():
            if not isinstance(stage, Mapping):
                continue
            outputs = stage.get("outputs")
            if not isinstance(outputs, Mapping):
                continue
            for output_name, raw_path in outputs.items():
                path = _safe_path(paths, raw_path)
                if path is not None:
                    indexed[f"{stage_name}:{output_name}"] = path
    _index_stage_images(paths, indexed)
    for manifest_path in (paths.materials_manifest, paths.multimodal_input_manifest):
        if manifest_path.is_file():
            indexed[f"inputs:{manifest_path.stem}"] = manifest_path
    quantitative_root = paths.run_dir / "quantitative"
    if quantitative_root.is_dir():
        allowed_suffixes = {".json", ".md", ".txt", ".pdf", ".tex", ".log", ".png", ".jpg", ".jpeg", ".svg"}
        excluded_names = {"workflow_state.json"}
        try:
            quantitative_files = sorted(path for path in quantitative_root.rglob("*") if path.is_file())
        except OSError:
            quantitative_files = []
        for path in quantitative_files[:256]:
            if path.suffix.casefold() not in allowed_suffixes or path.name in excluded_names:
                continue
            try:
                relative = path.resolve().relative_to(quantitative_root.resolve()).as_posix()
            except (OSError, ValueError):
                continue
            indexed[f"quantitative:{relative}"] = path
    return indexed


def _index_stage_images(paths: ScienceRunPaths, indexed: dict[str, Path]) -> None:
    """Index generated figures that stage manifests do not list individually."""

    known_paths = set(indexed.values())
    discovered = 0
    for stage_name, directory_name in _STAGE_ARTIFACT_DIRECTORIES.items():
        stage_root = paths.run_dir / directory_name
        if not stage_root.is_dir():
            continue
        try:
            candidates = sorted(
                candidate
                for candidate in stage_root.rglob("*")
                if candidate.is_file() and candidate.suffix.casefold() in _IMAGE_ARTIFACT_SUFFIXES
            )
        except OSError:
            continue
        for candidate in candidates:
            if discovered >= _MAX_DISCOVERED_STAGE_IMAGES:
                return
            path = _safe_path(paths, str(candidate))
            if path is None or path in known_paths:
                continue
            try:
                relative = path.relative_to(stage_root.resolve()).as_posix()
            except (OSError, ValueError):
                continue
            indexed[f"{stage_name}:figure:{relative}"] = path
            known_paths.add(path)
            discovered += 1


def list_artifacts(paths: ScienceRunPaths, state: Mapping[str, object]) -> list[ArtifactView]:
    views: list[ArtifactView] = []
    for artifact_id, path in artifact_index(paths, state).items():
        media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        figure_marker = ":figure:"
        label = artifact_id.split(figure_marker, 1)[1] if figure_marker in artifact_id else path.name
        views.append(
            ArtifactView(
                artifact_id=artifact_id,
                label=label,
                stage=artifact_id.split(":", 1)[0],
                media_type=media_type,
                previewable=media_type in {"application/pdf", "application/json", "text/markdown", "text/plain"} or media_type.startswith("image/"),
                size_bytes=path.stat().st_size,
            )
        )
    return sorted(views, key=lambda view: (view.stage, view.label))
