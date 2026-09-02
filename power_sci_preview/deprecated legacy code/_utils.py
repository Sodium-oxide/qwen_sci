from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any
import ast
import json
import re
import time
import xml.etree.ElementTree as ET

try:
    from .config import (
        WORKDIR,
    )
except ImportError:
    from config import (
        WORKDIR,
    )



def repair_project_extraction_quality(
    project: dict[str, Any],
    *,
    max_full_text_attempts: int = 3,
) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        from ._literature_import import extraction_quality_report, maybe_llm_reextract_structure, repair_payload_fields, sync_evidence_from_record
        from ._literature_search import enrich_papergraph_payload
    except ImportError:
        from _literature_import import extraction_quality_report, maybe_llm_reextract_structure, repair_payload_fields, sync_evidence_from_record
        from _literature_search import enrich_papergraph_payload
    repaired = 0
    attempted = 0
    still_low_quality = 0
    full_text_attempted = 0
    full_text_deferred = 0
    errors: list[str] = []
    records = project.get("papergraph", [])
    if not isinstance(records, list):
        return project, {
            "attempted": 0,
            "repaired": 0,
            "still_low_quality": 0,
            "full_text_attempted": 0,
            "full_text_deferred": 0,
            "errors": [],
        }

    full_text_budget = max(0, int(max_full_text_attempts or 0))

    for record in records:
        if not isinstance(record, dict):
            continue
        before_quality = extraction_quality_report(record)
        record["extraction_quality"] = before_quality
        payload = dict(record)
        full_text_state = record.get("full_text_enrichment") if isinstance(record.get("full_text_enrichment"), dict) else {}
        full_text_status = str(full_text_state.get("status") or "")
        needs_full_text_repair = (
            not normalize_space(str(record.get("full_text_excerpt") or ""))
            and (not full_text_status or full_text_enrichment_retry_due(full_text_state))
            and bool(
                record.get("open_access_pdf")
                or record.get("doi")
                or record.get("arxiv_id")
                or record.get("pmcid")
                or record.get("pmc_id")
            )
        )
        include_full_text = needs_full_text_repair and full_text_attempted < full_text_budget
        if needs_full_text_repair and not include_full_text:
            full_text_deferred += 1
        needs_expensive_repair = bool(
            before_quality.get("needs_enrichment")
            or before_quality.get("needs_llm_retry")
            or include_full_text
        )
        before_core = {
            key: normalize_label(record.get(key, ""))
            for key in ("method", "scenario", "benchmark", "contribution", "limitation")
        }
        if not needs_expensive_repair:
            repaired_payload = repair_payload_fields(payload)
            after_quality = extraction_quality_report(repaired_payload)
            after_quality["initial"] = before_quality
            after_quality["llm_retry"] = {"attempted": False, "succeeded": False, "error": ""}
            record.update(repaired_payload)
            record["extraction_quality"] = after_quality
            after_core = {
                key: normalize_label(record.get(key, ""))
                for key in ("method", "scenario", "benchmark", "contribution", "limitation")
            }
            if after_core != before_core or after_quality.get("requires_human_review"):
                repaired += 1
                sync_evidence_from_record(project, record)
            if after_quality.get("requires_human_review"):
                still_low_quality += 1
            continue
        attempted += 1
        sources: list[str] = []
        if before_quality.get("needs_enrichment") or include_full_text:
            try:
                payload, sources = enrich_papergraph_payload(payload, record, include_full_text=include_full_text)
                if include_full_text:
                    full_text_attempted += 1
            except Exception as exc:
                errors.append(f"{record.get('paper_id')}: enrichment failed: {exc}")
        llm_retry: dict[str, Any] = {"attempted": False, "succeeded": False, "error": ""}
        full_text_result = payload.get("_full_text_enrichment") if isinstance(payload.get("_full_text_enrichment"), dict) else {}
        full_text_extracted = str(full_text_result.get("status") or "") == "extracted"
        if extraction_quality_report(payload).get("needs_llm_retry") or full_text_extracted:
            payload, llm_retry = maybe_llm_reextract_structure(payload, force=full_text_extracted)
            if llm_retry.get("error"):
                errors.append(f"{record.get('paper_id')}: llm retry failed: {llm_retry.get('error')}")

        repaired_payload = repair_payload_fields(payload)
        after_quality = extraction_quality_report(repaired_payload)
        after_quality["initial"] = before_quality
        after_quality["llm_retry"] = llm_retry
        if repaired_payload.get("_enrichment_errors"):
            after_quality["enrichment_errors"] = repaired_payload.get("_enrichment_errors")
        repaired_payload.pop("_enrichment_errors", None)
        full_text_result = repaired_payload.pop("_full_text_enrichment", full_text_result)
        record.update(repaired_payload)
        if isinstance(full_text_result, dict):
            record["full_text_enrichment"] = full_text_result
            after_quality["full_text"] = full_text_result
        record["extraction_quality"] = after_quality
        existing_sources = record.get("enrichment_sources") if isinstance(record.get("enrichment_sources"), list) else []
        record["enrichment_sources"] = unique_preserve_order([*existing_sources, *sources])
        if after_quality.get("score", 0) > before_quality.get("score", 0):
            repaired += 1
        if after_quality.get("requires_human_review"):
            still_low_quality += 1
        sync_evidence_from_record(project, record)

    return project, {
        "attempted": attempted,
        "repaired": repaired,
        "still_low_quality": still_low_quality,
        "full_text_attempted": full_text_attempted,
        "full_text_deferred": full_text_deferred,
        "errors": errors[:10],
    }


