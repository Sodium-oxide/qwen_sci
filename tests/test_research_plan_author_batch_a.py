from __future__ import annotations

from datetime import datetime, timezone
from io import StringIO
import json
from pathlib import Path

import pytest
from omegaconf import OmegaConf

from src import cli
from src.agents.experiment_design_agent.artifacts import build_author_handoff
from src.agents.experiment_design_agent.contracts import (
    EVIDENCE_BUNDLE_SCHEMA_VERSION,
    EXPERIMENT_DESIGN_SCHEMA_VERSION,
    OUTCOME_BRANCH_SCHEMA_VERSION,
    RESEARCH_BRIEF_SCHEMA_VERSION,
)
from src.agents.experiment_design_agent.discipline_catalog import resolve_execution_policy
from src.agents.research_plan_author.artifacts import write_author_preparation_artifacts
from src.agents.research_plan_author.contracts import (
    AUTHORING_LANGUAGE,
    AUTHOR_PREPARATION_SCHEMA_VERSION,
    build_research_plan_document_skeleton,
    validate_author_preparation,
    validate_author_input,
)
from src.agents.research_plan_author.idea_evolution import IdeaEvolutionError, project_idea_evolution
from src.agents.research_plan_author.run import run_author_preparation
from src.agents.research_plan_author.run import AuthorRunError
from src.agents.research_plan_author.run_logging import AuthorRunLogger
from src.agents.research_plan_author.survey_source_loader import (
    SurveyAuthorSourceError,
    load_verified_survey_sources,
)
from src.pipeline.survey_idea_loader import SurveyIdeaContext


def _brief() -> dict:
    return {
        "schema_version": RESEARCH_BRIEF_SCHEMA_VERSION,
        "brief_id": "brief-1",
        "topic": "Reliable scientific image analysis",
        "discipline_ids": ["17"],
        "selected_direction": {
            "id": "selected-route",
            "title": "Reliable Scientific Image Analysis",
            "central_hypothesis": "The representation improves robust image analysis.",
            "mechanism_or_relation": "The representation changes error behavior under shift.",
        },
        "research_object": {"object_type": "scientific image dataset"},
        "intervention_or_transformation": "Use the proposed representation.",
        "discriminating_observations": ["Robustness changes under held-out shifts."],
        "boundary_conditions": ["Only for the stated dataset family."],
        "alternative_explanations": ["An unrelated preprocessing change explains the effect."],
        "known_unknowns": ["The deployment distribution is not yet known."],
        "evidence_status": "PROPOSED",
        "source": {"idea_result_schema": "idea_result_v5", "direction_id": "selected-route"},
        "reasoning_context": {
            "schema_version": "reasoning_context_v1",
            "selected_direction_id": "selected-route",
            "assumptions": [],
            "claim_scope": "The declared image-analysis proposal.",
            "falsifiers": [],
            "boundary_conditions": ["The stated boundary."],
            "alternative_explanations": ["A declared alternative explanation."],
            "formal_symbols": [],
            "gap_records": [],
            "evidence_roles": [],
            "source_anchors": [],
            "upstream_source_paths": [],
            "source_priority": ["selected_direction"],
        },
    }


def _branch(branch_id: str) -> dict:
    return {
        "schema_version": OUTCOME_BRANCH_SCHEMA_VERSION,
        "branch_id": branch_id,
        "trigger": "The preregistered decision rule for this branch is met.",
        "interpretation": "Interpret the result only within the declared design boundary.",
        "conclusion_scope": "The stated scientific image dataset family.",
        "improvement_actions": ["Update the next design iteration from this branch."],
        "evidence_status": "EXPECTED_NOT_OBSERVED",
    }


