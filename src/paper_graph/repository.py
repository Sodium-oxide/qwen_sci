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


def merge_verified_graph(previous: list[dict[str, Any]], incoming: list[dict[str, Any]]
                        ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    from src.paper_graph.ingest import stable_id

    nodes = {node["node_id"]: node for node in [*previous, *incoming]}
    cores = {identity: node for identity, node in nodes.items() if node["node_type"] == "Core"}
    components = [node for node in nodes.values() if node["node_type"] == "Component" and node["core_id"] in cores]
    papers = {node["paper_id"]: node["node_id"] for node in nodes.values() if node["node_type"] == "Paper"}
    edges = []
    for identity, core in cores.items():
        core = {**core, "components": sorted((node for node in components if node["core_id"] == identity),
                                            key=lambda node: node["node_id"])}
        nodes[identity] = core
        paper = papers[core["paper_id"]]
        edges.append({"id": stable_id("edge", core["paper_id"], identity), "source": paper,
                      "target": identity, "edge_type": "has_contribution"})
        for component in core["components"]:
            edges.append({"id": stable_id("edge", identity, component["node_id"]), "source": identity,
                          "target": component["node_id"], "edge_type": "has_component"})
    retained = [node for node in nodes.values() if node["node_type"] != "Component" or node in components]
    return sorted(retained, key=lambda node: node["node_id"]), sorted(edges, key=lambda edge: edge["id"])


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
        CREATE TABLE IF NOT EXISTS extraction_evidence_repairs (
          repair_id INTEGER PRIMARY KEY AUTOINCREMENT, attempt_id INTEGER NOT NULL,
          round INTEGER NOT NULL, status TEXT NOT NULL, request_json TEXT NOT NULL,
          response_json TEXT, outcome_json TEXT,
          started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          FOREIGN KEY(attempt_id) REFERENCES extraction_attempts(attempt_id));
        CREATE INDEX IF NOT EXISTS evidence_repair_attempt
          ON extraction_evidence_repairs(attempt_id, repair_id);
        CREATE TABLE IF NOT EXISTS extraction_requests (
          request_id INTEGER PRIMARY KEY AUTOINCREMENT, attempt_id INTEGER NOT NULL,
          stage TEXT NOT NULL, round INTEGER NOT NULL, status TEXT NOT NULL,
          request_json TEXT NOT NULL, response_json TEXT, outcome_json TEXT,
          started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          FOREIGN KEY(attempt_id) REFERENCES extraction_attempts(attempt_id));
        CREATE INDEX IF NOT EXISTS extraction_request_attempt
          ON extraction_requests(attempt_id, request_id);
        """)
        conn.execute("INSERT OR IGNORE INTO graph_state VALUES ('schema_version', ?)", (str(SCHEMA_VERSION),))
        conn.execute("INSERT OR IGNORE INTO graph_state VALUES ('revision', '0')")

    def replace_paper(self, paper_id: str, nodes: list[dict[str, Any]], edges: list[dict[str, Any]],
                      payload: dict[str, Any], reasons: list[str], *, authoritative: bool = True,
                      expected_queue_hash: str | None = None, extraction_attempt_id: int | None = None,
                      partial_import: bool = False, queue_input: dict[str, Any] | None = None,
                      extraction_error: dict[str, Any] | None = None) -> dict[str, Any]:
        content_hash = digest([nodes, edges])
        candidate_verification = payload.get("candidate_verification", [])
        # Retaining verified graph structure must not replace the queue's latest
        # input with a prior import when a new incomplete record arrives.
        queue_payload = queue_input if queue_input is not None else payload
        with self.write() as conn:
            if expected_queue_hash is not None:
                queued = conn.execute("SELECT status,payload_json FROM extraction_queue WHERE paper_id=?",
                                      (paper_id,)).fetchone()
                if (queued is None or queued["status"] not in {"pending", "partial"}
                        or digest(json.loads(queued["payload_json"])) != expected_queue_hash):
                    raise QueueChangedError(f"Queue input changed during extraction: {paper_id}; rerun with the current input.")
            old = conn.execute("SELECT content_hash,payload_json FROM paper_imports WHERE paper_id=?", (paper_id,)).fetchone()
            if old and not authoritative:
                previous = json.loads(old["payload_json"])
                old_sources = {d["source_id"]: d["sha256"] for d in previous.get("source_documents", [])}
                new_sources = {d["source_id"]: d["sha256"] for d in payload.get("source_documents", [])}
                if not new_sources or old_sources == new_sources:
                    # Bibliographic/keynote updates do not delete extracted cores.
                    previous_nodes = [json.loads(r[0]) for r in conn.execute(
                        "SELECT raw_json FROM nodes WHERE paper_id=?", (paper_id,))]
                    if partial_import and old_sources == new_sources:
                        nodes, edges = merge_verified_graph(previous_nodes, nodes)
                        content_hash = digest([nodes, edges])
                    else:
                        nodes = previous_nodes
                        ids = {node["node_id"] for node in nodes}
                        edges = [json.loads(row["raw_json"]) for row in conn.execute("SELECT * FROM edges")
                                 if row["source"] in ids and row["target"] in ids]
                        payload = {**previous, "latest_incomplete_input":
                                   {key: value for key, value in payload.items() if key != "latest_incomplete_input"}}
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
            status = "partial" if reasons and any(node["node_type"] == "Core" for node in nodes) else (
                "pending" if reasons else "succeeded")
            conn.execute("""INSERT INTO extraction_queue(paper_id,status,reasons_json,payload_json) VALUES(?,?,?,?)
                ON CONFLICT(paper_id) DO UPDATE SET status=excluded.status,reasons_json=excluded.reasons_json,
                payload_json=excluded.payload_json,updated_at=CURRENT_TIMESTAMP""",
                (paper_id, "resolved" if status == "succeeded" else status, json_text(reasons), json_text(queue_payload)))
            result = {"paper_id": paper_id, "changed": changed, "status": status,
                      "cores": sum(n["node_type"] == "Core" for n in nodes),
                      "components": sum(n["node_type"] == "Component" for n in nodes), "pending_reasons": reasons}
            if reasons:
                result["candidates"] = [candidate for candidate in candidate_verification
                                        if candidate["verification_status"] != "verified"]
            if extraction_attempt_id is not None:
                # A committed graph import and its successful checkpoint are
                # inseparable, including if the executor dies after this call.
                cursor = conn.execute("UPDATE extraction_attempts SET status=?,stage='complete',"
                                      "result_json=?,error_json=?,updated_at=CURRENT_TIMESTAMP "
                                      "WHERE attempt_id=? AND paper_id=? AND status='running' AND stage='ingestion'",
                                      (status, json_text(result), json_text(extraction_error) if reasons and extraction_error else None,
                                       extraction_attempt_id, paper_id))
                if cursor.rowcount != 1:
                    raise ValueError(f"No running ingestion attempt {extraction_attempt_id} for {paper_id}")
        return result

    def pending(self) -> list[dict[str, Any]]:
        conn = readonly_connection(self.db_path)
        try:
            has_attempts = conn.execute("SELECT 1 FROM sqlite_master WHERE name='extraction_attempts'").fetchone()
            pending = []
            for row in conn.execute("SELECT * FROM extraction_queue WHERE status IN ('pending','partial') ORDER BY paper_id"):
                item = {"paper_id": row["paper_id"], "status": row["status"], "reasons": json.loads(row["reasons_json"]),
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

    def start_evidence_repair(self, attempt_id: int, round_number: int, request: dict[str, Any]) -> int:
        with self.write() as conn:
            conn.execute("UPDATE extraction_attempts SET stage='evidence_repair',updated_at=CURRENT_TIMESTAMP "
                         "WHERE attempt_id=?", (attempt_id,))
            cursor = conn.execute("INSERT INTO extraction_evidence_repairs(attempt_id,round,status,request_json) "
                                  "VALUES(?,?,'running',?)", (attempt_id, round_number, json_text(request)))
            return cursor.lastrowid

    def save_evidence_repair_response(self, repair_id: int, response: Any) -> None:
        with self.write() as conn:
            conn.execute("UPDATE extraction_evidence_repairs SET status='received',response_json=?,"
                         "updated_at=CURRENT_TIMESTAMP WHERE repair_id=?", (json_text(response), repair_id))

    def finish_evidence_repair(self, repair_id: int, attempt_id: int, output: dict[str, Any],
                               outcome: dict[str, Any]) -> None:
        # A useful partial patch and its event become durable together before
        # another entity is sent to the model. Earlier extraction stays intact.
        with self.write() as conn:
            conn.execute("UPDATE extraction_evidence_repairs SET status=?,outcome_json=?,updated_at=CURRENT_TIMESTAMP "
                         "WHERE repair_id=? AND attempt_id=?", (outcome["status"], json_text(outcome), repair_id, attempt_id))
            conn.execute("UPDATE extraction_attempts SET stage='evidence_verification',output_json=?,"
                         "updated_at=CURRENT_TIMESTAMP WHERE attempt_id=?", (json_text(output), attempt_id))

    def delete_paper(self, paper_id: str) -> None:
        # Keep deletion in the same revision stream as imports. Index builds
        # reconcile the full active snapshot, so removed vectors cannot survive.
        self.replace_paper(paper_id, [], [], {"paper_id": paper_id, "deleted": True}, [])

    def start_extraction_request(self, attempt_id: int, stage: str, round_number: int,
                                 request: dict[str, Any]) -> int:
        with self.write() as conn:
            conn.execute("UPDATE extraction_attempts SET stage=?,updated_at=CURRENT_TIMESTAMP WHERE attempt_id=?",
                         (stage, attempt_id))
            cursor = conn.execute("INSERT INTO extraction_requests(attempt_id,stage,round,status,request_json) "
                                  "VALUES(?,?,?,'running',?)", (attempt_id, stage, round_number, json_text(request)))
            return cursor.lastrowid

    def save_extraction_response(self, request_id: int, response: Any) -> None:
        with self.write() as conn:
            conn.execute("UPDATE extraction_requests SET status='received',response_json=?,"
                         "updated_at=CURRENT_TIMESTAMP WHERE request_id=?", (json_text(response), request_id))

    def finish_extraction_request(self, request_id: int, attempt_id: int, outcome: dict[str, Any],
                                  *, output: dict[str, Any] | None = None) -> None:
        with self.write() as conn:
            conn.execute("UPDATE extraction_requests SET status=?,outcome_json=?,updated_at=CURRENT_TIMESTAMP "
                         "WHERE request_id=? AND attempt_id=?", (outcome["status"], json_text(outcome), request_id, attempt_id))
            if output is not None:
                conn.execute("UPDATE extraction_attempts SET output_json=?,updated_at=CURRENT_TIMESTAMP WHERE attempt_id=?",
                             (json_text(output), attempt_id))

    def latest_main_state(self, attempt_id: int) -> dict[str, Any] | None:
        conn = readonly_connection(self.db_path)
        try:
            if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='extraction_requests'").fetchone():
                return None
            row = conn.execute("SELECT request.* FROM extraction_requests request "
                               "JOIN extraction_attempts previous ON previous.attempt_id=request.attempt_id "
                               "JOIN extraction_attempts current ON current.attempt_id=? "
                               "WHERE previous.paper_id=current.paper_id AND previous.input_hash=current.input_hash "
                               "AND previous.attempt_id<=current.attempt_id "
                               "AND request.stage IN ('extraction','extraction_json_repair') "
                               "ORDER BY request.request_id DESC LIMIT 1", (attempt_id,)).fetchone()
            if row is None:
                return None
            outcome = json.loads(row["outcome_json"]) if row["outcome_json"] else {}
            state = outcome.get("repair_state")
            if state is not None:
                return state
            request = json.loads(row["request_json"])
            if row["response_json"] is not None:
                response = json.loads(row["response_json"])
                return {"received_response": response, "previous_state": request.get("repair_state")}
            return request.get("repair_state")
        finally:
            conn.close()
