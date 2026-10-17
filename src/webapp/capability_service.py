"""Runtime capability discovery for the web feature registry."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

from src.config import load_config
from src.llm.image_generation import resolve_image_generation_settings
from src.llm.provider_registry import resolve_provider, resolve_role_model

from .prompts.registry import TEXT_MODEL_CHOICES
from .redaction import safe_text


def _module_available(module_name: str) -> bool:
    try:
        return importlib.util.find_spec(module_name) is not None
    except (ImportError, ModuleNotFoundError, ValueError):
        return False


class CapabilityService:
    """Report optional runtime support without making feature requests guess."""

    def __init__(self, *, config_path: str | Path) -> None:
        self.config_path = Path(config_path).expanduser().resolve()

    def snapshot(self) -> dict[str, object]:
        config = load_config(str(self.config_path))
        text_models: dict[str, object] = {}
        for model_name in TEXT_MODEL_CHOICES:
            try:
                model = resolve_role_model(config, "worker", "qwen", model_name)
                provider = resolve_provider(config, model.provider)
                configured = bool(provider.api_key and provider.base_url)
                text_models[model_name] = {
                    "status": "configured" if configured else "unavailable",
                    "configured": configured,
                    "reason": None if configured else "The text provider credentials or endpoint are missing.",
                    "verified": False,
                    "verification": "not_checked",
                    "provider": model.provider,
                    "api_style": model.api_style,
                    "capabilities": {
                        name: bool(getattr(model.capabilities, name))
                        for name in (
                            "chat_completions",
                            "responses",
                            "json_object",
                            "vision",
                            "streaming",
                        )
                    },
                }
            except Exception as exc:
                text_models[model_name] = {
                    "status": "unavailable",
                    "reason": safe_text(str(exc))[:500],
                }

        try:
            image_settings = resolve_image_generation_settings(config, role="academic_figure")
            configured = bool(image_settings["api_key"] and image_settings["base_url"])
            image_capability: dict[str, object] = {
                "status": "configured" if configured else "unavailable",
                "configured": configured,
                "reason": None if configured else "The image provider credentials or endpoint are missing.",
                "verified": False,
                "verification": "not_checked",
                "provider": image_settings["provider"],
                "model": image_settings["model"],
                "role": "academic_figure",
            }
        except Exception as exc:
            image_capability = {
                "status": "unavailable",
                "role": "academic_figure",
                "reason": safe_text(str(exc))[:500],
            }

        return {
            "text_model_choices": list(TEXT_MODEL_CHOICES),
            "text_models": text_models,
            "figure": {
                "enabled": bool(config.get("figure", {}).get("enabled", True)),
                "python": self._python_figure_capability(),
                "r": self._r_capability(config),
                "image_generation": image_capability,
                "reference_image_editing": {"status": "unavailable", "reason": "The configured image adapter does not implement image editing."},
                "chart_types": ["line", "bar", "scatter", "hist", "box"],
                "planning_modes": ["auto", "model", "explicit"],
                "style_fields": ["x_label", "y_label", "title", "width_mm", "height_mm", "palette"],
                "style_revisions": True,
                "panels": "single",
            },
            "polish": {
                "enabled": bool(config.get("polish", {}).get("enabled", True)),
                "input_formats": ["text", "markdown", "latex", "docx"],
                "review_units": "segments", "selective_regeneration": True,
                "structured_content": "code and tables preserved verbatim",
                "docx_equations": "unsupported",
            },
            "translation": {
                "enabled": bool(config.get("translation", {}).get("enabled", True)),
                "pdf_parser": self._mineru_capability(config),
                "pdf_text": self._module_capability(
                    "pypdf", "pypdf is not installed; install the pdf extra."
                ),
                "page_renderer": self._module_capability(
                    "pypdfium2", "pypdfium2 is not installed; install the pdf extra."
                ),
                "ocr": self._ocr_capability(config),
                "modes": {
                    "text_preserving": {"status": "available" if _module_available("pypdf") else "unavailable"},
                    "image_page_translation": {"status": "unavailable", "reason": "Reference-image editing is not implemented."},
                },
                "review_units": "pages", "selective_regeneration": True,
                "layout_reconstruction": False,
            },
            "export": {
                "markdown": {"status": "available"},
                "json": {"status": "available"},
                "fidelity": "text, headings, source page/block map; source PDF layout is not reconstructed",
                "docx": self._module_capability(
                    "docx", "python-docx is not installed."
                ),
                "pdf": self._module_capability(
                    "reportlab", "reportlab is not installed; install the pdf extra."
                ),
            },
            "preferences": {"status": "available", "scope": "workspace", "versioned": True, "multiuser": False},
            "jobs": {"status": "available", "backend": "sqlite", "durable_events": True, "revision_identity": True},
        }

    @staticmethod
    def _python_figure_capability() -> dict[str, object]:
        missing = [
            module
            for module in ("matplotlib", "pandas", "PIL")
            if not _module_available(module)
        ]
        if missing:
            return {
                "status": "unavailable",
                "reason": f"Missing plotting modules: {', '.join(missing)}.",
            }
        return {"status": "available", "backend": "matplotlib"}

    @staticmethod
    def _r_capability(config: Any) -> dict[str, object]:
        if not bool(config.get("figure", {}).get("allow_r", False)):
            return {"status": "unavailable", "reason": "R figure execution is disabled by the server."}
        return {"status": "unavailable", "reason": "The R execution adapter is not implemented."}

    @staticmethod
    def _module_capability(module_name: str, reason: str) -> dict[str, object]:
        if not _module_available(module_name):
            return {"status": "unavailable", "reason": reason}
        return {"status": "available", "module": module_name}

    @staticmethod
    def _mineru_capability(config: Any) -> dict[str, object]:
        if str(config.get("translation", {}).get("parser_backend", "mineru")).casefold() != "mineru":
            return {"status": "unavailable", "reason": "The configured PDF parser is not MinerU."}
        if not _module_available("mineru"):
            return {"status": "unavailable", "reason": "MinerU is not installed; install the pdf extra."}
        try:
            from src.agents.survey_agent.utils.mineru_utils import parse_doc
            _ = parse_doc
        except Exception:
            return {"status": "unavailable", "reason": "The project MinerU adapter is unavailable."}
        return {
            "status": "configured",
            "backend": "mineru",
            "ocr_enabled": bool(config.get("translation", {}).get("ocr_enabled", True)),
            "verified": False,
            "verification": "parser_smoke_not_run",
        }

    @classmethod
    def _ocr_capability(cls, config: Any) -> dict[str, object]:
        parser = cls._mineru_capability(config)
        if parser.get("status") != "configured":
            return {"status": "unavailable", "reason": "MinerU OCR is not ready."}
        return {
            "status": "configured" if parser.get("ocr_enabled") else "disabled",
            "backend": "mineru",
            "verified": False,
            "verification": "parser_smoke_not_run",
        }
