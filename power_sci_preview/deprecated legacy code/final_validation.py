from __future__ import annotations

import re
import subprocess
from pathlib import Path

try:
    from .config import WORKDIR
    from .log import log_event
    from .task_system import load_task
except ImportError:
    from config import WORKDIR
    from log import log_event
    from task_system import load_task


TASK_ID_RE = re.compile(r"task_\d+_\d+")
PY_PATH_RE = re.compile(r"(?<![\w.-])(?:[\w.-]+[\\/])*[\w.-]+\.py")
TEST_INTENT_MARKERS = ("pytest", "test", "tests", "测试", "測試", "娴嬭瘯")


def extract_task_ids(text: str) -> set[str]:
    return set(TASK_ID_RE.findall(str(text)))


def validate_before_final(user_input: str, task_ids: set[str]) -> str:
    issues: list[str] = []

    for task_id in sorted(task_ids):
        try:
            task = load_task(task_id)
        except Exception as exc:
            issues.append(f"- Task {task_id} cannot be loaded: {exc}")
            continue
        if task.status != "completed":
            issues.append(
                f"- Task {task.id} is {task.status}, not completed "
                f"(owner={task.owner or 'none'})."
            )

    expected_paths = expected_python_paths(user_input)
    for rel_path in sorted(expected_paths):
        if not find_existing_path(rel_path):
            issues.append(f"- Expected file is missing in workspace: {rel_path}")

    test_paths = [path for path in sorted(expected_paths) if Path(path).name.startswith("test_")]
    for rel_path in test_paths:
        existing = find_existing_path(rel_path)
        if existing is None:
            continue
        pytest_issue = run_pytest(existing.root, existing.relative_path)
        if pytest_issue:
            issues.append(pytest_issue)

    if not issues:
        return ""

    log_event("AGENT", "pre_final_validation_failed", issues=len(issues))
    return (
        "Pre-final validation failed. You must continue instead of ending.\n"
        "Fix or explicitly complete the following before final response:\n"
        + "\n".join(issues)
    )


def expected_python_paths(user_input: str) -> set[str]:
    raw_paths = {
        normalize_rel_path(match.group(0))
        for match in PY_PATH_RE.finditer(user_input)
    }
    paths = {path for path in raw_paths if path}
    dirs = [str(Path(path).parent).replace("\\", "/") for path in paths if "/" in path]
    default_dir = dirs[0] if dirs else ""

    for path in list(paths):
        if "/" not in path and default_dir:
            paths.add(f"{default_dir}/{path}")

    if has_test_intent(user_input) and paths:
        for path in list(paths):
            p = Path(path)
            if p.suffix == ".py" and not p.name.startswith("test_"):
                parent = "" if str(p.parent) == "." else str(p.parent).replace("\\", "/")
                test_name = f"test_{p.name}"
                paths.add(f"{parent}/{test_name}" if parent else test_name)

    return paths


def has_test_intent(text: str) -> bool:
    lowered = str(text).lower()
    return any(marker in lowered for marker in TEST_INTENT_MARKERS)


class ExistingPath:
    def __init__(self, root: Path, relative_path: str, absolute_path: Path) -> None:
        self.root = root
        self.relative_path = relative_path
        self.absolute_path = absolute_path




def find_existing_path(rel_path: str, preferred_roots: list[Path] | None = None) -> ExistingPath | None:
    normalized = normalize_rel_path(rel_path)
    if not normalized:
        return None
    roots = list(preferred_roots or []) + [WORKDIR]

    seen: set[Path] = set()
    for root in roots:
        resolved_root = root.resolve()
        if resolved_root in seen:
            continue
        seen.add(resolved_root)
        candidate = (resolved_root / normalized).resolve()
        try:
            if not candidate.is_relative_to(resolved_root):
                continue
        except ValueError:
            continue
        if candidate.exists():
            return ExistingPath(resolved_root, normalized, candidate)
    return None


def run_pytest(root: Path, rel_path: str) -> str:
    completed = subprocess.run(
        ["python", "-m", "pytest", rel_path, "-q"],
        cwd=root,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=60,
    )
    output = (completed.stdout or "") + (completed.stderr or "")
    if completed.returncode == 0:
        return ""
    summary = output.strip().replace("\n", "\\n")
    if len(summary) > 1000:
        summary = summary[:1000] + "...[truncated]"
    return f"- Tests failed for {rel_path} under {root}: {summary}"


def normalize_rel_path(path: str) -> str:
    normalized = str(path).strip().replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    if not normalized or normalized.startswith("../") or "/../" in normalized:
        return ""
    return normalized
