from pathlib import Path

from omegaconf import OmegaConf

from src.agents.survey_agent.utils import config_utils


def _write_default_survey_config(path: Path, output_root: Path) -> None:
    OmegaConf.save(
        OmegaConf.create(
            {
                "survey": {
                    "output": {"root_dir": str(output_root)},
                    "BasicInfo": {
                        "topic": "",
                        "survey_run_id": "",
                        "base_dir": "",
                        "save_path": "",
                        "save_json_path": "",
                        "evaluation_save_path": "",
                    },
                }
            }
        ),
        path,
    )


def test_merge_preserves_explicit_science_survey_artifact_paths(
    monkeypatch, tmp_path: Path
) -> None:
    default_path = tmp_path / "default.yaml"
    _write_default_survey_config(default_path, tmp_path / "survey-output-root")
    monkeypatch.setattr(config_utils, "resolve_runtime_config_path", lambda: default_path)

    attempt_dir = tmp_path / "science-run" / "survey" / "attempt-001"
    runtime_config = OmegaConf.create(
        {
            "survey": {
                "BasicInfo": {
                    "topic": "A topic controlled by science",
                    "survey_run_id": "20260831-034619-359874-survey-001",
                    "base_dir": str(attempt_dir),
                    "save_path": str(attempt_dir / "survey.md"),
                    "save_json_path": str(attempt_dir / "survey.json"),
                    "evaluation_save_path": str(attempt_dir / "evaluation.txt"),
                }
            }
        }
    )

    merged = config_utils.merge_with_default_survey_config(runtime_config)

    assert merged.BasicInfo.survey_run_id == "20260831-034619-359874-survey-001"
    assert merged.BasicInfo.base_dir == str(attempt_dir)
    assert merged.BasicInfo.save_path == str(attempt_dir / "survey.md")
    assert merged.BasicInfo.save_json_path == str(attempt_dir / "survey.json")
    assert merged.BasicInfo.evaluation_save_path == str(attempt_dir / "evaluation.txt")


def test_merge_derives_paths_when_survey_paths_are_not_explicit(
    monkeypatch, tmp_path: Path
) -> None:
    default_path = tmp_path / "default.yaml"
    output_root = tmp_path / "survey-output-root"
    _write_default_survey_config(default_path, output_root)
    monkeypatch.setattr(config_utils, "resolve_runtime_config_path", lambda: default_path)

    merged = config_utils.merge_with_default_survey_config(
        OmegaConf.create(
            {
                "survey": {
                    "BasicInfo": {
                        "topic": "A topic requiring derived paths",
                        "survey_run_id": "20260831-034619-359874",
                    }
                }
            }
        )
    )

    expected_dir = output_root / "20260831-034619-359874"
    assert merged.BasicInfo.base_dir == str(expected_dir)
    assert merged.BasicInfo.save_path == str(expected_dir / "survey.md")
    assert merged.BasicInfo.save_json_path == str(expected_dir / "survey.json")
    assert merged.BasicInfo.evaluation_save_path == str(expected_dir / "evaluation.txt")
