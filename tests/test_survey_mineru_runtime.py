import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


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


@pytest.fixture
def mineru_output(monkeypatch, tmp_path):
    state = SimpleNamespace(events=[], warnings=[], failed_bbox=set())

    class _Writer:
        def __init__(self, path):
            self.path = Path(path)
            self.path.mkdir(parents=True, exist_ok=True)

        def write(self, filename, content):
            (self.path / filename).write_bytes(content)
            state.events.append(("write", filename))

        def write_string(self, filename, content):
            (self.path / filename).write_text(content, encoding="utf-8")
            state.events.append(("write", filename))

    class _MakeMode:
        MM_MD = "mm-md"
        CONTENT_LIST = "content-list"

    def draw_bbox(kind, pdf_info, pdf_bytes, output_dir, filename):
        state.events.append(("draw", filename))
        if kind in state.failed_bbox:
            raise RuntimeError(
                "Limit reached while decompressing. 12014599 bytes remaining."
            )
        (Path(output_dir) / filename).write_bytes(b"annotated-pdf")

    def make_content(backend, pdf_info, mode, image_dir):
        if mode == _MakeMode.CONTENT_LIST:
            return [{"type": "text", "text": "body"}]
        return f"# {backend} markdown"

    state.backend = {
        "FileBasedDataWriter": _Writer,
        "MakeMode": _MakeMode,
        "convert_pdf_bytes_to_bytes": lambda pdf, *_: pdf,
        "draw_layout_bbox": lambda *args: draw_bbox("layout", *args),
        "draw_span_bbox": lambda *args: draw_bbox("span", *args),
        "pipeline_union_make": lambda *args: make_content("pipeline", *args),
        "vlm_union_make": lambda *args: make_content("vlm", *args),
    }
    monkeypatch.setattr(mineru_utils, "_load_mineru_backend", lambda: state.backend)
    monkeypatch.setattr(
        mineru_utils,
        "logger",
        SimpleNamespace(
            warning=lambda message, *args: state.warnings.append(message.format(*args)),
            info=lambda *args: None,
        ),
    )

    state.output_dir = tmp_path / "paper" / "auto"
    state.options = {
        "pdf_info": [{"page": 0}],
        "pdf_bytes": b"original-pdf",
        "pdf_file_name": "paper",
        "local_md_dir": str(state.output_dir),
        "local_image_dir": str(state.output_dir / "images"),
        "md_writer": _Writer(state.output_dir),
        "f_draw_layout_bbox": True,
        "f_draw_span_bbox": True,
        "f_dump_orig_pdf": True,
        "f_dump_md": True,
        "f_dump_content_list": True,
        "f_dump_middle_json": True,
        "f_dump_model_output": True,
        "f_make_md_mode": _MakeMode.MM_MD,
        "middle_json": {"pdf_info": [{"page": 0}]},
        "model_output": [{"page": 0}],
    }
    return state


@pytest.mark.parametrize("is_pipeline", [True, False], ids=["pipeline", "vlm"])
@pytest.mark.parametrize("failed_bbox", [(), ("layout",), ("span",), ("layout", "span")])
def test_parsed_outputs_survive_optional_bbox_failures(mineru_output, is_pipeline, failed_bbox):
    state = mineru_output
    state.failed_bbox.update(failed_bbox)

    mineru_utils._process_output(**state.options, is_pipeline=is_pipeline)

    backend = "pipeline" if is_pipeline else "vlm"
    assert (state.output_dir / "paper.md").read_text() == f"# {backend} markdown"
    assert (state.output_dir / "paper_origin.pdf").read_bytes() == b"original-pdf"
    expected_files = {
        "paper.md",
        "paper_origin.pdf",
        "paper_content_list.json",
        "paper_middle.json",
        "paper_model.json",
    }
    assert all((state.output_dir / filename).is_file() for filename in expected_files)
    first_draw = next(index for index, event in enumerate(state.events) if event[0] == "draw")
    assert {filename for _, filename in state.events[:first_draw]} == expected_files
    assert [filename for action, filename in state.events if action == "draw"] == [
        "paper_layout.pdf",
        "paper_span.pdf",
    ]
    assert len(state.warnings) == len(failed_bbox)
    for kind in failed_bbox:
        assert any(
            f"paper_{kind}.pdf" in warning
            and "Limit reached while decompressing" in warning
            for warning in state.warnings
        )


def test_markdown_write_failure_is_not_treated_as_optional(mineru_output, monkeypatch):
    def fail_write(*args):
        raise OSError("Markdown write failed")

    monkeypatch.setattr(mineru_output.options["md_writer"], "write_string", fail_write)

    with pytest.raises(OSError, match="Markdown write failed"):
        mineru_utils._process_output(**mineru_output.options)

    assert not any(action == "draw" for action, _ in mineru_output.events)
    assert not mineru_output.warnings


def test_bbox_failures_do_not_abort_later_documents_in_streaming_batch(mineru_output, tmp_path):
    state = mineru_output
    state.failed_bbox.update(("layout", "span"))

    def prepare_env(output_dir, filename, parse_method):
        md_dir = Path(output_dir) / filename / parse_method
        return str(md_dir / "images"), str(md_dir)

    def streaming(pdf_bytes_list, image_writers, languages, on_doc_ready, **kwargs):
        for index in range(len(pdf_bytes_list)):
            on_doc_ready(index, [{"page": 0}], {"pdf_info": [{"page": 0}]}, False)

    state.backend.update(
        prepare_env=prepare_env,
        pipeline_doc_analyze_streaming=streaming,
    )

    mineru_utils.do_parse(
        output_dir=tmp_path,
        pdf_file_names=["first", "second"],
        pdf_bytes_list=[b"first-pdf", b"second-pdf"],
        p_lang_list=["en", "en"],
    )

    for filename in ("first", "second"):
        assert (tmp_path / filename / "auto" / f"{filename}.md").read_text() == (
            "# pipeline markdown"
        )
    assert len(state.warnings) == 4
