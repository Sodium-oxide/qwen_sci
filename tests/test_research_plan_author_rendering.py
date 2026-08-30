from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import json
import shutil
from types import SimpleNamespace

import pytest

from src.agents.research_plan_author.bibtex_renderer import (
    BibtexRenderError,
    bibliography_preflight_errors,
    ensure_citation_coverage,
    render_bibtex,
)
from src.agents.research_plan_author.contracts import validate_research_plan_document
import src.agents.research_plan_author.latex_compiler as latex_compiler
from src.agents.research_plan_author.latex_compiler import compile_latex_project, resolve_executable
from src.agents.research_plan_author.latex_safety import (
    LatexSafetyError,
    escape_latex_text,
    normalize_visible_text,
    safe_math_expression,
    split_equation_content,
)
from src.agents.research_plan_author.render import AuthorRenderingError, render_research_plan_document
from src.agents.research_plan_author.markdown_renderer import render_research_plan_markdown
from src.agents.research_plan_author.section_router import route_author_sections
from src.agents.research_plan_author.theory_presentation import theory_block_presentation
from src.agents.research_plan_author.template_adapter import TemplateAdapter, TemplateAdapterError
from src.agents.research_plan_author.template_profile import load_template_profile
from src.agents.research_plan_author.tex_renderer import TexRenderError, render_tex_project
from src.agents.research_plan_author.source_registry import build_frozen_source_registry


def _document(*, cited: bool = True, complete_metadata: bool = True) -> dict:
    citation_key = "cite_example_1"
    metadata = {
        "authors": ["Ada Example", "Ben Example"],
        "title": "A Provenance-Bounded Example Record",
        "year": "2026",
        "venue": "Journal of Testable Plans",
        "doi": "10.1000/example",
    }
    if not complete_metadata:
        metadata.pop("authors")
    return {
        "schema_version": "research_plan_document_v1",
        "document_status": "PROPOSAL_NO_OBSERVED_RESULTS",
        "language": "en",
        "source_design_id": "design-render-1",
        "document_metadata": {
            "title": "A 50% Proposal: Safe_Design & Traceability",
            "source_title": "中文上游标题",
            "title_status": "english_llm_composed",
            "discipline_ids": ["15"],
            "study_type": "proposal-only study",
        },
        "abstract": {"text": "This proposal plans a bounded comparison without reporting observed results.", "claim_ids": ["C1"]},
        "keywords": ["design", "traceability"],
        "sections": [
            {
                "section_id": "introduction",
                "title": "Introduction & Scope",
                "applicability": "required",
                "blocks": [
                    {
                        "block_id": "B1",
                        "kind": "paragraph",
                        "text": "The planned method uses 50% coverage, A_B, and a literal # marker.",
                        "claim_ids": ["C1"],
                    },
                    {
                        "block_id": "B2",
                        "kind": "equation",
                        "text": r"y = \alpha + \frac{x}{2}",
                        "claim_ids": ["C1"],
                    },
                    {
                        "block_id": "B3",
                        "kind": "table",
                        "text": "Condition | Planned role\nControl | Comparator",
                        "claim_ids": ["C1"],
                    },
                ],
            },
            {"section_id": "references", "title": "References", "applicability": "required", "blocks": []},
        ],
        "appendices": [],
        "citation_registry": [
            {
                "citation_key": citation_key,
                "source_id": "W1",
                "bibliographic_metadata": metadata,
            }
        ],
        "claim_provenance": [
            {
                "claim_id": "C1",
                "claim_kind": "background",
                "statement": "The proposal uses a provenance-bounded source record.",
                "qualification": "evidence_backed",
                "source_ids": ["W1"],
                "evidence_card_ids": [],
                "survey_anchor_ids": [],
                "formal_reference_ids": [],
                "outcome_branch_ids": [],
                "citation_keys": [citation_key] if cited else [],
            }
        ],
        "open_items": [],
        "review_items": [],
        "authoring_constraints": {"proposal_without_observed_results": True},
        "source_manifest": {},
        "authoring_blueprint": {},
        "contract_repair_audit": [],
    }


