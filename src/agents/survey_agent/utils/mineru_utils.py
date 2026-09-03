# Copyright (c) Opendatalab. All rights reserved.
import copy
import json
import os
from pathlib import Path

from loguru import logger

try:
    from .gpu_utils import get_preferred_device, get_cuda_visible_device_value
except ImportError:
    from utils.gpu_utils import get_preferred_device, get_cuda_visible_device_value


_MINERU_BACKEND = None
_MINERU_PROCESSING_WINDOW_SIZE_ENV = "MINERU_PROCESSING_WINDOW_SIZE"
_LEGACY_MINERU_BATCH_ENV = "MINERU_MIN_BATCH_INFERENCE_SIZE"
_DEFAULT_MINERU_PROCESSING_WINDOW_SIZE = 4


def _configure_mineru_page_batch_window() -> int:
    """Set MinerU 3.x's conservative processing window before it is imported.

    MinerU 3.x reads ``MINERU_PROCESSING_WINDOW_SIZE`` (its default is 64
    pages).  Preserve the previous environment variable as a one-way
    migration path for existing deployments, but always write the current
    variable that the 3.x pipeline actually consumes.
    """
    configured_value = os.environ.get(_MINERU_PROCESSING_WINDOW_SIZE_ENV)
    if configured_value is None:
        configured_value = os.environ.get(_LEGACY_MINERU_BATCH_ENV)
    if configured_value is None:
        os.environ[_MINERU_PROCESSING_WINDOW_SIZE_ENV] = str(
            _DEFAULT_MINERU_PROCESSING_WINDOW_SIZE
        )
        return _DEFAULT_MINERU_PROCESSING_WINDOW_SIZE

    try:
        parsed_value = int(configured_value)
        if parsed_value >= 1:
            os.environ[_MINERU_PROCESSING_WINDOW_SIZE_ENV] = str(parsed_value)
            return parsed_value
    except (TypeError, ValueError):
        pass

    logger.warning(
        "Invalid {}={!r}; using the conservative default {}.",
        _MINERU_PROCESSING_WINDOW_SIZE_ENV,
        configured_value,
        _DEFAULT_MINERU_PROCESSING_WINDOW_SIZE,
    )
    os.environ[_MINERU_PROCESSING_WINDOW_SIZE_ENV] = str(
        _DEFAULT_MINERU_PROCESSING_WINDOW_SIZE
    )
    return _DEFAULT_MINERU_PROCESSING_WINDOW_SIZE


def _load_mineru_backend():
    global _MINERU_BACKEND
    if _MINERU_BACKEND is not None:
        return _MINERU_BACKEND

    page_batch_window = _configure_mineru_page_batch_window()
    logger.info(
        "Configured MinerU processing window: "
        "MINERU_PROCESSING_WINDOW_SIZE={}",
        page_batch_window,
    )

    preferred_device = get_preferred_device()
    visible_value = get_cuda_visible_device_value(preferred_device)
    if visible_value is not None:
        os.environ["CUDA_DEVICE_ORDER"] = "PCI_BUS_ID"
        os.environ["CUDA_VISIBLE_DEVICES"] = visible_value
        logger.info(
            f"Configured MinerU to prefer {preferred_device} via CUDA_VISIBLE_DEVICES={visible_value}"
        )
    else:
        logger.info("Configured MinerU without CUDA pinning; CPU fallback will be used if needed.")

    from mineru.backend.pipeline.pipeline_analyze import (
        doc_analyze_streaming as pipeline_doc_analyze_streaming,
    )
    from mineru.backend.pipeline.pipeline_middle_json_mkcontent import (
        union_make as pipeline_union_make,
    )
    from mineru.backend.vlm.vlm_analyze import doc_analyze as vlm_doc_analyze
    from mineru.backend.vlm.vlm_middle_json_mkcontent import union_make as vlm_union_make
    from mineru.cli.common import convert_pdf_bytes_to_bytes, prepare_env, read_fn
    from mineru.data.data_reader_writer import FileBasedDataWriter
    from mineru.utils.draw_bbox import draw_layout_bbox, draw_span_bbox
    from mineru.utils.enum_class import MakeMode
    from mineru.utils.guess_suffix_or_lang import guess_suffix_by_path

    _MINERU_BACKEND = {
        "FileBasedDataWriter": FileBasedDataWriter,
        "MakeMode": MakeMode,
        "convert_pdf_bytes_to_bytes": convert_pdf_bytes_to_bytes,
        "draw_layout_bbox": draw_layout_bbox,
        "draw_span_bbox": draw_span_bbox,
        "guess_suffix_by_path": guess_suffix_by_path,
        "pipeline_doc_analyze_streaming": pipeline_doc_analyze_streaming,
        "pipeline_union_make": pipeline_union_make,
        "prepare_env": prepare_env,
        "read_fn": read_fn,
        "vlm_doc_analyze": vlm_doc_analyze,
        "vlm_union_make": vlm_union_make,
    }
    return _MINERU_BACKEND


