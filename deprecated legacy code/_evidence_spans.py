"""Source-addressable V6 evidence spans and coverage scheduling."""

from __future__ import annotations

import re
from typing import Any, Mapping
from uuid import NAMESPACE_URL, uuid5


SOURCE_SPAN_SCHEMA_VERSION = "source_span_v6"
EVIDENCE_SPAN_SET_SCHEMA_VERSION = "evidence_span_set_v6"
_SENTENCE_RE = re.compile(r"[^\n.!?。！？；;]+(?:[.!?。！？；;]+|$)")


def _text(value: Any) -> str:
    return str(value or "").strip()


def build_evidence_spans(section_set: Mapping[str, Any]) -> dict[str, Any]:
    document = section_set.get("document") if isinstance(section_set.get("document"), Mapping) else {}
    native_spans = section_set.get("source_spans")
    if isinstance(native_spans, list):
        spans = [dict(item) for item in native_spans if isinstance(item, Mapping)]
        if any(
            _text(span.get("schema_version")) != SOURCE_SPAN_SCHEMA_VERSION
            or _text(span.get("section_disposition")) not in {
                "INCLUDED",
                "EXCLUDED_REFERENCES",
                "EXCLUDED_ACKNOWLEDGEMENTS",
                "EXCLUDED_ADMINISTRATIVE",
            }
            or not _text(span.get("source_material_status"))
            for span in spans
        ):
            return {
                "schema_version": EVIDENCE_SPAN_SET_SCHEMA_VERSION,
                "document": dict(document),
                "sections": [],
                "source_spans": [],
                "llm_chunks": [],
                "coverage_manifest": [],
                "status": "REEXTRACTION_REQUIRED",
                "reason_codes": ["SOURCE_SPAN_V6_CUTOVER_REQUIRED"],
            }
        native_to_stable_ids: dict[str, str] = {}
        for index, span in enumerate(spans, start=1):
            native_span_id = _text(
                span.get("source_span_id") or span.get("span_id") or f"span_{index}"
            )
            stable_span_id = "span_" + uuid5(
                NAMESPACE_URL,
                "|".join((
                    _text(
                        document.get("document_version_hash")
                        or document.get("document_version_id")
                    ),
                    _text(span.get("source_locator")),
                    _text(span.get("section_id")),
                    _text(span.get("paragraph_id")),
                    str(span.get("paragraph_char_start") or span.get("char_start") or 0),
                    str(span.get("paragraph_char_end") or span.get("char_end") or 0),
                    _text(span.get("quote") or span.get("text")),
                )),
            ).hex[:24]
            native_to_stable_ids[native_span_id] = stable_span_id
            span["schema_version"] = SOURCE_SPAN_SCHEMA_VERSION
            span["native_source_span_id"] = native_span_id
            span["span_id"] = stable_span_id
            span["source_span_id"] = stable_span_id
            span["source_unit_id"] = stable_span_id
            span.setdefault("quote", _text(span.get("text")))
            span.setdefault("excerpt", _text(span.get("text")))
            span.setdefault("document_version_hash", _text(document.get("document_version_hash")))
            span.setdefault("paper_id", _text(document.get("paper_id")))
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
        llm_chunks = [
            dict(item)
            for item in section_set.get("llm_chunks", [])
            if isinstance(item, Mapping)
        ]
        for chunk in llm_chunks:
            chunk["source_span_ids"] = [
                native_to_stable_ids.get(_text(span_id), _text(span_id))
                for span_id in chunk.get("source_span_ids", [])
                if _text(span_id)
            ]
        return {
            "schema_version": EVIDENCE_SPAN_SET_SCHEMA_VERSION,
            "document": dict(document),
            "sections": [dict(item) for item in section_set.get("sections", []) if isinstance(item, Mapping)],
            "source_spans": spans,
            "llm_chunks": llm_chunks,
            "coverage_manifest": coverage,
            "status": str(section_set.get("status") or "STRUCTURED"),
            "reason_codes": list(section_set.get("reason_codes") or []),
        }
    spans: list[dict[str, Any]] = []
    for section in section_set.get("sections", []):
        if not isinstance(section, Mapping):
            continue
        section_text = str(section.get("text") or "")
        if not section_text.strip():
            continue
        section_heading = _text(section.get("heading") or section.get("section"))
        section_disposition = _text(section.get("section_disposition")) or "INCLUDED"
        chunks = list(_SENTENCE_RE.finditer(section_text))
        for index, match in enumerate(chunks):
            if match is None:
                continue
            raw = match.group(0)
            left_trim = len(raw) - len(raw.lstrip())
            right_trimmed = raw.rstrip()
            if not right_trimmed.strip():
                continue
            local_start = match.start() + left_trim
            local_end = match.start() + len(right_trimmed)
            quote = section_text[local_start:local_end]
            source_field = _text(section.get("source_field"))
            span_id = "span_" + uuid5(
                NAMESPACE_URL,
                "|".join((
                    _text(document.get("document_version_hash")),
                    _text(section.get("section_id")), str(local_start), str(local_end), quote,
                )),
            ).hex[:24]
            extraction_eligible = (
                section.get("extraction_eligible") is True
                and section_disposition == "INCLUDED"
            )
            spans.append({
                "schema_version": SOURCE_SPAN_SCHEMA_VERSION,
                "source_span_id": span_id,
                "source_unit_id": span_id,
                "paper_id": _text(document.get("paper_id")),
                "document_id": _text(document.get("document_id")),
                "document_version_id": _text(document.get("document_version_id")),
                "document_version_hash": _text(document.get("document_version_hash")),
                "section_id": _text(section.get("section_id")),
                "section": section_heading,
                "section_heading": section_heading,
                "section_number": _text(section.get("number")),
                "section_disposition": section_disposition,
                "source_field": source_field,
                "span_kind": "body_sentence",
                "source_type": "fulltext",
                "source_locator": f"{source_field}:{_text(section.get('section_id'))}:{index + 1}",
                "char_start": int(section.get("char_start") or 0) + local_start,
                "char_end": int(section.get("char_start") or 0) + local_end,
                "quote": quote,
                "excerpt": quote,
                "binding_status": "SOURCE_UNIT_VERIFIED",
                "evidence_material_stage": "SPAN_EXTRACTED",
                "extraction_eligible": extraction_eligible,
                "source_material_status": (
                    "SOURCE_BOUND_FULLTEXT"
                    if extraction_eligible else "EXCLUDED_SECTION"
                ),
                "eligibility_reason_codes": list(section.get("eligibility_reason_codes") or []),
                "parser_method": _text(section.get("parser_method")),
                "parser_confidence": section.get("parser_confidence"),
            })
    coverage = [{
        "source_span_id": span["source_span_id"],
        "section_heading": span["section_heading"],
        "section_disposition": span["section_disposition"],
        "status": "PENDING" if span["extraction_eligible"] else "SKIPPED",
        "reason_codes": [] if span["extraction_eligible"] else list(span["eligibility_reason_codes"]),
    } for span in spans]
    return {
        "schema_version": EVIDENCE_SPAN_SET_SCHEMA_VERSION,
        "document": dict(document),
        "sections": [
            dict(item) for item in section_set.get("sections", [])
            if isinstance(item, Mapping)
        ],
        "source_spans": spans,
        "coverage_manifest": coverage,
        "status": str(section_set.get("status") or "STRUCTURED"),
        "reason_codes": list(section_set.get("reason_codes") or []),
    }
