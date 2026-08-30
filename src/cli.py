from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Iterable, Sequence

from dotenv import load_dotenv
from omegaconf import OmegaConf

from src.agents.survey_agent.utils.topic_survey_storage import (
    apply_topic_survey_paths,
    get_survey_output_root,
)
from src.pipeline.survey_idea_loader import SurveyIdeaLoadError, load_survey_idea_context
from src.pipeline.science_run import (
    SCIENCE_RESULT_SCHEMA_VERSION,
    SCIENCE_STAGE_NAMES,
    SURVEY_APPENDIX_MODES,
    ScienceRunConflictError,
    ScienceRunError,
    ScienceRunInputError,
    ScienceRunLockError,
    ScienceRunPaths,
    ScienceRunStateError,
    atomic_write_json,
    append_science_event,
    initialize_science_run,
    invalidate_stages_from,
    load_science_run,
    locked_science_run,
    save_science_state,
    science_run_paths,
    validate_resume_inputs,
)
from src.pipeline.science_workflow import ScienceWorkflowError, run_science_workflow
from src.llm.provider_registry import (
    provider_required_settings,
    require_model_capabilities,
    resolve_provider,
    resolve_role_model,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = REPO_ROOT / "src" / "config" / "default.yaml"
DEFAULT_ENV_PATH = REPO_ROOT / ".env"
LEGACY_ENV_PATH = REPO_ROOT / "src" / "config" / ".env"
DEFAULT_SCIENCE_OUTPUT_ROOT = REPO_ROOT / "workspace" / "science-runs"
LEGACY_COMMAND_DEPRECATION = (
    "DeprecationWarning: `{legacy}` will be removed in a future release.\n"
    "Use `{replacement}` instead."
)


EXP_DESIGN_EXIT_SUCCESS = 0
EXP_DESIGN_EXIT_INPUT_ERROR = 2
EXP_DESIGN_EXIT_CONFIG_ERROR = 3
EXP_DESIGN_EXIT_IDEA_ERROR = 4
EXP_DESIGN_EXIT_SCOPE_ERROR = 5
EXP_DESIGN_EXIT_LLM_ERROR = 6
EXP_DESIGN_EXIT_VALIDATION_ERROR = 7
EXP_DESIGN_EXIT_OUTPUT_ERROR = 8
EXP_DESIGN_EXIT_RUNTIME_ERROR = 10

AUTHOR_EXIT_SUCCESS = 0
AUTHOR_EXIT_INPUT_ERROR = 20
AUTHOR_EXIT_SURVEY_ERROR = 21
AUTHOR_EXIT_IDEA_EVOLUTION_ERROR = 22
AUTHOR_EXIT_CONFIG_ERROR = 23
AUTHOR_EXIT_RENDER_ERROR = 27
AUTHOR_EXIT_OUTPUT_ERROR = 28
AUTHOR_EXIT_RUNTIME_ERROR = 29

SCIENCE_EXIT_SUCCESS = 0
SCIENCE_EXIT_INPUT_ERROR = 2
SCIENCE_EXIT_RUNTIME_ERROR = 10

_WSL_MOUNTED_PATH = re.compile(r"^/mnt/([A-Za-z])(?:/(.*))?$")
_WINDOWS_DRIVE_PATH = re.compile(r"^([A-Za-z]):[\\/](.*)$")


def _load_project_env() -> Path | None:
    loaded: Path | None = None
    for candidate in (DEFAULT_ENV_PATH, LEGACY_ENV_PATH):
        if candidate.exists():
            load_dotenv(candidate, override=False)
            if loaded is None:
                loaded = candidate
    return loaded


def _base_env(*, config_path: Path | None = None) -> dict[str, str]:
    _load_project_env()
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO_ROOT) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    if config_path is not None:
        resolved_config = str(config_path.resolve())
        env["QWENSCI_CONFIG"] = resolved_config
        env["QWENSCI_CONFIG_PATH"] = resolved_config
    return env


def _run_command(cmd: Sequence[str], *, env: dict[str, str] | None = None) -> int:
    process = subprocess.run(
        list(cmd),
        cwd=str(REPO_ROOT),
        env=env,
        check=False,
    )
    return int(process.returncode)


def _resolve_config_path(config: str | None) -> Path:
    return _resolve_cli_path(config) if config else DEFAULT_CONFIG_PATH


def _resolve_cli_path(value: str | Path) -> Path:
    """Resolve Windows, WSL-mounted, and native relative paths.

    The command is commonly launched from WSL while the project and Idea
    artifacts live on a Windows drive.  Python's ``Path`` does not translate
    ``/mnt/c/...`` when running on Windows, nor ``C:/...`` when running under
    WSL, so handle those two explicit forms before normal resolution.
    """

    raw_value = os.fspath(value)
    normalized = raw_value.replace("\\", "/")
    path: Path
    if os.name == "nt":
        wsl_match = _WSL_MOUNTED_PATH.fullmatch(normalized)
        if wsl_match:
            drive, remainder = wsl_match.groups()
            path = Path(f"{drive.upper()}:/{remainder or ''}")
        else:
            path = Path(raw_value).expanduser()
    else:
        windows_match = _WINDOWS_DRIVE_PATH.fullmatch(normalized)
        if windows_match:
            drive, remainder = windows_match.groups()
            path = Path(f"/mnt/{drive.lower()}/{remainder}").expanduser()
        else:
            path = Path(raw_value).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    return path.resolve()


def _resolve_idea_artifact_path(value: str | Path) -> Path:
    path = _resolve_cli_path(value)
    if path.is_dir() or path.suffix == "":
        path = path / "idea_result.json"
    return path.resolve()


def _ensure_config_exists(config_path: Path) -> None:
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")


def _survey_override_key(config_path: Path, key: str) -> str:
    config = OmegaConf.to_container(OmegaConf.load(config_path), resolve=False)
    prefix = "survey." if isinstance(config, dict) and "survey" in config else ""
    return f"{prefix}{key}"


def _temporary_config(base_config: Path, updates: Iterable[tuple[str, object]]) -> str | None:
    update_pairs = [(key, value) for key, value in updates if value is not None and value != ""]
    if not update_pairs:
        return None
    config = OmegaConf.load(base_config)
    for key, value in update_pairs:
        OmegaConf.update(config, key, value, merge=False)
    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False, encoding="utf-8") as handle:
        OmegaConf.save(config, handle.name)
        return handle.name


