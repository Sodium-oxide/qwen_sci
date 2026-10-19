"""Budgeted, resumable external literature discovery for Idea.

Only task and candidate scientific fields enter queries. Search results stay
discovery metadata until PaperRepository reads their full text or abstract.
"""
from __future__ import annotations

from collections.abc import Mapping
import json
from pathlib import Path
from typing import Any

from src.agents.idea_agent.utils.core.config_loader import get_config_value
from src.pipeline.anysearch import AnySearchClient, DEFAULT_ANYSEARCH_TAG, as_bool, identity_keys, merge_papers, write_json_atomic


REFERENCE_SOURCE_FIELDS = (
    "doi", "url", "year", "venue", "reading_mode", "reading_status", "reading_issues",
    "source_path", "source_chars", "used_chars", "search_checkpoint", "reading_checkpoint",
    "retrieval_provenance", "discovery_provenance", "source_references",
    "scoring_status", "scoring_issue",
)


def reference_metadata(reference: Mapping) -> dict:
    """Small public record; original sources and model replies stay in checkpoints."""
    fields = ("paper_id", "node_id", "title", "authors", "source", "summary", "insight", "compression_status", "compression_checkpoint", *REFERENCE_SOURCE_FIELDS)
    result = {key: reference[key] for key in fields if key in reference}
    for key in ("summary", "insight"):
        if isinstance(result.get(key), str):
            result[key] = result[key][:4000]
    return result


def flatten_references(batches) -> list[dict]:
    records = []
    for batch in batches or []:
        for reference in batch or []:
            if isinstance(reference, dict):
                records.append(reference)
                records.extend(item for item in reference.get("source_references", []) if isinstance(item, dict))
    return records


def _text(value: Any) -> str:
    return " ".join(value.split()) if isinstance(value, str) else ""


def build_external_queries(task: Mapping, *, topic: str, phase: str, candidates=(), limit: int = 2) -> list[str]:
    """Allowlist scientific inputs rather than serializing evaluation artifacts."""
    subject = _text(topic) or _text(task.get("original_request"))
    queries = []
    if phase == "initial":
        queries = [subject[:700], _text(task.get("original_request"))[:700]]
    elif phase == "candidate":
        for candidate in candidates:
            if not isinstance(candidate, Mapping):
                continue
            if candidate.get("maturity_status") == "rejected" or candidate.get("independence_status") == "collapsed_duplicate":
                continue
            terms = []
            for field in ("title", "central_hypothesis", "hypothesis", "mechanism", "mechanism_or_relation", "candidate_mechanism", "expected_mechanism", "evidence_gaps", "open_questions"):
                value = candidate.get(field)
                values = value if isinstance(value, list) else [value]
                terms.extend(_text(item) for item in values if _text(item))
            if terms:
                queries.append((subject[:180] + " " + " ".join(dict.fromkeys(terms))[:500]).strip())
    return list(dict.fromkeys(query for query in queries if query))[:max(0, limit)]