def _marker_template(path: Path, *, valid: bool = True, broken: bool = False) -> Path:
    path.mkdir()
    body_marker = "% QWENSCI_AUTHOR_BODY" if valid else "% QWENSCI_AUTHOR_CONTENT"
    document_end = "" if broken else "\\end{document}"
    (path / "main.tex").write_text(
        "\n".join(
            [
                "\\documentclass{article}",
                "% QWENSCI_AUTHOR_TITLE",
                "% QWENSCI_AUTHOR_AUTHOR",
                "\\begin{document}",
                "\\maketitle",
                "% QWENSCI_AUTHOR_ABSTRACT",
                body_marker,
                "% QWENSCI_AUTHOR_BIBLIOGRAPHY",
                document_end,
            ]
        ),
        encoding="utf-8",
    )
    return path


def test_marker_profile_copies_source_and_escapes_text(tmp_path: Path) -> None:
    template = _marker_template(tmp_path / "template")
    source_bytes = (template / "main.tex").read_bytes()
    rendered = render_tex_project(
        _document(),
        template_dir=template,
        project_dir=tmp_path / "render-project",
        profile=load_template_profile("markers_v1"),
    )

    text = rendered.main_tex.read_text(encoding="utf-8")
    assert source_bytes == (template / "main.tex").read_bytes()
    assert "% QWENSCI_AUTHOR_BODY" not in text
    assert "50\\%" in text
    assert "Safe\\_Design \\& Traceability" in text
    assert "中文上游标题" not in text
    assert r"\frac{x}{2}" in text
    assert "\\begin{equation}" in text
    assert "\\label{eq:introduction-B2}" in text
    assert "\\[" not in text
    assert "\\caption{Decision matrix}" in text
    assert "\\label{tab:introduction-B3}" in text
    assert "\\nocite" not in text
    assert rendered.bibliography.emitted_keys == ("cite_example_1",)


def test_renderer_renders_optional_block_heading_as_subsection(tmp_path: Path) -> None:
    document = _document()
    document["sections"][0]["blocks"][0]["heading"] = "Scope and Traceability"
    rendered = render_tex_project(
        document,
        template_dir=_marker_template(tmp_path / "heading-template"),
        project_dir=tmp_path / "heading-render",
        profile=load_template_profile("markers_v1"),
    )

    assert "\\subsection{Scope and Traceability}" in rendered.main_tex.read_text(encoding="utf-8")


def test_renderer_uses_align_cross_references_and_hides_private_survey_anchors(tmp_path: Path) -> None:
    document = _document()
    document["sections"][0]["blocks"][0]["text"] = (
        "The derivation remains source-bounded [survey:survey_markdown#section-003] "
        "and anchor:gap_evidence_anchor:sh4:boundary_variable:opaque-token."
    )
    document["sections"][0]["blocks"][0]["reference_block_ids"] = ["B2"]
    document["sections"][0]["blocks"][1]["text"] = r"x = y\\y = z"
    document["sections"][0]["blocks"][2]["text"] = (
        "Condition | Action\n"
        "[survey:survey_markdown#section-004] Control | Retain comparator\n"
        "Boundary | Request human review"
    )

    rendered = render_tex_project(
        document,
        template_dir=_marker_template(tmp_path / "align-template"),
        project_dir=tmp_path / "align-render",
        profile=load_template_profile("markers_v1"),
    )
    text = rendered.main_tex.read_text(encoding="utf-8")

    assert "\\begin{align}" in text
    assert r"\nonumber \\" in text
    assert "See Eq.~\\eqref{eq:introduction-B2}." in text
    assert "survey:survey_markdown" not in text
    assert "anchor:gap_evidence_anchor" not in text


