import os
import sys
import json
from types import SimpleNamespace

import pytest


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SURVEY_AGENT_ROOT = os.path.join(PROJECT_ROOT, "src", "agents", "survey_agent")
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, SURVEY_AGENT_ROOT)

from modules.survey_generator import (
    OUTLINE_EVIDENCE_PROMPT_SCHEMA_VERSION,
    OutlineGenerationError,
    SurveyGenerator,
)
from modules.pe import SURVEY_OUTLINE_GENERATION_PAPER_ASSIGNMENT
from src.pipeline.survey_evidence_plan import (
    EVIDENCE_BACKED_SYNTHESIS,
    QUALIFIED_SYNTHESIS,
    SURVEY_EVIDENCE_PLAN_SCHEMA_VERSION,
)


class _Logger:
    def __init__(self):
        self.messages = []

    def info(self, message, *args, **kwargs):
        self.messages.append(("info", message % args if args else message))

    def warning(self, message, *args, **kwargs):
        self.messages.append(("warning", message % args if args else message))

    def error(self, message, *args, **kwargs):
        self.messages.append(("error", message % args if args else message))


class _ChatAgent:
    def __init__(self, responses=()):
        self.responses = list(responses)
        self.calls = []

    def estimate_tokens(self, text):
        return len(text)

    def supports_response_format(self, response_format):
        return response_format == "json_object"

    def remote_chat(self, **kwargs):
        self.calls.append(kwargs)
        return self.responses.pop(0)


def _config(**overrides):
    values = {
        "outline_generation_draft_max_retry": 2,
        "outline_generation_draft_max_iterations": 2,
        "outline_generation_draft_empty_keynotes_iteration": 1,
        "outline_generation_draft_batch_size": 5,
        "outline_generation_assign_max_retry": 2,
        "outline_generation_assign_batch_size": 5,
        "outline_generation_max_retry": 1,
        "outline_generation_max_retry_in_generation_loop": 2,
        "outline_generation_batch_size": 5,
        "outline_generation_temperature": 0.0,
        "outline_draft_RAG_topk": 0,
        "outline_assign_RAG_topk": 0,
        "outline_RAG_topk": 0,
        "include_other_relevant_papers_RAG_in_outline": False,
        "llm_max_context_overhead_length_outline_generation": 10,
        "outline_prompt_max_input_tokens": 20_000,
        "outline_max_output_tokens": 100,
        "outline_evidence_plan_max_input_tokens": 5_000,
        "outline_current_outline_max_input_tokens": 1_000,
        "outline_keynotes_max_input_tokens": 100,
        "outline_analysis_max_input_tokens": 100,
        "outline_rag_max_input_tokens": 100,
        "outline_repair_previous_response_max_input_tokens": 1_000,
        "outline_repair_current_outline_max_input_tokens": 1_000,
        "outline_assign_fast_mode": False,
    }
    values.update(overrides)
    return SimpleNamespace(
        BasicInfo=SimpleNamespace(debug=False, error_conservatism_mode=False),
        APIInfo=SimpleNamespace(llm_max_context_length=25_000),
        ModuleInfo=SimpleNamespace(SurveyGenerator=SimpleNamespace(**values)),
    )


