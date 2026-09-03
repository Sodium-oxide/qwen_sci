import os
import re
import sys


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SURVEY_AGENT_ROOT = os.path.join(PROJECT_ROOT, "src", "agents", "survey_agent")
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, SURVEY_AGENT_ROOT)

from modules.work_analyzer import WorkAnalyzer
from utils.file_utils import save_analysis_artifacts


def test_analysis_artifact_names_use_resolved_domain_and_hhmmss(tmp_path):
    topic = "When will the universe die? Better astrophysics will determine its fate. " * 40

    save_analysis_artifacts(
        tmp_path / "survey.md",
        topic,
        relation_graph={},
        relation_table={},
        intra_analysis_results=[],
        inter_analysis_results="",
    )

    names = sorted(path.name for path in (tmp_path / "analysis").iterdir())
    expected_suffixes = {
        "relation_graph.json",
        "relation_table.json",
        "intra_cluster_analysis.json",
        "inter_cluster_analysis.tex",
    }
    matches = [
        re.fullmatch(r"(physics_astronomy_\d{6})_(.+)", name)
        for name in names
    ]

    assert len(names) == 4
    assert all(matches)
    assert len({match.group(1) for match in matches}) == 1
    assert {match.group(2) for match in matches} == expected_suffixes
    assert all(len(name.encode("utf-8")) < 120 for name in names)


def test_cluster_table_validator_normalizes_a_common_bare_row_list():
    raw_response = """[
      {
        "paper_id": "W1",
        "paper_title": "Paper One",
        "columns": {"Method": "Simulation", "Evidence": "Observational"}
      },
      {
        "paper_id": "W2",
        "paper_title": "Paper Two",
        "columns": {"Method": "Analytical", "Evidence": "Theoretical"}
      }
    ]"""

    valid, table = WorkAnalyzer._validate_cluster_table(raw_response, {})

    assert valid is True
    assert table == {
        "comparison_dimensions": ["Method", "Evidence"],
        "table_data": [
            {
                "paper_id": "W1",
                "paper_title": "Paper One",
                "columns": {"Method": "Simulation", "Evidence": "Observational"},
            },
            {
                "paper_id": "W2",
                "paper_title": "Paper Two",
                "columns": {"Method": "Analytical", "Evidence": "Theoretical"},
            },
        ],
    }


def test_cluster_table_validator_retries_invalid_rows_and_formatter_uses_normalized_schema():
    malformed_response = '["not a table row"]'

    try:
        WorkAnalyzer._validate_cluster_table(malformed_response, {})
    except ValueError as exc:
        assert "Every cluster-table row" in str(exc)
    else:
        raise AssertionError("A non-row list must be rejected so the LLM request is retried.")

    rendered = WorkAnalyzer.format_analysis_table(
        object.__new__(WorkAnalyzer),
        {
            "cluster-a": [
                {"paper_title": "Paper One", "Method": "Simulation"},
                {"paper_title": "Paper Two", "Method": "Analytical"},
            ]
        },
    )
    assert "| Title | Method |" in rendered
    assert "| Paper One | Simulation |" in rendered


def test_cluster_table_requests_json_object_when_provider_declares_support():
    """The strict row validator should be paired with provider JSON mode."""

    captured = {}

    class _ChatAgent:
        def supports_response_format(self, response_format):
            return response_format == "json_object"

        def batch_remote_chat_with_retry(self, **kwargs):
            captured.update(kwargs)
            return [
                {
                    "comparison_dimensions": ["Method"],
                    "table_data": [
                        {
                            "paper_id": "W1",
                            "paper_title": "Paper One",
                            "columns": {"Method": "Simulation"},
                        }
                    ],
                }
            ]

    analyzer = object.__new__(WorkAnalyzer)
    analyzer.config = type(
        "Config",
        (),
        {
            "BasicInfo": type("BasicInfo", (), {"debug": False})(),
            "ModuleInfo": type(
                "ModuleInfo",
                (),
                {
                    "WorkAnalyzer": type(
                        "WorkAnalyzerConfig",
                        (),
                        {
                            "cluster_table_max_retry": 3,
                            "cluster_table_temperature": 0.3,
                        },
                    )()
                },
            )(),
        },
    )()
    analyzer.chat_agent = _ChatAgent()

    result = analyzer.generate_cluster_tables(
        [{"cluster_name": "cluster-a", "summary": "", "papers": []}]
    )

    assert captured["response_format"] == "json_object"
    assert captured["future_timeout"] == 300.0
    assert result["cluster-a"]["table_data"][0]["paper_id"] == "W1"
