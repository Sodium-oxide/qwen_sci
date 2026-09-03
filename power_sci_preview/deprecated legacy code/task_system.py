from __future__ import annotations

import json
import random
import re
import shutil
import subprocess
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

try:
    from .config import BACKGROUND_ENABLED, BACKGROUND_MAX_OUTPUT_CHARS, TASKS_DIR
    from .log import log_event
except ImportError:
    from config import BACKGROUND_ENABLED, BACKGROUND_MAX_OUTPUT_CHARS, TASKS_DIR
    from log import log_event


TASK_STATUSES = {"pending", "in_progress", "completed"}
RETIRED_TASK_SUBJECT_PREFIXES = ("Boxue/",)
DELIVERY_MAX_BYTES = 2_000_000
DELIVERY_IGNORED_PARTS = {
    ".git",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "__pycache__",
    "node_modules",
    "tool_results",
    "transcripts",
}
DELIVERY_IGNORED_PREFIXES = {
    "v8/.memory",
    "v8/.team",
    "v8/.tasks",
    
}
SLOW_KEYWORDS = [
    "install",
    "build",
    "deploy",
    "docker build",
    "pip install",
    "npm install",
    "pnpm install",
    "yarn install",
    "cargo build",
    "cargo test",
    "mvn test",
    "gradle build",
    "make",
]
FOREGROUND_VALIDATION_MARKERS = (
    "pytest",
    "python -m pytest",
    "py_compile",
    "python -m py_compile",
)
PY_PATH_RE = re.compile(r"(?<![\w.-])(?:[\w.-]+[\\/])*[\w.-]+\.py")
TEST_INTENT_MARKERS = ("pytest", "test", "tests", "测试", "測試", "娴嬭瘯")
TASK_VALIDATION_TIMEOUT_SECONDS = 60

background_lock = threading.Lock()
task_lock = threading.Lock()
background_tasks: dict[str, dict[str, Any]] = {}
background_results: dict[str, dict[str, Any]] = {}


@dataclass
class Task:
    id: str
    subject: str
    description: str
    status: str = "pending"
    owner: str | None = None
    blockedBy: list[str] = field(default_factory=list)
    createdAt: float = field(default_factory=time.time)
    updatedAt: float = field(default_factory=time.time)


def ensure_tasks_dir() -> None:
    TASKS_DIR.mkdir(parents=True, exist_ok=True)


def create_task(subject: str, description: str, blockedBy: list[str] | None = None) -> str:
    ensure_tasks_dir()
    task = Task(
        id=new_task_id(),
        subject=subject,
        description=description,
        blockedBy=list(blockedBy or []),
    )
    if would_create_cycle(task.id, task.blockedBy):
        raise ValueError("Task dependencies would create a cycle.")
    save_task(task)
    log_event("TASK", "created", id=task.id, subject=subject, blocked=len(task.blockedBy))
    return render_task(task)


def list_tasks(include_completed: bool = True) -> str:
    tasks = load_tasks()
    if not include_completed:
        tasks = [task for task in tasks if task.status != "completed"]
    if not tasks:
        return "(no tasks)"
    return "\n".join(render_task_line(task) for task in sorted(tasks, key=lambda item: item.createdAt))


def get_task(task_id: str) -> str:
    return render_task(load_task(task_id))


def claim_task(task_id: str, owner: str = "main") -> str:
    with task_lock:
        task = load_task(task_id)
        if is_retired_task(task):
            raise ValueError(f"Task {task_id} belongs to the retired Boxue task-DAG workflow.")
        if task.status != "pending":
            raise ValueError(f"Task {task_id} is not pending.")
        if task.owner:
            raise ValueError(f"Task {task_id} is already owned by {task.owner}.")
        if not can_start(task):
            missing = incomplete_dependencies(task)
            raise ValueError(f"Task {task_id} is blocked by: {', '.join(missing)}")
        task.status = "in_progress"
        task.owner = owner
        task.updatedAt = time.time()
        save_task(task)
    log_event("TASK", "claimed", id=task.id, owner=owner)
    return render_task(task)


