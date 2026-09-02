from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import subprocess
import sys
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Iterable, Sequence

from dotenv import load_dotenv
from omegaconf import OmegaConf

from src.agents.survey_agent.utils.topic_survey_storage import (
    apply_topic_survey_paths,
    get_survey_output_root,
)
from src.pipeline.multimodal_evidence import (
    MultimodalInputError,
    MultimodalSettings,
    build_input_spec_from_files,
    build_local_multimodal_input_context,
    build_multimodal_evidence,
    load_input_manifest,
    preflight_multimodal_capabilities,
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

QUANTITATIVE_EXIT_SUCCESS = 0
QUANTITATIVE_EXIT_INPUT_ERROR = 50
QUANTITATIVE_EXIT_MODEL_ERROR = 51
QUANTITATIVE_EXIT_EXECUTION_ERROR = 52

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
    multimodal_input = survey.add_mutually_exclusive_group()
    multimodal_input.add_argument(
        "--multimodal-file",
        action="append",
        metavar="PATH",
        help=(
            "Explicit local multimodal file to analyze; repeat for multiple files. "
            "Optional readers: uv sync --group multimodal"
        ),
    )
    multimodal_input.add_argument(
        "--multimodal-evidence-manifest",
        metavar="PATH",
        help=(
            "Path to a multimodal_input_manifest_v1 JSON manifest; mutually exclusive "
            "with --multimodal-file"
        ),
    )
    survey.add_argument(
        "--allow-remote-perception",
        action="store_true",
        help=(
            "Allow qwen3-vl-plus to inspect bounded, metadata-free PNG previews of "
            "explicit multimodal input"
        ),
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
        "--quantitative-handoff-manifest",
        help="Optional verified quantitative Author handoff manifest; fail closed if it is invalid",
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
        "--minimum-pages",
        type=int,
        help="Minimum report pages; defaults to 7 and normalizes the legacy value 8 to 7",
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
    science.add_argument(
        "--quantitative-mode",
        choices=("off", "optional", "required"),
        default=None,
        help="Generate an isolated Q1/Q2 mathematical-modeling sidecar during Idea; default is off",
    )
    science.add_argument(
        "--allow-quantitative-modeling",
        action="store_true",
        help="Convenience alias for --quantitative-mode required",
    )
    science.add_argument(
        "--quantitative-model",
        help="Override the configured LLM model for isolated Q1/Q2 idea generation",
    )
    science.add_argument(
        "--defer-author",
        action="store_true",
        help="Stop after ExperimentDesign so approved quantitative simulation can finish before Author",
    )
    science.add_argument(
        "--continue-quantitative",
        action="store_true",
        help="Resume the quantitative branch and return to Author when its handoff is ready",
    )
    science.add_argument(
        "--quantitative-handoff-manifest",
        help="Late-bind a completed quantitative Author handoff when resuming through Author",
    )
    science.add_argument("--template-dir", help="Read-only LaTeX template directory for Author")
    science.add_argument("--template-profile", help="Author rendering template profile")
    science.add_argument("--template-main", help="Author rendering template main TeX path")
    science.add_argument("--latex-engine", help="Author rendering LaTeX engine")
    science.add_argument("--bibtex", help="Author rendering BibTeX executable")
    science.add_argument("--pdf-renderer", help="Author rendering PDF renderer")
    science.add_argument(
        "--minimum-pages",
        type=int,
        help="Minimum Author report pages; defaults to 7 and normalizes the legacy value 8 to 7",
    )
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

    quantitative = subparsers.add_parser(
        "quantitative",
        help="Run the independent Q1/Q2 mathematical-modeling and numerical-simulation branch",
    )
    quantitative_subparsers = quantitative.add_subparsers(dest="quantitative_command", required=True)
    quantitative_status = quantitative_subparsers.add_parser(
        "status", help="Reconcile and print the resumable Q1/Q2 branch state"
    )
    quantitative_status.add_argument("--run-dir", required=True, help="Existing science run directory")
    quantitative_status.set_defaults(func=_quantitative_status_command)

    quantitative_continue = quantitative_subparsers.add_parser(
        "continue", help="Advance one safe quantitative branch transition without executing a solver"
    )
    quantitative_continue.add_argument("--run-dir", required=True, help="Existing science run directory")
    quantitative_continue.add_argument("--config", default=str(DEFAULT_CONFIG_PATH), help="Path to config YAML")
    quantitative_continue.add_argument("--model", help="Override the quantitative-model LLM")
    quantitative_continue.add_argument("--latex-engine", help="LaTeX engine for automatic final publication")
    quantitative_continue.add_argument("--pdf-renderer", help="PDF renderer for automatic final publication")
    quantitative_continue.add_argument("--timeout-seconds", type=int, default=180)
    quantitative_continue.set_defaults(func=_quantitative_continue_command)

    quantitative_resume_from_idea = quantitative_subparsers.add_parser(
        "resume-from-idea",
        help="Resume quantitative modeling from an existing completed Idea without rerunning Survey or Idea",
    )
    quantitative_resume_from_idea.add_argument("--run-dir", required=True, help="Existing science run directory")
    quantitative_resume_from_idea.add_argument("--config", default=str(DEFAULT_CONFIG_PATH), help="Path to config YAML")
    quantitative_resume_from_idea.add_argument("--model", help="Override the quantitative-idea LLM")
    quantitative_resume_from_idea.set_defaults(func=_quantitative_resume_from_idea_command)

    quantitative_catalog = quantitative_subparsers.add_parser(
        "catalog", help="Convert the approved advisory model catalog Markdown to JSON"
    )
    quantitative_catalog.add_argument("--output", required=True, help="JSON artifact destination")
    quantitative_catalog.set_defaults(func=_quantitative_catalog_command)

    quantitative_pde_catalog = quantitative_subparsers.add_parser(
        "pde-catalog", help="Write the executable PDE capability catalog used by model synthesis"
    )
    quantitative_pde_catalog.add_argument("--output", required=True, help="JSON artifact destination")
    quantitative_pde_catalog.set_defaults(func=_quantitative_pde_catalog_command)

    quantitative_pde_validate = quantitative_subparsers.add_parser(
        "pde-validate", help="Validate one PDEIR or PDE execution IR without executing it"
    )
    quantitative_pde_validate.add_argument("--input", required=True, help="PDEIR or execution_ir JSON file")
    quantitative_pde_validate.set_defaults(func=_quantitative_pde_validate_command)

    quantitative_pde_dry_run = quantitative_subparsers.add_parser(
        "pde-dry-run", help="Estimate PDE resources without executing a solver"
    )
    quantitative_pde_dry_run.add_argument("--input", required=True, help="PDEIR, execution_ir, or simulation plan JSON file")
    quantitative_pde_dry_run.add_argument("--resource-limits-json", help="Optional inline JSON resource limits")
    quantitative_pde_dry_run.set_defaults(func=_quantitative_pde_dry_run_command)

    quantitative_pde_refine = quantitative_subparsers.add_parser(
        "pde-refine", help="Create validated grid/time-step child PDE documents without executing them"
    )
    quantitative_pde_refine.add_argument("--input", required=True, help="PDEIR JSON file")
    quantitative_pde_refine.add_argument("--output", required=True, help="Refinement manifest destination")
    quantitative_pde_refine.add_argument("--grid-multipliers-json", default="[1, 2, 4]")
    quantitative_pde_refine.add_argument("--time-step-divisors-json", default="[1]")
    quantitative_pde_refine.set_defaults(func=_quantitative_pde_refine_command)

    quantitative_pde_refine_plans = quantitative_subparsers.add_parser(
        "pde-refine-plans", help="Create identity-bound PDE refinement plans without executing them"
    )
    quantitative_pde_refine_plans.add_argument("--input", required=True, help="Parent simulation_run_plan.json")
    quantitative_pde_refine_plans.add_argument("--output", required=True, help="Refinement plans manifest destination")
    quantitative_pde_refine_plans.add_argument("--grid-multipliers-json", default="[1, 2, 4]")
    quantitative_pde_refine_plans.add_argument("--time-step-divisors-json", default="[1]")
    quantitative_pde_refine_plans.set_defaults(func=_quantitative_pde_refine_plans_command)

    quantitative_pde_workflow_convergence = quantitative_subparsers.add_parser(
        "pde-convergence-plans", help="Persist PDE convergence plans under an existing Q version"
    )
    quantitative_pde_workflow_convergence.add_argument("--run-dir", required=True)
    quantitative_pde_workflow_convergence.add_argument("--idea-id", choices=("Q1", "Q2"), required=True)
    quantitative_pde_workflow_convergence.add_argument("--version", type=int, choices=(0, 1, 2), default=0)
    quantitative_pde_workflow_convergence.add_argument("--grid-multipliers-json", default="[1, 2, 4]")
    quantitative_pde_workflow_convergence.add_argument("--time-step-divisors-json", default="[1]")
    quantitative_pde_workflow_convergence.set_defaults(func=_quantitative_pde_workflow_convergence_command)

    quantitative_pde_verify = quantitative_subparsers.add_parser(
        "pde-verify", help="Verify an existing PDE result without re-running it"
    )
    quantitative_pde_verify.add_argument("--result", required=True, help="PDE result JSON file")
    quantitative_pde_verify.add_argument("--document", help="Optional PDEIR JSON for boundary and field-bound checks")
    quantitative_pde_verify.add_argument("--required-checks-json", default="[]")
    quantitative_pde_verify.set_defaults(func=_quantitative_pde_verify_command)

    quantitative_model = quantitative_subparsers.add_parser(
        "model", help="Legacy inline-parameter model path; use blueprint, parameters, and materialize for new Q versions"
    )
    quantitative_model.add_argument("--run-dir", required=True, help="Existing science run directory")
    quantitative_model.add_argument(
        "--quantitative-ideas-manifest", required=True, help="Verified quantitative_ideas_manifest.json"
    )
    quantitative_model.add_argument("--idea-id", choices=("Q1", "Q2"), required=True)
    quantitative_model.add_argument("--version", type=int, choices=(0, 1, 2), default=0)
    quantitative_model.add_argument("--config", default=str(DEFAULT_CONFIG_PATH), help="Path to config YAML")
    quantitative_model.add_argument("--model", help="Override the quantitative-model LLM")
    quantitative_model.add_argument("--scenarios-json", help="Optional JSON scenario list")
    quantitative_model.add_argument("--resource-limits-json", help="Optional JSON resource-limit object")
    quantitative_model.set_defaults(func=_quantitative_model_command)

    quantitative_blueprint = quantitative_subparsers.add_parser(
        "blueprint",
        help="Generate a non-numeric Q model blueprint and parameter query plan",
    )
    quantitative_blueprint.add_argument("--run-dir", required=True, help="Existing science run directory")
    quantitative_blueprint.add_argument(
        "--quantitative-ideas-manifest", required=True, help="Verified quantitative_ideas_manifest.json"
    )
    quantitative_blueprint.add_argument("--idea-id", choices=("Q1", "Q2"), required=True)
    quantitative_blueprint.add_argument("--version", type=int, choices=(0, 1, 2), default=0)
    quantitative_blueprint.add_argument("--config", default=str(DEFAULT_CONFIG_PATH), help="Path to config YAML")
    quantitative_blueprint.add_argument("--model", help="Override the quantitative-model LLM")
    quantitative_blueprint.set_defaults(func=_quantitative_blueprint_command)

    quantitative_parameters = quantitative_subparsers.add_parser(
        "parameters",
        help="Discover, extract, review, and approve evidence-bound Q parameters",
    )
    quantitative_parameters_subparsers = quantitative_parameters.add_subparsers(
        dest="quantitative_parameters_command", required=True
    )
    quantitative_parameter_discover = quantitative_parameters_subparsers.add_parser(
        "discover", help="Discover citable parameter sources through academic metadata APIs"
    )
    quantitative_parameter_discover.add_argument("--run-dir", required=True)
    quantitative_parameter_discover.add_argument("--idea-id", choices=("Q1", "Q2"), required=True)
    quantitative_parameter_discover.add_argument("--version", type=int, choices=(0, 1, 2), default=0)
    quantitative_parameter_discover.add_argument("--config", default=str(DEFAULT_CONFIG_PATH), help="Path to config YAML")
    quantitative_parameter_discover.add_argument(
        "--fetch", action="store_true", required=True, help="Explicit authorization for academic metadata network requests"
    )
    quantitative_parameter_discover.set_defaults(func=_quantitative_parameter_discover_command)

    quantitative_parameter_fulltext = quantitative_parameters_subparsers.add_parser(
        "fetch-fulltext", help="Fetch only provider-declared open-access PDFs"
    )
    quantitative_parameter_fulltext.add_argument("--run-dir", required=True)
    quantitative_parameter_fulltext.add_argument("--idea-id", choices=("Q1", "Q2"), required=True)
    quantitative_parameter_fulltext.add_argument("--version", type=int, choices=(0, 1, 2), default=0)
    quantitative_parameter_fulltext.add_argument("--config", default=str(DEFAULT_CONFIG_PATH), help="Path to config YAML")
    quantitative_parameter_fulltext.add_argument(
        "--fetch", action="store_true", required=True, help="Explicit authorization for OA full-text network requests"
    )
    quantitative_parameter_fulltext.set_defaults(func=_quantitative_parameter_fulltext_command)

    quantitative_parameter_import = quantitative_parameters_subparsers.add_parser(
        "import-document", help="Copy a user-provided local parameter source into the controlled evidence tree"
    )
    quantitative_parameter_import.add_argument("--run-dir", required=True)
    quantitative_parameter_import.add_argument("--idea-id", choices=("Q1", "Q2"), required=True)
    quantitative_parameter_import.add_argument("--version", type=int, choices=(0, 1, 2), default=0)
    quantitative_parameter_import.add_argument("--document", required=True, help="Local PDF, TXT, MD, or CSV source")
    quantitative_parameter_import.add_argument("--document-id", required=True)
    quantitative_parameter_import.add_argument("--title", required=True)
    quantitative_parameter_import.add_argument("--doi", default="")
    quantitative_parameter_import.add_argument("--year", type=int)
    quantitative_parameter_import.set_defaults(func=_quantitative_parameter_import_command)

    quantitative_parameter_extract = quantitative_parameters_subparsers.add_parser(
        "extract", help="Extract quote-anchored parameter candidates from one controlled document"
    )
    quantitative_parameter_extract.add_argument("--run-dir", required=True)
    quantitative_parameter_extract.add_argument("--idea-id", choices=("Q1", "Q2"), required=True)
    quantitative_parameter_extract.add_argument("--version", type=int, choices=(0, 1, 2), default=0)
    quantitative_parameter_extract.add_argument("--document-id", required=True)
    quantitative_parameter_extract.add_argument("--config", default=str(DEFAULT_CONFIG_PATH), help="Path to config YAML")
    quantitative_parameter_extract.add_argument("--model", help="Override the parameter-extraction LLM")
    quantitative_parameter_extract.add_argument("--max-document-chars", type=int, default=40_000)
    quantitative_parameter_extract.set_defaults(func=_quantitative_parameter_extract_command)

    quantitative_parameter_propose = quantitative_parameters_subparsers.add_parser(
        "propose", help="Create a human-reviewable parameter selection proposal"
    )
    quantitative_parameter_propose.add_argument("--run-dir", required=True)
    quantitative_parameter_propose.add_argument("--idea-id", choices=("Q1", "Q2"), required=True)
    quantitative_parameter_propose.add_argument("--version", type=int, choices=(0, 1, 2), default=0)
    quantitative_parameter_propose.add_argument("--selections-json", required=True, help="Explicit parameter selection JSON list")
    quantitative_parameter_propose.set_defaults(func=_quantitative_parameter_propose_command)

    quantitative_parameter_approve = quantitative_parameters_subparsers.add_parser(
        "approve", help="Freeze a complete parameter proposal after explicit human approval"
    )
    quantitative_parameter_approve.add_argument("--run-dir", required=True)
    quantitative_parameter_approve.add_argument("--idea-id", choices=("Q1", "Q2"), required=True)
    quantitative_parameter_approve.add_argument("--version", type=int, choices=(0, 1, 2), default=0)
    quantitative_parameter_approve.add_argument(
        "--approve", action="store_true", required=True, help="Explicit human approval of this exact parameter proposal"
    )
    quantitative_parameter_approve.set_defaults(func=_quantitative_parameter_approve_command)

    quantitative_materialize = quantitative_subparsers.add_parser(
        "materialize", help="Build an executable Q model only from an approved parameter set"
    )
    quantitative_materialize.add_argument("--run-dir", required=True, help="Existing science run directory")
    quantitative_materialize.add_argument(
        "--quantitative-ideas-manifest", required=True, help="Verified quantitative_ideas_manifest.json"
    )
    quantitative_materialize.add_argument("--idea-id", choices=("Q1", "Q2"), required=True)
    quantitative_materialize.add_argument("--version", type=int, choices=(0, 1, 2), default=0)
    quantitative_materialize.add_argument("--config", default=str(DEFAULT_CONFIG_PATH), help="Path to config YAML")
    quantitative_materialize.add_argument("--model", help="Override the quantitative-model LLM")
    quantitative_materialize.add_argument("--scenarios-json", help="Optional JSON scenario list")
    quantitative_materialize.add_argument("--resource-limits-json", help="Optional JSON resource-limit object")
    quantitative_materialize.set_defaults(func=_quantitative_materialize_command)

    quantitative_simulate = quantitative_subparsers.add_parser(
        "simulate", help="Execute exactly one audited Q plan after explicit authorization"
    )
    quantitative_simulate.add_argument("--run-dir", required=True, help="Existing science run directory")
    quantitative_simulate.add_argument("--idea-id", choices=("Q1", "Q2"), required=True)
    quantitative_simulate.add_argument("--version", type=int, choices=(0, 1, 2), default=0)
    quantitative_simulate.add_argument(
        "--execute", action="store_true", required=True, help="Explicit authorization to run this exact plan"
    )
    quantitative_simulate.add_argument(
        "--plan-identity", required=True, help="Exact plan_identity printed in simulation_run_plan.json"
    )
    quantitative_simulate.set_defaults(func=_quantitative_simulate_command)

    quantitative_qualify = quantitative_subparsers.add_parser(
        "qualify", help="Qualify one completed run and append it to the result ledger"
    )
    quantitative_qualify.add_argument("--run-dir", required=True, help="Existing science run directory")
    quantitative_qualify.add_argument("--idea-id", choices=("Q1", "Q2"), required=True)
    quantitative_qualify.add_argument("--version", type=int, choices=(0, 1, 2), default=0)
    quantitative_qualify.add_argument("--execution-id", required=True)
    quantitative_qualify.add_argument(
        "--hypothesis-relation",
        choices=("SUPPORTED_WITHIN_MODEL", "CONSTRAINED", "REFUTED_WITHIN_MODEL", "INCONCLUSIVE"),
        required=True,
    )
    quantitative_qualify.add_argument(
        "--result-summary", required=True, help="Bounded model-internal summary for the ledger"
    )
    quantitative_qualify.set_defaults(func=_quantitative_qualify_command)

    quantitative_refine = quantitative_subparsers.add_parser(
        "propose-refinement", help="Create a Q@v1/v2 proposal from qualified simulation results"
    )
    quantitative_refine.add_argument("--run-dir", required=True)
    quantitative_refine.add_argument("--idea-id", choices=("Q1", "Q2"), required=True)
    quantitative_refine.add_argument("--version", type=int, choices=(0, 1), required=True)
    quantitative_refine.add_argument("--revision-reason", required=True)
    quantitative_refine.add_argument("--hypothesis-delta", required=True)
    quantitative_refine.add_argument("--model-delta-json", required=True)
    quantitative_refine.add_argument("--parameter-or-boundary-delta-json", required=True)
    quantitative_refine.add_argument("--expected-discriminating-result", required=True)
    quantitative_refine.add_argument("--falsification-condition", required=True)
    quantitative_refine.set_defaults(func=_quantitative_propose_refinement_command)

    quantitative_accept = quantitative_subparsers.add_parser(
        "accept-revision", help="Explicitly accept a Q refinement; a new simulation still needs --execute"
    )
    quantitative_accept.add_argument("--run-dir", required=True)
    quantitative_accept.add_argument("--idea-id", choices=("Q1", "Q2"), required=True)
    quantitative_accept.add_argument("--parent-version", type=int, choices=(0, 1), required=True)
    quantitative_accept.add_argument("--accept", action="store_true", required=True)
    quantitative_accept.set_defaults(func=_quantitative_accept_revision_command)

    quantitative_feedback = quantitative_subparsers.add_parser(
        "feedback-packet", help="Create a non-mutating main-hypothesis feedback packet"
    )
    quantitative_feedback.add_argument("--run-dir", required=True)
    quantitative_feedback.set_defaults(func=_quantitative_feedback_packet_command)

    quantitative_finalize = quantitative_subparsers.add_parser(
        "finalize", help="Freeze a Q version with all qualified outcomes before publication"
    )
    quantitative_finalize.add_argument("--run-dir", required=True)
    quantitative_finalize.add_argument("--idea-id", choices=("Q1", "Q2"), required=True)
    quantitative_finalize.add_argument("--version", type=int, choices=(0, 1, 2), required=True)
    quantitative_finalize.set_defaults(func=_quantitative_finalize_command)

    quantitative_publish = quantitative_subparsers.add_parser(
        "publish", help="Render the single standalone mathematical-model PDF for finalized Q ideas"
    )
    quantitative_publish.add_argument("--run-dir", required=True)
    quantitative_publish.add_argument("--latex-engine", help="LaTeX engine for the supplementary PDF")
    quantitative_publish.add_argument("--pdf-renderer", help="PDF renderer for first-page validation")
    quantitative_publish.add_argument("--timeout-seconds", type=int, default=180)
    quantitative_publish.set_defaults(func=_quantitative_publish_command)

    quantitative_handoff = quantitative_subparsers.add_parser(
        "author-handoff", help="Build a controlled Author sidecar after the supplementary PDF is validated"
    )
    quantitative_handoff.add_argument("--run-dir", required=True)
    quantitative_handoff.add_argument(
        "--quantitative-models-pdf",
        help="Defaults to the published quantitative_mathematical_models.pdf inside the run",
    )
    quantitative_handoff.set_defaults(func=_quantitative_author_handoff_command)

    quantitative_bundle = quantitative_subparsers.add_parser(
        "bundle", help="Bind the main Author PDF and standalone quantitative PDF without merging them"
    )
    quantitative_bundle.add_argument("--run-dir", required=True)
    quantitative_bundle.add_argument("--main-article-pdf", required=True)
    quantitative_bundle.add_argument("--quantitative-author-handoff-manifest", required=True)
    quantitative_bundle.set_defaults(func=_quantitative_bundle_command)

    doctor = subparsers.add_parser("doctor", help="Check local runtime prerequisites")
    doctor.add_argument("--config", default=str(DEFAULT_CONFIG_PATH), help="Path to config YAML")
    doctor.set_defaults(func=_doctor_command)

    install = subparsers.add_parser("install-mcp-wrappers", help="Install local MCP wrapper scripts")
    install.set_defaults(func=_install_mcp_wrappers_command)

    return parser


def _prepare_survey_multimodal_input(
    args: argparse.Namespace,
    config: object,
) -> tuple[object | None, dict[str, object] | None, dict[str, object] | None, MultimodalSettings]:
    raw_files = list(getattr(args, "multimodal_file", None) or [])
    manifest_value = getattr(args, "multimodal_evidence_manifest", None)
    remote_perception_authorized = bool(
        getattr(args, "allow_remote_perception", False)
    )
    has_multimodal_input = bool(raw_files or manifest_value)
    if remote_perception_authorized and not has_multimodal_input:
        raise MultimodalInputError(
            "--allow-remote-perception requires --multimodal-file or --multimodal-evidence-manifest."
        )
    if not has_multimodal_input:
        return None, None, None, MultimodalSettings()

    survey_config = (
        config.get("survey")
        if hasattr(config, "get") and config.get("survey") is not None
        else config
    )
    configured_settings = (
        survey_config.get("multimodal_evidence", {})
        if hasattr(survey_config, "get")
        else {}
    )
    settings_data = OmegaConf.to_container(configured_settings, resolve=False)
    if not isinstance(settings_data, dict):
        settings_data = {}
    settings_data["remote_perception_authorized"] = remote_perception_authorized
    settings = MultimodalSettings.from_mapping(settings_data)
    if manifest_value:
        input_spec = load_input_manifest(
            _resolve_cli_path(manifest_value),
            settings=settings,
        )
    else:
        input_spec = build_input_spec_from_files(
            [_resolve_cli_path(value) for value in raw_files],
            settings=settings,
        )
    preflight_multimodal_capabilities(
        input_spec,
        remote_perception_authorized=settings.remote_perception_authorized,
    )
    local_context = build_local_multimodal_input_context(
        input_spec,
        settings=settings,
    )
    runtime_evidence = build_multimodal_evidence(
        input_spec=input_spec,
        config=config,
        local_context=local_context,
    )
    return input_spec, local_context, runtime_evidence, settings


def _needs_multimodal_runtime_reset(config: object) -> bool:
    survey_config = (
        config.get("survey")
        if hasattr(config, "get") and config.get("survey") is not None
        else config
    )
    configured = (
        survey_config.get("multimodal_evidence", {})
        if hasattr(survey_config, "get")
        else {}
    )
    if not hasattr(configured, "get"):
        return False
    return any(
        bool(configured.get(key))
        for key in (
            "enabled",
            "allow_remote_perception",
            "input_spec",
            "local_input_context",
            "runtime_evidence",
        )
    )


def _multimodal_override_requested(overrides: Sequence[str]) -> bool:
    """Keep explicit CLI input as the only route into multimodal runtime state."""

    for raw_override in overrides:
        key = str(raw_override or "").strip().lstrip("+~")
        key = key.split("=", 1)[0].strip()
        if key == "multimodal_evidence" or key.startswith("multimodal_evidence."):
            return True
        if key == "survey.multimodal_evidence" or key.startswith(
            "survey.multimodal_evidence."
        ):
            return True
    return False


def _survey_command(args: argparse.Namespace) -> int:
    config_path = _resolve_config_path(args.config)
    _ensure_config_exists(config_path)
    if _multimodal_override_requested(args.overrides):
        print(
            "Multimodal runtime settings cannot be overridden positionally; use "
            "--multimodal-file or --multimodal-evidence-manifest and, when intended, "
            "--allow-remote-perception.",
            file=sys.stderr,
        )
        return 2
    override_key = lambda key: _survey_override_key(config_path, key)
    config = OmegaConf.load(config_path)
    try:
        (
            multimodal_input_spec,
            multimodal_local_context,
            multimodal_runtime_evidence,
            multimodal_settings,
        ) = (
            _prepare_survey_multimodal_input(args, config)
        )
    except MultimodalInputError as exc:
        print(f"Multimodal input error: {exc}", file=sys.stderr)
        return 2
    multimodal_updates: list[tuple[str, object]] = []
    if multimodal_input_spec is not None or _needs_multimodal_runtime_reset(config):
        multimodal_updates = [
            (
                override_key("multimodal_evidence.enabled"),
                multimodal_input_spec is not None,
            ),
            (
                override_key("multimodal_evidence.allow_remote_perception"),
                multimodal_settings.remote_perception_authorized,
            ),
            (
                override_key("multimodal_evidence.input_spec"),
                multimodal_input_spec.to_safe_runtime_dict()
                if multimodal_input_spec is not None
                else {},
            ),
            (
                override_key("multimodal_evidence.local_input_context"),
                multimodal_local_context or {},
            ),
            (
                override_key("multimodal_evidence.runtime_evidence"),
                multimodal_runtime_evidence or {},
            ),
        ]
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
            *multimodal_updates,
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
        quantitative_handoff_manifest_path = (
            _resolve_cli_path(args.quantitative_handoff_manifest)
            if args.quantitative_handoff_manifest
            else None
        )
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
            quantitative_handoff_manifest_path=quantitative_handoff_manifest_path,
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
                    minimum_pages=args.minimum_pages,
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
    quantitative_mode = args.quantitative_mode
    if getattr(args, "allow_quantitative_modeling", False):
        quantitative_mode = "required"
    return {
        "discipline_ids": args.discipline_id,
        "selected_direction": args.selected_direction,
        "exp_design_model": args.exp_design_model,
        "author_model": args.author_model,
        "quantitative_mode": quantitative_mode,
        "quantitative_model": args.quantitative_model,
        "template_dir": _science_path_option(args.template_dir),
        "template_profile": _science_template_profile_option(args.template_profile),
        "template_main": args.template_main,
        "latex_engine": _science_executable_option(args.latex_engine),
        "bibtex": _science_executable_option(args.bibtex),
        "pdf_renderer": _science_executable_option(args.pdf_renderer),
        "minimum_pages": args.minimum_pages,
        "compile_timeout_seconds": args.compile_timeout_seconds,
        "author_name": args.author_name,
        "render_required": args.render_required,
        "survey_appendix": args.survey_appendix,
    }


def _required_quantitative_sidecar_has_no_candidates(
    *, paths: ScienceRunPaths, state: Mapping[str, object], metadata: Mapping[str, object]
) -> bool:
    """Allow required-mode Author only when the verified sidecar found no Q."""

    stages = state.get("stages")
    idea_stage = stages.get("idea") if isinstance(stages, Mapping) else None
    idea_stage_mapping = idea_stage if isinstance(idea_stage, Mapping) else {}
    outputs = idea_stage_mapping.get("outputs")
    outputs_mapping = outputs if isinstance(outputs, Mapping) else {}
    raw_manifest = str(outputs_mapping.get("quantitative_ideas_manifest") or "").strip()
    if raw_manifest:
        manifest_path = Path(raw_manifest).expanduser().resolve()
    else:
        raw_idea_manifest = str(idea_stage_mapping.get("result_manifest_path") or "").strip()
        if not raw_idea_manifest:
            return False
        manifest_path = Path(raw_idea_manifest).expanduser().resolve().parent / "quantitative_ideas_manifest.json"
    try:
        manifest_path.relative_to((paths.run_dir / "idea").resolve())
    except ValueError as exc:
        raise ScienceRunInputError(
            "required quantitative sidecar must remain under the science run Idea directory"
        ) from exc
    if not manifest_path.is_file():
        return False
    try:
        from src.pipeline.quantitative_manifests import verify_quantitative_ideas_manifest

        immutable_inputs = metadata.get("immutable_inputs")
        immutable_mapping = immutable_inputs if isinstance(immutable_inputs, Mapping) else {}
        topic = str(immutable_mapping.get("topic") or "").strip()
        verified = verify_quantitative_ideas_manifest(manifest_path, expected_topic=topic)
    except Exception as exc:
        raise ScienceRunInputError(
            f"required quantitative sidecar validation failed: {exc}"
        ) from exc
    return (
        str(verified.payload.get("generation_status") or "").strip() == "NO_ELIGIBLE_IDEAS"
        and not list(verified.payload.get("ideas") or [])
    )


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


def _bind_quantitative_publication_bundle(
    *, paths: ScienceRunPaths, state: Mapping[str, object], handoff_path: Path | None
) -> Path | None:
    if handoff_path is None:
        return None
    stages = state.get("stages")
    author_stage = stages.get("author") if isinstance(stages, Mapping) else None
    if not isinstance(author_stage, Mapping) or author_stage.get("status") != "COMPLETED":
        return None
    outputs = author_stage.get("outputs")
    main_pdf_value = outputs.get("render_pdf") if isinstance(outputs, Mapping) else None
    main_pdf = Path(str(main_pdf_value or "")).expanduser().resolve()
    if not main_pdf.is_file():
        raise ScienceRunStateError(
            "quantitative closed loop requires a rendered main Author PDF before bundling"
        )
    bundle_path = paths.run_dir / "quantitative" / "publication" / "publication_bundle_manifest.json"
    if bundle_path.is_file():
        return bundle_path
    try:
        from src.agents.quantitative_modeling.publication_bundle import build_publication_bundle

        return build_publication_bundle(
            run_dir=paths.run_dir,
            main_article_pdf=main_pdf,
            quantitative_author_handoff_manifest=handoff_path,
        )
    except Exception as exc:
        raise ScienceRunStateError(f"Cannot bind the two formal PDFs: {exc}") from exc


def _science_command(args: argparse.Namespace) -> int:
    if bool(args.restart_from) != bool(args.force):
        print("science input error: --restart-from and --force must be supplied together", file=sys.stderr)
        return SCIENCE_EXIT_INPUT_ERROR

    if args.continue_quantitative and (
        not args.resume
        or args.until != "author"
        or args.defer_author
        or args.quantitative_handoff_manifest
        or args.restart_from
    ):
        print(
            "science input error: --continue-quantitative requires --resume --until author "
            "without --defer-author, --restart-from, or an explicit handoff",
            file=sys.stderr,
        )
        return SCIENCE_EXIT_INPUT_ERROR
    if args.defer_author and args.until not in {"author", "exp_design"}:
        print("science input error: --defer-author is only compatible with --until author or exp_design", file=sys.stderr)
        return SCIENCE_EXIT_INPUT_ERROR
    requested_quantitative_mode = args.quantitative_mode
    if args.allow_quantitative_modeling:
        requested_quantitative_mode = "required"
    auto_defer_quantitative = (
        not args.resume
        and args.until == "author"
        and not args.defer_author
        and str(requested_quantitative_mode or "off").casefold() == "required"
    )
    effective_until = "exp_design" if args.defer_author or auto_defer_quantitative else args.until
    if args.quantitative_handoff_manifest and not args.resume:
        print(
            "science input error: --quantitative-handoff-manifest requires --resume",
            file=sys.stderr,
        )
        return SCIENCE_EXIT_INPUT_ERROR
    if args.quantitative_handoff_manifest and effective_until != "author":
        print(
            "science input error: --quantitative-handoff-manifest requires --until author",
            file=sys.stderr,
        )
        return SCIENCE_EXIT_INPUT_ERROR
    explicit_options = _science_immutable_options(args)
    paths: ScienceRunPaths | None = None
    metadata: dict[str, object] | None = None
    quantitative_handoff_path: Path | None = None
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
                if args.quantitative_handoff_manifest:
                    quantitative_handoff_path = _resolve_cli_path(args.quantitative_handoff_manifest)
                else:
                    default_handoff = (
                        paths.run_dir
                        / "quantitative"
                        / "author"
                        / "quantitative_author_handoff_manifest.json"
                    )
                    if effective_until == "author" and default_handoff.is_file():
                        quantitative_handoff_path = default_handoff
                immutable_options = metadata.get("immutable_inputs", {}).get("options", {})
                quantitative_options = (
                    immutable_options.get("quantitative", {})
                    if isinstance(immutable_options, Mapping)
                    else {}
                )
                quantitative_mode = (
                    quantitative_options.get("mode")
                    if isinstance(quantitative_options, Mapping)
                    else None
                ) or (immutable_options.get("quantitative_mode") if isinstance(immutable_options, Mapping) else None)
                if (
                    effective_until == "author"
                    and str(quantitative_mode or "off").casefold() == "required"
                    and quantitative_handoff_path is None
                    and not args.continue_quantitative
                ):
                    stages = state.get("stages")
                    exp_design_stage = stages.get("exp_design") if isinstance(stages, Mapping) else None
                    exp_design_status = (
                        exp_design_stage.get("status")
                        if isinstance(exp_design_stage, Mapping)
                        else None
                    )
                    if exp_design_status != "COMPLETED":
                        effective_until = "exp_design"
                if (
                    effective_until == "author"
                    and str(quantitative_mode or "off").casefold() == "required"
                    and quantitative_handoff_path is None
                    and not args.continue_quantitative
                    and not _required_quantitative_sidecar_has_no_candidates(
                        paths=paths,
                        state=state,
                        metadata=metadata,
                    )
                ):
                    raise ScienceRunInputError(
                        "required quantitative mode needs a completed quantitative Author handoff before Author; "
                        "run quantitative status/continue and complete the Q branch first"
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
        if args.continue_quantitative:
            from src.agents.quantitative_modeling.idea_generation import build_quantitative_json_llm_call
            from src.agents.quantitative_modeling.model_synthesis import build_quantitative_model_llm_call
            from src.config import load_config
            from src.pipeline.quantitative_orchestrator import (
                continue_quantitative_until_author_ready,
            )

            immutable_inputs = metadata.get("immutable_inputs")
            immutable_mapping = immutable_inputs if isinstance(immutable_inputs, Mapping) else {}
            immutable_options = immutable_mapping.get("options")
            options_mapping = immutable_options if isinstance(immutable_options, Mapping) else {}
            models = options_mapping.get("models")
            models_mapping = models if isinstance(models, Mapping) else {}
            quantitative_model = str(
                args.quantitative_model
                or models_mapping.get("quantitative")
                or options_mapping.get("quantitative_model")
                or ""
            ).strip() or None
            try:
                quantitative_config = load_config(str(paths.config_snapshot))
                quantitative_state = continue_quantitative_until_author_ready(
                    run_dir=paths.run_dir,
                    idea_llm_call=build_quantitative_json_llm_call(
                        config=quantitative_config,
                        model=quantitative_model,
                    ),
                    model_llm_call=build_quantitative_model_llm_call(
                        config=quantitative_config,
                        model=quantitative_model,
                    ),
                    latex_engine=_science_executable_option(args.latex_engine),
                    pdf_renderer=_science_executable_option(args.pdf_renderer),
                    timeout_seconds=int(args.compile_timeout_seconds or 180),
                )
            except Exception as exc:
                raise ScienceRunStateError(f"quantitative continuation failed: {exc}") from exc

            quantitative_status = str(quantitative_state.get("status") or "").strip()
            if quantitative_status not in {"NO_QUANTITATIVE_IDEAS", "HANDED_OFF"}:
                result = _persist_science_result(
                    action=action,
                    paths=paths,
                    until="exp_design",
                )
                if result is None:
                    raise ScienceRunStateError("Cannot persist science_result.json")
                result["quantitative_state"] = quantitative_state
                if args.json:
                    print(json.dumps(result, ensure_ascii=False, sort_keys=True, allow_nan=False))
                else:
                    _print_science_result(result, as_json=False)
                    _print_quantitative_result(
                        {
                            "status": quantitative_status,
                            "run_dir": str(paths.run_dir),
                            "quantitative_state": quantitative_state,
                        }
                    )
                return SCIENCE_EXIT_SUCCESS
            if quantitative_status == "HANDED_OFF":
                quantitative_handoff_path = (
                    paths.run_dir
                    / "quantitative"
                    / "author"
                    / "quantitative_author_handoff_manifest.json"
                )
        with contextlib.redirect_stdout(sys.stderr if args.json else sys.stdout):
            outcome = run_science_workflow(
                paths=paths,
                metadata=metadata,
                until=effective_until,
                quiet=bool(args.json),
                quantitative_handoff_manifest_path=quantitative_handoff_path,
            )
        _bind_quantitative_publication_bundle(
            paths=paths,
            state=outcome.state,
            handoff_path=quantitative_handoff_path,
        )
        result = _persist_science_result(
            action=action,
            paths=paths,
            until=effective_until,
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
                until=effective_until,
                error=error_payload,
                expected_state_revision=exc.observed_state_revision,
            )
        if failure_result is None and paths is not None and metadata is not None and exc.observed_state:
            failure_result = _science_result_payload(
                action=action,
                paths=paths,
                metadata=metadata,
                state=exc.observed_state,
                until=effective_until,
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


def _quantitative_json_option(value: str | None, *, label: str) -> object:
    if value is None:
        return None
    try:
        decoded = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{label} must be valid inline JSON") from exc
    return decoded


def _print_quantitative_result(payload: Mapping[str, object]) -> None:
    print(json.dumps(dict(payload), ensure_ascii=False, sort_keys=True, allow_nan=False))


def _quantitative_catalog_command(args: argparse.Namespace) -> int:
    try:
        from src.agents.quantitative_modeling.catalog import write_model_catalog_json

        output = write_model_catalog_json(output_path=_resolve_cli_path(args.output))
    except (OSError, ValueError) as exc:
        print(f"quantitative catalog error: {exc}", file=sys.stderr)
        return QUANTITATIVE_EXIT_INPUT_ERROR
    _print_quantitative_result({"status": "COMPLETED", "catalog_json": str(output)})
    return QUANTITATIVE_EXIT_SUCCESS


def _quantitative_pde_catalog_command(args: argparse.Namespace) -> int:
    try:
        from src.agents.quantitative_modeling.pde_capability_registry import (
            design_pde_catalog,
            executable_pde_catalog,
        )

        output = _resolve_cli_path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(
            output,
            {
                "schema_version": "pde_capability_catalog_v1",
                "execution_boundary": "Only listed fixed adapters are executable; LLM output remains declarative PDEIR.",
                "families": executable_pde_catalog(),
                "design_only_families": design_pde_catalog(),
            },
        )
    except (OSError, ValueError) as exc:
        print(f"quantitative PDE catalog error: {exc}", file=sys.stderr)
        return QUANTITATIVE_EXIT_INPUT_ERROR
    _print_quantitative_result({"status": "COMPLETED", "pde_catalog_json": str(output)})
    return QUANTITATIVE_EXIT_SUCCESS


def _quantitative_read_json_file(path_value: str, *, label: str) -> dict[str, object]:
    path = _resolve_cli_path(path_value)
    try:
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is not valid JSON: {path}") from exc
    if not isinstance(payload, Mapping):
        raise ValueError(f"{label} must be a JSON object")
    return dict(payload)


def _quantitative_pde_document_from_payload(payload: Mapping[str, object]) -> dict[str, object]:
    from src.agents.quantitative_modeling.execution_ir import validate_execution_ir
    from src.agents.quantitative_modeling.pdeir import validate_pdeir_document

    if payload.get("kind") == "PDE":
        return dict(validate_execution_ir(payload)["document"])
    if payload.get("schema_version") == "execution_ir_v1":
        return dict(validate_execution_ir(payload)["document"])
    return dict(validate_pdeir_document(payload))


def _quantitative_pde_validate_command(args: argparse.Namespace) -> int:
    try:
        from src.agents.quantitative_modeling.execution_ir import validate_execution_ir
        from src.agents.quantitative_modeling.pdeir import validate_pdeir_document

        payload = _quantitative_read_json_file(args.input, label="PDE input")
        normalized = validate_execution_ir(payload) if payload.get("kind") == "PDE" else validate_pdeir_document(payload)
    except (OSError, ValueError) as exc:
        print(f"quantitative PDE validation input error: {exc}", file=sys.stderr)
        return QUANTITATIVE_EXIT_INPUT_ERROR
    _print_quantitative_result({"status": "VALIDATED", "pde": normalized})
    return QUANTITATIVE_EXIT_SUCCESS


def _quantitative_pde_dry_run_command(args: argparse.Namespace) -> int:
    try:
        from src.agents.quantitative_modeling.pde.diagnostics import estimate_pde_execution

        payload = _quantitative_read_json_file(args.input, label="PDE input")
        if payload.get("schema_version") == "simulation_run_plan_v1":
            execution_ir = payload.get("execution_ir")
            if not isinstance(execution_ir, Mapping):
                raise ValueError("simulation plan does not contain a PDE execution_ir")
            document = _quantitative_pde_document_from_payload(execution_ir)
        else:
            document = _quantitative_pde_document_from_payload(payload)
        limits = _quantitative_json_option(args.resource_limits_json, label="--resource-limits-json")
        estimate = estimate_pde_execution(document, resource_limits=limits if isinstance(limits, Mapping) else None)
    except (OSError, ValueError) as exc:
        print(f"quantitative PDE dry-run input error: {exc}", file=sys.stderr)
        return QUANTITATIVE_EXIT_INPUT_ERROR
    _print_quantitative_result(estimate)
    return QUANTITATIVE_EXIT_SUCCESS if estimate["execution_status"] == "READY" else QUANTITATIVE_EXIT_EXECUTION_ERROR


def _quantitative_pde_refine_command(args: argparse.Namespace) -> int:
    try:
        from src.agents.quantitative_modeling.pde.convergence import build_refinement_documents

        payload = _quantitative_read_json_file(args.input, label="PDE input")
        document = _quantitative_pde_document_from_payload(payload)
        grid_multipliers = _quantitative_json_option(args.grid_multipliers_json, label="--grid-multipliers-json")
        time_step_divisors = _quantitative_json_option(args.time_step_divisors_json, label="--time-step-divisors-json")
        if not isinstance(grid_multipliers, list) or not isinstance(time_step_divisors, list):
            raise ValueError("refinement levels must be JSON lists")
        children = build_refinement_documents(
            document,
            grid_multipliers=grid_multipliers,
            time_step_divisors=time_step_divisors,
        )
        output = _resolve_cli_path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(
            output,
            {
                "schema_version": "pde_refinement_manifest_v1",
                "requires_explicit_execution": True,
                "children": children,
            },
        )
    except (OSError, ValueError) as exc:
        print(f"quantitative PDE refinement input error: {exc}", file=sys.stderr)
        return QUANTITATIVE_EXIT_INPUT_ERROR
    _print_quantitative_result({"status": "PLANNED", "refinement_manifest": str(output)})
    return QUANTITATIVE_EXIT_SUCCESS


def _quantitative_pde_refine_plans_command(args: argparse.Namespace) -> int:
    try:
        from src.agents.quantitative_modeling.pde.convergence import build_refinement_plans

        parent_plan = _quantitative_read_json_file(args.input, label="parent simulation plan")
        grid_multipliers = _quantitative_json_option(args.grid_multipliers_json, label="--grid-multipliers-json")
        time_step_divisors = _quantitative_json_option(args.time_step_divisors_json, label="--time-step-divisors-json")
        if not isinstance(grid_multipliers, list) or not isinstance(time_step_divisors, list):
            raise ValueError("refinement levels must be JSON lists")
        plans = build_refinement_plans(
            parent_plan,
            grid_multipliers=grid_multipliers,
            time_step_divisors=time_step_divisors,
        )
        output = _resolve_cli_path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(
            output,
            {
                "schema_version": "pde_refinement_plan_manifest_v1",
                "requires_explicit_execution": True,
                "plans": plans,
            },
        )
    except (OSError, ValueError) as exc:
        print(f"quantitative PDE refinement-plan input error: {exc}", file=sys.stderr)
        return QUANTITATIVE_EXIT_INPUT_ERROR
    _print_quantitative_result({"status": "PLANNED", "refinement_plan_manifest": str(output)})
    return QUANTITATIVE_EXIT_SUCCESS


def _quantitative_pde_workflow_convergence_command(args: argparse.Namespace) -> int:
    try:
        from src.pipeline.quantitative_workflow import prepare_pde_convergence_plans

        grid_multipliers = _quantitative_json_option(args.grid_multipliers_json, label="--grid-multipliers-json")
        time_step_divisors = _quantitative_json_option(args.time_step_divisors_json, label="--time-step-divisors-json")
        if not isinstance(grid_multipliers, list) or not isinstance(time_step_divisors, list):
            raise ValueError("refinement levels must be JSON lists")
        paths = prepare_pde_convergence_plans(
            run_dir=_resolve_cli_path(args.run_dir),
            quantitative_idea_id=args.idea_id,
            version=args.version,
            grid_multipliers=tuple(grid_multipliers),
            time_step_divisors=tuple(time_step_divisors),
        )
    except (OSError, ValueError) as exc:
        print(f"quantitative PDE convergence-plan input error: {exc}", file=sys.stderr)
        return QUANTITATIVE_EXIT_INPUT_ERROR
    _print_quantitative_result({"status": "PLANNED", **paths})
    return QUANTITATIVE_EXIT_SUCCESS


def _quantitative_pde_verify_command(args: argparse.Namespace) -> int:
    try:
        from src.agents.quantitative_modeling.pde_verification import verify_pde_result

        result = _quantitative_read_json_file(args.result, label="PDE result")
        document = (
            _quantitative_pde_document_from_payload(
                _quantitative_read_json_file(args.document, label="PDE document")
            )
            if args.document
            else None
        )
        required_checks = _quantitative_json_option(args.required_checks_json, label="--required-checks-json")
        if not isinstance(required_checks, list):
            raise ValueError("--required-checks-json must be a JSON list")
        verification = verify_pde_result(result, document=document, required_checks=required_checks)
    except (OSError, ValueError) as exc:
        print(f"quantitative PDE verification input error: {exc}", file=sys.stderr)
        return QUANTITATIVE_EXIT_INPUT_ERROR
    _print_quantitative_result(verification)
    return QUANTITATIVE_EXIT_SUCCESS if verification["status"] == "NUMERICALLY_VERIFIED" else QUANTITATIVE_EXIT_EXECUTION_ERROR


def _quantitative_status_command(args: argparse.Namespace) -> int:
    try:
        from src.pipeline.quantitative_orchestrator import refresh_quantitative_state

        run_dir = _resolve_cli_path(args.run_dir)
        state = refresh_quantitative_state(run_dir)
        from src.pipeline.quantitative_state import quantitative_state_path

        _print_quantitative_result(
            {
                "status": state["status"],
                "science_run_id": state["science_run_id"],
                "run_dir": str(run_dir),
                "state_path": str(quantitative_state_path(run_dir)),
                "quantitative_state": state,
            }
        )
    except (OSError, ValueError) as exc:
        print(f"quantitative status input error: {exc}", file=sys.stderr)
        return QUANTITATIVE_EXIT_INPUT_ERROR
    except Exception as exc:
        print(f"quantitative status error: {exc}", file=sys.stderr)
        return QUANTITATIVE_EXIT_EXECUTION_ERROR
    return QUANTITATIVE_EXIT_SUCCESS


def _quantitative_continue_command(args: argparse.Namespace) -> int:
    try:
        from src.config import load_config
        from src.pipeline.quantitative_orchestrator import continue_quantitative_workflow

        config_path = _resolve_config_path(args.config)
        _ensure_config_exists(config_path)
        config = load_config(str(config_path))
        from src.agents.quantitative_modeling.model_synthesis import build_quantitative_model_llm_call

        state = continue_quantitative_workflow(
            run_dir=_resolve_cli_path(args.run_dir),
            llm_call=build_quantitative_model_llm_call(config=config, model=args.model),
            latex_engine=_science_executable_option(args.latex_engine),
            pdf_renderer=_science_executable_option(args.pdf_renderer),
            timeout_seconds=args.timeout_seconds,
        )
        _print_quantitative_result({"status": state["status"], "quantitative_state": state})
    except (OSError, ValueError) as exc:
        print(f"quantitative continuation input error: {exc}", file=sys.stderr)
        return QUANTITATIVE_EXIT_INPUT_ERROR
    except Exception as exc:
        print(f"quantitative continuation error: {exc}", file=sys.stderr)
        return QUANTITATIVE_EXIT_EXECUTION_ERROR
    return QUANTITATIVE_EXIT_SUCCESS


def _quantitative_resume_from_idea_command(args: argparse.Namespace) -> int:
    try:
        from src.agents.quantitative_modeling.idea_generation import build_quantitative_json_llm_call
        from src.config import load_config
        from src.pipeline.quantitative_orchestrator import resume_quantitative_from_existing_idea

        config_path = _resolve_config_path(args.config)
        _ensure_config_exists(config_path)
        config = load_config(str(config_path))
        run_dir = _resolve_cli_path(args.run_dir)
        state = resume_quantitative_from_existing_idea(
            run_dir=run_dir,
            llm_call=build_quantitative_json_llm_call(config=config, model=args.model),
        )
        _print_quantitative_result(
            {
                "status": state["status"],
                "run_dir": str(run_dir),
                "quantitative_state": state,
            }
        )
    except (OSError, ValueError) as exc:
        print(f"quantitative resume-from-idea input error: {exc}", file=sys.stderr)
        return QUANTITATIVE_EXIT_INPUT_ERROR
    except Exception as exc:
        print(f"quantitative resume-from-idea error: {exc}", file=sys.stderr)
        return QUANTITATIVE_EXIT_EXECUTION_ERROR
    return QUANTITATIVE_EXIT_SUCCESS


def _quantitative_model_command(args: argparse.Namespace) -> int:
    try:
        from src.agents.quantitative_modeling.model_synthesis import build_quantitative_model_llm_call
        from src.config import load_config
        from src.pipeline.quantitative_workflow import prepare_quantitative_model_version

        config_path = _resolve_config_path(args.config)
        _ensure_config_exists(config_path)
        paths = prepare_quantitative_model_version(
            run_dir=_resolve_cli_path(args.run_dir),
            quantitative_ideas_manifest_path=_resolve_cli_path(args.quantitative_ideas_manifest),
            quantitative_idea_id=args.idea_id,
            version=args.version,
            llm_call=build_quantitative_model_llm_call(
                config=load_config(str(config_path)), model=args.model
            ),
            scenarios=_quantitative_json_option(args.scenarios_json, label="--scenarios-json"),
            resource_limits=_quantitative_json_option(
                args.resource_limits_json, label="--resource-limits-json"
            ),
        )
    except (OSError, ValueError) as exc:
        print(f"quantitative model input error: {exc}", file=sys.stderr)
        return QUANTITATIVE_EXIT_INPUT_ERROR
    except Exception as exc:
        print(f"quantitative model error: {exc}", file=sys.stderr)
        return QUANTITATIVE_EXIT_MODEL_ERROR
    _print_quantitative_result({"status": "MODEL_AUDITED", **paths})
    return QUANTITATIVE_EXIT_SUCCESS


def _quantitative_blueprint_command(args: argparse.Namespace) -> int:
    try:
        from src.agents.quantitative_modeling.model_synthesis import build_quantitative_model_llm_call
        from src.config import load_config
        from src.pipeline.quantitative_workflow import prepare_quantitative_model_blueprint

        config_path = _resolve_config_path(args.config)
        _ensure_config_exists(config_path)
        paths = prepare_quantitative_model_blueprint(
            run_dir=_resolve_cli_path(args.run_dir),
            quantitative_ideas_manifest_path=_resolve_cli_path(args.quantitative_ideas_manifest),
            quantitative_idea_id=args.idea_id,
            version=args.version,
            llm_call=build_quantitative_model_llm_call(
                config=load_config(str(config_path)), model=args.model
            ),
        )
    except (OSError, ValueError) as exc:
        print(f"quantitative blueprint input error: {exc}", file=sys.stderr)
        return QUANTITATIVE_EXIT_INPUT_ERROR
    except Exception as exc:
        print(f"quantitative blueprint error: {exc}", file=sys.stderr)
        return QUANTITATIVE_EXIT_MODEL_ERROR
    _print_quantitative_result({"status": "BLUEPRINT_READY", **paths})
    return QUANTITATIVE_EXIT_SUCCESS


def _quantitative_parameter_discover_command(args: argparse.Namespace) -> int:
    try:
        from src.config import load_config
        from src.pipeline.quantitative_workflow import discover_quantitative_parameter_evidence

        config_path = _resolve_config_path(args.config)
        _ensure_config_exists(config_path)
        discovery = discover_quantitative_parameter_evidence(
            run_dir=_resolve_cli_path(args.run_dir),
            quantitative_idea_id=args.idea_id,
            version=args.version,
            fetch=bool(args.fetch),
            runtime_config=load_config(str(config_path)),
        )
    except (OSError, ValueError) as exc:
        print(f"quantitative parameter discovery input error: {exc}", file=sys.stderr)
        return QUANTITATIVE_EXIT_INPUT_ERROR
    except Exception as exc:
        print(f"quantitative parameter discovery error: {exc}", file=sys.stderr)
        return QUANTITATIVE_EXIT_EXECUTION_ERROR
    _print_quantitative_result({"status": "DISCOVERED", "discovery": str(discovery)})
    return QUANTITATIVE_EXIT_SUCCESS


def _quantitative_parameter_fulltext_command(args: argparse.Namespace) -> int:
    try:
        from src.config import load_config
        from src.pipeline.quantitative_workflow import fetch_quantitative_parameter_fulltext

        config_path = _resolve_config_path(args.config)
        _ensure_config_exists(config_path)
        manifest = fetch_quantitative_parameter_fulltext(
            run_dir=_resolve_cli_path(args.run_dir),
            quantitative_idea_id=args.idea_id,
            version=args.version,
            fetch=bool(args.fetch),
            runtime_config=load_config(str(config_path)),
        )
    except (OSError, ValueError) as exc:
        print(f"quantitative parameter full-text input error: {exc}", file=sys.stderr)
        return QUANTITATIVE_EXIT_INPUT_ERROR
    except Exception as exc:
        print(f"quantitative parameter full-text error: {exc}", file=sys.stderr)
        return QUANTITATIVE_EXIT_EXECUTION_ERROR
    _print_quantitative_result({"status": "FULLTEXT_FETCHED", "manifest": str(manifest)})
    return QUANTITATIVE_EXIT_SUCCESS


def _quantitative_parameter_import_command(args: argparse.Namespace) -> int:
    try:
        from src.pipeline.quantitative_workflow import register_quantitative_parameter_document

        record = register_quantitative_parameter_document(
            run_dir=_resolve_cli_path(args.run_dir),
            quantitative_idea_id=args.idea_id,
            version=args.version,
            document_path=_resolve_cli_path(args.document),
            document_id=args.document_id,
            title=args.title,
            doi=args.doi,
            year=args.year,
        )
    except (OSError, ValueError) as exc:
        print(f"quantitative parameter document input error: {exc}", file=sys.stderr)
        return QUANTITATIVE_EXIT_INPUT_ERROR
    except Exception as exc:
        print(f"quantitative parameter document error: {exc}", file=sys.stderr)
        return QUANTITATIVE_EXIT_EXECUTION_ERROR
    _print_quantitative_result({"status": "DOCUMENT_REGISTERED", "document_record": str(record)})
    return QUANTITATIVE_EXIT_SUCCESS


def _quantitative_parameter_extract_command(args: argparse.Namespace) -> int:
    try:
        from src.agents.quantitative_modeling.model_synthesis import build_quantitative_model_llm_call
        from src.config import load_config
        from src.pipeline.quantitative_workflow import extract_quantitative_parameter_candidates

        if args.max_document_chars < 1:
            raise ValueError("--max-document-chars must be positive")
        config_path = _resolve_config_path(args.config)
        _ensure_config_exists(config_path)
        collection = extract_quantitative_parameter_candidates(
            run_dir=_resolve_cli_path(args.run_dir),
            quantitative_idea_id=args.idea_id,
            version=args.version,
            document_id=args.document_id,
            llm_call=build_quantitative_model_llm_call(
                config=load_config(str(config_path)), model=args.model
            ),
            maximum_characters=args.max_document_chars,
        )
    except (OSError, ValueError) as exc:
        print(f"quantitative parameter extraction input error: {exc}", file=sys.stderr)
        return QUANTITATIVE_EXIT_INPUT_ERROR
    except Exception as exc:
        print(f"quantitative parameter extraction error: {exc}", file=sys.stderr)
        return QUANTITATIVE_EXIT_MODEL_ERROR
    _print_quantitative_result({"status": "CANDIDATES_EXTRACTED", "collection": str(collection)})
    return QUANTITATIVE_EXIT_SUCCESS


def _quantitative_parameter_propose_command(args: argparse.Namespace) -> int:
    try:
        from src.pipeline.quantitative_workflow import propose_quantitative_parameter_resolution

        selections = _quantitative_json_option(args.selections_json, label="--selections-json")
        if not isinstance(selections, list):
            raise ValueError("--selections-json must be a JSON list")
        proposal = propose_quantitative_parameter_resolution(
            run_dir=_resolve_cli_path(args.run_dir),
            quantitative_idea_id=args.idea_id,
            version=args.version,
            selections=selections,
        )
    except (OSError, ValueError) as exc:
        print(f"quantitative parameter proposal input error: {exc}", file=sys.stderr)
        return QUANTITATIVE_EXIT_INPUT_ERROR
    except Exception as exc:
        print(f"quantitative parameter proposal error: {exc}", file=sys.stderr)
        return QUANTITATIVE_EXIT_EXECUTION_ERROR
    _print_quantitative_result({"status": "REVIEW_REQUIRED", "proposal": str(proposal)})
    return QUANTITATIVE_EXIT_SUCCESS


def _quantitative_parameter_approve_command(args: argparse.Namespace) -> int:
    try:
        from src.pipeline.quantitative_workflow import approve_quantitative_parameter_resolution

        paths = approve_quantitative_parameter_resolution(
            run_dir=_resolve_cli_path(args.run_dir),
            quantitative_idea_id=args.idea_id,
            version=args.version,
            approve=bool(args.approve),
        )
    except (OSError, ValueError) as exc:
        print(f"quantitative parameter approval input error: {exc}", file=sys.stderr)
        return QUANTITATIVE_EXIT_INPUT_ERROR
    except Exception as exc:
        print(f"quantitative parameter approval error: {exc}", file=sys.stderr)
        return QUANTITATIVE_EXIT_EXECUTION_ERROR
    _print_quantitative_result({"status": "PARAMETERS_APPROVED", **paths})
    return QUANTITATIVE_EXIT_SUCCESS


def _quantitative_materialize_command(args: argparse.Namespace) -> int:
    try:
        from src.agents.quantitative_modeling.model_synthesis import build_quantitative_model_llm_call
        from src.config import load_config
        from src.pipeline.quantitative_workflow import materialize_quantitative_model_version

        config_path = _resolve_config_path(args.config)
        _ensure_config_exists(config_path)
        paths = materialize_quantitative_model_version(
            run_dir=_resolve_cli_path(args.run_dir),
            quantitative_ideas_manifest_path=_resolve_cli_path(args.quantitative_ideas_manifest),
            quantitative_idea_id=args.idea_id,
            version=args.version,
            llm_call=build_quantitative_model_llm_call(
                config=load_config(str(config_path)), model=args.model
            ),
            scenarios=_quantitative_json_option(args.scenarios_json, label="--scenarios-json"),
            resource_limits=_quantitative_json_option(
                args.resource_limits_json, label="--resource-limits-json"
            ),
        )
    except (OSError, ValueError) as exc:
        print(f"quantitative materialization input error: {exc}", file=sys.stderr)
        return QUANTITATIVE_EXIT_INPUT_ERROR
    except Exception as exc:
        print(f"quantitative materialization error: {exc}", file=sys.stderr)
        return QUANTITATIVE_EXIT_MODEL_ERROR
    _print_quantitative_result({"status": "MODEL_AUDITED", **paths})
    return QUANTITATIVE_EXIT_SUCCESS


def _quantitative_simulate_command(args: argparse.Namespace) -> int:
    try:
        from src.pipeline.quantitative_workflow import execute_quantitative_plan

        paths = execute_quantitative_plan(
            run_dir=_resolve_cli_path(args.run_dir),
            quantitative_idea_id=args.idea_id,
            version=args.version,
            execute=bool(args.execute),
            confirmed_plan_identity=args.plan_identity,
        )
    except (OSError, ValueError) as exc:
        print(f"quantitative simulation input error: {exc}", file=sys.stderr)
        return QUANTITATIVE_EXIT_INPUT_ERROR
    except Exception as exc:
        print(f"quantitative simulation error: {exc}", file=sys.stderr)
        return QUANTITATIVE_EXIT_EXECUTION_ERROR
    _print_quantitative_result({"status": "COMPLETED", **paths})
    return QUANTITATIVE_EXIT_SUCCESS


def _quantitative_qualify_command(args: argparse.Namespace) -> int:
    try:
        from src.pipeline.quantitative_workflow import qualify_quantitative_execution

        paths = qualify_quantitative_execution(
            run_dir=_resolve_cli_path(args.run_dir),
            quantitative_idea_id=args.idea_id,
            version=args.version,
            execution_id=args.execution_id,
            hypothesis_relation=args.hypothesis_relation,
            result_summary=args.result_summary,
        )
    except (OSError, ValueError) as exc:
        print(f"quantitative qualification input error: {exc}", file=sys.stderr)
        return QUANTITATIVE_EXIT_INPUT_ERROR
    except Exception as exc:
        print(f"quantitative qualification error: {exc}", file=sys.stderr)
        return QUANTITATIVE_EXIT_EXECUTION_ERROR
    _print_quantitative_result({"status": "COMPLETED", **paths})
    return QUANTITATIVE_EXIT_SUCCESS


def _quantitative_propose_refinement_command(args: argparse.Namespace) -> int:
    try:
        from src.pipeline.quantitative_workflow import propose_quantitative_refinement

        model_delta = _quantitative_json_option(args.model_delta_json, label="--model-delta-json")
        parameter_delta = _quantitative_json_option(
            args.parameter_or_boundary_delta_json,
            label="--parameter-or-boundary-delta-json",
        )
        if not isinstance(model_delta, list) or not isinstance(parameter_delta, list):
            raise ValueError("refinement delta options must be JSON lists")
        proposal = propose_quantitative_refinement(
            run_dir=_resolve_cli_path(args.run_dir),
            quantitative_idea_id=args.idea_id,
            version=args.version,
            revision_reason=args.revision_reason,
            hypothesis_delta=args.hypothesis_delta,
            model_delta=model_delta,
            parameter_or_boundary_delta=parameter_delta,
            expected_discriminating_result=args.expected_discriminating_result,
            falsification_condition=args.falsification_condition,
        )
    except (OSError, ValueError) as exc:
        print(f"quantitative refinement input error: {exc}", file=sys.stderr)
        return QUANTITATIVE_EXIT_INPUT_ERROR
    except Exception as exc:
        print(f"quantitative refinement error: {exc}", file=sys.stderr)
        return QUANTITATIVE_EXIT_EXECUTION_ERROR
    _print_quantitative_result({"status": "PROPOSED", "proposal": str(proposal)})
    return QUANTITATIVE_EXIT_SUCCESS


def _quantitative_accept_revision_command(args: argparse.Namespace) -> int:
    try:
        from src.pipeline.quantitative_workflow import accept_quantitative_refinement

        acceptance = accept_quantitative_refinement(
            run_dir=_resolve_cli_path(args.run_dir),
            quantitative_idea_id=args.idea_id,
            parent_version=args.parent_version,
            accept=bool(args.accept),
        )
    except (OSError, ValueError) as exc:
        print(f"quantitative revision input error: {exc}", file=sys.stderr)
        return QUANTITATIVE_EXIT_INPUT_ERROR
    except Exception as exc:
        print(f"quantitative revision error: {exc}", file=sys.stderr)
        return QUANTITATIVE_EXIT_EXECUTION_ERROR
    _print_quantitative_result({"status": "ACCEPTED", "acceptance": str(acceptance)})
    return QUANTITATIVE_EXIT_SUCCESS


def _quantitative_feedback_packet_command(args: argparse.Namespace) -> int:
    try:
        from src.pipeline.quantitative_workflow import build_main_hypothesis_feedback_packet

        packet = build_main_hypothesis_feedback_packet(run_dir=_resolve_cli_path(args.run_dir))
    except (OSError, ValueError) as exc:
        print(f"quantitative feedback input error: {exc}", file=sys.stderr)
        return QUANTITATIVE_EXIT_INPUT_ERROR
    except Exception as exc:
        print(f"quantitative feedback error: {exc}", file=sys.stderr)
        return QUANTITATIVE_EXIT_EXECUTION_ERROR
    _print_quantitative_result({"status": "COMPLETED", "feedback_packet": str(packet)})
    return QUANTITATIVE_EXIT_SUCCESS


def _quantitative_finalize_command(args: argparse.Namespace) -> int:
    try:
        from src.agents.quantitative_modeling.author_handoff import finalize_quantitative_idea

        finalization = finalize_quantitative_idea(
            run_dir=_resolve_cli_path(args.run_dir),
            quantitative_idea_id=args.idea_id,
            version=args.version,
        )
    except (OSError, ValueError) as exc:
        print(f"quantitative finalization input error: {exc}", file=sys.stderr)
        return QUANTITATIVE_EXIT_INPUT_ERROR
    except Exception as exc:
        print(f"quantitative finalization error: {exc}", file=sys.stderr)
        return QUANTITATIVE_EXIT_EXECUTION_ERROR
    _print_quantitative_result({"status": "FINALIZED", "finalization": str(finalization)})
    return QUANTITATIVE_EXIT_SUCCESS


def _quantitative_publish_command(args: argparse.Namespace) -> int:
    try:
        from src.agents.quantitative_modeling.publisher.run import publish_quantitative_models_pdf

        artifacts = publish_quantitative_models_pdf(
            run_dir=_resolve_cli_path(args.run_dir),
            latex_engine=_science_executable_option(args.latex_engine),
            pdf_renderer=_science_executable_option(args.pdf_renderer),
            timeout_seconds=args.timeout_seconds,
        )
    except (OSError, ValueError) as exc:
        print(f"quantitative publication input error: {exc}", file=sys.stderr)
        return QUANTITATIVE_EXIT_INPUT_ERROR
    except Exception as exc:
        print(f"quantitative publication error: {exc}", file=sys.stderr)
        return QUANTITATIVE_EXIT_EXECUTION_ERROR
    _print_quantitative_result({"status": "PUBLISHED", **artifacts})
    return QUANTITATIVE_EXIT_SUCCESS


def _quantitative_author_handoff_command(args: argparse.Namespace) -> int:
    try:
        from src.agents.quantitative_modeling.author_handoff import build_quantitative_author_handoff

        run_dir = _resolve_cli_path(args.run_dir)
        models_pdf = (
            _resolve_cli_path(args.quantitative_models_pdf)
            if args.quantitative_models_pdf
            else run_dir / "quantitative" / "publication" / "quantitative_mathematical_models.pdf"
        )
        handoff, manifest = build_quantitative_author_handoff(
            run_dir=run_dir,
            quantitative_models_pdf_path=models_pdf,
        )
    except (OSError, ValueError) as exc:
        print(f"quantitative Author handoff input error: {exc}", file=sys.stderr)
        return QUANTITATIVE_EXIT_INPUT_ERROR
    except Exception as exc:
        print(f"quantitative Author handoff error: {exc}", file=sys.stderr)
        return QUANTITATIVE_EXIT_EXECUTION_ERROR
    _print_quantitative_result({"status": "COMPLETED", "handoff": str(handoff), "manifest": str(manifest)})
    return QUANTITATIVE_EXIT_SUCCESS


def _quantitative_bundle_command(args: argparse.Namespace) -> int:
    try:
        from src.agents.quantitative_modeling.publication_bundle import build_publication_bundle

        manifest = build_publication_bundle(
            run_dir=_resolve_cli_path(args.run_dir),
            main_article_pdf=_resolve_cli_path(args.main_article_pdf),
            quantitative_author_handoff_manifest=_resolve_cli_path(
                args.quantitative_author_handoff_manifest
            ),
        )
    except (OSError, ValueError) as exc:
        print(f"quantitative bundle input error: {exc}", file=sys.stderr)
        return QUANTITATIVE_EXIT_INPUT_ERROR
    except Exception as exc:
        print(f"quantitative bundle error: {exc}", file=sys.stderr)
        return QUANTITATIVE_EXIT_EXECUTION_ERROR
    _print_quantitative_result({"status": "COMPLETED", "bundle_manifest": str(manifest)})
    return QUANTITATIVE_EXIT_SUCCESS


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


def doctor_main() -> int:
    return main(["doctor", *sys.argv[1:]])


def install_mcp_wrappers_main() -> int:
    return main(["install-mcp-wrappers", *sys.argv[1:]])


if __name__ == "__main__":
    raise SystemExit(main())
