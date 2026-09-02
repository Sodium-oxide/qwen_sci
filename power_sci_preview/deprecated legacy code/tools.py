from __future__ import annotations

import glob as glob_module
import json
import subprocess
from pathlib import Path
from typing import Callable

try:
    from .config import (
        BASH_TIMEOUT_SECONDS,
        MAX_OUTPUT_CHARS,
        TOOL_RESULTS_DIR,
        WORKDIR,
    )
except ImportError:
    from config import (
        BASH_TIMEOUT_SECONDS,
        MAX_OUTPUT_CHARS,
        TOOL_RESULTS_DIR,
        WORKDIR,
    )


def truncate(text: str, limit: int = MAX_OUTPUT_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n...[truncated to {limit} characters]"


def safe_cwd(cwd: str | None = None) -> Path:
    if not cwd:
        return WORKDIR
    raw = Path(cwd).expanduser()
    candidate = raw if raw.is_absolute() else WORKDIR / raw
    resolved = candidate.resolve()
    if not resolved.is_relative_to(WORKDIR):
        raise ValueError(f"cwd escapes workspace: {cwd}")
    if not resolved.exists() or not resolved.is_dir():
        raise ValueError(f"cwd is not a directory: {cwd}")
    return resolved


def safe_path(path: str, cwd: str | None = None) -> Path:
    root = safe_cwd(cwd)
    raw = Path(path).expanduser()
    candidate = raw if raw.is_absolute() else root / raw
    resolved = candidate.resolve()
    if not resolved.is_relative_to(root):
        raise ValueError(f"Path escapes current workspace: {path}")
    return resolved


def path_escapes_workspace(path: str) -> bool:
    raw = Path(path).expanduser()
    candidate = raw if raw.is_absolute() else WORKDIR / raw
    return not candidate.resolve().is_relative_to(WORKDIR)


def relative(path: Path) -> str:
    resolved = path.resolve()
    if resolved.is_relative_to(WORKDIR):
        return str(resolved.relative_to(WORKDIR)).replace("\\", "/")
    return str(resolved)


def bash(command: str, cwd: str | None = None) -> str:
    root = safe_cwd(cwd)
    completed = subprocess.run(
        command,
        cwd=root,
        shell=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=BASH_TIMEOUT_SECONDS,
    )
    output = []
    if completed.stdout:
        output.append(completed.stdout)
    if completed.stderr:
        output.append(completed.stderr)
    if not output:
        output.append("(no output)")
    output.append(f"\n[exit_code={completed.returncode}]")
    return truncate("".join(output))


def read_file(path: str, limit: int | None = None, cwd: str | None = None) -> str:
    target = safe_path(path, cwd)
    if is_tool_result_artifact(target):
        return read_tool_result_artifact(target, limit)
    with target.open("r", encoding="utf-8", errors="replace") as handle:
        lines = handle.readlines()

    if limit is not None and limit >= 0 and len(lines) > limit:
        visible = lines[:limit]
        visible.append(f"\n...[truncated after {limit} lines]\n")
        lines = visible

    return "".join(f"{index + 1:>4} | {line}" for index, line in enumerate(lines))


def is_tool_result_artifact(path: Path) -> bool:
    try:
        resolved = path.resolve()
        root = TOOL_RESULTS_DIR.resolve()
    except Exception:
        return False
    return resolved.is_relative_to(root) and resolved.suffix.lower() == ".txt"


def read_tool_result_artifact(path: Path, limit: int | None = None) -> str:
    text = path.read_text(encoding="utf-8", errors="replace")
    rel = relative(path)
    if limit is not None and 0 <= limit <= 80:
        lines = text.splitlines(keepends=True)
        visible = lines[:limit]
        if len(lines) > limit:
            visible.append(f"\n...[truncated after {limit} lines; tool result artifact has {len(text)} chars]\n")
        body = "".join(f"{index + 1:>4} | {line}" for index, line in enumerate(visible))
        return bounded_tool_result_preview(
            rel=rel,
            chars=len(text),
            mode=f"first {limit} lines",
            body=body,
        )
    head = text[:1200]
    tail = text[-1200:] if len(text) > 1200 else ""
    return bounded_tool_result_preview(
        rel=rel,
        chars=len(text),
        mode="head/tail",
        body=f"--- head ---\n{head}\n--- tail ---\n{tail}",
    )


def bounded_tool_result_preview(rel: str, chars: int, mode: str, body: str) -> str:
    header = (
        "[tool result artifact preview]\n"
        f"path: {rel}\n"
        f"chars: {chars}\n"
        f"mode: {mode}\n"
        "reason: Refusing full read of v8/tool_results artifacts to prevent recursive large-output loops.\n"
        "Use the original producing tool/search id when possible; this preview is intentionally bounded.\n\n"
    )
    rendered = header + body
    max_preview_chars = 6000
    if len(rendered) <= max_preview_chars:
        return rendered
    return rendered[:max_preview_chars] + (
        f"\n...[tool result artifact preview truncated to {max_preview_chars} chars]\n"
    )


def write_file(path: str, content: str, cwd: str | None = None, actor: str = "lead") -> str:
    target = safe_path(path, cwd)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return f"Wrote {len(content)} characters to {relative(target)}"


def edit_file(path: str, old_text: str, new_text: str, cwd: str | None = None, actor: str = "lead") -> str:
    target = safe_path(path, cwd)
    content = target.read_text(encoding="utf-8", errors="replace")
    if old_text not in content:
        raise ValueError("old_text was not found.")
    updated = content.replace(old_text, new_text, 1)
    target.write_text(updated, encoding="utf-8")
    return f"Replaced one occurrence in {relative(target)}"


def glob(pattern: str, limit: int = 200, cwd: str | None = None) -> str:
    matches: list[str] = []
    root = safe_cwd(cwd)
    search_pattern = str(root / pattern)
    for match in glob_module.glob(search_pattern, recursive=True):
        path = Path(match).resolve()
        if path.is_relative_to(root):
            matches.append(relative(path))

    matches = sorted(set(matches))[:limit]
    if not matches:
        return "(no matches)"
    return "\n".join(matches)


def spawn_subagent(description: str) -> str:
    try:
        from .subagent import spawn_subagent as run_subagent
    except ImportError:
        from subagent import spawn_subagent as run_subagent

    return run_subagent(description)


def task(description: str) -> str:
    return spawn_subagent(description)


def todo_write(items: list[dict[str, object]] | list[str]) -> str:
    try:
        from .todo_state import todo_write as write_todos
    except ImportError:
        from todo_state import todo_write as write_todos
    return write_todos(items)


def load_skill(name: str) -> str:
    try:
        from .skill import load_skill as skill_load
    except ImportError:
        from skill import load_skill as skill_load
    return skill_load(name)


def compact(focus: str = "") -> str:
    if focus:
        return f"Compaction requested. Focus: {focus}"
    return "Compaction requested."


def create_task(subject: str, description: str, blockedBy: list[str] | None = None) -> str:
    try:
        from .task_system import create_task as task_create
    except ImportError:
        from task_system import create_task as task_create
    return task_create(subject, description, blockedBy)


def list_tasks(include_completed: bool = True) -> str:
    try:
        from .task_system import list_tasks as task_list
    except ImportError:
        from task_system import list_tasks as task_list
    return task_list(include_completed)


def get_task(task_id: str) -> str:
    try:
        from .task_system import get_task as task_get
    except ImportError:
        from task_system import get_task as task_get
    return task_get(task_id)


def claim_task(task_id: str, owner: str = "main") -> str:
    try:
        from .task_system import claim_task as task_claim
    except ImportError:
        from task_system import claim_task as task_claim
    return task_claim(task_id, owner)


def complete_task(task_id: str) -> str:
    try:
        from .task_system import complete_task as task_complete
    except ImportError:
        from task_system import complete_task as task_complete
    return task_complete(task_id)










def connect_mcp(name: str) -> str:
    try:
        from .mcp_plugin import connect_mcp as mcp_connect
    except ImportError:
        from mcp_plugin import connect_mcp as mcp_connect
    return mcp_connect(name)


def schedule_cron(
    cron: str,
    prompt: str,
    recurring: bool = True,
    durable: bool = True,
) -> str:
    try:
        from .cron_scheduler import schedule_cron as cron_schedule
    except ImportError:
        from cron_scheduler import schedule_cron as cron_schedule
    return cron_schedule(cron, prompt, recurring, durable)


def list_crons() -> str:
    try:
        from .cron_scheduler import list_crons as cron_list
    except ImportError:
        from cron_scheduler import list_crons as cron_list
    return cron_list()


def cancel_cron(job_id: str) -> str:
    try:
        from .cron_scheduler import cancel_cron as cron_cancel
    except ImportError:
        from cron_scheduler import cancel_cron as cron_cancel
    return cron_cancel(job_id)


def create_research_project(
    title: str,
    domain: str,
    objective: str,
    strategic_need: str = "",
    research_brief: str = "",
    force_new_project: bool = False,
) -> str:
    try:
        from .science_core import create_research_project as science_create
    except ImportError:
        from science_core import create_research_project as science_create
    result = json.loads(
        science_create(title, domain, objective, strategic_need, research_brief)
    )
    result["force_new_project"] = bool(force_new_project)
    return json.dumps(result, ensure_ascii=False, indent=2)


def decompose_research_objective(
    project_id: str,
    max_subhypotheses: int = 6,
    use_llm: bool = True,
) -> str:
    try:
        from .science_core import decompose_research_objective as science_decompose
    except ImportError:
        from science_core import decompose_research_objective as science_decompose
    return science_decompose(project_id, max_subhypotheses, use_llm)


def set_research_brief(
    project_id: str,
    research_brief: str,
    redecompose: bool = False,
    use_llm: bool = True,
) -> str:
    try:
        from .science_core import set_research_brief as science_set_brief
    except ImportError:
        from science_core import set_research_brief as science_set_brief
    return science_set_brief(project_id, research_brief, redecompose, use_llm)


def list_research_projects() -> str:
    try:
        from .science_core import list_research_projects as science_list
    except ImportError:
        from science_core import list_research_projects as science_list
    return science_list()


def get_research_project(project_id: str) -> str:
    try:
        from .science_core import get_research_project as science_get
    except ImportError:
        from science_core import get_research_project as science_get
    return science_get(project_id)


def list_science_agents() -> str:
    try:
        from .science_core import list_science_agents as science_agents
    except ImportError:
        from science_core import list_science_agents as science_agents
    return science_agents()


def get_science_agent_prompt(agent: str) -> str:
    try:
        from .science_core import get_science_agent_prompt as science_prompt
    except ImportError:
        from science_core import get_science_agent_prompt as science_prompt
    return science_prompt(agent)


def list_literature_providers() -> str:
    try:
        from .science_core import list_literature_providers as science_providers
    except ImportError:
        from science_core import list_literature_providers as science_providers
    return science_providers()


def list_natural_science_disciplines() -> str:
    """List the discovery taxonomy without exposing humanities/social science."""
    try:
        from .science_core import list_natural_science_disciplines as list_disciplines
    except ImportError:
        from science_core import list_natural_science_disciplines as list_disciplines
    return json.dumps(
        {
            "schema_version": "natural_science_discipline_taxonomy_v1",
            "scope": "natural_science_health_engineering_only",
            "disciplines": list_disciplines(),
        },
        ensure_ascii=False,
        indent=2,
    )


def resolve_natural_science_discipline_taxonomy(domain: str, query: str = "") -> str:
    """Preview provider-native discovery filters without running a search."""
    try:
        from .science_core import resolve_discipline_taxonomy as resolve_taxonomy
    except ImportError:
        from science_core import resolve_discipline_taxonomy as resolve_taxonomy
    return json.dumps(resolve_taxonomy(domain, query=query), ensure_ascii=False, indent=2)


def literature_provider_doctor() -> str:
    try:
        from .science_core import literature_provider_doctor as science_provider_doctor
    except ImportError:
        from science_core import literature_provider_doctor as science_provider_doctor
    return science_provider_doctor()


def literature_provider_smoke(
    provider: str = "openalex",
    query: str = "controlled causal mechanism evidence",
    live: bool = False,
) -> str:
    try:
        from .science_core import literature_provider_smoke as science_provider_smoke
    except ImportError:
        from science_core import literature_provider_smoke as science_provider_smoke
    return science_provider_smoke(provider, query, live)


def document_conversion_doctor() -> str:
    """Report the offline MarkItDown document-conversion contract and readiness."""
    try:
        from ._document_conversion import document_conversion_capability_registry, markitdown_version
        from .config import (
            SCIENCE_DOCUMENT_OCR_API_KEY,
            SCIENCE_DOCUMENT_OCR_ENABLED,
            SCIENCE_DOCUMENT_OCR_MODEL,
            SCIENCE_MULTIMODAL_API_BASE,
            SCIENCE_MULTIMODAL_API_KEY,
            SCIENCE_MULTIMODAL_COUNTS_TOWARD_GATE,
            SCIENCE_MULTIMODAL_ENABLED,
            SCIENCE_MULTIMODAL_FALLBACK_MODEL,
            SCIENCE_MULTIMODAL_MODEL,
            SCIENCE_MULTIMODAL_PROVIDER,
            SCIENCE_MULTIMODAL_REQUIRE_HUMAN_REVIEW,
        )
    except ImportError:
        from _document_conversion import document_conversion_capability_registry, markitdown_version
        from config import (
            SCIENCE_DOCUMENT_OCR_API_KEY,
            SCIENCE_DOCUMENT_OCR_ENABLED,
            SCIENCE_DOCUMENT_OCR_MODEL,
            SCIENCE_MULTIMODAL_API_BASE,
            SCIENCE_MULTIMODAL_API_KEY,
            SCIENCE_MULTIMODAL_COUNTS_TOWARD_GATE,
            SCIENCE_MULTIMODAL_ENABLED,
            SCIENCE_MULTIMODAL_FALLBACK_MODEL,
            SCIENCE_MULTIMODAL_MODEL,
            SCIENCE_MULTIMODAL_PROVIDER,
            SCIENCE_MULTIMODAL_REQUIRE_HUMAN_REVIEW,
        )
    from importlib.util import find_spec

    dependencies = {
        package: bool(find_spec(package))
        for package in ("markitdown", "pdfminer", "pdfplumber", "mammoth", "pandas", "openpyxl")
    }
    required_ready = all(
        dependencies[package]
        for package in ("markitdown", "pdfminer", "pdfplumber", "mammoth", "pandas", "openpyxl")
    )
    ocr_status = (
        "disabled"
        if not SCIENCE_DOCUMENT_OCR_ENABLED
        else "configured" if SCIENCE_DOCUMENT_OCR_MODEL and SCIENCE_DOCUMENT_OCR_API_KEY else "missing_configuration"
    )
    return json.dumps(
        {
            "status": "ready" if required_ready else "degraded",
            "backend": {"name": "markitdown", "version": markitdown_version(), "plugins_enabled": False},
            "capabilities": document_conversion_capability_registry(),
            "dependencies": dependencies,
            "ocr": {
                "status": ocr_status,
                "candidate_only_when_completed": True,
                "credentials_present": bool(SCIENCE_DOCUMENT_OCR_API_KEY),
                "model_present": bool(SCIENCE_DOCUMENT_OCR_MODEL),
            },
            "multimodal_visual_evidence": {
                "enabled": bool(SCIENCE_MULTIMODAL_ENABLED),
                "provider": SCIENCE_MULTIMODAL_PROVIDER,
                "model": SCIENCE_MULTIMODAL_MODEL,
                "fallback_model": SCIENCE_MULTIMODAL_FALLBACK_MODEL,
                "api_key_present": bool(SCIENCE_MULTIMODAL_API_KEY),
                "api_base_configured": bool(SCIENCE_MULTIMODAL_API_BASE),
                "counts_toward_gate": bool(SCIENCE_MULTIMODAL_COUNTS_TOWARD_GATE),
                "effective_counts_toward_gate": False,
                "requires_human_review": bool(SCIENCE_MULTIMODAL_REQUIRE_HUMAN_REVIEW),
                "capability_probe_status": "not_run",
                "gate_policy": "candidate_only_until_human_review",
            },
            "policy": {
                "remote_url_conversion_allowed": False,
                "generic_zip_conversion_allowed": False,
                "automatic_direct_evidence_requires_ready_pdf_or_html": True,
                "multimodal_visual_evidence_counts_toward_gate": False,
            },
        },
        ensure_ascii=False,
        indent=2,
    )


def explore_domain_subspaces(
    domain: str,
    max_subspaces: int = 12,
    probe_depth: int = 5,
    use_llm: bool = True,
    providers: list[str] | None = None,
    user_hints: list[str] | None = None,
) -> str:
    try:
        from .science_core import explore_domain_subspaces as science_explore_subspaces
    except ImportError:
        from science_core import explore_domain_subspaces as science_explore_subspaces
    return science_explore_subspaces(domain, max_subspaces, probe_depth, use_llm, providers, user_hints)


def search_literature(
    query: str,
    providers: list[str] | None = None,
    max_results: int = 30,
    domain: str = "",
) -> str:
    try:
        from .science_core import search_literature as science_search
    except ImportError:
        from science_core import search_literature as science_search
    return science_search(query, providers, max_results, domain=domain)


def search_literature_stratified(
    query: str,
    providers: list[str] | None = None,
    max_results: int = 50,
    domain: str = "",
    focus_branches: list[str] | None = None,
    use_llm: bool | None = None,
) -> str:
    try:
        from .science_core import search_literature_stratified as science_search_stratified
    except ImportError:
        from science_core import search_literature_stratified as science_search_stratified
    return science_search_stratified(query, providers, max_results, domain, focus_branches, use_llm)


def search_papers(
    query: str,
    databases: list[str] | None = None,
    max_results: int = 50,
    years: str = "",
) -> str:
    try:
        from .science_core import search_papers as science_search_papers
    except ImportError:
        from science_core import search_papers as science_search_papers
    return science_search_papers(query, databases, max_results, years)


def search_papers_stratified(
    query: str,
    databases: list[str] | None = None,
    max_results: int = 50,
    years: str = "",
    domain: str = "",
    focus_branches: list[str] | None = None,
    use_llm: bool | None = None,
) -> str:
    try:
        from .science_core import search_papers_stratified as science_search_papers_stratified
    except ImportError:
        from science_core import search_papers_stratified as science_search_papers_stratified
    return science_search_papers_stratified(query, databases, max_results, years, domain, focus_branches, use_llm)


def extract_structured_info(
    paper_content: str,
    fields: list[str] | None = None,
    use_llm: bool | None = None,
) -> str:
    try:
        from .science_core import extract_structured_info as science_extract_structured
    except ImportError:
        from science_core import extract_structured_info as science_extract_structured
    return science_extract_structured(paper_content, fields, use_llm)


def select_literature_result(
    search_id: str,
    query: str = "",
    top_k: int = 5,
    use_llm: bool | None = None,
) -> str:
    try:
        from .science_core import select_literature_result as science_select_result
    except ImportError:
        from science_core import select_literature_result as science_select_result
    return science_select_result(search_id, query, top_k, use_llm)


def expand_literature_graph(
    search_id: str,
    result_index: int = 0,
    query: str = "",
    direction: str = "both",
    max_results: int = 50,
    use_llm: bool = False,
    depth: int = 1,
    second_layer_top_k: int = 3,
    allow_fallback: bool = True,
) -> str:
    try:
        from .science_core import expand_literature_graph as science_expand_graph
    except ImportError:
        from science_core import expand_literature_graph as science_expand_graph
    return science_expand_graph(
        search_id,
        result_index,
        query,
        direction,
        max_results,
        use_llm,
        depth,
        second_layer_top_k,
        allow_fallback,
    )


def search_cross_community_bridges(
    search_id: str,
    target_communities: list[str] | None = None,
    max_results: int = 12,
) -> str:
    try:
        from .science_core import search_cross_community_bridges as science_bridge_search
    except ImportError:
        from science_core import search_cross_community_bridges as science_bridge_search
    return science_bridge_search(search_id, target_communities, max_results)


def build_literature_relation_graph(
    search_id: str,
    query: str = "",
    max_nodes: int = 80,
    min_quality: float = 0.0,
    max_clusters: int = 8,
    run_louvain: bool = True,
    louvain_resolution: float | None = None,
) -> str:
    try:
        from .science_core import build_literature_relation_graph as science_relation_graph
    except ImportError:
        from science_core import build_literature_relation_graph as science_relation_graph
    return science_relation_graph(
        search_id,
        query,
        max_nodes,
        min_quality,
        max_clusters,
        run_louvain=run_louvain,
        louvain_resolution=louvain_resolution,
    )


def run_autogen_groupchat(
    project_id: str,
    goal: str = "",
    groupchat_id: str = "",
    restart_from_decomposition: bool = False,
) -> str:
    try:
        from .autogen_collab import run_autogen_groupchat as autogen_flow
    except ImportError:
        from autogen_collab import run_autogen_groupchat as autogen_flow
    return autogen_flow(
        project_id=project_id,
        goal=goal,
        groupchat_id=groupchat_id,
        restart_from_decomposition=restart_from_decomposition,
    )


def list_autogen_groupchats(project_id: str = "") -> str:
    try:
        from .autogen_collab import list_autogen_groupchats as autogen_list
    except ImportError:
        from autogen_collab import list_autogen_groupchats as autogen_list
    return autogen_list(project_id)


def get_autogen_run(run_id: str, include_details: bool = False) -> str:
    try:
        from .autogen_collab import get_autogen_run as autogen_run
    except ImportError:
        from autogen_collab import get_autogen_run as autogen_run
    return autogen_run(run_id, include_details=include_details)


def build_knowledge_map(project_id: str, dimension: str = "method-scenario-benchmark") -> str:
    try:
        from .science_core import build_knowledge_map as science_knowledge_map
    except ImportError:
        from science_core import build_knowledge_map as science_knowledge_map
    return science_knowledge_map(project_id, dimension)


def build_louvain_community_knowledge_maps(
    project_id: str,
    relation_graph_id: str = "",
    min_records: int | None = None,
) -> str:
    try:
        from .science_core import build_louvain_community_knowledge_maps as science_community_maps
    except ImportError:
        from science_core import build_louvain_community_knowledge_maps as science_community_maps
    return science_community_maps(project_id, relation_graph_id, min_records)


def add_literature_evidence(
    project_id: str,
    title: str,
    citation: str,
    method: str,
    scenario: str,
    benchmark: str,
    contribution: str,
    limitation: str,
    url: str = "",
) -> str:
    try:
        from .science_core import add_literature_evidence as science_add_evidence
    except ImportError:
        from science_core import add_literature_evidence as science_add_evidence
    return science_add_evidence(project_id, title, citation, method, scenario, benchmark, contribution, limitation, url)


def import_literature_text(
    project_id: str,
    text: str,
    title: str = "",
    citation: str = "",
    provider: str = "manual",
    source_type: str = "abstract",
    url: str = "",
    doi: str = "",
    arxiv_id: str = "",
    semantic_scholar_id: str = "",
    authors: list[str] | None = None,
    year: str = "",
    venue: str = "",
    use_llm: bool | None = None,
) -> str:
    try:
        from .science_core import import_literature_text as science_import_text
    except ImportError:
        from science_core import import_literature_text as science_import_text
    return science_import_text(
        project_id=project_id,
        text=text,
        title=title,
        citation=citation,
        provider=provider,
        source_type=source_type,
        url=url,
        doi=doi,
        arxiv_id=arxiv_id,
        semantic_scholar_id=semantic_scholar_id,
        authors=authors,
        year=year,
        venue=venue,
        use_llm=use_llm,
    )


def import_literature_file(
    project_id: str,
    path: str,
    title: str = "",
    citation: str = "",
    provider: str = "manual_file",
    source_type: str = "file",
    use_llm: bool | None = None,
    sub_hypothesis: str = "",
) -> str:
    try:
        from .science_core import import_literature_file as science_import_file
    except ImportError:
        from science_core import import_literature_file as science_import_file
    return science_import_file(project_id, path, title, citation, provider, source_type, use_llm, sub_hypothesis)


def import_literature_search_result(
    project_id: str,
    search_id: str,
    result_index: int = 0,
    use_llm: bool | None = None,
    force_import: bool = False,
) -> str:
    try:
        from .science_core import import_literature_search_result as science_import_search_result
    except ImportError:
        from science_core import import_literature_search_result as science_import_search_result
    return science_import_search_result(
        project_id,
        search_id,
        result_index,
        use_llm,
        force_import=force_import,
    )


def domain_review_paper(
    project_id: str,
    paper_id: str,
    target_domain_profile: list[str] | str | None = None,
    min_confidence: float = 0.6,
) -> dict[str, Any]:
    """Audit an already imported paper and deactivate clear domain noise."""
    try:
        from .science_core import domain_review_paper as science_domain_review
    except ImportError:
        from science_core import domain_review_paper as science_domain_review
    return science_domain_review(project_id, paper_id, target_domain_profile, min_confidence)


def reconcile_project_domain_reviews(
    project_id: str,
    target_domain_profile: list[str] | str | None = None,
    min_confidence: float = 0.6,
    include_active: bool = False,
) -> str:
    try:
        from .science_core import reconcile_project_domain_reviews as science_reconcile_reviews
    except ImportError:
        from science_core import reconcile_project_domain_reviews as science_reconcile_reviews
    return science_reconcile_reviews(project_id, target_domain_profile, min_confidence, include_active)


def extract_paper_keynote(
    project_id: str,
    paper_id: str = "",
    search_id: str = "",
    result_index: int = 0,
    text: str = "",
    use_llm: bool = True,
) -> str:
    try:
        from .science_core import extract_paper_keynote as science_keynote
    except ImportError:
        from science_core import extract_paper_keynote as science_keynote
    return science_keynote(project_id, paper_id, search_id, result_index, text, use_llm)


def import_papergraph_record(
    project_id: str,
    title: str,
    citation: str,
    authors: list[str] | None = None,
    year: str = "",
    venue: str = "",
    provider: str = "manual",
    source_type: str = "metadata",
    doi: str = "",
    arxiv_id: str = "",
    semantic_scholar_id: str = "",
    url: str = "",
    abstract: str = "",
    full_text_excerpt: str = "",
    conclusion: str = "",
    strengths: list[str] | None = None,
    improvements: list[str] | None = None,
    method: str = "",
    scenario: str = "",
    benchmark: str = "",
    contribution: str = "",
    limitation: str = "",
) -> str:
    try:
        from .science_core import import_papergraph_record as science_import_record
    except ImportError:
        from science_core import import_papergraph_record as science_import_record
    return science_import_record(
        project_id=project_id,
        title=title,
        citation=citation,
        authors=authors,
        year=year,
        venue=venue,
        provider=provider,
        source_type=source_type,
        doi=doi,
        arxiv_id=arxiv_id,
        semantic_scholar_id=semantic_scholar_id,
        url=url,
        abstract=abstract,
        full_text_excerpt=full_text_excerpt,
        conclusion=conclusion,
        strengths=strengths,
        improvements=improvements,
        method=method,
        scenario=scenario,
        benchmark=benchmark,
        contribution=contribution,
        limitation=limitation,
    )


def list_papergraph_records(project_id: str) -> str:
    try:
        from .science_core import list_papergraph_records as science_list_records
    except ImportError:
        from science_core import list_papergraph_records as science_list_records
    return science_list_records(project_id)


def verify_citation_uniqueness(
    project_id: str,
    title: str = "",
    citation: str = "",
    doi: str = "",
    arxiv_id: str = "",
    semantic_scholar_id: str = "",
    url: str = "",
) -> str:
    try:
        from .science_core import verify_citation_uniqueness as science_verify_unique
    except ImportError:
        from science_core import verify_citation_uniqueness as science_verify_unique
    return science_verify_unique(project_id, title, citation, doi, arxiv_id, semantic_scholar_id, url)


def assess_novelty(
    project_id: str,
    gap: dict[str, object] | str,
    dimensions: list[str] | None = None,
) -> str:
    try:
        from .science_core import assess_novelty as science_assess
    except ImportError:
        from science_core import assess_novelty as science_assess
    return science_assess(project_id, gap, dimensions)


def verify_uniqueness(
    project_id: str,
    idea: str,
    precision: str = "high",
    live_search: bool = False,
    providers: list[str] | None = None,
) -> str:
    try:
        from .science_core import verify_uniqueness as science_verify_idea
    except ImportError:
        from science_core import verify_uniqueness as science_verify_idea
    return science_verify_idea(project_id, idea, precision, live_search, providers)


def run_zhizhi_subhypothesis_analysis(
    project_id: str,
    sub_hypothesis_ids: list[str] | None = None,
) -> str:
    try:
        from .science_core import run_zhizhi_subhypothesis_analysis as science_zhizhi_subhypothesis
    except ImportError:
        from science_core import run_zhizhi_subhypothesis_analysis as science_zhizhi_subhypothesis
    return science_zhizhi_subhypothesis(
        project_id=project_id,
        sub_hypothesis_ids=sub_hypothesis_ids,
    )


def parse_literature_text(text: str, use_llm: bool | None = None) -> str:
    try:
        from .science_core import parse_literature_text as science_parse_text
    except ImportError:
        from science_core import parse_literature_text as science_parse_text
    return science_parse_text(text, use_llm)


def build_coverage_matrix(project_id: str) -> str:
    try:
        from .science_core import build_coverage_matrix as science_matrix
    except ImportError:
        from science_core import build_coverage_matrix as science_matrix
    return science_matrix(project_id)


def detect_knowledge_gaps(project_id: str, max_gaps: int = 10) -> str:
    try:
        from .science_core import detect_knowledge_gaps as science_gaps
    except ImportError:
        from science_core import detect_knowledge_gaps as science_gaps
    return science_gaps(project_id, max_gaps)


def run_tanxi_gap_exploration(
    project_id: str,
    target_domain: str = "",
    strategic_domains: list[str] | None = None,
    max_gaps: int = 10,
    semantic_audit_mode: str = "deterministic",
) -> str:
    try:
        from .science_core import run_tanxi_gap_exploration as science_tanxi
    except ImportError:
        from science_core import run_tanxi_gap_exploration as science_tanxi
    return science_tanxi(
        project_id,
        target_domain,
        strategic_domains,
        max_gaps,
        semantic_audit_mode=semantic_audit_mode,
    )


def apply_gap_retrieval_assessment(
    project_id: str,
    gap_id: str,
    retrieval_assessment: dict[str, object],
) -> str:
    """Apply a source-bound, type-directed retrieval decision to one v2 gap."""
    try:
        from .science_core import apply_gap_retrieval_assessment as science_apply
    except ImportError:
        from science_core import apply_gap_retrieval_assessment as science_apply
    return science_apply(project_id, gap_id, dict(retrieval_assessment))


def execute_research_question_retrieval_plan(
    project_id: str,
    sub_hypothesis_id: str,
    retrieval_results: list[dict[str, object]] | None = None,
) -> str:
    """Record an authorised V3 question-slot retrieval execution.

    ``source_ids`` name documents already imported by the provider adapter;
    this operation records coverage only and cannot infer a gap from an empty
    retrieval result.
    """
    try:
        from .science_core import execute_research_question_retrieval_plan as science_execute
    except ImportError:
        from science_core import execute_research_question_retrieval_plan as science_execute
    return science_execute(
        project_id,
        sub_hypothesis_id,
        retrieval_results,
    )


def run_socrates_type_specific_review(project_id: str, gap_id: str) -> str:
    """Review a qualified v2 ResearchPackage using its own evidence contract."""
    try:
        from .science_core import run_socrates_type_specific_review as science_review
    except ImportError:
        from science_core import run_socrates_type_specific_review as science_review
    import json
    return json.dumps(science_review(project_id, gap_id), ensure_ascii=False, indent=2)


def build_research_evidence_graph_v3(project_id: str) -> str:
    """Direct callers must resume the owning V3 AutoGen GroupChat."""
    import json
    return json.dumps(
        {
            "status": "BLOCKED_V3_GROUPCHAT_ONLY",
            "project_id": project_id,
            "reason_code": "V3_GROUPCHAT_RESUME_REQUIRED",
            "instruction": (
                "Resume the owning AutoGen GroupChat. TanXi builds the detached "
                "Research Evidence Graph from the V3 retrieval ledger and does not "
                "permit an independent full-project graph build."
            ),
        },
        ensure_ascii=False,
        indent=2,
    )


def get_research_graph_view_v3(
    project_id: str,
    research_question_contract_id: str = "",
    gap_type: str = "",
    required_scope_axes: list[str] | None = None,
    include_derived_inferences: bool = False,
) -> str:
    """Return a source-bounded GraphView for one declared research question."""
    try:
        from .science_core import get_research_graph_view
    except ImportError:
        from science_core import get_research_graph_view
    import json
    return json.dumps(
        get_research_graph_view(
            project_id,
            research_question_contract_id=research_question_contract_id,
            gap_type=gap_type,
            required_scope_axes=list(required_scope_axes or []),
            include_derived_inferences=include_derived_inferences,
        ),
        ensure_ascii=False,
        indent=2,
    )


def build_proposal_brief_v2(project_id: str, research_package_id: str) -> str:
    """Freeze one reviewed research_package_v2 as a type-directed brief."""
    try:
        from .science_core import build_and_persist_proposal_brief
    except ImportError:
        from science_core import build_and_persist_proposal_brief
    import json
    return json.dumps(build_and_persist_proposal_brief(project_id, research_package_id), ensure_ascii=False, indent=2)


def write_research_proposal_v2(project_id: str, proposal_brief_id: str) -> str:
    """Write a source-bounded proposal draft from ProposalBriefV2."""
    try:
        from .science_core import write_and_persist_research_proposal
    except ImportError:
        from science_core import write_and_persist_research_proposal
    import json
    return json.dumps(write_and_persist_research_proposal(project_id, proposal_brief_id), ensure_ascii=False, indent=2)


def audit_research_proposal_v2(project_id: str, proposal_id: str) -> str:
    """Audit source provenance, type contract, scope, and frozen versions."""
    try:
        from .science_core import audit_and_persist_research_proposal
    except ImportError:
        from science_core import audit_and_persist_research_proposal
    import json
    return json.dumps(audit_and_persist_research_proposal(project_id, proposal_id), ensure_ascii=False, indent=2)


def export_research_proposal_v2(project_id: str, proposal_id: str, output_dir: str = "") -> str:
    """Export only a current Proposal V2 whose audit passed."""
    try:
        from .science_core import export_research_proposal
    except ImportError:
        from science_core import export_research_proposal
    import json
    return json.dumps(export_research_proposal(project_id, proposal_id, output_dir), ensure_ascii=False, indent=2)


def generate_proposal_traceability_report_v3(project_id: str, output_dir: str = "") -> str:
    """Generate a V3 traceability report without requiring any proposal."""
    try:
        from .science_core import generate_proposal_traceability_report
    except ImportError:
        from science_core import generate_proposal_traceability_report
    import json
    return json.dumps(generate_proposal_traceability_report(project_id, output_dir), ensure_ascii=False, indent=2)


def generate_traceability_report_v3(project_id: str, output_dir: str = "") -> str:
    """Canonical V3 name for the always-available evidence traceability report."""
    return generate_proposal_traceability_report_v3(project_id, output_dir)


def generate_research_proposal_report_v3(project_id: str, output_dir: str = "") -> str:
    """Generate a proposal report only for current, audited Proposal V2 artifacts."""
    try:
        from .science_core import generate_research_proposal_report
    except ImportError:
        from science_core import generate_research_proposal_report
    import json
    return json.dumps(generate_research_proposal_report(project_id, output_dir), ensure_ascii=False, indent=2)


def run_zhizhi_near_pass_source_role_retrieval(
    project_id: str,
    candidate_identity: str = "",
    gap_id: str = "",
    retrieval_result: dict[str, object] | None = None,
    providers: list[str] | None = None,
    use_llm: bool | None = None,
) -> str:
    """Execute one TanXi-authorized bounded near-pass evidence repair."""
    try:
        from .science_core import run_zhizhi_near_pass_source_role_retrieval as science_near_pass
    except ImportError:
        from science_core import run_zhizhi_near_pass_source_role_retrieval as science_near_pass
    return science_near_pass(
        project_id,
        candidate_identity=candidate_identity,
        gap_id=gap_id,
        retrieval_result=dict(retrieval_result or {}),
        providers=providers,
        use_llm=use_llm,
    )


def check_semantic_plausibility(
    project_id: str,
    method: str,
    scenario: str,
    gap: dict[str, object] | None = None,
) -> str:
    try:
        from .science_core import load_project, semantic_plausibility_for_pair
    except ImportError:
        from science_core import load_project, semantic_plausibility_for_pair
    project = load_project(project_id)
    import json

    return json.dumps(semantic_plausibility_for_pair(project, method, scenario, gap or {}), ensure_ascii=False, indent=2)


def evolve_domain_subspaces(
    project_id: str,
    subspace_map_id: str = "",
    max_actions: int = 10,
) -> str:
    try:
        from .science_core import evolve_domain_subspaces as science_evolve_subspaces
    except ImportError:
        from science_core import evolve_domain_subspaces as science_evolve_subspaces
    return science_evolve_subspaces(project_id, subspace_map_id, max_actions)


def build_temporal_knowledge_graph(project_id: str) -> str:
    try:
        from .science_core import build_temporal_knowledge_graph as science_temporal_kg
    except ImportError:
        from science_core import build_temporal_knowledge_graph as science_temporal_kg
    return science_temporal_kg(project_id)


def detect_structural_knowledge_gaps(project_id: str, max_gaps: int = 10) -> str:
    try:
        from .science_core import detect_structural_knowledge_gaps as science_structural_gaps
    except ImportError:
        from science_core import detect_structural_knowledge_gaps as science_structural_gaps
    return science_structural_gaps(project_id, max_gaps)


def find_structural_analogy_transfers(
    project_id: str,
    target_scenario: str = "",
    threshold: float = 0.55,
    max_results: int = 50,
) -> str:
    try:
        from .science_core import find_structural_analogy_transfers as science_analogies
    except ImportError:
        from science_core import find_structural_analogy_transfers as science_analogies
    return science_analogies(project_id, target_scenario, threshold, max_results)


def run_mingli_hypothesis_evolution(
    project_id: str,
    gap_ids: list[str] | None = None,
    population_size: int = 24,
    generations: int = 4,
    top_k: int = 5,
    use_llm: bool = False,
) -> str:
    try:
        from .science_core import run_mingli_hypothesis_evolution as science_mingli
    except ImportError:
        from science_core import run_mingli_hypothesis_evolution as science_mingli
    return science_mingli(project_id, gap_ids, population_size, generations, top_k, use_llm)


def run_socrates_mechanism_enrichment(
    project_id: str,
    gap: dict[str, object] | str = "",
    gap_id: str = "",
    mechanism_contract: dict[str, object] | None = None,
    domain: str = "",
    providers: list[str] | None = None,
    max_iterations: int = 3,
    max_fields_per_iteration: int = 2,
    max_results_per_query: int = 12,
    imports_per_query: int = 2,
    use_llm: bool = False,
) -> str:
    try:
        from .science_core import run_socrates_mechanism_enrichment as science_socrates
    except ImportError:
        from science_core import run_socrates_mechanism_enrichment as science_socrates
    return science_socrates(
        project_id, gap, gap_id, mechanism_contract, domain, providers,
        max_iterations, max_fields_per_iteration, max_results_per_query,
        imports_per_query, use_llm,
    )


def generate_idea(
    project_id: str,
    gap: dict[str, object] | str = "",
    gap_id: str = "",
    style: str = "innovative",
    parent_hypothesis_id: str = "",
    use_llm: bool = False,
) -> str:
    try:
        from .science_core import generate_idea as science_generate_idea
    except ImportError:
        from science_core import generate_idea as science_generate_idea
    return science_generate_idea(project_id, gap, gap_id, style, parent_hypothesis_id, use_llm)


def generate_research_report(
    project_id: str,
    report_id: str = "",
    output_dir: str = "",
    template_dir: str = "",
    use_llm: bool = False,
    max_narrative_retries: int = 2,
    report_profile: str = "traceability_report",
    max_design_review_rounds: int = 2,
    latex_engine_path: str = "",
    bibtex_path: str = "",
    pdf_renderer_path: str = "",
    compile_pdf: bool = True,
) -> str:
    """Render an English-only traceability or full research-design LaTeX report."""
    try:
        from .science_core import generate_research_report as science_report
    except ImportError:
        from science_core import generate_research_report as science_report
    return science_report(
        project_id,
        report_id=report_id,
        output_dir=output_dir,
        template_dir=template_dir,
        use_llm=use_llm,
        max_narrative_retries=max_narrative_retries,
        report_profile=report_profile,
        max_design_review_rounds=max_design_review_rounds,
        latex_engine_path=latex_engine_path,
        bibtex_path=bibtex_path,
        pdf_renderer_path=pdf_renderer_path,
        compile_pdf=compile_pdf,
    )


def design_experiment(
    project_id: str,
    idea: dict[str, object] | str = "",
    idea_id: str = "",
    constraints: str = "academic lab scale",
) -> str:
    try:
        from .science_core import design_experiment as science_design_experiment
    except ImportError:
        from science_core import design_experiment as science_design_experiment
    return science_design_experiment(project_id, idea, idea_id, constraints)


def finalize_idea(
    project_id: str,
    idea_json: dict[str, object] | str = "",
    idea_id: str = "",
    live_search: bool = True,
    providers: list[str] | None = None,
) -> str:
    try:
        from .science_core import finalize_idea as science_finalize_idea
    except ImportError:
        from science_core import finalize_idea as science_finalize_idea
    return science_finalize_idea(project_id, idea_json, idea_id, live_search, providers)


def create_hypothesis(
    project_id: str,
    gap_id: str,
    statement: str,
    mechanism: str,
    expected_value: str,
    test_plan: str,
) -> str:
    try:
        from .science_core import create_hypothesis as science_hypothesis
    except ImportError:
        from science_core import create_hypothesis as science_hypothesis
    return science_hypothesis(project_id, gap_id, statement, mechanism, expected_value, test_plan)


def run_mechanism_check(
    project_id: str,
    hypothesis_id: str,
    shifted_conditions: list[str] | None = None,
) -> str:
    try:
        from .science_core import run_mechanism_check as science_check
    except ImportError:
        from science_core import run_mechanism_check as science_check
    return science_check(project_id, hypothesis_id, shifted_conditions)


def check_internal_consistency(
    hypothesis: str,
    reasoning_chain: list[str] | None = None,
) -> str:
    try:
        from .science_core import check_internal_consistency as science_internal
    except ImportError:
        from science_core import check_internal_consistency as science_internal
    return science_internal(hypothesis, reasoning_chain)


def check_data_consistency(
    hypothesis: str,
    cited_data: list[object] | None = None,
    original_sources: list[object] | None = None,
) -> str:
    try:
        from .science_core import check_data_consistency as science_data
    except ImportError:
        from science_core import check_data_consistency as science_data
    return science_data(hypothesis, cited_data, original_sources)


def regime_shift_test(
    mechanism: str,
    original_conditions: dict[str, object] | None = None,
    shifted_conditions: list[object] | None = None,
) -> str:
    try:
        from .science_core import regime_shift_test as science_regime
    except ImportError:
        from science_core import regime_shift_test as science_regime
    return science_regime(mechanism, original_conditions, shifted_conditions)


def detect_selective_citation(
    cited_papers: list[object] | None = None,
    full_paper_contexts: list[object] | None = None,
) -> str:
    try:
        from .science_core import detect_selective_citation as science_selective
    except ImportError:
        from science_core import detect_selective_citation as science_selective
    return science_selective(cited_papers, full_paper_contexts)


def causal_chain_audit(
    causal_chain: list[str] | None = None,
    evidence_for_each: list[object] | None = None,
) -> str:
    try:
        from .science_core import causal_chain_audit as science_chain
    except ImportError:
        from science_core import causal_chain_audit as science_chain
    return science_chain(causal_chain, evidence_for_each)


def run_yanzhen_mechanism_verification(
    project_id: str,
    hypothesis_id: str = "",
    hypothesis: str = "",
    reasoning_chain: list[str] | None = None,
    cited_data: list[object] | None = None,
    original_sources: list[object] | None = None,
    shifted_conditions: list[object] | None = None,
) -> str:
    try:
        from .science_core import run_yanzhen_mechanism_verification as science_yanzhen
    except ImportError:
        from science_core import run_yanzhen_mechanism_verification as science_yanzhen
    return science_yanzhen(project_id, hypothesis_id, hypothesis, reasoning_chain, cited_data, original_sources, shifted_conditions)


def ask_socratic_questions(
    project_id: str = "",
    hypothesis_id: str = "",
    hypothesis: str = "",
    question_types: list[str] | None = None,
    max_questions: int = 12,
) -> str:
    try:
        from .science_core import ask_socratic_questions as science_ask_socratic
    except ImportError:
        from science_core import ask_socratic_questions as science_ask_socratic
    return science_ask_socratic(project_id, hypothesis_id, hypothesis, question_types, max_questions)


def ask_critical_questions(
    project_id: str = "",
    hypothesis_id: str = "",
    hypothesis: str = "",
    question_types: list[str] | None = None,
    max_questions: int = 12,
) -> str:
    try:
        from .science_core import ask_critical_questions as science_ask_critical
    except ImportError:
        from science_core import ask_critical_questions as science_ask_critical
    return science_ask_critical(project_id, hypothesis_id, hypothesis, question_types, max_questions)


def find_counterexamples(
    project_id: str = "",
    hypothesis_id: str = "",
    hypothesis: str = "",
    max_questions: int = 6,
) -> str:
    try:
        from .science_core import find_counterexamples as science_counterexamples
    except ImportError:
        from science_core import find_counterexamples as science_counterexamples
    return science_counterexamples(project_id, hypothesis_id, hypothesis, max_questions)


def stress_test_assumptions(
    project_id: str = "",
    hypothesis_id: str = "",
    hypothesis: str = "",
    max_questions: int = 8,
) -> str:
    try:
        from .science_core import stress_test_assumptions as science_stress
    except ImportError:
        from science_core import stress_test_assumptions as science_stress
    return science_stress(project_id, hypothesis_id, hypothesis, max_questions)


def moderate_round(
    project_id: str,
    round_name: str,
    proponent_position: str = "",
    opponent_questions: list[dict[str, object]] | None = None,
    yanzhen_report: dict[str, object] | None = None,
) -> str:
    try:
        from .science_core import moderate_round as science_moderate
    except ImportError:
        from science_core import moderate_round as science_moderate
    return science_moderate(project_id, round_name, proponent_position, opponent_questions, yanzhen_report)


def summarize_positions(
    proponent_position: str = "",
    opponent_questions: list[dict[str, object]] | None = None,
    yanzhen_report: dict[str, object] | None = None,
) -> str:
    try:
        from .science_core import summarize_positions as science_summary
    except ImportError:
        from science_core import summarize_positions as science_summary
    return science_summary(proponent_position, opponent_questions, yanzhen_report)


def extract_emergent_method(debate_report: dict[str, object] | str) -> str:
    try:
        from .science_core import extract_emergent_method as science_extract_method
    except ImportError:
        from science_core import extract_emergent_method as science_extract_method
    return science_extract_method(debate_report)


def run_socratic_hypothesis_debate(
    project_id: str,
    hypothesis_id: str = "",
    hypothesis: str = "",
    max_rounds: int = 5,
    proponent_model_family: str = "qwen-max",
    opponent_model_family: str = "qwen-max",
    judge_model_family: str = "qwen-deep-research",
    verifier_model_family: str = "qwen-deep-research",
    shifted_conditions: list[object] | None = None,
    auto_literature_supplement: bool = True,
    supplement_providers: list[str] | None = None,
) -> str:
    try:
        from .science_core import run_socratic_hypothesis_debate as science_debate
    except ImportError:
        from science_core import run_socratic_hypothesis_debate as science_debate
    return science_debate(
        project_id,
        hypothesis_id,
        hypothesis,
        max_rounds,
        proponent_model_family,
        opponent_model_family,
        judge_model_family,
        verifier_model_family,
        shifted_conditions,
        auto_literature_supplement,
        supplement_providers,
    )


def export_research_plan(project_id: str) -> str:
    try:
        from .science_core import export_research_plan as science_export
    except ImportError:
        from science_core import export_research_plan as science_export
    return science_export(project_id)


BASIC_TOOLS = [
    {
        "name": "bash",
        "description": "Run a shell command in the workspace.",
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The shell command to run.",
                },
                "run_in_background": {
                    "type": "boolean",
                    "description": "Run slow commands asynchronously and notify later.",
                },
                "cwd": {
                    "type": "string",
                    "description": "Optional workspace-relative working directory.",
                },
            },
            "required": ["command"],
        },
    },
    {
        "name": "read_file",
        "description": (
            "Read a UTF-8 text file from the workspace. Files under v8/tool_results "
            "are returned as bounded previews only; prefer the original tool/search id "
            "instead of recursively reading tool result artifacts."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Workspace-relative path."},
                "limit": {
                    "type": "integer",
                    "description": "Optional maximum number of lines to read.",
                },
                "cwd": {
                    "type": "string",
                    "description": "Optional workspace-relative working directory.",
                },
            },
            "required": ["path"],
        },
    },
    {
        "name": "write_file",
        "description": "Create or overwrite a UTF-8 text file in the workspace.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Workspace-relative path."},
                "content": {"type": "string", "description": "New file content."},
                "cwd": {
                    "type": "string",
                    "description": "Optional workspace-relative working directory.",
                },
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "edit_file",
        "description": "Replace the first exact occurrence of text in a workspace file.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Workspace-relative path."},
                "old_text": {"type": "string", "description": "Text to replace."},
                "new_text": {"type": "string", "description": "Replacement text."},
                "cwd": {
                    "type": "string",
                    "description": "Optional workspace-relative working directory.",
                },
            },
            "required": ["path", "old_text", "new_text"],
        },
    },
    {
        "name": "glob",
        "description": "Find workspace files using a glob pattern.",
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "Glob pattern, for example '**/*.py'.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of paths to return.",
                },
                "cwd": {
                    "type": "string",
                    "description": "Optional workspace-relative working directory.",
                },
            },
            "required": ["pattern"],
        },
    },
]

