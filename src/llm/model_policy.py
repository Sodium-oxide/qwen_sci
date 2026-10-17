"""Selectable text models shared by web contracts and research configuration."""

from typing import Literal


TextModelName = Literal["qwen3.6-flash", "qwen3.7-plus", "qwen3.8-flash", "qwen3.8-max"]
TEXT_MODEL_CHOICES = ("qwen3.6-flash", "qwen3.7-plus", "qwen3.8-flash", "qwen3.8-max")
MODEL_PROFILES = {"fast": "qwen3.6-flash", "balanced": "qwen3.8-flash", "quality": "qwen3.8-max"}


def validate_text_model(value: str) -> str:
    if value not in TEXT_MODEL_CHOICES:
        raise ValueError("Select a registered Qwen text model.")
    return value
