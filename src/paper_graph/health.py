"""Read-only checks for real graph/index/model readiness; no embedding load."""
from __future__ import annotations

from collections import Counter
from typing import Any

import numpy as np

from src.paper_graph.artifacts import model_identity, read_artifacts
from src.paper_graph.indexing import component_records
from src.paper_graph.repository import core_snapshot, readonly_connection
from src.paper_graph.settings import PaperGraphSettings
from src.paper_graph.provenance import validate_graph
from src.pipeline.discipline_taxonomy import canonicalize_discipline_key


def check_paper_graph(settings: PaperGraphSettings) -> dict[str, Any]:
    checks = []
    counts: dict[str, int] = {}
    domains: Counter[str] = Counter()

    def check(name: str, ok: bool, detail: Any, *, required: bool = True) -> None:
        checks.append({"name": name, "ok": bool(ok), "detail": detail, "required": required})

    nodes, graph, records = [], {}, []
    try:
        conn = readonly_connection(settings.db_path)
        try:
            required_tables = {"nodes", "edges", "aliases", "node_fts", "graph_state", "paper_imports", "extraction_queue"}
            tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master")}
            columns = {r[1] for r in conn.execute("PRAGMA table_info(nodes)")}
            ok = required_tables <= tables and {"id", "node_type", "paper_id", "raw_json"} <= columns
            check("graph_schema", ok, {"missing_tables": sorted(required_tables - tables), "columns": sorted(columns)})
            counts = dict(conn.execute("SELECT node_type,COUNT(*) FROM nodes GROUP BY node_type"))
        finally:
            conn.close()
        nodes, graph = core_snapshot(settings.db_path)
        records = component_records(nodes)
        domains.update(canonicalize_discipline_key(n.get("paper_domain")) or "unresolved" for n in nodes)
        check("graph_content", bool(nodes and records), {"nodes": counts, "indexable_components": len(records)})
        validate_graph(settings.db_path, nodes)
        check("graph_provenance", bool(records), {"verified_cores": len(nodes), "verified_components": len(records)})
        check("discipline_coverage", bool(domains) and not domains.get("unresolved"), dict(domains), required=False)
    except Exception as exc:
        # sqlite schema errors are also diagnostics, never instructions to
        # create a replacement database during a read-only check.
        check("graph_readable_or_grounded", False, f"{type(exc).__name__}: {exc}")
    identity = {}
    try:
        identity = model_identity(settings.model_path)
        check("embedding_model", True, {"source": identity["source"], "revision": identity["revision"]})
    except (OSError, ValueError) as exc:
        check("embedding_model", False, str(exc))
    try:
        index, metadata, manifest = read_artifacts(settings.index_dir)
        check("component_index", True, {"vectors": index.ntotal, "dimension": index.d})
        check("index_manifest", bool(manifest), "Versioned manifest present" if manifest else "Legacy index: rebuild to record graph/model identity")
        check("graph_index_version", bool(graph) and manifest.get("graph") == graph,
              {"database": graph, "index": manifest.get("graph")})
        indexed = {r["id"]: r for r in metadata["meta"].values()}
        expected = {r["id"]: r for r in records}
        check("component_membership", indexed == expected, {"expected": len(expected), "indexed": len(indexed)})
        check("model_index_compatibility", bool(identity) and manifest.get("model", {}).get("revision") == identity.get("revision"),
              {"configured_revision": identity.get("revision"), "index_revision": manifest.get("model", {}).get("revision")})
        vectors = [index.reconstruct(int(fid)) for fid in metadata["meta"]]
        norms = np.linalg.norm(np.asarray(vectors), axis=1) if vectors else np.array([])
        check("vector_normalization", bool(len(norms)) and bool(np.all(np.isfinite(norms)) and np.allclose(norms, 1, atol=1e-4)),
              {"checked": len(norms), "normalization": manifest.get("normalization")})
    except Exception as exc:
        check("component_index", False, f"{type(exc).__name__}: {exc}")
    return {"ok": all(c["ok"] for c in checks if c["required"]), "checks": checks,
            "node_counts": counts, "domain_counts": dict(domains),
            "cross_domain_corpus": len(set(domains) - {"unresolved"}) >= 2,
            "paths": {"db_path": str(settings.db_path), "index_dir": str(settings.index_dir),
                      "model_path": str(settings.model_path)}}