def test_theory_renderer_uses_public_labels_and_resolves_scoped_equation_references(tmp_path: Path) -> None:
    document = _document(cited=False)
    introduction = document["sections"][0]
    introduction["blocks"][0].update(
        {
            "kind": "lemma",
            "text": "Candidate TS-L-1 uses the declared domain and the later relation.",
            "theory_unit_ids": ["TS-L-1"],
            "reference_block_ids": ["derivation:relation"],
        }
    )
    introduction["blocks"].append(
        {
            "block_id": "obligation",
            "kind": "proposition",
            "text": "TS-PO-1 remains open until the stated implication is checked.",
            "claim_ids": ["C1"],
            "theory_unit_ids": ["TS-PO-1"],
        }
    )
    document["sections"].insert(
        1,
        {
            "section_id": "derivation",
            "title": "Candidate Derivation",
            "applicability": "required",
            "blocks": [
                {
                    "block_id": "relation",
                    "kind": "equation",
                    "text": r"F = G",
                    "claim_ids": ["C1"],
                }
            ],
        },
    )
    document["sections"].insert(
        2,
        {
            "section_id": "outcomes",
            "title": "Decision Branches",
            "applicability": "required",
            "blocks": [
                {
                    "block_id": "no_information",
                    "kind": "table",
                    "text": "Decision status | Next action\nTS-BR-NOINFO | Route the unresolved dependency to review.",
                    "claim_ids": ["C1"],
                    "theory_unit_ids": ["TS-BR-NOINFO"],
                }
            ],
        },
    )
    document["theory_spine"] = {
        "lemma_units": [{"lemma_id": "TS-L-1", "display_label": "L1", "status": "candidate"}],
        "proof_obligations": [{"proof_obligation_id": "TS-PO-1", "display_label": "PO1", "status": "unverified"}],
        "falsifiers": [],
        "decision_branches": [{"branch_id": "TS-BR-NOINFO", "display_label": "No-information", "branch_kind": "no_information"}],
    }

    markdown = render_research_plan_markdown(document)
    rendered = render_tex_project(
        document,
        template_dir=_marker_template(tmp_path / "theory-template"),
        project_dir=tmp_path / "theory-render",
        profile=load_template_profile("markers_v1"),
    )
    tex = rendered.main_tex.read_text(encoding="utf-8")

    assert "**Lemma L1 (Candidate).**" in markdown
    assert "**Proof Obligation PO1 (Unverified).**" in markdown
    assert "**Decision Status: No-information.**" in markdown
    assert "See Eq. (eq:derivation-relation)." in markdown
    assert "TS-" not in markdown
    assert "\\paragraph{Lemma L1 (Candidate).}" in tex
    assert "\\paragraph{Proof Obligation PO1 (Unverified).}" in tex
    assert "\\caption{Decision Status: No-information}" in tex
    assert "See Eq.~\\eqref{eq:derivation-relation}." in tex
    assert "TS-" not in tex


def test_theory_unit_status_overrides_a_less_precise_claim_qualification() -> None:
    claims = {"C1": {"qualification": "proposed"}}
    proof_registry = {
        "TS-PO-1": {
            "unit_kind": "proof_obligation",
            "proof_obligation_id": "TS-PO-1",
            "display_label": "PO1",
            "status": "unverified",
        }
    }
    branch_registry = {
        "TS-BR-EXPECTED": {
            "unit_kind": "decision_branch",
            "branch_id": "TS-BR-EXPECTED",
            "display_label": "Expected branch",
            "status": "expected_not_observed",
        }
    }

    proof_prefix, proof_status = theory_block_presentation(
        {"kind": "proposition", "claim_ids": ["C1"], "theory_unit_ids": ["TS-PO-1"]},
        claims=claims,
        registry=proof_registry,
    )
    branch_prefix, branch_status = theory_block_presentation(
        {"kind": "outcome_branch", "claim_ids": ["C1"], "theory_unit_ids": ["TS-BR-EXPECTED"]},
        claims=claims,
        registry=branch_registry,
    )

    assert (proof_prefix, proof_status) == ("Proof Obligation PO1 (Unverified).", "Unverified")
    assert (branch_prefix, branch_status) == (
        "Pre-registered Branch (Expected---Not Observed).",
        "Expected---Not Observed",
    )


@pytest.mark.parametrize("text", ["研究计划", "研究計画", "연구 계획", "خطة البحث", "Исследовательский план", "Measurements of Ω and Λ"])
def test_visible_text_allows_all_scripts(text: str) -> None:
    assert normalize_visible_text(text, label="test prose") == text


def test_visible_text_normalization_allows_latin_accents() -> None:
    assert normalize_visible_text("René Descartes and naïve Bayesian design", label="test prose") == "René Descartes and naïve Bayesian design"


def test_visible_text_escape_restores_backslashes_without_control_characters() -> None:
    rendered = escape_latex_text(r"The literal expression is $\theta$.", label="test prose")

    assert rendered == r"The literal expression is \$\textbackslash{}theta\$."
    assert "\x00" not in rendered
    assert "QWENSCI_BACKSLASH" not in rendered


def test_math_expression_requires_a_real_mathematical_structure() -> None:
    with pytest.raises(LatexSafetyError, match="mathematical relation or structure"):
        safe_math_expression("The first matter premise is expressed in prose.", label="test equation")

    assert safe_math_expression(r"\int_\gamma T_{ab}k^ak^b\,d\lambda \geq 0", label="test equation")


