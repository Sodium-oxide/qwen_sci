"""Convert structured extractions and local Survey caches into grounded nodes.

No model calls happen here. Incomplete notes become durable extraction work,
not invented contributions. Evidence is checked against supplied full text.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Iterable

from src.paper_graph.repository import PaperGraphRepository, digest, readonly_connection
from src.pipeline.discipline_taxonomy import canonicalize_discipline_key
from src.pipeline.paper_identity import canonical_paper_id


def text(value: Any) -> str:
    return str(value or "").strip()


def object_value(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return {}
    return dict(value) if isinstance(value, Mapping) else {}


def stable_id(kind: str, *parts: str) -> str:
    return kind + ":" + digest([text(p).casefold() for p in parts])[:24]


def paper_identity(payload: dict[str, Any]) -> str:
    meta = object_value(payload.get("metadata"))
    identifier = text(payload.get("paper_id") or payload.get("doi") or payload.get("node_id")
                      or meta.get("paper_id") or meta.get("doi"))
    if identifier.lower().startswith(("https://doi.org/", "http://doi.org/", "doi:")):
        identifier = re.sub(r"^(?:https?://doi.org/|doi:)", "", identifier, flags=re.I).lower()
    if identifier.startswith("10."):
        identifier = identifier.lower()
    if identifier:
        return canonical_paper_id(identifier)
    title = text(payload.get("paper_title") or meta.get("title") or payload.get("title"))
    if not title:
        raise ValueError("An import requires a stable paper identifier or a paper title.")
    return stable_id("paper", title)


def source_documents(payload: dict[str, Any], documents: Iterable[dict[str, Any]] = ()) -> list[dict[str, Any]]:
    candidates = [*documents, *(payload.get("source_documents") or [])]
    if payload.get("source_text") or payload.get("source_path"):
        candidates.append({"source_id": payload.get("source_id"), "text": payload.get("source_text"),
                           "path": payload.get("source_path")})
    result: dict[str, dict[str, Any]] = {}
    for raw in candidates:
        if not isinstance(raw, Mapping):
            continue
        path = text(raw.get("path"))
        body = text(raw.get("text"))
        if path:
            file = Path(path).expanduser().resolve()
            # A path is authoritative: never accept inline text in place of a
            # missing or changed file while claiming that file as provenance.
            if not file.is_file():
                continue
            body = file.read_text(encoding="utf-8")
            path = str(file)
        if not body.strip():
            continue
        if raw.get("reading_mode", "fulltext") != "fulltext":
            continue
        sid = text(raw.get("source_id")) or stable_id("source", path or body)
        sha = hashlib.sha256(body.encode("utf-8")).hexdigest()
        expected = raw.get("sha256") or raw.get("source_sha256")
        if expected and expected != sha:
            raise ValueError(f"Source checksum mismatch: {path or sid}")
        if sid in result and result[sid]["sha256"] != sha:
            raise ValueError(f"Conflicting source identity: {sid}")
        result[sid] = {"source_id": sid, "path": path, "text": body, "sha256": sha,
                       "page": raw.get("page")}
    return [result[k] for k in sorted(result)]


def _section_span(body: str, section: str) -> tuple[int, int] | None:
    headings = list(re.finditer(r"(?m)^\s{0,3}(#{1,6})\s+(.+?)\s*#*\s*$", body))
    for i, heading in enumerate(headings):
        if section.strip().lstrip("#").strip() != heading.group(2).strip():
            continue
        end = len(body)
        for following in headings[i + 1:]:
            if len(following.group(1)) <= len(heading.group(1)):
                end = following.start()
                break
        return heading.end(), end
    return None


def verified_evidence(item: dict[str, Any], docs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    raw = item.get("evidence_records") or item.get("evidence") or []
    if isinstance(raw, (str, Mapping)):
        raw = [raw]
    if item.get("source_quote") or item.get("quote"):
        raw = [*raw, {"quote": item.get("source_quote") or item["quote"], "source_id": item.get("source_id"),
                       "locator": item.get("locator"), "source_section": item.get("source_section"),
                       "page": item.get("page")}]
    records = []
    for candidate in raw:
        entry = {"quote": candidate} if isinstance(candidate, str) else object_value(candidate)
        quote = text(entry.get("quote") or entry.get("evidence"))
        locator = object_value(entry.get("locator"))
        section = text(entry.get("source_section") or entry.get("section") or locator.get("section")
                       or item.get("source_section"))
        page = entry.get("page", locator.get("page", item.get("page")))
        for doc in docs:
            if entry.get("source_id") and entry["source_id"] != doc["source_id"]:
                continue
            if entry.get("source_sha256") and entry["source_sha256"] != doc["sha256"]:
                continue
            if locator.get("path") and str(Path(locator["path"]).expanduser().resolve()) != doc["path"]:
                continue
            if not quote:
                continue
            # Old Survey notes carry exact quotes without locators. Recover a
            # heading only from a unique literal match, never from a paraphrase.
            resolved_section = section
            if not section and page is None:
                offset = doc["text"].find(quote)
                if offset < 0 or doc["text"].find(quote, offset + 1) >= 0:
                    continue
                headings = list(re.finditer(r"(?m)^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$", doc["text"][:offset]))
                if headings:
                    resolved_section = headings[-1].group(1).strip()
            span = _section_span(doc["text"], resolved_section) if resolved_section else None
            # A reported page is verifiable only with a page-specific source.
            page_valid = page is not None and str(page) == str(doc.get("page"))
            if (resolved_section and not span) or (page is not None and not page_valid) or not (span or page_valid):
                continue
            start, end = span or (0, len(doc["text"]))
            offset = doc["text"].find(quote, start, end)
            if offset < 0:
                continue
            if "start" in locator or "end" in locator:
                claimed_start, claimed_end = locator.get("start"), locator.get("end")
                if (type(claimed_start) is not int or type(claimed_end) is not int
                        or not start <= claimed_start < claimed_end <= end
                        or doc["text"][claimed_start:claimed_end] != quote):
                    continue
                offset = claimed_start
            location = {"section": resolved_section, "page": page, "path": doc["path"],
                        "start": offset, "end": offset + len(quote)}
            records.append({"evidence_id": stable_id("evidence", doc["source_id"], quote, str(offset)),
                            "source_id": doc["source_id"], "quote": quote, "locator": location,
                            "source_sha256": doc["sha256"]})
            break
    return sorted({r["evidence_id"]: r for r in records}.values(), key=lambda r: r["evidence_id"])


def merge_entities(items: Iterable[Any], *, parent_key: str | None = None) -> list[dict[str, Any]]:
    """Merge repeated section extractions by declared identity, preserving quotes."""
    merged: dict[tuple[str, str], dict[str, Any]] = {}
    for item in items:
        entry = object_value(item)
        if not entry:
            continue
        key = (text(entry.get(parent_key)).casefold() if parent_key else "",
               text(entry.get("id") or entry.get("name")).casefold())
        if not key[1]:
            key = (key[0], digest(entry))
        # Convert each packet's legacy quote before any field is merged.
        evidence = entry.get("evidence_records") or entry.get("evidence") or []
        if isinstance(evidence, (str, Mapping)):
            evidence = [evidence]
        if entry.get("quote") or entry.get("source_quote"):
            evidence = [*evidence, {"quote": entry.get("source_quote") or entry["quote"],
                **{k: entry[k] for k in ("source_id", "source_section", "locator", "page") if k in entry}}]
        entry = {**entry, "evidence_records": evidence}
        if key not in merged:
            merged[key] = entry
            continue
        current = merged[key]
        if entry.get("id") and text(current.get("name")).casefold() != text(entry.get("name")).casefold():
            raise ValueError(f"Conflicting names for entity ID: {entry['id']}")
        for field, value in entry.items():
            if not current.get(field):
                current[field] = value
            elif isinstance(current[field], list) and isinstance(value, list):
                unique = {digest(v): v for v in [*current[field], *value]}
                current[field] = [unique[k] for k in sorted(unique)]
            elif field == "summary" and value != current[field]:
                parts = sorted(set(current[field].split("\n") + text(value).split("\n")))
                current[field] = "\n".join(parts)
    return [merged[k] for k in sorted(merged)]


def normalize_extraction(payload: dict[str, Any], documents: Iterable[dict[str, Any]] = ()) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]], dict[str, Any], list[str]]:
    pid = paper_identity(payload)
    meta = object_value(payload.get("metadata"))
    resources = object_value(payload.get("ideation_resource")) or payload
    title = text(payload.get("paper_title") or meta.get("title") or payload.get("title"))
    domain = canonicalize_discipline_key(payload.get("paper_domain") or meta.get("domain"))
    docs = source_documents(payload, documents)
    reasons = []
    if not title:
        reasons.append("missing_paper_title")
    if not domain:
        reasons.append("unresolved_discipline")
    if not docs:
        reasons.append("missing_fulltext")
    common = {"paper_id": pid, "paper_title": title, "paper_domain": domain,
              "pub_year": payload.get("pub_year") or meta.get("year") or "",
              "source_venue": payload.get("source_venue") or meta.get("venue") or ""}
    paper_node = {**common, "node_id": stable_id("paper", pid), "node_type": "Paper", "full_name": title,
                  "source_documents": [{k: v for k, v in d.items() if k != "text" or not d["path"]} for d in docs]}
    nodes = [paper_node]
    edges = []
    cores = resources.get("core_contributions", payload.get("cores", []))
    components = resources.get("components", [])
    if not isinstance(cores, list) or not cores:
        reasons.append("missing_structured_contributions")
        cores = []
    if not isinstance(components, list):
        reasons.append("invalid_components")
        components = []
    if any(not object_value(c) for c in cores):
        reasons.append("invalid_contribution")
    if any(not isinstance(c, Mapping) for c in components):
        reasons.append("invalid_component")
    cores = merge_entities(cores)
    if not cores:
        reasons.append("missing_structured_contributions")
    declared_core_links = {text(c.get("id")) or text(c.get("name")) for c in cores}
    declared_core_links.update(text(c.get("name")) for c in cores)
    if any(isinstance(c, Mapping) and text(c.get("related_to_core")) not in declared_core_links - {""}
           for c in components):
        reasons.append("unlinked_components")
    core_keys: set[str] = set()
    component_keys: set[str] = set()
    for raw_core in cores:
        core = object_value(raw_core)
        name, summary = text(core.get("name")), text(core.get("summary"))
        if not isinstance(core.get("name"), str) or not isinstance(core.get("summary"), str) or not name or not summary:
            reasons.append("incomplete_contribution")
            continue
        cid = stable_id("core", pid, text(core.get("id")) or name)
        if cid in core_keys:
            raise ValueError(f"Duplicate contribution identity: {name}")
        core_keys.add(cid)
        evidence = verified_evidence(core, docs)
        if not evidence:
            reasons.append(f"contribution_evidence_missing:{name}")
            continue
        core_node = {**common, "node_id": cid, "node_type": "Core", "label": name, "full_name": name,
                     "summary": summary, "evidence_records": evidence,
                     "text": "\n".join(e["quote"] for e in evidence),
                     "structure": core.get("structure", ""), "assumptions": core.get("assumptions", []),
                     "boundary_conditions": core.get("boundary_conditions", []), "components": []}
        own_components = core.get("components", [])
        if not isinstance(own_components, list):
            reasons.append(f"invalid_components:{name}")
            own_components = []
        if any(not object_value(c) for c in own_components):
            reasons.append(f"invalid_component:{name}")
        linked = [c for c in components if isinstance(c, Mapping) and
                  text(c.get("related_to_core")) in {name, text(core.get("id"))} - {""}]
        for raw_component in merge_entities([*own_components, *linked]):
            comp = object_value(raw_component)
            comp_name, comp_summary = text(comp.get("name")), text(comp.get("summary"))
            if not isinstance(comp.get("name"), str) or not isinstance(comp.get("summary"), str) or not comp_name or not comp_summary:
                reasons.append(f"incomplete_component:{name}")
                continue
            comp_id = stable_id("component", cid, text(comp.get("id")) or comp_name)
            if comp_id in component_keys:
                raise ValueError(f"Duplicate component identity under {name}: {comp_name}")
            component_keys.add(comp_id)
            comp_evidence = verified_evidence(comp, docs)
            if not comp_evidence:
                reasons.append(f"component_evidence_missing:{name}/{comp_name}")
                continue
            component = {**common, "node_id": comp_id, "node_type": "Component", "core_id": cid,
                         "name": comp_name, "summary": comp_summary, "keywords": comp.get("keywords", []),
                         "evidence_records": comp_evidence}
            nodes.append(component)
            core_node["components"].append(component)
            edges.append({"id": stable_id("edge", cid, comp_id), "source": cid,
                          "target": comp_id, "edge_type": "has_component"})
        if not core_node["components"]:
            reasons.append(f"missing_grounded_components:{name}")
        nodes.append(core_node)
        edges.append({"id": stable_id("edge", pid, cid), "source": paper_node["node_id"],
                      "target": cid, "edge_type": "has_contribution"})
    queued = {**payload, "paper_id": pid, "source_documents": docs}
    return pid, sorted(nodes, key=lambda n: n["node_id"]), sorted(edges, key=lambda e: e["id"]), queued, sorted(set(reasons))


def ingest_paper(db_path: Path | str, payload: dict[str, Any], *, documents: Iterable[dict[str, Any]] = (),
                 expected_queue_hash: str | None = None, extraction_attempt_id: int | None = None) -> dict[str, Any]:
    pid, nodes, edges, queued, reasons = normalize_extraction(payload, documents)
    if expected_queue_hash is not None and reasons:
        raise ValueError("Queue extraction failed import validation: " + "; ".join(reasons))
    resources = object_value(payload.get("ideation_resource")) or payload
    authoritative = not reasons and ("core_contributions" in resources or "cores" in payload)
    return PaperGraphRepository(db_path).replace_paper(pid, nodes, edges, queued, reasons, authoritative=authoritative,
                                                     expected_queue_hash=expected_queue_hash,
                                                     extraction_attempt_id=extraction_attempt_id)


def _diskcache_values(directory: Path) -> Iterable[dict[str, Any]]:
    """Read this workstation's trusted diskcache without changing its database."""
    if not (directory / "cache.db").is_file():
        return
    from diskcache import Disk
    disk = Disk(str(directory))
    conn = readonly_connection(directory / "cache.db")
    try:
        for row in conn.execute("SELECT mode, filename, value FROM Cache ORDER BY rowid"):
            value = disk.fetch(row["mode"], row["filename"], row["value"], read=False)
            if isinstance(value, Mapping):
                yield dict(value)
    finally:
        conn.close()


