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
from src.pipeline.adaptive_search import AdaptiveSearch, load_history
from src.pipeline.search_planner import compact_query, scientific_input, ScientificSearchPlanner


REFERENCE_SOURCE_FIELDS = (
    "doi", "url", "year", "venue", "reading_mode", "reading_status", "reading_issues",
    "source_path", "source_chars", "used_chars", "search_checkpoint", "reading_checkpoint",
    "retrieval_provenance", "discovery_provenance", "source_references",
    "scoring_status", "scoring_issue",
    "source_type", "version", "externalIds", "repository_id", "access_urls", "access_status",
    "fetched_at", "reading_range", "content_sha256",
    "pmid", "pmcid", "identity_provenance", "raw_source_path", "raw_source_sha256",
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
        queries = [compact_query(subject), compact_query(_text(task.get("original_request")))]
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
                queries.append(compact_query(" ".join(dict.fromkeys(terms))))
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

    def run(self, *, phase, task, topic, candidates=(), known_references=(), survey_context=None):
        if not as_bool(self.setting("enabled", False)):
            return {"references": [], "searches": []}
        if phase not in {"initial", "candidate"}:
            raise ValueError("Unknown Idea external-search phase")
        if phase == "candidate" and not scientific_input(task, topic=topic, candidates=candidates)["candidates"]:
            return {"references": [], "searches": []}
        context = survey_context if isinstance(survey_context, Mapping) else {}
        if not context:
            from src.agents.idea_agent.agent.artifacts import artifact_get
            context = artifact_get(getattr(self.agent, "artifact", {}), "survey_idea_context", {}) or {}
        project = context.get("project_context", {})
        if isinstance(project.get("research_context"), Mapping):
            project = project["research_context"]
        other = "candidate" if phase == "initial" else "initial"
        previous = load_history(self.root / (other + ".json"))
        inherited = [previous, context.get("search_history", {}), context.get("survey_json", {}).get("search_history", {})]
        successful_other = sum(read.get("status") == "completed" and not read.get("reused") for read in previous.get("reads", {}).values())
        known_references = [*known_references, *(r["reference"] for r in previous.get("reads", {}).values()
                                                if r.get("status") == "completed" and isinstance(r.get("reference"), Mapping))]
        read_limit = min(max(0, int(self.setting(phase + "_read_limit", 4))),
                         max(0, int(self.setting("max_total_papers", 8)) - successful_other))
        names = ("max_requests", "max_http_requests", "max_model_calls", "max_acquisition_attempts", "max_seconds",
                 "max_rounds", "plan_repair_attempts", "checkpoint_attempts", "result_limit")
        defaults = (12, 80, 12, 20, 900, 3, 1, 2, 5)
        settings = {key: self.setting(key, default) for key, default in zip(names, defaults)}
        spent_acquisition = int(previous.get("budget", {}).get("acquisitions", sum(r.get("attempts", 0) for r in previous.get("reads", {}).values())))
        settings["max_acquisition_attempts"] = min(int(settings["max_acquisition_attempts"]),
            max(0, int(self.setting("max_total_acquisition_attempts", 20)) - spent_acquisition))
        settings.update(read_limit=read_limit, max_needs=int(self.setting(phase + "_queries", 5 if phase == "initial" else 4)))
        settings["access_context_generation"] = get_config_value(
            getattr(self.repository, "config", None), "ModuleInfo.WorkCollector.fulltext_access_context_generation", "anonymous-v1")

        def read(paper):
            return self.repository.read_discovered_paper(
                paper, work_dir=self.root / "reading",
                prefer_fulltext=as_bool(self.setting("prefer_fulltext", True)),
                allow_abstract_fallback=as_bool(self.setting("allow_abstract_fallback", True)),
                max_source_chars=int(self.setting("max_source_chars", 60000)),
            )

        def llm(prompt):
            # The shared planner builds its own scientific allowlist. Do not
            # append candidate scoring, adjudication, rubric or evaluator text.
            return self.agent.chat(prompt, temperature=0.0, max_output_tokens=5000)

        def openalex_search(query, limit):
            manager = getattr(self.repository, "data_manager", None)
            api = getattr(manager, "openalex_api", None)
            if api is None:
                from src.agents.survey_agent.modules.data_manager import DataManager
                config = getattr(self.repository, "config", None)
                if config is None:
                    return []
                api = DataManager(config).openalex_api
            return list(api.search_papers(query, per_page=limit) or [])

        return AdaptiveSearch(path=self.root / (phase + ".json"), client=self.client, reader=read,
            llm=llm if callable(getattr(self.agent, "chat", None)) and as_bool(self.setting("planner_use_llm", True)) else None,
            openalex_search=openalex_search, settings=settings, inherited=inherited, logger=getattr(self.agent, "logger", None),
        ).run(phase=phase, task=task, topic=topic, project_context=project, candidates=candidates, known_references=known_references)


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
