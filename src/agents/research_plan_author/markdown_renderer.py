"""Deterministic Markdown views of structured Research Plan documents."""

from __future__ import annotations

from collections.abc import Mapping
import re
from typing import Any

from .theory_presentation import theory_block_presentation, theory_unit_registry, visible_theory_text


_PRIVATE_PROVENANCE = re.compile(
    r"\[?(?:survey:survey_markdown(?:#section-[A-Za-z0-9._:+-]+)?|anchor:[A-Za-z0-9_:+-]+(?:\.[A-Za-z0-9_:+-]+)*)\]?",
    flags=re.IGNORECASE,
)


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _text(value: object) -> str:
    return str(value or "").strip()


def _visible(value: object) -> str:
    return _PRIVATE_PROVENANCE.sub("", _text(value)).strip()


def _visible_for_document(document: Mapping[str, Any], value: object) -> str:
    return _visible(visible_theory_text(document, value))


def _label_component(value: object) -> str:
    component = re.sub(r"[^A-Za-z0-9:-]+", "-", _text(value)).strip("-:")
    return component or "unnamed"


def _equation_label(section_id: object, block_id: object) -> str:
    return f"eq:{_label_component(section_id)}-{_label_component(block_id)}"


def _document_equation_labels(document: Mapping[str, Any]) -> dict[str, str]:
    labels: dict[str, str] = {}
    for section in [*(document.get("sections") or []), *(document.get("appendices") or [])]:
        if not isinstance(section, Mapping):
            continue
        section_id = _text(section.get("section_id"))
        for block in section.get("blocks") or []:
            if isinstance(block, Mapping) and _text(block.get("kind")) == "equation":
                block_id = _text(block.get("block_id"))
                if section_id and block_id:
                    labels[f"{section_id}:{block_id}"] = _equation_label(section_id, block_id)
    return labels


def _equation_cross_references(block: Mapping[str, Any], *, equation_labels: Mapping[str, str]) -> str:
    labels = [
        equation_labels[reference_id]
        for raw_reference_id in block.get("reference_block_ids") or []
        if (reference_id := _text(raw_reference_id)) in equation_labels
    ]
    return "" if not labels else " See Eq. (" + ", ".join(labels) + ")."