def _build_root_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Qwen-Sci uv-friendly CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    survey = subparsers.add_parser("survey", help="Run Survey Agent")
    survey.add_argument("--config", default=str(DEFAULT_CONFIG_PATH), help="Path to config YAML")
    survey.add_argument("--topic", help="Override survey BasicInfo.topic")
    survey.add_argument(
        "--declared-domain",
        help="User-declared scientific domain for project-level domain confirmation",
    )
    survey.add_argument(
        "--research-title",
        help="Research title used when resolving the project domain",
    )
    survey.add_argument(
        "--research-objective",
        help="Scientific objective used when resolving the project domain",
    )
    survey.add_argument(
        "--research-brief",
        help="Additional scientific brief used when resolving the project domain",
    )
    survey.add_argument("--base-dir", help="Override survey BasicInfo.base_dir")
    survey.add_argument("--save-path", help="Override survey BasicInfo.save_path")
    survey.add_argument("--save-json-path", help="Override survey BasicInfo.save_json_path")
    survey.add_argument(
        "--evaluation-save-path",
        help="Override survey.BasicInfo.evaluation_save_path",
    )
    survey.add_argument("overrides", nargs="*", help="Additional Hydra overrides")
    survey.set_defaults(func=_survey_command)

    idea = subparsers.add_parser("idea", help="Run Idea Agent")
    idea.add_argument("--config", default=str(DEFAULT_CONFIG_PATH), help="Path to config YAML")
    idea.add_argument("--topic", help="Override idea.run.topic")
    idea.add_argument("--input", help="Override idea.run.input")
    idea.add_argument("--mature-idea", help="Override idea.run.mature_idea")
    idea.add_argument(
        "--mature-ideas",
        help="Override idea.run.mature_ideas with a JSON array or JSON object",
    )
    idea.add_argument("--refinement-scope", help="Override idea.run.refinement_scope")
    idea.add_argument("--output-root", help="Override idea.run.output_root")
    idea.add_argument(
        "--survey-manifest",
        help="Explicit completed Survey manifest, run directory, or survey.md to use as Idea context",
    )
    idea.add_argument(
        "--ablation-results-path",
        help="Set IDEA_AGENT_ABLATION_RESULTS_PATH",
    )
    idea.add_argument(
        "--previous-candidate-path",
        help="Set IDEA_AGENT_PREVIOUS_CANDIDATE_PATH",
    )
    idea.set_defaults(func=_idea_command)

    experiment = subparsers.add_parser("experiment", help="Run Experiment Agent")
    experiment.add_argument("--config", default=str(DEFAULT_CONFIG_PATH), help="Path to config YAML")
    experiment.add_argument("--experiment", required=True, help="Experiment ID")
    experiment.add_argument("--idea-json", required=True, help="Path to idea_result.json")
    experiment.add_argument("--prepare-only", action="store_true", help="Only run prepare phase")
    experiment.add_argument("--resume", action="store_true", help="Resume experiment execution")
    experiment.add_argument("--force", action="store_true", help="Force rerun prepare phase")
    experiment.add_argument("--skip-repos", action="store_true", help="Skip repo cloning in prepare")
    experiment.add_argument("--skip-datasets", action="store_true", help="Skip dataset downloads in prepare")
    experiment.add_argument("--clone-depth", type=int, default=1, help="git clone depth")
    experiment.add_argument(
        "--max-iterations",
        type=int,
        help="Deprecated compatibility option; OpenHarness uses fixed reviewed phase gates",
    )
    experiment.set_defaults(func=_experiment_command)

    exp_design = subparsers.add_parser(
        "exp_design",
        help="Run the design-only ExperimentDesign Agent; never execute experiments",
        description=(
            "Run the complete design-only ExperimentDesign workflow from one Idea Agent result. "
            "It retrieves design evidence, composes and validates the design, then writes JSON, Markdown, "
            "Author JSON, and a JSONL run log without running code, simulations, or experiments."
        ),
    )
    exp_design.add_argument("--config", default=str(DEFAULT_CONFIG_PATH), help="Path to config YAML")
    exp_design.add_argument(
        "--idea-json",
        required=True,
        help="Path to idea_result.json or an Idea Agent run directory",
    )
    exp_design.add_argument(
        "--discipline-id",
        action="append",
        metavar="ID",
        help=(
            "Scientific discipline ID, label, or OpenAlex field URL; repeat for multiple fields. "
            "May be omitted when idea_result.json contains discipline_ids."
        ),
    )
    exp_design.add_argument(
        "--selected-direction",
        default="",
        help="Direction ID, direction_mode, or title; defaults to idea_result.primary_direction",
    )
    exp_design.add_argument(
        "--brief-id",
        help="Stable ResearchBrief ID; defaults to the Idea Agent run directory name",
    )
    exp_design.add_argument(
        "--model",
        help="Override the configured ExperimentDesign LLM model",
    )
    exp_design.add_argument(
        "--output-dir",
        help="Directory for ExperimentDesign JSON, Markdown, and Author JSON; defaults to the Idea run directory",
    )
    exp_design.add_argument(
        "--log-file",
        help="Path for the JSONL run log; defaults to experiment_design_<timestamp>.jsonl in the output directory",
    )
    exp_design.set_defaults(func=_exp_design_command)

    author = subparsers.add_parser(
        "author",
        help="Compose an English-only Research Plan JSON from verified design evidence",
        description=(
            "Compose an English-only, proposal-only Research Plan JSON from a verified ExperimentDesign handoff, "
            "a completed Survey manifest, and optional source-anchored Idea checkpoints. When a declared template "
            "is available, render a copied TeX project, provenance-bounded BibTeX, and a validated PDF."
        ),
    )
    author.add_argument("--config", default=str(DEFAULT_CONFIG_PATH), help="Path to config YAML")
    author.add_argument(
        "--author-input",
        required=True,
        help="Path to experiment_design_author_<timestamp>.json",
    )
    author.add_argument(
        "--survey-manifest",
        required=True,
        help="Path to a completed, verified survey_manifest.json or its run directory",
    )
    author.add_argument(
        "--idea-result",
        help="Optional explicit idea_result.json for a source-anchored appendix; otherwise use Author provenance",
    )
    author.add_argument(
        "--include-idea-evolution",
        choices=("auto", "on", "off"),
        default=None,
        help="Include only real Idea checkpoints; auto exposes unavailable provenance without inventing history",
    )
    author.add_argument(
        "--max-idea-iterations",
        type=int,
        choices=(2, 3),
        default=None,
        help="Maximum source-anchored Idea iterations to retain in the future appendix",
    )
    author.add_argument(
        "--strict-survey-binding",
        action="store_true",
        help="Fail when ExperimentDesign does not contain a complete Survey identity binding",
    )
    author.add_argument(
        "--collect-section-contract-errors",
        action="store_true",
        help="Deprecated compatibility option; Author now always completes the section batch before reporting failures",
    )
    author.add_argument(
        "--composer-concurrency",
        type=int,
        help="Maximum concurrent Author section-composition requests; defaults to research_plan_author.authoring.composer_concurrency",
    )
    author.add_argument(
        "--section-cache-mode",
        choices=("disabled", "read_write", "read_only", "refresh"),
        help="Override the Author section-cache mode for this run; refresh bypasses reads and rewrites generated sections",
    )
    author.add_argument(
        "--model",
        help="Override the configured Research Plan Author LLM model",
    )
    author.add_argument(
        "--document-quality",
        choices=("on", "off"),
        help="Enable or disable whole-document Author scoring and bounded revision",
    )
    author.add_argument(
        "--document-quality-model",
        help="Override the Author whole-document quality model",
    )
    author.add_argument(
        "--document-quality-max-iterations",
        type=int,
        help="Override the maximum whole-document quality revision iterations",
    )
    author.add_argument(
        "--output-dir",
        help="Directory for Author preparation artifacts; defaults beside the Author input",
    )
    author.add_argument(
        "--log-file",
        help="Path for the JSONL Author log; defaults to author_<timestamp>.jsonl in the output directory",
    )
    author.add_argument(
        "--template-dir",
        help="Read-only LaTeX template directory; overrides research_plan_author.rendering.template_dir",
    )
    author.add_argument(
        "--template-profile",
        help="Built-in template profile ID or explicit JSON profile path",
    )
    author.add_argument(
        "--template-main",
        help="Relative main .tex path inside the copied template; overrides the profile main_tex",
    )
    author.add_argument(
        "--latex-engine",
        help="Explicit pdflatex-compatible executable; otherwise SCIENCE_LATEX_ENGINE, config, then PATH",
    )
    author.add_argument(
        "--bibtex",
        help="Explicit BibTeX executable; otherwise SCIENCE_BIBTEX, config, then PATH",
    )
    author.add_argument(
        "--pdf-renderer",
        help="Explicit pdftoppm-compatible executable; otherwise SCIENCE_PDF_RENDERER, config, then PATH",
    )
    author.add_argument(
        "--compile-timeout-seconds",
        type=int,
        help="Per LaTeX/BibTeX command timeout; overrides rendering configuration",
    )
    author.add_argument(
        "--author-name",
        default="Anonymous Research Plan Author",
        help="Plain-text author name to render; defaults to an anonymous proposal author",
    )
    author.set_defaults(func=_author_command)

    science = subparsers.add_parser(
        "science",
        help="Initialize or resume the Survey -> Idea -> ExperimentDesign -> Author workflow",
        description=(
            "Create or resume an auditable, design-only science run. "
            "This command never executes experiments."
        ),
    )
    science.add_argument(
        "--topic",
        help="Research topic; required for a new run and immutable after initialization",
    )
    science.add_argument(
        "--config",
        help="Config YAML for a new run or an explicit config consistency check while resuming",
    )
    science.add_argument(
        "--output-root",
        help="Parent directory for new science runs; defaults to workspace/science-runs",
    )
    science.add_argument(
        "--run-id",
        help="Optional filesystem-safe ID for a new science run",
    )
    science.add_argument(
        "--resume",
        help="Existing science run directory to resume",
    )
    science.add_argument(
        "--restart-from",
        choices=SCIENCE_STAGE_NAMES,
        help="Invalidate this stage and downstream stages; requires --resume --force",
    )
    science.add_argument(
        "--force",
        action="store_true",
        help="Confirm --restart-from; no historical artifacts are removed",
    )
    science.add_argument(
        "--discipline-id",
        action="append",
        metavar="ID",
        help="Discipline ID, label, or OpenAlex field URL; repeat for multiple fields",
    )
    science.add_argument(
        "--selected-direction",
        help="Idea direction selected for ExperimentDesign and Author",
    )
    science.add_argument(
        "--exp-design-model",
        help="Override the configured ExperimentDesign model",
    )
    science.add_argument(
        "--author-model",
        help="Override the configured Research Plan Author model",
    )
    science.add_argument("--template-dir", help="Read-only LaTeX template directory for Author")
    science.add_argument("--template-profile", help="Author rendering template profile")
    science.add_argument("--template-main", help="Author rendering template main TeX path")
    science.add_argument("--latex-engine", help="Author rendering LaTeX engine")
    science.add_argument("--bibtex", help="Author rendering BibTeX executable")
    science.add_argument("--pdf-renderer", help="Author rendering PDF renderer")
    science.add_argument(
        "--compile-timeout-seconds",
        type=int,
        help="Per Author rendering command timeout",
    )
    science.add_argument("--author-name", help="Plain-text Author name for rendered research plans")
    science.add_argument(
        "--render-required",
        action="store_true",
        default=None,
        help="Require Author rendering; fail if no template is configured or rendering fails",
    )
    science.add_argument(
        "--survey-appendix",
        choices=SURVEY_APPENDIX_MODES,
        help="Keep a source link or append the verified full Survey text in Author output",
    )
    science.add_argument(
        "--until",
        choices=SCIENCE_STAGE_NAMES,
        default="author",
        help="Stop after this stage once stage execution is enabled; defaults to author",
    )
    science.add_argument(
        "--json",
        action="store_true",
        help="Print only the stable science_run_result_v1 JSON result",
    )
    science.set_defaults(func=_science_command)

    blog = subparsers.add_parser("blog", help="Run Blog Agent")
    blog.add_argument("--config", default=str(DEFAULT_CONFIG_PATH), help="Path to config YAML")
    blog.add_argument("--experiment", required=True, help="Experiment/project name")
    blog.add_argument("--resume", action="store_true", help="Resume from the last completed step")
    blog.add_argument(
        "--source-workspace",
        help="Set BLOG_AGENT_SOURCE_WORKSPACE for an experiment workspace outside the default source path",
    )
    blog.set_defaults(func=_blog_command)

    pipeline = subparsers.add_parser("pipeline", help="Run Survey -> Idea -> Experiment loop")
    pipeline.add_argument("--config", default=str(DEFAULT_CONFIG_PATH), help="Path to config YAML")
    pipeline.add_argument("--topic", help="Override pipeline research topic")
    pipeline.set_defaults(func=_pipeline_command)

    doctor = subparsers.add_parser("doctor", help="Check local runtime prerequisites")
    doctor.add_argument("--config", default=str(DEFAULT_CONFIG_PATH), help="Path to config YAML")
    doctor.set_defaults(func=_doctor_command)

    install = subparsers.add_parser("install-mcp-wrappers", help="Install local MCP wrapper scripts")
    install.set_defaults(func=_install_mcp_wrappers_command)

    return parser


