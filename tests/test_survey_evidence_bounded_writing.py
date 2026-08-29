import json
import os
import sys
from types import SimpleNamespace

import pytest
from omegaconf import OmegaConf


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SURVEY_AGENT_ROOT = os.path.join(PROJECT_ROOT, "src", "agents", "survey_agent")
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, SURVEY_AGENT_ROOT)

from modules.pe import (
    SECTION_DRAFT,
    SUBSECTION_DRAFT,
    SUBSECTION_DRAFT_WITH_CODE,
    SURVEY_CLAIM_TRACE_REPAIR,
    SURVEY_OUTLINE_GENERATION,
    SURVEY_OUTLINE_GENERATION_OUTLINE_DRAFT,
    SURVEY_OUTLINE_GENERATION_PAPER_ASSIGNMENT,
)
from modules.survey_generator import SurveyGenerator
from src.pipeline.survey_evidence_plan import (
    EVIDENCE_BACKED_SYNTHESIS,
    QUALIFIED_SYNTHESIS,
    SURVEY_EVIDENCE_PLAN_SCHEMA_VERSION,
    build_survey_evidence_plan,
)
from src.pipeline.paper_identity import canonical_paper_id, canonical_paper_ids
from src.pipeline.sh_graph_provenance import (
    GRAPH_EXPANDED_CANDIDATE_ONLY,
    QUALIFIED_SH_CONTRIBUTION,
    build_graph_expansion_annotations,
    build_seed_annotation_index,
)


class _Logger:
    def info(self, *_args, **_kwargs):
        pass

    def warning(self, *_args, **_kwargs):
        pass

    def error(self, *_args, **_kwargs):
        pass


def _plan() -> dict:
    return {
        "schema_version": SURVEY_EVIDENCE_PLAN_SCHEMA_VERSION,
        "project_id": "sci_project",
        "project_context_fingerprint": "context-A",
        "evidence_bounded_writing": True,
        "subhypotheses": [
            {
                "sub_hypothesis_id": "SH1",
                "allowed_writing_mode": EVIDENCE_BACKED_SYNTHESIS,
                "allowed_claim_modes": [EVIDENCE_BACKED_SYNTHESIS],
                "evidence_paper_ids": ["W1"],
                "context_paper_ids": ["W-context"],
                "covered_slots": ["direct_observation"],
                "background_only_slots": [],
                "missing_slots": [],
                "slot_support": {
                    "direct_observation": {
                        "expected_evidence_role": "DIRECT_OBSERVATION",
                        "evidence_paper_ids": ["W1"],
                        "background_paper_ids": [],
                    }
                },
            }
        ],
    }


def _generator() -> SurveyGenerator:
    generator = object.__new__(SurveyGenerator)
    generator.logger = _Logger()
    generator.survey_evidence_plan = _plan()
    generator.config = SimpleNamespace(BasicInfo=SimpleNamespace(base_dir=""))
    generator.use_title_in_draft = False
    return generator


def test_openalex_aliases_are_canonicalized_before_evidence_plan_filtering() -> None:
    """A URL-form ledger ID must admit the same cached ``W...`` paper."""

    generator = _generator()
    entry = generator.survey_evidence_plan["subhypotheses"][0]
    openalex_url = "https://api.openalex.org/works/W100"
    entry["evidence_paper_ids"] = [openalex_url]
    entry["slot_support"]["direct_observation"]["evidence_paper_ids"] = [
        openalex_url
    ]
    entry["paper_role_constraints"] = {
        openalex_url: [
            {
                "evidence_use_mode": "DIRECT_LEDGER_EVIDENCE",
                "allowed_support_kinds": ["DIRECT_LEDGER_EVIDENCE"],
            }
        ]
    }

    assert canonical_paper_id(openalex_url) == "W100"
    assert canonical_paper_ids([openalex_url, "W100"]) == ["W100"]
    assert generator._permitted_evidence_plan_paper_ids() == {"W100", "W-context"}
    assert generator._bounded_writing_paper_ids(
        ["W100", openalex_url, "W-candidate"]
    ) == ["W100"]

    claim_text = "The observation supports the relation <Paper ID: W100>."
    claim = {
        "claim_text": claim_text,
        "sub_hypothesis_ids": ["SH1"],
        "claim_mode": EVIDENCE_BACKED_SYNTHESIS,
        "evidence_paths": [
            {
                "sub_hypothesis_id": "SH1",
                "slot_name": "direct_observation",
                "paper_id": openalex_url,
                "support_kind": "DIRECT_LEDGER_EVIDENCE",
                "evidence_role": "DIRECT_OBSERVATION",
            }
        ],
        "limitation_slots": [],
    }
    assert generator._validate_claim_trace(claim_text, [claim]) == []


def test_bounded_claim_trace_requires_verbatim_claim_slot_and_direct_paper() -> None:
    generator = _generator()
    response = (
        "The direct observation supports the stated relation <Paper ID: W1>.\n\n"
        "[[SH_CLAIM_TRACE]]\n"
        '{"claims":[{"claim_text":"The direct observation supports the stated relation <Paper ID: W1>.",'
        '"sub_hypothesis_ids":["SH1"],"claim_mode":"EVIDENCE_BACKED_SYNTHESIS",'
        '"evidence_paths":[{"sub_hypothesis_id":"SH1","slot_name":"direct_observation",'
        '"paper_id":"W1","support_kind":"DIRECT_LEDGER_EVIDENCE","evidence_role":"DIRECT_OBSERVATION"}],'
        '"limitation_slots":[]}]}'
        "\n[[/SH_CLAIM_TRACE]]"
    )

    visible_text, claims, parse_errors = generator._extract_claim_trace(response)

    assert parse_errors == []
    assert "SH_CLAIM_TRACE" not in visible_text
    assert generator._validate_claim_trace(visible_text, claims) == []


