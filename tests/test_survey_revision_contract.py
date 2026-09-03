import os
import sys
from types import SimpleNamespace
import json
from pathlib import Path

import pytest


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SURVEY_AGENT_ROOT = os.path.join(PROJECT_ROOT, "src", "agents", "survey_agent")
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, SURVEY_AGENT_ROOT)

from modules.refine_agent import (
    AgentContext,
    AgenticRevisor,
    apply_revision_to_text,
    validate_revision_payload,
)
from modules.survey_generator import SurveyGenerator
from utils.utils import extract_json
from src.pipeline.survey_handoff_persistence import verify_survey_manifest_artifacts


class _Logger:
    def info(self, *_args, **_kwargs):
        pass

    def warning(self, *_args, **_kwargs):
        pass

    def error(self, *_args, **_kwargs):
        pass


def test_survey_artifact_persists_project_research_context(tmp_path):
    generator = object.__new__(SurveyGenerator)
    generator.logger = _Logger()
    generator.config = SimpleNamespace(
        BasicInfo=SimpleNamespace(
            save_path=str(tmp_path / "survey.md"),
            save_json_path=str(tmp_path / "survey.json"),
            topic="Crop disease diagnosis",
            debug=False,
            research_context={
                "schema_version": "project_research_context_v1",
                "primary_discipline": "agricultural_biological_sciences",
            },
            subhypothesis_retrieval={
                "schema_version": "subhypothesis_retrieval_execution_v1",
                "coverage_final": {"complete": True},
            },
        )
    )

    generator.save_survey("Survey body", [{"title": "Reference"}])

    payload = json.loads((tmp_path / "survey.json").read_text(encoding="utf-8"))
    assert payload["research_context"]["primary_discipline"] == "agricultural_biological_sciences"
    assert payload["subhypothesis_retrieval"]["coverage_final"]["complete"] is True
    assert payload["paper"] == "Survey body"


def test_save_survey_publishes_completed_handoff_when_contract_is_available(tmp_path):
    generator = object.__new__(SurveyGenerator)
    generator.logger = _Logger()
    generator.survey_claim_traceability_artifact = {"claims": []}
    generator.survey_outline_artifact = {"sections": [{"title": "Survey"}]}
    generator.survey_evidence_plan = {
        "schema_version": "survey_sh_evidence_plan_v1",
        "project_id": "sci_run_1",
        "project_context_fingerprint": "context-1",
        "evidence_bounded_writing": True,
        "subhypotheses": [
            {
                "sub_hypothesis_id": "SH1",
                "summary": "A bounded scientific question.",
                "required_slots": ["direct_observation"],
                "covered_slots": [],
                "background_only_slots": [],
                "missing_slots": ["direct_observation"],
                "slot_support": {
                    "direct_observation": {
                        "expected_evidence_role": "DIRECT_OBSERVATION",
                        "evidence_paper_ids": [],
                        "background_paper_ids": [],
                        "qualified_paper_ids": [],
                        "qualified_paper_constraints": {},
                    }
                },
                "relevant_clusters": [],
                "conclusion_admissibility": {"blockers": []},
                "limitations": {"blockers": []},
                "allowed_claim_modes": ["EVIDENCE_GAP_REPORT"],
                "forbidden_paper_ids": [],
                "direct_writing_blocked_paper_ids": [],
            }
        ],
    }
    generator.config = SimpleNamespace(
        BasicInfo=SimpleNamespace(
            save_path=str(tmp_path / "survey.md"),
            save_json_path=str(tmp_path / "survey.json"),
            base_dir=str(tmp_path),
            topic="Completed handoff survey",
            survey_run_id="20260826-120000-000003",
            debug=False,
            research_context={
                "input_fingerprint": "context-1",
                "domain": "Materials Science",
                "discovery_taxonomy": {
                    "status": "unresolved",
                    "requires_human_confirmation": True,
                },
            },
            subhypothesis_retrieval={},
            subhypothesis_decomposition={},
        )
    )

    artifacts = generator.save_survey("Survey body", [])

    assert artifacts["survey_manifest_status"] == "completed"
    assert Path(artifacts["survey_idea_handoff_path"]).is_file()
    assert verify_survey_manifest_artifacts(artifacts["survey_manifest_path"], base_dir=tmp_path) == []


def test_extract_json_accepts_trailing_explanation():
    assert extract_json('Result: {"action": "done"}\nFinished.') == {"action": "done"}


def test_revision_preserves_existing_markdown_heading():
    original = "### Existing heading\nOriginal paragraph."
    revision = {
        "action": "replace",
        "originalText": original,
        "newText": "### Existing heading\nImproved paragraph.",
    }

    assert apply_revision_to_text(original, revision) == revision["newText"]


