"""Structured keynote compression with per-reference recovery and checkpoints."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from src.agents.idea_agent.utils.core.chat_errors import format_chat_retry_error
from src.agents.idea_agent.utils.core.config_loader import get_config_value
from src.agents.idea_agent.utils.core.json_utils import read_json_file, write_json_file
from src.llm.provider_registry import resolve_model
from src.llm.research_policy import research_policy
from src.llm.structured_output import schema_repair_prompt, validate_json_value


def _response_formats(agent: Any, model: str, schema: dict[str, Any]) -> list[Any]:
    model_spec = resolve_model(getattr(agent, "project_config", None), model)
    formats = []
    if model_spec.capabilities.json_schema:
        formats.append(
            {
                "type": "json_schema",
                "json_schema": {"name": "keynote_compression", "strict": True, "schema": schema},
            }
        )
    if model_spec.capabilities.json_object:
        formats.append({"type": "json_object"})
    formats.append(None)
    return formats


def _format_is_unsupported(error: Exception) -> bool:
    status = getattr(error, "status_code", None)
    if status not in (None, 400, 422):
        return False
    detail = format_chat_retry_error(error).casefold()
    format_mentioned = any(
        term in detail for term in ("response_format", "json_schema", "json_object", "text.format")
    )
    unsupported = any(
        term in detail
        for term in ("unsupported", "not support", "unknown", "unrecognized", "not allowed", "unexpected keyword")
    )
    return format_mentioned and unsupported


def _save_checkpoint(path: Path | None, checkpoint: dict[str, Any]) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(".tmp")
    write_json_file(temporary_path, checkpoint)
    temporary_path.replace(path)


def _validate_payload(raw: str, schema: dict[str, Any]) -> dict[str, str]:
    payload = json.loads(raw)
    validate_json_value(payload, schema)
    for field in schema["required"]:
        if not payload[field].strip():
            raise ValueError(f"{field} must be a non-empty string")
    return {field: payload[field].strip() for field in schema["required"]}


def compress_keynotes(
    agent: Any,
    ctx: Any,
    *,
    prompt: str,
    references: list[dict[str, Any]],
    group: bool = False,
) -> dict[str, Any]:
    runtime = ctx.runtime or agent.runtime
    session = ctx.session or getattr(agent, "session", None)
    logger = ctx.logger or getattr(agent, "logger", None)
    stage = "ka_keynote_group_summary" if group else "ka_keynote_single_compression"
    model = agent.model
    if hasattr(agent, "resolve_stage_model"):
        model = agent.resolve_stage_model(stage=stage, workflow_name=ctx.workflow_name, requested_model=model)
    model = research_policy(getattr(agent, "project_config", None)).get("model_name") or model
    fields = ["summary"] if group else ["summary", "insight"]
    schema = {
        "type": "object",
        "properties": {field: {"type": "string"} for field in fields},
        "required": fields,
        "additionalProperties": False,
    }
    originals = [
        {
            "paper_id": reference.get("paper_id") or reference.get("node_id"),
            "title": reference.get("title") or reference.get("paper_title"),
            "keynote": str(reference.get("keynote") or ""),
        }
        for reference in references
    ]
    identity = {"version": 1, "prompt": prompt, "model": model, "schema": schema, "references": originals}
    fingerprint = hashlib.sha256(json.dumps(identity, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
    run_dir = getattr(agent, "run_dir", None)
    checkpoint_path = (
        Path(run_dir) / "keynote_compression" / f"{stage}-{fingerprint}.json" if run_dir else None
    )
    checkpoint = {
        "fingerprint": fingerprint,
        "model": model,
        "references": originals,
        "attempts": [],
        "issues": [],
        "status": "running",
    }
    if checkpoint_path is not None and checkpoint_path.exists():
        try:
            saved = read_json_file(checkpoint_path)
            if saved.get("fingerprint") == fingerprint:
                if isinstance(saved.get("attempts"), list) and isinstance(saved.get("issues"), list):
                    checkpoint["attempts"] = saved["attempts"]
                    checkpoint["issues"] = saved["issues"]
                if saved.get("status") in {"completed", "repaired"}:
                    _validate_payload(json.dumps({field: saved["result"][field] for field in fields}), schema)
                    return saved["result"]
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            pass
    _save_checkpoint(checkpoint_path, checkpoint)
    formats = _response_formats(agent, model, schema)
    format_index = 0
    repair_attempts = max(
        0, int(get_config_value(getattr(agent, "config", None), "agent.keynote_json_repair_attempts", 2))
    )
    current_prompt = prompt
    paper_ids = [reference["paper_id"] for reference in originals]
    label = ", ".join(str(paper_id) for paper_id in paper_ids)
    payload = None
    for attempt in range(repair_attempts + 1):
        raw = ""
        while True:
            response_format = formats[format_index]
            record = {"attempt": attempt + 1, "response_format": response_format}
            checkpoint["attempts"].append(record)
            try:
                kwargs = {"response_format": response_format} if response_format is not None else {}
                raw = runtime.llm_text(
                    session=session,
                    stage=stage,
                    workflow_name=ctx.workflow_name,
                    op_name=stage.removeprefix("ka_"),
                    prompt=current_prompt,
                    model=model,
                    temperature=0.1 if attempt == 0 else 0.0,
                    max_output_tokens=4096 if group else 2048,
                    **kwargs,
                )
            except Exception as exc:
                record["error"] = format_chat_retry_error(exc)
                checkpoint["issues"].append(record["error"])
                _save_checkpoint(checkpoint_path, checkpoint)
                if response_format is not None and _format_is_unsupported(exc) and format_index + 1 < len(formats):
                    format_index += 1
                    if logger is not None:
                        logger.warning(
                            "Keynote compression paper=%s: structured output format rejected; "
                            "trying next supported format: %s",
                            label,
                            exc,
                        )
                    continue
                break
            record["raw_response"] = raw
            _save_checkpoint(checkpoint_path, checkpoint)
            break
        if "error" in record:
            break
        try:
            payload = _validate_payload(raw, schema)
            break
        except (ValueError, TypeError) as exc:
            record["error"] = str(exc)
            checkpoint["issues"].append(str(exc))
            _save_checkpoint(checkpoint_path, checkpoint)
            if attempt < repair_attempts:
                if logger is not None:
                    logger.warning(
                        "Keynote compression paper=%s: JSON validation failed; requesting repair %d/%d: %s",
                        label,
                        attempt + 1,
                        repair_attempts,
                        exc,
                    )
                current_prompt = (
                    f"{prompt}\n\n{schema_repair_prompt(schema, exc)}\n"
                    "Repair only this capsule using its original keynotes. Do not add facts. "
                    "Every required field must be a non-empty string.\n"
                    f"Previous response (format repair only):\n{raw[:12000]}"
                )
    if payload is None:
        summary = "\n\n".join(
            f"{reference['title']}\n{reference['keynote']}" if group else reference["keynote"]
            for reference in originals
        )
        payload = {"summary": summary, "insight": "", "original_keynotes": originals}
        status = "fallback"
        if logger is not None:
            logger.warning(
                "Keynote compression paper=%s failed; retaining original keynote and continuing. Checkpoint: %s",
                label,
                checkpoint_path,
            )
    else:
        status = "repaired" if attempt else "completed"
        payload.setdefault("insight", "")
    payload.update({"compression_status": status, "compression_issues": list(checkpoint["issues"])})
    if checkpoint_path is not None:
        payload["compression_checkpoint"] = str(checkpoint_path)
    checkpoint.update({"status": status, "result": payload})
    _save_checkpoint(checkpoint_path, checkpoint)
    if session is not None:
        session.record_event(
            "keynote_compression",
            paper_ids=paper_ids,
            status=status,
            issues=payload["compression_issues"],
            checkpoint=payload.get("compression_checkpoint"),
        )
    return payload