def test_trace_normalization_uses_sentence_index_and_derives_plan_fields() -> None:
    generator = _generator()
    visible_text = (
        "The direct observation—supports the stated relation <Paper ID: W1>. "
        "A separate sentence provides context."
    )
    minimal_claim = {
        "claim_index": 1,
        "claim_anchor": "direct observation supports",
        # This deliberately omits the em dash and terminal punctuation.  The
        # persisted trace must nevertheless use the exact reader-visible text.
        "claim_text": "The direct observation supports the stated relation <Paper ID: W1>",
        "sub_hypothesis_ids": ["SH1"],
        "claim_mode": EVIDENCE_BACKED_SYNTHESIS,
        "evidence_paths": [
            {
                "sub_hypothesis_id": "SH1",
                "slot_name": "direct_observation",
                "paper_id": "W1",
            }
        ],
    }

    claims, errors = generator._normalize_and_derive_claim_trace(
        visible_text,
        [minimal_claim],
    )

    assert errors == []
    assert claims[0]["claim_text"] == (
        "The direct observation—supports the stated relation <Paper ID: W1>."
    )
    assert claims[0]["evidence_paths"] == [
        {
            "sub_hypothesis_id": "SH1",
            "slot_name": "direct_observation",
            "paper_id": "W1",
            "support_kind": "DIRECT_LEDGER_EVIDENCE",
            "evidence_role": "DIRECT_OBSERVATION",
        }
    ]
    assert claims[0]["limitation_slots"] == []
    assert generator._validate_claim_trace(visible_text, claims) == []


def test_trace_normalization_derives_qualified_limitation_slot() -> None:
    generator = _generator()
    entry = generator.survey_evidence_plan["subhypotheses"][0]
    entry["allowed_writing_mode"] = QUALIFIED_SYNTHESIS
    entry["allowed_claim_modes"] = [QUALIFIED_SYNTHESIS]
    entry["slot_support"]["direct_observation"]["evidence_paper_ids"] = []
    entry["slot_support"]["direct_observation"]["qualified_paper_ids"] = ["WQ"]
    entry["qualified_paper_ids"] = ["WQ"]
    visible_text = "The qualified finding is limited <Paper ID: WQ>."

    claims, errors = generator._normalize_and_derive_claim_trace(
        visible_text,
        [
            {
                "claim_index": 1,
                "sub_hypothesis_ids": ["SH1"],
                "claim_mode": QUALIFIED_SYNTHESIS,
                "evidence_paths": [
                    {
                        "sub_hypothesis_id": "SH1",
                        "slot_name": "direct_observation",
                        "paper_id": "WQ",
                    }
                ],
            }
        ],
    )

    assert errors == []
    assert claims[0]["evidence_paths"][0]["support_kind"] == QUALIFIED_SH_CONTRIBUTION
    assert claims[0]["limitation_slots"] == ["direct_observation"]
    assert generator._validate_claim_trace(visible_text, claims) == []


def test_trace_repair_preserves_prose_and_repairs_minimal_json_only() -> None:
    class _TraceRepairChat:
        def __init__(self):
            self.prompts = []

        def batch_remote_chat(self, prompts, **_kwargs):
            self.prompts.extend(prompts)
            return [
                '{"claims":[{"claim_index":1,"claim_anchor":"direct observation",'
                '"sub_hypothesis_ids":["SH1"],'
                '"claim_mode":"EVIDENCE_BACKED_SYNTHESIS",'
                '"evidence_paths":[{"sub_hypothesis_id":"SH1",'
                '"slot_name":"direct_observation","paper_id":"W1"}]}]}'
            ]

    generator = _generator()
    generator.chat_agent = _TraceRepairChat()
    generator.config = SimpleNamespace(
        BasicInfo=SimpleNamespace(base_dir=""),
        ModuleInfo=SimpleNamespace(
            SurveyGenerator=SimpleNamespace(
                claim_trace_repair_max_attempts=2,
                claim_trace_repair_max_output_tokens=128,
            )
        ),
    )
    visible_text = "The direct observation supports the stated relation <Paper ID: W1>."

    repaired, failures = generator._repair_claim_traces(
        [
            {
                "draft_index": 4,
                "visible_draft": visible_text,
                "trace_errors": ["Expected exactly one [[SH_CLAIM_TRACE]] JSON block."],
            }
        ],
        stage="subsection",
    )

    assert failures == {}
    assert repaired[4][0]["claim_text"] == visible_text
    assert repaired[4][0]["evidence_paths"][0]["evidence_role"] == "DIRECT_OBSERVATION"
    assert len(generator.chat_agent.prompts) == 1
    assert visible_text in generator.chat_agent.prompts[0]
    assert "Return exactly this minimal JSON schema" in generator.chat_agent.prompts[0]
    assert "support_kind" not in SURVEY_CLAIM_TRACE_REPAIR.split("Return exactly this minimal JSON schema:", 1)[1].split("Rules:", 1)[0]


def test_bounded_empty_trace_is_rejected_for_untraced_bounded_writing() -> None:
    generator = _generator()
    response = (
        "This section introduces the organization of the survey.\n\n"
        "[[SH_CLAIM_TRACE]]\n{\"claims\": []}\n[[/SH_CLAIM_TRACE]]"
    )

    visible_text, claims, parse_errors = generator._extract_claim_trace(response)

    assert parse_errors == []
    assert claims == []
    assert "requires at least one SH claim trace" in generator._validate_claim_trace(
        visible_text, claims
    )[0]


