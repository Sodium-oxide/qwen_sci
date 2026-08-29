from __future__ import annotations

import sqlite3

from src.agents.blog_agent.utils.retrieval import (
    GraphDatabaseStatus,
    inspect_graph_database,
    select_retrieval_mode,
)
from src.agents.blog_agent.utils.search_core import get_core_nodes_within_hops
from src.agents.blog_agent.utils import semantic_scholar


def _create_usable_graph(path) -> None:
    with sqlite3.connect(path) as conn:
        conn.executescript(
            """
            CREATE TABLE nodes (
                id TEXT PRIMARY KEY,
                label TEXT NOT NULL,
                node_type TEXT NOT NULL,
                paper_title TEXT
            );
            CREATE TABLE edges (
                source TEXT NOT NULL,
                target TEXT NOT NULL
            );
            """
        )
        conn.executemany(
            "INSERT INTO nodes (id, label, node_type, paper_title) VALUES (?, ?, ?, ?)",
            [
                ("topic-memory", "agent memory", "Topic", None),
                ("paper-1", "Memory Paper", "Core", "A Useful Memory Paper"),
            ],
        )
        conn.execute(
            "INSERT INTO edges (source, target) VALUES (?, ?)",
            ("topic-memory", "paper-1"),
        )


def test_missing_graph_is_unavailable_without_creating_an_empty_database(tmp_path):
    missing_path = tmp_path / "missing-graph.db"

    status = inspect_graph_database(missing_path)
    result = get_core_nodes_within_hops("agent memory", db_path=str(missing_path))

    assert not status.available
    assert status.reason == "Database file does not exist."
    assert result["status"] == "unavailable"
    assert not missing_path.exists()


def test_empty_graph_database_falls_back_instead_of_querying_missing_tables(tmp_path):
    empty_path = tmp_path / "empty-graph.db"
    sqlite3.connect(empty_path).close()

    status = inspect_graph_database(empty_path)
    result = get_core_nodes_within_hops("agent memory", db_path=str(empty_path))

    assert not status.available
    assert "Missing required table(s): edges, nodes." in status.reason
    assert result["status"] == "unavailable"
    assert "Use Semantic Scholar instead" in result["detail"]


def test_valid_graph_can_still_find_related_core_papers(tmp_path):
    graph_path = tmp_path / "graph.db"
    _create_usable_graph(graph_path)

    status = inspect_graph_database(graph_path)
    result = get_core_nodes_within_hops("agent memory", db_path=str(graph_path))

    assert status.available
    assert result == {
        "status": "success",
        "detail": "Found 1 paper titles (hop1: 1)",
        "results": [
            {
                "id": "paper-1",
                "paper_title": "A Useful Memory Paper",
                "hops": 1,
            }
        ],
    }


def test_auto_mode_selects_graph_then_semantic_then_workspace():
    usable_graph = GraphDatabaseStatus(True, "/tmp/graph.db", "Graph database is usable.")
    unavailable_graph = GraphDatabaseStatus(False, "/tmp/graph.db", "Database file does not exist.")

    assert select_retrieval_mode("auto", usable_graph, False).mode == "graph"
    assert select_retrieval_mode("auto", unavailable_graph, True).mode == "semantic"
    assert select_retrieval_mode("auto", unavailable_graph, False).mode == "workspace"
    assert select_retrieval_mode("semantic", usable_graph, True).mode == "semantic"
    assert select_retrieval_mode("semantic", usable_graph, False).mode == "workspace"


def test_semantic_search_returns_a_bounded_candidate_set(monkeypatch):
    class _Response:
        status_code = 200

        @staticmethod
        def json():
            return {
                "data": [
                    {
                        "paperId": "paper-a",
                        "title": "First Candidate",
                        "abstract": "First abstract",
                        "year": 2025,
                        "authors": [{"name": "Ada"}],
                        "venue": "TestConf",
                        "url": "https://example.com/a",
                    },
                    {
                        "paperId": "paper-b",
                        "title": "Second Candidate",
                        "abstract": None,
                        "year": 2024,
                        "authors": [{"name": "Grace"}],
                        "venue": "TestConf",
                        "url": "https://example.com/b",
                    },
                ]
            }

    requested_params = {}

    def _fake_get(_url, **kwargs):
        requested_params.update(kwargs["params"])
        return _Response()

    monkeypatch.setattr(semantic_scholar.requests, "get", _fake_get)

    result = semantic_scholar.search_paper_and_get_abstract(
        "agent memory",
        api_key="test-key",
        max_results=2,
    )

    assert requested_params["limit"] == 5
    assert result["status"] == "success"
    assert result["paper"]["paper_id"] == "paper-a"
    assert [paper["paper_id"] for paper in result["papers"]] == ["paper-a", "paper-b"]
