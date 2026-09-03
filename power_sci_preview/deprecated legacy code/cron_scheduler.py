from __future__ import annotations

import json
import random
import threading
import time
from collections import deque
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Callable

try:
    from .config import (
        CRON_ENABLED,
        CRON_MAX_JOBS,
        CRON_POLL_SECONDS,
        CRON_QUEUE_POLL_SECONDS,
        SCHEDULED_TASKS_PATH,
    )
    from .log import log_event
except ImportError:
    from config import (
        CRON_ENABLED,
        CRON_MAX_JOBS,
        CRON_POLL_SECONDS,
        CRON_QUEUE_POLL_SECONDS,
        SCHEDULED_TASKS_PATH,
    )
    from log import log_event


AgentCallback = Callable[[str], str]

cron_lock = threading.RLock()
agent_lock = threading.RLock()
cron_queue: deque["CronJob"] = deque()
scheduled_jobs: dict[str, "CronJob"] = {}
_last_fired: dict[str, str] = {}
_started = False
_agent_callback: AgentCallback | None = None


@dataclass
class CronJob:
    id: str
    cron: str
    prompt: str
    recurring: bool = True
    durable: bool = True
    createdAt: float = field(default_factory=time.time)


def start_cron_services(agent_callback: AgentCallback | None = None) -> None:
    global _started, _agent_callback
    if agent_callback is not None:
        _agent_callback = agent_callback
    if _started or not CRON_ENABLED:
        return
    load_durable_jobs()
    threading.Thread(target=cron_scheduler_loop, daemon=True).start()
    threading.Thread(target=queue_processor_loop, daemon=True).start()
    _started = True
    log_event("CRON", "started", jobs=len(scheduled_jobs))


def schedule_cron(
    cron: str,
    prompt: str,
    recurring: bool = True,
    durable: bool = True,
) -> str:
    error = validate_cron(cron)
    if error:
        return f"ERROR: {error}"
    if not prompt.strip():
        return "ERROR: prompt is required."
    with cron_lock:
        if len(scheduled_jobs) >= CRON_MAX_JOBS:
            return f"ERROR: Too many scheduled jobs (max {CRON_MAX_JOBS}). Cancel one first."
        job = CronJob(
            id=new_cron_id(),
            cron=cron.strip(),
            prompt=prompt.strip(),
            recurring=bool(recurring),
            durable=bool(durable),
        )
        scheduled_jobs[job.id] = job
        if job.durable:
            save_durable_jobs()
    start_cron_services()
    log_event("CRON", "scheduled", id=job.id, cron=job.cron, recurring=job.recurring, durable=job.durable)
    return render_job(job)


def list_crons() -> str:
    with cron_lock:
        jobs = sorted(scheduled_jobs.values(), key=lambda item: item.createdAt)
    if not jobs:
        return "(no cron jobs)"
    return "\n".join(render_job_line(job) for job in jobs)


def cancel_cron(job_id: str) -> str:
    with cron_lock:
        job = scheduled_jobs.pop(job_id, None)
        _last_fired.pop(job_id, None)
        if job and job.durable:
            save_durable_jobs()
    if not job:
        return f"Cron job not found: {job_id}"
    log_event("CRON", "cancelled", id=job.id)
    return f"Cancelled cron job {job.id}."


def cron_scheduler_loop() -> None:
    while True:
        time.sleep(CRON_POLL_SECONDS)
        now = datetime.now()
        minute_marker = now.strftime("%Y-%m-%d %H:%M")
        with cron_lock:
            jobs = list(scheduled_jobs.values())
        for job in jobs:
            try:
                if not cron_matches(job.cron, now):
                    continue
                with cron_lock:
                    if _last_fired.get(job.id) == minute_marker:
                        continue
                    cron_queue.append(job)
                    _last_fired[job.id] = minute_marker
                    log_event("CRON", "queued", id=job.id, cron=job.cron)
                    if not job.recurring:
                        scheduled_jobs.pop(job.id, None)
                        if job.durable:
                            save_durable_jobs()
            except Exception as exc:
                log_event("ERROR", "cron_job_failed", id=job.id, error=exc)


def queue_processor_loop() -> None:
    while True:
        time.sleep(CRON_QUEUE_POLL_SECONDS)
        if not has_cron_queue():
            continue
        if _agent_callback is None:
            continue
        if not agent_lock.acquire(blocking=False):
            continue
        try:
            fired = consume_cron_queue()
            if not fired:
                continue
            prompt = render_scheduled_prompt(fired)
            log_event("CRON", "deliver", count=len(fired))
            _agent_callback(prompt)
        finally:
            agent_lock.release()


def consume_cron_queue() -> list[CronJob]:
    with cron_lock:
        jobs = list(cron_queue)
        cron_queue.clear()
    return jobs


def has_cron_queue() -> bool:
    with cron_lock:
        return bool(cron_queue)


def has_cron_jobs() -> bool:
    with cron_lock:
        return bool(scheduled_jobs)


def render_scheduled_prompt(jobs: list[CronJob]) -> str:
    return "\n\n".join(f"[Scheduled] {job.prompt}" for job in jobs)