def complete_task(task_id: str) -> str:
    task = load_task(task_id)
    if is_retired_task(task):
        raise ValueError(f"Task {task_id} belongs to the retired Boxue task-DAG workflow.")
    validation_issue = validate_task_completion(task)
    if validation_issue:
        log_event("TASK", "completion_blocked", id=task.id)
        raise ValueError(f"Task {task.id} is not ready to complete:\n{validation_issue}")

    with task_lock:
        task = load_task(task_id)
        task.status = "completed"
        task.updatedAt = time.time()
        save_task(task)

    deliverable_targets = [
        candidate
        for candidate in load_tasks()
        if candidate.status == "pending" and task.id in candidate.blockedBy and can_start(candidate)
    ]
    deliveries = deliver_outputs_to_dependents(task, deliverable_targets)
    unlocked = [candidate.id for candidate in load_tasks() if candidate.status == "pending" and can_start(candidate)]
    log_event("TASK", "completed", id=task.id, unlocked=len(unlocked), deliveries=len(deliveries))
    delivery_text = render_deliveries(deliveries)
    if unlocked:
        result = f"{render_task(task)}\n\nUnlocked tasks: {', '.join(unlocked)}"
    else:
        result = render_task(task)
    if delivery_text:
        result += f"\n\nDelivered outputs:\n{delivery_text}"
    return result


def deliver_outputs_to_dependents(source_task: Task, targets: list[Task]) -> list[dict[str, Any]]:
    # Worktree-based delivery removed; tasks share the same workspace.
    return []


def changed_output_paths(root: Path, *, since: float) -> list[str]:
    git_paths = changed_paths_from_git(root)
    if git_paths:
        return git_paths
    return changed_paths_from_mtime(root, since=since)


def changed_paths_from_git(root: Path) -> list[str]:
    completed = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        cwd=root,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
    )
    if completed.returncode != 0:
        log_event("WARN", "delivery_git_status_failed", root=root, detail=(completed.stderr or completed.stdout).strip())
        return []

    paths: list[str] = []
    for raw_line in completed.stdout.splitlines():
        if len(raw_line) < 4:
            continue
        status = raw_line[:2]
        raw_path = raw_line[3:].strip().strip('"')
        if " -> " in raw_path:
            raw_path = raw_path.split(" -> ", 1)[1].strip().strip('"')
        if "D" in status:
            continue
        normalized = normalize_rel(raw_path)
        if normalized and is_deliverable_path(normalized, root / normalized):
            paths.append(normalized)
    return sorted(set(paths))


def changed_paths_from_mtime(root: Path, *, since: float) -> list[str]:
    paths: list[str] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        try:
            rel = normalize_rel(str(path.relative_to(root)))
        except ValueError:
            continue
        if not rel or not is_deliverable_path(rel, path):
            continue
        try:
            if path.stat().st_mtime >= since:
                paths.append(rel)
        except OSError:
            continue
    return sorted(set(paths))


def copy_relative_outputs(source_root: Path, target_root: Path, rel_paths: list[str]) -> list[str]:
    copied: list[str] = []
    source_root = source_root.resolve()
    target_root = target_root.resolve()
    for rel in rel_paths:
        source = (source_root / rel).resolve()
        target = (target_root / rel).resolve()
        if not source.exists() or not source.is_file():
            continue
        if not source.is_relative_to(source_root) or not target.is_relative_to(target_root):
            continue
        if not is_deliverable_path(rel, source):
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        copied.append(rel)
    return copied


def is_deliverable_path(rel_path: str, path: Path) -> bool:
    normalized = normalize_rel(rel_path)
    parts = set(Path(normalized).parts)
    if parts & DELIVERY_IGNORED_PARTS:
        return False
    if any(normalized == prefix or normalized.startswith(prefix + "/") for prefix in DELIVERY_IGNORED_PREFIXES):
        return False
    try:
        if path.exists() and path.stat().st_size > DELIVERY_MAX_BYTES:
            return False
    except OSError:
        return False
    return True