def test_math_expression_partitions_explanatory_prose_from_valid_formulae() -> None:
    mixed = (
        "A null generator with tangent k^a obeys the proposed relation.\n\n"
        r"\int_\gamma T_{ab} k^a k^b \, d\lambda \geq 0 ."
        "\n\n"
        "The interpretation remains conditional on the stated assumptions."
    )

    with pytest.raises(LatexSafetyError, match="explanatory prose"):
        safe_math_expression(mixed, label="test equation")

    assert split_equation_content(mixed, label="test equation") == [
        ("prose", "A null generator with tangent k^a obeys the proposed relation."),
        ("equation", r"\int_\gamma T_{ab} k^a k^b \, d\lambda \geq 0 ."),
        ("prose", "The interpretation remains conditional on the stated assumptions."),
    ]


def test_renderer_splits_mixed_equation_content_before_tex_emission(tmp_path: Path) -> None:
    document = _document(cited=False)
    document["sections"][0]["blocks"][1]["text"] = (
        "A null generator with tangent k^a obeys the proposed relation.\n\n"
        r"\int_\gamma T_{ab} k^a k^b \, d\lambda \geq 0 ."
        "\n\n"
        "A second focusing condition is kept separate from the first relation.\n\n"
        r"\int_\gamma R_{ab} k^a k^b \, d\lambda > 0 ."
    )

    rendered = render_tex_project(
        document,
        template_dir=_marker_template(tmp_path / "mixed-equation-template"),
        project_dir=tmp_path / "mixed-equation-render",
        profile=load_template_profile("markers_v1"),
    )
    text = rendered.main_tex.read_text(encoding="utf-8")

    assert "\\begin{equation}\nA null generator" not in text
    assert text.count("\\begin{equation}") == 1
    assert text.count("\\begin{equation*}") == 1
    assert r"A null generator with tangent k\textasciicircum{}a obeys the proposed relation." in text
    assert r"\int_\gamma T_{ab} k^a k^b \, d\lambda \geq 0 ." in text
    assert r"\int_\gamma R_{ab} k^a k^b \, d\lambda > 0 ." in text


def test_renderer_uses_wide_layout_for_long_four_column_decision_matrix(tmp_path: Path) -> None:
    document = _document()
    document["sections"][0]["blocks"][2]["text"] = (
        "Candidate case | Assumption check | Interpretation | Next action\n"
        "--- | --- | --- | ---\n"
        "Near-threshold configuration | Compactness remains in the proposed domain | Continue the lemma chain only conditionally | Record the result for human review\n"
        "Boundary configuration | An upstream focusing premise fails | Treat it as an out-of-domain counterexample rather than a conclusion | Revise the declared domain"
    )

    rendered = render_tex_project(
        document,
        template_dir=_marker_template(tmp_path / "wide-table-template"),
        project_dir=tmp_path / "wide-table-render",
        profile=load_template_profile("markers_v1"),
    )
    text = rendered.main_tex.read_text(encoding="utf-8")

    assert "\\begin{table*}" in text
    assert "p{0.23\\textwidth}" in text
    assert "p{0.14\\linewidth}" not in text
    assert "---" not in text


def test_renderer_uses_a_safe_width_for_six_column_decision_matrix(tmp_path: Path) -> None:
    document = _document()
    document["sections"][0]["blocks"][2]["text"] = (
        "Branch | Premise | Boundary | Falsifier | Status | Action\n"
        "Candidate | Retained | Declared domain | None | Unverified | Continue the obligation\n"
        "No-information | Missing input | Do not infer theorem status | Not applicable | Review-required | Route to review"
    )

    rendered = render_tex_project(
        document,
        template_dir=_marker_template(tmp_path / "six-column-template"),
        project_dir=tmp_path / "six-column-render",
        profile=load_template_profile("markers_v1"),
    )
    text = rendered.main_tex.read_text(encoding="utf-8")

    assert "\\begin{table*}" in text
    assert text.count("p{0.1533\\textwidth}") == 6
    assert "p{0.18\\textwidth}" not in text


def test_renderer_rejects_unanchored_or_observed_visible_prose(tmp_path: Path) -> None:
    unanchored = _document(cited=False)
    unanchored["sections"][0]["blocks"][0]["claim_ids"] = []
    with pytest.raises(TexRenderError, match="must reference at least one claim ID"):
        render_tex_project(
            unanchored,
            template_dir=_marker_template(tmp_path / "unanchored-template"),
            project_dir=tmp_path / "unanchored-render",
            profile=load_template_profile("markers_v1"),
        )

    observed_abstract = _document(cited=False)
    observed_abstract["abstract"]["text"] = "This study observed a treatment effect."
    with pytest.raises(TexRenderError, match="abstract presents an observed result"):
        render_tex_project(
            observed_abstract,
            template_dir=_marker_template(tmp_path / "observed-template"),
            project_dir=tmp_path / "observed-render",
            profile=load_template_profile("markers_v1"),
        )


