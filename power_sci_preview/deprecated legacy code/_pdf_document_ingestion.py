"""Native, page-aware PDF ingestion for scientific evidence.

The module deliberately separates PDF layout fidelity from semantic extraction.
PyMuPDF objects are retained as the raw source, while paragraphs, sections and
LLM chunks are derived views with source references back to those objects.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import math
import re
from typing import Any, Iterable, Mapping
import unicodedata


RAW_SCHEMA_VERSION = "pdf_raw_layout_v2"
INGESTION_SCHEMA_VERSION = "pdf_document_ingestion_v4"
TEXT_QUALITY_SCHEMA_VERSION = "pdf_text_layer_quality_v1"
STRUCTURE_QUALITY_SCHEMA_VERSION = "pdf_structure_quality_v2"

NUMBERED_HEADING_RE = re.compile(
    r"^\s*(?P<number>\d+(?:\.\d+)*)"
    r"(?P<separator>[.)]?)\s*(?P<title>\S.{1,160})$",
    re.IGNORECASE,
)
ROMAN_HEADING_RE = re.compile(
    r"^\s*(?P<number>[IVXLC]+)(?P<separator>[.)]|\s+)"
    r"\s*(?P<title>\S.{1,160})$",
    re.IGNORECASE,
)
MARKDOWN_HEADING_RE = re.compile(r"^\s*#{1,6}\s+(?P<title>.+?)\s*#*\s*$")
REFERENCES_HEADINGS = frozenset({
    "references", "bibliography", "literature cited", "works cited",
})
ACKNOWLEDGEMENT_HEADINGS = frozenset({
    "acknowledgement", "acknowledgements", "acknowledgment", "acknowledgments",
})
ADMINISTRATIVE_HEADINGS = frozenset({
    "funding", "author contribution", "author contributions",
    "conflict of interest", "conflicts of interest", "publisher note",
    "publishers note", "copyright", "license", "licence",
    "copyright and license", "copyright and licence", "licensing",
})


@dataclass
class _Line:
    page: int
    block: int
    line: int
    text: str
    bbox: tuple[float, float, float, float]
    font_size: float
    font_flags: int
    font: str
    column: int
    page_height: float
    raw_spans: tuple[dict[str, Any], ...]


def _text(value: Any) -> str:
    return str(value or "").strip()


def _bbox(value: Iterable[Any]) -> tuple[float, float, float, float]:
    values = list(value or [])
    if len(values) < 4:
        return (0.0, 0.0, 0.0, 0.0)
    return tuple(round(float(item), 3) for item in values[:4])  # type: ignore[return-value]


def _clean_line_text(value: str) -> str:
    value = str(value or "").replace("\u00a0", " ").replace("\r", "")
    return re.sub(r"[ \t]+", " ", value).strip()


def _normalize_heading(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", _clean_line_text(value)).casefold()
    normalized = normalized.replace("’", "'").replace("&", " and ")
    normalized = normalized.replace("'", "")
    normalized = re.sub(r"^[#\s]*", "", normalized)
    normalized = re.sub(r"[\s:.;,()\[\]{}'\-_/]+", " ", normalized)
    return " ".join(normalized.split())


def _section_disposition(heading: str) -> str:
    normalized = _normalize_heading(heading)
    if normalized in REFERENCES_HEADINGS:
        return "EXCLUDED_REFERENCES"
    if normalized in ACKNOWLEDGEMENT_HEADINGS:
        return "EXCLUDED_ACKNOWLEDGEMENTS"
    if normalized in ADMINISTRATIVE_HEADINGS:
        return "EXCLUDED_ADMINISTRATIVE"
    return "INCLUDED"


def _line_height(line: _Line) -> float:
    return max(1.0, line.bbox[3] - line.bbox[1])


def _equation_like_heading_title(value: str) -> bool:
    title = _clean_line_text(value)
    if not re.search(r"[=∼≈≃≤≥±×÷]", title):
        return False
    symbolic_term = bool(
        re.search(r"(?:[A-Za-zΑ-Ωα-ω]\d|[δ∆εξℓλμσ][A-Za-z0-9]*|\([^)]{1,12}\))", title)
    )
    words = re.findall(r"[^\W\d_]+", title, flags=re.UNICODE)
    return symbolic_term and len(words) <= 8


def _heading_info(text: str, line: _Line) -> dict[str, Any] | None:
    clean = _clean_line_text(text)
    if not clean or len(clean) > 220:
        return None
    if re.match(r"^(?:fig(?:ure)?|table|chart|scheme|plate)\s*[A-Z0-9IVXLC.-]*\s*[:.]?\s*", clean, re.I):
        return None
    if line.page_height > 0 and line.bbox[1] >= line.page_height * 0.92:
        return None
    markdown = MARKDOWN_HEADING_RE.match(clean)
    number_match = NUMBERED_HEADING_RE.match(clean) or ROMAN_HEADING_RE.match(clean)
    number = ""
    title = clean
    if markdown:
        title = _clean_line_text(markdown.group("title"))
    elif number_match:
        number = _text(number_match.group("number"))
        title = _clean_line_text(number_match.group("title"))
        if title.startswith("-"):
            return None
        if "." not in number and len(title) <= 3:
            return None
    disposition = _section_disposition(title)
    if re.search(r"[!?。！？]$", clean) and not number_match and not markdown:
        return None
    if not markdown and not number_match:
        words = re.findall(r"\w+", clean)
        if len(words) > 14:
            return None
        if disposition == "INCLUDED" and len(words) <= 1 and len(clean) <= 12:
            return None
        if (
            disposition == "INCLUDED"
            and re.fullmatch(r"(?:[A-Z][a-z]+,?\s*){1,3}(?:[A-Z]\.){0,3}", clean)
        ):
            return None
    title_words = re.findall(r"[^\W\d_]+", title, flags=re.UNICODE)
    informative_word = any(len(word) >= 3 for word in title_words)
    short_acronym = bool(re.fullmatch(r"[A-Z]{2,8}", title.strip()))
    if disposition == "INCLUDED" and not informative_word and not short_acronym:
        return None
    if disposition == "INCLUDED" and re.fullmatch(r"[\d\W_]+", title, flags=re.UNICODE):
        return None
    if disposition == "INCLUDED" and number_match and _equation_like_heading_title(title):
        return None
    bold = bool(line.font_flags & 16)
    signal = bool(number or markdown or bold or disposition != "INCLUDED")
    if not signal:
        return None
    return {
        "number": number,
        "heading": title,
        "section_disposition": disposition,
        "confidence": 0.96 if number or markdown else 0.82,
        "font_size": line.font_size,
        "bold": bold,
    }


def _detect_columns(
    lines: list[_Line],
    page_width: float,
    page_height: float,
) -> tuple[list[_Line], str, dict[str, Any]]:
    native_order = list(lines)
    diagnostics = {
        "native_order_vs_reordered_displacement": 0.0,
        "column_gutter_confidence": 0.0,
        "vertical_overlap_ratio": 0.0,
        "stable_left_block_count": 0,
        "stable_right_block_count": 0,
        "layout_classification_status": "NATIVE_ORDER_RETAINED",
    }
    if len(lines) < 12 or page_width <= 0 or page_height <= 0:
        return native_order, "single_column", diagnostics
    midpoint = page_width / 2.0
    body_lines = [
        line for line in lines
        if page_height * 0.07 <= line.bbox[1] <= page_height * 0.93
        and (line.bbox[2] - line.bbox[0]) >= page_width * 0.18
        and len(re.findall(r"\w+", line.text)) >= 4
        and not re.match(r"^(?:fig(?:ure)?|table|chart|scheme)\b", line.text, re.I)
    ]
    left = [line for line in body_lines if line.bbox[2] <= midpoint - page_width * 0.015]
    right = [line for line in body_lines if line.bbox[0] >= midpoint + page_width * 0.015]
    left_blocks = {line.block for line in left}
    right_blocks = {line.block for line in right}
    diagnostics["stable_left_block_count"] = len(left_blocks)
    diagnostics["stable_right_block_count"] = len(right_blocks)
    if len(left) < 8 or len(right) < 8 or len(left_blocks) < 2 or len(right_blocks) < 2:
        diagnostics["layout_classification_status"] = "LAYOUT_CLASSIFICATION_UNCERTAIN"
        return native_order, "single_column", diagnostics
    left_top, left_bottom = min(line.bbox[1] for line in left), max(line.bbox[3] for line in left)
    right_top, right_bottom = min(line.bbox[1] for line in right), max(line.bbox[3] for line in right)
    overlap = max(0.0, min(left_bottom, right_bottom) - max(left_top, right_top))
    union = max(left_bottom, right_bottom) - min(left_top, right_top)
    overlap_ratio = overlap / max(1.0, union)
    left_edge = max(line.bbox[2] for line in left)
    right_edge = min(line.bbox[0] for line in right)
    gutter = max(0.0, right_edge - left_edge)
    gutter_confidence = min(1.0, gutter / max(page_width * 0.06, 1.0))
    diagnostics["vertical_overlap_ratio"] = round(overlap_ratio, 4)
    diagnostics["column_gutter_confidence"] = round(gutter_confidence, 4)
    if overlap_ratio < 0.55 or gutter < max(12.0, page_width * 0.025):
        diagnostics["layout_classification_status"] = "LAYOUT_CLASSIFICATION_UNCERTAIN"
        return native_order, "single_column", diagnostics
    full_width = [line for line in lines if line not in left and line not in right]
    body_top = min(left_top, right_top)
    body_bottom = max(left_bottom, right_bottom)
    headers = [line for line in full_width if line.bbox[1] <= body_top]
    footers = [line for line in full_width if line.bbox[1] >= body_bottom]
    flow = [line for line in full_width if line not in headers and line not in footers]
    spanning_flow = [
        line for line in flow
        if (
            line.bbox[0] <= page_width * 0.22
            and line.bbox[2] >= page_width * 0.78
        )
        or line.bbox[2] - line.bbox[0] >= page_width * 0.62
        or (
            line.bbox[0] < midpoint < line.bbox[2]
            and _heading_info(line.text, line) is not None
        )
    ]
    residual_flow = [line for line in flow if line not in spanning_flow]
    left_flow = [
        line for line in residual_flow
        if (line.bbox[0] + line.bbox[2]) / 2.0 < midpoint
    ]
    right_flow = [line for line in residual_flow if line not in left_flow]
    left_column = sorted([*left, *left_flow], key=lambda line: (line.bbox[1], line.bbox[0]))
    right_column = sorted([*right, *right_flow], key=lambda line: (line.bbox[1], line.bbox[0]))
    ordered_body: list[_Line] = []
    emitted: set[tuple[int, int]] = set()
    for separator in sorted(spanning_flow, key=lambda line: (line.bbox[1], line.bbox[0])):
        separator_top = separator.bbox[1]
        for column_lines in (left_column, right_column):
            for line in column_lines:
                key = (line.block, line.line)
                if key not in emitted and line.bbox[1] < separator_top:
                    ordered_body.append(line)
                    emitted.add(key)
        ordered_body.append(separator)
    for column_lines in (left_column, right_column):
        for line in column_lines:
            key = (line.block, line.line)
            if key not in emitted:
                ordered_body.append(line)
                emitted.add(key)
    ordered = (
        sorted(headers, key=lambda line: (line.bbox[1], line.bbox[0]))
        + ordered_body
        + sorted(footers, key=lambda line: (line.bbox[1], line.bbox[0]))
    )
    native_positions = {(line.block, line.line): index for index, line in enumerate(native_order)}
    displacement = sum(
        abs(index - native_positions[(line.block, line.line)])
        for index, line in enumerate(ordered)
    ) / max(1, len(ordered) ** 2)
    diagnostics["native_order_vs_reordered_displacement"] = round(displacement, 5)
    diagnostics["layout_classification_status"] = "STRONG_TWO_COLUMN_EVIDENCE"
    return ordered, "two_column", diagnostics


def _raw_page(page: Any, page_number: int) -> tuple[dict[str, Any], list[_Line]]:
    payload = page.get_text("dict", sort=True)
    raw_blocks: list[dict[str, Any]] = []
    lines: list[_Line] = []
    for block_index, block in enumerate(payload.get("blocks") or []):
        block_type = int(block.get("type") or 0)
        block_record: dict[str, Any] = {
            "block_index": block_index,
            "block_type": block_type,
            "bbox": list(_bbox(block.get("bbox") or [])),
            "lines": [],
        }
        if block_type != 0:
            raw_blocks.append(block_record)
            continue
        for line_index, raw_line in enumerate(block.get("lines") or []):
            raw_spans: list[dict[str, Any]] = []
            text_parts: list[str] = []
            sizes: list[float] = []
            flags: list[int] = []
            fonts: list[str] = []
            for span_index, raw_span in enumerate(raw_line.get("spans") or []):
                span_text = str(raw_span.get("text") or "")
                text_parts.append(span_text)
                sizes.append(float(raw_span.get("size") or 0.0))
                flags.append(int(raw_span.get("flags") or 0))
                fonts.append(str(raw_span.get("font") or ""))
                raw_spans.append({
                    "fragment_id": (
                        f"fragment_p{page_number}_b{block_index}_l{line_index}_s{span_index}"
                    ),
                    "page_number": page_number,
                    "block_index": block_index,
                    "line_index": line_index,
                    "span_index": span_index,
                    "bbox": list(_bbox(raw_span.get("bbox") or [])),
                    "font": str(raw_span.get("font") or ""),
                    "font_size": float(raw_span.get("size") or 0.0),
                    "font_flags": int(raw_span.get("flags") or 0),
                    "original_text": span_text,
                })
            text = _clean_line_text("".join(text_parts))
            if not text:
                continue
            line_bbox = _bbox(raw_line.get("bbox") or block.get("bbox") or [])
            line = _Line(
                page=page_number,
                block=block_index,
                line=line_index,
                text=text,
                bbox=line_bbox,
                font_size=max(sizes or [0.0]),
                font_flags=max(flags or [0]),
                font=fonts[0] if fonts else "",
                column=0,
                page_height=float(page.rect.height),
                raw_spans=tuple(raw_spans),
            )
            lines.append(line)
            block_record["lines"].append({
                "line_index": line_index,
                "bbox": list(line_bbox),
                "text": text,
                "font_size": line.font_size,
                "font_flags": line.font_flags,
                "font": line.font,
                "source_fragment_ids": [
                    str(item.get("fragment_id") or "") for item in raw_spans
                    if str(item.get("fragment_id") or "")
                ],
            })
        raw_blocks.append(block_record)
    ordered, layout, order_quality = _detect_columns(
        lines,
        float(page.rect.width),
        float(page.rect.height),
    )
    for line in ordered:
        line.column = 0 if layout == "single_column" else (0 if line.bbox[0] < float(page.rect.width) / 2 else 1)
    page_text = "\n".join(line.text for line in ordered)
    figure_intrusion = sum(
        bool(re.match(r"^(?:fig(?:ure)?|table|chart|scheme)\b", line.text, re.I))
        for line in ordered
    )
    page_number_intrusion = sum(
        bool(re.fullmatch(r"\s*\d{1,4}\s*", line.text))
        and (line.bbox[1] <= float(page.rect.height) * 0.08 or line.bbox[3] >= float(page.rect.height) * 0.92)
        for line in ordered
    )
    cross_block_continuity = sum(
        previous.block != current.block
        and not re.search(r"[.!?。！？:;]$", previous.text)
        and bool(re.match(r"^[a-z]", current.text))
        for previous, current in zip(ordered, ordered[1:])
    )
    order_quality.update({
        "repeated_header_footer_intrusion": 0,
        "author_title_abstract_sequence": "PRESERVED" if page_number == 1 else "NOT_APPLICABLE",
        "cross_block_sentence_continuity": cross_block_continuity,
        "figure_label_intrusion": figure_intrusion,
        "page_number_intrusion": page_number_intrusion,
    })
    return ({
        "page_number": page_number,
        "page": page_number,
        "width": float(page.rect.width),
        "height": float(page.rect.height),
        "layout": layout,
        "layout_classification_status": order_quality["layout_classification_status"],
        "reading_order_quality": order_quality,
        "raw_blocks": raw_blocks,
        "reading_order": [
            {"block_index": line.block, "line_index": line.line} for line in ordered
        ],
        "text": page_text,
        "has_images": any(block.get("block_type") == 1 for block in raw_blocks),
    }, ordered)


def _stabilize_document_reading_order(
    page_lines: list[tuple[dict[str, Any], list[_Line]]],
) -> set[tuple[int, int, int]]:
    margin_occurrences: dict[str, list[tuple[int, int, int]]] = {}
    for page, ordered in page_lines:
        page_height = float(page.get("height") or 0.0)
        for line in ordered:
            if not page_height:
                continue
            if line.bbox[1] > page_height * 0.1 and line.bbox[3] < page_height * 0.9:
                continue
            normalized = re.sub(r"\d+", "#", line.text.casefold()).strip()
            if len(normalized) < 4:
                continue
            margin_occurrences.setdefault(normalized, []).append(
                (line.page, line.block, line.line)
            )
    repeated_margin_keys = {
        key for values in margin_occurrences.values() if len({item[0] for item in values}) >= 2
        for key in values
    }
    for page, _ in page_lines:
        quality = dict(page.get("reading_order_quality") or {})
        page_number = int(page.get("page_number") or 0)
        quality["repeated_header_footer_intrusion"] = sum(
            key[0] == page_number for key in repeated_margin_keys
        )
        page["reading_order_quality"] = quality
    return repeated_margin_keys


def _join_lines(lines: list[_Line]) -> tuple[str, list[dict[str, Any]]]:
    pieces: list[str] = []
    fragments: list[dict[str, Any]] = []
    for index, line in enumerate(lines):
        if index:
            previous = pieces[-1]
            next_text = line.text
            if previous.endswith("-") and next_text[:1].islower() and not previous.endswith("--"):
                pieces[-1] = previous[:-1]
                separator = ""
                edit = "HYPHENATED_LINE_JOIN"
            else:
                separator = " "
                edit = "LINE_BREAK_JOIN"
            pieces.append(separator)
            fragments.append({"kind": edit, "page": line.page, "block_index": line.block, "line_index": line.line})
        pieces.append(line.text)
    text = re.sub(r"\s+", " ", "".join(pieces)).strip()
    return text, fragments


def _reconstruct_paragraphs(
    page_lines: list[tuple[dict[str, Any], list[_Line]]],
    repeated_margin_keys: set[tuple[int, int, int]] | None = None,
) -> list[dict[str, Any]]:
    paragraphs: list[dict[str, Any]] = []
    counter = 0
    excluded_heading_keys = repeated_margin_keys or set()
    for page, ordered_lines in page_lines:
        groups: list[list[_Line]] = []
        current: list[_Line] = []
        previous: _Line | None = None
        for line in ordered_lines:
            if previous is None:
                current = [line]
            else:
                gap = line.bbox[1] - previous.bbox[3]
                same_region = line.column == previous.column and line.block == previous.block
                boundary = gap > max(_line_height(previous) * 1.75, 8.0) or not same_region
                if boundary:
                    if current:
                        groups.append(current)
                    current = [line]
                else:
                    current.append(line)
            previous = line
        if current:
            groups.append(current)
        body_font_sizes = sorted(line.font_size for line in ordered_lines if line.font_size > 0)
        median_font_size = (
            body_font_sizes[len(body_font_sizes) // 2] if body_font_sizes else 0.0
        )
        for group_index, group in enumerate(groups):
            text, edits = _join_lines(group)
            if not text:
                continue
            counter += 1
            first, last = group[0], group[-1]
            first_key = (group[0].page, group[0].block, group[0].line)
            heading = (
                _heading_info(text, group[0])
                if len(group) <= 3 and first_key not in excluded_heading_keys
                else None
            )
            if heading and not heading.get("number") and heading.get("section_disposition") == "INCLUDED":
                previous_group = groups[group_index - 1] if group_index > 0 else []
                next_group = groups[group_index + 1] if group_index + 1 < len(groups) else []
                whitespace_before = (
                    group[0].bbox[1] - previous_group[-1].bbox[3]
                    if previous_group else _line_height(group[0])
                )
                whitespace_after = (
                    next_group[0].bbox[1] - group[-1].bbox[3]
                    if next_group else _line_height(group[-1])
                )
                font_hierarchy = group[0].font_size >= max(
                    median_font_size * 1.08,
                    median_font_size + 0.5,
                )
                isolated = max(whitespace_before, whitespace_after) >= _line_height(group[0]) * 0.7
                if not (font_hierarchy and isolated and len(group) == 1):
                    heading = None
            paragraphs.append({
                "paragraph_id": f"p_{counter}",
                "text": text,
                "page_start": first.page,
                "page_end": last.page,
                "source_line_refs": [
                    {"page_number": item.page, "block_index": item.block, "line_index": item.line}
                    for item in group
                ],
                "source_fragment_ids": [
                    str(fragment.get("fragment_id") or "")
                    for item in group for fragment in item.raw_spans
                    if str(fragment.get("fragment_id") or "")
                ],
                "bbox": list(_bbox((
                    min(item.bbox[0] for item in group), min(item.bbox[1] for item in group),
                    max(item.bbox[2] for item in group), max(item.bbox[3] for item in group),
                ))),
                "normalization_edits": edits,
                "heading_candidate": heading,
            })
    merged: list[dict[str, Any]] = []
    for paragraph in paragraphs:
        if merged and _can_join_page_paragraphs(merged[-1], paragraph):
            previous = merged[-1]
            previous["text"] = f"{previous['text']} {paragraph['text']}".strip()
            previous["page_end"] = paragraph["page_end"]
            previous["source_line_refs"].extend(paragraph.get("source_line_refs") or [])
            previous["source_fragment_ids"].extend(
                paragraph.get("source_fragment_ids") or []
            )
            previous["normalization_edits"].append({"kind": "PAGE_BREAK_JOIN", "page": paragraph["page_start"]})
            previous["bbox"] = [
                min(previous["bbox"][0], paragraph["bbox"][0]), min(previous["bbox"][1], paragraph["bbox"][1]),
                max(previous["bbox"][2], paragraph["bbox"][2]), max(previous["bbox"][3], paragraph["bbox"][3]),
            ]
        else:
            merged.append(paragraph)
    return merged


def _can_join_page_paragraphs(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    if left.get("page_end", 0) + 1 != right.get("page_start", 0):
        return False
    if left.get("heading_candidate") or right.get("heading_candidate"):
        return False
    left_text = _text(left.get("text"))
    right_text = _text(right.get("text"))
    if not left_text or not right_text or re.search(r"[.!?。！？:;]$", left_text):
        return False
    left_bbox = left.get("bbox") or []
    right_bbox = right.get("bbox") or []
    if len(left_bbox) < 4 or len(right_bbox) < 4:
        return False
    return abs(float(left_bbox[0]) - float(right_bbox[0])) <= 18.0


def _section_tree(paragraphs: list[dict[str, Any]], canonical_parts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    paragraph_offsets: dict[str, int] = {}
    document_offset = 0
    for paragraph in paragraphs:
        paragraph_offsets[str(paragraph.get("paragraph_id") or "")] = document_offset
        document_offset += len(str(paragraph.get("text") or "")) + 2
    boundaries = [index for index, paragraph in enumerate(paragraphs) if paragraph.get("heading_candidate")]
    if boundaries and boundaries[0] > 0:
        boundaries.insert(0, -1)
    elif not boundaries:
        boundaries = [-1]
    sections: list[dict[str, Any]] = []
    stack: list[tuple[str, str]] = []
    for offset, start in enumerate(boundaries):
        end = boundaries[offset + 1] if offset + 1 < len(boundaries) else len(paragraphs)
        heading_paragraph = paragraphs[start] if start >= 0 else None
        info = heading_paragraph.get("heading_candidate") if heading_paragraph else None
        number = str((info or {}).get("number") or "")
        heading = str((info or {}).get("heading") or "Document body")
        disposition = str(
            (info or {}).get("section_disposition") or _section_disposition(heading)
        )
        body_start_index = start + 1 if heading_paragraph else 0
        body = paragraphs[body_start_index:end]
        if not body and heading_paragraph:
            continue
        if number:
            depth = number.count(".") + 1
            stack = stack[: max(0, depth - 1)]
        parent = stack[-1][0] if stack and number and number.count(".") > 0 else None
        section_id = f"section_{len(sections) + 1}"
        section = {
            "section_id": section_id,
            "number": number,
            "heading": heading,
            "section_disposition": disposition,
            "parent_section_id": parent,
            "paragraph_ids": [item["paragraph_id"] for item in body],
            "page_start": min((item["page_start"] for item in body), default=heading_paragraph["page_start"] if heading_paragraph else 1),
            "page_end": max((item["page_end"] for item in body), default=heading_paragraph["page_end"] if heading_paragraph else 1),
            "text": "\n\n".join(item["text"] for item in body).strip(),
            "char_start": min(
                (
                    paragraph_offsets.get(str(body_item.get("paragraph_id") or ""), 0)
                    for body_item in body
                ),
                default=0,
            ),
            "char_end": max(
                (
                    paragraph_offsets.get(str(body_item.get("paragraph_id") or ""), 0)
                    + len(body_item["text"])
                    for body_item in body
                ),
                default=0,
            ),
            "parser_method": "native_layout_heading_boundary",
            "parser_confidence": float((info or {}).get("confidence") or 0.55),
        }
        sections.append(section)
        if number:
            stack.append((section_id, number))
    if not sections and paragraphs:
        sections = [{
            "section_id": "section_1", "number": "", "heading": "Document body",
            "section_disposition": "INCLUDED", "parent_section_id": None,
            "paragraph_ids": [item["paragraph_id"] for item in paragraphs],
            "page_start": paragraphs[0]["page_start"], "page_end": paragraphs[-1]["page_end"],
            "text": "\n\n".join(item["text"] for item in paragraphs),
            "char_start": 0,
            "char_end": sum(len(item["text"]) + 2 for item in paragraphs) - 2,
            "parser_method": "native_layout_unclassified", "parser_confidence": 0.45,
        }]
    return sections


def _paragraph_source_ranges(text: str, max_chars: int = 4000) -> list[tuple[int, int]]:
    if not _text(text):
        return []
    ranges: list[tuple[int, int]] = []
    cursor = 0
    text_length = len(text)
    while cursor < text_length:
        remaining = text_length - cursor
        boundary = text_length
        if remaining > max_chars:
            preferred_start = cursor + max(1, int(max_chars * 0.65))
            preferred_end = cursor + max_chars
            whitespace = [
                match.start()
                for match in re.finditer(r"\s+", text[preferred_start:preferred_end])
            ]
            if whitespace:
                boundary = preferred_start + whitespace[-1]
            else:
                following = re.search(r"\s+", text[preferred_end:min(text_length, preferred_end + 500)])
                boundary = preferred_end + following.start() if following else preferred_end
        raw = text[cursor:boundary]
        left_trim = len(raw) - len(raw.lstrip())
        right_trim = len(raw.rstrip())
        start = cursor + left_trim
        end = cursor + right_trim
        if start < end:
            ranges.append((start, end))
        cursor = max(boundary, cursor + 1)
        while cursor < text_length and text[cursor].isspace():
            cursor += 1
    return ranges


def _paragraph_extraction_eligibility(
    paragraph: Mapping[str, Any],
    section_disposition: str,
) -> tuple[bool, list[str]]:
    if section_disposition != "INCLUDED":
        return False, [f"{section_disposition}_NOT_PROPOSITION_SOURCE"]
    text = _text(paragraph.get("text"))
    if not text:
        return False, ["EMPTY_SOURCE_UNIT"]
    if paragraph.get("heading_candidate"):
        return False, ["HEADING_SOURCE_CONTEXT_ONLY"]
    words = re.findall(r"[^\W\d_]+(?:[-'][^\W\d_]+)?", text, flags=re.UNICODE)
    if not words:
        return False, ["FORMULA_OR_SYMBOL_SOURCE_CONTEXT_ONLY"]
    if re.fullmatch(r"(?:https?://|www\.|doi\s*:?).+", text, flags=re.I):
        return False, ["IDENTIFIER_BANNER_NOT_PROPOSITION_SOURCE"]
    if re.match(r"^(?:©|copyright\b|all rights reserved\b|creative commons\b|this article is licensed\b)", text, flags=re.I):
        return False, ["LICENCE_TEXT_NOT_PROPOSITION_SOURCE"]
    if re.fullmatch(r"\d{1,5}", text):
        return False, ["PAGE_NUMBER_NOT_PROPOSITION_SOURCE"]
    if len(words) <= 2 and len(text) <= 40:
        return False, ["MICRO_FRAGMENT_NOT_PROPOSITION_SOURCE"]
    return True, []


def _source_spans(paragraphs: list[dict[str, Any]], sections: list[dict[str, Any]], source_url: str) -> list[dict[str, Any]]:
    paragraph_map = {item["paragraph_id"]: item for item in paragraphs}
    spans: list[dict[str, Any]] = []
    document_offset = 0
    paragraph_offsets: dict[str, int] = {}
    for paragraph in paragraphs:
        paragraph_offsets[paragraph["paragraph_id"]] = document_offset
        document_offset += len(paragraph["text"]) + 2
    for section in sections:
        for paragraph_id in section.get("paragraph_ids") or []:
            paragraph = paragraph_map.get(paragraph_id)
            if not paragraph:
                continue
            base = paragraph_offsets[paragraph_id]
            section_disposition = str(
                section.get("section_disposition") or "INCLUDED"
            )
            extraction_eligible, eligibility_reasons = _paragraph_extraction_eligibility(
                paragraph,
                section_disposition,
            )
            for index, (start, end) in enumerate(_paragraph_source_ranges(paragraph["text"]), start=1):
                quote = paragraph["text"][start:end].strip()
                if len(quote) < 2:
                    continue
                refs = paragraph.get("source_line_refs") or []
                first_ref = refs[0] if refs else {}
                last_ref = refs[-1] if refs else first_ref
                locator = (
                    f"pdf_page:{first_ref.get('page_number', paragraph['page_start'])}:"
                    f"block:{first_ref.get('block_index', 0)}:line:{first_ref.get('line_index', 0)}-"
                    f"{last_ref.get('line_index', 0)}"
                )
                fragment_ids = [
                    str(item) for item in paragraph.get("source_fragment_ids", [])
                    if str(item)
                ]
                spans.append({
                    "span_id": f"span_{len(spans) + 1}",
                    "source_span_id": f"span_{len(spans) + 1}",
                    "source_type": "fulltext",
                    "span_kind": "body_paragraph",
                    "source_url": source_url,
                    "section": section.get("heading") or "Document body",
                    "section_id": section.get("section_id"),
                    "section_heading": section.get("heading") or "Document body",
                    "section_number": section.get("number") or "",
                    "section_disposition": section_disposition,
                    "extraction_eligible": extraction_eligible,
                    "eligibility_reason_codes": list(eligibility_reasons),
                    "source_material_status": (
                        "SOURCE_BOUND_FULLTEXT"
                        if extraction_eligible else "EXCLUDED_SECTION"
                    ),
                    "binding_status": "SOURCE_UNIT_VERIFIED",
                    "text": quote,
                    "quote": quote,
                    "excerpt": quote,
                    "offset_start": base + start,
                    "offset_end": base + end,
                    "char_start": base + start,
                    "char_end": base + end,
                    "paragraph_char_start": start,
                    "paragraph_char_end": end,
                    "page": paragraph.get("page_start"),
                    "page_number": paragraph.get("page_start"),
                    "page_end": paragraph.get("page_end"),
                    "bbox": paragraph.get("bbox") or [],
                    "source_locator": locator,
                    "source_fragment_ids": fragment_ids,
                    "source_fragment_range": {
                        "first_fragment_id": fragment_ids[0] if fragment_ids else "",
                        "last_fragment_id": fragment_ids[-1] if fragment_ids else "",
                    },
                    "paragraph_id": paragraph_id,
                    "paragraph_part_index": index,
                    "parser_method": "native_layout_paragraph_source_unit",
                })
    return spans


def _chunk_plan(paragraphs: list[dict[str, Any]], sections: list[dict[str, Any]], max_chars: int = 12000) -> list[dict[str, Any]]:
    paragraph_map = {item["paragraph_id"]: item for item in paragraphs}
    chunks: list[dict[str, Any]] = []
    for section in sections:
        if section.get("section_disposition") != "INCLUDED":
            continue
        current: list[dict[str, Any]] = []
        chars = 0
        for paragraph_id in section.get("paragraph_ids") or []:
            paragraph = paragraph_map.get(paragraph_id)
            if not paragraph:
                continue
            text = paragraph["text"]
            if len(text) > max_chars:
                if current:
                    chunks.append({
                        "chunk_id": f"chunk_{len(chunks) + 1}",
                        "section_id": section["section_id"],
                        "section_heading": section.get("heading") or "",
                        "paragraph_ids": [item["paragraph_id"] for item in current],
                        "paragraph_char_ranges": [
                            {"paragraph_id": item["paragraph_id"], "char_start": 0, "char_end": len(item["text"])}
                            for item in current
                        ],
                        "text": "\n\n".join(item["text"] for item in current),
                        "source_span_ids": [],
                        "status": "READY",
                    })
                    current = []
                    chars = 0
                for start, end in _paragraph_source_ranges(text, max_chars=max_chars):
                    chunks.append({
                        "chunk_id": f"chunk_{len(chunks) + 1}",
                        "section_id": section["section_id"],
                        "section_heading": section.get("heading") or "",
                        "paragraph_ids": [paragraph_id],
                        "paragraph_char_ranges": [{
                            "paragraph_id": paragraph_id,
                            "char_start": start,
                            "char_end": end,
                        }],
                        "text": text[start:end],
                        "source_span_ids": [],
                        "status": "READY",
                    })
                continue
            if current and chars + len(text) + 2 > max_chars:
                chunks.append({
                    "chunk_id": f"chunk_{len(chunks) + 1}",
                    "section_id": section["section_id"],
                    "section_heading": section.get("heading") or "",
                    "paragraph_ids": [item["paragraph_id"] for item in current],
                    "paragraph_char_ranges": [
                        {"paragraph_id": item["paragraph_id"], "char_start": 0, "char_end": len(item["text"])}
                        for item in current
                    ],
                    "text": "\n\n".join(item["text"] for item in current),
                    "source_span_ids": [],
                    "status": "READY",
                })
                current = []
                chars = 0
            current.append(paragraph)
            chars += len(text) + 2
        if current:
            chunks.append({
                "chunk_id": f"chunk_{len(chunks) + 1}",
                "section_id": section["section_id"],
                "section_heading": section.get("heading") or "",
                "paragraph_ids": [item["paragraph_id"] for item in current],
                "paragraph_char_ranges": [
                    {"paragraph_id": item["paragraph_id"], "char_start": 0, "char_end": len(item["text"])}
                    for item in current
                ],
                "text": "\n\n".join(item["text"] for item in current),
                "source_span_ids": [],
                "status": "READY",
            })
    return chunks


def _text_quality(pages: list[dict[str, Any]], full_text: str) -> dict[str, Any]:
    alpha = len(re.findall(r"[A-Za-z]", full_text))
    whitespace = len(re.findall(r"\s", full_text))
    tokens = re.findall(r"[A-Za-z]+(?:[-'][A-Za-z]+)?|\d+", full_text)
    long_runs = re.findall(r"[A-Za-z]{32,}", full_text)
    punctuation_without_space = len(re.findall(r"[,:;.!?][A-Za-z]", full_text))
    ratio = whitespace / max(1, alpha)
    long_ratio = sum(len(item) for item in long_runs) / max(1, alpha)
    status = "PASS"
    reasons: list[str] = []
    if alpha > 200 and ratio < 0.035 and (long_runs or punctuation_without_space > max(8, alpha // 200)):
        status = "WORD_BOUNDARY_CORRUPTED"
        reasons.append("LATIN_WORD_BOUNDARY_LOSS")
    return {
        "schema_version": TEXT_QUALITY_SCHEMA_VERSION,
        "status": status,
        "whitespace_to_alpha_ratio": round(ratio, 5),
        "median_token_length": round(sorted(map(len, tokens))[len(tokens) // 2], 2) if tokens else 0,
        "p95_token_length": round(sorted(map(len, tokens))[min(len(tokens) - 1, math.floor(len(tokens) * 0.95))], 2) if tokens else 0,
        "long_alpha_run_ratio": round(long_ratio, 5),
        "punctuation_without_space_ratio": round(punctuation_without_space / max(1, alpha), 5),
        "replacement_character_ratio": round(full_text.count("\ufffd") / max(1, len(full_text)), 6),
        "reasons": reasons,
        "page_count": len(pages),
        "nonempty_page_count": sum(bool(_text(page.get("text"))) for page in pages),
    }


def _structure_quality(
    paragraphs: list[dict[str, Any]],
    sections: list[dict[str, Any]],
    pages: list[dict[str, Any]],
    source_spans: list[dict[str, Any]],
    full_text: str,
) -> dict[str, Any]:
    candidates = [item for item in paragraphs if item.get("heading_candidate")]
    numbers = [str((item.get("heading_candidate") or {}).get("number") or "") for item in candidates]
    eligible_spans = [item for item in source_spans if item.get("extraction_eligible") is True]
    span_lengths = sorted(len(str(item.get("quote") or "")) for item in eligible_spans)
    median_span_chars = span_lengths[len(span_lengths) // 2] if span_lengths else 0
    micro_span_ratio = (
        sum(length < 40 for length in span_lengths) / len(span_lengths)
        if span_lengths else 0.0
    )
    spans_per_1000_chars = len(eligible_spans) * 1000 / max(1, len(full_text))
    reference_heading_detected = any(
        (item.get("heading_candidate") or {}).get("section_disposition")
        == "EXCLUDED_REFERENCES"
        for item in paragraphs
    )
    reference_section_detected = any(
        item.get("section_disposition") == "EXCLUDED_REFERENCES"
        for item in sections
    )
    largest_section_ratio = max(
        (len(str(item.get("text") or "")) / max(1, len(full_text)) for item in sections),
        default=0.0,
    )
    status = "PASS"
    reasons: list[str] = []
    if len(candidates) >= 3 and len(sections) <= max(2, len(candidates) // 3):
        status = "SECTION_COLLAPSE_DETECTED"
        reasons.append("HEADING_BOUNDARIES_NOT_RETAINED")
    elif largest_section_ratio > 0.65 and len(candidates) >= 3:
        status = "SECTION_COLLAPSE_DETECTED"
        reasons.append("LARGEST_SECTION_DOMINATES_DOCUMENT")
    if median_span_chars < 40 and spans_per_1000_chars > 12 and micro_span_ratio > 0.35:
        status = "SPAN_STRUCTURE_REPAIR_REQUIRED"
        reasons.append("SOURCE_SPANS_EXCESSIVELY_FRAGMENTED")
    return {
        "schema_version": STRUCTURE_QUALITY_SCHEMA_VERSION,
        "status": status,
        "heading_candidate_count": len(candidates),
        "recognized_heading_count": len(candidates),
        "unnumbered_or_untyped_heading_count": sum(
            not str((item.get("heading_candidate") or {}).get("number") or "")
            for item in candidates
        ),
        "section_count": len(sections),
        "largest_section_ratio": round(largest_section_ratio, 4),
        "section_number_monotonicity": "UNKNOWN" if not numbers else "PRESENT",
        "page_locator_coverage": round(sum(bool(page.get("raw_blocks")) for page in pages) / max(1, len(pages)), 3),
        "source_span_count": len(source_spans),
        "eligible_source_span_count": len(eligible_spans),
        "median_source_span_chars": median_span_chars,
        "micro_source_span_ratio": round(micro_span_ratio, 4),
        "source_spans_per_1000_chars": round(spans_per_1000_chars, 3),
        "reference_heading_detected": reference_heading_detected,
        "reference_section_detected": reference_section_detected,
        "reasons": reasons,
    }


def ingest_pdf_document(data: bytes | bytearray, *, source_url: str = "", max_pages: int | None = None) -> dict[str, Any]:
    """Extract a PDF with native layout metadata and neutral structural views."""
    raw_data = bytes(data)
    if not raw_data.lstrip().startswith(b"%PDF-"):
        return {
            "schema_version": INGESTION_SCHEMA_VERSION,
            "status": "DOCUMENT_INGESTION_FAILED",
            "reason_codes": ["PDF_MAGIC_MISMATCH"],
            "pages": [], "fragment_registry": [], "paragraphs": [], "sections": [], "source_spans": [], "llm_chunks": [],
            "text": "", "text_quality": {"status": "FAILED"}, "structure_quality": {"status": "FAILED"},
        }
    try:
        import fitz
    except ImportError as exc:
        return {
            "schema_version": INGESTION_SCHEMA_VERSION,
            "status": "DOCUMENT_INGESTION_FAILED",
            "reason_codes": [f"PYMUPDF_UNAVAILABLE:{type(exc).__name__}"],
            "pages": [], "fragment_registry": [], "paragraphs": [], "sections": [], "source_spans": [], "llm_chunks": [],
            "text": "", "text_quality": {"status": "FAILED"}, "structure_quality": {"status": "FAILED"},
        }
    try:
        document = fitz.open(stream=raw_data, filetype="pdf")
        page_lines: list[tuple[dict[str, Any], list[_Line]]] = []
        for page_number, page in enumerate(document, start=1):
            if max_pages and page_number > int(max_pages):
                break
            page_lines.append(_raw_page(page, page_number))
        document.close()
    except Exception as exc:
        return {
            "schema_version": INGESTION_SCHEMA_VERSION,
            "status": "DOCUMENT_INGESTION_FAILED",
            "reason_codes": [f"PYMUPDF_EXTRACTION_FAILED:{type(exc).__name__}"],
            "pages": [], "fragment_registry": [], "paragraphs": [], "sections": [], "source_spans": [], "llm_chunks": [],
            "text": "", "text_quality": {"status": "FAILED"}, "structure_quality": {"status": "FAILED"},
        }
    repeated_margin_keys = _stabilize_document_reading_order(page_lines)
    pages = [item[0] for item in page_lines]
    fragment_registry = [
        dict(fragment)
        for _, ordered_lines in page_lines
        for line in ordered_lines
        for fragment in line.raw_spans
    ]
    paragraphs = _reconstruct_paragraphs(page_lines, repeated_margin_keys)
    if not paragraphs:
        has_images = any(page.get("has_images") for page in pages)
        status = "NEEDS_OCR" if has_images or pages else "DOCUMENT_INGESTION_FAILED"
        reason = "PDF_TEXT_LAYER_EMPTY" if has_images or pages else "PDF_HAS_NO_PAGES"
        return {
            "schema_version": INGESTION_SCHEMA_VERSION,
            "status": status,
            "reason_codes": [reason],
            "pages": pages, "fragment_registry": fragment_registry, "paragraphs": [], "sections": [], "source_spans": [], "llm_chunks": [],
            "text": "", "text_quality": {"status": "NEEDS_OCR" if has_images else "FAILED"},
            "structure_quality": {"status": "PENDING"},
            "source_locator_quality": {"status": "PASS" if pages else "FAILED"},
            "evidence_admission": {
                "status": status,
                "allows_direct_evidence": False,
                "candidate_only": True,
                "requires_human_review": True,
                "reason_codes": [reason],
            },
        }
    sections = _section_tree(paragraphs, pages)
    full_text = "\n\n".join(item["text"] for item in paragraphs)
    source_spans = _source_spans(paragraphs, sections, source_url)
    chunks = _chunk_plan(paragraphs, sections)
    spans_by_paragraph: dict[str, list[dict[str, Any]]] = {}
    for span in source_spans:
        spans_by_paragraph.setdefault(str(span.get("paragraph_id")), []).append(span)
    for chunk in chunks:
        chunk_span_ids: list[str] = []
        for paragraph_range in chunk.get("paragraph_char_ranges") or []:
            paragraph_id = str(paragraph_range.get("paragraph_id") or "")
            range_start = int(paragraph_range.get("char_start") or 0)
            range_end = int(paragraph_range.get("char_end") or 0)
            chunk_span_ids.extend(
                str(span.get("source_span_id"))
                for span in spans_by_paragraph.get(paragraph_id, [])
                if int(span.get("paragraph_char_start") or 0) < range_end
                and int(span.get("paragraph_char_end") or 0) > range_start
            )
        chunk["source_span_ids"] = list(dict.fromkeys(chunk_span_ids))
    text_quality = _text_quality(pages, full_text)
    structure_quality = _structure_quality(paragraphs, sections, pages, source_spans, full_text)
    locator_quality = {
        "status": "PASS" if source_spans and all(span.get("source_locator") for span in source_spans) else "INCOMPLETE",
        "span_count": len(source_spans),
        "located_span_count": sum(bool(span.get("source_locator")) for span in source_spans),
    }
    status = "TEXT_READY"
    reason_codes = list(text_quality.get("reasons") or []) + list(structure_quality.get("reasons") or [])
    uncertain_layout_pages = [
        int(page.get("page_number") or 0)
        for page in pages
        if page.get("layout_classification_status") == "LAYOUT_CLASSIFICATION_UNCERTAIN"
    ]
    if uncertain_layout_pages:
        reason_codes.append("LAYOUT_CLASSIFICATION_UNCERTAIN")
    if text_quality.get("status") != "PASS":
        status = "TEXT_INTEGRITY_FAILED"
    elif structure_quality.get("status") == "SPAN_STRUCTURE_REPAIR_REQUIRED":
        status = "SPAN_STRUCTURE_REPAIR_REQUIRED"
    elif structure_quality.get("status") != "PASS":
        status = "SECTION_STRUCTURE_PENDING"
    elif locator_quality.get("status") != "PASS":
        status = "SOURCE_LOCATORS_INCOMPLETE"
    return {
        "schema_version": INGESTION_SCHEMA_VERSION,
        "raw_schema_version": RAW_SCHEMA_VERSION,
        "status": status,
        "reason_codes": reason_codes,
        "source_url": source_url,
        "text": full_text,
        "pages": pages,
        "fragment_registry": fragment_registry,
        "paragraphs": paragraphs,
        "sections": sections,
        "source_spans": source_spans,
        "llm_chunks": chunks,
        "text_quality": text_quality,
        "structure_quality": structure_quality,
        "source_locator_quality": locator_quality,
        "reading_order_quality": {
            "status": (
                "LAYOUT_CLASSIFICATION_UNCERTAIN"
                if uncertain_layout_pages else "PASS"
            ),
            "uncertain_page_numbers": uncertain_layout_pages,
            "two_column_page_count": sum(page.get("layout") == "two_column" for page in pages),
            "native_order_page_count": sum(page.get("layout") == "single_column" for page in pages),
            "repeated_header_footer_intrusion": sum(
                int((page.get("reading_order_quality") or {}).get("repeated_header_footer_intrusion") or 0)
                for page in pages
            ),
            "figure_label_intrusion": sum(
                int((page.get("reading_order_quality") or {}).get("figure_label_intrusion") or 0)
                for page in pages
            ),
            "page_number_intrusion": sum(
                int((page.get("reading_order_quality") or {}).get("page_number_intrusion") or 0)
                for page in pages
            ),
        },
        "evidence_admission": {
            "status": "TEXT_READY" if status == "TEXT_READY" else status,
            "allows_direct_evidence": False,
            "candidate_only": status != "TEXT_READY",
            "requires_human_review": status != "TEXT_READY",
            "reason_codes": ["PROPOSITION_AND_CONTRACT_GATES_REQUIRED"],
        },
    }


__all__ = ["ingest_pdf_document", "NUMBERED_HEADING_RE", "RAW_SCHEMA_VERSION", "INGESTION_SCHEMA_VERSION"]
