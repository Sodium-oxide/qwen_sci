"""Optional post-draft scientific figures for the Research Plan Author."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Mapping

from .markdown_renderer import render_research_plan_markdown


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _text(value: object) -> str:
    return str(value or "").strip()


class _NullLogger:
    def info(self, *_args: Any, **_kwargs: Any) -> None:
        return None

    def warning(self, *_args: Any, **_kwargs: Any) -> None:
        return None


class _AuthorChatAdapter:
    def __init__(self, callback: Callable[..., Any]) -> None:
        self.callback = callback

    def remote_chat(self, prompt: str, **kwargs: Any) -> str:
        response = self.callback(prompt, response_format="json_object", temperature=kwargs.get("temperature"), max_output_tokens=kwargs.get("max_output_tokens"))
        return response if isinstance(response, str) else json.dumps(response, ensure_ascii=False)


class AuthorVisualizer:
    """Run SurveyVisualizer on a completed Author document."""

    def __init__(self, *, config: Any, llm_call: Callable[..., Any] | None, logger: Any, image_client_factory: Callable[..., Any] | None = None, vision_client_factory: Callable[..., Any] | None = None) -> None:
        self.config = config
        self.llm_call = llm_call
        self.logger = logger or _NullLogger()
        self.image_client_factory = image_client_factory
        self.vision_client_factory = vision_client_factory

    def _settings(self) -> dict[str, Any]:
        root = _mapping(self.config)
        author = _mapping(root.get("research_plan_author"))
        settings = dict(_mapping(_mapping(root.get("ModuleInfo")).get("SurveyVisualization")))
        settings.update(_mapping(author.get("visualization")))
        return settings

    def run(self, document: Mapping[str, Any], *, output_dir: str | Path) -> dict[str, Any]:
        settings = self._settings()
        if not bool(settings.get("enabled", False)):
            return {"status": "disabled", "figure_count": 0, "figures": []}
        if self.llm_call is None:
            return {"status": "skipped_no_llm", "figure_count": 0, "figures": []}
        survey_root = Path(__file__).resolve().parents[1] / "survey_agent"
        if str(survey_root) not in sys.path:
            sys.path.insert(0, str(survey_root))
        from modules.survey_visualizer import SurveyVisualizer
        destination = Path(output_dir).expanduser().resolve()
        destination.mkdir(parents=True, exist_ok=True)
        source_path = destination / "author_visual_source.md"
        source_path.write_text(render_research_plan_markdown(document), encoding="utf-8")
        runtime_config = SimpleNamespace(ModuleInfo=SimpleNamespace(SurveyVisualization=SimpleNamespace(**settings)))
        kwargs: dict[str, Any] = {"config": runtime_config, "chat_agent": _AuthorChatAdapter(self.llm_call), "logger": self.logger, "project_config": self.config, "settings": settings}
        if self.image_client_factory is not None:
            kwargs["image_client_factory"] = self.image_client_factory
        if self.vision_client_factory is not None:
            kwargs["vision_client_factory"] = self.vision_client_factory
        result = SurveyVisualizer(**kwargs).run(
            source_path.read_text(encoding="utf-8"),
            survey_path=source_path,
            references=(),
            evidence_plan={},
            outline={},
            claim_traceability={},
            strict_evidence=bool(settings.get("strict_evidence", False)),
        )
        manifest_path = destination / "survey_visual_manifest.json"
        manifest: Mapping[str, Any] = {}
        if manifest_path.is_file():
            try:
                parsed = json.loads(manifest_path.read_text(encoding="utf-8"))
                manifest = parsed if isinstance(parsed, Mapping) else {}
            except (OSError, ValueError):
                manifest = {}
        figures: list[dict[str, Any]] = []
        for raw in manifest.get("figures", []):
            if not isinstance(raw, Mapping):
                continue
            file_name = _text(raw.get("file"))
            image_path = destination / file_name
            if not file_name or Path(file_name).name != file_name or not image_path.is_file():
                continue
            figures.append({"file": file_name, "source_path": str(image_path), "caption_en": _text(raw.get("caption_en")), "alt_text_en": _text(raw.get("alt_text_en")), "figure_id": _text(raw.get("figure_id")), "source_section_index": raw.get("source_section_index"), "source_section_title": _text(raw.get("source_section_title"))})
        if figures:
            (destination / "author_visual_manifest.json").write_text(json.dumps({"schema_version": "research_plan_author_visual_manifest_v1", "mode": "relaxed_manuscript_grounding", "source_markdown": source_path.name, "survey_visual_manifest": manifest_path.name, "figures": figures}, ensure_ascii=False, indent=2), encoding="utf-8")
        result = dict(result)
        result["figures"] = figures
        result["author_visual_manifest"] = str(destination / "author_visual_manifest.json") if figures else ""
        return result


__all__ = ["AuthorVisualizer"]