def test_missing_or_duplicate_template_marker_fails(tmp_path: Path) -> None:
    missing = _marker_template(tmp_path / "missing", valid=False)
    with pytest.raises(TexRenderError, match="must occur exactly once"):
        render_tex_project(
            _document(),
            template_dir=missing,
            project_dir=tmp_path / "missing-render",
            profile=load_template_profile("markers_v1"),
        )

    duplicate = _marker_template(tmp_path / "duplicate")
    with (duplicate / "main.tex").open("a", encoding="utf-8") as handle:
        handle.write("\n% QWENSCI_AUTHOR_TITLE\n")
    with pytest.raises(TexRenderError, match="must occur exactly once"):
        render_tex_project(
            _document(),
            template_dir=duplicate,
            project_dir=tmp_path / "duplicate-render",
            profile=load_template_profile("markers_v1"),
        )


def test_raw_tex_is_rejected_and_incomplete_bibtex_is_ledgered(tmp_path: Path) -> None:
    unsafe = _document(cited=False)
    unsafe["sections"][0]["blocks"][1]["text"] = r"\input{private.tex}"
    with pytest.raises(TexRenderError, match="forbidden TeX command"):
        render_tex_project(
            unsafe,
            template_dir=_marker_template(tmp_path / "unsafe-template"),
            project_dir=tmp_path / "unsafe-render",
            profile=load_template_profile("markers_v1"),
        )

    incomplete = _document(cited=False, complete_metadata=False)
    bibliography = render_bibtex(incomplete)
    assert bibliography.emitted_keys == ()
    assert bibliography.needs_completion == ()
    cited_incomplete = deepcopy(incomplete)
    cited_incomplete["claim_provenance"][0]["citation_keys"] = ["cite_example_1"]
    cited_bibliography = render_bibtex(cited_incomplete)
    assert cited_bibliography.needs_completion[0]["reason"] == "missing_metadata:authors"
    with pytest.raises(BibtexRenderError, match="cannot be rendered"):
        ensure_citation_coverage(cited_incomplete, cited_bibliography)


def test_frozen_evidence_paper_metadata_flows_to_a_renderable_bibtex_entry() -> None:
    compact_card = {
        "card_id": "EC-W42",
        "source_id": "W42",
        "citation_key": "cite_w42",
        "evidence_level": "fulltext",
        "claim_slot": "measurement_calibration",
        "source_location": "fulltext:W42",
    }
    registry = build_frozen_source_registry(
        {
            "source_bundle": {
                "author_context": {
                    "source_registry": {
                        "allowed_source_ids": ["W42"],
                        "allowed_survey_anchor_ids": [],
                        "evidence_cards_by_id": {"EC-W42": compact_card},
                        "citation_registry": [
                            {
                                "citation_key": "cite_w42",
                                "source_id": "W42",
                                "evidence_level": "fulltext",
                                "evidence_card_ids": ["EC-W42"],
                                "citation_rendering_status": "RENDERABLE",
                                "bibliographic_metadata": {
                                    "authors": ["Ada Example", "Ben Example"],
                                    "title": "A Traceable Literature Record",
                                    "year": "2026",
                                    "venue": "Journal of Research Plans",
                                    "doi": "10.1000/w42",
                                    "url": "https://example.test/W42",
                                },
                            }
                        ],
                    }
                }
            }
        }
    )
    document = _document(cited=True)
    citation = registry["citation_registry"][0]
    document["citation_registry"] = registry["citation_registry"]
    document["claim_provenance"][0]["citation_keys"] = [citation["citation_key"]]

    bibliography = render_bibtex(document)

    assert bibliography.emitted_keys == (citation["citation_key"],)
    assert bibliography.needs_completion == ()
    assert "@article{cite_w42," in bibliography.content
    assert bibliography_preflight_errors(registry["citation_registry"]) == []