def test_revision_rejects_markdown_heading_change():
    original = "### Existing heading\nOriginal paragraph."
    revision = {
        "action": "replace",
        "originalText": original,
        "newText": "### Changed heading\nImproved paragraph.",
    }

    with pytest.raises(ValueError, match="heading structure"):
        validate_revision_payload(original, revision)


def test_revision_requires_one_exact_match():
    with pytest.raises(ValueError, match="Could not find exact"):
        validate_revision_payload(
            "Current paragraph.",
            {
                "action": "replace",
                "originalText": "Paraphrased paragraph.",
                "newText": "Replacement.",
            },
        )

    with pytest.raises(ValueError, match="multiple locations"):
        validate_revision_payload(
            "Repeated. Repeated.",
            {
                "action": "replace",
                "originalText": "Repeated.",
                "newText": "Replacement.",
            },
        )


def test_section_revision_retries_with_validation_feedback():
    class _ChatAgent:
        model_name = "qwen3.6-flash"

        def __init__(self):
            self.calls = []
            self.responses = [
                '{"action":"replace","originalText":"Missing.","newText":"Ignored."}',
                '{"action":"replace","originalText":"Original.","newText":"Improved."}',
            ]

        def remote_chat(self, prompt, **kwargs):
            self.calls.append((prompt, kwargs))
            return self.responses.pop(0)

    chat_agent = _ChatAgent()
    revisor = object.__new__(AgenticRevisor)
    revisor.chat_agent = chat_agent
    revisor.database = SimpleNamespace(query_and_text=lambda *_args: "")
    revisor.section_revision_RAG_topk = 1
    revisor.section_revise_retry = 2
    revisor.section_revise_temperature = 0.5
    revisor.config = SimpleNamespace(BasicInfo=SimpleNamespace(debug=False))
    revisor.logger = _Logger()
    context = AgentContext(
        topic="Topic",
        survey_title="Survey",
        section_index=1,
        total_sections=1,
        section_title="Section",
        section_description="",
        current_section_text="Original.",
    )

    revised, result = revisor._call_revise(context, "Improve the paragraph.")

    assert revised == "Improved."
    assert result["action"] == "replace"
    assert "Could not find exact originalText" in chat_agent.calls[1][0]
    assert chat_agent.calls[0][1]["response_format"] == "json_object"
    assert chat_agent.calls[1][1]["temperature"] == 0.1


def test_non_agentic_reviews_accept_top_level_json_arrays():
    class _ChatAgent:
        model_name = "qwen3.6-flash"

        def __init__(self):
            self.calls = []

        def remote_chat(self, prompt, **kwargs):
            self.calls.append((prompt, kwargs))
            return '["Improve clarity."]'

    generator = object.__new__(SurveyGenerator)
    generator.chat_agent = _ChatAgent()
    generator.logger = _Logger()
    generator.config = SimpleNamespace(
        BasicInfo=SimpleNamespace(topic="Topic", debug=False),
        ModuleInfo=SimpleNamespace(
            SurveyGenerator=SimpleNamespace(
                include_env_report=False,
                include_code_report=False,
                section_least_words=None,
                section_review_retry=1,
                section_review_temperature=0.2,
            )
        ),
    )

    assert generator.review_section("Section text.") == ["Improve clarity."]
    assert generator.review_survey(
        "Survey text.",
        {"sections": []},
    ) == ["Improve clarity."]
    assert all("response_format" not in kwargs for _, kwargs in generator.chat_agent.calls)


def test_low_score_finish_executes_revise_operation():
    class _ChatAgent:
        model_name = "qwen3.6-flash"

        def remote_chat_with_retry(self, **_kwargs):
            return [
                {"operation": "review", "reason": "Review first"},
                {"operation": "finish", "reason": "Finish early"},
            ]

    class _RevisorHarness(AgenticRevisor):
        def _check_memory_compression(self, _agent_ctx):
            return False

        def _execute_operation(self, op, agent_ctx, full_survey_text=""):
            operation = op["operation"]
            if operation == "review":
                agent_ctx.review_scores = {"readability": 5, "depth": 5, "framework": 5}
                agent_ctx.current_suggestions = ["Apply the pending revision"]
                agent_ctx.has_reviewed = True
            elif operation == "revise":
                self.executed_revisions.append(op["input"])
            return operation, {"operation": operation, "result": "ok"}

    revisor = object.__new__(_RevisorHarness)
    revisor.config = SimpleNamespace(BasicInfo=SimpleNamespace(topic="Topic", debug=False))
    revisor.chat_agent = _ChatAgent()
    revisor.logger = _Logger()
    revisor.code_report = None
    revisor.include_code = False
    revisor.default_max_steps = 1
    revisor.executed_revisions = []

    revisor.agentic_revise_section(
        section_text="Original.",
        previous_section_text="",
        next_section_text="",
        section_outline={"title": "Section"},
        section_index=1,
        total_sections=1,
        max_steps=1,
    )

    assert revisor.executed_revisions == ["Apply the pending revision"]