TODO_TOOL = {
    "name": "todo_write",
    "description": "Replace the current session todo list with lightweight planning items.",
    "input_schema": {
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "description": "Todo items with content, status, priority, and optional id.",
                "items": {
                    "type": "object",
                    "properties": {
                        "content": {"type": "string", "description": "Todo text."},
                        "status": {
                            "type": "string",
                            "description": "pending, in_progress, or completed.",
                        },
                        "priority": {
                            "type": "string",
                            "description": "low, medium, or high.",
                        },
                        "id": {"type": "string", "description": "Optional stable id."},
                    },
                    "required": ["content"],
                },
            }
        },
        "required": ["items"],
    },
}

TASK_TOOL = {
    "name": "task",
    "description": (
        "Delegate a one-shot subtask to an isolated sub-agent. "
        "Use this for investigation or analysis that can return a final summary."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "description": {
                "type": "string",
                "description": "The subtask goal and expected deliverable.",
            },
            "run_in_background": {
                "type": "boolean",
                "description": "Run the sub-agent asynchronously and notify later.",
            }
        },
        "required": ["description"],
    },
}

LOAD_SKILL_TOOL = {
    "name": "load_skill",
    "description": "Load the full instructions for a skill listed in the system prompt catalog.",
    "input_schema": {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Skill name to load."},
        },
        "required": ["name"],
    },
}