def test_bibtex_allows_non_english_bibliographic_metadata() -> None:
    document = _document(cited=True)
    metadata = document["citation_registry"][0]["bibliographic_metadata"]
    metadata["authors"] = ["张伟", "Иван Петров"]
    metadata["title"] = "量子场中的能量条件"
    metadata["venue"] = "物理学报"

    bibliography = render_bibtex(document)

    assert bibliography.emitted_keys == ("cite_example_1",)
    assert "张伟 and others" in bibliography.content
    assert "Иван Петров" not in bibliography.content
    assert "量子场中的能量条件" in bibliography.content
    assert bibliography_preflight_errors(document["citation_registry"]) == []


def test_bibtex_omits_uncited_records_and_abbreviates_long_author_lists() -> None:
    document = _document(cited=True)
    document["citation_registry"][0]["bibliographic_metadata"]["authors"] = [
        "Ada Example",
        "Ben Example",
        "Casey Example",
    ]
    document["citation_registry"].append(
        {
            "citation_key": "cite_uncited",
            "source_id": "W2",
            "bibliographic_metadata": {
                "authors": ["Uncited Author", "Uncited Coauthor"],
                "title": "An Uncited Record",
                "year": "2025",
                "venue": "Unused Journal",
            },
        }
    )

    bibliography = render_bibtex(document)

    assert bibliography.emitted_keys == ("cite_example_1",)
    assert "Ada Example and others" in bibliography.content
    assert "Ben Example" not in bibliography.content
    assert "cite_uncited" not in bibliography.content


def test_document_validator_allows_unicode_reference_inventory_and_title() -> None:
    document = _document()
    references = next(section for section in document["sections"] if section["section_id"] == "references")
    references["title"] = "参考文献"
    references["blocks"] = [
        {
            "block_id": "ref_inventory",
            "kind": "list",
            "text": "张伟 and Иван Петров. 量子场中的能量条件. 物理学报.",
            "claim_ids": ["C1"],
        }
    ]

    assert validate_research_plan_document(document) == []


def test_bibliography_preflight_defers_uncited_metadata_completion() -> None:
    citation = {
        "citation_key": "cite_missing_metadata",
        "source_id": "W-missing",
        "evidence_level": "abstract",
        "evidence_card_ids": ["EC-missing"],
        "citation_rendering_status": "NOT_RENDERABLE_NEEDS_HUMAN_METADATA",
        "citation_missing_fields": ["authors", "venue"],
    }

    assert bibliography_preflight_errors([citation]) == []


def test_document_validator_rejects_unknown_or_non_equation_cross_references() -> None:
    unknown_reference = _document(cited=False)
    unknown_reference["sections"][0]["blocks"][0]["reference_block_ids"] = ["missing-equation"]
    assert validate_research_plan_document(unknown_reference) == [
        "visible section block B1 references unknown equation blocks: ['missing-equation']"
    ]

    non_equation_reference = _document(cited=False)
    non_equation_reference["sections"][0]["blocks"][0]["reference_block_ids"] = ["B3"]
    assert validate_research_plan_document(non_equation_reference) == [
        "visible section block B1 cross-references non-equation blocks: ['B3']"
    ]


def test_document_validator_accepts_scoped_equations_and_keeps_appendix_a_math_specific() -> None:
    document = _document(cited=False)
    document["sections"].insert(
        1,
        {
            "section_id": "derivation",
            "title": "Derivation",
            "applicability": "required",
            "blocks": [
                {"block_id": "relation", "kind": "equation", "text": "F = G", "claim_ids": ["C1"]},
                {"block_id": "explanation", "kind": "paragraph", "text": "This explains the relation.", "claim_ids": ["C1"]},
            ],
        },
    )
    document["sections"][0]["blocks"][0]["reference_block_ids"] = ["derivation:relation"]

    assert validate_research_plan_document(document) == []

    non_equation = deepcopy(document)
    non_equation["sections"][0]["blocks"][0]["reference_block_ids"] = ["derivation:explanation"]
    assert validate_research_plan_document(non_equation) == [
        "visible section block B1 cross-references non-equation blocks: ['derivation:explanation']"
    ]

    mathematics_routes = route_author_sections({"provenance": {"template_id": "mathematics_theory"}})["routes"]
    mathematics_appendices = [route for route in mathematics_routes if route["target"] == "appendices"]
    assert [route["section_id"] for route in mathematics_appendices] == [
        "appendix_variables_and_definitions",
        "appendix_idea_evolution",
        "appendix_evidence_and_review",
    ]
    assert mathematics_appendices[0]["title"] == "Energy-Condition Taxonomy, Symbols, and Boundary Defense"

    computational_routes = route_author_sections({"provenance": {"template_id": "computational_digital"}})["routes"]
    computational_appendices = [route for route in computational_routes if route["target"] == "appendices"]
    assert [route["section_id"] for route in computational_appendices] == [
        "appendix_idea_evolution",
        "appendix_variables_and_definitions",
        "appendix_evidence_and_review",
    ]


