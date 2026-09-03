"""Candidate-only multimodal visual evidence extraction for full-text PDFs.

This module is intentionally isolated from the text excerpt pipeline.  Vision
LLM output is never appended to ``full_text_excerpt`` and never counts toward
the sub-hypothesis full-text gate in the first implementation.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from hashlib import sha256
from typing import Any, Callable, Mapping
import base64
import json
import re
import time

try:
    from .config import (
        SCIENCE_MULTIMODAL_API_BASE,
        SCIENCE_MULTIMODAL_API_KEY,
        SCIENCE_MULTIMODAL_CAPABILITY_PROBE_CACHE_SECONDS,
        SCIENCE_MULTIMODAL_COUNTS_TOWARD_GATE,
        SCIENCE_MULTIMODAL_ENABLED,
        SCIENCE_MULTIMODAL_FALLBACK_MODEL,
        SCIENCE_MULTIMODAL_MAX_ASSETS_PER_PAPER,
        SCIENCE_MULTIMODAL_MAX_PAGES,
        SCIENCE_MULTIMODAL_MAX_RENDER_DPI,
        SCIENCE_MULTIMODAL_MODEL,
        SCIENCE_MULTIMODAL_PROVIDER,
        SCIENCE_MULTIMODAL_REQUIRE_HUMAN_REVIEW,
        SCIENCE_MULTIMODAL_TIMEOUT_SECONDS,
    )
    from .log import log_event
    from ._utils import normalize_space
except ImportError:  # pragma: no cover - script-mode compatibility
    from config import (
        SCIENCE_MULTIMODAL_API_BASE,
        SCIENCE_MULTIMODAL_API_KEY,
        SCIENCE_MULTIMODAL_CAPABILITY_PROBE_CACHE_SECONDS,
        SCIENCE_MULTIMODAL_COUNTS_TOWARD_GATE,
        SCIENCE_MULTIMODAL_ENABLED,
        SCIENCE_MULTIMODAL_FALLBACK_MODEL,
        SCIENCE_MULTIMODAL_MAX_ASSETS_PER_PAPER,
        SCIENCE_MULTIMODAL_MAX_PAGES,
        SCIENCE_MULTIMODAL_MAX_RENDER_DPI,
        SCIENCE_MULTIMODAL_MODEL,
        SCIENCE_MULTIMODAL_PROVIDER,
        SCIENCE_MULTIMODAL_REQUIRE_HUMAN_REVIEW,
        SCIENCE_MULTIMODAL_TIMEOUT_SECONDS,
    )
    from log import log_event
    from _utils import normalize_space


VISUAL_EVIDENCE_RUN_SCHEMA_VERSION = "multimodal_visual_evidence_run_v1"
VISUAL_EVIDENCE_UNIT_SCHEMA_VERSION = "visual_evidence_unit_v1"
VISUAL_EVIDENCE_PROMPT_VERSION = "visual_evidence_extraction_v1"

ALLOWED_VISUAL_TYPES = {
    "line_chart",
    "bar_chart",
    "scatter_plot",
    "heatmap",
    "table",
    "schematic",
    "microscopy",
    "map",
    "spectrum",
    "gel",
    "flow_diagram",
    "unknown",
}
RESULT_VISUAL_TYPES = {"line_chart", "bar_chart", "scatter_plot", "heatmap", "table"}
SCHEMATIC_VISUAL_TYPES = {"schematic", "flow_diagram"}
ALLOWED_VISUAL_EVIDENCE_ROLES = {
    "visual_project_background",
    "visual_project_background_only",
    "visual_sh_local_auxiliary",
    "visual_component_bridge_candidate",
    "visual_core_candidate_pending_review",
}
ALLOWED_VISUAL_ADMISSION_SCOPES = {
    "visual_project_background_only",
    "visual_sh_local_auxiliary",
    "visual_component_bridge_candidate",
    "visual_core_candidate_pending_review",
}
EFFECT_DIRECTIONS = {"positive", "negative", "null", "mixed", "unclear"}
CAPTION_RE = re.compile(
    r"^(?:fig(?:ure)?|table)\s*[\w.-]+[.:)\s-]+.+",
    re.IGNORECASE,
)
LABEL_RE = re.compile(r"\b(?:fig(?:ure)?|table)\s*[\w.-]+\b", re.IGNORECASE)
NEGATIVE_MARKERS = {
    "negative",
    "decrease",
    "decreased",
    "decreases",
    "reduced",
    "reduction",
    "lower",
    "decline",
    "declined",
    "inhibit",
    "inhibited",
    "suppressed",
}
POSITIVE_MARKERS = {
    "positive",
    "increase",
    "increased",
    "increases",
    "higher",
    "enhance",
    "enhanced",
    "promote",
    "promoted",
    "improved",
}
_TINY_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="
)
_PROBE_CACHE: dict[str, dict[str, Any]] = {}


@dataclass
class VisualAsset:
    asset_id: str
    asset_type: str
    page: int
    source_locator: str
    caption: str
    nearby_text: str
    referenced_by: list[str]
    image_sha256: str
    width: int
    height: int
    render_dpi: int
    png_bytes: bytes = field(repr=False, default=b"")
    selection_score: int = 0
    object_hits: list[str] = field(default_factory=list)
    declared_input_hits: list[str] = field(default_factory=list)
    mechanism_hits: list[str] = field(default_factory=list)
    outcome_hits: list[str] = field(default_factory=list)
    comparison_hits: list[str] = field(default_factory=list)


def _safe_log(category: str, event: str, **payload: Any) -> None:
    try:
        log_event(category, event, **payload)
    except Exception:
        return


def _clamp_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def _clamp_float(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = default
    return max(0.0, min(1.0, parsed))


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, (tuple, set)):
        return list(value)
    return [value]


def _add_terms(target: list[str], *values: Any) -> None:
    for value in values:
        if isinstance(value, Mapping):
            for nested in value.values():
                _add_terms(target, nested)
            continue
        for item in _as_list(value):
            if isinstance(item, Mapping):
                _add_terms(target, item)
                continue
            text = normalize_space(str(item or ""))
            if not text:
                continue
            if len(text) <= 1:
                continue
            lowered = text.lower()
            if lowered not in {existing.lower() for existing in target}:
                target.append(text)


def _contract_policy(contract: Mapping[str, Any]) -> Mapping[str, Any]:
    policy = contract.get("core_axis_policy")
    return policy if isinstance(policy, Mapping) else {}


def alignment_contract_terms(alignment_contract: Mapping[str, Any] | None) -> dict[str, list[str]]:
    """Extract generic SH-local term groups from an alignment contract."""

    contract = alignment_contract if isinstance(alignment_contract, Mapping) else {}
    policy = _contract_policy(contract)
    anchor_policy = (
        contract.get("scientific_object_anchor_policy")
        if isinstance(contract.get("scientific_object_anchor_policy"), Mapping)
        else {}
    )
    object_terms: list[str] = []
    declared_input_terms: list[str] = []
    mechanism_terms: list[str] = []
    outcome_terms: list[str] = []
    comparison_terms: list[str] = []
    project_terms: list[str] = []

    _add_terms(
        object_terms,
        contract.get("scientific_object"),
        contract.get("scientific_object_terms"),
        contract.get("scientific_object_aliases"),
        contract.get("scientific_object_phrases"),
        contract.get("object_anchors"),
        contract.get("required_object_anchors"),
        anchor_policy.get("object_anchors"),
        anchor_policy.get("required_object_anchors"),
        policy.get("object_terms"),
        policy.get("scientific_object_terms"),
        policy.get("object_anchors"),
    )
    _add_terms(
        declared_input_terms,
        contract.get("declared_input_terms"),
        contract.get("input_terms"),
        contract.get("independent_variable_terms"),
        contract.get("exposure_terms"),
        contract.get("intervention_terms"),
        policy.get("declared_input_terms"),
        policy.get("input_terms"),
        policy.get("independent_variable_terms"),
        policy.get("exposure_terms"),
        policy.get("intervention_terms"),
    )
    _add_terms(
        mechanism_terms,
        contract.get("mechanism_terms"),
        contract.get("mediator_terms"),
        contract.get("mechanism_anchors"),
        contract.get("method_or_platform_anchors"),
        policy.get("mechanism_terms"),
        policy.get("mediator_terms"),
        policy.get("mechanism_anchors"),
        policy.get("method_or_platform_anchors"),
    )
    _add_terms(
        outcome_terms,
        contract.get("outcome_terms"),
        contract.get("dependent_variable_terms"),
        contract.get("readout_terms"),
        contract.get("readout_anchors"),
        contract.get("endpoint_terms"),
        policy.get("outcome_terms"),
        policy.get("dependent_variable_terms"),
        policy.get("readout_terms"),
        policy.get("readout_anchors"),
        policy.get("endpoint_terms"),
    )
    _add_terms(
        comparison_terms,
        contract.get("comparison_terms"),
        contract.get("comparator_terms"),
        contract.get("baseline_terms"),
        policy.get("comparison_terms"),
        policy.get("comparator_terms"),
        policy.get("baseline_terms"),
    )
    for level in contract.get("comparison_levels") or policy.get("comparison_levels") or []:
        if isinstance(level, Mapping):
            _add_terms(comparison_terms, level.get("label"), level.get("terms"))
            _add_terms(declared_input_terms, level.get("terms"))
        else:
            _add_terms(comparison_terms, level)
    _add_terms(
        comparison_terms,
        contract.get("comparison_markers"),
        policy.get("comparison_markers"),
    )
    _add_terms(
        project_terms,
        contract.get("project_context_anchor_terms"),
        contract.get("project_identity_essential_terms"),
        policy.get("project_context_anchor_terms"),
        policy.get("project_identity_essential_terms"),
    )
    return {
        "object_terms": object_terms[:64],
        "declared_input_terms": declared_input_terms[:64],
        "mechanism_terms": mechanism_terms[:64],
        "outcome_terms": outcome_terms[:64],
        "comparison_terms": comparison_terms[:64],
        "project_terms": project_terms[:64],
    }


def contract_requires_declared_input(alignment_contract: Mapping[str, Any] | None) -> bool:
    terms = alignment_contract_terms(alignment_contract)
    return bool(terms["declared_input_terms"])


def _term_hit(term: str, text: str) -> bool:
    clean = normalize_space(term).lower()
    haystack = text.lower()
    if not clean or len(clean) <= 1:
        return False
    if " " in clean or "-" in clean or "/" in clean:
        return clean in haystack
    return bool(re.search(rf"(?<![A-Za-z0-9]){re.escape(clean)}(?![A-Za-z0-9])", haystack))


def term_hits(text: str, terms: list[str], *, limit: int = 16) -> list[str]:
    hits: list[str] = []
    haystack = normalize_space(text)
    for term in terms:
        if _term_hit(term, haystack):
            hits.append(term)
        if len(hits) >= limit:
            break
    return list(dict.fromkeys(hits))


def render_pdf_pages(
    pdf_bytes: bytes,
    *,
    max_pages: int,
    dpi: int,
) -> list[dict[str, Any]]:
    """Render bounded PDF pages to PNG bytes using PyMuPDF when available."""

    try:
        import fitz  # type: ignore
    except ImportError as exc:
        raise RuntimeError("pymupdf_not_installed") from exc
    doc = fitz.open(stream=bytes(pdf_bytes), filetype="pdf")
    zoom = float(dpi) / 72.0
    matrix = fitz.Matrix(zoom, zoom)
    pages: list[dict[str, Any]] = []
    try:
        for index in range(min(len(doc), max_pages)):
            page = doc[index]
            pix = page.get_pixmap(matrix=matrix, alpha=False)
            png_bytes = pix.tobytes("png")
            pages.append(
                {
                    "page": index + 1,
                    "png_bytes": png_bytes,
                    "sha256": sha256(png_bytes).hexdigest(),
                    "width": int(pix.width),
                    "height": int(pix.height),
                    "dpi": int(dpi),
                }
            )
    finally:
        doc.close()
    return pages


def extract_visual_caption_candidates(
    *,
    converted_markdown: str = "",
    full_text_report: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Extract figure/table caption candidates from PDF extraction reports or Markdown."""

    report = full_text_report if isinstance(full_text_report, dict) else {}
    non_text = report.get("non_text") if isinstance(report.get("non_text"), dict) else {}
    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, item in enumerate(non_text.get("caption_evidence") or [], start=1):
        if not isinstance(item, Mapping):
            continue
        text = normalize_space(str(item.get("text") or ""))
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        label_match = LABEL_RE.search(text)
        candidates.append(
            {
                "caption_id": f"caption_{len(candidates) + 1}",
                "kind": "table" if text.lower().startswith("table") else "figure",
                "label": normalize_space(label_match.group(0)) if label_match else "",
                "page": int(item.get("page") or 0),
                "text": text,
                "source_locator": str(item.get("source_locator") or "report_caption"),
            }
        )
    if candidates:
        return candidates[:100]

    for raw_line in str(converted_markdown or "").splitlines():
        clean = re.sub(r"^\s*(?:[#>*-]+\s*)+", "", raw_line).strip()
        if not CAPTION_RE.match(clean):
            continue
        text = normalize_space(clean)
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        label_match = LABEL_RE.search(text)
        candidates.append(
            {
                "caption_id": f"caption_{len(candidates) + 1}",
                "kind": "table" if text.lower().startswith("table") else "figure",
                "label": normalize_space(label_match.group(0)) if label_match else "",
                "page": 0,
                "text": text,
                "source_locator": "markdown_caption",
            }
        )
        if len(candidates) >= 100:
            break
    return candidates


