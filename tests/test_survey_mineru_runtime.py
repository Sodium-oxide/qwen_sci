import os
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SURVEY_AGENT_ROOT = PROJECT_ROOT / "src" / "agents" / "survey_agent"
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(SURVEY_AGENT_ROOT))

from utils import mineru_utils


def test_mineru_page_window_defaults_to_four_for_constrained_workstations(monkeypatch):
    monkeypatch.delenv("MINERU_MIN_BATCH_INFERENCE_SIZE", raising=False)
    monkeypatch.delenv("MINERU_PROCESSING_WINDOW_SIZE", raising=False)

    assert mineru_utils._configure_mineru_page_batch_window() == 4
    assert os.environ["MINERU_PROCESSING_WINDOW_SIZE"] == "4"


def test_mineru_page_window_respects_explicit_environment_override(monkeypatch):
    monkeypatch.setenv("MINERU_PROCESSING_WINDOW_SIZE", "24")

    assert mineru_utils._configure_mineru_page_batch_window() == 24
    assert os.environ["MINERU_PROCESSING_WINDOW_SIZE"] == "24"


def test_mineru_page_window_recovers_from_invalid_environment_value(monkeypatch):
    monkeypatch.setenv("MINERU_PROCESSING_WINDOW_SIZE", "not-an-integer")

    assert mineru_utils._configure_mineru_page_batch_window() == 4
    assert os.environ["MINERU_PROCESSING_WINDOW_SIZE"] == "4"


def test_mineru_page_window_migrates_the_legacy_environment_variable(monkeypatch):
    monkeypatch.delenv("MINERU_PROCESSING_WINDOW_SIZE", raising=False)
    monkeypatch.setenv("MINERU_MIN_BATCH_INFERENCE_SIZE", "12")

    assert mineru_utils._configure_mineru_page_batch_window() == 12
    assert os.environ["MINERU_PROCESSING_WINDOW_SIZE"] == "12"


def test_pipeline_backend_uses_mineru_3_streaming_callback_api(monkeypatch, tmp_path):
    class _Writer:
        def __init__(self, path):
            self.path = path

    class _MakeMode:
        MM_MD = "mm-md"

    received = {}
    outputs = []

    def fake_prepare_env(output_dir, file_name, parse_method):
        return str(tmp_path / file_name / "images"), str(tmp_path / file_name / parse_method)

    def fake_streaming(
        pdf_bytes_list,
        image_writer_list,
        lang_list,
        on_doc_ready,
        **kwargs,
    ):
        received["pdf_bytes_list"] = pdf_bytes_list
        received["image_writer_list"] = image_writer_list
        received["lang_list"] = lang_list
        received["kwargs"] = kwargs
        on_doc_ready(1, [{"page": 1}], {"pdf_info": ["second"]}, False)
        on_doc_ready(0, [{"page": 0}], {"pdf_info": ["first"]}, False)

    backend = {
        "FileBasedDataWriter": _Writer,
        "MakeMode": _MakeMode,
        "convert_pdf_bytes_to_bytes": lambda pdf, *_: pdf,
        "pipeline_doc_analyze_streaming": fake_streaming,
        "prepare_env": fake_prepare_env,
    }
    monkeypatch.setattr(mineru_utils, "_load_mineru_backend", lambda: backend)
    monkeypatch.setattr(
        mineru_utils,
        "_process_output",
        lambda *args, **kwargs: outputs.append((args, kwargs)),
    )

    mineru_utils.do_parse(
        output_dir=tmp_path,
        pdf_file_names=["first", "second"],
        pdf_bytes_list=[b"first-pdf", b"second-pdf"],
        p_lang_list=["en", "ch"],
        backend="pipeline",
    )

    assert received["pdf_bytes_list"] == [b"first-pdf", b"second-pdf"]
    assert received["lang_list"] == ["en", "ch"]
    assert received["kwargs"] == {
        "parse_method": "auto",
        "formula_enable": True,
        "table_enable": True,
    }
    assert [output[0][2] for output in outputs] == ["second", "first"]
    assert [output[0][1] for output in outputs] == [b"second-pdf", b"first-pdf"]
