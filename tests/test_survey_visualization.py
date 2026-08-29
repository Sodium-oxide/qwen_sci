import io
import json
import os
import sys
from types import SimpleNamespace

from omegaconf import OmegaConf
from PIL import Image


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SURVEY_AGENT_ROOT = os.path.join(PROJECT_ROOT, "src", "agents", "survey_agent")
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, SURVEY_AGENT_ROOT)

from modules.survey_visualizer import (
    FigureAsset,
    SurveyVisualizer,
    VisualBrief,
    VisualRelation,
    VisualStyleProfile,
)
from modules.survey_generator import SurveyGenerator
from src.llm.image_generation import ImageGenerationResult


class _Logger:
    def __init__(self):
        self.warnings = []

    def info(self, *_args, **_kwargs):
        pass

    def warning(self, *args, **_kwargs):
        self.warnings.append(args)


class _Chat:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def remote_chat(self, prompt, **kwargs):
        self.calls.append((prompt, kwargs))
        return self.responses.pop(0)


class _ImageClient:
    calls = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def generate(self, **kwargs):
        self.__class__.calls.append(kwargs)
        buffer = io.BytesIO()
        Image.new("RGB", (64, 48), "white").save(buffer, format="PNG")
        return ImageGenerationResult(
            images=(buffer.getvalue(),),
            model=kwargs["model"],
            provider="qwen",
            revised_prompt="provider-normalized prompt",
        )


def _project_config():
    return OmegaConf.create(
        {
            "llm": {
                "default_provider": "qwen",
                "providers": {
                    "qwen": {
                        "api_key": "test-key",
                        "base_url": "https://dashscope.example/compatible-mode/v1",
                    }
                },
            },
            "vision": {
                "provider": "qwen",
                "quality_model": "qwen3-vl-plus",
                "batch_model": "qwen3-vl-flash",
            },
            "image_generation": {
                "provider": "qwen",
                "base_url": "https://dashscope.example/api/v1",
                "role_models": {"academic_figure": "wan2.7-image-pro"},
            },
        }
    )


def _run_config(*, enabled=True):
    return SimpleNamespace(
        ModuleInfo=SimpleNamespace(
            SurveyVisualization=SimpleNamespace(
                enabled=enabled,
                max_figures=2,
                candidates_per_figure=1,
                allowed_figure_types=["overview_framework", "mechanism"],
                planner_section_max_chars=6000,
                planner_temperature=0.2,
                final_image_role="academic_figure",
                final_image_size="1024x768",
                compatible_image_size="1024x768",
                visual_qc_enabled=False,
                append_english_label_strip=False,
            )
        )
    )


def _brief(message, caption, alt, relation, entity, source_quote, source_paragraph_index=1):
    return json.dumps(
        {
            "main_message_en": message,
            "relations": [
                {
                    "relation_en": relation,
                    "source_quote": source_quote,
                    "source_paragraph_index": source_paragraph_index,
                }
            ],
            "entities_en": [entity, "Outcome"],
            "uncertainties_en": ["The boundary condition remains uncertain."],
            "composition_en": "Use a left-to-right conceptual layout with clear negative space.",
            "allowed_overlay_labels_en": [entity, "Outcome"],
            "caption_en": caption,
            "alt_text_en": alt,
        }
    )


