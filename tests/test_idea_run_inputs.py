import json
from types import SimpleNamespace

import pytest
from omegaconf import OmegaConf

from src.agents.idea_agent.utils.core.run_inputs import resolve_run_inputs
from src.agents.idea_agent.utils.core import run_inputs


@pytest.fixture(autouse=True)
def offline_contract_extraction(monkeypatch):
    monkeypatch.setattr(run_inputs, "AgentBase", lambda: SimpleNamespace(chat=lambda *args, **kwargs: json.dumps({
        "extraction_status": "complete", "required_deliverables": [], "user_constraints": [], "problem_premises": [],
    })))


def _empty_idea_run_config():
    return OmegaConf.create(
        {
            "run": {
                "topic": "",
                "input": "",
                "output_root": "runs",
                "console_logs": False,
                "rag_config": "src/config/default.yaml",
            }
        }
    )


def test_explicit_topic_override_prevents_empty_config_validation_error() -> None:
    resolved = resolve_run_inputs(
        _empty_idea_run_config(),
        default_output_root="runs",
        topic_override="Topic supplied by science",
    )

    assert resolved["topic"] == "Topic supplied by science"
    assert resolved["topic_source"] == "config_explicit"
    assert resolved["task_contract"]["original_request"] == "Topic supplied by science"


def test_survey_manifest_override_prevents_empty_config_validation_error() -> None:
    resolved = resolve_run_inputs(
        _empty_idea_run_config(),
        default_output_root="runs",
        survey_manifest_override="/tmp/survey_manifest.json",
    )

    assert resolved["topic"] == ""
    assert resolved["survey_manifest"] == "/tmp/survey_manifest.json"


def test_raw_request_survives_interpreter_failure(monkeypatch) -> None:
    request = "Study a chemical reaction. Propose candidate pathways and a concrete comparison under fixed temperature."
    config = _empty_idea_run_config()
    config.run.input = request
    monkeypatch.setattr(run_inputs, "AgentBase", lambda: SimpleNamespace(chat=lambda *args, **kwargs: "not valid JSON"))

    resolved = resolve_run_inputs(config, default_output_root="runs")

    assert resolved["task_contract"]["original_request"] == request
    assert resolved["task_contract"]["user_constraints"] == []


def test_interpreted_deliverables_are_source_grounded(monkeypatch) -> None:
    request = "Design an optical experiment. Keep the detector fixed. Predict a distinguishing signal."
    payload = {
        "topic": "Optical experiment", "topic_source": "explicit",
        "refinement_scope": "Do not predict a signal", "refinement_scope_source": "explicit",
        "task_contract": {
            "task_mode": "protocol_design",
            "required_deliverables": [{"source_quote": "Predict a distinguishing signal."}],
            "user_constraints": [{"source_quote": "Keep the detector fixed."}, {"source_quote": "Do not predict a signal"}],
        },
    }
    config = _empty_idea_run_config()
    config.run.input = request
    monkeypatch.setattr(run_inputs, "AgentBase", lambda: SimpleNamespace(chat=lambda *args, **kwargs: json.dumps(payload)))

    resolved = resolve_run_inputs(config, default_output_root="runs")

    assert resolved["task_contract"]["task_mode"] == "protocol_design"
    assert resolved["task_contract"]["required_deliverables"][0]["text"] == "Predict a distinguishing signal."
    assert [item["text"] for item in resolved["task_contract"]["user_constraints"]] == ["Keep the detector fixed."]
    assert resolved["refinement_scope_source"] == "input_inferred"


@pytest.mark.parametrize("explicit_topic", [False, True])
def test_manifest_binding_preserves_task_without_requiring_interpreter_title_equality(monkeypatch, tmp_path, explicit_topic) -> None:
    pytest.importorskip("faiss")
    from src.agents.idea_agent import run as idea_run
    from src.agents.idea_agent.utils.core.task_contract import build_task_contract
    from src.pipeline.survey_idea_loader import SurveyIdeaLoadError

    request = "Design a study of the supplied system and predict a discriminating observation."
    inputs = {
        "topic": "A paraphrased title",
        "topic_source": "config_explicit" if explicit_topic else "input_explicit",
        "task_contract": build_task_contract(original_request=request),
        "input_text": request, "output_root": str(tmp_path), "console_logs": False,
        "rag_config": "unused", "survey_manifest": "unused",
    }
    survey = SimpleNamespace(topic="The original Survey topic", manifest_path=tmp_path / "survey_manifest.json")
    monkeypatch.setattr(idea_run, "load_idea_agent_config", lambda *args: OmegaConf.create({}))
    monkeypatch.setattr(idea_run, "load_project_config", lambda *args: OmegaConf.create({}))
    monkeypatch.setattr(idea_run, "load_survey_idea_context", lambda *args: survey)
    monkeypatch.setattr(idea_run, "resolve_run_inputs", lambda *args, **kwargs: inputs)
    monkeypatch.setattr(idea_run, "_resolve_runtime_survey_config", lambda *args: (None, None))
    captured = []

    def capture_run(*args):
        captured.append(args)
        return str(tmp_path)

    monkeypatch.setattr(idea_run, "_run_topic", capture_run)
    if explicit_topic:
        with pytest.raises(SurveyIdeaLoadError, match="Explicit Idea topic does not match"):
            idea_run.run_idea_workflow(survey_manifest=str(survey.manifest_path))
        assert captured == []
    else:
        assert idea_run.run_idea_workflow(survey_manifest=str(survey.manifest_path)) == str(tmp_path)
        assert captured[0][0] == survey.topic
        assert captured[0][5]["task_contract"]["original_request"] == request


def test_manifest_only_entry_extracts_requirements_after_binding_the_topic(monkeypatch, tmp_path) -> None:
    pytest.importorskip("faiss")
    from src.agents.idea_agent import run as idea_run

    request = "Compare two mechanisms and give a discriminating observation."
    config = _empty_idea_run_config()
    survey = SimpleNamespace(topic=request, manifest_path=tmp_path / "survey_manifest.json")
    prompts = []

    def chat(prompt, **kwargs):
        prompts.append(prompt)
        return json.dumps({"extraction_status": "complete", "user_constraints": [], "problem_premises": [],
            "required_deliverables": [{"source_quote": "discriminating observation", "acceptance_description": "State a distinguishing signal."}]})

    monkeypatch.setattr(run_inputs, "AgentBase", lambda: SimpleNamespace(chat=chat))
    monkeypatch.setattr(idea_run, "load_idea_agent_config", lambda *args: config)
    monkeypatch.setattr(idea_run, "load_project_config", lambda *args: OmegaConf.create({}))
    monkeypatch.setattr(idea_run, "load_survey_idea_context", lambda *args: survey)
    monkeypatch.setattr(idea_run, "_resolve_runtime_survey_config", lambda *args: (None, None))
    captured = []
    monkeypatch.setattr(idea_run, "_run_topic", lambda *args: captured.append(args) or str(tmp_path))

    assert idea_run.run_idea_workflow(survey_manifest=str(survey.manifest_path), output_root=str(tmp_path)) == str(tmp_path)
    assert len(prompts) == 1 and request in prompts[0]
    contract = captured[0][5]["task_contract"]
    assert contract["original_request"] == request
    assert contract["extraction_status"] == "complete"
    assert contract["required_deliverables"][0]["source_quote"] == "discriminating observation"