def _full_plan():
    candidate_marker = "CANDIDATE_GRAPH_PROVENANCE_MUST_NOT_REACH_PROMPT"
    return {
        "schema_version": SURVEY_EVIDENCE_PLAN_SCHEMA_VERSION,
        "evidence_bounded_writing": True,
        "writing_rules": {
            "all_subhypotheses_accounted_for": True,
            "graph_expanded_candidates_are_not_evidence": True,
            "background_context_is_not_direct_evidence": True,
        },
        "subhypotheses": [
            {
                "sub_hypothesis_id": "SH1",
                "summary": "Test evidence boundary.",
                "research_role": "PRIMARY_QUESTION",
                "required_slots": ["observation"],
                "covered_slots": ["observation"],
                "background_only_slots": [],
                "missing_slots": [],
                "slot_support": {
                    "observation": {
                        "expected_evidence_role": "DIRECT_OBSERVATION",
                        "evidence_paper_ids": ["W1"],
                        "qualified_paper_ids": [],
                        "background_paper_ids": [],
                        "minimum_evidence": "direct study",
                    }
                },
                "allowed_writing_mode": EVIDENCE_BACKED_SYNTHESIS,
                "allowed_claim_modes": [EVIDENCE_BACKED_SYNTHESIS],
                "evidence_paper_ids": ["W1"],
                "qualified_paper_ids": [],
                "context_paper_ids": [],
                "challenge_paper_ids": [],
                "paper_role_constraints": {
                    "W1": [
                        {
                            "evidence_use_mode": "DIRECT_LEDGER_EVIDENCE",
                            "allowed_support_kinds": ["DIRECT_LEDGER_EVIDENCE"],
                            "semantic_claim_limits": ["Stay within observation."],
                            "writing_direct_evidence_allowed": True,
                        }
                    ],
                    "W-graph-candidate": [
                        {
                            "evidence_use_mode": "GRAPH_EXPANDED_CANDIDATE_ONLY",
                            "semantic_claim_limits": [candidate_marker] * 100,
                            "writing_direct_evidence_allowed": False,
                        }
                    ],
                },
                "limitations": {
                    "blockers": [],
                    "scope_rejection_count": 100,
                    "scope_rejections": [{"reason": candidate_marker}] * 100,
                },
                "relevant_clusters": [
                    {"candidate_paper_ids": ["W-graph-candidate"]}
                ],
            }
        ],
    }


def _generator(*, plan=None, responses=(), **config_overrides):
    generator = object.__new__(SurveyGenerator)
    generator.logger = _Logger()
    generator.chat_agent = _ChatAgent(responses)
    generator.config = _config(**config_overrides)
    generator.survey_evidence_plan = plan if plan is not None else {}
    generator.database = SimpleNamespace(query_and_text=lambda **_kwargs: "")
    generator.work_analyzer = SimpleNamespace()
    generator.outline_fast_mode = False
    generator.omit_error_preserve_retry_time = 0
    return generator


def _valid_outline():
    return {
        "title": "Survey",
        "sections": [
            {
                "title": "Evidence",
                "description": "Synthesizes admitted evidence.",
                "subsections": [
                    {
                        "title": "Observation",
                        "description": "Explains the direct observation.",
                    }
                ],
            }
        ],
    }


def test_outline_prompt_uses_compact_evidence_projection_not_graph_audit_payload():
    generator = _generator(plan=_full_plan())

    prompt_plan = generator._survey_evidence_plan_prompt()

    assert OUTLINE_EVIDENCE_PROMPT_SCHEMA_VERSION in prompt_plan
    assert '"W1"' in prompt_plan
    assert "W-graph-candidate" not in prompt_plan
    assert "CANDIDATE_GRAPH_PROVENANCE_MUST_NOT_REACH_PROMPT" not in prompt_plan
    assert "scope_rejections" not in prompt_plan
    assert generator.survey_evidence_plan["subhypotheses"][0][
        "paper_role_constraints"
    ]["W-graph-candidate"]