def test_visual_companion_writes_english_caption_and_images_beside_survey(tmp_path):
    _ImageClient.calls = []
    chat = _Chat(
        [
            json.dumps(
                {
                    "candidates": [
                        {
                            "section_index": 1,
                            "figure_type": "overview_framework",
                            "source_paragraph_indices": [1, 2],
                            "insert_after_paragraph": 2,
                            "main_message_en": "Connect the survey's core inputs, processes, and outcomes.",
                            "composition_en": "Use three connected conceptual layers.",
                            "importance": 5,
                        },
                        {
                            "section_index": 2,
                            "figure_type": "mechanism",
                            "source_paragraph_indices": [1, 2],
                            "insert_after_paragraph": 2,
                            "main_message_en": "Explain the mechanism described by the supplied evidence.",
                            "composition_en": "Use a causal pathway with a muted uncertainty branch.",
                            "importance": 4,
                        },
                    ]
                }
            ),
            _brief(
                "Connect the survey's core inputs, processes, and outcomes.",
                "A conceptual overview of the evidence-supported framework",
                "Conceptual overview of inputs, processes, and outcomes.",
                "Inputs inform the central process and its outcome.",
                "Input",
                "The first supplied paragraph introduces the input and outcome [1].",
            ),
            _brief(
                "Explain the mechanism described by the supplied evidence.",
                "Mechanism connecting the stated driver and outcome",
                "Conceptual mechanism connecting the stated driver and outcome.",
                "The driver modulates the intermediate process.",
                "Driver",
                "The driver changes the intermediate process under the stated conditions [1].",
            ),
            json.dumps(
                {
                    "visual_language_en": "A restrained editorial scientific figure style with crisp linework.",
                    "palette": {
                        "background": "#F4F1EA",
                        "ink": "#252B33",
                        "primary": "#356C89",
                        "secondary": "#6F7E59",
                        "accent": "#C47A3A",
                        "uncertainty": "#9AA1A5",
                    },
                }
            ),
        ]
    )
    logger = _Logger()
    visualizer = SurveyVisualizer(
        _run_config(),
        chat,
        logger,
        image_client_factory=_ImageClient,
        project_config=_project_config(),
    )
    source = """# Survey Title

## Introduction

    The first supplied paragraph introduces the input and outcome [1].

The second supplied paragraph relates the core process to the outcome.

## Mechanism

    The driver changes the intermediate process under the stated conditions [1].

The resulting outcome remains uncertain outside the observed boundary.

## References

1. Reference entry.
"""
    survey_path = tmp_path / "survey.md"
    survey_path.write_text(source, encoding="utf-8")

    result = visualizer.run(
        source,
        survey_path=survey_path,
        references=["https://api.openalex.org/works/W12345"],
        evidence_plan={
            "schema_version": "test",
            "subhypotheses": [
                {
                    "sub_hypothesis_id": "SH1",
                    "slot_support": {
                        "core_relation": {"evidence_paper_ids": ["W12345"]}
                    },
                }
            ],
        },
        outline={
            "sections": [
                {"title": "Introduction", "description": "Set the framework.", "subsections": []},
                {"title": "Mechanism", "description": "Explain the mechanism.", "subsections": []},
            ]
        },
    )

    assert result["status"] == "completed"
    assert result["figure_count"] == 2
    assert survey_path.read_text(encoding="utf-8") == source
    visual_markdown = (tmp_path / "survey_visual.md").read_text(encoding="utf-8")
    assert "(fig_01_overview_framework.png)" in visual_markdown
    assert "(fig_02_mechanism.png)" in visual_markdown
    assert "Figure 1 |" in visual_markdown
    assert "Figure 2 |" in visual_markdown
    assert (tmp_path / "fig_01_overview_framework.png").is_file()
    assert (tmp_path / "fig_02_mechanism.png").is_file()
    assert not (tmp_path / "figures").exists()

    manifest = json.loads((tmp_path / "survey_visual_manifest.json").read_text(encoding="utf-8"))
    assert manifest["reader_facing_language"] == "en"
    assert manifest["outline_used"] is True
    assert manifest["references_received"] is True
    assert manifest["reference_ids"] == ["W12345"]
    assert manifest["style_profile"]["source"] == "llm"
    assert manifest["figures"][0]["source_paper_ids"] == ["W12345"]
    assert manifest["figures"][0]["relations"][0]["evidence_paths"][0]["slot_name"] == "core_relation"
    assert all("\u4e00" > char or char > "\u9fff" for figure in manifest["figures"] for char in figure["caption_en"])
    assert len(_ImageClient.calls) == 2
    assert all("#356C89" in call["prompt"] for call in _ImageClient.calls)
    assert all("[DIRECT_LEDGER_EVIDENCE]" not in call["prompt"] for call in _ImageClient.calls)
    assert all("DIRECT_LEDGER_EVIDENCE" not in call["prompt"] for call in _ImageClient.calls)
    assert all("QUALIFIED_SH_CONTRIBUTION" not in call["prompt"] for call in _ImageClient.calls)
    assert all("Scientific content that must be represented:" in call["prompt"] for call in _ImageClient.calls)
    assert "Approved outline context" in chat.calls[0][0]