def normalize_rel(path: str) -> str:
    normalized = str(path).strip().replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    if not normalized or normalized.startswith("../") or "/../" in normalized:
        return ""
    return normalized


def render_deliveries(deliveries: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for delivery in deliveries:
        files = delivery.get("files")
        if isinstance(files, list):
            file_text = ", ".join(str(file) for file in files) or "(no files)"
            lines.append(
                f"- {delivery.get('target')} -> {delivery.get('target')}: "
                f"{delivery.get('status')} {file_text}"
            )
        else:
            lines.append(f"- {delivery.get('target')}: {delivery.get('status')} ({delivery.get('reason')})")
    return "\n".join(lines)


def validate_task_completion(task: Task) -> str:
    task_text = f"{task.subject}\n{task.description}"
    expected_paths = expected_task_python_paths(task_text)
    if not expected_paths:
        return ""

    issues: list[str] = []
    root = Path(WORKDIR)
    existing_files: dict[str, Path] = {}
    for rel_path in sorted(expected_paths):
        found = find_task_file(root, rel_path)
        if found is None:
            issues.append(f"- Expected file is missing: {rel_path}")
        else:
            existing_files[rel_path] = found

    for rel_path, file_path in sorted(existing_files.items()):
        if Path(rel_path).name.startswith("test_"):
            continue
        compile_issue = run_py_compile(file_path)
        if compile_issue:
            issues.append(compile_issue)

    if has_test_intent(task_text):
        test_paths = [
            (rel_path, file_path)
            for rel_path, file_path in sorted(existing_files.items())
            if Path(rel_path).name.startswith("test_")
        ]
        if not test_paths:
            issues.append("- Task asks for tests, but no test_*.py deliverable was found.")
        for rel_path, file_path in test_paths:
            pytest_issue = run_task_pytest(file_path)
            if pytest_issue:
                issues.append(f"- Tests failed for {rel_path}: {pytest_issue}")

    return "\n".join(issues)


def expected_task_python_paths(text: str) -> set[str]:
    raw_paths = {normalize_rel(match.group(0)) for match in PY_PATH_RE.finditer(str(text))}
    paths = {path for path in raw_paths if path}
    dirs = [str(Path(path).parent).replace("\\", "/") for path in paths if "/" in path]
    default_dir = dirs[0] if dirs else ""

    for path in list(paths):
        if "/" not in path and default_dir:
            paths.add(f"{default_dir}/{path}")

    if has_test_intent(text):
        for path in list(paths):
            parsed = Path(path)
            if parsed.suffix == ".py" and not parsed.name.startswith("test_"):
                parent = "" if str(parsed.parent) == "." else str(parsed.parent).replace("\\", "/")
                test_name = f"test_{parsed.name}"
                paths.add(f"{parent}/{test_name}" if parent else test_name)

    return paths


def has_test_intent(text: str) -> bool:
    lowered = str(text).lower()
    return any(marker in lowered for marker in TEST_INTENT_MARKERS)


def find_task_file(root: Path, rel_path: str) -> Path | None:
    normalized = normalize_rel(rel_path)
    if not normalized:
        return None
    root = root.resolve()
    candidate = (root / normalized).resolve()
    try:
        if candidate.is_relative_to(root) and candidate.exists() and candidate.is_file():
            return candidate
    except ValueError:
        return None
    return None


def run_py_compile(file_path: Path) -> str:
    completed = subprocess.run(
        ["python", "-m", "py_compile", file_path.name],
        cwd=file_path.parent,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=TASK_VALIDATION_TIMEOUT_SECONDS,
    )
    if completed.returncode == 0:
        return ""
    return f"- Python compile failed for {file_path}: {summarize_process_output(completed)}"


def run_task_pytest(test_file: Path) -> str:
    completed = subprocess.run(
        ["python", "-m", "pytest", test_file.name, "-q"],
        cwd=test_file.parent,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=TASK_VALIDATION_TIMEOUT_SECONDS,
    )
    if completed.returncode == 0:
        return ""
    return summarize_process_output(completed)


def summarize_process_output(completed: subprocess.CompletedProcess[str]) -> str:
    output = ((completed.stdout or "") + (completed.stderr or "")).strip().replace("\n", "\\n")
    if not output:
        output = f"exit_code={completed.returncode}"
    if len(output) > 1500:
        output = output[:1500] + "...[truncated]"
    return output


def load_tasks() -> list[Task]:
    ensure_tasks_dir()
    tasks: list[Task] = []
    for path in sorted(TASKS_DIR.glob("task_*.json")):
        try:
            task = task_from_dict(json.loads(path.read_text(encoding="utf-8")))
            if is_retired_task(task):
                continue
            tasks.append(task)
        except Exception as exc:
            log_event("WARN", "task_load_failed", path=path, error=exc)
    return tasks


def scan_unclaimed_tasks(owner: str = "", limit: int = 5, allowed_ids: set[str] | None = None) -> list[Task]:
    allowed = set(allowed_ids or [])
    candidates = [
        task
        for task in load_tasks()
        if task.status == "pending"
        and not task.owner
        and can_start(task)
        and (not allowed or task.id in allowed)
    ]
    candidates.sort(key=lambda item: item.createdAt)
    selected = candidates[: max(0, limit)]
    log_event("TASK", "scan_unclaimed", owner=owner, found=len(selected), scoped=bool(allowed))
    return selected


def load_task(task_id: str) -> Task:
    path = task_path(task_id)
    if not path.exists():
        raise ValueError(f"Task not found: {task_id}")
    return task_from_dict(json.loads(path.read_text(encoding="utf-8")))


def save_task(task: Task) -> None:
    ensure_tasks_dir()
    task.updatedAt = time.time()
    task_path(task.id).write_text(json.dumps(asdict(task), ensure_ascii=False, indent=2), encoding="utf-8")


def can_start(task: Task) -> bool:
    return not is_retired_task(task) and not incomplete_dependencies(task)


def is_retired_task(task: Task) -> bool:
    subject = str(task.subject or "")
    return any(subject.startswith(prefix) for prefix in RETIRED_TASK_SUBJECT_PREFIXES)


def incomplete_dependencies(task: Task) -> list[str]:
    tasks = {item.id: item for item in load_tasks()}
    missing: list[str] = []
    for dep_id in task.blockedBy:
        dependency = tasks.get(dep_id)
        if dependency is None or dependency.status != "completed":
            missing.append(dep_id)
    return missing


def would_create_cycle(new_id: str, dependencies: list[str]) -> bool:
    graph = {task.id: task.blockedBy for task in load_tasks()}
    graph[new_id] = dependencies
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node: str) -> bool:
        if node in visiting:
            return True
        if node in visited:
            return False
        visiting.add(node)
        for dep in graph.get(node, []):
            if visit(dep):
                return True
        visiting.remove(node)
        visited.add(node)
        return False

    return visit(new_id)


