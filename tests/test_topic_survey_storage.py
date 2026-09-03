import json
import re

from omegaconf import OmegaConf

from src.agents.survey_agent.utils.topic_survey_storage import (
    apply_topic_survey_paths,
    build_survey_artifact_paths,
    find_reusable_survey,
    load_stored_survey_artifacts,
)


def test_new_survey_output_directory_is_research_start_time_not_topic(tmp_path) -> None:
    topic = "A very long survey topic (with punctuation): precision medicine = patient-specific care"
    run_id = "20260822-101112-123456"

    artifacts = build_survey_artifact_paths(
        topic,
        output_root=tmp_path,
        research_run_id=run_id,
    )

    assert artifacts.research_run_id == run_id
    assert artifacts.topic_slug == run_id
    assert artifacts.base_dir == tmp_path / run_id
    assert artifacts.markdown_path == tmp_path / run_id / "survey.md"
    assert artifacts.json_path == tmp_path / run_id / "survey.json"
    assert "precision" not in artifacts.base_dir.name


def test_run_id_is_retained_across_repeated_path_application(tmp_path) -> None:
    config = OmegaConf.create(
        {
            "BasicInfo": {
                "topic": "",
                "survey_run_id": "",
                "base_dir": "",
                "save_path": "",
                "save_json_path": "",
                "evaluation_save_path": "",
            }
        }
    )

    first = apply_topic_survey_paths(
        config,
        "A long study topic that must remain metadata rather than a folder name",
        output_root=tmp_path,
    )
    second = apply_topic_survey_paths(
        config,
        config.BasicInfo.topic,
        output_root=tmp_path,
    )

    assert re.fullmatch(r"\d{8}-\d{6}-\d{6}", first.research_run_id)
    assert second.research_run_id == first.research_run_id
    assert config.BasicInfo.base_dir == str(first.base_dir)
    assert config.BasicInfo.save_json_path == str(first.json_path)


def test_timestamped_and_legacy_outputs_remain_discoverable_for_reuse(tmp_path) -> None:
    timestamped = tmp_path / "20260822-101112-123456"
    timestamped.mkdir()
    (timestamped / "survey.md").write_text("survey", encoding="utf-8")
    (timestamped / "survey.json").write_text(
        json.dumps(
            {
                "topic": "Precision medicine for individualized treatment",
                "research_run_id": timestamped.name,
            }
        ),
        encoding="utf-8",
    )

    legacy = tmp_path / "training-free-memory-system-for-llm-agents"
    legacy.mkdir()
    (legacy / "survey.md").write_text("survey", encoding="utf-8")
    (legacy / "survey.json").write_text(
        json.dumps({"topic": "Training-Free Memory System for LLM Agents"}),
        encoding="utf-8",
    )

    stored = load_stored_survey_artifacts(output_root=tmp_path)
    by_topic = {item.topic: item for item in stored}

    assert by_topic["Precision medicine for individualized treatment"].base_dir == timestamped
    assert by_topic["Precision medicine for individualized treatment"].research_run_id == timestamped.name
    assert by_topic["Training-Free Memory System for LLM Agents"].base_dir == legacy
    assert find_reusable_survey(
        "Precision medicine for individualized treatment",
        output_root=tmp_path,
    ) == by_topic["Precision medicine for individualized treatment"]


def test_incomplete_or_tampered_manifest_runs_are_not_discoverable(tmp_path) -> None:
    for run_id, status in (
        ("20260822-101112-123456", "partial"),
        ("20260822-101113-123456", "failed"),
    ):
        run_dir = tmp_path / run_id
        run_dir.mkdir()
        (run_dir / "survey.md").write_text("survey", encoding="utf-8")
        (run_dir / "survey.json").write_text(
            json.dumps({"topic": f"{status} survey", "research_run_id": run_id}),
            encoding="utf-8",
        )
        (run_dir / "survey_manifest.json").write_text(
            json.dumps({"status": status}),
            encoding="utf-8",
        )

    assert load_stored_survey_artifacts(output_root=tmp_path) == []
    assert find_reusable_survey("partial survey", output_root=tmp_path) is None