def _survey_command(args: argparse.Namespace) -> int:
    config_path = _resolve_config_path(args.config)
    _ensure_config_exists(config_path)
    override_key = lambda key: _survey_override_key(config_path, key)
    config = OmegaConf.load(config_path)
    derived_paths = None
    if args.topic and not any(
        (
            args.base_dir,
            args.save_path,
            args.save_json_path,
            args.evaluation_save_path,
        )
    ):
        survey_config = (
            config.get("survey")
            if hasattr(config, "get") and config.get("survey") is not None
            else config
        )
        derived_paths = apply_topic_survey_paths(
            OmegaConf.create(OmegaConf.to_container(survey_config, resolve=False)),
            args.topic,
            output_root=get_survey_output_root(survey_config),
        )
    runtime_config = _temporary_config(
        config_path,
        [
            (override_key("BasicInfo.topic"), args.topic),
            (override_key("BasicInfo.declared_domain"), args.declared_domain),
            (override_key("BasicInfo.research_title"), args.research_title),
            (override_key("BasicInfo.research_objective"), args.research_objective),
            (override_key("BasicInfo.research_brief"), args.research_brief),
            (
                override_key("BasicInfo.survey_run_id"),
                derived_paths.research_run_id if derived_paths else "",
            ),
            (
                override_key("BasicInfo.base_dir"),
                args.base_dir or (str(derived_paths.base_dir) if derived_paths else ""),
            ),
            (
                override_key("BasicInfo.save_path"),
                args.save_path or (str(derived_paths.markdown_path) if derived_paths else ""),
            ),
            (
                override_key("BasicInfo.save_json_path"),
                args.save_json_path or (str(derived_paths.json_path) if derived_paths else ""),
            ),
            (
                override_key("BasicInfo.evaluation_save_path"),
                args.evaluation_save_path
                or (str(derived_paths.evaluation_path) if derived_paths else ""),
            ),
        ],
    )
    effective_config_path = Path(runtime_config) if runtime_config else config_path
    env = _base_env(config_path=effective_config_path)
    for key in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY"):
        env.pop(key, None)
    env["no_proxy"] = "58.210.177.113,localhost,127.0.0.1"
    env.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
    env.setdefault("MINERU_MODEL_SOURCE", "modelscope")

    cmd = [
        sys.executable,
        str(REPO_ROOT / "src" / "agents" / "survey_agent" / "scripts" / "run_deep_survey.py"),
        "--config-path",
        str(effective_config_path.parent),
        "--config-name",
        effective_config_path.stem,
        *args.overrides,
    ]
    try:
        return _run_command(cmd, env=env)
    finally:
        if runtime_config:
            Path(runtime_config).unlink(missing_ok=True)