def should_run_background(block: Any) -> bool:
    if not BACKGROUND_ENABLED:
        return False
    name = block_attr(block, "name", "")
    normalized_name = str(name).replace("-", "_").replace(" ", "_").lower()
    tool_input = block_attr(block, "input", {}) or {}
    if bool(tool_input.get("run_in_background")) and normalized_name in {"bash", "task", "spawn_subagent", "spawnsubagent"}:
        return True
    if normalized_name == "bash":
        command = str(tool_input.get("command", "")).lower()
        if is_foreground_validation_command(command):
            return False
        return any(keyword in command for keyword in SLOW_KEYWORDS)
    if normalized_name in {"task", "spawn_subagent", "spawnsubagent", "agent"}:
        description = str(tool_input.get("description", "")).lower()
        return any(keyword in description for keyword in ("analyze", "investigate", "refactor", "review"))
    return False


def is_foreground_validation_command(command: str) -> bool:
    normalized = " ".join(str(command).lower().split())
    return any(marker in normalized for marker in FOREGROUND_VALIDATION_MARKERS)


def start_background_task(
    block: Any,
    handler: Callable[..., str],
    tool_input: dict[str, Any],
) -> str:
    task_id = new_background_id()
    name = str(block_attr(block, "name", "<unknown>"))
    summary = summarize_invocation(name, tool_input)
    with background_lock:
        background_tasks[task_id] = {
            "id": task_id,
            "name": name,
            "summary": summary,
            "status": "running",
            "startedAt": time.time(),
        }

    thread = threading.Thread(
        target=run_background_task,
        args=(task_id, handler, dict(tool_input)),
        daemon=True,
    )
    thread.start()
    log_event("BACKGROUND", "started", id=task_id, name=name, summary=summary)
    return f"[Background task {task_id} started] {summary}"