def test_outline_prompt_projects_only_representatives_with_qualified_limits():
    plan = _full_plan()
    entry = plan["subhypotheses"][0]
    entry["slot_support"]["qualified_observation"] = {
        "expected_evidence_role": "QUALIFIED_OBSERVATION",
        "evidence_paper_ids": [],
        "qualified_paper_ids": ["W2"],
        "background_paper_ids": [],
        "qualified_paper_constraints": {
            "W2": [
                {
                    "semantic_claim_limits": [
                        "Do not generalize beyond the measured population."
                    ]
                }
            ]
        },
    }
    entry["covered_slots"].append("qualified_observation")
    entry["qualified_paper_ids"] = ["W2"]
    entry["allowed_writing_mode"] = QUALIFIED_SYNTHESIS
    entry["paper_role_constraints"]["W2"] = [
        {"semantic_claim_limits": ["Use qualified wording."]}
    ]

    generator = _generator(plan=plan)
    generator.work_analyzer = SimpleNamespace(
        get_paper_keynote=lambda paper_id: {
            "summary": f"{paper_id} keynote " * 200,
        },
        work_collector=SimpleNamespace(
            get_paper_title=lambda paper_id: f"Title for {paper_id}"
        ),
    )

    prompt_plan = json.loads(
        generator._survey_evidence_plan_prompt(
            representative_paper_ids=["W1", "W2"]
        )
    )
    sh1 = prompt_plan["subhypotheses"][0]
    evidence = sh1["representative_evidence"]

    assert prompt_plan["projection_scope"] == "outline_representative_evidence_only"
    assert prompt_plan["selected_representative_paper_ids"] == ["W1", "W2"]
    assert {(item["paper_id"], item["evidence_role"]) for item in evidence} == {
        ("W1", "direct"),
        ("W2", "qualified"),
    }
    qualified = next(item for item in evidence if item["paper_id"] == "W2")
    assert qualified["covered_slots"] == ["qualified_observation"]
    assert "measured population" in qualified["limitation_summary"]
    assert qualified["title"] == "Title for W2"
    assert len(qualified["keynote_summary"]) <= 700
    brief = generator._outline_paper_brief("W2")
    assert "Keynote summary:" in brief
    assert "W2 keynote W2 keynote" in brief
    assert len(brief) < 800

    serialized = json.dumps(prompt_plan, ensure_ascii=False)
    assert "W-graph-candidate" not in serialized
    assert "scope_rejections" not in serialized
    assert "paper_role_constraints" not in serialized
    # The complete audit plan remains untouched and still contains its graph
    # candidate record for later provenance and claim-trace checks.
    assert "W-graph-candidate" in generator.survey_evidence_plan["subhypotheses"][0][
        "paper_role_constraints"
    ]


def test_outline_representative_projection_reports_missing_writable_slot_as_gap():
    generator = _generator(plan=_full_plan())

    prompt_plan = json.loads(
        generator._survey_evidence_plan_prompt(
            representative_paper_ids=["W-not-admitted"]
        )
    )

    sh1 = prompt_plan["subhypotheses"][0]
    assert sh1["representative_evidence"] == []
    assert sh1["representative_evidence_gaps"] == [
        {
            "slot_name": "observation",
            "instruction": (
                "State explicitly that this slot lacks selected representative evidence; "
                "do not make a substantive claim about it."
            ),
        }
    ]
    assert (
        prompt_plan["writing_rules"][
            "representative_evidence_gaps_must_be_reported_without_assertive_claims"
        ]
        is True
    )


def test_outline_representative_projection_makes_endpoint_gap_explicit():
    plan = _full_plan()
    entry = plan["subhypotheses"][0]
    entry["required_slots"].append("comparable_endpoint")
    entry["background_only_slots"].append("comparable_endpoint")
    entry["slot_support"]["comparable_endpoint"] = {
        "expected_evidence_role": "COMPARATIVE_OR_MEASUREMENT_EVIDENCE",
        "evidence_paper_ids": [],
        "qualified_paper_ids": [],
        "background_paper_ids": ["W-endpoint"],
    }
    entry["context_paper_ids"] = ["W-endpoint"]

    generator = _generator(plan=plan)
    prompt_plan = json.loads(
        generator._survey_evidence_plan_prompt(
            representative_paper_ids=["W-not-admitted"]
        )
    )

    gaps = prompt_plan["subhypotheses"][0]["representative_evidence_gaps"]
    assert {
        (gap["slot_name"], gap["instruction"])
        for gap in gaps
    } == {
        (
            "observation",
            "State explicitly that this slot lacks selected representative evidence; "
            "do not make a substantive claim about it.",
        ),
        (
            "comparable_endpoint",
            "State explicitly that the selected evidence does not support a "
            "comparable endpoint; do not draw a cross-model endpoint comparison.",
        ),
    }