def full_text_enrichment_retry_due(state: dict[str, Any], now: float | None = None) -> bool:
    status = str(state.get("status") or "")
    if status not in {"metadata_lookup_failed", "fetch_failed"}:
        return False
    retry_after = max(60.0, float(state.get("retry_after_seconds") or 900.0))
    attempted_at = float(state.get("attempted_at") or 0.0)
    current_time = time.time() if now is None else float(now)
    return attempted_at <= 0 or current_time - attempted_at >= retry_after

def science_term_in_text(term: str, lowered_text: str) -> bool:
    clean = normalize_space(term).lower()
    if not clean:
        return False
    if re.fullmatch(r"[a-z0-9][a-z0-9_-]*", clean):
        return re.search(rf"\b{re.escape(clean)}\b", lowered_text) is not None
    return clean in lowered_text

def is_unknown_value(value: Any) -> bool:
    text = normalize_space(str(value or "")).lower()
    return not text or text.startswith("unknown") or text in {"none", "n/a", "unspecified", "unspecified benchmark"}

def repair_unknown_field(value: Any, text: str, field: str) -> str:
    try:
        from ._literature_import import infer_generic_science_phrase, infer_ontology_field, is_low_information_field
    except ImportError:
        from _literature_import import infer_generic_science_phrase, infer_ontology_field, is_low_information_field
    current = normalize_space(value)
    if field == "benchmark" and current.lower() in {"benchmark dataset", "benchmark data", "benchmark"}:
        current = ""
    if (
        current
        and not current.lower().startswith("unknown")
        and current.lower() not in {"unspecified benchmark", "none", "n/a"}
        and not is_low_information_field(current, field)
    ):
        return current
    inferred = infer_ontology_field(text, field)
    if inferred:
        return inferred
    phrase = infer_generic_science_phrase(text, field)
    if phrase:
        return phrase
    return {
        "method": "unknown method",
        "scenario": "unknown scenario",
        "benchmark": "unknown benchmark",
    }.get(field, "unknown")

def record_context_text(record: dict[str, Any]) -> str:
    return "\n".join(
        str(record.get(key, ""))
        for key in (
            "title",
            "abstract",
            "conclusion",
            "full_text_excerpt",
            "gap_signals",
            "contribution",
            "limitation",
            "method",
            "scenario",
            "benchmark",
        )
        if record.get(key)
    )

def extract_year(text: str) -> str:
    try:
        from ._literature_import import extract_labeled_value
    except ImportError:
        from _literature_import import extract_labeled_value
    raw = extract_labeled_value(text, ["year", "published", "publication year"])
    match = re.search(r"\b(19|20)\d{2}\b", raw or text)
    return match.group(0) if match else ""

def extract_section(text: str, headings: list[str]) -> str:
    if not text:
        return ""
    heading_pattern = "|".join(re.escape(heading) for heading in headings)
    pattern = re.compile(
        rf"(?:^|\n)\s*(?:\d+\.?\s*)?(?:{heading_pattern})\s*[:\n]\s*(.*?)(?=\n\s*(?:\d+\.?\s*)?[A-Z][A-Za-z ]{{2,30}}\s*[:\n]|\Z)",
        flags=re.IGNORECASE | re.DOTALL,
    )
    match = pattern.search(text)
    if not match:
        return ""
    return trim_text(match.group(1), 1500)

