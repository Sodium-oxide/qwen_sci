"""Shared LigAgent utilities for reference context assembly and JSON response parsing."""

from __future__ import annotations

from time import perf_counter
from typing import Any, Dict, List, Optional

from src.agents.idea_agent.utils.core.json_utils import pretty_json
from src.agents.idea_agent.utils.core.response_parsing import (
    parse_json_object_response,
    parse_json_response,
)
from src.agents.idea_agent.agent.artifacts import (
    ensure_artifact_structure,
)


INTRODUCTION_DEFAULT_MAX_OUTPUT_TOKENS = 25600
INTRODUCTION_DEFAULT_JSON_REPAIR_ATTEMPTS = 2
INTRODUCTION_REPAIR_CONTEXT_LIMIT = 24000


def collect_paper_context_entries(
    artifact: Dict[str, Any],
    reference_batches: List[List[Dict[str, Any]]],
) -> List[Dict[str, Any]]:
    del artifact
    entries: List[Dict[str, Any]] = []
    seen_ids: set[str] = set()
    for batch in reference_batches or []:
        for reference in batch or []:
            if not isinstance(reference, dict):
                continue
            node_id = str(
                reference.get("node_id")
                or reference.get("paper_id")
                or reference.get("title")
                or ""
            ).strip()
            if not node_id or node_id in seen_ids:
                continue
            seen_ids.add(node_id)
            summary = str(reference.get("summary") or "").strip()
            insight = str(reference.get("insight") or "").strip()
            if insight and insight not in summary:
                summary = f"{summary} Insight: {insight}".strip()
            if not summary:
                summary = "No summary available."
            entries.append(
                {
                    "paper_id": node_id,
                    "title": reference.get("title") or reference.get("paper_title") or node_id,
                    "summary": summary,
                    "source": reference.get("source") or "survey_keynote",
                    "authors": reference.get("authors") or [],
                }
            )
    return entries


def generate_idea_introduction(
    chat_fn,
    prompt_template: str,
    model: str,
    topic: str,
    best_entry: Dict[str, Any],
    paper_entries: List[Dict[str, Any]],
    mature_idea: str,
    logger,
    max_output_tokens: int = INTRODUCTION_DEFAULT_MAX_OUTPUT_TOKENS,
    json_repair_attempts: int = INTRODUCTION_DEFAULT_JSON_REPAIR_ATTEMPTS,
) -> str:
    entries = paper_entries or []
    if not entries:
        return fallback_introduction_text(best_entry, entries, mature_idea)
    prompt = prompt_template.format(
        topic=topic,
        mature_idea=mature_idea or "",
        idea=pretty_json(best_entry),
        papers=pretty_json(entries),
    )
    output_budget = max(1024, int(max_output_tokens or INTRODUCTION_DEFAULT_MAX_OUTPUT_TOKENS))
    repair_attempts = max(0, int(json_repair_attempts or 0))
    total_attempts = repair_attempts + 1
    current_prompt = prompt
    previous_response = ""
    last_error: Optional[Exception] = None
    for attempt in range(1, total_attempts + 1):
        response = ""
        try:
            response = chat_fn(
                current_prompt,
                temperature=0.3 if attempt == 1 else 0.0,
                max_output_tokens=output_budget,
                model=model,
                response_format={"type": "json_object"},
            )
            payload = parse_json_object_response(response)
            intro = payload.get("introduction") or payload.get("intro")
            if not isinstance(intro, str) or not intro.strip():
                raise ValueError("introduction must be a non-empty string")
            if attempt > 1:
                logger.info("✅ Introduction JSON repaired on attempt %d/%d.", attempt, total_attempts)
            return intro.strip()
        except Exception as exc:  # pragma: no cover - network
            previous_response = str(response or "")
            last_error = exc
            if attempt >= total_attempts:
                break
            logger.warning(
                "⚠️ Introduction JSON contract violation; requesting repair %d/%d: %s",
                attempt,
                repair_attempts,
                exc,
            )
            current_prompt = _build_introduction_repair_prompt(
                prompt,
                previous_response,
                exc,
            )
    logger.warning(
        "⚠️ Introduction generation failed after %d attempt(s): %s; using fallback",
        total_attempts,
        last_error,
    )
    return fallback_introduction_text(best_entry, entries, mature_idea)


