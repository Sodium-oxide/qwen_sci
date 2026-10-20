"""Immutable index generations, atomic publication and model identity."""
from __future__ import annotations

import hashlib
import json
import os
import uuid
from functools import lru_cache
from pathlib import Path
from typing import Any

from src.paper_graph.repository import json_text

INDEX_SCHEMA_VERSION = 1


@lru_cache(maxsize=64)
def _file_hash(path: str, size: int, mtime_ns: int, ctime_ns: int) -> str:
    del size, mtime_ns, ctime_ns  # Only cache when file metadata is unchanged.
    sha = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            sha.update(block)
    return sha.hexdigest()


def file_hash(path: Path) -> str:
    stat = path.stat()
    return _file_hash(str(path.resolve()), stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)


def model_identity(path: Path | str) -> dict[str, Any]:
    root = Path(path).expanduser().resolve()
    configs = [p for p in root.rglob("*.json") if "onnx" not in p.parts and "openvino" not in p.parts]
    weights = sorted(root.glob("*.safetensors")) or sorted(root.glob("pytorch_model*.bin"))
    if not (root / "config.json").is_file() or not (root / "modules.json").is_file() or not weights:
        raise FileNotFoundError(f"Incomplete local SentenceTransformer model: {root}")
    files = {str(p.relative_to(root)): file_hash(p) for p in sorted(set(configs + weights))}
    for name in ("sentencepiece.bpe.model", "vocab.txt"):
        if (root / name).is_file():
            files[name] = file_hash(root / name)
    revision = hashlib.sha256(json_text(files).encode()).hexdigest()
    return {"source": str(root), "revision": revision, "files": files}


def index_generation(index_dir: Path | str) -> Path:
    root = Path(index_dir).expanduser().resolve()
    pointer = root / "CURRENT.json"
    if not pointer.is_file():
        return root  # Read legacy artifacts so they can be rebuilt/migrated.
    payload = json.loads(pointer.read_text(encoding="utf-8"))
    name = payload.get("generation") if isinstance(payload, dict) else None
    if not isinstance(name, str) or not name or Path(name).name != name or name in {".", ".."}:
        raise ValueError(f"Invalid paper graph generation pointer: {pointer}")
    return root / "generations" / name


def publish_index(index_dir: Path, index: Any, metadata: dict[str, Any], manifest: dict[str, Any],
                  stats: dict[str, Any]) -> Path:
    import faiss
    root = Path(index_dir).expanduser().resolve()
    generation = uuid.uuid4().hex
    staging = root / "generations" / (".staging-" + generation)
    staging.mkdir(parents=True)
    faiss.write_index(index, str(staging / "faiss.index"))
    (staging / "meta.json").write_text(json_text(metadata), encoding="utf-8")
    manifest = {**manifest, "generation": generation,
                "artifacts": {name: file_hash(staging / name) for name in ("faiss.index", "meta.json")}}
    (staging / "manifest.json").write_text(json_text(manifest), encoding="utf-8")
    (staging / "build_stats.json").write_text(json_text(stats), encoding="utf-8")
    for path in staging.iterdir():
        with path.open("rb") as handle:
            os.fsync(handle.fileno())
    target = root / "generations" / generation
    os.replace(staging, target)
    pointer = root / (".CURRENT-" + generation + ".json")
    with pointer.open("w", encoding="utf-8") as handle:
        handle.write(json_text({"generation": generation}))
        handle.flush()
        os.fsync(handle.fileno())
    # Readers resolve this pointer once and read both files from that generation.
    os.replace(pointer, root / "CURRENT.json")
    return target


def read_artifacts(index_dir: Path | str) -> tuple[Any, dict[str, Any], dict[str, Any]]:
    import faiss
    root = index_generation(index_dir)
    missing = [name for name in ("faiss.index", "meta.json") if not (root / name).is_file()]
    if missing:
        raise FileNotFoundError(f"Component index files are missing under {root}: {', '.join(missing)}")
    manifest_path = root / "manifest.json"
    if not manifest_path.is_file():
        raise ValueError("Legacy component index has no version manifest; rebuild with --rebuild.")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if (not isinstance(manifest, dict) or manifest.get("schema_version") != INDEX_SCHEMA_VERSION
            or not isinstance(manifest.get("graph"), dict) or not isinstance(manifest.get("model"), dict)
            or not manifest["model"].get("revision")
            or not {"schema_version", "revision", "fingerprint"} <= manifest["graph"].keys()
            or type(manifest.get("component_count")) is not int
            or type(manifest.get("dimension")) is not int or manifest["dimension"] <= 0
            or set(manifest.get("artifacts", {})) != {"faiss.index", "meta.json"}):
        raise ValueError("Incomplete or unsupported component index manifest; rebuild the index.")
    if root.name != manifest.get("generation") and root.parent.name == "generations":
        raise ValueError("Component index manifest belongs to a different generation.")
    for name, expected in manifest["artifacts"].items():
        if name not in {"faiss.index", "meta.json"} or file_hash(root / name) != expected:
            raise ValueError(f"Paper graph artifact checksum mismatch: {name}")
    index = faiss.read_index(str(root / "faiss.index"))
    metadata = json.loads((root / "meta.json").read_text(encoding="utf-8"))
    raw = metadata.get("meta") if isinstance(metadata, dict) else None
    if not isinstance(raw, dict) or index.ntotal != len(raw) or manifest["component_count"] != len(raw):
        raise ValueError("FAISS vector count does not match component metadata")
    component_ids = [r.get("id") for r in raw.values() if isinstance(r, dict)]
    if (len(component_ids) != len(raw) or any(not isinstance(i, str) or not i.strip() for i in component_ids)
            or len(set(component_ids)) != len(raw)
            or any(not r.get("node_id") or not r.get("content_hash") for r in raw.values())
            or len({int(i) for i in raw}) != len(raw)):
        raise ValueError("Missing or duplicate component metadata identity")
    if hasattr(index, "id_map"):
        ids = {int(i) for i in faiss.vector_to_array(index.id_map)}
    else:
        ids = set(range(index.ntotal))
    if len(ids) != index.ntotal or ids != {int(i) for i in raw}:
        raise ValueError("FAISS IDs do not match component metadata IDs")
    if (manifest.get("dimension") != index.d or manifest.get("metric") != "cosine"
            or manifest.get("normalization") != "l2" or index.metric_type != faiss.METRIC_INNER_PRODUCT):
        raise ValueError("Incompatible dimension, metric or normalization in index manifest")
    import numpy as np
    for fid in raw:
        vector = index.reconstruct(int(fid))
        if not np.all(np.isfinite(vector)) or not np.isclose(np.linalg.norm(vector), 1, atol=1e-4):
            raise ValueError(f"Non-finite or non-normalized component vector: {fid}")
    return index, metadata, manifest