def test_outline_builder_caps_components_before_the_request_is_made():
    generator = _generator(plan=_full_plan())

    prompt, breakdown = generator._build_outline_prompt(
        template=(
            "plan={survey_evidence_plan}\noutline={current_outline}\n"
            "keynotes={paper_keynotes}\nanalysis={papers_analysis}\n"
            "rag={other_relevant_papers}"
        ),
        phase="test",
        paper_keynotes="k" * 10_000,
        current_outline={"sections": []},
        papers_analysis="a" * 10_000,
        other_relevant_papers="r" * 10_000,
    )

    assert breakdown["paper_keynotes"] <= 100
    assert breakdown["papers_analysis"] <= 100
    assert breakdown["other_relevant_papers"] <= 100
    assert breakdown["total"] <= breakdown["budget"]
    assert "CANDIDATE_GRAPH_PROVENANCE_MUST_NOT_REACH_PROMPT" not in prompt


def test_outline_retry_uses_short_repair_prompt_and_json_mode():
    generator = _generator(
        plan=_full_plan(),
        responses=['{"title":"missing sections"}', __import__("json").dumps(_valid_outline())],
    )
    generator._bounded_writing_analysis = lambda *_args: ""

    outline = generator.generate_outline_draft_outline([], "", [], retry=1)

    assert outline == _valid_outline()
    assert len(generator.chat_agent.calls) == 2
    first, second = generator.chat_agent.calls
    assert first["response_format"] == "json_object"
    assert first["strict_input_budget"] is True
    assert "Repair a survey outline response" in second["text_content"]
    assert "Outline must have a 'sections' field of type list" in second["text_content"]
    assert second["response_format"] == "json_object"


def test_invalid_draft_cannot_fall_through_to_none_type_assignment():
    generator = _generator(
        plan=_full_plan(),
        responses=['{"title":"missing sections"}', '{"title":"still missing"}'],
    )
    generator._bounded_writing_analysis = lambda *_args: ""
    generator.generate_outline_assign_papers = lambda *_args, **_kwargs: pytest.fail(
        "paper assignment must not run after an invalid outline"
    )

    with pytest.raises(OutlineGenerationError, match="exhausted retries"):
        generator.generate_outline_in_steps([], "", [], retry=1)


def test_assignment_requires_object_schema_and_rejects_invalid_outline_early():
    generator = _generator(plan=_full_plan())

    assert generator._parse_outline_assignments(
        '{"assignments":[{"paper_id":"W1","assignment":{}}]}'
    ) == [{"paper_id": "W1", "assignment": {}}]
    with pytest.raises(OutlineGenerationError, match="draft outline is invalid"):
        generator.generate_outline_assign_papers({}, [], "", [], retry=1)


def test_assignment_prompt_explicitly_requires_one_json_object():
    assert "Return exactly one valid json object." in SURVEY_OUTLINE_GENERATION_PAPER_ASSIGNMENT
    assert (
        "Do not use Markdown fences, prose, or any text outside the json object."
        in SURVEY_OUTLINE_GENERATION_PAPER_ASSIGNMENT
    )