COMPACT_TOOL = {
    "name": "compact",
    "description": (
        "Request context compaction when the conversation history is getting too large. "
        "Use focus to preserve the most important topic."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "focus": {
                "type": "string",
                "description": "Optional area that the summary should preserve.",
            }
        },
        "required": [],
    },
}

TASK_TOOLS = [
    {
        "name": "create_task",
        "description": "Create a persistent DAG task with optional dependencies.",
        "input_schema": {
            "type": "object",
            "properties": {
                "subject": {"type": "string", "description": "Short task title."},
                "description": {"type": "string", "description": "Detailed task context."},
                "blockedBy": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Task ids that must be completed first.",
                },
            },
            "required": ["subject", "description"],
        },
    },
    {
        "name": "list_tasks",
        "description": "List persistent tasks and their DAG state.",
        "input_schema": {
            "type": "object",
            "properties": {
                "include_completed": {
                    "type": "boolean",
                    "description": "Whether completed tasks should be included.",
                }
            },
            "required": [],
        },
    },
    {
        "name": "get_task",
        "description": "Read one persistent task by id.",
        "input_schema": {
            "type": "object",
            "properties": {"task_id": {"type": "string", "description": "Task id."}},
            "required": ["task_id"],
        },
    },
    {
        "name": "claim_task",
        "description": "Claim a pending task if all dependencies are completed.",
        "input_schema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "Task id."},
                "owner": {"type": "string", "description": "Agent or worker name."},
            },
            "required": ["task_id"],
        },
    },
    {
        "name": "complete_task",
        "description": "Mark a task completed and report newly unblocked downstream tasks.",
        "input_schema": {
            "type": "object",
            "properties": {"task_id": {"type": "string", "description": "Task id."}},
            "required": ["task_id"],
        },
    },
]




