"""Page/block extraction with optional MinerU reuse and safe fallbacks."""

from __future__ import annotations

import importlib.util
import importlib.metadata
import json
import re
import shutil
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class ParsedPage:
    page_number: int
    source_blocks: tuple[dict[str, object], ...]
    parser_backend: str
    parser_version: str | None
    ocr_used: bool
    figures: tuple[str, ...]
    tables: tuple[str, ...]
    equations: tuple[str, ...]
    unresolved_items: tuple[str, ...]
    parser_diagnostics: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def parse_pdf_pages(
    pdf_path: str | Path,
    *,
    work_dir: str | Path,
    max_pages: int = 300,
    prefer_mineru: bool = True,
    ocr_enabled: bool = True,
) -> list[ParsedPage]:
    path = Path(pdf_path).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError("PDF input is unavailable.")
    if path.suffix.casefold() != ".pdf":
        try:
            with path.open("rb") as handle:
                is_pdf = handle.read(5) == b"%PDF-"
        except OSError as exc:
            raise ValueError("Translation input is unavailable.") from exc
        if not is_pdf:
            raise ValueError("Translation input must be a PDF.")
    output_root = Path(work_dir).expanduser().resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    from pypdf import PdfReader

    reader = PdfReader(path)
    if reader.is_encrypted and reader.decrypt("") == 0:
        raise ValueError("Password-protected PDF input is unsupported.")
    page_count = len(reader.pages)
    if page_count < 1 or page_count > max_pages:
        raise ValueError(f"PDF must contain between 1 and {max_pages} pages.")
    diagnostics: list[str] = []
    if prefer_mineru:
        if importlib.util.find_spec("mineru") is not None:
            mineru_pages = _try_mineru(path, output_root, max_pages=page_count, ocr_enabled=ocr_enabled, diagnostics=diagnostics)
            if mineru_pages and any(page.source_blocks for page in mineru_pages):
                fallback = None
                result = []
                for page in mineru_pages:
                    if not page.source_blocks:
                        fallback = fallback or _parse_with_pypdf(path, max_pages=max_pages)
                        alternative = fallback[page.page_number - 1]
                        if alternative.source_blocks:
                            page = replace(alternative, parser_diagnostics=("mineru_empty_page_fallback",))
                    result.append(page)
                return result
        else:
            diagnostics.append("mineru_not_installed")
    return [replace(page, parser_diagnostics=tuple(diagnostics)) for page in _parse_with_pypdf(path, max_pages=max_pages)]


def _try_mineru(
    path: Path, output_root: Path, *, max_pages: int, ocr_enabled: bool = True,
    diagnostics: list[str] | None = None,
) -> list[ParsedPage]:
    """Reuse the survey MinerU wrapper without making it a hard import dependency."""

    diagnostics = diagnostics if diagnostics is not None else []
    try:
        from src.agents.survey_agent.utils.mineru_utils import parse_doc
        from filelock import FileLock

        parse_root = output_root / "mineru"
        parse_input = output_root / "source.pdf"
        if not parse_input.exists():
            shutil.copyfile(path, parse_input)
        with FileLock(str(output_root.parent.parent / ".mineru.guard"), timeout=600):
            parse_doc([parse_input], parse_root, lang="ch", backend="pipeline", method="auto" if ocr_enabled else "txt")
        content_files = sorted(parse_root.rglob("*_content_list.json"))
        middle_files = sorted(parse_root.rglob("*_middle.json"))
        mineru_version = _mineru_version()
        ocr_used = False
        if middle_files:
            middle = json.loads(middle_files[0].read_text(encoding="utf-8"))
            ocr_used = middle.get("_parse_type") == "ocr" or middle.get("_ocr_enable") is True
        if content_files:
            raw_content = json.loads(content_files[0].read_text(encoding="utf-8"))
            if isinstance(raw_content, list):
                pages = _pages_from_mineru_content(
                    raw_content,
                    max_pages=max_pages,
                    parser_version=mineru_version,
                    ocr_used=ocr_used,
                )
                if pages and any(page.source_blocks for page in pages):
                    return pages
                diagnostics.append("mineru_empty_or_invalid_content_list")
        else:
            diagnostics.append("mineru_content_list_missing")
        return []
    except Exception as exc:
        diagnostics.append(f"mineru_failed:{type(exc).__name__}")
        return []


