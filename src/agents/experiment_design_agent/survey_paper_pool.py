"""Select original Survey papers without performing paper discovery."""

from collections.abc import Mapping, Sequence
from copy import deepcopy
from pathlib import Path
import json
import math
import os
import re
import hashlib

from src.pipeline.paper_identity import canonical_paper_id


MAX_EVIDENCE_PAPERS = 32
REFERENCE_SLOTS = ("research_object_measurability", "mechanism")


def _records(payload):
    values = payload.get("papers", payload.get("paper_registry", [])) if isinstance(payload, Mapping) else payload
    if isinstance(values, Mapping):
        return [{"paper_id": identifier, **dict(record)} for identifier, record in values.items()
                if isinstance(record, Mapping)]
    return [dict(record) for record in values or [] if isinstance(record, Mapping)]


def _score(record):
    values = [record.get("relevance_score"), record.get("score"),
              record.get("max_llm_relevance_score"), record.get("max_embedding_relatedness")]
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
    return max(scores, default=0)


def load_survey_papers(source):
    if source is None:
        return {"papers": [], "source": "survey_retrieval",
                "warnings": ["survey_original_paper_source_missing:no_independent_search"]}
    if isinstance(source, (Mapping, Sequence)) and not isinstance(source, (str, bytes, Path)):
        return source
    path = _local_path(source).expanduser().resolve()
    if path.is_dir():
        path = path / "survey_retrieval_manifest.json"
    if path.name == "survey_manifest.json":
        manifest = json.loads(path.read_text(encoding="utf-8"))
        artifact = (manifest.get("artifacts") or {}).get("retrieval_papers", {})
        path = path.parent / (artifact.get("path") or "survey_retrieval_manifest.json")
    if not path.exists() and path.name == "survey_retrieval_manifest.json":
        return _legacy_original_papers(path.parent)
    if path.name in {"survey.md", "survey.json"}:
        raise ValueError("ExperimentDesign requires original Survey papers, not the generated review.")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping) or "papers" not in payload:
        raise ValueError(f"Original Survey paper manifest has no papers array: {path}")
    return payload


def _local_path(value):
    value = str(value)
    if os.name == "nt" and re.match(r"^/mnt/[a-z]/", value):
        value = value[5].upper() + ":/" + value[7:]
    return Path(value)


def _legacy_original_papers(directory):
    provenance_path = directory / "sh_graph_provenance.json"
    if not provenance_path.is_file():
        return {"papers": [], "source": "survey_retrieval", "warnings": [
            f"survey_original_paper_manifest_missing:{directory}:no_independent_search"]}
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    repository = next((parent for parent in directory.parents if (parent / "src").is_dir()), None)
    cache_root = repository / "database" if repository else directory / "database"
    abstract_cache = None
    if (cache_root / "paper_abstracts" / "cache.db").is_file():
        import diskcache
        abstract_cache = diskcache.Cache(str(cache_root / "paper_abstracts"))
    papers = []
    try:
        for identifier, annotations in (provenance.get("paper_annotations") or {}).items():
            annotations = [item for item in annotations if isinstance(item, Mapping)]
            seed = any(item.get("association_stage") == "SEED_SELECTION" for item in annotations)
            record = {"paper_id": identifier, "source_kind": "survey_retrieval" if seed else "citation_graph_expansion",
                      "sh_semantic_assessments": annotations,
                      "parent_paper_ids": list(dict.fromkeys(parent for item in annotations for parent in item.get("parent_paper_ids", []))),
                      "lineage_depth": min((item.get("lineage_depth", 1) for item in annotations), default=1)}
            cached = abstract_cache.get(hashlib.md5(identifier.encode("utf-8")).hexdigest(), {}) if abstract_cache is not None else {}
            if isinstance(cached, Mapping):
                record.update({key: cached[key] for key in ("title", "abstract") if key in cached})
            markdown = cache_root / "parsed_papers" / identifier / "auto" / f"{identifier}.md"
            if markdown.is_file():
                record.update(fulltext=markdown.read_text(encoding="utf-8"), fulltext_source_location=str(markdown))
            papers.append(record)
    finally:
        if abstract_cache is not None:
            abstract_cache.close()
    return {"papers": papers, "source": "survey_retrieval", "warnings": [
        "legacy_survey_pool_reconstructed_from_original_cache_and_graph:only_persisted_papers_available"]}