def _idea_command(args: argparse.Namespace) -> int:
    config_path = _resolve_config_path(args.config)
    _ensure_config_exists(config_path)
    if args.survey_manifest:
        try:
            load_survey_idea_context(args.survey_manifest)
        except SurveyIdeaLoadError as exc:
            print(f"Survey manifest error: {exc}", file=sys.stderr)
            return 2
    runtime_config = _temporary_config(
        config_path,
        [
            ("idea.run.topic", args.topic),
            ("idea.run.input", args.input),
            ("idea.run.mature_idea", args.mature_idea),
            ("idea.run.mature_ideas", args.mature_ideas),
            ("idea.run.refinement_scope", args.refinement_scope),
            ("idea.run.output_root", args.output_root),
            ("idea.run.survey_manifest", args.survey_manifest),
        ],
    )
    env = _base_env(config_path=config_path)
    env["IDEA_AGENT_CONFIG"] = runtime_config or str(config_path)
    if args.survey_manifest:
        env["IDEA_AGENT_SURVEY_MANIFEST"] = str(
            Path(args.survey_manifest).expanduser().resolve()
        )
    if args.ablation_results_path:
        env["IDEA_AGENT_ABLATION_RESULTS_PATH"] = str(Path(args.ablation_results_path).expanduser().resolve())
    if args.previous_candidate_path:
        env["IDEA_AGENT_PREVIOUS_CANDIDATE_PATH"] = str(
            Path(args.previous_candidate_path).expanduser().resolve()
        )
    try:
        return _run_command(
            [sys.executable, str(REPO_ROOT / "src" / "agents" / "idea_agent" / "run.py")],
            env=env,
        )
    finally:
        if runtime_config:
            Path(runtime_config).unlink(missing_ok=True)


def _experiment_command(args: argparse.Namespace) -> int:
    config_path = _resolve_config_path(args.config)
    _ensure_config_exists(config_path)
    idea_json_path = Path(args.idea_json).expanduser().resolve()
    if not idea_json_path.exists():
        raise FileNotFoundError(f"Idea JSON not found: {idea_json_path}")

    from src.config import load_config

    config = load_config(str(config_path))
    workspace_root = Path(str(config.experiment.workspace.root)).expanduser()
    if not workspace_root.is_absolute():
        workspace_root = (REPO_ROOT / workspace_root).absolute()
    experiment_dir = workspace_root / args.experiment
    experiment_dir.mkdir(parents=True, exist_ok=True)

    target_idea_json = experiment_dir / "idea.json"
    target_idea_result_json = experiment_dir / "idea_result.json"
    if idea_json_path != target_idea_json.resolve():
        shutil.copy2(idea_json_path, target_idea_json)
    shutil.copy2(idea_json_path, target_idea_result_json)

    env = _base_env(config_path=config_path)
    env.setdefault("SHOW_LLM_REASONING", "1")
    env.setdefault("AGENT_BASH_TIMEOUT_SECONDS", "600000")
    env["EXPERIMENT_AGENT_WORKSPACE_DIR"] = str(experiment_dir)

    cmd = [
        sys.executable,
        "-m",
        "src.agents.experiment_agent.main",
        "--experiment",
        args.experiment,
        "--config",
        str(config_path),
        "--verbose",
        "--clone-depth",
        str(args.clone_depth),
    ]
    if args.prepare_only:
        cmd.append("--prepare-only")
    if args.resume:
        cmd.append("--resume")
    if args.force:
        cmd.append("--force")
    if args.skip_repos:
        cmd.append("--skip-repos")
    if args.skip_datasets:
        cmd.append("--skip-datasets")
    if args.max_iterations is not None:
        print(
            "Warning: --max-iterations is deprecated; the OpenHarness experiment "
            "control plane runs prepare, code, science, and finalization gates once."
        )
    return _run_command(cmd, env=env)


def _exp_design_allow_digital_execution(config: object) -> bool:
    """Read the opt-in flag without ever enabling it by default."""

    try:
        value = config.experiment_design.execution.allow_digital_execution  # type: ignore[attr-defined]
    except (AttributeError, KeyError, TypeError):
        return False
    if isinstance(value, str):
        return value.strip().casefold() not in {"", "0", "false", "no", "off", "none"}
    return bool(value)


def _exp_design_failure_code(exc: Exception) -> int:
    """Map design-only failures to stable CLI exit codes."""

    from src.agents.experiment_design_agent.llm_json import RequiredJsonLLMError
    from src.agents.experiment_design_agent.run import ExperimentDesignRunError

    if isinstance(exc, ExperimentDesignRunError):
        return exc.exit_code
    if isinstance(exc, RequiredJsonLLMError):
        return EXP_DESIGN_EXIT_LLM_ERROR
    message = str(exc).casefold()
    if "failed validation" in message or "validation" in message:
        return EXP_DESIGN_EXIT_VALIDATION_ERROR
    if "scope" in message or "discipline" in message:
        return EXP_DESIGN_EXIT_SCOPE_ERROR
    if isinstance(exc, ValueError):
        return EXP_DESIGN_EXIT_IDEA_ERROR
    return EXP_DESIGN_EXIT_RUNTIME_ERROR


def _exp_design_output_dir(args: argparse.Namespace, idea_path: Path) -> Path:
    return _resolve_cli_path(args.output_dir) if args.output_dir else idea_path.parent


def _author_output_dir(args: argparse.Namespace, author_input_path: Path, author_config: object) -> Path:
    if args.output_dir:
        return _resolve_cli_path(args.output_dir)
    configured_root = ""
    if hasattr(author_config, "get"):
        configured_root = str(author_config.get("output_root") or "").strip()
    return _resolve_cli_path(configured_root) if configured_root else author_input_path.parent / "research_plan_author"


def _author_failure_code(exc: Exception) -> int:
    from src.agents.research_plan_author.render import AuthorRenderingError
    from src.agents.research_plan_author.run import AuthorRunError

    if isinstance(exc, AuthorRenderingError):
        return AUTHOR_EXIT_RENDER_ERROR
    if isinstance(exc, AuthorRunError):
        return {
            "input": AUTHOR_EXIT_INPUT_ERROR,
            "survey": AUTHOR_EXIT_SURVEY_ERROR,
            "idea_evolution": AUTHOR_EXIT_IDEA_EVOLUTION_ERROR,
        }.get(exc.stage, AUTHOR_EXIT_RUNTIME_ERROR)
    return AUTHOR_EXIT_RUNTIME_ERROR


