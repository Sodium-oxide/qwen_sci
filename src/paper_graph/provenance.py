"""Verify graph evidence against the exact locally retained source text."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from src.paper_graph.ingest import _section_span, stable_id
from src.paper_graph.repository import SCHEMA_VERSION, digest, readonly_connection


def file_signature(path: str | Path) -> tuple[int, int, int]:
    stat = Path(path).stat()
    return stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns


def validate_graph(db_path: str | Path, cores: list[dict[str, Any]]) -> dict[str, tuple[int, int, int]]:
    """Raise on an ungrounded legacy node, dangling edge or stale source.

    Return signatures for the files actually read so runtime searches can
    detect changes without rereading the full corpus on every query.
    """
    conn = readonly_connection(db_path)
    try:
        conn.execute("BEGIN")
        state = dict(conn.execute("SELECT key,value FROM graph_state"))
        if int(state.get("schema_version", 0)) != SCHEMA_VERSION:
            raise ValueError("Unsupported graph schema; reimport structured paper extractions.")
        all_nodes = {r["id"]: json.loads(r["raw_json"]) for r in conn.execute("SELECT id,raw_json FROM nodes")}
        edges = [(r["source"], r["target"], r["edge_type"]) for r in conn.execute("SELECT source,target,edge_type FROM edges")]
    finally:
        conn.close()
    if any(source not in all_nodes or target not in all_nodes for source, target, _ in edges):
        raise ValueError("Paper graph contains dangling edges.")
    papers = {n["paper_id"]: n for n in all_nodes.values() if n.get("node_type") == "Paper"}
    signatures: dict[str, tuple[int, int, int]] = {}
    sources: dict[tuple[str, str], tuple[dict[str, Any], str]] = {}
    active_components = set()
    expected_edges = set()

    def verify(node: dict[str, Any], paper: dict[str, Any]) -> None:
        records = node.get("evidence_records")
        if not isinstance(records, list) or not records:
            raise ValueError(f"Missing verified evidence: {node.get('node_id')}")
        by_id = {s["source_id"]: s for s in paper.get("source_documents", [])}
        for record in records:
            source_id = record.get("source_id")
            key = (paper["paper_id"], source_id)
            if key not in sources:
                source = by_id.get(source_id)
                if not source:
                    raise ValueError(f"Evidence source is absent from its Paper: {source_id}")
                path = source.get("path")
                if path:
                    before = file_signature(path)
                    body = Path(path).read_text(encoding="utf-8")
                    after = file_signature(path)
                    if before != after:
                        raise ValueError(f"Source changed while reading: {path}")
                    signatures[path] = after
                else:
                    body = source.get("text") or ""
                sha = hashlib.sha256(body.encode("utf-8")).hexdigest()
                if not body or sha != source.get("sha256"):
                    raise ValueError(f"Paper source checksum mismatch: {path or source_id}")
                sources[key] = source, body
            source, body = sources[key]
            loc = record.get("locator") or {}
            quote = record.get("quote")
            start, end = loc.get("start"), loc.get("end")
            if (not isinstance(quote, str) or not quote or type(start) is not int or type(end) is not int
                    or start < 0 or end <= start or body[start:end] != quote
                    or record.get("source_sha256") != source["sha256"]
                    or loc.get("path", "") != source.get("path", "")
                    or record.get("evidence_id") != stable_id("evidence", source_id, quote, str(start))):
                raise ValueError(f"Evidence quote, checksum or locator mismatch: {node.get('node_id')}")
            section, page = loc.get("section"), loc.get("page")
            span = _section_span(body, section) if section else None
            if ((section and (not span or not span[0] <= start < end <= span[1]))
                    or (page is not None and str(page) != str(source.get("page")))
                    or (not section and page is None)):
                raise ValueError(f"Evidence section/page mismatch: {node.get('node_id')}")

    for core in cores:
        if digest(core) != digest(all_nodes.get(core["node_id"])):
            raise ValueError("Graph changed during provenance validation; retry.")
        paper = papers.get(core.get("paper_id"))
        if not paper:
            raise ValueError(f"Core has no Paper source record: {core['node_id']}; reimport it.")
        verify(core, paper)
        expected_edges.add((paper["node_id"], core["node_id"], "has_contribution"))
        for component in core.get("components", []):
            cid = component.get("node_id")
            if not cid or cid in active_components or component.get("core_id") != core["node_id"]:
                raise ValueError("Missing, duplicate or incorrectly linked component identity.")
            if component.get("paper_id") != core["paper_id"] or digest(component) != digest(all_nodes.get(cid)):
                raise ValueError(f"Embedded/standalone component mismatch: {cid}")
            verify(component, paper)
            active_components.add(cid)
            expected_edges.add((core["node_id"], cid, "has_component"))
    actual_components = {k for k, n in all_nodes.items() if n.get("node_type") == "Component"}
    actual_edges = {e for e in edges if e[2] in {"has_contribution", "has_component"}}
    if active_components != actual_components or expected_edges != actual_edges:
        raise ValueError("Contribution/component membership or graph relationships differ.")
    return signatures
