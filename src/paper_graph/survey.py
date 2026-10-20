"""Survey integration: reuse local text and notes, never trigger acquisition."""
from __future__ import annotations

from typing import Any

from src.paper_graph.ingest import cached_documents, ingest_paper, object_value
from src.paper_graph.settings import PaperGraphSettings, repo_path, select


def ingest_survey_paper(config: Any, data_manager: Any, paper_id: str,
                        extraction: Any) -> dict[str, Any] | None:
    if not select(config, "paper_graph.ingest_on_survey", False):
        return None
    settings = PaperGraphSettings.from_config(config)
    cache = repo_path(select(config, "BasicInfo.cache_path", "database"))
    payload = object_value(extraction)
    metadata = {}
    lookup = getattr(data_manager, "get_discovered_paper", None)
    if callable(lookup):
        metadata = object_value(lookup(paper_id))
    payload = {**payload, "paper_id": paper_id,
               "paper_title": payload.get("paper_title") or metadata.get("title") or
                              object_value(payload.get("metadata")).get("title", "")}
    docs = cached_documents(cache, paper_id)
    if metadata.get("verified_reading_mode") == "fulltext" and metadata.get("verified_source_path"):
        docs.append({"path": metadata["verified_source_path"],
                     "sha256": metadata.get("verified_source_sha256"), "reading_mode": "fulltext"})
    return ingest_paper(settings.db_path, payload, documents=docs)