def _nearby_text_for_caption(caption: dict[str, Any], markdown: str) -> str:
    caption_text = str(caption.get("text") or "")
    if not markdown or not caption_text:
        return ""
    normalized_caption = normalize_space(caption_text)
    lines = str(markdown).splitlines()
    for index, line in enumerate(lines):
        if normalize_space(line) == normalized_caption or normalized_caption[:80] in normalize_space(line):
            start = max(0, index - 3)
            end = min(len(lines), index + 4)
            return normalize_space(" ".join(lines[start:end]))[:1600]
    label = str(caption.get("label") or "")
    if label:
        pattern = re.compile(re.escape(label), flags=re.IGNORECASE)
        for index, line in enumerate(lines):
            if pattern.search(line):
                start = max(0, index - 2)
                end = min(len(lines), index + 3)
                return normalize_space(" ".join(lines[start:end]))[:1600]
    return ""


def _rendered_page_for_caption(
    rendered_pages: list[dict[str, Any]],
    caption: dict[str, Any],
) -> dict[str, Any] | None:
    if not rendered_pages:
        return None
    page_number = int(caption.get("page") or 0)
    if page_number > 0:
        for page in rendered_pages:
            if int(page.get("page") or 0) == page_number:
                return page
    return rendered_pages[0]


def select_visual_assets_for_sh(
    rendered_pages: list[dict[str, Any]],
    captions: list[dict[str, Any]],
    *,
    alignment_contract: dict[str, Any] | None,
    max_assets: int,
    converted_markdown: str = "",
    paper_metadata: dict[str, Any] | None = None,
) -> list[VisualAsset]:
    terms = alignment_contract_terms(alignment_contract)
    has_contract = bool(alignment_contract)
    if not has_contract:
        return []
    selected: list[VisualAsset] = []
    for caption in captions:
        page = _rendered_page_for_caption(rendered_pages, caption)
        if not page:
            continue
        nearby_text = _nearby_text_for_caption(caption, converted_markdown)
        # Keep SH-local visual selection bound to the figure/table unit itself.
        # Whole-paper title/excerpt context can make an unrelated image look
        # relevant, so the first-version selector only uses caption + nearby
        # text to satisfy declared input/mechanism/outcome anchors.
        score_text = " ".join(
            [
                str(caption.get("text") or ""),
                nearby_text,
            ]
        )
        object_hits = term_hits(score_text, terms["object_terms"])
        declared_input_hits = term_hits(score_text, terms["declared_input_terms"])
        mechanism_hits = term_hits(score_text, terms["mechanism_terms"])
        outcome_hits = term_hits(score_text, terms["outcome_terms"])
        comparison_hits = term_hits(score_text, terms["comparison_terms"])
        score = 0
        if object_hits:
            score += 5
        if declared_input_hits:
            score += 6
        if mechanism_hits:
            score += 4
        if outcome_hits:
            score += 4
        if comparison_hits:
            score += 3
        if str(caption.get("label") or "") and _term_hit(str(caption.get("label")), nearby_text):
            score += 3
        if terms["project_terms"] and term_hits(score_text, terms["project_terms"]) and not (
            object_hits or declared_input_hits or mechanism_hits or outcome_hits
        ):
            score -= 4
        requires_declared_input = contract_requires_declared_input(alignment_contract)
        if requires_declared_input and not declared_input_hits:
            continue
        eligible = bool(
            object_hits
            and (declared_input_hits or mechanism_hits or outcome_hits or comparison_hits)
        )
        if not eligible:
            continue
        if score <= 0:
            continue
        page_number = int(page.get("page") or 0)
        asset_kind = str(caption.get("kind") or "figure")
        asset = VisualAsset(
            asset_id=f"{asset_kind}_{len(selected) + 1}_page_{page_number or 'unknown'}",
            asset_type="table_image" if asset_kind == "table" else "figure",
            page=page_number,
            source_locator=(
                f"pdf_page:{page_number}:caption:{caption.get('label') or caption.get('caption_id')}"
                if int(caption.get("page") or 0) > 0
                else f"pdf_page:{page_number}:caption_without_page:{caption.get('label') or caption.get('caption_id')}"
            ),
            caption=str(caption.get("text") or ""),
            nearby_text=nearby_text,
            referenced_by=[str(caption.get("label") or "")] if caption.get("label") else [],
            image_sha256=str(page.get("sha256") or ""),
            width=int(page.get("width") or 0),
            height=int(page.get("height") or 0),
            render_dpi=int(page.get("dpi") or 0),
            png_bytes=bytes(page.get("png_bytes") or b""),
            selection_score=score,
            object_hits=object_hits,
            declared_input_hits=declared_input_hits,
            mechanism_hits=mechanism_hits,
            outcome_hits=outcome_hits,
            comparison_hits=comparison_hits,
        )
        selected.append(asset)
    selected.sort(key=lambda item: (-item.selection_score, item.page, item.asset_id))
    return selected[: max(0, int(max_assets))]