MCP_TOOLS = [
    {
        "name": "connect_mcp",
        "description": "Connect a mock MCP server and expose its tools dynamically.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Server name, for example docs, memory, or any custom echo server.",
                }
            },
            "required": ["name"],
        },
    }
]

CRON_TOOLS = [
    {
        "name": "schedule_cron",
        "description": "Schedule a prompt to be delivered by a five-field cron expression.",
        "input_schema": {
            "type": "object",
            "properties": {
                "cron": {
                    "type": "string",
                    "description": "Five-field cron expression: minute hour day month weekday.",
                },
                "prompt": {
                    "type": "string",
                    "description": "Prompt to inject when the schedule fires.",
                },
                "recurring": {
                    "type": "boolean",
                    "description": "Whether the job repeats. Defaults to true.",
                },
                "durable": {
                    "type": "boolean",
                    "description": "Persist to disk across process restarts. Defaults to true.",
                },
            },
            "required": ["cron", "prompt"],
        },
    },
    {
        "name": "list_crons",
        "description": "List scheduled cron jobs.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "cancel_cron",
        "description": "Cancel a scheduled cron job by id.",
        "input_schema": {
            "type": "object",
            "properties": {
                "job_id": {"type": "string", "description": "Cron job id."},
            },
            "required": ["job_id"],
        },
    },
]

