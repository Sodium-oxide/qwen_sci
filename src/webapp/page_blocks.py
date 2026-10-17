"""Protect scientific anchors while translating individual source blocks."""

from __future__ import annotations

import re
from collections import Counter


_LOCKED_TEXT = re.compile(
    r"\[(?:EQUATION|FIGURE|TABLE|CITATION):[^\]]+\]"
    r"|\$\$[\s\S]*?\$\$|\$[^$\n]+\$|\\\([\s\S]*?\\\)|\\\[[\s\S]*?\\\]"
    r"|\\cite\w*\{[^}]+\}|10\.\d{4,9}/[-._;()/:A-Z0-9]+"
    r"|\[\d+(?:\s*[-,;]\s*\d+)*\]"
    r"|(?:Figure|Fig\.?|Table)\s*\d+[A-Za-z]?"
    r"|(?<!\w)[-+]?\d+(?:[.,]\d+)*(?:[eE][-+]?\d+)?(?:\s*(?:%|‰|[munpµμ]?(?:mol|g|m|L|s|Hz|Pa)|°C))?"
    r"|\b(?:[A-Z][A-Z0-9_]+|[A-Za-z]+_[A-Za-z0-9_]+)\b"
)


def protect_block(block_id: str, text: str, *, verbatim: bool = False) -> tuple[str, dict[str, str]]:
    replacements: dict[str, str] = {}

    def lock(value: str) -> str:
        marker = f"[LOCK:{block_id}:{len(replacements) + 1:04d}]"
        replacements[marker] = value
        return marker

    if verbatim:
        return lock(text), replacements
    return _LOCKED_TEXT.sub(lambda match: lock(match.group()), text), replacements


def restore_block(text: str, replacements: dict[str, str]) -> str:
    expected = Counter(replacements.keys())
    observed = Counter(re.findall(r"\[LOCK:[^\]]+\]", text))
    if observed != expected:
        raise ValueError("Translation changed locked scientific anchors.")
    if re.findall(r"\[LOCK:[^\]]+\]", text) != list(replacements):
        raise ValueError("Translation changed the order of locked scientific anchors.")
    unlocked = re.sub(r"\[LOCK:[^\]]+\]", "", text)
    if _LOCKED_TEXT.search(unlocked):
        raise ValueError("Translation introduced scientific anchors outside the locked source.")
    for marker, original in replacements.items():
        text = text.replace(marker, original)
    return text
