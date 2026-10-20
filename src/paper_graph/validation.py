"""Explicit index publication and retrieval checks after supplementary extraction."""
from __future__ import annotations

from typing import Any

from src.paper_graph.health import check_paper_graph
from src.paper_graph.indexing import GraphCoreComponentIndexer, component_records
from src.paper_graph.repository import core_snapshot
from src.paper_graph.settings import PaperGraphSettings


def check_retrieval(settings: PaperGraphSettings, queries: list[str] | None = None, *,
                    top_k: int = 5, model: Any = None) -> dict[str, Any]:
    """Run the production vector store; a summary smoke query tests plumbing only."""
    if top_k < 1:
        raise ValueError("Retrieval --top-k must be positive")
    automatic = queries is None
    queries = [q.strip() for q in queries or [] if q.strip()]
    if automatic:
        records = component_records(core_snapshot(settings.db_path)[0])
        queries = [records[0]["component_summary"]] if records else []
    if not queries:
        return {"ok": False, "status": "skipped", "reason": "no_query_or_indexable_components"}
    try:
        from src.agents.idea_agent.utils.papers.paper_graph_vector_store import PaperGraphComponentVectorStore
        store = PaperGraphComponentVectorStore(config={"paper_graph": vars(settings)}, model=model).load()
        results = []
        for query in queries:
            hits = store.search(query, top_k=top_k, component_hits_per_core=1)
            results.append({"query": query, "query_source": "component_summary_smoke" if automatic else "user",
                "ok": bool(hits), "hit_count": len(hits), "hits": [
                    {"node_id": h["node_id"], "score": h["score"],
                     "paper_id": h["core_node"].get("paper_id"),
                     "paper_title": h["core_node"].get("paper_title"),
                     "paper_domain": h["core_node"].get("paper_domain"),
                     "matched_components": h["matched_components"],
                     "evidence_records": h["core_node"].get("evidence_records", [])}
                    for h in hits]})
        return {"ok": all(r["ok"] for r in results), "status": "checked", "results": results}
    except Exception as exc:
        return {"ok": False, "status": "failed", "error": {"type": type(exc).__name__, "message": str(exc)}}


def build_and_check(settings: PaperGraphSettings, *, queries: list[str] | None = None,
                    top_k: int = 5, batch_size: int = 8, fetch_size: int = 16,
                    rebuild: bool = False, model: Any = None) -> dict[str, Any]:
    """Preserve extraction outcomes even if publication or querying fails later."""
    result: dict[str, Any] = {}
    try:
        records = component_records(core_snapshot(settings.db_path)[0])
        if not records:
            result["index"] = {"ok": False, "status": "skipped", "reason": "no_indexable_components"}
        else:
            indexer = GraphCoreComponentIndexer(settings.db_path, settings.index_dir, settings.model_path,
                                                fetch_size=fetch_size, model=model)
            # An extraction limit must never turn into a partial index build.
            result["index"] = {"ok": True, "status": "built", **indexer.build(batch_size=batch_size, rebuild=rebuild)}
            model = indexer._model  # Reuse an encoder loaded by the build.
    except Exception as exc:
        result["index"] = {"ok": False, "status": "failed", "error": {"type": type(exc).__name__, "message": str(exc)}}
    try:
        result["health"] = check_paper_graph(settings)
    except Exception as exc:
        result["health"] = {"ok": False, "error": {"type": type(exc).__name__, "message": str(exc)}}
    if result["index"]["ok"] and result["health"]["ok"]:
        result["retrieval"] = check_retrieval(settings, queries, top_k=top_k, model=model)
    else:
        result["retrieval"] = {"ok": False, "status": "skipped", "reason": "graph_or_index_not_ready"}
    result["ok"] = all(result[k]["ok"] for k in ("index", "health", "retrieval"))
    return result
