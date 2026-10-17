"""Shared source maps for document segments and PDF page blocks."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Mapping, Sequence


@dataclass(frozen=True, slots=True)
class DocumentBlock:
    block_id: str
    text: str
    kind: str
    ordinal: int
    page_number: int | None = None
    start: int | None = None
    end: int | None = None
    parent_block_id: str | None = None


def document_source_map(
    blocks: Sequence[DocumentBlock], *, source_hashes: Mapping[str, str],
    parser: str, parser_version: str, limitations: Sequence[str] = (),
) -> dict[str, object]:
    identifiers = [block.block_id for block in blocks]
    if len(identifiers) != len(set(identifiers)) or any(not identifier for identifier in identifiers):
        raise ValueError("Document source blocks must have distinct nonempty IDs.")
    return {
        "schema_version": "document_source_map_v1", "source_hashes": dict(source_hashes),
        "parser": parser, "parser_version": parser_version, "limitations": list(limitations),
        "blocks": [asdict(block) for block in blocks],
    }
