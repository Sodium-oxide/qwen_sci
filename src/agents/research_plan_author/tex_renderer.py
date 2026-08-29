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
from .latex_safety import LatexSafetyError, escape_latex_text, require_english_visible_text, safe_math_expression
from .template_adapter import MaterializedTemplate, TemplateAdapter, TemplateAdapterError
from .template_profile import TemplateProfile


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
    fragments = [fragment.strip() for fragment in re.split(r"\n\s*\n", text) if fragment.strip()]
    if not fragments:
        return ""
    return "\n\n".join(escape_latex_text(fragment, label=label).replace("\n", " ") for fragment in fragments)


def _list_items(text: str, *, label: str) -> list[str]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    items = [re.sub(r"^(?:[-*+]|\d+[.)])\s*", "", line).strip() for line in lines]
    return [escape_latex_text(item, label=label) for item in items if item]


def _render_table(text: str, *, label: str) -> str:
    rows: list[list[str]] = []
    for line in (line.strip() for line in text.splitlines() if line.strip()):
        stripped = line.strip("|")
        cells = [cell.strip() for cell in (stripped.split("|") if "|" in stripped else stripped.split("\t"))]
        if len(cells) >= 2 and any(cells):
            rows.append(cells)
    if not rows or len(rows) > 40:
        return "\\begin{quote}\\small " + _paragraphs(text, label=label) + " \\end{quote}"
    width = max(len(row) for row in rows)
    if width > 6:
        return "\\begin{quote}\\small " + _paragraphs(text, label=label) + " \\end{quote}"
    normalized = [row + [""] * (width - len(row)) for row in rows]
    rendered_rows = [
        " & ".join(escape_latex_text(cell, label=label) for cell in row) + r" \\\hline"
        for row in normalized
    ]
    return "\n".join(
        [
            "\\begin{table}[htbp]",
            "\\centering",
            "\\small",
            "\\begin{tabular}{|" + "|".join("p{0.14\\linewidth}" for _ in range(width)) + "|}",
            "\\hline",
            *rendered_rows,
            "\\end{tabular}",
            "\\end{table}",
        ]
    )


def _render_block(block: Mapping[str, Any], *, claims: Mapping[str, Mapping[str, Any]]) -> str:
    kind = _text(block.get("kind"))
    text = require_english_visible_text(block.get("text"), label=f"block {block.get('block_id') or kind}")
    citations = _citation_suffix(_block_citations(block, claims))
    label = f"block {block.get('block_id') or kind}"
    if kind == "equation":
        return "\\[\n" + safe_math_expression(text, label=label) + "\n\\]" + citations
    if kind == "list":
        items = _list_items(text, label=label)
        if not items:
            return ""
        return "\\begin{itemize}\n" + "\n".join(f"\\item {item}" for item in items) + "\n\\end{itemize}" + citations
    if kind == "table":
        return _render_table(text, label=label) + citations
    paragraph = _paragraphs(text, label=label)
    if kind == "definition":
        return "\\paragraph{Definition.} " + paragraph + citations
    if kind == "proposition":
        return "\\paragraph{Proposition (proposed).} " + paragraph + citations
    if kind == "protocol":
        return "\\paragraph{Planned protocol.} " + paragraph + citations
    if kind == "outcome_branch":
        return "\\paragraph{Conditional outcome branch.} " + paragraph + citations
    if kind == "review_checklist":
        return "\\paragraph{Human-review checklist.} " + paragraph + citations
    return paragraph + citations


def _render_section(section: Mapping[str, Any], *, claims: Mapping[str, Mapping[str, Any]], appendix: bool) -> str:
    title = escape_latex_text(section.get("title"), label=f"section {section.get('section_id')} title")
    heading = "\\section" if appendix else "\\section"
    blocks = [_render_block(_mapping(block), claims=claims) for block in section.get("blocks") or [] if isinstance(block, Mapping)]
    blocks = [block for block in blocks if block]
    if _text(section.get("applicability")) == "not_applicable":
        blocks.insert(0, "\\emph{Not applicable to this proposal.}")
    if not blocks:
        blocks.append("\\emph{No additional prose is available for this source-bounded proposal section.}")
    return heading + "{" + title + "}\n" + "\n\n".join(blocks)


def _render_body(document: Mapping[str, Any], *, profile: TemplateProfile) -> str:
    claims = _claim_map(document)
    sections = [
        _render_section(_mapping(section), claims=claims, appendix=False)
        for section in document.get("sections") or []
        if isinstance(section, Mapping) and _text(section.get("section_id")) != "references"
    ]
    appendices = [
        _render_section(_mapping(section), claims=claims, appendix=True)
        for section in document.get("appendices") or []
        if isinstance(section, Mapping)
    ]
    if appendices:
        appendix_command = "\\appendices" if profile.profile_id == "ieee_conference_v1" else "\\appendix"
        sections.append(appendix_command + "\n" + "\n\n".join(appendices))
    return "\n\n".join(sections)


def _render_abstract(document: Mapping[str, Any], *, profile: TemplateProfile) -> str:
    abstract = _mapping(document.get("abstract"))
    text = _paragraphs(_text(abstract.get("text")), label="abstract")
    if not text:
        raise TexRenderError("ResearchPlanDocument has no rendered abstract")
    keywords = [escape_latex_text(keyword, label="keyword") for keyword in document.get("keywords") or []]
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
    keys = ",".join(result.emitted_keys)
    database = Path(profile.generated_bib).with_suffix("").as_posix()
    return "\n".join(
        [
            "\\section*{References}",
            f"\\nocite{{{keys}}}",
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
    require_english_visible_text(metadata.get("title"), label="document title")


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
        title = escape_latex_text(_mapping(document.get("document_metadata")).get("title"), label="document title")
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
