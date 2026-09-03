import os
import traceback
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, Any

from omegaconf import OmegaConf

from src.agents.idea_agent.agent.artifacts import artifact_set
from src.agents.idea_agent.agent.ligagent import LigAgent
from src.agents.idea_agent.utils.core.ablation_inputs import (
    ingest_ablation_results_if_available,
)
from src.agents.idea_agent.utils.core.logger import get_logger, init_logger
from src.agents.idea_agent.utils.core.config_loader import (
    get_config_value,
    load_idea_agent_config,
    load_project_config,
)
from src.agents.idea_agent.utils.core.json_utils import read_json_file
from src.agents.idea_agent.utils.core.run_inputs import clean_optional_text, load_topic, resolve_run_inputs
from src.agents.idea_agent.utils.workflow.idea_contract import (
    normalize_idea_contract,
    normalize_mature_ideas,
    mature_idea_legacy_text,
)
from src.agents.idea_agent.utils.workflow.ligagent_flow import run_agent_loop
from src.pipeline.survey_idea_loader import (
    SurveyIdeaContext,
    SurveyIdeaLoadError,
    load_survey_idea_context,
)
from src.research_run_ids import create_research_run_id

DEFAULT_OUTPUT_ROOT = Path(__file__).resolve().parent / "runs"
IDEA_AGENT_ROOT = Path(__file__).resolve().parent

def _load_previous_idea_candidate() -> Optional[Dict[str, Any]]:
    previous_candidate_path = clean_optional_text(os.getenv("IDEA_AGENT_PREVIOUS_CANDIDATE_PATH"))
    if not previous_candidate_path:
        return None
    payload = read_json_file(Path(previous_candidate_path))
    return normalize_idea_contract(payload, allow_legacy=True, keep_extra=True)


def _resolve_runtime_survey_config(
    survey_config: Optional[object],
    survey_context: Optional[SurveyIdeaContext],
) -> tuple[Optional[object], Optional[str]]:
    if survey_context is None:
        return None, None
    if survey_config is None:
        fallback_project_config = load_project_config(
            str(Path(__file__).resolve().parents[2] / "config" / "default.yaml")
        )
        survey_config = fallback_project_config.get("survey")
    runtime_config = OmegaConf.create(OmegaConf.to_container(survey_config, resolve=False))
    base_dir = survey_context.base_dir
    OmegaConf.update(runtime_config, "BasicInfo.topic", survey_context.topic, merge=False)
    OmegaConf.update(runtime_config, "BasicInfo.survey_run_id", survey_context.survey_run_id, merge=False)
    OmegaConf.update(
        runtime_config,
        "BasicInfo.survey_manifest_path",
        str(survey_context.manifest_path),
        merge=False,
    )
    OmegaConf.update(runtime_config, "BasicInfo.base_dir", str(base_dir), merge=False)
    OmegaConf.update(runtime_config, "BasicInfo.save_path", str(base_dir / "survey.md"), merge=False)
    OmegaConf.update(runtime_config, "BasicInfo.save_json_path", str(base_dir / "survey.json"), merge=False)
    OmegaConf.update(
        runtime_config,
        "BasicInfo.evaluation_save_path",
        str(base_dir / "evaluation.txt"),
        merge=False,
    )
    OmegaConf.update(
        runtime_config,
        "BasicInfo.project_context_artifact_path",
        str(base_dir / "project_context.json"),
        merge=False,
    )
    return runtime_config, survey_context.topic


