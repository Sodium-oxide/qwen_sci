from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    from .config import (
        MEMORY_DIR,
        MEMORY_EXTRACT_TOKENS,
        MEMORY_INDEX,
        MEMORY_MERGE_THRESHOLD,
        MEMORY_MERGE_TOKENS,
        MEMORY_RETRIEVAL_LIMIT,
        MODEL_ID,
    )
    from .llm import get_client
    from .log import log_event
except ImportError:
    from config import (
        MEMORY_DIR,
        MEMORY_EXTRACT_TOKENS,
        MEMORY_INDEX,
        MEMORY_MERGE_THRESHOLD,
        MEMORY_MERGE_TOKENS,
        MEMORY_RETRIEVAL_LIMIT,
        MODEL_ID,
    )
    from llm import get_client
    from log import log_event


MEMORY_TYPES = {"user", "feedback", "project", "reference"}


@dataclass(frozen=True)
class Memory:
    name: str
    description: str
    type: str
    content: str
    path: Path


def ensure_memory_store() -> None:
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    if not MEMORY_INDEX.exists():
        MEMORY_INDEX.write_text("# Memory Index\n\n", encoding="utf-8")


def load_all_memories() -> list[Memory]:
    ensure_memory_store()
    memories: list[Memory] = []
    for path in sorted(MEMORY_DIR.glob("*.md")):
        if path.name == MEMORY_INDEX.name:
            continue
        try:
            text = path.read_text(encoding="utf-8")
            meta, body = parse_frontmatter(text)
            memories.append(
                Memory(
                    name=meta.get("name") or path.stem,
                    description=meta.get("description") or "",
                    type=normalize_type(meta.get("type") or "project"),
                    content=body.strip(),
                    path=path,
                )
            )
        except Exception as exc:
            log_event("WARN", "memory_load_failed", path=path, error=exc)
    return memories


def render_memories(
    context: str,
    *,
    allowed_types: set[str] | frozenset[str] | None = None,
) -> str:
    memories = relevant_memories(context, allowed_types=allowed_types)
    if not memories:
        return ""
    blocks = [
        f"<memory name=\"{memory.name}\" type=\"{memory.type}\">\n"
        f"{memory.description}\n\n{memory.content}\n"
        f"</memory>"
        for memory in memories
    ]
    return "<relevant_memories>\n" + "\n\n".join(blocks) + "\n</relevant_memories>"


def relevant_memories(
    context: str,
    *,
    allowed_types: set[str] | frozenset[str] | None = None,
) -> list[Memory]:
    memories = load_all_memories()
    if allowed_types is not None:
        normalized_types = {normalize_type(memory_type) for memory_type in allowed_types}
        memories = [memory for memory in memories if memory.type in normalized_types]
    if not memories:
        log_event("MEMORY", "retrieved", count=0)
        return []
    try:
        selected = select_memories_with_llm(context, memories)
    except Exception as exc:
        log_event("WARN", "memory_retrieval_llm_failed", error=exc)
        selected = keyword_select(context, memories)
    selected = selected[:MEMORY_RETRIEVAL_LIMIT]
    log_event("MEMORY", "retrieved", count=len(selected))
    return selected


def extract_memories(messages: list[dict[str, Any]], final_text: str = "") -> None:
    ensure_memory_store()
    try:
        items = extract_with_llm(serialize_context(messages, final_text))
    except Exception as exc:
        log_event("WARN", "memory_extract_failed", error=exc)
        return

    saved = 0
    for item in items:
        if save_memory_item(item):
            saved += 1
    if saved:
        rebuild_index()
        log_event("MEMORY", "saved", count=saved)
        maybe_merge_memories()


def maybe_merge_memories() -> None:
    memories = load_all_memories()
    if len(memories) < MEMORY_MERGE_THRESHOLD:
        return
    try:
        merged = merge_with_llm(memories)
    except Exception as exc:
        log_event("WARN", "memory_merge_failed", error=exc)
        return
    if not merged:
        return

    written: set[Path] = set()
    for item in merged:
        path = memory_path(item)
        path.write_text(render_memory_file(item), encoding="utf-8")
        written.add(path)
    for memory in memories:
        if memory.path not in written:
            memory.path.unlink(missing_ok=True)
    rebuild_index()
    log_event("MEMORY", "merged", before=len(memories), after=len(written))


def select_memories_with_llm(context: str, memories: list[Memory]) -> list[Memory]:
    client = get_client()
    catalog = [
        {"name": memory.name, "description": memory.description, "type": memory.type}
        for memory in memories
    ]
    response = client.messages.create(
        model=MODEL_ID,
        max_tokens=400,
        system="Select memory names relevant to the current coding task. Return JSON only.",
        messages=[
            {
                "role": "user",
                "content": (
                    f"Task context:\n{context}\n\n"
                    f"Memories:\n{json.dumps(catalog, ensure_ascii=False)}\n\n"
                    "Return {\"names\": [\"...\"]}."
                ),
            }
        ],
    )
    names = set(parse_json_object(response_text(response.content)).get("names", []))
    return [memory for memory in memories if memory.name in names]


def extract_with_llm(payload: str) -> list[dict[str, str]]:
    client = get_client()
    response = client.messages.create(
        model=MODEL_ID,
        max_tokens=MEMORY_EXTRACT_TOKENS,
        system=(
            "Extract durable memories from an agent conversation. Save only stable "
            "user preferences, feedback, project facts, or reference pointers. Return JSON only."
        ),
        messages=[
            {
                "role": "user",
                "content": (
                    f"{payload}\n\n"
                    "Return {\"memories\": [{\"name\": \"snake_case\", "
                    "\"description\": \"short\", \"type\": \"user|feedback|project|reference\", "
                    "\"content\": \"markdown\"}]}."
                ),
            }
        ],
    )
    return [
        item
        for item in parse_json_object(response_text(response.content)).get("memories", [])
        if isinstance(item, dict)
    ]


