from __future__ import annotations

from datetime import datetime
import os
from pathlib import Path
from typing import Any

try:
    from .config import LOG_COLOR, LOG_PATH
except ImportError:
    from config import LOG_COLOR, LOG_PATH


COLORS = {
    "reset": "\033[0m",
    "gray": "\033[90m",
    "yellow": "\033[33m",
    "red": "\033[31m",
    "magenta": "\033[35m",
    "cyan": "\033[36m",
}

CATEGORY_COLORS = {
    "WARN": "yellow",
    "ERROR": "red",
    "SUBAGENT": "magenta",
    "USER": "cyan",
    "COMPACT": "yellow",
    
    "MCP": "cyan",
    
    "TASK": "cyan",
    "CRON": "cyan",
    "TODO": "cyan",
}

_TRUTHY = {"1", "true", "yes", "on", "debug", "verbose"}


def _env_flag(name: str, default: str = "0") -> bool:
    return str(os.environ.get(name, default)).strip().lower() in _TRUTHY


def _env_list(name: str) -> set[str]:
    raw = str(os.environ.get(name, "") or "")
    return {
        item.strip()
        for chunk in raw.split(";")
        for item in chunk.split(",")
        if item.strip()
    }


_VERBOSE_ALL = _env_flag("SCIENCE_LOG_VERBOSE", "0")
_VERBOSE_EVENTS = _env_list("SCIENCE_LOG_VERBOSE_EVENTS")
_WRITE_COMPACTED_DEBUG = _env_flag("SCIENCE_LOG_WRITE_COMPACTED_DEBUG", "1")
try:
    _FIELD_MAX_CHARS = max(
        240,
        min(4000, int(os.environ.get("SCIENCE_LOG_FIELD_MAX_CHARS", "1000"))),
    )
except ValueError:
    _FIELD_MAX_CHARS = 1000
_DEBUG_LOG_PATH = Path(
    os.environ.get(
        "AGENT_DEBUG_LOG_PATH",
        str(LOG_PATH.with_name(f"{LOG_PATH.stem}.debug{LOG_PATH.suffix}")),
    )
).resolve()


# These events are still useful for forensics, but they are too granular for
# the human-facing run log.  They are routed to ``agent.debug.log`` by default
# while compact SH/round summaries remain in ``agent.log``.
COMPACTED_DEFAULT_EVENTS = {
    # Query/candidate-level audits are verbose by design.  Keep one compact
    # summary in agent.log and route the per-branch/per-paper trail to debug.
    "subhypothesis_query_contamination_audit",
    "stratified_candidate_selected",
    "candidate_import_scheduled",
    "candidate_import_prepare_scheduled",
    "candidate_import_preflight_skipped",
    "candidate_import_preflight_deferred",
    "candidate_imported",
    "paper_imported",
    "paper_metadata_enriched",
    "metadata_enrichment_failed",
    "semantic_scholar_optional_detail_probe_complete",
    "semantic_scholar_detail_enrichment_complete",
    "provider_local_stratification_diagnostic_sample",
    "foundational_mechanism_bridge_gate_complete",
    "foundational_mechanism_rejection_summary",
    "objective_decomposed",
    "literature_search_stage_timing",
    "foundational_mechanism_candidate_rejected",
    "subhypothesis_candidate_rejected_alignment",
    "l2_alignment_rejection_diagnostic",
    "subhypothesis_preprint_candidate_rejected",
    "paper_duplicate",
    "paper_fuzzy_title_duplicate",
    "openalex_request_complete",
    "openalex_doi_metadata_complete",
    "pubmed_provider_batch_request_complete",
    "semantic_scholar_provider_batch_request_complete",
    "semantic_scholar_l2_provider_batch_complete",
    "openalex_l2_provider_batch_complete",
    "sciencedirect_provider_batch_complete",
    "semantic_scholar_cache_hit",
    "subhypothesis_import_candidate_start",
    "subhypothesis_import_layer_start",
    "subhypothesis_import_layer_complete",
    "subhypothesis_import_commit_batch_saved",
    "subhypothesis_batch_storage_normalization_start",
    "subhypothesis_batch_storage_normalization_complete",
    "subhypothesis_fulltext_batch_runtime_ready",
    "subhypothesis_round_import_budget",
    "subhypothesis_deep_alignment_budget",
    "targeted_deep_alignment_budget",
    "historical_foundation_budget_plan",
    "subhypothesis_domain_embedding_status",
    "subhypothesis_search_phase_frozen",
    "subhypothesis_search_phase_complete",
    "subhypothesis_import_phase_start",
    "subhypothesis_round_funnel",
    "subhypothesis_retrieval_complete",
    "subhypothesis_fulltext_gate",
    "subhypothesis_retrieval_failure_actions",
    "subhypothesis_low_admission_reassessment_complete",
}


def _event_is_compacted(category: str, event: str) -> bool:
    if _VERBOSE_ALL or event in _VERBOSE_EVENTS:
        return False
    if category.upper() in {"WARN", "ERROR"}:
        return False
    return event in COMPACTED_DEFAULT_EVENTS


def log_event(category: str, event: str, **data: Any) -> None:
    category = category.upper()
    line = format_event(category, event, **data)
    if _event_is_compacted(category, event):
        if _WRITE_COMPACTED_DEBUG:
            write_debug_log_line(line)
        return
    write_log_line(line)
    print(colorize(category, line))


def format_event(category: str, event: str, **data: Any) -> str:
    details = ", ".join(f"{key}={format_value(value)}" for key, value in data.items())
    if details:
        return f"[{category}] {event}: {details}"
    return f"[{category}] {event}"


def format_value(value: Any) -> str:
    text = str(value).replace("\n", "\\n")
    if len(text) > _FIELD_MAX_CHARS:
        return text[:_FIELD_MAX_CHARS] + "...[truncated]"
    return text


def write_log_line(line: str) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().isoformat(timespec="seconds")
    with LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(f"{timestamp} {line}\n")


def write_debug_log_line(line: str) -> None:
    _DEBUG_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().isoformat(timespec="seconds")
    with _DEBUG_LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(f"{timestamp} {line}\n")


def colorize(category: str, line: str) -> str:
    if not LOG_COLOR:
        return line
    lowered = line.lower()
    if category == "ERROR" or "error" in lowered or "] blocked:" in lowered:
        color = "red"
    elif "warn" in lowered or category in {"WARN", "COMPACT"}:
        color = "yellow"
    else:
        color = CATEGORY_COLORS.get(category, "gray")
    return f"{COLORS[color]}{line}{COLORS['reset']}"