def _run_topic(
    topic: str,
    output_root: str,
    run_id: str,
    include_console: bool,
    rag_config: str,
    resolved_inputs: Dict[str, object],
    survey_config: Optional[object] = None,
    survey_context: Optional[SurveyIdeaContext] = None,
    idea_config: Optional[object] = None,
) -> str:
    run_dir = Path(output_root) / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "logs").mkdir(parents=True, exist_ok=True)
    (run_dir / "run_metadata.json").write_text(
        json.dumps(
            {
                "research_run_id": run_id,
                "topic": topic,
                "started_at": datetime.now().isoformat(timespec="microseconds"),
                "survey": (
                    {
                        "manifest_path": str(survey_context.manifest_path),
                        "survey_run_id": survey_context.survey_run_id,
                        "project_id": survey_context.project_id,
                        "project_context_fingerprint": survey_context.project_context_fingerprint,
                        "legacy": survey_context.legacy,
                    }
                    if survey_context is not None
                    else None
                ),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    os.environ["IDEA_AGENT_TASK_TOPIC"] = topic
    print(f"[{topic}] 🏃 Starting run in {run_dir}...")

    init_logger(
        log_dir=str(run_dir / "logs"),
        filename="ligagent.log",
        include_console=include_console,
        include_timestamp=False,
        force_reinit=True,
    )
    logger = get_logger()
    logger.info("========================================")
    logger.info("💡 The research topic is %s", topic)

    config = idea_config if idea_config is not None else load_idea_agent_config()
    agent = LigAgent(
        run_dir=run_dir,
        rag_config=rag_config,
        config=config,
        survey_config=survey_config,
    )
    if survey_context is not None:
        artifact_set(agent.artifact, "survey_idea_context", survey_context.to_payload())
    agent.bootstrap_topic(topic)
    previous_candidate = _load_previous_idea_candidate()
    if previous_candidate is not None:
        artifact_set(agent.artifact, "latest_candidate", previous_candidate)

    mature_ideas = normalize_mature_ideas(
        resolved_inputs.get("mature_ideas"),
        legacy_value=resolved_inputs.get("mature_idea"),
        default_source=str(resolved_inputs.get("mature_idea_source") or "user_input"),
    )
    if mature_ideas:
        artifact_set(agent.artifact, "mature_ideas", mature_ideas)
    legacy_mature_idea = clean_optional_text(str(resolved_inputs.get("mature_idea") or "")) or mature_idea_legacy_text(mature_ideas)
    if legacy_mature_idea:
        artifact_set(agent.artifact, "mature_idea", legacy_mature_idea)
    artifact_set(agent.artifact, "mature_idea_source", str(resolved_inputs.get("mature_idea_source") or ""))
    if clean_optional_text(str(resolved_inputs.get("refinement_scope") or "")):
        artifact_set(
            agent.artifact,
            "refinement_scope",
            clean_optional_text(str(resolved_inputs["refinement_scope"])),
        )
    artifact_set(
        agent.artifact,
        "refinement_scope_source",
        str(resolved_inputs.get("refinement_scope_source") or ""),
    )
    ingest_ablation_results_if_available(agent, resolved_inputs, logger)

    try:
        run_agent_loop(agent, logger)
    except (Exception, KeyboardInterrupt):
        logger.info("Artifact snapshot at failure: %s", getattr(agent, "artifact", {}))
        tb = traceback.format_exc()
        logger.error("Traceback:\n%s", tb)
        raise RuntimeError(f"Worker failed for topic '{topic}': {tb}") from None

    logger.info("✅ Finished topic '%s'. Results in %s", topic, run_dir)
    return str(run_dir)


def run_idea_workflow(
    *,
    config_path: str | None = None,
    topic: str | None = None,
    output_root: str | None = None,
    run_id: str | None = None,
    survey_manifest: str | None = None,
    include_console: bool | None = None,
) -> str:
    """Run one Idea workflow and return its exact result directory."""

    config = load_idea_agent_config(config_path)
    project_config = load_project_config(config_path)
    _apply_env_config(config)
    requested_manifest = clean_optional_text(
        survey_manifest
        or os.getenv("IDEA_AGENT_SURVEY_MANIFEST")
        or str(get_config_value(config, "run.survey_manifest", "") or "")
    )
    survey_context: Optional[SurveyIdeaContext] = None
    if requested_manifest:
        survey_context = load_survey_idea_context(requested_manifest)
    resolved_inputs = resolve_run_inputs(
        config,
        default_output_root=str(DEFAULT_OUTPUT_ROOT),
        topic_override=topic,
        survey_manifest_override=requested_manifest,
    )
    requested_topic = clean_optional_text(topic or str(resolved_inputs.get("topic") or ""))
    if survey_context is not None:
        if requested_topic and requested_topic.casefold() != survey_context.topic.casefold():
            raise SurveyIdeaLoadError(
                "Explicit Idea topic does not match the selected Survey manifest: "
                f"{requested_topic!r} != {survey_context.topic!r}"
            )
        requested_topic = survey_context.topic
        resolved_inputs["topic_source"] = "survey_manifest"
    resolved_inputs["topic"] = requested_topic
    if output_root is not None:
        resolved_inputs["output_root"] = str(output_root)
    if survey_context is not None:
        resolved_inputs["survey_manifest"] = str(survey_context.manifest_path)
    resolved_topic = load_topic(str(resolved_inputs["topic"]))
    survey_config, _survey_topic = _resolve_runtime_survey_config(
        get_config_value(project_config, "survey", None),
        survey_context,
    )
    resolved_output_root = Path(str(resolved_inputs["output_root"])).expanduser()
    if not resolved_output_root.is_absolute():
        resolved_output_root = IDEA_AGENT_ROOT / resolved_output_root
    resolved_output_root.mkdir(parents=True, exist_ok=True)
    return _run_topic(
        resolved_topic,
        str(resolved_output_root),
        run_id or create_research_run_id(),
        bool(resolved_inputs["console_logs"]) if include_console is None else include_console,
        str(resolved_inputs["rag_config"]),
        resolved_inputs,
        survey_config,
        survey_context,
        config,
    )


def _apply_env_config(config: Optional[object]) -> None:
    if config is None:
        return
    env_map = {
        "OPENAI_API_KEY": "run.openai_api_key",
        "OPENAI_BASE_URL": "run.openai_base_url",
        "S2_API_KEY": "run.s2_api_key",
        "S2_API_TIMEOUT": "run.s2_api_timeout",
    }
    for env_var, key in env_map.items():
        if env_var not in os.environ:
            value = get_config_value(config, key, None)
            if value is not None:
                os.environ[env_var] = str(value)

def main() -> int:
    try:
        result_dir = run_idea_workflow()
        print(f"✅ completed -> {result_dir}")
        return 0
    except SurveyIdeaLoadError as exc:
        print(f"Survey manifest error: {exc}")
        return 2
    except Exception as exc:
        print(f"❌ failed: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