def test_bounded_claim_trace_rejects_graph_candidate_as_direct_evidence() -> None:
    generator = _generator()
    response = (
        "The direct observation supports the stated relation <Paper ID: W-candidate>.\n\n"
        "[[SH_CLAIM_TRACE]]\n"
        '{"claims":[{"claim_text":"The direct observation supports the stated relation <Paper ID: W-candidate>.",'
        '"sub_hypothesis_ids":["SH1"],"claim_mode":"EVIDENCE_BACKED_SYNTHESIS",'
        '"evidence_paths":[{"sub_hypothesis_id":"SH1","slot_name":"direct_observation",'
        '"paper_id":"W-candidate","support_kind":"DIRECT_LEDGER_EVIDENCE","evidence_role":"DIRECT_OBSERVATION"}],'
        '"limitation_slots":[]}]}'
        "\n[[/SH_CLAIM_TRACE]]"
    )
    visible_text, claims, parse_errors = generator._extract_claim_trace(response)

    assert parse_errors == []
    assert "does not directly cover this SH slot" in generator._validate_claim_trace(
        visible_text, claims
    )[0]


def test_semantic_exploration_root_is_qualified_but_its_graph_descendant_is_not() -> None:
    """E2E: preserve an exploration root's role without promoting its lineage."""

    ledger = {
        "schema_version": "evidence_coverage_ledger_v1",
        "project_id": "sci_project",
        "project_context_fingerprint": "context-A",
        "subhypotheses": [
            {
                "sub_hypothesis_id": "SH1",
                "question": "Does the direct relation hold?",
                "question_kind": "EMPIRICAL_COVERAGE",
                "required_slots": ["direct_observation"],
                "slot_ledger": {
                    "direct_observation": {
                        "task_id": "SH1.direct_observation",
                        "slot_name": "direct_observation",
                        "expected_evidence_role": "DIRECT_OBSERVATION",
                        "minimum_evidence": "direct study",
                        "admission_rule": "scope and role verified",
                        "covered_by": [],
                        "background_only_by": [],
                        "scope_rejections": [],
                    }
                },
                "covered_slots": [],
                "background_only_slots": [],
                "missing_slots": ["direct_observation"],
                "conclusion_admissibility": {
                    "admissible": False,
                    "blockers": ["missing_required_slot:direct_observation"],
                },
            }
        ],
    }
    semantic_assessment = {
        "sub_hypothesis_id": "SH1",
        "assessment_status": "assessed",
        "semantic_relevance_score": 5,
        "overall_relation": "partial",
        "contribution_types": ["PARTIAL_EVIDENCE", "MECHANISTIC_EVIDENCE"],
        "candidate_slot_contributions": [
            {
                "slot_name": "direct_observation",
                "support_level": "partial",
                "reason": "Tests one component but not the complete relation.",
            }
        ],
        "claim_limits": ["Does not establish the full relation."],
    }
    root_paper = {
        "paperId": "W-root",
        "sh_semantic_assessments": [semantic_assessment],
        "sh_matches": [
            {
                "sub_hypothesis_id": "SH1",
                "semantic_assessment": semantic_assessment,
                "slot_assessments": [
                    {
                        "admission_status": "PARTIAL_OR_INDIRECT_ONLY",
                        "graph_value_status": "EXPAND",
                    }
                ],
            }
        ],
        "seed_selection": {
            "selected": True,
            "seed_kind": "exploration_seed",
            "graph_expansion_mode": "bounded_exploration",
            "selection_basis": "llm_sh_semantic_assessment",
            "semantic_assessment_ids": ["SH1"],
        },
    }
    root_annotations = build_seed_annotation_index(
        [root_paper],
        ledger,
        project_id="sci_project",
        project_context_fingerprint="context-A",
    )["W-root"]
    root = root_annotations[0]
    expanded = build_graph_expansion_annotations(
        root_annotations,
        parent_paper_id="W-root",
        root_seed_paper_id="W-root",
        lineage_depth=1,
        citation_direction="out",
    )[0]

    assert root["evidence_use_mode"] == QUALIFIED_SH_CONTRIBUTION
    assert root["admission_status"] == "PARTIAL_OR_INDIRECT_ONLY"
    assert root["semantic_slot_contributions"] == [
        {
            "slot_name": "direct_observation",
            "support_level": "partial",
            "reason": "Tests one component but not the complete relation.",
        }
    ]
    assert expanded["evidence_use_mode"] == GRAPH_EXPANDED_CANDIDATE_ONLY
    assert expanded["admission_status"] == "NOT_EVALUATED_AS_DIRECT_EVIDENCE"
    assert expanded["semantic_slot_contributions"] == []
    assert expanded["root_evidence_use_mode"] == QUALIFIED_SH_CONTRIBUTION
    assert expanded["root_semantic_overall_relation"] == "partial"

    plan = build_survey_evidence_plan(
        provenance_artifact={
            "schema_version": "sh_graph_provenance_v1",
            "project_id": "sci_project",
            "project_context_fingerprint": "context-A",
            "paper_annotations": {"W-root": root_annotations, "W-expanded": [expanded]},
            "graph_expansion_records": [],
        },
        coverage_ledger=ledger,
        cluster_coverage_artifact={
            "schema_version": "sh_cluster_coverage_projection_v1",
            "project_id": "sci_project",
            "project_context_fingerprint": "context-A",
            "clusters": [
                {
                    "cluster_index": 1,
                    "cluster_name": "exploration cluster",
                    "subhypotheses": [
                        {
                            "sub_hypothesis_id": "SH1",
                            "cluster_evidence_state": "EXPLORATION_ONLY",
                            "evidence_paper_ids": [],
                            "background_paper_ids": [],
                            "graph_expanded_candidate_paper_ids": ["W-expanded"],
                            "seed_candidate_paper_ids": ["W-root"],
                            "cluster_covered_slots": [],
                            "cluster_background_slots": [],
                            "cluster_uncovered_required_slots": ["direct_observation"],
                        }
                    ],
                }
            ],
        },
        subhypothesis_contracts=[
            {
                "sub_hypothesis_id": "SH1",
                "question_kind": "EMPIRICAL_COVERAGE",
                "required_slots": ["direct_observation"],
                "research_role": "PRIMARY_QUESTION",
                "challenge_target": "",
            }
        ],
    )
    entry = plan["subhypotheses"][0]
    assert entry["allowed_writing_mode"] == QUALIFIED_SYNTHESIS
    assert entry["slot_support"]["direct_observation"]["qualified_paper_ids"] == [
        "W-root"
    ]
    assert entry["forbidden_paper_ids"] == ["W-expanded"]
    assert entry["paper_role_constraints"]["W-root"][0][
        "evidence_use_mode"
    ] == QUALIFIED_SH_CONTRIBUTION
    assert entry["paper_role_constraints"]["W-expanded"][0][
        "evidence_use_mode"
    ] == GRAPH_EXPANDED_CANDIDATE_ONLY

    generator = _generator()
    generator.survey_evidence_plan = plan
    claim_text = "The result offers partial support for the relation <Paper ID: W-root>."
    qualified_claim = {
        "claim_text": claim_text,
        "sub_hypothesis_ids": ["SH1"],
        "claim_mode": QUALIFIED_SYNTHESIS,
        "evidence_paths": [
            {
                "sub_hypothesis_id": "SH1",
                "slot_name": "direct_observation",
                "paper_id": "W-root",
                "support_kind": QUALIFIED_SH_CONTRIBUTION,
                "evidence_role": "DIRECT_OBSERVATION",
            }
        ],
        "limitation_slots": ["direct_observation"],
    }
    assert generator._validate_claim_trace(claim_text, [qualified_claim]) == []

    direct_upgrade = {
        **qualified_claim,
        "evidence_paths": [
            {
                **qualified_claim["evidence_paths"][0],
                "support_kind": "DIRECT_LEDGER_EVIDENCE",
            }
        ],
    }
    assert any(
        "provenance role does not permit DIRECT_LEDGER_EVIDENCE" in error
        for error in generator._validate_claim_trace(claim_text, [direct_upgrade])
    )

    expanded_claim_text = "A graph neighbor proves the relation <Paper ID: W-expanded>."
    expanded_upgrade = {
        **qualified_claim,
        "claim_text": expanded_claim_text,
        "evidence_paths": [
            {
                **qualified_claim["evidence_paths"][0],
                "paper_id": "W-expanded",
            }
        ],
    }
    assert any(
        "graph/holdout candidate" in error
        for error in generator._validate_claim_trace(expanded_claim_text, [expanded_upgrade])
    )


