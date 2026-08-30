"""Shared lexical guard for local observations that must remain non-causal."""

from __future__ import annotations

import re
from typing import Any


_PROHIBITED_ASSERTIONS = (
    re.compile(
        r"\b(?:proves?|proven|establishes?|confirms?|demonstrates?|"
        r"universally?|first[- ]ever)\b",
        flags=re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:causes?|causal(?:ly)?|drives?|leads?\s+to|induces?|"
        r"results?\s+in|produces?|creates?|determines?|mediates?|triggers?|"
        r"gives?\s+rise\s+to|is responsible for)\b",
        flags=re.IGNORECASE,
    ),
    re.compile(r"\b(?:shows?|indicates?|suggests?)\s+that\b", flags=re.IGNORECASE),
)


def violates_noncausal_policy(value: Any) -> bool:
    text = str(value or "")
    for pattern in _PROHIBITED_ASSERTIONS:
        for match in pattern.finditer(text):
            if _is_explicitly_tentative(text, match.start()):
                continue
            return True
    return False


def _is_explicitly_tentative(text: str, start: int) -> bool:
    prefix = text[max(0, start - 36) : start].casefold()
    return bool(
        re.search(
            r"\b(?:may|might|could|can|possibly|potentially)\s+(?:\w+\s+){0,2}$",
            prefix,
        )
    )
