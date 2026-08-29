from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable, MutableMapping

from dotenv import load_dotenv


SUBPROCESS_ENV_KEYS = (
    "QWENSCI_CONFIG",
    "QWENSCI_CONFIG_PATH",
    "QWENSCI_LLM_PROVIDER",
    "OPENAI_API_KEY",
    "OPENAI_API_BASE",
    "OPENAI_BASE_URL",
    "OPENAI_MODEL",
    "DASHSCOPE_API_KEY",
    "DASHSCOPE_BASE_URL",
    "DASHSCOPE_IMAGE_BASE_URL",
    "MEMORY_LLM_PROVIDER",
    "MEMORY_LLM_MODEL",
    "VISION_LLM_PROVIDER",
    "VISION_QUALITY_MODEL",
    "VISION_BATCH_MODEL",
    "IMAGE_GENERATION_PROVIDER",
    "IMAGE_ACADEMIC_FIGURE_MODEL",
    "IMAGE_TEXT_RICH_FIGURE_MODEL",
    "IMAGE_DRAFT_MODEL",
    "SURVEY_LLM_MODEL",
    "SURVEY_JUDGE_PROVIDER",
    "SURVEY_JUDGE_MODEL",
    "BLOG_LLM_PROVIDER",
    "BLOG_LLM_MODEL",
    "S2_API_KEY",
    "S2_API_TIMEOUT",
    "SEMANTIC_SCHOLAR_API_KEY",
    "SERPER_API_KEY",
    "MINIMAX_API_KEY",
    "JINA_API_KEY",
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "ANTHROPIC_BASE_URL",
    "HF_TOKEN",
    "http_proxy",
    "https_proxy",
    "OPENHANDS_MCP_TIMEOUT",
)


def hydrate_subprocess_env(
    env: MutableMapping[str, str],
    env_files: Iterable[Path],
) -> MutableMapping[str, str]:
    for env_file in env_files:
        if not env_file.exists():
            continue
        load_dotenv(env_file, override=False)
    for key in SUBPROCESS_ENV_KEYS:
        if not env.get(key):
            value = os.environ.get(key)
            if value:
                env[key] = value
    return env