def test_bounded_claim_trace_requires_the_exact_slot_paper_path_and_visible_citation() -> None:
    generator = _generator()
    generator.survey_evidence_plan["subhypotheses"][0]["slot_support"][
        "mechanistic_evidence"
    ] = {
        "expected_evidence_role": "MECHANISTIC_EVIDENCE",
        "evidence_paper_ids": ["W-mechanism"],
        "background_paper_ids": [],
    }
    generator.survey_evidence_plan["subhypotheses"][0]["covered_slots"].append(
        "mechanistic_evidence"
    )
    response = (
        "The direct observation supports the stated relation <Paper ID: W-mechanism>.\n\n"
        "[[SH_CLAIM_TRACE]]\n"
        '{"claims":[{"claim_text":"The direct observation supports the stated relation <Paper ID: W-mechanism>.",'
        '"sub_hypothesis_ids":["SH1"],"claim_mode":"EVIDENCE_BACKED_SYNTHESIS",'
        '"evidence_paths":[{"sub_hypothesis_id":"SH1","slot_name":"direct_observation",'
        '"paper_id":"W-mechanism","support_kind":"DIRECT_LEDGER_EVIDENCE","evidence_role":"DIRECT_OBSERVATION"}],'
        '"limitation_slots":[]}]}'
        "\n[[/SH_CLAIM_TRACE]]"
    )

    visible_text, claims, parse_errors = generator._extract_claim_trace(response)

    assert parse_errors == []
    assert "does not directly cover this SH slot" in generator._validate_claim_trace(
        visible_text, claims
    )[0]

    claims[0]["evidence_paths"][0]["paper_id"] = "W1"
    assert "paper_id must be cited in claim_text" in generator._validate_claim_trace(
        visible_text, claims
    )[-1]


def test_bounded_writing_context_filters_candidates_and_unassessed_analysis() -> None:
    generator = _generator()

    assert generator._bounded_writing_paper_ids(["W1", "W-context", "W-candidate"]) == [
        "W1",
        "W-context",
    ]
    assert generator._bounded_writing_analysis(
        [[{"question": "candidate", "answer": "candidate result", "related_papers": ["W-candidate"]}]],
        "candidate conclusion",
    ) == ""
    assert generator._bounded_writing_code_report("W-candidate code conclusion") == ""


def test_survey_evidence_plan_source_rejects_mismatched_retrieval_project_identity() -> None:
    generator = _generator()
    generator.survey_evidence_plan = {}
    provenance = {
        "schema_version": "sh_graph_provenance_v1",
        "project_id": "sci_project",
        "project_context_fingerprint": "context-A",
    }
    generator.work_analyzer = SimpleNamespace(
        sh_cluster_coverage_artifact={
            "schema_version": "sh_cluster_coverage_projection_v1",
            "project_id": "sci_project",
            "project_context_fingerprint": "context-A",
        },
        work_collector=SimpleNamespace(
            sh_graph_provenance_artifact=provenance,
            subhypothesis_retrieval_artifact={
                "project_id": "sci_other",
                "project_context_fingerprint": "context-A",
                "plan": {
                    "project_context": {"project_context_fingerprint": "context-A"},
                    "subhypotheses": [],
                },
            },
        ),
    )

    with pytest.raises(ValueError, match="mismatched SH provenance"):
        generator._survey_evidence_plan_sources()