def test_outline_representatives_cover_every_available_slot_before_optional_caps():
    plan = _full_plan()
    first = plan["subhypotheses"][0]
    first["slot_support"]["observation"]["evidence_paper_ids"] = [
        "W1",
        "W1-extra",
    ]
    first["evidence_paper_ids"] = ["W1", "W1-extra"]
    first["slot_support"]["qualified"] = {
        "expected_evidence_role": "QUALIFIED_OBSERVATION",
        "evidence_paper_ids": [],
        "qualified_paper_ids": ["W2"],
        "background_paper_ids": [],
    }
    first["qualified_paper_ids"] = ["W2"]
    second = {
        **first,
        "sub_hypothesis_id": "SH2",
        "slot_support": {
            "measurement": {
                "expected_evidence_role": "DIRECT_MEASUREMENT",
                "evidence_paper_ids": ["W3"],
                "qualified_paper_ids": [],
                "background_paper_ids": [],
            }
        },
        "evidence_paper_ids": ["W3"],
        "qualified_paper_ids": [],
    }
    plan["subhypotheses"].append(second)
    generator = _generator(
        plan=plan,
        outline_representative_papers_per_sh=1,
        outline_representative_max_papers=1,
    )

    selected = generator._select_outline_representative_paper_ids(
        ["W1", "W1-extra", "W2", "W3", "W4"]
    )

    # The soft global cap never removes the only available representative for
    # an SH evidence slot; optional comparison papers are what get capped.
    assert selected[:3] == ["W1", "W2", "W3"]
    assert "W1-extra" not in selected
    assert "W4" not in selected


def test_outline_shape_and_draft_length_budgets_are_concise_and_total_safe():
    generator = _generator(
        outline_min_sections=2,
        outline_target_sections=2,
        outline_max_sections=2,
        outline_min_subsections_per_section=1,
        outline_target_subsections_per_section=2,
        outline_max_subsections_per_section=2,
        survey_target_words=1_000,
        survey_max_words=1_200,
        subsection_target_min_words=100,
        subsection_target_max_words=400,
        section_preamble_target_words=50,
        section_preamble_max_words=60,
        subsection_target_citations=2,
        subsection_max_citations=3,
    )
    outline = {
        "title": "Survey",
        "sections": [
            {
                "title": "A",
                "description": "A.",
                "subsections": [
                    {"title": "A1", "description": "A1."},
                    {"title": "A2", "description": "A2."},
                ],
            },
            {
                "title": "B",
                "description": "B.",
                "subsections": [
                    {"title": "B1", "description": "B1."},
                    {"title": "B2", "description": "B2."},
                ],
            },
        ],
    }

    budget = generator._survey_length_budget(outline)
    valid, reason = generator.validate_outline_format(outline)

    assert valid, reason
    assert budget["subsection_target_words"] <= budget["subsection_max_words"]
    assert (
        budget["section_count"] * budget["section_preamble_max_words"]
        + budget["subsection_count"] * budget["subsection_max_words"]
        <= budget["survey_max_words"]
    )
    prompt_budget = generator._outline_size_budget_prompt()
    assert "about 1000 words" in prompt_budget
    assert "2-2 sections" in prompt_budget


def test_outline_shape_rejects_proliferating_subsections():
    generator = _generator(
        outline_min_sections=1,
        outline_max_sections=2,
        outline_min_subsections_per_section=1,
        outline_max_subsections_per_section=2,
    )
    outline = _valid_outline()
    outline["sections"][0]["subsections"].append(
        {"title": "Too many", "description": "Would exceed the budget."}
    )
    outline["sections"][0]["subsections"].append(
        {"title": "Still too many", "description": "Would exceed the budget."}
    )

    valid, reason = generator.validate_outline_format(outline)

    assert not valid
    assert "no more than 2 subsections" in reason


def test_overlong_revisions_fall_back_to_the_budgeted_section_without_truncation():
    generator = _generator(
        survey_target_words=1_000,
        survey_max_words=1_000,
        outline_target_sections=2,
    )
    outline = {
        "sections": [
            {"title": "A", "subsections": [{"title": "A1"}]},
            {"title": "B", "subsections": [{"title": "B1"}]},
        ]
    }
    originals = ["original first section", "original second section"]
    revised = ["word " * 501, "concise revised second section"]

    bounded = generator._keep_revised_sections_within_budget(
        originals, revised, outline
    )

    assert bounded == [originals[0], revised[1]]
