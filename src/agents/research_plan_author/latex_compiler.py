"""Isolated, shell-free LaTeX/BibTeX compilation for Author render projects."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from time import perf_counter
from collections.abc import Mapping
from typing import Any


LATEX_COMPILE_SCHEMA_VERSION = "research_plan_author_latex_compile_v1"


class LatexCompilerError(RuntimeError):
    """Raised when a required LaTeX executable cannot be resolved safely."""


@dataclass(frozen=True)
class LatexCompileResult:
    success: bool
    report: dict[str, Any]
    log_text: str
    staged_pdf: Path | None


def _text(value: object) -> str:
    return str(value or "").strip()


def _absolute_executable_path(value: str | Path) -> Path:
    """Make an executable path absolute without dereferencing its command name.

    LaTeX distributions frequently expose ``pdflatex`` and ``xelatex`` as
    symlinks to lower-level binaries.  The invoked filename selects the TeX
    format, so resolving that symlink changes the command's behavior.
    """

    return Path(value).expanduser().absolute()


def resolve_executable(
    *,
    explicit: str | Path | None,
    environment_variable: str,
    configured: str | Path | None,
    fallback: str,
    label: str,
) -> Path:
    """Resolve one executable in declared precedence order; a supplied bad path fails."""

    candidates = (
        ("explicit", _text(explicit)),
        (f"environment:{environment_variable}", _text(os.environ.get(environment_variable))),
        ("configuration", _text(configured)),
        ("PATH", fallback),
    )
    for source, candidate in candidates:
        if not candidate:
            continue
        path = Path(candidate).expanduser()
        has_path_syntax = path.is_absolute() or any(separator in candidate for separator in ("/", "\\"))
        if has_path_syntax:
            executable_path = _absolute_executable_path(path)
            if executable_path.is_file():
                return executable_path
            if source != "PATH":
                raise LatexCompilerError(f"{label} from {source} is not an executable file: {executable_path}")
            continue
        located = shutil.which(candidate)
        if located:
            return _absolute_executable_path(located)
        if source != "PATH":
            raise LatexCompilerError(f"{label} from {source} is not available on PATH: {candidate}")
    raise LatexCompilerError(
        f"{label} is unavailable; set {environment_variable}, pass the matching CLI option, or configure it explicitly"
    )


def _safe_command(command: list[str]) -> list[str]:
    return [str(argument).replace("\n", " ").replace("\r", " ")[:2000] for argument in command]


def _run_command(command: list[str], *, cwd: Path, timeout_seconds: int) -> tuple[dict[str, Any], str]:
    started_at = perf_counter()
    safe = _safe_command(command)
    try:
        completed = subprocess.run(
            command,
            cwd=str(cwd),
            shell=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=max(1, int(timeout_seconds)),
            check=False,
        )
        output = (completed.stdout or "") + ("\n" if completed.stdout and completed.stderr else "") + (completed.stderr or "")
        return (
            {
                "command": safe,
                "return_code": completed.returncode,
                "timed_out": False,
                "elapsed_ms": round((perf_counter() - started_at) * 1000, 3),
            },
            output,
        )
    except subprocess.TimeoutExpired as error:
        stdout = error.stdout.decode("utf-8", "replace") if isinstance(error.stdout, bytes) else str(error.stdout or "")
        stderr = error.stderr.decode("utf-8", "replace") if isinstance(error.stderr, bytes) else str(error.stderr or "")
        return (
            {
                "command": safe,
                "return_code": None,
                "timed_out": True,
                "elapsed_ms": round((perf_counter() - started_at) * 1000, 3),
            },
            stdout + ("\n" if stdout and stderr else "") + stderr,
        )
    except OSError as error:
        return (
            {
                "command": safe,
                "return_code": None,
                "timed_out": False,
                "elapsed_ms": round((perf_counter() - started_at) * 1000, 3),
                "execution_error": type(error).__name__,
            },
            str(error),
        )


def compile_latex_project(
    project_dir: str | Path,
    *,
    main_tex: str | Path,
    latex_engine: str | Path,
    bibtex: str | Path | None,
    run_bibtex: bool,
    timeout_seconds: int,
    staged_pdf_path: str | Path,
    logger: Any | None = None,
) -> LatexCompileResult:
    """Compile an isolated copy and stage a PDF only after all passes succeed."""

    source_project = Path(project_dir).expanduser().resolve()
    source_main = Path(main_tex).expanduser().resolve()
    target_pdf = Path(staged_pdf_path).expanduser().resolve()
    try:
        main_relative = source_main.relative_to(source_project)
    except ValueError as error:
        raise LatexCompilerError("main TeX file must remain inside the render project") from error
    if not source_project.is_dir() or not source_main.is_file():
        raise LatexCompilerError("render project or main TeX file does not exist")
    engine_path = _absolute_executable_path(latex_engine)
    bibtex_path = _absolute_executable_path(bibtex) if bibtex else None
    if not engine_path.is_file():
        raise LatexCompilerError(f"LaTeX engine is not an executable file: {engine_path}")
    if run_bibtex and (bibtex_path is None or not bibtex_path.is_file()):
        raise LatexCompilerError("BibTeX is required by emitted references but is not an executable file")
    base_name = main_relative.stem
    commands: list[tuple[str, list[str]]] = [
        (
            "latex_initial",
            [str(engine_path), "-interaction=nonstopmode", "-halt-on-error", "-no-shell-escape", main_relative.name],
        )
    ]
    if run_bibtex:
        commands.append(("bibtex", [str(bibtex_path), base_name]))
    commands.extend(
        [
            (
                "latex_resolve_references_1",
                [str(engine_path), "-interaction=nonstopmode", "-halt-on-error", "-no-shell-escape", main_relative.name],
            ),
            (
                "latex_resolve_references_2",
                [str(engine_path), "-interaction=nonstopmode", "-halt-on-error", "-no-shell-escape", main_relative.name],
            ),
        ]
    )
    command_reports: list[dict[str, Any]] = []
    log_parts: list[str] = []
    failure_stage = ""
    with tempfile.TemporaryDirectory(prefix="research-plan-author-compile-") as temporary_root:
        workspace = Path(temporary_root) / "project"
        shutil.copytree(source_project, workspace)
        compile_cwd = workspace / main_relative.parent
        for stage, command in commands:
            if logger is not None:
                logger.emit("latex_compile", "command_started", status="RUNNING", compile_stage=stage, command=_safe_command(command))
            report, output = _run_command(command, cwd=compile_cwd, timeout_seconds=timeout_seconds)
            report["stage"] = stage
            command_reports.append(report)
            log_parts.extend(
                [
                    f"===== {stage} =====",
                    "COMMAND: " + " ".join(report["command"]),
                    output.rstrip(),
                    "",
                ]
            )
            successful = report.get("return_code") == 0 and not report.get("timed_out")
            if logger is not None:
                logger.emit(
                    "latex_compile",
                    "command_completed" if successful else "command_failed",
                    level="INFO" if successful else "ERROR",
                    status="COMPLETED" if successful else "FAILED",
                    compile_stage=stage,
                    return_code=report.get("return_code"),
                    timed_out=report.get("timed_out"),
                    elapsed_ms=report.get("elapsed_ms"),
                )
            if not successful:
                failure_stage = stage
                break
        compiled_pdf = compile_cwd / f"{base_name}.pdf"
        success = not failure_stage and compiled_pdf.is_file() and compiled_pdf.stat().st_size > 0
        if not success and not failure_stage:
            failure_stage = "pdf_missing"
            log_parts.append("Compilation commands completed but the expected PDF was not produced.\n")
        staged: Path | None = None
        if success:
            target_pdf.parent.mkdir(parents=True, exist_ok=True)
            if target_pdf.exists():
                raise LatexCompilerError(f"staged PDF target already exists: {target_pdf}")
            temporary_pdf = target_pdf.with_name(f".{target_pdf.name}.{os.getpid()}.tmp")
            shutil.copy2(compiled_pdf, temporary_pdf)
            os.replace(temporary_pdf, target_pdf)
            staged = target_pdf
    report = {
        "schema_version": LATEX_COMPILE_SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        "success": bool(success),
        "failure_stage": failure_stage,
        "project_dir": str(source_project),
        "main_tex": str(source_main),
        "run_bibtex": bool(run_bibtex),
        "timeout_seconds": int(timeout_seconds),
        "allow_shell_escape": False,
        "commands": command_reports,
        "staged_pdf": str(staged) if staged is not None else "",
    }
    return LatexCompileResult(success=bool(success), report=report, log_text="\n".join(log_parts), staged_pdf=staged)


__all__ = [
    "LATEX_COMPILE_SCHEMA_VERSION",
    "LatexCompileResult",
    "LatexCompilerError",
    "compile_latex_project",
    "resolve_executable",
]