def test_prepare_survey_evidence_plan_uses_builder_keyword_contract(monkeypatch) -> None:
    generator = _generator()
    generator.survey_evidence_plan = {}
    provenance = {
        "schema_version": "sh_graph_provenance_v1",
        "project_id": "sci_project",
        "project_context_fingerprint": "context-A",
    }
    ledger = {"schema_version": "evidence_coverage_ledger_v1"}
    cluster_coverage = {
        "schema_version": "sh_cluster_coverage_projection_v1",
        "project_id": "sci_project",
        "project_context_fingerprint": "context-A",
    }
    contracts = []
    generator.work_analyzer = SimpleNamespace(
        sh_cluster_coverage_artifact=cluster_coverage,
        work_collector=SimpleNamespace(
            sh_graph_provenance_artifact=provenance,
            subhypothesis_retrieval_artifact={
                "project_id": "sci_project",
                "project_context_fingerprint": "context-A",
                "evidence_coverage_ledger_final": ledger,
                "plan": {
                    "project_context": {"project_context_fingerprint": "context-A"},
                    "subhypotheses": contracts,
                },
            },
        ),
    )
    captured = {}

    def fake_build_survey_evidence_plan(
        *,
        provenance_artifact,
        coverage_ledger,
        cluster_coverage_artifact,
        subhypothesis_contracts,
        max_writable_papers_per_sh,
    ):
        captured.update(
            {
                "provenance_artifact": provenance_artifact,
                "coverage_ledger": coverage_ledger,
                "cluster_coverage_artifact": cluster_coverage_artifact,
                "subhypothesis_contracts": subhypothesis_contracts,
                "max_writable_papers_per_sh": max_writable_papers_per_sh,
            }
        )
        return _plan()

    monkeypatch.setattr(
        "modules.survey_generator.build_survey_evidence_plan",
        fake_build_survey_evidence_plan,
    )

    result = generator.prepare_survey_evidence_plan()

    assert result["schema_version"] == SURVEY_EVIDENCE_PLAN_SCHEMA_VERSION
    assert captured == {
        "provenance_artifact": provenance,
        "coverage_ledger": ledger,
        "cluster_coverage_artifact": cluster_coverage,
        "subhypothesis_contracts": contracts,
        "max_writable_papers_per_sh": 20,
    }


def test_bounded_title_citation_rejects_database_resolved_graph_candidate() -> None:
    generator = _generator()
    generator.always_omit_error = False
    generator.config = SimpleNamespace(
        BasicInfo=SimpleNamespace(debug=False),
        ModuleInfo=SimpleNamespace(
            SurveyGenerator=SimpleNamespace(
                draft_length_relax_ratio=1.0,
                include_other_relevant_papers_RAG=False,
                valid_title_min_similarity=0.9,
            )
        ),
    )
    generator.database = SimpleNamespace(
        resolve_title_to_paper_id=lambda **_kwargs: ("W-candidate", "Candidate paper", 1.0)
    )

    valid, errors, _ = generator.validate_title_citation_draft(
        "This is not admissible evidence. <Candidate paper>",
        ["W1"],
        omit_error=True,
    )

    assert valid is False
    assert "outside the evidence-bounded paper set" in errors[0]


def test_title_mode_accepts_permitted_openalex_id_citations() -> None:
    generator = _generator()
    generator.always_omit_error = False
    generator.config = SimpleNamespace(
        BasicInfo=SimpleNamespace(debug=False),
        ModuleInfo=SimpleNamespace(
            SurveyGenerator=SimpleNamespace(
                include_other_relevant_papers_RAG=False,
                valid_title_min_similarity=0.5,
                draft_length_relax_ratio=1.0,
            )
        ),
    )
    generator.database = SimpleNamespace(
        resolve_title_to_paper_id=lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("OpenAlex ID citations must not use title resolution.")
        )
    )
    text = (
        "Direct evidence is available <W4288079944>, with a corroborating "
        "study <Paper ID: W2116312019>."
    )

    valid, errors, cleaned = generator.validate_title_citation_draft(
        text,
        ["W4288079944", "W2116312019"],
    )
    processed, references, valid_tokens, invalid_tokens = (
        generator.extract_and_process_citations(text)
    )

    assert valid is True
    assert errors == []
    assert cleaned == text
    assert processed == "Direct evidence is available [1], with a corroborating study [2]."
    assert references == ["W4288079944", "W2116312019"]
    assert valid_tokens == ["W4288079944", "Paper ID: W2116312019"]
    assert invalid_tokens == []


def test_save_survey_recursively_converts_omegaconf_containers(tmp_path) -> None:
    generator = _generator()
    save_path = tmp_path / "survey.md"
    save_json_path = tmp_path / "survey.json"
    generator.config = SimpleNamespace(
        BasicInfo=SimpleNamespace(
            save_path=str(save_path),
            save_json_path=str(save_json_path),
            topic="Nested config survey",
            survey_run_id="run-1",
            debug=False,
            research_context=OmegaConf.create(
                {
                    "declared_domain": "physics",
                    "research_domains": [{"key": "physics_astronomy"}],
                }
            ),
            subhypothesis_retrieval=OmegaConf.create(
                {"subhypotheses": ["SH1"]}
            ),
            subhypothesis_decomposition=OmegaConf.create(
                {"subhypotheses": [{"id": "SH1"}]}
            ),
            survey_evidence_plan=OmegaConf.create({"fallback": ["W1"]}),
            survey_claim_traceability=OmegaConf.create({"claims": ["C1"]}),
        )
    )
    generator.survey_evidence_plan = OmegaConf.create(
        {"subhypotheses": [{"evidence_paper_ids": ["W1"]}]}
    )
    generator.survey_claim_traceability_artifact = OmegaConf.create(
        {"claims": [{"paper_ids": ["W1"]}]}
    )

    generator.save_survey("Survey body", OmegaConf.create(["W1"]))

    saved = json.loads(save_json_path.read_text(encoding="utf-8"))
    assert save_path.read_text(encoding="utf-8") == "Survey body"
    assert saved["project_domain"]["research_domains"] == [
        {"key": "physics_astronomy"}
    ]
    assert saved["subhypothesis_retrieval"]["subhypotheses"] == ["SH1"]
    assert saved["survey_evidence_plan"]["subhypotheses"][0][
        "evidence_paper_ids"
    ] == ["W1"]
    assert saved["claim_traceability"]["claims"][0]["paper_ids"] == ["W1"]
    assert saved["references"] == ["W1"]


