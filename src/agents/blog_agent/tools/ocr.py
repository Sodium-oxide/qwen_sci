#!/usr/bin/env python3
"""PaddleOCR mask generation with optional Qwen visual review."""

from __future__ import annotations

import copy
import os
import sys
import warnings
from typing import Any

import cv2
import numpy as np

current_dir = os.path.dirname(os.path.abspath(__file__))
src_root = os.path.abspath(os.path.join(current_dir, "..", ".."))
if src_root not in sys.path:
    sys.path.insert(0, src_root)

from src.config import load_config

_project_config = load_config()
_config = _project_config.get("blog", {})
_deeperaser_config = _config.get("deeperaser", {})
_DEFAULT_USE_CUDA = _deeperaser_config.get("use_cuda", False)

warnings.filterwarnings("ignore")

from blog_agent.utils.deeperaser import remove_text


def remove_text_from_image(
    workspace_dir: str,
    input_image: str,
    output_image: str,
    mask_image: str = None,
    use_cuda: bool = None,
    ocr_lang: str = "ch",
    text_det_unclip_ratio: float = 1.6,
    humancheckimg: str = None,
    vision_batch: bool = False,
) -> dict:
    """Detect text, create a mask, review high-confidence labels, and erase text."""
    input_path = os.path.join(workspace_dir, input_image)
    output_path = os.path.join(workspace_dir, output_image)
    if not os.path.exists(input_path):
        return {
            "success": False,
            "input_path": input_path,
            "mask_path": None,
            "output_path": output_path,
            "text_count": 0,
            "error": f"输入文件不存在: {input_path}",
        }

    if use_cuda is None:
        use_cuda = _DEFAULT_USE_CUDA
    mask_path = os.path.join(workspace_dir, mask_image or "_auto_mask.png")
    humancheck_path = os.path.join(workspace_dir, humancheckimg or "checkimg.png")

    _generate_mask_from_ocr(
        mask_path,
        input_path,
        ocr_lang=ocr_lang,
        text_det_unclip_ratio=text_det_unclip_ratio,
        humancheck_path=humancheck_path,
        vision_batch=vision_batch,
    )
    try:
        remove_text(
            input_image_path=input_path,
            mask_image_path=mask_path,
            output_image_path=output_path,
            use_cuda=use_cuda,
        )
        return {
            "success": True,
            "input_path": input_path,
            "mask_path": mask_path,
            "output_path": output_path,
            "text_count": -1,
            "error": None,
            "humancheck_path": humancheck_path,
        }
    except Exception as exc:
        return {
            "success": False,
            "input_path": input_path,
            "mask_path": mask_path,
            "output_path": output_path,
            "text_count": -1,
            "error": str(exc),
            "humancheck_path": humancheck_path,
        }


def _generate_mask_from_ocr(
    mask_path: str,
    image_path: str,
    ocr_lang: str = "ch",
    text_det_unclip_ratio: float = 1.6,
    humancheck_path: str = None,
    vision_batch: bool = False,
) -> None:
    """Use PaddleOCR for coordinates and Qwen VL for semantic label review."""
    from paddleocr import PaddleOCR

    ocr = PaddleOCR(
        lang=ocr_lang,
        use_doc_unwarping=False,
        use_doc_orientation_classify=False,
        device="cpu",
        text_det_unclip_ratio=text_det_unclip_ratio,
    )
    image = cv2.imread(image_path)
    if image is None:
        raise FileNotFoundError(f"无法读取图片: {image_path}")
    mask = np.zeros(image.shape[:2], dtype=np.uint8)
    text_data: list[tuple[str, Any, float]] = []
    for page in ocr.predict(image_path):
        texts = page.get("rec_texts", [])
        polys = page.get("dt_polys", [])
        scores = page.get("rec_scores", [])
        for text, poly, score in zip(texts, polys, scores):
            score = float(score)
            print(f"内容: {text} | 置信度: {score:.2f}")
            text_data.append((str(text), poly, score))

    valid_items = [item for item in text_data if item[2] >= 0.6]
    for _, poly, _ in valid_items:
        points = np.asarray(poly, np.int32).reshape((-1, 1, 2))
        cv2.fillPoly(mask, [points], 255)
    print(f"[OCR] 识别到 {len(valid_items)} 处文字区域（置信度>=0.6）")
    cv2.imwrite(mask_path, mask)
    if humancheck_path:
        _generate_humancheck_image(
            image,
            text_data,
            humancheck_path,
            vision_batch=vision_batch,
        )


def _generate_humancheck_image(
    image: np.ndarray,
    text_data: list[tuple[str, Any, float]],
    output_path: str,
    *,
    vision_batch: bool = False,
) -> None:
    """Draw local OCR confidence boxes and optional Qwen review boxes."""
    check_image = copy.deepcopy(image)
    valid_items = [item for item in text_data if item[2] >= 0.6]
    mid_conf_items = [item for item in valid_items if item[2] < 0.9]
    high_conf_items = [item for item in valid_items if item[2] >= 0.9]
    print(f"[HumanCheck] 中置信度(0.6-0.9): {len(mid_conf_items)} 处")
    print(f"[HumanCheck] 高置信度(>=0.9): {len(high_conf_items)} 处，需要Qwen视觉检查")

    for _, poly, _ in mid_conf_items:
        points = np.asarray(poly, np.int32).reshape((-1, 1, 2))
        cv2.polylines(check_image, [points], isClosed=True, color=(0, 0, 255), thickness=2)

    misspelled_indices: list[int] = []
    if high_conf_items:
        try:
            from src.llm.vision import QwenVisionClient, resolve_vision_settings

            settings = resolve_vision_settings(_project_config, batch=vision_batch)
            encoded_ok, encoded = cv2.imencode(".png", image)
            if not encoded_ok:
                raise RuntimeError("无法将图片编码为 PNG 供视觉模型复核")
            client = QwenVisionClient(
                model=settings["model"],
                provider=settings["provider"],
                api_key=settings["api_key"],
                base_url=settings["base_url"],
                timeout=settings["timeout"],
                config=_project_config,
            )
            review = client.review_ocr_labels(
                encoded.tobytes(),
                [text for text, _, _ in high_conf_items],
                max_tokens=settings["max_tokens"],
            )
            misspelled_indices = list(review.problematic_indices)
            print(f"[HumanCheck] Qwen视觉复核: {review.notes}")
        except Exception as exc:
            print(f"[HumanCheck] Qwen视觉复核失败，保留PaddleOCR结果: {exc}")

    for index in misspelled_indices:
        if 0 <= index < len(high_conf_items):
            _, poly, _ = high_conf_items[index]
            points = np.asarray(poly, np.int32).reshape((-1, 1, 2))
            cv2.polylines(check_image, [points], isClosed=True, color=(0, 255, 255), thickness=2)
    cv2.imwrite(output_path, check_image)
    print(f"[HumanCheck] 已保存到: {output_path}")


def remove_text_batch(
    workspace_dir: str,
    image_list: list,
    use_cuda: bool = False,
) -> list:
    """Batch processing uses the lower-cost Qwen VL model."""
    results = []
    for img_file in image_list:
        name, ext = os.path.splitext(img_file)
        results.append(
            remove_text_from_image(
                workspace_dir=workspace_dir,
                input_image=img_file,
                output_image=f"{name}_cleaned{ext}",
                use_cuda=use_cuda,
                vision_batch=True,
            )
        )
    return results
