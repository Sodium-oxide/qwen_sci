"""Domain-neutral document section structuring for evidence extraction."""

from __future__ import annotations

import json
import re
from typing import Any, Callable, Mapping
from uuid import NAMESPACE_URL, uuid5

try:
    from ._science_execution_policy import ScienceExecutionPolicy
except ImportError:
    from _science_execution_policy import ScienceExecutionPolicy


DOCUMENT_SCHEMA_VERSION = "document_version_v4"
DOCUMENT_DESCRIPTOR_SCHEMA_VERSION = "document_descriptor_v1"
DOCUMENT_SECTION_SCHEMA_VERSION = "document_section_v5"
DOCUMENT_SECTION_SET_SCHEMA_VERSION = "document_section_set_v6"
SOURCE_SPAN_SCHEMA_VERSION = "source_span_v6"

SECTION_TYPES = frozenset({
    "TITLE", "ABSTRACT", "INTRODUCTION", "METHODS", "RESULTS", "DISCUSSION",
    "CONCLUSION", "TABLE", "FIGURE_CAPTION", "SUPPLEMENT", "REFERENCES",
    "ACKNOWLEDGEMENTS", "METADATA", "BODY_SECTION", "UNKNOWN",
})
EXTRACTION_SECTION_TYPES = frozenset({
    "ABSTRACT", "INTRODUCTION", "METHODS", "RESULTS", "DISCUSSION",
    "CONCLUSION", "TABLE", "FIGURE_CAPTION", "SUPPLEMENT", "BODY_SECTION",
})
EXCLUDED_SECTION_TYPES = frozenset({"REFERENCES", "ACKNOWLEDGEMENTS", "METADATA"})

_HEADING_TYPE_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"^(?:references|bibliography|works cited|literature cited)$", re.I), "REFERENCES"),
    (re.compile(r"^(?:acknowledg(?:e)?ments?|funding)$", re.I), "ACKNOWLEDGEMENTS"),
    (re.compile(r"^(?:abstract|summary)$", re.I), "ABSTRACT"),
    (re.compile(r"^(?:introduction|background)$", re.I), "INTRODUCTION"),
    (re.compile(r"^(?:materials?\s+and\s+methods?|methods?|methodology|experimental procedures?)$", re.I), "METHODS"),
    (re.compile(r"^(?:results?|findings?)$", re.I), "RESULTS"),
    (re.compile(r"^(?:discussion|results?\s+and\s+discussion)$", re.I), "DISCUSSION"),
    (re.compile(r"^(?:conclusions?|concluding remarks?)$", re.I), "CONCLUSION"),
    (re.compile(r"^(?:supplementary|supplement|supporting information)$", re.I), "SUPPLEMENT"),
)
_NUMBERED_HEADING_RE = re.compile(r"^\s*(?:\d+(?:\.\d+)*[.)]?\s+)?(?P<title>[^\n]{2,100})\s*$")
_REFERENCE_ENTRY_RE = re.compile(
    r"^\s*(?:\[?\d{1,4}\]?\s*[.)]?\s+).*(?:\b(?:19|20)\d{2}\b|\bdoi\b|https?://)",
    re.I,
)


def _text(value: Any) -> str:
    return str(value or "").strip()


def _present(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, dict, set)):
        return bool(value)
    return True


def _paper_id(record: Mapping[str, Any]) -> str:
    return _text(record.get("paper_id") or record.get("doi") or record.get("url") or record.get("title"))


def _record_payload(record: Mapping[str, Any]) -> Mapping[str, Any]:
    value = record.get("papergraph_input")
    return value if isinstance(value, Mapping) else {}


