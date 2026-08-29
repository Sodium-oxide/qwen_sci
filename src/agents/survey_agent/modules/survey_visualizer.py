"""Evidence-bounded visual enhancement for completed survey manuscripts.

The module is intentionally a post-save, fail-open companion: it never edits the
canonical ``survey.md`` and a provider or quality-control failure merely omits a
figure from ``survey_visual.md``.  Figures are planned from exact section
paragraphs, saved beside ``survey.md``, and recorded in an auditable manifest.
"""

from __future__ import annotations

import io
import json
import re
import textwrap
import unicodedata
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from PIL import Image, ImageColor, ImageDraw, ImageFont

from src.config import load_config
from src.llm.image_generation import (
    MODEL_ADAPTERS,
    DashScopeImageClient,
    resolve_image_generation_settings,
)
from src.llm.vision import QwenVisionClient, resolve_vision_settings
from src.pipeline.paper_identity import canonical_paper_id

from modules.visual_prompts import (
    ARTICLE_STYLE_PLANNER,
    FIGURE_TYPE_LAYOUT_INSTRUCTIONS,
    IMAGE_PROMPT,
    VISUAL_BRIEF_BUILDER,
    VISUAL_BRIEF_REPAIR,
    VISUAL_CANDIDATE_PLANNER,
    VISION_QC_PROMPT,
    json_schema_text,
)
from utils.utils import extract_json


_CJK_PATTERN = re.compile(r"[\u3400-\u9fff\uf900-\ufaff]")
_NON_LATIN_SCRIPT_PATTERN = re.compile(
    r"[\u0400-\u052f\u0530-\u058f\u0590-\u08ff\u0900-\u1fff\u3040-\u30ff\uac00-\ud7af]"
)
_HEX_PATTERN = re.compile(r"^#[0-9A-Fa-f]{6}$")
_PAPER_ID_PATTERN = re.compile(r"\bW\d{4,}\b")
_NUMBERED_CITATION_PATTERN = re.compile(r"\[(\d+)\]")
_HEADING_PATTERN = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_REFERENCE_MARKER_PATTERN = re.compile(
    r"^(?:references?|bibliography|reference\s+list)\s*:?\s*$",
    re.IGNORECASE,
)

DEFAULT_FIGURE_TYPES = (
    "overview_framework",
    "mechanism",
    "causal_pathway",
    "evidence_to_inference",
    "method_comparison",
    "multiscale_synthesis",
    "conceptual_workflow",
    "research_landscape",
    "future_roadmap",
)

DEFAULT_STYLE = {
    "visual_language_en": (
        "Refined editorial scientific figures with clean vector-like forms, "
        "subtle scientific rendering, ample negative space, and print-ready hierarchy."
    ),
    "palette": {
        "background": "#F6F4EF",
        "ink": "#26313A",
        "primary": "#326B7C",
        "secondary": "#5D7188",
        "accent": "#C77A37",
        "uncertainty": "#9AA2A8",
    },
}

DEFAULT_OVERLAY_LABELS = (
    "Evidence-supported relationship",
    "Stated uncertainty",
)


@dataclass(frozen=True)
class MarkdownParagraph:
    text: str
    start: int
    end: int


@dataclass(frozen=True)
class MarkdownSection:
    index: int
    title: str
    start: int
    end: int
    paragraphs: tuple[MarkdownParagraph, ...]


@dataclass(frozen=True)
class VisualCandidate:
    section_index: int
    figure_type: str
    source_paragraph_indices: tuple[int, ...]
    insert_after_paragraph: int
    main_message_en: str
    composition_en: str
    importance: int
    entities_en: tuple[str, ...] = ()


@dataclass(frozen=True)
class VisualEvidencePath:
    sub_hypothesis_id: str
    slot_name: str
    paper_id: str
    support_kind: str


@dataclass(frozen=True)
class VisualRelation:
    relation_en: str
    source_paragraph_index: int
    source_quote: str
    support_kind: str
    evidence_paper_ids: tuple[str, ...]
    evidence_paths: tuple[VisualEvidencePath, ...]


@dataclass(frozen=True)
class VisualBrief:
    figure_id: str
    figure_number: int
    figure_type: str
    section_index: int
    section_title: str
    source_paragraph_indices: tuple[int, ...]
    insert_after_paragraph: int
    main_message_en: str
    relations: tuple[VisualRelation, ...]
    entities_en: tuple[str, ...]
    uncertainties_en: tuple[str, ...]
    composition_en: str
    allowed_overlay_labels_en: tuple[str, ...]
    caption_en: str
    alt_text_en: str
    source_paper_ids: tuple[str, ...]


@dataclass(frozen=True)
class VisualStyleProfile:
    visual_language_en: str
    palette: dict[str, str]
    source: str = "llm"


@dataclass
class FigureAsset:
    brief: VisualBrief
    file_name: str
    prompt: str
    model: str
    provider: str
    quality_status: str
    qc_notes: list[str] = field(default_factory=list)
    revised_prompt: str = ""
    generation_attempts: int = 1


def _read(value: Any, name: str, default: Any = None) -> Any:
    """Read a dict, OmegaConf node, or namespace with one tolerant helper."""

    if isinstance(value, Mapping):
        return value.get(name, default)
    getter = getattr(value, "get", None)
    if callable(getter):
        try:
            return getter(name, default)
        except (AttributeError, TypeError):
            pass
    return getattr(value, name, default)


def _as_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return {str(key): item for key, item in value.items()}
    items = getattr(value, "items", None)
    if callable(items):
        try:
            return {str(key): item for key, item in items()}
        except TypeError:
            return {}
    return {}


def _clean_text(value: Any, *, limit: int = 4000) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text[:limit].strip()


def _english_text(value: Any, *, limit: int = 4000) -> str:
    """Return reader-facing English-only text, or an empty string if invalid."""

    text = _clean_text(value, limit=limit)
    if not text or _CJK_PATTERN.search(text) or _NON_LATIN_SCRIPT_PATTERN.search(text):
        return ""
    # This is intentionally a conservative script-level guard, not a language
    # detector: prompt and QC still request English, while this rejects the
    # common non-English scripts before any reader-facing Markdown is written.
    return text if re.search(r"[A-Za-z]", text) else ""


def _english_strings(value: Any, *, maximum: int) -> tuple[str, ...]:
    values = value if isinstance(value, Sequence) and not isinstance(value, (str, bytes)) else [value]
    cleaned: list[str] = []
    for item in values:
        text = _english_text(item, limit=300)
        if text and text not in cleaned:
            cleaned.append(text)
        if len(cleaned) >= maximum:
            break
    return tuple(cleaned)


