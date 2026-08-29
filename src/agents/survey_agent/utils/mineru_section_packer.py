"""Pack MinerU paper Markdown without cutting through a section.

MinerU's Markdown export usually uses one ``#`` heading for the paper title
and uses ``##`` for every body section, including logically nested headings
such as ``1.1`` and ``2.3.1``.  Numeric labels are therefore presentation
metadata, not reliable Markdown-tree boundaries.  This module treats the
original bytes from one exact ``##`` heading to the next as an atomic section.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Callable, Literal, Pattern


# Exactly level-two headings are MinerU's reliable physical body-section
# delimiter.  Do not turn ``###`` into a peer merely because its text contains
# a dotted section number.
SECTION_HEADING_RE = re.compile(r"^##(?!#)\s+(?P<title>\S.*?)(?:\s+#+)?\s*$")
TITLE_HEADING_RE = re.compile(r"^#(?!#)\s+(?P<title>\S.*?)(?:\s+#+)?\s*$")
NUMBERED_TITLE_RE = re.compile(
    r"^(?P<number>\d+(?:\.\d+)*\.?)\s*(?P<title>.*)$"
)
FENCE_RE = re.compile(r"^\s*(`{3,}|~{3,})")

DEFAULT_EXCLUDED_SECTION_PATTERNS: tuple[Pattern[str], ...] = (
    re.compile(r"^references$", re.IGNORECASE),
    re.compile(r"^acknowledg(?:e)?ments?$", re.IGNORECASE),
)

# This is a product limit, not merely a default configuration value.  A local
# override may lower it for a smaller-context provider, but cannot silently
# restore the previous 860k-scale requests.
MAX_COMPLETE_SECTION_PACKET_TOKENS = 512_000


@dataclass(frozen=True)
class MinerUSection:
    """One complete physical ``##`` section from a MinerU Markdown file."""

    index: int
    heading: str
    number: str | None
    title: str
    markdown: str
    token_count: int


@dataclass(frozen=True)
class SectionPacket:
    """An ordered group of complete sections that fits one LLM body budget."""

    index: int
    section_indices: tuple[int, ...]
    headings: tuple[str, ...]
    markdown: str
    body_token_count: int


@dataclass(frozen=True)
class PackingResult:
    """The complete, inspectable result of MinerU section packing."""

    status: Literal[
        "single_packet",
        "multi_packet",
        "no_sections",
        "unsplittable_section",
    ]
    paper_title: str
    front_matter: str
    sections: tuple[MinerUSection, ...]
    packets: tuple[SectionPacket, ...]
    excluded_headings: tuple[str, ...]
    unsplittable_section: MinerUSection | None = None


def derive_effective_body_budget(
    *,
    configured_max_body_tokens: int,
    context_window_tokens: int,
    max_output_tokens: int,
    prompt_reserve_tokens: int,
) -> int:
    """Return a safe body budget for a strict full-text LLM request.

    The configurable 512k limit governs raw paper Markdown.  A provider may
    have a smaller context window, however, so reserve capacity for the prompt
    envelope and model output before selecting whole sections.
    """

    values = (
        configured_max_body_tokens,
        context_window_tokens,
        max_output_tokens,
        prompt_reserve_tokens,
    )
    if any(int(value) <= 0 for value in values):
        raise ValueError("All token-budget values must be positive.")

    available_input = context_window_tokens - max_output_tokens - prompt_reserve_tokens
    if available_input <= 0:
        raise ValueError(
            "LLM context window leaves no room for a full-text input after "
            "reserving prompt and output tokens."
        )
    return min(
        configured_max_body_tokens,
        MAX_COMPLETE_SECTION_PACKET_TOKENS,
        available_input,
    )


