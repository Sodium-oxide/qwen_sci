from omegaconf import OmegaConf

from src.agents.idea_agent.utils.core.run_inputs import resolve_run_inputs


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


def test_survey_manifest_override_prevents_empty_config_validation_error() -> None:
    resolved = resolve_run_inputs(
        _empty_idea_run_config(),
        default_output_root="runs",
        survey_manifest_override="/tmp/survey_manifest.json",
    )

    assert resolved["topic"] == ""
    assert resolved["survey_manifest"] == "/tmp/survey_manifest.json"