def do_parse(
    output_dir,  # Output directory for storing parsing results
    pdf_file_names: list[str],  # List of PDF file names to be parsed
    pdf_bytes_list: list[bytes],  # List of PDF bytes to be parsed
    p_lang_list: list[str],  # List of languages for each PDF, default is 'ch' (Chinese)
    backend="pipeline",  # The backend for parsing PDF, default is 'pipeline'
    parse_method="auto",  # The method for parsing PDF, default is 'auto'
    formula_enable=True,  # Enable formula parsing
    table_enable=True,  # Enable table parsing
    server_url=None,  # Server URL for vlm-http-client backend
    f_draw_layout_bbox=True,  # Whether to draw layout bounding boxes
    f_draw_span_bbox=True,  # Whether to draw span bounding boxes
    f_dump_md=True,  # Whether to dump markdown files
    f_dump_middle_json=True,  # Whether to dump middle JSON files
    f_dump_model_output=True,  # Whether to dump model output files
    f_dump_orig_pdf=True,  # Whether to dump original PDF files
    f_dump_content_list=True,  # Whether to dump content list files
    f_make_md_mode=None,  # The mode for making markdown content, default is MM_MD
    start_page_id=0,  # Start page ID for parsing, default is 0
    end_page_id=None,  # End page ID for parsing, default is None (parse all pages until the end of the document)
):
    mineru = _load_mineru_backend()
    convert_pdf_bytes_to_bytes = mineru["convert_pdf_bytes_to_bytes"]
    FileBasedDataWriter = mineru["FileBasedDataWriter"]
    MakeMode = mineru["MakeMode"]
    pipeline_doc_analyze_streaming = mineru["pipeline_doc_analyze_streaming"]
    prepare_env = mineru["prepare_env"]
    if f_make_md_mode is None:
        f_make_md_mode = MakeMode.MM_MD

    if backend == "pipeline":
        for idx, pdf_bytes in enumerate(pdf_bytes_list):
            new_pdf_bytes = convert_pdf_bytes_to_bytes(
                pdf_bytes, start_page_id, end_page_id
            )
            pdf_bytes_list[idx] = new_pdf_bytes

        local_output_contexts = []
        image_writer_list = []
        for pdf_file_name in pdf_file_names:
            local_image_dir, local_md_dir = prepare_env(
                output_dir, pdf_file_name, parse_method
            )
            image_writer = FileBasedDataWriter(local_image_dir)
            local_output_contexts.append(
                (
                    pdf_file_name,
                    local_image_dir,
                    local_md_dir,
                    FileBasedDataWriter(local_md_dir),
                )
            )
            image_writer_list.append(image_writer)

        def on_doc_ready(doc_index, model_list, middle_json, _ocr_enable):
            (
                pdf_file_name,
                local_image_dir,
                local_md_dir,
                md_writer,
            ) = local_output_contexts[doc_index]
            _process_output(
                middle_json["pdf_info"],
                pdf_bytes_list[doc_index],
                pdf_file_name,
                local_md_dir,
                local_image_dir,
                md_writer,
                f_draw_layout_bbox,
                f_draw_span_bbox,
                f_dump_orig_pdf,
                f_dump_md,
                f_dump_content_list,
                f_dump_middle_json,
                f_dump_model_output,
                f_make_md_mode,
                middle_json,
                copy.deepcopy(model_list),
                is_pipeline=True,
            )

        pipeline_doc_analyze_streaming(
            pdf_bytes_list,
            image_writer_list,
            p_lang_list,
            on_doc_ready,
            parse_method=parse_method,
            formula_enable=formula_enable,
            table_enable=table_enable,
        )
    else:
        vlm_doc_analyze = mineru["vlm_doc_analyze"]
        if backend.startswith("vlm-"):
            backend = backend[4:]

        f_draw_span_bbox = False
        parse_method = "vlm"
        for idx, pdf_bytes in enumerate(pdf_bytes_list):
            pdf_file_name = pdf_file_names[idx]
            pdf_bytes = convert_pdf_bytes_to_bytes(
                pdf_bytes, start_page_id, end_page_id
            )
            local_image_dir, local_md_dir = prepare_env(
                output_dir, pdf_file_name, parse_method
            )
            image_writer, md_writer = FileBasedDataWriter(
                local_image_dir
            ), FileBasedDataWriter(local_md_dir)
            middle_json, infer_result = vlm_doc_analyze(
                pdf_bytes,
                image_writer=image_writer,
                backend=backend,
                server_url=server_url,
            )

            pdf_info = middle_json["pdf_info"]

            _process_output(
                pdf_info,
                pdf_bytes,
                pdf_file_name,
                local_md_dir,
                local_image_dir,
                md_writer,
                f_draw_layout_bbox,
                f_draw_span_bbox,
                f_dump_orig_pdf,
                f_dump_md,
                f_dump_content_list,
                f_dump_middle_json,
                f_dump_model_output,
                f_make_md_mode,
                middle_json,
                infer_result,
                is_pipeline=False,
            )