def test_visualisation_disabled_does_not_call_the_chat_or_image_clients(tmp_path):
    chat = _Chat([])
    visualizer = SurveyVisualizer(
        _run_config(enabled=False),
        chat,
        _Logger(),
        image_client_factory=_ImageClient,
        project_config=_project_config(),
    )

    result = visualizer.run("# Title\n\n## Introduction\n\nText.", survey_path=tmp_path / "survey.md")

    assert result == {"status": "disabled", "figure_count": 0}
    assert chat.calls == []


def test_non_4k_qwen_image_role_uses_compatible_size():
    config = _run_config()
    config.ModuleInfo.SurveyVisualization.final_image_size = "3072x2304"
    config.ModuleInfo.SurveyVisualization.compatible_image_size = "2048x1536"
    project_config = _project_config()
    project_config.image_generation.role_models.academic_figure = "qwen-image-3.0-pro"
    visualizer = SurveyVisualizer(
        config,
        _Chat([]),
        _Logger(),
        image_client_factory=_ImageClient,
        project_config=project_config,
    )

    assert visualizer._image_size_for_model("qwen-image-3.0-pro") == "2048x1536"


def test_figure_prompt_uses_type_layout_and_caption_evidence_contract():
    visualizer = SurveyVisualizer(
        _run_config(),
        _Chat([]),
        _Logger(),
        image_client_factory=_ImageClient,
        project_config=_project_config(),
    )
    brief = VisualBrief(
        figure_id="fig_01_method_comparison",
        figure_number=1,
        figure_type="method_comparison",
        section_index=1,
        section_title="Comparison",
        source_paragraph_indices=(1, 2),
        insert_after_paragraph=2,
        main_message_en="Compare the supported approaches.",
        relations=(
            VisualRelation(
                relation_en="The approaches have distinct stated limitations.",
                source_paragraph_index=1,
                source_quote="The approaches have distinct stated limitations.",
                support_kind="QUALIFIED_SH_CONTRIBUTION",
                evidence_paper_ids=("W12345",),
                evidence_paths=(),
            ),
        ),
        entities_en=("Approach A", "Approach B", "Outcome"),
        uncertainties_en=("Comparability remains limited.",),
        composition_en="Use two aligned panels.",
        allowed_overlay_labels_en=("Approach A", "Approach B"),
        caption_en="Figure 1 | Comparison.",
        alt_text_en="Comparison of the two approaches.",
        source_paper_ids=("W12345",),
    )
    style = VisualStyleProfile(
        visual_language_en="Restrained editorial scientific figure style.",
        palette={
            "background": "#F4F1EA", "ink": "#252B33", "primary": "#356C89",
            "secondary": "#6F7E59", "accent": "#C47A3A", "uncertainty": "#9AA1A5",
        },
    )

    assert SurveyVisualizer._normalise_caption("Comparison of approaches", 2) == (
        "Figure 2 | Comparison of approaches. This schematic is a conceptual synthesis "
        "of the cited survey evidence and introduces no new empirical data."
    )
    prompt = visualizer._image_prompt(brief, style)
    assert "balanced parallel panels" in prompt
    assert "Exact visible label inventory" in prompt
    assert '"Approach A"' in prompt
    assert "character-for-character" in prompt
    assert "DIRECT_LEDGER_EVIDENCE" not in prompt
    assert "QUALIFIED_SH_CONTRIBUTION" not in prompt
    assert "The approaches have distinct stated limitations." in prompt


def test_quote_grounding_accepts_sentence_punctuation_variants_only():
    assert SurveyVisualizer._quote_is_grounded(
        "A driver, under the stated condition, changes the outcome",
        "A driver under the stated condition changes the outcome.",
    )
    assert not SurveyVisualizer._quote_is_grounded(
        "The driver improves the outcome",
        "The driver changes the intermediate process under the stated condition.",
    )
    assert not SurveyVisualizer._quote_is_grounded(
        "The driver changes the outcome",
        "The driver changes. The outcome improves.",
    )