class IdeaExternalSearch:
    def __init__(self, agent: Any, *, client=None):
        self.agent = agent
        self.root = Path(agent.run_dir) / "external_search"
        self.repository = agent.paper_repository
        self.client = client or AnySearchClient(
            self.setting("base_url", "") or None,
            tag=self.setting("tag", DEFAULT_ANYSEARCH_TAG),
            timeout=self.setting("timeout_seconds", 30), max_retries=self.setting("max_retries", 1),
            cache_dir=self.root / "search_cache", enabled=as_bool(self.setting("enabled", False)),
        )

    def setting(self, name, default):
        return get_config_value(getattr(self.agent, "config", None), "agent.anysearch." + name, default)

    def _load(self, path):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            return payload if isinstance(payload, dict) else {}
        except (OSError, ValueError):
            return {}

    def run(self, *, phase, task, topic, candidates=(), known_references=()):
        if not as_bool(self.setting("enabled", False)):
            return {"references": [], "searches": []}
        if phase not in {"initial", "candidate"}:
            raise ValueError("Unknown Idea external-search phase")
        path = self.root / (phase + ".json")
        state = self._load(path)
        if not state:
            queries = build_external_queries(
                task, topic=topic, phase=phase, candidates=candidates,
                limit=min(8, max(0, int(self.setting(phase + "_queries", 2)))),
            )
            if not queries:
                return {"references": [], "searches": []}
            state = {"schema_version": 1, "phase": phase, "queries": [{"query": query, "attempts": 0} for query in queries], "papers": {}, "reads": {}}
        cap = min(3, max(1, int(self.setting("checkpoint_attempts", 2))))
        limit = min(30, max(1, int(self.setting("result_limit", 8))))
        for query in state["queries"]:
            if query.get("status") in {"success", "valid_empty"} or query["attempts"] >= cap:
                continue
            query["attempts"] += 1
            query["status"] = "in_progress"
            write_json_atomic(path, state)
            try:
                result = self.client.search(query["query"], limit=limit)
                query.update(status=result.status, cached=result.cached, request_attempts=result.attempts)
                query["papers"] = result.papers
            except Exception as exc:
                query.update(status="provider_failure", error_type=type(exc).__name__)
            write_json_atomic(path, state)
        discovered = merge_papers([
            {**paper, "retrieval_provenance": [*(paper.get("retrieval_provenance") or []), {"provider": "anysearch", "query": query["query"], "phase": phase}]}
            for query in state["queries"] if query.get("status") == "success"
            for paper in query.get("papers", [])
        ])
        other_phase = "candidate" if phase == "initial" else "initial"
        other_reads = self._load(self.root / (other_phase + ".json")).get("reads", {})
        known = set().union(*(identity_keys(ref) for ref in known_references)) if known_references else set()
        known.update(key for read in other_reads.values() for key in identity_keys(read.get("reference") or read.get("paper") or {}))
        budget = min(20, max(0, int(self.setting(phase + "_read_limit", 4))))
        total = min(40, max(0, int(self.setting("max_total_papers", 8))))
        budget = min(budget, max(0, total - len(other_reads)))
        for paper in discovered:
            pid = paper["paperId"]
            if pid in state["reads"]:
                continue
            if len(state["reads"]) >= budget:
                break
            if identity_keys(paper) & known:
                continue
            state["reads"][pid] = {"paper": paper, "attempts": 0}
            known.update(identity_keys(paper))
        write_json_atomic(path, state)
        for pid, read in state["reads"].items():
            if read.get("status") == "completed" or read["attempts"] >= cap:
                continue
            read["attempts"] += 1
            read["status"] = "in_progress"
            write_json_atomic(path, state)
            try:
                reference = self.repository.read_discovered_paper(
                    read["paper"], work_dir=self.root / "reading",
                    prefer_fulltext=as_bool(self.setting("prefer_fulltext", True)),
                    allow_abstract_fallback=as_bool(self.setting("allow_abstract_fallback", True)),
                    max_source_chars=int(self.setting("max_source_chars", 60000)),
                )
                read["status"] = reference.get("reading_status", "unavailable")
                read["reference"] = {
                    **reference, "retrieval_provenance": read["paper"].get("retrieval_provenance", []),
                    "search_checkpoint": str(path), "reading_checkpoint": str(path),
                }
            except Exception as exc:
                read.update(status="failed", error_type=type(exc).__name__)
            write_json_atomic(path, state)
        searches = [
            {"provider": "anysearch", "phase": phase, "query": query["query"], "status": query.get("status"), "attempts": query["attempts"], "paper_count": len(query.get("papers", [])), "checkpoint": str(path)}
            for query in state["queries"]
        ]
        logger = getattr(self.agent, "logger", None)
        references = [read["reference"] for read in state["reads"].values() if read.get("status") == "completed"]
        if logger:
            logger.info("Idea AnySearch phase=%s queries=%s readable=%s statuses=%s", phase, len(searches), len(references), ",".join(str(query["status"]) for query in searches))
        return {"references": references, "searches": searches}


def search_idea_literature(agent, **kwargs):
    """Keep optional discovery failures local; preserve the existing workflow."""
    if not as_bool(get_config_value(getattr(agent, "config", None), "agent.anysearch.enabled", False)):
        return {"references": [], "searches": []}
    try:
        return IdeaExternalSearch(agent).run(**kwargs)
    except Exception as exc:
        logger = getattr(agent, "logger", None)
        if logger:
            logger.warning("Idea AnySearch supplement failed (%s); preserving existing references.", type(exc).__name__)
        return {"references": [], "searches": [{"provider": "anysearch", "phase": kwargs.get("phase"), "status": "failed", "error_type": type(exc).__name__}]}