def _process_output(
    pdf_info,
    pdf_bytes,
    pdf_file_name,
    local_md_dir,
    local_image_dir,
    md_writer,
    f_draw_layout_bbox,
    f_draw_span_bbox,
    f_dump_orig_pdf,
    f_dump_md,
    f_dump_content_list,
    f_dump_middle_json,
    f_dump_model_output,
    f_make_md_mode,
    middle_json,
    model_output=None,
    is_pipeline=True,
):
    """处理输出文件"""
    mineru = _load_mineru_backend()
    draw_layout_bbox = mineru["draw_layout_bbox"]
    draw_span_bbox = mineru["draw_span_bbox"]
    MakeMode = mineru["MakeMode"]
    pipeline_union_make = mineru["pipeline_union_make"]
    vlm_union_make = mineru["vlm_union_make"]

    if f_draw_layout_bbox:
        draw_layout_bbox(
            pdf_info, pdf_bytes, local_md_dir, f"{pdf_file_name}_layout.pdf"
        )

    if f_draw_span_bbox:
        draw_span_bbox(pdf_info, pdf_bytes, local_md_dir, f"{pdf_file_name}_span.pdf")

    if f_dump_orig_pdf:
        md_writer.write(
            f"{pdf_file_name}_origin.pdf",
            pdf_bytes,
        )

    image_dir = str(os.path.basename(local_image_dir))

    if f_dump_md:
        make_func = pipeline_union_make if is_pipeline else vlm_union_make
        md_content_str = make_func(pdf_info, f_make_md_mode, image_dir)
        md_writer.write_string(
            f"{pdf_file_name}.md",
            md_content_str,
        )

    if f_dump_content_list:
        make_func = pipeline_union_make if is_pipeline else vlm_union_make
        content_list = make_func(pdf_info, MakeMode.CONTENT_LIST, image_dir)
        md_writer.write_string(
            f"{pdf_file_name}_content_list.json",
            json.dumps(content_list, ensure_ascii=False, indent=4),
        )

    if f_dump_middle_json:
        md_writer.write_string(
            f"{pdf_file_name}_middle.json",
            json.dumps(middle_json, ensure_ascii=False, indent=4),
        )

    if f_dump_model_output:
        md_writer.write_string(
            f"{pdf_file_name}_model.json",
            json.dumps(model_output, ensure_ascii=False, indent=4),
        )

    logger.info(f"local output dir is {local_md_dir}")


def parse_doc(
    path_list: list[Path],
    output_dir,
    lang="ch",
    backend="pipeline",
    method="auto",
    server_url=None,
    start_page_id=0,
    end_page_id=None,
):
    """
    Parameter description:
    path_list: List of document paths to be parsed, can be PDF or image files.
    output_dir: Output directory for storing parsing results.
    lang: Language option, default is 'ch', optional values include['ch', 'ch_server', 'ch_lite', 'en', 'korean', 'japan', 'chinese_cht', 'ta', 'te', 'ka']。
        Input the languages in the pdf (if known) to improve OCR accuracy.  Optional.
        Adapted only for the case where the backend is set to "pipeline"
    backend: the backend for parsing pdf:
        pipeline: More general.
        vlm-transformers: More general.
        vlm-vllm-engine: Faster(engine).
        vlm-http-client: Faster(client).
        without method specified, pipeline will be used by default.
    method: the method for parsing pdf:
        auto: Automatically determine the method based on the file type.
        txt: Use text extraction method.
        ocr: Use OCR method for image-based PDFs.
        Without method specified, 'auto' will be used by default.
        Adapted only for the case where the backend is set to "pipeline".
    server_url: When the backend is `http-client`, you need to specify the server_url, for example:`http://127.0.0.1:30000`
    start_page_id: Start page ID for parsing, default is 0
    end_page_id: End page ID for parsing, default is None (parse all pages until the end of the document)
    """
    try:
        mineru = _load_mineru_backend()
        read_fn = mineru["read_fn"]
        file_name_list = []
        pdf_bytes_list = []
        lang_list = []
        for path in path_list:
            file_name = str(Path(path).stem)
            pdf_bytes = read_fn(path)
            file_name_list.append(file_name)
            pdf_bytes_list.append(pdf_bytes)
            lang_list.append(lang)
        do_parse(
            output_dir=output_dir,
            pdf_file_names=file_name_list,
            pdf_bytes_list=pdf_bytes_list,
            p_lang_list=lang_list,
            backend=backend,
            parse_method=method,
            server_url=server_url,
            start_page_id=start_page_id,
            end_page_id=end_page_id,
        )
    except Exception as e:
        logger.exception(f"Error in mineru parse_doc: {e}")


if __name__ == "__main__":
    # For test purpose
    test_pdf_path_value = os.environ.get("SURVEY_AGENT_TEST_PDF_PATH")
    if not test_pdf_path_value:
        raise SystemExit("Set SURVEY_AGENT_TEST_PDF_PATH to a PDF file before running this module.")
    test_pdf_path = Path(test_pdf_path_value)
    parse_doc(
        path_list=[test_pdf_path],
        output_dir="./output/test_parse_doc",
        lang="ch",
        backend="pipeline",
        method="auto",
    )