SCIENCE_TOOLS = [
    {
        "name": "create_research_project",
        "description": "Create a persistent AI-for-Science research project.",
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Project title."},
                "domain": {"type": "string", "description": "Scientific domain."},
                "objective": {"type": "string", "description": "Research objective."},
                "strategic_need": {"type": "string", "description": "Optional strategic or application need."},
                "research_brief": {"type": "string", "description": "Complete original user task, preserved verbatim as the authoritative downstream specification. The runtime injects the current user prompt when omitted."},
                "force_new_project": {"type": "boolean", "description": "Explicitly confirm a separate project when this conversation already has an active project."},
            },
            "required": ["title", "domain", "objective"],
        },
    },
    {
        "name": "decompose_research_objective",
        "description": "Manual/setup-only Boxue Decomposer gate: use 2-4 bounded LLM batches, each returning 2-3 source-grounded SHs, then retain up to 6 validated, non-duplicate SHs. The LLM may propose a testable multi-SH combination; it is retained only after component-ID and integration-test validation. Local audits may reject invalid items but never create top-up SHs. For create-and-run or bare python -m v8.main science topics, do not call this directly after create_research_project; call run_autogen_groupchat instead, because GroupChat owns decomposition as its first internal stage.",
        "input_schema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "Science project id."},
                "max_subhypotheses": {"type": "integer", "minimum": 1, "maximum": 6, "description": "Maximum independently testable sub-hypotheses; the LLM may return any smaller valid count, default 6."},
                "use_llm": {"type": "boolean", "description": "Use Qwen JSON decomposition when configured; otherwise use a conservative heuristic fallback."},
            },
            "required": ["project_id"],
        },
    },
    {
        "name": "set_research_brief",
        "description": "Attach the complete original task instructions verbatim to an existing project, optionally then rerun decomposition so retrieval and gap discovery use the restored constraints.",
        "input_schema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "Science project id."},
                "research_brief": {"type": "string", "description": "Complete original user task; do not summarize or omit constraints."},
                "redecompose": {"type": "boolean", "description": "Immediately regenerate the decomposition from the restored brief."},
                "use_llm": {"type": "boolean", "description": "Use Qwen JSON decomposition when configured."},
            },
            "required": ["project_id", "research_brief"],
        },
    },
    {
        "name": "list_research_projects",
        "description": "List persistent AI-for-Science research projects.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "get_research_project",
        "description": "Read one AI-for-Science research project by id.",
        "input_schema": {
            "type": "object",
            "properties": {"project_id": {"type": "string", "description": "Science project id."}},
            "required": ["project_id"],
        },
    },
    {
        "name": "list_science_agents",
        "description": "List the Qwen-Zhikan science specialist agent roles.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "get_science_agent_prompt",
        "description": "Get a concise role prompt for a Qwen-Zhikan science agent.",
        "input_schema": {
            "type": "object",
            "properties": {"agent": {"type": "string", "description": "Agent name such as boxue, zhizhi, tanxi."}},
            "required": ["agent"],
        },
    },
    {
        "name": "list_literature_providers",
        "description": "List stable PaperGraph literature provider connectors: openalex, semantic_scholar, arxiv, biorxiv, chemrxiv, medrxiv, and pubmed.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "list_natural_science_disciplines",
        "description": "List the natural-science, health, and engineering discovery taxonomy and its provider-native mapping metadata. Humanities and social sciences are excluded.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "resolve_natural_science_discipline_taxonomy",
        "description": "Resolve a natural-science domain to auditable OpenAlex/arXiv/PubMed discovery filters without contacting any provider. The result is candidate-discovery metadata, never an evidence assessment.",
        "input_schema": {
            "type": "object",
            "properties": {
                "domain": {"type": "string", "description": "Declared scientific domain or project research context."},
                "query": {"type": "string", "description": "Optional focused retrieval query used only to disambiguate the domain."},
            },
            "required": ["domain"],
        },
    },
    {
        "name": "literature_provider_doctor",
        "description": "Run an offline literature-provider readiness diagnostic. It reports capability contracts, configuration presence, run budgets, and cooldown state without exposing credentials or sending a network query.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "literature_provider_smoke",
        "description": "Check one literature provider. The default is an offline contract/query check; set live=true only for an explicit one-result operational request. A smoke result is never scientific evidence.",
        "input_schema": {
            "type": "object",
            "properties": {
                "provider": {"type": "string", "description": "Provider name, such as openalex or pubmed."},
                "query": {"type": "string", "description": "Optional English smoke query."},
                "live": {"type": "boolean", "description": "False by default. True sends one provider request."},
            },
            "required": [],
        },
    },
    {
        "name": "document_conversion_doctor",
        "description": "Run an offline MarkItDown document-conversion readiness diagnostic. It reports allowlisted format contracts, dependency availability, non-secret OCR configuration status, and safety limits without converting a document or contacting a remote URL.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "explore_domain_subspaces",
        "description": "Domain Subspace Explorer (DSE): explicit background-map tool for user-requested subspace selection. Do not use for bare python -m v8.main science briefs or create-and-run AI Scientist workflows before run_autogen_groupchat; GroupChat owns decomposition and SH-local retrieval. When used as an exceptional background-only map, set allow_ad_hoc_discovery=true and provide ad_hoc_reason.",
        "input_schema": {
            "type": "object",
            "properties": {
                "domain": {"type": "string", "description": "Broad research domain to map before ZhiZhi retrieval."},
                "max_subspaces": {"type": "integer", "description": "Maximum substantive subspaces to generate, default 12."},
                "probe_depth": {"type": "integer", "description": "Seed-probe result count per subspace, default 5."},
                "use_llm": {"type": "boolean", "description": "Use Qwen/LLM to generate domain subspaces when available."},
                "providers": {"type": "array", "items": {"type": "string"}, "description": "Probe providers: openalex, semantic_scholar, arxiv, biorxiv, chemrxiv, medrxiv, pubmed."},
                "user_hints": {"type": "array", "items": {"type": "string"}, "description": "Optional user-supplied subspace hints or priorities."},
                "allow_ad_hoc_discovery": {"type": "boolean", "description": "Explicitly allow this as a background-only map outside canonical GroupChat. Requires ad_hoc_reason and cannot produce direct evidence."},
                "ad_hoc_reason": {"type": "string", "description": "Concrete audit reason for exceptional background-only domain mapping."},
            },
            "required": ["domain"],
        },
    },
    {
        "name": "search_literature",
        "description": "Search live literature providers for standalone work. For bare python -m v8.main science briefs, do not call this before run_autogen_groupchat; create the project and run GroupChat so retrieval is SH-local. After a project has decomposed sub-hypotheses, this generic tool is blocked: use run_zhizhi_subhypothesis_analysis. A documented ad-hoc exception is background-only and cannot become direct evidence. Results are ranked by text relevance, recency, field-normalized citation impact, journal quartile/venue quality, and quality gates.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Literature search query."},
                "providers": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional providers: openalex, semantic_scholar, arxiv, biorxiv, chemrxiv, medrxiv, pubmed.",
                },
                "max_results": {"type": "integer", "description": "Maximum provider result blocks."},
                "domain": {"type": "string", "description": "Optional declared natural-science domain used to compile provider-native candidate-discovery filters."},
                "allow_ad_hoc_discovery": {"type": "boolean", "description": "Only after decomposition: explicitly allow a background-only project map. Requires ad_hoc_reason and never permits direct-evidence import."},
                "ad_hoc_reason": {"type": "string", "description": "Concrete audit reason for an exceptional background-only discovery search."},
            },
            "required": ["query"],
        },
    },
    {
        "name": "search_literature_stratified",
        "description": "Run a standalone five-level cascade literature search. For bare python -m v8.main science briefs, do not call this before run_autogen_groupchat; GroupChat owns decomposition and scoped retrieval. After project decomposition use run_zhizhi_subhypothesis_analysis instead; a documented ad-hoc exception is background-only, never direct evidence. Results are deduplicated and each has stratified_layer plus _why_selected.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Literature search query."},
                "providers": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional providers: openalex, semantic_scholar, arxiv, biorxiv, chemrxiv, medrxiv, pubmed.",
                },
                "max_results": {"type": "integer", "description": "Total stratified result budget, default 15."},
                "domain": {"type": "string", "description": "Optional broad research domain. When provided, the search expands into known sub-branches and applies a pre-import domain relevance gate."},
                "focus_branches": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional user-confirmed or manually supplied sub-branches to prioritize before generic LLM/heuristic expansion.",
                },
                "use_llm": {"type": "boolean", "description": "Use Qwen to generate domain-agnostic sub-branch queries for any scientific field."},
                "allow_ad_hoc_discovery": {"type": "boolean", "description": "Only after decomposition: explicitly allow a background-only project map. Requires ad_hoc_reason."},
                "ad_hoc_reason": {"type": "string", "description": "Concrete audit reason for an exceptional background-only discovery search."},
            },
            "required": ["query"],
        },
    },
    {
        "name": "search_papers",
        "description": "Standalone retrieval alias. For bare python -m v8.main science briefs, do not call this before run_autogen_groupchat. It is blocked after project decomposition so it cannot bypass sub-hypothesis causal contracts; use run_zhizhi_subhypothesis_analysis instead.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Keyword combination or research topic."},
                "databases": {"type": "array", "items": {"type": "string"}, "description": "Database names, e.g. Semantic Scholar, OpenAlex, Crossref, arXiv, DBLP, OpenReview, Web of Science."},
                "max_results": {"type": "integer", "description": "Maximum results to retrieve."},
                "years": {"type": "string", "description": "Time window, e.g. last 15 years."},
                "allow_ad_hoc_discovery": {"type": "boolean", "description": "Only after decomposition: explicitly allow a background-only project map. Requires ad_hoc_reason."},
                "ad_hoc_reason": {"type": "string", "description": "Concrete audit reason for an exceptional background-only discovery search."},
            },
            "required": ["query"],
        },
    },
    {
        "name": "search_papers_stratified",
        "description": "Standalone systematic mapping. For bare python -m v8.main science briefs, do not call this before run_autogen_groupchat. It is blocked after project decomposition so it cannot bypass sub-hypothesis causal contracts; use run_zhizhi_subhypothesis_analysis instead.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Keyword combination or research topic."},
                "databases": {"type": "array", "items": {"type": "string"}, "description": "Database names, e.g. Semantic Scholar, OpenAlex, Crossref, arXiv, DBLP, OpenReview, Web of Science."},
                "max_results": {"type": "integer", "description": "Total stratified result budget."},
                "years": {"type": "string", "description": "Time window hint, e.g. last 15 years."},
                "domain": {"type": "string", "description": "Broad domain for subfield query expansion and coverage self-check, e.g. Autonomous Grid Control."},
                "focus_branches": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional user-selected priority branches, e.g. demand response, building energy management, MARL.",
                },
                "use_llm": {"type": "boolean", "description": "Use Qwen to generate field-wide subqueries instead of generic fallback templates."},
                "allow_ad_hoc_discovery": {"type": "boolean", "description": "Only after decomposition: explicitly allow a background-only project map. Requires ad_hoc_reason."},
                "ad_hoc_reason": {"type": "string", "description": "Concrete audit reason for an exceptional background-only discovery search."},
            },
            "required": ["query"],
        },
    },
    {
        "name": "extract_structured_info",
        "description": "ZhiZhi action for extracting method, scenario, benchmark, contribution/conclusion, limitation, and evidence claim types from paper text.",
        "input_schema": {
            "type": "object",
            "properties": {
                "paper_content": {"type": "string", "description": "Abstract, conclusion, or full paper text."},
                "fields": {"type": "array", "items": {"type": "string"}, "description": "Optional fields to extract."},
                "use_llm": {"type": "boolean", "description": "Use Qwen JSON extraction before heuristic fallback."},
            },
            "required": ["paper_content"],
        },
    },
    {
        "name": "select_literature_result",
        "description": "Select the best cached literature result by relevance_score, using text relevance plus recency and citation-impact components. Use this after search_literature before importing.",
        "input_schema": {
            "type": "object",
            "properties": {
                "search_id": {"type": "string", "description": "search_id returned by search_literature."},
                "query": {"type": "string", "description": "Optional query override for re-ranking cached results."},
                "top_k": {"type": "integer", "description": "How many ranked candidates to show."},
                "use_llm": {"type": "boolean", "description": "Use a Qwen judge to select among top candidates after rule ranking."},
            },
            "required": ["search_id"],
        },
    },
    {
        "name": "expand_literature_graph",
        "description": "DeepSurvey-style citation graph expansion from one cached seed paper through Semantic Scholar references/citations, then rank with PaperGraph quality gates. At depth two, it prefers seeds from different heuristic communities and may run a bounded bridge search only when result count or community coverage is sparse. Tries arXiv IDs with and without version suffix. If graph edges are empty, optionally falls back to Semantic Scholar keyword expansion and marks fallback_used.",
        "input_schema": {
            "type": "object",
            "properties": {
                "search_id": {"type": "string", "description": "Seed search_id returned by search_literature or graph expansion."},
                "result_index": {"type": "integer", "description": "Seed result_index to expand from."},
                "query": {"type": "string", "description": "Optional topic query for ranking expanded papers."},
                "direction": {"type": "string", "description": "references | citations | both."},
                "max_results": {"type": "integer", "description": "Maximum expanded candidates to keep."},
                "use_llm": {"type": "boolean", "description": "Use Qwen judge on the top expanded candidates after rule ranking."},
                "depth": {"type": "integer", "description": "Citation graph depth: 1 for direct neighbors, 2 to expand a few high-quality first-layer papers."},
                "second_layer_top_k": {"type": "integer", "description": "When depth=2, expand only this many strongest first-layer papers to control graph growth."},
                "allow_fallback": {"type": "boolean", "description": "When true, use keyword fallback if citation edges are empty or the seed is not indexed. Set false for strict citation-graph verification."},
            },
            "required": ["search_id"],
        },
    },
    {
        "name": "search_cross_community_bridges",
        "description": "Run a bounded Semantic Scholar bridge search for papers containing both clinical and molecular/mechanistic evidence. Saves candidates for review/import but never imports them automatically.",
        "input_schema": {
            "type": "object",
            "properties": {
                "search_id": {"type": "string", "description": "Source search_id whose query supplies bridge terms."},
                "target_communities": {"type": "array", "items": {"type": "string"}, "description": "Optional observed communities to record in the bridge-search provenance."},
                "max_results": {"type": "integer", "description": "Maximum bridge candidates, bounded by SCIENCE_BRIDGE_SEARCH_MAX_RESULTS."},
            },
            "required": ["search_id"],
        },
    },
    {
        "name": "build_literature_relation_graph",
        "description": "Build a mechanism lineage graph from cached search or graph-expansion results. Produces citation/relevance edges, mechanism clusters, PageRank centrality, and optional Louvain structural communities with bridge-paper recommendations.",
        "input_schema": {
            "type": "object",
            "properties": {
                "search_id": {"type": "string", "description": "search_id or graph_search_id returned by search_literature/expand_literature_graph."},
                "query": {"type": "string", "description": "Optional topic query used for mechanism term extraction."},
                "max_nodes": {"type": "integer", "description": "Maximum papers to include in the graph."},
                "min_quality": {"type": "number", "description": "Optional publication_quality_score floor; use 0.55+ to exclude weak/noisy papers."},
                "max_clusters": {"type": "integer", "description": "Maximum mechanism clusters after merging singleton clusters; default 8."},
                "run_louvain": {"type": "boolean", "description": "Run weighted Louvain detection over real citation-graph edges; default true."},
                "louvain_resolution": {"type": "number", "description": "Optional Louvain resolution in [0.1, 5.0]; higher values produce smaller communities."},
            },
            "required": ["search_id"],
        },
    },
    {
        "name": "run_autogen_groupchat",
        "description": "Run the complete V3 AutoGen research flow. The executor resolves one canonical run configuration, generates bounded ResearchQuestionContractV3 batches, executes each contract's internal evidence-slot retrieval profile, then runs source-bound TanXi analysis and type-directed downstream review. Returns a compact autogen_run_summary_v1 result; full artifacts remain persisted and are returned by reference.",
        "input_schema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "Science project id."},
                "goal": {"type": "string", "description": "Research goal/query for this AutoGen run."},
                "groupchat_id": {"type": "string", "description": "Optional persisted groupchat_id when resuming the current project."},
                "restart_from_decomposition": {"type": "boolean", "description": "Archive the prior SH generation, retain canonical papers/full texts, clear stale SH evidence bindings, and rebuild all SHs from the original objective. Default false."},
            },
            "required": ["project_id"],
        },
    },
    {
        "name": "list_autogen_groupchats",
        "description": "List AutoGen GroupChat specs stored in v8/.science/autogen_groupchats.",
        "input_schema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "Optional project filter."},
            },
        },
    },
    {
        "name": "get_autogen_run",
        "description": "Read a stored AutoGen GroupChat run by run_id. Returns a compact summary by default; set include_details=true only for explicit full-run audit because detailed records may be many megabytes.",
        "input_schema": {
            "type": "object",
            "properties": {
                "run_id": {"type": "string", "description": "AutoGen run id returned by run_autogen_groupchat."},
                "include_details": {"type": "boolean", "description": "Return the complete persisted run record instead of the default compact summary. Default false."},
            },
            "required": ["run_id"],
        },
    },
    {
        "name": "build_knowledge_map",
        "description": "ZhiZhi action for building a benchmark-aware method-scenario-benchmark knowledge map from project PaperGraph evidence. Do not call before run_autogen_groupchat in the canonical CLI science workflow; GroupChat first creates SH-local evidence.",
        "input_schema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "Science project id."},
                "dimension": {"type": "string", "description": "Usually method-scenario-benchmark."},
            },
            "required": ["project_id"],
        },
    },
    {
        "name": "build_louvain_community_knowledge_maps",
        "description": "Map a persisted Louvain relation graph onto imported PaperGraph evidence, build one evidence-bounded knowledge map per community, and identify communities requiring representative-paper import.",
        "input_schema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "Science project id."},
                "relation_graph_id": {"type": "string", "description": "Optional persisted relation_graph_id; defaults to the project's latest Louvain relation graph."},
                "min_records": {"type": "integer", "description": "Minimum imported evidence records before a community can produce gap candidates; default is the configured value."},
            },
            "required": ["project_id"],
        },
    },
    {
        "name": "add_literature_evidence",
        "description": "Add one structured PaperGraph evidence record to a science project.",
        "input_schema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "Science project id."},
                "title": {"type": "string", "description": "Paper title."},
                "citation": {"type": "string", "description": "Citation or paper identifier."},
                "method": {"type": "string", "description": "Core method category."},
                "scenario": {"type": "string", "description": "Application scenario."},
                "benchmark": {"type": "string", "description": "Dataset or benchmark."},
                "contribution": {"type": "string", "description": "Core contribution."},
                "limitation": {"type": "string", "description": "Documented limitation."},
                "url": {"type": "string", "description": "Optional URL."},
            },
            "required": ["project_id", "title", "citation", "method", "scenario", "benchmark", "contribution", "limitation"],
        },
    },
    {
        "name": "import_literature_text",
        "description": "Import a paper from pasted abstract/full text into PaperGraph and auto-extract evidence fields. In the canonical science workflow, call this only after create_research_project and a completed run_autogen_groupchat; GroupChat owns SH decomposition and retrieval ordering.",
        "input_schema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "Science project id."},
                "title": {"type": "string", "description": "Paper title."},
                "citation": {"type": "string", "description": "Citation or paper identifier."},
                "text": {"type": "string", "description": "Abstract, conclusion, or full text."},
                "provider": {"type": "string", "description": "Source provider."},
                "source_type": {"type": "string", "description": "abstract | conclusion | full_text | metadata."},
                "url": {"type": "string", "description": "Optional URL."},
                "doi": {"type": "string", "description": "Optional DOI."},
                "arxiv_id": {"type": "string", "description": "Optional arXiv id."},
                "semantic_scholar_id": {"type": "string", "description": "Optional Semantic Scholar id."},
                "authors": {"type": "array", "items": {"type": "string"}, "description": "Optional authors."},
                "year": {"type": "string", "description": "Optional publication year."},
                "venue": {"type": "string", "description": "Optional venue."},
                "use_llm": {"type": "boolean", "description": "Use Qwen/LLM JSON extraction before heuristic fallback."},
            },
            "required": ["project_id", "text"],
        },
    },
    {
        "name": "import_literature_file",
        "description": "Import a workspace text/PDF file into PaperGraph. In the canonical science workflow, call this only after create_research_project and a completed run_autogen_groupchat; GroupChat owns SH decomposition and retrieval ordering. PDF import uses structure-aware section selection, causal-keyword evidence, optional table extraction, and an extraction coverage report for TanXi/Socrates.",
        "input_schema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "Science project id."},
                "path": {"type": "string", "description": "Workspace-relative literature text/PDF path."},
                "title": {"type": "string", "description": "Optional title."},
                "citation": {"type": "string", "description": "Optional citation."},
                "provider": {"type": "string", "description": "Optional provider."},
                "source_type": {"type": "string", "description": "Optional source type."},
                "use_llm": {"type": "boolean", "description": "Use Qwen/LLM JSON extraction after text/PDF extraction."},
                "sub_hypothesis": {"type": "string", "description": "Optional exact, persisted V3 sub-hypothesis identifier for an explicit evidence binding."},
            },
            "required": ["project_id", "path"],
        },
    },
    {
        "name": "import_literature_search_result",
        "description": "Import one real paper from a cached search result. In the canonical science workflow, call this only after create_research_project and a completed run_autogen_groupchat; GroupChat owns SH decomposition and retrieval ordering. In a decomposed project, the cached search must prove a matching sub-hypothesis plus causal alignment contract; undocumented project-wide searches are rejected. Explicit ad-hoc discovery imports remain background-only and cannot supply direct evidence.",
        "input_schema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "Science project id."},
                "search_id": {"type": "string", "description": "search_id returned by search_literature."},
                "result_index": {"type": "integer", "description": "Zero-based result_index returned by search_literature."},
                "use_llm": {"type": "boolean", "description": "Use Qwen/LLM extraction on the result abstract before importing."},
                "force_import": {"type": "boolean", "description": "Human-reviewed override for a domain-gate rejection; record remains marked for review."},
            },
            "required": ["project_id", "search_id"],
        },
    },
    {
        "name": "extract_paper_keynote",
        "description": "Extract and store a DeepSurvey-style structured keynote from an imported paper, cached search result, or supplied text.",
        "input_schema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "Science project id."},
                "paper_id": {"type": "string", "description": "Optional PaperGraph paper_id."},
                "search_id": {"type": "string", "description": "Optional cached search_id."},
                "result_index": {"type": "integer", "description": "Search result index when search_id is provided."},
                "text": {"type": "string", "description": "Optional raw paper text or abstract."},
                "use_llm": {"type": "boolean", "description": "Use Qwen to extract a full keynote before heuristic fallback."},
            },
            "required": ["project_id"],
        },
    },
    {
        "name": "import_papergraph_record",
        "description": "Import a fully structured PaperGraph record with credibility scoring and citation uniqueness check. In the canonical science workflow, call this only after create_research_project and a completed run_autogen_groupchat; GroupChat owns SH decomposition and retrieval ordering.",
        "input_schema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "Science project id."},
                "title": {"type": "string", "description": "Paper title."},
                "citation": {"type": "string", "description": "Citation or paper identifier."},
                "authors": {"type": "array", "items": {"type": "string"}},
                "year": {"type": "string"},
                "venue": {"type": "string"},
                "provider": {"type": "string"},
                "source_type": {"type": "string"},
                "doi": {"type": "string"},
                "arxiv_id": {"type": "string"},
                "semantic_scholar_id": {"type": "string"},
                "url": {"type": "string"},
                "abstract": {"type": "string"},
                "full_text_excerpt": {"type": "string"},
                "conclusion": {"type": "string"},
                "strengths": {"type": "array", "items": {"type": "string"}},
                "improvements": {"type": "array", "items": {"type": "string"}},
                "method": {"type": "string"},
                "scenario": {"type": "string"},
                "benchmark": {"type": "string"},
                "contribution": {"type": "string"},
                "limitation": {"type": "string"},
            },
            "required": ["project_id", "title", "citation"],
        },
    },
    {
        "name": "list_papergraph_records",
        "description": "List imported PaperGraph records for a science project.",
        "input_schema": {
            "type": "object",
            "properties": {"project_id": {"type": "string", "description": "Science project id."}},
            "required": ["project_id"],
        },
    },
    {
        "name": "verify_citation_uniqueness",
        "description": "Check whether a citation/DOI/arXiv/title key is already present in a project's PaperGraph.",
        "input_schema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "Science project id."},
                "title": {"type": "string"},
                "citation": {"type": "string"},
                "doi": {"type": "string"},
                "arxiv_id": {"type": "string"},
                "semantic_scholar_id": {"type": "string"},
                "url": {"type": "string"},
            },
            "required": ["project_id"],
        },
    },
    {
        "name": "assess_novelty",
        "description": "ZhiZhi action for assessing a knowledge gap across academic novelty, application value, and implementation feasibility.",
        "input_schema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "Science project id."},
                "gap": {"description": "Gap object or gap description string."},
                "dimensions": {"type": "array", "items": {"type": "string"}, "description": "Assessment dimensions."},
            },
            "required": ["project_id", "gap"],
        },
    },
    {
        "name": "verify_uniqueness",
        "description": "ZhiZhi action for checking whether a proposed research idea overlaps with imported project literature, optionally with live literature search.",
        "input_schema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "Science project id."},
                "idea": {"type": "string", "description": "Research idea or gap to verify."},
                "precision": {"type": "string", "description": "high | medium."},
                "live_search": {"type": "boolean", "description": "If true, also run live literature search."},
                "providers": {"type": "array", "items": {"type": "string"}, "description": "Optional providers for live search."},
            },
            "required": ["project_id", "idea"],
        },
    },
    {
        "name": "run_zhizhi_subhypothesis_analysis",
        "description": "Run ZhiZhi retrieval separately for each decomposed sub-hypothesis, enforce its P0-P4 evidence window, and mark a branch evidence-insufficient instead of filling a missing P0 preprint with older literature.",
        "input_schema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "Science project id."},
                "sub_hypothesis_ids": {"type": "array", "items": {"type": "string"}, "description": "Optional SH identifiers; default runs all decomposed branches."},
            },
            "required": ["project_id"],
        },
    },
    {
        "name": "parse_literature_text",
        "description": "Parse pasted literature text into abstract, conclusion, strengths, improvements, method, scenario, benchmark, contribution, and limitation.",
        "input_schema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Literature text to parse."},
                "use_llm": {"type": "boolean", "description": "Use Qwen/LLM JSON extraction before heuristic fallback."},
            },
            "required": ["text"],
        },
    },
    {
        "name": "build_coverage_matrix",
        "description": "Build method-scenario coverage matrix from project evidence.",
        "input_schema": {
            "type": "object",
            "properties": {"project_id": {"type": "string", "description": "Science project id."}},
            "required": ["project_id"],
        },
    },
    {
        "name": "detect_knowledge_gaps",
        "description": "Detect candidate knowledge gaps from a project's PaperGraph coverage matrix plus PDF/full-text gap_signals, then enrich/rank them with TanXi-style density holes, migration pairs, suspended problems, and strategic alignment. Do not call before run_autogen_groupchat in the canonical CLI science workflow; TanXi must follow SH-local evidence retrieval.",
        "input_schema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "Science project id."},
                "max_gaps": {"type": "integer", "description": "Maximum gaps to return."},
            },
            "required": ["project_id"],
        },
    },
    {
        "name": "run_tanxi_gap_exploration",
        "description": "Run TanXi's source-bound, multi-type gap pipeline. It discovers candidates, assigns a scientific-gap type, audits source-span entailment, and routes each candidate to diagnostic repair, type-directed retrieval, or a qualified research package. Discovery never directly creates a hypothesis or a Socrates handoff.",
        "input_schema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "Science project id."},
                "target_domain": {"type": "string", "description": "Target research domain for density and strategic interpretation."},
                "strategic_domains": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional strategic domains, e.g. carbon neutrality, health, energy, food security, AI for Science.",
                },
                "max_gaps": {"type": "integer", "description": "Maximum ranked gaps to return."},
                "semantic_audit_mode": {
                    "type": "string",
                    "enum": ["deterministic", "llm_dual"],
                    "default": "deterministic",
                    "description": "Use deterministic source-span audit only, or a bounded positive/red-team LLM audit that may only judge supplied source spans.",
                },
            },
            "required": ["project_id"],
        },
    },
    {
        "name": "apply_gap_retrieval_assessment",
        "description": "Apply one bounded type-directed retrieval assessment to a TARGETED_RETRIEVAL v2 gap. Every cited source unit must already be bound and re-audited; this tool cannot promote an old gap state or an unbound search result.",
        "input_schema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "Science project id."},
                "gap_id": {"type": "string", "description": "Gap id from TanXi's current v2 candidate ledger."},
                "retrieval_assessment": {
                    "type": "object",
                    "description": "gap_retrieval_assessment_v2 with novelty_verdict, direct_resolution_found, design_ready, remaining_missing_axes, supporting_source_unit_ids, and retrieved_source_evidence_units.",
                },
            },
            "required": ["project_id", "gap_id", "retrieval_assessment"],
        },
    },
    {
        "name": "execute_research_question_retrieval_plan",
        "description": "Record one workflow-authorized ResearchQuestionContractV3 slot retrieval. It records task coverage and imported source ids only; empty results are diagnostics and cannot establish a scientific gap.",
        "input_schema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "Science project id."},
                "sub_hypothesis_id": {"type": "string", "description": "V3 research-question sub-hypothesis id."},
                "retrieval_results": {
                    "type": "array",
                    "items": {"type": "object"},
                    "description": "One record per V3 task: task_id, executed_query, and source_ids. Source ids must identify already imported documents.",
                },
            },
            "required": ["project_id", "sub_hypothesis_id"],
        },
    },
    {
        "name": "run_socrates_type_specific_review",
        "description": "Run Socrates' package-kind-specific review for a qualified research_package_v2. It checks the declared evidence roles and execution requirements but cannot promote a diagnostic or targeted-retrieval candidate.",
        "input_schema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "Science project id."},
                "gap_id": {"type": "string", "description": "Gap id with a current qualified research_package_v2."},
            },
            "required": ["project_id", "gap_id"],
        },
    },
    {
        "name": "build_research_evidence_graph_v3",
        "description": "Reserved for the V3 AutoGen GroupChat. Direct invocation returns a structured V3_GROUPCHAT_RESUME_REQUIRED response; TanXi alone builds the detached evidence graph from the retrieval ledger.",
        "input_schema": {
            "type": "object",
            "properties": {"project_id": {"type": "string", "description": "Science project id."}},
            "required": ["project_id"],
        },
    },
    {
        "name": "get_research_graph_view_v3",
        "description": "Read a contract-scoped, provenance-closed GraphView from the active Research Evidence Graph V3. By default it excludes derived inferences and never exposes an unscoped corpus traversal.",
        "input_schema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "Science project id."},
                "research_question_contract_id": {"type": "string", "description": "Optional V3 ResearchQuestionContract id. Empty returns the current full V3 projection."},
                "gap_type": {"type": "string", "description": "Optional typed-gap query context; it does not infer a new gap."},
                "required_scope_axes": {"type": "array", "items": {"type": "string"}, "description": "Optional scope axes whose observational coverage is reported."},
                "include_derived_inferences": {"type": "boolean", "description": "Include diagnostic-only derived inferences. Defaults to false and cannot make them primary evidence."},
            },
            "required": ["project_id"],
        },
    },
    {
        "name": "build_proposal_brief_v2",
        "description": "Build a frozen ProposalBriefV2 from a current, Socrates-reviewed research_package_v2. Non-causal packages retain their own type-specific design contract.",
        "input_schema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "Science project id."},
                "research_package_id": {"type": "string", "description": "Current qualified research_package_v2 id."},
            },
            "required": ["project_id", "research_package_id"],
        },
    },
    {
        "name": "write_research_proposal_v2",
        "description": "Write a structured, type-directed research proposal from ProposalBriefV2. Scientific motivation remains tied to the frozen assertion/span evidence bundle.",
        "input_schema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "Science project id."},
                "proposal_brief_id": {"type": "string", "description": "Current ProposalBriefV2 id."},
            },
            "required": ["project_id", "proposal_brief_id"],
        },
    },
    {
        "name": "audit_research_proposal_v2",
        "description": "Audit a Proposal V2 for frozen graph/package provenance, evidence-claim bindings, scope restrictions, and type-contract completeness.",
        "input_schema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "Science project id."},
                "proposal_id": {"type": "string", "description": "Current research_proposal_v2 id."},
            },
            "required": ["project_id", "proposal_id"],
        },
    },
    {
        "name": "export_research_proposal_v2",
        "description": "Export a current Proposal V2 only after its audit passes; emits Markdown and JSON with graph provenance.",
        "input_schema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "Science project id."},
                "proposal_id": {"type": "string", "description": "Audited research_proposal_v2 id."},
                "output_dir": {"type": "string", "description": "Optional export directory."},
            },
            "required": ["project_id", "proposal_id"],
        },
    },
    {
        "name": "generate_proposal_traceability_report_v3",
        "description": "Generate a traceability_report_v3 for the current evidence graph, typed gap landscape, retrieval coverage, packages, and any proposals. It does not require a primary package, proposal, or legacy hypothesis.",
        "input_schema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "Science project id."},
                "output_dir": {"type": "string", "description": "Optional report directory."},
            },
            "required": ["project_id"],
        },
    },
    {
        "name": "generate_traceability_report_v3",
        "description": "Generate traceability_report_v3 from the evidence graph and task graph regardless of whether any proposal is qualified. This is the canonical V3 reporting entrypoint.",
        "input_schema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "Science project id."},
                "output_dir": {"type": "string", "description": "Optional report directory."},
            },
            "required": ["project_id"],
        },
    },
    {
        "name": "generate_research_proposal_report_v3",
        "description": "Generate a research_proposal_report_v3 only when at least one current Proposal V2 has passed its provenance and type-contract audit.",
        "input_schema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "Science project id."},
                "output_dir": {"type": "string", "description": "Optional report directory."},
            },
            "required": ["project_id"],
        },
    },
    {
        "name": "run_zhizhi_near_pass_source_role_retrieval",
        "description": "Execute exactly one TanXi-approved near-pass source-role repair. Without retrieval_result it runs the bounded Zhizhi query; with retrieval_result it accepts only verified source units plus explicit input/mediator/outcome/comparison bindings, then queues the candidate for TanXi re-audit. It never promotes a candidate directly to Socrates.",
        "input_schema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "Science project id."},
                "candidate_identity": {"type": "string", "description": "Immutable candidate identity from TanXi near_pass_targeted_retrieval_tasks. Preferred selector."},
                "gap_id": {"type": "string", "description": "Canonical gap id for backwards-compatible selection; candidate_identity remains the stable audit key."},
                "retrieval_result": {"type": "object", "description": "Optional structured extraction with source_evidence_units (SOURCE_UNIT_VERIFIED), causal_role_bindings for input/mediator/outcome, and comparison."},
                "providers": {"type": "array", "items": {"type": "string"}, "description": "Optional literature providers for the bounded retrieval call."},
                "use_llm": {"type": "boolean", "description": "Use LLM extraction during the bounded Zhizhi retrieval call."},
            },
            "required": ["project_id"],
        },
    },
    {
        "name": "check_semantic_plausibility",
        "description": "Semantic gate between TanXi and MingLi: audit whether a method-scenario pair has a plausible data/modality/mechanism bridge before treating it as a scientific gap.",
        "input_schema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "Science project id."},
                "method": {"type": "string", "description": "Candidate method, technique, model, assay, or tool."},
                "scenario": {"type": "string", "description": "Candidate scientific scenario, application, system, disease, material, or task."},
                "gap": {"type": "object", "description": "Optional gap object for additional context."},
            },
            "required": ["project_id", "method", "scenario"],
        },
    },
    {
        "name": "evolve_domain_subspaces",
        "description": "Dynamic Subspace Evolution: update subspace metrics, detect fission/fusion/decline/emergent signals, and produce proposed subspace adjustments before MingLi hypothesis generation.",
        "input_schema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "Science project id."},
                "subspace_map_id": {"type": "string", "description": "Optional DSE subspace_map_id returned by explore_domain_subspaces."},
                "max_actions": {"type": "integer", "description": "Maximum proposed evolution actions to return."},
            },
            "required": ["project_id"],
        },
    },
    {
        "name": "build_temporal_knowledge_graph",
        "description": "Build a temporal knowledge graph from PaperGraph triples: method, scenario, benchmark, year, citations, lifecycle status, and hotspot predictions.",
        "input_schema": {
            "type": "object",
            "properties": {"project_id": {"type": "string", "description": "Science project id."}},
            "required": ["project_id"],
        },
    },
    {
        "name": "detect_structural_knowledge_gaps",
        "description": "Detect structural gaps in the PaperGraph concept topology: isolated/low-degree nodes, bottlenecks, and missing community bridges.",
        "input_schema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "Science project id."},
                "max_gaps": {"type": "integer", "description": "Maximum structural gaps to return."},
            },
            "required": ["project_id"],
        },
    },
    {
        "name": "find_structural_analogy_transfers",
        "description": "Find cross-domain transfer opportunities by encoding scenarios as problem-structure vectors and matching structurally similar but semantically distant scenarios.",
        "input_schema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "Science project id."},
                "target_scenario": {"type": "string", "description": "Optional scenario to search analogs for; empty scans all scenarios."},
                "threshold": {"type": "number", "description": "Minimum structural similarity, default 0.55."},
                "max_results": {"type": "integer", "description": "Maximum analogy transfers to return."},
            },
            "required": ["project_id"],
        },
    },
    {
        "name": "run_mingli_hypothesis_evolution",
        "description": "Agent 4 MingLi v1: generate seed hypotheses from validated gaps, run tournament selection plus mutation/crossover, score novelty/plausibility/grounding/testability/impact, and persist top hypotheses.",
        "input_schema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "Science project id."},
                "gap_ids": {"type": "array", "items": {"type": "string"}, "description": "Optional specific gap ids; omit to use top-ranked gaps."},
                "population_size": {"type": "integer", "description": "Initial hypothesis population size."},
                "generations": {"type": "integer", "description": "Tournament evolution generations."},
                "top_k": {"type": "integer", "description": "Number of final hypotheses to persist."},
                "use_llm": {"type": "boolean", "description": "Reserved for future LLM seed generation; v1 uses auditable templates."},
            },
            "required": ["project_id"],
        },
    },
    {
        "name": "domain_review_paper",
        "description": "Re-audit one imported PaperGraph record against the project's domain. Clear mismatches are retained for audit but marked inactive so knowledge maps and TanXi ignore them.",
        "input_schema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "Science project id."},
                "paper_id": {"type": "string", "description": "Imported PaperGraph paper_id."},
                "target_domain_profile": {"description": "Optional domain string or keyword list; defaults to the project domain."},
                "min_confidence": {"type": "number", "description": "Minimum target-anchor coverage for cross-field records; default 0.6."},
            },
            "required": ["project_id", "paper_id"],
        },
    },
    {
        "name": "reconcile_project_domain_reviews",
        "description": "Re-run domain review for inactive PaperGraph records and recover their original cached retrieval relevance when available. It can reactivate prior false negatives but keeps review-status records marked for audit.",
        "input_schema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "Science project id."},
                "target_domain_profile": {"type": ["array", "string"], "description": "Optional replacement domain profile."},
                "min_confidence": {"type": "number", "description": "Domain-review confidence threshold."},
                "include_active": {"type": "boolean", "description": "Also re-audit currently active records; defaults to inactive records only."},
            },
            "required": ["project_id"],
        },
    },
    {
        "name": "run_socrates_mechanism_enrichment",
        "description": "Socrates: repeatedly inspect PaperGraph evidence and run bounded, targeted ZhiZhi searches to resolve an incomplete mechanism contract. It returns INSUFFICIENT_EVIDENCE rather than inventing unresolved mechanism fields.",
        "input_schema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "Science project id."},
                "gap": {"description": "Optional TanXi gap object. Omit when using gap_id."},
                "gap_id": {"type": "string", "description": "Target TanXi knowledge gap id."},
                "mechanism_contract": {"description": "Optional incomplete mechanism draft. Fields without cited evidence are searched and remain unresolved if evidence is absent."},
                "domain": {"type": "string", "description": "Optional domain override for the targeted ZhiZhi query."},
                "providers": {"type": "array", "items": {"type": "string"}, "description": "Optional providers: openalex, semantic_scholar, arxiv, biorxiv, chemrxiv, medrxiv, pubmed."},
                "max_iterations": {"type": "integer", "description": "Maximum bounded enrichment iterations, default 3 and capped at 5."},
                "max_fields_per_iteration": {"type": "integer", "description": "Maximum unresolved mechanism fields to search in one iteration, default 2."},
                "max_results_per_query": {"type": "integer", "description": "Maximum ranked ZhiZhi candidates per field query, default 12."},
                "imports_per_query": {"type": "integer", "description": "Maximum papers imported per targeted query, default 2."},
                "use_llm": {"type": "boolean", "description": "Use LLM-assisted structured extraction for imported papers when available."},
            },
            "required": ["project_id"],
        },
    },
    {
        "name": "generate_idea",
        "description": "MingLi action: generate one gap-traceable research idea from a TanXi/ZhiZhi knowledge gap, with auditable lineage and preliminary scores.",
        "input_schema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "Science project id."},
                "gap": {"description": "Optional gap object or gap description. Omit when using gap_id."},
                "gap_id": {"type": "string", "description": "Specific TanXi/ZhiZhi knowledge gap id."},
                "style": {"type": "string", "description": "innovative or conservative."},
                "parent_hypothesis_id": {"type": "string", "description": "Optional parent id for tournament mutation lineage."},
                "use_llm": {"type": "boolean", "description": "Reserved flag for LLM-assisted generation; deterministic fallback remains auditable."},
            },
            "required": ["project_id"],
        },
    },
    {
        "name": "generate_research_report",
    "description": "Generate an English-only IEEE LaTeX report from a persisted frozen project snapshot. The default traceability profile is compact and auditable. The full_research_design profile additionally emits source-unit Evidence Cards, quantitative-anchor registry, Research Argument Graph, SH-deep-review chapters, formalization and experiment contracts, chapter-local writer/reviewer iterations, and configurable TeX/PDF QA. It never upgrades hypotheses or bridge evidence into validated findings.",
        "input_schema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "Science project id."},
                "report_id": {"type": "string", "description": "Optional stable report identifier; defaults to a snapshot-derived id."},
                "output_dir": {"type": "string", "description": "Optional output directory. Defaults to .science/reports/<project_id>/<report_id>."},
                "template_dir": {"type": "string", "description": "Optional IEEEtran template directory. Defaults to Conference-LaTeX-template_10-17-19."},
                "use_llm": {"type": "boolean", "description": "Optionally append source-constrained English narrative refinements. Deterministic tables and prose are always generated."},
                "max_narrative_retries": {"type": "integer", "description": "Maximum feedback-guided LLM narrative retries, from 0 to 2; default 2."},
                "report_profile": {"type": "string", "enum": ["traceability_report", "full_research_design"], "description": "traceability_report preserves the compact audit report. full_research_design adds evidence cards, argument graph, deep SH chapters, formalization/experiment contracts, and quality rubric."},
                "max_design_review_rounds": {"type": "integer", "description": "For full_research_design with use_llm=true: maximum independent reviewer passes per chapter, from 1 to 2; default 2."},
                "latex_engine_path": {"type": "string", "description": "Optional absolute path or command for pdflatex. It takes precedence over environment, template toolchain config, and PATH discovery."},
                "bibtex_path": {"type": "string", "description": "Optional absolute path or command for bibtex."},
                "pdf_renderer_path": {"type": "string", "description": "Optional absolute path or command for pdftoppm; PyMuPDF is used as a local fallback for preview rendering."},
                "compile_pdf": {"type": "boolean", "description": "Compile and statically QA the LaTeX bundle when pdflatex and bibtex are installed; rendered previews are emitted for subsequent visual inspection. Default true."},
            },
            "required": ["project_id"],
        },
    },
    {
        "name": "design_experiment",
        "description": "GeWu action: turn a generated idea into a structured, auditable experiment protocol. The protocol includes model system, intervention, five control arms, time course, readouts, replication/bias controls, analysis, success/failure rules, alternatives, regime shifts, and reproducibility. Execution remains blocked until its hard gate passes.",
        "input_schema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "Science project id."},
                "idea": {"description": "Idea JSON object or JSON string. It may include experiment_context with domain-expert selections for model_system, intervention, controls, timepoints, readouts, replication, analysis, thresholds, regime shifts, and reproducibility."},
                "idea_id": {"type": "string", "description": "draft_idea_id or experiment_plan_id from earlier MingLi output."},
                "constraints": {"type": "string", "description": "Resource constraints, e.g. academic lab scale, public datasets only, small GPU budget."},
            },
            "required": ["project_id"],
        },
    },
    {
        "name": "finalize_idea",
        "description": "MingLi action: finalize a complete idea JSON only after mandatory uniqueness/literature verification; overlap-risk ideas are rejected instead of persisted.",
        "input_schema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "Science project id."},
                "idea_json": {"description": "Complete MingLi final idea JSON. Omit when using idea_id."},
                "idea_id": {"type": "string", "description": "draft_idea_id or experiment_plan_id from earlier MingLi output."},
                "live_search": {"type": "boolean", "description": "Run live literature verification through verify_uniqueness; default true."},
                "providers": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional provider list: openalex, semantic_scholar, arxiv, biorxiv, chemrxiv, medrxiv, pubmed.",
                },
            },
            "required": ["project_id"],
        },
    },
    {
        "name": "create_hypothesis",
        "description": "Create a research hypothesis linked to a detected knowledge gap.",
        "input_schema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "Science project id."},
                "gap_id": {"type": "string", "description": "Knowledge gap id."},
                "statement": {"type": "string", "description": "Hypothesis statement."},
                "mechanism": {"type": "string", "description": "Claimed causal mechanism."},
                "expected_value": {"type": "string", "description": "Expected scientific or application value."},
                "test_plan": {"type": "string", "description": "Initial validation plan."},
            },
            "required": ["project_id", "gap_id", "statement", "mechanism", "expected_value", "test_plan"],
        },
    },
    {
        "name": "ask_socratic_questions",
        "description": "DuZhi Agent 5: ask structured Socratic questions across conceptual clarification, constraint checks, causal probes, and counterexample challenges.",
        "input_schema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "Science project id. Optional if hypothesis text is provided."},
                "hypothesis_id": {"type": "string", "description": "Persisted hypothesis id."},
                "hypothesis": {"type": "string", "description": "Hypothesis text when no hypothesis_id is available."},
                "question_types": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional subset: conceptual_clarification, constraint_check, causal_probe, counterexample_challenge.",
                },
                "max_questions": {"type": "integer", "description": "Maximum questions to return; default 12."},
            },
        },
    },
    {
        "name": "ask_critical_questions",
        "description": "Compatibility alias for ask_socratic_questions.",
        "input_schema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string"},
                "hypothesis_id": {"type": "string"},
                "hypothesis": {"type": "string"},
                "question_types": {"type": "array", "items": {"type": "string"}},
                "max_questions": {"type": "integer"},
            },
        },
    },
    {
        "name": "find_counterexamples",
        "description": "DuZhi counterexample challenge: generate regime-shift and falsification questions for a hypothesis.",
        "input_schema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string"},
                "hypothesis_id": {"type": "string"},
                "hypothesis": {"type": "string"},
                "max_questions": {"type": "integer"},
            },
        },
    },
    {
        "name": "stress_test_assumptions",
        "description": "DuZhi stress test: expose hidden assumptions, missing validity regimes, and boundary conditions.",
        "input_schema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string"},
                "hypothesis_id": {"type": "string"},
                "hypothesis": {"type": "string"},
                "max_questions": {"type": "integer"},
            },
        },
    },
    {
        "name": "moderate_round",
        "description": "BianLun Agent 6: moderate one structured debate round and decide advance/revise from DuZhi questions and YanZhen evidence.",
        "input_schema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string"},
                "round_name": {"type": "string"},
                "proponent_position": {"type": "string"},
                "opponent_questions": {"type": "array", "items": {}},
                "yanzhen_report": {"type": "object"},
            },
            "required": ["project_id", "round_name"],
        },
    },
    {
        "name": "summarize_positions",
        "description": "BianLun summary: compare proponent claim, opponent issues, and YanZhen verdict.",
        "input_schema": {
            "type": "object",
            "properties": {
                "proponent_position": {"type": "string"},
                "opponent_questions": {"type": "array", "items": {}},
                "yanzhen_report": {"type": "object"},
            },
        },
    },
    {
        "name": "extract_emergent_method",
        "description": "BianLun extraction: pull the refined method, causal chain, falsification conditions, and evidence requirements from a debate report.",
        "input_schema": {
            "type": "object",
            "properties": {
                "debate_report": {"description": "Debate report JSON object or JSON string."},
            },
            "required": ["debate_report"],
        },
    },
    {
        "name": "run_socratic_hypothesis_debate",
        "description": "Run the AHOIS/ARIS-inspired triangle loop: Socratic debate, YanZhen mechanism audit, targeted ZhiZhi literature completion, MingLi revision, and BianLun synthesis.",
        "input_schema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "Science project id."},
                "hypothesis_id": {"type": "string", "description": "Persisted hypothesis id from MingLi/finalize_idea."},
                "hypothesis": {"type": "string", "description": "Hypothesis text if no persisted id exists."},
                "max_rounds": {"type": "integer", "description": "4-5; default 5. Use 5 to allow an audit-feedback revision round before final synthesis."},
                "proponent_model_family": {"type": "string", "enum": ["qwen-max", "qwen-deep-research"], "default": "qwen-max", "description": "MingLi/proponent model. Qwen-only."},
                "opponent_model_family": {"type": "string", "enum": ["qwen-max", "qwen-deep-research"], "default": "qwen-max", "description": "DuZhi/opponent model. Qwen-only; role prompts provide adversarial independence."},
                "judge_model_family": {"type": "string", "enum": ["qwen-max", "qwen-deep-research"], "default": "qwen-deep-research", "description": "BianLun/moderator model. Qwen-only."},
                "verifier_model_family": {"type": "string", "enum": ["qwen-max", "qwen-deep-research"], "default": "qwen-deep-research", "description": "YanZhen/verifier model. Qwen-only."},
                "shifted_conditions": {"type": "array", "items": {}, "description": "Optional regime shift tests."},
                "auto_literature_supplement": {"type": "boolean", "description": "If true, YanZhen unsupported claims trigger capped ZhiZhi evidence completion."},
                "supplement_providers": {"type": "array", "items": {"type": "string"}, "description": "Optional providers for audit-triggered literature completion."},
            },
            "required": ["project_id"],
        },
    },
    {
        "name": "run_mechanism_check",
        "description": "Compatibility alias for YanZhen CAWM-style mechanism fidelity verification on a persisted hypothesis.",
        "input_schema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "Science project id."},
                "hypothesis_id": {"type": "string", "description": "Hypothesis id."},
                "shifted_conditions": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional regime-shift conditions.",
                },
            },
            "required": ["project_id", "hypothesis_id"],
        },
    },
    {
        "name": "check_internal_consistency",
        "description": "YanZhen Layer 1: audit hypothesis logic, causal chain integrity, formula/quantity assumptions, and internal contradictions.",
        "input_schema": {
            "type": "object",
            "properties": {
                "hypothesis": {"type": "string", "description": "Hypothesis or mechanism text."},
                "reasoning_chain": {"type": "array", "items": {"type": "string"}, "description": "Optional explicit premise -> mechanism -> conclusion chain."},
            },
            "required": ["hypothesis"],
        },
    },
    {
        "name": "check_data_consistency",
        "description": "YanZhen Layer 2: check whether a mechanism matches cited data and original source contexts.",
        "input_schema": {
            "type": "object",
            "properties": {
                "hypothesis": {"type": "string", "description": "Hypothesis or mechanism text."},
                "cited_data": {"type": "array", "items": {}, "description": "Cited papers, evidence snippets, references, or PaperGraph records."},
                "original_sources": {"type": "array", "items": {}, "description": "Broader source contexts for alignment and contradiction checks."},
            },
            "required": ["hypothesis"],
        },
    },
    {
        "name": "regime_shift_test",
        "description": "YanZhen Layer 3: stress a claimed mechanism under at least two shifted conditions to detect CAWM brittleness.",
        "input_schema": {
            "type": "object",
            "properties": {
                "mechanism": {"type": "string", "description": "Claimed mechanism text."},
                "original_conditions": {"type": "object", "description": "Original assumptions, parameters, dataset, environment, or boundary conditions."},
                "shifted_conditions": {
                    "type": "array",
                    "items": {},
                    "description": "Shift cases such as parameter 10x/0.1x, noise, domain transfer, different organism/material/system, or data distribution shift.",
                },
            },
            "required": ["mechanism"],
        },
    },
    {
        "name": "detect_selective_citation",
        "description": "YanZhen ARIS-style audit: detect cherry-picking by comparing cited papers/snippets against broader source contexts.",
        "input_schema": {
            "type": "object",
            "properties": {
                "cited_papers": {"type": "array", "items": {}, "description": "Papers or snippets cited as support."},
                "full_paper_contexts": {"type": "array", "items": {}, "description": "Broader PaperGraph records or source contexts, including limitations/contradictions."},
            },
            "required": [],
        },
    },
    {
        "name": "causal_chain_audit",
        "description": "YanZhen audit: trace causal links and verify that each link has supporting evidence.",
        "input_schema": {
            "type": "object",
            "properties": {
                "causal_chain": {"type": "array", "items": {"type": "string"}, "description": "Causal links, e.g. A -> B, B -> C."},
                "evidence_for_each": {"type": "array", "items": {}, "description": "Evidence snippets or records aligned to the causal links."},
            },
            "required": [],
        },
    },
    {
        "name": "run_yanzhen_mechanism_verification",
        "description": "YanZhen full protocol: execute internal consistency, data consistency, selective citation, causal-chain, and regime-shift CAWM verification.",
        "input_schema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "Science project id."},
                "hypothesis_id": {"type": "string", "description": "Persisted hypothesis id; preferred when available."},
                "hypothesis": {"type": "string", "description": "Raw hypothesis text when no persisted hypothesis is available."},
                "reasoning_chain": {"type": "array", "items": {"type": "string"}, "description": "Optional explicit causal/logical chain."},
                "cited_data": {"type": "array", "items": {}, "description": "Optional cited evidence."},
                "original_sources": {"type": "array", "items": {}, "description": "Optional original source contexts."},
                "shifted_conditions": {"type": "array", "items": {}, "description": "Optional regime-shift tests; at least two recommended."},
            },
            "required": ["project_id"],
        },
    },
    {
        "name": "export_research_plan",
        "description": "Export the current project as a standard science hypothesis and research plan.",
        "input_schema": {
            "type": "object",
            "properties": {"project_id": {"type": "string", "description": "Science project id."}},
            "required": ["project_id"],
        },
    },
]