def test_brief_uses_safe_english_fallbacks_for_optional_reader_fields():
    visualizer = SurveyVisualizer(
        _run_config(),
        _Chat([]),
        _Logger(),
        image_client_factory=_ImageClient,
        project_config=_project_config(),
    )
    candidate = SimpleNamespace(
        figure_type="mechanism",
        source_paragraph_indices=(1, 2),
        insert_after_paragraph=2,
    )
    section = SimpleNamespace(
        index=1,
        title="Mechanism",
        paragraphs=(
            SimpleNamespace(text="The driver changes the outcome [1]."),
            SimpleNamespace(text="The evidence remains bounded."),
        ),
    )
    brief = visualizer._brief_from_payload(
        {
            "main_message_en": "Explain the supported relationship.",
            "relations": [
                {
                    "relation_en": "The driver changes the outcome.",
                    "source_paragraph_index": 1,
                    "source_quote": "The driver changes the outcome [1].",
                }
            ],
            "entities_en": ["Driver", "Outcome"],
            "uncertainties_en": [],
            "composition_en": "Use a left-to-right pathway.",
        },
        candidate,
        section,
        1,
        [paragraph.text for paragraph in section.paragraphs],
        {"subhypotheses": [{"sub_hypothesis_id": "SH1", "evidence_paper_ids": ["W12345"]}]},
        {},
        {},
        ("W12345",),
    )

    assert brief is not None
    assert brief.caption_en.startswith("Figure 1 |")
    assert brief.alt_text_en.startswith("Conceptual diagram")
    assert brief.allowed_overlay_labels_en == (
        "Evidence-supported relationship",
        "Stated uncertainty",
    )


def test_brief_reuses_validated_candidate_composition_when_writer_omits_it():
    visualizer = SurveyVisualizer(
        _run_config(),
        _Chat([]),
        _Logger(),
        image_client_factory=_ImageClient,
        project_config=_project_config(),
    )
    candidate = SimpleNamespace(
        figure_type="mechanism",
        source_paragraph_indices=(1, 2),
        insert_after_paragraph=2,
        main_message_en="Explain the supported relationship.",
        composition_en="Use a left-to-right causal pathway with clear spacing.",
    )
    section = SimpleNamespace(
        index=1,
        title="Mechanism",
        paragraphs=(
            SimpleNamespace(text="The driver changes the outcome [1]."),
            SimpleNamespace(text="The evidence remains bounded."),
        ),
    )

    brief = visualizer._brief_from_payload(
        {
            "main_message_en": "Explain the supported relationship.",
            "relations": [
                {
                    "relation_en": "The driver changes the outcome.",
                    "source_paragraph_index": 1,
                    "source_quote": "The driver changes the outcome [1].",
                }
            ],
            "entities_en": ["Driver", "Outcome"],
        },
        candidate,
        section,
        1,
        [paragraph.text for paragraph in section.paragraphs],
        {"subhypotheses": [{"sub_hypothesis_id": "SH1", "evidence_paper_ids": ["W12345"]}]},
        {},
        {},
        ("W12345",),
    )

    assert brief is not None
    assert brief.composition_en == candidate.composition_en


def test_brief_reuses_validated_candidate_message_and_entities_when_writer_omits_them():
    visualizer = SurveyVisualizer(
        _run_config(),
        _Chat([]),
        _Logger(),
        image_client_factory=_ImageClient,
        project_config=_project_config(),
    )
    candidate = SimpleNamespace(
        figure_type="mechanism",
        source_paragraph_indices=(1, 2),
        insert_after_paragraph=2,
        main_message_en="Explain the supported relationship.",
        composition_en="Use a left-to-right causal pathway with clear spacing.",
        entities_en=("Driver", "Outcome"),
    )
    section = SimpleNamespace(
        index=1,
        title="Mechanism",
        paragraphs=(
            SimpleNamespace(text="The driver changes the outcome [1]."),
            SimpleNamespace(text="The evidence remains bounded."),
        ),
    )

    brief = visualizer._brief_from_payload(
        {
            "relations": [
                {
                    "relation_en": "The driver changes the outcome.",
                    "source_paragraph_index": 1,
                    "source_quote": "The driver changes the outcome [1].",
                }
            ]
        },
        candidate,
        section,
        1,
        [paragraph.text for paragraph in section.paragraphs],
        {"subhypotheses": [{"sub_hypothesis_id": "SH1", "evidence_paper_ids": ["W12345"]}]},
        {},
        {},
        ("W12345",),
    )

    assert brief is not None
    assert brief.main_message_en == candidate.main_message_en
    assert brief.entities_en == candidate.entities_en


