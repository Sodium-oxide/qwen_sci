"""Render a validated English ResearchPlanDocument into a restricted TeX project."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re
import tempfile
from collections.abc import Mapping
from typing import Any

from .bibtex_renderer import BibtexRenderResult, ensure_citation_coverage, render_bibtex
from .contracts import AUTHORING_LANGUAGE, validate_research_plan_document
from .latex_safety import (
    LatexSafetyError,
    escape_latex_text,
    normalize_visible_text,
    safe_math_expression,
    split_equation_content,
)
from .template_adapter import MaterializedTemplate, TemplateAdapter, TemplateAdapterError
from .template_profile import TemplateProfile
from .theory_presentation import theory_block_presentation, theory_unit_registry, visible_theory_text


TEX_RENDER_SCHEMA_VERSION = "research_plan_author_tex_render_v1"


class TexRenderError(RuntimeError):
    """Raised when a document cannot be rendered without violating Author constraints."""


@dataclass(frozen=True)
class TexRenderResult:
    profile_id: str
    project_dir: Path
    main_tex: Path
    bibtex: Path
    bibliography: BibtexRenderResult

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": TEX_RENDER_SCHEMA_VERSION,
            "profile_id": self.profile_id,
            "project_dir": str(self.project_dir),
            "main_tex": str(self.main_tex),
            "bibtex": str(self.bibtex),
            "bibliography": self.bibliography.as_dict(),
        }


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _text(value: object) -> str:
    return str(value or "").strip()


_PRIVATE_PROVENANCE_ANCHOR = re.compile(
    r"\[?(?:survey:survey_markdown(?:#section-[A-Za-z0-9._:+-]+)?|anchor:[A-Za-z0-9_:+-]+(?:\.[A-Za-z0-9_:+-]+)*)\]?",
    re.IGNORECASE,
)

_FORBIDDEN_NONROUTE_SECTION = re.compile(
    r"\\(?:sub)*section\*?\s*\{\s*acknowledg(?:e)?ments?\s*\}",
    re.IGNORECASE,
)


def _strip_private_survey_anchors(value: object) -> str:
    """Keep Survey provenance private even if a composer leaks an anchor into prose."""

    text = str(value or "")
    cleaned = _PRIVATE_PROVENANCE_ANCHOR.sub("", text)
    return re.sub(r"[ \t]{2,}", " ", cleaned).replace(" \n", "\n").strip()


def _label_component(value: object) -> str:
    component = re.sub(r"[^A-Za-z0-9:-]+", "-", _text(value)).strip("-:")
    return component or "unnamed"


def _equation_label(section_id: object, block_id: object) -> str:
    return f"eq:{_label_component(section_id)}-{_label_component(block_id)}"


def _table_label(section_id: object, block_id: object) -> str:
    return f"tab:{_label_component(section_id)}-{_label_component(block_id)}"


def _claim_map(document: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    claims: dict[str, dict[str, Any]] = {}
    for raw in document.get("claim_provenance") or []:
        claim = _mapping(raw)
        claim_id = _text(claim.get("claim_id"))
        if claim_id:
            claims[claim_id] = claim
    return claims


def _block_citations(block: Mapping[str, Any], claims: Mapping[str, Mapping[str, Any]]) -> list[str]:
    keys: list[str] = []
    for claim_id in block.get("claim_ids") or []:
        claim = claims.get(_text(claim_id), {})
        for key in claim.get("citation_keys") or []:
            value = _text(key)
            if value and value not in keys:
                keys.append(value)
    return keys


def _citation_suffix(keys: list[str]) -> str:
    return "" if not keys else "~\\cite{" + ",".join(keys) + "}"


def _paragraphs(text: str, *, label: str) -> str:
    visible_text = _strip_private_survey_anchors(text)
    fragments = [fragment.strip() for fragment in re.split(r"\n\s*\n", visible_text) if fragment.strip()]
    if not fragments:
        return ""
    return "\n\n".join(escape_latex_text(fragment, label=label).replace("\n", " ") for fragment in fragments)


def _list_items(text: str, *, label: str) -> list[str]:
    lines = [line.strip() for line in _strip_private_survey_anchors(text).splitlines() if line.strip()]
    items = [re.sub(r"^(?:[-*+]|\d+[.)])\s*", "", line).strip() for line in lines]
    return [escape_latex_text(item, label=label) for item in items if item]


def _render_table(text: str, *, label: str, caption: str, table_label: str) -> str:
    rows: list[list[str]] = []
    for line in (line.strip() for line in _strip_private_survey_anchors(text).splitlines() if line.strip()):
        stripped = line.strip("|")
        cells = [cell.strip() for cell in (stripped.split("|") if "|" in stripped else stripped.split("\t"))]
        if len(cells) >= 2 and any(cells):
            if all(re.fullmatch(r":?-{3,}:?", cell.replace(" ", "")) for cell in cells):
                continue
            rows.append(cells)
    if not rows or len(rows) > 40:
        return "\\begin{quote}\\small " + _paragraphs(text, label=label) + " \\end{quote}"
    width = max(len(row) for row in rows)
    if width > 6:
        return "\\begin{quote}\\small " + _paragraphs(text, label=label) + " \\end{quote}"
    normalized = [row + [""] * (width - len(row)) for row in rows]
    longest_cell = max((len(cell) for row in normalized for cell in row), default=0)
    use_wide_layout = width >= 4 or longest_cell > 52
    environment = "table*" if use_wide_layout else "table"
    available_width = r"\textwidth" if use_wide_layout else r"\linewidth"
    if use_wide_layout:
        column_width = f"{0.92 / width:.4f}".rstrip("0").rstrip(".")
    else:
        column_width = "0.45" if width == 2 else "0.29"
    rendered_rows = [
        " & ".join(escape_latex_text(cell, label=label) for cell in row) + r" \\\hline"
        for row in normalized
    ]
    return "\n".join(
        [
            "\\begin{" + environment + "}[htbp]",
            "\\centering",
            "\\footnotesize" if use_wide_layout else "\\small",
            "\\setlength{\\tabcolsep}{3pt}" if use_wide_layout else "",
            "\\renewcommand{\\arraystretch}{1.12}" if use_wide_layout else "",
            "\\caption{" + escape_latex_text(caption, label=f"{label} caption") + "}",
            "\\label{" + table_label + "}",
            "\\begin{tabular}{|" + "|".join(
                f"p{{{column_width}{available_width}}}" for _ in range(width)
            ) + "|}",
            "\\hline",
            *rendered_rows,
            "\\end{tabular}",
            "\\end{" + environment + "}",
        ]
    )


def _equation_cross_references(
    block: Mapping[str, Any],
    *,
    equation_labels: Mapping[str, str],
) -> str:
    labels = [
        equation_labels[reference_id]
        for raw_reference_id in block.get("reference_block_ids") or []
        if (reference_id := _text(raw_reference_id)) in equation_labels
    ]
    if not labels:
        return ""
    rendered = ", ".join("Eq.~\\eqref{" + label + "}" for label in labels)
    return " See " + rendered + "."


def _render_math_expression(expression: str, *, equation_label: str | None) -> str:
    lines = [line.strip() for line in expression.split(r"\\")]
    if len(lines) == 1:
        if equation_label:
            return "\\begin{equation}\n" + expression + "\n\\label{" + equation_label + "}\n\\end{equation}"
        return "\\begin{equation*}\n" + expression + "\n\\end{equation*}"
    if not all(lines):
        raise LatexSafetyError("equation has an empty align row")
    rendered_lines = [
        line
        + (
            r" \nonumber \\"
            if index < len(lines) - 1
            else (r" \label{" + equation_label + "}" if equation_label else "")
        )
        for index, line in enumerate(lines)
    ]
    environment = "align" if equation_label else "align*"
    return "\\begin{" + environment + "}\n" + "\n".join(rendered_lines) + "\n\\end{" + environment + "}"


def _render_equation(text: str, *, label: str, equation_label: str) -> str:
    fragments = split_equation_content(_strip_private_survey_anchors(text), label=label)
    rendered: list[str] = []
    labeled_expression = False
    for kind, fragment in fragments:
        if kind == "prose":
            prose = _paragraphs(fragment, label=label)
            if prose:
                rendered.append(prose)
            continue
        rendered.append(
            _render_math_expression(
                safe_math_expression(fragment, label=label),
                equation_label=equation_label if not labeled_expression else None,
            )
        )
        labeled_expression = True
    if not labeled_expression:
        raise LatexSafetyError(f"{label} contains no valid mathematical expression")
    return "\n\n".join(rendered)


def _render_block(
    block: Mapping[str, Any],
    *,
    claims: Mapping[str, Mapping[str, Any]],
    document: Mapping[str, Any],
    theory_registry: Mapping[str, Mapping[str, Any]],
    section_id: str,
    equation_labels: Mapping[str, str],
) -> str:
    kind = _text(block.get("kind"))
    text = normalize_visible_text(
        _strip_private_survey_anchors(visible_theory_text(document, block.get("text"))),
        label=f"block {block.get('block_id') or kind}",
    )
    citations = _citation_suffix(_block_citations(block, claims))
    label = f"block {block.get('block_id') or kind}"
    heading_text = _strip_private_survey_anchors(visible_theory_text(document, block.get("heading")))
    heading = "" if not heading_text else "\\subsection{" + escape_latex_text(heading_text, label=f"{label} heading") + "}\n"
    cross_references = _equation_cross_references(block, equation_labels=equation_labels)
    theory_prefix, theory_status = theory_block_presentation(
        block,
        claims=claims,
        registry=theory_registry,
    )
    if kind == "equation":
        equation_label = _equation_label(section_id, block.get("block_id"))
        return heading + _render_equation(text, label=label, equation_label=equation_label) + citations
    if kind == "list":
        items = _list_items(text, label=label)
        if not items:
            return ""
        return heading + "\\begin{itemize}\n" + "\n".join(f"\\item {item}" for item in items) + "\n\\end{itemize}" + citations
    if kind == "table":
        caption = heading_text or theory_prefix.rstrip(".") or (
            f"Decision matrix ({theory_status})" if theory_status else "Decision matrix"
        )
        return _render_table(
            text,
            label=label,
            caption=caption,
            table_label=_table_label(section_id, block.get("block_id")),
        ) + cross_references + citations
    paragraph = _paragraphs(text, label=label)
    if theory_prefix:
        return heading + "\\paragraph{" + escape_latex_text(theory_prefix, label=f"{label} theory presentation") + "} " + paragraph + cross_references + citations
    if kind == "definition":
        return heading + "\\paragraph{Definition.} " + paragraph + cross_references + citations
    if kind == "proposition":
        return heading + "\\paragraph{Proposition (proposed).} " + paragraph + cross_references + citations
    if kind == "protocol":
        return heading + "\\paragraph{Planned protocol.} " + paragraph + cross_references + citations
    if kind == "outcome_branch":
        return heading + "\\paragraph{Conditional outcome branch.} " + paragraph + cross_references + citations
    if kind == "review_checklist":
        return heading + "\\paragraph{Human-review checklist.} " + paragraph + cross_references + citations
    return heading + paragraph + cross_references + citations


def _render_section(
    section: Mapping[str, Any],
    *,
    claims: Mapping[str, Mapping[str, Any]],
    document: Mapping[str, Any],
    theory_registry: Mapping[str, Mapping[str, Any]],
    document_equation_labels: Mapping[str, str],
    appendix: bool,
) -> str:
    section_id = _text(section.get("section_id"))
    title = escape_latex_text(
        _strip_private_survey_anchors(visible_theory_text(document, section.get("title"))),
        label=f"section {section_id} title",
    )
    heading = "\\section" if appendix else "\\section"
    equation_labels = {
        _text(block.get("block_id")): _equation_label(section_id, block.get("block_id"))
        for block in section.get("blocks") or []
        if isinstance(block, Mapping) and _text(block.get("kind")) == "equation"
    }
    equation_labels = {**document_equation_labels, **equation_labels}
    blocks = [
        _render_block(
            _mapping(block),
            claims=claims,
            document=document,
            theory_registry=theory_registry,
            section_id=section_id,
            equation_labels=equation_labels,
        )
        for block in section.get("blocks") or []
        if isinstance(block, Mapping)
    ]
    blocks = [block for block in blocks if block]
    if _text(section.get("applicability")) == "not_applicable":
        blocks.insert(0, "\\emph{Not applicable to this proposal.}")
    if not blocks:
        blocks.append("\\emph{No additional prose is available for this source-bounded proposal section.}")
    return heading + "{" + title + "}\n" + "\n\n".join(blocks)


def _render_body(document: Mapping[str, Any], *, profile: TemplateProfile) -> str:
    claims = _claim_map(document)
    theory_registry = theory_unit_registry(document)
    document_equation_labels = {
        f"{_text(section.get('section_id'))}:{_text(block.get('block_id'))}": _equation_label(
            section.get("section_id"),
            block.get("block_id"),
        )
        for section in [*(document.get("sections") or []), *(document.get("appendices") or [])]
        if isinstance(section, Mapping)
        for block in section.get("blocks") or []
        if isinstance(block, Mapping)
        and _text(section.get("section_id"))
        and _text(block.get("block_id"))
        and _text(block.get("kind")) == "equation"
    }
    sections = [
        _render_section(
            _mapping(section),
            claims=claims,
            document=document,
            theory_registry=theory_registry,
            document_equation_labels=document_equation_labels,
            appendix=False,
        )
        for section in document.get("sections") or []
        if isinstance(section, Mapping) and _text(section.get("section_id")) != "references"
    ]
    appendices = [
        _render_section(
            _mapping(section),
            claims=claims,
            document=document,
            theory_registry=theory_registry,
            document_equation_labels=document_equation_labels,
            appendix=True,
        )
        for section in document.get("appendices") or []
        if isinstance(section, Mapping)
    ]
    if appendices:
        appendix_command = "\\appendices" if profile.profile_id == "ieee_conference_v1" else "\\appendix"
        sections.append(appendix_command + "\n" + "\n\n".join(appendices))
    return "\n\n".join(sections)


def _render_abstract(document: Mapping[str, Any], *, profile: TemplateProfile) -> str:
    abstract = _mapping(document.get("abstract"))
    text = _paragraphs(
        _strip_private_survey_anchors(visible_theory_text(document, abstract.get("text"))),
        label="abstract",
    )
    if not text:
        raise TexRenderError("ResearchPlanDocument has no rendered abstract")
    keywords = [
        escape_latex_text(_strip_private_survey_anchors(visible_theory_text(document, keyword)), label="keyword")
        for keyword in document.get("keywords") or []
    ]
    lines = ["\\begin{abstract}", text, "\\end{abstract}"]
    if keywords and profile.profile_id == "ieee_conference_v1":
        lines.extend(["\\begin{IEEEkeywords}", ", ".join(keywords), "\\end{IEEEkeywords}"])
    elif keywords:
        lines.append("\\paragraph{Keywords.} " + ", ".join(keywords))
    return "\n".join(lines)


def _render_bibliography(result: BibtexRenderResult, *, profile: TemplateProfile) -> str:
    if not result.emitted_keys:
        return (
            "\\section*{References}\n"
            "\\emph{No provenance-backed bibliographic records are available for rendering; see the bibliography completion ledger.}"
        )
    database = Path(profile.generated_bib).with_suffix("").as_posix()
    return "\n".join(
        [
            "\\section*{References}",
            f"\\bibliographystyle{{{profile.bibliography_style}}}",
            f"\\bibliography{{{database}}}",
        ]
    )


def _write_text_atomically(path: Path, content: str) -> None:
    temporary: Path | None = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, raw_path = tempfile.mkstemp(
            prefix=f".{path.name}.", suffix=".tmp", dir=path.parent, text=True
        )
        temporary = Path(raw_path)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except OSError as error:
        raise TexRenderError(f"cannot write generated file '{path.name}': {error}") from error
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _validate_document(document: Mapping[str, Any]) -> None:
    errors = validate_research_plan_document(document)
    if errors:
        raise TexRenderError("ResearchPlanDocument schema validation failed: " + "; ".join(errors))
    if document.get("language") != AUTHORING_LANGUAGE:
        raise TexRenderError("ResearchPlanDocument language must be English")
    if document.get("document_status") != "PROPOSAL_NO_OBSERVED_RESULTS":
        raise TexRenderError("only PROPOSAL_NO_OBSERVED_RESULTS documents may be rendered")
    metadata = _mapping(document.get("document_metadata"))
    normalize_visible_text(metadata.get("title"), label="document title")


def render_tex_project(
    document: Mapping[str, Any],
    *,
    template_dir: str | Path,
    project_dir: str | Path,
    profile: TemplateProfile,
    author_name: str = "Anonymous Research Plan Author",
) -> TexRenderResult:
    """Copy a declared template and render one source-bounded TeX project."""

    try:
        _validate_document(document)
        bibliography = render_bibtex(document)
        ensure_citation_coverage(document, bibliography)
        title = escape_latex_text(
            visible_theory_text(document, _mapping(document.get("document_metadata")).get("title")),
            label="document title",
        )
        author = escape_latex_text(author_name, label="author name")
        abstract = _render_abstract(document, profile=profile)
        body = _render_body(document, profile=profile)
        bibliography_fragment = _render_bibliography(bibliography, profile=profile)
    except (LatexSafetyError, TemplateAdapterError) as error:
        raise TexRenderError(str(error)) from error
    adapter = TemplateAdapter()
    try:
        materialized: MaterializedTemplate = adapter.materialize(template_dir, project_dir, profile)
        _write_text_atomically(materialized.generated_bib, bibliography.content)
        main_tex = adapter.apply(
            materialized,
            profile,
            {
                "title": "\\title{" + title + "}",
                "author": "\\author{" + author + "}",
                "abstract": abstract,
                "body": body,
                "bibliography": bibliography_fragment,
            },
        )
        rendered_tex = main_tex.read_text(encoding="utf-8")
        if _FORBIDDEN_NONROUTE_SECTION.search(rendered_tex):
            raise TexRenderError(
                "rendered report contains an Acknowledgment section outside the four-agent route"
            )
    except (TemplateAdapterError, LatexSafetyError) as error:
        raise TexRenderError(str(error)) from error
    return TexRenderResult(
        profile_id=profile.profile_id,
        project_dir=materialized.project_dir,
        main_tex=main_tex,
        bibtex=materialized.generated_bib,
        bibliography=bibliography,
    )


__all__ = ["TEX_RENDER_SCHEMA_VERSION", "TexRenderError", "TexRenderResult", "render_tex_project"]