CANONICAL_SCIENCE_TOOL_NAMES = frozenset(
    {
        "create_research_project",
        "list_research_projects",
        "get_research_project",
        "run_autogen_groupchat",
    }
)

INTERNAL_SCIENCE_TOOL_NAMES = frozenset(
    str(tool.get("name") or "")
    for tool in SCIENCE_TOOLS
    if str(tool.get("name") or "") not in CANONICAL_SCIENCE_TOOL_NAMES
)

PUBLIC_SCIENCE_TOOLS = [
    tool
    for tool in SCIENCE_TOOLS
    if str(tool.get("name") or "") in CANONICAL_SCIENCE_TOOL_NAMES
]

TOOLS = (
    BASIC_TOOLS
    + [TODO_TOOL, TASK_TOOL, LOAD_SKILL_TOOL, COMPACT_TOOL]
    + TASK_TOOLS
    + MCP_TOOLS
    + CRON_TOOLS
    + PUBLIC_SCIENCE_TOOLS
)

TOOL_HANDLERS: dict[str, Callable[..., str]] = {
    "bash": bash,
    "read_file": read_file,
    "write_file": write_file,
    "edit_file": edit_file,
    "glob": glob,
    "todo_write": todo_write,
    "task": task,
    "spawn_subagent": spawn_subagent,
    "load_skill": load_skill,
    "compact": compact,
    "create_task": create_task,
    "list_tasks": list_tasks,
    "get_task": get_task,
    "claim_task": claim_task,
    "complete_task": complete_task,
    "connect_mcp": connect_mcp,
    "schedule_cron": schedule_cron,
    "list_crons": list_crons,
    "cancel_cron": cancel_cron,
    "create_research_project": create_research_project,
    "list_research_projects": list_research_projects,
    "get_research_project": get_research_project,
    "list_science_agents": list_science_agents,
    "get_science_agent_prompt": get_science_agent_prompt,
    "list_literature_providers": list_literature_providers,
    "list_natural_science_disciplines": list_natural_science_disciplines,
    "resolve_natural_science_discipline_taxonomy": resolve_natural_science_discipline_taxonomy,
    "literature_provider_doctor": literature_provider_doctor,
    "literature_provider_smoke": literature_provider_smoke,
    "document_conversion_doctor": document_conversion_doctor,
    "explore_domain_subspaces": explore_domain_subspaces,
    "search_literature": search_literature,
    "search_literature_stratified": search_literature_stratified,
    "search_papers": search_papers,
    "search_papers_stratified": search_papers_stratified,
    "extract_structured_info": extract_structured_info,
    "select_literature_result": select_literature_result,
    "expand_literature_graph": expand_literature_graph,
    "search_cross_community_bridges": search_cross_community_bridges,
    "build_literature_relation_graph": build_literature_relation_graph,
    "run_autogen_groupchat": run_autogen_groupchat,
    "list_autogen_groupchats": list_autogen_groupchats,
    "get_autogen_run": get_autogen_run,
    "decompose_research_objective": decompose_research_objective,
    "set_research_brief": set_research_brief,
    "build_knowledge_map": build_knowledge_map,
    "build_louvain_community_knowledge_maps": build_louvain_community_knowledge_maps,
    "add_literature_evidence": add_literature_evidence,
    "import_literature_text": import_literature_text,
    "import_literature_file": import_literature_file,
    "import_literature_search_result": import_literature_search_result,
    "domain_review_paper": domain_review_paper,
    "reconcile_project_domain_reviews": reconcile_project_domain_reviews,
    "extract_paper_keynote": extract_paper_keynote,
    "import_papergraph_record": import_papergraph_record,
    "list_papergraph_records": list_papergraph_records,
    "verify_citation_uniqueness": verify_citation_uniqueness,
    "assess_novelty": assess_novelty,
    "verify_uniqueness": verify_uniqueness,
    "run_zhizhi_subhypothesis_analysis": run_zhizhi_subhypothesis_analysis,
    "parse_literature_text": parse_literature_text,
    "build_coverage_matrix": build_coverage_matrix,
    "detect_knowledge_gaps": detect_knowledge_gaps,
    "run_tanxi_gap_exploration": run_tanxi_gap_exploration,
    "apply_gap_retrieval_assessment": apply_gap_retrieval_assessment,
    "execute_research_question_retrieval_plan": execute_research_question_retrieval_plan,
    "run_socrates_type_specific_review": run_socrates_type_specific_review,
    "build_research_evidence_graph_v3": build_research_evidence_graph_v3,
    "get_research_graph_view_v3": get_research_graph_view_v3,
    "build_proposal_brief_v2": build_proposal_brief_v2,
    "write_research_proposal_v2": write_research_proposal_v2,
    "audit_research_proposal_v2": audit_research_proposal_v2,
    "export_research_proposal_v2": export_research_proposal_v2,
    "generate_proposal_traceability_report_v3": generate_proposal_traceability_report_v3,
    "generate_traceability_report_v3": generate_traceability_report_v3,
    "generate_research_proposal_report_v3": generate_research_proposal_report_v3,
    "run_zhizhi_near_pass_source_role_retrieval": run_zhizhi_near_pass_source_role_retrieval,
    "check_semantic_plausibility": check_semantic_plausibility,
    "evolve_domain_subspaces": evolve_domain_subspaces,
    "build_temporal_knowledge_graph": build_temporal_knowledge_graph,
    "detect_structural_knowledge_gaps": detect_structural_knowledge_gaps,
    "find_structural_analogy_transfers": find_structural_analogy_transfers,
    "run_mingli_hypothesis_evolution": run_mingli_hypothesis_evolution,
    "run_socrates_mechanism_enrichment": run_socrates_mechanism_enrichment,
    "generate_idea": generate_idea,
    "generate_research_report": generate_research_report,
    "design_experiment": design_experiment,
    "finalize_idea": finalize_idea,
    "create_hypothesis": create_hypothesis,
    "ask_socratic_questions": ask_socratic_questions,
    "ask_critical_questions": ask_critical_questions,
    "find_counterexamples": find_counterexamples,
    "stress_test_assumptions": stress_test_assumptions,
    "moderate_round": moderate_round,
    "summarize_positions": summarize_positions,
    "extract_emergent_method": extract_emergent_method,
    "run_socratic_hypothesis_debate": run_socratic_hypothesis_debate,
    "run_mechanism_check": run_mechanism_check,
    "check_internal_consistency": check_internal_consistency,
    "check_data_consistency": check_data_consistency,
    "regime_shift_test": regime_shift_test,
    "detect_selective_citation": detect_selective_citation,
    "causal_chain_audit": causal_chain_audit,
    "run_yanzhen_mechanism_verification": run_yanzhen_mechanism_verification,
    "export_research_plan": export_research_plan,
}