def _build_introduction_repair_prompt(
    original_prompt: str,
    previous_response: str,
    error: Exception,
) -> str:
    context_limit = INTRODUCTION_REPAIR_CONTEXT_LIMIT
    original_limit = max(8_000, context_limit * 2 // 3)
    response_limit = max(2_000, context_limit - original_limit)
    bounded_original = _bound_prompt_text(original_prompt, original_limit)
    bounded_response = _bound_prompt_text(previous_response, response_limit)
    return (
        "Regenerate the requested introduction. Your previous response violated the JSON contract.\n"
        "Return ONLY one complete JSON object with exactly this shape: "
        '{"introduction":"<one paragraph>"}\n'
        "The introduction must be a concise proposal of 180-300 words, with no Markdown fences, "
        "no commentary outside the JSON object, and all quotes/newlines escaped as valid JSON.\n"
        f"Validation error: {error}\n\n"
        "Original request context:\n"
        f"{bounded_original}\n\n"
        "Previous response excerpt (do not copy malformed JSON syntax):\n"
        f"{bounded_response}"
    )


def _bound_prompt_text(value: Any, limit: int) -> str:
    text = str(value or "")
    if len(text) <= limit:
        return text
    head = max(1_000, limit // 2)
    tail = max(1_000, limit - head - 80)
    return text[:head] + "\n[context truncated]\n" + text[-tail:]


def fallback_introduction_text(
    best_entry: Dict[str, Any], paper_entries: List[Dict[str, Any]], mature_idea: str
) -> str:
    title = best_entry.get("title", "This work")
    abstract = best_entry.get("abstract") or ""
    mature_anchor = str(mature_idea or "").strip()
    if mature_anchor:
        intro_lines = [
            f"{title} refines the mature idea by repairing a concrete limitation in the current design. {abstract}".strip()
        ]
    else:
        intro_lines = [
            f"{title} builds on recent literature to tackle the current topic. {abstract}".strip()
        ]
    if paper_entries:
        cite_lines = []
        for entry in paper_entries:
            cite_lines.append(
                f"- {entry.get('title') or entry.get('paper_id')}: {entry.get('summary', 'No summary available.')}"
            )
        intro_lines.append("Key references informing this idea:\n" + "\n".join(cite_lines))
    return "\n\n".join(intro_lines)


def align_public_idea_entry(
    chat_fn,
    prompt_template: str,
    model: str,
    topic: str,
    best_entry: Dict[str, Any],
    mature_idea: str,
    refinement_scope: str,
    paper_entries: List[Dict[str, Any]],
    logger,
) -> Dict[str, Any]:
    prompt = prompt_template.format(
        topic=topic,
        mature_idea=mature_idea or "",
        refinement_scope=refinement_scope or "",
        idea=pretty_json(best_entry),
        papers=pretty_json(paper_entries or []),
    )
    try:
        response = chat_fn(prompt, temperature=0.2, max_output_tokens=8192, model=model)
        payload = parse_json_response(response)
        if not isinstance(payload, dict):
            return dict(best_entry)
        aligned = dict(best_entry)
        for key in ("title", "abstract", "core_contribution", "method", "risks"):
            value = str(payload.get(key) or "").strip()
            if value:
                aligned[key] = value
        return aligned
    except Exception as exc:  # pragma: no cover - network
        logger.warning("⚠️ Public idea alignment failed: %s", exc)
        return dict(best_entry)
class LigRuntime:
    """Thin wrapper around LigAgent chat/tool calls with op-level tracing."""

    def __init__(self, agent: Any) -> None:
        self.agent = agent

    def llm_text(
        self,
        *,
        session: Optional[Any],
        stage: str,
        workflow_name: Optional[str] = None,
        op_name: str,
        prompt: str,
        model: Optional[str] = None,
        **kwargs: Any,
    ) -> str:
        started_at = perf_counter()
        if hasattr(self.agent, "resolve_stage_model"):
            resolved_model = self.agent.resolve_stage_model(
                stage=stage,
                workflow_name=workflow_name,
                requested_model=model,
            )
        else:
            resolved_model = model or getattr(self.agent, "model", "gpt-5-mini")
        try:
            result = self.agent.chat(prompt, model=resolved_model, stage=stage, **kwargs)
            self._record(
                session,
                "llm_call",
                stage=stage,
                workflow_name=workflow_name,
                op_name=op_name,
                model=resolved_model,
                status="success",
                latency_ms=round((perf_counter() - started_at) * 1000.0, 2),
            )
            return result
        except Exception as exc:
            self._record(
                session,
                "llm_call",
                stage=stage,
                workflow_name=workflow_name,
                op_name=op_name,
                model=resolved_model,
                status="error",
                error=str(exc),
                latency_ms=round((perf_counter() - started_at) * 1000.0, 2),
            )
            raise

    def llm_json(
        self,
        *,
        session: Optional[Any],
        stage: str,
        workflow_name: Optional[str] = None,
        op_name: str,
        prompt: str,
        model: Optional[str] = None,
        require_json_object: bool = False,
        **kwargs: Any,
    ) -> Any:
        raw = self.llm_text(
            session=session,
            stage=stage,
            workflow_name=workflow_name,
            op_name=op_name,
            prompt=prompt,
            model=model,
            **kwargs,
        )
        if require_json_object:
            return parse_json_object_response(raw)
        return parse_json_response(raw)

    def _record(self, session: Optional[Any], event_type: str, **payload: Any) -> None:
        if session is not None:
            session.record_event(event_type, **payload)


class LigSession:
    """Lightweight per-run state wrapper for LigAgent."""

    def __init__(self, artifact: Dict[str, Any]) -> None:
        self.artifact = ensure_artifact_structure(artifact)
        self._pending_slots: Dict[str, Any] = {}
        self._pending_events: List[Dict[str, Any]] = []

    def set_slot(self, name: str, value: Any) -> None:
        self._pending_slots[name] = value

    def record_event(self, event_type: str, **payload: Any) -> None:
        event = {"event": event_type}
        event.update(payload)
        self._pending_events.append(event)

    def drain_patch(self) -> tuple[Dict[str, Any], List[Dict[str, Any]]]:
        slots = self._pending_slots
        events = self._pending_events
        self._pending_slots = {}
        self._pending_events = []
        return slots, events