def _design() -> dict:
    policy = resolve_execution_policy(["17"])
    design = {
        "schema_version": EXPERIMENT_DESIGN_SCHEMA_VERSION,
        "design_id": "design-1",
        "evidence_status": "DESIGNED_NOT_EXECUTED",
        "execution_policy": {
            "mode": policy["mode"],
            "allow_digital_execution": False,
            "reason": policy["reason"],
        },
        "research_brief": _brief(),
        "evidence_bundle": {
            "schema_version": EVIDENCE_BUNDLE_SCHEMA_VERSION,
            "brief_id": "brief-1",
            "evidence_cards": [],
            "coverage": {
                "required_slots": ["comparison", "measurement"],
                "covered_slots": [],
                "uncovered_slots": ["comparison", "measurement"],
            },
        },
        "research_design": {
            "design_type": "comparative computational study",
            "experimental_unit": "held-out scientific image",
            "time_structure": "fixed train-validation-test split",
        },
        "hypothesis_mapping": [
            {
                "hypothesis_id": "H1",
                "claim": "The representation improves robustness.",
                "observables": ["shifted-distribution error"],
                "decision_rule": "Compare against the preregistered baseline.",
            }
        ],
        "variables_and_operationalization": {
            "independent_variables": [],
            "dependent_variables": [],
            "control_variables": [],
            "confounders": [],
            "operational_definitions": [],
        },
        "sampling_and_eligibility": {
            "source": {"status": "needs_human_input"},
            "eligibility_criteria": {"status": "needs_human_input"},
            "sample_size_or_power_basis": {"status": "needs_human_input"},
        },
        "measurement_and_calibration": {
            "instruments": [],
            "measurement_plan": {"status": "needs_human_input"},
            "calibration": {"status": "not_applicable"},
            "quality_control": {"status": "needs_human_input"},
        },
        "comparison_and_robustness": {
            "groups": [],
            "controls": [],
            "baselines": [],
            "comparisons": [],
            "ablation_sensitivity_robustness": [],
        },
        "analysis_plan": {
            "randomization": {"status": "needs_human_input"},
            "blinding": {"status": "not_applicable"},
            "repetitions": {"status": "needs_human_input"},
            "batch_effects": {"status": "needs_human_input"},
            "missing_data": {"status": "needs_human_input"},
            "statistical_analysis": {"status": "needs_human_input"},
        },
        "data_governance_and_reproducibility": {
            "data_management": {"status": "needs_human_input"},
            "reproducibility": {"status": "needs_human_input"},
        },
        "outcome_branches": [
            _branch("supports_mechanism"),
            _branch("partial_or_heterogeneous"),
            _branch("null_or_contradictory"),
            _branch("uninformative_or_invalid"),
        ],
        "risk_and_human_review": {
            "risk_level": "medium",
            "human_review_required": False,
            "review_triggers": [],
            "execution_prohibited": True,
        },
        "open_design_questions": ["Select the final dataset and baseline."],
        "observed_results": [],
        "validation_report": {"status": "DRAFT_REQUIRES_INPUT", "errors": [], "warnings": []},
    }
    _canonicalize_design(design)
    return design


def _canonicalize_design(design: dict) -> None:
    statuses = dict(design.get("field_statuses") or {})
    sections = {
        "research_design",
        "hypothesis_mapping",
        "variables_and_operationalization",
        "sampling_and_eligibility",
        "measurement_and_calibration",
        "comparison_and_robustness",
        "analysis_plan",
        "data_governance_and_reproducibility",
        "template_details",
    }

    def visit(value: object, path: str) -> object:
        if isinstance(value, dict):
            output = {}
            for key, child in value.items():
                child_path = f"{path}.{key}" if path else key
                if key == "status":
                    statuses.setdefault(path, child)
                else:
                    output[key] = visit(child, child_path)
            return output
        if isinstance(value, list):
            return [visit(child, f"{path}[{index}]") for index, child in enumerate(value)]
        return value

    for section in sections:
        if section in design:
            design[section] = visit(design[section], section)
    design["field_statuses"] = statuses


def _author_input() -> dict:
    return build_author_handoff(_design(), idea_result_path="")


