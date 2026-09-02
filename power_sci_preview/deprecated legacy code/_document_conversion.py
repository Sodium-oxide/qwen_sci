"""Bounded, auditable MarkItDown conversion for literature attachments.

This module is intentionally separate from literature-provider capabilities.
Providers discover papers; this policy decides which already-authorized document
bytes may be converted, by which backend, and whether their text can be used as
automatic evidence.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
from importlib.metadata import PackageNotFoundError, version
from io import BytesIO
from pathlib import Path
from time import perf_counter
from typing import Any
import mimetypes
import re
from zipfile import BadZipFile, ZipFile

try:
    from .config import (
        SCIENCE_DOCUMENT_MAX_BYTES,
        SCIENCE_DOCUMENT_MAX_ARCHIVE_MEMBERS,
        SCIENCE_DOCUMENT_MAX_EXPANDED_BYTES,
        SCIENCE_DOCUMENT_MAX_PDF_PAGES,
        SCIENCE_DOCUMENT_OCR_API_BASE,
        SCIENCE_DOCUMENT_OCR_API_KEY,
        SCIENCE_DOCUMENT_OCR_ENABLED,
        SCIENCE_DOCUMENT_OCR_MAX_IMAGES,
        SCIENCE_DOCUMENT_OCR_MAX_PAGES,
        SCIENCE_DOCUMENT_OCR_MODEL,
        SCIENCE_DOCUMENT_SOFT_RUNTIME_SECONDS,
    )
except ImportError:
    from config import (
        SCIENCE_DOCUMENT_MAX_BYTES,
        SCIENCE_DOCUMENT_MAX_ARCHIVE_MEMBERS,
        SCIENCE_DOCUMENT_MAX_EXPANDED_BYTES,
        SCIENCE_DOCUMENT_MAX_PDF_PAGES,
        SCIENCE_DOCUMENT_OCR_API_BASE,
        SCIENCE_DOCUMENT_OCR_API_KEY,
        SCIENCE_DOCUMENT_OCR_ENABLED,
        SCIENCE_DOCUMENT_OCR_MAX_IMAGES,
        SCIENCE_DOCUMENT_OCR_MAX_PAGES,
        SCIENCE_DOCUMENT_OCR_MODEL,
        SCIENCE_DOCUMENT_SOFT_RUNTIME_SECONDS,
    )


@dataclass(frozen=True)
class DocumentConversionCapabilities:
    """Format contract used before a file reaches a converter."""

    format_id: str
    extensions: tuple[str, ...]
    mimetypes: tuple[str, ...]
    allowed_input_kinds: tuple[str, ...]
    backend_chain: tuple[str, ...]
    plugins_allowed: bool
    ocr_eligible: bool
    max_bytes: int
    max_pages: int | None
    max_archive_members: int | None
    max_expanded_bytes: int | None
    soft_runtime_seconds: int
    direct_evidence_candidate: bool
    default_source_type: str
    required_audit_fields: tuple[str, ...]


_AUDIT_FIELDS = (
    "source_identity",
    "declared_type",
    "observed_type",
    "backend",
    "backend_version",
    "configuration",
    "output",
    "quality",
    "ocr",
    "evidence_admission",
)


DOCUMENT_CONVERSION_CAPABILITIES: dict[str, DocumentConversionCapabilities] = {
    "pdf": DocumentConversionCapabilities(
        format_id="pdf",
        extensions=(".pdf",),
        mimetypes=("application/pdf", "application/x-pdf"),
        allowed_input_kinds=("local_file", "fetched_stream"),
        backend_chain=("pymupdf_native_pdf", "ocr_candidate_only"),
        plugins_allowed=False,
        ocr_eligible=True,
        max_bytes=SCIENCE_DOCUMENT_MAX_BYTES,
        max_pages=SCIENCE_DOCUMENT_MAX_PDF_PAGES,
        max_archive_members=None,
        max_expanded_bytes=None,
        soft_runtime_seconds=SCIENCE_DOCUMENT_SOFT_RUNTIME_SECONDS,
        direct_evidence_candidate=True,
        default_source_type="pdf",
        required_audit_fields=_AUDIT_FIELDS,
    ),
    "docx": DocumentConversionCapabilities(
        format_id="docx",
        extensions=(".docx",),
        mimetypes=("application/vnd.openxmlformats-officedocument.wordprocessingml.document",),
        allowed_input_kinds=("local_file",),
        backend_chain=("markitdown_core_docx",),
        plugins_allowed=False,
        ocr_eligible=False,
        max_bytes=SCIENCE_DOCUMENT_MAX_BYTES,
        max_pages=None,
        max_archive_members=SCIENCE_DOCUMENT_MAX_ARCHIVE_MEMBERS,
        max_expanded_bytes=SCIENCE_DOCUMENT_MAX_EXPANDED_BYTES,
        soft_runtime_seconds=SCIENCE_DOCUMENT_SOFT_RUNTIME_SECONDS,
        direct_evidence_candidate=False,
        default_source_type="docx_supplement",
        required_audit_fields=_AUDIT_FIELDS,
    ),
    "xlsx": DocumentConversionCapabilities(
        format_id="xlsx",
        extensions=(".xlsx",),
        mimetypes=("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",),
        allowed_input_kinds=("local_file",),
        backend_chain=("markitdown_core_xlsx",),
        plugins_allowed=False,
        ocr_eligible=False,
        max_bytes=SCIENCE_DOCUMENT_MAX_BYTES,
        max_pages=None,
        max_archive_members=SCIENCE_DOCUMENT_MAX_ARCHIVE_MEMBERS,
        max_expanded_bytes=SCIENCE_DOCUMENT_MAX_EXPANDED_BYTES,
        soft_runtime_seconds=SCIENCE_DOCUMENT_SOFT_RUNTIME_SECONDS,
        direct_evidence_candidate=False,
        default_source_type="xlsx_supplement",
        required_audit_fields=_AUDIT_FIELDS,
    ),
    "html": DocumentConversionCapabilities(
        format_id="html",
        extensions=(".html", ".htm"),
        mimetypes=("text/html", "application/xhtml+xml"),
        allowed_input_kinds=("local_file",),
        backend_chain=("markitdown_core_html",),
        plugins_allowed=False,
        ocr_eligible=False,
        max_bytes=SCIENCE_DOCUMENT_MAX_BYTES,
        max_pages=None,
        max_archive_members=None,
        max_expanded_bytes=None,
        soft_runtime_seconds=SCIENCE_DOCUMENT_SOFT_RUNTIME_SECONDS,
        direct_evidence_candidate=True,
        default_source_type="html_full_text",
        required_audit_fields=_AUDIT_FIELDS,
    ),
    "epub": DocumentConversionCapabilities(
        format_id="epub",
        extensions=(".epub",),
        mimetypes=("application/epub+zip",),
        allowed_input_kinds=("local_file",),
        backend_chain=("markitdown_core_epub",),
        plugins_allowed=False,
        ocr_eligible=False,
        max_bytes=SCIENCE_DOCUMENT_MAX_BYTES,
        max_pages=None,
        max_archive_members=SCIENCE_DOCUMENT_MAX_ARCHIVE_MEMBERS,
        max_expanded_bytes=SCIENCE_DOCUMENT_MAX_EXPANDED_BYTES,
        soft_runtime_seconds=SCIENCE_DOCUMENT_SOFT_RUNTIME_SECONDS,
        direct_evidence_candidate=False,
        default_source_type="epub_reference",
        required_audit_fields=_AUDIT_FIELDS,
    ),
}


@dataclass
class DocumentConversionResult:
    markdown: str
    report: dict[str, Any]
    capability: DocumentConversionCapabilities


class MarkdownConversion(str):
    """A string result carrying its non-content conversion audit."""

    def __new__(cls, markdown: str, report: dict[str, Any]) -> "MarkdownConversion":
        value = super().__new__(cls, markdown)
        value.conversion_report = dict(report)
        return value


def document_conversion_capability_registry() -> dict[str, dict[str, Any]]:
    """Return a serializable registry for doctor output and run provenance."""
    return {
        name: asdict(capability)
        for name, capability in DOCUMENT_CONVERSION_CAPABILITIES.items()
    }


def document_capability_for_path(path: Path | str) -> DocumentConversionCapabilities:
    suffix = Path(path).suffix.lower()
    for capability in DOCUMENT_CONVERSION_CAPABILITIES.values():
        if suffix in capability.extensions:
            return capability
    supported = ", ".join(
        extension
        for capability in DOCUMENT_CONVERSION_CAPABILITIES.values()
        for extension in capability.extensions
    )
    raise ValueError(
        f"Unsupported literature document format '{suffix or '(none)'}'. "
        f"Allowed formats: {supported}."
    )


def convert_literature_document(
    source: bytes | bytearray | Path | str,
    *,
    filename: str = "",
    source_url: str = "",
    source_kind: str = "local_file",
    expected_format: str = "",
) -> DocumentConversionResult:
    """Convert one allowlisted document without enabling third-party plugins."""
    data, source_name, local_path = _load_document_bytes(source, filename=filename)
    capability = _resolve_capability(source_name, expected_format)
    if source_kind not in capability.allowed_input_kinds:
        raise ValueError(
            f"{capability.format_id} conversion does not allow source_kind={source_kind!r}"
        )
    if len(data) > capability.max_bytes:
        raise RuntimeError(
            f"{capability.format_id.upper()} exceeds {capability.max_bytes} byte safety limit"
        )

    observed_type = _observed_document_type(data, capability)
    if not observed_type["matches_expected"]:
        raise RuntimeError(
            f"Declared {capability.format_id.upper()} does not match observed content "
            f"({observed_type['reason'] or observed_type['magic'] or 'unknown'})"
        )
    page_count = _pdf_page_count(data) if capability.format_id == "pdf" else None
    if capability.max_pages and page_count is not None and page_count > capability.max_pages:
        raise RuntimeError(
            f"PDF has {page_count} pages, exceeding the {capability.max_pages} page safety limit"
        )

    declared_mimetype = _declared_mimetype(source_name, capability)
    started = perf_counter()
    if capability.format_id == "pdf":
        try:
            from ._pdf_document_ingestion import ingest_pdf_document
        except ImportError:
            from _pdf_document_ingestion import ingest_pdf_document
        ingestion = ingest_pdf_document(data, source_url=source_url)
        text = str(ingestion.get("text") or "")
        ingestion_status = str(ingestion.get("status") or "DOCUMENT_INGESTION_FAILED")
        report = {
            "version": "document_conversion_run_v2",
            "source_identity": source_name,
            "declared_type": "pdf",
            "observed_type": observed_type,
            "backend": "pymupdf_native",
            "backend_version": "pymupdf_native_pdf_ingestion_v4",
            "configuration": {"plugins_allowed": False, "ocr_enabled": False},
            "output": {"page_count": len(ingestion.get("pages") or []), "character_count": len(text)},
            "quality": dict(ingestion.get("text_quality") or {}),
            "structure_quality": dict(ingestion.get("structure_quality") or {}),
            "source_locator_quality": dict(ingestion.get("source_locator_quality") or {}),
            "reading_order_quality": dict(ingestion.get("reading_order_quality") or {}),
            "ocr": {"status": "needs_ocr" if ingestion_status == "NEEDS_OCR" else "not_run"},
            "evidence_admission": dict(ingestion.get("evidence_admission") or {}),
            "ingestion_status": ingestion_status,
            "elapsed_ms": round((perf_counter() - started) * 1000, 2),
        }
        return DocumentConversionResult(text, report, capability)
    try:
        from markitdown import MarkItDown, StreamInfo
    except ImportError as exc:
        raise RuntimeError(
            "Document conversion requires MarkItDown. Install dependencies with: "
            "pip install -r v8/requirements.txt"
        ) from exc
    try:
        result = MarkItDown(enable_plugins=False).convert_stream(
            BytesIO(data),
            stream_info=StreamInfo(
                extension=Path(source_name).suffix.lower(),
                mimetype=declared_mimetype,
                filename=Path(source_name).name,
                local_path=local_path,
                url=source_url or None,
            ),
        )
    except Exception as exc:
        raise RuntimeError(
            f"MarkItDown {capability.format_id.upper()} conversion failed: {str(exc)[:240]}"
        ) from exc
    markdown = normalize_conversion_markdown(str(getattr(result, "markdown", result) or ""))
    elapsed_ms = round((perf_counter() - started) * 1000, 1)

    quality = assess_markdown_conversion_quality(
        markdown,
        page_count=page_count,
        document_format=capability.format_id,
    )
    ocr_result = _maybe_run_pdf_ocr(
        data,
        source_name=source_name,
        source_url=source_url,
        page_count=page_count,
        capability=capability,
        quality=quality,
    )
    if ocr_result.get("markdown"):
        markdown = normalize_conversion_markdown(str(ocr_result["markdown"]))
        quality = assess_markdown_conversion_quality(
            markdown,
            page_count=page_count,
            document_format=capability.format_id,
        )
        quality["status"] = "needs_visual_review"
        quality["reasons"] = _unique(
            list(quality.get("reasons") or []) + ["ocr_output_requires_human_review"]
        )
        quality["requires_human_review"] = True

    if not markdown and capability.format_id != "pdf":
        raise RuntimeError(
            f"MarkItDown returned no extractable Markdown for this {capability.format_id.upper()}"
        )

    evidence_admission = _evidence_admission(capability, quality, ocr_result)
    report = {
        "version": "document_conversion_run_v1",
        "source_identity": {
            "sha256": sha256(data).hexdigest(),
            "bytes": len(data),
            "source_kind": source_kind,
            "path_kind": "local_file" if local_path else "byte_stream",
            "filename": Path(source_name).name,
            "source_url": source_url,
        },
        "declared_type": {
            "format": capability.format_id,
            "extension": Path(source_name).suffix.lower(),
            "mimetype": declared_mimetype,
        },
        "observed_type": observed_type,
        "backend": "markitdown",
        "backend_version": markitdown_version(),
        "configuration": {
            "plugins_enabled": False,
            "converter_route": capability.backend_chain[0],
            "max_bytes": capability.max_bytes,
            "max_pages": capability.max_pages,
            "max_archive_members": capability.max_archive_members,
            "max_expanded_bytes": capability.max_expanded_bytes,
            "soft_runtime_seconds": capability.soft_runtime_seconds,
        },
        "output": {
            "markdown_chars": len(markdown),
            "markdown_sha256": sha256(markdown.encode("utf-8")).hexdigest(),
            "page_count": page_count,
            "conversion_elapsed_ms": elapsed_ms,
            "soft_runtime_budget_exceeded": elapsed_ms > capability.soft_runtime_seconds * 1000,
        },
        "quality": quality,
        "ocr": {key: value for key, value in ocr_result.items() if key != "markdown"},
        "evidence_admission": evidence_admission,
    }
    return DocumentConversionResult(markdown=markdown, report=report, capability=capability)


def assess_markdown_conversion_quality(
    markdown: str,
    *,
    page_count: int | None = None,
    document_format: str = "pdf",
) -> dict[str, Any]:
    """Classify extraction quality without treating a heuristic as evidence quality."""
    text = normalize_conversion_markdown(markdown)
    non_whitespace_chars = len(re.sub(r"\s+", "", text))
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    prose_lines = [
        line for line in lines
        if not line.startswith("#") and "|" not in line and not line.startswith("![")
    ]
    tokens = re.findall(r"[A-Za-z\u0370-\u03ff][A-Za-z0-9_+\-./]*|[\u4e00-\u9fff]{1,}", text)
    normal_tokens = [token for token in tokens if re.search(r"[A-Za-z\u0370-\u03ff\u4e00-\u9fff]", token)]
    sentence_candidates = re.split(r"(?<=[.!?。！？])\s+|\n+", text)
    sentences = [value.strip() for value in sentence_candidates if value.strip()]
    continuous_sentences = [
        value for value in sentences
        if 35 <= len(value) <= 900 and re.search(r"[A-Za-z\u4e00-\u9fff]", value)
    ]
    short_prose_lines = [line for line in prose_lines if len(line) < 28]
    normalized_lines = [re.sub(r"\d+", "#", line.lower()) for line in prose_lines if 4 <= len(line) <= 160]
    repeated_line_count = sum(
        count for count in _counts(normalized_lines).values() if count >= 3
    )
    table_lines = sum(1 for line in lines if "|" in line)
    image_markers = sum(1 for line in lines if line.startswith("![") or "[image ocr]" in line.lower())
    caption_lines = sum(
        1 for line in lines
        if re.match(r"(?:fig(?:ure)?|table)\s*\d+\b", line, flags=re.IGNORECASE)
    )
    garbled_characters = sum(
        1 for char in text
        if char == "\ufffd" or (ord(char) < 32 and char not in "\n\t\r")
    )
    punctuation_density = len(re.findall(r"[.!?。！？]", text)) / max(1, non_whitespace_chars)
    fragmentation_rate = len(short_prose_lines) / max(1, len(prose_lines))
    repeated_line_rate = repeated_line_count / max(1, len(prose_lines))
    signals = {
        "document_format": document_format,
        "page_count": page_count,
        "non_whitespace_chars": non_whitespace_chars,
        "token_count": len(tokens),
        "normal_token_ratio": round(len(normal_tokens) / max(1, len(tokens)), 3),
        "sentence_continuity_ratio": round(len(continuous_sentences) / max(1, len(sentences)), 3),
        "fragmentation_rate": round(fragmentation_rate, 3),
        "garbled_character_ratio": round(garbled_characters / max(1, non_whitespace_chars), 4),
        "repeated_header_footer_rate": round(repeated_line_rate, 3),
        "table_line_density": round(table_lines / max(1, len(lines)), 3),
        "image_marker_density": round(image_markers / max(1, len(lines)), 3),
        "caption_density": round(caption_lines / max(1, len(lines)), 3),
        "sentence_punctuation_density": round(punctuation_density, 4),
    }
    reasons: list[str] = []
    if document_format == "pdf" and non_whitespace_chars < 80:
        status = "needs_ocr"
        reasons.append("no_text_layer_detected")
    elif non_whitespace_chars < 80:
        status = "failed"
        reasons.append("almost_no_extractable_text")
    elif document_format == "pdf" and (
        non_whitespace_chars < 320
        or (page_count and page_count > 1 and len(normal_tokens) < 80)
    ):
        status = "needs_ocr"
        reasons.append("low_text_density_suggests_scan_or_image_only_pdf")
    elif signals["garbled_character_ratio"] > 0.015:
        status = "needs_visual_review"
        reasons.append("garbled_character_rate_exceeds_threshold")
    elif non_whitespace_chars > 2_500 and fragmentation_rate > 0.76:
        status = "needs_visual_review"
        reasons.append("high_line_fragmentation_suggests_layout_order_risk")
    elif page_count and page_count >= 4 and repeated_line_rate > 0.18:
        status = "needs_visual_review"
        reasons.append("repeated_short_lines_suggest_headers_or_footers")
    else:
        status = "ready"
    signals.update(
        {
            "status": status,
            "reasons": reasons,
            "requires_human_review": status in {"needs_ocr", "needs_visual_review", "failed"},
        }
    )
    return signals


def normalize_conversion_markdown(value: str) -> str:
    lines = [line.rstrip() for line in str(value or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    text = "\n".join(lines)
    text = re.sub(r"\n[ \t]+\n", "\n\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def markitdown_version() -> str:
    return package_version("markitdown")


def package_version(package: str) -> str:
    try:
        return version(package)
    except PackageNotFoundError:
        return "unknown"


def _resolve_capability(source_name: str, expected_format: str) -> DocumentConversionCapabilities:
    if expected_format:
        capability = DOCUMENT_CONVERSION_CAPABILITIES.get(expected_format.lower())
        if capability is None:
            raise ValueError(f"Unsupported expected document format: {expected_format}")
        return capability
    return document_capability_for_path(source_name)


def _load_document_bytes(
    source: bytes | bytearray | Path | str,
    *,
    filename: str,
) -> tuple[bytes, str, str]:
    if isinstance(source, (bytes, bytearray)):
        name = filename or "document.bin"
        return bytes(source), name, ""
    path = Path(source)
    if not path.exists() or not path.is_file():
        raise ValueError(f"Literature document not found: {path}")
    return path.read_bytes(), filename or path.name, str(path)


def _declared_mimetype(source_name: str, capability: DocumentConversionCapabilities) -> str:
    guessed, _ = mimetypes.guess_type(source_name)
    return guessed or capability.mimetypes[0]


def _observed_document_type(
    data: bytes,
    capability: DocumentConversionCapabilities,
) -> dict[str, Any]:
    expected_format = capability.format_id
    prefix = data.lstrip()[:32]
    if prefix.startswith(b"%PDF-"):
        magic = "pdf"
    elif data.startswith(b"PK\x03\x04"):
        magic = "zip_container"
    elif data.startswith(b"\xd0\xcf\x11\xe0"):
        magic = "ole_container"
    elif re.match(br"\s*<(?:!doctype\s+html|html|\?xml)", data[:512], flags=re.IGNORECASE):
        magic = "html_or_xml"
    else:
        magic = "unknown"
    allowed_magic = {
        "pdf": {"pdf"},
        "docx": {"zip_container"},
        "xlsx": {"zip_container"},
        "html": {"html_or_xml"},
        "epub": {"zip_container"},
    }.get(expected_format, set())
    result: dict[str, Any] = {
        "magic": magic,
        "matches_expected": magic in allowed_magic,
        "reason": "" if magic in allowed_magic else f"expected_{expected_format}_magic",
    }
    if magic == "zip_container" and expected_format in {"docx", "xlsx", "epub"}:
        archive = _inspect_document_archive(data, capability)
        result["archive"] = archive
        result["matches_expected"] = bool(result["matches_expected"] and archive["valid"])
        if not archive["valid"]:
            result["reason"] = str(archive["reason"] or "invalid_archive")
    return result


def _inspect_document_archive(
    data: bytes,
    capability: DocumentConversionCapabilities,
) -> dict[str, Any]:
    """Validate allowlisted structured ZIP containers without extracting them."""
    required_members = {
        "docx": {"[content_types].xml", "word/document.xml"},
        "xlsx": {"[content_types].xml", "xl/workbook.xml"},
        "epub": {"mimetype", "meta-inf/container.xml"},
    }.get(capability.format_id, set())
    try:
        with ZipFile(BytesIO(data)) as archive:
            members = archive.infolist()
            member_count = len(members)
            expanded_bytes = sum(max(0, int(member.file_size)) for member in members)
            names = {member.filename.replace("\\", "/").lower() for member in members}
            encrypted = any(member.flag_bits & 0x1 for member in members)
            missing = sorted(required_members - names)
            if member_count > int(capability.max_archive_members or 0):
                reason = "archive_member_limit_exceeded"
            elif expanded_bytes > int(capability.max_expanded_bytes or 0):
                reason = "archive_expanded_size_limit_exceeded"
            elif encrypted:
                reason = "encrypted_archive_not_allowed"
            elif missing:
                reason = f"missing_required_archive_members:{','.join(missing)}"
            elif capability.format_id == "epub" and archive.read("mimetype")[:64] != b"application/epub+zip":
                reason = "invalid_epub_mimetype"
            else:
                reason = ""
            return {
                "valid": not reason,
                "reason": reason,
                "member_count": member_count,
                "expanded_bytes": expanded_bytes,
                "required_members": sorted(required_members),
            }
    except (BadZipFile, OSError, RuntimeError) as exc:
        return {
            "valid": False,
            "reason": f"invalid_zip_container:{str(exc)[:120]}",
            "member_count": None,
            "expanded_bytes": None,
            "required_members": sorted(required_members),
        }


def _pdf_page_count(data: bytes) -> int | None:
    try:
        from pypdf import PdfReader
        return len(PdfReader(BytesIO(data), strict=False).pages)
    except Exception:
        return None


def _pdf_image_count(data: bytes, *, stop_after: int) -> int | None:
    try:
        import pdfplumber
        count = 0
        with pdfplumber.open(BytesIO(data)) as pdf:
            for page in pdf.pages:
                count += len(page.images or [])
                if count > stop_after:
                    return count
        return count
    except Exception:
        return None


def _maybe_run_pdf_ocr(
    data: bytes,
    *,
    source_name: str,
    source_url: str,
    page_count: int | None,
    capability: DocumentConversionCapabilities,
    quality: dict[str, Any],
) -> dict[str, Any]:
    if capability.format_id != "pdf" or quality.get("status") != "needs_ocr":
        return {"status": "not_needed", "attempted": False}
    if not SCIENCE_DOCUMENT_OCR_ENABLED:
        return {
            "status": "deferred_disabled",
            "attempted": False,
            "reason": "SCIENCE_DOCUMENT_OCR_ENABLED is false",
        }
    if not SCIENCE_DOCUMENT_OCR_MODEL or not SCIENCE_DOCUMENT_OCR_API_KEY:
        return {
            "status": "deferred_missing_configuration",
            "attempted": False,
            "reason": "OCR requires an explicit model and API key",
        }
    if page_count is None:
        return {
            "status": "deferred_page_count_unknown",
            "attempted": False,
            "reason": "OCR does not run when page-count cost bounds cannot be checked",
        }
    if page_count > SCIENCE_DOCUMENT_OCR_MAX_PAGES:
        return {
            "status": "deferred_page_budget_exceeded",
            "attempted": False,
            "reason": f"page_count={page_count} exceeds OCR page budget={SCIENCE_DOCUMENT_OCR_MAX_PAGES}",
        }
    image_count = _pdf_image_count(data, stop_after=SCIENCE_DOCUMENT_OCR_MAX_IMAGES)
    if image_count is None:
        return {
            "status": "deferred_image_count_unknown",
            "attempted": False,
            "reason": "OCR does not run when image-count cost bounds cannot be checked",
        }
    if image_count > SCIENCE_DOCUMENT_OCR_MAX_IMAGES:
        return {
            "status": "deferred_image_budget_exceeded",
            "attempted": False,
            "reason": f"image_count={image_count} exceeds OCR image budget={SCIENCE_DOCUMENT_OCR_MAX_IMAGES}",
        }
    try:
        from openai import OpenAI
        from markitdown import StreamInfo
        from markitdown_ocr import LLMVisionOCRService, PdfConverterWithOCR
    except ImportError as exc:
        return {
            "status": "deferred_dependency_missing",
            "attempted": False,
            "reason": f"Optional OCR dependency missing: {str(exc)[:160]}",
        }
    try:
        client_kwargs: dict[str, Any] = {"api_key": SCIENCE_DOCUMENT_OCR_API_KEY}
        if SCIENCE_DOCUMENT_OCR_API_BASE:
            client_kwargs["base_url"] = SCIENCE_DOCUMENT_OCR_API_BASE
        ocr_prompt = (
            "Transcribe visible source text exactly. Preserve paragraphs, headings, "
            "tables, symbols, and reading order. Do not infer missing content or summarize."
        )
        service = LLMVisionOCRService(
            client=OpenAI(**client_kwargs),
            model=SCIENCE_DOCUMENT_OCR_MODEL,
            default_prompt=ocr_prompt,
        )
        # Directly instantiate the known plugin converter.  We never enable
        # entry-point discovery, so an unrelated package cannot take over PDF parsing.
        result = PdfConverterWithOCR(ocr_service=service).convert(
            BytesIO(data),
            StreamInfo(
                extension=".pdf",
                mimetype="application/pdf",
                filename=Path(source_name).name,
                url=source_url or None,
            ),
        )
        markdown = normalize_conversion_markdown(str(getattr(result, "markdown", result) or ""))
        if not markdown:
            return {
                "status": "failed_no_text",
                "attempted": True,
                "page_budget": SCIENCE_DOCUMENT_OCR_MAX_PAGES,
                "image_budget": SCIENCE_DOCUMENT_OCR_MAX_IMAGES,
            }
        return {
            "status": "completed_candidate_only",
            "attempted": True,
            "backend": "markitdown_ocr",
            "backend_version": package_version("markitdown-ocr"),
            "model": SCIENCE_DOCUMENT_OCR_MODEL,
            "prompt_version": "visible_source_transcription_v1",
            "prompt": ocr_prompt,
            "configuration": {
                "plugins_enabled": False,
                "api_base_configured": bool(SCIENCE_DOCUMENT_OCR_API_BASE),
                "page_budget": SCIENCE_DOCUMENT_OCR_MAX_PAGES,
                "image_budget": SCIENCE_DOCUMENT_OCR_MAX_IMAGES,
            },
            "page_count": page_count,
            "image_count": image_count,
            "page_range": {"start": 1, "end": page_count},
            "image_range": {"start": 1, "end": image_count},
            "page_budget": SCIENCE_DOCUMENT_OCR_MAX_PAGES,
            "image_budget": SCIENCE_DOCUMENT_OCR_MAX_IMAGES,
            "source_type": "image_ocr",
            "markdown": markdown,
        }
    except Exception as exc:
        return {
            "status": "failed",
            "attempted": True,
            "reason": str(exc)[:240],
            "page_budget": SCIENCE_DOCUMENT_OCR_MAX_PAGES,
            "image_budget": SCIENCE_DOCUMENT_OCR_MAX_IMAGES,
        }


def _evidence_admission(
    capability: DocumentConversionCapabilities,
    quality: dict[str, Any],
    ocr_result: dict[str, Any],
) -> dict[str, Any]:
    ocr_candidate = ocr_result.get("status") == "completed_candidate_only"
    ready = quality.get("status") == "ready"
    allows_direct_evidence = bool(capability.direct_evidence_candidate and ready and not ocr_candidate)
    if allows_direct_evidence:
        status = "eligible_for_standard_evidence_audit"
        reason = "Conversion is ready; normal L0-L4, alignment, role, and independence gates still apply."
    elif ocr_candidate:
        status = "candidate_only"
        reason = "OCR text requires human review and cannot automatically satisfy direct-evidence gates."
    elif not capability.direct_evidence_candidate:
        status = "supplemental_only"
        reason = "This document format is supporting material, not an automatic direct-evidence source."
    else:
        status = "candidate_only"
        reason = "Conversion quality requires OCR or visual review before evidence admission."
    return {
        "status": status,
        "allows_direct_evidence": allows_direct_evidence,
        "requires_human_review": not allows_direct_evidence,
        "reason": reason,
    }


def _counts(values: list[str]) -> dict[str, int]:
    result: dict[str, int] = {}
    for value in values:
        result[value] = result.get(value, 0) + 1
    return result


def _unique(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        clean = str(value or "").strip()
        if clean and clean not in seen:
            seen.add(clean)
            result.append(clean)
    return result