def run_background_task(task_id: str, handler: Callable[..., str], tool_input: dict[str, Any]) -> None:
    try:
        output = handler(**strip_control_args(tool_input))
        status = "completed"
        is_error = False
    except Exception as exc:
        output = f"ERROR: {exc}"
        status = "failed"
        is_error = True
    output = truncate(output, BACKGROUND_MAX_OUTPUT_CHARS)
    with background_lock:
        task = background_tasks.get(task_id, {})
        task["status"] = status
        task["completedAt"] = time.time()
        background_tasks[task_id] = task
        background_results[task_id] = {
            "id": task_id,
            "status": status,
            "summary": task.get("summary", ""),
            "output": output,
            "is_error": is_error,
        }
    log_event("BACKGROUND", status, id=task_id, chars=len(output))


def collect_background_notifications() -> list[str]:
    with background_lock:
        results = list(background_results.values())
        background_results.clear()
    return [render_background_notification(result) for result in results]


def render_background_notification(result: dict[str, Any]) -> str:
    return (
        "<task_notification>\n"
        f"  <task_id>{result['id']}</task_id>\n"
        f"  <status>{result['status']}</status>\n"
        f"  <summary>{escape_xml(str(result.get('summary', '')))}</summary>\n"
        f"  <output>{escape_xml(str(result.get('output', '')))}</output>\n"
        "</task_notification>"
    )


def strip_control_args(tool_input: dict[str, Any]) -> dict[str, Any]:
    control_keys = {
        "run_in_background",
        "allow_ad_hoc_discovery",
        "ad_hoc_reason",
    }
    return {key: value for key, value in tool_input.items() if key not in control_keys}


def task_path(task_id: str) -> Path:
    ensure_tasks_dir()
    return TASKS_DIR / f"{task_id}.json"


def task_from_dict(data: dict[str, Any]) -> Task:
    status = data.get("status", "pending")
    if status not in TASK_STATUSES:
        status = "pending"
    return Task(
        id=str(data["id"]),
        subject=str(data.get("subject", "")),
        description=str(data.get("description", "")),
        status=status,
        owner=data.get("owner"),
        blockedBy=list(data.get("blockedBy", [])),
        createdAt=float(data.get("createdAt", time.time())),
        updatedAt=float(data.get("updatedAt", time.time())),
    )


def render_task(task: Task) -> str:
    return json.dumps(asdict(task), ensure_ascii=False, indent=2)


def render_task_line(task: Task) -> str:
    blocked = f" blockedBy={','.join(task.blockedBy)}" if task.blockedBy else ""
    owner = f" owner={task.owner}" if task.owner else ""
    return f"{task.id} [{task.status}]{owner}{blocked} - {task.subject}"


def new_task_id() -> str:
    return f"task_{int(time.time() * 1000)}_{random.randint(1000, 9999)}"


def new_background_id() -> str:
    return f"bg_{int(time.time() * 1000)}_{random.randint(1000, 9999)}"




def summarize_invocation(name: str, tool_input: dict[str, Any]) -> str:
    if "command" in tool_input:
        return str(tool_input["command"])[:300]
    if "description" in tool_input:
        return str(tool_input["description"])[:300]
    return name


def truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n...[background output truncated to {limit} chars]"


def escape_xml(value: str) -> str:
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def block_attr(block: Any, name: str, default: Any = None) -> Any:
    if isinstance(block, dict):
        return block.get(name, default)
    return getattr(block, name, default)
