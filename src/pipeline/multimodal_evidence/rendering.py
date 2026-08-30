"""Build bounded, metadata-free in-memory previews for remote perception."""

from __future__ import annotations

from io import BytesIO
from typing import Any, Mapping

from .contract import ValidatedMultimodalRecord


_PREVIEWABLE_MODALITIES = frozenset({"image", "signal", "audio", "threeD", "trajectory"})


class PreviewRenderError(ValueError):
    """Raised when a selected record cannot become a bounded PNG preview."""


def supports_remote_preview(record: ValidatedMultimodalRecord) -> bool:
    return record.modality in _PREVIEWABLE_MODALITIES


def render_png_preview(
    record: ValidatedMultimodalRecord,
    native_finding: Mapping[str, Any],
    *,
    max_pixels: int,
    max_bytes: int,
) -> bytes:
    """Return a re-encoded PNG held only in memory.

    Image records retain their pixels but lose source metadata. Other allowed
    modalities become an aggregate-only card, so no source samples or table
    contents are sent to a remote model.
    """

    if max_pixels < 1 or max_bytes < 1:
        raise PreviewRenderError("Preview limits must be positive.")
    if not supports_remote_preview(record):
        raise PreviewRenderError("The selected modality has no remote preview in Batch B.")
    if record.modality == "image":
        return _render_image(record, max_pixels=max_pixels, max_bytes=max_bytes)
    return _render_aggregate_card(
        record,
        native_finding,
        max_pixels=max_pixels,
        max_bytes=max_bytes,
    )


def _render_image(
    record: ValidatedMultimodalRecord,
    *,
    max_pixels: int,
    max_bytes: int,
) -> bytes:
    try:
        from PIL import Image, ImageOps
    except ImportError as exc:
        raise PreviewRenderError("Pillow is required to prepare image previews.") from exc

    try:
        with Image.open(record.source_path) as source:
            source.load()
            transformed = ImageOps.exif_transpose(source).convert("RGB")
            clean = Image.new("RGB", transformed.size)
            clean.paste(transformed)
    except Exception as exc:
        raise PreviewRenderError("The selected image could not be rendered safely.") from exc
    return _encode_bounded_png(clean, max_pixels=max_pixels, max_bytes=max_bytes)


def _render_aggregate_card(
    record: ValidatedMultimodalRecord,
    native_finding: Mapping[str, Any],
    *,
    max_pixels: int,
    max_bytes: int,
) -> bytes:
    try:
        from PIL import Image, ImageDraw
    except ImportError as exc:
        raise PreviewRenderError("Pillow is required to prepare aggregate previews.") from exc

    metrics = native_finding.get("metrics")
    metric_count = len(metrics) if isinstance(metrics, Mapping) else 0
    image = Image.new("RGB", (960, 540), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 960, 86), fill=(20, 55, 93))
    draw.text((34, 28), "Aggregate multimodal preview", fill="white")
    draw.text((34, 130), f"Modality: {record.modality}", fill=(24, 24, 24))
    draw.text((34, 184), "This visual contains bounded local summary metadata only.", fill=(24, 24, 24))
    draw.text((34, 222), "Individual records, samples, and source paths are not included.", fill=(24, 24, 24))
    draw.text((34, 286), f"Local aggregate metric groups available: {metric_count}", fill=(24, 24, 24))
    draw.text((34, 390), "Interpret only visible aggregate structure; do not infer causality.", fill=(112, 38, 38))
    return _encode_bounded_png(image, max_pixels=max_pixels, max_bytes=max_bytes)


def _encode_bounded_png(image: Any, *, max_pixels: int, max_bytes: int) -> bytes:
    width, height = image.size
    if width < 1 or height < 1:
        raise PreviewRenderError("Preview image dimensions must be positive.")
    if width * height > max_pixels:
        scale = (max_pixels / float(width * height)) ** 0.5
        resampling = getattr(getattr(image, "Resampling", None), "LANCZOS", 1)
        image = image.resize(
            (max(1, int(width * scale)), max(1, int(height * scale))),
            resampling,
        )
    resampling = getattr(getattr(image, "Resampling", None), "LANCZOS", 1)
    for _ in range(6):
        buffer = BytesIO()
        image.save(buffer, format="PNG", optimize=True)
        payload = buffer.getvalue()
        if len(payload) <= max_bytes:
            return payload
        width, height = image.size
        if width == 1 and height == 1:
            break
        image = image.resize((max(1, int(width * 0.7)), max(1, int(height * 0.7))), resampling)
    raise PreviewRenderError("The sanitized PNG preview exceeds the configured byte limit.")