def test_document_validator_rejects_global_section_and_tex_equation_label_collisions() -> None:
    duplicate_section = _document(cited=False)
    duplicate_section["appendices"] = [
        {
            "section_id": "introduction",
            "title": "Repeated section",
            "applicability": "required",
            "blocks": [],
        }
    ]
    assert "document contains duplicate section_id values across sections and appendices" in validate_research_plan_document(duplicate_section)

    label_collision = _document(cited=False)
    label_collision["sections"].insert(
        1,
        {
            "section_id": "a_b",
            "title": "First normalized route",
            "applicability": "required",
            "blocks": [{"block_id": "relation", "kind": "equation", "text": "F = G", "claim_ids": ["C1"]}],
        },
    )
    label_collision["sections"].insert(
        2,
        {
            "section_id": "a-b",
            "title": "Second normalized route",
            "applicability": "required",
            "blocks": [{"block_id": "relation", "kind": "equation", "text": "F = G", "claim_ids": ["C1"]}],
        },
    )
    assert validate_research_plan_document(label_collision) == [
        "document equation labels collide after TeX normalization: eq:a-b-relation <- ['a-b:relation', 'a_b:relation']"
    ]


def test_compile_and_pdf_validation_publishes_only_validated_pdf(tmp_path: Path) -> None:
    if not all(shutil.which(executable) for executable in ("pdflatex", "bibtex", "pdftoppm")):
        pytest.skip("local LaTeX/PDF validation executables are unavailable")
    try:
        result = render_research_plan_document(
            _document(),
            output_dir=tmp_path / "out",
            timestamp="20260829-000000-000001",
            preparation_collision_index=0,
            template_dir=_marker_template(tmp_path / "compile-template"),
            template_profile="markers_v1",
            compile_timeout_seconds=60,
        )
    except AuthorRenderingError as error:
        paths = error.paths
        diagnostics = paths.compile_log.read_text(encoding="utf-8", errors="replace") if paths and paths.compile_log.is_file() else ""
        if "fresh TeX installation" in diagnostics or "CreateDirectoryW" in diagnostics:
            pytest.skip("local MiKTeX installation is not initialized for this sandbox user")
        raise

    assert result.artifacts.pdf.is_file()
    assert result.artifacts.compile_log.is_file()
    assert result.artifacts.compile_json.is_file()
    assert result.artifacts.pdf_validation_json.is_file()
    assert result.artifacts.tex.is_file()
    assert result.artifacts.bibtex.is_file()
    assert not result.artifacts.staged_pdf.exists()
    assert json.loads(result.artifacts.pdf_validation_json.read_text(encoding="utf-8"))["valid"] is True


def test_compile_failure_retains_diagnostics_but_never_publishes_pdf(tmp_path: Path) -> None:
    if not shutil.which("pdflatex"):
        pytest.skip("local pdflatex is unavailable")
    with pytest.raises(AuthorRenderingError) as error:
        render_research_plan_document(
            _document(cited=False),
            output_dir=tmp_path / "out",
            timestamp="20260829-000000-000002",
            preparation_collision_index=0,
            template_dir=_marker_template(tmp_path / "broken-template", broken=True),
            template_profile="markers_v1",
            compile_timeout_seconds=60,
        )
    paths = error.value.paths
    assert paths is not None
    assert paths.compile_log.is_file()
    assert paths.compile_json.is_file()
    assert not paths.pdf.exists()


def test_ieee_profile_requires_explicit_known_anchors(tmp_path: Path) -> None:
    template = tmp_path / "not-ieee"
    _marker_template(template)
    with pytest.raises(TexRenderError, match="must occur exactly once"):
        render_tex_project(
            _document(cited=False),
            template_dir=template,
            project_dir=tmp_path / "rendered",
            profile=load_template_profile("ieee_conference_v1", main_tex="main.tex"),
        )