def select_survey_papers(source, *, max_papers=32, max_expansion_papers=12, min_graph_relevance_score=3):
    payload = load_survey_papers(source)
    unique = {}
    for raw in _records(payload):
        identifier = canonical_paper_id(raw.get("canonical_paper_id") or raw.get("paper_id")
                                        or raw.get("id") or raw.get("doi"))
        if not identifier:
            continue
        record = deepcopy(raw)
        record["canonical_paper_id"] = identifier
        record["relevance_score"] = _score(raw)
        record.setdefault("source_kind", "survey_retrieval")
        if identifier not in unique or record["relevance_score"] > unique[identifier]["relevance_score"]:
            unique[identifier] = record
    ranked = sorted(unique.values(), key=lambda paper: (-paper["relevance_score"], paper["canonical_paper_id"]))
    limit = max(0, min(MAX_EVIDENCE_PAPERS, int(max_papers)))
    seeds = [paper for paper in ranked if paper["source_kind"] != "citation_graph_expansion"]
    seed_ids = {paper["canonical_paper_id"] for paper in seeds}
    expansions = [paper for paper in ranked if paper["source_kind"] == "citation_graph_expansion"
                  and paper["relevance_score"] >= float(min_graph_relevance_score) and
                  paper.get("lineage_depth", 1) == 1 and
                  any(canonical_paper_id(parent) in seed_ids for parent in
                      (paper.get("parent_paper_ids") or [paper.get("parent_paper_id")]))]
    expansion_limit = min(limit, max(0, int(max_expansion_papers)), len(expansions))
    selected_seeds = seeds[:max(0, limit - expansion_limit)]
    selected_ids = {paper["canonical_paper_id"] for paper in selected_seeds}
    selected_expansions = [paper for paper in expansions
                           if any(canonical_paper_id(parent) in selected_ids for parent in
                                  (paper.get("parent_paper_ids") or [paper.get("parent_paper_id")]))][:expansion_limit]
    remaining = limit - len(selected_seeds) - len(selected_expansions)
    selected_seeds.extend(seeds[len(selected_seeds):len(selected_seeds) + remaining])
    selected = selected_seeds + selected_expansions
    for paper in selected:
        paper.setdefault("providers", ["survey_retrieval"])
        paper.setdefault("provider_ids", {"canonical": paper["canonical_paper_id"]})
        paper["content_availability"] = "fulltext" if paper.get("fulltext") else "abstract" if paper.get("abstract") else "metadata"
        paper.setdefault("abstract_source_location", f"abstract:survey:{paper['canonical_paper_id']}")
        paper.setdefault("fulltext_source_location", paper.get("source_location") or f"fulltext:survey:{paper['canonical_paper_id']}")
    return {"schema_version": "survey_paper_pool_v1", "source": "survey_retrieval",
            "papers": selected, "primary_paper_count": len(selected_seeds),
            "expansion_paper_count": len(selected_expansions), "paper_count": len(selected),
            "max_papers": limit, "warnings": list(payload.get("warnings", [])) if isinstance(payload, Mapping) else []}


def resolve_survey_source(idea_path, binding=None, explicit_source=None):
    if explicit_source:
        return load_survey_papers(explicit_source)
    binding = binding or {}
    supplied = binding.get("survey_retrieval_manifest") or binding.get("manifest_path") or binding.get("survey_manifest_path")
    if supplied and _local_path(supplied).exists():
        return load_survey_papers(supplied)
    idea_path = Path(idea_path).resolve()
    for parent in idea_path.parents:
        survey_dir = parent / "survey"
        if survey_dir.is_dir():
            if supplied:
                match = re.search(r"survey[/\\](attempt-[^/\\]+)[/\\]", str(supplied))
                if match and (survey_dir / match.group(1)).is_dir():
                    return load_survey_papers(survey_dir / match.group(1))
                continue
            paths = sorted(survey_dir.glob("attempt-*/survey_manifest.json"))
            if paths:
                return load_survey_papers(paths[-1])
    return {"papers": [], "source": "survey_retrieval", "warnings": [
        f"survey_bound_source_unavailable:{supplied}:no_independent_search"]} if supplied else load_survey_papers(None)
