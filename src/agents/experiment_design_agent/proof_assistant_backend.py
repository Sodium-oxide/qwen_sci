"""Optional Lean proof-assistant adapter.

The adapter is opt-in and only treats Lean's successful process exit as a
kernel-checked result.  Missing executables, malformed source, and timeouts are
reported as unsupported or unknown; none are promoted to a proof.
"""

from __future__ import annotations

import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from typing import Any, Mapping


LEAN_BACKEND_VERSION = "lean-adapter-v1"
_THEOREM_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_']*$")


def lean_executable(configured: str | None = None) -> str | None:
    candidate = str(configured or "lean").strip()
    if not candidate or any(character in candidate for character in "\r\n\x00"):
        return None
    return shutil.which(candidate)


def build_lean_source(task: Mapping[str, Any]) -> str:
    theorem_name = str(task.get("theorem_name") or "formal_target")
    theorem_statement = str(task.get("theorem_statement") or "").strip()
    proof_script = str(task.get("proof_script") or "").strip()
    imports = str(task.get("lean_imports") or "Mathlib").strip()
    if not _THEOREM_NAME.fullmatch(theorem_name):
        raise ValueError("invalid_lean_theorem_name")
    if not theorem_statement or not proof_script:
        raise ValueError("missing_lean_theorem_or_proof")
    if any("\x00" in item or len(item) > 120000 for item in (imports, theorem_statement, proof_script)):
        raise ValueError("lean_source_too_large_or_invalid")
    return f"import {imports}\n\ntheorem {theorem_name} : {theorem_statement} := by\n  {proof_script.replace(chr(10), chr(10) + '  ')}\n"


def run_lean_task(task: Mapping[str, Any]) -> dict[str, Any]:
    if task.get("proof_assistant_enabled") is not True:
        return {
            "result": "unsupported",
            "proof_assistant_status": "proof_assistant_unsupported",
            "limitations": ["Lean backend is disabled; set proof_assistant.enabled=true to opt in."],
            "backend_version": LEAN_BACKEND_VERSION,
            "verification_level": "kernel_verified",
            "verification_method": "lean_kernel",
            "certificate": False,
            "coverage": {"available": False, "disabled": True},
        }
    executable = lean_executable(task.get("executable"))
    if executable is None:
        return {
            "result": "unsupported",
            "proof_assistant_status": "proof_assistant_unsupported",
            "limitations": ["Lean executable is not installed or not configured."],
            "backend_version": LEAN_BACKEND_VERSION,
            "verification_level": "kernel_verified",
            "verification_method": "lean_kernel",
            "certificate": False,
            "coverage": {"available": False},
        }
    try:
        source = build_lean_source(task)
    except (TypeError, ValueError) as error:
        return {
            "result": "unsupported",
            "proof_assistant_status": "proof_assistant_unsupported",
            "limitations": [str(error)],
            "backend_version": LEAN_BACKEND_VERSION,
            "verification_level": "kernel_verified",
            "verification_method": "lean_kernel",
            "certificate": False,
            "coverage": {"available": True, "source": "invalid"},
        }
    timeout = max(0.01, float(task.get("timeout_seconds", 60)))
    with tempfile.TemporaryDirectory(prefix="formal-lean-") as directory:
        source_path = Path(directory) / "FormalTarget.lean"
        source_path.write_text(source, encoding="utf-8")
        environment = os.environ.copy()
        environment.pop("PYTHONPATH", None)
        try:
            process = subprocess.run(
                [executable, str(source_path)],
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=directory,
                env=environment,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except subprocess.TimeoutExpired:
            return {
                "result": "timeout",
                "proof_assistant_status": "proof_assistant_timeout",
                "limitations": ["Lean exceeded the wall-clock limit."],
                "backend_version": LEAN_BACKEND_VERSION,
                "verification_level": "kernel_verified",
                "verification_method": "lean_kernel",
                "certificate": False,
                "coverage": {"available": True, "timeout": True},
            }
        if process.returncode == 0:
            return {
                "result": "passed",
                "proof_assistant_status": "proof_assistant_verified",
                "evidence_kind": "lean_kernel_checked",
                "backend_version": LEAN_BACKEND_VERSION,
                "verification_level": "kernel_verified",
                "verification_method": "lean_kernel",
                "certificate": True,
                "certificate_ref": "generated:FormalTarget.lean",
                "certificate_source": source,
                "limitations": ["Lean checked the generated theorem in the configured environment."],
                "coverage": {"available": True, "kernel_checked": True},
            }
        diagnostics = (process.stderr or process.stdout or "Lean rejected the theorem.").strip()
        return {
            "result": "failed",
            "proof_assistant_status": "proof_assistant_failed",
            "evidence_kind": "lean_kernel_rejected",
            "backend_version": LEAN_BACKEND_VERSION,
            "verification_level": "kernel_verified",
            "verification_method": "lean_kernel",
            "certificate": False,
            "diagnostics": diagnostics[:4000],
            "limitations": ["Lean rejected the generated theorem or proof script."],
            "coverage": {"available": True, "kernel_checked": True},
        }


__all__ = ["LEAN_BACKEND_VERSION", "build_lean_source", "lean_executable", "run_lean_task"]