def pack_mineru_markdown_by_complete_sections(
    markdown: str,
    *,
    max_body_tokens: int,
    count_tokens: Callable[[str], int],
    excluded_heading_patterns: tuple[Pattern[str], ...] = DEFAULT_EXCLUDED_SECTION_PATTERNS,
) -> PackingResult:
    """Split MinerU Markdown into token-bounded groups of whole ``##`` sections.

    The returned packets preserve source order and never use character or token
    prefix slicing.  If one atomic physical section itself exceeds the budget,
    callers receive ``unsplittable_section`` and must downgrade or fail rather
    than sending an incomplete section to an LLM.
    """

    if not isinstance(markdown, str) or not markdown.strip():
        return PackingResult(
            status="no_sections",
            paper_title="",
            front_matter=markdown or "",
            sections=(),
            packets=(),
            excluded_headings=(),
        )
    if int(max_body_tokens) <= 0:
        raise ValueError("max_body_tokens must be positive.")

    heading_records, paper_title = _scan_mineru_headings(markdown)
    if not heading_records:
        return PackingResult(
            status="no_sections",
            paper_title=paper_title,
            front_matter=markdown,
            sections=(),
            packets=(),
            excluded_headings=(),
        )

    front_matter = markdown[: heading_records[0][0]]
    all_sections: list[MinerUSection] = []
    excluded_headings: list[str] = []
    selected_sections: list[MinerUSection] = []

    for position, (start, heading) in enumerate(heading_records):
        end = (
            heading_records[position + 1][0]
            if position + 1 < len(heading_records)
            else len(markdown)
        )
        number, title = _split_numbered_heading(heading)
        section = MinerUSection(
            index=position,
            heading=heading,
            number=number,
            title=title,
            markdown=markdown[start:end],
            token_count=int(count_tokens(markdown[start:end])),
        )
        all_sections.append(section)
        if any(pattern.search(heading) for pattern in excluded_heading_patterns):
            excluded_headings.append(heading)
        else:
            selected_sections.append(section)

    if not selected_sections:
        return PackingResult(
            status="no_sections",
            paper_title=paper_title,
            front_matter=front_matter,
            sections=tuple(all_sections),
            packets=(),
            excluded_headings=tuple(excluded_headings),
        )

    front_matter_tokens = int(count_tokens(front_matter))
    if front_matter_tokens > max_body_tokens:
        # There is no physical body section to blame, but returning the first
        # selected section keeps the caller's strict downgrade path uniform.
        return PackingResult(
            status="unsplittable_section",
            paper_title=paper_title,
            front_matter=front_matter,
            sections=tuple(all_sections),
            packets=(),
            excluded_headings=tuple(excluded_headings),
            unsplittable_section=selected_sections[0],
        )

    for section in selected_sections:
        if section.token_count > max_body_tokens:
            return PackingResult(
                status="unsplittable_section",
                paper_title=paper_title,
                front_matter=front_matter,
                sections=tuple(all_sections),
                packets=(),
                excluded_headings=tuple(excluded_headings),
                unsplittable_section=section,
            )

    packets = _build_packets(
        selected_sections,
        front_matter=front_matter,
        front_matter_tokens=front_matter_tokens,
        max_body_tokens=max_body_tokens,
    )
    return PackingResult(
        status="single_packet" if len(packets) == 1 else "multi_packet",
        paper_title=paper_title,
        front_matter=front_matter,
        sections=tuple(all_sections),
        packets=tuple(packets),
        excluded_headings=tuple(excluded_headings),
    )


def render_packet_outline(result: PackingResult, packet: SectionPacket) -> tuple[str, str]:
    """Return human-readable included and omitted heading lists for a prompt."""

    included_indices = set(packet.section_indices)
    included = "\n".join(f"- {heading}" for heading in packet.headings) or "- (none)"
    omitted = "\n".join(
        f"- {section.heading}"
        for section in result.sections
        if section.index not in included_indices
        and section.heading not in result.excluded_headings
    ) or "- (none)"
    return included, omitted


def _scan_mineru_headings(markdown: str) -> tuple[list[tuple[int, str]], str]:
    records: list[tuple[int, str]] = []
    paper_title = ""
    offset = 0
    in_fence = False
    active_fence = ""

    for line in markdown.splitlines(keepends=True):
        stripped = line.rstrip("\r\n")
        fence = FENCE_RE.match(stripped)
        if fence:
            marker = fence.group(1)[0]
            if not in_fence:
                in_fence = True
                active_fence = marker
            elif marker == active_fence:
                in_fence = False
                active_fence = ""
            offset += len(line)
            continue

        if not in_fence:
            if not paper_title:
                title_match = TITLE_HEADING_RE.match(stripped)
                if title_match:
                    paper_title = _clean_heading(title_match.group("title"))
            section_match = SECTION_HEADING_RE.match(stripped)
            if section_match:
                records.append((offset, _clean_heading(section_match.group("title"))))

        offset += len(line)

    return records, paper_title


def _clean_heading(value: str) -> str:
    return value.strip().rstrip("#").rstrip()


def _split_numbered_heading(heading: str) -> tuple[str | None, str]:
    match = NUMBERED_TITLE_RE.match(heading)
    if not match:
        return None, heading
    title = match.group("title").strip() or heading
    return match.group("number"), title


def _build_packets(
    sections: list[MinerUSection],
    *,
    front_matter: str,
    front_matter_tokens: int,
    max_body_tokens: int,
) -> list[SectionPacket]:
    packets: list[SectionPacket] = []
    current: list[MinerUSection] = []
    # Front matter is useful but not a physical body chapter.  When including
    # it would push the first otherwise-complete section over the strict body
    # limit, retain it as result metadata and omit it from raw LLM body text.
    include_front_matter = bool(
        front_matter and front_matter_tokens + sections[0].token_count <= max_body_tokens
    )
    current_tokens = front_matter_tokens if include_front_matter else 0

    def flush() -> None:
        nonlocal current, current_tokens
        if not current:
            return
        prefix = front_matter if not packets and include_front_matter else ""
        markdown = prefix + "".join(section.markdown for section in current)
        packets.append(
            SectionPacket(
                index=len(packets),
                section_indices=tuple(section.index for section in current),
                headings=tuple(section.heading for section in current),
                markdown=markdown,
                body_token_count=current_tokens,
            )
        )
        current = []
        current_tokens = 0

    for section in sections:
        if current and current_tokens + section.token_count > max_body_tokens:
            flush()
        current.append(section)
        current_tokens += section.token_count

    flush()
    return packets
