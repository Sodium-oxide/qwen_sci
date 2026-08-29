"""Provenance-bounded, deterministic BibTeX rendering for Author documents."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import re
from collections.abc import Mapping
from typing import Any

from .latex_safety import LatexSafetyError, contains_non_english_script, escape_latex_text, validate_citation_key


BIBTEX_RENDER_SCHEMA_VERSION = "research_plan_author_bibtex_render_v1"


class BibtexRenderError(RuntimeError):
    """Raised when a cited source lacks sufficient provenance-backed metadata."""


@dataclass(frozen=True)
class BibtexRenderResult:
    content: str
    emitted_keys: tuple[str, ...]
    emitted_entries: tuple[dict[str, Any], ...]
    needs_completion: tuple[dict[str, Any], ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": BIBTEX_RENDER_SCHEMA_VERSION,
            "emitted_keys": list(self.emitted_keys),
            "emitted_entries": [deepcopy(entry) for entry in self.emitted_entries],
            "needs_completion": [deepcopy(entry) for entry in self.needs_completion],
        }


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _text(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _authors(value: object) -> list[str]:
    raw_authors = value if isinstance(value, list) else []
    authors: list[str] = []
    for raw_author in raw_authors:
        if isinstance(raw_author, Mapping):
            name = _text(raw_author.get("display_name") or raw_author.get("name") or raw_author.get("author"))
        else:
            name = _text(raw_author)
        if name and name not in authors:
            authors.append(name)
    return authors


def _paper_metadata(document: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """Resolve source records already frozen into the document or its source registry."""

    registry: dict[str, dict[str, Any]] = {}
    for raw in document.get("citation_registry") or []:
        record = _mapping(raw)
        source_id = _text(record.get("source_id"))
        if source_id:
            registry[source_id] = record
    return registry


def _field(record: Mapping[str, Any], name: str) -> object:
    if name in record:
        return record.get(name)
    metadata = _mapping(record.get("bibliographic_metadata"))
    return metadata.get(name)


def _completion_record(record: Mapping[str, Any], *, key: str, reason: str) -> dict[str, Any]:
    return {
        "citation_key": key,
        "source_id": _text(record.get("source_id")),
        "title": _text(_field(record, "title")),
        "doi": _text(_field(record, "doi")),
        "reason": reason,
        "required_fields": ["authors", "title", "year", "venue"],
        "status": "bibliography_needs_completion",
    }


def _bib_value(value: object, *, label: str) -> str:
    text = _text(value)
    if not text:
        raise BibtexRenderError(f"missing required BibTeX {label}")
    if contains_non_english_script(text):
        raise BibtexRenderError(
            f"BibTeX {label} contains non-English-script text; use an explicitly configured Unicode-capable profile after review"
        )
    try:
        return escape_latex_text(text, label=f"BibTeX {label}")
    except LatexSafetyError as error:
        raise BibtexRenderError(str(error)) from error


def _render_entry(record: Mapping[str, Any], *, key: str) -> tuple[str | None, dict[str, Any] | None]:
    authors = _authors(_field(record, "authors"))
    title = _text(_field(record, "title"))
    year = _text(_field(record, "year"))
    venue = _text(_field(record, "venue"))
    missing = [
        label
        for label, value in (("authors", authors), ("title", title), ("year", year), ("venue", venue))
        if not value
    ]
    if missing:
        return None, _completion_record(record, key=key, reason="missing_metadata:" + ",".join(missing))
    try:
        fields = [
            ("author", " and ".join(_bib_value(author, label="author") for author in authors)),
            ("title", _bib_value(title, label="title")),
            ("journal", _bib_value(venue, label="venue")),
            ("year", _bib_value(year, label="year")),
        ]
        doi = _text(_field(record, "doi"))
        url = _text(_field(record, "url"))
        if doi:
            fields.append(("doi", _bib_value(doi, label="doi")))
        if url:
            fields.append(("url", _bib_value(url, label="URL")))
    except BibtexRenderError as error:
        return None, _completion_record(record, key=key, reason=f"unsafe_metadata:{error}")
    rendered = "@article{" + key + ",\n" + ",\n".join(
        f"  {name} = {{{value}}}" for name, value in fields
    ) + "\n}\n"
    return rendered, None


def render_bibtex(document: Mapping[str, Any]) -> BibtexRenderResult:
    """Emit only fully identified citations; never make up missing bibliography fields."""

    registry = _paper_metadata(document)
    emitted: list[tuple[str, str, dict[str, Any]]] = []
    completion: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    for raw in document.get("citation_registry") or []:
        record = _mapping(raw)
        key_raw = _text(record.get("citation_key"))
        if not key_raw:
            continue
        try:
            key = validate_citation_key(key_raw)
        except LatexSafetyError as error:
            raise BibtexRenderError(str(error)) from error
        if key in seen_keys:
            raise BibtexRenderError(f"duplicate citation key in frozen document: {key}")
        seen_keys.add(key)
        source_id = _text(record.get("source_id"))
        source_record = registry.get(source_id, record)
        entry, needs_completion = _render_entry(source_record, key=key)
        if entry is None:
            if needs_completion is not None:
                completion.append(needs_completion)
            continue
        emitted.append(
            (
                key,
                entry,
                {
                    "citation_key": key,
                    "source_id": source_id,
                    "title": _text(_field(source_record, "title")),
                    "doi": _text(_field(source_record, "doi")),
                },
            )
        )
    emitted.sort(key=lambda item: item[0])
    completion.sort(key=lambda item: (item["citation_key"], item["source_id"]))
    return BibtexRenderResult(
        content="\n".join(entry.rstrip() for _key, entry, _metadata in emitted) + ("\n" if emitted else ""),
        emitted_keys=tuple(key for key, _entry, _metadata in emitted),
        emitted_entries=tuple(metadata for _key, _entry, metadata in emitted),
        needs_completion=tuple(completion),
    )


def required_citation_keys(document: Mapping[str, Any]) -> set[str]:
    """Return all claim-level citation keys without interpreting LLM prose."""

    keys: set[str] = set()
    for raw in document.get("claim_provenance") or []:
        record = _mapping(raw)
        for value in record.get("citation_keys") or []:
            try:
                keys.add(validate_citation_key(value))
            except LatexSafetyError as error:
                raise BibtexRenderError(str(error)) from error
    return keys


def ensure_citation_coverage(document: Mapping[str, Any], result: BibtexRenderResult) -> None:
    missing = sorted(required_citation_keys(document) - set(result.emitted_keys))
    if missing:
        raise BibtexRenderError(
            "document cites records that cannot be rendered without inventing metadata: " + ", ".join(missing)
        )


__all__ = [
    "BIBTEX_RENDER_SCHEMA_VERSION",
    "BibtexRenderError",
    "BibtexRenderResult",
    "ensure_citation_coverage",
    "render_bibtex",
    "required_citation_keys",
]