def cached_documents(cache_dir: Path, paper_id: str) -> list[dict[str, Any]]:
    identifiers = {paper_id, canonical_paper_id(paper_id)}
    if canonical_paper_id(paper_id).startswith("W"):
        identifiers.add("https://openalex.org/" + canonical_paper_id(paper_id))
    paths = set()
    for identifier in identifiers:
        key = hashlib.md5(identifier.encode("utf-8")).hexdigest()
        for key in (key, identifier):
            base = (cache_dir / "parsed_papers" / key).resolve()
            if base.is_relative_to(cache_dir / "parsed_papers") and base.is_dir():
                paths.update(base.rglob("*.md"))
    return [{"source_id": stable_id("source", paper_id, str(p)), "path": str(p)} for p in sorted(paths)]


def import_survey_cache(db_path: Path | str, cache_dir: Path | str) -> dict[str, Any]:
    cache = Path(cache_dir).expanduser().resolve()
    results = []
    errors = []
    records = []
    for path in sorted((cache / "constructed_nodes").glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            records.extend(payload if isinstance(payload, list) else [payload])
        except (ValueError, OSError) as exc:
            errors.append({"path": str(path), "error": str(exc)})
    structured_ids = set()
    for payload in records:
        try:
            if isinstance(payload, dict):
                structured_ids.add(paper_identity(payload))
        except ValueError:
            pass  # The per-record import below reports malformed inputs.
    for cached in _diskcache_values(cache / "paper_keynotes"):
        if not cached.get("paper_id"):
            continue
        if paper_identity(cached) in structured_ids:
            continue
        note = object_value(cached.get("keynote"))
        records.append({**note, "paper_id": cached["paper_id"], "keynote_cache": cached})
    for payload in records:
        try:
            if not isinstance(payload, dict):
                raise ValueError("Expected a paper extraction object")
            pid = paper_identity(payload)
            docs = cached_documents(cache, pid)
            # A Markdown title can fill bibliographic metadata, never a
            # contribution, discipline label or evidence span.
            if not payload.get("paper_title") and not object_value(payload.get("metadata")).get("title") and docs:
                body = Path(docs[0]["path"]).read_text(encoding="utf-8")
                heading = re.search(r"(?m)^#\s+(.+)$", body)
                if heading:
                    payload["paper_title"] = heading.group(1).strip()
            results.append(ingest_paper(db_path, payload, documents=docs))
        except (ValueError, TypeError, OSError) as exc:
            errors.append({"paper_id": text(payload.get("paper_id")) if isinstance(payload, dict) else "", "error": str(exc)})
    # Ensure first-time import also creates an empty queue/schema for an empty cache.
    with PaperGraphRepository(db_path).write():
        pass
    return {"papers": len(results), "cores": sum(r["cores"] for r in results),
            "components": sum(r["components"] for r in results),
            "queued": sum(bool(r["pending_reasons"]) for r in results), "errors": errors, "results": results}
