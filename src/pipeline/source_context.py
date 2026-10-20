"""Explicit source text and scope for scientific assessment prompts."""
import json
import re


def source_texts(paper):
    texts = {key: paper.get(key) or "" for key in ("title", "abstract")}
    # Discovery snippets never enter this accessor. The reader/Survey adapter
    # attach this field only after obtaining and hashing the actual source.
    if re.fullmatch(r"[a-f0-9]{64}", str(paper.get("verified_source_sha256") or "")):
        texts["source_excerpt"] = paper.get("verified_source_excerpt") or ""
    return texts


def has_source_content(paper):
    return any(str(value).strip() for key, value in source_texts(paper).items() if key != "title")


def source_scope(paper):
    return {key: paper.get(key) for key in (
        "source_type", "url", "doi", "version", "repository_id", "verified_reading_mode",
        "reading_range", "fetched_at", "verified_source_sha256", "access_urls", "access_status",
    ) if paper.get(key) is not None}


def assessment_source(paper):
    return {**source_texts(paper), "source_context": source_scope(paper)}


def labelled_source(content, paper):
    return "Source context: " + json.dumps(source_scope(paper), ensure_ascii=False) + "\n\n" + content