def test_bounded_outline_removes_unassessed_graph_candidates() -> None:
    generator = _generator()
    outline = {
        "sections": [
            {
                "papers_to_use": ["W1", "W-candidate"],
                "subsections": [
                    {"papers_to_use": ["W-context", "W-candidate"]}
                ],
            }
        ]
    }

    bounded = generator._bound_outline_to_evidence_plan(outline)

    assert bounded["sections"][0]["papers_to_use"] == ["W1"]
    assert bounded["sections"][0]["subsections"][0]["papers_to_use"] == ["W-context"]


def test_subsection_prompt_exposes_the_evidence_plan_and_trace_contract() -> None:
    prompt_values = {
        "title": "Evidence",
        "description": "Discuss only admitted evidence.",
        "papers": "Paper ID: W1",
        "other_relevant_papers": "",
        "survey_outline": "{}",
        "relevant_analysis": "",
        "subsection_target_citations": 3,
        "subsection_max_citations": 5,
        "subsection_target_words": 450,
        "subsection_max_words": 550,
        "survey_evidence_plan": '{"evidence_bounded_writing":true}',
    }

    prompt = SUBSECTION_DRAFT.format(**prompt_values)

    assert "Authoritative survey evidence plan" in prompt
    assert "[[SH_CLAIM_TRACE]]" in prompt

    code_prompt = SUBSECTION_DRAFT_WITH_CODE.format(
        **prompt_values,
        code_report_prompt="",
    )
    assert "[[SH_CLAIM_TRACE]]" in code_prompt

    section_prompt = SECTION_DRAFT.format(
        title="Evidence",
        description="Discuss only admitted evidence.",
        subsection_drafts="",
        papers="Paper ID: W1",
        other_relevant_papers="",
        survey_outline="{}",
        section_target_citations=1,
        section_max_citations=2,
        section_target_words=100,
        section_max_words=160,
        survey_evidence_plan='{"evidence_bounded_writing":true}',
    )
    assert "[[SH_CLAIM_TRACE]]" in section_prompt


def test_all_outline_prompts_accept_the_evidence_plan_parameter() -> None:
    values = {
        "paper_keynotes": "Paper ID: W1",
        "current_outline": "{}",
        "papers_analysis": "",
        "other_relevant_papers": "",
        "survey_evidence_plan": '{"evidence_bounded_writing":true}',
        "outline_size_budget": "Use a concise survey shape.",
    }

    for template in (
        SURVEY_OUTLINE_GENERATION,
        SURVEY_OUTLINE_GENERATION_OUTLINE_DRAFT,
        SURVEY_OUTLINE_GENERATION_PAPER_ASSIGNMENT,
    ):
        rendered = template.format(**values)
        assert "evidence_bounded_writing" in rendered