def _author_command(args: argparse.Namespace) -> int:
    """Compose an English proposal, then render only through a declared safe template."""

    try:
        config_path = _resolve_config_path(args.config)
        _ensure_config_exists(config_path)
        from src.config import load_config

        config = load_config(str(config_path))
        author_config = config.get("research_plan_author", {})
        if not bool(author_config.get("enabled", True)):
            raise ValueError("research_plan_author.enabled is false")
    except Exception as exc:
        print(f"author failed at config: {exc}", file=sys.stderr)
        return AUTHOR_EXIT_CONFIG_ERROR
    try:
        author_input_path = _resolve_cli_path(args.author_input)
        survey_manifest_path = _resolve_cli_path(args.survey_manifest)
        idea_result_path = _resolve_cli_path(args.idea_result) if args.idea_result else None
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"author failed at input: cannot resolve path: {exc}", file=sys.stderr)
        return AUTHOR_EXIT_INPUT_ERROR
    try:
        from src.agents.experiment_design_agent.artifacts import generate_timestamp
        from src.agents.research_plan_author.artifacts import (
            AuthorArtifactError,
            write_author_contract_failure_audit,
            write_author_preparation_artifacts,
        )
        from src.agents.research_plan_author.llm_json import build_author_json_llm_call
        from src.agents.research_plan_author.render import AuthorRenderingError, render_research_plan_document
        from src.agents.research_plan_author.run import run_research_plan_author
        from src.agents.research_plan_author.run_logging import AuthorRunLogger, AuthorRunLoggingError

        output_dir = _author_output_dir(args, author_input_path, author_config)
        output_dir.mkdir(parents=True, exist_ok=True)
        timestamp = generate_timestamp()
        log_path = _resolve_cli_path(args.log_file) if args.log_file else output_dir / f"author_{timestamp}.jsonl"
        logger = AuthorRunLogger(f"author-{timestamp}", jsonl_path=log_path)
    except (OSError, ValueError, AuthorRunLoggingError) as exc:
        print(f"author failed at output: cannot initialize output or log sink: {exc}", file=sys.stderr)
        return AUTHOR_EXIT_OUTPUT_ERROR
    try:
        authoring_config = author_config.get("authoring", {}) if hasattr(author_config, "get") else {}
        configured_section_repairs = (
            authoring_config.get(
                "max_contract_repairs_per_section",
                authoring_config.get("max_contract_repairs", 1),
            )
            if hasattr(authoring_config, "get")
            else 1
        )
        section_cache_config = dict(
            authoring_config.get("section_cache", {}) if hasattr(authoring_config, "get") else {}
        )
        document_quality_config = dict(
            author_config.get("document_quality", {}) if hasattr(author_config, "get") else {}
        )
        if args.document_quality is not None:
            document_quality_config["enabled"] = args.document_quality == "on"
        if args.document_quality_model:
            document_quality_config["model"] = args.document_quality_model
        if args.document_quality_max_iterations is not None:
            document_quality_config["max_iterations"] = args.document_quality_max_iterations
        if args.section_cache_mode is not None:
            section_cache_config["mode"] = args.section_cache_mode
        quality_model = str(document_quality_config.get("model") or "").strip() or None
        quality_enabled = bool(document_quality_config.get("enabled", True))
        result = run_research_plan_author(
            author_input_path,
            survey_manifest_path=survey_manifest_path,
            idea_result_path=idea_result_path,
            include_idea_evolution=args.include_idea_evolution
            or str(author_config.get("idea_evolution", {}).get("default_mode") or "auto"),
            max_idea_iterations=args.max_idea_iterations
            or int(author_config.get("idea_evolution", {}).get("max_iterations") or 3),
            strict_survey_binding=args.strict_survey_binding
            or bool(authoring_config.get("require_survey_binding", False)),
            llm_call=build_author_json_llm_call(config=config, model=args.model),
            max_contract_repairs=int(1 if configured_section_repairs is None else configured_section_repairs),
            composer_concurrency=(
                args.composer_concurrency
                if args.composer_concurrency is not None
                else int(authoring_config.get("composer_concurrency") or 5)
            ),
            section_cache_config=section_cache_config,
            document_quality_config=document_quality_config,
            quality_judge_llm_call=(
                build_author_json_llm_call(
                    config=config,
                    model=quality_model,
                    temperature=float(document_quality_config.get("judge_temperature") or 0.0),
                )
                if quality_enabled
                else None
            ),
            quality_revision_llm_call=(
                build_author_json_llm_call(
                    config=config,
                    model=quality_model,
                    temperature=float(document_quality_config.get("revision_temperature") or 0.5),
                )
                if quality_enabled
                else None
            ),
            collect_section_contract_errors=args.collect_section_contract_errors,
            logger=logger,
        )
        with logger.stage("artifacts", output_dir=str(output_dir)):
            paths = write_author_preparation_artifacts(result, output_dir, timestamp=timestamp)
    except Exception as exc:
        audit = getattr(exc, "audit", None)
        if isinstance(audit, dict):
            try:
                write_author_contract_failure_audit(audit, output_dir, timestamp=timestamp)
            except AuthorArtifactError as audit_error:
                print(f"author contract audit could not be written: {audit_error}", file=sys.stderr)
        code = AUTHOR_EXIT_OUTPUT_ERROR if isinstance(exc, AuthorArtifactError) else _author_failure_code(exc)
        stage = getattr(exc, "stage", "artifacts" if isinstance(exc, AuthorArtifactError) else "run")
        print(f"author failed at {stage}: {exc}", file=sys.stderr)
        try:
            logger.close()
        except AuthorRunLoggingError as log_error:
            print(f"author failed at output: cannot close log sink: {log_error}", file=sys.stderr)
        return code
    render_artifacts: dict[str, str | int] = {}
    rendering_config = author_config.get("rendering", {}) if hasattr(author_config, "get") else {}
    configured_template_dir = str(rendering_config.get("template_dir") or "").strip() if hasattr(rendering_config, "get") else ""
    template_dir_value = args.template_dir or configured_template_dir
    if template_dir_value:
        try:
            template_dir = _resolve_cli_path(template_dir_value)
            with logger.stage("render", template_dir=str(template_dir)):
                rendered = render_research_plan_document(
                    result["document"],
                    output_dir=output_dir,
                    timestamp=timestamp,
                    preparation_collision_index=paths.collision_index,
                    template_dir=template_dir,
                    template_profile=args.template_profile
                    or (str(rendering_config.get("template_profile") or "").strip() if hasattr(rendering_config, "get") else ""),
                    template_main=args.template_main
                    or (str(rendering_config.get("main_tex") or "").strip() if hasattr(rendering_config, "get") else ""),
                    latex_engine=args.latex_engine,
                    bibtex=args.bibtex,
                    pdf_renderer=args.pdf_renderer,
                    compile_timeout_seconds=args.compile_timeout_seconds
                    or int(rendering_config.get("compile_timeout_seconds") or 180),
                    configured_rendering=rendering_config,
                    author_name=args.author_name,
                    logger=logger,
                )
            render_artifacts = rendered.artifacts.as_dict()
        except Exception as exc:
            paths_from_error = getattr(exc, "paths", None)
            if paths_from_error is not None:
                render_artifacts = paths_from_error.as_dict()
            stage = getattr(exc, "stage", "render")
            print(f"author failed at {stage}: {exc}", file=sys.stderr)
            try:
                logger.close()
            except AuthorRunLoggingError as log_error:
                print(f"author failed at output: cannot close log sink: {log_error}", file=sys.stderr)
            return _author_failure_code(exc)
    else:
        logger.emit(
            "render",
            "not_configured",
            level="WARNING",
            status="SKIPPED",
            detail="No template directory was supplied by CLI or configuration; composition artifacts were retained.",
        )
    try:
        logger.close()
    except AuthorRunLoggingError as exc:
        print(f"author failed at output: cannot close log sink: {exc}", file=sys.stderr)
        return AUTHOR_EXIT_OUTPUT_ERROR
    manifest = {
        "schema_version": "research_plan_author_cli_result_v1",
        "status": result["status"],
        "language": "en",
        "source_design_id": result["source_design_id"],
        "selected_direction_id": result["selected_direction_id"],
        "artifacts": paths.as_dict(),
        "render_artifacts": render_artifacts,
        "log_file": str(log_path),
    }
    print(json.dumps(manifest, ensure_ascii=False, indent=2, allow_nan=False))
    return AUTHOR_EXIT_SUCCESS