def safe_workspace_path(path: str) -> Path:
    raw = Path(path).expanduser()
    candidate = raw if raw.is_absolute() else WORKDIR / raw
    resolved = candidate.resolve()
    if not resolved.is_relative_to(WORKDIR):
        raise ValueError(f"Path escapes workspace: {path}")
    if not resolved.exists() or not resolved.is_file():
        raise ValueError(f"Literature file not found: {path}")
    return resolved

def read_literature_file(path: Path) -> str:
    if path.suffix.lower() == ".pdf":
        try:
            from ._pdf_extraction import convert_pdf_to_markdown
        except ImportError as exc:
            try:
                from _pdf_extraction import convert_pdf_to_markdown
            except ImportError:
                raise exc
        return convert_pdf_to_markdown(path)
    if path.suffix.lower() in {".docx", ".xlsx", ".html", ".htm", ".epub"}:
        try:
            from ._document_conversion import convert_literature_document
        except ImportError as exc:
            try:
                from _document_conversion import convert_literature_document
            except ImportError:
                raise exc
        return convert_literature_document(path).markdown
    if path.suffix.lower() not in {".txt", ".md", ".markdown", ".csv", ".json", ".xml", ".bib", ".ris"}:
        raise ValueError(
            f"Unsupported literature document format: {path.suffix or '(none)'}. "
            "Allowed document conversions are PDF, DOCX, XLSX, HTML, and EPUB."
        )
    return path.read_text(encoding="utf-8", errors="replace")

def normalize_space(text: str) -> str:
    text = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()

def xml_text(element: ET.Element, path: str, ns: dict[str, str]) -> str:
    found = element.find(path, ns)
    return "" if found is None or found.text is None else str(found.text)

def clamp_int(value: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = minimum
    return max(minimum, min(maximum, parsed))

def numeric_value(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0

def scalar(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, dict)):
        return normalize_space(json.dumps(value, ensure_ascii=False))
    return normalize_space(str(value))

def string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [trim_text(scalar(item), 300) for item in value if scalar(item)]
    if isinstance(value, str):
        if not value.strip():
            return []
        parts = re.split(r"\s*(?:\n|;|\u2022|\d+\.)\s*", value)
        return [trim_text(part, 300) for part in parts if part.strip()]
    return [trim_text(scalar(value), 300)] if scalar(value) else []

def split_sentences(text: str) -> list[str]:
    normalized = normalize_space(text).replace("\n", " ")
    return [sentence.strip() for sentence in re.split(r"(?<=[.!?。！？])\s+", normalized) if sentence.strip()]

def first_sentences(text: str, count: int) -> str:
    return trim_text(" ".join(split_sentences(text)[:count]), 1500)

def last_sentences(text: str, count: int) -> str:
    sentences = split_sentences(text)
    return trim_text(" ".join(sentences[-count:]), 1500)

def first_nonempty(values: list[str]) -> str:
    for value in values:
        if value.strip():
            return value.strip()
    return ""

def unique_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        normalized = value.strip()
        key = normalized.lower()
        if normalized and key not in seen:
            result.append(normalized)
            seen.add(key)
    return result

def trim_text(text: str, limit: int) -> str:
    normalized = normalize_space(text)
    if len(normalized) <= limit:
        return normalized
    return normalized[:limit].rstrip() + "...[truncated]"

def references_for_gap(project: dict[str, Any], gap_id: str) -> list[str]:
    gap = find_by_id(project.get("knowledge_gaps", []), "gap_id", gap_id)
    if gap is None:
        return []
    return [str(ref) for ref in gap.get("supporting_references", []) if str(ref)]

def find_by_id(items: list[dict[str, Any]], key: str, value: str) -> dict[str, Any] | None:
    for item in items:
        if item.get(key) == value:
            return item
    return None

def normalize_label(value: Any) -> str:
    text = str(value or "unknown").strip()
    return text or "unknown"

def normalize_key(value: str) -> str:
    text = str(value).strip().lower().replace("-", "_").replace(" ", "_")
    safe = "".join(char for char in text if char.isalnum() or char == "_")
    return safe or "item"

def new_id(prefix: str) -> str:
    return f"{prefix}_{time.time_ns()}"

def extract_task_id(text: str) -> str:
    match = re.search(r"task_\d+_\d+", text)
    return match.group(0) if match else ""

