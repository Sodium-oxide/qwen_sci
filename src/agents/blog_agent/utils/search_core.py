import sqlite3
import os
from collections import deque
from pathlib import Path
from typing import Dict, Any

from .retrieval import inspect_graph_database

# DB_PATH relative to this file's location
_CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(_CURRENT_DIR, "graph.db")
_configured_db_path: str | None = None


def configure_graph_database(db_path: str | None) -> None:
    """Set the validated graph path selected for the current Blog workflow."""
    global _configured_db_path
    _configured_db_path = db_path


def _active_database_path(db_path: str | None = None) -> str:
    return (
        db_path
        or _configured_db_path
        or os.environ.get("BLOG_AGENT_GRAPH_DB_PATH")
        or DB_PATH
    )


def _unavailable_result(reason: str) -> Dict[str, Any]:
    return {
        "status": "unavailable",
        "detail": f"Knowledge graph is unavailable: {reason} Use Semantic Scholar instead.",
        "results": [],
    }


def get_core_nodes_within_hops(
    root_label: str,
    max_hops: int = 3,
    db_path: str | None = None,
) -> Dict[str, Any]:
    """
    Search for Core nodes within N hops from a root node.

    Returns:
        Dict with:
        - status: "success" or "fail"
        - detail: str - fail reason with optional query, or hop statistics on success
        - results: List[Dict] - only present on success, each dict has id, paper_title, hops
    """
    database_path = _active_database_path(db_path)
    database_status = inspect_graph_database(database_path)
    if not database_status.available:
        return _unavailable_result(database_status.reason)

    try:
        db_uri = f"{Path(database_status.path).resolve().as_uri()}?mode=ro"
        conn = sqlite3.connect(db_uri, uri=True)
        try:
            cur = conn.cursor()

            # 1. Find root node (supports exact and fuzzy matching)
            cur.execute("SELECT id, label FROM nodes WHERE label = ?", (root_label,))
            root_row = cur.fetchone()

            if not root_row:
                # Exact match not found, try fuzzy matching
                cur.execute("SELECT id, label FROM nodes WHERE label LIKE ?", (f"%{root_label}%",))
                matches = cur.fetchall()
                if not matches:
                    return {
                        "status": "fail",
                        "detail": f"Node not found: {root_label}",
                        "results": []
                    }
                if len(matches) > 1:
                    match_list = "\n".join([f"- {mlabel}" for _, mlabel in matches[:10]])
                    return {
                        "status": "fail",
                        "detail": f"Multiple matches found for '{root_label}', please specify a more precise name:\n{match_list}\n\nQuery: {root_label}",
                        "results": []
                    }
                root_row = matches[0]

            root_id, root_label = root_row

            # 2. Fast BFS phase: build relationship graph in memory only
            # Use node_hop_map to track visited nodes and their shortest hop distance
            visited = {root_id}
            queue = deque([(root_id, 0)])
            node_hop_map = {}

            while queue:
                curr_id, curr_hop = queue.popleft()
                if curr_hop >= max_hops:
                    continue

                # Combined query: fetch all neighbors at once to reduce SQL execution
                cur.execute("""
                    SELECT target FROM edges WHERE source = ?
                    UNION
                    SELECT source FROM edges WHERE target = ?
                """, (curr_id, curr_id))

                for (neighbor_id,) in cur.fetchall():
                    if neighbor_id not in visited:
                        visited.add(neighbor_id)
                        node_hop_map[neighbor_id] = curr_hop + 1
                        queue.append((neighbor_id, curr_hop + 1))

            # 3. Batch fetch phase: only query Core nodes with titles
            if not node_hop_map:
                return {
                    "status": "fail",
                    "detail": f"No Core nodes found within {max_hops} hops from '{root_label}'",
                    "results": []
                }

            target_ids = list(node_hop_map.keys())
            placeholders = ', '.join(['?'] * len(target_ids))
            query = f"""
                SELECT id, paper_title
                FROM nodes
                WHERE node_type = 'Core'
                  AND paper_title IS NOT NULL
                  AND id IN ({placeholders})
            """
            cur.execute(query, target_ids)

            # Assemble results
            core_nodes = []
            for row_id, title in cur.fetchall():
                core_nodes.append({
                    "id": row_id,
                    "paper_title": title,
                    "hops": node_hop_map[row_id]
                })
        finally:
            conn.close()
    except (OSError, sqlite3.Error) as exc:
        return _unavailable_result(f"SQLite query failed: {exc}")

    # 4. Sort and statistics
    core_nodes.sort(key=lambda x: x["hops"])
    final_results = core_nodes[:100]

    hop_counts = {}
    for node in final_results:
        h = node["hops"]
        hop_counts[h] = hop_counts.get(h, 0) + 1

    stats_str = ", ".join([f"hop{k}: {v}" for k, v in sorted(hop_counts.items())])

    return {
        "status": "success",
        "detail": f"Found {len(final_results)} paper titles ({stats_str})",
        "results": final_results
    }
