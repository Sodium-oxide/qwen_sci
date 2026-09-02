from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

try:
    from .config import SKILLS_DIR, WORKDIR
    from .memory import render_memories
    from .mcp_plugin import connected_mcp_summary
except ImportError:
    from config import SKILLS_DIR, WORKDIR
    from memory import render_memories
    from mcp_plugin import connected_mcp_summary


@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    body: str
    path: Path


BASE_SYSTEM_PROMPT = """You are a minimal coding agent.

You can inspect and modify files in the current workspace by using tools.
Work step by step. Use tools when you need facts from the environment.
When you are done, explain the result briefly.

Use todo_write for lightweight in-session planning. Use task for one-shot
delegation to an isolated sub-agent. Use load_skill(name) to load full skill
instructions after reading the skill catalog.

For multi-step work, create persistent tasks and encode dependencies with
blockedBy. Claim a task before working on it and complete it when finished.
For slow shell commands or long analysis, set run_in_background=true so the
main loop can continue and receive a task notification later.

For work that is too broad for one context window, act as Lead. Spawn named
teammates, send them focused messages, and check the Lead inbox for results.
Use request_plan/review_plan when a teammate should wait for approval before
changing files. Use request_shutdown when a teammate should stop gracefully.
Teammates run an idle loop and wait for inbox messages instead of exiting after
a fixed number of turns.
Use the registered send_message tool for mailbox traffic. Do not invent
message tool names. Avoid blocking the Lead with long sleep commands; prefer
background execution or short inbox checks.

In v8, teammates are autonomous workers. They can scan the persistent task board,
claim available tasks, work in task-bound worktrees, and complete tasks without
waiting for explicit Lead assignment. Use worktree tools when you need isolated
parallel file changes. Use connect_mcp to attach external tool servers; newly
connected MCP tools appear as mcp__server__tool on the next loop.

Use schedule_cron, list_crons, and cancel_cron for scheduled work. Cron uses
five fields: minute hour day month weekday. Scheduled prompts are injected back
as [Scheduled] messages when the scheduler fires.

The public science workflow has one outer orchestration path:
create_research_project, then run_autogen_groupchat. Before project creation,
list_research_projects may be used for inspection; after creation,
get_research_project may inspect the active project. Do not call decomposition,
literature search/import, ZhiZhi, TanXi, evidence extraction, review, proposal,
crew, delegation, or pipeline-DAG tools from the outer agent. The GroupChat
executor internally owns sub-hypothesis decomposition, contract construction,
retrieval, evidence admission, document-level LLM proposition extraction,
TanXi analysis, review, and proposal continuation. Call exactly one outer tool
per response and wait for its result before selecting the next tool. Never
claim that an internal stage ran unless run_autogen_groupchat returned evidence
that it ran.
"""

SUBAGENT_SYSTEM_APPENDIX = """Sub-agent mode:
- You are working on a delegated subtask.
- Do not delegate again or spawn another agent.
- Return a concise summary of findings, changes, and verification.
"""


def scan_skills(skills_dir: Path = SKILLS_DIR) -> list[Skill]:
    skills: list[Skill] = []
    if not skills_dir.exists():
        return skills

    for skill_file in sorted(skills_dir.glob("*/SKILL.md")):
        text = skill_file.read_text(encoding="utf-8")
        meta, body = parse_frontmatter(text)
        name = meta.get("name") or skill_file.parent.name
        description = meta.get("description") or "No description."
        skills.append(
            Skill(name=name, description=description, body=body.strip(), path=skill_file)
        )
    return skills


def parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    if not text.startswith("---\n"):
        return {}, text

    parts = text.split("---\n", 2)
    if len(parts) < 3:
        return {}, text

    meta_text = parts[1]
    body = parts[2]
    meta: dict[str, str] = {}
    for raw_line in meta_text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, value = line.split(":", 1)
        meta[key.strip()] = value.strip().strip("\"'")
    return meta, body


def build_system(
    user_input: str = "",
    *,
    subagent: bool = False,
    include_memory: bool = True,
    memory_types: set[str] | frozenset[str] | None = None,
) -> str:
    skills = scan_skills()
    sections = [BASE_SYSTEM_PROMPT.strip(), f"Workspace: {WORKDIR}"]

    if include_memory:
        memory_block = render_memories(user_input, allowed_types=memory_types)
        if memory_block:
            sections.append(memory_block)

    mcp_block = connected_mcp_summary()
    if mcp_block:
        sections.append(mcp_block)

    if skills:
        catalog = "\n".join(
            f"- {skill.name}: {skill.description}" for skill in skills
        )
        sections.append(
            "Available skills:\n"
            f"{catalog}\n\n"
            "Use a skill when the user request matches its description. "
            "If you need the full instructions, call load_skill(name)."
        )

    if subagent:
        sections.append(SUBAGENT_SYSTEM_APPENDIX.strip())

    return "\n\n".join(sections)


def load_skill(name: str) -> str:
    needle = name.strip().lower()
    if not needle:
        raise ValueError("skill name is required")
    skills = scan_skills()
    for skill in skills:
        if skill.name.lower() == needle or skill.path.parent.name.lower() == needle:
            return f"## {skill.name}\n\n{skill.body}"
    available = ", ".join(skill.name for skill in skills) or "(none)"
    raise ValueError(f"Skill not found: {name}. Available: {available}")