def _exp_design_command(args: argparse.Namespace) -> int:
    """Run and persist the complete ExperimentDesign workflow without an executor."""

    try:
        config_path = _resolve_config_path(args.config)
        _ensure_config_exists(config_path)
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"exp_design failed at config: {exc}", file=sys.stderr)
        return EXP_DESIGN_EXIT_CONFIG_ERROR

    try:
        from src.config import load_config

        config = load_config(str(config_path))
    except Exception as exc:
        print(f"exp_design failed at config: {exc}", file=sys.stderr)
        return EXP_DESIGN_EXIT_CONFIG_ERROR

    try:
        idea_path = _resolve_idea_artifact_path(args.idea_json)
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"exp_design failed at input: cannot resolve Idea path: {exc}", file=sys.stderr)
        return EXP_DESIGN_EXIT_INPUT_ERROR
    if not idea_path.exists() or not idea_path.is_file():
        print(f"exp_design failed at input: Idea JSON not found: {idea_path}", file=sys.stderr)
        return EXP_DESIGN_EXIT_INPUT_ERROR

    try:
        from src.agents.experiment_design_agent.idea_intake import load_idea_artifact_bundle

        idea_bundle = load_idea_artifact_bundle(idea_path)
    except FileNotFoundError as exc:
        print(f"exp_design failed at input: {exc}", file=sys.stderr)
        return EXP_DESIGN_EXIT_INPUT_ERROR
    except (OSError, ValueError) as exc:
        print(f"exp_design failed at idea_intake: {exc}", file=sys.stderr)
        return EXP_DESIGN_EXIT_IDEA_ERROR

    from src.agents.experiment_design_agent.discipline_catalog import resolve_design_scope

    discipline_ids = list(args.discipline_id or [])
    if not discipline_ids:
        idea_result = idea_bundle.get("idea_result", {})
        embedded_discipline_ids = (
            idea_result.get("discipline_ids") if isinstance(idea_result, dict) else None
        )
        if isinstance(embedded_discipline_ids, (list, tuple, str)):
            discipline_ids = (
                [embedded_discipline_ids]
                if isinstance(embedded_discipline_ids, str)
                else list(embedded_discipline_ids)
            )
    if not discipline_ids:
        print(
            "exp_design failed at scope_gate: no discipline_ids were supplied "
            "by --discipline-id or idea_result.json",
            file=sys.stderr,
        )
        return EXP_DESIGN_EXIT_SCOPE_ERROR

    scope = resolve_design_scope(discipline_ids)
    if scope["status"] != "IN_SCOPE":
        print(
            "exp_design failed at scope_gate: "
            f"{scope['status']}: {scope['reason']}",
            file=sys.stderr,
        )
        return EXP_DESIGN_EXIT_SCOPE_ERROR

    try:
        from src.agents.experiment_design_agent.artifacts import (
            ArtifactError,
            generate_timestamp,
            write_experiment_design_artifacts,
        )
        from src.agents.experiment_design_agent.run import run_experiment_design
        from src.agents.experiment_design_agent.run_logging import (
            ExperimentDesignRunLogger,
            RunLoggingError,
        )

        output_dir = _exp_design_output_dir(args, idea_path)
        output_dir.mkdir(parents=True, exist_ok=True)
        timestamp = generate_timestamp()
        log_path = (
            _resolve_cli_path(args.log_file)
            if args.log_file
            else output_dir / f"experiment_design_{timestamp}.jsonl"
        )
        logger = ExperimentDesignRunLogger(
            f"exp_design-{timestamp}",
            jsonl_path=log_path,
        )
    except (OSError, ValueError, RunLoggingError) as exc:
        print(f"exp_design failed at output: cannot initialize output or log sink: {exc}", file=sys.stderr)
        return EXP_DESIGN_EXIT_OUTPUT_ERROR

    try:
        result = run_experiment_design(
            str(idea_path),
            discipline_ids=discipline_ids,
            brief_id=args.brief_id,
            selected_direction=args.selected_direction,
            config=config,
            llm_model=args.model,
            logger=logger,
        )
        with logger.stage("artifacts", output_dir=str(output_dir)):
            paths = write_experiment_design_artifacts(
                result,
                output_dir,
                timestamp=timestamp,
                idea_result_path=str(idea_path),
            )
            artifact_manifest = paths.as_dict()
            logger.event(
                "artifacts",
                "written",
                status="COMPLETED",
                artifacts=artifact_manifest,
            )
    except Exception as exc:
        code = EXP_DESIGN_EXIT_OUTPUT_ERROR if isinstance(exc, ArtifactError) else _exp_design_failure_code(exc)
        stage = getattr(exc, "stage", "artifacts" if isinstance(exc, ArtifactError) else "run")
        print(f"exp_design failed at {stage}: {exc}", file=sys.stderr)
        try:
            logger.close()
        except RunLoggingError as log_error:
            print(f"exp_design failed at output: cannot close log sink: {log_error}", file=sys.stderr)
        return code

    try:
        logger.close()
    except RunLoggingError as exc:
        print(f"exp_design failed at output: cannot close log sink: {exc}", file=sys.stderr)
        return EXP_DESIGN_EXIT_OUTPUT_ERROR

    manifest = {
        "schema_version": "experiment_design_cli_result_v1",
        "status": "COMPLETED",
        "design_id": result["experiment_design"].get("design_id", ""),
        "execution_mode": result["experiment_design"].get("execution_policy", {}).get("mode", "DESIGN_ONLY"),
        "observed_results_count": len(result["experiment_design"].get("observed_results") or []),
        "artifacts": paths.as_dict(),
        "log_file": str(log_path),
        "cache_manifest": result.get("cache_manifest_path", ""),
    }
    try:
        print(json.dumps(manifest, ensure_ascii=False, indent=2, allow_nan=False))
    except (TypeError, ValueError) as exc:
        print(f"exp_design failed at output: cannot render result manifest: {exc}", file=sys.stderr)
        return EXP_DESIGN_EXIT_OUTPUT_ERROR
    return EXP_DESIGN_EXIT_SUCCESS


def _blog_command(args: argparse.Namespace) -> int:
    config_path = _resolve_config_path(args.config)
    _ensure_config_exists(config_path)
    env = _base_env(config_path=config_path)
    agents_root = REPO_ROOT / "src" / "agents"
    env["PYTHONPATH"] = str(agents_root) + os.pathsep + env["PYTHONPATH"]
    if args.source_workspace:
        env["BLOG_AGENT_SOURCE_WORKSPACE"] = str(Path(args.source_workspace).expanduser().resolve())

    cmd = [
        sys.executable,
        "-m",
        "blog_agent.scripts.run",
        "--experiment",
        args.experiment,
    ]
    if args.resume:
        cmd.append("--resume")
    return _run_command(cmd, env=env)


def _science_path_option(value: str | None) -> str | None:
    if value is None or not str(value).strip():
        return None
    return str(_resolve_cli_path(value))