def _safe_slug(value: str, *, fallback: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", str(value or "").lower()).strip("_")
    return slug[:48] or fallback


def _reference_ids(references: Any) -> tuple[str, ...]:
    """Extract canonical identifiers without exposing full citations to prompts."""

    if references is None:
        return ()
    if isinstance(references, Mapping):
        references = references.get("references", references.get("items", references))
    if isinstance(references, (str, bytes)) or not isinstance(references, Sequence):
        references = [references]
    identifiers: list[str] = []
    for reference in references:
        if isinstance(reference, Mapping):
            value = next(
                (
                    reference.get(key)
                    for key in ("paper_id", "paperId", "openalex_id", "work_id", "id")
                    if reference.get(key)
                ),
                "",
            )
        else:
            value = reference
        identifier = canonical_paper_id(_clean_text(value, limit=160))
        if identifier and identifier not in identifiers:
            identifiers.append(identifier)
    return tuple(identifiers)


def _numbered_reference_ids(text: str, reference_ids: Sequence[str]) -> tuple[str, ...]:
    """Resolve reader-visible ``[n]`` citations against the supplied list."""

    resolved: list[str] = []
    for raw_index in _NUMBERED_CITATION_PATTERN.findall(text):
        index = int(raw_index) - 1
        if 0 <= index < len(reference_ids) and reference_ids[index] not in resolved:
            resolved.append(reference_ids[index])
    return tuple(resolved)


class SurveyVisualizer:
    """Plan, generate, audit, and insert optional figure companions for a survey."""

    def __init__(
        self,
        config: Any,
        chat_agent: Any,
        logger: Any,
        *,
        image_client_factory: Callable[..., Any] = DashScopeImageClient,
        vision_client_factory: Callable[..., Any] = QwenVisionClient,
        project_config: Any = None,
    ) -> None:
        self.config = config
        self.chat_agent = chat_agent
        self.logger = logger
        self.settings = _read(_read(config, "ModuleInfo", {}), "SurveyVisualization", {})
        self.image_client_factory = image_client_factory
        self.vision_client_factory = vision_client_factory
        self.project_config = project_config or load_config()
        self._brief_rejections: list[dict[str, Any]] = []

    @property
    def enabled(self) -> bool:
        return bool(_read(self.settings, "enabled", False))

    def run(
        self,
        final_survey: str,
        *,
        survey_path: str | Path,
        references: Sequence[Any] | Mapping[str, Any] | None = None,
        evidence_plan: Mapping[str, Any] | None = None,
        outline: Mapping[str, Any] | None = None,
        claim_traceability: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Write optional visual artifacts; caller owns the fail-open boundary."""

        if not self.enabled:
            return {"status": "disabled", "figure_count": 0}

        self._brief_rejections = []
        survey_path = Path(survey_path)
        output_dir = survey_path.parent
        reference_ids = _reference_ids(references)
        outline = _as_mapping(outline)
        evidence_plan = _as_mapping(evidence_plan)
        claim_traceability = _as_mapping(claim_traceability)
        sections, survey_title = self._parse_sections(final_survey)
        if not sections:
            self.logger.warning("Survey visualisation skipped: no writable Markdown sections found.")
            return self._write_companion(
                final_survey, survey_path, [], VisualStyleProfile(
                    visual_language_en=str(DEFAULT_STYLE["visual_language_en"]),
                    palette=dict(DEFAULT_STYLE["palette"]), source="fallback_no_sections",
                ), status="skipped_no_sections", reason="no writable Markdown sections", outline=outline,
                evidence_plan=evidence_plan, reference_ids=reference_ids,
            )

        candidates = self._select_candidates(sections, survey_title, outline)
        if not candidates:
            self.logger.warning("Survey visualisation skipped: no suitable visual candidates were selected.")
            return self._write_companion(
                final_survey, survey_path, [], VisualStyleProfile(
                    visual_language_en=str(DEFAULT_STYLE["visual_language_en"]),
                    palette=dict(DEFAULT_STYLE["palette"]), source="fallback_no_candidates",
                ), status="skipped_no_candidates", reason="no suitable visual candidates", outline=outline,
                evidence_plan=evidence_plan, reference_ids=reference_ids,
            )

        briefs = self._build_briefs(
            candidates,
            sections,
            survey_title,
            evidence_plan,
            outline,
            claim_traceability,
            reference_ids,
        )
        if not briefs:
            self.logger.warning("Survey visualisation skipped: no evidence-bounded visual brief was accepted.")
            return self._write_companion(
                final_survey, survey_path, [], VisualStyleProfile(
                    visual_language_en=str(DEFAULT_STYLE["visual_language_en"]),
                    palette=dict(DEFAULT_STYLE["palette"]), source="fallback_no_briefs",
                ), status="skipped_no_briefs", reason="no evidence-bounded visual brief", outline=outline,
                evidence_plan=evidence_plan, reference_ids=reference_ids,
            )

        style = self._build_style_profile(survey_title, briefs)
        assets: list[FigureAsset] = []
        skipped_figures: list[dict[str, str]] = []
        for brief in briefs:
            try:
                asset = self._render_figure(brief, style, output_dir)
            except Exception as exc:  # Per-figure failure is explicitly non-blocking.
                self.logger.warning(
                    "Survey visualisation skipped figure %s after provider/QC failure: %s",
                    brief.figure_id,
                    exc,
                )
                skipped_figures.append(
                    {
                        "figure_id": brief.figure_id,
                        "reason": str(exc),
                    }
                )
                continue
            assets.append(asset)

        if not assets:
            return self._write_companion(
                final_survey, survey_path, [], style, status="completed_without_figures",
                reason="all generated candidates were skipped", outline=outline, skipped_figures=skipped_figures,
                evidence_plan=evidence_plan, reference_ids=reference_ids,
            )

        result = self._write_companion(
            self._insert_markdown(final_survey, sections, assets), survey_path, assets, style,
            status="completed", reason="", outline=outline, evidence_plan=evidence_plan,
            skipped_figures=skipped_figures, reference_ids=reference_ids,
        )
        self.logger.info(
            "Survey visualisation completed: %s figure(s), Markdown=%s",
            len(assets),
            result["survey_visual_path"],
        )
        return result

    def _write_companion(
        self,
        visual_markdown: str,
        survey_path: Path,
        assets: Sequence[FigureAsset],
        style: VisualStyleProfile,
        *,
        status: str,
        reason: str,
        outline: Mapping[str, Any],
        evidence_plan: Mapping[str, Any],
        reference_ids: Sequence[str] = (),
        skipped_figures: Sequence[Mapping[str, str]] = (),
    ) -> dict[str, Any]:
        """Always materialise the stable companion interface, including zero-figure runs."""

        output_dir = survey_path.parent
        image_location = str(
            _read(self.settings, "image_output_location", "survey_output_directory")
            or "survey_output_directory"
        )
        if image_location != "survey_output_directory":
            self.logger.warning(
                "Survey visualisation ignores image_output_location=%s; figures must remain beside survey.md.",
                image_location,
            )
        output_mode = str(_read(self.settings, "output_mode", "companion_markdown") or "companion_markdown")
        write_back = bool(_read(self.settings, "write_back_to_survey_md", False))
        if output_mode not in {"companion_markdown", "inline_markdown"}:
            self.logger.warning(
                "Unknown survey visual output_mode=%s; using companion_markdown.",
                output_mode,
            )
        if output_mode == "inline_markdown":
            write_back = True
        visual_path = survey_path if write_back else output_dir / "survey_visual.md"
        visual_path.write_text(visual_markdown, encoding="utf-8")
        manifest_path = output_dir / "survey_visual_manifest.json"
        manifest = self._build_manifest(
            survey_path=survey_path,
            visual_path=visual_path,
            style=style,
            assets=assets,
            status=status,
            reason=reason,
            outline=outline,
            evidence_plan=evidence_plan,
            reference_ids=reference_ids,
            rejected_figures=self._brief_rejections,
            skipped_figures=skipped_figures,
        )
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        return {
            "status": status,
            "reason": reason,
            "figure_count": len(assets),
            "survey_visual_path": str(visual_path),
            "manifest_path": str(manifest_path),
            "style_profile": asdict(style),
        }

    def _parse_sections(self, survey: str) -> tuple[list[MarkdownSection], str]:
        title = "Survey"
        lines = survey.splitlines(keepends=True)
        offsets: list[int] = []
        offset = 0
        for line in lines:
            offsets.append(offset)
            offset += len(line)

        headings: list[tuple[int, int, str]] = []
        for index, line in enumerate(lines):
            match = _HEADING_PATTERN.match(line.strip())
            if not match:
                continue
            level = len(match.group(1))
            heading = _clean_text(match.group(2), limit=300)
            if level == 1 and title == "Survey":
                title = heading or title
            if level == 2:
                headings.append((index, level, heading))

        sections: list[MarkdownSection] = []
        for section_index, (line_index, _level, heading) in enumerate(headings, start=1):
            if heading.lower() in {"references", "bibliography", "reference list"}:
                break
            next_line_index = (
                headings[section_index][0]
                if section_index < len(headings)
                else len(lines)
            )
            paragraphs = self._paragraphs_from_lines(
                lines,
                offsets,
                line_index + 1,
                next_line_index,
            )
            if paragraphs:
                sections.append(
                    MarkdownSection(
                        index=section_index,
                        title=heading or f"Section {section_index}",
                        start=offsets[line_index],
                        end=offsets[next_line_index] if next_line_index < len(offsets) else len(survey),
                        paragraphs=tuple(paragraphs),
                    )
                )
        return sections, title

    @staticmethod
    def _paragraphs_from_lines(
        lines: Sequence[str],
        offsets: Sequence[int],
        start: int,
        end: int,
    ) -> list[MarkdownParagraph]:
        paragraphs: list[MarkdownParagraph] = []
        buffered: list[str] = []
        paragraph_start: int | None = None
        paragraph_end: int | None = None

        def flush() -> None:
            nonlocal buffered, paragraph_start, paragraph_end
            text = _clean_text(" ".join(buffered), limit=12000)
            if text and paragraph_start is not None and paragraph_end is not None:
                if not text.startswith("[[SH_CLAIM_TRACE") and not text.startswith("[[/SH_CLAIM_TRACE"):
                    paragraphs.append(MarkdownParagraph(text=text, start=paragraph_start, end=paragraph_end))
            buffered = []
            paragraph_start = None
            paragraph_end = None

        for line_index in range(start, end):
            raw = lines[line_index]
            stripped = raw.strip()
            if not stripped:
                flush()
                continue
            if _REFERENCE_MARKER_PATTERN.match(stripped):
                flush()
                break
            if _HEADING_PATTERN.match(stripped):
                flush()
                continue
            if paragraph_start is None:
                paragraph_start = offsets[line_index]
            buffered.append(stripped)
            paragraph_end = offsets[line_index] + len(raw.rstrip("\r\n"))
        flush()
        return paragraphs

    def _select_candidates(
        self,
        sections: Sequence[MarkdownSection],
        survey_title: str,
        outline: Mapping[str, Any],
    ) -> list[VisualCandidate]:
        allowed_types = tuple(
            str(item).strip()
            for item in (_read(self.settings, "allowed_figure_types", DEFAULT_FIGURE_TYPES) or DEFAULT_FIGURE_TYPES)
            if str(item).strip() in DEFAULT_FIGURE_TYPES
        ) or DEFAULT_FIGURE_TYPES
        min_figures = max(1, int(_read(self.settings, "min_figures", 3) or 3))
        max_figures = max(1, int(_read(self.settings, "max_figures", 5) or 5))
        min_figures = min(min_figures, max_figures)
        max_context_per_section = max(800, int(_read(self.settings, "planner_section_max_chars", 6000) or 6000))
        section_texts: list[str] = []
        for section in sections:
            paragraphs = "\n".join(
                f"[{index}] {paragraph.text}"
                for index, paragraph in enumerate(section.paragraphs, start=1)
            )
            section_texts.append(
                f"SECTION {section.index}: {section.title}\n{paragraphs[:max_context_per_section]}"
            )

        schema = {
            "type": "object",
            "properties": {
                "candidates": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "section_index": {"type": "integer"},
                            "figure_type": {"type": "string"},
                            "source_paragraph_indices": {"type": "array", "items": {"type": "integer"}},
                            "insert_after_paragraph": {"type": "integer"},
                            "main_message_en": {"type": "string"},
                            "composition_en": {"type": "string"},
                            "entities_en": {"type": "array", "items": {"type": "string"}},
                            "importance": {"type": "integer"},
                        },
                        "required": [
                            "section_index", "figure_type", "source_paragraph_indices",
                            "insert_after_paragraph", "main_message_en", "composition_en", "importance",
                        ],
                        "additionalProperties": False,
                    },
                }
            },
            "required": ["candidates"],
            "additionalProperties": False,
        }
        prompt = VISUAL_CANDIDATE_PLANNER.format(
            allowed_figure_types=", ".join(allowed_types),
            survey_title=survey_title,
            outline_context=self._outline_context(outline),
            sections="\n\n".join(section_texts),
            numeric_chart_policy=(
                "Programmatic numeric charts are enabled only when structured data are supplied."
                if bool(_read(self.settings, "allow_generated_numeric_charts", False))
                else "Generated numeric charts are disabled; select only conceptual figures."
            ),
            min_figures=min_figures,
            max_figures=max_figures,
            schema=json_schema_text(schema),
        )
        try:
            payload = self._request_json(prompt, max_output_tokens=3000)
        except Exception as exc:
            self.logger.warning("Survey visual candidate planner failed: %s", exc)
            return self._fallback_candidates(sections, allowed_types, max_figures)

        section_map = {section.index: section for section in sections}
        accepted: list[VisualCandidate] = []
        seen_section_types: set[tuple[int, str]] = set()
        raw_candidates = _read(payload, "candidates", [])
        if not isinstance(raw_candidates, Sequence) or isinstance(raw_candidates, (str, bytes)):
            raw_candidates = []
        for candidate_number, raw in enumerate(raw_candidates, start=1):
            item = _as_mapping(raw)
            raw_section_index = item.get("section_index")
            raw_figure_type = _clean_text(item.get("figure_type"), limit=120)
            candidate_id = f"candidate_{candidate_number:02d}_{_safe_slug(raw_figure_type, fallback='unknown')}"

            def reject_candidate(reason: str) -> None:
                rejection = {
                    "figure_id": candidate_id,
                    "section_index": raw_section_index,
                    "figure_type": raw_figure_type,
                    "reasons": [reason],
                    "repair_attempted": False,
                    "stage": "candidate_selection",
                }
                self._brief_rejections.append(rejection)
                self.logger.warning(
                    "Survey visual candidate rejected (%s): %s",
                    candidate_id,
                    reason,
                )

            try:
                section_index = int(item.get("section_index"))
                section = section_map[section_index]
                figure_type = str(item.get("figure_type") or "").strip()
                paragraph_indices = tuple(sorted({int(index) for index in item.get("source_paragraph_indices", [])}))
                insert_after = int(item.get("insert_after_paragraph"))
                importance = max(1, min(5, int(item.get("importance", 3))))
            except (KeyError, TypeError, ValueError):
                reject_candidate("invalid section_index, figure_type, paragraph indices, or insert_after_paragraph")
                continue
            if figure_type not in allowed_types or not paragraph_indices:
                reject_candidate("figure_type is not allowed or source_paragraph_indices is empty")
                continue
            candidate_entities = _english_strings(item.get("entities_en"), maximum=8)
            if len(paragraph_indices) < 2 and len(candidate_entities) < 3:
                # A single paragraph is acceptable only when the planner
                # identifies enough distinct entities to justify integration.
                reject_candidate(
                    "candidate requires at least two source paragraphs or three English entities"
                )
                continue
            if any(index < 1 or index > len(section.paragraphs) for index in paragraph_indices):
                reject_candidate("source_paragraph_indices contains an out-of-range paragraph")
                continue
            if insert_after < 1 or insert_after > len(section.paragraphs):
                reject_candidate("insert_after_paragraph is outside the selected section")
                continue
            main_message = _english_text(item.get("main_message_en"), limit=700)
            composition = _english_text(item.get("composition_en"), limit=700)
            entities = candidate_entities
            if not main_message or not composition:
                reject_candidate("main_message_en or composition_en is missing or non-English")
                continue
            key = (section_index, figure_type)
            if key in seen_section_types:
                reject_candidate("duplicate section_index and figure_type")
                continue
            seen_section_types.add(key)
            accepted.append(
                VisualCandidate(
                    section_index=section_index,
                    figure_type=figure_type,
                    source_paragraph_indices=paragraph_indices,
                    insert_after_paragraph=insert_after,
                    main_message_en=main_message,
                    composition_en=composition,
                    importance=importance,
                    entities_en=entities,
                )
            )

        accepted.sort(key=lambda candidate: (-candidate.importance, candidate.section_index))
        return accepted[:max_figures]

    @staticmethod
    def _fallback_candidates(
        sections: Sequence[MarkdownSection],
        allowed_types: Sequence[str],
        max_figures: int,
    ) -> list[VisualCandidate]:
        """A modest fail-open fallback when the visual editor response is unavailable."""

        candidates: list[VisualCandidate] = []
        if sections and "overview_framework" in allowed_types:
            section = sections[0]
            source_indices = tuple(range(1, min(3, len(section.paragraphs)) + 1))
            if source_indices:
                candidates.append(
                    VisualCandidate(
                        section_index=section.index,
                        figure_type="overview_framework",
                        source_paragraph_indices=source_indices,
                        insert_after_paragraph=source_indices[-1],
                        main_message_en="A conceptual overview of the relationships introduced in this section.",
                        composition_en="Use a layered overview with a clear reading direction and reserved negative space.",
                        importance=3,
                    )
                )
        return candidates[:max_figures]

    def _build_briefs(
        self,
        candidates: Sequence[VisualCandidate],
        sections: Sequence[MarkdownSection],
        survey_title: str,
        evidence_plan: Mapping[str, Any],
        outline: Mapping[str, Any],
        claim_traceability: Mapping[str, Any],
        reference_ids: Sequence[str] = (),
    ) -> list[VisualBrief]:
        section_map = {section.index: section for section in sections}
        evidence_context = self._evidence_context(
            evidence_plan,
            include_gaps=bool(_read(self.settings, "show_explicit_evidence_gaps", True)),
        )
        briefs: list[VisualBrief] = []
        for figure_number, candidate in enumerate(candidates, start=1):
            section = section_map[candidate.section_index]
            source_paragraphs = [section.paragraphs[index - 1].text for index in candidate.source_paragraph_indices]
            schema = {
                "type": "object",
                "properties": {
                    "main_message_en": {"type": "string"},
                    "relations": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "relation_en": {"type": "string"},
                                "source_paragraph_index": {"type": "integer"},
                                "source_quote": {"type": "string"},
                            },
                            "required": ["relation_en", "source_paragraph_index", "source_quote"],
                            "additionalProperties": False,
                        },
                    },
                    "entities_en": {"type": "array", "items": {"type": "string"}},
                    "uncertainties_en": {"type": "array", "items": {"type": "string"}},
                    "composition_en": {"type": "string"},
                    "allowed_overlay_labels_en": {"type": "array", "items": {"type": "string"}},
                    "caption_en": {"type": "string"},
                    "alt_text_en": {"type": "string"},
                },
                "required": [
                    "main_message_en", "relations", "entities_en", "uncertainties_en",
                    "composition_en", "allowed_overlay_labels_en", "caption_en", "alt_text_en",
                ],
                "additionalProperties": False,
            }
            paragraph_block = "\n\n".join(
                f"Paragraph {index}: {paragraph}"
                for index, paragraph in zip(candidate.source_paragraph_indices, source_paragraphs)
            )
            prompt = VISUAL_BRIEF_BUILDER.format(
                survey_title=survey_title,
                section_title=section.title,
                figure_type=candidate.figure_type,
                proposed_message=candidate.main_message_en,
                outline_context=self._outline_context(outline, section_title=section.title),
                source_paragraphs=paragraph_block,
                evidence_context=evidence_context,
                schema=json_schema_text(schema),
            )
            payload: Any = {}
            rejection_reasons: tuple[str, ...] = ()
            initial_failure = ""
            try:
                payload = self._request_json(prompt, max_output_tokens=2400)
                brief, rejection_reasons = self._brief_from_payload_with_reasons(
                    payload,
                    candidate,
                    section,
                    figure_number,
                    source_paragraphs,
                    evidence_plan,
                    outline,
                    claim_traceability,
                    reference_ids,
                )
            except Exception as exc:
                brief = None
                initial_failure = f"initial brief request/parse failed: {type(exc).__name__}: {exc}"
                rejection_reasons = (initial_failure,)

            repair_attempted = False
            if brief is None and bool(_read(self.settings, "visual_brief_repair_enabled", True)):
                repair_attempted = True
                try:
                    repaired_payload = self._repair_visual_brief_payload(
                        survey_title=survey_title,
                        section=section,
                        candidate=candidate,
                        paragraph_block=paragraph_block,
                        evidence_context=evidence_context,
                        original_payload=payload,
                        rejection_reasons=rejection_reasons,
                        schema=schema,
                    )
                    brief, repair_reasons = self._brief_from_payload_with_reasons(
                        repaired_payload,
                        candidate,
                        section,
                        figure_number,
                        source_paragraphs,
                        evidence_plan,
                        outline,
                        claim_traceability,
                        reference_ids,
                    )
                    if brief is not None:
                        self.logger.info(
                            "Survey visual brief repaired for section %s after format validation.",
                            section.index,
                        )
                    else:
                        rejection_reasons = rejection_reasons + tuple(
                            f"repair: {reason}" for reason in repair_reasons
                        )
                except Exception as exc:
                    rejection_reasons = rejection_reasons + (
                        f"repair request/parse failed: {type(exc).__name__}: {exc}",
                    )

            if brief is not None:
                briefs.append(brief)
                continue

            rejection = {
                "figure_id": f"fig_{figure_number:02d}_{_safe_slug(candidate.figure_type, fallback='conceptual_figure')}",
                "section_index": candidate.section_index,
                "figure_type": candidate.figure_type,
                "reasons": list(dict.fromkeys(rejection_reasons)) or ["brief rejected without a recorded reason"],
                "repair_attempted": repair_attempted,
                "stage": "brief_validation",
            }
            self._brief_rejections.append(rejection)
            self.logger.warning(
                "Survey visual brief rejected for section %s (%s): %s",
                section.index,
                rejection["figure_id"],
                "; ".join(rejection["reasons"]),
            )
        return briefs

    def _repair_visual_brief_payload(
        self,
        *,
        survey_title: str,
        section: MarkdownSection,
        candidate: VisualCandidate,
        paragraph_block: str,
        evidence_context: str,
        original_payload: Any,
        rejection_reasons: Sequence[str],
        schema: Mapping[str, Any],
    ) -> Any:
        prompt = VISUAL_BRIEF_REPAIR.format(
            survey_title=survey_title,
            section_title=section.title,
            figure_type=candidate.figure_type,
            source_paragraphs=paragraph_block,
            evidence_context=evidence_context,
            original_payload=json.dumps(original_payload, ensure_ascii=False, default=str)[:12000],
            rejection_reasons="\n".join(f"- {reason}" for reason in rejection_reasons) or "- no valid payload was returned",
            schema=json_schema_text(schema),
        )
        return self._request_json(
            prompt,
            max_output_tokens=max(1200, int(_read(self.settings, "visual_brief_repair_max_output_tokens", 2400) or 2400)),
        )

    def _brief_from_payload(
        self,
        payload: Any,
        candidate: VisualCandidate,
        section: MarkdownSection,
        figure_number: int,
        source_paragraphs: Sequence[str],
        evidence_plan: Mapping[str, Any],
        outline: Mapping[str, Any],
        claim_traceability: Mapping[str, Any],
        reference_ids: Sequence[str] = (),
    ) -> VisualBrief | None:
        brief, _reasons = self._brief_from_payload_with_reasons(
            payload,
            candidate,
            section,
            figure_number,
            source_paragraphs,
            evidence_plan,
            outline,
            claim_traceability,
            reference_ids,
        )
        return brief

    def _brief_from_payload_with_reasons(
        self,
        payload: Any,
        candidate: VisualCandidate,
        section: MarkdownSection,
        figure_number: int,
        source_paragraphs: Sequence[str],
        evidence_plan: Mapping[str, Any],
        outline: Mapping[str, Any],
        claim_traceability: Mapping[str, Any],
        reference_ids: Sequence[str] = (),
    ) -> tuple[VisualBrief | None, tuple[str, ...]]:
        item = _as_mapping(payload)
        main_message = _english_text(item.get("main_message_en"), limit=700) or _english_text(
            getattr(candidate, "main_message_en", ""),
            limit=700,
        )
        composition = _english_text(item.get("composition_en"), limit=700) or _english_text(
            candidate.composition_en,
            limit=700,
        )
        caption = _english_text(item.get("caption_en"), limit=900)
        alt_text = _english_text(item.get("alt_text_en"), limit=700)
        relation_rejection_reasons: list[str] = []
        relations = self._validated_relations(
            item.get("relations", []),
            candidate,
            section,
            evidence_plan,
            outline,
            claim_traceability,
            reference_ids,
            rejection_reasons=relation_rejection_reasons,
        )
        entities = _english_strings(item.get("entities_en"), maximum=8)
        if not entities:
            entities = _english_strings(
                getattr(candidate, "entities_en", ()),
                maximum=8,
            )
        if not entities:
            entities = _english_strings(
                (
                    section.title,
                    str(getattr(candidate, "figure_type", "")).replace("_", " "),
                    "Evidence-supported relationship",
                ),
                maximum=8,
            )
        uncertainties = _english_strings(item.get("uncertainties_en"), maximum=5)
        labels = _english_strings(item.get("allowed_overlay_labels_en"), maximum=6)
        rejection_reasons: list[str] = []
        if not main_message:
            rejection_reasons.append("missing or non-English main_message_en")
        if not composition:
            rejection_reasons.append("missing or non-English composition_en")
        if not relations:
            rejection_reasons.append("no evidence-bounded relation survived validation")
            if relation_rejection_reasons:
                counts = Counter(relation_rejection_reasons)
                detail = "; ".join(
                    f"{reason} ({count})" if count > 1 else reason
                    for reason, count in counts.items()
                )
                rejection_reasons.append(f"relation validation details: {detail}")
        if not entities:
            rejection_reasons.append("missing or non-English entities_en")
        if rejection_reasons:
            return None, tuple(rejection_reasons)

        caption = caption or "Conceptual synthesis of the supported survey relationships."
        alt_text = alt_text or (
            "Conceptual diagram of the evidence-supported relationships discussed in this section."
        )
        labels = labels or DEFAULT_OVERLAY_LABELS
        caption = self._normalise_caption(caption, figure_number)
        source_ids = tuple(sorted({
            paper_id
            for relation in relations
            for paper_id in relation.evidence_paper_ids
        } | {
            paper_id for text in source_paragraphs for paper_id in _PAPER_ID_PATTERN.findall(text)
        }))
        figure_id = f"fig_{figure_number:02d}_{_safe_slug(candidate.figure_type, fallback='conceptual_figure')}"
        return VisualBrief(
            figure_id=figure_id,
            figure_number=figure_number,
            figure_type=candidate.figure_type,
            section_index=section.index,
            section_title=section.title,
            source_paragraph_indices=candidate.source_paragraph_indices,
            insert_after_paragraph=candidate.insert_after_paragraph,
            main_message_en=main_message,
            relations=relations,
            entities_en=entities,
            uncertainties_en=uncertainties,
            composition_en=composition,
            allowed_overlay_labels_en=labels,
            caption_en=caption,
            alt_text_en=alt_text,
            source_paper_ids=source_ids,
        ), ()

    @staticmethod
    def _normalise_caption(caption: str, figure_number: int) -> str:
        text = _clean_text(caption, limit=900)
        text = re.sub(r"^figure\s+\d+\s*[|:.\-]?\s*", "", text, flags=re.IGNORECASE).strip()
        if not text:
            text = "Conceptual synthesis of the supported survey relationships."
        if not text.endswith((".", "!", "?")):
            text += "."
        evidence_note = (
            "This schematic is a conceptual synthesis of the cited survey evidence "
            "and introduces no new empirical data."
        )
        if evidence_note.casefold() not in text.casefold():
            text = f"{text} {evidence_note}"
        return f"Figure {figure_number} | {text}"

    def _build_style_profile(
        self,
        survey_title: str,
        briefs: Sequence[VisualBrief],
    ) -> VisualStyleProfile:
        if not bool(_read(self.settings, "generate_article_style_profile", True)):
            return VisualStyleProfile(
                visual_language_en=str(DEFAULT_STYLE["visual_language_en"]),
                palette=dict(DEFAULT_STYLE["palette"]),
                source="fallback_disabled",
            )
        schema = {
            "type": "object",
            "properties": {
                "visual_language_en": {"type": "string"},
                "palette": {
                    "type": "object",
                    "properties": {
                        role: {"type": "string"}
                        for role in ("background", "ink", "primary", "secondary", "accent", "uncertainty")
                    },
                    "required": ["background", "ink", "primary", "secondary", "accent", "uncertainty"],
                    "additionalProperties": False,
                },
            },
            "required": ["visual_language_en", "palette"],
            "additionalProperties": False,
        }
        summaries = "\n".join(
            f"- {brief.figure_id}: {brief.figure_type}; {brief.main_message_en}"
            for brief in briefs
        )
        prompt = ARTICLE_STYLE_PLANNER.format(
            survey_title=survey_title,
            figure_summaries=summaries,
            schema=json_schema_text(schema),
        )
        try:
            payload = self._request_json(prompt, max_output_tokens=1600)
            raw_palette = _as_mapping(_read(payload, "palette", {}))
            palette = {role: str(raw_palette.get(role) or "").strip() for role in DEFAULT_STYLE["palette"]}
            visual_language = _english_text(_read(payload, "visual_language_en"), limit=900)
            if visual_language and all(_HEX_PATTERN.match(color) for color in palette.values()):
                return VisualStyleProfile(
                    visual_language_en=visual_language,
                    palette=palette,
                    source="llm",
                )
            raise ValueError("style response lacks English text or a complete valid hex palette")
        except Exception as exc:
            self.logger.warning("Survey visual style planner failed; using neutral fallback palette: %s", exc)
            return VisualStyleProfile(
                visual_language_en=str(DEFAULT_STYLE["visual_language_en"]),
                palette=dict(DEFAULT_STYLE["palette"]),
                source="fallback",
            )

    def _render_figure(
        self,
        brief: VisualBrief,
        style: VisualStyleProfile,
        output_dir: Path,
    ) -> FigureAsset:
        prompt = self._image_prompt(brief, style)
        role = str(_read(self.settings, "final_image_role", "academic_figure") or "academic_figure")
        image_settings = resolve_image_generation_settings(self.project_config, role=role)
        image_client = self.image_client_factory(
            api_key=image_settings["api_key"],
            base_url=image_settings["base_url"],
            timeout=image_settings["timeout"],
            poll_interval=image_settings["poll_interval"],
            config=self.project_config,
        )
        candidate_count = max(1, min(4, int(_read(self.settings, "candidates_per_figure", 2) or 2)))
        size = self._image_size_for_model(image_settings["model"])
        regenerate_for_palette = bool(
            _read(self.settings, "regenerate_on_palette_mismatch", True)
        )
        max_regenerations = max(
            0,
            min(3, int(_read(self.settings, "max_regeneration_attempts", 1) or 0)),
        )
        max_attempts = 1 + (max_regenerations if regenerate_for_palette else 0)
        accumulated_notes: list[str] = []

        for attempt in range(1, max_attempts + 1):
            response = image_client.generate(
                prompt=prompt,
                model=image_settings["model"],
                n=candidate_count,
                size=size,
                output_format="png",
            )
            image_bytes, quality_status, qc_notes, palette_mismatch = self._select_image_candidate(
                response.images,
                brief,
                style,
            )
            accumulated_notes.extend(f"generation {attempt}: {note}" for note in qc_notes)
            if image_bytes is not None:
                if bool(_read(self.settings, "append_english_label_strip", True)):
                    image_bytes = self._append_label_strip(image_bytes, brief, style)
                file_name = self._image_file_name(brief)
                (output_dir / file_name).write_bytes(image_bytes)
                return FigureAsset(
                    brief=brief,
                    file_name=file_name,
                    prompt=prompt,
                    model=str(response.model),
                    provider=str(response.provider),
                    quality_status=quality_status,
                    qc_notes=accumulated_notes,
                    revised_prompt=str(response.revised_prompt or ""),
                    generation_attempts=attempt,
                )
            if not palette_mismatch or attempt == max_attempts:
                break
            self.logger.warning(
                "Survey visualisation regenerating figure %s after palette mismatch (%s/%s).",
                brief.figure_id,
                attempt,
                max_attempts,
            )

        raise RuntimeError(
            "All generated image candidates were rejected by visual QC. "
            + " ".join(accumulated_notes)
        )

    def _image_size_for_model(self, model: str) -> str:
        """Keep a high-resolution default without breaking non-4K Qwen roles."""

        requested = str(_read(self.settings, "final_image_size", "3072x2304") or "3072x2304")
        try:
            width, height = (int(part) for part in requested.lower().replace("*", "x").split("x", 1))
        except (TypeError, ValueError):
            return requested
        if max(width, height) <= 2048:
            return requested
        configured_models = _as_mapping(_read(self.project_config, "image_generation", {})).get("models", {})
        configured_model = _as_mapping(_as_mapping(configured_models).get(model, {}))
        adapter = MODEL_ADAPTERS.get(str(model))
        supports_4k = bool(
            configured_model.get(
                "supports_4k",
                getattr(adapter, "supports_4k", False),
            )
        )
        if supports_4k:
            return requested
        compatible_size = str(
            _read(self.settings, "compatible_image_size", "2048x1536") or "2048x1536"
        )
        self.logger.info(
            "Survey visualisation model %s does not declare 4K support; using %s instead of %s.",
            model,
            compatible_size,
            requested,
        )
        return compatible_size

    def _image_file_name(self, brief: VisualBrief) -> str:
        """Resolve a safe, same-directory PNG filename from the configured template."""

        template = str(
            _read(self.settings, "image_filename_template", "fig_{index:02d}_{slug}.png")
            or "fig_{index:02d}_{slug}.png"
        )
        try:
            file_name = template.format(
                index=brief.figure_number,
                slug=_safe_slug(brief.figure_type, fallback="conceptual_figure"),
            )
        except (KeyError, ValueError):
            file_name = f"{brief.figure_id}.png"
        # The visual companion contract intentionally forbids subdirectories.
        file_name = Path(file_name.replace("\\", "/")).name
        return file_name if file_name.lower().endswith(".png") else f"{file_name}.png"

    def _image_prompt(self, brief: VisualBrief, style: VisualStyleProfile) -> str:
        palette = style.palette
        return IMAGE_PROMPT.format(
            figure_type=brief.figure_type.replace("_", " "),
            main_message=brief.main_message_en,
            relations="\n".join(f"- {relation.relation_en}" for relation in brief.relations),
            relation_guidance=(
                "Use solid prominent paths for directly supported relationships. "
                "Use thin, dashed, or muted paths for qualified contributions. "
                "Use translucent or restrained elements for background context. "
                "Never render evidence classifications, support metadata, paper IDs, "
                "or internal audit labels as visible text."
            ),
            entities=", ".join(brief.entities_en),
            exact_visible_labels=(
                json.dumps(list(brief.allowed_overlay_labels_en), ensure_ascii=False)
                if brief.allowed_overlay_labels_en
                else "None supplied; do not render any reader-facing labels."
            ),
            uncertainties=(
                "\n".join(f"- {item}" for item in brief.uncertainties_en)
                if bool(_read(self.settings, "show_explicit_evidence_gaps", True))
                else "Do not render uncertainty annotations."
            ) or "None stated in the supplied section.",
            composition=brief.composition_en,
            figure_type_layout=FIGURE_TYPE_LAYOUT_INSTRUCTIONS.get(
                brief.figure_type,
                "Use a clear conceptual composition based only on the supplied relationships.",
            ),
            visual_language=style.visual_language_en,
            **palette,
        )

    def _select_image_candidate(
        self,
        images: Sequence[bytes],
        brief: VisualBrief,
        style: VisualStyleProfile,
    ) -> tuple[bytes | None, str, list[str], bool]:
        if not images:
            return None, "rejected", ["Image provider returned no candidates."], False
        if not bool(_read(self.settings, "visual_qc_enabled", True)):
            return images[0], "not_reviewed", [], False
        advisory_notes: list[str] = []
        palette_mismatch = False
        for index, image in enumerate(images, start=1):
            accepted, notes, reviewed, palette_matches = self._run_visual_qc(image, brief, style)
            advisory_notes.extend(f"candidate {index}: {note}" for note in notes)
            if reviewed and not palette_matches:
                palette_mismatch = True
            if accepted:
                return image, "accepted" if reviewed else "qc_unavailable", advisory_notes, False
        return None, "rejected", advisory_notes or ["Visual QC rejected all candidates."], palette_mismatch

    def _run_visual_qc(
        self,
        image_bytes: bytes,
        brief: VisualBrief,
        style: VisualStyleProfile,
    ) -> tuple[bool, list[str], bool, bool]:
        schema = {
            "type": "object",
            "properties": {
                "accept": {"type": "boolean"},
                "major_issues": {"type": "array", "items": {"type": "string"}},
                "palette_match": {"type": "boolean"},
                "reader_facing_text_is_english": {"type": "boolean"},
            },
            "required": ["accept", "major_issues", "palette_match", "reader_facing_text_is_english"],
            "additionalProperties": False,
        }
        compact_brief = {
            "figure_type": brief.figure_type,
            "main_message_en": brief.main_message_en,
            "relations": [
                {
                    "relation_en": relation.relation_en,
                    "source_paragraph_index": relation.source_paragraph_index,
                }
                for relation in brief.relations
            ],
            "uncertainties_en": brief.uncertainties_en,
        }
        prompt = VISION_QC_PROMPT.format(
            brief=json.dumps(compact_brief, ensure_ascii=False),
            palette=json.dumps(style.palette, sort_keys=True),
            schema=json_schema_text(schema),
        )
        try:
            settings = resolve_vision_settings(self.project_config)
            client = self.vision_client_factory(
                model=settings["model"],
                provider=settings["provider"],
                api_key=settings["api_key"],
                base_url=settings["base_url"],
                timeout=settings["timeout"],
                config=self.project_config,
            )
            raw = client.describe(
                image_bytes,
                prompt=prompt,
                max_tokens=min(1600, int(settings["max_tokens"])),
                response_format={"type": "json_object"},
            )
            result = _as_mapping(extract_json(raw))
            notes = _english_strings(result.get("major_issues", []), maximum=8)
            palette_matches = bool(result.get("palette_match", False))
            accepted = bool(result.get("accept", False)) and palette_matches
            if not palette_matches:
                notes = notes + ("The candidate does not match the locked article palette.",)
            if not bool(result.get("reader_facing_text_is_english", True)):
                accepted = False
                notes = notes + ("The candidate contains non-English reader-facing text.",)
            return accepted, list(notes), True, palette_matches
        except Exception as exc:
            # QC has no authority to turn an optional enhancement into a pipeline failure.
            return True, [f"Visual QC unavailable; accepted fail-open ({exc})."], False, True

    @staticmethod
    def _append_label_strip(
        image_bytes: bytes,
        brief: VisualBrief,
        style: VisualStyleProfile,
    ) -> bytes:
        """Optionally add a compact English-only concept strip beneath a generated image."""

        labels = brief.allowed_overlay_labels_en[:4]
        if not labels:
            return image_bytes
        with Image.open(io.BytesIO(image_bytes)) as image:
            canvas = image.convert("RGB")
            footer_height = max(90, int(canvas.height * 0.11))
            output = Image.new("RGB", (canvas.width, canvas.height + footer_height), ImageColor.getrgb(style.palette["background"]))
            output.paste(canvas, (0, 0))
            draw = ImageDraw.Draw(output)
            try:
                font = ImageFont.truetype("DejaVuSans.ttf", max(16, footer_height // 6))
            except OSError:
                font = ImageFont.load_default()
            text = " · ".join(labels)
            draw.text(
                (max(24, canvas.width // 40), canvas.height + footer_height // 3),
                text,
                fill=ImageColor.getrgb(style.palette["ink"]),
                font=font,
            )
            buffer = io.BytesIO()
            output.save(buffer, format="PNG")
            return buffer.getvalue()

    @staticmethod
    def _outline_context(
        outline: Mapping[str, Any],
        *,
        section_title: str = "",
    ) -> str:
        """Provide the approved outline as a bounded planning constraint, not evidence."""

        outline_map = _as_mapping(outline)
        sections = outline_map.get("sections", [])
        if not isinstance(sections, Sequence) or isinstance(sections, (str, bytes)):
            return "No approved outline artifact is available. Use the supplied manuscript section only."
        requested = _clean_text(section_title, limit=300).casefold()
        summaries: list[str] = []
        for raw_section in sections:
            item = _as_mapping(raw_section)
            title = _clean_text(item.get("title"), limit=300)
            if requested and title.casefold() != requested:
                continue
            description = _clean_text(item.get("description"), limit=900)
            subsections = [
                _clean_text(_as_mapping(raw_subsection).get("title"), limit=220)
                for raw_subsection in item.get("subsections", [])
                if _clean_text(_as_mapping(raw_subsection).get("title"), limit=220)
            ]
            paper_ids = SurveyVisualizer._outline_paper_ids_from_section(item)
            summaries.append(
                f"Section: {title or 'Untitled'}; purpose: {description or 'not specified'}; "
                f"subsections: {', '.join(subsections) or 'none'}; "
                f"assigned paper IDs: {', '.join(paper_ids) or 'none'}"
            )
            if requested:
                break
        if not summaries:
            return "No matching approved outline section is available. Use the supplied manuscript section only."
        return "\n".join(summaries)[:5000]

    @staticmethod
    def _outline_paper_ids_for_section(
        outline: Mapping[str, Any],
        section_title: str,
    ) -> tuple[str, ...]:
        requested = _clean_text(section_title, limit=300).casefold()
        for raw_section in _as_mapping(outline).get("sections", []):
            section = _as_mapping(raw_section)
            if _clean_text(section.get("title"), limit=300).casefold() == requested:
                return SurveyVisualizer._outline_paper_ids_from_section(section)
        return ()

    @staticmethod
    def _outline_paper_ids_from_section(section: Mapping[str, Any]) -> tuple[str, ...]:
        paper_ids: list[str] = []
        for raw_unit in [section, *section.get("subsections", [])]:
            unit = _as_mapping(raw_unit)
            for raw_paper_id in unit.get("papers_to_use", []):
                paper_id = _clean_text(raw_paper_id, limit=100)
                if paper_id and paper_id not in paper_ids:
                    paper_ids.append(paper_id)
        return tuple(paper_ids)

    def _validated_relations(
        self,
        raw_relations: Any,
        candidate: VisualCandidate,
        section: MarkdownSection,
        evidence_plan: Mapping[str, Any],
        outline: Mapping[str, Any],
        claim_traceability: Mapping[str, Any],
        reference_ids: Sequence[str] = (),
        rejection_reasons: list[str] | None = None,
    ) -> tuple[VisualRelation, ...]:
        """Accept only relations anchored by an exact source quote and derive their role."""

        def reject(reason: str) -> None:
            if rejection_reasons is not None:
                rejection_reasons.append(reason)

        if not isinstance(raw_relations, Sequence) or isinstance(raw_relations, (str, bytes)):
            reject("relations is not an array")
            return ()
        source_index_set = set(candidate.source_paragraph_indices)
        result: list[VisualRelation] = []
        seen: set[tuple[str, int]] = set()
        for raw_relation in raw_relations[:8]:
            item = _as_mapping(raw_relation)
            relation_en = _english_text(item.get("relation_en"), limit=600)
            source_quote = _clean_text(
                item.get("source_quote", item.get("source_quote_en", "")),
                limit=1000,
            )
            try:
                paragraph_index = int(item.get("source_paragraph_index"))
            except (TypeError, ValueError):
                reject("invalid source_paragraph_index")
                continue
            if not relation_en:
                reject("relation_en is missing or non-English")
            if not source_quote:
                reject("source_quote is missing")
            if paragraph_index not in source_index_set:
                reject(f"source_paragraph_index {paragraph_index} is outside candidate paragraphs")
            if not relation_en or not source_quote or paragraph_index not in source_index_set:
                continue
            paragraph = section.paragraphs[paragraph_index - 1].text
            if not self._quote_is_grounded(source_quote, paragraph):
                reject(f"source_quote is not grounded in paragraph {paragraph_index}")
                continue
            key = (relation_en.casefold(), paragraph_index)
            if key in seen:
                continue
            seen.add(key)
            visible_paper_ids = tuple(sorted(set(_PAPER_ID_PATTERN.findall(paragraph))))
            numbered_paper_ids = _numbered_reference_ids(paragraph, reference_ids)
            numbered_indices = [int(index) for index in _NUMBERED_CITATION_PATTERN.findall(paragraph)]
            if reference_ids and numbered_indices and any(
                index < 1 or index > len(reference_ids) for index in numbered_indices
            ):
                # Do not let an out-of-range reader-visible citation fall back
                # to an unrelated outline paper during visual auditing.
                reject(f"numbered citation is outside supplied references in paragraph {paragraph_index}")
                continue
            audited_paper_ids = visible_paper_ids or numbered_paper_ids
            if reference_ids and visible_paper_ids:
                reference_id_set = set(reference_ids)
                audited_paper_ids = tuple(
                    paper_id for paper_id in visible_paper_ids if paper_id in reference_id_set
                )
                if len(audited_paper_ids) != len(visible_paper_ids):
                    # A citation visible in the survey but absent from the
                    # independently supplied references is not allowed to
                    # authorize a visual evidence path.
                    reject(f"visible paper ID is absent from supplied references in paragraph {paragraph_index}")
                    continue
            outline_paper_ids = self._outline_paper_ids_for_section(outline, section.title)
            evidence_paths = self._derive_evidence_paths(
                source_text=paragraph,
                source_quote=source_quote,
                paper_ids=audited_paper_ids or outline_paper_ids,
                evidence_plan=evidence_plan,
                claim_traceability=claim_traceability,
            )
            requires_anchor = bool(_read(self.settings, "require_evidence_anchor", True))
            allow_unsupported = bool(_read(self.settings, "allow_unsupported_claims", False))
            if not evidence_paths and (requires_anchor or not allow_unsupported):
                reject(f"no evidence path for grounded relation in paragraph {paragraph_index}")
                continue
            support_kind = self._conservative_support_kind(
                {path.support_kind for path in evidence_paths}
            ) if evidence_paths else "BACKGROUND_CONTEXT"
            evidence_paper_ids = tuple(sorted({path.paper_id for path in evidence_paths if path.paper_id})) or audited_paper_ids
            result.append(
                VisualRelation(
                    relation_en=relation_en,
                    source_paragraph_index=paragraph_index,
                    source_quote=source_quote,
                    support_kind=support_kind,
                    evidence_paper_ids=evidence_paper_ids,
                    evidence_paths=evidence_paths,
                )
            )
            if len(result) >= 6:
                break
        return tuple(result)

    @staticmethod
    def _normalise_for_grounding(value: Any) -> str:
        text = unicodedata.normalize("NFKC", str(value or ""))
        text = text.translate(str.maketrans({
            "\u2018": "'",
            "\u2019": "'",
            "\u201c": '"',
            "\u201d": '"',
            "\u2013": "-",
            "\u2014": "-",
            "\u2212": "-",
        }))
        return re.sub(r"\s+", " ", text).strip().casefold()

    @staticmethod
    def _grounding_sentences(value: Any) -> tuple[str, ...]:
        text = SurveyVisualizer._normalise_for_grounding(value)
        return tuple(
            sentence.strip()
            for sentence in re.split(r"(?<=[.!?。！？；;])\s*", text)
            if sentence.strip()
        )

    @staticmethod
    def _quote_is_grounded(source_quote: str, paragraph: str) -> bool:
        """Match exact text, or a whole source sentence after punctuation normalization."""

        quote = SurveyVisualizer._normalise_for_grounding(source_quote)
        source = SurveyVisualizer._normalise_for_grounding(paragraph)
        if not quote or not source:
            return False
        if quote in source:
            return True

        for quote_sentence in SurveyVisualizer._grounding_sentences(source_quote):
            compact_sentence = re.sub(r"[^\w\s]", "", quote_sentence)
            if not compact_sentence:
                continue
            for source_sentence in SurveyVisualizer._grounding_sentences(paragraph):
                compact_source_sentence = re.sub(r"[^\w\s]", "", source_sentence)
                if compact_sentence == compact_source_sentence:
                    return True
        return False

    def _derive_evidence_paths(
        self,
        *,
        source_text: str,
        source_quote: str,
        paper_ids: Sequence[str],
        evidence_plan: Mapping[str, Any],
        claim_traceability: Mapping[str, Any],
    ) -> tuple[VisualEvidencePath, ...]:
        """Resolve exact SH/slot/paper paths before a relation reaches image prompting."""

        trace_paths = self._trace_evidence_paths(source_text, source_quote, claim_traceability)
        if trace_paths:
            return trace_paths
        plan_paths = self._evidence_paths_by_paper(evidence_plan)
        return self._dedupe_evidence_paths(
            path
            for paper_id in paper_ids
            for path in plan_paths.get(paper_id, ())
        )

    @staticmethod
    def _conservative_support_kind(support_kinds: Sequence[str] | set[str]) -> str:
        kinds = {str(kind or "").strip() for kind in support_kinds}
        if kinds == {"DIRECT_LEDGER_EVIDENCE"}:
            return "DIRECT_LEDGER_EVIDENCE"
        if "QUALIFIED_SH_CONTRIBUTION" in kinds:
            return "QUALIFIED_SH_CONTRIBUTION"
        return "BACKGROUND_CONTEXT"

    @staticmethod
    def _trace_evidence_paths(
        source_text: str,
        source_quote: str,
        claim_traceability: Mapping[str, Any],
    ) -> tuple[VisualEvidencePath, ...]:
        source_normalized = SurveyVisualizer._normalise_for_grounding(source_text)
        quote_normalized = SurveyVisualizer._normalise_for_grounding(source_quote)
        paths: list[VisualEvidencePath] = []
        claims = _as_mapping(claim_traceability).get("claims", [])
        if not isinstance(claims, Sequence) or isinstance(claims, (str, bytes)):
            return ()
        for raw_claim in claims:
            claim = _as_mapping(raw_claim)
            claim_text = SurveyVisualizer._normalise_for_grounding(claim.get("claim_text"))
            if not claim_text or (claim_text not in source_normalized and claim_text not in quote_normalized):
                continue
            for raw_path in claim.get("evidence_paths", []):
                item = _as_mapping(raw_path)
                support_kind = _clean_text(item.get("support_kind"), limit=100)
                if support_kind not in {
                    "DIRECT_LEDGER_EVIDENCE",
                    "QUALIFIED_SH_CONTRIBUTION",
                    "BACKGROUND_CONTEXT",
                }:
                    continue
                paths.append(
                    VisualEvidencePath(
                        sub_hypothesis_id=_clean_text(item.get("sub_hypothesis_id"), limit=100),
                        slot_name=_clean_text(item.get("slot_name"), limit=160),
                        paper_id=canonical_paper_id(_clean_text(item.get("paper_id"), limit=100)),
                        support_kind=support_kind,
                    )
                )
        return SurveyVisualizer._dedupe_evidence_paths(paths)

    @staticmethod
    def _evidence_paths_by_paper(
        evidence_plan: Mapping[str, Any],
    ) -> dict[str, tuple[VisualEvidencePath, ...]]:
        paths: dict[str, list[VisualEvidencePath]] = {}

        def register(ids: Any, role: str, *, sh_id: str, slot_name: str) -> None:
            for paper_id in ids if isinstance(ids, Sequence) and not isinstance(ids, (str, bytes)) else [ids]:
                canonical = canonical_paper_id(_clean_text(paper_id, limit=100))
                if canonical:
                    paths.setdefault(canonical, []).append(
                        VisualEvidencePath(
                            sub_hypothesis_id=sh_id,
                            slot_name=slot_name,
                            paper_id=canonical,
                            support_kind=role,
                        )
                    )

        for raw_entry in _as_mapping(evidence_plan).get("subhypotheses", []):
            entry = _as_mapping(raw_entry)
            sh_id = _clean_text(entry.get("sub_hypothesis_id"), limit=100)
            register(entry.get("evidence_paper_ids", []), "DIRECT_LEDGER_EVIDENCE", sh_id=sh_id, slot_name="")
            register(entry.get("qualified_paper_ids", []), "QUALIFIED_SH_CONTRIBUTION", sh_id=sh_id, slot_name="")
            register(entry.get("context_paper_ids", []), "BACKGROUND_CONTEXT", sh_id=sh_id, slot_name="")
            for slot_name, raw_slot in _as_mapping(entry.get("slot_support", {})).items():
                slot = _as_mapping(raw_slot)
                register(slot.get("evidence_paper_ids", []), "DIRECT_LEDGER_EVIDENCE", sh_id=sh_id, slot_name=str(slot_name))
                register(slot.get("qualified_paper_ids", []), "QUALIFIED_SH_CONTRIBUTION", sh_id=sh_id, slot_name=str(slot_name))
                register(slot.get("background_paper_ids", []), "BACKGROUND_CONTEXT", sh_id=sh_id, slot_name=str(slot_name))
        return {paper_id: SurveyVisualizer._dedupe_evidence_paths(entries) for paper_id, entries in paths.items()}

    @staticmethod
    def _dedupe_evidence_paths(paths: Sequence[VisualEvidencePath] | Any) -> tuple[VisualEvidencePath, ...]:
        unique: list[VisualEvidencePath] = []
        seen: set[tuple[str, str, str, str]] = set()
        for path in paths:
            if not isinstance(path, VisualEvidencePath):
                continue
            key = (path.sub_hypothesis_id, path.slot_name, path.paper_id, path.support_kind)
            if key not in seen:
                seen.add(key)
                unique.append(path)
        return tuple(unique)

    @staticmethod
    def _evidence_context(
        evidence_plan: Mapping[str, Any],
        *,
        include_gaps: bool,
    ) -> str:
        plan = _as_mapping(evidence_plan)
        entries = plan.get("subhypotheses", [])
        summaries: list[str] = []
        if isinstance(entries, Sequence) and not isinstance(entries, (str, bytes)):
            for entry in entries[:20]:
                item = _as_mapping(entry)
                sh_id = _clean_text(item.get("sub_hypothesis_id"), limit=80)
                mode = _clean_text(item.get("allowed_writing_mode"), limit=100)
                missing = ", ".join(_clean_text(slot, limit=100) for slot in item.get("missing_slots", [])[:6])
                summaries.append(
                    f"{sh_id or 'SH'}: allowed mode={mode or 'unspecified'}; "
                    f"explicit gaps={missing or 'none recorded' if include_gaps else 'suppressed'}"
                )
        base = (
            "Only the supplied section paragraphs provide visualisable scientific facts. "
            "Direct evidence may use solid primary pathways; qualified, background, and gap "
            "content must remain visually qualified."
        )
        return base + ("\n" + "\n".join(summaries) if summaries else "")

    def _request_json(self, prompt: str, *, max_output_tokens: int) -> Any:
        raw = self.chat_agent.remote_chat(
            prompt,
            temperature=float(_read(self.settings, "planner_temperature", 0.2) or 0.2),
            max_output_tokens=max_output_tokens,
            response_format="json_object",
        )
        return extract_json(raw)

    @staticmethod
    def _insert_markdown(
        survey: str,
        sections: Sequence[MarkdownSection],
        assets: Sequence[FigureAsset],
    ) -> str:
        section_map = {section.index: section for section in sections}
        inserts: list[tuple[int, str]] = []
        for asset in assets:
            brief = asset.brief
            section = section_map[brief.section_index]
            paragraph = section.paragraphs[brief.insert_after_paragraph - 1]
            block = (
                f"\n\n<!-- FIGURE: {brief.figure_id}; section={brief.section_index}; "
                f"paragraphs={','.join(str(index) for index in brief.source_paragraph_indices)} -->\n\n"
                f"![{brief.alt_text_en}]({asset.file_name})\n\n"
                f"*{brief.caption_en}*\n"
            )
            inserts.append((paragraph.end, block))
        result = survey
        for position, block in sorted(inserts, key=lambda item: item[0], reverse=True):
            result = result[:position] + block + result[position:]
        return result

    @staticmethod
    def _build_manifest(
        *,
        survey_path: Path,
        visual_path: Path,
        style: VisualStyleProfile,
        assets: Sequence[FigureAsset],
        status: str,
        reason: str,
        outline: Mapping[str, Any],
        evidence_plan: Mapping[str, Any],
        skipped_figures: Sequence[Mapping[str, str]],
        reference_ids: Sequence[str] = (),
        rejected_figures: Sequence[Mapping[str, Any]] = (),
    ) -> dict[str, Any]:
        return {
            "schema_version": "survey_visual_manifest_v1",
            "status": status,
            "reason": reason,
            "source_survey": survey_path.name,
            "visual_survey": visual_path.name,
            "image_directory": ".",
            "reader_facing_language": "en",
            "captions_language": "en",
            "alt_text_language": "en",
            "outline_used": bool(_as_mapping(outline)),
            "references_received": bool(reference_ids),
            "reference_ids": list(reference_ids),
            "reference_count": len(reference_ids),
            "evidence_plan_schema_version": _clean_text(
                _as_mapping(evidence_plan).get("schema_version"), limit=120
            ),
            "style_profile": asdict(style),
            "rejected_figures": [dict(item) for item in rejected_figures],
            "skipped_figures": [dict(item) for item in skipped_figures],
            "figures": [
                {
                    "figure_id": asset.brief.figure_id,
                    "file": asset.file_name,
                    "figure_type": asset.brief.figure_type,
                    "source_section_index": asset.brief.section_index,
                    "source_section_title": asset.brief.section_title,
                    "source_paragraph_indices": list(asset.brief.source_paragraph_indices),
                    "insert_after_paragraph": asset.brief.insert_after_paragraph,
                    "source_paper_ids": list(asset.brief.source_paper_ids),
                    "relations": [asdict(relation) for relation in asset.brief.relations],
                    "caption_en": asset.brief.caption_en,
                    "alt_text_en": asset.brief.alt_text_en,
                    "allowed_overlay_labels_en": list(asset.brief.allowed_overlay_labels_en),
                    "model": asset.model,
                    "provider": asset.provider,
                    "quality_status": asset.quality_status,
                    "generation_attempts": asset.generation_attempts,
                    "qc_notes": asset.qc_notes,
                    "revised_prompt": asset.revised_prompt,
                    "prompt": asset.prompt,
                }
                for asset in assets
            ],
        }