def _raw_document_material(record: Mapping[str, Any]) -> dict[str, Any]:
    payload = _record_payload(record)
    fields = (
        "title", "abstract", "methods", "method", "results", "result",
        "discussion", "conclusion", "full_text_excerpt", "fulltext",
        "pdf_text", "extracted_text", "supplement", "supplement_text",
    )
    material = {
        field: record.get(field) if _present(record.get(field)) else payload.get(field)
        for field in fields
        if _present(record.get(field)) or _present(payload.get(field))
    }
    for candidate in (
        record.get("full_text_enrichment"), record.get("_full_text_enrichment"),
        payload.get("full_text_enrichment"), payload.get("_full_text_enrichment"),
    ):
        if isinstance(candidate, Mapping) and _present(candidate.get("canonical_text")):
            material["canonical_text"] = candidate.get("canonical_text")
            break
    return material


def _document_identity_material(record: Mapping[str, Any]) -> tuple[dict[str, Any], str]:
    material = _raw_document_material(record)
    canonical_text = material.get("canonical_text")
    if _present(canonical_text):
        return {"canonical_text": canonical_text}, "FULLTEXT_ACQUIRED"
    fulltext_fields = (
        "full_text_excerpt",
        "fulltext",
        "pdf_text",
        "extracted_text",
        "supplement",
        "supplement_text",
    )
    fulltext_material = {
        field: material[field]
        for field in fulltext_fields
        if _present(material.get(field))
    }
    if fulltext_material:
        return fulltext_material, "FULLTEXT_ACQUIRED"
    return {
        field: material[field]
        for field in ("title", "abstract")
        if _present(material.get(field))
    }, "METADATA_DISCOVERED"


def _derived_document_record(record: Mapping[str, Any]) -> dict[str, Any]:
    source = record if isinstance(record, Mapping) else {}
    identity_material, material_stage = _document_identity_material(source)
    explicit_version = _text(source.get("document_version_hash"))
    if explicit_version:
        version = explicit_version
    else:
        canonical = json.dumps(
            identity_material, ensure_ascii=False, sort_keys=True, default=str
        )
        version = uuid5(NAMESPACE_URL, f"{_paper_id(source)}|{canonical}").hex
    paper_id = _paper_id(source)
    return {
        "schema_version": DOCUMENT_SCHEMA_VERSION,
        "paper_id": paper_id,
        "document_id": "doc_" + uuid5(NAMESPACE_URL, paper_id).hex[:24],
        "document_version_id": "docv_" + uuid5(NAMESPACE_URL, f"{paper_id}|{version}").hex[:24],
        "document_version_hash": version,
        "title": _text(source.get("title")),
        "source_url": _text(source.get("source_pdf_url") or source.get("url")),
        "source_language": _text(source.get("source_language") or source.get("language")) or "UNSPECIFIED",
        "evidence_material_stage": material_stage,
    }


def validate_document_descriptor(
    descriptor: Mapping[str, Any],
    *,
    paper_id: str = "",
) -> dict[str, Any]:
    source = dict(descriptor or {})
    if source.get("schema_version") != DOCUMENT_DESCRIPTOR_SCHEMA_VERSION:
        raise ValueError("PREPARED_ARTIFACT_PROTOCOL_MISMATCH: invalid document descriptor schema")
    required = (
        "paper_id",
        "document_id",
        "document_version_id",
        "document_version_hash",
        "extractor_revision",
    )
    missing = [key for key in required if not _text(source.get(key))]
    if missing:
        raise ValueError(
            "PREPARED_ARTIFACT_PROTOCOL_MISMATCH: document descriptor missing "
            + ", ".join(missing)
        )
    if paper_id and _text(source.get("paper_id")) != _text(paper_id):
        raise ValueError("PREPARED_ARTIFACT_PROTOCOL_MISMATCH: descriptor paper_id changed")
    for ref_key in ("source_artifact_ref", "canonical_text_ref", "source_locator_ref"):
        value = source.get(ref_key)
        if value is not None and not isinstance(value, Mapping):
            raise ValueError(
                f"PREPARED_ARTIFACT_PROTOCOL_MISMATCH: {ref_key} must be an object"
            )
        source[ref_key] = dict(value or {})
    return source


