from __future__ import annotations

import json
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from src.pipeline import science_stages
from src.pipeline.science_run import science_run_paths
from src.pipeline.science_stages import SurveyStageRequest
from src.webapp.log_service import RunLogError, list_run_logs, read_run_log


def _log_paths(tmp_path: Path):
    paths = science_run_paths(tmp_path / "run")
    log = paths.run_dir / "survey" / "attempt-001" / "console.log"
    log.parent.mkdir(parents=True)
    return paths, log


def test_live_log_waits_for_complete_utf8_records_and_redacts_before_delivery(tmp_path: Path):
    paths, log = _log_paths(tmp_path)
    record = "检索中 api_key=private-secret\n".encode("utf-8")
    log.write_bytes(record[:5])
    first = read_run_log(paths, log_id="survey:attempt-001/console.log", offset=0, limit=4096)
    assert first.content == ""
    assert first.next_offset == 0
    with log.open("ab") as handle:
        handle.write(record[5:])
    complete = read_run_log(paths, log_id=first.log_id, offset=first.next_offset, limit=4096)
    assert "检索中" in complete.content
    assert "private-secret" not in complete.content
    assert "[redacted]" in complete.content
    assert "�" not in complete.content
    assert complete.next_offset == len(record)
    assert not complete.has_more


def test_log_chunks_keep_records_whole_and_resume_after_truncation(tmp_path: Path):
    paths, log = _log_paths(tmp_path)
    record = "日志" * 1000 + " password=must-stay-private\n"
    log.write_text(record, encoding="utf-8")
    chunk = read_run_log(paths, log_id="survey:attempt-001/console.log", offset=0, limit=4096)
    assert chunk.next_offset == len(record.encode("utf-8"))
    assert "must-stay-private" not in chunk.content
    log.write_text("新尝试\n", encoding="utf-8")
    reset = read_run_log(paths, log_id=chunk.log_id, offset=chunk.next_offset, limit=4096)
    assert reset.offset == 0
    assert reset.content == "新尝试\n"


def test_terminal_escape_codes_are_removed_before_credential_redaction(tmp_path: Path):
    paths, log = _log_paths(tmp_path)
    log.write_text("\x1b[31mapi_key\x1b[0m=secret-value\n输出目录 /home/user/private/run\n", encoding="utf-8")
    chunk = read_run_log(paths, log_id="survey:attempt-001/console.log", offset=0, limit=4096)
    assert "\x1b" not in chunk.content
    assert "secret-value" not in chunk.content
    assert "/home/user" not in chunk.content
    assert "[local path]" in chunk.content


def test_logs_do_not_follow_links_outside_the_owned_stage(tmp_path: Path):
    paths, log = _log_paths(tmp_path)
    log.write_text("owned\n", encoding="utf-8")
    outside = tmp_path / "private.log"
    outside.write_text("private\n", encoding="utf-8")
    (log.parent / "escaped.log").symlink_to(outside)
    assert [source.log_id for source in list_run_logs(paths)] == ["survey:attempt-001/console.log"]
    with pytest.raises(RunLogError, match="Unknown"):
        read_run_log(paths, log_id="survey:attempt-001/escaped.log", offset=0, limit=4096)


@pytest.mark.parametrize("quiet", [False, True])
def test_survey_output_is_visible_before_the_child_process_finishes(tmp_path: Path, monkeypatch, capsys, quiet: bool):
    attempt = tmp_path / "attempt-001"
    attempt.mkdir()
    runtime_config = tmp_path / "runtime.yaml"
    runtime_config.write_text("{}", encoding="utf-8")
    (attempt / "survey_status.json").write_text(json.dumps({
        "survey_status": "insufficient_evidence", "topic": "public test topic", "reason": "test",
    }), encoding="utf-8")
    release = tmp_path / "release"
    child = (
        "import pathlib, sys, time\n"
        "print('实时检索已启动', flush=True)\n"
        "print('runtime warning', file=sys.stderr, flush=True)\n"
        "deadline = time.monotonic() + 15\n"
        f"while not pathlib.Path({str(release)!r}).exists() and time.monotonic() < deadline:\n"
        "    time.sleep(0.01)\n"
    )
    original_popen = subprocess.Popen
    options = {}

    def start_child(command, **kwargs):
        options.update(kwargs)
        return original_popen([sys.executable, "-u", "-c", child], **kwargs)

    monkeypatch.setattr(science_stages, "_survey_runtime_config", lambda _request: runtime_config)
    monkeypatch.setattr(science_stages, "_stage_environment", lambda _config: {})
    monkeypatch.setattr(science_stages.subprocess, "Popen", start_child)
    request = SurveyStageRequest(
        config_path=runtime_config, topic="public test topic", attempt_dir=attempt,
        survey_run_id="test-survey", quiet=quiet,
    )
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(science_stages.run_survey_stage, request)
        try:
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                log = attempt / "console.log"
                if log.exists() and "runtime warning" in log.read_text(encoding="utf-8"):
                    break
                time.sleep(0.01)
            assert "实时检索已启动" in log.read_text(encoding="utf-8")
            assert "runtime warning" in log.read_text(encoding="utf-8")
            assert not future.done()
        finally:
            release.touch()
        assert future.result(timeout=10).stage == "survey"
    console = capsys.readouterr()
    assert ("实时检索已启动" in console.out) is (not quiet)
    assert options["env"]["PYTHONUNBUFFERED"] == "1"
    assert options["env"]["PYTHONIOENCODING"] == "utf-8"
    assert options["stderr"] == subprocess.STDOUT
