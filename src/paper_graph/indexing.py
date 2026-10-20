"""Reconcile the current graph snapshot with a versioned component index."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import faiss
import numpy as np
from filelock import FileLock

from src.paper_graph.artifacts import INDEX_SCHEMA_VERSION, model_identity, publish_index, read_artifacts
from src.paper_graph.repository import core_snapshot, digest
from src.paper_graph.provenance import validate_graph
from src.paper_graph.settings import PaperGraphSettings

def component_records(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    records = []
    seen = set()
    for node in nodes:
        for position, component in enumerate(node.get("components") or []):
            if not isinstance(component, dict) or not str(component.get("summary") or "").strip():
                continue
            rid = str(component.get("node_id") or component.get("id") or
                      "component:" + digest([node["node_id"], component.get("name")])[:24])
            if rid in seen:
                raise ValueError(f"Duplicate component identity in graph: {rid}")
            seen.add(rid)
            records.append({"id": rid, "node_id": node["node_id"], "component_index": position,
                            "node_label": node.get("label") or node.get("full_name", ""),
                            "paper_title": node.get("paper_title", ""), "paper_id": node.get("paper_id", ""),
                            "paper_domain": node.get("paper_domain", ""),
                            "component_name": component.get("name", ""),
                            "component_summary": component["summary"],
                            "component_keywords": component.get("keywords", []),
                            "evidence_records": component.get("evidence_records", []),
                            "content_hash": digest(component)})
    return records


class GraphCoreComponentIndexer:
    def __init__(self, db_path: Path | str | None = None, store_path: Path | str | None = None,
                 model_path: Path | str | None = None, fetch_size: int = 16, *, model: Any = None,
                 config: Any = None) -> None:
        settings = PaperGraphSettings.from_config(config)
        self.db_path = Path(db_path or settings.db_path).expanduser().resolve()
        self.store_path = Path(store_path or settings.index_dir).expanduser().resolve()
        self.model_path = Path(model_path or settings.model_path).expanduser().resolve()
        self._model = model
        self.fetch_size = fetch_size

    def build(self, batch_size: int = 8, limit: int | None = None, rebuild: bool = False) -> dict[str, Any]:
        if limit is not None:
            raise ValueError("Partial graph publication is unsupported; build the full active snapshot.")
        self.store_path.mkdir(parents=True, exist_ok=True)
        with FileLock(str(self.store_path / ".build.lock"), timeout=30):
            return self._build(max(1, batch_size), rebuild)

    def _build(self, batch_size: int, rebuild: bool) -> dict[str, Any]:
        nodes, graph = core_snapshot(self.db_path)
        validate_graph(self.db_path, nodes)
        records = component_records(nodes)
        identity = model_identity(self.model_path)
        previous, previous_meta, previous_manifest = None, {}, {}
        try:
            previous, previous_meta, previous_manifest = read_artifacts(self.store_path)
        except FileNotFoundError:
            pass
        except (ValueError, RuntimeError):
            if not rebuild:
                raise
        reusable = (not rebuild and previous_manifest.get("model", {}).get("revision") == identity["revision"])
        old_by_id = {r["id"]: (int(fid), r) for fid, r in previous_meta.get("meta", {}).items()}
        matrices: dict[str, Any] = {}
        pending = []
        for record in records:
            old = old_by_id.get(record["id"])
            if reusable and old and old[1].get("content_hash") == record["content_hash"]:
                matrices[record["id"]] = previous.reconstruct(old[0])
            else:
                pending.append(record)
        if pending and self._model is None:
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer(str(self.model_path), local_files_only=True)
        for offset in range(0, len(pending), batch_size):
            batch = pending[offset:offset + batch_size]
            vectors = np.asarray(self._model.encode([r["component_summary"] for r in batch],
                convert_to_numpy=True, normalize_embeddings=True, show_progress_bar=False), dtype=np.float32)
            if vectors.ndim != 2 or vectors.shape[0] != len(batch) or not np.all(np.isfinite(vectors)):
                raise ValueError("Embedding output has invalid shape or non-finite values")
            norms = np.linalg.norm(vectors, axis=1, keepdims=True)
            if np.any(norms == 0):
                raise ValueError("Embedding output contains zero vectors")
            for record, vector in zip(batch, vectors / norms):
                matrices[record["id"]] = vector
        dim = len(next(iter(matrices.values()))) if matrices else (previous.d if reusable and previous is not None else 0)
        if not dim:
            raise ValueError("No Core component summaries available; import structured grounded extractions first.")
        index = faiss.IndexIDMap2(faiss.IndexFlatIP(dim))
        if records:
            vectors = np.stack([matrices[r["id"]] for r in records]).astype(np.float32)
            index.add_with_ids(vectors, np.arange(len(records), dtype=np.int64))
        # Fail before publication if an ingestion writer changed the snapshot.
        if core_snapshot(self.db_path)[1] != graph:
            raise RuntimeError("Paper graph changed during index build; retry against the new snapshot.")
        validate_graph(self.db_path, nodes)
        metadata = {"model_name_or_path": str(self.model_path), "meta": {str(i): r for i, r in enumerate(records)}}
        manifest = {"schema_version": INDEX_SCHEMA_VERSION, "graph": graph, "model": identity,
                    "dimension": dim, "metric": "cosine", "normalization": "l2", "component_count": len(records)}
        stats = {"db_path": str(self.db_path), "store_path": str(self.store_path), "graph": graph,
                 "total_core_nodes": len(nodes), "vector_store_size": len(records),
                 "embedded": len(pending), "reused": len(records) - len(pending),
                 "removed": len(set(old_by_id) - {r["id"] for r in records}), "rebuild": rebuild}
        generation = publish_index(self.store_path, index, metadata, manifest, stats)
        return {**stats, "generation": str(generation)}


def build_component_summary_vector_store(**kwargs: Any) -> dict[str, Any]:
    build_keys = {k: kwargs.pop(k) for k in ("batch_size", "limit", "rebuild") if k in kwargs}
    return GraphCoreComponentIndexer(**kwargs).build(**build_keys)