def merge_with_llm(memories: list[Memory]) -> list[dict[str, str]]:
    client = get_client()
    payload = [
        {
            "name": memory.name,
            "description": memory.description,
            "type": memory.type,
            "content": memory.content,
        }
        for memory in memories
    ]
    response = client.messages.create(
        model=MODEL_ID,
        max_tokens=MEMORY_MERGE_TOKENS,
        system="Merge duplicate, stale, or contradictory memories. Return JSON only.",
        messages=[
            {
                "role": "user",
                "content": (
                    f"{json.dumps(payload, ensure_ascii=False)}\n\n"
                    "Return {\"memories\": [...]} using the same fields."
                ),
            }
        ],
    )
    return [
        item
        for item in parse_json_object(response_text(response.content)).get("memories", [])
        if isinstance(item, dict)
    ]


def save_memory_item(item: dict[str, str]) -> bool:
    name = sanitize_key(str(item.get("name", "")))
    content = str(item.get("content", "")).strip()
    if not name or not content:
        return False
    normalized = {
        "name": name,
        "description": str(item.get("description", "")).strip() or name,
        "type": normalize_type(str(item.get("type", "project"))),
        "content": content,
    }
    memory_path(normalized).write_text(render_memory_file(normalized), encoding="utf-8")
    return True


def memory_path(item: dict[str, str]) -> Path:
    ensure_memory_store()
    return MEMORY_DIR / f"{normalize_type(item.get('type', 'project'))}_{sanitize_key(item.get('name', 'memory'))}.md"


def render_memory_file(item: dict[str, str]) -> str:
    return (
        "---\n"
        f"name: {sanitize_key(item.get('name', 'memory'))}\n"
        f"description: {str(item.get('description', '')).replace(chr(10), ' ')}\n"
        f"type: {normalize_type(item.get('type', 'project'))}\n"
        "---\n\n"
        f"{item.get('content', '').strip()}\n"
    )


def rebuild_index() -> None:
    ensure_memory_store()
    lines = ["# Memory Index", ""]
    for memory in load_all_memories():
        lines.append(f"- [{memory.path.name}]({memory.path.name}) - {memory.type}: {memory.description}")
    MEMORY_INDEX.write_text("\n".join(lines) + "\n", encoding="utf-8")


def keyword_select(context: str, memories: list[Memory]) -> list[Memory]:
    terms = {term.lower().strip(".,:;()[]{}\"'") for term in context.split()}
    scored: list[tuple[int, Memory]] = []
    for memory in memories:
        haystack = f"{memory.name} {memory.description} {memory.content}".lower()
        score = sum(1 for term in terms if len(term) > 2 and term in haystack)
        if score:
            scored.append((score, memory))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [memory for _, memory in scored[:MEMORY_RETRIEVAL_LIMIT]]


def parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    if not text.startswith("---\n"):
        return {}, text
    parts = text.split("---\n", 2)
    if len(parts) < 3:
        return {}, text
    meta: dict[str, str] = {}
    for raw_line in parts[1].splitlines():
        line = raw_line.strip()
        if not line or ":" not in line:
            continue
        key, value = line.split(":", 1)
        meta[key.strip()] = value.strip().strip("\"'")
    return meta, parts[2]


def parse_json_object(text: str) -> dict[str, Any]:
    candidates = json_candidates(text)
    last_error: Exception | None = None
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError as exc:
            last_error = exc
            continue
        if isinstance(parsed, dict):
            return parsed

    if last_error is not None:
        log_event("MEMORY", "json_parse_skipped", detail=last_error, chars=len(candidates[0]))
    return {}


def json_candidates(text: str) -> list[str]:
    text = text.strip()
    candidates: list[str] = []

    fenced = extract_fenced_json(text)
    if fenced:
        candidates.append(fenced)

    balanced = first_balanced_json_object(text)
    if balanced:
        candidates.append(balanced)

    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end >= start:
        candidates.append(text[start : end + 1])

    deduped: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        normalized = candidate.strip()
        if normalized and normalized not in seen:
            deduped.append(normalized)
            seen.add(normalized)
    return deduped


def extract_fenced_json(text: str) -> str:
    stripped = text.strip()
    if not stripped.startswith("```"):
        return ""
    lines = stripped.splitlines()
    if len(lines) < 3:
        return ""
    if not lines[-1].strip().startswith("```"):
        return ""
    return "\n".join(lines[1:-1]).strip()


def first_balanced_json_object(text: str) -> str:
    start = text.find("{")
    if start == -1:
        return ""

    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue

        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    return ""


def serialize_context(messages: list[dict[str, Any]], final_text: str) -> str:
    return json.dumps(
        {"messages": messages, "final_text": final_text},
        ensure_ascii=False,
        default=str,
    )[:50000]


def response_text(content: list[Any]) -> str:
    parts: list[str] = []
    for block in content:
        block_type = block.get("type") if isinstance(block, dict) else getattr(block, "type", None)
        if block_type == "text":
            parts.append(block.get("text", "") if isinstance(block, dict) else getattr(block, "text", ""))
    return "\n".join(part for part in parts if part)


def normalize_type(value: str) -> str:
    value = value.strip().lower()
    return value if value in MEMORY_TYPES else "project"


def sanitize_key(value: str) -> str:
    value = value.strip().lower().replace(" ", "_").replace("-", "_")
    value = "".join(char for char in value if char.isalnum() or char == "_")
    return value[:80] or f"memory_{time.time_ns()}"