def build_document_descriptor(
    record: Mapping[str, Any],
    *,
    extractor_revision: str = DOCUMENT_SCHEMA_VERSION,
    source_artifact_ref: Mapping[str, Any] | None = None,
    canonical_text_ref: Mapping[str, Any] | None = None,
    source_locator_ref: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    source = record if isinstance(record, Mapping) else {}
    document = _derived_document_record(source)
    existing = source.get("document_descriptor")
    if isinstance(existing, Mapping):
        validated = validate_document_descriptor(existing, paper_id=_paper_id(source))
        existing_stage = _text(validated.get("evidence_material_stage"))
        current_stage = _text(document.get("evidence_material_stage"))
        extractor_matches = _text(validated.get("extractor_revision")) == (
            _text(extractor_revision) or DOCUMENT_SCHEMA_VERSION
        )
        if extractor_matches and (
            existing_stage == "FULLTEXT_ACQUIRED"
            and current_stage == "METADATA_DISCOVERED"
            or existing_stage == current_stage == "METADATA_DISCOVERED"
            or existing_stage == current_stage == "FULLTEXT_ACQUIRED"
            and _text(validated.get("document_version_hash"))
            == _text(document.get("document_version_hash"))
        ):
            return validated
    return validate_document_descriptor({
        "schema_version": DOCUMENT_DESCRIPTOR_SCHEMA_VERSION,
        "paper_id": document["paper_id"],
        "document_id": document["document_id"],
        "document_version_id": document["document_version_id"],
        "document_version_hash": document["document_version_hash"],
        "title": document["title"],
        "source_url": document["source_url"],
        "source_language": document["source_language"],
        "evidence_material_stage": document["evidence_material_stage"],
        "extractor_revision": _text(extractor_revision) or DOCUMENT_SCHEMA_VERSION,
        "source_artifact_ref": dict(source_artifact_ref or {}),
        "canonical_text_ref": dict(canonical_text_ref or {}),
        "source_locator_ref": dict(source_locator_ref or {}),
    })


def build_document_record(record: Mapping[str, Any]) -> dict[str, Any]:
    source = record if isinstance(record, Mapping) else {}
    descriptor = source.get("document_descriptor")
    if isinstance(descriptor, Mapping):
        validated = validate_document_descriptor(descriptor, paper_id=_paper_id(source))
        return {
            "schema_version": DOCUMENT_SCHEMA_VERSION,
            "paper_id": validated["paper_id"],
            "document_id": validated["document_id"],
            "document_version_id": validated["document_version_id"],
            "document_version_hash": validated["document_version_hash"],
            "title": _text(validated.get("title") or source.get("title")),
            "source_url": _text(validated.get("source_url")),
            "source_language": _text(validated.get("source_language")) or "UNSPECIFIED",
            "evidence_material_stage": _text(
                validated.get("evidence_material_stage")
            ) or "METADATA_DISCOVERED",
        }
    return _derived_document_record(source)


def _heading_type(line: str) -> str:
    match = _NUMBERED_HEADING_RE.match(line)
    title = _text(match.group("title") if match else line).rstrip(":")
    for pattern, section_type in _HEADING_TYPE_PATTERNS:
        if pattern.fullmatch(title):
            return section_type
    return ""


def _looks_like_reference_block(text: str) -> bool:
    lines = [line for line in text.splitlines() if _text(line)]
    if not lines:
        return False
    matches = sum(bool(_REFERENCE_ENTRY_RE.search(line)) for line in lines[:20])
    return matches >= max(2, len(lines[:20]) // 2)


def _section(
    *,
    document: Mapping[str, Any],
    section_type: str,
    heading: str,
    text: str,
    char_start: int,
    char_end: int,
    source_field: str,
    parser_method: str,
    parser_confidence: float,
) -> dict[str, Any]:
    normalized_type = section_type if section_type in SECTION_TYPES else "UNKNOWN"
    if normalized_type != "REFERENCES" and _looks_like_reference_block(text):
        normalized_type = "REFERENCES"
        parser_method = "reference_pattern_guard"
        parser_confidence = 1.0
    section_id = "section_" + uuid5(
        NAMESPACE_URL,
        "|".join((
            _text(document.get("document_version_hash")), source_field,
            str(char_start), str(char_end), normalized_type,
        )),
    ).hex[:24]
    disposition = (
        "EXCLUDED_REFERENCES" if normalized_type == "REFERENCES"
        else "EXCLUDED_ACKNOWLEDGEMENTS"
        if normalized_type == "ACKNOWLEDGEMENTS"
        else "EXCLUDED_ADMINISTRATIVE"
        if normalized_type == "METADATA"
        else "INCLUDED"
    )
    return {
        "schema_version": DOCUMENT_SECTION_SCHEMA_VERSION,
        "section_id": section_id,
        "paper_id": _text(document.get("paper_id")),
        "document_version_hash": _text(document.get("document_version_hash")),
        "section_type": normalized_type,
        "section_disposition": disposition,
        "heading": _text(heading),
        "text": text.strip(),
        "char_start": max(0, int(char_start)),
        "char_end": max(int(char_start), int(char_end)),
        "source_field": source_field,
        "parser_method": parser_method,
        "parser_confidence": max(0.0, min(1.0, float(parser_confidence))),
        "extraction_eligible": disposition == "INCLUDED",
        "eligibility_reason_codes": (
            [] if disposition == "INCLUDED"
            else [f"{disposition}_NOT_PROPOSITION_SOURCE"]
        ),
    }


def _split_heading_sections(
    text: str,
    *,
    document: Mapping[str, Any],
    source_field: str,
) -> list[dict[str, Any]]:
    heading_matches: list[tuple[int, int, str, str]] = []
    cursor = 0
    for line in text.splitlines(keepends=True):
        line_start = cursor
        cursor += len(line)
        section_type = _heading_type(line)
        if section_type:
            heading_matches.append((line_start, cursor, _text(line), section_type))
    if not heading_matches:
        return [_section(
            document=document,
            section_type="REFERENCES" if _looks_like_reference_block(text) else "UNKNOWN",
            heading="",
            text=text,
            char_start=0,
            char_end=len(text),
            source_field=source_field,
            parser_method="reference_pattern_guard" if _looks_like_reference_block(text) else "unclassified_fulltext",
            parser_confidence=1.0 if _looks_like_reference_block(text) else 0.0,
        )]
    output: list[dict[str, Any]] = []
    first_start = heading_matches[0][0]
    if _text(text[:first_start]):
        output.append(_section(
            document=document, section_type="UNKNOWN", heading="", text=text[:first_start],
            char_start=0, char_end=first_start, source_field=source_field,
            parser_method="heading_parser", parser_confidence=0.4,
        ))
    for index, (start, content_start, heading, section_type) in enumerate(heading_matches):
        end = heading_matches[index + 1][0] if index + 1 < len(heading_matches) else len(text)
        output.append(_section(
            document=document, section_type=section_type, heading=heading,
            text=text[content_start:end], char_start=content_start, char_end=end,
            source_field=source_field, parser_method="heading_parser", parser_confidence=0.98,
        ))
    return [item for item in output if _text(item.get("text"))]


def _explicit_sections(record: Mapping[str, Any], document: Mapping[str, Any]) -> list[dict[str, Any]]:
    payload = _record_payload(record)
    definitions = (
        ("title", "TITLE"), ("abstract", "ABSTRACT"), ("methods", "METHODS"),
        ("method", "METHODS"), ("results", "RESULTS"), ("result", "RESULTS"),
        ("discussion", "DISCUSSION"), ("conclusion", "CONCLUSION"),
        ("supplement", "SUPPLEMENT"), ("supplement_text", "SUPPLEMENT"),
        ("references", "REFERENCES"), ("acknowledgements", "ACKNOWLEDGEMENTS"),
    )
    output: list[dict[str, Any]] = []
    for field, section_type in definitions:
        value = record.get(field) if _present(record.get(field)) else payload.get(field)
        values = value if isinstance(value, list) else [value]
        for index, item in enumerate(values):
            text = _text(item.get("text") if isinstance(item, Mapping) else item)
            if not text:
                continue
            output.append(_section(
                document=document, section_type=section_type, heading=field,
                text=text, char_start=0, char_end=len(text),
                source_field=f"{field}:{index}" if len(values) > 1 else field,
                parser_method="structured_source_field", parser_confidence=1.0,
            ))
    typed = (
        ("table_cells", "TABLE"), ("table_captions", "TABLE"),
        ("figure_captions", "FIGURE_CAPTION"), ("supplement_spans", "SUPPLEMENT"),
    )
    for field, section_type in typed:
        values = record.get(field) or payload.get(field) or []
        values = values if isinstance(values, list) else [values]
        for index, item in enumerate(values):
            text = _text(item.get("text") if isinstance(item, Mapping) else item)
            if text:
                output.append(_section(
                    document=document, section_type=section_type, heading=field,
                    text=text, char_start=0, char_end=len(text), source_field=f"{field}:{index}",
                    parser_method="structured_source_field", parser_confidence=1.0,
                ))
    return output


def _fulltext_value(record: Mapping[str, Any]) -> tuple[str, str]:
    payload = _record_payload(record)
    for field in ("full_text_excerpt", "fulltext", "pdf_text", "extracted_text"):
        value = record.get(field) if _present(record.get(field)) else payload.get(field)
        if _text(value):
            return field, str(value)
    return "", ""


def _native_pdf_enrichment(record: Mapping[str, Any]) -> dict[str, Any]:
    payload = _record_payload(record)
    candidates = (
        record.get("full_text_enrichment"), record.get("_full_text_enrichment"),
        payload.get("full_text_enrichment"), payload.get("_full_text_enrichment"),
    )
    pdf_source_declared = any(
        _text(source.get(field))
        for source in (record, payload)
        for field in ("open_access_pdf", "source_pdf_url", "pdf_url", "pdf_source")
    ) or any(
        re.search(r"\.pdf(?:[/?#]|$)", _text(source.get(field)), flags=re.I)
        for source in (record, payload)
        for field in ("source_path", "source_url")
    )
    native_candidates: list[dict[str, Any]] = []
    for value in candidates:
        if not isinstance(value, Mapping):
            continue
        conversion = (
            value.get("document_conversion_run")
            if isinstance(value.get("document_conversion_run"), Mapping)
            else {}
        )
        candidate_is_pdf = any((
            str(value.get("backend") or "") == "pymupdf_native",
            bool(value.get("raw_layout_pages")),
            _text(value.get("declared_type")).lower() == "pdf",
            _text(value.get("format")).lower() == "pdf",
            _text(conversion.get("declared_type")).lower() == "pdf",
            bool(re.search(r"\.pdf(?:[/?#]|$)", _text(value.get("source_path") or value.get("source_url")), flags=re.I)),
            pdf_source_declared,
        ))
        if not candidate_is_pdf:
            continue
        native_candidates.append(dict(value))
    return next(
        (
            value for value in native_candidates
            if _text(value.get("converter_version")) == "pymupdf_native_pdf_ingestion_v4"
        ),
        native_candidates[0] if native_candidates else {},
    )


def _native_section_set(record: Mapping[str, Any], document: Mapping[str, Any], enrichment: Mapping[str, Any]) -> dict[str, Any] | None:
    if _text(enrichment.get("converter_version")) != "pymupdf_native_pdf_ingestion_v4":
        return {
            "schema_version": DOCUMENT_SECTION_SET_SCHEMA_VERSION,
            "document": dict(document),
            "sections": [],
            "source_spans": [],
            "llm_chunks": [],
            "coverage_manifest": [],
            "status": "REEXTRACTION_REQUIRED",
            "reason_codes": ["PDF_INGESTION_SCHEMA_CUTOVER_REQUIRED"],
        }
    raw_sections = enrichment.get("sections")
    if not isinstance(raw_sections, list) or not raw_sections:
        return {
            "schema_version": DOCUMENT_SECTION_SET_SCHEMA_VERSION,
            "document": dict(document),
            "sections": [],
            "source_spans": [],
            "llm_chunks": [],
            "coverage_manifest": [],
            "status": "SECTION_STRUCTURE_PENDING",
            "reason_codes": ["PDF_NATIVE_SECTIONS_MISSING"],
        }
    raw_spans = enrichment.get("evidence_spans")
    spans = [dict(item) for item in raw_spans if isinstance(item, Mapping)] if isinstance(raw_spans, list) else []
    if any(
        _text(span.get("section_disposition")) not in {
            "INCLUDED",
            "EXCLUDED_REFERENCES",
            "EXCLUDED_ACKNOWLEDGEMENTS",
            "EXCLUDED_ADMINISTRATIVE",
        }
        or not _text(span.get("source_material_status"))
        for span in spans
    ):
        return {
            "schema_version": DOCUMENT_SECTION_SET_SCHEMA_VERSION,
            "document": dict(document),
            "sections": [],
            "source_spans": [],
            "llm_chunks": [],
            "coverage_manifest": [],
            "status": "REEXTRACTION_REQUIRED",
            "reason_codes": ["PDF_SOURCE_SPAN_V6_CUTOVER_REQUIRED"],
        }
    chunks = [dict(item) for item in enrichment.get("llm_chunks", []) if isinstance(item, Mapping)] if isinstance(enrichment.get("llm_chunks"), list) else []
    all_span_ids = {
        _text(span.get("source_span_id"))
        for span in spans
        if _text(span.get("source_span_id"))
    }
    eligible_span_ids = {
        _text(span.get("source_span_id"))
        for span in spans
        if _text(span.get("source_span_id")) and span.get("extraction_eligible", True)
    }
    chunk_by_span: dict[str, dict[str, Any]] = {}
    referenced_chunk_span_ids: set[str] = set()
    for chunk in chunks:
        chunk_id = _text(chunk.get("chunk_id"))
        chunk_text = _text(chunk.get("text"))
        for raw_span_id in chunk.get("source_span_ids") or []:
            span_id = _text(raw_span_id)
            if not span_id:
                continue
            referenced_chunk_span_ids.add(span_id)
            if chunk_id and chunk_text:
                chunk_by_span.setdefault(span_id, chunk)
    mapped_eligible_span_ids = eligible_span_ids.intersection(chunk_by_span)
    missing_chunk_span_ids = eligible_span_ids - mapped_eligible_span_ids
    unknown_chunk_span_ids = referenced_chunk_span_ids - all_span_ids
    chunk_plan_incomplete = bool(missing_chunk_span_ids or unknown_chunk_span_ids)
    span_by_section: dict[str, list[dict[str, Any]]] = {}
    for span in spans:
        span["schema_version"] = SOURCE_SPAN_SCHEMA_VERSION
        span["paper_id"] = _text(document.get("paper_id"))
        span["document_id"] = _text(document.get("document_id"))
        span["document_version_id"] = _text(document.get("document_version_id"))
        span["document_version_hash"] = _text(document.get("document_version_hash"))
        span.setdefault("quote", _text(span.get("text")))
        span.setdefault("excerpt", _text(span.get("text")))
        chunk = chunk_by_span.get(_text(span.get("source_span_id")))
        if chunk:
            span["llm_chunk_id"] = _text(chunk.get("chunk_id"))
            span["llm_chunk_text"] = _text(chunk.get("text"))
            span["llm_chunk_paragraph_ids"] = list(chunk.get("paragraph_ids") or [])
        span_by_section.setdefault(_text(span.get("section_id")), []).append(span)
    sections: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_sections, start=1):
        if not isinstance(raw, Mapping):
            continue
        section = dict(raw)
        disposition = _text(section.get("section_disposition")) or "INCLUDED"
        section["schema_version"] = DOCUMENT_SECTION_SCHEMA_VERSION
        section["section_id"] = _text(section.get("section_id")) or f"section_{index}"
        section["paper_id"] = _text(document.get("paper_id"))
        section["document_version_hash"] = _text(document.get("document_version_hash"))
        section.pop("section_type", None)
        section.pop("type", None)
        section["section_disposition"] = disposition
        section["source_field"] = "pdf_native"
        section["parser_method"] = _text(section.get("parser_method")) or "native_layout_heading_boundary"
        section["extraction_eligible"] = disposition == "INCLUDED"
        section.pop("direct_evidence_eligible", None)
        section["eligibility_reason_codes"] = (
            [] if disposition == "INCLUDED"
            else [f"{disposition}_NOT_PROPOSITION_SOURCE"]
        )
        related = span_by_section.get(section["section_id"], [])
        section["char_start"] = min((int(item.get("offset_start") or 0) for item in related), default=int(section.get("char_start") or 0))
        section["char_end"] = max((int(item.get("offset_end") or 0) for item in related), default=int(section.get("char_end") or section["char_start"]))
        sections.append(section)
    if not sections:
        return None
    coverage = [
        {
            "source_span_id": _text(span.get("source_span_id")),
            "section_heading": _text(span.get("section_heading")),
            "section_disposition": _text(span.get("section_disposition")),
            "status": "PENDING" if span.get("extraction_eligible", True) else "SKIPPED",
            "reason_codes": list(span.get("eligibility_reason_codes") or []),
        }
        for span in spans
        if _text(span.get("source_span_id"))
    ]
    ingestion_status = _text(enrichment.get("ingestion_status") or enrichment.get("status"))
    if not spans:
        section_set_status = "SPAN_STRUCTURE_REPAIR_REQUIRED"
    elif chunk_plan_incomplete:
        section_set_status = "SPAN_STRUCTURE_REPAIR_REQUIRED"
    elif ingestion_status in {"TEXT_READY", "extracted"}:
        section_set_status = "STRUCTURED"
    elif ingestion_status in {
        "SPAN_STRUCTURE_REPAIR_REQUIRED",
        "SECTION_STRUCTURE_PENDING",
        "TEXT_INTEGRITY_FAILED",
        "SOURCE_LOCATORS_INCOMPLETE",
        "NEEDS_OCR",
        "DOCUMENT_INGESTION_FAILED",
    }:
        section_set_status = ingestion_status
    else:
        section_set_status = "STRUCTURING_PENDING"
    return {
        "schema_version": DOCUMENT_SECTION_SET_SCHEMA_VERSION,
        "document": dict(document),
        "sections": sections,
        "source_spans": spans,
        "llm_chunks": chunks,
        "llm_chunk_plan_quality": {
            "status": "INCOMPLETE" if chunk_plan_incomplete else "PASS",
            "eligible_span_count": len(eligible_span_ids),
            "mapped_eligible_span_count": len(mapped_eligible_span_ids),
            "missing_eligible_span_count": len(missing_chunk_span_ids),
            "unknown_span_reference_count": len(unknown_chunk_span_ids),
            "missing_eligible_span_ids": sorted(missing_chunk_span_ids)[:50],
            "unknown_span_reference_ids": sorted(unknown_chunk_span_ids)[:50],
        },
        "coverage_manifest": coverage,
        "status": section_set_status,
        "reason_codes": list(dict.fromkeys([
            *list(enrichment.get("reason_codes") or []),
            *list(enrichment.get("converter_warnings") or []),
            *(["PDF_NATIVE_SOURCE_SPANS_MISSING"] if not spans else []),
            *(["PDF_NATIVE_LLM_CHUNK_PLAN_INCOMPLETE"] if chunk_plan_incomplete else []),
        ])),
    }


def _default_llm_call(**kwargs: Any) -> dict[str, Any]:
    try:
        from ._llm import call_llm_json
    except ImportError:
        from _llm import call_llm_json
    return call_llm_json(**kwargs)


def _classify_unknown_sections(
    sections: list[dict[str, Any]],
    *,
    llm_call: Callable[..., dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[str]]:
    unknown = [item for item in sections if item.get("section_type") == "UNKNOWN"]
    if not unknown:
        return sections, []
    errors: list[str] = []
    updates: dict[str, str] = {}
    for offset in range(0, len(unknown), 16):
        batch = unknown[offset:offset + 16]
        try:
            payload = llm_call(
                system=(
                    "Classify scientific-document sections from the supplied text only. "
                    "Return JSON only. Never classify bibliography entries as results or discussion."
                ),
                prompt=(
                    "Return {\"sections\":[{\"section_id\":...,\"section_type\":...}]} using only "
                    f"these labels: {json.dumps(sorted(SECTION_TYPES))}. "
                    "Use UNKNOWN when a block mixes section types or lacks enough structure.\n"
                    + json.dumps([
                        {"section_id": item["section_id"], "text": _text(item.get("text"))[:6000]}
                        for item in batch
                    ], ensure_ascii=False)
                ),
                max_tokens=1200,
            )
        except Exception as exc:
            errors.append(f"SECTION_CLASSIFICATION_FAILED:{type(exc).__name__}")
            continue
        for item in payload.get("sections", []):
            if not isinstance(item, Mapping):
                continue
            section_id = _text(item.get("section_id"))
            section_type = _text(item.get("section_type")).upper()
            if section_id and section_type in SECTION_TYPES:
                updates[section_id] = section_type
    output: list[dict[str, Any]] = []
    for section in sections:
        current = dict(section)
        classified = updates.get(_text(current.get("section_id")))
        if classified and classified != "UNKNOWN":
            if classified != "REFERENCES" and _looks_like_reference_block(_text(current.get("text"))):
                classified = "REFERENCES"
            current.update({
                "section_type": classified,
                "parser_method": "llm_section_classifier_then_structure_guard",
                "parser_confidence": 0.8,
                "extraction_eligible": classified in EXTRACTION_SECTION_TYPES,
                "eligibility_reason_codes": (
                    [] if classified not in EXCLUDED_SECTION_TYPES
                    else [f"SECTION_{classified}_NOT_PROPOSITION_SOURCE"]
                ),
            })
        output.append(current)
    return output, errors


def structure_document_sections(
    record: Mapping[str, Any],
    policy: ScienceExecutionPolicy,
    *,
    llm_call: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    document = build_document_record(record)
    native_enrichment = _native_pdf_enrichment(record)
    if native_enrichment:
        native_set = _native_section_set(record, document, native_enrichment)
        if native_set is not None:
            return native_set
    sections = _explicit_sections(record, document)
    fulltext_field, fulltext = _fulltext_value(record)
    if fulltext:
        sections.extend(_split_heading_sections(
            fulltext, document=document, source_field=fulltext_field
        ))
    errors: list[str] = []
    if any(item.get("section_type") == "UNKNOWN" for item in sections):
        if policy.use_llm and policy.fulltext_structuring_mode == "llm_primary":
            sections, errors = _classify_unknown_sections(
                sections, llm_call=llm_call or _default_llm_call
            )
        else:
            errors.append("SECTION_CLASSIFICATION_LLM_DISABLED")
    status = "STRUCTURED"
    if errors:
        status = "STRUCTURING_PENDING"
    return {
        "schema_version": DOCUMENT_SECTION_SET_SCHEMA_VERSION,
        "document": document,
        "sections": sections,
        "status": status,
        "reason_codes": errors,
    }
