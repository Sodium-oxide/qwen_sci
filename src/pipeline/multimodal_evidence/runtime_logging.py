"""Small, dependency-free console logging for multimodal runtime stages."""

from __future__ import annotations

import logging
import re
import sys


_LOGGER_NAME = "QwenSci.Multimodal"
_MAX_ERROR_TEXT = 500
_SENSITIVE_VALUE = re.compile(
    r"(?i)(?:\b(?:api[_-]?key|authorization|token)\s*[:=]\s*(?:bearer\s+)?[^\s,;]+|\bbearer\s+[^\s,;]+)"
)


class _DynamicStderrHandler(logging.Handler):
    """Write through the current stderr so pipes and test capture keep working."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = self.format(record)
            print(message, file=sys.stderr, flush=True)
        except Exception:
            self.handleError(record)


def get_multimodal_logger() -> logging.Logger:
    """Return the process-local logger used by multimodal preparation."""

    logger = logging.getLogger(_LOGGER_NAME)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    if not any(isinstance(handler, _DynamicStderrHandler) for handler in logger.handlers):
        handler = _DynamicStderrHandler()
        handler.setLevel(logging.INFO)
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s | %(levelname)s | multimodal | %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )
        logger.addHandler(handler)
    return logger


def safe_exception_summary(exc: BaseException, *, limit: int = _MAX_ERROR_TEXT) -> str:
    """Summarize an exception chain without exposing credentials or payloads."""

    parts: list[str] = []
    current: BaseException | None = exc
    seen: set[int] = set()
    while current is not None and id(current) not in seen and len(parts) < 4:
        seen.add(id(current))
        detail = re.sub(r"\s+", " ", str(current)).strip()
        detail = _SENSITIVE_VALUE.sub("<redacted>", detail)
        label = type(current).__name__
        parts.append(f"{label}: {detail}" if detail else label)
        current = current.__cause__ or current.__context__
    return " <- ".join(parts)[:limit]


__all__ = ["get_multimodal_logger", "safe_exception_summary"]
