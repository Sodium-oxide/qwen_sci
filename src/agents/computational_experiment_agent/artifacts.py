"""Bounded artifact IO shared by the controller and evidence verifier."""

import json
from pathlib import Path, PurePosixPath

from src.pipeline.science_run import atomic_write_json, atomic_write_text, file_sha256


def safe_path(root: Path, relative: str) -> Path:
    normalized = relative.replace("\\", "/")
    parts = PurePosixPath(normalized)
    if not normalized or parts.is_absolute() or ":" in normalized or any(part in {"..", ".", ""} for part in normalized.split("/")):
        raise ValueError(f"unsafe_artifact_path:{relative}")
    candidate = root / parts
    for ancestor in [candidate, *candidate.parents]:
        if ancestor == root.parent:
            break
        if ancestor.is_symlink() or (hasattr(ancestor, "is_junction") and ancestor.is_junction()):
            raise ValueError(f"linked_artifact_path:{relative}")
    candidate.resolve().relative_to(root.resolve())
    return candidate


def read_json(path: Path, max_bytes: int = 8_000_000) -> dict:
    if path.is_symlink() or path.stat().st_size > max_bytes:
        raise ValueError(f"unsafe_or_oversized_json:{path.name}")
    result = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(result, dict):
        raise ValueError("artifact_must_be_object")
    return result


def record(root: Path, path: Path) -> dict:
    relative = path.relative_to(root).as_posix()
    checked = safe_path(root, relative)
    return {"path": relative, "sha256": file_sha256(checked)}


__all__ = ["safe_path", "read_json", "record", "atomic_write_json", "atomic_write_text"]