def qwen_multimodal_client():
    from openai import OpenAI

    kwargs: dict[str, Any] = {"api_key": SCIENCE_MULTIMODAL_API_KEY}
    if SCIENCE_MULTIMODAL_API_BASE:
        kwargs["base_url"] = SCIENCE_MULTIMODAL_API_BASE
    kwargs["timeout"] = SCIENCE_MULTIMODAL_TIMEOUT_SECONDS
    return OpenAI(**kwargs)


def probe_visual_model_capability(
    model: str,
    *,
    client_factory: Callable[[], Any] | None = None,
) -> dict[str, Any]:
    clean_model = str(model or "").strip()
    if not clean_model:
        return {
            "model": clean_model,
            "vision_input_supported": False,
            "status": "failed",
            "error": "empty_model",
        }
    now = time.time()
    cached = _PROBE_CACHE.get(clean_model)
    if (
        cached
        and SCIENCE_MULTIMODAL_CAPABILITY_PROBE_CACHE_SECONDS > 0
        and now - float(cached.get("checked_at") or 0) <= SCIENCE_MULTIMODAL_CAPABILITY_PROBE_CACHE_SECONDS
    ):
        return {**cached, "cache_hit": True}
    if not SCIENCE_MULTIMODAL_API_KEY:
        result = {
            "model": clean_model,
            "vision_input_supported": False,
            "status": "failed",
            "error": "SCIENCE_MULTIMODAL_API_KEY is missing",
            "checked_at": now,
        }
        _PROBE_CACHE[clean_model] = result
        return result
    try:
        client = client_factory() if client_factory else qwen_multimodal_client()
        client.chat.completions.create(
            model=clean_model,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": 'Return JSON only: {"ok": true} if you can receive this image.',
                        },
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{_TINY_PNG_B64}"},
                        },
                    ],
                }
            ],
            temperature=0,
            max_tokens=64,
        )
        result = {
            "model": clean_model,
            "vision_input_supported": True,
            "status": "ok",
            "checked_at": now,
        }
    except Exception as exc:
        result = {
            "model": clean_model,
            "vision_input_supported": False,
            "status": "failed",
            "error": str(exc)[:240],
            "checked_at": now,
        }
    _PROBE_CACHE[clean_model] = result
    return result


