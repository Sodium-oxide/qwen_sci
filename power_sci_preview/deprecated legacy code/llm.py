from __future__ import annotations

from typing import Any

try:
    from .config import LLM_PROVIDER, QWEN_API_BASE, QWEN_API_KEY, QWEN_MODEL_ID
except ImportError:
    from config import LLM_PROVIDER, QWEN_API_BASE, QWEN_API_KEY, QWEN_MODEL_ID


_client: Any | None = None


def get_client() -> Any:
    global _client
    if _client is None:
        try:
            from .qwen_adapter import QwenClient
        except ImportError:
            from qwen_adapter import QwenClient
        if LLM_PROVIDER not in {"qwen", "dashscope"}:
            raise RuntimeError(
                f"Unsupported LLM_PROVIDER={LLM_PROVIDER!r}. This build only supports Qwen/DashScope."
            )
        _client = QwenClient(api_key=QWEN_API_KEY or "", model=QWEN_MODEL_ID, api_base=QWEN_API_BASE or "")
    return _client
