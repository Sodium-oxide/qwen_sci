"""Bounded execution of server-owned plotting templates."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from .feature_service_base import FeatureJobError


def execution_prelude(*, cpu_seconds: int, memory_bytes: int, output_bytes: int) -> str:
    return f'''import sys
def restrict_execution(event, arguments):
    if event.startswith("socket.") or event in {{"subprocess.Popen", "os.system", "os.fork", "os.posix_spawn"}}:
        raise PermissionError("Network access and child processes are disabled in the figure renderer.")
sys.addaudithook(restrict_execution)
try:
    import resource
except ImportError:
    resource = None
if resource is not None:
    resource.setrlimit(resource.RLIMIT_CPU, ({cpu_seconds}, {cpu_seconds}))
    resource.setrlimit(resource.RLIMIT_AS, ({memory_bytes}, {memory_bytes}))
    resource.setrlimit(resource.RLIMIT_FSIZE, ({output_bytes}, {output_bytes}))
    resource.setrlimit(resource.RLIMIT_NOFILE, (128, 128))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
'''


def run_figure_template(context, directory: Path, *, timeout: float) -> None:
    environment = {
        "MPLBACKEND": "Agg", "MPLCONFIGDIR": str(directory / "mplconfig"),
        "PYTHONNOUSERSITE": "1", "PATH": os.defpath,
        "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1",
        "NUMEXPR_NUM_THREADS": "1", "VECLIB_MAXIMUM_THREADS": "1",
    }
    (directory / "mplconfig").mkdir(exist_ok=True)
    with (directory / "stdout.log").open("wb") as stdout, (directory / "stderr.log").open("wb") as stderr:
        process = subprocess.Popen(
            [sys.executable, "-I", "figure.py"], cwd=directory, env=environment, stdout=stdout, stderr=stderr,
        )
        import time

        deadline = time.monotonic() + context.remaining_seconds(timeout)
        try:
            while process.poll() is None:
                context.check_cancelled()
                if time.monotonic() >= deadline:
                    raise FeatureJobError("Figure rendering timed out.")
                try:
                    process.wait(timeout=0.2)
                except subprocess.TimeoutExpired:
                    continue
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=10)
    if process.returncode != 0:
        error = (directory / "stderr.log").read_text(encoding="utf-8", errors="replace")[-800:]
        raise FeatureJobError("Figure rendering failed: " + error)