def choose_visual_model(*, client_factory: Callable[[], Any] | None = None) -> dict[str, Any]:
    primary = SCIENCE_MULTIMODAL_MODEL or "qwen3.8-max"
    fallback = SCIENCE_MULTIMODAL_FALLBACK_MODEL or "qwen-plus"
    primary_probe = probe_visual_model_capability(primary, client_factory=client_factory)
    if primary_probe.get("vision_input_supported"):
        _safe_log(
            "SCIENCE",
            "visual_llm_capability_probe",
            primary_model=primary,
            fallback_model=fallback,
            selected_model=primary,
            status="ok",
            fallback_used=False,
            fallback_attempted=False,
        )
        return {
            "model": primary,
            "fallback_used": False,
            "fallback_attempted": False,
            "probe": primary_probe,
        }
    fallback_probe = probe_visual_model_capability(fallback, client_factory=client_factory)
    if fallback_probe.get("vision_input_supported"):
        _safe_log(
            "SCIENCE",
            "visual_llm_capability_probe",
            primary_model=primary,
            fallback_model=fallback,
            selected_model=fallback,
            status="ok",
            fallback_used=True,
            fallback_attempted=True,
        )
        return {
            "model": fallback,
            "fallback_used": True,
            "fallback_attempted": True,
            "probe": {"primary": primary_probe, "fallback": fallback_probe},
        }
    _safe_log(
        "SCIENCE",
        "visual_llm_capability_probe",
        primary_model=primary,
        fallback_model=fallback,
        selected_model="",
        status="failed",
        fallback_used=True,
        fallback_attempted=True,
    )
    return {
        "model": "",
        "fallback_used": True,
        "fallback_attempted": True,
        "disabled_reason": "no_configured_qwen_model_accepts_image_input",
        "probe": {"primary": primary_probe, "fallback": fallback_probe},
    }


def build_visual_evidence_prompt(
    asset: VisualAsset | Mapping[str, Any],
    *,
    paper_metadata: dict[str, Any] | None,
    alignment_contract: dict[str, Any] | None,
) -> str:
    data = asdict(asset) if isinstance(asset, VisualAsset) else dict(asset)
    terms = alignment_contract_terms(alignment_contract)
    contract = alignment_contract if isinstance(alignment_contract, dict) else {}
    payload = {
        "sub_hypothesis_id": str(contract.get("sub_hypothesis_id") or ""),
        "scientific_object": str(contract.get("scientific_object") or ""),
        "declared_input_terms": terms["declared_input_terms"],
        "mechanism_terms": terms["mechanism_terms"],
        "outcome_terms": terms["outcome_terms"],
        "comparison_terms": terms["comparison_terms"],
    }
    schema = {
        "visual_type": "line_chart|bar_chart|scatter_plot|heatmap|table|schematic|microscopy|map|spectrum|gel|flow_diagram|unknown",
        "readable": True,
        "object_hits": [],
        "declared_input_hits": [],
        "mechanism_hits": [],
        "outcome_hits": [],
        "comparison_present": False,
        "visible_measurements": [
            {
                "name": "",
                "value": "",
                "unit": "",
                "source": "axis|legend|table_cell|annotation|caption",
                "readability": "clear|partial|unclear",
            }
        ],
        "axis_or_table_structure": {
            "x_axis": {"label": "", "unit": "", "readable": False},
            "y_axis": {"label": "", "unit": "", "readable": False},
            "columns": [],
            "rows_observed": 0,
        },
        "effect_direction": "positive|negative|null|mixed|unclear",
        "supports_current_sh": "yes|partial|no|unclear",
        "evidence_role": "visual_project_background|visual_sh_local_auxiliary|visual_component_bridge_candidate|visual_core_candidate_pending_review",
        "rationale": "",
        "limitations": [],
        "confidence": 0.0,
        "requires_human_review": True,
    }
    return (
        "Current sub-hypothesis contract:\n"
        + json.dumps(payload, ensure_ascii=False, indent=2)
        + "\n\nPaper:\n"
        + json.dumps(
            {
                "paper_id": str((paper_metadata or {}).get("paper_id") or ""),
                "title": str((paper_metadata or {}).get("title") or ""),
                "caption": str(data.get("caption") or ""),
                "nearby_text": str(data.get("nearby_text") or ""),
                "source_locator": str(data.get("source_locator") or ""),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n\nTask:\n"
        "Analyze the attached scientific figure/table image as a candidate visual evidence unit for the current sub-hypothesis.\n"
        "Extract only information visibly present in the image or explicitly present in the provided caption/nearby text.\n"
        "Return JSON exactly matching this schema:\n"
        + json.dumps(schema, ensure_ascii=False, indent=2)
        + "\n\nRules:\n"
        "- Do not claim a direct causal effect unless the visual explicitly compares the declared input against the outcome.\n"
        "- A schematic or conceptual diagram cannot be direct core evidence.\n"
        "- If declared_input_terms are absent from both image and caption/nearby text, use visual_project_background.\n"
        "- If axis labels or table headers are unreadable, effect_direction must be unclear.\n"
        "- Separate visible facts from cautious interpretation.\n"
        "- Return strict JSON only."
    )


def _extract_first_json_object(raw: str) -> str:
    text = str(raw or "").strip()
    if not text:
        raise ValueError("empty_visual_llm_response")
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
    if text.startswith("{") and text.endswith("}"):
        return text
    start = text.find("{")
    if start < 0:
        raise ValueError("no_json_object_found")
    depth = 0
    in_string = False
    escaped = False
    for offset, char in enumerate(text[start:], start=start):
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if char == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : offset + 1]
    raise ValueError("unterminated_json_object")


def parse_visual_json(raw: str) -> dict[str, Any]:
    try:
        payload = json.loads(_extract_first_json_object(raw))
    except Exception as exc:
        return {
            "status": "failed_json_parse",
            "error": str(exc)[:240],
            "raw_preview": str(raw or "")[:240],
        }
    return payload if isinstance(payload, dict) else {"status": "failed_json_parse", "error": "json_root_not_object"}


def call_qwen_visual_evidence_extractor(
    *,
    image_bytes: bytes,
    prompt_text: str,
    model: str,
    client_factory: Callable[[], Any] | None = None,
) -> dict[str, Any]:
    client = client_factory() if client_factory else qwen_multimodal_client()
    image_b64 = base64.b64encode(bytes(image_bytes or b"")).decode("ascii")
    response = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a scientific visual-evidence extraction engine.\n\n"
                    "Extract only information visibly present in the image or explicitly present in the provided caption/nearby text.\n\n"
                    "Do not infer missing labels, numeric values, statistical significance, mechanism, or causal relation.\n\n"
                    "Separate visible facts from cautious interpretation.\n\n"
                    "If the image is unreadable, cropped, or the axis labels are unclear, say so.\n\n"
                    "Return strict JSON only."
                ),
            },
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt_text},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{image_b64}"},
                    },
                ],
            },
        ],
        temperature=0,
        max_tokens=2048,
    )
    raw = response.choices[0].message.content
    parsed = parse_visual_json(str(raw or ""))
    parsed["_raw_response_preview"] = str(raw or "")[:240]
    return parsed


