"""Transactional graph writes; readers never create a missing SQLite file."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

SCHEMA_VERSION = 1


class QueueChangedError(RuntimeError):
    """The source queue entry changed while an extraction was in flight."""


def json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(value: Any) -> str:
    return hashlib.sha256(json_text(value).encode("utf-8")).hexdigest()


def readonly_connection(db_path: Path | str) -> sqlite3.Connection:
    path = Path(db_path).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Paper graph database not found: {path}")
    conn = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def core_snapshot(db_path: Path | str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    conn = readonly_connection(db_path)
    try:
        conn.execute("BEGIN")
        rows = conn.execute("SELECT id, raw_json FROM nodes WHERE node_type='Core' ORDER BY id").fetchall()
        nodes = [{**json.loads(row["raw_json"]), "node_id": row["id"]} for row in rows]
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        state = dict(conn.execute("SELECT key, value FROM graph_state").fetchall()) if "graph_state" in tables else {}
        return nodes, {"schema_version": int(state.get("schema_version", 0)),
                       "revision": int(state.get("revision", 0)), "fingerprint": digest(nodes)}
    finally:
        conn.close()


class PaperGraphRepository:
    def __init__(self, db_path: Path | str) -> None:
        self.db_path = Path(db_path).expanduser().resolve()

    @contextmanager
    def write(self) -> Iterator[sqlite3.Connection]:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA foreign_keys=ON")
            self._schema(conn)
            conn.commit()
            conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    @staticmethod
    def _schema(conn: sqlite3.Connection) -> None:
        required = {"nodes": {"id", "node_type", "paper_id", "paper_title", "pub_year", "source_venue",
                              "full_name", "acronym", "summary", "raw_json"},
                    "edges": {"id", "source", "target", "edge_type", "raw_json"}}
        for table, fields in required.items():
            columns = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
            if columns and not fields <= columns:
                raise ValueError(f"Incompatible legacy {table} schema; import into a new paper_graph.db_path.")
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS nodes (
          id TEXT PRIMARY KEY, node_type TEXT NOT NULL, paper_id TEXT NOT NULL,
          paper_title TEXT, pub_year TEXT, source_venue TEXT, full_name TEXT,
          acronym TEXT, summary TEXT, raw_json TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS nodes_paper ON nodes(paper_id);
        CREATE TABLE IF NOT EXISTS edges (
          id TEXT PRIMARY KEY, source TEXT NOT NULL, target TEXT NOT NULL,
          edge_type TEXT NOT NULL, summary TEXT, keywords TEXT, insight TEXT, raw_json TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS edges_source ON edges(source);
        CREATE INDEX IF NOT EXISTS edges_target ON edges(target);
        CREATE TABLE IF NOT EXISTS aliases (alias TEXT, normalized_alias TEXT, target_id TEXT,
          UNIQUE(normalized_alias, target_id));
        CREATE VIRTUAL TABLE IF NOT EXISTS node_fts USING fts5(id UNINDEXED, full_name, paper_title, summary);
        CREATE TABLE IF NOT EXISTS graph_state (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS paper_imports (paper_id TEXT PRIMARY KEY, content_hash TEXT NOT NULL,
          payload_json TEXT NOT NULL, imported_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS extraction_queue (
          paper_id TEXT PRIMARY KEY, status TEXT NOT NULL, reasons_json TEXT NOT NULL,
          payload_json TEXT NOT NULL, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS extraction_attempts (
          attempt_id INTEGER PRIMARY KEY AUTOINCREMENT, paper_id TEXT NOT NULL,
          input_hash TEXT NOT NULL, status TEXT NOT NULL, stage TEXT NOT NULL,
          output_json TEXT, error_json TEXT, result_json TEXT,
          started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
        CREATE INDEX IF NOT EXISTS extraction_attempt_paper
          ON extraction_attempts(paper_id, attempt_id);
        """)
        conn.execute("INSERT OR IGNORE INTO graph_state VALUES ('schema_version', ?)", (str(SCHEMA_VERSION),))
        conn.execute("INSERT OR IGNORE INTO graph_state VALUES ('revision', '0')")

    def replace_paper(self, paper_id: str, nodes: list[dict[str, Any]], edges: list[dict[str, Any]],
                      payload: dict[str, Any], reasons: list[str], *, authoritative: bool = True,
                      expected_queue_hash: str | None = None, extraction_attempt_id: int | None = None) -> dict[str, Any]:
        content_hash = digest([nodes, edges])
        # Retaining verified graph structure must not replace the queue's latest
        # input with a prior import when a new incomplete record arrives.
        queue_payload = payload
        with self.write() as conn:
            if expected_queue_hash is not None:
                queued = conn.execute("SELECT status,payload_json FROM extraction_queue WHERE paper_id=?",
                                      (paper_id,)).fetchone()
                if (queued is None or queued["status"] != "pending"
                        or digest(json.loads(queued["payload_json"])) != expected_queue_hash):
                    raise QueueChangedError(f"Queue input changed during extraction: {paper_id}; rerun with the current input.")
            old = conn.execute("SELECT content_hash,payload_json FROM paper_imports WHERE paper_id=?", (paper_id,)).fetchone()
            if old and not authoritative:
                previous = json.loads(old["payload_json"])
                old_sources = {d["source_id"]: d["sha256"] for d in previous.get("source_documents", [])}
                new_sources = {d["source_id"]: d["sha256"] for d in payload.get("source_documents", [])}
                if not new_sources or old_sources == new_sources:
                    # Bibliographic/keynote updates do not delete extracted cores.
                    nodes = [json.loads(r[0]) for r in conn.execute("SELECT raw_json FROM nodes WHERE paper_id=?", (paper_id,))]
                    ids = {n["node_id"] for n in nodes}
                    edges = [json.loads(r["raw_json"]) for r in conn.execute("SELECT * FROM edges")
                             if r["source"] in ids and r["target"] in ids]
                    payload = {**previous, "latest_incomplete_input":
                               {k: v for k, v in payload.items() if k != "latest_incomplete_input"}}
                    content_hash = old["content_hash"]
            changed = old is None or old[0] != content_hash
            if changed:
                ids = [r[0] for r in conn.execute("SELECT id FROM nodes WHERE paper_id=?", (paper_id,))]
                for node_id in ids:
                    conn.execute("DELETE FROM edges WHERE source=? OR target=?", (node_id, node_id))
                    conn.execute("DELETE FROM aliases WHERE target_id=?", (node_id,))
                    conn.execute("DELETE FROM node_fts WHERE id=?", (node_id,))
                conn.execute("DELETE FROM nodes WHERE paper_id=?", (paper_id,))
                for node in nodes:
                    name = node.get("full_name") or node.get("name") or node.get("label") or node["node_id"]
                    conn.execute("""INSERT INTO nodes(id,node_type,paper_id,paper_title,pub_year,source_venue,
                      full_name,acronym,summary,raw_json) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                        (node["node_id"], node["node_type"], paper_id, node.get("paper_title", ""),
                         str(node.get("pub_year") or ""), node.get("source_venue", ""), name,
                         node.get("acronym", ""), node.get("summary", ""), json_text(node)))
                    conn.execute("INSERT INTO node_fts VALUES(?,?,?,?)",
                                 (node["node_id"], name, node.get("paper_title", ""), node.get("summary", "")))
                    norm = "".join(c for c in name.lower() if c.isalnum() or c == "+")
                    conn.execute("INSERT OR IGNORE INTO aliases VALUES(?,?,?)", (name, norm, node["node_id"]))
                for edge in edges:
                    conn.execute("INSERT INTO edges(id,source,target,edge_type,raw_json) VALUES(?,?,?,?,?)",
                                 (edge["id"], edge["source"], edge["target"], edge["edge_type"], json_text(edge)))
                conn.execute("UPDATE graph_state SET value=CAST(value AS INTEGER)+1 WHERE key='revision'")
            conn.execute("""INSERT INTO paper_imports(paper_id,content_hash,payload_json) VALUES(?,?,?)
                ON CONFLICT(paper_id) DO UPDATE SET content_hash=excluded.content_hash,
                payload_json=excluded.payload_json,imported_at=CURRENT_TIMESTAMP""", (paper_id, content_hash, json_text(payload)))
            conn.execute("""INSERT INTO extraction_queue(paper_id,status,reasons_json,payload_json) VALUES(?,?,?,?)
                ON CONFLICT(paper_id) DO UPDATE SET status=excluded.status,reasons_json=excluded.reasons_json,
                payload_json=excluded.payload_json,updated_at=CURRENT_TIMESTAMP""",
                (paper_id, "pending" if reasons else "resolved", json_text(reasons), json_text(queue_payload)))
            result = {"paper_id": paper_id, "changed": changed,
                      "cores": sum(n["node_type"] == "Core" for n in nodes),
                      "components": sum(n["node_type"] == "Component" for n in nodes), "pending_reasons": reasons}
            if extraction_attempt_id is not None:
                # A committed graph import and its successful checkpoint are
                # inseparable, including if the executor dies after this call.
                cursor = conn.execute("UPDATE extraction_attempts SET status='succeeded',stage='complete',"
                                      "result_json=?,error_json=NULL,updated_at=CURRENT_TIMESTAMP "
                                      "WHERE attempt_id=? AND paper_id=? AND status='running' AND stage='ingestion'",
                                      (json_text(result), extraction_attempt_id, paper_id))
                if cursor.rowcount != 1:
                    raise ValueError(f"No running ingestion attempt {extraction_attempt_id} for {paper_id}")
        return result

    def pending(self) -> list[dict[str, Any]]:
        conn = readonly_connection(self.db_path)
        try:
            has_attempts = conn.execute("SELECT 1 FROM sqlite_master WHERE name='extraction_attempts'").fetchone()
            pending = []
            for row in conn.execute("SELECT * FROM extraction_queue WHERE status='pending' ORDER BY paper_id"):
                item = {"paper_id": row["paper_id"], "reasons": json.loads(row["reasons_json"]),
                        "input": json.loads(row["payload_json"])}
                attempt = conn.execute("SELECT * FROM extraction_attempts WHERE paper_id=? ORDER BY attempt_id DESC LIMIT 1",
                                       (row["paper_id"],)).fetchone() if has_attempts else None
                item["execution"] = self._attempt_value(attempt, include_output=False)
                pending.append(item)
            return pending
        finally:
            conn.close()

    @staticmethod
    def _attempt_value(row: sqlite3.Row | None, *, include_output: bool = True) -> dict[str, Any] | None:
        if row is None:
            return None
        value = {k: row[k] for k in ("attempt_id", "paper_id", "input_hash", "status", "stage", "started_at", "updated_at")}
        value.update({key: json.loads(row[key + "_json"]) if row[key + "_json"] is not None else None
                      for key in ("error", "result")})
        value["has_output"] = row["output_json"] is not None
        if include_output:
            value["output"] = json.loads(row["output_json"]) if value["has_output"] else None
        return value

    def latest_attempt(self, paper_id: str, input_hash: str) -> dict[str, Any] | None:
        conn = readonly_connection(self.db_path)
        try:
            if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='extraction_attempts'").fetchone():
                return None
            row = conn.execute("SELECT * FROM extraction_attempts WHERE paper_id=? AND input_hash=? "
                               "ORDER BY attempt_id DESC LIMIT 1", (paper_id, input_hash)).fetchone()
            return self._attempt_value(row)
        finally:
            conn.close()

    def start_attempt(self, paper_id: str, input_hash: str) -> int:
        with self.write() as conn:
            cursor = conn.execute("INSERT INTO extraction_attempts(paper_id,input_hash,status,stage) VALUES(?,?,'running','source_validation')",
                                  (paper_id, input_hash))
            return cursor.lastrowid

    def checkpoint_attempt(self, attempt_id: int, *, status: str = "running", stage: str,
                           output: dict[str, Any] | None = None, error: dict[str, Any] | None = None,
                           result: dict[str, Any] | None = None) -> None:
        with self.write() as conn:
            conn.execute("UPDATE extraction_attempts SET status=?,stage=?,output_json=COALESCE(?,output_json),"
                         "error_json=?,result_json=COALESCE(?,result_json),updated_at=CURRENT_TIMESTAMP WHERE attempt_id=?",
                         (status, stage, json_text(output) if output is not None else None,
                          json_text(error) if error is not None else None,
                          json_text(result) if result is not None else None, attempt_id))

    def delete_paper(self, paper_id: str) -> None:
        # Keep deletion in the same revision stream as imports. Index builds
        # reconcile the full active snapshot, so removed vectors cannot survive.
        self.replace_paper(paper_id, [], [], {"paper_id": paper_id, "deleted": True}, [])
