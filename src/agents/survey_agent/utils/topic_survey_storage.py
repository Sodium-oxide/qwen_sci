from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Optional

from omegaconf import OmegaConf

from src.agents.idea_agent.agent.base import AgentBase
from src.agents.idea_agent.utils.core.response_parsing import parse_json_response
from src.pipeline.survey_handoff_persistence import verify_survey_manifest_artifacts


REPO_ROOT = Path(__file__).resolve().parents[4]
WORKSPACE_ROOT = (REPO_ROOT / "workspace").resolve()
DEFAULT_SURVEY_OUTPUT_ROOT = (Path(__file__).resolve().parents[1] / "outputs").resolve()
_SURVEY_RUN_ID_PATTERN = re.compile(r"^\d{8}-\d{6}-\d{6}$")
_LEGACY_SURVEY_DIRECTORY_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,120}$")


@dataclass(frozen=True)
class SurveyArtifactPaths:
    topic: str
    topic_slug: str
    research_run_id: str
    base_dir: Path
    markdown_path: Path
    json_path: Path
    evaluation_path: Path

    def exists(self) -> bool:
        return self.markdown_path.exists() and self.json_path.exists()


def normalize_topic_slug(topic: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", str(topic or "").strip().lower())
    slug = slug.strip("-")
    return slug or "topic"


def create_survey_run_id() -> str:
    """Return a filesystem-safe ID representing the Survey research start time."""

    return datetime.now().strftime("%Y%m%d-%H%M%S-%f")


def _resolve_survey_run_id(value: Any = "") -> str:
    candidate = str(value or "").strip()
    if candidate and (
        _SURVEY_RUN_ID_PATTERN.fullmatch(candidate)
        or _LEGACY_SURVEY_DIRECTORY_PATTERN.fullmatch(candidate)
    ):
        return candidate
    return create_survey_run_id()


def _to_raw_container(config: Optional[Any]) -> Any:
    if config is None:
        return None
    if OmegaConf.is_config(config):
        return OmegaConf.to_container(config, resolve=False)
    return config


def _raw_select(config: Optional[Any], key: str) -> Any:
    current = _to_raw_container(config)
    for part in key.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def _resolve_path_placeholders(value: Any) -> str:
    return (
        str(value)
        .replace("${repo_root}", str(REPO_ROOT.resolve()))
        .replace("${workspace}", str(WORKSPACE_ROOT))
    )


def get_survey_output_root(config: Optional[Any] = None) -> Path:
    configured_root = _raw_select(config, "output.root_dir")
    if configured_root:
        return Path(_resolve_path_placeholders(configured_root)).expanduser().resolve()

    base_dir = _raw_select(config, "BasicInfo.base_dir")
    if base_dir:
        base_path = Path(_resolve_path_placeholders(base_dir)).expanduser()
        if base_path.name == "outputs":
            return base_path.resolve()
        return (base_path.parent if base_path.name else base_path).resolve()

    return DEFAULT_SURVEY_OUTPUT_ROOT


def build_survey_artifact_paths(
    topic: str,
    *,
    output_root: Optional[str | Path] = None,
    config: Optional[Any] = None,
    research_run_id: Optional[str] = None,
) -> SurveyArtifactPaths:
    root = (
        Path(output_root).expanduser().resolve()
        if output_root is not None
        else get_survey_output_root(config)
    )
    run_id = _resolve_survey_run_id(research_run_id)
    base_dir = root / run_id
    return SurveyArtifactPaths(
        topic=str(topic or "").strip(),
        topic_slug=run_id,
        research_run_id=run_id,
        base_dir=base_dir,
        markdown_path=base_dir / "survey.md",
        json_path=base_dir / "survey.json",
        evaluation_path=base_dir / "evaluation.txt",
    )


def apply_topic_survey_paths(
    config: Any,
    topic: str,
    *,
    output_root: Optional[str | Path] = None,
    research_run_id: Optional[str] = None,
) -> SurveyArtifactPaths:
    configured_run_id = research_run_id or OmegaConf.select(
        config,
        "BasicInfo.survey_run_id",
    )
    artifacts = build_survey_artifact_paths(
        topic,
        output_root=output_root,
        config=config,
        research_run_id=configured_run_id,
    )
    return apply_existing_survey_artifact_paths(config, artifacts)


def apply_existing_survey_artifact_paths(
    config: Any,
    artifacts: SurveyArtifactPaths,
) -> SurveyArtifactPaths:
    OmegaConf.update(config, "BasicInfo.topic", artifacts.topic, merge=False)
    OmegaConf.update(
        config,
        "BasicInfo.survey_run_id",
        artifacts.research_run_id,
        merge=False,
    )
    OmegaConf.update(config, "BasicInfo.base_dir", str(artifacts.base_dir), merge=False)
    OmegaConf.update(config, "BasicInfo.save_path", str(artifacts.markdown_path), merge=False)
    OmegaConf.update(config, "BasicInfo.save_json_path", str(artifacts.json_path), merge=False)
    OmegaConf.update(config, "BasicInfo.evaluation_save_path", str(artifacts.evaluation_path), merge=False)
    return artifacts


def load_stored_survey_artifacts(
    *,
    output_root: Optional[str | Path] = None,
    config: Optional[Any] = None,
) -> list[SurveyArtifactPaths]:
    root = (
        Path(output_root).expanduser().resolve()
        if output_root is not None
        else get_survey_output_root(config)
    )
    if not root.exists():
        return []

    artifacts: list[SurveyArtifactPaths] = []
    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        standard_markdown = child / "survey.md"
        standard_json = child / "survey.json"
        if standard_markdown.exists() and standard_json.exists():
            manifest_path = child / "survey_manifest.json"
            if manifest_path.exists():
                if verify_survey_manifest_artifacts(manifest_path, base_dir=child):
                    continue
            topic = ""
            payload: dict[str, Any] = {}
            try:
                payload = json.loads(standard_json.read_text(encoding="utf-8"))
                topic = str(payload.get("topic") or "").strip()
            except Exception:
                topic = ""
            artifacts.append(
                SurveyArtifactPaths(
                    topic=topic or child.name.replace("-", " "),
                    topic_slug=child.name,
                    research_run_id=str(payload.get("research_run_id") or child.name),
                    base_dir=child,
                    markdown_path=standard_markdown,
                    json_path=standard_json,
                    evaluation_path=child / "evaluation.txt",
                )
            )
            continue

        for json_path in sorted(child.glob("*.json")):
            markdown_path = child / f"{json_path.stem}.md"
            if not markdown_path.exists():
                continue
            topic = ""
            payload = {}
            try:
                payload = json.loads(json_path.read_text(encoding="utf-8"))
                topic = str(payload.get("topic") or "").strip()
            except Exception:
                topic = ""
            artifacts.append(
                SurveyArtifactPaths(
                    topic=topic or json_path.stem.replace("_", " ").replace("-", " "),
                    topic_slug=normalize_topic_slug(topic or json_path.stem),
                    research_run_id=str(payload.get("research_run_id") or child.name),
                    base_dir=child,
                    markdown_path=markdown_path,
                    json_path=json_path,
                    evaluation_path=child / "evaluation.txt",
                )
            )
    return artifacts


def _topic_similarity_score(left: str, right: str) -> float:
    left_slug = normalize_topic_slug(left)
    right_slug = normalize_topic_slug(right)
    left_tokens = set(filter(None, left_slug.split("-")))
    right_tokens = set(filter(None, right_slug.split("-")))
    token_score = (
        len(left_tokens & right_tokens) / len(left_tokens | right_tokens)
        if left_tokens or right_tokens
        else 0.0
    )
    return max(token_score, SequenceMatcher(None, left_slug, right_slug).ratio())


_SURVEY_REUSE_PROMPT = """You are judging whether an existing survey topic can be directly reused for a requested idea-generation topic.

Target topic:
{target_topic}

Candidate surveys:
{candidate_block}

Return JSON only:
{{
  "reuse": true or false,
  "topic_slug": "candidate slug if reuse=true, else empty string",
  "reason": "one short sentence"
}}

Reuse only when the candidate survey is essentially the same topic or a very close paraphrase with matching scope. If the candidate is only adjacent, broader, narrower, or a different subproblem, return reuse=false."""


def find_reusable_survey(
    topic: str,
    *,
    output_root: Optional[str | Path] = None,
    config: Optional[Any] = None,
    judge_model: str = "gpt-5-mini",
    shortlist_size: int = 8,
) -> Optional[SurveyArtifactPaths]:
    stored = load_stored_survey_artifacts(output_root=output_root, config=config)
    if not stored:
        return None
    target_slug = normalize_topic_slug(topic)
    for item in stored:
        if normalize_topic_slug(item.topic or item.topic_slug) == target_slug and item.exists():
            return item

    ranked = sorted(
        stored,
        key=lambda item: _topic_similarity_score(topic, item.topic or item.topic_slug),
        reverse=True,
    )
    shortlist = ranked[: max(1, shortlist_size)]
    candidate_block = "\n".join(
        f"- slug: {item.topic_slug} | topic: {item.topic}"
        for item in shortlist
    )

    try:
        response = AgentBase().chat(
            _SURVEY_REUSE_PROMPT.format(target_topic=topic, candidate_block=candidate_block),
            model=judge_model,
            temperature=0.1,
            max_output_tokens=512,
        )
        payload = parse_json_response(response)
    except Exception:
        return None

    if not isinstance(payload, dict) or not bool(payload.get("reuse")):
        return None

    chosen_slug = normalize_topic_slug(str(payload.get("topic_slug") or ""))
    for item in shortlist:
        if item.topic_slug == chosen_slug and item.exists():
            return item
    return None
