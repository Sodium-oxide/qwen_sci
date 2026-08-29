from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import json
import shutil
from types import SimpleNamespace

import pytest

from src.agents.research_plan_author.bibtex_renderer import BibtexRenderError, ensure_citation_coverage, render_bibtex
from src.agents.research_plan_author.latex_compiler import compile_latex_project, resolve_executable
from src.agents.research_plan_author.latex_safety import LatexSafetyError, require_english_visible_text
from src.agents.research_plan_author.render import AuthorRenderingError, render_research_plan_document
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
    assert rendered.bibliography.emitted_keys == ("cite_example_1",)


@pytest.mark.parametrize("text", ["研究计划", "研究計画", "연구 계획", "خطة البحث", "Исследовательский план"])
def test_english_visible_text_rejects_non_latin_scripts(text: str) -> None:
    with pytest.raises(LatexSafetyError, match="non-English-script"):
        require_english_visible_text(text, label="test prose")


def test_english_visible_text_allows_latin_accents() -> None:
    assert require_english_visible_text("René Descartes and naïve Bayesian design", label="test prose")


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
    assert bibliography.needs_completion[0]["reason"] == "missing_metadata:authors"
    cited_incomplete = deepcopy(incomplete)
    cited_incomplete["claim_provenance"][0]["citation_keys"] = ["cite_example_1"]
    with pytest.raises(BibtexRenderError, match="cannot be rendered"):
        ensure_citation_coverage(cited_incomplete, bibliography)


def test_frozen_evidence_paper_metadata_flows_to_a_renderable_bibtex_entry() -> None:
    evidence_bundle = {
        "paper_registry": [
            {
                "canonical_paper_id": "W42",
                "title": "A Traceable Literature Record",
                "authors": ["Ada Example", "Ben Example"],
                "year": "2026",
                "venue": "Journal of Research Plans",
                "doi": "10.1000/w42",
                "url": "https://example.test/W42",
            }
        ],
        "evidence_cards": [
            {
                "card_id": "EC-W42",
                "source_id": "W42",
                "evidence_level": "fulltext",
                "claim_slot": "measurement_calibration",
                "source_location": "fulltext:W42",
            }
        ],
    }
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

    assert bibliography.emitted_keys == ()
    assert bibliography.needs_completion[0]["citation_key"] == citation["citation_key"]
    assert bibliography.needs_completion[0]["reason"].startswith("missing_metadata:")


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