@pytest.mark.parametrize(
    (
        "claim_trace_validation_enabled",
        "expected_claim_count",
        "expected_batch_calls",
        "expected_repair_calls",
    ),
    [(True, 2, 4, 2), (False, 0, 2, 0)],
)
def test_draft_survey_strips_validated_trace_blocks_and_persists_claim_artifact(
    tmp_path,
    claim_trace_validation_enabled,
    expected_claim_count,
    expected_batch_calls,
    expected_repair_calls,
) -> None:
    class _ChatAgent:
        def __init__(self):
            self.batch_calls = 0
            self.prompts = []
            self.descriptions = []

        def estimate_tokens(self, _prompt):
            return 1

        def truncate_text(self, _paper_id, text, _limit):
            return text

        def batch_remote_chat(self, _prompts, **_kwargs):
            self.batch_calls += 1
            self.prompts.extend(_prompts)
            self.descriptions.append(_kwargs.get("desc", ""))
            prose = "The direct observation supports the stated relation <Paper ID: W1>."
            if str(_kwargs.get("desc", "")).startswith("Repairing"):
                return [
                    '{"claims":[{"claim_index":1,"claim_anchor":"direct observation",'
                    '"sub_hypothesis_ids":["SH1"],'
                    '"claim_mode":"EVIDENCE_BACKED_SYNTHESIS",'
                    '"evidence_paths":[{"sub_hypothesis_id":"SH1",'
                    '"slot_name":"direct_observation","paper_id":"W1"}]}]}'
                ]
            # Simulate an otherwise valid long-form response whose only defect
            # is the missing trace block.  The production path must repair
            # metadata rather than regenerate this reader-visible prose.
            return [prose]

    generator = _generator()
    generator.chat_agent = _ChatAgent()
    generator.config = SimpleNamespace(
        BasicInfo=SimpleNamespace(
            base_dir=str(tmp_path),
            debug=False,
            error_conservatism_mode=False,
            topic="General scientific topic",
        ),
        APIInfo=SimpleNamespace(llm_max_context_length=16000),
        ModuleInfo=SimpleNamespace(
            WorkAnalyzer=SimpleNamespace(abstract_when_full_text_fail=True),
            SurveyGenerator=SimpleNamespace(
                include_other_relevant_papers_RAG=False,
                subsection_RAG_topk=0,
                section_RAG_topk=0,
                subsection_least_words=0,
                subsection_least_citations=0,
                subsection_target_min_words=1,
                subsection_target_max_words=100,
                subsection_target_citations=1,
                subsection_max_citations=2,
                survey_target_words=2,
                survey_max_words=200,
                section_preamble_target_words=1,
                section_preamble_max_words=100,
                section_preamble_target_citations=1,
                section_preamble_max_citations=2,
                section_preamble_least_words=0,
                section_preamble_least_citations=0,
                use_full_text_in_survey_generation=False,
                llm_max_context_overhead_length_generation=100,
                subsection_draft_max_retry=1,
                subsection_draft_temperature=0.0,
                section_draft_max_retry=1,
                section_draft_temperature=0.0,
                draft_length_relax_ratio=1.0,
                claim_trace_validation_enabled=claim_trace_validation_enabled,
            ),
        ),
    )
    generator.work_analyzer = SimpleNamespace(
        get_paper_keynote=lambda _paper_id: "Admitted direct evidence.",
        work_collector=SimpleNamespace(
            get_paper_title_abstract=lambda _paper_id: ("Evidence paper", "Abstract")
        ),
    )
    generator.database = SimpleNamespace(query_and_text=lambda *_args, **_kwargs: "")
    generator.use_title_in_draft = False
    generator.omit_error_preserve_retry_time = 0
    generator.always_omit_error = False
    generator.include_relation_graph = False
    generator.include_relation_table = False
    generator.include_initial_analysis = False

    draft = generator.draft_survey(
        [[{"question": "candidate", "answer": "candidate result", "related_papers": ["W-candidate"]}]],
        "candidate-only inter-cluster conclusion",
        {
            "title": "Bounded survey",
            "sections": [
                {
                    "title": "Findings",
                    "description": "Only admitted evidence.",
                    "papers_to_use": ["W-candidate"],
                    "subsections": [
                        {
                            "title": "Direct evidence",
                            "description": "Discuss admitted evidence.",
                            "papers_to_use": ["W1", "W-candidate"],
                        }
                    ],
                }
            ],
        },
        code_report="W-candidate unassessed code interpretation",
    )

    assert "SH_CLAIM_TRACE" not in draft["full_draft"]
    assert draft["outline"]["sections"][0]["papers_to_use"] == []
    assert draft["outline"]["sections"][0]["subsections"][0]["papers_to_use"] == ["W1"]
    assert (
        draft["claim_traceability"]["validation_enabled"]
        is claim_trace_validation_enabled
    )
    assert len(draft["claim_traceability"]["claims"]) == expected_claim_count
    assert (tmp_path / "survey_claim_traceability.json").exists()
    assert all("W-candidate" not in prompt for prompt in generator.chat_agent.prompts)
    assert all("candidate-only inter-cluster conclusion" not in prompt for prompt in generator.chat_agent.prompts)
    assert generator.chat_agent.batch_calls == expected_batch_calls
    assert sum(
        description.startswith("Drafting")
        for description in generator.chat_agent.descriptions
    ) == 2
    assert sum(
        description.startswith("Repairing")
        for description in generator.chat_agent.descriptions
    ) == expected_repair_calls


def test_section_retry_feedback_is_isolated_per_section() -> None:
    class _RetryFeedbackChat:
        def __init__(self):
            self.section_prompt_batches = []

        def estimate_tokens(self, _prompt):
            return 1

        def truncate_text(self, _paper_id, text, _limit):
            return text

        def batch_remote_chat(self, prompts, **_kwargs):
            if not prompts:
                return []
            self.section_prompt_batches.append(list(prompts))
            if len(self.section_prompt_batches) == 1:
                return [
                    "Invalid first citation <Paper ID: W-invalid-first>.",
                    "Invalid second citation <Paper ID: W-invalid-second>.",
                ]
            return ["Valid first preamble.", "Valid second preamble."]

    generator = _generator()
    generator.chat_agent = _RetryFeedbackChat()
    generator.config = SimpleNamespace(
        BasicInfo=SimpleNamespace(
            base_dir="", debug=False, error_conservatism_mode=False, topic="Topic"
        ),
        APIInfo=SimpleNamespace(llm_max_context_length=16_000),
        ModuleInfo=SimpleNamespace(
            SurveyGenerator=SimpleNamespace(
                include_other_relevant_papers_RAG=False,
                subsection_RAG_topk=0,
                section_RAG_topk=0,
                subsection_target_min_words=1,
                subsection_target_max_words=100,
                subsection_target_citations=1,
                subsection_max_citations=2,
                survey_target_words=2,
                survey_max_words=200,
                section_preamble_target_words=1,
                section_preamble_max_words=100,
                section_preamble_target_citations=1,
                section_preamble_max_citations=2,
                use_full_text_in_survey_generation=False,
                llm_max_context_overhead_length_generation=100,
                subsection_draft_max_retry=1,
                subsection_draft_temperature=0.0,
                section_draft_max_retry=2,
                section_draft_temperature=0.0,
                draft_length_relax_ratio=1.0,
                claim_trace_validation_enabled=False,
            )
        ),
    )
    generator.work_analyzer = SimpleNamespace(
        work_collector=SimpleNamespace(get_paper_title_abstract=lambda _paper_id: ("", ""))
    )
    generator.database = SimpleNamespace(query_and_text=lambda *_args, **_kwargs: "")
    generator.use_title_in_draft = False
    generator.omit_error_preserve_retry_time = 0
    generator.always_omit_error = False
    generator.include_relation_graph = False
    generator.include_relation_table = False
    generator.include_initial_analysis = False

    generator.draft_survey(
        [],
        "",
        {
            "title": "Retry feedback survey",
            "sections": [
                {"title": "First", "description": "First section", "subsections": []},
                {"title": "Second", "description": "Second section", "subsections": []},
            ],
        },
    )

    retry_prompts = generator.chat_agent.section_prompt_batches[1]
    assert "W-invalid-first" in retry_prompts[0]
    assert "W-invalid-second" not in retry_prompts[0]
    assert "W-invalid-second" in retry_prompts[1]
    assert "W-invalid-first" not in retry_prompts[1]