def _claim_map(document: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    return {
        _text(claim.get("claim_id")): claim
        for claim in document.get("claim_provenance") or []
        if isinstance(claim, Mapping) and _text(claim.get("claim_id"))
    }


def _citation_suffix(block: Mapping[str, Any], claims: Mapping[str, Mapping[str, Any]]) -> str:
    keys: list[str] = []
    for claim_id in block.get("claim_ids") or []:
        claim = claims.get(_text(claim_id))
        if not isinstance(claim, Mapping):
            continue
        for citation_key in claim.get("citation_keys") or []:
            normalized = _text(citation_key)
            if normalized and normalized not in keys:
                keys.append(normalized)
    return " " + " ".join(f"[@{key}]" for key in keys) if keys else ""


def _block_markdown(
    block: Mapping[str, Any],
    *,
    claims: Mapping[str, Mapping[str, Any]],
    evaluation_markers: bool,
    section_id: str,
    document: Mapping[str, Any],
    theory_registry: Mapping[str, Mapping[str, Any]],
    equation_labels: Mapping[str, str],
) -> str:
    block_id = _text(block.get("block_id"))
    marker = f"<!-- author:section={section_id} block={block_id} -->\n" if evaluation_markers else ""
    heading = _visible_for_document(document, block.get("heading"))
    kind = _text(block.get("kind"))
    text = _visible_for_document(document, block.get("text"))
    if not text:
        return ""
    prefix = f"### {heading}\n\n" if heading else ""
    suffix = _citation_suffix(block, claims)
    theory_prefix, _status = theory_block_presentation(
        block,
        claims=claims,
        registry=theory_registry,
    )
    cross_references = _equation_cross_references(block, equation_labels=equation_labels)
    if kind == "equation":
        equation_label = equation_labels.get(_text(block.get("block_id")), "")
        equation_prefix = f"**Equation [{equation_label}].**\n\n" if equation_label else ""
        return marker + prefix + equation_prefix + "$$\n" + text + "\n$$" + suffix
    if kind == "table" and theory_prefix:
        return marker + prefix + f"**{theory_prefix}**\n\n" + text + cross_references + suffix
    if theory_prefix:
        return marker + prefix + f"**{theory_prefix}** " + text + cross_references + suffix
    if kind == "definition":
        return marker + prefix + "**Definition.** " + text + cross_references + suffix
    if kind == "proposition":
        return marker + prefix + "**Proposition (Candidate).** " + text + cross_references + suffix
    if kind == "protocol":
        return marker + prefix + "**Planned protocol.** " + text + cross_references + suffix
    if kind == "outcome_branch":
        return marker + prefix + "**Pre-registered Branch (Expected---Not Observed).** " + text + cross_references + suffix
    if kind == "review_checklist":
        return marker + prefix + "**Human-review checklist (Review-required).** " + text + cross_references + suffix
    return marker + prefix + text + cross_references + suffix


def _section_markdown(
    section: Mapping[str, Any],
    *,
    claims: Mapping[str, Mapping[str, Any]],
    evaluation_markers: bool,
    document: Mapping[str, Any],
    theory_registry: Mapping[str, Mapping[str, Any]],
    document_equation_labels: Mapping[str, str],
) -> str:
    section_id = _text(section.get("section_id"))
    title = _visible_for_document(document, section.get("title"))
    equation_labels = {
        **document_equation_labels,
        **{
            _text(block.get("block_id")): _equation_label(section_id, block.get("block_id"))
            for block in section.get("blocks") or []
            if isinstance(block, Mapping) and _text(block.get("kind")) == "equation"
        },
    }
    lines = [f"## {title}"]
    for block in section.get("blocks") or []:
        if isinstance(block, Mapping):
            rendered = _block_markdown(
                block,
                claims=claims,
                evaluation_markers=evaluation_markers,
                section_id=section_id,
                document=document,
                theory_registry=theory_registry,
                equation_labels=equation_labels,
            )
            if rendered:
                lines.append(rendered)
    return "\n\n".join(lines)


def _bibliography_markdown(document: Mapping[str, Any], claims: Mapping[str, Mapping[str, Any]]) -> str:
    cited_keys = {
        _text(key)
        for claim in claims.values()
        for key in claim.get("citation_keys") or []
        if _text(key)
    }
    records = [
        dict(record)
        for record in document.get("citation_registry") or []
        if isinstance(record, Mapping) and _text(record.get("citation_key")) in cited_keys
    ]
    lines = ["## References"]
    if not records:
        lines.append("No registered sources are cited in the visible manuscript.")
        return "\n\n".join(lines)
    for record in sorted(records, key=lambda item: _text(item.get("citation_key"))):
        metadata = _mapping(record.get("bibliographic_metadata"))
        authors = [_text(author) for author in metadata.get("authors") or [] if _text(author)]
        author_text = authors[0] + (" et al." if len(authors) > 1 else "") if authors else "Registered source"
        title = _visible(metadata.get("title")) or "Untitled work"
        venue = _visible(metadata.get("venue"))
        year = _visible(metadata.get("year"))
        tail = ", ".join(item for item in (venue, year) if item)
        entry = f"- [@{_text(record.get('citation_key'))}] {author_text}. *{title}*."
        lines.append(entry + (f" {tail}." if tail else ""))
    return "\n".join(lines)


def render_research_plan_markdown(
    document: Mapping[str, Any],
    *,
    evaluation_markers: bool = False,
    compact_references: bool = False,
) -> str:
    """Render a complete, source-safe Markdown manuscript from one document."""

    claims = _claim_map(document)
    theory_registry = theory_unit_registry(document)
    document_equation_labels = _document_equation_labels(document)
    metadata = _mapping(document.get("document_metadata"))
    title = _visible_for_document(document, metadata.get("title")) or "Research Plan"
    lines = [f"# {title}"]
    keywords = [
        _visible_for_document(document, keyword)
        for keyword in document.get("keywords") or []
        if _visible_for_document(document, keyword)
    ]
    if keywords:
        lines.append("**Keywords:** " + ", ".join(keywords))
    abstract = _mapping(document.get("abstract"))
    abstract_text = _visible_for_document(document, abstract.get("text"))
    if abstract_text:
        lines.append("## Abstract\n\n" + abstract_text)
    for section in document.get("sections") or []:
        if not isinstance(section, Mapping) or _text(section.get("section_id")) == "references":
            continue
        lines.append(
            _section_markdown(
                section,
                claims=claims,
                evaluation_markers=evaluation_markers,
                document=document,
                theory_registry=theory_registry,
                document_equation_labels=document_equation_labels,
            )
        )
    appendices = [section for section in document.get("appendices") or [] if isinstance(section, Mapping)]
    if appendices:
        lines.append("# Appendices")
        lines.extend(
            _section_markdown(
                section,
                claims=claims,
                evaluation_markers=evaluation_markers,
                document=document,
                theory_registry=theory_registry,
                document_equation_labels=document_equation_labels,
            )
            for section in appendices
        )
    if compact_references:
        cited_count = len(
            {
                _text(key)
                for claim in claims.values()
                for key in claim.get("citation_keys") or []
                if _text(key)
            }
        )
        lines.append(f"## References\n\nThe manuscript uses {cited_count} registered citation key(s).")
    else:
        lines.append(_bibliography_markdown(document, claims))
    return "\n\n".join(part for part in lines if part.strip()).strip() + "\n"


def render_quality_review_markdown(document: Mapping[str, Any]) -> str:
    """Render the full prose with private stable markers for quality review only."""

    return render_research_plan_markdown(
        document,
        evaluation_markers=True,
        compact_references=True,
    )


__all__ = ["render_quality_review_markdown", "render_research_plan_markdown"]