def test_declared_ieee_template_profile_uses_the_real_entrypoint_without_mutation(tmp_path: Path) -> None:
    repository_root = Path(__file__).resolve().parents[1]
    template = repository_root / "Conference-LaTeX-template_10-17-19"
    source_main = template / "conference_101719.tex"
    source_bytes = source_main.read_bytes()
    result = render_tex_project(
        _document(cited=False),
        template_dir=template,
        project_dir=tmp_path / "ieee-rendered",
        profile=load_template_profile("ieee_conference_v1"),
    )

    rendered = result.main_tex.read_text(encoding="utf-8")
    assert result.main_tex.name == "conference_101719.tex"
    assert source_main.read_bytes() == source_bytes
    assert "This document is a model and instructions" not in rendered
    assert "IEEE conference templates contain guidance text" not in rendered
    assert "\\end{document}" in rendered
    assert "A 50\\% Proposal" in rendered


def test_resolve_executable_rejects_explicit_missing_path(tmp_path: Path) -> None:
    with pytest.raises(Exception, match="not an executable file"):
        resolve_executable(
            explicit=tmp_path / "missing-pdflatex",
            environment_variable="SCIENCE_LATEX_ENGINE",
            configured="",
            fallback="pdflatex",
            label="LaTeX engine",
        )


def test_author_cli_forwards_explicit_rendering_overrides(monkeypatch, tmp_path: Path, capsys) -> None:
    from omegaconf import OmegaConf
    import src.cli as cli
    import src.agents.research_plan_author.artifacts as author_artifacts
    import src.agents.research_plan_author.llm_json as author_llm_json
    import src.agents.research_plan_author.render as author_render
    import src.agents.research_plan_author.run as author_run

    config_path = tmp_path / "config.yaml"
    OmegaConf.save(OmegaConf.create({"research_plan_author": {"enabled": True}}), config_path)
    author_input = tmp_path / "author.json"
    survey_manifest = tmp_path / "survey_manifest.json"
    author_input.write_text("{}", encoding="utf-8")
    survey_manifest.write_text("{}", encoding="utf-8")
    captured: dict[str, object] = {}

    def fake_run(*_args: object, **_kwargs: object) -> dict:
        return {
            "status": "COMPOSED_FOR_RENDERING",
            "source_design_id": "design-1",
            "selected_direction_id": "direction-1",
            "document": {},
        }

    class FakePreparationPaths:
        collision_index = 0

        @staticmethod
        def as_dict() -> dict[str, object]:
            return {"preparation_json": "p.json"}

    class FakeRenderPaths:
        @staticmethod
        def as_dict() -> dict[str, object]:
            return {"pdf": "proposal.pdf"}

    def fake_render(document: object, **kwargs: object) -> object:
        captured["document"] = document
        captured.update(kwargs)
        return SimpleNamespace(artifacts=FakeRenderPaths())

    monkeypatch.setattr(author_run, "run_research_plan_author", fake_run)
    monkeypatch.setattr(author_artifacts, "write_author_preparation_artifacts", lambda *_args, **_kwargs: FakePreparationPaths())
    monkeypatch.setattr(author_llm_json, "build_author_json_llm_call", lambda **_kwargs: lambda *_a, **_kw: {})
    monkeypatch.setattr(author_render, "render_research_plan_document", fake_render)
    parser = cli._build_root_parser()
    args = parser.parse_args(
        [
            "author",
            "--config",
            str(config_path),
            "--author-input",
            str(author_input),
            "--survey-manifest",
            str(survey_manifest),
            "--template-dir",
            str(tmp_path / "template"),
            "--template-profile",
            "markers_v1",
            "--template-main",
            "paper.tex",
            "--latex-engine",
            "custom-pdflatex",
            "--bibtex",
            "custom-bibtex",
            "--pdf-renderer",
            "custom-pdftoppm",
            "--compile-timeout-seconds",
            "33",
            "--author-name",
            "Example Author",
        ]
    )

    assert cli._author_command(args) == cli.AUTHOR_EXIT_SUCCESS
    assert captured["template_dir"] == (tmp_path / "template").resolve()
    assert captured["template_profile"] == "markers_v1"
    assert captured["template_main"] == "paper.tex"
    assert captured["latex_engine"] == "custom-pdflatex"
    assert captured["bibtex"] == "custom-bibtex"
    assert captured["pdf_renderer"] == "custom-pdftoppm"
    assert captured["compile_timeout_seconds"] == 33
    assert captured["author_name"] == "Example Author"
    assert json.loads(capsys.readouterr().out)["render_artifacts"]["pdf"] == "proposal.pdf"
