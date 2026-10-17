"""Stable document segments and invariant checks for academic polishing."""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from typing import Iterable


_NUMBER_PATTERN = re.compile(r"(?<![A-Za-z])[-+]?\d+(?:[.,]\d+)?(?:\s*[%‰])?(?![A-Za-z])")
_CITATION_PATTERN = re.compile(r"(?:\\cite\w*\{[^}]+\}|\[[0-9]+(?:\s*[-,;]\s*[0-9]+)*\])")
_DOI_PATTERN = re.compile(r"10\.\d{4,9}/[-._;()/:A-Z0-9]+", re.IGNORECASE)
_LATEX_MATH_PATTERN = re.compile(r"(?:\$[^$]+\$|\\\([^\n]+?\\\)|\\\[[\s\S]+?\\\])")
_VARIABLE_PATTERN = re.compile(r"\b[A-Za-z][A-Za-z0-9_]*(?:_[A-Za-z0-9]+)?\b")
_UNIT_PATTERN = re.compile(r"\d\s*((?:[munpkMGTµμ]?(?:mol|g|m|L|l|s|V|A|Hz|Pa|K|W)|mmHg|eV|°C|℃)(?:[²³]|\^?-?\d)?(?:/[A-Za-zµμ]+)?)\b")


@dataclass(frozen=True, slots=True)
class DocumentSegment:
    segment_id: str
    text: str
    kind: str
    ordinal: int
    start: int = 0
    end: int = 0


@dataclass(frozen=True, slots=True)
class InvariantSet:
    numbers: tuple[str, ...]
    citations: tuple[str, ...]
    dois: tuple[str, ...]
    equations: tuple[str, ...]
    variables: tuple[str, ...]


def segment_text(text: str) -> list[DocumentSegment]:
    """Split text deterministically while retaining paragraph order."""

    normalized = str(text or "")
    blocks = re.finditer(r"(?ms)^```[^\n]*\n.*?^```[^\n]*|^~~~[^\n]*\n.*?^~~~[^\n]*|\S.*?(?=\n\s*\n|\Z)", normalized)
    segments: list[DocumentSegment] = []
    for block in blocks:
        value = block.group().strip()
        if not value:
            continue
        ordinal = len(segments) + 1
        first_line = value.splitlines()[0].strip()
        kind = "code" if first_line.startswith(("```", "~~~")) else "heading" if first_line.startswith("#") else "table" if first_line.startswith("|") else "paragraph"
        start = block.start() + len(block.group()) - len(block.group().lstrip())
        segments.append(DocumentSegment(f"p-{ordinal:04d}", value, kind, ordinal, start, start + len(value)))
    if not segments and normalized.strip():
        segments.append(DocumentSegment("p-0001", normalized.strip(), "paragraph", 1))
    return segments


def extract_invariants(text: str) -> InvariantSet:
    numbers = tuple(_NUMBER_PATTERN.findall(text))
    citations = tuple(_CITATION_PATTERN.findall(text))
    dois = tuple(_DOI_PATTERN.findall(text))
    equations = tuple(_LATEX_MATH_PATTERN.findall(text))
    variables = tuple(
        sorted(
            {
                token
                for token in _VARIABLE_PATTERN.findall(text)
                if "_" in token or token.isupper() or any(char.isdigit() for char in token)
            }
        )
    )
    return InvariantSet(numbers, citations, dois, equations, variables)


def validate_preserved_invariants(original: str, revised: str) -> list[str]:
    """Return stable error codes when a revision changes scientific tokens."""

    before = extract_invariants(original)
    after = extract_invariants(revised)
    errors: list[str] = []
    for field_name in ("numbers", "citations", "dois", "equations", "variables"):
        expected = list(getattr(before, field_name))
        observed = list(getattr(after, field_name))
        if Counter(expected) != Counter(observed):
            errors.append(f"{field_name}_changed")
    if Counter(_UNIT_PATTERN.findall(original)) != Counter(_UNIT_PATTERN.findall(revised)):
        errors.append("units_changed")
    if Counter(re.findall(r"\\[A-Za-z]+", original)) != Counter(re.findall(r"\\[A-Za-z]+", revised)):
        errors.append("latex_commands_changed")
    before_structure = re.findall(r"(?m)^\s*(#{1,6}\s|[-*+]\s|\d+\.\s|\|)", original)
    after_structure = re.findall(r"(?m)^\s*(#{1,6}\s|[-*+]\s|\d+\.\s|\|)", revised)
    if before_structure != after_structure:
        errors.append("document_structure_changed")
    cautious = re.search(r"(?i)\b(associated|correlat\w*|may|might|suggest\w*)\b|相关|可能|提示", original)
    causal = r"(?i)\b(causes?|proves?|definitively|demonstrates? causality)\b|导致|证实|证明"
    if cautious and re.search(causal, revised) and not re.search(causal, original):
        errors.append("claim_strength_increased")
    return errors


def validate_revision_segments(
    originals: Iterable[DocumentSegment],
    revisions: Iterable[dict[str, object]],
) -> list[str]:
    original_map = {segment.segment_id: segment for segment in originals}
    errors: list[str] = []
    seen: set[str] = set()
    for raw in revisions:
        segment_id = str(raw.get("segment_id") or "")
        revised = raw.get("revised")
        if segment_id in seen:
            errors.append(f"duplicate_segment:{segment_id}")
            continue
        seen.add(segment_id)
        original = original_map.get(segment_id)
        if original is None:
            errors.append(f"unknown_segment:{segment_id}")
            continue
        if not isinstance(revised, str) or not revised.strip():
            errors.append(f"empty_revision:{segment_id}")
            continue
        if raw.get("original") != original.text:
            errors.append(f"source_text_changed:{segment_id}")
        if original.kind == "code" and revised != original.text:
            errors.append(f"code_changed:{segment_id}")
        errors.extend(f"{segment_id}:{error}" for error in validate_preserved_invariants(original.text, revised))
    missing = sorted(set(original_map) - seen)
    errors.extend(f"missing_segment:{segment_id}" for segment_id in missing)
    return errors
