"""Small, deterministic checks used by evidence-bounded survey editing."""

import json
import re
from difflib import SequenceMatcher
from typing import Any, Mapping, Sequence


TRACE_START = "[[SH_CLAIM_TRACE]]"
TRACE_END = "[[/SH_CLAIM_TRACE]]"


def strip_claim_trace_metadata(text: str) -> tuple[str, list[str], list[str]]:
    """Remove trace payloads even when a model omits or damages the end marker."""

    remaining = str(text or "")
    payloads: list[str] = []
    errors: list[str] = []
    while TRACE_START in remaining:
        start = remaining.index(TRACE_START)
        content_start = start + len(TRACE_START)
        end = remaining.find(TRACE_END, content_start)
        next_heading = re.search(r"(?m)^\s{0,3}#{1,6}\s+\S", remaining[content_start:])
        heading_start = content_start + next_heading.start() if next_heading else -1
        if end >= 0 and (heading_start < 0 or end < heading_start):
            payloads.append(remaining[content_start:end].strip())
            remaining = remaining[:start] + remaining[end + len(TRACE_END):]
            continue
        decoder = json.JSONDecoder()
        try:
            _, consumed = decoder.raw_decode(remaining[content_start:].lstrip())
            prefix_space = len(remaining[content_start:]) - len(remaining[content_start:].lstrip())
            payload_end = content_start + prefix_space + consumed
            payloads.append(remaining[content_start:payload_end].strip())
            remaining = remaining[:start] + remaining[payload_end:]
        except ValueError:
            errors.append("Malformed or unterminated SH_CLAIM_TRACE block was removed.")
            cutoff = heading_start if heading_start >= 0 else len(remaining)
            remaining = remaining[:start] + remaining[cutoff:]
    if TRACE_END in remaining:
        errors.append("Orphan SH_CLAIM_TRACE end marker was removed.")
        remaining = remaining.replace(TRACE_END, "")
    return remaining.strip(), payloads, errors


def cited_passages(section_text: str, limit: int = 24) -> list[str]:
    """Return bounded, citation-bearing prose for sentence-level source review."""

    passages: list[str] = []
    for paragraph in re.split(r"\n\s*\n", section_text):
        if paragraph.lstrip().startswith("#"):
            continue
        sentences = re.split(r"(?<=[.!?])\s+(?=[A-Z])", paragraph.strip())
        for sentence in sentences:
            if re.search(r"<Paper\s+ID\s*:[^>]+>|<[^<>]+>", sentence):
                passages.append(sentence.strip())
                if len(passages) >= limit:
                    return passages
    return passages


def repeated_passages(sections: Sequence[str]) -> list[dict[str, Any]]:
    """Find long repeated paragraphs or leads across distinct sections."""

    seen: list[tuple[int, str, str, set[str]]] = []
    issues: list[dict[str, Any]] = []
    for section_index, section in enumerate(sections):
        for paragraph in re.split(r"\n\s*\n", str(section or "")):
            if paragraph.lstrip().startswith("#"):
                continue
            normalized = re.sub(r"\s+", " ", paragraph).strip().casefold()
            if len(normalized) < 160:
                continue
            words = set(normalized[:1200].split())
            for first_index, first_text, first_paragraph, first_words in seen:
                common_ratio = len(words & first_words) / max(1, min(len(words), len(first_words)))
                if normalized[:120] == first_text[:120] or (
                    common_ratio >= 0.6
                    and SequenceMatcher(None, normalized[:1200], first_text[:1200]).ratio() >= 0.86
                ):
                    issues.append(
                        {
                            "kind": "cross_section_repetition",
                            "source_section": first_index + 1,
                            "target_section": section_index + 1,
                            "source_excerpt": first_paragraph[:240],
                            "target_excerpt": paragraph[:240],
                        }
                    )
                    break
            seen.append((section_index, normalized, paragraph, words))
    return issues


def paper_role(plan: Mapping[str, Any], paper_id: str) -> str:
    """Summarize the strongest permitted evidence-plan role for a paper."""

    roles: set[str] = set()
    for entry in plan.get("subhypotheses", []):
        if not isinstance(entry, Mapping):
            continue
        if paper_id in entry.get("evidence_paper_ids", []):
            roles.add("admitted evidence")
        if paper_id in entry.get("qualified_paper_ids", []):
            roles.add("qualified evidence")
        if paper_id in entry.get("context_paper_ids", []):
            roles.add("background context")
        for slot in (entry.get("slot_support") or {}).values():
            if not isinstance(slot, Mapping):
                continue
            if paper_id in slot.get("evidence_paper_ids", []):
                roles.add(str(slot.get("expected_evidence_role") or "direct evidence"))
            if paper_id in slot.get("qualified_paper_ids", []):
                roles.add("qualified evidence")
            if paper_id in slot.get("background_paper_ids", []):
                roles.add("background context")
    return ", ".join(sorted(roles)) or "role unverified"