def _pages_from_mineru_content(
    raw_content: list[object],
    *,
    max_pages: int,
    parser_version: str | None,
    ocr_used: bool,
) -> list[ParsedPage]:
    """Convert MinerU content-list records into stable one-based page blocks."""

    grouped: dict[int, list[dict[str, object]]] = {}
    page_ids = [item.get("page_id") for item in raw_content if isinstance(item, dict) and item.get("page_idx") is None]
    page_id_base = None
    if page_ids:
        try:
            page_ids = [int(value) for value in page_ids]
        except (TypeError, ValueError):
            return []
        if 0 in page_ids:
            page_id_base = 0
        elif max_pages in page_ids:
            page_id_base = 1
        else:
            return []
    for ordinal, raw_item in enumerate(raw_content, start=1):
        if not isinstance(raw_item, dict):
            continue
        raw_page = raw_item.get("page_idx")
        if raw_page is None:
            raw_page = raw_item.get("page_id")
            page_offset = 1 - page_id_base if page_id_base is not None else 0
        else:
            page_offset = 1
        try:
            page_number = int(raw_page) + page_offset
        except (TypeError, ValueError):
            return []
        if page_number < 1 or page_number > max_pages:
            return []
        block_type = str(raw_item.get("type") or "text").casefold()
        raw_text = (
            raw_item.get("text")
            or raw_item.get("content")
            or raw_item.get("latex")
            or raw_item.get("table_body")
            or ""
        )
        if isinstance(raw_text, list):
            raw_text = " ".join(str(item) for item in raw_text)
        text = str(raw_text).strip()
        caption_text = ""
        if block_type in {"image", "table"}:
            caption = raw_item.get("image_caption" if block_type == "image" else "table_caption") or []
            caption_text = " ".join(str(item) for item in caption) if isinstance(caption, list) else str(caption)
            marker = "FIGURE" if block_type == "image" else "TABLE"
            next_id = len(grouped.get(page_number, [])) + 1
            text = f"[{marker}:p{page_number}-b{next_id:03d}]\n{text}".strip()
        grouped.setdefault(page_number, []).append(
            {
                "block_id": f"p{page_number}-b{len(grouped.get(page_number, [])) + 1:03d}",
                "text": text,
                "kind": block_type,
            }
        )
        if caption_text.strip():
            grouped[page_number].append({
                "block_id": f"p{page_number}-b{len(grouped[page_number]) + 1:03d}",
                "text": caption_text.strip(), "kind": "caption",
                "parent_block_id": grouped[page_number][-1]["block_id"],
            })

    pages: list[ParsedPage] = []
    for page_number in range(1, max_pages + 1):
        blocks = [block for block in grouped.get(page_number, []) if block.get("text")]
        page_text = "\n\n".join(str(block["text"]) for block in blocks)
        pages.append(
            _page_from_text(
                page_number,
                page_text,
                "mineru",
                parser_version,
                ocr_used=ocr_used,
                explicit_blocks=blocks,
            )
        )
    return pages


def _parse_with_pypdf(path: Path, *, max_pages: int) -> list[ParsedPage]:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise RuntimeError("No PDF parser is installed. Install the pdf extra.") from exc
    reader = PdfReader(str(path))
    pages: list[ParsedPage] = []
    for page_number, page in enumerate(reader.pages[:max_pages], start=1):
        text = str(page.extract_text() or "").strip()
        pages.append(_page_from_text(page_number, text, "pypdf", importlib.metadata.version("pypdf"), ocr_used=False))
    return pages


def _page_from_text(
    page_number: int,
    text: str,
    backend: str,
    version: str | None,
    *,
    ocr_used: bool,
    explicit_blocks: list[dict[str, object]] | None = None,
) -> ParsedPage:
    blocks = tuple(explicit_blocks) if explicit_blocks is not None else tuple(
        {
            "block_id": f"p{page_number}-b{index:03d}",
            "text": block.strip(),
            "kind": "paragraph",
        }
        for index, block in enumerate(re.split(r"\n\s*\n+", text), start=1)
        if block.strip()
    )
    figures = tuple(sorted(set(re.findall(r"(?i)(?:Figure|Fig\.?)[ ._-]*([A-Za-z0-9]+)", text))))
    tables = tuple(sorted(set(re.findall(r"(?i)Table[ ._-]*([A-Za-z0-9]+)", text))))
    equations = tuple(sorted(set(re.findall(r"(?s)\$[^$]+\$|\\\([^\n]+?\\\)", text))))
    unresolved = (f"page_{page_number}_no_selectable_text",) if not text else ()
    return ParsedPage(
        page_number=page_number,
        source_blocks=blocks,
        parser_backend=backend,
        parser_version=version,
        ocr_used=ocr_used,
        figures=figures,
        tables=tables,
        equations=equations,
        unresolved_items=unresolved,
    )


def _mineru_version() -> str | None:
    try:
        return importlib.metadata.version("mineru")
    except importlib.metadata.PackageNotFoundError:
        return None