def _normalized_hits(payload: Mapping[str, Any], key: str, fallback: list[str] | None = None) -> list[str]:
    values = [str(item) for item in _as_list(payload.get(key)) if str(item).strip()]
    if values:
        return list(dict.fromkeys(values))[:16]
    return list(fallback or [])[:16]


def normalize_visual_evidence_payload(
    payload: dict[str, Any],
    *,
    asset: VisualAsset | Mapping[str, Any],
    paper_metadata: dict[str, Any] | None = None,
    model_selection: dict[str, Any] | None = None,
    alignment_contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    data = asdict(asset) if isinstance(asset, VisualAsset) else dict(asset)
    model = model_selection if isinstance(model_selection, dict) else {}
    source_payload = payload if isinstance(payload, dict) else {}
    visual_type = str(source_payload.get("visual_type") or "unknown").strip().lower()
    if visual_type == "null":
        visual_type = "unknown"
    if visual_type not in ALLOWED_VISUAL_TYPES:
        visual_type = "unknown"
    readable = bool(source_payload.get("readable", True))
    evidence_role = str(source_payload.get("evidence_role") or "visual_project_background").strip()
    if evidence_role not in ALLOWED_VISUAL_EVIDENCE_ROLES:
        evidence_role = "visual_project_background"
    if evidence_role == "visual_project_background":
        evidence_role = "visual_project_background_only"
    if visual_type in SCHEMATIC_VISUAL_TYPES and evidence_role == "visual_core_candidate_pending_review":
        evidence_role = "visual_sh_local_auxiliary"
    if not readable or source_payload.get("status") == "failed_json_parse":
        evidence_role = "visual_project_background_only"
    effect_direction = str(source_payload.get("effect_direction") or "unclear").strip().lower()
    if effect_direction == "none":
        effect_direction = "null"
    if effect_direction not in EFFECT_DIRECTIONS:
        effect_direction = "unclear"
    axis_or_table_structure = source_payload.get("axis_or_table_structure")
    if not isinstance(axis_or_table_structure, dict):
        axis_or_table_structure = {
            "x_axis": {"label": "", "unit": "", "readable": False},
            "y_axis": {"label": "", "unit": "", "readable": False},
            "columns": [],
            "rows_observed": 0,
        }
    measurements = [
        item
        for item in _as_list(source_payload.get("visible_measurements"))
        if isinstance(item, dict)
    ][:24]
    limitations = [str(item) for item in _as_list(source_payload.get("limitations")) if str(item).strip()][:12]
    if source_payload.get("status") == "failed_json_parse":
        limitations.append("visual_llm_json_parse_failed")
    visual_id = f"{str((paper_metadata or {}).get('paper_id') or 'paper')}_{str(data.get('asset_id') or 'visual')}"
    source_pdf_url = str(
        (paper_metadata or {}).get("source_pdf_url")
        or (paper_metadata or {}).get("open_access_pdf")
        or (paper_metadata or {}).get("source_url")
        or ""
    )
    bound_sub_hypothesis_id = str(
        (paper_metadata or {}).get("sub_hypothesis_id")
        or (alignment_contract or {}).get("sub_hypothesis_id")
        or ""
    )
    normalized = {
        "visual_id": visual_id,
        "schema_version": VISUAL_EVIDENCE_UNIT_SCHEMA_VERSION,
        "paper_id": str((paper_metadata or {}).get("paper_id") or ""),
        "paper_title": str((paper_metadata or {}).get("title") or "")[:300],
        "sub_hypothesis_id": bound_sub_hypothesis_id,
        "source_type": str(data.get("asset_type") or "figure"),
        "source_pdf_url": source_pdf_url,
        "page": int(data.get("page") or 0),
        "source_locator": str(data.get("source_locator") or ""),
        "caption": str(data.get("caption") or ""),
        "nearby_text": str(data.get("nearby_text") or ""),
        "image_sha256": str(data.get("image_sha256") or ""),
        "visual_type": visual_type,
        "readable": readable,
        "object_hits": _normalized_hits(source_payload, "object_hits", data.get("object_hits") or []),
        "declared_input_hits": _normalized_hits(source_payload, "declared_input_hits", data.get("declared_input_hits") or []),
        "mechanism_hits": _normalized_hits(source_payload, "mechanism_hits", data.get("mechanism_hits") or []),
        "outcome_hits": _normalized_hits(source_payload, "outcome_hits", data.get("outcome_hits") or []),
        "comparison_present": bool(source_payload.get("comparison_present") or data.get("comparison_hits")),
        "comparison_hits": list(data.get("comparison_hits") or [])[:16],
        "visible_measurements": measurements,
        "axis_or_table_structure": axis_or_table_structure,
        "effect_direction": effect_direction,
        "supports_current_sh": str(source_payload.get("supports_current_sh") or "unclear"),
        "evidence_role": evidence_role,
        "admission_scope": evidence_role if evidence_role != "visual_project_background" else "visual_project_background_only",
        "counts_toward_gate": False,
        "counts_toward_corpus_target": False,
        "excluded_from_direct_core_gate": True,
        "excluded_from_sh_gap_synthesis": evidence_role == "visual_project_background_only",
        "requires_human_review": True if SCIENCE_MULTIMODAL_REQUIRE_HUMAN_REVIEW else True,
        "confidence": _clamp_float(source_payload.get("confidence"), 0.0),
        "rationale": str(source_payload.get("rationale") or "")[:1200],
        "limitations": list(dict.fromkeys(limitations)),
        "llm": {
            "provider": SCIENCE_MULTIMODAL_PROVIDER,
            "model": str(model.get("model") or ""),
            "fallback_used": bool(model.get("fallback_used")),
            "api_base_configured": bool(SCIENCE_MULTIMODAL_API_BASE),
            "prompt_version": VISUAL_EVIDENCE_PROMPT_VERSION,
        },
        "human_visual_review": {
            "status": "not_requested",
            "reviewer": "",
            "reviewed_at": None,
            "notes": "",
            "approved_claims": [],
        },
        "core_eligible": False,
        "standard_core_eligible": False,
        "direct_core_pending_human_review": False,
        "multimodal_counts_toward_gate_configured": bool(SCIENCE_MULTIMODAL_COUNTS_TOWARD_GATE),
    }
    return admit_visual_evidence_unit(normalized, alignment_contract=alignment_contract or {})


def _claim_terms_for_crosscheck(visual: Mapping[str, Any], alignment_contract: Mapping[str, Any] | None) -> list[str]:
    terms: list[str] = []
    _add_terms(
        terms,
        visual.get("object_hits"),
        visual.get("declared_input_hits"),
        visual.get("mechanism_hits"),
        visual.get("outcome_hits"),
        alignment_contract_terms(alignment_contract).get("comparison_terms", [])[:8],
    )
    return terms[:32]


def _text_has_any_terms(text: str, terms: list[str]) -> bool:
    return bool(term_hits(text, terms, limit=1))


def _direction_conflict(direction: str, text: str) -> bool:
    lowered = str(text or "").lower()
    if direction == "positive" and any(marker in lowered for marker in NEGATIVE_MARKERS):
        return True
    if direction == "negative" and any(marker in lowered for marker in POSITIVE_MARKERS):
        return True
    return False


def crosscheck_visual_evidence_against_text(
    visual: dict[str, Any],
    *,
    caption: str,
    nearby_text: str,
    full_text_excerpt: str,
    alignment_contract: dict[str, Any] | None,
) -> dict[str, Any]:
    terms = _claim_terms_for_crosscheck(visual, alignment_contract)
    caption_support = _text_has_any_terms(caption, terms)
    nearby_text_support = _text_has_any_terms(nearby_text, terms)
    label_match = LABEL_RE.search(str(caption or "") or str(visual.get("source_locator") or ""))
    label = normalize_space(label_match.group(0)) if label_match else ""
    body_reference_support = bool(label and re.search(re.escape(label), str(full_text_excerpt or ""), flags=re.IGNORECASE))
    combined_text = " ".join([caption, nearby_text, str(full_text_excerpt or "")[:2400]])
    conflict_detected = _direction_conflict(str(visual.get("effect_direction") or ""), combined_text)
    if conflict_detected:
        status = "conflict"
    elif caption_support or nearby_text_support:
        status = "supported_by_caption" if caption_support else "supported_by_nearby_text"
    elif body_reference_support:
        status = "weak_text_support"
    else:
        status = "no_text_support"
    return {
        "caption_support": caption_support,
        "nearby_text_support": nearby_text_support,
        "body_reference_support": body_reference_support,
        "conflict_detected": conflict_detected,
        "crosscheck_status": status,
    }


def admit_visual_evidence_unit(
    visual: dict[str, Any],
    *,
    alignment_contract: dict[str, Any] | None,
) -> dict[str, Any]:
    item = dict(visual or {})
    crosscheck = item.get("crosscheck") if isinstance(item.get("crosscheck"), dict) else {}
    crosscheck_status = str(crosscheck.get("crosscheck_status") or "")
    requires_input = contract_requires_declared_input(alignment_contract)
    object_hits = [str(value) for value in (item.get("object_hits") or []) if str(value).strip()]
    declared_input_hits = [str(value) for value in (item.get("declared_input_hits") or []) if str(value).strip()]
    mechanism_hits = [str(value) for value in (item.get("mechanism_hits") or []) if str(value).strip()]
    outcome_hits = [str(value) for value in (item.get("outcome_hits") or []) if str(value).strip()]
    comparison_present = bool(item.get("comparison_present"))
    visual_type = str(item.get("visual_type") or "unknown")
    crosscheck_support = crosscheck_status in {
        "supported_by_caption",
        "supported_by_nearby_text",
        "weak_text_support",
    }
    if crosscheck_status in {"", "conflict", "no_text_support"}:
        scope = "visual_project_background_only"
    elif requires_input and not declared_input_hits:
        scope = "visual_project_background_only"
    elif not object_hits:
        scope = "visual_project_background_only"
    elif visual_type in SCHEMATIC_VISUAL_TYPES and (
        declared_input_hits or mechanism_hits or outcome_hits
    ):
        scope = "visual_sh_local_auxiliary"
    elif (
        object_hits
        and declared_input_hits
        and outcome_hits
        and comparison_present
        and visual_type in RESULT_VISUAL_TYPES
        and crosscheck_support
    ):
        scope = "visual_core_candidate_pending_review"
        item["direct_core_pending_human_review"] = True
    elif (
        object_hits
        and declared_input_hits
        and (mechanism_hits or outcome_hits)
        and crosscheck_support
    ):
        scope = "visual_component_bridge_candidate"
    elif object_hits and (declared_input_hits or mechanism_hits or outcome_hits):
        scope = "visual_sh_local_auxiliary"
    else:
        scope = "visual_project_background_only"
    if visual_type in SCHEMATIC_VISUAL_TYPES and scope == "visual_core_candidate_pending_review":
        scope = "visual_sh_local_auxiliary"
        item["direct_core_pending_human_review"] = False
    item["admission_scope"] = scope
    item["evidence_role"] = scope
    item["excluded_from_sh_gap_synthesis"] = scope == "visual_project_background_only"
    # First-version hard safety policy.  These values deliberately ignore both
    # the environment toggle and any LLM-returned claim.
    item["counts_toward_gate"] = False
    item["counts_toward_corpus_target"] = False
    item["excluded_from_direct_core_gate"] = True
    item["requires_human_review"] = True
    item["core_eligible"] = False
    item["standard_core_eligible"] = False
    if scope != "visual_core_candidate_pending_review":
        item["direct_core_pending_human_review"] = False
    return item


def summarize_visual_evidence(visual_evidence: list[dict[str, Any]] | None) -> dict[str, Any]:
    summary = {
        "visual_project_background_only": 0,
        "visual_sh_local_auxiliary": 0,
        "visual_component_bridge_candidate": 0,
        "visual_core_candidate_pending_review": 0,
        "total": 0,
        "counts_toward_gate": False,
        "requires_human_review": True,
    }
    for item in visual_evidence or []:
        if not isinstance(item, dict):
            continue
        scope = str(item.get("admission_scope") or "visual_project_background_only")
        if scope not in ALLOWED_VISUAL_ADMISSION_SCOPES:
            scope = "visual_project_background_only"
        summary[scope] += 1
        summary["total"] += 1
    return summary


def normalize_visual_evidence_list(
    visual_evidence: list[dict[str, Any]] | None,
    *,
    paper_id: str = "",
    sub_hypothesis_id: str = "",
    source_pdf_url: str = "",
    alignment_contract: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(visual_evidence or [], start=1):
        if not isinstance(item, dict):
            continue
        unit = dict(item)
        unit.setdefault("schema_version", VISUAL_EVIDENCE_UNIT_SCHEMA_VERSION)
        unit["paper_id"] = str(unit.get("paper_id") or paper_id or "")
        if sub_hypothesis_id and not unit.get("sub_hypothesis_id"):
            unit["sub_hypothesis_id"] = str(sub_hypothesis_id)
        if source_pdf_url and not unit.get("source_pdf_url"):
            unit["source_pdf_url"] = str(source_pdf_url)
        unit.setdefault("visual_id", f"{unit['paper_id'] or 'paper'}_visual_{index}")
        unit.setdefault("human_visual_review", {
            "status": "not_requested",
            "reviewer": "",
            "reviewed_at": None,
            "notes": "",
            "approved_claims": [],
        })
        normalized.append(admit_visual_evidence_unit(unit, alignment_contract=alignment_contract or {}))
    return normalized


def _visual_cache_key_fields(
    *,
    content_hash: str,
    asset: VisualAsset,
    alignment_contract_hash: str,
    model: str,
) -> dict[str, Any]:
    return {
        "content_hash": content_hash,
        "asset_image_sha256": asset.image_sha256,
        "alignment_contract_hash": alignment_contract_hash,
        "model": model,
        "prompt_version": VISUAL_EVIDENCE_PROMPT_VERSION,
        "schema_version": VISUAL_EVIDENCE_UNIT_SCHEMA_VERSION,
    }


def extract_multimodal_evidence_from_pdf(
    pdf_bytes: bytes,
    *,
    paper_metadata: dict[str, Any],
    alignment_contract: dict[str, Any] | None = None,
    full_text_report: dict[str, Any] | None = None,
    converted_markdown: str = "",
    max_pages: int | None = None,
    max_assets: int | None = None,
    client_factory: Callable[[], Any] | None = None,
) -> dict[str, Any]:
    """Extract structured visual evidence candidates from one full-text PDF.

    The returned visual evidence remains bound to the supplied paper metadata
    and is candidate-only.  Failures are represented as deferred statuses rather
    than exceptions so full-text import can continue.
    """

    if not SCIENCE_MULTIMODAL_ENABLED:
        return {
            "schema_version": VISUAL_EVIDENCE_RUN_SCHEMA_VERSION,
            "status": "disabled",
            "enabled": False,
            "visual_evidence": [],
        }
    project_id = str(paper_metadata.get("project_id") or "")
    sub_id = str(
        paper_metadata.get("sub_hypothesis_id")
        or (alignment_contract or {}).get("sub_hypothesis_id")
        or ""
    )
    paper_id = str(paper_metadata.get("paper_id") or "")
    page_budget = _clamp_int(max_pages, SCIENCE_MULTIMODAL_MAX_PAGES, 1, 24)
    asset_budget = _clamp_int(
        max_assets,
        SCIENCE_MULTIMODAL_MAX_ASSETS_PER_PAPER,
        1,
        64,
    )
    dpi = _clamp_int(SCIENCE_MULTIMODAL_MAX_RENDER_DPI, 180, 100, 300)
    if not SCIENCE_MULTIMODAL_API_KEY:
        return {
            "schema_version": VISUAL_EVIDENCE_RUN_SCHEMA_VERSION,
            "status": "deferred_missing_configuration",
            "enabled": True,
            "reason": "SCIENCE_MULTIMODAL_API_KEY is missing",
            "visual_evidence": [],
            "audit": {
                "page_budget": page_budget,
                "asset_budget": asset_budget,
                "render_dpi": dpi,
                "counts_toward_gate": False,
                "requires_human_review": True,
            },
        }
    model_selection = choose_visual_model(client_factory=client_factory)
    if not model_selection.get("model"):
        return {
            "schema_version": VISUAL_EVIDENCE_RUN_SCHEMA_VERSION,
            "status": "deferred_model_unavailable",
            "enabled": True,
            "visual_evidence": [],
            "audit": {
                "capability_probe": model_selection.get("probe"),
                "page_budget": page_budget,
                "asset_budget": asset_budget,
                "render_dpi": dpi,
                "counts_toward_gate": False,
                "requires_human_review": True,
            },
        }
    _safe_log(
        "SCIENCE",
        "multimodal_visual_extraction_start",
        project_id=project_id,
        sub_hypothesis_id=sub_id,
        paper_id=paper_id,
        model=str(model_selection.get("model") or ""),
        fallback_model=SCIENCE_MULTIMODAL_FALLBACK_MODEL,
        max_pages=page_budget,
        max_assets=asset_budget,
    )
    try:
        rendered_pages = render_pdf_pages(pdf_bytes, max_pages=page_budget, dpi=dpi)
    except Exception as exc:
        return {
            "schema_version": VISUAL_EVIDENCE_RUN_SCHEMA_VERSION,
            "status": "deferred_render_failed",
            "enabled": True,
            "reason": str(exc)[:240],
            "visual_evidence": [],
            "audit": {
                "capability_probe": model_selection.get("probe"),
                "page_budget": page_budget,
                "asset_budget": asset_budget,
                "render_dpi": dpi,
                "counts_toward_gate": False,
                "requires_human_review": True,
            },
        }
    captions = extract_visual_caption_candidates(
        converted_markdown=converted_markdown,
        full_text_report=full_text_report or {},
    )
    assets = select_visual_assets_for_sh(
        rendered_pages,
        captions,
        alignment_contract=alignment_contract or {},
        max_assets=asset_budget,
        converted_markdown=converted_markdown,
        paper_metadata=paper_metadata,
    )
    content_hash = str(
        paper_metadata.get("content_hash")
        or sha256(bytes(pdf_bytes or b"")).hexdigest()
    )
    contract_hash = str(
        (alignment_contract or {}).get("contract_hash")
        or paper_metadata.get("alignment_contract_hash")
        or ""
    )
    full_text_excerpt = str(paper_metadata.get("full_text_excerpt") or "")
    visual_units: list[dict[str, Any]] = []
    cache_hits = 0
    cache_misses = 0
    try:
        from ._fulltext_cache import get_visual_evidence, put_visual_evidence
    except ImportError:  # pragma: no cover - script-mode compatibility
        from _fulltext_cache import get_visual_evidence, put_visual_evidence
    for asset in assets:
        _safe_log(
            "SCIENCE",
            "visual_asset_selected",
            project_id=project_id,
            sub_hypothesis_id=sub_id,
            paper_id=paper_id,
            asset_id=asset.asset_id,
            page=asset.page,
            caption=asset.caption[:160],
            object_hits=asset.object_hits,
            declared_input_hits=asset.declared_input_hits,
            mechanism_hits=asset.mechanism_hits,
            outcome_hits=asset.outcome_hits,
            selection_score=asset.selection_score,
        )
        cache_key = _visual_cache_key_fields(
            content_hash=content_hash,
            asset=asset,
            alignment_contract_hash=contract_hash,
            model=str(model_selection.get("model") or ""),
        )
        cached = get_visual_evidence(**cache_key)
        if cached and isinstance(cached.get("result"), dict):
            visual = dict(cached["result"])
            cache_hits += 1
        else:
            cache_misses += 1
            prompt = build_visual_evidence_prompt(
                asset,
                paper_metadata=paper_metadata,
                alignment_contract=alignment_contract or {},
            )
            try:
                raw_result = call_qwen_visual_evidence_extractor(
                    image_bytes=asset.png_bytes,
                    prompt_text=prompt,
                    model=str(model_selection.get("model") or ""),
                    client_factory=client_factory,
                )
            except Exception as exc:
                raw_result = {
                    "status": "visual_llm_call_failed",
                    "readable": False,
                    "evidence_role": "visual_project_background_only",
                    "limitations": [str(exc)[:240]],
                    "confidence": 0.0,
                }
            visual = normalize_visual_evidence_payload(
                raw_result,
                asset=asset,
                paper_metadata=paper_metadata,
                model_selection=model_selection,
                alignment_contract=alignment_contract or {},
            )
            crosscheck = crosscheck_visual_evidence_against_text(
                visual,
                caption=asset.caption,
                nearby_text=asset.nearby_text,
                full_text_excerpt=full_text_excerpt,
                alignment_contract=alignment_contract or {},
            )
            visual = admit_visual_evidence_unit(
                {**visual, "crosscheck": crosscheck},
                alignment_contract=alignment_contract or {},
            )
            put_visual_evidence(visual, **cache_key)
        visual_units.append(visual)
        _safe_log(
            "SCIENCE",
            "visual_llm_extraction_complete",
            project_id=project_id,
            sub_hypothesis_id=sub_id,
            paper_id=paper_id,
            asset_id=asset.asset_id,
            model=str((visual.get("llm") or {}).get("model") or model_selection.get("model") or ""),
            fallback_used=bool((visual.get("llm") or {}).get("fallback_used") or model_selection.get("fallback_used")),
            visual_type=str(visual.get("visual_type") or ""),
            evidence_role=str(visual.get("evidence_role") or ""),
            admission_scope=str(visual.get("admission_scope") or ""),
            confidence=visual.get("confidence"),
            requires_human_review=True,
            counts_toward_gate=False,
        )
        _safe_log(
            "SCIENCE",
            "visual_evidence_gate_exclusion",
            project_id=project_id,
            sub_hypothesis_id=sub_id,
            paper_id=paper_id,
            visual_id=str(visual.get("visual_id") or ""),
            reason="vision_llm_candidate_only_requires_human_review",
            counts_toward_gate=False,
        )
    return {
        "schema_version": VISUAL_EVIDENCE_RUN_SCHEMA_VERSION,
        "status": "completed",
        "enabled": True,
        "model": str(model_selection.get("model") or ""),
        "fallback_model": SCIENCE_MULTIMODAL_FALLBACK_MODEL,
        "fallback_used": bool(model_selection.get("fallback_used")),
        "assets_detected": len(captions),
        "assets_selected": len(assets),
        "visual_evidence": visual_units,
        "admission_summary": summarize_visual_evidence(visual_units),
        "audit": {
            "capability_probe": model_selection.get("probe"),
            "page_budget": page_budget,
            "asset_budget": asset_budget,
            "render_dpi": dpi,
            "requires_human_review": True,
            "counts_toward_gate": False,
            "paper_binding": {
                "paper_id": paper_id,
                "source_pdf_url": str(
                    paper_metadata.get("source_pdf_url")
                    or paper_metadata.get("open_access_pdf")
                    or paper_metadata.get("source_url")
                    or ""
                ),
                "sub_hypothesis_id": sub_id,
                "binding_policy": "asset_page_caption_image_hash_bound_to_originating_paper",
            },
            "cache_hits": cache_hits,
            "cache_misses": cache_misses,
        },
    }
