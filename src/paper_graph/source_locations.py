"""Resolve retained Markdown sections and literal quotes by character position."""
from __future__ import annotations

from dataclasses import dataclass
import re


@dataclass(frozen=True)
class SourceSection:
    name: str
    start: int
    end: int


def source_sections(body: str, name: str | None = None) -> list[SourceSection]:
    headings = list(re.finditer(r"(?m)^\s{0,3}(#{1,6})\s+(.+?)\s*#*\s*$", body))
    normalized = name.strip().lstrip("#").strip() if name else None
    sections = []
    for index, heading in enumerate(headings):
        title = heading.group(2).strip()
        if normalized is not None and title != normalized:
            continue
        end = next((following.start() for following in headings[index + 1:]
                    if len(following.group(1)) <= len(heading.group(1))), len(body))
        sections.append(SourceSection(title, heading.end(), end))
    return sections


def section_at(body: str, offset: int) -> SourceSection | None:
    candidates = [section for section in source_sections(body) if section.start <= offset < section.end]
    return max(candidates, key=lambda section: section.start) if candidates else None


def section_span(body: str, name: str, *, offset: int | None = None,
                 end: int | None = None) -> tuple[int, int] | None:
    candidates = source_sections(body, name)
    if offset is not None:
        candidates = [section for section in candidates
                      if section.start <= offset < (end if end is not None else offset + 1) <= section.end]
        selected = max(candidates, key=lambda section: section.start) if candidates else None
    else:
        selected = candidates[0] if len(candidates) == 1 else None
    return (selected.start, selected.end) if selected else None


def quote_offsets(body: str, quote: str) -> list[int]:
    offsets = []
    offset = body.find(quote) if quote else -1
    while offset >= 0:
        offsets.append(offset)
        offset = body.find(quote, offset + 1)
    return offsets


def quote_location(body: str, quote: str, *, section: str = "", start: int | None = None,
                   end: int | None = None, allow_unsectioned: bool = False) -> tuple[str, int, int] | None:
    if not quote:
        return None
    if start is not None or end is not None:
        if (type(start) is not int or type(end) is not int or not 0 <= start < end <= len(body)
                or body[start:end] != quote):
            return None
        offsets = [start]
    else:
        offsets = quote_offsets(body, quote)
    matches = []
    for offset in offsets:
        quote_end = offset + len(quote)
        enclosing = section_at(body, offset)
        if section:
            if section_span(body, section, offset=offset, end=quote_end) is None:
                continue
            resolved_section = section.strip().lstrip("#").strip()
        elif enclosing and quote_end <= enclosing.end:
            resolved_section = enclosing.name
        elif allow_unsectioned:
            resolved_section = ""
        else:
            continue
        matches.append((resolved_section, offset, quote_end))
    return matches[0] if len(matches) == 1 else None


def formatted_quote_locations(body: str, quote: str, *, section: str = "", start: int | None = None,
                              end: int | None = None, allow_unsectioned: bool = False,
                              limit: int | None = 2
                              ) -> list[tuple[str, int, int]]:
    horizontal = " \t\u00a0\u202f\u2007\u2009"
    whitespace = re.compile("[" + horizontal + "\\r\\n]+")
    separator = "(?:[" + horizontal + "]+|[" + horizontal + "]*\\r?\\n[" + horizontal + "]*)"
    fragments = []
    previous = 0
    for match in whitespace.finditer(quote):
        fragments.append(re.escape(quote[previous:match.start()]))
        fragments.append(separator if match.group().count("\n") <= 1 and
                         ("\r" not in match.group() or "\r\n" in match.group()) else re.escape(match.group()))
        previous = match.end()
    fragments.append(re.escape(quote[previous:]))
    if not quote or not fragments:
        return []
    matches = []
    for match in re.finditer("(?=(" + "".join(fragments) + "))", body):
        offset, quote_end = match.span(1)
        if (start is not None and offset != start) or (end is not None and quote_end != end):
            continue
        located = quote_location(body, body[offset:quote_end], section=section, start=offset, end=quote_end,
                                 allow_unsectioned=allow_unsectioned)
        if located is not None:
            matches.append(located)
            if limit is not None and len(matches) >= limit:
                break
    return matches


def formatted_quote_location(body: str, quote: str, *, section: str = "", start: int | None = None,
                             end: int | None = None, allow_unsectioned: bool = False
                             ) -> tuple[str, int, int] | None:
    matches = formatted_quote_locations(body, quote, section=section, start=start, end=end,
                                        allow_unsectioned=allow_unsectioned)
    return matches[0] if len(matches) == 1 else None
