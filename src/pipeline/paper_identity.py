"""Canonical paper identifiers shared by evidence and writing stages.

OpenAlex returns the same Work as either ``W123`` or a canonical URL such as
``https://api.openalex.org/works/W123``.  Evidence ledgers use paper IDs as
keys, so comparing those transport representations verbatim can silently
exclude otherwise admitted evidence from survey writing.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any


_OPENALEX_WORK_ID_PATTERN = re.compile(
    r"(?:https?://(?:api\.)?openalex\.org/(?:works/)?)?(W\d+)$",
    flags=re.IGNORECASE,
)


def canonical_paper_id(value: Any) -> str:
    """Return the canonical ``W...`` form for an OpenAlex Work, else text.

    Non-OpenAlex identifiers are deliberately retained unchanged: the survey
    pipeline can still carry other provider IDs, and this helper must not
    invent an equivalence between them.
    """

    text = str(value or "").strip()
    if not text:
        return ""
    match = _OPENALEX_WORK_ID_PATTERN.fullmatch(text)
    return match.group(1).upper() if match else text


def canonical_paper_ids(value: Any) -> list[str]:
    """Canonicalize a scalar or ID collection and preserve first-seen order."""

    values: Iterable[Any]
    if isinstance(value, (list, tuple, set)):
        values = value
    else:
        values = [value]
    result: list[str] = []
    seen: set[str] = set()
    for raw in values:
        identifier = canonical_paper_id(raw)
        if identifier and identifier not in seen:
            seen.add(identifier)
            result.append(identifier)
    return result