def _science_executable_option(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    if not normalized:
        return None
    if "/" in normalized.replace("\\", "/") or _WINDOWS_DRIVE_PATH.fullmatch(normalized):
        return str(_resolve_cli_path(normalized))
    return normalized


def _science_template_profile_option(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    if not normalized:
        return None
    if "/" in normalized.replace("\\", "/") or Path(normalized).suffix.casefold() == ".json":
        return str(_resolve_cli_path(normalized))
    return normalized


def _science_immutable_options(args: argparse.Namespace) -> dict[str, object]:
    return {
        "discipline_ids": args.discipline_id,
        "selected_direction": args.selected_direction,
        "exp_design_model": args.exp_design_model,
        "author_model": args.author_model,
        "template_dir": _science_path_option(args.template_dir),
        "template_profile": _science_template_profile_option(args.template_profile),
        "template_main": args.template_main,
        "latex_engine": _science_executable_option(args.latex_engine),
        "bibtex": _science_executable_option(args.bibtex),
        "pdf_renderer": _science_executable_option(args.pdf_renderer),
        "compile_timeout_seconds": args.compile_timeout_seconds,
        "author_name": args.author_name,
        "render_required": args.render_required,
        "survey_appendix": args.survey_appendix,
    }


def _science_result_payload(
    *,
    action: str,
    paths: ScienceRunPaths,
    metadata: dict[str, object],
    state: dict[str, object],
    until: str,
) -> dict[str, object]:
    immutable_inputs = metadata["immutable_inputs"]
    if not isinstance(immutable_inputs, dict):
        raise ScienceRunStateError("science_run.json has invalid immutable_inputs")
    stages = state["stages"]
    if not isinstance(stages, dict):
        raise ScienceRunStateError("science_state.json has invalid stages")
    stage_summary = {
        stage_name: {
            "status": stages[stage_name]["status"],
            "attempt": stages[stage_name]["attempt"],
        }
        for stage_name in SCIENCE_STAGE_NAMES
    }
    return {
        "schema_version": SCIENCE_RESULT_SCHEMA_VERSION,
        "action": action,
        "status": state["status"],
        "science_run_id": metadata["science_run_id"],
        "run_dir": str(paths.run_dir),
        "topic": immutable_inputs["topic"],
        "execution_mode": metadata["execution_mode"],
        "until": until,
        "state_revision": state.get("revision", 0),
        "stages": stage_summary,
    }


def _print_science_result(result: dict[str, object], *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, allow_nan=False))
        return
    print(f"Science run {result['action'].lower()}: {result['science_run_id']}")
    print(f"Run directory: {result['run_dir']}")
    print(f"Status: {result['status']} ({result['execution_mode']})")
    print(f"Executed through: {result['until']}")


def _persist_science_result(
    *,
    paths: ScienceRunPaths,
    action: str,
    until: str,
    error: dict[str, object] | None = None,
    expected_state_revision: int | None = None,
) -> dict[str, object] | None:
    try:
        with locked_science_run(paths):
            metadata, state = load_science_run(paths)
            if (
                error is not None
                and expected_state_revision is not None
                and state.get("revision", 0) != expected_state_revision
            ):
                return None
            result = _science_result_payload(
                action=action,
                paths=paths,
                metadata=metadata,
                state=state,
                until=until,
            )
            if error is not None:
                result["error"] = error
            atomic_write_json(paths.result, result)
            return result
    except (OSError, ScienceRunError):
        return None


def _science_command(args: argparse.Namespace) -> int:
    if bool(args.restart_from) != bool(args.force):
        print("science input error: --restart-from and --force must be supplied together", file=sys.stderr)
        return SCIENCE_EXIT_INPUT_ERROR

    explicit_options = _science_immutable_options(args)
    paths: ScienceRunPaths | None = None
    metadata: dict[str, object] | None = None
    action = "EXECUTED"
    try:
        if args.resume:
            if args.topic is not None:
                print("science input error: --topic cannot be changed while resuming", file=sys.stderr)
                return SCIENCE_EXIT_INPUT_ERROR
            if args.output_root is not None or args.run_id is not None:
                print(
                    "science input error: --output-root and --run-id are only valid for a new science run",
                    file=sys.stderr,
                )
                return SCIENCE_EXIT_INPUT_ERROR
            config_path = _resolve_cli_path(args.config) if args.config else None
            if config_path is not None:
                _ensure_config_exists(config_path)
            paths = science_run_paths(_resolve_cli_path(args.resume))
            with locked_science_run(paths):
                metadata, state = load_science_run(paths)
                validate_resume_inputs(
                    metadata,
                    config_path=config_path,
                    explicit_options=explicit_options,
                )
                action = "RESUMED"
                if args.restart_from:
                    invalidate_stages_from(state, args.restart_from)
                    save_science_state(paths, state)
                    append_science_event(
                        paths,
                        event_type="STAGES_INVALIDATED",
                        restart_from=args.restart_from,
                    )
                    action = "RESTART_INVALIDATED"
        else:
            if args.restart_from or args.force:
                print("science input error: --restart-from is only valid with --resume --force", file=sys.stderr)
                return SCIENCE_EXIT_INPUT_ERROR
            topic = str(args.topic or "").strip()
            if not topic:
                print("science input error: --topic is required for a new science run", file=sys.stderr)
                return SCIENCE_EXIT_INPUT_ERROR
            config_path = _resolve_config_path(args.config)
            _ensure_config_exists(config_path)
            output_root = _resolve_cli_path(args.output_root) if args.output_root else DEFAULT_SCIENCE_OUTPUT_ROOT
            paths, metadata, state = initialize_science_run(
                output_root=output_root,
                topic=topic,
                config_path=config_path,
                immutable_options=explicit_options,
                run_id=args.run_id,
            )
            action = "EXECUTED"
        with contextlib.redirect_stdout(sys.stderr if args.json else sys.stdout):
            outcome = run_science_workflow(
                paths=paths,
                metadata=metadata,
                until=args.until,
                quiet=bool(args.json),
            )
        result = _persist_science_result(
            action=action,
            paths=paths,
            until=args.until,
        )
        if result is None:
            raise ScienceRunStateError("Cannot persist science_result.json")
    except ScienceWorkflowError as exc:
        failure_result = None
        error_payload = {
            "stage": exc.stage,
            "exit_code": int(exc.exit_code),
            "message": str(exc),
        }
        if paths is not None:
            failure_result = _persist_science_result(
                paths=paths,
                action=action,
                until=args.until,
                error=error_payload,
                expected_state_revision=exc.observed_state_revision,
            )
        if failure_result is None and paths is not None and metadata is not None and exc.observed_state:
            failure_result = _science_result_payload(
                action=action,
                paths=paths,
                metadata=metadata,
                state=exc.observed_state,
                until=args.until,
            )
            failure_result["error"] = error_payload
        if args.json and failure_result is not None:
            _print_science_result(failure_result, as_json=True)
        print(f"science {exc.stage} error: {exc}", file=sys.stderr)
        return exc.exit_code
    except (FileNotFoundError, ScienceRunInputError, ScienceRunConflictError) as exc:
        print(f"science input error: {exc}", file=sys.stderr)
        return SCIENCE_EXIT_INPUT_ERROR
    except ScienceRunLockError as exc:
        print(f"science runtime error: {exc}", file=sys.stderr)
        return SCIENCE_EXIT_RUNTIME_ERROR
    except (OSError, ScienceRunError) as exc:
        print(f"science runtime error: {exc}", file=sys.stderr)
        return SCIENCE_EXIT_RUNTIME_ERROR
    _print_science_result(result, as_json=args.json)
    return SCIENCE_EXIT_SUCCESS


def _pipeline_command(args: argparse.Namespace) -> int:
    config_path = _resolve_config_path(args.config)
    _ensure_config_exists(config_path)
    env = _base_env(config_path=config_path)
    cmd = [
        sys.executable,
        "-m",
        "src.pipeline.run_loop",
        "--config",
        str(config_path),
    ]
    if args.topic:
        cmd.extend(["--topic", args.topic])
    return _run_command(cmd, env=env)


def _doctor_command(args: argparse.Namespace) -> int:
    config_path = _resolve_config_path(args.config)
    _ensure_config_exists(config_path)
    env_file = _load_project_env()

    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text

    from src.config import load_config

    config = load_config(str(config_path))
    llm_provider = resolve_provider(config)
    checks: list[tuple[str, bool, str]] = []
    checks.append(("config", True, str(config_path)))
    checks.append((".env", env_file is not None, str(env_file or DEFAULT_ENV_PATH)))
    checks.append(("llm provider", True, llm_provider.name))
    checks.append(("llm base URL", bool(llm_provider.base_url), llm_provider.base_url or "<missing>"))
    role_model_failures: list[bool] = []

    def add_role_model_check(
        role: str,
        provider_name: str,
        configured_model: object,
    ) -> None:
        try:
            model = require_model_capabilities(
                resolve_role_model(
                    config,
                    role,
                    provider_name,
                    str(configured_model or "").strip(),
                ),
                ["chat_completions"],
                f"{role} text agent",
            )
        except ValueError as exc:
            checks.append((f"{role} model", False, str(exc)))
            role_model_failures.append(True)
            return
        checks.append((f"{role} model", True, f"{model.provider}/{model.name}"))
        role_model_failures.append(False)

    survey_provider_name = str(config.survey.APIInfo.get("llm_provider", "") or llm_provider.name)
    add_role_model_check(
        "survey",
        survey_provider_name,
        config.survey.APIInfo.get("llm_model_name", ""),
    )
    judge_config = config.survey.ModuleInfo.Judge
    if bool(judge_config.get("use_different_api_for_judge", False)):
        add_role_model_check(
            "judge",
            str(judge_config.get("provider", "") or survey_provider_name),
            judge_config.get("model", ""),
        )
    blog_model = str(config.blog.get("model", "") or "").strip()
    if not blog_model.lower().startswith(("minimax", "gemini")):
        add_role_model_check(
            "blog",
            str(config.blog.get("provider", "") or llm_provider.name),
            blog_model,
        )
    checks.append(
        ("graph.db", (REPO_ROOT / "data" / "processed" / "graph.db").exists(), "data/processed/graph.db"),
    )
    vector_store_dir = REPO_ROOT / "data" / "processed" / "core_component_summary_vector_store"
    vector_store_files = [
        "build_stats.json",
        "faiss.index",
        "meta.json",
    ]
    for filename in vector_store_files:
        checks.append(
            (
                f"vector_store/{filename}",
                (vector_store_dir / filename).exists(),
                f"data/processed/core_component_summary_vector_store/{filename}",
            )
        )
    checks.append(
        ("all-MiniLM-L6-v2", (REPO_ROOT / "models" / "all-MiniLM-L6-v2").exists(), "models/all-MiniLM-L6-v2")
    )
    checks.append(
        ("bge-m3", (REPO_ROOT / "models" / "bge-m3").exists(), "models/bge-m3"),
    )
    required_settings = provider_required_settings(llm_provider)[:1] + [
        (
            "SEMANTIC_SCHOLAR_API_KEY",
            bool(os.environ.get("SEMANTIC_SCHOLAR_API_KEY")),
            "required",
        ),
    ]
    optional_env = [
        "SERPER_API_KEY",
        "GITHUB_AI_TOKEN",
        "JINA_API_KEY",
        "TAVILY_API_KEY",
        "HF_TOKEN",
    ]

    console = Console(highlight=False, soft_wrap=True)

    def status_icon(ok: bool) -> Text:
        return Text("OK", style="bold green") if ok else Text("FAIL", style="bold red")

    def optional_icon(ok: bool) -> Text:
        return Text("OK", style="bold green") if ok else Text("OPTIONAL", style="yellow")

    console.print("[bold]Qwen-Sci doctor[/bold]")
    console.print(f"[dim]repo:[/dim] {REPO_ROOT}")
    console.print(f"[dim]workspace:[/dim] {config.workspace.root}")

    check_table = Table.grid(padding=(0, 1))
    check_table.add_column(no_wrap=True)
    check_table.add_column(no_wrap=True)
    check_table.add_column(overflow="fold")
    for name, ok, detail in checks:
        check_table.add_row(status_icon(ok), name, detail)
    console.print(check_table)

    env_table = Table.grid(padding=(0, 1))
    env_table.add_column(no_wrap=True)
    env_table.add_column(no_wrap=True)
    env_table.add_column(no_wrap=True)
    for label, value, detail in required_settings:
        env_table.add_row(status_icon(value), label, Text(detail, style="dim"))
    for name in optional_env:
        value = os.environ.get(name, "")
        env_table.add_row(optional_icon(bool(value)), name, Text("optional", style="dim"))
    console.print(Panel(env_table, title="Environment variables", border_style="cyan", padding=(0, 1)))

    failures = [
        not llm_provider.api_key,
        not llm_provider.base_url,
        any(role_model_failures),
        not os.environ.get("SEMANTIC_SCHOLAR_API_KEY"),
        not (REPO_ROOT / "data" / "processed" / "graph.db").exists(),
        any(not (vector_store_dir / filename).exists() for filename in vector_store_files),
        not (REPO_ROOT / "models" / "all-MiniLM-L6-v2").exists(),
        not (REPO_ROOT / "models" / "bge-m3").exists(),
    ]
    return 1 if any(failures) else 0


def _install_mcp_wrappers_command(_: argparse.Namespace) -> int:
    env = _base_env()
    return _run_command(
        ["bash", str(REPO_ROOT / "scripts" / "install_mcp_wrappers.sh")],
        env=env,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_root_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


def survey_main() -> int:
    return main(["survey", *sys.argv[1:]])


def idea_main() -> int:
    return main(["idea", *sys.argv[1:]])


def experiment_main() -> int:
    return main(["experiment", *sys.argv[1:]])


def blog_main() -> int:
    return main(["blog", *sys.argv[1:]])


def pipeline_main() -> int:
    return main(["pipeline", *sys.argv[1:]])


def doctor_main() -> int:
    return main(["doctor", *sys.argv[1:]])


def install_mcp_wrappers_main() -> int:
    return main(["install-mcp-wrappers", *sys.argv[1:]])


def _warn_legacy_command(legacy: str, replacement: str) -> None:
    print(
        LEGACY_COMMAND_DEPRECATION.format(legacy=legacy, replacement=replacement),
        file=sys.stderr,
    )


def legacy_main() -> int:
    _warn_legacy_command("xcientist", "qwensci")
    return main()


def legacy_survey_main() -> int:
    _warn_legacy_command("xcientist-survey", "qwensci-survey")
    return survey_main()


def legacy_idea_main() -> int:
    _warn_legacy_command("xcientist-idea", "qwensci-idea")
    return idea_main()


def legacy_experiment_main() -> int:
    _warn_legacy_command("xcientist-experiment", "qwensci-experiment")
    return experiment_main()


def legacy_blog_main() -> int:
    _warn_legacy_command("xcientist-blog", "qwensci-blog")
    return blog_main()


def legacy_pipeline_main() -> int:
    _warn_legacy_command("xcientist-pipeline", "qwensci-pipeline")
    return pipeline_main()


def legacy_doctor_main() -> int:
    _warn_legacy_command("xcientist-doctor", "qwensci-doctor")
    return doctor_main()


def legacy_install_mcp_wrappers_main() -> int:
    _warn_legacy_command("xcientist-install-mcp-wrappers", "qwensci-install-mcp-wrappers")
    return install_mcp_wrappers_main()


if __name__ == "__main__":
    raise SystemExit(main())