def _write_idea_run(tmp_path: Path, *, include_candidate: bool, include_portfolio: bool) -> Path:
    path = tmp_path / "idea_result.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": "idea_result_v5",
                "primary_direction": "selected-route",
                "directions": [
                    {
                        "id": "selected-route",
                        "title": "Final Direction",
                        "central_hypothesis": "The final hypothesis.",
                        "boundary_conditions": ["Declared boundary."],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    if include_candidate:
        (tmp_path / "idea_candidate.json").write_text(
            json.dumps({"title": "Initial Candidate", "hypothesis": "Initial hypothesis."}),
            encoding="utf-8",
        )
    if include_portfolio:
        (tmp_path / "idea_portfolio.json").write_text(
            json.dumps(
                {
                    "selected_primary_idea": {
                        "title": "Constraint Revision",
                        "hypothesis": "Revised hypothesis.",
                    }
                }
            ),
            encoding="utf-8",
        )
    return path


def _fake_survey_context(tmp_path: Path) -> SurveyIdeaContext:
    filenames = {
        "idea_handoff": "survey_idea_handoff.json",
        "gap_ledger": "survey_gap_ledger.json",
        "project_context": "project_context.json",
        "survey_json": "survey.json",
        "survey_markdown": "survey.md",
        "claim_traceability": "survey_claim_traceability.json",
        "evidence_plan": "survey_evidence_plan.json",
    }
    artifacts: dict[str, dict[str, str]] = {}
    for name, filename in filenames.items():
        artifact_path = tmp_path / filename
        if name == "survey_markdown":
            artifact_path.write_text(
                "# Survey Overview\n\nVerified background.\n\n## Open Research Gap\n\nA bounded unresolved gap.\n",
                encoding="utf-8",
            )
        else:
            artifact_path.write_text("{}", encoding="utf-8")
        artifacts[name] = {"path": filename}
    manifest = {"artifacts": artifacts}
    return SurveyIdeaContext(
        manifest_path=tmp_path / "survey_manifest.json",
        base_dir=tmp_path,
        manifest=manifest,
        handoff={},
        gap_ledger={},
        project_context={},
        survey_json={},
        survey_markdown="# Survey Overview\n\nVerified background.\n\n## Open Research Gap\n\nA bounded unresolved gap.\n",
        topic="Test Topic",
        legacy=False,
    )


def test_author_input_contract_rejects_observed_results_and_locks_english() -> None:
    author_input = _author_input()

    assert validate_author_input(author_input) == []
    source_bundle = {
        "schema_version": "research_plan_author_source_bundle_v1",
        "language": "en",
        "source_design_id": "design-1",
        "selected_direction_id": "selected-route",
        "author_input_path": "/tmp/author.json",
        "survey_sources": {},
        "idea_evolution": {},
        "authoring_constraints": author_input["authoring_constraints"],
    }
    skeleton = build_research_plan_document_skeleton(author_input, source_bundle)

    assert skeleton["language"] == AUTHORING_LANGUAGE == "en"
    assert skeleton["document_status"] == "PREPARATION_ONLY"
    assert {section["section_id"] for section in skeleton["sections"]} >= {
        "introduction",
        "survey_and_research_gap",
        "study_design_and_methods",
        "expected_outcomes",
    }
    author_input["authoring_constraints"]["observed_results_are_absent"] = False
    assert any("observed_results_are_absent" in error for error in validate_author_input(author_input))
    author_input = _author_input()
    author_input["schema_version"] = "unsupported_author_input_v0"
    assert any("schema_version" in error for error in validate_author_input(author_input))
    author_input["schema_version"] = "research_plan_author_input_v2"
    assert any("schema_version" in error for error in validate_author_input(author_input))


def test_author_input_contract_rejects_duplicated_full_design_payload() -> None:
    author_input = _author_input()
    author_input["experiment_design"] = {}

    errors = validate_author_input(author_input)

    assert any("experiment_design" in error and "Additional properties" in error for error in errors)


def test_idea_evolution_projects_two_three_and_missing_history(tmp_path: Path) -> None:
    idea_path = _write_idea_run(tmp_path, include_candidate=True, include_portfolio=True)

    two_rounds = project_idea_evolution(idea_path, selected_direction_id="selected-route", max_iterations=2)
    three_rounds = project_idea_evolution(idea_path, selected_direction_id="selected-route", max_iterations=3)

    assert two_rounds["iterations"] == []
    assert two_rounds["temporal_order"] == "unknown"
    assert [entry["checkpoint_type"] for entry in two_rounds["checkpoints"]] == [
        "available_audit_snapshot",
        "available_audit_snapshot",
    ]
    assert [entry["checkpoint_type"] for entry in three_rounds["checkpoints"]] == [
        "available_audit_snapshot",
        "available_audit_snapshot",
        "available_audit_snapshot",
    ]
    missing_directory = tmp_path / "missing-history"
    missing_directory.mkdir()
    missing_path = _write_idea_run(missing_directory, include_candidate=False, include_portfolio=False)
    missing = project_idea_evolution(missing_path, selected_direction_id="selected-route", max_iterations=3)
    assert missing["status"] == "INSUFFICIENT_HISTORY"
    assert len(missing["checkpoints"]) == 1
    revision_only_directory = tmp_path / "revision-only"
    revision_only_directory.mkdir()
    revision_only_path = _write_idea_run(
        revision_only_directory,
        include_candidate=False,
        include_portfolio=True,
    )
    revision_only = project_idea_evolution(
        revision_only_path,
        selected_direction_id="selected-route",
        max_iterations=2,
    )
    assert [entry["checkpoint_type"] for entry in revision_only["checkpoints"]] == [
        "available_audit_snapshot",
        "available_audit_snapshot",
    ]
    with pytest.raises(IdeaEvolutionError, match="selected direction mismatch"):
        project_idea_evolution(idea_path, selected_direction_id="other-route")


def test_survey_loader_requires_verified_manifest_context(monkeypatch, tmp_path: Path) -> None:
    context = _fake_survey_context(tmp_path)
    import src.agents.research_plan_author.survey_source_loader as source_loader

    monkeypatch.setattr(source_loader, "load_survey_idea_context", lambda _source: context)
    sources = load_verified_survey_sources(tmp_path / "survey_manifest.json")
    assert sources["topic"] == "Test Topic"
    assert sources["artifacts"]["survey_markdown"]["content_available"] is True
    assert sources["artifacts"]["survey_markdown"]["excerpts"] == [
        {
            "anchor_id": "survey:survey_markdown#section-001",
            "heading": "Survey Overview",
            "ordinal": 1,
            "text": "# Survey Overview\n\nVerified background.",
        },
        {
            "anchor_id": "survey:survey_markdown#section-002",
            "heading": "Open Research Gap",
            "ordinal": 2,
            "text": "## Open Research Gap\n\nA bounded unresolved gap.",
        },
    ]
    context = SurveyIdeaContext(
        **{**context.__dict__, "legacy": True},
    )
    monkeypatch.setattr(source_loader, "load_survey_idea_context", lambda _source: context)
    with pytest.raises(SurveyAuthorSourceError, match="completed, verified"):
        load_verified_survey_sources(tmp_path / "survey_manifest.json")


def test_survey_loader_rejects_missing_manifest(tmp_path: Path) -> None:
    with pytest.raises(SurveyAuthorSourceError, match="does not exist"):
        load_verified_survey_sources(tmp_path / "missing-survey-manifest.json")


def test_run_preparation_and_atomic_artifacts(monkeypatch, tmp_path: Path) -> None:
    author_input = _author_input()
    idea_path = _write_idea_run(tmp_path, include_candidate=True, include_portfolio=False)
    author_input["provenance"]["idea_result_path"] = str(idea_path)
    author_path = tmp_path / "experiment_design_author.json"
    author_path.write_text(json.dumps(author_input), encoding="utf-8")
    survey_sources = {
        "schema_version": "research_plan_author_survey_sources_v1",
        "manifest_path": str(tmp_path / "survey_manifest.json"),
        "base_dir": str(tmp_path),
        "survey_run_id": "survey-run-1",
        "project_id": "project-1",
        "project_context_fingerprint": "fingerprint",
        "topic": "Test Topic",
        "manifest": {},
        "artifacts": {},
        "artifact_paths": {},
    }
    import src.agents.research_plan_author.run as author_run

    monkeypatch.setattr(author_run, "load_verified_survey_sources", lambda _path: survey_sources)
    result = run_author_preparation(author_path, survey_manifest_path=tmp_path / "survey_manifest.json")
    paths = write_author_preparation_artifacts(
        result,
        tmp_path / "out",
        generated_at=datetime(2026, 8, 28, tzinfo=timezone.utc),
    )

    assert result["schema_version"] == AUTHOR_PREPARATION_SCHEMA_VERSION
    assert result["language"] == "en"
    assert paths.preparation_json.is_file()
    assert paths.author_context_json.is_file()
    assert paths.document_json.is_file()
    assert paths.idea_evolution_json.is_file()
    assert json.loads(paths.document_json.read_text(encoding="utf-8"))["language"] == "en"
    assert json.loads(paths.author_context_json.read_text(encoding="utf-8")) == author_input
    assert len(result["source_bundle"]["author_input_identity"]["sha256"]) == 64
    assert result["source_bundle"]["survey_binding"]["status"] == "UNBOUND_REQUIRES_HUMAN_CONFIRMATION"
    assert validate_author_preparation(result) == []
    duplicate_paths = write_author_preparation_artifacts(
        result,
        tmp_path / "out",
        generated_at=datetime(2026, 8, 28, tzinfo=timezone.utc),
    )
    assert duplicate_paths.collision_index == 1
    assert duplicate_paths.preparation_json.name.endswith("_1.json")


def test_author_logger_writes_jsonl_and_redacts_sensitive_fields(tmp_path: Path) -> None:
    console = StringIO()
    log_path = tmp_path / "author.jsonl"
    logger = AuthorRunLogger("author-test", jsonl_path=log_path, console_stream=console)
    with logger.stage("input", source_path="author.json"):
        pass
    logger.emit("llm", "failed", level="ERROR", status="FAILED", raw_response="private", api_key="secret")
    logger.close()

    records = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    assert [record["event"] for record in records] == ["started", "completed", "failed"]
    assert records[-1]["raw_response"] == "[REDACTED]"
    assert records[-1]["api_key"] == "[REDACTED]"
    assert "private" not in console.getvalue()


def test_author_cli_defaults_output_and_maps_survey_failure(monkeypatch, tmp_path: Path, capsys) -> None:
    config_path = tmp_path / "config.yaml"
    OmegaConf.save(OmegaConf.create({"research_plan_author": {"enabled": True}}), config_path)
    author_path = tmp_path / "experiment_design_author.json"
    author_path.write_text("{}", encoding="utf-8")
    survey_path = tmp_path / "survey_manifest.json"
    survey_path.write_text("{}", encoding="utf-8")
    captured: dict[str, object] = {}

    def fake_run(author_input_path: Path, **kwargs: object) -> dict:
        captured["author_input_path"] = author_input_path
        captured.update(kwargs)
        return {
            "schema_version": AUTHOR_PREPARATION_SCHEMA_VERSION,
            "status": "COMPOSED_FOR_RENDERING",
            "language": "en",
            "source_design_id": "design-1",
            "selected_direction_id": "selected-route",
            "source_bundle": {
                "schema_version": "research_plan_author_source_bundle_v1",
                "language": "en",
                "source_design_id": "design-1",
                "selected_direction_id": "selected-route",
                "author_input_path": str(author_path),
                "author_input_identity": {"path": str(author_path), "sha256": "a" * 64, "byte_size": 2},
                "author_context": {},
                "survey_sources": {},
                "survey_binding": {
                    "status": "UNBOUND_REQUIRES_HUMAN_CONFIRMATION",
                    "expected": {},
                    "resolved": {},
                    "human_confirmation_required": True,
                },
                "idea_evolution": {},
                "authoring_constraints": {},
            },
            "document": {
                "schema_version": "research_plan_document_v1",
                "document_status": "PREPARATION_ONLY",
                "language": "en",
                "source_design_id": "design-1",
                "document_metadata": {"title": "", "discipline_ids": [], "study_type": ""},
                "abstract": {"text": "", "claim_ids": []},
                "keywords": [],
                "sections": [],
                "appendices": [],
                "citation_registry": [],
                "claim_provenance": [],
                "open_items": [],
                "review_items": [],
                "authoring_constraints": {},
                "source_manifest": {},
                "authoring_blueprint": {},
                "contract_repair_audit": [],
            },
        }

    class FakePaths:
        def as_dict(self) -> dict[str, str | int]:
            return {"timestamp": "test", "collision_index": 0, "preparation_json": "p.json", "document_json": "d.json", "idea_evolution_json": "i.json"}

    import src.agents.research_plan_author.artifacts as author_artifacts
    import src.agents.research_plan_author.llm_json as author_llm_json
    import src.agents.research_plan_author.run as author_run

    monkeypatch.setattr(author_run, "run_research_plan_author", fake_run)
    monkeypatch.setattr(author_artifacts, "write_author_preparation_artifacts", lambda *_args, **_kwargs: FakePaths())
    monkeypatch.setattr(
        author_llm_json,
        "build_author_json_llm_call",
        lambda **kwargs: captured.setdefault("llm_builder", kwargs) or (lambda *_args, **_kwargs: {}),
    )
    parser = cli._build_root_parser()
    args = parser.parse_args(
        [
            "author",
            "--config",
            str(config_path),
            "--author-input",
            str(author_path),
            "--survey-manifest",
            str(survey_path),
            "--model",
            "qwen3.8-flash",
        ]
    )

    assert not hasattr(args, "language")
    assert cli._author_command(args) == cli.AUTHOR_EXIT_SUCCESS
    assert captured["author_input_path"] == author_path.resolve()
    assert captured["include_idea_evolution"] == "auto"
    assert captured["llm_builder"]["model"] == "qwen3.8-flash"
    assert (author_path.parent / "research_plan_author").is_dir()
    output = json.loads(capsys.readouterr().out)
    assert output["language"] == "en"
    assert output["status"] == "COMPOSED_FOR_RENDERING"


def test_author_cli_uses_explicit_output_and_maps_survey_failure(monkeypatch, tmp_path: Path, capsys) -> None:
    config_path = tmp_path / "config.yaml"
    OmegaConf.save(OmegaConf.create({"research_plan_author": {"enabled": True}}), config_path)
    author_path = tmp_path / "experiment_design_author.json"
    author_path.write_text("{}", encoding="utf-8")
    survey_path = tmp_path / "survey_manifest.json"
    survey_path.write_text("{}", encoding="utf-8")
    explicit_output = tmp_path / "explicit-output"

    def fail_run(*_args: object, **_kwargs: object) -> dict:
        raise AuthorRunError("survey", "verified Survey manifest is unavailable")

    import src.agents.research_plan_author.run as author_run

    monkeypatch.setattr(author_run, "run_author_preparation", fail_run)
    parser = cli._build_root_parser()
    args = parser.parse_args(
        [
            "author",
            "--config",
            str(config_path),
            "--author-input",
            str(author_path),
            "--survey-manifest",
            str(survey_path),
            "--output-dir",
            str(explicit_output),
        ]
    )

    assert cli._author_command(args) == cli.AUTHOR_EXIT_SURVEY_ERROR
    assert explicit_output.is_dir()
    assert "author failed at survey" in capsys.readouterr().err
