"""Survey adapter for the same scientific search loop used by Idea."""
from pathlib import Path

from src.pipeline.adaptive_search import AdaptiveSearch, history_projection, load_history
from src.pipeline.anysearch import as_bool, write_json_atomic
from src.pipeline.source_reader import SourceReader
from src.pipeline.source_retry import source_access_context
import hashlib


def run_survey_search(collector, *, topic, research_context, subproblems=()):
    enabled = collector._anysearch_discovery_enabled() and as_bool(collector._work_collector_setting("shared_search_enabled", True))
    base = collector._basic_info_value("base_dir", "")
    if not enabled or not base:
        return {"papers": [], "references": [], "searches": []}
    root = Path(str(base))
    checkpoint = root / "search" / "project.json"
    manager = collector.data_manager
    settings = {key: collector._work_collector_setting("shared_search_" + key, default)
                for key, default in {"max_needs": 5, "max_requests": 12, "max_http_requests": 80,
                    "max_model_calls": 12, "max_acquisition_attempts": 20, "read_limit": 8,
                    "max_seconds": 900, "max_rounds": 3, "plan_repair_attempts": 1,
                    "checkpoint_attempts": 2, "result_limit": 5}.items()}
    reader = SourceReader(manager, root / "search" / "reading")
    settings["access_context_generation"] = source_access_context(manager)

    def read(paper):
        return reader.read(paper, prefer_fulltext=as_bool(collector._work_collector_setting("shared_search_prefer_fulltext", True)),
                           allow_abstract_fallback=as_bool(getattr(collector.config.ModuleInfo.WorkAnalyzer, "abstract_when_full_text_fail", True)),
                           max_source_chars=int(collector._work_collector_setting("shared_search_max_source_chars", 60000)))

    def llm(prompt):
        return collector.chat_agent.remote_chat(prompt, temperature=0.0, max_output_tokens=5000)

    def openalex(query, limit):
        return list(manager.openalex_api.search_papers(query, per_page=limit) or [])

    try:
        result = AdaptiveSearch(path=checkpoint, client=manager.anysearch_api, reader=read,
            llm=llm if as_bool(collector._work_collector_setting("shared_search_use_llm", True)) else None,
            openalex_search=openalex, settings=settings, logger=collector.logger,
        ).run(phase="survey", task={"original_request": topic, "current_subproblem": list(subproblems)},
              topic=topic, project_context=research_context)
    except Exception as exc:
        # The run checkpoint already contains completed requests and reads.
        # Preserve them even if an optional planner/IO adapter fails.
        state = load_history(checkpoint)
        collector.logger.warning("Shared Survey search stopped locally (%s); retaining existing evidence.", type(exc).__name__)
        result = {"papers": list(state.get("papers", {}).values()),
                  "references": [r["reference"] for r in state.get("reads", {}).values() if r.get("status") == "completed"],
                  "searches": state.get("queries", []), "history": history_projection([state])}
    write_json_atomic(root / "search_history.json", result.get("history", {}))
    # Only actually-read items enter the Survey corpus. Discovery-only hits
    # and snippets stay in the history for later targeted supplementation.
    completed = {r["paper_id"]: r for r in result.get("references", [])}
    papers = []
    for paper in result.get("papers", []):
        if paper.get("paperId") not in completed:
            continue
        reference = completed[paper["paperId"]]
        metadata = manager.get_discovered_paper(paper["paperId"])
        item = {**paper, **metadata, "retrieval_provenance": reference.get("retrieval_provenance", []),
                **{key: reference[key] for key in ("source_type", "version", "repository_id", "reading_range",
                    "fetched_at", "access_urls", "access_status") if key in reference}}
        source = Path(reference.get("source_path") or "")
        try:
            content = source.read_text(encoding="utf-8") if source.is_file() else ""
            if content and hashlib.sha256(content.encode()).hexdigest() == reference.get("content_sha256"):
                excerpt = str(reference.get("keynote") or "")[:12000]
                item.update(verified_source_path=str(source), verified_source_sha256=reference["content_sha256"],
                            verified_reading_mode=reference.get("reading_mode", ""),
                            verified_source_excerpt=excerpt,
                            reading_range={"start": 0, "end": len(excerpt), "total_chars": len(content)})
        except OSError:
            pass
        manager.register_discovered_papers([item])
        papers.append(item)
    result["papers"] = papers
    return result