def test_invalid_brief_receives_one_local_repair_before_acceptance(tmp_path):
    _ImageClient.calls = []
    chat = _Chat(
        [
            json.dumps(
                {
                    "candidates": [
                        {
                            "section_index": 1,
                            "figure_type": "mechanism",
                            "source_paragraph_indices": [1, 2],
                            "insert_after_paragraph": 2,
                            "main_message_en": "Explain the supported relationship.",
                            "composition_en": "Use a left-to-right pathway.",
                            "importance": 5,
                        }
                    ]
                }
            ),
            json.dumps({"main_message_en": "Missing grounded fields"}),
            _brief(
                "Explain the supported relationship.",
                "Supported relationship",
                "Supported relationship.",
                "The driver changes the outcome.",
                "Driver",
                "The driver changes the outcome [1].",
            ),
            json.dumps(
                {
                    "visual_language_en": "A restrained editorial scientific figure style.",
                    "palette": {
                        "background": "#F4F1EA", "ink": "#252B33", "primary": "#356C89",
                        "secondary": "#6F7E59", "accent": "#C47A3A", "uncertainty": "#9AA1A5",
                    },
                }
            ),
        ]
    )
    visualizer = SurveyVisualizer(
        _run_config(),
        chat,
        _Logger(),
        image_client_factory=_ImageClient,
        project_config=_project_config(),
    )
    source = (
        "# Survey\n\n## Mechanism\n\n"
        "The driver changes the outcome [1].\n\n"
        "The evidence remains bounded."
    )
    survey_path = tmp_path / "survey.md"
    survey_path.write_text(source, encoding="utf-8")

    result = visualizer.run(
        source,
        survey_path=survey_path,
        references=["W12345"],
        evidence_plan={"subhypotheses": [{"sub_hypothesis_id": "SH1", "evidence_paper_ids": ["W12345"]}]},
        outline={},
    )

    assert result["figure_count"] == 1
    assert any("Repair one rejected visual brief" in prompt for prompt, _kwargs in chat.calls)
    manifest = json.loads((tmp_path / "survey_visual_manifest.json").read_text(encoding="utf-8"))
    assert manifest["rejected_figures"] == []


def test_palette_mismatch_regenerates_only_the_affected_figure(tmp_path, monkeypatch):
    _ImageClient.calls = []
    config = _run_config()
    config.ModuleInfo.SurveyVisualization.visual_qc_enabled = True
    config.ModuleInfo.SurveyVisualization.max_regeneration_attempts = 1
    visualizer = SurveyVisualizer(
        config,
        _Chat([]),
        _Logger(),
        image_client_factory=_ImageClient,
        project_config=_project_config(),
    )
    brief = VisualBrief(
        figure_id="fig_01_mechanism",
        figure_number=1,
        figure_type="mechanism",
        section_index=1,
        section_title="Mechanism",
        source_paragraph_indices=(1, 2),
        insert_after_paragraph=2,
        main_message_en="Explain the supported relationship.",
        relations=(),
        entities_en=("Driver", "Outcome"),
        uncertainties_en=(),
        composition_en="Use a left-to-right pathway.",
        allowed_overlay_labels_en=(),
        caption_en="Figure 1 | Mechanism.",
        alt_text_en="Supported mechanism.",
        source_paper_ids=("W12345",),
    )
    style = VisualStyleProfile(
        visual_language_en="Restrained editorial scientific figure style.",
        palette={
            "background": "#F4F1EA", "ink": "#252B33", "primary": "#356C89",
            "secondary": "#6F7E59", "accent": "#C47A3A", "uncertainty": "#9AA1A5",
        },
    )
    responses = [
        (None, "rejected", ["The candidate does not match the locked article palette."], True),
        (b"final-image", "accepted", [], False),
    ]
    monkeypatch.setattr(
        visualizer,
        "_select_image_candidate",
        lambda *_args, **_kwargs: responses.pop(0),
    )

    asset = visualizer._render_figure(brief, style, tmp_path)

    assert asset.generation_attempts == 2
    assert len(_ImageClient.calls) == 2
    assert (tmp_path / "fig_01_mechanism.png").read_bytes() == b"final-image"