def load_durable_jobs() -> None:
    if not SCHEDULED_TASKS_PATH.exists():
        return
    try:
        data = json.loads(SCHEDULED_TASKS_PATH.read_text(encoding="utf-8"))
    except Exception as exc:
        log_event("WARN", "cron_load_failed", error=exc)
        return
    loaded = 0
    with cron_lock:
        for item in data.get("tasks", []):
            try:
                job = job_from_dict(item)
                if validate_cron(job.cron):
                    log_event("WARN", "cron_skip_invalid", id=job.id, cron=job.cron)
                    continue
                scheduled_jobs[job.id] = job
                loaded += 1
            except Exception as exc:
                log_event("WARN", "cron_skip_bad_job", error=exc)
    if loaded:
        log_event("CRON", "loaded", count=loaded)


def save_durable_jobs() -> None:
    SCHEDULED_TASKS_PATH.parent.mkdir(parents=True, exist_ok=True)
    tasks = [asdict(job) for job in scheduled_jobs.values() if job.durable]
    payload = {"tasks": tasks}
    SCHEDULED_TASKS_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def cron_matches(cron_expr: str, dt: datetime) -> bool:
    fields = cron_expr.strip().split()
    if len(fields) != 5:
        return False
    minute, hour, dom, month, dow = fields
    dow_val = (dt.weekday() + 1) % 7

    m = cron_field_matches(minute, dt.minute, 0, 59)
    h = cron_field_matches(hour, dt.hour, 0, 23)
    dom_ok = cron_field_matches(dom, dt.day, 1, 31)
    month_ok = cron_field_matches(month, dt.month, 1, 12)
    dow_ok = cron_field_matches(dow, dow_val, 0, 7, normalize_dow=True)

    if not (m and h and month_ok):
        return False
    dom_unconstrained = dom == "*"
    dow_unconstrained = dow == "*"
    if dom_unconstrained and dow_unconstrained:
        return True
    if dom_unconstrained:
        return dow_ok
    if dow_unconstrained:
        return dom_ok
    return dom_ok or dow_ok


def cron_field_matches(
    field: str,
    value: int,
    minimum: int,
    maximum: int,
    *,
    normalize_dow: bool = False,
) -> bool:
    try:
        allowed = expand_cron_field(field, minimum, maximum, normalize_dow=normalize_dow)
    except ValueError:
        return False
    compare = 0 if normalize_dow and value == 7 else value
    return compare in allowed


def expand_cron_field(
    field: str,
    minimum: int,
    maximum: int,
    *,
    normalize_dow: bool = False,
) -> set[int]:
    field = field.strip()
    if not field:
        raise ValueError("empty cron field")
    values: set[int] = set()
    for part in field.split(","):
        part = part.strip()
        if not part:
            raise ValueError("empty cron list item")
        values.update(expand_cron_part(part, minimum, maximum, normalize_dow=normalize_dow))
    return values


def expand_cron_part(
    part: str,
    minimum: int,
    maximum: int,
    *,
    normalize_dow: bool,
) -> set[int]:
    step = 1
    base = part
    if "/" in part:
        base, step_text = part.split("/", 1)
        if not step_text.isdigit():
            raise ValueError(f"invalid step: {part}")
        step = int(step_text)
        if step <= 0:
            raise ValueError(f"invalid step: {part}")

    if base == "*":
        start, end = minimum, maximum
    elif "-" in base:
        start_text, end_text = base.split("-", 1)
        start, end = parse_cron_int(start_text), parse_cron_int(end_text)
    else:
        start = end = parse_cron_int(base)

    if normalize_dow:
        if start == 7:
            start = 0
        if end == 7:
            end = 0
    if start < minimum or start > maximum or end < minimum or end > maximum:
        raise ValueError(f"value out of range: {part}")
    if start > end:
        if normalize_dow and end == 0:
            return set(range(start, maximum + 1, step)) | {0}
        raise ValueError(f"invalid range: {part}")
    return set(range(start, end + 1, step))


def parse_cron_int(text: str) -> int:
    if not text.isdigit():
        raise ValueError(f"invalid cron number: {text}")
    return int(text)


def validate_cron(cron: str) -> str | None:
    fields = cron.strip().split()
    if len(fields) != 5:
        return "cron must have five fields: minute hour day month weekday"
    ranges = [(0, 59, False), (0, 23, False), (1, 31, False), (1, 12, False), (0, 7, True)]
    for field, (minimum, maximum, normalize_dow) in zip(fields, ranges):
        try:
            expand_cron_field(field, minimum, maximum, normalize_dow=normalize_dow)
        except ValueError as exc:
            return str(exc)
    return None


def job_from_dict(data: dict[str, object]) -> CronJob:
    return CronJob(
        id=str(data["id"]),
        cron=str(data["cron"]),
        prompt=str(data["prompt"]),
        recurring=bool(data.get("recurring", True)),
        durable=bool(data.get("durable", True)),
        createdAt=float(data.get("createdAt", time.time())),
    )


def render_job(job: CronJob) -> str:
    return json.dumps(asdict(job), ensure_ascii=False, indent=2)


def render_job_line(job: CronJob) -> str:
    mode = "recurring" if job.recurring else "one-shot"
    durability = "durable" if job.durable else "session"
    return f"{job.id} [{mode}, {durability}] {job.cron} - {job.prompt}"


def new_cron_id() -> str:
    return f"cron_{int(time.time() * 1000)}_{random.randint(1000, 9999)}"
