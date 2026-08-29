"""Availability checks and mode selection for Blog Agent literature retrieval."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


_REQUIRED_NODE_COLUMNS = {"id", "label", "node_type", "paper_title"}
_REQUIRED_EDGE_COLUMNS = {"source", "target"}
_VALID_RETRIEVAL_MODES = {"auto", "graph", "semantic", "workspace"}


@dataclass(frozen=True)
class GraphDatabaseStatus:
    """The usability of one local SQLite knowledge-graph database."""

    available: bool
    path: str
    reason: str
    node_count: int | None = None
    core_node_count: int | None = None
    edge_count: int | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "available": self.available,
            "path": self.path,
            "reason": self.reason,
            "node_count": self.node_count,
            "core_node_count": self.core_node_count,
            "edge_count": self.edge_count,
        }


@dataclass(frozen=True)
class RetrievalPlan:
    """The retrieval mode selected for a single Blog Agent workflow."""

    requested_mode: str
    mode: str
    graph: GraphDatabaseStatus
    semantic_scholar_available: bool
    reason: str

    def to_dict(self) -> dict[str, object]:
        return {
            "requested_mode": self.requested_mode,
            "mode": self.mode,
            "reason": self.reason,
            "graph": self.graph.to_dict(),
            "semantic_scholar": {
                "available": self.semantic_scholar_available,
            },
        }


def _readonly_connection(path: Path) -> sqlite3.Connection:
    """Open *path* without allowing SQLite to create a missing database file."""
    return sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)


def inspect_graph_database(db_path: str | Path) -> GraphDatabaseStatus:
    """Return whether a database can serve Blog Agent's graph traversal query.

    The Blog Agent needs usable Core nodes and at least one relationship edge.  The
    function deliberately opens SQLite in read-only mode so an absent path cannot
    silently turn into an empty ``graph.db``.
    """
    raw_path = str(db_path).strip()
    if not raw_path:
        return GraphDatabaseStatus(False, "", "No graph database path was configured.")

    path = Path(raw_path).expanduser()
    display_path = str(path.resolve())
    if not path.exists():
        return GraphDatabaseStatus(False, display_path, "Database file does not exist.")
    if not path.is_file():
        return GraphDatabaseStatus(False, display_path, "Database path is not a regular file.")

    try:
        with _readonly_connection(path) as conn:
            cursor = conn.cursor()
            table_names = {
                row[0]
                for row in cursor.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
            missing_tables = {"nodes", "edges"} - table_names
            if missing_tables:
                return GraphDatabaseStatus(
                    False,
                    display_path,
                    f"Missing required table(s): {', '.join(sorted(missing_tables))}.",
                )

            node_columns = {
                row[1] for row in cursor.execute("PRAGMA table_info(nodes)")
            }
            missing_node_columns = _REQUIRED_NODE_COLUMNS - node_columns
            if missing_node_columns:
                return GraphDatabaseStatus(
                    False,
                    display_path,
                    "nodes is missing required column(s): "
                    f"{', '.join(sorted(missing_node_columns))}.",
                )

            edge_columns = {
                row[1] for row in cursor.execute("PRAGMA table_info(edges)")
            }
            missing_edge_columns = _REQUIRED_EDGE_COLUMNS - edge_columns
            if missing_edge_columns:
                return GraphDatabaseStatus(
                    False,
                    display_path,
                    "edges is missing required column(s): "
                    f"{', '.join(sorted(missing_edge_columns))}.",
                )

            node_count = int(cursor.execute("SELECT COUNT(*) FROM nodes").fetchone()[0])
            core_node_count = int(
                cursor.execute(
                    "SELECT COUNT(*) FROM nodes "
                    "WHERE node_type = 'Core' AND paper_title IS NOT NULL"
                ).fetchone()[0]
            )
            edge_count = int(cursor.execute("SELECT COUNT(*) FROM edges").fetchone()[0])
    except (OSError, sqlite3.Error) as exc:
        return GraphDatabaseStatus(
            False,
            display_path,
            f"SQLite database could not be opened read-only: {exc}",
        )

    if node_count == 0:
        return GraphDatabaseStatus(
            False,
            display_path,
            "nodes table is empty.",
            node_count=node_count,
            core_node_count=core_node_count,
            edge_count=edge_count,
        )
    if core_node_count == 0:
        return GraphDatabaseStatus(
            False,
            display_path,
            "No Core nodes with paper titles are available.",
            node_count=node_count,
            core_node_count=core_node_count,
            edge_count=edge_count,
        )
    if edge_count == 0:
        return GraphDatabaseStatus(
            False,
            display_path,
            "edges table is empty; graph traversal cannot discover related papers.",
            node_count=node_count,
            core_node_count=core_node_count,
            edge_count=edge_count,
        )

    return GraphDatabaseStatus(
        True,
        display_path,
        "Graph database is usable.",
        node_count=node_count,
        core_node_count=core_node_count,
        edge_count=edge_count,
    )


def find_available_graph_database(paths: Iterable[str | Path]) -> GraphDatabaseStatus:
    """Return the first usable graph database among ordered compatibility paths."""
    statuses: list[GraphDatabaseStatus] = []
    seen_paths: set[str] = set()
    for candidate in paths:
        path_key = str(Path(candidate).expanduser().resolve())
        if path_key in seen_paths:
            continue
        seen_paths.add(path_key)
        status = inspect_graph_database(candidate)
        statuses.append(status)
        if status.available:
            return status

    if not statuses:
        return GraphDatabaseStatus(False, "", "No graph database paths were provided.")

    details = "; ".join(f"{status.path}: {status.reason}" for status in statuses)
    first_status = statuses[0]
    return GraphDatabaseStatus(
        False,
        first_status.path,
        f"No usable graph database found. {details}",
        node_count=first_status.node_count,
        core_node_count=first_status.core_node_count,
        edge_count=first_status.edge_count,
    )


def select_retrieval_mode(
    requested_mode: str | None,
    graph_status: GraphDatabaseStatus,
    semantic_scholar_available: bool,
) -> RetrievalPlan:
    """Select graph, Semantic Scholar, or workspace-only retrieval safely."""
    normalized_mode = str(requested_mode or "auto").strip().lower()
    invalid_mode = normalized_mode not in _VALID_RETRIEVAL_MODES
    if invalid_mode:
        normalized_mode = "auto"

    prefix = (
        f"Unknown retrieval mode {requested_mode!r}; treated as 'auto'. "
        if invalid_mode
        else ""
    )
    if normalized_mode == "workspace":
        return RetrievalPlan(
            normalized_mode,
            "workspace",
            graph_status,
            semantic_scholar_available,
            prefix + "Workspace-only retrieval was explicitly requested.",
        )
    if normalized_mode == "semantic":
        if semantic_scholar_available:
            return RetrievalPlan(
                normalized_mode,
                "semantic",
                graph_status,
                True,
                prefix + "Semantic Scholar retrieval was explicitly requested.",
            )
        return RetrievalPlan(
            normalized_mode,
            "workspace",
            graph_status,
            False,
            prefix + "Semantic Scholar API key is unavailable; using workspace evidence only.",
        )
    if normalized_mode == "graph" and graph_status.available:
        return RetrievalPlan(
            normalized_mode,
            "graph",
            graph_status,
            semantic_scholar_available,
            prefix + "Graph retrieval was explicitly requested.",
        )
    if normalized_mode == "auto" and graph_status.available:
        return RetrievalPlan(
            normalized_mode,
            "graph",
            graph_status,
            semantic_scholar_available,
            prefix + "Using the configured graph database.",
        )
    if semantic_scholar_available:
        return RetrievalPlan(
            normalized_mode,
            "semantic",
            graph_status,
            True,
            prefix + f"Graph retrieval is unavailable: {graph_status.reason}",
        )
    return RetrievalPlan(
        normalized_mode,
        "workspace",
        graph_status,
        False,
        prefix
        + "Graph retrieval is unavailable and Semantic Scholar API key is unavailable; "
        "using workspace evidence only.",
    )