def test_untraced_relation_is_omitted_but_zero_figure_companion_is_still_written(tmp_path):
    chat = _Chat(
        [
            json.dumps(
                {
                    "candidates": [
                        {
                            "section_index": 1,
                            "figure_type": "mechanism",
                            "source_paragraph_indices": [1, 2],
                            "insert_after_paragraph": 2,
                            "main_message_en": "Explain the stated conceptual relationship.",
                            "composition_en": "Use a simple causal layout.",
                            "importance": 5,
                        }
                    ]
                }
            ),
            _brief(
                "Explain the stated conceptual relationship.",
                "Conceptual relationship in the section",
                "Conceptual relationship in the section.",
                "The first factor changes the second factor.",
                "First factor",
                "The first factor changes the second factor.",
            ),
        ]
    )
    visualizer = SurveyVisualizer(
        _run_config(),
        chat,
        _Logger(),
        image_client_factory=_ImageClient,
        project_config=_project_config(),
    )
    source = "# Survey\n\n## Evidence\n\nThe first factor changes the second factor.\n\nThe second factor affects a downstream outcome."
    survey_path = tmp_path / "survey.md"
    survey_path.write_text(source, encoding="utf-8")

    result = visualizer.run(source, survey_path=survey_path, evidence_plan={}, outline={})

    assert result["status"] == "skipped_no_briefs"
    assert (tmp_path / "survey_visual.md").read_text(encoding="utf-8") == source
    manifest = json.loads((tmp_path / "survey_visual_manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "skipped_no_briefs"
    assert manifest["figures"] == []


def test_save_survey_runs_visual_companion_after_canonical_artifacts(monkeypatch, tmp_path):
    import modules.survey_visualizer as visual_module

    calls = []

    class _FakeVisualizer:
        def __init__(self, config, chat_agent, logger):
            calls.append(("init", config, chat_agent, logger))

        def run(self, final_survey, *, survey_path, references, evidence_plan, outline, claim_traceability):
            calls.append(("run", final_survey, survey_path, references, evidence_plan, outline, claim_traceability))
            assert (tmp_path / "survey.md").read_text(encoding="utf-8") == final_survey
            return {"status": "completed", "figure_count": 1}

    monkeypatch.setattr(visual_module, "SurveyVisualizer", _FakeVisualizer)
    generator = object.__new__(SurveyGenerator)
    generator.logger = _Logger()
    generator.chat_agent = object()
    generator.survey_evidence_plan = {"subhypotheses": []}
    generator.survey_claim_traceability_artifact = {}
    generator.survey_outline_artifact = {"sections": [{"title": "Visual survey"}]}
    generator.config = SimpleNamespace(
        BasicInfo=SimpleNamespace(
            save_path=str(tmp_path / "survey.md"),
            save_json_path=str(tmp_path / "survey.json"),
            topic="Visual survey",
            debug=False,
            research_context={},
            subhypothesis_retrieval={},
            subhypothesis_decomposition={},
        )
    )

    artifacts = generator.save_survey("# Visual survey\n\nBody.", [])

    assert [call[0] for call in calls] == ["init", "run"]
    assert calls[1][3] == []
    assert calls[1][5] == {"sections": [{"title": "Visual survey"}]}
    assert artifacts["survey_markdown_path"] == str(tmp_path / "survey.md")
    assert artifacts["survey_outline_path"] == str(tmp_path / "survey_outline.json")
    assert json.loads((tmp_path / "survey.json").read_text(encoding="utf-8"))["survey_outline"] == {
        "sections": [{"title": "Visual survey"}]
    }
    assert json.loads((tmp_path / "survey_outline.json").read_text(encoding="utf-8")) == {
        "sections": [{"title": "Visual survey"}]
    }
    assert artifacts["survey_visualization"] == {"status": "completed", "figure_count": 1}
