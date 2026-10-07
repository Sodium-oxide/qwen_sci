"""Publish original Survey papers independently of the generated review."""

from collections.abc import Mapping
from pathlib import Path
import json
import hashlib
import math

from .paper_identity import canonical_paper_id


def _score(record):
    values = [record.get("relevance_score"), record.get("max_llm_relevance_score"),
              record.get("max_embedding_relatedness")]
    values.append((record.get("project_relevance") or {}).get("relevance_score"))
    values.extend(item.get("semantic_relevance_score") for item in record.get("sh_semantic_assessments", [])
                  if isinstance(item, Mapping))
    scores = []
    for value in values:
        try:
            number = float(value)
            if math.isfinite(number):
                scores.append(number)
        except (TypeError, ValueError):
            pass
    return max(scores, default=0.0)


def publish_survey_retrieval(config, collector, seed_ids, expanded_ids):
    destination = Path(str(config.BasicInfo.base_dir)) / "survey_retrieval_manifest.json"
    retrieval = getattr(collector, "subhypothesis_retrieval_artifact", {}) or {}
    candidates = retrieval.get("candidate_papers") or getattr(collector, "retrieval_candidates", [])
    records = {}
    for item in candidates:
        if not isinstance(item, Mapping):
            continue
        identifier = collector.data_manager._resolve_paper_reference_id(item)
        if identifier:
            records[canonical_paper_id(identifier)] = dict(item)
    provenance = getattr(collector, "sh_graph_provenance_artifact", {}) or {}
    budget = getattr(collector, "fulltext_budget_plan", {}) or provenance.get("fulltext_budget_plan") or {}
    expanded_scores = {canonical_paper_id(item.get("paper_id")): item
                       for item in budget.get("selected_for_fulltext", [])
                       if isinstance(item, Mapping)}
    annotations = provenance.get("paper_annotations") or {}
    papers = []
    original_ids = {canonical_paper_id(identifier): identifier for identifier in [*seed_ids, *expanded_ids]}
    expansion_ids = {canonical_paper_id(item) for item in expanded_ids}
    seed_canonicals = {canonical_paper_id(item) for item in seed_ids}
    # Persist only the bounded high-score handoff set.  The collector may keep
    # a larger working candidate list for Survey internals, but ExperimentDesign
    # receives at most 20 primary papers and 12 graph expansions.
    ranked_seed_ids = sorted(seed_canonicals, key=lambda item: (-_score(records.get(item, {})), item))[:20]
    ranked_expansion_ids = sorted(expansion_ids, key=lambda item: (-_score(expanded_scores.get(item, records.get(item, {}))), item))[:12]
    export_ids = dict.fromkeys([*ranked_seed_ids, *ranked_expansion_ids])
    for canonical in export_ids:
        identifier = original_ids.get(canonical, canonical)
        canonical = canonical_paper_id(identifier)
        record = records.get(canonical, {}).copy()
        cached = collector.data_manager.paper_abstract_cache.get(
            hashlib.md5(str(identifier).encode("utf-8")).hexdigest(), {}
        )
        cached = cached if isinstance(cached, Mapping) else {}
        title, abstract = cached.get("title", ""), cached.get("abstract", "")
        record.update(paper_id=canonical, title=record.get("title") or title,
                      abstract=record.get("abstract") or abstract)
        graph_annotations = annotations.get(canonical, [])
        parents = list(dict.fromkeys(parent for item in graph_annotations
                                     for parent in item.get("parent_paper_ids", item.get("root_seed_paper_ids", []))))
        is_expansion = canonical in expansion_ids and canonical not in seed_canonicals
        if is_expansion:
            record.update(expanded_scores.get(canonical, {}))
            if not parents:
                parents = list(record.get("matched_seed_ids") or [])
        record["source_kind"] = "citation_graph_expansion" if is_expansion else "survey_retrieval"
        record["parent_paper_ids"] = parents if is_expansion else []
        record["lineage_depth"] = min((item.get("lineage_depth", 1) for item in graph_annotations), default=1) if is_expansion else 0
        record["sh_semantic_assessments"] = list(record.get("sh_semantic_assessments", [])) + graph_annotations
        record["relevance_score"] = _score(record)
        markdown = Path(str(config.BasicInfo.cache_path)) / "parsed_papers" / str(identifier) / "auto" / f"{identifier}.md"
        if markdown.is_file():
            record["fulltext"] = markdown.read_text(encoding="utf-8")
            record["fulltext_source_location"] = str(markdown)
        papers.append(record)
    payload = {"schema_version": "survey_retrieval_manifest_v1", "source": "survey_retrieval",
               "topic": str(config.BasicInfo.topic), "papers": papers}
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return destination
