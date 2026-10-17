"""Audit exported plot files independently of the plotting worker."""

from __future__ import annotations

from pathlib import Path

from .feature_service_base import FeatureJobError


def audit_outputs(directory: Path, formats: set[str], *, max_bytes: int) -> dict[str, object]:
    checks = {}
    for output_format in formats & {"png", "pdf", "svg"}:
        path = directory / f"figure.{output_format}"
        if not path.is_file() or not 0 < path.stat().st_size <= max_bytes:
            raise FeatureJobError("A requested figure output is missing, empty, or exceeds the configured size limit.")
        if output_format == "png":
            from PIL import Image

            with Image.open(path) as image:
                image.verify()
        elif output_format == "pdf":
            with path.open("rb") as handle:
                if handle.read(5) != b"%PDF-":
                    raise FeatureJobError("The figure PDF output is invalid.")
        else:
            import xml.etree.ElementTree as ElementTree

            if ElementTree.parse(path).getroot().tag != "{http://www.w3.org/2000/svg}svg":
                raise FeatureJobError("The figure SVG output is invalid.")
        checks[output_format] = {"status": "PASS", "size_bytes": path.stat().st_size}
    return checks


def audit_pdf(path: Path) -> dict[str, object]:
    if not path.is_file():
        return {"status": "NOT_APPLICABLE", "reason": "PDF output was not requested."}
    try:
        import fitz
    except ImportError:
        return {"status": "NOT_AUDITABLE", "reason": "PyMuPDF is unavailable."}
    with fitz.open(path) as document:
        out_of_bounds = 0
        overlaps = 0
        for page in document:
            spans = [span for block in page.get_text("dict")["blocks"] if block.get("type") == 0
                     for line in block.get("lines", []) for span in line.get("spans", []) if span.get("text", "").strip()]
            rectangles = [fitz.Rect(span["bbox"]) for span in spans]
            out_of_bounds += sum(not page.rect.contains(rectangle) for rectangle in rectangles)
            overlaps += sum(
                (rectangle & other).get_area() > 1
                for ordinal, rectangle in enumerate(rectangles) for other in rectangles[ordinal + 1:]
            )
        return {
            "status": "WARN" if overlaps or out_of_bounds else "PASS", "backend": "pymupdf",
            "page_count": len(document), "overlap_count": overlaps, "out_of_bounds": out_of_bounds,
        }