class _QualityChatAgent:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def remote_chat(self, prompt, **kwargs):
        self.calls.append({"prompt": prompt, **kwargs})
        return self.responses.pop(0)


def _quality_generator(responses, *, strict_claim_trace=False) -> SurveyGenerator:
    generator = _generator()
    generator.chat_agent = _QualityChatAgent(responses)
    generator.config = SimpleNamespace(
        BasicInfo=SimpleNamespace(
            base_dir="",
            debug=False,
            topic="Evidence-bounded quality testing",
        ),
        ModuleInfo=SimpleNamespace(
            SurveyGenerator=SimpleNamespace(
                claim_trace_validation_enabled=strict_claim_trace,
                survey_target_words=100,
                survey_max_words=200,
                section_preamble_target_words=1,
                section_preamble_max_words=10,
                subsection_target_min_words=1,
                subsection_target_max_words=100,
                subsection_target_citations=1,
                subsection_max_citations=2,
                reviewer_max_suggestions=5,
                section_review_temperature=0.0,
                section_revise_temperature=0.0,
                evidence_bounded_section_quality_review_enabled=True,
                evidence_bounded_section_quality_score_threshold=8.0,
                evidence_bounded_section_quality_max_improvements=2,
                evidence_bounded_section_quality_review_retry=1,
                evidence_bounded_section_quality_revise_retry=1,
            )
        ),
    )
    generator.use_title_in_draft = False
    return generator


def _quality_draft(section_text: str) -> dict:
    return {
        "title": "Bounded quality survey",
        "outline": {
            "sections": [
                {
                    "title": "Evidence",
                    "description": "Discuss only admitted evidence.",
                    "papers_to_use": ["W1"],
                    "subsections": [],
                }
            ]
        },
        "section_drafts": [section_text],
        "full_draft": "Bounded quality survey\n\n" + section_text,
    }


def test_bounded_quality_review_improves_low_score_section_then_finalizes() -> None:
    original = "## 1. Evidence\n\nThe initial exposition is vague <Paper ID: W1>."
    revised = "## 1. Evidence\n\nThe evidence is stated precisely and cautiously <Paper ID: W1>."
    generator = _quality_generator(
        [
            json.dumps(
                {
                    "scores": {
                        "readability": 7,
                        "scientific": 7.5,
                        "framework": 8,
                    },
                    "suggestions": ["Clarify the relation without adding evidence."],
                }
            ),
            json.dumps({"revised_section": revised}),
            json.dumps(
                {
                    "scores": {
                        "readability": 8,
                        "scientific": 8,
                        "framework": 8.5,
                    },
                    "suggestions": [],
                }
            ),
        ]
    )
    generator._finalize_evidence_bounded_draft = lambda draft: (
        draft["full_draft"],
        ["W1"],
    )

    survey, references = generator.refine_draft(_quality_draft(original))

    assert revised in survey
    assert references == ["W1"]
    assert len(generator.chat_agent.calls) == 3
    assert "EVIDENCE_BOUNDED_SECTION_QUALITY" not in survey


def test_bounded_quality_review_discards_new_citation_without_blocking() -> None:
    original = "## 1. Evidence\n\nThe initial exposition is cautious <Paper ID: W1>."
    unsafe = "## 1. Evidence\n\nAn unsupported expansion is asserted <Paper ID: W-candidate>."
    generator = _quality_generator(
        [
            json.dumps(
                {
                    "scores": {
                        "readability": 7,
                        "scientific": 7,
                        "framework": 7,
                    },
                    "suggestions": ["Improve the wording."],
                }
            ),
            json.dumps({"revised_section": unsafe}),
        ]
    )
    generator._finalize_evidence_bounded_draft = lambda draft: (
        draft["full_draft"],
        ["W1"],
    )

    survey, references = generator.refine_draft(_quality_draft(original))

    assert original in survey
    assert unsafe not in survey
    assert references == ["W1"]
    assert len(generator.chat_agent.calls) == 2


def test_bounded_quality_revision_rejects_heading_changes_and_section_overflow() -> None:
    generator = _quality_generator([])
    original = "## 1. Evidence\n\nThe initial exposition is cautious <Paper ID: W1>."
    oversized_body = " ".join(["careful"] * 30)
    unsafe = (
        "## 1. Renamed evidence\n\n"
        f"{oversized_body} <Paper ID: W1>."
    )

    errors = generator._validate_evidence_bounded_section_quality_revision(
        original_section=original,
        revised_section=unsafe,
        allowed_paper_ids={"W1"},
        section_word_cap=10,
    )

    assert "section or subsection headings changed" in errors
    assert any("section exceeds its word cap" in error for error in errors)


def test_bounded_quality_review_skips_when_strict_claim_trace_is_active() -> None:
    original = "## 1. Evidence\n\nThe initial exposition is cautious <Paper ID: W1>."
    generator = _quality_generator([], strict_claim_trace=True)
    generator._finalize_evidence_bounded_draft = lambda draft: (
        draft["full_draft"],
        ["W1"],
    )

    survey, references = generator.refine_draft(_quality_draft(original))

    assert original in survey
    assert references == ["W1"]
    assert generator.chat_agent.calls == []
